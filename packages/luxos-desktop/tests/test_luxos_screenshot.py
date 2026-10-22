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
SHORTCUTS = os.path.join(HERE, "..", "files", "xdg", "xfce4", "xfconf", "xfce-perchannel-xml",
                         "xfce4-keyboard-shortcuts.xml")
BIN = os.path.join(HERE, "..", "files", "bin", "luxos-screenshot")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
TMP = tempfile.mkdtemp(prefix="luxos-shot-test-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "config")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(TMP, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ["XDG_DATA_HOME"] = os.path.join(TMP, "data")
# Zadna sezeni D-Bus uzivatele: notifikace ani spravce souboru se nesmi objevit na skutecne obrazovce
os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + os.path.join(TMP, "no-bus")
os.environ["NO_AT_BRIDGE"] = "1"
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


class TestShortcuts(unittest.TestCase):
    def test_pretty(self):
        self.assertEqual(shot.pretty_accel("<Super><Shift>3"), "Super+Shift+3")
        self.assertEqual(shot.pretty_accel("<Shift><Primary>a"), "Ctrl+Shift+A")
        self.assertEqual(shot.pretty_accel("<Shift>Print"), "Shift+Print")
        self.assertEqual(shot.pretty_accel("Print"), "Print")
        self.assertIsNone(shot.pretty_accel("<Super>"))
        self.assertIsNone(shot.pretty_accel(""))

    def test_defaults_from_luxos(self):
        self.assertEqual(shot.global_shortcut("luxos-screenshot --screen", [SHORTCUTS]), "Super+Shift+3")
        # vic zkratek pro jeden prikaz: prvni (Super+Shift+4, ne Shift+Print)
        self.assertEqual(shot.global_shortcut("luxos-screenshot --portion", [SHORTCUTS]), "Super+Shift+4")
        self.assertIsNone(shot.global_shortcut("luxos-screenshot --window", [SHORTCUTS]))

    def test_user_overrides_defaults(self):
        d = tempfile.mkdtemp(dir=TMP)
        user, broken = os.path.join(d, "user.xml"), os.path.join(d, "broken.xml")
        with open(user, "w") as f:
            f.write('''<?xml version="1.0"?><channel name="xfce4-keyboard-shortcuts" version="1.0">
<property name="commands" type="empty"><property name="custom" type="empty">
<property name="override" type="bool" value="true"/>
<property name="&lt;Primary&gt;&lt;Alt&gt;3" type="string" value="luxos-screenshot --screen"/>
</property></property></channel>''')
        with open(broken, "w") as f:
            f.write("<channel")
        files = [os.path.join(d, "missing.xml"), broken, user, SHORTCUTS]
        self.assertEqual(shot.global_shortcut("luxos-screenshot --screen", files), "Ctrl+Alt+3")
        # uzivatel zkratku odstranil: vychozi z /etc/xdg se neukaze
        self.assertIsNone(shot.global_shortcut("luxos-screenshot --portion", files))
        self.assertIsNone(shot.global_shortcut("luxos-screenshot --screen", [broken]))


@unittest.skipUnless(HAVE_DISPLAY, "parse_args je az v GTK casti (xvfb-run)")
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


def clip_png(wait=3.0):
    """PNG ze schranky virtualniho X (jiny proces nez program) nebo b""."""
    end = time.monotonic() + wait
    while True:
        r = subprocess.run(["xclip", "-o", "-selection", "clipboard", "-t", "image/png"],
                           capture_output=True, timeout=10)
        if r.returncode == 0 and r.stdout.startswith(b"\x89PNG"):
            return r.stdout
        if time.monotonic() > end:
            return b""
        time.sleep(0.1)


def clip_text(text):
    """Schranku prevezme text (aby stary obrazek nemohl projit testem)."""
    subprocess.run(["xclip", "-selection", "clipboard", "-i"], input=text.encode(), timeout=10,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.2)


def png_bytes_size(data):
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


@unittest.skipUnless(HAVE_DISPLAY, "needs X (xvfb-run)")
class TestGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gi.repository import Gdk, Gtk
        cls.Gtk, cls.Gdk = Gtk, Gdk
        # Modalni dialog, ktery nechal otevreny jiny modul testu (stejny proces pri discover),
        # drzi zachyceni GTK a lista by nedostavala udalosti mysi
        for w in Gtk.Window.list_toplevels():
            if w.get_modal() and w.get_visible():
                w.destroy()
        # Motiv hostitele (napr. *-Dark v /etc/gtk-3.0) nesmi urcovat svetly/tmavy vzhled testu
        Gtk.Settings.get_default().props.gtk_theme_name = "Adwaita"
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
        self.addCleanup(self.close_app, app)
        return app

    @staticmethod
    def close_app(app):
        """Okna neuspesneho testu nesmi zustat na obrazovce dalsich testu."""
        for name in ("thumb", "toolbar", "overlay", "pill", "countdown"):
            w = getattr(app, name, None)
            if w:
                w.destroy()
        pump(30)

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

    # ---- popisek nad listou -------------------------------------------------------------
    def key_event(self, keyval, release=False, state=0):
        Gdk = self.Gdk
        e = Gdk.Event.new(Gdk.EventType.KEY_RELEASE if release else Gdk.EventType.KEY_PRESS)
        e.key.keyval = keyval
        e.key.state = state
        return e.key

    def test_caption_names_modes(self):
        orig = shot.shortcut_files
        shot.shortcut_files = lambda: [SHORTCUTS]
        shot._SHORTCUTS.clear()
        try:
            app = self.make_app({"mode": "screen"}, {})
            app.run()
            pump(200)
            tb, cap = app.toolbar, app.toolbar.caption
            # Vybrany rezim je videt trvale, nad listou a na stredu
            self.assertTrue(cap.get_visible())
            self.assertEqual(cap.name.get_text(), "Capture Entire Screen")
            self.assertEqual(cap.key.get_text(), "Super+Shift+3")
            (cx, cy), (cw, ch) = cap.get_position(), cap.get_size()
            (tx, ty), (tw, th) = tb.get_position(), tb.get_size()
            self.assertLessEqual(cy + ch, ty)
            self.assertGreater(cy + ch, ty - 20)
            self.assertLessEqual(abs((cx + cw / 2) - (tx + tw / 2)), 2)
            self.assertLess(ch, 34)
            # Najeti mysi: nazev hned (bez cekani tooltipu), po odjeti zpet vybrany rezim
            tb.hover("portion")
            self.assertEqual(cap.name.get_text(), "Capture Selected Portion")
            self.assertEqual(cap.key.get_text(), "Super+Shift+4")
            tb.hover("rec_screen")
            self.assertEqual(cap.name.get_text(), "Record Entire Screen")
            self.assertFalse(cap.key.get_visible())
            tb.hover("window")
            self.assertEqual(cap.hint.get_text(), "Click a window to capture it")
            tb.hover("close")
            self.assertEqual((cap.name.get_text(), cap.key.get_text()), ("Close", "Esc"))
            tb.hover("options")
            self.assertEqual(cap.name.get_text(), "Save to: Desktop")
            app.set_opt("save_to", "clipboard")
            self.assertEqual(cap.name.get_text(), "Save to: Clipboard")
            app.set_opt("save_to", "desktop")
            tb.hover("capture")
            self.assertEqual(cap.key.get_text(), "Enter")
            self.assertIn("Ctrl", cap.hint.get_text())
            tb.hover(None)
            self.assertEqual(cap.name.get_text(), "Capture Entire Screen")
            pump(50)
            # Popisek se zmensi na kratsi text a zustane na stredu
            self.assertLessEqual(abs((cap.get_position()[0] + cap.get_size()[0] / 2) - (tx + tw / 2)), 2)
            # Tlacitka nemaji pomaly tooltip GTK, ale maji jmeno pro ctecku obrazovky
            self.assertIsNone(tb.modes["portion"].get_tooltip_text())
            self.assertEqual(tb.modes["portion"].get_accessible().get_name(), "Capture Selected Portion")
            # Prepnuti rezimu: popisek ukaze novy rezim; lista se skryva -> popisek taky
            app.set_mode("rec_portion")
            self.assertFalse(cap.get_visible())
            pump(shot.HIDE_DELAY + 200)
            self.assertTrue(cap.get_visible())
            self.assertEqual(cap.name.get_text(), "Record Selected Portion")
            self.save_look("caption-rec-portion.png")
            app.cancel()
            pump(50)
        finally:
            shot.shortcut_files = orig
            shot._SHORTCUTS.clear()

    def test_caption_real_pointer_and_ctrl(self):
        """Skutecny pohyb mysi a Ctrl+klik (xdotool ve virtualnim X): popisek a kopie do schranky."""
        if not shutil.which("xdotool") or not shutil.which("xclip"):
            self.skipTest("xdotool/xclip missing")
        clip_text("before")
        app = self.make_app({"mode": "screen"}, {})
        app.run()
        pump(300)
        tb, cap = app.toolbar, app.toolbar.caption

        def center(widget):
            x, y = widget.translate_coordinates(tb, widget.get_allocated_width() // 2,
                                                    widget.get_allocated_height() // 2)
            tx, ty = tb.get_position()
            return tx + x, ty + y
        x, y = center(tb.modes["rec_portion"])
        subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=True)
        t0 = time.monotonic()
        while cap.name.get_text() != "Record Selected Portion" and time.monotonic() - t0 < 1:
            pump(10)
        self.assertEqual(cap.name.get_text(), "Record Selected Portion")
        self.assertLess(time.monotonic() - t0, 0.25, "caption must follow the pointer immediately")
        self.save_look("caption-hover.png")
        x, y = center(tb.capture)
        subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=True)
        pump(100)
        self.assertEqual(cap.key.get_text(), "Enter")
        subprocess.run(["xdotool", "keydown", "ctrl"], check=True)
        pump(150)
        try:
            self.assertEqual(tb.capture.get_label(), "Copy")
            self.save_look("toolbar-ctrl.png")
            subprocess.run(["xdotool", "click", "1"], check=True)
            pump(shot.HIDE_DELAY + 500)
        finally:
            subprocess.run(["xdotool", "keyup", "ctrl"], check=True)
        self.assertEqual(self.pngs(), [])           # Ctrl: nic se neulozilo, jen schranka
        data = clip_png()
        self.assertEqual(png_bytes_size(data), (self.sw, self.sh))
        self.assertEqual(self.quits, 1)

    def test_ctrl_key_toggles_copy_label(self):
        app = self.make_app({"mode": "portion", "selection": [10, 10, 50, 40]}, {})
        app.run()
        pump(200)
        tb = app.toolbar
        app.on_key(tb, self.key_event(self.Gdk.KEY_Control_L))
        self.assertEqual(tb.capture.get_label(), "Copy")
        app.on_key_release(tb, self.key_event(self.Gdk.KEY_Control_L, release=True))
        self.assertEqual(tb.capture.get_label(), "Capture")
        app.set_mode("rec_screen")
        app.on_key(tb, self.key_event(self.Gdk.KEY_Control_R))
        self.assertEqual(tb.capture.get_label(), "Record")       # nahravani do schranky nejde
        app.cancel()
        pump(50)

    # ---- schranka -------------------------------------------------------------------------
    def test_ctrl_enter_copies_portion(self):
        if not shutil.which("xclip"):
            self.skipTest("xclip missing")
        clip_text("before")
        app = self.make_app({"mode": "portion", "selection": [100, 120, 200, 150]}, {})
        app.run()
        pump(200)
        app.on_key(app.overlay, self.key_event(self.Gdk.KEY_Return, state=self.Gdk.ModifierType.CONTROL_MASK))
        pump(400)
        self.assertEqual(self.pngs(), [])
        data = clip_png()
        self.assertEqual(png_bytes_size(data), (200, 150))
        from gi.repository import GdkPixbuf
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(data)
        loader.close()
        self.assertEqual(tuple(loader.get_pixbuf().get_pixels()[:3]), BG)
        # Bez Ctrl (Enter) se uklada soubor jako drive
        app = self.make_app({"mode": "portion", "selection": [100, 120, 200, 150]}, {})
        app.run()
        pump(200)
        app.on_key(app.overlay, self.key_event(self.Gdk.KEY_Return))
        pump(400)
        self.assertEqual(len(self.pngs()), 1)

    def test_quick_portion_ctrl_release_copies(self):
        if not shutil.which("xclip"):
            self.skipTest("xclip missing")
        clip_text("before")
        app = self.make_app({}, {"action": "portion"})
        app.run()
        pump(200)
        ov, Gdk = app.overlay, self.Gdk

        def ev(kind, x, y, state=0):
            e = Gdk.Event.new(kind)
            e.button.button = 1
            e.button.x, e.button.y, e.button.x_root, e.button.y_root = x, y, x, y
            e.button.state = state
            return e.button
        ov.on_press(ov, ev(Gdk.EventType.BUTTON_PRESS, 10, 10))
        m = Gdk.Event.new(Gdk.EventType.MOTION_NOTIFY)
        m.motion.x, m.motion.y = 70, 50
        ov.on_motion(ov, m.motion)
        ov.on_release(ov, ev(Gdk.EventType.BUTTON_RELEASE, 70, 50, Gdk.ModifierType.CONTROL_MASK))
        pump(400)
        self.assertEqual(self.pngs(), [])
        self.assertEqual(png_bytes_size(clip_png()), (60, 40))

    def test_save_to_clipboard_option_shows_copied_thumbnail(self):
        if not shutil.which("xclip"):
            self.skipTest("xclip missing")
        clip_text("before")
        shot.save_options(dict(shot.DEFAULTS, save_to="clipboard", mode="screen"))
        app = shot.App({"action": "toolbar"})          # bez --output: volba Schranka plati
        app.quit = self.on_quit
        self.addCleanup(self.close_app, app)
        app.run()
        pump(150)
        app.capture()
        pump(shot.HIDE_DELAY + 500)
        self.assertEqual(png_bytes_size(clip_png()), (self.sw, self.sh))
        th = app.thumb
        self.assertIsNotNone(th)
        self.assertTrue(th.get_visible())
        self.assertIsNone(th.path)
        self.assertEqual(list(th.buttons), ["save_as", "close"])
        self.save_look("thumb-copied.png")
        th.act("close")
        pump(50)
        self.assertIsNone(app.thumb)
        self.assertEqual(self.quits, 1)            # xclip drzi obrazek, proces muze skoncit

    def test_gtk_clipboard_fallback_keeps_process(self):
        """Bez xclipu drzi obrazek proces sam a skonci az po prevzeti schranky nekym jinym."""
        if not shutil.which("xclip"):
            self.skipTest("xclip missing (needed to read the clipboard)")
        from gi.repository import GdkPixbuf
        orig = shot.clipboard_png
        shot.clipboard_png = lambda pb: False
        try:
            app = self.make_app({}, {})
            pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 33, 21)
            pb.fill(0x112233ff)
            self.assertTrue(app.copy_image(pb))
            reader = subprocess.Popen(["xclip", "-o", "-selection", "clipboard", "-t", "image/png"],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            t0 = time.monotonic()
            while reader.poll() is None and time.monotonic() - t0 < 5:
                pump(20)                # odpovida tento proces
            data = reader.communicate(timeout=5)[0]
            self.assertEqual(png_bytes_size(data), (33, 21))
            app.done()                  # nahled zavreny, ale schranka je nase: neskoncit
            self.assertEqual(self.quits, 0)
            pump(1700)
            clip_text("someone else")
            pump(300)
            self.assertEqual(self.quits, 1)
        finally:
            shot.clipboard_png = orig

    # ---- nahled po ulozeni -------------------------------------------------------------------
    def thumb_app(self):
        app = self.make_app({"mode": "portion", "selection": [100, 120, 200, 150]}, {"no_thumb": False})
        app.run()
        pump(200)
        before = set(self.pngs())
        app.capture()
        pump(400)
        new = sorted(set(self.pngs()) - before)
        self.assertEqual(len(new), 1)
        self.assertIsNotNone(app.thumb)
        return app, app.thumb, new[0]

    def test_thumbnail_actions_layout(self):
        app, th, path = self.thumb_app()
        self.assertEqual(th.path, path)
        self.assertEqual(list(th.buttons), ["copy", "reveal", "save_as", "delete", "close"])
        self.assertEqual([b[2].get_text() for b in th.buttons.values()],
                         ["Copy", "Show in Files", "Save As…", "Delete", "Close"])
        x, y = th.get_position()
        w, h = th.get_size()
        self.assertLessEqual(x + w, self.sw)
        self.assertLessEqual(y + h, self.sh)
        self.assertLess(w, 400)
        self.assertLess(h, 190)
        self.save_look("thumb-light.png")
        settings = self.Gtk.Settings.get_default()
        settings.props.gtk_application_prefer_dark_theme = True
        pump(200)
        self.save_look("thumb-dark.png")
        settings.props.gtk_application_prefer_dark_theme = False
        menu = th.popup_menu()
        pump(100)
        labels = [i.get_label() for i in menu.get_children() if not isinstance(i, self.Gtk.SeparatorMenuItem)]
        self.assertEqual(labels, ["Open", "Copy", "Show in Files", "Save As…", "Delete", "Close"])
        self.assertIsNone(th.timer)                 # nabidka otevrena: nahled nezmizi
        menu.popdown()
        pump(50)
        self.assertIsNotNone(th.timer)
        th.act("close")
        pump(50)
        self.assertEqual(self.quits, 1)
        self.assertTrue(os.path.exists(path))      # Zavrit soubor nemaze

    def test_thumbnail_copy(self):
        if not shutil.which("xclip"):
            self.skipTest("xclip missing")
        clip_text("before")
        app, th, path = self.thumb_app()
        th.act("copy")
        self.assertEqual(th.buttons["copy"][2].get_text(), "Copied")
        self.assertEqual(png_bytes_size(clip_png()), (200, 150))
        self.assertIsNotNone(app.thumb)            # nahled zustava pro dalsi akce
        th.finish()
        pump(50)
        self.assertEqual(self.quits, 1)
        self.assertEqual(png_bytes_size(clip_png()), (200, 150))   # i po skonceni

    def test_thumbnail_save_as(self):
        app, th, path = self.thumb_app()
        dest_dir = tempfile.mkdtemp(dir=TMP)
        asked = []
        app.ask_save_path = lambda src, video=False: asked.append((src, video)) or None   # Zrusit
        th.act("save_as")
        pump(50)
        self.assertEqual(asked, [(path, False)])
        self.assertTrue(th.get_visible())          # po zruseni se nahled vrati
        self.assertIsNotNone(th.timer)
        self.assertEqual(self.quits, 0)
        app.ask_save_path = lambda src, video=False: os.path.join(dest_dir, "copy.jpg")
        th.act("save_as")
        pump(50)
        with open(os.path.join(dest_dir, "copy.jpg"), "rb") as f:
            self.assertEqual(f.read(3), b"\xff\xd8\xff")      # JPEG podle pripony
        self.assertTrue(os.path.exists(path))      # puvodni soubor zustava
        self.assertEqual(self.quits, 1)
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new_from_file(path)
        out = shot.write_copy(pb, path, os.path.join(dest_dir, "x.png"))
        self.assertEqual(png_size(out), (200, 150))
        shot.write_copy(pb, path, path)            # sam na sebe: nic se nerozbije
        self.assertEqual(png_size(path), (200, 150))
        vid = os.path.join(dest_dir, "v.mp4")
        with open(vid, "wb") as f:
            f.write(b"video")
        shot.write_copy(None, vid, os.path.join(dest_dir, "v2.mp4"), video=True)
        with open(os.path.join(dest_dir, "v2.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"video")
        shot.write_copy(None, vid, vid, video=True)

    def test_thumbnail_reveal(self):
        app, th, path = self.thumb_app()
        opened = []
        orig_open, orig_bus = shot.open_uri, shot.Gio.bus_get_sync
        shot.open_uri = opened.append
        try:
            # Bez sezeni D-Bus: otevre se slozka
            th.act("reveal")
            pump(50)
            self.assertEqual(opened, [self.GLib_uri(os.path.dirname(path))])
            self.assertEqual(self.quits, 1)
            # Se spravcem souboru: ShowItems s URI souboru
            app, th, path = self.thumb_app()
            calls = []

            class Bus:
                def call(self, *a):
                    calls.append(a[:5])
                    a[-1](self, None)

                def call_finish(self, res):
                    return None
            shot.Gio.bus_get_sync = lambda *a: Bus()
            th.act("reveal")
            pump(50)
            self.assertEqual(calls[0][:4], ("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                                            "org.freedesktop.FileManager1", "ShowItems"))
            self.assertEqual(calls[0][4].unpack(), ([self.GLib_uri(path)], ""))
            self.assertEqual(len(opened), 1)
            self.assertEqual(self.quits, 2)
        finally:
            shot.open_uri, shot.Gio.bus_get_sync = orig_open, orig_bus

    @staticmethod
    def GLib_uri(p):
        from gi.repository import GLib
        return GLib.filename_to_uri(p)

    def test_thumbnail_delete(self):
        app, th, path = self.thumb_app()
        trashed = []
        orig = shot.trash_file
        shot.trash_file = lambda p: trashed.append(p) or "trash"
        try:
            th.act("delete")
            pump(50)
        finally:
            shot.trash_file = orig
        self.assertEqual(trashed, [path])
        self.assertIsNone(app.thumb)
        self.assertEqual(self.quits, 1)

    def test_trash_file_real(self):
        """Skutecny Kos v oddelenem procesu s HOME v TMP (nikdy Kos uzivatele)."""
        home = tempfile.mkdtemp(dir=TMP)
        f = os.path.join(home, "Desktop", "Screenshot x.png")
        os.makedirs(os.path.dirname(f))
        open(f, "wb").close()
        code = ("import importlib.machinery as m, importlib.util as u, sys;"
                "l = m.SourceFileLoader('s', sys.argv[1]); s = u.module_from_spec(u.spec_from_loader('s', l));"
                "l.exec_module(s); print(s.trash_file(sys.argv[2]))")
        env = dict(os.environ, HOME=home, XDG_DATA_HOME=os.path.join(home, ".local", "share"), PYTHONPATH=I18N)
        r = subprocess.run([sys.executable, "-c", code, BIN, f], capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(r.stdout.strip(), "trash", r.stderr)
        self.assertFalse(os.path.exists(f))
        self.assertTrue(os.path.exists(os.path.join(home, ".local", "share", "Trash", "files", "Screenshot x.png")))
        # Slozka bez Kose (tmpfs mimo domov): soubor, ktery program prave vytvoril, se smaze
        g = os.path.join(tempfile.mkdtemp(dir=TMP), "y.png")
        open(g, "wb").close()
        env = dict(os.environ, PYTHONPATH=I18N)
        r = subprocess.run([sys.executable, "-c", code, BIN, g], capture_output=True, text=True, env=env, timeout=20)
        self.assertIn(r.stdout.strip(), ("trash", "deleted"), r.stderr)
        self.assertFalse(os.path.exists(g))
        # Chybejici soubor: chyba, nic se netvari jako smazane
        r = subprocess.run([sys.executable, "-c", code, BIN, g], capture_output=True, text=True, env=env, timeout=20)
        self.assertNotEqual(r.returncode, 0)

    def test_thumbnail_delete_failure_keeps_thumbnail(self):
        app, th, path = self.thumb_app()
        notes = []
        orig = shot.notify
        shot.notify = lambda text, icon=None: notes.append(text)
        try:
            os.unlink(path)                         # soubor mezitim zmizel
            th.act("delete")
            pump(50)
            self.assertEqual(len(notes), 1)
            self.assertIsNotNone(app.thumb)
            self.assertEqual(self.quits, 0)
            th.finish()
        finally:
            shot.notify = orig

    def test_video_thumbnail_has_no_copy(self):
        from gi.repository import GdkPixbuf
        app = self.make_app({}, {})
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 440, 248)
        pb.fill(0x334455ff)
        th = shot.Thumbnail(app, os.path.join(self.out, "rec.mp4"), pb, video=True)
        self.assertEqual(list(th.buttons), ["reveal", "save_as", "delete", "close"])
        th.finish()
        self.assertEqual(self.quits, 1)

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

    def test_clipboard_survives_exit(self):
        """--clipboard: proces skonci hned a obrazek ve schrance zustane (drzi ho xclip)."""
        if not shutil.which("xclip"):
            self.skipTest("xclip missing")
        clip_text("before")
        r = self.run_cli("--portion", "--region", "5,6,77,55", "--clipboard", "--no-thumbnail", timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(png_bytes_size(clip_png()), (77, 55))

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
