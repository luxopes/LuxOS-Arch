#!/usr/bin/env python3
"""LuxOS - stranky Nastaveni Profilova fotka, Wi-Fi a Vychozi nastaveni aplikaci (drive luxos-profile-picture,
luxos-wifi-qr, luxos-app-reset): odkazy s argumenty (i druhe spusteni do bezici instance pres D-Bus), prikazove
rezimy bez okna, kamera vypnuta po odchodu ze stranky a po zavreni okna, a jeden ucinek kazde stranky pres UI.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_settings_ports_b.py -v

Kamera je videotestsrc (LUXOS_CAMERA_TEST), uzly video* jen v docasne slozce, AccountsService napodobena
(LUXOS_ACCOUNTS_FAKE), nmcli a luxos-camera falesne. Okno ve vlastnim Xvfb, vlastni sbernice relace.
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
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

import gi  # noqa: E402
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

TMP = None
BIN = {}
XVFB = None

NMCLI = ("#!/bin/sh\ncase \"$*\" in\n"
         "*--active*) echo '802-11-wireless:uuid-1:wlan0:Home' ;;\n"
         "*uuid*) printf '802-11-wireless.ssid:Home\\n802-11-wireless.hidden:no\\n"
         "802-11-wireless-security.key-mgmt:wpa-psk\\n802-11-wireless-security.psk:not-a-real-secret\\n' ;;\n"
         "*) exit 2 ;;\nesac\n")


def setUpModule():
    global TMP, XVFB
    TMP = tempfile.mkdtemp(prefix="luxos-ports-b-", dir=luxos_testguard._private_dir())
    for name in ("luxos-settings", "luxos-profile-picture", "luxos-wifi-qr", "luxos-app-reset"):
        BIN[name] = lsl_app.build(name, TMP)
    XVFB = lsl_app.Xvfb()


def tearDownModule():
    if XVFB:
        XVFB.stop()
    if TMP:
        shutil.rmtree(TMP, True)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(dir=TMP)
        self.videos = os.path.join(self.home, "dev")
        os.mkdir(self.videos)
        self.bin = os.path.join(self.home, "bin")
        os.mkdir(self.bin)
        # falesna Kamera: zapise argumenty
        self.camera_log = os.path.join(self.home, "camera-args")
        self.write_exec("luxos-camera", '#!/bin/sh\necho "$@" >> "%s"\n' % self.camera_log)
        self.write_exec("nmcli", NMCLI)
        self.face = os.path.join(self.home, ".face")
        self.fake = os.path.join(self.home, "accounts-icon")
        self.bus = lsl_app.Bus()
        self.addCleanup(self.bus.stop)
        self.app = None

    def tearDown(self):
        if self.app:
            self.app.stop()

    def write_exec(self, name, text):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o755)

    def env(self, display=True):
        env = dict(os.environ, HOME=self.home, XDG_CONFIG_HOME=os.path.join(self.home, ".config"),
                   XDG_CACHE_HOME=os.path.join(self.home, ".cache"), XDG_DATA_HOME="", LANG="C.UTF-8", LC_ALL="C.UTF-8",
                   LUXOS_ACCOUNTS_FAKE=self.fake, LUXOS_CAMERA_TEST="1", LUXOS_VIDEO_DEV_DIR=self.videos,
                   LUXOS_NMCLI=os.path.join(self.bin, "nmcli"), LUXOS_DESKTOP_DIRS=os.path.join(self.home, "no-apps"),
                   PATH=self.bin + os.pathsep + os.environ["PATH"], DBUS_SESSION_BUS_ADDRESS=self.bus.address,
                   LUXOS_I18N_DIR=lsl_app.I18N, NO_AT_BRIDGE="1")
        if display:
            env["DISPLAY"] = XVFB.display
        else:
            env.pop("DISPLAY", None)
        luxos_testguard.check_env(env)
        return env

    def start(self, name, *args, cwd=None):
        argv = [BIN[name], *args]
        if cwd:
            # App nema cwd: spusteni pres sh
            argv = ["sh", "-c", 'cd "$0" && exec "$@"', cwd] + argv
        self.app = lsl_app.App(argv, self.env())
        self.assertTrue(self.app.wait(lambda: self.app.dump()), self.app.stderr())

    def run_cli(self, name, *args, cwd=None, display=False):
        return subprocess.run([BIN[name], *args], env=self.env(display), cwd=cwd, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=60)

    def page(self):
        return json.loads(self.app.ask("state", "state"))["page"]

    def pst(self):
        return json.loads(self.app.ask("page-state", "page-state"))

    def titles(self):
        return [w["title"] for w in self.app.dump()]

    def photo(self, name="photo.png", w=600, h=400):
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, w, h)
        pb.fill(0x2060e0ff)
        pb.new_subpixbuf(0, 0, w // 2, h).fill(0xe03030ff)
        path = os.path.join(self.home, name)
        pb.savev(path, "png", [], [])
        return path

    def camera_calls(self):
        if not os.path.exists(self.camera_log):
            return []
        with open(self.camera_log) as f:
            return f.read().split("\n")[:-1]


class Profile(Fixture):
    def test_deep_link_relative_file(self):
        # luxos-settings profile SOUBOR: rovnou orez, relativni cesta vuci pracovnimu adresari
        self.photo("rel.png", 800, 400)
        self.start("luxos-settings", "profile", "rel.png", cwd=self.home)
        self.assertEqual(self.page(), "profile")
        self.assertTrue(self.app.wait(lambda: self.pst()["page"] == "crop"))
        self.assertEqual(self.pst()["size"], [800, 400])
        self.assertEqual(self.titles(), ["Profile Picture"])

    def test_second_launch_forwards_args(self):
        # Nastaveni uz bezi na jine strance: druhe spusteni jen preda argumenty (D-Bus) a skonci bez okna
        self.start("luxos-settings", "app-reset")
        self.assertEqual(self.page(), "app-reset")
        r = subprocess.run([BIN["luxos-profile-picture"], "--camera"], env=self.env(), capture_output=True,
                           text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.app.wait(lambda: self.page() == "profile"))
        self.assertTrue(self.app.wait(lambda: self.pst()["cam"] == "preview" and self.pst()["camera"]))
        self.assertEqual(self.titles(), ["Profile Picture"])
        # relativni cesta z jineho adresare nez bezici okno
        sub = os.path.join(self.home, "Pictures")
        os.mkdir(sub)
        shutil.move(self.photo("second.png", 500, 500), os.path.join(sub, "second.png"))
        r = subprocess.run([BIN["luxos-profile-picture"], "second.png"], env=self.env(), cwd=sub, capture_output=True,
                           text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.app.wait(lambda: self.pst()["page"] == "crop"))
        st = self.pst()
        self.assertEqual(st["size"], [500, 500])
        self.assertFalse(st["camera"], "orez zastavi kameru")

    def test_camera_stops_on_leave_and_close(self):
        self.start("luxos-profile-picture", "--camera")
        self.assertTrue(self.app.wait(lambda: self.pst()["cam"] == "preview" and self.pst()["camera"]))
        self.app.ask("page desktop")
        self.assertEqual(self.page(), "desktop")
        self.app.ask("page profile")
        st = self.pst()
        self.assertEqual((st["page"], st["camera"]), ("main", False))
        # znovu z tlacitka stranky
        self.app.ask("click Take Photo")
        self.assertTrue(self.app.wait(lambda: self.pst()["camera"]))
        self.app.ask("page desktop")
        self.app.ask("page profile")
        self.assertFalse(self.pst()["camera"])
        # zavreni okna s bezici kamerou: proces skonci cisto
        self.app.ask("click Take Photo")
        self.assertTrue(self.app.wait(lambda: self.pst()["camera"]))
        self.app.send("close")
        self.assertEqual(self.app.proc.wait(10), 0, self.app.stderr())

    def test_save_through_ui(self):
        # Vyfotit -> spoust -> orez -> Ulozit: ~/.face a AccountsService (falesna)
        self.start("luxos-settings", "profile")
        self.assertEqual(self.pst()["page"], "main")
        self.app.ask("click Take Photo")
        self.assertTrue(self.app.wait(lambda: self.pst()["shutter"]))
        # po prolnuti je tlacitko stranky skryte a "Take Photo" je spoust (tooltip)
        self.assertTrue(self.app.wait(lambda: not [w for w in lsl_app.widgets(self.app.dump())
                                                   if w.get("text") == "Take Photo" and w["vis"]]))
        self.app.ask("click Take Photo")
        self.assertTrue(self.app.wait(lambda: self.pst()["page"] == "crop"))
        self.app.ask("click Save")
        self.assertTrue(self.app.wait(lambda: os.path.isfile(self.face)))
        with open(self.fake) as f:
            self.assertEqual(f.read(), self.face)
        pb = GdkPixbuf.Pixbuf.new_from_file(self.face)
        self.assertEqual((pb.get_width(), pb.get_height()), (384, 384))
        hint = lsl_app.find(self.app.dump(), name="hint")["text"]
        self.assertEqual(hint, "Saved. The new picture appears on the login screen and in the menu.")


class Wifi(Fixture):
    def test_scan_cli_without_window(self):
        for name, args in (("luxos-wifi-qr", ["--scan"]), ("luxos-settings", ["wifi", "--scan"])):
            r = self.run_cli(name, *args)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.camera_calls(), ["--scan-wifi", "--scan-wifi"])

    def test_scan_button_and_copy(self):
        self.start("luxos-wifi-qr")
        self.assertEqual(self.page(), "wifi")
        self.assertTrue(self.app.wait(lambda: self.pst()["page"] == "qr"))
        self.assertEqual(lsl_app.find(self.app.dump(), name="ssid")["text"], "Home")
        self.app.ask("click Copy QR code image")
        self.assertTrue(self.pst()["clipboard"])
        # skenovani v Kamere; Nastaveni zustane otevrene
        self.app.ask("click Join a Network with a QR Code…")
        self.assertTrue(self.app.wait(lambda: self.camera_calls() == ["--scan-wifi"]))
        self.assertIsNone(self.app.proc.poll())
        # znovu zobrazena stranka nacte sit znovu
        self.app.ask("page desktop")
        self.app.ask("page wifi")
        self.assertTrue(self.app.wait(lambda: self.pst()["page"] == "qr"))


class AppReset(Fixture):
    def make_app_settings(self):
        os.makedirs(os.path.join(self.home, ".config/someapp"))
        with open(os.path.join(self.home, ".config/someapp/conf"), "w") as f:
            f.write("c")

    def backups(self):
        root = os.path.join(self.home, ".local/share/luxos/app-settings-backups")
        return sorted(os.listdir(root)) if os.path.isdir(root) else []

    def test_cli_without_window(self):
        self.make_app_settings()
        r = self.run_cli("luxos-settings", "app-reset", "list", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([a["key"] for a in json.loads(r.stdout)], ["someapp"])
        r = self.run_cli("luxos-app-reset", "reset", "someapp", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config/someapp")))
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(self.run_cli("luxos-app-reset", "bogus").returncode, 2)

    def test_reset_through_ui(self):
        self.make_app_settings()
        self.start("luxos-app-reset")
        self.assertEqual(self.page(), "app-reset")
        status = lambda: lsl_app.find(self.app.dump(), name="status")["text"]  # noqa: E731
        self.assertTrue(self.app.wait(lambda: status() == "1 apps with settings"))
        self.app.send("click Reset…")
        self.assertTrue(self.app.wait(lambda: "Reset the settings of someapp?" in lsl_app.texts(self.app.dump(), dialog=True)))
        self.app.send("click Reset")
        self.assertTrue(self.app.wait(lambda: "Settings of someapp were reset" in lsl_app.texts(self.app.dump(), dialog=True)))
        self.app.send("click OK")
        self.assertTrue(self.app.wait(lambda: status() == "0 apps with settings"))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config/someapp")))
        [name] = self.backups()
        with open(os.path.join(self.home, ".local/share/luxos/app-settings-backups", name, "config/someapp/conf")) as f:
            self.assertEqual(f.read(), "c")


if __name__ == "__main__":
    unittest.main()
