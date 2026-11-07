#!/usr/bin/env python3
"""LSL IDE - testy oprav: anglicke popisky panelu, lokalni moduly v panelu Symbol, velikost okna.

    python3 -m unittest packages/apps/lsl-ide/tests/test_lsl_ide.py -v
    env -u DISPLAY xvfb-run -a -s "-screen 0 1280x800x24" python3 -m unittest packages/apps/lsl-ide/tests/test_lsl_ide.py -v

Zdroj IDE je jen v archivu lsl-ide-<verze>.tar.gz vedle PKGBUILD - test ho rozbali do docasne
slozky (nebo pouzije LSL_IDE_SRC=/cesta/k/rozbalenemu/lsl-ide). Okna jen pod xvfb-run.
"""
import ast
import glob
import os
import re
import shutil
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="lsl-ide-test-")


def _source_dir():
    if os.environ.get("LSL_IDE_SRC"):
        return os.environ["LSL_IDE_SRC"]
    ver = re.search(r"^pkgver=(\S+)", open(os.path.join(PKG, "PKGBUILD")).read(), re.M).group(1)
    with tarfile.open(os.path.join(PKG, f"lsl-ide-{ver}.tar.gz")) as tf:
        tf.extractall(TMP, filter="data")
    return os.path.join(TMP, f"lsl-ide-{ver}")


SRC = _source_dir()
LSLIDE = os.path.join(SRC, "lslide")
os.environ.update({"HOME": TMP, "XDG_CONFIG_HOME": os.path.join(TMP, "config"),
                   "XDG_CACHE_HOME": os.path.join(TMP, "cache"), "XDG_DATA_HOME": os.path.join(TMP, "data")})
UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")
if not UNDER_XVFB:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"     # nikdy skutecny displej
try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False
sys.path.insert(0, SRC)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def en_table():
    tree = ast.parse(open(os.path.join(LSLIDE, "i18n.py"), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "EN":
            return ast.literal_eval(node.value)
    raise AssertionError("EN table not found")


class TestTranslations(unittest.TestCase):
    """Anglicke UI nesmi ukazovat ceske texty (drive "Závažnost", "Kód" v panelu Problemy)."""

    def files(self):
        return sorted(glob.glob(os.path.join(LSLIDE, "*.py")))

    def test_every_tr_literal_has_english(self):
        en = en_table()
        missing = []
        for f in self.files():
            for node in ast.walk(ast.parse(open(f, encoding="utf-8").read())):
                if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr" and node.args
                        and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                        and node.args[0].value not in en):
                    missing.append(f"{os.path.basename(f)}:{node.lineno}: {node.args[0].value[:50]}")
        self.assertEqual(missing, [])

    def test_header_labels_are_translated(self):
        czech = re.compile(r"[áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]")
        bad = []
        for f in self.files():
            for node in ast.walk(ast.parse(open(f, encoding="utf-8").read())):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("setHeaderLabels", "setHorizontalHeaderLabels")
                        and node.args and isinstance(node.args[0], ast.List)):
                    for el in node.args[0].elts:
                        if isinstance(el, ast.Constant) and isinstance(el.value, str) and (
                                czech.search(el.value) or el.value in ("Kód", "Typ", "Název")):
                            bad.append(f"{os.path.basename(f)}:{node.lineno}: {el.value}")
        self.assertEqual(bad, [])
        en = en_table()
        self.assertEqual((en["Závažnost"], en["Kód"], en["Název"], en["Typ"]), ("Severity", "Code", "Name", "Type"))


@unittest.skipUnless(HAVE_QT, "needs PySide6")
class TestModules(unittest.TestCase):
    """`load` / `from … load` a lokalni moduly podle pravidel compileru (relativne k souboru)."""

    @classmethod
    def setUpClass(cls):
        from lslide import syntax, stdlib_index
        cls.syntax, cls.si = syntax, stdlib_index
        cls.proj = os.path.join(TMP, "proj")
        os.makedirs(os.path.join(cls.proj, "util"), exist_ok=True)
        with open(os.path.join(cls.proj, "helpers.lsl"), "w") as f:
            f.write("# Pomocne funkce\n\n# Druha mocnina\nfunction sq(x):\n    return x * x\nend\n\nclass Box\nend\n")
        with open(os.path.join(cls.proj, "util", "text.lsl"), "w") as f:
            f.write("function hi(name, greeting=\"Ahoj\"):\n    return greeting + name\nend\n")
        cls.main = os.path.join(cls.proj, "main.lsl")
        cls.text = ("load helpers\nload util.text\nload json as j\nload os, time as ot\n"
                    "from helpers load sq as q, Box\nprint helpers.sq(2)\n")
        with open(cls.main, "w") as f:
            f.write(cls.text)

    def test_parsing(self):
        lists = self.syntax.loaded_module_lists(self.text)
        self.assertEqual(lists, {"helpers": ["helpers"], "text": ["util.text"], "j": ["json"], "ot": ["os", "time"]})
        self.assertEqual(self.syntax.loaded_modules(self.text)["ot"], "os")
        self.assertEqual(self.syntax.imported_names(self.text), {"q": ("helpers", "sq"), "Box": ("helpers", "Box")})
        self.assertEqual(self.syntax.loaded_module_lists("x = 1  # load nothing\n"), {})

    def test_local_resolution(self):
        idx = self.si.StdlibIndex()
        mod = idx.resolve("helpers", self.main)
        self.assertEqual((mod.kind, mod.path), ("local", os.path.join(self.proj, "helpers.lsl")))
        self.assertEqual(mod.lookup("sq").line, 4)
        self.assertEqual(mod.lookup("sq").doc, "Druha mocnina")
        self.assertEqual(mod.doc, "Pomocne funkce")
        m2, sym = idx.lookup_member(["util.text"], "hi", self.main)
        self.assertEqual((m2.path, sym.signature), (os.path.join(self.proj, "util", "text.lsl"),
                                                    'text.hi(name, greeting="Ahoj")'))
        self.assertIsNone(idx.resolve("helpers", ""))                 # neulozeny soubor: jen stdlib
        self.assertIsNone(idx.resolve("missing", self.main))
        self.assertIsNone(idx.resolve("..secret", self.main))
        self.assertEqual(idx.lookup_member(["helpers"], "nothing", self.main)[1], None)
        # stdlib se pouzije, kdyz lokalni soubor neni; zmena souboru se projevi (cache podle mtime)
        idx.modules["json"] = self.si.Module("json", "bundled", "/nonexistent/json.lsl")
        self.assertEqual(idx.resolve("json", self.main).kind, "bundled")
        with open(os.path.join(self.proj, "helpers.lsl"), "a") as f:
            f.write("function cube(x):\n    return x * x * x\nend\n")
        os.utime(os.path.join(self.proj, "helpers.lsl"), ns=(1, 10**18))
        self.assertIsNotNone(idx.resolve("helpers", self.main).lookup("cube"))

    def test_window_size_fits_screen(self):
        from lslide.app import default_window_size
        from lslide.qt import QtCore
        self.assertEqual(default_window_size(None), (1280, 820))
        self.assertEqual(default_window_size(QtCore.QRect(0, 0, 1920, 1050)), (1280, 820))
        w, h = default_window_size(QtCore.QRect(0, 0, 1280, 772))      # 1280x800 minus panel
        self.assertEqual((w, h), (1152, 694))
        self.assertEqual(default_window_size(QtCore.QRect(0, 0, 1024, 600)), (921, 540))


@unittest.skipUnless(HAVE_QT, "needs PySide6")
class TestSymbolPanel(unittest.TestCase):
    """Panel Symbol: funkce z lokalniho modulu uz neni "Neznámý symbol"."""

    @classmethod
    def setUpClass(cls):
        from lslide.qt import QtWidgets
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from lslide import i18n
        i18n.set_language("en")
        TestModules.setUpClass()
        cls.main, cls.text = TestModules.main, TestModules.text

    def describe(self, text, line, col):
        from lslide.editor import CodeEditor
        from lslide.symbol_info import SymbolPanel
        from lslide.stdlib_index import StdlibIndex
        idx = StdlibIndex()
        ed = CodeEditor(stdlib_index=idx)
        ed.file_path = self.main
        ed.setPlainText(text)
        c = ed.textCursor()
        c.movePosition(c.MoveOperation.Start)
        c.movePosition(c.MoveOperation.Down, n=line)
        c.movePosition(c.MoveOperation.Right, n=col)
        ed.setTextCursor(c)
        panel = SymbolPanel()
        panel.describe(ed, idx, self.main)
        out = panel.view.toPlainText()
        sig = ed.signature_at_cursor()
        for w in (ed, panel):
            w.deleteLater()
        return out, sig

    def test_local_module_function(self):
        text = self.text + "print text.hi(\"x\")\nprint q(3)\nprint helpers.nope()\n"
        out, sig = self.describe(text, 5, len("print helpers.s"))
        self.assertNotIn("Unknown symbol", out)
        self.assertIn("Module function", out)
        self.assertIn("helpers.sq(x)", out)
        self.assertIn("local module", out)
        self.assertIn("helpers.lsl:4", out)
        self.assertIn("helpers.sq(x)", sig)
        out, _ = self.describe(text, 6, len("print text.h"))
        self.assertIn('text.hi(name, greeting="Ahoj")', out)
        out, _ = self.describe(text, 7, len("print q"))       # from helpers load sq as q
        self.assertNotIn("Unknown symbol", out)
        self.assertIn("Imported from module", out)
        out, _ = self.describe(text, 8, len("print helpers.no"))
        self.assertNotIn("Unknown symbol", out)
        self.assertIn("was not found in module", out)
        out, _ = self.describe(text, 0, len("load hel"))      # samotny modul
        self.assertIn("local module", out)
        self.assertIn("sq", out)

    def test_unknown_still_reported(self):
        out, _ = self.describe("print zzz_unknown\n", 0, len("print zzz"))
        self.assertIn("Unknown symbol", out)


@unittest.skipUnless(HAVE_QT and UNDER_XVFB, "main window only under xvfb-run (never on a real display)")
class TestMainWindow(unittest.TestCase):
    def test_default_window_fits_work_area(self):
        from lslide.qt import QtWidgets, QtGui
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from lslide.app import MainWindow
        win = MainWindow()
        self.addCleanup(win.deleteLater)
        area = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        self.assertLessEqual(win.width(), area.width())
        self.assertLessEqual(win.height(), area.height())
        self.assertLessEqual(win.width(), 1280)
        labels = [win.problems.headerItem().text(i) for i in range(win.problems.columnCount())]
        from lslide import i18n
        if i18n.LANG == "en":
            self.assertEqual(labels[:2], ["Severity", "Code"])
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
