"""Native App Studio projects, exports and isolated GUI lifecycle."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = next((parent for parent in PACKAGE.parents
             if (parent/'packages/apps').is_dir() and (parent/'out').is_dir()), PACKAGE)
OUT = ROOT / 'out' / 'app-studio-tests'
OUT.mkdir(parents=True, exist_ok=True)


def environment(folder):
    folder = Path(folder)
    for name in ('home', 'runtime', 'config', 'data', 'cache', 'state'):
        (folder / name).mkdir(mode=0o700, exist_ok=True)
    return dict(PATH='/usr/bin:/bin', HOME=str(folder/'home'),
                XDG_RUNTIME_DIR=str(folder/'runtime'), XDG_CONFIG_HOME=str(folder/'config'),
                XDG_DATA_HOME=str(folder/'data'), XDG_CACHE_HOME=str(folder/'cache'),
                XDG_STATE_HOME=str(folder/'state'), LANG='C.UTF-8',
                GDK_BACKEND='x11', GTK_THEME='Adwaita', GTK_USE_PORTAL='0',
                GIO_USE_VFS='local', NO_AT_BRIDGE='1', GSETTINGS_BACKEND='memory')


@unittest.skipUnless(shutil.which('lsl'), 'needs the LSL compiler')
class AppStudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix='build-', dir=OUT)
        cls.binary = Path(os.environ.get('APP_STUDIO_BIN', Path(cls.build.name)/'luxos-app-studio')).resolve()
        if not os.environ.get('APP_STUDIO_BIN'):
            subprocess.run(['lsl', 'compile', '--unsafe', '--target', 'linux-x86_64-gnu',
                            str(PACKAGE/'files/main.lsl'), str(cls.binary)],
                           check=True, capture_output=True, text=True, timeout=120)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix='project-', dir=OUT)
        self.folder = Path(self.work.name)
        self.env = environment(self.folder)

    def tearDown(self):
        self.work.cleanup()

    def cli(self, *args, ok=True, env=None):
        result = subprocess.run([str(self.binary), *map(str, args)], env=env or self.env,
                                capture_output=True, text=True, timeout=45, cwd=self.folder)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def create(self, title='My native application', kind='cli', folder=None, name='native-app'):
        path = folder or self.folder/'my project'
        self.cli('--new', path, '--name', title, '--id', name, '--type', kind)
        return path

    def test_cli_version_and_help_without_display(self):
        self.assertEqual(self.cli('--version').stdout.strip(), '1.0.0')
        self.assertIn('--package', self.cli('--help').stdout)
        self.cli('--unknown', ok=False)
        self.cli('--new', ok=False)

    def test_create_build_run_and_literal_title(self):
        title = '50% "Czech Žluťoučký" $(touch SHOULD_NOT_EXIST)'
        path = self.create(title=title, folder=self.folder/'a project $(literal)')
        metadata = json.loads(self.cli('--inspect', path).stdout)
        self.assertEqual(metadata['title'], title)
        desktop = (path/'package/share/applications/native-app.desktop').read_text()
        self.assertIn('Name='+title+'\n', desktop)
        self.assertNotIn('50%%', desktop)
        value = json.loads(self.cli('--build', path).stdout)
        self.assertTrue(value['ok'])
        result = subprocess.run([str(path/'build/native-app')], env=self.env,
                                capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(result.stdout.splitlines()[0], title)
        self.assertFalse((self.folder/'SHOULD_NOT_EXIST').exists())
        self.assertFalse((path/'SHOULD_NOT_EXIST').exists())
        self.assertFalse((path/'build/native-app.pending').exists())
        self.assertTrue((path/'build/success.json').is_file())

    def test_existing_project_is_never_overwritten(self):
        path = self.folder/'existing'
        path.mkdir()
        sentinel = path/'keep.txt'
        sentinel.write_text('preserve this')
        self.cli('--new', path, ok=False)
        self.assertEqual(sentinel.read_text(), 'preserve this')
        self.assertEqual(list(path.iterdir()), [sentinel])

    def test_invalid_names_titles_and_paths(self):
        for index, name in enumerate(['../escape', 'bad/name', 'Uppercase', '-start', 'x;touch marker', 'x\nname']):
            with self.subTest(name=name):
                path = self.folder/f'invalid-{index}'
                self.cli('--new', path, '--id', name, ok=False)
                self.assertFalse(path.exists())
        self.cli('--new', self.folder/'empty', '--name', '   ', ok=False)
        self.cli('--new', self.folder/'multiline', '--name', 'bad\nName', ok=False)
        self.cli('--new', 'relative-path', ok=False)
        self.cli('--new', self.folder/'../escape', ok=False)
        self.cli('--new', self.folder/'missing-parent/app', ok=False)

    def test_failed_and_stale_build_cannot_export(self):
        path = self.create()
        self.cli('--build', path)
        source = path/'src/main.lsl'
        source.write_text('print "changed"\n')
        self.cli('--package', path, self.folder/'stale', ok=False)
        self.assertFalse((self.folder/'stale').exists())
        source.write_text('bad syntax !!!\n')
        failed = self.cli('--build', path, ok=False)
        self.assertFalse(json.loads(failed.stdout)['ok'])
        self.assertFalse((path/'build/success.json').exists())
        self.cli('--package', path, self.folder/'failed', ok=False)
        source.write_text('print "recovered"\n')
        self.cli('--build', path)
        self.cli('--package', path, self.folder/'recovered')

    def test_imported_source_module_change_invalidates_build(self):
        path = self.create()
        module = path/'src/helper.lsl'
        module.write_text('VALUE = 1\n')
        (path/'src/main.lsl').write_text('load helper\nprint helper.VALUE\n')
        self.cli('--build', path)
        module.write_text('VALUE = 2\n')
        self.cli('--package', path, self.folder/'stale-module', ok=False)

    def test_real_lux_export_archive_and_collision(self):
        import tarfile
        path = self.create(kind='gtk')
        self.cli('--build', path)
        export = self.folder/'exports'
        self.cli('--package', path, export)
        archive = export/'native-app-0.1.0-1-x86_64.lux'
        original = archive.read_bytes()
        raw = subprocess.check_output(['zstd', '-dc', str(archive)])
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            self.assertTrue(all(m.uid == m.gid == 0 for m in tar.getmembers()))
            elf = tar.getmember('app/native-app')
            self.assertEqual(elf.mode & 0o777, 0o755)
            self.assertEqual(tar.extractfile(elf).read(4), b'\x7fELF')
            metadata = json.load(tar.extractfile('lux.json'))
            self.assertIn('gtk3', metadata['depends']['system'])
            self.assertIn('share/applications/native-app.desktop', tar.getnames())
        self.cli('--package', path, export, ok=False)
        self.assertEqual(archive.read_bytes(), original)

    def test_tar_fallback_export_without_lux(self):
        path = self.create()
        self.cli('--build', path)
        tools = self.folder/'tools'
        tools.mkdir()
        for name in ('tar', 'zstd', 'setsid', 'sh'):
            (tools/name).symlink_to(shutil.which(name))
        env = dict(self.env, PATH=str(tools))
        self.cli('--package', path, self.folder/'fallback', env=env)
        archive = self.folder/'fallback/native-app-0.1.0-1-x86_64.lux'
        self.assertTrue(archive.is_file())
        self.cli('--package', path, self.folder/'fallback', ok=False, env=env)

    def test_failed_packager_propagates_exit_and_log(self):
        path = self.create()
        self.cli('--build', path)
        tools = self.folder/'tools'
        tools.mkdir()
        source = tools/'failure.lsl'
        source.write_text('load glib\ncall glib.unbuffered()\nprint "Fixture packager failure"\ncall __lsl_qbe_call1(__lsl_symbol("exit"), 7)\n')
        subprocess.run(['lsl', 'compile', '--unsafe', '--target', 'linux-x86_64-gnu',
                        str(source), str(tools/'lux')],
                       check=True, capture_output=True, text=True, timeout=120)
        result = self.cli('--package', path, self.folder/'failed-packager', ok=False,
                          env=dict(self.env, PATH=str(tools)+':/usr/bin:/bin'))
        self.assertEqual(result.returncode, 7)
        value = json.loads(result.stdout)
        self.assertFalse(value['ok'])
        self.assertIn('Fixture packager failure', value['log'])
        self.assertEqual(list((self.folder/'failed-packager').iterdir()), [])

    def test_build_and_package_directories_reject_symlinks(self):
        path = self.create()
        outside = self.folder/'outside'
        outside.mkdir()
        shutil.rmtree(path/'build')
        (path/'build').symlink_to(outside, target_is_directory=True)
        self.cli('--build', path, ok=False)
        self.assertEqual(list(outside.iterdir()), [])
        (path/'build').unlink()
        self.cli('--build', path)
        shutil.rmtree(path/'package/app')
        (path/'package/app').symlink_to(outside, target_is_directory=True)
        self.cli('--package', path, self.folder/'out', ok=False)
        self.assertEqual(list(outside.iterdir()), [])

    def test_source_symlink_and_corrupt_project_rejected(self):
        path = self.create()
        external = self.folder/'external.lsl'
        external.write_text('print "outside"\n')
        (path/'src/main.lsl').unlink()
        (path/'src/main.lsl').symlink_to(external)
        self.cli('--build', path, ok=False)
        (path/'studio.json').write_text('{')
        self.cli('--inspect', path, ok=False)

    def test_unsupported_package_metadata_rejected(self):
        path = self.create()
        self.cli('--build', path)
        meta = path/'package/lux.json'
        value = json.loads(meta.read_text())
        value['version'] = '../../escape'
        meta.write_text(json.dumps(value))
        self.cli('--package', path, self.folder/'export', ok=False)
        value['version'] = '0.1.0'
        value['release'] = 'x'
        meta.write_text(json.dumps(value))
        self.cli('--package', path, self.folder/'export', ok=False)

    def test_immediate_stop_before_setsid_reaps_child(self):
        source = self.folder/'lifecycle-source'
        source.mkdir()
        shutil.copy2(PACKAGE/'files/studio_native.lsl', source/'studio_native.lsl')
        shutil.copy2(PACKAGE/'tests/lifecycle_driver.lsl', source/'main.lsl')
        binary = self.folder/'lifecycle-driver'
        subprocess.run(['lsl', 'compile', '--unsafe', '--target', 'linux-x86_64-gnu',
                        str(source/'main.lsl'), str(binary)],
                       capture_output=True, text=True, check=True, timeout=120)
        result = subprocess.run([str(binary), str(self.folder)], env=self.env,
                                capture_output=True, text=True, check=True, timeout=15)
        value = json.loads(result.stdout)
        self.assertEqual(value['leaks'], [])
        self.assertLess(value['seconds'], 10)

    def test_terminated_cli_job_reaps_its_child(self):
        import signal
        import time
        source = self.folder/'lifecycle-source'
        source.mkdir()
        shutil.copy2(PACKAGE/'files/studio_native.lsl', source/'studio_native.lsl')
        shutil.copy2(PACKAGE/'tests/lifecycle_driver.lsl', source/'main.lsl')
        binary = self.folder/'lifecycle-driver'
        subprocess.run(['lsl', 'compile', '--unsafe', '--target', 'linux-x86_64-gnu',
                        str(source/'main.lsl'), str(binary)],
                       capture_output=True, text=True, check=True, timeout=120)
        process = subprocess.Popen([str(binary), str(self.folder), 'wait'], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            pid = int(process.stdout.readline())
            time.sleep(.08)
            process.send_signal(signal.SIGTERM)
            output, error = process.communicate(timeout=4)
            self.assertEqual(process.returncode, 0, error)
            self.assertEqual(json.loads(output)['status'], 143)
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=2)

    @unittest.skipUnless(shutil.which('xvfb-run') and shutil.which('dbus-run-session'), 'needs isolated Xvfb and D-Bus')
    def test_gui_build_preview_stale_actions_and_close_cleanup(self):
        source = self.folder/'gui-source'
        shutil.copytree(PACKAGE/'files', source)
        shutil.copy2(PACKAGE/'tests/gui_driver.lsl', source/'gui_driver.lsl')
        binary = self.folder/'gui-driver'
        subprocess.run(['lsl', 'compile', '--unsafe', '--target', 'linux-x86_64-gnu',
                        str(source/'gui_driver.lsl'), str(binary)],
                       capture_output=True, text=True, check=True, timeout=120)
        result = subprocess.run(['dbus-run-session', '--', 'xvfb-run', '-a', '-s',
                                 '-screen 0 1450x1000x24', str(binary), str(self.folder)],
                                env=self.env, capture_output=True, text=True, timeout=50)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('CRITICAL', result.stderr)
        self.assertNotIn('WARNING', result.stderr)
        self.assertNotIn('callback error', result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value['built'])
        self.assertTrue(value['autosaved'], 'editor saves before building')
        self.assertTrue(value['stale_detected'])
        self.assertTrue(value['stale_run_rejected'])
        self.assertTrue(value['errors'], 'compiler errors parsed')
        self.assertEqual(value['errors'][0]['file'], 'src/main.lsl')
        self.assertTrue(value['bar_visible'], 'error bar shown above the editor')
        self.assertTrue(value['ran'], 'Run builds and starts the app')
        self.assertEqual([(e['file'], e['line']) for e in value['runtime_errors']], [('src/main.lsl', 2)],
                         'runtime error of the app is shown like a compiler error')
        self.assertIn('missing_value', value['runtime_errors'][0]['message'])
        self.assertTrue(value['runtime_bar'])
        self.assertFalse(value['child_alive_after_close'])
        self.assertIsNone(value['job'])
        self.assertEqual(value['timer'], 0)

    @unittest.skipUnless(shutil.which('xvfb-run') and shutil.which('dbus-run-session'), 'needs isolated Xvfb and D-Bus')
    def test_gui_czech_narrow_window(self):
        source = self.folder/'gui-source'
        shutil.copytree(PACKAGE/'files', source)
        shutil.copy2(PACKAGE/'tests/gui_driver.lsl', source/'gui_driver.lsl')
        binary = self.folder/'gui-driver'
        subprocess.run(['lsl', 'compile', '--unsafe', '--target', 'linux-x86_64-gnu',
                        str(source/'gui_driver.lsl'), str(binary)],
                       capture_output=True, text=True, check=True, timeout=120)
        env = dict(self.env, LANGUAGE='cs')
        result = subprocess.run(['dbus-run-session', '--', 'xvfb-run', '-a', '-s',
                                 '-screen 0 1450x1000x24', str(binary), str(self.folder), '850'],
                                env=env, capture_output=True, text=True, timeout=50)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('CRITICAL', result.stderr)
        self.assertNotIn('WARNING', result.stderr)
        self.assertNotIn('callback error', result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value['czech'])
        self.assertTrue(value['built'])
        self.assertFalse(value['child_alive_after_close'])


    def test_engine_details_icon_install_errors_and_recent(self):
        source = self.folder/'engine-source'
        shutil.copytree(PACKAGE/'files', source)
        shutil.copy2(PACKAGE/'tests/engine_driver.lsl', source/'engine_driver.lsl')
        binary = self.folder/'engine-driver'
        subprocess.run(['lsl', 'compile', '--unsafe', '--target', 'linux-x86_64-gnu',
                        str(source/'engine_driver.lsl'), str(binary)],
                       capture_output=True, text=True, check=True, timeout=120)
        work = self.folder/'engine'
        work.mkdir()
        result = subprocess.run([str(binary), str(work)], env=self.env, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        v = json.loads(result.stdout)
        # chyby prekladace: soubor projektu relativne, radek, sloupec, zprava bez kodu chyby
        self.assertEqual(v['errors'][0], {'file': 'src/helpers.lsl', 'line': 7, 'column': 12,
                                          'message': 'unknown native variable: y'})
        self.assertEqual(v['errors'][1]['file'], '/elsewhere/x.lsl')
        # udaje aplikace: studio.json, lux.json i .desktop
        self.assertEqual(v['details'], {'title': 'Weather Lite', 'summary': 'Forecast at a glance',
                                        'version': '1.2.0', 'category': 'Graphics'})
        self.assertIn('Name=Weather Lite\n', v['desktop'])
        self.assertIn('Categories=Graphics;\n', v['desktop'])
        self.assertEqual((v['lux']['version'], v['lux']['categories'], v['lux']['description']),
                         ('1.2.0', ['Graphics'], 'Forecast at a glance'))
        self.assertIn('Version', v['bad_version'])
        self.assertIn('Unknown category', v['bad_category'])
        # ikona: SVG ano, falesne PNG a jiny soubor ne
        self.assertTrue(v['icon_svg'].endswith('/scalable/apps/engine-app.svg'))
        self.assertEqual(v['icon_file'], v['icon_svg'])
        self.assertIn('not a PNG', v['icon_fake_png'])
        self.assertIn('SVG or PNG', v['icon_txt'])
        # nove soubory
        self.assertEqual(v['new_source'], 'src/helpers.lsl')
        self.assertIn('already exists', v['new_source_again'])
        self.assertIn('File name', v['new_source_bad'])
        self.assertEqual(v['sources'], ['src/main.lsl', 'src/helpers.lsl'])
        # instalace jen sestavene aplikace, spoustec s uplnou cestou, odinstalace vse smaze
        self.assertIn('Build the application', v['install_unbuilt'])
        self.assertTrue(v['built'])
        home = self.env['HOME']
        data = self.env['XDG_DATA_HOME']
        self.assertEqual(v['installed_files'], [home + '/.local/bin/engine-app',
                                                data + '/applications/engine-app.desktop',
                                                data + '/icons/hicolor/scalable/apps/engine-app.svg'])
        self.assertIn('Exec="' + home + '/.local/bin/engine-app"\n', v['installed_desktop'])
        self.assertTrue(v['installed'])
        self.assertEqual(sorted(v['removed']), sorted(v['installed_files']))
        self.assertFalse(v['installed_after'])
        for path in v['installed_files']:
            self.assertFalse(os.path.exists(path), path)
        # cizi program stejneho jmena zustane
        self.assertIn('already installed', v['foreign'])
        self.assertEqual(v['foreign_kept'], '#!/bin/sh\necho mine\n')
        # nedavne projekty: posledni nahore, bez duplicit
        self.assertEqual([r['title'] for r in v['recent']], ['Weather Lite', 'Other'])


if __name__ == '__main__':
    unittest.main()
