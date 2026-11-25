#!/usr/bin/env python3
"""LuxOS - testy Kalkulacky (luxos-calculator v LSL): vypocty, formatovani, klavesnice, vlozeni ze schranky.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_calculator.py -v

Aritmetika (files/lsl/luxos_calc.lsl, spolecna s Launchpadem) v tests/lsl/luxos-calc-test.lsl bez displeje;
okno files/lsl/luxos-calculator.lsl ve vlastnim Xvfb rizene pres luxos_testctl (klavesy jako skutecne udalosti
GDK). Cesky desetinny oddelovac jen s lokalizaci cs_CZ (localedef do docasneho LOCPATH). Snimky do
LUXOS_TEST_SHOTS.
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
PKG = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

TMP = tempfile.mkdtemp(prefix="luxos-calculator-test-")
NNBSP = " "


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def czech_locale():
    """LOCPATH s cs_CZ.UTF-8 (hostitel ho nemusi mit vygenerovany); None kdyz to nejde."""
    path = os.path.join(TMP, "locale")
    if not os.path.isdir(os.path.join(path, "cs_CZ.UTF-8")):
        if not shutil.which("localedef"):
            return None
        os.makedirs(path, exist_ok=True)
        subprocess.run(["localedef", "-i", "cs_CZ", "-f", "UTF-8", os.path.join(path, "cs_CZ.UTF-8")],
                       capture_output=True, timeout=60)
    return path if os.path.isdir(os.path.join(path, "cs_CZ.UTF-8")) else None


class Source(unittest.TestCase):
    def test_native_program_replaces_python(self):
        self.assertFalse(os.path.exists(os.path.join(PKG, "files", "bin", "luxos-calculator")))
        with open(os.path.join(PKG, "PKGBUILD")) as f:
            self.assertIn("luxos-calculator", f.read())


class Arithmetic(unittest.TestCase):
    """luxos_calc.lsl: desitkova aritmetika Kalkulacky, funkce, zobrazeni a vypocty Launchpadu."""

    def test_unit(self):
        lslc = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
        if not lslc:
            self.skipTest("lslc (lsl) is not installed")
        out = os.path.join(TMP, "luxos-calc-test")
        r = subprocess.run([lslc, "--target", "linux-x86_64-gnu", "--system-bindings", lsl_app.LSL_DIR,
                            os.path.join(HERE, "lsl", "luxos-calc-test.lsl"), out], capture_output=True, text=True,
                           timeout=900)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run([out], capture_output=True, text=True, timeout=120)
        failed = [line for line in r.stdout.splitlines() if not line.startswith("ok ")]
        self.assertEqual(failed, [])
        self.assertEqual(r.returncode, 0)
        self.assertGreater(len(r.stdout.splitlines()), 150)


class Window(unittest.TestCase):
    """Okno v Xvfb: jedna aplikace pro vsechny testy, mezi testy "reset" (jako nove okno)."""

    @classmethod
    def setUpClass(cls):
        cls.binary = lsl_app.build("luxos-calculator", TMP)
        cls.x = lsl_app.Xvfb("1280x900")
        cls.config = os.path.join(TMP, "config")
        cls.app = cls.start()

    @classmethod
    def start(cls, **extra):
        env = dict(os.environ, DISPLAY=cls.x.display, HOME=TMP, XDG_CONFIG_HOME=cls.config, LANG="C.UTF-8",
                   LC_ALL="C.UTF-8", GTK_THEME="Adwaita")
        env.pop("WAYLAND_DISPLAY", None)
        env.update(extra)
        luxos_testguard.check_env(env)
        app = lsl_app.App([cls.binary], env)
        if not app.wait(lambda: app.dump()):
            raise AssertionError(app.stderr())
        return app

    @classmethod
    def tearDownClass(cls):
        cls.app.stop()
        cls.x.stop()

    def setUp(self):
        self.app.ask("reset")

    def st(self):
        return json.loads(self.app.ask("state", "state"))

    def keys(self, seq):
        self.app.ask("keys " + seq)

    def act(self, action):
        self.app.ask("act " + action)

    def shown(self):
        return self.st()["value"]

    def result(self):
        return self.st()["result"]

    # ---- logika nad klavesovymi sekvencemi (drive OperandLogic) ----

    def test_function_on_parenthesized_expression(self):
        self.keys("(2+3)")
        self.act("func sq")
        self.keys("=")
        self.assertEqual(self.result(), "25")

    def test_function_replaces_only_trailing_operand(self):
        self.keys("10+(2+3)")
        self.act("func sq")
        self.keys("=")
        self.assertEqual(self.result(), "35")

    def test_nested_parentheses(self):
        self.keys("2*((1+2)*3)")
        self.act("func sqrt")
        self.keys("=")
        self.assertEqual(self.result(), "6")

    def test_percent_on_parenthesized_expression(self):
        self.keys("(100+100)")
        self.act("percent")
        self.keys("=")
        self.assertEqual(self.result(), "2")

    def test_negate_parenthesized_expression(self):
        self.keys("(2+3)")
        self.act("negate")
        self.keys("=")
        self.assertEqual(self.result(), "-5")

    def test_negate_zero_then_digit(self):
        self.keys("0")
        self.act("negate")
        self.keys("5")
        self.assertEqual(self.st()["entry"], "-5")
        self.keys("+1=")
        self.assertEqual(self.result(), "-4")

    def test_invalid_function_shows_error(self):
        self.keys("(1-5)")
        self.act("func sqrt")
        self.assertEqual(self.shown(), "Error")

    def test_relative_percent_on_parenthesized_operand(self):
        self.keys("200+(5+5)")
        self.act("percent")
        self.keys("=")
        self.assertEqual(self.result(), "220")

    def test_functions_on_numbers_and_results(self):
        self.keys("9")
        self.act("func sqrt")
        self.keys("=")
        self.assertEqual(self.result(), "3")
        self.act("func sq")
        self.keys("=")
        self.assertEqual(self.result(), "9")

    def test_percent_same_for_number_and_parenthesized_left_operand(self):
        # C-19: 300 + 10 % = 330 a (300) + 10 % musi dat totez (ne 300,1)
        for seq, want in (("300+10", "330"), ("(300)+10", "330"), ("(100+200)+10", "330"), ("2*100+10", "220"),
                          ("50*10", "5")):
            with self.subTest(seq=seq):
                self.app.ask("reset")
                self.keys(seq)
                self.act("percent")
                self.keys("=")
                self.assertEqual(self.result(), want)
        self.app.ask("reset")
        self.keys("5*(200-10")         # uvnitr zavorky jen jeji levy operand
        self.act("percent")
        self.keys(")=")
        self.assertEqual(self.result(), "900")

    def test_extreme_numbers_are_bounded(self):
        # C-05: vysledek mimo rozsah = Error, bez obri alokace
        self.app.ask("set-entry 9e999990")
        self.act("func sq")
        self.assertEqual(self.shown(), "Error")

    def test_unary_operations_report_invalid_parenthesized_expression(self):
        for action in ("percent", "negate"):
            with self.subTest(action=action):
                self.app.ask("reset")
                self.keys("(1/0)")
                self.act(action)
                self.assertEqual(self.shown(), "Error")

    def test_decimal_results(self):
        self.keys("0.1+0.2=")
        self.assertEqual(self.shown(), "0.3")
        self.keys("1234567890123.45-1234567890123=")
        self.assertEqual(self.shown(), "0.45")
        self.keys("1/3*3=")
        self.assertEqual(self.shown(), "1")
        self.keys("2^64=")
        self.assertEqual(self.shown(), "1.84467441e19")

    # ---- okno (drive Window) ----

    def test_basic_sequences(self):
        self.keys("2(3+4)=")
        self.assertEqual(self.shown(), "14")
        self.keys("5+=")
        self.assertEqual(self.shown(), "10")

    def test_lone_number_equals_then_new_number(self):
        # "5 =" a pak "7" ma zacit nove cislo (ne 57), "1. =" ukaze 1 (ne "1.")
        self.keys("5=7")
        self.assertEqual(self.shown(), "7")
        self.act("clear")
        self.act("clear")
        self.keys("1.=")
        self.assertEqual(self.shown(), "1")
        self.keys("+2=")
        self.assertEqual(self.shown(), "3")

    def paste(self, text):
        self.app.ask("copy-text " + text)
        before = self.st()
        self.app.ask("press ctrl+v")
        # schranka se cte asynchronne
        self.app.wait(lambda: self.st() != before, 1.5)

    def test_paste_rejects_nan_and_infinity(self):
        for text in ("NaN", "Infinity", "-inf", "sNaN"):
            self.app.ask("reset")
            self.paste(text)
            self.assertEqual(self.shown(), "0", text)

    def test_paste_exponent_and_long_numbers(self):
        self.paste("1e5")
        self.assertEqual(self.shown(), "100,000")
        self.keys("1")
        self.assertEqual(self.shown(), "1,000,001")
        self.app.ask("reset")
        self.paste("1" * 40)            # delsi nez displej: zaokrouhleny vedecky zapis
        self.assertIn("e39", self.shown())
        self.assertLess(len(self.shown()), 20)
        self.keys("+1=")                # pocita se s plnou hodnotou
        self.assertIn("e39", self.shown())
        self.app.ask("reset")
        self.paste(" 1,234.50 ")        # oddelovac tisicu a mezery pryc, cislice jak byly
        self.assertEqual(self.st()["entry"], "1234.50")
        self.assertEqual(self.shown(), "1,234.50")

    def test_paste_huge_exponent(self):
        # C-05: 1e999999999 ze schranky nesmi alokovat miliardu znaku; ukaze se chyba
        before = self.app.pss_kb()
        self.paste("1e999999999")
        self.assertEqual(self.shown(), "Error")
        self.app.ask("reset")
        self.paste("-1E-999999999")
        self.assertEqual(self.shown(), "Error")
        self.assertLess(self.app.pss_kb() - before, 50 * 1024)
        self.app.ask("reset")
        self.paste("1" * 5000)          # obri text se ignoruje
        self.assertEqual(self.shown(), "0")
        self.paste("2e500")             # velke, ale v rozsahu: vedecky zapis a pocita se dal
        self.assertIn("e500", self.shown())
        self.keys("*2=")
        self.assertIn("e500", self.shown())
        self.assertTrue(self.shown().startswith("4"))

    def test_keyboard_events(self):
        # skutecne udalosti klaves do okna (key-press-event)
        self.app.ask("type 12+3*2")
        self.assertEqual(self.st()["pending"], [])
        self.app.ask("press Return")
        self.assertEqual(self.shown(), "18")
        self.app.ask("type 7.5")
        self.assertEqual(self.st()["clear"], "C")
        self.app.ask("press BackSpace")
        self.assertEqual(self.shown(), "7.")
        self.app.ask("press Escape")          # nove cislo po "=" zapomnelo vysledek
        self.assertEqual((self.shown(), self.st()["clear"]), ("0", "AC"))
        self.app.ask("type 5!")
        self.assertEqual(self.shown(), "120")
        self.app.ask("type -")
        self.assertEqual(self.st()["pending"], ["-"])
        self.app.ask("type 20%=")
        self.assertEqual(self.shown(), "96")
        self.app.ask("type 2^10=")
        self.assertEqual(self.shown(), "1,024")
        # Ctrl+C zkopiruje displej, Ctrl+V ho vlozi zpet
        self.app.ask("press ctrl+c")
        self.app.ask("press Escape Escape")
        self.app.ask("press ctrl+v")
        self.assertTrue(self.app.wait(lambda: self.st()["entry"] == "1024", 1.5))

    def test_scientific_mode_is_remembered(self):
        cfg = os.path.join(self.config, "luxos", "calculator")
        basic = self.st()["size"]
        self.app.ask("press ctrl+2")
        st = self.st()
        self.assertTrue(st["scientific"])
        with open(cfg) as f:
            self.assertEqual(f.read(), "scientific")
        self.assertTrue(self.app.wait(lambda: self.st()["size"][0] > basic[0] + 200), self.st())
        self.app.ask("click Deg")
        self.app.ask("click sin")      # sin(0) v radianech
        self.assertEqual(self.st()["degrees"], False)
        self.app.ask("reset")
        self.app.ask("type 2")
        self.app.ask("click π")
        self.app.ask("press Return")
        self.assertEqual(self.shown(), "6.28318530717959")
        self.app.ask("click Rad")
        self.app.ask("type 30")
        self.app.ask("click sin")
        self.assertEqual(self.shown(), "0.5")
        self.app.ask("type +")
        self.app.ask("click xʸ")
        self.assertEqual(self.st()["pending"], ["^"])
        self.app.ask("press ctrl+1")
        self.assertFalse(self.st()["scientific"])
        with open(cfg) as f:
            self.assertEqual(f.read(), "basic")
        self.assertTrue(self.app.wait(lambda: self.st()["size"] == basic), (self.st()["size"], basic))

    # ---- displej a mazani (z luxos-desktop 1.1.0-108..111 na main) ----

    def test_expression_on_one_line_with_running_result(self):
        self.keys("7*9")
        st = self.st()
        self.assertEqual((st["value"], st["expr"].strip(), st["preview"]), ("7 × 9", "", "= 63"))
        self.assertEqual(st["copy"], "9")           # Ctrl+C kopiruje cislo, ne cely priklad
        self.keys("=")
        st = self.st()
        self.assertEqual((st["value"], st["expr"], st["preview"]), ("63", "7 × 9 =", ""))
        self.act("clear")
        self.keys("7")
        self.assertEqual(self.st()["preview"], "")  # samotne cislo: neni co pocitat

    def test_backspace_after_operator_edits_the_number(self):
        self.keys("425*")
        self.act("backspace")
        st = self.st()
        self.assertEqual((st["value"], st["entry"], st["tokens"]), ("425", "425", []))
        self.act("backspace")
        self.assertEqual(self.shown(), "42")
        # operand delsi nez displej (1/3) zustane cely
        self.app.ask("reset")
        self.keys("1/3=*")
        self.act("backspace")
        self.assertEqual(self.st()["entry"], "")

    def test_backspace_after_equals_returns_the_expression(self):
        self.keys("425/25=")
        self.assertEqual(self.shown(), "17")
        self.act("backspace")
        st = self.st()
        self.assertEqual((st["value"], st["entry"]), ("425 ÷ 25", "25"))
        self.act("backspace")
        st = self.st()
        self.assertEqual((st["value"], st["preview"]), ("425 ÷ 2", "= 212.5"))
        self.keys("5=")
        self.assertEqual(self.shown(), "17")
        # samotny vysledek se maze po cislicich
        self.app.ask("reset")
        self.keys("123=")
        self.act("backspace")
        self.assertEqual(self.shown(), "12")

    def test_error_can_be_corrected(self):
        self.keys("5/0=")
        self.assertEqual(self.shown(), "Error")
        self.act("backspace")
        st = self.st()
        self.assertEqual((st["value"], st["entry"]), ("5 ÷ 0", "0"))
        self.act("backspace")
        self.keys("2=")
        self.assertEqual(self.shown(), "2.5")

    def test_equals_after_open_parenthesis(self):
        self.keys("2*(=")
        self.assertEqual(self.shown(), "4")          # "2 × (" = jako "2 × =" -> 2 × 2
        self.app.ask("reset")
        self.keys("(=")
        self.assertNotEqual(self.shown(), "Error")
        self.app.ask("reset")
        self.keys("(2+3)*(=")
        self.assertEqual(self.shown(), "5")          # "(2+3) ×" bez druheho cisla -> (2+3)

    def test_long_expression_shrinks_then_wraps(self):
        self.keys("1")
        size0 = self.st()["size"]
        self.keys("+2")
        mid = self.st()
        self.assertEqual(mid["value"], "1 + 2")
        self.keys("/9" * 60)
        st = self.st()
        lines = st["value"].split("\n")
        self.assertGreater(len(lines), 1, st["value"])
        self.assertLessEqual(len(lines), 4, st["value"])
        self.assertTrue(lines[0].startswith("…"), lines)
        self.assertTrue(lines[-1].endswith("÷ 9"), lines)
        self.assertEqual(st["size"][0], size0[0])    # sirka okna se nemeni
        self.assertGreater(st["size"][1], size0[1])
        self.keys("=")
        self.assertTrue(self.app.wait(lambda: self.st()["size"][1] <= size0[1] + 2), (self.st()["size"], size0))
        self.assertNotIn("\n", self.st()["value"])

    def test_window_title_and_close_button(self):
        d = self.app.dump()
        self.assertEqual([(w["title"], w["close_button"]) for w in d], [("Calculator", True)])
        self.assertIsNotNone(lsl_app.find(d, text="f(x)"))
        self.assertIsNotNone(lsl_app.find(d, text="÷"))


class Startup(unittest.TestCase):
    """Samostatne spusteni: ulozeny rezim, cestina (oddelovace), Ctrl+Q, pamet."""

    @classmethod
    def setUpClass(cls):
        cls.binary = lsl_app.build("luxos-calculator", TMP)
        cls.x = lsl_app.Xvfb("1280x900")

    @classmethod
    def tearDownClass(cls):
        cls.x.stop()

    def start(self, config, **extra):
        env = dict(os.environ, DISPLAY=self.x.display, HOME=TMP, XDG_CONFIG_HOME=config, LANG="C.UTF-8",
                   LC_ALL="C.UTF-8", GTK_THEME="Adwaita")
        env.pop("WAYLAND_DISPLAY", None)
        env.update(extra)
        luxos_testguard.check_env(env)
        app = lsl_app.App([self.binary], env)
        self.addCleanup(app.stop)
        self.assertTrue(app.wait(lambda: app.dump()), app.stderr())
        return app

    def test_saved_scientific_mode_and_ctrl_q(self):
        config = os.path.join(TMP, "config-sci")
        os.makedirs(os.path.join(config, "luxos"), exist_ok=True)
        with open(os.path.join(config, "luxos", "calculator"), "w") as f:
            f.write("scientific\n")
        app = self.start(config)
        self.assertTrue(json.loads(app.ask("state", "state"))["scientific"])
        app.send("press ctrl+q")
        self.assertEqual(app.proc.wait(10), 0)

    def test_czech_separators(self):
        locpath = czech_locale()
        if not locpath:
            self.skipTest("cs_CZ locale cannot be generated")
        app = self.start(os.path.join(TMP, "config-cs"), LANG="cs_CZ.UTF-8", LC_ALL="cs_CZ.UTF-8", LOCPATH=locpath)
        self.assertEqual(app.dump()[0]["title"], "Kalkulačka")
        self.assertIsNotNone(lsl_app.find(app.dump(), text=",", kind="GtkButton"))
        app.ask("type 1250*1,21")
        app.ask("press Return")
        self.assertEqual(json.loads(app.ask("state", "state"))["value"], "1" + NNBSP + "512,5")
        app.ask("copy-text 2" + NNBSP + "000,5")
        app.ask("press Escape Escape ctrl+v")
        self.assertTrue(app.wait(lambda: json.loads(app.ask("state", "state"))["entry"] == "2000.5", 1.5))
        out = os.environ.get("LUXOS_TEST_SHOTS")
        if out:
            os.makedirs(out, exist_ok=True)
            time.sleep(0.3)
            lsl_app.shot(self.x.display, os.path.join(out, "calculator-cs.png"))

    def test_memory(self):
        app = self.start(os.path.join(TMP, "config-pss"))
        time.sleep(1.0)
        pss = app.pss_kb()
        print("luxos-calculator PSS %d kB" % pss, file=sys.stderr)
        self.assertLess(pss, 60 * 1024)


if __name__ == "__main__":
    unittest.main()
