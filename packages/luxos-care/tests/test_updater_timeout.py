"""Casovy limit aktualizace nad skutecnymi podprocesy, bez spravce baliku a bez site."""
import os
import shutil
import signal
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "files"))
import luxos_care as care  # noqa: E402


class UpdateTimeout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-update-timeout-")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def command(self, code, timeout=0.2, phase="download", total=0):
        updater = care.Updater()
        with mock.patch.object(care, "have", return_value=False), \
                mock.patch.object(care, "set_progress") as progress:
            rc, text = updater._transact([sys.executable, "-c", code], [], phase, total, None, 0.0, 1.0, timeout)
        self.assertIsNone(updater.proc)
        return rc, text, progress

    def test_silent_command_obeys_timeout(self):
        rc, _text, _progress = self.command("import time; time.sleep(0.6)")
        self.assertEqual(rc, 124)

    def test_partial_line_obeys_timeout_and_is_preserved(self):
        rc, text, _progress = self.command("import time; print('partial', end='', flush=True); time.sleep(0.6)")
        self.assertEqual(rc, 124)
        self.assertIn("partial", text)

    def test_child_holding_output_pipe_is_stopped(self):
        marker = os.path.join(self.tmp, "child-finished")
        child = f"import time; time.sleep(0.6); open({marker!r}, 'w').close()"
        code = f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {child!r}]); print('parent done', flush=True)"
        rc, text, _progress = self.command(code)
        self.assertEqual(rc, 124)
        self.assertIn("parent done", text)
        self.assertFalse(os.path.exists(marker), "casovy limit musi zastavit i potomka drziciho vystupni rouru")

    def test_success_keeps_unicode_output_and_install_progress(self):
        rc, text, progress = self.command(
            "print('upgrading a...'); print('upgrading b...'); print(':: Running post-transaction hooks'); print('žluťoučký')",
            timeout=3, phase="install", total=2)
        self.assertEqual(rc, 0)
        self.assertIn("žluťoučký", text)
        self.assertEqual([c.kwargs["done"] for c in progress.call_args_list if "done" in c.kwargs], [1, 2])
        self.assertEqual(progress.call_args.args[2], "hooks")

    def test_shutdown_interrupts_download_but_leaves_installation_running(self):
        for phase in ("download", "install"):
            with self.subTest(phase=phase):
                updater = care.Updater()
                proc = mock.Mock(luxos_phase=phase)
                proc.poll.return_value = None
                updater.proc = proc
                updater.stop()
                self.assertTrue(updater.stopping)
                if phase == "download":
                    proc.send_signal.assert_called_once_with(signal.SIGINT)
                else:
                    proc.send_signal.assert_not_called()


    def test_ctrl_c_in_terminal_lets_installation_finish(self):
        # sudo luxos-care update + Ctrl-C: proces nesmi skoncit (lux by prisel o rouru uprostred instalace)
        seen = []

        def run_update(up):
            up.proc = mock.Mock(luxos_phase="install")
            up.proc.poll.return_value = None
            os.kill(os.getpid(), signal.SIGINT)
            seen.append(up.stopping)
            up.proc.send_signal.assert_not_called()
            return {"result": "stopped"}
        old = signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)
        lock = mock.MagicMock()
        try:
            with mock.patch.object(care, "load_state", return_value={}), \
                    mock.patch.object(care, "mode", return_value="carefree"), \
                    mock.patch.object(care, "current_env", return_value={}), \
                    mock.patch.object(care, "conditions_ok", return_value=(True, "")), \
                    mock.patch.object(care, "CareLock", return_value=lock), \
                    mock.patch.object(care, "update_state"), mock.patch.object(care, "save_state"), \
                    mock.patch.object(care, "clear_progress"), \
                    mock.patch.object(care, "find_new_configs", return_value=[]), \
                    mock.patch.object(care.Updater, "run_update", run_update):
                self.assertEqual(care.do_update(manual=True), 0)
        finally:
            signal.signal(signal.SIGINT, old[0])
            signal.signal(signal.SIGTERM, old[1])
        self.assertEqual(seen, [True])


if __name__ == "__main__":
    unittest.main()
