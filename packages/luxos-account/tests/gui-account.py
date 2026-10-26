#!/usr/bin/env python3
"""LuxOS - okno Ucet LuxAI: prihlaseni kodem, zalozeni uctu a sprava uctu primo v aplikaci (lokalni napodoba serveru).

    xvfb-run -a python3 packages/luxos-account/tests/gui-account.py [--shots DIR]
"""
import json
import os
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader
# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM) - nikdy skutecna obrazovka
if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    sys.exit("Run under xvfb-run (or LUXOS_TEST_X=1 in a VM) - never on a real display.")

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


def manage(lang):
    """Sprava uctu: prehled se spotrebou, uzivatelske jmeno, heslo, predvolby, export, zadost o zruseni."""
    sfx = "-" + lang
    SRV.accounts.clear()
    SRV.sessions.clear()
    SRV.chats.clear()
    SRV.native_settings = SRV.native_history = True
    SRV.accounts["jan@example.cz"] = {"password": PW, "displayName": "Jan Novák", "username": "jan",
                                      "usage": {"fastTokens": 31250, "fastLimit": 50000,
                                                "liteTokens": 120000, "liteLimit": 1000000}}
    SRV.accounts["eva@example.cz"] = {"password": PW, "displayName": "Eva", "username": "eva"}
    SRV.chats["jan@example.cz"] = [{"id": "c1", "title": "Ahoj", "updatedAt": "2026-10-01", "messages": []}]
    acc.forget()
    acc.login_password("jan@example.cz", PW)
    n_me = sum(1 for x in SRV.log if x[1] == "/api/me")
    win = app.AccountWindow(False)
    win.show_all()
    check("sprava: /api/me nacteno", wait(lambda: sum(1 for x in SRV.log if x[1] == "/api/me") > n_me))
    pump(0.4)
    names = [win.pages.child_get_property(c, "name") for c in win.pages.get_children()]
    check("sprava: stranky", names == ["overview", "profile", "security", "preferences", "privacy"], names)
    check("sprava: titulek okna s krizkem", win.get_titlebar().get_show_close_button())
    labels = [w.get_text() for w in walk(win.usage_body) if isinstance(w, Gtk.Label)]
    check("prehled: spotreba Flash 63 %", "63 %" in labels, labels)
    check("prehled: datum vynulovani", any(t == _("The limits reset on %s (in %d days).")
                                           % (time.strftime("%x", acc.usage_reset({})),
                                              acc.days_until(acc.usage_reset({}))) for t in labels), labels)
    shot(win, "manage-overview" + sfx)

    # uzivatelske jmeno
    win.pages.set_visible_child_name("profile")
    check("profil: jmeno z /api/me", win.username.get_text() == "jan")
    check("profil: Ulozit neaktivni bez zmeny", not win.username_btn.get_sensitive())
    win.username.set_text("Ja")
    check("profil: neplatne jmeno", not win.username_btn.get_sensitive() and win.username_status.get_visible())
    win.username.set_text("eva")
    win.save_username()
    check("profil: obsazene jmeno", wait(lambda: win.username_status.get_text()
                                         == _("This username is already used by another account.")),
          win.username_status.get_text())
    win.username.set_text("jan.novak")
    win.save_username()
    check("profil: jmeno ulozeno", wait(lambda: SRV.accounts["jan@example.cz"]["username"] == "jan.novak"
                                        and win.username_status.get_text() == _("The username is saved.")))
    check("profil: hlavicka @jan.novak", all("@jan.novak" in e.get_text() for _n, e in win.ident))
    check("profil: account.json", acc.load()["user"]["username"] == "jan.novak")
    shot(win, "manage-profile" + sfx)

    # heslo
    win.pages.set_visible_child_name("security")
    win.pw_current.set_text("wrong password!")
    win.pw_new.set_text("brand new password")
    win.pw_again.set_text("brand new passwor")
    check("heslo: neshodna hesla", not win.pw_btn.get_sensitive())
    win.pw_again.set_text("brand new password")
    check("heslo: tlacitko aktivni", win.pw_btn.get_sensitive())
    win.save_password()
    check("heslo: spatne soucasne", wait(lambda: win.pw_status.get_text()
                                         == _("The current password is not correct.")))
    win.pw_current.set_text(PW)
    win.save_password()
    check("heslo: zmeneno", wait(lambda: SRV.accounts["jan@example.cz"]["password"] == "brand new password"
                                 and "good" in win.pw_status.get_style_context().list_classes()))
    check("heslo: pole vymazana", win.pw_new.get_text() == "" and win.pw_current.get_text() == "")
    shot(win, "manage-security" + sfx)

    # predvolby
    win.pages.set_visible_child_name("preferences")
    win.style.set_active_id("technical")
    check("styl: popis", win.style_desc.get_text() == _(app.AccountWindow.STYLES["technical"][1]))
    win.save_style()
    check("styl: ulozen", wait(lambda: SRV.accounts["jan@example.cz"]["settings"]["aiResponseStyle"] == "technical"))
    win.theme.set_active(True)
    check("vzhled: svetly", wait(lambda: SRV.accounts["jan@example.cz"]["settings"]["theme"] == "light"
                                 and win.theme.get_sensitive()))
    SRV.native_settings = False
    win.theme.set_active(False)
    check("vzhled: 403 -> Otevrit na webu", wait(lambda: win.theme_status.web.get_visible()),
          win.theme_status.get_text())
    check("vzhled: prepinac vracen", win.theme.get_active())
    shot(win, "manage-preferences" + sfx)
    win.theme_status.web.clicked()
    check("vzhled: web /settings", OPENED[-1:] == [SRV.origin + "/settings"], OPENED)
    SRV.native_settings = True

    # export a zruseni
    win.pages.set_visible_child_name("privacy")
    path = os.path.join(os.environ["XDG_CONFIG_HOME"], "export-%s.json" % lang)
    win.export_to(path)
    check("export: hotovo", wait(lambda: os.path.exists(path) and win.export_btn.get_sensitive()),
          win.export_status.get_text())
    check("export: bez tokenu", acc.load()["sessionToken"] not in open(path).read())
    check("export: hlaska", path in win.export_status.get_text(), win.export_status.get_text())
    shot(win, "manage-privacy" + sfx)
    dlg = win.confirm_delete()
    pump(0.3)
    check("zruseni: tlacitko zamcene", not dlg.delete_go.get_sensitive())
    dlg.delete_entry.set_text("jan@example.cz")
    check("zruseni: chybi zaskrtnuti", not dlg.delete_go.get_sensitive())
    dlg.delete_sure.set_active(True)
    check("zruseni: odemceno", dlg.delete_go.get_sensitive())
    shot(dlg, "manage-delete" + sfx)
    dlg.response(Gtk.ResponseType.ACCEPT)
    pump(0.2)
    check("zruseni: rozepsany e-mail podpore", OPENED[-1:] and OPENED[-1].startswith("mailto:info@lux-ai.cz?"),
          OPENED)
    check("zruseni: ucet zustava (nic se neodeslalo)", "jan@example.cz" in SRV.accounts)

    # vyprsela session
    SRV.sessions.clear()
    win.pages.set_visible_child_name("preferences")
    win.style.set_active_id("friendly")
    win.save_style()
    check("vyprsela session -> prihlaseni", wait(lambda: hasattr(win, "panel") and win.panel.get_parent() is not None))
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
        manage(lang)
    SRV.stop()
    print("\n%d chyb" % len(FAILS) if FAILS else "\nvse OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
