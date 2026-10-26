#!/usr/bin/env python3
"""LuxOS - profilova fotka (files/python/luxos_avatar.py): orez, ulozeni do ~/.face a AccountsService.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_avatar.py -v

AccountsService je napodobena (LUXOS_ACCOUNTS_FAKE), domov v docasne slozce.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "files", "python"))
import luxos_avatar as av  # noqa: E402
from gi.repository import GdkPixbuf  # noqa: E402


def pixel(pb, x, y):
    i = y * pb.get_rowstride() + x * pb.get_n_channels()
    return tuple(pb.get_pixels()[i:i + 3])


class Crop(unittest.TestCase):
    def test_zoom_one_covers_short_side(self):
        # 600x400, kruh 280: kratsi strana presne pod kruhem, vyrez ze stredu
        self.assertEqual(av.crop_rect(600, 400, 280, 1.0, 0, 0), (100.0, 0.0, 400.0))

    def test_offset_clamped_to_edges(self):
        x, y, side = av.crop_rect(600, 400, 280, 1.0, 10000, -10000)
        self.assertEqual((x, y, side), (0.0, 0.0, 400.0))      # posun doprava = leva cast obrazku
        x, y, side = av.crop_rect(600, 400, 280, 1.0, -10000, 0)
        self.assertEqual(x + side, 600.0)
        self.assertEqual(av.clamp_offset(600, 400, 280, 1.0, 0, 50), (0, 0.0))

    def test_zoom(self):
        x, y, side = av.crop_rect(600, 400, 280, 2.0, 0, 0)
        self.assertEqual(side, 200.0)
        self.assertEqual((x, y), (200.0, 100.0))
        self.assertEqual(av.crop_rect(600, 400, 280, 99, 0, 0)[2], 100.0)    # nejvys MAX_ZOOM
        self.assertEqual(av.crop_rect(600, 400, 280, 0.2, 0, 0)[2], 400.0)   # nejmene 1x

    def test_render_square(self):
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 300, 200)
        pb.fill(0x00000000)                      # pruhledny -> bily podklad
        pb.new_subpixbuf(0, 0, 150, 200).fill(0xe03030ff)
        out = av.render(pb, av.crop_rect(300, 200, 280, 1.0, 10000, 0), 64)
        self.assertEqual((out.get_width(), out.get_height(), out.get_has_alpha()), (64, 64, False))
        self.assertEqual(pixel(out, 10, 32)[:1], (0xe0,))
        self.assertEqual(pixel(out, 60, 32), (255, 255, 255))

    def test_initials(self):
        self.assertEqual(av.initials("anna Nováková"), "A")
        self.assertEqual(av.initials("  "), "?")
        self.assertEqual(av.initials("čeněk"), "Č")


class Save(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="luxos-avatar-")
        self.fake = os.path.join(self.home, "accounts")
        self.old = {k: os.environ.get(k) for k in ("HOME", "LUXOS_ACCOUNTS_FAKE")}
        os.environ.update(HOME=self.home, LUXOS_ACCOUNTS_FAKE=self.fake)

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_save_current_remove(self):
        self.assertIsNone(av.current())
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 384, 384)
        pb.fill(0x3060c0ff)
        self.assertIsNone(av.save(pb))
        face = os.path.join(self.home, ".face")
        self.assertEqual(av.current(), face)
        self.assertEqual(os.stat(face).st_mode & 0o777, 0o644)       # cte ho i AccountsService (cat jako uzivatel)
        self.assertFalse(os.path.exists(face + ".tmp"))
        with open(self.fake) as f:
            self.assertEqual(f.read(), face)
        self.assertIsNone(av.remove())
        self.assertFalse(os.path.exists(face))
        with open(self.fake) as f:
            self.assertEqual(f.read(), "")
        self.assertIsNone(av.current())
        self.assertIsNone(av.remove())                                # podruhe bez chyby

    def test_load_rotates_and_limits(self):
        path = os.path.join(self.home, "big.png")
        GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4000, 1000).savev(path, "png", [], [])
        pb = av.load(path)
        self.assertEqual((pb.get_width(), pb.get_height()), (2048, 512))
        bad = os.path.join(self.home, "bad.jpg")
        with open(bad, "w") as f:
            f.write("not an image")
        with self.assertRaises(Exception):
            av.load(bad)


if __name__ == "__main__":
    unittest.main()
