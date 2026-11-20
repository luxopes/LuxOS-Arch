#!/usr/bin/env python3
"""luxos_material.lsl: sklo pro plochy layer-shell (Wayland) dava stejne pixely jako dosavadni material v C.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_material.py -v

Reference je material z luxos-glass.c (vetev gpt-features-1.1.1, vyrez v glass-ref/luxos-glass-material.c),
ktery sam odpovida widgetum na plose (luxos-widgets.lsl). Prahy jako test_luxos_glass_module.py: rozmazana
tapeta pixel po pixelu shodna, volba svetleho skla shodna, zavoj na 12 mist, kontrast textu >= 4,5 : 1.
Navic hotove karty skla (pas listy, vyskakovaci okno, Dock, oznameni, okraje vystupu) bez jedineho
odlisneho pixelu a casy generovani materialu v rozpoctu (viz test_timing_budget).
LUXOS_LSLC: prekladac lslc (jinak lslc z PATH). Vypisy pixelu maji desitky MB: TMPDIR mimo tmpfs.
"""
import glob
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
REPO = PKG.parent.parent
REF = HERE / "glass-ref"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
CC = shutil.which("gcc")
GPT_REF = "gpt-features-1.1.1:packages/luxos-desktop/files/src/luxos-glass.c"


def pkg_flags():
    r = subprocess.run(["pkg-config", "--cflags", "--libs", "gtk+-3.0"], capture_output=True, text=True)
    return r.stdout.split() if r.returncode == 0 else None


def rgb(pixel):
    return [(pixel >> shift & 255) / 255 for shift in (16, 8, 0)]


def luminance(color):
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in color]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(pixel, light, veil, alpha):
    worst = None
    for sheen in (0, 0.08):
        background = [(v * (1 - veil) + int(light) * veil) * (1 - sheen) + sheen for v in rgb(pixel)]
        ink = (25 / 255, 31 / 255, 43 / 255) if light else (1, 1, 1)
        foreground = [i * alpha + v * (1 - alpha) for i, v in zip(ink, background)]
        values = sorted((luminance(foreground), luminance(background)))
        c = (values[1] + 0.05) / (values[0] + 0.05)
        worst = c if worst is None else min(worst, c)
    return worst


def parse_dump(path):
    glasses, cases = [], []
    for line in Path(path).read_text().splitlines():
        f = line.split(" ")
        if f[0] == "glass":
            glasses.append((f[1], int(f[2]), int(f[3]), [float(v) for v in f[4:9]], [int(v) for v in f[9:]]))
        elif f[0] == "case":
            cases.append((int(f[1]), f[2] == "1", [int(v) for v in f[3:]]))
    return glasses, cases


def channel_diff(a, b):
    return max(abs((a >> s & 255) - (b >> s & 255)) for s in (0, 8, 16, 24))


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, timeout=kw.pop("timeout", 300), **kw)


@unittest.skipUnless(CC and pkg_flags() and LSLC, "needs gcc, gtk+-3.0 headers and lslc")
class Material(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="luxos-material-"))
        cls.ref = cls.tmp / "material-ref"
        r = run([CC, "-O2", "-Wall", "-Werror", "-I", str(REF), "-o", str(cls.ref), str(REF / "material-ref.c"),
                 *pkg_flags(), "-lm"])
        if r.returncode:
            raise AssertionError(r.stdout + r.stderr)
        for f in glob.glob(str(PKG / "files/lsl/*.lsl")):
            shutil.copy(f, cls.tmp)
        shutil.copy(HERE / "lsl/luxos-material-test.lsl", cls.tmp)
        cls.lsl = cls.tmp / "material-test"
        r = run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(cls.tmp), str(cls.tmp / "luxos-material-test.lsl"), str(cls.lsl)])
        if r.returncode:
            raise AssertionError(r.stdout + r.stderr)
        cls.walls = cls.tmp / "walls"
        cls.walls.mkdir()
        subprocess.check_call([str(cls.ref), "gen", str(cls.walls)], timeout=60)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def cases(self):
        rows = []
        for wall, W, H in (("gradient.png", 1920, 1080), ("noise.png", 1920, 1080), ("noise.jpg", 1920, 1080),
                           ("portrait.png", 1366, 768), ("portrait.png", 2560, 1440), ("tiny.png", 1920, 1080)):
            path = str(self.walls / wall)
            for x, y, w, h, radius, ink in (
                    (0, 0, W, 32, 0, -1),                  # pas listy
                    (W - 360, 40, 340, 420, 18, 1),        # vyskakovaci okno, tmavy text
                    (W - 360, 40, 340, 420, 18, 0),        # totez s bilym textem
                    ((W - 640) // 2, H - 80, 640, 72, 22, -1),   # Dock
                    (W - 376, 48, 360, 90, 14, -1),        # oznameni
                    (W - 300, H - 160, 300, 160, 22, -1),  # roh vystupu (orez vyrezu nahore)
                    (-50, -20, 200, 100, 16, -1),          # mimo vystup (orez vyrezu dole)
                    (100, 100, 3, 2, 16, -1),              # polomer vetsi nez polovina
                    (200, 150, 480, 320, 16, -1)):         # okno
                rows.append("%s %d %d %d %d %d %d %s %d" % (path, W, H, x, y, w, h, radius, ink))
        return rows

    def test_same_pixels_as_c_material(self):
        cases = self.tmp / "cases.txt"
        cases.write_text("\n".join(self.cases()) + "\n")
        c_out, l_out = self.tmp / "c.txt", self.tmp / "l.txt"
        subprocess.check_call([str(self.ref), "dump", str(cases), str(c_out)], timeout=120)
        r = run([str(self.lsl), "dump", str(cases), str(l_out)], timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        c_glass, c_cases = parse_dump(c_out)
        l_glass, l_cases = parse_dump(l_out)
        self.assertEqual(len(c_glass), 6)
        self.assertEqual(len(l_glass), len(c_glass))
        for (wall, W, H, cmap, cpix), (lwall, lW, lH, lmap, lpix) in zip(c_glass, l_glass):
            self.assertEqual((wall, W, H), (lwall, lW, lH))
            for a, b in zip(cmap, lmap):
                self.assertAlmostEqual(a, b, places=12, msg=("mapa", wall, W, H))
            self.assertEqual(len(cpix), len(lpix))
            # RGB24: horni bajt se nepouziva
            self.assertEqual([p & 0xFFFFFF for p in cpix], [p & 0xFFFFFF for p in lpix], ("rozmazana tapeta", wall))
        self.assertEqual(len(l_cases), len(c_cases))
        total = 0
        for (n, c_light, cpix), (_, l_light, lpix) in zip(c_cases, l_cases):
            self.assertEqual(c_light, l_light, ("svetle sklo", self.cases()[n]))
            self.assertEqual(len(cpix), len(lpix))
            bad = [(a, b) for a, b in zip(cpix, lpix) if a != b]
            worst = max((channel_diff(a, b) for a, b in bad), default=0)
            self.assertEqual(len(bad), 0, "%s: %d odlisnych pixelu, nejvetsi rozdil %d" % (self.cases()[n], len(bad), worst))
            total += len(cpix)
        print("\n  material: %d karet, %d pixelu shodnych s C" % (len(c_cases), total), file=sys.stderr)

    def test_basics_like_glass_module(self):
        c = json.loads(subprocess.check_output([str(self.ref), "basics"], text=True, timeout=30))
        lsl = json.loads(subprocess.check_output([str(self.lsl), "basics"], text=True, timeout=30))
        self.assertEqual(c["solid"], lsl["solid"], "rozmazana tapeta pixel po pixelu")
        self.assertEqual(c["edge"], lsl["edge"], "prechod ostre hrany")
        for (light, veil, vl, vd), (l_light, l_veil, l_vl, l_vd) in zip(c["styles"], lsl["styles"]):
            self.assertEqual(light, l_light)
            self.assertAlmostEqual(veil, l_veil, places=12)
            self.assertAlmostEqual(vl, l_vl, places=12)
            self.assertAlmostEqual(vd, l_vd, places=12)
        # barva textu podle tapety (oznameni) i vynucena (nabidky podle motivu) drzi kontrast na kazde tapete
        for pixel, (light, veil, veil_light, veil_dark) in zip(lsl["solid"], lsl["styles"]):
            for alpha in (1.0, 0.90):
                self.assertGreaterEqual(contrast(pixel, light, veil, alpha), 4.5, (rgb(pixel), light, veil))
            self.assertGreaterEqual(contrast(pixel, True, veil_light, 1.0), 4.5, ("tmavy text", rgb(pixel)))
            self.assertGreaterEqual(contrast(pixel, False, veil_dark, 1.0), 4.5, ("bily text", rgb(pixel)))

    def test_reference_is_verbatim_copy(self):
        r = run(["git", "-C", str(REPO), "show", GPT_REF], timeout=30)
        if r.returncode:
            self.skipTest("vetev gpt-features-1.1.1 neni k dispozici")
        branch = r.stdout.splitlines()
        fixture = (REF / "luxos-glass-material.c").read_text().splitlines()
        body = fixture[fixture.index("#define GLASS_SIZE 96"):]
        self.assertEqual(body, branch[48:297])

    def api(self, conf, mode=None):
        home = self.tmp / ("cfg-%d" % len(conf))
        (home / "luxos").mkdir(parents=True, exist_ok=True)
        (home / "luxos/appearance.conf").write_text(conf)
        if mode:
            (home / "luxos/appearance").write_text(mode + "\n")
        env = dict(os.environ, XDG_CONFIG_HOME=str(home))
        r = run([str(self.lsl), "api"], env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_wallpaper_from_luxos_config_and_cache(self):
        noise, portrait = self.walls / "noise.jpg", self.walls / "portrait.png"
        out = self.api('BAR_OPACITY=62\nWALLPAPER="%s"\nWALLPAPER_HDMI_A_1=%s\n' % (noise, portrait))
        self.assertEqual(out["wallpaper"], str(noise), "WALLPAPER v uvozovkach")
        self.assertEqual(out["wallpaper_hdmi"], str(portrait), "tapeta jen pro vystup HDMI-A-1")
        self.assertTrue(out["same_surface"], "druhy dotaz = stejny povrch z mezipameti")
        self.assertEqual(out["hidpi_size"], [3840, 64], "scale 2: povrch v pixelech zarizeni")
        self.assertEqual(out["strips_cached"], 16, "mezipamet ma strop")
        self.assertEqual(out["after_forget"], 0)
        self.assertEqual(out["after_reload"], [0, 0])
        self.assertTrue(out["none_without_size"])

    def test_default_wallpaper_by_mode(self):
        out = self.api("WALLPAPER=/nonexistent/wall.jpg\n", "dark")
        default = "/usr/share/backgrounds/luxos/luxos-dark.jpg"
        self.assertEqual(out["wallpaper"], default if os.path.exists(default) else "")

    def test_layer_positions(self):
        out = self.api("WALLPAPER=%s\n" % (self.walls / "gradient.png"))
        self.assertEqual(out["layers"], [
            [0, 0, 1920, 32],        # lista: nahore pres celou sirku
            [660, 1002, 600, 70],    # Dock: dole na stred, okraj 8
            [1568, 40, 340, 400],    # popup vpravo nahore pod listou (plocha bez exkluzivni zony)
            [760, 390, 400, 300],    # bez kotvy: na stred
            [0, 0, 1920, 1080],      # vsechny kotvy, velikost 0: cely vystup
            [20, 515, 1890, 50],     # vlevo+vpravo s okraji, svisle na stred
            [1926, 956, 64, 64]])    # druhy vystup vpravo: vlevo dole

    def test_timing_budget(self):
        # Rozpocty (ms) s rezervou ~3x nad namerenym na vyvojovem PC (Ryzen 5 5500U, 2026-11-20):
        #   blur 16, glass_jpg 20, glass_png 53-66 (z toho ~35 dekodovani PNG v libpng), first_strip 23-31,
        #   strip 1.8 (C 1.6), popup 2.9, cached_strip 0.035.
        # Pixely se pocitaji jen pri zmene tapety (prvni pas listy po zmene <= 150 ms je jednorazova prodleva
        # spolu s prechodem tapety); nova karta skla (strip, popup) je kresleni cairo v C a musi se vejit do pul
        # snimku 60 Hz (8 ms); kazdy dalsi snimek jen vezme hotovy povrch (<= 0.5 ms).
        budget = {"blur_ms": 60, "glass_jpg_ms": 100, "glass_png_ms": 250, "first_strip_ms": 150,
                  "strip_ms": 8, "popup_ms": 12, "cached_strip_ms": 0.5}
        noise = self.walls / "noise.jpg"
        home = self.tmp / "cfg-bench"
        (home / "luxos").mkdir(parents=True, exist_ok=True)
        (home / "luxos/appearance.conf").write_text("WALLPAPER=%s\n" % noise)
        r = run([str(self.lsl), "bench", str(self.walls)], env=dict(os.environ, XDG_CONFIG_HOME=str(home)), timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lsl = json.loads(r.stdout)
        c = json.loads(subprocess.check_output([str(self.ref), "bench", str(self.walls)], text=True, timeout=120))
        print("\n  LSL " + ", ".join("%s %.3f" % kv for kv in sorted(lsl.items())), file=sys.stderr)
        print("  C   " + ", ".join("%s %.3f" % kv for kv in sorted(c.items())), file=sys.stderr)
        for key, limit in budget.items():
            self.assertLessEqual(lsl[key], limit, key)
        # kresleni karty je cairo v C v obou pripadech; LSL smi pridat jen rezii volani
        self.assertLessEqual(lsl["strip_ms"], 3 * c["strip_ms"] + 0.5)
        self.assertLessEqual(lsl["glass_jpg_ms"], 4 * c["glass_jpg_ms"] + 10)


if __name__ == "__main__":
    unittest.main()
