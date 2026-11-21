#!/usr/bin/env python3
"""Agent polkitu na Waylandu (files/lsl/luxos-polkit.lsl) proti beznemu labwc headless z harnessu WP-1.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -p MemorySwapMax=0 -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_polkit_wl.py -v

Systemova sbernice je soukromy dbus-daemon. Authority polkitd hraje tento skript (rezim `authority`, samostatny
proces s Gio): prijme RegisterAuthenticationAgent a na prikaz ze stdin vola BeginAuthentication/CancelAuthentication.
Pomocnika polkitu hraje soket v testu (LUXOS_POLKIT_SOCKET, radkovy protokol polkit 128) nebo skript
(LUXOS_POLKIT_HELPER, spusteny pomocnik). Heslo se pise pres `wlt input` do okna agenta.
"""
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
REPO = PKG.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test") / "sysroot")
HAVE_LABWC = (SYSROOT / "usr/bin/labwc").exists() or shutil.which("labwc")
HAVE_DBUS = shutil.which("dbus-daemon")
SECRET = "correct horse"
SESSION_ID = "c7"
NAME = "org.freedesktop.PolicyKit1"
AUTH_PATH = "/org/freedesktop/PolicyKit1/Authority"
AGENT_IFACE = "org.freedesktop.PolicyKit1.AuthenticationAgent"
# PAM_TEXT_INFO po cesku tak, jak ho posila pomocnik (g_strescape: UTF-8 jako osmickove kody)
INFO_TEXT = "Heslo vyprší za 3 dny"
INFO_ESCAPED = "".join(c if ord(c) < 128 else "".join(f"\\{b:03o}" for b in c.encode()) for c in INFO_TEXT)

BUS_CONF = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:path={path}</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""

AUTHORITY_XML = """<node><interface name="org.freedesktop.PolicyKit1.Authority">
<method name="RegisterAuthenticationAgent"><arg type="(sa{sv})" direction="in"/><arg type="s" direction="in"/>
<arg type="s" direction="in"/></method></interface></node>"""


def authority_main(address):
    """Nahradni polkitd: udalosti na stdout, prikazy ze stdin (begin COOKIE UID.., cancel COOKIE, foreign COOKIE,
    restart)."""
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    def emit(*words):
        print(" ".join(str(w) for w in words), flush=True)

    def connect():
        return Gio.DBusConnection.new_for_address_sync(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)

    conn = connect()
    agents = {}

    def bus_call(method, args, sig):
        return conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", method,
                              GLib.Variant(sig, args), None, Gio.DBusCallFlags.NONE, 5000, None).unpack()

    def on_call(_conn, sender, path, iface, method, params, inv):
        subject, locale, opath = params.unpack()
        sid = subject[1].get("session-id")
        if sid in agents and bus_call("NameHasOwner", (agents[sid][0],), "(s)")[0]:
            emit("refused", sid)
            inv.return_dbus_error("org.freedesktop.PolicyKit1.Error.Failed",
                                  "An authentication agent already exists for the given subject")
            return
        agents[sid] = (sender, opath)
        emit("registered", sender, subject[0], sid, locale, opath)
        inv.return_value(None)

    node = Gio.DBusNodeInfo.new_for_xml(AUTHORITY_XML)
    conn.register_object(AUTH_PATH, node.interfaces[0], on_call, None, None)
    bus_call("RequestName", (NAME, 4), "(su)")

    def reply(connection, result, data):
        what, cookie = data
        try:
            connection.call_finish(result)
            emit(what, cookie, "ok")
        except GLib.Error as e:
            emit(what, cookie, "error", Gio.DBusError.get_remote_error(e) or e.message)

    def agent_call(connection, method, args, sig, what, cookie):
        sender, opath = agents[SESSION_ID]
        connection.call(sender, opath, AGENT_IFACE, method, GLib.Variant(sig, args), None, Gio.DBusCallFlags.NONE,
                        120000, None, reply, (what, cookie))

    def begin_args(cookie, uids):
        ids = [("unix-user", {"uid": GLib.Variant("u", uid)}) for uid in uids]
        return ("org.luxos.test.action", "Authentication is needed to run the test action", "",
                {"polkit.caller-pid": "1"}, cookie, ids)

    extra = []

    def on_stdin(channel, condition):
        line = channel.readline()
        if not line:
            loop.quit()
            return False
        words = line.split()
        if words[0] == "begin":
            agent_call(conn, "BeginAuthentication", begin_args(words[1], [int(u) for u in words[2:]]),
                       "(sssa{ss}sa(sa{sv}))", "reply", words[1])
        elif words[0] == "cancel":
            agent_call(conn, "CancelAuthentication", (words[1],), "(s)", "cancelled", words[1])
        elif words[0] == "foreign":
            # jine spojeni nez vlastnik jmena polkitd
            other = connect()
            extra.append(other)
            agent_call(other, "BeginAuthentication", begin_args(words[1], [os.getuid()]),
                       "(sssa{ss}sa(sa{sv}))", "reply", words[1])
        elif words[0] == "restart":
            agents.clear()
            bus_call("ReleaseName", (NAME,), "(s)")
            bus_call("RequestName", (NAME, 4), "(su)")
            emit("restarted")
        return True

    loop = GLib.MainLoop()
    GLib.io_add_watch(GLib.IOChannel.unix_new(0), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, on_stdin)
    emit("ready", conn.get_unique_name())
    loop.run()


class Lines:
    """Radky stdout procesu."""

    def __init__(self, proc):
        self.proc = proc
        self.lines = []
        self.cond = threading.Condition()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for raw in self.proc.stdout:
            with self.cond:
                self.lines.append(raw.decode(errors="replace").rstrip("\n"))
                self.cond.notify_all()
        with self.cond:
            self.cond.notify_all()

    def mark(self):
        with self.cond:
            return len(self.lines)

    def wait(self, rx, timeout=15, start=0):
        rx = re.compile(rx)
        deadline = time.monotonic() + timeout
        with self.cond:
            while True:
                for line in self.lines[start:]:
                    m = rx.search(line)
                    if m:
                        return m
                left = deadline - time.monotonic()
                if left <= 0 or (self.proc.poll() is not None and not any(rx.search(l) for l in self.lines[start:])):
                    if left > 0:
                        self.cond.wait(0.2)
                        if any(rx.search(l) for l in self.lines[start:]):
                            continue
                    raise AssertionError(f"{rx.pattern!r} se neobjevilo:\n" + "\n".join(self.lines[-30:]))
                self.cond.wait(min(left, 0.2))

    def after(self, rx, start=0):
        """Index za prvnim radkem odpovidajicim vyrazu (az se objevi)."""
        self.wait(rx, start=start)
        with self.cond:
            return next(i for i in range(start, len(self.lines)) if re.search(rx, self.lines[i])) + 1

    def text(self):
        with self.cond:
            return "\n".join(self.lines)


class FakeHelper:
    """Soket pomocnika polkitu (polkit 128): jmeno, cookie, PAM_TEXT_INFO, PAM_PROMPT_ECHO_OFF, heslo -> vysledek."""

    def __init__(self, path):
        self.path = path
        self.sessions = []          # [uzivatel, cookie, heslo nebo None, vysledek]
        self.lock = threading.Lock()
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(4)
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(conn,), daemon=True).start()

    def serve(self, conn):
        record = [None, None, None, None]
        with self.lock:
            self.sessions.append(record)
        with conn, conn.makefile("rwb") as f:
            record[0] = f.readline().decode().rstrip("\n")
            record[1] = f.readline().decode().rstrip("\n")
            f.write(b"PAM_TEXT_INFO " + INFO_ESCAPED.encode() + b"\n")
            f.write(b"PAM_PROMPT_ECHO_OFF Password: \n")
            f.flush()
            answer = f.readline()
            if not answer:
                record[3] = "eof"
                return
            record[2] = answer.decode().rstrip("\n")
            record[3] = "SUCCESS" if record[2] == SECRET else "FAILURE"
            f.write(record[3].encode() + b"\n")
            f.flush()

    def close(self):
        self.server.close()

    def done(self):
        with self.lock:
            return [list(s) for s in self.sessions]


def whoami():
    import pwd
    return pwd.getpwuid(os.getuid()).pw_name


def pss_kb(pid):
    for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
        if line.startswith("Pss:"):
            return int(line.split()[1])
    return 0


@unittest.skipUnless(LSLC and HAVE_LABWC and HAVE_DBUS and WLT.exists(), "chybi lslc, labwc (WLT_SYSROOT) nebo dbus-daemon")
class WaylandPolkitAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
        base.mkdir(parents=True, exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(prefix="luxos-polkit-wl-", dir=base))
        src = cls.tmp / "lsl"
        src.mkdir()
        for f in (PKG / "files/lsl").glob("*.lsl"):
            shutil.copy(f, src)
        cls.agent_bin = cls.tmp / "luxos-polkit"
        r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", str(src / "luxos-polkit.lsl"), str(cls.agent_bin)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("luxos-polkit: " + r.stdout + r.stderr)
        cls.pss = {}

    @classmethod
    def tearDownClass(cls):
        if cls.pss:
            print("\n  PSS luxos-polkit: " + ", ".join(f"{k} {v} kB" for k, v in sorted(cls.pss.items())))
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.procs = []
        self.session = None
        self.helper = None

    def tearDown(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
            for stream in (p.stdin, p.stdout):
                if stream:
                    stream.close()
        if self.helper:
            self.helper.close()
        if self.session:
            subprocess.run([str(WLT), "stop", str(self.session)], capture_output=True)
            shutil.rmtree(self.session, True)

    # ---- pomucky ----

    def wlt(self, *args):
        r = subprocess.run([str(WLT), *args], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            self.fail(f"wlt {args[0]}: " + r.stdout + r.stderr)
        return r.stdout

    def start(self):
        # kratka jmena: cesta soketu unix ma nejvys 107 bajtu
        name = f"pk{os.getpid() % 100000}-{sorted(n for n in dir(self) if n.startswith('test_')).index(self._testMethodName)}"
        self.session = Path(self.wlt("start", "--mode", "headless", "--size", "800x500", "--timeout", "600",
                                     "--name", name).strip())
        env = {}
        for line in self.wlt("env", str(self.session)).splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            env[key] = value
        env.pop("LD_LIBRARY_PATH", None)
        (self.session / "config/gtk-3.0").mkdir(parents=True, exist_ok=True)
        (self.session / "config/gtk-3.0/settings.ini").write_text("[Settings]\ngtk-enable-animations=false\n")
        bus_path = self.session / "bus"
        conf = self.session / "sysbus.conf"
        conf.write_text(BUS_CONF.format(path=bus_path))
        bus = subprocess.Popen(["dbus-daemon", "--nofork", "--nopidfile", f"--config-file={conf}", "--print-address=1"],
                               stdout=subprocess.PIPE, env={"PATH": "/usr/bin:/bin"})
        self.procs.append(bus)
        self.address = bus.stdout.readline().decode().strip()
        self.assertTrue(self.address.startswith("unix:"), self.address)
        auth = subprocess.Popen([sys.executable, "-I", __file__, "authority", self.address], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        self.procs.append(auth)
        self.auth = Lines(auth)
        self.auth.wait(r"^ready ")
        env.update(PATH="/usr/bin:/bin", GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GTK_A11Y="none",
                   DBUS_SYSTEM_BUS_ADDRESS=self.address, XDG_SESSION_ID=SESSION_ID, LUXOS_POLKIT_TRACE="1",
                   LANG="en_US.UTF-8")
        self.helper_socket = self.session / "h.sock"
        self.helper = FakeHelper(self.helper_socket)
        env["LUXOS_POLKIT_SOCKET"] = str(self.helper_socket)
        self.env = env
        return self.session

    def agent(self, **extra):
        env = dict(self.env, **extra)
        p = subprocess.Popen([str(self.agent_bin)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.procs.append(p)
        lines = Lines(p)
        return p, lines

    def registered_agent(self, **extra):
        mark = self.auth.mark()
        p, lines = self.agent(**extra)
        lines.wait(r"^registered " + SESSION_ID)
        m = self.auth.wait(r"^registered (\S+) unix-session " + SESSION_ID + r" en_US\.UTF-8 /cz/luxos/PolkitAgent$",
                           start=mark)
        self.assertTrue(m)
        return p, lines

    def command(self, text):
        self.procs[1].stdin.write((text + "\n").encode())
        self.procs[1].stdin.flush()

    def input(self, *cmds):
        # nova virtualni klavesnice kazdeho `wlt input`: prvni klavesu labwc spolkne (keymap a enter)
        self.wlt("input", str(self.session), "key shift", "sleep 0.2", *cmds)

    def type_password(self, lines, text, start):
        start = lines.after(r"^prompt Password$", start=start)
        time.sleep(0.4)
        self.input(f"type {text}", "key Return")
        lines.wait(r"^answered$", start=start)

    def shot(self, name):
        path = self.session / name
        self.wlt("shot", str(self.session), str(path))
        return path.read_bytes()

    # ---- pripady ----

    def test_correct_password(self):
        self.start()
        p, lines = self.registered_agent(LUXOS_POLKIT_DUMPABLE="1")
        time.sleep(1.0)
        type(self).pss["idle"] = pss_kb(p.pid)
        empty = self.shot("empty.ppm")
        mark = lines.mark()
        self.command(f"begin ck-ok {os.getuid()}")
        lines.wait(r"^dialog ", start=mark)
        self.type_password(lines, SECRET, mark)
        self.auth.wait(r"^reply ck-ok ok$")
        lines.wait(r"^closed True$", start=mark)
        sessions = self.helper.done()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0][:2], [whoami(), "ck-ok"])
        self.assertEqual(sessions[0][3], "SUCCESS")
        # texty PAM z pomocnika (g_strescape) v UTF-8
        lines.wait("^message " + INFO_TEXT + "$", start=mark)
        time.sleep(0.5)
        self.assertEqual(self.shot("after.ppm"), empty, "okno po overeni zustalo na obrazovce")
        time.sleep(1.0)
        type(self).pss["after dialog"] = pss_kb(p.pid)
        self.assertNotIn(SECRET.split()[0], lines.text())
        self.assertIsNone(p.poll())

    def test_wrong_password_then_retry(self):
        self.start()
        p, lines = self.registered_agent()
        mark = lines.mark()
        self.command(f"begin ck-retry {os.getuid()}")
        self.type_password(lines, "nope", mark)
        mark2 = lines.after(r"^result failure$", start=mark)
        lines.wait(r"^message Wrong password\.$", start=mark)
        time.sleep(0.6)
        self.shot("wrong.png")
        self.type_password(lines, SECRET, mark2)
        self.auth.wait(r"^reply ck-retry ok$")
        results = [s[3] for s in self.helper.done()]
        self.assertEqual(results, ["FAILURE", "SUCCESS"])
        self.assertEqual(self.auth.text().count("reply ck-retry"), 1)

    def test_escape_cancels(self):
        self.start()
        p, lines = self.registered_agent()
        mark = lines.mark()
        self.command(f"begin ck-esc {os.getuid()}")
        lines.wait(r"^prompt Password$", start=mark)
        time.sleep(0.4)
        self.input("type abc", "key Escape")
        self.auth.wait(r"^reply ck-esc error org\.freedesktop\.PolicyKit1\.Error\.Cancelled$")
        lines.wait(r"^closed False$", start=mark)
        # spojeni s pomocnikem zavrene bez odpovedi
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self.helper.done()[0][3] is None:
            time.sleep(0.1)
        self.assertEqual(self.helper.done()[0][3], "eof")
        self.assertIsNone(p.poll())

    def test_authority_cancel_closes_dialog(self):
        self.start()
        p, lines = self.registered_agent()
        empty = self.shot("empty.ppm")
        mark = lines.mark()
        self.command(f"begin ck-cancel {os.getuid()}")
        lines.wait(r"^prompt Password$", start=mark)
        time.sleep(0.4)
        self.assertNotEqual(self.shot("dialog.ppm"), empty, "okno se neukazalo")
        self.command("cancel ck-cancel")
        self.auth.wait(r"^reply ck-cancel error org\.freedesktop\.PolicyKit1\.Error\.Cancelled$")
        self.auth.wait(r"^cancelled ck-cancel ok$")
        time.sleep(0.5)
        self.assertEqual(self.shot("after.ppm"), empty, "okno po zruseni zustalo")
        # neznama cookie
        self.command("cancel ck-unknown")
        self.auth.wait(r"^cancelled ck-unknown error org\.freedesktop\.PolicyKit1\.Error\.Failed$")

    def test_queue_and_foreign_caller(self):
        self.start()
        p, lines = self.registered_agent()
        mark = lines.mark()
        self.command("foreign ck-foreign")
        self.auth.wait(r"^reply ck-foreign error org\.freedesktop\.PolicyKit1\.Error\.Failed$")
        # dva pozadavky: druhy ceka, zrusit ho jde i ve fronte
        self.command(f"begin ck-a {os.getuid()}")
        self.command(f"begin ck-b {os.getuid()}")
        self.command(f"begin ck-c {os.getuid()}")
        lines.wait(r"^prompt Password$", start=mark)
        self.command("cancel ck-b")
        self.auth.wait(r"^reply ck-b error org\.freedesktop\.PolicyKit1\.Error\.Cancelled$")
        self.auth.wait(r"^cancelled ck-b ok$")
        time.sleep(0.4)
        self.input(f"type {SECRET}", "key Return")
        self.auth.wait(r"^reply ck-a ok$")
        mark2 = lines.after(r"^closed True$", start=mark)
        self.type_password(lines, SECRET, mark2)
        self.auth.wait(r"^reply ck-c ok$")
        self.assertEqual([s[1] for s in self.helper.done()], ["ck-a", "ck-c"])

    def test_spawned_helper(self):
        self.start()
        log = self.session / "helper.log"
        helper = self.session / "fake-helper"
        helper.write_text("#!/bin/sh\nread -r cookie\necho \"$# $1 $cookie\" >>'" + str(log) + "'\n"
                          "echo 'PAM_PROMPT_ECHO_OFF Password: '\nread -r pw\n"
                          "if [ \"$pw\" = '" + SECRET + "' ]; then echo SUCCESS; else echo FAILURE; fi\n")
        helper.chmod(0o755)
        p, lines = self.registered_agent(LUXOS_POLKIT_SOCKET="", LUXOS_POLKIT_HELPER=str(helper))
        mark = lines.mark()
        self.command(f"begin ck-spawn {os.getuid()}")
        lines.wait(r"^helper spawn ", start=mark)
        self.type_password(lines, "bad", mark)
        mark2 = lines.after(r"^message Wrong password\.$", start=mark)
        self.type_password(lines, SECRET, mark2)
        self.auth.wait(r"^reply ck-spawn ok$")
        self.assertEqual(log.read_text().splitlines(), [f"1 {whoami()} ck-spawn"] * 2)
        self.assertEqual(self.helper.done(), [])

    def test_other_admin_and_unusable_helper(self):
        # prihlaseny uzivatel neni mezi identitami: prvni spravce (root); pomocnik neodpovida -> chyba, ne smycka
        self.start()
        helper = self.session / "broken-helper"
        helper.write_text("#!/bin/sh\necho 'PAM_ERROR_MSG polkit-agent-helper-1 needs to be setuid root'\necho FAILURE\n")
        helper.chmod(0o755)
        p, lines = self.registered_agent(LUXOS_POLKIT_SOCKET="", LUXOS_POLKIT_HELPER=str(helper))
        mark = lines.mark()
        self.command("begin ck-root 0")
        lines.wait(r"^dialog root$", start=mark)
        lines.wait(r"^message polkit-agent-helper-1 needs to be setuid root$", start=mark)
        lines.wait(r"^message Authentication is not available\.$", start=mark)
        time.sleep(1.0)
        self.assertEqual(lines.text().count("helper spawn"), 1)
        self.input("key Escape")
        self.auth.wait(r"^reply ck-root error org\.freedesktop\.PolicyKit1\.Error\.Cancelled$")

    def test_second_instance_exits_2(self):
        self.start()
        p, lines = self.registered_agent()
        # bez LUXOS_POLKIT_DUMPABLE proces nejde cist (heslo v pameti)
        with self.assertRaises(PermissionError):
            pss_kb(p.pid)
        q, _ = self.agent()
        self.assertEqual(q.wait(15), 2)
        self.auth.wait(r"^refused " + SESSION_ID)
        self.assertIsNone(p.poll())

    def test_authority_restart_reregisters(self):
        self.start()
        p, lines = self.registered_agent()
        mark = self.auth.mark()
        self.command("restart")
        self.auth.wait(r"^registered \S+ unix-session " + SESSION_ID, start=mark)
        m2 = lines.mark()
        self.command(f"begin ck-again {os.getuid()}")
        self.type_password(lines, SECRET, m2)
        self.auth.wait(r"^reply ck-again ok$")
        self.assertIsNone(p.poll())

    def test_no_system_bus_exits_2(self):
        self.start()
        p, _ = self.agent(DBUS_SYSTEM_BUS_ADDRESS="unix:path=/nonexistent")
        self.assertEqual(p.wait(15), 2)
        # bez XDG_SESSION_ID a bez logindu na sbernici neni relace pro registraci
        q, _ = self.agent(XDG_SESSION_ID="")
        self.assertEqual(q.wait(40), 2)
        self.assertIn(b"no logind session", q.stderr.read())


if __name__ == "__main__":
    if sys.argv[1:2] == ["authority"]:
        authority_main(sys.argv[2])
    else:
        unittest.main()
