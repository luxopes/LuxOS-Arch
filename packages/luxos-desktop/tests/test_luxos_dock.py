#!/usr/bin/env python3
"""luxos-dock (Dock pro Wayland v LSL) proti beznemu labwc headless (pixman) pres scripts/wl-test.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -- timeout 1200 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_dock.py -v

Kazdy test ma vlastni relaci wlt (jeden vystup 1280x800, soukromy HOME a XDG_RUNTIME_DIR) a skutecne klienty:
Dock, okna GTK 3 v LSL (tests/lsl/luxos-wl-window.lsl) spoustena Dockem z .desktop souboru, vstup pres
wlt-input (virtualni mys a klavesnice), snimky pres grim. Zvetseni se meri z pixelu jako v
packages/plank/tests/dock_zoom.py: vyska Docku nad spodnim okrajem s mysi nad ikonami a po odchodu.

Vysledky (cena snimku, PSS, probuzeni, snimky obrazovky) jdou do out/dock-test/ (LUXOS_DOCK_TEST_OUT).
LUXOS_DOCK_IDLE_SECONDS = delka mereni necinnosti (vychozi 60).
"""
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import struct
import subprocess
import time
import unittest
import zlib

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
REPO = PKG.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
SYSROOT = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test") / "sysroot"
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")
OUT = Path(os.environ.get("LUXOS_DOCK_TEST_OUT") or REPO / "out/dock-test")
IDLE_SECONDS = int(os.environ.get("LUXOS_DOCK_IDLE_SECONDS", "60"))
W, H = 1280, 800
MARGIN = 0                           # luxos-dock MARGIN: panel lezi na spodnim okraji
APPS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
WINDOW = (0x3a, 0x6e, 0xa5)          # vychozi barva luxos-wl-window
ZOOM_MIN = 6
SETTLE = 0.6
LEAVE_LIMIT = 0.45                   # tokens MOTION dock_zoom_leave
CLEAN = {"DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS"}
RESULTS = {}


def ppm(path):
    data = Path(path).read_bytes()
    parts = data.split(b"\n", 3)
    w, h = map(int, parts[1].split())
    return w, h, parts[3]


def px(buf, w, x, y):
    i = (y * w + x) * 3
    return buf[i], buf[i + 1], buf[i + 2]


def differs(a, b, tol=10):
    return any(abs(a[i] - b[i]) > tol for i in range(3))


def lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def png(path, w, h, color_at):
    raw = b"".join(b"\0" + b"".join(bytes(color_at(x, y)) for x in range(w)) for y in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def percentile(values, p):
    v = sorted(values)
    return v[min(len(v) - 1, len(v) * p // 100)]


def record(name, value):
    RESULTS[name] = value
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(RESULTS, indent=1))


@unittest.skipUnless(LSLC and (SYSROOT / "usr/bin/labwc").exists() and shutil.which("make"),
                     "chybi lslc, sysroot wl-test (scripts/wl-test/fetch-sysroot.sh) nebo make")
class DockBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = OUT / "bin"
        src = OUT / "lsl"
        for d in (cls.bin, src):
            d.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["make", "-s", "-C", str(PKG / "files/src/luxos-wl"), f"OUT={cls.bin}"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("libluxos-wl: " + r.stdout + r.stderr)
        for f in list((PKG / "files/lsl").glob("*.lsl")) + list((HERE / "lsl").glob("*.lsl")):
            shutil.copy(f, src)
        for name in ("luxos-dock", "luxos-wl-window", "luxos-dock-model-test"):
            r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(src), str(src / f"{name}.lsl"),
                                str(cls.bin / name)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"{name}: " + r.stdout + r.stderr)
        subprocess.run([str(WLT), "build"], check=True, capture_output=True)

    # ---- relace ----

    def setUp(self):
        # kratke jmeno: soket luxwm v relaci musi projit do sun_path (108 znaku)
        name = "dock-" + self.id().rsplit(".", 1)[-1].replace("_", "-")[5:24]
        r = subprocess.run([str(WLT), "start", "--size", f"{W}x{H}", "--name", name, "--timeout", "600",
                            *self.compositor()], capture_output=True, text=True, env=self.outer())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.s = Path(r.stdout.strip().splitlines()[-1])
        self.env = {}
        for line in subprocess.run([str(WLT), "env", str(self.s)], capture_output=True, text=True).stdout.splitlines():
            k, _, v = line.removeprefix("export ").partition("=")
            self.env[k] = v
        # klienti GTK bez knihoven sysrootu labwc (vlastni cairo/pixman sysrootu se k systemovemu GTK nehodi)
        self.env.pop("LD_LIBRARY_PATH", None)
        self.env.update(GDK_BACKEND="wayland", NO_AT_BRIDGE="1", LUXOS_WL_LIB=str(self.bin / "libluxos-wl.so.0"),
                        LUXOS_DOCK_DEBUG="1")
        self.home = Path(self.env["HOME"])
        self.cfg = Path(self.env["XDG_CONFIG_HOME"])
        self.apps = self.home / ".local/share/applications"
        self.apps.mkdir(parents=True)
        for a in APPS:
            (self.apps / f"test-{a}.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=App " + a + "\n"
                f"Exec={self.bin}/luxos-wl-window cz.test.{a} \"Window {a}\"\n"
                "Icon=utilities-terminal\nStartupWMClass=cz.test." + a + "\n")
        (self.cfg / "luxos").mkdir(parents=True, exist_ok=True)
        self.procs = []
        self.dock = None
        self.inp = None
        self.seq = 0

    def tearDown(self):
        if self.inp is not None:
            self.inp.stdin.close()
            self.inp.wait(10)
            self.inp.stdout.close()
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        subprocess.run([str(WLT), "stop", str(self.s)], capture_output=True)

    def compositor(self):
        return []

    @staticmethod
    def outer():
        return {k: v for k, v in os.environ.items() if k not in CLEAN}

    def conf(self, items=None, zoom=150, hide="none"):
        items = items if items is not None else [f"test-{a}.desktop" for a in APPS] + ["trash"]
        (self.cfg / "luxos/dock.conf").write_text(f'ITEMS="{" ".join(items)}"\nZOOM={zoom}\nHIDE={hide}\n')

    def spawn(self, argv, env=None):
        p = subprocess.Popen(argv, env=env or self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        p.lines = []
        p.buf = b""
        self.procs.append(p)
        return p

    def pump(self, p, timeout=0.0):
        end = time.monotonic() + timeout
        while True:
            left = max(0.0, end - time.monotonic())
            r, _, _ = select.select([p.stdout], [], [], left)
            if not r:
                return
            chunk = os.read(p.stdout.fileno(), 65536)
            if not chunk:
                return
            p.buf += chunk
            while b"\n" in p.buf:
                line, p.buf = p.buf.split(b"\n", 1)
                p.lines.append(line.decode("utf-8", "replace"))
            if time.monotonic() >= end:
                return

    def wait_line(self, p, pattern, timeout=10, start=0):
        """Prvni radek od indexu start odpovidajici regularnimu vyrazu; vraci (index, match)."""
        rx = re.compile(pattern)
        end = time.monotonic() + timeout
        while True:
            for i in range(start, len(p.lines)):
                m = rx.search(p.lines[i])
                if m:
                    return i, m
            if time.monotonic() > end:
                self.fail(f"no line {pattern!r}; output:\n" + "\n".join(p.lines[-40:]))
            self.pump(p, 0.1)

    def start_dock(self, **env):
        self.dock = self.spawn([str(self.bin / "luxos-dock")], dict(self.env, **env))
        self.wait_line(self.dock, r" ready ")
        self.centers = self.slots()
        time.sleep(0.5)
        return self.dock

    def slots(self):
        """Stredy ikon na vystupu podle posledniho radku slots (po zmene poctu polozek)."""
        self.pump(self.dock, 0.2)
        line = [line for line in self.dock.lines if " slots " in line][-1].split()
        return [(W - int(line[2])) // 2 + int(c) for c in line[4:]]

    def stop_dock(self):
        self.dock.terminate()
        self.dock.wait(5)

    def run_window(self, app):
        return self.spawn([str(self.bin / "luxos-wl-window"), f"cz.test.{app}", f"Window {app}"])

    def input(self, *cmds):
        """Prikazy jednomu stale bezicimu `wlt input`: virtualni klavesnice zustava v seatu (nova klavesnice
        kazdeho volani pripravila GTK o prvni klavesu, napr. Escape nebo sipku v nabidce); `echo` = hotovo."""
        if self.inp is None:
            self.inp = subprocess.Popen([str(WLT), "input", str(self.s)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1, env=self.outer())
        self.seq += 1
        self.inp.stdin.write("\n".join(cmds) + f"\necho done {self.seq}\n")
        self.inp.stdin.flush()
        out = []
        while (line := self.inp.stdout.readline()) != f"done {self.seq}\n":
            self.assertNotEqual(line, "", "wlt input skoncil: " + "".join(out))
            out.append(line)

    def glide(self, points, step=12, delay=0.008):
        self.input(*self.glide_cmds(points, step, delay))

    @staticmethod
    def glide_cmds(points, step=12, delay=0.008):
        cmds = []
        for (xa, ya), (xb, yb) in zip(points, points[1:]):
            n = max(1, int(max(abs(xb - xa), abs(yb - ya)) / step))
            for i in range(1, n + 1):
                cmds.append(f"move {int(xa + (xb - xa) * i / n)} {int(ya + (yb - ya) * i / n)}")
                cmds.append(f"sleep {delay}")
        return cmds

    def mouse(self, x, y):
        self.input(f"move {x} {y}")

    def shot(self, name=None, y0=H - 170):
        """Pas obrazovky od y0 dolu (grim -g); s name ulozi i PNG celeho snimku do out/dock-test/shots."""
        f = self.s / "strip.ppm"
        geo = f"0,{y0} {W}x{H - y0}"
        r = subprocess.run([str(WLT), "run", str(self.s), "grim", "-g", geo, "-t", "ppm", str(f)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        if name:
            (OUT / "shots").mkdir(parents=True, exist_ok=True)
            subprocess.run([str(WLT), "shot", str(self.s), str(OUT / "shots" / f"{name}.png")], capture_output=True)
        w, h, buf = ppm(f)
        return w, h, buf

    def height(self, span=170):
        """Vyska Docku nad spodnim okrajem (0 = Dock neni videt)."""
        w, h, buf = self.shot(y0=H - span)
        bg = px(buf, w, 2, h - 2)
        x0, x1 = int(W * 0.15), int(W * 0.85)
        for row in range(h):
            n = 0
            for x in range(x0, x1, 2):
                if differs(px(buf, w, x, row), bg):
                    n += 1
                    if n >= 4:
                        return h - row
        return 0

    def wait_height(self, pred, timeout=1.5):
        t0 = time.monotonic()
        h = self.height()
        while not pred(h) and time.monotonic() - t0 < timeout:
            h = self.height()
        return h

    def peak_x(self, base):
        """Stred x vycnivajici (zvetsene) casti Docku, None = nic nevycniva."""
        w, h, buf = self.shot(y0=H - 170)
        bg = px(buf, w, 2, h - 2)
        xs = [x for row in range(h - base - 12, h - base - 3) for x in range(int(W * 0.15), int(W * 0.85), 2)
              if differs(px(buf, w, x, row), bg)]
        return sum(xs) / len(xs) if len(xs) > 10 else None

    def items_line(self, start=0):
        i, m = self.wait_line(self.dock, r"^\d+ items (.*)$", start=start)
        return [Path(k).name for k in m.group(1).split()]

    def frames(self):
        return [int(m.group(1)) for line in self.dock.lines if (m := re.search(r" frame (\d+) ", line))]

    def lines_since(self, n):
        self.pump(self.dock, 0.05)
        return self.dock.lines[n:]


class Dock(DockBase):
    def test_model(self):
        r = subprocess.run([str(self.bin / "luxos-dock-model-test")], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("all ok", r.stdout)

    def test_zoom_leave(self):
        """Porty scenaru odchodu z dock_zoom.py: zvetseni pryc do 0,45 s, pri navratu u mysi."""
        self.conf()
        self.start_dock()
        cx = W // 2
        away = (cx, 200)
        self.mouse(*away)
        time.sleep(0.6)
        base = self.height()
        self.assertGreater(base, 40, "Dock neni videt")
        record("dock_height_px", base)
        self.shot("zoom-rest")

        # prijezd zespodu a z boku: zvetseni musi byt videt a jit za mysi
        arrivals = {}
        for name, path in [("from-below", [away, (cx, H - 200), (cx, H - 6)]),
                           ("from-side", [(3, H - 4), (cx, H - 4)]),
                           ("gap-above", [away, (cx, H - base - 10), (cx, H - 8)])]:
            self.mouse(*path[0])
            time.sleep(0.3)
            self.glide(path, step=4 if name == "gap-above" else 12)
            h = self.wait_height(lambda v: v >= base + ZOOM_MIN)
            self.glide([(cx, H - 6), (cx - 110, H - 6)])
            time.sleep(SETTLE)
            p = self.peak_x(base)
            arrivals[name] = {"height": h, "peak_x": p}
            self.assertGreaterEqual(h, base + ZOOM_MIN, f"{name}: no magnification ({h} <= {base})")
            self.assertIsNotNone(p, name)
            self.assertLess(abs(p - (cx - 110)), 50, f"{name}: magnification at {p}, mouse at {cx - 110}")
            if name == "from-below":
                self.shot("zoom-hover")
            self.mouse(*away)
            self.wait_height(lambda v: v <= base + 2)
            time.sleep(0.3)

        left, right = cx - 200, cx + 200
        scenarios = [("leave-up", [(left, H - 8), (right, H - 30), (right - 60, H - 250)], 40, 0.002),
                     ("leave-up-l", [(right, H - 8), (left, H - 40), (left, 120)], 40, 0.002),
                     ("leave-side", [(left, H - 8), (right, H - 8), (W - 4, H - 8), (W - 4, H - 250)], 40, 0.002),
                     ("leave-diag-l", [(right, H - 20), (left, H - 10), (left - 300, H - 400)], 40, 0.002),
                     ("leave-top-slow", [(cx, H - 8), (cx, H - 260)], 2, 0.012)]
        results = []
        for name, path, step, delay in scenarios + [("leave-menu", None, 0, 0)]:
            start = path[0] if path else (cx - 60, H - 8)
            self.glide([away, start])
            time.sleep(0.4)
            mark = len(self.dock.lines)
            if path:
                self.glide(path, step=step, delay=delay)
                end = path[-1]
            else:
                # pres menu ikony: nahoru do menu, Escape, pryc
                self.input("click right", "sleep 0.6", *self.glide_cmds([start, (cx - 60, H - 140)], 10, 0.01),
                           "key Escape", *self.glide_cmds([(cx - 60, H - 140), (cx - 60, H - 300)], 40, 0.002))
                end = (cx - 60, H - 300)
            t0 = time.monotonic()
            h = self.wait_height(lambda v: v <= base + 2, LEAVE_LIMIT)
            gone_s = time.monotonic() - t0
            gone = h <= base + 2
            # zustava pryc (zadne znovu-zvetseni bez mysi)
            time.sleep(0.2)
            h_later = self.height()
            back = cx + (90 if name.endswith("-l") else -90)
            self.glide([end, (back, H - 4)], step=20, delay=0.004)
            time.sleep(SETTLE)
            p = self.peak_x(base)
            follows = p is not None and abs(p - back) < 50
            # presny cas z Docku: posledni odchod mysi -> konec zmenseni
            log = self.lines_since(mark)
            # s nabidkou zvetseni ceka na jeji zavreni (zustava u ikony jako v Planku)
            leave_t = [int(line.split()[0]) for line in log if line.endswith(" hover 0") or line.endswith(" menu 0")]
            flat_t = [int(line.split()[0]) for line in log if line.endswith("zoom-end 0.0") or line.endswith("zoom-guard")]
            dock_s = None
            if leave_t and flat_t:
                after = [t for t in flat_t if t >= leave_t[-1]]
                if after:
                    dock_s = (after[0] - leave_t[-1]) / 1000
            res = {"name": name, "ok": gone and follows and h_later <= base + 2, "height_after_leave": h,
                   "height_0_2s_later": h_later, "screen_gone_s": round(gone_s, 3), "dock_leave_to_flat_s": dock_s,
                   "peak_x": p, "mouse_x": back}
            results.append(res)
            self.mouse(*away)
            self.wait_height(lambda v: v <= base + 2)
            time.sleep(0.3)
        record("zoom_arrivals", arrivals)
        record("zoom_leave", results)
        bad = [r for r in results if not r["ok"]]
        self.assertEqual(bad, [], json.dumps(results, indent=1))
        for r in results:
            if r["dock_leave_to_flat_s"] is not None:
                self.assertLessEqual(r["dock_leave_to_flat_s"], LEAVE_LIMIT, r)
        costs = self.frames()
        record("frame_cost_us", {"frames": len(costs), "p50": percentile(costs, 50), "p90": percentile(costs, 90),
                                 "max": max(costs)})
        self.assertFalse(any("magnification off" in line for line in self.dock.lines))
        self.assertLessEqual(percentile(costs[4:], 90), 4000)

    def test_zoom_control(self):
        """Kontrola mereni: bez zvetseni (ZOOM=100) a po vypnuti pres rozpocet snimku musi byt Dock s mysi nad
        ikonou nizsi nez se zvetsenim (popisek nad ikonou je v obou pripadech)."""
        cx = W // 2

        def hovered():
            self.mouse(cx, 200)
            time.sleep(0.5)
            self.glide([(cx, 200), (cx, H - 8)])
            time.sleep(SETTLE)
            h = self.height()
            self.mouse(cx, 200)
            time.sleep(0.5)
            return h
        self.conf()
        self.start_dock()
        zoomed = hovered()
        self.stop_dock()
        self.conf(zoom=100)
        self.start_dock()
        flat = hovered()
        self.stop_dock()
        self.conf()
        self.start_dock(LUXOS_DOCK_FRAME_BUDGET_US="1")
        for _ in range(3):
            self.glide([(cx, 200), (cx - 150, H - 8), (cx + 150, H - 8), (cx, 200)], step=20, delay=0.01)
            time.sleep(0.4)
        self.wait_line(self.dock, r"magnification off")
        time.sleep(0.5)
        switched_off = hovered()
        record("zoom_control", {"zoomed": zoomed, "zoom_100": flat, "budget_off": switched_off})
        self.assertLessEqual(flat, zoomed - 15)
        self.assertLessEqual(abs(switched_off - flat), 2)

    def test_launch_activate_minimize(self):
        self.conf()
        self.start_dock()
        x = self.centers[0]
        n = len(self.dock.lines)
        self.input(f"move {x} {H - 30}", "click")
        i, m = self.wait_line(self.dock, r"^(\d+) launch .*test-alpha.desktop", start=n)
        launched = int(m.group(1))
        _, m = self.wait_line(self.dock, r" window (\d+) cz\.test\.alpha ", start=n)
        handle = m.group(1)
        # spusteni = dva poskoky ikony za 600 ms jako Plank (LaunchBounceTime)
        _, m = self.wait_line(self.dock, r"^(\d+) bounce-end .*test-alpha", start=i)
        self.assertTrue(550 <= int(m.group(1)) - launched <= 1000, int(m.group(1)) - launched)
        # misto ikony okna pro animaci minimalizace (set_rectangle): slot prvni ikony, velikost ikony
        _, m = self.wait_line(self.dock, rf" rect {handle} (\d+) (\d+) (\d+) (\d+)$", start=n)
        rx, size = int(m.group(1)), int(m.group(3))
        self.assertEqual(size, int(m.group(4)))
        self.assertLessEqual(abs(rx + size // 2 - (x - (W - int([l for l in self.dock.lines if " slots " in l][-1].split()[2])) // 2)), 1)
        time.sleep(0.3)
        w, h, buf = self.shot(y0=0)
        self.assertEqual(px(buf, w, W // 2, H // 2 - 20), WINDOW, "window did not appear")
        self.shot("running-light")
        # klik na aktivni aplikaci = minimalizovat
        n = len(self.dock.lines)
        self.input("click")
        self.wait_line(self.dock, r" minimize .*test-alpha", start=n)
        time.sleep(0.5)
        w, h, buf = self.shot(y0=0)
        self.assertNotEqual(px(buf, w, W // 2, H // 2 - 20), WINDOW, "window not minimized")
        # klik znovu = aktivovat
        n = len(self.dock.lines)
        self.input("click")
        self.wait_line(self.dock, r" activate .*test-alpha", start=n)
        time.sleep(0.5)
        w, h, buf = self.shot(y0=0)
        self.assertEqual(px(buf, w, W // 2, H // 2 - 20), WINDOW, "window not activated again")
        # prostredni tlacitko = dalsi okno
        n = len(self.dock.lines)
        self.input("click middle")
        self.wait_line(self.dock, r" window (\d+) cz\.test\.alpha ", start=n)
        # nabidka: Ukoncit (posledni polozka: sipka nahoru vybere posledni) zavre obe okna
        n = len(self.dock.lines)
        self.input("click right", "sleep 0.6", "key Up", "sleep 0.3", "key Return")
        self.wait_line(self.dock, r" menu 1 ", start=n)
        self.wait_line(self.dock, r" menu 0", start=n)
        # okna spustil Dock, jejich vystup jde do jeho vystupu: obe se zavrela
        i, _ = self.wait_line(self.dock, r"^closed$", start=n)
        self.wait_line(self.dock, r"^closed$", start=i + 1)

    def test_running_unpinned_and_pin(self):
        self.conf(items=["test-alpha.desktop", "trash"])
        self.start_dock()
        n = len(self.dock.lines)
        self.run_window("beta")
        names = None
        end = time.monotonic() + 10
        while time.monotonic() < end:
            names = self.items_line(start=n)
            if names[-1] == "test-beta.desktop":
                break
            n = len(self.dock.lines)
        self.assertEqual(names, ["test-alpha.desktop", "trash", "test-beta.desktop"])
        time.sleep(0.6)
        self.shot("running-unpinned")
        # Ponechat v Docku pres nabidku: druha polozka pod nazvem (Nove okno, Ponechat v Docku)
        centers = self.slots()
        n = len(self.dock.lines)
        self.input(f"move {centers[2]} {H - 30}", "sleep 0.3", "click right", "sleep 0.6", "key Down", "sleep 0.2",
                   "key Down", "sleep 0.2", "key Return")
        self.wait_line(self.dock, r" menu 1 .*test-beta", start=n)
        self.wait_line(self.dock, r" menu 0", start=n)
        time.sleep(0.3)
        text = (self.cfg / "luxos/dock.conf").read_text()
        self.assertIn('ITEMS="test-alpha.desktop test-beta.desktop trash"', text)

    def test_add_remove_slides(self):
        """Pribyla a ubyla ikona: sousedi se posunou a ikona naroste/zmizi za 200 ms (Plank ItemMoveTime), plocha se
        zuzi az po dobehnuti (odebirana ikona se neorizne)."""
        self.conf(items=["test-alpha.desktop", "trash"])
        self.start_dock()
        n = len(self.dock.lines)
        win = self.run_window("beta")
        i, m = self.wait_line(self.dock, r"^(\d+) items .*test-beta", start=n)
        added = int(m.group(1))
        j, m = self.wait_line(self.dock, r"^(\d+) move-end ", start=i)
        took = int(m.group(1)) - added
        self.assertTrue(150 <= took <= 700, f"posun pri pridani {took} ms")
        time.sleep(0.4)
        wide = int([line for line in self.dock.lines if " slots " in line][-1].split()[2])
        n = len(self.dock.lines)
        win.terminate()
        win.wait(5)
        i, m = self.wait_line(self.dock, r"^(\d+) items \S*test-alpha.desktop trash$", start=n)
        removed = int(m.group(1))
        # hned po zmene plocha zustava siroka
        self.assertEqual(int([line for line in self.dock.lines[:i + 2] if " slots " in line][-1].split()[2]), wide)
        j, m = self.wait_line(self.dock, r"^(\d+) move-end ", start=i)
        took = int(m.group(1)) - removed
        self.assertTrue(150 <= took <= 700, f"posun pri odebrani {took} ms")
        k, m = self.wait_line(self.dock, r" slots (\d+) ", start=j)
        self.assertLess(int(m.group(1)), wide)
        self.assertNotIn("LSL", "\n".join(self.dock.lines))

    def test_letter_icon_fallback(self):
        """Aplikace bez ikony (bez .desktop, nebo s Icon=, ktera v tematu neni): neutralni ctverec s prvnim
        pismenem nazvu, ne obecna ikona programu (ozubene kolo)."""
        (self.apps / "test-noicon.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Quux\nExec=true\nIcon=luxos-no-such-icon\nStartupWMClass=cz.test.noicon\n")
        self.conf(items=["test-alpha.desktop", "trash"])
        self.start_dock()
        n = len(self.dock.lines)
        self.run_window("noicon")
        self.run_window("nodesk")
        _, m = self.wait_line(self.dock, r"^\d+ items (\S+ trash \S+ \S+)$", start=n)
        self.assertEqual([Path(k).name for k in m.group(1).split()][0], "test-alpha.desktop")
        time.sleep(0.8)
        centers = self.slots()
        w, h, buf = self.shot("letter-icons", y0=H - 170)
        for slot in (2, 3):
            box = [px(buf, w, centers[slot] + dx, h - 34 + dy) for dx in range(-18, 19) for dy in range(-18, 19)]
            plate = [c for c in box if max(c) - min(c) <= 8 and 190 <= c[0] <= 250]
            ink = [c for c in box if max(c) < 110 and max(c) - min(c) <= 16]
            print(f"\n  slot {slot}: plate {len(plate)}/{len(box)} px, letter {len(ink)} px")
            self.assertGreater(len(plate), len(box) // 3, f"slot {slot}: no neutral plate")
            self.assertGreater(len(ink), 15, f"slot {slot}: no letter")

    def test_reorder_persists(self):
        self.conf()
        self.start_dock()
        a, c = self.centers[0], self.centers[2]
        n = len(self.dock.lines)
        self.input(f"move {a} {H - 30}", "sleep 0.4", f"drag {a} {H - 30} {c + 10} {H - 30} 900", "sleep 0.3",
                   f"move {W // 2} 200")
        self.wait_line(self.dock, r" drag .*test-alpha", start=n)
        _, m = self.wait_line(self.dock, r" order (.*)$", start=n)
        order = m.group(1).split()
        self.assertEqual(order[:3], ["test-beta.desktop", "test-gamma.desktop", "test-alpha.desktop"])
        text = (self.cfg / "luxos/dock.conf").read_text()
        self.assertIn('ITEMS="' + " ".join(order) + '"', text)
        self.stop_dock()
        self.start_dock()
        self.assertEqual(self.items_line()[:3], ["test-beta.desktop", "test-gamma.desktop", "test-alpha.desktop"])

    def test_migrate_from_plank(self):
        launchers = self.cfg / "plank/dock1/launchers"
        launchers.mkdir(parents=True)
        for a in ("alpha", "beta", "gamma"):
            (launchers / f"test-{a}.dockitem").write_text(
                f"[PlankDockItemPreferences]\nLauncher=file://{self.apps}/test-{a}.desktop\n")
        (launchers / "trash.dockitem").write_text("[PlankDockItemPreferences]\nLauncher=docklet://trash\n")
        (launchers / "missing.dockitem").write_text(
            "[PlankDockItemPreferences]\nLauncher=file:///opt/none/missing.desktop\n")
        # dconf jako v relaci X11: poradi dock-items, zvetseni a skryvani uzivatele
        fake = self.home / "bin"
        fake.mkdir()
        (fake / "dconf").write_text(
            "#!/bin/sh\ncase $2 in\n"
            "*dock-items) echo \"['test-gamma.dockitem', 'trash.dockitem', 'test-alpha.dockitem']\" ;;\n"
            "*zoom-percent) echo 170 ;;\n*hide-mode) echo \"'auto'\" ;;\nesac\n")
        (fake / "dconf").chmod(0o755)
        self.start_dock(PATH=f"{fake}:{self.env['PATH']}")
        text = (self.cfg / "luxos/dock.conf").read_text()
        self.assertIn('ITEMS="test-gamma.desktop trash test-alpha.desktop /opt/none/missing.desktop '
                      'test-beta.desktop"', text)
        self.assertIn("ZOOM=170", text)
        self.assertIn("HIDE=autohide", text)
        self.assertEqual(self.items_line(), ["test-gamma.desktop", "trash", "test-alpha.desktop", "test-beta.desktop"])

    def test_indicators_light_dark(self):
        """Tecka bezici aplikace jako Plank na X11 (modra zarici tecka na spodnim okraji panelu) na svetlem i tmavem
        skle (snimky out/dock-test/shots/indicator-*.png)."""
        light = self.home / "light.png"
        dark = self.home / "dark.png"
        png(light, 64, 40, lambda x, y: (232, 236, 244 - y))
        png(dark, 64, 40, lambda x, y: (18 + y // 4, 22, 38))
        self.conf(items=["test-alpha.desktop", "test-beta.desktop", "trash"])
        self.run_window("alpha")
        results = {}

        def blue(p):
            return p[2] - max(p[0], p[1])

        for mode, wall in (("light", light), ("dark", dark)):
            (self.cfg / "luxos/appearance.conf").write_text(f"WALLPAPER={wall}\n")
            (self.cfg / "luxos/appearance").write_text(mode + "\n")
            self.start_dock()
            self.mouse(W // 2, 200)
            time.sleep(0.8)
            self.shot(f"indicator-{mode}")
            w, h, buf = self.shot(y0=H - 40)
            # stred tecky na spodnim okraji panelu, jadro (barva #0860f2) do 1,2 px od stredu
            def spot(x):
                return max((px(buf, w, x + dx, h - MARGIN - 2) for dx in (-1, 0, 1)), key=blue)
            glass = px(buf, w, self.centers[0] + 30, h - MARGIN - 4)
            dot_running = spot(self.centers[0])
            dot_pinned = spot(self.centers[1])
            # zare nad jadrem slabne: 4 px nad okrajem uz jen nadech modre
            halo = px(buf, w, self.centers[0], h - MARGIN - 5)
            results[mode] = {"glass": glass, "running": dot_running, "pinned_only": dot_pinned, "halo": halo}
            self.assertGreater(blue(dot_running), 100, results)
            self.assertLess(dot_running[0], 80, results)
            self.assertLess(abs(dot_running[1] - 96), 40, results)
            self.assertLess(blue(dot_pinned), blue(glass) + 15, results)
            self.assertLess(blue(halo), 110, results)
            if mode == "light":
                self.assertGreater(lum(glass), 150, results)
            else:
                self.assertLess(lum(glass), 110, results)
            self.stop_dock()
        record("indicators", results)

    def test_input_region(self):
        """Kliknuti nad Dockem (do mista pro zvetseni) jde oknu pod nim, kliknuti na Dock ne."""
        self.conf()
        client = self.spawn(["wlt-client", "--size", f"{W - 80}x{H - 60}", "--events", "--app-id", "cz.test.under"],
                            dict(self.env, PATH=self.env["PATH"]))
        self.wait_line(client, r"configure")
        self.start_dock()
        x = self.centers[3]
        n = len(client.lines)
        self.input(f"move {x} {H - 110}", "click")
        self.wait_line(client, r"button", start=n, timeout=3)
        n = len(client.lines)
        self.input(f"move {x} {H - 30}", "sleep 0.3", "click right", "sleep 0.3", "key Escape", "sleep 0.3",
                   f"move {x} 300")
        self.pump(client, 0.8)
        self.assertFalse(any("button" in line for line in client.lines[n:]), client.lines[n:])

    def test_autohide(self):
        self.conf(hide="autohide")
        self.start_dock()
        self.mouse(W // 2, 200)
        time.sleep(0.8)
        self.assertEqual(self.height(), 0, "autohide dock visible at start")
        self.glide([(W // 2, 200), (W // 2, H - 1)], step=40)
        h = self.wait_height(lambda v: v > 40, 1.5)
        self.assertGreater(h, 40, "dock did not appear at the bottom edge")
        self.mouse(W // 2, 200)
        self.assertEqual(self.wait_height(lambda v: v == 0, 1.5), 0, "dock did not hide again")

    def test_dodge_maximized(self):
        """Mimo autohide Dock vyhradi misto (exkluzivni zona): maximalizovane okno konci nad nim, Dock neuhyba"""
        self.conf(hide="dodge")
        self.start_dock()
        self.mouse(W // 2, 200)
        dock_h = self.wait_height(lambda v: v > 40)
        n = len(self.dock.lines)
        self.spawn([str(self.bin / "luxos-wl-window"), "cz.test.alpha", "Window alpha", "--maximize"])
        self.pump(self.dock, 1.5)
        self.assertFalse(any("hide-end 1.0" in ln for ln in self.dock.lines[n:]), "dock hid for a maximized window")
        w, h, buf = self.shot(y0=H - 170, name="dodge-maximized-zone")
        above = {px(buf, w, x, h - dock_h - 4) for x in range(W // 2 - 100, W // 2 + 100, 7)}
        under = {px(buf, w, x, h - 4) for x in range(W // 2 - 100, W // 2 + 100, 7)}
        self.assertEqual(above, {WINDOW}, "maximized window above the dock")
        self.assertNotIn(WINDOW, under, "maximized window reaches under the dock")
        self.assertGreater(self.height(), 40)

    def test_badge_dbus(self):
        """com.canonical.Unity.LauncherEntry na soukrome sbernici: cislo a prubeh, po konci odesilatele pryc."""
        bus = self.spawn(["dbus-daemon", "--session", "--nofork", "--print-address=1"])
        _, m = self.wait_line(bus, r"^unix:\S+")
        address = m.group(0)
        self.env["DBUS_SESSION_BUS_ADDRESS"] = address
        self.conf(items=["test-alpha.desktop", "test-beta.desktop", "trash"])
        self.start_dock()
        self.mouse(W // 2, 200)
        time.sleep(0.4)
        before = self.shot(y0=H - 100)
        emitter = self.spawn(["python3", "-c", EMIT_PY, "application://test-alpha.desktop"],
                             dict(self.env, DBUS_SESSION_BUS_ADDRESS=address))
        self.wait_line(emitter, r"^sent")
        self.wait_line(self.dock, r" entry test-alpha.desktop 7 True")
        time.sleep(0.4)
        w, h, buf = self.shot("badge", y0=H - 100)
        red = [(x, y) for y in range(h) for x in range(self.centers[0] - 10, self.centers[0] + 40)
               if (c := px(buf, w, x, y))[0] > 200 and c[1] < 110 and c[2] < 110]
        self.assertGreater(len(red), 40, "no badge")
        accent = [(x, y) for y in range(h) for x in range(self.centers[0] - 24, self.centers[0] + 24)
                  if (c := px(buf, w, x, y))[2] > 200 and c[0] < 110]
        self.assertGreater(len(accent), 20, "no progress bar")
        self.assertEqual(px(buf, w, self.centers[1] + 20, h - 60), px(before[2], w, self.centers[1] + 20, h - 60))
        emitter.terminate()
        emitter.wait(5)
        time.sleep(0.6)
        w, h, buf = self.shot(y0=H - 100)
        red = [1 for y in range(h) for x in range(self.centers[0] - 10, self.centers[0] + 40)
               if (c := px(buf, w, x, y))[0] > 200 and c[1] < 110 and c[2] < 110]
        self.assertLess(len(red), 5, "badge stayed after the sender quit")
        record("badge_red_px", len(red))

    def test_flicker_during_zoom(self):
        self.conf()
        self.start_dock()
        cx = W // 2
        self.mouse(cx, 200)
        frames = self.s / "frames"
        cap = subprocess.Popen([str(WLT), "capture", str(self.s), str(frames), "20", "4"], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, env=self.outer())
        time.sleep(0.3)
        for _ in range(2):
            self.glide([(cx, 200), (cx - 220, H - 8)], step=30, delay=0.01)
            time.sleep(0.4)
            self.glide([(cx - 220, H - 8), (cx + 220, H - 8)], step=6, delay=0.01)
            time.sleep(0.4)
            self.glide([(cx + 220, H - 8), (cx + 220, 200)], step=30, delay=0.01)
            time.sleep(0.4)
        cap.wait(30)
        r = subprocess.run([str(WLT), "check", str(frames)], capture_output=True, text=True)
        record("flicker_check", r.stdout.strip().splitlines()[-3:])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_idle_memory_and_wakeups(self):
        self.conf()
        self.run_window("alpha")
        dock = self.start_dock()
        self.mouse(W // 2, 200)
        time.sleep(3)
        pid = dock.pid

        def status():
            d = {}
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                k, _, v = line.partition(":")
                d[k] = v.strip()
            return d
        pss = int(re.search(r"Pss:\s+(\d+)", Path(f"/proc/{pid}/smaps_rollup").read_text()).group(1))
        s0 = status()
        t0 = time.monotonic()
        time.sleep(IDLE_SECONDS)
        s1 = status()
        seconds = time.monotonic() - t0
        wake = (int(s1["voluntary_ctxt_switches"]) - int(s0["voluntary_ctxt_switches"])
                + int(s1["nonvoluntary_ctxt_switches"]) - int(s0["nonvoluntary_ctxt_switches"]))
        pss1 = int(re.search(r"Pss:\s+(\d+)", Path(f"/proc/{pid}/smaps_rollup").read_text()).group(1))
        record("idle", {"seconds": round(seconds, 1), "wakeups": wake, "pss_kb_start": pss, "pss_kb_end": pss1,
                        "threads": s1["Threads"]})
        self.assertLessEqual(wake, 10, "dock wakes up while idle")
        self.assertLess(pss1, 40 * 1024)


@unittest.skipUnless((LUXWM_BUILD / "luxwm").exists(), "chybi luxwm (packages/luxwm/tests/build-host.sh, LUXWM_BUILD)")
class DockLuxwm(DockBase):
    """Dock pod luxwm: hlasi svou vysku (dock_zone), nova okna lezi nad nim, uhyba kazdemu zamerenemu oknu,
    ktere ho prekryva (ram z udalosti window), jako window-dodge Planku na X11."""

    def compositor(self):
        conf = OUT / "luxwm-dock.conf"
        lines = [ln for ln in (REPO / "packages/luxwm/luxwm.conf").read_text().splitlines()
                 if not ln.startswith("displays_command")]
        conf.write_text("xwayland = no\n" + "\n".join(lines) + "\n")
        # allowlist: nastroje harnessu (wlt) a Dock (seznam oken, tema window, dock_zone)
        os.environ["WLT_PRIVILEGED"] = str(self.bin / "luxos-dock")
        os.environ["WLT_COMPOSITOR_ENV"] = (f"LUXCOMP_VIRTUAL_INPUT=1 LUXWM_TRACE=1 LUXWM_SYSTEM_CONFIG={conf} "
                                            f"LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib")
        return ["--", str(LUXWM_BUILD / "luxwm")]

    def tearDown(self):
        os.environ.pop("WLT_COMPOSITOR_ENV", None)
        os.environ.pop("WLT_PRIVILEGED", None)
        super().tearDown()

    def test_ctrl_click_opens_window_and_two_indicators(self):
        self.conf(items=["test-alpha.desktop", "trash"])
        self.start_dock()
        x = self.centers[0]
        self.input(f"move {x} {H - 30}", "click")
        self.wait_line(self.dock, r" window (\d+) cz\.test\.alpha ")
        n = len(self.dock.lines)
        self.input("keydown ctrl", "sleep 0.1", "click", "keyup ctrl")
        self.wait_line(self.dock, r" launch .*test-alpha.desktop", start=n)
        self.wait_line(self.dock, r" window (\d+) cz\.test\.alpha ", start=n)
        self.mouse(W // 2, 200)
        time.sleep(0.5)
        w, h, buf = self.shot(y0=H - 40)
        def blue(dx):
            color = px(buf, w, x + dx, h - MARGIN - 2)
            return color[2] - max(color[0], color[1])
        # Dve oddelene modre spicky pod stejnou ikonou, bez treti ve stredu.
        left = max(blue(dx) for dx in range(-9, -4))
        right = max(blue(dx) for dx in range(5, 10))
        middle = blue(0)
        self.assertGreater(left, 55, (left, middle, right))
        self.assertGreater(right, 55, (left, middle, right))
        self.assertLess(middle, min(left, right), (left, middle, right))

    def test_click_opens_window_from_another_workspace(self):
        """Aplikace otevrena na jine plose: klik na jeji ikonu v Docku prepne na tu plochu a okno zamerime
        (neotevrelo se nic)."""
        self.conf(items=["test-alpha.desktop", "trash"])
        self.start_dock()
        x = self.centers[0]
        self.input(f"move {x} {H - 30}", "click")
        self.wait_line(self.dock, r" window (\d+) cz\.test\.alpha ")
        self.mouse(W // 2, 200)
        time.sleep(0.5)
        self.input("key ctrl+super+2")
        time.sleep(1.2)
        self.pump(self.dock, 0.3)
        n = len(self.dock.lines)
        self.input(f"move {x} {H - 30}", "sleep 0.3", "click")
        self.pump(self.dock, 1.0)
        out = "\n".join(self.dock.lines[n:])
        self.assertNotIn("launch", out, "the click started another instance instead of showing the window")
        self.assertIn("activate", out, out)
        log = (self.s / "compositor.log").read_text() if (self.s / "compositor.log").exists() else ""
        self.assertIn("workspace 1", log.split("workspace 2")[-1], "switched back to the workspace of the window")

    def test_zone_placement_and_dodge_overlap(self):
        self.conf(hide="dodge")
        self.start_dock()
        _, m = self.wait_line(self.dock, r" zone HEADLESS-1 (\d+)")
        zone = int(m.group(1))
        self.assertGreater(zone, 40)
        self.mouse(W // 2, 100)
        # vysoke okno se zmensi a lezi cele nad Dockem: Dock zustava videt
        n = len(self.dock.lines)
        client = self.spawn(["wlt-client", "--size", "500x790", "--events", "--app-id", "cz.test.tall"])
        # plocha pro okna = nad Dockem s okrajem 8 px nahore i dole, zahlavi ciziho okna 30 px
        self.wait_line(client, r"configure 500 %d" % (H - zone - 2 * 8 - 30))
        self.pump(self.dock, 1.0)
        self.assertFalse(any("hide-end 1.0" in ln for ln in self.dock.lines[n:]), "dock hid for a window above it")
        self.assertGreater(self.height(), 40)
        self.shot("luxwm-tall-window-above-dock")
        # okno stazene pres Dock: Dock uhne, zpet nahoru: Dock se vrati
        n = len(self.dock.lines)
        self.input(f"move {W // 2} 16", "down", *self.glide_cmds([(W // 2, 16), (W // 2, 316)], 20, 0.01), "up",
                   f"move {W // 2 + 300} 200")
        self.wait_line(self.dock, r"hide-end 1\.0", start=n)
        n = len(self.dock.lines)
        self.input(f"move {W // 2} 316", "down", *self.glide_cmds([(W // 2, 316), (W // 2, 16)], 20, 0.01), "up",
                   f"move {W // 2 + 300} 200")
        self.wait_line(self.dock, r"hide-end 0\.0", start=n)
        # bez zamereneho okna Dock videt (okno zavrene)
        client.terminate()
        client.wait(5)
        self.assertGreater(self.wait_height(lambda v: v > 40, 2.0), 40)

    def test_autohide_over_window_shows_material(self):
        """Vysunuty Dock nad oknem pod luxwm: material Docku (tonovani pres rozmazane okno jako Dock macOS),
        ne sklo z tapety; nepruhledny podklad jen bez rozmazani v kompozitoru (labwc, X11)"""
        tokens = (REPO / "packages/luxos-desktop/files/lsl/luxos_tokens.lsl").read_text()
        m = re.search(r'"thin": \{\s*"light": \{"tint": \[(\d+), (\d+), (\d+)\], "opacity": ([\d.]+)', tokens)
        tint, alpha = [int(v) for v in m.groups()[:3]], float(m.group(4))
        self.conf(hide="autohide")
        self.start_dock()
        self.mouse(W // 2, 100)
        panels = {}
        for color in ("000000", "ffffff"):
            n = len(self.dock.lines)
            client = self.spawn(["wlt-client", "--solid", "--color", color, "--size", "1200x790", "--app-id",
                                 "cz.test.cover" + color])
            self.wait_line(self.dock, r"over-window 1", start=n)
            self.glide([(W // 2, 100), (W // 2, H - 1)], step=40)
            time.sleep(1.0)
            w, h, buf = self.shot(y0=H - 170, name="autohide-over-" + color)
            # height() porovnava s tapetou, okno ji tu zakryva: horni hrana panelu = prvni rada, kde v useku
            # vlevo od zvetsenych ikon neni barva okna; podklad = nejcastejsi barva kousek pod ni (nad ikonami)
            window = tuple(bytes.fromhex(color))
            xs = range(W // 4, W // 2 - 100)
            top = next(y for y in range(h) if all(differs(px(buf, w, x, y), window, 3) for x in xs))
            self.assertLess(top, h - 40, "Dock not shown")
            colors = [px(buf, w, x, top + 8) for x in xs]
            panels[color] = max(set(colors), key=colors.count)
            client.terminate()
            client.wait(5)
            self.mouse(W // 2, 100)
            self.wait_height(lambda v: v == 0, 1.5)
        print(f"\n  panel over black {panels['000000']}, over white {panels['ffffff']}")
        for color, under in (("000000", 0), ("ffffff", 255)):
            want = [round(t * alpha + under * (1 - alpha)) for t in tint]
            for got, exp in zip(panels[color], want):
                self.assertLessEqual(abs(got - exp), 10, (color, panels[color], want))


    def cover_dock(self):
        """Pruhovane okno (pripnuta aplikace alpha) stazene az za Dock: sklo (rozmazane pruhy) je pak videt i mimo
        panel."""
        _, m = self.wait_line(self.dock, r" zone HEADLESS-1 (\d+)")
        zone = int(m.group(1))
        client = self.spawn(["wlt-client", "--events", "--size", f"{W - 40}x{H - zone - 2 * 8 - 30}", "--app-id", "cz.test.alpha"])
        self.wait_line(client, r"configure")
        time.sleep(0.3)
        self.input(f"move {W // 2} 20", "down", *self.glide_cmds([(W // 2, 20), (W // 2, 220)], 20, 0.01), "up",
                   f"move {W // 2} 100")
        time.sleep(0.5)
        return zone

    def test_zoom_glass_stays_panel(self):
        """Zvetseni jako Plank: ikony vystoupi nad panel, sklo (material kompozitoru pod vstupni oblasti) zustane
        jen panel - nad panelem vedle zvetsenych ikon se nic nezmeni (drive se cele sklo zvedlo s ikonou)."""
        self.conf()
        self.start_dock()
        zone = self.cover_dock()
        rest = self.shot("zoom-glass-rest")
        x = self.centers[0]
        self.glide([(W // 2, 100), (x, H - 30)], step=12)
        time.sleep(0.8)
        hover = self.shot("zoom-glass-hover")
        w, h = rest[0], rest[1]
        panel_top = h - zone
        size = (self.centers[1] - self.centers[0]) * 24 // 31
        # zvetsene ikony u leve strany siri nez 3 sloty; vpravo od nich nad panelem musi zustat okno
        xs = range(self.centers[0] + 3 * (self.centers[1] - self.centers[0]), self.centers[-1] + size // 2, 3)
        changed = [(xx, y) for y in range(panel_top - size // 2 + 2, panel_top - 1) for xx in xs
                   if differs(px(hover[2], w, xx, y), px(rest[2], w, xx, y), 6)]
        self.assertEqual(changed[:10], [], f"glass rose above the panel at {len(changed)} px")
        # a zvetsena ikona opravdu vycniva nad panel (jinak by test nic nemeril)
        icon = [1 for y in range(panel_top - size // 2, panel_top - 2) for xx in range(x - 10, x + 10)
                if differs(px(hover[2], w, xx, y), px(rest[2], w, xx, y), 20)]
        self.assertGreater(len(icon), 50, "no magnified icon above the panel")

    def test_label_leaves_no_remnant(self):
        """Popisek krajni ikony je sirsi nez Dock: po odchodu mysi z nej nesmi zustat zamrzly zbytek
        (prekreslovala se jen sirka Docku, popisek mimo ni zustal v bufferu)."""
        name = "Monitor systemu s velmi dlouhym nazvem"
        (self.apps / "test-long.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=" + name + "\nExec=true\nIcon=utilities-terminal\n")
        self.conf(items=["test-alpha.desktop", "test-beta.desktop", "test-long.desktop"])
        self.start_dock()
        self.cover_dock()
        rest = self.shot("label-rest")
        for x, away in ((self.centers[-1], W - 5), (self.centers[0], 5)):
            self.glide([(W // 2, 100), (x, H - 30)], step=12)
            time.sleep(0.6)
            hover = self.shot()
            w, h = hover[0], hover[1]
            label = [(xx, y) for y in range(h - 160, h - 60) for xx in range(0, W, 2)
                     if differs(px(hover[2], w, xx, y), px(rest[2], w, xx, y), 20)]
            self.assertGreater(len(label), 100, "no label")
            self.glide([(x, H - 30), (away, H - 30), (away, 300)], step=30, delay=0.002)
            time.sleep(1.0)
            after = self.shot("label-away-" + ("right" if away > 100 else "left"))
            left = [(xx, y) for (xx, y) in label if differs(px(after[2], w, xx, y), px(rest[2], w, xx, y), 6)]
            self.assertEqual(left[:10], [], f"label remnant: {len(left)} px")


EMIT_PY = r'''
import sys
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION)
bus.emit_signal(None, "/cz/luxos/test", "com.canonical.Unity.LauncherEntry", "Update",
                GLib.Variant("(sa{sv})", (sys.argv[1], {"count": GLib.Variant("x", 7),
                                                       "count-visible": GLib.Variant("b", True),
                                                       "progress": GLib.Variant("d", 0.5),
                                                       "progress-visible": GLib.Variant("b", True)})))
bus.flush_sync(None)
print("sent", flush=True)
GLib.MainLoop().run()
'''

if __name__ == "__main__":
    unittest.main()
