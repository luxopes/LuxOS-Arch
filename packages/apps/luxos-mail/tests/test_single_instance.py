"""Jedna sluzba luxos-mail na data: dve relace stejneho uzivatele s jinym HOME (test, sandbox, druhy ucet dat)
maji kazda svou sluzbu a zadna nedostava pozadavky druhe; druhe spusteni nad stejnymi daty jen skonci a prvni
sluzba bezi dal. Bez LUXOS_MAIL_INSTANCE (vychozi jmena socketu; data testu jsou v docasnem HOME).
"""
import os
import socket
import sys
import time
import unittest
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailtest as mt  # noqa: E402


def short_hash(text):
    """Stejny otisk jako luxos_sys.short_hash (dva soucty po znacich)."""
    a = b = 0
    for ch in text:
        a = (a * 31 + ord(ch)) % 2147483647
        b = (b * 1000003 + ord(ch)) % 2147483629
    return "%d-%d" % (a, b)


def service_name(s):
    return "\0luxos-mail-%d-%s" % (os.getuid(), short_hash(os.path.join(s.env["XDG_DATA_HOME"], "luxos-mail")))


def reachable(s):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
        try:
            c.connect(service_name(s))
            return True
        except OSError:
            return False


class SingleService(unittest.TestCase):
    def setUp(self):
        self.sessions = []
        for _ in range(2):
            s = mt.Session(keyring=False, notifications=False)
            s.env.pop("LUXOS_MAIL_INSTANCE")
            self.addCleanup(s.close)
            self.sessions.append(s)

    def start(self, s):
        p = subprocess.Popen([mt.binary(), "--background"], env=s.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        s.procs.append(p)
        return p

    def wait_for(self, check, timeout=10):
        end = time.time() + timeout
        while time.time() < end and not check():
            time.sleep(0.05)
        return check()

    def test_two_homes_two_services(self):
        a, b = self.sessions
        pa = self.start(a)
        self.assertTrue(self.wait_for(lambda: reachable(a)), "sluzba A posloucha")
        self.assertFalse(reachable(b), "relace B sluzbu A nenajde")
        pb = self.start(b)
        self.assertTrue(self.wait_for(lambda: reachable(b)), "relace B ma vlastni sluzbu")
        # druhe spusteni nad daty A: skonci, A i B bezi dal
        again = self.start(a)
        self.assertEqual(again.wait(timeout=10), 0)
        time.sleep(0.3)
        self.assertIsNone(pa.poll(), "sluzba A bezi")
        self.assertIsNone(pb.poll(), "sluzba B bezi")
        self.assertTrue(reachable(a) and reachable(b))


if __name__ == "__main__":
    unittest.main()
