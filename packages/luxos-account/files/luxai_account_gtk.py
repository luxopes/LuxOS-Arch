"""LuxOS - spolecny GTK3 panel prihlaseni k uctu LuxAI (instalator i aplikace Ucet LuxAI).

    panel = SignInPanel(on_signed=lambda data: ..., name="Jana Novakova")
    box.pack_start(panel, False, False, 0)

Tri zpusoby (prepinac nahore): heslo, jednorazovy kod z e-mailu a zalozeni noveho uctu
(jmeno, e-mail, heslo, souhlas s podminkami -> kod z e-mailu -> ucet vznikne a prihlasi se).
on_signed dostane obsah account.json (dict) - NEukladany; aplikace ho ulozi pres acc.save(),
instalator ho preda do instalovaneho systemu. Vsechna sitova volani bezi ve vlakne.
"""
import re
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import luxai_account as acc  # noqa: E402
from luxos_i18n import _  # noqa: E402

ACCENT = "#3d7bff"
CSS = """
.luxai-seg button { padding: 4px 14px; }
.luxai-seg button:checked { background-image: none; background-color: ACCENT; color: white; border-color: ACCENT;
                            box-shadow: none; text-shadow: none; }
.luxai-seg button:checked label { color: white; }
.luxai-hint { font-size: 12px; opacity: 0.7; }
.luxai-error { color: #ff453a; }
.luxai-good { color: #30d158; }
.luxai-sent { font-weight: 700; }
.luxai-code { font-family: monospace; font-size: 24px; font-weight: 700; letter-spacing: 10px;
              min-height: 44px; padding: 4px 14px; }
.luxai-primary { border-radius: 8px; padding: 6px 20px; font-weight: 700; background-image: none;
                 background-color: ACCENT; color: white; border: none; box-shadow: none; text-shadow: none; }
.luxai-primary:disabled { background-color: alpha(ACCENT, 0.4); color: alpha(white, 0.8); }
.luxai-primary label { color: white; }
.luxai-link { border: none; background: none; box-shadow: none; color: ACCENT; padding: 2px 4px; }
.luxai-link:disabled { color: alpha(currentColor, 0.45); }
.luxai-action { border-radius: 8px; }
.luxai-terms { font-size: 13px; }
levelbar.luxai-strength trough { min-height: 5px; border-radius: 3px; }
levelbar.luxai-strength block { min-height: 5px; border-radius: 3px; }
""".replace("ACCENT", ACCENT).encode()
_css_done = [False]

MODES = ("password", "code", "register")


def install_css():
    if _css_done[0]:
        return
    screen = Gdk.Screen.get_default()
    if screen is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    _css_done[0] = True


def css(widget, *classes):
    ctx = widget.get_style_context()
    for c in classes:
        ctx.add_class(c)
    return widget


def run_async(work, done):
    """work() ve vlakne, done(vysledek, chyba) v hlavni smycce GTK (chyba = AccountError nebo None)."""
    def target():
        try:
            res, err = work(), None
        except acc.AccountError as e:
            res, err = None, e
        except Exception as e:  # noqa: BLE001 - neocekavana chyba se ukaze jako hlaska
            res, err = None, acc.AccountError("error:" + type(e).__name__)
        GLib.idle_add(lambda: done(res, err) and False)
    threading.Thread(target=target, daemon=True).start()


def open_url(widget, url):
    try:
        Gtk.show_uri_on_window(widget.get_toplevel() if widget else None, url, Gdk.CURRENT_TIME)
    except GLib.Error:
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def valid_email(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()))


def password_strength(pw):
    """(uroven 0-3, hlaska): 0 = kratke (neprojde), 1 = slabsi, 2 = dobre, 3 = silne."""
    if len(pw) > acc.PASSWORD_MAX:
        return 0, _("The password can have at most %d characters.") % acc.PASSWORD_MAX
    if len(pw) < acc.PASSWORD_MIN:
        if not pw:
            return 0, _("At least %d characters.") % acc.PASSWORD_MIN
        return 0, _("At least %d characters (%d more).") % (acc.PASSWORD_MIN, acc.PASSWORD_MIN - len(pw))
    kinds = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z\d]"))
    if len(set(pw)) < 5:
        return 1, _("Easy to guess - use different characters.")
    if len(pw) >= 16 and kinds >= 2 or kinds >= 3:
        return 3, _("Strong password.")
    return 2, _("Good password. Longer is even better.")


def password_entry(placeholder):
    """Pole hesla s ikonou oka (zobrazit / skryt)."""
    e = Gtk.Entry(visibility=False, placeholder_text=placeholder, input_purpose=Gtk.InputPurpose.PASSWORD)
    e.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-reveal-symbolic")
    e.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, _("Show password"))
    e.set_icon_activatable(Gtk.EntryIconPosition.SECONDARY, True)

    def toggle(entry, _pos, _ev):
        vis = not entry.get_visibility()
        entry.set_visibility(vis)
        entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY,
                                      "view-conceal-symbolic" if vis else "view-reveal-symbolic")
        entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY,
                                    _("Hide password") if vis else _("Show password"))
    e.connect("icon-press", toggle)
    return e


def show_terms(parent, on_agree=None):
    """Podminky pouzivani LuxAI v dialogu (stahne /terms a zobrazi jako text, bez prohlizece)."""
    install_css()
    dlg = Gtk.Dialog(title=_("LuxAI Terms of Use"), transient_for=parent, modal=True, use_header_bar=True)
    dlg.set_default_size(600, 560)
    dlg.add_button(_("Close"), Gtk.ResponseType.CLOSE)
    agree = dlg.add_button(_("I Agree"), Gtk.ResponseType.ACCEPT) if on_agree else None
    if agree:
        css(agree, "luxai-primary")
        agree.set_sensitive(False)
    area = dlg.get_content_area()
    area.set_spacing(8)
    stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
    area.pack_start(stack, True, True, 0)
    loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER)
    spinner = Gtk.Spinner(active=True)
    loading.pack_start(spinner, False, False, 0)
    loading.pack_start(Gtk.Label(label=_("Loading the terms…")), False, False, 0)
    stack.add_named(loading, "loading")
    view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                        left_margin=22, right_margin=22, top_margin=16, bottom_margin=16, pixels_below_lines=2)
    css(view, "luxai-terms")
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
    sw.add(view)
    stack.add_named(sw, "text")
    fail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER, margin=24)
    fail_msg = css(Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=50), "luxai-error")
    fail.pack_start(fail_msg, False, False, 0)
    retry = Gtk.Button(label=_("Try Again"), halign=Gtk.Align.CENTER)
    fail.pack_start(retry, False, False, 0)
    stack.add_named(fail, "fail")
    dlg.terms_view, dlg.terms_stack = view, stack   # pro testy

    def loaded(text, err):
        if not dlg.get_visible():
            return
        if err:
            fail_msg.set_text(acc.error_text(err, _) + "\n" + _("You can also read them at %s") % acc.TERMS_URL)
            stack.set_visible_child_name("fail")
            return
        buf = view.get_buffer()
        buf.set_text(text)
        # nadpis stranky (prvni kratky radek bez cislic) vetsim pismem
        title = buf.create_tag("title", weight=800, scale=1.3)
        lines = text.split("\n")
        start = buf.get_start_iter()
        for i, line in enumerate(lines[:4]):
            if line and len(line) < 80 and not re.search(r"\d", line):
                s = buf.get_iter_at_line(i)
                e = s.copy()
                e.forward_to_line_end()
                buf.apply_tag(title, s, e)
                break
        # nadpisy oddilu ("1. ...", kratke radky mezi prazdnymi)
        head = buf.create_tag("head", weight=700)
        for i, line in enumerate(lines):
            if (re.match(r"\d+\. \S", line) and len(line) < 90 and (i == 0 or not lines[i - 1].strip())
                    and (i + 1 >= len(lines) or not lines[i + 1].strip())):
                s = buf.get_iter_at_line(i)
                e = s.copy()
                e.forward_to_line_end()
                buf.apply_tag(head, s, e)
        buf.place_cursor(start)
        stack.set_visible_child_name("text")
        if agree:
            agree.set_sensitive(True)

    def load(*_a):
        stack.set_visible_child_name("loading")
        run_async(acc.fetch_terms, loaded)
    retry.connect("clicked", load)

    def response(d, resp):
        if resp == Gtk.ResponseType.ACCEPT and on_agree:
            on_agree()
        d.destroy()
    dlg.connect("response", response)
    dlg.show_all()
    load()
    return dlg


class CodeEntry(Gtk.Box):
    """Sestimistny kod z e-mailu: jen cislice, po 6. cislici se sam odesle; Poslat znovu s odpoctem."""

    def __init__(self, on_code, on_resend, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.on_code, self.on_resend = on_code, on_resend
        self.sent = css(Gtk.Label(xalign=0, wrap=True, max_width_chars=60), "luxai-sent")
        self.pack_start(self.sent, False, False, 0)
        self.entry = css(Gtk.Entry(max_length=6, width_chars=6, width_request=230, xalign=0.5,
                                   placeholder_text="000000", input_purpose=Gtk.InputPurpose.DIGITS,
                                   halign=Gtk.Align.START), "luxai-code")
        self.entry.connect("changed", self.changed)
        self.entry.connect("activate", lambda _e: self.submit())
        self.pack_start(self.entry, False, False, 0)
        self.pack_start(css(Gtk.Label(label=_("The code is valid for 10 minutes. Check also the spam folder."),
                                      xalign=0, wrap=True, max_width_chars=60), "luxai-hint"), False, False, 0)
        row = Gtk.Box(spacing=4)
        self.resend = css(Gtk.Button(), "luxai-link")
        self.resend.connect("clicked", lambda _b: self.on_resend())
        back = css(Gtk.Button(label=_("Use a different e-mail")), "luxai-link")
        back.connect("clicked", lambda _b: on_back())
        row.pack_start(self.resend, False, False, 0)
        row.pack_start(Gtk.Label(label="·"), False, False, 0)
        row.pack_start(back, False, False, 0)
        self.pack_start(row, False, False, 0)
        self.until = 0.0
        self.busy = False
        self._fixing = False
        self._tick = None
        self.connect("destroy", lambda *_a: self._tick and GLib.source_remove(self._tick))
        self.update_resend()

    def set_email(self, email):
        self.sent.set_text(_("We sent a code to %s.") % email)

    def reset(self):
        self._fixing = True
        self.entry.set_text("")
        self._fixing = False

    def changed(self, entry):
        if self._fixing:
            return
        text = entry.get_text()
        digits = re.sub(r"\D", "", text)[:6]
        if digits != text:   # vlozeny kod "123 456" nebo s pismeny -> jen cislice
            self._fixing = True
            entry.set_text(digits)
            entry.set_position(-1)
            self._fixing = False
        if len(digits) == 6:
            self.submit()

    def submit(self):
        code = self.entry.get_text()
        if self.busy or len(code) != 6:
            return
        self.on_code(code)

    def cooldown(self, seconds):
        self.until = time.monotonic() + seconds
        self.update_resend()
        if not self._tick:
            self._tick = GLib.timeout_add(500, self._on_tick)

    def remaining(self):
        return max(0, int(self.until - time.monotonic() + 0.999))

    def _on_tick(self):
        self.update_resend()
        if self.remaining() <= 0:
            self._tick = None
            return False
        return True

    def update_resend(self):
        left = self.remaining()
        if left > 0:
            self.resend.set_label(_("Resend code in %d s") % left)
        else:
            self.resend.set_label(_("Resend code"))
        self.resend.set_sensitive(left <= 0 and not self.busy)

    def set_busy(self, on):
        self.busy = on
        self.entry.set_sensitive(not on)
        self.update_resend()


class SignInPanel(Gtk.Box):
    """Prihlaseni heslem / kodem / zalozeni uctu. Stav (rezim, e-mail, odpocet) drzi sam panel, takze
    ho instalator muze pri prekresleni stranky jen presunout na novou stranku."""

    def __init__(self, on_signed, name="", email="", mode="password", offline_text=None, open_url_fn=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        install_css()
        self.on_signed = on_signed
        self.offline_text = offline_text
        self.open_url = open_url_fn or (lambda url: open_url(self, url))
        self.mode = mode
        self.stage = {"code": "email", "register": "form"}
        self.pending = {"code": "", "register": None}   # e-mail, kam odesel kod / udaje registrace
        self.busy = False

        seg = css(Gtk.Box(halign=Gtk.Align.START), "linked", "luxai-seg")
        self.seg = {}
        group = None
        for key, label in (("password", _("Password")), ("code", _("E-mail Code")),
                           ("register", _("New Account"))):
            b = Gtk.RadioButton(label=label, group=group, draw_indicator=False)
            group = group or b
            b.connect("toggled", lambda w, k=key: w.get_active() and self.set_mode(k))
            seg.pack_start(b, False, False, 0)
            self.seg[key] = b
        self.pack_start(seg, False, False, 0)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=150,
                               vhomogeneous=False, interpolate_size=True)
        self.pack_start(self.stack, False, False, 0)
        self.stack.add_named(self.build_password(email), "password")
        self.stack.add_named(self.build_code_email(email), "code-email")
        self.code_login = CodeEntry(self.verify_login_code, self.resend_login_code, lambda: self.set_stage("email"))
        self.stack.add_named(self.code_login, "code-verify")
        self.stack.add_named(self.build_register(name, email), "register-form")
        self.code_reg = CodeEntry(self.verify_register_code, self.resend_register_code,
                                  lambda: self.set_stage("form"))
        self.stack.add_named(self.code_reg, "register-verify")

        bottom = Gtk.Box(spacing=10)
        self.spinner = Gtk.Spinner()
        self.spinner.set_no_show_all(True)   # zastaveny spinner by odsazoval hlasku
        bottom.pack_start(self.spinner, False, False, 0)
        self.status = css(Gtk.Label(xalign=0, wrap=True, max_width_chars=64), "luxai-error")
        self.status.set_no_show_all(True)
        bottom.pack_start(self.status, True, True, 0)
        self.pack_start(bottom, False, False, 0)
        self.action = css(Gtk.Button(halign=Gtk.Align.START), "luxai-action")
        self.action.set_no_show_all(True)
        self.action.connect("clicked", lambda _b: self._action and self._action())
        self._action = None
        self.pack_start(self.action, False, False, 0)
        self.seg[mode].set_active(True)
        self.set_mode(mode)

    # ---- stavba ----
    def build_password(self, email):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.pw_email = Gtk.Entry(text=email, placeholder_text=_("E-mail"), input_purpose=Gtk.InputPurpose.EMAIL)
        self.pw_pass = password_entry(_("Password"))
        self.pw_pass.connect("activate", lambda _e: self.password_login())
        self.pw_email.connect("activate", lambda _e: self.pw_pass.grab_focus())
        box.pack_start(self.pw_email, False, False, 0)
        box.pack_start(self.pw_pass, False, False, 0)
        row = Gtk.Box(spacing=10)
        self.pw_btn = css(Gtk.Button(label=_("Sign In")), "luxai-primary")
        self.pw_btn.connect("clicked", lambda _b: self.password_login())
        forgot = css(Gtk.Button(label=_("Forgot password? Sign in with a code")), "luxai-link")
        forgot.connect("clicked", lambda _b: self.switch("code"))
        row.pack_start(self.pw_btn, False, False, 0)
        row.pack_start(forgot, False, False, 0)
        box.pack_start(row, False, False, 0)
        return box

    def build_code_email(self, email):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.pack_start(css(Gtk.Label(label=_("We will e-mail you a 6-digit code - no password needed."),
                                     xalign=0, wrap=True, max_width_chars=64), "luxai-hint"), False, False, 0)
        self.code_email = Gtk.Entry(text=email, placeholder_text=_("E-mail"), input_purpose=Gtk.InputPurpose.EMAIL)
        self.code_email.connect("activate", lambda _e: self.send_login_code())
        box.pack_start(self.code_email, False, False, 0)
        self.code_btn = css(Gtk.Button(label=_("Send Code"), halign=Gtk.Align.START), "luxai-primary")
        self.code_btn.connect("clicked", lambda _b: self.send_login_code())
        box.pack_start(self.code_btn, False, False, 0)
        return box

    def build_register(self, name, email):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.reg_name = Gtk.Entry(text=name, placeholder_text=_("Your name"), max_length=acc.NAME_MAX)
        self.reg_email = Gtk.Entry(text=email, placeholder_text=_("E-mail"), input_purpose=Gtk.InputPurpose.EMAIL)
        self.reg_pass = password_entry(_("Password (at least %d characters)") % acc.PASSWORD_MIN)
        for e in (self.reg_name, self.reg_email, self.reg_pass):
            box.pack_start(e, False, False, 0)
            e.connect("changed", lambda _e: self.update_register())
        self.reg_pass.connect("activate", lambda _e: self.start_register())
        strength = Gtk.Box(spacing=10)
        self.reg_bar = css(Gtk.LevelBar(min_value=0, max_value=3, width_request=90, valign=Gtk.Align.CENTER),
                           "luxai-strength")
        self.reg_bar.add_offset_value("low", 1)
        self.reg_bar.add_offset_value("high", 2)
        self.reg_bar.add_offset_value("full", 3)
        self.reg_hint = css(Gtk.Label(xalign=0, wrap=True), "luxai-hint")
        strength.pack_start(self.reg_bar, False, False, 0)
        strength.pack_start(self.reg_hint, True, True, 0)
        box.pack_start(strength, False, False, 0)
        terms = Gtk.Box(spacing=2)
        self.reg_terms = Gtk.CheckButton(label=_("I agree to the LuxAI Terms"))
        self.reg_terms.connect("toggled", lambda _c: self.update_register())
        read = css(Gtk.Button(label=_("Read the terms")), "luxai-link")
        read.connect("clicked", lambda _b: show_terms(self.get_toplevel(),
                                                      on_agree=lambda: self.reg_terms.set_active(True)))
        terms.pack_start(self.reg_terms, False, False, 0)
        terms.pack_start(read, False, False, 0)
        box.pack_start(terms, False, False, 0)
        self.reg_btn = css(Gtk.Button(label=_("Create Account"), halign=Gtk.Align.START), "luxai-primary")
        self.reg_btn.connect("clicked", lambda _b: self.start_register())
        box.pack_start(self.reg_btn, False, False, 0)
        self.update_register()
        return box

    # ---- prepinani ----
    def switch(self, mode):
        """Prepne rezim i tlacitko prepinace (e-mail se prenese)."""
        self.seg[mode].set_active(True)
        self.set_mode(mode)

    def current_email(self):
        return {"password": self.pw_email, "code": self.code_email, "register": self.reg_email}[self.mode] \
            .get_text().strip()

    def set_mode(self, mode):
        email = self.current_email() if hasattr(self, "reg_email") else ""
        self.mode = mode
        if email and not self.busy:
            for e in (self.pw_email, self.code_email, self.reg_email):
                if not e.get_text().strip():
                    e.set_text(email)
        self.say("")
        self.show_stage()

    def set_stage(self, stage):
        self.stage[self.mode] = stage
        self.say("")
        self.show_stage()

    def show_stage(self):
        name = {"password": "password", "code": "code-" + self.stage["code"],
                "register": "register-" + self.stage["register"]}[self.mode]
        self.stack.set_visible_child_name(name)
        GLib.idle_add(self.focus_first)

    def focus_first(self):
        name = self.stack.get_visible_child_name()
        w = {"password": self.pw_pass if self.pw_email.get_text() else self.pw_email,
             "code-email": self.code_email, "code-verify": self.code_login.entry,
             "register-form": self.reg_name if not self.reg_name.get_text() else self.reg_email,
             "register-verify": self.code_reg.entry}.get(name)
        if w and w.get_mapped() and w.get_sensitive():
            w.grab_focus_without_selecting()
        return False

    # ---- stav a hlasky ----
    def say(self, text, kind="error", action=None):
        """Hlaska pod formularem; action = (popisek, funkce) prida tlacitko (napr. otevrit web)."""
        self.status.set_text(text)
        self.status.set_visible(bool(text))
        ctx = self.status.get_style_context()
        for c in ("luxai-error", "luxai-good", "luxai-hint"):
            ctx.remove_class(c)
        ctx.add_class({"error": "luxai-error", "good": "luxai-good"}.get(kind, "luxai-hint"))
        self._action = action[1] if action else None
        self.action.set_label(action[0] if action else "")
        self.action.set_visible(bool(action))

    def set_busy(self, on):
        self.busy = on
        (self.spinner.start if on else self.spinner.stop)()
        self.spinner.set_visible(on)
        for w in (self.pw_btn, self.code_btn, self.pw_email, self.pw_pass, self.code_email,
                  self.reg_name, self.reg_email, self.reg_pass, self.reg_terms):
            w.set_sensitive(not on)
        for b in self.seg.values():
            b.set_sensitive(not on)
        self.code_login.set_busy(on)
        self.code_reg.set_busy(on)
        self.update_register()

    def fail(self, err):
        code = getattr(err, "code", "")
        if code == "network" and self.offline_text:
            self.say(self.offline_text)
        elif code == "origin":
            self.say(acc.error_text(err, _),
                     action=(_("Open %s") % acc.REGISTER_URL.split("://", 1)[-1],
                             lambda: self.open_url(acc.REGISTER_URL)))
        elif code == "account_exists":
            self.say(acc.error_text(err, _), action=(_("Sign In"), lambda: self.switch("password")))
        elif code == "email_unverified":
            self.say(acc.error_text(err, _), action=(_("Send Code"), self.unverified_to_code))
        else:
            self.say(acc.error_text(err, _))

    def unverified_to_code(self):
        email = self.pw_email.get_text().strip()
        self.code_email.set_text(email)
        self.switch("code")
        self.send_login_code()

    def signed(self, data, err):
        self.set_busy(False)
        if err:
            self.fail(err)
            for c in (self.code_login, self.code_reg):
                if err.code == "invalid_code" and c.get_mapped():
                    c.reset()
                    c.entry.grab_focus()
            return
        self.pw_pass.set_text("")
        self.reg_pass.set_text("")
        self.pending["register"] = None
        self.on_signed(data)

    # ---- heslo ----
    def password_login(self):
        email, pw = self.pw_email.get_text().strip(), self.pw_pass.get_text()
        if self.busy:
            return
        if not email or not pw:
            self.say(_("Enter your e-mail and password."))
            return
        self.say("")
        self.set_busy(True)
        run_async(lambda: acc.password_session(email, pw), self.signed)

    # ---- kod ----
    def send_login_code(self, resend=False):
        email = (self.pending["code"] if resend else self.code_email.get_text()).strip().lower()
        if self.busy:
            return
        if not valid_email(email):
            self.say(_("Enter a valid e-mail address."))
            return
        self.say("")
        self.set_busy(True)

        def sent(_res, err):
            self.set_busy(False)
            if err and not (err.code == "slow_down" and self.stage["code"] == "verify"):
                self.fail(err)
                if err.code == "slow_down" and email == self.pending["code"]:
                    self.code_login.cooldown(err.retry_after or acc.CODE_COOLDOWN)
                return
            self.pending["code"] = email
            self.code_login.set_email(email)
            self.code_login.reset()
            self.code_login.cooldown((err.retry_after if err else 0) or acc.CODE_COOLDOWN)
            self.set_stage("verify")
            if err:
                self.fail(err)
            elif resend:
                self.say(_("We sent a new code."), "good")
        run_async(lambda: acc.request_code(email), sent)

    def resend_login_code(self):
        self.send_login_code(resend=True)

    def verify_login_code(self, code):
        email = self.pending["code"]
        self.say("")
        self.set_busy(True)
        run_async(lambda: acc.verify_code(email, code), self.signed)

    # ---- registrace ----
    def register_problem(self):
        if not self.reg_name.get_text().strip():
            return _("Enter your name.")
        if not valid_email(self.reg_email.get_text()):
            return _("Enter a valid e-mail address.")
        if acc.password_problem(self.reg_pass.get_text()):
            return _("The password must have at least 12 characters.") \
                if len(self.reg_pass.get_text()) < acc.PASSWORD_MIN else password_strength(self.reg_pass.get_text())[1]
        if not self.reg_terms.get_active():
            return _("You need to agree to the LuxAI Terms.")
        return ""

    def update_register(self):
        if not hasattr(self, "reg_btn"):
            return
        level, text = password_strength(self.reg_pass.get_text())
        self.reg_bar.set_value(level)
        self.reg_hint.set_text(text)
        ctx = self.reg_hint.get_style_context()
        (ctx.add_class if level >= 2 else ctx.remove_class)("luxai-good")
        problem = self.register_problem()
        self.reg_btn.set_sensitive(not problem and not self.busy)
        self.reg_btn.set_tooltip_text(problem or None)

    def start_register(self, resend=False):
        if self.busy:
            return
        if resend and self.pending["register"]:
            name, email, pw = self.pending["register"]
        else:
            problem = self.register_problem()
            if problem:
                self.say(problem)
                return
            name, email, pw = (self.reg_name.get_text().strip(), self.reg_email.get_text().strip().lower(),
                               self.reg_pass.get_text())
        self.say("")
        self.set_busy(True)

        def sent(_res, err):
            self.set_busy(False)
            if err and not (err.code == "slow_down" and self.stage["register"] == "verify"):
                self.fail(err)
                return
            self.pending["register"] = (name, email, pw)
            self.code_reg.set_email(email)
            self.code_reg.reset()
            self.code_reg.cooldown((err.retry_after if err else 0) or acc.CODE_COOLDOWN)
            self.set_stage("verify")
            if err:
                self.fail(err)
            elif resend:
                self.say(_("We sent a new code."), "good")
        run_async(lambda: acc.register_start(email, pw, name), sent)

    def resend_register_code(self):
        self.start_register(resend=True)

    def verify_register_code(self, code):
        email = self.pending["register"][1] if self.pending["register"] else ""
        self.say("")
        self.set_busy(True)
        run_async(lambda: acc.verify_code(email, code), self.signed)
