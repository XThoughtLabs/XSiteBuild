"""Tests of check_css.py (plan 0.4 B.9, check_css.py list)."""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import sites  # noqa: E402

CC = os.path.join(sites.SCRIPTS, "check_css.py")


def run(d, b, *extra):
    j = os.path.join(os.path.dirname(d), "css-report.json")
    r = subprocess.run([sys.executable, "-I", "-B", CC, "--site", d, "--bundle", b, "--page", "index.html", "--json", j] + list(extra),
                       capture_output=True, text=True, timeout=120)
    items = json.load(open(j))["items"] if os.path.exists(j) else []
    return r.returncode, items, r.stdout + r.stderr


def page(style="", body="<p>text</p>", head=""):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>t</title>'
            '<link rel="stylesheet" href="x.css">%s<style>%s</style></head><body>%s</body></html>' % (head, style, body))


@pytest.fixture
def X(tmp_path):
    d = sites.build_x(tmp_path)
    sites.issue(d)
    return d


def fails(items, word=None):
    return [i for i in items if i["status"] == "FAIL" and (word is None or word in i["detail"])]


@pytest.mark.parametrize("style,ok", [
    (".a { color: var(--ink); }", True),
    (".a { color: #1a1a2e; }", False),                       # raw hex, even of a token
    (".a { border-color: var(--accent); }", False),          # a token of another role
    (".a { background-color: var(--paper); }", True),
    (".a { color: var(--old-accent); }", False),             # reserved
    (".a { box-shadow: 0 1px 2px rgba(26, 26, 46, 0.08); }", True),   # an extra in its role
    (".a { background-color: rgba(26, 26, 46, 0.08); }", False),      # the same extra outside its role
    (".a { border: 1px solid rgba(26, 26, 46, 0.2); }", True),        # border extra in a shorthand
    (".a { border: 1px solid #ff0000; }", False),
    (".a { color: var(--ink, #1a1a2e); }", False),           # hard-coded fallback
    (".a { color: currentColor; border-color: currentColor; }", True),
    (".a { color: transparent; }", True),
    (":root { --ink: #000000; } .a { color: var(--ink); }", False),   # redefines a contract variable
    (":root { --ink: #1a1a2e; }", True),                    # restated with its own value
    (".a { --mine: #ff0000; color: var(--mine); }", False),  # a page variable resolves to a raw value
    (".a { --mine: var(--ink); color: var(--mine); }", True),
    (".a { color: color-mix(in srgb, var(--ink) 50%, var(--paper)); }", False),
    (".a { color: color-mix(in srgb, var(--ink) 100%, var(--paper) 0%); }", True),
    (".a { background: linear-gradient(var(--paper), #ff0000); }", False),
    (".a { font-family: \"Inter Test\", sans-serif; }", True),
    (".a { font-family: Georgia, serif; }", False),
    ("code { font-family: ui-monospace, Menlo, monospace; }", True),
    ("p { font-family: ui-monospace, Menlo, monospace; }", False),
    (".a { fill: var(--accent); stroke: var(--ink); }", True),
    (".a { fill: #00ff00; }", False),
    (".a { border: var(--gap) solid var(--ink); }", True),     # a spacing variable in a shorthand is not a colour
    (".a { --w: 2px; border: var(--w) solid var(--ink); }", True),
    (".a { border: 1px solid navy; }", False),                  # a named colour is a raw value
    (".a { -webkit-text-fill-color: #00ff00; }", False),         # text paints beside color
    (".a { text-decoration: underline var(--accent); }", True),
    (".a { text-shadow: 0 1px 2px #ff0000; }", False),
    ('.q::before { content: "{"; color: var(--ink); }', True),  # a brace inside a string is not a block
], ids=lambda x: x if isinstance(x, str) else None)
def test_declarations(X, style, ok):
    b = sites.bundle(X, "p", page(style))
    code, items, out = run(X, b)
    assert (code == 0) is ok, out
    if not ok:
        assert code == 1 and fails(items), out


def test_style_attribute_and_unlinked_sheet(X):
    b = sites.bundle(X, "p", page(body='<p style="color: #ff0000">x</p>'), files={"unused.css": ".z { color: #00ff00; }"})
    code, items, out = run(X, b)
    assert code == 1 and fails(items, "#ff0000") and not [i for i in items if "unused.css" in i["path"]], out


def test_linked_own_sheet_is_checked_and_site_css_is_approved(X):
    b = sites.bundle(X, "p", page(head='<link rel="stylesheet" href="own.css">'), files={"own.css": ".z { color: #00ff00; }"})
    code, items, out = run(X, b)
    assert code == 1 and [i for i in items if "own.css" in i["path"] and i["status"] == "FAIL"], out
    assert [i for i in items if i["status"] == "INFO" and "approved site stylesheet" in i["detail"]], out


def test_import_incomplete(X):
    b = sites.bundle(X, "p", page('@import url("x.css");\n.a { color: var(--ink); }'))
    code, items, out = run(X, b)
    assert code == 3 and "@import" in out, out


def test_literal_token(tmp_path):
    d = sites.build_x(tmp_path)
    sites.edit(os.path.join(d, "trace-map.yaml"), "  paper: {var: --paper}", "  paper: {sel: .card, prop: background}")
    sites.issue(d)
    b = sites.bundle(d, "p", page(".a { background-color: #fffdf7; }"))
    assert run(d, b)[0] == 0
    b = sites.bundle(d, "q", page(".a { border-color: #fffdf7; }"))
    code, items, out = run(d, b)
    assert code == 1 and fails(items, "raw border-color"), out


def test_derived_and_stack_variables(tmp_path):
    d = sites.build_x(tmp_path)
    sites.edit(os.path.join(d, "policy.yaml"), "derived_vars: []", "derived_vars:\n- {name: --shadow, roles: [box-shadow]}")
    sites.edit(os.path.join(d, "policy.yaml"), "stack_vars: []", "stack_vars: [--font]")
    sites.edit(os.path.join(d, "../site/x.css"), "--measure: 680px;", "--measure: 680px; --shadow: 0 1px 2px rgba(26, 26, 46, 0.08); --font: \"Inter Test\", sans-serif;")
    sites.issue(d)
    b = sites.bundle(d, "p", page(".a { box-shadow: var(--shadow); font-family: var(--font); }"))
    assert run(d, b)[0] == 0
    b = sites.bundle(d, "q", page(".a { color: var(--shadow); }"))
    code, items, out = run(d, b)
    assert code == 1 and fails(items, "not allowed in color"), out


def test_missing_and_stale_receipt(tmp_path):
    d = sites.build_x(tmp_path)
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    code, items, out = run(d, b)
    assert code == 3 and "no receipt" in out, out
    sites.issue(d)
    assert run(d, b)[0] == 0
    sites.edit(os.path.join(d, "../site/x.css"), "--gap: 20px;", "--gap: 21px;")
    code, items, out = run(d, b)
    assert code == 3 and "CSS ../site/x.css changed" in out, out


def test_policy_and_receipt_edited_together(tmp_path):
    d = sites.build_x(tmp_path)
    sites.issue(d)
    sites.edit(os.path.join(d, "policy.yaml"), "reserved:\n- old-accent", "reserved: []")
    r = json.load(open(os.path.join(d, "ready.json")))
    r["profile"]["policy.yaml"]["sha256"] = sites.hashlib.sha256(open(os.path.join(d, "policy.yaml"), "rb").read()).hexdigest()
    open(os.path.join(d, "ready.json"), "w").write(json.dumps(r))
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    code, items, out = run(d, b)
    assert code == 3 and "policy.yaml differs from its version at HEAD" in out, out
    code, items, out = run(d, b, "--no-git")             # a repository is present: --no-git never passes (R1-09)
    assert code == 3 and "--no-git was given" in out, out


def test_rollback_of_policy_and_receipt(tmp_path):
    d = sites.build_x(tmp_path)
    sites.issue(d)
    v1 = {f: open(os.path.join(d, f), "rb").read() for f in ("policy.yaml", "ready.json")}
    sites.edit(os.path.join(d, "policy.yaml"), "  A3: blocking", "  A3: advisory")
    sites.issue(d)
    for f, data in v1.items():
        open(os.path.join(d, f), "wb").write(data)
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    code, items, out = run(d, b)
    assert code == 3 and "policy.yaml differs from its version at HEAD" in out, out


def test_git_failure_is_not_a_missing_repository(tmp_path):
    d = sites.build_x(tmp_path)
    sites.issue(d)
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    j = os.path.join(os.path.dirname(d), "r.json")
    env = dict(os.environ, PATH="/nonexistent")
    r = subprocess.run([sys.executable, "-I", "-B", CC, "--site", d, "--bundle", b, "--page", "index.html", "--json", j],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 3 and "Git failed" in r.stdout, r.stdout
    if hasattr(os, "geteuid") and os.geteuid() == 0:     # a repository owned by another user: Git refuses it
        subprocess.run(["chown", "-R", "claude", d], check=True)
        code, items, out = run(d, b)
        assert code == 3 and "Git failed" in out and "dubious ownership" in out, out


def test_profile_change_without_git(tmp_path):
    import shutil
    d = sites.build_x(tmp_path / "src")
    sites.issue(d)
    staged = tmp_path / "staged" / "X"                    # a staged copy without the repository, as in the cloud
    shutil.copytree(os.path.dirname(d), staged, ignore=shutil.ignore_patterns(".git"))
    sd = str(staged / "design")
    b = sites.bundle(sd, "p", page(".a { color: var(--ink); }"))
    fp = sites.hashlib.sha256(open(os.path.join(d, "ready.json"), "rb").read()).hexdigest()   # taken where the repository is
    code, items, out = run(sd, b, "--receipt-sha256", fp)
    assert code == 0 and "not re-verifiable here: no repository" in out, out
    sites.edit(os.path.join(sd, "README.md"), "synthetic", "synthetic, edited")
    code, items, out = run(sd, b, "--receipt-sha256", fp)
    assert code == 3 and "README.md changed since the receipt" in out, out


# ------------------------------------------------------------------ added after the outside audit, round 1

def _staged_copy(tmp_path):
    import shutil
    d = sites.build_x(tmp_path / "src")
    sites.issue(d)
    staged = tmp_path / "staged" / "X"
    shutil.copytree(os.path.dirname(d), staged, ignore=shutil.ignore_patterns(".git"))
    sd = str(staged / "design")
    fp = sites.hashlib.sha256(open(os.path.join(d, "ready.json"), "rb").read()).hexdigest()
    return d, sd, fp, sites.bundle(sd, "p", page(".a { color: var(--ink); }"))


def test_repository_free_copy_needs_the_receipt_fingerprint(tmp_path):
    """AST-H08, the CEO's decision: without a repository, approval counts only with the real receipt's SHA-256."""
    d, sd, fp, b = _staged_copy(tmp_path)
    code, items, out = run(sd, b)
    assert code == 3 and "approval counts only with --receipt-sha256" in out, out
    code, items, out = run(sd, b, "--receipt-sha256", "0" * 64)
    assert code == 3 and "is not the --receipt-sha256 given" in out, out
    code, items, out = run(sd, b, "--receipt-sha256", fp.upper())        # hex in either case
    assert code == 0, out


def test_hand_written_receipt_on_a_repository_free_copy(tmp_path):
    """AST-H08 (HQ's probe 2): a receipt without commit or blobs is refused by its schema, fingerprint or not."""
    d, sd, fp, b = _staged_copy(tmp_path)
    r = json.load(open(os.path.join(sd, "ready.json")))
    del r["commit"]
    for e in r["profile"].values():
        del e["blob"]
    open(os.path.join(sd, "ready.json"), "w").write(json.dumps(r))
    forged = sites.hashlib.sha256(open(os.path.join(sd, "ready.json"), "rb").read()).hexdigest()
    code, items, out = run(sd, b, "--receipt-sha256", forged)
    assert code == 3 and "invalid receipt" in out and "approval verified" not in out, out


@pytest.mark.parametrize("content,word", [
    ("[]", "not a JSON object"),
    ('{"receipt_version": 1, "receipt_version": 1}', "duplicate key"),
    (None, "receipt_version is not 1"),
    ("PROFILE", "the folder's files"),
    ("FONT", "the font files of the policy"),
], ids=["array", "duplicate key", "version", "unknown profile file", "font outside the policy"])
def test_receipt_schema_before_any_file_is_read(tmp_path, content, word):
    """AST-M12, AST-H08: the receipt's shape and inventories are checked before any file it names is read."""
    d = sites.build_x(tmp_path)
    sites.issue(d)
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    path = os.path.join(d, "ready.json")
    r = json.load(open(path))
    if content is None:
        r["receipt_version"] = 2
        content = json.dumps(r)
    elif content == "PROFILE":       # a named file outside the folder, too large to read: reading it would be an ERROR
        open(os.path.join(str(tmp_path), "outside.txt"), "wb").write(b"x" * 1_000_100)
        r["profile"]["../../outside.txt"] = dict(r["profile"]["README.md"])
        content = json.dumps(r)
    elif content == "FONT":
        r["fonts"]["../../elsewhere.ttf"] = "0" * 64
        content = json.dumps(r)
    open(path, "w").write(content)
    code, items, out = run(d, b)
    assert code == 3 and word in out and "INTERNAL" not in out, out


def test_a_missing_blob_is_refused_with_git(tmp_path):
    """AST-H09: blob is required in every profile entry."""
    d = sites.build_x(tmp_path)
    sites.issue(d)
    r = json.load(open(os.path.join(d, "ready.json")))
    del r["profile"]["policy.yaml"]["blob"]
    open(os.path.join(d, "ready.json"), "w").write(json.dumps(r))
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    code, items, out = run(d, b)
    assert code == 3 and "does not hold exactly blob and sha256" in out, out


def test_receipt_fingerprint_option_is_checked(tmp_path):
    d = sites.build_x(tmp_path)
    b = sites.bundle(d, "p", page())
    code, items, out = run(d, b, "--receipt-sha256", "xyz")
    assert code == 2 and "64 hex digits" in out, out


def test_consumer_hashes_the_bytes_it_checked(tmp_path, monkeypatch, capsys):
    """AST-H09 (consumer side): the snapshot holds a policy that is not at HEAD, its SHA-256 written into the receipt,
    and the committed bytes are back on disk before Git looks: the receipt is stale."""
    import check_css
    import designlib as dl
    d = sites.build_x(tmp_path)
    sites.issue(d)
    committed = open(os.path.join(d, "policy.yaml"), "rb").read()
    sites.edit(os.path.join(d, "policy.yaml"), "  A3: blocking", "  A3: advisory")
    r = json.load(open(os.path.join(d, "ready.json")))
    r["profile"]["policy.yaml"]["sha256"] = sites.hashlib.sha256(open(os.path.join(d, "policy.yaml"), "rb").read()).hexdigest()
    open(os.path.join(d, "ready.json"), "w").write(json.dumps(r, indent=1, sort_keys=True))
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    real = dl.Snapshot.read

    def read(self, path):
        data = real(self, path)
        if path.endswith("policy.yaml"):
            open(path, "wb").write(committed)
        return data
    monkeypatch.setattr(dl.Snapshot, "read", read)
    code = check_css.main(["--site", d, "--bundle", b, "--page", "index.html"])
    out = capsys.readouterr().out
    assert code == 3 and "policy.yaml differs from its version at HEAD" in out, out


# ---- the shared guard and resolver (AST-H01, AUD-F03)

@pytest.mark.parametrize("files,href", [({".env/s.css": "AUDIT_SECRET_SENTINEL"}, ".env/s.css"),
                                        ({"keys/a.pem": "AUDIT_SECRET_SENTINEL"}, "keys/a.pem"),
                                        ({"copy.css": "README"}, "copy.css")], ids=[".env folder", "pem", "profile bytes"])
def test_linked_files_pass_the_guard_and_are_never_quoted(X, files, href):
    """AST-H01: one guard for both checkers; a refused file is an ERROR and its bytes never appear in a finding."""
    if files.get("copy.css") == "README":         # a copy of the site design folder's README, by its bytes
        files = {"copy.css": open(os.path.join(X, "README.md"), "rb").read()}
    b = sites.bundle(X, "g", page(head='<link rel="stylesheet" href="%s">' % href), files=files)
    code, items, out = run(X, b)
    assert code == 2 and "bundle refused" in out and "AUDIT_SECRET_SENTINEL" not in out + json.dumps(items), out


def test_percent_encoded_link_names_the_file_the_browser_gets(X):
    """AUD-F03(2): %6fwn.css is own.css for the browser and the server; a literal file of that name is never read."""
    site_css = open(os.path.join(os.path.dirname(X), "site", "x.css"), encoding="utf-8").read()
    b = sites.bundle(X, "pct", page(head='<link rel="stylesheet" href="%6fwn.css">'),
                     files={"own.css": ".z { color: #00ff00; }", "%6fwn.css": site_css})
    code, items, out = run(X, b)
    assert code == 1 and [i for i in items if "own.css" in i["path"] and i["status"] == "FAIL"], out


def test_first_of_duplicate_style_attributes_wins(X):
    """AUD-F03(1)."""
    b = sites.bundle(X, "dup", page(body='<p style="color:#ff0000" style="color:var(--ink)">x</p>'))
    code, items, out = run(X, b)
    assert code == 1 and fails(items, "#ff0000"), out


# ---- variables, fallbacks, shorthands, frames (AST-M10, AST-M11, AUD-F05)

@pytest.mark.parametrize("style,word", [
    ("p { --tone: #ff0000; color: var(--tone); } .unused { --tone: var(--ink); }", "#ff0000"),
    ("p { font: 16px Georgia, serif; }", "Georgia"),
    ("p { font: italic 700 16px/1.5 Georgia; }", "Georgia"),
    (".a { color: var(--ink, var(--old-accent)); }", "reserved"),
    (".a { color: var(--ink, var(--ink, #ff0000)); }", "hard-coded fallback"),
    (":root { --a: var(--a); } .a { color: var(--a); }", "variable cycle"),
    (":root { --gap: #ff0000; } .a { border: 1px solid var(--gap); }", "certified variable --gap"),
    (":root { --measure: 1px; }", "certified variable --measure"),
], ids=["every definition", "font shorthand", "font shorthand with line height", "reserved fallback", "nested hard-coded fallback",
        "cycle", "non-colour variable redefined", "certified variable redefined"])
def test_page_variables_fallbacks_and_shorthands(X, style, word):
    b = sites.bundle(X, "v", page(style))
    code, items, out = run(X, b)
    assert code == 1 and fails(items, word) and "INTERNAL" not in out, out


def test_font_stack_variable_cannot_be_redefined(tmp_path):
    """AUD-F05(1): a font-stack variable of the policy is certified: a page may not redefine it."""
    d = sites.build_x(tmp_path)
    sites.edit(os.path.join(d, "policy.yaml"), "stack_vars: []", "stack_vars: [--font]")
    sites.edit(os.path.join(d, "../site/x.css"), "--measure: 680px;", "--measure: 680px; --font: \"Inter Test\", sans-serif;")
    sites.issue(d)
    b = sites.bundle(d, "s", page(':root { --font: Georgia, serif; } p { font-family: var(--font); }'))
    code, items, out = run(d, b)
    assert code == 1 and fails(items, "certified variable --font"), out
    b = sites.bundle(d, "t", page(':root { --font: "Inter Test", sans-serif; } p { font-family: var(--font); }'))
    assert run(d, b)[0] == 0          # control: restated with its approved value


def test_certified_variable_restated_with_a_function_value(X):
    """HQ's V3: the certified-variable check compares a value whose commas sit inside a function (dl.same) and fails it,
    never an internal error."""
    b = sites.bundle(X, "cb", page(":root { --gap: cubic-bezier(.2,.7,.2,1); }"))
    code, items, out = run(X, b)
    assert code == 1 and fails(items, "certified variable --gap") and "INTERNAL" not in out, out


@pytest.mark.parametrize("href", ["a%00b.css", "a%1fb.css"], ids=["NUL", "unit separator"])
def test_control_character_in_a_link_is_outside_the_bundle(X, href):
    """HQ's C5: a link whose percent-decoded path holds a control character is the A10 failure, never INTERNAL."""
    b = sites.bundle(X, "cc", page(head='<link rel="stylesheet" href="%s">' % href))
    code, items, out = run(X, b)
    assert code == 1 and fails(items, "stylesheet outside the bundle") and "INTERNAL" not in out, out


def chain(n):
    """HQ's probe C6: page variables --v0 ... --vn, each but the last defined twice, so --v0 has 2^n expansions."""
    rules = " ".join(".a%d { --v%d: var(--v%d); } .b%d { --v%d: var(--v%d); }" % (i, i, i + 1, i, i, i + 1) for i in range(n))
    return rules + " .a%d { --v%d: var(--ink); } .probe { color: var(--v0); }" % (n, n)


@pytest.mark.parametrize("n", [8, 20])
def test_variable_definitions_have_a_budget(X, n):
    """HQ's C6: at most 64 definitions are expanded for one declaration; more give one INCOMPLETE. The report stays
    small (a count, not a time): n=20 would otherwise expand 2^20 definitions."""
    b = sites.bundle(X, "ch%d" % n, page(chain(n), body='<p class="probe">t</p>'))
    code, items, out = run(X, b)
    budget = [i for i in items if i["status"] == "INCOMPLETE" and "too many variable definitions" in i["detail"]]
    assert code == 3 and len(budget) == 1 and len(items) <= 64 + 10, (code, len(items), out[-2000:])


def test_report_keeps_at_most_5000_items_failures_first(X):
    """HQ's C6: like check_page.py, the report holds at most 5,000 items, the truncation item included, failures first."""
    style = " ".join(".c%d { color: var(--ink); }" % i for i in range(5100)) + " .z { color: #ff0000; }"
    b = sites.bundle(X, "many", page(style))
    code, items, out = run(X, b)
    assert len(items) == 5000 and fails(items, "#ff0000"), (len(items), out[-1000:])
    assert [i for i in items if i["status"] == "INCOMPLETE" and i["check"] == "BUDGET" and "truncated" in i["detail"]] and code == 1, out[-1000:]


@pytest.mark.parametrize("style,want", [
    (".a { font: 16px/1.5 var(--font); }", 0),
    (".a { font: italic 700 16px var(--font); }", 0),
    (".a { font: 16px/1.5 var(--font, var(--font)); }", 3),       # a fallback: not exactly one var()
    (".a { font: var(--size) var(--font); }", 3),                   # another var() in the shorthand
    (".a { font: 16px/var(--lh) var(--font); }", 3),                # another var() in the line height
    (".a { --other: \"Inter Test\", sans-serif; font: 16px var(--other); }", 3),   # not a font-stack variable of the policy
], ids=["stack variable", "stack variable after style and weight", "with a fallback", "two variables", "variable line height", "page variable"])
def test_font_shorthand_with_a_font_stack_variable(tmp_path, style, want):
    """HQ's C7: a font shorthand whose family is exactly one approved font-stack variable is checked as font-family is;
    any other var() in the shorthand stays INCOMPLETE."""
    d = sites.build_x(tmp_path)
    sites.edit(os.path.join(d, "policy.yaml"), "stack_vars: []", "stack_vars: [--font]")
    sites.edit(os.path.join(d, "../site/x.css"), "--measure: 680px;", "--measure: 680px; --font: \"Inter Test\", sans-serif;")
    sites.issue(d)
    b = sites.bundle(d, "fs", page(style))
    code, items, out = run(d, b)
    assert code == want, out


def test_frame_documents_are_checked(X):
    """AST-M11: the styles of a same-bundle frame document (src and srcdoc) are checked too."""
    inner = '<!doctype html><html lang="en"><head><title>f</title></head><body><p style="color: #00ff00">in a frame</p></body></html>'
    b = sites.bundle(X, "fr", page(body='<p>t</p><iframe title="f" src="inner.html"></iframe>'), files={"inner.html": inner})
    code, items, out = run(X, b)
    assert code == 1 and fails(items, "#00ff00"), out
    b = sites.bundle(X, "sd", page(body='<p>t</p><iframe title="f" srcdoc="&lt;p style=&quot;color: #0000ff&quot;&gt;x&lt;/p&gt;"></iframe>'))
    code, items, out = run(X, b)
    assert code == 1 and fails(items, "#0000ff"), out


# ---- gradients and SVG paints (AST-H07, AUD-F02), code roles in style attributes (AUD-F10)

@pytest.mark.parametrize("style,body", [
    (".a { background: linear-gradient(var(--paper), red); }", "<p>t</p>"),
    (".a { background-image: linear-gradient(var(--paper), hsl(0, 100%, 50%)); }", "<p>t</p>"),
    ("", '<p>t</p><svg width="9" height="9"><defs><linearGradient id="g"><stop offset="0" stop-color="#9a3412"/></linearGradient></defs>'
         '<rect width="9" height="9" fill="url(#g)"/></svg>'),
    ("", '<p>t</p><svg width="9" height="9"><rect width="9" height="9" fill="#00ff00"/></svg>'),
    ("stop { stop-color: #ff0000; }", "<p>t</p>"),
], ids=["named stop", "hsl stop", "svg stop attribute", "svg fill attribute", "stop-color property"])
def test_every_gradient_stop_and_svg_paint_is_judged(X, style, body):
    b = sites.bundle(X, "gr", page(style, body=body))
    code, items, out = run(X, b)
    assert code == 1 and fails(items), out


def test_svg_paint_server_reference_passes(X):
    """Control: fill="url(#g)" names a paint server in the document; its stops are judged where they are declared."""
    body = ('<p>t</p><svg width="9" height="9"><defs><linearGradient id="g"><stop offset="0" stop-color="var(--paper)"/>'
            '</linearGradient></defs><rect width="9" height="9" fill="url(#g)"/></svg>')
    b = sites.bundle(X, "ps", page(body=body))
    code, items, out = run(X, b)
    assert not fails(items, "url(#g)"), out


def test_code_style_attribute_is_a_code_role(X):
    """AUD-F10: style="" on <code> is checked with the tag as its selector."""
    b = sites.bundle(X, "code", page(body='<p><code style="font-family: ui-monospace, monospace">x</code></p>'))
    code, items, out = run(X, b)
    assert code == 0, out


# ---- report mode (AST-L02), outputs (AST-M03, AST-M04)

def test_report_reads_every_colour_form_and_keyframes(tmp_path):
    d = sites.build_x(tmp_path)
    css = tmp_path / "r.css"
    css.write_text(".a { color: navy; border: 1px solid hsl(0 0% 50%); background: linear-gradient(red, var(--x)); }\n"
                   "@keyframes k { from { color: #123456; } }\n")
    r = subprocess.run([sys.executable, "-I", "-B", CC, "--site", d, "--report", str(css)], capture_output=True, text=True)
    for word in ("hard-coded navy", "hard-coded hsl(0 0% 50%)", "hard-coded red", "hard-coded #123456", "4 hard-coded values"):
        assert word in r.stdout, (word, r.stdout)


def test_outputs_and_their_errors(tmp_path):
    d = sites.build_x(tmp_path)
    css = os.path.join(os.path.dirname(d), "site", "x.css")
    r = subprocess.run([sys.executable, "-I", "-B", CC, "--site", d, "--report", css, "--json", os.path.join(d, "r.json")], capture_output=True, text=True)
    assert r.returncode == 2 and "inside the site design folder" in r.stdout and not os.path.exists(os.path.join(d, "r.json")), r.stdout
    r = subprocess.run([sys.executable, "-I", "-B", CC, "--site", d, "--report", css, "--json", str(tmp_path / "no" / "r.json")], capture_output=True, text=True)
    assert r.returncode == 2 and "could not be written" in r.stdout and "Traceback" not in r.stderr, r.stdout + r.stderr


def test_report_mode(tmp_path):
    d = sites.build_x(tmp_path)
    css = os.path.join(os.path.dirname(d), "site", "x.css")
    r = subprocess.run([sys.executable, "-I", "-B", CC, "--site", d, "--report", css], capture_output=True, text=True)
    assert r.returncode == 0 and "hard-coded #fffdf7" in r.stdout and "hard-coded values in role-bearing properties" in r.stdout


def test_reserved_variable_is_floor(X):
    b = sites.bundle(X, "r", page(".a { color: var(--old-accent); }"))
    code, items, out = run(X, b)
    assert code == 1 and [i for i in fails(items) if i.get("floor")], out


def test_authored_alpha_is_exact(X):
    b = sites.bundle(X, "al", page(".a { border: 1px solid rgba(26, 26, 46, 0.204); }"))
    code, items, out = run(X, b)
    assert code == 1 and fails(items, "raw border-color"), out


def test_changed_plugin_script_or_font_makes_receipt_stale(tmp_path):
    import shutil
    plugin = tmp_path / "plugin"
    shutil.copytree(os.path.dirname(sites.SCRIPTS), plugin, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    d = sites.build_x(tmp_path / "s")
    sites.git(d, "init", "-q")
    sites.git(d, "add", "-A")
    sites.git(d, "commit", "-qm", "p")
    cd = str(plugin / "scripts" / "check_design.py")
    assert subprocess.run([sys.executable, "-I", "-B", cd, "--site", d, "--issue"], capture_output=True).returncode == 0
    sites.commit_receipt(d)                               # the owner commits the receipt (R2-H06)
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    cc = [sys.executable, "-I", "-B", str(plugin / "scripts" / "check_css.py"), "--site", d, "--bundle", b, "--page", "index.html"]
    assert subprocess.run(cc, capture_output=True).returncode == 0
    with open(plugin / "scripts" / "csslite.py", "ab") as fh:     # bytes: the same on every platform
        fh.write(b"\n# changed\n")
    r = subprocess.run(cc, capture_output=True, text=True)
    assert r.returncode == 3 and "plugin's scripts differ" in r.stdout, r.stdout
    with open(plugin / "scripts" / "csslite.py", "rb") as fh:
        data = fh.read().replace(b"\n# changed\n", b"")
    with open(plugin / "scripts" / "csslite.py", "wb") as fh:
        fh.write(data)
    assert subprocess.run(cc, capture_output=True).returncode == 0
    with open(os.path.join(os.path.dirname(d), "site", "fonts", "x.ttf"), "ab") as fh:
        fh.write(b"\0")
    r = subprocess.run(cc, capture_output=True, text=True)
    assert r.returncode == 3 and "font ../site/fonts/x.ttf changed" in r.stdout, r.stdout


def test_waiver_needs_the_page_hash(tmp_path):
    sys.path.insert(0, sites.SCRIPTS)
    import policylib as pl
    d = sites.build_x(tmp_path)
    open(os.path.join(d, "waivers.yaml"), "w").write(
        "waivers:\n  - {id: w, assertion: A4, page: a.html, selector: div, page_sha256: abc, reason: r, owner_words: w, date: '2026-11-10'}\n")
    p = pl.Profile(d)
    assert pl.find_waiver(p, "A4", "a.html", "div", "abc") and not pl.find_waiver(p, "A4", "a.html", "div", "abd")
    assert not pl.find_waiver(p, "A8", "a.html", "div", "abc") and not pl.find_waiver(p, "A4", "b.html", "div", "abc")


def test_palette_refuses_reserved_first(tmp_path):
    sys.path.insert(0, sites.SCRIPTS)
    import designlib as dl
    import policylib as pl
    d = sites.build_x(tmp_path)
    sites.edit(os.path.join(d, "policy.yaml"), "    - accent\n    - paper\n    background-color:", "    - accent\n    - paper\n    - old-accent\n    background-color:")
    pal = pl.Palette(pl.Profile(d))
    ok, why = pal.allowed_colour(dl.parse_colour("#9a3412"), "light", "color", ["text"])
    assert not ok and why.startswith("reserved"), why


def test_policy_committed_but_receipt_hand_edited(tmp_path):
    d = sites.build_x(tmp_path)
    sites.issue(d)
    sites.edit(os.path.join(d, "policy.yaml"), "  A3: blocking", "  A3: advisory")
    sites.git(d, "commit", "-qam", "policy changed, receipt not reissued")
    r = json.load(open(os.path.join(d, "ready.json")))
    r["profile"]["policy.yaml"]["sha256"] = sites.hashlib.sha256(open(os.path.join(d, "policy.yaml"), "rb").read()).hexdigest()
    open(os.path.join(d, "ready.json"), "w").write(json.dumps(r))
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    code, items, out = run(d, b)
    assert code == 3 and "differs from its version at the receipt's commit" in out, out


def test_staged_copy_inside_another_repository(tmp_path):
    import shutil
    d = sites.build_x(tmp_path / "src")
    sites.issue(d)
    other = tmp_path / "other"
    other.mkdir()
    sites.git(str(other), "init", "-q")
    (other / "unrelated.txt").write_text("an unrelated project with history\n")
    sites.git(str(other), "add", "-A")
    sites.git(str(other), "commit", "-qm", "unrelated")      # HEAD resolves: the folder is untracked there
    shutil.copytree(os.path.dirname(d), other / "X", ignore=shutil.ignore_patterns(".git"))
    sd = str(other / "X" / "design")
    b = sites.bundle(sd, "p", page(".a { color: var(--ink); }"))
    code, items, out = run(sd, b)
    assert code == 3 and "is not tracked at HEAD of the repository" in out, out


# ================================================================== outside audit round 2 (Sol 6.1)

SENTINEL = "SDS-SYNTHETIC-SENTINEL-7f3a"      # synthetic bytes standing in for a secret; never a real key


@pytest.mark.parametrize("href", ["vault.key.", "vault.key%20", "vault.key::$DATA", "policy.yaml.", "GIT~1/config", "CON.css", "nul",
                                  "c:x.css", "sub/c:/x.css", "vault.key%2e", "x.css:alt", "./vault.key::$DATA"])
def test_windows_aliases_are_refused_and_never_quoted(X, href):
    """R2-H01: check_css.py refuses the same components as check_page.py (one portable grammar): the link is outside
    the bundle (A10), a nested drive path is named, never INTERNAL, and the aliased file's bytes are never read or quoted."""
    b = sites.bundle(X, "alias", page(head='<link rel="stylesheet" href="%s">' % href),
                     files={"vault.key": SENTINEL, "policy.yaml": SENTINEL, "x.css.txt": SENTINEL})
    code, items, out = run(X, b)
    assert code == 1 and fails(items, "stylesheet outside the bundle") and "INTERNAL" not in out, out
    assert SENTINEL not in out + json.dumps(items), out


# R2-M02: committed bytes by cat-file, CRLF to LF only, no attribute that lets the repository change content

def test_ident_attribute_is_incomplete(tmp_path):
    """R2-M02 (Sol's case): an ident attribute on a profile file lets two different texts share one blob through
    keyword expansion: the receipt is not approved (INCOMPLETE), whatever the blob comparison would say."""
    d = sites.build_x(tmp_path)
    sites.issue(d)
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    assert run(d, b)[0] == 0                                   # control: fresh
    with open(os.path.join(d, ".git", "info", "attributes"), "w") as fh:
        fh.write("policy.yaml ident\n")
    code, items, out = run(d, b)
    assert code == 3 and "attributes may change this file's content" in out and "ident" in out, out


def test_crlf_working_copy_of_an_lf_blob_is_fresh(tmp_path):
    """R2-M02: the one explicit normalisation, CRLF to LF on both sides: a CRLF working copy of an LF blob, issued and
    committed, is fresh; a real change is still stale (control)."""
    d = sites.build_x(tmp_path)
    sites.git(d, "init", "-q")
    sites.git(d, "add", "-A")
    sites.git(d, "commit", "-qm", "profile (LF)")
    pol = os.path.join(d, "policy.yaml")
    data = open(pol, "rb").read()
    open(pol, "wb").write(data.replace(b"\n", b"\r\n"))         # the working copy only; the blob stays LF
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(sites.SCRIPTS, "check_design.py"), "--site", d, "--issue"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout
    sites.commit_receipt(d)
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    code, items, out = run(d, b)
    assert code == 0, out
    open(pol, "wb").write(data.replace(b"\n", b"\r\n").replace(b"A3: blocking", b"A3: advisory"))
    assert run(d, b)[0] == 3


def _filter_marker(d):
    """A clean filter whose command would create a marker file beside the site design folder if Git ever ran it."""
    marker = os.path.join(os.path.dirname(d), "filter-ran.txt")
    sites.git(d, "config", "filter.mark.clean", "echo ran > ../filter-ran.txt; cat")
    with open(os.path.join(d, ".git", "info", "attributes"), "w") as fh:
        fh.write("* filter=mark\n")
    return marker


def test_a_configured_clean_filter_is_never_run_by_the_consumer(tmp_path):
    """R2-M02: approval runs no filter (an external program): with a clean filter configured for every path, the
    consumer gives INCOMPLETE and the filter's marker never appears."""
    d = sites.build_x(tmp_path)
    sites.issue(d)
    marker = _filter_marker(d)
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    code, items, out = run(d, b)
    assert code == 3 and "attributes may change" in out and "filter" in out, out
    assert not os.path.exists(marker), "the clean filter ran"


# R2-H06: the owner's commit of ready.json approves the CSS, script and font digests it holds (the CEO's decision)

def test_issue_then_commit_the_receipt_passes(tmp_path):
    d = sites.build_x(tmp_path)
    out = sites.issue(d, commit_receipt_too=False)
    assert "Commit ready.json now" in out.strip().splitlines()[-1], out
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    code, items, out = run(d, b)
    assert code == 3 and "the receipt is not committed, or changed since its commit" in out, out
    sites.commit_receipt(d)
    assert run(d, b)[0] == 0, run(d, b)[2]


def test_edited_css_with_a_rewritten_receipt_hash_is_incomplete(tmp_path):
    """R2-H06 (HQ's probe h06): the receipt committed, then the site's CSS edited outside the design folder and its hash
    rewritten in ready.json, the profile untouched: INCOMPLETE, never PASS; the edited sheet is never approved CSS."""
    d = sites.build_x(tmp_path)
    sites.issue(d)
    css = os.path.join(os.path.dirname(d), "site", "x.css")
    with open(css, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n.evil { color: #ff00ff; }\n")
    b = sites.bundle(d, "h06", page("<p>t</p>"))
    code, items, out = run(d, b)
    assert code == 3 and "CSS ../site/x.css changed since the receipt" in out, out       # control: receipt untouched
    r = json.load(open(os.path.join(d, "ready.json")))
    for k in r["css"]:
        r["css"][k] = sites.hashlib.sha256(open(css, "rb").read()).hexdigest()
    with open(os.path.join(d, "ready.json"), "w") as fh:
        json.dump(r, fh, indent=1, sort_keys=True)
    code, items, out = run(d, b)
    assert code == 3 and "the receipt is not committed, or changed since its commit" in out, out
    assert "approved site stylesheet" not in out, out


def test_committed_receipt_edited_in_the_work_tree_is_incomplete(tmp_path):
    d = sites.build_x(tmp_path)
    sites.issue(d)
    p = os.path.join(d, "ready.json")
    r = json.load(open(p))
    r["issued"] = "2000-01-01T00:00:00+00:00"
    open(p, "w").write(json.dumps(r, indent=1, sort_keys=True))
    b = sites.bundle(d, "p", page(".a { color: var(--ink); }"))
    code, items, out = run(d, b)
    assert code == 3 and "the receipt is not committed, or changed since its commit" in out, out


# R2-M04: one resolver, one budget, one map per document

def test_early_resolver_spends_the_budget(X):
    """R2-M04 (HQ's probe m04): 64 definitions of --x as a length, then a red colour definition used in a border
    shorthand: the early resolver used to keep the first 64 lengths and skip the colour (PASS, zero items); it now
    spends the one budget and gives INCOMPLETE, never PASS."""
    rules = " ".join(".a%d { --x: 1px; }" % i for i in range(64)) + " p { --x: #ff0000; border: 1px solid var(--x); }"
    b = sites.bundle(X, "m04", page(rules))
    code, items, out = run(X, b)
    assert code in (1, 3) and [i for i in items if i["status"] in ("FAIL", "INCOMPLETE")], out
    assert [i for i in items if i["status"] == "INCOMPLETE" and "too many variable definitions" in i["detail"]] or fails(items, "#ff0000"), out


def test_fallback_inside_a_color_mix_operand_is_validated(X):
    """R2-M04: a hard-coded fallback inside a color-mix() operand fails like any other fallback."""
    b = sites.bundle(X, "mix", page("p { color: color-mix(in srgb, var(--ink) 50%, var(--missing, #ff0000)); }"))
    code, items, out = run(X, b)
    assert code == 1 and fails(items, "hard-coded fallback"), out


def test_variables_are_collected_per_document(X):
    """R2-M04: a variable defined only inside an iframe's srcdoc document does not resolve a declaration of the main
    document (each document its own map); the same definition in the main document does (control)."""
    frame = '<iframe title="f" srcdoc="&lt;style&gt;:root { --frame-only: var(--ink); }&lt;/style&gt;&lt;p&gt;x&lt;/p&gt;"></iframe>'
    b = sites.bundle(X, "docs", page(".a { color: var(--frame-only); }", body='<p class="a">t</p>' + frame))
    code, items, out = run(X, b)
    assert code == 1 and fails(items, "--frame-only is not a contract, derived or page variable"), out
    b = sites.bundle(X, "docs2", page(":root { --frame-only: var(--ink); } .a { color: var(--frame-only); }", body='<p class="a">t</p>'))
    assert run(X, b)[0] == 0


def test_color_mix_is_not_rounded_into_a_token(X):
    """R2-L01: color-mix(in srgb, var(--ink) 99.99%, #1b1a2e .01%) differs from the ink colour before rounding: it is
    not accepted as the ink token (the exact mix of ink with itself is, control)."""
    b = sites.bundle(X, "l01", page(".a { color: color-mix(in srgb, var(--ink) 99.99%, #1b1a2e .01%); }"))
    code, items, out = run(X, b)
    assert code == 1 and fails(items, "color-mix() resolves to"), out
    b = sites.bundle(X, "l01c", page(".a { color: color-mix(in srgb, var(--ink) 60%, var(--ink) 40%); }"))
    assert run(X, b)[0] == 0


def test_report_mode_truncation_keeps_the_total(tmp_path, monkeypatch, capsys):
    """R2-L03: in report mode (informational, exit 0) a truncated report keeps the total line and says how many of how
    many items it printed; it never prints the outcome word INCOMPLETE; the JSON carries truncated and total."""
    import check_css
    d = sites.build_x(tmp_path)
    css = tmp_path / "many.css"
    css.write_text("".join(".c%d { color: #%06x; }\n" % (i, i) for i in range(10)))
    j = str(tmp_path / "r.json")
    monkeypatch.setattr(check_css, "MAX_ITEMS", 5)
    assert check_css.main(["--site", d, "--report", str(css), "--json", j]) == 0
    out = capsys.readouterr().out
    assert "report truncated: 4 of 11 items printed" in out and "10 hard-coded values" in out and "INCOMPLETE" not in out, out
    data = json.load(open(j))
    assert data["truncated"] is True and data["total"] == 11 and data["outcome"] == "REPORT" and len(data["items"]) == 5, data


def test_template_styles_do_not_apply(X):
    """R2-M11: a <style> inside an inert <template> applies to nothing: it is not checked (a live one is, control)."""
    b = sites.bundle(X, "tpl", page(body="<template><style>p { color: #ff0000; }</style><p>t</p></template><p>t</p>"))
    assert run(X, b)[0] == 0
    b = sites.bundle(X, "tpl2", page(body="<style>p { color: #ff0000; }</style><p>t</p>"))
    code, items, out = run(X, b)
    assert code == 1 and fails(items, "#ff0000"), out


def test_uncertified_font_stack_variable_is_not_accepted(tmp_path):
    """R2-M07: check_css.py accepts font-family: var(--font) only for a certified stack: with :root { --font: Georgia }
    in the site CSS it fails (in-process: check_design.py would refuse to issue a receipt for that profile)."""
    import check_css
    import designlib as dl
    import policylib as pl
    d = sites.build_x(tmp_path)
    sites.edit(os.path.join(d, "policy.yaml"), "stack_vars: []", "stack_vars: [--font]")
    sites.edit(os.path.join(d, "../site/x.css"), "--measure: 680px;", "--measure: 680px; --font: Georgia;")
    rep = dl.Report("t")
    check_css.Checker(pl.Profile(d), rep).font_family("p { font-family }", ["p"], "var(--font)")
    assert [i for i in rep.items if i["status"] == "FAIL" and "not an approved stack" in i["detail"]], rep.items
    sites.edit(os.path.join(d, "../site/x.css"), "--font: Georgia;", '--font: "Inter Test", sans-serif;')
    rep = dl.Report("t")
    check_css.Checker(pl.Profile(d), rep).font_family("p { font-family }", ["p"], "var(--font)")
    assert [i["status"] for i in rep.items] == ["PASS"], rep.items


def test_font_stack_with_listed_fallback_families_is_accepted(tmp_path):
    """The CEO's decision on Question 6 (2026-11-11), check_css's side: font-family: var(--font) through a stack that
    names system fallbacks is accepted when fonts.fallback_families lists every one of them, and fails when one
    (Arial) is missing from the list, as check_design.py certifies it."""
    import check_css
    import designlib as dl
    import policylib as pl
    d = sites.build_x(tmp_path)
    stack = '"Inter Test", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif'
    sites.edit(os.path.join(d, "policy.yaml"), "stack_vars: []", "stack_vars: [--font]")
    sites.edit(os.path.join(d, "../site/x.css"), "--measure: 680px;", "--measure: 680px; --font: %s;" % stack)
    sites.edit(os.path.join(d, "policy.yaml"), "fallback_families: []", "fallback_families: [Segoe UI, Roboto, Arial]")
    rep = dl.Report("t")
    check_css.Checker(pl.Profile(d), rep).font_family("p { font-family }", ["p"], "var(--font)")
    assert [i["status"] for i in rep.items] == ["PASS"], rep.items
    sites.edit(os.path.join(d, "policy.yaml"), "fallback_families: [Segoe UI, Roboto, Arial]", "fallback_families: [Segoe UI, Roboto]")
    rep = dl.Report("t")
    check_css.Checker(pl.Profile(d), rep).font_family("p { font-family }", ["p"], "var(--font)")
    assert [i["status"] for i in rep.items] == ["FAIL"] and "not an approved stack" in rep.items[0]["detail"], rep.items


def test_literal_font_stack_with_listed_fallback_families_is_accepted(tmp_path):
    """The CEO's decision on CC-06's Question 5 (2026-11-11, 'Yes, in literal stacks too': one rule for any stack): a
    literal font-family stack in a page's own CSS, an approved face first, is accepted when fonts.fallback_families lists
    every system family it names, as a stack variable is; it fails when one (Arial) is missing from the list, and without
    the key (control, as before the decision)."""
    import check_css
    import designlib as dl
    import policylib as pl
    d = sites.build_x(tmp_path)
    stack = '"Inter Test", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif'
    policy = os.path.join(d, "policy.yaml")

    def judged():
        rep = dl.Report("t")
        check_css.Checker(pl.Profile(d), rep).font_family("p { font-family }", ["p"], stack)
        return rep.items
    out = judged()
    assert [i["status"] for i in out] == ["FAIL"] and "is not an approved face or stack" in out[0]["detail"], out
    sites.edit(policy, "fallback_families: []", "fallback_families: [Segoe UI, Roboto, Arial]")
    out = judged()
    assert [i["status"] for i in out] == ["PASS"] and "approved face inter test" in out[0]["detail"], out
    sites.edit(policy, "fallback_families: [Segoe UI, Roboto, Arial]", "fallback_families: [Segoe UI, Roboto]")
    out = judged()
    assert [i["status"] for i in out] == ["FAIL"] and "is not an approved face or stack" in out[0]["detail"], out


@pytest.mark.parametrize("stack,accepted", [
    ('Arial, "Inter Test", sans-serif', False),
    ('"Inter Test", Arial, sans-serif', True),
    ("sans-serif", False),
    ("ui-sans-serif, system-ui, sans-serif", False),
], ids=["listed fallback first", "approved face first", "generic only", "generic families only"])
def test_every_font_stack_needs_an_approved_face_first(tmp_path, stack, accepted):
    """The CEO's decision on CC-07's Question 5 (2026-11-12, 'the approved face first everywhere'): one rule for a
    font-stack variable and a literal font-family stack of a page's own CSS. The first family is an approved face, then
    listed fonts.fallback_families and generic families. Arial is listed: first in the stack it fails in both forms;
    after the approved face both are accepted. A stack of generic families alone names no approved face first: it fails
    in both forms (check_design.py fails the variable too, test_check_design.py)."""
    import check_css
    import designlib as dl
    import policylib as pl
    d = sites.build_x(tmp_path)
    sites.edit(os.path.join(d, "policy.yaml"), "stack_vars: []", "stack_vars: [--font]")
    sites.edit(os.path.join(d, "policy.yaml"), "fallback_families: []", "fallback_families: [Arial]")
    sites.edit(os.path.join(d, "../site/x.css"), "--measure: 680px;", "--measure: 680px; --font: %s;" % stack)
    for value, word in (("var(--font)", "not an approved stack"), (stack, "is not an approved face or stack")):
        rep = dl.Report("t")
        check_css.Checker(pl.Profile(d), rep).font_family("p { font-family }", ["p"], value)
        want = ["PASS"] if accepted else ["FAIL"]
        assert [i["status"] for i in rep.items] == want and (accepted or word in rep.items[0]["detail"]), (value, rep.items)


def test_json_through_a_hard_link_is_refused(X, tmp_path):
    """R2-M03: check_css.py's --json destination that is a hard link is refused (ERROR 2); its other name keeps its bytes."""
    b = sites.bundle(X, "hl", page())
    other = tmp_path / "other.json"
    other.write_bytes(b"other bytes")
    j = tmp_path / "r.json"
    os.link(str(other), str(j))
    r = subprocess.run([sys.executable, "-I", "-B", CC, "--site", X, "--bundle", b, "--page", "index.html", "--json", str(j)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "hard link" in r.stdout and other.read_bytes() == b"other bytes", r.stdout
