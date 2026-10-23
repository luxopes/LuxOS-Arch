"""LuxDrop - graficka aplikace (GTK 3) ve stylu LocalSend: Prijem, Odeslat, Nastaveni."""
import os
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import dialogs, lsdiscovery, proto, store, transfer  # noqa: E402
from .cli import _, human  # noqa: E402
from .dialogs import device_icon, kind_label, open_path  # noqa: E402
from .engine import Engine  # noqa: E402
from .identity import Identity  # noqa: E402

APP_ID = "cz.luxos.LuxDrop"
SERVICE = "luxdrop-receiver.service"
FINAL = ("done", "failed", "cancelled", "declined")


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


def card():
    lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    lb.get_style_context().add_class("card")
    return lb


def row(label, widget, sub=None):
    r = Gtk.ListBoxRow(activatable=False)
    h = Gtk.Box(spacing=12)
    r.add(h)
    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
    v.pack_start(Gtk.Label(label=label, xalign=0, wrap=True), False, False, 0)
    if sub:
        s = Gtk.Label(label=sub, xalign=0, wrap=True, max_width_chars=40)
        s.get_style_context().add_class("dim")
        s.get_style_context().add_class("small")
        v.pack_start(s, False, False, 0)
    h.pack_start(v, True, True, 0)
    widget.set_valign(Gtk.Align.CENTER)
    h.pack_end(widget, False, False, 0)
    return r


def local_ips():
    try:
        return [a for _n, a, _m in lsdiscovery.interfaces()]
    except OSError:
        return []


class GuiHandler(transfer.Handler):
    """Prijem: dotazy a prubeh v okne aplikace."""

    def __init__(self, win):
        self.win = win

    def ask(self, req):
        ev, box = threading.Event(), {}

        def done(v):
            box["v"] = v
            ev.set()

        GLib.idle_add(self.win.show_accept, req, done)
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

        def done(v):
            box["v"] = v
            ev.set()

        GLib.idle_add(lambda: dialogs.verify_dialog(self.win, info, replied, done) and False)
        ev.wait()
        return box.get("v", (False, False))

    def ask_pin(self, peer_name, wrong):
        ev, box = threading.Event(), {}

        def run():
            box["v"] = dialogs.pin_dialog(self.win, peer_name, wrong)
            ev.set()
            return False

        GLib.idle_add(run)
        ev.wait()
        return box.get("v")

    def update(self, t):
        now = time.monotonic()
        if now - self._last > 0.1 or t.state not in ("transferring", "preparing"):
            self._last = now
            GLib.idle_add(self.win.update_transfer, t)


class NavButton(Gtk.RadioButton):
    def __init__(self, group, icon, label):
        super().__init__(group=group, draw_indicator=False)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
        v.pack_start(img, False, False, 0)
        v.pack_start(Gtk.Label(label=label), False, False, 0)
        self.add(v)
        self.set_relief(Gtk.ReliefStyle.NONE)


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="LuxDrop")
        self.app = app
        self.set_default_size(460, 720)
        self.set_icon_name("luxdrop")
        self.set_wmclass("luxdrop", "LuxDrop")
        dialogs.load_css()
        self.identity = Identity.load_or_create()
        self.settings = store.Settings()
        self.trust = store.TrustStore()
        self.history = store.History()
        self.selection = []      # cesty k odeslani
        self.text = None         # nebo text k odeslani
        self.manual = {}         # zarizeni pridana adresou
        self.rows = {}           # transfer.id -> widgety
        self.stopped_service = False
        self._ui_lock = False
        self._refresh_pending = False

        hb = Gtk.HeaderBar(show_close_button=True, title="LuxDrop")
        self.set_titlebar(hb)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)
        self.info = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING, show_close_button=True)
        self.info_label = Gtk.Label(xalign=0, wrap=True)
        self.info.get_content_area().add(self.info_label)
        self.info.connect("response", lambda b, _r: b.hide())
        self.info.set_no_show_all(True)
        outer.pack_start(self.info, False, False, 0)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        outer.pack_start(self.stack, True, True, 0)
        self.stack.add_named(self._scroll(self.build_receive()), "receive")
        self.stack.add_named(self._scroll(self.build_send()), "send")
        self.stack.add_named(self._scroll(self.build_settings()), "settings")

        nav = Gtk.Box(spacing=6, homogeneous=True)
        nav.get_style_context().add_class("navbar")
        self.nav = {}
        group = None
        for key, icon, label in (("receive", "folder-download-symbolic", _("Receive")),
                                 ("send", "document-send-symbolic", _("Send")),
                                 ("settings", "emblem-system-symbolic", _("Settings"))):
            b = NavButton(group, icon, label)
            group = group or b
            b.connect("toggled", self.on_nav, key)
            nav.pack_start(b, True, True, 0)
            self.nav[key] = b
        outer.pack_end(nav, False, False, 0)

        self.connect("destroy", self.on_destroy)
        self.start_engine()
        GLib.timeout_add_seconds(1, self.tick)

    @staticmethod
    def _scroll(child):
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.add(child)
        return sw

    def on_nav(self, button, key):
        if button.get_active():
            self.stack.set_visible_child_name(key)
            if key == "settings":
                self.fill_trusted()

    def show_page(self, key):
        self.nav[key].set_active(True)

    # --- Prijem ---------------------------------------------------------------

    def build_receive(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.get_style_context().add_class("page")
        self.logo = Gtk.Box(halign=Gtk.Align.CENTER, margin_top=18)
        self.logo.get_style_context().add_class("logo-ring")
        icon = Gtk.Image.new_from_icon_name("luxdrop", Gtk.IconSize.DIALOG)
        icon.set_pixel_size(110)
        self.logo.pack_start(icon, False, False, 0)
        box.pack_start(self.logo, False, False, 0)
        self.hero_name = Gtk.Label(ellipsize=Pango.EllipsizeMode.END, margin_top=10)
        self.hero_name.get_style_context().add_class("hero-name")
        box.pack_start(self.hero_name, False, False, 0)
        self.hero_sub = Gtk.Label()
        self.hero_sub.get_style_context().add_class("hero-sub")
        box.pack_start(self.hero_sub, False, False, 0)
        self.status = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, margin_bottom=8)
        self.status.get_style_context().add_class("dim")
        box.pack_start(self.status, False, False, 0)

        c = card()
        self.ready = Gtk.Switch()
        self.ready.connect("notify::active", self.on_ready)
        c.add(row(_("Ready to receive"), self.ready))
        self.who = Gtk.ComboBoxText()
        self.who.append("everyone", _("Everyone nearby"))
        self.who.append("trusted", _("Trusted devices only"))
        self.who.connect("changed", self.on_who)
        c.add(row(_("Who can send"), self.who, _("Every transfer from other devices must be accepted.")))
        self.quick = Gtk.Switch()
        self.quick.connect("notify::active", lambda s, _p: self._set("auto_accept_trusted", s.get_active()))
        c.add(row(_("Quick save"), self.quick, _("Save files from trusted devices without asking.")))
        box.pack_start(c, False, False, 0)

        self.in_title = section(_("Receiving"))
        box.pack_start(self.in_title, False, False, 0)
        self.in_list = card()
        box.pack_start(self.in_list, False, False, 0)

        hrow = Gtk.Box()
        hrow.pack_start(section(_("Recently received")), True, True, 0)
        folder = Gtk.Button(label=_("Open folder"), relief=Gtk.ReliefStyle.NONE, valign=Gtk.Align.END)
        folder.connect("clicked", lambda *_a: self.open_downloads())
        hrow.pack_end(folder, False, False, 0)
        box.pack_start(hrow, False, False, 0)
        self.hist_list = card()
        box.pack_start(self.hist_list, False, False, 0)
        return box

    def open_downloads(self):
        os.makedirs(self.settings.download_dir, exist_ok=True)
        open_path(self.settings.download_dir)

    def _set(self, key, value):
        if self._ui_lock:
            return
        self.settings.reload()
        self.settings.set(key, value)

    def on_ready(self, sw, _p):
        if self._ui_lock:
            return
        if sw.get_active():
            mode = self.settings["last_mode"]
            self.settings.set_mode(mode if mode in ("everyone", "trusted") else "everyone")
        else:
            self.settings.data["last_mode"] = self.settings.mode()
            self.settings.set_mode("off")
        self.refresh_receive()
        self.engine.sync()

    def on_who(self, combo):
        if self._ui_lock or not combo.get_active_id():
            return
        if self.settings.mode() != "off":
            self.settings.set_mode(combo.get_active_id())
        self.settings.data["last_mode"] = combo.get_active_id()
        self.settings.save()
        self.refresh_receive()

    def refresh_receive(self):
        self._ui_lock = True
        try:
            self.settings.reload()
            mode = self.settings.mode()
            self.ready.set_active(mode != "off")
            last = mode if mode != "off" else self.settings["last_mode"]
            self.who.set_active_id(last if last in ("everyone", "trusted") else "everyone")
            self.who.set_sensitive(mode != "off")
            self.quick.set_active(self.settings["auto_accept_trusted"])
            self.hero_name.set_text(self.settings.name)
            ips = local_ips()
            self.hero_sub.set_text("#%s%s" % (self.identity.id[:6], ("  ·  " + ", ".join(ips[:2])) if ips else ""))
            ctx = self.logo.get_style_context()
            (ctx.add_class if mode != "off" and self.engine.receiver else ctx.remove_class)("active")
            if not self.engine.receiver and not self.engine.ls_server:
                self.status.set_text(_("Not receiving"))
            elif mode == "off":
                self.status.set_text(_("Receiving is turned off. Other devices cannot see this computer."))
            else:
                left = self.settings.everyone_left()
                text = _("Visible to LuxOS computers and LocalSend apps nearby.")
                if left:
                    text += " " + _("%d:%02d left") % (left // 60, left % 60)
                self.status.set_text(text)
        finally:
            self._ui_lock = False

    def show_accept(self, req, done):
        self.present()  # nejdriv okno, dialog az nad nim
        dialogs.accept_dialog(req, done, parent=self)
        return False

    # --- Odeslat -------------------------------------------------------------

    def build_send(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.get_style_context().add_class("page")
        box.get_style_context().add_class("dropzone")
        self._make_drop_target(box, None)

        box.pack_start(section(_("Selection")), False, False, 0)
        picks = Gtk.Box(spacing=8, homogeneous=True)
        for icon, label, fn in (("text-x-generic-symbolic", _("File"), lambda: self.choose(False)),
                                ("folder-symbolic", _("Folder"), lambda: self.choose(True)),
                                ("insert-text-symbolic", _("Text"), self.enter_text),
                                ("edit-paste-symbolic", _("Paste"), self.paste)):
            b = Gtk.Button()
            b.get_style_context().add_class("pick")
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
            img.set_pixel_size(24)
            v.pack_start(img, False, False, 0)
            v.pack_start(Gtk.Label(label=label), False, False, 0)
            b.add(v)
            b.connect("clicked", lambda _b, f=fn: f())
            picks.pack_start(b, True, True, 0)
        box.pack_start(picks, False, False, 0)
        self.sel_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=6)
        box.pack_start(self.sel_box, False, False, 0)

        head = Gtk.Box(spacing=2)
        head.pack_start(section(_("Nearby devices")), True, True, 0)
        for icon, tip, fn in (("view-refresh-symbolic", _("Refresh"), self.on_refresh),
                              ("system-search-symbolic", _("Scan the local network"), self.on_scan),
                              ("list-add-symbolic", _("Connect by address…"), self.show_connect)):
            b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_valign(Gtk.Align.END)
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda _b, f=fn: f())
            head.pack_start(b, False, False, 0)
        box.pack_start(head, False, False, 0)
        self.dev_list = card()
        self.dev_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.dev_list.set_activate_on_single_click(True)
        self.dev_list.connect("row-activated", self.on_device_row)
        box.pack_start(self.dev_list, False, False, 0)
        self.scan_label = Gtk.Label(xalign=0, wrap=True, margin_top=4)
        self.scan_label.get_style_context().add_class("dim")
        self.scan_label.get_style_context().add_class("small")
        box.pack_start(self.scan_label, False, False, 0)

        self.out_title = section(_("Sending"))
        box.pack_start(self.out_title, False, False, 0)
        self.out_list = card()
        box.pack_start(self.out_list, False, False, 0)
        return box

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
            self.add_paths(paths)
        else:
            self.send_to(device, paths=paths)

    def choose(self, folders):
        dlg = Gtk.FileChooserNative.new(_("Choose folder") if folders else _("Choose files"), self,
                                        Gtk.FileChooserAction.SELECT_FOLDER if folders else Gtk.FileChooserAction.OPEN,
                                        _("Choose"), _("Cancel"))
        dlg.set_select_multiple(True)
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            self.add_paths([f.get_path() for f in dlg.get_files() if f.get_path()])
        dlg.destroy()

    def enter_text(self, initial=""):
        dlg = Gtk.Dialog(title=_("Text"), transient_for=self, modal=True)
        dlg.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Done"), Gtk.ResponseType.OK)
        dlg.set_default_size(400, 240)
        area = dlg.get_content_area()
        area.set_border_width(14)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.get_style_context().add_class("card")
        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=10, right_margin=10, top_margin=8,
                          bottom_margin=8)
        tv.get_buffer().set_text(initial or self.text or "")
        sw.add(tv)
        area.pack_start(sw, True, True, 0)
        dlg.show_all()
        if dlg.run() == Gtk.ResponseType.OK:
            b = tv.get_buffer()
            text = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
            if text.strip():
                self.set_text(text)
        dlg.destroy()

    def paste(self):
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        uris = cb.wait_for_uris()
        if uris:
            paths = []
            for u in uris:
                try:
                    paths.append(GLib.filename_from_uri(u)[0])
                except GLib.Error:
                    pass
            if paths:
                self.add_paths(paths)
                return
        text = cb.wait_for_text()
        if text and text.strip():
            self.set_text(text)
        else:
            self.show_info(_("The clipboard is empty."))

    def add_paths(self, paths):
        self.text = None
        self.selection += [p for p in paths if p not in self.selection and os.path.lexists(p)]
        self.refresh_selection()
        self.show_page("send")

    def set_text(self, text):
        self.selection = []
        self.text = text
        self.refresh_selection()

    def clear_selection(self):
        self.selection, self.text = [], None
        self.refresh_selection()

    def refresh_selection(self):
        for c in self.sel_box.get_children():
            self.sel_box.remove(c)
        if self.text is not None:
            items = [("insert-text-symbolic", self.text.strip().splitlines()[0][:60] if self.text.strip() else "",
                      _("%d characters") % len(self.text), None)]
        else:
            items = [("folder-symbolic" if os.path.isdir(p) else "text-x-generic-symbolic",
                      os.path.basename(p.rstrip("/")) or p, human(quick_size(p)), p) for p in self.selection]
        for icon, name, sub, path in items[:6]:
            chip = Gtk.Box(spacing=8)
            chip.get_style_context().add_class("chip")
            chip.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
            chip.pack_start(Gtk.Label(label=name, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE), True, True, 0)
            s = Gtk.Label(label=sub)
            s.get_style_context().add_class("dim")
            chip.pack_start(s, False, False, 0)
            x = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
            x.set_relief(Gtk.ReliefStyle.NONE)
            x.connect("clicked", lambda _b, p=path: self.remove_item(p))
            chip.pack_start(x, False, False, 0)
            self.sel_box.pack_start(chip, False, False, 0)
        if len(items) > 6:
            more = Gtk.Label(label=_("and %d more") % (len(items) - 6), xalign=0)
            more.get_style_context().add_class("dim")
            self.sel_box.pack_start(more, False, False, 0)
        if not items:
            hint = Gtk.Label(label=_("Choose what to send or drop files here, then tap a device."), xalign=0,
                             wrap=True)
            hint.get_style_context().add_class("dim")
            self.sel_box.pack_start(hint, False, False, 0)
        self.sel_box.show_all()

    def remove_item(self, path):
        if path is None:
            self.text = None
        else:
            self.selection = [p for p in self.selection if p != path]
        self.refresh_selection()

    # --- Zarizeni -------------------------------------------------------------

    def start_engine(self):
        if not os.environ.get("LUXDROP_NO_SYSTEMD"):
            try:
                if subprocess.run(["systemctl", "--user", "is-active", "--quiet", SERVICE], timeout=5).returncode == 0:
                    subprocess.run(["systemctl", "--user", "stop", SERVICE], timeout=15)
                    self.stopped_service = True
            except (OSError, subprocess.SubprocessError):
                pass
        self.engine = Engine(self.identity, self.settings, self.trust, self.history, GuiHandler(self),
                             on_change=self.devices_changed,
                             bind=os.environ.get("LUXDROP_BIND", ""),
                             ls_port=int(os.environ["LUXDROP_LS_PORT"]) if os.environ.get("LUXDROP_LS_PORT") else None)
        self.engine.start()
        for a in filter(None, os.environ.get("LUXDROP_PEERS", "").split(",")):
            d = self.engine.add_manual(a)
            self.manual[d["key"]] = d
        msgs = []
        for kind, port, err in self.engine.errors:
            if kind == "luxdrop_port":
                msgs.append(_("Cannot receive from LuxOS computers: port %d is in use (%s).") % (port, err))
            elif kind == "localsend_port":
                msgs.append(_("Cannot receive from LocalSend apps: port %d is in use. Is LocalSend running "
                              "on this computer?") % port)
            elif kind == "localsend_missing":
                msgs.append(_("LocalSend compatibility needs the python-pyopenssl package."))
            elif kind == "avahi":
                msgs.append(_("Nearby LuxOS computers cannot be found because Avahi is not running."))
            elif kind == "multicast":
                msgs.append(_("Automatic discovery of LocalSend devices is not available (%s). "
                              "Use “Scan the local network”.") % err)
        if msgs:
            self.show_info("\n".join(msgs))

    def devices(self):
        devs = {d["key"]: d for d in self.engine.devices()}
        for k, d in self.manual.items():
            devs.setdefault(k, d)
        return sorted(devs.values(), key=lambda d: (not d["trusted"], not d.get("secure", True), d["name"].lower()))

    def devices_changed(self):
        """Z libovolneho vlakna; davky zmen (multicast chodi vicekrat) se slouci."""
        if not self._refresh_pending:
            self._refresh_pending = True
            GLib.timeout_add(250, self.refresh_devices)

    def refresh_devices(self):
        self._refresh_pending = False
        for c in self.dev_list.get_children():
            self.dev_list.remove(c)
        devs = self.devices()
        for d in devs:
            self.dev_list.add(self.device_row(d))
        if not devs:
            lab = Gtk.Label(label=_("Looking for devices… Open LuxDrop or LocalSend on the other device and "
                                    "make sure it is on the same network."), wrap=True,
                            justify=Gtk.Justification.CENTER)
            lab.get_style_context().add_class("empty")
            r = Gtk.ListBoxRow(activatable=False, selectable=False)
            r.add(lab)
            self.dev_list.add(r)
        self.dev_list.show_all()
        return False

    def device_row(self, d):
        r = Gtk.ListBoxRow()
        r.device = d
        h = Gtk.Box(spacing=12)
        r.add(h)
        secure = d.get("secure", True)
        h.pack_start(device_icon(d.get("device_type", "desktop"), 24, luxos=d["kind"] == "luxdrop",
                                 off=not secure), False, False, 0)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, spacing=2)
        top = Gtk.Box(spacing=6)
        name = Gtk.Label(label=d["name"], xalign=0, ellipsize=Pango.EllipsizeMode.END)
        name.get_style_context().add_class("dev-name")
        top.pack_start(name, False, False, 0)
        if d["trusted"]:
            b = Gtk.Label(label=_("Trusted"))
            b.get_style_context().add_class("badge")
            top.pack_start(b, False, False, 0)
        if not secure:
            b = Gtk.Label(label=_("Unencrypted"))
            b.get_style_context().add_class("badge")
            b.get_style_context().add_class("warn")
            top.pack_start(b, False, False, 0)
        v.pack_start(top, False, False, 0)
        sub = Gtk.Label(label=kind_label(d["kind"], d.get("device_type", "desktop"), d.get("device_model", ""))
                        if not d.get("manual") else transfer.fmt_addr(d["host"], d["port"]), xalign=0,
                        ellipsize=Pango.EllipsizeMode.END)
        sub.get_style_context().add_class("dim")
        sub.get_style_context().add_class("small")
        v.pack_start(sub, False, False, 0)
        h.pack_start(v, True, True, 0)
        h.pack_end(Gtk.Image.new_from_icon_name("go-next-symbolic", Gtk.IconSize.MENU), False, False, 0)
        tip = "%s\n%s" % (d["name"], transfer.fmt_addr(d["host"], d["port"]))
        if not secure:
            tip += "\n" + _("This LocalSend device has encryption turned off. Turn on “Encryption” in "
                            "LocalSend settings to send files to it.")
        r.set_tooltip_text(tip)
        r.set_sensitive(secure)
        self._make_drop_target(r, d)
        return r

    def on_device_row(self, _lb, r):
        d = getattr(r, "device", None)
        if d is not None:
            self.send_to(d)

    def on_refresh(self):
        self.engine.refresh()
        self.refresh_devices()

    def on_scan(self):
        def done():
            GLib.idle_add(lambda: (self.scan_label.set_text(""), self.refresh_devices(), False)[2])
        if self.engine.scan(done=done):
            self.scan_label.set_text(_("Scanning the local network for LocalSend devices…"))

    def show_connect(self):
        dlg = Gtk.Dialog(title=_("Connect by address"), transient_for=self, modal=True)
        dlg.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Add"), Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        area = dlg.get_content_area()
        area.set_spacing(8)
        area.set_border_width(16)
        area.pack_start(Gtk.Label(label=_("IP address of the other device, e.g. 192.168.1.20"), xalign=0, wrap=True),
                        False, False, 0)
        entry = Gtk.Entry(activates_default=True)
        area.pack_start(entry, False, False, 0)
        ls = Gtk.RadioButton.new_with_label(None, _("LocalSend app (port %d)") % 53317)
        lux = Gtk.RadioButton.new_with_label_from_widget(ls, _("LuxOS computer (port %d)") % proto.DEFAULT_PORT)
        area.pack_start(ls, False, False, 0)
        area.pack_start(lux, False, False, 0)
        dlg.show_all()
        if dlg.run() == Gtk.ResponseType.OK and entry.get_text().strip():
            text = entry.get_text().strip()
            try:
                d = self.engine.add_manual(text, localsend_proto=ls.get_active())
            except ValueError:
                d = None
            if d is None:
                self.show_info(_("No device answers at %s.") % text)
            else:
                if d.get("manual"):
                    self.manual[d["key"]] = d
                self.refresh_devices()
        dlg.destroy()

    # --- Odesilani -------------------------------------------------------------

    def send_to(self, device, paths=None):
        paths = paths or list(self.selection)
        text = self.text if not paths else None
        if not paths and text is None:
            self.choose(False)
            paths = list(self.selection)
            if not paths:
                return
        t = self.engine.send_async(device, GuiSend(self), paths=paths or None, text=text,
                                   done=lambda tr: GLib.idle_add(self.transfer_finished, tr))
        self.add_transfer_row(t)
        self.clear_selection()

    # --- Prubeh prenosu -------------------------------------------------------

    def add_transfer_row(self, t):
        if t.id in self.rows:
            return self.rows[t.id]
        r = Gtk.ListBoxRow(activatable=False)
        v0 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        r.add(v0)
        h = Gtk.Box(spacing=10)
        v0.pack_start(h, False, False, 0)
        h.pack_start(device_icon(t.device_type, 18, luxos=t.protocol == "luxdrop"), False, False, 0)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        h.pack_start(v, True, True, 0)
        title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        v.pack_start(title, False, False, 0)
        bar = Gtk.ProgressBar()
        v.pack_start(bar, False, False, 0)
        status = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        status.get_style_context().add_class("dim")
        status.get_style_context().add_class("small")
        v.pack_start(status, False, False, 0)
        btn = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON)
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_valign(Gtk.Align.CENTER)
        btn.set_tooltip_text(_("Cancel"))
        btn.connect("clicked", lambda *_a: self.cancel_or_remove(t))
        h.pack_end(btn, False, False, 0)
        exp = Gtk.Expander(label=_("Files"))
        exp.get_style_context().add_class("small")
        files_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_start=36)
        exp.add(files_box)
        v0.pack_start(exp, False, False, 0)
        lst = self.out_list if t.direction == "out" else self.in_list
        lst.add(r)
        r.show_all()
        self.rows[t.id] = {"row": r, "title": title, "bar": bar, "status": status, "btn": btn, "exp": exp,
                           "files": files_box, "file_rows": [], "list": lst}
        self.refresh_transfers_visibility()
        self.update_transfer(t)
        return self.rows[t.id]

    def cancel_or_remove(self, t):
        if t.state in FINAL:
            w = self.rows.pop(t.id)
            w["list"].remove(w["row"])
            self.refresh_transfers_visibility()
        else:
            t.cancel()

    def _update_files(self, w, t):
        files = t.files[:100]
        if not files:
            w["exp"].hide()
            return
        w["exp"].show()
        w["exp"].set_label(_("Files (%d)") % len(t.files))
        if len(w["file_rows"]) != len(files):
            for c in w["files"].get_children():
                w["files"].remove(c)
            w["file_rows"] = []
            for f in files:
                h = Gtk.Box(spacing=8)
                n = Gtk.Label(label=f["name"], xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
                n.get_style_context().add_class("small")
                h.pack_start(n, True, True, 0)
                b = Gtk.ProgressBar(valign=Gtk.Align.CENTER)
                b.set_size_request(90, -1)
                h.pack_end(b, False, False, 0)
                w["files"].pack_start(h, False, False, 0)
                w["file_rows"].append(b)
            w["files"].show_all()
        for f, b in zip(files, w["file_rows"]):
            if t.state == "done" or (not f["size"] and f["state"] == "done"):
                b.set_fraction(1.0)
            else:
                b.set_fraction(min(1.0, f["done"] / f["size"]) if f["size"] else 0.0)
            b.set_tooltip_text("%s / %s · %s" % (human(f["done"]), human(f["size"]), f["state"]))

    def update_transfer(self, t):
        if t.direction == "in" and t.id not in self.rows:
            if not t.items or t.state in ("waiting", "connecting"):
                return False
            self.add_transfer_row(t)
        if t.id not in self.rows:
            return False
        w = self.rows[t.id]
        items = ", ".join(t.items[:3]) + ("…" if len(t.items) > 3 else "")
        if t.direction == "out":
            w["title"].set_text(_("To %s: %s") % (t.peer_name or "…", items or "…"))
        else:
            w["title"].set_text(_("From %s: %s") % (t.peer_name, items))
        w["bar"].set_fraction(min(1.0, t.fraction()))
        w["bar"].set_visible(t.state in ("preparing", "transferring", "done") or t.done > 0)
        st = {
            "preparing": _("Preparing (checksums)… %s / %s") % (human(t.done), human(t.total)),
            "connecting": _("Connecting…"),
            "waiting": (_("Waiting for the receiver to accept… code %s") % proto.format_sas(t.sas))
            if t.sas else _("Waiting for the receiver to accept…"),
            "transferring": "%s / %s" % (human(t.done), human(t.total)),
            "done": _("Done"),
            "declined": _("Declined"),
            "cancelled": _("Cancelled"),
            "failed": _("Failed: %s") % t.error,
        }.get(t.state, t.state)
        w["status"].set_text(st)
        w["status"].set_tooltip_text(st)
        self._update_files(w, t)
        return False

    def transfer_finished(self, t):
        if t.direction == "in" and t.id not in self.rows and t.state in ("done", "failed") and t.items:
            self.add_transfer_row(t)
        self.update_transfer(t)
        if t.id in self.rows:
            self.rows[t.id]["btn"].set_tooltip_text(_("Remove"))
        if t.direction == "in":
            self.refresh_history()
            if t.state == "done" and t.saved:
                self.notify_received(t)
        self.refresh_devices()
        if t.code == proto.E_KEY_MISMATCH:
            self.show_info(_("“%s” presented a different key than expected. Nothing was sent – someone may be "
                             "impersonating it. If it was reinstalled, remove it in Settings and try again.")
                           % (t.peer_name or t.peer_id))
        return False

    def notify_received(self, t):
        if self.is_active():
            return
        n = Gio.Notification.new(_("Received from %s") % t.peer_name)
        n.set_body(", ".join(os.path.basename(p) for p in t.saved[:5]))
        self.app.send_notification("received", n)

    def refresh_transfers_visibility(self):
        has_in = any(w["list"] is self.in_list for w in self.rows.values())
        has_out = any(w["list"] is self.out_list for w in self.rows.values())
        self.in_title.set_visible(has_in)
        self.in_list.set_visible(has_in)
        self.out_title.set_visible(has_out)
        self.out_list.set_visible(has_out)

    def refresh_history(self):
        for c in self.hist_list.get_children():
            self.hist_list.remove(c)
        items = [e for e in self.history.items() if e.get("direction") == "in" and e.get("state") == "done"][:8]
        if not items:
            lab = Gtk.Label(label=_("Nothing received yet."))
            lab.get_style_context().add_class("empty")
            self.hist_list.add(lab)
        for e in items:
            r = Gtk.ListBoxRow(activatable=False)
            h = Gtk.Box(spacing=10)
            r.add(h)
            h.pack_start(device_icon(e.get("device_type", "desktop"), 16, luxos=e.get("protocol") != "localsend"),
                         False, False, 0)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            h.pack_start(v, True, True, 0)
            names = ", ".join(os.path.basename(p) for p in e.get("saved", [])[:3]) or ", ".join(e.get("items", [])[:3])
            v.pack_start(Gtk.Label(label=names, xalign=0, ellipsize=Pango.EllipsizeMode.END), False, False, 0)
            sub = Gtk.Label(label="%s · %s · %s" % (e.get("peer", "?"), human(e.get("total", 0)),
                                                    time.strftime("%d.%m. %H:%M", time.localtime(e.get("time", 0)))),
                            xalign=0, ellipsize=Pango.EllipsizeMode.END)
            sub.get_style_context().add_class("dim")
            sub.get_style_context().add_class("small")
            v.pack_start(sub, False, False, 0)
            saved = e.get("saved", [])
            b = Gtk.Button.new_from_icon_name("folder-open-symbolic", Gtk.IconSize.BUTTON)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_tooltip_text(_("Show in folder"))
            b.connect("clicked", lambda _b, s=saved: open_path(os.path.dirname(s[0]) if s else
                                                               self.settings.download_dir))
            h.pack_end(b, False, False, 0)
            self.hist_list.add(r)
        self.hist_list.show_all()

    # --- Nastaveni -------------------------------------------------------------

    def build_settings(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.get_style_context().add_class("page")
        box.pack_start(section(_("This computer")), False, False, 0)
        c = card()
        self.name_entry = Gtk.Entry(text=self.settings.name, max_length=63, width_chars=22)
        self.name_entry.connect("changed", lambda e: self._set_name(e.get_text()))
        c.add(row(_("Device name"), self.name_entry))
        self.folder = Gtk.FileChooserButton(action=Gtk.FileChooserAction.SELECT_FOLDER, width_chars=16)
        try:
            os.makedirs(self.settings.download_dir, exist_ok=True)
        except OSError:
            pass
        self.folder.set_filename(self.settings.download_dir)
        self.folder.connect("file-set", lambda b: b.get_filename() and self._set("download_dir", b.get_filename()))
        c.add(row(_("Save to"), self.folder))
        self.bg = Gtk.Switch(active=self.settings["background"])
        self.bg.connect("notify::active", self.on_background)
        c.add(row(_("Receive when LuxDrop is closed"), self.bg, _("Requests then appear as notifications.")))
        box.pack_start(c, False, False, 0)

        box.pack_start(section(_("LocalSend")), False, False, 0)
        c = card()
        self.ls_switch = Gtk.Switch(active=self.settings["localsend"])
        self.ls_switch.connect("notify::active", self.on_localsend)
        c.add(row(_("Work with LocalSend apps"), self.ls_switch,
                  _("Phones, tablets and computers with the LocalSend app. Uses port 53317.")))
        self.pin_entry = Gtk.Entry(text=self.settings.pin, max_length=32, width_chars=10, visibility=False,
                                   placeholder_text=_("No PIN"))
        self.pin_entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-reveal-symbolic")
        self.pin_entry.connect("icon-press", lambda e, *_a: e.set_visibility(not e.get_visibility()))
        self.pin_entry.connect("changed", lambda e: self._set("pin", e.get_text().strip()))
        c.add(row(_("PIN"), self.pin_entry, _("LocalSend devices must enter this PIN before they can send.")))
        box.pack_start(c, False, False, 0)

        box.pack_start(section(_("Trusted devices")), False, False, 0)
        self.tlist = card()
        box.pack_start(self.tlist, False, False, 0)
        note = Gtk.Label(label=_("Trusted devices can use Quick save. Remove a device if it was lost or "
                                 "reinstalled."), xalign=0, wrap=True, max_width_chars=60, margin_top=4)
        note.get_style_context().add_class("dim")
        note.get_style_context().add_class("small")
        box.pack_start(note, False, False, 0)

        box.pack_start(section(_("Security")), False, False, 0)
        fp_text = _("Key fingerprint: %s") % proto.format_fp(self.identity.fp)
        fp = Gtk.Label(label="ID %s\n%s" % (self.identity.id, fp_text), xalign=0, selectable=True, wrap=True,
                       max_width_chars=50)
        fp.get_style_context().add_class("dim")
        fp.get_style_context().add_class("small")
        box.pack_start(fp, False, False, 0)
        sec = Gtk.Label(label=_("All transfers are encrypted (TLS). LuxOS computers verify each other with a "
                                "6-digit code; LocalSend devices are identified by their certificate."),
                        xalign=0, wrap=True, max_width_chars=60, margin_top=4)
        sec.get_style_context().add_class("dim")
        sec.get_style_context().add_class("small")
        box.pack_start(sec, False, False, 0)
        return box

    def _set_name(self, text):
        self._set("name", text.strip())
        self._name_changed = time.monotonic()

    def on_background(self, sw, _p):
        self._set("background", sw.get_active())
        if not os.environ.get("LUXDROP_NO_SYSTEMD"):
            # Sluzbu jen zapneme/vypneme; spusti se az po zavreni okna (porty drzi okno)
            try:
                subprocess.Popen(["systemctl", "--user", "enable" if sw.get_active() else "disable", SERVICE])
            except OSError:
                pass

    def on_localsend(self, sw, _p):
        self._set("localsend", sw.get_active())
        if sw.get_active():
            self.engine.start_localsend()
            self.engine.sync(force=True)
        elif self.engine.ls_server:
            self.engine.ls_server.stop()
            self.engine.ls_server = None
            if self.engine.lsd:
                self.engine.lsd.stop()
                self.engine.lsd = None
        self.refresh_devices()

    def fill_trusted(self):
        for c in self.tlist.get_children():
            self.tlist.remove(c)
        self.trust.reload()
        peers = sorted(self.trust.peers.items(), key=lambda kv: kv[1].get("name", "").lower())
        if not peers:
            lab = Gtk.Label(label=_("No trusted devices yet."))
            lab.get_style_context().add_class("empty")
            self.tlist.add(lab)
        for fp_hex, e in peers:
            r = Gtk.ListBoxRow(activatable=False)
            h = Gtk.Box(spacing=10)
            r.add(h)
            ls = e.get("kind") == "localsend"
            h.pack_start(device_icon(e.get("device_type", "desktop"), 16, luxos=not ls), False, False, 0)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            v.pack_start(Gtk.Label(label=e.get("name", "?"), xalign=0), False, False, 0)
            sub = Gtk.Label(label=("LocalSend" if ls else "LuxOS") + " · ID " + e.get("id", fp_hex[:16]), xalign=0)
            sub.get_style_context().add_class("dim")
            sub.get_style_context().add_class("small")
            v.pack_start(sub, False, False, 0)
            r.set_tooltip_text(proto.format_fp(bytes.fromhex(fp_hex)))
            h.pack_start(v, True, True, 0)
            b = Gtk.Button(label=_("Remove"), valign=Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, k=fp_hex: (self.trust.remove(k), self.fill_trusted(),
                                                        self.refresh_devices()))
            h.pack_end(b, False, False, 0)
            self.tlist.add(r)
        self.tlist.show_all()

    # --- Ostatni ---------------------------------------------------------------

    def tick(self):
        self.settings.reload()
        self.engine.sync()
        if self.stack.get_visible_child_name() == "receive":
            self.refresh_receive()
        return True

    def show_info(self, text):
        self.info_label.set_text(text)
        self.info.set_no_show_all(False)
        self.info.show_all()

    def on_destroy(self, *_a):
        self.engine.stop()
        if not os.environ.get("LUXDROP_NO_SYSTEMD") and self.settings["background"]:
            try:
                subprocess.Popen(["systemctl", "--user", "start", SERVICE])
            except OSError:
                pass


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
            self.win.refresh_receive()
            self.win.refresh_devices()
            self.win.refresh_selection()
            self.win.refresh_history()
            self.win.refresh_transfers_visibility()
            page = os.environ.get("LUXDROP_PAGE")
            if page in self.win.nav:
                self.win.show_page(page)
        self.win.present()

    def do_open(self, files, _n, _hint):
        self.do_activate()
        paths = [f.get_path() for f in files if f.get_path()]
        self.win.add_paths(paths)


def main(argv):
    GLib.set_prgname("luxdrop")
    GLib.set_application_name("LuxDrop")
    app = App()
    return app.run(["luxdrop"] + list(argv))

