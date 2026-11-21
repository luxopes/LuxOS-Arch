#!/usr/bin/env python3
"""LuxOS - testy vychodu a zapadu slunce (luxos_sun.lsl: luxos-hub, Nastaveni, luxos-sun pro luxos-appearance auto).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_sun.py -v

Poloha podle casoveho pasma: pasma, ktera v zone1970.tab nejsou (Europe/Bratislava, stare nazvy Asia/Calcutta,
US/Eastern), dostanou souradnice ze zone.tab nebo pres odkaz v tzdata.zi - ne Prahu. Casy podle NOAA na par minut.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")

ZONE1970 = "#comment\nCZ,SK\t+5005+01426\tEurope/Prague\nIN\t+2232+08822\tAsia/Kolkata\n"
ZONE = "#comment\nCZ\t+5005+01426\tEurope/Prague\nSK\t+4809+01707\tEurope/Bratislava\n"
ZI = "R x 1 2 - - 0 -\nL Asia/Kolkata Asia/Calcutta\nL Europe/Prague Europe/Bratislava\n"

# argv: location | times Y M D LAT LON | mode UNIX LAT LON
PROBE = """
load luxos_sun as sun
load luxos_date as date
if args[1] == "location":
    loc = sun.location()
    print String(Int(loc[0] * 100)) + " " + String(Int(loc[1] * 100))
elif args[1] == "times":
    t = sun.sun_times(date.ordinal(Int(args[2]), Int(args[3]), Int(args[4])), Float(args[5]), Float(args[6]))
    if t == None:
        print "-"
    else:
        print String(t[0]) + " " + String(t[1])
    end
else:
    print sun.mode_at(Int(args[2]), [Float(args[3]), Float(args[4])])
end
"""


def compile_lsl(tmp, name, source):
    src = os.path.join(tmp, "lsl")
    if not os.path.isdir(src):
        shutil.copytree(os.path.join(HERE, "..", "files", "lsl"), src)
    path = os.path.join(src, name + ".lsl")
    if source is not None:
        with open(path, "w") as f:
            f.write(source)
    out = os.path.join(tmp, name)
    r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", src, path, out],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr + r.stdout
    return out


@unittest.skipUnless(LSLC, "needs lslc")
class Sun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bin = compile_lsl(cls.tmp.name, "sun-probe", PROBE)
        cls.cli = compile_lsl(cls.tmp.name, "luxos-sun", None)
        d = os.path.join(cls.tmp.name, "zi")
        os.makedirs(d)
        for name, text in (("zone1970.tab", ZONE1970), ("zone.tab", ZONE), ("tzdata.zi", ZI)):
            with open(os.path.join(d, name), "w") as f:
                f.write(text)
        cls.tab = os.path.join(d, "zone1970.tab")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_probe(self, *args, tz="UTC", tab=None):
        env = dict(os.environ, TZ=tz)
        env.pop("LUXOS_ZONE_TAB", None)
        if tab:
            env["LUXOS_ZONE_TAB"] = tab
        r = subprocess.run([self.bin] + [str(a) for a in args], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def location(self, tz, tab=None):
        return self.run_probe("location", tz=tz, tab=tab or self.tab)

    def test_zone1970(self):
        self.assertEqual(self.location("Asia/Kolkata"), "2253 8836")

    def test_zone_tab_own_coordinates(self):
        self.assertEqual(self.location("Europe/Bratislava"), "4815 1711")

    def test_old_name_through_link(self):
        self.assertEqual(self.location("Asia/Calcutta"), "2253 8836")

    def test_unknown_falls_back(self):
        self.assertEqual(self.location("Nowhere/Zone"), "5008 1442")

    def test_missing_files_fall_back(self):
        self.assertEqual(self.location("Europe/Prague", tab="/nonexistent/zone1970.tab"), "5008 1442")

    @unittest.skipUnless(os.path.exists("/usr/share/zoneinfo/tzdata.zi"), "needs tzdata")
    def test_common_link_zones(self):
        for name in ("Europe/Bratislava", "Europe/Ljubljana", "Asia/Calcutta", "US/Eastern", "Europe/Kiev"):
            env = dict(os.environ, TZ=name)
            env.pop("LUXOS_ZONE_TAB", None)
            got = subprocess.run([self.bin, "location"], env=env, capture_output=True, text=True, timeout=10).stdout
            self.assertNotEqual(got.strip(), "5008 1442", name)

    def assert_near(self, unix, hh, mm, day):
        import calendar
        want = calendar.timegm((day[0], day[1], day[2], hh, mm, 0))
        self.assertLess(abs(unix - want), 5 * 60, (unix, want))

    def test_prague_times(self):
        # Praha: 21. 6. 2026 vychod 2:52, zapad 19:15 UTC; 21. 12. vychod 6:58, zapad 15:02 UTC
        rise, sset = map(int, self.run_probe("times", 2026, 6, 21, 50.08, 14.42).split())
        self.assert_near(rise, 2, 52, (2026, 6, 21))
        self.assert_near(sset, 19, 15, (2026, 6, 21))
        rise, sset = map(int, self.run_probe("times", 2026, 12, 21, 50.08, 14.42).split())
        self.assert_near(rise, 6, 58, (2026, 12, 21))
        self.assert_near(sset, 15, 2, (2026, 12, 21))

    def test_mode_day_and_night(self):
        import calendar
        noon = calendar.timegm((2026, 6, 21, 11, 0, 0))
        night = calendar.timegm((2026, 6, 21, 22, 30, 0))
        self.assertEqual(self.run_probe("mode", noon, 50.08, 14.42), "light")
        self.assertEqual(self.run_probe("mode", night, 50.08, 14.42), "dark")

    def test_polar_day_and_night(self):
        import calendar
        self.assertEqual(self.run_probe("times", 2026, 6, 21, 78.2, 15.6), "-")
        midnight_june = calendar.timegm((2026, 6, 21, 0, 0, 0))
        midnight_dec = calendar.timegm((2026, 12, 21, 12, 0, 0))
        self.assertEqual(self.run_probe("mode", midnight_june, 78.2, 15.6), "light")
        self.assertEqual(self.run_probe("mode", midnight_dec, 78.2, 15.6), "dark")
        # jizni polokoule naopak
        self.assertEqual(self.run_probe("mode", midnight_june, -78.0, 166.0), "dark")

    def test_cli_prints_mode(self):
        r = subprocess.run([self.cli], env=dict(os.environ, LUXOS_ZONE_TAB=self.tab, TZ="Europe/Prague"),
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(r.stdout.strip(), ("light", "dark"))


if __name__ == "__main__":
    unittest.main()
