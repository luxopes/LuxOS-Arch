"""LuxOS - testy GUI nikdy na skutecne obrazovce a ve skutecne relaci uzivatele.

Importuje ho kazdy test, ktery spousti okna, xdotool, setxkbmap, spravce oken nebo sluzby relace
(packages/*/tests). Pri importu:

  - DISPLAY, ktery neni virtualni obrazovka spustena pro testy (Xvfb/Xephyr/Xvnc tohoto uzivatele,
    napr. z xvfb-run), se nahradi vlastnim Xvfb (ukonci se s testem); bez Xvfb se DISPLAY odebere
    a testy GUI se preskoci. Nevyplneny DISPLAY zustava (testy GUI se preskoci jako dosud).
  - XAUTHORITY skutecne relace se odebere, sbernice D-Bus skutecne relace
    (DBUS_SESSION_BUS_ADDRESS = /run/user/UID/bus) se nahradi vlastni (dbus-daemon, skonci s testem).
  - HOME, XDG_RUNTIME_DIR a XDG_CONFIG/DATA/CACHE/STATE_HOME ukazujici do skutecneho domova nebo
    /run/user/UID se nahradi docasnou slozkou (xfconf, dconf, gtk.css, klavesnice skutecneho
    uzivatele se nikdy nezmeni).

Skutecnou obrazovku nelze vynutit zadnou promennou. Proc: test spusteny omylem s DISPLAY=:0
prepnul majiteli rozlozeni klavesnice (setxkbmap) a klikal do jeho oken.

    import luxos_testguard          # (scripts/ v sys.path; viz hlavicka testu)
    luxos_testguard.check_env(env)  # pred spustenim podprocesu s vlastnim prostredim (vyjimka)
"""
import atexit
import os
import pwd
import shutil
import subprocess
import tempfile
import time

_UID = os.getuid()
_REAL_HOME = pwd.getpwuid(_UID).pw_dir
_REAL_RUNTIME = "/run/user/%d" % _UID
_REAL_BUS = "unix:path=%s/bus" % _REAL_RUNTIME
_PRIVATE_X = ("Xvfb", "Xephyr", "Xvnc")
_procs = []
_tmp = None


class RealSessionError(RuntimeError):
    pass


def _display_number(display):
    """":0.0" -> "0"; vzdaleny nebo neplatny DISPLAY -> None"""
    if not display or not display.startswith(":"):
        return None
    num = display[1:].split(".")[0]
    return num if num.isdigit() else None


def is_private_display(display):
    """Bezi pro DISPLAY virtualni X server tohoto uzivatele (Xvfb/Xephyr/Xvnc)?"""
    num = _display_number(display)
    if num is None:
        return False
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            if os.stat("/proc/" + pid).st_uid != _UID:
                continue
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                argv = f.read().split(b"\0")
        except OSError:
            continue
        if argv and os.path.basename(argv[0].decode(errors="replace")) in _PRIVATE_X \
                and (":" + num).encode() in argv:
            return True
    return False


def _real_path(path):
    if not path:
        return False
    path = os.path.realpath(path)
    # vlastni docasna slozka testu (TMPDIR muze byt v domove, napr. ~/LuxOS-Arch/out) neni skutecna relace
    if _tmp and (path == os.path.realpath(_tmp) or path.startswith(os.path.realpath(_tmp) + os.sep)):
        return False
    return path == os.path.realpath(_REAL_HOME) or path.startswith(os.path.realpath(_REAL_HOME) + os.sep) \
        or path == _REAL_RUNTIME or path.startswith(_REAL_RUNTIME + os.sep)


def check_env(env):
    """Vyjimka, kdyz prostredi podprocesu miri do skutecne relace (obrazovka, sbernice, domov)."""
    problems = []
    display = env.get("DISPLAY")
    if display and not is_private_display(display):
        problems.append("DISPLAY=%s is not a test X server" % display)
    if env.get("DBUS_SESSION_BUS_ADDRESS", "").startswith(_REAL_BUS):
        problems.append("DBUS_SESSION_BUS_ADDRESS is the real session bus")
    for var in ("HOME", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        if var == "HOME" and env.get(var) and not _real_path(env.get(var)):
            continue
        if env.get(var) and _real_path(env.get(var)):
            problems.append("%s=%s is the real session" % (var, env.get(var)))
    if problems:
        raise RealSessionError("refusing to touch the real session: " + "; ".join(problems))


def _die_with_parent():
    """Xvfb skonci i pri padu testu (PR_SET_PDEATHSIG)."""
    try:
        import ctypes
        import signal
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)
    except (OSError, AttributeError):
        pass


def _free_display():
    for n in range(90, 200):
        if not os.path.exists("/tmp/.X11-unix/X%d" % n) and not os.path.exists("/tmp/.X%d-lock" % n):
            return n
    return None


def _start_xvfb():
    xvfb = shutil.which("Xvfb")
    n = _free_display()
    if not xvfb or n is None:
        return None
    p = subprocess.Popen([xvfb, ":%d" % n, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=_die_with_parent)
    for _ in range(100):
        if os.path.exists("/tmp/.X11-unix/X%d" % n):
            break
        if p.poll() is not None:
            return None
        time.sleep(0.05)
    else:
        p.kill()
        return None
    _procs.append(p)
    return ":%d" % n


def _start_bus():
    if not shutil.which("dbus-daemon"):
        return None
    p = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, preexec_fn=_die_with_parent)
    addr = p.stdout.readline().strip()
    if not addr:
        p.kill()
        return None
    _procs.append(p)
    return addr


def _cleanup():
    for p in _procs:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
    if _tmp:
        shutil.rmtree(_tmp, True)


def _private_dir():
    global _tmp
    if _tmp is None:
        _tmp = tempfile.mkdtemp(prefix="luxos-testguard-")
        os.chmod(_tmp, 0o700)
    return _tmp


def protect():
    """Upravi os.environ tohoto procesu (vola se pri importu)."""
    env = os.environ
    display = env.get("DISPLAY")
    if display and not is_private_display(display):
        env.pop("XAUTHORITY", None)
        own = _start_xvfb()
        if own:
            env["DISPLAY"] = own
        else:
            env.pop("DISPLAY", None)
    if _real_path(env.get("XDG_RUNTIME_DIR")):
        run = os.path.join(_private_dir(), "run")
        os.makedirs(run, mode=0o700, exist_ok=True)
        env["XDG_RUNTIME_DIR"] = run
    if _real_path(env.get("HOME")):
        env["HOME"] = os.path.join(_private_dir(), "home")
        os.makedirs(env["HOME"], exist_ok=True)
    for var, sub in (("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", ".local/share"),
                     ("XDG_CACHE_HOME", ".cache"), ("XDG_STATE_HOME", ".local/state")):
        if _real_path(env.get(var)):
            env[var] = os.path.join(env["HOME"], sub)
    # sbernice skutecne relace -> vlastni (az s docasnym HOME: sluzby aktivovane D-Bus ho zdedi)
    # bez sbernice (xvfb-run bez dbus-run-session) take vlastni - jinak GLib zkusi dbus-launch
    if env.get("DBUS_SESSION_BUS_ADDRESS", "").startswith(_REAL_BUS) or \
            (env.get("DISPLAY") and not env.get("DBUS_SESSION_BUS_ADDRESS")):
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
        bus = _start_bus()
        if bus:
            env["DBUS_SESSION_BUS_ADDRESS"] = bus
    check_env(env)


atexit.register(_cleanup)
protect()
