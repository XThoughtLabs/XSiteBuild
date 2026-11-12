"""check_page.py — a rendered page against its site's design system (plan 0.4 B.8, as changed by J1).

Usage: check_page.py <bundle> --page <relative path> --site <site design folder> [--out DIR] [--run-as USER]
                     [--snapshot FILE | --kept FILE --kept-sha256 HEX] [--json FILE] [--no-git] [--receipt-sha256 HEX]
Order: the inputs (bundle, page, site design folder), the vendored axe-core's pins and Playwright are checked first
(ERROR, nothing read from the bundle); then the receipt (missing, invalid, stale or not committed: INCOMPLETE,
nothing rendered; with no Git repository approval counts only with --receipt-sha256); then the page's reference
closure is read, each file once through the guard shared with check_css.py (one portable path grammar), and its known
A10 findings are reported at once; the same bytes are staged (never script files) and only they are served from
127.0.0.1, with Content-Security-Policy script-src 'none' on every response, so page scripts never run (H1, J1);
Chromium renders the page four times (1280x800 and 390x844, light and dark, reduced motion, no contrast or
transparency preference) and the checker, which changes no checked document and never resizes the viewport, scrolls to
take each text run's evidence where it lies inside the viewport; after each render's evidence the page is loaded again,
fresh, in each of the 11 other combinations of reduced motion, contrast and reduced transparency, and a frame that
paints differently in any of them (its paints, read by one list for every comparison, or its border boxes) gives its
text A6 INCOMPLETE (W1, X1); a box-shadow, outline or border image that reaches a text run where it was evidenced, a
paint whose reach is not computed (a blur or drop-shadow filter, a reflection, a transformed painter) and, where only
axe passed the text, a filter on its ancestors give it A6 INCOMPLETE (X2); the vendored axe-core gives contrast (A6) and
accessibility (A12) verdicts; assertions A1-A13 take their values from policy.yaml.
Containment: on Linux the renderer runs in its own network namespace with only loopback up (containment: os; as
root it drops to --run-as USER, since Chromium's sandbox refuses root); elsewhere routing plus a dead proxy confine
it (containment: browser).
--snapshot FILE writes the page's structure (A13 entries) and prints its SHA-256, for a later --kept FILE
--kept-sha256 HEX run on its replacement.
Outcomes: PASS 0, FAIL 1, ERROR 2, INCOMPLETE 3, INTERNAL 4."""
import argparse
import collections
import html.parser
import http.server
import importlib.util
import json
import mimetypes
import os
import posixpath
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import bundlelib as bl  # noqa: E402
import csslite  # noqa: E402
import designlib as dl  # noqa: E402
import pagejs  # noqa: E402
import policylib as pl  # noqa: E402

VERSION = "0.1.0"
A13_RULE_VERSION = "a13-2"      # a13-2: fields credited to their owner, buttons to objects included (R2-M09)
AXE_VERSION = "4.14.0"
AXE_PINS = {"axe.min.js": "20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878",
            "axe.js": "aae0b8b36278089962105b2351ea64f4da7d3d440b54e162e21616d597aa0d6f"}
CSP = "script-src 'none'; object-src 'none'; base-uri 'none'; worker-src 'none'"
INITIATOR_RULES = ("document-title", "html-has-lang", "aria-hidden-body", "meta-viewport", "meta-viewport-large")   # axe 4.14.0
RENDERS = (("w1280-light", 1280, 800, "light"), ("w1280-dark", 1280, 800, "dark"),
           ("w390-light", 390, 844, "light"), ("w390-dark", 390, 844, "dark"))
# Budgets (plan 0.4 B.8.1): any truncation gives INCOMPLETE.
MAX_FILES, MAX_STAGE_BYTES = 500, 20_000_000
RUN_SECONDS, FONT_WAIT_MS, MAX_HEIGHT = 120, 5000, 20000
MAX_POSITIONS = 40               # scroll offsets per render; the text beyond them is "not inside the checked viewport" (R2-H02)
MAX_SHOTS, MAX_SHOT_BYTES, MAX_ITEMS, MAX_ARTEFACTS = 4 * MAX_POSITIONS, 10_000_000, 5000, 60_000_000
MAX_CAPTURE_PIXELS = 1280 * 844  # the largest viewport of RENDERS: a capture is never larger (R2-L02)
MAX_RESULT_BYTES = 100_000_000   # the renderer's result file: refused before it is written or loaded (AST-M18)
MAX_SRCDOC_DEPTH = 8             # srcdoc documents nested inside srcdoc documents (AST-M02)
MAX_CANDIDATES = 512             # A6 fallback backdrops; more gives INCOMPLETE, never a silent cut (AST-H05)
GRADIENT_STEPS = 16              # samples per gradient segment, endpoints included (sRGB, premultiplied; AST-H05)
MODES = {"os-root": "os", "os-user": "os", "browser": "browser"}   # the only containment modes (AST-M21)
READING_TAGS = ("p", "li", "blockquote", "dd", "figcaption", "td")
GEOMETRY = ("path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan")
# A served file is a font by its first bytes, whatever its name (AST-H06): WOFF2, WOFF, CFF OpenType, TrueType
# (version 1.0 and Apple's 'true'), collections
FONT_MAGIC = (b"wOF2", b"wOFF", b"OTTO", b"\x00\x01\x00\x00", b"true", b"ttcf")
SIDES = ("top", "right", "bottom", "left")
URL_ATTRS = ("href", "xlink:href", "src", "action", "formaction", "data", "poster", "background", "srcset")
GENERATED_TEXT = re.compile(r"[^\W_]", re.U)        # a letter or digit in generated content
# Reader preferences (W1): the evidence is taken in one state, EVIDENCE_PREFS; after it, each render's page is loaded
# again, fresh, in every other combination of these values, and every frame's PAINTS is compared with the evidence
# page's first read. forced-colors: active (and prefers-contrast: custom, which goes with it) is a stated limit: the
# user agent replaces the page's colours there.
PREFERENCES = (("prefers-reduced-motion", ("reduce", "no-preference")),
               ("prefers-contrast", ("no-preference", "more", "less")),
               ("prefers-reduced-transparency", ("no-preference", "reduce")))
EVIDENCE_PREFS = {"prefers-reduced-motion": "reduce", "prefers-contrast": "no-preference",
                  "prefers-reduced-transparency": "no-preference"}


class StageError(Exception):
    """A bundle that must not be rendered (ERROR)."""


# ================================================================== the reference closure (plan 0.4 B.8.1)

class RefParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs, self.css, self.scripts, self.objects, self.srcdocs = [], [], [], [], []
        self._style, self._buf, self._template = False, [], 0

    def handle_starttag(self, tag, attrs):
        if tag == "template":          # inert content: nothing in it is fetched, applied or run (R2-M11)
            self._template += 1
            return
        if self._template:
            return
        a = bl.first_attrs(attrs)      # the first of duplicate attributes, as Chromium reads it (AUD-F03(1))
        rel = set(a.get("rel", "").lower().split())
        if tag == "link" and a.get("href"):
            if "stylesheet" in rel:
                self.refs.append(("css", a["href"]))
            elif rel & {"icon", "apple-touch-icon", "preload", "prefetch", "manifest", "mask-icon"} and a.get("as") != "script":
                self.refs.append(("file", a["href"]))
        if tag in ("img", "source", "input", "video", "audio", "track") and a.get("src"):
            self.refs.append(("file", a["src"]))
        if tag in ("img", "source") and a.get("srcset"):
            for cand in a["srcset"].split(","):
                if cand.strip():
                    self.refs.append(("file", cand.strip().split()[0]))
        if tag == "video" and a.get("poster"):
            self.refs.append(("file", a["poster"]))
        if tag == "iframe":
            if a.get("src"):
                self.refs.append(("html", a["src"]))
            if "srcdoc" in a:
                self.srcdocs.append(a["srcdoc"])
        if tag in ("object", "embed"):
            self.objects.append(tag)
        if tag == "script":
            self.scripts.append("<script %s>" % (a.get("src") or "inline"))
        for k, v in a.items():                      # inline handlers and javascript: URLs are scripts too
            if k.startswith("on"):
                self.scripts.append("<%s %s>" % (tag, k))
            elif k in URL_ATTRS and re.sub(r"[\t\n\r]", "", v.strip(" \x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f\x10\x11\x12"
                                                                     "\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f")).lower().startswith("javascript:"):
                self.scripts.append("<%s %s=javascript:>" % (tag, k))
        if tag == "meta" and a.get("http-equiv", "").strip().lower() == "refresh":
            self.scripts.append("<meta http-equiv=refresh>")   # replaces the document between checks, like a script
        if tag in ("image", "use", "feimage"):
            h = a.get("href") or a.get("xlink:href")
            if h and not h.startswith("#"):
                self.refs.append(("file", h))
        if a.get("style"):
            self.css.append(a["style"])
        if tag == "style":
            self._style, self._buf = True, []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "template" and self._template:
            self._template -= 1
            return
        if tag == "style" and self._style:
            self.css.append("".join(self._buf))
            self._style = False

    def handle_data(self, data):
        if self._style and not self._template:
            self._buf.append(data)


CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
CSS_IMPORT = re.compile(r"@import\s+(?:url\(\s*)?['\"]?([^'\")\s;]+)", re.I)
FONT_FACE = re.compile(r"@font-face\s*\{", re.I)


def _css_string_end(text, i):
    """The index just after the CSS string that starts at text[i] (a quote); escapes skipped; a newline ends it."""
    q, j = text[i], i + 1
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == q or text[j] == "\n":
            return j + 1
        j += 1
    return j


def _css_url(text, i):
    """(reference, end) of the url( token at text[i]: its quoted or unquoted argument."""
    j = i + 4
    while j < len(text) and text[j] in " \t\r\n\f":
        j += 1
    if j < len(text) and text[j] in "\"'":
        e = _css_string_end(text, j)
        ref = text[j + 1:e - 1]
        k = text.find(")", e)
        return ref, (k + 1 if k >= 0 else len(text))
    k = text.find(")", j)
    k = len(text) if k < 0 else k
    return text[j:k].strip(), k + 1


def css_refs(text):
    """References of a stylesheet by token (R2-M11): comments stripped first (AST-H01); a url() token or the string or
    url() of an @import is a reference; a url( written inside another string (generated content, a font name) never
    is. Kinds: 'css' for an @import, 'file' otherwise."""
    text = csslite.strip_comments(text)
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            i = _css_string_end(text, i)          # a string's content is no reference
            continue
        if ch == "@" and text[i:i + 7].lower() == "@import":
            j = i + 7
            while j < n and text[j] in " \t\r\n\f":
                j += 1
            if j < n and text[j] in "\"'":
                e = _css_string_end(text, j)
                if text[j + 1:e - 1].strip():
                    out.append(("css", text[j + 1:e - 1].strip()))
                i = e
                continue
            if text[j:j + 4].lower() == "url(":
                ref, i = _css_url(text, j)
                if ref:
                    out.append(("css", ref))
                continue
        if text[i:i + 4].lower() == "url(" and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "-_")):
            ref, i = _css_url(text, i)
            if ref:
                out.append(("file", ref))
            continue
        i += 1
    return out


def is_svg(rel, data):
    """An SVG document of the closure, by its name or its first bytes (R2-M11)."""
    return rel.lower().endswith(".svg") or b"<svg" in data[:1024].lower()


def font_sources(text):
    """(sources, readable): every source of every @font-face block of a stylesheet, wherever it is nested: ('url', ref)
    or ('local', name). readable is False when a block's braces do not balance."""
    text = csslite.strip_comments(text)
    out = []
    for m in FONT_FACE.finditer(text):
        try:
            end = csslite.match_brace(text, m.end() - 1)
        except ValueError:
            return out, False
        for decl in csslite.split_top(text[m.end():end], ";"):
            if ":" in decl and decl.split(":", 1)[0].strip().lower() == "src":
                value = decl.split(":", 1)[1]
                out += [("url", u.group(2).strip()) for u in CSS_URL.finditer(value)]
                out += [("local", x.strip()) for x in re.findall(r"local\(([^)]*)\)", value, re.I)]
    return out, True


def classify_ref(ref, base_rel_dir, bundle):
    """('skip'|'remote'|'outside'|'local', value): bundlelib's resolver, shared with check_css.py (AUD-F03(2)); for
    'local' the value is the bundle-relative path."""
    return bl.resolve_ref(ref, base_rel_dir, bundle)


def parse_document(text, rel, depth, res):
    """The references, inline CSS, scripts and objects of one HTML document and of its srcdoc documents, recursively
    within MAX_SRCDOC_DEPTH (AST-M02). Returns (refs, css texts)."""
    pr = RefParser()
    pr.feed(text)
    refs, css = list(pr.refs), list(pr.css)
    res["objects"] += len(pr.objects)
    res["scripts"] += ["%s: %s" % (rel if depth == 0 else "%s (srcdoc, level %d)" % (rel, depth), s) for s in pr.scripts]
    for doc in pr.srcdocs:
        if depth + 1 > MAX_SRCDOC_DEPTH:
            res["srcdoc_over"] = True
            continue
        r2, c2 = parse_document(doc, rel, depth + 1, res)
        refs += r2
        css += c2
    return refs, css


def closure(bundle, page_rel, guard):
    """The page's reference closure. Each file is read once through the guard (no link followed; names, private bytes
    and hard links refused) and its bytes kept: the same bytes are parsed, hashed and staged (AST-H02). Parsing is
    deduplicated by (kind, path), so a file first met as a plain file is still parsed as a frame document (AST-M02)."""
    res = {"files": {}, "missing": [], "outside": [], "remote": [], "objects": 0, "scripts": [], "bytes": 0,
           "font_sources": [], "font_unread": []}
    try:
        root = bl.BundleRoot(bundle)      # one trusted root for every read of the closure, never reopened by path (R2-M01)
    except ValueError as exc:
        raise StageError(str(exc))
    try:
        return _closure(bundle, root, page_rel, guard, res)
    finally:
        root.close()


def _closure(bundle, root, page_rel, guard, res):
    queue, seen = [("html", page_rel, None)], set()
    while queue:
        kind, rel, referrer = queue.pop(0)
        if (kind, rel) in seen:
            continue
        seen.add((kind, rel))
        data = res["files"].get(rel)
        if data is None:
            data, why = guard.read(root, rel, MAX_STAGE_BYTES - res["bytes"])
            if why == bl.MISSING:
                res["missing"].append((rel, referrer))
                continue
            if why:
                raise StageError(why)
            res["files"][rel] = data
            res["bytes"] += len(data)
            if len(res["files"]) > MAX_FILES or res["bytes"] > MAX_STAGE_BYTES:
                res["over"] = True
                return res
        refs, base, css_texts = [], posixpath.dirname(rel), []
        if kind == "file" and is_svg(rel, data):
            # every SVG file of the closure is scanned for scripts and event handlers, however it is used (R2-M11)
            svg = RefParser()
            svg.feed(data.decode("utf-8", "replace"))
            res["scripts"] += ["%s (SVG): %s" % (rel, s) for s in svg.scripts]
        if kind == "html":
            refs, css_texts = parse_document(data.decode("utf-8", "replace"), rel, 0, res)
        elif kind == "css":
            css_texts = [data.decode("utf-8", "replace")]
        for text in css_texts:
            refs += css_refs(text)
            found, readable = font_sources(text)
            res["font_sources"] += [(k, v, rel) for k, v in found]
            if not readable:
                res["font_unread"].append(rel)
        for k, ref in refs:
            cls, value = classify_ref(ref, base, bundle)
            if cls == "remote":
                res["remote"].append((ref, rel))
            elif cls == "outside":
                res["outside"].append((ref, rel))
            elif cls == "local":
                queue.append((k if k != "file" or not value.lower().endswith((".css",)) else "css", value, rel))
    return res


def stage_files(bundle, files, stage):
    """Write the closure's bytes (read once by closure()) into the new stage folder; nothing is read from the bundle
    again (AST-H02). The bundle is named in errors only."""
    for rel, data in sorted(files.items()):
        dst = os.path.join(stage, *rel.split("/"))
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
            with os.fdopen(fd, "wb") as fout:
                fout.write(data)
        except OSError as exc:
            raise StageError("%s of %s could not be staged: %s" % (rel, bundle, exc.strerror or exc))


# ================================================================== the renderer (runs in the child process)

def served_key(raw_path, inventory):
    """(key, None) when a request's percent-decoded path, without its one leading '/', is byte-equal to a key of the
    staged inventory; else (None, why). No normalisation: '.' or '..' segments, '//', an encoded '/' or '\\', or a case
    variant name no key (R2-H04); a key outside the job's inventory is never served (R2-M12). raw_path is the target
    of the request line as sent (http.server collapses a leading '//' in self.path; the request line keeps it)."""
    path = urllib.parse.unquote(raw_path.split("#", 1)[0].split("?", 1)[0])
    if not path.startswith("/"):
        return None, "not an absolute path"
    key = path[1:]
    if key not in inventory:
        return None, "not a key of the staged inventory"
    if bl.path_problem(key):
        return None, "refused by the component grammar"
    return key, None


def make_server(root, log, inventory):
    """The loopback server of the staged closure: it serves only the keys of the job's inventory, each read from the
    stage and sent only when its SHA-256 equals the inventory's (R2-M12), and logs for every response the exact staged
    key it served and the SHA-256 of the bytes it sent (R2-H04); anything else is 404, logged as refused."""
    root = os.path.realpath(root)
    inventory = dict(inventory)

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version, sys_version = "sds", ""

        def _send(self, code, data=b"", ctype="text/plain; charset=utf-8", body=True):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if body and data:
                self.wfile.write(data)

        def _serve(self, body):
            words = (self.requestline or "").split()
            raw = words[1] if len(words) >= 2 else self.path        # the target as sent, before http.server's clean-up
            path = urllib.parse.unquote(raw.split("#", 1)[0].split("?", 1)[0])
            key, why = served_key(raw, inventory)
            data = None
            if key is not None:
                data, why = bl.safe_read(root, key, MAX_STAGE_BYTES)
                if why is None and dl.sha256(data) != inventory[key]:
                    data, why = None, "the staged bytes differ from the inventory's SHA-256"
            if data is None:
                log.append({"path": path, "status": 404, "key": None, "sha256": None, "refused": why or "unreadable"})
                return self._send(404, b"not found", body=body)
            ctype = "font/woff2" if key.endswith(".woff2") else (mimetypes.guess_type(key)[0] or "application/octet-stream")
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            log.append({"path": path, "status": 200, "key": key, "sha256": dl.sha256(data)})   # the key served, not the request
            self._send(200, data, ctype, body)

        def end_headers(self):
            # every response, send_error's 400/414/501 included, carries the policy (J1)
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_GET(self):
            self._serve(True)

        def do_HEAD(self):
            self._serve(False)

        def do_POST(self):
            log.append({"path": self.path, "status": 405, "key": None, "sha256": None, "refused": "method"})
            self._send(405, b"no")

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_POST

        def log_message(self, *args):
            pass

    return http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def tree_elements(doc):
    """The element nodes of one CDP document node in tree order, light DOM only: the order of
    document.querySelectorAll('*') (shadow roots, template content, pseudo-elements and frame documents are separate
    fields of a CDP node and are not walked)."""
    out, stack = [], list(reversed(doc.get("children") or []))
    while stack:
        n = stack.pop()
        if n.get("nodeType") == 1:
            out.append(n)
            stack.extend(reversed(n.get("children") or []))
    return out


class FontReader:
    """CDP font evidence by element identity, with no marker in the DOM (R2-H02): the CDP document tree is read once;
    element i of frame k is the i-th element of that frame's CDP document in tree order; a child frame's CDP document is
    the contentDocument of its frame element, found by the element's index in its parent frame."""

    def __init__(self, ctx, page, frames):
        self.cdp = ctx.new_cdp_session(page)
        self.cdp.send("DOM.enable")
        self.cdp.send("CSS.enable")
        root = self.cdp.send("DOM.getDocument", {"depth": -1, "pierce": True})["root"]
        self.shadows, stack = [], [root]
        while stack:
            n = stack.pop()
            stack.extend(n.get("children") or [])
            for sr in n.get("shadowRoots") or []:
                if sr.get("shadowRootType") != "user-agent":
                    self.shadows.append("%s (%s)" % (n.get("localName") or n.get("nodeName"), sr.get("shadowRootType")))
                stack.append(sr)
            if n.get("contentDocument"):
                stack.append(n["contentDocument"])
        keys = {fr: "f%d" % i for i, fr in enumerate(frames)}
        docs = {keys[page.main_frame]: root} if page.main_frame in keys else {}
        pending, moved = [fr for fr in frames if fr != page.main_frame], True
        while pending and moved:
            moved = False
            for fr in list(pending):
                pk = keys.get(fr.parent_frame)
                if pk is not None and pk not in docs:
                    continue                       # its parent's document is not mapped yet
                pending.remove(fr)
                moved = True
                if pk is None:
                    continue
                try:
                    idx = fr.parent_frame.evaluate("(el) => Array.prototype.indexOf.call(document.querySelectorAll('*'), el)",
                                                   fr.frame_element())
                except Exception:  # noqa: BLE001
                    continue
                els = tree_elements(docs[pk])
                if isinstance(idx, int) and 0 <= idx < len(els) and els[idx].get("contentDocument"):
                    docs[keys[fr]] = els[idx]["contentDocument"]
        self.nodes = {k: [n["nodeId"] for n in tree_elements(d)] for k, d in docs.items()}

    def read(self, ids):
        out = {}
        for sid in ids:
            key, _, idx = sid.rpartition(":")
            nodes = self.nodes.get(key) or []
            if idx.isdigit() and int(idx) < len(nodes):
                try:
                    out[sid] = self.cdp.send("CSS.getPlatformFontsForNode", {"nodeId": nodes[int(idx)]})["fonts"]
                except Exception as exc:  # noqa: BLE001
                    out[sid] = {"error": str(exc)}
        return out

    def close(self):
        self.cdp.detach()


def paint_diff(before, now):
    """The indexes of the elements whose paint signature differs between two PAINTS reads of one frame; None when the
    element lists differ in length (every element counts as changed)."""
    if before is None or now is None or len(before) != len(now):
        return None
    return [i for i, (x, y) in enumerate(zip(before, now)) if x != y]


def preference_states():
    """Every combination of the PREFERENCES values except the evidence state, in a fixed order (W1)."""
    states = [{}]
    for feature, values in PREFERENCES:
        states = [{**s, feature: v} for s in states for v in values]
    return [s for s in states if s != EVIDENCE_PREFS]


def preference_label(state):
    """The features in which a state differs from the evidence state, as 'feature: value', joined by commas (W1)."""
    return ", ".join("%s: %s" % (f, state[f]) for f, _ in PREFERENCES if state[f] != EVIDENCE_PREFS[f])


def media_features(scheme, prefs):
    """The emulated media features of one page: the render's colour scheme and the reader preferences (W1)."""
    return [["prefers-color-scheme", scheme]] + [[f, prefs[f]] for f, _ in PREFERENCES]


def preference_changes(urls, before, boxes, fresh_urls, fresh, fresh_boxes):
    """The frame keys whose paint differs in a fresh load (W1, X1): urls, before and boxes are the evidence page's
    checked frames, their first PAINTS reads and their first BOXES reads (offset 0); fresh_urls, fresh and fresh_boxes
    the fresh page's (offset 0 too, so border boxes compare directly). A different frame list changes every frame;
    otherwise a frame changes when paint_diff finds a changed element or a different element list in its paints or in
    its border boxes."""
    keys = ["f%d" % i for i in range(len(urls))]
    if list(urls) != list(fresh_urls) or len(before) != len(fresh) or len(boxes) != len(fresh_boxes):
        return keys
    return [k for k, b, a, bx, fx in zip(keys, before, fresh, boxes, fresh_boxes)
            if paint_diff(b, a) != [] or paint_diff(bx, fx) != []]


def checked_frames(page, origin):
    """The frames whose documents are checked: the staged origin's, srcdoc and blank ones (others are listed apart)."""
    return [f for f in page.frames if f.url.startswith(origin + "/") or f.url in ("about:srcdoc", "about:blank")]


def scroll_plan(extents, page_h, view_h, limit=None):
    """The main frame's scroll offsets that bring every text run of the main frame wholly into the viewport at least
    once (R2-H02): extents are the runs' (top, bottom) in page coordinates read at offset 0. Offset 0 comes first; no
    offset passes min(page_h, limit) - view_h; a run taller than the viewport, or below the limit, fits nowhere; at most
    MAX_POSITIONS offsets (the caller reports a cut)."""
    limit = MAX_HEIGHT if limit is None else limit
    max_y = max(0, int(min(page_h, limit) - view_h))
    out = [0]
    for top, bottom in sorted(extents):
        cur = out[-1]
        if top >= cur and bottom <= cur + view_h:
            continue
        if bottom - top > view_h or bottom > limit:
            continue
        y = min(max(0, int(top)), max_y)
        if y > cur and top >= y and bottom <= y + view_h:
            out.append(y)
    return out


def merge_axe(results):
    """One color-contrast result from the results of every scroll position (R2-H02): each node counts from the first
    position where its element lay wholly inside the viewport (axe computes from geometry, so a verdict on text outside
    the viewport is not taken); a node axe could not tie to an element is kept once. A rule named at any position stays
    named (execution evidence); it is inapplicable only when no position applied it."""
    merged = {"passes": [], "violations": [], "incomplete": [], "inapplicable": []}
    if not results:
        return {"error": "no scroll position was checked"}
    for res in results:
        if res.get("error"):
            return {"error": res["error"]}
    taken, rules, applied = set(), {}, set()
    for res in results:
        for kind in ("violations", "passes", "incomplete"):       # a violation first within one position
            for rule in res.get(kind) or []:
                applied.add(rule["id"])
                if (kind, rule["id"]) not in rules:
                    rules[(kind, rule["id"])] = {"id": rule["id"], "impact": rule.get("impact"), "tags": rule.get("tags"), "nodes": []}
                    merged[kind].append(rules[(kind, rule["id"])])
                for node in rule.get("nodes") or []:
                    key = (rule["id"], node.get("id") or json.dumps(node.get("target")))
                    if key in taken or (node.get("id") and not node.get("inside")):
                        continue
                    taken.add(key)
                    rules[(kind, rule["id"])]["nodes"].append(node)
    for res in results:
        for rid in res.get("inapplicable") or []:
            if rid not in applied and rid not in merged["inapplicable"]:
                merged["inapplicable"].append(rid)
    return merged


def capture(page, job, name, y, w, h, result, shots):
    """A viewport-size capture at the current scroll position (R2-H02(5)): its pixel area is the viewport's, bounded
    before the capture (R2-L02); its bytes count in the one artefact budget with the screenshots before it."""
    if w * h > MAX_CAPTURE_PIXELS or len(result["screenshots"]) >= MAX_SHOTS:
        result["truncated"].append("%s: capture at %d px over the artefact budget; not taken" % (name, y))
        return
    png = page.screenshot()
    if len(png) > MAX_SHOT_BYTES or shots["bytes"] + len(png) > MAX_ARTEFACTS:
        result["truncated"].append("%s: capture at %d px of %d bytes over the artefact budget; not written" % (name, y, len(png)))
        return
    shot = os.path.join(job["out"], (name if y == 0 else "%s-at-%05d" % (name, y)) + ".png")
    dl.write_output(shot, png)
    shots["bytes"] += len(png)
    result["screenshots"].append(shot)


def render_evidence(ctx, page, origin, job, spec, axe_src, result, shots):
    """Every piece of evidence of one render, with the document never changed (R2-H02): the first PAINTS read; COLLECT;
    then the main frame scrolled (never the viewport resized) to each offset of scroll_plan(), where every frame's PAINTS
    are compared with the first read, axe gives color-contrast, and each text run wholly inside the viewport (and not
    yet seen) gets its overlap and font evidence; a viewport capture at each offset; A12 at offset 0; a last PAINTS read."""
    name, w, h, scheme = spec
    rd = {"name": name, "width": w, "height": h, "scheme": scheme, "frames": [], "positions": []}
    rd["fonts_ready"] = page.evaluate(pagejs.FONTS_READY, FONT_WAIT_MS)
    frames = checked_frames(page, origin)
    rd["unchecked_frames"] = [f.url[:120] for f in page.frames if f not in frames]
    keys = ["f%d" % i for i in range(len(frames))]
    before = [fr.evaluate(pagejs.PAINTS) for fr in frames]      # the first read, before any evidence (AST-H03)
    boxes = [fr.evaluate(pagejs.BOXES) for fr in frames]        # the border boxes at offset 0, for the fresh loads (X1)
    for i, fr in enumerate(frames):
        data = fr.evaluate(pagejs.COLLECT, {"frame": keys[i], "selectors": job["selectors"]})
        rd["frames"].append({"key": keys[i], "url": fr.url, "main": fr == page.main_frame, "data": data, "paints_before": before[i],
                             "boxes_before": boxes[i]})
    page_h = rd["frames"][0]["data"]["height"] if rd["frames"] else h
    rd["page_height"] = page_h
    if page_h > MAX_HEIGHT:
        result["truncated"].append("%s: page height %d px checked to %d px" % (name, page_h, MAX_HEIGHT))
    runs = {fd["key"]: [e["id"] for e in fd["data"]["elements"] if e["visible"] and e["text"] and e["text_rects"]] for fd in rd["frames"]}
    main = next((fd for fd in rd["frames"] if fd["main"]), None)
    extents = [(min(q[1] for q in e["text_rects"]), max(q[1] + q[3] for q in e["text_rects"]))
               for e in (main["data"]["elements"] if main else []) if e["visible"] and e["text"] and e["text_rects"]]
    positions = scroll_plan(extents, page_h, h)
    if len(positions) > MAX_POSITIONS:
        result["truncated"].append("%s: %d scroll positions needed, %d checked" % (name, len(positions), MAX_POSITIONS))
        positions = positions[:MAX_POSITIONS]
    fonts = FontReader(ctx, page, frames)
    rd["shadow_roots"], rd["fonts"] = fonts.shadows, {}
    seen = {k: {"axe": [], "overlap": {}, "changed": set(), "all": False, "geometry": []} for k in keys}
    try:
        for fr in frames:
            fr.evaluate(axe_src + "\n;0")
        for pos, y in enumerate(positions):
            rd["positions"].append(page.evaluate(pagejs.SCROLL, y)[1])
            for i, fr in enumerate(frames):         # every position against the first read (R2-H02(3))
                diff = paint_diff(before[i], fr.evaluate(pagejs.PAINTS))
                if diff is None:
                    seen[keys[i]]["all"] = True
                else:
                    seen[keys[i]]["changed"].update(diff)
            for i, fr in enumerate(frames):
                k, s = keys[i], seen[keys[i]]
                s["axe"].append(fr.evaluate(pagejs.AXE_RUN, {"frame": k, "options": {"runOnly": {"type": "rule", "values": ["color-contrast"]}, "iframes": False}}))
                todo = [x for x in runs[k] if x not in s["overlap"]]
                inside = fr.evaluate(pagejs.INSIDE, {"ids": todo}) if todo else []
                if inside:
                    s["overlap"].update(fr.evaluate(pagejs.OVERLAP, {"frame": k, "ids": inside}))
                    s["geometry"].append(fr.evaluate(pagejs.UNSEEN, {"frame": k, "ids": inside}))    # where they are evidenced (X2)
                    rd["fonts"].update(fonts.read(inside))
                if pos == 0 and job["tags"] is not None:        # both schemes (AST-M15)
                    rules = {"color-contrast": {"enabled": False}}
                    if fr != page.main_frame:      # rules about the top document only (axe's is-initiator-matches)
                        rules.update({r: {"enabled": False} for r in INITIATOR_RULES})
                    rd["frames"][i]["axe_a11y"] = fr.evaluate(pagejs.AXE_RUN, {"frame": k, "options": {
                        "runOnly": {"type": "tag", "values": job["tags"]}, "rules": rules, "iframes": False}})
                    rd["frames"][i]["axe_rules"] = fr.evaluate(pagejs.AXE_RULES, job["tags"])     # the expected rules (R2-M08)
            capture(page, job, name, y, w, h, result, shots)
    finally:
        fonts.close()
    for i, fr in enumerate(frames):
        fd, s = rd["frames"][i], seen[keys[i]]
        fd["axe_contrast"] = merge_axe(s["axe"])
        fd["overlap"] = s["overlap"]
        fd["geometry"] = s["geometry"]
        fd["paint_changes"] = "all" if s["all"] else sorted(s["changed"])
        fd["paints_after"] = fr.evaluate(pagejs.PAINTS)   # after every scroll, capture, CDP read, axe run and overlap
    return rd


def fresh_state(open_page, origin, rd, prefs):
    """W1: the render's page loaded again, fresh (a new context, never a switch on the live page, where a transition
    could hold the old value), in one other reader-preference state: whether that state was in effect, and the checked
    frames whose first PAINTS or BOXES read differs from the evidence page's first read (X1)."""
    ctx, page, feats, _cdp = open_page(rd["width"], rd["height"], rd["scheme"], prefs)
    try:
        ready = page.evaluate(pagejs.FONTS_READY, FONT_WAIT_MS)
        frames = checked_frames(page, origin)
        urls = [fr.url for fr in frames]
        paints = [fr.evaluate(pagejs.PAINTS) for fr in frames]
        boxes = [fr.evaluate(pagejs.BOXES) for fr in frames]
        in_effect = ready == "ready" and all(page.evaluate(pagejs.MEDIA, feats))
    finally:
        ctx.close()
    changed = preference_changes([fd["url"] for fd in rd["frames"]], [fd["paints_before"] for fd in rd["frames"]],
                                 [fd.get("boxes_before") for fd in rd["frames"]], urls, paints, boxes)
    return {"label": preference_label(prefs), "confirmed": in_effect, "changed": changed}


def render(job):
    log = []
    srv = make_server(job["stage"], log, job["inventory"])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    origin = "http://127.0.0.1:%d" % srv.server_address[1]
    url = origin + "/" + urllib.parse.quote(job["page"])
    with open(job["axe"], encoding="utf-8") as fh:
        axe_src = fh.read()
    if dl.sha256(axe_src.encode("utf-8")) != AXE_PINS["axe.min.js"]:
        raise RuntimeError("axe.min.js changed between the check and the run")
    from playwright.sync_api import sync_playwright
    result = {"origin": origin, "renders": [], "requests": [], "failed": [], "websockets": [], "aborted": [],
              "popups": 0, "downloads": 0, "truncated": [], "screenshots": []}
    browser_mode = job["containment"] == "browser"
    shots = {"bytes": 0}

    def route_filter(route):
        u = route.request.url
        if u.startswith(origin + "/") or u.startswith(("data:", "blob:")):
            return route.continue_()
        result["aborted"].append(u)
        return route.abort("blockedbyclient")

    def ws_filter(ws):
        result["aborted"].append(ws.url)
        ws.close()

    with sync_playwright() as p:
        launch = {"chromium_sandbox": True}
        if browser_mode:
            # <-loopback> first (Playwright would add it last, where it overrides the origin rule): every host and every
            # other loopback port goes to this dead proxy; only the checker's own origin bypasses it
            launch["proxy"] = {"server": "http://127.0.0.1:9", "bypass": "<-loopback>, 127.0.0.1:%d" % srv.server_address[1]}
        browser = p.chromium.launch(**launch)

        def open_page(w, h, scheme, prefs):
            """A new context and page loaded in one reader-preference state, with the containment of every load (the
            route filter, the launch's dead proxy, no service workers, downloads or popups; every request logged). The
            state is pinned by CDP before the load, so the host's own settings never decide it; the CDP session stays
            attached until the context closes (W1)."""
            ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme,
                                      reduced_motion=prefs["prefers-reduced-motion"], service_workers="block", accept_downloads=False)
            if browser_mode:
                ctx.route("**/*", route_filter)
                ctx.route_web_socket(re.compile(".*"), ws_filter)
            page = ctx.new_page()
            ctx.on("page", lambda pg: (result.__setitem__("popups", result["popups"] + 1), pg.close()))
            page.on("request", lambda r: result["requests"].append(r.url))
            page.on("requestfailed", lambda r: result["failed"].append([r.url, r.failure]))
            page.on("websocket", lambda ws: result["websockets"].append(ws.url))
            page.on("download", lambda d: (result.__setitem__("downloads", result["downloads"] + 1), d.cancel()))
            feats = media_features(scheme, prefs)
            cdp = ctx.new_cdp_session(page)
            cdp.send("Emulation.setEmulatedMedia", {"media": "", "features": [{"name": f, "value": v} for f, v in feats]})
            page.goto(url, wait_until="load", timeout=30000)
            return ctx, page, feats, cdp

        for name, w, h, scheme in RENDERS:
            ctx, page, feats, _cdp = open_page(w, h, scheme, EVIDENCE_PREFS)
            rd = render_evidence(ctx, page, origin, job, (name, w, h, scheme), axe_src, result, shots)
            in_effect = all(page.evaluate(pagejs.MEDIA, feats))      # the evidence state held through the evidence
            ctx.close()
            # every other reader-preference state, each in a fresh load compared with the first read (W1)
            rd["preferences"] = {"evidence": {"confirmed": in_effect},
                                 "states": [fresh_state(open_page, origin, rd, s) for s in preference_states()]}
            result["renders"].append(rd)
        browser.close()
    srv.shutdown()
    result["access_log"] = log
    return result


def lo_up():
    import fcntl
    import socket
    import struct
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ifr = struct.pack("16sh", b"lo", 0)
    flags = struct.unpack("16sh", fcntl.ioctl(s, 0x8913, ifr))[1]          # SIOCGIFFLAGS
    fcntl.ioctl(s, 0x8914, struct.pack("16sh", b"lo", flags | 0x1))        # SIOCSIFFLAGS, IFF_UP
    s.close()


def job_problem(job, job_path):
    """None, or why a job must not be rendered: a mode other than the exact supported ones, or folders that are not the
    parent's own staging folder beside this job file (AST-M21)."""
    if job.get("containment") not in MODES:
        return "unknown containment mode %r" % job.get("containment")
    base = os.path.realpath(os.path.dirname(os.path.abspath(job_path)))
    if not os.path.basename(base).startswith("sds-page-"):
        return "the job file is not in a staging folder made by check_page.py"
    for key, name in (("stage", "site"), ("out", "out"), ("home", "home")):
        if not isinstance(job.get(key), str) or os.path.realpath(job[key]) != os.path.join(base, name):
            return "the job's %s is not the staging folder's %s" % (key, name)
    if not result_path_ok(job, job_path):
        return "the job's result is not the staging folder's out/result.json"
    inv = job.get("inventory")
    if not isinstance(inv, dict) or not all(isinstance(k, str) and k and not bl.path_problem(k) and isinstance(v, str)
                                            and dl.SHA256_HEX.match(v) for k, v in inv.items()):
        return "the job's inventory is not a mapping of staged keys to SHA-256 digests (R2-M12)"
    return None


def result_path_ok(job, job_path):
    """True when the job's result is out/result.json of the staging folder (made by check_page.py) that holds the job
    file: the only place the child ever writes, even for a refused job (AST-M21, HQ's C4)."""
    base = os.path.realpath(os.path.dirname(os.path.abspath(job_path)))
    return (isinstance(job, dict) and os.path.basename(base).startswith("sds-page-") and isinstance(job.get("result"), str)
            and os.path.realpath(job["result"]) == os.path.join(base, "out", "result.json"))


KEPT_LIST = ("requests", "aborted", "websockets", "failed", "access_log", "truncated")
MAX_KEPT, MAX_KEPT_TEXT = 1000, 2000      # entries kept per list of an oversized result, characters kept per entry


def bounded_result(result, why):
    """What an oversized renderer result keeps (R2-M10): the evidence of A10 (requests, aborted requests, web sockets,
    failures, the access log) and the budget notes, each list cut to MAX_KEPT entries of at most MAX_KEPT_TEXT
    characters, with its full count; the renders are dropped (the parent reports what they feed INCOMPLETE)."""
    def cut(x):
        if isinstance(x, str):
            return x[:MAX_KEPT_TEXT]
        if isinstance(x, dict):
            return {k: cut(v) for k, v in list(x.items())[:20]}
        if isinstance(x, list):
            return [cut(v) for v in x[:20]]
        return x
    out = {"over_budget": why, "containment": result.get("containment"), "origin": result.get("origin"), "counts": {}}
    for k in KEPT_LIST:
        lst = result.get(k) or []
        out[k] = [cut(v) for v in lst[:MAX_KEPT]]
        out["counts"][k] = len(lst)
    return out


def report_bounded(rep, res):
    """The known A10 failures of an oversized result stay FAIL; what was cut or dropped is INCOMPLETE (R2-M10)."""
    rep.add("INCOMPLETE", "BUDGET", "result", "%s: the renders are not kept, so every assertion they feed is not checked" % res["over_budget"])
    origin = (res.get("origin") or "") + "/"
    for u in sorted({u for k in ("requests", "aborted", "websockets") for u in res.get(k) or [] if isinstance(u, str)}):
        if not u.startswith((origin, "data:", "blob:", "about:")):
            rep.add("FAIL", "A10", u[:120], "request outside the loopback origin attempted (%s)" % res.get("containment"), floor=True)
    for entry in res.get("access_log") or []:
        if isinstance(entry, dict) and entry.get("status") == 404 and entry.get("path") != "/favicon.ico":
            rep.add("FAIL", "A10", str(entry.get("path"))[:120], "requested local file not in the staged closure", floor=True)
    for k, n in sorted((res.get("counts") or {}).items()):
        if n > len(res.get(k) or []):
            rep.add("INCOMPLETE", "BUDGET", k, "%d of %d entries kept from the oversized result" % (len(res.get(k) or []), n))


def artefact_room(result):
    """The bytes left for the result file in the one artefact budget the captures already used (R2-L02)."""
    used = sum(os.path.getsize(x) for x in result.get("screenshots") or [] if isinstance(x, str) and os.path.isfile(x))
    return max(0, MAX_ARTEFACTS - used)


def child_main(job_path):
    with open(job_path, encoding="utf-8") as fh:
        job = json.load(fh)
    result = {}
    try:
        why = job_problem(job, job_path)
        if why:
            raise RuntimeError("job refused: %s" % why)
        mode = job["containment"]
        if mode in ("os-root", "os-user"):
            try:
                if mode == "os-root":
                    os.unshare(os.CLONE_NEWNET)
                    lo_up()
                    import pwd
                    u = pwd.getpwnam(job["run_as"])
                    os.setgroups([])
                    os.setgid(u.pw_gid)
                    os.setuid(u.pw_uid)
                else:
                    uid, gid = os.getuid(), os.getgid()
                    os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNET)
                    with open("/proc/self/setgroups", "w") as fh:
                        fh.write("deny")
                    with open("/proc/self/uid_map", "w") as fh:
                        fh.write("%d %d 1" % (uid, uid))
                    with open("/proc/self/gid_map", "w") as fh:
                        fh.write("%d %d 1" % (gid, gid))
                    lo_up()
            except (OSError, KeyError) as exc:
                result = {"namespace_error": "%s: %s" % (type(exc).__name__, exc)}
                raise
        elif hasattr(os, "geteuid") and os.geteuid() == 0 and job.get("run_as"):
            import pwd
            u = pwd.getpwnam(job["run_as"])
            os.setgroups([])
            os.setgid(u.pw_gid)
            os.setuid(u.pw_uid)
        os.environ["HOME"] = job["home"]
        for k in list(os.environ):
            if k.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
                del os.environ[k]
        result = render(job)
        result["containment"] = MODES[mode]
    except Exception as exc:  # noqa: BLE001
        result.setdefault("error", "%s: %s" % (type(exc).__name__, exc))
        result["trace"] = traceback.format_exc()
    data = json.dumps(result)
    room = min(MAX_RESULT_BYTES, artefact_room(result))       # one artefact budget with the captures (R2-L02)
    if len(data) > room:      # bounded before it is written (AST-M18), its A10 evidence kept (R2-M10)
        data = json.dumps(bounded_result(result, "the renderer's result of %d bytes is over the %d bytes left of the artefact budget" % (len(data), room)))
        if len(data) > room:      # even the bounded evidence does not fit: only the note and the counts
            data = json.dumps({k: v for k, v in json.loads(data).items() if k in ("over_budget", "containment", "origin", "counts")})
    if not result_path_ok(job, job_path):     # nothing is written anywhere else (C4); the parent sees no result
        print("check_page renderer: %s" % result.get("error", "the job's result path is not the staging folder's"))
        return 2
    try:
        dl.write_output(job["result"], data.encode("utf-8"))      # never through an existing name (R2-M03)
    except dl.InputError as exc:
        print("check_page renderer: %s" % exc)
        return 2
    return 0


# ================================================================== the run in the parent

def run_child(job, mode, base, run_as, deadline):
    """Run the renderer child within the one deadline shared by every attempt (AST-M18)."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return {"timeout": True}
    job = dict(job, containment=mode)
    path = os.path.join(base, "job-%s.json" % mode)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(job, fh)
    if run_as and hasattr(os, "geteuid") and os.geteuid() == 0:
        import pwd
        u = pwd.getpwnam(run_as)
        for d in (job["out"], job["home"]):
            os.chown(d, u.pw_uid, u.pw_gid)
        os.chmod(path, 0o644)
    if os.path.exists(job["result"]):
        os.remove(job["result"])
    proc = subprocess.Popen([sys.executable, "-I", "-B", os.path.realpath(__file__), "--_render", path],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=remaining)
    except subprocess.TimeoutExpired:
        killed = False
        if hasattr(os, "killpg"):          # POSIX only; Windows kills the process itself (AST-M03)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                killed = True
            except OSError:
                pass
        if not killed:
            proc.kill()
        proc.communicate()
        return {"timeout": True}
    if not os.path.exists(job["result"]):
        return {"error": "the renderer wrote no result", "output": (out or b"").decode("utf-8", "replace")[-2000:]}
    out_bytes = sum(os.path.getsize(os.path.join(job["out"], f)) for f in os.listdir(job["out"]) if os.path.isfile(os.path.join(job["out"], f)))
    if os.path.getsize(job["result"]) > MAX_RESULT_BYTES or out_bytes > MAX_ARTEFACTS:      # the one budget (R2-L02)
        return {"over_budget": "the renderer's result and captures (%d bytes) are over the %d-byte artefact budget" % (out_bytes, MAX_ARTEFACTS)}
    with open(job["result"], encoding="utf-8") as fh:
        return json.load(fh)


def open_tree(path):
    for dirpath, dirs, files in os.walk(path):
        os.chmod(dirpath, 0o755)
        for f in files:
            os.chmod(os.path.join(dirpath, f), 0o644)


# ================================================================== analysis helpers

def painted(value):
    """A background colour that paints something or cannot be read (so it is reported, never dropped; R2-H05)."""
    if not value:
        return False
    c = col(value)
    return c is None or c.a > 0


def col(text):
    """A computed colour, color(srgb ...) and color(srgb-linear ...) converted (R2-H05); None when unreadable."""
    return dl.parse_computed_colour(text) if text else None


# Colour tokens inside a computed shadow value: every colour function and hex form, not only rgb() (R2-H05)
COLOUR_TOKEN = re.compile(r"(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix|light-dark)\((?:[^()]|\([^()]*\))*\)|#[0-9a-fA-F]{3,8}\b", re.I)
PAINT_URL = re.compile(r"""^url\(\s*(["']?)(.*?)\1\s*\)\s*(.*)$""", re.I | re.S)


def paint_server(value, frame_url, servers):
    """(fallback, resolved) of an SVG paint that is a url(...) reference (R2-H05): the fallback colour written after it
    ('' when none) and whether the reference names a linear or radial gradient of the same document (whose stops are
    judged where they are declared). None when the paint is not a url()."""
    m = PAINT_URL.match((value or "").strip())
    if not m:
        return None
    ref, fallback = m.group(2), m.group(3).strip()
    doc, _, frag = ref.partition("#")
    same_doc = not doc or doc == (frame_url or "").split("#", 1)[0]
    return fallback, bool(frag) and same_doc and frag in (servers or [])


def gradient_samples(stops):
    """Colours along a gradient of legacy sRGB stops: each segment between adjacent stops sampled at GRADIENT_STEPS + 1
    points in sRGB with premultiplied alpha, as Chromium interpolates such gradients; the stops alone miss darker or
    lighter colours between them (AST-H05)."""
    if len(stops) == 1:
        return list(stops)
    out = []
    for a, b in zip(stops, stops[1:]):
        fa, fb = float(a.a), float(b.a)
        for k in range(GRADIENT_STEPS + 1):
            t = k / GRADIENT_STEPS
            alpha = fa + (fb - fa) * t
            if alpha <= 0:
                out.append(dl.Colour(0, 0, 0, 0))
                continue
            ch = [(x * fa * (1 - t) + y * fb * t) / alpha for x, y in ((a.r, b.r), (a.g, b.g), (a.b, b.b))]
            out.append(dl.Colour(ch[0], ch[1], ch[2], Decimal(repr(round(alpha, 6)))))
    return unique_colours(out)


def unique_colours(colours):
    seen, out = set(), []
    for c in colours:
        k = (round(float(c.r), 6), round(float(c.g), 6), round(float(c.b), 6), round(float(c.a), 6))
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def unique(rgbs):
    seen, out = set(), []
    for x in rgbs:
        k = tuple(round(v, 6) for v in x)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def px(text):
    m = re.match(r"^(-?[\d.]+)px$", str(text or "").strip())
    return float(m.group(1)) if m else None


# ---- X2: paints hit testing never sees (a box-shadow, an outline, a border image), judged from the boxes UNSEEN
# measured where each run was evidenced (viewport coordinates of that scroll position, so sticky and fixed boxes are
# where the reader sees them). Chromium blurs a shadow with a Gaussian of standard deviation blur / 2 and Skia draws it
# to three standard deviations: a blurred edge reaches BLUR_EXTENT * blur beyond the shadow's shape; AA_MARGIN adds a
# pixel of antialiasing to every reach. Every reach is an upper bound: a run it touches is INCOMPLETE, never PASS.
BLUR_EXTENT = 1.5
AA_MARGIN = 1.0
# U2: solid inset shadow bands of the run's element and its ancestors are composed over every combination of their
# groups (2 ** groups fallback computations); more groups than this are not composed (INCOMPLETE, never a silent cut)
MAX_BAND_GROUPS = 4
# U1: a blur(r) filter is a Gaussian of standard deviation r, drawn to three deviations: its output reaches
# BLUR_SIGMAS * r beyond what it filters; a drop-shadow's blur b reaches as a box-shadow's (BLUR_EXTENT * b)
BLUR_SIGMAS = 3.0
FILTER_FN = re.compile(r"([a-z-]+)\(((?:[^()]|\([^()]*\))*)\)", re.I)
COLOUR_FILTERS = {"brightness", "contrast", "grayscale", "hue-rotate", "invert", "opacity", "saturate", "sepia"}
# Elements whose own drawing may pass their border box (replaced content, object-position, SVG strokes): a filter on
# them keeps the frame-wide rule (U1)
REPLACED = {"img", "video", "canvas", "iframe", "object", "embed", "svg", "input", "textarea", "select", "meter",
            "progress", "audio", "picture"}
SHADOW_LENGTH = re.compile(r"^-?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?px$", re.I)
RADII = ("border-top-left-radius", "border-top-right-radius", "border-bottom-right-radius", "border-bottom-left-radius")
# The properties whose value other than the identity moves or reshapes an element's paint in ways a box measured by
# getBoundingClientRect does not describe (the reach of its shadow is then not computed)
TRANSFORMS = (("transform", ("none",)), ("scale", ("none",)), ("rotate", ("none",)), ("translate", ("none",)),
              ("zoom", ("1", "normal")), ("offset-path", ("none",)))


def shadow_layers(value):
    """The layers of a computed box-shadow value as (inset, x, y, blur, spread, colour): the colour a dl.Colour, or None
    when it cannot be read (the layer then counts as painting); [] for none; None when a layer cannot be read at all (a
    missing colour, a length that is not px, a negative blur): its reach is then not computed."""
    v = (value or "").strip()
    if v.lower() in ("", "none"):
        return []
    out = []
    for layer in dl.split_top(v, ","):
        text = layer.strip()
        m = COLOUR_TOKEN.search(text)
        if not m:
            return None
        words = (text[:m.start()] + " " + text[m.end():]).split()
        nums = [w for w in words if w.lower() != "inset"]
        if not 2 <= len(nums) <= 4 or not all(SHADOW_LENGTH.match(w) for w in nums):
            return None
        x, y, blur, spread = ([float(w[:-2]) for w in nums] + [0.0, 0.0])[:4]
        if blur < 0:
            return None
        out.append((len(nums) < len(words), x, y, blur, spread, col(m.group(0))))
    return out


def layer_paints(layer):
    """False for a box-shadow layer that paints nothing: a transparent colour, or no offset, blur or positive spread (an
    outer shadow then lies wholly inside the box that clips it, an inset one wholly inside its own hole)."""
    _inset, x, y, blur, spread, colour = layer
    if colour is not None and colour.a == 0:
        return False
    return not (x == 0 and y == 0 and blur == 0 and spread <= 0)


def rect_hit(a, b):
    """Two [left, top, width, height] rectangles overlap in an area (edges that only touch do not)."""
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def filter_ops(value):
    """U1: the functions of a computed filter value, in order: ('blur', r), ('drop', dx, dy, b), or ('colour',) for a
    function that paints only where its input paints; [] for none; None when a function cannot be read (an url()
    reference to an SVG filter, an unknown function, a length that is not px, a negative blur): what it paints is then
    not computed."""
    v = (value or "").strip()
    if v.lower() in ("", "none"):
        return []
    out, pos = [], 0
    for m in FILTER_FN.finditer(v):
        if v[pos:m.start()].strip():
            return None
        pos = m.end()
        name, args = m.group(1).lower(), m.group(2).strip()
        if name in COLOUR_FILTERS:
            out.append(("colour",))
        elif name == "blur":
            r = 0.0 if not args else px(args)
            if r is None or r < 0:
                return None
            out.append(("blur", r))
        elif name == "drop-shadow":
            cm = COLOUR_TOKEN.search(args)
            nums = ((args[:cm.start()] + " " + args[cm.end():]) if cm else args).split()
            if not 2 <= len(nums) <= 3 or not all(SHADOW_LENGTH.match(w) for w in nums):
                return None
            dx, dy, b = ([float(w[:-2]) for w in nums] + [0.0])[:3]
            if b < 0:
                return None
            out.append(("drop", dx, dy, b))
        else:
            return None
    return out if not v[pos:].strip() else None


def filter_reach(box, ops):
    """U1: the rectangle a filter's output may cover, from the border box of the element it filters (an element whose
    border box bounds what it paints, Analysis.filter_unbounded): each blur(r) grows it by BLUR_SIGMAS * r; each
    drop-shadow(dx dy b) adds the rectangle moved by (dx, dy) and grown by BLUR_EXTENT * b; a colour function paints
    inside it; the functions apply in order; AA_MARGIN is added once at the end."""
    rect = list(box)
    for op in ops:
        if op[0] == "blur":
            rect = grown(rect, BLUR_SIGMAS * op[1])
        elif op[0] == "drop":
            moved = grown([rect[0] + op[1], rect[1] + op[2], rect[2], rect[3]], BLUR_EXTENT * op[3])
            left, top = min(rect[0], moved[0]), min(rect[1], moved[1])
            right, bottom = max(rect[0] + rect[2], moved[0] + moved[2]), max(rect[1] + rect[3], moved[1] + moved[3])
            rect = [left, top, right - left, bottom - top]
    return grown(rect, AA_MARGIN)


def grown(box, d):
    """A [left, top, width, height] rectangle grown by d on every side (shrunk when d is negative)."""
    return [box[0] - d, box[1] - d, box[2] + 2 * d, box[3] + 2 * d]


def scale_radii(w, h, rs):
    """Corner radii [(horizontal, vertical)] * 4 (top-left, top-right, bottom-right, bottom-left) scaled down together,
    as CSS does, when two radii of one side add up to more than the side."""
    (tlh, tlv), (trh, trv), (brh, brv), (blh, blv) = rs
    f = min([1.0] + [side / s for side, s in ((w, tlh + trh), (w, blh + brh), (h, tlv + blv), (h, trv + brv)) if s > 0])
    return [(max(0.0, a * f), max(0.0, b * f)) for a, b in rs]


def used_radii(box, values):
    """The used corner radii of a border box from the four computed values ('12px', '12px 6px', '50%'); None when one
    cannot be read."""
    rs = []
    for value in values:
        parts = str(value if value not in (None, "") else "0px").split()
        if not 1 <= len(parts) <= 2:
            return None
        pair = []
        for p, size in zip(parts * (3 - len(parts)), (box[2], box[3])):
            if p.endswith("%"):
                try:
                    pair.append(float(p[:-1]) / 100 * size)
                except ValueError:
                    return None
            else:
                n = 0.0 if p == "0" else px(p)
                if n is None:
                    return None
                pair.append(n)
        rs.append(tuple(pair))
    return scale_radii(box[2], box[3], rs)


def inside_rounded(rect, box, radii):
    """rect lies wholly inside the rounded rectangle box (corner radii radii): its four corners do, since the shape is
    convex. A point in a corner's square beyond the centre of its arc must lie inside the arc's ellipse."""
    l, t, w, h = box
    (tlh, tlv), (trh, trv), (brh, brv), (blh, blv) = radii
    corners = (((tlh, tlv), l + tlh, t + tlv, -1, -1), ((trh, trv), l + w - trh, t + trv, 1, -1),
               ((brh, brv), l + w - brh, t + h - brv, 1, 1), ((blh, blv), l + blh, t + h - blv, -1, 1))

    def inside(x, y):
        if x < l or x > l + w or y < t or y > t + h:
            return False
        for (rx, ry), cx, cy, sx, sy in corners:
            if rx > 0 and ry > 0 and (x - cx) * sx > 0 and (y - cy) * sy > 0 and ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 > 1:
                return False
        return True
    x0, y0, x1, y1 = rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]
    return all(inside(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


def shadow_reaches(rects, box, inner, radii, layer, ancestor, inline):
    """X2: whether one box-shadow layer of an element may paint under (or over) any of a run's text rectangles. box is
    the element's border box and inner its padding box, measured where the run was evidenced; radii its used radii (None
    when unreadable); ancestor whether the element is the run's element or one of its ancestors; inline whether it is
    laid out in line fragments. An inset shadow paints inside the padding box: it counts for an ancestor and for any
    element whose padding box meets the run. An outer shadow is the border box moved by the offset and grown by the
    spread, blurred BLUR_EXTENT * blur further, and never paints inside the element's own (rounded) border box."""
    inset, x, y, blur, spread, _colour = layer
    if not layer_paints(layer):
        return False
    if inset:
        return ancestor or any(rect_hit(q, inner) for q in rects)
    core = [box[0] + x - spread, box[1] + y - spread, box[2] + 2 * spread, box[3] + 2 * spread]
    if core[2] <= 0 or core[3] <= 0:
        return False                                  # a negative spread larger than the box leaves nothing to blur
    reach = grown(core, BLUR_EXTENT * blur + AA_MARGIN)
    hits = [q for q in rects if rect_hit(q, reach)]
    if not hits:
        return False
    if inline or radii is None:
        return True                                   # line fragments or unreadable radii: no part of the box is excluded
    return not all(inside_rounded(q, box, radii) for q in hits)    # its own box: an outer shadow never paints there


def outline_reaches(rects, box, width, offset, radii, inline):
    """X2: whether an element's outline may be drawn over any of a run's text rectangles: a ring outline-width wide
    outside the border box grown by outline-offset (a negative offset draws it inside the box). Its hole keeps the box's
    corner radii grown by a positive offset; with unreadable radii, line fragments or no hole, nothing is excluded."""
    outer = grown(box, offset + width + AA_MARGIN)
    if outer[2] <= 0 or outer[3] <= 0 or not any(rect_hit(q, outer) for q in rects):
        return False
    hole = grown(box, offset - AA_MARGIN)
    if inline or radii is None or hole[2] <= 0 or hole[3] <= 0:
        return True
    g = max(0.0, offset)
    hole_radii = scale_radii(hole[2], hole[3], [(a + g, b + g) if a > 0 and b > 0 else (0.0, 0.0) for a, b in radii])
    return not all(inside_rounded(q, hole, hole_radii) for q in rects if rect_hit(q, outer))


def border_image_reaches(rects, box, outset, borders):
    """X2: whether an element's border image may paint under any of a run's text rectangles: it is drawn in the border
    image area, the border box grown by border-image-outset (a number is that many border widths of its side), and
    with 'fill' or a border-image-width larger than the border over the padding box too, so the whole area counts.
    None when the outset cannot be read."""
    parts = str(outset if outset not in (None, "") else "0").split()
    if not 1 <= len(parts) <= 4:
        return None
    parts = {1: parts * 4, 2: parts * 2, 3: parts + parts[1:2], 4: parts}[len(parts)]     # top, right, bottom, left
    sides = []
    for p, border in zip(parts, borders):
        n = px(p)
        if n is None:
            try:
                n = float(p) * border
            except ValueError:
                return None
        sides.append(max(0.0, n))
    top, right, bottom, left = sides
    area = grown([box[0] - left, box[1] - top, box[2] + left + right, box[3] + top + bottom], AA_MARGIN)
    return any(rect_hit(q, area) for q in rects)


def svg_opacity(value):
    """An SVG fill-opacity or stroke-opacity as a Decimal clamped to [0, 1] (a number or a percentage; '1' when unset);
    None when unreadable."""
    v = str("1" if value in (None, "") else value).strip()
    try:
        d = Decimal(v[:-1]) / 100 if v.endswith("%") else Decimal(v)
    except ArithmeticError:
        return None
    return max(Decimal(0), min(Decimal(1), d))


def svg_glyph_problem(s):
    """None, or why the fallback does not compute an SVG text's glyph paint (R2-H03(1)): a paint server url(...),
    context-fill or context-stroke as its fill, or a visible stroke of non-zero width over the glyphs."""
    fill = (s.get("fill") or "").strip().lower()
    if fill.startswith("url(") or fill.startswith(("context-fill", "context-stroke")):
        return "fill %s" % fill[:60]
    stroke = (s.get("stroke") or "none").strip().lower()
    if stroke not in ("none", "") and (px(s.get("stroke-width")) or 0) > 0 and (svg_opacity(s.get("stroke-opacity")) or 0) > 0:
        return "a visible stroke %s of width %s" % (stroke[:40], s.get("stroke-width"))
    return None


# The proved lower bound over a gradient (R2-H03(2), scripts/docs/check_page.md): with stops interpolated in sRGB the
# encoded channels are affine in the position, each decoded (linear) channel is a convex increasing function of its
# encoded channel, so the relative luminance is convex in the position: its maximum on an interval is at an end, its
# minimum is found by ternary search. TERNARY_STEPS narrows the search interval to (2/3)^100 (below double precision);
# LUMA_MARGIN (1e-9) is subtracted from the minimum found, far above the search and rounding error (under 1e-15).
TERNARY_STEPS = 100
LUMA_MARGIN = 1e-9


def seg_luminance(c0, c1):
    """(lowest found, highest) relative luminance along the sRGB interpolation of two opaque colours (0-255 floats);
    the lowest found is the luminance at a real point of the interval."""
    def f(u):
        return dl.luminance(tuple(a + (b - a) * u for a, b in zip(c0, c1)))
    lo, hi = 0.0, 1.0
    for _ in range(TERNARY_STEPS):
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        if f(m1) <= f(m2):
            hi = m2
        else:
            lo = m1
    return min(f((lo + hi) / 2), f(0.0), f(1.0)), max(f(0.0), f(1.0))


def seg_min_ratio(t, c0, c1):
    """(bound, real) for opaque text t over every colour of an interval: a proved lower bound of the contrast and the
    contrast at a real point of the interval (so real < threshold proves a FAIL)."""
    found, top = seg_luminance(c0, c1)
    lt = dl.luminance((float(t.r), float(t.g), float(t.b)))
    if lt > top:                                    # lighter text: the lowest ratio is at the lighter end, exactly
        r = (lt + 0.05) / (top + 0.05)
        return r, r
    if found <= lt:                                 # a point of the interval has the text's luminance (continuity)
        return 1.0, 1.0
    low = found - LUMA_MARGIN
    return ((low + 0.05) / (lt + 0.05) if lt < low else 1.0), (found + 0.05) / (lt + 0.05)


def backdrop_pieces(layers):
    """The colours beneath the text, when they can be proved (R2-H03(2)): ('pt', rgb) for one colour and ('seg', rgb0,
    rgb1) for the sRGB interpolation between two opaque stops. Bottom-up from the lowest opaque layer: an opaque layer
    replaces what is beneath, a translucent solid layer composites over each piece (an affine map keeps a segment a
    segment). None when a gradient with a translucent stop lies above it (premultiplied interpolation is not affine)."""
    pieces = None
    for layer in layers:
        opaque = all(c.a == 1 for c in layer)
        if pieces is None and not opaque:
            continue                                # beneath every opaque layer: covered
        if opaque:
            rgb = [(float(c.r), float(c.g), float(c.b)) for c in layer]
            pieces = [("pt", rgb[0])] if len(rgb) == 1 else [("seg", a, b) if a != b else ("pt", a) for a, b in zip(rgb, rgb[1:])]
            continue
        if len(layer) > 1:
            return None
        c = layer[0]
        pieces = [("pt", dl.composite(c, p[1])) if p[0] == "pt" else ("seg", dl.composite(c, p[1]), dl.composite(c, p[2])) for p in pieces]
    return pieces


def contrast_verdict(t, pieces, need, what):
    """('PASS'|'FAIL'|'INCOMPLETE', detail) of text t over proved backdrop pieces: PASS only when the proved lower bound
    over every piece reaches the threshold; FAIL when a real point lies below it; otherwise INCOMPLETE (R2-H03(2))."""
    bound = real = None
    for p in pieces:
        if p[0] == "pt":
            pb = pr = dl.ratio(dl.composite(t, p[1]), p[1])
        else:
            pb, pr = seg_min_ratio(t, p[1], p[2])
        bound = pb if bound is None else min(bound, pb)
        real = pr if real is None else min(real, pr)
    if bound >= need:
        return "PASS", "fallback: lowest ratio %.4f (a proved lower bound) over %d backdrops, threshold %.1f (%s)" % (bound, len(pieces), need, what)
    if real < need:
        return "FAIL", "fallback: ratio %.4f at a point of the backdrop, threshold %.1f (%s)" % (real, need, what)
    return "INCOMPLETE", ("fallback: the proved lower bound %.6f is below the threshold %.1f, but no point below it was found (%s)"
                          % (bound, need, what))


class Render:
    def __init__(self, rd):
        self.name, self.width, self.scheme, self.rd = rd["name"], rd["width"], rd["scheme"], rd
        self.els, self.frames = {}, rd["frames"]
        for fr in rd["frames"]:
            for e in fr["data"]["elements"]:
                e["frame"] = fr["key"]
                self.els[e["id"]] = e
        self.kids = {}
        for e in self.els.values():
            self.kids.setdefault(e["parent"], []).append(e)

    def frame_of(self, e):
        return next((fr for fr in self.frames if fr["key"] == e.get("frame")), None)

    def flow_kids(self, e):
        return [c for c in self.kids.get(e["id"], ()) if c["visible"] and c["style"].get("position") not in ("absolute", "fixed")]

    def inline_text(self, e, depth=0):
        """True when e holds text through inline-level children (a paragraph wrapped in <strong> or <a>)."""
        for c in self.flow_kids(e):
            if c["style"].get("display", "").startswith("inline") and (c["text"] or (depth < 8 and self.inline_text(c, depth + 1))):
                return True
        return False

    def lays_out(self, e):
        """No text of its own and a block-level child in flow, or no text at all: e only lays out other elements."""
        if e["text"]:
            return False
        return any(not c["style"].get("display", "").startswith("inline") for c in self.flow_kids(e)) or not self.inline_text(e)

    def ancestors(self, e):
        out, cur = [], e
        while cur is not None:
            out.append(cur)
            cur = self.els.get(cur["parent"]) if cur["parent"] else None
        return out

    def runs(self):
        return [e for e in self.els.values() if e["visible"] and e["text"] and e["text_rects"] and not e["in_noscript"]]


class Analysis:
    def __init__(self, profile, rep, page_rel, page_sha, result):
        self.p, self.rep, self.page_rel, self.page_sha = profile, rep, page_rel, page_sha
        self.pal = pl.Palette(profile)
        self.pol = profile.policy
        self.renders = [Render(rd) for rd in result["renders"]]
        self.result = result
        self.seen = set()
        self.files = {}           # the staged bytes by bundle-relative path (closure()); set by run()
        self.font_srcs = []       # @font-face sources found in the closure: (kind, value, referrer)
        self.bundle = ""

    # ---- shared
    def judge(self, a, path, ok, detail, render=None, selector=None, **kw):
        key = (a, path, ok, detail, render.name if render is not None else None)   # the render is kept (AST-L01)
        if key in self.seen:
            return None
        self.seen.add(key)
        if render is not None:
            kw["render"] = render.name
        return pl.judged(self.p, self.rep, a, path, ok, detail, page_rel=self.page_rel, page_sha=self.page_sha,
                         selector=selector or path, **kw)

    def add(self, status, a, path, detail, render=None, **kw):
        key = (status, a, path, detail, render.name if render is not None else None)
        if key in self.seen:
            return None
        self.seen.add(key)
        if render is not None:
            kw["render"] = render.name
        return self.rep.add(status, a, path, detail, **kw)

    @staticmethod
    def glyph_paint(e):
        """The paint that draws the glyphs: SVG text's fill; elsewhere -webkit-text-fill-color, which computes to the
        color when unset (AST-H05, AUD-F01(2, 3))."""
        s = e["style"]
        if e["svg"]:
            return s.get("fill") or "", "fill"
        fill = s.get("-webkit-text-fill-color")
        return (fill, "-webkit-text-fill-color") if fill else (s["color"], "color")

    @staticmethod
    def scroll_changes(fr):
        """Ids of the elements whose paints differed from the first read at a scroll position used (R2-H02(3)); every
        element of the frame (or the frame itself) when the renderer recorded 'all' (the element list changed)."""
        pc = fr.get("paint_changes")
        if pc == "all":
            return {e["id"] for e in fr["data"]["elements"]} | {fr["key"] + ":*"}
        return {"%s:%d" % (fr["key"], i) for i in (pc or [])}

    def paint_changed(self, r):
        """Ids of the elements whose computed paints differ between the first read (before any evidence) and a read at a
        scroll position used or the read after every other evidence (AST-H03, R2-H02); a frame whose element lists differ
        in length counts as all changed. A6 uses the frames these ids belong to: any changed element, not only the text's
        ancestors, changes what the reader sees (HQ's V4)."""
        out = set()
        for fr in r.frames:
            out |= self.scroll_changes(fr)
            b, a = fr.get("paints_before"), fr.get("paints_after")
            if b is None or a is None:
                continue
            if len(b) != len(a):
                out |= {e["id"] for e in fr["data"]["elements"]}
                continue
            out |= {"%s:%d" % (fr["key"], i) for i, (x, y) in enumerate(zip(b, a)) if x != y}
        return out

    @staticmethod
    def preference_problems(r):
        """{frame key: (changed, unchecked)} for the frames whose evidence may not describe what a reader with another
        preference sees (W1): changed lists the states whose fresh load painted the frame differently; unchecked says why
        a state gave no evidence (the record missing, a state not loaded, a state not in effect in its load). Every
        frame of the render gets an unchecked reason that is not tied to one frame."""
        keys = [fr["key"] for fr in r.frames]
        rec = r.rd.get("preferences")
        if not isinstance(rec, dict):
            return {k: ([], ["the fresh loads were not recorded"]) for k in keys}
        changed, unchecked = {k: [] for k in keys}, []
        if not (rec.get("evidence") or {}).get("confirmed"):
            unchecked.append("the evidence page's own preferences were not in effect")
        states = [s for s in rec.get("states") or [] if isinstance(s, dict)]
        loaded = {s.get("label") for s in states}
        unchecked += ["%s: not loaded" % preference_label(s) for s in preference_states() if preference_label(s) not in loaded]
        for s in states:
            if not s.get("confirmed"):
                unchecked.append("%s: not in effect in its fresh load" % s.get("label"))
                continue
            for k in s.get("changed") or []:
                changed.setdefault(k, []).append(s.get("label"))
        return {k: (moved, unchecked) for k, moved in changed.items() if moved or unchecked}

    @staticmethod
    def painted_group(r, s):
        """True when s takes part in painting (X2): neither it nor an ancestor has display none, it has a box (display
        contents has none) and an effective opacity above 0. Its descendants may paint though its own box is hidden."""
        if s["style"].get("display") == "contents" or (s.get("opacity") if s.get("opacity") is not None else 1) <= 0:
            return False
        return all(x["style"].get("display") != "none" for x in r.ancestors(s))

    @staticmethod
    def transformed(r, s):
        """The first element of s's ancestor chain (s included) whose transform, individual transform, zoom or motion
        path moves or reshapes its paint beyond the box getBoundingClientRect gives, or None (X2)."""
        for x in r.ancestors(s):
            for prop, identity in TRANSFORMS:
                if str(x["style"].get(prop) or identity[0]).strip().lower() not in identity:
                    return x
        return None

    @staticmethod
    def unseen_kinds(st):
        """What of a style paints where hit testing never sees: (box-shadow layers that paint, an outline, a border
        image), or None when the box-shadow cannot be read (X2)."""
        layers = shadow_layers(st.get("box-shadow"))
        if layers is None:
            return None
        outline = (st.get("outline-style") or "none") not in ("none", "") and (px(st.get("outline-width")) or 0) > 0
        image = (st.get("border-image-source") or "none") not in ("none", "")
        return [layer for layer in layers if layer_paints(layer)], outline, image

    def filter_unbounded(self, r, s):
        """U1: None when the border box of s bounds everything a filter on s takes as input, so that its reach can be
        computed from that box (filter_reach); otherwise why not: a transformed, zoomed or motion-path element or
        ancestor, SVG or replaced content, child elements or text of its own (they may lie or paint beyond the box), a
        rendered ::before or ::after (no box is measured for it), or its own box-shadow, outline or border image."""
        moved = self.transformed(r, s)
        if moved is not None:
            return "a transformed element (%s)" % moved["path"]
        if s.get("svg") or s.get("tag") in REPLACED:
            return "its content is %s, whose drawing may pass its box" % ("SVG" if s.get("svg") else "a replaced element")
        if r.kids.get(s["id"]) or s.get("text") or s.get("text_rects"):
            return "it holds child elements or text, which may lie or paint beyond its box"
        if s.get("pseudo"):
            return "it has a rendered %s, whose box is not measured" % ", ".join(sorted(s["pseudo"]))
        if s["style"].get("display") == "list-item":
            return "it is a list item, whose ::marker may be drawn beyond its box"
        kinds = self.unseen_kinds(s["style"])
        if kinds is None or any(kinds):
            return "its own box-shadow, outline or border image paints beyond its box"
        return None

    def unseen_painters(self, r):
        """X2, U1: {frame key: (reason, painters)}. reason (or None) names a paint of the frame whose reach is not
        computed, so no text run of the frame can pass: a filter that cannot be read, a blur() or drop-shadow() filter
        on an element whose border box does not bound what it filters (filter_unbounded), a -webkit-box-reflect, a
        box-shadow that cannot be read, a box-shadow, outline or border image of a ::before or ::after (no box is
        measured for it) or of a transformed element. painters are (element, kinds, filter ops): the elements whose
        box-shadow, outline or border image, or whose blur() or drop-shadow() filter, is judged per run from the boxes
        measured where the run was evidenced."""
        out = {}
        for fr in r.frames:
            reason, painters = None, []
            for s in (fr.get("data") or {}).get("elements") or []:
                if not self.painted_group(r, s):
                    continue
                st, where = s["style"], s["path"]
                flt = str(st.get("filter") or "none")
                ops = filter_ops(flt)
                spread = []                           # the filter's functions when it paints beyond its input (U1)
                if ops is None:
                    reason = "the filter %s of %s could not be read: what it paints is not computed" % (flt[:60], where)
                elif any(op[0] != "colour" for op in ops):
                    why = self.filter_unbounded(r, s)
                    if why:
                        reason = ("a filter paints beyond the box of %s (%s) and %s: what it paints under the text is not computed"
                                  % (where, flt[:60], why))
                    else:
                        spread = ops
                if not reason and str(st.get("-webkit-box-reflect") or "none").lower() != "none":
                    reason = "a reflection (-webkit-box-reflect) of %s is not composed" % where
                for ps, pst in sorted((s.get("pseudo") or {}).items()):
                    if reason or pst.get("visibility") in ("hidden", "collapse"):
                        continue
                    kinds = self.unseen_kinds(pst)
                    pflt = str(pst.get("filter") or "none").lower()
                    if (kinds is None or any(kinds) or "blur(" in pflt or "drop-shadow(" in pflt
                            or str(pst.get("-webkit-box-reflect") or "none").lower() != "none"):
                        reason = "a shadow, outline, border image, filter or reflection of %s%s: its reach is not measured" % (where, ps)
                if reason:
                    break
                if st.get("visibility") in ("hidden", "collapse"):
                    continue                          # its own box, with its shadow and outline, is not painted
                kinds = self.unseen_kinds(st)
                if kinds is None:
                    reason = "a box-shadow of %s could not be read (%s): its reach is not computed" % (where, str(st.get("box-shadow"))[:80])
                    break
                if not any(kinds) and not spread:
                    continue
                moved = self.transformed(r, s) if any(kinds) else None
                if moved is not None:
                    reason = ("the reach of a shadow, outline or border image of %s is not computed (a transformed element: %s)"
                              % (where, moved["path"]))
                    break
                painters.append((s, kinds, spread))
            out[fr["key"]] = (reason, painters)
        return out

    @staticmethod
    def unseen_paint(r, e, unseen):
        """X2, U2: (reason, bands). reason is None, or why a paint hit testing never sees may lie under (or over) the
        run e, so that the contrast evidence does not describe what the reader sees: the frame's reason
        (unseen_painters), or a painter whose box-shadow, outline or border image reaches the run's rectangles as
        measured where the run was evidenced; a painter with no box measured there is never taken as not reaching.
        bands are the (painter, layer index, layer) of every solid inset box-shadow layer (no blur, a readable colour)
        of the run's element or an ancestor that reaches the run: an inset shadow paints above its element's
        backgrounds and beneath its content, so the fallback composes it exactly (band_verdict). Every other reaching
        layer (an outer shadow, a blurred one, a non-ancestor's) gives the reason."""
        reason, painters = unseen.get(e["frame"], (None, []))
        if reason:
            return reason, []
        if not painters:
            return None, []
        fr = r.frame_of(e) or {}
        geo = next((g for g in fr.get("geometry") or [] if isinstance(g, dict) and e["id"] in (g.get("runs") or {})), None)
        chain = {x["id"] for x in r.ancestors(e)}
        bands = []
        for s, (layers, outline, image), spread in painters:
            st, where = s["style"], s["path"]
            box = ((geo or {}).get("boxes") or {}).get(s["id"])
            if geo is None or not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
                return "a shadow, outline, border image or filter of %s was not measured where the text was checked" % where, []
            rects = [q for q in geo["runs"][e["id"]] or [] if isinstance(q, list) and len(q) == 4]
            animated = s["id"] in (geo.get("animated") or [])
            if spread:      # U1: a blur() or drop-shadow() filter reaches only the runs that meet what it can paint
                if animated:
                    return ("the filter of %s (%s) is animated: what it paints after the check is not computed"
                            % (where, str(st.get("filter"))[:60])), []
                reach = filter_reach(box, spread)
                if any(rect_hit(q, reach) for q in rects):
                    return ("a filter of %s (%s) paints within reach of the text: what it paints there is not computed"
                            % (where, str(st.get("filter"))[:60])), []
            borders = [px(st.get("border-%s-width" % side)) or 0.0 for side in SIDES]       # top, right, bottom, left
            inner = [box[0] + borders[3], box[1] + borders[0], box[2] - borders[1] - borders[3], box[3] - borders[0] - borders[2]]
            radii = used_radii(box, [st.get(k) for k in RADII])
            inline = st.get("display") == "inline"
            own = s["id"] in chain
            under = Analysis.below_painter(r, e, s) if own else None
            for k, layer in enumerate(layers):
                if shadow_reaches(rects, box, inner, radii, layer, own, inline):
                    if own and layer[0] and layer[3] == 0 and layer[5] is not None:      # a solid inset band (U2)
                        if animated:
                            return "a shadow paints under the text: %s (animated: the band after the check is not composed)" % where, []
                        if under is not None:
                            return ("a shadow paints under the text: %s; the text lies in %s, a stacking layer with a negative "
                                    "z-index painted beneath that shadow: not composed" % (where, under["path"])), []
                        bands.append((s, k, layer))
                        continue
                    return "a shadow paints under the text: %s" % where, []
            if outline and outline_reaches(rects, box, px(st.get("outline-width")) or 0.0, px(st.get("outline-offset")) or 0.0, radii, inline):
                return "an outline is drawn over the text: %s" % where, []
            if image:
                hit = border_image_reaches(rects, box, st.get("border-image-outset"), borders)
                if hit is None:
                    return ("the border-image-outset %r of %s could not be read: the border image's reach is not computed"
                            % (st.get("border-image-outset"), where)), []
                if hit:
                    return "a border image paints under the text: %s" % where, []
        return None, bands

    @staticmethod
    def below_painter(r, e, s):
        """U2: the first element from the run's element up to the painter s (not included) whose z-index is negative,
        or None. Such a stacking layer, with the text inside it, may be painted beneath s's background and inset shadow
        (CSS 2.1 Appendix E: negative layers before in-flow backgrounds when s forms no stacking context), so where s's
        band lies in the backdrop is not known."""
        for x in r.ancestors(e):
            if x["id"] == s["id"]:
                return None
            if str(x["style"].get("z-index") or "auto").strip().startswith("-"):
                return x
        return None

    def band_verdict(self, r, e, bands):
        """U2: ('PASS'|'FAIL'|'INCOMPLETE', detail) of the run e over its solid shadow bands (unseen_paint). Layers of
        one element with the same offset and spread paint the same area, so they form one group, composed together; a
        point of the run lies under some set of the groups, so the fallback is computed over the plain backdrop and over
        every combination of the groups, each band composed with its alpha above its element's backgrounds and in paint
        order (the first listed layer on top). PASS only when every combination passes; FAIL when one has a real point
        below the threshold; otherwise INCOMPLETE. More than MAX_BAND_GROUPS groups are not composed (INCOMPLETE)."""
        groups = {}
        for s, k, layer in bands:
            groups.setdefault((s["id"],) + tuple(layer[1:5]), []).append((s, k, layer))
        keys = list(groups)
        names = ", ".join(sorted({s["path"] for s, _k, _l in bands}))
        if len(keys) > MAX_BAND_GROUPS:
            return "INCOMPLETE", ("more than %d solid shadow bands of different shapes reach the text (%s): not composed"
                                  % (MAX_BAND_GROUPS, names))
        results = []
        for mask in range(1 << len(keys)):
            extra = {}
            for i, key in enumerate(keys):
                if mask >> i & 1:
                    for s, k, layer in groups[key]:
                        extra.setdefault(s["id"], []).append((k, layer[5]))
            # bottom-up within an element: the last listed layer is painted first
            extra = {sid: [c for _k, c in sorted(cs, key=lambda kc: -kc[0])] for sid, cs in extra.items()}
            results.append((mask,) + self.fallback(r, e, extra))
        for want in ("FAIL", "INCOMPLETE"):
            hit = next((x for x in results if x[1] == want), None)
            if hit:
                how = "with the solid shadow band(s) of %s composed" % names if hit[0] else "without the solid shadow band(s) of %s" % names
                return want, "%s, %s (U2)" % (hit[2], how)
        return "PASS", "%s, and with every combination of the solid shadow band(s) of %s composed (U2)" % (results[0][2], names)

    @staticmethod
    def chain_filter(r, e):
        """None, or the first filter or backdrop-filter on the run's element or an ancestor: axe-core composes neither, so
        its pass does not describe what the reader sees (the CEO's decision of 2026-11-12, found during TASK-CC-07)."""
        for x in r.ancestors(e):
            for prop in ("filter", "backdrop-filter"):
                v = str(x["style"].get(prop) or "none")
                if v.strip().lower() not in ("none", ""):
                    return "%s %s on %s" % (prop, v[:60], x["path"])
        return None

    def roles_scheme(self, render):
        mode = self.p.mode()
        return "dark" if mode == "dark-only" else ("light" if mode == "light-only" else render.scheme)

    def mapped(self, tokens, render):
        """Policy tokens are written for the light set; with scheme both, a dark render uses each token's pair."""
        pairs = (self.pol.get("scheme") or {}).get("pairs") or {}
        if self.p.mode() == "both" and render.scheme == "dark":
            return [pairs.get(t, t) for t in tokens]
        return list(tokens)

    def colours(self, tokens, render):
        return [(t, c) for t, c in self.pal.token_colours(self.mapped(tokens, render))]

    def off(self, section):
        return pl.section_off(self.pol, section)

    def context(self, render, e):
        """(role, heading element, reading element) by precedence code > heading > label > reading."""
        if e["code"]:
            return "code", None, None
        chain = render.ancestors(e)
        heading = next((x for x in chain if x["heading"]), None)
        if heading:
            return "heading", heading, None
        if self.is_label(e):
            return "label", None, None
        reading = next((x for x in chain if x["tag"] in READING_TAGS or len(x["text"].split()) >= 20), None)
        return ("reading" if reading else "other"), None, reading

    def is_label(self, e):
        lab = self.pol.get("labels") or {}
        if self.off("labels"):
            return False
        if e["label"]:
            return True
        style = lab.get("style") or {}
        size, weight = px(e["style"]["font-size"]), int(float(e["style"]["font-weight"] or 400))
        return bool(style) and size is not None and size <= float(style.get("max_size_px", 0)) and weight >= int(style.get("min_weight", 1000))

    # ---- A1 fonts
    def a1(self):
        faces = self.pal.faces
        ps = {f.get("postscript"): f for f in faces}
        cover = [tuple(r) for f in faces for r in (f.get("coverage") or [])]
        approved_sha = {f.get("sha256") for f in faces}
        # every @font-face source must be a bundle file: data:, blob:, local() and remote sources cannot be bound to
        # approved bytes (AST-H06)
        for kind, value, frm in self.font_srcs:
            if kind == "local":
                self.add("FAIL", "A1", frm, "@font-face source local(%s) is not a bundle file: its bytes cannot be approved" % value[:60], floor=True)
            elif classify_ref(value, posixpath.dirname(frm), self.bundle)[0] != "local":
                self.add("FAIL", "A1", frm, "@font-face source %s is not a bundle file: its bytes cannot be approved" % value[:60], floor=True)
        served_approved = set()
        for entry in self.result.get("access_log", []):
            if entry["status"] != 200:
                continue
            # the staged key the server served and the digest of the bytes it sent, never a second lookup of the
            # requested path (R2-H04)
            key, sha = entry.get("key"), entry.get("sha256")
            data = self.files.get(key) if isinstance(key, str) else None
            if data is None or not isinstance(sha, str) or dl.sha256(data) != sha:
                self.add("INCOMPLETE", "A1", str(entry.get("path"))[:120], "a served response is not tied to staged bytes "
                         "(no staged key, or its digest differs): the fonts it may carry are not judged", floor=True)
                continue
            if not data.startswith(FONT_MAGIC):      # a font by its first bytes, whatever its name
                continue
            ok = sha in approved_sha
            if ok:
                served_approved.add(sha)
            self.add("PASS" if ok else "FAIL", "A1", key, "font file %s (SHA-256 %s)" % ("approved" if ok else "is not an approved face file", sha[:16]), floor=True)
        for r in self.renders:
            fonts, n = r.rd.get("fonts") or {}, 0
            for e in r.runs():
                f = fonts.get(e["id"])
                path = e["path"]
                if not isinstance(f, list):
                    self.add("INCOMPLETE", "A1", path, "no platform-font data for this text run", r)
                    continue
                if not f:              # an empty list is no evidence of the font that drew the glyphs (AST-H06)
                    self.add("INCOMPLETE", "A1", path, "empty platform-font data for this text run", r)
                    continue
                n += 1
                fam = e["style"]["font-family"]
                if e["code"] and self.pal.code_roles == "system-monospace":
                    custom = [x for x in f if x.get("isCustomFont")]
                    if custom or not pl.is_system_monospace(fam):
                        self.add("FAIL", "A1", path, "code role must use the system monospace stack, not a downloaded font (%s; %s)" % (fam, [x.get("postScriptName") for x in custom]), r, floor=True)
                    continue
                custom = [x for x in f if x.get("isCustomFont")]
                system = [x for x in f if not x.get("isCustomFont")]
                for x in custom:
                    face = ps.get(x.get("postScriptName"))
                    if face is None:
                        self.add("FAIL", "A1", path, "custom font %s is not an approved face" % x.get("postScriptName"), r, floor=True)
                        continue
                    if face.get("sha256") not in served_approved:   # the name alone is no proof of the bytes (AST-H06)
                        self.add("FAIL", "A1", path, "custom font %s has an approved face's name, but that face's approved file was not served"
                                 % x.get("postScriptName"), r, floor=True)
                        continue
                    wt = int(float(e["style"]["font-weight"] or 400))
                    lo, hi = (face.get("weight") or [wt, wt])[:2]
                    if not lo <= wt <= hi:
                        self.add("FAIL", "A1", path, "weight %d outside the approved range %s-%s of %s" % (wt, lo, hi, face.get("family")), r, floor=True)
                    if e["style"]["font-style"] != (face.get("style") or "normal"):
                        self.add("FAIL", "A1", path, "style %s is not the approved %s" % (e["style"]["font-style"], face.get("style")), r, floor=True)
                if system:
                    chars = [c for c in e["text"] if not c.isspace()]
                    outside = [c for c in chars if not any(lo <= ord(c) <= hi for lo, hi in cover)]
                    names = sorted({x.get("familyName") for x in system})
                    drawn = sum(int(x.get("glyphCount") or 0) for x in system)
                    if outside and drawn > len(outside):
                        self.add("FAIL", "A1", path, "a non-approved font %s drew %d glyphs, more than the %d characters outside the approved coverage" % (names, drawn, len(outside)), r, floor=True)
                    elif outside:
                        self.add("INCOMPLETE", "A1", path, "glyphs outside the approved coverage (%s) drawn by %s" % ("".join(sorted(set(outside)))[:20], names), r)
                    else:
                        self.add("FAIL", "A1", path, "text drawn by a non-approved font %s (font-family %s)" % (names, fam), r, floor=True)
            self.add("PASS", "A1", "page", "%d text runs read for fonts" % n, r)

    # ---- A2 palette by role
    def paints(self, e, render=None):
        """Every non-empty paint of an element as (role, kinds, value, what); an unreadable colour is kept as its text, so
        A2 reports it (floor INCOMPLETE) instead of dropping it (R2-H05)."""
        s, out = e["style"], []
        tag = e["tag"]
        if e["text"] and not e["svg"]:
            out.append(("color", ["text"], s["color"], "color"))
            out += self.text_paints(s, "")
        if painted(s["background-color"]):
            out.append(("background-color", ["background"] + ([] if e["text"] else ["decoration-background"]), s["background-color"], "background-color"))
        for stop in pl.gradient_stops(s["background-image"] or ""):
            out.append(("background-color", ["gradient-stop"], stop, "gradient stop"))
        if pl.GRADIENT.search(s["background-image"] or "") and not pl.gradient_stops(s["background-image"]):
            out.append(("background-color", ["gradient-stop"], s["background-image"], "gradient without a readable stop"))
        if e["svg"] and tag == "stop":      # an SVG paint server's stop: judged as a gradient stop (AST-H07)
            sc, so = col(s.get("stop-color")), s.get("stop-opacity") or "1"
            try:
                op = Decimal(so.strip())
            except (ArithmeticError, ValueError):
                op = None
            if sc is None or op is None:
                out.append(("background-color", ["gradient-stop"], "%s / %s" % (s.get("stop-color"), so), "stop-color"))
            else:
                out.append(("background-color", ["gradient-stop"], dl.Colour(sc.r, sc.g, sc.b, sc.a * max(Decimal(0), min(Decimal(1), op))), "stop-color"))
        for side in SIDES:
            if (px(s["border-%s-width" % side]) or 0) > 0 and s["border-%s-style" % side] not in ("none", "hidden"):
                out.append(("border-color", ["border"], s["border-%s-color" % side], "border-%s" % side))
        if s["outline-style"] not in ("none", "") and (px(s["outline-width"]) or 0) > 0:
            out.append(("outline-color", ["outline", "border"], s["outline-color"], "outline"))
        if s["box-shadow"] and s["box-shadow"] != "none":
            for c in COLOUR_TOKEN.findall(s["box-shadow"]):
                out.append(("box-shadow", ["box-shadow"], c, "box-shadow"))
        if e["svg"] and tag in GEOMETRY:
            frame = (render.frame_of(e) if render is not None else None) or {}
            servers = (frame.get("data") or {}).get("paint_servers") or []
            for prop, role, kinds, drawn in (("fill", "fill", ["fill"] + (["svg-text"] if tag in ("text", "tspan") else []), True),
                                             ("stroke", "stroke", ["stroke"], (px(s["stroke-width"]) or 0) > 0)):
                v = s[prop]
                if v in ("none", "") or not drawn:
                    continue
                ref = paint_server(v, frame.get("url"), servers)
                if ref is None:
                    out.append((role, kinds, v, prop))
                    continue
                fallback, resolved = ref
                if fallback and fallback.lower() != "none":      # a missing or invalid server paints it (R2-H05)
                    out.append((role, kinds, fallback, prop + " fallback of " + v.split(")", 1)[0] + ")"))
                if not resolved:
                    out.append((role, kinds, None, "%s %s names no gradient of this document: its paint is not checked" % (prop, v[:80])))
        for ps, pst in (e.get("pseudo") or {}).items():
            if painted(pst["background-color"]):
                out.append(("background-color", ["background", "decoration-background"], pst["background-color"], ps + " background"))
            for stop in pl.gradient_stops(pst["background-image"] or ""):
                out.append(("background-color", ["gradient-stop"], stop, ps + " gradient stop"))
            for side in SIDES:
                if (px(pst["border-%s-width" % side]) or 0) > 0 and pst["border-%s-style" % side] not in ("none", "hidden"):
                    out.append(("border-color", ["border"], pst["border-%s-color" % side], ps + " border"))
            if pst["box-shadow"] and pst["box-shadow"] != "none":
                for c in COLOUR_TOKEN.findall(pst["box-shadow"]):
                    out.append(("box-shadow", ["box-shadow"], c, ps + " box-shadow"))
            if pst["content"] not in ('""', "''", "none", "normal"):
                out.append(("color", ["text"], pst["color"], ps + " text"))
        for ps, pst in (e.get("textpseudo") or {}).items():
            out.append(("color", ["text"], pst["color"], ps + " text"))
            if painted(pst["background-color"]):
                out.append(("background-color", ["background"], pst["background-color"], ps + " background"))
            out += self.text_paints(pst, ps + " ")
        return out

    @staticmethod
    def generated_text(pst):
        c = pst.get("content") or ""
        return c not in ("none", "normal") and bool(GENERATED_TEXT.search(re.sub(r"^\s*[\"']|[\"']\s*$", "", c)))

    @staticmethod
    def text_paints(s, prefix):
        """Text paints beside color: -webkit-text-fill-color and -stroke-color, decoration colour, text-shadow colours."""
        out = []
        fill = s.get("-webkit-text-fill-color")
        if fill and fill != s.get("color"):
            out.append(("color", ["text"], fill, prefix + "-webkit-text-fill-color"))
        if (px(s.get("-webkit-text-stroke-width")) or 0) > 0 and s.get("-webkit-text-stroke-color"):
            out.append(("color", ["text"], s["-webkit-text-stroke-color"], prefix + "-webkit-text-stroke-color"))
        if s.get("text-decoration-line") not in (None, "", "none") and s.get("text-decoration-color"):
            out.append(("color", ["text"], s["text-decoration-color"], prefix + "text-decoration-color"))
        if s.get("text-shadow") not in (None, "", "none"):
            for c in COLOUR_TOKEN.findall(s["text-shadow"]):
                out.append(("box-shadow", ["box-shadow"], c, prefix + "text-shadow"))
        return out

    def a2(self):
        for r in self.renders:
            scheme, n = self.roles_scheme(r), 0
            for e in r.els.values():
                if not e["visible"] and not (e["svg"] and e["tag"] == "stop"):   # stops draw nothing of their own box
                    continue
                for role, kinds, value, what in self.paints(e, r):
                    c = value if isinstance(value, dl.Colour) else col(value)
                    if value is None:             # a paint whose colour is not knowable here (R2-H05)
                        self.add("INCOMPLETE", "A2", e["path"], what, r, floor=True)
                        continue
                    if c is None:                 # never a silent skip: the floor is not proved (R2-H05)
                        self.add("INCOMPLETE", "A2", e["path"], "%s %r could not be read as a colour (a space the checker does not "
                                 "convert exactly): the floor is not checked" % (what, value), r, floor=True)
                        continue
                    if c.a == 0:
                        continue
                    n += 1
                    ok, why = self.pal.allowed_colour(c, scheme, role, kinds, near=True)
                    if not ok and why.startswith("reserved"):
                        self.add("FAIL", "A2", e["path"], "%s %r is the %s (floor)" % (what, c, why), r, floor=True)
                    elif not ok:
                        self.judge("A2", e["path"], False, "%s: %s" % (what, why), r)
            self.add("PASS", "A2", "page", "%d paints checked in the %s set" % (n, scheme), r)

    # ---- A3 headings
    def a3(self):
        if self.off("headings"):
            return self.add("NOT_CONFIGURED", "A3", "policy.headings", "off: %s" % self.pol["headings"]["off"])
        h = self.pol.get("headings") or {}
        acc = h.get("accent") or {}
        for r in self.renders:
            normal = self.colours(h.get("tokens") or [], r)
            accent = self.colours(acc.get("tokens") or [], r)
            heads = [e for e in r.els.values() if e["visible"] and e["heading"]
                     and not any(x["heading"] for x in r.ancestors(e)[1:])]
            for hd in heads:
                runs = [e for e in r.runs() if hd in r.ancestors(e)]
                total = sum(len(e["text"].replace(" ", "")) for e in runs) or 1
                acc_chars, acc_runs, bad = 0, 0, []
                for e in runs:
                    c = col(e["style"]["color"])
                    if c is None:
                        bad.append("unreadable colour %s" % e["style"]["color"])
                    elif any(t.near(c) for _, t in normal):
                        continue
                    elif any(t.near(c) for _, t in accent):
                        acc_chars += len(e["text"].replace(" ", ""))
                        acc_runs += 1
                    else:
                        bad.append("%r in %r" % (c, e["text"][:30]))
                if bad:
                    self.judge("A3", hd["path"], False, "heading text not in a heading token: %s" % "; ".join(bad), r)
                elif acc_runs and (acc_chars / total > float(acc.get("max_share", 0)) or acc_runs > int(acc.get("max_runs", 0))):
                    self.judge("A3", hd["path"], False, "accent beyond the allowance: %d of %d characters in %d runs (max share %s, max runs %s)"
                               % (acc_chars, total, acc_runs, acc.get("max_share"), acc.get("max_runs")), r)
                else:
                    self.judge("A3", hd["path"], True, "heading colours within policy (accent %d of %d)" % (acc_chars, total), r)

    # ---- A4 limited fills
    def a4(self):
        if self.off("fills"):
            return self.add("NOT_CONFIGURED", "A4", "policy.fills", "off: %s" % self.pol["fills"]["off"])
        for r in self.renders:
            for rule in self.pol.get("fills") or []:
                toks = self.colours(rule.get("tokens") or [], r)
                thr, area_max = Decimal(str(rule.get("alpha_above", 0))), float(rule.get("max_area_px2", 0))
                for e in r.els.values():
                    if not e["visible"]:
                        continue
                    # the layout area (border box, untransformed), not the bounding box of a rotated or scaled box (AST-M13)
                    lay = e.get("layout")
                    area = lay[0] * lay[1] if isinstance(lay, list) and len(lay) == 2 else e["rect"][2] * e["rect"][3]
                    boxes = [(e["style"], area, e["path"])]
                    for ps, pst in (e.get("pseudo") or {}).items():
                        w, hh = px(pst["width"]), px(pst["height"])
                        boxes.append((pst, (w * hh) if w is not None and hh is not None else None, e["path"] + ps))
                    for st, area, path in boxes:
                        c = col(st["background-color"])
                        if c is not None and c.a > thr and any((c.r, c.g, c.b) == (t.r, t.g, t.b) for _, t in toks):
                            if area is None:
                                self.add("INCOMPLETE", "A4", path, "a limited fill on a pseudo-element of indefinite size", r)
                            elif area > area_max:
                                self.judge("A4", path, False, "limited fill %r over %.0f px2 (max %.0f)" % (c, area, area_max), r)
                        for stop in pl.gradient_stops(st["background-image"] or ""):
                            sc = col(stop)
                            if sc is not None and sc.a > thr and any((sc.r, sc.g, sc.b) == (t.r, t.g, t.b) for _, t in toks) and (area is None or area > area_max):
                                self.add("INCOMPLETE", "A4", path, "a gradient with a limited stop %r on a box over the area limit" % sc, r)
            self.add("PASS", "A4", "page", "limited fills checked", r)

    # ---- A5 forbidden text colours
    def a5(self):
        if self.off("forbidden_text_colours"):
            return self.add("NOT_CONFIGURED", "A5", "policy.forbidden_text_colours", "off")
        for r in self.renders:
            forb = self.colours(self.pol.get("forbidden_text_colours") or [], r)
            gen = [x for x in r.els.values() if x["visible"] and not x["text"]
                   and any(self.generated_text(pst) for pst in (x.get("pseudo") or {}).values())]
            for e in r.runs() + gen:
                texts = [e["style"]["color"], e["style"].get("-webkit-text-fill-color")]
                if e["svg"]:                      # SVG text draws with fill (AUD-F01(3))
                    texts.append(e["style"].get("fill"))
                texts += [v for pst in (e.get("textpseudo") or {}).values() for v in (pst["color"], pst.get("-webkit-text-fill-color"))]
                texts += [pst["color"] for pst in (e.get("pseudo") or {}).values() if self.generated_text(pst)]
                for value in texts:
                    c = col(value)
                    if c is None:
                        continue
                    eff = dl.Colour(c.r, c.g, c.b, (c.a * Decimal(str(round(e["opacity"], 4)))).quantize(Decimal("0.0001")))
                    hit = next((t for t, f in forb if f.near(c) or f.near(eff)), None)
                    if hit:
                        self.judge("A5", e["path"], False, "text %r is the forbidden text token %s" % (e["text"][:30], hit), r)
                        break
            self.add("PASS", "A5", "page", "text colours checked against forbidden tokens", r)

    # ---- A6 contrast
    def fallback(self, r, e, bands=None):
        """('PASS'|'FAIL'|'INCOMPLETE', detail): the deterministic check against every gradient stop. bands (U2) maps an
        element of the chain to the colours of its solid inset shadow bands, bottom-up: each is a solid layer above
        that element's backgrounds and beneath its descendants', and counts as a painted background of that element."""
        bands = bands or {}
        chain = r.ancestors(e)
        for x in chain:
            s = x["style"]
            for prop in ("filter", "backdrop-filter"):
                if s[prop] not in ("none", ""):
                    return "INCOMPLETE", "%s on %s" % (prop, x["path"])
            if s["mix-blend-mode"] not in ("normal", ""):
                return "INCOMPLETE", "mix-blend-mode on %s" % x["path"]
            if s["mask-image"] not in ("none", "") or s["clip-path"] not in ("none", ""):
                return "INCOMPLETE", "mask or clip-path on %s" % x["path"]
            if "url(" in (s["background-image"] or ""):
                return "INCOMPLETE", "background image on %s" % x["path"]
            if re.search(r"conic-gradient|image-set|element\(", s["background-image"] or ""):
                return "INCOMPLETE", "unsupported background on %s" % x["path"]
            for ps, pst in (x.get("pseudo") or {}).items():
                pb = col(pst["background-color"])
                if (pb is not None and pb.a > 0) or (pst["background-image"] or "none") != "none":
                    return "INCOMPLETE", "a painted %s on %s" % (ps, x["path"])
        ov = (self.result_overlap.get(r.name) or {}).get(e["id"]) or []
        if any(v.startswith("overlap") for v in ov):
            return "INCOMPLETE", "overlapped by another element (%s)" % next(v for v in ov if v.startswith("overlap"))
        if any(v == "offscreen" for v in ov) or not ov:
            return "INCOMPLETE", "text not inside the checked viewport"
        # text alpha x effective opacity is right only when no background inside a faded group lies between the text and
        # the backdrop: a faded element at or above a painted background of the chain is group compositing (AST-H05)
        painted = None
        for x in chain:
            s = x["style"]
            bc0 = col(s["background-color"])
            if (bc0 is not None and bc0.a > 0) or pl.GRADIENT.search(s["background-image"] or "") or bands.get(x["id"]):
                painted = painted or x
            try:
                own_op = float(s.get("opacity") or 1)
            except ValueError:
                own_op = 1.0
            if own_op < 1 and painted is not None:
                return "INCOMPLETE", "opacity %s on %s over the painted background of %s (group compositing is not computed)" % (s.get("opacity"), x["path"], painted["path"])
        layers = []                            # bottom-up: each a list of stop colours (one colour for a solid background)
        for x in reversed(chain):
            bc = col(x["style"]["background-color"])
            if bc is None:
                return "INCOMPLETE", "unreadable background on %s" % x["path"]
            if bc.a > 0:
                layers.append([bc])
            img = x["style"]["background-image"] or ""
            grads = pl.parse_gradients(img)
            if pl.GRADIENT.search(img) and not any(g["stops"] for g in grads):
                return "INCOMPLETE", "unreadable gradient on %s" % x["path"]
            for g in reversed(grads):          # the first listed background image paints on top
                if g["interp"] not in (None, "srgb"):
                    return "INCOMPLETE", "a gradient interpolated in %s on %s is not computed" % (g["interp"], x["path"])
                stops = [col(s) for s in g["stops"]]
                if not stops or any(s is None for s in stops):
                    return "INCOMPLETE", "unreadable gradient on %s" % x["path"]
                layers.append(stops)
            for c in bands.get(x["id"], ()):      # U2: its solid inset shadow bands, above its own backgrounds
                layers.append([c])
        if not any(all(c.a == 1 for c in layer) for layer in layers):
            frame_main = e["frame"] == "f0"
            dark_canvas = r.scheme == "dark" and "dark" in (chain[-1]["style"].get("color-scheme") or "")
            if not frame_main or dark_canvas:
                return "INCOMPLETE", "no opaque background beneath the text"
            layers = [[dl.Colour(255, 255, 255)]] + layers        # the white canvas of the main frame
        paint, what = self.glyph_paint(e)
        if e["svg"]:                           # the glyph paint of SVG text (R2-H03(1))
            why = svg_glyph_problem(e["style"])
            if why:
                return "INCOMPLETE", "SVG text paint not computed: %s" % why
        t = col(paint)
        if t is None:
            return "INCOMPLETE", "unreadable text colour (%s %s)" % (what, paint)
        alpha = t.a * Decimal(str(round(e["opacity"], 4)))
        if e["svg"]:
            fill_opacity = svg_opacity(e["style"].get("fill-opacity"))
            if fill_opacity is None:
                return "INCOMPLETE", "unreadable fill-opacity %r on SVG text" % e["style"].get("fill-opacity")
            alpha *= fill_opacity              # fill-opacity composes with the element's opacity (R2-H03(1))
        t = dl.Colour(t.r, t.g, t.b, alpha.quantize(Decimal("0.0001")))
        size = px(e["style"]["font-size"]) or 16
        need = 3.0 if dl.is_large(Decimal(str(size)), int(float(e["style"]["font-weight"] or 400))) else 4.5   # unrounded size
        pieces = backdrop_pieces(layers)
        if pieces is not None and (t.a == 1 or all(p[0] == "pt" for p in pieces)):
            return contrast_verdict(t, pieces, need, what)
        # not proved (translucent gradient stops, translucent text over a gradient): samples may still show a FAIL
        cands = None
        for layer in layers:
            samples = gradient_samples(layer) if len(layer) > 1 else layer
            if cands is None:
                if all(c.a == 1 for c in samples):
                    cands = [(float(c.r), float(c.g), float(c.b)) for c in samples]
                continue
            if len(samples) * len(cands) > MAX_CANDIDATES:
                return "INCOMPLETE", "more than %d backdrops to compute (budget)" % MAX_CANDIDATES
            cands = unique([dl.composite(c, b) for c in samples for b in cands])
        worst = min(dl.ratio(dl.composite(t, b), b) for b in cands)
        if worst < need:
            return "FAIL", "fallback: a sampled ratio %.3f over %d sampled backdrops, threshold %.1f (%s)" % (worst, len(cands), need, what)
        return "INCOMPLETE", ("fallback: no lower bound proved over a translucent gradient (sampled lowest %.3f, threshold %.1f, %s)"
                              % (worst, need, what))

    @staticmethod
    def frame_backdrop_missing(r, e):
        """True for text in a child frame whose own document gives it no opaque backdrop: no element of its frame beneath
        it (its ancestors there, the frame's root included) paints an opaque background colour or a gradient of opaque
        readable stops; axe's verdict in that frame assumes a canvas the parent page may cover (R2-H02(4))."""
        if e["frame"] == "f0":
            return False
        for x in r.ancestors(e):
            bc = col(x["style"]["background-color"])
            if bc is not None and bc.a == 1:
                return False
            img = x["style"]["background-image"] or ""
            grads = pl.parse_gradients(img)
            if grads and "url(" not in img and all(g["stops"] and all(col(s) is not None and col(s).a == 1 for s in g["stops"]) for g in grads):
                return False
        return True

    def a6(self):
        self.result_overlap = {}
        for r in self.renders:
            ov, verdict, inapplicable_frames, silent_frames = {}, {}, [], []
            for fr in r.frames:
                ov.update(fr.get("overlap") or {})
                res = fr.get("axe_contrast") or {}
                if res.get("error"):
                    self.add("INCOMPLETE", "A6", fr["url"], "axe did not run: %s" % res["error"], r)
                    silent_frames.append(fr["key"])
                    continue
                named = [x["id"] for k in ("passes", "violations", "incomplete") for x in res.get(k) or []] + list(res.get("inapplicable") or [])
                if "color-contrast" not in named:      # execution evidence (plan B.8.3)
                    silent_frames.append(fr["key"])
                if "color-contrast" in (res.get("inapplicable") or []):
                    inapplicable_frames.append(fr["key"])
                for kind in ("passes", "violations", "incomplete"):
                    for rule in res.get(kind) or []:
                        if rule["id"] != "color-contrast":
                            continue
                        for node in rule["nodes"]:
                            if node["id"]:
                                verdict.setdefault(node["id"], (kind, node))
                                if kind == "violations":
                                    verdict[node["id"]] = (kind, node)
            self.result_overlap[r.name] = ov
            runs = r.runs()
            counts = collections.Counter()
            changed = self.paint_changed(r)
            changed_frames = {i.rsplit(":", 1)[0] for i in changed}     # ids are "<frame key>:<index>"
            prefs = self.preference_problems(r)
            unseen = self.unseen_painters(r)
            run_ids = {e["id"] for e in runs}
            # every axe color-contrast violation is a FAIL: one whose node is unresolved, or on an element outside the
            # text runs, is named by axe's own selector (AST-H04)
            for fr in r.frames:
                for rule in (fr.get("axe_contrast") or {}).get("violations") or []:
                    if rule.get("id") != "color-contrast":
                        continue
                    for node in rule.get("nodes") or []:
                        if node.get("id") in run_ids:
                            continue
                        el = r.els.get(node.get("id")) if node.get("id") else None
                        d = node.get("data") or {}
                        where = el["path"] if el else "axe target %s" % " ".join(str(t) for t in node.get("target") or [])
                        self.add("FAIL", "A6", where, "axe: %s on %s ratio %s (needs %s)" % (d.get("fgColor"), d.get("bgColor"), d.get("contrastRatio"),
                                                                                           d.get("expectedContrastRatio")), r, floor=True)
                        counts["fail"] += 1
            for e in runs:
                kind, node = verdict.get(e["id"], (None, None))
                if kind == "violations":     # a named violation stays FAIL, drift or not, tracked or untracked (R2-M10)
                    d = node.get("data") or {}
                    self.add("FAIL", "A6", e["path"], "axe: %s on %s ratio %s (needs %s) for %r" % (d.get("fgColor"), d.get("bgColor"), d.get("contrastRatio"), d.get("expectedContrastRatio"), e["text"][:30]), r, floor=True)
                    counts["fail"] += 1
                    continue
                if e["frame"] in changed_frames:      # any element of the frame, a sibling layer included (V4)
                    self.add("INCOMPLETE", "A6", e["path"], "the page's paint changed during checking (at a scroll position or after "
                             "the first read): the contrast evidence does not describe one state", r, floor=True)
                    counts["incomplete"] += 1
                    continue
                if e["frame"] in prefs:      # the evidence is one reader-preference state among others (W1)
                    moved, unchecked = prefs[e["frame"]]
                    self.add("INCOMPLETE", "A6", e["path"], ("the page paints differently for readers with another preference: %s" % "; ".join(moved))
                             if moved else ("the page was not checked for readers with another preference: %s" % "; ".join(unchecked)), r, floor=True)
                    counts["incomplete"] += 1
                    continue
                if e["frame"] in silent_frames:
                    self.add("INCOMPLETE", "A6", e["path"], "axe gave no color-contrast result for this frame (no execution evidence)", r, floor=True)
                    counts["incomplete"] += 1
                    continue
                if kind is None and e["frame"] in inapplicable_frames:
                    self.add("INCOMPLETE", "A6", e["path"], "axe color-contrast inapplicable while text runs exist", r, floor=True)
                    counts["incomplete"] += 1
                    continue
                if self.frame_backdrop_missing(r, e):     # whatever axe says for that frame (R2-H02(4))
                    self.add("INCOMPLETE", "A6", e["path"], "the backdrop lies outside the frame: its document paints no opaque "
                             "background beneath the text, so what shows through is not checked", r, floor=True)
                    counts["incomplete"] += 1
                    continue
                why, bands = self.unseen_paint(r, e, unseen)
                if why:      # a paint hit testing never sees reaches the text: neither axe nor the fallback composes it (X2)
                    self.add("INCOMPLETE", "A6", e["path"], why, r, floor=True)
                    counts["incomplete"] += 1
                    continue
                if e.get("textpseudo"):
                    self.add("INCOMPLETE", "A6", e["path"], "%s repaints the text in other colours: contrast not computed" % ", ".join(sorted(e["textpseudo"])), r, floor=True)
                    counts["incomplete"] += 1
                elif bands:      # solid shadow bands axe does not see: the fallback composes them (U2), whatever axe said
                    status, detail = self.band_verdict(r, e, bands)
                    counts["fb_" + status.lower()] += 1
                    if status != "PASS":
                        self.add(status, "A6", e["path"], detail, r, floor=True)
                elif kind == "passes" and (e["svg"] or self.glyph_paint(e)[0] != e["style"]["color"]):
                    # axe reads color; the glyphs are drawn with SVG fill or a differing -webkit-text-fill-color: the
                    # fallback decides with the real glyph paint (AUD-F01(2, 3))
                    status, detail = self.fallback(r, e)
                    counts["fb_" + status.lower()] += 1
                    if status != "PASS":
                        self.add(status, "A6", e["path"], detail + " (axe's pass read color, not the glyph paint)", r, floor=True)
                elif kind == "passes":
                    ovl = [v for v in ov.get(e["id"]) or [] if v.startswith("overlap")]
                    flt = self.chain_filter(r, e)
                    if not ov.get(e["id"]) or "offscreen" in ov.get(e["id"]):     # no overlap evidence where axe looked (R2-H02)
                        self.add("INCOMPLETE", "A6", e["path"], "text not inside the checked viewport", r, floor=True)
                        counts["incomplete"] += 1
                    elif ovl:
                        self.add("INCOMPLETE", "A6", e["path"], "axe passed, but another element overlaps the text (%s): contrast at that spot unknown" % ovl[0], r, floor=True)
                        counts["incomplete"] += 1
                    elif flt:      # axe-core composes no CSS filter (the CEO's decision of 2026-11-12)
                        self.add("INCOMPLETE", "A6", e["path"], "axe passed, but %s: axe does not compose filters, so its verdict does not "
                                 "describe what the reader sees" % flt, r, floor=True)
                        counts["incomplete"] += 1
                    else:
                        counts["pass"] += 1
                else:
                    status, detail = self.fallback(r, e)
                    counts["fb_" + status.lower()] += 1
                    if status != "PASS":
                        self.add(status, "A6", e["path"], detail + (" (axe: %s)" % (node or {}).get("message", "")[:80] if node else " (axe gave no verdict)"), r, floor=True)
            for e in r.els.values():
                for ps, pst in (e.get("pseudo") or {}).items():
                    if e["visible"] and self.generated_text(pst):
                        self.add("INCOMPLETE", "A6", e["path"] + ps, "generated text (%s content %s): contrast not computed" % (ps, pst["content"][:40]), r, floor=True)
                        counts["incomplete"] += 1
            # an execution summary, never a verdict (AST-L01)
            self.add("INFO", "A6", "page", "axe-core %s color-contrast in %d frames, %d text runs: axe passes %d, axe fails %d; fallback passes %d, fails %d, undecided %d"
                     % (AXE_VERSION, len(r.frames), len(runs), counts["pass"], counts["fail"], counts["fb_pass"], counts["fb_fail"],
                        counts["incomplete"] + counts["fb_incomplete"]), r)

    # ---- A7 reading measure
    def a7(self):
        if self.off("measure"):
            return self.add("NOT_CONFIGURED", "A7", "policy.measure", "off")
        m = self.pol.get("measure") or {}
        roles = {x["selector"]: float(x["px"]) for x in m.get("roles") or []}
        default = float(m.get("default_px", 0))
        for r in self.renders:
            for e in r.els.values():
                # a list item or cell that only lays out other elements is not measured; its text blocks are
                # (smoke test 2026-11-10: timeline items)
                if not e["visible"] or not (e["tag"] in READING_TAGS or len(e["text"].split()) >= 20) or r.lays_out(e):
                    continue
                role, _, _ = self.context(r, e)
                if role not in ("reading", "other"):
                    continue
                s = e["style"]
                # the layout content width (untransformed, unrounded; AST-M13); the box width only where none was read
                cw = e.get("content_width")
                if cw is None:
                    cw = e["rect"][2] - sum(px(s[k]) or 0 for k in ("padding-left", "padding-right", "border-left-width", "border-right-width"))
                limit = next((roles[sel] for sel in e["measure"] if sel in roles), default)
                if cw > limit:
                    self.judge("A7", e["path"], False, "content box %.2f px wider than the measure %.0f px" % (cw, limit), r)
            self.add("PASS", "A7", "page", "reading measures checked", r)

    # ---- A8 capitals
    def a8(self):
        cap = self.pol.get("capitals")
        if self.off("capitals") or cap == "off":
            return self.add("NOT_CONFIGURED", "A8", "policy.capitals", "off")
        for r in self.renders:             # every render: capitals set only in a dark scheme count too (AST-M14)
            for e in r.runs():
                role, hd, rdg = self.context(r, e)
                if role not in ("heading", "reading"):
                    continue
                if e["style"]["text-transform"] == "uppercase":
                    self.judge("A8", e["path"], False, "text-transform: uppercase outside labels", r)
                    continue
                run, longest = 0, 0
                for w in e["text"].split():
                    core = re.sub(r"[^\w]", "", w)
                    if len(core) >= 2 and core.isalpha() and core.isupper():
                        run += 1
                        longest = max(longest, run)
                    else:
                        run = 0
                if longest >= 3:
                    self.judge("A8", e["path"], False, "%d consecutive words in capitals: %r" % (longest, e["text"][:40]), r)
            self.add("PASS", "A8", "page", "capitals checked", r)

    # ---- A9 scheme
    def a9(self):
        mode = self.p.mode()
        by_w = collections.defaultdict(dict)
        for r in self.renders:
            by_w[r.width][r.scheme] = r
        for w, pair in by_w.items():
            lt, dk = pair.get("light"), pair.get("dark")
            if not lt or not dk:
                continue
            if mode == "both":
                def root_bg(r):
                    for e in r.els.values():
                        if e["frame"] == "f0" and e["tag"] in ("html", "body"):
                            c = col(e["style"]["background-color"])
                            if c is not None and c.a > 0:
                                return c
                    return None
                a, b = root_bg(lt), root_bg(dk)
                bg_l = [c for _, c in self.pal.token_colours(self.pal.tokens_for("light", "background-color"))]
                bg_d = [c for _, c in self.pal.token_colours(self.pal.tokens_for("dark", "background-color"))]
                ok = (a is not None and b is not None and a != b and any(t.near(a) for t in bg_l) and any(t.near(b) for t in bg_d))
                self.judge("A9", "page @%d" % w, ok, "root background light %r, dark %r (scheme both: they differ and each is a "
                           "background token of its scheme)" % (a, b), dk)
                continue
            # presence counts too: a scheme that hides or fades a section changes the page (AST-M14, AUD-F13)
            keys = ["color", "background-color", "background-image", "box-shadow", "fill", "stroke", "visibility", "display",
                    "opacity"] + ["border-%s-color" % s for s in SIDES]
            diffs = 0
            for eid, e1 in lt.els.items():
                e2 = dk.els.get(eid)
                if e2 is None or not (e1["visible"] or e2["visible"]):
                    continue
                changed = [k for k in keys if e1["style"][k] != e2["style"][k]]
                pairs = [(k, e1["style"][k], e2["style"][k]) for k in changed]
                if e1["visible"] != e2["visible"]:
                    pairs.append(("visible", e1["visible"], e2["visible"]))
                if abs(float(e1["opacity"]) - float(e2["opacity"])) > 1e-9:
                    pairs.append(("effective opacity", e1["opacity"], e2["opacity"]))
                if pairs:
                    diffs += 1
                    if diffs <= 50:
                        self.judge("A9", e1["path"], False, "%s page differs in its dark render at %d px: %s" % (mode, w, ", ".join("%s %s -> %s" % p for p in pairs[:3])), dk)
            if not diffs:
                self.judge("A9", "page @%d" % w, True, "%s: light and dark renders paint the same" % mode, dk)

    # ---- what this checker could not see
    def coverage(self):
        for r in self.renders:
            for u in r.rd.get("unchecked_frames") or []:
                self.add("INCOMPLETE", "PAGE", u, "a frame that is not checked (only same-bundle, srcdoc and about:blank frames are)", r)
            hosts = sorted({h for fr in r.frames for h in fr["data"].get("shadow_hosts") or []} | set(r.rd.get("shadow_roots") or []))
            for h in hosts:
                self.add("INCOMPLETE", "PAGE", h, "shadow DOM content is not checked", r)
            if r.rd.get("fonts_ready") != "ready":
                self.add("INCOMPLETE", "BUDGET", "fonts", "document.fonts.ready not reached within %d ms" % FONT_WAIT_MS, r)
        main = next((x for x in self.renders if x.name == "w1280-light"), None)
        media = collections.Counter()
        for fr in (main.frames if main else []):
            media.update(fr["data"].get("media") or {})
        for kind, n in sorted(media.items()):
            if n:
                self.add("NOT_CHECKED", "PAGE", kind, "%d %s element(s): their contents are not checked" % (n, kind))

    # ---- A10 self-contained (the closure's own findings are reported by closure_findings before rendering)
    def a10(self):
        origin = self.result["origin"] + "/"
        outside = sorted({u for u in self.result.get("requests", []) + self.result.get("aborted", []) + self.result.get("websockets", [])
                          if not u.startswith((origin, "data:", "blob:", "about:"))})
        for u in outside:
            self.add("FAIL", "A10", u[:120], "request outside the loopback origin attempted (%s)" % self.result["containment"], floor=True)
        for entry in self.result.get("access_log", []):
            if entry["status"] == 404 and entry["path"] != "/favicon.ico":
                self.add("FAIL", "A10", entry["path"], "requested local file not in the staged closure", floor=True)
        blob = json.dumps(self.result.get("renders", []))
        reached = self.canary in blob or any(self.canary in e["path"] for e in self.result.get("access_log", []))
        # what this item shows: a file outside the stage that nothing references was never requested; containment
        # itself is proved by the tests, which reach a listener first and then see no request (AST-M01)
        self.add("FAIL" if reached else "PASS", "A10", "containment", "canary %s outside the stage: %s" % (
            self.canary[:8], "REQUESTED" if reached else "never requested (server log, frames)"), floor=True)

    # ---- A11 primary buttons
    def a11(self):
        if self.off("buttons"):
            return self.add("NOT_CONFIGURED", "A11", "policy.buttons", "off")
        b = self.pol.get("buttons") or {}
        paint = b.get("paint") if isinstance(b.get("paint"), dict) else {}     # selectors-only: no paint path, said (R2-M06)
        limit = int(b.get("max_per_view", 1))
        for r in [x for x in self.renders if x.width == 1280]:    # both desktop renders, light and dark (AST-M14)
            # the paint signature in the render's scheme: with scheme both, the dark render uses each token's pair
            bg_tok = self.mapped([paint["background"]], r)[0] if paint.get("background") else None
            fg_tok = self.mapped([paint["text"]], r)[0] if paint.get("text") else None
            bg = self.p.colour(bg_tok) if bg_tok else None
            fg = self.p.colour(fg_tok) if fg_tok else None
            btns = []
            for e in r.els.values():
                if not e["visible"]:
                    continue
                native = e["tag"] in ("button", "a") or e["role"] == "button"
                sig = bg is not None and fg is not None and native and (col(e["style"]["background-color"]) or dl.Colour(0, 0, 0, 0)).near(bg) \
                    and (col(e["style"]["color"]) or dl.Colour(0, 0, 0, 0)).near(fg)
                if e["button_sel"] or sig:
                    btns.append(e)
            worst = 0
            for x in btns:
                top = x["rect"][1]
                worst = max(worst, sum(1 for y in btns if y["rect"][1] < top + 800 and y["rect"][1] + y["rect"][3] > top))
            self.judge("A11", "page", worst <= limit, "%d primary buttons in one 800 px window (max %d); %d on the page" % (worst, limit, len(btns)), r)

    # ---- A12 accessibility
    def a12(self):
        acc = self.pol.get("accessibility") or {}
        if self.off("accessibility"):
            return self.add("NOT_CONFIGURED", "A12", "policy.accessibility", "off")
        tiers = {k: "blocking" for k in pl.H3_BLOCKING}
        tiers.update(acc.get("tiers") or {})
        default = acc.get("default") or "advisory"     # every rule neither listed nor one of H3's six (R2-M08)
        tags = acc.get("tags") or pl.DEFAULT_AXE_TAGS
        for r in self.renders:
            for fr in r.frames:
                res = fr.get("axe_a11y")
                if res is None:                  # A12 is enabled: every checked frame carries its result (R2-M08)
                    self.add("INCOMPLETE", "A12", fr["url"], "no accessibility result for this frame", r)
                    continue
                if res.get("error"):
                    self.add("INCOMPLETE", "A12", fr["url"], "axe did not run: %s" % res["error"], r)
                    continue
                if not any(res.get(k) for k in ("passes", "violations", "incomplete", "inapplicable")):
                    # no rule in any result list: no evidence that any rule ran (AST-M15)
                    self.add("INCOMPLETE", "A12", fr["url"], "axe returned no rule results: no execution evidence", r)
                    continue
                self.a12_coverage(r, fr, res)
                for rule in res.get("violations") or []:
                    for node in rule["nodes"]:
                        st = "FAIL" if tiers.get(rule["id"], default) == "blocking" else "WARN"
                        self.add(st, "A12", "%s %s" % (rule["id"], node["target"]), "%s (%s)" % (node["message"][:120], rule.get("impact")), r, rule=rule["id"])
                for rule in res.get("incomplete") or []:
                    for node in rule["nodes"]:
                        self.add("WARN", "A12", "%s %s" % (rule["id"], node["target"]), "needs review: %s" % node["message"][:120], r, rule=rule["id"])
            if any(fr.get("axe_a11y") for fr in r.frames):      # an execution summary, never a verdict (AST-L01)
                self.add("INFO", "A12", "page", "axe-core %s tags %s (no WCAG conformance claimed)" % (AXE_VERSION, ", ".join(tags)), r)

    def a12_coverage(self, r, fr, res):
        """The evidence is complete only when every rule the vendored axe-core has for the selected tags (the renderer's
        list from axe.getRules, the excluded tags removed), less color-contrast and, in a child frame, the rules about the
        top document, appears in a result list; each missing rule is named (R2-M08)."""
        expected = fr.get("axe_rules")
        if not isinstance(expected, list) or not expected:
            return self.add("INCOMPLETE", "A12", fr["url"], "the rules axe-core has for the selected tags are not known for this frame", r)
        skip = {"color-contrast"} | (set() if fr.get("main") else set(INITIATOR_RULES))
        named = {x["id"] for k in ("passes", "violations", "incomplete") for x in res.get(k) or []} | set(res.get("inapplicable") or [])
        missing = sorted(set(expected) - skip - named)
        if missing:
            self.add("INCOMPLETE", "A12", fr["url"], "axe gave no result for %d expected rule(s): %s" % (len(missing), ", ".join(missing[:20])), r)
        return None

    # ---- A13 structure
    def structure(self):
        r = next((x for x in self.renders if x.name == "w1280-light"), None)
        out = []
        for fr in (r.frames if r else []):
            out += [s["entry"] for s in fr["data"]["structure"] if s["visible"]]
        return out

    def structure_gaps(self):
        """Why the w1280-light structure may be incomplete (frames not checked, shadow DOM, budgets); [] when complete."""
        r = next((x for x in self.renders if x.name == "w1280-light"), None)
        if r is None:
            return ["no w1280-light render"]
        gaps = ["frame not checked: %s" % u for u in r.rd.get("unchecked_frames") or []]
        gaps += ["shadow DOM: %s" % h for fr in r.frames for h in fr["data"].get("shadow_hosts") or []]
        gaps += ["shadow DOM: %s" % h for h in r.rd.get("shadow_roots") or []]
        gaps += [t for t in self.result.get("truncated") or [] if t.startswith(r.name)]
        return gaps

    SNAPSHOT_KEYS = ("coverage", "entries", "page", "page_sha256", "rule_version")

    def a13(self, kept_path, kept_sha256=None):
        try:
            with open(kept_path, "rb") as fh:
                raw = fh.read()
            snap = dl.load_json_strict(raw.decode("utf-8"), "the --kept snapshot")
            if not isinstance(snap, dict):
                raise ValueError("not a JSON object")
        except (OSError, ValueError, UnicodeDecodeError, dl.ContentError) as exc:
            raise dl.InputError("the --kept snapshot %s is unreadable: %s" % (kept_path, exc))
        # the snapshot's schema: full page hash, entries, a complete coverage state (AST-M16)
        problems = []
        # the baseline is the snapshot whose SHA-256 the caller gives (the --snapshot run prints it), as receipts are
        # bound by --receipt-sha256: a snapshot written by anyone else proves nothing (R2-M09)
        if kept_sha256 is None:
            problems.append("its SHA-256 was not given (--kept-sha256 HEX, the value the --snapshot run printed)")
        elif kept_sha256 != dl.sha256(raw):
            problems.append("its SHA-256 %s is not the --kept-sha256 given (%s)" % (dl.sha256(raw)[:16], kept_sha256[:16]))
        if sorted(snap) != sorted(self.SNAPSHOT_KEYS):
            problems.append("its keys %s are not exactly %s" % (sorted(snap), list(self.SNAPSHOT_KEYS)))
        else:
            if not isinstance(snap["page_sha256"], str) or not dl.SHA256_HEX.match(snap["page_sha256"]):
                problems.append("page_sha256 is not the old page's full SHA-256")
            if not isinstance(snap["entries"], list) or not snap["entries"] or not all(isinstance(x, str) and x for x in snap["entries"]):
                problems.append("entries is not a non-empty list of entries")
            cov = snap["coverage"]
            if not isinstance(cov, dict) or cov.get("state") != "complete":
                problems.append("the snapshot was taken from a run with incomplete coverage (%s)" % (
                    "; ".join(cov.get("gaps") or []) if isinstance(cov, dict) else cov))
        self.add("INFO", "A13", "evidence", "snapshot SHA-256 %s; old page SHA-256 %s; rule %s (snapshot rule %s)"
                 % (dl.sha256(raw), snap.get("page_sha256"), A13_RULE_VERSION, snap.get("rule_version")))
        if snap.get("rule_version") != A13_RULE_VERSION:
            problems.append("the snapshot was taken under another rule version")
        for p in problems:
            self.add("INCOMPLETE", "A13", "evidence", "the snapshot cannot prove preservation: %s" % p)
        if problems:
            self.add("NOT_CHECKED", "A13", "scripts", "behaviour registered by scripts is not checked (page scripts never run, H1)")
            return
        old, new = collections.Counter(snap.get("entries") or []), collections.Counter(self.structure())
        missing = old - new
        for gap in self.structure_gaps():
            self.add("INCOMPLETE", "A13", "coverage", "the new page's structure is not fully seen: %s" % gap)
        view = next((x for x in self.renders if x.name == "w1280-light"), None)    # the one render compared (R2-M09)
        for entry, k in sorted(missing.items()):
            self.judge("A13", entry[:160], False, "missing from the new page's visible elements in the desktop light render "
                       "(%d of %d)" % (k, old[entry]), render=view, selector=entry)
        if not missing:
            self.judge("A13", "page", True, "all %d snapshot entries kept in the desktop light render" % sum(old.values()), render=view)
        self.add("NOT_CHECKED", "A13", "scripts", "behaviour registered by scripts is not checked (page scripts never run, H1)")


# ================================================================== main

def run(args, rep):
    dl.require_yaml()
    profile = pl.Profile(args.site)
    if pl.is_link(args.bundle.rstrip("/\\") or args.bundle):
        raise dl.InputError("the bundle root %s is a link (R2-M01)" % args.bundle)
    bundle = os.path.realpath(args.bundle)
    if not os.path.isdir(bundle):
        raise dl.InputError("the bundle %s is not a folder" % args.bundle)
    page = os.path.normpath(os.path.join(bundle, args.page))
    if os.path.commonpath([page, bundle]) != bundle:
        raise dl.InputError("--page %s resolves outside the bundle" % args.page)
    site = profile.dir
    if os.path.commonpath([bundle, site]) in (bundle, site):
        raise dl.InputError("the bundle and the site design folder overlap")
    if not os.path.isfile(page):
        raise dl.InputError("the page %s is not readable" % args.page)
    for name, sha in AXE_PINS.items():
        p = os.path.join(os.path.dirname(os.path.realpath(__file__)), "vendor", "axe-core", name)
        if not os.path.isfile(p) or dl.sha256_file(p) != sha:
            raise dl.InputError("vendored axe-core %s is missing or changed (expected SHA-256 %s)" % (name, sha[:16]))
    if importlib.util.find_spec("playwright") is None:
        raise dl.InputError("Playwright is not installed for this Python (pip install playwright; playwright install chromium)")
    if not pl.verify_receipt(profile, rep, use_git=not args.no_git, receipt_sha256=args.receipt_sha256):
        return None
    page_rel = os.path.relpath(page, bundle).replace(os.sep, "/")
    deadline = time.monotonic() + RUN_SECONDS      # one budget for every attempt (AST-M18), counted from before staging (R2-L02)
    try:
        clo = closure(bundle, page_rel, bl.Guard(profile, pl.folder_files(profile.dir)))
    except StageError as exc:
        raise dl.InputError("bundle refused at staging: %s" % exc)
    closure_findings(rep, clo)       # known A10 failures first: no later budget stop or timeout can hide them (AST-M03)
    if clo.get("over"):
        rep.add("INCOMPLETE", "STAGE", "closure", "more than %d files or %d bytes in the page's closure" % (MAX_FILES, MAX_STAGE_BYTES))
        return None
    if page_rel not in clo["files"]:
        raise dl.InputError("the page %s is not readable" % args.page)
    if clo["objects"]:
        rep.add("INCOMPLETE", "STAGE", "object/embed", "%d object or embed elements are not checked" % clo["objects"])
    if clo.get("srcdoc_over"):
        rep.add("INCOMPLETE", "STAGE", "srcdoc", "srcdoc documents nested deeper than %d levels are not read" % MAX_SRCDOC_DEPTH)
    for s in clo["scripts"]:
        # the CEO's decision R1-12 (2026-11-10, option A): what page scripts would render is not checked, so the page
        # is not proven; scripts are never staged nor run (H1)
        rep.add("INCOMPLETE", "STAGE", s[:120], "page script present: never run, so what it would render is not checked (remove it: pages are static)")
    for rel in clo["font_unread"]:
        rep.add("INCOMPLETE", "A1", rel, "@font-face sources of this stylesheet could not be read (unbalanced braces)")
    page_sha = dl.sha256(clo["files"][page_rel])     # the staged bytes, as waivers and snapshots bind them (AST-H02)
    linux = sys.platform.startswith("linux") and hasattr(os, "unshare")
    force_browser = os.environ.get("SDS_FORCE_BROWSER_CONTAINMENT") == "1"   # tests only: exercise containment: browser on Linux
    if hasattr(os, "geteuid") and os.geteuid() == 0 and not args.run_as:
        rep.add("INCOMPLETE", "CONTAIN", "isolation", "isolation unavailable: running as root (Chromium's sandbox refuses root); give --run-as USER")
        return None
    base = tempfile.mkdtemp(prefix="sds-page-")
    try:
        stage, out, home = (os.path.join(base, x) for x in ("site", "out", "home"))
        for d in (stage, out, home):
            os.makedirs(d)
        try:
            stage_files(bundle, clo["files"], stage)
        except StageError as exc:
            raise dl.InputError("bundle refused at staging: %s" % exc)
        canary = secrets.token_hex(16)
        with open(os.path.join(base, "canary-%s.txt" % canary), "w") as fh:
            fh.write(canary)
        open_tree(stage)
        os.chmod(base, 0o755)
        pol = profile.policy
        sel = {"labels": (pol.get("labels") or {}).get("selectors") or [] if not pl.section_off(pol, "labels") else [],
               "headings": (pol.get("headings") or {}).get("selectors") or [] if not pl.section_off(pol, "headings") else [],
               "measure": (pol.get("measure") or {}).get("roles") or [] if not pl.section_off(pol, "measure") else [],
               "buttons": (pol.get("buttons") or {}).get("selectors") or [] if not pl.section_off(pol, "buttons") else []}
        tags = None if pl.section_off(pol, "accessibility") else ((pol.get("accessibility") or {}).get("tags") or pl.DEFAULT_AXE_TAGS)
        axe_copy = os.path.join(base, "axe.min.js")   # the renderer may run as another user who cannot read the plugin folder
        shutil.copyfile(os.path.join(os.path.dirname(os.path.realpath(__file__)), "vendor", "axe-core", "axe.min.js"), axe_copy)
        os.chmod(axe_copy, 0o644)
        job = {"stage": stage, "page": page_rel, "out": out, "home": home, "result": os.path.join(out, "result.json"),
               "axe": axe_copy,
               # the only files the renderer's server may send, each with the SHA-256 of the bytes staged (R2-M12)
               "inventory": {rel: dl.sha256(data) for rel, data in sorted(clo["files"].items())},
               "selectors": sel, "tags": tags, "run_as": args.run_as}
        mode = ("os-root" if os.geteuid() == 0 else "os-user") if (linux and not force_browser) else "browser"
        res = run_child(job, mode, base, args.run_as, deadline)
        if res.get("namespace_error") and mode == "os-user":
            rep.add("INFO", "CONTAIN", "namespace", "network namespace refused (%s); browser containment used" % res["namespace_error"])
            res = run_child(job, "browser", base, args.run_as, deadline)
        if res.get("timeout"):
            rep.add("INCOMPLETE", "CONTAIN", "budget", "the render exceeded %d s" % RUN_SECONDS)
            return None
        if res.get("over_budget"):
            report_bounded(rep, res)          # the A10 failures it kept stay FAIL (R2-M10)
            return None
        if res.get("error"):
            rep.add("INFO", "RENDER", "trace", (res.get("trace") or res.get("output") or "")[-1500:])
            raise dl.InputError("browser unusable: %s" % res["error"])
        rep.add("INFO", "CONTAIN", "containment", "containment: %s" % res["containment"], containment=res["containment"])
        if force_browser and linux:
            rep.add("WARN", "CONTAIN", "containment", "containment forced to browser by SDS_FORCE_BROWSER_CONTAINMENT (a test switch)")
        for t in res.get("truncated") or []:
            rep.add("INCOMPLETE", "BUDGET", "height", t)
        an = Analysis(profile, rep, page_rel, page_sha, res)
        an.stage, an.canary, an.files, an.font_srcs, an.bundle = stage, canary, clo["files"], clo["font_sources"], bundle
        main = next((r for r in an.renders if r.name == "w1280-light"), None)
        if main is None or not [e for e in main.runs() if e["frame"] == "f0"]:
            rep.add("INCOMPLETE", "PAGE", page_rel, "no text to check (content created only by scripts is never rendered, H1)")
        an.coverage()
        an.a1()
        an.a2()
        an.a3()
        an.a4()
        an.a5()
        an.a6()
        an.a7()
        an.a8()
        an.a9()
        an.a10()
        an.a11()
        an.a12()
        if args.snapshot:
            gaps = an.structure_gaps()
            snap = {"rule_version": A13_RULE_VERSION, "page": page_rel, "page_sha256": page_sha, "entries": sorted(an.structure()),
                    "coverage": {"state": "incomplete" if gaps else "complete", "gaps": gaps}}
            snap_bytes = json.dumps(snap, indent=1).encode("utf-8")     # the bytes written are the bytes hashed (R2-M09)
            dl.write_output(args.snapshot, snap_bytes)       # never through an existing link or hard link (R2-M03)
            rep.add("INFO", "A13", "snapshot", "structure written to %s (coverage %s); its SHA-256 is %s (give it as --kept-sha256 "
                    "with --kept)" % (args.snapshot, snap["coverage"]["state"], dl.sha256(snap_bytes)))
            if gaps or not snap["entries"]:
                rep.add("INCOMPLETE", "A13", "snapshot", "the snapshot cannot prove a later page's preservation: %s"
                        % ("; ".join(gaps) if gaps else "no structure entries"))
        if args.kept:
            an.a13(args.kept, args.kept_sha256)
        try:
            keep_screens(rep, res, args.out)
        except OSError as exc:
            raise dl.InputError("the screenshots could not be written to %s: %s" % (args.out, exc.strerror or exc))
        return res
    finally:
        shutil.rmtree(base, ignore_errors=True)


def closure_findings(rep, clo):
    """The closure's own A10 failures, reported as soon as the closure is known (AST-M03)."""
    for ref, frm in clo["outside"]:
        rep.add("FAIL", "A10", frm, "reference %s leaves the bundle (not staged)" % ref, floor=True)
    for ref, frm in clo["remote"]:
        rep.add("FAIL", "A10", frm, "non-local reference %s" % ref, floor=True)
    for rel, frm in clo["missing"]:
        rep.add("FAIL", "A10", frm or rel, "referenced local file %s is missing" % rel, floor=True)


def keep_screens(rep, res, out_dir):
    out = os.path.realpath(out_dir or tempfile.mkdtemp(prefix="check_page-"))
    os.makedirs(out, exist_ok=True)
    dark_findings = any(i.get("render", "").endswith("dark") and i["status"] in ("FAIL", "INCOMPLETE", "WARN") for i in rep.items)
    total, kept = 0, []
    for shot in (res.get("screenshots") or [])[:MAX_SHOTS]:
        name = os.path.basename(shot)
        if "-dark" in name and not dark_findings:          # w1280-dark.png, w1280-dark-at-00800.png (R2-H02(5))
            continue
        size = os.path.getsize(shot) if os.path.isfile(shot) else 0
        if size > MAX_SHOT_BYTES or total + size > MAX_ARTEFACTS:
            rep.add("INCOMPLETE", "BUDGET", name, "screenshot over the artefact budget; not kept")
            continue
        with open(shot, "rb") as fh:                      # the renderer's own capture in the staging folder
            dl.write_output(os.path.join(out, name), fh.read())    # never through an existing name (R2-M03)
        total += size
        kept.append(name)
    rep.add("INFO", "OUT", out, "screenshots kept: %s" % ", ".join(kept))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--_render"]:
        return child_main(argv[1])
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bundle")
    ap.add_argument("--page", required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--out")
    ap.add_argument("--run-as")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--snapshot")
    g.add_argument("--kept")
    ap.add_argument("--json")
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--receipt-sha256", help="the SHA-256 of the issued ready.json (needed where no Git repository is)")
    ap.add_argument("--kept-sha256", help="the SHA-256 of the --kept snapshot, as its --snapshot run printed it (R2-M09)")
    args = ap.parse_args(argv)
    for opt in ("receipt_sha256", "kept_sha256"):
        value = getattr(args, opt)
        if value is not None:
            setattr(args, opt, value.strip().lower())
            if not dl.SHA256_HEX.match(getattr(args, opt)):
                print("check_page: ERROR --%s must be 64 hex digits" % opt.replace("_", "-"))
                return dl.EXIT["ERROR"]
    for opt, value in (("--json", args.json), ("--snapshot", args.snapshot), ("--out", args.out)):
        where = pl.output_problem(value, args.site)       # outputs never go into the site design folder (AST-M04)
        if where:
            print("check_page: ERROR %s %s" % (opt, where))
            return dl.EXIT["ERROR"]
    rep = dl.Report("check_page")
    containment = None
    try:
        res = run(args, rep)
        containment = (res or {}).get("containment")
    except (dl.InputError, dl.ContentError) as exc:
        rep.error = "ERROR"
        rep.add("INFO", "INPUT", "input", str(exc))
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        print("check_page: INTERNAL (%s)" % exc)
        return dl.EXIT["INTERNAL"]
    if len(rep.items) > MAX_ITEMS:
        rank = {"FAIL": 0, "INCOMPLETE": 1, "WARN": 2}
        # one slot kept for the truncation item, so the report holds at most MAX_ITEMS items (AST-M18)
        rep.items = sorted(rep.items, key=lambda i: rank.get(i["status"], 3))[:MAX_ITEMS - 1]
        rep.add("INCOMPLETE", "BUDGET", "report", "more than %d report items; truncated" % MAX_ITEMS)
    if args.json:          # outputs first, the summary after: a report that cannot be written is ERROR 2 (AST-M03)
        data = json.loads(rep.json())
        data.update({"containment": containment, "page": args.page, "checker": "check_page.py " + VERSION})
        try:
            dl.write_output(args.json, json.dumps(data, indent=1, default=str).encode("utf-8"))    # R2-M03
        except dl.InputError as exc:
            rep.error = "ERROR"
            rep.add("INFO", "OUT", args.json, "the report could not be written: %s" % exc)
    print(rep.text())
    print("containment: %s" % (containment or "none (nothing rendered)"))
    return dl.EXIT[rep.outcome()]


if __name__ == "__main__":
    sys.exit(main())
