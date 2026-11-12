"""Synthetic site profiles for the tests (plan 0.4 B.9): X (CSS-first, light-only, an accent, a reserved
token), Y (design-first, both schemes, no accent, nothing reserved), Z (CSS-first, dark-only).
Each builder writes <tmp>/<name>/design (the site design folder) and <tmp>/<name>/site (its deploy root)."""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)

FONT_DIR = "/usr/share/fonts/truetype/google-fonts"
# Real font files (SIL OFL fonts installed in the cloud sandbox), read at test time, never shipped with the plugin.
FONTS = {"x": ("Poppins-Regular.ttf", "Poppins-Regular"), "y": ("Lora-Variable.ttf", "Lora-Regular"),
         "z": ("Poppins-Medium.ttf", "Poppins-Medium")}


def font_bytes(site):
    path = os.path.join(FONT_DIR, FONTS[site][0])
    if not os.path.isfile(path):
        return b"synthetic-font-" + site.encode()
    with open(path, "rb") as fh:
        return fh.read()


def coverage(site):
    """Coverage ranges read from the font's cmap with fontTools (as a profile writer would); ASCII when unavailable."""
    try:
        from fontTools.ttLib import TTFont
        cmap = sorted(TTFont(os.path.join(FONT_DIR, FONTS[site][0])).getBestCmap())
    except Exception:  # noqa: BLE001
        return [[0x20, 0x7E]]
    out, start, prev = [], cmap[0], cmap[0]
    for c in cmap[1:]:
        if c != prev + 1:
            out.append([start, prev])
            start = c
        prev = c
    out.append([start, prev])
    return out


def write(path, text):
    """Write a fixture file; text gets LF line ends on every platform, as the plugin's own writers produce."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(text, bytes) else "w"
    with open(path, mode, **({} if mode == "wb" else {"encoding": "utf-8", "newline": "\n"})) as fh:
        fh.write(text)


X_CSS = """@font-face { font-family: "Inter Test"; src: url("fonts/x.ttf") format("truetype"); }
:root {
  --ink: #1a1a2e;
  --accent: #c2410c;
  --old-accent: #9a3412;
  --paper: #fffdf7;
  --muted: rgba(26, 26, 46, 0.7);
  --gap: 20px;
  --measure: 680px;
}
html, body { background: #fffdf7; color: var(--ink); font-family: "Inter Test", sans-serif; font-size: 16px; line-height: 1.5; }
.hero h1 { font-size: clamp(32px, 5vw, 56px); font-weight: 700; line-height: 1.1; letter-spacing: -0.02em; }
.card { background: var(--paper); border-radius: 12px; padding: 24px; }
.card p { font-size: 15px; line-height: 1.6; color: var(--muted); }
.button { border-radius: 8px; padding: 10px 18px; font-size: 15px; font-weight: 600; }
.button-primary { background: var(--ink); color: #fffdf7; }
.link { color: var(--accent); }
@media (max-width: 600px) { .hero h1 { font-size: 30px; } }
@keyframes pulse { from { opacity: 1; } to { opacity: .5; } }
"""

X_DESIGN = """---
version: alpha
name: Site X
colors:
  ink: "#1a1a2e"
  primary: "{colors.ink}"
  accent: "#c2410c"
  old-accent: "#9a3412"
  paper: "#fffdf7"
  muted: "rgba(26, 26, 46, 0.7)"
typography:
  display:
    fontFamily: Inter Test
    fontSize: 56px
    fontWeight: 700
    lineHeight: "1.1"
    letterSpacing: -0.02em
  body:
    fontFamily: Inter Test
    fontSize: 16px
    lineHeight: "1.5"
  card-text:
    fontFamily: Inter Test
    fontSize: 15px
    lineHeight: "1.6"
  button:
    fontFamily: Inter Test
    fontSize: 15px
    fontWeight: 600
rounded:
  card: 12px
  control: 8px
spacing:
  gap: 20px
  measure: 680px
components:
  card:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.muted}"
    typography: "{typography.card-text}"
    rounded: "{rounded.card}"
    padding: 24px
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.paper}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: 10px 18px
  link:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.accent}"
---

## Overview

Site X is a warm paper page with one ink and one accent.

## Colors

Shadows use `rgba(26, 26, 46, 0.08)` under cards. Borders use {colors.ink} at 20%.
"""

X_MAP = """colors:
  ink: {var: --ink}
  primary: {ref: "{colors.ink}"}
  accent: {var: --accent}
  old-accent: {var: --old-accent}
  paper: {var: --paper}
  muted: {var: --muted}
typography:
  display: {sel: [.hero h1], clamp_expr: "clamp(32px, 5vw, 56px)"}
  body: {sel: [body]}
  card-text: {sel: [.card p]}
  button: {sel: [.button]}
rounded:
  card: {sel: .card, prop: border-radius}
  control: {sel: .button, prop: border-radius}
spacing:
  gap: {var: --gap}
  measure: {var: --measure}
components:
  card:
    backgroundColor: {sel: .card, prop: background, ref: "{colors.paper}"}
    textColor: {sel: .card p, prop: color, ref: "{colors.muted}"}
    typography: {sel: .card p, ref: "{typography.card-text}"}
    rounded: {sel: .card, prop: border-radius, ref: "{rounded.card}"}
    padding: {sel: .card, prop: padding}
  button-primary:
    backgroundColor: {sel: .button-primary, prop: background, ref: "{colors.primary}"}
    textColor: {sel: .button-primary, prop: color, ref: "{colors.paper}"}
    typography: {sel: .button, ref: "{typography.button}"}
    rounded: {sel: .button, prop: border-radius, ref: "{rounded.control}"}
    padding: {sel: .button, prop: padding}
  link:
    backgroundColor: {host: body, own: .link, ref: "{colors.paper}"}
    textColor: {sel: .link, prop: color, ref: "{colors.accent}"}
overrides:
  - {sel: .hero h1, media: "(max-width: 600px)", prop: font-size, value: 30px}
"""

X_CONTRAST = """surfaces:
  light:
    card: [paper]
    button-primary: [primary]
    link: [paper]
baseline: []
"""


X_BUTTONS = {"selectors": [".button-primary"], "paint": {"background": "primary", "text": "paper"}, "max_per_view": 1}


def policy(roles, reserved, extras, font_sha, family, headings, forbidden, fills, scheme, measure_px=680, site="x", buttons=None):
    import yaml
    return yaml.safe_dump({
        "roles": roles, "reserved": reserved, "extras": extras,
        "derived_vars": [],
        "fonts": {"faces": [{"family": family, "file": "../site/fonts/%s.ttf" % site, "sha256": font_sha, "postscript": FONTS[site][1],
                             "weight": [400, 700], "style": "normal", "coverage": coverage(site)}],
                  "stack_vars": [], "fallback_families": [], "code_roles": "system-monospace"},
        "headings": headings, "labels": {"selectors": [], "style": {"max_size_px": 13, "min_weight": 600}},
        "forbidden_text_colours": forbidden, "fills": fills,
        "measure": {"default_px": measure_px, "roles": []}, "capitals": "labels-only", "scheme": scheme,
        "buttons": buttons or X_BUTTONS,
        "accessibility": {"tags": ["wcag2a", "wcag2aa"], "default": "advisory", "tiers": {"html-has-lang": "blocking"}},
        "tiers": {"A3": "blocking", "A4": "waivable", "A5": "blocking"},
        "decisions": ["synthetic test profile"],
    }, sort_keys=False, allow_unicode=True)


def build_x(tmp):
    root = os.path.join(str(tmp), "X")
    d, s = os.path.join(root, "design"), os.path.join(root, "site")
    write(os.path.join(s, "x.css"), X_CSS)
    write(os.path.join(s, "fonts", "x.ttf"), font_bytes("x"))
    write(os.path.join(d, "site.yaml"), "name: site-x\nsource: css\ncss: [../site/x.css]\ndeploy_root: ../site\npolicy_version: 1\n")
    write(os.path.join(d, "DESIGN.md"), X_DESIGN)
    write(os.path.join(d, "trace-map.yaml"), X_MAP)
    write(os.path.join(d, "contrast.yaml"), X_CONTRAST)
    write(os.path.join(d, "waivers.yaml"), "waivers: []\n")
    sha = hashlib.sha256(font_bytes("x")).hexdigest()
    write(os.path.join(d, "policy.yaml"), policy(
        roles={"light": {"color": ["ink", "primary", "muted", "accent", "paper"], "background-color": ["paper", "ink", "primary"],
                         "border-color": ["ink"], "outline-color": ["accent"], "box-shadow": [], "fill": ["ink", "accent"], "stroke": ["ink"]}},
        reserved=["old-accent"],
        extras=[{"id": "card-shadow", "rgb": [26, 26, 46], "alpha": 0.08, "roles": ["box-shadow"],
                 "quote": "Shadows use `rgba(26, 26, 46, 0.08)` under cards."},
                {"id": "ink-border", "rgb": [26, 26, 46], "alpha": 0.2, "roles": ["border"],
                 "quote": "Borders use {colors.ink} at 20%."}],
        font_sha=sha, family="Inter Test",
        headings={"tokens": ["ink"], "accent": {"tokens": ["accent"], "max_share": 0.34, "max_runs": 1}, "selectors": []},
        forbidden=["old-accent"], fills=[{"tokens": ["accent"], "alpha_above": 0.5, "max_area_px2": 2500}],
        scheme={"mode": "light-only", "sets": {"light": ["ink", "primary", "accent", "paper", "muted"]}}))
    write(os.path.join(d, "README.md"), "Site X design folder (synthetic).\n")
    return d


Y_DESIGN = """---
version: alpha
name: Site Y
colors:
  paper-light: "#ffffff"
  ink-light: "#111827"
  paper-dark: "#0b1120"
  ink-dark: "#e5e7eb"
  line: "rgba(17, 24, 39, 0.12)"
typography:
  title:
    fontFamily: Lora Test
    fontSize: 40px
    fontWeight: 600
    lineHeight: "1.2"
  body:
    fontFamily: Lora Test
    fontSize: 18px
    lineHeight: "1.7"
rounded:
  card: 4px
spacing:
  gap: 24px
components:
  card:
    backgroundColor: "{colors.paper-light}"
    textColor: "{colors.ink-light}"
    typography: "{typography.body}"
    rounded: "{rounded.card}"
    padding: 20px
---

## Overview

Site Y is a quiet reading site with a light and a dark scheme.
"""

Y_CONTRAST = """surfaces:
  light:
    card: [paper-light]
  dark:
    card: [paper-dark]
baseline: []
"""


def build_y(tmp):
    import yaml
    import generate_css
    import designlib as dl
    root = os.path.join(str(tmp), "Y")
    d, s = os.path.join(root, "design"), os.path.join(root, "site")
    write(os.path.join(s, "fonts", "y.ttf"), font_bytes("y"))
    write(os.path.join(s, "y.css"), '@font-face { font-family: "Lora Test"; src: url("fonts/y.ttf") format("truetype"); font-weight: 400 700; }\n'
          ".card { background: var(--comp-card-bg); color: var(--comp-card-text); }\n")
    write(os.path.join(d, "site.yaml"), "name: site-y\nsource: design\ncss: [../site/y.css]\ndeploy_root: ../site\npublic_tokens: ../site/tokens.css\npolicy_version: 1\n")
    write(os.path.join(d, "DESIGN.md"), Y_DESIGN)
    write(os.path.join(d, "trace-map.yaml"), "typography:\n  title: {clamp_expr: \"clamp(28px, 4vw, 40px)\"}\n")
    write(os.path.join(d, "contrast.yaml"), Y_CONTRAST)
    write(os.path.join(d, "waivers.yaml"), "waivers: []\n")
    sha = hashlib.sha256(font_bytes("y")).hexdigest()
    write(os.path.join(d, "policy.yaml"), policy(
        roles={"light": {"color": ["ink-light"], "background-color": ["paper-light"], "border-color": ["line"], "outline-color": ["ink-light"],
                         "box-shadow": [], "fill": ["ink-light"], "stroke": ["ink-light"]},
               "dark": {"color": ["ink-dark"], "background-color": ["paper-dark"], "border-color": ["line"], "outline-color": ["ink-dark"],
                        "box-shadow": [], "fill": ["ink-dark"], "stroke": ["ink-dark"]}},
        reserved=[], extras=[], font_sha=sha, family="Lora Test",
        headings={"tokens": ["ink-light", "ink-dark"], "accent": None, "selectors": []},
        forbidden=[], fills={"off": "no limited fills on site Y"},
        scheme={"mode": "both", "sets": {"light": ["paper-light", "ink-light", "line"], "dark": ["paper-dark", "ink-dark", "line"]},
                "pairs": {"paper-light": "paper-dark", "ink-light": "ink-dark"}}, measure_px=640, site="y",
        # its own palette's tokens: Y has no primary or paper token (R2-M06)
        buttons={"selectors": [".button-primary"], "paint": {"background": "ink-light", "text": "paper-light"}, "max_per_view": 1}))
    write(os.path.join(d, "README.md"), "Site Y design folder (synthetic).\n")
    snap = dl.Snapshot()
    fm, _ = dl.split_front_matter(snap.text(os.path.join(d, "DESIGN.md")))
    design = dl.load_yaml_text(fm, "DESIGN.md")
    old = yaml.safe_load(open(os.path.join(d, "trace-map.yaml"), encoding="utf-8"))
    pol = yaml.safe_load(open(os.path.join(d, "policy.yaml"), encoding="utf-8"))
    # the generator's own writer (LF on every platform), as generate_css.py --write uses it (AST-M05)
    generate_css.write_lf(os.path.join(s, "tokens.css"), generate_css.render(design, old, pol, snap.digest(os.path.join(d, "DESIGN.md"))))
    generate_css.write_lf(os.path.join(d, "trace-map.yaml"), yaml.safe_dump(generate_css.render_map(design, old), sort_keys=False))
    return d


Z_CSS = """@font-face { font-family: "Mono Test"; src: url("fonts/z.ttf") format("truetype"); }
:root { --night: #111111; --chalk: #eeeeee; --sun: #facc15; }
html, body { background: #111111; color: var(--chalk); font-family: "Mono Test", monospace; font-size: 17px; line-height: 1.6; }
.panel { background: var(--night); color: var(--chalk); border-radius: 6px; padding: 16px; }
"""

Z_DESIGN = """---
version: alpha
name: Site Z
colors:
  night: "#111111"
  chalk: "#eeeeee"
  sun: "#facc15"
typography:
  body:
    fontFamily: Mono Test
    fontSize: 17px
    lineHeight: "1.6"
rounded:
  panel: 6px
spacing:
  pad: 16px
components:
  panel:
    backgroundColor: "{colors.night}"
    textColor: "{colors.chalk}"
    rounded: "{rounded.panel}"
    padding: 16px
---

## Overview

Site Z is dark only.
"""

Z_MAP = """colors:
  night: {var: --night}
  chalk: {var: --chalk}
  sun: {var: --sun}
typography:
  body: {sel: [body]}
rounded:
  panel: {sel: .panel, prop: border-radius}
spacing:
  pad: {sel: .panel, prop: padding}
components:
  panel:
    backgroundColor: {sel: .panel, prop: background, ref: "{colors.night}"}
    textColor: {sel: .panel, prop: color, ref: "{colors.chalk}"}
    rounded: {sel: .panel, prop: border-radius, ref: "{rounded.panel}"}
    padding: {sel: .panel, prop: padding}
"""


def build_z(tmp):
    root = os.path.join(str(tmp), "Z")
    d, s = os.path.join(root, "design"), os.path.join(root, "site")
    write(os.path.join(s, "z.css"), Z_CSS)
    write(os.path.join(s, "fonts", "z.ttf"), font_bytes("z"))
    write(os.path.join(d, "site.yaml"), "name: site-z\nsource: css\ncss: [../site/z.css]\ndeploy_root: ../site\npolicy_version: 1\n")
    write(os.path.join(d, "DESIGN.md"), Z_DESIGN)
    write(os.path.join(d, "trace-map.yaml"), Z_MAP)
    write(os.path.join(d, "contrast.yaml"), "surfaces:\n  dark:\n    panel: [night]\nbaseline: []\n")
    write(os.path.join(d, "waivers.yaml"), "waivers: []\n")
    sha = hashlib.sha256(font_bytes("z")).hexdigest()
    write(os.path.join(d, "policy.yaml"), policy(
        roles={"dark": {"color": ["chalk", "sun"], "background-color": ["night"], "border-color": ["chalk"], "outline-color": ["sun"],
                        "box-shadow": [], "fill": ["chalk", "sun"], "stroke": ["chalk"]}},
        reserved=[], extras=[], font_sha=sha, family="Mono Test",
        headings={"tokens": ["chalk"], "accent": {"tokens": ["sun"], "max_share": 0.5, "max_runs": 2}, "selectors": []},
        forbidden=[], fills=[{"tokens": ["sun"], "alpha_above": 0.5, "max_area_px2": 1000}],
        scheme={"mode": "dark-only", "sets": {"dark": ["night", "chalk", "sun"]}}, measure_px=760, site="z",
        buttons={"selectors": [".button-primary"], "paint": {"background": "sun", "text": "night"}, "max_per_view": 1}))   # R2-M06
    write(os.path.join(d, "README.md"), "Site Z design folder (synthetic).\n")
    return d


def edit(path, old, new, count=1):
    text = open(path, encoding="utf-8").read()
    assert text.count(old) >= 1, "anchor not found in %s: %r" % (path, old)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text.replace(old, new, count))


def git(cwd, *args):
    import subprocess
    return subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "-c", "init.defaultBranch=main"] + list(args),
                          cwd=cwd, capture_output=True, text=True, check=True)


def commit_receipt(d):
    """The owner's step after --issue: commit ready.json; approval counts only once it is committed (R2-H06)."""
    git(d, "add", "ready.json")
    git(d, "commit", "-qm", "receipt", "--allow-empty")


def issue(d, commit_receipt_too=True):
    """Commit the site design folder (its own repository), issue its receipt and, as the owner does, commit the receipt
    (R2-H06; commit_receipt_too=False leaves it uncommitted); returns the checker's output."""
    import subprocess
    import sys
    if not os.path.isdir(os.path.join(d, ".git")):
        git(d, "init", "-q")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "profile", "--allow-empty")
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(SCRIPTS, "check_design.py"), "--site", d, "--issue"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    if commit_receipt_too:
        commit_receipt(d)
    return r.stdout


def bundle(d, name, page_html, files=None, site_css=True):
    """A bundle folder beside the site design folder: index.html, a copy of the site's CSS (approved) and extra files."""
    root = os.path.dirname(d)
    b = os.path.join(root, "bundles", name)
    os.makedirs(b, exist_ok=True)
    if site_css:
        import shutil
        site = os.path.join(root, "site")
        for f in os.listdir(site):
            if f.endswith(".css"):
                shutil.copy(os.path.join(site, f), os.path.join(b, f))
        if os.path.isdir(os.path.join(site, "fonts")):
            shutil.copytree(os.path.join(site, "fonts"), os.path.join(b, "fonts"), dirs_exist_ok=True)
    write(os.path.join(b, "index.html"), page_html)
    for rel, content in (files or {}).items():
        p = os.path.join(b, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb" if isinstance(content, bytes) else "w") as fh:
            fh.write(content)
    return b
