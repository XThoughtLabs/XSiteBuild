"""Entry points (plan 0.4 B.9): every script with -I from an unrelated working directory through a path with spaces;
missing PyYAML, Playwright's Chromium give ERROR naming them; font_facts reads a font."""
import importlib.util
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import sites  # noqa: E402

SCRIPTS = ["check_design.py", "check_css.py", "check_page.py", "generate_css.py", "inventory_css.py", "font_facts.py"]
RUN_AS = ["--run-as", "claude"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []
# the two runs of check_page.py below need Playwright for this Python (where it is missing they cannot show their point)
NEEDS_PLAYWRIGHT = pytest.mark.skipif(importlib.util.find_spec("playwright") is None, reason="Playwright not installed")


@pytest.fixture(scope="module")
def spaced_plugin(tmp_path_factory):
    dst = tmp_path_factory.mktemp("plug") / "a plugin folder with spaces"
    shutil.copytree(os.path.dirname(sites.SCRIPTS), dst, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    os.chmod(tmp_path_factory.getbasetemp(), 0o755)
    for dirpath, dirs, files in os.walk(tmp_path_factory.getbasetemp()):
        os.chmod(dirpath, 0o755)
    return str(dst)


@pytest.mark.parametrize("script", SCRIPTS)
def test_help_from_other_cwd_and_spaced_path(spaced_plugin, script):
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(spaced_plugin, "scripts", script), "--help"],
                       cwd="/", capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "usage" in r.stdout.lower(), r.stdout + r.stderr


@NEEDS_PLAYWRIGHT
def test_check_page_runs_from_spaced_path(spaced_plugin, tmp_path):
    d = sites.build_x(tmp_path)
    # the receipt hashes the plugin's scripts: issue it with the copied plugin
    sites.git(d, "init", "-q")
    sites.git(d, "add", "-A")
    sites.git(d, "commit", "-qm", "p")
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(spaced_plugin, "scripts", "check_design.py"), "--site", d, "--issue"],
                       capture_output=True, text=True, cwd="/")
    assert r.returncode == 0, r.stdout
    sites.commit_receipt(d)                               # the owner commits the receipt (R2-H06)
    b = sites.bundle(d, "p", '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>t</title><link rel="stylesheet" href="x.css">'
                             '</head><body><main style="max-width: 600px"><p>Plain text.</p></main></body></html>')
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(spaced_plugin, "scripts", "check_page.py"), b, "--page", "index.html", "--site", d] + RUN_AS,
                       capture_output=True, text=True, cwd="/", timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr


@NEEDS_PLAYWRIGHT
def test_missing_chromium_is_error(tmp_path):
    d = sites.build_x(tmp_path)
    sites.issue(d)
    b = sites.bundle(d, "p", '<!doctype html><html lang="en"><head><title>t</title><link rel="stylesheet" href="x.css"></head><body><p>x</p></body></html>')
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(tmp_path / "no-browsers"))
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(sites.SCRIPTS, "check_page.py"), b, "--page", "index.html", "--site", d] + RUN_AS,
                       capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 2 and "browser unusable" in r.stdout, r.stdout


@pytest.mark.parametrize("module,argv", [("check_css", ["--site", "{d}", "--report", "{css}"]),
                                         ("check_page", ["{b}", "--page", "index.html", "--site", "{d}"])])
def test_missing_pyyaml_is_error(tmp_path, monkeypatch, capsys, module, argv):
    sys.path.insert(0, sites.SCRIPTS)
    import designlib as dl
    mod = __import__(module)
    d = sites.build_x(tmp_path)
    b = sites.bundle(d, "p", "<p>x</p>")
    monkeypatch.setattr(dl, "yaml", None)
    args = [a.format(d=d, b=b, css=os.path.join(os.path.dirname(d), "site", "x.css")) for a in argv]
    assert mod.main(args) == 2
    assert "PyYAML" in capsys.readouterr().out


@pytest.mark.skipif(not os.path.isfile(os.path.join(sites.FONT_DIR, "Poppins-Regular.ttf")), reason="test font missing")
@pytest.mark.parametrize("method", ["fonttools", "browser"])
def test_font_facts(method):
    f = os.path.join(sites.FONT_DIR, "Poppins-Regular.ttf")
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(sites.SCRIPTS, "font_facts.py"), f, "--method", method, "--ranges", "0x20-0x7F"],
                       capture_output=True, text=True, timeout=120)
    cov = [l for l in r.stdout.splitlines() if "coverage:" in l]
    assert r.returncode == 0 and "postscript: Poppins-Regular" in r.stdout and cov and "0x7E]" in cov[0], r.stdout + r.stderr
