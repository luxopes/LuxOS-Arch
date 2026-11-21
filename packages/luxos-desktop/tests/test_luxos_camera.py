#!/usr/bin/env python3
"""LuxOS - Kamera (files/lsl/luxos-camera.lsl, luxos_camera.lsl, luxos_qr.lsl): nahled, fotka, samospoust,
video, zrcadleni, vyber kamery, chybove stavy a cteni QR kodu site Wi-Fi s pripojenim.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_camera.py -v
    (LUXOS_SHOTS=adresar ulozi snimky okna)

Kamera je videotestsrc (LUXOS_CAMERA_TEST), QR kod obrazek pres LUXOS_CAMERA_TEST_IMAGE, uzly video* jen
v docasne slozce (LUXOS_VIDEO_DEV_DIR) - skutecna kamera se nikdy neotevre. nmcli je falesny (LUXOS_NMCLI),
domov a XDG_RUNTIME_DIR v docasne slozce. Cast bez displeje: tests/lsl/luxos-camera-test.lsl.
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

SHOTS = os.environ.get("LUXOS_SHOTS", "")
TMP = None
BINARY = None
UNIT = None
XVFB = None

# Falesny nmcli: stav v $FAKE_NM_STATE (connected | connectfail), volani do $FAKE_NM_LOG, soubor s heslem
# (mod a obsah) do $FAKE_NM_LOG.pw
FAKE_NMCLI = r'''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
state = open(os.environ["FAKE_NM_STATE"]).read().strip()
with open(os.environ["FAKE_NM_LOG"], "a") as f:
    f.write("\x1f".join(args) + "\n")
if "up" in args:
    with open(os.environ["FAKE_NM_LOG"] + ".pw", "w") as f:
        f.write("passwd-file " + oct(os.stat(args[-1]).st_mode & 0o777) + " " + open(args[-1]).read())
if "add" in args or "delete" in args:
    sys.exit(0)
if state == "connectfail":
    print("Error: Connection activation failed: Secrets were required, but not provided.", file=sys.stderr)
    sys.exit(4)
print("Device 'wlan0' successfully activated")
'''


def setUpModule():
    global TMP, BINARY, UNIT, XVFB
    TMP = tempfile.mkdtemp(prefix="luxos-camera-test.", dir=luxos_testguard._private_dir())
    BINARY = lsl_app.build("luxos-camera", TMP)
    src = os.path.join(TMP, "lsl")
    shutil.copytree(lsl_app.LSL_DIR, src)
    shutil.copy(os.path.join(HERE, "lsl", "luxos-camera-test.lsl"), src)
    lslc = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
    UNIT = os.path.join(TMP, "luxos-camera-test")
    r = subprocess.run([lslc, "--target", "linux-x86_64-gnu", "--system-bindings", src,
                        os.path.join(src, "luxos-camera-test.lsl"), UNIT], capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise AssertionError("lslc failed: " + (r.stdout + r.stderr)[-3000:])
    with open(os.path.join(TMP, "nmcli"), "w") as f:
        f.write(FAKE_NMCLI)
    os.chmod(os.path.join(TMP, "nmcli"), 0o755)
    XVFB = lsl_app.Xvfb("1280x900")


def tearDownModule():
    if XVFB:
        XVFB.stop()
    if TMP:
        shutil.rmtree(TMP, True)


def have_zxing():
    r = subprocess.run([UNIT], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, LUXOS_VIDEO_DEV_DIR=TMP))
    return "skip zxing" not in r.stdout


class Units(unittest.TestCase):
    def test_qr_and_camera_units(self):
        # text WIFI:, nmcli, vyber formatu kamery, poradi uzlu video*, kodovani a cteni QR kodu
        nodes = os.path.join(TMP, "nodes")
        os.makedirs(nodes, exist_ok=True)
        for n in ("video10", "video2", "video0", "other"):
            open(os.path.join(nodes, n), "w").close()
        r = subprocess.run([UNIT], capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, LUXOS_VIDEO_DEV_DIR=nodes))
        fails = [line for line in r.stdout.splitlines() if not line.startswith(("ok ", "skip "))]
        self.assertEqual(r.returncode, 0, "\n".join(fails) + r.stderr)
        self.assertEqual(fails, [])
        self.assertIn("ok video-nodes", r.stdout)
        print("\n  %d unit cases" % r.stdout.count("ok "))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(dir=TMP)
        self.videos = os.path.join(self.home, "dev")
        os.mkdir(self.videos)
        self.runtime = os.path.join(self.home, "run")
        os.mkdir(self.runtime, 0o700)
        self.nm_state = os.path.join(self.home, "nm-state")
        self.nm_log = os.path.join(self.home, "nm.log")
        self.set_nm("connected")
        self.app = None

    def tearDown(self):
        if self.app:
            self.app.stop()

    def set_nm(self, state):
        with open(self.nm_state, "w") as f:
            f.write(state)

    def nm_calls(self):
        if not os.path.exists(self.nm_log):
            return []
        with open(self.nm_log) as f:
            return [line.rstrip("\n").split("\x1f") for line in f]

    def start(self, *args, lang="C.UTF-8", camera="1", **extra):
        env = dict(os.environ, DISPLAY=XVFB.display, HOME=self.home, LUXOS_CAMERA_TEST=camera,
                   LUXOS_VIDEO_DEV_DIR=self.videos, LANG=lang, LC_ALL=lang, XDG_RUNTIME_DIR=self.runtime,
                   XDG_CONFIG_HOME=os.path.join(self.home, ".config"), LUXOS_NMCLI=os.path.join(TMP, "nmcli"),
                   FAKE_NM_STATE=self.nm_state, FAKE_NM_LOG=self.nm_log, GTK_THEME="Adwaita")
        env.pop("LUXOS_CAMERA_TEST_IMAGE", None)
        env.update(extra)
        luxos_testguard.check_env(env)
        self.app = lsl_app.App([BINARY, *args], env)
        self.assertTrue(self.app.wait(lambda: self.app.dump()), self.app.stderr())

    def st(self):
        return json.loads(self.app.ask("state", "state"))

    def wait_state(self, state, timeout=10):
        ok = self.app.wait(lambda: self.st()["state"] == state, timeout)
        self.assertTrue(ok, self.st())

    def named(self, name):
        return lsl_app.find(self.app.dump(), name=name)

    def shot(self, name):
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            time.sleep(0.3)
            lsl_app.shot(XVFB.display, os.path.join(SHOTS, name + ".png"))

    def files(self, sub):
        d = os.path.join(self.home, sub, "Camera")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def config(self):
        with open(os.path.join(self.home, ".config", "luxos", "camera.json")) as f:
            return json.load(f)


class Window(Fixture):
    def test_preview_and_photo(self):
        self.start()
        self.assertEqual([(w["title"], w["close_button"]) for w in self.app.dump()], [("Camera", True)])
        self.wait_state("preview")
        st = self.st()
        self.assertTrue(st["frame"] and st["shutter"] and st["mirror"], st)
        self.assertFalse(st["combo"])                       # jedna kamera: bez vyberu
        self.assertFalse(st["thumb"])
        self.shot("camera-preview")
        # mezernik = spoust: fotka JPEG do ~/Pictures/Camera a nahled vlevo dole
        self.assertEqual(self.app.ask("key 32", "key"), "True")
        self.assertTrue(self.app.wait(lambda: self.files("Pictures")))
        name = self.files("Pictures")[0]
        self.assertTrue(name.startswith("Photo ") and name.endswith(".jpg"), name)
        with open(os.path.join(self.home, "Pictures", "Camera", name), "rb") as f:
            self.assertEqual(f.read(3), b"\xff\xd8\xff")
        self.assertTrue(self.app.wait(lambda: self.st()["thumb"]))
        self.assertFalse(self.st()["thumb_video"])
        # druha fotka v teze sekunde dostane cislo
        self.app.ask("click Take Photo")
        self.assertTrue(self.app.wait(lambda: len(self.files("Pictures")) == 2), self.files("Pictures"))
        self.shot("camera-photo")
        self.app.send("close")
        self.assertEqual(self.app.proc.wait(10), 0)

    def test_last_capture_on_start(self):
        pics = os.path.join(self.home, "Pictures", "Camera")
        vids = os.path.join(self.home, "Videos", "Camera")
        os.makedirs(pics)
        os.makedirs(vids)
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 64, 48)
        pb.fill(0x3080e0ff)
        pb.savev(os.path.join(pics, "old.jpg"), "jpeg", [], [])
        with open(os.path.join(vids, "new.webm"), "wb") as f:
            f.write(b"\x1a\x45\xdf\xa3")
        os.utime(os.path.join(pics, "old.jpg"), (1000, 1000))
        self.start()
        st = self.st()
        self.assertEqual(st["last"], os.path.join(vids, "new.webm"))
        self.assertTrue(st["thumb_video"])
        os.utime(os.path.join(vids, "new.webm"), (500, 500))
        self.app.stop()
        self.start()
        st = self.st()
        self.assertEqual((st["last"], st["thumb"], st["thumb_video"]), (os.path.join(pics, "old.jpg"), True, False))

    def test_timer_countdown_and_cancel(self):
        self.start()
        self.wait_state("preview")
        self.app.ask("timer 1")
        self.assertEqual(self.config()["timer"], True)
        self.app.ask("key 32")
        st = self.st()
        self.assertEqual(st["countdown"], 3)
        self.assertEqual(self.named("countdown")["text"], "3")
        self.assertTrue(self.named("countdown")["vis"])
        self.assertFalse(lsl_app.find(self.app.dump(), text="Video", kind="GtkRadioButton")["sens"])
        self.shot("camera-countdown")
        # Esc odpocet zrusi, nic se nevyfoti
        self.assertEqual(self.app.ask("key 65307", "key"), "True")
        self.assertEqual(self.st()["countdown"], 0)
        time.sleep(3.5)
        self.assertEqual(self.files("Pictures"), [])
        # znovu a az do konce: fotka po 3 s
        self.app.ask("key 32")
        self.assertTrue(self.app.wait(lambda: self.files("Pictures"), 6))
        self.assertFalse(self.named("countdown")["vis"])

    def test_video_recording(self):
        self.start()
        self.wait_state("preview")
        self.app.ask("click Video")
        self.assertEqual(self.config()["mode"], "video")
        self.assertEqual(self.st()["mode"], "video")
        self.app.ask("click Start recording")
        self.assertTrue(self.app.wait(lambda: self.st()["recording"]))
        st = self.st()
        self.assertTrue(st["recording"].startswith(os.path.join(self.home, "Videos", "Camera", "Video ")), st)
        self.assertTrue(st["audio"], st)                      # audiotestsrc v testovacim rezimu
        self.assertTrue(self.app.wait(lambda: self.named("rec")["vis"] and ":0" in self.named("rec")["text"]))
        self.assertFalse(lsl_app.find(self.app.dump(), text="Photo", kind="GtkRadioButton")["sens"])
        time.sleep(2.2)
        self.shot("camera-recording")
        self.app.ask("click Stop recording")
        self.assertTrue(self.app.wait(lambda: not self.st()["recording"], 10), self.st())
        self.wait_state("preview")
        path = st["recording"]
        self.assertTrue(os.path.getsize(path) > 1000)
        self.assertEqual(self.st()["last"], path)
        self.assertTrue(self.st()["thumb_video"] and self.st()["thumb"])
        probe = shutil.which("gst-discoverer-1.0")
        if probe:
            r = subprocess.run([probe, path], capture_output=True, text=True, timeout=60)
            self.assertIn("Duration", r.stdout)
        # zavreni okna behem nahravani soubor dopise (EOS)
        self.app.ask("click Start recording")
        self.assertTrue(self.app.wait(lambda: self.st()["recording"]))
        second = self.st()["recording"]
        time.sleep(1.5)
        self.app.send("close")
        self.assertEqual(self.app.proc.wait(15), 0)
        self.assertTrue(os.path.getsize(second) > 1000)

    def test_two_cameras_and_mirror(self):
        self.start(camera="2")
        self.wait_state("preview")
        st = self.st()
        self.assertEqual(st["devices"], ["Test Camera 1", "Test Camera 2"])
        self.assertTrue(st["combo"])
        self.assertEqual(st["device"], "test:0")
        self.app.ask("camera test:1")
        self.assertTrue(self.app.wait(lambda: self.st()["device"] == "test:1"))
        self.wait_state("preview")
        self.assertEqual(self.config()["device"], "test:1")
        self.app.ask("mirror 0")
        self.assertEqual(self.config()["mirror"], {"Test Camera 2": False})
        self.shot("camera-two")
        self.app.stop()
        # vybrana kamera a jeji zrcadleni se pamatuji
        self.start(camera="2")
        self.wait_state("preview")
        st = self.st()
        self.assertEqual((st["device"], st["mirror"]), ("test:1", False))
        self.app.ask("camera test:0")
        self.assertTrue(self.app.wait(lambda: self.st()["device"] == "test:0" and self.st()["mirror"]))

    def test_camera_states(self):
        for mode, title, retry in (("none", "No camera found", True),
                                   ("busy", "The camera is being used by another app", True),
                                   ("denied", "Camera access is not allowed", True)):
            with self.subTest(mode=mode):
                self.start(camera=mode)
                self.assertTrue(self.app.wait(lambda: self.named("state-title")["text"] == title))
                st = self.st()
                self.assertEqual((st["page"], st["shutter"]), ("state", False))
                self.assertEqual(lsl_app.find(self.app.dump(), text="Try Again")["vis"], retry)
                self.assertEqual(self.named("state-code")["vis"], mode == "denied")
                if mode == "denied":
                    self.assertEqual(self.named("state-code")["text"], "sudo usermod -aG video $USER")
                    self.assertIn("video group", self.named("state-hint")["text"])
                self.shot("camera-" + mode)
                self.app.ask("click Try Again")
                self.assertEqual(self.named("state-title")["text"], title)
                self.app.stop()
        # bez testovaci kamery a s prazdnou slozkou uzlu: zadna kamera (nikdy /dev/video*)
        self.start(camera="")
        self.assertTrue(self.app.wait(lambda: self.named("state-title")["text"] == "No camera found"))

    def test_czech(self):
        self.start(lang="cs_CZ.UTF-8")
        self.wait_state("preview")
        self.assertEqual([w["title"] for w in self.app.dump()], ["Kamera"])
        self.assertTrue(lsl_app.find(self.app.dump(), text="Fotka", kind="GtkRadioButton"))
        self.shot("camera-cs")

    def test_memory(self):
        self.start()
        self.wait_state("preview")
        time.sleep(3)
        pss = self.app.pss_kb()
        print("\n  PSS with preview: %d kB" % pss)
        self.assertLess(pss, 90 * 1024)


class Scan(Fixture):
    def qr_image(self, payload):
        """QR kod na papire na stole (jako snimek kamery), cesta k PNG."""
        img = os.path.join(self.home, "qr.png")
        r = subprocess.run([UNIT, "--render", payload, img], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return img

    def setUp(self):
        super().setUp()
        if not have_zxing():
            self.skipTest("needs libZXing (zxing-cpp) or LUXOS_ZXING_LIB")

    def dialog_texts(self):
        return lsl_app.texts(self.app.dump(), dialog=True)

    def test_scan_and_join(self):
        payload = "WIFI:T:WPA;S:Kavárna;P:tajne\\;heslo;;"
        self.start("--scan-wifi", LUXOS_CAMERA_TEST_IMAGE=self.qr_image(payload))
        d = self.app.dump()
        self.assertEqual([w["title"] for w in d], ["Join Wi-Fi with QR Code"])
        self.assertFalse(lsl_app.find(d, text="Take Photo")["vis"])   # v rezimu QR neni spoust
        self.assertTrue(self.app.wait(lambda: any(w["dialog"] for w in self.app.dump()), 15), self.st())
        self.assertEqual(self.st()["state"], "preview")
        self.assertIn("Join the Wi-Fi network “Kavárna”?", self.dialog_texts())
        self.shot("camera-scan-dialog")
        self.app.ask("click Join")
        self.assertTrue(self.app.wait(lambda: self.st()["state"] == "connected", 15), self.st())
        self.assertEqual(self.named("state-title")["text"], "Connected to “Kavárna”")
        self.shot("camera-scan-connected")
        calls = self.nm_calls()
        up = [c for c in calls if "up" in c]
        self.assertEqual(len(up), 1)
        self.assertEqual(up[0][:5], ["--wait", "60", "connection", "up", "uuid"])
        add = [c for c in calls if "add" in c][0]
        self.assertEqual(up[0][5], add[add.index("connection.uuid") + 1])
        # heslo nikdy v argumentech nmcli (viditelne v ps), jen v souboru 0600, ktery se smaze
        self.assertFalse([c for c in calls if any("tajne" in a for a in c)])
        with open(self.nm_log + ".pw") as f:
            self.assertEqual(f.read(), "passwd-file 0o600 802-11-wireless-security.psk:tajne;heslo\n")
        self.assertFalse(os.path.exists(up[0][-1]))
        self.assertTrue(up[0][-1].startswith(self.runtime + "/luxos-qr-"))

    def test_join_fails_and_cancel(self):
        self.set_nm("connectfail")
        self.start("--scan-wifi", LUXOS_CAMERA_TEST_IMAGE=self.qr_image("WIFI:T:WPA;S:Bad;P:wrong;;"))
        self.assertTrue(self.app.wait(lambda: any(w["dialog"] for w in self.app.dump()), 15))
        # Zrusit: dialog zmizi, stejny kod se nabidne znovu az po chvili
        self.app.ask("click Cancel")
        self.assertFalse(any(w["dialog"] for w in self.app.dump()))
        self.assertTrue(self.app.wait(lambda: any(w["dialog"] for w in self.app.dump()), 15))
        self.app.ask("click Join")
        self.assertTrue(self.app.wait(lambda: self.st()["state"] == "error", 15), self.st())
        self.assertEqual(self.named("state-title")["text"], "The network could not be joined")
        self.assertIn("Secrets were required", self.named("state-hint")["text"])
        self.assertEqual(self.nm_calls()[-1][:2], ["connection", "delete"])     # nepovedeny profil se uklidi

    def test_open_network_and_not_wifi(self):
        self.start("--scan-wifi", LUXOS_CAMERA_TEST_IMAGE=self.qr_image("WIFI:T:nopass;S:Open;;"))
        self.assertTrue(self.app.wait(lambda: any(w["dialog"] for w in self.app.dump()), 15))
        self.assertIn("Open network – no password needed.", self.dialog_texts())
        self.app.ask("click Join")
        self.assertTrue(self.app.wait(lambda: self.st()["state"] == "connected", 15), self.st())
        self.assertEqual(self.nm_calls()[-1], ["--wait", "60", "device", "wifi", "connect", "Open"])
        self.app.stop()
        # QR kod bez site: jen hlaska v nahledu
        self.start("--scan-wifi", LUXOS_CAMERA_TEST_IMAGE=self.qr_image("https://luxos.example/"))
        self.assertTrue(self.app.wait(
            lambda: self.named("scan-hint")["text"] == "This QR code is not a Wi-Fi network.", 15))
        self.assertFalse(any(w["dialog"] for w in self.app.dump()))


if __name__ == "__main__":
    unittest.main()
