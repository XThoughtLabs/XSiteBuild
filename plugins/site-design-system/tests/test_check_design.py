"""Tests of designlib.py and check_design.py on synthetic profiles X, Y, Z (plan 0.4 B.9).
Every negative control asserts the check (stage) and the path that must fail."""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import sites  # noqa: E402

CD = os.path.join(sites.SCRIPTS, "check_design.py")
sys.path.insert(0, sites.SCRIPTS)
import designlib as dl  # noqa: E402


def run(d, *extra, cwd=None):
    j = os.path.join(os.path.dirname(d), "report.json")
    r = subprocess.run([sys.executable, "-I", "-B", CD, "--site", d, "--json", j] + list(extra),
                       capture_output=True, text=True, cwd=cwd or os.path.dirname(d), timeout=120)
    items = json.load(open(j))["items"] if os.path.exists(j) else []
    if os.path.exists(j):
        os.remove(j)
    return r.returncode, items, r.stdout + r.stderr


def failed(items, check=None, path=None, status="FAIL"):
    return [i for i in items if i["status"] == status and (check is None or i["check"] == check)
            and (path is None or path in i["path"])]


def F(d, name):
    return os.path.join(d, name)


@pytest.fixture
def X(tmp_path):
    return sites.build_x(tmp_path)


@pytest.fixture
def Y(tmp_path):
    return sites.build_y(tmp_path)


@pytest.fixture
def Z(tmp_path):
    return sites.build_z(tmp_path)


# ------------------------------------------------------------------ the three profiles pass

@pytest.mark.parametrize("builder", [sites.build_x, sites.build_y, sites.build_z])
def test_profiles_pass(tmp_path, builder):
    code, items, out = run(builder(tmp_path))
    assert code == 0, out


# ------------------------------------------------------------------ typed values

@pytest.mark.parametrize("a,b", [("#fff", "#ffffff"), ("#007", "#000077"), ("rgba(7, 29, 70, 0.10)", "rgba(7,29,70,0.1)"),
                                 ("rgb(7 29 70 / 0.56)", "rgba(7, 29, 70, 0.56)"), ("12px 20px", "12px  20px")])
def test_equivalent_spellings(a, b):
    assert dl.same(a, b)


@pytest.mark.parametrize("a,b", [("#001234", "#1234"), ("rgba(7, 29, 70, 0.56)", "rgba(7, 29, 70, 0.563)"), ("12px", "12em")])
def test_different_values(a, b):
    assert not dl.same(a, b)


@pytest.mark.parametrize("value", ["repeat(3, 1fr)", "minmax(0, 1fr)", "cubic-bezier(.22,.72,.22,1)", "counter(x, decimal-leading-zero)",
                                   "translate(1px, 2px)", '"a, b"'])
def test_commas_inside_a_function_are_one_value(value):
    """HQ's V3: a single value whose commas all sit inside a function (or a string) is one item; typed() used to call
    itself on the same string without end."""
    assert dl.typed(value)[0] == "text"
    assert dl.same(value, value) and not dl.same(value, "20px")


def test_top_level_commas_still_make_a_list():
    """Control (passes before and after V3): a comma at the top level makes a list of typed items."""
    assert dl.typed("a,b") == ("list", (("text", "a"), ("text", "b")))


def test_bound_rule_with_function_values_is_checked(X):
    """HQ's V3: a bound selector's rule that also declares grid and animation values with commas inside functions is
    typed whole (AST-M08) and checked, never an internal error."""
    sites.edit(os.path.join(os.path.dirname(X), "site", "x.css"), ".card { background: var(--paper); border-radius: 12px; padding: 24px; }",
               ".card { background: var(--paper); border-radius: 12px; padding: 24px; grid-template-columns: 150px minmax(0, 1fr);"
               " animation: x 2s cubic-bezier(.2,.7,.2,1) infinite; }")
    code, items, out = run(X, "--verify")
    assert code == 0 and "INTERNAL" not in out, out


def test_probe_ratios():
    fg = dl.composite(dl.Colour(7, 29, 70, dl.Decimal("0.56")), (255, 255, 255))
    assert round(dl.ratio(fg, (255, 255, 255)), 4) == 3.9590
    assert round(dl.ratio_8bit(fg, (255, 255, 255)), 4) == 3.9794


@pytest.mark.parametrize("size,weight,large", [(23.9, 400, False), (24, 400, True), ("18.66", 700, False), ("18.67", 700, True), (19, 600, False)])
def test_large_text_boundary(size, weight, large):
    assert dl.is_large(size, weight) is large


# ------------------------------------------------------------------ the 15 trace controls (profile X)

TRACE_CONTROLS = [
    ("swap of two colours", "DESIGN.md", [('ink: "#1a1a2e"', 'ink: "@@"'), ('accent: "#c2410c"', 'accent: "#1a1a2e"'), ('ink: "@@"', 'ink: "#c2410c"')], "colors.ink"),
    ("colour set to a value existing elsewhere", "DESIGN.md", [('accent: "#c2410c"', 'accent: "#9a3412"')], "colors.accent"),
    ("radius set to a value existing elsewhere", "DESIGN.md", [("  card: 12px", "  card: 8px")], "rounded.card"),
    ("wrong component colour alias", "DESIGN.md", [('textColor: "{colors.muted}"', 'textColor: "{colors.ink}"')], "components.card.textColor"),
    ("wrong component typography alias", "DESIGN.md", [('typography: "{typography.button}"', 'typography: "{typography.card-text}"')], "components.button-primary.typography"),
    ("invented component literal", "DESIGN.md", [("    padding: 24px", "    padding: 26px")], "components.card.padding"),
    ("deleted typography property", "DESIGN.md", [("    letterSpacing: -0.02em\n", "")], "typography.display.letterSpacing"),
    ("deleted component field", "DESIGN.md", [("    padding: 10px 18px\n", "")], "components.button-primary.padding"),
    ("changed mobile-only value", "trace-map.yaml", [("value: 30px", "value: 31px")], "override .hero h1"),
    ("mobile value set to the desktop one", "../site/x.css", [("{ .hero h1 { font-size: 30px; } }", "{ .hero h1 { font-size: 56px; } }")], "override .hero h1"),
    ("fluid upper bound replaced by its lower bound", "DESIGN.md", [("    fontSize: 56px", "    fontSize: 32px")], "typography.display.fontSize"),
    ("changed host surface", "DESIGN.md", [('  link:\n    backgroundColor: "{colors.paper}"', '  link:\n    backgroundColor: "{colors.ink}"')], "components.link.backgroundColor"),
    ("new colour without a binding", "DESIGN.md", [('  paper: "#fffdf7"', '  paper: "#fffdf7"\n  extra: "#123456"')], "colors.extra"),
    ("malformed YAML", "DESIGN.md", [('  accent: "#c2410c"', '  accent: [unclosed, "#c2410c"')], "parse"),
    ("duplicate top-level key", "DESIGN.md", [("rounded:\n", 'colors:\n  ink: "#000000"\nrounded:\n')], "parse"),
]


@pytest.mark.parametrize("name,fname,edits,path", TRACE_CONTROLS, ids=[c[0] for c in TRACE_CONTROLS])
def test_trace_controls_fail(X, name, fname, edits, path):
    for old, new in edits:
        sites.edit(os.path.normpath(F(X, fname)), old, new)
    code, items, out = run(X)
    assert code == 1, out
    assert failed(items, path=path), out


def test_hex_collision_fails(X):
    sites.edit(F(X, "../site/x.css"), "--ink: #1a1a2e;", "--ink: #001234;")
    sites.edit(F(X, "DESIGN.md"), 'ink: "#1a1a2e"', 'ink: "#1234"')
    code, items, out = run(X)
    assert code == 1 and failed(items, "P1", "colors.ink"), out


def test_equivalent_spelling_in_profile_passes(X):
    sites.edit(F(X, "DESIGN.md"), 'muted: "rgba(26, 26, 46, 0.7)"', 'muted: "rgba(26,26,46,0.70)"')
    sites.edit(F(X, "../site/x.css"), "--paper: #fffdf7;", "--paper: #FFFDF7;")
    code, items, out = run(X)
    assert code == 0, out


# ------------------------------------------------------------------ P2: parse and schemas

@pytest.mark.parametrize("fname,old,new", [
    ("policy.yaml", "reserved:", "reserved: []\nreserved:"),
    ("contrast.yaml", "baseline: []", "baseline: []\nbaseline: []"),
    ("trace-map.yaml", "spacing:\n", "spacing:\n  gap: {var: --gap}\n"),
    ("site.yaml", "name: site-x", "name: site-x\nname: site-x"),
    ("waivers.yaml", "waivers: []", "waivers: []\nwaivers: []"),
    ("DESIGN.md", "  gap: 20px", "  gap: 20px\n  gap: 20px"),
], ids=["policy", "contrast", "trace-map", "site", "waivers", "design"])
def test_duplicate_identical_keys_fail(X, fname, old, new):
    sites.edit(F(X, fname), old, new)
    code, items, out = run(X)
    assert code == 1 and failed(items, "P2", "parse") and "duplicate key" in out, out


@pytest.mark.parametrize("fname,old,new,word", [
    ("contrast.yaml", None, "- just\n- a list\n", "not a mapping"),
    ("DESIGN.md", "rounded:\n  card: 12px\n  control: 8px\n", "rounded: {}\n", "rounded is missing or empty"),
    ("DESIGN.md", '  primary: "{colors.ink}"', '  primary: "{colors.secondary}"\n  secondary: "{colors.primary}"', "cycle"),
    ("DESIGN.md", '    lineHeight: "1.1"', "    lineHeight: 1.1", "quoted string"),
    ("DESIGN.md", "  card: 12px", "  card: 12pt", "dimension"),
    ("DESIGN.md", "  gap: 20px", "  gap_x: 20px", "lowercase"),
    ("DESIGN.md", "---\nversion", "--- \nversion", "first line"),
], ids=["non-mapping", "empty group", "cycle", "bare lineHeight", "pt", "underscore", "front matter"])
def test_parse_controls_fail(X, fname, old, new, word):
    if old is None:
        open(F(X, fname), "w").write(new)
    else:
        sites.edit(F(X, fname), old, new)
    code, items, out = run(X)
    assert code == 1 and word in out, out


def test_too_large_and_too_deep_fail(X, tmp_path):
    open(F(X, "waivers.yaml"), "w").write("waivers: []\n# " + "x" * 1_000_100 + "\n")
    code, _, out = run(X)
    assert code == 1 and "larger than" in out, out
    nested = "a:\n" + "".join("  " * i + "b%d:\n" % i for i in range(1, 23)) + "  " * 23 + "c: 1\n"
    open(F(X, "waivers.yaml"), "w").write("waivers: []\n" + nested)
    code, _, out = run(X)
    assert code == 1 and "nests deeper" in out, out


# ------------------------------------------------------------------ P1 extras

def test_unsupported_at_rule_incomplete(X):
    sites.edit(F(X, "../site/x.css"), ".link {", "@supports (display: grid) { .link { color: red; } }\n.link {")
    code, items, out = run(X)
    assert code == 3 and failed(items, "P1", "css", status="INCOMPLETE"), out


def test_clamp_lower_bound_change_fails(X):
    sites.edit(F(X, "../site/x.css"), "clamp(32px, 5vw, 56px)", "clamp(30px, 5vw, 56px)")
    code, items, out = run(X)
    assert code == 1 and failed(items, "P1", "typography.display.fontSize"), out


def test_clamp_expr_disagreeing_with_upper_bound_fails(X):
    sites.edit(F(X, "trace-map.yaml"), 'clamp_expr: "clamp(32px, 5vw, 56px)"', 'clamp_expr: "clamp(32px, 5vw, 60px)"')
    sites.edit(F(X, "../site/x.css"), "clamp(32px, 5vw, 56px)", "clamp(32px, 5vw, 60px)")
    code, items, out = run(X)
    assert code == 1 and "not the clamp maximum" in out, out


def test_component_typography_mismatch_fails(X):
    sites.edit(F(X, "../site/x.css"), "font-size: 15px; font-weight: 600;", "font-size: 15px; font-weight: 700;")
    code, items, out = run(X)
    assert code == 1 and failed(items, "P1", "components.button-primary.typography.fontWeight"), out


def test_identical_value_under_wrong_selector_fails(X):
    sites.edit(F(X, "trace-map.yaml"), "control: {sel: .button, prop: border-radius}", "control: {sel: .card, prop: border-radius}")
    code, items, out = run(X)
    assert code == 1 and failed(items, "P1", "rounded.control"), out


# ------------------------------------------------------------------ design-first (Y)

def test_design_first_hand_edit_fails(Y):
    sites.edit(F(Y, "../site/tokens.css"), "--color-ink-light: #111827;", "--color-ink-light: #111111;")
    code, items, out = run(Y)
    assert code == 1 and failed(items, "P1", "tokens.css"), out


def test_design_first_new_token_without_regeneration_fails(Y):
    sites.edit(F(Y, "DESIGN.md"), '  line: "rgba(17, 24, 39, 0.12)"', '  line: "rgba(17, 24, 39, 0.12)"\n  extra: "#123456"')
    code, items, out = run(Y)
    assert code == 1 and failed(items, "P1", "tokens.css") and failed(items, "P2", "colors.extra"), out


def test_design_first_dark_block_emitted(Y):
    css = open(F(Y, "../site/tokens.css")).read()
    assert "@media (prefers-color-scheme: dark)" in css and "--color-paper-light: var(--color-paper-dark);" in css


def test_component_typography_needs_selector_once_stylesheets_exist(Y):
    sites.edit(F(Y, "site.yaml"), "policy_version: 1", "policy_version: 1\ncomponent_stylesheets: [../site/y.css]")
    code, items, out = run(Y)
    assert code == 1 and failed(items, "P1", "components.card.typography"), out


# ------------------------------------------------------------------ P3: token contrast

def test_component_failing_on_one_of_two_surfaces(X):
    sites.edit(F(X, "contrast.yaml"), "link: [paper]", "link: [paper, ink]")
    code, items, out = run(X)
    assert code == 1 and failed(items, "P3", "components.link"), out


def test_missing_surface_fails(X):
    sites.edit(F(X, "contrast.yaml"), "    card: [paper]\n", "")
    code, items, out = run(X)
    assert code == 1 and "lists no surface" in out, out


def test_background_not_among_surfaces_fails(X):
    sites.edit(F(X, "contrast.yaml"), "card: [paper]", "card: [ink]")
    code, items, out = run(X)
    assert code == 1 and "not among its listed surfaces" in out, out


def test_translucent_surface_without_opaque_beneath_fails(X):
    sites.edit(F(X, "contrast.yaml"), "card: [paper]", "card: [paper, [muted]]")
    code, items, out = run(X)
    assert code == 1 and "translucent with nothing opaque" in out, out


def _make_link_fail(X):
    sites.edit(F(X, "DESIGN.md"), 'accent: "#c2410c"', 'accent: "#f0a080"')
    sites.edit(F(X, "../site/x.css"), "--accent: #c2410c;", "--accent: #f0a080;")


def test_baseline_kept_passes_and_worse_fails(X):
    _make_link_fail(X)
    code, items, out = run(X)
    assert code == 1 and failed(items, "P3", "components.link"), out
    fg = dl.composite(dl.Colour(240, 160, 128), (255, 253, 247))
    actual = dl.ratio(fg, (255, 253, 247))
    entry = ("  - {component: link, scheme: light, text: \"{colors.accent}\", surface: paper, method: fractional, ratio: %.4f, decision: test,"
             " text_colour: \"#f0a080\", surface_colour: \"#fffdf7\"}\n")
    open(F(X, "contrast.yaml"), "w").write(sites.X_CONTRAST.replace("baseline: []\n", "baseline:\n" + entry % (int(actual * 10000) / 10000)))
    code, items, out = run(X)
    assert code == 0, out
    open(F(X, "contrast.yaml"), "w").write(sites.X_CONTRAST.replace("baseline: []\n", "baseline:\n" + entry % (actual + 0.001)))
    code, items, out = run(X)
    assert code == 1 and "worse than its baseline" in out, out


def test_baseline_with_changed_surface_fails(X):
    _make_link_fail(X)
    entry = "  - {component: link, scheme: light, text: \"{colors.accent}\", surface: ink, method: fractional, ratio: 1.0, decision: test}\n"
    open(F(X, "contrast.yaml"), "w").write(sites.X_CONTRAST.replace("baseline: []\n", "baseline:\n" + entry))
    code, items, out = run(X)
    assert code == 1 and failed(items, "P3", "baseline"), out


def test_yaml_11_booleans_stay_strings():
    assert dl.load_yaml_text("a:\n  off: reason\n  on: x\n  yes: y\n  b: true\n", "t") == {"a": {"off": "reason", "on": "x", "yes": "y", "b": True}}


def test_dark_only_and_both_schemes(Y, Z):
    assert run(Y)[0] == 0 and run(Z)[0] == 0
    sites.edit(F(Y, "contrast.yaml"), "  dark:\n    card: [paper-dark]\n", "")
    code, items, out = run(Y)
    assert code == 1 and "(dark)" in out, out


# ------------------------------------------------------------------ policy

@pytest.mark.parametrize("old,new,word", [
    ("capitals: labels-only\n", "", "section missing"),
    ("reserved:\n- old-accent\n", "reserved:\n  off: none\n", "floor section can never be off"),
    ("capitals: labels-only", "capitals:\n  off: ''", "off needs a reason"),
    ("\ntiers:\n", "\ntiers:\n  A1: waivable\n", "floor assertion has no tier"),
    ("  tiers:\n    html-has-lang: blocking", "  tiers:\n    color-contrast: advisory", "floor rule; it has no tier"),
    ("reserved:\n- old-accent", "reserved:\n- no-such-token", "unknown token"),
    ("  quote: Shadows use `rgba(26, 26, 46, 0.08)` under cards.", "  quote: Shadows sit under cards.", "quote not found"),
    ("  alpha: 0.08", "  alpha:\n  - 0.08\n  - 0.3", "alpha"),
    ("- id: ink-border", "- id: card-shadow", "duplicate id"),
    ("  - border\n", "  - borders\n", "unknown role borders"),
    ("  alpha: 0.2", "  alpha:\n  - 0.08\n  - 0.2", "overlaps extra card-shadow"),
    ("derived_vars: []", "derived_vars:\n- {name: --nope, roles: [box-shadow]}", ":root declares no --nope"),
], ids=["missing", "floor off", "off no reason", "floor tier", "contrast tier", "unknown token", "quote", "widened range", "dup id",
        "extra role", "overlapping ranges", "derived undeclared"])
def test_policy_controls_fail(X, old, new, word):
    sites.edit(F(X, "policy.yaml"), old, new)
    code, items, out = run(X)
    assert code == 1 and word in out, out


@pytest.mark.parametrize("waiver,word", [
    ("{id: w1, assertion: A4, page: '*', selector: .x, page_sha256: abc, reason: r, owner_words: w, date: '2026-11-10'}", "bare *"),
    ("{id: w2, assertion: A4, page: a.html, selector: .x, page_sha256: abc, reason: r, date: '2026-11-10'}", "lacks owner_words"),
    ("{id: w3, assertion: A4, page: a.html, selector: .x, reason: r, owner_words: w, date: '2026-11-10'}", "lacks page_sha256"),
    ("{id: w4, assertion: A6, page: a.html, selector: .x, page_sha256: abc, reason: r, owner_words: w, date: '2026-11-10'}", "cannot be waived"),
])
def test_bad_waivers_fail(X, waiver, word):
    open(F(X, "waivers.yaml"), "w").write("waivers:\n  - %s\n" % waiver)
    code, items, out = run(X)
    assert code == 1 and word in out, out


def test_derived_variable_values(X):
    sites.edit(F(X, "policy.yaml"), "derived_vars: []", "derived_vars:\n- {name: --shadow, roles: [box-shadow]}")
    sites.edit(F(X, "../site/x.css"), "--gap: 20px;", "--gap: 20px; --shadow: 0 2px 6px rgba(26, 26, 46, 0.08);")
    assert run(X)[0] == 0
    sites.edit(F(X, "../site/x.css"), "rgba(26, 26, 46, 0.08);", "rgba(26, 26, 46, 0.09);")
    code, items, out = run(X)
    assert code == 1 and "not allowed in ['box-shadow']: rgba(26, 26, 46, 0.09)" in out, out


# ------------------------------------------------------------------ boundary, approval, receipt

def test_boundary(X):
    sites.edit(F(X, "site.yaml"), "deploy_root: ../site", "deploy_root: ..")
    code, items, out = run(X)
    assert code == 1 and failed(items, "PUB"), out
    sites.edit(F(X, "site.yaml"), "deploy_root: ..\n", "")
    code, items, out = run(X)
    assert code == 3 and failed(items, "PUB", status="INCOMPLETE"), out


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"] + list(args),
                          cwd=cwd, capture_output=True, text=True, check=True)


def test_verify_writes_nothing_and_issue_needs_commit(X):
    assert run(X, "--verify")[0] == 0 and not os.path.exists(F(X, "ready.json"))
    code, items, out = run(X, "--issue")
    assert code == 3 and not os.path.exists(F(X, "ready.json")), out
    git(X, "init", "-q")
    git(X, "add", ".")
    git(X, "commit", "-qm", "profile")
    code, items, out = run(X, "--issue")
    assert code == 0 and os.path.exists(F(X, "ready.json")), out
    receipt = json.load(open(F(X, "ready.json")))
    assert len(receipt["commit"]) == 40 and set(receipt["profile"]) >= {"policy.yaml", "DESIGN.md"}
    assert any(k.endswith("designlib.py") for k in receipt["plugin_scripts"])
    assert list(receipt["css"]) == ["../site/x.css"] and list(receipt["fonts"]) == ["../site/fonts/x.ttf"]
    os.remove(F(X, "ready.json"))
    sites.edit(F(X, "policy.yaml"), "- synthetic test profile", "- edited after the commit")
    code, items, out = run(X, "--issue")
    assert code == 3 and not os.path.exists(F(X, "ready.json")) and failed(items, "APP", "policy.yaml", status="INCOMPLETE"), out


def test_issue_covers_every_file_of_the_folder(X):
    git(X, "init", "-q")
    git(X, "add", ".")
    git(X, "commit", "-qm", "profile")
    sites.edit(F(X, "README.md"), "synthetic", "synthetic, edited")
    code, items, out = run(X, "--issue")
    assert code == 3 and failed(items, "APP", "README.md", status="INCOMPLETE"), out
    git(X, "checkout", "--", "README.md")
    open(F(X, "notes.txt"), "w").write("untracked\n")
    code, items, out = run(X, "--issue")
    assert code == 3 and failed(items, "APP", "notes.txt", status="INCOMPLETE") and not os.path.exists(F(X, "ready.json")), out
    os.remove(F(X, "notes.txt"))
    code, items, out = run(X, "--issue")
    assert code == 0 and "README.md" in json.load(open(F(X, "ready.json")))["profile"], out


# ------------------------------------------------------------------ entry points

def test_entry_point_from_other_cwd_and_path_with_spaces(tmp_path):
    spaced = tmp_path / "a folder with spaces"
    d = sites.build_x(spaced)
    code, items, out = run(d, cwd="/")
    assert code == 0, out


def test_missing_pyyaml_gives_error(X, monkeypatch, capsys):
    import check_design
    monkeypatch.setattr(dl, "yaml", None)
    code = check_design.main(["--site", X])
    assert code == 2 and "PyYAML" in capsys.readouterr().out


# ------------------------------------------------------------------ further controls (plan 0.4 B.9)

def test_nested_duplicate_key_fails(X):
    sites.edit(F(X, "DESIGN.md"), "    padding: 24px", "    padding: 24px\n    padding: 24px")
    code, items, out = run(X)
    assert code == 1 and "duplicate key 'padding'" in out, out


def test_classified_at_rules_pass_and_are_listed(X):
    sites.edit(F(X, "../site/x.css"), ".link {", "@keyframes fade { from { opacity: 0.5; } to { opacity: 1; } }\n"
               "@view-transition { navigation: auto; }\n@page { margin: 1cm; }\n.link {")
    code, items, out = run(X)
    assert code == 0, out
    listed = [i["detail"] for i in items if i["status"] == "INFO" and i["check"] == "P1"]
    assert any("@view-transition" in x for x in listed) and any("@page" in x for x in listed), out


def test_statement_import_is_incomplete(X):
    sites.edit(F(X, "../site/x.css"), ".link {", '@import url("other.css");\n.link {')
    code, items, out = run(X)
    assert code == 3 and "@import" in out, out


def test_projection_recorded(X):
    code, items, _ = run(X)
    proj = {i["path"]: i.get("projection") for i in items if i["check"] == "P1" and i["status"] == "PASS"}
    assert proj["colors.ink"] == "var" and proj["rounded.card"] == "literal"


def test_literal_binding_through_a_variable_passes_and_wrong_variable_value_fails(X):
    sites.edit(F(X, "../site/x.css"), ".card { background: var(--paper); border-radius: 12px;", ".card { background: var(--paper); border-radius: var(--r);")
    sites.edit(F(X, "../site/x.css"), "--gap: 20px;", "--gap: 20px; --r: 12px;")
    assert run(X)[0] == 0
    sites.edit(F(X, "../site/x.css"), "--r: 12px;", "--r: 13px;")
    code, items, out = run(X)
    assert code == 1 and failed(items, "P1", "rounded.card"), out


def test_base_state_uses_its_base_component(X):
    sites.edit(F(X, "DESIGN.md"), '  link:\n    backgroundColor: "{colors.paper}"\n', "  link:\n")
    sites.edit(F(X, "trace-map.yaml"), '    backgroundColor: {host: body, own: .link, ref: "{colors.paper}"}\n', "")
    code, items, out = run(X)
    assert code == 1 and "no base component" in out, out
    sites.edit(F(X, "contrast.yaml"), "baseline: []", "base:\n  link: card\nbaseline: []")
    code, items, out = run(X)
    assert code == 0, out


def test_exact_threshold_passes(X, monkeypatch, capsys):
    import check_design
    _make_link_fail(X)
    monkeypatch.setattr(check_design.dl, "ratio", lambda fg, bg: 4.5)
    assert check_design.main(["--site", X]) == 0, capsys.readouterr().out
    monkeypatch.setattr(check_design.dl, "ratio", lambda fg, bg: 4.4999999)
    assert check_design.main(["--site", X]) == 1


def test_baseline_entry_that_now_passes_is_reported(X):
    entry = ("  - {component: link, scheme: light, text: \"{colors.accent}\", surface: paper, method: fractional, ratio: 3.0, decision: test,"
             " text_colour: \"#c2410c\", surface_colour: \"#fffdf7\"}\n")
    open(F(X, "contrast.yaml"), "w").write(sites.X_CONTRAST.replace("baseline: []\n", "baseline:\n" + entry))
    code, items, out = run(X)
    assert code == 0 and failed(items, "P3", "components.link", status="INFO"), out


# ------------------------------------------------------------------ generality: nothing of one real site in the plugin

LAB_LITERALS = ["xthought", "x-thought", "manrope", "magistratum", "vlbra", "navy", "blue-deep", "faint", "soft-blue", "bg-alt",
                "planned-bg", "header-bg", "hover-blue", "line-strong", "research-card", "question-text", "is-featured",
                "7, 29, 70", "8, 105, 216", "a30ddcd3", "3.9589", "3.9794",
                "#0556b3", "#071d46", "#0869d8", "#0c2c63", "#eef5fe", "#f3f8fe", "#f4f5f8", "#f8fafd"]


def test_no_site_literals_in_the_plugin():
    plugin = os.path.dirname(sites.SCRIPTS)
    hits = []
    for sub in ("scripts", "skills"):
        for dirpath, _dirs, files in os.walk(os.path.join(plugin, sub)):
            if "vendor" in dirpath or "__pycache__" in dirpath:
                continue
            for f in files:
                text = open(os.path.join(dirpath, f), encoding="utf-8", errors="replace").read().lower()
                hits += ["%s: %s" % (f, w) for w in LAB_LITERALS if w in text]
    assert not hits, hits


# ------------------------------------------------------------------ added after the first mutation run

def test_alias_token_changed_fails(X):
    sites.edit(F(X, "DESIGN.md"), '  primary: "{colors.ink}"', '  primary: "{colors.accent}"')
    code, items, out = run(X)
    assert code == 1 and failed(items, "P1", "colors.primary"), out


def test_normal_text_needs_4_5(X):
    sites.edit(F(X, "DESIGN.md"), 'accent: "#c2410c"', 'accent: "#808080"')
    sites.edit(F(X, "../site/x.css"), "--accent: #c2410c;", "--accent: #808080;")
    code, items, out = run(X)
    assert code == 1 and failed(items, "P3", "components.link") and "threshold 4.5" in out, out


# ------------------------------------------------------------------ added after review round 1

@pytest.mark.parametrize("old,new,word", [
    ("    - accent\n    - paper\n    background-color:", "    - accent\n    - paper\n    - old-accent\n    background-color:", "admits the reserved token old-accent"),
    ("  tokens:\n  - ink\n", "  tokens:\n  - ink\n  - old-accent\n", "admits the reserved token old-accent"),
], ids=["in roles", "in headings"])
def test_reserved_token_admitted_by_the_policy_fails(X, old, new, word):
    sites.edit(F(X, "policy.yaml"), old, new)
    code, items, out = run(X)
    assert code == 1 and word in out, out


def test_reserved_colour_admitted_as_an_extra_fails(X):
    sites.edit(F(X, "policy.yaml"), "  rgb:\n  - 26\n  - 26\n  - 46\n  alpha: 0.2", "  rgb:\n  - 154\n  - 52\n  - 18\n  alpha: 1")
    sites.edit(F(X, "DESIGN.md"), "Borders use {colors.ink} at 20%.", "Borders use {colors.old-accent} at 100%.")
    sites.edit(F(X, "policy.yaml"), "Borders use {colors.ink} at 20%.", "Borders use {colors.old-accent} at 100%.")
    code, items, out = run(X)
    assert code == 1 and "admits the reserved token old-accent's colour" in out, out


def test_issue_refuses_overrides(X):
    code, items, out = run(X, "--issue", "--deploy-root", "/nonexistent-elsewhere")
    assert code == 2 and "cannot be combined" in out and not os.path.exists(F(X, "ready.json")), out


@pytest.mark.parametrize("css", [".card { & p { color: red; } }", ".card { c\\6f lor: red; }"], ids=["nesting", "escaped name"])
def test_nesting_and_escaped_names_are_incomplete(X, css):
    sites.edit(F(X, "../site/x.css"), ".link {", css + "\n.link {")
    code, items, out = run(X)
    assert code == 3 and "nested block or escaped property" in out, out


@pytest.mark.parametrize("old,new,word", [
    ("  muted: \"rgba(26, 26, 46, 0.7)\"", "  muted: \"rgba(26, 26, 46, 0.7)\"\n  rust: \"#9a3412\"", "has the reserved token old-accent's colour"),
], ids=["token with the reserved colour"])
def test_token_with_the_reserved_colour_fails(X, old, new, word):
    sites.edit(F(X, "DESIGN.md"), old, new)
    sites.edit(F(X, "trace-map.yaml"), "  muted: {var: --muted}", "  muted: {var: --muted}\n  rust: {var: --old-accent}")
    sites.edit(F(X, "policy.yaml"), "    border-color:\n    - ink", "    border-color:\n    - ink\n    - rust")
    code, items, out = run(X)
    assert code == 1 and word in out, out


@pytest.mark.parametrize("old,new", [
    ("- tokens:\n  - accent\n  alpha_above", "- tokens:\n  - old-accent\n  alpha_above"),
    ("    background: primary", "    background: old-accent"),
    ("    tokens:\n    - accent\n    max_share", "    tokens:\n    - old-accent\n    max_share"),
], ids=["fills", "buttons", "headings accent"])
def test_reserved_in_fills_buttons_accent_fails(X, old, new):
    sites.edit(F(X, "policy.yaml"), old, new)
    code, items, out = run(X)
    assert code == 1 and "admits the reserved token old-accent" in out, out


def test_reserved_in_scheme_pairs_fails(Y):
    sites.edit(F(Y, "policy.yaml"), "reserved: []", "reserved:\n- ink-dark")
    code, items, out = run(Y)
    assert code == 1 and failed(items, "POL", "policy.scheme.pairs"), out


# ------------------------------------------------------------------ added after the outside audit, round 1

def yaml_edit(path, change):
    """Load a profile YAML file, change the data, write it back (robust to the fixture's exact text)."""
    import yaml
    data = yaml.safe_load(open(path, encoding="utf-8"))
    change(data)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def regenerate(d):
    """Design-first: render tokens.css and the trace map again from the folder's files (as generate_css.py --write)."""
    import yaml
    import generate_css
    snap = dl.Snapshot()
    fm, _ = dl.split_front_matter(snap.text(F(d, "DESIGN.md")))
    design = dl.load_yaml_text(fm, "DESIGN.md")
    old = yaml.safe_load(open(F(d, "trace-map.yaml"), encoding="utf-8"))
    pol = yaml.safe_load(open(F(d, "policy.yaml"), encoding="utf-8"))
    generate_css.write_lf(F(d, "../site/tokens.css"), generate_css.render(design, old, pol, snap.digest(F(d, "DESIGN.md"))))
    generate_css.write_lf(F(d, "trace-map.yaml"), yaml.safe_dump(generate_css.render_map(design, old), sort_keys=False))


@pytest.mark.parametrize("old,new", [('textColor: "{colors.muted}"', 'textColor: "{rounded.card}"'),
                                     ("    rounded: \"{rounded.card}\"", "    rounded: \"{colors.ink}\"")],
                         ids=["dimension as textColor", "colour as rounded"])
def test_component_fields_are_typed(X, old, new):
    """AUD-F06: a reference resolving to the wrong type is a P2 FAIL, never INTERNAL."""
    sites.edit(F(X, "DESIGN.md"), old, new)
    code, items, out = run(X)
    assert code == 1 and failed(items, "P2", "components.card") and "INTERNAL" not in out, out


def test_unbalanced_site_css_is_an_error(X):
    """AUD-F06: unbalanced braces in the site CSS are an unusable input: ERROR 2."""
    sites.edit(F(X, "../site/x.css"), ".link { color: var(--accent); }", ".link { color: var(--accent);")
    code, items, out = run(X)
    assert code == 2 and "cannot be read" in out and "INTERNAL" not in out, out


@pytest.mark.parametrize("old,new,path", [
    ("  measure: {var: --measure}", "  measure: {sel: [], prop: width}", "spacing.measure"),
    ("  card: {sel: .card, prop: border-radius}", "  card: {sel: .card}", "rounded.card"),
    ("    padding: {sel: .card, prop: padding}", "    padding: {}", "components.card.padding"),
], ids=["empty selector list", "selector without property", "empty field binding"])
def test_empty_bindings_fail(X, old, new, path):
    """AST-M07: a binding that names no selector, property or variable binds nothing."""
    sites.edit(F(X, "trace-map.yaml"), old, new)
    code, items, out = run(X)
    assert code == 1 and failed(items, "P2", path), out


def test_empty_typography_vars_fail(Y):
    """AST-M07: design-first typography vars must bind every property of the token."""
    yaml_edit(F(Y, "trace-map.yaml"), lambda m: m["typography"]["body"].__setitem__("vars", {}))
    code, items, out = run(Y)
    assert code == 1 and failed(items, "P2", "typography.body"), out


def test_several_declarations_of_one_binding_are_incomplete(X):
    """AST-M08: two rules give .card two different radii: which applies is not decided, so INCOMPLETE."""
    sites.edit(F(X, "../site/x.css"), ".link {", ".card { border-radius: 9px; }\n.link {")
    code, items, out = run(X)
    assert code == 3 and failed(items, "P1", "rounded.card", status="INCOMPLETE"), out


@pytest.mark.parametrize("old,new,path", [
    (".button { border-radius: 8px;", ".button { font-family: Georgia, serif; border-radius: 8px;", "components.button-primary.typography.fontFamily"),
    ("font-size: 15px; font-weight: 600;", "font-size: 15px;", "components.button-primary.typography.fontWeight"),
], ids=["family", "subset"])
def test_component_typography_is_compared_whole(X, old, new, path):
    """AST-M08, AUD-F07(1): the family is compared, and a selector declaring part of the token fails."""
    sites.edit(F(X, "../site/x.css"), old, new)
    code, items, out = run(X)
    assert code == 1 and failed(items, "P1", path), out


def test_inherited_component_typography_checks_the_chain(X):
    """AST-M08, AUD-F07(1): a component selector declaring no typography inherits it along the named chain."""
    sites.edit(F(X, "../site/x.css"), ".card p { font-size: 15px; line-height: 1.6; color: var(--muted); }", ".card p { color: var(--muted); }")
    code, items, out = run(X)
    assert code == 1 and failed(items, "P1", "components.card.typography.fontSize") and "inherits font-size" in out, out


def test_design_first_clamp_maximum_is_checked(Y):
    """AST-M08: design-first, DESIGN.md's fontSize must be the generated clamp()'s maximum."""
    sites.edit(F(Y, "DESIGN.md"), "    fontSize: 40px", "    fontSize: 36px")
    regenerate(Y)
    code, items, out = run(Y)
    assert code == 1 and failed(items, "P1", "typography.title.fontSize") and "clamp maximum" in out, out


def test_literal_own_background_is_checked(X):
    """AST-M09: the card's literal background changed to ink while contrast.yaml still names paper."""
    sites.edit(F(X, "DESIGN.md"), '  card:\n    backgroundColor: "{colors.paper}"', '  card:\n    backgroundColor: "#1a1a2e"')
    sites.edit(F(X, "trace-map.yaml"), '    backgroundColor: {sel: .card, prop: background, ref: "{colors.paper}"}',
               "    backgroundColor: {sel: .card, prop: background}")
    sites.edit(F(X, "../site/x.css"), ".card { background: var(--paper);", ".card { background: #1a1a2e;")
    code, items, out = run(X)
    assert code == 1 and "not among its listed surfaces" in out and failed(items, "P3", "components.card"), out
    assert [i for i in failed(items, "P3", "components.card") if "on self:" in i["detail"]], out    # its own background, checked


def test_component_typography_subset_fails_even_when_inherited_values_match(X):
    """AUD-F07(1): a selector declaring part of a token fails even where the rest would be inherited equal."""
    sites.edit(F(X, "DESIGN.md"), "    fontSize: 15px\n    fontWeight: 600", '    fontSize: 15px\n    lineHeight: "1.5"')
    sites.edit(F(X, "../site/x.css"), "font-size: 15px; font-weight: 600;", "font-size: 15px;")
    code, items, out = run(X)
    assert code == 1 and failed(items, "P1", "components.button-primary.typography.lineHeight"), out


def _link_typography(X, level_css, size):
    """The link component gets typography.button; .link declares it; accent #808080 on paper is 3.9:1."""
    sites.edit(F(X, "DESIGN.md"), "    fontSize: 15px\n    fontWeight: 600", "    fontSize: %s\n    fontWeight: 400" % size)
    sites.edit(F(X, "../site/x.css"), "font-size: 15px; font-weight: 600;", "font-size: %s; font-weight: 400;" % level_css)
    sites.edit(F(X, "DESIGN.md"), '    textColor: "{colors.accent}"', '    textColor: "{colors.accent}"\n    typography: "{typography.button}"')
    sites.edit(F(X, "trace-map.yaml"), '    textColor: {sel: .link, prop: color, ref: "{colors.accent}"}',
               '    textColor: {sel: .link, prop: color, ref: "{colors.accent}"}\n    typography: {sel: .button, ref: "{typography.button}"}')
    sites.edit(F(X, "DESIGN.md"), 'accent: "#c2410c"', 'accent: "#808080"')
    sites.edit(F(X, "../site/x.css"), "--accent: #c2410c;", "--accent: #808080;")


def test_rem_component_size_is_converted(X):
    """AUD-F07(3): 1.5rem is 24 px: large text, 3:1 (it would be 4.5:1 at an assumed 16 px)."""
    _link_typography(X, "1.5rem", "1.5rem")
    code, items, out = run(X)
    assert code == 0, out


def test_em_component_size_is_undecided(X):
    """AUD-F07(3): an em size is not resolved here: below 4.5:1 and above 3:1 is INCOMPLETE, never a pass."""
    _link_typography(X, "1.5em", "1.5em")
    code, items, out = run(X)
    assert failed(items, "P3", "components.link", status="INCOMPLETE") and "relative size" in out, out


def test_issue_refuses_inputs_changed_during_the_run(X, monkeypatch, capsys):
    """AST-H08 (HQ's note): a site CSS file changed on disk after the checks read it: no receipt."""
    import check_design
    git(X, "init", "-q")
    git(X, "add", ".")
    git(X, "commit", "-qm", "profile")
    real = dl.Snapshot.read

    def read(self, path):
        data = real(self, path)
        if path.endswith("x.css"):
            open(path, "ab").write(b"\n/* changed after the read */\n")
        return data
    monkeypatch.setattr(dl.Snapshot, "read", read)
    code = check_design.main(["--site", X, "--issue"])
    assert code == 3 and not os.path.exists(F(X, "ready.json")) and "changed during the run" in capsys.readouterr().out


def test_fluid_component_text_uses_its_smallest_size(X):
    """AST-M09, AUD-F07(3): a clamp() whose minimum is 18 px bold is normal text (4.5:1), not its 56 px maximum."""
    sites.edit(F(X, "trace-map.yaml"), 'clamp_expr: "clamp(32px, 5vw, 56px)"', 'clamp_expr: "clamp(18px, 5vw, 56px)"')
    sites.edit(F(X, "../site/x.css"), "clamp(32px, 5vw, 56px)", "clamp(18px, 5vw, 56px)")
    sites.edit(F(X, "DESIGN.md"), '    textColor: "{colors.accent}"', '    textColor: "{colors.accent}"\n    typography: "{typography.display}"')
    sites.edit(F(X, "trace-map.yaml"), '    textColor: {sel: .link, prop: color, ref: "{colors.accent}"}',
               '    textColor: {sel: .link, prop: color, ref: "{colors.accent}"}\n    typography: {sel: .hero h1, ref: "{typography.display}"}')
    sites.edit(F(X, "DESIGN.md"), 'accent: "#c2410c"', 'accent: "#808080"')
    sites.edit(F(X, "../site/x.css"), "--accent: #c2410c;", "--accent: #808080;")
    code, items, out = run(X)
    assert code == 1 and failed(items, "P3", "components.link") and "threshold 4.5" in out, out


def test_dark_pair_follows_an_alias(Y):
    """AUD-F07(2): an alias of a paired token is mapped to the pair in the dark scheme."""
    sites.edit(F(Y, "DESIGN.md"), '  line: "rgba(17, 24, 39, 0.12)"', '  line: "rgba(17, 24, 39, 0.12)"\n  primary: "{colors.ink-light}"')
    sites.edit(F(Y, "DESIGN.md"), 'textColor: "{colors.ink-light}"', 'textColor: "{colors.primary}"')
    regenerate(Y)
    code, items, out = run(Y)
    assert code == 0, out


def test_baseline_with_changed_surface_colour_fails(X):
    """AUD-F08: the surface token keeps its name but its colour changes: the baseline no longer holds."""
    _make_link_fail(X)
    fg = dl.composite(dl.Colour(240, 160, 128), (255, 253, 247))
    entry = ("  - {component: link, scheme: light, text: \"{colors.accent}\", surface: paper, method: fractional, ratio: %.4f, decision: test,"
             " text_colour: \"#f0a080\", surface_colour: \"#fffdf7\"}\n" % (int(dl.ratio(fg, (255, 253, 247)) * 10000) / 10000))
    open(F(X, "contrast.yaml"), "w").write(sites.X_CONTRAST.replace("baseline: []\n", "baseline:\n" + entry))
    assert run(X)[0] == 0
    sites.edit(F(X, "DESIGN.md"), 'paper: "#fffdf7"', 'paper: "#ffffff"')
    for old, new in (("--paper: #fffdf7;", "--paper: #ffffff;"), ("background: #fffdf7;", "background: #ffffff;"), ("color: #fffdf7;", "color: #ffffff;")):
        sites.edit(F(X, "../site/x.css"), old, new)
    code, items, out = run(X)
    assert code == 1 and failed(items, "P3", "baseline"), out


@pytest.mark.parametrize("change,word", [
    (lambda p: p.__setitem__("fonts", {}), "at least one approved face"),
    (lambda p: p["fonts"].__setitem__("faces", []), "at least one approved face"),
    (lambda p: p["fonts"]["faces"][0].pop("coverage"), "coverage must be"),
    (lambda p: p["fonts"]["faces"][0].__setitem__("sha256", "0" * 64), "does not have the SHA-256"),
    (lambda p: p["fonts"]["faces"][0].__setitem__("file", "../site/fonts/none.ttf"), "does not exist"),
    (lambda p: p["roles"].__setitem__("light", {}), "needs its roles"),
    (lambda p: p["roles"]["light"]["color"].append("old-accent"), "is not in the light set"),
    (lambda p: p["accessibility"]["tags"].append("wcag-made-up"), "knows no tag wcag-made-up"),
    (lambda p: p["accessibility"]["tiers"].__setitem__("image-alt", "typo"), "tier must be blocking or advisory"),
    (lambda p: p["tiers"].__setitem__("A12", "advisory"), "unknown assertion"),
], ids=["no faces", "empty face list", "no coverage", "face hash", "face file", "empty roles", "role outside the set", "unknown axe tag",
        "accessibility tier", "A12 tier"])
def test_policy_schema(X, change, word):
    """AST-M06, AUD-F04, AST-M15, AUD-F09."""
    yaml_edit(F(X, "policy.yaml"), change)
    code, items, out = run(X)
    assert code == 1 and word in out and "INTERNAL" not in out, out


@pytest.mark.parametrize("change,word", [
    (lambda p: p["roles"].pop("dark"), "needs its roles"),
    (lambda p: p["scheme"]["pairs"].pop("ink-light"), "has no dark pair"),
], ids=["dark roles missing", "pairs incomplete"])
def test_policy_schema_both_schemes(Y, change, word):
    yaml_edit(F(Y, "policy.yaml"), change)
    code, items, out = run(Y)
    assert code == 1 and word in out, out


def test_waiver_fields_are_typed(X):
    open(F(X, "waivers.yaml"), "w").write("waivers:\n  - {id: w, assertion: A4, page: a.html, selector: div, page_sha256: abc, reason: r,"
                                          " owner_words: w, date: 'tomorrow'}\n")
    code, items, out = run(X)
    assert code == 1 and "page_sha256 is not a SHA-256" in out and "date is not YYYY-MM-DD" in out, out


def test_derived_variable_with_an_unknown_paint_fails(X):
    """AST-M10: the whole derived value is read: a named colour is a paint this check cannot allow."""
    sites.edit(F(X, "policy.yaml"), "derived_vars: []", "derived_vars:\n- {name: --shadow, roles: [box-shadow]}")
    sites.edit(F(X, "../site/x.css"), "--gap: 20px;", "--gap: 20px; --shadow: 0 0 1px red;")
    code, items, out = run(X)
    assert code == 1 and "red (not a colour this check can read)" in out, out


def test_issue_hashes_the_bytes_it_checked(X, monkeypatch, capsys):
    """AST-H09: the policy in the snapshot differs from HEAD while the disk is restored before Git looks: no receipt."""
    import check_design
    git(X, "init", "-q")
    git(X, "add", ".")
    git(X, "commit", "-qm", "profile")
    committed = open(F(X, "policy.yaml"), "rb").read()
    sites.edit(F(X, "policy.yaml"), "  A3: blocking", "  A3: advisory")
    real = dl.Snapshot.read

    def read(self, path):
        data = real(self, path)
        if path.endswith("policy.yaml"):
            open(path, "wb").write(committed)        # the disk now holds the committed bytes again
        return data
    monkeypatch.setattr(dl.Snapshot, "read", read)
    monkeypatch.setattr(check_design, "inputs_changed", lambda ctx: [])   # the approval alone must refuse it
    code = check_design.main(["--site", X, "--issue"])
    assert code == 3 and not os.path.exists(F(X, "ready.json")), capsys.readouterr().out


def test_issue_refuses_a_linked_ready_json(X, tmp_path):
    """AST-M04: ready.json is written to a new file and renamed into place; an existing link is refused."""
    git(X, "init", "-q")
    target = tmp_path / "elsewhere.json"
    target.write_text("{}")
    try:
        os.symlink(str(target), F(X, "ready.json"))
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links cannot be created here")
    git(X, "add", "-A")
    git(X, "commit", "-qm", "profile")
    code, items, out = run(X, "--issue")
    assert code == 3 and target.read_text() == "{}" and "is a link" in out, out


def test_issue_refuses_a_ready_json_that_is_not_a_file(X):
    """AST-M04 (every platform): an existing ready.json that is not a regular file is never replaced."""
    os.mkdir(F(X, "ready.json"))
    git(X, "init", "-q")
    git(X, "add", "-A")
    git(X, "commit", "-qm", "profile")
    code, items, out = run(X, "--issue")
    assert code == 3 and os.path.isdir(F(X, "ready.json")) and "not a regular file" in out, out
    assert not [f for f in os.listdir(X) if f.startswith(".ready.json.")], os.listdir(X)


def test_outputs_are_refused_inside_the_site_design_folder(X):
    """AST-M04."""
    r = subprocess.run([sys.executable, "-I", "-B", CD, "--site", X, "--json", F(X, "report.json")], capture_output=True, text=True)
    assert r.returncode == 2 and "inside the site design folder" in r.stdout and not os.path.exists(F(X, "report.json")), r.stdout


def test_unwritable_report_is_an_error(X, tmp_path):
    """AST-M03: the report is written before the summary; a report that cannot be written is ERROR 2."""
    r = subprocess.run([sys.executable, "-I", "-B", CD, "--site", X, "--json", str(tmp_path / "missing" / "r.json")], capture_output=True, text=True)
    assert r.returncode == 2 and "could not be written" in r.stdout and "Traceback" not in r.stderr, r.stdout + r.stderr


def test_component_stylesheets_are_loaded_and_hashed(Y):
    """AUD-F12: component_stylesheets are CSS of the site: loaded by P1 and hashed into the receipt."""
    open(F(Y, "../site/comp.css"), "w").write('.card { font-family: "Lora Test"; font-size: 18px; line-height: 1.7; }\n')
    sites.edit(F(Y, "site.yaml"), "policy_version: 1", "policy_version: 1\ncomponent_stylesheets: [../site/comp.css]")
    yaml_edit(F(Y, "trace-map.yaml"), lambda m: m["components"]["card"].__setitem__("typography", {"sel": ".card", "ref": "{typography.body}"}))
    git(Y, "init", "-q")
    git(Y, "add", ".")
    git(Y, "commit", "-qm", "profile")
    code, items, out = run(Y, "--issue")
    assert code == 0, out
    assert "../site/comp.css" in json.load(open(F(Y, "ready.json")))["css"], out
    sites.commit_receipt(Y)                               # the owner commits the receipt (R2-H06)
    b = sites.bundle(Y, "c", '<!doctype html><html lang="en"><head><title>t</title><link rel="stylesheet" href="tokens.css">'
                             '<link rel="stylesheet" href="comp.css"></head><body><p>t</p></body></html>')
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(sites.SCRIPTS, "check_css.py"), "--site", Y, "--bundle", b, "--page", "index.html"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout          # the consumer counts the component stylesheet in the receipt too


def test_generate_then_verify_on_the_written_bytes(Y):
    """AST-M05: generate_css.py --write writes LF bytes; check_design.py verifies them right after, on any platform."""
    gen = os.path.join(sites.SCRIPTS, "generate_css.py")
    r = subprocess.run([sys.executable, "-I", "-B", gen, "--site", Y, "--write"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert b"\r\n" not in open(F(Y, "../site/tokens.css"), "rb").read()
    code, items, out = run(Y)
    assert code == 0, out


@pytest.mark.parametrize("tokens,word", [("{d}/tokens.css", "inside the site design folder"), ("{root}/outside/tokens.css", "outside the deploy root")],
                         ids=["inside the profile", "outside the deploy root"])
def test_generator_destinations_are_checked(Y, tokens, word):
    """AST-M04."""
    gen = os.path.join(sites.SCRIPTS, "generate_css.py")
    path = tokens.format(d=Y, root=os.path.dirname(Y))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = subprocess.run([sys.executable, "-I", "-B", gen, "--site", Y, "--tokens", path, "--write"], capture_output=True, text=True)
    assert r.returncode == 2 and word in r.stdout and not os.path.exists(path), r.stdout


def test_generator_errors_are_error_2(Y):
    """AUD-F11: a reference the generator cannot project is ERROR 2, never a traceback with exit 1."""
    sites.edit(F(Y, "DESIGN.md"), "    padding: 20px", '    padding: 20px\n    width: "{typography.body}"')
    gen = os.path.join(sites.SCRIPTS, "generate_css.py")
    r = subprocess.run([sys.executable, "-I", "-B", gen, "--site", Y], capture_output=True, text=True)
    assert r.returncode == 2 and "cannot be a CSS variable" in r.stdout and "Traceback" not in r.stderr, r.stdout + r.stderr


def test_hex_alpha_is_exact():
    """AST-M17: an authored hex alpha is k/255 exactly; the browser tolerance is never applied to it."""
    assert not dl.same("#00000001", "rgba(0,0,0,.0039)")
    assert dl.same("#00000080", "#00000080") and dl.parse_colour("#000000ff") == dl.parse_colour("#000000")


def test_starting_skill_writes_the_policy_before_generating():
    """AST-M20: generate_css.py reads policy.yaml (its scheme pairs), so the skill orders the policy first."""
    text = open(os.path.join(os.path.dirname(sites.SCRIPTS), "skills", "starting-a-site-design-system", "SKILL.md"), encoding="utf-8").read()
    order = text.split("## Order of work", 1)[1].split("## Commands", 1)[0]
    assert order.index("**`policy.yaml`") < order.index("**Generate.**"), order[:400]


def test_skills_say_who_reads_prose_and_which_sections_may_be_off():
    """AST-L03: no claim that no script reads prose; the reference lists the sections that may be off."""
    root = os.path.dirname(sites.SCRIPTS)
    texts = {p: open(os.path.join(root, *p.split("/")), encoding="utf-8").read() for p in (
        "skills/starting-a-site-design-system/SKILL.md", "skills/keeping-a-site-design-system/SKILL.md",
        "skills/keeping-a-site-design-system/references/profile-files.md")}
    assert not [p for p, t in texts.items() if "no script reads prose" in t.lower() or "no script reads it" in t.lower()]
    ref = texts["skills/keeping-a-site-design-system/references/profile-files.md"]
    assert "`scheme` can never be `off`" in ref and "Any other section may be" not in ref


# ================================================================== outside audit round 2 (Sol 6.1)

def _committed_x(X):
    git(X, "init", "-q")
    git(X, "add", ".")
    git(X, "commit", "-qm", "profile")


def test_issue_refuses_a_path_whose_attributes_change_content(X):
    """R2-M02: --issue approves no file whose attributes set ident (Sol's case), a filter or working-tree-encoding: the
    repository could map a different text to the committed blob."""
    _committed_x(X)
    for attrs, word in (("policy.yaml ident\n", "ident"), ("DESIGN.md working-tree-encoding=UTF-16\n", "working-tree-encoding")):
        with open(F(X, ".git/info/attributes"), "w") as fh:
            fh.write(attrs)
        code, items, out = run(X, "--issue")
        assert code == 3 and not os.path.exists(F(X, "ready.json")), out
        assert [i for i in items if i["status"] == "INCOMPLETE" and i["check"] == "APP" and word in i["detail"]], out


def test_issue_never_runs_a_configured_clean_filter(X):
    """R2-M02: approval at issue runs no filter: with a clean filter configured for every path, --issue is refused
    and the filter's marker never appears."""
    _committed_x(X)
    marker = os.path.join(os.path.dirname(X), "filter-ran.txt")
    git(X, "config", "filter.mark.clean", "echo ran > ../filter-ran.txt; cat")
    with open(F(X, ".git/info/attributes"), "w") as fh:
        fh.write("* filter=mark\n")
    code, items, out = run(X, "--issue")
    assert code == 3 and "attributes may change" in out and not os.path.exists(F(X, "ready.json")), out
    assert not os.path.exists(marker), "the clean filter ran"


def test_issue_records_the_blob_rev_parse_gives_and_ends_with_the_commit_step(X):
    """R2-M02, R2-H06: a receipt's blob id is the one rev-parse <commit>:./<name> gives; --issue prints the receipt's
    SHA-256 and ends with the instruction to commit ready.json."""
    _committed_x(X)
    r = subprocess.run([sys.executable, "-I", "-B", CD, "--site", X, "--issue"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout
    receipt = json.load(open(F(X, "ready.json")))
    want = subprocess.run(["git", "rev-parse", "%s:./policy.yaml" % receipt["commit"]], cwd=X, capture_output=True, text=True).stdout.strip()
    assert receipt["profile"]["policy.yaml"]["blob"] == want
    fp = sites.hashlib.sha256(open(F(X, "ready.json"), "rb").read()).hexdigest()
    last = r.stdout.strip().splitlines()[-1]
    assert fp in r.stdout and "Commit ready.json now" in last and "only once it is committed" in last, r.stdout


# R2-M05: rem from the site's root font size

def _root_size(X, decl):
    """The X profile with its own html rule: body keeps 16px; html gets decl (the root font size the site sets)."""
    sites.edit(F(X, "../site/x.css"), "html, body {", "body {")
    sites.edit(F(X, "../site/x.css"), ".hero h1 {", "html { %s }\n.hero h1 {" % decl)


def test_rem_uses_the_root_font_size_the_site_sets(X):
    """R2-M05 (Sol's case): html { font-size: 12px }, a component at 1.5rem, weight 400, ratio 3.88:1: 18 px is normal
    text, so P3 FAILs at 4.5:1 (at an assumed 16 px it was large text and passed at 3:1)."""
    _link_typography(X, "1.5rem", "1.5rem")
    _root_size(X, "font-size: 12px;")
    code, items, out = run(X)
    assert code == 1 and failed(items, "P3", "components.link") and "threshold 4.5" in out, out


def test_rem_without_a_root_size_is_16_px(X):
    """R2-M05, control: no root font size set: the browser default 16 px, 1.5rem is 24 px, large text, PASS."""
    _link_typography(X, "1.5rem", "1.5rem")
    sites.edit(F(X, "../site/x.css"), "html, body {", "body {")
    code, items, out = run(X)
    assert code == 0, out


def test_uncertain_root_size_takes_the_stricter_threshold(X):
    """R2-M05: a root size in a viewport unit is uncertain; where the large-text class decides the outcome, 4.5:1."""
    _link_typography(X, "1.5rem", "1.5rem")
    _root_size(X, "font-size: 1.2vw;")
    code, items, out = run(X)
    assert code == 1 and failed(items, "P3", "components.link") and "root font size is uncertain" in out, out


def test_smaller_override_size_is_used(X):
    """R2-M05: the smallest applicable size among the token and the trace map's font-size overrides: a 15 px override
    of the component's selector makes 24 px text normal text (FAIL at 4.5:1)."""
    _link_typography(X, "24px", "24px")
    assert run(X)[0] == 0                                  # control: 24 px is large text, 3.9:1 passes 3:1
    sites.edit(F(X, "trace-map.yaml"), "overrides:\n", "overrides:\n  - {sel: .button, media: \"(max-width: 600px)\", prop: font-size, value: 15px}\n")
    sites.edit(F(X, "../site/x.css"), "@media (max-width: 600px) { .hero h1 { font-size: 30px; } }",
               "@media (max-width: 600px) { .hero h1 { font-size: 30px; } .button { font-size: 15px; } }")
    code, items, out = run(X)
    assert code == 1 and failed(items, "P3", "components.link"), out


# R2-M06: the policy's whole shape, before any entry is read; the button signature

def _set_policy(d, mutate):
    import yaml
    path = F(d, "policy.yaml")
    data = yaml.safe_load(open(path, encoding="utf-8"))
    mutate(data)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def test_face_of_the_wrong_type_is_a_policy_failure(X):
    """R2-M06 (HQ's probe m06): fonts.faces: [3] is a named POL FAIL, not INTERNAL 4."""
    _set_policy(X, lambda p: p["fonts"].__setitem__("faces", [3]))
    code, items, out = run(X, "--verify")
    assert code == 1 and failed(items, "POL", "fonts.faces[0]") and "INTERNAL" not in out, out


def _paths(node, prefix=()):
    """Every key path of a parsed policy, list items included."""
    yield prefix
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _paths(v, prefix + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _paths(v, prefix + (i,))


def _kind(v):
    return "null" if v is None else "num" if isinstance(v, (int, float)) else type(v).__name__


def test_every_wrong_type_in_the_policy_is_a_named_failure(X):
    """R2-M06: for every key of X's policy, each wrong type (integer, string, list, mapping, null) gives POL FAIL and
    never INTERNAL 4 (a null may be an allowed empty value: never INTERNAL then either)."""
    import yaml
    import check_design
    original = open(F(X, "policy.yaml"), encoding="utf-8").read()
    base = yaml.safe_load(original)
    wrong = {"num": 7, "str": "x", "list": [1], "dict": {"k": 1}, "null": None}
    misses = []
    for path in list(_paths(base))[1:]:
        cur = base
        for k in path:
            cur = cur[k]
        for kind, value in wrong.items():
            if kind == _kind(cur):
                continue

            def put(p, path=path, value=value):
                node = p
                for k in path[:-1]:
                    node = node[k]
                node[path[-1]] = value
            _set_policy(X, put)
            code = check_design.main(["--site", X, "--verify"])
            if code == 4 or (kind != "null" and code != 1):
                misses.append((path, kind, code))
            open(F(X, "policy.yaml"), "w", encoding="utf-8", newline="\n").write(original)
    assert not misses, misses[:20]


def test_unknown_button_paint_token_is_a_policy_failure(X):
    """R2-M06: buttons.paint names tokens of the palette: an unknown one is POL FAIL (A11 would lose its paint path)."""
    _set_policy(X, lambda p: p["buttons"]["paint"].__setitem__("text", "no-such-token"))
    code, items, out = run(X, "--verify")
    assert code == 1 and failed(items, "POL", "buttons.paint.text"), out


def test_selector_only_buttons_are_said_explicitly(X):
    """R2-M06: paint: selectors-only is the explicit selector-only configuration (passes); a policy with neither a
    paint signature nor selectors-only fails (A11 never loses its paint path silently)."""
    _set_policy(X, lambda p: p["buttons"].__setitem__("paint", "selectors-only"))
    assert run(X, "--verify")[0] == 0
    _set_policy(X, lambda p: p["buttons"].pop("paint"))
    code, items, out = run(X, "--verify")
    assert code == 1 and failed(items, "POL", "buttons"), out


def test_profiles_y_and_z_name_their_own_button_tokens(tmp_path):
    """R2-M06: the Y and Z fixtures' button signatures name tokens of their own palettes (they named absent ones)."""
    import yaml
    for builder in (sites.build_y, sites.build_z):
        d = builder(tmp_path / builder.__name__)
        pol = yaml.safe_load(open(F(d, "policy.yaml"), encoding="utf-8"))
        colors = yaml.safe_load(dl.split_front_matter(open(F(d, "DESIGN.md"), encoding="utf-8").read())[0])["colors"]
        assert set(pol["buttons"]["paint"].values()) <= set(colors), (builder.__name__, pol["buttons"])


# R2-M07: certified variables hold only approved values

def test_font_stack_variable_with_an_unapproved_family_fails(X):
    """R2-M07 (Sol's case): stack_vars: [--font] with :root { --font: Georgia }: check_design FAILs it (an approved stack
    with a generic family passes, control)."""
    sites.edit(F(X, "policy.yaml"), "stack_vars: []", "stack_vars: [--font]")
    sites.edit(F(X, "../site/x.css"), "--measure: 680px;", "--measure: 680px; --font: Georgia;")
    code, items, out = run(X)
    assert code == 1 and failed(items, "POL", "stack_vars.--font") and "Georgia" in out, out
    sites.edit(F(X, "../site/x.css"), "--font: Georgia;", '--font: "Inter Test", sans-serif;')
    assert run(X)[0] == 0


# The CEO's decision on Question 6 (2026-11-11): a policy may name allowed system fallback families
LAB_STACK = '"Inter Test", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif'


def test_font_stack_with_listed_fallback_families_is_certified(X):
    """fonts.fallback_families: the lab's font stack (its approved face replaced by this synthetic site's, the system
    fallbacks "Segoe UI", Roboto and Arial kept) fails without the key, as the lab's folder does today (control); with
    the three named families listed it is certified; with Arial missing from the list it fails naming arial alone."""
    sites.edit(F(X, "policy.yaml"), "stack_vars: []", "stack_vars: [--font]")
    sites.edit(F(X, "../site/x.css"), "--measure: 680px;", "--measure: 680px; --font: %s;" % LAB_STACK)
    _set_policy(X, lambda p: p["fonts"].pop("fallback_families"))        # the key is optional
    code, items, out = run(X)
    assert code == 1 and failed(items, "POL", "stack_vars.--font") and "holds segoe ui, roboto, arial:" in out, out
    _set_policy(X, lambda p: p["fonts"].__setitem__("fallback_families", ["Segoe UI", "Roboto", "Arial"]))
    code, items, out = run(X)
    assert code == 0 and [i for i in items if i["status"] == "PASS" and i["path"] == "policy.fonts.stack_vars.--font"], out
    _set_policy(X, lambda p: p["fonts"].__setitem__("fallback_families", ["Segoe UI", "Roboto"]))
    code, items, out = run(X)
    assert code == 1 and failed(items, "POL", "stack_vars.--font") and "holds arial:" in out, out


@pytest.mark.parametrize("stack,certified", [
    ('Arial, "Inter Test", sans-serif', False),
    ('"Inter Test", Arial, sans-serif', True),
    ("sans-serif", False),
    ("ui-sans-serif, system-ui, sans-serif", False),
], ids=["listed fallback first", "approved face first", "generic only", "generic families only"])
def test_font_stack_variable_needs_an_approved_face_first(X, stack, certified):
    """The CEO's decision on CC-07's Question 5 (2026-11-12, 'the approved face first everywhere'): a font-stack
    variable is certified only when its first family is an approved face, then listed fallback families and generic
    families, as a literal stack is (test_check_css.py::test_every_font_stack_needs_an_approved_face_first). Arial is
    listed in fonts.fallback_families: first in the stack it fails; after the approved face it is certified. A stack of
    generic families alone names no approved face first: it fails."""
    sites.edit(F(X, "policy.yaml"), "stack_vars: []", "stack_vars: [--font]")
    sites.edit(F(X, "../site/x.css"), "--measure: 680px;", "--measure: 680px; --font: %s;" % stack)
    _set_policy(X, lambda p: p["fonts"].__setitem__("fallback_families", ["Arial"]))
    code, items, out = run(X)
    if certified:
        assert code == 0 and [i for i in items if i["status"] == "PASS" and i["path"] == "policy.fonts.stack_vars.--font"], out
    else:
        bad = failed(items, "POL", "stack_vars.--font")
        assert code == 1 and bad and "the first family must be an approved face" in bad[0]["detail"], out


@pytest.mark.parametrize("value", [7, "Segoe UI", [3], [""], {"Arial": 1}], ids=["integer", "string", "list of integers", "empty name", "mapping"])
def test_fallback_families_of_the_wrong_type_is_a_policy_failure(X, value):
    """fonts.fallback_families must be a list of non-empty family names (R2-M06's shape check): anything else is a
    named POL FAIL, never INTERNAL 4."""
    _set_policy(X, lambda p: p["fonts"].__setitem__("fallback_families", value))
    code, items, out = run(X, "--verify")
    assert code == 1 and failed(items, "POL", "fonts.fallback_families") and "INTERNAL" not in out, out


def test_derived_value_is_checked_for_each_role(X):
    """R2-M07: a derived value approved for one role (the accent in color) but admitted in another (border-color,
    where only ink is a token) fails there; admitted in color alone it passes (control)."""
    sites.edit(F(X, "policy.yaml"), "derived_vars: []", "derived_vars:\n- {name: --tone, roles: [color]}")
    sites.edit(F(X, "../site/x.css"), "--gap: 20px;", "--gap: 20px; --tone: #c2410c;")
    assert run(X)[0] == 0
    sites.edit(F(X, "policy.yaml"), "roles: [color]}", "roles: [color, border-color]}")
    code, items, out = run(X)
    assert code == 1 and "#c2410c [not in border-color (light)]" in out, out


def test_derived_value_is_checked_in_each_scheme(Y):
    """R2-M07: with scheme both, a derived value that is a light token fails in the dark scheme; a dark override in a
    prefers-color-scheme: dark media query holding the dark token passes (control)."""
    sites.edit(F(Y, "policy.yaml"), "derived_vars: []", "derived_vars:\n- {name: --tone, roles: [color]}")
    css = F(Y, "../site/y.css")
    with open(css, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(":root { --tone: #111827; }\n")
    code, items, out = run(Y)
    assert code == 1 and "#111827 [not in color (dark)]" in out, out
    with open(css, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("@media (prefers-color-scheme: dark) { :root { --tone: #e5e7eb; } }\n")
    code, items, out = run(Y)
    assert code == 0, out


# R2-M13: ambiguity and importance through the variable graph; component stylesheet bindings

def test_ambiguity_through_the_dependency_graph(X):
    """R2-M13 (Sol's case): --ink: var(--ink-paint) with --ink-paint: #ff0000 !important and then --ink-paint: #1a1a2e:
    the bound variable is not ambiguous, a variable it reaches is (and is importance-dependent): never PASS for
    colors.ink; an importance-only link counts too."""
    sites.edit(F(X, "../site/x.css"), "--ink: #1a1a2e;", "--ink: var(--ink-paint); --ink-paint: #ff0000 !important; --ink-paint: #1a1a2e;")
    code, items, out = run(X)
    assert code != 0 and not [i for i in items if i["status"] == "PASS" and i["path"] == "colors.ink"], out
    assert [i for i in items if i["path"] == "colors.ink" and i["status"] in ("FAIL", "INCOMPLETE")], out
    sites.edit(F(X, "../site/x.css"), "--ink-paint: #ff0000 !important; --ink-paint: #1a1a2e;", "--ink-paint: #1a1a2e !important;")
    code, items, out = run(X)
    assert code != 0 and "!important" in out and not [i for i in items if i["status"] == "PASS" and i["path"] == "colors.ink"], out


def test_component_stylesheet_field_binds_to_its_selector(Y):
    """R2-M13 (B.3.3 step 5): when site.yaml names component stylesheets, a non-typography field they define (the
    card's radius) binds to the component selector; a field they do not define keeps its --comp- variable."""
    import yaml
    sites.write(F(Y, "../site/comp.css"), ".card { border-radius: 4px; }\n")
    sites.edit(F(Y, "site.yaml"), "policy_version: 1", "policy_version: 1\ncomponent_stylesheets: [../site/comp.css]")
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(sites.SCRIPTS, "generate_css.py"), "--site", Y, "--write"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    card = yaml.safe_load(open(F(Y, "trace-map.yaml"), encoding="utf-8"))["components"]["card"]
    assert card["rounded"] == {"sel": ".card", "prop": "border-radius", "ref": "{rounded.card}"}, card
    assert card["backgroundColor"] == {"var": "--comp-card-bg", "ref": "{colors.paper-light}"}, card
    code, items, out = run(Y)
    assert [i for i in items if i["path"] == "components.card.rounded" and i["status"] == "PASS"], out


# R2-M03: outputs never written through an existing name

def test_json_through_a_hard_link_is_refused(X, tmp_path):
    """R2-M03: check_design.py's --json destination that is a hard link is refused (ERROR 2), its other name unchanged."""
    other = tmp_path / "other.json"
    other.write_bytes(b"other bytes")
    j = tmp_path / "r.json"
    os.link(str(other), str(j))
    r = subprocess.run([sys.executable, "-I", "-B", CD, "--site", X, "--verify", "--json", str(j)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "hard link" in r.stdout and other.read_bytes() == b"other bytes", r.stdout


@pytest.mark.parametrize("kind", ["hard link", "symlink"])
def test_generator_refuses_a_linked_trace_map(Y, tmp_path, kind):
    """R2-M03: the generator reads and writes trace-map.yaml through the same validated name: a link there is refused
    and the file it points to keeps its bytes (symlinks skip where they cannot be made; hard links run everywhere)."""
    other = tmp_path / "elsewhere.yaml"
    other.write_bytes(open(F(Y, "trace-map.yaml"), "rb").read())
    before = other.read_bytes()
    os.remove(F(Y, "trace-map.yaml"))
    try:
        (os.link if kind == "hard link" else os.symlink)(str(other), F(Y, "trace-map.yaml"))
    except (OSError, NotImplementedError):
        pytest.skip("%s cannot be created here" % kind)
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(sites.SCRIPTS, "generate_css.py"), "--site", Y, "--write"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and ("hard link" in r.stdout + r.stderr or "link" in r.stdout + r.stderr), r.stdout + r.stderr
    assert other.read_bytes() == before
