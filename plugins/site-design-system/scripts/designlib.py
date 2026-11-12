"""Shared library of the site-design-system plugin: strict YAML, schemas, typed values, colour and
contrast maths, references, and the report with its outcomes. Standard library plus PyYAML.

Outcomes (every checker): PASS 0, FAIL 1, ERROR 2, INCOMPLETE 3, INTERNAL 4."""
import hashlib
import json
import os
import re
import secrets
import stat
from decimal import Decimal, InvalidOperation, localcontext

try:
    import yaml
except ImportError:  # reported by the checkers as ERROR naming the dependency
    yaml = None

EXIT = {"PASS": 0, "FAIL": 1, "ERROR": 2, "INCOMPLETE": 3, "INTERNAL": 4}
MAX_BYTES = 1_000_000          # largest input file (plan 0.4 B.7.1)
MAX_DEPTH = 20                 # deepest YAML nesting (plan 0.4 B.7.1)
ALPHA_TOL = Decimal("0.005")   # browser-serialised alpha (two decimals); never for authored values
LARGE_PX = Decimal(24)         # WCAG large text: 18pt = 24 CSS px
LARGE_BOLD_PX = Decimal(56) / Decimal(3)   # 14pt = 18.666... CSS px, at weight 700 or more
TOKEN_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
GROUPS = ("colors", "typography", "rounded", "spacing", "components")


class InputError(Exception):
    """An input could not be used (missing, unreadable, a dependency missing): ERROR 2."""


class ContentError(Exception):
    """An input is invalid as content (bad YAML, duplicate key, schema): a FAIL of P2."""


# ---------------------------------------------------------------- files and YAML

def read_bytes(path):
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_BYTES + 1)
    except OSError as exc:
        raise InputError("cannot read %s: %s" % (path, exc.strerror or exc))
    if len(data) > MAX_BYTES:
        raise ContentError("%s is larger than %d bytes" % (path, MAX_BYTES))
    return data


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def output_name_problem(path):
    """None, or why an output must not be written at path (R2-M03): an existing name that is a link, a junction or
    another reparse point, a hard link (more than one link) or not a regular file."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return "%s cannot be examined: %s" % (path, exc.strerror or exc)
    if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400) \
            or (hasattr(os.path, "isjunction") and os.path.isjunction(path)):
        return "%s is a link or junction: outputs are never written through one" % path
    if not stat.S_ISREG(st.st_mode):
        return "%s is not a regular file" % path
    if st.st_nlink > 1:
        return "%s is a hard link: writing it would change its other names too" % path
    return None


def write_output(path, data):
    """Write bytes to an output file (R2-M03): an existing name refused by output_name_problem raises InputError and
    nothing is written; otherwise a new temporary file is created exclusively in the destination folder (never
    following a link) and put in place with os.replace, so no existing name is ever written through."""
    why = output_name_problem(path)
    if why:
        raise InputError(why)
    folder = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(folder, ".%s.%s.tmp" % (os.path.basename(path), secrets.token_hex(8)))
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o644)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError as exc:
        if os.path.lexists(tmp):
            os.remove(tmp)
        raise InputError("%s could not be written: %s" % (path, exc.strerror or exc))


def sha256_file(path):
    return sha256(read_bytes_any(path))


def read_bytes_any(path):
    """Read a file of any size (fonts, scripts) for hashing."""
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise InputError("cannot read %s: %s" % (path, exc.strerror or exc))


if yaml is not None:
    class StrictLoader(yaml.SafeLoader):
        """SafeLoader that refuses duplicate keys at any level, identical values included."""

    def _construct_mapping(loader, node, deep=False):
        loader.flatten_mapping(node)
        seen = {}
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=True)
            if key in seen:
                raise ContentError("duplicate key %r at line %d (first at line %d)"
                                   % (key, key_node.start_mark.line + 1, seen[key]))
            seen[key] = key_node.start_mark.line + 1
        return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)

    StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)
    # YAML 1.2 booleans only: PyYAML follows YAML 1.1, where the policy key `off:` (and on, yes, no) would
    # become a boolean and a section switched off would silently read as configured.
    StrictLoader.yaml_implicit_resolvers = {
        first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()}
    StrictLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF"))


def require_yaml():
    if yaml is None:
        raise InputError("PyYAML is not installed for this Python (pip install pyyaml); ask the owner")


def depth(obj, level=0):
    if level > MAX_DEPTH:
        return level
    if isinstance(obj, dict):
        return max([depth(v, level + 1) for v in obj.values()] or [level + 1])
    if isinstance(obj, list):
        return max([depth(v, level + 1) for v in obj] or [level + 1])
    return level


def load_yaml_text(text, name):
    """Parse YAML strictly; the document must be a mapping within the depth limit."""
    require_yaml()
    try:
        data = yaml.load(text, Loader=StrictLoader)
    except ContentError as exc:
        raise ContentError("%s: %s" % (name, exc))
    except yaml.YAMLError as exc:
        raise ContentError("%s is not valid YAML: %s" % (name, str(exc).splitlines()[0]))
    if not isinstance(data, dict):
        raise ContentError("%s is not a mapping" % name)
    if depth(data) > MAX_DEPTH:
        raise ContentError("%s nests deeper than %d" % (name, MAX_DEPTH))
    return data


SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
GIT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def load_json_strict(text, name):
    """Parse JSON with duplicate keys refused at any level (a receipt, a snapshot; plan 0.4 B.9's seventh file)."""
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ContentError("%s: duplicate key %r" % (name, k))
            out[k] = v
        return out
    try:
        return json.loads(text, object_pairs_hook=pairs)
    except ValueError as exc:
        raise ContentError("%s is not valid JSON: %s" % (name, exc))


def split_front_matter(text, name="DESIGN.md"):
    """Front matter between a first line that is exactly '---' and the next line that is exactly '---'."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ContentError("%s: the first line is not exactly ---" % name)
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":
            return "".join(lines[1:i]), "".join(lines[i + 1:])
    raise ContentError("%s: no closing --- line" % name)


class Snapshot:
    """Every file read once; the same bytes are hashed and used (no re-reading)."""

    def __init__(self):
        self.files = {}

    def read(self, path):
        real = os.path.realpath(path)
        if real not in self.files:
            self.files[real] = read_bytes(real)
        return self.files[real]

    def text(self, path):
        try:
            return self.read(path).decode("utf-8")
        except UnicodeDecodeError:
            raise ContentError("%s is not UTF-8 text" % path)

    def digest(self, path):
        return sha256(self.read(path))


# ---------------------------------------------------------------- typed values

HEX = re.compile(r"^#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
RGB = re.compile(r"^rgba?\(\s*(.*?)\s*\)$", re.I)
NUM = r"[+-]?(?:\d+\.?\d*|\.\d+)"
DIM = re.compile(r"^(%s)(px|em|rem|%%|vw|vh|vmin|vmax|ch|ex|pt|s|ms|deg)?$" % NUM)
NAMED = {"white": (255, 255, 255), "black": (0, 0, 0)}


def canon_decimal(d):
    d = d.normalize()
    if d == d.to_integral():
        return d.quantize(Decimal(1))
    return d


class Colour:
    __slots__ = ("r", "g", "b", "a")

    def __init__(self, r, g, b, a=Decimal(1)):
        self.r, self.g, self.b, self.a = r, g, b, canon_decimal(Decimal(a))

    def key(self):
        return (self.r, self.g, self.b, self.a)

    def __eq__(self, other):
        return isinstance(other, Colour) and self.key() == other.key()

    def __hash__(self):
        return hash(self.key())

    def near(self, other, tol=ALPHA_TOL):
        """Browser-serialised comparison: equal channels, alpha within tol."""
        return (self.r, self.g, self.b) == (other.r, other.g, other.b) and abs(self.a - other.a) <= tol

    def __repr__(self):
        if any(Decimal(str(c)) != Decimal(str(c)).to_integral_value() for c in (self.r, self.g, self.b)):
            # a converted colour with fractional channels (color(srgb ...); R2-H05): never a token, shown as it is
            return "rgb(%s %s %s / %s)" % (self.r, self.g, self.b, self.a)
        if self.a == 1:
            return "#%02x%02x%02x" % (int(self.r), int(self.g), int(self.b))
        return "rgba(%d, %d, %d, %s)" % (self.r, self.g, self.b, self.a)


def parse_colour(text):
    """A Colour for hex (3/4/6/8 digits), rgb()/rgba() with commas or spaces and an optional '/ alpha',
    'transparent', 'white', 'black'; None otherwise."""
    s = str(text).strip()
    low = s.lower()
    if low == "transparent":
        return Colour(0, 0, 0, 0)
    if low in NAMED:
        return Colour(*NAMED[low])
    m = HEX.match(s)
    if m:
        h = m.group(1).lower()
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        # an authored hex alpha is exact (k/255, never rounded): #00000001 is not rgba(0,0,0,.0039) (AST-M17)
        a = Decimal(int(h[6:8], 16)) / Decimal(255) if len(h) == 8 else Decimal(1)
        return Colour(r, g, b, a)
    m = RGB.match(s)
    if m:
        inner = m.group(1)
        if "/" in inner:
            chans, alpha = inner.split("/", 1)
            parts = chans.replace(",", " ").split() + [alpha.strip()]
        else:
            parts = [p for p in re.split(r"[,\s]+", inner) if p]
        if len(parts) not in (3, 4):
            return None
        try:
            chans = [Decimal(p) for p in parts[:3]]
            a = Decimal(parts[3].rstrip("%")) / (100 if parts[3].endswith("%") else 1) if len(parts) == 4 else Decimal(1)
        except (InvalidOperation, ValueError):
            return None
        if any(c != c.to_integral_value() for c in chans):
            return None
        rgb = [int(c) for c in chans]
        if not all(0 <= c <= 255 for c in rgb) or not (0 <= a <= 1):
            return None
        return Colour(rgb[0], rgb[1], rgb[2], a)
    return None


COLOR_FN = re.compile(r"^color\(\s*(srgb|srgb-linear)\s+([^/)]*?)\s*(?:/\s*([^)]*?)\s*)?\)$", re.I)


def parse_computed_colour(text):
    """parse_colour, and the computed colour spaces the plugin converts exactly (R2-H05): color(srgb r g b [/ a]) and
    color(srgb-linear r g b [/ a]), channels 0-1 scaled to 0-255 (fractional channels kept: such a colour is never a
    token's exact value). None for any other space (display-p3, lab, oklch, ...): the caller reports it, never skips it."""
    c = parse_colour(text)
    if c is not None:
        return c
    m = COLOR_FN.match(str(text).strip())
    if not m:
        return None
    try:
        chans = [Decimal(x) for x in m.group(2).split()]
        a = Decimal(1) if m.group(3) is None else (Decimal(m.group(3)[:-1]) / 100 if m.group(3).endswith("%") else Decimal(m.group(3)))
    except (InvalidOperation, ValueError):
        return None
    if len(chans) != 3 or not all(0 <= x <= 1 for x in chans) or not 0 <= a <= 1:
        return None
    if m.group(1).lower() == "srgb-linear":     # encode: the sRGB transfer function, in 40-digit decimal arithmetic
        with localcontext() as lc:
            lc.prec = 40
            chans = [x * Decimal("12.92") if x <= Decimal("0.0031308") else
                     Decimal("1.055") * x ** (Decimal(1) / Decimal("2.4")) - Decimal("0.055") for x in chans]
    # 0-255, quantised to 1e-9 (the decimal arithmetic's rounding is far below it; an integral channel stays integral)
    rgb = [canon_decimal((x * 255).quantize(Decimal("1e-9"))) for x in chans]
    return Colour(rgb[0], rgb[1], rgb[2], a)


def parse_dimension(text, units=("px", "em", "rem")):
    m = DIM.match(str(text).strip())
    if not m or (m.group(2) or "") not in units:
        return None
    return (canon_decimal(Decimal(m.group(1))), m.group(2))


def split_top(s, sep):
    out, level, cur, quote = [], 0, "", None
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([":
            level += 1
        elif ch in ")]":
            level -= 1
        if ch == sep and level == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def typed(value):
    """A typed form of a CSS or token value for exact comparison."""
    s = re.sub(r"\s+", " ", str(value).strip())
    c = parse_colour(s)
    if c is not None:
        return ("colour", c.key())
    m = DIM.match(s)
    if m:
        return ("dim", canon_decimal(Decimal(m.group(1))), m.group(2) or "")
    m = re.match(r"^clamp\((.*)\)$", s, re.I)
    if m:
        parts = [p.strip() for p in split_top(m.group(1), ",")]
        if len(parts) == 3:
            return ("clamp", tuple(typed(p) for p in parts))
    if s.lower().startswith(("calc(", "var(", "rgba(", "rgb(", "linear-gradient(", "radial-gradient(")):
        return ("text", re.sub(r"\s*([(),/*+])\s*", r"\1", s))
    parts = [p for p in split_top(s, " ") if p]
    if len(parts) > 1:
        return ("seq", tuple(typed(p) for p in parts))
    items = split_top(s, ",")
    if len(items) > 1:       # a comma list only at the top level: commas inside a function or a string are one item (V3)
        return ("list", tuple(typed(p) for p in items))
    return ("text", s.strip("\"'"))


def same(a, b):
    """Exact typed equality of two authored values."""
    return typed(a) == typed(b)


def clamp_parts(text):
    t = typed(text)
    return t[1] if t[0] == "clamp" else None


# ---------------------------------------------------------------- references

REF = re.compile(r"^\{([a-z]+)\.([a-z0-9-]+)\}$")


def is_ref(value):
    return isinstance(value, str) and REF.match(value.strip()) is not None


def resolve(value, groups, seen=None):
    """Resolve {group.token} references; ContentError on a missing target or a cycle."""
    seen = seen or []
    if not is_ref(value):
        return value
    g, name = REF.match(value.strip()).groups()
    if value in seen:
        raise ContentError("reference cycle: %s" % " -> ".join(seen + [value]))
    target = (groups.get(g) or {}).get(name)
    if target is None:
        raise ContentError("reference %s does not resolve" % value)
    return resolve(target, groups, seen + [value])


# ---------------------------------------------------------------- contrast (WCAG 2.x)

def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = (_lin(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def composite(fg, bg_rgb):
    """Fractional channels: fg Colour over an opaque bg (r, g, b) floats."""
    a = float(fg.a)
    return tuple(a * f + (1 - a) * b for f, b in zip((fg.r, fg.g, fg.b), bg_rgb))


def flatten(layers):
    """Opaque rgb from a bottom-up list of Colours (the first must be opaque, else white is assumed by the caller)."""
    rgb = (layers[0].r, layers[0].g, layers[0].b)
    for c in layers[1:]:
        rgb = composite(c, rgb)
    return rgb


def ratio(rgb1, rgb2):
    hi, lo = sorted((luminance(rgb1), luminance(rgb2)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def ratio_8bit(rgb1, rgb2):
    return ratio(tuple(round(x) for x in rgb1), tuple(round(x) for x in rgb2))


def is_large(size_px, weight):
    size = Decimal(str(size_px))
    return size >= LARGE_PX or (size >= LARGE_BOLD_PX and int(weight or 400) >= 700)


# ---------------------------------------------------------------- report

class Report:
    """Items with a status; the outcome follows plan 0.4 B.7.0."""

    STATUSES = ("PASS", "FAIL", "WAIVED", "WARN", "INCOMPLETE", "NOT_CONFIGURED", "NOT_CHECKED", "INFO")

    def __init__(self, tool):
        self.tool, self.items, self.error = tool, [], None

    def add(self, status, check, path, detail="", **extra):
        if status not in self.STATUSES:
            raise ValueError("unknown status %r" % status)
        item = {"status": status, "check": check, "path": path, "detail": detail}
        item.update(extra)
        self.items.append(item)
        return item

    def count(self, status):
        return sum(1 for i in self.items if i["status"] == status)

    def find(self, check, path, status="FAIL"):
        return [i for i in self.items if i["check"] == check and i["path"] == path and i["status"] == status]

    def outcome(self):
        if self.error:
            return self.error
        if self.count("FAIL"):
            return "FAIL"
        if self.count("INCOMPLETE"):
            return "INCOMPLETE"
        return "PASS"

    def summary(self):
        counts = ", ".join("%s %d" % (s, self.count(s)) for s in self.STATUSES if self.count(s))
        return "%s: %s (%s)" % (self.tool, self.outcome(), counts or "no items")

    def text(self):
        rows = ["%-14s %-6s %-48s %s" % (i["status"], i["check"], i["path"], i["detail"]) for i in self.items]
        return "\n".join(rows + ["", self.summary()])

    def json(self):
        return json.dumps({"tool": self.tool, "outcome": self.outcome(), "items": self.items}, indent=1, default=str)
