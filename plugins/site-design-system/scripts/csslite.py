"""A small read-only CSS reader for the site-design-system checks (plan 0.4 B.7.2).

Grammar: style rules; nested @media (conditions recorded); :root custom properties and var() of them.
@font-face is read as font evidence; @keyframes is kept for the role check; @view-transition and @page
are reviewed as non-binding and listed; any other at-rule (@supports, @layer, @container, @scope,
@import, ...) is returned as unsupported so the checkers report INCOMPLETE. No CSS nesting."""
import re

NONBINDING = ("@view-transition", "@page")


class Rule:
    __slots__ = ("media", "selectors", "decls", "line", "important")

    def __init__(self, media, selectors, decls, line, important=frozenset()):
        # important: the properties this rule declares with !important (the value itself keeps no marker; R2-M13)
        self.media, self.selectors, self.decls, self.line, self.important = media, selectors, decls, line, important


def important_props(body):
    """The properties a declaration block marks !important (R2-M13: an importance-dependent value is not decided by
    reading the declarations in order)."""
    out = set()
    for part in split_top(body, ";"):
        if ":" in part:
            p, v = part.split(":", 1)
            if re.search(r"!\s*important\s*$", v.strip(), re.I):
                out.add(p.strip() if p.strip().startswith("--") else p.strip().lower())
    return frozenset(out)


class Sheet:
    def __init__(self):
        self.rules, self.font_faces, self.keyframes = [], [], {}
        self.nonbinding, self.unsupported = [], []


def _strip_comments(css):
    out, i, n, quote = [], 0, len(css), None
    while i < n:
        ch = css[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(css[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif css.startswith("/*", i):
            j = css.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("\n" * css.count("\n", i, j))
            i = j
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _match_brace(text, start):
    level, i, quote = 0, start, None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            level += 1
        elif ch == "}":
            level -= 1
            if level == 0:
                return i
        i += 1
    raise ValueError("unbalanced braces")


def split_top(s, sep):
    out, level, cur, quote = [], 0, "", None
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([":
            level += 1
        elif ch in ")]":
            level -= 1
        if ch == sep and level == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _unquoted_brace(text):
    quote = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "{}":
            return True
        i += 1
    return False


PROPERTY = re.compile(r"^(--[A-Za-z0-9_-]+|-?[A-Za-z][A-Za-z0-9-]*)$")


def parse_decls(body, bad=None):
    """Declarations of a block. A part that holds a nested block (CSS nesting) or whose property is not a plain
    identifier (an escaped name such as c\\6f lor) is outside the grammar: it goes to `bad` (reported unsupported)."""
    decls = []
    for part in split_top(body, ";"):
        if _unquoted_brace(part):
            if part.strip() and part.strip() != "}" and bad is not None:
                bad.append(part.strip()[:60])
            continue
        if ":" in part:
            p, v = part.split(":", 1)
            if not PROPERTY.match(p.strip()):
                if bad is not None:
                    bad.append(p.strip()[:60])
                continue
            v = re.sub(r"\s*!important\s*$", "", v.strip(), flags=re.I)
            decls.append((p.strip().lower() if not p.strip().startswith("--") else p.strip(), re.sub(r"\s+", " ", v)))
        elif part.strip() and bad is not None:
            bad.append(part.strip()[:60])
    return decls


def parse(css):
    css = _strip_comments(css)
    sheet = Sheet()

    def walk(text, offset, media):
        k = 0
        while k < len(text):
            semi, brace = text.find(";", k), text.find("{", k)
            if brace < 0 and semi < 0:
                break
            if semi >= 0 and (brace < 0 or semi < brace):
                stmt = text[k:semi].strip()
                if stmt.startswith("@"):  # statement at-rules: @import, @charset, @layer a, b; ...
                    if not stmt.lower().startswith("@charset"):
                        sheet.unsupported.append("%s (line %d)" % (stmt.split()[0], css.count("\n", 0, offset + k) + 1))
                k = semi + 1
                continue
            end = _match_brace(text, brace)
            prelude, body = text[k:brace].strip(), text[brace + 1:end]
            line = css.count("\n", 0, offset + k + len(text[k:brace]) - len(text[k:brace].lstrip())) + 1
            low = prelude.lower()
            bad = []
            if low.startswith("@media"):
                cond = prelude[6:].strip()
                walk(body, offset + brace + 1, (media + " and " if media else "") + cond)
            elif low.startswith("@font-face"):
                sheet.font_faces.append({"media": media, "decls": parse_decls(body, bad), "line": line})
            elif low.startswith("@keyframes") or low.startswith("@-webkit-keyframes"):
                name = prelude.split(None, 1)[1].strip() if " " in prelude else ""
                frames, j = [], 0
                while j < len(body):
                    b2 = body.find("{", j)
                    if b2 < 0:
                        break
                    e2 = _match_brace(body, b2)
                    frames.append((body[j:b2].strip(), parse_decls(body[b2 + 1:e2], bad)))
                    j = e2 + 1
                sheet.keyframes[name] = {"media": media, "frames": frames, "line": line}
            elif low.startswith(NONBINDING):
                sheet.nonbinding.append("%s (line %d)" % (prelude.split()[0], line))
            elif low.startswith("@"):
                sheet.unsupported.append("%s (line %d)" % (prelude.split()[0], line))
            else:
                sels = [re.sub(r"\s+", " ", s.strip()) for s in split_top(prelude, ",") if s.strip()]
                sheet.rules.append(Rule(media, sels, parse_decls(body, bad), line, important_props(body)))
            for b in bad:
                sheet.unsupported.append("nested block or escaped property %r (line %d)" % (b, line))
            k = end + 1

    walk(css, 0, "")
    return sheet


def find(sheet, selector, media=""):
    """Merged declarations (last wins) of every rule whose selector list holds `selector` exactly, in a media context."""
    merged, seen = {}, False
    for r in sheet.rules:
        if r.media == media and selector in r.selectors:
            merged.update(dict(r.decls))
            seen = True
    return merged if seen else None


def custom_props(sheet, media=""):
    props = {}
    for r in sheet.rules:
        if r.media == media and ":root" in r.selectors:
            props.update({k: v for k, v in r.decls if k.startswith("--")})
    return props


VAR = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*(?:\([^()]*\)[^()]*)*))?\)")


def resolve_vars(value, props, depth=0):
    """Replace var(--x) by its value from `props`; returns (value, unresolved names)."""
    missing = []
    if depth > 10:
        return value, ["(depth)"]

    def rep(m):
        name, fallback = m.group(1), m.group(2)
        if name in props:
            v, miss = resolve_vars(props[name], props, depth + 1)
            missing.extend(miss)
            return v
        if fallback is not None:
            return fallback.strip()
        missing.append(name)
        return m.group(0)

    out = VAR.sub(rep, value)
    return out, missing


def media_contexts(sheet):
    return sorted({r.media for r in sheet.rules if r.media})


strip_comments = _strip_comments    # shared with check_page.py: references and @font-face sources outside comments
match_brace = _match_brace
