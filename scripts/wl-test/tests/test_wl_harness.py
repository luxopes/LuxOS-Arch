"""Testy harnessu scripts/wl-test (labwc headless a nested, vstup, detektor blikani).

Spousteni: systemd-run --user --scope -p TasksMax=300 -- timeout 600 python3 -m unittest scripts/wl-test/tests/test_wl_harness.py
Potrebuje labwc + wlroots 0.20 (fetch-sysroot.sh nebo system); nested navic Xvfb.
WLT_FRAMES_DIR=adresar: detektor se navic overi na skutecne rade snimku (napr. z VM matice).
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
WLT = HERE / "wlt"
OUT = Path(os.environ.get("WLT_OUT", HERE.parent.parent / "out" / "wl-test"))
FRAMES = OUT / "bin" / "wlt-frames"


def clean_env():
    env = {k: v for k, v in os.environ.items()
           if k not in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS")}
    env["DBUS_SYSTEM_BUS_ADDRESS"] = "unix:path=/nonexistent"
    return env


def wlt(*args, check=True, timeout=120):
    r = subprocess.run([str(WLT), *map(str, args)], env=clean_env(), capture_output=True, text=True,
                       timeout=timeout)
    if check and r.returncode:
        raise AssertionError(f"wlt {' '.join(map(str, args))} failed: {r.stderr}")
    return r


def have_labwc():
    if (OUT / "sysroot" / "usr" / "bin" / "labwc").exists():
        return True
    return shutil.which("labwc") is not None and shutil.which("grim") is not None


def write_ppm(path, w, h, pixels):
    with open(path, "wb") as f:
        f.write(b"P6\n%d %d\n255\n" % (w, h))
        f.write(pixels)


def frame(w, h, rect_x, bg=(30, 30, 40), fg=(59, 130, 246)):
    """Snimek s obdelnikem 120x90 na pozici rect_x (jako tazene okno)."""
    row_bg = bytes(bg) * w
    rows = []
    for y in range(h):
        if 60 <= y < 150:
            x0, x1 = max(rect_x, 0), min(rect_x + 120, w)
            rows.append(bytes(bg) * x0 + bytes(fg) * (x1 - x0) + bytes(bg) * (w - x1))
        else:
            rows.append(row_bg)
    return b"".join(rows)


def check(*args):
    r = subprocess.run([str(FRAMES), "check", *map(str, args)], capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout


class Detector(unittest.TestCase):
    """Detektor na umelych snimcich: okno se posouva, pak stoji."""

    W, H = 320, 240

    @classmethod
    def setUpClass(cls):
        wlt("build")

    def sequence(self, d):
        xs = list(range(0, 200, 5)) + [200] * 20
        for i, x in enumerate(xs):
            write_ppm(d / f"f{i:04d}.ppm", self.W, self.H, frame(self.W, self.H, x))
        return xs

    def test_clean_sequence(self):
        with tempfile.TemporaryDirectory() as t:
            self.sequence(Path(t))
            rc, out = check(t)
            self.assertEqual(rc, 0, out)
            self.assertIn("flagged=0", out)

    def test_black_frame(self):
        with tempfile.TemporaryDirectory() as t:
            self.sequence(Path(t))
            write_ppm(Path(t) / "f0010.ppm", self.W, self.H, bytes(self.W * self.H * 3))
            rc, out = check(t)
            self.assertEqual(rc, 1)
            self.assertIn("FLAG black f0010.ppm", out)
            self.assertIn("flagged=1", out)

    def test_regressed_frame(self):
        with tempfile.TemporaryDirectory() as t:
            self.sequence(Path(t))
            shutil.copy(Path(t) / "f0020.ppm", Path(t) / "f0025.ppm")
            rc, out = check(t)
            self.assertEqual(rc, 1)
            self.assertIn("FLAG regressed f0025.ppm like=f0020.ppm", out)
            self.assertIn("flagged=1", out)

    def test_half_drawn_frame(self):
        # okno uz stoji, jeden snimek ma spodni polovinu jen s pozadim
        with tempfile.TemporaryDirectory() as t:
            self.sequence(Path(t))
            half = frame(self.W, self.H, 200)[: self.W * 3 * 100] + frame(self.W, self.H, -500)[self.W * 3 * 100:]
            write_ppm(Path(t) / "f0050.ppm", self.W, self.H, half)
            rc, out = check(t)
            self.assertEqual(rc, 1)
            self.assertIn("FLAG transient f0050.ppm", out)

    def test_direction_reversal_is_not_flicker(self):
        # tam a zpet s pauzou na konci - skutecny stav, ne probliknuti
        with tempfile.TemporaryDirectory() as t:
            xs = list(range(0, 100, 5)) + [100] * 10 + list(range(95, 0, -5))
            for i, x in enumerate(xs):
                write_ppm(Path(t) / f"f{i:04d}.ppm", self.W, self.H, frame(self.W, self.H, x))
            rc, out = check(t)
            self.assertEqual(rc, 0, out)

    def test_menu_open_close_is_not_flicker(self):
        with tempfile.TemporaryDirectory() as t:
            a, b = frame(self.W, self.H, 0), frame(self.W, self.H, 0, fg=(250, 250, 250))
            for i, px in enumerate([a] * 10 + [b] * 10 + [a] * 10):
                write_ppm(Path(t) / f"f{i:04d}.ppm", self.W, self.H, px)
            rc, out = check(t)
            self.assertEqual(rc, 0, out)

    @unittest.skipUnless(os.environ.get("WLT_FRAMES_DIR"), "WLT_FRAMES_DIR not set")
    def test_real_frames_injection(self):
        src = Path(os.environ["WLT_FRAMES_DIR"])
        with tempfile.TemporaryDirectory(dir=OUT) as t:
            for f in sorted(src.glob("f*.ppm")):
                shutil.copy(f, t)
            rc, out = check(t)
            self.assertEqual(rc, 0, out)
            files = sorted(Path(t).glob("f*.ppm"))
            w, h = map(int, open(files[0], "rb").read(32).split()[1:3])
            write_ppm(files[50], w, h, bytes(w * h * 3))
            shutil.copy(files[55], files[60])
            rc, out = check(t)
            self.assertIn(f"FLAG black {files[50].name}", out)
            self.assertIn(f"FLAG regressed {files[60].name} like={files[55].name}", out)
            self.assertIn("flagged=2", out)


@unittest.skipUnless(have_labwc(), "labwc not available (run fetch-sysroot.sh)")
class Headless(unittest.TestCase):
    mode = "headless"

    def setUp(self):
        if self.mode == "nested" and not shutil.which("Xvfb"):
            self.skipTest("Xvfb not installed")
        self.name = f"test-{self.mode}-{os.getpid()}-{time.monotonic_ns()}"
        self.session = Path(wlt("start", "--mode", self.mode, "--name", self.name, "--size", "1024x768",
                                "--timeout", "300").stdout.strip())
        self.tmp = Path(tempfile.mkdtemp(dir=OUT))

    def tearDown(self):
        wlt("stop", self.session, check=False)
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.session, ignore_errors=True)

    def start_client(self):
        wlt("run", self.session, "--bg", "wlt-client", "--events", "--title", "T")
        log = self.session / "clients.log"
        for _ in range(100):
            if log.exists() and "configure" in log.read_text():
                break
            time.sleep(0.05)
        time.sleep(0.3)

    def stat(self, path):
        out = subprocess.run([str(FRAMES), "stat", str(path)], capture_output=True, text=True).stdout
        fields = dict(kv.split("=") for kv in out.split()[2:])
        return int(fields["colors"]), float(fields["nonblack"])

    def test_isolation(self):
        pid = int((self.session / "compositor.pid").read_text())
        child = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
        env = Path(f"/proc/{child[0] if child else pid}/environ").read_bytes().split(b"\0")
        env = dict(e.decode().split("=", 1) for e in env if b"=" in e)
        self.assertNotIn("WAYLAND_DISPLAY", env)
        self.assertEqual(env["XDG_RUNTIME_DIR"], str(self.session / "run"))
        self.assertEqual(env["WLR_RENDERER"], "pixman")
        self.assertIn(env["WLR_BACKENDS"], ("headless", "x11"))
        if self.mode == "headless":
            self.assertNotIn("DISPLAY", env)
        else:
            self.assertEqual(env["DISPLAY"], (self.session / "display").read_text().strip())

    def test_screenshot_not_empty(self):
        self.start_client()
        wlt("shot", self.session, self.tmp / "s.ppm")
        wlt("shot", self.session, self.tmp / "s.png")
        colors, nonblack = self.stat(self.tmp / "s.ppm")
        self.assertGreaterEqual(colors, 3)
        self.assertGreater(nonblack, 0.1)
        self.assertGreater((self.tmp / "s.png").stat().st_size, 1000)
        self.assertRegex(wlt("mem", self.session).stdout, r"compositor_pss_kb=\d+")

    def test_input_reaches_client(self):
        self.start_client()
        wlt("input", self.session, "move 512 384", "click", "type aB", "key ctrl+x")
        time.sleep(0.3)
        log = (self.session / "clients.log").read_text()
        for line in ("enter", "button 272 down", "button 272 up", "key a down", "key Control_L down",
                     "key x down"):
            self.assertIn(line, log)

    def test_input_echo_after_commands(self):
        """Trvale bezici wlt input: radek echo prijde az po odeslani predchozich prikazu, klient je uz ma."""
        self.start_client()
        p = subprocess.Popen([str(WLT), "input", str(self.session)], env=clean_env(), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
        p.stdin.write("move 512 384\nkey b\necho one two\n")
        p.stdin.flush()
        self.assertEqual(p.stdout.readline(), "one two\n")
        time.sleep(0.1)
        self.assertIn("key b down", (self.session / "clients.log").read_text())
        p.stdin.close()
        self.assertEqual(p.wait(10), 0)
        p.stdout.close()

    def test_drag_moves_window(self):
        self.start_client()
        wlt("shot", self.session, self.tmp / "a.ppm")
        wlt("input", self.session, "drag 512 222 300 150 300")
        time.sleep(0.3)
        wlt("shot", self.session, self.tmp / "b.ppm")
        d = subprocess.run([str(FRAMES), "diff", self.tmp / "a.ppm", self.tmp / "b.ppm"], capture_output=True,
                           text=True).stdout
        self.assertGreater(float(d), 0.05)

    def test_idle_no_false_positives(self):
        self.start_client()
        for run in range(3):
            d = self.tmp / f"idle{run}"
            wlt("capture", self.session, d, 30, 3)
            rc, out = check(d)
            self.assertEqual(rc, 0, out)

    def test_capture_during_scenario(self):
        self.start_client()
        d = self.tmp / "cap"
        p = subprocess.Popen([str(WLT), "capture", str(self.session), str(d), "30", "4"], env=clean_env(),
                             stdout=subprocess.DEVNULL)
        wlt("input", self.session, "sleep 0.3", "drag 512 222 300 150 1200", "sleep 0.3", "move 800 100",
            "click right", "sleep 0.3", "move 830 120", "move 830 150", "move 830 180", "key esc")
        p.wait(timeout=60)
        rc, out = check(d)
        self.assertEqual(rc, 0, out)
        files = sorted(d.glob("f*.ppm"))
        w, h = 1024, 768
        write_ppm(files[20], w, h, bytes(w * h * 3))
        rc, out = check(d)
        self.assertIn(f"FLAG black {files[20].name}", out)


class Nested(Headless):
    mode = "nested"


@unittest.skipUnless(have_labwc(), "labwc not available (run fetch-sysroot.sh)")
class MultiOutput(unittest.TestCase):
    def test_two_outputs_side_by_side(self):
        for mode in ("headless", "nested"):
            if mode == "nested" and not shutil.which("Xvfb"):
                continue
            s = Path(wlt("start", "--mode", mode, "--outputs", 2, "--size", "800x600", "--timeout", 120).stdout.strip())
            try:
                self.assertEqual((s / "layout").read_text().strip(), "1600x600")
                wlt("run", s, "--bg", "wlt-client")
                time.sleep(0.5)
                # okno se otevre na prvnim vystupu, oba vystupy jsou v jednom snimku
                with tempfile.TemporaryDirectory(dir=OUT) as t:
                    wlt("shot", s, Path(t) / "s.ppm")
                    out = subprocess.run([str(FRAMES), "stat", str(Path(t) / "s.ppm")], capture_output=True,
                                         text=True).stdout
                    self.assertIn(" 1600x600 ", out)
            finally:
                wlt("stop", s, check=False)
                shutil.rmtree(s, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
