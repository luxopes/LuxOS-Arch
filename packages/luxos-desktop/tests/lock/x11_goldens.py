#!/usr/bin/env python3
"""Snimky X11 zamku (xfce4-screensaver-dialog s luxos-lock-ui.c) a X11 prihlaseni (luxos-greeter --demo) jako vzory
pro Wayland (tests/test_luxos_lock_x11_match.py). Kazdy stav ve vlastnim Xvfb, s pevnymi hodinami a rizenym monotonnim
casem (tests/lock/x11-fake.c), takze animace (prichod, zatreseni, kurzor) stoji presne tam, kde je test chce.

    gcc -shared -fPIC -O2 -o out/x11-fake.so packages/luxos-desktop/tests/lock/x11-fake.c -ldl
    scripts/wl-test/isolate python3 packages/luxos-desktop/tests/lock/x11_goldens.py \\
        --dialog BUILD/src/xfce4-screensaver-dialog --fake out/x11-fake.so --out DIR \\
        [--size 1280x800] [--scale 1] [--lang cs] [--theme light] [--wallpaper light=PATH] [STAV...]

Stavy: idle prompt typing wrong caps fingerprint lockout battery layout power enter-50 shake (zamek) a greeter
greeter-wrong greeter-users (prihlaseni). Vystup DIR/<lang>-<theme>-<W>x<H>@<scale>/<stav>.png v pixelech zarizeni.
Jen v izolovanem prostredi (scripts/wl-test/isolate): vlastni Xvfb, D-Bus, HOME; nikdy displej :0.
"""
import argparse
import ctypes
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
GREETER = os.path.join(REPO, "packages", "luxos-greeter", "files", "luxos-greeter")
I18N = os.path.join(REPO, "packages", "luxos-i18n", "files")
XSETTINGS = os.path.join(REPO, "packages", "luxos-desktop", "files", "xdg", "xfce4", "xfconf", "xfce-perchannel-xml",
                         "xsettings.xml")
EPOCH = 1795167660          # patek 20. 11. 2026 9:41 UTC
NAME = "Alex Novák"
LOCK_STATES = ["idle", "prompt", "typing", "wrong", "caps", "fingerprint", "lockout", "battery", "layout", "power",
               "enter-50", "shake"]
GREETER_STATES = ["greeter", "greeter-wrong", "greeter-users"]
FP_INFO = "Place your finger on the fingerprint reader"
LOCKED = "The account is locked due to 3 failed logins. (1 minute left to unlock)"

HOST = r"""
import sys, gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
w = Gtk.Window()
w.set_decorated(False)
w.move(0, 0)
w.set_default_size(int(sys.argv[2]), int(sys.argv[3]))
s = Gtk.Socket()
w.add(s)
w.show_all()
s.add_id(int(sys.argv[1]))
s.connect("plug-removed", lambda *a: Gtk.main_quit() or False)
def focus():
    w.get_window().focus(Gdk.CURRENT_TIME)
    s.child_focus(Gtk.DirectionType.TAB_FORWARD)
    return False
GLib.timeout_add(200, focus)
Gtk.main()
"""

SHOT = ("import sys,gi; gi.require_version('Gdk','3.0'); from gi.repository import Gdk;"
        "w=Gdk.get_default_root_window(); "
        "Gdk.pixbuf_get_from_window(w,0,0,w.get_width(),w.get_height()).savev(sys.argv[1],'png',[],[])")


def wait_fd(fd, what):
    data = b""
    while not data.endswith(b"\n"):
        if not select.select([fd], [], [], 15)[0]:
            sys.exit(what + " did not start")
        data += os.read(fd, 256)
    os.close(fd)
    return data.decode().strip()


def rules_names(disp, layouts):
    """Nazvy rozlozeni na korenovem okne (_XKB_RULES_NAMES, odtud je cte libxklavier); setxkbmap v Xvfb bez
    zapisovatelneho adresare map nic nezmeni, mapa se proto nahrava pres xkbcomp."""
    x = ctypes.CDLL("libX11.so.6")
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XInternAtom.restype = ctypes.c_ulong
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    d = x.XOpenDisplay(disp.encode())
    names = b"\0".join([b"evdev", b"pc105", layouts.encode(), b"", b""]) + b"\0"
    x.XChangeProperty(d, x.XDefaultRootWindow(d), x.XInternAtom(d, b"_XKB_RULES_NAMES", 0), 31, 8, 0, names, len(names))
    x.XCloseDisplay(d)


class Env:
    """Xvfb, D-Bus a HOME jen pro jeden stav."""

    def __init__(self, base, size, scale, lang, wallpaper, layouts, xsettings):
        self.dir = tempfile.mkdtemp(prefix="x11-golden-", dir=base)
        self.procs = []
        home = os.path.join(self.dir, "home")
        run = os.path.join(self.dir, "run")
        for d in (home, run, os.path.join(self.dir, "ps"), os.path.join(self.dir, "net")):
            os.makedirs(d)
        os.chmod(run, 0o700)
        loc = "cs_CZ.UTF-8" if lang == "cs" else "en_US.UTF-8"
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "USER", "LOGNAME", "SHELL", "TERM")}
        env.update({
            "HOME": home, "XDG_RUNTIME_DIR": run, "XDG_CONFIG_HOME": os.path.join(home, ".config"),
            "XDG_DATA_HOME": os.path.join(home, ".local/share"), "XDG_CACHE_HOME": os.path.join(home, ".cache"),
            "XDG_DATA_DIRS": "/usr/local/share:/usr/share", "XDG_CONFIG_DIRS": "/etc/xdg",
            "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=" + os.path.join(run, "no-system-bus"),
            "LANG": loc, "LC_ALL": loc, "LANGUAGE": lang, "NO_AT_BRIDGE": "1", "GTK_A11Y": "none", "TMPDIR": self.dir,
            "TZ": "UTC",
        })
        # xsettings skutecne relace (xfsettingsd s xsettings.xml z luxos-desktop): pisma Xft hintslight + rgb
        xml = os.path.join(env["XDG_CONFIG_HOME"], "xfce4", "xfconf", "xfce-perchannel-xml")
        os.makedirs(xml)
        shutil.copy(XSETTINGS, xml)
        self.env = env
        self.W, self.H, self.scale = size[0], size[1], scale
        self.wallpaper = wallpaper
        # displej od :90 (nikdy :0 ani :1 z isolate)
        num = next(n for n in range(90, 200) if not os.path.exists(f"/tmp/.X{n}-lock"))
        disp = f":{num}"
        self.procs.append(subprocess.Popen(
            ["Xvfb", disp, "-screen", "0", f"{size[0] * scale}x{size[1] * scale}x24", "-nolisten", "tcp",
             "-dpi", str(96 * scale), "+extension", "XKEYBOARD"], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        for _ in range(200):
            if os.path.exists(f"/tmp/.X11-unix/X{num}"):
                break
            time.sleep(0.025)
        else:
            sys.exit("Xvfb did not start")
        env["DISPLAY"] = disp
        r, w = os.pipe()
        self.procs.append(subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=" + str(w)],
                                           pass_fds=(w,), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        os.close(w)
        env["DBUS_SESSION_BUS_ADDRESS"] = wait_fd(r, "dbus-daemon")
        # pisma jako skutecna relace LuxOS (xsettings.xml: Xft hintslight, rgb; xfsettingsd je zapise i do
        # prostredku X, odkud je cte cairo pro okna)
        self.run(["xrdb", "-nocpp", "-merge", "-"], input="Xft.antialias: 1\nXft.hinting: 1\nXft.hintstyle: hintslight\n"
                 "Xft.rgba: rgb\nXft.lcdfilter: lcddefault\n")
        self.run(["xfconf-query", "-c", "xfce4-desktop", "-p", "/backdrop/screen0/monitor0/workspace0/last-image",
                  "-n", "-t", "string", "-s", wallpaper])
        # prihlaseni (LightDM) bezi bez xfsettingsd, zamek v relaci s nim
        if xsettings:
            self.procs.append(subprocess.Popen(["xfsettingsd", "--disable-wm-check"], env=env, stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL))
            time.sleep(0.8)
        # rozlozeni az po xfsettingsd (ten pri startu nastavuje klavesnici)
        keymap = self.run(["setxkbmap", "-layout", layouts, "-option", "", "-print"]).stdout
        subprocess.run(["xkbcomp", "-w", "0", "-", disp], input=keymap, text=True, env=env, capture_output=True)
        rules_names(disp, layouts)
        self.mono = os.path.join(self.dir, "mono")
        self.t = 0
        self.set_mono(0)

    def run(self, cmd, **kw):
        return subprocess.run(cmd, env=self.env, check=False, capture_output=True, text=True, **kw)

    def set_mono(self, us):
        self.t = us
        with open(self.mono + ".new", "w") as f:
            f.write(str(us))
        os.replace(self.mono + ".new", self.mono)

    def advance(self, ms, step=8):
        """Monotonni cas po krocich (casovace GLib se nedohani: kazdy krok jedno kolo smycky)."""
        end = self.t + ms * 1000
        while self.t < end:
            self.set_mono(min(end, self.t + step * 1000))
            time.sleep(0.012)

    def power_supply(self, level, charging):
        for name, files in (("AC", {"type": "Mains", "online": "1" if charging else "0"}),
                            ("BAT0", {"type": "Battery", "scope": "System", "capacity": str(level),
                                      "status": "Charging" if charging else "Discharging"})):
            d = os.path.join(self.dir, "ps", name)
            os.makedirs(d, exist_ok=True)
            for k, v in files.items():
                with open(os.path.join(d, k), "w") as f:
                    f.write(v + "\n")

    def wifi(self):
        d = os.path.join(self.dir, "net", "wlan0")
        os.makedirs(os.path.join(d, "wireless"))
        os.makedirs(os.path.join(d, "device"))
        with open(os.path.join(d, "operstate"), "w") as f:
            f.write("up\n")

    def key(self, *keys):
        self.run(["xdotool", "key", "--delay", "30", *keys])

    def type(self, text):
        self.run(["xdotool", "type", "--delay", "30", text])

    def shot(self, path):
        e = {k: v for k, v in self.env.items() if not k.startswith("GDK_")}
        r = subprocess.run([sys.executable, "-c", SHOT, path], env=e, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("screenshot failed: " + r.stderr[-300:])

    def close(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(3)
                except subprocess.TimeoutExpired:
                    p.kill()
        shutil.rmtree(self.dir, ignore_errors=True)


def spawn(env, cmd, extra):
    e = dict(env.env, **extra)
    if env.scale != 1:
        e["GDK_SCALE"] = str(env.scale)
    p = subprocess.Popen(cmd, env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    env.procs.append(p)
    return p


def start_dialog(env, args, extra):
    e = {"LD_PRELOAD": args.fake, "LUXOS_FAKE_EPOCH": str(EPOCH), "LUXOS_FAKE_MONO": env.mono,
         "LUXOS_LOCK_DEMO_USERS": "1", "LUXOS_LOCK_DEMO_NAME": NAME, "LUXOS_GREETER_CONF": "/nonexistent",
         "LUXOS_I18N_DIR": I18N, "LUXOS_LOCK_DEMO_POWER_SUPPLY": os.path.join(env.dir, "ps"),
         "LUXOS_LOCK_DEMO_NET": os.path.join(env.dir, "net"), "LUXOS_LOCK_DEMO_FPRINT": "0", "LUXOS_LOCK_DEBUG": "1"}
    e.update(extra)
    p = spawn(env, [args.dialog, "--width", str(env.W), "--height", str(env.H)], e)
    os.set_blocking(p.stdout.fileno(), False)
    os.set_blocking(p.stderr.fileno(), False)
    wid, t0 = None, time.time()
    out = ""
    while time.time() - t0 < 15 and wid is None:
        time.sleep(0.05)
        try:
            out += p.stdout.read() or ""
        except BlockingIOError:
            pass
        for line in out.splitlines():
            if line.startswith("WINDOW ID="):
                wid = line.split("=", 1)[1].strip()
    if wid is None:
        sys.exit("dialog did not start: " + (p.stderr.read() or "")[-500:])
    host = spawn(env, [sys.executable, "-c", HOST, wid, str(env.W), str(env.H)], {})
    host.stdout.close()
    # okno, prvni vykresleni a zamereni pole (zamereni za 200 ms skutecneho casu)
    time.sleep(1.2)
    return p


def wait_error(env, dialog):
    err = ""
    for _ in range(300):
        try:
            err += dialog.stderr.read() or ""
        except BlockingIOError:
            pass
        if "error=1" in err:
            return
        env.advance(8, step=8)
    sys.exit("dialog did not report the failed attempt")


def lock_state(env, args, state, path):
    extra = {}
    if state == "fingerprint":
        extra = {"LUXOS_LOCK_DEMO_FPRINT": "1", "LUXOS_FAKE_PAM_INFO": FP_INFO, "LUXOS_FAKE_PAM_INFO_WAIT": "20"}
    elif state == "lockout":
        extra = {"LUXOS_FAKE_PAM_ERROR": LOCKED}
    elif state == "battery":
        env.power_supply(84, False)
        env.wifi()
    if state == "caps":
        env.key("Caps_Lock")
    dialog = start_dialog(env, args, extra)
    if state == "idle":
        env.shot(path)
        return
    if state == "enter-50":
        env.advance(190, step=190)          # prichod trva 380 ms: presne polovina
        time.sleep(0.4)
        env.shot(path)
        return
    env.advance(500)
    if state == "typing":
        env.type("tajne12")
        env.advance(300)
    elif state in ("wrong", "lockout", "shake"):
        env.type("spatne")
        env.key("Return")
        # overeni: vlakno PAM ve skutecnem case, vysledek pres smycku -> posouvat cas, dokud neprijde chyba
        wait_error(env, dialog)
        if state == "shake":
            env.advance(30, step=30)        # zatreseni 480 ms: 30 ms (nejvetsi vychyleni)
            time.sleep(0.3)
            env.shot(path)
            return
        env.advance(1000)
    elif state == "caps":
        env.type("abc")
        env.advance(300)
    elif state == "layout":
        env.advance(300)
    elif state == "power":
        # mys nad Restartovat (prostredni tlacitko napajeni, svisle stred rady tlacitek)
        env.run(["xdotool", "mousemove", str(env.W * env.scale // 2), str(int(env.H * env.scale * 0.915))])
        env.advance(300)
    time.sleep(0.4)
    env.shot(path)


def greeter_state(env, args, state, path):
    users = "3" if state == "greeter-users" else "1"
    conf = os.path.join(env.dir, "greeter.conf")
    with open(conf, "w") as f:
        f.write(f"[greeter]\nbackground = {env.wallpaper}\nuser-background = false\n")
    e = {"LD_PRELOAD": args.fake, "LUXOS_FAKE_EPOCH": str(EPOCH), "LUXOS_FAKE_MONO": env.mono,
         "LUXOS_I18N_DIR": I18N, "LUXOS_GREETER_CONF": conf, "LUXOS_GREETER_KEYBOARD_CONF": "/nonexistent",
         "LUXOS_GREETER_DEMO_POWER_SUPPLY": os.path.join(env.dir, "ps"),
         "LUXOS_GREETER_DEMO_NET": os.path.join(env.dir, "net"), "LUXOS_GREETER_DEBUG": "1"}
    p = spawn(env, [sys.executable, GREETER, "--demo", "--users", users, "--sessions", "2"], e)
    os.set_blocking(p.stderr.fileno(), False)
    time.sleep(2.5)
    env.key("space")
    env.advance(600)
    env.key("BackSpace")
    env.advance(300)
    if state == "greeter-wrong":
        env.type("spatne")
        env.key("Return")
        err = ""
        for _ in range(400):
            try:
                err += p.stderr.read() or ""
            except BlockingIOError:
                pass
            if "complete" in err:
                break
            env.advance(8, step=8)
        env.advance(1000)
    time.sleep(0.4)
    env.shot(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialog", required=True)
    ap.add_argument("--fake", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="1280x800")
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--lang", default="cs")
    ap.add_argument("--theme", default="light")
    ap.add_argument("--wallpaper", action="append", default=[], help="light=PATH / dark=PATH")
    ap.add_argument("states", nargs="*")
    args = ap.parse_args()
    if not os.environ.get("ISOLATE_TMP") and os.getpid() != 1 and os.path.exists("/proc/1/cmdline"):
        if b"isolate" not in open("/proc/1/cmdline", "rb").read():
            sys.exit("run under scripts/wl-test/isolate")
    walls = {"light": "/usr/share/backgrounds/luxos/luxos-light.jpg", "dark": "/usr/share/backgrounds/luxos/luxos-dark.jpg"}
    for item in args.wallpaper:
        k, v = item.split("=", 1)
        walls[k] = os.path.abspath(v)
    size = tuple(int(v) for v in args.size.split("x"))
    out = os.path.join(args.out, f"{args.lang}-{args.theme}-{size[0]}x{size[1]}@{args.scale}")
    os.makedirs(out, exist_ok=True)
    base = os.path.join(args.out, "tmp")
    os.makedirs(base, exist_ok=True)
    for state in args.states or LOCK_STATES + GREETER_STATES:
        layouts = "us,cz" if state == "layout" else "us"
        env = Env(base, size, args.scale, args.lang, walls[args.theme], layouts, not state.startswith("greeter"))
        try:
            path = os.path.join(out, state + ".png")
            if state.startswith("greeter"):
                greeter_state(env, args, state, path)
            else:
                lock_state(env, args, state, path)
            print("shot", path, flush=True)
        finally:
            env.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
