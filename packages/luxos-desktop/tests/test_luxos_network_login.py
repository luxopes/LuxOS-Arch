"""Testy luxos-network-login (files/bin): okno prihlaseni do site s portalem jde otevrit znovu po
zavreni, bezi jen jednou (dalsi spusteni zvedne okno), adresa portalu ze stavu luxos-hub
($XDG_RUNTIME_DIR/luxos-portal), uklid profilu a pid souboru. Falesny firefox, gdbus, wmctrl,
getent a luxos-portal-check v PATH - zadna sit ani skutecny prohlizec.

Spusteni: python3 -m unittest packages/luxos-desktop/tests/test_luxos_network_login.py -v
"""
import glob
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "files", "bin", "luxos-network-login")

FAKE_FIREFOX = """#!/bin/bash
profile=""
while [[ $# -gt 1 ]]; do [[ $1 == --profile ]] && profile=$2; shift; done
echo "firefox $$ $profile $1" >>"$FAKE_LOG"
cp "$profile/user.js" "$FAKE_DIR/user.js.last"
exec sleep 60
"""


class NetworkLogin(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxos-netlogin-")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.run_dir = os.path.join(self.t, "run")
        os.mkdir(self.run_dir, 0o700)
        self.fake = os.path.join(self.t, "fake")
        os.mkdir(self.fake)
        self.log = os.path.join(self.t, "calls.log")
        progs = {"firefox": FAKE_FIREFOX,
                 "gdbus": "#!/bin/sh\nexit 1\n",
                 "getent": "#!/bin/sh\nexit 2\n",
                 "wmctrl": '#!/bin/sh\necho "wmctrl $*" >>"$FAKE_LOG"\n',
                 "luxos-portal-check": '#!/bin/sh\necho "luxos-portal-check" >>"$FAKE_LOG"\necho "${FAKE_PORTAL:-none}"\n'}
        for name, body in progs.items():
            path = os.path.join(self.fake, name)
            with open(path, "w") as f:
                f.write(body)
            os.chmod(path, 0o755)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        for pid in self.firefox_pids():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def env(self, **extra):
        env = {"PATH": self.fake + ":/usr/bin:/bin", "HOME": self.t, "XDG_RUNTIME_DIR": self.run_dir,
               "FAKE_LOG": self.log, "FAKE_DIR": self.t, "LANG": "C"}
        env.update(extra)
        return env

    def start(self, *args, **extra):
        p = subprocess.Popen(["bash", SCRIPT, *args], env=self.env(**extra))
        self.procs.append(p)
        return p

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().splitlines()

    def firefox_calls(self):
        return [c.split() for c in self.calls() if c.startswith("firefox ")]

    def firefox_pids(self):
        return [int(c[1]) for c in self.firefox_calls()]

    def wait_for(self, cond, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.05)
        return cond()

    def alive(self, pid):
        try:
            with open("/proc/%d/stat" % pid) as f:
                return f.read().split()[2] != "Z"
        except OSError:
            return False

    def test_reopen_after_closing_and_single_window(self):
        with open(os.path.join(self.run_dir, "luxos-portal"), "w") as f:
            f.write("http://login.portal.test/guest 10.5.0.2\n")
        first = self.start()
        self.assertTrue(self.wait_for(lambda: len(self.firefox_calls()) == 1))
        ff = self.firefox_calls()[0]
        # adresa a IP portalu ze stavu luxos-hub, bez nove kontroly; IP napevno jen v jednorazovem profilu
        self.assertEqual(ff[3], "http://login.portal.test/guest")
        self.assertNotIn("luxos-portal-check", self.calls())
        with open(os.path.join(self.t, "user.js.last")) as f:
            self.assertIn('user_pref("network.dns.forceResolve", "10.5.0.2");', f.read())
        pidfile = os.path.join(self.run_dir, "luxos-network-login.pid")
        with open(pidfile) as f:
            self.assertEqual(f.read().strip(), str(first.pid))
        # druhe spusteni (lista, Ovladaci centrum): jen zvedne okno, druhy prohlizec ne
        second = self.start()
        self.assertEqual(second.wait(5), 0)
        self.assertIn("wmctrl -x -a luxos-network-login", self.calls())
        self.assertEqual(len(self.firefox_calls()), 1)
        self.assertIsNone(first.poll())
        # uzivatel zavre okno (bez prihlaseni): skript skonci, uklidi profil i pid soubor
        os.kill(int(ff[1]), signal.SIGTERM)
        self.assertEqual(first.wait(5) in (0, 143), True)
        self.assertFalse(os.path.exists(ff[2]))
        self.assertFalse(os.path.exists(pidfile))
        # a jde otevrit znovu
        third = self.start()
        self.assertTrue(self.wait_for(lambda: len(self.firefox_calls()) == 2))
        self.assertEqual(self.firefox_calls()[1][3], "http://login.portal.test/guest")
        # luxos-hub ho po pripojeni zavre (SIGTERM podle pid souboru): konci i prohlizec
        with open(pidfile) as f:
            self.assertEqual(int(f.read()), third.pid)
        third.send_signal(signal.SIGTERM)
        third.wait(5)
        ff2 = self.firefox_calls()[1]
        self.assertTrue(self.wait_for(lambda: not self.alive(int(ff2[1]))))
        self.assertFalse(os.path.exists(ff2[2]))
        self.assertFalse(os.path.exists(pidfile))
        self.assertEqual(glob.glob(os.path.join(self.run_dir, "luxos-network-login.*")), [])

    def test_without_hub_state_asks_portal_check(self):
        p = self.start(FAKE_PORTAL="portal http://captive.test/login 10.9.0.1")
        self.assertTrue(self.wait_for(lambda: len(self.firefox_calls()) == 1))
        self.assertIn("luxos-portal-check", self.calls())
        self.assertEqual(self.firefox_calls()[0][3], "http://captive.test/login")
        p.send_signal(signal.SIGTERM)
        p.wait(5)

    def test_no_portal_opens_check_address(self):
        """Bez portalu (kontrola "none") a s neplatnym stavem: adresa kontroly pripojeni NetworkManageru."""
        with open(os.path.join(self.run_dir, "luxos-portal"), "w") as f:
            f.write("\n")
        p = self.start()
        self.assertTrue(self.wait_for(lambda: len(self.firefox_calls()) == 1))
        self.assertEqual(self.firefox_calls()[0][3], "http://ping.archlinux.org/nm-check.txt")
        with open(os.path.join(self.t, "user.js.last")) as f:
            self.assertNotIn("forceResolve", f.read())
        p.send_signal(signal.SIGTERM)
        p.wait(5)

    def test_explicit_url_from_hub(self):
        p = self.start("http://login.portal.test/x", "10.5.0.9")
        self.assertTrue(self.wait_for(lambda: len(self.firefox_calls()) == 1))
        self.assertEqual(self.firefox_calls()[0][3], "http://login.portal.test/x")
        self.assertNotIn("luxos-portal-check", self.calls())
        p.send_signal(signal.SIGTERM)
        p.wait(5)


if __name__ == "__main__":
    unittest.main()
