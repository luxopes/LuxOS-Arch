#!/usr/bin/env python3
"""LuxOS - sklo nabidek podle skutecneho pozadi (files/src/luxos-glass.c, on_menu_map) pod Xvfb.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_menu_backdrop.py -v

Vlastni Xvfb, xfwm4 s kompozitorem, vlastni sbernice a xfconfd nad docasnou konfiguraci (skutecna
relace se nemeni). Tapeta je modra, za nabidkou je cervene okno. Program se jmenem xfce4-panel
(modul se nacita jen v liste) otevre vyskakovaci nabidku GTK nad cervenym oknem:
  - vychozi: sklo nabidky je z obrazovky pod ni -> do cervena,
  - MENU_GLASS=wallpaper v ~/.config/luxos/appearance.conf: zase tapeta -> do modra (bez restartu).
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
SRC = os.path.join(HERE, "..", "files", "src", "luxos-glass.c")
# CSS motivu LuxOS (pozadi nabidek se tridou luxos-glass pruhledne) jako uzivatelske gtk.css
THEME_CSS = os.path.join(HERE, "..", "..", "luxos-themes", "files", "luxos-gtk3.css")
NEEDED = ("Xvfb", "dbus-run-session", "xfwm4", "xfconf-query", "gcc", "pkg-config")


def have_tools():
    if not all(shutil.which(t) for t in NEEDED):
        return False
    return subprocess.run(["pkg-config", "--exists", "gtk+-3.0", "libxfconf-0"]).returncode == 0


# Cervene okno pres celou obrazovku (normalni okno, pod nabidkou)
RED_PY = """
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk
w = Gtk.Window(title="red")
w.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.85, 0.1, 0.1, 1))
w.move(0, 0)
w.resize(1280, 800)
w.show_all()
Gtk.main()
"""

# "xfce4-panel": vyskakovaci nabidka u bodu (300, 200); pri kazdem otevreni zapise "menu x y w h"
MENU_PY = """
import sys, gi
from gi.repository import GLib
GLib.set_prgname("xfce4-panel")
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk
log = sys.argv[1]
anchor = Gtk.Window(type=Gtk.WindowType.POPUP)
anchor.move(300, 200)
anchor.resize(1, 1)
anchor.show()
state = {}

def new_menu():
    menu = Gtk.Menu()
    for i in range(6):
        menu.append(Gtk.MenuItem(label="Polozka %d" % i))
    menu.show_all()
    menu.connect("hide", lambda *a: open(log, "a").write("hidden\\n"))
    return menu

def shown(menu):
    def report():
        top = menu.get_toplevel()
        x, y = top.get_position()
        al = menu.get_allocation()
        with open(log, "a") as f:
            f.write("menu %d %d %d %d\\n" % (x + al.x, y + al.y, al.width, al.height))
        return False
    GLib.timeout_add(700, report)

def popup(*a):
    # nova nabidka pro kazde otevreni (jako lista: nabidka pluginu se sestavuje pri kliknuti)
    menu = state["menu"] = new_menu()
    menu.popup_at_rect(anchor.get_window(), Gdk.Rectangle(0, 0, 1, 1), Gdk.Gravity.SOUTH_WEST,
                       Gdk.Gravity.NORTH_WEST, None)
    shown(menu)
    return True

def close(*a):
    menu = state.pop("menu", None)
    if menu:
        menu.popdown()
        GLib.timeout_add(200, lambda: menu.destroy() and False)
    return True

import signal
GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, popup)
GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, close)
open(log, "a").write("ready\\n")
Gtk.main()
"""

SHOT_PY = """
import sys, gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk
x, y, w, h = map(int, sys.argv[2:6])
Gdk.pixbuf_get_from_window(Gdk.get_default_root_window(), x, y, w, h).savev(sys.argv[1], "png", [], [])
"""

SCENARIO = r"""
set -u
L="$T/menu.log"
wait_line() {
    for _ in $(seq 80); do n=$(grep -c "$1" "$L" 2>/dev/null); [ "${n:-0}" -ge "$2" ] && return 0; sleep 0.1; done
    echo "timeout $1 $2"; return 1
}
python3 "$T/solid.py" "$T/blue.png"
xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorscreen/workspace0/last-image -n -t string -s "$T/blue.png"
xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorscreen/workspace0/image-style -n -t int -s 5
xfwm4 --compositor=on >/dev/null 2>&1 &
sleep 2
python3 "$T/red.py" >/dev/null 2>&1 &
sleep 1.5
GTK_MODULES="$MODULE" python3 "$T/menu.py" "$L" 2>"$T/menu.err" &
M=$!
wait_line ready 1
kill -USR1 $M; wait_line '^menu' 1
read -r _ X Y W H <<<"$(grep '^menu' "$L" | tail -1)"
echo "geometry $X $Y $W $H"
python3 "$T/shot.py" "$T/screen.png" "$X" "$Y" "$W" "$H"
kill -USR2 $M; wait_line hidden 1
printf 'MENU_GLASS=wallpaper\n' > "$XDG_CONFIG_HOME/luxos/appearance.conf"
kill -USR1 $M; wait_line '^menu' 2
read -r _ X Y W H <<<"$(grep '^menu' "$L" | tail -1)"
python3 "$T/shot.py" "$T/wallpaper.png" "$X" "$Y" "$W" "$H"
kill -USR2 $M; wait_line hidden 2
rm -f "$XDG_CONFIG_HOME/luxos/appearance.conf"
kill -USR1 $M; wait_line '^menu' 3
python3 "$T/shot.py" "$T/screen2.png" "$X" "$Y" "$W" "$H"
kill $M
echo "log $(tr '\n' '|' < "$L")"
"""

SOLID_PY = """
import sys, gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
p = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 640, 400)
p.fill(0x2040d0ff)
p.savev(sys.argv[1], "png", [], [])
"""


def mean_rgb(path):
    """Prumer pravych 40 % nabidky (bez textu polozek)."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    p = GdkPixbuf.Pixbuf.new_from_file(path)
    n, rs, px = p.get_n_channels(), p.get_rowstride(), p.get_pixels()
    w, h = p.get_width(), p.get_height()
    total, count = [0, 0, 0], 0
    for y in range(h // 4, 3 * h // 4):
        for x in range(int(w * 0.6), w - 8):
            o = y * rs + x * n
            for i in range(3):
                total[i] += px[o + i]
            count += 1
    return [t / max(1, count) for t in total]


@unittest.skipUnless(have_tools(), "needs Xvfb, xfwm4, xfconf and gtk3 headers")
class MenuBackdrop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.mkdtemp(prefix="luxos-menu-backdrop-")
        t = cls.t
        cfg = os.path.join(t, "config")
        os.makedirs(os.path.join(cfg, "luxos"))
        os.makedirs(os.path.join(cfg, "gtk-3.0"))
        shutil.copy(THEME_CSS, os.path.join(cfg, "gtk-3.0", "gtk.css"))
        os.makedirs(os.path.join(t, "run"), mode=0o700)
        module = os.path.join(t, "libluxos-glass.so")
        flags = subprocess.run(["pkg-config", "--cflags", "--libs", "gtk+-3.0", "libxfconf-0"],
                               capture_output=True, text=True, check=True).stdout.split()
        subprocess.run(["gcc", "-O2", "-Wall", "-Werror", "-shared", "-fPIC", "-o", module, SRC, *flags, "-lm"],
                       check=True)
        for name, body in (("red.py", RED_PY), ("menu.py", MENU_PY), ("shot.py", SHOT_PY), ("solid.py", SOLID_PY),
                           ("scenario.sh", SCENARIO)):
            with open(os.path.join(t, name), "w") as f:
                f.write(textwrap.dedent(body))
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("DBUS_", "XDG_", "WAYLAND", "SESSION_MANAGER", "XAUTHORITY", "GTK_"))}
        env.update(HOME=t, XDG_CONFIG_HOME=cfg, XDG_CACHE_HOME=os.path.join(t, "cache"),
                   XDG_RUNTIME_DIR=os.path.join(t, "run"), XDG_CONFIG_DIRS="/nonexistent", XDG_DATA_DIRS="/usr/share",
                   DISPLAY=":86", T=t, MODULE=module, NO_AT_BRIDGE="1", GIO_USE_VFS="local", GTK_THEME="Adwaita")
        xvfb = subprocess.Popen(["Xvfb", ":86", "-screen", "0", "1280x800x24", "-nolisten", "tcp", "-noreset"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            subprocess.run(["sleep", "1"])
            r = subprocess.run(["dbus-run-session", "--", "bash", os.path.join(t, "scenario.sh")], env=env,
                               capture_output=True, text=True, timeout=120)
        finally:
            xvfb.terminate()
            xvfb.wait(timeout=10)
        cls.stdout = r.stdout + r.stderr[-1500:]
        try:
            with open(os.path.join(t, "menu.err")) as f:
                cls.stdout += f.read()[-1500:]
        except OSError:
            pass

    @classmethod
    def tearDownClass(cls):
        if not os.environ.get("LUXOS_KEEP"):
            shutil.rmtree(cls.t, True)

    def colors(self, name):
        path = os.path.join(self.t, name)
        self.assertTrue(os.path.exists(path), (name, self.stdout))
        return mean_rgb(path)

    def test_glass_from_screen_under_menu(self):
        r, g, b = self.colors("screen.png")
        self.assertGreater(r, b + 20, ("sklo z cerveneho okna pod nabidkou", (r, g, b), self.stdout))

    def test_wallpaper_switch_without_restart(self):
        r, g, b = self.colors("wallpaper.png")
        self.assertGreater(b, r + 20, ("MENU_GLASS=wallpaper: modra tapeta", (r, g, b), self.stdout))
        r, g, b = self.colors("screen2.png")
        self.assertGreater(r, b + 20, ("bez volby zase obrazovka", (r, g, b)))


if __name__ == "__main__":
    unittest.main()
