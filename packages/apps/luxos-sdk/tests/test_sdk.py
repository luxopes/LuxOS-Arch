"""Compile the reusable LSL UI module and exercise it on a private X11 display."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = next((p for p in PACKAGE.parents if (p / "packages/apps").is_dir()), PACKAGE)

DRIVER = r'''# lsl: internal-abi
load gtk
load glib
load luxui
load json
load time

state = {"count": 0, "label": 0}
function clicked(button):
    state["count"] += 1
    call gtk.label_set_text(state["label"], "Updated " + String(state["count"]))
end

call gtk.init()
window = luxui.window("SDK integration fixture", 760, 520)
body = luxui.column(16)
call gtk.widget_set_margin(body, 32)
call gtk.container_add(window, body)
call luxui.add(body, luxui.subtitle("BUILT WITH LSL"))
call luxui.add(body, luxui.heading("Make something useful."))
call luxui.add(body, luxui.subtitle("Native components for your next LuxOS application."))
card = luxui.add(body, luxui.card())
state["label"] = luxui.add(card, luxui.label("Ready"))
buttons = luxui.add(card, luxui.row())
button = luxui.add(buttons, luxui.button("Try it", clicked, True))
call gtk.widget_show_all(window)
deadline = time.monotonic() + 0.3
while time.monotonic() < deadline:
    call gtk.pump()
    call time.sleep(0.005)
end
call gtk.button_clicked(button)
call gtk.button_clicked(button)
title = glib.from_c(__lsl_qbe_call1(__lsl_symbol("gtk_window_get_title"), glib.ptr(window)))
print json.encode({"version": luxui.VERSION, "count": state["count"], "label": gtk.label_get_text(state["label"]), "title": title, "width": gtk.widget_get_allocated_width(window), "height": gtk.widget_get_allocated_height(window)})
call gtk.widget_destroy(window)
call gtk.pump()
'''


@unittest.skipUnless(shutil.which('lsl') and shutil.which('xvfb-run'), 'LSL and Xvfb required')
class NativeSdk(unittest.TestCase):
    def test_native_module_compiles_and_buttons_update_state(self):
        build = ROOT / 'out' / 'studio-sdk-tests'
        build.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='sdk-', dir=build) as folder:
            path = Path(folder)
            for sub in ('home', 'runtime', 'config', 'cache', 'data', 'state'):
                (path / sub).mkdir(mode=0o700)
            env = dict(PATH='/usr/bin:/bin', HOME=str(path/'home'),
                       XDG_RUNTIME_DIR=str(path/'runtime'), XDG_CONFIG_HOME=str(path/'config'),
                       XDG_DATA_HOME=str(path/'data'), XDG_CACHE_HOME=str(path/'cache'),
                       XDG_STATE_HOME=str(path/'state'), LANG='C.UTF-8', GTK_THEME='Adwaita',
                       GTK_USE_PORTAL='0', GIO_USE_VFS='local', NO_AT_BRIDGE='1',
                       GSETTINGS_BACKEND='memory', GDK_BACKEND='x11', GTK_MODULES='', GTK3_MODULES='')
            shutil.copy2(PACKAGE/'files/luxui.lsl', path/'luxui.lsl')
            (path/'test.lsl').write_text(DRIVER)
            binary = path/'sdk-test'
            result = subprocess.run(['lsl', 'compile', '--unsafe', '--target', 'linux-x86_64-gnu', str(path/'test.lsl'), str(binary)],
                                    env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(['dbus-run-session', '--', 'xvfb-run', '-a', '-s', '-screen 0 1200x900x24', str(binary)],
                                    env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('CRITICAL', result.stderr)
            self.assertNotIn('callback error', result.stderr)
            self.assertNotIn('Theme parsing error', result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value['version'], '1.0.0')
            self.assertEqual(value['count'], 2)
            self.assertEqual(value['label'], 'Updated 2')
            self.assertEqual(value['title'], 'SDK integration fixture')
            self.assertGreaterEqual(value['width'], 760)
            self.assertGreaterEqual(value['height'], 520)


if __name__ == '__main__':
    unittest.main()
