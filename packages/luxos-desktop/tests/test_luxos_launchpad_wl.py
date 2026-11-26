#!/usr/bin/env python3
"""Launchpad a Hledani na Waylandu (files/lsl/luxos-launchpad.lsl) proti beznemu labwc headless (pixman) z harnessu WP-1.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -p MemorySwapMax=0 -- timeout 1200 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_launchpad_wl.py -v

Kazdy test ma vlastni relaci `scripts/wl-test/wlt start` a soukromou sbernici D-Bus. Aplikace jsou jen testovaci
.desktop soubory (XDG_DATA_DIRS = adresar testu, ikony hostitele pres odkaz); kazda spousti marker.sh, ktery zapise
sve id. Super+A / Super+Space v labwc spousti files/bin/luxos-launchpad a luxos-search jako v relaci (gdbus -> bezici
Launchpad, jinak novy proces). Klavesnice je jeden stale bezici `wlt input` (WLT_STAMP: cas stisku), jinak by labwc
po kazdem volani vzal fokus. Doba otevreni = stisk klavesy -> prvni snimek Launchpadu po commitu (metoda
scripts/perf/launch-probe.py: od spusteni do zobrazeni okna).

Snimky: tests/wl-launchpad-goldens/*.png, novy vzor: LUXOS_LAUNCHPAD_UPDATE_GOLDENS=1.
"""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_luxos_bar_wl import Bar, crop, gradient, pixel, png_read, png_write, ppm_read  # noqa: E402

PKG = HERE.parent
REPO = PKG.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
GOLDENS = HERE / "wl-launchpad-goldens"
UPDATE = os.environ.get("LUXOS_LAUNCHPAD_UPDATE_GOLDENS") == "1"
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test") / "sysroot")
HAVE_LABWC = (SYSROOT / "usr/bin/labwc").exists() or shutil.which("labwc")
HAVE_TOOLS = all(shutil.which(t) for t in ("dbus-daemon", "gdbus", "make", "gcc"))
IDLE_SECONDS = int(os.environ.get("LUXOS_LAUNCHPAD_IDLE_SECONDS", "60"))
W, H = 1280, 800

# id -> radky .desktop (Exec doplni setUpClass)
APPS = {
    "org.example.Browser": "Name=Web Browser\nName[cs]=Prohlížeč\nGenericName=Web Browser\nGenericName[cs]=Webový prohlížeč\n"
                           "Keywords=web;internet;\nIcon=web-browser\nCategories=Network;\n",
    "org.example.Terminal": "Name=Terminal\nName[cs]=Terminál\nKeywords=shell;prompt;command;\nIcon=utilities-terminal\n"
                            "Categories=System;\n",
    "org.example.Files": "Name=Files\nName[cs]=Soubory\nGenericName[cs]=Správce souborů\nIcon=system-file-manager\n"
                         "Categories=System;\n",
    "org.example.Text": "Name=Text Editor\nName[cs]=Textový editor\nIcon=accessories-text-editor\nCategories=Utility;\n",
    "org.example.Calculator": "Name=Calculator\nName[cs]=Kalkulačka\nIcon=accessories-calculator\nCategories=Utility;\n",
    "org.example.Paint": "Name=Image Editor\nName[cs]=Editor obrázků\nIcon=applications-graphics\nCategories=Graphics;\n",
    "org.example.TestApp": "Name=Lux Test App\nIcon=applications-science\nCategories=Science;\n",
    # Launchpad ukazuje vsechny aplikace, i panely Nastaveni a kopie jen pro Launchpad (X-LuxOS-Launchpad);
    # ne NoDisplay souboru, OnlyShowIn jineho prostredi a kopii panelu, kdyz je videt puvodni panel.
    # "Zzz": az za vyplni, at nove viditelne polozky neposunou prvni stranu (vzory snimku)
    "luxos-bluetooth": "Name=Bluetooth\nIcon=bluetooth\nCategories=Settings;X-XFCE-SettingsDialog;\n",
    "org.example.Printers": "Name=Printers\nIcon=printer\nOnlyShowIn=X-LuxOS-Launchpad;\nCategories=Settings;\n",
    "org.example.Hidden": "Name=Hidden Thing\nNoDisplay=true\nIcon=dialog-warning\n",
    "org.example.Panel": "Name=Zzz Panel Dialog\nIcon=preferences-system\nCategories=Settings;X-XFCE-SettingsDialog;\n",
    "org.example.Panel-launchpad": "Name=Zzz Panel Dialog\nIcon=preferences-system\nOnlyShowIn=X-LuxOS-Launchpad;\n"
                                   "Categories=X-LuxOS-Launchpad;\n",
    "org.example.KdeOnly": "Name=Kde Only\nOnlyShowIn=KDE;\nIcon=preferences-system\n",
    # skryta prekrytim LuxOS (COVERED: .../luxos/xdg, NoDisplay bez Exec), puvodni soubor je aplikace
    "org.example.Covered": "Name=Zzz Covered Tool\nIcon=utilities-system-monitor\nCategories=System;\n",
    "org.example.CoveredHelper": "Name=Covered Helper\nNoDisplay=true\nIcon=dialog-warning\n",
}
COVERED = ["org.example.Covered", "org.example.CoveredHelper", "org.example.NotInstalled"]
for _n in range(1, 31):
    APPS[f"org.example.Filler{_n:02d}"] = f"Name=Zz Filler {_n:02d}\nIcon=application-x-executable\nCategories=Utility;\n"
VISIBLE = [k for k in APPS if k not in ("org.example.Hidden", "org.example.Panel-launchpad", "org.example.KdeOnly",
                                        "org.example.CoveredHelper")]
FOLD = str.maketrans("áčďéěíňóřšťúůýž", "acdeeinorstuuyz")


def alpha_order():
    """Poradi Abecedne jako luxos_launchpad_model.order (nazev bez diakritiky, malymi pismeny, bajty UTF-8)."""
    def name(k):
        m = re.search(r"^Name\[cs\]=(.*)$", APPS[k], re.M) or re.search(r"^Name=(.*)$", APPS[k], re.M)
        return m.group(1).lower().translate(FOLD).encode()
    return [k + ".desktop" for k in sorted(VISIBLE, key=name)]


class Input:
    """Jeden stale pripojeny `wlt input` (klavesnice zustava v seatu); radky `stamp KEY US`."""

    def __init__(self, session, env):
        self.proc = subprocess.Popen([str(WLT), "input", str(session)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, env=env, text=True, bufsize=1)
        self.stamps = []
        self.cond = threading.Condition()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in self.proc.stdout:
            m = re.match(r"^stamp (\S+) (\d+)$", line.strip())
            with self.cond:
                if m:
                    self.stamps.append((m.group(1), int(m.group(2))))
                self.cond.notify_all()

    def send(self, *cmds):
        for c in cmds:
            self.proc.stdin.write(c + "\n")
        self.proc.stdin.flush()

    def stamp(self, key, after, timeout=5):
        deadline = time.monotonic() + timeout
        with self.cond:
            while True:
                for k, us in self.stamps[after:]:
                    if k == key:
                        return us
                if time.monotonic() > deadline:
                    raise AssertionError(f"stisk {key} se neobjevil")
                self.cond.wait(0.1)

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc.stdout.close()


class LogFile:
    """Vystup Launchpadu spusteneho kompozitorem (klavesova zkratka) v souboru."""

    def __init__(self, path):
        self.path = path

    def lines(self):
        return self.path.read_text(errors="replace").splitlines() if self.path.exists() else []

    def mark(self):
        return len(self.lines())

    def wait(self, pattern, timeout=10, start=0):
        rx = re.compile(pattern)
        deadline = time.monotonic() + timeout
        while True:
            lines = self.lines()
            for i in range(start, len(lines)):
                m = rx.search(lines[i])
                if m:
                    return i, m
            if time.monotonic() > deadline:
                raise AssertionError(f"{pattern!r} se neobjevilo:\n" + "\n".join(lines[-30:]))
            time.sleep(0.01)


@unittest.skipUnless(LSLC and HAVE_LABWC and HAVE_TOOLS and WLT.exists(), "chybi lslc, labwc (WLT_SYSROOT), dbus-daemon/gdbus nebo make")
class WaylandLaunchpad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
        base.mkdir(parents=True, exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(prefix="lp-", dir=base))
        src = cls.tmp / "lsl"
        src.mkdir()
        for f in list((PKG / "files/lsl").glob("*.lsl")) + list((HERE / "lsl").glob("*.lsl")):
            shutil.copy(f, src)
        for name in ("luxos-launchpad", "luxos-calc-test", "luxos-launchpad-model-test"):
            r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(src), str(src / f"{name}.lsl"),
                                str(cls.tmp / name)],
                               capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                raise RuntimeError(f"{name}: " + r.stdout + r.stderr)
        marker = cls.tmp / "marker.sh"
        marker.write_text('#!/bin/sh\necho "$1" >>"$LP_MARKER"\n')
        marker.chmod(0o755)
        share = cls.tmp / "share"
        (share / "applications").mkdir(parents=True)
        for k, body in APPS.items():
            (share / "applications" / f"{k}.desktop").write_text(
                f"[Desktop Entry]\nType=Application\n{body}Exec={marker} {k}\n")
        for d in ("icons", "glib-2.0", "mime"):
            if Path("/usr/share", d).exists():
                (share / d).symlink_to(Path("/usr/share", d))
        # skryvaci prekryti LuxOS jako v luxos-desktop (PKGBUILD, files/hide/apps)
        cover = cls.tmp / "luxos/xdg/applications"
        cover.mkdir(parents=True)
        for k in COVERED:
            (cover / f"{k}.desktop").write_text(f"[Desktop Entry]\nType=Application\nName={k}\nNoDisplay=true\n")
        # luxos-search spousti luxos-launchpad z PATH
        cls.bin = cls.tmp / "bin"
        cls.bin.mkdir()
        for name in ("luxos-launchpad", "luxos-search"):
            (cls.bin / name).symlink_to(PKG / "files/bin" / name)
        # LuxAI jen jako zaznam dotazu (vysledek "Zeptat se LuxAI" nezavisi na hostiteli)
        luxai = cls.bin / "luxai"
        luxai.write_text('#!/bin/sh\necho "luxai $*" >>"$LP_MARKER"\n')
        luxai.chmod(0o755)
        # Super+A / Super+Space jako luxwm.conf; key.sh nacte prostredi klienta (ne knihovny sysrootu kompozitoru)
        key = cls.tmp / "key.sh"
        key.write_text('#!/bin/bash\nset -a\n. "$(dirname "$0")/key.env"\nset +a\nunset LD_LIBRARY_PATH\n'
                       'exec "$(dirname "$0")/bin/$1" >>"$LP_KEYLOG" 2>&1\n')
        key.chmod(0o755)
        conf = cls.tmp / "labwc"
        shutil.copytree(REPO / "scripts/wl-test/labwc", conf)
        rc = (conf / "rc.xml").read_text()
        binds = (f'    <keybind key="W-a"><action name="Execute" command="{key} luxos-launchpad"/></keybind>\n'
                 f'    <keybind key="W-space"><action name="Execute" command="{key} luxos-search"/></keybind>\n')
        rc = rc.replace("  </keyboard>", binds + "  </keyboard>")
        (conf / "rc.xml").write_text(rc)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.procs = []
        self.pids = []
        self.session = None
        self.input = None

    def tearDown(self):
        if self.input:
            self.input.close()
        for pid in self.pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
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

    def wlt(self, *args):
        r = subprocess.run([str(WLT), *args], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            self.fail(f"wlt {args[0]}: " + r.stdout + r.stderr)
        return r.stdout

    def start(self, dark=False, wallpaper="light", sort="alpha"):
        name = f"lp{os.getpid()}-{sorted(n for n in dir(self) if n.startswith('test_')).index(self._testMethodName)}"
        bus = self.tmp / f"{name}.bus"
        p = subprocess.Popen(["dbus-daemon", "--session", f"--address=unix:path={bus}", "--nofork", "--nopidfile"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        self.session = Path(self.wlt("start", "--mode", "headless", "--size", f"{W}x{H}", "--timeout", "900",
                                     "--name", name, "--config", str(self.tmp / "labwc")).strip())
        env = {}
        for line in self.wlt("env", str(self.session)).splitlines():
            k, _, v = line.removeprefix("export ").partition("=")
            env[k] = v
        # wlt input si prostredi relace vezme sam; zvenku jen WLT_OUT/WLT_SYSROOT (jinak by nastroje harnessu
        # stavel znovu v out/wl-test s knihovnami sysrootu a skoncil hned na startu - BrokenPipe v testech)
        input_env = {k: v for k, v in os.environ.items()
                     if k not in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS")}
        env.pop("LD_LIBRARY_PATH", None)
        env.update(GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GTK_A11Y="none", LUXOS_LAUNCHPAD_TRACE="1",
                   DBUS_SESSION_BUS_ADDRESS=f"unix:path={bus}", XDG_DATA_DIRS=f"{self.tmp / 'luxos/xdg'}:{self.tmp / 'share'}",
                   LANG="cs_CZ.UTF-8", LANGUAGE="cs", LUXOS_I18N_DIR=str(REPO / "packages/luxos-i18n/files"),
                   LP_MARKER=str(self.session / "marker"), LP_KEYLOG=str(self.session / "key.log"),
                   LUXOS_LAUNCHPAD_WAYLAND=str(self.tmp / "luxos-launchpad"),
                   PATH=f"{self.bin}:{env['PATH']}")
        self.env = env
        (self.tmp / "key.env").write_text("".join(f"{k}={v}\n" for k, v in env.items()))
        conf = self.session / "config"
        (conf / "luxos").mkdir(parents=True, exist_ok=True)
        (conf / "gtk-3.0").mkdir(parents=True, exist_ok=True)
        theme = "WhiteSur" if Path("/usr/share/icons/WhiteSur").exists() else "Adwaita"
        (conf / "gtk-3.0/settings.ini").write_text(f"[Settings]\ngtk-icon-theme-name={theme}\ngtk-font-name=Inter 10\n"
                                                   "gtk-enable-animations=false\ngtk-cursor-blink=false\n")
        (conf / "luxos/launchpad-sort").write_text(sort + "\n")
        self.set_look(dark, wallpaper)
        for _ in range(100):
            if bus.exists():
                break
            time.sleep(0.05)
        self.input = Input(self.session, dict(input_env, WLT_STAMP="1"))
        return self.session

    def set_look(self, dark, wallpaper):
        conf = self.session / "config/luxos"
        path = self.session / f"wall-{wallpaper}.png"
        top, bottom = ((246, 241, 232), (226, 232, 246)) if wallpaper == "light" else ((24, 30, 62), (46, 28, 60))
        png_write(path, 320, 200, gradient(320, 200, top, bottom))
        (conf / "appearance").write_text("dark\n" if dark else "light\n")
        (conf / "appearance.conf").write_text(f"WALLPAPER={path}\n")

    def resident(self, *args):
        p = subprocess.Popen([str(self.tmp / "luxos-launchpad"), *args], env=self.env, stdout=subprocess.PIPE)
        self.procs.append(p)
        lp = Bar(p)
        lp.wait(r"^\d+ icons ")
        return lp

    def gdbus(self, method, *args):
        return subprocess.run(["gdbus", "call", "--session", "--dest", "cz.luxos.Launchpad", "--object-path",
                               "/cz/luxos/Launchpad", "--method", f"cz.luxos.Launchpad.{method}", *args],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def open_by_key(self, lp, key="super+a", mode="launchpad"):
        """Stisk zkratky -> ms do prvniho snimku."""
        mark = lp.mark()
        after = len(self.input.stamps)
        self.input.send(f"key {key}")
        pressed = self.input.stamp(key.split("+")[-1], after)
        _, m = lp.wait(rf"shown mode={mode} mono_us=(\d+)", start=mark)
        return (int(m.group(1)) - pressed) / 1000

    def close_by_key(self, lp):
        mark = lp.mark()
        self.input.send("key Escape")
        lp.wait(r" hidden$", start=mark)

    def type_query(self, lp, text):
        mark = lp.mark()
        self.input.send("key ctrl+a", "key BackSpace", f"type {text}")
        _, m = lp.wait(rf" results {re.escape(text)} : (.*)$", start=mark)
        return m.group(1).split()

    def shot(self):
        path = self.session / "shot.ppm"
        self.wlt("shot", str(self.session), str(path))
        return ppm_read(path)

    def marker(self, timeout=5):
        path = self.session / "marker"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists() and path.read_text().strip():
                return path.read_text().split()
            time.sleep(0.05)
        return []

    def compare_golden(self, name, image):
        golden = GOLDENS / f"{name}.png"
        out = self.session / f"{name}.png"
        png_write(out, *image)
        keep = Path(os.environ.get("LUXOS_LAUNCHPAD_SHOTS") or self.tmp.parent / "launchpad-shots")
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

    # ---- bez displeje ----

    def unit(self, name):
        r = subprocess.run([str(self.tmp / name)], capture_output=True, text=True, timeout=60)
        fails = [l for l in r.stdout.splitlines() if not l.startswith("ok ")]
        self.assertEqual(r.returncode, 0, "\n".join(fails) + r.stderr)
        self.assertEqual(fails, [])
        return len(r.stdout.splitlines())

    def test_calc_and_model_units(self):
        n = self.unit("luxos-calc-test") + self.unit("luxos-launchpad-model-test")
        print(f"\n  {n} pripadu vypoctu a hledani")

    # ---- otevreni ----

    def test_open_time_resident_and_fresh(self):
        self.start()
        lp = self.resident()
        first = self.open_by_key(lp)
        self.close_by_key(lp)
        warm = []
        for _ in range(10):
            warm.append(self.open_by_key(lp))
            self.close_by_key(lp)
        warm.sort()
        # rozpad: stisk -> obsluha D-Bus v Launchpadu (labwc, bash, gdbus) a obsluha -> snimek
        shows = [int(l.split()[0]) for l in lp.lines if l.endswith(" show launchpad")]
        frames = [int(l.split()[0]) for l in lp.lines if " shown mode=" in l]
        handler = sorted(b - a for a, b in zip(shows, frames))[1:]
        draw = [int(m.group(1)) for m in (re.search(r"first-draw us=(\d+)", l) for l in lp.lines) if m]
        # novy proces pri kazdem stisku: Launchpad nebezi a sbernice ho neumi spustit (bez aktivace)
        lp.proc.terminate()
        lp.proc.wait(5)
        log = LogFile(self.session / "key.log")
        fresh = []
        for _ in range(3):
            start = log.mark()
            fresh.append(self.open_by_key(log))
            _, m = log.wait(r" ready pid=(\d+)", start=start)
            pid = int(m.group(1))
            self.pids.append(pid)
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
        fresh.sort()
        print(f"\n  otevreni klavesou -> prvni snimek: bezici proces prvni {first:.0f} ms, teple median "
              f"{warm[len(warm) // 2]:.0f} ms, max {warm[-1]:.0f} ms (prvni kresleni median "
              f"{sorted(draw)[len(draw) // 2] / 1000:.1f} ms, obsluha -> snimek median {handler[len(handler) // 2]} ms); novy proces median {fresh[1]:.0f} ms, max {fresh[-1]:.0f} ms")
        self.assertLessEqual(warm[len(warm) // 2], 100)
        self.assertLessEqual(warm[-1], 150)

    def test_idle_memory_and_wakeups(self):
        self.start()
        lp = self.resident()
        self.open_by_key(lp)
        self.type_query(lp, "te")
        self.close_by_key(lp)
        time.sleep(3)
        pid = lp.proc.pid

        def switches():
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
        time.sleep(IDLE_SECONDS)
        after = switches()
        wakeups = sum(max(0, n - before.get(tid, 0)) for tid, n in after.items())
        cpu = sum(map(int, Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[11:13])) - cpu_before
        mem = rollup()
        print(f"\n  skryty Launchpad: PSS {mem['Pss'] / 1024:.1f} MB, RSS {mem['Rss'] / 1024:.1f} MB, privatni "
              f"{(mem['Private_Clean'] + mem['Private_Dirty']) / 1024:.1f} MB; za {IDLE_SECONDS} s {wakeups} probuzeni, "
              f"CPU {cpu} tiku")
        self.assertLess(mem["Pss"], 40 * 1024)
        self.assertLess(wakeups / IDLE_SECONDS, 0.5)
        self.assertLessEqual(cpu, 2)

    # ---- klavesnice ----

    def test_keyboard_only_navigation_launches_app(self):
        self.start(sort="alpha")
        lp = self.resident()
        order = alpha_order()
        cols = 6
        self.open_by_key(lp)
        mark = lp.mark()
        self.input.send("key Down", "key Right", "key Right")
        self.assertEqual(lp.wait(rf" sel {cols + 2} (\S+)", start=mark)[1].group(1), order[cols + 2])
        # Tab dal, Shift+Tab zpet, PageDown o 4 radky (posun mrizky), End/Home
        mark = lp.mark()
        self.input.send("key Tab", "key shift+Tab", "key Page_Down")
        _, m = lp.wait(rf" sel {cols + 2 + 4 * cols} (\S+) top=(\d+)", start=mark)
        self.assertEqual(m.group(1), order[cols + 2 + 4 * cols])
        self.assertGreater(int(m.group(2)), 0)
        mark = lp.mark()
        self.input.send("key End")
        lp.wait(rf" sel {len(order) - 1} {re.escape(order[-1])} ", start=mark)
        mark = lp.mark()
        self.input.send("key Home")
        lp.wait(r" sel 0 .* top=0", start=mark)
        # na Lux Test App sipkami a Enter
        target = order.index("org.example.TestApp.desktop")
        mark = lp.mark()
        self.input.send(*(["key Down"] * (target // cols)), *(["key Right"] * (target % cols)))
        lp.wait(rf" sel {target} org.example.TestApp", start=mark)
        mark = lp.mark()
        self.input.send("key Return")
        lp.wait(r" launch org.example.TestApp.desktop$", start=mark)
        lp.wait(r" hidden$", start=mark)
        self.assertEqual(self.marker(), ["org.example.TestApp"])
        usage = json.loads((self.session / "home/.local/share/luxos/launchpad-usage.json").read_text())
        self.assertEqual(usage["apps"]["org.example.TestApp.desktop"]["count"], 1)
        # Nejpouzivanejsi: spustena aplikace je prvni (Alt+3)
        self.open_by_key(lp)
        mark = lp.mark()
        self.input.send("key alt+3", "key Right", "key Left")
        lp.wait(r" sort most$", start=mark)
        lp.wait(r" sel 0 org.example.TestApp.desktop", start=mark)

    def test_search_ranking(self):
        self.start()
        lp = self.resident()
        self.open_by_key(lp)
        cases = [
            ("prohlizec", "org.example.Browser.desktop"),      # cesky nazev bez diakritiky
            ("Prohlizec", "org.example.Browser.desktop"),
            ("web", "org.example.Browser.desktop"),            # anglicky nazev a klicove slovo
            ("term", "org.example.Terminal.desktop"),          # zacatek nazvu
            ("shell", "org.example.Terminal.desktop"),         # klicove slovo
            ("calculator", "org.example.Calculator.desktop"),  # nelokalizovany nazev
            ("kalk", "org.example.Calculator.desktop"),
            ("obrazku", "org.example.Paint.desktop"),          # zacatek slova uprostred nazvu
            ("sprvce", "org.example.Files.desktop"),           # fuzzy v popisu ("Spravce souboru")
            ("spr soub", "org.example.Files.desktop"),         # dve slova, kazde jinde
            ("lxtst", "org.example.TestApp.desktop"),          # fuzzy
            ("bluetooth", "luxos-bluetooth.desktop"),          # aplikace z LAUNCHPAD_APPS i s kategorii panelu
            ("printers", "org.example.Printers.desktop"),      # OnlyShowIn=X-LuxOS-Launchpad
            ("panel dialog", "org.example.Panel.desktop"),     # panel Nastaveni; kopie jen pro Launchpad navic ne
            ("covered", "org.example.Covered.desktop"),        # skryta v nabidce prekrytim LuxOS
        ]
        for query, first in cases:
            with self.subTest(query=query):
                found = self.type_query(lp, query)
                self.assertEqual(found[0], first, found)
        for query in ("hidden thing", "kde only", "covered helper"):
            with self.subTest(query=query):
                self.assertEqual([f for f in self.type_query(lp, query) if f != "luxai"], [])
        self.assertEqual([f for f in self.type_query(lp, "panel dialog") if f != "luxai"], ["org.example.Panel.desktop"])
        # bez shody jen LuxAI; Ctrl+Enter posle dotaz LuxAI i kdyz aplikace sedi
        self.assertEqual(self.type_query(lp, "jak se mas"), ["luxai"])
        self.assertEqual(self.type_query(lp, "terminal")[-1], "luxai")
        mark = lp.mark()
        self.input.send("key ctrl+Return")
        lp.wait(r" luxai terminal$", start=mark)
        self.assertEqual(self.marker(), ["luxai", "--agent", "terminal"])
        (self.session / "marker").unlink()
        self.open_by_key(lp)
        # Enter po psani spusti nejlepsi shodu
        self.type_query(lp, "textovy")
        mark = lp.mark()
        self.input.send("key Return")
        lp.wait(r" launch org.example.Text.desktop$", start=mark)
        self.assertEqual(self.marker(), ["org.example.Text"])
        # aplikace pod prekrytim LuxOS se spusti z puvodniho souboru (prekryti nema Exec)
        (self.session / "marker").unlink()
        self.open_by_key(lp)
        self.type_query(lp, "covered")
        mark = lp.mark()
        self.input.send("key Return")
        lp.wait(r" launch org.example.Covered.desktop$", start=mark)
        self.assertEqual(self.marker(), ["org.example.Covered"])

    def test_math_inline(self):
        self.start()
        lp = self.resident()
        self.open_by_key(lp)
        for query, shown in (("2+2*3", "=8"), ("sqrt(2)", "=1,41421356237"), ("15% z 300", "=45"), ("2^10", "=1024"),
                             ("(1+2)*3/4", "=2,25"), ("0,1+0,2", "=0,3"), ("1/3*3", "=1")):
            with self.subTest(query=query):
                self.assertEqual(self.type_query(lp, query)[0], shown)
        self.assertNotIn("=", "".join(self.type_query(lp, "42")))
        self.type_query(lp, "12*(3+4)")
        time.sleep(0.3)
        image = self.shot()
        self.compare_golden("calc", crop(image, 240, 80, 800, 240))
        mark = lp.mark()
        self.input.send("key Return")
        lp.wait(r" copy 84$", start=mark)
        lp.wait(r" hidden$", start=mark)

    def test_escape_and_click_outside_close(self):
        self.start()
        lp = self.resident()
        self.open_by_key(lp)
        time.sleep(0.2)
        self.assertNotEqual(pixel(self.shot(), W // 2, H // 2), "000000")
        self.close_by_key(lp)
        time.sleep(0.3)
        self.assertEqual(pixel(self.shot(), W // 2, H // 2), "000000")
        # klik do panelu mimo dlazdice nezavre, klik mimo panel ano
        self.open_by_key(lp)
        mark = lp.mark()
        self.input.send(f"move {W // 2} 92", "click")
        time.sleep(0.4)
        self.assertFalse(any(l.endswith(" hidden") for l in lp.lines[mark:]))
        self.input.send("move 30 30", "click")
        lp.wait(r" hidden$", start=mark)
        # druhy stisk zkratky zavira (Toggle)
        self.open_by_key(lp)
        mark = lp.mark()
        self.input.send("key super+a")
        lp.wait(r" hidden$", start=mark)

    # ---- vzhled ----

    def test_open_fade_under_pixman(self):
        """Prolnuti panelu pri otevreni (gtk-enable-animations): levne snimky, bez probliknuti."""
        self.start()
        ini = self.session / "config/gtk-3.0/settings.ini"
        ini.write_text(ini.read_text().replace("gtk-enable-animations=false", "gtk-enable-animations=true"))
        lp = self.resident()
        frames = self.session / "frames"
        cap = subprocess.Popen([str(WLT), "capture", str(self.session), str(frames), "30", "2"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        mark = lp.mark()
        self.open_by_key(lp)
        _, m = lp.wait(r" fade frames=(\d+)", start=mark)
        cap.wait(30)
        costs = [int(l.split("us=")[1]) / 1000 for l in lp.lines[mark:] if " fade-frame " in l]
        # pred otevrenim je headless vystup cerny
        r = subprocess.run([str(WLT), "check", "--allow-black", str(frames)], capture_output=True, text=True)
        print(f"\n  prolnuti: {len(costs)} snimku, prvni {costs[0]:.1f} ms, dalsi nejvys {max(costs[1:]):.1f} ms; "
              f"detektor: {r.stdout.strip()}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertGreaterEqual(len(costs), 2)
        self.assertLess(max(costs[1:]), 16)

    def golden_case(self, dark, wallpaper, name):
        self.start(dark=dark, wallpaper=wallpaper)
        lp = self.resident()
        self.open_by_key(lp)
        time.sleep(0.3)
        image = self.shot()
        self.assertEqual(image[:2], (W, H))
        self.compare_golden(name, image)

    def test_golden_light(self):
        self.golden_case(False, "light", "launchpad-light")

    def test_golden_dark(self):
        self.golden_case(True, "dark", "launchpad-dark")

    def test_golden_after_mode_switch(self):
        """Bezici Launchpad po prepnuti rezimu: jako luxos-appearance nejdriv rezim, pak appearance.conf prejmenovanim
        docasneho souboru (monitor hlasi RENAMED) -> sklo z nove tapety jako po startu v tmavem rezimu."""
        self.start(dark=False, wallpaper="light")
        lp = self.resident()
        self.open_by_key(lp)
        self.close_by_key(lp)
        conf = self.session / "config/luxos"
        dark_wall = self.session / "wall-dark.png"
        png_write(dark_wall, 320, 200, gradient(320, 200, (24, 30, 62), (46, 28, 60)))
        (conf / "appearance").write_text("dark\n")
        time.sleep(0.5)
        tmp = conf / "appearance.conf.new.1"
        tmp.write_text(f"WALLPAPER={dark_wall}\n")
        os.replace(tmp, conf / "appearance.conf")
        time.sleep(0.5)
        self.open_by_key(lp)
        time.sleep(0.3)
        self.compare_golden("launchpad-dark", self.shot())

    def test_labels_two_lines_no_hard_cut(self):
        """Nazvy aplikaci LuxOS na prvni strane: nejvys dva radky zalomene mezi slovy, bez vypustky
        (drive "Aktualizace s...", "Klávesové zk...", "Prohlížeč do...")."""
        spec = __import__("importlib.util").util.spec_from_file_location(
            "desktop_i18n", REPO / "packages/luxos-i18n/files/desktop-i18n.py")
        i18n = __import__("importlib.util").util.module_from_spec(spec)
        spec.loader.exec_module(i18n)
        tabs = i18n.load(str(REPO / "packages/luxos-i18n/files"))
        names = set()
        for path in sorted((PKG / "files/applications").glob("*.desktop")):
            text = i18n.translate(path.read_text(encoding="utf-8"), tabs)
            m = re.search(r"^Name\[cs\]=(.*)$", text if isinstance(text, str) else path.read_text(encoding="utf-8"), re.M)
            if m:
                names.add(m.group(1))
        must = ["Aktualizace softwaru", "Klávesové zkratky", "Prohlížeč dokumentů"]
        names = must + sorted(names - set(must), key=len, reverse=True)[:18]
        share = self.tmp / "labels-share"
        (share / "applications").mkdir(parents=True, exist_ok=True)
        if not (share / "icons").exists() and (self.tmp / "share/icons").exists():
            (share / "icons").symlink_to(self.tmp / "share/icons")
        for i, name in enumerate(names):
            (share / "applications" / f"org.example.Label{i:02d}.desktop").write_text(
                f"[Desktop Entry]\nType=Application\nName={name}\nExec=true\nIcon=applications-utilities\nCategories=Utility;\n")
        self.start()
        self.env["XDG_DATA_DIRS"] = str(share)
        lp = self.resident()
        self.open_by_key(lp)
        time.sleep(0.4)
        labels = {}
        for line in lp.lines:
            m = re.search(r" label lines=(\d+) ellipsized=(\d) word=(\d+) width=(\d+) (.*)$", line)
            if m:
                labels[m.group(5)] = [int(v) for v in m.groups()[:4]]
        for name in names:
            with self.subTest(name=name):
                self.assertIn(name, labels, "not drawn on the first page")
                lines, cut, word, width = labels[name]
                self.assertEqual(cut, 0, "ellipsized")
                self.assertLessEqual(lines, 2)
                # kazde slovo se vejde na radek, takze Pango zalamuje jen mezi slovy
                self.assertLessEqual(word, width, "a word is wider than the label")
                self.assertLessEqual(lines, len(name.split(" ")))
        print(f"\n  popisky: {len(names)} nazvu, dvouradkove {sum(1 for n in names if labels[n][0] == 2)}")
        keep = Path(os.environ.get("LUXOS_LAUNCHPAD_SHOTS") or self.tmp.parent / "launchpad-shots")
        keep.mkdir(parents=True, exist_ok=True)
        png_write(keep / "labels.png", *self.shot())

    def test_search_mode_and_cli(self):
        self.start()
        lp = self.resident()
        # Super+Space = luxos-search -> uzky panel se seznamem
        self.open_by_key(lp, "super+space", "search")
        self.type_query(lp, "te")
        time.sleep(0.3)
        self.compare_golden("search", crop(self.shot(), 280, 140, 720, 420))
        self.close_by_key(lp)
        # druhe spusteni programu preda pozadavek bezicimu a skonci
        mark = lp.mark()
        r = subprocess.run([str(self.tmp / "luxos-launchpad"), "--show", "search"], env=self.env, capture_output=True,
                           timeout=10)
        self.assertEqual(r.returncode, 0)
        lp.wait(r" shown mode=search", start=mark)
        mark = lp.mark()
        self.assertEqual(self.gdbus("Hide").returncode, 0)
        lp.wait(r" hidden$", start=mark)
        # jina relace na stejne sbernici (sbernice uzivatele je spolecna vsem jeho relacim): Launchpad
        # teto relace neovlada ani nenahradi, skonci s chybou
        other = self.session / "other-run"
        other.mkdir(mode=0o700, exist_ok=True)
        wayland = self.env["WAYLAND_DISPLAY"]
        if not wayland.startswith("/"):
            wayland = os.path.join(self.env["XDG_RUNTIME_DIR"], wayland)
        mark = lp.mark()
        r = subprocess.run([str(self.tmp / "luxos-launchpad"), "--show", "search"], capture_output=True, timeout=10,
                           env=dict(self.env, XDG_RUNTIME_DIR=str(other), WAYLAND_DISPLAY=wayland))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn(b"another session", r.stderr)
        time.sleep(0.5)
        self.assertNotRegex("\n".join(lp.lines[mark:]), r" shown ")
        self.assertIsNone(lp.proc.poll(), "Launchpad teto relace bezi dal")

    def test_app_index_follows_file_changes(self):
        self.start()
        (self.session / "home/.local/share/applications").mkdir(parents=True)
        lp = self.resident()
        _, m = lp.wait(r" ready pid=\d+ apps=(\d+)")
        n = int(m.group(1))
        self.assertEqual(n, len(VISIBLE))
        user = self.session / "home/.local/share/applications"
        mark = lp.mark()
        (user / "org.example.New.desktop").write_text(f"[Desktop Entry]\nType=Application\nName=Brand New\n"
                                                      f"Exec={self.tmp / 'marker.sh'} new\nIcon=applications-games\n")
        lp.wait(rf" apps {n + 1}$", start=mark, timeout=5)
        self.open_by_key(lp)
        self.assertEqual(self.type_query(lp, "brand")[0], "org.example.New.desktop")
        self.close_by_key(lp)
        mark = lp.mark()
        (user / "org.example.New.desktop").unlink()
        lp.wait(rf" apps {n}$", start=mark, timeout=5)

    @unittest.skipUnless(shutil.which("systemd-analyze"), "chybi systemd-analyze")
    def test_unit_and_dbus_files(self):
        unit = PKG / "files/systemd-user/luxos-launchpad.service"
        r = subprocess.run(["systemd-analyze", "--user", "verify", str(unit)], capture_output=True, text=True)
        # program neni nainstalovany (test bez balicku)
        problems = [l for l in r.stderr.splitlines() if "luxos-launchpad.service:" in l and "is not executable" not in l]
        self.assertEqual(problems, [])
        text = unit.read_text()
        self.assertIn("BusName=cz.luxos.Launchpad", text)
        service = (PKG / "files/dbus-services/cz.luxos.Launchpad.service").read_text()
        self.assertIn("Name=cz.luxos.Launchpad", service)
        self.assertIn("SystemdService=luxos-launchpad.service", service)
        pkgbuild = (PKG / "PKGBUILD").read_text()
        self.assertIn("usr/share/dbus-1/services/cz.luxos.Launchpad.service", pkgbuild)
        self.assertIn("usr/lib/luxos/luxos-launchpad", pkgbuild)


if __name__ == "__main__":
    unittest.main()
