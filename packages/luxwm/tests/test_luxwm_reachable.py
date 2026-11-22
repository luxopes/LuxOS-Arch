"""Zahlavi okna zustava dosazitelne (pripominka 28): okno zatazene pod listu uz neslo chytit ani zavrit.

Presun mysi (jadro, input.c keep_reachable), obnoveni z maximalizace a zmena pouzitelne plochy (luxwm keep_reachable)
a presun se Super kdekoli v okne.

  packages/luxwm/tests/build-host.sh
  scripts/wl-test/run-all packages/luxwm/tests/test_luxwm_reachable.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_luxwm import BAR, BUILD, TITLE, H, W, Session, frame  # noqa: E402

REACH_X = 100


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")), "build first: packages/luxwm/tests/build-host.sh")
class Reachable(unittest.TestCase):
    def setUp(self):
        self.s = Session()
        self.addCleanup(self.s.stop)

    def tearDown(self):
        self.assertNotIn("error in", self.s.log())
        self.assertNotIn("LSL callback error", self.s.log())

    def view(self, title):
        return self.s.state()["views"][title]

    def drag_title(self, title, to_x, to_y):
        v = self.view(title)
        x, y = v["x"] + v["w"] // 2, v["y"] - TITLE // 2
        self.s.input(f"drag {x} {y} {to_x} {to_y} 400", wait=0.5)
        return self.view(title)

    def test_drag_under_bar_and_off_screen(self):
        s = self.s
        s.bar()
        s.client("A")
        # nahoru pres listu az za horni okraj: ram konci pod listou
        a = self.drag_title("A", 640, -300)
        self.assertEqual(frame(a)[1], BAR, frame(a))
        # zavrit jde: semafor je na obrazovce (cervene kolecko)
        r, g, b = s.pixel(a["x"] + 18, a["y"] - TITLE // 2)
        self.assertTrue(r > 180 and g < 140, (r, g, b))
        # dolu za spodni okraj: zahlavi zustava cele nad spodkem
        a = self.drag_title("A", 640, H + 300)
        self.assertEqual(frame(a)[1], H - TITLE, frame(a))
        # vpravo a vlevo za okraj (chyceno u kraje okna, kurzor zustava na obrazovce): kus okna zustava
        a = self.view("A")
        s.input("keydown super", f"drag {a['x'] + 5} {a['y'] + 150} {W + 900} 400 400", "keyup super", wait=0.5)
        a = self.view("A")
        self.assertEqual(a["x"], W - REACH_X)
        s.input(f"drag {a["x"] + 80} {a["y"] - TITLE // 2} 900 400 400", wait=0.5)
        a = self.view("A")
        s.input(f"drag {a['x'] + a['w'] - 10} {a['y'] - TITLE // 2} -900 400 400", wait=0.5)
        a = self.view("A")
        self.assertEqual(a["x"] + a["w"], REACH_X)
        s.shot("reachable-left.png")
        # zpet doprostred jde (za kus zahlavi u okraje)
        s.input(f"drag {REACH_X // 2} {a['y'] - TITLE // 2} 640 300 400", wait=0.5)
        a = self.view("A")
        self.assertGreater(a["x"], 200)

    def test_super_drag_anywhere(self):
        s = self.s
        s.client("A", size="400x300")
        a = self.view("A")
        cx, cy = a["x"] + 200, a["y"] + 150
        log = os.path.join(s.dir, "clients.log")
        before = open(log).read().count("button")
        s.input("keydown super", f"drag {cx} {cy} {cx + 120} {cy + 60} 400", "keyup super", wait=0.5)
        b = self.view("A")
        self.assertEqual((b["x"] - a["x"], b["y"] - a["y"]), (120, 60))
        self.assertEqual(open(log).read().count("button"), before, "the client must not get the Super+click")
        # pod listu ani se Super
        s.bar()
        b = self.view("A")
        s.input("keydown super", f"drag {b['x'] + 200} {b['y'] + 150} {b['x'] + 200} -400 400", "keyup super", wait=0.5)
        self.assertEqual(frame(self.view("A"))[1], BAR)
        # bez Super klik do okna dostane klient a okno stoji
        b = self.view("A")
        s.input(f"drag {b['x'] + 200} {b['y'] + 150} {b['x'] + 300} {b['y'] + 200} 300", wait=0.5)
        self.assertEqual(self.view("A")["x"], b["x"])
        self.assertGreater(open(log).read().count("button"), before)

    def test_restore_and_taller_bar(self):
        s = self.s
        s.bar()
        s.client("A")
        a = self.drag_title("A", 640, 0)
        self.assertEqual(frame(a)[1], BAR)
        s.input("key super+Up", wait=0.6)
        self.assertEqual(self.view("A")["maximized"], 1)
        # druha lista: pouzitelna plocha zacina niz, obnovene okno nesmi skoncit pod ni
        s.bar(40)
        top = s.state()["usable"][1]
        self.assertEqual(top, BAR + 40)
        s.input("key super+Up", wait=0.6)
        a = self.view("A")
        self.assertEqual((a["maximized"], frame(a)[1]), (0, top), frame(a))


if __name__ == "__main__":
    unittest.main()
