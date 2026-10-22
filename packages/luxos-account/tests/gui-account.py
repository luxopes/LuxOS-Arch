#!/usr/bin/env python3
"""LuxOS - okno Ucet LuxAI: prihlaseni kodem a zalozeni uctu primo v aplikaci (lokalni napodoba serveru).

    xvfb-run -a python3 packages/luxos-account/tests/gui-account.py [--shots DIR]
"""
import json
import os
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else ""
sys.path.insert(0, HERE)
from mock_luxai import MockLuxAI  # noqa: E402

SRV = MockLuxAI().start()
os.environ.update({"LUXAI_ORIGIN": SRV.origin, "LUXOS_I18N_DIR": I18N, "LANG": "en_US.UTF-8",
                   "XDG_CONFIG_HOME": tempfile.mkdtemp(prefix="luxai-app-")})
sys.argv = sys.argv[:1]
sys.path.insert(0, I18N)
sys.path.insert(0, FILES)
import luxai_account as acc  # noqa: E402
import luxai_account_gtk as accgtk  # noqa: E402
import luxos_i18n  # noqa: E402
app = SourceFileLoader("luxos_account_app", os.path.join(FILES, "luxos-account")).load_module()
from gi.repository import Gdk, Gtk  # noqa: E402

_ = luxos_i18n._
FAILS = []
OPENED = []
PW = "correct horse battery"


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
        time.sleep(0.02)
    return cond()


def set_lang(code):
    luxos_i18n._TR.clear()
    if code != "en":
        with open(os.path.join(I18N, code + ".tsv"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or "\t" not in line:
                    continue
                k, v = line.rstrip("\n").split("\t", 1)
                if v:
                    luxos_i18n._TR[k] = v


def shot(win, name):
    if not SHOTS:
        return
    pump(0.4)
    gw = win.get_window()
    pb = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
    if pb:
        pb.savev(os.path.join(SHOTS, name + ".png"), "png", [], [])


def type_code(entry, code):
    entry.set_text("")
    for ch in code:
        entry.set_text(entry.get_text() + ch)
        pump()


def new_window():
    acc.forget()
    win = app.AccountWindow(False)
    win.show_all()
    pump(0.3)
    return win


def run(lang):
    sfx = "-" + lang
    set_lang(lang)
    SRV.accounts.clear()
    SRV.pending.clear()
    SRV.last_sent.clear()
    SRV.allow_native = True
    SRV.accounts["jan@example.cz"] = {"password": PW, "displayName": "Jan"}

    # ---- kod z e-mailu ----
    win = new_window()
    p = win.panel
    check("okno: panel prihlaseni", isinstance(p, accgtk.SignInPanel))
    shot(win, "account-login" + sfx)
    p.switch("code")
    p.code_email.set_text("jan@example.cz")
    p.send_login_code()
    check("kod: krok zadani kodu", wait(lambda: p.stack.get_visible_child_name() == "code-verify"))
    check("kod: odpocet Poslat znovu", not p.code_login.resend.get_sensitive())
    shot(win, "account-code" + sfx)
    type_code(p.code_login.entry, "123456")
    check("kod: ulozeny ucet", wait(lambda: acc.load() is not None))
    a = acc.load() or {}
    check("kod: account.json 0600 a e-mail", a.get("user", {}).get("email") == "jan@example.cz"
          and os.stat(acc.ACCOUNT_FILE).st_mode & 0o777 == 0o600)
    check("kod: okno ukazuje profil", wait(lambda: not hasattr(win, "panel") or win.panel.get_parent() is None))
    # profil si dotahne /api/me (a ucet znovu ulozi) - pockat, at nezasahuje do dalsi casti
    wait(lambda: any(path == "/api/me" for _m, path, _b, _c in SRV.log))
    pump(0.5)
    shot(win, "account-profile" + sfx)
    win.destroy()

    # ---- novy ucet ----
    win = new_window()
    p = win.panel
    # odkaz "Vytvorit ucet" dole prepne na registraci (uz neotevira web)
    link = [b for b in walk(win) if isinstance(b, Gtk.Button) and b.get_label() == _("Create an account")
            and b.get_style_context().has_class("link")]
    check("odkaz Vytvorit ucet existuje", bool(link))
    link and link[0].clicked()
    pump(0.2)
    check("odkaz prepne na registraci", p.stack.get_visible_child_name() == "register-form" and not OPENED,
          (p.stack.get_visible_child_name(), OPENED))
    p.reg_name.set_text("Petr Novy")
    p.reg_email.set_text("petr@example.cz")
    p.reg_pass.set_text("dlouhe heslo 2026")
    p.reg_terms.set_active(True)
    shot(win, "account-register" + sfx)
    SRV.allow_native = False
    p.start_register()
    check("403 origin: hlaska s odkazem", wait(lambda: not p.busy and p.action.get_visible())
          and "/register" in p.status.get_text(), p.status.get_text())
    p.action.clicked()
    check("403 origin: otevre web", OPENED[-1:] == [SRV.origin + "/register"], OPENED)
    shot(win, "account-register-origin" + sfx)
    SRV.allow_native = True
    p.start_register()
    check("registrace: krok kodu", wait(lambda: p.stack.get_visible_child_name() == "register-verify"),
          (p.stack.get_visible_child_name(), p.status.get_text()))
    type_code(p.code_reg.entry, "654321")
    check("spatny kod: hlaska", wait(lambda: not p.busy and p.status.get_visible())
          and p.status.get_text() == _("The code is not valid or has expired."))
    type_code(p.code_reg.entry, "123456")
    check("registrace: ucet ulozen", wait(lambda: (acc.load() or {}).get("user", {}).get("email") == "petr@example.cz"))
    check("registrace: jmeno na serveru", SRV.accounts.get("petr@example.cz", {}).get("displayName") == "Petr Novy",
          SRV.accounts)
    saved = json.load(open(acc.ACCOUNT_FILE))
    check("heslo neni v account.json", "dlouhe heslo" not in json.dumps(saved))
    win.destroy()
    OPENED.clear()


def walk(w):
    yield w
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            yield from walk(c)


def main():
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
    accgtk.open_url = lambda _w, url: OPENED.append(url)
    provider = Gtk.CssProvider()
    provider.load_from_data(app.CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    for lang in ("en", "cs"):
        print("---", lang)
        run(lang)
    SRV.stop()
    print("\n%d chyb" % len(FAILS) if FAILS else "\nvse OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
