"""Politika D-Bus pro upozorneni pojistek (files/forkguard/cz.luxos.ForkGuard.conf): signaly
cz.luxos.ForkGuard a net.nuetzlich.SystemNotifications smi na systemovou sbernici poslat jen root
(forkguard) a skupina proc (earlyoom), ne bezny uzivatel. Overuje se na vlastnim dbus-daemon
s pravidly systemove sbernice; root a skupina proc se v kopii politiky nahradi aktualnim uzivatelem.

Spusteni: python3 -m unittest packages/luxos-desktop/tests/test_luxos_signal_policy.py -v
"""
import grp
import os
import pwd
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
POLICY = os.path.join(HERE, "..", "files", "forkguard", "cz.luxos.ForkGuard.conf")

BUS = """<busconfig>
  <type>system</type>
  <listen>unix:path=%s</listen>
  <policy context="default">
    <allow user="*"/>
    <allow own="*"/>
    <allow send_type="signal"/>
    <allow receive_type="signal"/>
    <allow send_destination="*"/>
    <allow receive_sender="*"/>
    <allow receive_type="method_return"/>
    <allow receive_type="error"/>
  </policy>
  <includedir>%s</includedir>
</busconfig>
"""

LISTEN = r"""
import sys
from gi.repository import Gio, GLib
c = Gio.DBusConnection.new_for_address_sync(sys.argv[1], Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                                            | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
loop = GLib.MainLoop()
def got(conn, sender, path, iface, member, params):
    print(iface, flush=True)
    if iface == "cz.luxos.Done":
        loop.quit()
c.signal_subscribe(None, None, None, None, None, 0, got)
print("ready", flush=True)
GLib.timeout_add(10000, loop.quit)
loop.run()
"""


@unittest.skipUnless(shutil.which("dbus-daemon") and shutil.which("dbus-send"), "chybi dbus-daemon/dbus-send")
class SignalPolicy(unittest.TestCase):
    def received(self, policy_text):
        """Posle oba signaly pojistek a kontrolni signal; vrati mnozinu prijatych rozhrani."""
        tmp = tempfile.mkdtemp(prefix="luxos-sigpol-")
        self.addCleanup(shutil.rmtree, tmp, True)
        os.mkdir(os.path.join(tmp, "system.d"))
        with open(os.path.join(tmp, "system.d", "cz.luxos.ForkGuard.conf"), "w") as f:
            f.write(policy_text)
        sock = os.path.join(tmp, "bus")
        with open(os.path.join(tmp, "bus.conf"), "w") as f:
            f.write(BUS % (sock, os.path.join(tmp, "system.d")))
        bus = subprocess.Popen(["dbus-daemon", "--config-file", os.path.join(tmp, "bus.conf"), "--nofork"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(bus.wait)
        self.addCleanup(bus.terminate)
        for _ in range(100):
            if os.path.exists(sock):
                break
            time.sleep(0.05)
        addr = "unix:path=" + sock
        lis = subprocess.Popen(["python3", "-c", LISTEN, addr], stdout=subprocess.PIPE, text=True)
        self.assertEqual(lis.stdout.readline().strip(), "ready")
        send = ["dbus-send", "--bus=" + addr, "--type=signal"]
        subprocess.run(send + ["/cz/luxos/ForkGuard", "cz.luxos.ForkGuard.Stopped",
                               "string:podvrh", "uint32:1", "uint32:%d" % os.getuid()], check=True)
        subprocess.run(send + ["/", "net.nuetzlich.SystemNotifications.Notify", "string:process 1 podvrh",
                               "string:"], check=True)
        subprocess.run(send + ["/", "cz.luxos.Done.Ping"], check=True)
        out, _ = lis.communicate(timeout=15)
        got = set(out.split())
        self.assertIn("cz.luxos.Done", got)
        return got

    def policy(self):
        with open(POLICY) as f:
            return f.read()

    def test_ordinary_user_cannot_send(self):
        if os.getuid() == 0:
            self.skipTest("bezi jako root")
        got = self.received(self.policy())
        self.assertNotIn("cz.luxos.ForkGuard", got)
        self.assertNotIn("net.nuetzlich.SystemNotifications", got)

    def test_guards_can_send(self):
        me = pwd.getpwuid(os.getuid()).pw_name
        group = grp.getgrgid(os.getgid()).gr_name
        text = self.policy().replace('user="root"', 'user="%s"' % me)
        got = self.received(text)
        self.assertIn("cz.luxos.ForkGuard", got)
        self.assertIn("net.nuetzlich.SystemNotifications", got)
        # earlyoom: jen skupina proc (bez prava roota)
        text = self.policy().replace('<policy user="root">', '<policy user="nikdo-takovy">')
        text = text.replace('group="proc"', 'group="%s"' % group)
        got = self.received(text)
        self.assertNotIn("cz.luxos.ForkGuard", got)
        self.assertIn("net.nuetzlich.SystemNotifications", got)


if __name__ == "__main__":
    unittest.main()
