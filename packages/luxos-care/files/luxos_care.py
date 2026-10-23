"""LuxOS Care - system bez udrzby: automaticke aktualizace, zalozni jadro a samooprava.

Rezim je v /etc/luxos/care.conf (MODE=carefree|classic, chybi = carefree):

  carefree  aktualizace se instaluji samy (ne na merenem pripojeni, ne na baterii pod 40 %),
            zname problemy se opravi pravidly, nezname vybere LuxAI Flash z bezpecneho katalogu
  classic   jen kontrola a upozorneni ("N aktualizaci k dispozici", nalezene problemy)

Stav pro aplikaci a relaci (vse citelne pro uzivatele, nic tajneho):
  /var/lib/luxos-care/state.json     posledni aktualizace, cekajici aktualizace, problemy
  /var/lib/luxos-care/events.json    posledni udalosti pro upozorneni (luxos-hub)
  /var/lib/luxos-care/history.jsonl  auditni zaznam (aktualizace, opravy, rozhodnuti AI)
  /run/luxos-care/progress.json      prubeh prave bezici aktualizace

LUXOS_CARE_ROOT predradi vsem cestam jiny koren (testy).
"""
import fcntl
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.environ.get("LUXOS_CARE_ROOT", "").rstrip("/")


def P(path):
    """Cesta v (pripadne testovacim) koreni."""
    return ROOT + path


CONF = "/etc/luxos/care.conf"
ESP_CONF = "/etc/luxos/esp.conf"
STATE_DIR = "/var/lib/luxos-care"
RUN_DIR = "/run/luxos-care"
STATE = STATE_DIR + "/state.json"
EVENTS = STATE_DIR + "/events.json"
HISTORY = STATE_DIR + "/history.jsonl"
PROGRESS = RUN_DIR + "/progress.json"
LOCK = RUN_DIR + "/lock"
KSTATE = STATE_DIR + "/kernel"
STAGING = KSTATE + "/staging"
MODULES = "/usr/lib/modules"
DB_LOCK = "/var/lib/lux/db.lck"
ENGINE_LOG = "/var/log/lux.log"
PKG_CACHE = "/var/cache/lux/pkg"
# Nastroje jadra lux (lux-engine, lux-engine-key, lux-engine-conf) jsou mimo PATH. Spoustene prikazy
# (lux, lux-engine) i hooky transakci je dostanou v PATH (engine_env); proces sam PATH nemeni (modul
# nacita i aplikace v relaci uzivatele). Konfiguraci jadra (/run/lux/engine.conf) zajisti nastroje samy.
ENGINE_BIN = "/usr/lib/lux/alpm/bin"
ENGINE = ENGINE_BIN + "/lux-engine"


def engine_env(**extra):
    """Prostredi pro spoustene prikazy: PATH s nastroji jadra na zacatku (bez duplicit)."""
    path = [p for p in os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/bin").split(":")
            if p and p != ENGINE_BIN]
    return dict(os.environ, PATH=":".join([ENGINE_BIN] + path), **extra)
GRUBENV = "/boot/grub/grubenv"
GRUB_PREV_DIR = "/boot/luxos-prev"

MODES = ("carefree", "classic")
BATTERY_MIN = 40            # % - pod touto hranici bez nabijeni se neaktualizuje
UPDATE_EVERY = 20 * 3600    # automaticka aktualizace nejvys jednou za den
CHECK_EVERY = 20 * 3600     # klasicky rezim: kontrola aktualizaci jednou za den
BACKOFF_BASE = 3600
BACKOFF_MAX = 24 * 3600
AI_ACTIONS_PER_DAY = 3
NOTIFY_FAIL_AFTER = 3       # upozornit az po N neuspesnych pokusech za sebou


def log(msg):
    print(f"luxos-care: {msg}", file=sys.stderr, flush=True)


def now():
    return int(time.time())


# ---- konfigurace -------------------------------------------------------------------------
def read_kv(path):
    d = {}
    try:
        with open(P(path)) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return d


def config():
    c = read_kv(CONF)
    if c.get("MODE") not in MODES:
        c["MODE"] = "carefree"
    c.setdefault("KERNEL", read_kv(ESP_CONF).get("KERNEL") or "linux-zen")
    return c


def mode():
    return config()["MODE"]


def set_mode(m):
    if m not in MODES:
        raise ValueError(m)
    path = P(CONF)
    lines, found = [], False
    try:
        with open(path) as f:
            for line in f:
                if line.strip().startswith("MODE="):
                    if not found:
                        lines.append(f"MODE={m}\n")
                    found = True
                else:
                    lines.append(line)
    except OSError:
        lines = ["# LuxOS Care - carefree (automatic updates and repairs) | classic (notify only)\n"]
    if not found:
        lines.append(f"MODE={m}\n")
    atomic_write(path, "".join(lines), 0o644)


# ---- soubory stavu -----------------------------------------------------------------------
def atomic_write(path, text, mode_bits=0o644):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode_bits)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path, default):
    try:
        with open(P(path)) as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def write_json(path, data):
    atomic_write(P(path), json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def load_state():
    return read_json(STATE, {})


def save_state(st):
    write_json(STATE, st)


def update_state(**kw):
    st = load_state()
    st.update(kw)
    save_state(st)
    return st


def add_event(kind, **data):
    """Udalost pro upozorneni v relaci; luxos-hub si pamatuje posledni videne seq."""
    ev = read_json(EVENTS, {"seq": 0, "events": []})
    ev["seq"] = int(ev.get("seq", 0)) + 1
    item = {"seq": ev["seq"], "time": now(), "kind": kind}
    item.update(data)
    ev["events"] = (ev.get("events") or [])[-49:] + [item]
    write_json(EVENTS, ev)
    return item


def history(kind, **data):
    """Auditni zaznam (jeden JSON na radek), drzi se poslednich 1000 zaznamu."""
    item = {"time": now(), "kind": kind}
    item.update(data)
    path = P(HISTORY)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    try:
        if os.path.getsize(path) > 512 * 1024:
            with open(path) as f:
                lines = f.readlines()[-1000:]
            atomic_write(path, "".join(lines))
    except OSError:
        pass
    log(f"{kind}: {json.dumps(data, ensure_ascii=False)}")
    return item


def read_history(limit=200):
    out = []
    try:
        with open(P(HISTORY)) as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out[-limit:]


def set_progress(phase, fraction, text="", **extra):
    data = {"phase": phase, "fraction": round(max(0.0, min(1.0, fraction)), 3), "text": text,
            "pid": os.getpid(), "time": now()}
    data.update(extra)
    try:
        write_json(PROGRESS, data)
    except OSError:
        pass


def clear_progress():
    try:
        os.unlink(P(PROGRESS))
    except OSError:
        pass


class CareLock:
    """Jen jedna operace LuxOS Care najednou (aktualizace, kontrola, oprava)."""

    def __init__(self, wait=False):
        self.wait = wait
        self.fd = None

    def __enter__(self):
        os.makedirs(P(RUN_DIR), exist_ok=True)
        self.fd = os.open(P(LOCK), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | (0 if self.wait else fcntl.LOCK_NB))
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            raise
        return self

    def __exit__(self, *_a):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)


# ---- spousteni prikazu -------------------------------------------------------------------
def run(cmd, timeout=600, input=None, env=None):
    """(navratovy kod, vystup stdout+stderr). Nikdy nevyhazuje vyjimku."""
    e = engine_env(LC_ALL="C", LANG="C")
    if env:
        e.update(env)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input, env=e)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except OSError as ex:
        return 127, str(ex)


def have(cmd):
    return shutil.which(cmd) is not None


# ---- podminky pro automatickou aktualizaci -----------------------------------------------
def power_supplies(base="/sys/class/power_supply"):
    """(ac_online: True/False/None, [(kapacita %, status)]) ze sysfs."""
    ac, bats = None, []
    try:
        names = sorted(os.listdir(P(base)))
    except OSError:
        return None, []
    for n in names:
        d = os.path.join(P(base), n)

        def rd(f, d=d):
            try:
                with open(os.path.join(d, f)) as fh:
                    return fh.read().strip()
            except OSError:
                return ""
        typ = rd("type")
        if typ == "Mains" or (typ in ("USB", "USB_C", "USB_PD") and rd("online")):
            if rd("online") == "1":
                ac = True
            elif ac is None:
                ac = False
        elif typ == "Battery" and rd("scope") != "Device":     # baterie mysi apod. nepocitat
            cap = rd("capacity")
            if cap.isdigit():
                bats.append((int(cap), rd("status")))
    return ac, bats


def battery_ok(ac_online, batteries, minimum=BATTERY_MIN):
    """Smi se aktualizovat z hlediska napajeni? -> (ok, duvod)."""
    if not batteries:
        return True, ""                       # stolni pocitac
    if ac_online:
        return True, ""
    if any(st in ("Charging", "Full") for _c, st in batteries) and ac_online is not False:
        return True, ""
    level = sum(c for c, _s in batteries) / len(batteries)
    if level >= minimum:
        return True, ""
    return False, "battery"


# NM: NMMetered 0 unknown, 1 yes, 2 no, 3 guess-yes, 4 guess-no
def metered_value(text):
    """Hodnota z `busctl get-property ... Metered` ("u 1") nebo `nmcli -g GENERAL.METERED` ("yes (guessed)")."""
    t = (text or "").strip().lower()
    m = re.match(r"^u\s+(\d+)$", t)
    if m:
        return {"1": "yes", "3": "yes", "2": "no", "4": "no"}.get(m.group(1), "unknown")
    if t.startswith("yes"):
        return "yes"
    if t.startswith("no"):
        return "no"
    return "unknown"


def nm_metered():
    """'yes' kdyz je primarni pripojeni merene (Sporic dat nebo sdileni z telefonu)."""
    if have("busctl"):
        rc, out = run(["busctl", "get-property", "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager",
                       "org.freedesktop.NetworkManager", "Metered"], timeout=10)
        if rc == 0:
            v = metered_value(out)
            if v != "unknown":
                return v
    if have("nmcli"):
        rc, out = run(["nmcli", "-t", "-f", "DEVICE,STATE", "device"], timeout=10)
        vals = []
        for line in out.splitlines() if rc == 0 else []:
            dev, _s, st = line.partition(":")
            if st == "connected" and dev != "lo":
                rc2, m = run(["nmcli", "-g", "GENERAL.METERED", "device", "show", dev], timeout=10)
                if rc2 == 0:
                    vals.append(metered_value(m))
        if "yes" in vals:
            return "yes"
        if vals:
            return "no"
    return "unknown"


def nm_connectivity():
    """full | limited | portal | none | unknown (bez NetworkManageru: zkusi DNS)."""
    if have("nmcli"):
        rc, out = run(["nmcli", "-g", "CONNECTIVITY", "general"], timeout=15)
        if rc == 0 and out.strip():
            return out.strip().splitlines()[0]
    try:
        socket.setdefaulttimeout(5)
        socket.getaddrinfo("geo.mirror.pkgbuild.com", 443)
        return "full"
    except OSError:
        return "none"
    finally:
        socket.setdefaulttimeout(None)


def conditions_ok(env, manual=False):
    """Rozhodnuti, zda ted aktualizovat. env: metered, connectivity, ac, batteries. -> (ok, duvod)."""
    conn = env.get("connectivity", "unknown")
    if conn in ("none", "portal", "limited"):
        return False, "offline"
    if manual:
        return True, ""                       # rucni "Aktualizovat" - uzivatel rozhodl sam
    if env.get("metered") == "yes":
        return False, "metered"
    ok, why = battery_ok(env.get("ac"), env.get("batteries") or [])
    if not ok:
        return False, why
    # Sporic baterie (luxos-powersaver): automaticky jen s nabijeckou
    bats = env.get("batteries") or []
    if env.get("powersaver") and bats and env.get("ac") is not True and \
            not any(st in ("Charging", "Full") for _c, st in bats):
        return False, "battery"
    return True, ""


def current_env():
    ac, bats = power_supplies()
    return {"metered": nm_metered(), "connectivity": nm_connectivity(), "ac": ac, "batteries": bats,
            "powersaver": os.path.exists(P("/run/luxos/powersaver"))}


def backoff(failures):
    """Pauza po N neuspesnych pokusech za sebou: 1 h, 2 h, 4 h ... max 24 h."""
    if failures <= 0:
        return 0
    return min(BACKOFF_MAX, BACKOFF_BASE * (2 ** (failures - 1)))


def update_due(st, t=None, every=UPDATE_EVERY):
    """Je cas na automatickou aktualizaci? (posledni uspech + odklad po chybach)."""
    t = now() if t is None else t
    nxt = int(st.get("next_attempt", 0) or 0)
    if t < nxt:
        return False
    last = int(st.get("last_success", 0) or 0)
    return t - last >= every


# ---- spravce baliku: blokovani a aktualizace ---------------------------------------------------
PKG_MANAGERS = {"lux-engine", "lux-engine-key", "pacman", "yay", "paru", "pamac", "pacman-key", "makepkg",
                "pacstrap", "lux_alpm.py"}

# Transakce dela lux (libalpm: stejna databaze, podpisy a hooky jako jadro) ve strojovem rezimu;
# jeho vystup obsahuje i radky ve stylu jadra ("upgrading x...", "error: ...", "x: /f exists in
# filesystem"), takze prubeh i rozpoznani chyb zustavaji stejne. Bez lux/pyalpm se pouzije lux-engine.
LUX_ALPM = os.environ.get("LUXOS_CARE_LUX_ALPM", "/usr/lib/lux/lux_alpm.py")
_lux_ok = None


def lux_available():
    global _lux_ok
    if _lux_ok is None:
        _lux_ok = os.access(LUX_ALPM, os.X_OK) and run([LUX_ALPM, "available"], timeout=120)[0] == 0
    return _lux_ok


def lux_command(args):
    """Argumenty jadra, ktere LuxOS Care pouziva -> prikaz lux; None = jen lux-engine."""
    a = [x for x in args if x not in ("--noconfirm", "--noprogressbar")]
    base = [LUX_ALPM, "--machine", "-y", "--color=never"]
    if not a:
        return None
    op, rest = a[0], a[1:]
    if op == "-Syuw" and not rest:
        return base + ["upgrade", "--refresh", "--download-only"]
    if op == "-Su" and not rest:
        return base + ["upgrade"]
    if op == "-Syu" and not rest:
        return base + ["upgrade", "--refresh"]
    if op in ("-S", "-Sy") and rest:
        names = [x for x in rest if x != "--needed"]
        if names and all(PKG_RE.match(n) for n in names):
            return base + ["install"] + (["--refresh"] if op == "-Sy" else []) + \
                (["--needed"] if "--needed" in rest else []) + ["--"] + names
    if op == "-U" and len(rest) == 1 and rest[0].startswith("/"):
        return base + ["install", "--", rest[0]]
    return None


def pm(args):
    """Prikaz pro transakci: lux, kdyz je k dispozici, jinak lux-engine (bez otazek a progress baru)."""
    cmd = lux_command(args) if lux_available() else None
    return cmd or [ENGINE, "--noconfirm", "--noprogressbar", "--color", "never"] + \
        [x for x in args if x not in ("--noconfirm", "--noprogressbar")]


def engine_running():
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            with open(f"/proc/{pid}/comm") as f:
                if f.read().strip() in PKG_MANAGERS:
                    return True
        except OSError:
            pass
    return False


def stale_lock(lock_exists, manager_running, lock_age, min_age=120):
    """db.lck je opusteny (zadny spravce baliku nebezi a zamek neni cerstvy)."""
    return bool(lock_exists) and not manager_running and lock_age >= min_age


def remove_stale_lock():
    path = P(DB_LOCK)
    try:
        age = time.time() - os.stat(path).st_mtime
    except OSError:
        return False
    if stale_lock(True, engine_running(), age):
        os.unlink(path)
        return True
    return False


def check_updates_db():
    """Docasna databaze lux_alpm.py check-updates (stejna cesta jako check_updates_db v lux_alpm)."""
    return os.path.join(os.environ.get("TMPDIR") or "/tmp", f"lux-checkupdates-{os.getuid()}")


def check_updates_engine():
    """Zaloha bez pyalpm: totez nastrojem jadra (docasna kopie databaze, systemova se nemeni)."""
    db = check_updates_db()
    try:
        os.makedirs(os.path.join(db, "sync"), mode=0o700, exist_ok=True)
        if not os.path.lexists(os.path.join(db, "local")):
            os.symlink("/var/lib/lux/local", os.path.join(db, "local"))
        for f in os.listdir("/var/lib/lux/sync"):
            src = os.path.join("/var/lib/lux/sync", f)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(db, "sync", f))
    except OSError as e:
        return 1, str(e)
    rc, out = run([ENGINE, "-Sy", "--dbpath", db, "--logfile", "/dev/null", "--disable-sandbox"], timeout=600)
    if rc != 0:
        return 1, out
    rc, out = run([ENGINE, "-Qu", "--dbpath", db], timeout=120)
    return (0 if out.strip() else 2), out


def check_updates():
    """Seznam cekajicich aktualizaci [(nazev, stara, nova)] bez zasahu do systemove databaze
    (lux check-updates synchronizuje do docasne kopie). None = nepodarilo se zjistit."""
    if not os.access(LUX_ALPM, os.X_OK):
        return None
    rc, out = run([LUX_ALPM, "--color=never", "check-updates", "--db", check_updates_db()], timeout=600)
    if rc == 3:
        rc, out = check_updates_engine()
    if rc not in (0, 2):          # 2 = zadne aktualizace
        return None
    res = []
    for line in out.splitlines():
        m = re.match(r"^(\S+)\s+(\S+)\s+->\s+(\S+)$", line.strip())
        if m:
            res.append(m.groups())
    return res


ENGINE_ERRORS = [
    ("unable to lock database", "locked"),
    ("could not lock database", "locked"),
    ("signature from", "keyring"),
    ("invalid or corrupted package (PGP signature)", "keyring"),
    ("unknown trust", "keyring"),
    ("required key missing from keyring", "keyring"),
    ("not enough free disk space", "disk"),
    ("No space left on device", "disk"),
    ("conflicting files", "conflict"),
    ("are in conflict", "conflict"),
    ("could not satisfy dependencies", "deps"),
    ("unable to satisfy dependency", "deps"),
    ("failed retrieving file", "network"),
    ("failed to synchronize all databases", "network"),
    ("Could not resolve host", "network"),
    ("download library error", "network"),
]


def classify_engine_error(output):
    for needle, kind in ENGINE_ERRORS:
        if needle.lower() in (output or "").lower():
            return kind
    return "unknown"


class Updater:
    """Aktualizace systemu: klice -> stazeni (-Syuw) -> instalace z cache (-Su). Bez castecnych aktualizaci."""

    def __init__(self, manual=False):
        self.manual = manual
        self.proc = None
        self.stopping = False
        self.output = []

    def stop(self, *_a):
        """SIGTERM (vypnuti): stahovani se prerusi, instalace se nechá dobehnout."""
        self.stopping = True
        p = self.proc
        if p is not None and getattr(p, "luxos_phase", "") == "download" and p.poll() is None:
            p.send_signal(signal.SIGINT)

    def transact(self, args, phase, total=0, sizes=None, base=0.0, span=1.0, timeout=7200):
        """Spusti transakci (lux, jinak lux-engine) a z vystupu pocita prubeh. Vraci (rc, vystup)."""
        cmd = pm(args)
        if have("systemd-inhibit") and os.path.exists("/run/systemd/system") and phase == "install":
            cmd = ["systemd-inhibit", "--what=shutdown:sleep:handle-lid-switch", "--who=LuxOS",
                   "--why=Installing updates", "--mode=block"] + cmd
        env = engine_env(LC_ALL="C", LANG="C")
        out, done = [], [0]
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                         env=env, stdin=subprocess.DEVNULL)
        except OSError as e:
            return 127, str(e)
        self.proc.luxos_phase = phase
        stop_poll = threading.Event()
        if phase == "download" and sizes:
            threading.Thread(target=self._poll_download, args=(sizes, base, span, stop_poll), daemon=True).start()
        start = time.time()
        for line in self.proc.stdout:
            out.append(line)
            if phase == "install" and line.startswith(":: Running post-transaction hooks"):
                set_progress("install", base + span, "hooks")
            elif phase == "install" and total:
                if re.match(r"^(installing|upgrading|reinstalling|downgrading|removing) \S+\.\.\.", line):
                    done[0] += 1
                    name = line.split()[1].rstrip(".")
                    set_progress("install", base + span * min(1.0, done[0] / total), name,
                                 done=done[0], total=total)
            if time.time() - start > timeout:
                self.proc.kill()
        rc = self.proc.wait()
        stop_poll.set()
        self.proc = None
        text = "".join(out)
        self.output.append(text[-20000:])
        return rc, text

    def _poll_download(self, sizes, base, span, stop):
        total = sum(sizes.values()) or 1
        while not stop.wait(0.7):
            got = 0
            for root, _d, files in os.walk(PKG_CACHE):
                if root.count(os.sep) - PKG_CACHE.count(os.sep) > 1:
                    continue
                for fn in files:
                    name = fn[:-5] if fn.endswith(".part") else fn
                    if name in sizes:
                        try:
                            got += min(os.path.getsize(os.path.join(root, fn)), sizes[name])
                        except OSError:
                            pass
            set_progress("download", base + span * min(1.0, got / total), "", bytes=got, total_bytes=total)

    def download_plan(self):
        """{nazev souboru: velikost} pro balicky, ktere jeste nejsou v cache."""
        rc, out = run([ENGINE, "-Sup", "--print-format", "%l %s"], timeout=120)
        sizes = {}
        if rc != 0:
            return sizes
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and "://" in parts[0] and parts[1].isdigit():
                fn = parts[0].rsplit("/", 1)[-1]
                if not os.path.exists(os.path.join(PKG_CACHE, fn)):
                    sizes[fn] = int(parts[1])
        return sizes

    def run_update(self):
        """-> dict(result=ok|nothing|failed|stopped, error, packages, kernel)"""
        set_progress("check", 0.02, "")
        if engine_running():
            return {"result": "busy"}              # uzivatel prave pracuje s balicky - pozdeji
        if os.path.exists(P(DB_LOCK)):
            if not remove_stale_lock():
                return {"result": "failed", "error": "locked"}
            history("repair", action="remove_db_lock", source="rule", ok=True, title="Removed a stale package manager lock")
        pending = check_updates()
        if pending is None:
            return {"result": "failed", "error": "network"}
        if not pending:
            return {"result": "nothing", "packages": []}
        names = [p[0] for p in pending]
        set_progress("check", 0.05, "", total=len(names))

        # 1. Nejdriv klice (doporucena vyjimka z pravidla "zadne castecne aktualizace")
        keyrings = [k for k in ("archlinux-keyring", "luxos-keyring") if k in names]
        if keyrings and not self.stopping:
            set_progress("keyring", 0.06, " ".join(keyrings))
            rc, out = self.retry(lambda: self.transact(["-Sy", "--needed"] + keyrings, "keyring"))
            if rc != 0:
                return {"result": "failed", "error": classify_engine_error(out), "packages": names}

        # 2. Stazeni vseho (synchronizace databaze + -w); preruseni je bezpecne
        if self.stopping:
            return {"result": "stopped"}
        sizes = self.download_plan_after_sync()
        rc, out = self.retry(lambda: self.transact(["-Syuw"], "download", sizes=sizes, base=0.08, span=0.52))
        if self.stopping:
            return {"result": "stopped"}
        if rc != 0:
            return {"result": "failed", "error": classify_engine_error(out), "packages": names}

        # 3. Instalace z cache (bez site, nepreruzi se vypnutim - viz TimeoutStopSec)
        rc, out = run([ENGINE, "-Qu"], timeout=60)
        total = len([x for x in out.splitlines() if x.strip()]) if rc == 0 else len(names)
        kernel_before = installed_version(config()["KERNEL"])
        rc, out = self.transact(["-Su"], "install", total=max(total, 1), base=0.6, span=0.37)
        if rc != 0 and release_kept_conflicts(out):
            rc, out = self.transact(["-Su"], "install", total=max(total, 1), base=0.6, span=0.37)
        if rc != 0:
            return {"result": "failed", "error": classify_engine_error(out), "packages": names}
        kernel_after = installed_version(config()["KERNEL"])
        set_progress("cleanup", 0.98, "")
        clean_cache()
        return {"result": "ok", "packages": names, "kernel": kernel_before != kernel_after,
                "kernel_version": kernel_after}

    def download_plan_after_sync(self):
        # Velikosti stahovani zname az po synchronizaci; -Sup s docasnou databazi z check-updates
        dbpath = check_updates_db()
        if os.path.isdir(dbpath):
            rc, out = run([ENGINE, "-Sup", "--dbpath", dbpath, "--logfile", "/dev/null",
                           "--print-format", "%l %s"], timeout=120)
            sizes = {}
            if rc == 0:
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) == 2 and "://" in parts[0] and parts[1].isdigit():
                        fn = parts[0].rsplit("/", 1)[-1]
                        if not os.path.exists(os.path.join(PKG_CACHE, fn)):
                            sizes[fn] = int(parts[1])
                return sizes
        return self.download_plan()

    def retry(self, fn, attempts=3, delays=(20, 90)):
        """Opakovani pri chybach site (kratke, v ramci jednoho behu); jine chyby hned vraci."""
        rc, out = 1, ""
        for i in range(attempts):
            rc, out = fn()
            if rc == 0 or self.stopping or classify_engine_error(out) != "network":
                return rc, out
            if i < attempts - 1:
                time.sleep(delays[min(i, len(delays) - 1)])
        return rc, out


def installed_version(pkg):
    rc, out = run([ENGINE, "-Q", pkg], timeout=30)
    return out.split()[1] if rc == 0 and len(out.split()) >= 2 else ""


def clean_cache(keep=2):
    """Cache balicku: posledni verze instalovanych (oprava z cache), odinstalovane pryc."""
    if os.access(LUX_ALPM, os.X_OK):
        run([LUX_ALPM, "--machine", "--color=never", "clean", "--keep", str(keep), "--keep-uninstalled", "0"],
            timeout=300)


def find_pacnew():
    res = []
    for root, dirs, files in os.walk(P("/etc")):
        dirs[:] = [d for d in dirs if d not in ("ssl", "ca-certificates")]
        res += [os.path.join(root, f)[len(ROOT):] for f in files if f.endswith((".pacnew", ".pacsave"))]
    return sorted(res)


def running_kernel():
    return os.uname().release


def needs_reboot():
    """Bezi jine jadro, nez je nainstalovane (aktualizace jadra ceka na restart). Pri startu se
    zaloznim jadrem po vadnem novem restart nepomuze - to resi samooprava, ne upozorneni."""
    if not installed_kernels():
        return False
    if running_kernel() in installed_kernels():
        return False
    return not (is_prev_running() and main_entry_bad())


# ---- automaticka aktualizace (sluzba) ----------------------------------------------------
def do_update(manual=False):
    """Telo luxos-care-update.service. carefree: aktualizace; classic: jen kontrola."""
    st = load_state()
    m = mode()
    if not manual and m == "classic":
        return do_check_updates(st)
    if not manual and not update_due(st):
        log("update not due")
        return 0
    env = current_env()
    ok, why = conditions_ok(env, manual=manual)
    if not ok:
        log(f"update skipped: {why}")
        update_state(last_skip=now(), last_skip_reason=why)
        if manual:
            add_event("update_skipped", reason=why)
        return 0
    try:
        lock = CareLock()
        lock.__enter__()
    except BlockingIOError:
        log("another LuxOS Care operation is running")
        return 0
    up = Updater(manual=manual)
    signal.signal(signal.SIGTERM, up.stop)
    try:
        update_state(updating=True, update_started=now())
        res = up.run_update()
    except Exception as e:  # noqa: BLE001 - stav se musi zapsat vzdy
        res = {"result": "failed", "error": f"internal: {e}"}
    finally:
        clear_progress()
        lock.__exit__()
    st = load_state()
    st["updating"] = False
    st["last_attempt"] = now()
    st["pacnew"] = find_pacnew()
    r = res.get("result")
    if r in ("ok", "nothing"):
        st.update(last_success=now(), failures=0, next_attempt=0, pending=[], last_error="")
        if r == "ok":
            st["last_update"] = now()
            st["last_update_packages"] = res.get("packages", [])
            st["needs_reboot"] = bool(res.get("kernel")) or needs_reboot()
            history("update", ok=True, packages=res.get("packages", []), count=len(res.get("packages", [])),
                    kernel=bool(res.get("kernel")), manual=manual)
            add_event("updated", count=len(res.get("packages", [])), reboot=st["needs_reboot"])
        save_state(st)
        if r == "ok":
            safe_check(after_update=True)
        return 0
    if r in ("stopped", "busy"):
        save_state(st)
        return 0
    st["failures"] = int(st.get("failures", 0)) + 1
    st["next_attempt"] = now() + backoff(st["failures"])
    st["last_error"] = res.get("error", "unknown")
    st["last_error_output"] = redact("\n".join(up.output)[-3000:])
    save_state(st)
    history("update", ok=False, error=st["last_error"], failures=st["failures"], manual=manual)
    if manual or st["failures"] >= NOTIFY_FAIL_AFTER:
        add_event("update_failed", error=st["last_error"])
    safe_check(after_update=True)
    return 1


def do_check_updates(st=None, force=False):
    """Klasicky rezim (a tlacitko Zkontrolovat): seznam aktualizaci, upozorneni pri zmene."""
    st = st or load_state()
    if not force and now() - int(st.get("last_check_updates", 0) or 0) < CHECK_EVERY:
        return 0
    env = current_env()
    ok, why = conditions_ok(env, manual=force)
    if not ok:
        log(f"check skipped: {why}")
        return 0
    pending = check_updates()
    if pending is None:
        return 1
    st = load_state()
    old = {p[0] for p in st.get("pending", [])}
    st["pending"] = [list(p) for p in pending]
    st["last_check_updates"] = now()
    st["pacnew"] = find_pacnew()
    save_state(st)
    if pending and ({p[0] for p in pending} - old) and mode() == "classic":
        add_event("updates_available", count=len(pending))
    return 0


# ---- zalozni jadro -----------------------------------------------------------------------
def kread(name, default=""):
    try:
        with open(P(f"{KSTATE}/{name}")) as f:
            return f.read().strip()
    except OSError:
        return default


def kwrite(name, value):
    atomic_write(P(f"{KSTATE}/{name}"), value + "\n")


def kept_list():
    return [v for v in kread("kept").split() if v]


def pkgbase(ver):
    try:
        with open(P(f"{MODULES}/{ver}/pkgbase")) as f:
            return f.read().strip()
    except OSError:
        return ""


def owned_by_package(path):
    rc, _o = run([ENGINE, "-Qoq", "--", path], timeout=60)
    return rc == 0


def versions_from_targets(lines):
    out = []
    for t in lines:
        m = re.match(r"^/?usr/lib/modules/([^/]+)/vmlinuz$", t.strip())
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def choose_keep(removed, good, good_available):
    """Ktere z odebiranych jader si nechat jako zalozni (nejvys jedno).

    removed         verze jader, ktera transakce odebira (stejny pkgbase)
    good            posledni jadro, se kterym system uspesne nabehl (luxos-care-boot)
    good_available  jeho moduly v systemu zustanou (je zachovane nebo se neodebira)
    """
    if good and good in removed:
        return good
    if good and good_available:
        return None            # mezitim nespustene jadro nenahradi overene zalozni
    return sorted(removed, key=_verkey)[-1] if removed else None


def _verkey(v):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", v)]


def copy_tree_linked(src, dst):
    """Kopie adresare pres pevne odkazy (bez mista navic); jinde obycejna kopie."""
    def link_or_copy(s, d):
        try:
            os.link(s, d)
        except OSError:
            shutil.copy2(s, d)
    shutil.copytree(src, dst, symlinks=True, copy_function=link_or_copy, dirs_exist_ok=True)


def kernel_pre(targets):
    """PreTransaction: odebirane jadro, se kterym system naposled nabehl, odlozit do STAGING."""
    kernel = config()["KERNEL"]
    removed = [v for v in versions_from_targets(targets) if pkgbase(v) == kernel]
    if not removed:
        return 0
    good = kread("good")
    good_available = bool(good) and good not in removed and os.path.isfile(P(f"{MODULES}/{good}/vmlinuz"))
    keep = choose_keep(removed, good, good_available)
    if not keep:
        log(f"keeping the previous kernel {kread('prev') or '-'} (newer one never booted)")
        return 0
    src = P(f"{MODULES}/{keep}")
    dst = P(f"{STAGING}/{keep}")
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    copy_tree_linked(src, dst)
    # Initramfs, se kterym jadro opravdu nabehlo (jen pokud /boot patri k teto verzi)
    for bootdir in ("/boot",):
        vml = P(f"{bootdir}/vmlinuz-{kernel}")
        img = P(f"{bootdir}/initramfs-{kernel}.img")
        if os.path.isfile(vml) and os.path.isfile(img) and _same_file(vml, os.path.join(src, "vmlinuz")):
            shutil.copy2(img, os.path.join(dst, ".luxos-initramfs.img"))
    log(f"saved kernel {keep} as the previous kernel")
    return 0


def _same_file(a, b):
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                x, y = fa.read(1 << 20), fb.read(1 << 20)
                if x != y:
                    return False
                if not x:
                    return True
    except OSError:
        return False


def restore_staged():
    """PostTransaction: odlozena jadra vratit do /usr/lib/modules (uz mimo spravu pacmanu)."""
    restored = []
    base = P(STAGING)
    for ver in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        src = os.path.join(base, ver)
        dst = P(f"{MODULES}/{ver}")
        if os.path.isfile(os.path.join(dst, "vmlinuz")) and owned_by_package(f"{MODULES}/{ver}/vmlinuz"):
            shutil.rmtree(src, ignore_errors=True)       # jadro nakonec zustalo nainstalovane
            continue
        img = os.path.join(src, ".luxos-initramfs.img")
        if os.path.isfile(img):
            os.makedirs(P(KSTATE), exist_ok=True)
            shutil.move(img, P(f"{KSTATE}/initramfs-{ver}.img"))
        if not os.path.exists(dst):
            try:
                os.rename(src, dst)
            except OSError:
                shutil.copytree(src, dst, symlinks=True)
                shutil.rmtree(src, ignore_errors=True)
        else:
            copy_tree_linked(src, dst)              # zbytky (napr. prazdne adresare) doplnit
            shutil.rmtree(src, ignore_errors=True)
        # Bez pkgbase: mkinitcpio pro nej nevytvari preset, pacman ho nepovazuje za sve
        try:
            os.unlink(os.path.join(dst, "pkgbase"))
        except OSError:
            pass
        restored.append(ver)
    return restored


def release_kept_conflicts(output):
    """pacman odmitl instalaci, protoze zachovane zalozni jadro ma stejnou verzi jako instalovany
    balicek (napr. navrat na starsi jadro): zalozni kopii uvolnit, aby se dal balicek nainstalovat.
    Vraci seznam uvolnenych verzi (nikdy ne bezici jadro)."""
    kept = set(kept_list())
    hit = set()
    for m in re.finditer(r"/usr/lib/modules/([^/\s]+)/\S* exists in filesystem", output or ""):
        if m.group(1) in kept and m.group(1) != running_kernel():
            hit.add(m.group(1))
    for v in sorted(hit):
        shutil.rmtree(P(f"{MODULES}/{v}"), ignore_errors=True)
        try:
            os.unlink(P(f"{KSTATE}/initramfs-{v}.img"))
        except OSError:
            pass
        if kread("prev") == v:
            kwrite("prev", "")
            remove_prev_boot(detect_layout())
        kwrite("kept", " ".join(x for x in kept_list() if x != v))
        history("kernel", ok=True, released=v, title="Released the kept kernel for reinstallation")
    return sorted(hit)


def cleanup_kept(prev):
    """Drzet presne jedno zalozni jadro; starsi odstranit (nikdy ne bezici)."""
    keep = []
    running = running_kernel()
    for v in kept_list():
        d = P(f"{MODULES}/{v}")
        if v == prev:
            keep.append(v)
        elif v == running:
            keep.append(v)            # smaze se pri pristi transakci po restartu
        elif os.path.isdir(d) and not owned_by_package(f"{MODULES}/{v}/vmlinuz"):
            shutil.rmtree(d, ignore_errors=True)
            try:
                os.unlink(P(f"{KSTATE}/initramfs-{v}.img"))
            except OSError:
                pass
            log(f"removed older kept kernel {v}")
    if prev and prev not in keep and os.path.isdir(P(f"{MODULES}/{prev}")):
        keep.append(prev)
    kwrite("kept", " ".join(keep))


# -- zavadec --
ENTRY_RE = r"(?:\+\d+(?:-\d+)?)?\.conf$"


def parse_entry(text):
    d = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        k, _sp, v = s.partition(" ")
        d.setdefault(k, []).append(v.strip())
    return d


def entry_tries(fname):
    """luxos+2-1.conf -> (2, 1); bez pocitadla (None, None)."""
    m = re.search(r"\+(\d+)(?:-(\d+))?\.conf$", fname)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2) or 0)


def entry_id(fname):
    return re.sub(r"\+\d+(?:-\d+)?(\.conf)$", r"\1", fname)


def detect_layout():
    """Jak LuxOS startuje. dict(kind=sdboot|grub|none, ...). Nikdy nesaha na cizi soubory."""
    kernel = config()["KERNEL"]
    esp = read_kv(ESP_CONF)
    if esp.get("ESP_DIR"):
        # (b) sdileny ESP: jadro se kopiruje do EFI/LuxOS/<id> (luxos-esp-sync)
        esp_dir = esp["ESP_DIR"]
        root = esp_dir.split("/EFI/")[0] if "/EFI/" in esp_dir else os.path.dirname(esp_dir)
        ident = os.path.basename(esp_dir.rstrip("/"))
        return _sdboot_layout(root, f"luxos-{ident}", kernel, kdir=esp_dir, freespace=True)
    for root in ("/boot", "/efi", "/boot/efi"):
        if os.path.isdir(P(f"{root}/loader/entries")):
            lay = _sdboot_layout(root, "luxos", kernel)
            if lay["main"]:
                return lay
    if os.path.isfile(P("/boot/grub/grub.cfg")):
        return {"kind": "grub", "kernel": kernel, "kdir": GRUB_PREV_DIR,
                "prev_vmlinuz": f"{GRUB_PREV_DIR}/vmlinuz", "prev_initrd": f"{GRUB_PREV_DIR}/initramfs.img"}
    return {"kind": "none", "kernel": kernel}


def _sdboot_layout(root, name, kernel, kdir=None, freespace=False):
    entries = f"{root}/loader/entries"
    main = None
    try:
        files = sorted(os.listdir(P(entries)))
    except OSError:
        files = []
    for f in files:
        if re.fullmatch(re.escape(name) + ENTRY_RE, f):
            main = f
            break
    lay = {"kind": "sdboot", "kernel": kernel, "esp": root, "entries": entries, "main": main, "name": name,
           "prev_entry": f"{name}-prev.conf", "freespace": freespace}
    linux_dir = None
    if main:
        try:
            with open(P(f"{entries}/{main}")) as fh:
                e = parse_entry(fh.read())
            linux = (e.get("linux") or [""])[0]
            if linux.startswith("/"):
                linux_dir = os.path.dirname(linux)
        except OSError:
            pass
    if kdir is None:
        kdir = root + (linux_dir if linux_dir and linux_dir != "/" else "")
        rel = linux_dir if linux_dir and linux_dir != "/" else ""
    else:
        rel = kdir[len(root):] if kdir.startswith(root) else "/" + os.path.basename(kdir)
    lay["kdir"] = kdir
    lay["rel"] = rel
    lay["prev_vmlinuz"] = f"{kdir}/vmlinuz-{kernel}-prev"
    lay["prev_initrd"] = f"{kdir}/initramfs-{kernel}-prev.img"
    lay["loader_owned"] = loader_owned(root, name)
    return lay


INSTALLER_LOADERS = {
    # (a) cely disk: loader.conf zapsal instalator LuxOS
    "luxos": ["default luxos.conf", "timeout 0", "console-mode max", "editor no"],
}
CARE_MARK = "# luxos-care:"


def loader_owned(root, name):
    """loader.conf patri LuxOS (zapsal ho instalator LuxOS nebo uz ho upravil LuxOS Care).
    Cizi loader.conf (Kali, jiny systemd-boot) se nikdy neupravuje."""
    try:
        with open(P(f"{root}/loader/loader.conf")) as f:
            text = f.read()
    except OSError:
        return False
    if CARE_MARK in text:
        return True
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    lines = [" ".join(ln.split()) for ln in lines]
    if name == "luxos":
        return lines == INSTALLER_LOADERS["luxos"]
    # (b) sdileny ESP: instalator zapisuje loader.conf jen kdyz zadny nebyl
    return lines == [f"default {name}.conf", "timeout 3", "console-mode max", "editor no"]


def prev_entry_text(main_text, lay, ver):
    """Polozka "LuxOS (previous kernel)" odvozena z hlavni (stejne options, jine jadro)."""
    kernel = lay["kernel"]
    rel = lay.get("rel", "")
    out = []
    for line in main_text.splitlines():
        s = line.strip()
        key = s.split(None, 1)[0] if s else ""
        if key == "title":
            out.append("title   LuxOS (previous kernel)")
        elif key == "linux":
            out.append(f"linux   {rel}/vmlinuz-{kernel}-prev")
        elif key == "initrd" and os.path.basename(s.split(None, 1)[1]) in (f"initramfs-{kernel}.img",
                                                                            f"initramfs-{kernel}-fallback.img"):
            out.append(f"initrd  {rel}/initramfs-{kernel}-prev.img")
        elif key in ("version", "sort-key"):
            continue
        else:
            out.append(line.rstrip())
    while out and not out[-1]:
        out.pop()
    out.insert(1, f"version {ver}")
    if lay.get("loader_owned"):
        out.insert(2, "sort-key luxos-prev")
    return "# LuxOS Care - previous kernel (fallback), managed automatically\n" + "\n".join(out) + "\n"


def ensure_main_sort_key(lay):
    """Na vlastnim loader.conf: hlavni polozka pred zalozni (sort-key), default jako vzor.
    systemd-boot pak pri vzoru vybere prvni NEvadnou polozku - po 3 neuspesnych startech zalozni."""
    if lay["kind"] != "sdboot" or not lay.get("loader_owned") or not lay.get("main"):
        return
    path = P(f"{lay['entries']}/{lay['main']}")
    with open(path) as f:
        text = f.read()
    if not re.search(r"^\s*sort-key\s", text, re.M):
        lines = text.rstrip("\n").splitlines()
        lines.insert(1 if lines else 0, "sort-key luxos")
        atomic_write(path, "\n".join(lines) + "\n")
    lpath = P(f"{lay['esp']}/loader/loader.conf")
    with open(lpath) as f:
        ltext = f.read()
    want = f"default {lay['name']}*"
    if CARE_MARK not in ltext or not re.search(r"^\s*default\s+" + re.escape(lay["name"]) + r"\*\s*$", ltext, re.M):
        lines = [ln for ln in ltext.splitlines() if not ln.strip().startswith(CARE_MARK)]
        lines = [want if re.match(r"^\s*default\s", ln) else ln for ln in lines]
        if want not in lines:
            lines.insert(0, want)
        lines.insert(0, f"{CARE_MARK} default = newest working LuxOS entry (automatic boot assessment)")
        atomic_write(lpath, "\n".join(lines) + "\n")


def free_bytes(path):
    try:
        s = os.statvfs(path)
        return s.f_bavail * s.f_frsize
    except OSError:
        return 0


def build_prev_initramfs(ver, out):
    """Initramfs pro zalozni jadro (stejna konfigurace mkinitcpio jako hlavni)."""
    if not have("mkinitcpio"):
        return False
    os.makedirs(os.path.dirname(out), exist_ok=True)
    rc, o = run(["mkinitcpio", "-k", ver, "-g", out], timeout=900)
    if rc != 0:
        log(f"mkinitcpio for {ver} failed: {o[-800:]}")
        try:
            os.unlink(out)
        except OSError:
            pass
        return False
    return True


def install_prev_boot(lay, ver, rebuild=False):
    """Zalozni jadro na misto, odkud ho zavadec nacte, + polozka. -> (ok, duvod)."""
    if lay["kind"] == "none":
        return False, "no_bootloader"
    vml_src = P(f"{MODULES}/{ver}/vmlinuz")
    if not os.path.isfile(vml_src):
        return False, "no_vmlinuz"
    img = P(f"{KSTATE}/initramfs-{ver}.img")
    if rebuild or not os.path.isfile(img):
        if not build_prev_initramfs(ver, img):
            return False, "initramfs"
    kdir = P(lay["kdir"])
    if lay["kind"] == "sdboot" and not os.path.isdir(P(lay["esp"] + "/loader")):
        return False, "esp_missing"
    os.makedirs(kdir, exist_ok=True)
    dst_v, dst_i = P(lay["prev_vmlinuz"]), P(lay["prev_initrd"])
    need = os.path.getsize(vml_src) + os.path.getsize(img) + 4 * 1024 * 1024
    have_now = free_bytes(kdir) + sum(os.path.getsize(f) for f in (dst_v, dst_i) if os.path.isfile(f))
    if have_now < need:
        return False, "esp_full"
    for src, dst in ((vml_src, dst_v), (img, dst_i)):
        if os.path.isfile(dst) and _same_file(src, dst):
            continue
        tmp = dst + ".new"
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    if lay["kind"] == "sdboot":
        with open(P(f"{lay['entries']}/{lay['main']}")) as f:
            main_text = f.read()
        atomic_write(P(f"{lay['entries']}/{lay['prev_entry']}"), prev_entry_text(main_text, lay, ver))
        ensure_main_sort_key(lay)
    elif lay["kind"] == "grub":
        update_grub(force=False)
    return True, ""


def remove_prev_boot(lay):
    """Odstrani jen vlastni soubory zalozniho jadra (presne nazvy)."""
    if lay["kind"] == "none":
        return
    for f in (lay.get("prev_vmlinuz"), lay.get("prev_initrd")):
        if f:
            try:
                os.unlink(P(f))
            except OSError:
                pass
    if lay["kind"] == "sdboot":
        try:
            os.unlink(P(f"{lay['entries']}/{lay['prev_entry']}"))
        except OSError:
            pass
    elif lay["kind"] == "grub":
        update_grub(force=True)


def update_grub(force):
    cfg = P("/boot/grub/grub.cfg")
    try:
        with open(cfg) as f:
            present = "luxos-previous" in f.read()
    except OSError:
        return
    if (present and not force) or not have("grub-mkconfig"):
        return
    rc, out = run(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"], timeout=300)
    if rc != 0:
        log(f"grub-mkconfig failed: {out[-500:]}")


def arm_trial(lay):
    """Nove jadro: 3 pokusy o start, pak zavadec sam pouzije zalozni (automatic boot assessment)."""
    if lay["kind"] == "sdboot" and lay.get("main"):
        main = lay["main"]
        new = entry_id(main).replace(".conf", "+3.conf")
        if main != new:
            os.replace(P(f"{lay['entries']}/{main}"), P(f"{lay['entries']}/{new}"))
            lay["main"] = new
        return True
    if lay["kind"] == "grub" and have("grub-editenv"):
        rc, _o = run(["grub-editenv", GRUBENV, "set", "luxos_tries=3"], timeout=30)
        return rc == 0
    return False


def main_entry_bad(lay=None):
    """Hlavni polozka vycerpala pokusy (nove jadro opakovane nenabehlo)."""
    lay = lay or detect_layout()
    if lay["kind"] == "sdboot" and lay.get("main"):
        left, _done = entry_tries(lay["main"])
        return left == 0
    if lay["kind"] == "grub" and have("grub-editenv"):
        rc, out = run(["grub-editenv", GRUBENV, "list"], timeout=30)
        return rc == 0 and "luxos_tries=0" in out.split()
    return False


def reset_trial(lay=None):
    """Znovu zkusit nove jadro (po oprave): pocitadlo zpet na 3."""
    lay = lay or detect_layout()
    return arm_trial(lay)


def kernel_post(targets):
    """PostTransaction: obnovit odlozene jadro, drzet jedno zalozni, polozka zavadece, pokusy."""
    kernel_changed = any(re.match(r"^/?usr/lib/modules/[^/]+/vmlinuz$", t.strip()) for t in targets)
    dkms_changed = any(re.match(r"^/?usr/src/[^/]+/dkms\.conf$", t.strip()) for t in targets)
    restored = restore_staged()
    prev = kread("prev")
    if restored:
        prev = sorted(restored, key=_verkey)[-1]
        kwrite("prev", prev)
        kept = kept_list()
        if prev not in kept:
            kwrite("kept", " ".join(kept + [prev]))
    if prev and not os.path.isfile(P(f"{MODULES}/{prev}/vmlinuz")):
        prev = ""
        kwrite("prev", "")
    # Zalozni jadro nesmi byt shodne s nainstalovanym (napr. downgrade na stejnou verzi)
    kernel = config()["KERNEL"]
    if prev and owned_by_package(f"{MODULES}/{prev}/vmlinuz"):
        prev = ""
        kwrite("prev", "")
    cleanup_kept(prev)
    if prev and (restored or dkms_changed):
        run(["depmod", prev], timeout=300)
    lay = detect_layout()
    if not prev:
        remove_prev_boot(lay)
        return 0
    rebuild = dkms_changed and not restored
    ok, why = install_prev_boot(lay, prev, rebuild=rebuild)
    st = load_state()
    st["prev_kernel"] = prev
    st["prev_kernel_ok"] = ok
    st["prev_kernel_error"] = why
    st["boot_layout"] = lay["kind"]
    st["auto_fallback"] = bool(lay["kind"] == "grub" or (lay["kind"] == "sdboot" and lay.get("loader_owned")))
    save_state(st)
    if not ok:
        log(f"previous kernel {prev} is not bootable: {why}")
        if lay["kind"] != "none":
            history("kernel", ok=False, prev=prev, error=why)
        return 0
    if kernel_changed and installed_version(kernel):
        arm_trial(lay)
        history("kernel", ok=True, prev=prev, new=installed_version(kernel), layout=lay["kind"])
    return 0


# ---- kontrola po startu (pred boot-complete.target) --------------------------------------
def unit_state(unit):
    rc, out = run(["systemctl", "show", "-p", "ActiveState", "-p", "UnitFileState", "--value", unit], timeout=20)
    vals = out.split()
    return (vals[0] if vals else "", vals[1] if len(vals) > 1 else "")


def boot_check(wait=True):
    """Start je v poradku? Pri uspechu zaznamena overene jadro (pro zalozni) a GRUB pocitadlo.
    Neuspech -> boot-complete.target selze, systemd-bless-boot polozku neoznaci za dobrou."""
    problems = []
    dm_active, dm_enabled = unit_state("display-manager.service")
    if dm_enabled or dm_active:
        for _i in range(30 if wait else 1):
            dm_active, _e = unit_state("display-manager.service")
            if dm_active == "active":
                break
            if wait:
                time.sleep(2)
        if dm_active != "active":
            problems.append("display-manager")
    for t in ("local-fs.target", "sysinit.target", "basic.target"):
        a, _e = unit_state(t)
        if a and a != "active":
            problems.append(t)
    ver = running_kernel()
    if problems:
        history("boot", ok=False, kernel=ver, problems=problems)
        return 1
    if os.path.isfile(P(f"{MODULES}/{ver}/vmlinuz")):
        kwrite("good", ver)
    lay = detect_layout()
    inst = installed_version(lay["kernel"])
    if lay["kind"] == "grub" and have("grub-editenv") and not is_prev_running():
        run(["grub-editenv", GRUBENV, "unset", "luxos_tries"], timeout=30)
    update_state(last_boot_ok=now(), booted_kernel=ver, installed_kernel=inst)
    return 0


def is_prev_running():
    prev = kread("prev")
    return bool(prev) and prev == running_kernel()


# ---- redakce diagnostiky -----------------------------------------------------------------
def _local_names():
    names = set()
    try:
        with open("/etc/passwd") as f:
            for line in f:
                p = line.split(":")
                if len(p) > 5 and p[2].isdigit() and int(p[2]) >= 1000 and p[0] != "nobody":
                    names.add(p[0])
                    if p[4].split(",")[0].strip():
                        names.add(p[4].split(",")[0].strip())
    except OSError:
        pass
    h = socket.gethostname()
    return names, h


REDACT_RULES = [
    (re.compile(r"(?i)\b(password|passwd|pass|token|secret|key|cookie|session|auth[a-z_]*)\s*[=:]\s*\S+"), r"\1=<redacted>"),
    (re.compile(r"(?i)authorization:\s*\S+(\s+\S+)?"), "Authorization: <redacted>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b"), "<mac>"),
    (re.compile(r"\b[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{0,4}){4,7}\b"), "<ip6>"),
    (re.compile(r"\b[A-Za-z0-9_\-+/=]{32,}\b"), "<redacted>"),
    (re.compile(r"/home/[^/\s]+"), "/home/USER"),
    (re.compile(r"/safe/[^/\s]+"), "/safe/USER"),
    (re.compile(r"/run/media/[^/\s]+"), "/run/media/USER"),
    (re.compile(r"\b(SSID|ssid)[ =:]+\S+"), r"\1=<redacted>"),
]


def redact(text, names=None, host=None):
    """Diagnostika pro AI: bez tokenu, hesel, e-mailu, IP/MAC, jmen uzivatelu a domovskych cest."""
    if names is None or host is None:
        n, h = _local_names()
        names = n if names is None else names
        host = h if host is None else host
    out = text or ""
    for rx, rep in REDACT_RULES:
        out = rx.sub(rep, out)
    for n in sorted(names or (), key=len, reverse=True):
        if len(n) >= 2:
            out = re.sub(r"\b" + re.escape(n) + r"\b", "USER", out)
    if host and host not in ("localhost", "archlinux"):
        out = re.sub(r"\b" + re.escape(host) + r"\b", "HOST", out)
    return out


# ---- katalog bezpecnych oprav ------------------------------------------------------------
UNIT_RE = re.compile(r"^[A-Za-z0-9:_.\\@-]{1,200}\.(service|socket|mount|timer|target|path)$")
PKG_RE = re.compile(r"^[a-z0-9@._+][a-z0-9@._+-]{0,120}$")
KVER_RE = re.compile(r"^[A-Za-z0-9._+-]{1,100}$")

# id: (popis, typ cile) - jine akce nez tyto se nikdy neprovedou (ani na pokyn AI)
CATALOG = {
    "none": ("Do nothing and only report the problem", None),
    "remove_db_lock": ("Remove a stale package manager lock", None),
    "complete_upgrade": ("Finish an interrupted system update (lux update)", None),
    "refresh_keyring": ("Refresh the package signing keys", None),
    "rebuild_initramfs": ("Rebuild the initramfs of installed kernels", None),
    "dkms_autoinstall": ("Rebuild DKMS kernel modules (e.g. NVIDIA) for a kernel", "kernel"),
    "reinstall_package": ("Reinstall a package (from cache when possible)", "package"),
    "restart_unit": ("Restart a failed system service", "unit"),
    "clean_cache": ("Free disk space (package cache, old logs)", None),
    "retry_new_kernel": ("Try the newest kernel again on next boot", None),
    "use_previous_kernel": ("Start the previous kernel on next boot", None),
}


def valid_action(action, target=None):
    """Akce je v katalogu a cil ma spravny tvar (dalsi kontrola je v execute_action)."""
    if action not in CATALOG:
        return False
    kind = CATALOG[action][1]
    if kind is None:
        return target in (None, "")
    if not isinstance(target, str):
        return False
    return bool({"unit": UNIT_RE, "package": PKG_RE, "kernel": KVER_RE}[kind].match(target))


def execute_action(action, target=None):
    """Provede akci z katalogu (jako root). Vraci (ok, vystup). Nikdy nespousti libovolny prikaz."""
    if not valid_action(action, target):
        return False, "invalid action"
    if action == "none":
        return True, ""
    if action == "remove_db_lock":
        return remove_stale_lock(), ""
    if action == "complete_upgrade":
        if engine_running():
            return False, "busy"
        rc, out = run(pm(["-Syu"]), timeout=7200)
        if rc != 0 and release_kept_conflicts(out):
            rc, out = run(pm(["-Su"]), timeout=7200)
        return rc == 0, out[-3000:]
    if action == "refresh_keyring":
        rc1, o1 = run(["lux-engine-key", "--populate"], timeout=600)
        rc2, o2 = run(pm(["-Sy", "--needed", "archlinux-keyring"]), timeout=1200)
        return rc1 == 0 and rc2 == 0, (o1 + o2)[-3000:]
    if action == "rebuild_initramfs":
        rc, out = run(["mkinitcpio", "-P"], timeout=1800)
        if os.path.exists("/usr/local/sbin/luxos-esp-sync"):
            run(["/usr/local/sbin/luxos-esp-sync"], timeout=300)
        prev = kread("prev")
        if prev:
            install_prev_boot(detect_layout(), prev, rebuild=True)
        return rc == 0, out[-3000:]
    if action == "dkms_autoinstall":
        if not os.path.isdir(P(f"{MODULES}/{target}/build")):
            return False, "no headers for kernel"
        rc, out = run(["dkms", "autoinstall", "-k", target], timeout=3600)
        return rc == 0, out[-3000:]
    if action == "reinstall_package":
        rc, _o = run([ENGINE, "-Q", target], timeout=30)
        if rc != 0:
            return False, "not installed"
        ver = installed_version(target)
        cached = [f for f in os.listdir(PKG_CACHE)
                  if f.startswith(f"{target}-{ver}-") and f.endswith((".pkg.tar.zst", ".pkg.tar.xz"))] \
            if os.path.isdir(PKG_CACHE) else []
        cached = [f for f in cached if re.fullmatch(re.escape(f"{target}-{ver}-") + r"[a-z0-9_]+\.pkg\.tar\.(zst|xz)", f)]
        if cached:
            rc, out = run(pm(["-U", os.path.join(PKG_CACHE, cached[0])]), timeout=1800)
        else:
            rc, out = run(pm(["-S", target]), timeout=1800)
        return rc == 0, out[-3000:]
    if action == "restart_unit":
        rc, out = run(["systemctl", "restart", target], timeout=180)
        if rc == 0:
            time.sleep(3)
            a, _e = unit_state(target)
            return a in ("active", "activating", "inactive"), out
        return False, out
    if action == "clean_cache":
        clean_cache(keep=1)
        run(["journalctl", "--vacuum-size=200M"], timeout=300)
        return True, ""
    if action == "retry_new_kernel":
        return reset_trial(), ""
    if action == "use_previous_kernel":
        return use_previous_kernel()
    return False, "unknown"


def use_previous_kernel():
    lay = detect_layout()
    prev = kread("prev")
    if not prev or lay["kind"] == "none":
        return False, "no previous kernel"
    if lay["kind"] == "sdboot":
        if lay.get("loader_owned") and lay.get("main"):
            main = lay["main"]
            left, done = entry_tries(main)
            bad = entry_id(main).replace(".conf", f"+0-{max(done or 0, 3)}.conf")
            os.replace(P(f"{lay['entries']}/{main}"), P(f"{lay['entries']}/{bad}"))
            return True, ""
        # Cizi loader.conf: jen jednorazove (promenna EFI, zadny soubor jineho systemu)
        if have("bootctl"):
            rc, out = run(["bootctl", "set-oneshot", lay["prev_entry"]], timeout=30)
            return rc == 0, out
        return False, "bootctl missing"
    if lay["kind"] == "grub" and have("grub-editenv"):
        rc, out = run(["grub-editenv", GRUBENV, "set", "luxos_tries=0"], timeout=30)
        return rc == 0, out
    return False, "unsupported"


# ---- detekce vaznych problemu ------------------------------------------------------------
# Jen sluzby, jejichz selhani uzivatel pozna; ostatni selhani jsou sum.
CRITICAL_UNITS = {
    "display-manager.service", "lightdm.service", "NetworkManager.service", "dbus.service",
    "dbus-broker.service", "polkit.service", "systemd-logind.service", "systemd-journald.service",
    "systemd-udevd.service", "systemd-resolved.service", "bluetooth.service", "power-profiles-daemon.service",
    "upower.service", "udisks2.service", "accounts-daemon.service", "wpa_supplicant.service",
    "systemd-timesyncd.service", "systemd-oomd.service", "cups.service", "avahi-daemon.service",
}
IGNORED_UNITS_RE = re.compile(r"^(luxos-care.*|systemd-fsck@.*|user@.*|session-.*|.*\.scope)$")


def make_problem(pid, title, severity="serious", rules=(), options=(), detail="", **extra):
    p = {"id": pid, "title": title, "severity": severity, "rules": list(rules), "options": list(options),
         "detail": detail}
    p.update(extra)
    return p


def failed_units():
    rc, out = run(["systemctl", "list-units", "--failed", "--plain", "--no-legend", "--no-pager"], timeout=30)
    res = []
    for line in out.splitlines() if rc == 0 else []:
        u = line.split()[0] if line.split() else ""
        if u.startswith("●"):
            u = line.split()[1]
        if u:
            res.append(u)
    return res


def unit_package(unit):
    rc, out = run(["systemctl", "show", "-p", "FragmentPath", "--value", unit], timeout=20)
    path = out.strip()
    if rc != 0 or not path.startswith("/usr/"):
        return ""
    rc, out = run([ENGINE, "-Qoq", path], timeout=30)
    return out.strip() if rc == 0 and PKG_RE.match(out.strip()) else ""


def interrupted_transaction(log_tail):
    """Posledni transakce v logu jadra (lux.log) zacala, ale neskoncila."""
    started = completed = -1
    for i, line in enumerate(log_tail):
        if "[ALPM] transaction started" in line:
            started = i
        elif "[ALPM] transaction completed" in line or "[ALPM] transaction failed" in line:
            completed = i
    return started > completed


def tail(path, n=400):
    try:
        with open(P(path), errors="replace") as f:
            return f.readlines()[-n:]
    except OSError:
        return []


def dkms_missing():
    """[(modul/verze, jadro)] DKMS moduly, ktere pro nainstalovana jadra nejsou nainstalovane."""
    if not have("dkms"):
        return []
    rc, out = run(["dkms", "status"], timeout=120)
    if rc != 0:
        return []
    mods = set()
    installed = set()
    for line in out.splitlines():
        m = re.match(r"^([^/,]+/[^,]+),\s*([^,]+),\s*[^:]+:\s*(\w+)", line)
        if m:
            mods.add(m.group(1))
            if m.group(3) == "installed":
                installed.add((m.group(1), m.group(2)))
        else:
            m = re.match(r"^([^/,]+/[^,:]+):\s*(\w+)", line)
            if m:
                mods.add(m.group(1))
    # jen nejnovejsi verze kazdeho modulu
    latest = {}
    for mv in mods:
        name, ver = mv.split("/", 1)
        if name not in latest or _verkey(ver) > _verkey(latest[name]):
            latest[name] = ver
    res = []
    for ver in installed_kernels():
        if not os.path.isdir(P(f"{MODULES}/{ver}/build/include")):
            continue
        for name, mver in latest.items():
            if (f"{name}/{mver}", ver) not in installed:
                res.append((f"{name}/{mver}", ver))
    return res


def installed_kernels():
    """Verze jader z balicku (ne zachovane zalozni)."""
    res = []
    try:
        names = os.listdir(P(MODULES))
    except OSError:
        return res
    for v in names:
        if os.path.isfile(P(f"{MODULES}/{v}/pkgbase")) and os.path.isfile(P(f"{MODULES}/{v}/vmlinuz")):
            res.append(v)
    return res


def detect_problems():
    """Seznam vaznych problemu (sum se ignoruje). Kazdy ma pravidla (rules) a moznosti pro AI (options)."""
    probs = []
    kernel = config()["KERNEL"]

    # 1. Opusteny zamek databaze balicku
    try:
        age = time.time() - os.stat(P(DB_LOCK)).st_mtime
        if stale_lock(True, engine_running(), age, min_age=600):
            probs.append(make_problem("stale_lock", "The package manager was left locked",
                                      rules=["remove_db_lock"], options=[("remove_db_lock", None)]))
    except OSError:
        pass

    # 2. Prerusena aktualizace (napr. vypnuti uprostred)
    if not engine_running() and interrupted_transaction(tail(ENGINE_LOG)):
        probs.append(make_problem("interrupted_update", "A system update was interrupted",
                                  rules=["remove_db_lock", "complete_upgrade"],
                                  options=[("complete_upgrade", None), ("refresh_keyring", None)]))

    # 3. Chybejici initramfs nebo jadro v /boot pro nainstalovane jadro
    lay = detect_layout()
    if lay["kind"] != "none" and installed_version(kernel):
        bootdir = "/boot"
        missing = [f for f in (f"vmlinuz-{kernel}", f"initramfs-{kernel}.img") if not os.path.isfile(P(f"{bootdir}/{f}"))]
        if missing:
            probs.append(make_problem("initramfs_missing", "The kernel boot files are missing",
                                      rules=["rebuild_initramfs"], options=[("rebuild_initramfs", None)],
                                      detail=", ".join(missing)))

    # 4. DKMS (NVIDIA apod.) se pro jadro nesestavilo
    miss = dkms_missing()
    if miss:
        kvers = sorted({k for _m, k in miss})
        probs.append(make_problem("dkms_failed", "A driver module (DKMS) is not built for the kernel",
                                  rules=[("dkms_autoinstall", k) for k in kvers] + ["rebuild_initramfs"],
                                  options=[("dkms_autoinstall", k) for k in kvers] + [("rebuild_initramfs", None)],
                                  detail="; ".join(f"{m} {k}" for m, k in miss)))

    # 5. System nabehl se zalozni jadrem, protoze nove opakovane selhalo
    if is_prev_running() and installed_version(kernel) and main_entry_bad(lay):
        inst = [v for v in installed_kernels() if pkgbase(v) == kernel]
        rules = [("dkms_autoinstall", v) for v in inst if os.path.isdir(P(f"{MODULES}/{v}/build"))]
        probs.append(make_problem("fallback_kernel", "The newest kernel did not start, LuxOS used the previous one",
                                  rules=rules + ["rebuild_initramfs", "retry_new_kernel"],
                                  options=[("rebuild_initramfs", None), ("retry_new_kernel", None)]
                                  + [("dkms_autoinstall", v) for v in inst],
                                  once_per=installed_version(kernel)))

    # 6. Selhane dulezite sluzby
    for u in failed_units():
        if IGNORED_UNITS_RE.match(u) or u not in CRITICAL_UNITS:
            continue
        pkg = unit_package(u)
        opts = [("restart_unit", u)] + ([("reinstall_package", pkg)] if pkg else [])
        probs.append(make_problem(f"unit:{u}", "A system service failed: %s", rules=[("restart_unit", u)],
                                  options=opts, unit=u, args=[u]))

    # 7. Plny disk
    for mnt, limit in (("/", 2 * 1024 ** 3), (PKG_CACHE, 1024 ** 3)):
        try:
            s = os.statvfs(P(mnt))
        except OSError:
            continue
        free = s.f_bavail * s.f_frsize
        total = s.f_blocks * s.f_frsize
        if total and (free < limit and free / total < 0.05):
            probs.append(make_problem("disk_full", "The disk is almost full", rules=["clean_cache"],
                                      options=[("clean_cache", None)], detail=f"{mnt}: {free // 1024 ** 2} MiB free"))
            break

    # 8. Chyby souboroveho systemu (jen hlaseni - automaticka oprava neni bezpecna)
    fs = fs_errors()
    if fs:
        probs.append(make_problem("fs_errors", "The file system reported errors - back up your data",
                                  severity="report", detail=fs))

    # 9. Aktualizace opakovane selhava
    st = load_state()
    if int(st.get("failures", 0) or 0) >= NOTIFY_FAIL_AFTER:
        err = st.get("last_error", "unknown")
        rules = {"locked": ["remove_db_lock"], "keyring": ["refresh_keyring"], "disk": ["clean_cache"]}.get(err, [])
        probs.append(make_problem(f"update_failing:{err}", "System updates keep failing", rules=rules,
                                  options=[("refresh_keyring", None), ("clean_cache", None), ("complete_upgrade", None)],
                                  detail=err, once_per=str(st.get("failures"))))
    return probs


def fs_errors():
    out = []
    rc, txt = run(["journalctl", "-b", "-k", "-p", "err", "--no-pager", "-q", "-o", "cat",
                   "--grep", "(EXT4-fs error|BTRFS (error|critical)|I/O error|FAT-fs.*error)"], timeout=60)
    if rc == 0 and txt.strip():
        out.append(f"{len(txt.splitlines())} kernel file system errors in this boot")
    for u in failed_units():
        if u.startswith("systemd-fsck@"):
            out.append(f"file system check failed ({u})")
    if have("btrfs"):
        rc, txt = run(["btrfs", "device", "stats", "-c", "/"], timeout=30)
        if rc not in (0, 127) and "corruption_errs" in txt:
            bad = [ln.strip() for ln in txt.splitlines() if re.search(r"(corruption|generation|read_io|write_io)_errs\s+[1-9]", ln)]
            if bad:
                out.append("btrfs: " + "; ".join(bad[:4]))
    return "; ".join(out)


def diagnosis(problem):
    """Kratka diagnostika pro LuxAI (redigovana, max ~6 kB, zadne osobni soubory)."""
    parts = [f"Problem: {problem['title']}", f"Detail: {problem.get('detail', '')}",
             f"Kernel running: {running_kernel()}, installed: {installed_version(config()['KERNEL'])}, "
             f"previous kept: {kread('prev') or '-'}"]
    pid = problem["id"]
    if pid.startswith("unit:"):
        u = problem.get("unit", "")
        _rc, o = run(["journalctl", "-b", "-u", u, "-n", "40", "--no-pager", "-q", "-o", "short-monotonic",
                      "--no-hostname"], timeout=30)
        parts.append(f"journal of {u}:\n{o}")
    elif pid in ("interrupted_update",) or pid.startswith("update_failing"):
        parts.append("lux.log (package manager log):\n" + "".join(tail(ENGINE_LOG, 40)))
        parts.append("last error output:\n" + str(load_state().get("last_error_output", ""))[-1500:])
    elif pid in ("fallback_kernel", "dkms_failed", "initramfs_missing"):
        _rc, o = run(["dkms", "status"], timeout=60) if have("dkms") else (0, "")
        parts.append(f"dkms status:\n{o}")
        _rc, o = run(["journalctl", "-b", "-1", "-p", "err", "-n", "40", "--no-pager", "-q", "-o", "cat"], timeout=30)
        parts.append(f"errors from the previous boot:\n{o}")
    text = redact("\n".join(parts))
    return text[:6000]


# ---- samooprava --------------------------------------------------------------------------
def repair_attempts_today(st):
    day = time.strftime("%Y-%m-%d")
    return st.get("attempts", {}).get(day, {})


def do_check(after_update=False, boot=False):
    """Telo luxos-care-check.service: najde vazne problemy, v carefree je opravi pravidly
    a pro neopravene pripravi dotaz pro LuxAI (vybere relace uzivatele)."""
    m = mode()
    st = load_state()
    probs = detect_problems()
    known = {p["id"]: p for p in st.get("problems", [])}
    day = time.strftime("%Y-%m-%d")
    attempts = st.get("attempts", {})
    attempts = {day: attempts.get(day, {})}
    today = attempts[day]
    done_once = list(st.get("rules_done_once", []))[-200:]
    result = []
    for p in probs:
        old = known.get(p["id"], {})
        tag = p["id"] + "@" + str(p.get("once_per", ""))
        p["first_seen"] = old.get("first_seen", now())
        fixed = False
        # Pravidla jednou denne; problemy s once_per (napr. verze jadra) jen jednou vubec - zadne smycky
        once = "once_per" in p
        allowed = (tag not in done_once) if once else today.get(tag, 0) < 1
        if m == "carefree" and p["rules"] and allowed:
            today[tag] = today.get(tag, 0) + 1
            if once:
                done_once.append(tag)
            for rule in p["rules"]:
                action, target = (rule if isinstance(rule, (list, tuple)) else (rule, None))
                ok, out = execute_action(action, target)
                history("repair", problem=p["id"], title=p["title"], args=p.get("args", []), action=action, target=target or "",
                        source="rule", ok=ok, output=redact(out[-600:]) if out else "")
                if ok and not _still_present(p):
                    fixed = True
                    add_event("repaired", title=p["title"], args=p.get("args", []))
                    break
        if fixed:
            continue
        p["status"] = "open"
        if p["severity"] == "serious" and p["options"]:
            if m == "carefree":
                req = old.get("ai") if old.get("ai", {}).get("tag") == tag else None
                if req is None and today.get("ai:" + tag, 0) < 1:
                    req = {"request_id": secrets.token_hex(6), "tag": tag, "status": "pending",
                           "diagnosis": diagnosis(p),
                           "options": [{"n": i + 1, "action": a, "target": t or "",
                                        "label": CATALOG[a][0] + (f": {t}" if t else "")}
                                       for i, (a, t) in enumerate(p["options"])] +
                                      [{"n": 0, "action": "none", "target": "", "label": CATALOG["none"][0]}],
                           "created": now()}
                    today["ai:" + tag] = 1
                if req:
                    p["ai"] = req
        if p["id"] not in known:
            add_event("problem", title=p["title"], args=p.get("args", []), id=p["id"])
        result.append(p)
    st = load_state()
    st["problems"] = result
    st["attempts"] = attempts
    st["rules_done_once"] = done_once
    st["last_check"] = now()
    st["pacnew"] = find_pacnew()
    st["needs_reboot"] = needs_reboot()
    st["mode"] = m
    save_state(st)
    return 0


def _still_present(p):
    try:
        return any(q["id"] == p["id"] for q in detect_problems())
    except Exception:  # noqa: BLE001
        return True


def safe_check(after_update=False):
    try:
        do_check(after_update=after_update)
    except Exception as e:  # noqa: BLE001
        log(f"check failed: {e}")


def apply_ai_choice(request_id, n):
    """Volba LuxAI z relace uzivatele (luxos-care-apply@ID-N.service). Overi se proti stavu:
    pozadavek existuje a ceka, N je jedna z moznosti, ktere pripravil root, rezim carefree, limit."""
    if mode() != "carefree":
        return False, "classic mode"
    if not re.fullmatch(r"[0-9a-f]{12}", request_id or "") or not (0 <= int(n) <= 20):
        return False, "invalid request"
    st = load_state()
    for p in st.get("problems", []):
        req = p.get("ai")
        if not req or req.get("request_id") != request_id:
            continue
        if req.get("status") != "pending":
            return False, "already handled"
        opt = next((o for o in req.get("options", []) if int(o.get("n", -1)) == int(n)), None)
        if opt is None or not valid_action(opt["action"], opt["target"] or None):
            return False, "option not offered"
        day = time.strftime("%Y-%m-%d")
        used = sum(1 for h in read_history(500) if h.get("source") == "ai" and h.get("action") != "none"
                   and time.strftime("%Y-%m-%d", time.localtime(h.get("time", 0))) == day)
        if used >= AI_ACTIONS_PER_DAY and opt["action"] != "none":
            return False, "daily limit"
        req["status"] = "running"
        save_state(st)
        ok, out = execute_action(opt["action"], opt["target"] or None)
        history("repair", problem=p["id"], title=p["title"], args=p.get("args", []), action=opt["action"], target=opt["target"],
                source="ai", model="LuxAI Flash", ok=ok, output=redact(out[-600:]) if out else "")
        st = load_state()
        for q in st.get("problems", []):
            if q.get("ai", {}).get("request_id") == request_id:
                q["ai"]["status"] = "done" if ok else "failed"
                q["ai"]["chosen"] = int(n)
        save_state(st)
        if ok and opt["action"] != "none":
            if not _still_present(p) or opt["action"] in ("retry_new_kernel", "use_previous_kernel"):
                add_event("repaired", title=p["title"], args=p.get("args", []), ai=True)
        safe_check()
        return ok, out
    return False, "unknown request"
