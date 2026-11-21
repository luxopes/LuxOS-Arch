#!/usr/bin/env python3
"""LuxOS - Plocha a Dock (files/lsl/luxos-settings.lsl) v relaci X11 (vlastni Xvfb) i na Waylandu (luxwm headless).

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -p MemorySwapMax=0 -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_settings.py -v

luxos-appearance, xfconf-query, luxos-splash, pkexec a luxos-widgets jsou falesne programy, ktere zapisuji,
s cim byly spusteny; Dock na X11 jde do GSettings Planku (GSETTINGS_BACKEND=keyfile v docasnem domove),
na Waylandu do ~/.config/luxos/dock.conf. Okno se ovlada pres LUXOS_UI_TEST (lsl_app_harness).
Wayland cast potrebuje luxwm (packages/luxwm/tests/build-host.sh) a sysroot harnessu wl-test.
"""
import configparser
import os
import tempfile
import time
import unittest
from pathlib import Path

import lsl_app_harness as h

FAKES = ["luxos-appearance", "xfconf-query", "luxos-splash", "pkexec", "luxos-widgets", "luxos-display-settings"]


def setUpModule():
    if not h.lslc_ok():
        raise unittest.SkipTest("lslc 0.11 is not installed")
    h.build("luxos-settings")


def make_env(lang="C.UTF-8", **extra):
    tmp = Path(tempfile.mkdtemp(prefix="settings-", dir=h.private_dir()))
    env = h.base_env(tmp, lang)
    env["PATH"] = str(h.fake_bin(tmp / "bin", FAKES)) + ":" + os.environ["PATH"]
    env.update(FAKE_OUT_luxos_appearance="light", FAKE_OUT_luxos_splash="blue",
               FAKE_OUT_xfconf_query="/backdrop/screen0/monitor0/workspace0/last-image")
    env.update(extra)
    return tmp, env


def calls(tmp):
    log = tmp / "fake.log"
    return log.read_text().splitlines() if log.exists() else []


def find(dump, kind, text):
    """Radek prvku: 'GtkSwitch' za popiskem radku text, jinak prvni prvek kind s textem."""
    for i, line in enumerate(dump):
        if line == f"GtkLabel\t{text}":
            for nxt in dump[i + 1:i + 4]:
                if nxt.startswith(kind + "\t"):
                    return nxt.split("\t")[1:]
    return None


def keyfile(tmp):
    kf = configparser.ConfigParser()
    kf.read(tmp / "config/glib-2.0/settings/keyfile")
    return kf["net/launchpad/plank/docks/dock1"] if kf.has_section("net/launchpad/plank/docks/dock1") else {}


def wait_for(cond, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.1)
    return False


@unittest.skipUnless(h.HAVE_X11, "Xvfb, xdotool or dbus-run-session missing")
class X11(unittest.TestCase):
    def run_app(self, script, tmp=None, env=None, size=(1366, 768)):
        if env is None:
            tmp, env = make_env()
        app = h.X11App([str(h.build("luxos-settings"))], env, script, size=size, tmp=tmp)
        self.addCleanup(app.close)
        return app

    def test_groups_and_xfce_links(self):
        tmp, env = make_env()
        app = self.run_app(["dump", "quit"], tmp, env)
        d = app.wait_dump()
        for title in ("Appearance", "Boot Screen", "Wallpaper", "Widgets", "Dock", "Menu Bar"):
            self.assertIn("GtkLabel\t" + title, d)
        for link in ("Displays…", "Advanced Desktop Settings…", "Menu Bar Items…"):
            self.assertIn("GtkButton\t" + link, d)
        self.assertEqual(find(d, "GtkComboBoxText", "Position on screen"), ["bottom"])
        self.assertIn("GtkButton\tBlue [current]", d)
        # stav vzhledu a spousteci obrazovky z luxos-appearance / luxos-splash, tapeta z xfconf
        self.assertIn("luxos-appearance mode", calls(tmp))
        self.assertIn("luxos-splash get", calls(tmp))
        self.assertIn("xfconf-query -c xfce4-desktop -l", calls(tmp))

    def test_appearance_and_bar(self):
        tmp, env = make_env()
        app = self.run_app(["click Dark", "switch Clock in the middle on", "switch Rounded corners on",
                            "switch Darken bright wallpaper under the menu bar and widgets off",
                            "switch Notify about summer and winter time off", "slider Menu bar opacity 40",
                            "wait 600", "dump", "quit"], tmp, env)
        d = app.wait_dump()
        app.wait_exit()
        log = calls(tmp)
        for want in ("luxos-appearance dark", "luxos-appearance bar-clock center", "luxos-appearance bar-style rounded",
                     "luxos-appearance desktop-scrim off", "luxos-appearance bar-opacity 40"):
            self.assertIn(want, log)
        self.assertIn("GtkButton\tDark [current]", d)
        self.assertNotIn("GtkButton\tLight [current]", d)
        self.assertIn("TIME_CHANGE=0", (tmp / "config/luxos/notifications.conf").read_text().splitlines())

    def test_prefs_shown(self):
        tmp, env = make_env()
        (tmp / "config/luxos").mkdir(parents=True)
        (tmp / "config/luxos/appearance.conf").write_text("BAR_OPACITY=30\nBAR_CLOCK=center\nDESKTOP_SCRIM=0\n"
                                                          "DOCK_OPACITY=55\nBAR_STYLE=rounded\n")
        (tmp / "config/luxos/notifications.conf").write_text("TIME_CHANGE=0\n")
        d = self.run_app(["dump", "quit"], tmp, env).wait_dump()
        self.assertEqual(find(d, "GtkScale", "Menu bar opacity"), ["30"])
        self.assertEqual(find(d, "GtkScale", "Dock opacity"), ["55"])
        self.assertEqual(find(d, "GtkSwitch", "Clock in the middle"), ["on"])
        self.assertEqual(find(d, "GtkSwitch", "Rounded corners"), ["on"])
        self.assertEqual(find(d, "GtkSwitch", "Notify about summer and winter time"), ["off"])
        self.assertEqual(find(d, "GtkSwitch", "Darken bright wallpaper under the menu bar and widgets"), ["off"])

    def test_dock_gsettings(self):
        tmp, env = make_env()
        app = self.run_app(["switch Automatically hide and show the Dock on", "slider Size 60",
                            "switch Magnification on", "slider Magnification size 180", "combo Position on screen left",
                            "wait 700", "dump", "quit"], tmp, env)
        d = app.wait_dump()
        app.wait_exit()
        kf = keyfile(tmp)
        self.assertEqual(kf.get("hide-mode"), "'auto'")
        self.assertEqual(kf.get("icon-size"), "60")
        self.assertEqual(kf.get("zoom-enabled"), "true")
        self.assertEqual(kf.get("zoom-percent"), "180")
        self.assertEqual(kf.get("position"), "'left'")
        self.assertTrue((tmp / "config/luxos/dock-autohide").exists())
        self.assertEqual(find(d, "GtkScale", "Magnification size"), ["180"])       # uz ne (insensitive)

    def test_widgets_follow_file(self):
        tmp, env = make_env()
        app = self.run_app(["dump", "wait 1500", "dump", "switch Show widgets on the desktop off", "wait 300", "quit"],
                           tmp, env)
        self.assertEqual(find(app.wait_dump(1), "GtkSwitch", "Show widgets on the desktop"), ["off"])
        (tmp / "config/luxos/widgets.conf").write_text("ENABLED=1\n")          # galerie widgetu je zapnula
        self.assertEqual(find(app.wait_dump(2), "GtkSwitch", "Show widgets on the desktop"), ["on"])
        app.wait_exit()
        # zmena souboru zvenku nespusti luxos-widgets, vypnuti uzivatelem ano
        self.assertEqual([c for c in calls(tmp) if c.startswith("luxos-widgets")], ["luxos-widgets off"])

    def test_boot_screen(self):
        for rc, text, current in (("0", "The new boot screen will be shown at the next start.", "Purple"),
                                  ("126", "Change cancelled.", "Blue")):
            with self.subTest(rc=rc):
                tmp, env = make_env(FAKE_RC_pkexec=rc)
                app = self.run_app(["click Purple", "wait 800", "dump", "quit"], tmp, env)
                d = app.wait_dump()
                self.assertIn("pkexec /usr/bin/luxos-splash set purple", calls(tmp))
                self.assertIn("GtkLabel\t" + text, d)
                self.assertIn(f"GtkButton\t{current} [current]", d)

    def test_boot_screen_error_reason(self):
        tmp, env = make_env(FAKE_RC_pkexec="1", FAKE_OUT_pkexec="mkinitcpio failed\nno space left")
        d = self.run_app(["click Green", "wait 800", "dump", "quit"], tmp, env).wait_dump()
        self.assertIn("GtkLabel\tCould not change the boot screen. (no space left)", d)

    def test_wallpaper_thumbs_cached(self):
        tmp, env = make_env()
        self.run_app(["wait 2500", "quit"], tmp, env).wait_exit(30)
        thumbs = list((tmp / "cache/luxos/wallpaper-thumbs").glob("*.png"))
        walls = [p for p in Path("/usr/share/backgrounds/luxos").glob("*") if p.suffix in (".jpg", ".png", ".webp")]
        if walls:
            self.assertGreater(len(thumbs), 0)

    def test_window_fits_small_screens(self):
        for size in ((1366, 768), (1280, 800)):
            with self.subTest(size=size):
                app = self.run_app(["wait 600000"], size=size)
                win = app.window("Desktop & Dock")
                self.assertLessEqual(win["height"], size[1] - 16, win)
                self.assertLessEqual(win["width"], size[0], win)
                minimum = app.hints(win["id"])
                self.assertIsNotNone(minimum)
                self.assertGreaterEqual(minimum[0], 340)
                self.assertGreaterEqual(minimum[1], 300)

    def test_czech(self):
        tmp, env = make_env("cs_CZ.UTF-8")
        d = self.run_app(["dump", "quit"], tmp, env).wait_dump()
        for title in ("Vzhled", "Tapeta", "Horní lišta"):
            self.assertIn("GtkLabel\t" + title, d)


@unittest.skipUnless(h.HAVE_WAYLAND, "luxwm (LUXWM_BUILD) or wl-test sysroot missing")
class Wayland(unittest.TestCase):
    def run_app(self, script, tmp, env):
        app = h.WaylandApp([str(h.build("luxos-settings"))], env, script, tmp=tmp)
        self.addCleanup(app.close)
        return app

    def test_wayland_layout(self):
        tmp, env = make_env()
        (tmp / "config/luxos").mkdir(parents=True)
        wall = sorted(Path("/usr/share/backgrounds/luxos").glob("*.jpg"))
        if wall:
            (tmp / "config/luxos/appearance.conf").write_text(f"WALLPAPER='{wall[0]}'\n")
        d = self.run_app(["dump", "quit"], tmp, env).wait_dump()
        self.assertIn("GtkButton\tDisplays…", d)
        self.assertNotIn("GtkButton\tAdvanced Desktop Settings…", d)
        self.assertNotIn("GtkButton\tMenu Bar Items…", d)
        self.assertIsNone(find(d, "GtkComboBoxText", "Position on screen"))     # luxos-dock je jen dole
        self.assertFalse([c for c in calls(tmp) if c.startswith("xfconf-query")], calls(tmp))
        if wall:
            self.assertEqual(sum(1 for line in d if line.startswith("GtkButton") and line.endswith("[current]")), 3)

    def test_dock_conf(self):
        tmp, env = make_env()
        (tmp / "config/luxos").mkdir(parents=True)
        (tmp / "config/luxos/dock.conf").write_text('ITEMS="firefox.desktop trash"\nICON_SIZE=40\nZOOM=100\nHIDE=dodge\n')
        app = self.run_app(["dump", "switch Automatically hide and show the Dock on", "slider Size 64",
                            "switch Magnification on", "wait 700", "slider Magnification size 170", "wait 700", "quit"],
                           tmp, env)
        d = app.wait_dump()
        app.wait_exit()
        self.assertEqual(find(d, "GtkScale", "Size"), ["40"])
        self.assertEqual(find(d, "GtkSwitch", "Magnification"), ["off"])
        conf = (tmp / "config/luxos/dock.conf").read_text().splitlines()
        self.assertIn('ITEMS="firefox.desktop trash"', conf)
        for want in ("ICON_SIZE=64", "ZOOM=170", "HIDE=autohide"):
            self.assertIn(want, conf)
        self.assertFalse((tmp / "config/glib-2.0/settings/keyfile").exists())


if __name__ == "__main__":
    unittest.main()
