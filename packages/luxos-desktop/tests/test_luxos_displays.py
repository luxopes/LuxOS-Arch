"""Testy pro Monitory: luxos_displays (parsovani xrandr, ulozene rezimy, velikost textu),
luxos-displays auto s ulozenym nastavenim a aplikace luxos-display-settings (Xvfb).

Spusteni: xvfb-run -a python3 -m unittest discover -s packages/luxos-desktop/tests -v
(bez DISPLAY se testy GUI preskoci). Pouziva falesny xrandr/xfconf-query z fake-displays,
skutecne nastaveni uzivatele nemeni.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.normpath(os.path.join(HERE, "..", "files", "python"))
BIN = os.path.normpath(os.path.join(HERE, "..", "files", "bin"))
FAKE = os.path.join(HERE, "fake-displays")
sys.path.insert(0, PYDIR)
sys.path.insert(1, os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files")))
import luxos_displays as ld  # noqa: E402

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
        self.assertEqual(e["geometry"], (1920, 1080, 0, 0))
        self.assertEqual(e["mm"], (344, 194))
        h = self.outs["HDMI-1"]
        self.assertFalse(h["primary"])
        self.assertEqual(h["rotation"], "left")
        self.assertEqual(h["geometry"], (1080, 1920, 1920, 0))
        self.assertFalse(self.outs["DP-1"]["connected"])
        # pripojeny, ale vypnuty
        d = self.outs["DP-2"]
        self.assertTrue(d["connected"])
        self.assertFalse(d["active"])
        self.assertIsNone(d["geometry"])

    def test_rates_and_flags(self):
        e = self.outs["eDP-1"]
        self.assertEqual(ld.current_mode(e), ("1920x1080", "60.02"))
        self.assertEqual(ld.preferred_mode(e), ("1920x1080", "60.02"))
        self.assertEqual(ld.find_mode(e, "1920x1080")["rates"], ["60.02", "60.01", "59.97", "48.01"])
        h = self.outs["HDMI-1"]
        # "+" oddelene mezerou patri k predchozi frekvenci
        self.assertEqual(ld.preferred_mode(h), ("1920x1080", "60.00"))
        self.assertEqual(ld.current_mode(h), ("2560x1440", "59.95"))
        self.assertEqual(ld.current_mode(self.outs["DP-2"]), (None, None))

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
        self.assertEqual(ld.current_mode(o), ("1920x1080", "60.00"))   # vlastnosti nepokazi rezimy
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
        self.assertEqual(ld.all_output_args(outs, entries),
                         [("HDMI-1", ["--mode", "1680x1050", "--rate", "59.88", "--rotate", "normal"])])

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
                    "XDG_RUNTIME_DIR": os.path.join(self.dir, "run"), "LUXOS_PYDIR": PYDIR}
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
        self.assertEqual(self.f.calls()[-1], "--output DP-1 --off --output eDP-1 --mode 1280x720 --rate 60.00 "
                                             "--rotate normal --primary --pos 0x0 --output HDMI-1 --auto --same-as eDP-1")
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


def load_app():
    loader = importlib.machinery.SourceFileLoader("luxos_display_settings", os.path.join(BIN, "luxos-display-settings"))
    spec = importlib.util.spec_from_loader("luxos_display_settings", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM) - nikdy skutecna obrazovka
@unittest.skipUnless(os.environ.get("DISPLAY") and ("xvfb-run" in os.environ.get("XAUTHORITY", "")
                                                    or os.environ.get("LUXOS_TEST_X") == "1"),
                     "potrebuje virtualni X (xvfb-run)")
class App(unittest.TestCase):
    """Okno Monitory s falesnym xrandr: zkusebni pouziti, potvrzeni, vraceni, velikost textu."""

    @classmethod
    def setUpClass(cls):
        cls.f = FakeEnv()
        cls.saved_env = os.environ.copy()
        os.environ.update(cls.f.env)
        os.environ["LUXOS_DISPLAYS_CONFIRM_SECONDS"] = "2"
        cls.app = load_app()
        from gi.repository import GLib, Gtk
        cls.GLib, cls.Gtk = GLib, Gtk

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls.saved_env)
        cls.f.cleanup()

    def setUp(self):
        self.f.write_state(fake_state())
        for p in (self.f.conf, self.f.xfconf):
            if os.path.exists(p):
                os.unlink(p)
        self.win = self.app.Displays()
        self.win.show_all()
        self.pump(0.2)

    def tearDown(self):
        self.win.pending = None
        self.win.destroy()
        self.pump(0.1)

    def pump(self, seconds, until=None):
        end = time.time() + seconds
        ctx = self.GLib.MainContext.default()
        while time.time() < end:
            while ctx.pending():
                ctx.iteration(False)
            if until and until():
                return True
            time.sleep(0.01)
        return bool(until and until())

    def test_window(self):
        self.assertEqual(set(self.win.combos), {"eDP-1", "HDMI-1"})
        res, rate, rot = self.win.combos["HDMI-1"]
        self.assertEqual(res.get_active_id(), "1920x1080")
        model = [r[0] for r in res.get_model()]
        self.assertIn("1920 × 1080 (Recommended)", model)
        self.assertNotIn("1920 × 1080 i", model)
        self.assertEqual(rate.get_active_id(), "60.00")
        self.assertEqual([r[0] for r in rate.get_model()], ["74.97 Hz", "60 Hz", "50 Hz"])
        self.assertEqual(rot.get_active_id(), "normal")
        # Nazvy z EDID / vestaveny displej v nadpisech skupin
        titles = []

        def collect(w):
            if isinstance(w, self.Gtk.Label):
                titles.append(w.get_text())
            elif isinstance(w, self.Gtk.Container):
                w.foreach(collect)
        self.win.page.foreach(collect)
        self.assertIn("DELL U2419H", titles)
        self.assertIn("Built-in Display", titles)
        self.assertIn("Multiple Displays", titles)
        self.assertIn("Text Size", titles)

    def change_resolution(self, name, mode):
        res = self.win.combos[name][0]
        res.set_active_id(mode)
        ok = self.pump(15, lambda: self.win.dialog is not None)
        self.assertTrue(ok, "potvrzovaci dialog se neukazal")

    def test_keep(self):
        self.change_resolution("HDMI-1", "1280x1024")
        st = self.f.read_state()
        self.assertEqual(st["HDMI-1"]["current"], ["1280x1024", "75.02"])     # doporucena -> nejvyssi
        self.assertFalse(os.path.exists(self.f.conf))                           # jeste neulozeno
        self.assertFalse(self.win.page.get_sensitive())
        self.win.dialog.response(self.Gtk.ResponseType.OK)
        self.pump(0.3)
        saved = ld.load(self.f.conf)
        self.assertEqual(saved, {"HDMI-1|" + ld.edid_id(EDID_DELL): {"mode": "1280x1024", "rate": "75.02",
                                                                     "rotate": "normal"}})
        self.assertTrue(self.win.page.get_sensitive())
        self.assertFalse(os.path.exists(self.win.preview_path()))
        # Po prihlaseni/pripojeni plati ulozene nastaveni
        self.f.write_state(fake_state())
        self.f.run_displays("auto")
        self.assertEqual(self.f.read_state()["HDMI-1"]["current"], ["1280x1024", "75.02"])

    def test_timeout_reverts(self):
        self.change_resolution("eDP-1", "1280x720")
        self.assertEqual(self.f.read_state()["eDP-1"]["current"], ["1280x720", "60.00"])
        # Odpocet 2 s, pak luxos-displays auto s puvodnim nastavenim
        ok = self.pump(15, lambda: self.win.dialog is None and not self.win.busy)
        self.assertTrue(ok)
        self.assertEqual(self.f.read_state()["eDP-1"]["current"], ["1920x1080", "60.02"])
        self.assertFalse(os.path.exists(self.f.conf))
        self.assertEqual(self.win.combos["eDP-1"][0].get_active_id(), "1920x1080")

    def test_revert_button_keeps_previous_saved(self):
        key = "HDMI-1|" + ld.edid_id(EDID_DELL)
        ld.save({key: {"mode": "1280x720", "rate": "50.00", "rotate": "normal"}}, self.f.conf)
        self.win.destroy()
        self.f.run_displays("auto")
        self.win = self.app.Displays()
        self.win.show_all()
        self.assertEqual(self.win.combos["HDMI-1"][1].get_active_id(), "50.00")
        rot = self.win.combos["HDMI-1"][2]
        rot.set_active_id("right")
        self.assertTrue(self.pump(15, lambda: self.win.dialog is not None))
        self.assertEqual(self.f.read_state()["HDMI-1"]["rotation"], "right")
        self.win.dialog.response(self.Gtk.ResponseType.CANCEL)
        self.assertTrue(self.pump(15, lambda: not self.win.busy))
        st = self.f.read_state()["HDMI-1"]
        self.assertEqual((st["current"], st["rotation"]), (["1280x720", "50.00"], "normal"))
        self.assertEqual(ld.load(self.f.conf)[key]["rotate"], "normal")

    def test_rejected_mode(self):
        os.environ["FAKE_XRANDR_REJECT"] = "1600x900"
        try:
            res = self.win.combos["eDP-1"][0]
            res.set_active_id("1600x900")
            self.assertTrue(self.pump(15, lambda: self.win.pending is None and not self.win.busy))
        finally:
            del os.environ["FAKE_XRANDR_REJECT"]
        self.assertIsNone(self.win.dialog)
        self.assertEqual(self.f.read_state()["eDP-1"]["current"], ["1920x1080", "60.02"])
        self.assertFalse(os.path.exists(self.f.conf))

    def test_recommended_removes_entry(self):
        key = "eDP-1|"
        ld.save({key: {"mode": "1280x720", "rate": "60.00", "rotate": "normal"}}, self.f.conf)
        self.win.destroy()
        self.f.run_displays("auto")
        self.win = self.app.Displays()
        self.win.show_all()
        self.win.combos["eDP-1"][0].set_active_id("1920x1080")
        self.assertTrue(self.pump(15, lambda: self.win.dialog is not None))
        self.win.dialog.response(self.Gtk.ResponseType.OK)
        self.pump(0.2)
        self.assertEqual(ld.load(self.f.conf), {})

    def test_forget_xfce_profile(self):
        with open(self.f.xfconf, "w") as f:
            json.dump({"displays": {"/Default/HDMI-1/Resolution": "800x600", "/Notify": "0"}}, f)
        self.change_resolution("eDP-1", "1280x720")
        self.win.dialog.response(self.Gtk.ResponseType.OK)
        self.pump(0.2)
        with open(self.f.xfconf) as f:
            self.assertEqual(json.load(f)["displays"], {"/Notify": "0"})

    def test_text_size(self):
        scale = self.win.text_scale
        self.assertEqual(scale.get_value(), ld.TEXT_SIZES.index(None))
        scale.set_value(4)
        self.pump(0.6)
        with open(self.f.xfconf) as f:
            self.assertEqual(json.load(f)["xsettings"]["/Xft/DPI"], "132")
        scale.set_value(1)
        self.pump(0.6)
        with open(self.f.xfconf) as f:
            self.assertNotIn("/Xft/DPI", json.load(f)["xsettings"])

    def test_close_during_preview_reverts(self):
        self.change_resolution("eDP-1", "1280x720")
        # Zavreni hlavniho okna behem odpoctu (main() vola abandon pri "destroy")
        d = self.win.dialog
        d.finished = True
        self.GLib.source_remove(d.timer)
        d.destroy()
        self.win.dialog = None
        self.win.abandon()
        self.assertIsNone(self.win.pending)
        self.assertTrue(self.pump(10, lambda: self.f.read_state()["eDP-1"]["current"] == ["1920x1080", "60.02"]))


@unittest.skipUnless(os.environ.get("DISPLAY") and shutil.which("xrandr") and
                     os.environ.get("LUXOS_TEST_REAL_XRANDR") == "1", "LUXOS_TEST_REAL_XRANDR=1 pod xvfb-run")
class RealXrandr(unittest.TestCase):
    """Skutecny xrandr na Xvfb (RandR): vystup se precte a zmena rezimu projde."""

    def test_query(self):
        outs = [o for o in ld.query() if o["connected"]]
        self.assertTrue(outs)
        mode, _rate = ld.current_mode(outs[0])
        self.assertTrue(mode)
        args = ld.output_args(outs[0], {"mode": mode, "rotate": "normal"})
        r = subprocess.run(["xrandr", "--output", outs[0]["name"], *args], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
