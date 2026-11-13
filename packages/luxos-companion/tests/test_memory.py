"""Regrese nacitani nepouzivanych funkci v novem procesu (bez modulu z jinych testu)."""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers


class TestIdleImports(unittest.TestCase):
    def test_bluetooth_handshake_and_status_do_not_load_calendar(self):
        code = r'''
import sys
sys.path.insert(0, sys.argv[1])
from luxos_companion import service
from gi.repository import GLib
import socket, json, time
svc = service.Service(None)
svc.settings.set("allow_luxai", False)
address = "AA:BB:CC:DD:EE:01"
svc.settings.approve(address, "Phone")
a, b = socket.socketpair()
b.setblocking(False)
s = svc.new_connection(a.detach(), {"address": address, "name": "Phone"})
b.sendall(b'{"v":1,"type":"hello","id":"h","protocol":1}\n')
ctx = GLib.MainContext.default()
response = b""
end = time.monotonic() + 3
while b"\n" not in response and time.monotonic() < end:
    while ctx.pending():
        ctx.iteration(False)
    try:
        response += b.recv(65536)
    except BlockingIOError:
        time.sleep(0.005)
assert json.loads(response)["type"] == "hello.ok", response
assert svc.status()["connections"]
s.close("test")
assert not svc.status()["connections"]
assert "luxos_companion.calendar_note" not in sys.modules
assert "luxos_calendar_ics" not in sys.modules
b.close()
'''
        result = subprocess.run([sys.executable, "-B", "-c", code, helpers.FILES],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
