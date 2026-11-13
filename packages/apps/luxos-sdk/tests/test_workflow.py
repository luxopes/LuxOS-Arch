"""End-to-end native Studio workflow, without launching the generated GUI.

Set LUXOS_ICON_STUDIO_BIN and LUXOS_APP_STUDIO_BIN to freshly built binaries.
Otherwise the installed commands are used; missing applications skip clearly.
All projects, builds and archives stay in an isolated directory under out/.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PACKAGE = Path(__file__).resolve().parents[1]
ROOT = next((p for p in PACKAGE.parents if (p / "packages/apps").is_dir()), PACKAGE)


def application(variable, command):
    explicit = os.environ.get(variable)
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise AssertionError(f'{variable} does not name an executable: {path}')
        return str(path)
    return shutil.which(command)


class StudioWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.icon = application('LUXOS_ICON_STUDIO_BIN', 'luxos-icon-studio')
        cls.app = application('LUXOS_APP_STUDIO_BIN', 'luxos-app-studio')
        missing = [name for name, path in [('luxos-icon-studio', cls.icon),
                                          ('luxos-app-studio', cls.app),
                                          ('lsl', shutil.which('lsl')),
                                          ('bsdtar', shutil.which('bsdtar'))]
                   if not path]
        if missing:
            raise unittest.SkipTest('Studio workflow requires: ' + ', '.join(missing)
                                    + '; set LUXOS_ICON_STUDIO_BIN and LUXOS_APP_STUDIO_BIN for local builds')
        cls.bsdtar = shutil.which('bsdtar')

    def setUp(self):
        artifacts = ROOT / 'out' / 'studio-sdk-workflow-tests'
        artifacts.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='workflow-', dir=artifacts)
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        for sub in ('home', 'runtime', 'config', 'data', 'cache', 'state'):
            (self.folder / sub).mkdir(mode=0o700)
        # Deliberately construct an environment: no DISPLAY, Wayland socket,
        # session bus, user keyring, portal, agent socket or user PATH entries.
        self.env = dict(PATH='/usr/bin:/bin', HOME=str(self.folder/'home'),
                        XDG_RUNTIME_DIR=str(self.folder/'runtime'),
                        XDG_CONFIG_HOME=str(self.folder/'config'),
                        XDG_DATA_HOME=str(self.folder/'data'),
                        XDG_CACHE_HOME=str(self.folder/'cache'),
                        XDG_STATE_HOME=str(self.folder/'state'), LANG='C.UTF-8',
                        GTK_USE_PORTAL='0', GIO_USE_VFS='local', NO_AT_BRIDGE='1',
                        GSETTINGS_BACKEND='memory', GTK_MODULES='', GTK3_MODULES='')

    def invoke(self, argv, success=True, timeout=120):
        result = subprocess.run([str(value) for value in argv], cwd=self.folder,
                                env=self.env, capture_output=True, text=True, timeout=timeout)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, 'The operation unexpectedly succeeded: ' + result.stdout)
        self.assertNotIn('CRITICAL', result.stderr)
        self.assertNotIn('cannot open display', result.stderr.lower())
        return result

    def test_create_build_design_icon_and_export_installable_native_application(self):
        title = '50% Czech Žluťoučký'
        identity = 'hello-studio'
        project = self.folder / 'My native application'
        self.invoke([self.app, '--new', project, '--name', title,
                     '--id', identity, '--type', 'gtk'])
        self.invoke([self.app, '--build', project])

        artwork = self.folder / 'Aurora.luxicon'
        self.invoke([self.icon, '--new', artwork, 'aurora'])
        icon_member = f'share/icons/hicolor/scalable/apps/{identity}.svg'
        exported_icon = project / 'package' / icon_member
        self.invoke([self.icon, '--render', artwork, exported_icon])
        icon_bytes = exported_icon.read_bytes()
        self.assertIn(b'<svg', icon_bytes)

        destination = self.folder / 'Local exports'
        self.invoke([self.app, '--package', project, destination])
        archives = list(destination.glob('*.lux'))
        self.assertEqual(len(archives), 1, 'One local application package must be produced')
        archive = archives[0]
        self.assertTrue(archive.read_bytes().startswith(b'\x28\xb5\x2f\xfd'), '.lux must use zstd compression')
        members = self.invoke([self.bsdtar, '-tf', archive]).stdout.splitlines()
        executable_member = f'app/{identity}'
        desktop_member = f'share/applications/{identity}.desktop'
        for member in ('lux.json', executable_member, icon_member, desktop_member):
            self.assertIn(member, members)

        metadata = json.loads(self.invoke([self.bsdtar, '-xOf', archive, 'lux.json']).stdout)
        self.assertEqual(metadata['format'], 1)
        self.assertEqual(metadata['name'], identity)
        self.assertEqual(metadata['title'], title)
        self.assertEqual(metadata['bin'][identity], identity)
        self.assertIn('gtk3', metadata['depends']['system'])

        packed_icon = subprocess.run([self.bsdtar, '-xOf', str(archive), icon_member],
                                     cwd=self.folder, env=self.env, capture_output=True, timeout=30)
        self.assertEqual(packed_icon.returncode, 0, packed_icon.stderr)
        self.assertEqual(packed_icon.stdout, icon_bytes, 'The package must contain the actual Icon Studio export')

        desktop = self.invoke([self.bsdtar, '-xOf', archive, desktop_member]).stdout
        values = dict(line.split('=', 1) for line in desktop.splitlines()
                      if '=' in line and not line.startswith('#'))
        self.assertEqual(values['Name'], title, 'Name values keep literal percent characters')
        self.assertNotIn('50%%', desktop)
        self.assertEqual(values['Icon'], identity)
        self.assertEqual(values['Exec'], identity)

        extracted = self.folder/'Extracted executable'; extracted.mkdir()
        self.invoke([self.bsdtar, '-xpf', archive, '--no-same-owner', '-C', extracted, executable_member])
        executable = extracted / executable_member
        self.assertEqual(executable.read_bytes()[:4], b'\x7fELF')
        self.assertEqual(executable.stat().st_mode & 0o777, 0o755)
        # Do not execute the GTK application: build and packaging require no display.

    def test_changed_source_and_failed_build_cannot_export_a_stale_executable(self):
        project = self.folder/'Stale build fixture'
        self.invoke([self.app, '--new', project, '--name', 'Stale build fixture',
                     '--id', 'stale-fixture', '--type', 'gtk'])
        self.invoke([self.app, '--build', project])
        executable = project/'build/stale-fixture'
        original_digest = hashlib.sha256(executable.read_bytes()).digest()
        source = project/'src/main.lsl'
        source.write_text(source.read_text() + '\nthis is deliberately invalid LSL !!!\n')
        destination = self.folder/'Rejected stale export'
        self.invoke([self.app, '--package', project, destination], success=False)
        self.assertFalse(list(destination.glob('*.lux')))
        self.invoke([self.app, '--build', project], success=False)
        self.assertEqual(hashlib.sha256(executable.read_bytes()).digest(), original_digest,
                         'A failed build must preserve the last successful executable')
        self.invoke([self.app, '--package', project, destination], success=False)
        self.assertFalse(list(destination.glob('*.lux')), 'A failed rebuild must never export the old application')


if __name__ == '__main__':
    unittest.main()
