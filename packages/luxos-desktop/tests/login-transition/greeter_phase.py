#!/usr/bin/env python3
"""Run the real luxos-greeter (demo backend) on the test X server, log in, exit like LightDM stops it.
usage: greeter_phase.py GREETER_PATH WALLPAPER FRAME_DIR"""
import argparse
import os
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader

GREETER, WALL, FRAMES = sys.argv[1:4]
TMP = tempfile.mkdtemp(prefix="greeter-phase-")
CONF = os.path.join(TMP, "luxos-greeter.conf")
with open(CONF, "w") as f:
    f.write("[greeter]\n")
# snimek drzeny serverem pres konec greeteru jako pri skutecnem prihlaseni (HOLD=0 bez nej)
os.environ.update({"LUXOS_GREETER_DEMO_HOLD": os.environ.get("HOLD", "1"), "LUXOS_GREETER_CONF": CONF,
                   "XDG_CACHE_HOME": TMP, "LUXOS_GREETER_DEMO_BACKGROUND": WALL,
                   "LUXOS_GREETER_DEMO_FRAME_DIR": FRAMES})
sys.dont_write_bytecode = True
g = SourceFileLoader("luxos_greeter", GREETER).load_module()
from gi.repository import Gtk  # noqa: E402


def pump(sec=0.0):
    end = time.monotonic() + sec
    while True:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if time.monotonic() >= end:
            break
        time.sleep(0.005)


def wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pump()
        if cond():
            return True
    return cond()


g.DEMO_FPRINT = None
win = g.Greeter(argparse.Namespace(demo=True, users=1, sessions=1, lock=False))
started = []
win.backend.start_session = lambda key: started.append(time.monotonic())
win.present()
pump(0.8)
win.set_active(True)
wait(lambda: win.awaiting)
pump(0.6)
win.entry.set_text("luxos")
win.submit()
wait(lambda: started, 5)
print("greeter: session start requested", flush=True)
# LightDM stops the greeter right away
os._exit(0)
