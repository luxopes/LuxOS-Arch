#!/usr/bin/env python3
"""LuxOS - testy tapety prihlasovaci obrazovky (luxos-appearance greeter-sync).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_appearance.py -v

Nic nemeni na skutecnem systemu: busctl (AccountsService), xfconf-query a xrandr jsou falesne
programy v PATH, domov a nastaveni v docasne slozce.
"""
import os
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APPEARANCE = os.path.normpath(os.path.join(HERE, "..", "files", "bin", "luxos-appearance"))
WALL = "/usr/share/backgrounds/luxos"
READABLE = "/etc/os-release"       # citelny pro vsechny (cela cesta), na kazdem systemu

FAKES = {
    # AccountsService: BackgroundFile v souboru $FAKE_BG, volani do $FAKE_LOG
    "busctl": r'''#!/bin/sh
printf "%s\n" "busctl $*" >>"$FAKE_LOG"
case "$*" in
  *FindUserById*) echo 'o "/org/freedesktop/Accounts/User1000"';;
  *get-property*) printf 's "%s"\n' "$(cat "$FAKE_BG" 2>/dev/null)";;
  *set-property*) for a; do last=$a; done; printf "%s" "$last" >"$FAKE_BG";;
esac
''',
    "xfconf-query": r'''#!/bin/sh
case "$*" in
  "-c xfce4-desktop -l -v") cat "$FAKE_DESKTOP" 2>/dev/null;;
  *) printf "%s\n" "xfconf-query $*" >>"$FAKE_LOG";;
esac
''',
    "xrandr": r'''#!/bin/sh
cat "$FAKE_MONITORS"
''',
}


class GreeterSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-appearance-")
        fake = os.path.join(self.tmp, "fake")
        os.makedirs(fake)
        for name, body in FAKES.items():
            p = os.path.join(fake, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        self.cfg = os.path.join(self.tmp, "config")
        self.state = os.path.join(self.cfg, "luxos")
        os.makedirs(self.state)
        self.bg = os.path.join(self.tmp, "bg")
        self.log = os.path.join(self.tmp, "calls.log")
        self.desktop = os.path.join(self.tmp, "desktop")
        self.monitors = os.path.join(self.tmp, "monitors")
        self.env = {"PATH": fake + ":/usr/bin:/bin", "HOME": self.tmp, "XDG_CONFIG_HOME": self.cfg,
                    "XDG_DATA_HOME": os.path.join(self.tmp, "data"), "USER": "test", "LANG": "C",
                    "FAKE_BG": self.bg, "FAKE_LOG": self.log, "FAKE_DESKTOP": self.desktop,
                    "FAKE_MONITORS": self.monitors}
        self.screens(["0: +*eDP-1 1920/344x1080/194+0+0  eDP-1"])

    def screens(self, lines):
        with open(self.monitors, "w") as f:
            f.write("Monitors: %d\n" % len(lines) + "".join(" " + line + "\n" for line in lines))

    def wallpapers(self, props):
        with open(self.desktop, "w") as f:
            for prop, val in props.items():
                f.write(f"/backdrop/screen0/{prop}/last-image{' ' * 6}{val}\n")
                f.write(f"/backdrop/screen0/{prop}/image-style{' ' * 5}5\n")

    def set_bg(self, value):
        with open(self.bg, "w") as f:
            f.write(value)

    def bg_value(self):
        try:
            with open(self.bg) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def sets(self):
        try:
            with open(self.log) as f:
                return [line for line in f if "set-property" in line]
        except FileNotFoundError:
            return []

    def run_sync(self, *args):
        r = subprocess.run(["bash", APPEARANCE, *(args or ("greeter-sync",))], env=self.env,
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_empty_background_gets_desktop_wallpaper(self):
        self.wallpapers({"monitoreDP-1/workspace0": READABLE, "monitoreDP-1/workspace1": "/x/other.jpg"})
        self.run_sync()
        self.assertEqual(self.bg_value(), READABLE)
        with open(os.path.join(self.state, "greeter-wallpaper")) as f:
            self.assertEqual(f.read().strip(), READABLE)

    def test_primary_monitor_wins(self):
        self.screens(["0: +HDMI-1 1920/510x1080/290+0+0  HDMI-1", "1: +*eDP-1 1920/344x1080/194+1920+0  eDP-1"])
        self.wallpapers({"monitorHDMI-1/workspace0": "/usr/share/backgrounds/luxos/luxos-dark.jpg",
                         "monitoreDP-1/workspace0": READABLE})
        self.run_sync()
        self.assertEqual(self.bg_value(), READABLE)

    def test_unreadable_wallpaper_falls_back_to_mode_default(self):
        private = os.path.join(self.tmp, "private")
        os.makedirs(private)
        os.chmod(private, 0o700)
        pic = os.path.join(private, "photo.jpg")
        with open(pic, "w") as f:
            f.write("x")
        os.chmod(pic, 0o644)
        self.wallpapers({"monitoreDP-1/workspace0": pic})
        with open(os.path.join(self.state, "appearance"), "w") as f:
            f.write("dark\n")
        self.run_sync()
        self.assertEqual(self.bg_value(), WALL + "/luxos-dark.jpg")

    def test_no_wallpaper_uses_mode_default(self):
        self.wallpapers({})
        self.run_sync()
        self.assertEqual(self.bg_value(), WALL + "/luxos-light.jpg")   # vychozi rezim je svetly

    def test_old_luxos_default_is_replaced(self):
        # drivejsi stav: greeter mel vychozi tmavou tapetu, plocha je svetla
        self.set_bg(WALL + "/luxos-dark.jpg")
        self.wallpapers({"monitoreDP-1/workspace0": READABLE})
        self.run_sync()
        self.assertEqual(self.bg_value(), READABLE)

    def test_explicit_background_is_kept(self):
        self.set_bg("/usr/share/backgrounds/my-login.png")
        self.wallpapers({"monitoreDP-1/workspace0": READABLE})
        self.run_sync()
        self.assertEqual(self.bg_value(), "/usr/share/backgrounds/my-login.png")
        self.assertEqual(self.sets(), [])

    def test_follows_later_changes(self):
        self.wallpapers({"monitoreDP-1/workspace0": WALL + "/luxos-light.jpg"})
        self.run_sync()
        self.assertEqual(self.bg_value(), WALL + "/luxos-light.jpg")
        self.wallpapers({"monitoreDP-1/workspace0": READABLE})
        self.run_sync()
        self.assertEqual(self.bg_value(), READABLE)
        # znovu stejna -> zadny dalsi zapis
        n = len(self.sets())
        self.run_sync()
        self.assertEqual(len(self.sets()), n)

    def test_opt_out(self):
        with open(os.path.join(self.state, "appearance.conf"), "w") as f:
            f.write("LOGIN_WALLPAPER=0\n")
        self.wallpapers({"monitoreDP-1/workspace0": READABLE})
        self.run_sync()
        self.assertEqual(self.bg_value(), "")
        self.assertFalse(os.path.exists(self.log) and "busctl" in open(self.log).read())

    def test_without_accountsservice_nothing_fails(self):
        with open(os.path.join(self.tmp, "fake", "busctl"), "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        self.wallpapers({"monitoreDP-1/workspace0": READABLE})
        self.run_sync()
        self.assertFalse(os.path.exists(os.path.join(self.state, "greeter-wallpaper")))

    def test_world_readable_needs_whole_path(self):
        # soubor 644 ve slozce 711 (lze projit) je citelny, ve slozce 700 ne
        d = os.path.join(self.tmp, "pub")
        os.makedirs(d)
        pic = os.path.join(d, "a.jpg")
        with open(pic, "w") as f:
            f.write("x")
        os.chmod(pic, 0o600)
        script = f'source <(sed -n "/^world_readable()/,/^}}/p" "{APPEARANCE}"); world_readable "$1" && echo yes || echo no'
        r = subprocess.run(["bash", "-c", script, "x", pic], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "no")
        r = subprocess.run(["bash", "-c", script, "x", READABLE], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "yes")
        r = subprocess.run(["bash", "-c", script, "x", "/nonexistent/a.jpg"], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "no")
        self.assertTrue(stat.S_IMODE(os.stat(pic).st_mode) == 0o600)


if __name__ == "__main__":
    unittest.main()
