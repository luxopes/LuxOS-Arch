#!/usr/bin/env python3
"""LuxOS - testy polohy podle casoveho pasma (luxos_sun.py, automaticky svetly/tmavy vzhled).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_sun.py -v

Pasma, ktera v zone1970.tab nejsou (Europe/Bratislava, stare nazvy Asia/Calcutta, US/Eastern),
dostanou souradnice ze zone.tab nebo pres odkaz v tzdata.zi - ne Prahu.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "files", "python"))
import luxos_sun  # noqa: E402

ZONE1970 = "#comment\nCZ,SK\t+5005+01426\tEurope/Prague\nIN\t+2232+08822\tAsia/Kolkata\n"
ZONE = "#comment\nCZ\t+5005+01426\tEurope/Prague\nSK\t+4809+01707\tEurope/Bratislava\n"
ZI = "R x 1 2 - - 0 -\nL Asia/Kolkata Asia/Calcutta\nL Europe/Prague Europe/Bratislava\n"


class Location(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        for name, text in (("zone1970.tab", ZONE1970), ("zone.tab", ZONE), ("tzdata.zi", ZI)):
            with open(os.path.join(d, name), "w") as f:
                f.write(text)
        self.saved = luxos_sun.ZONE_TABS, luxos_sun.TZDATA_ZI
        luxos_sun.ZONE_TABS = (os.path.join(d, "zone.tab"), os.path.join(d, "zone1970.tab"))
        luxos_sun.TZDATA_ZI = os.path.join(d, "tzdata.zi")

    def tearDown(self):
        luxos_sun.ZONE_TABS, luxos_sun.TZDATA_ZI = self.saved
        self.tmp.cleanup()

    def near(self, got, lat, lon):
        self.assertAlmostEqual(got[0], lat, places=1)
        self.assertAlmostEqual(got[1], lon, places=1)

    def test_zone1970(self):
        self.near(luxos_sun.location("Asia/Kolkata"), 22.53, 88.37)

    def test_zone_tab_own_coordinates(self):
        self.near(luxos_sun.location("Europe/Bratislava"), 48.15, 17.12)

    def test_old_name_through_link(self):
        self.near(luxos_sun.location("Asia/Calcutta"), 22.53, 88.37)

    def test_unknown_falls_back(self):
        self.assertEqual(luxos_sun.location("Nowhere/Zone"), luxos_sun.DEFAULT)

    def test_missing_files_fall_back(self):
        luxos_sun.ZONE_TABS = ("/nonexistent/zone.tab",)
        luxos_sun.TZDATA_ZI = "/nonexistent/tzdata.zi"
        self.assertEqual(luxos_sun.location("Europe/Prague"), luxos_sun.DEFAULT)


@unittest.skipUnless(os.path.exists("/usr/share/zoneinfo/tzdata.zi"), "needs tzdata")
class RealTzdata(unittest.TestCase):
    def test_common_link_zones(self):
        for name in ("Europe/Bratislava", "Europe/Ljubljana", "Asia/Calcutta", "US/Eastern", "Europe/Kiev"):
            self.assertNotEqual(luxos_sun.location(name), luxos_sun.DEFAULT, name)


LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")


@unittest.skipUnless(LSLC, "needs lslc")
class LslLocation(unittest.TestCase):
    """Stejne chovani v prepisu luxos_sun.lsl (luxos-hub)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        src = os.path.join(cls.tmp.name, "lsl")
        shutil.copytree(os.path.join(HERE, "..", "files", "lsl"), src)
        with open(os.path.join(src, "sun-test.lsl"), "w") as f:
            f.write('load luxos_sun as sun\nloc = sun.location()\nprint String(Int(loc[0] * 100)) + " " + String(Int(loc[1] * 100))\n')
        cls.bin = os.path.join(cls.tmp.name, "sun-test")
        r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", src, os.path.join(src, "sun-test.lsl"), cls.bin],
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stderr + r.stdout
        d = os.path.join(cls.tmp.name, "zi")
        os.makedirs(d)
        for name, text in (("zone1970.tab", ZONE1970), ("zone.tab", ZONE), ("tzdata.zi", ZI)):
            with open(os.path.join(d, name), "w") as f:
                f.write(text)
        cls.tab = os.path.join(d, "zone1970.tab")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def location(self, tz):
        env = dict(os.environ, TZ=tz, LUXOS_ZONE_TAB=self.tab)
        return subprocess.run([self.bin], env=env, capture_output=True, text=True, timeout=10).stdout.strip()

    def test_lookups(self):
        self.assertEqual(self.location("Asia/Kolkata"), "2253 8836")
        self.assertEqual(self.location("Europe/Bratislava"), "4815 1711")
        self.assertEqual(self.location("Asia/Calcutta"), "2253 8836")
        self.assertEqual(self.location("Nowhere/Zone"), "5008 1442")


if __name__ == "__main__":
    unittest.main()
