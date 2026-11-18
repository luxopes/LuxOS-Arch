#!/usr/bin/env python3
"""LuxOS - plugin horni listy luxos-bar ve skutecnem xfce4-panel pod Xvfb.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_bar_gui.py -v

Vlastni displej (Xvfb), vlastni sbernice D-Bus (dbus-run-session) a docasny domov: skutecna
relace uzivatele se nemeni. Plugin se prelozi do docasne slozky ($XDG_DATA_HOME/xfce4/panel/plugins
a ~/.local/lib), panel ho nacte jako uzivatelsky plugin. Overuje se:
  - bez oken lista pruhledna podle BAR_OPACITY; ve vychozim stavu i s maximalizovanym oknem,
  - s BAR_COVER=solid: maximalizovane okno (dotyka se listy) a celoobrazovkove okno v pozadi
    pod malym oknem -> neprusvitna, po zavreni oken zase pruhledna; okno "vzdy vespod" tesne pod listou (widgety plochy) ji nezneprusvitni,
  - vychozi BAR_COVER=wallpaper: s tapetou plugin kresli do listy sklo ze stejneho materialu jako
    widgety, oznameni a nabidky (files/src/luxos-glass.c; panel background-style 2) - okno za listou
    neprosvita; v tmavem rezimu tmave sklo, s bilym pismem svetle/tmave sklo a pismo podle tapety,
  - BAR_CLOCK=center: cas uprostred listy (pixely textu na stredu obrazovky), bez restartu panelu.
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
import shutil
import subprocess
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "src", "luxos-bar.c")
GLASS_SRC = os.path.join(HERE, "..", "files", "src", "luxos-glass.c")
DESKTOP = os.path.join(HERE, "..", "files", "panel-plugins", "luxos-bar.desktop")
NEEDED = ("Xvfb", "dbus-run-session", "xfwm4", "xfce4-panel", "xfconfd", "xfconf-query", "gcc", "pkg-config")


def have_tools():
    if not all(shutil.which(t) or os.path.exists("/usr/lib/xfce4/xfconf/" + t) for t in NEEDED):
        return False
    r = subprocess.run(["pkg-config", "--exists", "libxfce4panel-2.0", "libwnck-3.0", "libxfconf-0"])
    return r.returncode == 0


PANEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-panel" version="1.0">
  <property name="configver" type="int" value="2"/>
  <property name="panels" type="array"><value type="int" value="1"/>
    <property name="dark-mode" type="bool" value="false"/>
    <property name="panel-1" type="empty">
      <property name="position" type="string" value="p=6;x=0;y=0"/>
      <property name="length" type="double" value="100"/>
      <property name="position-locked" type="bool" value="true"/>
      <property name="size" type="uint" value="28"/>
      <property name="background-style" type="uint" value="1"/>
      <property name="background-rgba" type="array">
        <value type="double" value="0.96"/><value type="double" value="0.96"/>
        <value type="double" value="0.97"/><value type="double" value="0.62"/>
      </property>
      <property name="plugin-ids" type="array">
        <value type="int" value="1"/><value type="int" value="2"/><value type="int" value="3"/>
      </property>
    </property>
  </property>
  <property name="plugins" type="empty">
    <property name="plugin-1" type="string" value="separator"><property name="style" type="uint" value="0"/></property>
    <property name="plugin-2" type="string" value="luxos-bar"/>
    <property name="plugin-3" type="string" value="separator"><property name="style" type="uint" value="0"/></property>
  </property>
</channel>
"""

WINDOW_PY = """
import sys, gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
mode = sys.argv[1]
w = Gtk.Window(title=mode)
if mode == "max":
    w.maximize()
elif mode == "full":
    w.fullscreen()
elif mode == "white":
    # bila "webova stranka" na celou obrazovku v pozadi
    css = Gtk.CssProvider()
    css.load_from_data(b"window { background: #ffffff; }")
    Gtk.StyleContext.add_provider_for_screen(w.get_screen(), css, 900)
    w.fullscreen()
elif mode == "below":
    # widget plochy hned pod listou (jako luxos-widgets)
    w.set_keep_below(True)
    w.set_decorated(False)
    w.set_default_size(300, 120)
    w.move(900, 28)
else:
    w.set_default_size(300, 200)
    w.move(600, 400)
w.show_all()
Gtk.main()
"""

# Scenar uvnitr dbus-run-session; vysledky radky "KROK alfa"
SCENARIO = r"""
set -u
# luxos-appearance napodoba: plugin jen zapise rozhodnuti o pismu (bar-ink)
mkdir -p "$T/bin"
printf '#!/bin/sh\necho "$*" >>"$T/appearance.log"\n' >"$T/bin/luxos-appearance"
chmod +x "$T/bin/luxos-appearance"
export PATH="$T/bin:$PATH"
alpha() { xfconf-query -c xfce4-panel -p /panels/panel-1/background-rgba | grep -E '^[0-9.]+$' | tail -1; }
wait_alpha() {  # wait_alpha hodnota: az 5 s
    for _ in $(seq 50); do [ "$(alpha)" = "$1" ] && break; sleep 0.1; done
    echo "$2 $(alpha)"
}
/usr/lib/xfce4/xfconf/xfconfd >/dev/null 2>&1 &
sleep 0.5
xfwm4 --compositor=off >/dev/null 2>&1 &
sleep 1
xfce4-panel >"$T/panel.log" 2>&1 &
P=$!
for _ in $(seq 50); do xprop -root _NET_WORKAREA 2>/dev/null | grep -q ', 28,' && break; sleep 0.1; done
sleep 1
wait_alpha 0.620000 empty
# vychozi: lista zustava pruhledna i nad maximalizovanym oknem (pod ni tapeta)
python3 "$T/win.py" max & M=$!
sleep 2
echo "maximized-default $(alpha)"
kill $M
sleep 1
# BAR_COVER=solid: pod oknem neprusvitna
printf 'BAR_COVER=solid\n' > "$XDG_CONFIG_HOME/luxos/appearance.conf"
sleep 1
python3 "$T/win.py" max & M=$!
wait_alpha 1.000000 maximized
kill $M
wait_alpha 0.620000 closed
python3 "$T/win.py" full & F=$!
sleep 1.5
python3 "$T/win.py" small & W=$!
wait_alpha 1.000000 fullscreen-behind
kill $F $W
wait_alpha 0.620000 closed2
python3 "$T/win.py" below & K=$!
sleep 2
echo "below $(alpha)"
kill $K
printf 'BAR_CLOCK=center\n' > "$XDG_CONFIG_HOME/luxos/appearance.conf"
sleep 1.5
python3 "$T/shot.py" "$T/center.png"
kill -0 $P 2>/dev/null && echo "same-panel yes"
# tapeta pod listou: jednobarevna tapeta, za listou bile okno na celou obrazovku
python3 "$T/solid.py" "$T/wall.png"
xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorscreen/workspace0/last-image -n -t string -s "$T/wall.png"
xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorscreen/workspace0/image-style -n -t int -s 5
for _ in $(seq 50); do [ "$(xfconf-query -c xfce4-panel -p /panels/panel-1/background-style)" = 2 ] && break; sleep 0.1; done
echo "wallpaper-style $(xfconf-query -c xfce4-panel -p /panels/panel-1/background-style)"
python3 "$T/win.py" white & F=$!
sleep 1.5
python3 "$T/win.py" small & W=$!
sleep 2
python3 "$T/shot.py" "$T/wallpaper.png" 300
kill $F $W
# bile pismo ve svetlem rezimu: na bile tapete tmave pismo, na tmave zpet bile (zivě, bez restartu)
printf 'BAR_TEXT=white\n' > "$XDG_CONFIG_HOME/luxos/appearance.conf"
python3 "$T/solid.py" "$T/white.png" 0xffffffff
xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorscreen/workspace0/last-image -s "$T/white.png"
for _ in $(seq 50); do grep -q 'bar-ink dark' "$T/appearance.log" 2>/dev/null && break; sleep 0.1; done
echo "ink-white-wallpaper $(tail -1 "$T/appearance.log" 2>/dev/null | tr ' ' _)"
sleep 1.3
python3 "$T/solid.py" "$T/dark.png" 0x203050ff
xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorscreen/workspace0/last-image -s "$T/dark.png"
for _ in $(seq 50); do grep -q 'bar-ink white' "$T/appearance.log" 2>/dev/null && break; sleep 0.1; done
echo "ink-dark-wallpaper $(tail -1 "$T/appearance.log" 2>/dev/null | tr ' ' _)"
echo "ink-calls $(wc -l < "$T/appearance.log")"
kill -0 $P 2>/dev/null && echo "ink-same-panel yes"
# pruhlednost 0 %: svetly rezim = cista tapeta, tmavy rezim = presto tmave sklo (jako luxos-appearance apply)
printf 'BAR_OPACITY=0\n' > "$XDG_CONFIG_HOME/luxos/appearance.conf"
xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorscreen/workspace0/last-image -s "$T/wall.png"
xfconf-query -c xfce4-panel -p /panels/panel-1/background-rgba -t double -s 0.96 -t double -s 0.96 -t double -s 0.97 -t double -s 0
sleep 2
python3 "$T/shot.py" "$T/zero-light.png"
xfconf-query -c xfce4-panel -p /panels/dark-mode -s true
xfconf-query -c xfce4-panel -p /panels/panel-1/background-rgba -t double -s 0.09 -t double -s 0.09 -t double -s 0.12 -t double -s 0
sleep 2
python3 "$T/shot.py" "$T/zero-dark.png"
xfconf-query -c xfce4-panel -p /panels/dark-mode -s false
xfce4-panel -q 2>/dev/null
sleep 0.5
"""

SOLID_PY = """
import sys, gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
p = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 640, 400)
p.fill(int(sys.argv[2], 16) if len(sys.argv) > 2 else 0xc03020ff)
p.savev(sys.argv[1], "png", [], [])
"""

SHOT_PY = """
import sys, gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk
w = Gdk.get_default_root_window()
h = int(sys.argv[2]) if len(sys.argv) > 2 else 28
Gdk.pixbuf_get_from_window(w, 0, 0, w.get_width(), h).savev(sys.argv[1], "png", [], [])
"""


# Ocekavane sklo listy primo z materialu luxos-glass.c (ten porovnava s widgety test_luxos_glass_module):
# tapeta, ink (0 bile pismo, 1 tmave, -1 podle tapety), vystup PNG 1280x28 pro obrazovku 1280x800
GLASS_C = r"""
#define LUXOS_GLASS_MATERIAL_ONLY 1
#include "GLASS_SRC"
#include <stdlib.h>
int main(int argc, char **argv)
{
    GdkRectangle geo = {0, 0, 1280, 800};
    cairo_surface_t *s;
    cairo_t *cr;
    if (argc != 4)
        return 2;
    glass_load_path(argv[1], geo);
    if (!glass.surface)
        return 1;
    s = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 1280, 28);
    cr = cairo_create(s);
    glass_paint(cr, 0, 0, 1280, 28, 0, 0, 0, atoi(argv[2]));
    cairo_destroy(cr);
    return cairo_surface_write_to_png(s, argv[3]) == CAIRO_STATUS_SUCCESS ? 0 : 1;
}
"""


def rgb_at(path, x, y=14):
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    p = GdkPixbuf.Pixbuf.new_from_file(path)
    n, rs, px = p.get_n_channels(), p.get_rowstride(), p.get_pixels()
    o = y * rs + x * n
    return list(px[o:o + 3])


def white_contrast(rgb):
    lin = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in (c / 255 for c in rgb)]
    return 1.05 / (0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2] + 0.05)


@unittest.skipUnless(have_tools(), "needs Xvfb, dbus-run-session, xfwm4, xfce4-panel, xfconf and libxfce4panel headers")
class BarPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.mkdtemp(prefix="luxos-bar-gui-")
        t = cls.t
        home = os.path.join(t, "home")
        cfg = os.path.join(home, ".config")
        data = os.path.join(home, ".local", "share")
        lib = os.path.join(home, ".local", "lib", "xfce4", "panel", "plugins")
        for d in (os.path.join(cfg, "xfce4", "xfconf", "xfce-perchannel-xml"), os.path.join(cfg, "luxos"),
                  os.path.join(data, "xfce4", "panel", "plugins"), lib, os.path.join(t, "run")):
            os.makedirs(d, exist_ok=True)
        os.chmod(os.path.join(t, "run"), 0o700)
        flags = subprocess.run(["pkg-config", "--cflags", "--libs", "libxfce4panel-2.0", "libwnck-3.0",
                                "libxfconf-0", "gtk+-3.0"], capture_output=True, text=True, check=True).stdout.split()
        subprocess.run(["gcc", "-O2", "-Wall", "-Werror", "-shared", "-fPIC", "-o",
                        os.path.join(lib, "libluxos-bar.so"), SRC, *flags, "-lm"], check=True)
        shutil.copy(DESKTOP, os.path.join(data, "xfce4", "panel", "plugins"))
        glass_c = os.path.join(t, "glass.c")
        with open(glass_c, "w") as f:
            f.write(GLASS_C.replace("GLASS_SRC", os.path.abspath(GLASS_SRC)))
        gtk = subprocess.run(["pkg-config", "--cflags", "--libs", "gtk+-3.0"], capture_output=True, text=True,
                             check=True).stdout.split()
        cls.glass_bin = os.path.join(t, "glass")
        subprocess.run(["gcc", "-O2", "-Wall", "-Werror", "-o", cls.glass_bin, glass_c, *gtk, "-lm"], check=True)
        with open(os.path.join(cfg, "xfce4", "xfconf", "xfce-perchannel-xml", "xfce4-panel.xml"), "w") as f:
            f.write(PANEL_XML)
        for name, body in (("win.py", WINDOW_PY), ("shot.py", SHOT_PY), ("solid.py", SOLID_PY), ("scenario.sh", SCENARIO)):
            with open(os.path.join(t, name), "w") as f:
                f.write(textwrap.dedent(body))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DBUS_", "XDG_", "WAYLAND"))}
        env.update(HOME=home, XDG_CONFIG_HOME=cfg, XDG_DATA_HOME=data, XDG_CACHE_HOME=os.path.join(t, "cache"),
                   XDG_RUNTIME_DIR=os.path.join(t, "run"), XDG_CONFIG_DIRS="/nonexistent",
                   XDG_DATA_DIRS="/usr/share", DISPLAY=":87", T=t, GTK_MODULES="", NO_AT_BRIDGE="1",
                   GIO_USE_VFS="local", GVFS_DISABLE_FUSE="1")
        xvfb = subprocess.Popen(["Xvfb", ":87", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            subprocess.run(["sleep", "1"])
            r = subprocess.run(["dbus-run-session", "--", "bash", os.path.join(t, "scenario.sh")], env=env,
                               capture_output=True, text=True, timeout=120)
        finally:
            xvfb.terminate()
            xvfb.wait(timeout=10)
        cls.out = dict(line.split(" ", 1) for line in r.stdout.splitlines() if " " in line)
        cls.stdout = r.stdout
        try:
            with open(os.path.join(t, "panel.log")) as f:
                cls.panel_log = f.read()
        except OSError:
            cls.panel_log = ""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.t, True)

    def step(self, name):
        self.assertIn(name, self.out, "%s\n%s\n%s" % (name, self.stdout, self.panel_log[-2000:]))
        return float(self.out[name])

    def test_translucent_without_windows(self):
        self.assertAlmostEqual(self.step("empty"), 0.62, places=2)

    def test_default_stays_translucent_under_maximized_window(self):
        """Vychozi lista nikdy nezcerna: pod ni je tapeta i s maximalizovanym oknem."""
        self.assertAlmostEqual(self.step("maximized-default"), 0.62, places=2)

    def test_opaque_under_maximized_window(self):
        self.assertAlmostEqual(self.step("maximized"), 1.0, places=2)
        self.assertAlmostEqual(self.step("closed"), 0.62, places=2)

    def test_opaque_with_fullscreen_app_behind_small_window(self):
        self.assertAlmostEqual(self.step("fullscreen-behind"), 1.0, places=2)
        self.assertAlmostEqual(self.step("closed2"), 0.62, places=2)

    def test_desktop_widget_below_keeps_bar_translucent(self):
        """Okno "vzdy vespod" tesne pod listou (widgety plochy) listu nezneprusvitni."""
        self.assertAlmostEqual(self.step("below"), 0.62, places=2)

    def expected_glass(self, ink):
        out = os.path.join(self.t, "expected-%d.png" % ink)
        subprocess.run([self.glass_bin, os.path.join(self.t, "wall.png"), str(ink), out], check=True)
        return out

    def assert_glass(self, shot, ink):
        want_png = self.expected_glass(ink)
        for x in (5, 300, 450, 900, 1200):
            got, want = rgb_at(os.path.join(self.t, shot), x), rgb_at(want_png, x)
            self.assertTrue(all(abs(g - w) <= 3 for g, w in zip(got, want)), (shot, x, got, want))

    def test_wallpaper_drawn_under_bar_not_window_behind(self):
        """Vychozi: lista je sklo z tapety (stejny material jako widgety), i kdyz je za ni bile okno."""
        self.assertEqual(self.out.get("wallpaper-style"), "2", self.stdout + self.panel_log[-2000:])
        # svetly rezim, tmave pismo: svetle sklo
        self.assert_glass("wallpaper.png", 1)
        # rozostrena tapeta se zavojem, ne ostra tapeta s tonem listy ani okno za listou
        tinted = [round(c * 0.38 + t * 255 * 0.62) for c, t in zip((0xc0, 0x30, 0x20), (0.96, 0.96, 0.97))]
        got = rgb_at(os.path.join(self.t, "wallpaper.png"), 900)
        self.assertGreater(max(abs(g - w) for g, w in zip(got, tinted)), 10, (got, tinted))
        self.assertNotEqual(got, [255, 255, 255])
        # pod listou je opravdu bile okno
        self.assertEqual(rgb_at(os.path.join(self.t, "wallpaper.png"), 300, 200), [255, 255, 255])

    def test_white_text_switches_to_dark_on_white_wallpaper(self):
        """BAR_TEXT=white: bila tapeta -> svetle sklo a luxos-appearance bar-ink dark, tmava -> bar-ink white."""
        self.assertEqual(self.out.get("ink-white-wallpaper"), "bar-ink_dark_live", self.stdout + self.panel_log[-2000:])
        self.assertEqual(self.out.get("ink-dark-wallpaper"), "bar-ink_white_live", self.stdout)
        self.assertEqual(self.out.get("ink-calls"), "2", "kazde rozhodnuti jen jednou")
        self.assertEqual(self.out.get("ink-same-panel"), "yes", "pismo se prepina bez restartu panelu")

    def test_dark_mode_is_dark_glass_even_at_zero_opacity(self):
        """BAR_OPACITY=0 nemeni material: svetly rezim svetle sklo, tmavy rezim tmave sklo jako widgety."""
        wall = (0xc0, 0x30, 0x20)
        self.assert_glass("zero-light.png", 1)
        self.assert_glass("zero-dark.png", 0)
        light = rgb_at(os.path.join(self.t, "zero-light.png"), 900)
        dark = rgb_at(os.path.join(self.t, "zero-dark.png"), 900)
        self.assertGreaterEqual(sum(light), sum(wall) - 10, ("svetly rezim neztmavne", light))
        self.assertLess(sum(dark), sum(light), (dark, light))
        # bile pismo v tmavem rezimu citelne (WCAG AA)
        self.assertGreaterEqual(white_contrast(dark), 4.5, dark)

    def test_clock_in_the_middle_without_restart(self):
        self.assertEqual(self.out.get("same-panel"), "yes", "panel se nerestartoval")
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        p = GdkPixbuf.Pixbuf.new_from_file(os.path.join(self.t, "center.png"))
        n, rs, px = p.get_n_channels(), p.get_rowstride(), p.get_pixels()
        bg = px[0:3]

        def text_pixels(x0, x1):
            count = 0
            for y in range(4, 24):
                for x in range(x0, x1):
                    o = y * rs + x * n
                    if sum(abs(px[o + i] - bg[i]) for i in range(3)) > 120:
                        count += 1
            return count
        mid = p.get_width() // 2
        self.assertGreater(text_pixels(mid - 40, mid + 40), 30, "text hodin uprostred listy")
        self.assertEqual(text_pixels(0, 300), 0, "vlevo nic")
        self.assertEqual(text_pixels(p.get_width() - 300, p.get_width()), 0, "vpravo nic")


if __name__ == "__main__":
    unittest.main()
