#!/usr/bin/env python3
"""luxos_wl.lsl + libluxos-wl a luxos_layer.lsl proti skutecnemu kompozitoru: labwc a luxwm headless (pixman).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_wl.py -v

Kazdy test ma vlastni kompozitor (WLR_BACKENDS=headless, jeden vystup 1280x720) se soukromym
XDG_RUNTIME_DIR a skutecne klienty: okna GTK 3 v LSL (tests/lsl/luxos-wl-window.lsl), scenare protokolu
(tests/lsl/luxos-wl-test.lsl) a listu na vrstve (tests/lsl/luxos-layer-test.lsl). Nic nebezi na
skutecne obrazovce: DISPLAY, WAYLAND_DISPLAY a sbernice relace se klientum nepredavaji.

labwc: LUXOS_WL_SYSROOT (adresar s usr/bin/labwc a usr/lib, napr. sysroot z scripts/wl-test/fetch-sysroot.sh
baliku WP-1, vychozi out/wl-test/sysroot), jinak labwc z PATH; bez nej se test preskoci.
luxwm: LUXWM_BUILD (vychozi out/luxwm-test/build z packages/luxwm/tests/build-host.sh, luxwm a libluxcomp.so.0);
privilegovane protokoly dostanou jen testovaci klienti a grim (allowlist LUXWM_PRIVILEGED).
LUXOS_LSLC: prekladac lslc (jinak lslc z PATH).
"""
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
REPO = PKG.parent.parent
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
SYSROOT = Path(os.environ.get("LUXOS_WL_SYSROOT") or REPO / "out" / "wl-test" / "sysroot")
LABWC = SYSROOT / "usr/bin/labwc" if (SYSROOT / "usr/bin/labwc").exists() else shutil.which("labwc")
GRIM = SYSROOT / "usr/bin/grim" if (SYSROOT / "usr/bin/grim").exists() else shutil.which("grim")
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out" / "luxwm-test" / "build")
LUXWM = LUXWM_BUILD / "luxwm" if (LUXWM_BUILD / "luxwm").exists() else None
TOOLS = all(shutil.which(t) for t in ("make", "gcc", "wayland-scanner", "pkg-config"))

RC_XML = """<?xml version="1.0"?>
<labwc_config>
  <core><gap>0</gap></core>
  <placement><policy>center</policy></placement>
  <theme><dropShadows>no</dropShadows></theme>
</labwc_config>
"""
WINDOW = "3a6ea5"     # vychozi barva testovaciho okna
LOCK = "193399"       # zamykaci plocha (0.1, 0.2, 0.6)


def lines(text, prefix):
    return [line[len(prefix):] for line in text.splitlines() if line.startswith(prefix)]


class WaylandShell:
    """Testy spolecne pro oba kompozitory; potomek urci compositor_cmd()."""
    name = "?"

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="luxos-wl-"))
        r = subprocess.run(["make", "-s", "-C", str(PKG / "files/src/luxos-wl"), f"OUT={cls.tmp}"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("libluxos-wl: " + r.stdout + r.stderr)
        cls.lib = cls.tmp / "libluxos-wl.so.0"
        src = cls.tmp / "lsl"
        src.mkdir()
        for f in (PKG / "files/lsl").glob("*.lsl"):
            shutil.copy(f, src)
        for name in ("luxos-wl-test", "luxos-wl-window", "luxos-layer-test"):
            shutil.copy(HERE / "lsl" / f"{name}.lsl", src)
            r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(src), str(src / f"{name}.lsl"), str(cls.tmp / name)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"{name}: " + r.stdout + r.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.session = Path(tempfile.mkdtemp(prefix="sess-", dir=self.tmp))
        run = self.session / "run"
        run.mkdir(mode=0o700)
        (self.session / "home").mkdir()
        (self.session / "config/labwc").mkdir(parents=True)
        (self.session / "config/labwc/rc.xml").write_text(RC_XML)
        self.env = {
            "HOME": str(self.session / "home"), "XDG_RUNTIME_DIR": str(run), "LANG": "C.UTF-8",
            "PATH": "/usr/bin:/bin", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent",
            "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent",
        }
        comp_env = dict(self.env, XDG_CONFIG_HOME=str(self.session / "config"), WLR_BACKENDS="headless",
                        WLR_RENDERER="pixman", WLR_LIBINPUT_NO_DEVICES="1", WLR_HEADLESS_OUTPUTS="1",
                        WLR_DRM_DEVICES="/nonexistent")
        command = self.compositor_cmd(comp_env)
        cmd = ["env", "-i"] + [f"{k}={v}" for k, v in comp_env.items()] + ["timeout", "300"] + command
        if shutil.which("systemd-run") and os.environ.get("XDG_RUNTIME_DIR"):
            # scope s limitem procesu; systemd-run --scope prikaz spusti primo (PID = env -> timeout)
            cmd = ["systemd-run", "--user", "--scope", "-q", "-p", "TasksMax=300", "--"] + cmd
        outer = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY")}
        self.log = open(self.session / "compositor.log", "w")
        self.procs = []
        self.compositor = subprocess.Popen(cmd, env=outer, stdout=self.log, stderr=subprocess.STDOUT)
        socket = run / "wayland-0"
        for _ in range(100):
            if socket.exists():
                break
            time.sleep(0.05)
        else:
            self.fail(f"{self.name} nevytvoril soket: " + (self.session / "compositor.log").read_text())
        self.env.update(WAYLAND_DISPLAY="wayland-0", GDK_BACKEND="wayland", LUXOS_WL_LIB=str(self.lib),
                        NO_AT_BRIDGE="1")

    def tearDown(self):
        for p in self.procs + [self.compositor]:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        self.log.close()
        for p in self.procs:
            if p.stdout:
                p.stdout.close()

    def assertAlive(self):
        self.assertIsNone(self.compositor.poll(), f"{self.name} skoncil: " +
                          (self.session / "compositor.log").read_text()[-2000:])

    # ---- klienti ----

    def run_client(self, name, *args, timeout=20, env=None):
        r = subprocess.run([str(self.tmp / name), *args], env=env or self.env, capture_output=True, text=True,
                           timeout=timeout)
        return r

    def spawn(self, name, *args, env=None):
        p = subprocess.Popen([str(self.tmp / name), *args], env=env or self.env, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL)
        p.seen = b""
        self.procs.append(p)
        return p

    def wait_line(self, proc, text, timeout=10):
        """Ceka na radek vystupu klienta; vraci vsechny dosavadni radky."""
        deadline = time.monotonic() + timeout
        fd = proc.stdout.fileno()
        while text not in proc.seen.decode(errors="replace").splitlines():
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                self.fail(f"{text!r} se neobjevilo: {proc.seen.decode(errors='replace')}")
            chunk = os.read(fd, 65536)
            if not chunk:
                self.fail(f"{text!r} se neobjevilo, klient skoncil: {proc.seen.decode(errors='replace')}")
            proc.seen += chunk
        return proc.seen.decode(errors="replace").splitlines()

    def window(self, app_id, title, *extra):
        p = self.spawn("luxos-wl-window", app_id, title, *extra)
        self.wait_line(p, "shown")
        time.sleep(0.2)   # snimek kompozitoru po commitu prvniho buferu
        return p

    def scenario(self, *args, timeout=20):
        r = self.run_client("luxos-wl-test", *args, timeout=timeout)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("LSL callback error", r.stderr)
        return r.stdout

    def screenshot(self):
        """Snimek nezavislym klientem (grim): [sirka, vyska, pixel(x, y) -> 'rrggbb']."""
        path = self.session / "shot.ppm"
        env = dict(self.env)
        if str(GRIM).startswith(str(SYSROOT)):
            env["LD_LIBRARY_PATH"] = str(SYSROOT / "usr/lib")
        subprocess.run([str(GRIM), "-t", "ppm", str(path)], env=env, check=True, timeout=10)
        data = path.read_bytes()
        magic, size, depth, pixels = data.split(b"\n", 3)
        width, height = map(int, size.split())
        return width, height, lambda x, y: pixels[(y * width + x) * 3:(y * width + x) * 3 + 3].hex()

    # ---- testy ----

    def test_toplevels_list_activate_minimize_close(self):
        one = self.window("luxos.test.one", "Okno jedna")
        self.window("luxos.test.two", "Okno dva", "#20a040")
        out = self.scenario("toplevels", "luxos.test.one", "luxos.test.two")
        wlr = sorted(line.rsplit("|", 1)[0] for line in lines(out, "wlr "))
        self.assertEqual(wlr, ["luxos.test.one|Okno jedna", "luxos.test.two|Okno dva"])
        self.assertEqual(sorted(lines(out, "ext ")), ["luxos.test.one|Okno jedna|True", "luxos.test.two|Okno dva|True"])
        target = lines(out, "activated ")
        other = lines(out, "minimized ")
        self.assertEqual(len(target), 1)
        self.assertEqual(len(other), 1)
        self.assertNotEqual(target, other)
        self.assertEqual(lines(out, "closed "), target)
        self.assertEqual(lines(out, "remaining "), ["1"])
        # zavrene okno skutecne skoncilo (GTK dostal close a znicil okno)
        closed = one if target == ["luxos.test.one"] else self.procs[1]
        self.assertEqual(closed.wait(5), 0)
        self.assertAlive()

    def test_lock_and_unlock(self):
        self.window("luxos.test.desk", "Plocha")
        _, _, pixel = self.screenshot()
        self.assertEqual(pixel(640, 360), WINDOW)
        out = self.scenario("lock")
        self.assertIn("locked", out.splitlines())
        self.assertEqual(lines(out, "configure "), ["1280x720"])
        # pod zamkem je videt jen zamykaci plocha, po odemceni zase okno
        self.assertEqual(lines(out, "pixel "), [LOCK, WINDOW])
        self.assertEqual(lines(out, "unlock "), ["True"])
        # heslo: klavesy virtualni klavesnice prisly na zamykaci plochu jako keysym + znak (a, e s hackem)
        self.assertEqual(lines(out, "key "), ["97 97", "492 283"])
        _, _, pixel = self.screenshot()
        self.assertEqual(pixel(640, 360), WINDOW)
        self.assertAlive()

    def test_lock_stays_when_locker_dies(self):
        self.window("luxos.test.desk", "Plocha")
        out = self.scenario("lock-abandon")
        self.assertIn("locked", out.splitlines())
        self.assertIn("abandon", out.splitlines())
        time.sleep(0.3)
        _, _, pixel = self.screenshot()
        # zamykac skoncil bez odemceni: plocha zustava skryta
        self.assertNotEqual(pixel(640, 360), WINDOW)
        self.assertAlive()

    def test_capture_output_and_window(self):
        self.window("luxos.test.shot", "Snimek")
        png = self.session / "capture.png"
        out = self.scenario("capture", str(png))
        self.assertEqual(lines(out, "output "), ["HEADLESS-1 [0, 0, 1280, 720]"])
        self.assertTrue(lines(out, "capture ")[0].startswith("1280x720 format "))
        self.assertEqual(lines(out, "png "), ["True"])
        self.assertEqual(lines(out, "center "), [WINDOW])
        data = png.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual((int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")), (1280, 720))
        # snimek samotneho okna (ext-foreign-toplevel-image-capture-source)
        shot = lines(out, "toplevel-capture ")
        self.assertEqual(len(shot), 1)
        if shot[0] != "unsupported":
            size, color = shot[0].split()
            self.assertEqual(color, WINDOW)
            width, height = map(int, size.split("x"))
            self.assertGreaterEqual(width, 300)
            self.assertGreaterEqual(height, 150)

    def test_clipboard_roundtrip(self):
        text = "Ahoj ěščř 😀"
        out = self.scenario("clip-roundtrip", text)
        data = sorted(lines(out, "data "))
        self.assertEqual(data, [f"{len(text.encode())} 0 {text}", f"{len(text.encode()) + 10} 0 {text} (primary)"])
        types = lines(out, "changed primary=0 text=1 types=")
        self.assertIn("text/plain;charset=utf-8", types[0].split(","))

    def test_clipboard_between_clients(self):
        holder = self.spawn("luxos-wl-test", "clip-set", "z jineho klienta ✓")
        self.wait_line(holder, "set True")
        out = self.scenario("clip-get")
        self.assertIn(f"data {len('z jineho klienta ✓'.encode())} 0 z jineho klienta ✓", out.splitlines())
        # novy vyber jineho klienta zrusi ten nas (cancelled) a drzitel skonci
        self.scenario("clip-roundtrip", "novy")
        self.wait_line(holder, "cancelled primary=0")
        self.assertEqual(holder.wait(5), 0)

    def test_clipboard_empty(self):
        out = self.run_client("luxos-wl-test", "clip-get")
        self.assertEqual(out.returncode, 1)
        self.assertIn("no-text", out.stdout)

    def test_virtual_keyboard_types_unicode(self):
        # headless seat nema klavesnici; prvni klavesnice az po fokusu okna by GTK nedostal (enter
        # chodi jen s klavesnici) - na skutecnem stroji klavesnice existuje driv nez okna
        holder = self.spawn("luxos-wl-test", "keyboard")
        self.wait_line(holder, "keyboard True")
        entry = self.window("luxos.test.entry", "Psani", "--entry")
        text = "Ahoj 😀 ěšé"
        self.scenario("type", text)
        self.wait_line(entry, "text: " + text)

    def test_output_management(self):
        out = self.scenario("heads")
        heads = lines(out, "head ")
        self.assertEqual(heads[0], "HEADLESS-1 Headless output 1 True 0 0 1280 720 0 1000 0")
        self.assertEqual(lines(out, "modes "), ["1"])
        self.assertEqual(lines(out, "result "), ["1", "1"])
        self.assertEqual(heads[-1], "HEADLESS-1 Headless output 1 True 200 50 1280 720 0 1000 0")

    def test_idle_notify(self):
        out = self.scenario("idle", "500")
        idle = lines(out, "idle ")
        self.assertEqual(len(idle), 1)
        self.assertGreaterEqual(int(idle[0]), 450)
        self.assertIn("resumed", out.splitlines())

    def test_layer_shell_bar_with_exclusive_zone(self):
        if not GRIM:
            self.skipTest("chybi grim")
        self.window("luxos.test.max", "Maximalni", "#0000ff", "--maximize")
        bar = self.spawn("luxos-layer-test", "32", "#ff0000")
        out = self.wait_line(bar, "mapped")
        self.assertIn("supported True", out)
        self.assertIn("layer True 2 luxos-test-bar", out)
        self.assertIn("anchors True False", out)
        self.assertIn("auto-zone True", out)
        self.assertIn("monitors 1", out)
        # luxos_wl na soketu GDK: okna vidi i list (udalosti rozesila GDK)
        self.assertIn("attach True", out)
        self.assertIn("toplevel luxos.test.max", out)
        time.sleep(0.5)
        width, height, pixel = self.screenshot()
        self.assertEqual((width, height), (1280, 720))
        for x in (5, 640, 1275):
            self.assertEqual([pixel(x, y) for y in (0, 16, 31)], ["ff0000"] * 3)
        # maximalizovane okno zacina pod vyhradni zonou listy (y = 32: titulkovy pruh, pak obsah)
        self.assertNotEqual(pixel(640, 32), "ff0000")
        self.assertEqual(pixel(640, 100), "0000ff")
        self.assertEqual(pixel(640, 719), "0000ff")

    def test_layer_client_idle_memory(self):
        results = {}
        for label, lib in (("luxos_wl", str(self.lib)), ("bez luxos_wl", "/nonexistent")):
            bar = self.spawn("luxos-layer-test", env=dict(self.env, LUXOS_WL_LIB=lib))
            self.wait_line(bar, "mapped")
            time.sleep(2)
            status = Path(f"/proc/{bar.pid}/status").read_text()
            rss = int(next(l for l in status.splitlines() if l.startswith("VmRSS:")).split()[1])
            rollup = Path(f"/proc/{bar.pid}/smaps_rollup").read_text()
            pss = int(next(l for l in rollup.splitlines() if l.startswith("Pss:")).split()[1])
            private = sum(int(l.split()[1]) for l in rollup.splitlines() if l.startswith("Private_"))
            results[label] = (rss, pss, private)
            bar.terminate()
            bar.wait(5)
        print("\n  necinny klient layer-shell (kB): " +
              ", ".join(f"{k}: RSS {v[0]}, PSS {v[1]}, privatni {v[2]}" for k, v in results.items()))
        rss, pss, private = results["luxos_wl"]
        self.assertLess(rss, 60 * 1024)
        self.assertLess(private, 25 * 1024)
        # knihovna protokolu stoji jen malo pameti navic
        self.assertLess(private - results["bez luxos_wl"][2], 2 * 1024)

    def test_no_growth_over_many_events(self):
        out = self.scenario("soak", "3000", timeout=180)
        start, end = map(int, lines(out, "rss ")[0].split())
        print(f"\n  3000 kol snimku 1280x720 + schranky: RSS {start} -> {end} kB")
        self.assertLess(end - start, 4 * 1024)

    def test_without_library_or_compositor(self):
        r = self.run_client("luxos-wl-test", "capture", "x.png", env=dict(self.env, LUXOS_WL_LIB="/nonexistent"))
        self.assertEqual((r.returncode, r.stdout.strip()), (2, "no-library"))
        r = self.run_client("luxos-wl-test", "capture", "x.png", env=dict(self.env, WAYLAND_DISPLAY="wayland-9"))
        self.assertEqual((r.returncode, r.stdout.strip()), (2, "no-connection"))


@unittest.skipUnless(LSLC and LABWC and TOOLS, "chybi lslc, labwc (LUXOS_WL_SYSROOT) nebo make/gcc/wayland-scanner")
class Labwc(WaylandShell, unittest.TestCase):
    name = "labwc"

    def compositor_cmd(self, env):
        if str(LABWC).startswith(str(SYSROOT)):
            env["LD_LIBRARY_PATH"] = str(SYSROOT / "usr/lib")
        return [str(LABWC), "-C", str(self.session / "config/labwc")]


@unittest.skipUnless(LSLC and LUXWM and GRIM and TOOLS, "chybi lslc, luxwm (LUXWM_BUILD), grim nebo make/gcc")
class Luxwm(WaylandShell, unittest.TestCase):
    name = "luxwm"

    def compositor_cmd(self, env):
        # allowlist: testovaci klienti a grim; XWayland vypnuty (zadne sokety v /tmp/.X11-unix)
        allow = self.session / "privileged.conf"
        allow.write_text("".join(str(Path(p).resolve()) + "\n" for p in
                                 [self.tmp / "luxos-wl-test", self.tmp / "luxos-layer-test", GRIM]))
        (self.session / "config/luxwm").mkdir(parents=True)
        (self.session / "config/luxwm/luxwm.conf").write_text("xwayland = no\n")
        env.update(LD_LIBRARY_PATH=f"{LUXWM_BUILD}:{SYSROOT}/usr/lib", LUXWM_PRIVILEGED=str(allow),
                   LUXWM_SYSTEM_CONFIG=str(REPO / "packages/luxwm/luxwm.conf"))
        return [str(LUXWM), "-d"]


if __name__ == "__main__":
    unittest.main()
