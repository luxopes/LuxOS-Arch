#!/usr/bin/env python3
"""LuxOS - zamykaci obrazovka (xfce4-screensaver-dialog) a Caps Lock / rozlozeni / probuzeni, v Xvfb.

    gcc -shared -fPIC -o fake-pam.so packages/xfce4-screensaver/tests/fake-pam.c
    python3 packages/xfce4-screensaver/tests/gui-caps-lock.py \\
        --dialog BUILD/src/xfce4-screensaver-dialog --fake-pam fake-pam.so [--shots DIR] \\
        [--daemon PREFIX/bin/xfce4-screensaver --command PREFIX/bin/xfce4-screensaver-command]

Spousti vlastni Xvfb (nikdy :0), vlastni session D-Bus, docasny HOME a vsechny XDG_* v docasnem
adresari (XDG_RUNTIME_DIR 700), bez systemoveho D-Bus (zadny logind, zadne inhibitory) a s
napodobenym libpam (fake-pam.so, heslo "luxos") - skutecne heslo ani pam_faillock se nepouziji.
Docasne soubory jsou v LUXOS_TEST_TMP (vychozi: out/ repozitare), nikdy v /tmp.

Overuje (samostatny dialog):
  - Caps Lock zapnuty uz pri zobrazeni dialogu (jako po otevreni vika) -> radek "Caps Lock is on"
  - spatne heslo s Caps Lockem -> "Incorrect password – Caps Lock is on", radek Caps Lock zustava
    i po zacatku psani (driv po chybe zmizel a uz se neukazal)
  - vypnuti / zapnuti Caps Locku se projevi hned; spatne heslo bez nej -> "Incorrect password. Try again."
  - dve rozlozeni (us,cz): rozlozeni pod polem, prepnuti zkratkou X (obe klavesy Shift) hned a
    kliknutim na rozlozeni; s jednim rozlozenim se pod polem neukazuje
  - probuzeni z uspani s otevrenym dialogem: rozepsane heslo a stara chyba zmizi, novy znak zustane
  - spravne heslo odemkne
S --daemon navic cely xfce4-screensaver: zamknout, probudit klavesou a hned psat heslo (16+ klaves
vcetne Shiftu, driv se fronta 16 udalosti uriznula), odemknuti.
"""
import argparse
import ctypes
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
REAL_HOME = os.path.expanduser("~")
FAILS = []
CAPS_FAIL = "Incorrect password – Caps Lock is on"
PLAIN_FAIL = "Incorrect password. Try again."


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        FAILS.append(what)


class XKB:
    """Klavesnice docasneho displeje pres libX11/libXtst: Caps Lock a rozlozeni jako skutecne klavesy
    (XTest). "xdotool key Caps_Lock" v Xvfb Caps Lock nezamkne a setxkbmap v Xvfb bez zapisovatelneho
    adresare pro prelozene mapy nic nezmeni - mapa se proto nahraje pres xkbcomp a nazvy rozlozeni
    (_XKB_RULES_NAMES, odtud je cte libxklavier) se zapisi primo."""

    def __init__(self, display):
        x = self.x = ctypes.CDLL("libX11.so.6")
        self.xt = ctypes.CDLL("libXtst.so.6")
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XStringToKeysym.restype = ctypes.c_ulong
        x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x.XInternAtom.restype = ctypes.c_ulong
        x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x.XDefaultRootWindow.restype = ctypes.c_ulong
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x.XkbGetState.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
        x.XkbLockGroup.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        self.xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.d = x.XOpenDisplay(display.encode())
        if not self.d:
            sys.exit("cannot open the test display")
        i = [ctypes.c_int() for _ in range(5)]
        i[3].value, i[4].value = 1, 0
        x.XkbQueryExtension(ctypes.c_void_p(self.d), *[ctypes.byref(v) for v in i])

    def state(self):
        st = (ctypes.c_ubyte * 32)()
        self.x.XkbGetState(self.d, 0x100, st)
        return st[0], st[9]              # group, locked_mods (XkbStateRec)

    def caps(self):
        return bool(self.state()[1] & 2)

    def keycode(self, name):
        return self.x.XKeysymToKeycode(self.d, self.x.XStringToKeysym(name.encode()))

    def key(self, *names):
        """Stisk (a pusteni v obracenem poradi) jako na skutecne klavesnici."""
        codes = [self.keycode(n) for n in names]
        for c in codes:
            self.xt.XTestFakeKeyEvent(self.d, c, 1, 0)
        for c in reversed(codes):
            self.xt.XTestFakeKeyEvent(self.d, c, 0, 0)
        self.x.XSync(self.d, 0)

    def set_layouts(self, env, layouts, options):
        keymap = env.run(["setxkbmap", "-layout", layouts, "-option", "", "-option", options, "-print"]).stdout
        subprocess.run(["xkbcomp", "-w", "0", "-", env.env["DISPLAY"]], input=keymap, text=True, env=env.env,
                       check=False, capture_output=True)
        names = b"\0".join([b"evdev", b"pc105", layouts.encode(), b"", options.encode()]) + b"\0"
        atom = self.x.XInternAtom(self.d, b"_XKB_RULES_NAMES", 0)
        self.x.XChangeProperty(self.d, self.x.XDefaultRootWindow(self.d), atom, 31, 8, 0, names, len(names))
        self.x.XkbLockGroup(self.d, 0x100, 0)
        self.x.XSync(self.d, 0)


class Env:
    """Docasne prostredi: Xvfb, D-Bus, HOME a XDG_* - nic ze skutecne relace."""

    def __init__(self, base, layouts):
        self.dir = tempfile.mkdtemp(prefix="caps-lock-test-", dir=base)
        self.procs = []
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("XDG_", "DBUS_", "DISPLAY", "WAYLAND", "XAUTHORITY", "SESSION_MANAGER",
                                    "GNOME_", "XFCE", "DESKTOP_SESSION", "LD_PRELOAD", "LUXOS_"))}
        home = os.path.join(self.dir, "home")
        run = os.path.join(self.dir, "run")
        for d in (home, run):
            os.makedirs(d)
        os.chmod(run, 0o700)
        env.update({
            "HOME": home, "XDG_RUNTIME_DIR": run,
            "XDG_CONFIG_HOME": os.path.join(home, ".config"), "XDG_DATA_HOME": os.path.join(home, ".local/share"),
            "XDG_CACHE_HOME": os.path.join(home, ".cache"), "XDG_STATE_HOME": os.path.join(home, ".local/state"),
            "XDG_DATA_DIRS": "/usr/local/share:/usr/share", "XDG_CONFIG_DIRS": "/etc/xdg",
            "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=" + os.path.join(run, "no-system-bus"),
            "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "NO_AT_BRIDGE": "1", "GTK_A11Y": "none",
            "TMPDIR": self.dir,
        })
        for k, v in env.items():
            if k.startswith("XDG_") and k not in ("XDG_DATA_DIRS", "XDG_CONFIG_DIRS"):
                if not os.path.realpath(v).startswith(os.path.realpath(self.dir) + os.sep):
                    sys.exit(f"refusing: {k}={v} is outside the test directory")
                if os.path.realpath(v).startswith(os.path.join(REAL_HOME, ".")):
                    sys.exit(f"refusing: {k}={v} points into the real home configuration")
        os.makedirs(env["XDG_CONFIG_HOME"])
        self.env = env
        # Xvfb s volnym cislem displeje
        r, w = os.pipe()
        xvfb = subprocess.Popen(["Xvfb", "-displayfd", str(w), "-screen", "0", "1280x800x24", "-nolisten", "tcp",
                                 "+extension", "XKEYBOARD"], pass_fds=(w,), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(w)
        self.procs.append(xvfb)
        num = b""
        while not num.endswith(b"\n"):
            if not select.select([r], [], [], 10)[0]:
                sys.exit("Xvfb did not start")
            num += os.read(r, 16)
        os.close(r)
        disp = ":" + num.decode().strip()
        if disp in (":0", ":0.0") or disp == os.environ.get("DISPLAY"):
            sys.exit(f"refusing to use display {disp}")
        env["DISPLAY"] = disp
        # vlastni session D-Bus (xfconfd se spusti sam, s konfiguraci v docasnem HOME)
        r, w = os.pipe()
        dbus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=" + str(w)],
                                pass_fds=(w,), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(w)
        self.procs.append(dbus)
        addr = b""
        while not addr.endswith(b"\n"):
            if not select.select([r], [], [], 10)[0]:
                sys.exit("dbus-daemon did not start")
            addr += os.read(r, 256)
        os.close(r)
        env["DBUS_SESSION_BUS_ADDRESS"] = addr.decode().strip()
        self.xkb = XKB(disp)
        self.xkb.set_layouts(self, layouts, "grp:shifts_toggle")
        print(f"# Xvfb {disp}, temp {self.dir}", flush=True)

    def run(self, cmd, **kw):
        return subprocess.run(cmd, env=self.env, check=False, capture_output=True, text=True, **kw)

    def wallpaper(self, path):
        self.run(["xfconf-query", "-c", "xfce4-desktop", "-p", "/backdrop/screen0/monitor0/workspace0/last-image",
                  "-n", "-t", "string", "-s", path])

    def set_caps(self, on):
        if self.xkb.caps() != on:
            self.xkb.key("Caps_Lock")
        time.sleep(0.15)

    def close(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(3)
                except subprocess.TimeoutExpired:
                    p.kill()
        shutil.rmtree(self.dir, ignore_errors=True)


# okno s GtkSocket jako okno xfce4-screensaver (gs-window): dialog (GtkPlug) se do nej vlozi, klavesy
# jdou do hostitele a ten je posila dialogu (XEmbed) - stejne jako pri skutecnem zamceni
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
    print("HOST", w.get_window().get_xid(), flush=True)
    return False
GLib.timeout_add(200, focus)
Gtk.main()
"""


class Dialog:
    """xfce4-screensaver-dialog vlozeny do okna s GtkSocket (jako v xfce4-screensaver)."""

    def __init__(self, env, path, fake_pam, extra_env=None):
        e = dict(env.env, LD_PRELOAD=fake_pam, LUXOS_LOCK_DEBUG="1", LUXOS_LOCK_DEMO_USERS="1",
                 LUXOS_LOCK_DEMO_NAME="Test User", LUXOS_GREETER_CONF="/nonexistent",
                 LUXOS_I18N_DIR=os.path.join(REPO, "packages", "luxos-i18n", "files"))
        e.update(extra_env or {})
        self.env = env
        self.lines = []
        self.out = []
        self.p = subprocess.Popen([path, "--width", "1280", "--height", "800"], env=e, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, bufsize=1)
        os.set_blocking(self.p.stdout.fileno(), False)
        os.set_blocking(self.p.stderr.fileno(), False)
        self.wid = None
        t0 = time.time()
        while time.time() - t0 < 15 and not self.wid:
            self.pump(0.1)
            for l in self.out:
                if l.startswith("WINDOW ID="):
                    self.wid = l.split("=", 1)[1].strip()
        self.host = None
        if self.wid:
            self.host = subprocess.Popen([sys.executable, "-c", HOST, self.wid, "1280", "800"], env=env.env,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.wait_state(lambda s: s.get("focus") == "1", 5)

    def pump(self, t=0.05):
        end = time.time() + t
        while True:
            for f, dest in ((self.p.stderr, self.lines), (self.p.stdout, self.out)):
                try:
                    data = f.read()
                except (OSError, ValueError):
                    data = None
                if data:
                    dest.extend(data.splitlines())
            if time.time() >= end:
                return
            time.sleep(0.02)

    def state(self):
        self.pump()
        for l in reversed(self.lines):
            m = re.match(r"luxos-lock: (\S+) caps=(\d) layout=(.*?) chip=(\d) hint=\[(.*)\] error=(\d) focus=(\d) "
                         r"text=(\d+)", l)
            if m:
                return dict(zip(("why", "caps", "layout", "chip", "hint", "error", "focus", "text"), m.groups()))
        return {}

    def wait_state(self, pred, timeout=3.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            s = self.state()
            if s and pred(s):
                return s, time.time() - t0
            time.sleep(0.03)
        return self.state(), None

    def type(self, text):
        self.env.run(["xdotool", "type", "--delay", "25", text])

    def key(self, *keys):
        self.env.run(["xdotool", "key", "--delay", "40", *keys])

    def clear(self):
        self.key("ctrl+a", "BackSpace")

    def alive(self):
        return self.p.poll() is None

    def close(self):
        for p in (self.p, self.host):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(3)
                except subprocess.TimeoutExpired:
                    p.kill()


def shot(env, path):
    """Snimek obrazovky Xvfb (GDK na docasnem displeji)."""
    code = ("import sys,gi; gi.require_version('Gdk','3.0'); from gi.repository import Gdk;"
            "w=Gdk.get_default_root_window(); "
            "Gdk.pixbuf_get_from_window(w,0,0,w.get_width(),w.get_height()).savev(sys.argv[1],'png',[],[])")
    r = env.run([sys.executable, "-c", code, path])
    check(r.returncode == 0 and os.path.exists(path), f"screenshot {os.path.basename(path)} {r.stderr[-300:]}")


def test_dialog(args, base):
    env = Env(base, "us,cz")
    try:
        env.wallpaper("/usr/share/backgrounds/luxos/luxos-dark.jpg")
        # jako po otevreni vika: Caps Lock zapnuty uz pred zobrazenim dialogu
        env.set_caps(True)
        d = Dialog(env, args.dialog, args.fake_pam)
        check(d.wid is not None, "dialog window shown")
        s, _t = d.wait_state(lambda s: s.get("caps") == "1", 3)
        check(s.get("caps") == "1", "Caps Lock on when the dialog appears -> warning shown")
        check(s.get("chip") == "1" and s.get("layout") == "US", f"two layouts: layout under the field (US): {s}")
        check(s.get("focus") == "1", "password field focused right away")
        if args.shots:
            time.sleep(0.8)
            shot(env, os.path.join(args.shots, "lock-caps-on-dark.png"))

        # spatne heslo s Caps Lockem ("luxos" se napise jako "LUXOS")
        d.type("luxos")
        d.key("Return")
        s, _t = d.wait_state(lambda s: s.get("error") == "1", 4)
        check(s.get("hint") == CAPS_FAIL, f"failed attempt with Caps Lock: '{s.get('hint')}'")
        check(s.get("caps") == "1", "Caps Lock warning still shown after the failed attempt")
        if args.shots:
            time.sleep(0.7)
            shot(env, os.path.join(args.shots, "lock-wrong-caps-dark.png"))
        # zacatek psani smaze chybu, ale Caps Lock zustava videt (driv uz se neukazal)
        time.sleep(3.2)                  # dialog je po chybe 3 s neaktivni (xfce4-screensaver)
        d.type("x")
        s, _t = d.wait_state(lambda s: s.get("text") == "1" and s.get("hint") == "", 3)
        check(s.get("hint") == "" and s.get("caps") == "1",
              f"typing after the error: error cleared, Caps Lock still shown: {s}")

        # vypnuti Caps Locku hned (bez cekani na sekundovy casovac)
        env.xkb.key("Caps_Lock")
        s, t = d.wait_state(lambda s: s.get("caps") == "0", 2)
        check(s.get("caps") == "0" and t is not None and t < 0.7, f"Caps Lock off -> warning hidden at once ({t})")
        env.xkb.key("Caps_Lock")
        s, t = d.wait_state(lambda s: s.get("caps") == "1", 2)
        check(t is not None and t < 0.7, f"Caps Lock on again -> warning at once ({t})")
        env.xkb.key("Caps_Lock")
        d.wait_state(lambda s: s.get("caps") == "0", 2)

        # spatne heslo bez Caps Locku
        d.clear()
        d.type("nope")
        d.key("Return")
        s, _t = d.wait_state(lambda s: s.get("error") == "1", 4)
        check(s.get("hint") == PLAIN_FAIL, f"failed attempt without Caps Lock: '{s.get('hint')}'")
        time.sleep(3.2)

        # rozlozeni: zkratka X (obe klavesy Shift) a kliknuti na rozlozeni pod polem
        env.xkb.key("Shift_L", "Shift_R")
        check(env.xkb.state()[0] == 1, "X server switched to the second layout (both Shift keys)")
        s, t = d.wait_state(lambda s: s.get("layout") == "CZ", 2)
        check(t is not None and t < 0.7, f"layout switched by the X shortcut shown at once: {s.get('layout')} ({t})")
        if args.shots:
            time.sleep(0.5)
            shot(env, os.path.join(args.shots, "lock-layout-cz-dark.png"))
        click_chip(env, d)
        s, t = d.wait_state(lambda s: s.get("layout") == "US", 2)
        check(t is not None, f"click on the layout under the field switches back: {s.get('layout')}")
        check(s.get("focus") == "1", "password field keeps focus after switching layout")

        # probuzeni z uspani s otevrenym dialogem: rozepsane heslo a chyba z doby pred uspanim pryc
        d.clear()
        d.type("abc")
        s, _t = d.wait_state(lambda s: s.get("text") == "3", 2)
        d.p.send_signal(signal.SIGUSR1)
        time.sleep(0.1)
        d.type("l")
        s, _t = d.wait_state(lambda s: s.get("why") in ("resume", "hint") or s.get("text") == "1", 2)
        resumed = any(l.startswith("luxos-lock: resume") for l in d.lines)
        s, _t = d.wait_state(lambda s: s.get("text") == "1", 2)
        check(resumed and s.get("text") == "1", f"after sleep: old text dropped, new key kept: {s}")

        # spravne heslo odemkne
        d.type("uxos")
        d.key("Return")
        t0 = time.time()
        while d.alive() and time.time() - t0 < 6:
            d.pump(0.1)
        d.pump(0.2)
        check(not d.alive() and any("RESPONSE=OK" in l for l in d.out), "correct password unlocks")
        d.close()

        # svetla tapeta, Caps Lock a chyba
        env.wallpaper("/usr/share/backgrounds/luxos/luxos-light.jpg")
        env.set_caps(True)
        d = Dialog(env, args.dialog, args.fake_pam)
        d.type("luxos")
        d.key("Return")
        s, _t = d.wait_state(lambda s: s.get("error") == "1", 4)
        check(s.get("hint") == CAPS_FAIL, "light wallpaper: failed attempt with Caps Lock")
        if args.shots:
            time.sleep(0.7)
            shot(env, os.path.join(args.shots, "lock-wrong-caps-light.png"))
        d.close()
        env.set_caps(False)
        # cestina: preklady novych textu
        d = Dialog(env, args.dialog, args.fake_pam, {"LANG": "cs_CZ.UTF-8", "LC_ALL": "cs_CZ.UTF-8"})
        env.set_caps(True)
        s, _t = d.wait_state(lambda s: s.get("caps") == "1", 2)
        d.type("luxos")
        d.key("Return")
        s, _t = d.wait_state(lambda s: s.get("error") == "1", 4)
        check(s.get("hint") == "Nesprávné heslo – je zapnutý Caps Lock", f"Czech failed text: '{s.get('hint')}'")
        if args.shots:
            time.sleep(0.7)
            shot(env, os.path.join(args.shots, "lock-wrong-caps-light-cs.png"))
        d.close()
        env.set_caps(False)
    finally:
        env.close()

    # jedno rozlozeni: pod polem nic
    env = Env(base, "us")
    try:
        d = Dialog(env, args.dialog, args.fake_pam)
        s, _t = d.wait_state(lambda s: s.get("focus") == "1", 3)
        check(s.get("chip") == "0" and s.get("caps") == "0", f"one layout, Caps Lock off: nothing under the field: {s}")
        d.close()
    finally:
        env.close()


def click_chip(env, d):
    """Kliknout na rozlozeni pod polem: pozice z ATK neni, proto hledame stitek na snimku nebo
    pouzijeme klavesovou cestu - kliknuti v ose pod polem (rozlozeni je vpravo od stredu)."""
    # radek pod polem: vyska 800 -> u = 0.74; stred x 640; radek ~ y = 800 - 111 - (24+14+22)*u
    for x, y in ((640, 655), (640, 650), (640, 660), (650, 655), (630, 655)):
        env.run(["xdotool", "mousemove", str(x), str(y), "click", "1"])
        s, t = d.wait_state(lambda s: s.get("layout") == "US", 0.4)
        if t is not None:
            return


def test_daemon(args, base):
    """Cely xfce4-screensaver: zamknout, probudit klavesou a hned psat (pred zobrazenim dialogu)."""
    env = Env(base, "us,cz")
    daemon = None
    try:
        env.wallpaper("/usr/share/backgrounds/luxos/luxos-dark.jpg")
        for prop, typ, val in (("/lock/enabled", "bool", "true"), ("/saver/enabled", "bool", "true"),
                               ("/saver/mode", "int", "0"), ("/lock/saver-activation/enabled", "bool", "true")):
            env.run(["xfconf-query", "-c", "xfce4-screensaver", "-p", prop, "-n", "-t", typ, "-s", val])
        pw = "LuxOS-Test-Password-123"
        pamlog = os.path.join(env.dir, "pam.log")
        e = dict(env.env, LD_PRELOAD=args.fake_pam, LUXOS_LOCK_DEBUG="1", LUXOS_LOCK_DEMO_USERS="1",
                 LUXOS_GREETER_CONF="/nonexistent", LUXOS_FAKE_PAM_PASSWORD=pw, LUXOS_FAKE_PAM_LOG=pamlog)
        log = open(os.path.join(env.dir, "daemon.log"), "w")
        daemon = subprocess.Popen([args.daemon, "--debug"], env=e, stdout=log, stderr=log)
        time.sleep(1.5)
        cmd = [args.command]
        r = env.run(cmd + ["--lock"])
        check(r.returncode == 0, f"lock via private D-Bus ({r.stderr.strip()})")
        if r.returncode != 0:
            log.flush()
            print("".join(open(log.name, encoding="utf-8", errors="replace").readlines()[-25:]))
        time.sleep(1.5)
        r = env.run(cmd + ["--query"])
        check("is active" in r.stdout, f"locked: {r.stdout.strip()}")
        # probudit a hned psat dlouhe heslo s velkymi pismeny (Shift = dalsi udalosti)
        env.run(["xdotool", "type", "--delay", "8", pw])
        env.run(["xdotool", "key", "Return"])
        t0 = time.time()
        while time.time() - t0 < 12:
            if "is active" not in env.run(cmd + ["--query"]).stdout:
                break
            time.sleep(0.3)
        r = env.run(cmd + ["--query"])
        got = open(pamlog, encoding="utf-8").read().splitlines() if os.path.exists(pamlog) else []
        check("is inactive" in r.stdout and got[:1] == [pw],
              f"password typed right after waking (before the dialog) unlocks: {r.stdout.strip()!r}, PAM got {got}")
    finally:
        if daemon and daemon.poll() is None:
            daemon.terminate()
            try:
                daemon.wait(3)
            except subprocess.TimeoutExpired:
                daemon.kill()
        if FAILS and os.path.exists(os.path.join(env.dir, "daemon.log")):
            shutil.copy(os.path.join(env.dir, "daemon.log"), os.path.join(base, "daemon-last.log"))
            print("# daemon log:", os.path.join(base, "daemon-last.log"))
        env.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialog", required=True)
    ap.add_argument("--fake-pam", required=True)
    ap.add_argument("--daemon")
    ap.add_argument("--command")
    ap.add_argument("--shots")
    ap.add_argument("--only", choices=("dialog", "daemon"))
    args = ap.parse_args()
    args.fake_pam = os.path.abspath(args.fake_pam)
    base = os.environ.get("LUXOS_TEST_TMP") or os.path.join(REPO, "out")
    os.makedirs(base, exist_ok=True)
    if os.path.realpath(base).startswith("/tmp"):
        sys.exit("refusing: temporary files must not be in /tmp")
    if args.shots:
        os.makedirs(args.shots, exist_ok=True)
    if args.only != "daemon":
        test_dialog(args, base)
    if args.daemon and args.only != "dialog":
        test_daemon(args, base)
    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
