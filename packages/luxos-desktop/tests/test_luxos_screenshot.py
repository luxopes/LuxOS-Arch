"""Testy pro luxos-screenshot: nazvy souboru, volby, ffmpeg a (pod Xvfb) lista, snimky a nahravani.

Spusteni:  python3 -m unittest discover -s packages/luxos-desktop/tests -v
GUI cast:  xvfb-run -a -s "-screen 0 1280x800x24" python3 -m unittest packages/luxos-desktop/tests/test_luxos_screenshot.py -v
LUXOS_SHOT_DIR=/slozka ulozi snimky listy (svetla/tmava) pro vizualni kontrolu.
"""
import datetime as dt
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "files", "bin", "luxos-screenshot")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
TMP = tempfile.mkdtemp(prefix="luxos-shot-test-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "config")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(TMP, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ["LANG"] = "en_US.UTF-8"
os.environ.pop("LC_ALL", None)
os.environ.pop("LC_MESSAGES", None)
sys.path.insert(0, I18N)

# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM) - nikdy skutecna obrazovka
# vyvojare: testy zachytavaji a nahravaji obrazovku
HAVE_DISPLAY = bool(os.environ.get("DISPLAY")) and (
    "xvfb-run" in os.environ.get("XAUTHORITY", "") or os.environ.get("LUXOS_TEST_X") == "1")
shot = None
if HAVE_DISPLAY:
    loader = importlib.machinery.SourceFileLoader("luxos_screenshot", BIN)
    spec = importlib.util.spec_from_loader("luxos_screenshot", loader)
    shot = importlib.util.module_from_spec(spec)
    loader.exec_module(shot)
else:
    # Bez X nelze nacist GTK cast: cist jen funkce nad radkem "# ---- GTK"
    with open(BIN, encoding="utf-8") as f:
        src = f.read().split("# ---- GTK")[0]
    shot = type(sys)("luxos_screenshot")
    shot.__file__ = BIN
    exec(compile(src, BIN, "exec"), shot.__dict__)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


class TestNames(unittest.TestCase):
    def test_file_name(self):
        when = dt.datetime(2026, 10, 22, 11, 12, 3)
        self.assertEqual(shot.file_name(when), "Screenshot 2026-10-22 at 11.12.03.png")
        self.assertEqual(shot.file_name(when, video=True), "Screen Recording 2026-10-22 at 11.12.03.mp4")

    def test_file_name_translated(self):
        when = dt.datetime(2026, 1, 2, 3, 4, 5)
        orig = shot._
        try:
            shot._ = {"Screenshot %s at %s": "Snímek obrazovky %s v %s"}.get
            shot._ = (lambda f: lambda t: f(t) or t)(shot._)
            self.assertEqual(shot.file_name(when), "Snímek obrazovky 2026-01-02 v 03.04.05.png")
            # Poskozeny preklad (chybi %s) nesmi shodit program
            shot._ = lambda t: "Broken %d" if "%s" in t else t
            self.assertEqual(shot.file_name(when), "Screenshot 2026-01-02 at 03.04.05.png")
            shot._ = lambda t: "A/B %s %s" if "%s" in t else t
            self.assertNotIn("/", shot.file_name(when))
        finally:
            shot._ = orig

    def test_unique_path(self):
        d = tempfile.mkdtemp(dir=TMP)
        self.assertEqual(shot.unique_path(d, "a b.png"), os.path.join(d, "a b.png"))
        open(os.path.join(d, "a b.png"), "w").close()
        self.assertEqual(shot.unique_path(d, "a b.png"), os.path.join(d, "a b (2).png"))
        open(os.path.join(d, "a b (2).png"), "w").close()
        self.assertEqual(shot.unique_path(d, "a b.png"), os.path.join(d, "a b (3).png"))


class TestOptions(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(dir=TMP), "luxos", "screenshot.json")

    def test_defaults_when_missing(self):
        self.assertEqual(shot.load_options(self.path), shot.DEFAULTS)

    def test_roundtrip(self):
        other = tempfile.mkdtemp(dir=TMP)
        o = dict(shot.DEFAULTS, save_to="other", other_dir=other, timer=10, pointer=True, remember=False,
                 selection=[1, 2, 30, 40], mode="rec_portion")
        shot.save_options(o, self.path)
        self.assertEqual(shot.load_options(self.path), o)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_invalid_values(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            json.dump({"save_to": "nowhere", "timer": 7, "pointer": "yes", "remember": 1,
                       "selection": [0, 0, 0, 10], "mode": "x", "other_dir": 5}, f)
        self.assertEqual(shot.load_options(self.path), shot.DEFAULTS)
        with open(self.path, "w") as f:
            json.dump({"timer": True, "selection": [True, 0, 5, 5]}, f)
        self.assertEqual(shot.load_options(self.path), shot.DEFAULTS)
        with open(self.path, "w") as f:
            f.write("{broken")
        self.assertEqual(shot.load_options(self.path), shot.DEFAULTS)
        with open(self.path, "w") as f:
            f.write("[1, 2]")
        self.assertEqual(shot.load_options(self.path), shot.DEFAULTS)

    def test_other_without_dir_falls_back(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            json.dump({"save_to": "other"}, f)
        self.assertEqual(shot.load_options(self.path)["save_to"], "desktop")

    def test_save_dir(self):
        o = dict(shot.DEFAULTS)
        self.assertIsNone(shot.save_dir(dict(o, save_to="clipboard")))
        # video do schranky nejde -> plocha
        self.assertEqual(shot.save_dir(dict(o, save_to="clipboard"), video=True), shot.user_dir("desktop"))
        self.assertEqual(shot.save_dir(dict(o, save_to="pictures")), shot.user_dir("pictures"))
        d = tempfile.mkdtemp(dir=TMP)
        self.assertEqual(shot.save_dir(dict(o, save_to="other", other_dir=d)), d)
        # smazana jina slozka -> plocha
        self.assertEqual(shot.save_dir(dict(o, save_to="other", other_dir=d + "-gone")), shot.user_dir("desktop"))
        self.assertEqual(shot.save_dir(dict(o, save_to="clipboard"), override=d), d)
        self.assertNotEqual(os.path.realpath(shot.user_dir("desktop")), os.path.realpath(os.path.expanduser("~")))


class TestGeometry(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(shot.clamp_rect((10, 20, 30, 40), 100, 100), (10, 20, 30, 40))
        self.assertEqual(shot.clamp_rect((-10, -10, 30, 40), 100, 100), (0, 0, 20, 30))
        self.assertEqual(shot.clamp_rect((90, 90, 30, 40), 100, 100), (90, 90, 10, 10))
        self.assertEqual(shot.clamp_rect((50, 50, -20, -10), 100, 100), (30, 40, 20, 10))   # tazeni doleva nahoru
        self.assertIsNone(shot.clamp_rect((200, 0, 10, 10), 100, 100))
        self.assertIsNone(shot.clamp_rect((5, 5, 0, 10), 100, 100))

    def test_parse_region(self):
        self.assertEqual(shot.parse_region("10,20,300,200"), (10, 20, 300, 200))
        self.assertEqual(shot.parse_region(" 1, 2 ,3,4 "), (1, 2, 3, 4))
        for bad in ("", "1,2,3", "1,2,0,4", "a,b,c,d", "1,2,-3,4", None):
            self.assertIsNone(shot.parse_region(bad), bad)


class TestFfmpeg(unittest.TestCase):
    LIST = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D libx264rgb           libx264 H.264 RGB (codec h264)
 V.S..D mpeg4                MPEG-4 part 2
"""

    def test_prefers_h264(self):
        self.assertEqual(shot.pick_encoder(self.LIST)[:2], ["-c:v", "libx264"])

    def test_fallbacks(self):
        no264 = "\n".join(line for line in self.LIST.splitlines() if "libx264" not in line)
        self.assertEqual(shot.pick_encoder(no264)[:2], ["-c:v", "mpeg4"])
        self.assertEqual(shot.pick_encoder(" V....D libopenh264  OpenH264\n V.S..D mpeg4  x\n")[:2],
                         ["-c:v", "libopenh264"])
        self.assertIsNone(shot.pick_encoder(" A....D aac  AAC\n"))
        self.assertIsNone(shot.pick_encoder(""))
        # libx264rgb samotny neni libx264 (jine pixely)
        self.assertIsNone(shot.pick_encoder(" V....D libx264rgb  x\n"))

    def test_cmd_even_size(self):
        cmd = shot.ffmpeg_cmd(":1", (5, 7, 301, 199), "/t/o.mp4", ["-c:v", "mpeg4"], pointer=False)
        self.assertIn("300x198", cmd)
        self.assertEqual(cmd[cmd.index("-i") + 1], ":1+5,7")
        self.assertEqual(cmd[cmd.index("-draw_mouse") + 1], "0")
        self.assertEqual(cmd[-1], "/t/o.mp4")
        self.assertEqual(cmd[cmd.index("-f", cmd.index("-i")) + 1], "mp4")   # .part soubor -> formát explicitne


class TestArgs(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(shot.parse_args([])["action"], "toolbar")
        a = shot.parse_args(["--portion", "--clipboard", "--region", "1,2,3,4", "--output", "/x"])
        self.assertEqual((a["action"], a["clipboard"], a["region"], a["output"]), ("portion", True, (1, 2, 3, 4), "/x"))
        self.assertTrue(shot.parse_args(["--stop"])["stop"])
        with self.assertRaises(SystemExit):
            shot.parse_args(["--bogus"])
        with self.assertRaises(SystemExit):
            shot.parse_args(["--region", "1,2"])


# ---- GUI (Xvfb) -------------------------------------------------------------------------
BG = (40, 160, 90)


def pump(ms):
    from gi.repository import GLib, Gtk
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        GLib.usleep(5000)


@unittest.skipUnless(HAVE_DISPLAY, "needs X (xvfb-run)")
class TestGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gi.repository import Gdk, Gtk
        cls.Gtk, cls.Gdk = Gtk, Gdk
        shot.install_css()
        # Pozadi se znamou barvou (bez WM: obycejne okno pres celou obrazovku)
        root = Gdk.get_default_root_window()
        cls.sw, cls.sh = root.get_width(), root.get_height()
        bg = Gtk.Window()
        bg.set_decorated(False)
        bg.move(0, 0)
        bg.set_default_size(cls.sw, cls.sh)
        bg.set_app_paintable(True)

        def draw(_w, cr):
            cr.set_source_rgb(*(c / 255 for c in BG))
            cr.paint()
            # Barevne pruhy, aby byl snimek listy citelny
            for i, col in enumerate(((0.95, 0.6, 0.2), (0.3, 0.45, 0.9), (0.9, 0.3, 0.5))):
                cr.set_source_rgb(*col)
                cr.rectangle(0, cls.sh - 260 + i * 50, cls.sw, 25)
                cr.fill()
        bg.connect("draw", draw)
        bg.show()
        cls.bg = bg
        pump(300)

    def setUp(self):
        self.out = tempfile.mkdtemp(dir=TMP)
        self.quits = 0

    def make_app(self, opts, args):
        shot.save_options(dict(shot.DEFAULTS, **opts))
        app = shot.App(dict({"action": "toolbar", "output": self.out, "no_thumb": True}, **args))
        app.quit = self.on_quit
        return app

    def on_quit(self, *_a):
        self.quits += 1

    def pngs(self):
        return [os.path.join(self.out, f) for f in sorted(os.listdir(self.out)) if f.endswith(".png")]

    def save_look(self, name):
        d = os.environ.get("LUXOS_SHOT_DIR")
        if d:
            os.makedirs(d, exist_ok=True)
            shot.grab().savev(os.path.join(d, name), "png", [], [])

    def test_toolbar_full_screen(self):
        app = self.make_app({"mode": "screen"}, {})
        t0 = time.monotonic()
        app.run()
        pump(10)
        tb = app.toolbar
        self.assertTrue(tb.get_visible())
        self.assertLess(time.monotonic() - t0, 0.3, "toolbar must show quickly")
        pump(300)
        x, y = tb.get_position()
        w, h = tb.get_size()
        self.assertGreater(w, 300)
        self.assertLess(h, 70)
        self.assertLessEqual(abs(x + w / 2 - self.sw / 2), 2)        # dole uprostred
        self.assertGreater(y, self.sh / 2)
        self.assertIsNone(app.overlay)
        self.assertEqual(tb.capture.get_label(), "Capture")
        self.save_look("toolbar-light.png")
        settings = self.Gtk.Settings.get_default()
        settings.props.gtk_application_prefer_dark_theme = True
        pump(300)
        self.save_look("toolbar-dark.png")
        settings.props.gtk_application_prefer_dark_theme = False
        app.capture()
        pump(shot.HIDE_DELAY + 400)
        files = self.pngs()
        self.assertEqual(len(files), 1)
        self.assertEqual(png_size(files[0]), (self.sw, self.sh))
        self.assertTrue(os.path.basename(files[0]).startswith("Screenshot "))
        # Lista ve snimku neni: na jejim miste je pozadi
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new_from_file(files[0])
        px = pb.get_pixels()
        off = (y + h // 2) * pb.get_rowstride() + (x + w // 2) * pb.get_n_channels()
        self.assertNotIn(tuple(px[off:off + 3]), [(32, 33, 52), (246, 247, 252)])
        self.assertEqual(self.quits, 1)
        self.assertIsNone(app.toolbar)

    def test_toolbar_portion_remembered_selection(self):
        app = self.make_app({"mode": "portion", "selection": [100, 120, 200, 150]}, {})
        app.run()
        pump(300)
        self.assertIsNotNone(app.overlay)
        self.assertEqual(app.overlay.norm(), (100, 120, 200, 150))
        self.save_look("toolbar-portion.png")
        app.capture()
        pump(400)
        files = self.pngs()
        self.assertEqual(len(files), 1)
        self.assertEqual(png_size(files[0]), (200, 150))
        # Vyrez ze zmrazeneho snimku: bez ztmaveni prekryvem
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new_from_file(files[0])
        self.assertEqual(tuple(pb.get_pixels()[:3]), BG)
        self.assertEqual(shot.load_options()["selection"], [100, 120, 200, 150])

    def test_mode_switch_and_record_label(self):
        app = self.make_app({"mode": "screen"}, {})
        app.run()
        pump(100)
        app.set_mode("rec_portion")
        pump(shot.HIDE_DELAY + 200)
        self.assertIsNotNone(app.overlay)
        self.assertEqual(app.toolbar.capture.get_label(), "Record")
        self.assertTrue(app.toolbar.get_visible())
        app.set_mode("window")
        pump(100)
        self.assertEqual(app.overlay.mode, "window")
        self.assertFalse(app.toolbar.capture.get_sensitive())
        self.assertEqual(shot.load_options()["mode"], "window")
        app.cancel()
        pump(100)
        self.assertIsNone(app.toolbar)
        self.assertEqual(self.pngs(), [])

    def test_quick_portion_drag(self):
        """Shift+Super+4: tazeni mysi a pusteni -> snimek; Esc v jine instanci nic neulozi."""
        app = self.make_app({}, {"action": "portion"})
        app.run()
        pump(200)
        ov = app.overlay
        self.assertTrue(ov.get_visible())
        Gdk = self.Gdk

        def ev(kind, x, y, button=1):
            e = Gdk.Event.new(kind)
            e.button.button = button
            e.button.x, e.button.y, e.button.x_root, e.button.y_root = x, y, x, y
            return e
        ov.on_press(ov, ev(Gdk.EventType.BUTTON_PRESS, 300, 200).button)
        m = Gdk.Event.new(Gdk.EventType.MOTION_NOTIFY)
        m.motion.x, m.motion.y = 50, 60      # tazeni doleva nahoru
        ov.on_motion(ov, m.motion)
        ov.on_release(ov, ev(Gdk.EventType.BUTTON_RELEASE, 50, 60).button)
        pump(400)
        files = self.pngs()
        self.assertEqual(len(files), 1)
        self.assertEqual(png_size(files[0]), (250, 140))

    def test_quick_portion_escape(self):
        app = self.make_app({}, {"action": "portion"})
        app.run()
        pump(150)
        e = self.Gdk.Event.new(self.Gdk.EventType.KEY_PRESS)
        e.key.keyval = self.Gdk.KEY_Escape
        app.overlay.on_key(app.overlay, e.key)
        pump(100)
        self.assertIsNone(app.overlay)
        self.assertEqual(self.quits, 1)
        self.assertEqual(self.pngs(), [])

    def test_window_list_bounds(self):
        """Okno se stinem GTK (_GTK_FRAME_EXTENTS) se orizne na viditelnou cast; nejvyssi okno vyhrava."""
        class W:
            def __init__(self, geo, client, xid):
                self.geo, self.client, self.xid = geo, client, xid

            def get_geometry(self):
                return self.geo

            def get_client_window_geometry(self):
                return self.client

            def get_xid(self):
                return self.xid
        wl = shot.WindowList.__new__(shot.WindowList)
        wl.items = [[W((100, 100, 340, 260), (100, 100, 340, 260), 1), None],      # CSD, navrchu
                    [W((0, 0, 800, 600), (0, 30, 800, 570), 2), None]]              # s ramcem xfwm4
        orig = shot.frame_extents
        shot.frame_extents = lambda xid: (20, 20, 15, 25) if xid == 1 else None
        try:
            self.assertEqual(wl.at(130, 130), (120, 115, 300, 220))
            self.assertEqual(wl.at(105, 105), (0, 0, 800, 600))       # neviditelny okraj -> okno pod nim
            self.assertEqual(wl.at(700, 500), (0, 0, 800, 600))
            self.assertIsNone(wl.at(900, 700))
        finally:
            shot.frame_extents = orig

    def test_cursor_composite(self):
        from gi.repository import GdkPixbuf
        cur = shot.cursor_image()
        self.assertIsNotNone(cur)       # Xvfb ma XFixes
        base = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 50, 50)
        base.fill(0x000000ff)
        cpb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 4, 4)
        cpb.fill(0xffffffff)
        shot.add_cursor(base, (10, 10), (cpb, 48, 48))     # castecne mimo snimek
        px, rs = base.get_pixels(), base.get_rowstride()
        self.assertEqual(tuple(px[38 * rs + 38 * 3:38 * rs + 38 * 3 + 3]), (255, 255, 255))
        self.assertEqual(tuple(px[37 * rs + 37 * 3:37 * rs + 37 * 3 + 3]), (0, 0, 0))
        shot.add_cursor(base, (0, 0), (cpb, -100, -100))   # uplne mimo: nic


@unittest.skipUnless(HAVE_DISPLAY, "needs X (xvfb-run)")
class TestCli(unittest.TestCase):
    def run_cli(self, *args, timeout=20):
        env = dict(os.environ, PYTHONPATH=I18N)
        return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout, env=env)

    def test_full_and_region(self):
        out = tempfile.mkdtemp(dir=TMP)
        r = self.run_cli("--screen", "--output", out, "--no-thumbnail")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli("--portion", "--region", "10,20,300,200", "--output", out, "--no-thumbnail")
        self.assertEqual(r.returncode, 0, r.stderr)
        files = sorted(os.listdir(out))
        self.assertEqual(len(files), 2, files)
        sizes = sorted(png_size(os.path.join(out, f)) for f in files)
        self.assertEqual(sizes[0], (300, 200))
        self.assertGreater(sizes[1][0], 300)

    def test_record_and_stop(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg missing")
        fmts = subprocess.run(["ffmpeg", "-hide_banner", "-devices"], capture_output=True, text=True).stdout
        if "x11grab" not in fmts:
            self.skipTest("ffmpeg without x11grab")
        out = tempfile.mkdtemp(dir=TMP)
        env = dict(os.environ, PYTHONPATH=I18N)
        p = subprocess.Popen([sys.executable, BIN, "--record-portion", "--region", "0,0,321,241",
                              "--output", out, "--no-thumbnail"], env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        time.sleep(2.5)
        self.assertIsNone(p.poll(), p.stderr.read() if p.poll() is not None else "")
        with open(shot.PIDFILE) as f:
            self.assertTrue(f.read().endswith(" recording"))
        r = self.run_cli("--stop")
        self.assertEqual(r.returncode, 0)
        stdout, stderr = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 0, stderr)
        files = os.listdir(out)
        self.assertEqual(len(files), 1, files)
        self.assertTrue(files[0].startswith("Screen Recording ") and files[0].endswith(".mp4"))
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height,codec_name", "-of", "csv=p=0", os.path.join(out, files[0])],
                               capture_output=True, text=True).stdout.strip()
        self.assertEqual(probe, "h264,320,240")
        self.assertFalse(os.path.exists(shot.PIDFILE))

    def test_second_run_stops_recording(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg missing")
        out = tempfile.mkdtemp(dir=TMP)
        env = dict(os.environ, PYTHONPATH=I18N)
        p = subprocess.Popen([sys.executable, BIN, "--record-screen", "--region", "0,0,200,100",
                              "--output", out, "--no-thumbnail"], env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        time.sleep(2)
        r = self.run_cli("--portion", "--output", out)          # jakekoli dalsi spusteni nahravani zastavi
        self.assertEqual(r.returncode, 0)
        p.communicate(timeout=20)
        self.assertEqual([f for f in os.listdir(out) if f.endswith(".mp4")].__len__(), 1)


if __name__ == "__main__":
    unittest.main()
