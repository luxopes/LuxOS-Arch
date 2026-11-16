#!/usr/bin/env python3
"""LuxOS - upravy temat WhiteSur (luxos-themes).

    python3 packages/luxos-themes/tests/test_luxos_themes.py

CSS se musi nacist v GTK 3 bez chyb (chybne pravidlo GTK tise preskoci). Kontroluje i to, co balik doplnuje
k release archivu WhiteSur: ramecky xfwm4 pro HiDPI a chybejici nazvy kurzoru.
"""
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
