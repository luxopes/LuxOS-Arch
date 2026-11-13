"""Native GTK editing exercised only on a private Xvfb display and D-Bus session."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
REPO = next((p for p in PACKAGE.parents if (p / "packages/apps").is_dir()), PACKAGE)


@unittest.skipUnless(all(shutil.which(cmd) for cmd in ('lsl', 'xvfb-run', 'dbus-run-session')), 'native GUI test dependencies unavailable')
class IconStudioGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        output = REPO / 'out'
        output.mkdir(exist_ok=True)
        cls.build = tempfile.TemporaryDirectory(prefix='icon-studio-gui-test-', dir=output)
        cls.folder = Path(cls.build.name)
        cls.binary = cls.folder / 'ui-driver'
        subprocess.run(['lsl', 'compile', '--unsafe', '--target', 'linux-x86_64-gnu',
                        str(PACKAGE / 'files/icon_ui_test.lsl'), str(cls.binary)],
                       check=True, capture_output=True, text=True, timeout=90)
        cls.results = {}
        for locale in ('en', 'cs'):
            artifacts = cls.folder / locale
            artifacts.mkdir()
            with tempfile.TemporaryDirectory(prefix='private-', dir=cls.folder) as private:
                for name in ('home', 'runtime', 'config', 'data', 'cache', 'state'):
                    Path(private, name).mkdir(mode=0o700)
                env = dict(PATH='/usr/bin:/bin', HOME=private+'/home',
                           XDG_RUNTIME_DIR=private+'/runtime', XDG_CONFIG_HOME=private+'/config',
                           XDG_DATA_HOME=private+'/data', XDG_CACHE_HOME=private+'/cache',
                           XDG_STATE_HOME=private+'/state', LANG='C.UTF-8', GDK_BACKEND='x11',
                           GTK_THEME='Adwaita', GTK_MODULES='', GTK3_MODULES='', GTK_USE_PORTAL='0',
                           GIO_USE_VFS='local', NO_AT_BRIDGE='1', GSETTINGS_BACKEND='memory')
                result = subprocess.run(['dbus-run-session', '--', 'xvfb-run', '-a', '-s',
                                         '-screen 0 1600x1100x24', str(cls.binary), str(artifacts), locale],
                                        env=env, text=True, capture_output=True, timeout=40)
                if result.returncode:
                    raise AssertionError(result.stdout + '\n' + result.stderr)
                if result.stderr.strip():
                    raise AssertionError('Unexpected GTK/runtime diagnostics:\n' + result.stderr)
                cls.results[locale] = json.loads(result.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def test_editing_shortcuts_drag_and_undo(self):
        for locale, report in self.results.items():
            for field in ('property_signal', 'undo_signal', 'redo_signal', 'glyph_signal', 'color_signal',
                          'text_signal', 'drag_signal', 'drag_undo', 'duplicate_shortcut', 'undo_shortcut'):
                with self.subTest(locale=locale, field=field):
                    self.assertIs(report[field], True)

    def test_save_roundtrip_and_callback_lifetime(self):
        for locale, report in self.results.items():
            with self.subTest(locale=locale):
                self.assertTrue(report['save_signal'])
                self.assertTrue(report['save_clean'])
                self.assertTrue(report['roundtrip'])
                self.assertEqual(report['handler_growth'], 0)

    def test_native_file_dialogs_and_unsaved_close(self):
        for locale, report in self.results.items():
            for field in ('save_as_dialog', 'save_as_file', 'export_dialog', 'close_cancel', 'close_save'):
                with self.subTest(locale=locale, field=field):
                    self.assertIs(report[field], True)
        self.assertEqual(self.results['en']['close_labels'], ['Cancel', 'Discard changes', 'Save'])
        self.assertEqual(self.results['cs']['close_labels'], ['Zrušit', 'Zahodit změny', 'Uložit'])

    def test_localized_inspector_and_canvas_allocation(self):
        self.assertEqual(self.results['en']['heading'], 'Properties')
        self.assertEqual(self.results['cs']['heading'], 'Vlastnosti')
        for report in self.results.values():
            self.assertGreater(report['allocated'][2], 600)
            self.assertGreater(report['allocated'][3], 350)
