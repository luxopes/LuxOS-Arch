#!/usr/bin/env python3
"""LuxOS - testy Launchpadu (luxos-launchpad + rofi z [luxos] s volbou -hover-no-scroll).

  env -u DISPLAY xvfb-run -a -s "-screen 0 1280x800x24" python3 -m unittest packages/luxos-desktop/tests/test_luxos_launchpad.py -v

Spousti skutecny skript luxos-launchpad nad 60 falesnymi aplikacemi (App00..App59, mrizka 7x4,
9 radku) a ovlada ho pres xdotool; spustena aplikace zapise sve jmeno do souboru, takze test
vidi, co by Enter nebo klik spustil. pkill, luxos-appearance a luxos-luxai-rofi jsou falesne
(skript nesmi zavrit rofi uzivatele). Rofi bez -hover-no-scroll (Arch, ne [luxos]) se preskoci;
jinou binarku lze zadat v LUXOS_ROFI (napr. sestaveni packages/rofi). Jen pod xvfb-run.
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
LAUNCHPAD = os.path.join(FILES, "bin", "luxos-launchpad")
DESKTOP = os.path.join(FILES, "applications", "luxos-launchpad.desktop")
ROFI = os.environ.get("LUXOS_ROFI") or shutil.which("rofi")
COLS, ROWS, APPS = 7, 4, 60

UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")


def rofi_has_hover_no_scroll():
    if not ROFI:
        return False
    try:
        r = subprocess.run([ROFI, "-help"], capture_output=True, text=True, timeout=10,
                           env=dict(os.environ, HOME=tempfile.gettempdir()))
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "hover-no-scroll" in r.stdout


def xdo(*args):
    return subprocess.run(["xdotool", *map(str, args)], capture_output=True, text=True, timeout=10).stdout


class TestDesktopEntry(unittest.TestCase):
    def test_launchpad_hidden_in_launchpad_only(self):
        """Launchpad v mrizce sam sebe neukazuje (XDG_CURRENT_DESKTOP ...:X-LuxOS-Launchpad), jinde ano."""
        with open(DESKTOP, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f]
        self.assertIn("NotShowIn=X-LuxOS-Launchpad;", lines)
        self.assertFalse(any(ln.startswith("OnlyShowIn=") or ln.startswith("NoDisplay=") for ln in lines))
        with open(LAUNCHPAD, encoding="utf-8") as f:
            self.assertIn(':X-LuxOS-Launchpad"', f.read())


@unittest.skipUnless(UNDER_XVFB, "GUI only under xvfb-run (never on a real display)")
@unittest.skipUnless(shutil.which("xdotool"), "needs xdotool")
@unittest.skipUnless(rofi_has_hover_no_scroll(), "needs rofi with -hover-no-scroll (packages/rofi, LUXOS_ROFI)")
class TestLaunchpadMouse(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxos-launchpad-test-")
        self.addCleanup(shutil.rmtree, self.t, True)
        home = os.path.join(self.t, "home")
        apps = os.path.join(home, ".local", "share", "applications")
        themes = os.path.join(home, ".local", "share", "rofi", "themes")
        fake = os.path.join(self.t, "bin")
        for d in (apps, themes, fake, os.path.join(self.t, "sys", "applications")):
            os.makedirs(d)
        self.launched = os.path.join(self.t, "launched")
        for i in range(APPS):
            with open(os.path.join(apps, "app%02d.desktop" % i), "w") as f:
                f.write("[Desktop Entry]\nType=Application\nName=App%02d\nExec=sh -c \"echo App%02d >> %s\"\n"
                        "Categories=Utility;\n" % (i, i, self.launched))
        # Launchpad sam (Exec zapise "Launchpad"): v mrizce byt nesmi
        with open(DESKTOP, encoding="utf-8") as f:
            entry = f.read().replace("Exec=luxos-launchpad", "Exec=sh -c \"echo Launchpad >> %s\"" % self.launched)
        self.assertIn("echo Launchpad", entry)
        with open(os.path.join(apps, "luxos-launchpad.desktop"), "w", encoding="utf-8") as f:
            f.write(entry)
        for name in ("luxos-launchpad.rasi", "luxos-light-colors.rasi"):
            shutil.copy(os.path.join(FILES, "rofi", name), themes)
        scripts = {"pkill": "#!/bin/sh\nexit 1\n",                   # zadne rofi uzivatele nezavirat
                   "luxos-appearance": "#!/bin/sh\necho dark\n",
                   "luxos-luxai-rofi": "#!/bin/sh\nexit 0\n"}
        for name, body in scripts.items():
            p = os.path.join(fake, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        os.symlink(os.path.abspath(ROFI), os.path.join(fake, "rofi"))
        self.env = dict(os.environ, HOME=home, XDG_DATA_HOME=os.path.join(home, ".local", "share"),
                        XDG_DATA_DIRS=os.path.join(self.t, "sys"), XDG_CONFIG_HOME=os.path.join(home, ".config"),
                        XDG_CACHE_HOME=os.path.join(self.t, "cache"), XDG_CURRENT_DESKTOP="XFCE",
                        PATH=fake + ":" + os.environ.get("PATH", "/usr/bin"))
        self.env.pop("LC_ALL", None)
        self.proc = None

    def tearDown(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=10)

    def open(self):
        xdo("mousemove", 2, 2)
        time.sleep(0.3)
        self.proc = subprocess.Popen(["bash", LAUNCHPAD], env=self.env, stderr=subprocess.DEVNULL)
        out = ""
        for _ in range(50):
            out = xdo("search", "--class", "rofi", "getwindowgeometry", "--shell", "%@")
            if "WIDTH=" in out:
                break
            time.sleep(0.1)
        g = dict(ln.split("=", 1) for ln in out.split() if "=" in ln)
        x, y, w, h = (int(g[k]) for k in ("X", "Y", "WIDTH", "HEIGHT"))
        time.sleep(0.4)
        # mrizka podle luxos-launchpad.rasi: okraj 22/26 px, vyhledavani ~42 px + mezera 18 px
        self.grid = (x + 26, y + 22 + 42 + 18, w - 52, h - 22 - 42 - 18 - 18)
        self.search = (x + w // 2, y + 40)

    def cell(self, row, col):
        gx, gy, gw, gh = self.grid
        return gx + (2 * col + 1) * gw // (2 * COLS), gy + (2 * row + 1) * gh // (2 * ROWS)

    def hover(self, row, col):
        """Najeti na dlazdici s chvenim mysi (puvodni chyba: kazdy pohyb posunul mrizku)."""
        cx, cy = self.cell(row, col)
        for d in (0, 1, 2, 3, 2, 1, 0, 1, 2, 3, 4, 3, 2):
            xdo("mousemove", cx + d, cy + d)
            time.sleep(0.04)

    def wheel(self, button, times=1):
        for _ in range(times):
            xdo("click", button)
            time.sleep(0.15)

    def key(self, *keys):
        xdo("key", *keys)
        time.sleep(0.25)

    def enter(self):
        time.sleep(0.2)
        xdo("key", "Return")
        return self.result()

    def result(self):
        for _ in range(30):
            if os.path.exists(self.launched):
                break
            time.sleep(0.1)
        self.proc.wait(timeout=10)
        try:
            with open(self.launched) as f:
                return f.read().split()
        except OSError:
            return []

    def test_enter_without_mouse_starts_first_app(self):
        """Mys stoji nad mrizkou uz pri otevreni: zvyrazneni zacina na prvni aplikaci."""
        xdo("mousemove", 640, 400)
        time.sleep(0.3)
        self.proc = subprocess.Popen(["bash", LAUNCHPAD], env=self.env, stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        self.assertEqual(self.enter(), ["App00"])

    def test_hover_highlights_tile(self):
        self.open()
        self.hover(1, 2)
        self.assertEqual(self.enter(), ["App09"])

    def test_hover_bottom_row_does_not_scroll(self):
        self.open()
        self.hover(3, 6)
        self.assertEqual(self.enter(), ["App27"])

    def test_pointer_leaving_grid_keeps_highlight(self):
        self.open()
        self.hover(3, 0)
        xdo("mousemove", *self.search)          # vyhledavaci pole
        time.sleep(0.2)
        xdo("mousemove", 3, 3)                  # mimo okno
        self.assertEqual(self.enter(), ["App21"])

    def test_wheel_scrolls_view_and_highlight_follows_pointer(self):
        self.open()
        self.hover(1, 2)
        self.wheel(5, 2)                        # o 2 radky dolu: pod mysi je App23
        self.hover(1, 2)
        self.assertEqual(self.enter(), ["App23"])

    def test_wheel_clamps_at_end_and_start(self):
        self.open()
        self.hover(0, 0)
        self.wheel(5, 8)                        # 9 radku, videt 4 -> nejvys o 5 radku
        self.hover(0, 0)
        self.wheel(4)
        self.hover(0, 0)
        self.assertEqual(self.enter(), ["App28"])

    def test_wheel_up_at_top(self):
        self.open()
        self.hover(1, 2)
        self.wheel(4)
        self.hover(1, 2)
        self.assertEqual(self.enter(), ["App09"])

    def test_keyboard_moves_highlight_and_scrolls_minimally(self):
        self.open()
        xdo("mousemove", *self.search)
        self.key("Down", "Down", "Down", "Down", "Down")       # radek 5 -> pohled radky 2..5
        self.hover(0, 0)
        self.assertEqual(self.enter(), ["App14"])

    def test_keyboard_after_hover(self):
        self.open()
        self.hover(1, 2)
        self.key("Right")
        self.assertEqual(self.enter(), ["App10"])

    def test_click_launches_tile(self):
        self.open()
        self.hover(2, 2)
        xdo("click", 1)
        self.assertEqual(self.result(), ["App16"])

    def test_typing_selects_best_match(self):
        """Po psani plati nejlepsi shoda, ne dlazdice drive zvyraznena mysi (mys stoji)."""
        self.open()
        self.hover(2, 3)
        xdo("type", "App41")
        time.sleep(0.4)
        self.assertEqual(self.enter(), ["App41"])

    def test_backspace_returns_to_first(self):
        self.open()
        self.hover(2, 3)
        xdo("type", "4")
        time.sleep(0.3)
        self.key("BackSpace")
        self.assertEqual(self.enter(), ["App00"])

    def test_launchpad_not_in_grid(self):
        """Launchpad se v mrizce nenajde (ani hledanim), v mrizce je jen 60 aplikaci."""
        self.open()
        xdo("type", "Launchpad")
        time.sleep(0.4)
        self.assertNotIn("Launchpad", self.enter())


if __name__ == "__main__":
    unittest.main()
