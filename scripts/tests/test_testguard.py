#!/usr/bin/env python3
"""scripts/luxos_testguard.py: vlastni docasna slozka testu neni "skutecna relace", ani kdyz je TMPDIR
v domove (napr. ~/LuxOS-Arch/out); skutecny domov a /run/user/UID dal ano.

    python3 scripts/tests/test_testguard.py
"""
import os
import pwd
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir

PROBE = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
import luxos_testguard as g
real = g._real_path(g._REAL_HOME) and g._real_path(g._REAL_HOME + "/x") and g._real_path(g._REAL_RUNTIME)
print(json.dumps({"home": os.environ["HOME"], "tmp": g._tmp, "real_still_real": bool(real)}))
'''


class TestGuardTmpInHome(unittest.TestCase):
    def run_probe(self, tmpdir):
        env = {"PATH": os.environ.get("PATH", "/usr/bin"), "HOME": REAL_HOME, "TMPDIR": tmpdir,
               "XDG_RUNTIME_DIR": "/run/user/%d" % os.getuid()}
        r = subprocess.run([sys.executable, "-c", PROBE, SCRIPTS], env=env, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        import json
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_tmpdir_inside_home(self):
        # TMPDIR v domove (jako ~/LuxOS-Arch/out pri vyvoji LuxOS): import nesmi selhat
        base = os.environ.get("TMPDIR") or tempfile.gettempdir()
        with tempfile.TemporaryDirectory(dir=base) as tmpdir:
            out = self.run_probe(tmpdir)
            self.assertTrue(out["home"].startswith(os.path.realpath(tmpdir)), out)
            self.assertNotEqual(os.path.realpath(out["home"]), os.path.realpath(REAL_HOME))
            self.assertTrue(out["real_still_real"], "real home/runtime must stay protected")


SYS_PROBE = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
import luxos_testguard as g
out = {"sysbus": os.environ.get("DBUS_SYSTEM_BUS_ADDRESS"), "video": os.environ.get("LUXOS_VIDEO_DEV_DIR"),
       "approved": os.environ.get("LUXOS_TEST_SYSTEM_BUS")}
out["video_empty"] = os.path.isdir(out["video"]) and not os.listdir(out["video"])
# pojistka nesmi pustit otevreni kamery ani pres odkaz; /dev/video999 neexistuje, takze ani pri chybe
# pojistky se zadna skutecna kamera neotevre
link = os.path.join(g._private_dir(), "cam")
os.symlink("/dev/video999", link)
for key, path in (("open_dev", "/dev/video999"), ("open_link", link), ("open_v4l", "/dev/v4l/by-id/x")):
    try:
        open(path, "rb")
        out[key] = "opened"
    except PermissionError as e:
        out[key] = "blocked" if "camera" in str(e) else "perm"
    except OSError:
        out[key] = "oserror"
try:
    os.open("/dev/video999", os.O_RDONLY)
    out["os_open"] = "opened"
except PermissionError:
    out["os_open"] = "blocked"
except OSError:
    out["os_open"] = "oserror"
refused = []
for env in ({"DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/run/dbus/system_bus_socket"},
            {"DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/var/run/dbus/system_bus_socket"},
            {"DBUS_SYSTEM_BUS_ADDRESS": ""},
            {"LUXOS_VIDEO_DEV_DIR": "/dev"}, {"LUXOS_VIDEO_DEV_DIR": "/dev/"}):
    try:
        g.check_env(env)
    except g.RealSessionError:
        refused.append(True)
    else:
        refused.append(False)
out["refused"] = refused
g.check_env({"DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/tmp/fake-sysbus", "LUXOS_VIDEO_DEV_DIR": out["video"]})
out["ok_fake"] = True
print(json.dumps(out))
'''


class TestGuardSystemBusAndCamera(unittest.TestCase):
    """Testy nikdy nesahaji na skutecnou systemovou sbernici (BlueZ, UPower, NM...) ani na kameru."""

    def probe(self, extra):
        env = {"PATH": os.environ.get("PATH", "/usr/bin"), "HOME": REAL_HOME}
        env.update(extra)
        r = subprocess.run([sys.executable, "-c", SYS_PROBE, SCRIPTS], env=env, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        import json
        return json.loads(r.stdout.strip().splitlines()[-1])

    def assert_dead(self, addr):
        self.assertTrue(addr.startswith("unix:path="), addr)
        path = addr[len("unix:path="):]
        self.assertNotIn(path, ("/run/dbus/system_bus_socket", "/var/run/dbus/system_bus_socket"))
        self.assertFalse(os.path.exists(path), path)

    def test_system_bus_dead_by_default(self):
        for start in ({}, {"DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/run/dbus/system_bus_socket"},
                      {"DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/tmp/whatever"}):
            out = self.probe(start)
            self.assert_dead(out["sysbus"])
            self.assertIsNone(out["approved"])

    def test_approved_fake_system_bus(self):
        out = self.probe({"LUXOS_TEST_SYSTEM_BUS": "unix:path=/tmp/luxos-fake-sysbus"})
        self.assertEqual(out["sysbus"], "unix:path=/tmp/luxos-fake-sysbus")
        # skutecny soket ani pres schvalenou promennou neprojde
        for bad in ("unix:path=/run/dbus/system_bus_socket", "tcp:host=127.0.0.1,port=1"):
            out = self.probe({"LUXOS_TEST_SYSTEM_BUS": bad})
            self.assert_dead(out["sysbus"])

    def test_check_env_and_camera(self):
        out = self.probe({"LUXOS_VIDEO_DEV_DIR": "/dev"})
        self.assertFalse(os.path.realpath(out["video"]).startswith("/dev"), out)
        self.assertTrue(out["video_empty"], out)
        self.assertEqual(out["refused"], [True] * 5)
        self.assertTrue(out["ok_fake"])
        for key in ("open_dev", "open_link", "open_v4l", "os_open"):
            self.assertEqual(out[key], "blocked", (key, out))

    def test_shell_guard(self):
        sh = ('. "$1/luxos-testguard.sh"; printf "%s\\n" "$DBUS_SYSTEM_BUS_ADDRESS" "$LUXOS_VIDEO_DEV_DIR" '
              '"${LUXOS_TEST_SYSTEM_BUS-}"; ls -A "$LUXOS_VIDEO_DEV_DIR" | wc -l')
        base = {"PATH": os.environ.get("PATH", "/usr/bin"), "HOME": REAL_HOME}
        for extra, want in (({"DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/run/dbus/system_bus_socket",
                              "LUXOS_VIDEO_DEV_DIR": "/dev"}, None),
                            ({"LUXOS_TEST_SYSTEM_BUS": "unix:path=/run/dbus/system_bus_socket"}, None),
                            ({"LUXOS_TEST_SYSTEM_BUS": "unix:path=/tmp/fake-sb"}, "unix:path=/tmp/fake-sb")):
            r = subprocess.run(["bash", "-c", sh, "x", SCRIPTS], env=dict(base, **extra), capture_output=True,
                               text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            bus, video, approved, count = r.stdout.splitlines()[:4]
            if want:
                self.assertEqual(bus, want)
            else:
                self.assert_dead(bus)
                self.assertEqual(approved, "")
            self.assertFalse(os.path.realpath(video).startswith("/dev"), video)
            self.assertEqual(count.strip(), "0")


class TestCameraNodesFromGuardDir(unittest.TestCase):
    """luxos_camera / luxos-wifi-qr hledaji kamery v LUXOS_VIDEO_DEV_DIR (pojistka: prazdna slozka)."""

    def test_video_nodes(self):
        repo = os.path.dirname(SCRIPTS)
        pydir = os.path.join(repo, "packages", "luxos-desktop", "files", "python")
        with tempfile.TemporaryDirectory() as d:
            for n in ("video10", "video2", "video0", "other"):
                open(os.path.join(d, n), "w").close()
            code = ("import sys; sys.path.insert(0, sys.argv[1]); import luxos_camera as c; "
                    "print('|'.join(c.video_nodes()))")
            env = dict(os.environ, LUXOS_VIDEO_DEV_DIR=d)
            env.pop("LUXOS_CAMERA_TEST", None)
            r = subprocess.run([sys.executable, "-c", code, pydir], env=env, capture_output=True, text=True,
                               timeout=60)
            if r.returncode and "gi" in r.stderr and "No module" in r.stderr:
                self.skipTest("python-gobject missing")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip().split("|"), [os.path.join(d, n) for n in ("video0", "video2", "video10")])
        # aplikace v LSL (QR kod Wi-Fi, Profilova fotka) hledaji uzly tamtez
        for name in ("luxos-wifi-qr.lsl", "luxos_camera.lsl"):
            with open(os.path.join(repo, "packages", "luxos-desktop", "files", "lsl", name)) as f:
                self.assertIn('env.get("LUXOS_VIDEO_DEV_DIR"', f.read(), name)


if __name__ == "__main__":
    unittest.main()
