"""Spolecne pomucky testu LuxOS Companion: cesty ke zdrojum, docasne XDG slozky, falesne hodiny,
sluzba se socketpair misto RFCOMM a pumpovani hlavni smycky GLib."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.normpath(os.path.join(HERE, "..", "files"))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, FILES)
sys.path.insert(1, os.path.join(ROOT, "luxos-desktop", "files", "python"))
sys.path.insert(2, os.path.join(ROOT, "luxos-i18n", "files"))

TMP = tempfile.mkdtemp(prefix="luxos-companion-test-")
os.environ.update({
    "XDG_CONFIG_HOME": os.path.join(TMP, "config"),
    "XDG_DATA_HOME": os.path.join(TMP, "data"),
    "XDG_STATE_HOME": os.path.join(TMP, "state"),
    "XDG_CACHE_HOME": os.path.join(TMP, "cache"),
    "LUXOS_I18N_DIR": os.path.join(ROOT, "luxos-i18n", "files"),
    "LANG": "en_GB.UTF-8",
    "LUXOS_COMPANION_LUXAI": os.path.join(HERE, "fake-luxai"),
    "LUXOS_COMPANION_QUIET": "1",
    "GIO_USE_VFS": "local",           # zadne gvfs (aktivace sluzeb skutecne relace)
})
os.environ.pop("LC_ALL", None)
os.environ.pop("LC_MESSAGES", None)
os.environ.pop("LUXOS_CALENDAR_DIR", None)

from gi.repository import GLib  # noqa: E402

PHONE = {"address": "AA:BB:CC:DD:EE:01", "name": "Pixel Test"}


class Clock:
    """Falesne monotonni hodiny."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class FakeNotifier:
    def __init__(self):
        self.sent = []
        self.closed = []
        self.waiting = {}
        self.next = 1

    def notify(self, summary, body, actions=(), urgent=False, timeout=-1, replaces=0, callback=None):
        nid = self.next
        self.next += 1
        self.sent.append({"id": nid, "summary": summary, "body": body, "actions": list(actions)})
        if callback:
            self.waiting[nid] = callback
        return nid

    def close(self, nid):
        self.waiting.pop(nid, None)
        self.closed.append(nid)

    def press(self, nid, key):
        self.waiting.pop(nid)(key)


def pump(cond=lambda: False, timeout=2.0):
    ctx = GLib.MainContext.default()
    end = time.time() + timeout
    while time.time() < end:
        while ctx.pending():
            ctx.iteration(False)
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def fresh_dir(name):
    d = os.path.join(TMP, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return d


class Phone:
    """Konec socketpair na strane telefonu."""

    def __init__(self, sock):
        self.sock = sock
        self.sock.setblocking(False)
        self.buf = b""
        self.closed = False

    def __del__(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def send_raw(self, data):
        self.sock.sendall(data)

    def send(self, mtype, mid=None, **fields):
        msg = {"v": 1, "type": mtype, "id": mid or f"{mtype}-{time.monotonic_ns()}"}
        msg.update(fields)
        self.send_raw(json.dumps(msg, ensure_ascii=False).encode("utf-8") + b"\n")
        return msg["id"]

    def _read(self):
        try:
            data = self.sock.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if data:
            self.buf += data
        else:
            self.closed = True

    def messages(self):
        self._read()
        out = []
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            out.append(json.loads(line))
        return out

    def wait(self, n=1, timeout=3.0):
        got = []
        pump(lambda: (got.extend(self.messages()) or len(got) >= n or self.closed), timeout)
        got.extend(self.messages())
        return got

    def wait_closed(self, timeout=3.0):
        return pump(lambda: (self.messages() is not None and self.closed), timeout)


def make_service(clock=None, calendar_dir=None, approve=True, luxai_factory=None):
    from luxos_companion import calendar_note, service, store
    cfg = fresh_dir("config-" + str(time.monotonic_ns()))
    settings = store.Settings(os.path.join(cfg, "companion.json"))
    if approve:
        settings.approve(PHONE["address"], PHONE["name"])
    cal = calendar_note.CalendarWriter(calendar_dir or fresh_dir("cal-" + str(time.monotonic_ns())),
                                       done_path=os.path.join(cfg, "done.json"))
    svc = service.Service(None, settings=settings, calendar=cal, clock=clock or Clock(),
                          notifier=FakeNotifier(), luxai_factory=luxai_factory)
    return svc


def connect(svc, peer=None):
    """Nove spojeni pres socketpair -> (Session, Phone)."""
    a, b = socket.socketpair()
    s = svc.new_connection(a.detach(), peer or PHONE)
    return s, Phone(b)


BUS_CONFIG = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:path=%s</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""


def private_bus():
    """Vlastni dbus-daemon bez aktivace sluzeb (zadne sluzby skutecne relace) -> (proces, adresa)."""
    d = fresh_dir("bus-" + str(time.monotonic_ns()))
    conf = os.path.join(d, "bus.conf")
    with open(conf, "w") as f:
        f.write(BUS_CONFIG % os.path.join(d, "bus"))
    proc = subprocess.Popen(["dbus-daemon", "--config-file=" + conf, "--nofork", "--nopidfile", "--print-address=1"],
                            stdout=subprocess.PIPE, text=True)
    return proc, proc.stdout.readline().strip()
