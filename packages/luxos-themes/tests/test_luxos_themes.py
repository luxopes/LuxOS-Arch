#!/usr/bin/env python3
"""LuxOS - upravy temat WhiteSur (luxos-themes).

    python3 packages/luxos-themes/tests/test_luxos_themes.py

CSS se musi nacist v GTK 3 bez chyb (chybne pravidlo GTK tise preskoci). Kontroluje i to, co balik doplnuje
k release archivu WhiteSur: ramecky xfwm4 pro HiDPI a chybejici nazvy kurzoru.
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
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, ".."))
FILES = os.path.join(PKG, "files")

CHECK = r"""
import sys
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
errors = []
p = Gtk.CssProvider()
p.connect("parsing-error", lambda _p, sec, err: errors.append("%d: %s" % (sec.get_start_line() + 1, err.message)))
# barvy tematu, na ktere se CSS odkazuje (jinak by GTK hlasilo neznamou barvu)
try:
    p.load_from_data(b"@define-color theme_bg_color #fff; @define-color theme_fg_color #000; "
                     b"@define-color theme_base_color #fff;\n" + open(sys.argv[1], "rb").read())
except Exception as e:  # GTK 3 po chybe navic vyhodi GError
    errors.append(str(e))
print("\n".join(errors))
"""


def css_errors(path):
    r = subprocess.run([sys.executable, "-c", CHECK, path], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise unittest.SkipTest("GTK 3 not available: " + r.stderr[-200:])
    return [e for e in r.stdout.splitlines() if e]


class Css(unittest.TestCase):
    def test_gtk3_css_parses(self):
        self.assertEqual(css_errors(os.path.join(FILES, "luxos-gtk3.css")), [])

    def test_notify_css_parses(self):
        for v in ("Light", "Dark"):
            self.assertEqual(css_errors(os.path.join(FILES, "notify", v + ".css")), [], v)

    def test_keyboard_focus_ring(self):
        """WhiteSur ma outline-width: 0 vsude - tlacitka, zaskrtavatka a zalozky potrebuji vlastni ramecek."""
        with open(os.path.join(FILES, "luxos-gtk3.css")) as f:
            css = f.read()
        block = css[css.index("button:focus,"):]
        block = block[:block.index("}")]
        for sel in ("button:focus", "checkbutton:focus", "radiobutton:focus", "notebook:focus > header > tabs > tab:checked",
                    "list > row:focus", "treeview.view:focus"):
            self.assertIn(sel, block)
        self.assertIn("outline-width: 2px;", block)
        self.assertRegex(css, r"#xfwm-tabwin button:focus,[^{]*\{\s*outline-width: 0;")

    def test_menu_mostly_opaque(self):
        """Bez rozmazani pozadi (xfwm4) musi byt nabidky skoro nepruhledne - jinak prosvita obsah okna."""
        with open(os.path.join(FILES, "luxos-gtk3.css")) as f:
            css = f.read()
        alpha = float(re.search(r"\.background\.popup > menu \{\s*background-color: alpha\(@theme_bg_color, ([0-9.]+)\)", css).group(1))
        self.assertGreaterEqual(alpha, 0.9)


class TitlebarSpec(unittest.TestCase):
    """Zahlavi GTK (CSD) ve stejne mire jako zahlavi kompozitoru luxwm: luxos_tokens.lsl TITLEBAR.
    Pixelove porovnani obou je v packages/luxwm/tests/test_luxwm_titlebar.py."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(FILES, "luxos-gtk3.css")) as f:
            cls.css = f.read()
        tokens = os.path.join(PKG, "..", "luxos-desktop", "files", "lsl", "luxos_tokens.lsl")
        with open(tokens) as f:
            text = f.read()
        block = text[text.index("TITLEBAR = {"):]
        block = block[:block.index("}") + 1]
        cls.spec = {k: float(v) for k, v in re.findall(r'"(\w+)": (-?[\d.]+)(?=[,}])', block)}
        # zaobleni okna je ze stupnice polomeru (RADIUS m), ne ze zahlavi
        cls.spec["radius"] = float(re.search(r'RADIUS = \{[^}]*"m": (\d+)', text).group(1))

    def rule(self, selector):
        m = re.search(r"(?m)^" + re.escape(selector) + r"\s*(?:,[^{]*)?\{([^}]*)\}", self.css)
        self.assertIsNotNone(m, selector)
        return dict((k.strip(), v.strip()) for k, v in (d.split(":", 1) for d in m.group(1).split(";") if ":" in d))

    def px(self, value):
        return float(value.replace("px", "").split()[0])

    def test_heights_and_title(self):
        self.assertEqual(self.px(self.rule("headerbar")["min-height"]), self.spec["height"])
        self.assertEqual(self.px(self.rule("headerbar.compact")["min-height"]), self.spec["height_compact"])
        title = self.rule("headerbar .title")
        self.assertEqual(self.px(title["font-size"]), self.spec["title_px"])
        self.assertEqual(float(title["font-weight"]), self.spec["title_weight"])
        self.assertIn("alpha(@theme_fg_color, %.2f)" % self.spec["inactive_title_alpha"],
                      self.rule("headerbar:backdrop .title")["color"])

    def test_lights_geometry(self):
        """Stred prvniho svetla: okraj headerbaru WhiteSur 8 px + box.left + okraj tlacitka + pul svetla"""
        light = self.rule("headerbar button.titlebutton.close")
        size = self.px(light["min-width"])
        margin = self.px(light["margin"].split()[1])
        self.assertEqual(size, self.spec["light"])
        # GTK dava mezi tlacitka zahlavi 6 px (spacing GtkHeaderBar)
        self.assertEqual(size + 2 * margin + 6, self.spec["pitch"])
        left = self.px(self.rule("headerbar > box.left")["padding-left"])
        self.assertEqual(8 + left + margin + size / 2, self.spec["inset"])
        compact = self.px(self.rule("headerbar.compact")["padding-left"])
        self.assertEqual(compact + left + margin + size / 2, self.spec["inset_compact"])
        self.assertEqual(self.px(light["border-radius"]), size / 2)
        inactive = self.rule("headerbar:backdrop button.titlebutton.close")
        self.assertIn("%.2f" % self.spec["light_inactive_alpha"], inactive["background-color"])
        self.assertIn("%.2f" % self.spec["light_ring_alpha"], inactive["box-shadow"])

    def test_window_radius(self):
        self.assertEqual(self.px(self.rule("window.csd > decoration")["border-radius"]), self.spec["radius"])
        self.assertEqual(self.rule("window.csd > .titlebar")["border-radius"],
                         "%dpx %dpx 0 0" % (self.spec["radius"], self.spec["radius"]))


class Pkgbuild(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(PKG, "PKGBUILD")) as f:
            self.pkg = f.read()

    def test_hidpi_window_frames(self):
        self.assertIn("for s in hdpi xhdpi; do", self.pkg)
        self.assertIn('src/assets/xfwm4/assets-$v-$s"/*.png', self.pkg)
        self.assertIn('WhiteSur-$v-$s/xfwm4/themerc', self.pkg)

    def test_themerc_offsets_scaled(self):
        """Odsazeni tlacitek v themerc se zvetsi jako obrazky (stejny awk jako v PKGBUILD)."""
        prog = re.search(r"awk -F= -v k=\"\$\(.*?\)\" \\\n\s*'([^']+)'", self.pkg).group(1)
        src = "button_offset=10\nbutton_spacing=0\ntitle_horizontal_offset=3\nshow_app_icon=false\n"
        out = subprocess.run(["awk", "-F=", "-v", "k=2", prog], input=src, capture_output=True, text=True,
                             check=True).stdout
        self.assertEqual(out, "button_offset=20\nbutton_spacing=0\ntitle_horizontal_offset=6\nshow_app_icon=false\n")
        out = subprocess.run(["awk", "-F=", "-v", "k=1.5", prog], input=src, capture_output=True, text=True,
                             check=True).stdout
        self.assertIn("button_offset=15\n", out)
        self.assertIn("title_horizontal_offset=5\n", out)

    def test_cursor_aliases(self):
        for alias in ("ew-resize:size_hor", "ns-resize:size_ver", "all-resize:fleur", "dnd-link:link"):
            self.assertIn(alias, self.pkg)


if __name__ == "__main__":
    unittest.main()
