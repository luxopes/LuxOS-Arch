#!/usr/bin/env python3
"""Plocha na Waylandu (files/lsl/luxos-backdrop.lsl, widgety luxos-widgets.lsl) proti beznemu labwc headless
(pixman) z harnessu WP-1.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -p MemorySwapMax=0 -- timeout 1200 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_backdrop_wl.py -v

Kazdy test ma vlastni relaci `scripts/wl-test/wlt start` (soukrome XDG_RUNTIME_DIR, HOME, XDG_CONFIG_HOME).
Plocha bezi s LUXOS_BACKDROP_TRACE=1 (udalosti na stdout). Prikazy nabidky plochy jsou nahradni skripty v PATH,
ktere jen zapisi, ze byly spusteny.

Snimky: tests/wl-backdrop-goldens/*.png (bez pisma, tolerance jen na zaokrouhleni). Novy vzor:
LUXOS_BACKDROP_UPDATE_GOLDENS=1. Necinnost: LUXOS_BACKDROP_IDLE_SECONDS (vychozi 60).
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import re

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_luxos_bar_wl import png_write, png_read, ppm_read, crop, pixel  # noqa: E402

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
REPO = PKG.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
GOLDENS = HERE / "wl-backdrop-goldens"
UPDATE = os.environ.get("LUXOS_BACKDROP_UPDATE_GOLDENS") == "1"
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test") / "sysroot")
HAVE_LABWC = (SYSROOT / "usr/bin/labwc").exists() or shutil.which("labwc")
TOOLS = all(shutil.which(t) for t in ("make", "gcc", "wayland-scanner", "pkg-config"))
COLOR = "204060"
FAKE_COMMANDS = ("luxos-settings", "luxos-display-settings", "luxos-widgets", "xdg-open", "gio")


def pattern(width, height):
    """Tapeta bez symetrie: vlevo oranzovy prechod, vpravo modry, bily ctverec 20 px vlevo nahore."""
    rows = []
    for y in range(height):
        t = y / max(1, height - 1)
        left = bytes((240, round(120 + 100 * t), 40)) * (width // 2)
        right = bytes((40, round(90 + 120 * t), 220)) * (width - width // 2)
        row = bytearray(left + right)
        if y < 20:
            row[:60] = b"\xff" * 60
        rows.append(bytes(row))
    return b"".join(rows)


def solid(width, height, rgb):
    return bytes(rgb) * (width * height)


class Proc:
    """Bezici program: radky stdout s casem prijeti (CLOCK_MONOTONIC)."""

    def __init__(self, proc):
        self.proc = proc
        self.lines = []
        self.cond = threading.Condition()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for raw in self.proc.stdout:
            with self.cond:
                self.lines.append((time.monotonic(), raw.decode(errors="replace").rstrip("\n")))
                self.cond.notify_all()
        with self.cond:
            self.cond.notify_all()

    def wait(self, rx, timeout=10, start=0):
        """Prvni radek od indexu start odpovidajici vyrazu -> (cas, match)."""
        rx = re.compile(rx)
        deadline = time.monotonic() + timeout
        with self.cond:
            while True:
                for at, line in self.lines[start:]:
                    m = rx.search(line)
                    if m:
                        return at, m
                left = deadline - time.monotonic()
                if left <= 0 or self.proc.poll() is not None:
                    raise AssertionError(f"{rx.pattern!r} se neobjevilo:\n" + "\n".join(l for _, l in self.lines[-40:]))
                self.cond.wait(min(left, 0.2))

    def mark(self):
        with self.cond:
            return len(self.lines)

    def count(self, rx):
        with self.cond:
            return sum(1 for _, l in self.lines if re.search(rx, l))


def rollup(pid):
    fields = {}
    for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines()[1:]:
        key, value = line.split(":")
        fields[key] = int(value.split()[0])
    return fields


def switches(pid):
    """Prepnuti kontextu po vlaknech (vlakno, ktere mezitim skonci, by soucet snizilo)."""
    counts = {}
    for task in Path(f"/proc/{pid}/task").iterdir():
        try:
            counts[task.name] = sum(int(line.split()[1]) for line in (task / "status").read_text().splitlines()
                                    if line.startswith(("voluntary_ctxt_switches", "nonvoluntary_ctxt_switches")))
        except FileNotFoundError:
            pass
    return counts


@unittest.skipUnless(LSLC and HAVE_LABWC and TOOLS and WLT.exists(), "chybi lslc, labwc (WLT_SYSROOT) nebo nastroje sestaveni")
class WaylandBackdrop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
        base.mkdir(parents=True, exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(prefix="luxos-backdrop-wl-", dir=base))
        r = subprocess.run(["make", "-s", "-C", str(PKG / "files/src/luxos-wl"), f"OUT={cls.tmp}"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("libluxos-wl: " + r.stdout + r.stderr)
        cls.lib = cls.tmp / "libluxos-wl.so.0"
        src = cls.tmp / "lsl"
        src.mkdir()
        for f in (PKG / "files/lsl").glob("*.lsl"):
            shutil.copy(f, src)
        for name in ("luxos-backdrop", "luxos-widgets"):
            r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", str(src / f"{name}.lsl"), str(cls.tmp / name)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"{name}: " + r.stdout + r.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.procs = []
        self.session = None

    def tearDown(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
            if p.stdout:
                p.stdout.close()
        if self.session:
            subprocess.run([str(WLT), "stop", str(self.session)], capture_output=True)
            shutil.rmtree(self.session, True)

    # ---- pomucky ----

    def wlt(self, *args, check=True):
        r = subprocess.run([str(WLT), *args], capture_output=True, text=True, timeout=120)
        if check and r.returncode != 0:
            self.fail(f"wlt {args[0]}: " + r.stdout + r.stderr)
        return r.stdout

    def start(self, outputs=1, size="640x400", conf=""):
        name = f"d{os.getpid()}-{sorted(n for n in dir(self) if n.startswith('test_')).index(self._testMethodName)}"
        size_args = ["--size", size] if size else []
        self.session = Path(self.wlt("start", "--mode", "headless", "--outputs", str(outputs), *size_args,
                                     "--timeout", "900", "--name", name).strip())
        env = {}
        for line in self.wlt("env", str(self.session)).splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            env[key] = value
        env.pop("LD_LIBRARY_PATH", None)
        fake = self.session / "fakebin"
        fake.mkdir()
        self.ran = self.session / "ran.log"
        for cmd in FAKE_COMMANDS:
            (fake / cmd).write_text(f"#!/bin/sh\necho \"{cmd} $*\" >>'{self.ran}'\n")
            (fake / cmd).chmod(0o755)
        # Plocha ve spravci souboru (Nova slozka): GIO podle mimeapps.list spusti nahradni program
        apps = self.session / "home/.local/share/applications"
        apps.mkdir(parents=True, exist_ok=True)
        (fake / "fake-files").write_text(f"#!/bin/sh\necho \"files $*\" >>'{self.ran}'\n")
        (fake / "fake-files").chmod(0o755)
        (apps / "fake-files.desktop").write_text(f"[Desktop Entry]\nType=Application\nName=Files\nExec={fake}/fake-files %U\n"
                                                 "MimeType=inode/directory;\n")
        (self.session / "config").mkdir(exist_ok=True)
        (self.session / "config/mimeapps.list").write_text("[Default Applications]\ninode/directory=fake-files.desktop\n")
        env.update(PATH=f"{fake}:/usr/bin:/bin", GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GTK_A11Y="none",
                   LUXOS_WL_LIB=str(self.lib), LUXOS_BACKDROP_TRACE="1")
        self.env = env
        self.conf = self.session / "config/luxos"
        self.conf.mkdir(parents=True, exist_ok=True)
        (self.session / "config/gtk-3.0").mkdir(parents=True, exist_ok=True)
        (self.session / "config/gtk-3.0/settings.ini").write_text("[Settings]\ngtk-enable-animations=false\n")
        (self.conf / "appearance").write_text("light\n")
        self.set_conf(conf)
        return self.session

    def set_conf(self, text):
        tmp = self.conf / "appearance.conf.new"
        tmp.write_text(text)
        tmp.rename(self.conf / "appearance.conf")
        return time.monotonic()

    def image(self, name, width, height, pixels):
        path = self.session / name
        png_write(path, width, height, pixels)
        return path

    def backdrop(self):
        p = subprocess.Popen([str(self.tmp / "luxos-backdrop")], env=self.env, stdout=subprocess.PIPE)
        self.procs.append(p)
        d = Proc(p)
        d.wait(r"^ready$")
        return d

    def widgets(self, names):
        (self.conf / "widgets.conf").write_text(f"ENABLED=1\nWIDGETS={names}\n")
        p = subprocess.Popen([str(self.tmp / "luxos-widgets")], env=self.env, stdout=subprocess.PIPE)
        self.procs.append(p)
        return p

    def input(self, *cmds):
        self.wlt("input", str(self.session), *cmds)

    def keys(self, *names):
        # nova virtualni klavesnice kazdeho `wlt input`: prvni klavesu labwc spolkne (posle keymap a enter)
        self.input("key shift", *(f"key {n}" for n in names))

    def shot(self):
        path = self.session / "shot.ppm"
        self.wlt("shot", str(self.session), str(path))
        return ppm_read(path)

    def compositor_alive(self):
        pid = int((self.session / "compositor.pid").read_text())
        return Path(f"/proc/{pid}").exists()

    def compare_golden(self, name, image):
        golden = GOLDENS / f"{name}.png"
        out = self.session / f"{name}.png"
        png_write(out, *image)
        if UPDATE or not golden.exists():
            GOLDENS.mkdir(exist_ok=True)
            shutil.copy(out, golden)
            if not UPDATE:
                self.skipTest(f"vzor {golden} vytvoren")
        want = png_read(golden)
        self.assertEqual(want[:2], image[:2], "jina velikost nez vzor")
        a, b = want[2], image[2]
        bad = sum(1 for i in range(0, len(a), 3) if max(abs(a[i + k] - b[i + k]) for k in range(3)) > 24) / (len(a) // 3)
        print(f"\n  {name}: odlisne pixely {bad * 100:.3f} %")
        self.assertLess(bad, 0.002, f"snimek {out} se lisi od {golden}")

    # ---- rezimy zobrazeni ----

    def mode_case(self, mode):
        self.start()
        wall = self.image("wall.png", 300, 120, pattern(300, 120))
        self.set_conf(f"WALLPAPER={wall}\nWALLPAPER_MODE={mode}\nWALLPAPER_COLOR=#{COLOR}\n")
        d = self.backdrop()
        d.wait(r"^drawn HEADLESS-1 640x400")
        time.sleep(0.3)
        image = self.shot()
        self.assertEqual(image[:2], (640, 400))
        self.compare_golden(f"mode-{mode}", image)
        return image

    def test_mode_fill(self):
        image = self.mode_case("fill")
        # 300x120 na 640x400: vyska 400 (k = 3,33), stredni cast sirky; zadna barva pozadi
        self.assertNotIn(COLOR, {pixel(image, x, y) for x in (0, 320, 639) for y in (0, 200, 399)})
        # levy okraj je uz oranzova polovina, prechod do modre uprostred
        self.assertGreater(image[2][(200 * 640 + 10) * 3], 200)
        self.assertLess(image[2][(200 * 640 + 630) * 3], 80)

    def test_mode_fit(self):
        image = self.mode_case("fit")
        # k = 640/300: obrazek 640x256 uprostred, nahore a dole po 72 px barva
        self.assertEqual(pixel(image, 320, 10), COLOR)
        self.assertEqual(pixel(image, 320, 390), COLOR)
        self.assertEqual(pixel(image, 20, 72 + 10), "ffffff")
        self.assertNotEqual(pixel(image, 320, 200), COLOR)

    def test_mode_center(self):
        image = self.mode_case("center")
        # puvodni velikost na stredu: (170, 140) az (470, 260)
        self.assertEqual(pixel(image, 10, 10), COLOR)
        self.assertEqual(pixel(image, 169, 200), COLOR)
        self.assertEqual(pixel(image, 175, 145), "ffffff")
        self.assertNotEqual(pixel(image, 175, 165), "ffffff")
        self.assertEqual(pixel(image, 471, 200), COLOR)

    def test_mode_tile(self):
        image = self.mode_case("tile")
        for x, y in ((5, 5), (305, 5), (605, 5), (5, 125), (305, 245), (605, 365)):
            self.assertEqual(pixel(image, x, y), "ffffff", (x, y))
        self.assertEqual(pixel(image, 100, 60), pixel(image, 400, 180))

    def test_color_without_wallpaper(self):
        self.start(conf=f"WALLPAPER=/nonexistent.jpg\nWALLPAPER_COLOR=#{COLOR}\n")
        # vychozi tapeta LuxOS nemusi byt v systemu testu: bez ni plna barva, s ni neni cerno
        d = self.backdrop()
        d.wait(r"^drawn HEADLESS-1")
        time.sleep(0.3)
        image = self.shot()
        corner = pixel(image, 5, 5)
        if not Path("/usr/share/backgrounds/luxos/luxos-light.jpg").exists():
            self.assertEqual(corner, COLOR)
        self.assertNotEqual(corner, "000000")

    # ---- zmena tapety ----

    def test_change_propagates_quickly(self):
        self.start()
        red = self.image("red.png", 64, 40, solid(64, 40, (200, 30, 30)))
        green = self.image("green.png", 64, 40, solid(64, 40, (30, 180, 60)))
        self.set_conf(f"WALLPAPER={red}\n")
        d = self.backdrop()
        d.wait(r"^drawn HEADLESS-1")
        times = []
        for wall, rgb in ((green, "1eb43c"), (red, "c81e1e"), (green, "1eb43c")):
            mark = d.mark()
            t0 = self.set_conf(f"WALLPAPER={wall}\n")
            t1, _ = d.wait(r"^drawn HEADLESS-1", start=mark)
            times.append((t1 - t0) * 1000)
            time.sleep(0.2)
            self.assertEqual(pixel(self.shot(), 320, 200), rgb)
        print(f"\n  zmena tapety -> nakresleno: {', '.join(f'{t:.0f}' for t in times)} ms")
        self.assertLess(max(times), 300)
        # stejny obsah souboru znovu (luxos-appearance prepise soubor i beze zmeny): nic se nekresli
        mark = d.mark()
        self.set_conf(f"WALLPAPER={green}\n")
        time.sleep(0.5)
        self.assertEqual(d.count(r"^rendered") - sum(1 for _, l in d.lines[:mark] if l.startswith("rendered")), 0)

    def test_luxos_appearance_command(self):
        """luxos-appearance wallpaper / wallpaper-mode zapise klice, ktere plocha hned pouzije."""
        self.start()
        blue = self.image("blue.png", 64, 40, solid(64, 40, (20, 40, 220)))
        d = self.backdrop()
        d.wait(r"^drawn HEADLESS-1")
        env = dict(self.env, HOME=str(self.session / "home"), XDG_CONFIG_HOME=str(self.session / "config"), USER="test")
        script = PKG / "files/bin/luxos-appearance"
        mark = d.mark()
        r = subprocess.run(["bash", str(script), "wallpaper", str(blue)], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        d.wait(r"^drawn HEADLESS-1", start=mark)
        time.sleep(0.2)
        self.assertEqual(pixel(self.shot(), 320, 200), "1428dc")
        mark = d.mark()
        r = subprocess.run(["bash", str(script), "wallpaper-mode", "center"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        d.wait(r"^rendered HEADLESS-1 640x400@1 center", start=mark)
        text = (self.conf / "appearance.conf").read_text()
        self.assertIn(f"WALLPAPER='{blue}'", text)
        self.assertIn("WALLPAPER_MODE=center", text)

    # ---- vic monitoru ----

    def test_per_output_wallpaper_and_shared_image(self):
        self.start(outputs=2, size=None)
        red = self.image("red.png", 64, 40, solid(64, 40, (200, 30, 30)))
        blue = self.image("blue.png", 64, 40, solid(64, 40, (20, 40, 220)))
        self.set_conf(f"WALLPAPER={red}\n")
        d = self.backdrop()
        d.wait(r"^backdrop added HEADLESS-1 1280x720")
        d.wait(r"^backdrop added HEADLESS-2 1280x720")
        d.wait(r"^drawn HEADLESS-1")
        d.wait(r"^drawn HEADLESS-2")
        # stejna tapeta a velikost: jeden obrazek pro oba vystupy
        self.assertEqual(d.count(r"^rendered"), 1)
        mark = d.mark()
        self.set_conf(f"WALLPAPER={red}\nWALLPAPER_HEADLESS_2={blue}\n")
        d.wait(r"^drawn HEADLESS-2", start=mark)
        time.sleep(0.3)
        image = self.shot()
        self.assertEqual(image[:2], (2560, 720))
        layout = {}
        for line in self.wlt("run", str(self.session), "wlr-randr").splitlines():
            if line and not line[0].isspace():
                current = line.split()[0]
            elif "Position:" in line:
                layout[current] = int(line.split(":")[1].split(",")[0])
        self.assertEqual(pixel(image, layout["HEADLESS-1"] + 640, 360), "c81e1e")
        self.assertEqual(pixel(image, layout["HEADLESS-2"] + 640, 360), "1428dc")
        self.assertEqual(sum(1 for _, l in d.lines[mark:] if l.startswith("drawn HEADLESS-1")), 0)

    def test_unplug_and_replug_output(self):
        self.start(outputs=2, size=None)
        red = self.image("red.png", 64, 40, solid(64, 40, (200, 30, 30)))
        self.set_conf(f"WALLPAPER={red}\n")
        d = self.backdrop()
        d.wait(r"^drawn HEADLESS-2")
        for round_ in range(2):
            mark = d.mark()
            self.wlt("run", str(self.session), "wlr-randr", "--output", "HEADLESS-2", "--off")
            d.wait(r"^backdrop removed HEADLESS-2", start=mark)
            time.sleep(0.3)
            self.assertEqual(self.shot()[:2], (1280, 720))
            mark = d.mark()
            # plocha nedrzi zwlr_output_manager_v1: zapnuti vystupu wlroots 0.20.2 nesestreli
            self.wlt("run", str(self.session), "wlr-randr", "--output", "HEADLESS-2", "--on")
            # GDK hlasi monitor drive, nez zna jeho polohu: nazev vystupu az po kole udalosti
            d.wait(r"^backdrop added ", start=mark)
            d.wait(r"^drawn HEADLESS-2", start=mark)
            time.sleep(0.3)
            self.assertTrue(self.compositor_alive(), "kompozitor po opetovnem zapnuti vystupu skoncil")
            self.assertIsNone(d.proc.poll(), "plocha po zmene vystupu skoncila")
            image = self.shot()
            self.assertEqual(image[:2], (2560, 720))
            self.assertEqual(pixel(image, 640, 360), "c81e1e")
            self.assertEqual(pixel(image, 1280 + 640, 360), "c81e1e")
        self.assertEqual(d.count(r"^backdrop added") - d.count(r"^backdrop removed"), 2)

    # ---- nabidka plochy ----

    def menu_action(self, downs):
        self.start()
        red = self.image("red.png", 64, 40, solid(64, 40, (200, 30, 30)))
        self.set_conf(f"WALLPAPER={red}\n")
        d = self.backdrop()
        d.wait(r"^drawn HEADLESS-1")
        mark = d.mark()
        self.open_menu(d, 200, 150)
        image = self.shot()
        # nabidka vpravo dole od ukazatele, jinak nez tapeta
        self.assertNotEqual(pixel(image, 240, 170), "c81e1e")
        self.keys(*(["Down"] * downs), "Return")
        return d, mark

    def open_menu(self, d, x, y):
        mark = d.mark()
        self.input(f"move {x} {y}", "click right")
        d.wait(r"^menu$", start=mark)
        time.sleep(0.4)
        # ukazatel pryc z nabidky: polozku pod nim by GTK vybralo a Down by zacal od ni
        self.input(f"move {x - 100} {y - 100}")
        time.sleep(0.2)

    def test_menu_displays(self):
        d, mark = self.menu_action(4)
        d.wait(r"^run luxos-display-settings$", start=mark)
        for _ in range(50):
            if self.ran.exists():
                break
            time.sleep(0.1)
        self.assertEqual(self.ran.read_text().split("\n")[0], "luxos-display-settings ")

    def test_menu_change_wallpaper_and_edit_widgets(self):
        d, mark = self.menu_action(2)
        d.wait(r"^run luxos-settings$", start=mark)
        mark = d.mark()
        self.open_menu(d, 300, 200)
        self.keys("Down", "Down", "Down", "Return")
        d.wait(r"^run luxos-widgets settings$", start=mark)
        time.sleep(0.3)
        self.assertEqual(self.ran.read_text().splitlines(), ["luxos-settings ", "luxos-widgets settings"])

    def test_menu_new_folder(self):
        d, mark = self.menu_action(1)
        _, m = d.wait(r"^folder (.*)$", start=mark)
        desktop = self.session / "home/Desktop"
        self.assertEqual(Path(m.group(1)), desktop / "New Folder")
        self.assertTrue((desktop / "New Folder").is_dir())
        for _ in range(50):
            if self.ran.exists():
                break
            time.sleep(0.1)
        self.assertEqual(self.ran.read_text().splitlines(), [f"files {desktop}"])
        # druha slozka nepreplacne prvni
        mark = d.mark()
        self.open_menu(d, 300, 200)
        self.keys("Down", "Return")
        d.wait(r"^folder .*New Folder 2$", start=mark)

    def test_windows_keep_keyboard_focus(self):
        """Plocha ma klavesnici jen po dobu nabidky: okno nad ni pise dal. Navrat fokusu kliknutim po kliku na plochu
        harness neoveri: stock labwc 0.20.3 s virtualni klavesnici `wlt input` ho nevrati ani bez plochy."""
        self.start()
        d = self.backdrop()
        d.wait(r"^drawn HEADLESS-1")
        client = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test") / "bin/wlt-client"
        p = subprocess.Popen([str(client), "--events", "--title", "T", "--size", "200x120"], env=self.env, stdout=subprocess.PIPE)
        self.procs.append(p)
        c = Proc(p)
        c.wait(r"^configure")
        time.sleep(0.3)
        # klavesnice existuje az s virtualni klavesnici `wlt input`
        mark = c.mark()
        self.keys("a")
        c.wait(r"^key a down", start=mark)

    # ---- widgety ----

    def test_widgets_render_on_wayland(self):
        self.start(outputs=2, size=None)
        wall = self.image("wall.png", 320, 200, solid(320, 200, (40, 70, 130)))
        self.set_conf(f"WALLPAPER={wall}\n")
        d = self.backdrop()
        d.wait(r"^drawn HEADLESS-2")
        time.sleep(0.3)
        plain = self.shot()
        w = self.widgets("today,calendar")
        time.sleep(3)
        self.assertIsNone(w.poll(), "luxos-widgets skoncil")
        image = self.shot()
        changed = [x for x in range(0, 2560, 8) if any(pixel(image, x, y) != pixel(plain, x, y) for y in range(0, 720, 8))]
        self.assertTrue(changed, "karty widgetu nejsou videt")
        # karty na hlavnim (prvnim) monitoru GDK, vpravo, druhy monitor beze zmeny
        first = min(changed)
        self.assertTrue(all(first // 1280 == x // 1280 for x in changed), changed[:5] + changed[-5:])
        span = max(changed) - min(changed)
        self.assertLess(span, 420)
        # karta je sklo (svetlejsi nez tapeta), ne cerny ctverec
        x = (min(changed) + max(changed)) // 2
        self.assertGreater(sum(bytes.fromhex(pixel(image, x, 40))), sum(bytes.fromhex(pixel(plain, x, 40))))

    # ---- necinnost a pamet ----

    def idle(self, pid, seconds):
        before = switches(pid)
        cpu_before = sum(map(int, Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[11:13]))
        time.sleep(seconds)
        after = switches(pid)
        cpu = sum(map(int, Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[11:13])) - cpu_before
        return sum(max(0, n - before.get(t, 0)) for t, n in after.items()), cpu

    def test_idle_wakeups(self):
        seconds = int(os.environ.get("LUXOS_BACKDROP_IDLE_SECONDS", "60"))
        self.start(outputs=2, size=None)
        wall = self.image("wall.png", 320, 200, pattern(320, 200))
        self.set_conf(f"WALLPAPER={wall}\n")
        d = self.backdrop()
        d.wait(r"^drawn HEADLESS-2")
        w = self.widgets("today,calendar")
        time.sleep(3)
        pids = {"backdrop": d.proc.pid, "widgets": w.pid}
        results = {}
        threads = [threading.Thread(target=lambda k=k, p=p: results.__setitem__(k, self.idle(p, seconds)))
                   for k, p in pids.items()]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for k, (wakeups, cpu) in results.items():
            print(f"\n  {k}: za {seconds} s {wakeups} probuzeni, CPU {cpu} tiku")
        # plocha nema zadny casovac
        self.assertEqual(results["backdrop"][0], 0)
        # widgety: hodiny jednou za minutu (+ prekresleni), nic dalsiho
        self.assertLessEqual(results["widgets"][0], 6 * max(1, seconds // 60))

    def pss_case(self, outputs, size, wall_size):
        self.start(outputs=outputs, size=size)
        ww, wh = wall_size
        wall = self.image("wall.png", ww, wh, pattern(ww, wh))
        self.set_conf(f"WALLPAPER={wall}\n")
        d = self.backdrop()
        for i in range(outputs):
            d.wait(rf"^drawn HEADLESS-{i + 1}", timeout=30)
        time.sleep(3)
        mem = rollup(d.proc.pid)
        rendered = [l for _, l in d.lines if l.startswith("rendered")]
        print(f"\n  {outputs}x {size}, tapeta {ww}x{wh}: PSS {mem['Pss'] / 1024:.1f} MB, RSS {mem['Rss'] / 1024:.1f} MB, "
              f"anonymni {mem['Anonymous'] / 1024:.1f} MB; {rendered}")
        return mem, len(rendered)

    def test_pss_one_output_1080p(self):
        mem, renders = self.pss_case(1, "1920x1080", (3840, 2160))
        self.assertEqual(renders, 1)
        self.assertLess(mem["Pss"], 60 * 1024)

    def test_pss_two_outputs_1080p(self):
        mem, renders = self.pss_case(2, "1920x1080", (3840, 2160))
        # stejna velikost: obrazek jednou
        self.assertEqual(renders, 1)
        self.assertLess(mem["Pss"], 80 * 1024)

    def test_pss_4k_output(self):
        mem, renders = self.pss_case(1, "3840x2160", (3840, 2160))
        self.assertEqual(renders, 1)
        # obrazek 32 MB + bufery GDK; puvodni pixely tapety uz ne
        self.assertLess(mem["Pss"], 140 * 1024)

    # ---- systemd ----

    @unittest.skipUnless(shutil.which("systemd-analyze"), "chybi systemd-analyze")
    def test_unit_file_lint(self):
        text = (PKG / "files/systemd-user/luxos-backdrop.service").read_text()
        unit = self.tmp / "luxos-backdrop.service"
        unit.write_text(text.replace("/usr/bin/luxos-backdrop", str(self.tmp / "luxos-backdrop")))
        r = subprocess.run(["systemd-analyze", "--user", "verify", str(unit)], capture_output=True, text=True)
        problems = [l for l in (r.stdout + r.stderr).splitlines() if "luxos-backdrop" in l]
        self.assertEqual(problems, [], r.stdout + r.stderr)
        self.assertIn("Restart=always", text)
        self.assertIn("RestartPreventExitStatus=2", text)

    def test_exits_2_without_wayland(self):
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY")}
        env.update(GDK_BACKEND="wayland", WAYLAND_DISPLAY="wayland-nonexistent-test", XDG_RUNTIME_DIR=str(self.tmp))
        r = subprocess.run([str(self.tmp / "luxos-backdrop")], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2, r.stderr)


if __name__ == "__main__":
    unittest.main()
