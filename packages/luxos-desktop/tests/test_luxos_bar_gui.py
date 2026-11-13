#!/usr/bin/env python3
"""LuxOS - plugin horni listy luxos-bar ve skutecnem xfce4-panel pod Xvfb.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_bar_gui.py -v

Vlastni displej (Xvfb), vlastni sbernice D-Bus (dbus-run-session) a docasny domov: skutecna
relace uzivatele se nemeni. Plugin se prelozi do docasne slozky ($XDG_DATA_HOME/xfce4/panel/plugins
a ~/.local/lib), panel ho nacte jako uzivatelsky plugin. Overuje se:
  - bez oken lista pruhledna podle BAR_OPACITY; ve vychozim stavu i s maximalizovanym oknem,
  - s BAR_COVER=solid: maximalizovane okno (dotyka se listy) a celoobrazovkove okno v pozadi
    pod malym oknem -> neprusvitna, po zavreni oken zase pruhledna; okno "vzdy vespod" tesne pod listou (widgety plochy) ji nezneprusvitni,
  - vychozi BAR_COVER=wallpaper: s tapetou plugin kresli do listy jeji vyrez s tonem listy
    (panel background-style 2) - okno za listou neprosvita,
  - BAR_CLOCK=center: cas uprostred listy (pixely textu na stredu obrazovky), bez restartu panelu.
"""
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "src", "luxos-bar.c")
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
xfce4-panel -q 2>/dev/null
sleep 0.5
"""

SOLID_PY = """
import sys, gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
p = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 640, 400)
p.fill(0xc03020ff)
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

    def test_wallpaper_drawn_under_bar_not_window_behind(self):
        """Vychozi: lista ukazuje tapetu s tonem listy, i kdyz je za ni bile okno na celou obrazovku."""
        self.assertEqual(self.out.get("wallpaper-style"), "2", self.stdout + self.panel_log[-2000:])
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        p = GdkPixbuf.Pixbuf.new_from_file(os.path.join(self.t, "wallpaper.png"))
        n, rs, px = p.get_n_channels(), p.get_rowstride(), p.get_pixels()
        # svetla lista 62 % (0.96, 0.96, 0.97) pres tapetu #c03020
        want = [round(c * 0.38 + t * 255 * 0.62) for c, t in zip((0xc0, 0x30, 0x20), (0.96, 0.96, 0.97))]
        for x in (300, 900, 1200):
            o = 14 * rs + x * n
            got = list(px[o:o + 3])
            self.assertTrue(all(abs(g - w) <= 6 for g, w in zip(got, want)), (x, got, want))
        # pod listou je opravdu bile okno
        o = 200 * rs + 300 * n
        self.assertEqual(list(px[o:o + 3]), [255, 255, 255])

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
