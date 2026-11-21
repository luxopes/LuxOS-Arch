#!/usr/bin/env python3
"""LuxOS - okna Nastaveni se vejdou na male obrazovky a nejdou zmensit na nepouzitelnou velikost.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_window_fit.py -v

Kazda aplikace bezi ve vlastnim Xvfb 1366x768 a 1280x800 (nikdy na skutecne obrazovce), s mrtvou
systemovou sbernici a bez kamer (scripts/luxos_testguard.py) a jen v testovacich rezimech s vymyslenymi
daty (LUXOS_POWER_DEMO, LUXOS_MONITOR_DEMO, falesne nmcli/ip/ping). Sonda tests/fit-probe zmeri X okno
vcetne HeaderBar, okno pak zmensi na 100x100 a zmeri nejmensi dovolenou velikost.
Snimky obrazovky: LUXOS_FIT_SHOTS=<slozka>.
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(PKG, ".."))
BIN = os.path.join(PKG, "files", "bin")
PYDIR = os.path.join(PKG, "files", "python")
I18N = os.path.join(ROOT, "luxos-i18n", "files")
PROBE = os.path.join(HERE, "fit-probe")
FAKE_NET = os.path.join(HERE, "fake-net")
SCREENS = ((1366, 768), (1280, 800))
MIN_USABLE = 300      # okno nesmi jit zmensit pod tuto vysku (X okno vcetne HeaderBar)

NO_NET = {"routes": [], "device": "", "wifi": "", "neigh": [], "ping": {}}

# aplikace -> prostredi testovaciho rezimu (zadna nesaha na hardware ani systemove sluzby)
APPS = {
    "luxos-feedback": {},
    "luxos-monitor": {"LUXOS_MONITOR_DEMO": "1"},
    "luxos-router": {"LUXOS_IP": os.path.join(FAKE_NET, "ip"), "LUXOS_NMCLI": os.path.join(FAKE_NET, "nmcli"),
                     "LUXOS_PING": os.path.join(FAKE_NET, "ping"), "LUXOS_ROUTER_PORT": "9"},
    "luxos-display-settings": lambda tmp: displays_env(tmp),
}
FPRINTD = os.path.join(HERE, "fingerprint", "fake_fprintd.py")
APPS.update({
    "luxos-keyboard": {},
    "luxos-bluetooth": {"_sysbus": "1"},             # soukroma prazdna "systemova" sbernice: bez BlueZ
    "luxos-fingerprint": {"LUXOS_FPRINT_BUS": "session"},
    "luxos-profile-picture": {"LUXOS_CAMERA_TEST": "none"},
    "luxos-wifi-qr": {"LUXOS_CAMERA_TEST": "none", "LUXOS_NMCLI": "false"},
    "luxos-shortcuts": lambda tmp: {"LUXOS_XFCONF_QUERY": os.path.join(HERE, "fake-shortcuts", "xfconf-query"),
                                    "FAKE_XFCONF": os.path.join(tmp, "xfconf.json")},
})
PRE = {"luxos-fingerprint": [sys.executable, FPRINTD, "--enrolled", "right-index-finger"]}
LAPTOP = {"name": "eDP-1", "connected": True, "edid": "", "mm": [344, 194], "primary": True,
          "modes": [["1920x1080", ["60.02", "48.01"]], ["1280x720", ["60.00"]]], "preferred": ["1920x1080", "60.02"],
          "current": ["1920x1080", "60.02"], "rotation": "normal", "pos": [0, 0]}


def displays_env(tmp):
    """Monitory: falesny xrandr / xfconf-query / luxos-displays (tests/fake-displays), jeden displej notebooku."""
    fake = os.path.join(HERE, "fake-displays")
    state = os.path.join(tmp, "xrandr.json")
    with open(state, "w") as f:
        json.dump({"outputs": [LAPTOP]}, f)
    return {"PATH": fake + os.pathsep + os.environ["PATH"], "FAKE_XRANDR_STATE": state,
            "FAKE_XRANDR_LOG": os.path.join(tmp, "xrandr.log"), "FAKE_XFCONF": os.path.join(tmp, "xfconf.json")}


def free_display():
    for n in range(400, 500):
        if not os.path.exists("/tmp/.X11-unix/X%d" % n) and not os.path.exists("/tmp/.X%d-lock" % n):
            return n
    raise RuntimeError("no free display")


class Xvfb:
    def __init__(self, width, height):
        if not shutil.which("Xvfb"):
            raise unittest.SkipTest("Xvfb is not installed")
        self.n = free_display()
        self.proc = subprocess.Popen(["Xvfb", ":%d" % self.n, "-screen", "0", "%dx%dx24" % (width, height),
                                      "-nolisten", "tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(200):
            if os.path.exists("/tmp/.X11-unix/X%d" % self.n):
                break
            time.sleep(0.05)
        self.display = ":%d" % self.n
        luxos_testguard.check_env({"DISPLAY": self.display})

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def run_app(app, screen, extra=None, shot=None, hook=None, delay=2500):
    """Spusti aplikaci ze zdroju se sondou; vraci JSON sondy."""
    x = Xvfb(*screen)
    tmp = tempfile.mkdtemp(prefix="luxos-fit-", dir=luxos_testguard._private_dir())
    try:
        out = os.path.join(tmp, "fit.json")
        env = dict(os.environ)
        for k in ("DBUS_SESSION_BUS_ADDRESS",):
            env.pop(k, None)
        env.update({"DISPLAY": x.display, "HOME": os.path.join(tmp, "home"),
                    "XDG_CONFIG_HOME": os.path.join(tmp, "config"), "XDG_DATA_HOME": os.path.join(tmp, "data"),
                    "XDG_CACHE_HOME": os.path.join(tmp, "cache"), "XDG_RUNTIME_DIR": os.path.join(tmp, "run"),
                    "PYTHONPATH": ":".join((PROBE, PYDIR, I18N)), "LUXOS_FIT_PYDIR": ":".join((PYDIR, I18N)),
                    "LUXOS_PYDIR": PYDIR, "LUXOS_I18N_DIR": I18N, "LUXOS_FIT_OUT": out,
                    "LUXOS_FIT_DELAY": str(delay), "GTK_USE_PORTAL": "0", "NO_AT_BRIDGE": "1",
                    "GIO_USE_VFS": "local", "LANG": "cs_CZ.UTF-8", "LUXOS_NMCLI": "false"})
        os.makedirs(env["XDG_RUNTIME_DIR"], mode=0o700)
        os.makedirs(env["HOME"])
        net = os.path.join(tmp, "net.json")
        with open(net, "w") as f:
            json.dump(NO_NET, f)
        env["FAKE_NET"] = net
        conf = APPS.get(app, {})
        env.update(conf(tmp) if callable(conf) else conf)
        sysbus = None
        if env.pop("_sysbus", None):
            # soukroma prazdna sbernice misto systemove (jako scripts/check-titlebars.sh): okno nenajde
            # BlueZ ani jine sluzby pocitace
            sysbus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            env["DBUS_SYSTEM_BUS_ADDRESS"] = sysbus.stdout.readline().strip()
        env.update(extra or {})
        if shot:
            env["LUXOS_FIT_SHOT"] = shot
        if hook:
            env["LUXOS_FIT_HOOK"] = hook
        luxos_testguard.check_env(env)
        cmd = [sys.executable, os.path.join(BIN, app)]
        pre = PRE.get(app)
        if pre:
            # napodobena sluzba (fprintd) na session sbernici teto relace, pak aplikace
            cmd = ["bash", "-c", '"$@" & sleep 1; exec "$0" "%s"' % os.path.join(BIN, app), sys.executable, *pre]
        try:
            r = subprocess.run(["dbus-run-session", "--", *cmd], env=env, capture_output=True, text=True,
                               timeout=90)
        finally:
            if sysbus:
                sysbus.terminate()
                sysbus.wait(5)
                sysbus.stdout.close()
        if not os.path.exists(out):
            raise AssertionError("%s did not report (rc %s): %s" % (app, r.returncode, r.stderr[-3000:]))
        with open(out) as f:
            return json.load(f)
    finally:
        x.close()
        shutil.rmtree(tmp, True)


def shot_path(name):
    folder = os.environ.get("LUXOS_FIT_SHOTS")
    if not folder:
        return None
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, name + ".png")


@unittest.skipUnless(shutil.which("Xvfb") and shutil.which("dbus-run-session"), "Xvfb/dbus-run-session missing")
class WindowFits(unittest.TestCase):
    def check(self, app, require_min=True):
        for screen in SCREENS:
            with self.subTest(app=app, screen=screen):
                data = run_app(app, screen, shot=shot_path("%s-%dx%d" % (app, *screen)))
                self.assertTrue(data["windows"], data)
                win = data["windows"][0]
                # cele okno vcetne HeaderBar se vejde na obrazovku i s okrajem (bez WM = pracovni plocha =
                # obrazovka; s horni listou a Dockem hlasi spravce oken mensi pracovni plochu)
                self.assertLessEqual(win["height"], screen[1] - 16, (app, screen, win))
                self.assertLessEqual(win["width"], screen[0], (app, screen, win))
                if require_min and win["resizable"]:
                    self.assertGreaterEqual(win["min"]["height"], MIN_USABLE, (app, screen, win))
                    self.assertGreaterEqual(win["min"]["width"], 340, (app, screen, win))

    def test_feedback(self):
        self.check("luxos-feedback")

    def test_monitor_demo(self):
        self.check("luxos-monitor")

    def test_router_without_network(self):
        self.check("luxos-router")


    def test_shortcuts(self):
        self.check("luxos-shortcuts")


@unittest.skipUnless(shutil.which("Xvfb") and shutil.which("dbus-run-session"), "Xvfb/dbus-run-session missing")
class SizedToContent(unittest.TestCase):
    """Okna bez velke prazdne plochy dole: vyska podle obsahu, ne pevna vychozi (drive + HeaderBar 45 px)."""

    OLD = {"luxos-keyboard": 600, "luxos-display-settings": 700}

    def test_heights(self):
        for app, old in self.OLD.items():
            with self.subTest(app=app):
                data = run_app(app, (1366, 768), shot=shot_path(app), extra={"LUXOS_FIT_NO_SHRINK": "1"})
                win = data["windows"][0]
                self.assertLess(win["height"], old + 45 - 40, (app, win))
                self.assertLessEqual(win["height"], 768 - 16, (app, win))


@unittest.skipUnless(shutil.which("Xvfb") and shutil.which("dbus-run-session"), "Xvfb/dbus-run-session missing")
class RouterOffline(unittest.TestCase):
    """Bez site jsou tlacitka Zobrazit / Vyzkouset / Zmerit neaktivni (s vysvetlenim), se siti aktivni."""

    def buttons(self, net):
        code = ("(lambda G: (lambda walk: walk(walk, wins[0]))(lambda f, w: ([(w.get_label(), w.get_sensitive())] "
                "if isinstance(w, G.Button) and w.get_label() and w.get_mapped() else []) + "
                "sum((f(f, c) for c in (w.get_children() if isinstance(w, G.Container) else [])), [])))(Gtk)")
        tmp = tempfile.mkdtemp(prefix="luxos-fit-net-", dir=luxos_testguard._private_dir())
        try:
            path = os.path.join(tmp, "net.json")
            with open(path, "w") as f:
                json.dump(net, f)
            data = run_app("luxos-router", (1366, 768), extra={"FAKE_NET": path, "LANG": "C.UTF-8"},
                           hook=code, delay=1500)
        finally:
            shutil.rmtree(tmp, True)
        return dict((label, sens) for label, sens in data["hook"])

    def test_offline_disabled(self):
        b = self.buttons(NO_NET)
        for label in ("Show", "Test", "Measure"):
            self.assertIn(label, b)
            self.assertFalse(b[label], (label, b))

    def test_online_enabled(self):
        net = {"routes": [{"dst": "default", "gateway": "192.168.1.1", "dev": "wlp4s0", "metric": 600}],
               "device": "GENERAL.DEVICE: wlp4s0\nGENERAL.TYPE: wifi\nGENERAL.STATE: 100 (connected)\n"
                         "GENERAL.CONNECTION: Domov\nIP4.ADDRESS[1]: 192.168.1.23/24\n",
               "wifi": "yes:Domov\n", "neigh": [], "ping": {}}
        b = self.buttons(net)
        for label in ("Show", "Test", "Measure"):
            self.assertIn(label, b)
            self.assertTrue(b[label], (label, b))


if __name__ == "__main__":
    unittest.main()
