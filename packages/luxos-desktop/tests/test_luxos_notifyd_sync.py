#!/usr/bin/env python3
"""LuxOS - historie oznameni synchronizovana s aplikacemi (GTK modul files/src/luxos-notifyd.c).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_notifyd_sync.py -v

Skutecny xfce4-notifyd na vlastnim Xvfb a vlastni sbernici, docasna konfigurace a data (relace
uzivatele se nemeni). Testovaci "aplikace" (Python, Gio) posila oznameni jako Posta (x-luxos-keep,
vychozi akce, desktop-entry) a overuje se:
  - aplikace oznameni zavre (CloseNotification) -> zaznam zmizi z historie; ostatni zustanou,
  - nahrazeni stejnym id a zavreni -> v historii nic nezbyde,
  - Activate(log_id) dokud aplikace bezi: aplikace dostane ActionInvoked(id, "default"), zaznam zmizi,
  - Activate neznameho zaznamu / po ukonceni aplikace / po zavreni uzivatelem -> false (okno pak
    otevre aplikaci samo),
  - oznameni bez x-luxos-keep (do historie nepatri) nepriradi svou odpoved cizimu zaznamu.
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
SRC = os.path.join(HERE, "..", "files", "src", "luxos-notifyd.c")
NOTIFYD = "/usr/lib/xfce4/notifyd/xfce4-notifyd"


# Sbernice bez aktivace sluzeb: jinak by si volani na org.freedesktop.Notifications samo spustilo
# xfce4-notifyd (bez modulu, s prostredim sbernice) a testovane by skoncilo "Another daemon is running"
BUS_CONF = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:tmpdir=%s</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""


def have_tools():
    if not (os.path.exists(NOTIFYD) and shutil.which("Xvfb") and shutil.which("dbus-daemon") and shutil.which("gcc")):
        return False
    return subprocess.run(["pkg-config", "--exists", "gtk+-3.0"]).returncode == 0


# Testovaci aplikace: prikazy na stdin (JSON), odpovedi na stdout; zaznamenava ActionInvoked
APP_PY = r'''
import json, sys, threading
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
events = []
bus.signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications", "ActionInvoked",
                     "/org/freedesktop/Notifications", None, 0,
                     lambda c, s, p, i, n, v: events.append(["action", v.unpack()[0], v.unpack()[1]]))
bus.signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications", "NotificationClosed",
                     "/org/freedesktop/Notifications", None, 0,
                     lambda c, s, p, i, n, v: events.append(["closed", v.unpack()[0], v.unpack()[1]]))

def call(iface, path, method, sig, args, dest="org.freedesktop.Notifications"):
    r = bus.call_sync(dest, path, iface, method, GLib.Variant(sig, tuple(args)), None, 0, 5000, None)
    return r.unpack() if r is not None else None

def handle(line):
    cmd = json.loads(line)
    op = cmd["op"]
    if op == "notify":
        hints = {"desktop-entry": GLib.Variant("s", "luxos-mail")}
        if cmd.get("keep", True):
            hints["x-luxos-keep"] = GLib.Variant("b", True)
        out = call("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "Notify", "(susssasa{sv}i)",
                   ["Mail", cmd.get("replaces", 0), "luxos-mail", cmd["summary"], "Text", ["default", "Open"], hints, 0])
        return out[0]
    if op == "close":
        call("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "CloseNotification", "(u)", [cmd["id"]])
        return True
    if op == "list":
        return [[e[0], e[6]] for e in call("org.xfce.Notifyd.Log", "/org/xfce/Notifyd", "List", "(sub)", ["", 50, False],
                                          dest="org.xfce.Notifyd")[0]]
    if op == "activate":
        return call("cz.luxos.NotificationHistory", "/cz/luxos/NotificationHistory", "Activate", "(s)", [cmd["log"]])[0]
    if op == "events":
        return events
    return None

def reader():
    for line in sys.stdin:
        result = {}
        def run():
            try:
                result["v"] = handle(line)
            except Exception as e:
                result["v"] = "error: %s" % e
            done.set()
        done = threading.Event()
        GLib.idle_add(lambda: (run(), False)[1])
        done.wait(10)
        print(json.dumps(result.get("v")), flush=True)
    GLib.idle_add(loop.quit)

loop = GLib.MainLoop()
threading.Thread(target=reader, daemon=True).start()
print(json.dumps("ready"), flush=True)
loop.run()
'''


@unittest.skipUnless(have_tools(), "needs xfce4-notifyd, Xvfb, dbus-daemon and gtk3 headers")
class NotifydSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.mkdtemp(prefix="luxos-notifyd-sync-")
        cls.module = os.path.join(cls.t, "libluxos-notifyd.so")
        flags = subprocess.run(["pkg-config", "--cflags", "--libs", "gtk+-3.0"], capture_output=True, text=True,
                               check=True).stdout.split()
        subprocess.run(["gcc", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC", "-o", cls.module, SRC, *flags],
                       check=True)
        with open(os.path.join(cls.t, "app.py"), "w") as f:
            f.write(APP_PY)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.t, True)

    def setUp(self):
        self.procs = []
        d = tempfile.mkdtemp(dir=self.t)
        for sub in ("config", "data", "cache", "run"):
            os.makedirs(os.path.join(d, sub), mode=0o700)
        self.xvfb = subprocess.Popen(["Xvfb", ":85", "-screen", "0", "1280x800x24", "-nolisten", "tcp", "-noreset"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(self.xvfb)
        time.sleep(0.8)
        self.testlog = os.path.join(d, "module.log")
        # vse (i sbernice) s docasnym domovem a testovacim displejem - nikdy relace uzivatele
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("DBUS_", "XDG_", "WAYLAND", "SESSION_MANAGER", "XAUTHORITY", "GTK_", "DISPLAY"))}
        env.update(HOME=d, DISPLAY=":85", XDG_CONFIG_HOME=os.path.join(d, "config"),
                   XDG_DATA_HOME=os.path.join(d, "data"), XDG_CACHE_HOME=os.path.join(d, "cache"),
                   XDG_RUNTIME_DIR=os.path.join(d, "run"), NO_AT_BRIDGE="1",
                   GIO_USE_VFS="local", LUXOS_NOTIFYD_TEST_LOG=self.testlog)
        # historii oznameni zapina az vychozi nastaveni LuxOS (/etc/xdg/luxos, jen cteni)
        env["XDG_CONFIG_DIRS"] = "/etc/xdg/luxos:/etc/xdg"
        conf = os.path.join(d, "bus.conf")
        with open(conf, "w") as f:
            f.write(BUS_CONF % os.path.join(d, "run"))
        bus = subprocess.Popen(["dbus-daemon", "--config-file", conf, "--nofork", "--print-address"], env=env,
                               stdout=subprocess.PIPE, text=True)
        self.procs.append(bus)
        env["DBUS_SESSION_BUS_ADDRESS"] = bus.stdout.readline().strip()
        self.env = env
        xfconfd = subprocess.Popen(["/usr/lib/xfce4/xfconf/xfconfd"], env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        self.procs.append(xfconfd)
        self.notifyd_err = os.path.join(d, "notifyd.err")
        notifyd = subprocess.Popen([NOTIFYD], env=dict(env, GTK_MODULES=self.module), stdout=subprocess.DEVNULL,
                                   stderr=self.errfile())
        self.procs.append(notifyd)
        self.app = self.start_app()
        end = time.time() + 10
        while time.time() < end and self.cmd("list") is None:
            time.sleep(0.2)

    def errfile(self):
        f = open(self.notifyd_err, "w")
        self.addCleanup(f.close)
        return f

    def start_app(self):
        app = subprocess.Popen([sys.executable, os.path.join(self.t, "app.py")], env=self.env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True)
        self.procs.append(app)
        self.assertEqual(json.loads(app.stdout.readline()), "ready")
        return app

    def tearDown(self):
        for p in reversed(self.procs):
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()

    def cmd(self, op, app=None, **kw):
        app = app or self.app
        app.stdin.write(json.dumps(dict(kw, op=op)) + "\n")
        app.stdin.flush()
        value = json.loads(app.stdout.readline())
        if isinstance(value, str) and value.startswith("error"):
            return None if op == "list" else value
        return value

    def summaries(self):
        return [e[1] for e in self.cmd("list")]

    def log_id(self, summary):
        return [e[0] for e in self.cmd("list") if e[1] == summary][0]

    def wait_for(self, check, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            if check():
                return True
            time.sleep(0.1)
        return check()

    def test_closed_by_app_disappears_from_history(self):
        a = self.cmd("notify", summary="Nova posta A")
        self.cmd("notify", summary="Nova posta B")
        self.assertTrue(self.wait_for(lambda: set(self.summaries()) == {"Nova posta A", "Nova posta B"}),
                        self.summaries())
        self.cmd("close", id=a)
        self.assertTrue(self.wait_for(lambda: self.summaries() == ["Nova posta B"]), self.summaries())

    def test_replaced_then_closed_leaves_nothing(self):
        a = self.cmd("notify", summary="Nova posta od X")
        self.assertEqual(self.cmd("notify", summary="Nove zpravy: 2", replaces=a), a)
        self.assertTrue(self.wait_for(lambda: self.summaries() == ["Nove zpravy: 2"]), self.summaries())
        self.cmd("close", id=a)
        self.assertTrue(self.wait_for(lambda: self.summaries() == []), self.summaries())

    def test_activate_invokes_default_action_and_removes(self):
        a = self.cmd("notify", summary="Klik")
        self.assertTrue(self.wait_for(lambda: "Klik" in self.summaries()))
        self.assertIs(self.cmd("activate", log=self.log_id("Klik")), True)
        self.assertTrue(self.wait_for(lambda: ["action", a, "default"] in self.cmd("events")), self.cmd("events"))
        self.assertTrue(self.wait_for(lambda: self.summaries() == []), self.summaries())

    def test_activate_falls_back_when_app_cannot_handle(self):
        self.assertIs(self.cmd("activate", log="neexistuje"), False)
        # aplikace skoncila: akce by nikdo neprevzal
        other = self.start_app()
        self.cmd("notify", app=other, summary="Bez aplikace")
        self.assertTrue(self.wait_for(lambda: "Bez aplikace" in self.summaries()))
        other.stdin.close()
        other.wait(timeout=10)
        self.assertIs(self.cmd("activate", log=self.log_id("Bez aplikace")), False)
        self.assertIn("Bez aplikace", self.summaries(), "zaznam zustane (okno ho smaze po otevreni aplikace)")

    def test_not_kept_notification_does_not_steal_mapping(self):
        self.cmd("notify", summary="Jen bublina", keep=False)
        b = self.cmd("notify", summary="Do historie")
        self.assertTrue(self.wait_for(lambda: self.summaries() == ["Do historie"]), self.summaries())
        self.cmd("close", id=b)
        self.assertTrue(self.wait_for(lambda: self.summaries() == []), self.summaries())


if __name__ == "__main__":
    unittest.main()
