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


if __name__ == "__main__":
    unittest.main()
