"""policylib.py — what the page checkers share (plan 0.4 B.2, B.3.1, B.6, B.7.4, B.8.4).

The profile loaded once; the receipt checked by the consumer; the palette by role (contract variables, literal
tokens, extras, derived variables, font stacks); tiers and waivers. Standard library + PyYAML (through designlib)."""
import os
import re
import stat
import subprocess
from decimal import Decimal

import designlib as dl

PROFILE_FILES = ("site.yaml", "DESIGN.md", "trace-map.yaml", "contrast.yaml", "policy.yaml", "waivers.yaml")
FLOOR_ASSERTIONS = ("A1", "A6", "A10")          # A2's reserved tokens are floor too (checked apart)
DEFAULT_TIERS = {"A2": "blocking", "A3": "blocking", "A4": "waivable", "A5": "blocking", "A7": "blocking",
                 "A8": "waivable", "A9": "blocking", "A11": "advisory", "A13": "blocking"}
H3_BLOCKING = ("html-has-lang", "document-title", "image-alt", "button-name", "link-name", "label")
DEFAULT_AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]
# Every rule tag axe-core 4.14.0 knows, read once from the vendored scripts/vendor/axe-core/axe.js (the `tags` arrays
# of its rules; 147 tags) on 2026-11-10; a policy tag outside this list selects no rule (AST-M15). The vendored files
# are never edited (their SHA-256 values are pinned in check_page.py).
AXE_TAGS = frozenset("""
ACT EN-301-549 EN-301-549v4 EN-9.1.1.1 EN-9.1.2.1 EN-9.1.2.2 EN-9.1.3.1 EN-9.1.3.4 EN-9.1.3.5 EN-9.1.4.1 EN-9.1.4.12
EN-9.1.4.2 EN-9.1.4.3 EN-9.1.4.4 EN-9.2.1.1 EN-9.2.1.3 EN-9.2.2.1 EN-9.2.2.2 EN-9.2.4.1 EN-9.2.4.2 EN-9.2.4.4 EN-9.2.5.3
EN-9.2.5.8 EN-9.3.1.1 EN-9.3.1.2 EN-9.3.3.2 EN-9.4.1.2 RGAA-1.1.1 RGAA-1.1.2 RGAA-1.1.3 RGAA-1.1.4 RGAA-1.1.5 RGAA-1.1.6
RGAA-10.4.2 RGAA-10.6.1 RGAA-10.8.1 RGAA-11.1.1 RGAA-11.13.1 RGAA-11.2.1 RGAA-11.9.1 RGAA-12.7.1 RGAA-12.8.1 RGAA-13.1.2
RGAA-13.8.1 RGAA-13.9.1 RGAA-2.1.1 RGAA-2.2.1 RGAA-3.2.1 RGAA-4.10.1 RGAA-4.3.1 RGAA-5.2.1 RGAA-5.4.1 RGAA-5.7.1 RGAA-5.7.4
RGAA-6.1.5 RGAA-6.2.1 RGAA-7.1.1 RGAA-7.3.2 RGAA-8.2.1 RGAA-8.3.1 RGAA-8.4.1 RGAA-8.5.1 RGAA-8.8.1 RGAA-9.1.3 RGAA-9.2.1
RGAA-9.3.1 RGAA-9.3.3 RGAAv4 TT11.a TT11.b TT12.a TT12.d TT13.a TT13.c TT14.b TT17.a TT2.a TT2.b TT4.a TT5.c TT6.a TT7.a
TT7.b TT8.a TT9.a TTv5 best-practice cat.aria cat.color cat.forms cat.keyboard cat.language cat.name-role-value
cat.parsing cat.semantics cat.sensory-and-visual-cues cat.structure cat.tables cat.text-alternatives cat.time-and-media
deprecated experimental review-item section508 section508.22.a section508.22.f section508.22.g section508.22.i
section508.22.j section508.22.n section508.22.o wcag111 wcag121 wcag122 wcag131 wcag134 wcag135 wcag141 wcag1412 wcag142
wcag143 wcag144 wcag146 wcag211 wcag213 wcag21a wcag21aa wcag221 wcag222 wcag224 wcag22aa wcag241 wcag242 wcag244 wcag249
wcag253 wcag258 wcag2a wcag2a-obsolete wcag2aa wcag2aaa wcag311 wcag312 wcag325 wcag332 wcag411 wcag412
""".split())
# Role kinds an extra may name (policy.extras[].roles): where a prose-only colour may be painted.
EXTRA_ROLES = ("text", "background", "decoration-background", "gradient-stop", "border", "outline",
               "box-shadow", "fill", "stroke", "svg-text")
ROLE_PROPS = ("color", "background-color", "border-color", "outline-color", "box-shadow", "fill", "stroke", "font-family")
KEYWORDS = {"inherit", "initial", "unset", "revert", "revert-layer", "currentcolor", "transparent"}
GENERIC_FAMILIES = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif",
                    "ui-monospace", "ui-rounded", "emoji", "math", "fangsong", "-apple-system", "blinkmacsystemfont"}
# System monospace faces accepted in code roles when policy.fonts.code_roles is system-monospace (never downloaded).
SYSTEM_MONOSPACE = {"ui-monospace", "monospace", "sfmono-regular", "sf mono", "menlo", "monaco", "consolas",
                    "liberation mono", "dejavu sans mono", "courier new", "courier", "cascadia mono", "cascadia code",
                    "roboto mono", "ubuntu mono", "noto sans mono", "lucida console"}


def as_list(x):
    return x if isinstance(x, list) else [x]


def section_off(policy, name):
    v = policy.get(name)
    return isinstance(v, dict) and set(v) == {"off"}


# ------------------------------------------------------------------ the profile

class Profile:
    """The parsed site design folder; bytes read once through a Snapshot."""

    def __init__(self, site_dir, snap=None):
        self.dir = os.path.realpath(site_dir)
        self.snap = snap or dl.Snapshot()
        for name in PROFILE_FILES:
            if not os.path.isfile(os.path.join(self.dir, name)):
                raise dl.InputError("missing %s in the site design folder %s" % (name, self.dir))
        self.site = dl.load_yaml_text(self.snap.text(self.path("site.yaml")), "site.yaml")
        fm, _ = dl.split_front_matter(self.snap.text(self.path("DESIGN.md")))
        self.design = dl.load_yaml_text(fm, "DESIGN.md front matter")
        self.tmap = dl.load_yaml_text(self.snap.text(self.path("trace-map.yaml")), "trace-map.yaml")
        self.policy = dl.load_yaml_text(self.snap.text(self.path("policy.yaml")), "policy.yaml")
        self.waivers = (dl.load_yaml_text(self.snap.text(self.path("waivers.yaml")), "waivers.yaml") or {}).get("waivers") or []
        self.groups = {g: self.design.get(g) or {} for g in dl.GROUPS}

    def path(self, name):
        return os.path.join(self.dir, name)

    def site_path(self, p):
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(self.dir, p))

    def css_paths(self):
        # component stylesheets are CSS of the site too: loaded, traced and hashed into the receipt (AUD-F12)
        paths = []
        for p in as_list(self.site.get("css") or []) + as_list(self.site.get("component_stylesheets") or []):
            if self.site_path(p) not in paths:
                paths.append(self.site_path(p))
        if self.site.get("source") == "design":
            tok = self.site_path(self.site.get("public_tokens", "tokens.css"))
            paths = [tok] + [p for p in paths if p != tok]
        return paths

    def colour(self, token):
        v = self.groups["colors"].get(token)
        if v is None:
            return None
        return dl.parse_colour(dl.resolve(v, self.groups))

    def mode(self):
        return (self.policy.get("scheme") or {}).get("mode") or "light-only"

    def schemes(self):
        return {"light-only": ["light"], "dark-only": ["dark"], "both": ["light", "dark"]}.get(self.mode(), ["light"])

    def tier(self, assertion):
        if assertion in FLOOR_ASSERTIONS:
            return "blocking"
        tiers = self.policy.get("tiers") or {}
        if isinstance(tiers, dict) and not section_off(self.policy, "tiers"):
            return tiers.get(assertion, DEFAULT_TIERS.get(assertion, "blocking"))
        return DEFAULT_TIERS.get(assertion, "blocking")


# ------------------------------------------------------------------ the receipt (consumer side, plan 0.4 B.2)

def folder_files(site):
    out = []
    for dirpath, dirs, files in os.walk(site):
        dirs[:] = sorted(x for x in dirs if x != ".git")
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), site).replace(os.sep, "/")
            if rel != "ready.json":
                out.append(rel)
    return sorted(out)


def plugin_script_hashes():
    scripts = os.path.dirname(os.path.realpath(__file__))
    out = {}
    for dirpath, dirs, files in os.walk(scripts):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            out[os.path.relpath(p, scripts).replace(os.sep, "/")] = dl.sha256_file(p)
    return out


def _git_raw(args, cwd):
    """(exit code, stdout bytes, stderr text); exit 127 when git cannot be run at all. Read-only plumbing only
    (rev-parse, cat-file, check-attr): nothing writes the index or the object store, runs a filter or a hook."""
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, input=b"", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, b"", str(exc)
    return r.returncode, r.stdout, r.stderr.decode("utf-8", "replace").strip()


def _git(args, cwd):
    """(exit code, stdout text stripped, stderr text): _git_raw for commands whose output is text."""
    code, out, err = _git_raw(args, cwd)
    return code, out.decode("utf-8", "replace").strip(), err


def resolve_head(cwd):
    """The commit HEAD names, resolved once (AST-H09): every later rev-parse uses this id, never HEAD again."""
    code, head, _err = _git(["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], cwd)
    return head if code == 0 and dl.GIT_ID.match(head) else None


# Attributes that let the repository change a file's content between the work tree and its blob (R2-M02): a clean or
# smudge filter (an external program), keyword expansion, a re-encoding. Line endings are normalised explicitly instead.
CONTENT_ATTRS = ("filter", "ident", "working-tree-encoding")
RECEIPT_UNCOMMITTED = ("the receipt is not committed, or changed since its commit: the owner commits ready.json after "
                       "check_design.py --issue")


def attributes_problem(cwd, name):
    """None, or why the repository's attributes may change this path's content (git check-attr reads the attribute
    files only; it runs no filter). A Git failure is a problem too: nothing is assumed."""
    code, out, err = _git_raw(["check-attr", "-z"] + list(CONTENT_ATTRS) + ["--", name], cwd)
    if code:
        return "git check-attr failed: %s" % (err or "exit %d" % code)[:200]
    fields = out.decode("utf-8", "replace").split("\0")
    for i in range(0, len(fields) - 2, 3):           # -z: path, attribute, value, each ended by NUL
        if fields[i + 2] not in ("unspecified", "unset"):
            return "the repository's attributes may change this file's content (%s: %s)" % (fields[i + 1], fields[i + 2])
    return None


def committed(cwd, rev, name):
    """(exit code, blob id, bytes) of name at the commit rev, the id from `rev-parse <rev>:./<name>` and the bytes from
    `cat-file blob <id>`, which runs no filter (R2-M02). Nonzero code when the path is not tracked there."""
    code, blob, _err = _git(["rev-parse", "%s:./%s" % (rev, name)], cwd)
    if code or not dl.GIT_ID.match(blob):
        return code or 1, None, None
    code, data, _err = _git_raw(["cat-file", "blob", blob], cwd)
    return (code, blob, data) if not code else (code, blob, None)


def same_content(committed_bytes, checked_bytes):
    """The committed bytes equal the bytes checked after the one explicit normalisation, CRLF to LF on both sides."""
    return committed_bytes is not None and committed_bytes.replace(b"\r\n", b"\n") == checked_bytes.replace(b"\r\n", b"\n")


def face_files(policy):
    fonts = policy.get("fonts") if isinstance(policy.get("fonts"), dict) else {}
    faces = fonts.get("faces") if isinstance(fonts.get("faces"), list) else []
    return sorted(str(f["file"]) for f in faces if isinstance(f, dict) and isinstance(f.get("file"), str))


RECEIPT_KEYS = ("checker", "commit", "css", "fonts", "issued", "plugin_scripts", "profile", "receipt_version")


def receipt_problems(r, profile):
    """Why a parsed receipt is invalid, checked before any file it names is read (AST-H08, AST-M12): a JSON object with
    exactly the receipt's keys, version 1, hex ids and digests, and inventories equal to the folder's files, the CSS
    files of site.yaml and the font files of the policy."""
    if not isinstance(r, dict):
        return ["the receipt is not a JSON object"]
    if sorted(r) != sorted(RECEIPT_KEYS):
        return ["its keys %s are not exactly %s" % (sorted(r), list(RECEIPT_KEYS))]
    p = []
    if type(r["receipt_version"]) is not int or r["receipt_version"] != 1:
        p.append("receipt_version is not 1")
    for k in ("checker", "issued"):
        if not isinstance(r[k], str) or not r[k]:
            p.append("%s is not a non-empty string" % k)
    if not isinstance(r["commit"], str) or not dl.GIT_ID.match(r["commit"]):
        p.append("commit is not a 40- or 64-digit hex id")
    if not isinstance(r["profile"], dict):
        p.append("profile is not a mapping")
    else:
        for name, e in r["profile"].items():
            if not isinstance(e, dict) or sorted(e) != ["blob", "sha256"]:
                p.append("profile[%s] does not hold exactly blob and sha256" % name)
            elif not isinstance(e["blob"], str) or not dl.GIT_ID.match(e["blob"]):
                p.append("profile[%s].blob is not a 40- or 64-digit hex id" % name)
            elif not isinstance(e["sha256"], str) or not dl.SHA256_HEX.match(e["sha256"]):
                p.append("profile[%s].sha256 is not a SHA-256 hex digest" % name)
    for k in ("css", "plugin_scripts", "fonts"):
        if not isinstance(r[k], dict):
            p.append("%s is not a mapping" % k)
            continue
        for name, v in r[k].items():
            if not isinstance(v, str) or not dl.SHA256_HEX.match(v):
                p.append("%s[%s] is not a SHA-256 hex digest" % (k, name))
    if p:
        return p
    files = folder_files(profile.dir)
    if sorted(r["profile"]) != files:
        p.append("the folder's files %s differ from the receipt's %s" % (files, sorted(r["profile"])))
    want_css = sorted(os.path.relpath(x, profile.dir).replace(os.sep, "/") for x in profile.css_paths())
    if sorted(r["css"]) != want_css:
        p.append("the CSS files of site.yaml %s differ from the receipt's %s" % (want_css, sorted(r["css"])))
    if sorted(r["fonts"]) != face_files(profile.policy):
        p.append("the font files of the policy %s differ from the receipt's %s" % (face_files(profile.policy), sorted(r["fonts"])))
    return p


def is_link(path):
    """A symbolic link, a junction or another reparse point (Windows)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return (stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
            or (hasattr(os.path, "isjunction") and os.path.isjunction(path)))


def output_problem(path, site_dir):
    """None, or why an output (a report, a snapshot, a screenshot folder) must not be written there: inside the site
    design folder, links resolved (AST-M04)."""
    if not path:
        return None
    full, site = os.path.realpath(path), os.path.realpath(site_dir)
    try:
        inside = os.path.commonpath([full, site]) == site
    except ValueError:             # another drive
        inside = False
    return "%s lies inside the site design folder %s: outputs never go there" % (path, site) if inside else None


def repository_marker(folder):
    """The nearest .git (folder or file) at or above the folder, or None: whether a repository is there at all,
    decided without running Git."""
    cur = os.path.realpath(folder)
    while True:
        if os.path.exists(os.path.join(cur, ".git")):
            return os.path.join(cur, ".git")
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def verify_receipt(profile, rep, check="RCPT", use_git=True, receipt_sha256=None):
    """True when ready.json is valid and fresh. Order: the receipt's bytes read once and parsed strictly; its schema and
    inventories checked before any file it names is read; every profile file, CSS file, plugin script and font as
    hashed in it; then approval: where a repository is reachable, every profile file's snapshot bytes equal its
    committed bytes at HEAD (resolved once) and at the receipt's commit, and the receipt's bytes as read equal its own
    committed bytes at HEAD (R2-H06), each compared after CRLF-to-LF only, never through the repository's filters (no
    path with a filter, ident or working-tree-encoding attribute is approved; R2-M02); with no repository at all, approval counts
    only when receipt_sha256 (the SHA-256 of the issued ready.json, supplied by the caller) equals the receipt's bytes
    (the CEO's decision of 2026-11-10 on AST-H08). Invalid, stale or missing gives INCOMPLETE items (never a pass)."""
    path = profile.path("ready.json")
    if not os.path.lexists(path):
        rep.add("INCOMPLETE", check, "ready.json", "no receipt: run check_design.py --issue after the owner's commit")
        return False
    if is_link(path) or not os.path.isfile(path):
        rep.add("INCOMPLETE", check, "ready.json", "invalid receipt: ready.json is a link or not a regular file")
        return False
    try:
        raw = profile.snap.read(path)
        r = dl.load_json_strict(raw.decode("utf-8"), "ready.json")
    except (UnicodeDecodeError, dl.ContentError, dl.InputError) as exc:
        rep.add("INCOMPLETE", check, "ready.json", "unreadable receipt: %s" % exc)
        return False
    problems = receipt_problems(r, profile)
    for s in problems:
        rep.add("INCOMPLETE", check, "ready.json", "invalid receipt: " + s)
    if problems:
        return False
    stale = []
    recorded = r["profile"]
    for name, entry in sorted(recorded.items()):
        full = os.path.join(profile.dir, *name.split("/"))
        if not os.path.isfile(full) or profile.snap.digest(full) != entry.get("sha256"):
            stale.append("%s changed since the receipt" % name)
    for rel, sha in sorted(r["css"].items()):
        full = profile.site_path(rel)
        if not os.path.isfile(full) or profile.snap.digest(full) != sha:
            stale.append("CSS %s changed since the receipt" % rel)
    if (r.get("plugin_scripts") or {}) != plugin_script_hashes():
        stale.append("the plugin's scripts differ from those that issued the receipt")
    for rel, sha in sorted(r["fonts"].items()):
        full = profile.site_path(rel)
        if not os.path.isfile(full) or dl.sha256_file(full) != sha:
            stale.append("font %s changed since the receipt" % rel)
    fingerprint = dl.sha256(raw)
    if receipt_sha256 is not None and receipt_sha256 != fingerprint:
        stale.append("the receipt's SHA-256 %s is not the --receipt-sha256 given (%s)" % (fingerprint[:16], receipt_sha256[:16]))
    marker = repository_marker(profile.dir)
    commit = r["commit"]
    if not stale and marker is None:
        if receipt_sha256 is None:
            stale.append("no repository here, so nothing proves this receipt came from check_design.py --issue: approval counts "
                         "only with --receipt-sha256 <the SHA-256 of the issued ready.json, taken where the repository is>")
        else:
            # a staged copy with no repository: plan 0.4 B.2 "approval verified at issue (commit ...), not re-verifiable here"
            rep.add("INFO", check, "ready.json", "approval verified at issue (commit %s), not re-verifiable here: no repository; "
                    "the receipt's SHA-256 equals the --receipt-sha256 given" % commit[:12])
    elif not stale and not use_git:
        stale.append("a repository is present (%s) but --no-git was given: approval not re-verified" % marker)
    elif not stale:
        code, _top, err = _git(["rev-parse", "--show-toplevel"], profile.dir)
        head = resolve_head(profile.dir) if code == 0 else None
        if code != 0:
            stale.append("a repository is present (%s) but Git failed: %s" % (marker, (err or "exit %d" % code)[:200]))
        elif head is None:
            stale.append("the folder is not tracked at HEAD of the repository at %s: it has no commit (a staged copy must sit outside any repository)" % _top)
        else:
            for name, entry in sorted(recorded.items()):
                full = os.path.join(profile.dir, *name.split("/"))
                checked = profile.snap.read(full)            # the bytes every check used (AST-H09)
                attr = attributes_problem(profile.dir, name)
                c0, at_head, head_bytes = committed(profile.dir, head, name)
                c1, at_receipt, receipt_bytes = committed(profile.dir, commit, name)
                if attr:
                    stale.append("%s: %s" % (name, attr))
                elif c0:
                    stale.append("%s is not tracked at HEAD of the repository at %s (a staged copy must sit outside any repository)" % (name, _top))
                elif not same_content(head_bytes, checked):
                    stale.append("%s differs from its version at HEAD (uncommitted, or rolled back)" % name)
                elif c1 or not same_content(receipt_bytes, checked) or entry["blob"] != at_receipt:
                    stale.append("%s differs from its version at the receipt's commit %s" % (name, commit[:12]))
            # the receipt itself, with the CSS, script and font digests it holds: tracked at HEAD and its bytes as read
            # equal its committed blob; the owner's commit of ready.json is the approval (R2-H06, the CEO's decision)
            r_attr = attributes_problem(profile.dir, "ready.json")
            rc, _r_blob, r_bytes = committed(profile.dir, head, "ready.json")
            if r_attr:
                stale.append("ready.json: %s" % r_attr)
            elif rc or not same_content(r_bytes, raw):
                stale.append(RECEIPT_UNCOMMITTED)
    for s in stale:
        rep.add("INCOMPLETE", check, "ready.json", "stale receipt: " + s)
    if not stale:
        rep.add("PASS", check, "ready.json", "fresh receipt of commit %s" % commit[:12])
    return not stale


# ------------------------------------------------------------------ the palette by role

class Palette:
    """Allowed values per role and scheme, from DESIGN.md, trace-map.yaml and policy.yaml (plan 0.4 B.3.1, B.6.1)."""

    def __init__(self, profile):
        self.p = profile
        pol = profile.policy
        self.contract = {}      # variable name -> token, for colour tokens projected as variables
        self.literal = set()    # colour tokens projected as literal values (selector bindings)
        for name, b in (profile.tmap.get("colors") or {}).items():
            if isinstance(b, dict) and "var" in b:
                self.contract[b["var"]] = name
            elif isinstance(b, dict) and "sel" in b:
                self.literal.add(name)
        self.contract_values = {}
        for var, tok in self.contract.items():
            self.contract_values[var] = profile.colour(tok)
        self.roles = {} if section_off(pol, "roles") else (pol.get("roles") or {})
        self.reserved = [] if not isinstance(pol.get("reserved"), list) else list(pol["reserved"])
        self.extras = [] if not isinstance(pol.get("extras"), list) else list(pol["extras"])
        self.derived = {d["name"]: as_list(d.get("roles") or []) for d in (pol.get("derived_vars") or []) if isinstance(d, dict)}
        fonts = pol.get("fonts") or {}
        self.faces = fonts.get("faces") or []
        self.stack_vars = list(fonts.get("stack_vars") or [])
        self.fallback_families = fallback_families(fonts)
        self.code_roles = fonts.get("code_roles", "off")
        self.sets = (pol.get("scheme") or {}).get("sets") or {}

    def tokens_for(self, scheme, role):
        r = (self.roles.get(scheme) or {})
        return list(r.get(role) or [])

    def token_colours(self, tokens):
        out = []
        for t in tokens:
            c = self.p.colour(t)
            if c is not None:
                out.append((t, c))
        return out

    def reserved_match(self, colour, near=False):
        for t, c in self.token_colours(self.reserved):
            if (c.near(colour) if near else c == colour):
                return t
        return None

    def extra_match(self, colour, kinds, near=False):
        """The id of an extra whose base RGB, alpha (one value or a closed range) and roles admit the colour."""
        for e in self.extras:
            if not set(as_list(e.get("roles") or [])) & set(kinds):
                continue
            rgb = e.get("rgb")
            if not rgb or (colour.r, colour.g, colour.b) != tuple(rgb):
                continue
            alpha = e.get("alpha")
            tol = dl.ALPHA_TOL if near else Decimal(0)
            if isinstance(alpha, list):
                lo, hi = Decimal(str(alpha[0])), Decimal(str(alpha[1]))
                if lo - tol <= colour.a <= hi + tol:
                    return e.get("id")
            elif alpha is not None and abs(Decimal(str(alpha)) - colour.a) <= tol:
                return e.get("id")
        return None

    def allowed_colour(self, colour, scheme, role, kinds, near=False):
        """(ok, why) for a resolved colour painted in a role. Reserved tokens are refused first (floor)."""
        r = self.reserved_match(colour, near)
        if r:
            return False, "reserved token %s" % r
        for t, c in self.token_colours(self.tokens_for(scheme, role)):
            if (c.near(colour) if near else c == colour):
                return True, "token %s" % t
        x = self.extra_match(colour, kinds, near)
        if x:
            return True, "extra %s" % x
        return False, "%r is not a %s token of the %s scheme nor an extra in this role" % (colour, role, scheme)

    def face_families(self):
        return [f.get("family", "").lower() for f in self.faces]


def families(value):
    return [f.strip().strip('"\'').lower() for f in dl.split_top(value, ",") if f.strip()]


def fallback_families(fonts):
    """The system fallback families a policy allows in a font-stack variable (the optional key fonts.fallback_families,
    the CEO's decision of 2026-11-11), read as families() reads a stack: unquoted and lowercased. A1 still judges the
    font that actually draws the text."""
    if not isinstance(fonts, dict) or not isinstance(fonts.get("fallback_families"), list):
        return set()
    return {f.strip().strip('"\'').lower() for f in fonts["fallback_families"] if isinstance(f, str) and f.strip()}


def is_system_monospace(value):
    fams = families(value)
    return bool(fams) and all(f in SYSTEM_MONOSPACE for f in fams)


# ------------------------------------------------------------------ waivers (plan 0.4 B.6.2)

def find_waiver(profile, assertion, page_rel, selector, page_sha):
    for w in profile.waivers:
        if (w.get("assertion") == assertion and w.get("page") == page_rel and w.get("selector") == selector
                and w.get("page_sha256") == page_sha and w.get("owner_words") and w.get("reason")):
            return w
    return None


def judged(profile, rep, assertion, path, ok, detail, page_rel=None, page_sha=None, selector=None, **extra):
    """Add one assertion item with its tier and waiver applied; floor assertions are always blocking."""
    tier = profile.tier(assertion)
    if ok:
        return rep.add("PASS", assertion, path, detail, tier=tier, **extra)
    if tier == "advisory":
        return rep.add("WARN", assertion, path, detail, tier=tier, **extra)
    if tier == "waivable" and assertion not in FLOOR_ASSERTIONS:
        w = find_waiver(profile, assertion, page_rel, selector or path, page_sha)
        if w:
            return rep.add("WAIVED", assertion, path, detail + "; waiver %s: %s" % (w.get("id"), w.get("reason")), tier=tier, **extra)
    return rep.add("FAIL", assertion, path, detail, tier=tier, **extra)


# ------------------------------------------------------------------ CSS values

GRADIENT = re.compile(r"(repeating-)?(linear|radial|conic)-gradient\(", re.I)
NUMERIC = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)(px|em|rem|%|vw|vh|vmin|vmax|ch|ex|pt|cm|mm|in|q|pc|deg|grad|rad|turn|s|ms|fr|lh|rlh)?$", re.I)
# Gradient syntax that is not a colour: directions, shapes, sizes, positions, interpolation spaces and hue methods.
GRADIENT_WORDS = {"to", "at", "from", "in", "left", "right", "top", "bottom", "center", "circle", "ellipse", "closest-side",
                  "closest-corner", "farthest-side", "farthest-corner", "srgb", "srgb-linear", "display-p3", "a98-rgb",
                  "prophoto-rgb", "rec2020", "lab", "oklab", "xyz", "xyz-d50", "xyz-d65", "hsl", "hwb", "lch", "oklch",
                  "shorter", "longer", "increasing", "decreasing", "hue"}
NON_COLOUR = {"none", "hidden", "dotted", "dashed", "solid", "double", "groove", "ridge", "inset", "outset", "thin", "medium",
              "thick", "repeat", "repeat-x", "repeat-y", "no-repeat", "space", "round", "center", "top", "bottom", "left", "right",
              "cover", "contain", "fixed", "scroll", "local", "border-box", "padding-box", "content-box", "text", "auto", "/",
              "auto-fill", "!important"}


def parse_gradients(value):
    """Each gradient function of a value, in order: {'fn', 'interp', 'stops'}: the interpolation space named after `in`
    (None when absent) and every stop token with positions and geometry removed. No stop is dropped for its spelling
    (named colours, hsl(), oklch(), color(), color-mix() and var() stay), so an unreadable stop is seen (AST-H07)."""
    out = []
    for m in GRADIENT.finditer(value):
        start = m.end()
        level, i = 1, start
        while i < len(value) and level:
            level += {"(": 1, ")": -1}.get(value[i], 0)
            i += 1
        inner = value[start:i - 1]
        interp, stops = None, []
        for part in dl.split_top(inner, ","):
            toks = [t.strip() for t in dl.split_top(part.strip(), " ") if t.strip()]
            low = [t.lower() for t in toks]
            if "in" in low and low.index("in") + 1 < len(low):
                interp = low[low.index("in") + 1]
            for tok, lt in zip(toks, low):
                if lt in GRADIENT_WORDS or NUMERIC.match(lt) or lt.startswith(("calc(", "min(", "max(", "clamp(")):
                    continue
                stops.append(tok)
        out.append({"fn": m.group(0)[:-1].lower(), "interp": interp, "stops": stops})
    return out


def gradient_stops(value):
    """Every colour stop of the gradient functions of a value (see parse_gradients)."""
    return [s for g in parse_gradients(value) for s in g["stops"]]


def is_colourish(part):
    """A shorthand component that can only be a colour: not a length, number, keyword of width, style, position,
    size, repeat or box, not an image. Named colours count (and fail as raw values)."""
    low = part.strip().lower()
    if not low or low in NON_COLOUR or NUMERIC.match(low):
        return False
    if low.startswith(("url(", "image-set(", "calc(", "min(", "max(", "clamp(", "env(", "attr(")):
        return False
    if GRADIENT.match(low):
        return False
    return True


def strip_gradients(value):
    out, i = "", 0
    for m in GRADIENT.finditer(value):
        out += value[i:m.start()]
        level, j = 1, m.end()
        while j < len(value) and level:
            level += {"(": 1, ")": -1}.get(value[j], 0)
            j += 1
        i = j
    return out + value[i:]
