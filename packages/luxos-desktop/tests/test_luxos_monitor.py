#!/usr/bin/env python3
"""LuxOS - Monitor systemu (files/lsl/luxos-monitor.lsl, luxos_monitor_model.lsl): data z /proc, razeni seznamu
a zapamatovana volba, okno na malych obrazovkach, otevrene aplikace a jejich ukonceni.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_monitor.py -v
    (LUXOS_SHOTS=adresar ulozi snimky okna)

Okno bezi ve vlastnim Xvfb (nikdy skutecna obrazovka), vymyslena data jsou LUXOS_MONITOR_DEMO=1. Otevrene
aplikace a Ukoncit se zkousi jen na oknech a procesech, ktere spustil test (xfwm4 ve stejnem Xvfb jako spravce
oken, jinak se cast preskoci); nic jineho se neukoncuje. Data bez okna (cteni /proc, razeni, nastaveni) testuje
tests/lsl/luxos-monitor-model-test.lsl.
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

SHOTS = os.environ.get("LUXOS_SHOTS", "")
TMP = None
BINARY = None

# Okno pro test Ukoncit: zavre se krizkem, nebo (stuck) zavreni ignoruje
HELPER = r'''import sys, gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk
GLib.set_prgname(sys.argv[1])
w = Gtk.Window(title=sys.argv[1])
w.connect("delete-event", lambda *a: sys.argv[2] == "stuck")
w.connect("destroy", Gtk.main_quit)
w.show_all()
print("READY", flush=True)
Gtk.main()
'''


def setUpModule():
    global TMP, BINARY
    TMP = tempfile.mkdtemp(prefix="luxos-monitor-test.", dir=luxos_testguard._private_dir())
    BINARY = lsl_app.build("luxos-monitor", TMP)


def tearDownModule():
    if TMP:
        shutil.rmtree(TMP, True)


class Model(unittest.TestCase):
    def test_model(self):
        exe = os.path.join(TMP, "model-test")
        r = subprocess.run([os.environ.get("LUXOS_LSLC") or shutil.which("lslc"), "--target", "linux-x86_64-gnu",
                            "--system-bindings", lsl_app.LSL_DIR, os.path.join(HERE, "lsl", "luxos-monitor-model-test.lsl"),
                            exe], capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        work = tempfile.mkdtemp(dir=TMP)
        r = subprocess.run([exe, work], capture_output=True, text=True, timeout=60)
        fails = [line for line in r.stdout.splitlines() if not line.startswith("ok ")]
        self.assertEqual((r.returncode, fails), (0, []), r.stderr)
        self.assertGreater(len(r.stdout.splitlines()), 30)


class Window(unittest.TestCase):
    screen = "1366x768"

    def setUp(self):
        self.xvfb = lsl_app.Xvfb(self.screen)
        self.home = tempfile.mkdtemp(dir=TMP)
        self.app = None
        self.procs = []

    def tearDown(self):
        if self.app:
            self.app.stop()
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
            p.wait(5)
        self.xvfb.stop()

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items()
               if k not in ("WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS") and not k.startswith("LC_")}
        env.update(DISPLAY=self.xvfb.display, HOME=self.home, XDG_CONFIG_HOME=self.home + "/config",
                   XDG_DATA_HOME=self.home + "/data", XDG_CACHE_HOME=self.home + "/cache", LANG="en_US.UTF-8",
                   GTK_THEME="Adwaita", GIO_USE_VFS="local")
        env.update(extra)
        return env

    def open(self, **extra):
        self.app = lsl_app.App([BINARY], self.env(**extra))
        self.assertTrue(self.app.wait(lambda: self.app.dump()), self.app.stderr())
        time.sleep(0.5)

    def state(self):
        return json.loads(self.app.ask("state", "state"))

    def x(self, *argv):
        return subprocess.run(argv, env=self.env(), capture_output=True, text=True, timeout=20).stdout

    def shot(self, name):
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            lsl_app.shot(self.xvfb.display, os.path.join(SHOTS, name + ".png"))

    def visible_size(self):
        """X okno vcetne HeaderBar bez stinu GTK (_GTK_FRAME_EXTENTS)."""
        xid = self.x("xdotool", "search", "--pid", str(self.app.proc.pid), "--onlyvisible", "--name", ".").split()[0]
        w, h = (int(v) for v in self.x("xdotool", "getwindowgeometry", xid).split("Geometry:")[1].split()[0].split("x"))
        ext = self.x("xprop", "-id", xid, "_GTK_FRAME_EXTENTS")
        if "=" in ext:
            l, r, t, b = (int(v) for v in ext.split("=")[1].split(","))
            w, h = w - l - r, h - t - b
        return w, h


class Demo(Window):
    def test_layout_and_data(self):
        self.open(LUXOS_MONITOR_DEMO="1")
        d = self.app.dump()
        self.assertEqual(d[0]["title"], "System Monitor")
        self.assertTrue(d[0]["close_button"])
        labels = lsl_app.texts(d)
        for text in ("Processor", "Memory", "Disk", "Network", "All processes", "Download and upload"):
            self.assertIn(text, labels)
        s = self.state()
        self.assertEqual(s["title"], "Open apps (4)")
        self.assertEqual([r["name"] for r in s["rows"]], ["Celluloid", "Luxos-terminal", "Thunar", "Firefox"])
        self.assertEqual(s["rows"][0]["cpu"], "10.0 %")
        self.assertEqual(s["rows"][0]["mem"], "755 MB")
        self.assertEqual(s["rows"][0]["detail"], "1 process")
        self.assertEqual(s["heads"], {"name": "Name", "cpu": "Processor ▼", "mem": "Memory"})
        self.assertEqual(s["subs"][1], "6.4 GB of 17.2 GB used")
        self.assertEqual(s["subs"][2], "335 GB free · activity 2.0 MB/s")
        self.assertEqual(s["centers"][1], ["38 %", "6.4 GB"])
        # rychlost site zavisi na case mezi obnovami
        self.assertRegex(s["centers"][3][0], r"^↓ [0-9.]+ [KM]B/s$")
        self.assertRegex(s["centers"][3][1], r"^↑ [0-9.]+ [KM]B/s$")
        self.shot("monitor-demo")
        # Quit v demu nic neukoncuje
        self.app.ask("quit firefox")
        self.assertIsNone(self.app.proc.poll())
        self.app.ask("close")
        self.assertEqual(self.app.proc.wait(10), 0)

    def test_czech(self):
        self.open(LUXOS_MONITOR_DEMO="1", LANG="cs_CZ.UTF-8")
        s = self.state()
        self.assertEqual(s["title"], "Otevřené aplikace (4)")
        self.assertEqual(s["rows"][0]["cpu"], "10,0 %")
        self.assertEqual(s["rows"][0]["detail"], "1 proces")
        self.assertEqual(s["subs"][1], "využito 6,4 GB z 17,2 GB")

    def test_sort_is_remembered(self):
        self.open(LUXOS_MONITOR_DEMO="1")
        names = lambda: [r["name"] for r in self.state()["rows"]]  # noqa: E731
        self.app.ask("sort name")
        self.assertEqual(names(), ["Celluloid", "Firefox", "Luxos-terminal", "Thunar"])
        self.assertEqual(self.state()["heads"]["name"], "Name ▲")
        self.app.ask("sort name")
        self.assertEqual(names(), ["Thunar", "Luxos-terminal", "Firefox", "Celluloid"])
        self.app.ask("sort mem")
        self.assertEqual(self.state()["sort"], ["mem", True])
        self.app.ask("sort mem")
        self.assertEqual(names(), ["Firefox", "Thunar", "Luxos-terminal", "Celluloid"])
        with open(os.path.join(self.home, "config/luxos/monitor.conf")) as f:
            self.assertEqual(json.load(f), {"sort": "mem", "descending": False})
        self.app.ask("close")
        self.app.proc.wait(10)
        self.app.stop()
        self.open(LUXOS_MONITOR_DEMO="1")
        s = self.state()
        self.assertEqual(s["sort"], ["mem", False])
        self.assertEqual(s["heads"]["mem"], "Memory ▲")

    def test_all_processes(self):
        self.open(LUXOS_MONITOR_DEMO="1")
        self.app.ask("switch 1")
        s = self.state()
        self.assertEqual(s["title"], "All processes (6)")
        self.assertEqual(len(s["rows"]), 6)
        self.assertRegex(s["rows"][0]["name"], r"^luxos-hub  \(1005, .+\)$")
        self.app.ask("switch 0")
        self.assertEqual(len(self.state()["rows"]), 4)


class SmallScreen(Window):
    """Okno se vejde na 1366x768 i 1280x800 (s okrajem) a nejde zmensit na nepouzitelnou velikost."""

    def check(self):
        self.open(LUXOS_MONITOR_DEMO="1")
        sw, sh = (int(v) for v in self.screen.split("x"))
        w, h = self.visible_size()
        self.assertLessEqual(h, sh - 16, (w, h))
        self.assertLessEqual(w, sw, (w, h))
        self.assertGreaterEqual(h, 420)
        mw, mh = self.state()["min"]
        self.assertGreaterEqual(mh, 300)
        self.assertGreaterEqual(mw, 340)

    def test_1366x768(self):
        self.check()

    def test_1280x800(self):
        self.screen = "1280x800"
        self.xvfb.stop()
        self.xvfb = lsl_app.Xvfb(self.screen)
        self.check()


class Live(Window):
    """Skutecna data: procesy a okna spustena testem, spravce oken xfwm4 ve stejnem Xvfb."""

    def setUp(self):
        super().setUp()
        if not shutil.which("xfwm4"):
            self.skipTest("xfwm4 is missing")
        self.bus = lsl_app.Bus()
        apps = os.path.join(self.home, "data/applications")
        os.makedirs(apps)
        self.bin = os.path.join(self.home, "bin")
        os.makedirs(self.bin)
        for name, title in (("luxos-test-app", "Test App"), ("luxos-test-stuck", "Stuck App")):
            with open(os.path.join(apps, name + ".desktop"), "w") as f:
                f.write("[Desktop Entry]\nType=Application\nName=%s\nExec=%s\nIcon=utilities-terminal\n"
                        "StartupWMClass=%s\n" % (title, name, name))
            with open(os.path.join(self.bin, name), "w") as f:
                f.write("#!%s\n%s" % (sys.executable, HELPER))
            # GIO bere jen .desktop, jehoz program je v PATH
            os.chmod(os.path.join(self.bin, name), 0o755)
        wm = subprocess.Popen(["xfwm4", "--compositor=off", "--sm-client-disable"],
                              env=self.env(DBUS_SESSION_BUS_ADDRESS=self.bus.address),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(wm)
        for _ in range(100):
            if "_NET_SUPPORTING_WM_CHECK(WINDOW)" in self.x("xprop", "-root", "_NET_SUPPORTING_WM_CHECK"):
                break
            time.sleep(0.1)
        else:
            self.skipTest("xfwm4 did not start")

    def tearDown(self):
        super().tearDown()
        self.bus.stop()

    def env(self, **extra):
        env = super().env(**extra)
        if hasattr(self, "bin"):
            env["PATH"] = self.bin + os.pathsep + env["PATH"]
        return env

    def helper(self, name, mode):
        p = subprocess.Popen([os.path.join(self.bin, name), name, mode], env=self.env(),
                             stdout=subprocess.PIPE, text=True)
        self.procs.append(p)
        self.assertEqual(p.stdout.readline().strip(), "READY")
        return p

    def rows(self):
        return {r["name"]: r for r in self.state()["rows"]}

    def test_open_apps_and_quit(self):
        ok = self.helper("luxos-test-app", "ok")
        stuck = self.helper("luxos-test-stuck", "stuck")
        self.open(DBUS_SESSION_BUS_ADDRESS=self.bus.address)
        self.assertTrue(self.app.wait(lambda: {"Test App", "Stuck App"} <= set(self.rows())), self.state())
        self.assertEqual(self.rows()["Test App"]["detail"], "1 process")
        self.shot("monitor-live")
        # okno se zavre jako krizkem (_NET_CLOSE_WINDOW), zadna otazka na vynucene ukonceni
        self.app.ask("quit Test App")
        self.assertEqual(ok.wait(10), 0)
        self.assertTrue(self.app.wait(lambda: "Test App" not in self.rows()))
        # okno, ktere zavreni ignoruje: po 5 s nabidka vynuceneho ukonceni (SIGKILL)
        self.app.ask("quit Stuck App")
        self.assertTrue(self.app.wait(lambda: any(w["dialog"] for w in self.app.dump()), timeout=12))
        d = self.app.dump()
        self.assertIn("Stuck App is not responding", lsl_app.texts(d, dialog=True))
        self.shot("monitor-force-quit")
        self.assertIsNone(stuck.poll())
        self.app.send("click Force Quit")
        self.assertEqual(stuck.wait(10), -9)
        self.assertIsNone(self.app.proc.poll())

    def test_cancel_force_quit_keeps_app(self):
        stuck = self.helper("luxos-test-stuck", "stuck")
        self.open(DBUS_SESSION_BUS_ADDRESS=self.bus.address)
        self.assertTrue(self.app.wait(lambda: "Stuck App" in self.rows()), self.state())
        self.app.ask("quit Stuck App")
        self.assertTrue(self.app.wait(lambda: any(w["dialog"] for w in self.app.dump()), timeout=12))
        self.app.send("click Cancel")
        self.assertTrue(self.app.wait(lambda: not any(w["dialog"] for w in self.app.dump())))
        time.sleep(0.5)
        self.assertIsNone(stuck.poll())

    def test_all_processes_lists_own_process(self):
        self.open(DBUS_SESSION_BUS_ADDRESS=self.bus.address)
        self.app.ask("switch 1")
        s = self.state()
        self.assertTrue(s["title"].startswith("All processes ("))
        pid = self.app.proc.pid
        self.assertTrue(any(r["name"].startswith("luxos-monitor  (%d, " % pid) for r in s["rows"]), s["rows"][:5])
        self.app.ask("refresh")
        self.assertTrue(self.state()["subs"][1].endswith(" used"))


if __name__ == "__main__":
    unittest.main()
