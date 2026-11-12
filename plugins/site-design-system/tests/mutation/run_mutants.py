"""Mutation harness for the plugin's scripts (plan 0.4 B.9; the method of handoff-maker).

Each mutant in mutants.py is one exact textual change to one script. It is applied to a copy of the plugin in a
temporary folder, and only its killers (the tests of the assertion ID or stage it weakens) run there. Outcomes:
KILLED (a killer failed), SURVIVED (all killers passed), CRASH (collection or import error, pytest exit 2-5),
TIMEOUT, STALE (the old text does not occur exactly once). A baseline run of every killer on the unchanged copy
comes first; any baseline failure stops the run.

Usage, from the plugin root: python3 -B tests/mutation/run_mutants.py [--jobs N] [--only TEXT] [--out FILE]
Exit code: 0 every mutant killed; 1 a survivor, crash or timeout; 2 a stale anchor or a failing baseline."""
import argparse
import concurrent.futures
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from mutants import MUTANTS  # noqa: E402

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "mutation", ".pytest_cache")
TIMEOUT = 900


def pytest(folder, killers):
    # the child writes UTF-8 and its output is read as UTF-8 with replacement, so no printed text (a non-ASCII test
    # name, docstring or message, or bytes that are no text at all) can crash the runner in any code page (X4)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    try:
        done = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x"] + killers,
                              cwd=folder, capture_output=True, encoding="utf-8", errors="replace", env=env, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", ""
    lines = (done.stdout + done.stderr).strip().splitlines()
    failed = [l.split(" - ")[0].replace("FAILED ", "") for l in lines if l.startswith("FAILED ")]
    tail = (lines[-1:] or [""])[0]
    if done.returncode == 0:
        return "PASSED", tail
    if done.returncode == 1:
        return "FAILED", "killed by %s" % ", ".join(failed) if failed else tail
    return "CRASH", tail


def copy_plugin(tmp):
    dst = os.path.join(tmp, "plugin")
    shutil.copytree(PLUGIN, dst, ignore=IGNORE)
    os.chmod(tmp, 0o755)
    return dst


def run_one(m):
    origin, fname, name, old, new, killers = m
    with tempfile.TemporaryDirectory() as tmp:
        dst = copy_plugin(tmp)
        path = os.path.join(dst, "scripts", fname)
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(src.replace(old, new))
        result, tail = pytest(dst, killers)
    if result == "FAILED" and not tail.startswith("killed by"):
        result = "CRASH"            # exit 1 without a named failing killer: not counted as a kill
    outcome = {"FAILED": "KILLED", "PASSED": "SURVIVED"}.get(result, result)
    return origin, fname, name, outcome, tail


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the hand-written mutants against their killer tests.")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument("--only")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    todo = [m for m in MUTANTS if not a.only or a.only in m[2]]
    stale = []
    for m in todo:
        with open(os.path.join(PLUGIN, "scripts", m[1]), encoding="utf-8") as fh:
            n = fh.read().count(m[3])
        if n != 1:
            stale.append("%s: %s (anchor occurs %d times)" % (m[1], m[2], n))
    if stale:
        print("STALE\n  " + "\n  ".join(stale))
        return 2
    killers = sorted({k for m in todo for k in m[5]})
    with tempfile.TemporaryDirectory() as tmp:
        result, tail = pytest(copy_plugin(tmp), killers)
    if result != "PASSED":
        print("baseline of the killers did not pass: %s %s" % (result, tail))
        return 2
    t0 = time.time()
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for row in ex.map(run_one, todo):
            rows.append(row)
            print("%-9s %-16s %s" % (row[3], row[1], row[2]), flush=True)
    counts = {}
    for r in rows:
        counts[r[3]] = counts.get(r[3], 0) + 1
    summary = "mutants %d: %s; %.0f s" % (len(rows), ", ".join("%s %d" % kv for kv in sorted(counts.items())), time.time() - t0)
    print(summary)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write("# run_mutants.py results (plugin site-design-system 0.1.0)\n")
            for r in rows:
                fh.write("%-9s %-16s %-6s %s | %s\n" % (r[3], r[1], r[0], r[2], r[4]))
            fh.write(summary + "\n")
    return 0 if counts.get("KILLED", 0) == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
