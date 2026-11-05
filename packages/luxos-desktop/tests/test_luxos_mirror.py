"""Testy zrcadleni a rezimu vice monitoru (Ovladaci centrum: Zrcadlit / Rozsirit / Jen externi):
vyber spolecneho rozliseni, pomer stran, --scale-from bez spolecneho rozliseni, sestaveni prikazu
xrandr, navrat meritka pri rozsireni a rezim ulozeny pro kazdou sadu monitoru.

Spusteni: env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_mirror.py -v
Falesny xrandr/xfconf-query/dconf z fake-displays - skutecna obrazovka se nikdy nemeni.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_luxos_displays as td  # noqa: E402
import luxos_arrange as la  # noqa: E402
import luxos_displays as ld  # noqa: E402

DELL_ID = ld.edid_id(td.EDID_DELL)
EDID_PROJ = td.make_edid("EPSON PROJ")
PROJ_ID = ld.edid_id(EDID_PROJ)


def xr(*blocks):
    """Vystupy z textu xrandr (hlavicka + rezimy) - bez spousteni procesu."""
    return ld.parse("Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384\n" + "".join(blocks))


LAPTOP = """eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 344mm x 194mm
   1920x1080     60.02*+  48.01
   1680x1050     60.02
   1600x900      60.00
   1280x1024     60.02
   1280x800      59.81
   1280x720      60.00
   1024x768      60.04
   800x600       60.32
"""
# Monitor 1920x1080 (umi nativni rozliseni notebooku)
DELL = """HDMI-1 connected 1920x1080+1920+0 (normal left inverted right x axis y axis) 527mm x 296mm
   1920x1080     60.00 +  74.97    50.00
   1920x1080i    60.00
   1280x1024     75.02    60.02
   1280x720      60.00    50.00
"""
# Projektor 4:3 bez 1920x1080: spolecne 1280x1024 (5:4), 1280x800 (16:10), 1280x720 (16:9), 1024x768
PROJ = """HDMI-1 connected 1024x768+1920+0 (normal left inverted right x axis y axis) 300mm x 225mm
   1024x768      60.00 +  75.03    70.07
   1280x1024     60.02
   1280x800      59.81
   1280x720      60.00    50.00
   800x600       60.32    56.25
"""
# Televize jen 4K a 1080p, notebook 1366x768 bez nich: zadne spolecne rozliseni
SMALL = """eDP-1 connected primary 1366x768+0+0 (normal left inverted right x axis y axis) 294mm x 165mm
   1366x768      60.00*+
   1024x768      60.00
"""
TV = """HDMI-1 connected 1920x1080+1366+0 (normal left inverted right x axis y axis) 1600mm x 900mm
   3840x2160     60.00 +  30.00
   1920x1080     60.00    50.00
   1920x1080i    60.00
"""
OFF = "DP-1 disconnected (normal left inverted right x axis y axis)\n"


class CommonMode(unittest.TestCase):
    def test_native_of_primary_when_all_support_it(self):
        outs = [o for o in xr(LAPTOP, DELL) if o["connected"]]
        self.assertEqual(la.common_mode(outs, ["1920x1080"]), "1920x1080")

    def test_saved_mode_first(self):
        outs = [o for o in xr(LAPTOP, DELL) if o["connected"]]
        self.assertEqual(la.common_mode(outs, ["1280x720", "1920x1080"]), "1280x720")
        # ulozene rozliseni, ktere druhy monitor neumi, preskocit na nativni
        self.assertEqual(la.common_mode(outs, ["1600x900", "1920x1080"]), "1920x1080")

    def test_same_aspect_beats_bigger_other_aspect(self):
        # 16:9 notebook + projektor: 1280x720 (16:9) ma prednost pred vetsim 1280x1024 (5:4)
        outs = [o for o in xr(LAPTOP, PROJ) if o["connected"]]
        self.assertEqual(la.common_mode(outs, ["1920x1080"]), "1280x720")

    def test_largest_when_aspect_match_is_tiny(self):
        # stejny pomer stran jen u 640x360 (mene nez polovina plochy) -> nejvetsi spolecne
        a = xr("eDP-1 connected primary 1920x1080+0+0 (normal)\n   1920x1080     60.00*+\n   1280x1024     60.00\n"
               "   640x360       60.00\n")
        b = xr("HDMI-1 connected 1280x1024+1920+0 (normal)\n   1280x1024     60.02 +\n   640x360       60.00\n")
        self.assertEqual(la.common_mode([a[0], b[0]], ["1920x1080"]), "1280x1024")

    def test_interlaced_never(self):
        a = xr("eDP-1 connected primary 1920x1080+0+0 (normal)\n   1920x1080i    60.00*+\n   1280x720      60.00\n")
        b = xr("HDMI-1 connected (normal)\n   1920x1080i    60.00 +\n   1280x720      60.00\n")
        self.assertEqual(la.common_mode([a[0], b[0]], ["1920x1080i"]), "1280x720")

    def test_none_without_common(self):
        outs = [o for o in xr(SMALL, TV) if o["connected"]]
        self.assertIsNone(la.common_mode(outs, ["1366x768"]))


class Rate(unittest.TestCase):
    def test_rates(self):
        outs = {o["name"]: o for o in xr(LAPTOP, PROJ)}
        self.assertEqual(la.mirror_rate(outs["HDMI-1"], "1024x768"), "60.00")       # doporucena
        self.assertEqual(la.mirror_rate(outs["HDMI-1"], "1280x720"), "60.00")       # nejblize 60 Hz
        dell = {o["name"]: o for o in xr(DELL)}["HDMI-1"]
        self.assertEqual(la.mirror_rate(dell, "1280x1024"), "60.02")
        self.assertIsNone(la.mirror_rate(dell, "800x600"))


class MirrorPlan(unittest.TestCase):
    def test_same_native_resolution(self):
        p = la.mirror_plan(xr(LAPTOP, DELL, OFF), {})
        self.assertEqual(p["primary"], "eDP-1")
        self.assertEqual(p["mode"], "1920x1080")
        self.assertEqual(" ".join(p["args"]),
                         "--output DP-1 --off "
                         "--output eDP-1 --mode 1920x1080 --rate 60.02 --rotate normal --scale 1x1 --pos 0x0 --primary "
                         "--output HDMI-1 --mode 1920x1080 --rate 60.00 --rotate normal --scale 1x1 --pos 0x0")

    def test_projector_common_mode(self):
        p = la.mirror_plan(xr(LAPTOP, PROJ), {})
        self.assertEqual(p["mode"], "1280x720")
        self.assertEqual(p["scale"], {})
        self.assertIn("--output HDMI-1 --mode 1280x720 --rate 60.00 --rotate normal --scale 1x1 --pos 0x0", " ".join(p["args"]))

    def test_scale_from_without_common_mode(self):
        p = la.mirror_plan(xr(SMALL, TV), {})
        self.assertIsNone(p["mode"])
        self.assertEqual(p["scale"], {"HDMI-1": "1366x768"})
        self.assertEqual(" ".join(p["args"]),
                         "--output eDP-1 --mode 1366x768 --rate 60.00 --rotate normal --scale 1x1 --pos 0x0 --primary "
                         "--output HDMI-1 --mode 3840x2160 --rate 60.00 --rotate normal --scale-from 1366x768 --pos 0x0")

    def test_desktop_primary_and_layout_primary(self):
        # Bez vestaveneho displeje: aktualni hlavni monitor
        a = "DP-1 connected 1920x1080+0+0 (normal)\n   1920x1080     60.00*+\n"
        b = "DP-2 connected primary 1920x1080+1920+0 (normal)\n   1920x1080     60.00*+\n"
        self.assertEqual(la.mirror_plan(xr(a, b), {})["primary"], "DP-2")
        # Ulozene rozlozeni s hlavnim HDMI-1 ma prednost pred vestavenym
        outs = xr(LAPTOP, DELL)
        lay = {la.set_key(outs): {"primary": "HDMI-1|", "pos": {}}}
        p = la.mirror_plan(outs, {}, lay)
        self.assertEqual(p["primary"], "HDMI-1")
        self.assertTrue(" ".join(p["args"]).startswith("--output HDMI-1 --mode 1920x1080"))

    def test_saved_rotation_ignored(self):
        outs = xr(LAPTOP, DELL)
        p = la.mirror_plan(outs, {"eDP-1|": {"mode": "1280x720", "rate": "60.00", "rotate": "left"}})
        self.assertEqual(p["mode"], "1280x720")
        self.assertNotIn("left", p["args"])

    def test_single_monitor(self):
        self.assertIsNone(la.mirror_plan(xr(LAPTOP, OFF), {}))

    def test_layout_mirror_uses_common_mode(self):
        # Prepinac Zrcadlit v Monitorech > Usporadani: stejny vyber rozliseni (nic se neorizne)
        outs = xr(LAPTOP, PROJ)
        lay = la.make_layout(outs, {"eDP-1": (0, 0), "HDMI-1": (1920, 0)}, "eDP-1", mirror=True)
        p = la.plan(outs, {}, {la.set_key(outs): lay})
        self.assertTrue(p["mirror"])
        self.assertEqual(p["pos"], {"eDP-1": (0, 0), "HDMI-1": (0, 0)})
        self.assertIn("--output eDP-1 --mode 1280x720", " ".join(p["args"]))
        self.assertTrue(la.matches(xr(LAPTOP.replace("1920x1080+0+0", "1280x720+0+0"),
                                      PROJ.replace("+1920+0", "+0+0").replace("1024x768+", "1280x720+")), p))


class Unscale(unittest.TestCase):
    def test_detect(self):
        o = xr(LAPTOP)[0]
        self.assertFalse(ld.is_scaled(o))
        self.assertEqual(ld.unscale_args(o), [])
        # TV v rezimu 3840x2160 s plochou 1366x768 (--scale-from ze zrcadleni)
        tv = xr(TV.replace("1920x1080+1366+0", "1366x768+0+0").replace("3840x2160     60.00 +", "3840x2160     60.00*+"))[0]
        self.assertTrue(ld.is_scaled(tv))
        self.assertEqual(ld.unscale_args(tv), ["--scale", "1x1"])
        # otoceny monitor neni meritko
        rot = xr("HDMI-1 connected 1080x1920+0+0 left (normal left inverted right x axis y axis)\n   1920x1080     60.00*+\n")[0]
        self.assertFalse(ld.is_scaled(rot))
        # vypnuty
        self.assertFalse(ld.is_scaled(xr(PROJ.replace("1024x768+1920+0 ", ""))[0]))

    def test_extend_plan_resets_scale(self):
        tv_scaled = TV.replace("1920x1080+1366+0", "1366x768+0+0").replace("3840x2160     60.00 +", "3840x2160     60.00*+")
        outs = xr(SMALL, tv_scaled)
        lay = la.make_layout(outs, {"eDP-1": (0, 0), "HDMI-1": (1366, 0)}, "eDP-1")
        p = la.plan(outs, {}, {la.set_key(outs): lay}, force_extend=True)
        self.assertIn("--output HDMI-1 --auto --rotate normal --scale 1x1 --pos 1366x0", " ".join(p["args"]))
        self.assertNotIn("--scale", " ".join(p["args"]).split("--output HDMI-1")[0])


class Modes(unittest.TestCase):
    def setUp(self):
        self.dell = xr(LAPTOP, DELL.replace("HDMI-1 connected", "HDMI-1 connected"))
        for o in self.dell:
            if o["name"] == "HDMI-1":
                o["edid"] = td.EDID_DELL
        self.proj = xr(LAPTOP, PROJ)
        for o in self.proj:
            if o["name"] == "HDMI-1":
                o["edid"] = EDID_PROJ

    def test_per_set(self):
        modes = la.with_mode({}, self.proj, "mirror")
        modes = la.with_mode(modes, self.dell, "extend")
        self.assertEqual(la.mode_for(self.proj, modes), "mirror")
        self.assertEqual(la.mode_for(self.dell, modes), "extend")
        self.assertIsNone(la.mode_for(xr(LAPTOP), modes))
        self.assertIsNone(la.with_mode(modes, xr(LAPTOP, OFF), "mirror"))     # jeden monitor: nic
        self.assertIsNone(la.with_mode(modes, self.proj, "nonsense"))

    def test_other_port_rekeyed(self):
        # Stejny projektor na DP-2 (dokovaci stanice): rezim se najde podle EDID a ulozi pod novy klic
        modes = la.with_mode({}, self.proj, "mirror")
        moved = xr(LAPTOP, PROJ.replace("HDMI-1", "DP-2"))
        for o in moved:
            if o["name"] == "DP-2":
                o["edid"] = EDID_PROJ
        self.assertIsNone(la.mode_for(moved, modes))      # vestaveny displej bez EDID: jen presna sada
        for o in moved + self.proj:
            if o["name"] == "eDP-1":
                o["edid"] = td.make_edid("PANEL")
        modes = la.with_mode({}, self.proj, "mirror")
        self.assertEqual(la.mode_for(moved, modes), "mirror")
        modes = la.with_mode(modes, moved, "external")
        self.assertEqual(list(modes), [la.set_key(moved)])
        self.assertEqual(la.mode_for(moved, modes), "external")

    def test_storage_keeps_other_keys(self):
        f = td.FakeEnv()
        try:
            ld.save({"eDP-1|": {"mode": "1280x720", "rotate": "normal"}}, f.conf, layouts={"x": {"pos": {}}})
            ld.save(ld.load(f.conf), f.conf, modes={"a+b": {"mode": "mirror"}, "bad": {"mode": "zzz"}})
            self.assertEqual(ld.load_modes(f.conf), {"a+b": {"mode": "mirror"}})
            ld.save({}, f.conf)                     # modes=None ponecha rezimy i rozlozeni
            self.assertEqual(ld.load_modes(f.conf), {"a+b": {"mode": "mirror"}})
            self.assertIn("x", ld.load_layouts(f.conf))
        finally:
            f.cleanup()


def proj_state():
    """Falesny xrandr: notebook 1920x1080 + projektor 4:3 bez 1920x1080."""
    st = td.fake_state()
    st["outputs"][1] = {"name": "HDMI-1", "connected": True, "edid": EDID_PROJ, "mm": [300, 225], "primary": False,
                        "modes": [["1024x768", ["60.00", "75.03"]], ["1280x720", ["60.00", "50.00"]], ["800x600", ["60.32"]]],
                        "preferred": ["1024x768", "60.00"], "current": ["1024x768", "60.00"], "rotation": "normal",
                        "pos": [1920, 0]}
    return st


def tv_state():
    """Falesny xrandr: notebook 1366x768 + televize jen 3840x2160 / 1920x1080."""
    st = td.fake_state()
    st["outputs"][0].update({"modes": [["1366x768", ["60.00"]]], "preferred": ["1366x768", "60.00"],
                             "current": ["1366x768", "60.00"]})
    st["outputs"][1].update({"modes": [["3840x2160", ["60.00", "30.00"]], ["1920x1080", ["60.00"]]],
                             "preferred": ["3840x2160", "60.00"], "current": ["3840x2160", "60.00"], "pos": [1366, 0]})
    return st


class Script(unittest.TestCase):
    """luxos-displays mirror/extend/external s falesnym xrandr, rezim pro sadu monitoru."""

    def setUp(self):
        self.f = td.FakeEnv()
        self.f.env["FAKE_DCONF_LOG"] = os.path.join(self.f.dir, "dconf.log")
        with open(self.f.xfconf, "w") as fh:
            json.dump({"xfce4-panel": {"/panels/panel-1/output-name": "HDMI-1"}}, fh)

    def tearDown(self):
        self.f.cleanup()

    def mode_file(self):
        with open(os.path.join(self.f.dir, "config", "luxos", "displays-mode")) as fh:
            return fh.read().strip()

    def test_mirror_projector_then_extend(self):
        self.f.write_state(proj_state())
        r = self.f.run_displays("mirror")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.f.read_state()
        self.assertEqual(st["eDP-1"]["current"], ["1280x720", "60.00"])
        self.assertEqual(st["HDMI-1"]["current"], ["1280x720", "60.00"])
        self.assertEqual(st["eDP-1"]["pos"], [0, 0])
        self.assertEqual(st["HDMI-1"]["pos"], [0, 0])
        self.assertTrue(st["eDP-1"]["primary"])
        # Horni lista na hlavnim monitoru i v rezimu zrcadleni
        with open(self.f.xfconf) as fh:
            self.assertEqual(json.load(fh)["xfce4-panel"]["/panels/panel-1/output-name"], "Primary")
        self.assertEqual(self.mode_file(), "mirror")
        outs = ld.parse(subprocess_xrandr(self.f))
        self.assertEqual(ld.load_modes(self.f.conf), {la.set_key(outs): {"mode": "mirror"}})
        self.assertEqual(self.f.run_displays("mode").stdout.strip(), "mirror")
        # Rozsirit: zpet doporucene rezimy, projektor vpravo
        self.f.run_displays("extend")
        st = self.f.read_state()
        self.assertEqual(st["eDP-1"]["current"], ["1920x1080", "60.02"])
        self.assertEqual(st["HDMI-1"]["current"], ["1024x768", "60.00"])
        self.assertEqual(st["HDMI-1"]["pos"], [1920, 0])
        self.assertEqual(self.f.run_displays("mode").stdout.strip(), "extend")

    def test_tv_scale_from_and_reset(self):
        self.f.write_state(tv_state())
        self.f.run_displays("mirror")
        self.assertIn("--output HDMI-1 --mode 3840x2160 --rate 60.00 --rotate normal --scale-from 1366x768 --pos 0x0",
                      self.f.calls()[-1])
        st = self.f.read_state()
        self.assertEqual(st["HDMI-1"]["scale_from"], [1366, 768])
        # Rozsireni bez ulozeneho rozlozeni: meritko zpet 1:1, jinak by TV ukazovala zmenseny obraz
        self.f.run_displays("extend")
        self.assertIn("--output HDMI-1 --auto --scale 1x1 --right-of eDP-1", self.f.calls()[-1])
        st = self.f.read_state()
        self.assertIsNone(st["HDMI-1"]["scale_from"])
        self.assertEqual(st["HDMI-1"]["pos"], [1366, 0])
        # Jen externi: vestaveny vypnut, TV hlavni
        self.f.run_displays("mirror")
        self.f.run_displays("external")
        self.assertEqual(self.f.calls()[-1], "--output DP-1 --off --output eDP-1 --off "
                                             "--output HDMI-1 --auto --scale 1x1 --primary --pos 0x0")

    def test_mode_remembered_per_monitor_set(self):
        # Projektor: zrcadlit; monitor Dell: rozsirit. Po opetovnem pripojeni kazdy svuj rezim.
        self.f.write_state(proj_state())
        self.f.run_displays("mirror")
        self.f.write_state(td.fake_state())
        self.f.run_displays("extend")
        self.f.write_state(proj_state())
        self.f.run_displays("auto")
        st = self.f.read_state()
        self.assertEqual(st["HDMI-1"]["pos"], [0, 0])
        self.f.write_state(td.fake_state())
        self.f.run_displays("auto")
        self.assertEqual(self.f.read_state()["HDMI-1"]["pos"], [1920, 0])
        # Nova (neznama) sada: posledni zvoleny rezim (displays-mode), jako drive
        other = proj_state()
        other["outputs"][1]["edid"] = td.make_edid("NEW TV")
        self.f.write_state(other)
        self.assertEqual(self.f.run_displays("mode").stdout.strip(), "extend")
        # Zkusebni pouziti z Monitoru ma prednost
        self.assertEqual(self.f.run_displays("mode", extra={"LUXOS_DISPLAYS_MODE": "mirror"}).stdout.strip(), "mirror")

    def test_single_monitor_mirror_is_harmless(self):
        st = td.fake_state()
        st["outputs"][1]["connected"] = False
        st["outputs"][1]["current"] = None
        self.f.write_state(st)
        r = self.f.run_displays("mirror")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.f.calls()[-1], "--output HDMI-1 --off --output DP-1 --off --output eDP-1 --auto --primary --pos 0x0")
        self.assertEqual(ld.load_modes(self.f.conf), {})


def subprocess_xrandr(f):
    import subprocess
    return subprocess.run([os.path.join(td.FAKE, "xrandr"), "--current", "--prop"], env=dict(os.environ, **f.env),
                          capture_output=True, text=True).stdout


if __name__ == "__main__":
    unittest.main()
