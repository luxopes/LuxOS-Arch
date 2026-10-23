"""Lux Guard - spolecna logika: puvod souboru, kdo soubor otevira (spusteni x cteni), stav a rozhodovani.

Bez fanotify a bez GTK (testuje se bez rootu s podvrzenym /proc). Pouziva ji sluzba luxos-guard
(root), prikaz luxos-guard i sezeni uzivatele (luxos-guard-agent).

Puvod "zvenku" (jen takove soubory Lux Guard hlida):
  - slozka Stazene (XDG_DOWNLOAD_DIR i ~/Downloads), ~/Sandbox (vymena se sandboxem),
    docasne prilohy posty a prohlizece (/tmp/mozilla_*, /tmp/thunderbird*), vymenna media
    (/run/media, /media, /mnt),
  - soubor s xattr user.xdg.origin.url (prohlizece Chromium/Firefox, wget --xattr ...),
  - soubor zapsany prohlizecem, postou, stahovacim nebo chatovacim programem kdekoli v domove,
  - soubor zapsany programem, ktery sam prisel zvenku (dropper), nebo programem, ktery ma prave
    otevreny soubor zvenku (rozbalovani archivu ze Stazenych, kopirovani z USB),
  - kopie hlidaneho souboru (stejny obsah - porovna se velikost a pak SHA-256).
"""
import hashlib
import json
import os
import pwd
import re
import stat
import threading
import time

STATE_DIR = "/var/lib/luxos-guard"
DB_PATH = STATE_DIR + "/state.json"
RUN_DIR = "/run/luxos-guard"
SOCKET = RUN_DIR + "/guard.sock"
SNAP_DIR_NAME = ".luxos-guard-snapshots"
VERSION = "1.0.0"

RISKY = "risky"
CRITICAL = "critical"
FLAGGED = "flagged"         # hlidany soubor (znacka fanotify na inode)
ALLOWED = "allowed"         # uzivatel zvolil "Presto spustit" (jen rizikovy)

ASK_TIMEOUT = 90            # s - bez odpovedi uzivatele se spusteni zamitne
DENY_MEMORY = 60            # s - po "Nespoustet" se stejny soubor znovu neptá (zamita se hned)
EXEC_MEMORY = 10            # s - povolene spusteni: interpret, ktery skript hned otevre, se uz nepta
MAX_ENTRIES = 5000
MAX_LOG = 100
UID_MIN = 1000

REMOVABLE_ROOTS = ("/run/media/", "/media/", "/mnt/")
MAIL_TMP = re.compile(r"^/tmp/(?:mozilla_[^/]+|thunderbird[^/]*|evolution[^/]*|geary[^/]*)/")
# Programy, ktere zapisuji soubory z internetu nebo od jinych lidi
FETCHERS = frozenset({
    "firefox", "firefox-bin", "firefox-esr", "librewolf", "waterfox", "floorp", "zen", "tor-browser",
    "chromium", "chrome", "google-chrome", "google-chrome-stable", "brave", "brave-browser", "vivaldi-bin",
    "vivaldi", "opera", "msedge", "epiphany", "WebKitNetworkProcess", "falkon", "qutebrowser", "midori",
    "thunderbird", "thunderbird-bin", "betterbird", "evolution", "geary", "claws-mail", "mutt", "neomutt",
    "wget", "wget2", "curl", "aria2c", "axel", "yt-dlp", "uget-gtk", "persepolis",
    "transmission-gtk", "transmission-qt", "transmission-cli", "qbittorrent", "deluge", "deluge-gtk", "ktorrent",
    "fragments", "telegram-desktop", "Telegram", "discord", "Discord", "signal-desktop", "element-desktop",
    "slack", "teams", "skypeforlinux", "zoom", "whatsapp", "luxdrop", "luxdrop-receiver", "nicotine",
    "filezilla", "megasync", "warpinator", "localsend", "localsend_app", "kdeconnectd", "gsconnect",
})
# Interprety: kdyz takovy proces otevre hlidany skript, muze ho spoustet (bash skript.sh)
_INTERP_FAMILY = (
    (re.compile(r"^(?:ba|da|z|k|mk|a|fi|c|tc|rba|ya|ok|l)?sh$|^busybox$"), "sh"),     # lsh = shell LuxOS
    (re.compile(r"^(?:python|pypy)[\d.]*$"), "python"),
    (re.compile(r"^perl[\d.]*$"), "perl"),
    (re.compile(r"^ruby[\d.]*$"), "ruby"),
    (re.compile(r"^(?:node|nodejs|bun|deno)$"), "node"),
    (re.compile(r"^php[\d.]*(?:-cli)?$"), "php"),
    (re.compile(r"^lua(?:jit)?[\d.]*$"), "lua"),
    (re.compile(r"^(?:java|javaw)$"), "java"),
    (re.compile(r"^wine(?:64)?(?:-preloader)?$|^wine64-preloader$|^wine-preloader$"), "wine"),
    (re.compile(r"^(?:tclsh|wish)[\d.]*$|^g?awk$|^mawk$|^nawk$|^Rscript$|^osh$|^lsl$"), "other"),
)
# Volby interpretu, ktere nesou kod primo (bash -c ...) nebo berou hodnotu (python -W x)
_INLINE = {"sh": ("c",), "python": ("c",), "perl": ("e", "E"), "ruby": ("e",), "node": ("e", "p", "-eval", "-print"),
           "php": ("r",), "lua": ("e",), "other": ("e",)}
_WITH_VALUE = {
    "sh": {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"},
    "python": {"-W", "-X", "-Q"},
    "perl": {"-I", "-M", "-m", "-x"},
    "ruby": {"-I", "-r", "-C", "-E", "--encoding"},
    "node": {"-r", "--require", "--import", "--loader", "--experimental-loader", "-C", "--conditions"},
    "php": {"-c", "-d", "-z"},
    "java": {"-cp", "-classpath", "--class-path", "-p", "--module-path", "--add-modules", "-javaagent"},
    "lua": {"-l"},
    "other": {"-f"},
}


def now():
    return time.time()


# ---- /proc ------------------------------------------------------------------------------------
class Proc:
    """Cteni /proc/<pid>; root lze v testech podvrhnout."""

    def __init__(self, root="/proc"):
        self.root = root

    def _p(self, pid, *rest):
        return os.path.join(self.root, str(pid), *rest)

    def exe(self, pid):
        try:
            return os.readlink(self._p(pid, "exe"))
        except OSError:
            return None

    def exe_id(self, pid):
        try:
            st = os.stat(self._p(pid, "exe"))
            return (st.st_dev, st.st_ino)
        except OSError:
            return None

    def comm(self, pid):
        try:
            with open(self._p(pid, "comm")) as f:
                return f.read().strip()
        except OSError:
            return None

    def cmdline(self, pid):
        try:
            with open(self._p(pid, "cmdline"), "rb") as f:
                raw = f.read(65536)
        except OSError:
            return []
        return [a.decode("utf-8", "surrogateescape") for a in raw.split(b"\0")[:-1]] if raw else []

    def cwd(self, pid):
        try:
            return os.readlink(self._p(pid, "cwd"))
        except OSError:
            return None

    def status(self, pid):
        out = {}
        try:
            with open(self._p(pid, "status")) as f:
                for line in f:
                    k, _s, v = line.partition(":")
                    if k in ("PPid", "Uid", "Name"):
                        out[k] = v.split()
        except OSError:
            pass
        return out

    def ppid(self, pid):
        try:
            return int(self.status(pid)["PPid"][0])
        except (KeyError, IndexError, ValueError):
            return 0

    def uid(self, pid):
        """Uzivatel, za ktereho proces bezi: loginuid (i pod sudo), jinak skutecne UID."""
        try:
            with open(self._p(pid, "loginuid")) as f:
                lu = int(f.read().strip())
            if 0 < lu < 4294967295:
                return lu
        except (OSError, ValueError):
            pass
        try:
            return int(self.status(pid)["Uid"][0])
        except (KeyError, IndexError, ValueError):
            return None

    def fds(self, pid, limit=512):
        """Cesty otevrenych souboru procesu (bez socketu a rour)."""
        out = []
        d = self._p(pid, "fd")
        try:
            names = os.listdir(d)
        except OSError:
            return out
        for n in names[:limit]:
            try:
                t = os.readlink(os.path.join(d, n))
            except OSError:
                continue
            if t.startswith("/") and not t.startswith(("/dev/", "/proc/", "/memfd:")):
                out.append(t)
        return out


def exe_family(exe):
    """Cesta k programu -> rodina interpretu (sh, python, ..., java, wine), None = neni interpret."""
    if not exe:
        return None
    base = os.path.basename(exe.split(" (deleted)")[0])
    for rx, fam in _INTERP_FAMILY:
        if rx.match(base):
            return fam
    return None


def program_arg(fam, argv):
    """Z prikazove radky interpretu: (program, inline). program = skript/archiv, ktery interpret spousti
    (None = kod z -c, ze stdin nebo interaktivni), inline = kod primo v argumentu (bash -c, perl -e)."""
    args = argv[1:]
    if fam == "java":
        for i, a in enumerate(args):
            if a == "-jar" and i + 1 < len(args):
                return args[i + 1], False
        return None, False
    if fam == "wine":
        rest = [a for a in args if not a.startswith("-")]
        return (rest[0] if rest else None), False
    inline_opts = _INLINE.get(fam, ())
    with_value = _WITH_VALUE.get(fam, set())
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return (args[i + 1] if i + 1 < len(args) else None), False
        if a == "-":
            return None, False                       # kod ze stdin
        if a.startswith("--"):
            if a[1:] in inline_opts or a[2:] in ("eval", "print"):
                return None, True
            if a in with_value:
                i += 2
                continue
            i += 1
            continue
        if a.startswith("-") or (fam == "sh" and a.startswith("+")):
            if fam == "python" and a == "-m":
                return None, False                   # modul (python -m pip ...)
            flags = a[1:]
            if fam == "other" and a == "-f" and i + 1 < len(args):
                return args[i + 1], False
            if a in with_value and len(a) == 2:
                i += 2                               # volba s hodnotou v dalsim argumentu (-W x)
                continue
            if any(a[:2] == v for v in with_value if len(v) == 2):
                i += 1                               # hodnota prilepena (-Mstrict, -Ilib)
                continue
            singles = [f for f in inline_opts if len(f) == 1]
            if flags.isalpha() and (fam == "sh" and "c" in flags or flags[-1] in singles and len(flags) <= 3):
                return None, True                    # bash -c / -ec, python -c / -Bc, perl -e
            i += 1
            continue
        return a, False
    return None, False


def _resolve(path, cwd):
    if not path:
        return None
    if not path.startswith("/"):
        if not cwd:
            return None
        path = os.path.join(cwd, path)
    return path


def _same_file(path, target):
    try:
        st = os.stat(path)
    except OSError:
        return False
    return (st.st_dev, st.st_ino) == target


def is_system_file(path):
    """Program/skript patrici systemu (root, mimo zapis ostatnich, v /usr) - napr. /usr/bin/luxos-sandbox."""
    if not path or not path.startswith(("/usr/", "/opt/")):
        return False
    try:
        st = os.stat(path)
    except OSError:
        return False
    return st.st_uid == 0 and not st.st_mode & 0o022


SANDBOX_SIG = ("--unshare-all", "--die-with-parent", "--hostname", "sandbox", "--clearenv")


def in_sandbox(proc, pid, depth=32):
    """Proces bezi v LuxOS Sandboxu (predek je bwrap spusteny z luxos-sandbox)."""
    seen = 0
    while pid and pid > 1 and seen < depth:
        argv = proc.cmdline(pid)
        if argv and os.path.basename(argv[0]) == "bwrap" and tuple(argv[1:6]) == SANDBOX_SIG and "--seccomp" in argv:
            exe = proc.exe(pid) or ""
            if exe.startswith("/usr/bin/bwrap"):
                return True
        pid = proc.ppid(pid)
        seen += 1
    return False


def opener_intent(proc, pid, target, kind=None, strict=False):
    """FAN_OPEN_PERM na hlidanem souboru: 'exec' (interpret ho spousti), 'read' (jen cteni), 'sandbox'.
    strict=True (kriticky soubor): i cteni jinym skriptem se bere jako spusteni (import modulu,
    exec(open(...).read())) - povolene je jen cteni systemovym nastrojem a neinterpretem."""
    exe = proc.exe(pid)
    fam = exe_family(exe)
    if fam is None:
        return "read"
    if kind == "jar" and fam != "java" or kind == "windows" and fam != "wine":
        return "read"
    if in_sandbox(proc, pid):
        return "sandbox"
    argv = proc.cmdline(pid)
    cwd = proc.cwd(pid)
    prog, inline = program_arg(fam, argv)
    prog_path = _resolve(prog, cwd)
    if prog_path and _same_file(prog_path, target):
        return "exec"
    if prog_path and is_system_file(prog_path):
        return "read"                            # systemovy nastroj soubor jen cte (luxos-sandbox, LuxAI ...)
    for a in argv[1:]:
        p = _resolve(a, cwd)
        if p and "/" in a and _same_file(p, target):
            return "exec"                        # java -cp soubor.jar, soubor jako argument interpretu
    if prog_path and os.path.exists(prog_path) and not strict:
        return "read"                            # jiny skript, ktery soubor jen cte
    return "exec"                                # -c, stdin, interaktivni shell (source, < soubor)


# ---- puvod ------------------------------------------------------------------------------------
class Users:
    """Domovy a slozky Stazene uzivatelu (cache, obnova po minute)."""

    def __init__(self, ttl=60):
        self.ttl = ttl
        self._cache = {}
        self._homes = None
        self._homes_t = 0

    def homes(self):
        if self._homes is None or now() - self._homes_t > self.ttl:
            h = {}
            try:
                for p in pwd.getpwall():
                    if p.pw_uid >= UID_MIN and p.pw_uid < 60000 and p.pw_dir.startswith("/") and p.pw_dir != "/":
                        h[os.path.normpath(p.pw_dir)] = p.pw_uid
            except OSError:
                pass
            self._homes, self._homes_t = h, now()
        return self._homes

    def owner_of(self, path):
        """(uid, domov) uzivatele, v jehoz domove cesta lezi, jinak (None, None)."""
        for home, uid in self.homes().items():
            if path.startswith(home + "/"):
                return uid, home
        return None, None

    def download_dirs(self, home):
        c = self._cache.get(home)
        if c and now() - c[0] < self.ttl:
            return c[1]
        dirs = {home + "/Downloads"}
        try:
            with open(os.path.join(home, ".config/user-dirs.dirs"), encoding="utf-8", errors="replace") as f:
                text = f.read(8192)
            m = re.search(r'^XDG_DOWNLOAD_DIR="([^"\n]*)"', text, re.M)
            if m:
                d = m.group(1).replace("$HOME", home)
                if d.startswith("/") and os.path.normpath(d) != home:
                    dirs.add(os.path.normpath(d))
        except OSError:
            pass
        dirs = tuple(sorted(dirs))
        self._cache[home] = (now(), dirs)
        return dirs


# Casti domova, ktere se nikdy nehlidaji podle polohy (cache, profily aplikaci)
SKIP_PARTS = ("/.cache/", "/.mozilla/", "/.thunderbird/", "/.config/chromium/", "/.config/google-chrome/",
              "/.config/BraveSoftware/", "/.local/share/Trash/", "/.git/", "/node_modules/", "/.npm/",
              "/.cargo/registry/", "/.rustup/", "/.var/app/", "/" + SNAP_DIR_NAME + "/")


def location_origin(path, users):
    """Puvod podle polohy: ('download'|'removable'|'sandbox'|'mail', detail) nebo None."""
    if path.startswith(REMOVABLE_ROOTS):
        return ("removable", "/".join(path.split("/")[:5]))
    if MAIL_TMP.match(path):
        return ("mail", None)
    uid, home = users.owner_of(path)
    if home is None:
        return None
    if any(s in path for s in SKIP_PARTS):
        return None
    for d in users.download_dirs(home):
        if path.startswith(d + "/"):
            return ("download", None)
    if path.startswith(home + "/Sandbox/"):
        return ("sandbox", None)
    return None


def writer_info(proc, pid):
    """Rychly snimek procesu, ktery soubor zapsal (pro rozhodnuti o puvodu)."""
    if not pid or pid <= 0:
        return {}
    exe = proc.exe(pid)
    info = {"pid": pid, "exe": exe, "comm": proc.comm(pid), "uid": proc.uid(pid), "exe_id": proc.exe_id(pid)}
    argv = proc.cmdline(pid)
    info["argv"] = argv[:16]
    fam = exe_family(exe)
    if fam and fam not in ("java", "wine"):
        prog, _inline = program_arg(fam, argv)
        p = _resolve(prog, proc.cwd(pid))
        if p:
            try:
                st = os.stat(p)
                info["script_id"] = (st.st_dev, st.st_ino)
                info["script"] = p
            except OSError:
                pass
    info["fds"] = proc.fds(pid)
    return info


def writer_origin(info, state, users, path):
    """Puvod podle zapisujiciho procesu: ('browser', jmeno) | ('program', zdroj) | ('copy', zdroj) | None."""
    if not info:
        return None
    for name in (os.path.basename((info.get("exe") or "").split(" (deleted)")[0]), info.get("comm")):
        if name and name in FETCHERS:
            return ("browser", name)
    for key in ("exe_id", "script_id"):
        ident = info.get(key)
        if ident:
            e = state.get(tuple(ident))
            if e:
                return ("program", e.get("path"))
    for fd_path in info.get("fds") or ():
        if fd_path == path:
            continue
        if location_origin(fd_path, users) or state.by_path(fd_path):
            return ("copy", fd_path)
    return None


def sha256_fd(fd, limit=None):
    h = hashlib.sha256()
    off = 0
    while True:
        chunk = os.pread(fd, 1 << 20, off)
        if not chunk:
            break
        h.update(chunk)
        off += len(chunk)
        if limit and off >= limit:
            break
    return h.hexdigest()


# ---- stav (DB) -------------------------------------------------------------------------------------
class State:
    """Hlidane soubory a povolene obsahy. Klic v pameti = (st_dev, st_ino); na disk se uklada i cesta,
    velikost a cas zmeny, aby se znacky po restartu daly obnovit (cislo zarizeni btrfs se muze zmenit)."""

    def __init__(self, path=DB_PATH):
        self.path = path
        self.lock = threading.RLock()
        self.entries = {}       # (dev, ino) -> zaznam
        self.allowed = {}       # sha256 -> {"uid", "path", "t"}
        self.log = []           # posledni rozhodnuti (pro okno Lux Guard)
        self.dirty = False

    # --- disk
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        with self.lock:
            self.allowed = {k: v for k, v in (data.get("allowed") or {}).items() if isinstance(v, dict)}
            self.log = [x for x in (data.get("log") or []) if isinstance(x, dict)][-MAX_LOG:]
        return [e for e in (data.get("entries") or []) if isinstance(e, dict) and e.get("path")]

    def save(self):
        with self.lock:
            data = {"version": 1, "entries": list(self.entries.values()), "allowed": self.allowed, "log": self.log}
            self.dirty = False
        d = os.path.dirname(self.path)
        os.makedirs(d, mode=0o700, exist_ok=True)
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    # --- zaznamy
    def get(self, key):
        with self.lock:
            return self.entries.get(key)

    def by_path(self, path):
        with self.lock:
            for e in self.entries.values():
                if e.get("path") == path:
                    return e
        return None

    def put(self, key, entry):
        with self.lock:
            entry["dev"], entry["ino"] = key
            self.entries[key] = entry
            if len(self.entries) > MAX_ENTRIES:
                for k, _e in sorted(self.entries.items(), key=lambda kv: kv[1].get("t", 0))[:len(self.entries) - MAX_ENTRIES]:
                    self.entries.pop(k, None)
            self.dirty = True

    def remove(self, key):
        with self.lock:
            e = self.entries.pop(key, None)
            if e is not None:
                self.dirty = True
            return e

    def sizes(self):
        with self.lock:
            return {e.get("size") for e in self.entries.values()}

    def by_hash(self, sha):
        with self.lock:
            for e in self.entries.values():
                if e.get("sha256") == sha:
                    return e
        return None

    def allow_hash(self, sha, uid, path):
        if not sha:
            return
        with self.lock:
            self.allowed[sha] = {"uid": uid, "path": path, "t": int(now())}
            if len(self.allowed) > MAX_ENTRIES:
                for k, _v in sorted(self.allowed.items(), key=lambda kv: kv[1].get("t", 0))[:len(self.allowed) - MAX_ENTRIES]:
                    self.allowed.pop(k, None)
            self.dirty = True

    def is_allowed(self, sha):
        with self.lock:
            return bool(sha) and sha in self.allowed

    def add_log(self, **item):
        item.setdefault("t", int(now()))
        with self.lock:
            self.log.append(item)
            del self.log[:-MAX_LOG]
            self.dirty = True

    def for_uid(self, uid):
        with self.lock:
            items = list(self.entries.values()) if uid == 0 else [e for e in self.entries.values() if e.get("uid") == uid]
            log = list(self.log) if uid == 0 else [x for x in self.log if x.get("uid") == uid]
        return items, log


def make_entry(path, st, verdict, origin, uid, sha=None):
    level = CRITICAL if verdict.critical else RISKY
    return {"path": path, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha, "kind": verdict.kind,
            "interp": verdict.interp, "level": level, "reasons": verdict.reasons, "notes": verdict.notes,
            "origin": origin[0] if origin else None, "origin_detail": origin[1] if origin else None,
            "uid": uid, "status": FLAGGED, "t": int(now())}


def entry_matches_file(e, st):
    """Zaznam z disku patri porad stejnemu souboru (po restartu)."""
    return (stat.S_ISREG(st.st_mode) and e.get("ino") == st.st_ino and e.get("size") == st.st_size
            and e.get("mtime_ns") == st.st_mtime_ns)


# ---- rozhodnuti ------------------------------------------------------------------------------------
ALLOW = "allow"
DENY = "deny"
ASK = "ask"


def decide(entry, intent):
    """Hlidany soubor + zamer (exec/read/sandbox) -> allow | deny | ask.
    Kriticky soubor se mimo sandbox nespusti nikdy; kriticky spoustec (.desktop) se neda ani precist."""
    if intent == "sandbox":
        return ALLOW
    level = entry.get("level")
    if entry.get("kind") == "desktop" and level == CRITICAL:
        return DENY
    if intent == "read":
        return ALLOW
    if level == CRITICAL:
        return DENY
    if entry.get("status") == ALLOWED:
        return ALLOW
    return ASK


def mark_mask_for(kind):
    """Ktere udalosti fanotify hlidat na inode: (exec, open). Programy staci pri spusteni (execve),
    skripty, .jar a .exe i pri otevreni (bash skript.sh soubor jen otevre); spoustece .desktop
    take pri otevreni (kriticke se nedaji precist, takze je Soubory nespusti)."""
    if kind in ("elf", "appimage"):
        return True, False
    if kind in ("script",):
        return True, True
    if kind in ("jar", "windows", "desktop"):
        return False, True
    return True, False


def describe_origin(origin, detail):
    """Kratky anglicky popis puvodu (UI ho prelozi)."""
    return {
        "download": "downloaded from the internet",
        "browser": "downloaded from the internet",
        "mail": "an e-mail or web attachment",
        "removable": "from a USB drive or memory card",
        "sandbox": "from the sandbox shared folder",
        "copy": "a copy of a file from outside this computer",
        "program": "created by a program from outside this computer",
        "url": "downloaded from the internet",
    }.get(origin or "", "from outside this computer")
