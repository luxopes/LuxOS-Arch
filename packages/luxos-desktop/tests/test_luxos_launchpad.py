#!/usr/bin/env python3
"""LuxOS - testy Launchpadu (luxos-launchpad + rofi z [luxos] s volbou -hover-no-scroll).

  env -u DISPLAY xvfb-run -a -s "-screen 0 1280x800x24" python3 -m unittest packages/luxos-desktop/tests/test_luxos_launchpad.py -v

Spousti skutecny skript luxos-launchpad nad 60 falesnymi aplikacemi (App00..App59, mrizka 7x4,
9 radku) a ovlada ho pres xdotool; spustena aplikace zapise sve jmeno do souboru, takze test
vidi, co by Enter nebo klik spustil. pkill, luxos-appearance a luxos-luxai-rofi jsou falesne
(skript nesmi zavrit rofi uzivatele). Rofi bez -hover-no-scroll (Arch, ne [luxos]) se preskoci;
jinou binarku lze zadat v LUXOS_ROFI (napr. sestaveni packages/rofi). Jen pod xvfb-run.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
LAUNCHPAD = os.path.join(FILES, "bin", "luxos-launchpad")
PY = os.path.join(FILES, "python", "luxos_launchpad.py")
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
                        XDG_RUNTIME_DIR=os.path.join(self.t, "run"), LUXOS_LAUNCHPAD_PY=PY)
        os.makedirs(self.env["XDG_RUNTIME_DIR"], mode=0o700)
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
            subprocess.run(["python3", PY, "order", mode,
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
        subprocess.run(["xdotool", "search", "--class", "rofi", "windowkill"], capture_output=True)
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

    def test_launchpad_not_in_grid(self):
        """Launchpad se v mrizce nenajde (ani hledanim), v mrizce je jen 60 aplikaci."""
        self.open()
        xdo("type", "Launchpad")
        time.sleep(0.4)
        self.assertNotIn("Launchpad", self.enter())


class TestSortOrder(unittest.TestCase):
    """luxos_launchpad.py: poradi pro rofi a pocitani spusteni (bez GUI)."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("luxos_launchpad", PY)
        self.lp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.lp)
        self.t = tempfile.mkdtemp(prefix="luxos-launchpad-order-")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.old_env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.old_env)))
        os.environ.update(XDG_DATA_HOME=os.path.join(self.t, "data"), XDG_CACHE_HOME=os.path.join(self.t, "cache"),
                          XDG_DATA_DIRS=os.path.join(self.t, "sys"), LANG="cs_CZ.UTF-8")

    def app(self, did, name, cats, root="sys", extra=""):
        d = os.path.join(self.t, root, "applications")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, did), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=%s\nCategories=%s\nExec=true\n%s"
                    "[Desktop Action new]\nName=Zzz\n" % (name, cats, extra))

    def hist(self, path):
        with open(path) as f:
            return [ln.split(" ", 1)[1].strip() for ln in f]

    def test_modes(self):
        usage = {"a.desktop": {"count": 1, "last": 300}, "b.desktop": {"count": 5, "last": 100},
                 "c.desktop": {"count": 5, "last": 200}, "d.desktop": {"count": 0, "last": 0}}
        self.assertEqual(self.lp.order_ids("recent", usage), ["a.desktop", "c.desktop", "b.desktop"])
        self.assertEqual(self.lp.order_ids("most", usage), ["c.desktop", "b.desktop", "a.desktop"])
        self.assertEqual(self.lp.order_ids("alpha", usage), [])

    def test_history_text_descending_with_sentinel(self):
        text = self.lp.history_text(["x.desktop", "y.desktop"])
        self.assertEqual(text, "2 x.desktop\n1 y.desktop\n0 luxos-launchpad-sentinel\n")

    def test_category_order_localized(self):
        self.app("gimp.desktop", "GIMP", "Graphics;2DGraphics;")
        self.app("firefox.desktop", "Firefox", "Network;WebBrowser;")
        self.app("calc.desktop", "Calculator", "Utility;", extra="Name[cs]=Kalkulacka\n")
        self.app("zed.desktop", "Zed", "")
        self.app("abiword.desktop", "AbiWord", "Office;")
        self.app("evolution.desktop", "Evolution", "Office;Network;")
        os.makedirs(os.path.join(self.t, "sys", "applications", "kde"))
        with open(os.path.join(self.t, "sys", "applications", "kde", "kate.desktop"), "w") as f:
            f.write("[Desktop Entry]\nName=Kate\nCategories=Utility;TextEditor;\n")
        ids = self.lp.order_ids("category", {})
        self.assertEqual(ids, ["evolution.desktop", "firefox.desktop", "abiword.desktop", "gimp.desktop",
                               "calc.desktop", "kde-kate.desktop", "zed.desktop"])

    def test_record_counts_launched_app(self):
        before = os.path.join(self.t, "before")
        after = os.path.join(self.t, "after")
        with open(before, "w") as f:
            f.write("2 b.desktop\n1 a.desktop\n0 luxos-launchpad-sentinel\n")
        # rofi zapsal +1 u a.desktop a seradil podle poctu
        with open(after, "w") as f:
            f.write("2 a.desktop\n2 b.desktop\n0 luxos-launchpad-sentinel\n")
        self.assertEqual(self.lp.record(before, after, now=1000), "a.desktop")
        with open(after, "w") as f:
            f.write("2 b.desktop\n1 a.desktop\n1 new.desktop\n0 luxos-launchpad-sentinel\n")
        self.assertEqual(self.lp.record(before, after, now=2000), "new.desktop")
        with open(self.lp.usage_path()) as f:
            data = json.load(f)
        self.assertEqual(data["apps"], {"a.desktop": {"count": 1, "last": 1000},
                                        "new.desktop": {"count": 1, "last": 2000}})
        self.assertEqual(self.hist(self.lp.order_path("recent")),
                         ["new.desktop", "a.desktop", "luxos-launchpad-sentinel"])
        # nic nespusteno (Esc, dotaz LuxAI): beze zmeny
        self.assertIsNone(self.lp.record(before, before))

    def test_usage_file_has_only_ids_counts_times(self):
        before = os.path.join(self.t, "before")
        with open(before, "w") as f:
            f.write("0 luxos-launchpad-sentinel\n")
        after = os.path.join(self.t, "after")
        with open(after, "w") as f:
            f.write("1 org.gnome.Calculator.desktop\n0 luxos-launchpad-sentinel\n")
        self.lp.record(before, after, now=5)
        with open(self.lp.usage_path()) as f:
            data = json.load(f)
        self.assertEqual(set(data), {"version", "apps"})
        self.assertEqual(set(data["apps"]["org.gnome.Calculator.desktop"]), {"count", "last"})

    def test_first_run_imports_rofi_history(self):
        os.makedirs(os.path.join(self.t, "cache"))
        with open(os.path.join(self.t, "cache", "rofi3.druncache"), "w") as f:
            f.write("7 firefox.desktop\n2 gimp.desktop\n")
        self.assertEqual(self.lp.order_ids("most", self.lp.load_usage()), ["firefox.desktop", "gimp.desktop"])

    def test_cli_order_alpha_and_bad_mode(self):
        out = os.path.join(self.t, "o", "h")
        self.assertEqual(self.lp.main(["x", "order", "alpha", out]), 0)
        self.assertEqual(self.hist(out), ["luxos-launchpad-sentinel"])
        self.assertEqual(self.lp.main(["x", "order", "bogus", out]), 0)     # neznamy -> vychozi
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.lp.main(["x"]), 2)


if __name__ == "__main__":
    unittest.main()
