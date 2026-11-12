"""check_css.py — the static role check of a page's own CSS (plan 0.4 B.7.4, after Mozilla's use-design-tokens).

Usage:
  check_css.py --site <site design folder> --bundle <folder> --page <relative path> [--json FILE] [--no-git]
               [--receipt-sha256 HEX]
  check_css.py --site <site design folder> --report <CSS file> [...] [--json FILE]
Bundle mode checks every stylesheet the page and its same-bundle frame documents (iframe src and srcdoc) apply: linked
local sheets, <style> elements, style="" attributes and the SVG presentation attributes fill, stroke and stop-color.
Every bundle file it reads passes the guard shared with check_page.py (bundlelib.py: names, links, bytes equal to a
site design folder file): a refused file is an ERROR and is never parsed or quoted. A linked sheet whose SHA-256 equals
a CSS file of the receipt is the approved site CSS (traced by check_design.py) and is listed, not role-checked. Each
role-bearing declaration must take a contract variable of a token allowed for its role and scheme, a literal token's
exact value, an extra in its roles and range, a derived variable in its roles, a font-stack variable or an approved
family stack, or a CSS-wide keyword, currentColor, transparent. Every definition of a page variable is checked (at most
64 definitions expanded per declaration; more give INCOMPLETE); var() fallbacks are checked at every level; certified
variables (the trace map's, the font stacks, the derived ones) may be restated only with their approved value. A font
shorthand's family is checked when it is written out or is exactly one approved font-stack variable; any other var()
in it gives INCOMPLETE. The report holds at most 5,000 items, the truncation item included.
--receipt-sha256: the SHA-256 of the issued ready.json; with no Git repository, approval counts only with it.
--report lists a site's hard-coded values by property and file (report only; exit 0 unless the input is unreadable).
Outcomes: PASS 0, FAIL 1, ERROR 2, INCOMPLETE 3, INTERNAL 4."""
import argparse
import html.parser
import json
import os
import posixpath
import re
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import bundlelib as bl  # noqa: E402
import csslite  # noqa: E402
import designlib as dl  # noqa: E402
import policylib as pl  # noqa: E402

VERSION = "0.1.0"
BORDER_SIDES = ("border", "border-top", "border-right", "border-bottom", "border-left",
                "border-block", "border-block-start", "border-block-end", "border-inline", "border-inline-start", "border-inline-end")
BORDER_COLOURS = re.compile(r"^border(-(top|right|bottom|left|block|inline|block-start|block-end|inline-start|inline-end))?-color$")
CODE_SEL = re.compile(r"(^|[\s>+~(,])(code|pre|kbd|samp)\b")
VAR = re.compile(r"^var\(\s*(--[\w-]+)\s*(?:,(.*))?\)$", re.S)
PAINT_SERVER = re.compile(r"^url\(\s*(['\"]?)#[^'\")]+\1\s*\)$", re.I)   # an SVG paint server in the same document
MAX_FILE_BYTES = 20_000_000    # the largest page, frame document or stylesheet read (check_page.py's staging budget)
MAX_DOCUMENTS = 50             # the page and its frame documents read in one run
MAX_EXPANSIONS = 64            # page-variable definitions expanded for one declaration (the limit of resolutions(); C6)
MAX_ITEMS = 5000               # report items, the truncation item included (check_page.py's limit; C6)
FONT_SIZE_WORDS = {"xx-small", "x-small", "small", "medium", "large", "x-large", "xx-large", "xxx-large", "larger", "smaller", "math"}
SYSTEM_FONTS = {"caption", "icon", "menu", "message-box", "small-caption", "status-bar"}
LENGTH = re.compile(r"^([+-]?(\d+\.?\d*|\.\d+)(px|em|rem|%|vw|vh|vmin|vmax|ch|ex|pt|cm|mm|in|q|pc|lh|rlh)|0)$", re.I)
TEXT_DECORATION_WORDS = ("underline", "overline", "line-through", "wavy", "blink")


class PageSources(html.parser.HTMLParser):
    """What one document applies, in order: linked sheets, <style> elements, style="" attributes, the SVG presentation
    attributes fill, stroke and stop-color; and its frames (iframe src and srcdoc). The first of duplicate attributes
    wins, as in browsers (AUD-F03(1))."""
    PRESENTATION = ("fill", "stroke", "stop-color")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.styles, self.attrs, self.frames, self.srcdocs = [], [], [], [], []
        self._in_style, self._buf, self.line, self._template = False, [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag == "template":          # inert content: nothing in it applies (R2-M11)
            self._template += 1
            return
        if self._template:
            return
        a = bl.first_attrs(attrs)
        line = self.getpos()[0]
        if tag == "link" and "stylesheet" in (a.get("rel") or "").lower().split() and a.get("href"):
            self.links.append((a["href"], line))
        if tag == "style":
            self._in_style, self._buf, self.line = True, [], line
        if a.get("style"):
            self.attrs.append((tag, a["style"], line))
        for name in self.PRESENTATION:
            if a.get(name):
                self.attrs.append((tag, "%s: %s" % (name, a[name]), line))
        if tag == "iframe":
            if a.get("src"):
                self.frames.append((a["src"], line))
            if "srcdoc" in a:
                self.srcdocs.append((a["srcdoc"], line))

    def handle_endtag(self, tag):
        if tag == "template" and self._template:
            self._template -= 1
            return
        if tag == "style" and self._in_style:
            self.styles.append(("".join(self._buf), self.line))
            self._in_style = False

    def handle_data(self, data):
        if self._in_style and not self._template:
            self._buf.append(data)


def font_shorthand_family(value):
    """The family list of a font shorthand: everything after the size (and its /line-height); None when no size is found."""
    parts = [p for p in dl.split_top(value.strip(), " ") if p.strip()]
    for i, p in enumerate(parts):
        size = p.split("/", 1)[0]
        if LENGTH.match(size) or size.lower() in FONT_SIZE_WORDS or size.lower().startswith(("calc(", "clamp(", "min(", "max(")):
            j = i + 1
            if "/" not in p and j < len(parts) and parts[j].startswith("/"):
                j += 2 if parts[j] == "/" else 1
            return " ".join(parts[j:]).strip() or None
    return None


def traced_vars(tmap):
    """Every custom property the trace map names (colours, dimensions, typography, component fields)."""
    out = set()
    for g, fields in tmap.items():
        if g == "overrides" or not isinstance(fields, dict):
            continue
        for b in fields.values():
            if not isinstance(b, dict):
                continue
            if isinstance(b.get("var"), str):
                out.add(b["var"])
            for sub in b.values():
                if isinstance(sub, dict) and isinstance(sub.get("var"), str):
                    out.add(sub["var"])
            for v in (b.get("vars") or {}).values() if isinstance(b.get("vars"), dict) else []:
                out.add(v)
    return out


class Checker:
    def __init__(self, profile, rep):
        self.p, self.rep, self.pal = profile, rep, pl.Palette(profile)
        self.local_vars = {}     # the checked document's page variable -> every definition there (AST-M11, R2-M04)
        self.left, self.over = MAX_EXPANSIONS, False   # the expansion budget of the declaration being checked (C6)
        self.docs = []           # one entry per document (page, frame, srcdoc): its sheets and its own variables (R2-M04)
        self.noncolour = set()   # contract variables of widths, radii, spaces and type: never a colour part
        for g, fields in profile.tmap.items():
            if g in ("colors", "overrides") or not isinstance(fields, dict):
                continue
            for name, b in fields.items():
                if isinstance(b, dict):
                    if "var" in b:
                        self.noncolour.add(b["var"])
                    for k, sub in b.items():
                        if isinstance(sub, dict) and "var" in sub and k not in ("backgroundColor", "textColor"):
                            self.noncolour.add(sub["var"])
                    for v in (b.get("vars") or {}).values():
                        self.noncolour.add(v)
        # certified variables: restated only with their approved value, never redefined by a page (AST-M10, AUD-F05)
        names = (traced_vars(profile.tmap) | set(self.pal.stack_vars) | set(self.pal.derived)) - set(self.pal.contract)
        self.certified = {n: None for n in names}
        site_props = {}
        for path in profile.css_paths():
            try:
                sheet = csslite.parse(profile.snap.text(path))
            except (ValueError, dl.InputError, dl.ContentError):
                continue
            for k, v in csslite.custom_props(sheet).items():
                site_props[k] = v
                if k in self.certified:
                    self.certified[k] = v
        # a font-stack variable is certified only when the first family of its approved value is an approved face family
        # and every family an approved face family, a generic family or a fallback family the policy lists
        # (check_design.py fails it otherwise; R2-M07, the CEO's decision of 2026-11-11 on fonts.fallback_families, and
        # of 2026-11-12: the approved face first in every stack, a variable or a literal one)
        faces = set(self.pal.face_families())
        self.stack_ok = {}
        for n in self.pal.stack_vars:
            v = self.certified.get(n)
            fams = pl.families(csslite.resolve_vars(v, site_props)[0]) if v is not None else []
            self.stack_ok[n] = (bool(fams) and fams[0] in faces
                                and all(f in faces or f in pl.GENERIC_FAMILIES or f in self.pal.fallback_families for f in fams))

    def resolutions(self, value, where, depth=0):
        """Every value a page-variable reference can take, one per definition (at most 10 levels), each expansion spent
        from the declaration's one budget (R2-M04): past it the declaration has its one INCOMPLETE and the values not
        reached are left out (never a silent truncation: the INCOMPLETE says so)."""
        m = re.search(r"var\(\s*(--[\w-]+)\s*\)", value)
        if not m or depth > 10 or m.group(1) not in self.local_vars:
            return [value]
        out = []
        for d in self.local_vars[m.group(1)]:
            if not self.spend(where):
                break
            out += self.resolutions(value[:m.start()] + d + value[m.end():], where, depth + 1)
        return out

    def spend(self, where):
        """One more page-variable definition expanded for the current declaration. Past MAX_EXPANSIONS the declaration
        gets one INCOMPLETE and nothing more is expanded: definitions that multiply per level grow exponentially (C6)."""
        self.left -= 1
        if self.left >= 0:
            return True
        if not self.over:
            self.over = True
            self.rep.add("INCOMPLETE", "CSS", where, "too many variable definitions to check (more than %d in one declaration)" % MAX_EXPANSIONS)
        return False

    def colourish(self, part, where):
        m = VAR.match(part.strip())
        if m and m.group(1) in self.noncolour:
            return False
        if m and m.group(1) in self.local_vars:
            return any(pl.is_colourish(v) for v in self.resolutions(part.strip(), where))
        return pl.is_colourish(part)

    def scheme_of(self, media):
        mode = self.p.mode()
        if mode == "dark-only":
            return "dark"
        if mode == "both" and "prefers-color-scheme: dark" in re.sub(r"\s+", " ", media.lower()).replace("( ", "("):
            return "dark"
        return "light"

    # ---- one colour part
    def colour_part(self, where, prop_role, kinds, part, scheme, seen=frozenset()):
        s = part.strip()
        low = s.lower()
        if low in pl.KEYWORDS or (low == "none" and prop_role in ("box-shadow", "fill", "stroke", "background-color")):
            return self.ok(where, "%s: %s (keyword)" % (prop_role, s))
        if prop_role in ("fill", "stroke"):
            head = dl.split_top(s, " ")[0].strip()
            if PAINT_SERVER.match(head):        # its stops are judged where they are declared (stop-color)
                rest = s[len(head):].strip()
                if rest:
                    return self.colour_part(where, prop_role, kinds, rest, scheme, seen)
                return self.ok(where, "%s: paint server %s (its stops are checked as gradient stops)" % (prop_role, head))
        m = VAR.match(s)
        if m:
            name, fallback = m.group(1), m.group(2)
            if name in seen:                        # seen: the variables being expanded through their definitions
                return self.fail(where, "variable cycle through %s" % name)
            if fallback is not None:
                fb = fallback.strip()
                if not fb.lower().startswith("var("):
                    return self.fail(where, "var(%s, %s) has a hard-coded fallback" % (name, fb))
                self.colour_part(where, prop_role, kinds, fb, scheme, seen)    # fallbacks are checked at every level
            if name in self.local_vars:
                res = None
                for d in self.local_vars[name]:     # every definition, not the last one (AST-M11)
                    if not self.spend(where):
                        return None
                    res = self.colour_part(where, prop_role, kinds, d, scheme, seen | {name})
                return res
            if name in self.pal.contract:
                tok = self.pal.contract[name]
                if tok in self.pal.reserved:
                    return self.fail(where, "%s is the reserved token %s (never painted in new work)" % (name, tok), floor=True)
                if tok in self.pal.tokens_for(scheme, prop_role):
                    return self.ok(where, "%s: %s = token %s" % (prop_role, name, tok))
                return self.fail(where, "%s is token %s, not a %s token of the %s scheme" % (name, tok, prop_role, scheme))
            if name in self.pal.derived:
                if prop_role in self.pal.derived[name] or set(kinds) & set(self.pal.derived[name]):
                    return self.ok(where, "%s: derived variable %s" % (prop_role, name))
                return self.fail(where, "derived variable %s is not allowed in %s" % (name, prop_role))
            return self.fail(where, "%s is not a contract, derived or page variable" % name)
        if low.startswith("light-dark("):
            inner = dl.split_top(s[s.index("(") + 1:-1], ",")
            if len(inner) != 2:
                return self.fail(where, "light-dark() needs two values: %s" % s)
            self.colour_part(where, prop_role, kinds, inner[0], "light", seen)
            return self.colour_part(where, prop_role, kinds, inner[1], "dark", seen)
        if low.startswith("color-mix("):
            for operand in dl.split_top(s[s.index("(") + 1:-1], ",")[1:]:     # its fallbacks, like any fallback (R2-M04)
                for bit in dl.split_top(operand.strip(), " "):
                    mv = VAR.match(bit.strip())
                    if mv and mv.group(2) is not None:
                        fb = mv.group(2).strip()
                        if not fb.lower().startswith("var("):
                            return self.fail(where, "var(%s, %s) has a hard-coded fallback inside color-mix()" % (mv.group(1), fb))
                        self.colour_part(where, prop_role, kinds, fb, scheme, seen)
            c = color_mix(s, self, where)
            if c is None:
                return self.rep.add("INCOMPLETE", "CSS", where, "color-mix() not resolvable here (only 'in srgb' of resolvable colours): %s" % s)
            ok, why = self.pal.allowed_colour(c, scheme, prop_role, kinds)
            return (self.ok if ok else self.fail)(where, "color-mix() resolves to %r: %s" % (c, why))
        c = dl.parse_colour(s)
        if c is None:
            return self.fail(where, "%s value %r is not an allowed value (raw or unsupported colour)" % (prop_role, s))
        lit = [t for t in self.pal.tokens_for(scheme, prop_role) if t in self.pal.literal and self.p.colour(t) == c]
        if lit:
            return self.ok(where, "%s: literal token %s" % (prop_role, lit[0]))
        x = self.pal.extra_match(c, kinds)
        if x:
            return self.ok(where, "%s: extra %s" % (prop_role, x))
        r = self.pal.reserved_match(c)
        if r:
            return self.fail(where, "%r is the reserved token %s" % (c, r), floor=True)
        return self.fail(where, "raw %s value %s is not allowed (use a contract variable)" % (prop_role, s))

    def ok(self, where, detail):
        return self.rep.add("PASS", "CSS", where, detail)

    def fail(self, where, detail, floor=False):
        return self.rep.add("FAIL", "CSS", where, detail, floor=floor)

    # ---- one declaration
    def declaration(self, where, selectors, prop, value, media):
        self.left, self.over = MAX_EXPANSIONS, False
        scheme = self.scheme_of(media)
        pseudo = any(re.search(r"::?(before|after|selection|marker)\b", s) for s in selectors)
        if prop.startswith("--"):
            if prop in self.pal.contract:
                want = self.pal.contract_values.get(prop)
                got = {dl.parse_colour(v) for v in self.resolutions(value, where)}
                got = got.pop() if len(got) == 1 else None
                if want is None or got != want:
                    return self.fail(where, "redefines the contract variable %s (%s) to %s" % (prop, want, value))
                return self.ok(where, "contract variable %s restated with its own value" % prop)
            if prop in self.certified:
                approved = self.certified[prop]
                if approved is None or not dl.same(value, approved):
                    return self.fail(where, "redefines the certified variable %s (%s) to %s" % (prop, approved, value))
                return self.ok(where, "certified variable %s restated with its approved value" % prop)
            return None
        value = value.strip()
        if prop in ("color", "-webkit-text-fill-color", "-webkit-text-stroke-color", "text-decoration-color"):
            return self.colour_part(where, "color", ["text"], value, scheme)
        if prop in ("text-decoration", "-webkit-text-stroke"):
            for part in dl.split_top(value, " "):
                part = part.strip()
                if part and self.colourish(part, where) and part.lower() not in TEXT_DECORATION_WORDS:
                    self.colour_part(where, "color", ["text"], part, scheme)
            return None
        if prop == "text-shadow":
            if value.lower() in ("none",) or value.lower() in pl.KEYWORDS:
                return self.ok(where, "text-shadow: %s" % value)
            for shadow in dl.split_top(value, ","):
                for c in [x for x in dl.split_top(shadow.strip(), " ") if x.strip() and self.colourish(x, where)]:
                    self.colour_part(where, "box-shadow", ["box-shadow"], c, scheme)
            return None
        if prop == "background-color":
            return self.colour_part(where, "background-color", ["background"] + (["decoration-background"] if pseudo else []), value, scheme)
        if prop == "stop-color":         # an SVG gradient stop (AST-H07)
            return self.colour_part(where, "background-color", ["gradient-stop"], value, scheme)
        if BORDER_COLOURS.match(prop):
            for part in dl.split_top(value, " "):
                if part.strip():
                    self.colour_part(where, "border-color", ["border"], part, scheme)
            return None
        if prop == "outline-color":
            return self.colour_part(where, "outline-color", ["outline", "border"], value, scheme)
        if prop in ("fill", "stroke"):
            return self.colour_part(where, prop, [prop] + (["svg-text"] if prop == "fill" else []), value, scheme)
        if prop in BORDER_SIDES or prop == "outline":
            role = "outline-color" if prop == "outline" else "border-color"
            for part in dl.split_top(value, " "):
                part = part.strip()
                if part and self.colourish(part, where):
                    self.colour_part(where, role, ["outline", "border"] if prop == "outline" else ["border"], part, scheme)
            return None
        if prop in ("background", "background-image"):
            kinds = ["background"] + (["decoration-background"] if pseudo else [])
            for stop in pl.gradient_stops(value):
                self.colour_part(where, "background-color", ["gradient-stop"], stop, scheme)
            if prop == "background":
                for layer in dl.split_top(pl.strip_gradients(value), ","):
                    for part in dl.split_top(layer, " "):
                        part = part.strip()
                        if part and self.colourish(part, where):
                            self.colour_part(where, "background-color", kinds, part, scheme)
            return None
        if prop == "box-shadow":
            if value.lower() in ("none",) or value.lower() in pl.KEYWORDS:
                return self.ok(where, "box-shadow: %s" % value)
            m = VAR.match(value)
            if m:
                return self.colour_part(where, "box-shadow", ["box-shadow"], value, scheme)
            for shadow in dl.split_top(value, ","):
                parts = [x for x in dl.split_top(shadow.strip(), " ") if x.strip()]
                cols = [x for x in parts if self.colourish(x, where)]
                if not cols:
                    self.fail(where, "box-shadow without an explicit colour (currentColor implied): %s" % shadow.strip())
                for c in cols:
                    self.colour_part(where, "box-shadow", ["box-shadow"], c, scheme)
            return None
        if prop == "font-family":
            return self.font_family(where, selectors, value)
        if prop == "font":              # the shorthand's family is checked like font-family (AST-M11)
            low = value.lower()
            if low in pl.KEYWORDS:
                return self.ok(where, "font: %s" % value)
            if low in SYSTEM_FONTS:
                return self.fail(where, "font: %s selects a system font, not an approved face" % value)
            if "var(" in value:
                fam = font_shorthand_family(value)
                m = VAR.match(fam or "")
                if value.count("var(") == 1 and m and m.group(2) is None and m.group(1) in self.pal.stack_vars:
                    return self.font_family(where, selectors, fam)     # exactly one approved font-stack variable (C7)
                return self.rep.add("INCOMPLETE", "CSS", where, "font shorthand through a variable: its family is not read here: %s" % value)
            fam = font_shorthand_family(value)
            if not fam:
                return self.fail(where, "font shorthand without a readable family: %s" % value)
            return self.font_family(where, selectors, fam)
        return None

    def font_family(self, where, selectors, value, seen=frozenset()):
        v = value.strip()
        m = VAR.match(v)
        if m:
            name, fallback = m.group(1), m.group(2)
            if name in seen:
                return self.fail(where, "variable cycle through %s" % name)
            if fallback is not None:
                fb = fallback.strip()
                if not fb.lower().startswith("var("):
                    return self.fail(where, "var(%s, …) has a hard-coded fallback" % name)
                self.font_family(where, selectors, fb, seen)
            if name in self.pal.stack_vars:
                if not self.stack_ok.get(name):           # an uncertified stack is never accepted (R2-M07)
                    return self.fail(where, "font-stack variable %s holds %s, not an approved stack" % (name, self.certified.get(name)))
                return self.ok(where, "font-family: stack variable %s" % name)
            if name in self.local_vars:
                res = None
                for d in self.local_vars[name]:
                    if not self.spend(where):
                        return None
                    res = self.font_family(where, selectors, d, seen | {name})
                return res
            return self.fail(where, "font-family variable %s is not a font-stack variable of the policy" % name)
        if v.lower() in pl.KEYWORDS:
            return self.ok(where, "font-family: %s" % v)
        fams = pl.families(v)
        # a literal stack: an approved face first, then approved faces, generic families or the fallback families the
        # policy lists, as in a font-stack variable (the CEO's decisions of 2026-11-11 on CC-06's Question 5 and of
        # 2026-11-12 on CC-07's Question 5: one rule for every stack)
        if fams and fams[0] in self.pal.face_families() and all(
                f in self.pal.face_families() or f in pl.GENERIC_FAMILIES or f in self.pal.fallback_families for f in fams):
            return self.ok(where, "font-family: approved face %s" % fams[0])
        if pl.is_system_monospace(v):
            if self.pal.code_roles == "system-monospace" and selectors and all(CODE_SEL.search(s) for s in selectors):
                return self.ok(where, "font-family: system monospace in a code role")
            return self.fail(where, "monospace stack outside code roles (or code roles off): %s" % v)
        return self.fail(where, "font-family %s is not an approved face or stack" % v)

    def new_document(self, label):
        """A document whose sheets share one variable map: the page, a frame document or a srcdoc (R2-M04)."""
        doc = {"label": label, "sheets": [], "vars": {}}
        self.docs.append(doc)
        return doc

    def add_sheet(self, label, css_text, doc=None):
        """Parse one stylesheet of a document and learn its page variables there; declarations are checked by
        check_all, after every sheet is read, so each reference sees every definition of its own document (AST-M11;
        R2-M04: a sheet linked by two documents applies to each of them)."""
        doc = doc if doc is not None else (self.docs[-1] if self.docs else self.new_document("page"))
        try:
            sheet = csslite.parse(css_text)
        except ValueError as exc:
            self.rep.add("FAIL", "CSS", label, "unreadable CSS: %s" % exc)
            return
        doc["sheets"].append((label, sheet))
        for r in sheet.rules:
            for prop, value in r.decls:
                if prop.startswith("--") and prop not in self.pal.contract and prop not in self.certified:
                    doc["vars"].setdefault(prop, []).append(value)

    def check_all(self):
        for doc in self.docs:
            self.local_vars = doc["vars"]             # this document's definitions only (R2-M04)
            self.check_document(doc)

    def check_document(self, doc):
        for label, sheet in doc["sheets"]:
            for item in sheet.unsupported:
                self.rep.add("INCOMPLETE", "CSS", label, "unsupported at-rule %s: not checked" % item)
            for r in sheet.rules:
                for prop, value in r.decls:
                    self.declaration("%s:%d %s { %s }" % (label, r.line, ", ".join(r.selectors), prop), r.selectors, prop, value, r.media)
            for ff in sheet.font_faces:
                fam = dict(ff["decls"]).get("font-family", "")
                if fam and pl.families(fam)[0] not in self.pal.face_families():
                    self.fail("%s:%d @font-face" % (label, ff["line"]), "@font-face declares %s, not an approved face" % fam)
            for name, k in sheet.keyframes.items():
                for sel, decls in k["frames"]:
                    for prop, value in decls:
                        self.declaration("%s:%d @keyframes %s %s { %s }" % (label, k["line"], name, sel, prop), [], prop, value, k["media"])


def color_mix(s, checker, where):
    """color-mix(in srgb, A p%, B q%) of resolvable colours, else None."""
    inner = dl.split_top(s[s.index("(") + 1:-1], ",")
    if len(inner) != 3 or inner[0].strip().lower() != "in srgb":
        return None
    parts = []
    for x in inner[1:]:
        bits = [b for b in dl.split_top(x.strip(), " ") if b]
        pct = next((b for b in bits if b.endswith("%")), None)
        col = next((b for b in bits if not b.endswith("%")), None)
        m = VAR.match(col or "")
        c = None
        if m and m.group(1) in checker.pal.contract_values:
            c = checker.pal.contract_values[m.group(1)]
        elif col:
            found = {dl.parse_colour(v) for v in checker.resolutions(col, where)}
            c = found.pop() if len(found) == 1 else None
        if c is None:
            return None
        parts.append((c, Decimal(pct[:-1]) / 100 if pct else None))
    (c1, p1), (c2, p2) = parts
    if p1 is None and p2 is None:
        p1 = p2 = Decimal("0.5")
    elif p1 is None:
        p1 = 1 - p2
    elif p2 is None:
        p2 = 1 - p1
    total = p1 + p2
    if total <= 0:
        return None
    w1, w2 = p1 / total, p2 / total
    a = c1.a * w1 + c2.a * w2
    if a == 0:
        return dl.Colour(0, 0, 0, 0)
    # fractional channels and alpha kept until the exact comparison with the allowed colours: an authored mix is never
    # rounded into a token (R2-L01); no tolerance here (the browser's two-decimal alpha tolerance is check_page.py's)
    ch = [dl.canon_decimal((x1 * c1.a * w1 + x2 * c2.a * w2) / a) for x1, x2 in ((c1.r, c2.r), (c1.g, c2.g), (c1.b, c2.b))]
    alpha = a * min(total, 1)
    return dl.Colour(ch[0], ch[1], ch[2], alpha)


def run_bundle(args, rep):
    profile = pl.Profile(args.site)
    receipt_ok = pl.verify_receipt(profile, rep, use_git=not args.no_git, receipt_sha256=args.receipt_sha256)
    if pl.is_link(args.bundle.rstrip("/\\") or args.bundle):
        raise dl.InputError("bundle refused: the bundle root %s is a link (R2-M01)" % args.bundle)
    bundle = os.path.realpath(args.bundle)
    page = os.path.normpath(os.path.join(bundle, args.page))
    if os.path.commonpath([page, bundle]) != bundle or not os.path.isfile(page):
        raise dl.InputError("the page %s is not a file inside the bundle %s" % (args.page, bundle))
    if not receipt_ok:
        return
    guard = bl.Guard(profile, pl.folder_files(profile.dir))
    approved = {}
    for p in profile.css_paths():
        if os.path.isfile(p):
            approved[profile.snap.digest(p)] = os.path.basename(p)   # the bytes the receipt check hashed
    try:
        root = bl.BundleRoot(bundle)      # one trusted root for every read, never reopened by path (R2-M01)
    except ValueError as exc:
        raise dl.InputError("bundle refused: %s" % exc)
    try:
        _check_bundle(args, rep, profile, bundle, root, guard, approved, page)
    finally:
        root.close()


def _check_bundle(args, rep, profile, bundle, root, guard, approved, page):
    def read(rel):
        data, why = guard.read(root, rel, MAX_FILE_BYTES)
        if why and why != bl.MISSING:
            raise dl.InputError("bundle refused: %s" % why)       # the refused file is never parsed or quoted (AST-H01)
        if data is not None and len(data) > MAX_FILE_BYTES:
            raise dl.InputError("bundle refused: %s is larger than %d bytes" % (rel, MAX_FILE_BYTES))
        return data

    ck = Checker(profile, rep)
    page_rel = os.path.relpath(page, bundle).replace(os.sep, "/")
    queue, seen, count = [(page_rel, None, "", args.page)], set(), 0
    while queue:
        rel, text, base, label = queue.pop(0)
        if rel is not None:
            if rel in seen:
                continue
            seen.add(rel)
            data = read(rel)
            if data is None:
                if rel == page_rel:
                    raise dl.InputError("the page %s is not readable" % args.page)
                rep.add("FAIL", "CSS", label, "frame document %s is missing" % rel)
                continue
            text, base = data.decode("utf-8", "replace"), posixpath.dirname(rel)
        count += 1
        if count > MAX_DOCUMENTS:
            rep.add("INCOMPLETE", "CSS", label, "more than %d documents (page and frames): the rest are not checked" % MAX_DOCUMENTS)
            break
        doc = ck.new_document(label)            # its own variable map (R2-M04)
        src = PageSources()
        src.feed(text)
        for href, line in src.links:
            where = "%s:%d <link %s>" % (label, line, href)
            kind, target = bl.resolve_ref(href, base, bundle)   # percent-decoded, as check_page.py resolves it (AUD-F03(2))
            if kind != "local":
                rep.add("FAIL", "CSS", where, "stylesheet outside the bundle or not local (A10)")
                continue
            data = read(target)
            if data is None:
                rep.add("FAIL", "CSS", where, "linked stylesheet is missing")
                continue
            sha = dl.sha256(data)
            if sha in approved:
                rep.add("INFO", "CSS", href, "approved site stylesheet (%s in the receipt); traced by check_design.py, not role-checked" % approved[sha])
                continue
            ck.add_sheet(target, data.decode("utf-8", "replace"), doc)
        for i, (css, line) in enumerate(src.styles):
            ck.add_sheet("%s:<style #%d at line %d>" % (label, i + 1, line), css, doc)
        for tag, style, line in src.attrs:
            ck.add_sheet("%s:%d <%s style>" % (label, line, tag), "%s{%s}" % (tag, style), doc)   # the tag is the selector (AUD-F10)
        for href, line in src.frames:
            kind, target = bl.resolve_ref(href, base, bundle)
            if kind == "local":
                queue.append((target, None, "", target))
            elif kind != "skip":
                rep.add("FAIL", "CSS", "%s:%d <iframe %s>" % (label, line, href), "frame outside the bundle or not local (A10)")
            elif href.strip().lower().startswith(("data:", "blob:")):
                rep.add("INCOMPLETE", "CSS", "%s:%d <iframe %s>" % (label, line, href[:40]), "a frame document that is not a bundle file is not checked")
        for i, (doc, line) in enumerate(src.srcdocs):
            queue.append((None, doc, base, "%s:%d <iframe srcdoc #%d>" % (label, line, i + 1)))
    ck.check_all()


def hard_coded(prop, value):
    """The hard-coded values of one role-bearing declaration, read through the same parts the role check reads (AST-L02):
    each colour part and gradient stop that is not a variable or a keyword; a family stack without a variable."""
    v = value.strip()
    if v.lower() in pl.KEYWORDS:
        return []
    if prop == "font-family":
        return [] if "var(" in v else [v]
    if prop == "font":
        fam = font_shorthand_family(v) if "var(" not in v else None
        return [fam] if fam else []
    out = []
    for layer in dl.split_top(v, ","):
        for part in dl.split_top(layer.strip(), " "):
            p = part.strip()
            low = p.lower()
            if not p:
                continue
            if pl.GRADIENT.match(p):
                out += [s for s in pl.gradient_stops(p) if not s.lower().startswith("var(") and s.lower() not in pl.KEYWORDS]
            elif pl.is_colourish(p) and not low.startswith("var(") and low not in pl.KEYWORDS and low not in TEXT_DECORATION_WORDS:
                out.append(p)
    return out


def run_report(args, rep):
    total = 0
    for path in args.report:
        try:
            sheet = csslite.parse(dl.read_bytes_any(path).decode("utf-8", "replace"))
        except ValueError as exc:
            raise dl.InputError("%s is not readable CSS: %s" % (path, exc))
        blocks = [(r.line, r.selectors, r.decls) for r in sheet.rules]
        blocks += [(k["line"], ["@keyframes %s %s" % (name, sel)], decls) for name, k in sheet.keyframes.items() for sel, decls in k["frames"]]
        for line, selectors, decls in blocks:
            for prop, value in decls:
                if prop.startswith("--"):
                    continue
                role = (prop in pl.ROLE_PROPS or BORDER_COLOURS.match(prop) or prop in BORDER_SIDES + ("background", "background-image", "outline", "font", "stop-color")
                        or prop in ("-webkit-text-fill-color", "-webkit-text-stroke-color", "text-decoration-color", "text-decoration", "text-shadow"))
                if not role:
                    continue
                for v in hard_coded(prop, value):
                    total += 1
                    rep.add("INFO", "COVERAGE", "%s:%d %s" % (os.path.basename(path), line, prop), "hard-coded %s in %s" % (v, ", ".join(selectors)))
        for item in sheet.unsupported:
            rep.add("INFO", "COVERAGE", os.path.basename(path), "unsupported at-rule %s: its declarations are not counted" % item)
    rep.add("INFO", "COVERAGE", "total", "%d hard-coded values in role-bearing properties" % total)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", required=True)
    ap.add_argument("--bundle")
    ap.add_argument("--page")
    ap.add_argument("--report", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--no-git", action="store_true", help="do not re-check the receipt's commit with git")
    ap.add_argument("--receipt-sha256", help="the SHA-256 of the issued ready.json (needed where no Git repository is)")
    args = ap.parse_args(argv)
    if args.receipt_sha256 is not None:
        args.receipt_sha256 = args.receipt_sha256.strip().lower()
        if not dl.SHA256_HEX.match(args.receipt_sha256):
            print("check_css: ERROR --receipt-sha256 must be 64 hex digits")
            return dl.EXIT["ERROR"]
    where = pl.output_problem(args.json, args.site)
    if where:
        print("check_css: ERROR --json %s" % where)
        return dl.EXIT["ERROR"]
    rep = dl.Report("check_css")
    try:
        dl.require_yaml()
        if args.report:
            run_report(args, rep)
        elif args.bundle and args.page:
            run_bundle(args, rep)
        else:
            ap.error("give --bundle and --page, or --report")
    except (dl.InputError, dl.ContentError) as exc:
        rep.error = "ERROR"
        rep.add("INFO", "INPUT", "input", str(exc))
        print("check_css: ERROR %s" % exc)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("check_css: INTERNAL (%s)" % exc)
        return dl.EXIT["INTERNAL"]
    informational = bool(args.report) and rep.error is None      # report mode: exit 0, no checker outcome (B.7.4)
    total, truncated = len(rep.items), False
    if len(rep.items) > MAX_ITEMS:
        truncated = True
        rank = {"FAIL": 0, "INCOMPLETE": 1, "WARN": 2}
        if informational:
            # the total line is kept, and the truncation says how many of how many (R2-L03)
            keep = [i for i in rep.items if i["check"] == "COVERAGE" and i["path"] == "total"]
            rest = [i for i in rep.items if i not in keep]
            rep.items = rest[:MAX_ITEMS - 1 - len(keep)] + keep
            rep.add("INFO", "BUDGET", "report", "report truncated: %d of %d items printed" % (len(rep.items), total))
        else:
            # failures first; one slot kept for the truncation item, so the report holds at most MAX_ITEMS items (C6)
            rep.items = sorted(rep.items, key=lambda i: rank.get(i["status"], 3))[:MAX_ITEMS - 1]
            rep.add("INCOMPLETE", "BUDGET", "report", "more than %d report items; truncated (%d in all)" % (MAX_ITEMS, total))
    if args.json:          # outputs first, the summary after: a report that cannot be written is ERROR 2 (AST-M03)
        data = json.loads(rep.json())
        data.update({"truncated": truncated, "total": total})
        if informational:
            data["outcome"] = "REPORT"            # informational: no checker outcome (R2-L03)
        try:
            dl.write_output(args.json, json.dumps(data, indent=1, default=str).encode("utf-8"))    # R2-M03
        except dl.InputError as exc:
            rep.error = "ERROR"
            informational = False
            rep.add("INFO", "OUT", args.json, "the report could not be written: %s" % exc)
    if informational:
        rows = ["%-14s %-6s %-48s %s" % (i["status"], i["check"], i["path"], i["detail"]) for i in rep.items]
        print("\n".join(rows + ["", "check_css: report only, exit 0 (%d items%s)" % (len(rep.items), "; truncated" if truncated else "")]))
        return 0
    print(rep.text())
    return dl.EXIT[rep.outcome()]


if __name__ == "__main__":
    sys.exit(main())
