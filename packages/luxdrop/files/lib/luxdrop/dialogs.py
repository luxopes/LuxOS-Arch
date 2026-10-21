"""LuxDrop - spolecne prvky GTK: styl, ikony zarizeni, dialog prijeti a zpravy.

Pouziva okno aplikace i sluzba na pozadi (dialog se ukaze i pri zavrenem okne).
"""
import colorsys
import hashlib
import math
import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import proto  # noqa: E402
from .cli import _, human  # noqa: E402

ACCENT = "#1f8fe8"

# Barvy jen pres currentColor/alpha a akcent -> funguje se svetlym i tmavym motivem
CSS = b"""
.navbar { border-top: 1px solid alpha(currentColor, 0.10); padding: 4px 10px 6px; }
.navbar button { border: none; box-shadow: none; background: none; border-radius: 12px; padding: 4px 18px;
                 opacity: 0.62; }
.navbar button:checked { opacity: 1; color: #1f8fe8; background-color: alpha(#1f8fe8, 0.10); }
.navbar button label { font-size: 11px; font-weight: 600; }
.page { padding: 18px 20px; }
.hero-name { font-size: 26px; font-weight: 800; }
.hero-sub { opacity: 0.6; }
.logo-ring { border-radius: 999px; padding: 26px; background-color: alpha(currentColor, 0.05); }
.logo-ring.active { background-color: alpha(#1f8fe8, 0.13); }
.card { border-radius: 14px; border: 1px solid alpha(currentColor, 0.11);
        background-color: alpha(currentColor, 0.035); }
.card row, .card .row { padding: 10px 14px; }
.card list { background: none; }
.section-title { font-size: 13px; font-weight: 700; opacity: 0.7; margin: 14px 4px 6px; }
.dim { opacity: 0.6; }
.small { font-size: 11px; }
.pick { border-radius: 14px; padding: 12px 6px; min-width: 76px; }
.pick label { font-size: 12px; font-weight: 600; }
.chip { border-radius: 10px; padding: 2px 4px 2px 10px; background-color: alpha(currentColor, 0.06); }
.dev-icon { border-radius: 12px; padding: 9px; background-color: alpha(#1f8fe8, 0.12); color: #1f8fe8; }
.dev-icon.lux { background-color: alpha(#7a5cff, 0.14); color: #7a5cff; }
.dev-icon.off { background-color: alpha(currentColor, 0.07); color: alpha(currentColor, 0.5); }
.dev-name { font-weight: 700; }
.badge { font-size: 10px; font-weight: 700; border-radius: 6px; padding: 1px 6px;
         background-color: alpha(#2e9d55, 0.16); color: #2e9d55; }
.badge.warn { background-color: alpha(#d93025, 0.14); color: #d93025; }
.empty { opacity: 0.6; padding: 18px; }
.sas { font-family: monospace; font-size: 34px; font-weight: 800; letter-spacing: 6px; }
.sas-box { border-radius: 12px; background-color: alpha(#1f8fe8, 0.10); padding: 10px 22px; }
.warn { color: #d93025; font-weight: 700; }
.message { font-size: 15px; }
.dropzone.hover { background-color: alpha(#1f8fe8, 0.08); }
progressbar trough, progressbar progress { min-height: 6px; border-radius: 3px; }
"""

_css_loaded = False


def load_css():
    global _css_loaded
    if _css_loaded:
        return
    prov = Gtk.CssProvider()
    prov.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_loaded = True


DEVICE_ICONS = {
    "mobile": ("phone-symbolic", "smartphone-symbolic"),
    "desktop": ("computer-symbolic",),
    "web": ("web-browser-symbolic", "applications-internet-symbolic"),
    "headless": ("utilities-terminal-symbolic",),
    "server": ("network-server-symbolic",),
}


def device_icon_name(kind):
    theme = Gtk.IconTheme.get_default()
    for name in DEVICE_ICONS.get(kind, DEVICE_ICONS["desktop"]):
        if theme.has_icon(name):
            return name
    return "computer-symbolic"


def device_icon(kind, size=26, luxos=False, off=False):
    img = Gtk.Image.new_from_icon_name(device_icon_name(kind), Gtk.IconSize.DND)
    img.set_pixel_size(size)
    box = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
    box.get_style_context().add_class("dev-icon")
    if luxos:
        box.get_style_context().add_class("lux")
    if off:
        box.get_style_context().add_class("off")
    box.pack_start(img, False, False, 0)
    return box


def avatar_colors(key):
    h = hashlib.sha256(key.encode()).digest()
    hue = h[0] / 255.0
    return colorsys.hsv_to_rgb(hue, 0.55, 0.95), colorsys.hsv_to_rgb((hue + 0.08) % 1.0, 0.75, 0.75)


def initials(name):
    words = [w for w in name.replace("(", " ").replace(")", " ").split() if w[:1].isalnum()]
    if not words:
        return "?"
    return (words[0][0] + (words[1][0] if len(words) > 1 else "")).upper()


class Avatar(Gtk.DrawingArea):
    def __init__(self, name, key, size=64):
        super().__init__()
        self.name, self.key, self.size = name, key, size
        self.set_size_request(size, size)
        self.connect("draw", self._draw)

    def _draw(self, _w, cr):
        import cairo
        s = self.size
        x0 = (self.get_allocated_width() - s) / 2
        (r1, g1, b1), (r2, g2, b2) = avatar_colors(self.key)
        grad = cairo.LinearGradient(x0, 0, x0 + s, s)
        grad.add_color_stop_rgb(0, r1, g1, b1)
        grad.add_color_stop_rgb(1, r2, g2, b2)
        cr.arc(x0 + s / 2, s / 2, s / 2, 0, 2 * math.pi)
        cr.set_source(grad)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.select_font_face("Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(s * 0.36)
        text = initials(self.name)
        ext = cr.text_extents(text)
        cr.move_to(x0 + s / 2 - ext.width / 2 - ext.x_bearing, s / 2 - ext.height / 2 - ext.y_bearing)
        cr.show_text(text)
        return False


def sas_widget(code):
    b = Gtk.Box(halign=Gtk.Align.CENTER)
    b.get_style_context().add_class("sas-box")
    lab = Gtk.Label(label=proto.format_sas(code))
    lab.get_style_context().add_class("sas")
    b.pack_start(lab, False, False, 0)
    return b


def open_path(path):
    try:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def kind_label(protocol, device_type, device_model=""):
    if protocol == "luxdrop":
        return "LuxOS"
    names = {"mobile": _("Phone or tablet"), "desktop": _("Computer"), "web": _("Web browser"),
             "headless": _("Terminal"), "server": _("Server")}
    label = names.get(device_type, _("Computer"))
    if device_model and device_model.lower() not in ("luxos",):
        label = "%s · %s" % (label, device_model)
    return "LocalSend · " + label


def accept_dialog(req, on_done, parent=None):
    """Dialog prijeti (nebo zobrazeni zpravy). on_done((prijmout, duverovat)) se zavola prave jednou."""
    load_css()
    if req.message is not None:
        return message_dialog(req, on_done, parent)
    dlg = Gtk.Dialog(title=_("Incoming files"), transient_for=parent, modal=False)
    dlg.set_icon_name("luxdrop")
    dlg.set_keep_above(parent is None)
    dlg.set_default_size(420, -1)
    dlg.add_buttons(_("Decline"), Gtk.ResponseType.CANCEL, _("Accept"), Gtk.ResponseType.OK)
    dlg.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
    dlg.set_urgency_hint(True)
    area = dlg.get_content_area()
    area.set_spacing(10)
    area.set_border_width(18)
    head = Gtk.Box(spacing=12)
    head.pack_start(device_icon(req.device_type, 30, luxos=req.protocol == "luxdrop"), False, False, 0)
    t = Gtk.Label(xalign=0, wrap=True, max_width_chars=44)
    t.set_markup("<b>%s</b>\n<small>%s</small>" % (
        GLib.markup_escape_text(_("“%s” wants to send you %d item(s), %s") %
                                (req.peer_name, len(req.items), human(req.total))),
        GLib.markup_escape_text(kind_label(req.protocol, req.device_type, getattr(req, "device_model", ""))
                                + (" · ID %s" % req.peer_id if req.peer_id else ""))))
    head.pack_start(t, True, True, 0)
    area.pack_start(head, False, False, 0)

    files = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    files.get_style_context().add_class("card")
    for n in req.items[:8]:
        lab = Gtk.Label(label=n, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=48)
        lab.get_style_context().add_class("row")
        files.pack_start(lab, False, False, 0)
    if len(req.items) > 8:
        more = Gtk.Label(label=_("and %d more") % (len(req.items) - 8), xalign=0)
        more.get_style_context().add_class("row")
        files.pack_start(more, False, False, 0)
    area.pack_start(files, False, False, 0)

    if req.name_clash:
        w = Gtk.Label(label=_("Warning: this device uses the name of a trusted device, but its key is "
                              "different. It may be someone else."), xalign=0, wrap=True, max_width_chars=48)
        w.get_style_context().add_class("warn")
        area.pack_start(w, False, False, 0)
    if req.protocol == "localsend" and not req.verified:
        w = Gtk.Label(label=_("The identity of this device cannot be verified (old LocalSend version). "
                              "Accept only if you expect these files."), xalign=0, wrap=True, max_width_chars=48)
        w.get_style_context().add_class("dim")
        area.pack_start(w, False, False, 0)
    trust_cb = None
    if req.sas:
        area.pack_start(Gtk.Label(label=_("Verification code"), xalign=0), False, False, 0)
        area.pack_start(sas_widget(req.sas), False, False, 0)
        area.pack_start(Gtk.Label(label=_("Accept only if the sender shows the same code."),
                                  xalign=0, wrap=True), False, False, 0)
        trust_cb = Gtk.CheckButton(label=_("Trust this device (no code next time)"), active=True)
        area.pack_start(trust_cb, False, False, 0)
    elif req.can_trust:
        trust_cb = Gtk.CheckButton(label=_("Trust this device (save its files without asking next time)"),
                                   active=False)
        area.pack_start(trust_cb, False, False, 0)
    dlg.show_all()
    dlg.present()
    state = {"done": False}

    def finish(v):
        if not state["done"]:
            state["done"] = True
            on_done(v)

    def watch():
        if req.withdrawn.is_set() and not state["done"]:
            dlg.response(Gtk.ResponseType.DELETE_EVENT)
            return False
        return not state["done"]

    GLib.timeout_add(300, watch)

    def on_response(d, r):
        finish((r == Gtk.ResponseType.OK, bool(trust_cb and trust_cb.get_active())))
        d.destroy()

    dlg.connect("response", on_response)
    dlg.finish = finish
    return dlg


def message_dialog(req, on_done, parent=None):
    """Textova zprava z LocalSend: zobrazit, nabidnout kopirovani."""
    dlg = Gtk.Dialog(title=_("Message"), transient_for=parent, modal=False)
    dlg.set_icon_name("luxdrop")
    dlg.set_keep_above(parent is None)
    dlg.set_default_size(420, 260)
    dlg.add_buttons(_("Copy"), 1, _("Close"), Gtk.ResponseType.CLOSE)
    area = dlg.get_content_area()
    area.set_spacing(10)
    area.set_border_width(18)
    head = Gtk.Box(spacing=12)
    head.pack_start(device_icon(req.device_type, 26), False, False, 0)
    t = Gtk.Label(xalign=0, wrap=True)
    t.set_markup("<b>%s</b>" % GLib.markup_escape_text(_("Message from “%s”") % req.peer_name))
    head.pack_start(t, True, True, 0)
    area.pack_start(head, False, False, 0)
    sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    sw.get_style_context().add_class("card")
    tv = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR, cursor_visible=False,
                      left_margin=12, right_margin=12, top_margin=10, bottom_margin=10)
    tv.get_style_context().add_class("message")
    tv.get_buffer().set_text(req.message)
    sw.add(tv)
    area.pack_start(sw, True, True, 0)
    dlg.show_all()
    dlg.present()

    def on_response(d, r):
        if r == 1:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(req.message, -1)
            return
        on_done((False, False))
        d.destroy()

    dlg.connect("response", on_response)
    return dlg


def verify_dialog(parent, info, replied, on_done):
    """Odesilatel LuxDrop: porovnani overovaciho kodu."""
    dlg = Gtk.Dialog(title=_("Verify code"), transient_for=parent, modal=True)
    dlg.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Codes match"), Gtk.ResponseType.OK)
    area = dlg.get_content_area()
    area.set_spacing(10)
    area.set_border_width(18)
    t = Gtk.Label(xalign=0, wrap=True, max_width_chars=50)
    t.set_markup("<b>%s</b>" % GLib.markup_escape_text(_("Does “%s” show the same code?") % info["peer_name"]))
    area.pack_start(t, False, False, 0)
    area.pack_start(sas_widget(info["sas"]), False, False, 0)
    area.pack_start(Gtk.Label(label=_("Compare the code with the screen of the receiving computer. "
                                      "If the codes differ, someone may be intercepting the connection."),
                              xalign=0, wrap=True, max_width_chars=50), False, False, 0)
    remember = Gtk.CheckButton(label=_("Remember this device (no code next time)"), active=True)
    area.pack_start(remember, False, False, 0)
    dlg.show_all()

    def watch():
        if replied.is_set() and not getattr(replied, "accepted", False):
            dlg.response(Gtk.ResponseType.CANCEL)
            return False
        return dlg.get_visible()

    GLib.timeout_add(300, watch)
    r = dlg.run()
    v = (r == Gtk.ResponseType.OK, remember.get_active())
    dlg.destroy()
    on_done(v)


def pin_dialog(parent, peer_name, wrong):
    dlg = Gtk.Dialog(title=_("PIN required"), transient_for=parent, modal=True)
    dlg.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Send"), Gtk.ResponseType.OK)
    dlg.set_default_response(Gtk.ResponseType.OK)
    area = dlg.get_content_area()
    area.set_spacing(10)
    area.set_border_width(18)
    area.pack_start(Gtk.Label(label=(_("Wrong PIN.") + " " if wrong else "") +
                              _("“%s” requires a PIN to receive files.") % peer_name, xalign=0, wrap=True,
                              max_width_chars=44), False, False, 0)
    entry = Gtk.Entry(activates_default=True, visibility=False, max_length=32)
    area.pack_start(entry, False, False, 0)
    dlg.show_all()
    r = dlg.run()
    pin = entry.get_text().strip() if r == Gtk.ResponseType.OK else None
    dlg.destroy()
    return pin or None


def home_short(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + "/") or path == home else path
