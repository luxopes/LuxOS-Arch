#!/usr/bin/env python3
"""LuxOS - horni lista: luxos-appearance bar-style / bar-clock / bar-text a rozlozeni pro plugin luxos-bar.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_bar.py -v

Nic nemeni na skutecnem systemu: xfconf-query je napodoba se stavem v JSON (kanal xfce4-panel),
pgrep a xfce4-panel jen zapisuji volani; nastaveni, gtk.css a datove slozky v docasne slozce.
Plugin samotny (hodiny uprostred, neprusvitna lista pod okny) se zkousi pod Xvfb s xfwm4 a panelem,
viz docs v hlavicce files/src/luxos-bar.c.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "files", "bin", "luxos-appearance")
PLUGIN_DESKTOP = os.path.join(HERE, "..", "files", "panel-plugins", "luxos-bar.desktop")

# xfconf-query s pameti: -c CH -p P [-n -t T -s V ...] [--force-array], -l -p PREFIX
FAKE_XFCONF = r'''#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_XFCONF"]
with open(path) as f:
    db = json.load(f)
a = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write("xfconf-query " + " ".join(a) + "\n")
prop = a[a.index("-p") + 1] if "-p" in a else ""
if "-l" in a:
    for k in sorted(db):
        if k.startswith(prop):
            print(k)
    sys.exit(0)
if "-s" in a:
    vals = [a[i + 1] for i, x in enumerate(a) if x == "-s"]
    db[prop] = vals if (len(vals) > 1 or "--force-array" in a) else vals[0]
    with open(path, "w") as f:
        json.dump(db, f)
    sys.exit(0)
if prop not in db:
    sys.stderr.write("Property \"%s\" does not exist on channel\n" % prop)
    sys.exit(1)
v = db[prop]
if isinstance(v, list):
    print("Value is an array with %d items:\n" % len(v))
    for x in v:
        print(x)
else:
    print(v)
'''

# vychozi lista LuxOS (zkracena): logo, nazev aplikace, rozpinaci oddelovac, ..., hodiny, oddelovac
DEFAULT_PANEL = {
    "/panels/panel-1/plugin-ids": ["1", "2", "3", "15", "7", "8", "9"],
    "/panels/panel-1/size": "28",
    "/plugins/plugin-1": "whiskermenu",
    "/plugins/plugin-2": "genmon",
    "/plugins/plugin-3": "separator",
    "/plugins/plugin-3/expand": "true",
    "/plugins/plugin-3/style": "0",
    "/plugins/plugin-15": "cpugraph",
    "/plugins/plugin-7": "notification-plugin",
    "/plugins/plugin-8": "genmon",
    "/plugins/plugin-8/command": "luxos-clock",
    "/plugins/plugin-9": "separator",
    "/plugins/plugin-9/style": "0",
}


class Bar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-bar-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cfg = os.path.join(self.tmp, "config")
        self.bin = os.path.join(self.tmp, "bin")
        self.log = os.path.join(self.tmp, "calls")
        self.db = os.path.join(self.tmp, "xfconf.json")
        os.makedirs(os.path.join(self.cfg, "luxos"))
        os.makedirs(self.bin)
        for name in ("pgrep", "xfce4-panel"):
            self.script(name, '#!/bin/sh\necho "%s $*" >> "$FAKE_LOG"\nexit 0\n' % name)
        self.script("xfconf-query", FAKE_XFCONF)
        self.share = os.path.join(self.tmp, "share")
        self.set_panel(DEFAULT_PANEL)
        self.install_plugin()
        with open(os.path.join(self.cfg, "luxos", "appearance"), "w") as f:
            f.write("light\n")
        self.css = os.path.join(self.cfg, "gtk-3.0", "gtk.css")

    def script(self, name, body):
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write(body)
        os.chmod(p, 0o755)

    def install_plugin(self):
        d = os.path.join(self.share, "xfce4", "panel", "plugins")
        os.makedirs(d, exist_ok=True)
        shutil.copy(PLUGIN_DESKTOP, d)

    def set_panel(self, props):
        with open(self.db, "w") as f:
            json.dump(dict(props), f)

    def panel(self):
        with open(self.db) as f:
            return json.load(f)

    def read(self, path):
        try:
            with open(path) as f:
                return f.read()
        except OSError:
            return ""

    def run_appearance(self, *args, check=True):
        env = dict(os.environ, XDG_CONFIG_HOME=self.cfg, HOME=self.tmp, PATH=self.bin + ":" + os.environ["PATH"],
                   XDG_DATA_HOME=os.path.join(self.tmp, "data"), XDG_DATA_DIRS=self.share,
                   FAKE_XFCONF=self.db, FAKE_LOG=self.log, USER="test", LANG="C")
        return subprocess.run(["bash", SCRIPT, *args], env=env, check=check, capture_output=True, text=True)

    def restarts(self):
        # restart panelu bezi na pozadi (&)
        time.sleep(0.3)
        return self.read(self.log).count("xfce4-panel -r")

    def ids(self):
        return self.panel()["/panels/panel-1/plugin-ids"]

    def prefs(self):
        return self.read(os.path.join(self.cfg, "luxos", "appearance.conf"))

    # ---- rozlozeni listy ----------------------------------------------------------------

    def test_panel_css_replaces_expanding_separator_with_bar(self):
        self.run_appearance("panel-css")
        ids = self.ids()
        self.assertEqual(len(ids), 7)
        bar = ids[2]
        self.assertNotEqual(bar, "3")
        self.assertEqual(self.panel()["/plugins/plugin-" + bar], "luxos-bar")
        self.assertGreater(int(bar), 15, "nove id nesmi kolidovat s existujicimi pluginy")
        self.assertEqual(ids[:2] + ids[3:], ["1", "2", "15", "7", "8", "9"])
        self.assertGreaterEqual(self.restarts(), 1)

    def test_layout_is_idempotent(self):
        self.run_appearance("panel-css")
        first = self.panel()
        open(self.log, "w").close()
        self.run_appearance("panel-css")
        self.assertEqual(self.panel(), first)
        self.assertEqual(self.restarts(), 0, "beze zmeny se panel nerestartuje")

    def test_without_plugin_layout_untouched(self):
        shutil.rmtree(self.share)
        self.run_appearance("panel-css")
        self.assertEqual(self.panel(), DEFAULT_PANEL)

    def test_custom_bar_without_expanding_separator_untouched(self):
        props = dict(DEFAULT_PANEL)
        props["/plugins/plugin-3/expand"] = "false"
        self.set_panel(props)
        self.run_appearance("panel-css")
        self.assertEqual(self.ids(), DEFAULT_PANEL["/panels/panel-1/plugin-ids"])

    def test_rounded_style(self):
        self.run_appearance("bar-style", "rounded")
        p = self.panel()
        self.assertEqual(p["/panels/panel-1/size"], "28", "vyska listy se nemeni")
        ids = p["/panels/panel-1/plugin-ids"]
        self.assertEqual(len(ids), 8)
        self.assertEqual(p["/plugins/plugin-" + ids[0]], "separator", "pruhledny oddelovac pred logem (levy roh)")
        self.assertEqual(ids[1], "1")
        self.assertIn("luxos-bar", [p["/plugins/plugin-" + i] for i in ids])
        css = self.read(self.css)
        self.assertIn("#XfcePanelWindow.xfce4-panel.background { border-radius: 0 0 10px 10px; }", css)
        self.assertIn("#XfcePanelWindowWrapper.xfce4-panel.background, #XfcePanelWindow.xfce4-panel.background"
                      ".luxos-covered { border-radius: 0; }", css, "externi pluginy a lista pod oknem bez zaobleni")
        self.assertNotIn("border-width", css, "nahore lista licuje s obrazovkou")
        self.assertIn("BAR_STYLE=rounded", self.prefs())
        # znovu: zadny dalsi oddelovac
        self.run_appearance("bar-style", "rounded")
        self.assertEqual(len(self.ids()), 8)

    def test_back_to_classic(self):
        self.run_appearance("bar-style", "rounded")
        self.run_appearance("bar-style", "classic")
        self.assertEqual(self.panel()["/panels/panel-1/size"], "28")
        self.assertNotIn("0 0 10px 10px", self.read(self.css))
        self.assertIn("BAR_STYLE=classic", self.prefs())

    def test_clock_center_needs_no_restart_when_bar_present(self):
        self.run_appearance("panel-css")
        open(self.log, "w").close()
        self.run_appearance("bar-clock", "center")
        self.assertIn("BAR_CLOCK=center", self.prefs())
        self.assertEqual(self.run_appearance("bar-clock", "center").returncode, 0)
        self.assertEqual(self.restarts(), 0, "plugin si zmenu nacte sam")
        self.run_appearance("bar-clock", "right")
        self.assertIn("BAR_CLOCK=right", self.prefs())
        self.assertNotIn("BAR_CLOCK=center", self.prefs())

    def test_white_text(self):
        self.run_appearance("bar-text", "white")
        css = self.read(self.css)
        self.assertIn("#XfcePanelWindow, #XfcePanelWindowWrapper, #XfcePanelWindow label, #XfcePanelWindowWrapper label,"
                      " #XfcePanelWindow button, #XfcePanelWindowWrapper button, #XfcePanelWindow image,"
                      " #XfcePanelWindowWrapper image { color: #ffffff; }", css)
        self.assertIn("#XfcePanelWindow label, #XfcePanelWindowWrapper label { text-shadow:", css)
        # vyskakovaci okna pluginu maji vlastni tridu .xfce4-panel - selektory jen podle okna listy
        self.assertNotIn(".xfce4-panel label", css)
        self.run_appearance("bar-text", "auto")
        self.assertEqual(self.run_appearance("bar-text", "auto").returncode, 0, "beze zmeny take uspech")
        css = self.read(self.css)
        self.assertIn("color: #1d1d1f; }", css)
        self.assertNotIn("text-shadow: 0", css)

    def test_plugin_menus_keep_theme_colors(self):
        """Nabidka zvuku/Wi-Fi je ve stromu CSS pod tlacitkem listy: bily text listy do ni nesmi."""
        self.run_appearance("bar-text", "white")
        css = self.read(self.css)
        reset = [l for l in css.splitlines() if "color: inherit" in l]
        self.assertEqual(len(reset), 1, css)
        for sel in ("#XfcePanelWindow window label", "#XfcePanelWindow window image", "#XfcePanelWindow popover label",
                    "#XfcePanelWindowWrapper window label"):
            self.assertIn(sel, reset[0])
        self.assertIn("text-shadow: none; -gtk-icon-shadow: none;", reset[0])
        # pravidlo musi byt az za pravidly listy (stejna nebo vyssi specificita, pozdejsi vyhrava)
        self.assertGreater(css.index("color: inherit"), css.index("{ color: #ffffff; }"))

    def test_dark_mode_white_text_has_no_extra_shadow(self):
        with open(os.path.join(self.cfg, "luxos", "appearance"), "w") as f:
            f.write("dark\n")
        self.run_appearance("bar-text", "white")
        self.assertNotIn("text-shadow: 0", self.read(self.css))

    def test_other_prefs_kept(self):
        with open(os.path.join(self.cfg, "luxos", "appearance.conf"), "w") as f:
            f.write("BAR_OPACITY=40\nAPPEARANCE_AUTO=1\n")
        self.run_appearance("bar-clock", "center")
        prefs = self.prefs()
        self.assertIn("BAR_OPACITY=40", prefs)
        self.assertIn("APPEARANCE_AUTO=1", prefs)

    def test_invalid_values(self):
        for args in (("bar-style", "floating"), ("bar-clock", "left"), ("bar-text", "black"), ("bar-style",)):
            r = self.run_appearance(*args, check=False)
            self.assertEqual(r.returncode, 2, args)
        self.assertEqual(self.prefs(), "")
        self.assertEqual(self.panel(), DEFAULT_PANEL)


if __name__ == "__main__":
    unittest.main()
