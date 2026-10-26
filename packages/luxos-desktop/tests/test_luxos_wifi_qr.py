#!/usr/bin/env python3
"""LuxOS - testy QR kodu Wi-Fi: text WIFI: (escapovani), udaje z NetworkManageru, zxing-cpp a okna.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_wifi_qr.py -v
    env -u DISPLAY xvfb-run -a -s "-screen 0 1280x900x24" python3 -m unittest packages/luxos-desktop/tests/test_luxos_wifi_qr.py -v

nmcli a pkexec jsou falesne (LUXOS_NMCLI, LUXOS_PKEXEC) - na skutecnou sit ani hesla se nesahne.
Kodovani a cteni QR kodu potrebuje libZXing (zxing-cpp; jinak LUXOS_ZXING_LIB=/cesta/libZXing.so.4).
Okna (luxos-wifi-qr, luxos-camera --scan-wifi s testovaci kamerou) jen pod xvfb-run; snimky do
LUXOS_TEST_SHOTS (je-li nastaveno).
"""
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
PYDIR = os.path.join(ROOT, "luxos-desktop", "files", "python")
BIN = os.path.join(ROOT, "luxos-desktop", "files", "bin")
sys.path.insert(0, PYDIR)
sys.path.insert(1, os.path.join(ROOT, "luxos-i18n", "files"))

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
if "connection" in args and "uuid" in args:
    secrets = "--show-secrets" in args and (state != "nosecrets" or os.environ.get("FAKE_ROOT"))
    print("802-11-wireless.ssid:Kavárna:1")
    print("802-11-wireless.hidden:no")
    print("802-11-wireless-security.key-mgmt:" + ("wpa-eap" if state == "eap" else "wpa-psk"))
    print("802-11-wireless-security.psk:" + ("tajne;heslo,\\1" if secrets else ""))
    print("802-11-wireless-security.wep-key0:")
    sys.exit(0)
if "connect" in args:
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

import luxos_qr as qr  # noqa: E402

HAVE_ZXING = qr.available()
UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")


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


def render(matrix, scale=6, quiet=4, mirror=False):
    """Matice QR -> obrazek Lum (bajty, sirka) s okrajem."""
    n = len(matrix)
    size = (n + 2 * quiet) * scale
    img = bytearray([255]) * (size * size)
    for y, row in enumerate(matrix):
        for x, v in enumerate(row[::-1] if mirror else row):
            if v:
                for dy in range(scale):
                    start = ((y + quiet) * scale + dy) * size + (x + quiet) * scale
                    img[start:start + scale] = b"\0" * scale
    return bytes(img), size


class TestPayload(unittest.TestCase):
    def test_escape(self):
        self.assertEqual(qr.escape('a\\b;c,d:e"f'), 'a\\\\b\\;c\\,d\\:e\\"f')
        self.assertEqual(qr.escape("Kavárna 5G"), "Kavárna 5G")

    def test_payloads(self):
        self.assertEqual(qr.wifi_payload("Home", "secret"), "WIFI:T:WPA;S:Home;P:secret;;")
        self.assertEqual(qr.wifi_payload("Home", "x", "SAE"), "WIFI:T:SAE;S:Home;P:x;;")
        self.assertEqual(qr.wifi_payload("Cafe", "ignored", "nopass"), "WIFI:T:nopass;S:Cafe;;")
        self.assertEqual(qr.wifi_payload("Old", "12345", "WEP", hidden=True), "WIFI:T:WEP;S:Old;P:12345;H:true;;")
        self.assertEqual(qr.wifi_payload("a;b", 'p"w\\'), 'WIFI:T:WPA;S:a\\;b;P:p\\"w\\\\;;')
        with self.assertRaises(ValueError):
            qr.wifi_payload("x", "y", "WPA-EAP")

    def test_parse(self):
        self.assertEqual(qr.parse_wifi("WIFI:T:WPA;S:Home;P:secret;;"),
                         {"ssid": "Home", "password": "secret", "security": "WPA", "hidden": False})
        # libovolne poradi, mala pismena, H:true, chybejici T
        self.assertEqual(qr.parse_wifi("wifi:S:Net;H:true;P:pw;;"),
                         {"ssid": "Net", "password": "pw", "security": "WPA", "hidden": True})
        self.assertEqual(qr.parse_wifi("WIFI:S:Open;;")["security"], "nopass")
        self.assertEqual(qr.parse_wifi("WIFI:T:nopass;S:Open;P:;;")["password"], "")
        self.assertEqual(qr.parse_wifi("WIFI:T:WPA2;S:x;P:y;;")["security"], "WPA")
        self.assertEqual(qr.parse_wifi("WIFI:T:WPA3;S:x;P:y;;")["security"], "SAE")
        # hexadecimalni retezec v uvozovkach (ZXing)
        self.assertEqual(qr.parse_wifi('WIFI:T:WPA;S:"0123ABCD";P:"pass";;')["ssid"], "0123ABCD")
        self.assertEqual(qr.parse_wifi('WIFI:T:WPA;S:a\\"b\\";P:x;;')["ssid"], 'a"b"')
        for bad in ("", "https://luxos.example/", "WIFI:;", "WIFI:T:WPA;P:x;;", None):
            self.assertIsNone(qr.parse_wifi(bad), bad)

    def test_round_trip(self):
        for ssid, pw, sec, hidden in (("Kavárna;1", "tajne;heslo,\\1", "WPA", False),
                                      ('"quoted"', ':colon:', "SAE", True),
                                      ("Чай", "пароль", "WPA", False),
                                      ("Free", "", "nopass", False)):
            info = qr.parse_wifi(qr.wifi_payload(ssid, pw, sec, hidden))
            self.assertEqual(info, {"ssid": ssid, "password": pw, "security": sec, "hidden": hidden})

    def test_security_types(self):
        self.assertEqual(qr.security_type("wpa-psk"), "WPA")
        self.assertEqual(qr.security_type("sae"), "SAE")
        self.assertEqual(qr.security_type("none"), "WEP")
        self.assertEqual(qr.security_type("owe"), "nopass")
        self.assertEqual(qr.security_type(""), "nopass")
        self.assertIsNone(qr.security_type("wpa-eap"))

    def test_connect_args(self):
        self.assertEqual(qr.connect_args({"ssid": "A", "password": "p", "security": "WPA"}),
                         ["device", "wifi", "connect", "A", "password", "p"])
        self.assertEqual(qr.connect_args({"ssid": "A", "password": "", "security": "nopass", "hidden": True}),
                         ["device", "wifi", "connect", "A", "hidden", "yes"])
        self.assertEqual(qr.connect_args({"ssid": "A", "password": "k", "security": "WEP"})[-2:],
                         ["wep-key-type", "key"])


class TestNetworkManager(unittest.TestCase):
    def test_terse_split(self):
        self.assertEqual(qr._split_terse("802-11-wireless:u:wlan0:Ka\\:fe\\\\x"),
                         ["802-11-wireless", "u", "wlan0", "Ka:fe\\x"])

    def test_active_and_details(self):
        set_state("connected")
        act = qr.active_wifi()
        self.assertEqual(act, {"uuid": "uuid-1", "device": "wlan0", "name": "Kavárna:1"})
        info, err = qr.wifi_details("uuid-1")
        self.assertIsNone(err)
        self.assertEqual(info["ssid"], "Kavárna:1")
        self.assertEqual(info["password"], "tajne;heslo,\\1")
        self.assertEqual(info["security"], "WPA")
        self.assertFalse(info["need_auth"])
        self.assertIn("--show-secrets", nm_calls()[-1])

    def test_secrets_need_admin(self):
        set_state("nosecrets")
        info, err = qr.wifi_details("uuid-1")
        self.assertTrue(info["need_auth"])
        info, err = qr.wifi_details("uuid-1", root=True)
        self.assertFalse(info["need_auth"])
        self.assertEqual(nm_calls()[-1][0].split(" ")[0], "root")
        os.environ["FAKE_PKEXEC_CANCEL"] = "1"
        try:
            self.assertEqual(qr.wifi_details("uuid-1", root=True), (None, "cancelled"))
        finally:
            del os.environ["FAKE_PKEXEC_CANCEL"]

    def test_enterprise_and_wired(self):
        set_state("eap")
        info, _err = qr.wifi_details("uuid-1")
        self.assertIsNone(info["security"])
        set_state("wired")
        self.assertIsNone(qr.active_wifi())

    def test_connect(self):
        set_state("connected")
        ok, _msg = qr.connect({"ssid": "Kavárna", "password": "p;w", "security": "WPA"})
        self.assertTrue(ok)
        self.assertEqual(nm_calls()[-1], ["--wait", "60", "device", "wifi", "connect", "Kavárna", "password", "p;w"])
        set_state("connectfail")
        ok, msg = qr.connect({"ssid": "X", "password": "bad", "security": "WPA"})
        self.assertFalse(ok)
        self.assertIn("Secrets were required", msg)


@unittest.skipUnless(HAVE_ZXING, "needs libZXing (zxing-cpp) or LUXOS_ZXING_LIB")
class TestZXing(unittest.TestCase):
    def test_round_trip(self):
        for text in ("WIFI:T:WPA;S:Home;P:secret;;", qr.wifi_payload("Čajovna \\;x", "heslo:ěščř", "SAE", True)):
            matrix = qr.encode(text)
            self.assertEqual(len(matrix), len(matrix[0]))
            self.assertGreaterEqual(len(matrix), 21)
            img, size = render(matrix)
            self.assertEqual(qr.decode(img, size, size), [text])

    def test_mirrored_and_bgra(self):
        text = qr.wifi_payload("Mirror", "image")
        img, size = render(qr.encode(text), mirror=True)
        self.assertEqual(qr.decode(img, size, size), [text])      # zrcadleny nahled kamery
        bgra = bytes(b for px in img for b in (px, px, px, 255))
        self.assertEqual(qr.decode(bgra, size, size, qr.FORMAT_BGRA), [text])

    def test_nothing_found(self):
        self.assertEqual(qr.decode(b"\xff" * (100 * 100), 100, 100), [])
        self.assertEqual(qr.decode(b"\xff" * 10, 100, 100), [])      # kratky buffer


def load_program(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@unittest.skipUnless(UNDER_XVFB, "GUI only under xvfb-run (never on a real display)")
@unittest.skipUnless(HAVE_ZXING, "needs libZXing (zxing-cpp) or LUXOS_ZXING_LIB")
class TestWindows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["LUXOS_CAMERA_TEST"] = "1"
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("Gst", "1.0")
        from gi.repository import Gdk, Gst, Gtk
        cls.Gtk, cls.Gdk = Gtk, Gdk
        if Gdk.Screen.get_default() is None:      # Gio.TestDBus jineho testu zrusi DISPLAY
            raise unittest.SkipTest("no X display (run this file on its own under xvfb-run)")
        Gst.init(None)
        cls.share = load_program("luxos_wifi_qr_app", os.path.join(BIN, "luxos-wifi-qr"))
        cls.camera = load_program("luxos_camera_app", os.path.join(BIN, "luxos-camera"))
        for css in (cls.share.CSS, cls.camera.CSS):
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def pump(self, cond, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            while self.Gtk.events_pending():
                self.Gtk.main_iteration_do(False)
            if cond():
                return True
            time.sleep(0.02)
        return False

    def grab(self, window):
        self.pump(lambda: False, 0.4)
        gw = window.get_window()
        return self.Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())

    def shot(self, window, name):
        out = os.environ.get("LUXOS_TEST_SHOTS")
        if out:
            os.makedirs(out, exist_ok=True)
            self.grab(window).savev(os.path.join(out, name), "png", [], [])

    def test_share_window_shows_scannable_code(self):
        set_state("connected")
        win = self.share.QRWindow()
        win.show_all()
        self.addCleanup(win.destroy)
        self.assertTrue(win.get_titlebar().get_visible() and win.get_titlebar().get_show_close_button())
        self.assertTrue(self.pump(lambda: win.stack.get_visible_child_name() == "qr"))
        self.assertEqual(win.ssid_label.get_text(), "Kavárna:1")
        self.assertFalse(win.pw_entry.get_visibility())
        # QR kod v okne se da skutecne precist a obsahuje sit s heslem
        pix = self.grab(win)
        self.shot(win, "wifi-qr-share.png")
        rgba = pix.add_alpha(False, 0, 0, 0)
        texts = qr.decode(rgba.get_pixels(), rgba.get_width(), rgba.get_height(), qr.FORMAT_RGBA,
                          stride=rgba.get_rowstride())
        self.assertEqual([qr.parse_wifi(t) for t in texts],
                         [{"ssid": "Kavárna:1", "password": "tajne;heslo,\\1", "security": "WPA", "hidden": False}])
        win.copy_image(None)
        self.assertTrue(self.Gtk.Clipboard.get(self.Gdk.SELECTION_CLIPBOARD).wait_is_image_available())

    def test_share_window_states(self):
        set_state("nosecrets")
        win = self.share.QRWindow()
        win.show_all()
        self.addCleanup(win.destroy)
        self.assertTrue(self.pump(lambda: win.unlock_btn.get_visible()))
        self.shot(win, "wifi-qr-admin.png")
        win.unlock_btn.clicked()                    # pkexec nmcli (falesne)
        self.assertTrue(self.pump(lambda: win.stack.get_visible_child_name() == "qr"))
        set_state("wired")
        win.load()
        self.assertTrue(self.pump(lambda: win.state_title.get_text() == self.share._("Not connected to Wi-Fi")))
        self.assertTrue(win.scan_btn.get_visible())
        set_state("eap")
        win.load()
        self.assertTrue(self.pump(lambda: "802.1X" in win.state_hint.get_text()))

    def test_camera_scan_and_join(self):
        set_state("connected")
        import cairo
        payload = qr.wifi_payload("Kavárna", "tajne;heslo")
        matrix = qr.encode(payload)
        n, scale = len(matrix), 10
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 640, 480)
        cr = cairo.Context(surf)
        cr.set_source_rgb(0.85, 0.82, 0.78)      # "stul" za papirem
        cr.paint()
        x0, y0 = (640 - n * scale) // 2, (480 - n * scale) // 2
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(x0 - 40, y0 - 40, n * scale + 80, n * scale + 80)
        cr.fill()
        cr.set_source_rgb(0, 0, 0)
        for y, row in enumerate(matrix):
            for x, v in enumerate(row):
                if v:
                    cr.rectangle(x0 + x * scale, y0 + y * scale, scale, scale)
        cr.fill()
        image = os.path.join(TMP, "qr.png")
        surf.write_to_png(image)
        self.camera.TEST_IMAGE = image

        answers = []
        orig = self.camera.CameraWindow.scan_result

        def scan_result(window, texts):
            if texts and not answers:
                self.assertEqual(window.state, "preview")
                self.shot(window, "wifi-qr-scan-preview.png")     # pred dialogem (bez WM by ho prekryl)
            res = orig(window, texts)
            for w in self.Gtk.Window.list_toplevels():
                if isinstance(w, self.Gtk.MessageDialog) and w.get_visible() and not answers:
                    answers.append(w.get_property("text"))
                    self.shot(w, "wifi-qr-scan-dialog.png")
                    w.response(self.Gtk.ResponseType.OK)
            return res
        self.camera.CameraWindow.scan_result = scan_result
        self.addCleanup(setattr, self.camera.CameraWindow, "scan_result", orig)
        win = self.camera.CameraWindow(scan=True)
        win.show_all()
        self.addCleanup(win.destroy)
        self.assertEqual(win.get_title(), self.camera._("Join Wi-Fi with QR Code"))
        self.assertTrue(self.pump(lambda: win.state == "connected", 20), win.state)
        self.assertIn("Kavárna", answers[0])
        connect = [c for c in nm_calls() if "connect" in c]
        self.assertEqual(connect, [["--wait", "60", "device", "wifi", "connect", "Kavárna", "password", "tajne;heslo"]])
        self.shot(win, "wifi-qr-scan-connected.png")


if __name__ == "__main__":
    unittest.main()
