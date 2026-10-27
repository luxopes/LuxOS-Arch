#!/usr/bin/env python3
"""LuxOS - testy vychoziho nastaveni novych uzivatelu (luxos-new-user-defaults, /etc/luxos/new-users.conf).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_new_user_defaults.py -v

Nic nemeni na skutecnem systemu ani v relaci: luxos-appearance, gsettings, xdg-mime a xfconf-query jsou
falesne programy v PATH (jen zapisi argumenty), domov je docasna slozka.
"""
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.normpath(os.path.join(HERE, "..", "files", "session", "luxos-new-user-defaults"))
FAKE = '#!/bin/sh\nprintf "%s\\n" "$(basename "$0") $*" >>"$FAKE_LOG"\n'


class NewUserDefaultsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="luxos-new-user-")
        t = self.tmp.name
        self.home, self.bin, self.log = f"{t}/home", f"{t}/bin", f"{t}/calls.log"
        self.data = f"{t}/share"
        os.makedirs(self.bin)
        os.makedirs(f"{self.data}/applications")
        for app in ("firefox.desktop", "thunar.desktop", "luxos-text.desktop"):
            open(f"{self.data}/applications/{app}", "w").close()
        launchers = f"{self.home}/.config/plank/dock1/launchers"
        os.makedirs(launchers)
        open(f"{launchers}/luxai.dockitem", "w").close()          # z /etc/skel
        for name in ("luxos-appearance", "gsettings", "xdg-mime", "xfconf-query"):
            with open(f"{self.bin}/{name}", "w") as f:
                f.write(FAKE)
            os.chmod(f"{self.bin}/{name}", 0o755)
        self.wall = f"{t}/wall.jpg"
        open(self.wall, "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def run_helper(self, conf):
        path = f"{self.tmp.name}/new-users.conf"
        with open(path, "w") as f:
            f.write(conf)
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": self.home, "FAKE_LOG": self.log,
               "XDG_DATA_DIRS": self.data, "XDG_DATA_HOME": f"{self.tmp.name}/none"}
        r = subprocess.run(["bash", HELPER, path], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def test_all_defaults(self):
        calls = self.run_helper(f"# LuxOS\nTHEME=auto\nWALLPAPER={self.wall}\n"
                                "DOCK=firefox.desktop thunar.desktop nonexistent.desktop trash\n"
                                "BROWSER=firefox.desktop\nTEXT_EDITOR=luxos-text.desktop\nLOCK_AFTER=5\n"
                                "SCREEN_OFF=0\n")
        self.assertEqual(calls[0], "luxos-appearance auto")
        self.assertEqual(calls[1], f"luxos-appearance wallpaper {self.wall}")
        self.assertIn("gsettings set net.launchpad.plank.dock.settings:/net/launchpad/plank/docks/dock1/ dock-items "
                      "['firefox.dockitem', 'thunar.dockitem', 'trash.dockitem']", calls)
        launchers = f"{self.home}/.config/plank/dock1/launchers"
        self.assertEqual(sorted(os.listdir(launchers)), ["firefox.dockitem", "thunar.dockitem", "trash.dockitem"])
        with open(f"{launchers}/firefox.dockitem") as f:
            self.assertIn(f"Launcher=file://{self.data}/applications/firefox.desktop", f.read())
        self.assertIn("xdg-mime default firefox.desktop x-scheme-handler/http x-scheme-handler/https text/html", calls)
        self.assertIn("xdg-mime default luxos-text.desktop text/plain", calls)
        self.assertIn("xfconf-query -c xfce4-screensaver -p /saver/idle-activation/delay -n -t int -s 5", calls)
        self.assertIn("xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/dpms-on-ac-off -n -t uint -s 0",
                      calls)

    def test_nothing_and_no_injection(self):
        self.assertEqual(self.run_helper("THEME=pink\nDOCK=$(touch /tmp/x)\nBROWSER=`id`\nLOCK_AFTER=abc\n"), [])
        launchers = f"{self.home}/.config/plank/dock1/launchers"
        self.assertEqual(os.listdir(launchers), ["luxai.dockitem"])     # Dock ze skel zustava


if __name__ == "__main__":
    unittest.main()
