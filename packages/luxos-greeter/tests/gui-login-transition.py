#!/usr/bin/env python3
"""LuxOS - prechod po prihlaseni na strane greeteru (rezim --demo), bez LightDM.

    env -u DISPLAY xvfb-run -a python3 packages/luxos-greeter/tests/gui-login-transition.py [--shots DIR]

Overuje: po spravnem hesle zmizi formular, hodiny i stavova lista a posledni snimek je jen tapeta
(ten pak drzi luxos-session-cover --login, dokud se neposklada plocha); relace se spusti nejvys
o jeden snimek pozdeji (< 150 ms). Spatne heslo nic neskryje. Snimek se ulozi i do souboru
(login-frame.raw + mala rozmazana login-frame-small.raw) pro server, ktery ho po skonceni greeteru neudrzi.
"""
import argparse
import os
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader
if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    sys.exit("Run under xvfb-run (or LUXOS_TEST_X=1 in a VM) - never on a real display.")

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="luxos-greeter-leave-")
CONF = os.path.join(TMP, "luxos-greeter.conf")
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else ""
WALL = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-branding", "files", "wallpapers", "luxos-flow-light.jpg"))
with open(CONF, "w") as f:
    f.write("[greeter]\n")
FRAMES = os.path.join(TMP, "lightdm-data")
os.makedirs(FRAMES)
os.environ.update({"LANG": "en_US.UTF-8", "LUXOS_GREETER_CONF": CONF, "XDG_CACHE_HOME": TMP,
                   "LUXOS_GREETER_DEMO_BACKGROUND": WALL, "LUXOS_GREETER_DEMO_FRAME_DIR": FRAMES})
sys.dont_write_bytecode = True
g = SourceFileLoader("luxos_greeter", os.path.join(HERE, "..", "files", "luxos-greeter")).load_module()
from gi.repository import Gdk, Gtk  # noqa: E402

FAILS = []


def check(desc, cond, extra=""):
    print(("ok    " if cond else "FAIL  ") + desc + (f"\n      {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(desc)


def pump(sec=0.0):
    end = time.monotonic() + sec
    while True:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if time.monotonic() >= end:
            break
        time.sleep(0.01)


def wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pump()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def shot(win, name):
    if not SHOTS:
        return None
    gw = win.get_window()
    pb = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
    os.makedirs(SHOTS, exist_ok=True)
    pb.savev(os.path.join(SHOTS, name + ".png"), "png", [], [])
    return pb


g.DEMO_FPRINT = None
win = g.Greeter(argparse.Namespace(demo=True, users=1, sessions=1, lock=False))
win.launched = []
win.backend.start_session = lambda key: win.launched.append((win.backend.auth_user(), key, time.monotonic()))
pump(0.5)
win.set_active(True)
check("prompt", wait(lambda: win.awaiting))
pump(0.5)
win.entry.set_text("wrong")
win.submit()
check("wrong password: form stays", wait(lambda: win.error_shown, 4) and win.login.get_visible() and not win.leaving)
check("prompt again", wait(lambda: win.awaiting, 4))
check("wrong password wrote no frame", os.listdir(FRAMES) == [])
pump(0.5)
shot(win, "greeter-login")
win.entry.set_text("luxos")
t0 = time.monotonic()
win.submit()
check("session started", wait(lambda: win.launched, 4))
if win.launched:
    # od overeni (demo backend odpovida asynchronne) do spusteni relace: jen jeden snimek
    check("session start not delayed", win.launched[0][2] - t0 < 1.0, win.launched[0][2] - t0)
check("leaving: wallpaper only", win.leaving and not win.login.get_visible() and not win.power.get_visible()
      and not win.status.get_visible())
pump(0.1)
shot(win, "greeter-leaving")


def read_frame(name):
    with open(os.path.join(FRAMES, name), "rb") as f:
        head = f.readline().split()
        return int(head[1]), int(head[2]), f.read(), head[0]


w, h, data, magic = read_frame("login-frame.raw")
check("frame file: whole screen", (magic, w, h, len(data)) == (b"LUXFRAME1", win.W, win.H, win.W * win.H * 4),
      (magic, w, h, len(data)))
check("frame file readable by the session user", os.stat(os.path.join(FRAMES, "login-frame.raw")).st_mode & 0o044 == 0o044)
gw = win.get_window()
pb = Gdk.pixbuf_get_from_window(gw, win.W // 2, win.H // 2, 1, 1)
px = pb.get_pixels()
o = (win.H // 2 * win.W + win.W // 2) * 4
check("frame file = last frame on screen", all(abs(px[c] - data[o + 2 - c]) <= 2 for c in range(3)),
      (list(px[:3]), list(data[o:o + 3])))
sw, sh, sdata, _m = read_frame("login-frame-small.raw")
check("small blurred wallpaper", sh == 64 and len(sdata) == sw * sh * 4 and any(sdata), (sw, sh))
check("no temp files left", sorted(os.listdir(FRAMES)) == ["login-frame-small.raw", "login-frame.raw"],
      os.listdir(FRAMES))

# relace nejde spustit: formular je zpet s hlaskou
win2 = g.Greeter(argparse.Namespace(demo=True, users=1, sessions=1, lock=False))


def fail_start(key):
    raise g.GLib.Error("no session")


win2.backend.start_session = fail_start
os.environ["LUXOS_GREETER_DEMO_FRAME_DIR"] = os.path.join(TMP, "missing")   # bez slozky: prihlaseni jde dal
pump(0.3)
win2.set_active(True)
wait(lambda: win2.awaiting)
win2.entry.set_text("luxos")
win2.submit()
check("failed start: form back", wait(lambda: not win2.leaving and win2.login.get_visible()
                                             and win2.hint.get_text() == "Could not start the session.", 4),
      (win2.leaving, win2.login.get_visible(), win2.error_shown, win2.hint.get_text()))
print("FAIL: %d" % len(FAILS) if FAILS else "all ok")
sys.exit(1 if FAILS else 0)
