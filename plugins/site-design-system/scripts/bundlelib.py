"""bundlelib.py — what both page checkers share about a bundle (outside audit round 1: AST-H01, AST-H02, AUD-F03).

One guard for every bundle file a checker reads: a forbidden name in any path component (VCS folders, .env files and
folders, private keys, the site design folder's own file names), bytes equal to any file of the site design folder,
links, junctions, reparse points, hard links and non-regular files. One reader that opens each file once without
following links and returns the bytes it checked, so the bytes parsed, hashed and staged are the same. One resolver of
references (percent-decoding included), so both checkers name the same file. HTML attributes where the first of
duplicate attributes wins, as in browsers. Standard library only."""
import os
import posixpath
import re
import stat
import urllib.parse

import designlib as dl

# A forbidden name in any path component (AST-H01): VCS folders, .env files or folders, private keys.
FORBIDDEN_COMPONENT = re.compile(r"^(\.(git|hg|svn)|\.env.*|.+\.(pem|key))$", re.I)
# One portable component grammar, applied on every platform before anything is opened, logged or staged (R2-H01):
# Windows opens another name than the one a guard checked when a component ends in a dot or a space ('vault.key.'),
# holds a colon (a stream such as '::$DATA', a drive), a reserved character, a short 8.3 alias ('GIT~1') or a device name.
WINDOWS_CHARS = re.compile(r'[\\<>"|?*\x00-\x1f]')    # a control character names no bundle file either (C5)
SHORT_ALIAS = re.compile(r"~[0-9]")
DEVICE = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³]) *(\..*)?$", re.I)
MISSING = "missing"            # the reader's answer for a file that does not exist (A10 names it; not a refusal)
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def first_attrs(attrs):
    """Attributes of one HTML start tag, the first of duplicates kept (HTML parsing and Chromium; AUD-F03(1))."""
    out = {}
    for k, v in attrs:
        out.setdefault(k.lower(), v or "")
    return out


def component_problem(part):
    """None, or why one path component is refused by the portable grammar (R2-H01). '.' and '..' are normalised by the
    resolver before this is asked; here they end in a dot and are refused like any other such name."""
    if part.endswith((".", " ")):
        return "ends in a dot or a space (Windows opens the name without them)"
    if ":" in part:
        return "holds a colon (a stream or a drive on Windows)"
    if WINDOWS_CHARS.search(part):
        return "holds a character Windows reserves"
    if SHORT_ALIAS.search(part):
        return "holds ~ and a digit (a Windows short name may alias a long one)"
    if DEVICE.match(part):
        return "is a Windows device name"
    return None


def path_problem(rel):
    """None, or why a bundle-relative path (forward slashes) is refused by the component grammar (R2-H01). The reason
    names the component, never a byte of any file."""
    for part in rel.split("/"):
        why = component_problem(part)
        if why:
            return "%r: the component %r %s" % (rel, part, why)
    return None


def name_problem(rel, profile_names):
    """None, or why a bundle path must never be read or staged because of a name in any of its components."""
    why = path_problem(rel)          # the grammar first: a guard that checks one name while Windows opens another is none
    if why:
        return why
    for part in rel.split("/"):
        if FORBIDDEN_COMPONENT.match(part):
            return "%s matches a VCS or secret pattern" % rel
        if part.casefold() in profile_names:
            return "%s carries a site design folder file name" % rel
    return None


def resolve_ref(ref, base_dir, bundle):
    """('skip'|'remote'|'outside'|'local', value): a reference as both checkers resolve it (percent-decoded, as the
    browser and the loopback server do). For 'local' the value is the bundle-relative path with forward slashes; a
    decoded path the portable grammar refuses (a control character U+0000-U+001F included, C5) is 'outside'."""
    r = ref.strip()
    if not r or r.startswith("#"):
        return "skip", r
    low = r.lower()
    if low.startswith(("data:", "blob:", "about:", "javascript:", "mailto:", "tel:")):
        return "skip", r
    if re.match(r"^[a-z][a-z0-9+.-]*:", low) or r.startswith("//") or r.startswith("\\"):
        return "remote", r
    path = urllib.parse.unquote(r.split("#", 1)[0].split("?", 1)[0]).replace("\\", "/")
    if not path:
        return "skip", r
    joined = posixpath.normpath(path.lstrip("/") if path.startswith("/") else posixpath.join(base_dir, path))
    if joined == ".." or joined.startswith("../") or posixpath.isabs(joined) or re.match(r"^[A-Za-z]:", joined):
        return "outside", r
    if joined in ("", "."):
        return "skip", r
    if path_problem(joined):              # the portable grammar, before any join with a real folder (R2-H01)
        return "outside", r
    full = os.path.normpath(os.path.join(bundle, *joined.split("/")))
    try:
        inside = os.path.commonpath([full, bundle]) == bundle
    except ValueError:                    # another drive: named as outside, never an internal error (R2-H01)
        inside = False
    if not inside:
        return "outside", r
    return "local", joined


def _is_link(path, st):
    if stat.S_ISLNK(st.st_mode) or (getattr(st, "st_file_attributes", 0) & REPARSE):
        return True
    return hasattr(os.path, "isjunction") and os.path.isjunction(path)


def _leaf_problem(rel, st):
    if not stat.S_ISREG(st.st_mode):
        return "%s is not a regular file" % rel
    if st.st_nlink > 1:
        return "%s is a hard link" % rel
    return None


def _read_fd(fd, limit):
    chunks, total = [], 0
    while total <= limit:
        chunk = os.read(fd, min(1 << 20, limit + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _posix_walk():
    return hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd


class BundleRoot:
    """The bundle root, opened once for a whole closure (R2-M01). A link or a non-folder at the root is refused. On POSIX
    its descriptor is kept and every file is read relative to it, never the path reopened; on every platform the root's
    identity (device and file id) is checked before and after each read, so a root replaced during the run is refused."""

    def __init__(self, path):
        self.path, self.fd = path, None
        try:
            st = os.lstat(path)
        except OSError as exc:
            raise ValueError("the bundle root %s cannot be read: %s" % (path, exc.strerror or exc))
        if _is_link(path, st) or not stat.S_ISDIR(st.st_mode):
            raise ValueError("the bundle root %s is a link or not a folder" % path)
        self.ident = (st.st_dev, st.st_ino)
        if _posix_walk():
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
            fst = os.fstat(fd)
            if (fst.st_dev, fst.st_ino) != self.ident:
                os.close(fd)
                raise ValueError("the bundle root %s changed while it was opened" % path)
            self.fd = fd

    def problem(self):
        """None while the path still names the folder opened at first; else why every further read is refused."""
        try:
            st = os.lstat(self.path)
        except OSError:
            return "the bundle root %s changed while the closure was read" % self.path
        if _is_link(self.path, st) or (st.st_dev, st.st_ino) != self.ident:
            return "the bundle root %s changed while the closure was read" % self.path
        return None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _root_fd(bundle, cloexec):
    """A directory descriptor where one read starts: a duplicate of the trusted root's descriptor (R2-M01), or, for a
    plain path (the checker's own stage), that path opened without following a link at it."""
    if isinstance(bundle, BundleRoot):
        return os.dup(bundle.fd)
    return os.open(bundle, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | cloexec)


def _read_posix(bundle, parts, rel, limit):
    """Walk with directory descriptors and O_NOFOLLOW: no component can be swapped for a link between checks."""
    cloexec = getattr(os, "O_CLOEXEC", 0)
    try:
        fd = _root_fd(bundle, cloexec)
    except OSError:
        return None, "%s: the bundle root is a link or not a folder" % rel
    try:
        for part in parts[:-1]:
            try:
                nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | cloexec, dir_fd=fd)
            except FileNotFoundError:
                return None, MISSING
            except OSError:
                return None, "%s: a folder on its path is a link or not a folder" % rel
            os.close(fd)
            fd = nfd
        try:
            ffd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | cloexec | getattr(os, "O_NONBLOCK", 0), dir_fd=fd)
        except FileNotFoundError:
            return None, MISSING
        except OSError:
            return None, "%s is a link or junction" % rel
        try:
            st = os.fstat(ffd)
            why = _leaf_problem(rel, st)
            if why:
                return None, why
            return _read_fd(ffd, limit), None
        finally:
            os.close(ffd)
    finally:
        os.close(fd)


def _read_windows(bundle, parts, rel, limit):
    """No directory descriptors on Windows: every component is checked for a link, junction or reparse point, the file
    is opened and its handle compared with the walk, then every component is checked again (unchanged). The root's own
    identity is checked by safe_read before and after (R2-M01)."""
    cur, walk = (bundle.path if isinstance(bundle, BundleRoot) else bundle), []
    for part in parts:
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            return None, MISSING
        except OSError as exc:
            return None, "%s cannot be read: %s" % (rel, exc.strerror or exc)
        if _is_link(cur, st):
            return None, "%s is a link or junction" % rel
        walk.append((cur, st.st_ino, st.st_dev))
    why = _leaf_problem(rel, st)
    if why:
        return None, why
    fd = os.open(cur, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        after = os.fstat(fd)
        if (after.st_ino, after.st_dev, after.st_size) != (st.st_ino, st.st_dev, st.st_size):
            return None, "%s changed while it was read" % rel
        data = _read_fd(fd, limit)
    finally:
        os.close(fd)
    for path, ino, dev in walk:
        try:
            again = os.lstat(path)
        except OSError:
            return None, "%s changed while it was read" % rel
        if (again.st_ino, again.st_dev) != (ino, dev) or _is_link(path, again):
            return None, "%s changed while it was read" % rel
    return data, None


def safe_read(bundle, rel, limit):
    """(bytes, problem) for a bundle-relative path: the bytes of a regular file read once (at most limit + 1 bytes, so
    the caller sees an overrun), or problem MISSING, or why it was refused. The name guard is the caller's."""
    parts = [p for p in rel.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        return None, "%s is not a path inside the bundle" % rel
    why = path_problem("/".join(parts))       # the reader refuses the grammar itself, on every platform (R2-H01)
    if why:
        return None, why
    root = bundle if isinstance(bundle, BundleRoot) else None
    if root is not None and root.problem():   # the trusted root is still the folder opened at first (R2-M01)
        return None, root.problem()
    if _posix_walk():
        data, why = _read_posix(bundle, parts, rel, limit)
    else:
        data, why = _read_windows(bundle, parts, rel, limit)
    if root is not None and root.problem():
        return None, root.problem()
    return data, why


class Guard:
    """The read-time guard of both checkers (AST-H01): names, links, and bytes equal to a site design folder file."""

    def __init__(self, profile, folder_files):
        # the profile files' names in any case; a README is refused by its bytes, not its name (AST-H01)
        self.profile_names = {"site.yaml", "design.md", "trace-map.yaml", "contrast.yaml", "policy.yaml", "waivers.yaml",
                              "ready.json"}
        self.private = {}
        for name in list(folder_files) + ["ready.json"]:
            full = os.path.join(profile.dir, *name.split("/"))
            if os.path.isfile(full):
                self.private[profile.snap.digest(full)] = name

    def read(self, bundle, rel, limit):
        """(bytes, problem) as safe_read, after the name guard; bytes equal to a private file are refused."""
        why = name_problem(rel, self.profile_names)
        if why:
            return None, why
        data, why = safe_read(bundle, rel, limit)
        if why:
            return None, why
        hit = self.private.get(dl.sha256(data))
        if hit:
            return None, "%s has the same bytes as the site design folder's %s" % (rel, hit)
        return data, None
