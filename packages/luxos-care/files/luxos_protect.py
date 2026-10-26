"""LuxOS Care - ochrana systemu: systemove soubory (/usr) jen pro cteni a kontrola jejich celistvosti.

Prvni krok k "neznicitelnemu" systemu jako Signed System Volume v macOS (navrh a duvody v
/usr/share/luxos/docs/luxos/system-protection.md):

1. /usr (programy, knihovny, moduly jadra, data aplikaci - vse z baliku, /bin /lib /sbin jsou odkazy
   do /usr) je vazane pripojeni jen pro cteni. Zapisovat do nej muze jen transakce baliku (lux, LuxOS
   Care, Obchod, lux system apply): pred transakci se /usr prepoji pro zapis, po ni zase jen pro cteni.
   Zapisovatelne zustavaji /etc, /var, /home, /opt, /root, /srv a /usr/local. Ro je priznak pripojeni,
   ne souboroveho systemu (snimky, /home a ostatni subvolumy se nemeni). Pri startu ho nastavi
   luxos-protect.service (/usr/lib/luxos/care/luxos-protect-boot); kdyz cokoli selze, system nabehne
   jako dosud (zapisovatelny) - ochrana nikdy nezastavi start.
   Zapnuti: PROTECT=yes v /etc/luxos/care.conf (nova instalace), vypnuti PROTECT=no; parametr jadra
   luxos.protect=0 ji vypne pro jeden start.

2. Kontrola celistvosti (luxos-care verify): soubory baliku v /usr a /opt se porovnaji se zaznamem
   v databazi baliku (mtree v /var/lib/lux/local/*/mtree: typ, velikost, cil odkazu, SHA-256, prava).
   Konfiguracni soubory (zalohy baliku) se nekontroluji. Oprava = preinstalace dotcenych baliku
   z podepsanych repozitaru. Jednou tydne nizkou prioritou (luxos-care-verify.service), jen na
   nabijecce; upozorneni jen pri nalezu.

Zamek /run/luxos-protect/lock: kazdy, kdo prave potrebuje zapisovatelny /usr (writable()), drzi sdileny
zamek; zpet jen pro cteni se prepne az ve chvili, kdy nikdo jiny zamek nedrzi (vylucny bez cekani).
Hooky transakce (00-0-luxos-protect / zz-luxos-protect) totez pro transakce mimo lux (lux-engine).
"""
import contextlib
import fcntl
import fnmatch
import gzip
import hashlib
import json
import os
import re
import stat
import time

import luxos_care as care
from luxos_care import P

PROTECTED = "/usr"
KEEP_WRITABLE = ("/usr/local",)
LOCK = "/run/luxos-protect/lock"
BOOT_SCRIPT = "/usr/lib/luxos/care/luxos-protect-boot"
LOCAL_DB = "/var/lib/lux/local"
VERIFY_STATE = care.STATE_DIR + "/verify.json"
VERIFY_PROGRESS = care.RUN_DIR + "/verify-progress.json"
VERIFY_LOCK = care.RUN_DIR + "/verify.lock"
VERIFY_UNIT = "luxos-care-verify.service"
VERIFY_EVERY = 7 * 24 * 3600
VERIFY_SCOPE = ("usr/", "opt/")
VERIFY_IGNORE_CONF = "/etc/luxos/verify-ignore"
MAX_LISTED = 300
POWER_EVERY = 20            # s: jak casto automaticka kontrola overuje napajeni
YES = ("yes", "1", "true", "on")
NO = ("no", "0", "false", "off")
# Soubory jinych baliku, ktere LuxOS zamerne meni hookem (nejsou to cizi zmeny): branding prepisuje
# os-release baliku filesystem (10-luxos-branding.hook), relace "LuxOS" nahrazuje "Xfce Session"
# (luxos-xsession.hook smaze xfce.desktop z xfce4-session)
BUILTIN_IGNORE = ("/usr/lib/os-release", "/usr/share/xsessions/xfce.desktop")


class ProtectError(Exception):
    """Chyba s kodem pro uzivatele (code) a podrobnosti (detail)."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ---- nastaveni -----------------------------------------------------------------------------
def enabled():
    """Ochrana zapnuta (PROTECT=yes). Chybi = vypnuto: starsi instalace si ji zapnou samy
    (Aktualizace softwaru > Ochrana systemu), nove ji ma zapnutou instalator."""
    return care.config().get("PROTECT", "no").lower() in YES


def verify_enabled():
    """Tydenni kontrola (VERIFY=no ji vypne; rucni kontrola jde vzdy)."""
    return care.config().get("VERIFY", "yes").lower() not in NO


def set_conf(key, value):
    """Nastavi KEY=value v /etc/luxos/care.conf (ostatni radky zustanou)."""
    path = P(care.CONF)
    lines, found = [], False
    try:
        with open(path) as f:
            for line in f:
                if line.strip().startswith(key + "="):
                    if not found:
                        lines.append(f"{key}={value}\n")
                    found = True
                else:
                    lines.append(line)
    except OSError:
        lines = ["# LuxOS Care - carefree (automatic updates and repairs) | classic (notify only)\n"]
    if not found:
        lines.append(f"{key}={value}\n")
    care.atomic_write(path, "".join(lines), 0o644)


# ---- pripojeni /usr --------------------------------------------------------------------------
def _unescape(s):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)


def mount_entry(path=PROTECTED):
    """Posledni (nejvrchnejsi) pripojeni presne na `path` -> dict(opts, fstype) nebo None."""
    found = None
    try:
        with open(P("/proc/self/mountinfo"), encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 7 or _unescape(parts[4]) != path:
                    continue
                try:
                    sep = parts.index("-")
                except ValueError:
                    continue
                found = {"opts": parts[5].split(","), "fstype": parts[sep + 1] if len(parts) > sep + 1 else ""}
    except OSError:
        return None
    return found


def state():
    """'ro' (chraneno), 'rw' (prave probiha transakce nebo ochrana vypnuta za behu) nebo 'off'
    (/usr neni samostatne pripojeny - ochrana neni aktivni)."""
    m = mount_entry()
    if not m:
        return "off"
    return "ro" if "ro" in m["opts"] else "rw"


def _mount(*args, timeout=60):
    return care.run(["mount", *args], timeout=timeout)


def remount(readonly, attempts=5, delay=0.4):
    """Prepojeni /usr (jen priznak pripojeni, ne souboroveho systemu). Pri prepnuti zpet jen pro
    cteni muze byt /usr chvili zaneprazdneny (otevreny soubor pro zapis) - zkusi to vickrat."""
    opt = "remount,bind," + ("ro" if readonly else "rw")
    out = ""
    for i in range(attempts):
        rc, out = _mount("-o", opt, PROTECTED)
        if rc == 0:
            return True
        if not readonly or "busy" not in out.lower():
            break
        time.sleep(delay * (i + 1))
    care.log(f"remount {PROTECTED} {'ro' if readonly else 'rw'} failed: {out.strip()[-300:]}")
    return False


def setup():
    """Zapnuti ochrany hned (bez restartu) - totez, co pri startu luxos-protect-boot."""
    if state() == "off":
        rc, out = _mount("--rbind", PROTECTED, PROTECTED)
        if rc != 0:
            raise ProtectError("mount_failed", out.strip()[-300:])
    for d in KEEP_WRITABLE:
        if os.path.isdir(P(d)) and mount_entry(d) is None:
            if _mount("--bind", d, d)[0] == 0:
                _mount("-o", "remount,bind,rw", d)
    if not remount(True):
        raise ProtectError("remount_failed")
    return True


def cmdline_has(key):
    try:
        with open(P("/proc/cmdline")) as f:
            return any(t == key or t.startswith(key + "=") for t in f.read().split())
    except OSError:
        return False


def in_chroot():
    try:
        a, b = os.stat("/"), os.stat("/proc/1/root/.")
        return (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino)
    except OSError:
        return False


def _lock_fd():
    path = P(LOCK)
    os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
    return os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)


def relock(fd=None, transaction_done=False):
    """Zpet jen pro cteni, pokud ochrana plati a /usr prave nikdo nepotrebuje (zadny drzitel
    zamku, zadna transakce). -> True, kdyz je /usr ted jen pro cteni."""
    own = fd is None
    if own:
        try:
            fd = _lock_fd()
        except OSError:
            return False
    try:
        if not enabled():
            return False
        st = state()
        if st != "rw":
            return st == "ro"
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False              # jiny drzitel - prepne az on
        # Transakce mimo lux (hook ji odemkl): nechat dobehnout (hook na konci zamkne sam)
        if not transaction_done and os.path.exists(P(care.DB_LOCK)) and care.engine_running():
            return False
        return remount(True)
    finally:
        if own:
            os.close(fd)


@contextlib.contextmanager
def writable():
    """/usr zapisovatelny po dobu bloku (transakce baliku, locale-gen, dkms); pak zase jen pro cteni.
    Bez aktivni ochrany (nebo bez roota) nedela nic."""
    if (os.geteuid() != 0 and not care.ROOT) or state() == "off" or in_chroot():
        yield False
        return
    fd = _lock_fd()
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        if state() == "ro" and not remount(False):
            raise ProtectError("unlock_failed")
        yield True
    finally:
        try:
            relock(fd)
        finally:
            os.close(fd)


def hook_unlock():
    """PreTransaction hook (AbortOnFail): bez zapisovatelneho /usr by transakce skoncila v pulce."""
    if in_chroot() or state() != "ro":
        return 0
    if remount(False):
        return 0
    return 1


def hook_lock():
    """PostTransaction hook: zpet jen pro cteni (pokud /usr nedrzi lux - ten zamkne sam)."""
    if in_chroot():
        return 0
    relock(transaction_done=True)
    return 0


def apply_config():
    """Stav pripojeni podle care.conf (po zmene nastaveni): zapnout hned, vypnout hned (/usr zustane
    vazane pripojeni, ale zapisovatelne; zmizi pri pristim startu)."""
    if in_chroot() or os.path.exists(P("/run/archiso")):
        return state()
    if enabled():
        if state() != "ro":
            fd = _lock_fd()
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return state()             # probiha transakce - zamkne se po ni
                setup()
            finally:
                os.close(fd)
    elif state() == "ro":
        remount(False)
    return state()


# ---- kontrola celistvosti --------------------------------------------------------------------
def _mtree_unvis(s):
    """mtree (libarchive) koduje zvlastni znaky jako \\ooo (osmickove)."""
    if "\\" not in s:
        return s
    raw = re.sub(rb"\\([0-7]{3})", lambda m: bytes([int(m.group(1), 8)]), s.encode("utf-8", "surrogateescape"))
    return raw.decode("utf-8", "surrogateescape")


def parse_mtree(text):
    """Zaznamy mtree -> [(cesta bez ./, {klic: hodnota})] (/set a /unset se uplatni)."""
    defaults, out = {}, []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        if tokens[0] == "/set":
            for t in tokens[1:]:
                k, _s, v = t.partition("=")
                defaults[k] = v
            continue
        if tokens[0] == "/unset":
            for t in tokens[1:]:
                defaults.pop(t, None)
            continue
        attrs = dict(defaults)
        for t in tokens[1:]:
            k, _s, v = t.partition("=")
            attrs[k] = v
        path = _mtree_unvis(tokens[0])
        if path.startswith("./"):
            path = path[2:]
        if not path or path == ".":
            continue
        if "link" in attrs:
            attrs["link"] = _mtree_unvis(attrs["link"])
        out.append((path, attrs))
    return out


def read_desc(pkgdir):
    """%NAME%, %VERSION% z desc lokalni databaze."""
    out, key = {}, None
    try:
        with open(os.path.join(pkgdir, "desc"), encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.startswith("%") and line.endswith("%"):
                    key = line.strip("%")
                elif line and key and key not in out:
                    out[key] = line
                elif not line:
                    key = None
    except OSError:
        pass
    return out.get("NAME", ""), out.get("VERSION", "")


def backup_files(pkgdir):
    """Konfiguracni soubory baliku (%BACKUP% v files) - smi se menit, nekontroluji se."""
    out, inside = set(), False
    try:
        with open(os.path.join(pkgdir, "files"), encoding="utf-8", errors="surrogateescape") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.startswith("%"):
                    inside = line == "%BACKUP%"
                    continue
                if inside and line:
                    out.add(line.split("\t", 1)[0])
    except OSError:
        pass
    return out


def local_packages(names=None):
    """[(nazev, verze, adresar v databazi)] nainstalovanych baliku (serazene)."""
    base = P(LOCAL_DB)
    try:
        dirs = sorted(os.listdir(base))
    except OSError:
        return []
    out = []
    want = set(names) if names else None
    for d in dirs:
        path = os.path.join(base, d)
        if not os.path.isdir(path):
            continue
        name, ver = read_desc(path)
        if not name or (want is not None and name not in want):
            continue
        out.append((name, ver, path))
    return out


def ignore_patterns():
    pats = list(BUILTIN_IGNORE)
    try:
        with open(P(VERIFY_IGNORE_CONF)) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and line.startswith("/"):
                    pats.append(line)
    except OSError:
        pass
    return pats


def _digest(path, algo):
    with open(path, "rb") as f:
        if hasattr(hashlib, "file_digest"):
            return hashlib.file_digest(f, algo).hexdigest()
        h = hashlib.new(algo)
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


SUSPICIOUS_BITS = stat.S_ISUID | stat.S_ISGID | stat.S_IWOTH


def check_entry(rel, attrs, full=True):
    """Porovna jeden soubor se zaznamem mtree -> druh problemu nebo None
    ('missing', 'type', 'link', 'modified', 'permissions', 'unreadable')."""
    kind = attrs.get("type", "file")
    if kind == "dir":
        return None
    path = P("/" + rel)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "missing"
    except NotADirectoryError:
        return "missing"
    except OSError:
        return "unreadable"
    if kind == "link":
        if not stat.S_ISLNK(st.st_mode):
            return "type"
        try:
            return None if os.readlink(path) == attrs.get("link", "") else "link"
        except OSError:
            return "unreadable"
    if kind != "file":
        return None
    if not stat.S_ISREG(st.st_mode):
        return "type"
    try:
        if "size" in attrs and st.st_size != int(attrs["size"]):
            return "modified"
    except ValueError:
        pass
    try:
        want_mode = int(attrs.get("mode", "644"), 8)
    except ValueError:
        want_mode = 0o644
    if (st.st_mode & 0o7777) & ~want_mode & SUSPICIOUS_BITS:
        return "permissions"
    same_time = False
    try:
        same_time = int(float(attrs.get("time", "-1"))) == int(st.st_mtime)
    except ValueError:
        pass
    if not full and same_time:
        return None
    algo, want = ("sha256", attrs.get("sha256digest")) if attrs.get("sha256digest") else \
        ("md5", attrs.get("md5digest"))
    if not want:
        return None
    try:
        return None if _digest(path, algo) == want else "modified"
    except PermissionError:
        return "unreadable"
    except OSError:
        return "missing" if not os.path.lexists(path) else "unreadable"


def read_mtree(pkgdir):
    try:
        with gzip.open(os.path.join(pkgdir, "mtree"), "rt", encoding="utf-8", errors="surrogateescape") as f:
            return f.read()
    except (OSError, EOFError):
        return None


def power_ok():
    """Automaticka kontrola jen s nabijeckou (nebo bez baterie - stolni pocitac)."""
    ac, bats = care.power_supplies()
    if not bats:
        return True
    if ac is True:
        return True
    return any(st in ("Charging", "Full") for _c, st in bats)


def set_progress(done, total, name=""):
    try:
        care.write_json(VERIFY_PROGRESS, {"done": done, "total": total, "package": name, "pid": os.getpid(),
                                          "time": care.now()})
    except OSError:
        pass


def clear_progress():
    try:
        os.unlink(P(VERIFY_PROGRESS))
    except OSError:
        pass


def verify(names=None, full=True, progress=None, stop=None, scope=VERIFY_SCOPE):
    """Kontrola souboru baliku -> dict(problems [{package, path, kind}], affected, ...).
    stop(): True = prerusit (napr. odpojena nabijecka) -> result 'stopped'."""
    start = time.time()
    pkgs = local_packages(names)
    ignore = ignore_patterns()
    problems, affected = [], set()
    files = unreadable = no_mtree = 0
    stopped = False
    for i, (name, ver, pkgdir) in enumerate(pkgs):
        if stop and stop():
            stopped = True
            break
        if progress:
            progress(i, len(pkgs), name)
        text = read_mtree(pkgdir)
        if text is None:
            no_mtree += 1
            continue
        backup = backup_files(pkgdir)
        for rel, attrs in parse_mtree(text):
            if rel.startswith(".") or not rel.startswith(scope) or rel in backup:
                continue
            if attrs.get("type", "file") == "dir":
                continue
            files += 1
            kind = check_entry(rel, attrs, full=full)
            if kind is None:
                continue
            if kind == "unreadable":
                unreadable += 1
                continue
            path = "/" + rel
            if any(fnmatch.fnmatchcase(path, pat) for pat in ignore):
                continue
            problems.append({"package": name, "version": ver, "path": path, "kind": kind})
            affected.add(name)
    if progress:
        progress(len(pkgs), len(pkgs), "")
    return {"time": care.now(), "result": "stopped" if stopped else ("problems" if problems else "ok"),
            "mode": "full" if full else "quick", "packages": len(pkgs), "files": files,
            "duration": round(time.time() - start, 1), "problem_count": len(problems),
            "problems": problems[:MAX_LISTED], "affected": sorted(affected), "unreadable": unreadable,
            "no_mtree": no_mtree, "partial": bool(names)}


def load_result():
    return care.read_json(VERIFY_STATE, {})


def save_result(res):
    """Ulozi vysledek; castecna kontrola (vybrane balicky, napr. po oprave) se slouci s posledni celou."""
    if res.get("partial"):
        old = load_result()
        if old and not old.get("partial"):
            names = set(res.get("checked", []))
            keep = [p for p in old.get("problems", []) if p.get("package") not in names]
            probs = keep + res.get("problems", [])
            merged = dict(old)
            merged["problems"] = probs[:MAX_LISTED]
            merged["problem_count"] = len(probs)
            merged["affected"] = sorted({p["package"] for p in probs})
            merged["result"] = "problems" if probs else "ok"
            merged["rechecked"] = res["time"]
            res = merged
    care.write_json(VERIFY_STATE, res)
    return res


def verify_due(st=None, t=None):
    st = load_result() if st is None else st
    t = care.now() if t is None else t
    return t - int(st.get("time", 0) or 0) >= VERIFY_EVERY


def schedule_verify():
    """Z periodicke kontroly (luxos-care check): tydenni kontrola na pozadi, kdyz je cas a nabiji se."""
    if not verify_enabled() or os.path.exists(P("/run/archiso")):
        return False
    if cmdline_has("luxos.snapshot"):
        return False
    if not verify_due() or not power_ok():
        return False
    rc, _o = care.run(["systemctl", "start", "--no-block", VERIFY_UNIT], timeout=30)
    return rc == 0


def run_verify(auto=False, full=True, names=None):
    """Telo luxos-care verify (root: ulozi vysledek). auto = tydenni beh: jen kdyz je cas a nabiji se,
    pri odpojeni nabijecky se prerusi; upozorni jen pri nalezu."""
    if auto:
        if not verify_enabled():
            return {"result": "disabled"}
        if not verify_due():
            return {"result": "not_due"}
        if not power_ok():
            care.log("verify postponed: on battery")
            return {"result": "postponed"}
    last = [time.time()]

    def stop():
        if not auto or time.time() - last[0] < POWER_EVERY:
            return False
        last[0] = time.time()
        return not power_ok()

    store = os.geteuid() == 0 or bool(care.ROOT)
    prog = (lambda d, t, n: set_progress(d, t, n)) if store else None
    lockfd = None
    if store:
        # Jen jedna kontrola naraz (tydenni a "Zkontrolovat ted" se mohou potkat)
        os.makedirs(P(care.RUN_DIR), exist_ok=True)
        lockfd = os.open(P(VERIFY_LOCK), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
        try:
            fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(lockfd)
            return {"result": "busy"}
    try:
        res = verify(names=names, full=full, progress=prog, stop=stop)
    finally:
        if store:
            clear_progress()
            os.close(lockfd)
    if names:
        res["checked"] = sorted(names)
    if res["result"] == "stopped":
        care.log("verify stopped: on battery")
        return res
    if store:
        res = save_result(res)
        if res["result"] == "problems":
            care.history("verify", ok=False, count=res["problem_count"], packages=res["affected"][:20])
            if auto:
                care.add_event("integrity", count=res["problem_count"], packages=res["affected"][:10])
    return res


def foreign_packages(names):
    """Balicky, ktere nejsou v repozitarich (nelze je preinstalovat z podepsaneho zdroje)."""
    rc, out = care.run([care.ENGINE, "-Qmq"], timeout=120)
    if rc not in (0, 1):
        return []
    foreign = set(out.split())
    return sorted(n for n in names if n in foreign)


def repair(names, out=None):
    """Preinstalace dotcenych baliku z podepsanych repozitaru (jinak z mezipameti) a nova kontrola
    jen techto baliku. -> dict(repaired, failed, foreign, result)."""
    names = sorted(set(n for n in names if care.PKG_RE.match(n)))
    if not names:
        return {"result": "nothing", "repaired": [], "failed": [], "foreign": []}
    foreign = foreign_packages(names)
    todo = [n for n in names if n not in foreign]
    failed = []
    if todo:
        if out:
            out(" ".join(todo))
        with writable():
            ok = _reinstall(todo)
            if not ok and len(todo) > 1:
                # jeden vadny balik (napr. uz neni v repozitari ani v mezipameti) nesmi zastavit ostatni
                failed = [n for n in todo if not _reinstall([n])]
            elif not ok:
                failed = list(todo)
    res = run_verify(names=names)
    still = set(res.get("affected", [])) & set(names) if res.get("result") != "stopped" else set(names)
    repaired = [n for n in todo if n not in failed and n not in still]
    care.history("verify_repair", ok=not failed and not (still - set(foreign)), repaired=repaired,
                 failed=sorted(set(failed) | (still - set(foreign))), foreign=foreign)
    return {"result": "ok" if not (still - set(foreign)) and not failed else "failed", "repaired": repaired,
            "failed": sorted(set(failed) | (still - set(foreign) - set(failed))), "foreign": foreign,
            "verify": res}


def _reinstall(names):
    if care.lux_available():
        cmd = [care.LUX_ALPM, "--machine", "-y", "--color=never", "reinstall", "--"] + names
    else:
        cmd = [care.ENGINE, "-S", "--noconfirm", "--noprogressbar", "--color", "never"] + names
    rc, out = care.run(cmd, timeout=3600)
    if rc != 0:
        care.log(f"reinstall {' '.join(names)} failed: {out.strip()[-500:]}")
    return rc == 0


def status():
    """Pro aplikaci a `luxos-care protect status` (bez roota)."""
    st = load_result()
    return {"enabled": enabled(), "state": state(), "verify_enabled": verify_enabled(),
            "verified": int(st.get("time", 0) or 0), "result": st.get("result", ""),
            "problem_count": int(st.get("problem_count", 0) or 0), "affected": st.get("affected", []),
            "mode": st.get("mode", "")}
