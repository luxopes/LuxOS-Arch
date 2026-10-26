#!/usr/bin/env python3
"""LuxOS - greeter v domene (luxos-domain): Jiny uzivatel s doménovym jmenem, offline stav, hlasky SSSD.

    env -u DISPLAY xvfb-run -a dbus-run-session -- python3 packages/luxos-greeter/tests/gui-domain.py [--shots DIR]

Rezim --demo bez LightDM; stav domeny z LUXOS_GREETER_DOMAIN_INFO (JSON jako luxos_domain.greeter_info()).
Overuje: dlazdici Jiny uzivatel, zastupny text "Jmeno (jan nebo jan@firma.local)", radek "Prihlaseni
do domeny", rucni jmeno + heslo, offline radek se zbyvajicimi dny, chybu offline odlisenou od
spatneho hesla, zamek uctu domenou (ne pam_faillock), vyprsele heslo a vyzvy ke zmene hesla.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader
# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM) - nikdy skutecna obrazovka
if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    sys.exit("Run under xvfb-run (or LUXOS_TEST_X=1 in a VM) - never on a real display.")

ap = argparse.ArgumentParser()
ap.add_argument("--shots", help="directory for screenshots (default: temp dir)")
opts = ap.parse_args()
SHOTS = opts.shots or tempfile.mkdtemp(prefix="luxos-greeter-domain-shots-")
os.makedirs(SHOTS, exist_ok=True)

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="luxos-greeter-domain-")
os.environ.update({"LANG": "en_US.UTF-8", "LUXOS_GREETER_CONF": "/nonexistent", "XDG_CACHE_HOME": TMP})
os.environ.pop("LUXOS_GREETER_DEMO_FPRINT", None)
INFO = os.path.join(TMP, "domain.json")
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


def set_info(info):
    if info is None:
        os.environ.pop("LUXOS_GREETER_DOMAIN_INFO", None)
        return
    with open(INFO, "w", encoding="utf-8") as f:
        json.dump(info, f)
    os.environ["LUXOS_GREETER_DOMAIN_INFO"] = INFO


def greeter(info, users=1):
    set_info(info)
    win = g.Greeter(argparse.Namespace(demo=True, users=users, sessions=1, lock=False, domain=None))
    win.launched = []
    win.backend.start_session = lambda key: win.launched.append((win.backend.auth_user(), key))
    pump(0.1)
    win.set_active(True)
    pump(0.15)
    return win


def other(win):
    for b in win.user_buttons:
        if b.user.name is None:
            return b
    return None


def shot(win, name):
    pump(0.3)
    w = win.get_window()
    pb = Gdk.pixbuf_get_from_window(w, 0, 0, w.get_width(), w.get_height()) if w else None
    if pb:
        pb.savev(os.path.join(SHOTS, name + ".png"), "png", [], [])
    return pb is not None


def done(win):
    win.destroy()
    pump(0.05)


ONLINE = {"domain": "firma.local", "short": "FIRMA", "online": True, "offline_left_days": None,
          "example": "jan@firma.local"}
OFFLINE = dict(ONLINE, online=False, offline_left_days=12)

# 0. bez domeny: zadna dlazdice Jiny uzivatel, zadny radek domeny
w = greeter(None)
check("no domain: no Other tile in demo", other(w) is None)
check("no domain: domain line hidden", not w.domain_label.get_visible())
done(w)

# 0b. ciste funkce
check("domain_info: missing file -> None", (set_info(None), os.environ.update(LUXOS_GREETER_DOMAIN_INFO=TMP + "/x"),
                                            g.domain_info())[2] is None)
set_info({"domain": "firma.local"})
d = g.domain_info()
check("domain_info: defaults filled", d and d["short"] == "FIRMA" and d["example"] == "jan@firma.local"
      and d["online"] is None, d)
check("domain_message: cached credentials", g.domain_message("Authenticated with cached credentials.") == "offline")
check("domain_message: expired", g.domain_message("Password expired. Change your password now.") == "expired")
check("domain_message: domain lock", g.domain_message("Account is locked by the domain administrator.") == "domain-locked")
check("domain_message: faillock is not domain", g.domain_message("The account is locked due to 20 failed logins.") is None)
check("domain_message: offline chauthtok is not offline login",
      g.domain_message("System is offline, password change not possible") is None)

# 1. online: Jiny uzivatel, zastupny text a radek domeny
w = greeter(ONLINE, users=2)
b = other(w)
check("online: Other tile present", b is not None)
w.on_user_clicked(None, b.user)
pump(0.2)
check("online: name placeholder", w.placeholder == "Name (jan or jan@firma.local)", w.placeholder)
check("online: entry visible text for the name", w.entry.get_visibility())
check("online: domain line", w.domain_label.get_visible() and w.domain_label.get_text() == "Sign in to domain FIRMA",
      w.domain_label.get_text())
check("online: domain line not an error", not w.domain_label.get_style_context().has_class("offline"))
check("screenshot online", shot(w, "domain-online"))
# rucni jmeno, pak heslo
w.entry.set_text("jan@firma.local")
w.submit()
pump(0.2)
check("online: then password prompt", w.placeholder == "Enter Password" and not w.entry.get_visibility(), w.placeholder)
w.entry.set_text("luxos")
w.submit()
pump(0.7)
check("online: domain user logs in", w.launched == [("jan@firma.local", "xfce")], w.launched)
done(w)

# 1b. mistni uzivatel v domene: radek domeny se neukazuje
w = greeter(ONLINE, users=1)
check("online: local user has no domain line", w.user.name == "anna" and not w.domain_label.get_visible(),
      f"{w.user.name} {w.domain_label.get_visible()} {w.domain_label.get_text()}")
done(w)

# 2. offline: radek se zbyvajicimi dny, spatne heslo = jina hlaska nez online
w = greeter(OFFLINE, users=1)
w.on_user_clicked(None, other(w).user)
pump(0.2)
txt = w.domain_label.get_text()
check("offline: offline line with days", "Offline" in txt and "12" in txt and w.domain_label.get_visible(), txt)
check("offline: highlighted", w.domain_label.get_style_context().has_class("offline"))
check("screenshot offline", shot(w, "domain-offline"))
w.entry.set_text("jan")
w.submit()
pump(0.2)
w.entry.set_text("wrong")
w.submit()
pump(0.7)
h = w.hint.get_text()
check("offline: wrong password explains first sign-in needs the network",
      "organization network" in h and w.error_shown, h)
check("offline: not logged in", not w.launched)
check("screenshot offline error", shot(w, "domain-offline-error"))
done(w)

# 2b. offline, spravne ulozene heslo -> info o prihlaseni z cache a prihlaseni
w = greeter(OFFLINE, users=1)
w.on_user_clicked(None, other(w).user)
pump(0.2)
w.entry.set_text("jan")
w.submit()
pump(0.2)
w.entry.set_text("luxos")
w.submit()
pump(0.7)
check("offline: cached password logs in", w.launched == [("jan", "xfce")], w.launched)
check("offline: note about saved password", "saved password" in w.domain_label.get_text(), w.domain_label.get_text())
done(w)

# 3. zamek uctu domenou (ne pam_faillock) a vypnuty ucet
w = greeter(ONLINE, users=1)
w.on_user_clicked(None, other(w).user)
pump(0.2)
w.on_message("Account is locked by the domain administrator.", True)
check("domain lock: clear message", "locked by the domain administrator" in w.hint.get_text(), w.hint.get_text())
check("domain lock: not the faillock text", "Too many failed" not in w.hint.get_text())
w.backend.state = "wait"
w.backend.ok = False
w.on_complete()
pump(0.1)
check("domain lock: kept after failure", "domain administrator" in w.hint.get_text(), w.hint.get_text())
w.on_message("The account is locked due to 20 failed logins. (1 minutes left to unlock)", True)
check("faillock still recognised in a domain", "locked for 1 min" in w.hint.get_text(), w.hint.get_text())
done(w)

# 4. vyprsele heslo: hlaska a vyzvy ke zmene hesla
w = greeter(ONLINE, users=1)
w.on_user_clicked(None, other(w).user)
pump(0.2)
w.on_message("Password expired. Change your password now.", True)
check("expired: hint", "expired" in w.hint.get_text() and not w.error_shown, w.hint.get_text())
w.on_prompt("Current Password: ", True)
check("expired: current password prompt", w.placeholder == "Current Password", w.placeholder)
w.on_prompt("New Password: ", True)
check("expired: new password prompt", w.placeholder == "New Password", w.placeholder)
w.on_prompt("Reenter new Password: ", True)
check("expired: repeat prompt", w.placeholder == "Repeat New Password", w.placeholder)
w.on_prompt("login: ", False)
check("login prompt uses domain placeholder", w.placeholder == "Name (jan or jan@firma.local)", w.placeholder)
done(w)

print(f"\nscreenshots: {SHOTS}")
print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall ok")
sys.exit(1 if FAILS else 0)
