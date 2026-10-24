#!/usr/bin/env python3
"""LuxOS - aplikace Otisk prstu proti napodobene sluzbe fprintd na soukrome D-Bus sbernici.

    xvfb-run -a python3 packages/luxos-desktop/tests/test_luxos_fingerprint.py [--shots DIR]

Spusti vlastni dbus-daemon (session), na nem fingerprint/fake_fprintd.py a aplikaci
s LUXOS_FPRINT_BUS=session. Overuje seznam otisku, pridani s prubehem, chyby snimani,
odebrani, odmitnuti opravneni, obsazenou ctecku a pocitac bez ctecky.
"""
import atexit
import os
import subprocess
import sys
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
FAKE = os.path.join(HERE, "fingerprint", "fake_fprintd.py")
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else ""
if SHOTS:
    del sys.argv[sys.argv.index("--shots"):sys.argv.index("--shots") + 2]

os.environ.update({"LANG": "en_US.UTF-8", "LUXOS_I18N_DIR": I18N})
DBUS = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
# i pri "unittest discover" (bez __main__): vlastni sbernici po testech vzdy ukoncit
atexit.register(DBUS.terminate)
# Aplikace i napodobeny fprintd jdou na tuto sbernici podle adresy - sdilena session sbernice
# procesu (a DBUS_SESSION_BUS_ADDRESS ostatnich testu) zustava beze zmeny
FP_BUS = DBUS.stdout.readline().strip()
os.environ["LUXOS_FPRINT_BUS"] = FP_BUS
sys.path.insert(0, I18N)
app = SourceFileLoader("luxos_fingerprint", os.path.join(FILES, "bin", "luxos-fingerprint")).load_module()
from gi.repository import Gdk, Gtk  # noqa: E402

# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM) - nikdy skutecna obrazovka
HAVE_DISPLAY = Gdk.Display.get_default() is not None and (
    "xvfb-run" in os.environ.get("XAUTHORITY", "") or os.environ.get("LUXOS_TEST_X") == "1")


def pump(sec=0.0, until=None):
    end = time.monotonic() + sec
    while True:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if until and until():
            return True
        if time.monotonic() >= end:
            return bool(until and until())
        time.sleep(0.01)


def shot(win, name):
    if not SHOTS:
        return
    pump(0.2)
    w = win.get_window()
    pb = Gdk.pixbuf_get_from_window(w, 0, 0, w.get_width(), w.get_height())
    os.makedirs(SHOTS, exist_ok=True)
    pb.savev(os.path.join(SHOTS, f"{name}.png"), "png", [], [])


class Unit(unittest.TestCase):
    def test_enroll_messages(self):
        self.assertEqual(app.enroll_message("enroll-stage-passed"),
                         ("Lift your finger, then touch the sensor again", False, False))
        self.assertEqual(app.enroll_message("enroll-stage-passed", swipe=True)[0], "Swipe your finger again")
        self.assertEqual(app.enroll_message("enroll-completed"), ("Fingerprint added", True, False))
        self.assertEqual(app.enroll_message("enroll-retry-scan")[1:], (False, True))
        for r in ("enroll-failed", "enroll-data-full", "enroll-duplicate", "enroll-disconnected",
                  "enroll-unknown-error", "something-new"):
            text, done, err = app.enroll_message(r)
            self.assertTrue(done and err and text, r)

    def test_finger_labels(self):
        self.assertEqual(app.finger_label("right-index-finger"), "Right index finger")
        self.assertEqual(app.finger_label("left-little-finger"), "Left little finger")
        self.assertEqual(app.finger_label("any"), "Any")
        self.assertEqual(len({k for k, _l in app.FINGERS}), 10)


@unittest.skipUnless(HAVE_DISPLAY, "needs X display (xvfb-run)")
class Gui(unittest.TestCase):
    def start(self, *fake_args):
        self.state = tempfile.mktemp(prefix="luxos-fprintd-")
        self.svc = subprocess.Popen([sys.executable, FAKE, "--state", self.state, *fake_args],
                                    stdout=subprocess.PIPE, text=True,
                                    env=dict(os.environ, DBUS_SESSION_BUS_ADDRESS=FP_BUS))
        self.assertEqual(self.svc.stdout.readline().strip(), "ready")
        self.addCleanup(self.stop)
        self.win = app.FingerprintWindow(client=None)
        self.win.show()
        self.addCleanup(self.win.destroy)
        pump(0.05)

    def stop(self):
        self.svc.terminate()
        self.svc.wait(5)
        if os.path.exists(self.state):
            os.remove(self.state)

    def calls(self):
        try:
            with open(self.state, encoding="utf-8") as f:
                return f.read().split("\n")
        except OSError:
            return []

    def page(self):
        return self.win.stack.get_visible_child_name()

    def rows(self):
        out = []
        for row in self.win.group.box.get_children():
            labels = [c.get_text() for c in row.get_children() if isinstance(c, Gtk.Label)]
            out.extend(labels)
        return out

    def wait_main(self):
        self.assertTrue(pump(5, lambda: self.page() == "main"), self.page())
        pump(0.1)

    def test_list_and_enroll(self):
        self.start("--enrolled", "left-thumb", "--stages", "4")
        self.wait_main()
        self.assertEqual(self.rows(), ["Left thumb"])
        self.assertEqual(self.win.reader_label.get_text(), "Fake Sensor 3000")
        shot(self.win, "fingerprint-list")
        self.win.enroll("right-index-finger")
        self.assertEqual(self.page(), "enroll")
        self.assertTrue(pump(3, lambda: self.win.passed == 2))
        self.assertEqual(self.win.enroll_status.get_text(), "Lift your finger, then touch the sensor again")
        self.assertEqual(self.win.enroll_count.get_text(), "Step 3 of 4")
        self.assertAlmostEqual(self.win.ridges.progress, 0.5)
        shot(self.win, "fingerprint-enroll")
        self.assertTrue(pump(3, lambda: self.win.enroll_done.get_visible()))
        self.assertEqual(self.win.enroll_status.get_text(), "Fingerprint added")
        self.assertEqual(self.win.ridges.progress, 1.0)
        self.assertFalse(self.win.enroll_cancel.get_visible())
        shot(self.win, "fingerprint-done")
        pump(0.3)
        c = self.calls()
        self.assertIn("EnrollStart right-index-finger", c)
        self.assertIn("EnrollStop", c)
        self.assertEqual(c.count("Claim "), c.count("Release"), "device released")
        self.win.enroll_done.clicked()
        self.wait_main()
        self.assertEqual(self.rows(), ["Right index finger", "Left thumb"])
        self.assertTrue(self.win.remove_all_btn.get_visible())

    def test_enroll_retry_and_fail(self):
        self.start("--enroll-script", "enroll-stage-passed,enroll-retry-scan,enroll-failed")
        self.wait_main()
        self.assertEqual(self.rows(), ["No fingerprints added yet."])
        self.assertFalse(self.win.remove_all_btn.get_visible())
        self.win.enroll("left-index-finger")
        self.assertTrue(pump(3, lambda: "Didn't catch" in self.win.enroll_status.get_text()))
        self.assertIn("error", self.win.enroll_status.get_style_context().list_classes())
        self.assertTrue(pump(3, lambda: "could not read your finger" in self.win.enroll_status.get_text()))
        self.assertTrue(self.win.enroll_cancel.get_visible())
        self.assertEqual(self.win.enroll_cancel.get_label(), "Back")
        self.assertFalse(self.win.enroll_done.get_visible())
        self.win.enroll_cancel.clicked()
        self.wait_main()
        self.assertEqual(self.rows(), ["No fingerprints added yet."])
        pump(0.2)
        c = self.calls()
        self.assertEqual(c.count("Claim "), c.count("Release"))

    def test_enroll_try_again(self):
        """Po neuspechu tlacitko Zkusit znovu: stejny prst znovu, az po uvolneni ctecky."""
        self.start("--enroll-script", "enroll-failed")
        self.wait_main()
        self.win.enroll("left-index-finger")
        self.assertTrue(pump(3, lambda: self.win.enroll_retry.get_visible() and self.win.enroll_retry.get_sensitive()))
        c = self.calls()
        self.assertEqual(c.count("Claim "), c.count("Release"))
        self.win.enroll_retry.clicked()
        self.assertEqual(self.win.enroll_title.get_text(), "Left index finger")
        self.assertFalse(self.win.enroll_retry.get_visible())
        self.assertEqual(self.win.enroll_cancel.get_label(), "Cancel")
        self.assertTrue(pump(3, lambda: sum(c.startswith("EnrollStart") for c in self.calls()) == 2))
        self.assertTrue(pump(3, lambda: self.win.enroll_retry.get_visible()))

    def test_cancel_enroll(self):
        self.start("--stages", "40")
        self.wait_main()
        self.win.enroll("right-thumb")
        self.assertTrue(pump(2, lambda: self.win.passed >= 1))
        self.win.enroll_cancel.clicked()
        self.wait_main()
        pump(0.3)
        c = self.calls()
        self.assertIn("EnrollStop", c)
        self.assertIn("Release", c)
        self.assertEqual(self.rows(), ["No fingerprints added yet."])

    def test_remove_one_and_all(self):
        self.start("--enrolled", "right-index-finger,left-thumb,right-thumb")
        self.wait_main()
        self.win.confirm = lambda *_a: True
        self.win.on_remove(None, "left-thumb")
        self.assertTrue(pump(3, lambda: "Left thumb" not in self.rows() and not self.win.busy))
        self.assertEqual(self.rows(), ["Right index finger", "Right thumb"])
        self.assertIn("DeleteEnrolledFinger left-thumb", self.calls())
        self.win.on_remove_all(None)
        self.assertTrue(pump(3, lambda: self.rows() == ["No fingerprints added yet."]))
        pump(0.2)
        c = self.calls()
        self.assertEqual(c.count("Claim "), c.count("Release"))
        # zamitnute potvrzeni nic nesmaze
        self.win.confirm = lambda *_a: False
        self.win.on_remove(None, "right-thumb")
        self.assertNotIn("DeleteEnrolledFinger right-thumb", self.calls())

    def test_permission_denied(self):
        self.start("--enrolled", "left-thumb", "--deny-claim")
        self.wait_main()
        self.win.confirm = lambda *_a: True
        self.win.on_remove(None, "left-thumb")
        self.assertTrue(pump(3, lambda: not self.win.busy))
        self.assertEqual(self.win.status.get_text(), "You are not allowed to change fingerprints.")
        self.assertEqual(self.rows(), ["Left thumb"])
        self.win.enroll("right-thumb")
        self.assertTrue(pump(3, lambda: self.win.enroll_cancel.get_label() == "Back"))
        self.assertEqual(self.win.enroll_status.get_text(), "You are not allowed to change fingerprints.")

    def test_reader_busy(self):
        self.start("--busy")
        self.wait_main()
        self.win.enroll("right-thumb")
        self.assertTrue(pump(3, lambda: "another app" in self.win.enroll_status.get_text()))

    def test_no_device(self):
        self.start("--no-device")
        self.assertTrue(pump(5, lambda: self.page() == "message" and self.win.msg_title.get_text()
                             == "No fingerprint reader found"))
        self.assertIn("no supported fingerprint reader", self.win.msg_text.get_text())
        shot(self.win, "fingerprint-no-reader")

    def test_service_missing(self):
        # sluzba neni na sbernici (fprintd nenainstalovany)
        self.win = app.FingerprintWindow(client=None)
        self.addCleanup(self.win.destroy)
        self.win.show()
        self.assertTrue(pump(5, lambda: self.win.msg_title.get_text() == "No fingerprint reader found"))
        self.assertIn("not installed", self.win.msg_text.get_text())


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        DBUS.terminate()
