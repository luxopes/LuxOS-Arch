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
        self.css = os.path.join(self.cfg, "gtk-3.0", "gtk.css")

    def run_css(self, mode):
        with open(os.path.join(self.cfg, "luxos", "appearance"), "w") as f:
            f.write(mode + "\n")
        env = dict(os.environ, XDG_CONFIG_HOME=self.cfg, PATH=self.bin + ":" + os.environ["PATH"])
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
        self.assertIn(".xfce4-panel, .xfce4-panel label", css)
        self.assertIn(".xfce4-panel grid > button:checked { background: alpha(#3d7bff, 0.22); }", css)
        self.assertIn("alpha(#1d1d1f, 0.55)", css)
        self.assertIn(".xfce4-panel wnck-pager { background: transparent; }", css)

    def test_dark_block_without_text_color(self):
        self.run_css("dark")
        css = self.read(self.css)
        self.assertNotIn(".xfce4-panel, .xfce4-panel label", css)
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


if __name__ == "__main__":
    unittest.main()
