#!/usr/bin/env python3
"""Horni lista na Waylandu (files/lsl/luxos-bar.lsl) proti beznemu labwc headless (pixman) z harnessu WP-1.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_bar_wl.py -v

Kazdy test ma vlastni relaci `scripts/wl-test/wlt start` (soukrome XDG_RUNTIME_DIR, HOME, XDG_CONFIG_HOME).
Lista bezi s LUXOS_BAR_TRACE=1 (udalosti na stdout) a zastavenymi hodinami (LUXOS_BAR_NOW). Sluzby D-Bus
(NetworkManager, UPower, locale1, historie oznameni, polozka oznamovaci oblasti) jsou nahradni na soukromych
sbernicich (fake_bar_services.py), skutecna sbernice ani obrazovka se nepouziva.

Snimky: tests/wl-bar-goldens/*.png, porovnani s toleranci (pismo a ikony z hostitele). Novy vzor:
LUXOS_BAR_UPDATE_GOLDENS=1. Sysroot s labwc/grim: WLT_SYSROOT (vychozi out/wl-test/sysroot, fetch-sysroot.sh).
"""
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import zlib

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
REPO = PKG.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
GOLDENS = HERE / "wl-bar-goldens"
UPDATE = os.environ.get("LUXOS_BAR_UPDATE_GOLDENS") == "1"
NOW = "2026-11-20 09:41"
BAR = 28
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test") / "sysroot")
HAVE_LABWC = (SYSROOT / "usr/bin/labwc").exists() or shutil.which("labwc")
TOOLS = all(shutil.which(t) for t in ("make", "gcc", "wayland-scanner", "pkg-config"))


# ---- obrazky -----------------------------------------------------------------------------------------

def png_write(path, width, height, rgb):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    rows = b"".join(b"\0" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def png_read(path):
    """8bit RGB/RGBA bez prokladani (vzory zapisuje png_write) -> (sirka, vyska, RGB)."""
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
    data = Path(path).read_bytes()
    magic, size, depth, pixels = data.split(b"\n", 3)
    width, height = map(int, size.split())
    return width, height, pixels


def crop(image, x, y, w, h):
    width, _, pixels = image
    return w, h, b"".join(pixels[((y + r) * width + x) * 3:((y + r) * width + x + w) * 3] for r in range(h))


def pixel(image, x, y):
    width, _, pixels = image
    return pixels[(y * width + x) * 3:(y * width + x) * 3 + 3].hex()


def gradient(width, height, top, bottom):
    rows = []
    for y in range(height):
        t = y / max(1, height - 1)
        c = bytes(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        rows.append(c * width)
    return b"".join(rows)


def white_contrast(v):
    """Kontrast bileho pisma na sede tapete v (0-255) podle WCAG (luxos-bar.lsl decide_look)."""
    c = v / 255
    lin = c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 1.05 / (lin + 0.05)


# ---- relace ---------------------------------------------------------------------------------------------

class Bar:
    """Bezici lista: radky stdout s casem prijeti."""

    def __init__(self, proc):
        self.proc = proc
        self.lines = []
        self.cond = threading.Condition()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for raw in self.proc.stdout:
            with self.cond:
                self.lines.append(raw.decode(errors="replace").rstrip("\n"))
                self.cond.notify_all()
        with self.cond:
            self.cond.notify_all()

    def wait(self, pattern, timeout=10, start=0):
        """Prvni radek od indexu start odpovidajici regularnimu vyrazu -> (index, match)."""
        rx = re.compile(pattern)
        deadline = time.monotonic() + timeout
        with self.cond:
            while True:
                for i in range(start, len(self.lines)):
                    m = rx.search(self.lines[i])
                    if m:
                        return i, m
                left = deadline - time.monotonic()
                if left <= 0 or (self.proc.poll() is not None and not self.lines[start:]):
                    raise AssertionError(f"{pattern!r} se neobjevilo:\n" + "\n".join(self.lines[-40:]))
                self.cond.wait(min(left, 0.2))

    def mark(self):
        with self.cond:
            return len(self.lines)


@unittest.skipUnless(LSLC and HAVE_LABWC and TOOLS and WLT.exists(), "chybi lslc, labwc (WLT_SYSROOT) nebo nastroje sestaveni")
class WaylandBar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
        base.mkdir(parents=True, exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(prefix="luxos-bar-wl-", dir=base))
        r = subprocess.run(["make", "-s", "-C", str(PKG / "files/src/luxos-wl"), f"OUT={cls.tmp}"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("libluxos-wl: " + r.stdout + r.stderr)
        cls.lib = cls.tmp / "libluxos-wl.so.0"
        src = cls.tmp / "lsl"
        src.mkdir()
        for f in (PKG / "files/lsl").glob("*.lsl"):
            shutil.copy(f, src)
        shutil.copy(HERE / "lsl/luxos-wl-window.lsl", src)
        for name in ("luxos-bar", "luxos-wl-window"):
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

    def start(self, outputs=1, dark=False, wallpaper="light", size="1280x800"):
        # kratky nazev: cesta soketu Waylandu ma nejvys 108 znaku
        name = f"b{os.getpid()}-{sorted(n for n in dir(self) if n.startswith('test_')).index(self._testMethodName)}"
        size_args = ["--size", size] if size else []
        self.session = Path(self.wlt("start", "--mode", "headless", "--outputs", str(outputs), *size_args,
                                     "--timeout", "900", "--name", name).strip())
        env = {}
        for line in self.wlt("env", str(self.session)).splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            env[key] = value
        # GTK hostitele, ne knihovny sysrootu kompozitoru
        env.pop("LD_LIBRARY_PATH", None)
        env.update(GDK_BACKEND="wayland", NO_AT_BRIDGE="1", LUXOS_WL_LIB=str(self.lib), LUXOS_BAR_TRACE="1",
                   LUXOS_BAR_NOW=NOW, GTK_A11Y="none")
        self.env = env
        conf = self.session / "config"
        (conf / "luxos").mkdir(parents=True, exist_ok=True)
        (conf / "gtk-3.0").mkdir(parents=True, exist_ok=True)
        theme = "WhiteSur" if Path("/usr/share/icons/WhiteSur").exists() else "Adwaita"
        (conf / "gtk-3.0/settings.ini").write_text(f"[Settings]\ngtk-icon-theme-name={theme}\ngtk-font-name=Inter 10\n"
                                                   "gtk-enable-animations=false\n")
        self.set_look(dark, wallpaper)
        return self.session

    def wallpaper(self, kind):
        path = self.session / f"wall-{kind}.png"
        if kind == "light":
            png_write(path, 320, 200, gradient(320, 200, (246, 241, 232), (226, 232, 246)))
        elif kind == "dark":
            png_write(path, 320, 200, gradient(320, 200, (24, 30, 62), (46, 28, 60)))
        else:
            v = int(kind.removeprefix("gray"))
            png_write(path, 64, 40, bytes([v, v, v]) * (64 * 40))
        return path

    def set_look(self, dark, wallpaper):
        conf = self.session / "config/luxos"
        (conf / "appearance").write_text("dark\n" if dark else "light\n")
        tmp = conf / "appearance.conf.new"
        tmp.write_text(f"WALLPAPER={self.wallpaper(wallpaper)}\n")
        tmp.rename(conf / "appearance.conf")

    def bar(self, env=None):
        p = subprocess.Popen([str(self.tmp / "luxos-bar")], env=env or self.env, stdout=subprocess.PIPE)
        self.procs.append(p)
        bar = Bar(p)
        bar.wait(r"^ready$")
        return bar

    def spawn(self, *cmd, env=None):
        p = subprocess.Popen(list(cmd), env=env or self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        return p

    def client(self, app_id, title, size="300x200", color="3a6ea5"):
        client = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test") / "bin/wlt-client"
        return self.spawn(str(client), "--app-id", app_id, "--title", title, "--size", size, "--color", color)

    def input(self, *cmds):
        self.wlt("input", str(self.session), *cmds)

    def shot(self):
        path = self.session / "shot.ppm"
        self.wlt("shot", str(self.session), str(path))
        return ppm_read(path)

    def compare_golden(self, name, image):
        golden = GOLDENS / f"{name}.png"
        out = self.session / f"{name}.png"
        png_write(out, *image)
        keep = Path(os.environ.get("LUXOS_BAR_SHOTS") or self.tmp.parent / "bar-shots")
        keep.mkdir(parents=True, exist_ok=True)
        shutil.copy(out, keep / f"{name}.png")
        if UPDATE or not golden.exists():
            GOLDENS.mkdir(exist_ok=True)
            shutil.copy(out, golden)
            if not UPDATE:
                self.skipTest(f"vzor {golden} vytvoren")
        want = png_read(golden)
        self.assertEqual(want[:2], image[:2], "jina velikost nez vzor")
        a, b = want[2], image[2]
        diff = [abs(a[i] - b[i]) for i in range(len(a))]
        bad = sum(1 for i in range(0, len(diff), 3) if max(diff[i:i + 3]) > 48) / (len(diff) // 3)
        mean = sum(diff) / len(diff)
        print(f"\n  {name}: prumerny rozdil {mean:.2f}, odlisne pixely {bad * 100:.2f} %")
        self.assertLess(mean, 4.0, f"snimek {out} se lisi od {golden}")
        self.assertLess(bad, 0.02, f"snimek {out} se lisi od {golden}")

    # ---- vzhled ----

    def golden_case(self, dark, wallpaper, ink, name):
        self.start(dark=dark, wallpaper=wallpaper)
        bar = self.bar()
        _, m = bar.wait(r"^look HEADLESS-1 ink=(\w+) scrim=(\d+)")
        self.assertEqual(m.group(1), ink)
        self.assertEqual(m.group(2), "0")
        bar.wait(r"^drawn HEADLESS-1 1280x28")
        time.sleep(0.5)
        image = self.shot()
        self.assertEqual(image[:2], (1280, 800))
        self.compare_golden(name, crop(image, 0, 0, 1280, BAR))
        # pod listou nic (zadna plocha zavoje, okno listy presne 28 px)
        self.assertEqual(pixel(image, 640, BAR + 2), "000000")

    def test_golden_light(self):
        self.golden_case(False, "light", "dark", "bar-light")

    def test_golden_dark(self):
        self.golden_case(True, "dark", "white", "bar-dark")

    def test_ink_hysteresis_and_live_reload(self):
        # seda tapeta s kontrastem bileho pisma mezi prahy (2,0 tmave / 2,3 zpet bile)
        middle = next(v for v in range(150, 256) if 2.05 < white_contrast(v) < 2.25)
        self.start(wallpaper="light")
        bar = self.bar()
        bar.wait(r"^look HEADLESS-1 ink=dark scrim=0")
        steps = [(f"gray{middle}", "dark"), ("dark", "white"), (f"gray{middle}", "white"), ("light", "dark")]
        for wall, ink in steps:
            mark = bar.mark()
            self.set_look(False, wall)
            if wall == f"gray{middle}":
                # stejne pismo jako dosud: zadna zmena (hystereze); lista jen znovu nacte tapetu
                time.sleep(1.0)
                changes = [l for l in bar.lines[mark:] if l.startswith("look ")]
                self.assertTrue(all(f"ink={ink}" in l for l in changes), changes)
            else:
                bar.wait(rf"^look HEADLESS-1 ink={ink}", start=mark)
        # tmavy rezim: vzdy bile pismo, na svetle tapete zavoj
        mark = bar.mark()
        self.set_look(True, "gray250")
        _, m = bar.wait(r"^look HEADLESS-1 ink=white scrim=(\d+)", start=mark)
        self.assertGreater(int(m.group(1)), 50)

    # ---- okna ----

    def test_app_name_follows_activation(self):
        self.start()
        apps = self.session / "home/.local/share/applications"
        apps.mkdir(parents=True)
        (apps / "org.example.Foo.desktop").write_text("[Desktop Entry]\nType=Application\nName=Foo Example\n"
                                                      "Name[cs]=Foo priklad\nExec=foo\n[Desktop Action x]\nName=Other\n")
        bar = self.bar()
        bar.wait(r"^app Desktop$")
        self.client("luxos-terminal", "One", "400x300")
        bar.wait(r"^app Terminal$")
        mark = bar.mark()
        # sirsi a nizsi nez prvni okno: po zvednuti prvniho z nej vlevo a vpravo vycniva
        self.client("org.example.Foo", "Two", "600x100", "20a040")
        bar.wait(r"^app Foo Example$", start=mark)
        # klik do prvniho okna (vetsi, presahuje druhe) ho aktivuje
        mark = bar.mark()
        self.input("move 450 300", "click")
        bar.wait(r"^app Terminal$", start=mark)
        mark = bar.mark()
        self.input("move 360 400", "click")
        bar.wait(r"^app Foo Example$", start=mark)
        # bez .desktop titulek okna, nikdy syrovy app_id programu; koren Xwayland ze sandboxu ani ten ne
        mark = bar.mark()
        self.client("luxos-displays-settings", "Monitory", "300x200", "a04020")
        bar.wait(r"^app Monitory$", start=mark)
        mark = bar.mark()
        self.client("org.example.NoDesktop", "Xwayland on :0", "300x200", "4020a0")
        bar.wait(r"^app Desktop$", start=mark)
        self.assertFalse([line for line in bar.lines if re.match(r"^app (luxos-displays-settings|org\.example|Xwayland)", line)])
        # zadne aktivni okno: Plocha (posledni okno bez .desktop uz Plochu ukazuje, takze novy radek prijit
        # nemusi - plati posledni hlaseni, az vsechna okna skonci)
        for p in self.procs[1:]:
            p.terminate()
        for p in self.procs[1:]:
            p.wait(10)
        time.sleep(1.0)
        with bar.cond:
            apps = [line for line in bar.lines if line.startswith("app ")]
        self.assertEqual(apps[-1], "app Desktop", apps)

    def test_exclusive_zone_under_maximized_window(self):
        self.start()
        bar = self.bar()
        bar.wait(r"^drawn ")
        win = subprocess.Popen([str(self.tmp / "luxos-wl-window"), "luxos.test.max", "Max", "#0000ff", "--maximize"],
                               env=self.env, stdout=subprocess.PIPE)
        self.procs.append(win)
        Bar(win).wait(r"^shown$")
        time.sleep(0.5)
        image = self.shot()
        column = [pixel(image, 640, y) for y in range(200)]
        first_blue = column.index("0000ff")
        # lista zustava nahore, okno (titulek labwc, pak obsah) zacina az pod vyhradnou zonou
        self.assertNotIn("0000ff", column[:BAR])
        self.assertGreater(first_blue, BAR)
        self.assertLess(first_blue, BAR + 60)
        self.assertEqual(pixel(image, 640, 799), "0000ff")

    def test_two_outputs_and_unplug(self):
        self.start(outputs=2, size=None)
        bar = self.bar()
        bar.wait(r"^bar added HEADLESS-1 1280x720")
        bar.wait(r"^bar added HEADLESS-2 1280x720")
        bar.wait(r"^drawn HEADLESS-2")
        time.sleep(0.5)
        image = self.shot()
        self.assertEqual(image[:2], (2560, 720))
        # na obou vystupech lista (sklo, ne cerne pozadi), pod ni cerno
        for x in (20, 1280 + 20, 640, 1280 + 640):
            self.assertNotEqual(pixel(image, x, 16), "000000")
            self.assertEqual(pixel(image, x, BAR + 2), "000000")
        mark = bar.mark()
        self.wlt("run", str(self.session), "wlr-randr", "--output", "HEADLESS-2", "--off")
        bar.wait(r"^bar removed HEADLESS-2", start=mark)
        time.sleep(0.5)
        self.assertIsNone(bar.proc.poll(), "lista po odpojeni vystupu skoncila")
        self.assertEqual(sum(1 for l in bar.lines if l.startswith("bar added")) -
                         sum(1 for l in bar.lines if l.startswith("bar removed")), 1)
        # Opetovne zapnuti nejde overit: labwc 0.20.3/wlroots 0.20.2 pak spadne na assert v head_send_state
        # (wlr_output_management_v1.c:777), kdyz nejaky klient drzi zwlr_output_manager (tady lista pres libluxos-wl);
        # bez takoveho klienta zapnuti projde. Headless vystup nema seznam rezimu. Hlaseno pro WP-2.

    # ---- vyskakovaci okna ----

    def test_popup_open_time_and_close(self):
        self.start()
        bar = self.bar()
        bar.wait(r"^drawn ")
        # Oznameni vpravo, hodiny uprostred (otevrou Kalendar hubu, test_luxos_hub_wl)
        bell = "move 1262 14"
        # prvni otevreni stavi okno (studene), pak teple
        mark = bar.mark()
        self.input(bell, "click")
        _, m = bar.wait(r"^popup notifications shown event_ms=(-?\d+) handler_ms=(\d+)", start=mark)
        cold = int(m.group(1))
        time.sleep(0.3)
        image = self.shot()
        # okno ze skla pod zvonkem, pod vyhradnou zonou listy
        self.assertNotEqual(pixel(image, 1240, BAR + 30), "000000")
        self.assertEqual(pixel(image, 1150, BAR + 2), "000000")
        mark = bar.mark()
        self.input("key Escape")
        bar.wait(r"^popup notifications hidden", start=mark)
        warm = []
        for _ in range(8):
            mark = bar.mark()
            self.input(bell, "click")
            _, m = bar.wait(r"^popup notifications shown event_ms=(-?\d+) handler_ms=(\d+)", start=mark)
            warm.append(int(m.group(1)))
            mark = bar.mark()
            self.input(bell, "click")
            bar.wait(r"^popup notifications hidden", start=mark)
        warm.sort()
        print(f"\n  oznameni: studene {cold} ms, teple median {warm[len(warm) // 2]} ms, max {warm[-1]} ms (klik -> snimek)")
        self.assertTrue(all(v >= 0 for v in warm), "cas udalosti neni CLOCK_MONOTONIC")
        self.assertLessEqual(warm[len(warm) // 2], 120)
        self.assertLessEqual(warm[-1], 120)
        # klik mimo okno ho zavre (ztrata fokusu)
        mark = bar.mark()
        self.input(bell, "click")
        bar.wait(r"^popup notifications shown", start=mark)
        mark = bar.mark()
        self.input("move 640 600", "click")
        bar.wait(r"^popup notifications hidden", start=mark)
        time.sleep(0.3)
        self.assertEqual(pixel(self.shot(), 1240, BAR + 30), "000000")

    def test_clock_center_and_rounded_corners(self):
        # jako lista verze 1.0.5: hodiny uprostred a zaoblene spodni rohy; BAR_CLOCK=right a BAR_STYLE=classic vrati
        # hodiny vpravo a rovne rohy bez restartu
        self.start()
        bar = self.bar()
        bar.wait(r"^drawn ")
        time.sleep(0.4)

        def ink(image, x0, x1):
            # tmave pismo listy na svetle tapete
            return sum(1 for x in range(x0, x1) for y in range(8, 20) if int(pixel(image, x, y)[:2], 16) < 110)

        image = self.shot()
        self.assertGreater(ink(image, 590, 690), 40, "hodiny uprostred")
        # roh: pod zaoblenim nic (cerny vystup bez tapety), kousek dal uz sklo listy
        self.assertEqual(pixel(image, 0, BAR - 1), "000000")
        self.assertEqual(pixel(image, 1279, BAR - 1), "000000")
        self.assertNotEqual(pixel(image, 12, BAR - 1), "000000")
        self.assertNotEqual(pixel(image, 0, 2), "000000")
        conf = self.session / "config/luxos/appearance.conf"
        tmp = conf.with_suffix(".new")
        tmp.write_text(conf.read_text() + "BAR_CLOCK=right\nBAR_STYLE=classic\n")
        tmp.rename(conf)
        time.sleep(0.8)
        image = self.shot()
        self.assertLess(ink(image, 590, 690), 5, "hodiny vpravo")
        self.assertGreater(ink(image, 1180, 1276), 40, "hodiny vpravo")
        self.assertNotEqual(pixel(image, 0, BAR - 1), "000000")
        self.assertNotEqual(pixel(image, 1279, BAR - 1), "000000")

    def test_account_row_opens_luxos_account(self):
        # radek s fotkou a jmenem v nabidce systemu otevre ucet LuxAI jako jmeno uzivatele v nabidce na X11
        self.start()
        fake = self.session / "fakebin"
        fake.mkdir()
        opened = self.session / "account-opened"
        (fake / "luxos-account").write_text(f"#!/bin/sh\necho \"$@\" > {opened}\n")
        (fake / "luxos-account").chmod(0o755)
        bar = self.bar(dict(self.env, PATH=f"{fake}:{self.env['PATH']}"))
        bar.wait(r"^drawn ")
        mark = bar.mark()
        self.input("move 14 14", "click")
        bar.wait(r"^popup system shown", start=mark)
        time.sleep(0.3)
        mark = bar.mark()
        # jmeno vpravo od fotky na prvnim radku karty (okraj 8, karta 6 px pod listou)
        self.input("move 120 66", "click")
        bar.wait(r"^popup system hidden", start=mark)
        for _ in range(50):
            if opened.exists():
                break
            time.sleep(0.1)
        self.assertTrue(opened.exists(), "luxos-account se nespustil")
        self.assertEqual(opened.read_text().strip(), "")

    def test_logo_opens_system_menu_and_signal_opens_wifi(self):
        self.start()
        bar = self.bar()
        bar.wait(r"^drawn ")
        mark = bar.mark()
        self.input("move 14 14", "click")
        bar.wait(r"^popup system shown", start=mark)
        time.sleep(0.3)
        image = self.shot()
        # nabidka systemu ze skla vlevo pod logem, pod vyhradnou zonou listy
        self.assertNotEqual(pixel(image, 60, BAR + 40), "000000")
        self.assertEqual(pixel(image, 60, BAR + 2), "000000")
        mark = bar.mark()
        self.input("move 14 14", "click")
        bar.wait(r"^popup system hidden", start=mark)
        # SIGUSR1 (zbytek dlazdice Wi-Fi v Ovladacim centru): okno Wi-Fi; PID v $XDG_RUNTIME_DIR/luxos-bar.pid
        pid = int((Path(self.env["XDG_RUNTIME_DIR"]) / "luxos-bar.pid").read_text())
        self.assertEqual(pid, bar.proc.pid)
        mark = bar.mark()
        os.kill(pid, signal.SIGUSR1)
        bar.wait(r"^signal wifi$", start=mark)
        bar.wait(r"^popup wifi shown", start=mark)
        # SIGUSR2 (tlacitko napajeni v Ovladacim centru): nabidka LuxOS pod logem misto okna Wi-Fi
        mark = bar.mark()
        os.kill(pid, signal.SIGUSR2)
        bar.wait(r"^signal system$", start=mark)
        bar.wait(r"^popup system shown", start=mark)
        self.assertIsNone(bar.proc.poll())

    # ---- stav systemu (soukrome sbernice) ----

    def private_buses(self):
        bus_dir = self.session / "dbus"
        bus_dir.mkdir()
        addrs = {}
        for name in ("system", "session"):
            p = subprocess.Popen(["dbus-daemon", "--session", f"--address=unix:path={bus_dir / name}", "--nofork",
                                  "--nopidfile"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.procs.append(p)
            addrs[name] = f"unix:path={bus_dir / name}"
        for name in ("system", "session"):
            for _ in range(100):
                if (bus_dir / name).exists():
                    break
                time.sleep(0.05)
        return addrs

    @unittest.skipUnless(shutil.which("dbus-daemon"), "chybi dbus-daemon")
    def test_status_items_from_dbus(self):
        # tmave sklo s bilym pismem: ikona oznamovaci oblasti se na snimku najde podle svetlych pixelu
        self.start(dark=True, wallpaper="dark")
        addrs = self.private_buses()
        fake = subprocess.Popen(["python3", "-I", str(HERE / "fake_bar_services.py"), addrs["system"], addrs["session"]],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=dict(os.environ, PYTHONUNBUFFERED="1"))
        self.procs.append(fake)
        services = Bar(fake)
        services.wait(r"^ready$")
        # vlajka rozlozeni jako panel xkb na X11 (vlastni adresar: snimek nezavisi na hostiteli)
        flags = self.session / "flags"
        flags.mkdir()
        (flags / "cz.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="15">'
                                      '<rect width="20" height="15" fill="#d7141a"/><rect width="20" height="7.5" fill="#fff"/>'
                                      '<path d="M0 0L10 7.5L0 15Z" fill="#11457e"/></svg>')
        env = dict(self.env, DBUS_SYSTEM_BUS_ADDRESS=addrs["system"], DBUS_SESSION_BUS_ADDRESS=addrs["session"],
                   LUXOS_XKB_FLAGS=str(flags))
        bar = self.bar(env)
        bar.wait(r"^status network network-wireless-signal-excellent-symbolic$")
        bar.wait(r"^status battery battery-level-80-symbolic 76 %$")
        bar.wait(r"^status keyboard CZ$")
        # rozlozeni: tucny kod bez ramecku jako luxos-xkb.c verze 1.1.1, vlajka jen s BAR_KEYBOARD=flag
        time.sleep(0.5)
        widths = [int(line.split()[3]) for line in bar.lines if line.startswith("badge keyboard ")]
        self.assertTrue(widths and abs(widths[-1] - 35) <= 6, "keyboard item widths %s" % widths)
        # klik na kod: hned dalsi rozlozeni (luxwm IPC, tady bez luxwm jen pozadavek), bez modreho zablesku
        x = [int(line.split()[2]) + int(line.split()[3]) // 2 for line in bar.lines if line.startswith("badge keyboard ")][-1]
        mark = bar.mark()
        self.input(f"move {x} 14", "click", "move 640 400")
        bar.wait(r"^layout next 1$", start=mark)
        for _ in range(4):
            image = self.shot()
            self.assertEqual([x2 for x2 in range(x - 14, x + 14) for y in (5, 14) if pixel(image, x2, y) == "3d7bff"], [],
                             "zablesk po prepnuti rozlozeni")
            time.sleep(0.15)
        self.assertFalse(any(line.startswith("layout menu") for line in bar.lines[mark:]), "klik neotevira nabidku")
        bar.wait(r"^status notifications notification-new-symbolic$")
        bar.wait(r"^tray watcher own=True$")
        bar.wait(r"^tray \S+ audio-volume-high-symbolic Active$")
        services.wait(r"^registered$")

        def send(line):
            fake.stdin.write(line.encode() + b"\n")
            fake.stdin.flush()
        mark = bar.mark()
        send("battery 15 1")
        bar.wait(r"^status battery battery-level-20-charging-symbolic 15 %$", start=mark)
        send("strength 30")
        bar.wait(r"^status network network-wireless-signal-ok-symbolic$", start=mark)
        send("connectivity 3")
        bar.wait(r"^status network luxos-network-no-internet-symbolic$", start=mark)
        time.sleep(0.5)
        image = self.shot()
        # prava cast listy: oznamovaci oblast, CZ, Wi-Fi, baterie, Hledani, Ovladaci centrum, zvonek, hodiny
        right = crop(image, 900, 0, 380, BAR)
        self.compare_golden("bar-status", right)
        blue = lambda img: [x for x in range(900, 1280) for y in range(6, 22) if pixel(img, x, y) == "11457e"]  # noqa: E731
        self.assertEqual(blue(image), [], "flag shown although BAR_KEYBOARD is not flag")
        # vlajka na prani: modry klin vlajky misto textu CZ
        mark = bar.mark()
        conf = self.session / "config/luxos/appearance.conf"
        tmp = conf.with_suffix(".new")
        tmp.write_text(conf.read_text() + "BAR_KEYBOARD=flag\n")
        tmp.rename(conf)
        bar.wait(r"^flag cz " + re.escape(str(flags / "cz.svg")) + "$", start=mark)
        time.sleep(0.5)
        self.assertGreater(len(blue(self.shot())), 10, "no flag in the bar")
        conf.write_text(conf.read_text().replace("BAR_KEYBOARD=flag\n", ""))
        time.sleep(0.5)
        # zvonek: historie oznameni; bubliny luxos-notify skryte, dokud je okno otevrene; zavreni = precteno
        mark = bar.mark()
        self.input("move 1262 14", "click")   # zvonek vpravo (hodiny uprostred)
        bar.wait(r"^popup notifications shown", start=mark)
        services.wait(r"^popups-hidden True$")
        time.sleep(0.4)
        self.compare_golden("popup-notifications", crop(self.shot(), 1280 - 340, BAR, 340, 260))
        self.input("key Escape")
        bar.wait(r"^popup notifications hidden", start=mark)
        services.wait(r"^popups-hidden False$")
        services.wait(r"^mark-all-read$")
        bar.wait(r"^status notifications notification-symbolic$", start=mark)
        # ikona oznamovaci oblasti = Activate polozky (nejlevejsi ikona vpravo)
        tray_x = self.find_tray_icon(image)
        self.input(f"move {tray_x} 16", "click")
        services.wait(r"^activate 0 0$")
        self.assertNotIn("LSL callback error", "\n".join(bar.lines))

    def find_tray_icon(self, image):
        """Nejlevejsi svetly pixel ikony v prave casti listy (pismo listy je v tmavem skle bile)."""
        for x in range(900, 1280):
            for y in range(8, 24):
                if all(int(pixel(image, x, y)[i:i + 2], 16) > 200 for i in (0, 2, 4)):
                    return x + 8
        self.fail("ikona oznamovaci oblasti nenalezena")

    # ---- pamet a probouzeni ----

    def test_idle_memory_and_wakeups(self):
        seconds = int(os.environ.get("LUXOS_BAR_IDLE_SECONDS", "60"))
        self.start()
        bar = self.bar()
        bar.wait(r"^drawn ")
        time.sleep(3)
        pid = bar.proc.pid

        def switches():
            """Prepnuti kontextu po vlaknech (vlakno, ktere mezitim skonci, by soucet snizilo)."""
            counts = {}
            for task in Path(f"/proc/{pid}/task").iterdir():
                counts[task.name] = sum(int(line.split()[1]) for line in (task / "status").read_text().splitlines()
                                        if line.startswith(("voluntary_ctxt_switches", "nonvoluntary_ctxt_switches")))
            return counts

        def rollup():
            fields = {}
            for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines()[1:]:
                key, value = line.split(":")
                fields[key] = int(value.split()[0])
            return fields
        before = switches()
        cpu_before = sum(map(int, Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[11:13]))
        time.sleep(seconds)
        after = switches()
        wakeups = sum(max(0, n - before.get(tid, 0)) for tid, n in after.items())
        cpu = sum(map(int, Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[11:13])) - cpu_before
        mem = rollup()
        threads = len(list(Path(f"/proc/{pid}/task").iterdir()))
        print(f"\n  necinna lista: PSS {mem['Pss'] / 1024:.1f} MB, RSS {mem['Rss'] / 1024:.1f} MB, privatni "
              f"{(mem['Private_Clean'] + mem['Private_Dirty']) / 1024:.1f} MB, vlaken {threads}; za {seconds} s "
              f"{wakeups} probuzeni ({wakeups / seconds:.2f}/s), CPU {cpu} tiku")
        self.assertLess(mem["Pss"], 40 * 1024)
        # jediny casovac jsou hodiny (1x za minutu); GDK/GLib vlakna obcas, ale ne trvale
        self.assertLess(wakeups / seconds, 1.0)
        self.assertLessEqual(cpu, max(2, seconds // 30))

    # ---- systemd ----

    def unit_text(self):
        return (PKG / "files/systemd-user/luxos-bar.service").read_text()

    @unittest.skipUnless(shutil.which("systemd-analyze"), "chybi systemd-analyze")
    def test_unit_file_lint(self):
        unit = self.tmp / "luxos-bar.service"
        unit.write_text(self.unit_text().replace("/usr/bin/luxos-bar", str(self.tmp / "luxos-bar")))
        r = subprocess.run(["systemd-analyze", "--user", "verify", str(unit)], capture_output=True, text=True)
        problems = [l for l in (r.stdout + r.stderr).splitlines() if "luxos-bar" in l]
        self.assertEqual(problems, [], r.stdout + r.stderr)
        self.assertIn("Restart=always", self.unit_text())
        self.assertIn("RestartPreventExitStatus=2", self.unit_text())

    @unittest.skipUnless(shutil.which("systemd-run") and os.environ.get("XDG_RUNTIME_DIR"), "chybi uzivatelsky systemd")
    def test_crash_restart_keeps_exclusive_zone(self):
        """Prechodna sluzba se stejnymi Restart*/StartLimit* jako luxos-bar.service, v headless relaci testu."""
        props = []
        for line in self.unit_text().splitlines():
            if re.match(r"^(Restart|RestartSec|RestartPreventExitStatus|StartLimitIntervalSec|StartLimitBurst|Type)=", line):
                props += ["-p", line]
        self.start()
        win = subprocess.Popen([str(self.tmp / "luxos-wl-window"), "luxos.test.max", "Max", "#0000ff", "--maximize"],
                               env=self.env, stdout=subprocess.PIPE)
        self.procs.append(win)
        Bar(win).wait(r"^shown$")
        log = self.session / "bar-unit.log"
        unit = f"luxos-bar-test-{os.getpid()}"
        envs = []
        for k, v in self.env.items():
            envs += ["-E", f"{k}={v}"]
        subprocess.run(["systemd-run", "--user", "--quiet", f"--unit={unit}", "-p", "TasksMax=300", "-p", "RuntimeMaxSec=300",
                        "-p", f"StandardOutput=append:{log}", "-p", "StandardError=journal", *props, *envs, "--",
                        str(self.tmp / "luxos-bar")], check=True)
        try:
            def main_pid():
                out = subprocess.run(["systemctl", "--user", "show", "-p", "MainPID", "--value", unit],
                                     capture_output=True, text=True).stdout.strip()
                return int(out or 0)

            def wait_ready(count, timeout=10):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if log.exists() and log.read_text().splitlines().count("ready") >= count:
                        return time.monotonic()
                    time.sleep(0.01)
                self.fail("lista se nespustila: " + (log.read_text() if log.exists() else ""))
            wait_ready(1)
            time.sleep(0.5)
            self.assertNotIn("0000ff", [pixel(self.shot(), 640, y) for y in range(BAR)])
            pid = main_pid()
            killed = time.monotonic()
            os.kill(pid, signal.SIGKILL)
            # pada: okno se roztahne nahoru; po restartu je vyhradna zona zpet
            ready = wait_ready(2)
            restart = ready - killed
            self.assertNotEqual(main_pid(), pid)
            time.sleep(0.5)
            image = self.shot()
            column = [pixel(image, 640, y) for y in range(200)]
            print(f"\n  restart po SIGKILL: {restart * 1000:.0f} ms do 'ready'")
            self.assertLess(restart, 1.0)
            self.assertNotIn("0000ff", column[:BAR])
            self.assertGreater(column.index("0000ff"), BAR)
        finally:
            subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True)
            subprocess.run(["systemctl", "--user", "reset-failed", unit], capture_output=True)


if __name__ == "__main__":
    unittest.main()
