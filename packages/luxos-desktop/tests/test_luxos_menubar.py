"""Testy pro luxos-menubar: tuknuti na samotnou klavesu Super otevre Launchpad.

Stavovy automat (files/src/luxos-super-tap.h) se testuje harnessem tests/super-tap/harness.c,
cely program pak pod Xvfb (raw udalosti XInput2 z xdotool, falesny luxos-launchpad).

Spusteni:  python3 -m unittest packages/luxos-desktop/tests/test_luxos_menubar.py -v
X cast:    env -u DISPLAY xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_luxos_menubar.py -v
LUXOS_TEST_CFLAGS prida volby prekladace (napr. -I/-L k hlavickam XTest, kdyz chybi v systemu).
"""
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "src")
HARNESS = os.path.join(HERE, "super-tap", "harness.c")
TMP = tempfile.mkdtemp(prefix="luxos-menubar-test-")
CC = shutil.which("gcc") or shutil.which("cc")
EXTRA = shlex.split(os.environ.get("LUXOS_TEST_CFLAGS", ""))
# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM) - nikdy skutecna obrazovka
HAVE_DISPLAY = bool(os.environ.get("DISPLAY")) and (
    "xvfb-run" in os.environ.get("XAUTHORITY", "") or os.environ.get("LUXOS_TEST_X") == "1")

SUPER, SUPER_R, KEY_E, CTRL = 133, 134, 26, 37


def build(name, sources, libs=()):
    out = os.path.join(TMP, name)
    res = subprocess.run([CC, "-O2", "-Wall", "-Wextra", "-Werror", "-o", out, *sources, *EXTRA, *libs],
                         capture_output=True, text=True)
    return out if res.returncode == 0 else res.stderr


@unittest.skipUnless(CC, "chybi prekladac C")
class TapStateMachine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = build("harness", [HARNESS])
        assert os.path.exists(cls.bin), cls.bin

    def run_events(self, text):
        res = subprocess.run([self.bin], input=text, capture_output=True, text=True, check=True)
        return [int(x) for x in res.stdout.split()]

    def test_tap_opens(self):
        self.assertEqual(self.run_events(f"p {SUPER} 1 1000\nr {SUPER} 1 1100\n"), [0, 1])

    def test_right_super(self):
        self.assertEqual(self.run_events(f"p {SUPER_R} 1 1000\nr {SUPER_R} 1 1050\n"), [0, 1])

    def test_limit(self):
        self.assertEqual(self.run_events(f"p {SUPER} 1 1000\nr {SUPER} 1 1400\n"), [0, 1])   # 400 ms jeste ano
        self.assertEqual(self.run_events(f"p {SUPER} 1 1000\nr {SUPER} 1 1401\n"), [0, 0])

    def test_super_combo_never(self):
        # Super+E: E se stiskne i pusti pred Super, nebo az po ni
        self.assertEqual(self.run_events(f"p {SUPER} 1 1000\np {KEY_E} 0 1050\nr {KEY_E} 0 1080\n"
                                         f"r {SUPER} 1 1100\n"), [0, 0, 0, 0])
        self.assertEqual(self.run_events(f"p {SUPER} 1 1000\np {KEY_E} 0 1050\nr {SUPER} 1 1080\n"
                                         f"r {KEY_E} 0 1100\n"), [0, 0, 0, 0])

    def test_modifier_held_before(self):
        # Ctrl drzeny pred Super (Ctrl+Super) - zadne tuknuti, ani po uvolneni Ctrl
        self.assertEqual(self.run_events(f"p {CTRL} 0 1000\np {SUPER} 1 1010\nr {CTRL} 0 1020\n"
                                         f"r {SUPER} 1 1030\n"), [0, 0, 0, 0])

    def test_both_supers(self):
        self.assertEqual(self.run_events(f"p {SUPER} 1 1000\np {SUPER_R} 1 1010\nr {SUPER_R} 1 1020\n"
                                         f"r {SUPER} 1 1030\n"), [0, 0, 0, 0])

    def test_mouse_button_cancels(self):
        # Super+tah mysi (presun okna), Super+kolecko
        self.assertEqual(self.run_events(f"p {SUPER} 1 1000\nb 1050\nr {SUPER} 1 1100\n"), [0, 0, 0])

    def test_autorepeat_keeps_tap(self):
        self.assertEqual(self.run_events(f"p {SUPER} 1 1000\np {SUPER} 1 1030\np {SUPER} 1 1060\n"
                                         f"r {SUPER} 1 1100\n"), [0, 0, 0, 1])

    def test_long_hold_with_repeat(self):
        self.assertEqual(self.run_events(f"p {SUPER} 1 1000\np {SUPER} 1 1300\np {SUPER} 1 1600\n"
                                         f"r {SUPER} 1 1700\n"), [0, 0, 0, 0])

    def test_debounce(self):
        self.assertEqual(self.run_events(f"p {SUPER} 1 1000\nr {SUPER} 1 1050\np {SUPER} 1 1100\n"
                                         f"r {SUPER} 1 1150\np {SUPER} 1 1400\nr {SUPER} 1 1450\n"),
                         [0, 1, 0, 0, 0, 1])

    def test_tap_after_combo(self):
        self.assertEqual(self.run_events(f"p {SUPER} 1 1000\np {KEY_E} 0 1050\nr {KEY_E} 0 1080\n"
                                         f"r {SUPER} 1 1100\np {SUPER} 1 2000\nr {SUPER} 1 2100\n"),
                         [0, 0, 0, 0, 0, 1])

    def test_release_without_press(self):
        # Program spusten pri drzene Super / ztracena udalost: samotne uvolneni nic nespusti
        self.assertEqual(self.run_events(f"r {SUPER} 1 1000\nr {KEY_E} 0 1010\n"), [0, 0])

    def test_sync_stale_key(self):
        # Server hlasi drzenou jinou klavesu (ztracene uvolneni opravi dalsi synchronizace)
        self.assertEqual(self.run_events(f"k {KEY_E} {SUPER}\np {SUPER} 1 1000\nr {SUPER} 1 1050\n"
                                         f"k {SUPER}\np {SUPER} 1 2000\nr {SUPER} 1 2050\n"), [0, 0, 0, 1])

    def test_clock_backwards(self):
        self.assertEqual(self.run_events(f"p {SUPER} 1 1000\nr {SUPER} 1 900\n"), [0, 0])


GRABBER = r"""
#include <X11/Xlib.h>
#include <stdio.h>
#include <unistd.h>
int main(void)
{
    Display *d = XOpenDisplay(NULL);
    if (!d || XGrabKeyboard(d, DefaultRootWindow(d), False, GrabModeAsync, GrabModeAsync, CurrentTime) != GrabSuccess)
        return 1;
    XSync(d, False);
    puts("grabbed");
    fflush(stdout);
    for (;;)
        pause();
}
"""


@unittest.skipUnless(HAVE_DISPLAY and CC and shutil.which("xdotool"), "jen pod xvfb-run s xdotool a gcc")
class Running(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.menubar = build("luxos-menubar", [os.path.join(SRC, "luxos-menubar.c")],
                            ["-lX11", "-lXi", "-lXtst", "-lXrandr", "-lXext"])
        if not os.path.exists(cls.menubar):
            raise unittest.SkipTest("luxos-menubar nejde prelozit: " + cls.menubar[-400:])
        src = os.path.join(TMP, "grabber.c")
        with open(src, "w") as f:
            f.write(GRABBER)
        cls.grabber = build("grabber", [src], ["-lX11"])
        assert os.path.exists(cls.grabber), cls.grabber
        cls.bindir = os.path.join(TMP, "bin")
        os.makedirs(cls.bindir, exist_ok=True)
        cls.marker = os.path.join(TMP, "launchpad.log")
        for name, body in (("luxos-launchpad", f'echo run >> "{cls.marker}"'), ("luxos-displays", "exit 0")):
            p = os.path.join(cls.bindir, name)
            with open(p, "w") as f:
                f.write(f"#!/bin/sh\n{body}\n")
            os.chmod(p, 0o755)
        os.symlink(shutil.which("sleep"), os.path.join(cls.bindir, "rofi"))   # proces jmenem rofi

    def setUp(self):
        self.cfg = tempfile.mkdtemp(dir=TMP)
        os.makedirs(os.path.join(self.cfg, "luxos"))
        if os.path.exists(self.marker):
            os.remove(self.marker)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()

    def start(self, off=False):
        if off:
            open(os.path.join(self.cfg, "luxos", "super-launchpad-off"), "w").close()
        env = dict(os.environ, XDG_CONFIG_HOME=self.cfg, PATH=self.bindir + ":" + os.environ["PATH"])
        self.procs.append(subprocess.Popen([self.menubar], env=env))
        time.sleep(0.4)

    def runs(self, wait=0.5):
        time.sleep(wait)
        try:
            with open(self.marker) as f:
                return len(f.read().split())
        except FileNotFoundError:
            return 0

    def xdo(self, *args):
        subprocess.run(["xdotool", *args], check=True)

    def test_tap_and_combos(self):
        self.start()
        self.xdo("key", "super")
        self.assertEqual(self.runs(), 1)
        self.xdo("key", "super+e")
        self.assertEqual(self.runs(), 1)
        self.xdo("keydown", "ctrl", "key", "super", "keyup", "ctrl")
        self.assertEqual(self.runs(), 1)
        self.xdo("keydown", "super", "sleep", "0.6", "keyup", "super")    # drzena Super
        self.assertEqual(self.runs(), 1)
        self.xdo("keydown", "super", "click", "1", "keyup", "super")      # Super+klik
        self.assertEqual(self.runs(), 1)
        self.xdo("keydown", "super", "click", "5", "keyup", "super")      # Super+kolecko
        self.assertEqual(self.runs(), 1)
        # xdotool posila Super_R spolu se Super_L (modifikator) = dve klavesy, zadne tuknuti;
        # samotna Super_R je overena v TapStateMachine.test_right_super
        self.xdo("key", "Super_R")
        self.assertEqual(self.runs(), 1)
        self.xdo("key", "super")
        self.assertEqual(self.runs(), 2)
        self.xdo("key", "--delay", "40", "super", "super")               # odskok: jen jednou
        self.assertEqual(self.runs(), 3)

    def test_grabbed_keyboard_ignored(self):
        # Zamcena obrazovka / otevrena nabidka drzi grab klavesnice
        self.start()
        g = subprocess.Popen([self.grabber], stdout=subprocess.PIPE, text=True)
        self.procs.append(g)
        self.assertEqual(g.stdout.readline().strip(), "grabbed")
        self.xdo("key", "super")
        self.assertEqual(self.runs(), 0)
        # Otevreny Launchpad (rofi drzi grab): tuknuti ho zavre spustenim luxos-launchpad
        r = subprocess.Popen([os.path.join(self.bindir, "rofi"), "30"])
        self.procs.append(r)
        time.sleep(0.2)
        self.xdo("key", "super")
        self.assertEqual(self.runs(), 1)
        g.kill()
        g.wait()
        r.kill()
        r.wait()
        self.xdo("key", "super")
        self.assertEqual(self.runs(), 2)

    def test_setting_off(self):
        self.start(off=True)
        self.xdo("key", "super")
        self.assertEqual(self.runs(), 0)


if __name__ == "__main__":
    unittest.main()
