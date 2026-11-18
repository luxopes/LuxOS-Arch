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
import types
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


class OperandLogic(unittest.TestCase):
    """Klavesove sekvence nad skutecnymi metodami kalkulacky, bez widgetu a bez X serveru."""

    def setUp(self):
        self.shown = None
        self.c = types.SimpleNamespace(tokens=[], entry="", fresh=False, result=None, degrees=True,
                                       op_buttons={})
        for name, method in calc.Calculator.__dict__.items():
            if callable(method) and not name.startswith("__"):
                setattr(self.c, name, types.MethodType(method, self.c))
        self.c.refresh = lambda: None
        self.c.show = lambda expr, value: setattr(self, "shown", value)
        self.c.update_ops = lambda: None

    def keys(self, seq):
        for key in seq:
            if key.isdigit():
                self.c.digit(key)
            elif key in "()":
                self.c.paren(key)
            elif key == "=":
                self.c.equals()
            else:
                self.c.operator(key)

    def test_function_on_parenthesized_expression(self):
        self.keys("(2+3)")
        self.c.func("sq")
        self.c.equals()
        self.assertEqual(self.c.result, Decimal(25))

    def test_function_replaces_only_trailing_operand(self):
        self.keys("10+(2+3)")
        self.c.func("sq")
        self.c.equals()
        self.assertEqual(self.c.result, Decimal(35))

    def test_nested_parentheses(self):
        self.keys("2*((1+2)*3)")
        self.c.func("sqrt")
        self.c.equals()
        self.assertEqual(self.c.result, Decimal(6))

    def test_percent_on_parenthesized_expression(self):
        self.keys("(100+100)")
        self.c.percent()
        self.c.equals()
        self.assertEqual(self.c.result, Decimal(2))

    def test_negate_parenthesized_expression(self):
        self.keys("(2+3)")
        self.c.negate()
        self.c.equals()
        self.assertEqual(self.c.result, Decimal(-5))

    def test_invalid_function_shows_error(self):
        self.keys("(1-5)")
        self.c.func("sqrt")
        self.assertEqual(self.shown, calc._("Error"))

    def test_relative_percent_on_parenthesized_operand(self):
        self.keys("200+(5+5)")
        self.c.percent()
        self.c.equals()
        self.assertEqual(self.c.result, Decimal(220))

    def test_functions_on_numbers_and_results(self):
        self.keys("9")
        self.c.func("sqrt")
        self.c.equals()
        self.assertEqual(self.c.result, Decimal(3))
        self.c.func("sq")
        self.c.equals()
        self.assertEqual(self.c.result, Decimal(9))

    def test_percent_same_for_number_and_parenthesized_left_operand(self):
        # C-19: 300 + 10 % = 330 a (300) + 10 % musi dat totez (ne 300,1)
        for seq in ("300+10", "(300)+10", "(100+200)+10"):
            with self.subTest(seq=seq):
                self.setUp()
                self.keys(seq)
                self.c.percent()
                self.c.equals()
                self.assertEqual(self.c.result, Decimal(330))
        self.setUp()
        self.keys("2*100+10")          # procento z celeho leveho vyrazu (200)
        self.c.percent()
        self.c.equals()
        self.assertEqual(self.c.result, Decimal(220))
        self.setUp()
        self.keys("5*(200-10")         # uvnitr zavorky jen jeji levy operand
        self.c.percent()
        self.keys(")=")
        self.assertEqual(self.c.result, Decimal(900))
        self.setUp()
        self.keys("50*10")              # krat: prosta setina
        self.c.percent()
        self.c.equals()
        self.assertEqual(self.c.result, Decimal(5))

    def trig(self, name, value, degrees=True):
        self.c.degrees = degrees
        return self.c.compute(name, Decimal(value))

    def test_small_trig_results_are_not_rounded_to_zero(self):
        # C-20: maly nenulovy vysledek se ukaze vedecky, ne jako 0
        r = self.trig("sin", "1e-14", degrees=False)
        self.assertNotEqual(r, 0)
        self.assertAlmostEqual(float(r), 1e-14, delta=1e-28)
        self.assertIn("e-14", calc.fmt(r))
        r = self.trig("sin", "180.0000000001")
        self.assertNotEqual(r, 0)
        self.assertAlmostEqual(float(r), -1.745329252e-12, delta=1e-20)
        r = self.trig("cos", "90.000000001")
        self.assertNotEqual(r, 0)
        self.assertNotEqual(self.trig("asin", "1e-14", degrees=False), 0)
        self.assertNotEqual(self.trig("atan", "1e-13", degrees=False), 0)

    def test_exact_angles_stay_exact(self):
        D = Decimal
        for name, value, expected in (("sin", "180", 0), ("sin", "360", 0), ("sin", "-90", -1), ("cos", "90", 0),
                                      ("cos", "270", 0), ("cos", "180", -1), ("tan", "180", 0), ("tan", "45", 1),
                                      ("sin", "30", D("0.5")), ("cos", "60", D("0.5")), ("asin", "0.5", 30),
                                      ("acos", "0.5", 60), ("atan", "1", 45), ("acos", "-1", 180)):
            with self.subTest(name=name, value=value):
                self.assertEqual(self.trig(name, value), expected)
        self.assertEqual(self.trig("sin", calc.PI, degrees=False), 0)
        self.assertEqual(self.trig("cos", calc.PI / 2, degrees=False), 0)
        self.assertEqual(self.trig("sin", calc.PI * 2, degrees=False), 0)
        for value in ("90", "270", "-90"):
            with self.assertRaises(ValueError):
                self.trig("tan", value)
        with self.assertRaises(ValueError):
            self.trig("tan", calc.PI / 2, degrees=False)

    def test_extreme_numbers_are_bounded(self):
        # C-05: obri exponent se odmitne bez obri alokace; vysledky mimo rozsah = Error
        self.assertFalse(calc.in_range(Decimal("1e999999999")))
        self.assertFalse(calc.in_range(Decimal("1e-999999999")))
        self.assertTrue(calc.in_range(Decimal("1e999")))
        self.assertTrue(calc.in_range(Decimal(0)))
        self.assertLess(len(calc.entry_text_for(Decimal("1e999"))), 20)
        self.c.entry = "9" + "e999990"
        self.c.func("sq")
        self.assertEqual(self.shown, calc._("Error"))

    def test_unary_operations_report_invalid_parenthesized_expression(self):
        for operation in ("percent", "negate"):
            with self.subTest(operation=operation):
                self.setUp()
                self.keys("(1/0)")
                getattr(self.c, operation)()
                self.assertEqual(self.shown, calc._("Error"))


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

    def test_paste_huge_exponent(self):
        # C-05: 1e999999999 ze schranky nesmi alokovat miliardu znaku; ukaze se chyba
        import resource
        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        self.paste("1e999999999")
        self.assertEqual(self.shown(), calc._("Error"))
        self.paste("-1E-999999999")
        self.assertEqual(self.shown(), calc._("Error"))
        self.assertLess(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before, 50 * 1024)  # < 50 MB
        self.paste("1" * 5000)          # obri text se ignoruje
        self.c.clear()
        self.c.clear()
        self.paste("2e500")             # velke, ale v rozsahu: vedecky zapis a pocita se dal
        self.assertIn("e500", self.shown())
        self.keys("*2=")
        self.assertIn("e500", self.shown())
        self.assertTrue(self.shown().startswith("4"))


if __name__ == "__main__":
    unittest.main()
