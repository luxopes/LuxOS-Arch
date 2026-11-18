#!/usr/bin/env python3
"""LuxOS - aplikace Hodiny (files/lsl/luxos-clock-app.lsl): budik, minutka, jedna instance, beh na pozadi.

    xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_luxos_clock_app.py -v

Vlastni data a sbernice (dbus-run-session), okna jen pod Xvfb. paplay a notify-send jsou napodoby
v PATH, ktere zapisuji volani (zadny skutecny zvuk ani oznameni). Test budiku ceka na dalsi minutu.
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
SOUNDS = os.path.join(HERE, "..", "files", "sounds", "clock")
ICON = os.path.join(HERE, "..", "files", "icons", "luxos-clock.svg")
CLASSIC = "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"
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
        icons = os.path.join(self.t, "share", "icons", "hicolor", "scalable", "apps")
        for d in (os.path.join(self.data, "luxos", "clock"), self.fake, self.run_dir, icons):
            os.makedirs(d)
        shutil.copy(ICON, icons)       # ikona Hodin ze zdrojovych souboru (v systemu jeste neni)
        os.chmod(self.run_dir, 0o700)
        self.log = os.path.join(self.t, "calls")
        for name in ("paplay", "notify-send"):
            p = os.path.join(self.fake, name)
            with open(p, "w") as f:
                f.write('#!/bin/sh\necho "%s $*" >> "$FAKE_LOG"\nsleep 1\n' % name)
            os.chmod(p, 0o755)
        self.env = dict(os.environ, XDG_DATA_HOME=self.data, XDG_RUNTIME_DIR=self.run_dir, FAKE_LOG=self.log,
                        PATH=self.fake + ":" + os.environ["PATH"], LANG="C", GIO_USE_VFS="local",
                        LUXOS_CLOCK_SOUND_DIR=SOUNDS,
                        XDG_DATA_DIRS=os.path.join(self.t, "share") + ":" + os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share"),
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

    def test_sharp_icon_and_ctrl_w_closes(self):
        self.write([{"h": 7, "m": 0, "label": "", "days": [], "on": False}])
        p = self.start()
        self.assertTrue(self.wait_for(lambda: self.windows("--class", "luxos-clock-app")), "okno")
        win = self.windows("--class", "luxos-clock-app")[0]
        icon = subprocess.run(["xprop", "-id", win, "_NET_WM_ICON"], capture_output=True, text=True).stdout
        for size in ("16 x 16", "32 x 32", "64 x 64", "128 x 128"):
            self.assertIn(f"Icon ({size})", icon, "ostra ikona v Docku a Alt+Tab")
        # je to ikona Hodin LuxOS: nahore uprostred 32px ikony oranzovy prechod
        raw = subprocess.run(["xprop", "-id", win, "-f", "_NET_WM_ICON", "32c", " $0+", "_NET_WM_ICON"],
                             capture_output=True, text=True).stdout
        nums = [int(v) for v in raw.split(" ", 1)[1].replace(",", " ").split()]
        i = 0
        while i < len(nums) and (nums[i], nums[i + 1]) != (32, 32):
            i += 2 + nums[i] * nums[i + 1]
        self.assertLess(i, len(nums), "ikona 32 px")
        argb = nums[i + 2 + 4 * 32 + 16]
        r, g, b = argb >> 16 & 255, argb >> 8 & 255, argb & 255
        self.assertTrue(r > 200 and b < 160 and r > g, ("oranzove pozadi ikony luxos-clock", r, g, b))
        # Esc zavre formular noveho budiku, okno zustane
        subprocess.run(["xdotool", "windowactivate", "--sync", win], capture_output=True)
        subprocess.run(["xdotool", "key", "--window", win, "Escape"])
        time.sleep(0.5)
        self.assertIsNone(p.poll(), "Esc okno nezavira")
        # Ctrl+W zavre okno; bez zapnuteho budiku proces skonci
        subprocess.run(["xdotool", "key", "--window", win, "ctrl+w"])
        self.assertEqual(p.wait(timeout=10), 0)

    def geometry(self, win):
        out = subprocess.run(["xdotool", "getwindowgeometry", "--shell", win], capture_output=True, text=True).stdout
        g = dict(line.split("=", 1) for line in out.split() if "=" in line)
        return [int(g[k]) for k in ("X", "Y", "WIDTH", "HEIGHT")]

    def click(self, x, y):
        subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "1"])
        time.sleep(0.5)

    def test_sound_choice_preview_and_save(self):
        # formular noveho budiku: nahled znelky, vyber jine v seznamu, ulozeni do clock.json
        self.write([])
        self.start()
        self.assertTrue(self.wait_for(lambda: self.windows("--class", "luxos-clock-app")), "okno")
        x, y, w, h = self.geometry(self.windows("--class", "luxos-clock-app")[0])
        self.click(x + w - 38, y + 90)                       # + novy budik
        self.click(x + 420, y + 231)                          # nahled vychozi znelky
        self.assertTrue(self.wait_for(lambda: "paplay " + CLASSIC in self.read(self.log)), "nahled Klasicke")
        self.click(x + 235, y + 231)                          # seznam znelek: Classic -> Sunrise -> Chimes
        for key in ("Down", "Down", "Return"):
            subprocess.run(["xdotool", "key", key])
            time.sleep(0.3)
        self.click(x + 420, y + 231)
        chimes = "paplay " + os.path.join(SOUNDS, "chimes.oga")
        self.assertTrue(self.wait_for(lambda: chimes in self.read(self.log)), "nahled vybrane znelky")
        self.click(x + 403, y + 272)                          # Ulozit
        self.assertTrue(self.wait_for(lambda: len(self.stored()["alarms"]) == 1), "budik ulozen")
        self.assertEqual(self.stored()["alarms"][0]["sound"], "chimes")

    def test_own_sound_from_file(self):
        # "Choose File…" na konci seznamu znelek: kopie souboru mezi vlastni znelky, ulozi se "file:<jmeno>"
        src = os.path.join(self.t, "Moje znelka.oga")
        shutil.copy(os.path.join(SOUNDS, "pulse.oga"), src)
        self.write([])
        self.start()
        self.assertTrue(self.wait_for(lambda: self.windows("--class", "luxos-clock-app")), "okno")
        x, y, w, h = self.geometry(self.windows("--class", "luxos-clock-app")[0])
        self.click(x + w - 38, y + 90)                       # + novy budik
        self.click(x + 235, y + 231)                          # seznam znelek
        for _ in range(6):                                    # 5 vestavenych -> Choose File…
            subprocess.run(["xdotool", "key", "Down"])
            time.sleep(0.15)
        subprocess.run(["xdotool", "key", "Return"])
        self.assertTrue(self.wait_for(lambda: len(self.windows("--class", "luxos-clock-app")) >= 2), "dialog vyberu souboru")
        time.sleep(0.8)
        subprocess.run(["xdotool", "key", "ctrl+l"])
        time.sleep(0.4)
        subprocess.run(["xdotool", "type", "--delay", "20", src])
        time.sleep(0.4)
        subprocess.run(["xdotool", "key", "Return"])
        own = os.path.join(self.data, "luxos", "clock", "sounds", "Moje znelka.oga")
        self.assertTrue(self.wait_for(lambda: os.path.exists(own)), "kopie mezi vlastni znelky")
        time.sleep(0.5)
        self.click(x + 420, y + 231)                          # nahled vlastni znelky
        self.assertTrue(self.wait_for(lambda: "paplay " + own in self.read(self.log)), self.read(self.log))
        self.click(x + 403, y + 272)                          # Ulozit
        self.assertTrue(self.wait_for(lambda: len(self.stored()["alarms"]) == 1), "budik ulozen")
        self.assertEqual(self.stored()["alarms"][0]["sound"], "file:Moje znelka.oga")

    def test_unattended_alarm_goes_quiet(self):
        # bez reakce zvoneni po case utichne (v aplikaci 10 minut, tady 3 s) a proces bez budiku skonci;
        # neznama znelka (napr. ze starsi verze) zazvoni jako Klasicka
        nxt = datetime.datetime.now() + datetime.timedelta(minutes=1)
        self.write([{"h": nxt.hour, "m": nxt.minute, "label": "Away", "days": [], "on": True, "sound": "missing"}])
        self.env["LUXOS_CLOCK_RING_SECONDS"] = "3"
        p = self.start("--background")
        self.assertTrue(self.wait_for(lambda: self.sound_loops() == 1, timeout=75), "zvoni")
        self.assertIn("paplay " + CLASSIC, self.read(self.log))
        # jednorazovy budik se po zazvoneni vypne a ulozi (az po otevreni okna zvoneni)
        self.assertTrue(self.wait_for(lambda: not self.stored()["alarms"][0]["on"]), "budik vypnut a ulozen")
        self.assertEqual(self.stored()["alarms"][0]["sound"], "classic", "neznama znelka se ulozi jako Klasicka")
        self.assertTrue(self.wait_for(lambda: self.sound_loops() == 0, timeout=10), "utichne samo")
        self.assertFalse(self.windows("--name", "^Clock$"), "okno zvoneni zmizi")
        self.assertEqual(p.wait(timeout=10), 0)

    def test_alarm_rings_once_and_turns_off(self):
        nxt = datetime.datetime.now() + datetime.timedelta(minutes=1)
        self.write([{"h": nxt.hour, "m": nxt.minute, "label": "Test", "days": [], "on": True, "sound": "crystal"}])
        self.start("--background")
        self.assertTrue(self.wait_for(lambda: "notify-send" in self.read(self.log), timeout=75), "budik zazvonil")
        self.assertIn("Test", self.read(self.log))
        self.assertTrue(self.wait_for(lambda: self.sound_loops() == 1), "zvuk hraje")
        crystal = "paplay " + os.path.join(SOUNDS, "crystal.oga")
        self.assertTrue(self.wait_for(lambda: crystal in self.read(self.log)), "zvoni zvolena znelka")
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
