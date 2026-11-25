#!/usr/bin/env python3
"""LuxOS - testy Launchpadu (luxos-launchpad + rofi z [luxos] s volbou -hover-no-scroll).

  env -u DISPLAY xvfb-run -a -s "-screen 0 1280x800x24" python3 -m unittest packages/luxos-desktop/tests/test_luxos_launchpad.py -v

Spousti skutecny skript luxos-launchpad nad 60 falesnymi aplikacemi (App00..App59, mrizka 7x4,
9 radku) a ovlada ho pres xdotool; spustena aplikace zapise sve jmeno do souboru, takze test
vidi, co by Enter nebo klik spustil. pkill, luxos-appearance a luxos-luxai-rofi jsou falesne
(skript nesmi zavrit rofi uzivatele). Rofi bez -hover-no-scroll (Arch, ne [luxos]) se preskoci;
jinou binarku lze zadat v LUXOS_ROFI (napr. sestaveni packages/rofi). Jen pod xvfb-run.
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
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
LAUNCHPAD = os.path.join(FILES, "bin", "luxos-launchpad")
TMP = tempfile.mkdtemp(prefix="luxos-launchpad-test-")
ORDER = None        # luxos-launchpad-order (LSL), prelozeny v setUpModule
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
    # -custom-exit (tlacitka razeni) je ve stejnem baliku rofi z [luxos] (packages/rofi)
    return "hover-no-scroll" in r.stdout and "custom-exit" in r.stdout


def rofi_has_custom_resort():
    if not ROFI:
        return False
    try:
        r = subprocess.run([ROFI, "-help"], capture_output=True, text=True, timeout=10,
                           env=dict(os.environ, HOME=tempfile.gettempdir()))
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "custom-resort" in r.stdout


RESORT = rofi_has_custom_resort()


def setUpModule():
    global ORDER
    import sys
    sys.path.insert(0, HERE)
    import lsl_app
    ORDER = lsl_app.build("luxos-launchpad-order", TMP)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def rofi_has_touch():
    """rofi z [luxos] 2.0.0-1.5+: svisly tah posouva, LUXOS_ROFI_KEEP_BELOW (klavesnice na obrazovce)."""
    if not ROFI:
        return False
    try:
        with open(os.path.realpath(ROFI), "rb") as f:
            return b"LUXOS_ROFI_KEEP_BELOW" in f.read()
    except OSError:
        return False


def rofi_has_swipe():
    """rofi z [luxos] s luxos-swipe.patch (nenaleza se v -help: podle retezce v binarce)."""
    if not ROFI:
        return False
    try:
        with open(os.path.realpath(ROFI), "rb") as f:
            return b"LUXOS_ROFI_SORT" in f.read()
    except OSError:
        return False


def xdo(*args):
    # env=os.environ: Gio.TestDBus jineho modulu muze DISPLAY smazat v prostredi C, ktere by xdotool jinak zdedil
    return subprocess.run(["xdotool", *map(str, args)], env=os.environ, capture_output=True, text=True,
                          timeout=10).stdout


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
@unittest.skipUnless(rofi_has_hover_no_scroll(), "needs rofi with -hover-no-scroll -custom-exit (packages/rofi, LUXOS_ROFI)")
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
                        PATH=fake + ":" + os.environ.get("PATH", "/usr/bin"),
                        XDG_RUNTIME_DIR=os.path.join(self.t, "run"), LUXOS_LAUNCHPAD_ORDER=ORDER)
        os.makedirs(self.env["XDG_RUNTIME_DIR"], mode=0o700)
        self.env.pop("LC_ALL", None)
        self.proc = None

    def tearDown(self):
        # cela skupina (bash + rofi): rofi, ktere zustalo po neuspesnem testu, by drzelo klavesnici
        # a mys a dalsi testy by selhaly take
        if self.proc:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            self.proc.wait(timeout=10)

    def open(self):
        xdo("mousemove", 2, 2)
        time.sleep(0.3)
        self.proc = subprocess.Popen(["bash", LAUNCHPAD], env=self.env, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
        out = ""
        for _ in range(50):
            out = xdo("search", "--class", "rofi", "getwindowgeometry", "--shell", "%@")
            if "WIDTH=" in out:
                break
            time.sleep(0.1)
        g = dict(ln.split("=", 1) for ln in out.split() if "=" in ln)
        x, y, w, h = (int(g[k]) for k in ("X", "Y", "WIDTH", "HEIGHT"))
        time.sleep(0.4)
        # mrizka podle luxos-launchpad.rasi: okraj 22/26 px, vyhledavani ~42 px + mezera 18 px,
        # dole mezera 18 px + radek razeni ~24 px
        self.grid = (x + 26, y + 22 + 42 + 18, w - 52, h - 22 - 42 - 18 - 18 - 24 - 18)
        self.sortbar_y = y + h - 18 - 12
        self.win = (x, y, w, h)
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
        self.proc = subprocess.Popen(["bash", LAUNCHPAD], env=self.env, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
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

    def wait_rofi_restart(self, old):
        """Starsi rofi bez -custom-resort: po kliknuti na razeni rofi skonci a Launchpad ho hned
        otevre znovu (jine okno)."""
        for _ in range(60):
            ids = xdo("search", "--class", "rofi").split()
            if ids and ids != old:
                break
            time.sleep(0.1)
        time.sleep(0.5)

    def write_usage(self, apps):
        """Pocty spusteni (Nejpouzivanejsi = poradi seznamu) a pripravene poradi jako po spusteni."""
        now = int(time.time())
        usage = {a: {"count": 100 - i, "last": now - i} for i, a in enumerate(apps)}
        os.makedirs(os.path.join(self.env["XDG_DATA_HOME"], "luxos"), exist_ok=True)
        with open(os.path.join(self.env["XDG_DATA_HOME"], "luxos", "launchpad-usage.json"), "w") as f:
            json.dump({"version": 1, "apps": usage}, f)
        for mode in ("recent", "most"):
            subprocess.run([ORDER, "order", mode,
                            os.path.join(self.env["XDG_CACHE_HOME"], "luxos", "launchpad-order-" + mode)],
                           env=self.env, check=True)

    def test_sort_keys_switch_and_remember(self):
        """Alt+2 (= tlacitko Naposledy pouzite) prepne razeni, volba se pamatuje; s -custom-resort
        zustane stejne okno (zadne bliknuti)."""
        conf = os.path.join(self.env["XDG_CONFIG_HOME"], "luxos", "launchpad-sort")
        self.open()
        old = xdo("search", "--class", "rofi").split()
        xdo("key", "alt+2")
        if RESORT:
            time.sleep(0.5)
            self.assertEqual(xdo("search", "--class", "rofi").split(), old)
        else:
            self.wait_rofi_restart(old)
        with open(conf) as f:
            self.assertEqual(f.read().strip(), "recent")
        self.assertIsNone(self.proc.poll())     # Launchpad zustal otevreny
        self.hover(0, 0)
        self.assertEqual(self.enter(), ["App00"])

    @unittest.skipUnless(RESORT, "needs rofi with -custom-resort (packages/rofi)")
    def test_resort_in_place(self):
        """Razeni se zmeni na miste: stejne okno, nove poradi, vybrana prvni dlazdice, hledany
        text zustane, spusteni se zapocita do zvoleneho razeni."""
        self.write_usage(["app42.desktop", "app07.desktop"])
        os.makedirs(os.path.join(self.env["XDG_CONFIG_HOME"], "luxos"))
        conf = os.path.join(self.env["XDG_CONFIG_HOME"], "luxos", "launchpad-sort")
        with open(conf, "w") as f:
            f.write("alpha\n")
        self.open()
        old = xdo("search", "--class", "rofi").split()
        self.key("Right", "Right")              # vyber mimo prvni dlazdici
        xdo("key", "alt+3")                     # Nejpouzivanejsi
        time.sleep(0.5)
        self.assertEqual(xdo("search", "--class", "rofi").split(), old)
        with open(conf) as f:
            self.assertEqual(f.read().strip(), "most")
        self.assertEqual(self.enter(), ["App42"])
        usage = os.path.join(self.env["XDG_DATA_HOME"], "luxos", "launchpad-usage.json")
        for _ in range(50):
            with open(usage) as f:
                if json.load(f)["apps"]["app42.desktop"]["count"] == 101:
                    break
            time.sleep(0.1)
        with open(usage) as f:
            self.assertEqual(json.load(f)["apps"]["app42.desktop"]["count"], 101)

    def drag(self, start, end, steps=10):
        """Tah levym tlacitkem (dotykova obrazovka posila rofi stejny tah ukazatelem)."""
        (x1, y1), (x2, y2) = start, end
        xdo("mousemove", x1, y1)
        time.sleep(0.15)
        xdo("mousedown", 1)
        for i in range(1, steps + 1):
            xdo("mousemove", x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps)
            time.sleep(0.03)
        xdo("mouseup", 1)
        time.sleep(0.5)

    @unittest.skipUnless(RESORT, "needs rofi with -custom-resort (packages/rofi)")
    def test_swipe_changes_sort(self):
        """Vodorovny tah pres dlazdice prepne razeni (doleva dalsi, doprava predchozi, dokola) a nic
        nespusti; svisly tah razeni nemeni; klepnuti dlazdici dal spousti."""
        if not rofi_has_swipe():
            self.skipTest("needs rofi with luxos-swipe.patch (packages/rofi 2.0.0-1.5, LUXOS_ROFI)")
        os.makedirs(os.path.join(self.env["XDG_CONFIG_HOME"], "luxos"))
        conf = os.path.join(self.env["XDG_CONFIG_HOME"], "luxos", "launchpad-sort")
        with open(conf, "w") as f:
            f.write("alpha\n")
        self.open()
        old = xdo("search", "--class", "rofi").split()

        def sort():
            with open(conf) as f:
                return f.read().strip()
        self.drag(self.cell(1, 5), self.cell(1, 1))           # doleva: dalsi
        self.assertEqual(sort(), "recent")
        self.drag(self.cell(2, 5), self.cell(2, 1))
        self.assertEqual(sort(), "most")
        self.drag(self.cell(1, 1), self.cell(1, 5))           # doprava: predchozi
        self.assertEqual(sort(), "recent")
        self.drag(self.cell(1, 1), self.cell(1, 5))
        self.drag(self.cell(1, 1), self.cell(1, 5))           # z prvniho dokola na posledni
        self.assertEqual(sort(), "category")
        self.drag(self.cell(0, 2), self.cell(2, 2))           # svisle: razeni zustava (jen posun)
        self.assertEqual(sort(), "category")
        self.assertEqual(xdo("search", "--class", "rofi").split(), old)     # stale stejne okno
        self.assertFalse(os.path.exists(self.launched), "tah nesmi spustit aplikaci")
        # klepnuti (stisk + puštěni na miste) spusti dlazdici pod mysi
        self.hover(0, 0)
        xdo("click", 1)
        self.assertEqual(len(self.result()), 1)

    def need_touch_rofi(self):
        if not rofi_has_touch():
            self.skipTest("needs rofi with LUXOS_ROFI_KEEP_BELOW (packages/rofi 2.0.0-1.5, LUXOS_ROFI)")

    @unittest.skipUnless(RESORT, "needs rofi with -custom-resort (packages/rofi)")
    def test_vertical_drag_scrolls(self):
        """Svisly tah prstem posune mrizku o stranku (prst nahoru = dalsi aplikace, dolu = zpet) a nic
        nespusti - na dotyku jinak aplikace mimo prvni stranku nejdou najit."""
        self.need_touch_rofi()
        self.open()
        self.drag(self.cell(3, 3), self.cell(0, 3))           # nahoru: o 4 radky (stranku) dal
        self.drag(self.cell(0, 3), self.cell(3, 3))           # dolu: zpet na zacatek
        self.drag(self.cell(3, 3), self.cell(0, 3))           # a zase dal
        self.assertFalse(os.path.exists(self.launched), "tah nesmi spustit aplikaci")
        self.hover(0, 0)
        xdo("click", 1)
        self.assertEqual(self.result(), ["App%02d" % (COLS * ROWS)])

    def test_click_outside_closes_but_not_on_keyboard(self):
        """Klepnuti mimo Launchpad ho zavre (omylem otevreny), klepnuti do pasu klavesnice na obrazovce
        (pod LUXOS_ROFI_KEEP_BELOW od luxos-touch rofi-begin) ne."""
        self.need_touch_rofi()
        w, h = (int(v) for v in xdo("getdisplaygeometry").split())
        self.env["LUXOS_ROFI_KEEP_BELOW"] = str(h - 60)
        self.open()
        x, y, ww, wh = self.win
        self.assertLess(y + wh, h - 80, "okno musi koncit nad pasem klavesnice")
        xdo("mousemove", w // 2, h - 20)                     # "klavesnice"
        time.sleep(0.2)
        xdo("click", 1)
        time.sleep(0.6)
        self.assertIsNone(self.proc.poll(), "klepnuti na klavesnici Launchpad zavrelo")
        xdo("mousemove", w // 2, (y + wh + h - 60) // 2)      # plocha mezi oknem a klavesnici
        time.sleep(0.2)
        xdo("click", 1)
        self.proc.wait(timeout=10)
        self.assertFalse(os.path.exists(self.launched))

    @unittest.skipUnless(RESORT, "needs rofi with -custom-resort (packages/rofi)")
    def test_resort_keeps_filter(self):
        """Hledany text zustane i po zmene razeni (Nejpouzivanejsi -> Abecedne)."""
        self.write_usage(["app07.desktop", "app42.desktop"])
        self.open()
        old = xdo("search", "--class", "rofi").split()
        xdo("type", "App4")
        time.sleep(0.4)
        xdo("key", "alt+1")
        time.sleep(0.5)
        self.assertEqual(xdo("search", "--class", "rofi").split(), old)
        self.assertTrue(self.enter()[0].startswith("App4"))

    def test_usage_recorded_and_recent_first(self):
        """Spustena aplikace se zapise do launchpad-usage.json a v Naposledy pouzite je prvni."""
        os.makedirs(os.path.join(self.env["XDG_CONFIG_HOME"], "luxos"))
        with open(os.path.join(self.env["XDG_CONFIG_HOME"], "luxos", "launchpad-sort"), "w") as f:
            f.write("recent\n")
        self.open()
        self.hover(2, 2)
        self.assertEqual(self.enter(), ["App16"])
        usage = os.path.join(self.env["XDG_DATA_HOME"], "luxos", "launchpad-usage.json")
        for _ in range(50):
            if os.path.exists(usage):
                break
            time.sleep(0.1)
        with open(usage) as f:
            data = json.load(f)
        self.assertEqual(list(data["apps"]), ["app16.desktop"])
        self.assertEqual(data["apps"]["app16.desktop"]["count"], 1)
        time.sleep(0.5)
        os.unlink(self.launched)
        self.open()
        self.assertEqual(self.enter(), ["App16"])

    def test_new_flathub_app_shown_right_away(self):
        """Aplikace z Flathubu nainstalovana za behu relace (odkaz z luxos-apps-sync ve slozce
        /var/lib/luxos/apps, ktera je v XDG_DATA_DIRS) je v Launchpadu pri dalsim otevreni - i pri
        razeni podle kategorie, kde je pripravene poradi z doby pred instalaci."""
        luxos_apps = os.path.join(self.t, "var-lib-luxos-apps")
        export = os.path.join(self.t, "flatpak-exports", "applications")
        os.makedirs(os.path.join(luxos_apps, "applications"))
        os.makedirs(export)
        self.env["XDG_DATA_DIRS"] = luxos_apps + ":" + self.env["XDG_DATA_DIRS"]
        os.makedirs(os.path.join(self.env["XDG_CONFIG_HOME"], "luxos"))
        with open(os.path.join(self.env["XDG_CONFIG_HOME"], "luxos", "launchpad-sort"), "w") as f:
            f.write("category\n")
        self.open()                                 # pripravi poradi podle kategorie (jen App00..59)
        self.proc.terminate()
        self.proc.wait(timeout=10)
        subprocess.run(["xdotool", "search", "--class", "rofi", "windowkill"], env=os.environ, capture_output=True)
        order = os.path.join(self.env["XDG_CACHE_HOME"], "luxos", "launchpad-order-category")
        self.assertTrue(os.path.exists(order))
        time.sleep(1.1)                             # mtime slozky musi byt novejsi nez poradi
        src = os.path.join(export, "org.example.Browser.desktop")
        with open(src, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=Zebra Browser\n"
                    "Exec=sh -c \"echo Zebra >> %s\"\nCategories=Network;\n" % self.launched)
        os.symlink(src, os.path.join(luxos_apps, "applications", "org.example.Browser.desktop"))
        # Internet je prvni kategorie: nova aplikace musi byt prvni dlazdice (ne na konci mrizky)
        xdo("mousemove", 640, 400)
        self.open()
        self.assertEqual(self.enter(), ["Zebra"])

    def settings_entry(self, did, name):
        with open(os.path.join(self.t, "sys", "applications", did), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=%s\nExec=sh -c \"echo %s >> %s\"\n"
                    "Categories=Settings;HardwareSettings;X-XFCE-SettingsDialog;GTK;\n"
                    % (name, name.replace(" ", ""), self.launched))

    def test_selected_settings_apps_in_grid(self):
        """Samostatne aplikace s kategorii Nastaveni (Bluetooth, Telefon...) v Launchpadu jsou,
        ostatni panely Nastaveni (X-XFCE-SettingsDialog) dal ne; originalni soubor se nemeni."""
        self.settings_entry("luxos-bluetooth.desktop", "Zz Bluetooth")
        self.settings_entry("xfce-mouse-settings.desktop", "Zz Mouse Panel")
        self.open()
        xdo("type", "Zz Bluetooth")
        time.sleep(0.4)
        self.assertEqual(self.enter(), ["ZzBluetooth"])
        os.remove(self.launched)
        xdo("mousemove", 2, 2)
        self.open()
        xdo("type", "Zz Mouse")
        time.sleep(0.4)
        self.assertNotIn("ZzMousePanel", self.enter())
        with open(os.path.join(self.t, "sys", "applications", "luxos-bluetooth.desktop")) as f:
            self.assertIn("X-XFCE-SettingsDialog", f.read())

    def test_launchpad_not_in_grid(self):
        """Launchpad se v mrizce nenajde (ani hledanim), v mrizce je jen 60 aplikaci."""
        self.open()
        xdo("type", "Launchpad")
        time.sleep(0.4)
        self.assertNotIn("Launchpad", self.enter())


class TestSortOrder(unittest.TestCase):
    """luxos-launchpad-order: poradi pro rofi a pocitani spusteni (bez GUI)."""

    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxos-launchpad-order-")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.env = {k: v for k, v in os.environ.items() if k not in ("LC_ALL", "LC_MESSAGES")}
        self.env.update(XDG_DATA_HOME=os.path.join(self.t, "data"), XDG_CACHE_HOME=os.path.join(self.t, "cache"),
                        XDG_DATA_DIRS=os.path.join(self.t, "sys"), LANG="cs_CZ.UTF-8", HOME=self.t)

    def app(self, did, name, cats, root="sys", extra=""):
        d = os.path.join(self.t, root, "applications")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, did), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=%s\nCategories=%s\nExec=true\n%s"
                    "[Desktop Action new]\nName=Zzz\n" % (name, cats, extra))

    def run_order(self, *args):
        return subprocess.run([ORDER, *args], env=self.env, capture_output=True, text=True, timeout=30)

    def hist(self, path):
        with open(path) as f:
            return [ln.split(" ", 1)[1].strip() for ln in f]

    def usage_path(self):
        return os.path.join(self.t, "data", "luxos", "launchpad-usage.json")

    def order_path(self, mode):
        return os.path.join(self.t, "cache", "luxos", "launchpad-order-" + mode)

    def write_usage(self, apps):
        os.makedirs(os.path.dirname(self.usage_path()), exist_ok=True)
        with open(self.usage_path(), "w") as f:
            json.dump({"version": 1, "apps": apps}, f)

    def order(self, mode):
        out = os.path.join(self.t, "out", mode)
        self.assertEqual(self.run_order("order", mode, out).returncode, 0)
        return self.hist(out)

    def test_modes(self):
        self.write_usage({"a.desktop": {"count": 1, "last": 300}, "b.desktop": {"count": 5, "last": 100},
                          "c.desktop": {"count": 5, "last": 200}, "d.desktop": {"count": 0, "last": 0}})
        sentinel = ["luxos-launchpad-sentinel"]
        self.assertEqual(self.order("recent"), ["a.desktop", "c.desktop", "b.desktop"] + sentinel)
        self.assertEqual(self.order("most"), ["c.desktop", "b.desktop", "a.desktop"] + sentinel)
        self.assertEqual(self.order("alpha"), sentinel)

    def test_history_text_descending_with_sentinel(self):
        self.write_usage({"x.desktop": {"count": 2, "last": 2}, "y.desktop": {"count": 1, "last": 1}})
        out = os.path.join(self.t, "h")
        self.run_order("order", "most", out)
        with open(out) as f:
            self.assertEqual(f.read(), "2 x.desktop\n1 y.desktop\n0 luxos-launchpad-sentinel\n")

    def test_category_order_localized(self):
        self.app("gimp.desktop", "GIMP", "Graphics;2DGraphics;")
        self.app("firefox.desktop", "Firefox", "Network;WebBrowser;")
        self.app("calc.desktop", "Calculator", "Utility;", extra="Name[cs]=Výpočty\n")
        self.app("zed.desktop", "Zed", "")
        self.app("abiword.desktop", "AbiWord", "Office;")
        self.app("evolution.desktop", "Evolution", "Office;Network;")
        os.makedirs(os.path.join(self.t, "sys", "applications", "kde"))
        with open(os.path.join(self.t, "sys", "applications", "kde", "kate.desktop"), "w") as f:
            f.write("[Desktop Entry]\nName=Kate\nCategories=Utility;TextEditor;\n")
        # uzivatelska kopie ma prednost (jiny nazev, jina kategorie)
        self.app("zed.desktop", "Zed", "Development;", root="data")
        self.assertEqual(self.order("category"), ["evolution.desktop", "firefox.desktop", "abiword.desktop",
                                                  "gimp.desktop", "zed.desktop", "kde-kate.desktop", "calc.desktop",
                                                  "luxos-launchpad-sentinel"])
        # Výpočty (cs, bez diakritiky "vypocty") az za Kate - v anglictine Calculator pred Kate
        self.env["LANG"] = "C.UTF-8"
        self.assertEqual(self.order("category")[-3:-1], ["calc.desktop", "kde-kate.desktop"])

    def test_record_counts_launched_app(self):
        before = os.path.join(self.t, "before")
        after = os.path.join(self.t, "after")
        with open(before, "w") as f:
            f.write("2 b.desktop\n1 a.desktop\n0 luxos-launchpad-sentinel\n")
        # rofi zapsal +1 u a.desktop a seradil podle poctu
        with open(after, "w") as f:
            f.write("2 a.desktop\n2 b.desktop\n0 luxos-launchpad-sentinel\n")
        t0 = int(time.time())
        self.assertEqual(self.run_order("record", before, after).returncode, 0)
        with open(after, "w") as f:
            f.write("2 b.desktop\n1 a.desktop\n1 new.desktop\n0 luxos-launchpad-sentinel\n")
        time.sleep(1.1)
        self.run_order("record", before, after)
        with open(self.usage_path()) as f:
            apps = json.load(f)["apps"]
        self.assertEqual(sorted(apps), ["a.desktop", "new.desktop"])
        self.assertEqual([apps["a.desktop"]["count"], apps["new.desktop"]["count"]], [1, 1])
        self.assertTrue(t0 <= apps["a.desktop"]["last"] < apps["new.desktop"]["last"] <= time.time())
        self.assertEqual(self.hist(self.order_path("recent")), ["new.desktop", "a.desktop", "luxos-launchpad-sentinel"])
        self.assertEqual(self.hist(self.order_path("most")), ["new.desktop", "a.desktop", "luxos-launchpad-sentinel"])
        # nic nespusteno (Esc, dotaz LuxAI): beze zmeny
        with open(self.usage_path()) as f:
            saved = f.read()
        self.run_order("record", before, before)
        with open(self.usage_path()) as f:
            self.assertEqual(f.read(), saved)

    def test_usage_file_has_only_ids_counts_times(self):
        before = os.path.join(self.t, "before")
        with open(before, "w") as f:
            f.write("0 luxos-launchpad-sentinel\n")
        after = os.path.join(self.t, "after")
        with open(after, "w") as f:
            f.write("1 org.gnome.Calculator.desktop\n0 luxos-launchpad-sentinel\n")
        self.run_order("record", before, after)
        with open(self.usage_path()) as f:
            data = json.load(f)
        self.assertEqual(set(data), {"version", "apps"})
        self.assertEqual(set(data["apps"]["org.gnome.Calculator.desktop"]), {"count", "last"})

    def test_first_run_imports_rofi_history(self):
        os.makedirs(os.path.join(self.t, "cache"))
        with open(os.path.join(self.t, "cache", "rofi3.druncache"), "w") as f:
            f.write("7 firefox.desktop\n2 gimp.desktop\n")
        self.assertEqual(self.order("most"), ["firefox.desktop", "gimp.desktop", "luxos-launchpad-sentinel"])

    def test_cli_order_alpha_and_bad_mode(self):
        out = os.path.join(self.t, "o", "h")
        self.assertEqual(self.run_order("order", "alpha", out).returncode, 0)
        self.assertEqual(self.hist(out), ["luxos-launchpad-sentinel"])
        self.write_usage({"x.desktop": {"count": 3, "last": 1}})
        self.assertEqual(self.run_order("order", "bogus", out).returncode, 0)     # neznamy -> vychozi (most)
        self.assertEqual(self.hist(out), ["x.desktop", "luxos-launchpad-sentinel"])
        r = self.run_order()
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stderr)



class WithoutLuxAI(unittest.TestCase):
    """LuxOS Desktop na jine distribuci: bez luxos-luxai-rofi jen hledani aplikaci (rofi bez rezimu luxai).
    Falesna rofi jen zapise argumenty; PATH = vsechny programy systemu krome luxos-luxai-rofi."""

    def run_launchpad(self, with_luxai):
        tmp = tempfile.mkdtemp(prefix="lp-noai-")
        self.addCleanup(shutil.rmtree, tmp, True)
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        for d in ("/usr/bin", "/bin"):
            for name in os.listdir(d):
                dst = os.path.join(bindir, name)
                if name in ("luxos-luxai-rofi", "rofi", "luxos-appearance", "pkill") or os.path.lexists(dst):
                    continue
                os.symlink(os.path.join(d, name), dst)
        args = os.path.join(tmp, "args")
        fakes = {"rofi": "#!/bin/sh\nprintf '%%s\\n' \"$@\" > %s\nexit 1\n" % args,
                 "luxos-appearance": "#!/bin/sh\necho dark\n", "pkill": "#!/bin/sh\nexit 1\n"}
        if with_luxai:
            fakes["luxos-luxai-rofi"] = "#!/bin/sh\nexit 0\n"
        for name, body in fakes.items():
            with open(os.path.join(bindir, name), "w") as f:
                f.write(body)
            os.chmod(os.path.join(bindir, name), 0o755)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        env = {"PATH": bindir, "HOME": home, "XDG_CONFIG_HOME": home + "/.config", "XDG_CACHE_HOME": home + "/.cache",
               "XDG_RUNTIME_DIR": tmp, "XDG_DATA_DIRS": "/usr/share", "LC_ALL": "C",
               "LUXOS_I18N_DIR": os.path.join(HERE, "..", "..", "luxos-i18n", "files")}
        subprocess.run(["bash", LAUNCHPAD], env=env, capture_output=True, text=True, timeout=60)
        with open(args) as f:
            return f.read().splitlines()

    def test_without_luxai_only_apps(self):
        args = self.run_launchpad(with_luxai=False)
        self.assertEqual(args[args.index("-combi-modi") + 1], "drun")
        self.assertIn('entry { placeholder: "Search apps"; }', args)

    def test_with_luxai_apps_and_questions(self):
        args = self.run_launchpad(with_luxai=True)
        self.assertEqual(args[args.index("-combi-modi") + 1], "luxai:luxos-luxai-rofi,drun")
        self.assertIn('entry { placeholder: "Search apps or ask LuxAI"; }', args)



if __name__ == "__main__":
    unittest.main()
