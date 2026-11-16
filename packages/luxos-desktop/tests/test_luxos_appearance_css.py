#!/usr/bin/env python3
"""luxos-appearance panel-css: spravovany blok v ~/.config/gtk-3.0/gtk.css (barvy listy, prepinac ploch).

    python3 packages/luxos-desktop/tests/test_luxos_appearance_css.py

Bez X a bez skutecneho panelu: pgrep a xfce4-panel jsou napodoby v PATH (zapisuji volani).
"""
import os
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "files", "bin", "luxos-appearance")


class PanelCss(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-appearance-css-")
        self.cfg = os.path.join(self.tmp, "config")
        self.bin = os.path.join(self.tmp, "bin")
        self.log = os.path.join(self.tmp, "calls")
        os.makedirs(os.path.join(self.cfg, "luxos"))
        os.makedirs(self.bin)
        for name in ("pgrep", "xfce4-panel"):
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write('#!/bin/sh\necho "%s $*" >> "%s"\nexit 0\n' % (name, self.log))
            os.chmod(path, 0o755)
        # panel teto relace nabizi /org/xfce/Panel na sbernici
        path = os.path.join(self.bin, "gdbus")
        with open(path, "w") as f:
            f.write('#!/bin/sh\ncase "$*" in *GetNameOwner*) echo "(\':1.$(date +%N)\',)"; exit;; esac\necho "  interface org.xfce.Panel {"\n')
        os.chmod(path, 0o755)
        self.css = os.path.join(self.cfg, "gtk-3.0", "gtk.css")

    def run_css(self, mode):
        with open(os.path.join(self.cfg, "luxos", "appearance"), "w") as f:
            f.write(mode + "\n")
        # bez pluginu luxos-bar: panel-css jinak upravuje rozlozeni listy pres skutecne xfconf-query
        env = dict(os.environ, XDG_CONFIG_HOME=self.cfg, PATH=self.bin + ":" + os.environ["PATH"], XDG_RUNTIME_DIR=self.tmp,
                   DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent",
                   XDG_DATA_HOME=os.path.join(self.tmp, "data"), XDG_DATA_DIRS=os.path.join(self.tmp, "share"))
        subprocess.run(["bash", SCRIPT, "panel-css"], env=env, check=True, capture_output=True)

    def read(self, path):
        try:
            with open(path) as f:
                return f.read()
        except OSError:
            return ""

    def restarts(self, expected):
        # restart bezi na pozadi (&): chvili pockat, pak spocitat
        for _ in range(40):
            if self.read(self.log).count("xfce4-panel -r") >= expected:
                break
            time.sleep(0.05)
        time.sleep(0.1)
        return self.read(self.log).count("xfce4-panel -r")

    def test_light_block(self):
        self.run_css("light")
        css = self.read(self.css)
        self.assertIn("#XfcePanelWindow, #XfcePanelWindowWrapper, #XfcePanelWindow label", css)
        self.assertIn("#XfcePanelWindow grid > button:checked, #XfcePanelWindowWrapper grid > button:checked"
                      " { background: alpha(#3d7bff, 0.22); }", css)
        self.assertIn("alpha(#1d1d1f, 0.55)", css)
        self.assertIn("#XfcePanelWindow wnck-pager, #XfcePanelWindowWrapper wnck-pager { background: transparent; }", css)

    def test_dark_block_without_text_color(self):
        self.run_css("dark")
        css = self.read(self.css)
        self.assertNotIn("#XfcePanelWindow label", css)
        self.assertNotIn("color: inherit", css)
        self.assertIn("alpha(#ffffff, 0.55)", css)

    def test_panel_restarted_only_on_change_and_user_css_kept(self):
        os.makedirs(os.path.dirname(self.css))
        with open(self.css, "w") as f:
            f.write("/* moje */\nlabel { color: red; }\n")
        self.run_css("light")
        self.assertEqual(self.restarts(1), 1)
        self.run_css("light")
        self.assertEqual(self.restarts(1), 1)          # beze zmeny bloku zadny restart
        self.run_css("dark")
        self.assertEqual(self.restarts(2), 2)
        css = self.read(self.css)
        self.assertIn("label { color: red; }", css)
        self.assertEqual(css.count("LuxOS appearance begin"), 1)

    def test_gtk4_window_buttons(self):
        """GTK 4/libadwaita (Celluloid): barevna tlacitka oken jako xfwm4, obsah souboru uzivatele zustava."""
        css4 = os.path.join(self.cfg, "gtk-4.0", "gtk.css")
        os.makedirs(os.path.dirname(css4))
        with open(css4, "w") as f:
            f.write("/* moje */\nlabel { color: red; }\n")
        self.run_css("light")
        self.run_css("dark")
        css = self.read(css4)
        self.assertIn("label { color: red; }", css)
        self.assertEqual(css.count("LuxOS window buttons begin"), 1)
        self.assertIn("windowcontrols > button.close > image { background-color: #ff5f57; }", css)
        self.assertIn("windowcontrols > button.minimize > image { background-color: #febc2e; }", css)
        self.assertIn("windowcontrols > button.maximize > image { background-color: #28c840; }", css)
        self.assertNotIn("XfcePanelWindow", css)       # blok listy patri jen do GTK 3
        self.run_css("dark")                            # blok GTK 4 beze zmeny: zadny dalsi restart listy
        self.assertEqual(self.restarts(2), 2)
        self.assertEqual(self.read(css4), css)
        # CSS musi GTK 4 nacist bez chyb (jinak by pravidla tise neplatila)
        try:
            import gi
            gi.require_version("Gtk", "4.0")
            from gi.repository import Gtk
        except (ImportError, ValueError):
            self.skipTest("GTK 4 not available")
        errors = []
        prov = Gtk.CssProvider()
        prov.connect("parsing-error", lambda _p, _s, err: errors.append(err.message))
        prov.load_from_path(css4)
        self.assertEqual(errors, [])



class WmTheme(unittest.TestCase):
    """Ramecky oken xfwm4 podle meritka oken: 2x -> WhiteSur-*-xhdpi (falesny xfconf-query, falesna temata)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-appearance-wm-")
        self.cfg = os.path.join(self.tmp, "config")
        self.bin = os.path.join(self.tmp, "bin")
        self.themes = os.path.join(self.tmp, "themes")
        self.db = os.path.join(self.tmp, "xfconf")
        os.makedirs(os.path.join(self.cfg, "luxos"))
        os.makedirs(self.bin)
        for t in ("WhiteSur-Light", "WhiteSur-Dark", "WhiteSur-Light-xhdpi", "WhiteSur-Dark-xhdpi"):
            os.makedirs(os.path.join(self.themes, t, "xfwm4"))
            open(os.path.join(self.themes, t, "xfwm4", "themerc"), "w").close()
        # xfconf-query: -c KANAL -p VLASTNOST [-n -t TYP -s HODNOTA]; hodnoty v souboru "kanal vlastnost hodnota"
        with open(os.path.join(self.bin, "xfconf-query"), "w") as f:
            f.write('#!/bin/bash\ndb="%s"; touch "$db"\n'
                    'while (($#)); do case $1 in -c) c=$2; shift;; -p) p=$2; shift;; -s) v=$2; shift;; esac; shift; done\n'
                    'if [[ -n ${v+x} ]]; then grep -v "^$c $p " "$db" >"$db.n"; echo "$c $p $v" >>"$db.n"; mv "$db.n" "$db"\n'
                    'else l=$(grep "^$c $p " "$db") || exit 1; echo "${l#"$c $p "}"; fi\n' % self.db)
        os.chmod(os.path.join(self.bin, "xfconf-query"), 0o755)
        for name in ("pgrep", "gsettings", "xrandr", "xfce4-panel"):
            with open(os.path.join(self.bin, name), "w") as f:
                f.write("#!/bin/sh\nexit 1\n")
            os.chmod(os.path.join(self.bin, name), 0o755)
        with open(os.path.join(self.cfg, "luxos", "appearance.conf"), "w") as f:
            f.write("LOGIN_WALLPAPER=0\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, True)

    def set(self, channel, prop, value):
        try:
            with open(self.db) as f:
                lines = [ln for ln in f if not ln.startswith(f"{channel} {prop} ")]
        except OSError:
            lines = []
        with open(self.db, "w") as f:
            f.writelines(lines + [f"{channel} {prop} {value}\n"])

    def get(self, channel, prop):
        with open(self.db) as f:
            for line in f:
                if line.startswith(f"{channel} {prop} "):
                    return line.rstrip("\n").split(" ", 2)[2]
        return None

    def run_app(self, *args):
        env = dict(os.environ, XDG_CONFIG_HOME=self.cfg, PATH=self.bin + ":/usr/bin:/bin", LUXOS_THEMES_DIR=self.themes,
                   XDG_DATA_HOME=os.path.join(self.tmp, "data"), XDG_DATA_DIRS=os.path.join(self.tmp, "share"))
        subprocess.run(["bash", SCRIPT, *args], env=env, check=True, capture_output=True, timeout=30)

    def test_scale_1_plain_theme(self):
        self.run_app("dark")
        self.assertEqual(self.get("xfwm4", "/general/theme"), "WhiteSur-Dark")

    def test_scale_2_xhdpi_theme(self):
        self.set("xsettings", "/Gdk/WindowScalingFactor", "2")
        self.run_app("light")
        self.assertEqual(self.get("xfwm4", "/general/theme"), "WhiteSur-Light-xhdpi")
        self.assertEqual(self.get("xsettings", "/Net/ThemeName"), "WhiteSur-Light")   # GTK tema bez -xhdpi

    def test_scaling_change_switches_and_back(self):
        self.run_app("light")
        self.set("xsettings", "/Gdk/WindowScalingFactor", "2")
        self.run_app("wm-theme")
        self.assertEqual(self.get("xfwm4", "/general/theme"), "WhiteSur-Light-xhdpi")
        self.run_app("dark")
        self.assertEqual(self.get("xfwm4", "/general/theme"), "WhiteSur-Dark-xhdpi")
        self.run_app("wm-theme")
        self.assertEqual(self.get("xfwm4", "/general/theme"), "WhiteSur-Dark-xhdpi")
        self.set("xsettings", "/Gdk/WindowScalingFactor", "1")
        self.run_app("wm-theme")
        self.assertEqual(self.get("xfwm4", "/general/theme"), "WhiteSur-Dark")

    def test_missing_variant_and_own_theme_kept(self):
        import shutil
        shutil.rmtree(os.path.join(self.themes, "WhiteSur-Light-xhdpi"))
        self.set("xsettings", "/Gdk/WindowScalingFactor", "2")
        self.run_app("light")
        self.assertEqual(self.get("xfwm4", "/general/theme"), "WhiteSur-Light")
        self.set("xfwm4", "/general/theme", "Default-xhdpi")
        self.run_app("wm-theme")
        self.assertEqual(self.get("xfwm4", "/general/theme"), "Default-xhdpi")   # vlastni volba uzivatele


class Defaults(unittest.TestCase):
    def test_gtk_settings_match_light_default(self):
        """Vychozi svetly rezim: settings.ini GTK 3 i 4 (bez xsettings) maji tytez ikony a pismo jako xsettings."""
        import configparser
        import re
        files = os.path.join(HERE, "..", "files", "xdg")
        with open(os.path.join(files, "xfce4", "xfconf", "xfce-perchannel-xml", "xsettings.xml")) as f:
            xs = f.read()
        icons = re.search(r'name="IconThemeName" type="string" value="([^"]+)"', xs).group(1)
        font = re.search(r'name="FontName" type="string" value="([^"]+)"', xs).group(1)
        self.assertEqual(icons, "WhiteSur-light")
        for ver in ("gtk-3.0", "gtk-4.0"):
            cp = configparser.ConfigParser(interpolation=None)
            cp.read(os.path.join(files, ver, "settings.ini"))
            self.assertEqual(cp["Settings"]["gtk-icon-theme-name"], icons, ver)
            self.assertEqual(cp["Settings"]["gtk-font-name"], font, ver)


if __name__ == "__main__":
    unittest.main()
