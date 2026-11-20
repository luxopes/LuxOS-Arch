#!/usr/bin/env python3
"""LuxOS - testy plynuleho posouvani a setrvacnosti (modul GTK luxos-scroll, luxos-scrolling).

    LUXOS_XORG_DUMMY_DIR=<rozbaleny xf86-video-dummy>/usr/lib/xorg/modules \\
        python3 -m unittest packages/luxos-desktop/tests/test_luxos_scroll.py -v

Testy GUI spousti vlastni soukromy Xorg (ovladac dummy + vstupni zarizeni inputtest, viz
scroll/xinputtest.py): touchpad a kolecko posilaji skutecne udalosti XInput2 s plynulym posunem jako
xf86-input-libinput - vcetne udalosti s nulovym posunem po zvednuti prstu. Bez roota, bez uinput,
vlastni HOME, XDG_* a XDG_RUNTIME_DIR pod out/ repozitare. Bez ovladace dummy se testy GUI preskoci.
Modul se prelozi ze zdroju (nebo LUXOS_SCROLL_MODULE = sestaveny libluxos-scroll.so z baliku).

Co test neumi: skutecny touchpad (libinput, jeho rychlost a cas udalosti) - posloupnost udalosti
napodobuje to, co xf86-input-libinput posila (posuny po ~10 ms a nulovy posun po zvednuti prstu).
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
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
SRC = os.path.join(FILES, "src", "luxos-scroll.c")
APP = os.path.join(HERE, "scroll", "scroll_app.py")
WEBKIT_APP = os.path.join(HERE, "scroll", "webkit_app.py")
XINIT_FIREFOX = os.path.join(FILES, "xinit", "50-luxos-firefox-xinput2.sh")
SETTINGS_LSL = os.path.join(FILES, "lsl", "luxos-scrolling.lsl")
sys.path.insert(0, os.path.join(HERE, "scroll"))
import firefox_run  # noqa: E402
import xinputtest  # noqa: E402

OUT = os.path.join(REPO, "out")
STEP = 62.996   # krok GTK pro stranku 500 px: min(500^(2/3), 250)


def workdir(prefix):
    """Docasny adresar pod out/ repozitare (nikdy /tmp - tmpfs bere RAM)."""
    os.makedirs(OUT, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=OUT)


def build_module(dest):
    """Modul ze zdroju; LUXOS_SCROLL_MODULE = hotovy modul (sestaveni baliku)."""
    given = os.environ.get("LUXOS_SCROLL_MODULE")
    if given:
        return given
    so = os.path.join(dest, "libluxos-scroll.so")
    flags = subprocess.run(["pkg-config", "--cflags", "--libs", "gtk+-3.0", "xi", "x11"], capture_output=True, text=True,
                           check=True).stdout.split()
    subprocess.run(["gcc", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC", "-o", so, SRC, *flags, "-lm"],
                   check=True)
    return so


def has_webkit():
    try:
        import gi
        gi.require_version("WebKit2", "4.1")
        from gi.repository import WebKit2  # noqa: F401
        return True
    except (ImportError, ValueError):
        return False


def has_vte():
    try:
        import gi
        gi.require_version("Vte", "2.91")
        from gi.repository import Vte  # noqa: F401
        return True
    except (ImportError, ValueError):
        return False


class TestSources(unittest.TestCase):
    def test_module_builds_without_warnings(self):
        d = workdir("test-scroll-build-")
        self.addCleanup(shutil.rmtree, d, True)
        if os.environ.get("LUXOS_SCROLL_MODULE"):
            self.skipTest("prebuilt module given")
        self.assertTrue(os.path.exists(build_module(d)))

    def test_module_stays_resident(self):
        """Odebrani z Gtk/Modules (GTK zavola g_module_close) modul neuvolni - jinak spadnou vsechny aplikace."""
        d = workdir("test-scroll-resident-")
        self.addCleanup(shutil.rmtree, d, True)
        so = build_module(d)
        code = (
            "import ctypes, sys\n"
            "g = ctypes.CDLL('libgmodule-2.0.so.0')\n"
            "g.g_module_open.restype = ctypes.c_void_p\n"
            "g.g_module_open.argtypes = [ctypes.c_char_p, ctypes.c_int]\n"
            "g.g_module_close.argtypes = [ctypes.c_void_p]\n"
            "m = g.g_module_open(sys.argv[1].encode(), 0)\n"
            "assert m, 'open failed'\n"
            "g.g_module_close(m)\n"
            "print(sys.argv[1] in open('/proc/self/maps').read())\n")
        out = subprocess.run([sys.executable, "-c", code, so], capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "True", out.stderr)

    def test_loaded_by_xsettings(self):
        """Modul nacita xsettings Gtk/Modules (vychozi kanal i blok luxos-session)."""
        with open(os.path.join(FILES, "xdg/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml")) as f:
            self.assertIn('<property name="Modules" type="string" value="luxos-scroll"/>', f.read())
        with open(os.path.join(HERE, "..", "PKGBUILD")) as f:
            pkg = f.read()
        self.assertIn("usr/lib/gtk-3.0/modules/libluxos-scroll.so", pkg)
        self.assertIn("luxos-scrolling.lsl", pkg)

    def test_firefox_prefs(self):
        with open(os.path.join(FILES, "firefox", "luxos.js")) as f:
            js = f.read()
        for pref in ('pref("apz.gtk.kinetic_scroll.enabled", true);', 'pref("apz.gtk.pangesture.enabled", true);',
                     'pref("general.smoothScroll", true);', 'pref("general.smoothScroll.msdPhysics.enabled", true);'):
            self.assertIn(pref, js)

    def test_firefox_xinput2_env(self):
        """Relace: MOZ_USE_XINPUT2=1 (gesto posunu z touchpadu), vlastni hodnota uzivatele zustava."""
        def run(env):
            return subprocess.run(["sh", "-c", '. "$0"; printf %s "$MOZ_USE_XINPUT2"', XINIT_FIREFOX],
                                  capture_output=True, text=True, env=dict(env, PATH="/usr/bin:/bin")).stdout
        self.assertEqual(run({}), "1")
        self.assertEqual(run({"MOZ_USE_XINPUT2": "0"}), "0")
        with open(os.path.join(HERE, "..", "PKGBUILD")) as f:
            self.assertIn("etc/X11/xinit/xinitrc.d/50-luxos-firefox-xinput2.sh", f.read())

    def test_desktop_entry_translated(self):
        with open(os.path.join(FILES, "applications", "luxos-scrolling.desktop"), encoding="utf-8") as f:
            text = f.read()
        for lang in ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv"):
            self.assertIn(f"Name[{lang}]=", text)
            self.assertIn(f"Comment[{lang}]=", text)
        self.assertIn("X-XFCE-SettingsDialog", text)

    def test_ui_strings_translated(self):
        """Vsechny texty okna Posouvani maji preklad ve vsech 12 jazycich."""
        import re
        with open(SETTINGS_LSL, encoding="utf-8") as f:
            texts = set(re.findall(r'i18n\.T\("((?:[^"\\]|\\.)*)"\)', f.read()))
        self.assertGreater(len(texts), 5)
        i18n = os.path.join(REPO, "packages", "luxos-i18n", "files")
        for lang in ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv"):
            with open(os.path.join(i18n, f"{lang}.tsv"), encoding="utf-8") as f:
                have = {ln.split("\t", 1)[0] for ln in f if "\t" in ln and not ln.startswith("#")}
            missing = sorted(t for t in texts if t not in have)
            self.assertEqual(missing, [], f"{lang}.tsv")


class TestSessionBlock(unittest.TestCase):
    """Blok luxos-session: Gtk/Modules vzdy obsahuje luxos-scroll (falesny xfconf-query)."""

    def run_block(self, user, defaults=True):
        home = workdir("test-scroll-session-")
        self.addCleanup(shutil.rmtree, home, True)
        with open(os.path.join(FILES, "bin", "luxos-session"), encoding="utf-8") as f:
            src = f.read()
        start = src.index("# Plynule posouvani (modul GTK luxos-scroll)")
        end = src.index("\n# Lupa (Hledani)", start)
        fake = os.path.join(home, "bin")
        os.makedirs(fake)
        shutil.copy(os.path.join(HERE, "fake-shortcuts", "xfconf-query"), fake)
        module = os.path.join(home, "libluxos-scroll.so")
        open(module, "w").close()
        state = os.path.join(home, "xfconf.json")
        with open(state, "w") as f:
            json.dump(user, f)
        env = {"PATH": fake + ":/usr/bin:/bin", "FAKE_XFCONF": state, "HOME": home, "LUXOS_SCROLL_MODULE": module}
        if defaults:
            env["FAKE_XFCONF_DEFAULTS"] = os.path.join(FILES, "xdg/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml")
        r = subprocess.run(["bash", "-c", src[start:end]], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(state) as f:
            return json.load(f)

    def test_default_kept(self):
        # vychozi hodnota z /etc/xdg staci, uzivatelsky profil se nemeni
        self.assertEqual(self.run_block({}), {})

    def test_added_to_other_modules(self):
        data = self.run_block({"/Gtk/Modules": "canberra-gtk-module"})
        self.assertEqual(data["/Gtk/Modules"], "canberra-gtk-module:luxos-scroll")

    def test_without_default(self):
        self.assertEqual(self.run_block({}, defaults=False)["/Gtk/Modules"], "luxos-scroll")

    def test_not_duplicated(self):
        data = self.run_block({"/Gtk/Modules": "luxos-scroll:canberra-gtk-module"})
        self.assertEqual(data["/Gtk/Modules"], "luxos-scroll:canberra-gtk-module")


@unittest.skipUnless(shutil.which("lslc"), "needs lslc (LSL compiler)")
class TestSettingsCli(unittest.TestCase):
    """luxos-scrolling status / kinetic / smooth-wheel (zapis souboru, ktery modul sleduje)."""

    @classmethod
    def setUpClass(cls):
        cls.dir = workdir("test-scroll-cli-")
        cls.bin = os.path.join(cls.dir, "luxos-scrolling")
        r = subprocess.run(["lslc", "--target", "linux-x86_64-gnu", "--system-bindings", os.path.dirname(SETTINGS_LSL), SETTINGS_LSL, cls.bin],
                           capture_output=True, text=True, cwd=os.path.dirname(SETTINGS_LSL))
        if r.returncode != 0:
            raise unittest.SkipTest("lslc failed: " + r.stderr[-500:])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, True)

    def run_cli(self, cfg, *args):
        env = {"PATH": "/usr/bin:/bin", "HOME": cfg, "XDG_CONFIG_HOME": os.path.join(cfg, ".config")}
        return subprocess.run([self.bin, *args], env=env, capture_output=True, text=True, timeout=20)

    def test_status_defaults_and_changes(self):
        cfg = tempfile.mkdtemp(dir=self.dir)
        self.assertEqual(self.run_cli(cfg, "status").stdout, "smooth_wheel=true\nkinetic=true\n")
        self.assertEqual(self.run_cli(cfg, "kinetic", "off").returncode, 0)
        self.assertEqual(self.run_cli(cfg, "status").stdout, "smooth_wheel=true\nkinetic=false\n")
        self.assertEqual(self.run_cli(cfg, "smooth-wheel", "off").returncode, 0)
        self.assertEqual(self.run_cli(cfg, "kinetic", "on").returncode, 0)
        self.assertEqual(self.run_cli(cfg, "status").stdout, "smooth_wheel=false\nkinetic=true\n")
        with open(os.path.join(cfg, ".config", "luxos", "scrolling.conf")) as f:
            text = f.read()
        self.assertIn("[scrolling]\nsmooth_wheel=false\nkinetic=true\n", text)
        self.assertFalse(os.path.exists(os.path.join(cfg, ".config", "luxos", "scrolling.conf.tmp")))

    def test_bad_arguments(self):
        cfg = tempfile.mkdtemp(dir=self.dir)
        self.assertEqual(self.run_cli(cfg, "kinetic", "maybe").returncode, 2)
        self.assertEqual(self.run_cli(cfg, "bogus").returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(cfg, ".config", "luxos", "scrolling.conf")))

    def test_hand_edited_file(self):
        cfg = tempfile.mkdtemp(dir=self.dir)
        os.makedirs(os.path.join(cfg, ".config", "luxos"))
        with open(os.path.join(cfg, ".config", "luxos", "scrolling.conf"), "w") as f:
            f.write("[other]\nkinetic=false\n[scrolling]\n# comment\n kinetic = No \nsmooth_wheel=junk\n")
        self.assertEqual(self.run_cli(cfg, "status").stdout, "smooth_wheel=true\nkinetic=false\n")


@unittest.skipUnless(xinputtest.available(), "needs Xorg + inputtest + dummy driver (LUXOS_XORG_DUMMY_DIR) + xinput")
@unittest.skipUnless(shutil.which("xdotool"), "needs xdotool")
class ScrollGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = workdir("test-scroll-gui-")
        cls.module = build_module(cls.work)
        cls.server = xinputtest.Server(os.path.join(cls.work, "x"))

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        shutil.rmtree(cls.work, True)

    def setUp(self):
        self.home = tempfile.mkdtemp(dir=self.work, prefix="home-")
        self.runtime = os.path.join(self.home, "runtime")
        os.makedirs(self.runtime, mode=0o700)
        os.chmod(self.runtime, 0o700)
        # ~/.config/luxos zaklada luxos-session pri kazdem prihlaseni (modul sleduje soubor v nem)
        os.makedirs(os.path.join(self.home, ".config", "luxos"))
        self.app = None

    def tearDown(self):
        if self.app:
            if self.app.poll() is None:
                self.app.terminate()
                self.app.wait(10)
            self.app.stdout.close()

    def env(self, module=True, **extra):
        h = self.home
        env = {"DISPLAY": self.server.display, "PATH": "/usr/bin:/bin", "HOME": h, "XDG_RUNTIME_DIR": self.runtime,
               "XDG_CONFIG_HOME": h + "/.config", "XDG_CACHE_HOME": h + "/.cache", "XDG_DATA_HOME": h + "/.local/share",
               "XDG_STATE_HOME": h + "/.local/state", "XDG_CONFIG_DIRS": h + "/etc-xdg", "XDG_DATA_DIRS": "/usr/share",
               "NO_AT_BRIDGE": "1", "GSETTINGS_BACKEND": "memory", "GDK_BACKEND": "x11", "LANG": "C.UTF-8",
               "GTK_THEME": "Adwaita", "GTK_MODULES": self.module if module else ""}
        env.update(extra)
        for k, v in env.items():   # pojistka: nic nesmi ukazovat do skutecneho profilu
            if k.startswith("XDG_") and k != "XDG_DATA_DIRS":
                self.assertTrue(v.startswith(self.work), k)
        return env

    def config(self, text):
        d = os.path.join(self.home, ".config", "luxos")
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, "scrolling.conf.tmp")
        with open(tmp, "w") as f:
            f.write(text)
        os.rename(tmp, os.path.join(d, "scrolling.conf"))   # jako luxos-scrolling (atomicky)

    def gtk_settings(self, text):
        d = os.path.join(self.home, ".config", "gtk-3.0")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "settings.ini"), "w") as f:
            f.write("[Settings]\n" + text)

    def start(self, mode="list", module=True, pointer=(0.5, 0.5), script=APP, **extra):
        self.log = os.path.join(self.home, "log")
        self.err = os.path.join(self.home, "err")
        with open(self.err, "w") as err:
            self.app = subprocess.Popen([sys.executable, script, self.log, mode], env=self.env(module, **extra),
                                        stdout=subprocess.PIPE, stderr=err, text=True)
        line = self.app.stdout.readline().split()
        with open(self.err) as err:
            self.assertTrue(line and line[0] == "ready", err.read())
        x, y, w, h = map(int, line[1:5])
        subprocess.run(["xdotool", "mousemove", str(x + int(w * pointer[0])), str(y + int(h * pointer[1]))],
                       env=self.env(), check=True)
        time.sleep(0.3)
        return x, y, w, h

    def rows(self):
        with open(self.log) as f:
            return [tuple(map(float, ln.split())) for ln in f if ln[0].isdigit()]

    def handler_calls(self):
        with open(self.log) as f:
            return sum(1 for ln in f if ln.startswith("handler"))

    def now(self):
        return time.monotonic() * 1000

    def flick(self, sign=1, events=12, delta=60, stop=True):
        """Rychle tazeni dvema prsty: posun po 10 ms, pak zvednuti prstu (nulovy posun jako libinput)."""
        tp = self.server.touchpad
        tp.motion(scroll_y=0)            # GDK po prepnuti zarizeni zahodi prvni hodnotu
        tp.sync()
        time.sleep(0.05)
        for _ in range(events):
            tp.motion(scroll_y=sign * delta)
            time.sleep(0.010)
        if stop:
            tp.motion(scroll_y=0)
        tp.sync()
        return self.now()

    def wheel(self, notches=3, sign=1, interval=0.06, device=None, prime=True):
        m = device or self.server.mouse
        if prime:                        # GDK po vstupu do okna / prepnuti zarizeni prvni hodnotu nepocita
            m.motion(scroll_y=0)
            m.sync()
            time.sleep(0.05)
        for _ in range(notches):
            m.motion(scroll_y=sign * 120)
            m.sync()
            time.sleep(interval)
        return self.now()

    def finish(self, wait=1.6):
        time.sleep(wait)
        self.app.terminate()
        self.app.wait(10)
        return self.rows()

    @staticmethod
    def value_at(rows, t):
        v = rows[0][1] if rows else 0.0
        for rt, rv in rows:
            if rt > t:
                break
            v = rv
        return v

    @staticmethod
    def speed(rows, t0, t1):
        a = ScrollGui.value_at(rows, t0)
        b = ScrollGui.value_at(rows, t1)
        return abs(b - a) / (t1 - t0) * 1000.0

    # ---- setrvacnost touchpadu ----
    def test_flick_glides_and_decelerates(self):
        self.start()
        t = self.flick()
        rows = self.finish()
        at_lift = self.value_at(rows, t + 25)
        final = rows[-1][1]
        self.assertGreater(final - at_lift, 200, "content keeps moving after lifting the fingers")
        later = [r for r in rows if r[0] > t + 300]
        self.assertTrue(later, "still moving 300 ms after the last touchpad event")
        early, late = self.speed(rows, t + 30, t + 130), self.speed(rows, t + 330, t + 430)
        self.assertGreater(early, late * 1.5, f"decelerates ({early:.0f} -> {late:.0f} px/s)")
        self.assertLess(rows[-1][0] - t, 1590, "stops by itself")

    def test_no_glide_without_lift_event(self):
        """Kontrola testu: bez nuloveho posunu (prsty zustaly lezet) se nic nedeje."""
        self.start()
        t = self.flick(stop=False)
        rows = self.finish(1.0)
        self.assertFalse([r for r in rows if r[0] > t + 40])

    def test_kinetic_off(self):
        self.config("[scrolling]\nkinetic=false\n")
        self.start()
        t = self.flick()
        rows = self.finish(1.0)
        self.assertGreater(rows[-1][1], 300, "touchpad scrolling itself works")
        self.assertFalse([r for r in rows if r[0] > t + 40], "no glide with kinetic=false")

    def test_kinetic_toggle_applies_to_open_window(self):
        self.start()
        self.config("[scrolling]\nkinetic=false\n")
        time.sleep(0.5)
        t = self.flick()
        time.sleep(1.0)
        rows = self.rows()
        self.assertFalse([r for r in rows if r[0] > t + 40], "kinetic=false applies without restarting the app")
        self.config("[scrolling]\nkinetic=true\n")
        time.sleep(0.5)
        t = self.flick()
        rows = self.finish(1.4)
        self.assertGreater(rows[-1][1] - self.value_at(rows, t + 25), 200, "and back on")

    def test_touch_stops_glide(self):
        self.start()
        t = self.flick()
        time.sleep(0.15)
        self.server.touchpad.motion(dx=2, dy=0)     # prst na touchpadu posune kurzor
        self.server.touchpad.sync()
        touch = self.now()
        rows = self.finish(1.0)
        self.assertGreater(self.value_at(rows, touch) - self.value_at(rows, t + 25), 30, "was gliding")
        after = [r for r in rows if r[0] > touch + 40]
        self.assertFalse(after, f"glide stops on touch ({len(after)} changes after)")

    def test_click_stops_glide(self):
        self.start()
        self.flick()
        time.sleep(0.15)
        self.server.touchpad.button(1, True)       # klepnuti
        self.server.touchpad.button(1, False)
        self.server.touchpad.sync()
        touch = self.now()
        rows = self.finish(1.0)
        self.assertFalse([r for r in rows if r[0] > touch + 40])

    def test_touch_without_module_keeps_gliding(self):
        """Srovnani: samotne GTK pri dotyku dal jede (libinput na X11 polozeni prstu neposila)."""
        self.start(module=False)
        self.flick()
        time.sleep(0.15)
        self.server.touchpad.motion(dx=2, dy=0)
        self.server.touchpad.sync()
        touch = self.now()
        rows = self.finish(1.0)
        self.assertTrue([r for r in rows if r[0] > touch + 100])

    def test_mouse_move_does_not_stop_glide(self):
        """Pohyb jinou mysi setrvacnost nezastavi (jen dotyk touchpadu nebo klik)."""
        self.start()
        self.flick()
        time.sleep(0.1)
        self.server.mouse.motion(dx=2, dy=0)
        self.server.mouse.sync()
        moved = self.now()
        rows = self.finish(1.2)
        self.assertTrue([r for r in rows if r[0] > moved + 100])

    def test_module_disabled_by_env(self):
        self.config("[scrolling]\nkinetic=false\n")
        self.start(LUXOS_SCROLL="0")
        t = self.flick()
        rows = self.finish(1.2)
        self.assertTrue([r for r in rows if r[0] > t + 200], "LUXOS_SCROLL=0: GTK alone (glides)")

    # ---- kolecko ----
    def assert_animated(self, rows, notches, t_end):
        self.assertAlmostEqual(rows[-1][1], notches * STEP, delta=1.0, msg="same distance as GTK")
        steps = [b[1] - a[1] for a, b in zip([(0, 0.0)] + rows, rows)]
        self.assertGreaterEqual(len(rows), notches * 4, f"several frames per notch: {rows}")
        self.assertLess(max(abs(s) for s in steps), STEP * 0.8, f"no jumps: {steps}")
        self.assertTrue(all(s >= -0.01 for s in steps), "moves one way")

    def assert_jumps(self, rows, notches):
        self.assertEqual(len(rows), notches, f"one change per notch: {rows}")
        self.assertAlmostEqual(rows[-1][1], notches * STEP, delta=1.0)

    def test_wheel_animated(self):
        self.start()
        t = self.wheel(3)
        rows = self.finish(0.6)
        self.assert_animated(rows, 3, t)
        self.assertLess(rows[-1][0] - t, 300, "ends ~200 ms after the last notch")

    def test_wheel_without_module_jumps(self):
        self.start(module=False)
        self.wheel(3)
        self.assert_jumps(self.finish(0.5), 3)

    def test_first_notch_after_entering_window(self):
        """Prvni zarazka po vstupu ukazatele do okna se neztrati (GDK na X11 ji jinak zahodi)."""
        self.start()
        self.wheel(3, prime=False)
        rows = self.finish(0.6)
        self.assertAlmostEqual(rows[-1][1], 3 * STEP, delta=1.0, msg=str(rows))

    def test_first_notch_lost_without_module(self):
        """Srovnani: samotne GTK prvni zarazku po vstupu do okna zahodi."""
        self.start(module=False)
        self.wheel(3, prime=False)
        rows = self.finish(0.5)
        self.assertAlmostEqual(rows[-1][1], 2 * STEP, delta=1.0, msg=str(rows))

    def test_first_notch_after_touchpad(self):
        """Prepnuti z touchpadu na mys (jine zarizeni): prvni zarazka nahoru i dolu plati."""
        self.config("[scrolling]\nkinetic=false\n")
        self.start()
        self.flick(events=10, delta=120)          # touchpad dolu
        time.sleep(0.5)
        before = self.rows()[-1][1]
        self.wheel(1, sign=-1, prime=False)       # mys nahoru, jedna zarazka
        time.sleep(0.5)
        after_up = self.rows()[-1][1]
        self.assertAlmostEqual(after_up, before - STEP, delta=1.0)
        self.flick(events=2, delta=120)
        time.sleep(0.5)
        before = self.rows()[-1][1]
        self.wheel(1, prime=False)
        rows = self.finish(0.5)
        self.assertAlmostEqual(rows[-1][1], before + STEP, delta=1.0)

    def test_fast_wheel_accumulates(self):
        """Rychle otaceni: kazda zarazka posune cil dal, nic se neztrati."""
        self.start()
        self.wheel(6, interval=0.015)
        rows = self.finish(0.7)
        self.assertAlmostEqual(rows[-1][1], 6 * STEP, delta=1.0)

    def test_wheel_up_down(self):
        self.start()
        self.wheel(4)
        time.sleep(0.4)
        self.wheel(2, sign=-1)
        rows = self.finish(0.6)
        self.assertAlmostEqual(rows[-1][1], 2 * STEP, delta=1.0)

    def test_wheel_stops_at_end(self):
        self.start()
        self.wheel(2, sign=-1)       # nahoru na zacatku: nic
        rows = self.finish(0.5)
        self.assertEqual(rows, [])

    def test_xtest_wheel_buttons(self):
        """Kolecko bez plynulych udalosti (tlacitka 4/5, xdotool) je take plynule."""
        self.start()
        subprocess.run(["xdotool", "click", "--repeat", "2", "--delay", "60", "5"], env=self.env(), check=True)
        t = self.now()
        rows = self.finish(0.6)
        self.assert_animated(rows, 2, t)

    def test_smooth_wheel_off(self):
        self.config("[scrolling]\nsmooth_wheel=false\n")
        self.start()
        self.wheel(3)
        self.assert_jumps(self.finish(0.5), 3)

    def test_reduce_motion(self):
        """Vypnute animace (omezeni pohybu, Uspora baterie): kolecko skace jako dosud."""
        self.gtk_settings("gtk-enable-animations=false\n")
        self.start()
        self.wheel(3)
        self.assert_jumps(self.finish(0.5), 3)

    def test_ctrl_wheel_untouched(self):
        """Ctrl+kolecko (zoom v aplikacich) modul neanimuje."""
        self.start()
        kb = self.server.keyboard
        kb.key(37, True)                 # Control_L
        kb.sync()
        self.wheel(2)
        kb.key(37, False)
        kb.sync()
        self.assert_jumps(self.finish(0.5), 2)

    def test_app_handler_gets_wheel(self):
        """Vlastni obsluha posunu v aplikaci ma prednost: dostane vsechny udalosti, nic se neanimuje."""
        self.start("handler")
        self.wheel(3)
        time.sleep(0.5)
        self.assertEqual(self.handler_calls(), 4)    # i "nulova" prvni udalost
        self.assertEqual(self.finish(0.1), [])

    def test_nested_scrolled_window(self):
        """Kolecko nad vnitrnim vodorovnym seznamem posouva vnejsi stranku (plynule)."""
        self.start("nested", pointer=(0.5, 0.5))
        t = self.wheel(2)
        self.assert_animated(self.finish(0.6), 2, t)

    def test_touchpad_not_animated(self):
        """Touchpad posouva primo po pixelech (zadna animace navic)."""
        self.config("[scrolling]\nkinetic=false\n")
        self.start()
        tp = self.server.touchpad
        tp.motion(scroll_y=0)
        tp.sync()
        time.sleep(0.05)
        for _ in range(3):
            tp.motion(scroll_y=15)       # 1/8 zarazky
            tp.sync()
            time.sleep(0.05)
        rows = self.finish(0.4)
        self.assertEqual(len(rows), 3, rows)
        self.assertAlmostEqual(rows[-1][1], 3 * STEP / 8, delta=0.5)

    # ---- WebKitGTK (Posta, napoveda) ----
    @unittest.skipUnless(has_webkit(), "needs WebKitGTK 4.1")
    def test_webkit_glides(self):
        """WebKitGTK dojede setrvacnosti sam (stop z X11 -> ScrollAnimationKinetic)."""
        self.start(script=WEBKIT_APP)
        t = self.flick(events=12, delta=60)
        rows = self.finish(1.5)
        self.assertTrue(rows, "page scrolled")
        self.assertGreater(rows[-1][1] - self.value_at(rows, t + 40), 100, f"glides: {rows[-5:]}")

    @unittest.skipUnless(has_webkit(), "needs WebKitGTK 4.1")
    def test_webkit_kinetic_off(self):
        """Vypnuta setrvacnost plati i pro WebKitGTK (opozdeny stop, rychlost vyjde nulova)."""
        self.config("[scrolling]\nkinetic=false\n")
        self.start(script=WEBKIT_APP)
        t = self.flick(events=12, delta=60)
        rows = self.finish(1.2)
        self.assertTrue(rows, "page scrolled")
        moved = self.value_at(rows, 10 ** 12) - self.value_at(rows, t + 60)
        self.assertLess(moved, 5, f"no glide: {rows[-5:]}")

    # ---- Firefox (gesto posunu z XInput2 + volby LuxOS) ----
    def firefox(self, kinetic=True):
        if not kinetic:
            self.config("[scrolling]\nkinetic=false\n")
        # prostredi relace LuxOS: MOZ_USE_XINPUT2 ze skriptu xinitrc.d (jako ho nacte Xsession)
        xi2 = subprocess.run(["sh", "-c", '. "$0"; printf %s "$MOZ_USE_XINPUT2"', XINIT_FIREFOX],
                             capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}).stdout
        env = self.env(MOZ_CRASHREPORTER_DISABLE="1", MOZ_USE_XINPUT2=xi2)
        ff = firefox_run.Firefox(self.home, env, os.path.join(FILES, "firefox", "luxos.js"))
        self.addCleanup(ff.stop)
        if not ff.ready.wait(60):
            self.skipTest("Firefox did not start in the test display")
        subprocess.run(["xdotool", "mousemove", "400", "450"], env=self.env(), check=True)
        time.sleep(0.5)
        return ff

    @unittest.skipUnless(firefox_run.firefox(), "needs Firefox")
    def test_firefox_glides(self):
        ff = self.firefox()
        t = self.flick(events=12, delta=60)
        time.sleep(2.0)
        rows = list(ff.lines)
        self.assertTrue(rows, "page scrolled")
        # bez setrvacnosti stranka po zvednuti prstu jen dozene vstup (softwarove kresleni, < 200 px)
        self.assertGreater(rows[-1][1] - self.value_at(rows, t + 60), 300, f"Firefox glides: {rows[-5:]}")

    @unittest.skipUnless(firefox_run.firefox(), "needs Firefox")
    def test_firefox_kinetic_off(self):
        ff = self.firefox(kinetic=False)
        t = self.flick(events=12, delta=60)
        time.sleep(1.5)
        rows = list(ff.lines)
        self.assertTrue(rows, "page scrolled")
        self.assertLess(rows[-1][1] - self.value_at(rows, t + 120), 5, f"no glide: {rows[-5:]}")

    @unittest.skipUnless(firefox_run.firefox(), "needs Firefox")
    def test_firefox_wheel_smooth(self):
        ff = self.firefox()
        self.wheel(1)
        time.sleep(0.8)
        self.assertGreaterEqual(len(ff.lines), 4, f"one notch scrolls in several frames: {ff.lines}")

    # ---- nacteni pres XSETTINGS Gtk/Modules (jako v relaci LuxOS z xfsettingsd) ----
    def test_loaded_through_xsettings(self):
        """Modul z Gtk/Modules (bez GTK_MODULES): kolecko plynule a dotyk zastavi setrvacnost
        (vlastni zpracovani udalosti se nastavi i pri nacteni pres XSETTINGS pri startu aplikace)."""
        mgr = subprocess.Popen([sys.executable, os.path.join(HERE, "scroll", "xsettings_manager.py"),
                                "Gtk/Modules=" + self.module], env=self.env(), stdout=subprocess.PIPE, text=True)
        self.addCleanup(mgr.stdout.close)
        self.addCleanup(mgr.wait, 10)
        self.addCleanup(mgr.terminate)
        self.assertEqual(mgr.stdout.readline().strip(), "ready")
        self.start(module=False)
        t = self.wheel(2)
        time.sleep(0.5)
        rows = self.rows()
        self.assert_animated(rows, 2, t)
        t = self.flick()
        time.sleep(0.15)
        self.server.touchpad.motion(dx=2, dy=0)
        self.server.touchpad.sync()
        touch = self.now()
        rows = self.finish(0.8)
        self.assertGreater(self.value_at(rows, touch) - self.value_at(rows, t + 25), 30, "was gliding")
        self.assertFalse([r for r in rows if r[0] > touch + 40], "touch stops the glide")

    def test_loaded_into_running_app(self):
        """Gtk/Modules zmenene za behu aplikace (napr. luxos-session pri prihlaseni): modul se nacte do
        bezici aplikace bez padu a kolecko je plynule; cizi zpracovani udalosti se neprepisuje."""
        xs = os.path.join(HERE, "scroll", "xsettings_manager.py")
        first = subprocess.Popen([sys.executable, xs, "Gtk/FontName=Sans 10"], env=self.env(), stdout=subprocess.PIPE,
                                 text=True)
        self.addCleanup(first.stdout.close)
        self.addCleanup(first.wait, 10)
        self.addCleanup(first.terminate)
        self.assertEqual(first.stdout.readline().strip(), "ready")
        self.start(module=False)
        self.wheel(1)
        time.sleep(0.4)
        self.assertEqual(len(self.rows()), 1, "no module yet: the wheel jumps")
        second = subprocess.Popen([sys.executable, xs, "Gtk/FontName=Sans 10", "Gtk/Modules=" + self.module],
                                  env=self.env(), stdout=subprocess.PIPE, text=True)
        self.addCleanup(second.stdout.close)
        self.addCleanup(second.wait, 10)
        self.addCleanup(second.terminate)
        self.assertEqual(second.stdout.readline().strip(), "ready")
        time.sleep(0.8)
        before = len(self.rows())
        self.wheel(2)
        time.sleep(0.5)
        rows = self.rows()[before:]
        self.assertIsNone(self.app.poll(), "app still runs")
        self.assertGreaterEqual(len(rows), 8, f"wheel animated after the module loaded: {rows}")

    # ---- okno Nastaveni > Posouvani ----
    @unittest.skipUnless(shutil.which("lslc"), "needs lslc (LSL compiler)")
    def test_settings_window_switch(self):
        """Prepinac v okne zapise volbu a otevrena aplikace ji hned pouzije."""
        binary = os.path.join(self.work, "luxos-scrolling")
        if not os.path.exists(binary):
            subprocess.run(["lslc", "--target", "linux-x86_64-gnu", "--system-bindings", os.path.dirname(SETTINGS_LSL), SETTINGS_LSL, binary], check=True,
                           capture_output=True, cwd=os.path.dirname(SETTINGS_LSL))
        self.start(pointer=(0.5, 0.5))
        win = subprocess.Popen([binary], env=self.env(module=False, LUXOS_I18N_DIR="/nonexistent"),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(win.wait, 10)
        self.addCleanup(win.terminate)
        wid = ""
        for _ in range(50):
            wid = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "luxos-scrolling"],
                                 capture_output=True, text=True, env=self.env()).stdout.split()
            if wid:
                break
            time.sleep(0.1)
        self.assertTrue(wid, "settings window")
        time.sleep(0.5)
        # bez spravce oken jde klavesnice do okna pod mysi; GTK da fokus prvnimu prepinaci, Tab = setrvacnost
        subprocess.run(["xdotool", "mousemove", "--window", wid[0], "20", "330", "key", "Tab", "space"],
                       env=self.env(), check=True)
        conf = os.path.join(self.home, ".config", "luxos", "scrolling.conf")
        if os.environ.get("SHOT"):
            subprocess.run([sys.executable, "-c", "import gi,sys; gi.require_version('Gdk','3.0'); from gi.repository import Gdk; r=Gdk.get_default_root_window(); Gdk.pixbuf_get_from_window(r,0,0,r.get_width(),r.get_height()).savev(sys.argv[1],'png',[],[])", os.environ["SHOT"]], env=self.env())
        for _ in range(30):
            if os.path.exists(conf):
                break
            time.sleep(0.1)
        with open(conf) as f:
            self.assertIn("kinetic=false", f.read())
        subprocess.run(["xdotool", "mousemove", "300", "250"], env=self.env(), check=True)   # zpet nad seznam
        time.sleep(0.5)
        t = self.flick()
        rows = self.finish(1.0)
        self.assertFalse([r for r in rows if r[0] > t + 40], "open app follows the switch")

    # ---- terminal (VTE s posouvanim po pixelech jako luxos-terminal) ----
    @unittest.skipUnless(has_vte(), "needs VTE")
    def test_vte_pixels_glide_and_smooth_wheel(self):
        self.start("vte", VTE_PIXELS="1")
        rows0 = self.rows()
        top = rows0[-1][1] if rows0 else None
        t = self.flick(sign=-1)
        time.sleep(1.4)
        rows = [r for r in self.rows() if r[0] > t - 200]
        self.assertTrue([r for r in rows if r[0] > t + 300], "terminal history glides")
        self.assertTrue(any(abs(v - round(v / 17.0) * 17.0) > 0.5 for _, v in rows) or top is None, "pixel steps")
        t2 = self.wheel(2, sign=-1)
        rows = [r for r in self.finish(0.5) if r[0] > t2 - 200]
        self.assertGreaterEqual(len(rows), 6, "wheel animates the history")

    @unittest.skipUnless(has_vte(), "needs VTE")
    def test_vte_lines_baseline(self):
        """Srovnani: VTE po radcich (vychozi) setrvacnost nema - proto luxos-terminal posouva po pixelech."""
        self.start("vte")
        t = self.flick(sign=-1)
        rows = self.finish(1.0)
        self.assertFalse([r for r in rows if r[0] > t + 40])


if __name__ == "__main__":
    unittest.main()
