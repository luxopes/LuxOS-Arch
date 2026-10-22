#!/usr/bin/env python3
"""LuxOS installer - krok LuxAI (heslo, kod z e-mailu, novy ucet) proti lokalni napodobe serveru.

    xvfb-run -a python3 packages/luxos-installer/tests/gui-luxai.py [--shots DIR]

Zadne skutecne ucty ani e-maily: server je packages/luxos-account/tests/mock_luxai.py na 127.0.0.1.
S --shots ulozi snimky jednotlivych podstranek v cestine a anglictine.
"""
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
ACC_FILES = os.path.join(HERE, "..", "..", "luxos-account", "files")
ACC_TESTS = os.path.join(HERE, "..", "..", "luxos-account", "tests")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else ""

sys.path.insert(0, ACC_TESTS)
from mock_luxai import MockLuxAI  # noqa: E402

SRV = MockLuxAI().start()
os.environ.update({"LUXOS_INSTALL_FAKE": "1", "LUXAI_ORIGIN": SRV.origin, "LUXOS_I18N_DIR": I18N,
                   "XDG_CONFIG_HOME": tempfile.mkdtemp(prefix="luxai-gui-"), "LANG": "en_US.UTF-8"})
for d in (FILES, I18N, ACC_FILES):
    sys.path.insert(0, d)
# knihovny ze zdrojaku maji prednost pred pripadne nainstalovanymi v /usr/lib/luxos/python
import luxai_account as acc  # noqa: E402,F401
import luxai_account_gtk as accgtk  # noqa: E402
gui = SourceFileLoader("luxos_install_gui", os.path.join(FILES, "luxos-install-gui")).load_module()
from gi.repository import Gdk, GdkPixbuf, Gtk  # noqa: E402,F401

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
    pump()
    return cond()


def texts(widget):
    """Vsechny texty popisku/tlacitek ve viditelne casti stromu widgetu."""
    out = []

    def walk(w):
        if not w.get_visible():
            return
        if isinstance(w, Gtk.Stack):
            c = w.get_visible_child()
            if c:
                walk(c)
            return
        if isinstance(w, (Gtk.Label,)):
            out.append(w.get_text())
        if isinstance(w, Gtk.Button) and w.get_label():
            out.append(w.get_label())
        if isinstance(w, Gtk.Container):
            for c in w.get_children():
                walk(c)
    walk(widget)
    return "\n".join(out)


def shot(win, name):
    if not SHOTS:
        return
    pump(0.4)
    gw = win.get_window()
    w, h = gw.get_width(), gw.get_height()
    pb = Gdk.pixbuf_get_from_window(gw, 0, 0, w, h)
    if pb:
        pb.savev(os.path.join(SHOTS, name + ".png"), "png", [], [])


def type_code(entry, code):
    entry.set_text("")
    for ch in code:
        entry.set_text(entry.get_text() + ch)
        pump()


def reset_server():
    SRV.accounts.clear()
    SRV.pending.clear()
    SRV.last_sent.clear()
    SRV.sent_codes.clear()
    SRV.allow_native = True
    SRV.accounts["jan@example.cz"] = {"password": PW, "displayName": "Jan"}


def open_luxai(win):
    win.idx = win.steps.index("luxai")
    win.render()
    pump(0.2)
    return win.luxai_panel


def flows(win, lang):
    """Projde vsechny podstranky; vraci nic, chyby zapisuje do FAILS."""
    sfx = "-" + lang
    reset_server()
    win.s.update({"luxai": None, "luxai_email": ""})
    win.luxai_panel = None
    win.online = True
    p = open_luxai(win)
    check("panel prihlaseni na strance LuxAI", isinstance(p, accgtk.SignInPanel))
    check("tlacitko dole = Preskocit", win.btn_next.get_label() == gui._("Skip") and win.btn_next.get_sensitive())
    check("jmeno z kroku Ucet predvyplneno", p.reg_name.get_text() == "Jana Test", p.reg_name.get_text())
    shot(win, "luxai-password" + sfx)

    # ---- heslo ----
    p.pw_email.set_text("jan@example.cz")
    p.pw_pass.set_text("wrong password")
    p.password_login()
    check("spatne heslo: hlaska", wait(lambda: p.status.get_visible() and not p.busy)
          and p.status.get_text() == gui._("Wrong e-mail or password."), p.status.get_text())
    shot(win, "luxai-password-error" + sfx)
    p.pw_pass.set_text(PW)
    p.password_login()
    check("heslo: prihlaseno", wait(lambda: win.s["luxai"] is not None))
    acct = win.s["luxai"] or {}
    check("ucet ma token a e-mail", acct.get("sessionToken") and acct["user"]["email"] == "jan@example.cz")
    check("ucet se neulozil do home zive relace", acc.load() is None)
    pump(0.2)
    check("stranka: Prihlasen jako", "jan@example.cz" in texts(win.scroll), texts(win.scroll))
    check("tlacitko dole = Pokracovat", win.btn_next.get_label() == gui._("Continue"))
    cfg = win.build_config()
    check("LUXAI_ACCOUNT v konfiguraci backendu", "LUXAI_ACCOUNT=" in cfg and acct["sessionToken"] in cfg)
    shot(win, "luxai-signed-in" + sfx)
    # odhlasit -> novy panel
    win.s["luxai"] = None
    win.render()
    pump(0.2)
    p = win.luxai_panel

    # ---- kod z e-mailu ----
    p.switch("code")
    pump(0.2)
    check("rezim kod: pole e-mailu", p.stack.get_visible_child_name() == "code-email")
    p.code_email.set_text("nonsense")
    p.send_login_code()
    check("neplatny e-mail: hlaska bez pozadavku", p.status.get_text() == gui._("Enter a valid e-mail address."))
    p.code_email.set_text("Jan@Example.cz")
    shot(win, "luxai-code-email" + sfx)
    p.send_login_code()
    check("kod odeslan -> zadani kodu", wait(lambda: p.stack.get_visible_child_name() == "code-verify"))
    check("server dostal pozadavek na kod", SRV.sent_codes == [("jan@example.cz", "123456")], SRV.sent_codes)
    check("text: kod jsme poslali na e-mail", gui._("We sent a code to %s.") % "jan@example.cz"
          == p.code_login.sent.get_text(), p.code_login.sent.get_text())
    check("Poslat znovu: odpocet, neaktivni", not p.code_login.resend.get_sensitive()
          and ("60" in p.code_login.resend.get_label() or "59" in p.code_login.resend.get_label()),
          p.code_login.resend.get_label())
    pump(1.2)
    check("odpocet bezi", any(n in p.code_login.resend.get_label() for n in ("58", "59")),
          p.code_login.resend.get_label())
    # prekresleni stranky (napr. Zpet/Dalsi) nesmi stav ztratit
    win.render()
    pump(0.2)
    check("po prekresleni stejny panel i krok", win.luxai_panel is p
          and p.stack.get_visible_child_name() == "code-verify" and p.get_toplevel() is win)
    type_code(p.code_login.entry, "12a3 4")
    check("jen cislice, 5 cislic se neodesle", p.code_login.entry.get_text() == "1234" and not p.busy,
          p.code_login.entry.get_text())
    shot(win, "luxai-code-verify" + sfx)
    type_code(p.code_login.entry, "000000")
    check("spatny kod (automaticky odeslan): hlaska", wait(lambda: not p.busy and p.status.get_visible())
          and p.status.get_text() == gui._("The code is not valid or has expired."), p.status.get_text())
    check("spatny kod: pole se vyprazdni", p.code_login.entry.get_text() == "")
    shot(win, "luxai-code-error" + sfx)
    # Poslat znovu po odpoctu (server ma vlastni limit -> slow_down)
    p.code_login.until = time.monotonic() - 1
    p.code_login.update_resend()
    check("po odpoctu lze poslat znovu", p.code_login.resend.get_sensitive()
          and p.code_login.resend.get_label() == gui._("Resend code"))
    p.code_login.resend.clicked()
    check("server: slow_down -> hlaska a novy odpocet",
          wait(lambda: not p.busy and p.status.get_visible())
          and p.status.get_text() == gui._("Please wait a minute before requesting another code.")
          and not p.code_login.resend.get_sensitive(), p.status.get_text())
    SRV.last_sent.clear()
    p.code_login.until = 0
    p.code_login.resend.clicked()
    check("Poslat znovu: novy kod", wait(lambda: not p.busy and len(SRV.sent_codes) == 2)
          and p.status.get_text() == gui._("We sent a new code."), p.status.get_text())
    type_code(p.code_login.entry, "123456")
    check("spravny kod: prihlaseno", wait(lambda: win.s["luxai"] is not None))
    check("kod: ucet jan@", (win.s["luxai"] or {}).get("user", {}).get("email") == "jan@example.cz")
    win.s["luxai"] = None
    win.render()
    pump(0.2)
    p = win.luxai_panel

    # ---- novy ucet ----
    p.switch("register")
    pump(0.2)
    check("rezim registrace", p.stack.get_visible_child_name() == "register-form")
    p.reg_email.set_text("nova@example.cz")
    p.reg_pass.set_text("kratke")
    check("kratke heslo: napoveda s poctem znaku",
          p.reg_hint.get_text() == gui._("At least %d characters (%d more).") % (12, 6), p.reg_hint.get_text())
    check("Vytvorit ucet neaktivni", not p.reg_btn.get_sensitive())
    p.reg_pass.set_text("Velmi-Dlouhe-Heslo-42")
    check("silne heslo", p.reg_hint.get_text() == gui._("Strong password."), p.reg_hint.get_text())
    check("bez souhlasu s podminkami neaktivni", not p.reg_btn.get_sensitive())
    p.reg_pass.set_text("x")
    p.reg_pass.emit("icon-press", Gtk.EntryIconPosition.SECONDARY, Gdk.Event.new(Gdk.EventType.BUTTON_PRESS))
    check("oko: heslo viditelne", p.reg_pass.get_visibility())
    p.reg_pass.emit("icon-press", Gtk.EntryIconPosition.SECONDARY, Gdk.Event.new(Gdk.EventType.BUTTON_PRESS))
    check("oko: heslo znovu skryte", not p.reg_pass.get_visibility())
    p.reg_pass.set_text("Velmi-Dlouhe-Heslo-42")
    shot(win, "luxai-register" + sfx)
    # podminky v dialogu (bez prohlizece)
    dlg = accgtk.show_terms(win, on_agree=lambda: p.reg_terms.set_active(True))
    check("podminky: text nacten", wait(lambda: dlg.terms_stack.get_visible_child_name() == "text"))
    buf = dlg.terms_view.get_buffer()
    txt = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
    check("podminky: prosty text bez HTML", "Podmínky používání LuxAI" in txt and "<" not in txt.replace("<bez>", ""),
          txt[:200])
    shot_dialog(dlg, "luxai-terms" + sfx)
    dlg.response(Gtk.ResponseType.ACCEPT)
    pump(0.2)
    check("Souhlasim v dialogu zaskrtne podminky", p.reg_terms.get_active())
    check("Vytvorit ucet aktivni", p.reg_btn.get_sensitive())
    shot(win, "luxai-register-filled" + sfx)
    # server zatim nepovoluje registraci z LuxOS (403 origin) -> odkaz na web
    SRV.allow_native = False
    p.start_register()
    check("403 origin: srozumitelna hlaska", wait(lambda: not p.busy and p.status.get_visible())
          and SRV.origin + "/register" in p.status.get_text(), p.status.get_text())
    check("403 origin: tlacitko otevrit web", p.action.get_visible())
    p.action.clicked()
    check("tlacitko otevre /register", OPENED[-1:] == [SRV.origin + "/register"], OPENED)
    shot(win, "luxai-register-origin" + sfx)
    SRV.allow_native = True
    # ucet uz existuje -> nabidne prihlaseni
    p.reg_email.set_text("jan@example.cz")
    p.start_register()
    check("existujici ucet: hlaska + Prihlasit", wait(lambda: not p.busy and p.action.get_visible())
          and p.action.get_label() == gui._("Sign In"), p.status.get_text())
    for email, code in (("a@blocked.test", "email_domain_blocked"), ("a@down.test", "email_domain_check_unavailable"),
                        ("a@review.test", "email_domain_review"), ("a@busy.test", "rate")):
        p.reg_email.set_text(email)
        p.start_register()
        check(f"chyba {code}: hlaska", wait(lambda: not p.busy and p.status.get_visible())
              and p.status.get_text() == gui._(acc.ERROR_TEXTS[code]), p.status.get_text())
    p.reg_email.set_text("Nova@Example.cz")
    p.start_register()
    check("registrace: zadani kodu", wait(lambda: p.stack.get_visible_child_name() == "register-verify"))
    sent = [b for m, path, b, _c in SRV.log if path == "/api/auth/register/start"][-1]
    check("registrace: data a termsAccepted", sent == {"email": "nova@example.cz", "password": "Velmi-Dlouhe-Heslo-42",
                                                        "displayName": "Jana Test", "termsAccepted": True}, sent)
    check("ucet zatim nevznikl", "nova@example.cz" not in SRV.accounts)
    shot(win, "luxai-register-code" + sfx)
    type_code(p.code_reg.entry, "123456")
    check("registrace dokoncena a prihlaseno", wait(lambda: win.s["luxai"] is not None))
    check("novy ucet na serveru", SRV.accounts.get("nova@example.cz", {}).get("displayName") == "Jana Test")
    check("JSON uctu pro instalovany system", (win.s["luxai"] or {}).get("user", {}).get("email") == "nova@example.cz")
    check("heslo neni v JSON uctu", "Velmi-Dlouhe" not in str(win.s["luxai"]))
    win.s["luxai"] = None
    win.render()

    # ---- bez internetu ----
    win.online = False
    win.render()
    pump(0.2)
    t = texts(win.scroll)
    check("offline: vysvetleni", gui._("No internet connection") in t, t)
    check("offline: lze preskocit", win.btn_next.get_sensitive() and win.btn_next.get_label() == gui._("Skip"))
    shot(win, "luxai-offline" + sfx)
    win.online = True
    win.render()


def shot_dialog(dlg, name):
    if not SHOTS:
        return
    pump(0.4)
    gw = dlg.get_window()
    pb = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
    if pb:
        pb.savev(os.path.join(SHOTS, name + ".png"), "png", [], [])


def main():
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
    gui.open_url = lambda url: OPENED.append(url)   # zadny prohlizec v testu
    provider = Gtk.CssProvider()
    provider.load_from_data(gui.CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    win = gui.Installer()
    win.s.update({"fullname": "Jana Test", "username": "jana", "pw1": "pw", "pw2": "pw", "hostname": "jana-luxos"})
    pump(0.3)
    for lang, loc in (("en", "en_US.UTF-8"), ("cs", "cs_CZ.UTF-8")):
        gui.set_ui_lang(loc)
        print(f"--- {lang}")
        flows(win, lang)
    # sit vypadne az pri pozadavku -> srozumitelna hlaska z offline_text
    gui.set_ui_lang("en_US.UTF-8")
    win.luxai_panel = None
    p = open_luxai(win)
    SRV.stop()
    p.pw_email.set_text("jan@example.cz")
    p.pw_pass.set_text(PW)
    p.password_login()
    check("vypadek site: hlaska o preskoceni", wait(lambda: not p.busy and p.status.get_visible(), 15)
          and "sign in later in Settings" in p.status.get_text(), p.status.get_text())
    win.destroy()
    print("\n%d chyb" % len(FAILS) if FAILS else "\nvse OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
