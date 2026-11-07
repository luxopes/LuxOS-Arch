#!/usr/bin/env python3
"""LuxOS - aplikace spustene ze zdroju nacitaji vlastni moduly, ne starsi instalovane.

    python3 -m unittest packages/luxos-desktop/tests/test_source_module_path.py -v

Drive mely Mapy, Pocasi, Kamera, Pruvodce (a Tiskarny/Skenovani) na zacatku sys.path
/usr/lib/luxos/python, takze `luxos-maps` ze zdroju (i v testech) importoval instalovany
luxos_maps.py. Test provede jen nastaveni sys.path z hlavicky skriptu (nic nespousti) a overi
poradi: zdrojova slozka pred instalovanou, instalovana zustava jako zaloha.
"""
import ast
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
INSTALLED = "/usr/lib/luxos/python"

# skript -> (slozka, ktera musi byt v sys.path pred instalovanou, modul ze zdroju)
SCRIPTS = {
    "luxos-maps/files/luxos-maps": ("luxos-maps/files", "luxos_maps"),
    "luxos-weather/files/luxos-weather": ("luxos-weather/files", "luxos_weather"),
    "luxos-desktop/files/bin/luxos-camera": ("luxos-desktop/files/python", "luxos_camera"),
    "luxos-desktop/files/bin/luxos-tour": ("luxos-desktop/files/python", None),
    "luxos-printing/files/luxos-printers": ("luxos-printing/files", "luxos_printing"),
    "luxos-printing/files/luxos-scan": ("luxos-printing/files", "luxos_scan"),
}


def path_setup(path):
    """sys.path po provedeni prikazu hlavicky skriptu, ktere s sys.path pracuji (bez importu modulu LuxOS)."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    body = []
    for node in tree.body:
        src = ast.unparse(node)
        if "sys.path" in src or (isinstance(node, ast.Assign) and "_SRC_PY" in src):
            body.append(node)
    assert body, f"{path}: no sys.path setup"
    code = compile(ast.Module(body=body, type_ignores=[]), path, "exec")
    import sys as real_sys

    class FakeSys:
        path = ["<script-dir>", "/usr/lib/python3/site-packages"]
    env = {"__file__": path, "os": os, "sys": FakeSys}
    exec(code, env)          # noqa: S102 - jen prirazeni do sys.path z vlastniho repozitare
    assert real_sys.path is not FakeSys.path
    return FakeSys.path


class TestSourceModulePath(unittest.TestCase):
    def test_source_dir_before_installed(self):
        for rel, (src_dir, module) in SCRIPTS.items():
            with self.subTest(script=rel):
                sp = path_setup(os.path.join(ROOT, rel))
                src = os.path.join(ROOT, src_dir)
                self.assertIn(INSTALLED, sp)                       # instalovane moduly jako zaloha
                self.assertIn(src, sp)
                self.assertLess(sp.index(src), sp.index(INSTALLED))
                if module:
                    self.assertTrue(os.path.isfile(os.path.join(src, module + ".py")))

    def test_installed_layout_has_no_bogus_entries(self):
        # instalovany /usr/bin/luxos-camera: /usr/python neexistuje a do sys.path se nepridava
        for rel in ("luxos-desktop/files/bin/luxos-camera", "luxos-desktop/files/bin/luxos-tour"):
            with self.subTest(script=rel):
                text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
                tree = ast.parse(text)
                fake = os.path.join(os.sep, "nonexistent-luxos-test", "bin", os.path.basename(rel))
                body = [n for n in tree.body if "sys.path" in ast.unparse(n) or "_SRC_PY" in ast.unparse(n)]

                class FakeSys:
                    path = ["/nonexistent-luxos-test/bin"]
                exec(compile(ast.Module(body=body, type_ignores=[]), rel, "exec"),   # noqa: S102
                     {"__file__": fake, "os": os, "sys": FakeSys})
                self.assertEqual(FakeSys.path, [INSTALLED, "/nonexistent-luxos-test/bin"])


if __name__ == "__main__":
    unittest.main()
