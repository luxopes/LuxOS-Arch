#!/usr/bin/python3
"""lux countme - anonymni pocitani aktivnich instalaci LuxOS (podle "countme" z DNF Fedory).

Nejvys jednou za kalendarni tyden (ISO tyden od pondeli, UTC), kdyz lux jako root uz stahuje seznamy
baliku (luxos.db), posle jeden maly pozadavek navic:

    GET https://luxos.lux-ai.cz/countme?v=1.0.0&arch=x86_64&ch=stable&age=2

a NIC jineho: v = verze LuxOS (/usr/lib/luxos/version, jinak VERSION_ID z os-release), arch =
architektura, ch = kanal aktualizaci (stable|staging), age = stari instalace (1 = prvni tyden,
2 = do mesice, 3 = do pul roku, 4 = dele). Zadny identifikator, nazev pocitace, hardware, seznam
aplikaci ani data uzivatele; hlavicky jen Host, User-Agent "LuxOS-countme" a Connection: close
(bez cookies, bez verze Pythonu, bez jmena pocitace).

Stav: /var/lib/lux/countme (JSON {"since": unix cas instalace, "last_week": "2026-W45"}; "since"
= cas zmeny /var/log/luxos-install.log z instalatoru, jinak cas prvniho behu). Tyden se zapise jen po
uspesne odpovedi serveru; chyba = zkusi se pri pristim behu lux (zadne dalsi opakovani).

Nikdy nezdrzuje aktualizaci: pozadavek bezi ve vlakne na pozadi (casovy limit 5 s), chyby se
ignoruji. Neposila se: z live ISO, v kontejneru, pro jiny koren nez /, bez prav roota, pri
[general] countme = false v /etc/lux/lux.conf (lux-config set-countme off, Aktualizace softwaru >
Soukromi, instalator) a pred dokoncenim Pruvodce nastavenim u OEM instalaci.

  lux_countme.py status      co by se poslalo a proc (ne)
  lux_countme.py send        poslat hned, kdyz je tento tyden na rade (jen root; pro ladeni)
"""
import datetime
import http.client
import json
import os
import re
import sys
import threading
import time
import urllib.parse

HOST = "luxos.lux-ai.cz"
PATH = "/countme"
TIMEOUT = 5.0
USER_AGENT = "LuxOS-countme"
STATE = "/var/lib/lux/countme"
LOCK = "/var/lib/lux/countme.lock"
LUX_CONF = "/etc/lux/lux.conf"
VERSION_FILE = "/usr/lib/luxos/version"
OS_RELEASE = ("/etc/os-release", "/usr/lib/os-release")
INSTALL_LOG = "/var/log/luxos-install.log"
# OEM (luxos-oem): pocitac pripraveny pro jineho cloveka se pocita az po Pruvodci nastavenim (majitel
# videl volbu); stari instalace se pak pocita od dokonceni Pruvodce
OEM_CONF = "/etc/luxos/oem.conf"
OEM_DONE = "/var/lib/luxos/oem/done"
LIVE_MARKERS = ("/run/archiso", "/run/archiso/bootmnt")
CONTAINER_MARKERS = ("/run/.containerenv", "/.dockerenv")
VERSION_RE = re.compile(r"^[0-9]{1,2}\.[0-9]{1,3}\.[0-9]{1,3}$")
ARCHES = ("x86_64",)
CHANNELS = ("stable", "staging")
DAY = 86400
# hranice skupin stari instalace (dny): 1 = prvni tyden, 2 = do mesice, 3 = do pul roku, 4 = dele
AGE_LIMITS = ((7, 1), (30, 2), (182, 3))


def iso_week(now=None):
    """Kalendarni tyden ISO 8601 (od pondeli, UTC): "2026-W45"."""
    d = datetime.datetime.fromtimestamp(time.time() if now is None else now, datetime.timezone.utc)
    y, w, _d = d.isocalendar()
    return f"{y}-W{w:02d}"


def age_bucket(since, now):
    days = max(0.0, (now - since) / DAY)
    for limit, bucket in AGE_LIMITS:
        if days < limit:
            return bucket
    return 4


def _read(path, root="", limit=65536):
    try:
        with open(root + path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return None


def os_version(root=""):
    """Verze LuxOS X.Y.Z (luxos-branding /usr/lib/luxos/version, jinak VERSION_ID z os-release)."""
    text = _read(VERSION_FILE, root) or ""
    m = re.search(r"^VERSION=[\"']?([^\"'\s]+)", text, re.M)
    if m and VERSION_RE.match(m.group(1)):
        return m.group(1)
    for p in OS_RELEASE:
        text = _read(p, root) or ""
        m = re.search(r"^VERSION_ID=[\"']?([^\"'\s]+)", text, re.M)
        if m and VERSION_RE.match(m.group(1)):
            return m.group(1)
    return None


def machine_arch():
    a = os.uname().machine
    return a if a in ARCHES else None


def _lux_config():
    """lux_config z lux-engine (uz nacteny lux_alpm.py, /usr/lib/lux, pri spusteni z repozitare
    ../lux-engine)."""
    if "lux_config" in sys.modules:
        return sys.modules["lux_config"]
    here = os.path.dirname(os.path.abspath(__file__))
    for d in ("/usr/lib/lux", os.path.join(here, "..", "lux-engine")):
        if os.path.isfile(os.path.join(d, "lux_config.py")) and d not in sys.path:
            sys.path.append(d)
    try:
        import lux_config
        return lux_config
    except ImportError:
        return None


def settings(conf=LUX_CONF, root=""):
    """(zapnuto, kanal) z lux.conf. Rozbita nebo chybejici konfigurace = nic neposilat."""
    lc = _lux_config()
    if lc is not None:
        try:
            cfg = lc.parse(conf, root)
        except Exception:
            return False, None
        on = cfg.get("countme")
        ch = cfg.get("channel") or "stable"
        if on is None:
            # lux-engine bez klice countme (starsi nez lux): primo z TOML, vychozi zapnuto
            on = _toml_countme(conf, root)
        return on in (True, "on"), ch
    return _toml_countme(conf, root) == "on", "stable"


def _toml_countme(conf, root):
    import tomllib
    try:
        with open(root + conf, "rb") as f:
            v = tomllib.load(f).get("general", {}).get("countme", True)
    except (OSError, ValueError):
        return "off"
    return "on" if v is True or str(v).lower() in ("on", "yes", "true", "1") else "off"


def load_state(path=STATE):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except (OSError, ValueError):
        pass
    return {}


def save_state(state, path=STATE):
    d = os.path.dirname(path)
    tmp = os.path.join(d, ".countme.tmp")
    data = {"since": int(state["since"]), "last_week": state.get("last_week")}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
        f.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def oem_pending(root=""):
    text = _read(OEM_CONF, root) or ""
    return re.search(r"^OEM=1\s*$", text, re.M) is not None and not os.path.exists(root + OEM_DONE)


def install_time(now, root=""):
    """Cas instalace: dokonceni Pruvodce nastavenim (OEM), jinak zmena protokolu instalatoru
    (kopiruje se na konci instalace), jinak ted."""
    for p in (OEM_DONE, INSTALL_LOG):
        try:
            t = os.stat(root + p).st_mtime
            if 0 < t <= now:
                return int(t)
        except OSError:
            pass
    return int(now)


def blocked(root="", euid=None, rootdir="/"):
    """Duvod, proc se tento pocitac nepocita (None = muze)."""
    if (os.geteuid() if euid is None else euid) != 0:
        return "not root"
    if os.path.realpath(rootdir or "/") != "/":
        return "other root"
    if any(os.path.exists(root + m) for m in LIVE_MARKERS):
        return "live system"
    cmd = _read("/proc/cmdline", root) or ""
    if "archisobasedir=" in cmd or "archisolabel=" in cmd:
        return "live system"
    if any(os.path.exists(root + m) for m in CONTAINER_MARKERS):
        return "container"
    if oem_pending(root):
        return "setup assistant not finished (OEM)"
    return None


def plan(now=None, conf=LUX_CONF, state_path=STATE, root="", euid=None, rootdir="/", check_week=True):
    """-> (parametry pozadavku jako [(klic, hodnota)], stav) nebo (None, duvod)."""
    now = time.time() if now is None else now
    why = blocked(root, euid, rootdir)
    if why:
        return None, why
    on, ch = settings(conf, root)
    if not on:
        return None, "turned off (countme = false in /etc/lux/lux.conf)"
    if ch not in CHANNELS:
        return None, "unknown channel"
    v, arch = os_version(root), machine_arch()
    if not v:
        return None, "unknown LuxOS version"
    if not arch:
        return None, "unsupported architecture"
    st = load_state(state_path)
    since = st.get("since")
    if not isinstance(since, (int, float)) or since <= 0 or since > now + DAY:
        since = install_time(now, root)
    st = {"since": int(since), "last_week": st.get("last_week") if isinstance(st.get("last_week"), str) else None}
    week = iso_week(now)
    if check_week and st["last_week"] == week:
        return None, f"already counted this week ({week})"
    params = [("v", v), ("arch", arch), ("ch", ch), ("age", str(age_bucket(st["since"], now)))]
    return params, st


def query(params):
    return PATH + "?" + urllib.parse.urlencode(params)


def send(params, host=HOST, timeout=TIMEOUT, port=None, https=True):
    """Jeden GET; True = server odpovedel 2xx. Zadne presmerovani, cookies ani opakovani."""
    cls = http.client.HTTPSConnection if https else http.client.HTTPConnection
    conn = cls(host, port, timeout=timeout)
    try:
        # skip_accept_encoding: http.client by jinak pridal "Accept-Encoding: identity"; posila se
        # tedy jen Host, User-Agent a Connection
        conn.putrequest("GET", query(params), skip_accept_encoding=True)
        conn.putheader("User-Agent", USER_AGENT)
        conn.putheader("Connection", "close")
        conn.endheaders()
        r = conn.getresponse()
        r.read(1024)
        return 200 <= r.status < 300
    finally:
        conn.close()


def run_once(now=None, state_path=STATE, lock_path=LOCK, sender=send, **kw):
    """Poslat, kdyz je tento tyden na rade. Vraci "sent" | "failed" | "busy" | duvod, proc ne."""
    import fcntl
    now = time.time() if now is None else now
    try:
        lockf = open(lock_path, "a")
    except OSError:
        return "no state directory"
    try:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return "busy"
        params, st = plan(now, state_path=state_path, **kw)
        if params is None:
            return st
        try:
            if not sender(params):
                return "failed"
        except Exception:
            return "failed"
        st["last_week"] = iso_week(now)
        try:
            save_state(st, state_path)
        except OSError:
            return "failed"
        return "sent"
    finally:
        lockf.close()


_THREAD = None


def start(rootdir="/", **kw):
    """Z lux po uspesne obnove seznamu baliku: rychla kontrola v hlavnim vlakne (soubor stavu),
    samotny pozadavek ve vlakne na pozadi. Nikdy nevyhodi vyjimku a nezdrzi volajiciho."""
    global _THREAD
    try:
        if _THREAD is not None:
            return None
        params, _st = plan(rootdir=rootdir, **{k: v for k, v in kw.items()
                                               if k in ("now", "conf", "euid", "root", "state_path")})
        if params is None:
            return None
        t = threading.Thread(target=lambda: run_once(rootdir=rootdir, **kw), name="countme", daemon=True)
        t.deadline = time.monotonic() + TIMEOUT + 1
        t.start()
        _THREAD = t
        return t
    except Exception:
        return None


def finish(interactive=None):
    """Na konci lux: sluzby (LuxOS Care) pockaji na dokonceni pozadavku nejvys do jeho casoveho limitu
    od startu (aktualizace mezitim obvykle davno bezi dal); v terminalu se neceka vubec - nedokonceny
    pozadavek se zkusi pri pristim behu."""
    t = _THREAD
    if t is None or not t.is_alive():
        return
    if interactive is None:
        try:
            interactive = os.isatty(1) or os.isatty(2)
        except Exception:
            interactive = False
    if interactive:
        return
    t.join(max(0.0, t.deadline - time.monotonic()))


def status_text():
    params, st = plan(check_week=False, euid=0)     # co by poslal root (lux update, LuxOS Care)
    last = load_state().get("last_week") or "never"
    lines = [f"countme: last counted week: {last}"]
    if params is None:
        lines.append(f"countme: not sent - {st}")
    else:
        lines.append(f"countme: request (once per week, when the package lists are refreshed): "
                     f"https://{HOST}{query(params)}")
        lines.append(f"countme: headers: Host: {HOST}, User-Agent: {USER_AGENT}, Connection: close")
        if st.get("last_week") == iso_week():
            lines.append("countme: this week is already counted")
    lines.append("countme: turn off: sudo lux-config set-countme off")
    return "\n".join(lines)


def main(argv):
    cmd = argv[0] if argv else "status"
    if cmd == "status":
        print(status_text())
        return 0
    if cmd == "send":
        r = run_once()
        print(f"countme: {r}")
        return 0 if r in ("sent",) or r.startswith("already") else 1
    print("usage: lux_countme.py status|send", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
