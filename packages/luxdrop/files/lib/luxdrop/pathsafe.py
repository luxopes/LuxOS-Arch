"""LuxDrop - bezpecne cesty: kontrola nabidky u prijemce a sber souboru u odesilatele."""
import os
import stat
import unicodedata

from . import proto

MAX_FILES = 100_000
MAX_PATH = 4096
MAX_COMPONENT = 255
MAX_DEPTH = 64
MAX_TOTAL = 1 << 53  # bezpecne cele cislo i v JSON/JavaScriptu
# Znaky pro obraceni smeru textu (napr. "foto\u202egpj.exe" vypada jako "fotoexe.jpg")
BIDI = set("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def _bad(msg):
    return proto.ProtocolError(proto.E_INVALID_OFFER, msg)


def check_relpath(path):
    """Overi relativni cestu z nabidky; vrati tuple slozek nebo vyhodi ProtocolError.

    Povoleno: slozky oddelene "/", kazda neprazdna, bez "." a "..", bez "\\", NUL
    a ridicich znaku, max. 255 bajtu na slozku a 4096 na celou cestu.
    """
    if not isinstance(path, str) or not path:
        raise _bad("empty path")
    if unicodedata.normalize("NFC", path) != path:
        raise _bad("path must be NFC normalized: %r" % path)
    if len(path.encode("utf-8", "surrogatepass")) > MAX_PATH:
        raise _bad("path too long")
    if path.startswith("/") or path.startswith("~"):
        raise _bad("absolute path: %r" % path)
    if "\\" in path:
        raise _bad("backslash in path: %r" % path)
    if any(ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0 or c in BIDI for c in path):
        raise _bad("control character in path: %r" % path)
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        raise _bad("invalid characters in path") from None
    parts = path.split("/")
    if len(parts) > MAX_DEPTH:
        raise _bad("path too deep")
    for p in parts:
        if p in ("", ".", ".."):
            raise _bad("invalid path component in %r" % path)
        if len(p.encode("utf-8")) > MAX_COMPONENT:
            raise _bad("path component too long")
    return tuple(parts)


def check_offer(offer):
    """Overi nabidku a vrati (soubory, slozky, celkova velikost).

    soubory: seznam slovniku {path, parts, size, sha256 (bytes), exec}
    """
    files = offer.get("files")
    dirs = offer.get("dirs", [])
    if not isinstance(files, list) or not isinstance(dirs, list):
        raise _bad("files/dirs must be lists")
    if not files and not dirs:
        raise _bad("nothing to send")
    if len(files) + len(dirs) > MAX_FILES:
        raise _bad("too many files")
    out_files, out_dirs = [], []
    file_set, dir_set = set(), set()
    total = 0
    for i, f in enumerate(files):
        if not isinstance(f, dict):
            raise _bad("file entry must be an object")
        parts = check_relpath(f.get("path"))
        size = f.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > MAX_TOTAL:
            raise _bad("invalid size")
        sha = proto.hex32(f.get("sha256"), "sha256")
        total += size
        if total > MAX_TOTAL:
            raise _bad("total size too large")
        out_files.append({"index": i, "path": "/".join(parts), "parts": parts, "size": size,
                          "sha256": sha, "exec": bool(f.get("exec", False))})
        file_set.add(parts)
    for d in dirs:
        parts = check_relpath(d)
        out_dirs.append(parts)
        dir_set.add(parts)
    # Duplicity a kolize soubor/slozka (napr. soubor "a" a soubor "a/b")
    if len(file_set) != len(out_files) or len(dir_set) != len(out_dirs):
        raise _bad("duplicate path")
    for parts in file_set | dir_set:
        for k in range(1, len(parts)):
            if parts[:k] in file_set:
                raise _bad("path below a file: %s" % "/".join(parts))
    for parts in dir_set:
        if parts in file_set:
            raise _bad("path is both file and directory")
    return out_files, out_dirs, total


def collect(paths, on_skip=None):
    """Sesbira soubory k odeslani.

    Vrati (polozky, slozky): polozky = [(lokalni_cesta, rel_cesta, velikost, exec)],
    slozky = [rel_cesta] (vsechny slozky vcetne prazdnych). Uvnitr slozek se
    nenasleduji symlinky; preskoci se i zarizeni, roury a sokety (on_skip(cesta, duvod)).
    """
    items, dirs = [], []
    used_top = set()
    for p in paths:
        p = os.path.abspath(p)
        try:
            st = os.stat(p)  # vybrany soubor muze byt symlink - uzivatel ho vybral vedome
        except OSError as e:
            raise FileNotFoundError("%s: %s" % (p, e.strerror)) from None
        top = unicodedata.normalize("NFC", os.path.basename(p.rstrip("/")) or "root")
        base, n = top, 2
        while top.casefold() in used_top:
            top = "%s (%d)" % (base, n)
            n += 1
        used_top.add(top.casefold())
        if stat.S_ISREG(st.st_mode):
            items.append((p, top, st.st_size, bool(st.st_mode & 0o111)))
        elif stat.S_ISDIR(st.st_mode):
            dirs.append(top)
            _walk(p, top, items, dirs, on_skip)
        elif on_skip:
            on_skip(p, "not a regular file")
    for _p, rel, _s, _x in items:
        check_relpath(rel)
    for rel in dirs:
        check_relpath(rel)
    return items, dirs


def _walk(root, rel_root, items, dirs, on_skip):
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError as e:
        if on_skip:
            on_skip(root, e.strerror or str(e))
        return
    for e in entries:
        name = unicodedata.normalize("NFC", e.name)
        rel = rel_root + "/" + name
        try:
            check_relpath(rel)
        except proto.ProtocolError as err:
            if on_skip:
                on_skip(e.path, err.message)
            continue
        try:
            st = e.stat(follow_symlinks=False)
        except OSError as err:
            if on_skip:
                on_skip(e.path, err.strerror or str(err))
            continue
        if stat.S_ISLNK(st.st_mode):
            if on_skip:
                on_skip(e.path, "symbolic link")
        elif stat.S_ISREG(st.st_mode):
            items.append((e.path, rel, st.st_size, bool(st.st_mode & 0o111)))
        elif stat.S_ISDIR(st.st_mode):
            dirs.append(rel)
            _walk(e.path, rel, items, dirs, on_skip)
        elif on_skip:
            on_skip(e.path, "special file")
