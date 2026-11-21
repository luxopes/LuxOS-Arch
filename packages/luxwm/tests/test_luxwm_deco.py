"""Vzhled oken luxcomp + luxwm pres harness scripts/wl-test (headless pixman, nikdy skutecna obrazovka):
stin aktivniho a neaktivniho okna, zaoblene dolni rohy, kontrast titulku neaktivniho okna, znak na semaforu
pod ukazatelem, dvojklik na zahlavi, meritko 2, kurzor LuxOS a cas snimku pri tazeni (6 oken, 1080p).

Spusteni jako test_luxwm.py (nejdriv packages/luxwm/tests/build-host.sh):
  env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
    systemd-run --user --scope -p TasksMax=300 -- timeout 900 python3 -m unittest -v packages/luxwm/tests/test_luxwm_deco.py
Snimky: out/luxwm-test/results/deco-*.png, mereni na stdout.
"""
import os
import re
import signal
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_luxwm import BUILD, RESULTS, TITLE, W, H, WLT, Session, frame, wlt  # noqa: E402

RADIUS = 12         # tokens.TITLEBAR radius
BUTTON, SPACING = 12, 8
INSET = 14          # TITLEBAR inset_compact: centre of the first light
FRAME_BUDGET_MS = 8.0


class Image:
    def __init__(self, path):
        with open(path, "rb") as f:
            data = f.read()
        parts = data.split(maxsplit=4)
        self.w, self.h = int(parts[1]), int(parts[2])
        self.data = data[len(data) - self.w * self.h * 3:]

    def px(self, x, y):
        i = (y * self.w + x) * 3
        return tuple(self.data[i:i + 3])


def grab(s, name="deco-probe.ppm"):
    return Image(s.shot(name))


def lum(c):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def near(a, b, tol=6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def title_contrast(img, f, scale=1):
    """Nejtmavsi pixel textu uprostred zahlavi proti pozadi zahlavi (svetly motiv)"""
    x0, y0, w = f[0] * scale, f[1] * scale, f[2] * scale
    bg = img.px(x0 + w - 6 * scale, y0 + TITLE * scale // 2)
    ink = min((img.px(x, y) for y in range(y0 + 4 * scale, y0 + (TITLE - 4) * scale)
               for x in range(x0 + w // 4, x0 + 3 * w // 4)), key=lum)
    return contrast(ink, bg), ink, bg


def cursor_box(s, name):
    """Obdelnik kurzoru na prazdne plose kolem 100,100 (grim -c kresli i softwarovy kurzor)"""
    path = os.path.join(RESULTS, name)
    wlt("run", s.dir, "grim", "-c", "-t", "ppm", path)
    img = Image(path)
    bg = img.px(5, 5)
    pts = [(x, y) for y in range(60, 220) for x in range(60, 220) if img.px(x, y) != bg]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1) if pts else None


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")), "build first: packages/luxwm/tests/build-host.sh")
class LuxwmDeco(unittest.TestCase):
    def start(self, **kw):
        self.s = Session(**kw)
        return self.s

    def tearDown(self):
        self.s.stop()
        self.assertNotIn("error in", self.s.log())
        self.assertNotIn("LSL callback error", self.s.log())

    def test_shadow_active_stronger_than_inactive(self):
        s = self.start()
        s.client("A", size="300x200")
        s.client("B", size="300x200")
        st = s.state()["views"]
        img = grab(s)
        os.replace(os.path.join(RESULTS, "deco-probe.ppm"), os.path.join(RESULTS, "deco-shadow.ppm"))
        bg = img.px(W - 5, H - 5)
        dark = {}
        for t in ("A", "B"):
            x, y, w, h = frame(st[t])
            below = img.px(x + w // 2, y + h + 6)
            dark[t] = lum(bg) - lum(below)
            # za dosahem stinu (40 + posun 10) zase pozadi
            self.assertTrue(near(img.px(x + w // 2, y + h + 70), bg, 1), t)
            self.assertTrue(near(img.px(x - 60, y + h // 2), bg, 1), t)
            self.assertTrue(near(img.px(x + w // 2, y - 50), bg, 1), t)
        print(f"\nshadow 6 px below: active {dark['B']:.4f}, inactive {dark['A']:.4f} (luminance drop)")
        self.assertEqual(st["B"]["focused"], 1)
        self.assertGreater(dark["A"], 0.002)
        self.assertGreater(dark["B"], dark["A"] * 1.4)
        # po zamereni A se stiny prohodi
        s.input("move %d %d" % (st["A"]["x"] + 150, st["A"]["y"] + 100), "click")
        img = grab(s)
        xa, ya, wa, ha = frame(st["A"])
        xb, yb, wb, hb = frame(st["B"])
        self.assertGreater(lum(bg) - lum(img.px(xa + wa // 2, ya + ha + 6)),
                           lum(bg) - lum(img.px(xb + wb // 2, yb + hb + 6)))

    def test_bottom_corners_transparent(self):
        s = self.start()
        s.client("C", size="400x300", color="e02020")
        v = s.state()["views"]["C"]
        x, y, w, h = frame(v)
        img = grab(s)
        s.shot("deco-corners.png")
        bottom = y + h - 1
        # pruhy klienta: svetle e02020 (r 224) a tmave (r 112), pozadi r 38
        for cx, inner in ((x, x + RADIUS), (x + w - 1, x + w - 1 - RADIUS)):
            corner = img.px(cx, bottom)
            self.assertLess(corner[0], 60, f"corner {cx},{bottom} drawn by the client: {corner}")
            self.assertGreater(img.px(inner, bottom)[0], 100)
            self.assertGreater(img.px(cx, bottom - RADIUS)[0], 100)
        # vyhlazeny okraj: na diagonale mezi pozadim a obsahem je mezistupen
        diag = [img.px(x + i, bottom - i)[0] for i in range(RADIUS)]
        self.assertTrue(any(60 <= r <= 200 for r in diag), diag)
        # maximalizovane okno ma rohy ostre (az k okraji obrazovky)
        s.input("key super+Up", wait=0.6)
        img = grab(s)
        self.assertGreater(img.px(0, H - 1)[0], 100)
        self.assertGreater(img.px(W - 1, H - 1)[0], 100)

    def test_inactive_title_contrast(self):
        s = self.start()
        s.client("Inactive window", size="400x200")
        s.client("Active window", size="400x200")
        st = s.state()["views"]
        img = grab(s)
        s.shot("deco-titles.png")
        ratio_in, ink, bg = title_contrast(img, frame(st["Inactive_window"]))
        ratio_act, _, _ = title_contrast(img, frame(st["Active_window"]))
        print(f"\ntitle contrast: inactive {ratio_in:.2f}:1 (text {ink} on {bg}), active {ratio_act:.2f}:1")
        # neaktivni nazev = fg na 45 % (design review 1.1.0, cast 10), aktivni plny fg
        self.assertGreaterEqual(ratio_in, 2.5)
        self.assertGreaterEqual(ratio_act, 4.5)
        self.assertGreater(ratio_act, ratio_in * 2)

    def test_hover_glyphs(self):
        s = self.start()
        s.client("A", size="300x200")
        s.client("B", size="300x200")
        a = frame(s.state()["views"]["A"])
        cy = a[1] + TITLE // 2
        centres = [a[0] + INSET + i * (BUTTON + SPACING) for i in range(3)]
        s.input("move %d %d" % (a[0] + a[2] // 2, a[1] + a[3] // 2))
        img = grab(s)
        idle = [img.px(cx, cy) for cx in centres]
        for c in idle:
            self.assertLess(max(c) - min(c), 12, f"inactive light should be grey: {c}")
        fills = [(200, 130), (200, 255), (0, 255)]
        for i, cx in enumerate(centres):
            s.input("move %d %d" % (cx, cy), wait=0.3)
            img = grab(s)
            if i == 0:
                s.shot("deco-hover-close.png")
            centre, edge = img.px(cx, cy), img.px(cx + 4, cy - 4 if i else cy)
            # znak (tmavy inkoust) uprostred, barevna vypln u okraje kolecka
            self.assertLess(lum(centre), lum(edge) * 0.6, f"button {i}: no glyph, centre {centre} edge {edge}")
            self.assertGreater(max(edge) - min(edge), 60, f"button {i} not coloured: {edge}")
            # znaky ukazuji vsechna tri tlacitka skupiny (jako macOS)
            other = centres[(i + 1) % 3]
            self.assertLess(lum(img.px(other, cy)), lum(img.px(other + 4, cy - 4)) * 0.6, "group hover")
        s.input("move %d %d" % (a[0] + a[2] // 2, a[1] + a[3] // 2), wait=0.3)
        img = grab(s)
        self.assertTrue(near(img.px(centres[2], cy), idle[2], 3), "glyph stays after the pointer left")

    def test_double_click_title_maximizes(self):
        s = self.start()
        s.client("D", size="400x300")
        v = s.state()["views"]["D"]
        tx, ty = v["x"] + 200, v["y"] - TITLE // 2
        s.input("move %d %d" % (tx, ty), "click", "click", wait=0.6)
        v = s.state()["views"]["D"]
        self.assertEqual((v["maximized"], frame(v)), (1, (0, 0, W, H)))
        s.input("move %d %d" % (W // 2, TITLE // 2), "click", "click", wait=0.6)
        v = s.state()["views"]["D"]
        self.assertEqual((v["maximized"], v["w"], v["h"]), (0, 400, 300))
        # pomaly druhy klik (nad 400 ms) okno nemaximalizuje
        s.input("move %d %d" % (v["x"] + 200, v["y"] - TITLE // 2), "click", "sleep 0.6", "click", wait=0.6)
        self.assertEqual(s.state()["views"]["D"]["maximized"], 0)

    def test_scale_2(self):
        s = self.start()
        wlt("run", s.dir, "wlr-randr", "--output", "HEADLESS-1", "--scale", "2")
        time.sleep(0.5)
        s.client("Scale two with a title long enough to be shortened", size="260x160", color="e02020")
        s.client("Other", size="200x120")
        st = s.state()["views"]
        v = st["Scale_two_with_a_title_long_enough_to_be_shortened"]
        x, y, w, h = (2 * c for c in frame(v))
        img = grab(s)
        s.shot("deco-scale2.png")
        # zahlavi 2x vyssi: pod nim (y + 2 * TITLE) uz obsah okna
        self.assertGreater(img.px(x + w // 2, y + 2 * TITLE + 2)[0], 150)
        self.assertLess(img.px(x + w // 2, y + 2 * TITLE - 4)[0] - img.px(x + w // 2, y + 2 * TITLE - 4)[2], 20)
        # semafor neaktivniho okna: kolecko 2 x 12 px
        cy = y + TITLE
        row = [img.px(px, cy) for px in range(x, x + 2 * (SPACING + BUTTON + 4))]
        grey = [i for i, c in enumerate(row) if max(c) - min(c) < 12 and 150 < c[0] < 215]
        self.assertTrue(20 <= len(grey) <= 26, f"button width {len(grey)} px")
        # zaobleny dolni roh i ve 2x, text titulku citelny
        self.assertLess(img.px(x, y + h - 1)[0], 80)
        self.assertGreater(img.px(x + 2 * RADIUS, y + h - 1)[0], 150)
        ratio, _, _ = title_contrast(img, frame(v), 2)
        print(f"\nscale 2: inactive title contrast {ratio:.2f}:1")
        self.assertGreaterEqual(ratio, 2.5)

    def test_cursor_theme_and_scale(self):
        if not os.path.isdir("/usr/share/icons/WhiteSur-cursors"):
            self.skipTest("WhiteSur-cursors not installed on the host")
        s = self.start()
        settings = os.path.join(s.dir, "config", "gtk-3.0", "settings.ini")
        os.makedirs(os.path.dirname(settings), exist_ok=True)

        def use(size):
            with open(settings, "w") as f:
                f.write(f"[Settings]\ngtk-cursor-theme-name=WhiteSur-cursors\ngtk-cursor-theme-size={size}\n")
            os.kill(s.pid, signal.SIGHUP)
            time.sleep(0.5)
            self.assertIn(f"cursor WhiteSur-cursors {size}", s.log())
            s.input("move 100 100", wait=0.3)

        # WhiteSur-cursors ma velikosti 24, 30, 36 a 48
        use(24)
        base = cursor_box(s, "deco-cursor-24.ppm")
        use(36)
        big = cursor_box(s, "deco-cursor-36.ppm")
        use(24)
        wlt("run", s.dir, "wlr-randr", "--output", "HEADLESS-1", "--scale", "2")
        time.sleep(0.5)
        s.input("move 100 100", wait=0.3)
        hidpi = cursor_box(s, "deco-cursor-24-scale2.ppm")
        print(f"\ncursor (x, y, w, h): 24 px {base}, 36 px {big}, 24 px at scale 2 {hidpi}")
        self.assertTrue(base and big and hidpi)
        self.assertTrue(1.3 <= big[3] / base[3] <= 1.7, (base, big))
        self.assertTrue(1.8 <= hidpi[3] / base[3] <= 2.2, (base, hidpi))

    def test_drag_frame_time_six_windows_1080p(self):
        s = self.start(env="LUXCOMP_STATS=1", size="1920x1080")
        for i in range(6):
            s.client(f"W{i}", app=f"app{i}", size="900x650", wait=0.4)
        top = [v for v in s.state()["views"].values() if v["focused"] == 1][0]
        tx, ty = top["x"] + 600, top["y"] - TITLE // 2
        s.shot("deco-six-windows.png")
        for _ in range(3):
            s.input(f"drag {tx} {ty} 300 200 1500", "sleep 0.3", f"drag 300 200 {tx} {ty} 1500", "sleep 0.3", wait=0.5)
        drags = [tuple(float(v) for v in m) for m in
                 re.findall(r"luxcomp: drag (\d+) frames, slowest render ([\d.]+) ms, mean ([\d.]+) ms", s.log())]
        self.assertEqual(len(drags), 6, s.log()[-2000:])
        slowest = max(d[1] for d in drags)
        mean = sum(d[2] * d[0] for d in drags) / sum(d[0] for d in drags)
        print(f"\ndrag 6 windows 1080p pixman: {int(sum(d[0] for d in drags))} frames, "
              f"slowest {slowest:.2f} ms, mean {mean:.2f} ms")
        self.assertLess(slowest, FRAME_BUDGET_MS)


if __name__ == "__main__":
    unittest.main()
