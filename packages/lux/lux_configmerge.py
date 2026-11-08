#!/usr/bin/python3
"""lux_configmerge - nove verze konfiguracnich souboru z aktualizaci (*.luxnew) se slouci samy.

Kdyz uzivatel zmenil soubor backup= baliku (napr. /etc/lux/lux.conf: channel = "staging") a nova
verze baliku zmenila vychozi soubor, libalpm necha soubor uzivatele a novou verzi ulozi jako
SOUBOR.luxnew (do LuxOS 1.0 .pacnew). LuxOS je bezstarostny: slouceni udela sam.

Trojcestne slouceni: zaklad = soubor ze STARE verze baliku (kopie v /var/lib/lux/pristine/<cesta>,
overena proti kontrolnimu souctu v databazi baliku pred transakci), nase = soubor v /etc,
jejich = SOUBOR.luxnew.

  - soubory "klic = hodnota" (TOML, INI, /etc/lux/lux.conf): po klicich - hodnota, kterou uzivatel
    ma, zustava VZDY (novou vychozi hodnotu jen kdyz se hodnota uzivatele presne rovna STARE
    vychozi; pri neznamem zakladu nikdy); nove klice, sekce a komentare z nove verze. Klice, ktere
    zapisuje lux-config (lux.conf: channel, countme), patri uzivateli vzdy.
  - ostatni textove soubory: radkove diff3 - jen bez konfliktu.
  - bez zakladu (starsi zbyle *.luxnew): jen kdyz nova verze pridava (klice, komentare, radky).

Uspech: zapis atomicky, jedna zaloha SOUBOR.lux-old, *.luxnew pryc. Konflikt: soubor zustane,
*.luxnew zustane a hlaseni rekne, ze system bezi se soucasnym souborem a jak to projit
(sudo lux config-diff SOUBOR).

  lux_configmerge.py pre  [--root R]     hook pred transakci (NeedsTargets: cesty na stdin) -
                                         zaklad pro slouceni (kopie stare verze souboru)
  lux_configmerge.py post [--root R]     hook po transakci: slouceni + nove kopie
  lux_configmerge.py merge [--root R] [--quiet]   zbyle *.luxnew (lux update, LuxOS Care)
  lux_configmerge.py diff SOUBOR [--keep|--new|--merge]   lux config-diff
  lux_configmerge.py pending [--root R]  cekajici *.luxnew (jeden na radek)

Spolecne volby: --dbpath (vychozi R/var/lib/lux), --cachedir (vychozi R/var/cache/lux/pkg).
Promenne: LUX_CONFIG_MERGE_QUIET=1 (hook nic nevypise - lux to vypise sam),
LUX_CONFIG_MERGE_RESULT=/cesta (vysledky jako JSON; cesta v koreni systemu).
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

PRISTINE_DIR = "var/lib/lux/pristine"
NEW_SUFFIXES = (".luxnew", ".pacnew")       # .pacnew: jadro pred LuxOS 1.0
OLD_SUFFIX = ".lux-old"                     # jedna zaloha souboru pred slouceni (jako lux configs)
SCAN_DIRS = ("etc",)
SKIP_DIRS = ("ssl", "ca-certificates")
QUIET_ENV = "LUX_CONFIG_MERGE_QUIET"
RESULT_ENV = "LUX_CONFIG_MERGE_RESULT"
MAX_EXTRACT = 40                            # kopie z cache baliku za jedno spusteni (bez hooku)

# Klice, ktere zapisuje lux-config / Aktualizace softwaru (set-channel, set-countme): patri
# uzivateli vzdy, i kdyz se jeho hodnota rovna stare vychozi.
PINNED = {
    "etc/lux/lux.conf": {("general", "channel"), ("general", "countme")},
}

_TR = None


def _(text):
    global _TR
    if _TR is None:
        _TR = lambda s: s  # noqa: E731
        sys.path.insert(0, "/usr/lib/luxos/python")
        try:
            from luxos_i18n import _ as tr
            _TR = tr
        except ImportError:
            pass
    return _TR(text)


# ---- slouceni textu -----------------------------------------------------------------------------
def _lines(text):
    return text.splitlines(keepends=True)


def _join(lines):
    out = []
    for i, ln in enumerate(lines):
        if i < len(lines) - 1 and not ln.endswith("\n"):
            ln += "\n"
        out.append(ln)
    return "".join(out)


def _intersect(ra, rb):
    lo, hi = max(ra[0], rb[0]), min(ra[1], rb[1])
    return (lo, hi) if lo < hi else None


def _sync_regions(base, a, b):
    """Oblasti, kde se obe strany shoduji se zakladem (jako merge3 z bzr)."""
    am = difflib.SequenceMatcher(None, base, a, autojunk=False).get_matching_blocks()
    bm = difflib.SequenceMatcher(None, base, b, autojunk=False).get_matching_blocks()
    ia = ib = 0
    out = []
    while ia < len(am) and ib < len(bm):
        abase, amatch, alen = am[ia]
        bbase, bmatch, blen = bm[ib]
        i = _intersect((abase, abase + alen), (bbase, bbase + blen))
        if i:
            lo, hi = i
            asub = amatch + (lo - abase)
            bsub = bmatch + (lo - bbase)
            out.append((lo, hi, asub, asub + hi - lo, bsub, bsub + hi - lo))
        if abase + alen < bbase + blen:
            ia += 1
        else:
            ib += 1
    out.append((len(base), len(base), len(a), len(a), len(b), len(b)))
    return out


def diff3(base, ours, theirs):
    """Radkove trojcestne slouceni. Vraci text, nebo None pri konfliktu."""
    # posledni radek bez konce radku se nesmi lisit jen tim (jinak zbytecny konflikt)
    nl = lambda t: t if not t or t.endswith("\n") else t + "\n"  # noqa: E731
    strip = bool(ours) and bool(theirs) and not ours.endswith("\n") and not theirs.endswith("\n")
    zb, za, zt = _lines(nl(base)), _lines(nl(ours)), _lines(nl(theirs))
    res = []
    iz = ia = it = 0
    for zmatch, zend, amatch, aend, tmatch, tend in _sync_regions(zb, za, zt):
        aseg, tseg, zseg = za[ia:amatch], zt[it:tmatch], zb[iz:zmatch]
        if aseg or tseg:
            if aseg == tseg or tseg == zseg:
                res += aseg
            elif aseg == zseg:
                res += tseg
            else:
                return None
        res += zb[zmatch:zend]
        iz, ia, it = zend, aend, tend
    out = _join(res)
    return out[:-1] if strip and out.endswith("\n") else out


def only_additions(ours, theirs):
    """Nova verze jen pridava radky (zadny radek uzivatele nezmizi ani se nezmeni)."""
    sm = difflib.SequenceMatcher(None, _lines(ours), _lines(theirs), autojunk=False)
    return all(op in ("equal", "insert") for op, *_r in sm.get_opcodes())


# ---- soubory "klic = hodnota" (TOML, INI) ------------------------------------------------------
_BARE = r"[A-Za-z0-9_\-]+"
_QUOTED = r'"(?:[^"\\]|\\.)*"|\'[^\']*\''
_KEYPART = rf"(?:{_BARE}|{_QUOTED})"
KEY_RE = re.compile(rf"^\s*({_KEYPART}(?:\s*\.\s*{_KEYPART})*)\s*=(.*)$", re.S)
SECTION_RE = re.compile(rf"^\s*(\[\[?)\s*({_KEYPART}(?:\s*\.\s*{_KEYPART})*)\s*(\]\]?)\s*(?:[#;].*)?$", re.S)


def _norm_name(name):
    return re.sub(r"\s*\.\s*", ".", name.strip())


def _scan_value(text, state):
    """Prochazi hodnotu: state = [hloubka zavorek, otevreny vicerakdovy retezec nebo None].
    Komentar (#) mimo retezec konci radek."""
    i, n = 0, len(text)
    while i < n:
        if state[1]:
            j = text.find(state[1], i)
            if j < 0:
                return
            i = j + 3
            state[1] = None
            continue
        c = text[i]
        if c == "#":
            return
        if text.startswith('"""', i) or text.startswith("'''", i):
            state[1] = text[i:i + 3]
            i += 3
            continue
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            i += 1
            continue
        if c == "'":
            j = text.find("'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if c in "[{":
            state[0] += 1
        elif c in "]}":
            state[0] -= 1
        i += 1


class Item:
    __slots__ = ("kind", "sec", "key", "lines", "lead")

    def __init__(self, kind, sec, key, lines, lead=()):
        self.kind, self.sec, self.key, self.lines, self.lead = kind, sec, key, list(lines), list(lead)

    def value(self):
        """Hodnota pro porovnani (bez rozdilu v mezerach)."""
        text = "".join(self.lines)
        text = text.split("=", 1)[1] if "=" in text else text
        return re.sub(r"\s+", " ", text).strip()


class KeyDoc:
    """Soubor jako posloupnost polozek: sekce, klic (i vicerakdova hodnota), ostatni (komentar, prazdny)."""

    def __init__(self, items):
        self.items = items
        self.keys = {(it.sec, it.key): it for it in items if it.kind == "key"}
        self.sections = [it.sec for it in items if it.kind == "section"]


def parse_keys(text):
    """KeyDoc, nebo None, kdyz soubor neni ciste "klic = hodnota" (pak radkove slouceni)."""
    if text is None:
        return None
    lines = _lines(text)
    items, sec, seen, secs = [], "", set(), set()
    lead = []
    nkeys = 0
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s or s[0] in "#;":
            items.append(Item("other", sec, None, [ln]))
            lead = lead + [ln] if s else []
            i += 1
            continue
        m = SECTION_RE.match(ln)
        if m and KEY_RE.match(ln) is None:
            if m.group(1) == "[[" or m.group(3) == "]]":
                return None             # pole tabulek: opakovane sekce, po klicich nejde
            sec = _norm_name(m.group(2))
            if sec in secs:
                return None
            secs.add(sec)
            items.append(Item("section", sec, None, [ln]))
            lead = []
            i += 1
            continue
        m = KEY_RE.match(ln)
        if not m:
            return None
        key = _norm_name(m.group(1))
        block = [ln]
        state = [0, None]
        _scan_value(m.group(2), state)
        i += 1
        while state[0] > 0 or state[1]:
            if i >= len(lines):
                return None
            block.append(lines[i])
            _scan_value(lines[i], state)
            i += 1
        if (sec, key) in seen:
            return None                 # opakovany klic (seznam) - po klicich nejde
        seen.add((sec, key))
        items.append(Item("key", sec, key, block, lead))
        lead = []
        nkeys += 1
    return KeyDoc(items) if nkeys else None


def _first_section_index(out):
    for i, ln in enumerate(out):
        s = ln.strip()
        if s.startswith("[") and SECTION_RE.match(ln) and not KEY_RE.match(ln):
            return i
    return len(out)


def merge_keys(base, ours, theirs, pinned=()):
    """Slouceni po klicich. Vraci (text, None) nebo (None, duvod)."""
    B = parse_keys(base) if base is not None else None
    O, T = parse_keys(ours), parse_keys(theirs)
    if O is None or T is None or (base is not None and B is None):
        return None, "format"
    out, sec_end, used, covered = [], {}, set(), set()
    in_theirs = {ln.strip() for ln in _lines(theirs)}
    in_base = {ln.strip() for ln in _lines(base)} if base is not None else set()

    def own_lead(o, always=False):
        """Komentare uzivatele tesne nad jeho klicem (ne z nove ani stare verze baliku). Pri
        neznamem zakladu nejde poznat komentar uzivatele od stareho komentare baliku - jen u klicu,
        ktere pridal uzivatel (always)."""
        if B is None and not always:
            return []
        lines = [ln for ln in o.lead if ln.strip() not in in_theirs and ln.strip() not in in_base]
        covered.update(ln.strip() for ln in lines)
        return lines

    cur = ""
    for it in T.items:
        if it.kind == "section":
            cur = it.sec
            out += it.lines
            sec_end[cur] = len(out)
            continue
        if it.kind == "other":
            out += it.lines
            continue
        k = (it.sec, it.key)
        if k in O.keys:
            used.add(k)
            o = O.keys[k]
            # nova vychozi hodnota jen kdyz uzivatel ma presne starou vychozi (a klic neni jeho)
            take_new = B is not None and k in B.keys and o.value() == B.keys[k].value() and k not in pinned
            out += own_lead(o) + (it.lines if take_new else o.lines)
        elif B is not None and k in B.keys:
            # uzivatel klic smazal: zustane smazany; zmenila-li ho nova verze, at rozhodne clovek
            if it.value() != B.keys[k].value():
                return None, "removed:" + ".".join(x for x in k if x)
            continue
        else:
            out += it.lines
        sec_end[cur] = len(out)
    extra = {}
    for k, o in O.keys.items():
        if k in used:
            continue
        if B is not None and k in B.keys:
            # nova verze klic vypustila: hodnotu uzivatele by to zahodilo -> clovek
            if o.value() == B.keys[k].value() and k not in pinned:
                continue
            return None, "dropped:" + ".".join(x for x in k if x)
        extra.setdefault(k[0], []).append(o)
    blocks = {sec: [ln for o in keys for ln in own_lead(o, always=True) + o.lines] for sec, keys in extra.items()}
    # vlastni komentare uzivatele (pri znamem zakladu) se nesmi ztratit
    if B is not None:
        known = in_theirs | in_base | covered
        for it in O.items:
            if it.kind == "other" and it.lines[0].strip() and it.lines[0].strip() not in known:
                return None, "comments"
    tail = []
    inserts = []
    header = {it.sec: it.lines for it in O.items if it.kind == "section"}
    for sec, block in blocks.items():
        if sec in sec_end:
            inserts.append((sec_end[sec], block))
        elif sec == "":
            inserts.append((_first_section_index(out), block))
        else:
            tail += ["\n"] + header.get(sec, ["[%s]\n" % sec]) + block
    for pos, block in sorted(inserts, key=lambda x: -x[0]):
        out[pos:pos] = block
    if tail:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out += tail
    return _join(out), None


def respects_user(base, ours, theirs, merged, pinned=()):
    """Kontrola vysledku: kazda hodnota uzivatele zustala (jinak jen nova vychozi misto presne stare)."""
    B = parse_keys(base) if base is not None else None
    O, T, M = parse_keys(ours), parse_keys(theirs), parse_keys(merged)
    if M is None or O is None:
        return False
    for k, o in O.keys.items():
        m = M.keys.get(k)
        old_default = B is not None and k in B.keys and o.value() == B.keys[k].value() and k not in pinned
        if m is None:
            if not (old_default and k not in T.keys):
                return False
        elif m.value() != o.value():
            if not (old_default and k in T.keys and m.value() == T.keys[k].value()):
                return False
    return True


def _toml_ok(ours, theirs, merged):
    """Byly-li obe verze platne TOML, musi byt i vysledek."""
    if tomllib is None:
        return True
    try:
        tomllib.loads(ours)
        tomllib.loads(theirs)
    except (tomllib.TOMLDecodeError, ValueError):
        return True
    try:
        tomllib.loads(merged)
        return True
    except (tomllib.TOMLDecodeError, ValueError):
        return False


def merge(base, ours, theirs, rel=""):
    """Trojcestne slouceni souboru. base None = neznamy zaklad.
    Vraci (text, zpusob) nebo (None, duvod konfliktu)."""
    if ours == theirs:
        return ours, "same"
    if base is not None and base == theirs:
        base = None     # nova verze = zaklad: zaklad neni spolehlivy (libalpm by .luxnew netvoril)
    pinned = PINNED.get(rel.lstrip("/"), set())
    if parse_keys(ours) is not None and parse_keys(theirs) is not None:
        m, why = merge_keys(base, ours, theirs, pinned)
        if m is not None and respects_user(base, ours, theirs, m, pinned) and _toml_ok(ours, theirs, m):
            return m, "keys"
        if base is not None:
            m = diff3(base, ours, theirs)
            if m is not None and respects_user(base, ours, theirs, m, pinned) and _toml_ok(ours, theirs, m):
                return m, "lines"
        return None, why or "conflict"
    if base is not None:
        m = diff3(base, ours, theirs)
        if m is not None:
            return m, "lines"
        return None, "conflict"
    if only_additions(ours, theirs):
        return theirs, "lines"
    return None, "nobase"


# ---- databaze baliku, kopie stare verze (zaklad) -----------------------------------------------
def md5_bytes(data):
    return hashlib.md5(data).hexdigest()


def md5_file(path):
    try:
        with open(path, "rb") as f:
            return md5_bytes(f.read())
    except OSError:
        return None


def read_file(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _sections(path):
    """Soubor databaze libalpm (%NAZEV% + radky) -> {nazev: [radky]}."""
    out, cur = {}, None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for ln in f:
                ln = ln.rstrip("\n")
                if ln.startswith("%") and ln.endswith("%") and len(ln) > 2:
                    cur = out.setdefault(ln[1:-1], [])
                elif cur is not None and ln:
                    cur.append(ln)
    except OSError:
        pass
    return out


def read_backups(dbpath, names=None):
    """{cesta bez /: (balik, verze, md5)} ze zaznamu %BACKUP% mistni databaze."""
    res = {}
    local = os.path.join(dbpath, "local")
    try:
        entries = os.listdir(local)
    except OSError:
        return res
    for e in entries:
        parts = e.rsplit("-", 2)
        if len(parts) != 3 or (names is not None and parts[0] not in names):
            continue
        d = os.path.join(local, e)
        files = os.path.join(d, "files")
        if not os.path.isfile(files):
            continue
        backup = _sections(files).get("BACKUP")
        if not backup:
            continue
        desc = _sections(os.path.join(d, "desc"))
        name = (desc.get("NAME") or [parts[0]])[0]
        ver = (desc.get("VERSION") or [parts[1] + "-" + parts[2]])[0]
        for ln in backup:
            path, _t, md5 = ln.partition("\t")
            md5 = md5.strip().lower()
            res[path.lstrip("/")] = (name, ver, md5 if re.fullmatch(r"[0-9a-f]{32}", md5) else None)
    return res


def pristine_path(root, rel):
    return os.path.join(root, PRISTINE_DIR, rel)


def _atomic_write(path, data, like=None, mode=0o600):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".lux-merge-", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            if like is not None:
                os.fchmod(f.fileno(), like.st_mode & 0o7777)
                try:
                    os.fchown(f.fileno(), like.st_uid, like.st_gid)
                except OSError:
                    pass
            else:
                os.fchmod(f.fileno(), mode)
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_pristine(root, rel, data):
    base = os.path.join(root, PRISTINE_DIR)
    os.makedirs(base, mode=0o700, exist_ok=True)
    try:
        os.chmod(base, 0o700)
    except OSError:
        pass
    _atomic_write(pristine_path(root, rel), data)


def _drop_pristine(root, rel):
    try:
        os.unlink(pristine_path(root, rel))
    except OSError:
        pass


def cached_package(cachedirs, name, version):
    for d in cachedirs:
        try:
            files = os.listdir(d)
        except OSError:
            continue
        for f in sorted(files):
            if f.startswith(f"{name}-{version}-") and ".pkg.tar" in f and not f.endswith((".sig", ".part")):
                rest = f[len(name) + len(version) + 2:]
                if "-" not in rest.split(".pkg.tar")[0]:     # jen architektura (ne jiny balik/verze)
                    return os.path.join(d, f)
    return None


def extract_from_package(pkgfile, rel):
    try:
        r = subprocess.run(["bsdtar", "-xOqf", pkgfile, rel], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def ensure_pristine(root, rel, entry, cachedirs, extract=True):
    """Kopie verze souboru z baliku (entry = (balik, verze, md5)) v /var/lib/lux/pristine.
    Vraci True, kdyz kopie odpovida md5; jinak starou kopii smaze (neoverena = zadny zaklad)."""
    name, ver, md5 = entry
    if not md5:
        _drop_pristine(root, rel)
        return False
    if md5_file(pristine_path(root, rel)) == md5:
        return True
    data = read_file(os.path.join(root, rel))
    if data is None or md5_bytes(data) != md5:
        data = None
        if extract:
            pkg = cached_package(cachedirs, name, ver)
            if pkg:
                data = extract_from_package(pkg, rel)
                if data is not None and md5_bytes(data) != md5:
                    data = None
    if data is None:
        _drop_pristine(root, rel)
        return False
    try:
        _write_pristine(root, rel, data)
    except OSError:
        return False
    return True


# ---- cekajici *.luxnew ---------------------------------------------------------------------------
def pending(root):
    """Cekajici nove verze: [(cesta k .luxnew, cesta k souboru)] (cesty v koreni root)."""
    res = []
    for top in SCAN_DIRS:
        for dirpath, dirs, files in os.walk(os.path.join(root, top)):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for f in sorted(files):
                for suf in NEW_SUFFIXES:
                    if f.endswith(suf) and len(f) > len(suf):
                        res.append((os.path.join(dirpath, f), os.path.join(dirpath, f[:-len(suf)])))
    return res


def _rel(root, path):
    return os.path.relpath(path, root or "/").replace(os.sep, "/")


def _show(rel):
    return "/" + rel.lstrip("/")


def apply_merged(cur, new, merged_bytes, ours_bytes):
    """Zapis vysledku: zaloha SOUBOR.lux-old (jedna), atomicky zapis, *.luxnew pryc."""
    if merged_bytes != ours_bytes:
        st = os.stat(cur)
        _atomic_write(cur + OLD_SUFFIX, ours_bytes, like=st)
        _atomic_write(cur, merged_bytes, like=st)
    os.unlink(new)


def merge_one(root, new, cur, backups=None):
    """Jedna cekajici nova verze. Vraci slovnik vysledku (status merged | conflict)."""
    rel = _rel(root, cur)
    res = {"path": _show(rel), "new": _show(_rel(root, new))}
    if os.path.islink(new) or os.path.islink(cur) or not os.path.isfile(cur) or not os.path.isfile(new):
        res.update(status="conflict", reason="missing")
        return res
    ours_b, theirs_b = read_file(cur), read_file(new)
    if ours_b is None or theirs_b is None:
        res.update(status="conflict", reason="unreadable")
        return res
    try:
        ours, theirs = ours_b.decode("utf-8"), theirs_b.decode("utf-8")
    except UnicodeDecodeError:
        res.update(status="conflict", reason="binary")
        return res
    base = None
    pb = read_file(pristine_path(root, rel))
    if pb is not None and pb != theirs_b:
        try:
            base = pb.decode("utf-8")
        except UnicodeDecodeError:
            base = None
    merged, how = merge(base, ours, theirs, rel)
    if merged is None:
        res.update(status="conflict", reason=how, base=base is not None)
        return res
    try:
        apply_merged(cur, new, merged.encode("utf-8"), ours_b)
    except OSError as e:
        res.update(status="conflict", reason=f"write: {e.strerror or e}")
        return res
    # nova verze z baliku je zakladem pro priste
    entry = (backups or {}).get(rel)
    if entry and entry[2] and md5_bytes(theirs_b) == entry[2]:
        try:
            _write_pristine(root, rel, theirs_b)
        except OSError:
            pass
    res.update(status="merged", how=how, base=base is not None, changed=merged != ours)
    return res


def merge_pending(root, dbpath):
    backups = read_backups(dbpath)
    return [merge_one(root, new, cur, backups) for new, cur in pending(root)]


def refresh(root, dbpath, cachedirs, targets=None, names=None, extract_limit=MAX_EXTRACT):
    """Kopie soucasne verze souboru z baliku (zaklad pro pristi slouceni). Soubor s cekajici
    *.luxnew se nemeni (jeho kopie je zakladem pro zbyle slouceni)."""
    waiting = {_rel(root, cur) for _n, cur in pending(root)}
    left = extract_limit
    for rel, entry in read_backups(dbpath, names).items():
        if (targets is not None and rel not in targets) or rel in waiting:
            continue
        ok = ensure_pristine(root, rel, entry, cachedirs, extract=left > 0)
        if not ok and left > 0 and entry[2] and md5_file(os.path.join(root, rel)) != entry[2]:
            left -= 1


def pre(root, dbpath, cachedirs, targets=None, names=None):
    """Pred transakci: overena kopie verze, ktera je prave nainstalovana (= zaklad pro slouceni)."""
    for rel, entry in read_backups(dbpath, names).items():
        if targets is not None and rel not in targets:
            continue
        if os.path.exists(pristine_path(root, rel)) or os.path.exists(os.path.join(root, rel)):
            ensure_pristine(root, rel, entry, cachedirs)


# ---- hlaseni -------------------------------------------------------------------------------------
def messages(results):
    """[(druh, text)] pro vysledky: ok = slouceno (klidne), warn = clovek musi projit."""
    out = []
    for r in results:
        if r["status"] == "merged":
            out.append(("ok", _("Updated %s; your settings were kept") % r["path"]))
        else:
            out.append(("warn", _("The new version of %s could not be combined with your changes automatically.")
                        % r["path"]))
            out.append(("note", _("Your current file stays in use and the system works normally. "
                                  "To review it: sudo lux config-diff %s") % r["path"]))
    return out


def print_messages(results, out=None):
    out = out or sys.stdout
    for kind, text in messages(results):
        prefix = {"ok": "✓ ", "warn": "! ", "note": "  "}[kind]
        out.write(prefix + text + "\n")
    out.flush()


def write_results(root, results):
    path = os.environ.get(RESULT_ENV)
    if not path:
        return
    try:
        old = []
        full = os.path.join(root, path.lstrip("/"))
        try:
            with open(full, encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError):
            pass
        seen = {r["path"] for r in results}
        data = [r for r in old if r.get("path") not in seen] + results
        _atomic_write(full, json.dumps(data).encode("utf-8"), mode=0o600)
    except OSError:
        pass


def read_results(root, path, remove=True):
    full = os.path.join(root, path.lstrip("/"))
    try:
        with open(full, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = []
    if remove:
        try:
            os.unlink(full)
        except OSError:
            pass
    return data if isinstance(data, list) else []


def combine(*lists):
    """Vysledky hooku a lux dohromady - kazdy soubor jednou (posledni stav)."""
    res = {}
    for lst in lists:
        for r in lst:
            res[r["path"]] = r
    return list(res.values())


# ---- lux config-diff -----------------------------------------------------------------------------
def _color(out):
    c = os.environ.get("LUX_COLOR")
    if c in ("always", "never"):
        return c == "always"
    return hasattr(out, "isatty") and out.isatty() and not os.environ.get("NO_COLOR")


def _print_diff(a, b, la, lb, out):
    color = _color(out)
    for ln in difflib.unified_diff(_lines(a), _lines(b), la, lb):
        ln = ln if ln.endswith("\n") else ln + "\n"
        if color and ln.startswith("+") and not ln.startswith("+++"):
            ln = "\x1b[32m" + ln[:-1] + "\x1b[0m\n"
        elif color and ln.startswith("-") and not ln.startswith("---"):
            ln = "\x1b[31m" + ln[:-1] + "\x1b[0m\n"
        out.write(ln)


def resolve_target(root, path):
    """Cesta zadana uzivatelem (soubor nebo soubor.luxnew) -> (soubor, .luxnew nebo None)."""
    full = os.path.join(root, path.lstrip("/")) if root not in ("", "/") else os.path.abspath(path)
    for suf in NEW_SUFFIXES:
        if full.endswith(suf):
            full = full[:-len(suf)]
    for suf in NEW_SUFFIXES:
        if os.path.isfile(full + suf):
            return full, full + suf
    return full, None


def config_diff(root, path, choice=None, yes=False, out=None, inp=None):
    out = out or sys.stdout
    inp = inp or sys.stdin
    cur, new = resolve_target(root, path)
    shown = _show(_rel(root, cur))
    if new is None:
        out.write("✓ " + _("No new version of %s is waiting - nothing to do.") % shown + "\n")
        return 0
    ours_b, theirs_b = read_file(cur), read_file(new)
    if theirs_b is None:
        out.write("! " + _("Cannot read %s") % new + "\n")
        return 1
    try:
        ours = ours_b.decode("utf-8") if ours_b is not None else None
        theirs = theirs_b.decode("utf-8")
    except UnicodeDecodeError:
        ours = theirs = None
    rel = _rel(root, cur)
    merged = None
    if ours is not None and theirs is not None:
        pb = read_file(pristine_path(root, rel))
        base = None
        if pb is not None and pb != theirs_b:
            try:
                base = pb.decode("utf-8")
            except UnicodeDecodeError:
                pass
        merged, _how = merge(base, ours, theirs, rel)
    if choice is None:
        out.write(_("New version of %s from an update") % shown + "\n")
        if ours is not None and theirs is not None:
            _print_diff(ours, theirs, shown + " " + _("(yours, in use)"), shown + " " + _("(new version)"), out)
        if merged is not None:
            out.write("✦ " + _("LuxOS can combine both: your settings stay, new settings and comments are added.")
                      + "\n")
    while choice is None:
        if yes:
            choice = "merge" if merged is not None else "skip"
            break
        if merged is not None:
            q = _("[m] combine (recommended)  [k] keep yours  [n] use the new version  [d] show the result  "
                  "[s] skip: ")
        else:
            q = _("[k] keep yours  [n] use the new version (yours is saved as .lux-old)  [s] skip: ")
        out.write(q)
        out.flush()
        a = (inp.readline() or "s").strip().lower()
        if a == "m" and merged is not None:
            choice = "merge"
        elif a == "k":
            choice = "keep"
        elif a == "n":
            choice = "new"
        elif a == "d" and merged is not None:
            _print_diff(ours, merged, shown + " " + _("(yours, in use)"), shown + " " + _("(combined)"), out)
        elif a in ("s", ""):
            choice = "skip"
    if choice == "merge":
        if merged is None:
            out.write("! " + _("The two versions cannot be combined automatically - choose to keep yours "
                               "or use the new version.") + "\n")
            return 1
        apply_merged(cur, new, merged.encode("utf-8"), ours_b)
        _write_pristine_from_db(root, rel, theirs_b)
        out.write("✓ " + _("Updated %s; your settings were kept") % shown + "\n")
    elif choice == "keep":
        os.unlink(new)
        _write_pristine_from_db(root, rel, theirs_b)
        out.write("✓ " + _("Kept your version of %s") % shown + "\n")
    elif choice == "new":
        if ours_b is not None:
            st = os.stat(cur)
            _atomic_write(cur + OLD_SUFFIX, ours_b, like=st)
            _atomic_write(cur, theirs_b, like=st)
            os.unlink(new)
        else:
            os.replace(new, cur)
        _write_pristine_from_db(root, rel, theirs_b)
        out.write("✓ " + _("Using the new version (yours is saved as %s)") % (shown + OLD_SUFFIX) + "\n")
    return 0


def _write_pristine_from_db(root, rel, data, dbpath=None):
    """Po rozhodnuti: nova verze z baliku je zakladem pro priste (jen kdyz sedi s databazi)."""
    entry = read_backups(dbpath or os.path.join(root, "var/lib/lux")).get(rel)
    if entry and entry[2] and md5_bytes(data) == entry[2]:
        try:
            _write_pristine(root, rel, data)
        except OSError:
            pass


# ---- prikazova radka -----------------------------------------------------------------------------
def _targets_from_stdin():
    if sys.stdin is None or sys.stdin.isatty():
        return None
    t = {ln.strip().lstrip("/") for ln in sys.stdin if ln.strip()}
    return t or None


def main(argv=None):
    p = argparse.ArgumentParser(prog="lux_configmerge.py")
    p.add_argument("cmd", choices=("pre", "post", "merge", "diff", "pending"))
    p.add_argument("file", nargs="?")
    p.add_argument("--root", default="/")
    p.add_argument("--dbpath", default=None)
    p.add_argument("--cachedir", action="append", default=None)
    p.add_argument("--quiet", action="store_true")
    p.add_argument("-y", "--yes", action="store_true")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--keep", dest="choice", action="store_const", const="keep")
    g.add_argument("--new", dest="choice", action="store_const", const="new")
    g.add_argument("--merge", dest="choice", action="store_const", const="merge")
    a = p.parse_args(argv)
    root = a.root
    dbpath = a.dbpath or os.path.join(root, "var/lib/lux")
    cachedirs = a.cachedir or [os.path.join(root, "var/cache/lux/pkg")]
    quiet = a.quiet or os.environ.get(QUIET_ENV) == "1"
    if a.cmd == "pending":
        for new, _cur in pending(root):
            print(_show(_rel(root, new)))
        return 0
    if a.cmd == "diff":
        if not a.file:
            p.error("diff needs a file")
        try:
            return config_diff(root, a.file, a.choice, a.yes)
        except PermissionError:
            sys.stderr.write("! " + _("This needs administrator rights.") + "\n")
            return 1
    try:
        if a.cmd == "pre":
            pre(root, dbpath, cachedirs, _targets_from_stdin())
            return 0
        # post (hook) / merge (lux update, LuxOS Care, lux configs)
        targets = _targets_from_stdin() if a.cmd == "post" else None
        results = merge_pending(root, dbpath)
        refresh(root, dbpath, cachedirs, targets=targets)
        write_results(root, results)
        if not quiet:
            print_messages(results)
    except Exception as e:  # noqa: BLE001 - hook nesmi rozbit transakci; soubory zustanou jak byly
        sys.stderr.write(f"lux_configmerge: {e}\n")
        return 0 if a.cmd in ("pre", "post") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
