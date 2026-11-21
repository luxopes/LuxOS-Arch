"""Testy usporadani monitoru na X11: geometrie (prichyceni, bez prekryvu a mezer), profily podle
konektoru/EDID, prikaz xrandr (luxos_xrandr.lsl), luxos-displays auto s ulozenym rozlozenim a okno Monitory
v LSL (vlastni Xvfb, luxos_testctl).

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_arrange.py -v

Falesny xrandr/xfconf-query/dconf z fake-displays - skutecna obrazovka se nikdy nemeni.
LUXOS_TEST_SHOTS=adresar ulozi snimky okna.
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
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402
import test_luxos_displays as td  # noqa: E402
import luxos_xrandr_lsl as lx  # noqa: E402
from luxos_xrandr_lsl import la, ld  # noqa: E402

FHD = (1920, 1080)


def rects(**kw):
    return {n: list(v) for n, v in kw.items()}


class Geometry(unittest.TestCase):
    def test_overlap_and_touch(self):
        a = (0, 0, 1920, 1080)
        self.assertFalse(la.overlaps(a, (1920, 0, 100, 100)))      # dotyk hranou
        self.assertTrue(la.overlaps(a, (1919, 0, 100, 100)))
        self.assertTrue(la.touches(a, (1920, 500, 100, 100)))
        self.assertTrue(la.touches(a, (100, 1080, 100, 100)))
        self.assertFalse(la.touches(a, (1920, 1080, 100, 100)))    # jen roh
        self.assertFalse(la.touches(a, (1921, 0, 100, 100)))       # mezera

    def test_valid(self):
        self.assertTrue(la.valid(rects(A=(0, 0, 1920, 1080), B=(1920, 0, 1280, 1024))))
        self.assertFalse(la.valid(rects(A=(0, 0, 1920, 1080), B=(1930, 0, 1280, 1024))))   # mezera
        self.assertFalse(la.valid(rects(A=(0, 0, 1920, 1080), B=(1900, 0, 1280, 1024))))   # prekryv
        self.assertTrue(la.valid(rects(A=(0, 0, 100, 100), B=(100, 0, 100, 100), C=(0, 100, 100, 100))))

    def test_rect_size(self):
        self.assertEqual(la.rect_size("2560x1440", "normal"), [2560, 1440])
        self.assertEqual(la.rect_size("2560x1440", "left"), [1440, 2560])
        self.assertEqual(la.rect_size("1920x1080i", "inverted"), [1920, 1080])

    def test_drop_snaps_to_edge(self):
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 1920, 1080))
        # B pustena kousek vlevo nad A (prekryv) -> nad A, zarovnana
        pos = la.drop(r, "B", 300, -1000, "A", snap=50)
        full = {n: [*pos[n], *r[n][2:]] for n in r}
        self.assertTrue(la.valid(full))
        self.assertEqual(pos["B"][1] + 1080, pos["A"][1])          # B nad A

    def test_drop_gap_closes(self):
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 1280, 1024))
        pos = la.drop(r, "B", 2500, 40, "A", snap=0)                # daleko vpravo s mezerou
        self.assertEqual(pos, {"A": [0, 0], "B": [1920, 40]})

    def test_drop_overlap_resolved(self):
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 1280, 1024))
        pos = la.drop(r, "B", 1000, 200, "A")                       # pres A
        full = {n: [*pos[n], *r[n][2:]] for n in r}
        self.assertTrue(la.valid(full))

    def test_align_snap(self):
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 1280, 1024))
        # 20 px od spodni hrany A -> zarovnat spodky (1080 - 1024 = 56)
        self.assertEqual(la.drop(r, "B", 1920, 70, "A", snap=30)["B"], [1920, 56])
        self.assertEqual(la.drop(r, "B", 1920, 70, "A", snap=0)["B"], [1920, 70])
        # vlevo: normalizace na 0,0
        self.assertEqual(la.drop(r, "B", -1300, 10, "A", snap=30), {"A": [1280, 0], "B": [0, 0]})

    def test_min_contact(self):
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 1920, 1080))
        pos = la.drop(r, "B", 1920, 1075, "A")                      # skoro jen roh
        self.assertEqual(pos["B"][1] - pos["A"][1], 1080 - la.MIN_CONTACT)

    def test_bridge_removed_keeps_connected(self):
        # B spojovala A a C; po presunu B nalevo se C prichyti k A
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 1920, 1080), C=(3840, 0, 1920, 1080))
        pos = la.drop(r, "B", -1920, 0, "A")
        full = {n: [*pos[n], *r[n][2:]] for n in r}
        self.assertTrue(la.valid(full))
        self.assertEqual(pos, {"B": [0, 0], "A": [1920, 0], "C": [3840, 0]})

    def test_drag_primary(self):
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 2560, 1440))
        pos = la.drop(r, "A", 2200, 1500, "A")                      # hlavni pod B
        self.assertEqual(pos["B"], [0, 0])
        self.assertEqual(pos["A"][1], 1440)
        self.assertTrue(la.valid({n: [*pos[n], *r[n][2:]] for n in r}))

    def test_settle_many_random(self):
        import random
        rnd = random.Random(7)
        for _ in range(200):
            n = rnd.randint(2, 5)
            sizes = {f"M{i}": rnd.choice([(1920, 1080), (2560, 1440), (1080, 1920), (1280, 1024), (3840, 2160)])
                     for i in range(n)}
            props = {k: (rnd.randint(-5000, 5000), rnd.randint(-3000, 3000)) for k in sizes}
            pos = la.settle(sizes, props, sorted(sizes), {k: 40 for k in sizes})
            full = {k: [*pos[k], *sizes[k]] for k in sizes}
            self.assertTrue(la.valid(full), full)
            self.assertEqual(min(p[0] for p in pos.values()), 0)
            self.assertEqual(min(p[1] for p in pos.values()), 0)


def outs_from(state):
    """Vystupy (jako ld.query) z falesneho stavu xrandr."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(state, f)
    try:
        r = subprocess.run([os.path.join(td.FAKE, "xrandr"), "--current", "--prop"], capture_output=True, text=True,
                           env=dict(os.environ, FAKE_XRANDR_STATE=f.name))
        return ld.parse(r.stdout)
    finally:
        os.unlink(f.name)


DELL_ID = lx.md5_id(td.EDID_DELL)


class Profiles(unittest.TestCase):
    def setUp(self):
        self.outs = outs_from(td.fake_state())

    def test_set_key(self):
        self.assertEqual(la.set_key(self.outs), f"HDMI-1|{DELL_ID}+eDP-1|")

    def test_exact_match(self):
        lay = {"primary": f"HDMI-1|{DELL_ID}", "mirror": False, "pos": {"eDP-1|": [0, 1080]}}
        found, names = la.find_layout({la.set_key(self.outs): lay}, self.outs)
        self.assertEqual(found, lay)
        self.assertEqual(names, {"eDP-1|": "eDP-1", f"HDMI-1|{DELL_ID}": "HDMI-1"})

    def test_no_match_other_monitor(self):
        self.assertEqual(la.find_layout({"HDMI-1|ffffffffffff+eDP-1|": {"pos": {}}}, self.outs), (None, {}))
        # jediny monitor: rozlozeni nema smysl
        st = td.fake_state()
        st["outputs"][1]["connected"] = False
        self.assertEqual(la.find_layout({la.set_key(self.outs): {"pos": {}}}, outs_from(st)), (None, {}))

    def test_match_by_edid_other_port(self):
        st = td.fake_state()
        e1, e2 = td.make_edid("LAPTOP PANEL"), td.make_edid("DELL U2419H")
        st["outputs"][0]["edid"] = e1
        st["outputs"][1]["edid"] = e2
        old_key = f"eDP-1|{lx.md5_id(e1)}+DP-3|{lx.md5_id(e2)}"
        lay = {"primary": f"DP-3|{lx.md5_id(e2)}", "pos": {}}
        found, names = la.find_layout({old_key: lay, "zz+yy": dict(lay)}, outs_from(st))
        self.assertEqual(found, lay)
        self.assertEqual(names[f"DP-3|{lx.md5_id(e2)}"], "HDMI-1")

    def test_make_layout(self):
        lay = la.make_layout(self.outs, {"eDP-1": [0, 1080], "HDMI-1": [0, 0]}, "HDMI-1", mirror=False)
        self.assertEqual(lay, {"primary": f"HDMI-1|{DELL_ID}", "mirror": False,
                               "pos": {"eDP-1|": [0, 1080], f"HDMI-1|{DELL_ID}": [0, 0]}})


class Plan(unittest.TestCase):
    def setUp(self):
        self.outs = outs_from(td.fake_state())
        self.key = la.set_key(self.outs)

    def test_none_without_layout(self):
        self.assertIsNone(la.plan(self.outs, {}, {}))

    def test_extend_above(self):
        lay = la.make_layout(self.outs, {"eDP-1": [0, 1080], "HDMI-1": [0, 0]}, "HDMI-1")
        p = la.plan(self.outs, {}, {self.key: lay})
        self.assertEqual(p["primary"], "HDMI-1")
        self.assertEqual(p["pos"], {"HDMI-1": [0, 0], "eDP-1": [0, 1080]})
        self.assertEqual(" ".join(p["args"]),
                         "--output DP-1 --off --output HDMI-1 --auto --rotate normal --pos 0x0 --primary "
                         "--output eDP-1 --auto --rotate normal --pos 0x1080")

    def test_saved_mode_resettles(self):
        # HDMI otocene na vysku (1080x1920): eDP vpravo se posune, aby nebyla mezera
        lay = la.make_layout(self.outs, {"HDMI-1": [0, 0], "eDP-1": [1920, 0]}, "eDP-1")
        entries = {f"HDMI-1|{DELL_ID}": {"mode": "1920x1080", "rate": "60.00", "rotate": "left"}}
        p = la.plan(self.outs, entries, {self.key: lay})
        self.assertEqual(p["pos"], {"eDP-1": [1080, 0], "HDMI-1": [0, 0]})
        self.assertIn("--output HDMI-1 --mode 1920x1080 --rate 60.00 --rotate left --pos 0x0", " ".join(p["args"]))

    def test_mirror(self):
        lay = la.make_layout(self.outs, {"eDP-1": [0, 0], "HDMI-1": [1920, 0]}, "eDP-1", mirror=True)
        p = la.plan(self.outs, {}, {self.key: lay})
        self.assertTrue(p["mirror"])
        self.assertTrue(" ".join(p["args"]).endswith("--output HDMI-1 --mode 1920x1080 --rate 60.00 --rotate normal "
                                                     "--scale 1x1 --pos 0x0"))
        p = la.plan(self.outs, {}, {self.key: lay}, force_extend=True)
        self.assertFalse(p["mirror"])
        self.assertIn("--pos 1920x0", " ".join(p["args"]))

    def test_broken_layout(self):
        p = la.plan(self.outs, {}, {self.key: {"primary": "nonsense", "pos": {"eDP-1|": "x"}}})
        self.assertEqual(p["primary"], "eDP-1")       # vestaveny
        full = {n: [*p["pos"][n], *FHD] for n in p["pos"]}
        self.assertTrue(la.valid(full))

    def test_matches(self):
        lay = la.make_layout(self.outs, {"eDP-1": [0, 0], "HDMI-1": [1920, 0]}, "eDP-1")
        p = la.plan(self.outs, {}, {self.key: lay})
        self.assertTrue(la.matches(self.outs, p))
        lay = la.make_layout(self.outs, {"eDP-1": [0, 1080], "HDMI-1": [0, 0]}, "eDP-1")
        self.assertFalse(la.matches(self.outs, la.plan(self.outs, {}, {self.key: lay})))


class Script(unittest.TestCase):
    """luxos-displays auto/extend s ulozenym rozlozenim (falesny xrandr)."""

    def setUp(self):
        self.f = td.FakeEnv()
        self.f.env["FAKE_DCONF_LOG"] = os.path.join(self.f.dir, "dconf.log")
        self.outs = outs_from(td.fake_state())
        self.key = la.set_key(self.outs)

    def tearDown(self):
        self.f.cleanup()

    def test_auto_uses_layout_and_moves_panel(self):
        lay = la.make_layout(self.outs, {"eDP-1": [320, 1080], "HDMI-1": [0, 0]}, "HDMI-1")
        ld.save({}, self.f.conf, layouts={self.key: lay})
        with open(self.f.xfconf, "w") as f:
            json.dump({"xfce4-panel": {"/panels/panel-1/output-name": "eDP-1"}}, f)
        r = self.f.run_displays("auto", extra={"FAKE_DCONF_VALUE": "'eDP-1'"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.f.calls()[-1], "--output DP-1 --off --output HDMI-1 --auto --rotate normal --pos 0x0 "
                                             "--primary --output eDP-1 --auto --rotate normal --pos 320x1080")
        st = self.f.read_state()
        self.assertTrue(st["HDMI-1"]["primary"])
        self.assertEqual(st["eDP-1"]["pos"], [320, 1080])
        with open(self.f.xfconf) as f:
            self.assertEqual(json.load(f)["xfce4-panel"]["/panels/panel-1/output-name"], "Primary")
        with open(self.f.env["FAKE_DCONF_LOG"]) as f:
            self.assertEqual(f.read().split(), ["write", "/net/launchpad/plank/docks/dock1/monitor", "''"])

    def test_other_set_uses_default(self):
        ld.save({}, self.f.conf, layouts={"HDMI-1|ffffffffffff+eDP-1|": {"primary": "eDP-1|", "pos": {}}})
        self.f.run_displays("auto")
        self.assertEqual(self.f.calls()[-1], "--output DP-1 --off --output eDP-1 --auto --primary --pos 0x0 "
                                             "--output HDMI-1 --auto --right-of eDP-1")

    def test_super_p_extend_turns_mirror_off(self):
        lay = la.make_layout(self.outs, {"eDP-1": [0, 0], "HDMI-1": [1920, 0]}, "eDP-1", mirror=True)
        ld.save({}, self.f.conf, layouts={self.key: lay})
        self.f.run_displays("auto")
        self.assertIn("--output HDMI-1 --mode 1920x1080 --rate 60.00 --rotate normal --scale 1x1 --pos 0x0",
                      self.f.calls()[-1])
        self.f.run_displays("extend")
        self.assertIn("--output HDMI-1 --auto --rotate normal --pos 1920x0", self.f.calls()[-1])
        self.assertFalse(ld.load_layouts(self.f.conf)[self.key]["mirror"])
        # rezimy Super+P mimo extend rozlozeni nepouzivaji
        self.f.run_displays("internal")
        self.assertTrue(self.f.calls()[-1].endswith("--output HDMI-1 --off"))
        self.f.run_displays("auto")
        self.assertTrue(self.f.calls()[-1].endswith("--output HDMI-1 --off"))
        # LUXOS_DISPLAYS_MODE (zkusebni pouziti z Monitoru) prepise ulozeny rezim
        self.f.run_displays("auto", extra={"LUXOS_DISPLAYS_MODE": "extend"})
        self.assertIn("--pos 1920x0", self.f.calls()[-1])

    def test_save_keeps_layouts(self):
        ld.save({}, self.f.conf, layouts={self.key: {"pos": {}}})
        ld.save({"eDP-1|": {"mode": "1280x720", "rotate": "normal"}}, self.f.conf)
        self.assertIn(self.key, ld.load_layouts(self.f.conf))
        ld.save({}, self.f.conf, layouts={})
        self.assertEqual(ld.load_layouts(self.f.conf), {})


class App(unittest.TestCase):
    """Okno Monitory: pretazeni monitoru, hlavni monitor, zrcadleni, potvrzeni a vraceni (vlastni Xvfb)."""

    @classmethod
    def setUpClass(cls):
        lx.window()
        lx.helper()
        cls.x = lsl_app.Xvfb()
        cls.f = td.FakeEnv()
        cls.f.env["FAKE_DCONF_LOG"] = os.path.join(cls.f.dir, "dconf.log")
        cls.mode_file = os.path.join(cls.f.dir, "config", "luxos", "displays-mode")

    @classmethod
    def tearDownClass(cls):
        cls.x.stop()
        cls.f.cleanup()

    def setUp(self):
        self.f.write_state(td.fake_state())
        for p in (self.f.conf, self.f.xfconf, self.f.log, self.mode_file):
            if os.path.exists(p):
                os.unlink(p)
        self.win = td.Window(self.f, self.x.display)

    def tearDown(self):
        self.win.stop()

    def shot(self, name):
        shots = os.environ.get("LUXOS_TEST_SHOTS")
        if shots:
            os.makedirs(shots, exist_ok=True)
            time.sleep(0.3)
            lsl_app.shot(self.x.display, os.path.join(shots, name))

    def test_window(self):
        st = self.win.state()
        self.assertTrue(st["editable"])
        self.assertEqual(st["primary"], "eDP-1")
        self.assertEqual(st["combos"]["main"]["active"], "eDP-1")
        self.assertTrue(st["combos"]["main"]["sensitive"])
        self.assertFalse(st["switch"])
        self.assertTrue(self.win.app.dump()[0]["close_button"])

    def test_drag_above_keep(self):
        # HDMI nad vestaveny displej
        self.win.app.ask("drag HDMI-1 -1920 -1090")
        self.win.wait_dialog()
        st = self.f.read_state()
        self.assertEqual((st["HDMI-1"]["pos"], st["eDP-1"]["pos"]), ([0, 0], [0, 1080]))
        self.assertFalse(os.path.exists(self.f.conf))
        self.shot("displays-arrangement-confirm.png")
        self.win.app.ask("click Keep Changes")
        self.win.wait_idle()
        lays = ld.load_layouts(self.f.conf)
        key = la.set_key(outs_from(td.fake_state()))
        self.assertEqual(lays[key]["pos"], {"eDP-1|": [0, 1080], f"HDMI-1|{DELL_ID}": [0, 0]})
        with open(self.mode_file) as f:
            self.assertEqual(f.read().strip(), "extend")
        self.assertEqual(ld.load_modes(self.f.conf), {key: {"mode": "extend"}})
        # Opetovne pripojeni stejne sady: luxos-displays auto obnovi rozlozeni
        self.f.write_state(td.fake_state())
        self.f.run_displays("auto")
        st = self.f.read_state()
        self.assertEqual((st["HDMI-1"]["pos"], st["eDP-1"]["pos"]), ([0, 0], [0, 1080]))

    def test_drag_timeout_reverts(self):
        self.win.app.ask("drag HDMI-1 -3840 0")       # nalevo od vestaveneho
        self.win.wait_dialog()
        self.assertEqual(self.f.read_state()["eDP-1"]["pos"], [1920, 0])
        self.win.wait_idle()
        st = self.f.read_state()
        self.assertEqual((st["eDP-1"]["pos"], st["HDMI-1"]["pos"]), ([0, 0], [1920, 0]))
        self.assertEqual(ld.load_layouts(self.f.conf), {})

    def test_small_click_no_change(self):
        self.win.app.ask("drag HDMI-1 1 1")
        time.sleep(0.3)
        st = self.win.state()
        self.assertFalse(st["busy"] or st["dialog"])
        self.assertEqual(self.f.calls(), [])

    def test_primary_by_bar_drag(self):
        self.win.app.ask("drag eDP-1 1920 0 bar")
        self.win.wait_dialog()
        st = self.f.read_state()
        self.assertTrue(st["HDMI-1"]["primary"])
        self.assertFalse(st["eDP-1"]["primary"])
        self.win.app.ask("click Keep Changes")
        st = self.win.wait_idle()
        self.assertEqual(st["primary"], "HDMI-1")
        self.assertEqual(st["combos"]["main"]["active"], "HDMI-1")

    def test_main_display_combo(self):
        self.win.select("main", "HDMI-1")
        self.win.wait_dialog()
        self.assertTrue(self.f.read_state()["HDMI-1"]["primary"])
        self.win.app.ask("click Revert")
        self.win.wait_idle()
        self.assertTrue(self.f.read_state()["eDP-1"]["primary"])

    def test_mirror_switch(self):
        self.win.app.ask("mirror 1")
        self.win.wait_dialog()
        st = self.f.read_state()
        self.assertEqual(st["HDMI-1"]["pos"], st["eDP-1"]["pos"])
        self.win.app.ask("click Keep Changes")
        st = self.win.wait_idle()
        self.assertTrue(st["switch"])
        self.assertTrue(st["mirrored"])
        self.assertFalse(st["editable"])
        self.assertFalse(st["combos"]["main"]["sensitive"])
        self.shot("displays-mirror.png")
        # vypnuti zrcadleni vrati ulozene polohy
        self.win.app.ask("mirror 0")
        self.win.wait_dialog()
        self.assertEqual(self.f.read_state()["HDMI-1"]["pos"], [1920, 0])
        self.win.app.ask("click Keep Changes")
        self.win.wait_idle()

    def test_screenshot(self):
        if not os.environ.get("LUXOS_TEST_SHOTS"):
            self.skipTest("LUXOS_TEST_SHOTS neni nastaveno")
        self.shot("displays-arrangement.png")
        # nahled pretahovani (pred pustenim)
        self.win.app.ask("drag HDMI-1 -1300 800 hold")
        self.shot("displays-arrangement-drag.png")


if __name__ == "__main__":
    unittest.main()
