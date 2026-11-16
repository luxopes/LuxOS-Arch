#!/usr/bin/env python3
"""LuxOS - greeter: Caps Lock, rozlozeni klavesnice a hlaska po spatnem hesle (rezim --demo), bez LightDM.

    xvfb-run -a python3 packages/luxos-greeter/tests/gui-caps-lock.py [--shots DIR]

Caps Lock a rozlozeni jako skutecne klavesy (XTest) na displeji testu; mapa us,cz se nahraje
pres xkbcomp (setxkbmap v Xvfb nemusi nic zmenit). Overuje: Caps Lock zapnuty uz pri startu ->
radek "Caps Lock is on" pod polem; spatne heslo s Caps Lockem -> "Incorrect password – Caps Lock is on"
a radek zustava i pri dalsim psani (driv po chybe zmizel); vypnuti se projevi hned; spatne heslo
bez Caps Locku -> "Incorrect password. Try again."; rozlozeni pod polem jen pri vic rozlozenich,
kliknuti ho prepne; spravne heslo prihlasi.
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
import argparse
import ctypes
import os
import subprocess
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader
# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM / v docasnem Xvfb) - nikdy skutecna obrazovka
if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    sys.exit("Run under xvfb-run (or LUXOS_TEST_X=1 in a VM) - never on a real display.")
if os.environ.get("DISPLAY") in (None, "", ":0", ":0.0"):
    sys.exit("refusing to run on display :0")

ap = argparse.ArgumentParser()
ap.add_argument("--shots")
args = ap.parse_args()

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="luxos-greeter-caps-", dir=os.environ.get("LUXOS_TEST_TMP"))
KBD_CONF = os.path.join(TMP, "00-keyboard.conf")
os.environ.update({"LANG": "en_US.UTF-8", "LUXOS_GREETER_CONF": "/nonexistent", "XDG_CACHE_HOME": TMP,
                   "LUXOS_GREETER_KEYBOARD_CONF": KBD_CONF})


def kbd_conf(layouts):
    with open(KBD_CONF, "w", encoding="utf-8") as f:
        f.write('Section "InputClass"\n    Identifier "system-keyboard"\n    MatchIsKeyboard "on"\n'
                f'    Option "XkbLayout" "{layouts}"\n    Option "XkbOptions" "grp:shifts_toggle"\nEndSection\n')


kbd_conf("us,cz")
g = SourceFileLoader("luxos_greeter", os.path.join(HERE, "..", "files", "luxos-greeter")).load_module()
from gi.repository import Gdk, Gtk  # noqa: E402

FAILS = []
CAPS_FAIL = "Incorrect password – Caps Lock is on"
PLAIN_FAIL = "Incorrect password. Try again."


def check(desc, cond, extra=""):
    print(("ok    " if cond else "FAIL  ") + desc + (f"\n      {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(desc)


class X:
    """Klavesnice testovaciho displeje (XTest, XKB)."""

    def __init__(self):
        x = self.x = ctypes.CDLL("libX11.so.6")
        self.xt = ctypes.CDLL("libXtst.so.6")
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XStringToKeysym.restype = ctypes.c_ulong
        x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x.XkbGetState.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
        x.XkbLockGroup.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        self.xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.d = x.XOpenDisplay(None)
        i = [ctypes.c_int() for _ in range(5)]
        i[3].value, i[4].value = 1, 0
        x.XkbQueryExtension(ctypes.c_void_p(self.d), *[ctypes.byref(v) for v in i])
        keymap = subprocess.run(["setxkbmap", "-layout", "us,cz", "-option", "grp:shifts_toggle", "-print"],
                                capture_output=True, text=True, check=False).stdout
        subprocess.run(["xkbcomp", "-w", "0", "-", os.environ["DISPLAY"]], input=keymap, text=True,
                       capture_output=True, check=False)
        x.XkbLockGroup(self.d, 0x100, 0)
        x.XSync(self.d, 0)

    def state(self):
        st = (ctypes.c_ubyte * 32)()
        self.x.XkbGetState(self.d, 0x100, st)
        return st[0], st[9]

    def caps(self):
        return bool(self.state()[1] & 2)

    def key(self, *names):
        codes = [self.x.XKeysymToKeycode(self.d, self.x.XStringToKeysym(n.encode())) for n in names]
        for c in codes:
            self.xt.XTestFakeKeyEvent(self.d, c, 1, 0)
        for c in reversed(codes):
            self.xt.XTestFakeKeyEvent(self.d, c, 0, 0)
        self.x.XSync(self.d, 0)

    def set_caps(self, on):
        if self.caps() != on:
            self.key("Caps_Lock")


def pump(sec=0.0):
    end = time.monotonic() + sec
    while True:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if time.monotonic() >= end:
            break
        time.sleep(0.01)


def wait(pred, sec=1.0):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        pump(0.02)
        if pred():
            return True
    return pred()


def greeter():
    win = g.Greeter(argparse.Namespace(demo=True, users=1, sessions=1, lock=False, domain=None))
    win.launched = []
    win.backend.start_session = lambda key: win.launched.append((win.backend.auth_user(), key))
    pump(0.2)
    win.set_active(True)
    pump(0.6)
    return win


def attempt(w, text):
    w.entry.set_text(text)
    w.submit()
    pump(0.8)


def shot(name):
    if not args.shots:
        return
    pump(0.5)
    root = Gdk.get_default_root_window()
    pb = Gdk.pixbuf_get_from_window(root, 0, 0, root.get_width(), root.get_height())
    os.makedirs(args.shots, exist_ok=True)
    pb.savev(os.path.join(args.shots, name), "png", [], [])


x = X()

# 1. Caps Lock zapnuty uz pri startu (jako po otevreni vika)
x.set_caps(True)
w = greeter()
check("Caps Lock on at start -> warning under the field", w.caps_box.get_visible() and w.caps_on)
check("warning text", w.caps_label.get_text() == "Caps Lock is on", w.caps_label.get_text())
check("two layouts -> layout under the field", w.layout_chip.get_visible() and
      w.layout_chip.get_child().get_text() == "US", w.layout_chip.get_child().get_text())
check("hint row stays free for messages", w.hint.get_text() == "", w.hint.get_text())
shot("greeter-caps-on.png")

# 2. spatne heslo s Caps Lockem
attempt(w, "LUXOS")
check("failed attempt with Caps Lock -> says so", w.hint.get_text() == CAPS_FAIL, w.hint.get_text())
check("Caps Lock warning still shown after the failure", w.caps_box.get_visible())
shot("greeter-wrong-caps.png")
w.entry.set_text("l")
pump(0.1)
check("typing again: error cleared, Caps Lock warning stays", w.hint.get_text() == "" and w.caps_box.get_visible())

# 3. vypnuti Caps Locku hned
x.key("Caps_Lock")
check("Caps Lock off -> warning hidden at once", wait(lambda: not w.caps_box.get_visible(), 0.5))
x.key("Caps_Lock")
check("Caps Lock on -> warning at once", wait(lambda: w.caps_box.get_visible(), 0.5))
x.key("Caps_Lock")
wait(lambda: not w.caps_box.get_visible(), 0.5)

# 4. spatne heslo bez Caps Locku
attempt(w, "nope")
check("failed attempt without Caps Lock", w.hint.get_text() == PLAIN_FAIL, w.hint.get_text())

# 5. rozlozeni: kliknuti pod polem prepne
w.layout_chip.clicked()
check("click on the layout switches it", wait(lambda: w.layout_chip.get_child().get_text() == "CZ", 0.6)
      and x.state()[0] == 1, w.layout_chip.get_child().get_text())
check("top-right indicator follows", w.kbd_btn.get_child().get_text() == "CZ")
w.layout_chip.clicked()
wait(lambda: w.layout_chip.get_child().get_text() == "US", 0.6)

# 6. spravne heslo
attempt(w, "luxos")
pump(0.5)
check("correct password logs in", w.launched == [("anna", "xfce")], w.launched)
w.destroy()
pump(0.1)

# 7. jedno rozlozeni: pod polem nic, Caps Lock vypnuty
kbd_conf("us")
w = greeter()
check("one layout, Caps Lock off: nothing under the field",
      not w.layout_chip.get_visible() and not w.caps_box.get_visible())
w.destroy()
pump(0.1)

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
