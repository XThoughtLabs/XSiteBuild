"""check_design.py — the design pair of one site: its DESIGN.md and its CSS (plan 0.4 B.7.3).

Usage: check_design.py --site <site design folder> [--verify | --issue] [--css PATH ...] [--deploy-root PATH] [--json FILE]
  --verify (default) writes nothing; --issue also checks the owner's approval (the profile committed at HEAD
  of its Git repository, read-only plumbing) and writes ready.json on PASS.
Stages: P2 parse, P1 trace, P3 token contrast, policy, publication boundary, (issue) approval and receipt.
Outcomes: PASS 0, FAIL 1, ERROR 2, INCOMPLETE 3, INTERNAL 4."""
import argparse
import datetime
import json
import os
import re
import secrets
import subprocess
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import csslite  # noqa: E402
import designlib as dl  # noqa: E402
import policylib as pl  # noqa: E402

VERSION = "0.1.0"
PROFILE_FILES = ("site.yaml", "DESIGN.md", "trace-map.yaml", "contrast.yaml", "policy.yaml", "waivers.yaml")
TYPO_PROPS = {"fontSize": "font-size", "fontWeight": "font-weight", "lineHeight": "line-height",
              "letterSpacing": "letter-spacing"}
TYPO_KEYS = set(TYPO_PROPS) | {"fontFamily", "fontFeature", "fontVariation"}
TYPO_VAR_KEYS = ("fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing")   # generate_css.py's variables
COMPONENT_KEYS = {"backgroundColor", "textColor", "typography", "rounded", "padding", "size", "height", "width"}
FLOOR_SECTIONS = ("fonts", "roles", "reserved")
POLICY_SECTIONS = ("roles", "reserved", "extras", "derived_vars", "fonts", "headings", "labels",
                   "forbidden_text_colours", "fills", "measure", "capitals", "scheme", "buttons",
                   "accessibility", "tiers", "decisions")
FLOOR_ASSERTIONS = ("A1", "A6", "A10")
# A12's rules have their own tiers (policy.accessibility.tiers); it takes no assertion tier (AUD-F09)
NON_FLOOR = ("A2", "A3", "A4", "A5", "A7", "A8", "A9", "A11", "A13")
TIERS = ("blocking", "waivable", "advisory")
A11Y_TIERS = ("blocking", "advisory")
ROLE_KEYS = ("color", "background-color", "border-color", "outline-color", "box-shadow", "fill", "stroke")
FACE_STYLES = ("normal", "italic", "oblique")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Ambiguous(str):
    """A P1 detail that gives INCOMPLETE, not FAIL: a binding declared several times with different values (AST-M08)."""


class Ctx:
    def __init__(self, args):
        self.args, self.site = args, os.path.realpath(args.site)
        self.snap, self.rep = dl.Snapshot(), dl.Report("check_design")
        self.data = {}
        self.font_digests = {}     # face file (as the policy writes it) -> SHA-256, read once

    def path(self, name):
        return os.path.join(self.site, name)

    def fail(self, check, path, detail, **kw):
        self.rep.add("FAIL", check, path, detail, **kw)

    def ok(self, check, path, detail, **kw):
        self.rep.add("PASS", check, path, detail, **kw)

    def problem(self, check, path, detail, **kw):
        self.rep.add("INCOMPLETE" if isinstance(detail, Ambiguous) else "FAIL", check, path, detail, **kw)


def as_list(x):
    return x if isinstance(x, list) else [x]


def site_path(ctx, p):
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(ctx.site, p))


# ------------------------------------------------------------------ P2: parse and schemas

def p2_parse(ctx):
    for name in PROFILE_FILES:
        if not os.path.exists(ctx.path(name)):
            raise dl.InputError("missing %s in %s" % (name, ctx.site))
    site = dl.load_yaml_text(ctx.snap.text(ctx.path("site.yaml")), "site.yaml")
    fm, _body = dl.split_front_matter(ctx.snap.text(ctx.path("DESIGN.md")))
    design = dl.load_yaml_text(fm, "DESIGN.md front matter")
    tmap = dl.load_yaml_text(ctx.snap.text(ctx.path("trace-map.yaml")), "trace-map.yaml")
    contrast = dl.load_yaml_text(ctx.snap.text(ctx.path("contrast.yaml")), "contrast.yaml")
    policy = dl.load_yaml_text(ctx.snap.text(ctx.path("policy.yaml")), "policy.yaml")
    waivers = dl.load_yaml_text(ctx.snap.text(ctx.path("waivers.yaml")), "waivers.yaml")
    ctx.data = dict(site=site, design=design, tmap=tmap, contrast=contrast, policy=policy, waivers=waivers)
    problems = []
    for key in ("name", "source", "css"):
        if key not in site:
            problems.append("site.yaml lacks %s" % key)
    if site.get("source") not in ("css", "design"):
        problems.append("site.yaml source must be css or design")
    for g in dl.GROUPS:
        if not isinstance(design.get(g), dict) or not design.get(g):
            problems.append("DESIGN.md group %s is missing or empty" % g)
    for p in problems:
        ctx.fail("P2", "schema", p)
    if problems:
        return False
    groups = {g: design[g] for g in dl.GROUPS}
    for g in dl.GROUPS:
        for name, value in design[g].items():
            path = "%s.%s" % (g, name)
            if not dl.TOKEN_NAME.match(str(name)):
                ctx.fail("P2", path, "token name must be lowercase letters, digits and single hyphens")
            if g == "colors":
                v = value
                try:
                    v = dl.resolve(value, groups)
                except dl.ContentError as exc:
                    ctx.fail("P2", path, str(exc))
                    continue
                if dl.parse_colour(v) is None:
                    ctx.fail("P2", path, "%r is not a supported colour" % (value,))
            elif g in ("rounded", "spacing"):
                try:
                    v = dl.resolve(value, groups)
                except dl.ContentError as exc:
                    ctx.fail("P2", path, str(exc))
                    continue
                if dl.parse_dimension(v) is None:      # a reference is typed by its target (AUD-F06)
                    ctx.fail("P2", path, "%r is not a dimension in px, em or rem" % (value,))
            elif g == "typography":
                if not isinstance(value, dict):
                    ctx.fail("P2", path, "typography token is not a mapping")
                    continue
                for k, v in value.items():
                    if k not in TYPO_KEYS:
                        ctx.fail("P2", "%s.%s" % (path, k), "unknown typography property")
                    elif k == "lineHeight" and not isinstance(v, str):
                        ctx.fail("P2", "%s.%s" % (path, k), "lineHeight must be a quoted string (Google's 0.4.0 model drops bare numbers)")
                    elif k in ("fontSize", "letterSpacing") and dl.parse_dimension(v) is None:
                        ctx.fail("P2", "%s.%s" % (path, k), "%r is not a dimension in px, em or rem" % (v,))
                    elif k == "fontWeight" and not isinstance(v, int):
                        ctx.fail("P2", "%s.%s" % (path, k), "fontWeight must be a number")
            elif g == "components":
                if not isinstance(value, dict):
                    ctx.fail("P2", path, "component is not a mapping")
                    continue
                for k, v in value.items():
                    if k not in COMPONENT_KEYS:
                        ctx.fail("P2", "%s.%s" % (path, k), "unknown component property")
                        continue
                    try:
                        rv = dl.resolve(v, groups)
                    except dl.ContentError as exc:
                        ctx.fail("P2", "%s.%s" % (path, k), str(exc))
                        continue
                    # every field is typed by what it resolves to (AUD-F06): a dimension as textColor is a P2 FAIL
                    if k in ("backgroundColor", "textColor") and dl.parse_colour(rv) is None:
                        ctx.fail("P2", "%s.%s" % (path, k), "%r is not a colour or a reference to one" % (v,))
                    elif k in ("rounded", "size", "height", "width") and dl.parse_dimension(rv) is None:
                        ctx.fail("P2", "%s.%s" % (path, k), "%r is not a dimension in px, em or rem or a reference to one" % (v,))
                    elif k == "typography" and not (dl.is_ref(v) and isinstance(rv, dict)):
                        ctx.fail("P2", "%s.%s" % (path, k), "%r is not a reference to a typography token" % (v,))
                    elif k == "padding" and not isinstance(rv, str):
                        ctx.fail("P2", "%s.%s" % (path, k), "padding must be a string")
    for g in dl.GROUPS:  # binding coverage both ways (vacuity guard)
        fields, mapped = design[g], tmap.get(g) or {}
        if not isinstance(mapped, dict):
            ctx.fail("P2", "trace-map.%s" % g, "is not a mapping")
            continue
        for name in mapped:
            if name not in fields:
                ctx.fail("P2", "%s.%s" % (g, name), "bound in trace-map.yaml but absent from DESIGN.md")
        for name, value in fields.items():
            if name not in mapped:
                ctx.fail("P2", "%s.%s" % (g, name), "in DESIGN.md but without a binding")
            elif g == "components" and isinstance(value, dict):
                if not isinstance(mapped[name], dict):
                    ctx.fail("P2", "%s.%s" % (g, name), "the component's bindings are not a mapping")
                    continue
                for k in mapped[name]:
                    if k not in value:
                        ctx.fail("P2", "%s.%s.%s" % (g, name, k), "bound but absent from DESIGN.md")
                for k in value:
                    if k not in mapped[name]:
                        ctx.fail("P2", "%s.%s.%s" % (g, name, k), "in DESIGN.md but without a binding")
    check_binding_shapes(ctx, design, tmap)
    return ctx.rep.count("FAIL") == 0


def check_binding_shapes(ctx, design, tmap):
    """A binding that names no selector, no property or no variable binds nothing: refused in P2 (AST-M07)."""
    def text(x):
        return isinstance(x, str) and x.strip() != ""

    def bad(path, why):
        ctx.fail("P2", path, why)

    def binding(path, b, typography=False, token=None):
        if not isinstance(b, dict) or not b:
            return bad(path, "the binding is not a non-empty mapping")
        if "sel" in b and not (text(b["sel"]) or (isinstance(b["sel"], list) and b["sel"] and all(text(s) for s in b["sel"]))):
            bad(path, "sel names no selector (an empty selector binds nothing)")
        if "sel" in b and not typography and not text(b.get("prop")):
            bad(path, "sel without a property (prop)")
        if "var" in b and not (text(b["var"]) and b["var"].startswith("--")):
            bad(path, "var is not a custom property name")
        if "inherit" in b and not (isinstance(b["inherit"], list) and b["inherit"] and all(text(s) for s in b["inherit"])):
            bad(path, "inherit names no selector")
        if "host" in b and not (text(b["host"]) and text(b.get("own"))):
            bad(path, "a host surface needs host and own selectors")
        if "vars" in b:
            v = b["vars"]
            if not isinstance(v, dict) or not v or not all(text(x) and x.startswith("--") for x in v.values()):
                bad(path, "vars is not a non-empty mapping of properties to custom property names")
            elif isinstance(token, dict):
                for key in token:
                    if key in TYPO_VAR_KEYS and key not in v:
                        bad("%s.%s" % (path, key), "a property of the token without a variable in vars")
                for key in v:
                    if key not in token:
                        bad("%s.%s" % (path, key), "vars names a property the token lacks")
        if typography and token is not None and not ({"sel", "vars"} & set(b)):
            bad(path, "a typography binding needs sel or vars")

    for g in ("colors", "rounded", "spacing", "typography"):
        for name, b in (tmap.get(g) or {}).items() if isinstance(tmap.get(g), dict) else []:
            if name in design[g]:
                binding("%s.%s" % (g, name), b, typography=(g == "typography"), token=design[g][name] if g == "typography" else None)
    for name, fields in (tmap.get("components") or {}).items() if isinstance(tmap.get("components"), dict) else []:
        if not isinstance(fields, dict) or not fields:
            bad("components.%s" % name, "a component without bound fields")
            continue
        for k, b in fields.items():
            binding("components.%s.%s" % (name, k), b, typography=(k == "typography"))
    for i, o in enumerate(tmap.get("overrides") or []):
        if not isinstance(o, dict) or not all(text(str(o.get(k, ""))) for k in ("sel", "media", "prop", "value")):
            bad("overrides[%d]" % i, "an override needs sel, media, prop and value")


# ------------------------------------------------------------------ P1: trace

VAR_NAME = re.compile(r"var\(\s*(--[\w-]+)")


class Css:
    def __init__(self, ctx, paths):
        self.sheets = []
        for p in paths:
            try:
                self.sheets.append((p, csslite.parse(ctx.snap.text(p))))
            except ValueError as exc:        # unbalanced braces: the site CSS is unusable as input (AUD-F06)
                raise dl.InputError("the site CSS %s cannot be read: %s" % (p, exc))
        merged = csslite.Sheet()
        for _, s in self.sheets:
            merged.rules += s.rules
            merged.font_faces += s.font_faces
            merged.keyframes.update(s.keyframes)
            merged.nonbinding += s.nonbinding
            merged.unsupported += s.unsupported
        self.sheet = merged
        self.root = csslite.custom_props(merged)

    def props(self, media=""):
        p = dict(self.root)
        if media:
            p.update(csslite.custom_props(self.sheet, media))
        return p

    def decls(self, sel, media=""):
        """(merged declarations of the rules whose selector list holds sel, the properties declared there with
        different values), or (None, set()) when no rule matches. The checker does not decide which of several
        different declarations applies (AST-M08)."""
        merged, values, seen = {}, {}, False
        for r in self.sheet.rules:
            if r.media == media and sel in r.selectors:
                seen = True
                for k, v in r.decls:
                    values.setdefault(k, set()).add(dl.typed(v))
                    merged[k] = v
        if not seen:
            return None, set()
        return merged, {k for k, vs in values.items() if len(vs) > 1}

    def ambiguous_var(self, name, media=""):
        """True when :root declares the variable several times with different values in the context that supplies it
        (the media context when it declares the variable, else the top level)."""
        def vals(m):
            return {dl.typed(v) for r in self.sheet.rules if ":root" in r.selectors and r.media == m for k, v in r.decls if k == name}
        return len(vals(media) if media and vals(media) else vals("")) > 1

    def var_values(self, name, media=""):
        """Every definition of a variable in :root, in the context that supplies it (as ambiguous_var reads it)."""
        def vals(m):
            return [v for r in self.sheet.rules if ":root" in r.selectors and r.media == m for k, v in r.decls if k == name]
        return vals(media) if media and vals(media) else vals("")

    def important_var(self, name, media=""):
        rules = [r for r in self.sheet.rules if ":root" in r.selectors and r.media in ("", media)]
        return any(name in r.important for r in rules)

    def var_graph_problem(self, name, media=""):
        """None, or why the value of a variable is not decided by reading the declarations P1 reads (R2-M13): it, or any
        variable it reaches through var() (every definition followed, every branch), is declared several times with
        different values or with !important in the context that supplies it."""
        seen, stack = set(), [name]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            if self.ambiguous_var(n, media):
                return "%s is declared several times with different values" % n
            if self.important_var(n, media):
                return "%s is declared with !important" % n
            for v in self.var_values(n, media):
                stack.extend(VAR_NAME.findall(v))
        return None

    def refs_problem(self, value, media=""):
        """var_graph_problem for every variable a declared value refers to (R2-M13)."""
        for n in VAR_NAME.findall(value or ""):
            why = self.var_graph_problem(n, media)
            if why:
                return why
        return None

    def value(self, sel, prop, media=""):
        decls, amb = self.decls(sel, media)
        if decls is None:
            return None, "selector %r not found%s" % (sel, " in @media " + media if media else "")
        if prop not in decls:
            alt = {"background": "background-color"}.get(prop)
            if alt and alt in decls:
                prop = alt
            else:
                return None, "%r declares no %s" % (sel, prop)
        if prop in amb:
            return None, Ambiguous("%r declares %s several times with different values%s: which one applies is not decided here"
                                   % (sel, prop, " in @media " + media if media else ""))
        why = self.refs_problem(decls[prop], media)        # through the whole variable graph (R2-M13)
        if why:
            return None, Ambiguous("%r %s depends on %s: which value applies is not decided here" % (sel, prop, why))
        v, missing = csslite.resolve_vars(decls[prop], self.props(media))
        if missing:
            return None, "%r %s uses undefined %s" % (sel, prop, ", ".join(missing))
        return v, None


def p1_trace(ctx, css):
    d, tmap = ctx.data["design"], ctx.data["tmap"]
    groups = {g: d[g] for g in dl.GROUPS}
    for item in css.sheet.unsupported:
        ctx.rep.add("INCOMPLETE", "P1", "css", "unsupported at-rule %s: bindings inside it are not checked" % item)
    for item in css.sheet.nonbinding:
        ctx.rep.add("INFO", "P1", "css", "reviewed non-binding at-rule %s" % item)

    def literal(value):
        try:
            return dl.resolve(value, groups)
        except dl.ContentError:
            return None

    def check_simple(path, value, b):
        kind = b.get("kind", "exact")
        if "ref" in b and str(value).strip() != b["ref"]:
            return ctx.fail("P1", path, "is %r; the map expects the reference %r" % (value, b["ref"]), kind=kind)
        lit = literal(value)
        media = b.get("media", "")
        if "var" in b:
            props = css.props(media)
            if b["var"] not in props:
                return ctx.fail("P1", path, ":root declares no %s%s" % (b["var"], " in @media " + media if media else ""), kind=kind)
            graph = css.var_graph_problem(b["var"], media)      # the bound variable and every variable it reaches (R2-M13)
            if graph:
                return ctx.problem("P1", path, Ambiguous("%s: %s, so which value applies is not decided here" % (b["var"], graph)), kind=kind)
            cv, missing = csslite.resolve_vars(props[b["var"]], props)
            if missing:
                return ctx.fail("P1", path, "%s uses undefined %s" % (b["var"], ", ".join(missing)), kind=kind)
            if dl.same(cv, lit):
                return ctx.ok("P1", path, "%s = %s" % (b["var"], cv), kind=kind, projection="var")
            return ctx.fail("P1", path, "%s = %s but DESIGN.md has %s" % (b["var"], cv, lit), kind=kind)
        if "sel" not in b:
            if set(b) <= {"ref", "kind", "note"} and "ref" in b:
                return ctx.ok("P1", path, "alias of %s" % b["ref"], kind="alias")
            return ctx.fail("P1", path, "binding has neither var nor sel", kind=kind)
        for sel in as_list(b["sel"]):
            cv, err = css.value(sel, b["prop"], media)
            if err:
                ctx.problem("P1", path, err, kind=kind)
                continue
            if "pattern" in b:
                m = re.search(b["pattern"], cv)
                if not m:
                    ctx.fail("P1", path, "%s %s = %s does not match %s" % (sel, b["prop"], cv, b["pattern"]), kind=kind)
                    continue
                cv = m.group(1)
            if dl.same(cv, lit):
                ctx.ok("P1", path, "%s { %s: %s }" % (sel, b["prop"], cv), kind=kind, projection="literal")
            else:
                ctx.fail("P1", path, "%s { %s: %s } but DESIGN.md has %s" % (sel, b["prop"], cv, lit), kind=kind)

    def first_family(fam):
        return fam.split(",")[0].strip().strip("\"'")

    def inherited(path, key, want, chain, own_sel):
        """Compare one typography property that own_sel does not declare with the first rule along the named
        inheritance chain that does (AST-M08, AUD-F07(1)); none declaring it is a FAIL."""
        prop = "font-family" if key == "fontFamily" else TYPO_PROPS[key]
        for sel in chain:
            decls, amb = css.decls(sel)
            if decls is None or prop not in decls:
                continue
            if prop in amb:
                return ctx.problem("P1", path, Ambiguous("%s declares %s several times with different values" % (sel, prop)), kind="inherited")
            why = css.refs_problem(decls[prop])        # every inheritance branch through the variable graph (R2-M13)
            if why:
                return ctx.problem("P1", path, Ambiguous("%s %s depends on %s" % (sel, prop, why)), kind="inherited")
            cv = csslite.resolve_vars(decls[prop], css.root)[0]
            ok = first_family(cv) == str(want) if key == "fontFamily" else (
                dl.same(cv, want) or (key == "fontSize" and dl.clamp_parts(cv) is not None and dl.clamp_parts(cv)[2] == dl.typed(want)))
            return (ctx.ok if ok else ctx.fail)("P1", path, "%s inherits %s: %s from %s%s" % (own_sel, prop, cv, sel, "" if ok else " but the token has %s" % want), kind="inherited")
        return ctx.fail("P1", path, "%s declares no %s and no rule along %s does" % (own_sel, prop, " > ".join(chain)), kind="inherited")

    def check_typo_values(path, token, sels, clamp_expr=None):
        body_family = css.value("body", "font-family")[0] or ""
        for key, value in token.items():
            p = "%s.%s" % (path, key)
            if key == "fontFamily":
                for sel in sels:
                    own, amb = css.decls(sel)
                    own = own or {}
                    if "font-family" in amb:
                        ctx.problem("P1", p, Ambiguous("%s declares font-family several times with different values" % sel))
                        continue
                    if "font-family" in own:
                        fam = csslite.resolve_vars(own["font-family"], css.root)[0]
                        kind = "exact"
                    else:
                        fam, kind = body_family, "inherited"
                    first = first_family(fam)
                    (ctx.ok if first == str(value) else ctx.fail)("P1", p, "%s font-family starts with %s%s" % (sel, first, "" if first == str(value) else " but DESIGN.md has %s" % value), kind=kind)
                continue
            if key not in TYPO_PROPS:
                ctx.rep.add("INFO", "P1", p, "no CSS binding for %s" % key)
                continue
            prop = TYPO_PROPS[key]
            for sel in sels:
                cv, err = css.value(sel, prop)
                if err:
                    ctx.problem("P1", p, err)
                    continue
                if key == "fontSize" and clamp_expr:
                    parts = dl.clamp_parts(clamp_expr)
                    if parts is None:
                        ctx.fail("P1", p, "clamp_expr %r is not a clamp()" % clamp_expr, kind="derived")
                    elif not dl.same(cv, clamp_expr):
                        ctx.fail("P1", p, "%s font-size = %s but clamp_expr is %s" % (sel, cv, clamp_expr), kind="derived")
                    elif parts[2] != dl.typed(value):
                        ctx.fail("P1", p, "DESIGN.md fontSize %s is not the clamp maximum of %s" % (value, clamp_expr), kind="derived")
                    else:
                        ctx.ok("P1", p, "%s font-size: %s (upper bound %s)" % (sel, cv, value), kind="derived")
                    continue
                (ctx.ok if dl.same(cv, value) else ctx.fail)("P1", p, "%s { %s: %s }%s" % (sel, prop, cv, "" if dl.same(cv, value) else " but DESIGN.md has %s" % value))
        for sel in sels:
            decls = csslite.find(css.sheet, sel) or {}
            for key, prop in TYPO_PROPS.items():
                if prop in decls and key not in token:
                    ctx.fail("P1", "%s.%s" % (path, key), "%s sets %s: %s but the token has no %s" % (sel, prop, decls[prop], key))

    def check_component(path, value, b, comp_value):
        if "host" in b:
            if "ref" in b and str(value).strip() != b["ref"]:
                return ctx.fail("P1", path, "is %r; the map expects %r" % (value, b["ref"]), kind="host")
            own = csslite.find(css.sheet, b["own"]) or {}
            if "background" in own or "background-color" in own:
                return ctx.fail("P1", path, "%s declares its own background; a host surface is wrong here" % b["own"], kind="host")
            cv, err = css.value(b["host"], "background")
            if err:
                return ctx.problem("P1", path, err, kind="host")
            lit = literal(value)
            ok = dl.same(cv, lit)
            return (ctx.ok if ok else ctx.fail)("P1", path, "%s sits on %s (%s)%s" % (b["own"], b["host"], cv, "" if ok else " but DESIGN.md has %s" % lit), kind="host")
        if "inherit" in b:
            if "ref" in b and str(value).strip() != b["ref"]:
                return ctx.fail("P1", path, "is %r; the map expects %r" % (value, b["ref"]), kind="inherited")
            for sel in b["inherit"]:
                decls, amb = css.decls(sel)
                decls = decls or {}
                if "color" in decls:
                    why = ("%s declares color several times with different values" % sel) if "color" in amb else css.refs_problem(decls["color"])
                    if why:                 # an inherited colour is not decided last-wins either (R2-M13)
                        return ctx.problem("P1", path, Ambiguous("%s inherits color through %s" % (b["inherit"][0], why)), kind="inherited")
                    cv = csslite.resolve_vars(decls["color"], css.root)[0]
                    lit = literal(value)
                    ok = dl.same(cv, lit)
                    return (ctx.ok if ok else ctx.fail)("P1", path, "%s inherits color %s from %s%s" % (b["inherit"][0], cv, sel, "" if ok else " but DESIGN.md has %s" % lit), kind="inherited")
            return ctx.fail("P1", path, "no colour along %s" % " > ".join(b["inherit"]), kind="inherited")
        if path.endswith(".typography"):
            if "ref" not in b or str(value).strip() != b["ref"]:
                return ctx.fail("P1", path, "is %r; the map expects %r" % (value, b.get("ref")))
            token = literal(value)
            if not isinstance(token, dict):
                return ctx.fail("P1", path, "reference %s is not a typography token" % value)
            if "sel" not in b:
                site = ctx.data["site"]
                if site.get("source") == "design" and not site.get("component_stylesheets"):
                    return ctx.ok("P1", path, "reference %s (no component stylesheets yet: documented only)" % value, kind="reference")
                return ctx.fail("P1", path, "component typography needs the component's selector (sel) to be checked against CSS")
            chain = as_list(b.get("inherit") or ["body"])
            for sel in as_list(b["sel"]):
                decls, amb = css.decls(sel)
                if decls is None:
                    ctx.fail("P1", path, "selector %r not found" % sel)
                    continue
                declared = 0
                for key, prop in TYPO_PROPS.items():
                    if prop in decls:
                        declared += 1
                        if prop in amb:
                            ctx.problem("P1", "%s.%s" % (path, key), Ambiguous("%s declares %s several times with different values" % (sel, prop)))
                            continue
                        why = css.refs_problem(decls[prop])      # R2-M13
                        if why:
                            ctx.problem("P1", "%s.%s" % (path, key), Ambiguous("%s %s depends on %s" % (sel, prop, why)))
                            continue
                        cv = csslite.resolve_vars(decls[prop], css.root)[0]
                        want = token.get(key)
                        if want is None:
                            ctx.fail("P1", "%s.%s" % (path, key), "%s sets %s: %s, absent from %s" % (sel, prop, cv, value))
                        elif dl.same(cv, want) or (key == "fontSize" and dl.clamp_parts(cv) and dl.clamp_parts(cv)[2] == dl.typed(want)):
                            ctx.ok("P1", "%s.%s" % (path, key), "%s { %s: %s } = %s" % (sel, prop, cv, value))
                        else:
                            ctx.fail("P1", "%s.%s" % (path, key), "%s { %s: %s } but %s has %s" % (sel, prop, cv, value, want))
                for key, prop in TYPO_PROPS.items():
                    if key in token and prop not in decls:
                        if declared:      # a subset of the token's properties is not the token (AUD-F07(1))
                            ctx.fail("P1", "%s.%s" % (path, key), "%s declares part of %s but not %s" % (sel, value, prop))
                        else:             # nothing declared: every property is checked along the inheritance chain
                            inherited("%s.%s" % (path, key), key, token[key], chain, sel)
                if "fontFamily" in token:     # the family is compared too: declared here, or inherited along the chain
                    if "font-family" in amb:
                        ctx.problem("P1", "%s.fontFamily" % path, Ambiguous("%s declares font-family several times with different values" % sel))
                    elif "font-family" in decls:
                        fam = first_family(csslite.resolve_vars(decls["font-family"], css.root)[0])
                        ok = fam == str(token["fontFamily"])
                        (ctx.ok if ok else ctx.fail)("P1", "%s.fontFamily" % path, "%s font-family starts with %s%s" % (sel, fam, "" if ok else " but %s has %s" % (value, token["fontFamily"])))
                    else:
                        inherited("%s.fontFamily" % path, "fontFamily", token["fontFamily"], chain, sel)
                elif "font-family" in decls:
                    ctx.fail("P1", "%s.fontFamily" % path, "%s sets font-family, absent from %s" % (sel, value))
            return None
        if set(b) <= {"ref"}:
            ok = str(value).strip() == b["ref"]
            return (ctx.ok if ok else ctx.fail)("P1", path, "reference %s%s" % (value, "" if ok else "; the map expects %s" % b["ref"]))
        return check_simple(path, value, b)

    for g in dl.GROUPS:
        mapped = tmap.get(g) or {}
        for name, value in d[g].items():
            if name not in mapped:
                continue
            b = mapped[name]
            path = "%s.%s" % (g, name)
            if g == "typography":
                if "vars" in b:  # design-first: each property bound to a generated variable
                    for key, var in b["vars"].items():
                        props = css.props()
                        cv = csslite.resolve_vars(props.get(var, ""), props)[0] if var in props else None
                        want = b.get("clamp_expr") if key == "fontSize" and b.get("clamp_expr") else value.get(key)
                        if cv is None:
                            ctx.fail("P1", "%s.%s" % (path, key), ":root declares no %s" % var)
                        elif key == "fontFamily":
                            first = cv.split(",")[0].strip().strip("\"'")
                            (ctx.ok if first == str(want) else ctx.fail)("P1", "%s.%s" % (path, key), "%s = %s" % (var, cv), kind="exact")
                        elif key == "fontSize" and b.get("clamp_expr") and dl.same(cv, want) and (
                                dl.clamp_parts(want) is None or dl.clamp_parts(want)[2] != dl.typed(value.get(key))):
                            # design-first too: DESIGN.md keeps the fluid size's upper bound (AST-M08)
                            ctx.fail("P1", "%s.%s" % (path, key), "%s = %s, but DESIGN.md fontSize %s is not its clamp maximum" % (var, cv, value.get(key)), kind="derived")
                        else:
                            (ctx.ok if dl.same(cv, want) else ctx.fail)("P1", "%s.%s" % (path, key), "%s = %s" % (var, cv), kind="exact")
                else:
                    check_typo_values(path, value, as_list(b["sel"]), b.get("clamp_expr"))
            elif g == "components":
                for key, v in value.items():
                    if key in b:
                        check_component("%s.%s" % (path, key), v, b[key], value)
            else:
                check_simple(path, value, b)
    for o in tmap.get("overrides") or []:
        path = "override %s @media %s %s" % (o.get("sel"), o.get("media"), o.get("prop"))
        cv, err = css.value(o.get("sel", ""), o.get("prop", ""), o.get("media", ""))
        if err:
            ctx.problem("P1", path, err)
        else:
            want = csslite.resolve_vars(str(o.get("value")), css.props(o.get("media", "")))[0]
            (ctx.ok if dl.same(cv, want) else ctx.fail)("P1", path, "%s (expected %s)" % (cv, o.get("value")))


BUTTONS_SELECTORS_ONLY = "selectors-only"    # buttons.paint: identify primary buttons by their selectors alone (R2-M06)


def policy_shape_problems(pol):
    """[(where, why)] for every value of policy.yaml whose type is not the schema's, checked before any entry is read
    (R2-M06): a wrong type anywhere is a named POL FAIL, never an internal error. A section may be {off: reason}
    (whether it may be off is checked later); a missing section or key is checked later too."""
    out = []

    def is_str(v):
        return isinstance(v, str)

    def is_num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    def is_int(v):
        return isinstance(v, int) and not isinstance(v, bool)

    def strs(v, null=False):
        return (null and v is None) or (isinstance(v, list) and all(isinstance(x, str) for x in v))

    def want(ok, where, why):
        if not ok:
            out.append((where, why))
        return ok

    def record(v, where, fields, null=False):
        """v is a mapping whose known keys have the given checks (key -> (check, what)); unknown keys are not types."""
        if null and v is None:
            return
        if not want(isinstance(v, dict), where, "must be a mapping"):
            return
        for k, (check, what) in fields.items():
            if k in v:
                want(check(v[k]), "%s.%s" % (where, k), "must be %s" % what)

    def is_off(v):
        return isinstance(v, dict) and set(v) == {"off"}

    def section(name, check):
        if name in pol and not is_off(pol[name]):
            check(pol[name], name)

    def roles(v, w):
        if want(isinstance(v, dict), w, "must be a mapping of schemes"):
            for sc, rp in v.items():
                if rp is not None and want(isinstance(rp, dict), "%s.%s" % (w, sc), "must be a mapping of roles"):
                    for prop, toks in rp.items():
                        want(strs(toks, null=True), "%s.%s.%s" % (w, sc, prop), "must be a list of token names")

    def entries(check):
        def run(v, w):
            if want(isinstance(v, list), w, "must be a list"):
                for i, x in enumerate(v):
                    check(x, "%s[%d]" % (w, i))
        return run

    def extra(x, w):
        record(x, w, {"id": (is_str, "a string"), "rgb": (lambda v: isinstance(v, list) and all(is_int(c) for c in v), "a list of three integers"),
                      "alpha": (lambda v: is_num(v) or (isinstance(v, list) and all(is_num(a) for a in v)), "a number or [low, high]"),
                      "roles": (strs, "a list of roles"), "quote": (is_str, "a string")})

    def derived(x, w):
        record(x, w, {"name": (is_str, "a string"), "roles": (strs, "a list of roles")})

    def face(x, w):
        record(x, w, {"family": (is_str, "a string"), "file": (is_str, "a string"), "sha256": (is_str, "a string"),
                      "postscript": (is_str, "a string"), "style": (is_str, "a string"),
                      "weight": (lambda v: isinstance(v, list) and all(is_int(a) for a in v), "[min, max] integers"),
                      "coverage": (lambda v: isinstance(v, list) and all(isinstance(p, list) and all(is_int(c) for c in p) for p in v),
                                   "a list of [first, last] integer pairs")})

    def fonts(v, w):
        record(v, w, {"faces": (lambda x: isinstance(x, list), "a list of faces"), "stack_vars": (lambda x: strs(x, null=True), "a list of names"),
                      "code_roles": (is_str, "a string"),
                      "fallback_families": (lambda x: x is None or (strs(x) and all(s.strip() for s in x)), "a list of non-empty family names")})
        if isinstance(v, dict) and isinstance(v.get("faces"), list):
            for i, f in enumerate(v["faces"]):
                face(f, "%s.faces[%d]" % (w, i))

    def headings(v, w):
        record(v, w, {"tokens": (strs, "a list of token names"), "selectors": (lambda x: strs(x, null=True), "a list of selectors")})
        if isinstance(v, dict):
            record(v.get("accent"), w + ".accent", {"tokens": (strs, "a list of token names"), "max_share": (is_num, "a number"),
                                                   "max_runs": (is_int, "an integer")}, null=True)

    def labels(v, w):
        record(v, w, {"selectors": (lambda x: strs(x, null=True), "a list of selectors")})
        if isinstance(v, dict):
            record(v.get("style"), w + ".style", {"max_size_px": (is_num, "a number"), "min_weight": (is_int, "an integer")}, null=True)

    def fill(x, w):
        record(x, w, {"tokens": (strs, "a list of token names"), "alpha_above": (is_num, "a number"), "max_area_px2": (is_num, "a number")})

    def measure(v, w):
        record(v, w, {"default_px": (is_num, "a number"), "roles": (lambda x: x is None or isinstance(x, list), "a list")})
        if isinstance(v, dict) and isinstance(v.get("roles"), list):
            for i, x in enumerate(v["roles"]):
                record(x, "%s.roles[%d]" % (w, i), {"selector": (is_str, "a string"), "px": (is_num, "a number")})

    def scheme(v, w):
        record(v, w, {"mode": (is_str, "a string"), "sets": (lambda x: isinstance(x, dict) and all(strs(t) for t in x.values()), "a mapping of token lists"),
                      "pairs": (lambda x: x is None or (isinstance(x, dict) and all(is_str(t) for t in x.values())), "a mapping of token names")})

    def buttons(v, w):
        record(v, w, {"selectors": (lambda x: strs(x, null=True), "a list of selectors"), "max_per_view": (is_int, "an integer"),
                      "paint": (lambda x: x == BUTTONS_SELECTORS_ONLY or (isinstance(x, dict) and all(is_str(t) for t in x.values())),
                                "{background, text} token names, or %s" % BUTTONS_SELECTORS_ONLY)})

    def accessibility(v, w):
        record(v, w, {"tags": (lambda x: strs(x, null=True), "a list of axe tags"), "default": (is_str, "a string"),
                      "tiers": (lambda x: x is None or (isinstance(x, dict) and all(is_str(t) for t in x.values())), "a mapping of rule ids to tiers")})

    if not isinstance(pol, dict):
        return [("policy", "is not a mapping")]
    section("roles", roles)
    section("reserved", lambda v, w: want(strs(v), w, "must be a list of token names"))
    section("extras", entries(extra))
    section("derived_vars", entries(derived))
    section("fonts", fonts)
    section("headings", headings)
    section("labels", labels)
    section("forbidden_text_colours", lambda v, w: want(strs(v), w, "must be a list of token names"))
    section("fills", entries(fill))
    section("measure", measure)
    section("capitals", lambda v, w: want(is_str(v), w, "must be a string (labels-only) or off"))
    section("scheme", scheme)
    section("buttons", buttons)
    section("accessibility", accessibility)
    section("tiers", lambda v, w: want(isinstance(v, dict) and all(is_str(t) for t in v.values()), w, "must be a mapping of assertions to tiers"))
    section("decisions", lambda v, w: want(strs(v), w, "must be a list of strings"))
    return out


def check_reserved_floor(ctx, pol, d):
    """A2's reserved tokens are floor: no profile file may admit them, by name or by colour (plan 0.4 B.6.2)."""
    reserved = [t for t in (pol.get("reserved") or []) if isinstance(pol.get("reserved"), list) and t in d["colors"]]
    if not reserved:
        return
    groups = {g: d[g] for g in dl.GROUPS}

    def colour(t):
        try:
            return dl.parse_colour(dl.resolve(d["colors"].get(t), groups))
        except (dl.ContentError, TypeError):
            return None
    rcol = {t: colour(t) for t in reserved}
    named = []
    roles = pol.get("roles") if isinstance(pol.get("roles"), dict) else {}
    for scheme, rp in roles.items():
        for prop, toks in (rp or {}).items() if isinstance(rp, dict) else []:
            named += [("roles.%s.%s" % (scheme, prop), t) for t in toks or []]
    h = pol.get("headings") if isinstance(pol.get("headings"), dict) else {}
    named += [("headings.tokens", t) for t in h.get("tokens") or []]
    named += [("headings.accent.tokens", t) for t in ((h.get("accent") or {}).get("tokens") or [])]
    for f in pol.get("fills") or [] if isinstance(pol.get("fills"), list) else []:
        named += [("fills.tokens", t) for t in f.get("tokens") or []]
    paint = (pol.get("buttons") or {}).get("paint") or {} if isinstance(pol.get("buttons"), dict) else {}
    named += [("buttons.paint", t) for t in (paint.values() if isinstance(paint, dict) else [])]
    pairs = (pol.get("scheme") or {}).get("pairs") or {}
    named += [("scheme.pairs", t) for t in list(pairs.keys()) + list(pairs.values())]
    for where, t in named:
        if t in rcol:
            ctx.fail("POL", "policy." + where, "admits the reserved token %s (reserved tokens are floor)" % t)
        else:
            c = colour(t)
            hit = next((r for r, rc in rcol.items() if rc is not None and c is not None and (c.r, c.g, c.b, c.a) == (rc.r, rc.g, rc.b, rc.a)), None)
            if hit:
                ctx.fail("POL", "policy." + where, "token %s has the reserved token %s's colour" % (t, hit))
    for e in pol.get("extras") or [] if isinstance(pol.get("extras"), list) else []:
        for r, rc in rcol.items():
            if rc is not None and tuple(e.get("rgb") or ()) == (rc.r, rc.g, rc.b):
                al = e.get("alpha")
                lo, hi = (al if isinstance(al, list) else [al, al])
                try:
                    if dl.Decimal(str(lo)) <= rc.a <= dl.Decimal(str(hi)):
                        ctx.fail("POL", "policy.extras.%s" % e.get("id"), "admits the reserved token %s's colour" % r)
                except (dl.InvalidOperation, TypeError):
                    pass


def derived_paints(value):
    """Every paint of a resolved derived value: each top-level part that can only be a colour (named colours and colour
    functions included) and every gradient stop; lengths, keywords of shape and style, transparent and currentColor
    are not paints of their own."""
    out = []
    for layer in dl.split_top(value, ","):
        for part in dl.split_top(layer.strip(), " "):
            p = part.strip()
            if not p:
                continue
            if pl.GRADIENT.match(p):
                out += [s for s in pl.gradient_stops(p) if s.lower() not in pl.KEYWORDS]
            elif pl.is_colourish(p) and p.lower() not in pl.KEYWORDS:
                out.append(p)
    return out


def root_contexts(css, name, schemes):
    """[(media, schemes)]: every context where :root declares the variable (its top level and each override), with the
    schemes of the mode it applies to (R2-M07): a prefers-color-scheme media query names its one scheme; the top level
    applies to every scheme no such query overrides; any other media query to every scheme."""
    def scheme_of(m):
        low = re.sub(r"\s+", "", m.lower())
        return "dark" if "prefers-color-scheme:dark" in low else "light" if "prefers-color-scheme:light" in low else None
    medias = sorted({r.media for r in css.sheet.rules if ":root" in r.selectors and any(k == name for k, _ in r.decls)})
    overridden = {scheme_of(m) for m in medias} - {None}
    out = []
    for m in medias:
        sc = scheme_of(m)
        applies = [sc] if sc else [s for s in schemes if not (m == "" and s in overridden)]
        out.append((m, [s for s in applies if s in schemes]))
    return out


def check_derived(ctx, css):
    """Each derived variable is declared in :root and, in every context that declares it (overrides included, its
    references resolved), resolves only to values allowed in each of its roles in each scheme that context applies to,
    never against the union of roles and schemes (R2-M07)."""
    pol, d = ctx.data["policy"], ctx.data["design"]
    if pl.section_off(pol, "derived_vars"):
        return
    groups = {g: d[g] for g in dl.GROUPS}
    props = css.props()
    roles_by_scheme = pol.get("roles") if isinstance(pol.get("roles"), dict) else {}
    mode = (pol.get("scheme") or {}).get("mode") or "light-only"
    schemes = {"light-only": ["light"], "dark-only": ["dark"], "both": ["light", "dark"]}.get(mode, ["light"])

    def token_colour(t):
        try:
            return dl.parse_colour(dl.resolve(groups["colors"].get(t), groups))
        except (dl.ContentError, TypeError):
            return None

    def allowed(c, role, scheme):
        """A token of this role in this scheme, or an extra admitted in this role."""
        if any(token_colour(t) == c for t in ((roles_by_scheme.get(scheme) or {}).get(role) or [])):
            return True
        for e in pol.get("extras") or []:
            if isinstance(e, dict) and role in pl.as_list(e.get("roles") or []):
                al = e.get("alpha")
                lo, hi = (al if isinstance(al, list) else [al, al])
                if (c.r, c.g, c.b) == tuple(e.get("rgb") or ()) and dl.Decimal(str(lo)) <= c.a <= dl.Decimal(str(hi)):
                    return True
        return False

    for dv in pol.get("derived_vars") or []:
        name, roles = dv.get("name"), pl.as_list(dv.get("roles") or [])
        path = "policy.derived_vars.%s" % name
        if name not in props:
            ctx.fail("POL", path, ":root declares no %s" % name)
            continue
        bad, values = [], []
        for media, applies in root_contexts(css, name, schemes):
            mp = css.props(media)
            value, missing = csslite.resolve_vars(mp[name], mp)
            if missing:
                bad.append("%s uses undefined %s%s" % (name, ", ".join(missing), " in @media " + media if media else ""))
                continue
            values.append(value)
            for raw in derived_paints(value):
                c = dl.parse_colour(raw)
                if c is None:      # the whole value is read: a paint this check cannot read fails (AST-M10)
                    bad.append(raw + " (not a colour this check can read)")
                    continue
                for scheme in applies:
                    for role in roles:
                        if not allowed(c, role, scheme):      # each role in each scheme (R2-M07)
                            bad.append("%s [not in %s (%s%s)]" % (raw, role, scheme, ", @media " + media if media else ""))
        if bad:
            ctx.fail("POL", path, "%s resolves to values not allowed in %s: %s" % (name, roles, ", ".join(bad)))
        else:
            ctx.ok("POL", path, "%s = %s (allowed in %s in %s)" % (name, " | ".join(values), roles, ", ".join(schemes)))


def check_stack_vars(ctx, css):
    """Each font-stack variable of the policy is declared in :root and, in every context that declares it, its first
    family is an approved face family of the policy and every other family an approved face family, a generic family or
    a fallback family listed in fonts.fallback_families: only then is it certified, so font-family: var(--x) can be
    accepted (R2-M07; the key by the CEO's decision of 2026-11-11; the approved face first, as in a literal stack, by the
    CEO's decision of 2026-11-12). A1 still judges the font that actually draws the text."""
    pol = ctx.data["policy"]
    fonts = pol.get("fonts") if isinstance(pol.get("fonts"), dict) and not pl.section_off(pol, "fonts") else {}
    approved = {f.get("family", "").lower() for f in fonts.get("faces") or [] if isinstance(f, dict) and isinstance(f.get("family"), str)}
    fallbacks = pl.fallback_families(fonts)
    for name in fonts.get("stack_vars") or []:
        path = "policy.fonts.stack_vars.%s" % name
        contexts = root_contexts(css, name, ["light", "dark"])
        if not contexts:
            ctx.fail("POL", path, ":root declares no %s: a font-stack variable must hold an approved stack" % name)
            continue
        for media, _ in contexts:
            mp = css.props(media)
            value, missing = csslite.resolve_vars(mp[name], mp)
            fams = pl.families(value)
            bad = [f for f in fams if f not in approved and f not in pl.GENERIC_FAMILIES and f not in fallbacks]
            first_ok = bool(fams) and fams[0] in approved
            where = " in @media " + media if media else ""
            if missing or not fams or bad or not first_ok:
                held = (("undefined " + ", ".join(missing)) if missing else ", ".join(bad) if bad else
                        "%s first (the first family must be an approved face)" % fams[0] if fams else "no family")
                ctx.fail("POL", path, "%s = %s%s holds %s: not an approved stack (approved faces %s, generic families or "
                         "fonts.fallback_families %s)" % (name, value, where, held, sorted(approved), sorted(fallbacks)))
            else:
                ctx.ok("POL", path, "%s = %s%s (an approved face first, then approved faces, generic families and fallback "
                       "families)" % (name, value, where))


# ------------------------------------------------------------------ P3: token contrast

def root_font_size(css):
    """(px, None): the root font size the site sets on html or :root, resolved as P1 resolves declarations, the smallest
    across its media contexts; 16 px, the browser default, when the site sets none (R2-M05). (None, why) when it is
    uncertain: declared several times with different values, a viewport unit, clamp(), a keyword, the font shorthand."""
    if css is None:
        return Decimal(16), None
    sizes = []
    for media in sorted({r.media for r in css.sheet.rules if set(r.selectors) & {"html", ":root"}}):
        for sel in ("html", ":root"):
            decls, _amb = css.decls(sel, media)
            if decls is None:
                continue
            if "font" in decls:
                return None, "%s sets the font shorthand" % sel
            if "font-size" not in decls:
                continue
            v, err = css.value(sel, "font-size", media)
            if err:
                return None, str(err)
            t = dl.typed(v)
            if t[0] == "dim" and t[2] == "px":
                sizes.append(t[1])
            elif t[0] == "dim" and t[2] == "%":
                sizes.append(t[1] * 16 / 100)          # of the browser default, as the root's own percentage is
            elif t[0] == "dim" and t[2] in ("em", "rem"):
                sizes.append(t[1] * 16)
            else:
                return None, "%s font-size %s" % (sel, v)
    return (min(sizes) if sizes else Decimal(16)), None


def p3_contrast(ctx, css=None):
    d, c = ctx.data["design"], ctx.data["contrast"]
    groups = {g: d[g] for g in dl.GROUPS}
    comps = d["components"]
    mode = ((ctx.data["policy"].get("scheme") or {}).get("mode")) or "light-only"
    schemes = {"light-only": ["light"], "dark-only": ["dark"], "both": ["light", "dark"]}.get(mode, ["light"])
    baseline = [e for e in (c.get("baseline") or []) if isinstance(e, dict)]
    pairs = ((ctx.data["policy"].get("scheme") or {}).get("pairs")) or {}
    colors = d["colors"]
    typo_map = ctx.data["tmap"].get("typography") if isinstance(ctx.data["tmap"].get("typography"), dict) else {}
    comp_map = ctx.data["tmap"].get("components") if isinstance(ctx.data["tmap"].get("components"), dict) else {}
    overrides = [o for o in (ctx.data["tmap"].get("overrides") or []) if isinstance(o, dict) and o.get("prop") == "font-size"]
    root_px, root_why = root_font_size(css)
    used = set()

    def in_scheme(ref, scheme):
        """With scheme both, a light token used in the dark render is its pair; an alias is followed to the token that
        has a pair before the lookup (AUD-F07(2))."""
        if scheme == "dark" and mode == "both" and dl.is_ref(ref):
            g, n = dl.REF.match(ref.strip()).groups()
            seen = set()
            while g == "colors" and n not in pairs and n not in seen and dl.is_ref(colors.get(n)):
                seen.add(n)
                g, n = dl.REF.match(colors[n].strip()).groups()
            if g == "colors" and n in pairs:
                return "{colors.%s}" % pairs[n]
        return ref

    def colour_of(src):
        try:
            return dl.parse_colour(dl.resolve(src, groups))
        except dl.ContentError:
            return None

    def smallest_size(name, comp):
        """(size in px or None, weight, root uncertain): the smallest size the component's text reaches (AST-M09,
        AUD-F07(3), R2-M05): of the token's size (a fluid size's clamp() minimum) and the trace map's font-size
        overrides for its selectors; rem with the site's root font size; em and other relative units are not
        resolved here (None); a rem size under an uncertain root size gives (None, weight, True)."""
        if not dl.is_ref(comp.get("typography")):
            return Decimal(16), 400, False
        t = dl.resolve(comp["typography"], groups)
        if not isinstance(t, dict):
            return Decimal(16), 400, False
        weight = t.get("fontWeight", 400)
        b = typo_map.get(dl.REF.match(comp["typography"].strip()).groups()[1])
        clamp = dl.clamp_parts(b["clamp_expr"]) if isinstance(b, dict) and b.get("clamp_expr") else None
        sizes = [clamp[0] if clamp else dl.typed(t.get("fontSize", "16px"))]
        own = (comp_map.get(name) or {}).get("typography") if isinstance(comp_map.get(name), dict) else None
        sels = set(as_list((b or {}).get("sel") or []) if isinstance(b, dict) else []) | set(as_list((own or {}).get("sel") or []) if isinstance(own, dict) else [])
        sizes += [dl.typed(str(o.get("value"))) for o in overrides if o.get("sel") in sels]
        px, uncertain = [], False
        for v in sizes:
            if v[0] == "clamp":
                v = v[1][0]
            if v[0] == "dim" and v[2] == "px":
                px.append(v[1])
            elif v[0] == "dim" and v[2] == "rem":
                if root_px is None:
                    uncertain = True
                else:
                    px.append(v[1] * root_px)          # the site's root size, 16 px only when it sets none (R2-M05)
            else:
                return None, weight, False
        if uncertain:
            return None, weight, True
        return min(px), weight, False

    def same_colours(recorded, actual):
        rec = recorded if isinstance(recorded, list) else [recorded]
        return len(rec) == len(actual) and all(isinstance(x, str) and dl.parse_colour(x) == a for x, a in zip(rec, actual))

    for scheme in schemes:
        surfaces = (c.get("surfaces") or {}).get(scheme) or {}
        for name, comp in comps.items():
            if "textColor" not in comp:
                continue
            path = "components.%s (%s)" % (name, scheme)
            base = (c.get("base") or {}).get(name)
            bg_src = comp.get("backgroundColor") or (comps.get(base) or {}).get("backgroundColor")
            if bg_src is None:
                ctx.fail("P3", path, "no backgroundColor and no base component in contrast.yaml")
                continue
            items = surfaces.get(name)
            if not items:
                ctx.fail("P3", path, "contrast.yaml lists no surface for this text component")
                continue
            bg_src = in_scheme(bg_src, scheme)
            own = colour_of(bg_src)
            tops = [as_list(i)[-1] for i in items]
            top_colours = [own if t == "self" else colour_of("{colors.%s}" % t) for t in tops]
            if own is not None and own not in top_colours:   # by resolved colour, literals included (AST-M09)
                ctx.fail("P3", path, "its background %s (%r) is not among its listed surfaces %s" % (bg_src, own, tops))
            checked = [as_list(i) for i in items]
            if own is not None and own.a == 1 and not any(len(i) == 1 and (i[0] == "self" or colour_of("{colors.%s}" % i[0]) == own) for i in checked):
                checked.append(["self"])     # the component's own bound background is always checked (AST-M09)
            text = colour_of(in_scheme(comp["textColor"], scheme))
            if text is None:
                ctx.fail("P3", path, "its text colour %s does not resolve to a colour" % comp["textColor"])
                continue
            size, weight, uncertain = smallest_size(name, comp)
            threshold = None
            if size is not None:
                threshold = 3.0 if dl.is_large(size, weight) else 4.5
            elif uncertain:              # the root size is uncertain: the stricter threshold applies (R2-M05)
                threshold = 4.5
            for item in checked:
                layers_names = [x for x in as_list(item)]
                layers = []
                for x in layers_names:
                    src = bg_src if x == "self" else "{colors.%s}" % x
                    try:
                        col = dl.parse_colour(dl.resolve(src, groups))
                    except dl.ContentError as exc:
                        ctx.fail("P3", path, str(exc))
                        col = None
                    if col is None:
                        layers = None
                        break
                    layers.append(col)
                if not layers:
                    continue
                if layers[0].a != 1:
                    ctx.fail("P3", path, "surface %s is translucent with nothing opaque beneath" % "+".join(layers_names))
                    continue
                backdrop = dl.flatten(layers)
                fg = dl.composite(text, backdrop)
                r, r8 = dl.ratio(fg, backdrop), dl.ratio_8bit(fg, backdrop)
                key = (name, scheme, "+".join(layers_names))
                # a baseline holds only while its resolved text and surface colours are unchanged (AUD-F08, AST-M09)
                entry = next((e for e in baseline if (e.get("component"), e.get("scheme", "light"), "+".join(as_list(e.get("surface")))) == key
                              and e.get("text") == comp["textColor"] and e.get("method", "fractional") == "fractional"
                              and same_colours(e.get("text_colour"), [text]) and same_colours(e.get("surface_colour"), layers)), None)
                need = threshold if threshold is not None else 4.5
                label = "%s on %s: %.4f (8-bit %.4f), threshold %.1f%s" % (comp["textColor"], "+".join(layers_names), r, r8, need,
                                                                          (" (the root font size is uncertain: %s; the stricter threshold applies)" % root_why)
                                                                          if uncertain else "" if threshold is not None else " (its size is not resolved to px)")
                if r >= need:
                    ctx.ok("P3", path, label)
                    if entry:
                        used.add(id(entry))
                        ctx.rep.add("INFO", "P3", path, "baseline entry now passes and can leave the baseline")
                elif threshold is None and r >= 3.0 and not entry:
                    ctx.rep.add("INCOMPLETE", "P3", path, label + "; below 4.5:1, and whether it is large text is not decided (an em or other relative size)")
                elif entry and r >= float(entry.get("ratio", 99)) - 1e-9:
                    used.add(id(entry))
                    ctx.rep.add("PASS", "P3", path, label + "; baseline kept by %s" % entry.get("decision", "?"), baseline=True)
                elif entry:
                    ctx.fail("P3", path, label + "; worse than its baseline %.4f" % float(entry["ratio"]))
                else:
                    ctx.fail("P3", path, label)
    for e in baseline:
        if id(e) not in used:
            ctx.fail("P3", "baseline", "entry %s matches no pair (component, scheme, text, surface, method, text_colour and "
                                       "surface_colour must match exactly)" % (e,))


# ------------------------------------------------------------------ policy

def check_policy(ctx):
    pol, d = ctx.data["policy"], ctx.data["design"]
    colours = d["colors"]
    for s in POLICY_SECTIONS:
        if s not in pol:
            ctx.fail("POL", "policy." + s, "section missing (use off: <reason> for a non-floor section)")
            continue
        v = pol[s]
        if isinstance(v, dict) and set(v) == {"off"}:
            if s in FLOOR_SECTIONS:
                ctx.fail("POL", "policy." + s, "a floor section can never be off")
            elif not str(v["off"]).strip():
                ctx.fail("POL", "policy." + s, "off needs a reason")
            else:
                ctx.rep.add("NOT_CONFIGURED", "POL", "policy." + s, "off: %s" % v["off"])
    if not isinstance(pol.get("reserved"), list):
        ctx.fail("POL", "policy.reserved", "must be a list ([] when nothing is reserved)")
    for tok in pol.get("reserved") or []:
        if tok not in colours:
            ctx.fail("POL", "policy.reserved", "unknown token %s" % tok)
    check_reserved_floor(ctx, pol, d)
    roles = pol.get("roles")
    if isinstance(roles, dict) and set(roles) != {"off"}:
        for scheme, props in roles.items():
            for prop, toks in (props or {}).items():
                for tok in toks or []:
                    if tok not in colours:
                        ctx.fail("POL", "policy.roles.%s.%s" % (scheme, prop), "unknown token %s" % tok)
    for tok in pol.get("forbidden_text_colours") or []:
        if isinstance(pol.get("forbidden_text_colours"), list) and tok not in colours:
            ctx.fail("POL", "policy.forbidden_text_colours", "unknown token %s" % tok)
    ids, design_text = set(), ctx.snap.text(ctx.path("DESIGN.md"))
    for e in pol.get("extras") or [] if isinstance(pol.get("extras"), list) else []:
        if not extra_typed(ctx, e):
            continue
        eid = e.get("id")
        if eid in ids:
            ctx.fail("POL", "policy.extras", "duplicate id %s" % eid)
        ids.add(eid)
        quote = str(e.get("quote", ""))
        alpha = e.get("alpha")
        if quote not in design_text:
            ctx.fail("POL", "policy.extras.%s" % eid, "quote not found verbatim in DESIGN.md")
        rgb = e.get("rgb") or []
        rng = alpha if isinstance(alpha, list) else [alpha, alpha]
        if len(rng) != 2 or rng[0] is None or float(rng[0]) > float(rng[1]):
            ctx.fail("POL", "policy.extras.%s" % eid, "alpha must be a number or a closed range [low, high]")
        elif not all(re.search(r"(?<![\d.])%s(?![\d])" % re.escape(str(a)), quote)
                     or ("%s%%" % dl.canon_decimal(dl.Decimal(str(a)) * 100)) in quote for a in set(map(str, rng))):
            ctx.fail("POL", "policy.extras.%s" % eid, "the quote does not contain the entry's alpha %s" % alpha)
        elif rgb and ", ".join(map(str, rgb)) not in quote and not any(
                dl.parse_colour(colours[t]) and (dl.parse_colour(colours[t]).r, dl.parse_colour(colours[t]).g, dl.parse_colour(colours[t]).b) == tuple(rgb) and ("{colors.%s}" % t) in quote
                for t in colours if not dl.is_ref(colours[t])):
            ctx.fail("POL", "policy.extras.%s" % eid, "the quote does not name the base colour %s" % rgb)
        if not e.get("roles"):
            ctx.fail("POL", "policy.extras.%s" % eid, "no roles")
        for role in e.get("roles") or []:
            if role not in pl.EXTRA_ROLES:
                ctx.fail("POL", "policy.extras.%s" % eid, "unknown role %s (one of %s)" % (role, ", ".join(pl.EXTRA_ROLES)))
    extras = [e for e in (pol.get("extras") or []) if isinstance(e, dict) and extra_typed(None, e)] if isinstance(pol.get("extras"), list) else []
    for i, a in enumerate(extras):
        for b in extras[i + 1:]:
            if a.get("rgb") and a.get("rgb") == b.get("rgb"):
                ra = a["alpha"] if isinstance(a.get("alpha"), list) else [a.get("alpha"), a.get("alpha")]
                rb = b["alpha"] if isinstance(b.get("alpha"), list) else [b.get("alpha"), b.get("alpha")]
                try:
                    overlap = float(ra[0]) <= float(rb[1]) and float(rb[0]) <= float(ra[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if overlap:
                    ctx.fail("POL", "policy.extras.%s" % b.get("id"), "alpha range overlaps extra %s of the same colour (one entry per colour and range)" % a.get("id"))
    tiers = pol.get("tiers") or {}
    if isinstance(tiers, dict) and set(tiers) != {"off"}:
        for a, t in tiers.items():
            if a in FLOOR_ASSERTIONS:
                ctx.fail("POL", "policy.tiers.%s" % a, "a floor assertion has no tier (it is fixed in code)")
            elif a not in NON_FLOOR:
                ctx.fail("POL", "policy.tiers.%s" % a, "unknown assertion")
            elif t not in TIERS:
                ctx.fail("POL", "policy.tiers.%s" % a, "tier must be one of %s" % ", ".join(TIERS))
    acc = pol.get("accessibility") or {}
    for rule in (acc.get("tiers") or {}) if isinstance(acc, dict) else {}:
        if rule == "color-contrast":
            ctx.fail("POL", "policy.accessibility.tiers", "color-contrast is a floor rule; it has no tier")
    mode = (pol.get("scheme") or {}).get("mode")
    if mode not in ("light-only", "dark-only", "both"):
        ctx.fail("POL", "policy.scheme.mode", "must be light-only, dark-only or both")
    elif mode == "both" and not (pol["scheme"].get("pairs")):
        ctx.fail("POL", "policy.scheme.pairs", "scheme both needs light-to-dark token pairs")
    fonts = pol.get("fonts") or {}
    for face in fonts.get("faces") or [] if isinstance(fonts, dict) else []:
        for k in ("family", "file", "sha256", "postscript", "weight", "style"):
            if k not in face:
                ctx.fail("POL", "policy.fonts", "face lacks %s" % k)
    check_policy_schema(ctx, pol, d)
    waivers = ctx.data["waivers"].get("waivers") or []
    if not isinstance(waivers, list):
        ctx.fail("POL", "waivers", "waivers is not a list")
        waivers = []
    wids = set()
    for w in waivers:
        if not isinstance(w, dict):
            ctx.fail("POL", "waivers", "a waiver is not a mapping")
            continue
        wid = w.get("id", "?")
        for k in ("assertion", "page", "selector", "page_sha256", "reason", "owner_words", "date"):
            if not w.get(k):
                ctx.fail("POL", "waivers.%s" % wid, "lacks %s" % k)
        if str(w.get("page", "")).strip() == "*" or str(w.get("selector", "")).strip() == "*":
            ctx.fail("POL", "waivers.%s" % wid, "a bare * scope is forbidden")
        if w.get("assertion") in FLOOR_ASSERTIONS:
            ctx.fail("POL", "waivers.%s" % wid, "a floor assertion cannot be waived")
        # waiver fields typed (AST-M06)
        if wid in wids:
            ctx.fail("POL", "waivers.%s" % wid, "duplicate id")
        wids.add(wid)
        for k in ("id", "assertion", "page", "selector", "page_sha256", "reason", "owner_words", "date"):
            if k in w and not isinstance(w[k], str):
                ctx.fail("POL", "waivers.%s" % wid, "%s is not a string" % k)
        if w.get("assertion") and w.get("assertion") not in FLOOR_ASSERTIONS + NON_FLOOR:
            ctx.fail("POL", "waivers.%s" % wid, "unknown assertion %s" % w.get("assertion"))
        if isinstance(w.get("page_sha256"), str) and w["page_sha256"] and not dl.SHA256_HEX.match(w["page_sha256"]):
            ctx.fail("POL", "waivers.%s" % wid, "page_sha256 is not a SHA-256 hex digest (64 lowercase hex digits)")
        if isinstance(w.get("date"), str) and w["date"] and not DATE.match(w["date"]):
            ctx.fail("POL", "waivers.%s" % wid, "date is not YYYY-MM-DD")
    if not ctx.rep.count("FAIL"):
        ctx.ok("POL", "policy", "all sections present; floor intact")


def extra_typed(ctx, e):
    """True when an extra has its fields' types (id, rgb of three 0-255 integers, alpha a number or a closed range in
    0..1, roles, quote); otherwise FAIL (with ctx) and False, so no later check reads a malformed entry."""
    def num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 1
    al = e.get("alpha") if isinstance(e, dict) else None
    ok = (isinstance(e, dict) and isinstance(e.get("id"), str) and e["id"]
          and isinstance(e.get("rgb"), list) and len(e["rgb"]) == 3 and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in e["rgb"])
          and (num(al) or (isinstance(al, list) and len(al) == 2 and num(al[0]) and num(al[1])))
          and isinstance(e.get("roles"), list) and isinstance(e.get("quote"), str))
    if not ok and ctx is not None:
        ctx.fail("POL", "policy.extras.%s" % (e.get("id") if isinstance(e, dict) else "?"),
                 "an extra needs id, rgb [r, g, b] (0-255), alpha (a number or [low, high] in 0..1), roles and quote")
    return ok


def check_policy_schema(ctx, pol, d):
    """Required keys and types of every policy section (AST-M06, AUD-F04): non-empty floor sections, roles for every
    scheme of the mode within that scheme's set, complete scheme pairs, typed faces whose files exist with their SHA-256,
    axe tags axe-core 4.14.0 knows (AST-M15), accessibility tiers blocking or advisory (AUD-F09)."""
    colours = d["colors"]

    def bad(where, why):
        ctx.fail("POL", "policy." + where, why)

    def off(s):
        return pl.section_off(pol, s)

    def strs(x):
        return isinstance(x, list) and all(isinstance(i, str) and i for i in x)

    def num(x, lo=None, hi=None):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and (lo is None or x >= lo) and (hi is None or x <= hi)

    def integer(x, lo=None, hi=None):
        return isinstance(x, int) and not isinstance(x, bool) and num(x, lo, hi)

    def tokens(where, x, nonempty=False):
        if not strs(x if x is not None else []):
            return bad(where, "must be a list of token names")
        if nonempty and not x:
            return bad(where, "must name at least one token")
        for t in x or []:
            if t not in colours:
                bad(where, "unknown token %s" % t)

    scheme = pol.get("scheme") if isinstance(pol.get("scheme"), dict) else {}
    mode = scheme.get("mode")
    schemes = {"light-only": ["light"], "dark-only": ["dark"], "both": ["light", "dark"]}.get(mode, [])
    sets = scheme.get("sets") if isinstance(scheme.get("sets"), dict) else None
    if not isinstance(pol.get("scheme"), dict):
        bad("scheme", "must be a mapping with mode, sets and (for both) pairs")
    elif off("scheme"):
        bad("scheme", "scheme cannot be off: the checks need its mode")
    else:
        if sets is None:
            bad("scheme.sets", "must name the tokens of each scheme of the mode")
        else:
            for s in schemes:
                tokens("scheme.sets.%s" % s, sets.get(s), nonempty=True)
        if mode == "both" and isinstance(scheme.get("pairs"), dict) and sets is not None:
            light, dark = sets.get("light") or [], sets.get("dark") or []
            for lt, dk in scheme["pairs"].items():
                if lt not in light or dk not in dark:
                    bad("scheme.pairs", "pair %s: %s must map a light-set token to a dark-set token" % (lt, dk))
            for t in light:
                if t not in dark and t not in scheme["pairs"]:
                    bad("scheme.pairs", "light-set token %s has no dark pair (pairs must be complete)" % t)
    roles = pol.get("roles")
    if not off("roles"):
        if not isinstance(roles, dict):
            bad("roles", "must be a mapping per scheme")
        else:
            for s in roles:
                if s not in ("light", "dark"):
                    bad("roles.%s" % s, "unknown scheme (light or dark)")
            for s in schemes:
                rp = roles.get(s)
                if not isinstance(rp, dict) or not any(isinstance(v, list) and v for v in rp.values()):
                    bad("roles.%s" % s, "the %s scheme of mode %s needs its roles (a floor section is never empty)" % (s, mode))
                    continue
                for prop, toks in rp.items():
                    if prop not in ROLE_KEYS:
                        bad("roles.%s.%s" % (s, prop), "unknown role (one of %s)" % ", ".join(ROLE_KEYS))
                    if not strs(toks if toks is not None else []):
                        bad("roles.%s.%s" % (s, prop), "must be a list of token names")
                    elif sets is not None and isinstance(sets.get(s), list):
                        for t in toks or []:
                            if t in colours and t not in sets[s]:
                                bad("roles.%s.%s" % (s, prop), "token %s is not in the %s set (scheme.sets.%s)" % (t, s, s))
    fonts = pol.get("fonts")
    if not off("fonts"):
        if not isinstance(fonts, dict):
            bad("fonts", "must be a mapping with faces")
        else:
            faces = fonts.get("faces")
            if not isinstance(faces, list) or not faces:
                bad("fonts.faces", "must list at least one approved face (a floor section is never empty)")
                faces = []
            for i, face in enumerate(faces):
                w = "fonts.faces[%d]" % i
                if not isinstance(face, dict):
                    bad(w, "a face is not a mapping")
                    continue
                for k in ("family", "file", "postscript"):
                    if k in face and not (isinstance(face[k], str) and face[k]):
                        bad(w, "%s is not a non-empty string" % k)
                if "sha256" in face and not (isinstance(face["sha256"], str) and dl.SHA256_HEX.match(face["sha256"])):
                    bad(w, "sha256 is not a SHA-256 hex digest (64 lowercase hex digits)")
                wt = face.get("weight")
                if "weight" in face and not (isinstance(wt, list) and len(wt) == 2 and integer(wt[0], 1, 1000) and integer(wt[1], 1, 1000) and wt[0] <= wt[1]):
                    bad(w, "weight must be [min, max] between 1 and 1000")
                if "style" in face and face["style"] not in FACE_STYLES:
                    bad(w, "style must be one of %s" % ", ".join(FACE_STYLES))
                cov = face.get("coverage")
                if not (isinstance(cov, list) and cov and all(isinstance(p, list) and len(p) == 2 and integer(p[0], 0, 0x10FFFF)
                                                             and integer(p[1], 0, 0x10FFFF) and p[0] <= p[1] for p in cov)):
                    bad(w, "coverage must be a non-empty list of [first, last] code point pairs (read them with font_facts.py)")
                if isinstance(face.get("file"), str) and face["file"]:
                    p = site_path(ctx, face["file"])
                    if not os.path.isfile(p):
                        bad(w, "the face file %s does not exist" % face["file"])
                    else:
                        digest = ctx.font_digests.get(face["file"]) or dl.sha256_file(p)
                        ctx.font_digests[face["file"]] = digest
                        if isinstance(face.get("sha256"), str) and digest != face["sha256"]:
                            bad(w, "the face file %s does not have the SHA-256 the policy names" % face["file"])
            if not (fonts.get("stack_vars") is None or (strs(fonts["stack_vars"]) and all(v.startswith("--") for v in fonts["stack_vars"]))):
                bad("fonts.stack_vars", "must be a list of custom property names")
            if fonts.get("code_roles", "off") not in ("system-monospace", "off"):
                bad("fonts.code_roles", "must be system-monospace or off")
    if isinstance(pol.get("extras"), dict) and not off("extras"):
        bad("extras", "must be a list or off")
    dv = pol.get("derived_vars")
    if not off("derived_vars"):
        if not isinstance(dv, list):
            bad("derived_vars", "must be a list or off")
        else:
            for x in dv:
                if not (isinstance(x, dict) and isinstance(x.get("name"), str) and x["name"].startswith("--")
                        and strs(x.get("roles")) and x["roles"] and all(r in ROLE_KEYS + pl.EXTRA_ROLES for r in x["roles"])):
                    bad("derived_vars", "an entry needs name (--name) and roles from %s" % ", ".join(ROLE_KEYS + pl.EXTRA_ROLES))
    h = pol.get("headings")
    if not off("headings"):
        if not isinstance(h, dict):
            bad("headings", "must be a mapping or off")
        else:
            tokens("headings.tokens", h.get("tokens"), nonempty=True)
            a = h.get("accent")
            if a is not None and not (isinstance(a, dict) and num(a.get("max_share"), 0, 1) and integer(a.get("max_runs"), 0)):
                bad("headings.accent", "must be none or {tokens, max_share (0..1), max_runs (an integer)}")
            elif isinstance(a, dict):
                tokens("headings.accent.tokens", a.get("tokens"), nonempty=True)
            if not strs(h.get("selectors") if h.get("selectors") is not None else []):
                bad("headings.selectors", "must be a list of selectors")
    lab = pol.get("labels")
    if not off("labels"):
        st = lab.get("style") if isinstance(lab, dict) else None
        if not isinstance(lab, dict) or not strs(lab.get("selectors") if lab.get("selectors") is not None else []):
            bad("labels", "must be {selectors, style} or off")
        elif st is not None and not (isinstance(st, dict) and num(st.get("max_size_px"), 0) and integer(st.get("min_weight"), 1, 1000)):
            bad("labels.style", "must be {max_size_px, min_weight}")
    if not off("forbidden_text_colours"):
        tokens("forbidden_text_colours", pol.get("forbidden_text_colours"))
    fills = pol.get("fills")
    if not off("fills"):
        if not isinstance(fills, list):
            bad("fills", "must be a list or off")
        else:
            for f in fills:
                if not (isinstance(f, dict) and num(f.get("alpha_above"), 0, 1) and num(f.get("max_area_px2"), 0)):
                    bad("fills", "an entry needs tokens, alpha_above (0..1) and max_area_px2")
                else:
                    tokens("fills.tokens", f.get("tokens"), nonempty=True)
    m = pol.get("measure")
    if not off("measure"):
        if not (isinstance(m, dict) and num(m.get("default_px"), 1) and isinstance(m.get("roles", []), list)
                and all(isinstance(x, dict) and isinstance(x.get("selector"), str) and num(x.get("px"), 1) for x in m.get("roles") or [])):
            bad("measure", "must be {default_px, roles: [{selector, px}]} or off")
    if not off("capitals") and pol.get("capitals") not in ("labels-only", "off"):
        bad("capitals", "must be labels-only, or off with a reason")
    btn = pol.get("buttons")
    if not off("buttons"):
        paint = btn.get("paint") if isinstance(btn, dict) else None
        if not (isinstance(btn, dict) and strs(btn.get("selectors") if btn.get("selectors") is not None else []) and integer(btn.get("max_per_view", 1), 0)
                and (paint == BUTTONS_SELECTORS_ONLY or (isinstance(paint, dict) and set(paint) == {"background", "text"} and strs(list(paint.values()))))):
            bad("buttons", "must be {selectors, paint: {background, text} or %s, max_per_view} or off (R2-M06: the paint "
                           "signature is named, or selectors-only is said)" % BUTTONS_SELECTORS_ONLY)
        elif isinstance(paint, dict):
            for k, t in sorted(paint.items()):     # the signature names tokens of the palette (R2-M06)
                if t not in colours:
                    bad("buttons.paint.%s" % k, "unknown token %s (A11 could not identify a button by its paint)" % t)
        elif not btn.get("selectors"):
            bad("buttons.selectors", "paint: %s needs at least one selector" % BUTTONS_SELECTORS_ONLY)
    acc = pol.get("accessibility")
    if not off("accessibility"):
        if not isinstance(acc, dict):
            bad("accessibility", "must be a mapping or off")
        else:
            tags = acc.get("tags")
            if tags is not None and not (strs(tags) and tags):
                bad("accessibility.tags", "must be a non-empty list of axe tags")
            for t in (tags or []) if strs(tags or []) else []:
                if t not in pl.AXE_TAGS:
                    bad("accessibility.tags", "axe-core 4.14.0 knows no tag %s" % t)
            if "default" in acc and acc["default"] not in A11Y_TIERS:
                bad("accessibility.default", "must be blocking or advisory")
            at = acc.get("tiers") or {}
            if not isinstance(at, dict):
                bad("accessibility.tiers", "must be a mapping of axe rule ids to tiers")
            else:
                for rule, t in at.items():
                    if t not in A11Y_TIERS:
                        bad("accessibility.tiers.%s" % rule, "tier must be blocking or advisory")
    if not off("decisions") and not strs(pol.get("decisions")):
        bad("decisions", "must be a list of the owner's decisions (quoted strings) or off")


# ------------------------------------------------------------------ boundary, approval, receipt

def check_boundary(ctx):
    root = ctx.args.deploy_root or ctx.data["site"].get("deploy_root")
    if not root:
        ctx.rep.add("INCOMPLETE", "PUB", "deploy_root", "site.yaml names no deploy root: publication boundary unknown")
        return
    root = os.path.realpath(site_path(ctx, root))
    if os.path.commonpath([root, ctx.site]) == root:
        ctx.fail("PUB", "deploy_root", "the site design folder lies inside the deploy root %s" % root)
    else:
        ctx.ok("PUB", "deploy_root", "the site design folder is outside the deploy root")


def git(args, cwd):
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise dl.InputError("Git cannot be run for --issue: %s" % exc)
    return r.returncode, r.stdout.strip()


def approval(ctx):
    """Every file of the folder equals its committed bytes at HEAD, HEAD resolved once to one commit: the snapshot's bytes
    (the bytes the checks used, AST-H09) against `cat-file blob` of `rev-parse HEAD:./<name>`, equal after CRLF to LF
    only; a path whose attributes set a filter, ident or working-tree-encoding is not approved (R2-M02). Read-only
    plumbing: no filter, hook or index write runs."""
    code, top = git(["rev-parse", "--show-toplevel"], ctx.site)
    if code:
        ctx.rep.add("INCOMPLETE", "APP", "approval", "the site design folder is not in a Git repository; approval cannot be checked")
        return None
    head = pl.resolve_head(ctx.site)
    if head is None:
        ctx.rep.add("INCOMPLETE", "APP", "approval", "the repository has no commit")
        return None
    blobs, names = {}, folder_files(ctx.site)
    for name in names:
        full = os.path.join(ctx.site, *name.split("/"))
        attr = pl.attributes_problem(ctx.site, name)
        if attr:
            ctx.rep.add("INCOMPLETE", "APP", name, attr)
            continue
        c1, blob, committed = pl.committed(ctx.site, head, name)
        try:
            checked = ctx.snap.read(full)
        except dl.ContentError:
            checked = None
        if c1 or checked is None or not pl.same_content(committed, checked):
            ctx.rep.add("INCOMPLETE", "APP", name, "differs from HEAD or is not committed (uncommitted changes are not approved)")
        else:
            blobs[name] = blob
    if len(blobs) == len(names):
        ctx.ok("APP", "approval", "all %d files of the site design folder equal HEAD %s" % (len(names), head[:12]))
        return {"commit": head, "blobs": blobs}
    return None


def inputs_changed(ctx):
    """The inputs whose bytes on disk differ now from the bytes the checks read (profile, CSS, fonts): a receipt is never
    issued over inputs that changed during the run (AST-H08)."""
    out = []
    for real, data in sorted(ctx.snap.files.items()):
        try:
            now = dl.read_bytes(real)
        except (dl.InputError, dl.ContentError):
            now = None
        if now != data:
            out.append(os.path.basename(real))
    for rel, digest in sorted(ctx.font_digests.items()):
        p = site_path(ctx, rel)
        try:
            if dl.sha256_file(p) != digest:
                out.append(rel)
        except dl.InputError:
            out.append(rel)
    return out


def rel_to_site(ctx, path):
    """A path as the receipt records it: relative to the site design folder, forward slashes (portable across machines)."""
    return os.path.relpath(os.path.realpath(path), ctx.site).replace(os.sep, "/")


def folder_files(site):
    """Every file of the site design folder except ready.json (plan 0.4 B.2), as sorted relative paths; .git skipped."""
    out = []
    for dirpath, dirs, files in os.walk(site):
        dirs[:] = sorted(x for x in dirs if x != ".git")
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), site).replace(os.sep, "/")
            if rel != "ready.json":
                out.append(rel)
    return sorted(out)


def write_receipt(ctx, appr, css_paths):
    plugin = os.path.dirname(os.path.realpath(__file__))
    scripts = {}
    for dirpath, _dirs, files in os.walk(plugin):
        if "__pycache__" in dirpath:
            continue
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            scripts[os.path.relpath(p, plugin).replace(os.sep, "/")] = dl.sha256_file(p)
    fonts = {}
    for face in (ctx.data["policy"].get("fonts") or {}).get("faces") or []:
        fonts[face["file"]] = ctx.font_digests.get(face["file"]) or dl.sha256_file(site_path(ctx, face["file"]))
    receipt = {
        "receipt_version": 1, "checker": "check_design.py " + VERSION,
        "issued": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "commit": appr["commit"],
        "profile": {n: {"blob": appr["blobs"][n], "sha256": ctx.snap.digest(os.path.join(ctx.site, *n.split("/")))} for n in sorted(appr["blobs"])},
        "css": {rel_to_site(ctx, p): ctx.snap.digest(p) for p in css_paths},
        "plugin_scripts": scripts, "fonts": fonts,
    }
    data = json.dumps(receipt, indent=1, sort_keys=True).encode("utf-8")
    changed = inputs_changed(ctx)
    if changed:
        ctx.rep.add("INCOMPLETE", "APP", "ready.json", "not issued: %s changed during the run" % ", ".join(changed))
        return
    target = ctx.path("ready.json")
    why = dl.output_name_problem(target)  # a link, junction, hard link or non-regular file (AST-M04, R2-M03)
    if why:
        ctx.rep.add("INCOMPLETE", "APP", "ready.json", "not issued: %s" % why)
        return
    # a new file in the folder, then renamed into place: never written through an existing ready.json (AST-M04, R2-M03)
    dl.write_output(target, data)
    ctx.rep.add("INFO", "APP", "ready.json", "receipt written for commit %s; its SHA-256 is %s (give it as --receipt-sha256 to a "
                "copy without a repository)" % (appr["commit"][:12], dl.sha256(data)))
    # the owner's commit of the receipt is the approval of the CSS, script and font digests it holds (R2-H06)
    ctx.rep.add("INFO", "APP", "next step", "commit ready.json now: approval counts only once it is committed")
    ctx.issued = dl.sha256(data)


def regeneration_check(ctx, args, site):
    """Design-first: the public tokens.css must equal a fresh render of DESIGN.md (runs even when P2 failed)."""
    import generate_css  # noqa: E402
    tokens_path = os.path.realpath(args.tokens or site_path(ctx, site.get("public_tokens", "tokens.css")))
    try:
        fresh = generate_css.render(ctx.data["design"], ctx.data["tmap"], ctx.data["policy"], ctx.snap.digest(ctx.path("DESIGN.md")))
    except (dl.ContentError, KeyError, AttributeError, TypeError) as exc:
        ctx.fail("P1", "tokens.css", "cannot regenerate from DESIGN.md: %s" % exc)
        return tokens_path
    if ctx.snap.text(tokens_path) != fresh:
        ctx.fail("P1", "tokens.css", "differs from a fresh regeneration (hand edit or stale file)")
    else:
        ctx.ok("P1", "tokens.css", "equals a fresh regeneration")
    return tokens_path


# ------------------------------------------------------------------ main

def run(args):
    ctx = Ctx(args)
    try:
        p2_ok = p2_parse(ctx)
        schema_ok = not ctx.rep.find("P2", "schema")
        site = ctx.data.get("site") or {}
        tokens_path = None
        if schema_ok and site.get("source") == "design":
            tokens_path = regeneration_check(ctx, args, site)
        if not p2_ok:
            return ctx
        shape = policy_shape_problems(ctx.data["policy"])   # the whole shape before any entry is read (R2-M06)
        for where, why in shape:
            ctx.fail("POL", "policy." + where if where != "policy" else where, why)
        listed = as_list(site["css"]) + as_list(site.get("component_stylesheets") or [])   # AUD-F12
        css_paths = []
        for p in (args.css or [site_path(ctx, x) for x in listed]):
            if os.path.realpath(p) not in css_paths:
                css_paths.append(os.path.realpath(p))
        if tokens_path:
            css_paths = [tokens_path] + [p for p in css_paths if p != tokens_path]
        css = Css(ctx, css_paths)
        p1_trace(ctx, css)
        if shape:
            ctx.rep.add("INFO", "POL", "policy", "derived variables, token contrast and the policy's entries are not read: its shape is invalid")
        else:
            check_derived(ctx, css)
            check_stack_vars(ctx, css)
            p3_contrast(ctx, css)
            check_policy(ctx)
        check_boundary(ctx)
        if args.issue:
            if ctx.rep.outcome() != "PASS":
                ctx.rep.add("INFO", "APP", "ready.json", "not issued: the checks did not pass")
            else:
                appr = approval(ctx)
                if appr and ctx.rep.outcome() == "PASS":
                    write_receipt(ctx, appr, css_paths)
    except dl.InputError as exc:
        ctx.rep.error = "ERROR"
        ctx.rep.add("FAIL", "IN", "input", str(exc))
    except dl.ContentError as exc:
        ctx.fail("P2", "parse", str(exc))
    return ctx


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--verify", action="store_true")
    g.add_argument("--issue", action="store_true")
    ap.add_argument("--css", action="append", help="override the CSS paths of site.yaml (repeatable)")
    ap.add_argument("--tokens", help="override the public tokens.css path (design-first)")
    ap.add_argument("--deploy-root")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    if args.issue and (args.css or args.tokens or args.deploy_root):
        print("check_design: ERROR --issue cannot be combined with --css, --tokens or --deploy-root (overrides are for --verify reports only)")
        return dl.EXIT["ERROR"]
    where = pl.output_problem(args.json, args.site)
    if where:
        print("check_design: ERROR --json %s" % where)
        return dl.EXIT["ERROR"]
    try:
        ctx = run(args)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("check_design: INTERNAL (%s)" % exc)
        return dl.EXIT["INTERNAL"]
    if args.json:          # outputs first, the summary after: a report that cannot be written is ERROR 2 (AST-M03)
        try:
            dl.write_output(args.json, ctx.rep.json().encode("utf-8"))      # R2-M03
        except dl.InputError as exc:
            ctx.rep.error = "ERROR"
            ctx.rep.add("INFO", "OUT", args.json, "the report could not be written: %s" % exc)
    print(ctx.rep.text())
    if getattr(ctx, "issued", None):         # the last line of --issue: the owner's step that makes it count (R2-H06)
        print("ready.json SHA-256 %s. Commit ready.json now: approval counts only once it is committed." % ctx.issued)
    return dl.EXIT[ctx.rep.outcome()]


if __name__ == "__main__":
    sys.exit(main())
