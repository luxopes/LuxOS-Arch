"""Testy usporadani monitoru: geometrie (prichyceni, bez prekryvu a mezer), profily podle
konektoru/EDID, prikaz xrandr, luxos-displays auto s ulozenym rozlozenim a okno Monitory (Xvfb).

Spusteni: env -u DISPLAY xvfb-run -a python3 -m unittest discover -s packages/luxos-desktop/tests
Falesny xrandr/xfconf-query/dconf z fake-displays - skutecna obrazovka se nikdy nemeni.
LUXOS_TEST_SHOTS=adresar ulozi snimek okna.
"""
import os
import sys
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_luxos_displays as td  # noqa: E402
import luxos_arrange as la  # noqa: E402
import luxos_displays as ld  # noqa: E402

FHD = (1920, 1080)


def rects(**kw):
    return {n: tuple(v) for n, v in kw.items()}


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
        self.assertEqual(la.rect_size("2560x1440", "normal"), (2560, 1440))
        self.assertEqual(la.rect_size("2560x1440", "left"), (1440, 2560))
        self.assertEqual(la.rect_size("1920x1080i", "inverted"), (1920, 1080))

    def test_drop_snaps_to_edge(self):
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 1920, 1080))
        # B pustena kousek vlevo nad A (prekryv) -> nad A, zarovnana
        pos = la.drop(r, "B", 300, -1000, "A", snap=50)
        full = {n: (*pos[n], *r[n][2:]) for n in r}
        self.assertTrue(la.valid(full))
        self.assertEqual(pos["B"][1] + 1080, pos["A"][1])          # B nad A

    def test_drop_gap_closes(self):
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 1280, 1024))
        pos = la.drop(r, "B", 2500, 40, "A", snap=0)                # daleko vpravo s mezerou
        self.assertEqual(pos, {"A": (0, 0), "B": (1920, 40)})

    def test_drop_overlap_resolved(self):
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 1280, 1024))
        pos = la.drop(r, "B", 1000, 200, "A")                       # pres A
        full = {n: (*pos[n], *r[n][2:]) for n in r}
        self.assertTrue(la.valid(full))

    def test_align_snap(self):
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 1280, 1024))
        # 20 px od spodni hrany A -> zarovnat spodky (1080 - 1024 = 56)
        self.assertEqual(la.drop(r, "B", 1920, 70, "A", snap=30)["B"], (1920, 56))
        self.assertEqual(la.drop(r, "B", 1920, 70, "A", snap=0)["B"], (1920, 70))
        # vlevo: normalizace na 0,0
        self.assertEqual(la.drop(r, "B", -1300, 10, "A", snap=30), {"A": (1280, 0), "B": (0, 0)})

    def test_min_contact(self):
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 1920, 1080))
        pos = la.drop(r, "B", 1920, 1075, "A")                      # skoro jen roh
        self.assertEqual(pos["B"][1] - pos["A"][1], 1080 - la.MIN_CONTACT)

    def test_bridge_removed_keeps_connected(self):
        # B spojovala A a C; po presunu B nalevo se C prichyti k A
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 1920, 1080), C=(3840, 0, 1920, 1080))
        pos = la.drop(r, "B", -1920, 0, "A")
        full = {n: (*pos[n], *r[n][2:]) for n in r}
        self.assertTrue(la.valid(full))
        self.assertEqual(pos, {"B": (0, 0), "A": (1920, 0), "C": (3840, 0)})

    def test_drag_primary(self):
        r = rects(A=(0, 0, 1920, 1080), B=(1920, 0, 2560, 1440))
        pos = la.drop(r, "A", 2200, 1500, "A")                      # hlavni pod B
        self.assertEqual(pos["B"], (0, 0))
        self.assertEqual(pos["A"][1], 1440)
        self.assertTrue(la.valid({n: (*pos[n], *r[n][2:]) for n in r}))

    def test_settle_many_random(self):
        import random
        rnd = random.Random(7)
        for _ in range(200):
            n = rnd.randint(2, 5)
            sizes = {f"M{i}": rnd.choice([(1920, 1080), (2560, 1440), (1080, 1920), (1280, 1024), (3840, 2160)])
                     for i in range(n)}
            props = {k: (rnd.randint(-5000, 5000), rnd.randint(-3000, 3000)) for k in sizes}
            pos = la.settle(sizes, props, sorted(sizes), {k: 40 for k in sizes})
            full = {k: (*pos[k], *sizes[k]) for k in sizes}
            self.assertTrue(la.valid(full), full)
            self.assertEqual(min(p[0] for p in pos.values()), 0)
            self.assertEqual(min(p[1] for p in pos.values()), 0)


def outs_from(state):
    """Vystupy (jako ld.query) z falesneho stavu xrandr bez spousteni procesu."""
    import json
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(state, f)
    try:
        r = subprocess.run([os.path.join(td.FAKE, "xrandr"), "--current", "--prop"], capture_output=True, text=True,
                           env=dict(os.environ, FAKE_XRANDR_STATE=f.name))
        return ld.parse(r.stdout)
    finally:
        os.unlink(f.name)


DELL_ID = ld.edid_id(td.EDID_DELL)


class Profiles(unittest.TestCase):
    def setUp(self):
        self.outs = outs_from(td.fake_state())

    def test_set_key(self):
        self.assertEqual(la.set_key(self.outs), f"HDMI-1|{DELL_ID}+eDP-1|")

    def test_exact_match(self):
        lay = {"primary": f"HDMI-1|{DELL_ID}", "mirror": False, "pos": {"eDP-1|": [0, 1080]}}
        found, names = la.find_layout({la.set_key(self.outs): lay}, self.outs)
        self.assertIs(found, lay)
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
        old_key = f"eDP-1|{ld.edid_id(e1)}+DP-3|{ld.edid_id(e2)}"
        lay = {"primary": f"DP-3|{ld.edid_id(e2)}", "pos": {}}
        found, names = la.find_layout({old_key: lay}, outs_from(st))
        self.assertIs(found, lay)
        self.assertEqual(names[f"DP-3|{ld.edid_id(e2)}"], "HDMI-1")

    def test_make_layout(self):
        lay = la.make_layout(self.outs, {"eDP-1": (0, 1080), "HDMI-1": (0, 0)}, "HDMI-1", mirror=False)
        self.assertEqual(lay, {"primary": f"HDMI-1|{DELL_ID}", "mirror": False,
                               "pos": {"eDP-1|": [0, 1080], f"HDMI-1|{DELL_ID}": [0, 0]}})


class Plan(unittest.TestCase):
    def setUp(self):
        self.outs = outs_from(td.fake_state())
        self.key = la.set_key(self.outs)

    def test_none_without_layout(self):
        self.assertIsNone(la.plan(self.outs, {}, {}))

    def test_extend_above(self):
        lay = la.make_layout(self.outs, {"eDP-1": (0, 1080), "HDMI-1": (0, 0)}, "HDMI-1")
        p = la.plan(self.outs, {}, {self.key: lay})
        self.assertEqual(p["primary"], "HDMI-1")
        self.assertEqual(p["pos"], {"HDMI-1": (0, 0), "eDP-1": (0, 1080)})
        self.assertEqual(" ".join(p["args"]),
                         "--output DP-1 --off --output HDMI-1 --auto --rotate normal --pos 0x0 --primary "
                         "--output eDP-1 --auto --rotate normal --pos 0x1080")

    def test_saved_mode_resettles(self):
        # HDMI otocene na vysku (1080x1920): eDP vpravo se posune, aby nebyla mezera
        lay = la.make_layout(self.outs, {"HDMI-1": (0, 0), "eDP-1": (1920, 0)}, "eDP-1")
        entries = {f"HDMI-1|{DELL_ID}": {"mode": "1920x1080", "rate": "60.00", "rotate": "left"}}
        p = la.plan(self.outs, entries, {self.key: lay})
        self.assertEqual(p["pos"], {"eDP-1": (1080, 0), "HDMI-1": (0, 0)})
        self.assertIn("--output HDMI-1 --mode 1920x1080 --rate 60.00 --rotate left --pos 0x0", " ".join(p["args"]))

    def test_mirror(self):
        lay = la.make_layout(self.outs, {"eDP-1": (0, 0), "HDMI-1": (1920, 0)}, "eDP-1", mirror=True)
        p = la.plan(self.outs, {}, {self.key: lay})
        self.assertTrue(p["mirror"])
        self.assertTrue(" ".join(p["args"]).endswith("--output HDMI-1 --auto --rotate normal --same-as eDP-1"))
        p = la.plan(self.outs, {}, {self.key: lay}, force_extend=True)
        self.assertFalse(p["mirror"])
        self.assertIn("--pos 1920x0", " ".join(p["args"]))

    def test_broken_layout(self):
        p = la.plan(self.outs, {}, {self.key: {"primary": "nonsense", "pos": {"eDP-1|": "x"}}})
        self.assertEqual(p["primary"], "eDP-1")       # vestaveny
        full = {n: (*p["pos"][n], *FHD) for n in p["pos"]}
        self.assertTrue(la.valid(full))

    def test_matches(self):
        lay = la.make_layout(self.outs, {"eDP-1": (0, 0), "HDMI-1": (1920, 0)}, "eDP-1")
        p = la.plan(self.outs, {}, {self.key: lay})
        self.assertTrue(la.matches(self.outs, p))
        lay = la.make_layout(self.outs, {"eDP-1": (0, 1080), "HDMI-1": (0, 0)}, "eDP-1")
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
        lay = la.make_layout(self.outs, {"eDP-1": (320, 1080), "HDMI-1": (0, 0)}, "HDMI-1")
        ld.save({}, self.f.conf, layouts={self.key: lay})
        import json
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
        lay = la.make_layout(self.outs, {"eDP-1": (0, 0), "HDMI-1": (1920, 0)}, "eDP-1", mirror=True)
        ld.save({}, self.f.conf, layouts={self.key: lay})
        self.f.run_displays("auto")
        self.assertIn("--same-as eDP-1", self.f.calls()[-1])
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


SHOT_CODE = ("import sys, gi; gi.require_version('Gdk', '3.0'); from gi.repository import Gdk; "
             "r = Gdk.get_default_root_window(); "
             "Gdk.pixbuf_get_from_window(r, 0, 0, r.get_width(), r.get_height()).savev(sys.argv[1], 'png', [], [])")


def shot(path):
    """Snimek cele virtualni obrazovky (Xvfb) do PNG - v samostatnem procesu (nemeni stav X testu)."""
    import subprocess
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run([sys.executable, "-c", SHOT_CODE, path], timeout=20)


class Ev:
    """Udalost mysi pro Arrangement (x, y, tlacitko)."""

    def __init__(self, x, y, button=1):
        self.x, self.y, self.button = x, y, button


@unittest.skipUnless(os.environ.get("DISPLAY") and ("xvfb-run" in os.environ.get("XAUTHORITY", "")
                                                    or os.environ.get("LUXOS_TEST_X") == "1"),
                     "potrebuje virtualni X (xvfb-run)")
class App(unittest.TestCase):
    """Okno Monitory: pretazeni monitoru, hlavni monitor, zrcadleni, potvrzeni a vraceni."""

    @classmethod
    def setUpClass(cls):
        cls.f = td.FakeEnv()
        cls.f.env["FAKE_DCONF_LOG"] = os.path.join(cls.f.dir, "dconf.log")
        cls.saved_env = os.environ.copy()
        os.environ.update(cls.f.env)
        os.environ["LUXOS_DISPLAYS_CONFIRM_SECONDS"] = "2"
        cls.app = td.load_app()
        from gi.repository import GLib, Gtk
        cls.GLib, cls.Gtk = GLib, Gtk

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls.saved_env)
        cls.f.cleanup()

    def setUp(self):
        self.f.write_state(td.fake_state())
        for p in (self.f.conf, self.f.xfconf, self.f.log, os.path.join(self.f.dir, "config", "luxos", "displays-mode")):
            if os.path.exists(p):
                os.unlink(p)
        self.win = self.app.Displays()
        self.win.show_all()
        self.pump(0.3)

    def tearDown(self):
        self.win.pending = None
        self.win.destroy()
        self.pump(0.1)

    pump = td.App.pump

    def wait_dialog(self):
        self.assertTrue(self.pump(15, lambda: self.win.dialog is not None), "potvrzovaci dialog se neukazal")

    def drag(self, name, dx, dy, bar=False):
        area = self.win.arrangement
        view = area.compute_view()
        rx, ry, rw, rh = area.to_view(area.rects[name], view)
        x, y = (rx + rw / 2, ry + 8) if bar else (rx + rw / 2, ry + rh / 2)
        self.assertTrue(area.on_press(area, Ev(x, y)))
        area.on_motion(area, Ev(x + dx / 2, y + dy / 2))
        area.on_motion(area, Ev(x + dx, y + dy))
        area.queue_draw()
        self.pump(0.1)
        area.on_release(area, Ev(x + dx, y + dy))

    def test_window(self):
        area = self.win.arrangement
        self.assertIsNotNone(area)
        self.assertTrue(area.editable)
        self.assertEqual(area.primary, "eDP-1")
        self.assertEqual(self.win.main_combo.get_active_id(), "eDP-1")
        self.assertFalse(self.win.mirror_switch.get_active())
        self.assertIsInstance(self.win.get_titlebar(), self.Gtk.HeaderBar)
        self.assertTrue(self.win.get_titlebar().get_show_close_button())

    def test_drag_above_keep(self):
        area = self.win.arrangement
        scale = area.compute_view()[0]
        # HDMI nad vestaveny displej
        self.drag("HDMI-1", -1920 * scale, -1080 * scale - 5)
        self.wait_dialog()
        st = self.f.read_state()
        self.assertEqual((st["HDMI-1"]["pos"], st["eDP-1"]["pos"]), ([0, 0], [0, 1080]))
        self.assertFalse(os.path.exists(self.f.conf))
        shots = os.environ.get("LUXOS_TEST_SHOTS")
        if shots:
            os.makedirs(shots, exist_ok=True)
            self.pump(0.3)
            shot(os.path.join(shots, 'displays-arrangement-confirm.png'))
        self.win.dialog.response(self.Gtk.ResponseType.OK)
        self.pump(0.3)
        lays = ld.load_layouts(self.f.conf)
        key = la.set_key(ld.query())
        self.assertEqual(lays[key]["pos"], {"eDP-1|": [0, 1080], f"HDMI-1|{DELL_ID}": [0, 0]})
        with open(self.app.MODE_FILE) as f:
            self.assertEqual(f.read().strip(), "extend")
        # Opetovne pripojeni stejne sady: luxos-displays auto obnovi rozlozeni
        self.f.write_state(td.fake_state())
        self.f.run_displays("auto")
        st = self.f.read_state()
        self.assertEqual((st["HDMI-1"]["pos"], st["eDP-1"]["pos"]), ([0, 0], [0, 1080]))

    def test_drag_timeout_reverts(self):
        area = self.win.arrangement
        scale = area.compute_view()[0]
        self.drag("HDMI-1", -3840 * scale, 0)       # nalevo od vestaveneho
        self.wait_dialog()
        self.assertEqual(self.f.read_state()["eDP-1"]["pos"], [1920, 0])
        self.assertTrue(self.pump(15, lambda: self.win.dialog is None and not self.win.busy))
        st = self.f.read_state()
        self.assertEqual((st["eDP-1"]["pos"], st["HDMI-1"]["pos"]), ([0, 0], [1920, 0]))
        self.assertEqual(ld.load_layouts(self.f.conf), {})

    def test_small_click_no_change(self):
        self.drag("HDMI-1", 1, 1)
        self.pump(0.3)
        self.assertIsNone(self.win.pending)
        self.assertEqual(self.f.calls(), [])

    def test_primary_by_bar_drag(self):
        area = self.win.arrangement
        scale = area.compute_view()[0]
        self.drag("eDP-1", 1920 * scale, 0, bar=True)
        self.wait_dialog()
        st = self.f.read_state()
        self.assertTrue(st["HDMI-1"]["primary"])
        self.assertFalse(st["eDP-1"]["primary"])
        self.win.dialog.response(self.Gtk.ResponseType.OK)
        self.pump(0.3)
        self.assertEqual(self.win.arrangement.primary, "HDMI-1")
        self.assertEqual(self.win.main_combo.get_active_id(), "HDMI-1")

    def test_main_display_combo(self):
        self.win.main_combo.set_active_id("HDMI-1")
        self.wait_dialog()
        self.assertTrue(self.f.read_state()["HDMI-1"]["primary"])
        self.win.dialog.response(self.Gtk.ResponseType.CANCEL)
        self.assertTrue(self.pump(15, lambda: not self.win.busy))
        self.assertTrue(self.f.read_state()["eDP-1"]["primary"])

    def test_mirror_switch(self):
        self.win.mirror_switch.set_active(True)
        self.wait_dialog()
        st = self.f.read_state()
        self.assertEqual(st["HDMI-1"]["pos"], st["eDP-1"]["pos"])
        self.win.dialog.response(self.Gtk.ResponseType.OK)
        self.pump(0.3)
        self.assertTrue(self.win.mirror_switch.get_active())
        self.assertFalse(self.win.arrangement.editable)
        shots = os.environ.get("LUXOS_TEST_SHOTS")
        if shots:
            shot(os.path.join(shots, 'displays-mirror.png'))
        # vypnuti zrcadleni vrati ulozene polohy
        self.win.mirror_switch.set_active(False)
        self.wait_dialog()
        self.assertEqual(self.f.read_state()["HDMI-1"]["pos"], [1920, 0])
        self.win.dialog.response(self.Gtk.ResponseType.OK)
        self.pump(0.3)

    def test_screenshot(self):
        shots = os.environ.get("LUXOS_TEST_SHOTS")
        if not shots:
            self.skipTest("LUXOS_TEST_SHOTS neni nastaveno")
        os.makedirs(shots, exist_ok=True)
        self.win.resize(640, 760)
        self.pump(0.5)
        shot(os.path.join(shots, 'displays-arrangement.png'))
        # nahled pretahovani (pred pustenim)
        area = self.win.arrangement
        view = area.compute_view()
        rx, ry, rw, rh = area.to_view(area.rects["HDMI-1"], view)
        area.on_press(area, Ev(rx + rw / 2, ry + rh / 2))
        area.on_motion(area, Ev(rx + rw / 2 - rw * 0.7, ry + rh / 2 + rh * 0.8))
        area.queue_draw()
        self.pump(0.4)
        shot(os.path.join(shots, 'displays-arrangement-drag.png'))
        area.drag = None


if __name__ == "__main__":
    unittest.main()
