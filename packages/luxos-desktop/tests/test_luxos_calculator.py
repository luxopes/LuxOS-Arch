#!/usr/bin/env python3
"""LuxOS - testy Kalkulacky (luxos-calculator): vypocty, formatovani, vlozeni ze schranky.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_calculator.py -v
GUI cast (okno, klavesy, schranka):
    env -u DISPLAY xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_luxos_calculator.py -v
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
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from decimal import Decimal, DivisionByZero

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "files", "bin", "luxos-calculator")


def load():
    loader = importlib.machinery.SourceFileLoader("luxos_calculator", SCRIPT)
    spec = importlib.util.spec_from_loader("luxos_calculator", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


calc = load()


class Logic(unittest.TestCase):
    def test_evaluate_precedence_and_parens(self):
        D = Decimal
        self.assertEqual(calc.evaluate([D(2), "+", D(3), "*", D(4)]), 14)
        self.assertEqual(calc.evaluate(["(", D(2), "+", D(3), ")", "*", D(4)]), 20)
        self.assertEqual(calc.evaluate([D(2), "^", D(3), "^", D(2)]), 512)   # zprava doleva
        self.assertEqual(calc.evaluate([D("0.1"), "+", D("0.2")]), D("0.3"))
        with self.assertRaises(DivisionByZero):
            calc.evaluate([D(1), "/", D(0)])

    def test_fmt_extremes(self):
        self.assertEqual(calc.fmt(Decimal(0)), "0")
        self.assertIn("e", calc.fmt(Decimal(10) ** 20))
        self.assertIn("e", calc.fmt(Decimal("1e-12")))


# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1) - nikdy skutecna obrazovka
@unittest.skipUnless(os.environ.get("DISPLAY") and ("xvfb-run" in os.environ.get("XAUTHORITY", "")
                                                    or os.environ.get("LUXOS_TEST_X") == "1"),
                     "potrebuje virtualni X (xvfb-run)")
class Window(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        calc.CONFIG = os.path.join(cls.tmp.name, "calculator")   # nemenit skutecne nastaveni
        from gi.repository import Gdk, Gtk
        cls.Gdk, cls.Gtk = Gdk, Gtk

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.c = calc.Calculator()

    def tearDown(self):
        self.c.destroy()

    def keys(self, seq):
        for k in seq:
            if k.isdigit():
                self.c.digit(k)
            elif k == ".":
                self.c.point()
            elif k in "+-*/^":
                self.c.operator(k)
            elif k in "()":
                self.c.paren(k)
            elif k == "=":
                self.c.equals()

    def paste(self, text):
        self.Gtk.Clipboard.get(self.Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        ev = self.Gdk.Event.new(self.Gdk.EventType.KEY_PRESS)
        ev.keyval = self.Gdk.KEY_v
        ev.state = self.Gdk.ModifierType.CONTROL_MASK
        self.assertTrue(self.c.on_key(self.c, ev))

    def shown(self):
        return self.c.value.get_text()

    def test_basic_sequences(self):
        self.keys("2(3+4)=")
        self.assertEqual(self.shown(), "14")
        self.keys("5+=")
        self.assertEqual(self.shown(), "10")

    def test_lone_number_equals_then_new_number(self):
        # "5 =" a pak "7" ma zacit nove cislo (ne 57), "1. =" ukaze 1 (ne "1,")
        self.keys("5=7")
        self.assertEqual(self.shown(), "7")
        self.c.clear()
        self.c.clear()
        self.keys("1.=")
        self.assertEqual(self.shown(), "1")
        self.keys("+2=")
        self.assertEqual(self.shown(), "3")

    def test_paste_rejects_nan_and_infinity(self):
        for text in ("NaN", "Infinity", "-inf", "sNaN"):
            self.c.clear()
            self.c.clear()
            self.paste(text)
            self.assertEqual(self.shown(), "0", text)

    def test_paste_exponent_and_long_numbers(self):
        self.paste("1e5")
        self.assertEqual(self.shown(), calc.group("100000"))
        self.keys("1")
        self.assertEqual(self.shown(), calc.group("1000001"))
        self.c.clear()
        self.paste("1" * 40)            # delsi nez displej: zaokrouhleny vedecky zapis
        self.assertIn("e39", self.shown())
        self.assertLess(len(self.shown()), 20)
        self.keys("+1=")                # pocita se s plnou hodnotou
        self.assertIn("e39", self.shown())


if __name__ == "__main__":
    unittest.main()
