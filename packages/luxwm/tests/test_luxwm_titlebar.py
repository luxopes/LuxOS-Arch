"""Jedno zahlavi pro okna se zahlavim kompozitoru (SSD, libluxcomp deco.c) i GTK headerbarem (CSD, luxos-themes
luxos-gtk3.css) podle tokens.TITLEBAR (design review 1.1.0, cast 10): vyska 38 px (nizke 30 px), svetla 12 px
na stejnych mistech, stejny nazev, barva zahlavi podle obsahu okna (tmavy terminal = tmave zahlavi), obrys
a zaobleni 12 px. Dale umisteni novych oken: okraj 8 px od listy a Docku, vysoke okno se zmensi, okno, ktere
se po namapovani samo zvetsi, se vrati nad Dock.

Okna GTK pouzivaji tema WhiteSur z hostitele s luxos.css z tohoto stromu (soukroma kopie, GTK_THEME);
bez nainstalovaneho WhiteSur se testy CSD preskoci. Vse headless (scripts/wl-test), nikdy skutecna obrazovka.

  packages/luxwm/tests/build-host.sh
  env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
    systemd-run --user --scope -p TasksMax=300 -p MemoryMax=1G -- timeout 900 \\
    python3 -m unittest -v packages/luxwm/tests/test_luxwm_titlebar.py

Vzorove snimky zahlavi kompozitoru: tests/golden/titlebar-*.png (LUXWM_UPDATE_GOLDEN=1 je prepise).
Snimky z behu a list SSD vedle CSD: out/luxwm-test/results/titlebar-*.
"""
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import unittest
import zlib

sys.path.insert(0, os.path.dirname(__file__))
from test_luxwm import BUILD, RESULTS, W, H, Session, frame, wlt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
CLIENT = os.path.join(HERE, "clients", "gtk-window.py")
GOLDEN = os.path.join(HERE, "golden")
CSS = os.path.join(ROOT, "packages", "luxos-themes", "files", "luxos-gtk3.css")
TOKENS = os.path.join(ROOT, "packages", "luxos-desktop", "files", "lsl", "luxos_tokens.lsl")
HOST_THEMES = "/usr/share/themes"
BAR = 28
DOCK = 74


def titlebar_tokens():
    with open(TOKENS) as f:
        text = f.read()
    block = text[text.index("TITLEBAR = {"):]
    block = block[:block.index("}") + 1]
    return {k: float(v) if "." in v else int(v) for k, v in re.findall(r'"(\w+)": (-?[\d.]+)(?=[,}])', block)}


SPEC = titlebar_tokens()


# ---- obrazky -------------------------------------------------------------------------------

class Image:
    def __init__(self, w, h, data):
        self.w, self.h, self.data = w, h, bytearray(data)

    @classmethod
    def ppm(cls, path):
        with open(path, "rb") as f:
            data = f.read()
        parts = data.split(maxsplit=4)
        w, h = int(parts[1]), int(parts[2])
        return cls(w, h, data[len(data) - w * h * 3:])

    @classmethod
    def png(cls, path):
        """Jen PNG zapsane funkci save() (RGB 8 bitu, filtr 0)"""
        with open(path, "rb") as f:
            data = f.read()
        w, h = struct.unpack(">II", data[16:24])
        idat, pos = b"", 8
        while pos < len(data):
            n, kind = struct.unpack(">I4s", data[pos:pos + 8])
            if kind == b"IDAT":
                idat += data[pos + 8:pos + 8 + n]
            pos += 12 + n
        raw = zlib.decompress(idat)
        rows = [raw[y * (w * 3 + 1) + 1:(y + 1) * (w * 3 + 1)] for y in range(h)]
        return cls(w, h, b"".join(rows))

    def save(self, path):
        raw = b"".join(b"\0" + bytes(self.data[y * self.w * 3:(y + 1) * self.w * 3]) for y in range(self.h))

        def chunk(kind, body):
            return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))

    def px(self, x, y):
        i = (y * self.w + x) * 3
        return tuple(self.data[i:i + 3])

    def crop(self, x, y, w, h):
        """Vyrez; mimo obrazek sedy"""
        out = Image(w, h, bytes([128, 128, 128]) * (w * h))
        x0, x1 = max(x, 0), min(x + w, self.w)
        for r in range(max(y, 0), min(y + h, self.h)):
            i = (r * self.w + x0) * 3
            j = ((r - y) * w + x0 - x) * 3
            out.data[j:j + (x1 - x0) * 3] = self.data[i:i + (x1 - x0) * 3]
        return out

    def paste(self, img, x, y):
        for r in range(img.h):
            i = ((y + r) * self.w + x) * 3
            self.data[i:i + img.w * 3] = img.data[r * img.w * 3:(r + 1) * img.w * 3]


def lum(c):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def near(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def diff_share(a, b, tol=12):
    """Podil pixelu, ktere se lisi o vic nez tol v nekterem kanalu"""
    bad = sum(1 for i in range(0, len(a.data), 3)
              if max(abs(a.data[i + c] - b.data[i + c]) for c in range(3)) > tol)
    return bad / (a.w * a.h)


def analyse(img, f, height, inset=SPEC["inset"]):
    """Zahlavi okna s ramem f = [x, y, w] a vyskou zahlavi: barva, svetla, nazev"""
    x0, y0, w = f
    bg = img.px(x0 + w - 30, y0 + height // 2)
    lights = []
    # pasy kolem ocekavanych stredu, od x = 6: zaobleny roh a obrys okna k semaforu nepatri
    half = SPEC["pitch"] // 2
    for i in range(3):
        lo, hi = max(6, inset + i * SPEC["pitch"] - half), inset + i * SPEC["pitch"] + half
        pts = [(x, y) for y in range(y0 + 4, y0 + height - 2) for x in range(x0 + lo, x0 + hi)
               if max(abs(a - b) for a, b in zip(img.px(x, y), bg)) > 14]
        if pts:
            lights.append((sum(p[0] for p in pts) / len(pts) - x0, sum(p[1] for p in pts) / len(pts) - y0,
                           max(p[0] for p in pts) - min(p[0] for p in pts) + 1))
    ink, box = 0.0, None
    lb = lum(bg)
    for y in range(y0 + 2, y0 + height - 2):
        for x in range(x0 + w // 4, x0 + 3 * w // 4):
            d = abs(lum(img.px(x, y)) - lb)
            if d > 0.06:
                ink += d
                box = (min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y)) if box else (x, y, x, y)
    title = (box[0] - x0, box[1] - y0, box[2] - box[0] + 1, box[3] - box[1] + 1) if box else None
    darkest = min((img.px(x, y) for y in range(y0 + 4, y0 + height - 4) for x in range(x0 + w // 4, x0 + 3 * w // 4)),
                  key=lambda c: abs(lum(c) - lb) * -1)
    return {"bg": bg, "lights": lights, "title": title, "ink": ink, "contrast": contrast(darkest, bg)}


def content_top(img, f):
    """Prvni radek modreho obdelniku (12 px pod zahlavim okna --themed)"""
    x = f[0] + f[2] - 40
    for y in range(f[1], f[1] + f[3]):
        r, g, b = img.px(x, y)
        if b > 150 and r < 110 and g < 140:
            return y - f[1]
    return None


# ---- sezeni s okny GTK ----------------------------------------------------------------------

def have_gtk():
    return subprocess.run([sys.executable, "-c", "import gi; gi.require_version('Gtk', '3.0')"],
                          capture_output=True).returncode == 0


def have_whitesur():
    return all(os.path.exists(os.path.join(HOST_THEMES, "WhiteSur-" + v, "gtk-3.0", "gtk.gresource"))
               for v in ("Light", "Dark"))


def private_themes(base):
    """WhiteSur z hostitele s luxos.css z tohoto stromu (jako balik luxos-themes)"""
    for v in ("Light", "Dark"):
        dst = os.path.join(base, "themes", "LuxTest-" + v, "gtk-3.0")
        os.makedirs(dst, exist_ok=True)
        src = os.path.join(HOST_THEMES, "WhiteSur-" + v, "gtk-3.0")
        shutil.copy(os.path.join(src, "gtk.gresource"), dst)
        with open(os.path.join(dst, "gtk.css"), "w") as f:
            f.write('@import url("resource:///org/gnome/theme/gtk.css");\n\n@import url("luxos.css");\n')
        shutil.copy(CSS, os.path.join(dst, "luxos.css"))
    return base


def set_dark(s):
    cfg = os.path.join(s.dir, "config", "luxos")
    os.makedirs(cfg, exist_ok=True)
    with open(os.path.join(cfg, "appearance"), "w") as f:
        f.write("dark\n")
    os.kill(s.pid, 10)     # SIGUSR1: luxwm znovu nacte vzhled
    time.sleep(0.4)


class GtkSession:
    def __init__(self, dark=False):
        self.s = Session()
        if dark:
            set_dark(self.s)
        self.env = {}
        for line in wlt("env", self.s.dir).splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            self.env[key] = value
        self.env.pop("LD_LIBRARY_PATH", None)
        data = private_themes(os.path.join(self.s.dir, "data"))
        self.env.update(GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GTK_A11Y="none", XDG_DATA_HOME=data,
                        GTK_THEME="LuxTest-Dark" if dark else "LuxTest-Light", GSETTINGS_BACKEND="memory")
        self.procs = []

    def window(self, *args, title="Monitory", size="500x300", app="luxos-test"):
        p = subprocess.Popen([sys.executable, "-u", CLIENT, *args, "--themed", "--title", title, "--size", size,
                              "--app-id", app], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True)
        self.procs.append(p)
        assert p.stdout.readline().strip() == "mapped"
        time.sleep(0.8)
        return self.s.state()["views"][title.replace(" ", "_")]

    def stop(self):
        for p in self.procs:
            p.terminate()
            p.wait(5)
        log = self.s.log()
        self.s.stop()
        assert "LSL callback error" not in log


def golden_check(test, img, name):
    path = os.path.join(GOLDEN, name + ".png")
    img.save(os.path.join(RESULTS, "titlebar-" + name + ".png"))
    if os.environ.get("LUXWM_UPDATE_GOLDEN") == "1" or not os.path.exists(path):
        os.makedirs(GOLDEN, exist_ok=True)
        img.save(path)
        if os.environ.get("LUXWM_UPDATE_GOLDEN") != "1":
            test.fail(f"golden {name} missing, written - review and commit it")
        return
    ref = Image.png(path)
    test.assertEqual((ref.w, ref.h), (img.w, img.h), name)
    share = diff_share(ref, img)
    test.assertLess(share, 0.005, f"{name}: {share:.2%} pixels differ from the golden")


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")), "build first: packages/luxwm/tests/build-host.sh")
class Titlebar(unittest.TestCase):
    def gtk(self, dark=False):
        g = GtkSession(dark)
        self.addCleanup(g.stop)
        return g

    def plain(self, dark=False):
        s = Session()
        self.addCleanup(s.stop)
        if dark:
            set_dark(s)
        return s

    @unittest.skipUnless(have_gtk() and have_whitesur(), "python3-gobject and WhiteSur on the host")
    def test_ssd_and_csd_identical(self):
        """Stejna aplikace LuxOS se zahlavim kompozitoru a s headerbarem: stejna vyska, svetla, nazev, barva"""
        for dark in (False, True):
            mode = "dark" if dark else "light"
            with self.subTest(mode=mode):
                g = self.gtk(dark)
                ssd = g.window("--plain", title="Monitory SSD", app="luxos-test-ssd", size="360x220")
                csd = g.window("--headerbar", title="Monitory CSD", app="luxos-test-csd", size="360x220")
                self.assertEqual(ssd["top"], SPEC["height"], "LuxOS app: normal title bar")
                self.assertEqual(csd["top"], 0)
                fs, fc = frame(ssd), frame(csd)
                shots = {}
                for focus, other in (("ssd", fc), ("csd", fs)):
                    target = fs if focus == "ssd" else fc
                    g.s.input("move %d %d" % (target[0] + target[2] // 2, target[1] + target[3] - 30), "click")
                    time.sleep(0.3)
                    shots[focus] = Image.ppm(g.s.shot(f"titlebar-pair-{mode}-{focus}.ppm"))
                states = {"active": (shots["ssd"], shots["csd"]), "inactive": (shots["csd"], shots["ssd"])}
                sheet_rows = []
                for state, (img_s, img_c) in states.items():
                    hs, hc = content_top(img_s, fs) - 12, content_top(img_c, fc) - 12
                    self.assertEqual((hs, hc), (SPEC["height"], SPEC["height"]), f"{mode} {state} heights")
                    a = analyse(img_s, fs[:3], hs)
                    b = analyse(img_c, fc[:3], hc)
                    print(f"\n{mode} {state}: ssd {a}\n{' ' * len(mode + state)}  csd {b}")
                    self.assertTrue(near(a["bg"], b["bg"], 3), f"{mode} {state} bar colour {a['bg']} vs {b['bg']}")
                    self.assertEqual(len(a["lights"]), 3)
                    self.assertEqual(len(b["lights"]), 3)
                    for i, (la, lc) in enumerate(zip(a["lights"], b["lights"])):
                        want_x = SPEC["inset"] + i * SPEC["pitch"]
                        self.assertAlmostEqual(la[0], want_x, delta=1.0, msg=f"ssd light {i} x")
                        self.assertAlmostEqual(lc[0], want_x, delta=1.0, msg=f"csd light {i} x")
                        self.assertAlmostEqual(la[1], SPEC["height"] / 2, delta=1.0)
                        self.assertAlmostEqual(lc[1], SPEC["height"] / 2, delta=1.0)
                        self.assertAlmostEqual(la[2], SPEC["light"], delta=1)
                        self.assertAlmostEqual(lc[2], SPEC["light"], delta=1)
                    ta, tc = a["title"], b["title"]
                    self.assertAlmostEqual(ta[3], tc[3], delta=1, msg=f"title height {ta} {tc}")
                    self.assertAlmostEqual(ta[1], tc[1], delta=1, msg=f"title top {ta} {tc}")
                    # titulek "Monitory SSD" a "Monitory CSD": stejna sirka, stejny stred
                    self.assertAlmostEqual(ta[2], tc[2], delta=3, msg=f"title width {ta} {tc}")
                    self.assertAlmostEqual(ta[0] + ta[2] / 2, fs[2] / 2, delta=2)
                    self.assertAlmostEqual(tc[0] + tc[2] / 2, fc[2] / 2, delta=2)
                    # stejna vaha pisma; barva v tmavem motivu se mirne lisi: GTK bere popredi tematu (#dedede),
                    # kompozitor fg z luxos_tokens (#f4f4fa)
                    self.assertLess(abs(a["ink"] - b["ink"]) / b["ink"], 0.25, "title weight")
                    sheet_rows.append((img_s.crop(fs[0] - 20, fs[1] - 20, 400, hs + 60),
                                       img_c.crop(fc[0] - 20, fc[1] - 20, 400, hc + 60)))
                sw, sh = 2 * 400 + 30, len(sheet_rows) * (SPEC["height"] + 70) + 10
                sheet = Image(sw, sh, bytes([128, 128, 128]) * (sw * sh))
                for r, (left, right) in enumerate(sheet_rows):
                    sheet.paste(left, 10, 10 + r * (SPEC["height"] + 70))
                    sheet.paste(right, 420, 10 + r * (SPEC["height"] + 70))
                sheet.save(os.path.join(RESULTS, f"titlebar-ssd-vs-csd-{mode}.png"))

    @unittest.skipUnless(have_gtk() and have_whitesur(), "python3-gobject and WhiteSur on the host")
    def test_compact_csd_matches_compact_ssd(self):
        """Nizke zahlavi: cizi aplikace se zahlavim kompozitoru i headerbar.compact (Kalkulacka) 30 px"""
        g = self.gtk()
        ssd = g.window("--plain", title="Small SSD", app="org.example.small", size="360x200")
        csd = g.window("--headerbar", "--compact", title="Small CSD", app="luxos-calculator", size="360x200")
        self.assertEqual(ssd["top"], SPEC["height_compact"])
        img = Image.ppm(g.s.shot("titlebar-compact.ppm"))
        for v, top in ((ssd, ssd["top"]), (csd, 0)):
            f = frame(v)
            h = content_top(img, f) - 12
            self.assertEqual(h, SPEC["height_compact"], v["title"])
            a = analyse(img, f[:3], h, SPEC["inset_compact"])
            xs = [round(l[0]) for l in a["lights"]]
            want = [SPEC["inset_compact"] + i * SPEC["pitch"] for i in range(3)]
            self.assertTrue(all(abs(x - w) <= 1 for x, w in zip(xs, want)), f"{v['title']} lights {xs}")

    def test_dark_client_gets_dark_titlebar(self):
        """Tmavy obsah (terminal) = tmave zahlavi i ve svetlem rezimu, s citelnym nazvem; svetly obsah svetle"""
        s = self.plain()
        for title, app, color in (("Terminal", "foot", "1e1e1e"), ("Paper", "org.example.paper", "fafafa")):
            wlt("run", s.dir, "--bg", "wlt-client", "--solid", "--title", title, "--app-id", app, "--size", "400x200",
                "--color", color)
            time.sleep(0.6)
        st = s.state()["views"]
        img = Image.ppm(s.shot("titlebar-dark-client.ppm"))
        term, paper = frame(st["Terminal"]), frame(st["Paper"])
        t = analyse(img, term[:3], st["Terminal"]["top"], SPEC["inset_compact"])
        p = analyse(img, paper[:3], st["Paper"]["top"], SPEC["inset_compact"])
        print(f"\nterminal {t}\npaper {p}")
        self.assertEqual(t["bg"], (0x1e, 0x1e, 0x1e))
        self.assertEqual(p["bg"], (0xfa, 0xfa, 0xfa))
        self.assertGreaterEqual(t["contrast"], 2.5, "inactive title on the dark bar")
        self.assertGreaterEqual(p["contrast"], 4.5, "active title")
        # zahlavi splyva s obsahem: zadna cara mezi zahlavim a oknem
        x = term[0] + term[2] - 30
        self.assertEqual(img.px(x, term[1] + st["Terminal"]["top"] - 1), img.px(x, term[1] + st["Terminal"]["top"] + 2))

    def test_golden_titlebars(self):
        """Vzorove snimky zahlavi kompozitoru: svetle/tmave, aktivni/neaktivni, bezne/nizke"""
        for dark in (False, True):
            s = self.plain(dark)
            # wlt-client: svisle pruhy = barva klienta neznama, zahlavi v barve motivu
            s.client("Okno A", app="luxos-golden", size="320x120")
            s.client("Okno B", app="org.example.golden", size="320x120")
            st = s.state()["views"]
            img = Image.ppm(s.shot("titlebar-golden.ppm"))
            mode = "dark" if dark else "light"
            for title, name in (("Okno_A", f"{mode}-normal-inactive"), ("Okno_B", f"{mode}-compact-active")):
                f = frame(st[title])
                golden_check(self, img.crop(f[0] - 4, f[1] - 4, f[2] + 8, st[title]["top"] + 4), name)
            # obrys okna: 1 px vedle okna tmavsi nez pozadi o kus dal (stin je dole, ne po stranach nahore)
            f = frame(st["Okno_B"])
            edge, away = img.px(f[0] - 1, f[1] + 20), img.px(f[0] - 6, f[1] + 20)
            self.assertLess(lum(edge), lum(away) * 0.97, f"outline {edge} vs {away}")


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")), "build first: packages/luxwm/tests/build-host.sh")
class Placement(unittest.TestCase):
    """Nova okna: pouzitelna plocha bez listy a Docku s okrajem 8 px; nikdy pod Dockem"""

    def setUp(self):
        self.s = Session()
        self.s.bar(BAR)
        wlt("run", self.s.dir, "--bg", "wlt-bar", "--bottom", "--height", str(DOCK))
        time.sleep(0.6)
        self.area = (8, BAR + 8, W - 16, H - BAR - DOCK - 16)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.terminate()
            p.wait(5)
        self.s.stop()

    def inside(self, f):
        x, y, w, h = self.area
        return f[0] >= x and f[1] >= y and f[0] + f[2] <= x + w and f[1] + f[3] <= y + h

    def test_margins_and_upper_third(self):
        s = self.s
        self.assertEqual(s.state()["usable"], (0, BAR, W, H - BAR - DOCK))
        s.client("A", app="luxos-a", size="400x300")
        f = frame(s.state()["views"]["A"])
        x, y, w, h = self.area
        self.assertEqual(f[0], x + (w - 400) // 2)
        self.assertEqual(f[1], y + (h - f[3]) // 3, "upper third")
        self.assertTrue(self.inside(f), f)
        s.client("B", app="luxos-b", size="400x300")
        s.client("C", app="luxos-c", size="400x300")
        for t, v in s.state()["views"].items():
            self.assertTrue(self.inside(frame(v)), (t, frame(v), self.area))

    def test_tall_window_shrinks_to_fit(self):
        s = self.s
        s.client("Tall", app="luxos-tall", size="700x900")
        f = frame(s.state()["views"]["Tall"])
        self.assertEqual((f[1], f[3]), (self.area[1], self.area[3]), f)
        self.assertTrue(self.inside(f), f)

    @unittest.skipUnless(have_gtk(), "python3-gobject")
    def test_window_growing_after_map_is_refit(self):
        env = {}
        for line in wlt("env", self.s.dir).splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            env[key] = value
        env.pop("LD_LIBRARY_PATH", None)
        env.update(GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GTK_A11Y="none")
        p = subprocess.Popen([sys.executable, "-u", CLIENT, "--plain", "--title", "Grow", "--size", "500x300",
                              "--app-id", "luxos-grow", "--grow", "560x600"], env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True)
        self.procs.append(p)
        self.assertEqual(p.stdout.readline().strip(), "mapped")
        time.sleep(2.2)
        f = frame(self.s.state()["views"]["Grow"])
        self.assertTrue(self.inside(f), (f, self.area))
        self.assertIn("refit", self.s.log())


if __name__ == "__main__":
    unittest.main()
