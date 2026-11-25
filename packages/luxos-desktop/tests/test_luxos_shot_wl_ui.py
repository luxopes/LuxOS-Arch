"""Logika vyberu Wayland UI; bez displeje a bez relace uzivatele."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
LSL = HERE.parent / 'files/lsl'
LSLC = os.environ.get('LUXOS_LSLC') or shutil.which('lslc')

@unittest.skipUnless(LSLC, 'chybi lslc')
class WaylandSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='shot-wl-ui-')
        cls.bin = Path(cls.tmp.name) / 'probe'
        r = subprocess.run([LSLC, '--target', 'linux-x86_64-gnu', '--system-bindings', str(LSL),
                            str(HERE / 'lsl/luxos-shot-wl-ui-test.lsl'), str(cls.bin)], capture_output=True, text=True)
        if r.returncode:
            cls.tmp.cleanup()
            raise RuntimeError(r.stdout + r.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_probe(self, *args):
        env = {k: v for k, v in os.environ.items() if k not in ('DISPLAY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS')}
        r = subprocess.run([str(self.bin), *map(str, args)], capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_negative_monitor_and_reverse_drag(self):
        self.assertEqual(self.run_probe('norm', '[-100,300,-300,-200]'), [-400, 100, 300, 200])
        self.assertEqual(self.run_probe('norm', '[-800,-50,400,200]'), [-640, 0, 240, 150])
        self.assertIsNone(self.run_probe('norm', '[1500,0,30,30]'))

    def test_default_and_remembered_selection(self):
        self.assertEqual(self.run_probe('reset', 'null', 1), [-160, 200, 960, 400])
        self.assertEqual(self.run_probe('reset', '[-500,20,200,300]', 1), [-500, 20, 200, 300])
        self.assertEqual(self.run_probe('reset', '[4000,20,200,300]', 1), [-160, 200, 960, 400])
        self.assertEqual(self.run_probe('reset', '[-500,20,200,300]', 0), [-160, 200, 960, 400])

    def test_move_stays_in_layout(self):
        self.assertEqual(self.run_probe('drag', '[-500,20,200,300]', '[-450,40]', 'move', -900, -100), [-640, 0, 200, 300])
        self.assertEqual(self.run_probe('drag', '[-500,20,200,300]', '[-450,40]', 'move', 2000, 1500), [1080, 500, 200, 300])

    def test_resize_handles_and_minimum(self):
        self.assertEqual(self.run_probe('drag', '[100,100,200,100]', '[300,200]', 'se', 500, 350), [100, 100, 400, 250])
        self.assertEqual(self.run_probe('drag', '[100,100,200,100]', '[100,100]', 'nw', 500, 500), [297, 197, 3, 3])
        self.assertEqual(self.run_probe('drag', '[100,100,200,100]', '[100,100]', 'nw', -900, -900), [-640, 0, 940, 200])

    def test_spatial_windows_are_front_to_back(self):
        reply = {'ok': True, 'windows': [{'frame': [20, 20, 200, 100]}, {'frame': [0, 0, 500, 400]}, {'frame': [900, 0, 100, 100], 'minimized': True}]}
        self.assertEqual(self.run_probe('windows', json.dumps(reply), 30, 30), [True, 0])
        self.assertEqual(self.run_probe('windows', json.dumps(reply), 300, 30), [True, 1])
        self.assertEqual(self.run_probe('windows', json.dumps(reply), 950, 30), [True, -1])
        self.assertEqual(self.run_probe('windows', '{"ok":true,"windows":[{"title":"old compositor"}]}', 0, 0), [False, -1])

    def test_preview_actions(self):
        self.assertEqual(self.run_probe('actions', '/tmp/shot.png', 0), ['copy', 'reveal', 'save_as', 'delete', 'close'])
        self.assertEqual(self.run_probe('actions', '', 1), ['save_as', 'close'])

    def test_selection_draws_without_callback_errors(self):
        path = Path(self.tmp.name) / 'selection.png'
        self.assertEqual(self.run_probe('selection_image', path), 0)
        from test_luxos_shot_wl import png_read
        w, h, pixels = png_read(path)
        pixel = lambda x, y: pixels[(y * w + x) * 3:(y * w + x + 1) * 3]
        self.assertEqual((w, h), (1280, 800))
        self.assertGreater(sum(pixel(400, 300)), sum(pixel(50, 50)))
        self.assertGreater(min(pixel(200, 150)), 240)
