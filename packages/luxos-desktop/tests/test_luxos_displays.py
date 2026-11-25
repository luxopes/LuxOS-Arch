"""Testy pro Monitory na X11: luxos_xrandr.lsl (parsovani xrandr, ulozene rezimy, velikost textu), skript
luxos-displays s pomocnikem v LSL a stranka Monitory okna Nastaveni (luxos-displays-settings je odkaz na
luxos-settings; vlastni Xvfb, rizene pres luxos_testctl).

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_displays.py -v

Funkce luxos_xrandr.lsl vola tests/lsl/luxos-xrandr-probe.lsl (luxos_xrandr_lsl.py). Pouziva falesny
xrandr/xfconf-query z fake-displays, skutecne nastaveni uzivatele nemeni. LUXOS_TEST_SHOTS=adresar ulozi snimky.
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
BIN = os.path.normpath(os.path.join(HERE, "..", "files", "bin"))
FAKE = os.path.join(HERE, "fake-displays")
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402
import luxos_xrandr_lsl as lx  # noqa: E402
from luxos_xrandr_lsl import ld  # noqa: E402

# Skutecny vystup xrandr --current (notebook + monitor, HDMI otoceny, odpojeny DP)
REAL = """Screen 0: minimum 320 x 200, current 3000 x 1920, maximum 16384 x 16384
eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 344mm x 194mm
   1920x1080     60.02*+  60.01    59.97    48.01
   1680x1050     60.02
   1280x720      60.00    59.99
   1920x1080i    60.00
HDMI-1 connected 1080x1920+1920+0 left (normal left inverted right x axis y axis) 527mm x 296mm
   1920x1080     60.00 +  74.97    50.00    59.94    30.00
   1920x1080i    60.00    50.00
   1680x1050     59.88
   2560x1440     59.95*
   1280x720      60.00    50.00
DP-1 disconnected (normal left inverted right x axis y axis)
DP-2 connected (normal left inverted right x axis y axis)
   3840x2160     60.00 +  30.00
   1920x1080     60.00
"""


def make_edid(model):
    """Minimalni EDID (128 B) s nazvem modelu v deskriptoru 0xFC."""
    data = bytearray(128)
    data[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    desc = b"\x00\x00\x00\xfc\x00" + (model.encode() + b"\n").ljust(13, b" ")
    data[72:90] = desc
    return data.hex()


EDID_DELL = make_edid("DELL U2419H")


class Parse(unittest.TestCase):
    def setUp(self):
        self.outs = {o["name"]: o for o in ld.parse(REAL)}

    def test_outputs(self):
        self.assertEqual(list(self.outs), ["eDP-1", "HDMI-1", "DP-1", "DP-2"])
        e = self.outs["eDP-1"]
        self.assertTrue(e["connected"] and e["primary"] and e["active"])
        self.assertEqual(e["geometry"], [1920, 1080, 0, 0])
        self.assertEqual(e["mm"], [344, 194])
        h = self.outs["HDMI-1"]
        self.assertFalse(h["primary"])
        self.assertEqual(h["rotation"], "left")
        self.assertEqual(h["geometry"], [1080, 1920, 1920, 0])
        self.assertFalse(self.outs["DP-1"]["connected"])
        # pripojeny, ale vypnuty
        d = self.outs["DP-2"]
        self.assertTrue(d["connected"])
        self.assertFalse(d["active"])
        self.assertIsNone(d["geometry"])

    def test_rates_and_flags(self):
        e = self.outs["eDP-1"]
        self.assertEqual(ld.current_mode(e), ["1920x1080", "60.02"])
        self.assertEqual(ld.preferred_mode(e), ["1920x1080", "60.02"])
        self.assertEqual(ld.find_mode(e, "1920x1080")["rates"], ["60.02", "60.01", "59.97", "48.01"])
        h = self.outs["HDMI-1"]
        # "+" oddelene mezerou patri k predchozi frekvenci
        self.assertEqual(ld.preferred_mode(h), ["1920x1080", "60.00"])
        self.assertEqual(ld.current_mode(h), ["2560x1440", "59.95"])
        self.assertEqual(ld.current_mode(self.outs["DP-2"]), [None, None])

    def test_choices(self):
        h = self.outs["HDMI-1"]
        ch = ld.resolution_choices(h)
        names = [n for n, _r in ch]
        self.assertEqual(names, ["2560x1440", "1920x1080", "1680x1050", "1280x720"])   # bez prokladanych
        self.assertEqual([n for n, rec in ch if rec], ["1920x1080"])

    def test_format(self):
        self.assertEqual(ld.fmt_rate("60.00"), "60 Hz")
        self.assertEqual(ld.fmt_rate("59.94"), "59.94 Hz")
        self.assertEqual(ld.fmt_rate("74.97"), "74.97 Hz")
        self.assertEqual(ld.fmt_mode("2560x1440"), "2560 × 1440")

    def test_best_rate(self):
        h = self.outs["HDMI-1"]
        self.assertEqual(ld.best_rate(ld.find_mode(h, "1920x1080")), "60.00")     # doporucena
        self.assertEqual(ld.best_rate(ld.find_mode(h, "1280x720")), "60.00")      # nejvyssi
        self.assertEqual(ld.best_rate(ld.find_mode(h, "1680x1050")), "59.88")

    def test_edid(self):
        text = ("HDMI-1 connected 1920x1080+0+0 (normal left inverted right x axis y axis) 527mm x 296mm\n"
                "\tEDID: \n" + "".join("\t\t" + EDID_DELL[i:i + 32] + "\n" for i in range(0, 256, 32)) +
                "\tnon-desktop: 0 \n\t\tsupported: 0, 1\n   1920x1080     60.00*+\n")
        o = ld.parse(text)[0]
        self.assertEqual(o["edid"], EDID_DELL)
        self.assertEqual(ld.edid_name(o["edid"]), "DELL U2419H")
        self.assertEqual(ld.current_mode(o), ["1920x1080", "60.00"])   # vlastnosti nepokazi rezimy
        self.assertEqual(len(ld.edid_id(o["edid"])), 12)
        self.assertEqual(ld.edid_name(""), "")
        self.assertEqual(ld.edid_name("zz"), "")
        self.assertEqual(ld.output_key({"name": "eDP-1", "edid": ""}), "eDP-1|")

    def test_garbage(self):
        self.assertEqual(ld.parse(""), [])
        self.assertEqual(ld.parse("Can't open display\n"), [])


class SavedArgs(unittest.TestCase):
    def setUp(self):
        self.outs = {o["name"]: o for o in ld.parse(REAL)}

    def test_entry_default_is_none(self):
        h = self.outs["HDMI-1"]
        self.assertIsNone(ld.entry_for(h, "1920x1080", "60.00", "normal"))
        self.assertEqual(ld.entry_for(h, "1920x1080", "60.00", "left"),
                         {"mode": "1920x1080", "rate": "60.00", "rotate": "left"})
        self.assertEqual(ld.entry_for(h, "1280x720", "50.00", "normal"),
                         {"mode": "1280x720", "rate": "50.00", "rotate": "normal"})

    def test_output_args(self):
        h = self.outs["HDMI-1"]
        self.assertEqual(ld.output_args(h, {"mode": "1280x720", "rate": "50.00", "rotate": "normal"}),
                         ["--mode", "1280x720", "--rate", "50.00", "--rotate", "normal"])
        # neexistujici frekvence: jen rezim
        self.assertEqual(ld.output_args(h, {"mode": "1280x720", "rate": "75.00", "rotate": "normal"}),
                         ["--mode", "1280x720", "--rotate", "normal"])
        # monitor rezim nenabizi: doporuceny rezim, otoceni zustane
        self.assertIsNone(ld.output_args(h, {"mode": "800x600", "rotate": "normal"}))
        self.assertEqual(ld.output_args(h, {"mode": "800x600", "rotate": "right"}), ["--auto", "--rotate", "right"])
        # neplatne otoceni
        self.assertEqual(ld.output_args(h, {"mode": "1280x720", "rotate": "sideways"})[-1], "normal")
        self.assertIsNone(ld.output_args(self.outs["DP-1"], {"mode": "1920x1080"}))
        self.assertIsNone(ld.output_args(h, None))

    def test_all_output_args_match_by_edid(self):
        outs = list(self.outs.values())
        entries = {"HDMI-1|": {"mode": "1680x1050", "rate": "59.88", "rotate": "normal"},
                   "HDMI-1|0123456789ab": {"mode": "1280x720", "rotate": "normal"},
                   "DP-1|": {"mode": "1920x1080", "rotate": "normal"}}
        # HDMI-1 ve vzorku: plocha 1080x1920 neodpovida rezimu 2560x1440 = zbyle meritko -> --scale 1x1
        self.assertEqual(ld.all_output_args(outs, entries),
                         [["HDMI-1", ["--mode", "1680x1050", "--rate", "59.88", "--rotate", "normal", "--scale", "1x1"]]])

    def test_save_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "displays.json")
            self.assertEqual(ld.load(p), {})
            ld.save({"HDMI-1|": {"mode": "1280x720", "rotate": "normal"}}, p)
            self.assertEqual(ld.load(p), {"HDMI-1|": {"mode": "1280x720", "rotate": "normal"}})
            with open(p, "w") as f:
                f.write("{broken")
            self.assertEqual(ld.load(p), {})
            with open(p, "w") as f:
                json.dump({"outputs": {"x": "bad", "y": {"mode": "1x1"}}}, f)
            self.assertEqual(ld.load(p), {"y": {"mode": "1x1"}})


class TextSize(unittest.TestCase):
    def test_index(self):
        default = ld.TEXT_SIZES.index(None)
        self.assertEqual(ld.text_size_index(None), default)
        self.assertEqual(ld.text_size_index(96), default)
        self.assertEqual(ld.text_size_index(-1), default)
        self.assertEqual(ld.text_size_index(84), 0)
        self.assertEqual(ld.text_size_index(120), 3)
        self.assertEqual(ld.text_size_index(200), len(ld.TEXT_SIZES) - 1)
        self.assertEqual(ld.text_size_index(110), 2)

    def test_set_and_reset(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, FAKE_XFCONF=os.path.join(d, "x.json"),
                       PATH=FAKE + os.pathsep + os.environ["PATH"])
            old = os.environ.copy()
            os.environ.update(env)
            try:
                self.assertIsNone(ld.read_dpi())
                self.assertTrue(ld.set_text_size(3))
                self.assertEqual(ld.read_dpi(), 120)
                self.assertTrue(ld.set_text_size(ld.TEXT_SIZES.index(None)))
                self.assertIsNone(ld.read_dpi())
            finally:
                os.environ.clear()
                os.environ.update(old)


def fake_state():
    return {"outputs": [
        {"name": "eDP-1", "connected": True, "edid": "", "mm": [344, 194], "primary": True,
         "modes": [["1920x1080", ["60.02", "48.01"]], ["1600x900", ["60.00"]], ["1280x720", ["60.00"]]],
         "preferred": ["1920x1080", "60.02"], "current": ["1920x1080", "60.02"], "rotation": "normal", "pos": [0, 0]},
        {"name": "HDMI-1", "connected": True, "edid": EDID_DELL, "mm": [527, 296], "primary": False,
         "modes": [["1920x1080", ["60.00", "74.97", "50.00"]], ["1920x1080i", ["60.00"]], ["1280x1024", ["75.02", "60.02"]],
                   ["1280x720", ["60.00", "50.00"]]],
         "preferred": ["1920x1080", "60.00"], "current": ["1920x1080", "60.00"], "rotation": "normal", "pos": [1920, 0]},
        {"name": "DP-1", "connected": False, "edid": "", "mm": [0, 0], "primary": False, "modes": [],
         "preferred": None, "current": None, "rotation": "normal", "pos": [0, 0]},
    ]}


class FakeEnv:
    """Docasne prostredi: falesne prikazy v PATH, vlastni XDG_CONFIG_HOME a XDG_RUNTIME_DIR."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="luxos-displays-test-")
        self.state = os.path.join(self.dir, "xrandr.json")
        self.log = os.path.join(self.dir, "xrandr.log")
        self.xfconf = os.path.join(self.dir, "xfconf.json")
        os.makedirs(os.path.join(self.dir, "config", "luxos"))
        os.makedirs(os.path.join(self.dir, "run"))
        self.write_state(fake_state())
        self.env = {"PATH": FAKE + os.pathsep + os.environ["PATH"], "FAKE_XRANDR_STATE": self.state,
                    "FAKE_XRANDR_LOG": self.log, "FAKE_XFCONF": self.xfconf,
                    "XDG_CONFIG_HOME": os.path.join(self.dir, "config"),
                    "XDG_RUNTIME_DIR": os.path.join(self.dir, "run"),
                    "LUXOS_DISPLAYS_HELPER": lx.helper()}
        self.conf = os.path.join(self.dir, "config", "luxos", "displays.json")

    def write_state(self, st):
        with open(self.state, "w") as f:
            json.dump(st, f)

    def read_state(self):
        with open(self.state) as f:
            return {o["name"]: o for o in json.load(f)["outputs"]}

    def calls(self):
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def run_displays(self, *args, extra=None):
        env = dict(os.environ, **self.env, **(extra or {}))
        return subprocess.run([os.path.join(FAKE, "luxos-displays"), *args], env=env,
                              capture_output=True, text=True, timeout=30)

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class DisplaysScript(unittest.TestCase):
    """luxos-displays auto: ulozene rozliseni/otoceni se pouzije, bez zaznamu --auto."""

    def setUp(self):
        self.f = FakeEnv()

    def tearDown(self):
        self.f.cleanup()

    def test_scale_set_x11(self):
        # meritko 100-200 % (Monitory > Meritko na X11): xsettings, kurzor, lista, ulozena volba
        env = dict(os.environ, **self.f.env, GSETTINGS_BACKEND="memory")

        def helper(*args):
            return subprocess.run([lx.helper(), *args], env=env, capture_output=True, text=True, timeout=30)

        def xfconf():
            with open(self.f.xfconf) as f:
                return json.load(f)

        self.assertEqual(helper("scale-get").stdout.strip(), "100")
        r = helper("scale-set", "150")
        self.assertEqual(r.returncode, 0, r.stderr)
        db = xfconf()
        self.assertEqual(db["xsettings"]["/Gdk/WindowScalingFactor"], "1")
        self.assertEqual(db["xsettings"]["/Xft/DPI"], "144")
        self.assertEqual(db["xsettings"]["/Gtk/CursorThemeSize"], "36")
        self.assertEqual(db["xfce4-panel"]["/panels/panel-1/size"], "42")
        self.assertEqual(helper("scale-get").stdout.strip(), "150")
        # 200 %: GTK 2x, DPI zpet na 96, lista podle 100 %
        self.assertEqual(helper("scale-set", "200").returncode, 0)
        db = xfconf()
        self.assertEqual(db["xsettings"]["/Gdk/WindowScalingFactor"], "2")
        self.assertEqual(db["xsettings"]["/Xft/DPI"], "96")
        self.assertEqual(db["xfce4-panel"]["/panels/panel-1/size"], "28")
        # zpet na 100 %: DPI vlastnost pryc
        self.assertEqual(helper("scale-set", "100").returncode, 0)
        self.assertNotIn("/Xft/DPI", xfconf()["xsettings"])
        self.assertNotEqual(helper("scale-set", "130").returncode, 0)

    def test_auto_without_saved(self):
        r = self.f.run_displays("auto")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.f.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], "--output DP-1 --off --output eDP-1 --auto --primary --pos 0x0 "
                                   "--output HDMI-1 --auto --right-of eDP-1")

    def test_auto_with_saved(self):
        key = "HDMI-1|" + ld.edid_id(EDID_DELL)
        ld.save({key: {"mode": "1280x1024", "rate": "75.02", "rotate": "left"},
                 "eDP-1|": {"mode": "1600x900", "rate": "60.00", "rotate": "normal"}}, self.f.conf)
        r = self.f.run_displays("auto")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.f.calls()[-1],
                         "--output DP-1 --off --output eDP-1 --mode 1600x900 --rate 60.00 --rotate normal "
                         "--primary --pos 0x0 --output HDMI-1 --mode 1280x1024 --rate 75.02 --rotate left "
                         "--right-of eDP-1")
        st = self.f.read_state()
        self.assertEqual(st["HDMI-1"]["current"], ["1280x1024", "75.02"])
        self.assertEqual(st["HDMI-1"]["rotation"], "left")
        self.assertEqual(st["HDMI-1"]["pos"], [1600, 0])

    def test_other_monitor_on_same_port(self):
        # Zaznam pro jiny monitor (jiny EDID) se na HDMI-1 nepouzije
        ld.save({"HDMI-1|ffffffffffff": {"mode": "1280x720", "rotate": "normal"}}, self.f.conf)
        self.f.run_displays("auto")
        self.assertIn("--output HDMI-1 --auto", self.f.calls()[-1])

    def test_modes_keep_saved(self):
        ld.save({"eDP-1|": {"mode": "1280x720", "rate": "60.00", "rotate": "normal"}}, self.f.conf)
        self.f.run_displays("mirror")
        # zrcadleni: ulozene rozliseni hlavniho monitoru umi i HDMI-1 -> oba 1280x720 v 0,0
        self.assertEqual(self.f.calls()[-1], "--output DP-1 --off --output eDP-1 --mode 1280x720 --rate 60.00 "
                                             "--rotate normal --scale 1x1 --pos 0x0 --primary "
                                             "--output HDMI-1 --mode 1280x720 --rate 60.00 --rotate normal --scale 1x1 --pos 0x0")
        self.f.run_displays("external")
        self.assertEqual(self.f.calls()[-1], "--output DP-1 --off --output eDP-1 --off "
                                             "--output HDMI-1 --auto --primary --pos 0x0")
        self.f.run_displays("internal")
        self.assertIn("--output eDP-1 --mode 1280x720", self.f.calls()[-1])
        self.assertTrue(self.f.calls()[-1].endswith("--output HDMI-1 --off"))

    def test_preview_conf_env(self):
        prev = os.path.join(self.f.dir, "run", "preview.json")
        ld.save({"eDP-1|": {"mode": "1280x720", "rate": "60.00", "rotate": "inverted"}}, prev)
        self.f.run_displays("auto", extra={"LUXOS_DISPLAYS_CONF": prev})
        self.assertIn("--output eDP-1 --mode 1280x720 --rate 60.00 --rotate inverted", self.f.calls()[-1])
        self.assertFalse(os.path.exists(self.f.conf))

    def test_broken_conf(self):
        with open(self.f.conf, "w") as f:
            f.write("not json")
        r = self.f.run_displays("auto")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--output eDP-1 --auto", self.f.calls()[-1])


class Window:
    """Stranka Monitory (luxos-displays-settings) ve vlastnim Xvfb s falesnym xrandr (FakeEnv) rizena pres luxos_testctl."""

    def __init__(self, f, display, extra=None):
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "XAUTHORITY")}
        env.update(f.env, DISPLAY=display, LUXOS_DISPLAYS_CONFIRM_SECONDS="2", GDK_BACKEND="x11",
                   DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent", **(extra or {}))
        self.app = lsl_app.App([lx.window()], env)
        self.wait(lambda s: s["x11"], 15)

    def state(self):
        return json.loads(self.app.ask("page-state", "state "))

    def wait(self, cond, timeout=15.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            st = self.state()
            if cond(st):
                return st
            time.sleep(0.1)
        raise AssertionError("timeout, state: %s; stderr: %s" % (self.state(), self.app.stderr()))

    def select(self, name, value):
        self.app.ask("select %s %s" % (name, json.dumps([value])))

    def wait_dialog(self):
        return self.wait(lambda s: s["dialog"])

    def wait_idle(self):
        return self.wait(lambda s: not s["busy"] and not s["dialog"] and s["page_sensitive"])

    def stop(self):
        self.app.stop()


class App(unittest.TestCase):
    """Okno Monitory s falesnym xrandr: zkusebni pouziti, potvrzeni, vraceni, velikost textu."""

    @classmethod
    def setUpClass(cls):
        lx.window()
        lx.helper()
        cls.x = lsl_app.Xvfb()
        cls.f = FakeEnv()

    @classmethod
    def tearDownClass(cls):
        cls.x.stop()
        cls.f.cleanup()

    def setUp(self):
        self.f.write_state(fake_state())
        for p in (self.f.conf, self.f.xfconf, self.f.log, os.path.join(self.f.dir, "config", "luxos", "displays-mode")):
            if os.path.exists(p):
                os.unlink(p)
        self.win = Window(self.f, self.x.display)

    def tearDown(self):
        self.win.stop()

    def restart(self, extra=None):
        self.win.stop()
        self.win = Window(self.f, self.x.display, extra)

    def preview_path(self):
        return os.path.join(self.f.dir, "run", "luxos-displays-preview.json")

    def change(self, combo, value):
        self.win.select(combo, value)
        return self.win.wait_dialog()

    def test_window(self):
        st = self.win.state()
        self.assertTrue(st["x11"])
        c = st["combos"]
        self.assertEqual({k for k in c if k.startswith("res:")}, {"res:eDP-1", "res:HDMI-1"})
        self.assertEqual(c["res:HDMI-1"]["active"], "1920x1080")
        self.assertIn("1920 × 1080 (Recommended)", c["res:HDMI-1"]["labels"])
        self.assertNotIn("1920 × 1080 i", c["res:HDMI-1"]["labels"])
        self.assertEqual(c["rate:HDMI-1"]["active"], "60.00")
        self.assertEqual(c["rate:HDMI-1"]["labels"], ["74.97 Hz", "60 Hz", "50 Hz"])
        self.assertEqual(c["rot:HDMI-1"]["active"], "normal")
        self.assertEqual(c["rot:HDMI-1"]["labels"], ["Standard", "90°", "180°", "270°"])
        # Nazvy z EDID / vestaveny displej v nadpisech skupin; meritko na X11 neni (jako drive)
        windows = self.win.app.dump()
        titles = lsl_app.texts(windows)
        for title in ("DELL U2419H", "Built-in Display", "Multiple Displays", "Text Size", "Arrangement"):
            self.assertIn(title, titles)
        # meritko 100-200 % na X11 (luxos-displays scale-set) a velikost tlacitek oken
        for title in ("Scale", "Size of everything on the screen", "Window buttons"):
            self.assertIn(title, titles)
        self.assertTrue(windows[0]["close_button"])
        print("\nPSS okna Monitory (X11, LSL): %d kB" % self.win.app.pss_kb())

    def test_keep(self):
        st = self.change("res:HDMI-1", "1280x1024")
        self.assertEqual(self.f.read_state()["HDMI-1"]["current"], ["1280x1024", "75.02"])     # doporucena -> nejvyssi
        self.assertFalse(os.path.exists(self.f.conf))                                           # jeste neulozeno
        self.assertFalse(st["page_sensitive"])
        self.win.app.ask("click Keep Changes")
        st = self.win.wait_idle()
        self.assertEqual(ld.load(self.f.conf), {"HDMI-1|" + lx.md5_id(EDID_DELL): {"mode": "1280x1024", "rate": "75.02",
                                                                                   "rotate": "normal"}})
        self.assertEqual(st["combos"]["res:HDMI-1"]["active"], "1280x1024")
        self.assertFalse(os.path.exists(self.preview_path()))
        # Po prihlaseni/pripojeni plati ulozene nastaveni
        self.f.write_state(fake_state())
        self.f.run_displays("auto")
        self.assertEqual(self.f.read_state()["HDMI-1"]["current"], ["1280x1024", "75.02"])

    def test_timeout_reverts(self):
        self.change("res:eDP-1", "1280x720")
        self.assertEqual(self.f.read_state()["eDP-1"]["current"], ["1280x720", "60.00"])
        # Odpocet 2 s, pak luxos-displays auto s puvodnim nastavenim
        st = self.win.wait_idle()
        self.assertEqual(self.f.read_state()["eDP-1"]["current"], ["1920x1080", "60.02"])
        self.assertFalse(os.path.exists(self.f.conf))
        self.assertEqual(st["combos"]["res:eDP-1"]["active"], "1920x1080")

    def test_revert_button_keeps_previous_saved(self):
        key = "HDMI-1|" + lx.md5_id(EDID_DELL)
        ld.save({key: {"mode": "1280x720", "rate": "50.00", "rotate": "normal"}}, self.f.conf)
        self.f.run_displays("auto")
        self.restart()
        self.assertEqual(self.win.state()["combos"]["rate:HDMI-1"]["active"], "50.00")
        self.change("rot:HDMI-1", "right")
        self.assertEqual(self.f.read_state()["HDMI-1"]["rotation"], "right")
        self.win.app.ask("click Revert")
        self.win.wait_idle()
        st = self.f.read_state()["HDMI-1"]
        self.assertEqual((st["current"], st["rotation"]), (["1280x720", "50.00"], "normal"))
        self.assertEqual(ld.load(self.f.conf)[key]["rotate"], "normal")

    def test_rejected_mode(self):
        self.restart({"FAKE_XRANDR_REJECT": "1600x900"})
        self.win.select("res:eDP-1", "1600x900")
        st = self.win.wait(lambda s: not s["busy"] and s["message"] != "")
        self.assertFalse(st["dialog"])
        self.assertIn("could not use this setting", st["message"])
        self.assertEqual(self.f.read_state()["eDP-1"]["current"], ["1920x1080", "60.02"])
        self.assertFalse(os.path.exists(self.f.conf))

    def test_recommended_removes_entry(self):
        ld.save({"eDP-1|": {"mode": "1280x720", "rate": "60.00", "rotate": "normal"}}, self.f.conf)
        self.f.run_displays("auto")
        self.restart()
        self.change("res:eDP-1", "1920x1080")
        self.win.app.ask("click Keep Changes")
        self.win.wait_idle()
        self.assertEqual(ld.load(self.f.conf), {})

    def test_forget_xfce_profile(self):
        with open(self.f.xfconf, "w") as f:
            json.dump({"displays": {"/Default/HDMI-1/Resolution": "800x600", "/Notify": "0"}}, f)
        self.change("res:eDP-1", "1280x720")
        self.win.app.ask("click Keep Changes")
        self.win.wait_idle()
        with open(self.f.xfconf) as f:
            self.assertEqual(json.load(f)["displays"], {"/Notify": "0"})

    def test_text_size(self):
        st = self.win.state()
        self.assertEqual(st["text"], [1, "Default"])
        self.win.app.ask("text 4")
        time.sleep(0.8)
        self.assertEqual(self.win.state()["text"], [4, "Largest"])
        with open(self.f.xfconf) as f:
            self.assertEqual(json.load(f)["xsettings"]["/Xft/DPI"], "132")
        self.win.app.ask("text 1")
        time.sleep(0.8)
        with open(self.f.xfconf) as f:
            self.assertNotIn("/Xft/DPI", json.load(f)["xsettings"])
        # ulozena velikost po novem otevreni
        self.win.app.ask("text 3")
        time.sleep(0.8)
        self.restart()
        self.assertEqual(self.win.state()["text"], [3, "Larger"])

    def wait_xrandr(self, name, current, timeout=10):
        end = time.monotonic() + timeout
        while time.monotonic() < end and self.f.read_state()[name]["current"] != current:
            time.sleep(0.1)
        return self.f.read_state()[name]["current"]

    def test_close_dialog_reverts(self):
        # Krizek potvrzovaciho dialogu = vratit (modalni dialog nepusti zavreni hlavniho okna)
        self.change("res:eDP-1", "1280x720")
        self.win.app.ask("close")
        st = self.win.wait_idle()
        self.assertEqual(self.wait_xrandr("eDP-1", ["1920x1080", "60.02"]), ["1920x1080", "60.02"])
        self.assertEqual(st["combos"]["res:eDP-1"]["active"], "1920x1080")
        self.assertFalse(os.path.exists(self.f.conf))
        # bez dialogu krizek okno zavre
        self.win.app.send("close")
        self.win.app.proc.wait(10)

    def test_crash_during_preview_reverts(self):
        # Okno spadne behem odpoctu: puvodni nastaveni vrati pomocnik sam (drive abandon() v Pythonu)
        self.change("res:eDP-1", "1280x720")
        os.kill(self.win.app.proc.pid, 9)
        self.win.app.proc.wait(10)
        self.assertEqual(self.wait_xrandr("eDP-1", ["1920x1080", "60.02"]), ["1920x1080", "60.02"])
        self.assertFalse(os.path.exists(self.f.conf))
        self.assertFalse(os.path.exists(self.preview_path()))

    def test_multiple_displays_mode(self):
        # Rezim vice monitoru se pouzije hned (luxos-displays MODE jako Super+P), bez potvrzovani
        self.win.select("mode", "mirror")
        st = self.win.wait(lambda s: not s["busy"] and s["mirrored"])
        self.assertFalse(st["dialog"])
        self.assertEqual(st["combos"]["mode"]["active"], "mirror")
        self.assertEqual(self.f.read_state()["HDMI-1"]["pos"], [0, 0])
        self.assertTrue(st["switch"])
        self.win.select("mode", "internal")
        st = self.win.wait(lambda s: not s["busy"] and len(s["rects"]) == 1)
        self.assertEqual(self.f.read_state()["HDMI-1"]["current"], None)
        titles = lsl_app.texts(self.win.app.dump())
        self.assertIn("This display is turned off.", titles)


class WindowFits(unittest.TestCase):
    """Okno vysoke podle obsahu (bez prazdne plochy dole), nejvys pracovni plocha (drive luxos_winsize v Pythonu)."""

    def test_sizes(self):
        lx.window()
        for screen in ((1366, 768), (1280, 800)):
            for monitors in (1, 2):
                with self.subTest(screen=screen, monitors=monitors):
                    x = lsl_app.Xvfb("%dx%d" % screen)
                    f = FakeEnv()
                    st = fake_state()
                    if monitors == 1:
                        st["outputs"][1].update(connected=False, current=None)
                    f.write_state(st)
                    try:
                        win = Window(f, x.display)
                        try:
                            time.sleep(0.5)
                            w, h = win.state()["size"]
                            self.assertLessEqual(h, screen[1] - 16)
                            self.assertLessEqual(w, screen[0])
                            self.assertGreaterEqual(h, 300)
                            if monitors == 1:
                                self.assertLess(h, 700 + 45 - 40)
                        finally:
                            win.stop()
                    finally:
                        x.stop()
                        f.cleanup()


class Drawing(unittest.TestCase):
    """Nazev monitoru v nahledu nezasahuje do sousedniho obdelniku (kresleni do obrazku Cairo v okne)."""

    def test_display_labels_stay_inside_their_rectangles(self):
        lx.window()
        x = lsl_app.Xvfb()
        f = FakeEnv()
        try:
            win = Window(f, x.display)
            try:
                for label in ("DELL U2419H (DisplayPort-0)", "Built-in Display = DELL U2419H", "HDMI-1"):
                    with self.subTest(label=label):
                        self.assertEqual(win.app.ask("drawcheck " + label, "outside "), "0")
            finally:
                win.stop()
        finally:
            x.stop()
            f.cleanup()


@unittest.skipUnless(shutil.which("Xvfb") and shutil.which("xrandr") and os.environ.get("LUXOS_TEST_REAL_XRANDR") == "1",
                     "LUXOS_TEST_REAL_XRANDR=1 (skutecny xrandr na vlastnim Xvfb)")
class RealXrandr(unittest.TestCase):
    """Skutecny xrandr na Xvfb (RandR): vystup se precte a zmena rezimu projde."""

    def test_query(self):
        x = lsl_app.Xvfb()
        try:
            env = dict(os.environ, DISPLAY=x.display)
            text = subprocess.run(["xrandr", "--current", "--prop"], env=env, capture_output=True, text=True).stdout
            outs = [o for o in ld.parse(text) if o["connected"]]
            self.assertTrue(outs)
            mode, _rate = ld.current_mode(outs[0])
            self.assertTrue(mode)
            args = ld.output_args(outs[0], {"mode": mode, "rotate": "normal"})
            r = subprocess.run(["xrandr", "--output", outs[0]["name"], *args], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([lx.helper(), "output-args"], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            x.stop()


if __name__ == "__main__":
    unittest.main()
