#!/usr/bin/env python3
"""LuxOS - zavoj pod listou a stin widgetu na velmi svetle tapete, cela plocha pod Xvfb.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_desktop_scrim_gui.py -v

Vlastni Xvfb, sbernice (dbus-run-session) a docasny domov; xfwm4 s kompozitorem, xfdesktop,
xfce4-panel s pluginem luxos-bar (prelozen z files/src) a luxos-widgets (lslc, kdyz je). Overuje se:
  - bila tapeta, bile pismo listy: okno zavoje pod listou je videt, tapeta pod listou plynule ztmavne,
    bile pismo listy ma aspon 4,5 : 1 a lista neprepne na tmave pismo,
  - prave tlacitko v pasu zavoje dostane plocha (okno zavoje vstup nebere),
  - Sunrise (bezna svetla tapeta): bez zavoje,
  - tapety podle ploch: bez ulozene volby xfdesktop ukazuje na vsech plochach tapetu plochy 0 -
    lista i zavoj taky; s single-workspace-mode=false tapeta aktivni plochy,
  - DESKTOP_SCRIM=0: bez zavoje, na bile tapete zase tmave pismo (bar-ink dark),
  - widgety: na bile tapete tmavy stin vedle karty,
  - panel v klidu nepracuje (okno zavoje se samo neprekresluje a nemapuje dokola).
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
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "src", "luxos-bar.c")
WIDGETS = os.path.join(HERE, "..", "files", "lsl", "luxos-widgets.lsl")
DESKTOP = os.path.join(HERE, "..", "files", "panel-plugins", "luxos-bar.desktop")
SUNRISE = "/usr/share/backgrounds/luxos/luxos-sunrise.jpg"
NEEDED = ("Xvfb", "dbus-run-session", "xfwm4", "xfdesktop", "xfce4-panel", "xfconf-query", "xdotool", "xprop",
          "gcc", "pkg-config")


def have_tools():
    if not all(shutil.which(t) for t in NEEDED) or not os.path.exists("/usr/lib/xfce4/xfconf/xfconfd"):
        return False
    return subprocess.run(["pkg-config", "--exists", "libxfce4panel-2.0", "libwnck-3.0", "libxfconf-0"]).returncode == 0


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

SOLID_PY = """
import sys, gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
p = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 960, 540)
p.fill(int(sys.argv[2], 16))
p.savev(sys.argv[1], "png", [], [])
"""

# "px X Y" -> linearni jas pixelu na obrazovce
PX_PY = """
import sys, gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk
def lin(v):
    c = v / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
w = Gdk.get_default_root_window()
out = []
for a in sys.argv[1:]:
    x, y = map(int, a.split(","))
    p = Gdk.pixbuf_get_from_window(w, x, y, 1, 1).get_pixels()
    out.append("%.4f" % (0.2126 * lin(p[0]) + 0.7152 * lin(p[1]) + 0.0722 * lin(p[2])))
print(" ".join(out))
"""

SCENARIO = r"""
set -u
mkdir -p "$T/bin"
printf '#!/bin/sh\necho "$*" >>"$T/appearance.log"\n' >"$T/bin/luxos-appearance"
chmod +x "$T/bin/luxos-appearance"
export PATH="$T/bin:$PATH"
conf="$XDG_CONFIG_HOME/luxos/appearance.conf"
/usr/lib/xfce4/xfconf/xfconfd >/dev/null 2>&1 &
sleep 0.5
xfconf-query -c xfwm4 -p /general/workspace_count -n -t int -s 2
setwall() {  # setwall SOUBOR PLOCHY
    for ws in $2; do
        xfconf-query -c xfce4-desktop -p "/backdrop/screen0/monitorscreen/workspace$ws/last-image" -n -t string -s "$1"
        xfconf-query -c xfce4-desktop -p "/backdrop/screen0/monitorscreen/workspace$ws/image-style" -n -t int -s 5
    done
}
scrim() { xdotool search --onlyvisible --name "^LuxOS menu bar scrim$" >/dev/null 2>&1 && echo yes || echo no; }
px() { python3 "$T/px.py" "$@"; }
python3 "$T/solid.py" "$T/white.png" 0xffffffff
setwall "$T/white.png" "0 1"
xfwm4 --compositor=on >/dev/null 2>&1 &
sleep 1.5
xfdesktop >/dev/null 2>&1 &
xfce4-panel >"$T/panel.log" 2>&1 &
pp=$!
for _ in $(seq 80); do xprop -root _NET_WORKAREA 2>/dev/null | grep -q ', 28,' && break; sleep 0.1; done
[ -x "$T/luxos-widgets" ] && "$T/luxos-widgets" >/dev/null 2>&1 &
sleep 4
echo "white-scrim $(scrim)"
# v klidu panel nepracuje (okno zavoje se nesmi samo dokola znovu mapovat)
c0=$(awk '{print $14 + $15}' "/proc/$pp/stat")
sleep 3
echo "idle-ticks $(( $(awk '{print $14 + $15}' "/proc/$pp/stat") - c0 ))"
echo "white-px $(px 900,14 900,60 900,110 900,400)"
echo "white-ink $(grep -c 'bar-ink dark' "$T/appearance.log" 2>/dev/null || echo 0)"
xdotool mousemove 900 70
sleep 0.3
w=$(xdotool getmouselocation --shell | sed -n 's/^WINDOW=//p')
echo "under-scrim $(xprop -id "$w" WM_NAME | sed 's/.*= //' | tr -d '\"' | tr ' ' _)"
echo "white-widget $(px 1598,200 1300,200)"
# Sunrise: bez zavoje a bez stinu
setwall "$SUNRISE" "0 1"
sleep 3
echo "sunrise-scrim $(scrim)"
# tapeta jen na plose 1: bez ulozene volby xfdesktop ukazuje i tam plochu 0 (Sunrise)
setwall "$T/white.png" "1"
xdotool set_desktop 1
sleep 3
echo "ws1-default-scrim $(scrim)"
xfconf-query -c xfce4-desktop -p /backdrop/single-workspace-mode -n -t bool -s false
sleep 3
echo "ws1-perws-scrim $(scrim)"
xdotool set_desktop 0
sleep 3
echo "ws0-perws-scrim $(scrim)"
xdotool set_desktop 1
sleep 3
# vypnuti
printf 'BAR_TEXT=white\nDESKTOP_SCRIM=0\n' >"$conf"
for _ in $(seq 50); do grep -q 'bar-ink dark' "$T/appearance.log" 2>/dev/null && break; sleep 0.1; done
sleep 1.5
echo "optout-scrim $(scrim)"
echo "optout-ink $(grep -c 'bar-ink dark' "$T/appearance.log" 2>/dev/null || echo 0)"
xfce4-panel -q 2>/dev/null
sleep 0.5
"""


@unittest.skipUnless(have_tools(), "needs Xvfb, dbus, xfwm4, xfdesktop, xfce4-panel, xdotool and panel headers")
@unittest.skipUnless(os.path.exists(SUNRISE), "LuxOS wallpapers not installed")
class DesktopScrim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.mkdtemp(prefix="luxos-scrim-gui-")
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
        cls.widgets = bool(shutil.which("lslc"))
        if cls.widgets:
            subprocess.run(["lslc", "--target", "linux-x86_64-gnu", WIDGETS, os.path.join(t, "luxos-widgets")],
                           check=True, capture_output=True)
            with open(os.path.join(cfg, "luxos", "widgets.conf"), "w") as f:
                f.write("ENABLED=1\nWIDGETS=today,system,calendar\n")
        shutil.copy(DESKTOP, os.path.join(data, "xfce4", "panel", "plugins"))
        with open(os.path.join(cfg, "xfce4", "xfconf", "xfce-perchannel-xml", "xfce4-panel.xml"), "w") as f:
            f.write(PANEL_XML)
        with open(os.path.join(cfg, "luxos", "appearance.conf"), "w") as f:
            f.write("BAR_TEXT=white\n")
        for name, body in (("solid.py", SOLID_PY), ("px.py", PX_PY), ("scenario.sh", SCENARIO)):
            with open(os.path.join(t, name), "w") as f:
                f.write(body)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DBUS_", "XDG_", "WAYLAND"))}
        env.update(HOME=home, XDG_CONFIG_HOME=cfg, XDG_DATA_HOME=data, XDG_CACHE_HOME=os.path.join(t, "cache"),
                   XDG_RUNTIME_DIR=os.path.join(t, "run"), XDG_CONFIG_DIRS="/nonexistent",
                   XDG_DATA_DIRS="/usr/share", DISPLAY=":85", T=t, SUNRISE=SUNRISE, GTK_MODULES="",
                   NO_AT_BRIDGE="1", GIO_USE_VFS="local", GVFS_DISABLE_FUSE="1", LANG="C.UTF-8")
        xvfb = subprocess.Popen(["Xvfb", ":85", "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            subprocess.run(["sleep", "1"])
            r = subprocess.run(["dbus-run-session", "--", "bash", os.path.join(t, "scenario.sh")], env=env,
                               capture_output=True, text=True, timeout=240)
        finally:
            xvfb.terminate()
            xvfb.wait(timeout=10)
        cls.out = dict(line.split(" ", 1) for line in r.stdout.splitlines() if " " in line)
        cls.stdout = r.stdout

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.t, True)

    def get(self, key):
        self.assertIn(key, self.out, self.stdout)
        return self.out[key]

    def test_scrim_on_white_wallpaper(self):
        self.assertEqual(self.get("white-scrim"), "yes")
        bar, under, lower, far = map(float, self.get("white-px").split())
        self.assertGreaterEqual(1.05 / (bar + 0.05), 4.5, "bile pismo listy aspon 4,5 : 1")
        # plynule: tesne pod listou tmavsi, niz svetlejsi, daleko puvodni bila
        self.assertLess(under, lower)
        self.assertLess(lower, far)
        self.assertLess(under, 0.75)
        self.assertGreater(far, 0.98)
        self.assertEqual(self.get("white-ink"), "0", "se zavojem zustava bile pismo")

    def test_panel_idle(self):
        """Regrese: okno zavoje (typ DESKTOP) se po kazdem namapovani samo vytahovalo znovu - panel 100 % CPU."""
        self.assertLess(int(self.get("idle-ticks")), 10)

    def test_scrim_takes_no_clicks(self):
        self.assertEqual(self.get("under-scrim"), "Desktop")

    def test_normal_wallpaper_unchanged(self):
        self.assertEqual(self.get("sunrise-scrim"), "no")

    def test_single_workspace_default_like_xfdesktop(self):
        self.assertEqual(self.get("ws1-default-scrim"), "no", "xfdesktop ukazuje Sunrise plochy 0")
        self.assertEqual(self.get("ws1-perws-scrim"), "yes")
        self.assertEqual(self.get("ws0-perws-scrim"), "no")

    def test_opt_out(self):
        self.assertEqual(self.get("optout-scrim"), "no")
        self.assertNotEqual(self.get("optout-ink"), "0", "bez zavoje zase tmave pismo na bile tapete")

    def test_widget_shadow_only_on_bright_wallpaper(self):
        if not self.widgets:
            self.skipTest("needs lslc")
        beside, far = map(float, self.get("white-widget").split())
        self.assertLess(beside, far - 0.05, "stin vedle karty na bile tapete")


if __name__ == "__main__":
    unittest.main()
