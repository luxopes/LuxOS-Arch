#!/usr/bin/env python3
"""LuxAI - stavovy radek agenta ukazuje kratkou cestu (~ misto domovske slozky, zkraceny stred).

    python3 -m unittest packages/apps/luxai/tests/test_short_path.py -v

Zdroj LuxAI je jen v archivu luxai-<verze>.tar.gz vedle PKGBUILD: test ho rozbali do docasne
slozky, prelozi maly testovaci program nad lsl/common.lsl (`lsl compile`) a spusti ho.
Potrebuje prekladac LSL (balicek lsl); bez nej se preskoci.
"""
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

PROGRAM = r'''load common
home = "/home/anna"
cases = [["/home/anna", home, 48], ["/home/anna/Projects/web", home, 48], ["/home/annabel/x", home, 48],
         ["/srv/data", home, 48], ["/home/anna/Projects/LuxOS-Arch/packages/luxos-desktop/files/python", home, 40],
         ["/var/lib/very/long/path/to/some/deep/folder/name", "", 30], ["/home/anna/x", "/home/anna/", 48],
         ["/home/anna/a-very-long-single-folder-name-that-does-not-fit", home, 20], ["/", "/", 48]]
for c in cases:
    print common.short_path(c[0], c[1], c[2])
end
'''

EXPECTED = [
    "~",
    "~/Projects/web",
    "/home/annabel/x",
    "/srv/data",
    "~/Projects/…/luxos-desktop/files/python",
    "/var/…/some/deep/folder/name",
    "~/x",
    "~/a-very-long-single-folder-name-that-does-not-fit",
    "/",
]


@unittest.skipUnless(shutil.which("lsl"), "needs the LSL compiler (package lsl)")
class TestShortPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxai-short-path-")
        ver = re.search(r"^pkgver=(\S+)", open(os.path.join(PKG, "PKGBUILD")).read(), re.M).group(1)
        with tarfile.open(os.path.join(PKG, f"luxai-{ver}.tar.gz")) as tf:
            tf.extractall(cls.tmp, filter="data")
        cls.lsl = os.path.join(cls.tmp, f"luxai-{ver}", "lsl")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_short_path(self):
        src = os.path.join(self.lsl, "short_path_test_main.lsl")
        with open(src, "w", encoding="utf-8") as f:
            f.write(PROGRAM)
        out = os.path.join(self.tmp, "short-path-test")
        r = subprocess.run(["nice", "-n", "10", "lsl", "compile", "--unsafe", src, out],
                           capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run([out], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), EXPECTED)

    def test_status_line_uses_short_path(self):
        text = open(os.path.join(self.lsl, "app_window.lsl"), encoding="utf-8").read()
        line = next(l for l in text.splitlines() if 'i18n.translate("folder")' in l and "status" in l)
        self.assertIn("common.short_path(app_model.workdir(state), glib.home_dir())", line)


if __name__ == "__main__":
    unittest.main()
