#!/usr/bin/env python3
"""Snimek obrazovky na Waylandu (files/lsl/luxos_shot_wl.lsl pres luxos-screenshot-ui) proti luxwm headless.

    packages/luxwm/tests/build-host.sh
    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_shot_wl.py -v

Kazdy test ma vlastni relaci `scripts/wl-test/wlt start -- luxwm` (pixman, 1280x800, LUXCOMP_VIRTUAL_INPUT=1
kvuli `wlt input`). Privilegovane protokoly dostane jen prelozeny luxos-screenshot-ui a pomocny klient
(WLT_PRIVILEGED); kopie stejneho programu jinde v allowlistu neni a snimek porizovat nesmi.
Snimky se porovnavaji s grim ze stejne relace (pixel po pixelu). LUXWM_BUILD: vychozi out/luxwm-test/build.
"""
import os
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
import zlib

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
REPO = PKG.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
OUT = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or OUT / "sysroot")
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")
LUXWM = LUXWM_BUILD / "luxwm"
TOOLS = all(shutil.which(t) for t in ("make", "gcc", "wayland-scanner", "pkg-config"))
W, H = 1280, 800
BLUE = "3b82f6"          # wlt-client: pruhy barvy a jeji polovicni jasnosti
BLUE_DARK = "1d417b"


def png_read(path):
    """8bit RGB/RGBA bez prokladani -> (sirka, vyska, RGB)."""
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "neni PNG"
    pos, idat = 8, b""
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, ctype = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    bpp = 4 if ctype == 6 else 3
    raw = zlib.decompress(idat)
    stride = width * bpp
    out, prev = bytearray(), bytearray(stride)
    for y in range(height):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        out += line if bpp == 3 else bytes(v for i, v in enumerate(line) if i % 4 != 3)
    return width, height, bytes(out)


def ppm_read(path):
    magic, size, depth, pixels = Path(path).read_bytes().split(b"\n", 3)
    width, height = map(int, size.split())
    return width, height, pixels


def crop(image, x, y, w, h):
    width, _, pixels = image
    return w, h, b"".join(pixels[((y + r) * width + x) * 3:((y + r) * width + x + w) * 3] for r in range(h))


def colors(image):
    _, _, pixels = image
    return {pixels[i:i + 3].hex() for i in range(0, len(pixels), 3)}


@unittest.skipUnless(LSLC and LUXWM.exists() and TOOLS and WLT.exists() and (SYSROOT / "usr/bin/grim").exists(),
                     "chybi lslc, luxwm (build-host.sh), sysroot harnessu nebo nastroje sestaveni")
class ShotWayland(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(prefix="luxos-shot-wl-", dir=OUT))
        r = subprocess.run(["make", "-s", "-C", str(PKG / "files/src/luxos-wl"), f"OUT={cls.tmp}"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("libluxos-wl: " + r.stdout + r.stderr)
        src = cls.tmp / "lsl"
        src.mkdir()
        for f in (PKG / "files/lsl").glob("*.lsl"):
            shutil.copy(f, src)
        shutil.copy(HERE / "lsl/luxos-shot-wl-probe.lsl", src)
        for name in ("luxos-screenshot-ui", "luxos-shot-wl-probe"):
            r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(src), str(src / f"{name}.lsl"),
                                str(cls.tmp / name)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"{name}: " + r.stdout + r.stderr)
        # stejny program mimo allowlist
        (cls.tmp / "other").mkdir()
        shutil.copy(cls.tmp / "luxos-screenshot-ui", cls.tmp / "other/luxos-screenshot-ui")
        conf = cls.tmp / "luxwm.conf"
        conf.write_text("xwayland = no\n" + "".join(line for line in (REPO / "packages/luxwm/luxwm.conf").read_text()
                                                    .splitlines(True) if not line.startswith("xwayland")))
        cls.conf = conf
        cls.times = {}

    @classmethod
    def tearDownClass(cls):
        if cls.times:
            print("\n  casy (ms): " + ", ".join(f"{k} {v:.0f}" for k, v in sorted(cls.times.items())))
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.procs = []
        name = f"s{os.getpid() % 10000}-{self._testMethodName[5:17]}"
        env = dict(os.environ, WLT_PRIVILEGED=f"{self.tmp / 'luxos-screenshot-ui'} {self.tmp / 'luxos-shot-wl-probe'}",
                   WLT_COMPOSITOR_ENV=f"LUXCOMP_VIRTUAL_INPUT=1 LUXWM_SYSTEM_CONFIG={self.conf} "
                                      f"LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib")
        r = subprocess.run([str(WLT), "start", "--mode", "headless", "--size", f"{W}x{H}", "--timeout", "600",
                            "--name", name, "--", str(LUXWM)], env=env, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            self.fail("wlt start: " + r.stdout + r.stderr)
        self.session = Path(r.stdout.strip().splitlines()[-1])
        self.env = {}
        for line in self.wlt("env", str(self.session)).splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            self.env[key] = value
        self.env.pop("LD_LIBRARY_PATH", None)        # GTK hostitele, ne knihovny sysrootu
        self.log = self.session / "shot.log"
        self.saved = self.session / "saved"
        self.env.update(GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GTK_A11Y="none", LUXOS_WL_LIB=str(self.tmp / "libluxos-wl.so.0"),
                        LUXOS_SCREENSHOT_TEST_LOG=str(self.log))

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        log = (self.session / "compositor.log").read_text(errors="replace")
        self.assertNotIn("Segmentation", log)
        subprocess.run([str(WLT), "stop", str(self.session)], capture_output=True)
        shutil.rmtree(self.session, True)

    # ---- pomucky ----

    def wlt(self, *args):
        r = subprocess.run([str(WLT), *args], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            self.fail(f"wlt {args[0]}: " + r.stdout + r.stderr)
        return r.stdout

    def client(self, title, size, color=BLUE):
        self.wlt("run", str(self.session), "--bg", "wlt-client", "--title", title, "--app-id", f"test.{title.lower()}",
                 "--size", size, "--color", color)
        time.sleep(0.8)

    def grim(self):
        path = self.session / "grim.ppm"
        self.wlt("shot", str(self.session), str(path))
        return ppm_read(path)

    def ui(self, *args, program=None, output=True, thumbnail=False):
        # --clipboard s --output uklada soubor (jako na X11): pro schranku bez slozky
        cmd = [str(program or self.tmp / "luxos-screenshot-ui"), *args]
        if not thumbnail:
            cmd += ["--no-thumbnail"]
        if output:
            cmd += ["--output", str(self.saved)]
        p = subprocess.Popen(cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.procs.append(p)
        return p

    def finish(self, p, timeout=15):
        out, err = p.communicate(timeout=timeout)
        self.assertNotIn("LSL callback error", err)
        return p.returncode, out, err

    def tlog(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def wait_log(self, prefix, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for line in self.tlog():
                if line.startswith(prefix):
                    return line
            time.sleep(0.05)
        self.fail(f"{prefix!r} neni v logu: {self.tlog()}")

    def files(self):
        return sorted(self.saved.glob("*.png")) if self.saved.exists() else []

    def one_png(self, out):
        files = self.files()
        self.assertEqual(len(files), 1, files)
        self.assertEqual(out.strip(), str(files[0]))
        return png_read(files[0])

    # ---- testy ----

    def test_screen(self):
        self.client("Okno", "400x300")
        want = self.grim()
        start = time.monotonic()
        code, out, err = self.finish(self.ui("--screen"))
        self.times["screen"] = (time.monotonic() - start) * 1000
        self.assertEqual(code, 0, err)
        got = self.one_png(out)
        self.assertEqual(got[:2], (W, H))
        self.assertGreaterEqual(len(colors(got)), 4)
        self.assertEqual(got[2], want[2], "snimek se lisi od grim")

    def test_region(self):
        self.client("Okno", "400x300")
        want = crop(self.grim(), 100, 50, 300, 200)
        code, out, err = self.finish(self.ui("--region", "100,50,300,200"))
        self.assertEqual(code, 0, err)
        got = self.one_png(out)
        self.assertEqual(got, want)

    def test_portion_drag(self):
        self.client("Okno", "400x300")
        before = self.grim()
        p = self.ui("--portion")
        line = self.wait_log("overlay portion")
        self.assertIn(f"size={W}x{H}", line)
        # prekryv ukazuje zmrazeny snimek ztmaveny mimo vyber
        shown = self.grim()
        self.assertNotEqual(shown[2], before[2])
        self.wlt("input", str(self.session), "drag 440 250 840 550 400")
        code, out, err = self.finish(p)
        self.assertEqual(code, 0, err)
        self.assertIn("selected 440 250 400 300", self.tlog())
        got = self.one_png(out)
        self.assertEqual(got[:2], (400, 300))
        self.assertEqual(got, crop(before, 440, 250, 400, 300))
        self.assertGreaterEqual(len(colors(got)), 3)
        # prekryv zmizel
        self.assertEqual(self.grim()[2], before[2])

    def test_window(self):
        self.client("Velke", "400x300")
        self.client("Male", "240x160", "20a040")
        before = self.grim()
        p = self.ui("--window")
        self.wait_log("overlay window windows=2")
        boxes = [json.loads(line.removeprefix("window-box ")) for line in self.tlog() if line.startswith("window-box ")]
        if boxes:
            rect = next(r for title, r in boxes if title == "Male")
            x, y, w, h = rect
            self.wlt("input", str(self.session), f"move {x + w // 2} {y + h // 2}", "click left")
            code, out, err = self.finish(p)
            self.assertEqual(code, 0, err)
            self.assertEqual(self.one_png(out), crop(before, x, y, w, h))
            return
        rows = [line.split(" ", 2) for line in self.tlog() if line.startswith("row ")]
        index = [r[2] for r in rows].index("test.male|Male")
        keys = "".join("key Down\n" for _ in range(index)) + "key Return\n"
        subprocess.run([str(WLT), "input", str(self.session)], input=keys, text=True, check=True, timeout=30)
        code, out, err = self.finish(p)
        self.assertEqual(code, 0, err)
        self.assertIn("window test.male|Male", self.tlog())
        got = self.one_png(out)
        # obsah okna bez titulku a stinu: presne jeho buffer, dole zakulacene rohy jako na obrazovce
        # (radius okna 16 px, vyhlazene okraje maji mezitony)
        self.assertEqual(got[:2], (240, 160))
        r = 16
        self.assertEqual(colors(crop(got, 0, 0, 240, 160 - r)), {"20a040", "105020"})
        self.assertEqual(colors(crop(got, r, 160 - r, 240 - 2 * r, r)) - {"20a040", "105020"}, set())
        corner = colors(crop(got, 0, 160 - r, r, r))
        self.assertGreater(len(corner), 2, "zakulaceny roh")

    def test_space_switches_and_escape_cancels(self):
        self.client("Okno", "400x300")
        before = self.grim()
        p = self.ui("--portion")
        self.wait_log("overlay portion")
        kb = subprocess.Popen([str(WLT), "input", str(self.session)], stdin=subprocess.PIPE, text=True)
        kb.stdin.write("key space\n")
        kb.stdin.flush()
        self.wait_log("overlay window windows=1")
        kb.stdin.write("key Escape\n")
        kb.stdin.close()
        kb.wait(30)
        code, out, err = self.finish(p)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.files(), [])
        self.assertIn("end 0", self.tlog())
        self.assertEqual(self.grim()[2], before[2])

    def test_right_click_cancels(self):
        p = self.ui("--portion")
        self.wait_log("overlay portion")
        self.wlt("input", str(self.session), "move 300 300", "click right")
        code, out, err = self.finish(p)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.files(), [])

    def test_clipboard(self):
        self.client("Okno", "400x300")
        p = self.ui("--portion", "--clipboard", output=False)
        self.wait_log("overlay portion")
        probe = subprocess.Popen([str(self.tmp / "luxos-shot-wl-probe"), "clip"], env=self.env,
                                 stdout=subprocess.PIPE, text=True)
        self.procs.append(probe)
        time.sleep(0.3)
        start = time.monotonic()
        self.wlt("input", str(self.session), "drag 400 200 700 450 300")
        self.wait_log("clipboard")
        out, _ = probe.communicate(timeout=15)
        self.times["drag to clipboard read"] = (time.monotonic() - start) * 1000
        self.assertEqual(probe.returncode, 0, out)
        self.assertIn("types image/png", out.splitlines())
        size = int([line for line in out.splitlines() if line.startswith("png ")][0].split()[1])
        self.assertGreater(size, 200)
        print(f"\n  image/png ve schrance: {size} B")
        # schranku prevzal jiny klient: drzitel obrazku skonci
        start = time.monotonic()
        code, out, err = self.finish(p)
        self.times["clipboard taken to exit"] = (time.monotonic() - start) * 1000
        self.assertEqual(code, 0, err)
        self.assertEqual(self.files(), [])

    def test_second_run_closes_selection(self):
        p = self.ui("--portion")
        self.wait_log("overlay portion")
        start = time.monotonic()
        code2, _, err2 = self.finish(self.ui("--portion"))
        code, _, err = self.finish(p)
        self.times["second run closes"] = (time.monotonic() - start) * 1000
        self.assertEqual((code, code2), (0, 0), err + err2)
        self.assertEqual(self.files(), [])
        self.assertEqual(len([line for line in self.tlog() if line.startswith("overlay")]), 1)

    def test_not_allowlisted_cannot_capture(self):
        self.client("Okno", "400x300")
        code, out, err = self.finish(self.ui("--screen", program=self.tmp / "other/luxos-screenshot-ui"))
        self.assertEqual(code, 1)
        self.assertIn("does not allow screen capture", err)
        self.assertEqual(self.files(), [])
        # pro srovnani: klient na allowlistu globaly vidi, stejny program jinde ne
        seen = subprocess.run([str(self.tmp / "luxos-shot-wl-probe"), "globals"], env=self.env, capture_output=True,
                              text=True, timeout=10).stdout
        self.assertIn("has ext_image_copy_capture_manager_v1 1", seen)
        self.assertIn("has ext_foreign_toplevel_image_capture_source_manager_v1 1", seen)

    def configure(self, **values):
        folder = Path(self.env["XDG_CONFIG_HOME"]) / "luxos"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "screenshot.json").write_text(json.dumps(dict(version=2, **values)))

    def test_toolbar_screen_capture_omits_own_ui(self):
        self.client("Okno", "400x300")
        before = self.grim()
        p = self.ui()
        line = self.wait_log("toolbar ").split()
        self.assertGreater(int(line[2]), H // 2, "lista ma byt dole jako na X11")
        self.wlt("input", str(self.session), "key 1", "key Return")
        code, out, err = self.finish(p)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.one_png(out), before)

    def test_toolbar_drag_waits_for_confirmation(self):
        self.configure(mode="portion", selection=[300, 200, 400, 300], remember=True)
        p = self.ui()
        self.wait_log("toolbar ")
        self.wlt("input", str(self.session), "drag 500 350 550 400 250")
        self.wait_log("selected 350 250 400 300")
        self.assertIsNone(p.poll())
        self.assertEqual(self.files(), [])
        self.wlt("input", str(self.session), "key Return")
        code, out, err = self.finish(p)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.one_png(out)[:2], (400, 300))

    def test_timer_escape_cancels_without_file(self):
        self.configure(mode="screen", timer=5)
        p = self.ui()
        self.wait_log("toolbar ")
        self.wlt("input", str(self.session), "key Return")
        self.wait_log("countdown 5")
        self.wlt("input", str(self.session), "key Escape")
        code, out, err = self.finish(p)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.files(), [])

    def test_preview_second_run_closes(self):
        p = self.ui("--screen", thumbnail=True)
        self.wait_log("thumb copy,reveal,save_as,delete,close")
        self.assertIsNone(p.poll())
        code2, _, err2 = self.finish(self.ui("--portion"))
        code, out, err = self.finish(p)
        self.assertEqual((code, code2), (0, 0), err + err2)
        self.assertEqual(self.one_png(out)[:2], (W, H))

    def test_recording_not_available(self):
        code, out, err = self.finish(self.ui("--record-screen"))
        self.assertEqual(code, 1)
        self.assertEqual(self.files(), [])


if __name__ == "__main__":
    unittest.main()
