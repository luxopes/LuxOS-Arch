"""Animace oken, zaneprazdneny ukazatel a prechod po prihlaseni v luxwm (headless pixman, harness scripts/wl-test).

Spusteni jako test_luxwm.py (build-host.sh, pak unittest pod isolate). LUXCOMP_ANIM_SCALE zpomali animace,
aby grim zachytil mezistavy; snimky jako pasy PNG v out/luxwm-test/results/anim-*.png, casy snimku
z LUXCOMP_STATS v logu kompozitoru.
"""
import os
import re
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_luxwm import BAR, BUILD, H, RESULTS, TITLE, W, WLT, Session, frame, test_conf, wlt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.join(HERE, "clients", "gtk-launcher.py")
MSG = os.path.join(BUILD, "luxwm-msg")
SLOW = 12           # LUXCOMP_ANIM_SCALE: otevreni 180 ms -> 2,16 s
RED = "ff0000"


def ppm(path):
    with open(path, "rb") as f:
        data = f.read()
    parts = data.split(maxsplit=4)
    w, h = int(parts[1]), int(parts[2])
    return w, h, data[len(data) - w * h * 3:]


def red_box(path, near=None):
    """Ohraniceni pixelu okna (cervene, i poloprusvitne) a nejvetsi r-g uvnitr (1 = plne nepruhledne);
    near = okno ze stavu luxwm: jen jeho sloupce (cerveny semafor jinych oken se nepocita)"""
    w, h, px = ppm(path)
    xs = range(near["x"] - 40, near["x"] + near["w"] + 40) if near else range(w)
    x0 = y0 = 1 << 30
    x1 = y1 = -1
    best = 0
    for y in range(BAR, h, 2):
        row = y * w * 3
        for x in range(max(0, xs.start) & ~1, min(w, xs.stop), 2):
            r, g = px[row + x * 3], px[row + x * 3 + 1]
            if r - g > 40:
                x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
                best = max(best, r - g)
    if x1 < 0:
        return None
    return (x0, y0, x1 - x0 + 2, y1 - y0 + 2, best / 255)


def strip(frames, out, scale=4):
    """Zmensene snimky vedle sebe do jednoho PNG (GdkPixbuf hostitele)"""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pics = [GdkPixbuf.Pixbuf.new_from_file(f) for f in frames]
    w, h = pics[0].get_width() // scale, pics[0].get_height() // scale
    sheet = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, (w + 4) * len(pics), h)
    sheet.fill(0xffffffff)
    for i, p in enumerate(pics):
        p.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR).copy_area(0, 0, w, h, sheet, i * (w + 4), 0)
    sheet.savev(out, "png", [], [])


class Capture:
    """grim na pozadi (wlt capture), behem toho test spusti akci"""

    def __init__(self, s, name, fps, sec):
        self.dir = os.path.join(RESULTS, name)
        os.makedirs(self.dir, exist_ok=True)
        for f in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, f))
        self.proc = subprocess.Popen([WLT, "capture", s.dir, self.dir, str(fps), str(sec)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.15)

    def frames(self):
        self.proc.wait(timeout=60)
        return sorted(os.path.join(self.dir, f) for f in os.listdir(self.dir) if f.endswith(".ppm"))


def stats(log, kind):
    return [(int(f), float(ms)) for f, ms in re.findall(r"luxcomp: anim %d (\d+) frames, slowest render ([\d.]+) ms" % kind, log)]


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")), "build first: packages/luxwm/tests/build-host.sh")
class LuxwmAnimations(unittest.TestCase):
    def session(self, env="", **kw):
        os.environ["WLT_PRIVILEGED"] = os.path.realpath(MSG)
        self.s = Session(env="LUXCOMP_STATS=1 " + env, **kw)
        self.addCleanup(self.check_log)
        self.addCleanup(self.s.stop)
        return self.s

    def check_log(self):
        log = self.s.log()
        self.assertNotIn("error in", log)
        self.assertNotIn("LSL callback error", log)

    def assert_final(self, got, view):
        """konec animace = okno presne na svem miste (vzorkovani po 2 px)"""
        want = (view["x"], 400, view["y"] + 300, 1.0)
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, delta=1, msg=f"{got} != {want}")

    def red(self, s, title="A", size="400x300"):
        wlt("run", s.dir, "--bg", "wlt-client", "--events", "--solid", "--color", RED, "--title", title,
            "--size", size)

    def test_open_grows_fades_in_and_ends_exact(self):
        s = self.session(f"LUXCOMP_ANIM_SCALE={SLOW}")
        s.bar()
        cap = Capture(s, "anim-open", 8, 3)
        self.red(s)
        frames = cap.frames()
        view = s.state()["views"]["A"]
        boxes = [red_box(f, view) for f in frames]
        seen = [(f, b) for f, b in zip(frames, boxes) if b]
        self.assertGreaterEqual(len(seen), 6, boxes)
        widths = [b[2] for _, b in seen]
        alphas = [b[4] for _, b in seen]
        # roste a prolina se (nikdy zpet), konec presne na miste okna, plne nepruhledne
        self.assertLess(widths[0], 396, widths)
        self.assertLess(alphas[0], 0.9, alphas)
        self.assertEqual(widths, sorted(widths))
        self.assertEqual(alphas, sorted(alphas))
        # zahlavi ma barvu klienta, proto se porovnava spodni okraj obsahu
        x, y, w, h, a = seen[-1][1]
        self.assert_final((x, w, y + h, a), view)
        # stred zustava (pocatecni zmenseni kolem stredu ramu vcetne zahlavi)
        cx = seen[0][1][0] + seen[0][1][2] / 2
        self.assertAlmostEqual(cx, view["x"] + 200, delta=3)
        strip([f for f, _ in seen[:: max(1, len(seen) // 8)]][:8] + [seen[-1][0]], os.path.join(RESULTS, "anim-open.png"))

    def test_input_works_mid_open(self):
        s = self.session(f"LUXCOMP_ANIM_SCALE={SLOW * 2}")
        self.red(s)
        time.sleep(0.4)     # animace bezi jeste ~3,9 s
        view = s.state()["views"]["A"]
        s.input(f"move {view['x'] + 200} {view['y'] + 150}", "click", "type hi", wait=0.3)
        box = red_box(s.shot("anim-mid-input.ppm"))
        self.assertTrue(box and box[4] < 0.98, f"animation must still run: {box}")
        with open(os.path.join(s.dir, "clients.log")) as f:
            events = f.read()
        self.assertIn("button", events)
        self.assertRegex(events, r"key.*\bh\b|key 35|key.*104", events[-400:])
        self.assertEqual(s.focused(), ["A"])

    def test_close_is_a_picture_and_clicks_go_through(self):
        s = self.session(f"LUXCOMP_ANIM_SCALE={SLOW}")
        s.client("Below", size="600x400", color="2040c0")
        time.sleep(2.2)
        self.red(s, "Top", "300x200")
        time.sleep(2.6)
        top = s.state()["views"]["Top"]
        cap = Capture(s, "anim-close", 8, 2)
        s.input("key alt+F4", wait=0.25)
        # behem zavirani klik do mista zavirajiciho okna dostane okno pod nim
        s.input(f"move {top['x'] + 150} {top['y'] + 100}", "click", wait=0.2)
        frames = cap.frames()
        st = s.state()
        self.assertNotIn("Top", st["views"])
        self.assertEqual(s.focused(), ["Below"])
        boxes = [red_box(f, top) for f in frames]
        fading = [b for b in boxes if b]
        self.assertGreaterEqual(len(fading), 3, boxes)
        # do stisku Alt+F4 okno stoji, pak se zmensuje
        widths = [b[2] for b in fading]
        self.assertEqual(widths, sorted(widths, reverse=True))
        self.assertLess(widths[-1], widths[0])
        # zmensuje se cely obraz okna (obsah klienta), ne jen jeho okraje
        self.assertTrue(any(b[2] < 298 and b[3] > 180 for b in fading), fading)
        self.assertLess(fading[-1][4], fading[0][4])
        self.assertIsNone(boxes[-1], "the picture must be gone at the end")
        strip(frames[:12:2], os.path.join(RESULTS, "anim-close.png"))

    def test_minimize_to_dock_and_restore(self):
        s = self.session(f"LUXCOMP_ANIM_SCALE={SLOW}")
        self.red(s)
        time.sleep(2.6)
        view = s.state()["views"]["A"]
        cap = Capture(s, "anim-minimize", 6, 5)
        s.input("key super+m", wait=0.1)
        frames = cap.frames()
        self.assertEqual(s.state()["views"]["A"]["visible"], 0)
        boxes = [b for b in (red_box(f) for f in frames) if b]
        self.assertGreaterEqual(len(boxes), 4, boxes)
        centres = [(b[0] + b[2] / 2, b[1] + b[3] / 2) for b in boxes]
        # zmensuje se a jede ke spodnimu okraji uprostred (Dock bez set_rectangle)
        self.assertEqual([b[2] for b in boxes], sorted([b[2] for b in boxes], reverse=True))
        self.assertGreater(centres[-1][1], centres[0][1] + 100)
        self.assertAlmostEqual(centres[-1][0], W / 2, delta=40)
        self.assertIsNone(red_box(frames[-1]))
        strip(frames[:16:2], os.path.join(RESULTS, "anim-minimize.png"))
        # obnoveni jako klik na ikonu v Docku (aktivace z panelu); Alt+Tab ukazuje okna bez animace
        cap = Capture(s, "anim-restore", 6, 5)
        wlt("run", s.dir, MSG, "focus-window", str(view["id"]))
        frames = cap.frames()
        x, y, w, h, a = red_box(frames[-1])
        self.assert_final((x, w, y + h, a), view)
        first = next(b for b in (red_box(f) for f in frames) if b)
        self.assertTrue(first and first[2] < 300, f"restore grows out of the Dock: {first}")
        strip(frames[:16:2], os.path.join(RESULTS, "anim-restore.png"))
        self.assertEqual(s.focused(), ["A"])

    def test_reduce_motion_and_greeter_have_none(self):
        conf = test_conf("luxwm-anim-reduce.conf")
        with open(conf) as f:
            text = f.read().replace("reduce_motion = no", "reduce_motion = yes")
        with open(conf, "w") as f:
            f.write(text)
        s = self.session(f"LUXCOMP_ANIM_SCALE={SLOW} LUXWM_SYSTEM_CONFIG={conf}")
        self.red(s)
        time.sleep(0.5)
        x, y, w, h, a = red_box(s.shot("anim-reduced.ppm"))
        view = s.state()["views"]["A"]
        self.assert_final((x, w, y + h, a), view)
        s.input("key super+m", wait=0.3)
        self.assertIsNone(red_box(s.shot("anim-reduced-min.ppm")))
        self.assertEqual(stats(s.log(), 1) + stats(s.log(), 3), [])

    def test_frame_cost_pixman_1080p(self):
        """Skutecne casy (bez zpomaleni): pocet snimku a nejpomalejsi vykresleni na snimek z LUXCOMP_STATS"""
        s = self.session(size="1920x1080")
        s.bar()
        s.client("Big", size="900x600", color="808080")
        self.red(s, "A", "900x600")
        time.sleep(0.6)
        s.input("key super+m", wait=0.6)
        wlt("run", s.dir, MSG, "focus-window", str(s.state()["views"]["A"]["id"]))
        time.sleep(0.6)
        s.input("key alt+F4", wait=0.5)
        log = s.log()
        report = []
        for kind, name in ((1, "open"), (2, "close"), (3, "minimize"), (4, "restore")):
            runs = stats(log, kind)
            self.assertTrue(runs, f"no {name} animation in the log")
            frames, slowest = runs[-1]
            report.append(f"{name}: {frames} frames, slowest render {slowest:.2f} ms")
            # casy jsou z hostitele, ktery muze byt vytizeny jinymi testy: hrube meze, cisla do anim-cost.txt
            self.assertGreaterEqual(frames, 2, report)
            self.assertLess(slowest, 25.0, report)
        with open(os.path.join(RESULTS, "anim-cost.txt"), "w") as f:
            f.write("\n".join(report) + "\n")
        print("\n" + "\n".join(report))


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")), "build first: packages/luxwm/tests/build-host.sh")
class LuxwmLaunchFeedback(unittest.TestCase):
    def setUp(self):
        self.s = Session(env="LUXCOMP_STATS=1")
        self.addCleanup(self.s.stop)

    def busy_lines(self):
        return re.findall(r"luxcomp: busy pointer (on|off)", self.s.log())

    def test_gtk_launch_shows_progress_until_window_maps(self):
        s = self.s
        # GTK spoustec (jako Dock): klik -> g_app_info_launch s GdkAppLaunchContext -> token xdg-activation
        app = os.path.join(RESULTS, "anim-app.desktop")
        with open(app, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=Late\nStartupNotify=true\n"
                    "Exec=sh -c 'sleep 1.2; exec wlt-client --title Late'\n")
        wlt("run", s.dir, "--bg", sys.executable, LAUNCHER, app)
        time.sleep(1.5)
        launcher = s.state()["views"]["Launcher"]
        s.input(f"move {launcher['x'] + 100} {launcher['y'] + 60}", "click", wait=0.6)
        self.assertEqual(self.busy_lines(), ["on"], "busy pointer while the app starts")
        time.sleep(1.5)
        self.assertIn("Late", s.state()["views"])
        self.assertEqual(self.busy_lines(), ["on", "off"], "back to the arrow once the window maps")

    def test_key_binding_launch_and_timeout(self):
        s = self.s
        conf = test_conf("luxwm-anim-launch.conf", "[keys]\n<Super>F9 = exec true\n<Super>F10 = exec wlt-client --title K\n")
        s.stop()
        self.s = Session(env=f"LUXCOMP_STATS=1 LUXWM_SYSTEM_CONFIG={conf} LUXWM_LAUNCH_FEEDBACK_MS=800")
        self.addCleanup(self.s.stop)
        s = self.s
        s.input("key super+F10", wait=1.0)
        self.assertIn("K", s.state()["views"])
        lines = self.busy_lines()
        # okno se objevi driv nez za 150 ms, nebo ukazatel kratce bezi a vypne se
        self.assertIn(lines, ([], ["on", "off"]))
        s.input("key super+F9", wait=0.4)
        self.assertEqual(self.busy_lines()[-1:], ["on"], "a program without a window keeps the busy pointer a while")
        time.sleep(0.8)
        self.assertEqual(self.busy_lines()[-1:], ["off"], "the policy timeout ends it")


WALLPAPER = "/usr/share/backgrounds/luxos/luxos-light.jpg"
COVER_SRC = os.path.join(HERE, "..", "..", "luxos-desktop", "files", "src", "luxos-session-cover.c")


def greeter_frame(path, w, h):
    """Posledni snimek greeteru jako ho uklada luxos-greeter (X11 1.0.5 i LSL): tapeta pres obrazovku a cerna
    0.24, soubor LUXFRAME1 (test_luxos_greeter_wl overuje, ze LSL greeter zapise presne tohle) -> pixely RGB"""
    import cairo
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file(WALLPAPER)
    sc = max(w / pb.get_width(), h / pb.get_height())
    tw, th = max(1, round(pb.get_width() * sc)), max(1, round(pb.get_height() * sc))
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
    cr = cairo.Context(surf)
    Gdk.cairo_set_source_pixbuf(cr, pb.scale_simple(tw, th, GdkPixbuf.InterpType.BILINEAR), (w - tw) / 2, (h - th) / 2)
    cr.paint()
    cr.set_source_rgba(0, 0, 0, 0.24)
    cr.paint()
    surf.flush()
    bgrx = bytes(surf.get_data())
    with open(path, "wb") as f:
        f.write(b"LUXFRAME1 %d %d\n" % (w, h) + bgrx)
    return bytes(b for i in range(0, len(bgrx), 4) for b in (bgrx[i + 2], bgrx[i + 1], bgrx[i]))


def bar_box(rgb, frame, w, h):
    """Ohraniceni pixelu, ktere se od snimku greeteru lisi o vic nez 3 (bar prubehu)"""
    x0 = y0 = 1 << 30
    x1 = y1 = -1
    for y in range(h // 2, h):
        for x in range(w // 4, 3 * w // 4):
            i = (y * w + x) * 3
            if max(abs(rgb[i + c] - frame[i + c]) for c in range(3)) > 3:
                x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1) if x1 >= 0 else None


def outside_diff(rgb, frame, w, h, box):
    worst = 0
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            if box and box[0] - 2 <= x < box[0] + box[2] + 2 and box[1] - 2 <= y < box[1] + box[3] + 2:
                continue
            i = (y * w + x) * 3
            worst = max(worst, max(abs(rgb[i + c] - frame[i + c]) for c in range(3)))
    return worst


def x11_cover_shot(frame_path, delay):
    """luxos-session-cover --login z X11 1.0.5 v soukromem Xvfb (isolate): cerny koren = snimek z login-frame.raw,
    bez spravce oken bezi az 6 s; snimek obrazovky po delay s -> pixely RGB"""
    import ctypes
    import ctypes.util
    import shutil
    import tempfile
    import gi
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk
    Gdk.init([])
    tmp = tempfile.mkdtemp(dir=RESULTS)
    binary = os.path.join(tmp, "luxos-session-cover")
    subprocess.run(["gcc", "-O2", "-o", binary, COVER_SRC, "-lX11", "-lXfixes", "-lXcomposite", "-lXrandr", "-lXrender",
                    "-lcairo", "-lm", "-pthread"], check=True)
    shutil.copy(frame_path, os.path.join(tmp, "login-frame.raw"))
    x = ctypes.CDLL(ctypes.util.find_library("X11"))
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XSetWindowBackground.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
    x.XClearWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    dpy = x.XOpenDisplay(None)
    root = x.XDefaultRootWindow(dpy)
    x.XSetWindowBackground(dpy, root, 0)
    x.XClearWindow(dpy, root)
    x.XSync(dpy, 0)
    env = dict(os.environ, HOME=tmp, XDG_CONFIG_HOME=os.path.join(tmp, "config"), LUXOS_LOGIN_FRAME_DIR=tmp)
    p = subprocess.Popen([binary, "--login"], env=env)
    try:
        time.sleep(delay)
        win = Gdk.get_default_root_window()
        pb = Gdk.pixbuf_get_from_window(win, 0, 0, win.get_width(), win.get_height())
        data, stride, n = pb.get_pixels(), pb.get_rowstride(), pb.get_n_channels()
        w, h = pb.get_width(), pb.get_height()
        rgb = b"".join(data[y * stride:y * stride + w * n] for y in range(h))
        if n == 4:
            rgb = bytes(b for i in range(0, len(rgb), 4) for b in rgb[i:i + 3])
        return w, h, rgb
    finally:
        p.terminate()
        p.wait(timeout=10)
        shutil.rmtree(tmp, True)


def save_rgb(rgb, w, h, path):
    with open(path, "wb") as f:
        f.write(b"P6 %d %d 255\n" % (w, h) + rgb)


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")), "build first: packages/luxwm/tests/build-host.sh")
class LuxwmIntro(unittest.TestCase):
    def test_greeter_frame_and_bar_like_x11_then_fade(self):
        os.makedirs(RESULTS, exist_ok=True)
        path = os.path.join(RESULTS, "login-frame")
        frame = greeter_frame(path, W, H)
        s = Session(env=f"LUXCOMP_STATS=1 LUXOS_LOGIN_FRAME={path}", args=("--intro",))
        self.addCleanup(s.stop)
        time.sleep(0.8)
        w, h, wl = ppm(s.shot("intro-wayland.ppm"))
        self.assertIn("luxwm: intro with the greeter frame", s.log())
        box = bar_box(wl, frame, w, h)
        # 1280x800 jako v X11 bar_geometry: 220x6, stred, 204 * 800/1080 nad spodnim okrajem
        self.assertIsNotNone(box)
        self.assertEqual((box[1], box[3]), (646, 6), box)
        self.assertEqual(box[0], 530)
        self.assertLessEqual(outside_diff(wl, frame, w, h, box), 0, "the rest is the greeter frame unchanged")

        xw, xh, x11 = x11_cover_shot(path, 0.8)
        save_rgb(x11, xw, xh, os.path.join(RESULTS, "intro-x11.ppm"))
        self.assertEqual((xw, xh), (w, h))
        xbox = bar_box(x11, frame, w, h)
        self.assertLessEqual(outside_diff(x11, frame, w, h, xbox), 0)
        print(f"\nbar wayland {box} x11 {xbox}")
        # stejne misto a tvar; mimo usek mezi konci obou vyplni (vypln roste podle fazi relace, X11 tu bez spravce
        # oken stoji ve fazi 0) pixel po pixelu stejne
        self.assertEqual(box, xbox)

        def fill_end(rgb):
            y = box[1] + box[3] // 2
            return next(x for x in range(box[0] + 4, box[0] + box[2]) if rgb[(y * w + x) * 3] < 225)
        ends = sorted([fill_end(wl), fill_end(x11)])
        worst = 0
        for y in range(box[1] - 1, box[1] + box[3] + 1):
            for x in range(box[0] - 1, box[0] + box[2] + 1):
                if ends[0] - 4 <= x <= ends[1] + 4:
                    continue
                i = (y * w + x) * 3
                worst = max(worst, max(abs(wl[i + c] - x11[i + c]) for c in range(3)))
        print(f"\nbar {box}, fill ends wayland {fill_end(wl)} x11 {fill_end(x11)}, max pixel difference {worst}")
        self.assertLessEqual(worst, 3)

        # plocha (tapeta, lista) nakreslena: zakryti se rozplyne do ni
        cap = Capture(s, "anim-intro", 15, 3)
        wlt("run", s.dir, "--bg", "wlt-bar", "--height", str(H), "--layer", "background", "--color", "6080a0")
        wlt("run", s.dir, "--bg", "wlt-bar", "--height", str(BAR), "--color", "e0e0e0")
        frames = cap.frames()
        self.assertIn("intro end (ready)", s.log())
        self.assertIn("luxcomp: cover fade", s.log())
        desk = [ppm(f)[2] for f in frames]
        # podil plochy (modra 6080a0) v pixelu uprostred: 0 -> 1, nikdy zpet
        mix = []
        for d in desk:
            i = (300 * w + 200) * 3
            mix.append(round((d[i + 2] - frame[i + 2]) / (0xa0 - frame[i + 2] or 1), 2))
        self.assertAlmostEqual(mix[0], 0, delta=0.02)
        self.assertAlmostEqual(mix[-1], 1, delta=0.02)
        self.assertEqual(mix, sorted(mix) if mix[-1] >= mix[0] else mix, mix)
        self.assertGreaterEqual(len(set(mix)) - 2, 2, f"visible steps of the fade {mix}")
        start = max(0, next(i for i, v in enumerate(mix) if v > 0.02) - 2)
        strip(frames[start:start + 8], os.path.join(RESULTS, "anim-intro.png"))

    def test_without_frame_black_with_bar_input_goes_through(self):
        s = Session(env="LUXCOMP_STATS=1 LUXOS_LOGIN_FRAME=/nonexistent", args=("--intro",))
        self.addCleanup(s.stop)
        time.sleep(0.5)
        w, h, px = ppm(s.shot("anim-intro-black.ppm"))
        box = bar_box(px, bytes(len(px)), w, h)
        self.assertEqual((box[0], box[1], box[3]), (530, 646, 6), box)
        self.assertEqual(outside_diff(px, bytes(len(px)), w, h, box), 0, "black outside the bar")
        wlt("run", s.dir, "--bg", "wlt-client", "--events", "--title", "Under")
        time.sleep(0.6)
        v = s.state()["views"]["Under"]
        s.input(f"move {v['x'] + 50} {v['y'] + 50}", "click")
        with open(os.path.join(s.dir, "clients.log")) as f:
            self.assertIn("button", f.read())


if __name__ == "__main__":
    unittest.main()
