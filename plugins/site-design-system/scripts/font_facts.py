"""font_facts.py — the facts a policy face needs, read from a font file (plan 0.4 B.6.1 fonts).

Usage: font_facts.py <font file> [--family NAME] [--ranges 0x20-0x24F,0x400-0x4FF] [--method auto|fonttools|browser]
Prints a YAML face entry: file, sha256, postscript, coverage ranges (code points the font draws) and how they were read.
fontTools reads the cmap directly (WOFF2 needs its brotli module); otherwise Chromium (Playwright) draws each code
point of the probe ranges and CDP CSS.getPlatformFontsForNode says which ones the font itself drew.
The weight range and style are the owner's decision (a variable font's axis is printed when fontTools can read it).
Outcomes: 0 printed, 2 the file or both readers unusable (named), 4 unexpected."""
import argparse
import base64
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import designlib as dl  # noqa: E402

# Probe ranges for the browser method: Latin, Greek, Cyrillic, Hebrew, punctuation, currency, letterlike, arrows, maths.
DEFAULT_RANGES = [(0x20, 0x24F), (0x370, 0x3FF), (0x400, 0x4FF), (0x590, 0x5FF), (0x2000, 0x206F), (0x20A0, 0x20CF),
                  (0x2100, 0x214F), (0x2190, 0x21FF), (0x2200, 0x22FF)]
FORMATS = {".woff2": "woff2", ".woff": "woff", ".ttf": "truetype", ".otf": "opentype"}


def ranges_of(points):
    points = sorted(set(points))
    out = []
    for c in points:
        if out and c == out[-1][1] + 1:
            out[-1][1] = c
        else:
            out.append([c, c])
    return out


def by_fonttools(path):
    from fontTools.ttLib import TTFont
    f = TTFont(path)
    axis = None
    if "fvar" in f:
        axis = {a.axisTag: [a.minValue, a.maxValue] for a in f["fvar"].axes}
    return {"postscript": f["name"].getDebugName(6), "coverage": ranges_of(f.getBestCmap() or {}), "axes": axis}


def by_browser(path, probe):
    from playwright.sync_api import sync_playwright
    with open(path, "rb") as fh:
        data = base64.b64encode(fh.read()).decode("ascii")
    fmt = FORMATS.get(os.path.splitext(path)[1].lower(), "truetype")
    points = [c for lo, hi in probe for c in range(lo, hi + 1) if not (0xD800 <= c <= 0xDFFF) and c not in (0x20, 0xA0, 0xAD)]
    spans = "".join('<span id="c%x">%s</span>' % (c, html.escape(chr(c))) for c in points)
    page_html = ('<!doctype html><html><head><meta charset="utf-8"><style>@font-face { font-family: "FactsProbe"; '
                 'src: url(data:font/%s;base64,%s) format("%s"); } body { font-family: "FactsProbe", monospace; }</style></head>'
                 '<body>%s</body></html>' % (fmt, data, fmt, spans))
    covered, names = [], set()
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
        pg = ctx.new_page()
        pg.set_content(page_html)
        pg.evaluate("document.fonts.ready.then(() => 1)")
        cdp = ctx.new_cdp_session(pg)
        cdp.send("DOM.enable")
        cdp.send("CSS.enable")
        root = cdp.send("DOM.getDocument", {"depth": -1})["root"]
        ids, stack = {}, [root]
        while stack:
            n = stack.pop()
            a = n.get("attributes") or []
            for k in range(0, len(a) - 1, 2):
                if a[k] == "id":
                    ids[a[k + 1]] = n["nodeId"]
            stack.extend(n.get("children") or [])
        for c in points:
            nid = ids.get("c%x" % c)
            fonts = cdp.send("CSS.getPlatformFontsForNode", {"nodeId": nid})["fonts"] if nid else []
            custom = [f for f in fonts if f.get("isCustomFont")]
            if custom:
                covered.append(c)
                names |= {f.get("postScriptName") for f in custom}
        b.close()
    return {"postscript": sorted(n for n in names if n)[0] if names else None, "coverage": ranges_of(covered), "axes": None,
            "probed": [[lo, hi] for lo, hi in probe]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("font")
    ap.add_argument("--family", default="<family name used in your CSS>")
    ap.add_argument("--ranges", help="browser probe ranges, e.g. 0x20-0x24F,0x400-0x4FF")
    ap.add_argument("--method", choices=("auto", "fonttools", "browser"), default="auto")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.font):
        print("font_facts: ERROR no such file %s" % a.font)
        return 2
    probe = DEFAULT_RANGES
    if a.ranges:
        probe = [tuple(int(x, 16) for x in r.split("-")) for r in a.ranges.split(",")]
    facts, errors = None, []
    if a.method in ("auto", "fonttools"):
        try:
            facts, method = by_fonttools(a.font), "fontTools cmap"
        except Exception as exc:  # noqa: BLE001  (missing module, brotli for WOFF2, unreadable file)
            errors.append("fontTools: %s" % exc)
    if facts is None and a.method in ("auto", "browser"):
        try:
            facts, method = by_browser(a.font, probe), "Chromium CDP over the probe ranges"
        except Exception as exc:  # noqa: BLE001
            errors.append("browser: %s" % exc)
    if facts is None:
        print("font_facts: ERROR %s" % "; ".join(errors))
        return 2
    face = {"family": a.family, "file": a.font, "sha256": dl.sha256_file(a.font), "postscript": facts["postscript"],
            "weight": "[min, max]: the owner's decision", "style": "normal", "coverage": facts["coverage"]}
    print("# read by %s%s" % (method, ("; probed %s" % ", ".join("%#x-%#x" % tuple(r) for r in facts["probed"])) if facts.get("probed") else ""))
    if facts.get("axes"):
        print("# variable axes: %s" % json.dumps(facts["axes"]))
    for e in errors:
        print("# not used: %s" % e)
    print("- family: %s" % face["family"])
    for k in ("file", "sha256", "postscript", "weight", "style"):
        print("  %s: %s" % (k, face[k]))
    print("  coverage: [%s]" % ", ".join("[0x%X, 0x%X]" % (lo, hi) for lo, hi in face["coverage"]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print("font_facts: INTERNAL (%s)" % exc)
        sys.exit(4)
