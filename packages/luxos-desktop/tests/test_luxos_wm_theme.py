#!/usr/bin/env python3
"""luxos-appearance wm-theme: ramecky oken xfwm4 podle meritka - 125-150 % (Monitory > Meritko) varianta
-hdpi (vetsi tlacitka oken i pro dotyk), Gdk/WindowScalingFactor 2 varianta -xhdpi, jinak zakladni;
dotykova obrazovka o stupen vetsi.
Falesny xfconf-query a slozka motivu; nic se nemeni na skutecnem systemu.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_wm_theme.py
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "files", "bin", "luxos-appearance")

XFCONF = r'''#!/bin/sh
case "$*" in
  "-c xsettings -p /Gdk/WindowScalingFactor") echo "$FAKE_WSF" ;;
  "-c xfwm4 -p /general/theme") cat "$FAKE_THEME" ;;
  *"-c xfwm4 -p /general/theme -n -t string -s "*) for a; do last=$a; done; printf "%s" "$last" >"$FAKE_THEME" ;;
  *) exit 1 ;;
esac
'''


class WmTheme(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wmtheme-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        fake = os.path.join(self.tmp, "bin")
        os.makedirs(fake)
        with open(os.path.join(fake, "xfconf-query"), "w") as f:
            f.write(XFCONF)
        os.chmod(os.path.join(fake, "xfconf-query"), 0o755)
        self.themes = os.path.join(self.tmp, "themes")
        for t in ("WhiteSur-Light", "WhiteSur-Light-hdpi", "WhiteSur-Light-xhdpi", "WhiteSur-Dark", "WhiteSur-Dark-hdpi"):
            os.makedirs(os.path.join(self.themes, t, "xfwm4"))
            open(os.path.join(self.themes, t, "xfwm4", "themerc"), "w").close()
        self.cfg = os.path.join(self.tmp, "cfg")
        os.makedirs(os.path.join(self.cfg, "luxos"))
        self.theme = os.path.join(self.tmp, "theme")
        self.path = fake + ":/usr/bin:/bin"

    def wm(self, wsf="1", scale=None, cur="WhiteSur-Light", mode="light", buttons=None):
        with open(self.theme, "w") as f:
            f.write(cur)
        p = os.path.join(self.cfg, "luxos", "display-scale")
        if scale is None:
            if os.path.exists(p):
                os.unlink(p)
        else:
            with open(p, "w") as f:
                f.write("%d\n" % scale)
        with open(os.path.join(self.cfg, "luxos", "appearance"), "w") as f:
            f.write(mode)
        prefs = os.path.join(self.cfg, "luxos", "appearance.conf")
        if buttons is None:
            if os.path.exists(prefs):
                os.unlink(prefs)
        else:
            with open(prefs, "w") as f:
                f.write("WM_BUTTONS=%s\n" % buttons)
        env = {"PATH": self.path, "HOME": self.tmp, "XDG_CONFIG_HOME": self.cfg, "LUXOS_THEMES_DIR": self.themes,
               "FAKE_WSF": wsf, "FAKE_THEME": self.theme}
        r = subprocess.run(["bash", SCRIPT, "wm-theme"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.theme) as f:
            return f.read()

    def test_by_scale(self):
        self.assertEqual(self.wm(), "WhiteSur-Light")
        self.assertEqual(self.wm(scale=100), "WhiteSur-Light")
        self.assertEqual(self.wm(scale=125), "WhiteSur-Light-hdpi")
        self.assertEqual(self.wm(scale=150), "WhiteSur-Light-hdpi")
        self.assertEqual(self.wm(wsf="2", scale=200), "WhiteSur-Light-xhdpi")
        self.assertEqual(self.wm(wsf="2"), "WhiteSur-Light-xhdpi")
        # zpet na 100 % z -hdpi
        self.assertEqual(self.wm(scale=100, cur="WhiteSur-Light-hdpi"), "WhiteSur-Light")

    def test_missing_variant_and_own_theme(self):
        # tmavy rezim bez -xhdpi: nejblizsi mensi (-hdpi); vlastni motiv uzivatele se nemeni
        self.assertEqual(self.wm(wsf="2", scale=200, cur="WhiteSur-Dark", mode="dark"), "WhiteSur-Dark-hdpi")
        self.assertEqual(self.wm(scale=150, cur="Greybird"), "Greybird")
        self.assertEqual(self.wm(scale=150, cur="WhiteSur-Dark", mode="dark"), "WhiteSur-Dark-hdpi")

    def test_touch_screen_bigger_buttons(self):
        """Dotykova obrazovka (touch-state od luxos-touch): o stupen vetsi tlacitka oken pro prst."""
        state = os.path.join(self.cfg, "luxos", "touch-state")
        with open(state, "w") as f:
            f.write("touchscreen=1 keyboard=1 accel=1\n")
        self.assertEqual(self.wm(), "WhiteSur-Light-hdpi")
        self.assertEqual(self.wm(scale=100), "WhiteSur-Light-hdpi")
        self.assertEqual(self.wm(scale=150), "WhiteSur-Light-xhdpi")
        self.assertEqual(self.wm(wsf="2", scale=200), "WhiteSur-Light-xhdpi")
        # tmavy rezim bez -xhdpi: aspon -hdpi
        self.assertEqual(self.wm(scale=150, cur="WhiteSur-Dark", mode="dark"), "WhiteSur-Dark-hdpi")
        # touchscreen=0 a smazany stav (dotykovy monitor odpojen): zase podle meritka
        with open(state, "w") as f:
            f.write("touchscreen=0 keyboard=1 accel=0\n")
        self.assertEqual(self.wm(cur="WhiteSur-Light-hdpi"), "WhiteSur-Light")
        os.unlink(state)
        self.assertEqual(self.wm(scale=150, cur="WhiteSur-Light-xhdpi"), "WhiteSur-Light-hdpi")
        self.assertEqual(self.wm(scale=200, cur="WhiteSur-Light-xhdpi"), "WhiteSur-Light")

    def test_user_choice(self):
        """Volba Monitory > Tlacitka oken (WM_BUTTONS) ma prednost pred automatikou - i na dotyku."""
        with open(os.path.join(self.cfg, "luxos", "touch-state"), "w") as f:
            f.write("touchscreen=1 keyboard=1 accel=1\n")
        self.assertEqual(self.wm(buttons="auto"), "WhiteSur-Light-hdpi")
        self.assertEqual(self.wm(buttons="standard", cur="WhiteSur-Light-hdpi"), "WhiteSur-Light")
        self.assertEqual(self.wm(buttons="standard", scale=150), "WhiteSur-Light-hdpi")   # meritko plati dal
        self.assertEqual(self.wm(buttons="large"), "WhiteSur-Light-hdpi")
        self.assertEqual(self.wm(buttons="larger"), "WhiteSur-Light-xhdpi")
        self.assertEqual(self.wm(buttons="larger", cur="WhiteSur-Dark", mode="dark"), "WhiteSur-Dark-hdpi")
        self.assertEqual(self.wm(buttons="nonsense"), "WhiteSur-Light-hdpi")              # neplatna = auto
        os.unlink(os.path.join(self.cfg, "luxos", "touch-state"))
        self.assertEqual(self.wm(buttons="large"), "WhiteSur-Light-hdpi")                 # i bez dotyku

    def test_wm_buttons_command(self):
        """luxos-appearance wm-buttons: ulozi volbu, hned prepne ramecek; bez hodnoty ji vypise."""
        env = {"PATH": self.path, "HOME": self.tmp, "XDG_CONFIG_HOME": self.cfg, "LUXOS_THEMES_DIR": self.themes,
               "FAKE_WSF": "1", "FAKE_THEME": self.theme}
        with open(self.theme, "w") as f:
            f.write("WhiteSur-Light")
        with open(os.path.join(self.cfg, "luxos", "appearance"), "w") as f:
            f.write("light")

        def run(*args):
            return subprocess.run(["bash", SCRIPT, *args], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(run("wm-buttons").stdout.strip(), "auto")
        r = run("wm-buttons", "larger")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.theme) as f:
            self.assertEqual(f.read(), "WhiteSur-Light-xhdpi")
        self.assertEqual(run("wm-buttons").stdout.strip(), "larger")
        self.assertEqual(run("wm-buttons", "huge").returncode, 2)
        self.assertEqual(run("wm-buttons").stdout.strip(), "larger")


if __name__ == "__main__":
    unittest.main()
