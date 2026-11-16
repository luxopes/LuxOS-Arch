#!/usr/bin/env python3
"""luxos-sandbox-helper: pacstrap mimo relaci uzivatele (limit uloh session scope + zombie gpg z pacstrapu,
stejna chyba jako u instalatoru, audit 1.0.2). Nic se nespousti, jen sestaveni prikazu.
    python3 packages/luxos-sandbox/tests/test_helper_scope.py"""
import os
import sys

sys.dont_write_bytecode = True
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from unittest import mock

HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files", "luxos-sandbox-helper")
h = SourceFileLoader("luxos_sandbox_helper", HELPER).load_module()


class Scope(unittest.TestCase):
    def cg(self, text):
        fd, p = tempfile.mkstemp()
        os.write(fd, text.encode())
        os.close(fd)
        self.addCleanup(os.unlink, p)
        return p

    def test_session_moves_to_system_scope(self):
        with mock.patch.object(h.os.path, "isdir", return_value=True), \
                mock.patch.object(h.shutil, "which", return_value="/usr/bin/systemd-run"):
            cmd = h.outside_session(["pacstrap", "-c"], self.cg("0::/user.slice/user-1000.slice/session-2.scope\n"))
        self.assertEqual(cmd[:6], ["systemd-run", "--quiet", "--scope", "--collect", "--slice=system.slice", "-p"])
        self.assertIn("TasksMax=infinity", cmd)
        self.assertEqual(cmd[-3:], ["--", "pacstrap", "-c"])

    def test_already_outside_or_no_systemd(self):
        with mock.patch.object(h.os.path, "isdir", return_value=True), \
                mock.patch.object(h.shutil, "which", return_value="/usr/bin/systemd-run"):
            self.assertEqual(h.outside_session(["pacstrap"], self.cg("0::/system.slice/x.service\n")), ["pacstrap"])
        with mock.patch.object(h.os.path, "isdir", return_value=False):
            self.assertEqual(h.outside_session(["pacstrap"], self.cg("0::/user.slice/u/session-1.scope\n")),
                             ["pacstrap"])
        self.assertEqual(h.outside_session(["pacstrap"], "/nonexistent"), ["pacstrap"])


if __name__ == "__main__":
    unittest.main()
