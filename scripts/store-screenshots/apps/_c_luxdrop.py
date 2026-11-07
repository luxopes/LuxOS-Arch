#!/usr/bin/env python3
"""LuxDrop pro snimky Obchodu: okno ze zdroju s ukazkovymi zarizenimi v okoli (zadna sit).

Spousti postup luxdrop.py / luxdrop-connect.py (s.launch). Prijem posloucha jen na 127.0.0.1 na nahodnych
portech, mDNS i multicast LocalSend jsou vypnute a objevovani je nahrazene ukazkovym seznamem - nic se
neoznamuje ani neposila do skutecne site. Ovladani: soubor $LUXDROP_DEMO_CTL (radek = prikaz).

    _c_luxdrop.py main      hlavni okno (prikazy: send, receive, incoming)
    _c_luxdrop.py connect   okno Pripojit k pocitaci (prikazy: code)
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.environ["LUXDROP_LIB"])

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from luxdrop import engine, lsdiscovery, remote, transfer  # noqa: E402

DEMO_DEVICES = [
    {"key": "lux:3f9a1c0d22e7b851", "kind": "luxdrop", "name": "Martin's Desktop", "host": "192.168.1.31",
     "port": 53318, "id": "3f9a1c0d22e7b851", "device_type": "desktop", "device_model": "LuxOS",
     "trusted": True, "secure": True},
    {"key": "lux:b2d47e6a91c03f58", "kind": "luxdrop", "name": "Office Laptop", "host": "192.168.1.44",
     "port": 53318, "id": "b2d47e6a91c03f58", "device_type": "desktop", "device_model": "LuxOS",
     "trusted": False, "secure": True},
    {"key": "ls:pixel", "kind": "localsend", "name": "Anna's Pixel", "host": "192.168.1.52", "port": 53317,
     "id": "a81c55e0d3b94f27", "device_type": "mobile", "device_model": "Android", "trusted": True,
     "secure": True, "protocol": "https", "fingerprint": "A81C55E0D3B94F27"},
    {"key": "ls:ipad", "kind": "localsend", "name": "Living Room iPad", "host": "192.168.1.60", "port": 53317,
     "id": "c0e9f1a2b3d4e5f6", "device_type": "mobile", "device_model": "iPad", "trusted": False,
     "secure": True, "protocol": "https", "fingerprint": "C0E9F1A2B3D4E5F6"},
]


# --- zadna sit: objevovani a oznamovani nahrazene ----------------------------
engine.Engine.devices = lambda self: [dict(d) for d in DEMO_DEVICES]
engine.Engine.refresh = lambda self: None
engine.Engine.scan = lambda self, done=None, targets=None, port=None: False
lsdiscovery.LocalSendDiscovery.announce = lambda self: None
lsdiscovery.LocalSendDiscovery._send = lambda self, announce: None


def demo_transfer(win):
    t = transfer.Transfer("out", "Anna's Pixel", "a81c55e0d3b94f27")
    t.protocol, t.device_type = "localsend", "mobile"
    t.items = ["Trip to the mountains"]
    t.files = [{"name": "Trip to the mountains/IMG_%04d.jpg" % (2041 + i), "size": 4_200_000,
                "done": 4_200_000 if i < 5 else (1_900_000 if i == 5 else 0),
                "state": "done" if i < 5 else ("transferring" if i == 5 else "waiting")} for i in range(9)]
    t.total = sum(f["size"] for f in t.files)
    t.done = sum(f["done"] for f in t.files)
    t.state = "transferring"
    t.files = []   # bez rozbalovaciho seznamu souboru (radek se vejde do okna)
    win.add_transfer_row(t)


class FakeReq:
    message = None
    device_type = "desktop"
    protocol = "luxdrop"
    device_model = "LuxOS"
    peer_name = "Martin's Desktop"
    peer_id = "3f9a1c0d22e7b851"
    items = ["Project plan.odt", "Budget 2027.ods", "Office photos"]
    total = 48_600_000
    name_clash = False
    verified = True
    sas = "482915"
    can_trust = True

    def __init__(self):
        self.withdrawn = threading.Event()


def control(handlers):
    path = os.environ["LUXDROP_DEMO_CTL"]
    state = {"pos": 0}

    def poll():
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        for cmd in lines[state["pos"]:]:
            if cmd in handlers:
                handlers[cmd]()
        state["pos"] = len(lines)
        return True
    GLib.timeout_add(200, poll)


def run_main():
    from luxdrop import dialogs, gui
    gui.local_ips = lambda: ["192.168.1.24"]
    app = gui.App()

    def ready():
        win = app.win
        if win is None:
            return True
        home = os.path.expanduser("~")
        win.add_paths([os.path.join(home, "Documents", "Quarterly report.pdf"),
                       os.path.join(home, "Pictures", "Summer 2026")])
        demo_transfer(win)
        control({
            "send": lambda: win.show_page("send"),
            "receive": lambda: win.show_page("receive"),
            "incoming": lambda: dialogs.accept_dialog(FakeReq(), lambda v: None, parent=win),
        })
        return False
    GLib.timeout_add(300, ready)
    GLib.set_prgname("luxdrop")
    GLib.set_application_name("LuxDrop")
    return app.run(["luxdrop"])


class FakeDisc:
    def devices(self, my_id):
        return [{"name": "Martin's Desktop", "id": "3f9a1c0d22e7b851", "host": "192.168.1.31", "port": 53319},
                {"name": "Office Laptop", "id": "b2d47e6a91c03f58", "host": "192.168.1.44", "port": 53319},
                {"name": "Kitchen PC", "id": "7e21d9c4a0b6f312", "host": "192.168.1.27", "port": 53319}]

    def stop(self):
        pass


def run_connect():
    from luxdrop import remote_ui
    remote_ui.ConnectWindow.start_discovery = lambda self: setattr(self, "disc", FakeDisc())
    remote.connections = lambda: [{"name": "Martin's Desktop", "peer": "Martin's Desktop", "write": False,
                                   "path": "/nonexistent/luxdrop-demo"}]
    remote_ui.ConnectWindow.tick = lambda self: True

    def code():
        win = [w for w in Gtk.Window.list_toplevels() if isinstance(w, remote_ui.ConnectWindow)][0]
        win.code_box.foreach(win.code_box.remove)
        win.status.set_text("Connecting to Office Laptop…")
        win.stack.set_visible_child_name("progress")
        win.on_status("waiting", {"peer_name": "Office Laptop", "trusted": False, "sas": "731604"})
        win.ask_code({"peer_name": "Office Laptop"}, threading.Event(), lambda v: None)
    GLib.idle_add(lambda: (control({"code": code}), False)[1])
    return remote_ui.main(False)


if __name__ == "__main__":
    time.sleep(0)
    sys.exit(run_main() if sys.argv[1:] == ["main"] else run_connect())
