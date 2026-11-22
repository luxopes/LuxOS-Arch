"""Aplikace spustene ze sluzby shellu (Dock, Launchpad, lista, plocha) bezi ve vlastnim scope systemd (pripominka 44).

Firefox z Docku zustaval v cgroup luxos-dock.service a pod jejim MemoryHigh (96 MB) visel ve stavu D, okno se skoro
nikdy neukazalo. luxos_apps.launch/launch_uri a luxos_glib.spawn_app proto ze sluzby (INVOCATION_ID) spousti
`systemd-run --user --scope --unit=app-luxos-ID-N -- ...`. Tady misto systemd-run zaznam argumentu, ktery prikaz
za "--" spusti; aplikace samy jen zapisi, ze bezi. Skutecne cgroup a okna: scripts/wl-preview/firefox-launch.sh.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      scripts/wl-test/isolate python3 -m unittest packages/luxos-desktop/tests/test_luxos_app_scope.py -v
LUXOS_LSLC: prekladac lslc (jinak lslc z PATH).
"""
import glob
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LSL = os.path.join(HERE, "..", "files", "lsl")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")

FAKE_SYSTEMD_RUN = """#!/bin/sh
echo "$*" >>"$SCOPE_LOG"
while [ "$1" != "--" ]; do shift; done
shift
exec "$@"
"""


@unittest.skipUnless(LSLC and shutil.which("gio"), "chybi lslc (LUXOS_LSLC) nebo gio")
class AppScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxos-app-scope-")
        src = os.path.join(cls.tmp, "lsl")
        os.mkdir(src)
        for f in glob.glob(os.path.join(LSL, "*.lsl")) + [os.path.join(HERE, "lsl", "luxos-app-scope-test.lsl")]:
            shutil.copy(f, src)
        cls.prog = os.path.join(cls.tmp, "app-scope-test")
        r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", src,
                            os.path.join(src, "luxos-app-scope-test.lsl"), cls.prog],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(r.stdout + r.stderr)
        cls.bin = os.path.join(cls.tmp, "bin")
        os.mkdir(cls.bin)
        cls.write(os.path.join(cls.bin, "systemd-run"), FAKE_SYSTEMD_RUN, 0o755)
        # aplikace: zapise svuj nazev a argumenty
        cls.marker_sh = os.path.join(cls.tmp, "marker.sh")
        cls.write(cls.marker_sh, '#!/bin/sh\necho "$*" >>"$APP_MARKER"\n', 0o755)
        apps = os.path.join(cls.tmp, "share", "applications")
        os.makedirs(apps)
        cls.app = os.path.join(apps, "org.example.Test-App.desktop")
        cls.write(cls.app, f"[Desktop Entry]\nType=Application\nName=Test\nExec={cls.marker_sh} app %F\n")
        cls.handler = os.path.join(apps, "luxtest-handler.desktop")
        cls.write(cls.handler, "[Desktop Entry]\nType=Application\nName=Handler\nNoDisplay=true\n"
                  f"MimeType=x-scheme-handler/luxtest;\nExec={cls.marker_sh} uri %u\n")
        cls.dbus_app = os.path.join(apps, "org.example.Bus.desktop")
        cls.write(cls.dbus_app, f"[Desktop Entry]\nType=Application\nName=Bus\nDBusActivatable=true\nExec={cls.marker_sh} bus\n")
        os.makedirs(os.path.join(cls.tmp, "config"))
        cls.write(os.path.join(cls.tmp, "config", "mimeapps.list"),
                  "[Default Applications]\nx-scheme-handler/luxtest=luxtest-handler.desktop\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    @staticmethod
    def write(path, text, mode=0o644):
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)

    def setUp(self):
        self.scope_log = os.path.join(self.tmp, "scope.log")
        self.marker = os.path.join(self.tmp, "marker")
        for f in (self.scope_log, self.marker):
            if os.path.exists(f):
                os.unlink(f)

    def run_prog(self, *args, service=True):
        env = {"PATH": self.bin + ":/usr/bin:/bin", "HOME": self.tmp, "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
               "XDG_DATA_HOME": os.path.join(self.tmp, "share"), "XDG_DATA_DIRS": os.path.join(self.tmp, "share"),
               "XDG_CONFIG_DIRS": os.path.join(self.tmp, "config"), "GIO_USE_VFS": "local",
               "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent", "SCOPE_LOG": self.scope_log, "APP_MARKER": self.marker}
        if service:
            env["INVOCATION_ID"] = "0123456789abcdef0123456789abcdef"
        r = subprocess.run([self.prog, *args], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split()

    def lines(self, path, count):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if os.path.exists(path):
                with open(path) as f:
                    found = f.read().splitlines()
                if len(found) >= count:
                    return found
            time.sleep(0.05)
        self.fail(f"{path}: fewer than {count} lines")

    def test_service_launch_gets_own_scope(self):
        self.assertEqual(self.run_prog("launch", self.app, "launch", self.app), ["ok", "ok"])
        calls = self.lines(self.scope_log, 2)
        unit = r"--user --scope --quiet --collect --unit=app-luxos-org\.example\.Test\\x2dApp-(\d+)_(\d) -- gio launch "
        first = re.fullmatch(unit + re.escape(self.app), calls[0])
        second = re.fullmatch(unit + re.escape(self.app), calls[1])
        self.assertTrue(first and second, calls)
        # jedinecne jmeno jednotky pro kazde spusteni (stejne jmeno by systemd odmitl)
        self.assertEqual(first.group(1), second.group(1))
        self.assertEqual((first.group(2), second.group(2)), ("1", "2"))
        self.assertEqual(self.lines(self.marker, 2), ["app", "app"])

    def test_service_uri_and_command_get_own_scope(self):
        # % v adrese projde beze zmeny (radka GAppInfo ma pravidla Exec, kde % zacina pole)
        self.assertEqual(self.run_prog("uri", "luxtest://a%20b%u", "spawn", self.marker_sh), ["ok", "ok"])
        calls = self.lines(self.scope_log, 2)
        self.assertRegex(calls[0], r"--unit=app-luxos-open-\d+_1 -- gio open luxtest://a%20b%u$")
        self.assertRegex(calls[1], r"--unit=app-luxos-marker\.sh-\d+_2 -- " + re.escape(self.marker_sh) + "$")
        self.assertEqual(sorted(self.lines(self.marker, 2)), ["", "uri luxtest://a%20b%u"])

    def test_outside_service_launches_directly(self):
        self.assertEqual(self.run_prog("launch", self.app, "uri", "luxtest://x", "spawn", self.marker_sh, service=False),
                         ["ok", "ok", "ok"])
        self.assertEqual(sorted(self.lines(self.marker, 3)), ["", "app", "uri luxtest://x"])
        self.assertFalse(os.path.exists(self.scope_log))

    def test_dbus_activatable_not_wrapped(self):
        # spousti ji D-Bus ve vlastni jednotce; bez sbernice se nespusti vubec (ani Exec mimo D-Bus)
        self.run_prog("launch", self.dbus_app)
        time.sleep(0.5)
        self.assertFalse(os.path.exists(self.scope_log))


if __name__ == "__main__":
    unittest.main()
