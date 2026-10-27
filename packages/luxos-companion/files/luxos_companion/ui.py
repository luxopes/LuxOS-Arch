"""Okno Telefon (LuxOS Companion): schvalene telefony, prepinace opravneni a stav spojeni.

Nastaveni zapisuje primo do companion.json (store.Settings, se zamkem); bezici sluzbe da vedet
pres D-Bus (ReloadSettings), sluzba soubor navic hlida sama. Stav (Bluetooth, pripojeny telefon,
cekajici dotazy na schvaleni) cte z cz.luxos.Companion1 a signalu StatusChanged.
"""
import json
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from . import BUS_NAME, INTERFACE, OBJECT_PATH, store  # noqa: E402

try:
    sys.path.insert(1, "/usr/lib/luxos/python")
    from luxos_i18n import _  # noqa: E402
except ImportError:  # pragma: no cover
    def _(s):
        return s

APP = "luxos-companion"
CSS = b"""
.companion-section { font-size: 11px; font-weight: 700; opacity: 0.6; }
.companion-card { background-color: @theme_base_color; border-radius: 10px; border: 1px solid alpha(black, 0.10); }
.companion-card row { padding: 8px 12px; }
.companion-status { font-weight: 700; }
.dim { opacity: 0.7; }
.small { font-size: 11px; }
"""


def set_window_icons(win):
    """Ikona okna 16-256 px (ostra v Alt+Tab); bez ikony v tematu SVG vedle programu."""
    theme = Gtk.IconTheme.get_default()
    here = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    svg = os.path.join(here, APP + ".svg")
    pixbufs = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        pb = None
        try:
            if theme.has_icon(APP):
                pb = theme.load_icon(APP, size, Gtk.IconLookupFlags.FORCE_SIZE)
            elif os.path.exists(svg):
                pb = GdkPixbuf.Pixbuf.new_from_file_at_size(svg, size, size)
        except GLib.Error:
            pb = None
        if pb:
            pixbufs.append(pb)
    if pixbufs:
        win.set_icon_list(pixbufs)
    else:
        win.set_icon_name(APP)


def label(text="", cls=None, xalign=0.0, wrap=False, **kw):
    lb = Gtk.Label(label=text, xalign=xalign, **kw)
    if wrap:
        lb.set_line_wrap(True)
        lb.set_max_width_chars(60)
    for c in (cls or "").split():
        lb.get_style_context().add_class(c)
    return lb


class CompanionWindow(Gtk.Window):
    def __init__(self, application=None):
        super().__init__(title=_("Phone"))
        if application:
            self.set_application(application)
        self.set_default_size(540, 600)
        set_window_icons(self)
        self.settings = store.Settings()
        self.status = None
        self.bus = None
        self._updating = False
        header = Gtk.HeaderBar(show_close_button=True, title=_("Phone"), subtitle="LuxOS Companion")
        self.set_titlebar(header)

        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.add(scroll)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=18)
        scroll.add(box)

        # stav
        self.status_icon = Gtk.Image(icon_name="phone-symbolic", pixel_size=32)
        self.status_title = label("", "companion-status", wrap=True)
        self.status_detail = label("", "dim small", wrap=True)
        self.start_btn = Gtk.Button(label=_("Start"), valign=Gtk.Align.CENTER, no_show_all=True)
        self.start_btn.connect("clicked", self.on_start)
        top = Gtk.Box(spacing=12, margin=12)
        top.pack_start(self.status_icon, False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        texts.pack_start(self.status_title, False, False, 0)
        texts.pack_start(self.status_detail, False, False, 0)
        top.pack_start(texts, True, True, 0)
        top.pack_end(self.start_btn, False, False, 0)
        box.pack_start(self.card(top), False, False, 0)

        # cekajici dotazy
        self.pending_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.pending_card = self.card(self.pending_box)
        self.pending_card.set_no_show_all(True)
        box.pack_start(self.pending_card, False, False, 0)

        # schvalene telefony
        box.pack_start(label(_("Allowed Phones"), "companion-section", margin_top=10, margin_start=4),
                       False, False, 0)
        self.phones = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.pack_start(self.card(self.phones), False, False, 0)

        # opravneni
        box.pack_start(label(_("Permissions"), "companion-section", margin_top=10, margin_start=4),
                       False, False, 0)
        perms = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.switches = {}
        for key, title, sub in (
                ("share_location", _("Share phone location with Maps"),
                 _("Maps uses it only after you allow My Location in Maps.")),
                ("allow_luxai", _("Allow LuxAI requests from the phone"),
                 _("LuxAI answers with the permissions of this computer; actions are confirmed here.")),
                ("allow_calendar", _("Allow saving notes to Calendar"),
                 _("Notes from the phone are added to your calendar on this computer."))):
            row = Gtk.Box(spacing=12)
            t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            t.pack_start(label(title), False, False, 0)
            t.pack_start(label(sub, "dim small", wrap=True), False, False, 0)
            row.pack_start(t, True, True, 0)
            sw = Gtk.Switch(valign=Gtk.Align.CENTER, active=self.settings.get(key))
            sw.connect("notify::active", self.on_switch, key)
            self.switches[key] = sw
            row.pack_end(sw, False, False, 0)
            perms.add(row)
        box.pack_start(self.card(perms), False, False, 0)

        # napoveda k parovani
        help_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=10)
        help_box.pack_start(label(_(
            "First pair the phone with this computer in Bluetooth settings, then open LuxOS Companion on the "
            "phone and connect. This computer does not become visible to other devices by itself."),
            "dim small", wrap=True), False, False, 0)
        bt = Gtk.Button(label=_("Bluetooth Settings…"), halign=Gtk.Align.START)
        bt.connect("clicked", self.on_bluetooth)
        help_box.pack_start(bt, False, False, 0)
        box.pack_start(help_box, False, False, 0)

        self.rebuild_phones()
        self.connect_bus()
        self.refresh()
        self.connect("destroy", self.on_destroy)

    @staticmethod
    def card(child):
        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.NONE)
        frame.get_style_context().add_class("companion-card")
        frame.add(child)
        return frame

    # ---- D-Bus ----
    def connect_bus(self):
        self.subs = []
        self.watch = None
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            self.bus = None
            return
        self.subs.append(self.bus.signal_subscribe(BUS_NAME, INTERFACE, "StatusChanged", OBJECT_PATH, None, 0,
                                                   self.on_status_signal))
        self.watch = Gio.bus_watch_name_on_connection(self.bus, BUS_NAME, Gio.BusNameWatcherFlags.NONE,
                                                      lambda *_a: self.refresh(), lambda *_a: self.set_status(None))

    def on_destroy(self, _w):
        if self.bus:
            for s in self.subs:
                self.bus.signal_unsubscribe(s)
            if self.watch:
                Gio.bus_unwatch_name(self.watch)

    def call(self, method, params=None, reply=None):
        if not self.bus:
            return

        def done(bus, res, _d):
            try:
                out = bus.call_finish(res)
            except GLib.Error:
                if reply:
                    reply(None)
                return
            if reply:
                reply(out.unpack())
        self.bus.call(BUS_NAME, OBJECT_PATH, INTERFACE, method, params, None,
                      Gio.DBusCallFlags.NO_AUTO_START, 3000, None, done, None)

    def refresh(self):
        self.call("GetStatus", None, lambda r: self.set_status(json.loads(r[0]) if r else None))

    def on_status_signal(self, _c, _s, _p, _i, _sig, params):
        try:
            self.set_status(json.loads(params.unpack()[0]))
        except ValueError:
            pass

    # ---- stav ----
    def set_status(self, st):
        self.status = st
        self.start_btn.hide()
        if st is None:
            icon, title, detail = "dialog-warning-symbolic", _("The phone service is not running."), _(
                "Phones cannot connect until it is started.")
            self.start_btn.show()
        else:
            open_conns = [c for c in st.get("connections", []) if c.get("state") == "open"]
            bt = st.get("bluetooth", {})
            if open_conns:
                icon = "phone-symbolic"
                title = _("Connected: %s") % ", ".join(c["name"] for c in open_conns)
                detail = _("Sharing location") if st.get("location") else _("Connected over Bluetooth")
            elif not bt.get("registered"):
                icon = "bluetooth-disabled-symbolic"
                title = _("Bluetooth is off or not available.")
                detail = bt.get("error") or _("Turn on Bluetooth to connect a phone.")
            else:
                icon = "bluetooth-active-symbolic"
                title = _("Ready for the phone")
                detail = _("Open LuxOS Companion on the phone and connect to this computer.")
        theme = Gtk.IconTheme.get_default()
        self.status_icon.set_from_icon_name(icon if theme.has_icon(icon) else "phone-symbolic", Gtk.IconSize.DND)
        self.status_icon.set_pixel_size(32)
        self.status_title.set_text(title)
        self.status_detail.set_text(detail)
        self.rebuild_pending()
        self.rebuild_phones()
        return False

    def rebuild_pending(self):
        for c in self.pending_box.get_children():
            self.pending_box.remove(c)
        pending = (self.status or {}).get("pending", [])
        for p in pending:
            row = Gtk.Box(spacing=8)
            row.pack_start(label(_("Allow “%s” to connect to LuxOS?") % p["name"], wrap=True), True, True, 0)
            for text, allow in ((_("Deny"), False), (_("Allow"), True)):
                b = Gtk.Button(label=text, valign=Gtk.Align.CENTER)
                if allow:
                    b.get_style_context().add_class("suggested-action")
                b.connect("clicked", lambda _b, a=p["address"], v=allow: self.call(
                    "AnswerApproval", GLib.Variant("(sb)", (a, v))))
                row.pack_start(b, False, False, 0)
            self.pending_box.add(row)
        self.pending_box.show_all()
        self.pending_card.set_visible(bool(pending))
        if pending:
            self.pending_card.show_all()

    def rebuild_phones(self):
        self.settings.reload()
        for c in self.phones.get_children():
            self.phones.remove(c)
        connected = {c["address"] for c in (self.status or {}).get("connections", []) if c.get("state") == "open"}
        phones = self.settings.phones()
        if not phones:
            self.phones.add(label(_("No phone is allowed yet. The first connection from a paired phone asks "
                                    "for permission."), "dim small", wrap=True, margin=4))
        for address, name in phones:
            row = Gtk.Box(spacing=12)
            t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            t.pack_start(label(name), False, False, 0)
            t.pack_start(label(address + ("  ·  " + _("Connected") if address in connected else ""),
                               "dim small"), False, False, 0)
            row.pack_start(t, True, True, 0)
            b = Gtk.Button(label=_("Remove"), valign=Gtk.Align.CENTER)
            b.connect("clicked", self.on_remove, address)
            row.pack_end(b, False, False, 0)
            self.phones.add(row)
        self.phones.show_all()
        self._updating = True
        for key, sw in self.switches.items():
            sw.set_active(self.settings.get(key))
        self._updating = False

    # ---- akce ----
    def on_switch(self, sw, _pspec, key):
        if self._updating:
            return
        try:
            self.settings.set(key, sw.get_active())
        except OSError as e:
            self.error(str(e))
            return
        self.call("ReloadSettings")

    def on_remove(self, _b, address):
        try:
            self.settings.remove(address)
        except OSError as e:
            self.error(str(e))
            return
        self.call("ReloadSettings")
        self.call("Disconnect", GLib.Variant("(s)", (address,)))
        self.rebuild_phones()

    def on_start(self, _b):
        try:
            subprocess.Popen(["systemctl", "--user", "start", "luxos-companion.service"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            self.error(str(e))

    def on_bluetooth(self, _b):
        for cmd in (["luxos-bluetooth"], ["blueman-manager"]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                continue

    def error(self, text):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.CLOSE, text=_("The setting could not be saved."))
        dlg.format_secondary_text(text)
        dlg.connect("response", lambda d, _r: d.destroy())
        dlg.show()


class CompanionApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="cz.luxos.CompanionSettings", flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        from gi.repository import Gdk
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        if self.win is None:
            self.win = CompanionWindow(application=self)
            self.win.show_all()
        self.win.present()


def main():
    GLib.set_prgname(APP)
    return CompanionApp().run([sys.argv[0]])
