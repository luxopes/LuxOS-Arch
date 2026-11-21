#!/usr/bin/env python3
"""Plocha na Waylandu (files/lsl/luxos-backdrop.lsl, widgety luxos-widgets.lsl) proti beznemu labwc headless
(pixman) z harnessu WP-1.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -p MemorySwapMax=0 -- timeout 1200 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_backdrop_wl.py -v

Kazdy test ma vlastni relaci `scripts/wl-test/wlt start` (soukrome XDG_RUNTIME_DIR, HOME, XDG_CONFIG_HOME).
Plocha bezi s LUXOS_BACKDROP_TRACE=1 (udalosti na stdout). Prikazy nabidky plochy jsou nahradni skripty v PATH,
ktere jen zapisi, ze byly spusteny.

Ikony plochy: soubory v soukromem ~/Desktop, kanal xfce4-desktop v soukromem XDG_CONFIG_HOME (vymenitelne disky
vypnute, hostitel by je mohl mit), soubory otevira nahradni aplikace z mimeapps.list, ktera jen zapise "open SOUBOR".
Pretazeni ze spravce souboru napodobuje tests/backdrop/drag_source.py (GTK 3).

Snimky: tests/wl-backdrop-goldens/*.png (tapety bez pisma, ikony s pismem a motivem ikon systemu). Novy vzor:
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
# Plocha bezi proti luxwm (cilovy kompozitor: klavesnice vrstvy na vyzadani, grab nabidek), kdyz je postaveny
# (packages/luxwm/tests/build-host.sh); jinak proti labwc
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")
USE_LUXWM = (LUXWM_BUILD / "luxwm").exists() and os.environ.get("LUXOS_BACKDROP_LABWC") != "1"
TOOLS = all(shutil.which(t) for t in ("make", "gcc", "wayland-scanner", "pkg-config"))
COLOR = "204060"
FAKE_COMMANDS = ("luxos-settings", "luxos-display-settings", "luxos-widgets", "xdg-open", "gio")
DESKTOP_CHANNEL = """<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-desktop" version="1.0">
  <property name="desktop-icons" type="empty">
    <property name="style" type="int" value="2"/>
    <property name="icon-size" type="uint" value="56"/>
    <property name="font-size" type="double" value="10"/>
    <property name="file-icons" type="empty">
      <property name="show-removable" type="bool" value="false"/>
    </property>
  </property>
</channel>
"""
# mrizka luxos_desk pro ikonu 56 a pismo 10: bunka 100x108 od (8, 40) (lista 32 + 8)
CELL_W, CELL_H, GRID_X, GRID_Y = 100, 108, 8, 36   # GRID_Y = tokens.BAR["height"] + 8


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


def pool_threads(pid):
    """Pracovni vlakna GThreadPool (pool-0...); pool-spawner zustava a sam se nebudi."""
    names = []
    for task in Path(f"/proc/{pid}/task").iterdir():
        try:
            name = (task / "comm").read_text().strip()
        except FileNotFoundError:
            continue
        if name.startswith("pool-") and name != "pool-spawner":
            names.append(name)
    return names


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
            r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(src), str(src / f"{name}.lsl"),
                                str(cls.tmp / name)],
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
        comp_args, comp_env = [], {}
        if USE_LUXWM:
            conf_path = Path(tempfile.mkdtemp(prefix="luxwm-conf-", dir=self.tmp)) / "luxwm.conf"
            conf_path.write_text("xwayland = no\n" + (REPO / "packages/luxwm/luxwm.conf").read_text())
            comp_args = ["--", str(LUXWM_BUILD / "luxwm")]
            comp_env = {"WLT_COMPOSITOR_ENV": f"LUXCOMP_VIRTUAL_INPUT=1 LUXWM_SYSTEM_CONFIG={conf_path} "
                                              f"LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib"}
        r = subprocess.run([str(WLT), "start", "--mode", "headless", "--outputs", str(outputs), *size_args,
                            "--timeout", "900", "--name", name, *comp_args], capture_output=True, text=True, timeout=120,
                           env={**os.environ, **comp_env})
        if r.returncode != 0:
            self.fail("wlt start: " + r.stdout + r.stderr)
        self.session = Path(r.stdout.strip().splitlines()[-1])
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
        (fake / "fake-open").write_text(f"#!/bin/sh\necho \"open $*\" >>'{self.ran}'\n")
        (fake / "fake-open").chmod(0o755)
        (apps / "fake-open.desktop").write_text(f"[Desktop Entry]\nType=Application\nName=Open\nExec={fake}/fake-open %f\n"
                                                "MimeType=text/plain;application/pdf;\n")
        (self.session / "config").mkdir(exist_ok=True)
        (self.session / "config/mimeapps.list").write_text("[Default Applications]\ninode/directory=fake-files.desktop\n"
                                                          "text/plain=fake-open.desktop\napplication/pdf=fake-open.desktop\n")
        channel = self.session / "config/xfce4/xfconf/xfce-perchannel-xml"
        channel.mkdir(parents=True, exist_ok=True)
        (channel / "xfce4-desktop.xml").write_text(DESKTOP_CHANNEL)
        env.update(PATH=f"{fake}:/usr/bin:/bin", GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GTK_A11Y="none",
                   LUXOS_WL_LIB=str(self.lib), LUXOS_BACKDROP_TRACE="1", GIO_USE_VOLUME_MONITOR="unix")
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

    def new_window_center(self, before):
        """Stred okna, ktere se objevilo od snimku `before` (stred ohraniceni zmenenych pixelu vcetne stinu).
        luxwm nova okna klade do horni tretiny plochy, labwc testu doprostred."""
        width, height, old = before
        _, _, new = self.shot()
        row = width * 3
        ys = [y for y in range(height) if old[y * row:(y + 1) * row] != new[y * row:(y + 1) * row]]
        self.assertTrue(ys, "no new window on screen")
        xs = [x for y in ys[::4] for x in range(width)
              if old[y * row + x * 3:y * row + x * 3 + 3] != new[y * row + x * 3:y * row + x * 3 + 3]]
        return (min(xs) + max(xs)) // 2, (ys[0] + ys[-1]) // 2

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
        d.wait(r"^run luxos-settings desktop$", start=mark)
        mark = d.mark()
        self.open_menu(d, 300, 200)
        self.keys("Down", "Down", "Down", "Return")
        d.wait(r"^run luxos-widgets settings$", start=mark)
        time.sleep(0.3)
        self.assertEqual(self.ran.read_text().splitlines(), ["luxos-settings ", "luxos-widgets settings"])

    def test_menu_new_folder(self):
        self.start()
        red = self.image("red.png", 64, 40, solid(64, 40, (200, 30, 30)))
        self.set_conf(f"WALLPAPER={red}\n")
        d = self.backdrop()
        d.wait(r"^drawn HEADLESS-1")
        desktop = self.session / "home/Desktop"
        send = self.live()

        def new_folder():
            mark = d.mark()
            send("move 200 150", "sleep 0.1", "click right")
            d.wait(r"^menu$", start=mark)
            send("sleep 0.4", "move 100 50", "sleep 0.2", "key Down", "key Return")
            return mark

        mark = new_folder()
        _, m = d.wait(r"^folder (.*)$", start=mark)
        self.assertEqual(Path(m.group(1)), desktop / "New Folder")
        self.assertTrue((desktop / "New Folder").is_dir())
        # s ikonami se slozka hned prejmenovava (pole pres popisek), spravce souboru se nespousti
        d.wait(r"^rename New Folder$", start=mark)
        send("sleep 0.2", "type Fotky", "key Return")
        d.wait(r"^renamed New Folder -> Fotky$", start=mark)
        self.assertTrue((desktop / "Fotky").is_dir())
        self.assertFalse(self.ran.exists())
        # druha slozka nepreplacne prvni (Escape prejmenovani zrusi)
        (desktop / "Fotky").rename(desktop / "New Folder")
        time.sleep(0.3)
        mark = new_folder()
        d.wait(r"^folder .*New Folder 2$", start=mark)
        d.wait(r"^rename New Folder 2$", start=mark)
        send("sleep 0.2", "key Escape")
        time.sleep(0.4)
        self.assertTrue((desktop / "New Folder 2").is_dir())
        self.assertFalse(any(l.startswith("renamed") for _, l in d.lines[mark:]))

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

    # ---- ikony plochy ----

    def desktop_files(self, *names):
        desktop = self.session / "home/Desktop"
        desktop.mkdir(parents=True, exist_ok=True)
        for name in names:
            if name.endswith("/"):
                (desktop / name).mkdir(exist_ok=True)
            else:
                (desktop / name).write_text(name + "\n")
        return desktop

    def icons(self, d, start=0):
        """Posledni radek "icons N klic@sloupec,radek | ..." -> {klic: (sloupec, radek)}."""
        line = [l for _, l in d.lines[start:] if l.startswith("icons ") and l != "icons drawn"][-1]
        out = {}
        rest = line.split(" ", 2)[2] if line.count(" ") >= 2 else ""
        for part in filter(None, rest.split(" | ")):
            key, _, pos = part.rpartition("@")
            col, row = pos.split(",")
            out[key] = (int(col), int(row))
        return out

    def center(self, pos):
        """Stred ikony (ne popisku) v bunce."""
        return GRID_X + pos[0] * CELL_W + CELL_W // 2, GRID_Y + pos[1] * CELL_H + 6 + 28

    def icon_backdrop(self, *names, size="1024x640"):
        self.start(size=size)
        wall = self.image("wall.png", 64, 40, solid(64, 40, (40, 70, 130)))
        self.set_conf(f"WALLPAPER={wall}\n")
        self.desktop_files(*names)
        d = self.backdrop()
        d.wait(r"^icons drawn")
        return d

    def ran_lines(self, count, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.ran.exists() and len(self.ran.read_text().splitlines()) >= count:
                break
            time.sleep(0.05)
        return self.ran.read_text().splitlines() if self.ran.exists() else []

    def test_icons_for_desktop_files_and_new_file_fast(self):
        d = self.icon_backdrop("notes.txt", "Projects/", ".hidden-file", "backup.txt~")
        pos = self.icons(d)
        # slozky prvni, skryte soubory a zalohy ne, sloupec od leveho horniho rohu
        self.assertEqual(pos, {"Projects": (0, 0), "notes.txt": (0, 1)})
        time.sleep(0.2)
        image = self.shot()
        x, y = self.center(pos["notes.txt"])
        self.assertNotEqual(pixel(image, x, y), "284682", "ikona neni videt")
        # popisek pod ikonou: bile pismo
        label = [pixel(image, xx, yy) for xx in range(x - 40, x + 40) for yy in range(y + 34, y + 48)]
        self.assertTrue(any(int(p[:2], 16) > 200 and int(p[2:4], 16) > 200 for p in label), "popisek neni videt")
        times = []
        for name in ("zprava.txt", "Archiv/"):
            mark = d.mark()
            t0 = time.monotonic()
            self.desktop_files(name)
            t1, _ = d.wait(r"^icons drawn$", start=mark)
            times.append((t1 - t0) * 1000)
            self.assertIn(name.rstrip("/"), self.icons(d, mark))
        print(f"\n  novy soubor na Plose -> ikona nakreslena: {', '.join(f'{t:.0f}' for t in times)} ms")
        self.assertLess(max(times), 500)
        # smazany soubor zmizi
        mark = d.mark()
        (self.session / "home/Desktop/zprava.txt").unlink()
        d.wait(r"^icons 3 ", start=mark)

    def test_long_label_ellipsized(self):
        d = self.icon_backdrop("Velmi dlouhy nazev souboru, ktery se nevejde ani na dva radky popisku.txt")
        pos = list(self.icons(d).values())[0]
        time.sleep(0.2)
        image = self.shot()
        x, y = self.center(pos)
        # popisek zustava v bunce: pod ni (dalsi bunka) uz zadne bile pismo
        below = [pixel(image, xx, GRID_Y + CELL_H + 4) for xx in range(x - 48, x + 48)]
        self.assertTrue(all(p == "284682" for p in below), "popisek pretekl do dalsi bunky")

    def test_double_click_opens_in_default_app(self):
        d = self.icon_backdrop("notes.txt", "Projects/")
        desktop = self.session / "home/Desktop"
        app = desktop / "editor.desktop"
        app.write_text(f"[Desktop Entry]\nType=Application\nName=Muj editor\nExec={self.session}/fakebin/fake-open --app\n"
                       "Icon=accessories-text-editor\n")
        app.chmod(0o755)
        plain = desktop / "cizi.desktop"
        plain.write_text("[Desktop Entry]\nType=Application\nName=Cizi\nExec=/bin/false\n")
        mark = d.mark()
        d.wait(r"^icons 4 ", start=mark)
        pos = self.icons(d)
        # spustitelny spoustec ma jmeno aplikace, nespustitelny zustava souborem
        self.assertIn("editor.desktop", pos)
        x, y = self.center(pos["notes.txt"])
        mark = d.mark()
        self.input(f"move {x} {y}", "click", "click")
        d.wait(r"^open notes.txt$", start=mark)
        self.assertEqual(self.ran_lines(1), [f"open {desktop / 'notes.txt'}"])
        x, y = self.center(pos["editor.desktop"])
        self.input("sleep 0.6", f"move {x} {y}", "click", "click")
        d.wait(r"^open editor.desktop$", start=mark)
        self.assertEqual(self.ran_lines(2)[1], "open --app")
        x, y = self.center(pos["Projects"])
        self.input("sleep 0.6", f"move {x} {y}", "click", "click")
        self.assertEqual(self.ran_lines(3)[2], f"files {desktop / 'Projects'}")

    def live(self):
        """Jedna virtualni klavesnice po cely test (jako skutecna): kazde `wlt input` by pridalo a odebralo vlastni
        a labwc po odebrani vrstve plochy fokus nevrati. Prikazy po radcich na stdin."""
        p = subprocess.Popen([str(WLT), "input", str(self.session)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, text=True)
        self.procs.append(p)

        def send(*cmds):
            p.stdin.write("".join(c + "\n" for c in cmds))
            p.stdin.flush()
        send("key shift")
        return send

    def item_menu(self, d, send, pos, downs):
        x, y = self.center(pos)
        mark = d.mark()
        send(f"move {x} {y}", "sleep 0.1", "click right")
        d.wait(r"^item menu ", start=mark)
        time.sleep(0.4)
        send(f"move {x + 300} {y + 200}", "sleep 0.2", *(["key Down"] * downs), "key Return")

    def test_rename_from_menu_and_keyboard(self):
        d = self.icon_backdrop("notes.txt", "a.txt")
        desktop = self.session / "home/Desktop"
        pos = self.icons(d)
        send = self.live()
        mark = d.mark()
        # Otevrit, Prejmenovat, Do Kose
        self.item_menu(d, send, pos["notes.txt"], 2)
        d.wait(r"^rename notes.txt$", start=mark)
        time.sleep(0.2)
        # vybrane je jmeno bez pripony
        send("type todo", "key Return")
        d.wait(r"^renamed notes.txt -> todo.txt$", start=mark)
        self.assertTrue((desktop / "todo.txt").exists())
        d.wait(r"^icons 2 ", start=mark)
        # poloha zustava ikone
        self.assertEqual(self.icons(d)["todo.txt"], pos["notes.txt"])
        # F2 na vybrane ikone; jmeno, ktere uz existuje, nic neprepise
        x, y = self.center(pos["a.txt"])
        mark = d.mark()
        send(f"move {x} {y}", "sleep 0.1", "click", "sleep 0.3", "key F2", "sleep 0.3", "type todo", "key Return")
        d.wait(r"^rename exists todo.txt$", start=mark)
        self.assertEqual((desktop / "a.txt").read_text(), "a.txt\n")
        self.assertEqual((desktop / "todo.txt").read_text(), "notes.txt\n")

    def test_trash_from_menu_and_delete_key(self):
        d = self.icon_backdrop("notes.txt", "b.txt", "c.txt")
        desktop = self.session / "home/Desktop"
        trash = self.session / "home/.local/share/Trash/files"
        pos = self.icons(d)
        send = self.live()
        mark = d.mark()
        self.item_menu(d, send, pos["notes.txt"], 3)
        d.wait(r"^trash notes.txt trash$", start=mark)
        d.wait(r"^icons 2 ", start=mark)
        self.assertFalse((desktop / "notes.txt").exists())
        self.assertTrue((trash / "notes.txt").exists())
        x, y = self.center(pos["b.txt"])
        mark = d.mark()
        send(f"move {x} {y}", "sleep 0.1", "click", "sleep 0.3", "key Delete")
        d.wait(r"^trash b.txt trash$", start=mark)
        d.wait(r"^icons 1 ", start=mark)
        self.assertEqual(sorted(p.name for p in trash.iterdir()), ["b.txt", "notes.txt"])

    def test_rubber_band_selects(self):
        d = self.icon_backdrop("a.txt", "b.txt", "c.txt", "d.txt")
        pos = self.icons(d)
        self.assertEqual(pos["c.txt"], (0, 2))
        send = self.live()
        mark = d.mark()
        # z prazdneho mista vpravo dolu pres a, b az do horni casti c (tlacitko drzi jedna klavesnice/ukazatel:
        # konec `wlt input` by tlacitko pustil)
        bx, by = self.center(pos["c.txt"])
        send("move 300 50", "sleep 0.2", "down", "sleep 0.05", "move 250 100", "sleep 0.05", "move 200 200", "sleep 0.05",
             f"move {bx} {by - 10}")
        d.wait(r"^selected a.txt,b.txt,c.txt$", start=mark)
        time.sleep(0.3)
        image = self.shot()
        send("up")
        # obdelnik vyberu je videt (modry nadech) a po pusteni zmizi
        self.assertNotEqual(pixel(image, 250, 150), "284682")
        time.sleep(0.2)
        self.assertEqual(pixel(self.shot(), 250, 150), "284682")
        self.assertFalse(any(l.startswith("selected") and "d.txt" in l for _, l in d.lines[mark:]))
        # klik do prazdna vyber zrusi
        mark = d.mark()
        self.input("move 600 400", "click")
        d.wait(r"^selected $", start=mark)

    def test_drag_rearranges_and_positions_persist(self):
        d = self.icon_backdrop("a.txt", "b.txt")
        pos = self.icons(d)
        x, y = self.center(pos["a.txt"])
        tx, ty = self.center((3, 2))
        mark = d.mark()
        self.input(f"drag {x} {y} {tx} {ty} 500")
        d.wait(r"^moved a.txt 3,2$", start=mark)
        time.sleep(0.3)
        self.assertNotEqual(pixel(self.shot(), tx, ty), "284682")
        # na obsazenou bunku: nejblizsi volna
        bx, by = self.center(pos["b.txt"])
        mark = d.mark()
        self.input(f"drag {bx} {by} {tx} {ty} 400")
        _, m = d.wait(r"^moved b.txt (\d+),(\d+)$", start=mark)
        b_pos = (int(m.group(1)), int(m.group(2)))
        self.assertNotEqual(b_pos, (3, 2))
        self.assertLessEqual(abs(b_pos[0] - 3) + abs(b_pos[1] - 2), 1)
        saved = (self.session / "config/luxos/desktop-icons").read_text().splitlines()
        self.assertIn("3 2 a.txt", saved)
        # novy start plochy: stejne polohy
        d.proc.terminate()
        d.proc.wait(5)
        d2 = self.backdrop()
        d2.wait(r"^icons drawn")
        self.assertEqual(self.icons(d2), {"a.txt": (3, 2), "b.txt": b_pos})

    def test_keyboard_navigation_and_window_focus(self):
        d = self.icon_backdrop("a.txt", "b.txt", "c.txt")
        client = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test") / "bin/wlt-client"
        before = self.shot()
        p = subprocess.Popen([str(client), "--events", "--title", "T", "--size", "200x120"], env=self.env, stdout=subprocess.PIPE)
        self.procs.append(p)
        c = Proc(p)
        c.wait(r"^configure")
        time.sleep(0.3)
        wx, wy = self.new_window_center(before)
        pos = self.icons(d)
        x, y = self.center(pos["a.txt"])
        mark = d.mark()
        cmark = c.mark()
        # jedna virtualni klavesnice po celou dobu (nova by vzala fokus): okno, plocha, okno
        self.input("key shift", f"move {wx} {wy}", "click", "sleep 0.2", "key a", "sleep 0.2",
                   f"move {x} {y}", "sleep 0.1", "click", "sleep 0.3", "key Down", "sleep 0.1", "key Down", "sleep 0.1",
                   "key Up", "sleep 0.1", "key Return", "sleep 0.3",
                   f"move {wx} {wy}", "sleep 0.1", "click", "sleep 0.3", "key c", "sleep 0.2")
        d.wait(r"^open b.txt$", start=mark)
        out = [l for _, l in d.lines[mark:] if l.startswith("selected")]
        self.assertEqual(out, ["selected a.txt", "selected b.txt", "selected c.txt", "selected b.txt"])
        c.wait(r"^key a down", start=cmark)
        c.wait(r"^key c down", start=cmark)
        # sipky a Enter nesly do okna
        self.assertFalse(any("key Down" in l or "key Return" in l for _, l in c.lines[cmark:]))
        self.assertEqual(self.ran_lines(1), [f"open {self.session / 'home/Desktop/b.txt'}"])

    def test_drop_files_from_file_manager(self):
        d = self.icon_backdrop("a.txt")
        src = self.session / "outside.txt"
        src.write_text("x\n")
        env = dict(self.env)
        before = self.shot()
        p = subprocess.Popen(["python3", str(HERE / "backdrop/drag_source.py"), str(src)], env=env, stdout=subprocess.PIPE)
        self.procs.append(p)
        s = Proc(p)
        s.wait(r"^ready$")
        time.sleep(0.5)
        wx, wy = self.new_window_center(before)
        mark = d.mark()
        # z okna zdroje pustit vpravo dole na plose
        self.input(f"drag {wx} {wy} 700 450 600")
        d.wait(r"^drop copy 1$", start=mark)
        lines = self.ran_lines(1)
        desktop_uri = (self.session / "home/Desktop").as_uri()
        self.assertEqual(lines[-1], f"gio copy -- {src.as_uri()} {desktop_uri}")
        # skutecna kopie (nahradni gio jen zapisuje): soubor se objevi v bunce, kam byl pusten
        mark = d.mark()
        shutil.copy(src, self.session / "home/Desktop/outside.txt")
        d.wait(r"^icons 2 ", start=mark)
        col, row = self.icons(d)["outside.txt"]
        self.assertEqual((col, row), ((700 - GRID_X) // CELL_W, (450 - GRID_Y) // CELL_H))

    def icon_golden(self, mode):
        self.start(size="640x400")
        (self.conf / "appearance").write_text(mode + "\n")
        wall = self.image("wall.png", 320, 200, pattern(320, 200))
        self.set_conf(f"WALLPAPER={wall}\n")
        self.desktop_files("Projects/", "notes.txt", "Velmi dlouhy nazev souboru na dva radky.txt")
        d = self.backdrop()
        d.wait(r"^icons drawn")
        x, y = self.center(self.icons(d)["notes.txt"])
        mark = d.mark()
        self.input(f"move {x} {y}", "click", "move 600 380")
        d.wait(r"^icons drawn", start=mark)
        time.sleep(0.3)
        self.compare_golden(f"icons-{mode}", self.shot())

    def test_icons_golden_light(self):
        self.icon_golden("light")

    def test_icons_golden_dark(self):
        self.icon_golden("dark")

    def test_icons_off_with_style_0(self):
        self.start()
        channel = self.session / "config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml"
        channel.write_text(DESKTOP_CHANNEL.replace('name="style" type="int" value="2"', 'name="style" type="int" value="0"'))
        self.desktop_files("notes.txt")
        d = self.backdrop()
        d.wait(r"^drawn HEADLESS-1")
        self.assertEqual(self.icons(d), {})
        # zmena kanalu plati hned
        mark = d.mark()
        channel.write_text(DESKTOP_CHANNEL)
        d.wait(r"^icons 1 ", start=mark)

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
        # i s ikonami plochy (monitor ~/Desktop, GVolumeMonitor) zadne probuzeni
        self.desktop_files("notes.txt", "Projects/")
        d = self.backdrop()
        d.wait(r"^drawn HEADLESS-2")
        d.wait(r"^icons drawn")
        w = self.widgets("today,calendar")
        pids = {"backdrop": d.proc.pid, "widgets": w.pid}
        # GIO nacita ikony a informace o souborech ve vlaknech GThreadPool ("pool-N"); necinne vlakno ceka
        # 15 s (max idle time GLib), pak se probudi a skonci. Merit az bez nich, jinak 1-10 probuzeni navic
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and any(pool_threads(p) for p in pids.values()):
            time.sleep(0.5)
        time.sleep(1)
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
