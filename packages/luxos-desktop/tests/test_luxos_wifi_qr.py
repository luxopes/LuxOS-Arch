#!/usr/bin/env python3
"""LuxOS - testy okna QR kodu Wi-Fi (files/lsl/luxos-wifi-qr.lsl): QR kod pripojene site, stavy, heslo spravce.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_wifi_qr.py -v

nmcli a pkexec jsou falesne (LUXOS_NMCLI, LUXOS_PKEXEC) - na skutecnou sit ani hesla se nesahne.
Kodovani a cteni QR kodu potrebuje libZXing (zxing-cpp; jinak LUXOS_ZXING_LIB=/cesta/libZXing.so.4).
Okno ve vlastnim Xvfb, rizene pres luxos_testctl; snimky do LUXOS_TEST_SHOTS. Text WIFI:, rozbor vystupu
nmcli, cteni QR kodu a pripojeni z Kamery: test_luxos_camera.py (luxos_qr.lsl).
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
import ctypes.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

TMP = tempfile.mkdtemp(prefix="luxos-wifi-qr-test-")
NM_STATE = os.path.join(TMP, "nm-state")
NM_LOG = os.path.join(TMP, "nm.log")

# Falesny nmcli: stav v NM_STATE (connected | wired | nosecrets), volani do NM_LOG
FAKE_NMCLI = r'''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
state = open(os.environ["FAKE_NM_STATE"]).read().strip()
with open(os.environ["FAKE_NM_LOG"], "a") as f:
    f.write(("root " if os.environ.get("FAKE_ROOT") else "") + "\x1f".join(args) + "\n")
if args[-2:] == ["show", "--active"]:
    print("loopback:lo-uuid:lo:lo")
    if state != "wired":
        print("802-11-wireless:uuid-1:wlan0:Kavárna\\:1")
    sys.exit(0)
if "add" in args:
    sys.exit(0)
if "up" in args:
    with open(os.environ["FAKE_NM_LOG"] + ".pw", "w") as f:
        f.write("passwd-file " + oct(os.stat(args[-1]).st_mode & 0o777) + " " + open(args[-1]).read())
if "delete" in args:
    sys.exit(0)
if "show" in args and "uuid" in args and state == "broken":
    print("Error: connection uuid-1 cannot be read.", file=sys.stderr)
    sys.exit(10)
if "show" in args and "uuid" in args:
    secrets = "--show-secrets" in args and (state != "nosecrets" or os.environ.get("FAKE_ROOT"))
    print("802-11-wireless.ssid:Kavárna:1")
    print("802-11-wireless.hidden:no")
    print("802-11-wireless-security.key-mgmt:" + ("wpa-eap" if state == "eap" else "wpa-psk"))
    print("802-11-wireless-security.psk:" + ("tajne;heslo,\\1" if secrets else ""))
    print("802-11-wireless-security.wep-key0:")
    sys.exit(0)
if "connect" in args or "up" in args:
    if state == "connectfail":
        print("Error: Connection activation failed: Secrets were required, but not provided.", file=sys.stderr)
        sys.exit(4)
    print("Device 'wlan0' successfully activated")
    sys.exit(0)
sys.exit(2)
'''
FAKE_PKEXEC = '#!/bin/sh\n[ -n "$FAKE_PKEXEC_CANCEL" ] && exit 126\nFAKE_ROOT=1 exec "$@"\n'

for name, text in (("nmcli", FAKE_NMCLI), ("pkexec", FAKE_PKEXEC)):
    path = os.path.join(TMP, name)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, 0o755)
os.environ.update({
    "LUXOS_NMCLI": os.path.join(TMP, "nmcli"), "LUXOS_PKEXEC": os.path.join(TMP, "pkexec"),
    "FAKE_NM_STATE": NM_STATE, "FAKE_NM_LOG": NM_LOG,
    "LUXOS_I18N_DIR": os.path.join(ROOT, "luxos-i18n", "files"),
    "HOME": TMP, "XDG_CONFIG_HOME": os.path.join(TMP, "config"), "XDG_CACHE_HOME": os.path.join(TMP, "cache"),
})

sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

HAVE_ZXING = bool(os.environ.get("LUXOS_ZXING_LIB") or ctypes.util.find_library("ZXing"))


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def set_state(state):
    with open(NM_STATE, "w") as f:
        f.write(state)
    if os.path.exists(NM_LOG):
        os.unlink(NM_LOG)


def nm_calls():
    if not os.path.exists(NM_LOG):
        return []
    with open(NM_LOG) as f:
        return [line.rstrip("\n").split("\x1f") for line in f]


@unittest.skipUnless(HAVE_ZXING, "needs libZXing (zxing-cpp) or LUXOS_ZXING_LIB")
class TestShareWindow(unittest.TestCase):
    """Okno luxos-wifi-qr v LSL: QR kod pripojene site, stavy, heslo spravce, kopirovani obrazku."""

    @classmethod
    def setUpClass(cls):
        cls.binary = lsl_app.build("luxos-wifi-qr", TMP)
        # cteni QR kodu ze snimku: pomocny program testu Kamery (luxos_qr.lsl)
        src = os.path.join(TMP, "lsl")
        shutil.copytree(lsl_app.LSL_DIR, src, dirs_exist_ok=True)
        shutil.copy(os.path.join(HERE, "lsl", "luxos-camera-test.lsl"), src)
        cls.reader = os.path.join(TMP, "luxos-camera-test")
        r = subprocess.run([os.environ.get("LUXOS_LSLC") or shutil.which("lslc"), "--target", "linux-x86_64-gnu",
                            "--system-bindings", src, os.path.join(src, "luxos-camera-test.lsl"), cls.reader],
                           capture_output=True, text=True, timeout=600)
        if r.returncode:
            raise AssertionError("lslc failed: " + (r.stdout + r.stderr)[-3000:])
        cls.x = lsl_app.Xvfb("1280x900")
        cls.videos = os.path.join(TMP, "no-cameras")
        os.makedirs(cls.videos, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.x.stop()

    def start(self, state, *args, **extra):
        set_state(state)
        env = dict(os.environ, DISPLAY=self.x.display, LUXOS_CAMERA_TEST="1", LUXOS_VIDEO_DEV_DIR=self.videos,
                   LANG="C.UTF-8", LC_ALL="C.UTF-8")
        env.update(extra)
        luxos_testguard.check_env(env)
        self.app = lsl_app.App([self.binary, *args], env)
        self.addCleanup(self.app.stop)
        self.assertTrue(self.app.wait(lambda: self.app.dump()), self.app.stderr())

    def st(self):
        return json.loads(self.app.ask("state", "state"))

    def named(self, name):
        return lsl_app.find(self.app.dump(), name=name)["text"]

    def button(self, text):
        return lsl_app.find(self.app.dump(), text=text, kind="GtkButton")

    def wait(self, cond, timeout=10):
        return self.app.wait(cond, timeout)

    def test_share_window_shows_scannable_code(self):
        self.start("connected")
        self.assertEqual([(w["title"], w["close_button"]) for w in self.app.dump()], [("Wi-Fi QR Code", True)])
        self.assertTrue(self.wait(lambda: self.st()["page"] == "qr"))
        self.assertEqual(self.named("ssid"), "Kavárna:1")
        self.assertFalse(self.st()["password_shown"])
        # QR kod v okne se da skutecne precist a obsahuje sit s heslem
        time.sleep(0.4)
        shot = os.path.join(TMP, "share.png")
        lsl_app.shot(self.x.display, shot)
        out = os.environ.get("LUXOS_TEST_SHOTS")
        if out:
            os.makedirs(out, exist_ok=True)
            shutil.copy(shot, os.path.join(out, "wifi-qr-share.png"))
        r = subprocess.run([self.reader, shot], capture_output=True, text=True, timeout=60)
        texts = [json.loads(line[5:]) for line in r.stdout.splitlines() if line.startswith("text ")]
        self.assertEqual(texts, ["WIFI:T:WPA;S:Kavárna\\:1;P:tajne\\;heslo\\,\\\\1;;"])
        # Tlacitko Kopirovat je videt (i s ikonou: drive no_show_all schoval ikonu)
        copy = self.button("Copy QR code image")
        self.assertTrue(copy and copy["vis"])
        self.app.ask("click Copy QR code image")
        self.assertTrue(self.st()["clipboard"])
        # zobrazeni hesla ikonou v poli
        self.app.ask("toggle")
        self.assertTrue(self.st()["password_shown"])
        # heslo se nikam nevypisuje
        self.app.stop()
        self.assertNotIn("tajne", self.app.stderr())
        self.assertNotIn("tajne", "\n".join(self.app.lines))

    def test_share_window_states(self):
        self.start("nosecrets")
        self.assertTrue(self.wait(lambda: (self.button("Show Password…") or {}).get("vis")))
        self.assertIn("administrator password", self.named("state-hint"))
        self.assertFalse(self.button("Copy QR code image")["vis"])
        self.app.ask("click Show Password…")                    # pkexec nmcli (falesne)
        self.assertTrue(self.wait(lambda: self.st()["page"] == "qr"))
        self.assertTrue([c for c in nm_calls() if c[0].startswith("root ")])
        set_state("wired")
        self.app.ask("reload")
        self.assertTrue(self.wait(lambda: self.named("state-title") == "Not connected to Wi-Fi"))
        self.assertTrue(self.button("Join a Network with a QR Code…")["vis"])
        set_state("eap")
        self.app.ask("reload")
        self.assertTrue(self.wait(lambda: "802.1X" in self.named("state-hint")))
        self.assertEqual(self.named("state-title"), "Kavárna:1")

    def test_admin_cancelled(self):
        # zrusene okno pkexec: zpet na vyzvu k heslu spravce (bez hesla v QR kodu)
        self.start("nosecrets", FAKE_PKEXEC_CANCEL="1")
        self.assertTrue(self.wait(lambda: (self.button("Show Password…") or {}).get("vis")))
        self.app.ask("click Show Password…")
        time.sleep(0.5)
        self.assertTrue(self.wait(lambda: (self.button("Show Password…") or {}).get("vis")))
        self.assertEqual(self.st()["page"], "state")

    def test_open_network_and_errors(self):
        # nmcli selze: hlaska s vystupem nmcli
        self.start("broken")
        self.assertTrue(self.wait(lambda: self.named("state-title") == "The network settings could not be read"))
        self.assertEqual(self.named("state-hint"), "Error: connection uuid-1 cannot be read.")

    def test_no_camera_hides_scan(self):
        self.start("connected", LUXOS_CAMERA_TEST="")
        self.assertTrue(self.wait(lambda: self.st()["page"] == "qr"))
        self.assertFalse(self.button("Join a Network with a QR Code…")["vis"])

    def test_scan_runs_camera(self):
        # --scan preda rizeni Kamere (luxos-camera --scan-wifi)
        bindir = os.path.join(TMP, "fake-bin")
        os.makedirs(bindir, exist_ok=True)
        log = os.path.join(TMP, "camera-args")
        with open(os.path.join(bindir, "luxos-camera"), "w") as f:
            f.write('#!/bin/sh\necho "$@" > "%s"\n' % log)
        os.chmod(os.path.join(bindir, "luxos-camera"), 0o755)
        r = subprocess.run([self.binary, "--scan"], env=dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"]),
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(log) as f:
            self.assertEqual(f.read().strip(), "--scan-wifi")

    def test_czech(self):
        self.start("connected", LANG="cs_CZ.UTF-8", LC_ALL="cs_CZ.UTF-8")
        self.assertTrue(self.wait(lambda: self.st()["page"] == "qr"))
        self.assertEqual([w["title"] for w in self.app.dump()], ["QR kód Wi\u2011Fi"])


if __name__ == "__main__":
    unittest.main()
