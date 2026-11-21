#!/usr/bin/env python3
"""Kresba zamku a prihlasovaci obrazovky (files/lsl/luxos_lock_draw.lsl) bez kompozitoru: vzory a cena snimku.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=1G -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_lock_draw.py -v

tests/lock/lock-render.lsl kresli stavy (klid, vyzva, spatne heslo, Caps Lock, otisk prstu, prihlaseni) do PNG.
Tapety jsou umele (svetla a tmava, generuje test), at vzory nezavisi na balicku tapet. Vzory: tests/wl-lock-goldens
v polovicni velikosti, porovnani s toleranci (pismo z hostitele). Novy vzor: LUXOS_LOCK_UPDATE_GOLDENS=1.
Cena snimku se meri pri 1920x1080 do obrazku ARGB32 (jako bufer wl_shm, pixman): prumer <= 8 ms.
"""
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import unittest
import zlib

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
REPO = PKG.parent.parent
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
GOLDENS = HERE / "wl-lock-goldens"
UPDATE = os.environ.get("LUXOS_LOCK_UPDATE_GOLDENS") == "1"
OUT = REPO / "out/lock-draw-test"
LOCK_STATES = ["idle", "prompt", "wrong", "caps", "fingerprint"]
GREETER_STATES = ["greeter", "greeter-wrong"]
FRAME_BUDGET_US = 8000


def png_write(path, width, height, rgb):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    rows = b"".join(b"\0" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def png_read(path):
    """8bit RGB/RGBA bez prokladani -> (sirka, vyska, RGB)."""
    data = Path(path).read_bytes()
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
        if f == 2:
            line = bytearray((line[i] + prev[i]) & 255 for i in range(stride))
        elif f:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                if f == 1:
                    line[i] = (line[i] + a) & 255
                elif f == 3:
                    line[i] = (line[i] + (a + b) // 2) & 255
                elif f == 4:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        out += line if bpp == 3 else bytes(v for i, v in enumerate(line) if i % 4 != 3)
    return width, height, bytes(out)


def wallpaper(path, dark):
    """Umela tapeta 960x600: plynuly prechod se dvema vlnami (svetla pastelova / tmava modrofialova)."""
    w, h = 960, 600
    if dark:
        a, b, c = (22, 26, 58), (70, 40, 110), (20, 90, 120)
    else:
        a, b, c = (250, 196, 120), (240, 110, 120), (150, 200, 120)
    rgb = bytearray()
    for y in range(h):
        for x in range(w):
            t = x / w
            wave = 0.5 + 0.5 * math.sin(x / 90.0 + y / 70.0) * math.cos(y / 110.0)
            k = min(1.0, max(0.0, y / h * 0.7 + wave * 0.3))
            for i in range(3):
                top = a[i] + (b[i] - a[i]) * t
                rgb.append(int(top + (c[i] - top) * k * 0.6))
    png_write(path, w, h, bytes(rgb))


@unittest.skipUnless(LSLC, "chybi lslc")
class LockDraw(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shutil.rmtree(OUT, True)
        OUT.mkdir(parents=True)
        cls.render = OUT / "lock-render"
        r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(PKG / "files/lsl"),
                            str(HERE / "lock/lock-render.lsl"), str(cls.render)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        cls.walls = {}
        for mode in ("light", "dark"):
            cls.walls[mode] = OUT / f"wall-{mode}.png"
            wallpaper(cls.walls[mode], mode == "dark")

    def run_render(self, out, size, scale, wall, states, lang="en", half=False):
        out.mkdir(parents=True, exist_ok=True)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(OUT), "TZ": "UTC", "LANG": "cs_CZ.UTF-8" if lang == "cs" else "en_US.UTF-8",
               "LUXOS_I18N_DIR": str(REPO / "packages/luxos-i18n/files")}
        if half:
            env["LOCK_RENDER_HALF"] = "1"
        r = subprocess.run([str(self.render), str(out), str(size[0]), str(size[1]), str(scale), str(wall), *states],
                           capture_output=True, text=True, env=env, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        result = {}
        for line in r.stdout.splitlines():
            words = line.split()
            if words[0] == "frame":
                result[words[1]] = (float(words[2]), float(words[3]))
            elif words[0] in ("fade", "soft", "sharp"):
                result[words[0]] = tuple(float(v) for v in words[1:])
        return result

    def compare(self, name, path):
        golden = GOLDENS / f"{name}.png"
        keep = Path(os.environ.get("LUXOS_LOCK_SHOTS") or OUT / "shots")
        keep.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, keep / f"{name}.png")
        if UPDATE or not golden.exists():
            GOLDENS.mkdir(exist_ok=True)
            shutil.copy(path, golden)
            if not UPDATE:
                self.skipTest(f"vzor {golden} vytvoren")
        want, got = png_read(golden), png_read(path)
        self.assertEqual(want[:2], got[:2], "jina velikost nez vzor")
        a, b = want[2], got[2]
        diff = [abs(a[i] - b[i]) for i in range(len(a))]
        bad = sum(1 for i in range(0, len(diff), 3) if max(diff[i:i + 3]) > 48) / (len(diff) // 3)
        mean = sum(diff) / len(diff)
        self.assertLess(mean, 3.0, f"{path} se lisi od {golden} (prumer {mean:.2f})")
        self.assertLess(bad, 0.01, f"{path} se lisi od {golden} ({bad * 100:.2f} % pixelu)")
        return mean, bad

    def goldens(self, lang, mode):
        out = OUT / f"{lang}-{mode}"
        self.run_render(out, (1280, 800), 1, self.walls[mode], LOCK_STATES + GREETER_STATES, lang, half=True)
        worst = 0.0
        created = []
        for state in LOCK_STATES + GREETER_STATES:
            try:
                mean, bad = self.compare(f"{lang}-{mode}-{state}", out / f"{state}.png")
                worst = max(worst, mean)
            except unittest.SkipTest as e:
                created.append(str(e))
        if created:
            self.skipTest(", ".join(created))
        print(f"\n  {lang}-{mode}: {len(LOCK_STATES + GREETER_STATES)} goldens, worst mean diff {worst:.2f}")

    def test_goldens_en_light(self):
        self.goldens("en", "light")

    def test_goldens_en_dark(self):
        self.goldens("en", "dark")

    def test_goldens_cs_light(self):
        self.goldens("cs", "light")

    def test_goldens_cs_dark(self):
        self.goldens("cs", "dark")

    def test_states_differ(self):
        """Kazdy stav vypada jinak: klid bez pole, chyba neni totez co vyzva (drive spatne heslo = beze zmeny)."""
        out = OUT / "differ"
        self.run_render(out, (1280, 800), 1, self.walls["light"], LOCK_STATES, half=True)
        images = {s: png_read(out / f"{s}.png")[2] for s in LOCK_STATES}
        # pole a hlasky v polovicni velikosti (pole y ~284-299)
        def box(img, x0, y0, x1, y1):
            return [img[(y * 640 + x) * 3:(y * 640 + x) * 3 + 3] for y in range(y0, y1) for x in range(x0, x1)]
        for a, b in [("idle", "prompt"), ("prompt", "wrong"), ("prompt", "caps"), ("prompt", "fingerprint")]:
            changed = sum(p != q for p, q in zip(box(images[a], 200, 262, 440, 320), box(images[b], 200, 262, 440, 320)))
            self.assertGreater(changed, 150, f"{a} a {b} se pod avatarem nelisi")

    def test_frame_cost_1080p(self):
        result = self.run_render(OUT / "perf", (1920, 1080), 1, self.walls["light"],
                                 ["idle", "prompt", "typed", "wrong", "busy", "greeter", "greeter-menu"])
        print("\n  1920x1080 frame cost [avg us, max us]: " + ", ".join(f"{k} {v[0]:.0f}/{v[1]:.0f}" for k, v in result.items()
                                                                     if k not in ("soft", "sharp")))
        print(f"  wallpaper scale {result['sharp'][0]:.0f} ms, blur {result['soft'][0]:.0f} ms (once per wallpaper and size)")
        for state, value in result.items():
            if state in ("soft", "sharp"):
                continue
            avg = value[0]
            self.assertLess(avg, FRAME_BUDGET_US, f"{state}: {avg:.0f} us per frame")
        self.assertLess(result["soft"][0], 500)

    def test_hidpi_scale_2(self):
        """Meritko 2: bufer 2x, stejne rozvrzeni jako 1x (zmensenina se lisi jen hranami pisma)."""
        one = OUT / "scale1"
        two = OUT / "scale2"
        self.run_render(one, (1280, 800), 1, self.walls["dark"], ["wrong"], half=True)
        cost = self.run_render(two, (1280, 800), 2, self.walls["dark"], ["wrong"], half=True)
        full = OUT / "scale2-full"
        self.run_render(full, (1280, 800), 2, self.walls["dark"], ["wrong"])
        self.assertEqual(png_read(full / "wrong.png")[:2], (2560, 1600))
        a, b = png_read(one / "wrong.png")[2], png_read(two / "wrong.png")[2]
        mean = sum(abs(a[i] - b[i]) for i in range(len(a))) / len(a)
        print(f"\n  scale 2 vs 1 mean diff {mean:.2f}, frame {cost['wrong'][0]:.0f} us at 2560x1600")
        self.assertLess(mean, 4.0)


if __name__ == "__main__":
    unittest.main()
