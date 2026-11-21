"""X11 okna v luxwm pres XWayland (clients/x11-probe.c, headless pixman): klavesy spolknute zkratkou nesmi
po zmene zamereni zustat v X serveru stisknute, okno pevne velikosti se nemaximalizuje a X11 okna maji kurzor
z tematu, ne krizek X serveru.

  packages/luxwm/tests/build-host.sh
  scripts/wl-test/isolate python3 -m unittest -v packages/luxwm/tests/test_luxwm_x11.py

XWayland si dela svuj X soket v privatnim /tmp/.X11-unix (isolate; volne cislo displeje, ne :0).
"""
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_luxwm import BUILD, ROOT, SYSROOT, WLT, Session, wlt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
XWAYLAND = os.path.join(SYSROOT, "usr/bin/Xwayland")
GRIM = os.path.join(SYSROOT, "usr/bin/grim")


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")) and os.path.exists(XWAYLAND)
                     and shutil.which("gcc") and os.path.exists("/usr/include/X11/Xlib.h"),
                     "build first (build-host.sh), Xwayland in the sysroot, gcc and libX11 headers")
class X11Windows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxwm-x11-", dir=os.path.join(ROOT, "out"))
        cls.probe = os.path.join(cls.tmp, "x11-probe")
        subprocess.run(["gcc", "-O1", "-Wall", "-o", cls.probe, os.path.join(HERE, "clients/x11-probe.c"), "-lX11"],
                       check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        wrapper = os.path.join(ROOT, "packages/luxcomp/xwayland-sw")
        self.s = Session(env=f"LUXCOMP_XWAYLAND_WRAPPER={wrapper}")
        self.addCleanup(self.s.stop)
        self.display = self.s.log().split("xwayland ")[1].split()[0]
        self.lines = []

    def start(self, *args):
        p = subprocess.Popen([WLT, "run", self.s.dir, "env", f"DISPLAY={self.display}", self.probe, *args],
                             stdout=subprocess.PIPE)
        self.addCleanup(lambda: (p.poll() is None and p.terminate(), p.wait(5)))
        self.p = p
        self.buf = b""
        return p

    def read(self, timeout):
        """Radky probe do self.lines (primo z deskriptoru: select nad bufferovanym souborem by radky ztracel)."""
        if select.select([self.p.stdout], [], [], max(0.0, timeout))[0]:
            chunk = os.read(self.p.stdout.fileno(), 65536)
            if not chunk:
                return False
            self.buf += chunk
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                self.lines.append(line.decode())
        return True

    def wait(self, line, timeout=10):
        end = time.monotonic() + timeout
        while line not in self.lines:
            left = end - time.monotonic()
            self.assertGreater(left, 0, f"no {line!r}: {self.lines}")
            self.assertTrue(self.read(left), f"x11-probe quit before {line!r}: {self.lines}")

    def drain(self, seconds):
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0 and self.read(left):
            pass

    def view(self, title):
        for _ in range(100):
            v = self.s.state()["views"].get(title)
            if v:
                return v
            time.sleep(0.1)
        self.fail(f"no view {title}: {list(self.s.state()['views'])}")

    def test_shortcut_keys_do_not_stick_after_focus_change(self):
        # Super+Q zavre dialog X11, zatimco jsou klavesy jeste dole (ssh -X, pomaly klient): zamereni prejde na
        # hlavni okno a Q, jehoz uvolneni spolkla zkratka, nesmi prijit jako stisknute - X server by ho opakoval
        # ("qqq") a dalsi Super+Q by psalo misto zavreni okna
        self.start("--dialog")
        self.wait("mapped xmain")
        self.wait("mapped xdialog")
        self.view("xdialog")
        time.sleep(0.5)
        self.assertEqual(self.s.focused(), ["xdialog"])
        self.s.input("keydown super", "keydown q", "sleep 1.0", "keyup q", "keyup super", wait=0.2)
        self.wait("closed xdialog")
        self.drain(1.5)
        self.assertEqual(self.s.focused(), ["xmain"])
        self.assertEqual([ln for ln in self.lines if ln.startswith("key ") and not ln.startswith("key xdialog Super")
                          and not ln.startswith("key xmain Super")], [])
        self.s.input("key a", wait=0.3)
        self.wait("key xmain a")
        self.s.input("key super+q", wait=0.3)
        self.wait("closed xmain")
        self.assertNotIn("key xmain q", self.lines)

    def test_fixed_size_window_is_not_maximized(self):
        # min = max: maximalizace by dala obrazovku velky cerny ram kolem okna, ktere se nezvetsi
        self.start("--fixed", "300x200")
        self.wait("mapped xmain")
        before = self.view("xmain")
        self.assertEqual((before["w"], before["h"]), (300, 200))
        for keys in (("keydown super", "key Up", "keyup super"), ("keydown super", "key Left", "keyup super")):
            self.s.input(*keys, wait=0.6)
            v = self.s.state()["views"]["xmain"]
            self.assertEqual(v["maximized"], 0, keys)
            self.assertEqual((v["x"], v["y"], v["w"], v["h"]), (before["x"], before["y"], 300, 200), keys)
        # okno, ktere velikost menit muze, se maximalizuje dal
        self.lines = []
        self.start("--title", "xfree")
        self.wait("mapped xfree")
        self.view("xfree")
        time.sleep(0.5)
        self.s.input("keydown super", "key Up", "keyup super", wait=0.6)
        self.assertEqual(self.s.state()["views"]["xfree"]["maximized"], 1)

    @unittest.skipUnless(os.path.exists(GRIM), "grim not in the sysroot")
    def test_x11_window_shows_theme_cursor(self):
        # X11 okno bez vlastniho kurzoru ukazuje kurzor korenoveho okna: bez nastaveni od kompozitoru krizek
        # X serveru. Kurzor "default" ma hotspot ve spicce vlevo nahore, krizek kolem stredu.
        self.start()
        self.wait("mapped xmain")
        v = self.view("xmain")
        x, y = v["x"] + v["w"] // 2, v["y"] + v["h"] // 2
        self.s.input(f"move {x - 30} {y - 30}", f"move {x} {y}", wait=0.8)
        path = os.path.join(self.s.dir, "cursor.ppm")
        wlt("run", self.s.dir, GRIM, "-c", "-t", "ppm", "-g", f"{x - 16},{y - 16} 40x40", path)
        with open(path, "rb") as f:
            data = f.read()
        _, size, _, pixels = data.split(b"\n", 3)
        w = int(size.split()[0])

        def dark(px, py):
            i = (py * w + px) * 3
            return sum(pixels[i:i + 3]) < 600

        up_left = sum(dark(px, py) for py in range(0, 14) for px in range(0, 14))
        down_right = sum(dark(px, py) for py in range(17, 40) for px in range(17, 40))
        print(f"\n  cursor pixels up-left of the hotspot {up_left}, down-right {down_right}")
        self.assertGreater(down_right, 5, "no cursor in the capture")
        self.assertEqual(up_left, 0, "X server's cross cursor over an X11 window")


if __name__ == "__main__":
    unittest.main()
