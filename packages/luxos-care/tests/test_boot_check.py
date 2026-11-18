"""boot_check: kdy se ceka na display-manager.service (bez systemctl, vystup se podstrci).

    python3 -m unittest discover -s packages/luxos-care/tests -v
"""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "files"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "luxos-i18n", "files"))

import luxos_care as care  # noqa: E402

TARGET_OK = "LoadState=loaded\nActiveState=active\nUnitFileState=static\n"
# skutecny vystup systemctl show pro neexistujici jednotku (ActiveState neni prazdny!)
NOT_FOUND = "LoadState=not-found\nActiveState=inactive\nUnitFileState=\n"


class BootCheck(unittest.TestCase):
    def run_check(self, dm):
        def fake_run(cmd, timeout=600, **_kw):
            if cmd[:2] == ["systemctl", "show"]:
                return 0, dm if cmd[-1] == "display-manager.service" else TARGET_OK
            return 0, ""
        hist = []
        with mock.patch.object(care, "run", fake_run), \
                mock.patch.object(care, "history", lambda *a, **k: hist.append(k)), \
                mock.patch.object(care, "running_kernel", lambda: "6.17.1-luxos1-1"), \
                mock.patch.object(care, "detect_layout", lambda: {"kind": "none", "kernel": "linux-luxos"}), \
                mock.patch.object(care, "installed_version", lambda k: "6.17.1"), \
                mock.patch.object(care, "update_state", lambda **k: None), \
                mock.patch.object(care, "kwrite", lambda *a: None):
            rc = care.boot_check(wait=False)
        return rc, hist

    def test_no_display_manager_unit_is_blessed(self):
        # server, DM vypnuty, nebo DM nespousteny pres alias display-manager.service
        rc, hist = self.run_check(NOT_FOUND)
        self.assertEqual(rc, 0, hist)

    def test_disabled_inactive_display_manager_is_blessed(self):
        rc, _h = self.run_check("LoadState=loaded\nActiveState=inactive\nUnitFileState=disabled\n")
        self.assertEqual(rc, 0)

    def test_enabled_display_manager_must_run(self):
        rc, hist = self.run_check("LoadState=loaded\nActiveState=inactive\nUnitFileState=enabled\n")
        self.assertEqual(rc, 1)
        self.assertEqual(hist[0]["problems"], ["display-manager"])

    def test_failed_display_manager_is_a_problem(self):
        rc, _h = self.run_check("LoadState=loaded\nActiveState=failed\nUnitFileState=disabled\n")
        self.assertEqual(rc, 1)

    def test_running_display_manager_ok(self):
        rc, _h = self.run_check("LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n")
        self.assertEqual(rc, 0)

    def test_unit_state_parses_keys_not_order(self):
        with mock.patch.object(care, "run", lambda *a, **k: (0, "UnitFileState=\nActiveState=failed\n")):
            self.assertEqual(care.unit_state("x.service"), ("failed", ""))
        with mock.patch.object(care, "run", lambda *a, **k: (1, "")):
            self.assertEqual(care.unit_state("x.service"), ("", ""))


if __name__ == "__main__":
    unittest.main()
