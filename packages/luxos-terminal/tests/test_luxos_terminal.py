#!/usr/bin/env python3
"""LuxOS Terminal - testy programu luxos-terminal.

    LUXOS_TERMINAL_BIN=cesta/k/luxos-terminal XDG_RUNTIME_DIR=$(mktemp -d) \\
    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS xvfb-run -a -s "-screen 0 1280x900x24" dbus-run-session -- python3 -m unittest packages/luxos-terminal/tests/test_luxos_terminal.py -v

Okna se testuji jen pod xvfb-run (nikdy na skutecne obrazovce), kazdy test ve vlastnim procesu
terminalu (LUXOS_TERMINAL_NEW_PROCESS=1) a s docasnym HOME. Kontroluje se snimek obrazovky:
barvy profilu (svetly/tmavy), barevny text, obrazek SIXEL (jen kdyz VTE podporu SIXEL ma -
balik vte3 z [luxos]), nazev okna, panely v jednom procesu, pracovni adresar, preklad, velikost okna.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
# Sestaveni baliku (makepkg) kopiruje jen adresar baliku - zdroje ostatnich baliku pak nejsou k dispozici
IN_REPO = os.path.isdir(os.path.join(ROOT, "packages", "luxos-i18n", "files"))
I18N_DIR = os.path.join(ROOT, "packages/luxos-i18n/files") if IN_REPO else "/usr/share/luxos/i18n"
BIN = os.environ.get("LUXOS_TERMINAL_BIN") or shutil.which("luxos-terminal") or ""
UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")


def sixel_square(w, h, rgb_percent):
    """Obrazek SIXEL: plny obdelnik jedne barvy (registr 1, barva v procentech RGB)."""
    r, g, b = rgb_percent
    band = f"#1!{w}~"
    rows = (h + 5) // 6
    return f'\x1bPq"1;1;{w};{h}#1;2;{r};{g};{b}' + "-".join([band] * rows) + "\x1b\\"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def logo_source():
    """Barevne logo LuxOS ze zdroju (SVG, potrebuje zavadec SVG pro gdk-pixbuf), jinak None."""
    svg = os.path.join(ROOT, "packages/luxos-branding/files/logo/luxos-logo.svg")
    if not os.path.isfile(svg):
        svg = "/usr/share/luxos/logo/luxos-logo.svg"
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        GdkPixbuf.Pixbuf.new_from_file_at_size(svg, 32, 32)
        return svg
    except Exception:
        return None


def has_sixel():
    out = subprocess.run([BIN, "--version"], capture_output=True, text=True).stdout
    return "SIXEL" in out


class SourceTest(unittest.TestCase):
    @unittest.skipUnless(IN_REPO, "needs the LuxOS source tree")
    def test_translations(self):
        """Kazdy text T("...") z luxos-terminal.c je prelozeny ve vsech 12 jazycich (stejne %s)."""
        import re
        src = read(os.path.join(HERE, "..", "files", "luxos-terminal.c"))
        keys = set(re.findall(r'\bT\("((?:[^"\\]|\\.)*)"\)', src))
        self.assertGreater(len(keys), 15)
        i18n = os.path.join(ROOT, "packages", "luxos-i18n", "files")
        langs = sorted(f for f in os.listdir(i18n) if f.endswith(".tsv"))
        self.assertEqual(len(langs), 12)
        for lang in langs:
            table = {}
            for line in read(os.path.join(i18n, lang)).splitlines():
                if "\t" in line and not line.startswith("#"):
                    k, v = line.split("\t", 1)
                    table[k] = v.strip("\t")
            for k in keys:
                self.assertTrue(table.get(k), f"{lang}: missing {k!r}")
                self.assertEqual(k.count("%s"), table[k].count("%s"), f"{lang}: {k!r}")

    def test_desktop_files(self):
        d = read(os.path.join(HERE, "..", "files", "luxos-terminal.desktop"))
        for lang in ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv"):
            self.assertIn(f"Name[{lang}]=", d)
            self.assertIn(f"Comment[{lang}]=", d)
        self.assertIn("Categories=System;TerminalEmulator;GTK;", d)
        self.assertIn("StartupWMClass=luxos-terminal", d)
        h = read(os.path.join(HERE, "..", "files", "luxos-terminal-helper.desktop"))
        self.assertIn("X-XFCE-Category=TerminalEmulator", h)


class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BIN or not os.access(BIN, os.X_OK):
            raise unittest.SkipTest("luxos-terminal binary not found (LUXOS_TERMINAL_BIN)")

    def test_version(self):
        r = subprocess.run([BIN, "--version"], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"^luxos-terminal \S+ \(VTE \d+\.\d+\.\d+")

    def test_help(self):
        r = subprocess.run([BIN, "--help"], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)
        for opt in ("--execute", "--working-directory", "--hold", "--tab", "--title"):
            self.assertIn(opt, r.stdout)

    def test_logo_sixel(self):
        """Logo pro fastfetch: SIXEL v presne velikosti pole loga, okraje pruhledne, mezipamet."""
        if not logo_source():
            self.skipTest("cannot load the LuxOS logo (SVG loader)")
        sys.path.insert(0, HERE)
        from sixel_decode import decode
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, XDG_CACHE_HOME=tmp, LUXOS_TERMINAL_LOGO_SOURCE=logo_source())
            for cell, mode, bg in (("9x20", "dark", (28, 28, 34)), ("12x26", "light", (255, 255, 255))):
                r = subprocess.run([BIN, "--logo-sixel", cell, mode], capture_output=True, env=env, timeout=30)
                self.assertEqual(r.returncode, 0, r.stderr)
                data, path = r.stdout.decode("latin-1").rsplit("\n", 2)[:2]
                self.assertEqual(path, os.path.join(tmp, "luxos", "terminal", f"logo2-{cell}-{mode}.six"))
                self.assertTrue(data.startswith("\x1bP0;1;0q"), "P2=1 (transparent background)")
                cw, ch = map(int, cell.split("x"))
                w, h, px = decode(data)
                self.assertEqual((w, h), (min(31 * cw, 11 * ch),) * 2, "logo fits 31x12 cells, last row free")
                self.assertNotIn((0, 0), px, "corner is transparent")
                blue = sum(1 for (r_, g, b) in px.values() if b > r_ + 40 and b > 150)
                self.assertGreater(blue, w * h * 0.08, "blue/violet logo pixels")
                # okraje smichane s pozadim profilu: zadny bod nema barvu "druheho" profilu
                other = (255, 255, 255) if mode == "dark" else (0, 0, 0)
                self.assertNotIn(other, set(px.values()))
            # podruhe z mezipameti (stejny soubor)
            r = subprocess.run([BIN, "--logo-sixel", "9x20", "dark"], capture_output=True, env=env, timeout=30)
            self.assertTrue(r.stdout.decode("latin-1").endswith("logo2-9x20-dark.six\n"))


@unittest.skipUnless(UNDER_XVFB, "GUI only under xvfb-run (never on a real display)")
class GuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BIN or not os.access(BIN, os.X_OK):
            raise unittest.SkipTest("luxos-terminal binary not found (LUXOS_TERMINAL_BIN)")
        import gi
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk
        cls.Gdk = Gdk
        if Gdk.Screen.get_default() is None:
            raise unittest.SkipTest("no X display")

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="luxos-terminal-test-")
        self.procs = []
        self.env = dict(os.environ, HOME=self.home, XDG_CONFIG_HOME=os.path.join(self.home, ".config"),
                        XDG_CACHE_HOME=os.path.join(self.home, ".cache"), SHELL="/bin/sh",
                        LUXOS_TERMINAL_NEW_PROCESS="1", GTK_THEME="Adwaita", LANG="C.UTF-8", NO_AT_BRIDGE="1")
        self.env.pop("LC_ALL", None)
        self.env.pop("LC_MESSAGES", None)

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
        shutil.rmtree(self.home, ignore_errors=True)

    # --- pomocne ---
    def config(self, text):
        d = os.path.join(self.home, ".config", "luxos")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "terminal.conf"), "w") as f:
            f.write(text)

    def start(self, *args, env=None, stderr=subprocess.DEVNULL):
        p = subprocess.Popen([BIN, *args], env=env or self.env, stdout=subprocess.DEVNULL, stderr=stderr)
        self.procs.append(p)
        return p

    def windows(self):
        r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "luxos-terminal"],
                           capture_output=True, text=True, env=self.env)
        return r.stdout.split()

    def wait_window(self, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            w = self.windows()
            if w:
                return w
            time.sleep(0.1)
        self.fail("terminal window did not appear")

    def window_name(self, wid):
        return subprocess.run(["xdotool", "getwindowname", wid], capture_output=True, text=True).stdout.strip()

    def screenshot(self, name=None):
        Gdk = self.Gdk
        while Gdk.events_pending():
            Gdk.event_get()
        root = Gdk.get_default_root_window()
        pb = Gdk.pixbuf_get_from_window(root, 0, 0, root.get_width(), root.get_height())
        out = os.environ.get("LUXOS_TEST_SCREENSHOTS")
        if out and name:
            os.makedirs(out, exist_ok=True)
            pb.savev(os.path.join(out, name + ".png"), "png", [], [])
        return pb

    @staticmethod
    def count(pb, rgb, tol=6):
        data = pb.get_pixels()
        n, step, rs = pb.get_n_channels(), pb.get_n_channels(), pb.get_rowstride()
        hits = 0
        for y in range(pb.get_height()):
            row = y * rs
            for x in range(0, pb.get_width() * step, step):
                i = row + x
                if abs(data[i] - rgb[0]) <= tol and abs(data[i + 1] - rgb[1]) <= tol and abs(data[i + 2] - rgb[2]) <= tol:
                    hits += 1
        return hits

    def window_area(self, pb):
        """Vyrez snimku s oknem terminalu (koren obrazovky xvfb je cerny jako tmavy profil)."""
        w = self.windows()
        if not w:
            return pb
        geo = subprocess.run(["xdotool", "getwindowgeometry", "--shell", w[0]], capture_output=True,
                             text=True, env=self.env).stdout
        g = dict(line.split("=", 1) for line in geo.split() if "=" in line)
        x, y = max(0, int(g["X"])), max(0, int(g["Y"]))
        width = min(int(g["WIDTH"]), pb.get_width() - x)
        height = min(int(g["HEIGHT"]), pb.get_height() - y)
        return pb.new_subpixbuf(x, y, width, height)

    def wait_pixels(self, rgb, minimum, name, timeout=8):
        end = time.time() + timeout
        hits = 0
        while time.time() < end:
            time.sleep(0.3)
            pb = self.window_area(self.screenshot())
            hits = self.count(pb, rgb)
            if hits >= minimum:
                break
        self.screenshot(name)
        return hits

    # --- testy ---
    def test_dark_profile_and_colors(self):
        self.config("[terminal]\ntheme=dark\n")
        # cervene pozadi (paleta 1 = #ff6b81) pres 10 znaku
        self.start("-H", "-x", "sh", "-c", r"printf '\033[41m%s\033[0m\n' '          '; sleep 30")
        self.wait_window()
        self.assertGreater(self.wait_pixels((28, 28, 34), 100000, "dark"), 100000, "dark background")
        self.assertGreater(self.count(self.screenshot(), (0xff, 0x6b, 0x81)), 500, "red cells (palette)")

    def test_default_dark_opaque(self):
        """Bez nastaveni: tmavy profil i ve svetlem vzhledu systemu, pozadi nepruhledne."""
        d = os.path.join(self.home, ".config", "gtk-3.0")
        os.makedirs(d)
        with open(os.path.join(d, "settings.ini"), "w") as f:
            f.write("[Settings]\ngtk-theme-name=WhiteSur-Light\n")
        env = dict(self.env)
        env.pop("GTK_THEME")
        self.start("-x", "sh", "-c", "sleep 30", env=env)
        self.wait_window()
        self.assertGreater(self.wait_pixels((28, 28, 34), 100000, "default-dark"), 100000)

    def test_auto_follows_light_system(self):
        self.config("[terminal]\ntheme=auto\n")
        d = os.path.join(self.home, ".config", "gtk-3.0")
        os.makedirs(d)
        with open(os.path.join(d, "settings.ini"), "w") as f:
            f.write("[Settings]\ngtk-theme-name=WhiteSur-Light\n")
        env = dict(self.env)
        env.pop("GTK_THEME")
        self.start("-x", "sh", "-c", "sleep 30", env=env)
        self.wait_window()
        self.assertGreater(self.wait_pixels((0xff, 0xff, 0xff), 100000, "auto-light"), 100000)

    def test_no_warnings(self):
        """Bezny beh (OSC 7 adresar, novy panel, hledani, zoom, prepnuti panelu) bez VTE/GTK varovani."""
        err = os.path.join(self.home, "stderr")
        with open(err, "w") as ef:
            self.start("-x", "bash", "--norc", "-c",
                       'printf "\\033]7;file://%s%s\\007\\033]0;title\\007" "$(hostname)" "$PWD"; '
                       "echo https://luxos.example; sleep 30", stderr=ef)
            self.wait_window()
            time.sleep(1)
            for keys in ("ctrl+shift+t", "ctrl+Page_Up", "ctrl+shift+f", "Escape", "ctrl+plus", "ctrl+0",
                         "ctrl+shift+n"):
                # bez spravce oken jde klavesnice do okna pod mysi (okno se zoomem zmensuje)
                subprocess.run(["xdotool", "mousemove", "--window", self.windows()[0], "40", "70"], env=self.env)
                subprocess.run(["xdotool", "key", keys], env=self.env)
                time.sleep(0.4)
            time.sleep(1)
        text = read(err)
        for bad in ("CRITICAL", "WARNING", "Gtk-", "VTE-"):
            self.assertNotIn(bad, text, text)
        for _ in range(50):
            if len(self.windows()) == 2:
                break
            time.sleep(0.1)
        self.assertEqual(len(self.windows()), 2, "Ctrl+Shift+N opens a second window")

    def test_light_profile(self):
        self.config("[terminal]\ntheme=light\n")
        self.start("-x", "sh", "-c", "sleep 30")
        self.wait_window()
        self.assertGreater(self.wait_pixels((0xff, 0xff, 0xff), 100000, "light"), 100000, "light background")

    def test_system_theme_dark(self):
        # automaticky profil podle tematu GTK (LuxOS: WhiteSur-Dark / WhiteSur-Light pres xsettings)
        d = os.path.join(self.home, ".config", "gtk-3.0")
        os.makedirs(d)
        with open(os.path.join(d, "settings.ini"), "w") as f:
            f.write("[Settings]\ngtk-theme-name=WhiteSur-Dark\n")
        self.config("[terminal]\ntheme=auto\n")
        env = dict(self.env)
        env.pop("GTK_THEME")
        self.start("-x", "sh", "-c", "sleep 30", env=env)
        self.wait_window()
        self.assertGreater(self.wait_pixels((28, 28, 34), 100000, "auto-dark"), 100000)

    def test_title_and_hold(self):
        self.start("-T", "Hello LuxOS", "-H", "-x", "true")
        wid = self.wait_window()[0]
        time.sleep(1)
        self.assertEqual(self.window_name(wid), "Hello LuxOS")
        # --hold: okno zustane i po skonceni prikazu
        self.assertTrue(self.windows())

    def test_default_title_translated(self):
        if not os.path.isfile(os.path.join(I18N_DIR, "cs.tsv")):
            self.skipTest("no translations")
        env = dict(self.env, LANG="cs_CZ.UTF-8", LUXOS_I18N_DIR=I18N_DIR)
        self.start("-x", "sh", "-c", "sleep 30", env=env)
        wid = self.wait_window()[0]
        time.sleep(0.5)
        self.assertEqual(self.window_name(wid), "Terminál")

    def test_exit_closes_window(self):
        p = self.start("-x", "true")
        p.wait(10)
        self.assertEqual(p.returncode, 0)

    def test_close_without_question_when_only_a_shell_runs(self):
        """Shell v popredi (i vnoreny pres spousteci skript) neni bezici program: okno se zavre hned."""
        p = self.start("-x", "bash", "--norc", "-c", "bash --norc -i; true")   # vnoreny shell v popredi
        wid = self.wait_window()[0]
        time.sleep(1.0)
        # bez spravce oken jde klavesnice do okna pod mysi
        subprocess.run(["xdotool", "mousemove", "--window", wid, "40", "70"], env=self.env)
        subprocess.run(["xdotool", "key", "ctrl+shift+w"], env=self.env)
        p.wait(10)
        self.assertEqual(p.returncode, 0)

    def test_working_directory_and_env(self):
        out = os.path.join(self.home, "out")
        wd = os.path.join(self.home, "složka s mezerou")
        os.mkdir(wd)
        env = dict(self.env, TERM="tmux-256color")   # TERM volajiciho se neprenasi
        self.start("-w", wd, "-x", "sh", "-c", f'pwd > "{out}"; echo "$TERM_PROGRAM $TERM" >> "{out}"', env=env)
        for _ in range(100):
            if os.path.exists(out) and read(out).count("\n") >= 2:
                break
            time.sleep(0.1)
        lines = read(out).splitlines()
        self.assertEqual(lines[0], wd)
        self.assertEqual(lines[1], "LuxOS-Terminal xterm-256color")

    def test_tabs_one_process(self):
        env = dict(self.env)
        env.pop("LUXOS_TERMINAL_NEW_PROCESS")
        p1 = self.start("-x", "sh", "-c", "sleep 30", env=env)
        self.wait_window()
        time.sleep(0.5)
        # druhe volani preda prikaz bezicimu procesu a hned skonci
        p2 = self.start("--tab", "-T", "Second", "-x", "sh", "-c", "sleep 30", env=env)
        self.assertEqual(p2.wait(10), 0)
        p3 = self.start("-T", "Third", "-x", "sh", "-c", "sleep 30", env=env)
        self.assertEqual(p3.wait(10), 0)
        time.sleep(1)
        self.assertIsNone(p1.poll())
        self.assertEqual(len(self.windows()), 2, "--tab adds a tab, plain call a new window")
        self.screenshot("tabs")

    def test_link_ctrl_click(self):
        """Ctrl+klik na adresu otevre vychozi aplikaci pro http (falesna, zapise adresu do souboru)."""
        out = os.path.join(self.home, "opened")
        apps = os.path.join(self.home, ".local", "share", "applications")
        os.makedirs(apps)
        script = os.path.join(self.home, "open-url")
        with open(script, "w") as f:
            f.write(f'#!/bin/sh\necho "$1" > "{out}"\n')
        os.chmod(script, 0o755)
        with open(os.path.join(apps, "fake-browser.desktop"), "w") as f:
            f.write(f"[Desktop Entry]\nType=Application\nName=Fake\nExec={script} %u\n"
                    "MimeType=x-scheme-handler/https;x-scheme-handler/http;\n")
        with open(self._mkconf("mimeapps.list"), "w") as f:
            f.write("[Default Applications]\nx-scheme-handler/https=fake-browser.desktop\n"
                    "x-scheme-handler/http=fake-browser.desktop\n")
        env = dict(self.env, XDG_DATA_HOME=os.path.join(self.home, ".local", "share"))
        self.config("[terminal]\ntheme=dark\nfont=Monospace 12\n")
        self.start("-x", "sh", "-c", "printf 'https://luxos.example/docs?x=1, more\\n'; sleep 30", env=env)
        wid = self.wait_window()[0]
        time.sleep(1.5)
        # prvni radek textu: lista je od spravce oken (pod xvfb zadna), okraj 4 px, radek ~20 px
        geo = subprocess.run(["xdotool", "getwindowgeometry", wid], capture_output=True, text=True).stdout
        subprocess.run(["xdotool", "mousemove", "--window", wid, "60", "12"], env=self.env)
        time.sleep(0.3)
        subprocess.run(["xdotool", "keydown", "ctrl", "click", "1", "keyup", "ctrl"], env=self.env)
        for _ in range(50):
            if os.path.exists(out):
                break
            time.sleep(0.1)
        self.screenshot("link")
        self.assertTrue(os.path.exists(out), "link not opened " + geo)
        self.assertEqual(read(out).strip(), "https://luxos.example/docs?x=1")

    def _mkconf(self, name):
        d = os.path.join(self.home, ".config")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, name)

    def test_window_size_remembered(self):
        self.config("[state]\ncolumns=60\nrows=12\n")
        p = self.start("-x", "sh", "-c", "sleep 30")
        wid = self.wait_window()[0]
        time.sleep(0.5)
        geo = subprocess.run(["xdotool", "getwindowgeometry", wid], capture_output=True, text=True).stdout
        w60 = int(geo.split("Geometry: ")[1].split("x")[0])
        p.terminate()
        p.wait(5)
        self.config("[state]\ncolumns=120\nrows=12\n")
        self.start("-x", "sh", "-c", "sleep 30")
        wid = self.wait_window()[0]
        time.sleep(0.5)
        geo = subprocess.run(["xdotool", "getwindowgeometry", wid], capture_output=True, text=True).stdout
        w120 = int(geo.split("Geometry: ")[1].split("x")[0])
        self.assertGreater(w120, w60 + 200)

    def test_sixel_image(self):
        if not has_sixel():
            self.skipTest("VTE without SIXEL (needs vte3 from [luxos])")
        self.config("[terminal]\ntheme=dark\n")
        img = os.path.join(self.home, "green.six")
        with open(img, "w") as f:
            f.write(sixel_square(96, 60, (0, 100, 0)))
        self.start("-x", "sh", "-c", f'printf "LUXOS_TERMINAL_SIXEL=%s\\n" "$LUXOS_TERMINAL_SIXEL"; cat "{img}"; sleep 30')
        self.wait_window()
        hits = self.wait_pixels((0, 255, 0), 96 * 60 * 0.9, "sixel")
        self.assertGreaterEqual(hits, 96 * 60 * 0.9, "green SIXEL square not drawn")

    def test_sixel_image_under_text_and_alt_screen(self):
        """Obrazek patri bunkam pod nim (jako v xterm): text pres nej (top hned po uvitani s logem
        prekresluje obrazovku pres \\e[H a \\e[K bez alternativni obrazovky), smazani radku a
        alternativni obrazovka (vim, less, htop) ho skryji; po navratu z alt. obrazovky je zpet.
        Regrese: logo zustavalo nakreslene pres vystup top (vte3 0.84.1-1.1)."""
        if not has_sixel():
            self.skipTest("VTE without SIXEL (needs vte3 from [luxos])")
        self.config("[terminal]\ntheme=dark\n")
        img = os.path.join(self.home, "green.six")
        with open(img, "w") as f:
            f.write(sixel_square(200, 120, (0, 100, 0)))
        st = os.path.join(self.home, "step")
        # 1 obrazek; 2 alt. obrazovka (?1049h) s textem; 3 zpet (?1049l); 4 jako top: domu a radky
        # textu s \e[K pres celou obrazovku; 5 novy obrazek a jen cast prvniho radku prepsana
        script = (f'cat "{img}"; echo; echo normal; : > "{st}1"; sleep 2; '
                  f'printf "\\033[?1049h\\033[H\\033[2Jalt screen\\n"; seq 1 20; : > "{st}2"; sleep 2; '
                  f'printf "\\033[?1049l"; : > "{st}3"; sleep 2; '
                  f'printf "\\033[H"; i=0; while [ $i -lt 20 ]; do printf "top line %s\\033[K\\r\\n" $i; '
                  f'i=$((i+1)); done; : > "{st}4"; sleep 2; '
                  f'printf "\\033[H\\033[2J"; cat "{img}"; printf "\\033[1;1HXXXX"; : > "{st}5"; sleep 30')
        self.start("--geometry", "100x30", "-x", "sh", "-c", script)
        self.wait_window()
        full = 200 * 120
        hits = {}
        for k in range(1, 6):
            end = time.time() + 15
            while not os.path.exists(f"{st}{k}") and time.time() < end:
                time.sleep(0.05)
            time.sleep(0.8)
            hits[k] = self.count(self.window_area(self.screenshot(f"sixel-text-{k}")), (0, 255, 0))
        self.assertGreaterEqual(hits[1], full * 0.95, "image on the normal screen")
        self.assertEqual(hits[2], 0, "image drawn over the alternate screen")
        self.assertGreaterEqual(hits[3], full * 0.95, "image back after leaving the alternate screen")
        self.assertEqual(hits[4], 0, "image drawn over text written over it (top)")
        self.assertTrue(full * 0.5 < hits[5] < full * 0.99, f"partly overwritten image: {hits[5]}")

    def test_fastfetch_logo_image(self):
        """fastfetch s logem LuxOS jako obrazkem (jako bashrc v Terminalu LuxOS)."""
        if not has_sixel():
            self.skipTest("VTE without SIXEL (needs vte3 from [luxos])")
        conf = os.path.join(ROOT, "packages/luxos-shell/files/fastfetch/config.jsonc")
        if not logo_source() or not shutil.which("fastfetch") or not os.path.isfile(conf):
            self.skipTest("needs fastfetch, the LuxOS source tree and an SVG loader")
        self.config("[terminal]\ntheme=dark\n")
        env = dict(self.env, LUXOS_TERMINAL_LOGO_SOURCE=logo_source())
        self.start("-x", "sh", "-c", f'fastfetch -c "{conf}" --logo-type raw --logo "$LUXOS_TERMINAL_LOGO"; sleep 30',
                   env=env)
        self.wait_window()
        end = time.time() + 10
        while time.time() < end:
            time.sleep(0.5)
            pb = self.screenshot()
            data, rs, n = pb.get_pixels(), pb.get_rowstride(), pb.get_n_channels()
            blue = 0
            # pole loga vlevo nahore (31x12 bunek, okraj 3 radky / 2 sloupce)
            for y in range(40, min(pb.get_height(), 400)):
                for x in range(0, min(pb.get_width(), 330)):
                    i = y * rs + x * n
                    if data[i + 2] > data[i] + 40 and data[i + 2] > 150:
                        blue += 1
            if blue > 3000:
                break
        self.screenshot("fastfetch-logo")
        self.assertGreater(blue, 3000, "LuxOS logo image not drawn")
        caches = os.listdir(os.path.join(self.home, ".cache", "luxos", "terminal"))
        self.assertTrue(any(c.endswith("-dark.six") for c in caches), caches)

    def x_server_ticks(self):
        """Cas CPU (tiky) X serveru teto virtualni obrazovky."""
        disp = os.environ["DISPLAY"]
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmd = f.read().split(b"\0")
                if os.path.basename(cmd[0]) == b"Xvfb" and disp.encode() in cmd:
                    with open(f"/proc/{pid}/stat") as f:
                        st = f.read().rsplit(")", 1)[1].split()
                    return int(st[11]) + int(st[12])
            except (OSError, IndexError):
                continue
        self.skipTest("Xvfb process not found")

    def test_x_server_load_with_image(self):
        """Obrazek na obrazovce nesmi zatezovat X server: necinnost (blikajici kurzor) ~0,
        pravidelny vystup vedle obrazku omezeny (regrese: zatizeni X a zamrznuti relace)."""
        if not has_sixel():
            self.skipTest("VTE without SIXEL (needs vte3 from [luxos])")
        img = os.path.join(self.home, "big.six")
        with open(img, "w") as f:
            f.write(sixel_square(600, 300, (20, 60, 90)))
        go = os.path.join(self.home, "go")
        self.start("-x", "sh", "-c", f'cat "{img}"; echo; while [ ! -e "{go}" ]; do sleep 0.2; done; '
                   'i=0; while [ $i -lt 100 ]; do printf "\\r%s" $i; i=$((i+1)); sleep 0.1; done; sleep 30')
        self.wait_window()
        time.sleep(2)
        hz = os.sysconf("SC_CLK_TCK")
        t0 = self.x_server_ticks()
        time.sleep(10)
        idle = (self.x_server_ticks() - t0) / hz / 10 * 100
        open(go, "w").close()
        t0 = self.x_server_ticks()
        time.sleep(8)
        busy = (self.x_server_ticks() - t0) / hz / 8 * 100
        self.screenshot("x-load")
        print(f"\nX server CPU: idle {idle:.1f} %, output every 100 ms {busy:.1f} %", file=sys.stderr)
        self.assertLess(idle, 2.0, f"X server CPU while idle: {idle:.1f} %")
        self.assertLess(busy, 25.0, f"X server CPU with output every 100 ms: {busy:.1f} %")

    def test_open_close_stress(self):
        """Opakovane otevirani a zavirani panelu a oken v jednom procesu (regrese: pad pri zavirani -
        uvolneny Win v signalech panelu pri ruseni okna). Uvolnena pamet se prepisuje (MALLOC_PERTURB_),
        takze pristup k ni spadne; proces musi skoncit s kodem 0 a bez varovani."""
        env = dict(self.env, MALLOC_PERTURB_="165", MALLOC_CHECK_="3", G_SLICE="always-malloc",
                   G_DEBUG="fatal-criticals")
        env.pop("LUXOS_TERMINAL_NEW_PROCESS")
        err = os.path.join(self.home, "stderr")
        with open(err, "w") as ef:
            main = self.start("-x", "sh", "-c", "sleep 9", env=env, stderr=ef)
            self.wait_window()
            for i in range(6):
                for args in (["--tab", "-x", "sleep", "0.2"], ["-x", "sleep", "0.2"], ["--tab", "-x", "true"],
                             ["-T", "w", "-x", "sh", "-c", "sleep 0.4"]):
                    subprocess.run([BIN, *args], env=env, timeout=10, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                time.sleep(0.5)
            rc = main.wait(30)
        text = read(err)
        self.assertEqual(rc, 0, text)
        for bad in ("CRITICAL", "WARNING", "free()", "corrupted"):
            self.assertNotIn(bad, text, text)

    def test_sixel_disabled_by_config(self):
        if not has_sixel():
            self.skipTest("VTE without SIXEL (needs vte3 from [luxos])")
        self.config("[terminal]\ntheme=dark\nsixel=false\n")
        img = os.path.join(self.home, "green.six")
        with open(img, "w") as f:
            f.write(sixel_square(96, 60, (0, 100, 0)))
        self.start("-x", "sh", "-c", f'cat "{img}"; sleep 30')
        self.wait_window()
        time.sleep(1.5)
        self.assertLess(self.count(self.screenshot("sixel-off"), (0, 255, 0)), 100)


if __name__ == "__main__":
    unittest.main()
