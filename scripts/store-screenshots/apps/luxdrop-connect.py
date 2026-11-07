"""Pripojit k pocitaci (LuxDrop): pocitace v okoli se sdilenymi slozkami a overovaci kod pri pripojeni.

Ukazkove pocitace (_c_luxdrop.py nahrazuje objevovani), zadne skutecne spojeni ani pripojeni sshfs.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def shots(s):
    now = time.time()
    s.write(".config/luxdrop/settings.json", json.dumps({"name": "Anna's Laptop"}), 0o600)
    s.write(".local/share/luxdrop/trusted.json", json.dumps({
        "3f9a1c0d22e7b851" + "0" * 48: {"name": "Martin's Desktop", "id": "3f9a1c0d22e7b851", "kind": "luxdrop",
                                         "added": now, "last_seen": now}}), 0o600)
    ctl = os.path.join(s.tmp, "luxdrop-ctl")
    open(ctl, "w").close()
    env = {"LUXDROP_LIB": s.src("luxdrop/files/lib"), "LUXDROP_NO_MDNS": "1", "LUXDROP_NO_SYSTEMD": "1",
           "LUXDROP_DEMO_CTL": ctl}
    s.python_env()
    s.launch([sys.executable, os.path.join(HERE, "_c_luxdrop.py"), "connect"], env=env)
    win = s.window(name="Connect to Computer", size=(500, 560))
    s.sleep(0.5)
    s.activate(win)
    s.capture("1", win)
    with open(ctl, "a") as f:
        f.write("code\n")
    s.sleep(1.0)
    s.activate(win)
    s.capture("2", win)
