#!/usr/bin/env python3
"""LuxOS - test hlidani zamrzle plochy (luxos-unfreeze, funkce wm_alive).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_unfreeze.py -v

Bez beziciho xfwm4 musi wm_alive hlasit, ze spravce oken nebezi (drive vracela vzdy "bezi").
Nic se nespousti ani neukoncuje: pgrep je nahrazeny skriptem.
"""
import os
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files", "bin", "luxos-unfreeze")


def wm_alive(pgrep_output):
    with tempfile.TemporaryDirectory() as d:
        fake = os.path.join(d, "pgrep")
        with open(fake, "w") as f:
            f.write("#!/bin/sh\n" + (f"echo {pgrep_output}\n" if pgrep_output else "exit 1\n"))
        os.chmod(fake, 0o755)
        code = (f'source <(sed -n "/^wm_alive()/,/^}}/p" "{SCRIPT}"); '
                f'wm_alive && echo alive || echo dead')
        env = dict(os.environ, PATH=d + ":/usr/bin:/bin")
        return subprocess.run(["bash", "-c", code], env=env, capture_output=True, text=True,
                              timeout=10).stdout.strip()


class WmAlive(unittest.TestCase):
    def test_no_window_manager(self):
        self.assertEqual(wm_alive(""), "dead")

    def test_running_process(self):
        self.assertEqual(wm_alive(str(os.getpid())), "alive")

    def test_vanished_process(self):
        self.assertEqual(wm_alive("999999999"), "dead")


if __name__ == "__main__":
    unittest.main()
