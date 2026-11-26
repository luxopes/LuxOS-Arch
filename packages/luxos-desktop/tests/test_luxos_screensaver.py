#!/usr/bin/env python3
"""LuxOS - setric obrazovky (luxos-screensaver v LSL, /usr/lib/xfce4-screensaver/luxos): styly, tapeta plochy,
rucickove hodiny, kresleni do okna xfce4-screensaver (XSCREENSAVER_WINDOW) a vlastni okno.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_screensaver.py -v

xfconf-query je falesny program v PATH; snimky stylu se kresli bez obrazovky (--render, --hands,
--analog-dirty), okna jen ve vlastnim Xvfb (lsl_app, nikdy na skutecne obrazovce). Okno xfce4-screensaver
nahrazuje okno GDK s cervenym pozadim (cervena = setric nekreslil). PSS proti puvodnimu programu v Pythonu
(6e718756), kdyz je k dispozici git a PyGObject.
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
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.normpath(os.path.join(HERE, "..", "files"))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
WALLS = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-branding", "files", "wallpapers"))
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

TMP = tempfile.mkdtemp(prefix="luxos-screensaver-test-")
STYLES = ["desktop", "wallpapers", "analog", "clock", "aurora", "photos", "logo", "blank"]
SLIDE = 20.0
ANALOG_SLIDE = 30.0
ANALOG_FADE = 2.5
BIN = {}


def setUpModule():
    BIN["saver"] = lsl_app.build("luxos-screensaver", TMP)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def pixels(path):
    """PNG -> (sirka, vyska, kanaly, bajty) pres GdkPixbuf."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file(path)
    return pb.get_width(), pb.get_height(), pb.get_n_channels(), pb.get_rowstride(), pb.get_pixels()


def region_stats(path, x, y, w, h):
    """[prumer zelene, podil cervenych pixelu (pozadi okna = setric nekreslil), pocet ruznych barev] v obdelniku."""
    _w, _h, n, stride, px = pixels(path)
    total = red = green = 0
    colors = set()
    for yy in range(y, y + h, 4):
        row = yy * stride
        for xx in range(x, x + w, 4):
            i = row + xx * n
            r, g, b = px[i], px[i + 1], px[i + 2]
            total += 1
            green += g
            red += r > 240 and g < 15 and b < 15
            colors.add((r >> 3, g >> 3, b >> 3))
    return green / total, red / total, len(colors)


class Env:
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="saver-", dir=TMP)
        fake = os.path.join(self.tmp, "fake")
        os.makedirs(fake)
        self.listing = os.path.join(self.tmp, "desktop")
        with open(os.path.join(fake, "xfconf-query"), "w") as f:
            f.write('#!/bin/sh\n[ "$*" = "-c xfce4-desktop -l -v" ] && cat "$FAKE_DESKTOP" 2>/dev/null\nexit 0\n')
        with open(os.path.join(fake, "xdg-user-dir"), "w") as f:
            f.write('#!/bin/sh\necho "$FAKE_PICTURES"\n')
        for name in ("xfconf-query", "xdg-user-dir"):
            os.chmod(os.path.join(fake, name), 0o755)
        self.cfg = os.path.join(self.tmp, "cfg")
        self.env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "XSCREENSAVER_WINDOW")}
        self.env.update({"PATH": fake + ":" + os.environ.get("PATH", "/usr/bin:/bin"), "FAKE_DESKTOP": self.listing,
                         "XDG_CONFIG_HOME": self.cfg, "HOME": self.tmp, "LUXOS_SCREENSAVER_WALLS": WALLS,
                         "FAKE_PICTURES": os.path.join(self.tmp, "nopics"), "LANG": "en_US.UTF-8",
                         "LUXOS_GREETER_CONF": os.path.join(self.tmp, "greeter.conf"), "LC_ALL": "", "LC_TIME": ""})
        self.light = os.path.join(WALLS, "luxos-flow-light.jpg")
        self.dark = os.path.join(WALLS, "luxos-flow-dark.jpg")

    def run_saver(self, *args):
        r = subprocess.run([BIN["saver"], *args], env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def props(self, d):
        with open(self.listing, "w") as f:
            for k, v in d.items():
                f.write(f"/backdrop/screen0/{k}/last-image     {v}\n/backdrop/screen0/{k}/image-style    5\n")

    def appearance(self, mode):
        os.makedirs(os.path.join(self.cfg, "luxos"), exist_ok=True)
        with open(os.path.join(self.cfg, "luxos", "appearance"), "w") as f:
            f.write(mode + "\n")


class DesktopWallpaper(Env, unittest.TestCase):
    def wallpaper(self, monitor=None):
        return self.run_saver("--wallpaper", *([monitor] if monitor else [])).strip()

    def test_monitor_workspace0(self):
        self.props({"monitorHDMI-1/workspace0": self.dark, "monitoreDP-1/workspace0": self.light,
                    "monitoreDP-1/workspace1": self.dark})
        self.assertEqual(self.wallpaper("eDP-1"), self.light)
        self.assertEqual(self.wallpaper("HDMI-1"), self.dark)

    def test_unknown_monitor_uses_another(self):
        self.props({"monitoreDP-1/workspace0": self.light})
        self.assertEqual(self.wallpaper("DP-3"), self.light)
        self.assertEqual(self.wallpaper(None), self.light)

    def test_monitor_without_workspace_before_others(self):
        self.props({"monitorHDMI-1": self.dark, "monitoreDP-1/workspace0": self.light})
        self.assertEqual(self.wallpaper("HDMI-1"), self.dark)
        self.assertEqual(self.wallpaper("DP-9"), self.light)       # workspace0 jineho monitoru pred holym

    def test_missing_file_and_mode_fallback(self):
        self.props({"monitoreDP-1/workspace0": "/nonexistent/x.jpg"})
        self.assertEqual(self.wallpaper("eDP-1"), "/usr/share/backgrounds/luxos/luxos-light.jpg")
        self.appearance("dark")
        self.assertEqual(self.wallpaper("eDP-1"), "/usr/share/backgrounds/luxos/luxos-dark.jpg")

    def test_draw_shows_desktop_wallpaper_still(self):
        # styl desktop: stejna tapeta, nemeni se v case (zadne prolinani ani pohyb)
        self.props({"monitor0/workspace0": self.light})
        self.assertEqual(self.run_saver("--info", "desktop").split(), ["desktop", "1", "1"])
        a, b = os.path.join(self.tmp, "a.png"), os.path.join(self.tmp, "b.png")
        self.run_saver("--render", "desktop", "320", "200", a, "0")
        self.run_saver("--render", "desktop", "320", "200", b, str(SLIDE + 5))   # ve stylu wallpapers uz jina tapeta
        pa, pb = pixels(a)[4], pixels(b)[4]
        n = pixels(a)[2]
        diff = sum(1 for i in range(0, len(pa), n) if pa[i:i + 3] != pb[i:i + 3])
        self.assertLess(diff, len(pa) // n // 10)   # zmeni se nejvys hodiny
        # svetla tapeta (po ztmaveni pro hodiny) je jasnejsi nez tmava LuxOS
        self.assertGreater(region_stats(a, 0, 0, 320, 200)[0], 100)
        self.assertEqual(self.run_saver("--info", "wallpapers").split()[:2], ["wallpapers", "15"])

    def test_unknown_style_is_desktop(self):
        self.props({})
        self.assertEqual(self.run_saver("--info", "nonsense").split()[0], "desktop")

    def test_greeter_clock_format(self):
        # vlastni format hodin luxos-greeter (24h, sekundy) - hodiny vypadaji jinak nez vychozi 12h
        self.props({"monitor0/workspace0": self.light})
        a, b = os.path.join(self.tmp, "a.png"), os.path.join(self.tmp, "b.png")
        self.run_saver("--render", "desktop", "640", "400", a)
        with open(self.env["LUXOS_GREETER_CONF"], "w") as f:
            f.write("[greeter]\nclock-format = %H:%M:%S\ndate-format = [%Y]\n")
        self.run_saver("--render", "desktop", "640", "400", b)
        self.assertNotEqual(pixels(a)[4], pixels(b)[4])


class Slides(Env, unittest.TestCase):
    def test_wallpapers_without_duplicates_and_defaults(self):
        d = os.path.join(self.tmp, "walls")
        os.makedirs(d)
        for name in ("luxos-a.jpg", "luxos-b.jpg", "luxos-dark.jpg", "luxos-light.jpg", "other.jpg", "luxos-c.png"):
            shutil.copy(self.light, os.path.join(d, name))
        os.symlink("luxos-a.jpg", os.path.join(d, "luxos-z.jpg"))
        self.env["LUXOS_SCREENSAVER_WALLS"] = d
        self.assertEqual(self.run_saver("--walls").split(), [os.path.join(d, "luxos-a.jpg"), os.path.join(d, "luxos-b.jpg")])
        self.assertEqual(self.run_saver("--styles").split(), STYLES)

    def test_photos_from_pictures_or_wallpapers(self):
        self.assertEqual(self.run_saver("--info", "photos").split(), ["photos", "15", str(len(os.listdir(WALLS)))])
        pics = os.path.join(self.tmp, "Fotky")
        os.makedirs(os.path.join(pics, "2026", "leto"))
        shutil.copy(self.light, os.path.join(pics, "a.JPG"))
        shutil.copy(self.dark, os.path.join(pics, "2026", "leto", "b.webp"))
        with open(os.path.join(pics, "notes.txt"), "w") as f:
            f.write("x")
        os.symlink(os.path.join(pics, "2026"), os.path.join(pics, "loop"))    # odkaz na slozku se neprochazi
        self.env["FAKE_PICTURES"] = pics
        self.assertEqual(self.run_saver("--info", "photos").split(), ["photos", "15", "2"])
        out = os.path.join(self.tmp, "p.png")
        self.run_saver("--render", "photos", "320", "200", out, "1")
        self.assertGreater(region_stats(out, 0, 0, 320, 200)[2], 50)

    def test_every_style_renders(self):
        self.props({"monitor0/workspace0": self.light})
        for style in STYLES:
            out = os.path.join(self.tmp, style + ".png")
            self.run_saver("--render", style, "320", "200", out, "2")
            green, _red, colors = region_stats(out, 0, 0, 320, 200)
            if style == "blank":
                self.assertEqual((green, colors), (0, 1))
            else:
                self.assertGreater(colors, 3, style)


class Fade(Env, unittest.TestCase):
    """Prolinani tapet: tapety se nesmi dekodovat znovu pri kazdem snimku (cukani) a prolinani jede plynule."""

    def test_wallpapers_decoded_once_each_over_several_transitions(self):
        # 130 s = ctyri prechody; kazda tapeta nejvys jednou (cache vyhazovala aktualni misto nejstarsi:
        # od druheho prechodu desitky dekodovani, kazde ~280 ms)
        out = self.run_saver("--cache-test", "wallpapers", "640", "360", "130").split()
        slides, decodes = int(out[3]), int(out[5])
        self.assertGreater(slides, 3)
        self.assertLessEqual(decodes, 7, out)

    def test_fade_runs_at_60_fps_and_otherwise_slow(self):
        self.assertEqual(self.run_saver("--info", "wallpapers").split()[:2], ["wallpapers", "15"])


class Analog(Env, unittest.TestCase):
    """Styl "analog": tapety LuxOS s prolinanim a rucickove hodiny; mimo prolinani jen ctverec s hodinami."""

    def test_fps(self):
        self.assertEqual(self.run_saver("--info", "analog").split()[:2], ["analog", "20"])

    def test_only_clock_redrawn_between_fades(self):
        out = self.run_saver("--analog-dirty", "320", "200").splitlines()
        self.assertEqual(out[0], "first full")                 # prvni snimek cely
        m = re.match(r"box \[(\d+), (\d+), (\d+), (\d+)\] \[([\d.]+), ([\d.]+), ([\d.]+)\]", out[1])
        self.assertTrue(m, out[1])
        x, y, bw, bh = (int(v) for v in m.groups()[:4])
        cx, cy, r = (float(v) for v in m.groups()[4:])
        self.assertTrue(x <= cx - r and y <= cy - r and x + bw >= cx + r and y + bh >= cy + r, out[1])
        self.assertLess(bw * bh, 320 * 200 / 2)
        self.assertEqual(out[2], "fade full")                  # prolinani: cela obrazovka

    def test_hands_move_and_light_dark(self):
        def hands(dark, now):
            path = os.path.join(self.tmp, "h-%d-%s.png" % (dark, now))
            face = self.run_saver("--hands", str(dark), repr(now), path).strip()
            return pixels(path)[4], face
        t = 1_800_000_000.0
        light, light_face = hands(0, t)
        self.assertNotEqual(light, hands(0, t + 1.0)[0])        # vterinova rucicka
        self.assertNotEqual(light, hands(0, t + 0.25)[0])       # plynule, ne skokem po vterinach
        self.assertEqual(light, hands(0, t)[0])
        dark, dark_face = hands(1, t)
        self.assertNotEqual(light, dark)                        # svetle / tmave rucicky
        self.assertNotEqual(light_face, dark_face)

    def test_draw_full_screen_image(self):
        out = os.path.join(self.tmp, "a.png")
        self.run_saver("--render", "analog", "320", "200", out)
        self.assertGreater(region_stats(out, 0, 0, 320, 200)[0], 20)       # tapeta, ne cerna
        self.appearance("dark")
        out2 = os.path.join(self.tmp, "b.png")
        self.run_saver("--render", "analog", "320", "200", out2)
        # ciselnik uprostred: svetly kotouc je jasnejsi nez tmavy
        self.assertGreater(region_stats(out, 150, 60, 20, 20)[0], region_stats(out2, 150, 60, 20, 20)[0])


class Defaults(unittest.TestCase):
    def test_default_theme_is_changing_wallpapers(self):
        # owner 2026-11-22 (item 42): stridajici se tapety LuxOS; X11 (xfce4-screensaver), klid zamku na Waylandu
        # (luxos-lock: chybejici seznam i nezname tema) a stranka Nastaveni maji stejnou vychozi hodnotu
        tree = ET.parse(os.path.join(FILES, "xdg", "xfce4", "xfconf", "xfce-perchannel-xml", "xfce4-screensaver.xml"))
        values = [v.get("value") for v in tree.iter("value")]
        self.assertEqual(values, ["screensavers-luxos"])
        with open(os.path.join(FILES, "screensaver", "luxos.desktop")) as f:
            self.assertIn("Exec=/usr/lib/xfce4-screensaver/luxos --style wallpapers\n", f.read())
        with open(os.path.join(FILES, "lsl", "luxos_page_lock.lsl")) as f:
            src = f.read()
        self.assertIn('["screensavers-luxos", "wallpapers", "LuxOS - wallpapers and clock"]', src)
        self.assertIn('current = "screensavers-luxos"\n', src)
        with open(os.path.join(FILES, "lsl", "luxos_saver.lsl")) as f:
            saver = f.read()
        self.assertIn('DEFAULT_STYLE = "wallpapers"\n', saver)
        self.assertIn('"screensavers-luxos": "wallpapers"', saver)
        with open(os.path.join(FILES, "lsl", "luxos-lock.lsl")) as f:
            self.assertIn("style = saver.DEFAULT_STYLE\n", f.read())
        # kazdy styl z nastaveni existuje v setrici a ma .desktop soubor
        for theme, style in re.findall(r'\["(screensavers-[a-z-]+)", "([a-z]+)"', src):
            self.assertIn(style, STYLES)
            name = theme[len("screensavers-"):] + ".desktop"
            with open(os.path.join(FILES, "screensaver", name)) as f:
                self.assertIn(f"--style {style}\n", f.read())

    def test_built_and_installed(self):
        with open(os.path.join(HERE, "..", "PKGBUILD")) as f:
            pkg = f.read()
        self.assertIn('"$startdir/files/lsl/luxos-screensaver.lsl" luxos-screensaver', pkg)
        self.assertIn('install -Dm755 luxos-screensaver "$pkgdir/usr/lib/xfce4-screensaver/luxos"', pkg)
        self.assertFalse(os.path.exists(os.path.join(FILES, "screensaver", "luxos-screensaver")))


class LockDefaults(unittest.TestCase):
    """Bezpecnost: sporic zamyka hned (0 min). S 1 minutou Enter po spusteni sporice pustil na plochu."""

    def test_lock_immediately(self):
        root = ET.parse(os.path.join(FILES, "xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-screensaver.xml")).getroot()
        lock = root.find("./property[@name='lock']")
        self.assertEqual(lock.find("./property[@name='enabled']").get("value"), "true")
        sa = lock.find("./property[@name='saver-activation']")
        self.assertEqual(sa.find("./property[@name='enabled']").get("value"), "true")
        self.assertEqual(sa.find("./property[@name='delay']").get("value"), "0")
        self.assertEqual(lock.find("./property[@name='sleep-activation']").get("value"), "true")

    def test_running_sessions_migrated(self):
        with open(os.path.join(HERE, "..", "luxos-desktop.install")) as f:
            inst = f.read()
        self.assertIn("_luxos_lock_now", inst.split("post_upgrade()")[1].splitlines()[0])


# Okno xfce4-screensaver: GDK okno 800x500 na 0,0 s cervenym pozadim; prikazy na stdin hide/show
FOREIGN = r"""
import sys, gi
gi.require_version("Gdk", "3.0"); gi.require_version("GdkX11", "3.0")
from gi.repository import Gdk, GdkX11, GLib
Gdk.init([])
a = Gdk.WindowAttr()
a.x, a.y, a.width, a.height = 0, 0, 800, 500
a.window_type = Gdk.WindowType.TOPLEVEL
a.wclass = Gdk.WindowWindowClass.INPUT_OUTPUT
w = Gdk.Window.new(None, a, Gdk.WindowAttributesType.X | Gdk.WindowAttributesType.Y)
w.set_background_rgba(Gdk.RGBA(1, 0, 0, 1))
w.show()
Gdk.flush()
print("0x%x" % w.get_xid(), flush=True)
def cmd(src, cond):
    line = sys.stdin.readline().strip()
    if line == "hide": w.hide()
    elif line == "show": w.show()
    elif line in ("", "quit"): GLib.MainLoop.quit(loop); return False
    Gdk.flush(); print("ok", flush=True)
    return True
GLib.io_add_watch(sys.stdin, GLib.IO_IN, cmd)
loop = GLib.MainLoop(); loop.run()
"""


def pss_kb(pid):
    total = 0
    for p in [pid] + children(pid):
        try:
            with open("/proc/%d/smaps_rollup" % p) as f:
                for line in f:
                    if line.startswith("Pss:"):
                        total += int(line.split()[1])
        except OSError:
            pass
    return total


def children(pid):
    try:
        with open("/proc/%d/task/%d/children" % (pid, pid)) as f:
            return [int(v) for v in f.read().split()]
    except OSError:
        return []


class Windows(Env, unittest.TestCase):
    """Kresleni ve vlastnim Xvfb: okno xfce4-screensaver (XSCREENSAVER_WINDOW) a vlastni okno (nahled)."""

    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("GdkX11", "3.0")
        except (ImportError, ValueError):
            raise unittest.SkipTest("PyGObject s GdkX11 chybi (okno xfce4-screensaver v testu)")
        cls.x = lsl_app.Xvfb("1024x640")
        cls.procs = []

    @classmethod
    def tearDownClass(cls):
        cls.x.stop()

    def setUp(self):
        super().setUp()
        self.env["DISPLAY"] = self.x.display
        self.env.pop("XAUTHORITY", None)
        self.props({"monitor0/workspace0": self.light, "monitorscreen/workspace0": self.light})
        self.started = []

    def tearDown(self):
        for p in self.started:
            if p.poll() is None:
                p.kill()
            p.wait(5)

    def start(self, argv, env=None, stdin=None):
        p = subprocess.Popen(argv, env=env or self.env, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True)
        self.started.append(p)
        return p

    def foreign(self):
        p = self.start([sys.executable, "-c", FOREIGN], stdin=subprocess.PIPE)
        xid = p.stdout.readline().strip()
        self.assertTrue(xid.startswith("0x"), p.stderr.read() if p.poll() is not None else xid)
        return p, xid

    def shot(self, name):
        path = os.path.join(self.tmp, name + ".png")
        lsl_app.shot(self.x.display, path)
        return path

    def saver_in(self, xid, style, argv=None):
        env = dict(self.env, XSCREENSAVER_WINDOW=xid)
        return self.start(argv or [BIN["saver"], "--style", style], env)

    def wait_drawn(self, timeout=6.0):
        end = time.monotonic() + timeout
        while True:
            stats = region_stats(self.shot("w"), 0, 0, 800, 500)
            if stats[1] < 0.02 or time.monotonic() > end:
                return stats
            time.sleep(0.2)

    def test_draws_every_style_into_screensaver_window(self):
        for style in STYLES:
            with self.subTest(style=style):
                win, xid = self.foreign()
                saver = self.saver_in(xid, style)
                green, red, colors = self.wait_drawn()
                self.assertLess(red, 0.02, style)                 # okno cele prekreslene
                if style == "blank":
                    self.assertEqual(colors, 1)
                else:
                    self.assertGreater(colors, 3, style)
                # mimo okno nic (setric kresli jen do sveho okna)
                outside = region_stats(self.shot("o"), 820, 520, 200, 110)
                self.assertEqual(outside[2], 1)
                t0 = time.monotonic()
                saver.send_signal(signal.SIGTERM)
                saver.wait(5)
                self.assertLess(time.monotonic() - t0, 2)
                win.stdin.write("quit\n")
                win.stdin.flush()
                win.wait(5)

    def test_redraws_after_window_shown_again(self):
        # desktop kresli 1 snimek/s: po odkryti (Expose/MapNotify) hned cela obrazovka, ne az pristi sekundu
        win, xid = self.foreign()
        self.saver_in(xid, "desktop")
        self.assertLess(self.wait_drawn()[1], 0.02)
        for _ in range(3):
            win.stdin.write("hide\n")
            win.stdin.flush()
            win.stdout.readline()
            time.sleep(0.3)
            win.stdin.write("show\n")
            win.stdin.flush()
            win.stdout.readline()
            time.sleep(0.35)
            green, red, _c = region_stats(self.shot("r"), 0, 0, 800, 500)
            self.assertLess(red, 0.02)
            self.assertGreater(green, 100)        # svetla tapeta plochy

    def test_bad_window_exits(self):
        p = self.saver_in("0x7ffffff", "desktop")
        try:
            rc = p.wait(10)
        except subprocess.TimeoutExpired:
            rc = None
        self.assertNotEqual(rc, None)
        self.assertNotEqual(rc, 0)

    def test_preview_window(self):
        # nahled z Nastaveni zamku: --window na celou obrazovku, klavesa ho zavre
        p = self.start([BIN["saver"], "--window", "--style", "aurora"])
        time.sleep(1.5)
        _g, _r, colors = region_stats(self.shot("p"), 0, 0, 1024, 640)
        self.assertGreater(colors, 20)
        subprocess.run(["xdotool", "key", "space"], env=self.env, timeout=10) if shutil.which("xdotool") else p.terminate()
        self.assertIsNotNone(p.wait(5))

    def test_small_window_without_argument(self):
        p = self.start([BIN["saver"], "--style", "clock"])
        time.sleep(1.0)
        self.assertIsNone(p.poll())
        _g, _r, colors = region_stats(self.shot("s"), 0, 0, 1024, 640)
        self.assertGreater(colors, 1)
        p.terminate()
        p.wait(5)

    def test_pss_lower_than_python(self):
        script = os.path.join(TMP, "luxos-screensaver.py")
        r = subprocess.run(["git", "-C", REPO, "show", "6e718756:packages/luxos-desktop/files/screensaver/luxos-screensaver"],
                           capture_output=True, text=True)
        if r.returncode:
            self.skipTest("puvodni program v Pythonu neni v gitu")
        with open(script, "w") as f:
            f.write(r.stdout)
        results = {}
        for style in ("desktop", "analog", "aurora"):
            for kind, argv in (("lsl", [BIN["saver"], "--style", style]), ("python", [sys.executable, script, "--style", style])):
                win, xid = self.foreign()
                p = self.saver_in(xid, style, argv)
                self.wait_drawn()
                time.sleep(3)
                results[(style, kind)] = pss_kb(p.pid)
                p.kill()
                p.wait(5)
                win.stdin.write("quit\n")
                win.stdin.flush()
                win.wait(5)
        print("\nPSS kB (Xvfb 1024x640, okno 800x500): " + ", ".join(
            "%s %s %d" % (s, k, v) for (s, k), v in sorted(results.items())), file=sys.stderr)
        for style in ("desktop", "analog", "aurora"):
            self.assertGreater(results[(style, "lsl")], 1000, style)          # bezi (mrtvy proces ma 0)
            self.assertLess(results[(style, "lsl")], results[(style, "python")], style)


if __name__ == "__main__":
    unittest.main()
