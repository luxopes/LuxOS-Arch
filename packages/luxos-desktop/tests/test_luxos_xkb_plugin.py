#!/usr/bin/env python3
"""LuxOS - plugin listy luxos-xkb (rozlozeni klavesnice jako text US, CZ) ve skutecnem xfce4-panel pod Xvfb.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_xkb_plugin.py -v

Vlastni Xvfb, vlastni sbernice (dbus-run-session) a docasny domov, skutecna relace se nemeni.
Plugin zapisuje s LUXOS_XKB_TEST_LOG, co ukazuje ("label US caps 0 visible 1 n 2 pos X Y").
Overuje se: text velkymi pismeny podle setxkbmap, klik prepne na dalsi rozlozeni (a dokola),
zmena rozlozeni za behu (setxkbmap), Caps Lock, jedno rozlozeni = plugin skryty.
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
SRC = os.path.join(HERE, "..", "files", "src", "luxos-xkb.c")
DESKTOP = os.path.join(HERE, "..", "files", "panel-plugins", "luxos-xkb.desktop")
NEEDED = ("Xvfb", "dbus-run-session", "xfwm4", "xfce4-panel", "xfconf-query", "gcc", "pkg-config", "setxkbmap",
          "xdotool")


def have_tools():
    if not all(shutil.which(t) for t in NEEDED):
        return False
    return subprocess.run(["pkg-config", "--exists", "libxfce4panel-2.0", "x11"]).returncode == 0


PANEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-panel" version="1.0">
  <property name="configver" type="int" value="2"/>
  <property name="panels" type="array"><value type="int" value="1"/>
    <property name="panel-1" type="empty">
      <property name="position" type="string" value="p=6;x=0;y=0"/>
      <property name="length" type="double" value="100"/>
      <property name="position-locked" type="bool" value="true"/>
      <property name="size" type="uint" value="28"/>
      <property name="plugin-ids" type="array"><value type="int" value="1"/></property>
    </property>
  </property>
  <property name="plugins" type="empty">
    <property name="plugin-1" type="string" value="luxos-xkb"/>
  </property>
</channel>
"""

# kazdy krok: akce, pak cekani na novy radek zaznamu a jeho vypis "krok <radek>"
SCENARIO = r"""
set -u
L="$LUXOS_XKB_TEST_LOG"
mark() { wc -l < "$L" 2>/dev/null || echo 0; }
shot() {  # volitelne snimky listy (LUXOS_TEST_SHOTS=slozka)
    [ -n "${LUXOS_TEST_SHOTS:-}" ] || return 0
    python3 -c 'import sys, gi; gi.require_version("Gdk", "3.0"); from gi.repository import Gdk
w = Gdk.get_default_root_window(); Gdk.pixbuf_get_from_window(w, 0, 0, 200, 28).savev(sys.argv[1], "png", [], [])' "$LUXOS_TEST_SHOTS/$1"
}
step() {  # step jmeno pocet_radku_pred
    for _ in $(seq 60); do [ "$(mark)" -gt "$2" ] && break; sleep 0.1; done
    sleep 0.3
    echo "$1 $(tail -1 "$L" 2>/dev/null)"
}
setxkbmap -layout us,cz
xfwm4 --compositor=off >/dev/null 2>&1 &
sleep 1.5
xfce4-panel >"$T/panel.log" 2>&1 &
for _ in $(seq 80); do grep -q 'pos [0-9]' "$L" 2>/dev/null && break; sleep 0.1; done
echo "start $(grep 'pos [0-9]' "$L" | tail -1)"
read -r X Y <<<"$(grep 'pos [0-9]' "$L" | tail -1 | sed 's/.* pos //')"
n=$(mark); xdotool mousemove "$X" "$Y" click 1; step click1 "$n"
n=$(mark); xdotool mousemove "$X" "$Y" click 1; step click2 "$n"
n=$(mark); setxkbmap -layout de,us,cz; step relayout "$n"
shot xkb-badge.png
n=$(mark); xdotool key Caps_Lock; step caps-on "$n"
shot xkb-caps.png
n=$(mark); xdotool key Caps_Lock; step caps-off "$n"
n=$(mark); setxkbmap -layout us; step single "$n"
kill -0 %2 2>/dev/null && echo "panel-alive yes"
xfce4-panel -q 2>/dev/null
sleep 0.5
"""


@unittest.skipUnless(have_tools(), "needs Xvfb, xfwm4, xfce4-panel, setxkbmap, xdotool and libxfce4panel headers")
class XkbPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.mkdtemp(prefix="luxos-xkb-")
        t = cls.t
        home = os.path.join(t, "home")
        cfg = os.path.join(home, ".config")
        data = os.path.join(home, ".local", "share")
        lib = os.path.join(home, ".local", "lib", "xfce4", "panel", "plugins")
        for d in (os.path.join(cfg, "xfce4", "xfconf", "xfce-perchannel-xml"),
                  os.path.join(data, "xfce4", "panel", "plugins"), lib, os.path.join(t, "run")):
            os.makedirs(d, exist_ok=True)
        os.chmod(os.path.join(t, "run"), 0o700)
        flags = subprocess.run(["pkg-config", "--cflags", "--libs", "libxfce4panel-2.0", "gtk+-3.0", "x11"],
                               capture_output=True, text=True, check=True).stdout.split()
        subprocess.run(["gcc", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC", "-o",
                        os.path.join(lib, "libluxos-xkb.so"), SRC, *flags], check=True)
        shutil.copy(DESKTOP, os.path.join(data, "xfce4", "panel", "plugins"))
        with open(os.path.join(cfg, "xfce4", "xfconf", "xfce-perchannel-xml", "xfce4-panel.xml"), "w") as f:
            f.write(PANEL_XML)
        with open(os.path.join(t, "scenario.sh"), "w") as f:
            f.write(textwrap.dedent(SCENARIO))
        cls.log = os.path.join(t, "xkb.log")
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("DBUS_", "XDG_", "WAYLAND", "SESSION_MANAGER", "XAUTHORITY"))}
        env.update(HOME=home, XDG_CONFIG_HOME=cfg, XDG_DATA_HOME=data, XDG_CACHE_HOME=os.path.join(t, "cache"),
                   XDG_RUNTIME_DIR=os.path.join(t, "run"), XDG_CONFIG_DIRS="/nonexistent",
                   XDG_DATA_DIRS="/usr/share", DISPLAY=":88", T=t, GTK_MODULES="", NO_AT_BRIDGE="1",
                   GIO_USE_VFS="local", LUXOS_XKB_TEST_LOG=cls.log, LANG="C")
        # -noreset: bez nej Xvfb po odpojeni posledniho klienta (setxkbmap) vrati rozlozeni na vychozi
        xvfb = subprocess.Popen(["Xvfb", ":88", "-screen", "0", "1280x800x24", "-nolisten", "tcp", "-noreset"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            subprocess.run(["sleep", "1"])
            r = subprocess.run(["dbus-run-session", "--", "bash", os.path.join(t, "scenario.sh")], env=env,
                               capture_output=True, text=True, timeout=120)
        finally:
            xvfb.terminate()
            xvfb.wait(timeout=10)
        cls.stdout = r.stdout + r.stderr[-1500:]
        cls.out = {}
        for line in r.stdout.splitlines():
            name, _, rest = line.partition(" ")
            parts = rest.split()
            cls.out[name] = dict(zip(parts[0::2], parts[1::2])) if parts and parts[0] == "label" else rest

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.t, True)

    def state(self, step):
        self.assertIsInstance(self.out.get(step), dict, (step, self.stdout))
        return self.out[step]

    def test_shows_uppercase_layout_code(self):
        s = self.state("start")
        self.assertEqual((s["label"], s["n"], s["visible"], s["caps"]), ("US", "2", "1", "0"), self.stdout)

    def test_click_cycles_layouts(self):
        self.assertEqual(self.state("click1")["label"], "CZ", self.stdout)
        self.assertEqual(self.state("click2")["label"], "US", "dokola zpet na prvni")

    def test_follows_setxkbmap_while_running(self):
        s = self.state("relayout")
        self.assertEqual((s["label"], s["n"]), ("DE", "3"), self.stdout)
        self.assertEqual(self.out.get("panel-alive"), "yes", "bez restartu panelu")

    def test_caps_lock_indicator(self):
        self.assertEqual(self.state("caps-on")["caps"], "1", self.stdout)
        self.assertEqual(self.state("caps-off")["caps"], "0", self.stdout)

    def test_single_layout_hidden(self):
        s = self.state("single")
        self.assertEqual((s["label"], s["n"], s["visible"]), ("US", "1", "0"), self.stdout)


if __name__ == "__main__":
    unittest.main()
