"""LuxOS - okna jako v macOS: umisteni novych oken (volne misto, jinak kaskada), Alt+` (okna aktualni
aplikace), volba "Seskupit okna podle aplikaci v Alt+Tab" a posun ploch do strany pri prepnuti
(xfwm4 z [luxos], packages/xfwm4).

Spusteni:  python3 -m unittest packages/luxos-desktop/tests/test_luxos_windows.py -v
Se spravcem oken (jen pod Xvfb, nikdy na skutecne obrazovce):
  env -u DISPLAY xvfb-run -a -s "-screen 0 1920x1080x24" python3 -m unittest \
      packages/luxos-desktop/tests/test_luxos_windows.py -v
LUXOS_XFWM4 = xfwm4 s opravou LuxOS (napr. rozbaleny artefakt .../usr/bin/xfwm4); bez nej se pouzije
/usr/bin/xfwm4, jen kdyz uz opravu obsahuje. LUXOS_SHOT_DIR = slozka pro snimky obrazovky.
Test spousti vlastni sbernici D-Bus s docasnym HOME (xfconfd bez nastaveni uzivatele).
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
FILES = os.path.normpath(os.path.join(HERE, "..", "files"))
XFCONF_DIR = os.path.join(FILES, "xdg", "xfce4", "xfconf", "xfce-perchannel-xml")
TMP = tempfile.mkdtemp(prefix="luxos-windows-test-")
SHOT_DIR = os.environ.get("LUXOS_SHOT_DIR")
STEP = 28
SLIDE_SCREEN = (1920, 1080)     # xvfb-run -s "-screen 0 1920x1080x24"
SLIDE_Y = 420                   # radek obrazovky pres okna testu posunu ploch


def patched(path):
    try:
        with open(path, "rb") as f:
            return b"cycle_app_windows_key" in f.read()
    except OSError:
        return False


XFWM4 = os.environ.get("LUXOS_XFWM4") or ("/usr/bin/xfwm4" if patched("/usr/bin/xfwm4") else None)
HAVE_DISPLAY = bool(os.environ.get("DISPLAY")) and shutil.which("xdotool") and shutil.which("xprop")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


# ---- vychozi nastaveni a Klavesove zkratky (bez obrazovky) ----------------------------------------------

class Defaults(unittest.TestCase):
    def test_xfwm4_defaults(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(os.path.join(XFCONF_DIR, "xfwm4.xml")).getroot()
        general = {p.get("name"): p.get("value") for p in root.find("property").findall("property")}
        self.assertEqual(general["placement_mode"], "luxos")
        self.assertEqual(general["cycle_group_apps"], "false")      # seskupeni vychozi vypnute
        self.assertEqual(general["cycle_preview"], "true")
        self.assertEqual(general["workspace_slide"], "true")        # posun ploch do strany
        self.assertEqual(general["workspace_slide_duration"], "420")
        self.assertEqual(general["use_compositing"], "true")        # posun jen s kompozitorem
        self.assertEqual(general["activate_action"], "switch")      # okno z jine plochy se nepresouva

    def test_shortcut_defaults(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(os.path.join(XFCONF_DIR, "xfce4-keyboard-shortcuts.xml")).getroot()
        wm = [p for p in root.iter("property") if p.get("name") == "xfwm4"][0].find("property")
        binds = {p.get("name"): p.get("value") for p in wm.findall("property")}
        self.assertEqual(binds["<Alt>grave"], "cycle_app_windows_key")
        self.assertEqual(binds["<Alt><Shift>grave"], "cycle_reverse_app_windows_key")
        # xfwm4 bere pro kazdou akci jen jednu zkratku - nove akce nesmi mit dalsi
        values = list(binds.values())
        self.assertEqual(values.count("cycle_app_windows_key"), 1)
        self.assertEqual(values.count("cycle_reverse_app_windows_key"), 1)
        self.assertEqual(binds["<Super>grave"], "switch_window_key")

    def test_catalog_and_group_setting(self):
        state = os.path.join(TMP, "xfconf-group.json")
        env = {"LUXOS_XFCONF_QUERY": os.path.join(HERE, "fake-shortcuts", "xfconf-query"),
               "FAKE_XFCONF": state, "FAKE_XFCONF_DEFAULTS": os.path.join(XFCONF_DIR, "xfwm4.xml")}
        code = ("import sys, luxos_shortcuts as ls\n"
                "c = {a.id: (a.label, a.values) for a in ls.catalog()}\n"
                "print(c['cycle-app'][1], c['cycle-app-reverse'][1], c['switch-app'][1])\n"
                "print(ls.format_accel('<Alt>grave'), '|', ls.format_accel('<Alt><Shift>grave'))\n"
                "print(ls.group_apps_enabled())\nprint(ls.set_group_apps(True), ls.group_apps_enabled())\n"
                "print(ls.set_group_apps(False), ls.group_apps_enabled())\n")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env=dict(os.environ, PYTHONPATH=os.path.join(FILES, "python"), LANG="C", **env))
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "['cycle_app_windows_key'] ['cycle_reverse_app_windows_key'] ['switch_window_key']")
        self.assertEqual(lines[1], "Alt + ` | Alt + Shift + `")
        self.assertEqual(lines[2:], ["False", "True True", "True False"])
        with open(state) as f:
            self.assertEqual(json.load(f), {"/general/cycle_group_apps": "false"})

    def test_translations(self):
        keys = ["Switch windows of the current app", "Switch windows of the current app backwards",
                "Next window of the same app (without previews)", "Group windows by app in Alt+Tab",
                "Each app is shown once. While holding Alt, press Down or ` to see the windows of the selected app."]
        i18n = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
        langs = sorted(f for f in os.listdir(i18n) if f.endswith(".tsv"))
        self.assertEqual(len(langs), 12)
        for lang in langs:
            with open(os.path.join(i18n, lang), encoding="utf-8") as f:
                rows = dict(line.rstrip("\n").split("\t", 1) for line in f if "\t" in line and not line.startswith("#"))
            for k in keys:
                self.assertTrue(rows.get(k), "%s: %s" % (lang, k))
                self.assertNotEqual(rows[k], k, "%s: %s" % (lang, k))


class SessionMigration(unittest.TestCase):
    """Jednorazove prepnuti starsich profilu (bloky z luxos-session s falesnym xfconf-query)."""

    def run_block(self, user, home, extra=None):
        with open(os.path.join(FILES, "bin", "luxos-session"), encoding="utf-8") as f:
            src = f.read()
        start = src.index("# Nove okno na volne misto")
        end = src.index("\n# Prepinac ploch (pager)", start)
        fake = os.path.join(home, "bin")
        os.makedirs(fake, exist_ok=True)
        shutil.copy(os.path.join(HERE, "fake-shortcuts", "xfconf-query"), fake)
        state = os.path.join(home, "xfconf.json")
        with open(state, "w") as f:
            json.dump(user, f)
        cfg = os.path.join(home, "cfg")
        os.makedirs(cfg, exist_ok=True)
        r = subprocess.run(["bash", "-c", "cfg=%s\n%s\n" % (cfg, src[start:end])],
                           env=dict({"PATH": fake + ":/usr/bin:/bin", "FAKE_XFCONF": state, "HOME": home},
                                    **(extra or {})),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(state) as f:
            return json.load(f), sorted(os.listdir(cfg))

    def test_text_editor_added_to_empty_dock(self):
        # gsettings vypisuje prazdny seznam jako "@as []" - editor se ma pridat i tam
        with open(os.path.join(FILES, "bin", "luxos-session"), encoding="utf-8") as f:
            src = f.read()
        block = src[src.index("# Textovy editor v Docku"):src.index("# Tapety \"vlny\"")]
        for before, after in (("@as []", "['luxos-text.dockitem']"),
                              ("['luxos-terminal.dockitem', 'trash.dockitem']",
                               "['luxos-terminal.dockitem', 'luxos-text.dockitem', 'trash.dockitem']")):
            home = tempfile.mkdtemp(dir=TMP)
            fake = os.path.join(home, "bin")
            os.makedirs(fake)
            state = os.path.join(home, "dock")
            with open(state, "w") as f:
                f.write(before)
            with open(os.path.join(fake, "gsettings"), "w") as f:
                f.write('#!/bin/sh\ncase $1 in get) cat "$STATE";; set) printf %s "$4" >"$STATE";; esac\n')
            with open(os.path.join(fake, "luxos-text"), "w") as f:
                f.write("#!/bin/sh\n")
            for name in ("gsettings", "luxos-text"):
                os.chmod(os.path.join(fake, name), 0o755)
            cfg = os.path.join(home, "cfg")
            os.makedirs(cfg)
            r = subprocess.run(["bash", "-c", "cfg=%s\n%s" % (cfg, block)], capture_output=True, text=True,
                               env={"PATH": fake + ":/usr/bin:/bin", "HOME": home, "STATE": state})
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(state) as f:
                self.assertEqual(f.read(), after)
            self.assertEqual(os.listdir(cfg), ["text-editor-dock"])

    def test_slide_duration_migrated_once(self):
        with open(os.path.join(FILES, "bin", "luxos-session"), encoding="utf-8") as f:
            src = f.read()
        block = src[src.index("# Posun ploch (xfwm4 z [luxos])"):src.index("# Aktivace okna na jine plose")]
        for before, after in (("280", "420"), ("600", "600"), (None, None)):
            home = tempfile.mkdtemp(dir=TMP)
            fake = os.path.join(home, "bin")
            os.makedirs(fake)
            shutil.copy(os.path.join(HERE, "fake-shortcuts", "xfconf-query"), fake)
            state = os.path.join(home, "xfconf.json")
            user = {"/general/theme": "WhiteSur-Light"}
            if before:
                user["/general/workspace_slide_duration"] = before
            with open(state, "w") as f:
                json.dump(user, f)
            cfg = os.path.join(home, "cfg")
            os.makedirs(cfg)
            for _ in range(2):          # podruhe uz nic (znacka)
                r = subprocess.run(["bash", "-c", "cfg=%s\n%s" % (cfg, block)], capture_output=True, text=True,
                                   env={"PATH": fake + ":/usr/bin:/bin", "FAKE_XFCONF": state, "HOME": home})
                self.assertEqual(r.returncode, 0, r.stderr)
            with open(state) as f:
                self.assertEqual(json.load(f).get("/general/workspace_slide_duration"), after, before)
            self.assertEqual(os.listdir(cfg), ["workspace-slide-420"])

    def test_activate_action_migrated_once(self):
        with open(os.path.join(FILES, "bin", "luxos-session"), encoding="utf-8") as f:
            src = f.read()
        block = src[src.index("# Aktivace okna na jine plose"):src.index("# Nove okno na volne misto")]
        for before, after in (("bring", "switch"), ("none", "none"), ("switch", "switch"), (None, None)):
            home = tempfile.mkdtemp(dir=TMP)
            fake = os.path.join(home, "bin")
            os.makedirs(fake)
            shutil.copy(os.path.join(HERE, "fake-shortcuts", "xfconf-query"), fake)
            state = os.path.join(home, "xfconf.json")
            user = {"/general/theme": "WhiteSur-Light"}
            if before:
                user["/general/activate_action"] = before
            with open(state, "w") as f:
                json.dump(user, f)
            cfg = os.path.join(home, "cfg")
            os.makedirs(cfg)
            for step in range(2):
                r = subprocess.run(["bash", "-c", "cfg=%s\n%s" % (cfg, block)], capture_output=True, text=True,
                                   env={"PATH": fake + ":/usr/bin:/bin", "FAKE_XFCONF": state, "HOME": home})
                self.assertEqual(r.returncode, 0, r.stderr)
                if step == 0 and before == "bring":
                    # uzivatel si pak sam zvoli "bring" - podruhe se uz nemeni
                    with open(state) as f:
                        data = json.load(f)
                    self.assertEqual(data["/general/activate_action"], "switch")
                    data["/general/activate_action"] = "bring"
                    with open(state, "w") as f:
                        json.dump(data, f)
                    after = "bring"
            with open(state) as f:
                self.assertEqual(json.load(f).get("/general/activate_action"), after, before)
            self.assertEqual(os.listdir(cfg), ["activate-switch"])

    def test_old_default_switched_once(self):
        home = tempfile.mkdtemp(dir=TMP)
        old = {"/general/placement_mode": "center", "/general/placement_ratio": "50"}
        data, markers = self.run_block(old, home)
        self.assertEqual(markers, ["app-windows-shortcuts", "window-placement"])
        self.assertEqual(data["/general/placement_mode"], "luxos")
        self.assertEqual(data["/xfwm4/custom/<Alt>grave"], "cycle_app_windows_key")
        self.assertEqual(data["/xfwm4/custom/<Alt><Shift>grave"], "cycle_reverse_app_windows_key")
        # podruhe uz nic: uzivatel si pak vybral "center" a Alt+` vypnul
        data["/general/placement_mode"] = "center"
        data["/xfwm4/custom/<Alt>grave"] = ""
        data2, _ = self.run_block(data, home)
        self.assertEqual(data2["/general/placement_mode"], "center")
        self.assertEqual(data2["/xfwm4/custom/<Alt>grave"], "")

    def test_own_choice_kept(self):
        for user in ({"/general/placement_mode": "mouse", "/general/placement_ratio": "50"},
                     {"/general/placement_mode": "center", "/general/placement_ratio": "20"},
                     {"/xfwm4/custom/<Alt>grave": "close_window_key"}):
            home = tempfile.mkdtemp(dir=TMP)
            data, markers = self.run_block(user, home)
            self.assertIn("window-placement", markers)
            for k, v in user.items():
                self.assertEqual(data[k], v, k)               # vlastni volba / prirazeni zustava
            self.assertNotEqual(data.get("/general/placement_mode"), "luxos")

    def test_no_xfconf_retries_later(self):
        # xfconf nedostupny: nic se nezapise ani neoznaci, zkusi se to pri dalsim prihlaseni
        home = tempfile.mkdtemp(dir=TMP)
        data, markers = self.run_block({"/general/placement_mode": "center", "/general/placement_ratio": "50"},
                                       home, {"FAKE_XFCONF_FAIL": "1"})
        self.assertEqual(markers, [])
        self.assertEqual(data["/general/placement_mode"], "center")


# ---- skutecny xfwm4 pod Xvfb -------------------------------------------------------------------------------

APP = r'''
import sys, gi
from gi.repository import GLib
title, cls, w, h = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
opts = sys.argv[5:]
GLib.set_prgname(cls)           # WM_CLASS - pred inicializaci GTK (import Gtk)
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from gi.repository import Gdk
win = Gtk.Window(title=title)
win.set_default_size(w, h)
if "--color" in opts:
    # jednobarevne okno (kontrola, co je na obrazovce navrchu)
    rgb = [int(opts[opts.index("--color") + 1][k:k + 2], 16) / 255 for k in (0, 2, 4)]
    area = Gtk.DrawingArea()
    area.connect("draw", lambda _w, cr: (cr.set_source_rgb(*rgb), cr.paint()))
    win.add(area)
else:
    win.add(Gtk.Label(label=title))
if "--dock" in opts:
    # lista/Dock: okno typu DOCK na vsech plochach; jako Plank bez zamereni (input = False),
    # s --focusable jako xfce4-panel
    win.set_type_hint(Gdk.WindowTypeHint.DOCK)
    win.set_decorated(False)
    win.set_accept_focus("--focusable" in opts)
    win.stick()
if "--no-focus" in opts:
    win.set_accept_focus(False)         # input = False, zamereni nebere
if "--move" in opts:
    i = opts.index("--move")
    win.move(int(opts[i + 1]), int(opts[i + 2]))
win.connect("destroy", Gtk.main_quit)
win.show_all()
if "--fullscreen" in opts:
    GLib.timeout_add(300, lambda: win.fullscreen())
if "--unfullscreen-on-usr1" in opts:
    import signal
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        add_signal = GLibUnix.signal_add
    except (ValueError, ImportError):
        add_signal = GLib.unix_signal_add
    add_signal(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, lambda: (win.unfullscreen(), True)[1])
if "--dialog" in opts:
    def dialog():
        d = Gtk.Window(title=title + "-dialog", transient_for=win, type_hint=1)  # DIALOG
        d.set_default_size(300, 160)
        d.add(Gtk.Label(label="dialog"))
        d.show_all()
        return False
    GLib.timeout_add(300, dialog)
Gtk.main()
'''

SHOT = ("import sys, gi\ngi.require_version('Gdk', '3.0')\nfrom gi.repository import Gdk\n"
        "r = Gdk.get_default_root_window()\n"
        "Gdk.pixbuf_get_from_window(r, 0, 0, r.get_width(), r.get_height()).savev(sys.argv[1], 'png', [], [])\n")


KEYCODE = ("import ctypes, sys\nx = ctypes.CDLL('libX11.so.6')\nx.XOpenDisplay.restype = ctypes.c_void_p\n"
           "x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]\n"
           "x.XStringToKeysym.restype = ctypes.c_ulong\nx.XStringToKeysym.argtypes = [ctypes.c_char_p]\n"
           "d = x.XOpenDisplay(None)\nprint(x.XKeysymToKeycode(d, x.XStringToKeysym(sys.argv[1].encode())))\n")


PIXELS = ("import sys, gi\ngi.require_version('Gdk', '3.0')\nfrom gi.repository import Gdk\n"
          "r = Gdk.get_default_root_window()\n"
          "for a in sys.argv[1:]:\n"
          "    x, y = [int(v) for v in a.split(',')]\n"
          "    p = Gdk.pixbuf_get_from_window(r, x, y, 1, 1).get_pixels()\n"
          "    print(p[0], p[1], p[2])\n")

# _NET_ACTIVE_WINDOW se zdrojem pozadavku (1 = aplikace, 2 = pager/xdotool) - jako Plank nebo jine okno
ACTIVATE = r'''
import ctypes, sys
x = ctypes.CDLL("libX11.so.6")
class Ev(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("data", ctypes.c_long * 5), ("pad", ctypes.c_char * 96)]
x.XOpenDisplay.restype = ctypes.c_void_p
x.XInternAtom.restype = ctypes.c_ulong
x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
x.XDefaultRootWindow.restype = ctypes.c_ulong
x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
x.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
x.XFlush.argtypes = [ctypes.c_void_p]
d = x.XOpenDisplay(None)
e = Ev(type=33, send_event=1, window=int(sys.argv[1]), format=32,
       message_type=x.XInternAtom(d, b"_NET_ACTIVE_WINDOW", 0))
e.data[0] = int(sys.argv[2])
x.XSendEvent(d, x.XDefaultRootWindow(d), 0, (1 << 19) | (1 << 20), ctypes.byref(e))
x.XFlush(d)
'''


def xprop_root(prop):
    return subprocess.run(["xprop", "-root", prop], capture_output=True, text=True).stdout


NEEDS_WM = "needs patched xfwm4 (LUXOS_XFWM4) and Xvfb (xvfb-run) with xdotool"


class WindowManagerBase(unittest.TestCase):
    """Vlastni xfwm4 pod Xvfb (bez testu); COMPOSITOR = volba --compositor."""
    COMPOSITOR = "on"

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="home-", dir=TMP)
        run = os.path.join(cls.home, "run")
        os.makedirs(run, mode=0o700)
        os.chmod(run, 0o700)
        xdg = os.path.join(cls.home, "xdg")
        shutil.copytree(os.path.join(FILES, "xdg"), xdg)
        cls.env = dict(os.environ, HOME=cls.home, XDG_RUNTIME_DIR=run,
                       XDG_CONFIG_HOME=os.path.join(cls.home, ".config"),
                       XDG_CACHE_HOME=os.path.join(cls.home, ".cache"),
                       XDG_DATA_HOME=os.path.join(cls.home, ".local", "share"),
                       XDG_CONFIG_DIRS=xdg + ":/etc/xdg", GTK_A11Y="none", NO_AT_BRIDGE="1", LANG="C")
        cls.env.pop("SESSION_MANAGER", None)
        # vlastni sbernice: xfconfd (aktivace D-Bus) dedi prostredi demona, tedy docasny HOME
        cls.bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                                   env=cls.env, stdout=subprocess.PIPE, text=True)
        cls.env["DBUS_SESSION_BUS_ADDRESS"] = cls.bus.stdout.readline().strip()
        subprocess.run(["setxkbmap", "-layout", "us"], env=cls.env, check=True)
        cls.wm_log = open(os.path.join(cls.home, "xfwm4.log"), "w")
        cls.wm = subprocess.Popen([XFWM4, "--compositor=" + cls.COMPOSITOR, "--sm-client-disable"], env=cls.env,
                                  stdout=subprocess.DEVNULL, stderr=cls.wm_log)
        for _ in range(100):
            if "window id" in xprop_root("_NET_SUPPORTING_WM_CHECK"):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("xfwm4 did not start")
        time.sleep(1.0)
        cls.apps = []

    @classmethod
    def tearDownClass(cls):
        for p in cls.apps:
            p.kill()
        cls.wm.terminate()
        try:
            cls.wm.wait(5)
        except subprocess.TimeoutExpired:
            cls.wm.kill()
        cls.wm_log.close()
        cls.bus.terminate()
        cls.bus.wait(5)
        cls.bus.stdout.close()

    def tearDown(self):
        self.close_all()
        self.xfconf("xfwm4", "/general/cycle_group_apps", "false", "bool")
        self.xfconf("xfwm4", "/general/workspace_slide", "true", "bool")
        subprocess.run(["xdotool", "set_desktop", "0"], env=self.env)
        subprocess.run(["setxkbmap", "-layout", "us"], env=self.env)

    # -- pomocne --
    def xfconf(self, channel, prop, value, typ="string"):
        subprocess.run(["xfconf-query", "-c", channel, "-p", prop, "-n", "-t", typ, "-s", value],
                       env=self.env, check=True)
        time.sleep(0.3)

    def close_all(self):
        for p in type(self).apps:
            p.kill()
            p.wait()
        type(self).apps = []
        time.sleep(0.5)

    def open(self, title, cls="luxtesta", w=600, h=400, *opts):
        p = subprocess.Popen([sys.executable, "-c", APP, title, cls, str(w), str(h), *opts], env=self.env)
        type(self).apps.append(p)
        self.procs = getattr(self, "procs", {})
        self.procs[title] = p
        wid = self.find(title)
        time.sleep(0.4)
        return wid

    def find(self, title):
        r = subprocess.run(["xdotool", "search", "--sync", "--onlyvisible", "--name", "^%s$" % title],
                           env=self.env, capture_output=True, text=True, timeout=20)
        return int(r.stdout.split()[0])

    def frame(self, wid):
        """(x, y, w, h) ramu okna vcetne dekorace."""
        r = subprocess.run(["xdotool", "getwindowgeometry", "--shell", str(wid)], env=self.env,
                           capture_output=True, text=True).stdout
        g = dict(line.split("=", 1) for line in r.split())
        ext = subprocess.run(["xprop", "-id", str(wid), "_NET_FRAME_EXTENTS"], env=self.env,
                             capture_output=True, text=True).stdout
        left, right, top, bottom = [int(v) for v in ext.split("=")[1].split(",")]
        return (int(g["X"]) - left, int(g["Y"]) - top, int(g["WIDTH"]) + left + right,
                int(g["HEIGHT"]) + top + bottom)

    def active(self):
        out = xprop_root("_NET_ACTIVE_WINDOW")
        return int(out.split("#")[1].split(",")[0].strip(), 16)

    def key(self, *keys):
        subprocess.run(["xdotool", *keys], env=self.env, check=True)
        time.sleep(0.5)

    def keycode(self, keysym):
        r = subprocess.run([sys.executable, "-c", KEYCODE, keysym], env=self.env, capture_output=True, text=True)
        return int(r.stdout.strip())

    def shot(self, name):
        if not SHOT_DIR:
            return
        os.makedirs(SHOT_DIR, exist_ok=True)
        subprocess.run([sys.executable, "-c", SHOT, os.path.join(SHOT_DIR, name + ".png")], env=self.env)

    def screen(self):
        out = xprop_root("_NET_WORKAREA")
        x, y, w, h = [int(v) for v in out.split("=")[1].split(",")[:4]]
        return x, y, w, h

    @staticmethod
    def overlap(a, b):
        w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
        h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
        return max(w, 0) * max(h, 0)

    def assert_not_stacked(self, frames):
        for i, a in enumerate(frames):
            for b in frames[:i]:
                self.assertFalse(abs(a[0] - b[0]) < STEP // 2 and abs(a[1] - b[1]) < STEP // 2,
                                 "window %s on top of %s" % (a, b))



@unittest.skipUnless(XFWM4 and HAVE_DISPLAY, NEEDS_WM)
class WindowManager(WindowManagerBase):
    # -- umisteni --
    def test_free_space_then_cascade_small(self):
        sx, sy, sw, sh = self.screen()
        frames = []
        for i in range(1, 9):
            frames.append(self.frame(self.open("small%d" % i)))
        self.shot("placement-small-8")
        first = frames[0]
        # 1. prvni okno uprostred volne obrazovky
        self.assertLessEqual(abs(first[0] + first[2] // 2 - (sx + sw // 2)), 2, first)
        self.assertLessEqual(abs(first[1] + first[3] // 2 - (sy + sh // 2)), 2, first)
        # 2. dalsi okna do volneho mista, dokud nejake je (bez prekryti s predchozimi)
        free = 1
        while free < len(frames) and all(self.overlap(frames[free], f) == 0 for f in frames[:free]):
            free += 1
        self.assertGreaterEqual(free, 4, frames)               # 1920x1080: aspon 4 okna 600x400 vedle sebe
        # 3. pak kaskada o 28 px od posledniho okna stejne aplikace
        for i in range(free, len(frames)):
            prev = frames[i - 1]
            if prev[0] + STEP + frames[i][2] > sx + sw or prev[1] + STEP + frames[i][3] > sy + sh:
                # na okraji pracovni plochy novy sloupec vlevo / nahore
                self.assertTrue(frames[i][0] == sx or frames[i][1] == sy, (i, frames))
                self.assertTrue(frames[i][0] == sx or frames[i][0] == prev[0] + STEP, (i, frames))
                self.assertTrue(frames[i][1] == sy or frames[i][1] == prev[1] + STEP, (i, frames))
            else:
                self.assertEqual((frames[i][0] - prev[0], frames[i][1] - prev[1]), (STEP, STEP), (i, frames))
        self.assert_not_stacked(frames)
        for f in frames:
            self.assertTrue(sx <= f[0] and f[0] + f[2] <= sx + sw and sy <= f[1] and f[1] + f[3] <= sy + sh, f)

    def test_cascade_large_wraps(self):
        sx, sy, sw, sh = self.screen()
        frames = [self.frame(self.open("big%d" % i, "luxtesta", 1100, 800)) for i in range(1, 13)]
        self.shot("placement-large-12")
        self.assertLessEqual(abs(frames[0][0] + frames[0][2] // 2 - (sx + sw // 2)), 2)
        for i in range(1, len(frames)):
            dx, dy = frames[i][0] - frames[i - 1][0], frames[i][1] - frames[i - 1][1]
            if frames[i - 1][1] + STEP + frames[i][3] > sy + sh or frames[i - 1][0] + STEP + frames[i][2] > sx + sw:
                # na okraji pracovni plochy novy sloupec nahore / vlevo
                self.assertTrue(frames[i][1] == sy or frames[i][0] == sx, (i, frames))
            else:
                self.assertEqual((dx, dy), (STEP, STEP), (i, frames))
            f = frames[i]
            self.assertTrue(sx <= f[0] and f[0] + f[2] <= sx + sw and sy <= f[1] and f[1] + f[3] <= sy + sh, f)
        self.assert_not_stacked(frames)

    def test_cascade_per_app_and_other_app(self):
        a = [self.frame(self.open("ca%d" % i, "luxtesta", 1100, 800)) for i in range(1, 4)]
        b1 = self.frame(self.open("cb1", "luxtestb", 1100, 800))
        a4 = self.frame(self.open("ca4", "luxtesta", 1100, 800))
        b2 = self.frame(self.open("cb2", "luxtestb", 1100, 800))
        self.shot("placement-two-apps")
        # okno jine aplikace bez volneho mista: nikdy presne na jinem okne
        self.assert_not_stacked(a + [b1, a4, b2])
        # dalsi okno A pokracuje kaskadou od posledniho okna A, B od posledniho B
        self.assertEqual((a4[0] - a[2][0], a4[1] - a[2][1]), (STEP, STEP))
        self.assertEqual((b2[0] - b1[0], b2[1] - b1[1]), (STEP, STEP))

    def test_dialog_and_own_position_untouched(self):
        parent = self.open("withdialog", "luxtesta", 1100, 800, "--dialog")
        self.open("blocker", "luxtesta", 1100, 800)
        d = self.find("withdialog-dialog")
        time.sleep(0.3)
        pf, df = self.frame(parent), self.frame(d)
        # dialog uprostred rodice (puvodni pravidlo xfwm4), ne kaskadou
        self.assertLessEqual(abs((df[0] + df[2] // 2) - (pf[0] + pf[2] // 2)), 30, (pf, df))
        self.assertLessEqual(abs((df[1] + df[3] // 2) - (pf[1] + pf[3] // 2)), 40, (pf, df))
        # okno s vlastni pozici (gtk_window_move pred zobrazenim = USPosition) zustane, kde chtelo
        own = self.open("ownpos", "luxtesta", 500, 300, "--move", "40", "60")
        r = subprocess.run(["xdotool", "getwindowgeometry", "--shell", str(own)], env=self.env,
                           capture_output=True, text=True).stdout
        g = dict(line.split("=", 1) for line in r.split())
        ext = subprocess.run(["xprop", "-id", str(own), "_NET_FRAME_EXTENTS"], env=self.env,
                             capture_output=True, text=True).stdout
        left, _r, top, _b = [int(v) for v in ext.split("=")[1].split(",")]
        self.assertEqual((int(g["X"]) - left, int(g["Y"]) - top), (40, 60))
        self.shot("placement-dialog")

    # -- Alt+` --
    def open_apps(self):
        w = {}
        for name, cls in (("a1", "luxtesta"), ("b1", "luxtestb"), ("a2", "luxtesta"), ("b2", "luxtestb"),
                          ("a3", "luxtesta")):
            w[name] = self.open(name, cls, 500, 350)
        return w

    def check_app_cycle(self, key, reverse_key, layout):
        w = self.open_apps()
        a = {w["a1"], w["a2"], w["a3"]}
        self.assertEqual(self.active(), w["a3"])
        seen = []
        for _ in range(4):
            self.key("key", key)
            seen.append(self.active())
        self.assertTrue(all(s in a for s in seen), (seen, w))
        self.assertEqual(seen[0], w["a2"])              # naposledy pouzite jine okno aplikace
        self.assertEqual(seen[1], w["a3"])              # opakovane Alt+` = zpet
        # s drzenym Alt dal: a3 -> a2 -> a1
        self.key("keydown", "alt", "key", key.split("+")[1])
        self.key("key", key.split("+")[1])
        self.shot("alt-grave-%s" % layout)
        self.key("keyup", "alt")
        self.assertEqual(self.active(), w["a1"])
        # Shift+Alt+` pozpatku
        self.key("key", reverse_key)
        self.assertIn(self.active(), a)
        self.assertNotEqual(self.active(), w["a1"])
        # z okna B jen okna B
        subprocess.run(["xdotool", "windowactivate", "--sync", str(w["b1"])], env=self.env)
        time.sleep(0.4)
        self.key("key", key)
        self.assertEqual(self.active(), w["b2"])

    def test_alt_grave_us(self):
        self.check_app_cycle("alt+grave", "alt+shift+grave", "us")

    def test_alt_grave_cz(self):
        # ceske rozlozeni: na klavese pod Esc je ";" (` jen s AltGr jinde) - Alt+` = fyzicka klavesa <TLDE>
        tilde = self.keycode("grave")                   # us: ` je na <TLDE>
        subprocess.run(["setxkbmap", "-layout", "cz"], env=self.env, check=True)
        time.sleep(1.0)
        self.assertEqual(self.keycode("semicolon"), tilde)  # rozlozeni opravdu ceske: ";" na <TLDE>
        # XKeysymToKeycode("grave") v cz vrati H (` je tam jen s AltGr) - puvodni xfwm4 by Alt+` navazal na Alt+H
        self.assertEqual(self.keycode("grave"), self.keycode("h"))
        self.check_app_cycle("alt+semicolon", "alt+shift+semicolon", "cz")
        # Alt+H (puvodni xfwm4 by sem dal "grave" z AltGr+H) okna neprepina
        before = self.active()
        self.key("key", "alt+h")
        self.assertEqual(self.active(), before)

    def test_single_window_app(self):
        only = self.open("lonely", "luxtestc", 500, 350)
        self.open("other", "luxtestd", 500, 350)
        subprocess.run(["xdotool", "windowactivate", "--sync", str(only)], env=self.env)
        time.sleep(0.4)
        self.key("key", "alt+grave")
        self.assertEqual(self.active(), only)           # jine okno aplikace neni - nic se nestane

    # -- seskupeny Alt+Tab --
    def tabwin_width(self):
        r = subprocess.run(["xdotool", "search", "--onlyvisible", "--classname", "xfwm4"], env=self.env,
                           capture_output=True, text=True).stdout.split()
        widths = []
        for wid in r:
            g = subprocess.run(["xdotool", "getwindowgeometry", "--shell", wid], env=self.env,
                               capture_output=True, text=True).stdout
            d = dict(line.split("=", 1) for line in g.split())
            if int(d["HEIGHT"]) > 50:
                widths.append(int(d["WIDTH"]))
        return max(widths) if widths else 0

    def test_alt_tab_ungrouped_default(self):
        w = self.open_apps()
        self.key("keydown", "alt", "key", "Tab")
        width_all = self.tabwin_width()
        self.shot("alt-tab-all")
        self.key("keyup", "alt")
        self.assertEqual(self.active(), w["b2"])        # vychozi: naposledy pouzite okno (puvodni chovani)
        self.assertGreater(width_all, 0)

    def test_alt_tab_grouped(self):
        w = self.open_apps()
        self.key("keydown", "alt", "key", "Tab")
        width_all = self.tabwin_width()
        self.key("keyup", "alt")
        subprocess.run(["xdotool", "windowactivate", "--sync", str(w["a3"])], env=self.env)
        time.sleep(0.4)
        self.xfconf("xfwm4", "/general/cycle_group_apps", "true", "bool")
        # kazda aplikace jednou: dalsi aplikace je B (jeji posledni okno), ne dalsi okno A
        self.key("keydown", "alt", "key", "Tab")
        width_grouped = self.tabwin_width()
        self.shot("alt-tab-grouped")
        self.key("keyup", "alt")
        self.assertIn(self.active(), {w["b1"], w["b2"]})
        self.assertLess(width_grouped, width_all)       # 2 polozky misto 5
        b_last = self.active()
        b_other = ({w["b1"], w["b2"]} - {b_last}).pop()
        subprocess.run(["xdotool", "windowactivate", "--sync", str(w["a3"])], env=self.env)
        time.sleep(0.4)
        # Alt+Tab, Dolu = okna vybrane aplikace (B), ` = jeji dalsi okno
        self.key("keydown", "alt", "key", "Tab")
        self.key("key", "Down")
        width_expanded = self.tabwin_width()
        self.shot("alt-tab-grouped-down")
        self.key("key", "grave")
        self.key("keyup", "alt")
        self.assertEqual(self.active(), b_other)
        self.assertGreater(width_expanded, 0)
        # ted je aktivni B: Alt+Tab vybere aplikaci A, ` rozbali jeji okna (posune na dalsi okno A),
        # Nahoru = zpet na aplikace s vybranou A -> po pusteni Alt jeji naposledy pouzite okno (a3)
        self.key("keydown", "alt", "key", "Tab")
        self.key("key", "grave")
        self.key("key", "Up")
        self.shot("alt-tab-grouped-up")
        self.key("keyup", "alt")
        self.assertEqual(self.active(), w["a3"])
        # Alt+` funguje i se seskupenim
        a_now = self.active()
        self.key("key", "alt+grave")
        self.assertIn(self.active(), {w["a1"], w["a2"], w["a3"]} - {a_now})

    def test_window_closed_while_cycling(self):
        # zavreni okna behem prepinani (seskupeny i rozbaleny seznam) xfwm4 neshodi
        w = self.open_apps()
        self.xfconf("xfwm4", "/general/cycle_group_apps", "true", "bool")
        self.key("keydown", "alt", "key", "Tab")
        self.key("key", "Down")                         # okna aplikace B
        self.procs["b2"].kill()
        self.procs["b1"].kill()
        time.sleep(0.8)
        self.key("key", "grave")
        self.key("key", "Up")                           # zpet na aplikace (B uz zadna okna nema)
        self.key("keyup", "alt")
        self.assertIsNone(self.wm.poll(), "xfwm4 crashed")
        self.assertIn(self.active(), {w["a1"], w["a2"], w["a3"]})
        # Alt+` s jedinou aplikaci dal funguje
        self.key("key", "alt+grave")
        self.assertIsNone(self.wm.poll())
        self.assertIn(self.active(), {w["a1"], w["a2"], w["a3"]})

    # -- okno z jine plochy se nepresouva na aktualni (activate_action "switch", XRaiseWindow) --
    def desktop_of(self, wid):
        out = subprocess.run(["xprop", "-id", str(wid), "_NET_WM_DESKTOP"], env=self.env,
                             capture_output=True, text=True).stdout
        return int(out.split("=")[1])

    def current_desktop(self):
        return int(xprop_root("_NET_CURRENT_DESKTOP").split("=")[1])

    def test_window_from_other_workspace_stays(self):
        a = self.open("ws-stay-a", "luxwsa", 500, 300)
        b = self.open("ws-stay-b", "luxwsb", 500, 300)
        subprocess.run(["xdotool", "set_desktop_for_window", str(b), "1"], env=self.env, check=True)
        for _ in range(30):
            if self.desktop_of(b) == 1:
                break
            time.sleep(0.1)
        subprocess.run(["xdotool", "set_desktop", "0"], env=self.env, check=True)
        time.sleep(0.6)
        subprocess.run(["xdotool", "windowactivate", "--sync", str(a)], env=self.env, check=True)
        time.sleep(0.3)             # posledni vytazene okno je a (xfwm4 si zadosti okna o vytazeni jinak nevsima)
        self.assertEqual((self.desktop_of(a), self.desktop_of(b), self.current_desktop()), (0, 1, 0))
        # aplikace na pozadi se sama vytahne nahoru (XRaiseWindow): zustane na sve plose, plocha se nemeni
        subprocess.run(["xdotool", "windowraise", str(b)], env=self.env, check=True)
        time.sleep(0.6)
        self.assertEqual((self.desktop_of(b), self.current_desktop()), (1, 0))
        net = subprocess.run(["xprop", "-id", str(b), "_NET_WM_STATE"], env=self.env, capture_output=True,
                             text=True).stdout
        self.assertIn("_NET_WM_STATE_DEMANDS_ATTENTION", net)
        # aktivace (Dock, prepinac oken): prepne na plochu okna jako macOS, okno se nepresouva
        subprocess.run(["xdotool", "windowactivate", str(b)], env=self.env, check=True)
        time.sleep(0.8)
        self.assertEqual((self.desktop_of(a), self.desktop_of(b), self.current_desktop()), (0, 1, 1))
        self.assertEqual(self.active(), b)

    # -- posun ploch do strany --
    def record_switch(self, desktop, name):
        """Zaznam obrazovky (60 snimku/s) behem prepnuti na plochu desktop; vrati radky y=SLIDE_Y."""
        video = os.path.join(TMP, name + ".mkv")
        rec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-framerate", "60",
                                "-video_size", "%dx%d" % SLIDE_SCREEN, "-i", self.env["DISPLAY"], "-t", "1.4",
                                "-c:v", "ffv1", video], env=self.env)
        time.sleep(0.3)
        subprocess.run(["xdotool", "set_desktop", str(desktop)], env=self.env, check=True)
        rec.wait(20)
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", video, "-vf",
                              "crop=%d:1:0:%d" % (SLIDE_SCREEN[0], SLIDE_Y), "-f", "rawvideo", "-pix_fmt", "gray",
                              "-"], capture_output=True, check=True).stdout
        w = SLIDE_SCREEN[0]
        return [raw[i * w:(i + 1) * w] for i in range(len(raw) // w)]

    @staticmethod
    def light_spans(line):
        """Svetle useky (okna) delsi nez 40 px; vzorek pozadi Xvfb (stridave pixely) mezi ne nepatri."""
        spans, start = [], None
        for x, v in enumerate(line + b"\0"):
            if v > 200 and start is None:
                start = x
            elif v <= 200 and start is not None:
                if x - start > 40:
                    spans.append((start, x))
                start = None
        return spans

    def distinct_spans(self, lines):
        out = []
        for line in lines:
            sp = self.light_spans(line)
            if not out or out[-1] != sp:
                out.append(sp)
        return out

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_workspace_slide(self):
        a = self.open("slide-a", "luxslide", 800, 500, "--move", "500", "300")
        b = self.open("slide-b", "luxslide", 800, 500, "--move", "500", "300")
        subprocess.run(["xdotool", "set_desktop_for_window", str(b), "1"], env=self.env, check=True)
        for _ in range(30):
            if self.desktop_of(b) == 1:
                break
            time.sleep(0.1)
        time.sleep(0.3)
        x0 = self.frame(a)[0]
        # dalsi plocha: stara okna odjedou doleva, nova prijedou zprava (mezi tim aspon 4 polohy)
        steps = self.distinct_spans(self.record_switch(1, "slide-next"))
        self.assertGreaterEqual(len(steps), 6, steps)
        self.assertEqual(steps[0], steps[-1])                       # okno na stejnem miste
        middle = steps[1:-1]
        # mirny rozjezd (ne ease-out s nejvetsim krokem hned na zacatku): prvni posun je maly
        first = middle[0][0][0] if middle[0] else 0
        self.assertLess(x0 - first, 150, middle[:3])
        self.assertTrue(any(sp and sp[0][0] == 0 for sp in middle), middle)                 # vlevo ven
        self.assertTrue(any(sp and sp[-1][1] == SLIDE_SCREEN[0] for sp in middle), middle)  # zprava dovnitr
        lefts = [sp[0][0] for sp in middle if len(sp) == 1 and sp[0][0] > x0]
        self.assertEqual(lefts, sorted(lefts, reverse=True), middle)  # nove okno jede jen doleva
        self.assertIsNone(self.wm.poll(), "xfwm4 crashed")
        # predchozi plocha: opacne
        steps = self.distinct_spans(self.record_switch(0, "slide-prev"))
        middle = steps[1:-1]
        self.assertGreaterEqual(len(middle), 4, steps)
        self.assertTrue(any(sp and sp[-1][1] == SLIDE_SCREEN[0] for sp in middle), middle)  # vpravo ven
        self.assertTrue(any(sp and sp[0][0] == 0 for sp in middle), middle)                 # zleva dovnitr
        # vypnuto: prepne se hned, zadne mezipolohy
        self.xfconf("xfwm4", "/general/workspace_slide", "false", "bool")
        steps = self.distinct_spans(self.record_switch(1, "slide-off"))
        self.assertLessEqual(len(steps), 2, steps)
        self.assertEqual(xprop_root("_NET_CURRENT_DESKTOP").split("=")[1].strip(), "1")


# ---- celoobrazovkove okno nad horni listou a Dockem -------------------------------------------------------

RED, BLUE, GREEN = (255, 0, 0), (0, 0, 255), (0, 255, 0)
BAR_PT = (960, 14)              # uprostred horni listy (28 px)
DOCK_PT = (960, 1040)           # uprostred Docku


class FullscreenTests:
    """Celoobrazovkove okno (video ve Firefoxu, prezentace) zakryje horni listu i Dock - jako v macOS.
    Chyba: po aktivaci okna, ktere zamereni neprevzalo (Dock), zustalo celoobrazovkove okno zamerene,
    ale pod listou, a klik do nej uz nepomohl."""

    def setUp(self):
        out = subprocess.run(["xdotool", "getdisplaygeometry"], env=self.env, capture_output=True,
                             text=True).stdout.split()
        if [int(v) for v in out] != list(SLIDE_SCREEN):
            self.skipTest("needs xvfb-run -s \"-screen 0 1920x1080x24\"")
        # lista nahore jako xfce4-panel (bere zamereni, rezervuje 28 px), Dock dole jako Plank (nebere)
        self.bar = self.open("fs-bar", "luxfsbar", SLIDE_SCREEN[0], 28, "--dock", "--focusable",
                             "--color", "0000ff", "--move", "0", "0")
        subprocess.run(["xprop", "-id", str(self.bar), "-f", "_NET_WM_STRUT", "32c", "-set", "_NET_WM_STRUT",
                        "0, 0, 28, 0"], env=self.env, check=True)
        self.dock = self.open("fs-dock", "luxfsdock", 800, 80, "--dock", "--color", "00ff00",
                              "--move", "560", "1000")
        self.fs = self.open("fs-video", "luxfsvideo", 800, 500, "--color", "ff0000", "--fullscreen",
                            "--unfullscreen-on-usr1")
        time.sleep(1.0)

    def wait_active(self, wid, timeout=4.0):
        """Zamerene okno (pod zatezi muze xfwm4 chvili trvat)."""
        end = time.time() + timeout
        while self.active() != wid and time.time() < end:
            time.sleep(0.1)
        self.assertEqual(self.active(), wid)

    def stacking(self):
        out = xprop_root("_NET_CLIENT_LIST_STACKING")
        return [int(v.strip(), 16) for v in out.split("#")[1].split(",")]

    def pixels(self, *pts):
        r = subprocess.run([sys.executable, "-c", PIXELS] + ["%d,%d" % p for p in pts], env=self.env,
                           capture_output=True, text=True, check=True)
        return [tuple(int(v) for v in line.split()) for line in r.stdout.splitlines()]

    def state(self, wid):
        return subprocess.run(["xprop", "-id", str(wid), "_NET_WM_STATE"], env=self.env,
                              capture_output=True, text=True).stdout

    def click_fs(self):
        subprocess.run(["xdotool", "mousemove", "960", "540", "click", "1"], env=self.env, check=True)
        time.sleep(0.8)

    def assert_on_top(self, what):
        stack = self.stacking()
        self.assertIn("_NET_WM_STATE_FULLSCREEN", self.state(self.fs), what)
        self.assertGreater(stack.index(self.fs), stack.index(self.bar), "%s: bar above fullscreen" % what)
        self.assertGreater(stack.index(self.fs), stack.index(self.dock), "%s: dock above fullscreen" % what)
        # co je opravdu videt (s kompozitorem kresli xfwm4, bez nej X server)
        self.assertEqual(self.pixels(BAR_PT, DOCK_PT), [RED, RED], what)

    def test_fullscreen_covers_bar_and_dock(self):
        g = subprocess.run(["xdotool", "getwindowgeometry", "--shell", str(self.fs)], env=self.env,
                           capture_output=True, text=True).stdout
        geo = dict(line.split("=", 1) for line in g.split())
        self.assertEqual((int(geo["X"]), int(geo["Y"]), int(geo["WIDTH"]), int(geo["HEIGHT"])),
                         (0, 0) + SLIDE_SCREEN)
        self.wait_active(self.fs)
        self.shot("fullscreen-%s" % self.COMPOSITOR)
        self.assert_on_top("fullscreen")
        # konec celoobrazovkoveho rezimu: lista a Dock zase navrchu
        self.procs["fs-video"].send_signal(10)          # SIGUSR1 -> unfullscreen
        time.sleep(1.0)
        self.assertNotIn("_NET_WM_STATE_FULLSCREEN", self.state(self.fs))
        stack = self.stacking()
        self.assertGreater(stack.index(self.bar), stack.index(self.fs))
        self.assertEqual(self.pixels(BAR_PT, DOCK_PT), [BLUE, GREEN])

    def test_dock_activation_keeps_fullscreen_on_top(self):
        # Dock bez zamereni pozada o aktivaci (pager i aplikace): zamereni zustane celoobrazovkovemu
        # oknu a to musi zustat nad listou a Dockem (drive kleslo pod ne)
        for source in ("2", "1"):
            subprocess.run([sys.executable, "-c", ACTIVATE, str(self.dock), source], env=self.env, check=True)
            time.sleep(0.8)
            self.wait_active(self.fs)
            self.assert_on_top("dock activation, source %s" % source)
        subprocess.run(["xdotool", "windowactivate", str(self.dock)], env=self.env)
        time.sleep(0.8)
        self.shot("fullscreen-dock-activated-%s" % self.COMPOSITOR)
        self.assert_on_top("xdotool windowactivate dock")
        # lista, ktera zamereni vezme: ta je chvili navrchu, klik do celoobrazovkoveho okna ho vrati nahoru
        subprocess.run([sys.executable, "-c", ACTIVATE, str(self.bar), "2"], env=self.env, check=True)
        time.sleep(0.8)
        self.click_fs()
        self.wait_active(self.fs)
        self.assert_on_top("click after bar activation")

    def test_focus_changes(self):
        other = self.open("fs-other", "luxfsother", 600, 400)
        self.wait_active(other)
        # jine okno vepredu: celoobrazovkove okno jde pod listu (lista je videt)
        self.assertEqual(self.pixels(BAR_PT), [BLUE])
        # klik zpet do celoobrazovkoveho okna
        self.click_fs()
        self.wait_active(self.fs)
        self.assert_on_top("click back")
        # Alt+Tab pryc a zpet
        self.key("key", "alt+Tab")
        self.wait_active(other)
        self.key("key", "alt+Tab")
        self.wait_active(self.fs)
        self.assert_on_top("alt+tab back")
        # opakovany klik do zamereneho okna nic nerozbije
        self.click_fs()
        self.assert_on_top("click on focused")

    def test_window_without_focus_appears(self):
        # Skutecna chyba: pri prehravani videa se ukaze karta Hudba widgetu LuxOS (okno bez zamereni,
        # vzdy vespod, na vsech plochach). xfwm4 dal celoobrazovkove okno pod listu uz pri namapovani
        # noveho okna, to zamereni odmitlo -> video zustalo zamerene, ale lista pres nej (i po kliku).
        widget = self.open("fs-widget", "luxos-widgets", 340, 120, "--no-focus", "--move", "1216", "40")
        subprocess.run(["wmctrl", "-i", "-r", str(widget), "-b", "add,below,sticky"], env=self.env)
        time.sleep(0.5)
        self.wait_active(self.fs)
        self.shot("fullscreen-widget-%s" % self.COMPOSITOR)
        self.assert_on_top("widget mapped")
        # znovu skryti a ukazani karty (dalsi skladba)
        subprocess.run(["xdotool", "windowunmap", "--sync", str(widget)], env=self.env, check=True)
        subprocess.run(["xdotool", "windowmap", "--sync", str(widget)], env=self.env, check=True)
        time.sleep(0.8)
        self.wait_active(self.fs)
        self.assert_on_top("widget remapped")
        # obycejne okno bez zamereni (input = False) a Alt+Tab na nej: zamereni i vrch zustava videu
        self.open("fs-nofocus", "luxfsnofocus", 600, 400, "--no-focus")
        self.wait_active(self.fs)
        self.assert_on_top("normal window without focus")
        self.key("key", "alt+Tab")
        self.wait_active(self.fs)
        self.assert_on_top("alt+tab to window without focus")
        self.click_fs()
        self.assert_on_top("click")

    def check_workspace_switch(self, slide):
        self.xfconf("xfwm4", "/general/workspace_slide", "true" if slide else "false", "bool")
        subprocess.run(["xdotool", "set_desktop", "1"], env=self.env, check=True)
        time.sleep(1.0)
        # jina plocha: lista a Dock (na vsech plochach) videt, celoobrazovkove okno ne
        self.assertEqual(self.pixels(BAR_PT, DOCK_PT), [BLUE, GREEN])
        subprocess.run(["xdotool", "set_desktop", "0"], env=self.env, check=True)
        time.sleep(1.0)
        self.wait_active(self.fs)
        self.assert_on_top("workspace switch back (slide %s)" % slide)
        self.assertIsNone(self.wm.poll(), "xfwm4 crashed")

    def test_workspace_switch_with_slide(self):
        self.check_workspace_switch(True)

    def test_workspace_switch_without_slide(self):
        self.check_workspace_switch(False)


@unittest.skipUnless(XFWM4 and HAVE_DISPLAY, NEEDS_WM)
class Fullscreen(FullscreenTests, WindowManagerBase):
    COMPOSITOR = "on"


@unittest.skipUnless(XFWM4 and HAVE_DISPLAY, NEEDS_WM)
class FullscreenNoCompositor(FullscreenTests, WindowManagerBase):
    COMPOSITOR = "off"


if __name__ == "__main__":
    unittest.main()
