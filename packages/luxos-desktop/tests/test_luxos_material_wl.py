#!/usr/bin/env python3
"""Material shellu pod luxwm (headless, pixman): lista, Dock, vyskakovaci okno listy, oznameni, Ovladaci centrum,
Kalendar, nabidka plochy a Launchpad nad tapetou s kontrastnimi pruhy, svetly i tmavy rezim.

    packages/luxwm/tests/build-host.sh
    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -p MemorySwapMax=0 -- timeout 1800 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_material_wl.py -v

Tapeta ma svisle pruhy 4 px (cerna/bila). Pod plochou s materialem je kompozitor rozmaze: slozka s periodou 8 px
v radku pod plochou musi zmizet (rozmazani je pritomne), mimo plochu zustane (kontrola, ze tapeta pruhy ma).
Snimky ploch: tests/wl-material-goldens/*.png, novy vzor LUXOS_MATERIAL_UPDATE_GOLDENS=1. Vsechny snimky obrazovky
ulozi LUXOS_MATERIAL_SHOTS=adresar; LUXOS_MATERIAL_LSL=adresar prelozi klienty z jinych zdroju (snimky "pred" pro
srovnani, kontroly a vzory se pak preskoci). LUXOS_MATERIAL_COMPOSITOR_ENV prida promenne kompozitoru (napr.
LD_PRELOAD=libasan.so pro sestaveni s ASan).

Sbernice jen soukrome (dbus-daemon testu, nahradni sluzby fake_bar_services.py), luxos-notify na nich.
"""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_luxos_bar_wl import Bar, crop, png_read, png_write, ppm_read  # noqa: E402

PKG = HERE.parent
REPO = PKG.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or REPO / "out/wl-test/sysroot")
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")
GOLDENS = HERE / "wl-material-goldens"
UPDATE = os.environ.get("LUXOS_MATERIAL_UPDATE_GOLDENS") == "1"
SOURCES = Path(os.environ.get("LUXOS_MATERIAL_LSL") or PKG / "files/lsl")
BEFORE = "LUXOS_MATERIAL_LSL" in os.environ
SHOTS = os.environ.get("LUXOS_MATERIAL_SHOTS")
TOOLS = all(shutil.which(t) for t in ("make", "gcc", "dbus-daemon", "notify-send"))
W, H, BAR = 1280, 800, 28
PROGRAMS = ("luxos-bar", "luxos-hub", "luxos-dock", "luxos-notify", "luxos-backdrop", "luxos-launchpad")


def stripes():
    """Tapeta: svisle pruhy 4 px, v horni tretine barevne (pestra tapeta), jinde cerne a bile."""
    rows = []
    colours = [(230, 40, 30), (250, 210, 40), (30, 120, 220), (40, 170, 70)]
    for y in range(H):
        row = bytearray()
        for x in range(W):
            on = (x // 4) % 2 == 0
            if y < H // 3:
                c = colours[(x // 160) % 4] if on else (255, 255, 255)
            else:
                c = (0, 0, 0) if on else (255, 255, 255)
            row += bytes(c)
        rows.append(bytes(row))
    return b"".join(rows)


def stripe_energy(image, y, x0, x1):
    """Velikost slozky s periodou pruhu (8 px) v radku: korelace s +1/-1 podle faze tapety; text ani hrany
    s ni nekoreluji. Ostra tapeta ~127, plne rozmazana ~0."""
    width, _, px = image
    total = 0.0
    for x in range(x0, x1):
        i = (y * width + x) * 3
        lum = 0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2]
        total += -lum if (x // 4) % 2 == 0 else lum
    return abs(total) / (x1 - x0)


@unittest.skipUnless(LSLC and TOOLS and WLT.exists() and (LUXWM_BUILD / "luxwm").exists()
                     and (SYSROOT / "usr/lib").exists(), "chybi lslc, luxwm (build-host.sh), sysroot nebo dbus/notify-send")
class MaterialShell(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = REPO / "out/wl-test"
        base.mkdir(parents=True, exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(prefix="matwl-", dir=base))
        r = subprocess.run(["make", "-s", "-C", str(PKG / "files/src/luxos-wl"), f"OUT={cls.tmp}"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("libluxos-wl: " + r.stdout + r.stderr)
        cls.lib = cls.tmp / "libluxos-wl.so.0"
        src = cls.tmp / "src"
        src.mkdir()
        for f in SOURCES.glob("*.lsl"):
            shutil.copy(f, src)
        cls.bin = cls.tmp / "bin"
        cls.bin.mkdir()
        procs = [subprocess.Popen([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(src), str(src / f"{n}.lsl"),
                                   str(cls.bin / n)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT) for n in PROGRAMS]
        for name, p in zip(PROGRAMS, procs):
            out = p.communicate()[0]
            if p.returncode != 0:
                raise RuntimeError(f"{name}: " + out.decode())
        os.symlink("luxos-hub", cls.bin / "luxos-control-center")
        os.symlink("luxos-hub", cls.bin / "luxos-calendar")
        cls.wall = cls.tmp / "stripes.png"
        png_write(cls.wall, W, H, stripes())

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
            # logy klientu a kompozitoru posledniho behu (rozbor chyb)
            keep = REPO / "out/wl-test/material-logs" / self._testMethodName
            shutil.rmtree(keep, True)
            keep.mkdir(parents=True)
            for f in self.session.glob("*.log"):
                shutil.copy(f, keep)
            shutil.rmtree(self.session, True)

    # ---- relace ----

    def wlt(self, *args, env=None):
        r = subprocess.run([str(WLT), *args], capture_output=True, text=True, timeout=120, env=env)
        if r.returncode != 0:
            self.fail(f"wlt {args[0]}: " + r.stdout + r.stderr)
        return r.stdout

    def start(self, dark):
        name = f"m{os.getpid() % 100000}{'d' if dark else 'l'}"
        conf = self.tmp / f"luxwm-{name}.conf"
        conf.write_text("xwayland = no\n" + (REPO / "packages/luxwm/luxwm.conf").read_text())
        env = dict(os.environ)
        env["WLT_COMPOSITOR_ENV"] = (f"LUXCOMP_VIRTUAL_INPUT=1 LUXCOMP_STATS=1 LUXWM_SYSTEM_CONFIG={conf} "
                                     f"LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib "
                                     + os.environ.get("LUXOS_MATERIAL_COMPOSITOR_ENV", ""))
        env["WLT_PRIVILEGED"] = f"{self.bin / 'luxos-bar'} {self.bin / 'luxos-dock'}"
        self.session = Path(self.wlt("start", "--mode", "headless", "--size", f"{W}x{H}", "--timeout", "900",
                                     "--name", name, "--", str(LUXWM_BUILD / "luxwm"), env=env).strip().splitlines()[-1])
        self.env = {}
        for line in self.wlt("env", str(self.session)).splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            self.env[key] = value
        self.env.pop("LD_LIBRARY_PATH", None)
        cfg = self.session / "config"
        (cfg / "luxos").mkdir(parents=True, exist_ok=True)
        (cfg / "luxos/appearance").write_text("dark\n" if dark else "light\n")
        (cfg / "luxos/appearance.conf").write_text(f"WALLPAPER={self.wall}\nWALLPAPER_MODE=fill\n")
        (cfg / "gtk-3.0").mkdir(parents=True, exist_ok=True)
        theme = "WhiteSur" if Path("/usr/share/icons/WhiteSur").exists() else "Adwaita"
        (cfg / "gtk-3.0/settings.ini").write_text(f"[Settings]\ngtk-icon-theme-name={theme}\ngtk-font-name=Inter 10\n"
                                                  "gtk-enable-animations=false\n"
                                                  + ("gtk-theme-name=Adwaita-dark\n" if dark else ""))
        (cfg / "luxos/dock.conf").write_text("pinned=\nhide=none\n")
        buses = self.session / "dbus"
        buses.mkdir()
        addrs = {}
        for bus in ("system", "session"):
            self.spawn("dbus-daemon", "--session", f"--address=unix:path={buses / bus}", "--nofork", "--nopidfile")
            addrs[bus] = f"unix:path={buses / bus}"
        for bus in ("system", "session"):
            for _ in range(100):
                if (buses / bus).exists():
                    break
                time.sleep(0.05)
        fake = subprocess.Popen(["python3", "-I", str(HERE / "fake_bar_services.py"), addrs["system"], addrs["session"]],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=dict(os.environ, PYTHONUNBUFFERED="1"))
        self.procs.append(fake)
        Bar(fake).wait(r"^ready$")
        self.env.update(GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GTK_A11Y="none", LUXOS_WL_LIB=str(self.lib),
                        PATH=f"{self.bin}:/usr/bin:/bin", LUXOS_BAR_TRACE="1", LUXOS_BAR_NOW="2026-11-20 09:41",
                        DBUS_SYSTEM_BUS_ADDRESS=addrs["system"], DBUS_SESSION_BUS_ADDRESS=addrs["session"],
                        LUXOS_HUB_PREBUILD_DELAY="1", LUXOS_HUB_NEWS_DELAY="100000", LUXOS_HUB_NO_PORTAL="1",
                        LUXOS_CALENDAR_DIR=str(self.session / "calendar"), LUXOS_POWER_SUPPLY=str(self.session / "power"))
        if dark:
            # hub bere rezim z nazvu motivu GTK (na Waylandu z GSettings, settings.ini nestaci)
            self.env["GTK_THEME"] = "Adwaita:dark"
        (self.session / "power").mkdir()
        self.spawn(str(self.bin / "luxos-backdrop"))
        bar = Bar(self.spawn(str(self.bin / "luxos-bar"), out=True))
        bar.wait(r"^drawn HEADLESS-1")
        self.bar = bar
        self.spawn(str(self.bin / "luxos-dock"))
        self.hub = self.spawn(str(self.bin / "luxos-hub"))
        self.spawn(str(self.bin / "luxos-notify"))
        time.sleep(3.0)

    def spawn(self, *cmd, out=False):
        log = open(self.session / f"{Path(cmd[0]).name}.log", "a") if self.session else subprocess.DEVNULL
        p = subprocess.Popen(list(cmd), env=getattr(self, "env", None), stdout=subprocess.PIPE if out else subprocess.DEVNULL,
                             stderr=log)
        self.procs.append(p)
        return p

    def input(self, *cmds):
        self.wlt("input", str(self.session), *cmds)

    def shot(self, name):
        path = self.session / "shot.ppm"
        self.wlt("shot", str(self.session), str(path))
        image = ppm_read(path)
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            png_write(Path(SHOTS) / f"{name}.png", *image)
        return image

    # ---- kontroly ----

    def blurred(self, image, name, y, x0, x1):
        if BEFORE:
            return
        under = stripe_energy(image, y, x0, x1)
        print(f"\n  {name}: pruhy pod plochou {under:.1f}", end="")
        self.assertLess(under, 6.0, f"{name}: pod plochou jsou ostre pruhy tapety ({under:.1f})")

    def sharp(self, image, y, x0, x1):
        if not BEFORE:
            self.assertGreater(stripe_energy(image, y, x0, x1), 30.0, "tapeta bez pruhu")

    def golden(self, name, image):
        if BEFORE:
            return
        golden = GOLDENS / f"{name}.png"
        if UPDATE or not golden.exists():
            GOLDENS.mkdir(exist_ok=True)
            png_write(golden, *image)
            if not UPDATE:
                self.skipTest(f"vzor {golden} vytvoren")
            return
        want = png_read(golden)
        self.assertEqual(want[:2], image[:2], f"{name}: jina velikost nez vzor")
        a, b = want[2], image[2]
        diff = [abs(a[i] - b[i]) for i in range(len(a))]
        bad = sum(1 for i in range(0, len(diff), 3) if max(diff[i:i + 3]) > 48) / (len(diff) // 3)
        mean = sum(diff) / len(diff)
        print(f"\n  {name}: prumerny rozdil {mean:.2f}, odlisne pixely {bad * 100:.2f} %", end="")
        self.assertLess(mean, 4.0, name)
        self.assertLess(bad, 0.03, name)

    def close(self):
        self.input("key Escape")
        time.sleep(0.6)

    # ---- testy ----

    def surfaces(self, dark):
        mode = "dark" if dark else "light"
        self.start(dark)
        image = self.shot(f"desktop-{mode}")
        self.sharp(image, 500, 100, 400)
        # lista: pruh 28 px nahore pres celou sirku, uprostred bez textu
        self.blurred(image, f"bar-{mode}", 14, 400, 900)
        self.golden(f"bar-{mode}", crop(image, 0, 0, W, BAR))
        # Dock dole uprostred (panel = vstupni oblast)
        self.blurred(image, f"dock-{mode}", H - 4, W // 2 - 30, W // 2 + 30)
        self.golden(f"dock-{mode}", crop(image, W // 2 - 200, H - 120, 400, 120))

        # oznameni vpravo nahore
        subprocess.run(["notify-send", "-a", "Pošta", "-t", "0", "Nová zpráva", "Krátký text oznámení"], env=self.env,
                       timeout=10)
        time.sleep(1.0)
        image = self.shot(f"toast-{mode}")
        self.blurred(image, f"toast-{mode}", BAR + 40, W - 8 - 120, W - 16)
        # mezi bublinou a okrajem plochy (vstupni oblast jen bublina) material neni
        self.sharp(image, BAR + 75, W - 8 - 120, W - 16)
        self.golden(f"toast-{mode}", crop(image, W - 360, BAR, 360, 120))

        # Ovladaci centrum a Kalendar (signaly hubu, bez zapisu listy vpravo pod listou)
        for name, sig, width in (("cc", signal.SIGUSR1, 340), ("calendar", signal.SIGUSR2, 340)):
            self.hub.send_signal(sig)
            time.sleep(1.2)
            image = self.shot(f"{name}-{mode}")
            self.blurred(image, f"{name}-{mode}", BAR + 14, W - 8 - width + 20, W - 30)
            self.golden(f"{name}-{mode}", crop(image, W - 8 - width - 20, BAR, width + 28, 420))
            self.close()

        # vyskakovaci okno listy: zvonek vlevo od hodin
        self.input("move 1145 14", "click")
        time.sleep(1.0)
        image = self.shot(f"popup-{mode}")
        self.blurred(image, f"popup-{mode}", BAR + 10, W - 330, W - 30)
        self.golden(f"popup-{mode}", crop(image, W - 360, BAR, 360, 300))
        self.close()

        # nabidka plochy (xdg_popup plochy s materialem "popups")
        self.input("move 300 400", "click right")
        time.sleep(1.0)
        image = self.shot(f"menu-{mode}")
        self.blurred(image, f"menu-{mode}", 404, 330, 420)
        self.golden(f"menu-{mode}", crop(image, 290, 390, 260, 240))
        self.close()

        # Launchpad: rozmazana cela obrazovka se zatemnenim a panel sheet
        self.spawn(str(self.bin / "luxos-launchpad"), "--show", "launchpad")
        time.sleep(2.5)
        image = self.shot(f"launchpad-{mode}")
        self.blurred(image, f"launchpad-{mode}", 20, 20, 200)
        self.golden(f"launchpad-{mode}", self.half(image))
        self.close()
        if not BEFORE:
            log = (self.session / "compositor.log")
            stats = log.read_text() if log.exists() else ""
            self.assertNotIn("solid material from now on", stats)

    def half(self, image):
        """Polovicni zmensenina (vzor Launchpadu by mel pres 2 MB)."""
        width, height, px = image
        out = bytearray()
        for y in range(0, height, 2):
            for x in range(0, width, 2):
                i = (y * width + x) * 3
                out += px[i:i + 3]
        return width // 2, height // 2, bytes(out)

    def test_light(self):
        self.surfaces(False)

    def test_dark(self):
        self.surfaces(True)


if __name__ == "__main__":
    unittest.main()
