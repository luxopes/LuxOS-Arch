#!/usr/bin/env python3
"""LuxOS - aplikace Hodiny (files/lsl/luxos-clock-app.lsl): budik, minutka, jedna instance, beh na pozadi.

    xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_luxos_clock_app.py -v

Vlastni data a sbernice (dbus-run-session), okna jen pod Xvfb. paplay a notify-send jsou napodoby
v PATH, ktere zapisuji volani (zadny skutecny zvuk ani oznameni). Test budiku ceka na dalsi minutu.
"""
import datetime
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "lsl", "luxos-clock-app.lsl")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")
BIN = tempfile.mkdtemp(prefix="luxos-clock-bin-")


def build():
    if not LSLC:
        return False
    r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", SRC, os.path.join(BIN, "luxos-clock-app")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(r.stderr + r.stdout)
    return True


BUILT = build()


@unittest.skipUnless(BUILT, "needs lslc with the linux-x86_64-gnu target")
@unittest.skipUnless(UNDER_XVFB, "GUI only under xvfb-run (never on a real display)")
class ClockApp(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxos-clock-")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.data = os.path.join(self.t, "data")
        self.fake = os.path.join(self.t, "fake")
        self.run_dir = os.path.join(self.t, "run")
        for d in (os.path.join(self.data, "luxos", "clock"), self.fake, self.run_dir):
            os.makedirs(d)
        os.chmod(self.run_dir, 0o700)
        self.log = os.path.join(self.t, "calls")
        for name in ("paplay", "notify-send"):
            p = os.path.join(self.fake, name)
            with open(p, "w") as f:
                f.write('#!/bin/sh\necho "%s $*" >> "$FAKE_LOG"\nsleep 1\n' % name)
            os.chmod(p, 0o755)
        self.env = dict(os.environ, XDG_DATA_HOME=self.data, XDG_RUNTIME_DIR=self.run_dir, FAKE_LOG=self.log,
                        PATH=self.fake + ":" + os.environ["PATH"], LANG="C", GIO_USE_VFS="local",
                        GVFS_DISABLE_FUSE="1", NO_AT_BRIDGE="1")
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            p.wait(timeout=10)
        subprocess.run(["pkill", "-f", "^sh -c while :; do paplay"], capture_output=True)

    def write(self, alarms, cities=()):
        with open(os.path.join(self.data, "luxos", "clock", "clock.json"), "w") as f:
            json.dump({"alarms": alarms, "cities": list(cities)}, f)

    def stored(self):
        with open(os.path.join(self.data, "luxos", "clock", "clock.json")) as f:
            return json.load(f)

    def start(self, *args):
        p = subprocess.Popen([os.path.join(BIN, "luxos-clock-app"), *args], env=self.env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(p)
        return p

    def read(self, path):
        try:
            with open(path) as f:
                return f.read()
        except OSError:
            return ""

    def windows(self, *pattern):
        r = subprocess.run(["xdotool", "search", "--onlyvisible", *pattern], capture_output=True, text=True)
        return r.stdout.split()

    def wait_for(self, check, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            if check():
                return True
            time.sleep(0.1)
        return check()

    def sound_loops(self):
        r = subprocess.run(["pgrep", "-f", "^sh -c while :; do paplay"], capture_output=True, text=True)
        return len(r.stdout.split())

    def test_background_without_alarms_exits(self):
        self.write([{"h": 7, "m": 0, "label": "", "days": [], "on": False}])
        self.assertEqual(self.start("--background").wait(timeout=20), 0)

    def test_single_instance_shows_window(self):
        self.write([{"h": 7, "m": 0, "label": "", "days": [], "on": True}])
        self.start("--background")
        time.sleep(1.5)
        self.assertEqual(self.windows("--class", "luxos-clock-app"), [], "na pozadi bez okna")
        second = self.start()
        self.assertEqual(second.wait(timeout=20), 0, "druhe spusteni jen preda pozadavek")
        self.assertTrue(self.wait_for(lambda: self.windows("--class", "luxos-clock-app")), "bezici instance ukaze okno")

    def test_alarm_rings_once_and_turns_off(self):
        nxt = datetime.datetime.now() + datetime.timedelta(minutes=1)
        self.write([{"h": nxt.hour, "m": nxt.minute, "label": "Test", "days": [], "on": True}])
        self.start("--background")
        self.assertTrue(self.wait_for(lambda: "notify-send" in self.read(self.log), timeout=75), "budik zazvonil")
        self.assertIn("Test", self.read(self.log))
        self.assertTrue(self.wait_for(lambda: self.sound_loops() == 1), "zvuk hraje")
        self.assertFalse(self.stored()["alarms"][0]["on"], "jednorazovy budik se vypne")
        win = self.windows("--name", "^Clock$")
        self.assertTrue(win, "okno zvoneni")
        out = subprocess.run(["xdotool", "getwindowgeometry", "--shell", win[-1]], capture_output=True, text=True).stdout
        g = dict(line.split("=", 1) for line in out.split() if "=" in line)
        x, y, w, h = (int(g[k]) for k in ("X", "Y", "WIDTH", "HEIGHT"))
        # Vypnout je prave tlacitko dole
        subprocess.run(["xdotool", "mousemove", str(x + w // 2 + 44), str(y + h - 62), "click", "1"])
        self.assertTrue(self.wait_for(lambda: self.sound_loops() == 0), "Vypnout zastavi zvuk")


if __name__ == "__main__":
    unittest.main()
