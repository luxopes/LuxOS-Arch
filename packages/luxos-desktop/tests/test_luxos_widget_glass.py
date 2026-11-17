#!/usr/bin/env python3
"""Kontrast a rozostreni skutecneho materialu widgetu, bez displeje a D-Bus.

    python3 -m unittest discover -s packages/luxos-desktop/tests -p test_luxos_widget_glass.py -v
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SRC = Path(__file__).resolve().parent.parent / "files/lsl/luxos-widgets.lsl"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")


def function(source, name):
    start = source.index("function " + name + "(")
    return source[start:source.index("\nend", start) + 4]


def rgb(pixel):
    return [(pixel >> shift & 255) / 255 for shift in (16, 8, 0)]


def luminance(color):
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in color]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


@unittest.skipUnless(LSLC, "needs lslc with the linux-x86_64-gnu target")
class GlassMaterial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Prekladame primo produkcni filtr, ktery vlastni a uvolnuje vstupni surface.
        source = SRC.read_text()
        harness = "load cairo, json\n" + function(source, "clamp") + "\n" + function(source, "glass_surface") + "\n" + function(source, "glass_style")
        harness += '''
colors = [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.7, 0.3], [1.0, 0.0, 1.0], [0.0, 1.0, 1.0], [1.0, 1.0, 0.0], [0.5, 0.5, 0.5]]
solid = []
styles = []
for color in colors:
    s = cairo.image_surface_create(cairo.FORMAT_RGB24, 16, 16)
    cr = cairo.create(s)
    call cairo.set_source_rgb(cr, color[0], color[1], color[2])
    call cairo.paint(cr)
    call cairo.destroy(cr)
    glass = glass_surface(s, 16, 16)
    solid.append(cairo.image_surface_pixel(glass, 8, 8))
    styles.append(glass_style(glass, 0, 0, 16, 16))
    call cairo.surface_destroy(glass)
end
s = cairo.image_surface_create(cairo.FORMAT_RGB24, 16, 16)
cr = cairo.create(s)
call cairo.set_source_rgb(cr, 0.0, 0.0, 0.0)
call cairo.paint(cr)
call cairo.set_source_rgb(cr, 1.0, 1.0, 1.0)
call cairo.rectangle(cr, 8, 0, 8, 16)
call cairo.fill(cr)
call cairo.destroy(cr)
glass = glass_surface(s, 16, 16)
edge = []
for x in range(5, 11):
    edge.append(cairo.image_surface_pixel(glass, x, 8))
end
call cairo.surface_destroy(glass)
print(json.encode([solid, edge, styles]))
'''
        with tempfile.TemporaryDirectory(prefix="widget-glass-") as tmp:
            src, binary = Path(tmp) / "glass.lsl", Path(tmp) / "glass"
            src.write_text(harness)
            result = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", str(src), str(binary)],
                                    capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            output = subprocess.check_output([str(binary)], text=True, timeout=10)
        cls.solid, cls.edge, cls.styles = json.loads(output)

    def test_text_contrast_on_light_dark_and_saturated_wallpapers(self):
        for pixel, (light, veil) in zip(self.solid, self.styles):
            # Skutecny zavoj a oba konce odlesku; text prepina stejne jako Cairo a CSS.
            for sheen in (0, 0.08):
                background = [(v * (1 - veil) + int(light) * veil) * (1 - sheen) + sheen
                              for v in rgb(pixel)]
                ink = (25 / 255, 31 / 255, 43 / 255) if light else (1, 1, 1)
                for alpha in (1.0, 0.90):
                    foreground = [i * alpha + v * (1 - alpha) for i, v in zip(ink, background)]
                    values = sorted((luminance(foreground), luminance(background)))
                    contrast = (values[1] + 0.05) / (values[0] + 0.05)
                    self.assertGreaterEqual(contrast, 4.5, (rgb(pixel), light, veil, alpha))

    def test_light_wallpaper_stays_light(self):
        for index in (1, 5, 8):  # bila, tepla, zluta
            light, veil = self.styles[index]
            self.assertTrue(light)
            self.assertLess(veil, 0.05)
            self.assertGreater(luminance(rgb(self.solid[index])), 0.4)

    def test_wallpaper_colors_and_variations_remain_visible(self):
        red, green, blue = map(rgb, self.solid[2:5])
        self.assertGreater(red[0], red[1])
        self.assertGreater(green[1], green[0])
        self.assertGreater(blue[2], blue[0])
        # Regrese proti puvodni oprave, ktera barvy stlacila do tmavych ploch.
        self.assertGreater(luminance(rgb(self.solid[1])) - luminance(rgb(self.solid[0])), 0.7)

    def test_hard_wallpaper_edge_becomes_a_smooth_transition(self):
        values = [luminance(rgb(pixel)) for pixel in self.edge]
        for left, right in zip(values, values[1:]):
            self.assertLess(left, right)
        self.assertEqual(self.edge[0], self.solid[0])
        self.assertEqual(self.edge[-1], self.solid[1])


POOL_HARNESS = '''
theme = {"raw": 0, "pool": True, "map": []}
alpha = []
for d in range(0, 24):
    alpha.append(pool_alpha(1.0, Float(d)))
end
lin = []
for i in range(0, 11):
    lin.append(srgb_linear(Float(i) / 10.0))
end
A = "%(a)s"
B = "%(b)s"
C = "%(c)s"
D = "%(d)s"
base = {"/backdrop/screen0/monitoreDP-1/workspace0/last-image": A,
        "/backdrop/screen0/monitoreDP-1/workspace2/last-image": B,
        "/backdrop/screen0/monitorzz-old/workspace0/last-image": C,
        "/backdrop/screen0/monitorzz-old/workspace2/last-image": D}
per_ws = {"/backdrop/single-workspace-mode": False}
for k in base.keys():
    per_ws[k] = base[k]
end
picks = [pick_wallpaper(base, 2, "eDP-1"), pick_wallpaper(per_ws, 2, "eDP-1"), pick_wallpaper(per_ws, 0, "eDP-1"),
         pick_wallpaper(per_ws, 2, "HDMI-1"), pick_wallpaper({}, 0, "eDP-1")]
print(json.encode([alpha, lin, picks]))
'''


@unittest.skipUnless(LSLC, "needs lslc with the linux-x86_64-gnu target")
class PoolAndWallpaper(unittest.TestCase):
    """Stin karty na svetle tapete a vyber tapety (hlavni monitor, aktivni plocha)."""

    @classmethod
    def setUpClass(cls):
        source = SRC.read_text()
        consts = "\n".join(line for line in source.splitlines() if line.startswith(("POOL_", "GLASS_RADIUS")))
        cls.tmp = tempfile.mkdtemp(prefix="widget-pool-")
        cls.walls = {}
        for name in ("a", "b", "c", "d"):
            cls.walls[name] = os.path.join(cls.tmp, name + ".png")
            Path(cls.walls[name]).write_bytes(b"x")
        harness = "load cairo, json\n" + consts + "\n" + "\n".join(
            function(source, n) for n in ("clamp", "srgb_linear", "pool_alpha", "pick_wallpaper"))
        harness += POOL_HARNESS % cls.walls
        src, binary = Path(cls.tmp) / "pool.lsl", Path(cls.tmp) / "pool"
        src.write_text(harness)
        result = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", str(src), str(binary)],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.alpha, cls.lin, cls.picks = json.loads(subprocess.check_output([str(binary)], text=True, timeout=10))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_pool_fades_to_zero_without_edge(self):
        self.assertAlmostEqual(self.alpha[0], 0.20, places=3)
        self.assertEqual(self.alpha[20:], [0.0] * 4)
        self.assertLess(self.alpha[19], 0.002, "na dosahu prakticky nula - bez hrany na okraji okna")
        self.assertEqual(self.alpha[:21], sorted(self.alpha[:21], reverse=True))

    def test_linear_light_approximation(self):
        for i, v in enumerate(self.lin):
            self.assertAlmostEqual(v, luminance([i / 10] * 3), delta=0.01)

    def test_wallpaper_of_primary_monitor_and_active_workspace(self):
        w = self.walls
        # bez ulozene volby xfdesktop: jedna tapeta (plocha 0) na vsech plochach, stary monitor nevadi
        self.assertEqual(self.picks[0], w["a"])
        # tapeta pro kazdou plochu zvlast: aktivni plocha hlavniho monitoru
        self.assertEqual(self.picks[1], w["b"])
        self.assertEqual(self.picks[2], w["a"])
        # neznamy monitor: aspon spravna plocha
        self.assertIn(self.picks[3], (w["b"], w["d"]))
        self.assertEqual(self.picks[4], "")


if __name__ == "__main__":
    unittest.main()
