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


if __name__ == "__main__":
    unittest.main()
