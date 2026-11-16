#!/usr/bin/env python3
"""LuxOS - pojistka testu GUI (scripts/luxos_testguard.py a scripts/luxos-testguard.sh).

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_testguard.py -v

Skutecna obrazovka se tu nikdy nepouzije: "skutecny" DISPLAY napodobuje cislo displeje, na kterem nebezi
zadny X server (pojistka DISPLAY jen cte, nikdy se k nemu nepripojuje). Overuje se, ze pojistka
takovy DISPLAY nahradi vlastnim Xvfb, odebere sbernici skutecne relace a domov / XDG_RUNTIME_DIR
skutecneho uzivatele nahradi docasnymi; virtualni obrazovku testu (Xvfb) ponecha.
"""
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "scripts"))
UID = os.getuid()
REAL_HOME = pwd.getpwuid(UID).pw_dir
PROBE = ("import json, os, sys; sys.path.insert(0, sys.argv[1]); import luxos_testguard; "
         "print(json.dumps({k: os.environ.get(k) for k in ('DISPLAY', 'HOME', 'XDG_RUNTIME_DIR', "
         "'DBUS_SESSION_BUS_ADDRESS', 'XAUTHORITY', 'XDG_CONFIG_HOME')}))")
SH_PROBE = ('. "$1/luxos-testguard.sh"; printf "%s\\n" "${DISPLAY-}" "$HOME" "${XDG_RUNTIME_DIR-}" '
            '"${DBUS_SESSION_BUS_ADDRESS-}" "${XDG_CONFIG_HOME-}"')


def unused_display():
    for n in range(300, 400):
        if not os.path.exists("/tmp/.X11-unix/X%d" % n) and not os.path.exists("/tmp/.X%d-lock" % n):
            return ":%d" % n
    raise RuntimeError("no free display number")


def real_session_env():
    """Prostredi jako ve skutecne relaci uzivatele (jen retezce, nic se nepripojuje)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DISPLAY", "DBUS_", "XAUTHORITY", "XDG_"))}
    env.update(DISPLAY=unused_display(), HOME=REAL_HOME, XDG_RUNTIME_DIR="/run/user/%d" % UID,
               DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/%d/bus" % UID, XAUTHORITY=REAL_HOME + "/.Xauthority",
               XDG_CONFIG_HOME=REAL_HOME + "/.config")
    return env


class Guard(unittest.TestCase):
    def assert_private(self, data, real_display):
        self.assertNotEqual(data["DISPLAY"], real_display)
        if data["DISPLAY"]:
            self.assertTrue(data["DISPLAY"].startswith(":"))
        self.assertFalse(data["HOME"].startswith(REAL_HOME + os.sep) or data["HOME"] == REAL_HOME, data)
        self.assertFalse((data["XDG_RUNTIME_DIR"] or "").startswith("/run/user/"), data)
        self.assertFalse(data["DBUS_SESSION_BUS_ADDRESS"], data)
        self.assertFalse((data["XDG_CONFIG_HOME"] or "").startswith(REAL_HOME), data)

    def test_python_replaces_real_session(self):
        env = real_session_env()
        r = subprocess.run([sys.executable, "-c", PROBE, SCRIPTS], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assert_private(data, env["DISPLAY"])
        self.assertIsNone(data["XAUTHORITY"])

    def test_shell_replaces_real_session(self):
        env = real_session_env()
        r = subprocess.run(["bash", "-c", SH_PROBE, "probe", SCRIPTS], env=env, capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        display, home, runtime, bus, config = r.stdout.split("\n")[:5]
        self.assert_private({"DISPLAY": display, "HOME": home, "XDG_RUNTIME_DIR": runtime,
                             "DBUS_SESSION_BUS_ADDRESS": bus, "XDG_CONFIG_HOME": config}, env["DISPLAY"])

    @unittest.skipUnless(shutil.which("Xvfb"), "Xvfb is not installed")
    def test_own_xvfb_is_kept_and_check_env(self):
        display = unused_display()
        xvfb = subprocess.Popen(["Xvfb", display, "-nolisten", "tcp"], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if os.path.exists("/tmp/.X11-unix/X" + display[1:]):
                    break
                time.sleep(0.05)
            tmp = tempfile.mkdtemp(prefix="luxos-tg-test-")
            self.addCleanup(shutil.rmtree, tmp, True)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("DISPLAY", "DBUS_", "XAUTHORITY"))}
            env.update(DISPLAY=display, HOME=tmp, XDG_RUNTIME_DIR=tmp)
            r = subprocess.run([sys.executable, "-c", PROBE, SCRIPTS], env=env, capture_output=True, text=True,
                               timeout=30)
            self.assertEqual(json.loads(r.stdout)["DISPLAY"], display, r.stderr)
            # check_env: vlastni Xvfb projde, skutecna relace ne
            code = ("import sys; sys.path.insert(0, sys.argv[1]); import luxos_testguard as g; "
                    "g.check_env({'DISPLAY': sys.argv[2]})\n"
                    "try:\n    g.check_env({'DISPLAY': sys.argv[3]})\nexcept g.RealSessionError:\n    print('refused')\n"
                    "try:\n    g.check_env({'HOME': sys.argv[4]})\nexcept g.RealSessionError:\n    print('refused-home')\n")
            r = subprocess.run([sys.executable, "-c", code, SCRIPTS, display, unused_display(), REAL_HOME],
                               env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.stdout.split(), ["refused", "refused-home"], r.stderr)
        finally:
            xvfb.terminate()
            xvfb.wait(5)

    def test_xvfb_of_guard_ends_with_test(self):
        """Vlastni Xvfb pojistky po skonceni testu nezustane bezet."""
        env = real_session_env()
        r = subprocess.run([sys.executable, "-c", PROBE, SCRIPTS], env=env, capture_output=True, text=True, timeout=30)
        own = json.loads(r.stdout)["DISPLAY"]
        if not own:
            self.skipTest("Xvfb is not installed")
        for _ in range(100):
            if not os.path.exists("/tmp/.X11-unix/X" + own[1:]):
                break
            time.sleep(0.05)
        self.assertFalse(os.path.exists("/tmp/.X11-unix/X" + own[1:]), own)


if __name__ == "__main__":
    unittest.main()
