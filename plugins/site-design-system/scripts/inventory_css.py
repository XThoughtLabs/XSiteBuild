"""inventory_css.py — CSS-first seed (plan 0.4 B.3.2): every :root custom property, and the declarations of the
properties listed in PROPS below (colours, fonts, sizes, weights, line heights, letter spacing, radii, shadows,
spacing; shorthands and the common longhands), with their selectors, media conditions and at-rule context, from style
rules; @keyframes are listed whole under keyframes. Properties outside PROPS are not listed (the claim is this list,
nothing more; AST-L02). Deterministic. Usage: inventory_css.py <CSS file> [...] [--json FILE]"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import csslite  # noqa: E402
import designlib as dl  # noqa: E402

SIDES = ("top", "right", "bottom", "left")
PROPS = ("color", "background", "background-color", "background-image", "border", "border-color", "border-top",
         "border-bottom", "border-left", "border-right") + tuple("border-%s-color" % s for s in SIDES) + (
         "outline", "outline-color", "box-shadow", "text-shadow", "fill", "stroke", "stop-color",
         "-webkit-text-fill-color", "-webkit-text-stroke-color", "text-decoration-color",
         "font", "font-family", "font-size", "font-weight", "line-height", "letter-spacing", "border-radius") + tuple(
         "border-%s-radius" % c for c in ("top-left", "top-right", "bottom-right", "bottom-left")) + (
         "padding",) + tuple("padding-%s" % s for s in SIDES) + ("margin",) + tuple("margin-%s" % s for s in SIDES) + (
         "gap", "row-gap", "column-gap", "width", "max-width", "height", "text-transform")


def inventory(paths):
    out = {"custom_properties": [], "values": [], "font_faces": [], "keyframes": [], "nonbinding": [], "unsupported": []}
    for p in paths:
        sheet = csslite.parse(dl.read_bytes_any(p).decode("utf-8"))
        for r in sheet.rules:
            for prop, val in r.decls:
                if prop.startswith("--"):
                    out["custom_properties"].append({"file": p, "line": r.line, "selectors": r.selectors, "media": r.media, "name": prop, "value": val})
                elif prop in PROPS:
                    out["values"].append({"file": p, "line": r.line, "selectors": r.selectors, "media": r.media, "property": prop, "value": val})
        out["font_faces"] += [{"file": p, **f} for f in sheet.font_faces]
        out["keyframes"] += [{"file": p, "name": k, "line": v["line"], "frames": v["frames"]} for k, v in sheet.keyframes.items()]
        out["nonbinding"] += [{"file": p, "at": x} for x in sheet.nonbinding]
        out["unsupported"] += [{"file": p, "at": x} for x in sheet.unsupported]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("css", nargs="+")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    try:
        inv = inventory(a.css)
    except (dl.InputError, ValueError, UnicodeDecodeError) as exc:
        print("inventory_css: ERROR %s" % exc)
        return 2
    text = json.dumps(inv, indent=1)
    if a.json:
        open(a.json, "w", encoding="utf-8").write(text)
    else:
        print(text)
    print("inventory_css: %d custom properties, %d values, %d font faces, %d keyframes, %d unsupported at-rules"
          % (len(inv["custom_properties"]), len(inv["values"]), len(inv["font_faces"]), len(inv["keyframes"]), len(inv["unsupported"])), file=sys.stderr)
    return 3 if inv["unsupported"] else 0


if __name__ == "__main__":
    sys.exit(main())
