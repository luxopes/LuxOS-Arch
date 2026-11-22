#!/usr/bin/env python3
"""LuxOS - Otisk prstu (stranka okna Nastaveni files/lsl/luxos_page_fingerprint.lsl, luxos-fingerprint je odkaz
na luxos-settings) proti napodobene sluzbe fprintd na soukrome D-Bus sbernici.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_fingerprint.py -v
    (LUXOS_SHOTS=adresar ulozi snimky okna)

Spusti vlastni Xvfb a dbus-daemon, na nem fingerprint/fake_fprintd.py a aplikaci s LUXOS_FPRINT_BUS=adresa.
Overuje seznam otisku, pridani s prubehem, chyby snimani, odebrani, odmitnuti opravneni, obsazenou ctecku
a pocitac bez ctecky. Skutecna ctecka ani fprintd se nikdy nepouziji. Okno se ridi pres luxos_testctl.
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

FAKE = os.path.join(HERE, "fingerprint", "fake_fprintd.py")
SHOTS = os.environ.get("LUXOS_SHOTS", "")
TMP = None
BINARY = None
XVFB = None


def setUpModule():
    global TMP, BINARY, XVFB
    TMP = tempfile.mkdtemp(prefix="luxos-fp-test.", dir=luxos_testguard._private_dir())
    os.mkdir(os.path.join(TMP, "no-programs"))
    BINARY = lsl_app.build("luxos-fingerprint", TMP)
    XVFB = lsl_app.Xvfb()


def tearDownModule():
    if XVFB:
        XVFB.stop()
    if TMP:
        shutil.rmtree(TMP, True)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.bus = lsl_app.Bus()
        self.state = os.path.join(tempfile.mkdtemp(dir=TMP), "calls")
        self.svc = None
        self.app = None

    def tearDown(self):
        if self.app:
            self.app.stop()
        if self.svc:
            self.svc.terminate()
            self.svc.wait(5)
        self.bus.stop()

    def start(self, *fake_args, fake=True, lang="C.UTF-8", **extra):
        if fake:
            self.svc = subprocess.Popen([sys.executable, FAKE, "--state", self.state, *fake_args],
                                        stdout=subprocess.PIPE, text=True,
                                        env=dict(os.environ, DBUS_SESSION_BUS_ADDRESS=self.bus.address))
            self.assertEqual(self.svc.stdout.readline().strip(), "ready")
        # bez luxos-drivers v PATH (tlacitko Otevrit ovladace by spustilo skutecnou aplikaci)
        env = dict(os.environ, DISPLAY=XVFB.display, LUXOS_FPRINT_BUS=self.bus.address, LANG=lang, LC_ALL=lang,
                   PATH=os.path.join(TMP, "no-programs"), **extra)
        luxos_testguard.check_env(env)
        self.app = lsl_app.App([BINARY], env)
        self.assertTrue(self.app.wait(lambda: self.app.dump()), self.app.stderr())

    def st(self):
        return json.loads(self.app.ask("page-state", "page-state"))

    def page(self):
        return self.st()["page"]

    def text(self, name):
        w = lsl_app.find(self.app.dump(), name=name)
        return None if w is None else w["text"]

    def visible(self, text):
        w = lsl_app.find(self.app.dump(), text=text, kind="GtkButton")
        return w is not None and w["vis"]

    def rows(self):
        return [w["text"] for w in lsl_app.widgets(self.app.dump()) if w.get("name") == "finger-row" and w["vis"]]

    def calls(self):
        try:
            with open(self.state, encoding="utf-8") as f:
                return f.read().split("\n")
        except OSError:
            return []

    def wait(self, cond, timeout=5.0):
        return self.app.wait(cond, timeout)

    def wait_main(self):
        self.assertTrue(self.wait(lambda: self.page() == "main"), self.page())
        time.sleep(0.1)

    def shot(self, name):
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            time.sleep(0.3)
            lsl_app.shot(XVFB.display, os.path.join(SHOTS, name + ".png"))

    def released(self):
        c = self.calls()
        return c.count("Claim ") == c.count("Release")


class Unit(Fixture):
    def test_enroll_messages(self):
        self.start("--no-device")
        msg = lambda r: json.loads(self.app.ask("message " + r, "message"))  # noqa: E731
        self.assertEqual(msg("enroll-stage-passed"), ["Lift your finger, then touch the sensor again", False, False])
        self.assertEqual(msg("enroll-stage-passed swipe")[0], "Swipe your finger again")
        self.assertEqual(msg("enroll-completed"), ["Fingerprint added", True, False])
        self.assertEqual(msg("enroll-retry-scan")[1:], [False, True])
        for r in ("enroll-failed", "enroll-data-full", "enroll-duplicate", "enroll-disconnected",
                  "enroll-unknown-error", "something-new"):
            text, done, err = msg(r)
            self.assertTrue(done and err and text, r)
        # technicky duvod od ctecky jen u neznamych chyb
        self.assertTrue(msg("something-new")[0].endswith("\n(something-new)"))
        self.assertTrue(msg("enroll-failed")[0].endswith("\n(enroll-failed)"))
        self.assertNotIn("(", msg("enroll-duplicate")[0])

    def test_finger_labels(self):
        self.start("--no-device")
        self.assertEqual(self.app.ask("finger right-index-finger", "finger"), "Right index finger")
        self.assertEqual(self.app.ask("finger left-little-finger", "finger"), "Left little finger")
        self.assertEqual(self.app.ask("finger any", "finger"), "Any")
        self.assertEqual(self.app.ask("finger some-new-finger", "finger"), "Some new finger")


class Gui(Fixture):
    def test_list_and_enroll(self):
        self.start("--enrolled", "left-thumb", "--stages", "8")
        self.wait_main()
        d = self.app.dump()
        # titulek okna Nastaveni = titulek stranky
        self.assertEqual([(w["title"], w["close_button"]) for w in d], [("Fingerprint", True)])
        self.assertEqual(self.rows(), ["Left thumb"])
        self.assertEqual(self.text("reader-label"), "Fake Sensor 3000")
        self.assertFalse(self.visible("Remove All"))
        self.shot("fingerprint-list")
        self.app.ask("enroll right-index-finger")
        self.assertEqual(self.page(), "enroll")
        self.assertEqual(self.text("enroll-title"), "Right index finger")
        self.assertTrue(self.wait(lambda: 2 <= self.st()["passed"] < 7))
        # jeden snimek stavu (fprintd posila dalsi kroky kazdych 60 ms)
        st = self.st()
        if st["passed"] < 7:
            self.assertEqual(st["status"], "Lift your finger, then touch the sensor again")
            self.assertEqual(st["count"], "Step %d of 8" % (st["passed"] + 1))
            self.assertAlmostEqual(st["progress"], st["passed"] / 8)
        self.shot("fingerprint-enroll")
        self.assertTrue(self.wait(lambda: self.visible("Done")))
        self.assertEqual(self.text("enroll-status"), "Fingerprint added")
        self.assertEqual(self.st()["progress"], 1.0)
        self.assertFalse(self.visible("Back"))
        self.assertFalse(self.visible("Cancel"))
        self.shot("fingerprint-done")
        self.assertTrue(self.wait(lambda: "EnrollStop" in self.calls() and self.released()))
        self.assertIn("EnrollStart right-index-finger", self.calls())
        self.app.ask("click Done")
        self.wait_main()
        self.assertEqual(self.rows(), ["Right index finger", "Left thumb"])
        self.assertTrue(self.visible("Remove All"))

    def test_add_dialog(self):
        # Pridat otisk: v nabidce jen prsty, ktere jeste nejsou pridane
        self.start("--enrolled", "right-index-finger", "--stages", "40")
        self.wait_main()
        self.app.send("click Add Fingerprint…")
        self.assertTrue(self.wait(lambda: any(w["dialog"] for w in self.app.dump())))
        d = self.app.dump()
        self.assertEqual([w["title"] for w in d if w["dialog"]], ["Add Fingerprint"])
        self.assertIn("Which finger do you want to add?", lsl_app.texts(d, dialog=True))
        self.app.ask("click Continue")
        self.assertTrue(self.wait(lambda: self.page() == "enroll"))
        self.assertEqual(self.text("enroll-title"), "Left index finger")
        self.app.ask("click Cancel")
        self.wait_main()
        self.assertTrue(self.wait(self.released))

    def test_enroll_retry_and_fail(self):
        # mezivysledek (Nezachyceno) vydrzi dele nez jeden vypis okna
        self.start("--enroll-script", "enroll-stage-passed,enroll-retry-scan,enroll-failed", "--step-ms", "1500")
        self.wait_main()
        self.assertEqual(self.rows(), ["No fingerprints added yet."])
        self.assertFalse(self.visible("Remove All"))
        self.app.ask("enroll left-index-finger")
        self.assertTrue(self.wait(lambda: "Didn't catch" in self.text("enroll-status")))
        self.assertTrue(self.st()["enroll_error"])
        self.assertTrue(self.wait(lambda: "could not read your finger" in self.text("enroll-status")))
        self.assertTrue(self.st()["ridges_error"])
        self.assertTrue(self.visible("Back"))
        self.assertFalse(self.visible("Done"))
        self.app.ask("click Back")
        self.wait_main()
        self.assertEqual(self.rows(), ["No fingerprints added yet."])
        self.assertTrue(self.wait(self.released))

    def test_enroll_try_again(self):
        """Po neuspechu tlacitko Zkusit znovu: stejny prst znovu, az po uvolneni ctecky."""
        self.start("--enroll-script", "enroll-failed")
        self.wait_main()
        self.app.ask("enroll left-index-finger")
        try_again = lambda: lsl_app.find(self.app.dump(), text="Try Again")  # noqa: E731
        self.assertTrue(self.wait(lambda: (try_again() or {}).get("vis") and try_again()["sens"]))
        self.assertTrue(self.released())
        self.app.ask("click Try Again")
        self.assertEqual(self.text("enroll-title"), "Left index finger")
        self.assertFalse(self.visible("Try Again"))
        self.assertTrue(self.visible("Cancel"))
        self.assertTrue(self.wait(lambda: sum(c.startswith("EnrollStart") for c in self.calls()) == 2))
        self.assertTrue(self.wait(lambda: self.visible("Try Again")))

    def test_cancel_enroll(self):
        self.start("--stages", "40")
        self.wait_main()
        self.app.ask("enroll right-thumb")
        self.assertTrue(self.wait(lambda: self.st()["passed"] >= 1))
        self.app.ask("click Cancel")
        self.wait_main()
        self.assertTrue(self.wait(lambda: "Release" in self.calls()))
        self.assertIn("EnrollStop", self.calls())
        self.assertEqual(self.rows(), ["No fingerprints added yet."])

    def test_cancel_while_claim_waits(self):
        # Zrusit, zatimco Claim ceka na heslo: po dobehnuti Claim se nesmi zacit snimat a ctecka se uvolni
        self.start("--stages", "40", "--claim-delay", "0.8")
        self.wait_main()
        self.app.ask("enroll right-thumb")
        time.sleep(0.2)
        self.app.ask("click Cancel")
        self.wait_main()
        time.sleep(1.5)
        c = self.calls()
        self.assertNotIn("EnrollStart right-thumb", c)
        self.assertIn("Release", c)

    def test_close_while_enrolling(self):
        # Zavreni okna behem snimani: EnrollStop a uvolneni ctecky, pak konec procesu
        self.start("--stages", "40")
        self.wait_main()
        self.app.ask("enroll right-thumb")
        self.assertTrue(self.wait(lambda: self.st()["passed"] >= 1))
        self.app.send("close")
        self.assertEqual(self.app.proc.wait(10), 0)
        c = self.calls()
        self.assertIn("EnrollStop", c)
        self.assertIn("Release", c)

    def test_remove_one_and_all(self):
        self.start("--enrolled", "right-index-finger,left-thumb,right-thumb")
        self.wait_main()
        self.assertEqual(self.rows(), ["Right index finger", "Right thumb", "Left thumb"])
        # Odebrat u Leveho palce: potvrzovaci dialog
        remove = [w for w in lsl_app.widgets(self.app.dump()) if w["t"] == "GtkButton" and w["text"] == "Remove"]
        self.assertEqual(len(remove), 3)
        self.app.send("remove left-thumb")
        self.assertTrue(self.wait(lambda: "Remove the fingerprint “Left thumb”?" in lsl_app.texts(self.app.dump(), dialog=True)))
        self.app.ask("respond -5")
        self.assertTrue(self.wait(lambda: "Left thumb" not in self.rows() and not self.st()["busy"]))
        self.assertEqual(self.rows(), ["Right index finger", "Right thumb"])
        self.assertIn("DeleteEnrolledFinger left-thumb", self.calls())
        self.app.send("click Remove All")
        self.assertTrue(self.wait(lambda: "Remove all fingerprints?" in lsl_app.texts(self.app.dump(), dialog=True)))
        self.app.ask("click Remove")
        self.assertTrue(self.wait(lambda: self.rows() == ["No fingerprints added yet."]))
        self.assertTrue(self.wait(self.released))
        self.assertIn("DeleteEnrolledFingers2", self.calls())

    def test_remove_cancelled(self):
        # zamitnute potvrzeni nic nesmaze
        self.start("--enrolled", "right-thumb")
        self.wait_main()
        self.app.send("click Remove")
        self.assertTrue(self.wait(lambda: any(w["dialog"] for w in self.app.dump())))
        self.app.ask("click Cancel")
        time.sleep(0.3)
        self.assertNotIn("DeleteEnrolledFinger right-thumb", self.calls())
        self.assertNotIn("Claim ", self.calls())
        self.assertEqual(self.rows(), ["Right thumb"])

    def test_permission_denied(self):
        self.start("--enrolled", "left-thumb", "--deny-claim")
        self.wait_main()
        self.app.send("click Remove")
        self.assertTrue(self.wait(lambda: any(w["dialog"] for w in self.app.dump())))
        self.app.ask("respond -5")
        self.assertTrue(self.wait(lambda: self.text("status") == "You are not allowed to change fingerprints."))
        self.assertTrue(self.st()["status_error"])
        self.assertFalse(self.st()["busy"])
        self.assertEqual(self.rows(), ["Left thumb"])
        self.app.ask("enroll right-thumb")
        self.assertTrue(self.wait(lambda: self.visible("Back")))
        self.assertEqual(self.text("enroll-status"), "You are not allowed to change fingerprints.")

    def test_reader_busy(self):
        self.start("--busy")
        self.wait_main()
        self.app.ask("enroll right-thumb")
        self.assertTrue(self.wait(lambda: "another app" in self.text("enroll-status")))

    def test_no_device(self):
        self.start("--no-device")
        self.assertTrue(self.wait(lambda: self.page() == "message" and self.text("msg-title") == "No fingerprint reader found"))
        self.assertIn("no supported fingerprint reader", self.text("msg-text"))
        # bez luxos-drivers v PATH zadne tlacitko
        self.assertFalse(self.visible("Open Drivers"))
        self.shot("fingerprint-no-reader")

    def test_service_missing(self):
        # sluzba neni na sbernici (fprintd nenainstalovany)
        self.start(fake=False)
        self.assertTrue(self.wait(lambda: self.text("msg-title") == "No fingerprint reader found"))
        self.assertIn("not installed", self.text("msg-text"))

    def test_czech(self):
        self.start("--enrolled", "left-thumb", lang="cs_CZ.UTF-8")
        self.wait_main()
        self.assertEqual(self.rows(), ["Levý palec"])
        self.assertEqual([w["title"] for w in self.app.dump()], ["Otisk prstu"])


if __name__ == "__main__":
    unittest.main()
