"""Tests of check_page.py on synthetic sites X, Y, Z (plan 0.4 B.9, check_page.py list).
Each negative control asserts the assertion ID (or stage) that must report it."""
import json
import os
import shutil
import subprocess
import sys
import uuid

import pytest

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import sites  # noqa: E402

CP = os.path.join(sites.SCRIPTS, "check_page.py")
RUN_AS = ["--run-as", "claude"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []
FONTS = "/usr/share/fonts/truetype"
pytestmark = pytest.mark.skipif(not os.path.isdir(sites.FONT_DIR), reason="test fonts not installed")


def cp(d, html, files=None, extra=(), page="index.html", site_css=True, script=CP, drop=()):
    b = sites.bundle(d, uuid.uuid4().hex[:10], html, files=files, site_css=site_css)
    for rel in drop:
        os.remove(os.path.join(b, rel))
    j = os.path.join(os.path.dirname(d), "page-%s.json" % uuid.uuid4().hex[:8])
    r = subprocess.run([sys.executable, "-I", "-B", script, b, "--page", page, "--site", d, "--json", j,
                        "--out", os.path.join(os.path.dirname(d), "out")] + RUN_AS + list(extra),
                       capture_output=True, text=True, timeout=300)
    rep = json.load(open(j)) if os.path.exists(j) else {"items": []}
    return r.returncode, rep["items"], r.stdout + r.stderr, rep, b


def kept(snap):
    """--kept with the snapshot's SHA-256, as the --snapshot run printed it (R2-M09)."""
    return ["--kept", snap, "--kept-sha256", sites.hashlib.sha256(open(snap, "rb").read()).hexdigest()]


def has(items, a, status="FAIL", word=None, path=None):
    return [i for i in items if i["check"] == a and i["status"] == status and (word is None or word in i["detail"])
            and (path is None or path in i["path"])]


def not_a_pass(items, a, path):
    """The report names the element at path for check a and gives it no PASS: at least one item of a whose path holds
    path, none of them PASS (X3). A filter that matches no item is never evidence of 'no PASS': report paths are tag
    paths ('html > body > main > div > p'), never class names, and A6 writes no PASS item per text run at all."""
    hit = [i for i in items if i["check"] == a and path in i["path"]]
    return bool(hit) and all(i["status"] != "PASS" for i in hit)


def xpage(body, style="", head="", lang=' lang="en"', title="<title>X page</title>"):
    return ('<!doctype html><html%s><head><meta charset="utf-8">%s<link rel="stylesheet" href="x.css">%s'
            '<style>body { margin: 0; } .wrap { max-width: 640px; padding: 16px; } %s</style></head>'
            '<body><main class="wrap">%s</main></body></html>' % (lang, title, head, style, body))


@pytest.fixture(scope="module")
def X(tmp_path_factory):
    d = sites.build_x(tmp_path_factory.mktemp("x"))
    sites.issue(d)
    return d


@pytest.fixture(scope="module")
def Y(tmp_path_factory):
    d = sites.build_y(tmp_path_factory.mktemp("y"))
    sites.issue(d)
    return d


@pytest.fixture(scope="module")
def Z(tmp_path_factory):
    d = sites.build_z(tmp_path_factory.mktemp("z"))
    sites.issue(d)
    return d


GOOD_X = xpage('<h1>Weekly progress</h1><p>Three short updates, written plainly.</p>'
               '<div class="card"><p>Muted text on the paper card.</p></div><a class="link" href="#top">Back to top</a>')
GOOD_Y = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Y page</title>'
          '<link rel="stylesheet" href="tokens.css"><link rel="stylesheet" href="y.css">'
          '<style>html, body { margin: 0; background: var(--color-paper-light); color: var(--color-ink-light); font-family: "Lora Test", serif; }'
          ' main { max-width: 600px; padding: 16px; }</style></head>'
          '<body><main><h1>Status</h1><p>A plain paragraph in the ink colour.</p></main></body></html>')
GOOD_Z = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Z page</title><link rel="stylesheet" href="z.css">'
          '<style>main { max-width: 700px; padding: 16px; }</style></head>'
          '<body><main><h1>Night board</h1><div class="panel"><p>Chalk text on the night panel.</p></div></main></body></html>')


# ------------------------------------------------------------------ positive and cross-profile controls

@pytest.mark.parametrize("site,html", [("X", GOOD_X), ("Y", GOOD_Y), ("Z", GOOD_Z)])
def test_correct_pages_pass(request, site, html):
    d = request.getfixturevalue(site)
    code, items, out, rep, _ = cp(d, html)
    assert code == 0, out
    assert rep["containment"] == ("os" if sys.platform.startswith("linux") else "browser")


@pytest.mark.parametrize("page_site,profile,checks", [("X", "Y", {"A1", "A2"}), ("Y", "X", {"A1", "A2"}), ("X", "Z", {"A1", "A2"})])
def test_cross_profile_fails(request, page_site, profile, checks):
    d_page, d_prof = request.getfixturevalue(page_site), request.getfixturevalue(profile)
    html = {"X": GOOD_X, "Y": GOOD_Y}[page_site]
    files = {}
    for f in os.listdir(os.path.join(os.path.dirname(d_page), "site")):
        p = os.path.join(os.path.dirname(d_page), "site", f)
        if os.path.isfile(p):
            files[f] = open(p, "rb").read()
    files.update({"fonts/" + f: open(os.path.join(os.path.dirname(d_page), "site", "fonts", f), "rb").read()
                  for f in os.listdir(os.path.join(os.path.dirname(d_page), "site", "fonts"))})
    code, items, out, _, _ = cp(d_prof, html, files=files, site_css=False)
    assert code == 1, out
    for a in checks:
        assert has(items, a), (a, out)


# ------------------------------------------------------------------ containment (H1, H2)

def test_outside_and_remote_references(X, tmp_path):
    canary = uuid.uuid4().hex
    outside = os.path.join(os.path.dirname(X), "bundles", "canary-%s.png" % canary)
    open(outside, "w").write(canary)
    html = xpage('<p>Text.</p><img alt="c" src="../canary-%s.png"><iframe title="f" src="file:///etc/hostname"></iframe>'
                 '<img alt="r" src="http://192.0.2.1/x.png">' % canary,
                 head='<link rel="stylesheet" href="http://192.0.2.1/x.css"><link rel="preload" href="wss://192.0.2.1/s" as="fetch">')
    code, items, out, rep, _ = cp(X, html)
    assert code == 1 and canary not in json.dumps(rep).replace("canary-%s.png" % canary, ""), out
    assert has(items, "A10", word="leaves the bundle") and has(items, "A10", word="file:///etc/hostname")
    assert has(items, "A10", word="http://192.0.2.1/x.css") and has(items, "A10", word="wss://192.0.2.1/s")
    assert has(items, "A10", "PASS", word="canary")
    if sys.platform.startswith("linux"):
        assert rep["containment"] == "os"
        assert has(items, "A10", word="request outside the loopback origin attempted (os)")


def test_symlink_and_env_refused(X):
    target = os.path.join(os.path.dirname(X), "secret.txt")
    open(target, "w").write("secret")
    b = sites.bundle(X, uuid.uuid4().hex[:10], xpage('<p>Text.</p><img alt="l" src="link.png">'))
    os.symlink(target, os.path.join(b, "link.png"))
    j = os.path.join(b, "..", "r.json")
    r = subprocess.run([sys.executable, "-I", "-B", CP, b, "--page", "index.html", "--site", X, "--json", j] + RUN_AS, capture_output=True, text=True)
    assert r.returncode == 2 and "link or junction" in r.stdout, r.stdout
    code, items, out, _, _ = cp(X, xpage('<p>Text.</p><img alt="e" src=".env.png">'), files={".env.png": "KEY=1"})
    assert code == 2 and "secret pattern" in out, out


def test_unreferenced_private_file_never_served(X):
    code, items, out, rep, b = cp(X, GOOD_X, files={"private-notes.txt": "private"})
    assert code == 0, out
    assert "private-notes" not in json.dumps(rep)


def _reach(port, hits):
    """Reach the test listener directly first, then forget the hit: zero hits later then mean containment, not a dead
    listener (AST-M01)."""
    import urllib.request
    urllib.request.urlopen("http://127.0.0.1:%d/positive-control" % port, timeout=10).read()
    assert hits == ["/positive-control"], hits
    hits.clear()


def test_script_never_runs(X):
    import http.server
    import threading
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    _reach(port, hits)          # positive control: the listener is reachable without containment (AST-M01)
    html = xpage('<p id="t">Static text.</p><img alt="x" src="data:," onerror="document.body.style.color=\'#00ff00\'">'
                 '<a class="link" href="javascript:fetch(\'http://127.0.0.1:%d/js\')">Link</a>' % port,
                 head='<script>fetch("http://127.0.0.1:%d/inline");document.addEventListener("DOMContentLoaded", () =>'
                      ' document.body.insertAdjacentHTML("beforeend", "<p style=\'color:#ff0000\'>injected</p>"));</script>'
                      '<script src="app.js"></script>' % port)
    code, items, out, rep, _ = cp(X, html, files={"app.js": "fetch('http://127.0.0.1:%d/file')" % port})
    srv.shutdown()
    assert hits == [], hits
    assert not has(items, "A2"), out          # a script that ran would have painted #ff0000 or #00ff00
    assert code == 3 and len([i for i in items if i["check"] == "STAGE" and i["status"] == "INCOMPLETE" and "never run" in i["detail"]]) == 4, out


def test_script_only_page_incomplete(X):
    html = xpage("", head='<script>document.body.innerHTML = "<p>made by script</p>";</script>')
    code, items, out, _, _ = cp(X, html)
    assert code == 3 and has(items, "PAGE", "INCOMPLETE", word="no text"), out


@pytest.mark.skipif(not (hasattr(os, "geteuid") and os.geteuid() == 0), reason="needs root")
def test_root_without_run_as_incomplete(X):
    b = sites.bundle(X, uuid.uuid4().hex[:10], GOOD_X)
    r = subprocess.run([sys.executable, "-I", "-B", CP, b, "--page", "index.html", "--site", X], capture_output=True, text=True)
    assert r.returncode == 3 and "isolation unavailable" in r.stdout, r.stdout


# ------------------------------------------------------------------ axe provenance and frames

def test_tampered_axe_is_error(X, tmp_path):
    plugin = tmp_path / "plugin"
    shutil.copytree(os.path.dirname(sites.SCRIPTS), plugin, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    with open(plugin / "scripts" / "vendor" / "axe-core" / "axe.min.js", "a") as fh:
        fh.write("\n// tampered\n")
    code, items, out, _, _ = cp(X, GOOD_X, script=str(plugin / "scripts" / "check_page.py"))
    assert code == 2 and "axe-core axe.min.js is missing or changed" in out, out


def test_contrast_failure_in_main_and_nested_frame(X):
    low = '<p style="color: var(--muted); background: var(--muted)">Low contrast text here.</p>'
    frame = '<!doctype html><html lang="en"><head><title>f</title><link rel="stylesheet" href="x.css"></head><body>%s</body></html>' % low
    code, items, out, _, _ = cp(X, xpage(low + '<iframe title="inner" src="inner.html"></iframe>'), files={"inner.html": frame})
    assert code == 1, out
    a6 = has(items, "A6")
    assert any(i["path"].startswith("html > body > main") for i in a6) and any(i["path"] == "html > body > p" for i in a6), out
    assert has(items, "A6", "INFO", word="in 2 frames"), out       # the execution summary is INFO (AST-L01)


# ------------------------------------------------------------------ A1 fonts

@pytest.mark.parametrize("style,body,files,status,word", [
    ("p { font-family: Georgia, serif; }", "<p>Serif text.</p>", None, "FAIL", "non-approved font"),
    ("", "<p>Text.</p>", "DROP", "FAIL", "non-approved font"),
    ('@font-face { font-family: "Inter Test"; src: url("other.ttf"); } p { font-family: "Inter Test"; }', "<p>Text.</p>",
     {"other.ttf": "google-fonts/Poppins-Bold.ttf"}, "FAIL", "not an approved"),
    ("p { font-weight: 800; }", "<p>Heavy text.</p>", None, "FAIL", "outside the approved range"),
    ("", "<p>Привет, мир.</p>", None, "INCOMPLETE", "outside the approved coverage"),
    ("code { font-family: ui-monospace, monospace; }", "<p><code>x = 1</code></p>", None, None, None),
    ('@font-face { font-family: "Code Dl"; src: url("code.ttf"); } code { font-family: "Code Dl", monospace; }', "<p><code>x = 1</code></p>",
     {"code.ttf": "dejavu/DejaVuSansMono.ttf"}, "FAIL", "code role must use the system monospace"),
    ("p { font-family: ui-monospace, monospace; }", "<p>Monospace prose.</p>", None, "FAIL", "non-approved font"),
], ids=["georgia", "file missing", "other file same name", "weight", "cyrillic", "system mono in code", "downloaded mono in code", "mono in p"])
def test_a1(X, style, body, files, status, word):
    drop = ["fonts/x.ttf"] if files == "DROP" else []
    files = {k: open(os.path.join(FONTS, v), "rb").read() for k, v in (files or {}).items()} if files != "DROP" else None
    code, items, out, _, _ = cp(X, xpage(body, style), files=files, drop=drop)
    if drop:
        assert has(items, "A10", word="fonts/x.ttf is missing"), out
    if status is None:
        assert not has(items, "A1") and not has(items, "A1", "INCOMPLETE"), out
    else:
        assert has(items, "A1", status, word), out


# ------------------------------------------------------------------ A2 palette by role

@pytest.mark.parametrize("style,body,word", [
    (".b { border: 2px solid #ff0000; }", '<p class="b">Bordered.</p>', "border-top"),
    (".g { background: linear-gradient(var(--paper), #00ff00); }", '<p class="g">Gradient.</p>', "gradient stop"),
    (".s { box-shadow: 0 2px 4px rgba(255, 0, 0, 0.3); }", '<p class="s">Shadow.</p>', "box-shadow"),
    ("", '<p>Icon</p><svg width="20" height="20"><circle cx="10" cy="10" r="8" fill="#00ff00"/></svg>', "fill"),
    (".f { background-color: rgba(26, 26, 46, 0.2); }", '<div class="f" style="width:40px;height:40px"></div><p>x</p>', "background-color"),
], ids=["border", "gradient", "shadow", "svg fill", "border extra as fill"])
def test_a2_invented_colours(X, style, body, word):
    code, items, out, _, _ = cp(X, xpage(body, style))
    assert code == 1 and has(items, "A2", word=word), out


def test_a2_reserved_is_floor(X):
    code, items, out, _, _ = cp(X, xpage('<p><a href="#a" style="color: var(--old-accent)">Old link</a></p>'))
    assert code == 1 and [i for i in has(items, "A2") if i.get("floor") and "reserved" in i["detail"]], out


@pytest.mark.parametrize("alpha,ok", [("0.2", True), ("0.22", False)])
def test_a2_extra_alpha(X, alpha, ok):
    code, items, out, _, _ = cp(X, xpage('<p style="border: 1px solid rgba(26, 26, 46, %s)">Edge.</p>' % alpha))
    assert bool(has(items, "A2")) is not ok, out


def test_a2_svg_group_without_geometry_passes(X):
    code, items, out, _, _ = cp(X, xpage('<p>Figure.</p><svg width="10" height="10"><g></g></svg>'))
    assert code == 0, out


def test_a2_light_token_in_dark_render_fails(Y):
    html = GOOD_Y.replace("color: var(--color-ink-light)", "color: #111827")
    code, items, out, _, _ = cp(Y, html)
    assert code == 1 and [i for i in has(items, "A2") if i.get("render", "").endswith("dark")], out


# ------------------------------------------------------------------ A3 headings

@pytest.mark.parametrize("body,ok", [
    ('<h4>Plain <span style="color: var(--accent)">accented words beyond</span></h4>', False),
    ('<h2><span style="color: var(--accent)">All accent</span></h2>', False),
    ('<h1>A heading of fifty letters with <span style="color: var(--accent)">ten accent</span> here x</h1>', True),
], ids=["beyond allowance", "whole accent", "site-like accent"])
def test_a3(X, body, ok):
    code, items, out, _, _ = cp(X, xpage(body + "<p>Body.</p>"))
    assert bool(has(items, "A3")) is not ok, out


def test_a3_no_accent_profile(Y):
    html = GOOD_Y.replace("<h1>Status</h1>", '<h1>Status <span style="color: var(--color-line)">now</span></h1>')
    code, items, out, _, _ = cp(Y, html)
    assert has(items, "A3"), out


# ------------------------------------------------------------------ A4 limited fills

@pytest.mark.parametrize("box,ok", [("width:50px;height:50px;background:var(--accent)", True),
                                    ("width:41px;height:61px;background:var(--accent)", False),
                                    ("width:200px;height:200px;background:rgba(194, 65, 12, 0.5)", True),
                                    ("width:200px;height:200px;background:rgba(194, 65, 12, 0.51)", False)],
                         ids=["2500 passes", "2501 fails", "alpha at threshold", "alpha above"])
def test_a4(X, box, ok):
    code, items, out, _, _ = cp(X, xpage('<div style="%s"></div><p>Fill.</p>' % box))
    assert bool(has(items, "A4")) is not ok, out


def test_a4_pseudo_and_gradient(X):
    code, items, out, _, _ = cp(X, xpage('<p class="z">Badge.</p><div class="gb" style="width:300px;height:100px"></div>',
                                         '.z::after { content: ""; display: block; width: 100px; height: 100px; background: var(--accent); }'
                                         '.gb { background: linear-gradient(var(--paper), var(--accent)); }'))
    assert has(items, "A4", path="::after") and has(items, "A4", "INCOMPLETE", word="gradient"), out


def test_a4_waiver(tmp_path):
    d = sites.build_x(tmp_path)
    html = xpage('<div id="big" style="width:41px;height:61px;background:var(--accent)"></div><p>Fill.</p>')
    b = sites.bundle(d, "w", html)
    sha = sites.hashlib.sha256(open(os.path.join(b, "index.html"), "rb").read()).hexdigest()
    open(os.path.join(d, "waivers.yaml"), "w").write(
        "waivers:\n  - {id: w1, assertion: A4, page: index.html, selector: 'div#big', page_sha256: %s, reason: test banner, owner_words: 'да', date: '2026-11-10'}\n" % sha)
    sites.issue(d)
    j = os.path.join(tmp_path, "r.json")
    r = subprocess.run([sys.executable, "-I", "-B", CP, b, "--page", "index.html", "--site", d, "--json", j] + RUN_AS, capture_output=True, text=True)
    items = json.load(open(j))["items"]
    assert has(items, "A4", "WAIVED") and not has(items, "A4"), r.stdout


# ------------------------------------------------------------------ A5, A6

def test_a5(X):
    code, items, out, _, _ = cp(X, xpage('<p>Status: <span style="color: var(--old-accent)">late</span></p>'))
    assert has(items, "A5"), out
    code, items, out, _, _ = cp(X, xpage('<p style="color: var(--muted)">Muted note.</p>'))
    assert not has(items, "A5"), out


@pytest.mark.parametrize("body,style,status,word", [
    ('<div class="card"><p>Muted on paper.</p></div>', "", None, None),
    ('<div style="opacity: 0.1"><p style="color: var(--ink)">Faded ink.</p></div>', "", "FAIL", None),
    ('<p class="g">Ink on a gradient to ink.</p>', ".g { background: linear-gradient(var(--paper), var(--ink)); color: var(--ink); }", "FAIL", "fallback"),
    ('<p class="g">Ink on a paper gradient.</p>', ".g { background: linear-gradient(var(--paper), var(--paper)); color: var(--ink); }", None, None),
    ('<p class="i">Text on an image.</p>', '.i { background-image: url("bg.png"); }', "INCOMPLETE", "background image"),
    ('<div style="position:relative"><p>Corner covered text.</p><div style="position:absolute;top:0;left:0;width:10px;height:10px;background:var(--paper)"></div></div>',
     "", "INCOMPLETE", "overlap"),
    ('<div style="height:1500px"></div><div style="position:relative"><p>Low text.</p><div style="position:absolute;top:0;left:0;width:8px;height:8px;background:var(--paper)"></div></div>',
     "", "INCOMPLETE", "overlap"),
], ids=["muted on paper", "opacity", "gradient fails", "gradient passes", "image", "overlay", "overlay below the fold"])
def test_a6(X, body, style, status, word):
    files = {"bg.png": open(os.path.join(HERE, "..", "scripts", "vendor", "axe-core", "LICENSE"), "rb").read()} if "bg.png" in style else None
    code, items, out, _, _ = cp(X, xpage(body, style), files=files)
    a6 = [i for i in items if i["check"] == "A6" and i["status"] in ("FAIL", "INCOMPLETE")]
    if status is None:
        # a positive control needs execution evidence, not only the absence of findings (AST-M19)
        summaries = [i for i in items if i["check"] == "A6" and i["status"] == "INFO" and "color-contrast in 1 frames" in i["detail"]]
        assert not a6 and len(summaries) == 4 and all(" 0 text runs" not in i["detail"] for i in summaries), out
    else:
        assert [i for i in a6 if i["status"] == status and (word is None or word in i["detail"])], out


# ------------------------------------------------------------------ A7, A8

@pytest.mark.parametrize("style,ok", [("width:681px", False), ("width:680px", True),
                                      ("width:720px;padding:0 20px;box-sizing:border-box", True)])
def test_a7(X, style, ok):
    code, items, out, _, _ = cp(X, xpage('<p style="%s">Reading text.</p>' % style, ".wrap { max-width: none; }"))
    assert bool(has(items, "A7")) is not ok, out


def test_a7_label_not_measured(X):
    code, items, out, _, _ = cp(X, xpage('<p style="width:900px;font-size:12px;font-weight:700">A label line.</p>', ".wrap { max-width: none; }"))
    assert not has(items, "A7"), out


def test_a7_named_role(tmp_path):
    d = sites.build_x(tmp_path)
    sites.edit(os.path.join(d, "policy.yaml"), "roles: []\ncapitals", "roles:\n  - {selector: .wide, px: 760}\ncapitals")
    sites.issue(d)
    ok = cp(d, xpage('<p class="wide" style="width:760px">Wide.</p>', ".wrap { max-width: none; }"))
    bad = cp(d, xpage('<p class="wide" style="width:761px">Wide.</p>', ".wrap { max-width: none; }"))
    assert not has(ok[1], "A7") and has(bad[1], "A7"), bad[2]


@pytest.mark.parametrize("body,ok", [("<h2 style='text-transform:uppercase'>Loud heading</h2>", False),
                                     ("<p>THIS IS SHOUTING in a paragraph.</p>", False),
                                     ("<p style='font-size:12px;font-weight:700'>LABEL IN CAPITALS NOW</p>", True),
                                     ("<p>The NASA report is long.</p>", True)],
                         ids=["uppercase heading", "literal capitals", "label", "acronym"])
def test_a8(X, body, ok):
    code, items, out, _, _ = cp(X, xpage(body))
    assert bool(has(items, "A8")) is not ok, out


# ------------------------------------------------------------------ A9 scheme

def test_a9_light_only(X):
    dark = "@media (prefers-color-scheme: dark) { .card { background: var(--ink); } }"
    code, items, out, _, _ = cp(X, xpage('<div class="card"><p>Panel.</p></div>', dark))
    assert has(items, "A9"), out
    narrow = "@media (prefers-color-scheme: dark) and (max-width: 500px) { .card p { color: var(--ink); } }"
    code, items, out, _, _ = cp(X, xpage('<div class="card"><p>Panel.</p></div>', narrow))
    assert [i for i in has(items, "A9") if "390" in i["detail"]], out


def test_a9_dark_only_and_both(Z, Y):
    light = GOOD_Z.replace("</style>", "@media (prefers-color-scheme: light) { body { background: #eeeeee; color: #111111; } }</style>")
    code, items, out, _, _ = cp(Z, light)
    assert has(items, "A9"), out
    flat = GOOD_Y.replace("background: var(--color-paper-light)", "background: #fafafa")
    code, items, out, _, _ = cp(Y, flat)
    assert has(items, "A9", word="scheme both: they differ"), out


# ------------------------------------------------------------------ A11, A12

def test_a11_advisory_and_blocking(tmp_path):
    two = '<p>Choose.</p><a class="button-primary" href="#a">One</a> <a class="button-primary" href="#b">Two</a>'
    d = sites.build_x(tmp_path / "a")
    sites.issue(d)
    code, items, out, _, _ = cp(d, xpage(two))
    assert has(items, "A11", "WARN") and code == 0, out
    d2 = sites.build_x(tmp_path / "b")
    sites.edit(os.path.join(d2, "policy.yaml"), "  A5: blocking", "  A5: blocking\n  A11: blocking")
    sites.issue(d2)
    code, items, out, _, _ = cp(d2, xpage(two))
    assert has(items, "A11", "FAIL") and code == 1, out


def test_a12(X, tmp_path):
    code, items, out, _, _ = cp(X, xpage("<p>No language.</p>", lang=""))
    assert code == 1 and (has(items, "A12", word="lang") or [i for i in has(items, "A12") if "html-has-lang" in i["path"]]), out   # AST-M19
    d = sites.build_x(tmp_path)
    sites.edit(os.path.join(d, "policy.yaml"), "  - wcag2aa", "  - wcag2aa\n  - best-practice")
    sites.issue(d)
    code, items, out, _, _ = cp(d, '<!doctype html><html lang="en"><head><title>t</title><link rel="stylesheet" href="x.css"></head>'
                                   '<body><p>No landmark around me.</p></body></html>')
    assert [i for i in has(items, "A12", "WARN") if i.get("rule") == "region"], out


# ------------------------------------------------------------------ A13 structural preservation

OLD = xpage('<h2>Contact</h2><nav aria-label="Main"><a href="/a">Alpha</a> <a href="/b">Beta</a> <a href="/b">Beta</a></nav>'
            '<form action="/send" method="post"><label>Name <input name="who" type="text"></label><button>Send</button></form>'
            '<p><span onclick="go()">tap</span></p>')


@pytest.mark.parametrize("new,entry", [
    (OLD.replace('<a href="/a">Alpha</a>', ""), "link|"),
    (OLD.replace('<input name="who" type="text">', ""), "field|"),
    (OLD.replace("<button>Send</button>", ""), "button|"),
    (OLD.replace("<h2>Contact</h2>", ""), "heading|"),
    (OLD.replace('<nav aria-label="Main">', "<div>").replace("</nav>", "</div>"), "landmark|"),
    (OLD.replace('action="/send"', 'action="/other"'), "form|"),
    (OLD.replace(' onclick="go()"', ""), "handler|"),
    (OLD.replace(' <a href="/b">Beta</a></nav>', "</nav>"), "link|"),
    (OLD.replace("<button>Send</button>", '<button style="display:none">Send</button>'), "button|"),
], ids=["link", "field", "button", "heading", "landmark", "form action", "handler", "duplicate", "hidden replacement"])
def test_a13(X, tmp_path, new, entry):
    snap = str(tmp_path / "snap.json")
    code, items, out, _, _ = cp(X, OLD, extra=["--snapshot", snap])
    assert os.path.exists(snap), out
    code, items, out, _, _ = cp(X, new, extra=kept(snap))
    missing = [i["path"] for i in has(items, "A13")]
    allowed = (entry, "field|") if entry in ("form|", "button|") else (entry,)     # a button is a field of its form (R2-M09)
    assert missing and all(m.startswith(allowed) for m in missing) and any(m.startswith(entry) for m in missing), out


def test_a13_kept_unchanged_and_waived(tmp_path):
    d = sites.build_x(tmp_path)
    sites.issue(d)
    snap = str(tmp_path / "snap.json")
    cp(d, OLD, extra=["--snapshot", snap])
    code, items, out, _, _ = cp(d, OLD, extra=kept(snap))
    assert has(items, "A13", "PASS") and has(items, "A13", "NOT_CHECKED"), out
    new = OLD.replace("<h2>Contact</h2>", "")
    b = sites.bundle(d, "kept", new)
    sha = sites.hashlib.sha256(open(os.path.join(b, "index.html"), "rb").read()).hexdigest()
    open(os.path.join(d, "waivers.yaml"), "w").write(
        "waivers:\n  - {id: w2, assertion: A13, page: index.html, selector: 'heading|2|Contact', page_sha256: %s, reason: heading moved, owner_words: 'да', date: '2026-11-10'}\n" % sha)
    sites.edit(os.path.join(d, "policy.yaml"), "  A5: blocking", "  A5: blocking\n  A13: waivable")
    sites.issue(d)
    j = os.path.join(tmp_path, "r.json")
    r = subprocess.run([sys.executable, "-I", "-B", CP, b, "--page", "index.html", "--site", d] + kept(snap) + ["--json", j] + RUN_AS,
                       capture_output=True, text=True)
    assert has(json.load(open(j))["items"], "A13", "WAIVED"), r.stdout


# ------------------------------------------------------------------ outcomes

def test_empty_page_incomplete(X):
    code, items, out, _, _ = cp(X, xpage(""))
    assert code == 3 and has(items, "PAGE", "INCOMPLETE"), out


def test_unreadable_page_error(X):
    code, items, out, _, _ = cp(X, GOOD_X, page="missing.html")
    assert code == 2 and "not readable" in out, out


def test_stale_receipt_incomplete(tmp_path):
    d = sites.build_x(tmp_path)
    sites.issue(d)
    sites.edit(os.path.join(d, "README.md"), "synthetic", "synthetic, edited")
    code, items, out, _, _ = cp(d, GOOD_X)
    assert code == 3 and "stale receipt" in out and "containment: none" in out, out


def test_missing_playwright_and_truncation(X, monkeypatch, capsys):
    import importlib.util
    sys.path.insert(0, sites.SCRIPTS)
    import check_page
    b = sites.bundle(X, uuid.uuid4().hex[:10], GOOD_X)
    real = importlib.util.find_spec
    monkeypatch.setattr(check_page.importlib.util, "find_spec", lambda n: None if n == "playwright" else real(n))
    assert check_page.main([b, "--page", "index.html", "--site", X] + RUN_AS) == 2
    assert "Playwright is not installed" in capsys.readouterr().out
    monkeypatch.setattr(check_page.importlib.util, "find_spec", real)
    monkeypatch.setattr(check_page, "MAX_ITEMS", 3)
    assert check_page.main([b, "--page", "index.html", "--site", X] + RUN_AS) == 3
    assert "truncated" in capsys.readouterr().out


def test_a1_renamed_file_and_data_url_font(X, tmp_path):
    ft = pytest.importorskip("fontTools.ttLib")
    f = ft.TTFont(os.path.join(sites.FONT_DIR, "Poppins-Bold.ttf"))
    for rec in f["name"].names:
        if rec.nameID == 6:
            rec.string = "Poppins-Regular"
    renamed = str(tmp_path / "renamed.ttf")
    f.save(renamed)
    style = '@font-face { font-family: "Inter Test"; src: url("renamed.ttf"); } p { font-family: "Inter Test"; }'
    code, items, out, _, _ = cp(X, xpage("<p>Text.</p>", style), files={"renamed.ttf": open(renamed, "rb").read()}, drop=["fonts/x.ttf"])
    assert has(items, "A1", word="is not an approved face file"), out
    import base64
    data = base64.b64encode(open(os.path.join(sites.FONT_DIR, "Poppins-Bold.ttf"), "rb").read()).decode()
    style = '@font-face { font-family: "Dl"; src: url(data:font/ttf;base64,%s); } p { font-family: "Dl"; }' % data
    code, items, out, _, _ = cp(X, xpage("<p>Text.</p>", style))
    assert has(items, "A1", word="custom font Poppins-Bold is not an approved face"), out


def test_a6_axe_violation_stands_when_the_fallback_cannot_decide(X):
    style = '.d::before { content: ""; position: absolute; left: -9999px; width: 1px; height: 1px; background: var(--ink); }'
    code, items, out, _, _ = cp(X, xpage('<div class="d" style="position:relative"><p style="color: var(--muted); background: var(--muted)">Low.</p></div>', style))
    assert [i for i in has(items, "A6") if "axe:" in i["detail"]], out


def test_a12_needs_review_warns_and_object_incomplete(X):
    files = {"clip.mp4": b"\0\0\0\x18ftypmp42", "x.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>"}
    code, items, out, _, _ = cp(X, xpage('<p>Clip.</p><video src="clip.mp4" width="80" height="40"></video>'), files=files)
    assert code == 0 and has(items, "A12", "WARN", word="needs review"), out
    code, items, out, _, _ = cp(X, xpage('<p>Text.</p><object data="x.svg" width="10" height="10"></object>'), files=files)
    assert code == 3 and has(items, "STAGE", "INCOMPLETE", path="object/embed"), out


# ------------------------------------------------------------------ added after review round 1

def test_shadow_dom_and_data_frames_are_incomplete(X):
    shadow = '<div><template shadowrootmode="open"><p style="color:#ff0000;font-family:Georgia,serif">Hidden red.</p></template></div>'
    code, items, out, _, _ = cp(X, xpage("<p>Visible.</p>" + shadow))
    assert code != 0 and has(items, "PAGE", "INCOMPLETE", word="shadow DOM"), out
    closed = '<div><template shadowrootmode="closed"><p style="color:#ff0000">Closed.</p></template></div>'
    code, items, out, _, _ = cp(X, xpage("<p>Visible.</p>" + closed))
    assert code != 0 and has(items, "PAGE", "INCOMPLETE", word="shadow DOM"), out
    frame = "<iframe title=\"d\" src=\"data:text/html,<p style='color:%23ff0000'>In a data frame.</p>\"></iframe>"
    code, items, out, _, _ = cp(X, xpage("<p>Visible.</p>" + frame))
    assert code != 0 and has(items, "PAGE", "INCOMPLETE", word="frame that is not checked"), out


def test_a1_dark_only_font_and_partial_system_font(X):
    code, items, out, _, _ = cp(X, xpage("<p>Text.</p>", "@media (prefers-color-scheme: dark) { p { font-family: Georgia, serif; } }"))
    assert [i for i in has(items, "A1") if i.get("render", "").endswith("dark")], out
    code, items, out, _, _ = cp(X, xpage("<p>Hello мир</p>", "p { font-family: Georgia, serif; }"))
    assert has(items, "A1", word="more than the"), out


def test_a1_italic_fails(X):
    code, items, out, _, _ = cp(X, xpage("<p><em>Slanted words.</em></p>"))
    assert has(items, "A1", word="style italic"), out


def test_a3_too_many_accent_runs(X):
    body = ('<h1>A long heading with <span style="color: var(--accent)">one</span> and <span style="color: var(--accent)">two</span>'
            ' accents inside it</h1><p>Body.</p>')
    code, items, out, _, _ = cp(X, xpage(body))
    assert has(items, "A3", word="in 2 runs"), out


def test_first_line_paints(X):
    code, items, out, _, _ = cp(X, xpage('<p class="fl">First line in another colour, then the rest.</p>', ".fl::first-line { color: var(--old-accent); }"))
    assert has(items, "A2", word="::first-line") and has(items, "A6", "INCOMPLETE", word="::first-line"), out


def test_text_fill_and_decoration_paints(X):
    code, items, out, _, _ = cp(X, xpage('<p class="t">Filled.</p><p class="u">Underlined.</p>',
                                         ".t { -webkit-text-fill-color: #00ff00; } .u { text-decoration: underline; text-decoration-color: #ff00ff; }"))
    assert has(items, "A2", word="-webkit-text-fill-color") and has(items, "A2", word="text-decoration-color"), out


def test_a12_profile_tiers_keep_the_h3_defaults(X):
    code, items, out, _, _ = cp(X, xpage('<p>Picture.</p><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="10" height="10">'))
    assert [i for i in has(items, "A12") if i.get("rule") == "image-alt"], out    # X names only html-has-lang; image-alt stays blocking


def test_media_contents_listed_as_not_checked(X):
    code, items, out, _, _ = cp(X, xpage('<p>Picture.</p><img alt="dot" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="10" height="10">'))
    assert has(items, "PAGE", "NOT_CHECKED", word="img element"), out


def test_kept_snapshot_unreadable_is_error(X, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    code, items, out, _, _ = cp(X, GOOD_X, extra=["--kept", str(bad)])
    assert code == 2 and "unreadable" in out, out


def test_server_error_responses_carry_the_policy():
    import socket
    import threading
    sys.path.insert(0, sites.SCRIPTS)
    import check_page
    import tempfile
    root = tempfile.mkdtemp()
    srv = check_page.make_server(root, [], {})   # HQ's W2 fix: the inventory argument (R2-M12)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    def raw(req):
        s = socket.create_connection(("127.0.0.1", port))
        s.sendall(req)
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        s.close()
        return data.decode("latin-1")
    try:
        for req in (b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\nHost: x\r\n\r\n", b"BREW /x HTTP/1.1\r\nHost: x\r\n\r\n", b"GET /nope HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"):
            resp = raw(req)
            assert "Content-Security-Policy: script-src 'none'" in resp, resp[:300]
    finally:
        srv.shutdown()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="forces the browser level on Linux")
def test_browser_containment(X):
    import http.server
    import threading
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    _reach(port, hits)          # positive control (AST-M01)
    html = xpage('<p>Contained text.</p><img alt="o" src="http://127.0.0.1:%d/img.png"><img alt="r" src="http://192.0.2.1/x.png">' % port,
                 head='<link rel="stylesheet" href="http://127.0.0.1:%d/css.css">' % port)
    b = sites.bundle(X, uuid.uuid4().hex[:10], html)
    j = os.path.join(os.path.dirname(X), "bc.json")
    env = dict(os.environ, SDS_FORCE_BROWSER_CONTAINMENT="1")
    r = subprocess.run([sys.executable, "-I", "-B", CP, b, "--page", "index.html", "--site", X, "--json", j] + RUN_AS,
                       capture_output=True, text=True, env=env, timeout=300)
    srv.shutdown()
    rep = json.load(open(j))
    assert rep["containment"] == "browser" and hits == [], (hits, r.stdout)
    assert has(rep["items"], "CONTAIN", "WARN", word="forced to browser"), r.stdout
    assert has(rep["items"], "A10", word="127.0.0.1:%d/css.css" % port), r.stdout


def test_truncation_keeps_failures(X, monkeypatch, capsys):
    sys.path.insert(0, sites.SCRIPTS)
    import check_page
    b = sites.bundle(X, uuid.uuid4().hex[:10], xpage('<p style="border: 1px solid #ff0000">Bad border.</p>'))
    monkeypatch.setattr(check_page, "MAX_ITEMS", 2)
    assert check_page.main([b, "--page", "index.html", "--site", X] + RUN_AS) == 1
    assert "truncated" in capsys.readouterr().out


def _fake_render(axe):
    el = {"id": "f0:0", "tag": "p", "path": "html > body > p", "rect": [0, 0, 100, 20], "visible": True, "text": "Some text.",
          "text_rects": [[0, 0, 80, 16]], "parent": None, "svg": False, "role": "", "heading": False, "label": False, "code": False,
          "measure": [], "button_sel": False, "in_noscript": False, "pseudo": {}, "textpseudo": {}, "opacity": 1.0,
          "style": {"color": "rgb(26, 26, 46)", "background-color": "rgb(255, 253, 247)", "background-image": "none", "font-size": "16px",
                    "font-weight": "400", "filter": "none", "backdrop-filter": "none", "mix-blend-mode": "normal", "mask-image": "none",
                    "clip-path": "none", "color-scheme": "normal"}}
    frame = {"key": "f0", "url": "http://127.0.0.1/x", "main": True, "data": {"elements": [el]}, "axe_contrast": axe, "overlap": {"f0:0": ["ok"] * 5}}
    import check_page
    prefs = {"evidence": {"confirmed": True},      # the fresh loads of every other preference state, all unchanged (W1)
             "states": [{"label": check_page.preference_label(s), "confirmed": True, "changed": []} for s in check_page.preference_states()]}
    return {"renders": [{"name": "w1280-light", "width": 1280, "scheme": "light", "frames": [frame], "preferences": prefs}],
            "origin": "http://127.0.0.1"}


@pytest.mark.parametrize("axe,word", [({"passes": [], "violations": [], "incomplete": [], "inapplicable": ["color-contrast"]}, "inapplicable"),
                                      ({"passes": [], "violations": [], "incomplete": [], "inapplicable": []}, "no execution evidence")],
                         ids=["inapplicable", "silent"])
def test_a6_needs_axe_evidence(tmp_path, axe, word):
    sys.path.insert(0, sites.SCRIPTS)
    import check_page
    import designlib as dl
    import policylib as pl
    d = sites.build_x(tmp_path)
    rep = dl.Report("t")
    an = check_page.Analysis(pl.Profile(d), rep, "index.html", "x", _fake_render(axe))
    an.a6()
    assert [i for i in rep.items if i["check"] == "A6" and i["status"] == "INCOMPLETE" and word in i["detail"]], rep.items


def test_hard_link_and_profile_name_refused(X):
    b = sites.bundle(X, uuid.uuid4().hex[:10], xpage('<p>Text.</p><img alt="h" src="hard.png">'), files={"real.png": b"\x89PNG"})
    os.link(os.path.join(b, "real.png"), os.path.join(b, "hard.png"))
    r = subprocess.run([sys.executable, "-I", "-B", CP, b, "--page", "index.html", "--site", X] + RUN_AS, capture_output=True, text=True)
    assert r.returncode == 2 and "hard link" in r.stdout, r.stdout
    code, items, out, _, _ = cp(X, xpage('<p>Text.</p><img alt="p" src="Policy.YAML">'), files={"Policy.YAML": "roles: {}"})
    assert code == 2 and "site design folder file name" in out, out


def test_a9_both_needs_the_scheme_background_tokens(Y):
    html = GOOD_Y.replace("</style>", "@media (prefers-color-scheme: dark) { html, body { background: #000000; } }</style>")
    code, items, out, _, _ = cp(Y, html)
    assert has(items, "A9", word="scheme both: they differ"), out


# ------------------------------------------------------------------ added after review round 2

def test_generated_text(X):
    style = ('.g::before { content: "Generated sentence in the paper colour on paper. "; color: var(--paper); }'
             '.f::after { content: "late"; color: var(--old-accent); } .d::after { content: ""; display: inline-block; width: 4px; height: 4px; }')
    code, items, out, _, _ = cp(X, xpage('<p class="g">Real text.</p><p class="f">Status: </p><p class="d">Plain.</p>', style))
    assert has(items, "A6", "INCOMPLETE", word="generated text (::before") and has(items, "A5", path="p:nth-of-type(2)"), out
    assert not [i for i in items if i["check"] == "A6" and "p:nth-of-type(3)" in i["path"]], out


def test_svg_link_and_clobbered_form_action(X, tmp_path):
    body = ('<p>Chart.</p><svg width="40" height="20"><a href="#top"><text x="0" y="15" fill="#1a1a2e">Top</text></a></svg>'
            '<form action="/subscribe" method="post"><input type="hidden" name="action" value="x"><button class="button-primary">Go</button></form>')
    snap = str(tmp_path / "s.json")
    code, items, out, _, _ = cp(X, xpage(body), extra=["--snapshot", snap])
    assert code != 2, out
    entries = json.load(open(snap))["entries"]
    assert "link|/#top|Top" in [e.replace("index.html", "") if False else e for e in entries] or any(e.startswith("link|") and e.endswith("#top|Top") for e in entries), entries
    assert any(e.startswith("form|") and e.endswith("/subscribe|post") for e in entries), entries


@pytest.mark.parametrize("body", ['<svg width="10" height="10"><a xlink:href="javascript:void(0)"><text y="9">x</text></a></svg>',
                                  '<a class="link" href="java&#9;script:void(0)">Tab</a>',
                                  ""], ids=["xlink", "tab", "meta refresh"])
def test_script_forms_and_meta_refresh_incomplete(X, body):
    head = '<meta http-equiv="refresh" content="30">' if not body else ""
    code, items, out, _, _ = cp(X, xpage("<p>Text.</p>" + body, head=head))
    assert code != 0 and has(items, "STAGE", "INCOMPLETE", word="page script present"), out


def test_frame_documents_do_not_fail_page_level_rules(X):
    frame = '<iframe title="inner" srcdoc="&lt;p&gt;Frame text.&lt;/p&gt;"></iframe>'
    code, items, out, _, _ = cp(X, xpage("<p>Text.</p>" + frame))
    assert not [i for i in has(items, "A12") if i.get("rule") in ("document-title", "html-has-lang")], out
    assert has(items, "A12", "INFO", word="tags") and not has(items, "A12", "INCOMPLETE"), out    # A12 ran (AST-M19)


def test_a5_and_a2_on_first_line_fill_shadow_and_stroke(X):
    style = (".a::first-line { color: var(--old-accent); } .b { -webkit-text-fill-color: var(--old-accent); }"
             ".c { text-shadow: 0 1px 2px #ff00ff; } .s { -webkit-text-stroke: 1px #00ffff; }")
    code, items, out, _, _ = cp(X, xpage('<p class="a">First line text here.</p><p class="b">Fill.</p><p class="c">Shadow.</p><p class="s">Stroke.</p>', style))
    assert has(items, "A5", path="p:nth-of-type(1)") and has(items, "A5", path="p:nth-of-type(2)"), out
    assert has(items, "A2", word="text-shadow") and has(items, "A2", word="-webkit-text-stroke-color"), out


def test_fonts_not_ready_is_incomplete(tmp_path):
    sys.path.insert(0, sites.SCRIPTS)
    import check_page
    import designlib as dl
    import policylib as pl
    d = sites.build_x(tmp_path)
    res = _fake_render({"passes": [], "violations": [], "incomplete": [], "inapplicable": []})
    res["renders"][0]["fonts_ready"] = "timeout"
    rep = dl.Report("t")
    check_page.Analysis(pl.Profile(d), rep, "index.html", "x", res).coverage()
    assert [i for i in rep.items if i["check"] == "BUDGET" and i["status"] == "INCOMPLETE"], rep.items


def test_hg_folder_refused(X):
    code, items, out, _, _ = cp(X, xpage('<p>Text.</p><img alt="h" src=".hg/x.png">'), files={".hg/x.png": b"\x89PNG"})
    assert code == 2 and "VCS or secret pattern" in out, out



# ------------------------------------------------------------------ added after the smoke test (plan 0.4 B.10)

def test_a7_layout_container_without_own_text_not_measured(X):
    body = ('<ol style="width:1000px;list-style:none;padding:0"><li style="display:flex;gap:20px"><div style="width:120px">2026-09-14</div>'
            '<div style="width:600px">Body text of a timeline entry.</div></li></ol><ul style="padding:0;list-style:none">'
            '<li style="width:800px">A list item with its own text.</li></ul>'
            '<p style="width:800px"><a href="#x"><strong>A paragraph whose only text sits inside a link.</strong></a></p>'
            '<ol style="width:1000px;padding:0"><li style="position:relative"><span style="position:absolute;left:0">*</span>'
            '<span>An item with a positioned marker and inline text.</span></li></ol>')
    code, items, out, _, _ = cp(X, xpage(body, ".wrap { max-width: none; }"))
    paths = sorted({x["path"] for x in has(items, "A7")})      # findings now keep their render (AST-L01)
    assert len(paths) == 3, out
    assert sum("ul > li" in q for q in paths) == 1 and sum(q.endswith(" > p") or q.endswith(" > p:nth-of-type(1)") for q in paths) == 1, paths
    assert sum("ol:nth-of-type(2) > li" in q for q in paths) == 1, paths


# ------------------------------------------------------------------ added after the outside audit, round 1 (browser)

@pytest.mark.parametrize("style,body", [
    ("p.m { color: var(--paper); } html[data-sds-id] p.m { color: var(--ink); }", '<p class="m">Text that reacts to the marker.</p>'),
    ("p.m { color: var(--paper); } @media (min-height: 1200px) { p.m { color: var(--ink); } }",
     '<p class="m">Text that reacts to a tall viewport.</p><div style="height:1500px"></div>'),
], ids=["marker", "viewport height"])
def test_a6_paint_changed_while_checking(X, style, body):
    """AST-H03, R2-H02: page CSS written to react to a checker's marker or to a taller viewport never fires (the checker
    adds no marker and never resizes the viewport), so the paper-on-paper text the reader sees is never a pass."""
    code, items, out, _, _ = cp(X, xpage(body, style))
    # "> p", not "p": the A6 summary's path "page" holds a p (X3)
    assert code != 0 and (has(items, "A6", "FAIL", path="> p") or has(items, "A6", "INCOMPLETE", path="> p")), out
    assert not_a_pass(items, "A6", "> p"), out


LAYER = ('<div class="box"><div class="bg"></div><p class="probe">Ink text that must not pass on an ink layer.</p></div>',
         ".box { position: relative; z-index: 0; } .bg { position: absolute; inset: 0; z-index: -1; background: var(--ink); }"
         " .probe { color: var(--ink); }")


@pytest.mark.parametrize("extra,tall", [
    (".bg[data-sds-id] { scale: 0; }", False),
    (".bg[data-sds-id] { display: none; }", False),
    ("html:has(> style) .bg { display: none; }", False),
    ("@media (min-height: 1500px) { .bg { display: none; } }", True),
    (".bg[data-sds-id] { inset: auto; top: 5000px; left: 0; width: 100%; height: 100%; }", False),
    (".bg { pointer-events: none; }", False),
], ids=["scale under a marker", "hidden under a marker", "hidden by an appended style", "hidden in a taller viewport",
        "moved by top under a marker", "pointer-events none"])
def test_a6_paint_change_of_a_sibling_layer(X, extra, tall):
    """HQ's V4 and C2, R2-H02 (HQ's sibling-layer page): page CSS written to hide or move the ink layer behind the ink
    text when a checker marks the DOM, appends a style or grows the viewport never fires, and a layer hit testing skips
    (pointer-events: none) is still seen: exit not 0 and an A6 item that is not PASS on the paragraph, as the control."""
    body, style = LAYER
    code, items, out, _, _ = cp(X, xpage(body + ('<div style="height:2400px"></div>' if tall else ""), style + " " + extra))
    assert code != 0 and (has(items, "A6", "INCOMPLETE", path="> p") or has(items, "A6", "FAIL", path="> p")), out   # the page's one p
    assert not_a_pass(items, "A6", "> p"), out


@pytest.mark.parametrize("visible,hidden", [("scale: 1", "scale: 0"), ("top: 0px", "top: 5000px")], ids=["scale", "top"])
def test_a6_layer_changed_by_scrolling_is_not_a_pass(X, visible, hidden):
    """R2-H02(3), C2: the paragraph lies below the first viewport over the ink layer, which a scroll-driven animation
    removes once the page is scrolled: the PAINTS read at that scroll position differs from the first read, so A6 is
    INCOMPLETE there (never PASS on the state the scrolling made)."""
    body, style = LAYER
    anim = ("@keyframes away { 0%% { %s; } 1%% { %s; } 100%% { %s; } }"
            " .bg { animation: away auto linear both; animation-timeline: scroll(root); }") % (visible, hidden, hidden)
    html = xpage('<div style="height:1500px"></div>' + body + '<div style="height:1500px"></div>', style + " " + anim)
    code, items, out, _, _ = cp(X, html)
    assert code != 0 and (has(items, "A6", "INCOMPLETE", path="> p") or has(items, "A6", "FAIL", path="> p")), out
    assert not_a_pass(items, "A6", "> p"), out


def test_a6_layer_hidden_only_in_the_middle_of_the_scroll_range_is_not_a_pass(X):
    """W3 (HQ's probe scroll_mid): the ink layer is hidden by a scroll-driven animation only in the middle of the scroll
    range; at offset 0 and at the last offset it paints as in the first read, and the text is evidenced at a middle
    offset where the layer is gone. Only the comparison at each scroll position sees it: A6 INCOMPLETE "paint changed",
    never PASS (the read after all evidence, at the last offset, equals the first read)."""
    body, style = LAYER
    anim = (" .gap { height: 1200px; } .bg { animation: mid linear both; animation-timeline: scroll(root); }"
            " @keyframes mid { 0%, 19% { scale: 1; } 20%, 90% { scale: 0; } 91%, 100% { scale: 1; } }")
    html = xpage('<div class="gap"></div>' + body + '<div class="gap"></div><p>End of the page.</p>', style + anim)
    code, items, out, _, _ = cp(X, html)
    # the probe paragraph's path is html > body > main > div:nth-of-type(2) > p; the page's other p has no div (X3)
    assert code != 0 and has(items, "A6", "INCOMPLETE", word="paint changed", path="div"), out
    assert not_a_pass(items, "A6", "div"), out


def test_a6_layer_moved_only_by_its_offset_in_the_middle_of_the_scroll_range_is_not_a_pass(X):
    """Y1 (HQ's C2, isolated; HQ's probe scroll_mid_top with the layer's size fixed): the ink layer keeps its size (top,
    left, width and height set, bottom and right auto) and a scroll-driven animation moves it away by top alone in the
    middle of the scroll range; at offset 0 and at the last offset it is back. No paint property but its offsets
    changes (with inset: 0, as in scroll_mid_top, its height moved with top and gave the change away), so only the
    offsets in the paint list, compared at each scroll position, see it: A6 INCOMPLETE "paint changed", never PASS."""
    body, style = LAYER
    anim = (" .gap { height: 1200px; } .bg { inset: auto; top: 0px; left: 0px; width: 100%; height: 100%;"
            " animation: midtop linear both; animation-timeline: scroll(root); }"
            " @keyframes midtop { 0%, 19% { top: 0px; } 20%, 90% { top: -5000px; } 91%, 100% { top: 0px; } }")
    html = xpage('<div class="gap"></div>' + body + '<div class="gap"></div><p>End of the page.</p>', style + anim)
    code, items, out, _, _ = cp(X, html)
    # the probe paragraph's path is html > body > main > div:nth-of-type(2) > p; the page's other p has no div (X3)
    assert code != 0 and has(items, "A6", "INCOMPLETE", word="paint changed", path="div"), out
    assert not_a_pass(items, "A6", "div"), out


@pytest.mark.parametrize("extra,label", [
    ("@media (prefers-reduced-motion: reduce) { .bg { display: none; } }", "prefers-reduced-motion: no-preference"),
    (".bg { display: none; } @media (prefers-contrast: more) { .bg { display: block; } }", "prefers-contrast: more"),
    (".bg { display: none; } @media (prefers-contrast: less) { .bg { display: block; } }", "prefers-contrast: less"),
    (".bg { display: none; } @media (prefers-reduced-transparency: reduce) { .bg { display: block; } }", "prefers-reduced-transparency: reduce"),
    (".bg { display: none; } @media (prefers-reduced-motion: no-preference) and (prefers-contrast: more) { .bg { display: block; } }",
     "prefers-reduced-motion: no-preference, prefers-contrast: more"),
], ids=["hidden for reduced motion", "drawn for more contrast", "drawn for less contrast", "drawn for reduced transparency",
        "drawn for two preferences at once"])
def test_a6_layer_that_depends_on_a_reader_preference_is_not_a_pass(X, extra, label):
    """W1 (HQ's probes reduced_motion and contrast_more, and the other states): the ink layer behind the ink text is
    hidden in the evidence state (reduced motion, no contrast or transparency preference) and drawn for readers with
    another preference, or two at once: the fresh load in that state paints differently, so A6 is INCOMPLETE naming the
    state, never PASS. GOOD_X, GOOD_Y and GOOD_Z (test_correct_pages_pass) are the controls: they still pass."""
    body, style = LAYER
    code, items, out, _, _ = cp(X, xpage(body, style + " " + extra))
    # the probe paragraph's path is html > body > main > div > p: the only text run under a div (X3)
    hit = has(items, "A6", "INCOMPLETE", word="paints differently for readers with another preference", path="div")
    assert code != 0 and hit and label in hit[0]["detail"], out
    assert not_a_pass(items, "A6", "div"), out


@pytest.mark.parametrize("extra", [
    "@media (prefers-contrast: more) { .box { box-shadow: inset 0 0 0 2000px var(--ink); } }",
    ".box { position: static; } @media (prefers-contrast: more) { .box { border: 40px solid var(--ink); } }",
    "@media (prefers-contrast: more) { .box { outline: 2000px solid var(--ink); outline-offset: -2000px; } }",
    ".box { background-image: linear-gradient(var(--ink), var(--ink)); background-repeat: no-repeat; background-size: 0 0; }"
    " @media (prefers-contrast: more) { .box { background-size: 100% 100%; } }",
], ids=["contrast_shadow", "border over a static box", "outline", "background-size"])
def test_a6_paint_outside_the_old_list_drawn_only_for_more_contrast_is_not_a_pass(X, extra):
    """X1 (HQ's probes contrast_shadow and contrast_bgsize, a border and an outline variant): with no layer at all, ink
    is drawn behind the ink text only for readers who asked for more contrast, by a property PAINTS did not read before
    (box-shadow, border, outline, background-size): the fresh load in that state paints differently, so A6 is INCOMPLETE
    naming it, never PASS. GOOD_X, GOOD_Y and GOOD_Z (test_correct_pages_pass) are the controls."""
    body, style = LAYER
    code, items, out, _, _ = cp(X, xpage(body, style + " .bg { display: none; } " + extra))
    hit = has(items, "A6", "INCOMPLETE", word="paints differently for readers with another preference", path="div")
    assert code != 0 and hit and "prefers-contrast: more" in hit[0]["detail"], out
    assert not_a_pass(items, "A6", "div"), out


SHADOW_STACK = ", ".join(["inset 0 0 0 2000px rgba(26, 26, 46, 0.08)"] * 60)      # site X's approved card shadow, 60 times


@pytest.mark.parametrize("body,style,word", [
    # HQ's shadow_stack and shadow_always are composed since TASK-CC-08 (U2): test_a6_solid_shadow_band_under_the_text_fails
    ('<div class="s"></div><p class="probe">Ink text under an earlier sibling\'s shadow.</p>',
     ".s { height: 10px; box-shadow: 0 0 0 40px rgba(26, 26, 46, 0.08); } .probe { color: var(--ink); margin: 20px 0 0; }",
     "a shadow paints under the text"),
    ('<div class="o"></div><p class="probe">Ink text under an earlier sibling\'s outline.</p>',
     ".o { height: 10px; outline: 80px solid var(--accent); outline-offset: -20px; } .probe { color: var(--ink); margin: 20px 0 0; }",
     "an outline is drawn over the text"),
], ids=["sibling outer spread shadow", "sibling outline"])
def test_a6_paint_hit_testing_never_sees_under_the_text_is_not_a_pass(X, body, style, word):
    """X2 (an earlier sibling's outer spread shadow; a sibling's outline reaching past its box at a negative offset):
    axe ignores box-shadow and outlines and hit testing never sees them, so A6 is INCOMPLETE naming the painter, never
    PASS. Controls: test_card_with_its_own_outer_shadow_passes and test_correct_pages_pass."""
    code, items, out, _, _ = cp(X, xpage(body, style))
    assert code != 0 and has(items, "A6", "INCOMPLETE", word=word, path="> p"), out
    assert not_a_pass(items, "A6", "> p"), out


HONEST_CARDS = ("<h1>Weekly progress</h1><p>Three short updates, written plainly.</p>"       # HQ's honest pages (probe_cc07.py)
                + "".join('<div class="card"><p>Update %d: the work moved on and nothing is blocked.</p></div>' % i for i in range(3))
                + '<p>Read the full notes below.</p><a class="link" href="#top">Back to top</a>')
CARD_SHADOW = "box-shadow: 0 2px 8px rgba(26, 26, 46, 0.08);"
UNDERLINE = ".link { box-shadow: inset 0 -1px 0 rgba(26, 26, 46, 0.08); }"


@pytest.mark.parametrize("body,style,path,ratio", [
    (LAYER[0], LAYER[1] + " .bg { display: none; } .box { box-shadow: %s; }" % SHADOW_STACK, "div > p", "ratio 1.0"),
    (LAYER[0], LAYER[1] + " .bg { display: none; } .box { box-shadow: inset 0 0 0 2000px var(--ink); }", "div > p", "ratio 1.0"),
    (LAYER[0], LAYER[1] + " .bg { display: none; } .probe { box-shadow: inset 0 -8px 0 var(--ink); }", "div > p", "ratio 1.0"),
    (HONEST_CARDS, ".card { %s margin: 24px 0; } %s" % (CARD_SHADOW, UNDERLINE), "> a", "ratio 4.3"),
], ids=["shadow_stack", "shadow_always", "ink band under ink text", "honest_link_underline"])
def test_a6_solid_shadow_band_under_the_text_fails(X, body, style, path, ratio):
    """U2 (TASK-CC-08): a solid inset band of the text's element or an ancestor is composed exactly into the backdrop.
    HQ's shadow_stack (60 inset spreads of the approved 8 % ink card shadow), shadow_always, and a solid ink band under
    ink text: the composed backdrop is (near) ink: A6 FAIL, never PASS. HQ's honest_link_underline: the accent link
    (5.09 on paper) over its own 8 % ink underline band gives 4.34, below 4.5: A6 FAIL on the link, by the CEO's choice
    «Считать точно (Recommended)» ("compute exactly"). The control is test_link_with_a_solid_underline_band_passes."""
    code, items, out, _, _ = cp(X, xpage(body, style))
    hit = has(items, "A6", "FAIL", word="solid shadow band", path=path)
    assert code == 1 and hit and ratio in hit[0]["detail"], out
    assert not_a_pass(items, "A6", path), out


def test_link_with_a_solid_underline_band_passes(X):
    """U2 control: HQ's honest cards with the same solid underline band under a link whose colour keeps the contrast
    over it (ink: about 15 over the band): exit 0, as is HQ's honest_cards page without the underline."""
    style = ".card { %s margin: 24px 0; } %s .link { color: var(--ink); }" % (CARD_SHADOW, UNDERLINE)
    code, items, out, _, _ = cp(X, xpage(HONEST_CARDS, style))
    assert code == 0, out


BLOB = ("width: 120px; height: 120px; border-radius: 50%; background: var(--paper); filter: blur(30px);")    # HQ's honest_blob


def _a6_open(items):
    return [i for i in items if i["check"] == "A6" and i["status"] in ("FAIL", "INCOMPLETE")]


def test_a6_blur_far_from_every_text_passes(X):
    """U1 (TASK-CC-08): HQ's decorative circle with filter: blur(30px) placed where no text lies within its reach (its
    box grown by 3 x 30 + 1 px) at either width: exit 0; the frame-wide rule of X2 gave every run INCOMPLETE."""
    style = ".card { margin: 24px 0; } .blob { position: absolute; top: 1600px; right: 0; %s }" % BLOB
    code, items, out, _, _ = cp(X, xpage('<div class="blob"></div>' + HONEST_CARDS, style))
    assert code == 0 and not _a6_open(items), out


def test_a6_corner_blur_counts_only_near_itself(X):
    """U1, HQ's honest_blob (the circle at the top right corner of the page): at 1280 px no text lies within its reach,
    so no A6 item there; at 390 px the heading and the first lines lie within 91 px of it, and only runs that near may be
    INCOMPLETE, by the filter's reach, never the later cards, the last paragraph or the link (X2 gave all 28 runs of the
    four renders INCOMPLETE). Exit 0 or 3, never 1."""
    style = ".blob { position: absolute; top: 0; right: 0; %s }" % BLOB
    code, items, out, _, _ = cp(X, xpage('<div class="blob"></div>' + HONEST_CARDS, style))
    open_ = _a6_open(items)
    assert code in (0, 3) and all(i["status"] == "INCOMPLETE" and "a filter of" in i["detail"] for i in open_), out
    assert not [i for i in open_ if str(i.get("render", "")).startswith("w1280")], out
    far = ("div:nth-of-type(3) > p", "div:nth-of-type(4) > p", "p:nth-of-type(2)", "main > a")      # the blob is div 1
    assert not [i for i in open_ if any(f in i["path"] for f in far)], out


def test_a6_blur_under_a_paragraph_is_incomplete_on_that_paragraph_only(X):
    """U1: the same circle moved under one paragraph (behind it, in its own stacking context, so hit testing and axe see
    only its unblurred paper background) gives A6 INCOMPLETE by the filter's reach on that paragraph only; the cards
    above and the paragraph below lie 400 px away."""
    body = (HONEST_CARDS + '<div style="height:400px"></div><section class="bw"><div class="blob"></div>'
            "<p>Text over a blurred decorative circle.</p></section><div style=\"height:400px\"></div><p>End of the page.</p>")
    style = (".card { margin: 24px 0; } .bw { position: relative; z-index: 0; }"
             " .blob { position: absolute; z-index: -1; top: 0; left: 0; %s }" % BLOB)
    code, items, out, _, _ = cp(X, xpage(body, style))
    open_ = _a6_open(items)
    assert code == 3 and has(items, "A6", "INCOMPLETE", word="a filter of", path="section > p"), out
    assert all("section > p" in i["path"] for i in open_), out


LATE = "@keyframes late { to { %s } }"


@pytest.mark.parametrize("body,style,path,word", [
    ('<div class="g"><div class="pz"><p class="probe">Ink text in a layer beneath an ink band.</p></div></div>',
     ".g { box-shadow: inset 0 0 0 2000px var(--ink); } .pz { position: relative; z-index: -1; background: var(--paper); }"
     " .probe { color: var(--ink); }", "div > p", "negative z-index"),
    (HONEST_CARDS, UNDERLINE + " .link { color: var(--ink); animation: late 600s step-end both; } "
     + LATE % "box-shadow: inset 0 0 0 2000px var(--ink);", "> a", "animated"),
    ('<div class="blob"></div>' + HONEST_CARDS, ".blob { position: absolute; top: 1600px; right: 0; %s animation: late 600s step-end both; } "
     % BLOB + LATE % "filter: drop-shadow(var(--ink) 0px -1600px 0px);", "> p", "is animated"),
], ids=["text beneath an ancestor's band", "underline band animated after ten minutes", "blur animated after ten minutes"])
def test_a6_narrowed_paints_never_reopen_an_attack(X, body, style, path, word):
    """U1, U2 (TASK-CC-08: never reopen a closed attack): what X2 gave INCOMPLETE, the narrowed rules must not pass.
    Text in a stacking layer with a negative z-index under an ancestor's opaque ink inset band is painted beneath the
    band (the reader sees ink): not composed. A link's solid underline band, or a far blurred circle, animated to paint
    ink over the text only after ten minutes: the animation is found, so neither is composed nor narrowed. A6 not PASS
    on the text, never exit 0."""
    code, items, out, _, _ = cp(X, xpage(body, style))
    hit = [i for i in items if i["check"] == "A6" and i["status"] in ("INCOMPLETE", "FAIL") and path in i["path"]]
    assert code != 0 and [i for i in hit if word in i["detail"]], out
    assert not_a_pass(items, "A6", path), out


def test_card_with_its_own_outer_shadow_passes(X):
    """X2 control: a card's own outer shadow (site X's approved card shadow) never paints inside the card, so the card's
    text still passes; the card's margins keep the shadow's reach (offset, spread and 1.5 x blur) off the text around it."""
    html = GOOD_X.replace("</style>", ".card { box-shadow: 0 4px 12px rgba(26, 26, 46, 0.08); margin: 32px 0; } </style>")
    code, items, out, _, _ = cp(X, html)
    assert code == 0, out


def test_a6_text_under_an_ancestor_filter_is_not_a_pass(X):
    """The CEO's decision of 2026-11-12 (found during TASK-CC-07): axe-core composes no CSS filter, so its pass on the
    card's text under filter: brightness(0.15), which the reader sees dark on dark, is never taken: A6 INCOMPLETE naming
    the filter (from the axe-pass branch, or from the fallback's own filter check should axe give no verdict there)."""
    code, items, out, _, _ = cp(X, xpage('<div class="card"><p>Muted text on the paper card.</p></div>', ".card { filter: brightness(0.15); }"))
    assert code != 0 and has(items, "A6", "INCOMPLETE", word="filter", path="div > p"), out
    assert not_a_pass(items, "A6", "div > p"), out


def test_a6_transparent_frame_over_an_ink_area_is_not_a_pass(X):
    """R2-H02(4): a transparent same-bundle frame with ink text, over an ink area of the parent page: the backdrop lies
    outside the frame, so A6 is INCOMPLETE whatever axe says inside the frame."""
    frame = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>f</title><link rel="stylesheet" href="x.css">'
             '<style>html, body { background: transparent !important; margin: 0; }</style></head>'
             '<body><p style="color: var(--ink)">Ink text in a transparent frame.</p></body></html>')
    html = xpage('<div style="background: var(--ink); padding: 8px"><iframe title="f" src="frame.html" style="border: 0; width: 600px; height: 80px"></iframe></div>')
    code, items, out, _, _ = cp(X, html, files={"frame.html": frame})
    assert code != 0 and has(items, "A6", "INCOMPLETE", word="backdrop lies outside the frame"), out


def test_render_leaves_every_document_unchanged_and_the_viewport_its_size(X, tmp_path):
    """R2-H02(1, 2), the property itself: one render's whole evidence sequence (COLLECT, every scroll position, axe,
    overlap, CDP fonts, captures, A12) leaves each frame's documentElement.outerHTML byte-equal and the viewport its
    size; the page was scrolled (more than one position)."""
    pytest.importorskip("playwright")
    import threading
    import check_page
    from playwright.sync_api import sync_playwright
    body, style = LAYER
    html = xpage(body + '<iframe title="f" srcdoc="&lt;p&gt;Frame text.&lt;/p&gt;"></iframe><div style="height:2400px"></div><p>Below.</p>',
                 style + " .probe { pointer-events: none; }")
    stage, out = tmp_path / "stage", tmp_path / "out"
    stage.mkdir()
    out.mkdir()
    files = {"index.html": html.encode("utf-8"), "x.css": open(os.path.join(os.path.dirname(X), "site", "x.css"), "rb").read(),
             "fonts/x.ttf": sites.font_bytes("x")}
    for rel, data in files.items():
        os.makedirs(os.path.dirname(str(stage / rel)), exist_ok=True)
        (stage / rel).write_bytes(data)
    log = []
    srv = check_page.make_server(str(stage), log, {k: sites.hashlib.sha256(v).hexdigest() for k, v in files.items()})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    origin = "http://127.0.0.1:%d" % srv.server_address[1]
    axe_src = open(os.path.join(sites.SCRIPTS, "vendor", "axe-core", "axe.min.js"), encoding="utf-8").read()
    job = {"selectors": {"labels": [], "headings": [], "measure": [], "buttons": [".button-primary"]}, "tags": ["wcag2a", "wcag2aa"], "out": str(out)}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
            page = ctx.new_page()
            page.goto(origin + "/index.html", wait_until="load")
            before = [f.evaluate("() => document.documentElement.outerHTML") for f in page.frames]
            result = {"truncated": [], "screenshots": []}
            rd = check_page.render_evidence(ctx, page, origin, job, ("w1280-light", 1280, 800, "light"), axe_src, result, {"bytes": 0})
            after = [f.evaluate("() => document.documentElement.outerHTML") for f in page.frames]
            size = page.evaluate("() => [innerWidth, innerHeight]")
            browser.close()
    finally:
        srv.shutdown()
    assert before == after, "the checker changed a checked document"
    assert size == [1280, 800], size
    assert len(rd["positions"]) > 1 and len(result["screenshots"]) == len(rd["positions"]), (rd["positions"], result)


def test_a6_sibling_layer_without_a_trick_is_an_overlap(X):
    """Control for HQ's V4 (unchanged by the fix): the same layer with nothing reacting to the checker is an overlap."""
    body, style = LAYER
    code, items, out, _, _ = cp(X, xpage(body, style))
    assert code == 3 and has(items, "A6", "INCOMPLETE", word="overlap", path="> p"), out
    assert not has(items, "A6", "INCOMPLETE", word="paint changed"), out


def test_a6_display_contents_text_is_a_run(X):
    """AST-H04: text in an element with display: contents is drawn: it gets an A6 verdict on its element, a FAIL or,
    where axe gives no color-contrast result for it (Chromium; HQ's V1), an INCOMPLETE; never no verdict."""
    code, items, out, _, _ = cp(X, xpage('<div class="c" style="display: contents; color: var(--paper)">Contents text on paper.</div>'))
    assert code in (1, 3) and (has(items, "A6", "FAIL", path="div") or has(items, "A6", "INCOMPLETE", path="div")), out


def test_a6_painting_child_over_the_text_is_an_overlap(X):
    """AUD-F01(1): a positioned child that paints over its parent's text makes the contrast there unknown."""
    body = '<p style="position:relative">Covered text here.<span style="position:absolute;inset:0;background:var(--paper)"></span></p>'
    code, items, out, _, _ = cp(X, xpage(body))
    assert has(items, "A6", "INCOMPLETE", word="overlap"), out


def test_a6_text_fill_colour_is_the_glyph_paint(X):
    """AUD-F01(2): -webkit-text-fill-color paints the glyphs; axe's pass on color is not trusted."""
    code, items, out, _, _ = cp(X, xpage('<p style="color: var(--ink); -webkit-text-fill-color: var(--paper)">Invisible text.</p>'))
    assert code == 1 and has(items, "A6", word="-webkit-text-fill-color"), out


def test_a6_svg_text_uses_fill(X):
    """AUD-F01(3)."""
    code, items, out, _, _ = cp(X, xpage('<p>Chart.</p><svg width="80" height="20"><text x="0" y="15" style="fill: var(--paper)">Label</text></svg>'))
    assert code == 1 and has(items, "A6", word="fill"), out


def test_a2_svg_paint_server_stops(X):
    """AST-H07: a gradient paint server's stop colours are judged (a reserved stop is a floor FAIL)."""
    body = ('<p>Icon.</p><svg width="20" height="20"><defs><linearGradient id="g"><stop offset="0" stop-color="#9a3412"/></linearGradient></defs>'
            '<rect width="20" height="20" fill="url(#g)"/></svg>')
    code, items, out, _, _ = cp(X, xpage(body))
    assert code == 1 and [i for i in has(items, "A2", word="stop-color") if i.get("floor")], out


def test_a1_extensionless_font_with_an_approved_name(X, tmp_path):
    """AST-H06: a served file is a font by its first bytes, and an approved name needs its approved file served."""
    ft = pytest.importorskip("fontTools.ttLib")
    f = ft.TTFont(os.path.join(sites.FONT_DIR, "Poppins-Bold.ttf"))
    for rec in f["name"].names:
        if rec.nameID == 6:
            rec.string = "Poppins-Regular"
    renamed = str(tmp_path / "renamed.ttf")
    f.save(renamed)
    style = '@font-face { font-family: "Inter Test"; src: url("face.bin"); } p { font-family: "Inter Test"; }'
    code, items, out, _, _ = cp(X, xpage("<p>Text.</p>", style), files={"face.bin": open(renamed, "rb").read()}, drop=["fonts/x.ttf"])
    assert has(items, "A1", word="is not an approved face file", path="face.bin") and has(items, "A1", word="approved file was not served"), out


def test_a7_and_a4_read_layout_sizes(X):
    """AST-M13: a scaled reading box keeps its layout width; a rotated fill keeps its layout area."""
    code, items, out, _, _ = cp(X, xpage('<p style="width:681px;transform:scale(0.5);transform-origin:0 0">Scaled reading text.</p>',
                                         ".wrap { max-width: none; }"))
    assert has(items, "A7"), out
    code, items, out, _, _ = cp(X, xpage('<div style="width:50px;height:50px;background:var(--accent);transform:rotate(45deg)"></div><p>Fill.</p>'))
    assert not has(items, "A4"), out


def test_a8_and_a12_run_in_dark_renders(X):
    """AST-M14, AST-M15: capitals and accessibility rules that appear only in the dark scheme are found."""
    style = (".x { display: none; } p.u { } @media (prefers-color-scheme: dark) { p.u { text-transform: uppercase; } .x { display: inline; } }")
    body = '<p class="u">Shouting only at night.</p><img class="x" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="10" height="10">'
    code, items, out, _, _ = cp(X, xpage(body, style))
    assert [i for i in has(items, "A8") if i.get("render", "").endswith("dark")], out
    assert [i for i in has(items, "A12") if i.get("rule") == "image-alt" and i.get("render", "").endswith("dark")], out


def test_a13_field_owned_by_form_attribute(X, tmp_path):
    """AST-M16: a field outside the form's subtree but owned by form="..." is part of the structure."""
    old = xpage('<form id="f" action="/send" method="post"><button>Send</button></form><input form="f" name="who" type="text"><p>Text.</p>')
    snap = str(tmp_path / "snap.json")
    cp(X, old, extra=["--snapshot", snap])
    assert any(e.startswith("field|") and "|who|" in e for e in json.load(open(snap))["entries"]), open(snap).read()
    code, items, out, _, _ = cp(X, old.replace('<input form="f" name="who" type="text">', ""), extra=kept(snap))
    assert [i for i in has(items, "A13") if i["path"].startswith("field|")], out


def test_a13_image_submit_button_is_a_field(X, tmp_path):
    """HQ's C3: form.elements leaves out <input type="image">; the snapshot lists it from the form's subtree."""
    html = xpage('<form action="/go"><input name="q" type="text"><input type="image" name="go" alt="Go" '
                 'src="data:image/gif;base64,R0lGODlhAQABAAAAACw="></form><p>Text.</p>')
    snap = str(tmp_path / "snap-image.json")
    cp(X, html, extra=["--snapshot", snap])
    entries = json.load(open(snap))["entries"]
    assert any(e.startswith("field|") and "|go|image" in e for e in entries) and any("|q|text" in e for e in entries), entries


def test_repository_free_copy_with_the_receipt_fingerprint(tmp_path):
    """AST-H08: check_page.py takes --receipt-sha256 like check_css.py."""
    d = sites.build_x(tmp_path / "src")
    sites.issue(d)
    staged = tmp_path / "staged" / "X"
    shutil.copytree(os.path.dirname(d), staged, ignore=shutil.ignore_patterns(".git"))
    sd = str(staged / "design")
    fp = sites.hashlib.sha256(open(os.path.join(d, "ready.json"), "rb").read()).hexdigest()
    code, items, out, _, _ = cp(sd, GOOD_X)
    assert code == 3 and "--receipt-sha256" in out, out
    code, items, out, _, _ = cp(sd, GOOD_X, extra=["--receipt-sha256", fp])
    assert code == 0, out


# ================================================================== outside audit round 2 (Sol 6.1), in the browser

def test_a1_aliased_replacement_font_never_passes(X):
    """R2-H04: a stylesheet fetches a replacement font through an aliased URL (an encoded '/' and a dot segment) while
    the page also fetches the approved face: the alias is refused (404, A10) and A1 never gives PASS for the replacement."""
    style = ('@font-face { font-family: "Rep"; src: url("fonts%2f.%2freplacement.ttf") format("truetype"); }'
             ' .r { font-family: "Rep", sans-serif; }')
    html = xpage('<p>Approved text in the approved face.</p><p class="r">Replacement text.</p>', style=style)
    code, items, out, rep, _ = cp(X, html, files={"fonts/replacement.ttf": sites.font_bytes("z")})
    assert code != 0, out
    assert not [i for i in items if i["check"] == "A1" and i["status"] == "PASS" and "replacement" in i["path"] + i["detail"]], out
    assert has(items, "A10", word="not in the staged closure"), out


def test_a6_svg_text_fill_opacity_is_composed(X):
    """R2-H03(1) (HQ's probe h03): SVG text in the ink colour with fill-opacity 0.01 on paper is about 1.02:1: A6 is
    never PASS (FAIL expected)."""
    body = ('<svg width="400" height="60" style="background: var(--paper)"><text x="10" y="40" font-size="24" '
            'style="fill: var(--ink); fill-opacity: 0.01">Nearly invisible SVG text</text></svg>')
    code, items, out, _, _ = cp(X, xpage(body))
    assert code != 0 and (has(items, "A6", "FAIL", path="text") or has(items, "A6", "INCOMPLETE", path="text")), out
    assert not_a_pass(items, "A6", "text"), out


def test_a2_paints_that_escaped_the_floor(X):
    """R2-H05 (HQ's probe h05): the rect fill="url(#missing) #9a3412" paints X's reserved old-accent (A2 FAIL); a
    color(srgb 0.6 0.2 0.07) background gives an A2 item that is not PASS; a color(display-p3 ...) background gives A2
    INCOMPLETE (not converted exactly)."""
    body = ('<svg width="200" height="60"><rect width="200" height="60" fill="url(#missing) #9a3412"/></svg>'
            '<div class="s" style="background-color: color(srgb 0.6 0.2 0.07); height: 20px"></div>'
            '<div class="p3" style="background-color: color(display-p3 0.6 0.2 0.07); height: 20px"></div><p>Text</p>')
    code, items, out, _, _ = cp(X, xpage(body))
    assert code == 1 and has(items, "A2", "FAIL", word="reserved", path="rect"), out
    assert has(items, "A2", "FAIL", path="div:nth-of-type(1)") or has(items, "A2", "INCOMPLETE", path="div:nth-of-type(1)"), out
    assert has(items, "A2", "INCOMPLETE", path="div:nth-of-type(2)"), out


def test_a13_field_is_credited_to_its_owner_only(X, tmp_path):
    """R2-M09: a field inside form A's subtree that names form B (form="B") is credited to B only; an image submit button
    outside B's subtree owned by B is listed under B, and its removal gives A13 FAIL."""
    html = xpage('<form id="A" action="/a"><input name="inside" form="B" type="text"><button>A</button></form>'
                 '<form id="B" action="/b"><button>B</button></form>'
                 '<input type="image" name="go" form="B" alt="Go" src="data:image/gif;base64,R0lGODlhAQABAAAAACw="><p>Text.</p>')
    snap = str(tmp_path / "snap-owner.json")
    code, items, out, _, _ = cp(X, html, extra=["--snapshot", snap])
    entries = json.load(open(snap))["entries"]
    assert "field|/b|inside|text" in entries and not [e for e in entries if e.startswith("field|/a|inside")], entries
    assert "field|/b|go|image" in entries, entries
    sha = sites.hashlib.sha256(open(snap, "rb").read()).hexdigest()
    assert sha in out, out                                  # the --snapshot run prints the digest to give with --kept
    code, items, out, _, _ = cp(X, html.replace('<input type="image" name="go" form="B" alt="Go" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">', ""),
                                extra=kept(snap))
    assert code == 1 and [i for i in has(items, "A13") if i["path"] == "field|/b|go|image"], out


def test_a11_identifies_buttons_by_paint_alone(tmp_path):
    """R2-M06: a paint-only profile (no button selectors) identifies primary buttons by their paint signature in A11:
    two ink-on-paper links in one window are counted (A11 is advisory: WARN)."""
    d = sites.build_x(tmp_path)
    import yaml
    pol = yaml.safe_load(open(os.path.join(d, "policy.yaml"), encoding="utf-8"))
    pol["buttons"]["selectors"] = []
    open(os.path.join(d, "policy.yaml"), "w", encoding="utf-8", newline="\n").write(yaml.safe_dump(pol, sort_keys=False, allow_unicode=True))
    sites.issue(d)
    body = ('<p>Two primary actions.</p><a class="b" href="#a">One</a> <a class="b" href="#b">Two</a>')
    code, items, out, _, _ = cp(d, xpage(body, ".b { background: var(--ink); color: #fffdf7; padding: 8px; }"))
    assert [i for i in items if i["check"] == "A11" and i["status"] in ("WARN", "FAIL") and "2 primary buttons" in i["detail"]], out
