"""check_page.py without a browser (outside audit round 1): the reference closure and its guard, staging, the child's
job checks and budgets, and the analysis of synthetic renders (A1-A13). These run on every platform; the browser tests
of the same fixes are in test_check_page.py (they need Playwright, Chromium and the test fonts)."""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import sites  # noqa: E402

sys.path.insert(0, sites.SCRIPTS)
import bundlelib as bl  # noqa: E402
import check_page  # noqa: E402
import designlib as dl  # noqa: E402
import policylib as pl  # noqa: E402

PAPER, INK, GREY = "rgb(255, 253, 247)", "rgb(26, 26, 46)", "rgb(128, 128, 128)"
NO_VERDICT = {"passes": [], "violations": [], "incomplete": [{"id": "color-contrast", "nodes": []}], "inapplicable": []}


def style(**kw):
    s = {"color": INK, "background-color": "rgba(0, 0, 0, 0)", "background-image": "none", "box-shadow": "none",
         "fill": "rgb(0, 0, 0)", "stroke": "none", "stroke-width": "1px", "font-family": '"Inter Test", sans-serif',
         "font-size": "16px", "font-weight": "400", "font-style": "normal", "text-transform": "none", "opacity": "1",
         "padding-left": "0px", "padding-right": "0px", "visibility": "visible", "display": "block", "mix-blend-mode": "normal",
         "filter": "none", "backdrop-filter": "none", "mask-image": "none", "clip-path": "none", "position": "static",
         "content": "normal", "width": "100px", "height": "20px", "color-scheme": "normal", "-webkit-text-stroke-color": INK,
         "-webkit-text-stroke-width": "0px", "text-decoration-line": "none", "text-decoration-color": INK, "text-shadow": "none",
         "outline-color": INK, "outline-style": "none", "outline-width": "0px", "stop-color": "rgb(0, 0, 0)", "stop-opacity": "1",
         "box-sizing": "content-box", "fill-opacity": "1", "stroke-opacity": "1"}
    for side in check_page.SIDES:
        s.update({"border-%s-color" % side: INK, "border-%s-width" % side: "0px", "border-%s-style" % side: "none"})
    s.update({k.replace("_", "-"): v for k, v in kw.items()})
    s.setdefault("-webkit-text-fill-color", s["color"])
    return s


def el(eid, tag="p", text="Some text.", parent="f0:0", svg=False, opacity=1.0, visible=True, **st):
    return {"id": eid, "tag": tag, "path": "html > body > %s.%s" % (tag, eid.replace(":", "-")), "rect": [0, 0, 100, 20],
            "content_width": 100.0, "layout": [100, 20], "visible": visible, "text": text,
            "text_rects": [[0, 0, 80, 16]] if text else [], "parent": parent, "svg": svg, "role": "", "heading": False,
            "label": False, "code": False, "measure": [], "button_sel": False, "in_noscript": False, "pseudo": {},
            "textpseudo": {}, "opacity": opacity, "style": style(**st)}


def body(**st):
    return el("f0:0", tag="body", text="", parent=None, **dict({"background_color": PAPER}, **st))


def rnd(elements, axe=None, name="w1280-light", scheme="light", width=1280, overlap=None, paints=None, a11y="none", fonts=None):
    frame = {"key": "f0", "url": "http://127.0.0.1/x", "main": True,
             "data": {"elements": elements, "structure": [], "shadow_hosts": [], "media": {}},
             "axe_contrast": NO_VERDICT if axe is None else axe,
             "overlap": overlap or {e["id"]: ["ok"] * 5 for e in elements if e["text"]}}
    if paints:
        frame["paints_before"], frame["paints_after"] = paints
    if a11y != "none":
        frame["axe_a11y"] = a11y
    return {"name": name, "width": width, "height": 800, "scheme": scheme, "frames": [frame], "fonts": fonts or {},
            "preferences": prefs_unchanged()}


def prefs_unchanged():
    """The renderer's record of the fresh loads (W1) when every other reader-preference state painted the same."""
    return {"evidence": {"confirmed": True},
            "states": [{"label": check_page.preference_label(s), "confirmed": True, "changed": []} for s in check_page.preference_states()]}


def analysis(d, *renders, access_log=None, files=None, font_srcs=None):
    rep = dl.Report("t")
    an = check_page.Analysis(pl.Profile(d), rep, "index.html", "0" * 64,
                             {"renders": list(renders), "origin": "http://127.0.0.1", "access_log": access_log or []})
    an.files, an.font_srcs, an.bundle = files or {}, font_srcs or [], os.path.dirname(d)
    return an, rep


def items(rep, check, status=None, word=None):
    return [i for i in rep.items if i["check"] == check and (status is None or i["status"] == status) and (word is None or word in i["detail"] or word in i["path"])]


@pytest.fixture
def X(tmp_path):
    return sites.build_x(tmp_path)


# ------------------------------------------------------------------ A6: the fallback (AST-H05, AUD-F01) and axe (AST-H04)

def test_a6_gradient_is_sampled_between_its_stops(X):
    """AST-H05: black text on a red-to-green gradient passes at both stops but not between them."""
    red, green = dl.Colour(255, 0, 0), dl.Colour(0, 160, 0)
    black = dl.Colour(0, 0, 0)
    assert dl.ratio(dl.composite(black, (255, 0, 0)), (255, 0, 0)) >= 4.5 and dl.ratio(dl.composite(black, (0, 160, 0)), (0, 160, 0)) >= 4.5
    mid = check_page.gradient_samples([red, green])[check_page.GRADIENT_STEPS // 2]
    assert dl.ratio((0, 0, 0), (mid.r, mid.g, mid.b)) < 4.5
    p = el("f0:1", color="rgb(0, 0, 0)", background_image="linear-gradient(rgb(255, 0, 0), rgb(0, 160, 0))")
    an, rep = analysis(X, rnd([body(), p]))
    an.a6()
    assert items(rep, "A6", "FAIL", "fallback"), rep.items


def test_a6_faded_group_over_its_own_background_is_incomplete(X):
    """AST-H05: white text in a 50% opaque black box on white is group compositing (3.98:1), not text alpha (5.28:1)."""
    box = el("f0:1", tag="div", text="", background_color="rgb(0, 0, 0)", opacity=0.5)
    box["style"]["opacity"] = "0.5"
    p = el("f0:2", parent="f0:1", color="rgb(255, 255, 255)", opacity=0.5)
    an, rep = analysis(X, rnd([body(background_color="rgb(255, 255, 255)"), box, p]))
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", "group compositing"), rep.items


def test_a6_faded_ancestor_above_every_background_is_computed(X):
    """Control: a faded element with no painted background at or below it is text alpha x opacity (computed)."""
    box = el("f0:1", tag="div", text="")
    box["style"]["opacity"] = "0.1"
    p = el("f0:2", parent="f0:1", opacity=0.1)
    an, rep = analysis(X, rnd([body(), box, p]))
    an.a6()
    assert items(rep, "A6", "FAIL", "fallback") and not items(rep, "A6", "INCOMPLETE"), rep.items


def test_a6_candidate_budget_is_incomplete(X):
    """AST-H05: more backdrops than the budget give INCOMPLETE, never a silent cut."""
    g = "linear-gradient(rgba(255, 0, 0, 0.5), rgba(0, 0, 255, 0.5), rgba(0, 255, 0, 0.5))"
    outer = el("f0:1", tag="div", text="", background_image=g)
    p = el("f0:2", parent="f0:1", background_image=g)
    an, rep = analysis(X, rnd([body(), outer, p]))
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", "budget"), rep.items


@pytest.mark.parametrize("axe", ["none", "pass"])
def test_a6_text_fill_paints_the_glyphs(X, axe):
    """AST-H05, AUD-F01(2): the glyphs are drawn with -webkit-text-fill-color; axe's pass read color."""
    p = el("f0:1", color=INK, **{"-webkit-text-fill-color": PAPER})
    res = NO_VERDICT if axe == "none" else {"passes": [{"id": "color-contrast", "nodes": [{"id": "f0:1", "target": ["p"], "data": {}}]}],
                                            "violations": [], "incomplete": [], "inapplicable": []}
    an, rep = analysis(X, rnd([body(), p], axe=res))
    an.a6()
    assert items(rep, "A6", "FAIL", "-webkit-text-fill-color"), rep.items


def test_a6_large_text_size_is_not_rounded(X):
    """AST-H05: 18.666 px bold is below 56/3 px (18.6667): normal text, 4.5:1; rounded to 18.67 it would pass at 3:1."""
    p = el("f0:1", color=GREY, font_size="18.666px", font_weight="700")
    an, rep = analysis(X, rnd([body(), p]))
    an.a6()
    assert items(rep, "A6", "FAIL", "threshold 4.5"), rep.items


def test_a6_and_a5_svg_text_use_fill(X):
    """AUD-F01(3): SVG text draws with fill: A6's fallback and A5 read it."""
    t = el("f0:1", tag="text", svg=True, color=INK, fill=PAPER)
    an, rep = analysis(X, rnd([body(), t]))
    an.a6()
    assert items(rep, "A6", "FAIL", "fill"), rep.items
    t2 = el("f0:1", tag="text", svg=True, color=INK, fill="rgb(154, 52, 18)")       # the forbidden old-accent
    an, rep = analysis(X, rnd([body(), t2]))
    an.a5()
    assert items(rep, "A5", "FAIL"), rep.items


def test_a6_every_axe_violation_is_a_fail(X):
    """AST-H04: a violation whose node is unresolved, or on an element that is not a text run, is not dropped."""
    viol = {"passes": [], "incomplete": [], "inapplicable": [], "violations": [{"id": "color-contrast", "nodes": [
        {"id": None, "target": ["#lost"], "data": {"fgColor": "#fff", "bgColor": "#fff", "contrastRatio": 1, "expectedContrastRatio": "4.5:1"}},
        {"id": "f0:0", "target": ["body"], "data": {}}]}]}
    an, rep = analysis(X, rnd([body(), el("f0:1")], axe=viol))
    an.a6()
    assert items(rep, "A6", "FAIL", "axe target #lost") and items(rep, "A6", "FAIL", "html > body > body"), rep.items


def test_a6_paint_changed_during_checking_is_incomplete(X):
    """AST-H03: page CSS that reacts to the checker's marker (or to the taller viewport) changes the paint between the
    first read and the last: the evidence does not describe one state."""
    before, after = ["a", "b"], ["a", "b'"]
    an, rep = analysis(X, rnd([body(), el("f0:1")], paints=(before, after)))
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", "paint changed"), rep.items
    an, rep = analysis(X, rnd([body(), el("f0:1")], paints=(before, list(before))))     # control: unchanged
    an.a6()
    assert not items(rep, "A6", "INCOMPLETE", "paint changed"), rep.items


def test_a6_paint_change_of_a_non_ancestor_is_incomplete(X):
    """HQ's V4: a sibling layer behind the text (not its ancestor) that changes under the checker's marker or in the
    taller viewport changes what the reader sees: every text run of the frame gets A6 INCOMPLETE."""
    layer = el("f0:1", tag="div", text="")               # a sibling of the paragraph: its parent is the body
    p = el("f0:2", parent="f0:0")
    before, after = ["body", "layer", "p"], ["body", "layer'", "p"]
    an, rep = analysis(X, rnd([body(), layer, p], paints=(before, after)))
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", "paint changed") and items(rep, "A6", "INCOMPLETE", p["path"]), rep.items
    an, rep = analysis(X, rnd([body(), layer, p], paints=(before, list(before))))     # control: nothing changed
    an.a6()
    assert not items(rep, "A6", "INCOMPLETE", "paint changed"), rep.items


def test_a6_summary_is_info_and_findings_keep_their_render(X):
    """AST-L01: the A6 summary is INFO; the same finding in two renders is kept twice."""
    p = el("f0:1", color=PAPER)
    an, rep = analysis(X, rnd([body(), p]), rnd([body(), p], name="w1280-dark", scheme="dark"))
    an.a6()
    assert items(rep, "A6", "INFO", "color-contrast in 1 frames") and not items(rep, "A6", "PASS"), rep.items
    assert sorted(i["render"] for i in items(rep, "A6", "FAIL")) == ["w1280-dark", "w1280-light"], rep.items


# ------------------------------------------------------------------ A1 (AST-H06)

def _font_profile(X, tmp_path):
    """X with an approved face file whose first bytes are a TrueType header (on any machine)."""
    font = b"\x00\x01\x00\x00" + b"synthetic approved face"
    path = os.path.join(os.path.dirname(X), "site", "fonts", "x.ttf")
    old = sites.hashlib.sha256(open(path, "rb").read()).hexdigest()
    open(path, "wb").write(font)
    sites.edit(os.path.join(X, "policy.yaml"), old, sites.hashlib.sha256(font).hexdigest())
    return font


def served(key, data):
    """One access-log entry as the loopback server writes it: the staged key served and the SHA-256 sent (R2-H04)."""
    return {"path": "/" + key, "status": 200, "key": key, "sha256": dl.sha256(data)}


def test_a1_served_font_by_first_bytes(X, tmp_path):
    font = _font_profile(X, tmp_path)
    other = b"\x00\x01\x00\x00" + b"another face"
    log = [served("fonts/x.ttf", font), served("fonts/f.bin", other)]
    an, rep = analysis(X, access_log=log, files={"fonts/x.ttf": font, "fonts/f.bin": other})
    an.a1()
    assert items(rep, "A1", "FAIL", "fonts/f.bin") and items(rep, "A1", "PASS", "fonts/x.ttf"), rep.items


def test_a1_approved_name_needs_its_approved_file_served(X, tmp_path):
    font = _font_profile(X, tmp_path)
    run = {"isCustomFont": True, "postScriptName": sites.FONTS["x"][1], "familyName": "Inter Test", "glyphCount": 10}
    fonts = {"f0:1": [run]}
    an, rep = analysis(X, rnd([body(), el("f0:1")], fonts=fonts))
    an.a1()
    assert items(rep, "A1", "FAIL", "approved file was not served"), rep.items
    an, rep = analysis(X, rnd([body(), el("f0:1")], fonts=fonts), access_log=[served("fonts/x.ttf", font)],
                       files={"fonts/x.ttf": font})
    an.a1()
    assert not items(rep, "A1", "FAIL"), rep.items          # control: the approved file was served


def test_a1_empty_platform_font_data_is_incomplete(X):
    an, rep = analysis(X, rnd([body(), el("f0:1")], fonts={"f0:1": []}))
    an.a1()
    assert items(rep, "A1", "INCOMPLETE", "empty platform-font data"), rep.items


@pytest.mark.parametrize("kind,value", [("url", "data:font/ttf;base64,AAEAAA=="), ("url", "blob:x"), ("local", "Inter"),
                                        ("url", "http://192.0.2.1/f.woff2")], ids=["data", "blob", "local", "remote"])
def test_a1_font_sources_must_be_bundle_files(X, kind, value):
    an, rep = analysis(X, font_srcs=[(kind, value, "index.html"), ("url", "fonts/x.ttf", "x.css")])
    an.a1()
    fails = items(rep, "A1", "FAIL", "not a bundle file")
    assert len(fails) == 1 and fails[0]["path"] == "index.html", rep.items


# ------------------------------------------------------------------ A2 (AST-H07), A4 and A7 (AST-M13)

def test_a2_svg_stop_colour_is_a_gradient_stop(X):
    stop = el("f0:1", tag="stop", text="", svg=True, visible=False, **{"stop-color": "rgb(154, 52, 18)"})
    an, rep = analysis(X, rnd([body(), stop]))
    an.a2()
    assert items(rep, "A2", "FAIL", "stop-color"), rep.items


def test_a2_and_a6_unreadable_gradient_stops(X):
    g = "linear-gradient(oklch(0.2 0.05 260), oklch(0.2 0.05 260))"
    assert pl.gradient_stops(g) == ["oklch(0.2 0.05 260)", "oklch(0.2 0.05 260)"]
    p = el("f0:1", background_image=g)
    an, rep = analysis(X, rnd([body(), p]))
    an.a2()
    an.a6()
    assert items(rep, "A2", "INCOMPLETE", "could not be read") and items(rep, "A6", "INCOMPLETE", "unreadable gradient"), rep.items


@pytest.mark.parametrize("value,stops", [("linear-gradient(to right, red 10%, hsl(0 100% 50%) 40%)", ["red", "hsl(0 100% 50%)"]),
                                         ("radial-gradient(circle at center, color-mix(in srgb, red, blue), transparent)",
                                          ["color-mix(in srgb, red, blue)", "transparent"]),
                                         ("linear-gradient(in oklab 45deg, var(--a), color(srgb 1 0 0))", ["var(--a)", "color(srgb 1 0 0)"])])
def test_every_gradient_stop_is_kept(value, stops):
    """AST-H07, AUD-F02: named colours and every colour function are stops; geometry and positions are not."""
    assert pl.gradient_stops(value) == stops


def test_a7_reads_the_layout_width(X):
    """AST-M13: a 681 px reading box scaled to 500 px by a transform is still 681 px wide; unrounded."""
    p = el("f0:1")
    p["rect"][2], p["content_width"] = 500.0, 680.004
    an, rep = analysis(X, rnd([body(), p]))
    an.a7()
    assert items(rep, "A7", "FAIL"), rep.items


def test_a4_reads_the_layout_area(X):
    """AST-M13: a rotated 50x50 fill has a 70x70 bounding box but a 2,500 px2 area (the limit, which passes)."""
    box = el("f0:1", tag="div", text="", background_color="rgb(194, 65, 12)")
    box["rect"][2:] = [70.7, 70.7]
    box["layout"] = [50, 50]
    an, rep = analysis(X, rnd([body(), box]))
    an.a4()
    assert not items(rep, "A4", "FAIL"), rep.items
    box["layout"] = [41, 61]
    an, rep = analysis(X, rnd([body(), box]))
    an.a4()
    assert items(rep, "A4", "FAIL"), rep.items


def test_a2_extra_alpha_tolerance_boundary(X):
    """AST-M19: a browser-serialised alpha within 0.005 of an extra's alpha passes; beyond it does not."""
    pal = pl.Palette(pl.Profile(X))
    assert pal.allowed_colour(dl.parse_colour("rgba(26, 26, 46, 0.205)"), "light", "border-color", ["border"], near=True)[0]
    assert not pal.allowed_colour(dl.parse_colour("rgba(26, 26, 46, 0.2051)"), "light", "border-color", ["border"], near=True)[0]
    assert not pal.allowed_colour(dl.parse_colour("rgba(26, 26, 46, 0.205)"), "light", "border-color", ["border"], near=False)[0]


# ------------------------------------------------------------------ A8, A9, A11 (AST-M14), A12 (AST-M15), A13 (AST-M16)

def test_a8_runs_in_dark_renders(X):
    p = el("f0:1", text_transform="uppercase")
    an, rep = analysis(X, rnd([body(), el("f0:1")]), rnd([body(), p], name="w1280-dark", scheme="dark"))
    an.a8()
    assert [i for i in items(rep, "A8", "FAIL") if i.get("render") == "w1280-dark"], rep.items


def test_a9_compares_presence(X):
    hidden = el("f0:1", display="none", visible=False)
    an, rep = analysis(X, rnd([body(), el("f0:1")]), rnd([body(), hidden], name="w1280-dark", scheme="dark"))
    an.a9()
    assert items(rep, "A9", "FAIL", "visible"), rep.items


def test_a11_counts_the_dark_desktop_render(X):
    b1, b2 = el("f0:1", tag="a", text="One"), el("f0:2", tag="a", text="Two")
    b1["button_sel"] = b2["button_sel"] = True
    an, rep = analysis(X, rnd([body(), el("f0:1", tag="a", text="One")]), rnd([body(), b1, b2], name="w1280-dark", scheme="dark"))
    an.a11()
    assert [i for i in items(rep, "A11", "WARN") if i.get("render") == "w1280-dark"], rep.items


def test_a12_needs_execution_evidence(X):
    empty = {"passes": [], "violations": [], "incomplete": [], "inapplicable": []}
    an, rep = analysis(X, rnd([body(), el("f0:1")], a11y=empty))
    an.a12()
    assert items(rep, "A12", "INCOMPLETE", "no execution evidence") and not items(rep, "A12", "PASS"), rep.items


@pytest.mark.parametrize("snap,word", [({"rule_version": check_page.A13_RULE_VERSION}, "keys"),
                                       ({"rule_version": check_page.A13_RULE_VERSION, "page": "index.html", "page_sha256": "0" * 64, "entries": ["heading|1|A"],
                                         "coverage": {"state": "incomplete", "gaps": ["shadow DOM: div"]}}, "incomplete coverage"),
                                       ({"rule_version": check_page.A13_RULE_VERSION, "page": "index.html", "page_sha256": "abc", "entries": ["heading|1|A"],
                                         "coverage": {"state": "complete", "gaps": []}}, "full SHA-256"),
                                       ({"rule_version": check_page.A13_RULE_VERSION, "page": "index.html", "page_sha256": "0" * 64, "entries": [],
                                         "coverage": {"state": "complete", "gaps": []}}, "non-empty")],
                         ids=["bare", "incomplete coverage", "short hash", "no entries"])
def test_a13_snapshot_schema(X, tmp_path, snap, word):
    path = tmp_path / "snap.json"
    path.write_text(json.dumps(snap))
    an, rep = analysis(X, rnd([body(), el("f0:1")]))
    an.a13(str(path), dl.sha256(path.read_bytes()))
    assert items(rep, "A13", "INCOMPLETE", word) and not items(rep, "A13", "PASS"), rep.items


def test_a13_valid_snapshot_passes(X, tmp_path):
    path = tmp_path / "snap.json"
    path.write_text(json.dumps({"rule_version": check_page.A13_RULE_VERSION, "page": "index.html", "page_sha256": "0" * 64, "entries": ["heading|1|A"],
                                "coverage": {"state": "complete", "gaps": []}}))
    r = rnd([body(), el("f0:1")])
    r["frames"][0]["data"]["structure"] = [{"entry": "heading|1|A", "visible": True, "id": "f0:1"}]
    an, rep = analysis(X, r)
    an.a13(str(path), dl.sha256(path.read_bytes()))
    assert items(rep, "A13", "PASS") and items(rep, "A13", "PASS")[0].get("render") == "w1280-light", rep.items


# ------------------------------------------------------------------ the closure, its guard and staging (AST-H01, H02, M02, AUD-F03)

def _bundle(tmp_path, files):
    b = tmp_path / "bundle"
    for rel, content in files.items():
        p = b / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return os.path.realpath(str(b))


def _guard(X):
    return bl.Guard(pl.Profile(X), pl.folder_files(X))


@pytest.mark.parametrize("href", ["a%00b.css", "a%1fb.css"], ids=["NUL", "unit separator"])
def test_control_character_in_a_reference_is_outside_the_bundle(X, tmp_path, href):
    """HQ's C5: a reference whose percent-decoded path holds a control character names no bundle file: A10 reports it
    as leaving the bundle, never an internal error."""
    b = _bundle(tmp_path, {"index.html": '<link rel="stylesheet" href="%s"><p>t</p>' % href})
    clo = check_page.closure(b, "index.html", _guard(X))
    assert [ref for ref, _ in clo["outside"]] == [href], clo["outside"]
    rep = dl.Report("t")
    check_page.closure_findings(rep, clo)
    assert items(rep, "A10", "FAIL", "leaves the bundle"), rep.items


def test_closure_ignores_urls_in_css_comments(X, tmp_path):
    b = _bundle(tmp_path, {"index.html": '<link rel="stylesheet" href="a.css"><p>t</p>', "a.css": "/* url(unused.js) */ p { color: red; }",
                           "unused.js": "secret()"})
    clo = check_page.closure(b, "index.html", _guard(X))
    assert sorted(clo["files"]) == ["a.css", "index.html"], clo["files"].keys()


@pytest.mark.parametrize("rel", [".env/x.png", "a/.git/x.png", "keys/site.pem/x.png"])
def test_closure_refuses_forbidden_names_in_any_component(X, tmp_path, rel):
    b = _bundle(tmp_path, {"index.html": '<img alt="x" src="%s"><p>t</p>' % rel, rel: b"\x89PNG"})
    with pytest.raises(check_page.StageError, match="VCS or secret pattern"):
        check_page.closure(b, "index.html", _guard(X))


def test_closure_refuses_a_copy_of_a_site_design_folder_file(X, tmp_path):
    readme = open(os.path.join(X, "README.md"), "rb").read()
    b = _bundle(tmp_path, {"index.html": '<a href="notes.txt">n</a><img alt="r" src="notes.txt"><p>t</p>', "notes.txt": readme})
    with pytest.raises(check_page.StageError, match="same bytes as the site design folder's README.md"):
        check_page.closure(b, "index.html", _guard(X))


def test_staging_writes_the_bytes_the_closure_read(X, tmp_path):
    """AST-H02: the file is read once; a change after the closure never reaches the stage."""
    b = _bundle(tmp_path, {"index.html": '<img alt="x" src="x.png"><p>t</p>', "x.png": b"first bytes"})
    clo = check_page.closure(b, "index.html", _guard(X))
    open(os.path.join(b, "x.png"), "wb").write(b"replaced after the closure, and longer")
    stage = tmp_path / "stage"
    stage.mkdir()
    check_page.stage_files(b, clo["files"], str(stage))
    assert (stage / "x.png").read_bytes() == b"first bytes"


def test_closure_reads_nested_srcdoc_and_frames_met_as_files(X, tmp_path):
    """AST-M02: a script in a second-level srcdoc, and a frame document first met as a plain file, are both found."""
    inner = '<iframe srcdoc="&lt;script&gt;x()&lt;/script&gt;"></iframe>'
    html = '<p>t</p><iframe srcdoc="%s"></iframe>' % inner.replace("&", "&amp;").replace('"', "&quot;")
    b = _bundle(tmp_path, {"index.html": html})
    clo = check_page.closure(b, "index.html", _guard(X))
    assert any("srcdoc, level 2" in s for s in clo["scripts"]), clo["scripts"]
    b2 = _bundle(tmp_path / "two", {"index.html": '<link rel="preload" href="frame.html"><iframe src="frame.html"></iframe><p>t</p>',
                                    "frame.html": "<script>y()</script><p>f</p>"})
    clo = check_page.closure(b2, "index.html", _guard(X))
    assert any(s.startswith("frame.html") for s in clo["scripts"]), clo["scripts"]


def test_closure_refuses_links(X, tmp_path):
    """AST-H02: a linked file is never followed (POSIX: O_NOFOLLOW on the last component; Windows: reparse points)."""
    b = _bundle(tmp_path, {"index.html": '<img alt="l" src="link.png"><p>t</p>'})
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    try:
        os.symlink(str(secret), os.path.join(b, "link.png"))
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links cannot be created here")
    with pytest.raises(check_page.StageError, match="link or junction"):
        check_page.closure(b, "index.html", _guard(X))


def test_closure_refuses_linked_folders(X, tmp_path):
    """AST-H02: a folder on the path that is a link or junction is refused (POSIX: the walk by directory
    descriptors; Windows: the reparse-point check of every component)."""
    b = _bundle(tmp_path, {"index.html": '<img alt="l" src="sub/x.png"><p>t</p>'})
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.png").write_bytes(b"\x89PNG")
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(outside), os.path.join(b, "sub"))
        else:
            os.symlink(str(outside), os.path.join(b, "sub"), target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("folder links cannot be created here")
    with pytest.raises(check_page.StageError, match="link"):
        check_page.closure(b, "index.html", _guard(X))


def test_closure_refuses_hard_links_and_profile_names_in_any_case(X, tmp_path):
    b = _bundle(tmp_path, {"index.html": '<img alt="h" src="hard.png"><p>t</p>', "real.png": b"\x89PNG"})
    os.link(os.path.join(b, "real.png"), os.path.join(b, "hard.png"))
    with pytest.raises(check_page.StageError, match="hard link"):
        check_page.closure(b, "index.html", _guard(X))
    b2 = _bundle(tmp_path / "two", {"index.html": '<img alt="p" src="Policy.YAML"><p>t</p>', "Policy.YAML": "roles: {}"})
    with pytest.raises(check_page.StageError, match="site design folder file name"):
        check_page.closure(b2, "index.html", _guard(X))


def test_a2_gradient_without_a_readable_stop(X):
    """AUD-F02: a gradient in background-image with no readable stop at all gives INCOMPLETE."""
    an, rep = analysis(X, rnd([body(), el("f0:1", background_image="linear-gradient(to right)")]))
    an.a2()
    assert items(rep, "A2", "INCOMPLETE", "without a readable stop"), rep.items


def test_report_truncation_keeps_failures_first(X, monkeypatch, tmp_path):
    def fake_run(args, rep):
        for i in range(10):
            rep.add("PASS", "A2", "p%d" % i, "x")
        rep.add("FAIL", "A2", "last", "the one failure")
        return None
    monkeypatch.setattr(check_page, "run", fake_run)
    monkeypatch.setattr(check_page, "MAX_ITEMS", 5)
    assert check_page.main([str(tmp_path), "--page", "index.html", "--site", X]) == 1


def test_first_of_duplicate_attributes_wins():
    """AUD-F03(1): Chromium reads the first of duplicate attributes; so do both parsers."""
    pr = check_page.RefParser()
    pr.feed('<a href="javascript:alert(1)" href="#ok">x</a>')
    assert pr.scripts == ["<a href=javascript:>"]


def test_closure_findings_are_reported_before_a_budget_stop(X, tmp_path, monkeypatch, capsys):
    """AST-M03: a known A10 failure is reported even when the closure's budget stops the run; an unwritable report is
    ERROR 2, never a traceback after a printed outcome."""
    import importlib.util
    sites.issue(X)
    b = sites.bundle(X, "p", '<!doctype html><html lang="en"><head><title>t</title><link rel="stylesheet" href="x.css"></head>'
                             '<body><img alt="o" src="../../outside.png"><p>x</p></body></html>')
    real = importlib.util.find_spec
    monkeypatch.setattr(check_page.importlib.util, "find_spec", lambda n: object() if n == "playwright" else real(n))
    monkeypatch.setattr(check_page, "MAX_FILES", 1)       # the page is read and parsed; the next file stops the closure
    assert check_page.main([b, "--page", "index.html", "--site", X]) == 1
    out = capsys.readouterr().out
    assert "leaves the bundle" in out and "more than" in out, out
    code = check_page.main([b, "--page", "index.html", "--site", X, "--json", os.path.join(str(tmp_path), "no-such-folder", "r.json")])
    assert code == 2 and "could not be written" in capsys.readouterr().out


# ------------------------------------------------------------------ the child and the budgets (AST-M21, AST-M18, AST-M03)

def _job(base, mode="browser", **extra):
    for x in ("site", "out", "home"):
        os.makedirs(os.path.join(base, x), exist_ok=True)
    job = {"containment": mode, "stage": os.path.join(base, "site"), "out": os.path.join(base, "out"), "home": os.path.join(base, "home"),
           "result": os.path.join(base, "out", "result.json"), "page": "index.html", "axe": "", "selectors": {}, "tags": None, "run_as": None,
           "inventory": {}}
    job.update(extra)
    path = os.path.join(base, "job.json")
    open(path, "w").write(json.dumps(job))
    return path, job


@pytest.mark.parametrize("mode,extra,word", [("os-unchecked", {}, "unknown containment mode"),
                                             ("browser", {"stage": "ELSEWHERE"}, "stage is not the staging folder's site")],
                         ids=["mode", "stage elsewhere"])
def test_child_refuses_a_job_it_did_not_get_from_the_parent(tmp_path, mode, extra, word):
    base = str(tmp_path / "sds-page-test")
    if extra.get("stage") == "ELSEWHERE":
        extra = {"stage": str(tmp_path)}
    path, job = _job(base, mode, **extra)
    assert check_page.child_main(path) == 0
    result = json.load(open(job["result"]))
    assert word in result.get("error", "") and "containment" not in result, result


@pytest.mark.parametrize("mode", ["os-unchecked", "browser"], ids=["unknown mode", "known mode"])
def test_refused_job_writes_nothing_outside_its_staging_folder(tmp_path, mode):
    """HQ's C4: a refused job whose result path names another folder leaves no file there, nor in the staging folder."""
    base = str(tmp_path / "sds-page-test")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = str(elsewhere / "result.json")
    path, job = _job(base, mode, result=target)
    assert check_page.child_main(path) != 0
    assert not os.listdir(str(elsewhere)) and not os.listdir(os.path.join(base, "out")), (os.listdir(str(elsewhere)), os.listdir(os.path.join(base, "out")))


def test_child_result_is_bounded_before_it_is_written(tmp_path, monkeypatch):
    base = str(tmp_path / "sds-page-test")
    path, job = _job(base, "os-unchecked")
    monkeypatch.setattr(check_page, "MAX_RESULT_BYTES", 20)
    check_page.child_main(path)
    assert "over_budget" in json.load(open(job["result"]))


def test_one_deadline_for_every_attempt(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(check_page.subprocess, "Popen", lambda *a, **k: started.append(a) or (_ for _ in ()).throw(AssertionError("started")))
    base = str(tmp_path / "sds-page-test")
    _job(base)
    res = check_page.run_child({"out": os.path.join(base, "out"), "home": os.path.join(base, "home"),
                                "result": os.path.join(base, "out", "result.json")}, "browser", base, None, check_page.time.monotonic() - 1)
    assert res == {"timeout": True} and not started


def test_timeout_kills_without_killpg(tmp_path, monkeypatch):
    """AST-M03: where os.killpg does not exist (Windows), the timed-out process itself is killed."""
    class Proc:
        pid, killed, calls = 1, False, 0

        def communicate(self, timeout=None):
            Proc.calls += 1
            if Proc.calls == 1:
                raise subprocess.TimeoutExpired("x", timeout)
            return b"", b""

        def kill(self):
            Proc.killed = True
    monkeypatch.delattr(check_page.os, "killpg", raising=False)
    monkeypatch.setattr(check_page.subprocess, "Popen", lambda *a, **k: Proc())
    base = str(tmp_path / "sds-page-test")
    _job(base)
    res = check_page.run_child({"out": os.path.join(base, "out"), "home": os.path.join(base, "home"),
                                "result": os.path.join(base, "out", "result.json")}, "browser", base, None, check_page.time.monotonic() + 60)
    assert res == {"timeout": True} and Proc.killed


def test_report_truncation_keeps_a_slot(X, monkeypatch, capsys, tmp_path):
    """AST-M18: after truncation the report holds at most MAX_ITEMS items, the truncation item included."""
    def fake_run(args, rep):
        for i in range(10):
            rep.add("FAIL", "A2", "p%d" % i, "x")
        return None
    monkeypatch.setattr(check_page, "run", fake_run)
    monkeypatch.setattr(check_page, "MAX_ITEMS", 5)
    j = os.path.join(str(tmp_path), "r.json")
    check_page.main([str(tmp_path), "--page", "index.html", "--site", X, "--json", j])
    assert len(json.load(open(j))["items"]) == 5


@pytest.mark.parametrize("opt", ["--json", "--snapshot", "--out"])
def test_outputs_refused_inside_the_site_design_folder(X, opt, capsys):
    """AST-M04."""
    target = os.path.join(X, "out.json") if opt != "--out" else os.path.join(X, "shots")
    assert check_page.main([os.path.dirname(X), "--page", "index.html", "--site", X, opt, target]) == 2
    assert "inside the site design folder" in capsys.readouterr().out and not os.path.exists(target)


def test_receipt_fingerprint_option_is_checked(X, capsys):
    assert check_page.main([os.path.dirname(X), "--page", "index.html", "--site", X, "--receipt-sha256", "abc"]) == 2
    assert "64 hex digits" in capsys.readouterr().out


# ================================================================== outside audit round 2 (Sol 6.1), without a browser

SENTINEL = b"SDS-SYNTHETIC-SENTINEL-7f3a"      # synthetic bytes standing in for a secret; never a real key

# R2-H01: one portable component grammar. Each reference names a file Windows would open under another name than the
# one the guard checked (a trailing dot or space, a stream, a short 8.3 alias, a device, a drive).
ALIASES = ["vault.key.", "vault.key%20", "vault.key::$DATA", "policy.yaml.", "GIT~1/config", "CON.css", "nul", "c:x.css",
           "sub/c:/x.css", "./vault.key::$DATA", "sub/x.css:alt", "canary.key.", "canary.key%20%20", "vault.key%2e", "x.css:alt", "COM%C2%B9.css", "lpt3.txt"]


def _alias_bundle(tmp_path, href):
    return _bundle(tmp_path, {"index.html": '<link rel="stylesheet" href="%s"><img alt="a" src="%s"><p>t</p>' % (href, href),
                              "vault.key": SENTINEL, "canary.key": SENTINEL, "x.css": b"p { color: red; }"})


@pytest.mark.parametrize("href", ALIASES)
def test_windows_aliases_are_outside_the_bundle(X, tmp_path, href):
    """R2-H01: on every platform the resolver refuses a component Windows would read as another name: the reference is
    outside the bundle (A10), never read, staged or quoted; a nested drive path is named, never INTERNAL."""
    b = _alias_bundle(tmp_path, href)
    clo = check_page.closure(b, "index.html", _guard(X))
    # 'x.css:alt', 'c:x.css' and 'vault.key::$DATA' read as a URL scheme (remote, as in the browser); the rest are outside
    assert href in [ref for ref, _ in clo["outside"] + clo["remote"]], (clo["outside"], clo["missing"], sorted(clo["files"]))
    assert sorted(clo["files"]) == ["index.html"] and not clo["missing"], sorted(clo["files"])
    rep = dl.Report("t")
    check_page.closure_findings(rep, clo)
    assert (items(rep, "A10", "FAIL", "leaves the bundle") or items(rep, "A10", "FAIL", "non-local reference"))         and SENTINEL.decode() not in json.dumps(rep.items), rep.items


def test_a_literal_trailing_space_is_stripped_and_then_refused(X, tmp_path):
    """R2-H01: a literal space at the end of an attribute is stripped (as browsers do), so 'vault.key ' is vault.key,
    refused by its name before any byte is read."""
    b = _alias_bundle(tmp_path, "vault.key ")
    with pytest.raises(check_page.StageError, match="VCS or secret pattern"):
        check_page.closure(b, "index.html", _guard(X))


@pytest.mark.parametrize("rel", ["vault.key.", "vault.key ", "vault.key::$DATA", "GIT~1/config", "CON.css", "nul", "Aux.txt",
                                 "com1", "LPT\u00b2.css", "sub/c:x", "a<b", "a|b", "a?b", "a*b", 'a"b'])
def test_the_reader_refuses_the_component_grammar(X, tmp_path, rel):
    """R2-H01: the shared reader and the guard refuse the same components themselves (the reader is the last line):
    no byte of the aliased file is returned, on any platform."""
    b = _alias_bundle(tmp_path, "x.css")
    data, why = bl.safe_read(b, rel, 1000)
    assert data is None and why and why != bl.MISSING, (data, why)
    data, why = _guard(X).read(b, rel, 1000)
    assert data is None and why and why != bl.MISSING and SENTINEL.decode() not in why, (data, why)


@pytest.mark.parametrize("rel", ["x.css", "sub/x.css", "a.b.css", "my file.css", "con-tact.css", "nullable.css", "com10.css", "v~a.css"])
def test_the_component_grammar_keeps_ordinary_names(X, tmp_path, rel):
    """Control for R2-H01: ordinary names (a space inside, a dot inside, a device-like prefix, ~ without a digit) read."""
    b = _bundle(tmp_path, {rel: b"p { color: red; }"})
    data, why = bl.safe_read(b, rel, 1000)
    assert why is None and data == b"p { color: red; }", why


@pytest.mark.skipif(os.name != "nt", reason="Windows path normalisation (Win32 aliases) exists only on Windows")
def test_windows_aliases_never_bring_the_sentinel_in(X, tmp_path):
    """R2-H01 on Windows: real files canary.key and vault.key hold a synthetic sentinel; read through each alias, the
    sentinel never enters the closure, the staged folder or any diagnostic. The control shows the alias is real here:
    Windows' own open of 'vault.key.' returns the sentinel."""
    b = _alias_bundle(tmp_path, "vault.key.")
    with open(os.path.join(b, "vault.key."), "rb") as fh:
        assert fh.read() == SENTINEL          # the alias is real on this machine
    for i, href in enumerate(["vault.key.", "vault.key%20", "./vault.key::$DATA", "canary.key.", "canary.key%20%20"]):
        bb = _alias_bundle(tmp_path / ("w%d" % i), href)
        clo = check_page.closure(bb, "index.html", _guard(X))
        assert all(SENTINEL not in v for v in clo["files"].values()), href
        stage = tmp_path / ("stage%d" % i)
        stage.mkdir()
        check_page.stage_files(bb, clo["files"], str(stage))
        for dirpath, _dirs, files in os.walk(str(stage)):
            for f in files:
                assert SENTINEL not in open(os.path.join(dirpath, f), "rb").read(), (href, f)
        rep = dl.Report("t")
        check_page.closure_findings(rep, clo)
        assert SENTINEL.decode() not in json.dumps(rep.items), href


# R2-H04, R2-M12: the loopback server serves only the staged inventory, by exact key, and logs the key and digest sent

def _served(stage_files_, inventory, requests):
    """Start the renderer's server on a stage holding stage_files_ (key -> bytes) with this inventory, send each raw
    request path, and return [(status, body)] and the server's log."""
    import http.client
    import threading
    stage = os.path.join(os.path.realpath(str(_served.tmp)), "stage-%d" % len(os.listdir(str(_served.tmp))))
    for rel, data in stage_files_.items():
        p = os.path.join(stage, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(data)
    os.makedirs(stage, exist_ok=True)
    log = []
    srv = check_page.make_server(stage, log, inventory)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out = []
    try:
        for raw in requests:
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            c.putrequest("GET", raw, skip_accept_encoding=True)
            c.endheaders()
            r = c.getresponse()
            out.append((r.status, r.read()))
            c.close()
    finally:
        srv.shutdown()
        srv.server_close()
    return out, log


@pytest.fixture
def served_tmp(tmp_path):
    _served.tmp = tmp_path
    return tmp_path


FONT_A = b"\x00\x01\x00\x00" + b"approved face"
FONT_R = b"\x00\x01\x00\x00" + b"replacement face"


@pytest.mark.parametrize("raw", ["/fonts%2f.%2freplacement.bin", "/fonts/./replacement.bin", "/fonts%2freplacement.bin%2f.",
                                 "/Fonts/replacement.bin", "/FONTS/REPLACEMENT.BIN", "//fonts/replacement.bin",
                                 "/fonts%5creplacement.bin", "/fonts/../fonts/replacement.bin", "/fonts/replacement.bin."],
                         ids=["encoded slash and dot", "dot segment", "trailing encoded dot", "case variant", "upper case",
                              "double slash", "encoded backslash", "dot-dot", "trailing dot"])
def test_server_refuses_a_request_that_is_not_a_canonical_staged_key(served_tmp, raw):
    """R2-H04: a request whose decoded path is not byte-equal to a staged key is 404 and logged as refused; the
    control, the exact key, is 200 and its log entry names the staged key and the SHA-256 of the bytes sent."""
    files = {"fonts/replacement.bin": FONT_R, "fonts/x.ttf": FONT_A}
    inv = {k: dl.sha256(v) for k, v in files.items()}
    res, log = _served(files, inv, [raw, "/fonts/replacement.bin"])
    assert res[0][0] == 404 and FONT_R not in res[0][1], res[0]
    assert log[0]["status"] == 404 and log[0]["key"] is None and log[0]["refused"], log[0]
    assert res[1] == (200, FONT_R), res[1]
    assert log[1] == {"path": "/fonts/replacement.bin", "status": 200, "key": "fonts/replacement.bin", "sha256": dl.sha256(FONT_R)}, log[1]


def test_server_serves_only_the_inventory_with_its_digest(served_tmp):
    """R2-M12: a staged file the job's inventory does not list, and one whose bytes differ from the inventory's SHA-256,
    are never served; the control with its right digest is."""
    files = {"a.css": b"p { color: red; }", "extra.css": b"p { color: blue; }"}
    res, log = _served(files, {"a.css": dl.sha256(b"other bytes")}, ["/a.css", "/extra.css"])
    assert [s for s, _ in res] == [404, 404] and all(e["refused"] for e in log), (res, log)
    assert "differ" in log[0]["refused"] and "inventory" in log[1]["refused"], log
    res, log = _served(files, {"a.css": dl.sha256(files["a.css"])}, ["/a.css"])
    assert res == [(200, files["a.css"])], res


def test_a1_judges_the_served_key_not_the_requested_path(X, tmp_path):
    """R2-H04: A1 reads the bytes of the staged key the server logged; an entry with no key or a digest that differs
    from the staged bytes is INCOMPLETE (its fonts are not judged), never skipped."""
    font = _font_profile(X, tmp_path)
    files = {"fonts/x.ttf": font, "fonts/replacement.bin": FONT_R}
    log = [{"path": "/fonts/./replacement.bin", "status": 200, "key": "fonts/replacement.bin", "sha256": dl.sha256(FONT_R)},
           served("fonts/x.ttf", font)]
    an, rep = analysis(X, access_log=log, files=files)
    an.a1()
    assert items(rep, "A1", "FAIL", "fonts/replacement.bin") and items(rep, "A1", "PASS", "fonts/x.ttf"), rep.items
    for bad in ({"path": "/fonts/r.bin", "status": 200}, {"path": "/fonts/r.bin", "status": 200, "key": "fonts/replacement.bin",
                                                          "sha256": dl.sha256(b"else")}):
        an, rep = analysis(X, access_log=[bad], files=files)
        an.a1()
        assert items(rep, "A1", "INCOMPLETE", "not tied to staged bytes"), rep.items


def test_job_needs_a_valid_inventory(tmp_path):
    """R2-M12: the hidden renderer refuses a job whose inventory is missing or names a key the grammar refuses."""
    base = str(tmp_path / "sds-page-test")
    for inv in (None, {"a.css.": "0" * 64}, {"a.css": "zz"}):
        path, job = _job(base, "browser", inventory=inv)
        assert "inventory" in (check_page.job_problem(job, path) or ""), inv
    path, job = _job(base, "browser", inventory={"a.css": "0" * 64})
    assert check_page.job_problem(job, path) is None


# R2-M01: one trusted root for the whole closure

def _link_folder(target, link):
    """A folder link (junction on Windows, symlink elsewhere); pytest.skip where none can be made."""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(str(target), str(link), target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("folder links cannot be created here")


def test_closure_root_replaced_between_reads_is_refused(X, tmp_path):
    """R2-M01: the bundle root is opened once; when it is replaced by a link to another folder between the first and the
    second read (the test's wrapper of the guard swaps it), the second read refuses and the other folder's bytes never
    enter the closure."""
    b = _bundle(tmp_path / "real", {"index.html": '<img alt="x" src="x.png"><p>t</p>', "x.png": b"real bytes"})
    evil = _bundle(tmp_path / "evil", {"index.html": '<img alt="x" src="x.png"><p>t</p>', "x.png": SENTINEL})
    guard = _guard(X)
    real_read, calls = guard.read, []

    def read(root, rel, limit):
        out = real_read(root, rel, limit)
        if not calls:
            os.rename(b, b + "-moved")
            _link_folder(evil, b)
        calls.append(rel)
        return out
    guard.read = read
    with pytest.raises(check_page.StageError, match="bundle root"):
        check_page.closure(b, "index.html", guard)


def test_closure_refuses_a_link_at_the_root(X, tmp_path):
    """R2-M01: a link at the bundle root itself is refused before any file is read."""
    real = _bundle(tmp_path / "real", {"index.html": "<p>t</p>"})
    link = tmp_path / "link"
    _link_folder(real, link)
    with pytest.raises(check_page.StageError, match="link or not a folder"):
        check_page.closure(str(link), "index.html", _guard(X))


def _swap(b, evil):
    """The bundle path b now names the real folder evil (never a link); the original folder waits at b + '-moved'."""
    os.rename(b, b + "-moved")
    os.rename(evil, b)


def _swap_back(b, evil):
    os.rename(b, evil)
    os.rename(b + "-moved", b)


def test_closure_root_swapped_for_a_real_folder_around_one_read_is_refused(X, tmp_path):
    """W5 (HQ's check of CC-05), R2-M01: the bundle path is pointed at another real folder (not a link) for the second
    read only and back after it. O_NOFOLLOW sees no link, so only the trusted root tells the folders apart: its identity
    check refuses that read, and the other folder's bytes never enter the closure (every platform)."""
    b = _bundle(tmp_path / "real", {"index.html": '<img alt="x" src="x.png"><p>t</p>', "x.png": b"real bytes"})
    evil = _bundle(tmp_path / "evil", {"index.html": '<img alt="x" src="x.png"><p>t</p>', "x.png": SENTINEL})
    guard = _guard(X)
    real_read, calls = guard.read, []

    def read(root, rel, limit):
        swapped = len(calls) == 1
        if swapped:
            _swap(b, evil)
        try:
            out = real_read(root, rel, limit)
        finally:
            if swapped:
                _swap_back(b, evil)
        calls.append((rel, out))
        return out
    guard.read = read
    with pytest.raises(check_page.StageError, match="bundle root"):
        check_page.closure(b, "index.html", guard)
    assert [rel for rel, _ in calls] == ["index.html", "x.png"], calls
    assert not any(data and SENTINEL in data for _, (data, _why) in calls), calls


@pytest.mark.skipif(not bl._posix_walk(), reason="POSIX only: the reads go through the root's directory descriptor")
def test_closure_reads_through_the_root_descriptor_when_the_path_names_another_folder(X, tmp_path, monkeypatch):
    """W5 (HQ's check of CC-05), R2-M01 on POSIX: the bundle path names another real folder only while one file is read,
    after the identity check before the read and before the one after it, so only the root's descriptor tells the
    folders apart: the closure holds the real folder's bytes, never the other folder's."""
    b = _bundle(tmp_path / "real", {"index.html": '<img alt="x" src="x.png"><p>t</p>', "x.png": b"real bytes"})
    evil = _bundle(tmp_path / "evil", {"index.html": '<img alt="x" src="x.png"><p>t</p>', "x.png": SENTINEL})
    real_posix, reads = bl._read_posix, []

    def read_posix(bundle, parts, rel, limit):
        swapped = rel == "x.png"
        if swapped:
            _swap(b, evil)
        try:
            out = real_posix(bundle, parts, rel, limit)
        finally:
            if swapped:
                _swap_back(b, evil)
        reads.append(rel)
        return out
    monkeypatch.setattr(bl, "_read_posix", read_posix)
    res = check_page.closure(b, "index.html", _guard(X))
    assert reads == ["index.html", "x.png"] and res["files"]["x.png"] == b"real bytes", (reads, res["files"].get("x.png"))


# R2-H02: the analysis of the render sequence (recorded inputs; the browser tests are in test_check_page.py)

def test_paint_change_at_a_scroll_position_makes_the_frame_incomplete(X):
    """R2-H02(3): the renderer compares every frame's PAINTS at every scroll position with the first read; a change on
    any element (here a sibling layer, index 2) gives every text run of that frame A6 INCOMPLETE; no change, none."""
    layer = el("f0:2", tag="div", text="", background_color=INK)
    p = el("f0:1", text="Ink text.")
    rd = rnd([body(), p, layer], axe={"passes": [{"id": "color-contrast", "nodes": [{"id": "f0:1", "inside": True}]}],
                                      "violations": [], "incomplete": [], "inapplicable": []})
    rd["frames"][0]["paint_changes"] = [2]
    an, rep = analysis(X, rd)
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", "paint changed"), rep.items
    rd["frames"][0]["paint_changes"] = []
    an, rep = analysis(X, rd)
    an.a6()
    assert not items(rep, "A6", "INCOMPLETE", "paint changed") and not items(rep, "A6", "FAIL"), rep.items
    rd["frames"][0]["paint_changes"] = "all"           # the element list itself changed
    an, rep = analysis(X, rd)
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", "paint changed"), rep.items


def test_paint_diff_names_the_changed_elements():
    assert check_page.paint_diff(["a", "b", "c"], ["a", "b", "c"]) == []
    assert check_page.paint_diff(["a", "b", "c"], ["a", "x", "c"]) == [1]
    assert check_page.paint_diff(["a", "b"], ["a", "b", "c"]) is None


def test_scroll_plan_brings_every_run_into_the_viewport():
    """R2-H02(2): offsets from 0, never past the page's end, each run wholly inside the viewport at one offset; a run
    taller than the viewport or below the height limit fits nowhere (it stays 'not inside the checked viewport')."""
    extents = [(10, 40), (700, 760), (790, 830), (1500, 1540), (2350, 2390), (100, 1000), (25000, 25040)]
    pos = check_page.scroll_plan(extents, 2400, 800, limit=20000)
    assert pos[0] == 0 and pos == sorted(set(pos)) and max(pos) <= 2400 - 800, pos
    for top, bottom in extents[:5]:
        assert any(top >= y and bottom <= y + 800 for y in pos), (top, bottom, pos)
    assert not any(100 >= y and 1000 <= y + 800 for y in pos)
    assert check_page.scroll_plan([(10, 40)], 600, 800) == [0]


def test_merge_axe_takes_each_node_where_its_element_was_inside():
    """R2-H02(2): a node counts from the first position where its element lay wholly inside the viewport; a verdict on
    an element outside the viewport is never taken; an unresolved violation is kept once; a rule applied anywhere is
    never inapplicable, even with no node inside."""
    def res(kind, nodes, inapplicable=()):
        out = {"passes": [], "violations": [], "incomplete": [], "inapplicable": list(inapplicable)}
        out[kind] = [{"id": "color-contrast", "nodes": nodes}]
        return out
    p0 = res("passes", [{"id": "f0:1", "inside": True}, {"id": "f0:2", "inside": False}])
    p1 = res("violations", [{"id": "f0:2", "inside": True}, {"id": "f0:1", "inside": True}, {"id": None, "target": ["#x"], "inside": False}])
    p2 = res("violations", [{"id": None, "target": ["#x"], "inside": False}])
    m = check_page.merge_axe([p0, p1, p2])
    passes = [n["id"] for r in m["passes"] for n in r["nodes"]]
    viols = [n["id"] for r in m["violations"] for n in r["nodes"]]
    assert passes == ["f0:1"] and viols == ["f0:2", None], m
    m = check_page.merge_axe([res("passes", [{"id": "f0:3", "inside": False}], inapplicable=["color-contrast"])])
    assert m["passes"] and not m["passes"][0]["nodes"] and "color-contrast" not in m["inapplicable"], m
    assert check_page.merge_axe([{"error": "boom"}]) == {"error": "boom"}


def test_axe_pass_without_overlap_evidence_is_not_inside(X):
    """R2-H02(2): a text run with no overlap evidence (it was never wholly inside the viewport) is never a pass."""
    p = el("f0:1", text="Far below.")
    rd = rnd([body(), p], axe={"passes": [{"id": "color-contrast", "nodes": [{"id": "f0:1", "inside": True}]}],
                               "violations": [], "incomplete": [], "inapplicable": []}, overlap={"f0:9": ["ok"]})
    an, rep = analysis(X, rd)
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", "not inside the checked viewport"), rep.items


def _two_frames(child_bg):
    """A render with the main frame and a same-bundle child frame f1 whose root has background child_bg; axe passes the
    child's text (its own canvas)."""
    rd = rnd([body(), el("f0:1", tag="iframe", text="")])
    child = [el("f1:0", tag="html", text="", parent=None, background_color=child_bg),
             el("f1:1", tag="body", text="", parent="f1:0"), el("f1:2", text="Ink text in a frame.", parent="f1:1")]
    rd["frames"].append({"key": "f1", "url": "about:srcdoc", "main": False,
                         "data": {"elements": child, "structure": [], "shadow_hosts": [], "media": {}},
                         "axe_contrast": {"passes": [{"id": "color-contrast", "nodes": [{"id": "f1:2", "inside": True}]}],
                                          "violations": [], "incomplete": [], "inapplicable": []},
                         "overlap": {"f1:2": ["ok"] * 5}})
    return rd


def test_child_frame_text_without_an_opaque_backdrop_is_incomplete(X):
    """R2-H02(4): a transparent same-bundle frame over an ink area of the parent page: whatever axe says in that frame,
    its text gets A6 INCOMPLETE; a frame whose own root paints an opaque background keeps axe's verdict (control)."""
    an, rep = analysis(X, _two_frames("rgba(0, 0, 0, 0)"))
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", "backdrop lies outside the frame"), rep.items
    an, rep = analysis(X, _two_frames(PAPER))
    an.a6()
    assert not items(rep, "A6", "INCOMPLETE", "backdrop lies outside the frame"), rep.items


# W1 (HQ's check of CC-05): the evidence is one reader-preference state; every other state is loaded fresh and compared

def test_preference_states_are_every_other_combination():
    """W1, the CEO's choice of 2026-11-11 ("every combination"): the fresh loads cover every combination of reduced
    motion (reduce, no-preference), contrast (no-preference, more, less) and reduced transparency (no-preference,
    reduce) except the evidence state: 11 states, each labelled by the features it changes."""
    import itertools
    want = [dict(zip(("prefers-reduced-motion", "prefers-contrast", "prefers-reduced-transparency"), v))
            for v in itertools.product(("reduce", "no-preference"), ("no-preference", "more", "less"), ("no-preference", "reduce"))]
    evidence = {"prefers-reduced-motion": "reduce", "prefers-contrast": "no-preference", "prefers-reduced-transparency": "no-preference"}
    states = check_page.preference_states()
    assert check_page.EVIDENCE_PREFS == evidence and evidence not in states, states
    assert sorted(map(str, states)) == sorted(str(s) for s in want if s != evidence) and len(states) == 11, states
    labels = [check_page.preference_label(s) for s in states]
    assert len(set(labels)) == 11 and "prefers-reduced-motion: no-preference" in labels and "prefers-contrast: less" in labels, labels
    assert "prefers-reduced-motion: no-preference, prefers-contrast: more" in labels and "prefers-reduced-transparency: reduce" in labels, labels


def test_preference_changes_compare_each_frame_with_the_first_read():
    """W1: a fresh read equal to the evidence page's first read changes no frame; one element's paint, a different
    element list or a different frame list (an extra frame, a frame's URL) changes that frame or every frame."""
    urls, before, bx = ["http://o/index.html", "about:srcdoc"], [["a", "b"], ["c"]], [["0,0,9,9", "1,1,5,5"], ["0,0,3,3"]]
    pc = check_page.preference_changes
    assert pc(urls, before, bx, urls, [["a", "b"], ["c"]], bx) == []
    assert pc(urls, before, bx, urls, [["a", "x"], ["c"]], bx) == ["f0"]
    assert pc(urls, before, bx, urls, [["a", "b"], ["c", "d"]], bx) == ["f1"]
    assert pc(urls, before, bx, urls + ["about:blank"], [["a", "b"], ["c"], ["e"]], bx + [["0,0,1,1"]]) == ["f0", "f1"]
    assert pc(urls, before, bx, urls[:1], [["a", "b"]], bx[:1]) == ["f0", "f1"]
    assert pc(urls, before, bx, [urls[0], "about:blank"], [["a", "b"], ["c"]], bx) == ["f0", "f1"]
    assert pc(urls, before, [None, bx[1]], urls, [["a", "b"], ["c"]], bx) == ["f0"]       # no first boxes: never unchanged


def _passed_run(*frames_changed, confirmed=True, evidence=True, drop=None):
    """A render whose axe pass on ink text over paper would be a PASS, with the fresh loads recorded: the states in
    frames_changed (label -> changed frame keys) painted differently; drop leaves one state out of the record."""
    p = el("f0:1", text="Ink text.")
    rd = rnd([body(), p], axe={"passes": [{"id": "color-contrast", "nodes": [{"id": "f0:1", "inside": True}]}],
                               "violations": [], "incomplete": [], "inapplicable": []})
    rec = prefs_unchanged()
    rec["evidence"]["confirmed"] = evidence
    for s in rec["states"]:
        s["confirmed"] = confirmed
        for label, keys in frames_changed:
            if s["label"] == label:
                s["changed"] = keys
    if drop:
        rec["states"] = [s for s in rec["states"] if s["label"] != drop]
    rd["preferences"] = rec
    return rd


def test_a6_text_painted_differently_for_another_preference_is_incomplete(X):
    """W1 (HQ's probes reduced_motion and contrast_more, as recorded reads): a fresh load in which the frame paints
    differently gives every text run of that frame A6 INCOMPLETE naming the preference, never the axe pass; no change in
    any state keeps the pass (control); a change recorded for another frame leaves this frame's pass (control)."""
    an, rep = analysis(X, _passed_run(("prefers-contrast: more", ["f0"])))
    an.a6()
    hit = items(rep, "A6", "INCOMPLETE", "paints differently for readers with another preference: prefers-contrast: more")
    assert hit and hit[0]["path"].endswith("p.f0-1"), rep.items
    an, rep = analysis(X, _passed_run(("prefers-reduced-motion: no-preference", ["f0"]),
                                      ("prefers-reduced-motion: no-preference, prefers-contrast: more", ["f0"])))
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", "prefers-reduced-motion: no-preference; prefers-reduced-motion: no-preference, prefers-contrast: more"), rep.items
    an, rep = analysis(X, _passed_run())
    an.a6()
    assert not items(rep, "A6", "INCOMPLETE") and not items(rep, "A6", "FAIL"), rep.items
    an, rep = analysis(X, _passed_run(("prefers-contrast: less", ["f1"])))
    an.a6()
    assert not items(rep, "A6", "INCOMPLETE", "p.f0-1"), rep.items


@pytest.mark.parametrize("kw,word", [
    ({"confirmed": False}, "not in effect in its fresh load"),
    ({"evidence": False}, "the evidence page's own preferences were not in effect"),
    ({"drop": "prefers-reduced-transparency: reduce"}, "prefers-reduced-transparency: reduce: not loaded"),
], ids=["state not in effect", "evidence state not in effect", "state not loaded"])
def test_a6_preference_state_without_evidence_is_incomplete(X, kw, word):
    """W1: a state that was not in effect in its fresh load (matchMedia), an evidence page whose own state was not in
    effect, or a state missing from the record gives no evidence: A6 INCOMPLETE, never the axe pass."""
    an, rep = analysis(X, _passed_run(**kw))
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", "not checked for readers with another preference") and items(rep, "A6", "INCOMPLETE", word), rep.items


def test_a6_render_without_a_preference_record_is_incomplete(X):
    """W1: a render that carries no record of the fresh loads gives every text run A6 INCOMPLETE (fail closed)."""
    rd = _passed_run()
    del rd["preferences"]
    an, rep = analysis(X, rd)
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", "the fresh loads were not recorded"), rep.items


# R2-H03: SVG text's fill-opacity; a proved lower bound over a gradient

def _svg_text(**st):
    return el("f0:2", tag="text", text="Nearly invisible SVG text", parent="f0:1", svg=True, **st)


def test_svg_text_fill_opacity_is_composed(X):
    """R2-H03(1) (HQ's probe h03): SVG text in the ink colour with fill-opacity 0.01 on paper composes to about 1.02:1:
    A6 FAIL after axe's pass (axe read color); fill-opacity 1 passes (control)."""
    svg = el("f0:1", tag="svg", text="", svg=True)
    passed = {"passes": [{"id": "color-contrast", "nodes": [{"id": "f0:2", "inside": True}]}], "violations": [], "incomplete": [], "inapplicable": []}
    an, rep = analysis(X, rnd([body(), svg, _svg_text(fill=INK, fill_opacity="0.01")], axe=passed))
    an.a6()
    assert items(rep, "A6", "FAIL", "fallback"), rep.items
    an, rep = analysis(X, rnd([body(), svg, _svg_text(fill=INK, fill_opacity="1")], axe=passed))
    an.a6()
    assert not items(rep, "A6", "FAIL") and not items(rep, "A6", "INCOMPLETE"), rep.items


@pytest.mark.parametrize("st,word", [({"fill": 'url("#g")'}, "fill url"), ({"fill": "context-fill"}, "context-fill"),
                                     ({"fill": INK, "stroke": PAPER, "stroke_width": "2px"}, "visible stroke")],
                         ids=["paint server", "context-fill", "visible stroke"])
def test_svg_text_paint_not_computed_is_incomplete(X, st, word):
    """R2-H03(1): a glyph paint the fallback does not compute gives A6 INCOMPLETE, never a pass."""
    svg = el("f0:1", tag="svg", text="", svg=True)
    an, rep = analysis(X, rnd([body(), svg, _svg_text(**st)]))
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", word), rep.items


TASK_GRADIENT = "linear-gradient(in srgb, rgb(107, 178, 133), rgb(209, 47, 150))"     # true minimum 4.4997:1 near 0.883
ABOVE_GRADIENT = "linear-gradient(in srgb, rgb(107, 178, 133), rgb(202, 50, 168))"    # true minimum 4.50022:1


def test_gradient_below_the_threshold_between_samples_fails(X):
    """R2-H03(2): black text over the task's gradient: the 17 samples all give at least 4.5000345:1, the true minimum
    is 4.4997:1 near position 0.883: A6 FAIL (a real point lies below 4.5)."""
    a, b = dl.parse_colour("rgb(107,178,133)"), dl.parse_colour("rgb(209,47,150)")
    assert min(dl.ratio((0, 0, 0), (s.r, s.g, s.b)) for s in check_page.gradient_samples([a, b])) > 4.5     # the old samples pass
    an, rep = analysis(X, rnd([body(), el("f0:1", color="rgb(0, 0, 0)", background_image=TASK_GRADIENT)]))
    an.a6()
    assert items(rep, "A6", "FAIL", "fallback"), rep.items


def test_gradient_just_above_the_threshold_passes(X):
    """R2-H03(2), control: a gradient whose true minimum is just above 4.5:1 (4.50022:1) gives PASS by the bound."""
    an, rep = analysis(X, rnd([body(), el("f0:1", color="rgb(0, 0, 0)", background_image=ABOVE_GRADIENT)]))
    an.a6()
    assert not items(rep, "A6", "FAIL") and not items(rep, "A6", "INCOMPLETE"), rep.items


def test_seg_min_ratio_bounds_a_dense_scan():
    """R2-H03(2): the bound lies below the real point found, which is no higher than a dense scan's minimum (the scan
    is itself only an upper bound of the true minimum), within the stated margin."""
    black = dl.Colour(0, 0, 0)
    for c0, c1 in (((107, 178, 133), (209, 47, 150)), ((107, 178, 133), (202, 50, 168)), ((255, 0, 0), (0, 160, 0)), ((250, 250, 250), (20, 20, 20))):
        bound, real = check_page.seg_min_ratio(black, c0, c1)
        scan = min(dl.ratio((0, 0, 0), tuple(a + (b - a) * i / 20000 for a, b in zip(c0, c1))) for i in range(20001))
        assert bound <= real <= scan + 1e-12 and real - bound < 1e-6, (c0, c1, bound, real, scan)


def test_translucent_text_over_a_gradient_is_not_proved(X):
    """R2-H03(2): translucent text over a gradient is not proved: INCOMPLETE when no sample lies below the threshold."""
    an, rep = analysis(X, rnd([body(), el("f0:1", color="rgba(0, 0, 0, 0.99)", background_image="linear-gradient(rgb(255, 255, 255), rgb(250, 250, 250))")]))
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", "no lower bound proved"), rep.items


def test_translucent_text_over_a_gradient_fails_on_its_worst_sample(X):
    """W4 (HQ's check of CC-05): translucent text over a gradient is not proved, so the samples decide; one sample (the
    dark end, about 1.4:1) lies below 4.5:1 while the light end gives about 20:1: A6 FAIL on the worst sample, never the
    INCOMPLETE the best sample would give. The test above (every sample above the threshold: INCOMPLETE) is the control."""
    grad = "linear-gradient(rgb(255, 255, 255), rgb(40, 40, 40))"
    an, rep = analysis(X, rnd([body(), el("f0:1", color="rgba(0, 0, 0, 0.99)", background_image=grad)]))
    an.a6()
    fails = items(rep, "A6", "FAIL", "sampled ratio")
    assert fails and not items(rep, "A6", "INCOMPLETE", "no lower bound proved"), rep.items
    assert float(fails[0]["detail"].split("sampled ratio ")[1].split()[0]) < 2.0, fails


# R2-H05: every non-empty paint gives an A2 item

def _rect(fill, eid="f0:2"):
    return el(eid, tag="rect", text="", parent="f0:1", svg=True, fill=fill)


def test_a2_paint_server_fallback_is_judged(X):
    """R2-H05(1) (HQ's probe h05): fill="url(#missing) #9a3412" paints the fallback, X's reserved old-accent: A2 FAIL."""
    svg = el("f0:1", tag="svg", text="", svg=True)
    an, rep = analysis(X, rnd([body(), svg, _rect('url("#missing") rgb(154, 52, 18)')]))
    an.a2()
    assert items(rep, "A2", "FAIL", "reserved"), rep.items


def test_a2_paint_server_without_fallback(X):
    """R2-H05(1): a url() with no fallback naming no gradient of the document gives A2 INCOMPLETE; one naming a gradient
    of the document is judged by its stops (no item of its own; control)."""
    svg = el("f0:1", tag="svg", text="", svg=True)
    rd = rnd([body(), svg, _rect('url("http://127.0.0.1/x#missing")')])
    an, rep = analysis(X, rd)
    an.a2()
    assert items(rep, "A2", "INCOMPLETE", "names no gradient"), rep.items
    rd = rnd([body(), svg, _rect('url("#g")')])
    rd["frames"][0]["data"]["paint_servers"] = ["g"]
    an, rep = analysis(X, rd)
    an.a2()
    assert not items(rep, "A2", "INCOMPLETE") and not items(rep, "A2", "FAIL"), rep.items


@pytest.mark.parametrize("prop,value,status", [
    ("background_color", "color(srgb 0.6 0.2 0.07)", "FAIL"),            # converted exactly: not a token
    ("background_color", "color(srgb 0.6039215686 0.2039215686 0.0705882353)", "FAIL"),
    ("background_color", "color(display-p3 0.6 0.2 0.07)", "INCOMPLETE"),
    ("background_color", "oklch(0.5 0.1 30)", "INCOMPLETE"),
    ("box_shadow", "color(display-p3 0.6 0.2 0.07) 0px 1px 2px 0px", "INCOMPLETE"),
    ("color", "lab(40 30 20)", "INCOMPLETE"),
], ids=["srgb", "srgb fractional", "display-p3", "oklch", "shadow in display-p3", "text in lab"])
def test_a2_colours_the_parser_did_not_read(X, prop, value, status):
    """R2-H05(2): a computed colour in a space the plugin converts exactly is judged (never a token unless equal);
    any other space gives an A2 floor INCOMPLETE, never a silent skip."""
    div = el("f0:1", tag="div", text="Text", **{prop: value})
    an, rep = analysis(X, rnd([body(), div]))
    an.a2()
    got = items(rep, "A2", status)
    assert got and (status == "FAIL" or got[0].get("floor")), rep.items


def test_computed_colour_conversion():
    assert dl.parse_computed_colour("color(srgb 1 0 0)") == dl.Colour(255, 0, 0)
    assert dl.parse_computed_colour("color(srgb 0.2 0.4 0.6 / 0.5)") == dl.Colour(51, 102, 153, dl.Decimal("0.5"))
    assert dl.parse_computed_colour("color(srgb-linear 1 1 1)") == dl.Colour(255, 255, 255)
    assert dl.parse_computed_colour("color(display-p3 1 0 0)") is None and dl.parse_computed_colour("color(srgb 2 0 0)") is None
    assert repr(dl.parse_computed_colour("color(srgb 0.6 0.2 0.07)")).startswith("rgb(153 51 17.85")


# R2-M10: FAIL evidence survives drift and truncation

def test_named_violation_stays_fail_when_the_frame_changed(X):
    """R2-M10: a named axe violation on a tracked text run stays FAIL when the frame's paint changed (as an untracked
    one does); a pass in the same changed frame is INCOMPLETE (control)."""
    viol = {"passes": [], "incomplete": [], "inapplicable": [],
            "violations": [{"id": "color-contrast", "nodes": [{"id": "f0:1", "inside": True, "data": {"contrastRatio": 1.2}}]}]}
    rd = rnd([body(), el("f0:1"), el("f0:2", tag="div", text="")], axe=viol)
    rd["frames"][0]["paint_changes"] = [2]
    an, rep = analysis(X, rd)
    an.a6()
    assert items(rep, "A6", "FAIL", "axe") and not items(rep, "A6", "INCOMPLETE", "paint changed"), rep.items
    passed = {"passes": [{"id": "color-contrast", "nodes": [{"id": "f0:1", "inside": True}]}], "violations": [], "incomplete": [], "inapplicable": []}
    rd = rnd([body(), el("f0:1"), el("f0:2", tag="div", text="")], axe=passed)
    rd["frames"][0]["paint_changes"] = [2]
    an, rep = analysis(X, rd)
    an.a6()
    assert items(rep, "A6", "INCOMPLETE", "paint changed"), rep.items


def test_oversized_result_keeps_bounded_a10_evidence(monkeypatch):
    """R2-M10: an oversized renderer result keeps its A10 evidence, each list cut with its count; the parent reports
    the known A10 failures as FAIL and the rest INCOMPLETE, instead of dropping everything."""
    monkeypatch.setattr(check_page, "MAX_KEPT", 3)
    res = {"origin": "http://127.0.0.1:1", "containment": "browser", "renders": [{"huge": "x" * 1000}],
           "requests": ["http://127.0.0.1:1/a.css"] + ["http://192.0.2.1/x%d" % i for i in range(5)],
           "access_log": [{"path": "/missing.png", "status": 404, "key": None, "sha256": None, "refused": "x"}]}
    b = check_page.bounded_result(res, "over")
    assert "renders" not in b and b["counts"]["requests"] == 6 and len(b["requests"]) == 3, b
    rep = dl.Report("t")
    check_page.report_bounded(rep, b)
    assert items(rep, "A10", "FAIL", "outside the loopback origin") and items(rep, "A10", "FAIL", "not in the staged closure"), rep.items
    assert items(rep, "BUDGET", "INCOMPLETE", "3 of 6 entries kept") and rep.outcome() == "FAIL", rep.items


# R2-M08: A12's evidence: a result per frame, every expected rule, the default tier

A11Y_OK = {"passes": [{"id": "image-alt", "nodes": []}], "violations": [{"id": "region", "impact": "moderate", "nodes": [
    {"target": ["p"], "message": "Some page content is not contained by landmarks"}]}], "incomplete": [], "inapplicable": ["label"]}


def _a11y_render(a11y, rules=("image-alt", "region", "label", "color-contrast")):
    rd = rnd([body(), el("f0:1")], a11y=a11y)
    if rules is not None:
        rd["frames"][0]["axe_rules"] = list(rules)
    return rd


def test_a12_frame_without_a_result_is_incomplete(X):
    """R2-M08: with A12 enabled, a checked frame that carries no axe_a11y result gives A12 INCOMPLETE."""
    an, rep = analysis(X, _a11y_render("none"))
    an.a12()
    assert items(rep, "A12", "INCOMPLETE", "no accessibility result"), rep.items


def test_a12_result_lacking_an_expected_rule_is_incomplete(X):
    """R2-M08: a rule axe-core has for the selected tags that appears in no result list gives A12 INCOMPLETE naming
    it; color-contrast (disabled on purpose) is never expected; the complete result has no such item (control)."""
    an, rep = analysis(X, _a11y_render(A11Y_OK, rules=("image-alt", "region", "label", "color-contrast", "bypass")))
    an.a12()
    assert items(rep, "A12", "INCOMPLETE", "bypass"), rep.items
    an, rep = analysis(X, _a11y_render(A11Y_OK))
    an.a12()
    assert not items(rep, "A12", "INCOMPLETE"), rep.items
    an, rep = analysis(X, _a11y_render(A11Y_OK, rules=None))
    an.a12()
    assert items(rep, "A12", "INCOMPLETE", "not known"), rep.items


def test_a12_default_tier_applies_to_unlisted_rules(X):
    """R2-M08: accessibility.default sets the tier of every rule neither listed nor one of H3's six: with blocking, an
    unlisted rule's violation (region) is FAIL; with the default advisory (X's), WARN (control)."""
    an, rep = analysis(X, _a11y_render(A11Y_OK))
    an.a12()
    assert [i for i in items(rep, "A12", "WARN") if i.get("rule") == "region"], rep.items
    sites.edit(os.path.join(X, "policy.yaml"), "default: advisory", "default: blocking")
    an, rep = analysis(X, _a11y_render(A11Y_OK))
    an.a12()
    assert [i for i in items(rep, "A12", "FAIL") if i.get("rule") == "region"], rep.items


# R2-M09: A13's baseline is bound by its SHA-256

def _valid_snapshot(tmp_path):
    path = tmp_path / "snap.json"
    path.write_text(json.dumps({"rule_version": check_page.A13_RULE_VERSION, "page": "index.html", "page_sha256": "0" * 64,
                                "entries": ["heading|1|A"], "coverage": {"state": "complete", "gaps": []}}))
    r = rnd([body(), el("f0:1")])
    r["frames"][0]["data"]["structure"] = [{"entry": "heading|1|A", "visible": True, "id": "f0:1"}]
    return path, r


@pytest.mark.parametrize("given,word", [(None, "was not given"), ("0" * 64, "is not the --kept-sha256 given")], ids=["absent", "wrong"])
def test_a13_kept_snapshot_needs_its_sha256(X, tmp_path, given, word):
    """R2-M09: --kept is accepted only with the snapshot's SHA-256 (--kept-sha256); without it, or with another, A13 is
    INCOMPLETE and nothing passes (the valid snapshot with its digest passes: test_a13_valid_snapshot_passes)."""
    path, r = _valid_snapshot(tmp_path)
    an, rep = analysis(X, r)
    an.a13(str(path), given)
    assert items(rep, "A13", "INCOMPLETE", word) and not items(rep, "A13", "PASS"), rep.items


def test_kept_sha256_option_is_checked(X, capsys):
    assert check_page.main([os.path.dirname(X), "--page", "index.html", "--site", X, "--kept", "x.json", "--kept-sha256", "abc"]) == 2
    assert "--kept-sha256 must be 64 hex digits" in capsys.readouterr().out


# R2-M11: references by token

def test_url_inside_a_css_string_is_not_a_reference(X, tmp_path):
    """R2-M11: p::after { content: "url(unused.js)" } names no file: nothing is staged for it (a real url() is)."""
    b = _bundle(tmp_path, {"index.html": '<link rel="stylesheet" href="a.css"><p>t</p>',
                           "a.css": 'p::after { content: "url(unused.js)"; } q { quotes: \'url(x.js)\' "a"; } p { background: url("bg.png"); }',
                           "unused.js": "secret()", "x.js": "x()", "bg.png": b"\x89PNG"})
    clo = check_page.closure(b, "index.html", _guard(X))
    assert sorted(clo["files"]) == ["a.css", "bg.png", "index.html"], sorted(clo["files"])


def test_template_content_is_not_followed(X, tmp_path):
    """R2-M11: a <template> holding <img src="x.png"> (and a style and a script) stages nothing and adds no script."""
    b = _bundle(tmp_path, {"index.html": '<template><img alt="t" src="x.png"><style>p { background: url(y.png); }</style>'
                                         '<script>z()</script></template><p>t</p>', "x.png": b"\x89PNG", "y.png": b"\x89PNG"})
    clo = check_page.closure(b, "index.html", _guard(X))
    assert sorted(clo["files"]) == ["index.html"] and not clo["scripts"], (sorted(clo["files"]), clo["scripts"])


def test_svg_file_of_the_closure_is_scanned_for_scripts(X, tmp_path):
    """R2-M11: an <img src="a.svg"> whose SVG holds a <script> (or an event handler) gives the script rule's result."""
    b = _bundle(tmp_path, {"index.html": '<img alt="a" src="a.svg"><img alt="b" src="b.svg"><p>t</p>',
                           "a.svg": '<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>',
                           "b.svg": '<svg xmlns="http://www.w3.org/2000/svg" onload="y()"></svg>'})
    clo = check_page.closure(b, "index.html", _guard(X))
    assert any(s.startswith("a.svg (SVG)") for s in clo["scripts"]) and any(s.startswith("b.svg (SVG)") for s in clo["scripts"]), clo["scripts"]


# R2-M03: outputs never written through an existing name

def test_screenshot_through_a_link_is_refused(tmp_path):
    """R2-M03: a symlink named like a screenshot (w1280-light.png) in --out, pointing to another file of the test's
    folder: that file's bytes stay unchanged and the copy is refused by name."""
    (tmp_path / "stage").mkdir()   # HQ's W2 fix: the capture carries the name it is kept under
    shot = tmp_path / "stage" / "w1280-light.png"
    shot.write_bytes(b"\x89PNG new capture")
    other = tmp_path / "other.txt"
    other.write_bytes(b"other bytes")
    out = tmp_path / "out"
    out.mkdir()
    try:
        os.symlink(str(other), str(out / "w1280-light.png"))
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links cannot be created here")
    rep = dl.Report("t")
    with pytest.raises(dl.InputError, match="link"):
        check_page.keep_screens(rep, {"screenshots": [str(shot)]}, str(out))
    assert other.read_bytes() == b"other bytes"


def test_report_through_a_hard_link_is_refused(X, tmp_path, monkeypatch, capsys):
    """R2-M03: a hard link as the --json destination of check_page.py: refused (ERROR 2), its other name's bytes
    unchanged; the shared writer refuses it for every caller."""
    other = tmp_path / "other.json"
    other.write_bytes(b"other bytes")
    j = tmp_path / "r.json"
    os.link(str(other), str(j))
    monkeypatch.setattr(check_page, "run", lambda args, rep: rep.add("PASS", "A2", "p", "x") and None)
    assert check_page.main([str(tmp_path), "--page", "index.html", "--site", X, "--json", str(j)]) == 2
    assert other.read_bytes() == b"other bytes" and "hard link" in capsys.readouterr().out
    with pytest.raises(dl.InputError, match="hard link"):
        dl.write_output(str(j), b"x")
    assert other.read_bytes() == b"other bytes"


def test_renderer_result_through_a_hard_link_is_refused(tmp_path):
    """R2-M03: the renderer's result.json already present as a hard link: nothing is written through it."""
    base = str(tmp_path / "sds-page-test")
    path, job = _job(base, "os-unchecked")
    other = tmp_path / "other.json"
    other.write_bytes(b"other bytes")
    os.link(str(other), job["result"])
    assert check_page.child_main(path) == 2
    assert other.read_bytes() == b"other bytes"


def test_write_output_replaces_a_plain_file(tmp_path):
    """Control for R2-M03: an existing regular file is replaced by a new file (no temporary file left)."""
    p = tmp_path / "r.json"
    p.write_bytes(b"old")
    dl.write_output(str(p), b"new")
    assert p.read_bytes() == b"new" and sorted(os.listdir(str(tmp_path))) == ["r.json"]


# R2-L02: limits for the whole run

def test_deadline_counts_from_before_staging(X, monkeypatch, capsys):
    """R2-L02: the 120-second deadline starts before staging: staging that uses it up leaves no render (INCOMPLETE,
    no renderer started)."""
    import importlib.util
    sites.issue(X)
    b = sites.bundle(X, "dl", '<!doctype html><html lang="en"><head><title>t</title><link rel="stylesheet" href="x.css"></head><body><p>x</p></body></html>')
    real = importlib.util.find_spec
    monkeypatch.setattr(check_page.importlib.util, "find_spec", lambda n: object() if n == "playwright" else real(n))
    clock = [1000.0]
    monkeypatch.setattr(check_page.time, "monotonic", lambda: clock[0])
    real_stage = check_page.stage_files

    def slow_stage(*a):
        real_stage(*a)
        clock[0] += check_page.RUN_SECONDS + 1          # staging took the whole budget
    monkeypatch.setattr(check_page, "stage_files", slow_stage)
    started, real_popen = [], check_page.subprocess.Popen

    def popen(args, *a, **k):                     # only the renderer is refused; Git's read-only calls run
        if "--_render" in args:
            started.append(args)
            raise AssertionError("the renderer was started")
        return real_popen(args, *a, **k)
    monkeypatch.setattr(check_page.subprocess, "Popen", popen)
    run_as = ["--run-as", "claude"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []   # HQ's W2 fix: root in the cloud
    assert check_page.main([b, "--page", "index.html", "--site", X] + run_as) == 3
    assert not started and "the render exceeded" in capsys.readouterr().out


def test_result_counts_in_the_artefact_budget(tmp_path, monkeypatch):
    """R2-L02: the renderer's result file shares one artefact budget with the captures: a result that fits its own cap
    but not the room the captures left is written bounded (over_budget), never in full; with room it is whole (control)."""
    # child_main sets HOME and removes proxy variables: monkeypatch records them so they are restored afterwards
    monkeypatch.setenv("HOME", os.environ.get("HOME", str(tmp_path)))
    for k in [k for k in os.environ if k.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")]:
        monkeypatch.setenv(k, os.environ[k])
    base = str(tmp_path / "sds-page-test")
    path, job = _job(base, "browser")
    shot = os.path.join(job["out"], "w1280-light.png")
    open(shot, "wb").write(b"\x89PNG" + b"0" * 596)                  # 600 bytes of captures
    monkeypatch.setattr(check_page, "render", lambda j: {"origin": "http://127.0.0.1:1", "screenshots": [shot], "renders": [{"pad": "x" * 500}]})
    monkeypatch.setattr(check_page, "MAX_ARTEFACTS", 1000)
    assert check_page.child_main(path) == 0
    assert "over_budget" in json.load(open(job["result"]))
    monkeypatch.setattr(check_page, "MAX_ARTEFACTS", 100_000)
    assert check_page.child_main(path) == 0
    assert "over_budget" not in json.load(open(job["result"])) and json.load(open(job["result"]))["renders"]


# ------------------------------------------------------------------ HQ's check of CC-06 (TASK-CC-07: X1-X3, the CEO's decision on filters)

def test_report_filters_name_the_element_they_check():
    """X3: report paths are tag paths, so a filter on a class name ('probe') matches no item, and a 'no PASS' assertion
    built on such a filter holds whatever the report says; not_a_pass needs an item of the check on that path and no
    PASS among them. Recorded items of HQ's W1 probe."""
    import test_check_page as tcp
    items = [{"check": "A6", "status": "INCOMPLETE", "path": "html > body > main > div > p",
              "detail": "the page paints differently for readers with another preference: prefers-contrast: more"},
             {"check": "A6", "status": "INFO", "path": "page", "detail": "axe-core 4.14.0 color-contrast in 1 frames"}]
    assert not tcp.has(items, "A6", "INCOMPLETE", path="probe") and tcp.has(items, "A6", "INCOMPLETE", path="div")
    assert tcp.not_a_pass(items, "A6", "div")
    assert not tcp.not_a_pass(items, "A6", "probe")              # names no element: never evidence of 'no PASS'
    passed = items + [{"check": "A6", "status": "PASS", "path": "html > body > main > div > p", "detail": ""}]
    assert not tcp.not_a_pass(passed, "A6", "div")               # a PASS on the element
    assert not tcp.not_a_pass(items, "A1", "div")                # another check's items do not count


X1_REQUIRED = ({"box-shadow", "outline-color", "outline-width", "outline-style", "outline-offset", "background-size",
                "background-position", "background-repeat", "background-clip", "background-origin", "width", "height",
                "border-image-source", "-webkit-box-reflect", "accent-color", "color-scheme", "text-decoration-color",
                "text-decoration-line", "text-decoration-thickness"}
               | {"border-%s-%s" % (s, k) for s in check_page.SIDES for k in ("color", "width", "style")}
               | {"padding-%s" % s for s in check_page.SIDES})


def test_every_comparison_reads_one_paint_list():
    """X1: the one list PAINT_PROPS holds every property the task names; PAINTS reads exactly it; the first read, each
    scroll offset, the read after the evidence and each fresh load all evaluate PAINTS, and only the fresh loads also
    compare BOXES (sticky and fixed boxes move with scrolling)."""
    import inspect
    pj = check_page.pagejs
    assert X1_REQUIRED <= set(pj.PAINT_PROPS), sorted(X1_REQUIRED - set(pj.PAINT_PROPS))
    assert json.dumps(list(pj.PAINT_PROPS)) in pj.PAINTS
    ev, fresh = inspect.getsource(check_page.render_evidence), inspect.getsource(check_page.fresh_state)
    assert ev.count("pagejs.PAINTS") == 3 and fresh.count("pagejs.PAINTS") == 1, (ev.count("pagejs.PAINTS"), fresh.count("pagejs.PAINTS"))
    assert ev.count("pagejs.BOXES") == 1 and fresh.count("pagejs.BOXES") == 1
    assert "boxes" not in inspect.getsource(check_page.paint_diff) and "BOXES" not in inspect.getsource(check_page.Analysis.paint_changed)


def test_paint_list_holds_offsets_and_margins():
    """Y1 (HQ's C2, isolated): the paint list every comparison reads holds an element's offsets and margins, so a layer
    moved by top, right, bottom, left or a margin alone (its size and every other paint unchanged) changes the
    signature; the browser test test_check_page.py::test_a6_layer_moved_only_by_its_offset_in_the_middle_of_the_scroll_range_is_not_a_pass
    shows the same on a page."""
    need = {"top", "right", "bottom", "left", "margin-top", "margin-right", "margin-bottom", "margin-left"}
    assert need <= set(check_page.pagejs.PAINT_PROPS), sorted(need - set(check_page.pagejs.PAINT_PROPS))


class _ScriptedFrame:
    """Y1: a stand-in for a Playwright frame whose page scripts return recorded reads; PAINTS depends on the scroll
    offset (state B at the middle offsets only), as a scroll-driven animation would."""

    def __init__(self, page, url):
        self.page, self.url, self.parent_frame = page, url, None

    def evaluate(self, script, arg=None):
        pj, y = check_page.pagejs, self.page.y
        texts = {2: 100, 3: 1500, 4: 2900}                      # element index: the top of its text (page coordinates)
        if script is pj.PAINTS:
            layer = "scale:0" if 1000 <= y <= 2000 else "scale:1"     # the layer f0:5 hidden in the middle only
            return ["html", "body", "p", "p", "p", layer]
        if script is pj.BOXES:
            return ["0,0,1280,3200"] * 6
        if script is pj.COLLECT:
            els = [{"id": "f0:%d" % i, "parent": "f0:%d" % (i - 1 if i < 2 else 1) if i else None, "visible": True,
                    "text": "Run %d." % i if i in texts else "", "text_rects": [[16, texts[i], 300, 20]] if i in texts else []}
                   for i in range(6)]
            return {"height": 3200, "elements": els}
        if script is pj.INSIDE:
            tops = {"f0:%d" % i: t for i, t in texts.items()}
            return [i for i in arg["ids"] if y <= tops[i] and tops[i] + 20 <= y + 800]
        if script is pj.OVERLAP:
            return {i: ["ok"] for i in arg["ids"]}
        if script is pj.UNSEEN:
            return {"boxes": {}, "runs": {i: [] for i in arg["ids"]}}
        if script is pj.AXE_RUN:
            return {"passes": [], "violations": [], "incomplete": [], "inapplicable": []}
        return None                                             # the axe source


class _ScriptedPage:
    def __init__(self, origin):
        self.y = 0
        self.main_frame = _ScriptedFrame(self, origin + "/index.html")
        self.frames = [self.main_frame]

    def evaluate(self, script, arg=None):
        if script is check_page.pagejs.SCROLL:
            self.y = arg
            return [arg, arg]
        return "ready"                                          # FONTS_READY

    def screenshot(self):
        return b"\x89PNG scripted"


class _ScriptedContext:
    def new_cdp_session(self, page):
        class Cdp:
            def send(self, method, params=None):
                if method == "DOM.getDocument":
                    return {"root": {"nodeType": 9, "children": []}}
                return {"fonts": []}

            def detach(self):
                return None
        return Cdp()


def test_render_compares_paints_at_every_scroll_position(tmp_path):
    """Y1 (R2-H02's per-scroll comparison, isolated): the renderer, driven through scripted page reads with no browser,
    scrolls to the offsets 0, 1500 and 2400; the layer f0:5 paints differently only at 1500 (a middle offset), so the
    first read, the read after every evidence (at 2400) and the fresh loads (offset 0) all see state A. The comparison
    at each scroll position alone records f0:5 as changed; A6's paint_changed then names it."""
    origin = "http://127.0.0.1:1"
    page = _ScriptedPage(origin)
    job = {"selectors": {}, "tags": None, "out": str(tmp_path)}
    result, shots = {"screenshots": [], "truncated": []}, {"bytes": 0}
    rd = check_page.render_evidence(_ScriptedContext(), page, origin, job, ("w1280-light", 1280, 800, "light"), "", result, shots)
    fd = rd["frames"][0]
    assert rd["positions"] == [0, 1500, 2400], rd["positions"]
    assert fd["paints_before"] == fd["paints_after"]               # the read after the evidence sees nothing (control)
    assert fd["paint_changes"] == [5], fd["paint_changes"]
    assert "f0:5" in check_page.Analysis.paint_changed(check_page.Analysis, check_page.Render(rd))


def _sig(**changed):
    """A recorded PAINTS read of one element: the PAINT_PROPS values in their order, 'none' unless changed."""
    values = dict.fromkeys(check_page.pagejs.PAINT_PROPS, "none")
    values.update({k.replace("_", "-"): v for k, v in changed.items()})
    return "|".join(values[p] for p in check_page.pagejs.PAINT_PROPS)


@pytest.mark.parametrize("prop,value", [
    ("box-shadow", "rgb(26, 26, 46) 0px 0px 0px 2000px inset"),      # HQ's contrast_shadow
    ("border-top-width", "40px"), ("border-left-color", "rgb(26, 26, 46)"), ("outline-width", "2000px"),
    ("outline-offset", "-2000px"), ("background-size", "100% 100%"), ("padding-top", "40px"), ("height", "400px"),
    ("-webkit-box-reflect", "below 0px"), ("text-decoration-thickness", "40px"),
])
def test_fresh_load_differing_in_one_property_of_the_new_list_alone_changes_the_frame(prop, value):
    """X1: recorded reads of a fresh load that differ from the evidence page's first read only in one property the list
    lacked before change the frame; equal reads change nothing (control)."""
    urls, boxes = ["http://o/index.html"], [["0,0,1280,800", "16,16,600,40"]]
    before = [[_sig(), _sig()]]
    assert check_page.preference_changes(urls, before, boxes, urls, [[_sig(), _sig()]], boxes) == []
    assert check_page.preference_changes(urls, before, boxes, urls, [[_sig(), _sig(**{prop: value})]], boxes) == ["f0"], prop


def test_fresh_load_differing_in_one_border_box_alone_changes_the_frame():
    """X1: a fresh load (offset 0) whose paints equal the first read but where one element's border box moved or grew
    changes the frame (a box is compared only between loads at offset 0); equal boxes change nothing (control)."""
    urls, before = ["http://o/index.html"], [[_sig(), _sig()]]
    boxes = [["0,0,1280,800", "16,16,600,40"]]
    assert check_page.preference_changes(urls, before, boxes, urls, [[_sig(), _sig()]], [["0,0,1280,800", "16,16,600,40"]]) == []
    assert check_page.preference_changes(urls, before, boxes, urls, [[_sig(), _sig()]], [["0,0,1280,800", "16,56,600,40"]]) == ["f0"]
    assert check_page.preference_changes(urls, before, boxes, urls, [[_sig(), _sig()]], [["0,0,1280,800", "16,16,600,440"]]) == ["f0"]


# X2: paints hit testing never sees, from recorded rectangles (viewport coordinates where the run was evidenced)

NO_RADII = [(0.0, 0.0)] * 4
INK_INSET = "rgba(26, 26, 46, 0.08) 0px 0px 0px 2000px inset"


def _layer(value):
    return check_page.shadow_layers(value)[0]


def test_shadow_layers_are_read_or_refused():
    """X2: Chromium's computed box-shadow (colour first, four lengths, inset last) is read layer by layer; none is no
    layer; a value that cannot be read is None (its reach is then not computed, never taken as no shadow)."""
    sl = check_page.shadow_layers
    assert sl("none") == [] and sl("") == []
    layers = sl(", ".join([INK_INSET] * 60))
    assert len(layers) == 60 and layers[0][:5] == (True, 0.0, 0.0, 0.0, 2000.0) and float(layers[0][5].a) == 0.08
    assert sl("rgb(0, 0, 0) 0px 4px 12px -2px")[0][:5] == (False, 0.0, 4.0, 12.0, -2.0)
    assert sl("color(srgb 0.1 0.1 0.2) 1px 1px")[0][:5] == (False, 1.0, 1.0, 0.0, 0.0)
    for bad in ("0px 4px 12px", "rgb(0, 0, 0) 1em 0px", "rgb(0, 0, 0) 0px 0px -3px 0px", "rgb(0, 0, 0) 0px", "rgb(0, 0, 0) 0px 0px 0px 0px 0px"):
        assert sl(bad) is None, bad


def test_shadow_reach_inset_of_an_ancestor_and_outer_reaching_or_not():
    """X2 geometry: an inset shadow of an ancestor reaches the run (HQ's shadow_stack and shadow_always); one of another
    element reaches it when its padding box meets the run. An earlier sibling's outer shadow, 20 px above the run,
    reaches it by its spread or its blur alone; the same shadows 200 px away do not. A transparent layer, or one with no
    offset, blur or spread, paints nothing."""
    run = [[40, 60, 300, 20]]
    parent = [16, 16, 640, 200]
    inset = _layer(INK_INSET)
    assert check_page.shadow_reaches(run, parent, parent, NO_RADII, inset, True, False)
    assert check_page.shadow_reaches(run, [0, 50, 100, 40], [0, 50, 100, 40], NO_RADII, inset, False, False)
    assert not check_page.shadow_reaches(run, [0, 300, 100, 40], [0, 300, 100, 40], NO_RADII, inset, False, False)
    sib, far = [40, 30, 300, 10], [40, 300, 300, 10]
    for value in ("rgb(26, 26, 46) 0px 0px 0px 25px", "rgb(26, 26, 46) 0px 0px 16px 0px"):     # spread alone, blur alone
        assert check_page.shadow_reaches(run, sib, sib, NO_RADII, _layer(value), False, False), value
        assert not check_page.shadow_reaches(run, far, far, NO_RADII, _layer(value), False, False), value
    assert check_page.shadow_reaches(run, sib, sib, NO_RADII, _layer("rgb(26, 26, 46) 0px 25px 0px 0px"), False, False)   # by its offset
    assert not check_page.shadow_reaches(run, parent, parent, NO_RADII, _layer("rgba(0, 0, 0, 0) 0px 0px 0px 2000px inset"), True, False)
    assert not check_page.shadow_reaches(run, sib, sib, NO_RADII, _layer("rgb(0, 0, 0) 0px 0px 0px 0px"), False, False)
    assert not check_page.shadow_reaches(run, sib, sib, NO_RADII, _layer("rgb(0, 0, 0) 0px 0px 0px -40px"), False, False)


def test_shadow_reach_own_outer_shadow_never_paints_inside_its_box():
    """X2 geometry: a card's own outer shadow never paints inside the card, so the card's text is not reached; text that
    overflows the card, text in a rounded corner beyond the arc, or a box laid out in line fragments is reached. Used
    radii scale down as CSS does (a pill's 9999 px becomes half its height)."""
    card = [16, 16, 400, 120]
    own = _layer("rgba(26, 26, 46, 0.08) 0px 4px 12px 0px")
    radii = check_page.used_radii(card, ["12px"] * 4)
    text = [[40, 40, 300, 20]]
    assert not check_page.shadow_reaches(text, card, card, radii, own, True, False)
    assert check_page.shadow_reaches([[40, 130, 300, 20]], card, card, radii, own, True, False)      # overflows the card
    assert check_page.shadow_reaches([[17, 17, 20, 10]], card, card, radii, own, True, False)        # in the rounded corner
    assert check_page.shadow_reaches(text, card, card, radii, own, True, True)                       # line fragments
    assert check_page.shadow_reaches(text, card, card, None, own, True, False)                       # unreadable radii
    assert check_page.used_radii([0, 0, 120, 40], ["9999px"] * 4) == [(20.0, 20.0)] * 4
    assert check_page.used_radii([0, 0, 200, 100], ["50%", "10px 20px", "0px", "0"]) == [(100.0, 50.0), (10.0, 20.0), (0.0, 0.0), (0.0, 0.0)]
    assert check_page.used_radii(card, ["12em"] * 4) is None


def test_outline_and_border_image_reach():
    """X2 geometry: a sibling's outline 80 px wide at offset -20 px reaches 60 px beyond its box, over the run 20 px below;
    a thin outline does not. An ancestor's outline drawn inside its box at a large negative offset crosses the text; one
    around the box does not. A border image paints over its border image area (the box grown by its outset)."""
    run, strip, box = [[40, 60, 300, 20]], [40, 30, 300, 10], [16, 16, 640, 200]
    assert check_page.outline_reaches(run, strip, 80.0, -20.0, NO_RADII, False)
    assert not check_page.outline_reaches(run, strip, 4.0, 0.0, NO_RADII, False)
    assert check_page.outline_reaches(run, box, 4.0, -40.0, NO_RADII, False)
    assert not check_page.outline_reaches(run, box, 4.0, 0.0, NO_RADII, False)
    borders = [10.0, 10.0, 10.0, 10.0]
    assert check_page.border_image_reaches(run, strip, "30px", borders) and check_page.border_image_reaches(run, strip, "3", borders)
    assert not check_page.border_image_reaches(run, strip, "0", borders)
    assert check_page.border_image_reaches(run, box, "0", borders)                 # an ancestor's image area holds the run
    assert check_page.border_image_reaches(run, strip, "auto", borders) is None


def _x2_run(ancestor=False, box=(40, 30, 300, 10), measured=True, **st):
    """A render whose axe pass on ink text over paper would be a PASS, with the geometry UNSEEN recorded where the run
    f0:2 was evidenced (its text at 40, 60, 300 x 20): the painter is its parent f0:1 (ancestor) or an earlier sibling
    f0:3, styled by st and measured at box; measured=False leaves its box out."""
    parent = el("f0:1", tag="div", text="", **(st if ancestor else {}))
    p = el("f0:2", text="Ink text.", parent="f0:1")
    sib = el("f0:3", tag="div", text="", **({} if ancestor else st))
    rd = rnd([body(), parent, p, sib], axe={"passes": [{"id": "color-contrast", "nodes": [{"id": "f0:2", "inside": True}]}],
                                           "violations": [], "incomplete": [], "inapplicable": []})
    painter = "f0:1" if ancestor else "f0:3"
    rd["frames"][0]["geometry"] = [{"boxes": {painter: list(box)} if measured else {}, "runs": {"f0:2": [[40, 60, 300, 20]]}}]
    return rd


@pytest.mark.parametrize("kw,word,where", [
    # HQ's shadow_stack and shadow_always (solid inset bands of an ancestor) are composed since TASK-CC-08 (U2):
    # test_a6_solid_shadow_bands_are_composed_into_the_backdrop
    ({"box_shadow": "rgba(26, 26, 46, 0.08) 0px 0px 0px 25px"}, "a shadow paints under the text", "div.f0-3"),
    ({"box": (0, 50, 400, 40), "box_shadow": "rgb(26, 26, 46) 0px 0px 0px 25px inset"}, "a shadow paints under the text", "div.f0-3"),
    ({"ancestor": True, "box": (16, 16, 640, 200), "box_shadow": "rgba(26, 26, 46, 0.08) 0px 0px 4px 0px inset"},
     "a shadow paints under the text", "div.f0-1"),
    ({"outline_style": "solid", "outline_width": "80px", "outline_offset": "-20px"}, "an outline is drawn over the text", "div.f0-3"),
    ({"border_image_source": "linear-gradient(rgb(26, 26, 46), rgb(26, 26, 46))", "border_image_outset": "30px"},
     "a border image paints under the text", "div.f0-3"),
    ({"box_shadow": "rgba(26, 26, 46, 0.08) 0px 0px 0px 25px", "measured": False}, "was not measured where the text was checked", "div.f0-3"),
], ids=["sibling outer spread", "sibling solid inset band", "ancestor blurred inset band", "sibling outline",
        "sibling border image", "not measured"])
def test_a6_paint_hit_testing_never_sees_under_the_text_is_incomplete(X, kw, word, where):
    """X2: an axe pass on text that such a paint reaches is never taken: A6 INCOMPLETE naming the painter. Since U2 a
    solid inset band of the run's element or an ancestor is composed instead; a non-ancestor's solid inset band (its
    paint order against the text's backdrop is not computed) and a blurred band of an ancestor stay INCOMPLETE."""
    an, rep = analysis(X, _x2_run(**kw))
    an.a6()
    hit = items(rep, "A6", "INCOMPLETE", word)
    assert hit and hit[0]["path"].endswith("p.f0-2") and where in hit[0]["detail"], rep.items


@pytest.mark.parametrize("kw", [
    {"ancestor": True, "box": (16, 16, 400, 120), "box_shadow": "rgba(26, 26, 46, 0.08) 0px 4px 12px 0px",
     "border_top_left_radius": "12px", "border_top_right_radius": "12px", "border_bottom_right_radius": "12px",
     "border_bottom_left_radius": "12px"},
    {"box": (40, 300, 300, 10), "box_shadow": "rgba(26, 26, 46, 0.08) 0px 0px 0px 25px"},
    {"box_shadow": "rgba(0, 0, 0, 0) 0px 0px 0px 2000px"},
    {"box_shadow": "rgb(26, 26, 46) 0px 0px 0px 25px", "visibility": "hidden"},
    {"filter": "brightness(0.5)"},
    {},
    {"box": (40, 600, 100, 100), "filter": "blur(30px)"},
    {"box": (40, 600, 100, 100), "filter": "drop-shadow(rgb(0, 0, 0) 2px 2px 4px)"},
], ids=["card's own outer shadow", "shadow far away", "transparent shadow", "hidden box", "non-ancestor brightness", "nothing",
        "blur far away", "drop-shadow far away"])
def test_a6_paint_hit_testing_never_sees_away_from_the_text_keeps_the_pass(X, kw):
    """X2 controls: a card's own outer shadow (its text inside), a shadow that does not reach, a transparent one, the
    shadow of a hidden box, a non-ancestor's colour filter and no such paint at all keep the axe pass."""
    an, rep = analysis(X, _x2_run(**kw))
    an.a6()
    assert not items(rep, "A6", "INCOMPLETE") and not items(rep, "A6", "FAIL"), rep.items


@pytest.mark.parametrize("st,word", [
    ({"filter": "blur(40px)", "child": True}, "a filter paints beyond the box of"),
    ({"filter": "drop-shadow(rgb(0, 0, 0) 2px 2px 4px)", "own_text": True}, "a filter paints beyond the box of"),
    ({"filter": "blur(4px)", "svg": True}, "SVG"),
    ({"filter": "blur(4px)", "box_shadow": "rgb(0, 0, 0) 0px 0px 0px 2px"}, "its own box-shadow, outline or border image"),
    ({"filter": "blur(4px)", "rotate": "5deg"}, "a transformed element"),
    ({"filter": 'url("#wobble")'}, "could not be read"),
    ({"filter": "blur(4px)", "pseudo_after": True}, "::after, whose box is not measured"),
    ({"filter": "blur(4px)", "display": "list-item"}, "a list item, whose ::marker"),
    ({"-webkit-box-reflect": "below 0px"}, "a reflection (-webkit-box-reflect) of"),
    ({"box_shadow": "rgb(0, 0, 0) 0px 0px 0px calc(10px)"}, "could not be read"),
    ({"box_shadow": "rgb(26, 26, 46) 0px 0px 0px 25px", "transform": "matrix(1, 0, 0, 1, 10, 0)"}, "a transformed element"),
    ({"outline_style": "solid", "outline_width": "4px", "rotate": "5deg"}, "a transformed element"),
    ({"pseudo": True}, "::before: its reach is not measured"),
], ids=["blur over a child", "drop-shadow over its own text", "blur of SVG", "blur over its own shadow", "rotated blur",
        "unreadable filter", "blur over its ::after", "blur of a list item", "reflection", "unreadable shadow",
        "transformed shadow", "rotated outline", "pseudo-element shadow"])
def test_a6_paint_whose_reach_is_not_computed_is_incomplete(X, st, word):
    """X2, U1: a paint whose reach is not computed gives every text run of its frame A6 INCOMPLETE, never the axe pass:
    a blur or drop-shadow filter on an element whose border box does not bound what it filters (child elements, its own
    text, SVG, its own shadow, a rendered ::after) or that is transformed, a filter that cannot be read (an SVG filter
    reference), a reflection, an unreadable shadow, a shadow or outline of a transformed element, a shadow of a
    ::before. The painter is far from the text and was measured."""
    st = dict(st)
    pseudo, child, own_text = st.pop("pseudo", False), st.pop("child", False), st.pop("own_text", False)
    svg, pseudo_after = st.pop("svg", False), st.pop("pseudo_after", False)
    rd = _x2_run(box=(40, 600, 300, 10), **st)
    els = rd["frames"][0]["data"]["elements"]
    if pseudo:
        els[3]["pseudo"] = {"::before": style(content='""', box_shadow="rgb(26, 26, 46) 0px 0px 0px 40px")}
    if pseudo_after:
        els[3]["pseudo"] = {"::after": style(content='""')}
    if child:
        els.append(el("f0:4", tag="span", text="", parent="f0:3"))
    if own_text:
        els[3].update(text="Decor.", text_rects=[[40, 600, 40, 10]])
    if svg:
        els[3].update(svg=True, tag="circle")
    an, rep = analysis(X, rd)
    an.a6()
    hit = items(rep, "A6", "INCOMPLETE", word)
    assert hit and hit[0]["path"].endswith("p.f0-2"), rep.items


# U1: a blur() or drop-shadow() filter reaches only the runs that meet what it can paint (recorded rectangles)

def test_filter_functions_are_read_or_refused():
    """U1: a computed filter is read function by function (blur, drop-shadow, colour functions); a value that cannot be
    read (an SVG filter reference, a length that is not px, a negative blur, a short drop-shadow, an unknown function,
    a trailing word) is None, never taken as no filter."""
    fo = check_page.filter_ops
    assert fo("none") == [] and fo("") == []
    assert fo("blur(30px)") == [("blur", 30.0)] and fo("blur()") == [("blur", 0.0)]
    assert fo("drop-shadow(rgb(0, 0, 0) 2px -4px 6px)") == [("drop", 2.0, -4.0, 6.0)]
    assert fo("drop-shadow(rgba(26, 26, 46, 0.08) 0px 2px)") == [("drop", 0.0, 2.0, 0.0)]
    assert fo("brightness(0.5) blur(2px) grayscale(1)") == [("colour",), ("blur", 2.0), ("colour",)]
    for bad in ('url("#f")', "blur(1em)", "blur(-2px)", "drop-shadow(rgb(0, 0, 0) 2px)", "wobble(1)", "blur(2px) junk"):
        assert fo(bad) is None, bad


def test_filter_reach_grows_three_deviations_and_moves_with_a_drop_shadow():
    """U1 geometry: blur(r) reaches 3 r beyond the box (r is the standard deviation), plus one pixel; drop-shadow(dx dy
    b) adds the box moved by its offset and grown by 1.5 b; functions apply in order."""
    box = [40, 130, 100, 100]
    assert check_page.filter_reach(box, [("blur", 30.0)]) == [-51.0, 39.0, 282.0, 282.0]
    assert check_page.filter_reach(box, [("drop", 0.0, -330.0, 4.0)]) == [33.0, -207.0, 114.0, 438.0]
    assert check_page.filter_reach(box, [("colour",)]) == [39.0, 129.0, 102.0, 102.0]
    assert check_page.filter_reach(box, [("blur", 10.0), ("drop", 50.0, 0.0, 0.0)]) == [9.0, 99.0, 212.0, 162.0]


@pytest.mark.parametrize("top,filt,reached", [
    (130, "blur(30px)", True),         # reach 91 px: its top at 39, above the run's bottom (80)
    (180, "blur(30px)", False),        # its top at 89: below the run
    (171, "blur(30px)", False),        # its top exactly at the run's bottom: edges that touch do not overlap
    (170.5, "blur(30px)", True),       # half a pixel nearer: reached
    (400, "drop-shadow(rgb(0, 0, 0) 0px -330px 4px)", True),     # the shadow moved up over the run
    (400, "drop-shadow(rgb(0, 0, 0) 0px 0px 4px)", False),       # the same without its offset
], ids=["inside", "outside", "on the edge", "half a pixel inside", "drop-shadow offset reaching", "drop-shadow not moved"])
def test_a6_blur_or_drop_shadow_counts_only_near_itself(X, top, filt, reached):
    """U1 (TASK-CC-08; HQ's honest_blob): a decorative element with a blur or drop-shadow filter (no children, no text,
    measured where the run was evidenced) gives A6 INCOMPLETE only to a run whose rectangles (40, 60, 300 x 20) meet
    what the filter can paint: its 100 px box grown by 3 x blur, or moved by the drop shadow's offset and grown by 1.5 x
    its blur, plus one pixel. A run beyond that keeps axe's pass."""
    an, rep = analysis(X, _x2_run(box=(40, top, 100, 100), filter=filt))
    an.a6()
    hit = items(rep, "A6", "INCOMPLETE")
    if reached:
        assert hit and hit[0]["path"].endswith("p.f0-2") and "a filter of" in hit[0]["detail"] and "div.f0-3" in hit[0]["detail"], rep.items
    else:
        assert not hit and not items(rep, "A6", "FAIL"), rep.items


def test_a6_animated_blur_is_never_taken_as_still(X):
    """U1: a decorative blurred element far from the text but animated (UNSEEN found a running or pending animation,
    a delayed one included: it may paint a drop shadow over the text after the check) gives the text A6 INCOMPLETE;
    the same element not animated keeps the pass (control)."""
    rd = _x2_run(box=(40, 600, 100, 100), filter="blur(30px)")
    rd["frames"][0]["geometry"][0]["animated"] = ["f0:3"]
    an, rep = analysis(X, rd)
    an.a6()
    hit = items(rep, "A6", "INCOMPLETE", "is animated")
    assert hit and hit[0]["path"].endswith("p.f0-2"), rep.items
    an, rep = analysis(X, _x2_run(box=(40, 600, 100, 100), filter="blur(30px)"))
    an.a6()
    assert not items(rep, "A6", "INCOMPLETE"), rep.items


# U2: a solid shadow band (no blur) of the run's element or an ancestor is composed into the backdrop exactly

ACCENT = "rgb(194, 65, 12)"
BAND = "rgba(26, 26, 46, 0.08) 0px -1px 0px 0px inset"       # HQ's honest_link_underline: a link's own underline band
AXE_PASS_F02 = {"passes": [{"id": "color-contrast", "nodes": [{"id": "f0:2", "inside": True}]}], "violations": [], "incomplete": [],
                "inapplicable": []}


def _band_run(own=None, parent=None, color=INK, parent_opacity=None, own_z=None, animated=()):
    """A render whose axe pass on the run f0:2 (its text colour color, at 40, 60, 300 x 20, inside its parent f0:1 at
    16, 16, 640 x 200 on the paper body) would be a PASS; own and parent are the box-shadow values of the run's element
    and of its parent, both measured where the run was evidenced; parent_opacity the parent's own opacity; own_z the
    run's element's z-index; animated the painters UNSEEN found animated."""
    par = el("f0:1", tag="div", text="", **({"box_shadow": parent} if parent else {}))
    if parent_opacity is not None:
        par["style"]["opacity"] = parent_opacity
    p = el("f0:2", text="Text over a solid band.", parent="f0:1", color=color, **({"box_shadow": own} if own else {}))
    if own_z is not None:
        p["style"].update({"z-index": own_z, "position": "relative"})
    rd = rnd([body(), par, p], axe=AXE_PASS_F02)
    rd["frames"][0]["geometry"] = [{"boxes": {"f0:1": [16, 16, 640, 200], "f0:2": [40, 60, 300, 20]}, "runs": {"f0:2": [[40, 60, 300, 20]]},
                                    "animated": list(animated)}]
    return rd


def _a6(X, rd):
    an, rep = analysis(X, rd)
    an.a6()
    return [i for i in rep.items if i["check"] == "A6" and i["status"] != "INFO"], items(rep, "A6", "INFO")[0]["detail"]


@pytest.mark.parametrize("kw,ratio", [
    ({"own": BAND, "color": ACCENT}, "ratio 4.3420"),                                  # the CEO's choice (2026-11-12)
    ({"parent": ", ".join([INK_INSET] * 60)}, "ratio 1.0164"),                          # HQ's shadow_stack
    ({"parent": "rgb(26, 26, 46) 0px 0px 0px 2000px inset"}, "ratio 1.0000"),           # HQ's shadow_always
    ({"own": "rgb(26, 26, 46) 0px -8px 0px 0px inset"}, "ratio 1.0000"),                # an ink band under ink text
    ({"own": "rgb(255, 253, 247) 0px 0px 0px 2000px inset, rgba(0, 0, 0, 0.9) 0px 0px 0px 2000px inset"}, None),
    ({"parent": "rgba(0, 0, 0, 0.9) 0px 0px 0px 2000px inset", "own": "rgb(255, 253, 247) 0px -4px 0px 0px inset"}, "ratio 1.0"),
], ids=["accent link over its own underline", "shadow_stack", "shadow_always", "ink band under ink text",
        "paper band painted over a dark one (paint order)", "an ancestor's band where the run's own band does not cover it"])
def test_a6_solid_shadow_bands_are_composed_into_the_backdrop(X, kw, ratio):
    """U2 (TASK-CC-08): a solid inset band of the run's element or of an ancestor is composed exactly into the backdrop,
    each layer with its alpha, above the backgrounds of the element that paints it and in paint order (a box-shadow's
    first listed layer on top). The run passes only when its text meets the threshold over the plain backdrop and over
    every combination of the bands that reach it; it fails when one is below. HQ's link: accent text (5.09 on paper)
    over its own 8 % ink underline band gives 4.34: FAIL, by the CEO's choice «Считать точно (Recommended)». HQ's
    shadow_stack (60 layers of 8 % ink) and shadow_always: FAIL, never PASS. A paper band listed first is painted over
    a dark one: PASS. An ancestor's near-black band with the run's own paper band covering only its bottom 4 px: the
    rest of the run lies over the ancestor's band alone: FAIL (comparing only the plain backdrop and all bands together
    would pass it)."""
    found, summary = _a6(X, _band_run(**kw))
    if ratio is None:
        assert found == [] and "fallback passes 1," in summary, (found, summary)
        return
    assert [i["status"] for i in found] == ["FAIL"] and found[0]["path"].endswith("p.f0-2"), found
    assert ratio in found[0]["detail"] and "solid shadow band" in found[0]["detail"], found


@pytest.mark.parametrize("kw", [
    {"own": BAND},                                                     # the same underline under ink text
    {"parent": INK_INSET},                                             # one layer of the approved card shadow
    {"own": BAND, "parent": "rgba(26, 26, 46, 0.08) 0px 2px 0px 0px inset"},
], ids=["ink text over its own underline", "one translucent ancestor band", "two bands"])
def test_a6_solid_shadow_bands_that_keep_the_contrast_pass(X, kw):
    """U2 controls: ink text over an 8 % ink band of its own, of an ancestor, or both (every combination composed) keeps
    the contrast: no A6 item but the summary, which counts one fallback pass."""
    found, summary = _a6(X, _band_run(**kw))
    assert found == [] and "fallback passes 1," in summary, (found, summary)


@pytest.mark.parametrize("kw,word", [
    ({"parent": ", ".join("rgba(26, 26, 46, 0.08) 0px -%dpx 0px 0px inset" % k for k in range(1, 6))}, "more than 4"),
    ({"parent": INK_INSET, "parent_opacity": "0.5"}, "group compositing"),
    ({"own": "rgba(26, 26, 46, 0.08) 0px -1px 1px 0px inset"}, "a shadow paints under the text"),
    ({"parent": "rgb(26, 26, 46) 0px 0px 0px 2000px inset", "own_z": "-1"}, "negative z-index"),
    ({"parent": INK_INSET, "own_z": "2"}, None),
    ({"own": BAND, "animated": ["f0:2"]}, "animated"),
], ids=["five band shapes", "a faded painter of a band", "a blurred own band", "text in a negative layer beneath the band",
        "text in a positive layer (control)", "an animated band"])
def test_a6_solid_shadow_bands_not_composed_are_incomplete(X, kw, word):
    """U2 limits: more than four bands of different shapes, a band painted inside a faded group (group opacity is not
    computed), a band with blur, an ancestor's band over text in a stacking layer with a negative z-index (painted
    beneath the band, where the composition would put it above), or the band of an animated painter (it may paint
    otherwise after the check, as a delayed animation does), are not composed: A6 INCOMPLETE, never PASS. A positive
    z-index paints above the band: composed (control)."""
    found, _ = _a6(X, _band_run(**kw))
    if word is None:
        assert found == [], found
        return
    found, _ = _a6(X, _band_run(**kw))
    assert [i["status"] for i in found] == ["INCOMPLETE"] and word in found[0]["detail"], found


@pytest.mark.parametrize("prop,value", [("filter", "brightness(0.15)"), ("backdrop-filter", "invert(1)")])
def test_a6_axe_pass_under_an_ancestor_filter_is_incomplete(X, prop, value):
    """The CEO's decision of 2026-11-12 (found during TASK-CC-07): axe-core composes no CSS filter, so its pass on ink
    text inside a card whose filter (or backdrop-filter) the reader sees darkened is never taken: A6 INCOMPLETE naming
    the filter; the same card with no filter keeps the pass (control)."""
    an, rep = analysis(X, _x2_run(ancestor=True, **{prop: value}))
    an.a6()
    hit = items(rep, "A6", "INCOMPLETE", "axe does not compose filters")
    assert hit and value in hit[0]["detail"] and "div.f0-1" in hit[0]["detail"], rep.items
    an, rep = analysis(X, _x2_run(ancestor=True))
    an.a6()
    assert not items(rep, "A6", "INCOMPLETE") and not items(rep, "A6", "FAIL"), rep.items
