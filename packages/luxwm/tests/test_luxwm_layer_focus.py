"""Klavesnice a plochy layer-shell v libluxcomp: keyboard_interactivity on_demand (plocha, nabidky)
a grab xdg_popup (nabidky GTK listy). Harness scripts/wl-test, headless pixman.

  packages/luxwm/tests/build-host.sh
  env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \
    systemd-run --user --scope -p TasksMax=300 -- timeout 900 python3 -m unittest -v packages/luxwm/tests/test_luxwm_layer_focus.py

Plochu dela tests/clients/layer-keys.py (GTK 3 + gtk-layer-shell), okno wlt-client --events.
"""
import os
import signal
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_luxwm_ipc import BUILD, MSG, WLT, Session  # noqa: E402

CLIENT = os.path.join(os.path.dirname(__file__), "clients", "layer-keys.py")
DESKTOP = (100, 720)        # mimo okno 400x300 uprostred 1280x800
WINDOW = (640, 420)


def have_layer_shell():
    r = subprocess.run([sys.executable, "-c", "import gi; gi.require_version('GtkLayerShell', '0.1')"],
                       capture_output=True)
    return r.returncode == 0


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")) and os.path.exists(MSG) and have_layer_shell(),
                     "build first (build-host.sh) and python3-gobject with GtkLayerShell")
class LayerFocus(unittest.TestCase):
    def setUp(self):
        self.s = Session(f"lf{os.getpid() % 10000}{self._testMethodName[5:12]}")
        self.log = os.path.join(self.s.dir, "layer.log")

    def tearDown(self):
        self.s.stop()

    def layer(self, *args):
        with open(self.log, "w") as f:
            p = self.s.spawn(sys.executable, "-u", CLIENT, *args, out=f)
        deadline = time.monotonic() + 8
        while "mapped" not in open(self.log).read():
            self.assertLess(time.monotonic(), deadline, "plocha se nezobrazila")
            time.sleep(0.05)
        time.sleep(0.3)
        return p

    def layer_keys(self):
        return [line.split()[1] for line in open(self.log) if line.startswith("key ")]

    def window_keys(self):
        return [line.split()[1] for line in self.s.clients_log().splitlines()
                if line.startswith("key ") and line.endswith(" down")]

    def type(self, key, at=None):
        # jedna virtualni klavesnice na krok; prvni klavesa nove klavesnice muze GTK ztratit, proto Shift
        cmds = ([f"move {at[0]} {at[1]}", "click"] if at else []) + ["sleep 0.2", "key Shift_L", f"key {key}"]
        self.s.input(*cmds, wait=0.4)

    def test_on_demand_bottom_layer(self):
        self.layer("--layer", "bottom", "--mode", "on_demand")
        self.s.client("Win", app="win")
        self.type("a")
        self.assertEqual(self.window_keys()[-1], "a", "nove okno ma klavesnici, plocha na pozadani ne")
        self.assertNotIn("a", self.layer_keys())
        # klik na plochu: klavesnice plose
        self.type("b", at=DESKTOP)
        self.assertEqual(self.layer_keys()[-1:], ["b"])
        self.assertNotIn("b", self.window_keys())
        # jina vrstva (lista, oznameni) se objevi: plocha si klavesnici necha
        subprocess.run([WLT, "run", self.s.dir,
                        "--bg", "wlt-bar", "--height", "30"], check=True, capture_output=True, timeout=30)
        time.sleep(0.6)
        self.type("c")
        self.assertEqual(self.layer_keys()[-1:], ["c"], "mapovani jine vrstvy klavesnici nebere")
        # klik do (uz zamereneho) okna: klavesnice zpet oknu
        self.type("d", at=WINDOW)
        self.assertEqual(self.window_keys()[-1], "d")
        self.assertNotIn("d", self.layer_keys())
        # plocha, pak nove okno: dostane klavesnici okno
        self.type("e", at=DESKTOP)
        self.assertEqual(self.layer_keys()[-1:], ["e"])
        self.s.client("New", app="new")
        self.type("f")
        self.assertNotIn("f", self.layer_keys(), "nove okno bere klavesnici plose na pozadani")
        self.assertEqual(self.window_keys()[-1], "f")

    def test_on_demand_switched_to_none_returns_keyboard(self):
        p = self.layer("--layer", "background", "--mode", "on_demand")
        self.s.client("Win", app="win")
        self.type("a", at=DESKTOP)
        self.assertEqual(self.layer_keys()[-1:], ["a"])
        p.send_signal(signal.SIGUSR1)
        time.sleep(0.5)
        self.type("b")
        self.assertEqual(self.window_keys()[-1], "b", "plocha bez interaktivity vrati klavesnici oknu")
        self.assertNotIn("b", self.layer_keys())
        # a klik na plochu ji klavesnici uz neda
        self.type("c", at=DESKTOP)
        self.assertNotIn("c", self.layer_keys())

    def test_on_demand_layer_closed_returns_keyboard(self):
        p = self.layer("--layer", "bottom", "--mode", "on_demand")
        self.s.client("Win", app="win")
        self.type("a", at=DESKTOP)
        self.assertEqual(self.layer_keys()[-1:], ["a"])
        p.terminate()
        p.wait(5)
        time.sleep(0.4)
        self.type("b")
        self.assertEqual(self.window_keys()[-1], "b")

    def test_exclusive_layer_keeps_keyboard_over_clicks(self):
        self.s.client("Win", app="win")
        self.layer("--layer", "top", "--mode", "exclusive")
        self.type("a")
        self.assertEqual(self.layer_keys()[-1:], ["a"])
        self.type("b", at=WINDOW)
        self.assertEqual(self.layer_keys()[-1:], ["b"], "exkluzivni vrstva (zamek, spoustec) si klavesnici drzi")
        self.assertNotIn("b", self.window_keys())


if __name__ == "__main__":
    unittest.main()
