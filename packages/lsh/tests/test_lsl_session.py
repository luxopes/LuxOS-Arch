"""lsh: soubor relace LSL (lsl-session) nikdy s predvidatelnym jmenem v /tmp.

    python3 -m unittest discover -s packages/lsh/tests
"""
import os
import shutil
import subprocess
import tempfile
import unittest

LSHRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files", "lshrc")


def session_function():
    src = open(LSHRC, encoding="utf-8").read()
    start = src.index("\nlsl-session() {") + 1
    return src[start:src.index("\n}\n", start) + 3]


class LslSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lsh-session-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        # lsl nahradi cat: vypise, co by spustil
        with open(os.path.join(self.bin, "lsl"), "w") as f:
            f.write("#!/bin/sh\nexec cat\n")
        os.chmod(os.path.join(self.bin, "lsl"), 0o755)

    def run_shell(self, body, env):
        e = {"PATH": self.bin + ":/usr/bin:/bin", "TMPDIR": self.tmp, **env}
        return subprocess.run(["bash", "-c", session_function() + body], capture_output=True, text=True,
                              env=e, timeout=30)

    def test_without_runtime_dir_private_folder(self):
        # cizi soubor s predvidatelnym jmenem (jako drive /tmp/lsh-lsl-PID.lsl) se nikdy necte
        r = self.run_shell('printf "evil = 1\\n" >"$TMPDIR/lsh-lsl-$$.lsl"\n'
                           'lsl-session run "x = 1" >/dev/null; lsl-session run "print(x)"; echo "F=$_lsh_lsl_file"',
                           {})
        self.assertNotIn("evil", r.stdout)
        self.assertIn("x = 1\nprint(x)", r.stdout)
        f = r.stdout.split("F=")[1].strip()
        d = os.path.dirname(f)
        self.assertTrue(os.path.basename(d).startswith("lsh-lsl."), f)
        self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)

    def test_foreign_runtime_dir_not_used(self):
        # su / sudo -s: XDG_RUNTIME_DIR jineho uzivatele (tady slozka, ktera nam nepatri) se nepouzije
        r = self.run_shell('lsl-session run "x = 1" >/dev/null; echo "F=$_lsh_lsl_file"', {"XDG_RUNTIME_DIR": "/"})
        self.assertFalse(r.stdout.split("F=")[1].startswith("//"), r.stdout)
        own = os.path.join(self.tmp, "run")
        os.mkdir(own, 0o700)
        r = self.run_shell('lsl-session run "x = 1" >/dev/null; echo "F=$_lsh_lsl_file"', {"XDG_RUNTIME_DIR": own})
        self.assertTrue(r.stdout.split("F=")[1].strip().startswith(own + "/lsh-lsl-"), r.stdout)

    def test_show_and_clear(self):
        r = self.run_shell('lsl-session show; lsl-session run "load math" >/dev/null; lsl-session show; '
                           'lsl-session clear; lsl-session show', {})
        self.assertEqual(r.stdout, "lsl-session: empty\nload math\nlsl-session: empty\n")


if __name__ == "__main__":
    unittest.main()
