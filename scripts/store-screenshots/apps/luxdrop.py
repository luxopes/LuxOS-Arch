"""LuxDrop: Odeslat (zarizeni v okoli, vyber, probihajici prenos), Prijem s historii a dialog prichozich souboru.

Zadna sit: prijem jen na 127.0.0.1 s nahodnymi porty, bez mDNS a multicastu, zarizeni v okoli jsou ukazkova
(_c_luxdrop.py nahrazuje objevovani). Nic se neodesila.
"""
import json
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def free_port():
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


def prepare(s):
    """Ukazkove nastaveni, historie a duveryhodna zarizeni v docasnem HOME -> (env, ridici soubor)."""
    now = time.time()
    s.write(".config/luxdrop/settings.json", json.dumps({
        "name": "Anna's Laptop", "receive_mode": "everyone", "everyone_until": 0, "port": free_port(),
        "localsend": True, "localsend_port": free_port(), "auto_accept_trusted": True}), 0o600)
    dl = os.path.join(s.home, "Downloads", "LuxDrop")
    hist = []
    for peer, files, size, kind, dev, ago in (
            ("Martin's Desktop", ["Holiday itinerary.pdf"], 1_350_000, "luxdrop", "desktop", 900),
            ("Anna's Pixel", ["IMG_1842.jpg", "IMG_1843.jpg", "IMG_1847.jpg"], 11_800_000, "localsend", "mobile",
             5400)):
        hist.append({"direction": "in", "peer": peer, "items": files, "total": size, "state": "done",
                     "saved": [os.path.join(dl, f) for f in files], "protocol": kind, "device_type": dev,
                     "time": now - ago})
    s.write(".local/share/luxdrop/history.json", json.dumps(hist), 0o600)
    s.write(".local/share/luxdrop/trusted.json", json.dumps({
        "3f9a1c0d22e7b851" + "0" * 48: {"name": "Martin's Desktop", "id": "3f9a1c0d22e7b851", "kind": "luxdrop",
                                         "added": now, "last_seen": now},
        "a81c55e0d3b94f27" + "1" * 48: {"name": "Anna's Pixel", "id": "a81c55e0d3b94f27", "kind": "localsend",
                                         "device_type": "mobile", "added": now, "last_seen": now}}), 0o600)
    s.write("Documents/Quarterly report.pdf", "%PDF-1.4\n" + "x" * 240_000)
    for n in range(12):
        s.write("Pictures/Summer 2026/IMG_%04d.jpg" % (3100 + n), "x" * 350_000)
    ctl = os.path.join(s.tmp, "luxdrop-ctl")
    open(ctl, "w").close()
    return {"LUXDROP_LIB": s.src("luxdrop/files/lib"), "LUXDROP_NO_MDNS": "1", "LUXDROP_NO_MULTICAST": "1",
            "LUXDROP_NO_SYSTEMD": "1", "LUXDROP_NON_UNIQUE": "1", "LUXDROP_BIND": "127.0.0.1",
            "LUXDROP_DEMO_CTL": ctl}, ctl


def command(s, ctl, cmd, wait=1.0):
    with open(ctl, "a") as f:
        f.write(cmd + "\n")
    s.sleep(wait)


def shots(s):
    env, ctl = prepare(s)
    s.python_env()
    s.launch([sys.executable, os.path.join(HERE, "_c_luxdrop.py"), "main"], env=env)
    win = s.window(name="^LuxDrop$", size=(480, 760))
    command(s, ctl, "send", 1.5)
    s.capture("1", win)
    command(s, ctl, "receive")
    s.capture("2", win)
    command(s, ctl, "incoming", 1.0)
    dlg = s.window(name="Incoming files", size=None)
    s.capture("3", dlg)
