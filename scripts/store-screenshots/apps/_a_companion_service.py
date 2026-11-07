"""Ukazkova sluzba LuxOS Companion pro snimky okna Telefon (spousti postup luxos-companion.py).

Skutecna trida service.Service ze zdroju na soukrome sbernici relace snimkovaci sezeni (dbus-run-session),
bez BlueZ: telefon "Pixel 8" je pripojeny pres socketpair (jako v testech) a posila polohu.
Kdyz vznikne soubor argv[1], pripoji se druhy, zatim neschvaleny telefon (dotaz Povolit / Odmitnout).
Nic se nepripojuje ke skutecnemu Bluetooth ani k telefonu.
"""
import json
import os
import socket
import sys
import time

from gi.repository import Gio, GLib

from luxos_companion import BUS_NAME, service, store

TRIGGER = sys.argv[1]
PHONE = {"address": "4C:2A:91:7E:05:B3", "name": "Pixel 8"}
TABLET = {"address": "8E:13:5F:C2:9A:41", "name": "Galaxy Tab S9"}


class QuietNotifier:
    def notify(self, *_a, **_k):
        return None

    def close(self, _nid):
        pass


class Phone:
    def __init__(self, svc, peer):
        a, b = socket.socketpair()
        self.sock = b
        self.sock.setblocking(False)
        svc.new_connection(a.detach(), peer)
        GLib.io_add_watch(self.sock.fileno(), GLib.IO_IN, self.drain)

    def drain(self, *_a):
        try:
            while self.sock.recv(65536):
                pass
        except BlockingIOError:
            pass
        except OSError:
            return False
        return True

    def send(self, mtype, **fields):
        msg = {"v": 1, "type": mtype, "id": "%s-%d" % (mtype, time.monotonic_ns())}
        msg.update(fields)
        self.sock.sendall(json.dumps(msg).encode() + b"\n")


def main():
    settings = store.Settings()
    settings.approve(PHONE["address"], PHONE["name"])
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    svc = service.Service(bus, settings=settings, notifier=QuietNotifier())
    svc.export()
    Gio.bus_own_name_on_connection(bus, BUS_NAME, 0, None, None)
    svc.bt.update(registered=True, available=True)
    phone = Phone(svc, PHONE)
    phone.send("hello", protocol=1)

    def location():
        phone.send("location.status", enabled=True)
        phone.send("location.update", latitude=50.0875, longitude=14.4213, accuracy_m=8.0,
                   timestamp_ms=int(time.time() * 1000), age_ms=500)
        svc.status_changed()
        return True
    GLib.timeout_add(1500, lambda: location() and False)
    GLib.timeout_add_seconds(5, location)

    state = {"tablet": None}

    def watch():
        if state["tablet"] is None and os.path.exists(TRIGGER):
            state["tablet"] = Phone(svc, TABLET)
            state["tablet"].send("hello", protocol=1)
        return True
    GLib.timeout_add(200, watch)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
