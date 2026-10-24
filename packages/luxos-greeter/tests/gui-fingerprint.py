#!/usr/bin/env python3
"""LuxOS - greeter a otisk prstu (rezim --demo s napodobenym pam_fprintd), bez LightDM.

    xvfb-run -a python3 packages/luxos-greeter/tests/gui-fingerprint.py

Overuje: napovedu pri cekani na otisk, prihlaseni otiskem, neshodu a navrat k heslu,
okamzite heslo behem cekani na otisk (nova autentizace bez otisku), spatne heslo
a beh bez ctecky; zapis souboru pro pam_listfile.
"""
import argparse
import os
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader
# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM) - nikdy skutecna obrazovka
if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    sys.exit("Run under xvfb-run (or LUXOS_TEST_X=1 in a VM) - never on a real display.")

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.update({"LANG": "en_US.UTF-8", "LUXOS_GREETER_CONF": "/nonexistent",
                   "XDG_CACHE_HOME": tempfile.mkdtemp(prefix="luxos-greeter-test-")})
g = SourceFileLoader("luxos_greeter", os.path.join(HERE, "..", "files", "luxos-greeter")).load_module()
from gi.repository import Gtk  # noqa: E402

FAILS = []
TOUCH = "Touch the fingerprint sensor or enter your password"
NOMATCH = "Fingerprint not recognized. Try again or enter your password."


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


def greeter(mode):
    g.DEMO_FPRINT = mode
    win = g.Greeter(argparse.Namespace(demo=True, users=1, sessions=1, lock=False))
    win.launched = []
    win.backend.start_session = lambda key: win.launched.append((win.backend.auth_user(), key))
    pump(0.1)
    win.set_active(True)
    pump(0.15)
    return win


def hint(win):
    return win.hint.get_text()


def done(win):
    win.destroy()
    pump(0.05)


# 1. otisk sedi -> prihlaseni bez hesla
w = greeter("match")
check("fingerprint: hint shown while waiting", hint(w) == TOUCH, hint(w))
check("fingerprint: entry stays editable", w.entry.get_sensitive() and w.entry.get_editable())
check("fingerprint: not logged in yet", not w.launched)
pump(1.0)
check("fingerprint match logs in", w.launched == [("anna", "xfce")], w.launched)
done(w)

# 2. otisk nesedi -> chyba, po vyprseni vyzva k heslu; heslo funguje
w = greeter("nomatch")
pump(0.5)
check("no match: error hint", hint(w) == NOMATCH and w.error_shown, hint(w))
pump(1.0)
check("no match: falls back to password prompt", w.awaiting and not w.fp_wait and w.placeholder == "Enter Password",
      f"{w.awaiting} {w.fp_wait} {w.placeholder}")
w.entry.set_text("luxos")
w.submit()
pump(0.7)
check("no match: password logs in", w.launched == [("anna", "xfce")], w.launched)
done(w)

# 3. uzivatel pise heslo, zatimco se ceka na otisk -> hned heslo (bez timeoutu)
w = greeter("wait")
check("waiting: fp_wait set", w.fp_wait)
w.entry.set_text("luxos")
w.submit()
check("waiting: restarted without fingerprint", w.password_only and not w.fp_wait)
check("waiting: entry cleared", w.entry.get_text() == "")
pump(0.7)
check("waiting: typed password logs in without waiting", w.launched == [("anna", "xfce")], w.launched)
done(w)

# 4. spatne heslo behem cekani -> chyba; dalsi pokus znovu nabidne otisk, chyba zustane videt
w = greeter("wait")
w.entry.set_text("wrong")
w.submit()
pump(0.7)
check("wrong password: not logged in", not w.launched)
check("wrong password: error kept", w.error_shown and "Incorrect password" in hint(w), hint(w))
check("wrong password: fingerprint offered again", w.fp_wait and not w.password_only)
w.entry.set_text("luxos")
w.submit()
pump(0.7)
check("wrong password: then correct one logs in", w.launched == [("anna", "xfce")], w.launched)
done(w)

# 4b. ucet docasne zamceny (pam_faillock) behem cekani na otisk -> jasna hlaska, ne "otisk/heslo spatne"
w = greeter("wait")
w.on_message("The account is locked due to 10 failed logins.", True)
w.on_message("(1 minutes left to unlock)", True)
check("locked: clear message with minutes", "locked for 1 min" in hint(w), hint(w))
w.backend.state = "wait"
w.backend.ok = False
w.on_complete()
pump(0.1)
check("locked: failure keeps the lock message", "locked" in hint(w) and "Incorrect" not in hint(w), hint(w))
done(w)

# 5. Enter v prazdnem poli behem cekani -> prepnuti na heslo
w = greeter("wait")
w.submit()
pump(0.2)
check("empty Enter: switches to password prompt", w.awaiting and w.password_only and not w.launched)
done(w)

# 6. bez ctecky / bez pam_fprintd -> puvodni chovani
w = greeter("")
check("no reader: no fingerprint hint", hint(w) != TOUCH and not w.fp_wait and w.awaiting, hint(w))
w.entry.set_text("luxos")
w.submit()
pump(0.7)
check("no reader: password logs in", w.launched == [("anna", "xfce")], w.launched)
done(w)

# 7. navrat na hodiny zrusi cekani na otisk
w = greeter("match")
w.set_active(False)
pump(1.1)
check("idle: cancelled fingerprint does not log in", not w.launched)
done(w)

# 8. soubor pro pam_listfile (mimo demo)
w = greeter("wait")
w.demo = False
tmp = tempfile.mkdtemp(prefix="luxos-fp-skip-")
g.FPRINT_SKIP = os.path.join(tmp, "password-only")
check("skip file: write user", w.fprint_skip("anna") and open(g.FPRINT_SKIP).read() == "anna\n")
check("skip file: clear", w.fprint_skip(None) and open(g.FPRINT_SKIP).read() == "")
g.FPRINT_SKIP = os.path.join(tmp, "missing", "password-only")
check("skip file: unwritable -> False", w.fprint_skip("anna") is False)
w.fprint = False
check("skip file: disabled -> False, nothing written", w.fprint_skip("anna") is False)
w.demo = True
done(w)

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall ok")
sys.exit(1 if FAILS else 0)
