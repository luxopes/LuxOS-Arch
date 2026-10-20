"""LuxDrop - graficka aplikace (GTK 3): odesilani, prijem, nastaveni."""
import colorsys
import hashlib
import math
import os
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import proto, store, transfer  # noqa: E402
from .cli import _, human  # noqa: E402
from .identity import Identity  # noqa: E402

APP_ID = "cz.luxos.LuxDrop"
SERVICE = "luxdrop-receiver.service"

CSS = b"""
.dropzone { border: 2px dashed alpha(currentColor, 0.22); border-radius: 18px;
            background-color: alpha(currentColor, 0.03); padding: 22px; }
.dropzone.hover { border-color: #1f8fe8; background-color: alpha(#1f8fe8, 0.09); }
.drop-title { font-size: 17px; font-weight: 700; }
.drop-sub { opacity: 0.6; }
.section-title { font-size: 13px; font-weight: 700; opacity: 0.7; margin: 16px 4px 6px; }
.group { border-radius: 12px; border: 1px solid alpha(currentColor, 0.12);
         background-color: alpha(currentColor, 0.04); }
.group row { padding: 8px 12px; }
.tile { border-radius: 14px; padding: 8px 4px; }
.tile:hover, .tile.hover { background-color: alpha(#1f8fe8, 0.12); }
.tile-name { font-weight: 600; }
.tile-sub { font-size: 11px; opacity: 0.6; }
.empty { opacity: 0.6; padding: 18px; }
.sas { font-family: monospace; font-size: 36px; font-weight: 800; letter-spacing: 6px; }
.sas-box { border-radius: 12px; background-color: alpha(#1f8fe8, 0.10); padding: 12px 24px; }
.warn { color: #d93025; font-weight: 700; }
.dim { opacity: 0.6; }
.group progressbar trough, .group progressbar progress { min-height: 6px; border-radius: 3px; }
.bottom-bar { border-top: 1px solid alpha(currentColor, 0.10); padding: 8px 16px; }
"""

MODE_LABELS = [("off", "Off"), ("trusted", "Trusted devices only"), ("everyone", "Everyone for 10 minutes")]


def avatar_colors(key):
    h = hashlib.sha256(key.encode()).digest()
    hue = h[0] / 255.0
    a = colorsys.hsv_to_rgb(hue, 0.55, 0.95)
    b = colorsys.hsv_to_rgb((hue + 0.08) % 1.0, 0.75, 0.75)
    return a, b


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
        s = self.size
        w = self.get_allocated_width()
        x0 = (w - s) / 2
        (r1, g1, b1), (r2, g2, b2) = avatar_colors(self.key)
        import cairo
        grad = cairo.LinearGradient(x0, 0, x0 + s, s)
        grad.add_color_stop_rgb(0, r1, g1, b1)
        grad.add_color_stop_rgb(1, r2, g2, b2)
        cr.arc(x0 + s / 2, s / 2, s / 2, 0, 2 * math.pi)
        cr.set_source(grad)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.select_font_face("Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(s * 0.36)
        text = "IP" if self.key.startswith("addr:") and self.name == self.key[5:] else initials(self.name)
        ext = cr.text_extents(text)
        cr.move_to(x0 + s / 2 - ext.width / 2 - ext.x_bearing, s / 2 - ext.height / 2 - ext.y_bearing)
        cr.show_text(text)
        return False


def quick_size(path, limit=20000):
    """Velikost souboru/slozky pro zobrazeni (u velkych slozek jen odhad zdola)."""
    try:
        if not os.path.isdir(path):
            return os.path.getsize(path)
    except OSError:
        return 0
    total, n = 0, 0
    for dp, _dns, fns in os.walk(path):
        for f in fns:
            n += 1
            if n > limit:
                return total
            try:
                total += os.lstat(os.path.join(dp, f)).st_size
            except OSError:
                pass
    return total


def section(title):
    lab = Gtk.Label(label=title, xalign=0)
    lab.get_style_context().add_class("section-title")
    return lab


def open_path(path):
    try:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def run_main(fn, *args):
    """Z pracovniho vlakna: zavola fn v hlavnim vlakne GTK a pocka na vysledek."""
    ev, box = threading.Event(), {}

    def call():
        box["v"] = fn(*args)
        ev.set()
        return False

    GLib.idle_add(call)
    ev.wait()
    return box["v"]


class GuiHandler(transfer.Handler):
    """Prijem: dotazy a prubeh v okne aplikace."""

    def __init__(self, win):
        self.win = win

    def ask(self, req):
        ev, box = threading.Event(), {}
        GLib.idle_add(self.win.show_accept_dialog, req, ev, box)
        ev.wait()
        return box.get("v", (False, False))

    def update(self, t):
        GLib.idle_add(self.win.update_transfer, t)

    def finished(self, t):
        GLib.idle_add(self.win.transfer_finished, t)


class GuiSend(transfer.SendCallbacks):
    def __init__(self, win):
        self.win = win
        self._last = 0.0

    def confirm(self, info, replied):
        ev, box = threading.Event(), {}
        GLib.idle_add(self.win.show_verify_dialog, info, replied, ev, box)
        ev.wait()
        return box.get("v", (False, False))

    def update(self, t):
        now = time.monotonic()
        if now - self._last > 0.1 or t.state not in ("transferring", "preparing"):
            self._last = now
            GLib.idle_add(self.win.update_transfer, t)


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="LuxDrop")
        self.app = app
        self.set_default_size(580, 720)
        self.set_icon_name("luxdrop")
        self.set_wmclass("luxdrop", "LuxDrop")
        self.identity = Identity.load_or_create()
        self.settings = store.Settings()
        self.trust = store.TrustStore()
        self.history = store.History()
        self.selection = []
        self.manual = {}  # rucne pridana zarizeni: id -> zaznam
        for a in filter(None, os.environ.get("LUXDROP_PEERS", "").split(",")):
            self.add_manual(a)
        self.rows = {}  # transfer.id -> (row, bar, label, button)
        self.receiver = None
        self.discovery = None
        self.stopped_service = False

        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        hb = Gtk.HeaderBar(show_close_button=True, title="LuxDrop")
        self.set_titlebar(hb)
        gear = Gtk.Button.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON)
        gear.set_tooltip_text(_("Settings"))
        gear.connect("clicked", lambda *_a: self.show_settings())
        hb.pack_end(gear)
        conn = Gtk.Button.new_from_icon_name("network-server-symbolic", Gtk.IconSize.BUTTON)
        conn.set_tooltip_text(_("Connect by address…"))
        conn.connect("clicked", lambda *_a: self.show_connect())
        hb.pack_end(conn)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)
        self.info = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING, show_close_button=True)
        self.info_label = Gtk.Label(xalign=0, wrap=True)
        self.info.get_content_area().add(self.info_label)
        self.info.connect("response", lambda b, _r: b.hide())
        self.info.set_no_show_all(True)
        outer.pack_start(self.info, False, False, 0)

        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        outer.pack_start(scroll, True, True, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=16)
        scroll.add(box)

        # Zona pro pretazeni souboru
        self.drop = Gtk.EventBox()
        self.drop.get_style_context().add_class("dropzone")
        dz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.drop.add(dz)
        icon = Gtk.Image.new_from_icon_name("luxdrop", Gtk.IconSize.DIALOG)
        icon.set_pixel_size(56)
        dz.pack_start(icon, False, False, 0)
        self.drop_title = Gtk.Label(label=_("Drop files here"))
        self.drop_title.get_style_context().add_class("drop-title")
        dz.pack_start(self.drop_title, False, False, 0)
        self.drop_sub = Gtk.Label(label=_("or click to choose files, then pick a device below"),
                                  ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=60)
        self.drop_sub.get_style_context().add_class("drop-sub")
        dz.pack_start(self.drop_sub, False, False, 0)
        btns = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        bf = Gtk.Button(label=_("Choose files…"))
        bf.connect("clicked", lambda *_a: self.choose(False))
        bd = Gtk.Button(label=_("Choose folder…"))
        bd.connect("clicked", lambda *_a: self.choose(True))
        self.clear_btn = Gtk.Button(label=_("Clear"))
        self.clear_btn.connect("clicked", lambda *_a: self.set_selection([]))
        for b in (bf, bd, self.clear_btn):
            btns.pack_start(b, False, False, 0)
        dz.pack_start(btns, False, False, 4)
        self.drop.connect("button-release-event", lambda *_a: self.choose(False) if not self.selection else None)
        self._make_drop_target(self.drop, None)
        box.pack_start(self.drop, False, False, 0)

        # Zarizeni v okoli
        box.pack_start(section(_("Nearby devices")), False, False, 0)
        devbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        devbox.get_style_context().add_class("group")
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=5,
                                min_children_per_line=2, homogeneous=True, column_spacing=6, row_spacing=6)
        devbox.pack_start(self.flow, False, False, 0)
        self.flow_empty = Gtk.Label(label=_("No devices found yet. Open LuxDrop on the other computer, "
                                            "or connect by address."), wrap=True,
                                    justify=Gtk.Justification.CENTER, no_show_all=True)
        self.flow_empty.get_style_context().add_class("empty")
        devbox.pack_start(self.flow_empty, False, False, 0)
        box.pack_start(devbox, False, False, 0)

        # Prenosy
        self.tr_title = section(_("Transfers"))
        box.pack_start(self.tr_title, False, False, 0)
        self.tr_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.tr_list.get_style_context().add_class("group")
        box.pack_start(self.tr_list, False, False, 0)

        # Historie
        hrow = Gtk.Box()
        hrow.pack_start(section(_("Received")), True, True, 0)
        hclear = Gtk.Button(label=_("Clear"), relief=Gtk.ReliefStyle.NONE, valign=Gtk.Align.END)
        hclear.connect("clicked", lambda *_a: (self.history.clear(), self.refresh_history()))
        hrow.pack_end(hclear, False, False, 0)
        box.pack_start(hrow, False, False, 0)
        self.hist_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.hist_list.get_style_context().add_class("group")
        box.pack_start(self.hist_list, False, False, 0)

        # Spodni lista: kdo smi posilat
        bar = Gtk.Box(spacing=8)
        bar.get_style_context().add_class("bottom-bar")
        bar.pack_start(Gtk.Label(label=_("Allow receiving from:")), False, False, 0)
        self.mode_combo = Gtk.ComboBoxText()
        for k, label in MODE_LABELS:
            self.mode_combo.append(k, _(label))
        self.mode_combo.set_active_id(self.settings.mode())
        self.mode_combo.connect("changed", self.on_mode_changed)
        bar.pack_start(self.mode_combo, False, False, 0)
        self.vis_label = Gtk.Label(xalign=1, ellipsize=Pango.EllipsizeMode.END)
        self.vis_label.get_style_context().add_class("dim")
        bar.pack_end(self.vis_label, True, True, 0)
        outer.pack_end(bar, False, False, 0)

        self.connect("destroy", self.on_destroy)
        self.set_selection([])
        self.refresh_history()
        self.refresh_transfers_visibility()
        self.start_receiving()
        self.start_discovery()
        self.refresh_devices()
        GLib.timeout_add_seconds(1, self.tick)

    # --- Vyber souboru ------------------------------------------------------

    def _make_drop_target(self, widget, device):
        widget.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
                             Gdk.DragAction.COPY)
        widget.connect("drag-data-received", self.on_drop, device)
        widget.connect("drag-motion", lambda w, *_a: (w.get_style_context().add_class("hover"), False)[1])
        widget.connect("drag-leave", lambda w, *_a: w.get_style_context().remove_class("hover"))

    def on_drop(self, widget, _ctx, _x, _y, data, _info, _time, device):
        widget.get_style_context().remove_class("hover")
        paths = []
        for uri in data.get_uris() or []:
            try:
                p, _host = GLib.filename_from_uri(uri)
                paths.append(p)
            except GLib.Error:
                continue
        if not paths:
            return
        if device is None:
            self.set_selection(self.selection + [p for p in paths if p not in self.selection])
        else:
            self.send_to(device, paths)

    def choose(self, folders):
        dlg = Gtk.FileChooserNative.new(_("Choose folder") if folders else _("Choose files"), self,
                                        Gtk.FileChooserAction.SELECT_FOLDER if folders else Gtk.FileChooserAction.OPEN,
                                        _("Choose"), _("Cancel"))
        dlg.set_select_multiple(True)
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            new = [f.get_path() for f in dlg.get_files() if f.get_path()]
            self.set_selection(self.selection + [p for p in new if p not in self.selection])
        dlg.destroy()
        return True

    def set_selection(self, paths):
        self.selection = [p for p in paths if os.path.lexists(p)]
        if not self.selection:
            self.drop_title.set_text(_("Drop files here"))
            self.drop_sub.set_text(_("or click to choose files, then pick a device below"))
            self.clear_btn.hide()
        else:
            size = sum(quick_size(p) for p in self.selection)
            n = len(self.selection)
            self.drop_title.set_text(_("%d item(s) ready to send") % n)
            names = ", ".join(os.path.basename(p.rstrip("/")) for p in self.selection[:4])
            self.drop_sub.set_text(names + ("…" if n > 4 else "") + (" · " + human(size) if size else ""))
            self.clear_btn.show()

    # --- Zarizeni -----------------------------------------------------------

    def start_discovery(self):
        try:
            from .discovery import Discovery
        except ImportError:
            return
        if os.environ.get("LUXDROP_NO_MDNS"):
            return
        self.discovery = Discovery(on_change=lambda: GLib.idle_add(self.refresh_devices))
        if not self.discovery.browse():
            self.show_info(_("Nearby devices cannot be found because avahi-daemon is not running. "
                             "You can still connect by address."))
        self.publish()

    def publish(self):
        if not self.discovery or not self.receiver:
            return
        if self.settings.mode() == "off":
            self.discovery.unpublish()
        else:
            self.discovery.publish(self.settings.name, self.identity.id, self.receiver.port)

    def devices(self):
        devs = {}
        if self.discovery:
            for d in self.discovery.devices(self.identity.id):
                devs[d["id"]] = dict(d)
        for k, d in self.manual.items():
            devs.setdefault(k, d)
        trusted = {e.get("id"): e for e in self.trust.peers.values()}
        by_addr = {e.get("last_addr"): e for e in self.trust.peers.values() if e.get("last_addr")}
        for d in devs.values():
            d["trusted"] = d["id"] in trusted
            if d.get("manual") and transfer.fmt_addr(d["host"], d["port"]) in by_addr:
                # Jen zobrazeni - identitu stejne overi otisk po pripojeni
                d = devs[d["id"]] = dict(d, name=by_addr[transfer.fmt_addr(d["host"], d["port"])]["name"],
                                         trusted=True)
        return sorted(devs.values(), key=lambda d: (not d["trusted"], d["name"].lower()))

    def refresh_devices(self):
        self.trust.reload()
        for c in self.flow.get_children():
            self.flow.remove(c)
        devs = self.devices()
        for d in devs:
            self.flow.add(self.device_tile(d))
        self.flow.show_all()
        self.flow.set_visible(bool(devs))
        self.flow_empty.set_visible(not devs)
        return False

    def device_tile(self, d):
        ev = Gtk.EventBox()
        ev.get_style_context().add_class("tile")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        ev.add(v)
        v.pack_start(Avatar(d["name"], d["id"]), False, False, 0)
        name = Gtk.Label(label=d["name"], ellipsize=Pango.EllipsizeMode.END, max_width_chars=14)
        name.get_style_context().add_class("tile-name")
        v.pack_start(name, False, False, 0)
        sub = Gtk.Label(label=_("Trusted") if d["trusted"] else _("Not verified yet"))
        sub.get_style_context().add_class("tile-sub")
        v.pack_start(sub, False, False, 0)
        addr = transfer.fmt_addr(d["host"], d["port"])
        ev.set_tooltip_text("%s\n%s" % (d["name"], addr) if d.get("manual") else
                            "%s\nID %s\n%s" % (d["name"], d["id"], addr))
        ev.connect("button-release-event", lambda *_a: self.send_to(d, None))
        self._make_drop_target(ev, d)
        return ev

    def show_connect(self):
        dlg = Gtk.Dialog(title=_("Connect by address"), transient_for=self, modal=True)
        dlg.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Add"), Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        area = dlg.get_content_area()
        area.set_spacing(8)
        area.set_border_width(16)
        area.pack_start(Gtk.Label(label=_("IP address of the other computer, e.g. 192.168.1.20 or "
                                          "192.168.1.20:%d") % proto.DEFAULT_PORT, xalign=0, wrap=True),
                        False, False, 0)
        entry = Gtk.Entry(activates_default=True)
        area.pack_start(entry, False, False, 0)
        dlg.show_all()
        if dlg.run() == Gtk.ResponseType.OK and entry.get_text().strip():
            if self.add_manual(entry.get_text()):
                self.refresh_devices()
            else:
                self.show_info(_("Invalid address."))
        dlg.destroy()

    def add_manual(self, text):
        """Zarizeni zadane adresou (bez mDNS); identitu overi az TLS + kod."""
        try:
            host, port = transfer.parse_addr(text)
        except ValueError:
            return False
        if not host or not 0 < port < 65536:
            return False
        key = "addr:" + transfer.fmt_addr(host, port)
        self.manual[key] = {"name": transfer.fmt_addr(host, port), "id": key, "host": host,
                            "port": port, "manual": True}
        return True

    # --- Odesilani ----------------------------------------------------------

    def send_to(self, device, paths):
        paths = paths or self.selection
        if not paths:
            self.choose(False)
            paths = self.selection
            if not paths:
                return True
        expected = None
        if not device.get("manual"):
            for fp_hex, e in self.trust.peers.items():
                if e.get("id") == device["id"]:
                    expected = bytes.fromhex(fp_hex)
        t = transfer.Transfer("out", device["name"], device["id"] if not device.get("manual") else "")
        cb = GuiSend(self)
        self.add_transfer_row(t)

        def run():
            transfer.send(self.identity, self.settings, self.trust, self.history, device["host"], device["port"],
                          list(paths), cb, transfer=t, expected_fp=expected)
            GLib.idle_add(self.transfer_finished, t)

        threading.Thread(target=run, daemon=True).start()
        if paths is self.selection:
            self.set_selection([])
        return True

    def show_verify_dialog(self, info, replied, ev, box):
        dlg = Gtk.Dialog(title=_("Verify code"), transient_for=self, modal=True)
        dlg.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Codes match"), Gtk.ResponseType.OK)
        area = dlg.get_content_area()
        area.set_spacing(10)
        area.set_border_width(18)
        t = Gtk.Label(xalign=0, wrap=True, max_width_chars=50)
        t.set_markup("<b>%s</b>" % GLib.markup_escape_text(
            _("Does “%s” show the same code?") % info["peer_name"]))
        area.pack_start(t, False, False, 0)
        area.pack_start(self._sas_widget(info["sas"]), False, False, 0)
        area.pack_start(Gtk.Label(label=_("Compare the code with the screen of the receiving computer. "
                                          "If the codes differ, someone may be intercepting the connection."),
                                  xalign=0, wrap=True, max_width_chars=50), False, False, 0)
        remember = Gtk.CheckButton(label=_("Remember this device (no code next time)"), active=True)
        area.pack_start(remember, False, False, 0)
        dlg.show_all()

        def watch():
            # Prijemce odmitl -> dialog zavrit; po prijeti cekame na potvrzeni zde
            if replied.is_set() and not getattr(replied, "accepted", False):
                dlg.response(Gtk.ResponseType.CANCEL)
                return False
            return dlg.get_visible()

        GLib.timeout_add(300, watch)
        r = dlg.run()
        box["v"] = (r == Gtk.ResponseType.OK, remember.get_active())
        dlg.destroy()
        ev.set()
        return False

    # --- Prijem -------------------------------------------------------------

    def start_receiving(self):
        if not os.environ.get("LUXDROP_NO_SYSTEMD"):
            try:
                if subprocess.run(["systemctl", "--user", "is-active", "--quiet", SERVICE], timeout=5).returncode == 0:
                    subprocess.run(["systemctl", "--user", "stop", SERVICE], timeout=15)
                    self.stopped_service = True
            except (OSError, subprocess.SubprocessError):
                pass
        self.receiver = transfer.Receiver(self.identity, self.settings, self.trust, self.history, GuiHandler(self),
                                          bind=os.environ.get("LUXDROP_BIND", ""))
        try:
            self.receiver.start()
        except OSError as e:
            self.receiver = None
            self.show_info(_("Cannot receive files: port %d is in use (%s). Is LuxDrop already running?")
                           % (self.settings["port"], e.strerror))

    def show_accept_dialog(self, req, ev, box):
        dlg = Gtk.Dialog(title=_("Incoming files"), transient_for=self, modal=False)
        dlg.add_buttons(_("Decline"), Gtk.ResponseType.CANCEL, _("Accept"), Gtk.ResponseType.OK)
        dlg.set_urgency_hint(True)
        area = dlg.get_content_area()
        area.set_spacing(10)
        area.set_border_width(18)
        head = Gtk.Box(spacing=12)
        head.pack_start(Avatar(req.peer_name, req.peer_id, 48), False, False, 0)
        t = Gtk.Label(xalign=0, wrap=True, max_width_chars=46)
        t.set_markup("<b>%s</b>\n<small>ID %s</small>" % (
            GLib.markup_escape_text(_("“%s” wants to send you %d item(s), %s") %
                                    (req.peer_name, len(req.items), human(req.total))),
            req.peer_id))
        head.pack_start(t, True, True, 0)
        area.pack_start(head, False, False, 0)
        names = "\n".join("• " + n for n in req.items[:6]) + ("\n…" if len(req.items) > 6 else "")
        area.pack_start(Gtk.Label(label=names, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE), False, False, 0)
        if req.name_clash:
            w = Gtk.Label(label=_("Warning: this device uses the name of a trusted device, but its key is "
                                  "different. It may be someone else."), xalign=0, wrap=True, max_width_chars=50)
            w.get_style_context().add_class("warn")
            area.pack_start(w, False, False, 0)
        trust_cb = None
        if req.sas:
            area.pack_start(Gtk.Label(label=_("Verification code"), xalign=0), False, False, 0)
            area.pack_start(self._sas_widget(req.sas), False, False, 0)
            area.pack_start(Gtk.Label(label=_("Accept only if the sender shows the same code."),
                                      xalign=0, wrap=True), False, False, 0)
            trust_cb = Gtk.CheckButton(label=_("Trust this device (no code next time)"), active=True)
            area.pack_start(trust_cb, False, False, 0)
        dlg.show_all()
        self.present()
        dlg.present()

        def watch():
            if req.withdrawn.is_set():
                dlg.response(Gtk.ResponseType.DELETE_EVENT)
                return False
            return dlg.get_visible()

        GLib.timeout_add(300, watch)

        def on_response(d, r):
            box["v"] = (r == Gtk.ResponseType.OK, bool(trust_cb and trust_cb.get_active()))
            d.destroy()
            ev.set()

        dlg.connect("response", on_response)
        return False

    def _sas_widget(self, code):
        b = Gtk.Box(halign=Gtk.Align.CENTER)
        b.get_style_context().add_class("sas-box")
        lab = Gtk.Label(label=proto.format_sas(code), selectable=False)
        lab.get_style_context().add_class("sas")
        b.pack_start(lab, False, False, 0)
        return b

    # --- Prubeh prenosu -----------------------------------------------------

    def add_transfer_row(self, t):
        if t.id in self.rows:
            return self.rows[t.id]
        row = Gtk.ListBoxRow(activatable=False)
        h = Gtk.Box(spacing=10)
        row.add(h)
        icon = Gtk.Image.new_from_icon_name("go-up-symbolic" if t.direction == "out" else "go-down-symbolic",
                                            Gtk.IconSize.LARGE_TOOLBAR)
        h.pack_start(icon, False, False, 0)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        h.pack_start(v, True, True, 0)
        title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        v.pack_start(title, False, False, 0)
        bar = Gtk.ProgressBar(no_show_all=True)
        v.pack_start(bar, False, False, 0)
        status = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        status.get_style_context().add_class("tile-sub")
        v.pack_start(status, False, False, 0)
        btn = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON)
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_valign(Gtk.Align.CENTER)
        btn.set_tooltip_text(_("Cancel"))
        btn.connect("clicked", lambda *_a: self.cancel_or_remove(t))
        h.pack_end(btn, False, False, 0)
        self.tr_list.add(row)
        row.show_all()
        self.rows[t.id] = (row, title, bar, status, btn)
        self.refresh_transfers_visibility()
        self.update_transfer(t)
        return self.rows[t.id]

    def cancel_or_remove(self, t):
        if t.state in ("done", "failed", "cancelled", "declined"):
            row = self.rows.pop(t.id)[0]
            self.tr_list.remove(row)
            self.refresh_transfers_visibility()
        else:
            t.cancel()

    def update_transfer(self, t):
        if t.direction == "in" and t.id not in self.rows:
            if not t.items:
                return False
            self.add_transfer_row(t)
        if t.id not in self.rows:
            return False
        _row, title, bar, status, _btn = self.rows[t.id]
        items = ", ".join(t.items[:3]) + ("…" if len(t.items) > 3 else "")
        if t.direction == "out":
            title.set_text(_("To %s: %s") % (t.peer_name or "…", items or "…"))
        else:
            title.set_text(_("From %s: %s") % (t.peer_name, items))
        bar.set_fraction(min(1.0, t.fraction()))
        bar.set_visible(t.state in ("preparing", "transferring", "done") or t.done > 0)
        st = {
            "preparing": _("Preparing (checksums)… %s / %s") % (human(t.done), human(t.total)),
            "connecting": _("Connecting…"),
            "waiting": (_("Waiting for the receiver to accept… code %s") % proto.format_sas(t.sas))
            if t.sas else _("Waiting for acceptance…"),
            "transferring": "%s / %s" % (human(t.done), human(t.total)),
            "done": _("Done"),
            "declined": _("Declined"),
            "cancelled": _("Cancelled"),
            "failed": _("Failed: %s") % t.error,
        }.get(t.state, t.state)
        status.set_text(st)
        status.set_tooltip_text(st)
        return False

    def transfer_finished(self, t):
        self.update_transfer(t)
        if t.id in self.rows:
            self.rows[t.id][4].set_tooltip_text(_("Remove"))
        if t.direction == "in":
            self.refresh_history()
        self.refresh_devices()
        if t.code == proto.E_KEY_MISMATCH:
            self.show_info(_("“%s” presented a different key than the trusted device. Nothing was sent – someone "
                             "may be impersonating it. If it was reinstalled, remove it in Settings and pair "
                             "again.") % (t.peer_name or t.peer_id))
        return False

    def refresh_transfers_visibility(self):
        vis = bool(self.rows)
        self.tr_title.set_visible(vis)
        self.tr_list.set_visible(vis)

    def refresh_history(self):
        for c in self.hist_list.get_children():
            self.hist_list.remove(c)
        items = [e for e in self.history.items() if e.get("direction") == "in" and e.get("state") == "done"][:20]
        if not items:
            lab = Gtk.Label(label=_("Nothing received yet."))
            lab.get_style_context().add_class("empty")
            self.hist_list.add(lab)
        for e in items:
            row = Gtk.ListBoxRow(activatable=False)
            h = Gtk.Box(spacing=10)
            row.add(h)
            h.pack_start(Avatar(e.get("peer", "?"), e.get("peer_id", "?"), 32), False, False, 0)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            h.pack_start(v, True, True, 0)
            names = ", ".join(os.path.basename(p) for p in e.get("saved", [])[:3]) or ", ".join(e.get("items", [])[:3])
            v.pack_start(Gtk.Label(label=names, xalign=0, ellipsize=Pango.EllipsizeMode.END), False, False, 0)
            sub = Gtk.Label(label="%s · %s · %s" % (e.get("peer", "?"), human(e.get("total", 0)),
                                                    time.strftime("%d.%m. %H:%M", time.localtime(e.get("time", 0)))),
                            xalign=0)
            sub.get_style_context().add_class("tile-sub")
            v.pack_start(sub, False, False, 0)
            saved = e.get("saved", [])
            b = Gtk.Button(label=_("Show"), valign=Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, s=saved: open_path(os.path.dirname(s[0]) if s else self.settings.download_dir))
            h.pack_end(b, False, False, 0)
            self.hist_list.add(row)
        self.hist_list.show_all()

    # --- Rezim a nastaveni --------------------------------------------------

    def on_mode_changed(self, combo):
        mode = combo.get_active_id()
        if mode and mode != self.settings.mode():
            self.settings.set_mode(mode)
            self.publish()
        self.tick()

    def tick(self):
        self.settings.reload()
        mode = self.settings.mode()
        if self.mode_combo.get_active_id() != mode:
            self.mode_combo.set_active_id(mode)
            self.publish()
        if not self.receiver:
            self.vis_label.set_text(_("Not receiving"))
        elif mode == "off":
            self.vis_label.set_text(_("Not visible"))
        elif mode == "everyone":
            left = self.settings.everyone_left()
            self.vis_label.set_text(_("Visible as “%s” · %d:%02d left") % (self.settings.name, left // 60, left % 60))
        else:
            self.vis_label.set_text(_("Visible as “%s”") % self.settings.name)
        return True

    def show_info(self, text):
        self.info_label.set_text(text)
        self.info.set_no_show_all(False)
        self.info.show_all()

    def show_settings(self):
        SettingsDialog(self).run_and_close()
        self.settings.reload()
        self.publish()
        self.tick()
        self.refresh_devices()

    def on_destroy(self, *_a):
        if self.receiver:
            self.receiver.stop()
        if self.discovery:
            self.discovery.stop()
        if not os.environ.get("LUXDROP_NO_SYSTEMD") and (self.settings["background"] or self.stopped_service):
            if self.settings["background"]:
                try:
                    subprocess.Popen(["systemctl", "--user", "start", SERVICE])
                except OSError:
                    pass


class SettingsDialog(Gtk.Dialog):
    def __init__(self, win):
        super().__init__(title=_("LuxDrop Settings"), transient_for=win, modal=True)
        self.win = win
        self.s = win.settings
        self.add_buttons(_("Close"), Gtk.ResponseType.CLOSE)
        self.set_default_size(520, 560)
        area = self.get_content_area()
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        area.pack_start(scroll, True, True, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=16)
        scroll.add(box)

        box.pack_start(section(_("This computer")), False, False, 0)
        g = Gtk.Grid(column_spacing=12, row_spacing=10, margin=12)
        frame = Gtk.Box()
        frame.get_style_context().add_class("group")
        frame.pack_start(g, True, True, 0)
        box.pack_start(frame, False, False, 0)
        self.name = Gtk.Entry(text=self.s.name, hexpand=True, max_length=63)
        self._row(g, 0, _("Device name"), self.name)
        self.mode = Gtk.ComboBoxText()
        for k, label in MODE_LABELS:
            self.mode.append(k, _(label))
        self.mode.set_active_id(self.s.mode())
        self._row(g, 1, _("Allow receiving from"), self.mode)
        self.folder = Gtk.FileChooserButton(action=Gtk.FileChooserAction.SELECT_FOLDER)
        os.makedirs(self.s.download_dir, exist_ok=True)
        self.folder.set_filename(self.s.download_dir)
        self._row(g, 2, _("Save received files to"), self.folder)
        self.auto = Gtk.Switch(active=self.s["auto_accept_trusted"], halign=Gtk.Align.START)
        self._row(g, 3, _("Accept automatically from trusted devices"), self.auto)
        self.bg = Gtk.Switch(active=self.s["background"], halign=Gtk.Align.START)
        self._row(g, 4, _("Receive when LuxDrop is closed"), self.bg)
        fp = Gtk.Label(label="ID %s\n%s" % (win.identity.id, proto.format_fp(win.identity.fp)),
                       xalign=0, selectable=True, wrap=True)
        fp.get_style_context().add_class("tile-sub")
        self._row(g, 5, _("Fingerprint"), fp)

        box.pack_start(section(_("Trusted devices")), False, False, 0)
        self.tlist = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.tlist.get_style_context().add_class("group")
        box.pack_start(self.tlist, False, False, 0)
        note = Gtk.Label(label=_("Trusted devices can send to you without a verification code. Remove a device "
                                 "if it was lost or reinstalled."), xalign=0, wrap=True, max_width_chars=60)
        note.get_style_context().add_class("tile-sub")
        note.set_margin_top(6)
        box.pack_start(note, False, False, 0)
        self.fill_trusted()
        self.show_all()

    @staticmethod
    def _row(g, y, label, widget):
        g.attach(Gtk.Label(label=label, xalign=0), 0, y, 1, 1)
        widget.set_valign(Gtk.Align.CENTER)
        g.attach(widget, 1, y, 1, 1)

    def fill_trusted(self):
        for c in self.tlist.get_children():
            self.tlist.remove(c)
        peers = sorted(self.win.trust.peers.items(), key=lambda kv: kv[1].get("name", "").lower())
        if not peers:
            lab = Gtk.Label(label=_("No trusted devices yet."))
            lab.get_style_context().add_class("empty")
            self.tlist.add(lab)
        for fp_hex, e in peers:
            row = Gtk.ListBoxRow(activatable=False)
            h = Gtk.Box(spacing=10)
            row.add(h)
            h.pack_start(Avatar(e.get("name", "?"), e.get("id", fp_hex[:16]), 32), False, False, 0)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            v.pack_start(Gtk.Label(label=e.get("name", "?"), xalign=0), False, False, 0)
            sub = Gtk.Label(label="ID " + e.get("id", fp_hex[:16]), xalign=0)
            sub.get_style_context().add_class("tile-sub")
            v.pack_start(sub, False, False, 0)
            row.set_tooltip_text(proto.format_fp(bytes.fromhex(fp_hex)))
            h.pack_start(v, True, True, 0)
            b = Gtk.Button(label=_("Remove"), valign=Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, k=fp_hex: (self.win.trust.remove(k), self.fill_trusted()))
            h.pack_end(b, False, False, 0)
            self.tlist.add(row)
        self.tlist.show_all()

    def run_and_close(self):
        self.run()
        self.s.data["name"] = self.name.get_text().strip()
        if self.folder.get_filename():
            self.s.data["download_dir"] = self.folder.get_filename()
        self.s.data["auto_accept_trusted"] = self.auto.get_active()
        bg_changed = self.s.data["background"] != self.bg.get_active()
        self.s.data["background"] = self.bg.get_active()
        self.s.save()
        mode = self.mode.get_active_id()
        if mode and mode != self.s.mode():
            self.s.set_mode(mode)
        if bg_changed and not os.environ.get("LUXDROP_NO_SYSTEMD"):
            # Sluzbu jen zapneme/vypneme; spusti se az po zavreni okna (port drzi okno)
            try:
                subprocess.Popen(["systemctl", "--user", "enable" if self.s["background"] else "disable", SERVICE])
            except OSError:
                pass
        self.destroy()


class App(Gtk.Application):
    def __init__(self):
        flags = Gio.ApplicationFlags.HANDLES_OPEN
        if os.environ.get("LUXDROP_NON_UNIQUE"):
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=APP_ID, flags=flags)
        self.win = None

    def do_activate(self):
        if self.win is None:
            self.win = Window(self)
            self.win.show_all()
            self.win.refresh_devices()  # show_all by ukazal i skryte casti
            self.win.set_selection(self.win.selection)
            self.win.refresh_transfers_visibility()
        self.win.present()

    def do_open(self, files, _n, _hint):
        self.do_activate()
        paths = [f.get_path() for f in files if f.get_path()]
        self.win.set_selection(self.win.selection + [p for p in paths if p not in self.win.selection])


def main(argv):
    GLib.set_prgname("luxdrop")
    GLib.set_application_name("LuxDrop")
    app = App()
    return app.run(["luxdrop"] + list(argv))
