"""LuxOS - okna jako v macOS: umisteni novych oken (volne misto, jinak kaskada), Alt+` (okna aktualni
aplikace) a volba "Seskupit okna podle aplikaci v Alt+Tab" (xfwm4 z [luxos], packages/xfwm4).

Spusteni:  python3 -m unittest packages/luxos-desktop/tests/test_luxos_windows.py -v
Se spravcem oken (jen pod Xvfb, nikdy na skutecne obrazovce):
  env -u DISPLAY xvfb-run -a -s "-screen 0 1920x1080x24" python3 -m unittest \
      packages/luxos-desktop/tests/test_luxos_windows.py -v
LUXOS_XFWM4 = xfwm4 s opravou LuxOS (napr. rozbaleny artefakt .../usr/bin/xfwm4); bez nej se pouzije
/usr/bin/xfwm4, jen kdyz uz opravu obsahuje. LUXOS_SHOT_DIR = slozka pro snimky obrazovky.
Test spousti vlastni sbernici D-Bus s docasnym HOME (xfconfd bez nastaveni uzivatele).
"""
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
win = Gtk.Window(title=title)
win.set_default_size(w, h)
win.add(Gtk.Label(label=title))
if "--move" in opts:
    i = opts.index("--move")
    win.move(int(opts[i + 1]), int(opts[i + 2]))
win.connect("destroy", Gtk.main_quit)
win.show_all()
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


def xprop_root(prop):
    return subprocess.run(["xprop", "-root", prop], capture_output=True, text=True).stdout


@unittest.skipUnless(XFWM4 and HAVE_DISPLAY, "needs patched xfwm4 (LUXOS_XFWM4) and Xvfb (xvfb-run) with xdotool")
class WindowManager(unittest.TestCase):
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
        cls.wm = subprocess.Popen([XFWM4, "--compositor=on", "--sm-client-disable"], env=cls.env,
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


if __name__ == "__main__":
    unittest.main()
