#!/usr/bin/env python3
"""LuxOS - Profilova fotka (files/lsl/luxos-profile-picture.lsl, luxos_avatar.lsl, luxos_camera.lsl): orez
obrazku, fotka z testovaci kamery, ulozeni a odebrani, chybove stavy kamery.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_profile_picture.py -v
    (LUXOS_SHOTS=adresar ulozi snimky okna)

AccountsService je napodobena (LUXOS_ACCOUNTS_FAKE), kamera je videotestsrc (LUXOS_CAMERA_TEST=1), uzly
video* jen v docasne slozce (LUXOS_VIDEO_DEV_DIR) - skutecna kamera se nikdy neotevre. Domov v docasne slozce.
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
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

from gi.repository import GdkPixbuf  # noqa: E402

SHOTS = os.environ.get("LUXOS_SHOTS", "")
TMP = None
BINARY = None
XVFB = None


def setUpModule():
    global TMP, BINARY, XVFB
    TMP = tempfile.mkdtemp(prefix="luxos-pp-test.", dir=luxos_testguard._private_dir())
    BINARY = lsl_app.build("luxos-profile-picture", TMP)
    XVFB = lsl_app.Xvfb()


def tearDownModule():
    if XVFB:
        XVFB.stop()
    if TMP:
        shutil.rmtree(TMP, True)


def pixel(pb, x, y):
    i = y * pb.get_rowstride() + x * pb.get_n_channels()
    return tuple(pb.get_pixels()[i:i + 3])


class Fixture(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(dir=TMP)
        self.fake = os.path.join(self.home, "accounts-icon")
        self.videos = os.path.join(self.home, "dev")
        os.mkdir(self.videos)
        self.face = os.path.join(self.home, ".face")
        self.app = None

    def tearDown(self):
        if self.app:
            self.app.stop()

    def start(self, *args, lang="C.UTF-8", camera="1"):
        env = dict(os.environ, DISPLAY=XVFB.display, HOME=self.home, LUXOS_ACCOUNTS_FAKE=self.fake,
                   LUXOS_CAMERA_TEST=camera, LUXOS_VIDEO_DEV_DIR=self.videos, LANG=lang, LC_ALL=lang,
                   XDG_CONFIG_HOME=os.path.join(self.home, ".config"))
        luxos_testguard.check_env(env)
        self.app = lsl_app.App([BINARY, *args], env)
        self.assertTrue(self.app.wait(lambda: self.app.dump()), self.app.stderr())

    def st(self):
        return json.loads(self.app.ask("state", "state"))

    def photo(self, name="photo.jpg", w=600, h=400, alpha=False):
        """Obrazek: vlevo cerveny, vpravo modry pruh."""
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, alpha, 8, w, h)
        pb.fill(0x2060e0ff)
        pb.new_subpixbuf(0, 0, w // 2, h).fill(0xe03030ff)
        path = os.path.join(self.home, name)
        pb.savev(path, "png" if name.endswith(".png") else "jpeg", [], [])
        return path

    def visible(self, text):
        w = lsl_app.find(self.app.dump(), text=text, kind="GtkButton")
        return bool(w and w["vis"])

    def hint(self):
        return lsl_app.find(self.app.dump(), name="hint")["text"]

    def shot(self, name):
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            time.sleep(0.3)
            lsl_app.shot(XVFB.display, os.path.join(SHOTS, name + ".png"))


class Crop(Fixture):
    """Geometrie orezu (drive i v luxos_avatar.py pro aplikace v Pythonu)."""

    def crop(self, *v):
        return json.loads(self.app.ask("crop " + " ".join(str(x) for x in v), "crop"))

    def test_geometry(self):
        self.start()
        # 600x400, kruh 280: kratsi strana presne pod kruhem, vyrez ze stredu
        self.assertEqual(self.crop(600, 400, 280, 1.0, 0, 0), [100.0, 0.0, 400.0])
        # posun doprava = leva cast obrazku, omezeny na okraj
        self.assertEqual(self.crop(600, 400, 280, 1.0, 10000, -10000), [0.0, 0.0, 400.0])
        x, y, side = self.crop(600, 400, 280, 1.0, -10000, 0)
        self.assertEqual(x + side, 600.0)
        x, y, side = self.crop(600, 400, 280, 2.0, 0, 0)
        self.assertEqual((x, y, side), (200.0, 100.0, 200.0))
        self.assertEqual(self.crop(600, 400, 280, 99, 0, 0)[2], 100.0)      # nejvys MAX_ZOOM
        self.assertEqual(self.crop(600, 400, 280, 0.2, 0, 0)[2], 400.0)     # nejmene 1x
        # vyska presne pod kruhem: svisly posun neni
        self.assertEqual(json.loads(self.app.ask("clamp 600 400 280 1.0 0 50", "clamp")), [0.0, 0.0])

    def test_load_limits_and_rejects(self):
        self.start()
        big = os.path.join(self.home, "big.png")
        GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4000, 1000).savev(big, "png", [], [])
        self.assertEqual(self.app.ask("open " + big, "open"), "True")
        self.assertEqual(self.st()["size"], [2048, 512])            # nejvys MAX_SOURCE px
        bad = os.path.join(self.home, "bad.jpg")
        with open(bad, "w") as f:
            f.write("not an image")
        self.assertEqual(self.app.ask("open " + bad, "open"), "False")
        self.assertEqual(self.st()["page"], "main")
        self.assertTrue(lsl_app.find(self.app.dump(), name="hint")["text"].startswith("This file is not a picture"))

    def test_initials(self):
        self.start()
        self.assertEqual(self.app.ask("initials anna Nováková", "initials"), "A")
        self.assertEqual(self.app.ask("initials   ", "initials"), "?")
        self.assertEqual(self.app.ask("initials čeněk", "initials"), "Č")


ACCOUNTS_XML = """<node><interface name="org.freedesktop.Accounts">
  <method name="FindUserById"><arg type="x" direction="in"/><arg type="o" direction="out"/></method>
</interface><interface name="org.freedesktop.Accounts.User">
  <method name="SetIconFile"><arg type="s" direction="in"/></method>
</interface></node>"""


class AccountsError(Fixture):
    """Chyba AccountsService: text bez predpony "GDBus.Error:jmeno: " (Python ukazoval "True")."""

    def test_remote_error_text(self):
        from gi.repository import Gio, GLib
        from test_luxos_awake import ServiceThread, connect, own
        bus = lsl_app.Bus()
        svc = ServiceThread()
        calls = []

        def on_call(_c, _s, _p, _i, method, params, inv):
            calls.append(method)
            if method == "FindUserById":
                inv.return_value(GLib.Variant("(o)", ("/org/freedesktop/Accounts/User1000",)))
            else:
                inv.return_dbus_error("org.freedesktop.Accounts.Error.PermissionDenied", "Not authorized")

        def init():
            conn = connect(bus.address)
            node = Gio.DBusNodeInfo.new_for_xml(ACCOUNTS_XML)
            conn.register_object("/org/freedesktop/Accounts", node.interfaces[0], on_call, None, None)
            conn.register_object("/org/freedesktop/Accounts/User1000", node.interfaces[1], on_call, None, None)
            own(conn, "org.freedesktop.Accounts")
            return conn
        conn = svc.run(init)
        try:
            env = dict(os.environ, DISPLAY=XVFB.display, HOME=self.home, LUXOS_TEST_SYSTEM_BUS=bus.address,
                       DBUS_SYSTEM_BUS_ADDRESS=bus.address, LANG="C.UTF-8", LC_ALL="C.UTF-8",
                       LUXOS_VIDEO_DEV_DIR=self.videos, LUXOS_CAMERA_TEST="1")
            env.pop("LUXOS_ACCOUNTS_FAKE", None)
            luxos_testguard.check_env(env)
            self.app = lsl_app.App([BINARY], env)
            self.assertTrue(self.app.wait(lambda: self.app.dump()), self.app.stderr())
            self.assertEqual(self.app.ask("seticon /tmp/x.png", "seticon"), "Not authorized")
            self.assertEqual(calls[-2:], ["FindUserById", "SetIconFile"])
        finally:
            svc.run(conn.close_sync, None)
            svc.stop()
            bus.stop()


class Window(Fixture):
    def test_crop_save_remove(self):
        self.start()
        d = self.app.dump()
        self.assertEqual([(w["title"], w["close_button"]) for w in d], [("Profile Picture", True)])
        self.assertFalse(self.visible("Remove Picture"), "bez fotky: tlacitko Odebrat skryte")
        self.shot("profile-empty")
        # orez obrazku: posun doleva az na doraz -> pod kruhem cervena polovina
        self.assertEqual(self.app.ask("open " + self.photo(), "open"), "True")
        self.assertEqual(self.st()["page"], "crop")
        self.app.ask("offset 10000 0")
        st = self.st()
        self.assertTrue(0 < st["ox"] < 1000 and st["oy"] == 0, st)
        self.app.ask("zoom 1.5")
        self.assertAlmostEqual(self.st()["zoom"], 1.5)
        self.shot("profile-crop")
        self.app.ask("click Save")
        self.assertTrue(self.app.wait(lambda: os.path.isfile(self.face)))
        with open(self.fake) as f:
            self.assertEqual(f.read(), self.face)
        self.assertEqual(os.stat(self.face).st_mode & 0o777, 0o644)
        self.assertFalse(os.path.exists(self.face + ".tmp"))
        pb = GdkPixbuf.Pixbuf.new_from_file(self.face)
        self.assertEqual((pb.get_width(), pb.get_height(), pb.get_has_alpha()), (384, 384, False))
        r, g, b = pixel(pb, 192, 192)
        self.assertTrue(r > 180 and b < 90, (r, g, b))
        self.assertTrue(self.app.wait(lambda: self.visible("Remove Picture")))
        self.assertEqual(self.st()["page"], "main")
        self.assertEqual(self.hint(), "Saved. The new picture appears on the login screen and in the menu.")
        self.shot("profile-saved")
        # odebrani
        self.app.ask("click Remove Picture")
        self.assertFalse(os.path.exists(self.face))
        with open(self.fake) as f:
            self.assertEqual(f.read(), "")
        self.assertTrue(self.app.wait(lambda: not self.visible("Remove Picture")))
        self.assertEqual(self.hint(), "Picture removed.")

    def test_existing_picture_and_cancel(self):
        # fotka uz je: Odebrat je videt hned po startu; Zrusit v orezu nic neulozi
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 384, 384)
        pb.fill(0x3060c0ff)
        pb.savev(self.face, "png", [], [])
        self.start()
        self.assertTrue(self.visible("Remove Picture"))
        before = open(self.face, "rb").read()
        self.app.ask("open " + self.photo(), "open")
        self.app.ask("click Cancel")
        self.assertEqual(self.st()["page"], "main")
        self.assertEqual(open(self.face, "rb").read(), before)
        self.assertFalse(os.path.exists(self.fake))

    def test_enter_on_cancel_does_not_save(self):
        # Enter s fokusem na Zrusit v orezu: zrusi, neulozi (drive prepsal ~/.face)
        self.start()
        self.app.ask("open " + self.photo(), "open")
        self.app.ask("focus Cancel")
        self.assertEqual(self.app.ask("key 65293", "key"), "False")
        self.assertFalse(os.path.exists(self.face))
        # Enter s fokusem na Ulozit (vychozi po otevreni) ulozi
        self.app.ask("focus Save")
        self.assertEqual(self.app.ask("key 65293", "key"), "True")
        self.assertTrue(os.path.isfile(self.face))
        # Esc v orezu zpet
        self.app.ask("open " + self.photo(), "open")
        self.assertEqual(self.app.ask("key 65307", "key"), "True")
        self.assertEqual(self.st()["page"], "main")

    def test_file_argument_large_and_transparent(self):
        # SOUBOR z prikazove radky rovnou do orezu; velka fotka zmensena na 2048 px
        self.start(self.photo("big.png", 4000, 1000))
        self.assertTrue(self.app.wait(lambda: self.st()["page"] == "crop"))
        self.assertEqual(self.st()["size"], [2048, 512])
        self.app.stop()
        # pruhledne PNG na bilem podkladu
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 300, 200)
        pb.fill(0x00000000)
        pb.new_subpixbuf(0, 0, 150, 200).fill(0xe03030ff)
        path = os.path.join(self.home, "alpha.png")
        pb.savev(path, "png", [], [])
        self.start(path)
        self.app.ask("offset -10000 0")
        self.app.ask("click Save")
        self.assertTrue(self.app.wait(lambda: os.path.isfile(self.face)))
        out = GdkPixbuf.Pixbuf.new_from_file(self.face)
        self.assertFalse(out.get_has_alpha())
        self.assertEqual(pixel(out, 380, 192), (255, 255, 255))

    def test_not_a_picture(self):
        self.start()
        with open(os.path.join(self.home, "bad.jpg"), "w") as f:
            f.write("not an image")
        self.assertEqual(self.app.ask("open " + os.path.join(self.home, "bad.jpg"), "open"), "False")
        self.assertEqual(self.hint(), "This file is not a picture LuxOS can open.")
        self.assertTrue(self.st()["hint_error"])
        self.assertEqual(self.st()["page"], "main")

    def test_czech(self):
        self.start(lang="cs_CZ.UTF-8")
        texts = [w.get("text") for w in lsl_app.widgets(self.app.dump())]
        self.assertIn("Vybrat fotku…", texts)
        self.assertEqual([w["title"] for w in self.app.dump()], ["Profilová fotka"])


class Camera(Fixture):
    def test_test_camera_photo(self):
        # kamera (videotestsrc) -> fotka -> orez
        self.start()
        self.app.ask("camera")
        self.assertTrue(self.app.wait(lambda: self.st()["cam"] == "preview"))
        st = self.st()
        self.assertTrue(st["camera"] and st["shutter"], st)
        self.shot("profile-camera")
        self.app.ask("photo")
        self.assertTrue(self.app.wait(lambda: self.st()["page"] == "crop"))
        st = self.st()
        self.assertFalse(st["camera"], "kamera zastavena")
        self.assertEqual(st["size"], [1280, 720])
        self.app.ask("click Save")
        self.assertTrue(self.app.wait(lambda: os.path.isfile(self.face)))

    def test_camera_argument_and_escape(self):
        self.start("--camera")
        self.assertTrue(self.app.wait(lambda: self.st()["cam"] == "preview"))
        self.assertEqual(self.app.ask("key 65307", "key"), "True")
        st = self.st()
        self.assertEqual((st["page"], st["camera"]), ("main", False))

    def cam_texts(self):
        d = self.app.dump()
        return lsl_app.find(d, name="cam-title")["text"], lsl_app.find(d, name="cam-text")["text"]

    def test_no_camera(self):
        self.start(camera="none")
        self.app.ask("camera")
        st = self.st()
        self.assertEqual((st["cam"], st["shutter"]), ("state", False))
        self.assertEqual(self.cam_texts()[0], "No camera found")
        self.shot("profile-nocamera")

    def test_busy_and_denied(self):
        self.start(camera="busy")
        self.app.ask("camera")
        self.assertEqual(self.cam_texts()[0], "The camera is being used by another app")
        self.app.stop()
        self.start(camera="denied")
        self.app.ask("camera")
        self.assertEqual(self.cam_texts()[0], "Camera access is not allowed")

    def test_scan_device_nodes(self):
        # uzly v LUXOS_VIDEO_DEV_DIR: obycejny soubor neni kamera (VIDIOC_QUERYCAP selze), nepristupny uzel
        # = chybi opravneni; jine soubory se ignoruji. Skutecne /dev se nikdy necte.
        open(os.path.join(self.videos, "video0"), "w").close()
        locked = os.path.join(self.videos, "video1")
        open(locked, "w").close()
        os.chmod(locked, 0)
        open(os.path.join(self.videos, "media0"), "w").close()
        self.start(camera="")
        self.assertEqual(json.loads(self.app.ask("scan", "scan")), [[], 1])
        self.app.ask("camera")
        self.assertEqual(self.cam_texts()[0], "Camera access is not allowed")
        os.chmod(locked, 0o600)
        self.assertEqual(json.loads(self.app.ask("scan", "scan")), [[], 0])
        self.app.ask("camera")
        self.assertEqual(self.cam_texts()[0], "No camera found")

    def test_pick_caps(self):
        # vyber formatu kamery: <= 1280 px, >= 20 fps, raw pred MJPEG
        self.start()
        pick = lambda caps: json.loads(self.app.ask("pick " + caps, "pick"))  # noqa: E731
        caps = ("video/x-raw, format=(string)YUY2, width=(int)1920, height=(int)1080, framerate=(fraction)5/1; "
                "video/x-raw, format=(string)YUY2, width=(int)1280, height=(int)720, framerate=(fraction)10/1; "
                "image/jpeg, width=(int)1280, height=(int)720, framerate=(fraction){ 30/1, 15/1 }; "
                "image/jpeg, width=(int)1920, height=(int)1080, framerate=(fraction)30/1")
        self.assertEqual(pick(caps), ["image/jpeg,width=1280,height=720,framerate=30/1", True])
        raw = ("video/x-raw, format=(string)YUY2, width=(int)640, height=(int)480, framerate=(fraction){ 60/1, 30/1 }; "
               "image/jpeg, width=(int)640, height=(int)480, framerate=(fraction)30/1")
        self.assertEqual(pick(raw), ["video/x-raw,width=640,height=480,framerate=30/1,format=YUY2", False])
        # rozsah frekvenci vyjedna v4l2src (bez framerate v caps)
        self.assertEqual(pick("video/x-raw, format=(string)NV12, width=(int)1280, height=(int)720, "
                              "framerate=(fraction)[ 1/1, 30/1 ]"),
                         ["video/x-raw,width=1280,height=720,format=NV12", False])
        self.assertIsNone(pick("audio/x-raw, rate=(int)44100"))


if __name__ == "__main__":
    unittest.main()
