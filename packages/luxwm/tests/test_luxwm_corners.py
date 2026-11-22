"""Zaoblene rohy oken bez artefaktu (pripominky 20 a 26: tmave ctverecky v rozich Firefoxu, Terminalu, Hodin).

Okno corner-probe bez zahlavi kompozitoru ve ctyrech podobach (nepruhledne, klient si rohy zaobli sam, sklo s alfou,
obsah v podpovrchu jako Firefox). V rozich mimo oblouk musi byt totez co u nepruhledneho okna (tapeta a stin okna),
uvnitr oblouku barva klienta; pod pruhlednym klientem nesmi byt stin ani obrys (jen tapeta). Pixman vzdy, gles2 jen
s render node (WLT_RENDER_NODE, vychozi /dev/dri/renderD128). Snimky: out/luxwm-test/results/corners-*.png

  packages/luxwm/tests/build-host.sh
  scripts/wl-test/run-all packages/luxwm/tests/test_luxwm_corners.py
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_luxwm_window_material import (BUILD, HERE, RESULTS, SYSROOT, Session, pixel,  # noqa: E402
                                        render_node)

CLIENT = (0xf6, 0xf6, 0xfa)
PROBE = ""


def build_probe():
    global PROBE
    if PROBE:
        return
    os.makedirs(RESULTS, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="corner-", dir=RESULTS)
    xml = os.path.join(SYSROOT, "usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml")
    scanner = os.path.join(SYSROOT, "usr/bin/wayland-scanner")
    env = {**os.environ, "LD_LIBRARY_PATH": os.path.join(SYSROOT, "usr/lib")}
    subprocess.run([scanner, "client-header", xml, os.path.join(tmp, "xdg-shell-client-protocol.h")], check=True, env=env)
    subprocess.run([scanner, "private-code", xml, os.path.join(tmp, "xdg-shell.c")], check=True, env=env)
    PROBE = os.path.join(tmp, "corner-probe")
    subprocess.run(["gcc", "-O1", "-Wall", "-I", tmp, "-o", PROBE, os.path.join(HERE, "corner-probe.c"),
                    os.path.join(tmp, "xdg-shell.c"), "-lwayland-client", "-lm"], check=True)


def near(a, b, tol):
    return max(abs(x - y) for x, y in zip(a, b)) <= tol


# body v rohu vuci levemu dolnimu rohu geometrie (dx od leveho okraje, dy od spodniho okraje); polomer 12
OUTSIDE = [(0, 1), (1, 1), (0, 3), (2, 2), (3, 0)]     # za obloukem
INSIDE = [(5, 5), (8, 3), (3, 8), (11, 1)]              # pred obloukem (11, 1 je na kraji pod obloukem)


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")), "build first: packages/luxwm/tests/build-host.sh")
class Base:
    render = ""
    label = "pixman"

    @classmethod
    def setUpClass(cls):
        build_probe()

    def setUp(self):
        self.s = Session(f"cor{os.getpid() % 10000}-{self.label}-{self._testMethodName[5:14]}", self.render)
        self.addCleanup(self.s.stop)

    def tearDown(self):
        log = self.s.log()
        self.assertNotIn("error in", log)
        self.assertNotIn("LSL callback error", log)

    def window(self, mode):
        p = self.s.spawn(PROBE, mode, "300", "200")
        self.assertEqual(p.stdout.readline().strip(), "mapped")
        time.sleep(0.6)
        return p, self.s.views()[mode]

    def close(self, p):
        p.stdin.close()
        p.wait(5)
        time.sleep(0.4)

    def corners(self, img, v):
        """{(roh, dx, dy): pixel} pro dolni rohy; roh 0 levy, 1 pravy (dx zrcadlene od praveho okraje)"""
        out = {}
        for corner in (0, 1):
            for dx, dy in OUTSIDE + INSIDE:
                x = v["x"] + dx if corner == 0 else v["x"] + v["w"] - 1 - dx
                out[corner, dx, dy] = pixel(img, x, v["y"] + v["h"] - 1 - dy)
        return out

    def reference(self):
        p, v = self.window("opaque")
        img = self.s.image(f"corners-{self.label}-opaque")
        ref = self.corners(img, v)
        for corner in (0, 1):
            for dx, dy in INSIDE:
                self.assertTrue(near(ref[corner, dx, dy], CLIENT, 2), (corner, dx, dy, ref[corner, dx, dy]))
            for dx, dy in OUTSIDE:
                self.assertFalse(near(ref[corner, dx, dy], CLIENT, 30), ("zaobleno", corner, dx, dy))
        self.close(p)
        return ref

    def check(self, mode, inside):
        ref = self.reference()
        p, v = self.window(mode)
        img = self.s.image(f"corners-{self.label}-{mode}")
        got = self.corners(img, v)
        bad = []
        for (corner, dx, dy), px in got.items():
            want = inside(img, v) if (dx, dy) in INSIDE else ref[corner, dx, dy]
            if not near(px, want, 4):
                bad.append(f"{'LR'[corner]}({dx},{dy}) {px} != {want}")
        print(f"\n  {self.label} {mode}: {len(bad)} bad", *bad, sep="\n    ", flush=True)
        self.assertEqual(bad, [])
        return p, v

    def test_subsurface_content(self):
        # Firefox: obsah v podpovrchu, koren pruhledny; kopie rohu jen z korene byla pruhledna (tmavy ctverec)
        p, v = self.check("subsurface", lambda img, v: CLIENT)
        # podpovrch se prekresli sam (desync, koren bez commitu): rohy musi jit s nim
        p.stdin.write("color 2050c0\n")
        p.stdin.flush()
        self.assertEqual(p.stdout.readline().strip(), "drawn")
        time.sleep(0.4)
        img = self.s.image(f"corners-{self.label}-subsurface-blue")
        for corner in (0, 1):
            for dx, dy in INSIDE:
                x = v["x"] + dx if corner == 0 else v["x"] + v["w"] - 1 - dx
                self.assertTrue(near(pixel(img, x, v["y"] + v["h"] - 1 - dy), (0x20, 0x50, 0xc0), 2), (corner, dx, dy))

    def test_glass_has_no_shadow_under_it(self):
        # Terminal, Hodiny: pod pruhlednym oknem tapeta, ne stin a obrys (ctverecky u rohu)
        def middle(img, v):
            return pixel(img, v["x"] + v["w"] // 2, v["y"] + v["h"] // 2)
        p, v = self.check("glass", middle)
        img = self.s.image(f"corners-{self.label}-glass")
        mid = middle(img, v)
        # cela spodni hrana a boky uvnitr okna stejne jako stred (stin pod oknem byl videt 50 px od rohu)
        for x, y in ((v["x"] + 30, v["y"] + v["h"] - 2), (v["x"] + 2, v["y"] + v["h"] - 30), (v["x"] + 6, v["y"] + 6),
                     (v["x"] + v["w"] - 3, v["y"] + 30), (v["x"] + 40, v["y"] + 40)):
            self.assertTrue(near(pixel(img, x, y), mid, 3), (x - v["x"], y - v["y"], pixel(img, x, y), mid))

    def test_client_rounded_corners(self):
        # GTK 4 / libadwaita: klient si rohy zaobli sam stejnym polomerem
        self.check("rounded", lambda img, v: CLIENT)


class Pixman(Base, unittest.TestCase):
    pass


@unittest.skipUnless(render_node(), "no accessible render node")
class Gles2(Base, unittest.TestCase):
    render = render_node()
    label = "gles2"


if __name__ == "__main__":
    unittest.main()
