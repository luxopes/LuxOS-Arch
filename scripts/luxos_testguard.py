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
  - Systemova sbernice: DBUS_SYSTEM_BUS_ADDRESS vzdy miri na neexistujici soket (BlueZ, UPower,
    NetworkManager, fprintd, logind pocitace jsou pro testy nedostupne). Vlastni falesnou systemovou
    sbernici preda test jen schvalenou promennou LUXOS_TEST_SYSTEM_BUS (adresa jeho dbus-daemon), nebo
    ji nastavi az v prostredi podprocesu (check_env odmitne jen skutecny soket).
  - Kamery: LUXOS_VIDEO_DEV_DIR (kde aplikace hledaji video*, jinak /dev) miri na prazdnou docasnou
    slozku, takze Kamera, Profilova fotka ani QR kod Wi-Fi zadnou skutecnou kameru nenajdou. Proces
    testu navic nesmi otevrit /dev/video* (audit hook -> PermissionError).

Skutecnou obrazovku nelze vynutit zadnou promennou. Proc: test spusteny omylem s DISPLAY=:0
prepnul majiteli rozlozeni klavesnice (setxkbmap) a klikal do jeho oken.

    import luxos_testguard          # (scripts/ v sys.path; viz hlavicka testu)
    luxos_testguard.check_env(env)  # pred spustenim podprocesu s vlastnim prostredim (vyjimka)
"""
import atexit
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import time

_UID = os.getuid()
_REAL_HOME = pwd.getpwuid(_UID).pw_dir
_REAL_RUNTIME = "/run/user/%d" % _UID
_REAL_BUS = "unix:path=%s/bus" % _REAL_RUNTIME
_PRIVATE_X = ("Xvfb", "Xephyr", "Xvnc")
# skutecna systemova sbernice (vychozi adresa libdbus/GDBus bez DBUS_SYSTEM_BUS_ADDRESS)
_REAL_SYSTEM_SOCKETS = ("/run/dbus/system_bus_socket", "/var/run/dbus/system_bus_socket")
_SYSTEM_BUS_VAR = "LUXOS_TEST_SYSTEM_BUS"     # schvalena falesna systemova sbernice testu
_VIDEO_VAR = "LUXOS_VIDEO_DEV_DIR"
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


def is_real_system_bus(address):
    """Miri adresa D-Bus na skutecnou systemovou sbernici? (prazdna = vychozi = skutecna)"""
    if not address:
        return True
    for part in address.split(";"):
        if part.startswith("unix:") and ("abstract=" not in part):
            for kv in part[5:].split(","):
                if kv.startswith("path="):
                    path = kv[5:]
                    real = os.path.realpath(path)
                    if path in _REAL_SYSTEM_SOCKETS or real in [os.path.realpath(p) for p in _REAL_SYSTEM_SOCKETS]:
                        return True
        elif part.startswith(("tcp:", "nonce-tcp:", "systemd:", "launchd:", "autolaunch:")):
            return True     # mimo soukromy soket testu neumime overit - radeji odmitnout
    return False


def is_real_video_dir(path):
    """Slozka s video* je skutecna /dev (nebo v ni lezi) -> testy by otevrely skutecnou kameru."""
    if not path:
        return True
    real = os.path.realpath(path)
    return real == "/dev" or real.startswith("/dev/")


def _is_camera_path(path):
    """/dev/video*, /dev/v4l/... (i pres symbolicky odkaz)"""
    if not isinstance(path, (str, bytes)):
        return False      # cislo deskriptoru
    path = os.fsdecode(path)
    for p in (path, os.path.realpath(path)):
        if re.match(r"/dev/(video\d*$|v4l/)", p):
            return True
    return False


def _block_camera(event, args):
    """Audit hook: proces testu nikdy neotevre skutecnou kameru."""
    if event == "open" and args and _is_camera_path(args[0]):
        raise PermissionError("luxos_testguard: tests must not open camera devices (%s); "
                              "use LUXOS_CAMERA_TEST / %s" % (args[0], _VIDEO_VAR))


def check_env(env):
    """Vyjimka, kdyz prostredi podprocesu miri do skutecne relace (obrazovka, sbernice, domov,
    systemova sbernice, kamera)."""
    problems = []
    if "DBUS_SYSTEM_BUS_ADDRESS" in env and is_real_system_bus(env["DBUS_SYSTEM_BUS_ADDRESS"]):
        problems.append("DBUS_SYSTEM_BUS_ADDRESS=%s is the real system bus" % env["DBUS_SYSTEM_BUS_ADDRESS"])
    if _VIDEO_VAR in env and is_real_video_dir(env[_VIDEO_VAR]):
        problems.append("%s=%s would open real cameras" % (_VIDEO_VAR, env[_VIDEO_VAR]))
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
    # systemova sbernice: vzdy mrtvy soket, jen schvalena falesna sbernice testu projde
    fake = env.get(_SYSTEM_BUS_VAR, "")
    if fake and not is_real_system_bus(fake):
        env["DBUS_SYSTEM_BUS_ADDRESS"] = fake
    else:
        env.pop(_SYSTEM_BUS_VAR, None)
        env["DBUS_SYSTEM_BUS_ADDRESS"] = "unix:path=" + os.path.join(_private_dir(), "no-system-bus")
    # kamery: prazdna slozka misto /dev (aplikace hledaji $LUXOS_VIDEO_DEV_DIR/video*)
    video = os.path.join(_private_dir(), "no-cameras")
    os.makedirs(video, exist_ok=True)
    env[_VIDEO_VAR] = video
    check_env(env)


atexit.register(_cleanup)
protect()
try:
    import sys as _sys
    _sys.addaudithook(_block_camera)
except AttributeError:      # Python < 3.8
    pass
