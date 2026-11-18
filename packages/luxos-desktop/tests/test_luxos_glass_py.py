#!/usr/bin/env python3
"""LuxOS - sklo oken v Pythonu (files/python/luxos_glass.py) = sklo oken v LSL (files/lsl/luxos_glass.lsl).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_glass_py.py -v

Rozmazani tapety (gtk.pixbuf_blur + pixbuf_saturate ze standardni knihovny LSL) musi dat stejne
pixely: maly program v LSL vypise pixely po rozmazani, Python udela totez a porovnaji se vsechny.
Obrazky: barevny sum (RGB), ostre hrany, pruhledny PNG (RGBA) a obrazek mensi nez okno filtru.
Dale: okno se sklem pod Xvfb (bez kompozitoru) se vykresli, semafor a tmavy rezim.
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
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "files", "python"))
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")

import gi  # noqa: E402

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib  # noqa: E402

import cairo  # noqa: E402

import luxos_glass as glass  # noqa: E402

HARNESS = r'''
load gtk, cairo
pb = gtk.pixbuf_new_from_file_at_scale(arg(1), 240, 240, True)
call gtk.pixbuf_blur(pb, 3)
call gtk.pixbuf_saturate(pb, 1.18)
s = gtk.pixbuf_to_surface(pb)
w = gtk.pixbuf_get_width(pb)
h = gtk.pixbuf_get_height(pb)
parts = [String(w), String(h)]
y = 0
while y < h:
    x = 0
    while x < w:
        parts.append(String(cairo.image_surface_pixel(s, x, y) & 4294967295))
        x = x + 1
    end
    y = y + 1
end
print " ".join(parts)
'''


def python_pixels(path):
    pb = glass.blurred_pixbuf(path)
    w, h = pb.get_width(), pb.get_height()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    from gi.repository import Gdk
    Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
    cr.paint()
    surface.flush()
    data, stride = surface.get_data(), surface.get_stride()
    out = []
    for y in range(h):
        for x in range(w):
            o = y * stride + x * 4
            out.append(int.from_bytes(bytes(data[o:o + 4]), "little"))
    return w, h, out


def write_image(path, w, h, alpha, fill):
    pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, alpha, 8, w, h)
    ch, st = pb.get_n_channels(), pb.get_rowstride()
    data = bytearray(st * h)
    for y in range(h):
        for x in range(w):
            px = fill(x, y)
            data[y * st + x * ch:y * st + x * ch + ch] = bytes(px[:ch])
    GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(data)), GdkPixbuf.Colorspace.RGB, alpha, 8, w, h,
                                   st).savev(path, "png", [], [])


@unittest.skipUnless(LSLC, "needs lslc with the linux-x86_64-gnu target")
class BlurMatchesLsl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.mkdtemp(prefix="luxos-glass-py-")
        src = os.path.join(cls.t, "harness.lsl")
        with open(src, "w") as f:
            f.write(HARNESS)
        cls.bin = os.path.join(cls.t, "harness")
        r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", src, cls.bin], capture_output=True, text=True)
        if r.returncode != 0:
            raise AssertionError(r.stderr + r.stdout)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.t, True)

    def compare(self, name, w, h, alpha, fill):
        path = os.path.join(self.t, name)
        write_image(path, w, h, alpha, fill)
        out = subprocess.run([self.bin, path], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        values = [int(v) for v in out.stdout.split()]
        lw, lh, lsl = values[0], values[1], values[2:]
        pw, ph, py = python_pixels(path)
        self.assertEqual((pw, ph), (lw, lh))
        diff = [i for i, (a, b) in enumerate(zip(py, lsl)) if a != b]
        self.assertEqual(diff[:5], [], (name, len(diff), [(hex(py[i]), hex(lsl[i])) for i in diff[:5]]))

    def test_noise_rgb(self):
        rnd = random.Random(7)
        self.compare("noise.png", 320, 180, False, lambda x, y: (rnd.randrange(256), rnd.randrange(256),
                                                                 rnd.randrange(256)))

    def test_sharp_edges_and_saturated_colors(self):
        self.compare("edges.png", 240, 160, False,
                     lambda x, y: (255, 30, 10) if (x // 17 + y // 13) % 2 else (10, 40, 255))

    def test_transparent_png(self):
        rnd = random.Random(3)
        self.compare("alpha.png", 200, 120, True, lambda x, y: (rnd.randrange(256), 120, 40, (x * 7 + y * 3) % 256))

    def test_tiny_image_smaller_than_filter(self):
        self.compare("tiny.png", 2, 3, False, lambda x, y: (x * 120, y * 80, 200))


class WindowGlass(unittest.TestCase):
    def test_window_draws_glass_and_lights(self):
        if not os.environ.get("DISPLAY"):
            self.skipTest("GUI only under xvfb-run")
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        # bez tapety a sledovani xfconf (test nesaha na nastaveni sezeni): jen material bez vyrezu
        glass._state["watch"] = -1
        win = Gtk.Window(title="test")
        glass.setup(win, True)
        box = glass.lights(win, lambda b: None)
        self.assertEqual(len(box.get_children()), 3, "zavrit, minimalizovat, maximalizovat")
        fixed = Gtk.Window(title="pevne")
        glass.setup(fixed, False)
        self.assertEqual(len(glass.lights(fixed, lambda b: None).get_children()), 2, "pevna velikost bez zeleneho")
        self.assertFalse(win.get_decorated())
        self.assertTrue(win.get_style_context().has_class("lg-window"))
        for dark, expect in ((False, lambda p: sum(p) > 600), (True, lambda p: sum(p) < 200)):
            glass.set_dark(dark)
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 120)
            cr = cairo.Context(surface)
            win.resize(200, 120)
            win.show_all()
            while Gtk.events_pending():
                Gtk.main_iteration()
            glass._on_draw(win, cr)
            surface.flush()
            data, st = surface.get_data(), surface.get_stride()
            o = 60 * st + 100 * 4
            pixel = (data[o + 2], data[o + 1], data[o])
            self.assertTrue(expect(pixel), (dark, pixel))
            # roh za zaoblenim pruhledny
            self.assertEqual(data[3], 0)
        win.destroy()
        fixed.destroy()


if __name__ == "__main__":
    unittest.main()
