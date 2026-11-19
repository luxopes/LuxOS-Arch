#!/usr/bin/env python3
"""Zpetna vazba (luxos-feedback): co se z logu odstrani pred odeslanim a fronta neodeslanych hlaseni.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_feedback.py -v

Bez okna a bez site: testuji se jen funkce redact a flush_outbox z programu.
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
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(HERE, "..", "files", "bin", "luxos-feedback")
for d in (os.path.join(HERE, "..", "..", "luxos-i18n", "files"), os.path.join(HERE, "..", "..", "luxos-account", "files"),
          os.path.join(HERE, "..", "files", "python")):
    sys.path.insert(0, os.path.normpath(d))


def load():
    loader = importlib.machinery.SourceFileLoader("luxos_feedback", PROG)
    spec = importlib.util.spec_from_loader("luxos_feedback", loader)
    mod = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, [PROG]
    try:
        loader.exec_module(mod)
    finally:
        sys.argv = argv
    return mod


try:
    FB = load()
except (ImportError, ValueError):      # bez GTK
    FB = None


@unittest.skipIf(FB is None, "luxos-feedback needs python-gobject with Gtk 3")
class Redact(unittest.TestCase):
    def setUp(self):
        FB._wifi_cache["names"] = ["Domov Novak", "x"]

    def tearDown(self):
        FB._wifi_cache.clear()

    def test_ipv6(self):
        for addr in ("2001:db8:85a3::8a2e:370:7334", "fe80::1%wlan0", "2001:0db8:0000:0000:0000:ff00:0042:8329",
                     "::1", "[2a00:1028:9192:35c2::5]:443"):
            out = FB.redact("connect to " + addr + " failed")
            self.assertNotIn("db8", out)
            self.assertNotIn("35c2", out)
            self.assertIn("<ip>", out, addr)
        # casy a jine dvojtecky zustanou
        self.assertEqual(FB.redact("Nov 19 08:25:26 std::string a:b"), "Nov 19 08:25:26 std::string a:b")

    def test_ssid(self):
        out = FB.redact("wlan0: Trying to associate with SSID 'Kavarna U Lipy'")
        self.assertEqual(out, "wlan0: Trying to associate with SSID '<ssid>'")
        self.assertEqual(FB.redact('ssid="Moje sit" freq=2412'), 'ssid="<ssid>" freq=2412')
        self.assertEqual(FB.redact("device (wlan0): Activation: starting connection 'Domov Novak'"),
                         "device (wlan0): Activation: starting connection '<ssid>'")
        self.assertEqual(FB.redact("x y"), "x y")          # prilis kratke nazvy se nenahrazuji


@unittest.skipIf(FB is None, "luxos-feedback needs python-gobject with Gtk 3")
class Outbox(unittest.TestCase):
    def test_expired_sign_in_keeps_report(self):
        with tempfile.TemporaryDirectory() as d:
            FB.OUTBOX = d
            path = os.path.join(d, "1.json")
            with open(path, "w") as f:
                json.dump({"message": "x"}, f)
            orig = FB.send
            self.addCleanup(setattr, FB, "send", orig)
            for status, kept in ((401, True), (403, True), (400, False)):
                def send(_payload, status=status):
                    raise FB.acc.AccountError("unauthorized", status)
                FB.send = send
                self.assertEqual(FB.flush_outbox(), 0)
                self.assertEqual(os.path.exists(path), kept, status)
            self.assertTrue(os.path.exists(path + ".rejected"))


if __name__ == "__main__":
    unittest.main()
