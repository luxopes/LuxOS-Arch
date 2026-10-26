"""LuxDrop - okna pro soubory jineho pocitace: dotaz na pristup (sdilejici pocitac) a Pripojit k pocitaci."""
import os
import signal
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import proto, remote, transfer  # noqa: E402
from .cli import Ctx, _  # noqa: E402
from .dialogs import device_icon, load_css, sas_widget  # noqa: E402


def _small(text, warn=False):
    lab = Gtk.Label(label=text, xalign=0, wrap=True, max_width_chars=48)
    lab.get_style_context().add_class("warn" if warn else "dim")
    return lab


# --- Sdilejici pocitac: dotaz -------------------------------------------------------

def access_dialog(req, on_done):
    """Povolit jednou / Vzdy povolit / Odmitnout; on_done((rozhodnuti, zapis)) prave jednou."""
    load_css()
    dlg = Gtk.Dialog(title=_("Access to shared folders"), modal=False)
    dlg.set_icon_name("luxdrop")
    dlg.set_keep_above(True)
    dlg.set_urgency_hint(True)
    dlg.set_default_size(440, -1)
    dlg.add_buttons(_("Deny"), Gtk.ResponseType.CANCEL, _("Allow once"), 1, _("Always allow"), 2)
    dlg.set_default_response(Gtk.ResponseType.CANCEL)
    area = dlg.get_content_area()
    area.set_spacing(10)
    area.set_border_width(18)
    head = Gtk.Box(spacing=12)
    head.pack_start(device_icon("desktop", 30, luxos=True), False, False, 0)
    t = Gtk.Label(xalign=0, wrap=True, max_width_chars=44)
    title = (_("“%s” wants to access and change your shared folders") if req.want_write
             else _("“%s” wants to access your shared folders")) % req.peer_name
    t.set_markup("<b>%s</b>\n<small>%s</small>" % (GLib.markup_escape_text(title),
                                                    GLib.markup_escape_text("LuxOS · ID %s" % req.peer_id)))
    head.pack_start(t, True, True, 0)
    area.pack_start(head, False, False, 0)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.get_style_context().add_class("card")
    for n in req.shares[:6]:
        lab = Gtk.Label(label=n, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=48)
        lab.get_style_context().add_class("row")
        box.pack_start(lab, False, False, 0)
    if len(req.shares) > 6:
        more = Gtk.Label(label=_("and %d more") % (len(req.shares) - 6), xalign=0)
        more.get_style_context().add_class("row")
        box.pack_start(more, False, False, 0)
    area.pack_start(box, False, False, 0)
    if req.name_clash:
        area.pack_start(_small(_("Warning: this device uses the name of a trusted device, but its key is "
                                 "different. It may be someone else."), warn=True), False, False, 0)
    if req.sas:
        area.pack_start(Gtk.Label(label=_("Verification code"), xalign=0), False, False, 0)
        area.pack_start(sas_widget(req.sas), False, False, 0)
        area.pack_start(Gtk.Label(label=_("Allow only if the other computer shows the same code."), xalign=0,
                                  wrap=True, max_width_chars=48), False, False, 0)
    write_cb = None
    if req.want_write:
        write_cb = Gtk.CheckButton(label=_("Also allow changes (copy in, rename and delete files)"), active=False)
        area.pack_start(write_cb, False, False, 0)
    else:
        area.pack_start(_small(_("Read-only: the other computer can open and copy your shared files, "
                                 "but cannot change them.")), False, False, 0)
    dlg.show_all()
    dlg.present()
    state = {"done": False}

    def watch():
        if req.withdrawn.is_set() and not state["done"]:
            dlg.response(Gtk.ResponseType.DELETE_EVENT)
            return False
        return not state["done"]

    GLib.timeout_add(300, watch)

    def on_response(d, r):
        if not state["done"]:
            state["done"] = True
            decision = {1: "once", 2: "always"}.get(r, "deny")
            on_done((decision, bool(write_cb and write_cb.get_active())))
        d.destroy()

    dlg.connect("response", on_response)
    return dlg


class ServiceAsker:
    """Dotaz ze sluzby na pozadi: dialog (je-li displej) a oznameni; bez obojiho se odmita."""

    def __init__(self, notifier, use_gtk):
        self.n = notifier
        self.use_gtk = use_gtk

    def __call__(self, req):
        ev, box, ui = threading.Event(), {}, {}

        def answer(v):
            if "v" in box:
                return
            box["v"] = v
            ev.set()

            def cleanup():
                if ui.get("nid") is not None and self.n is not None:
                    self.n.waiting.pop(ui["nid"], None)
                    self.n.close(ui["nid"])
                return False
            GLib.idle_add(cleanup)

        def show():
            esc = GLib.markup_escape_text
            summary = _("LuxDrop: access to shared folders")
            body = esc(_("“%s” wants to access your shared folders") % req.peer_name)
            if req.sas:
                body += "\n" + esc(_("Verification code: %s") % proto.format_sas(req.sas))
            if self.use_gtk:
                ui["dlg"] = access_dialog(req, answer)
            if self.n is not None:
                actions = [] if self.use_gtk else ["deny", _("Deny"), "once", _("Allow once"),
                                                   "always", _("Always allow")]
                try:
                    nid = self.n.notify(summary, body, actions, 0 if actions else -1, True)
                    ui["nid"] = nid
                    if actions:
                        # Z oznameni jen cteni (zapis jen v dialogu se zaskrtnutim)
                        self.n.waiting[nid] = lambda key: answer((key if key in ("once", "always") else "deny",
                                                                  False))
                except GLib.Error:
                    if not self.use_gtk:
                        answer(("deny", False))
            elif not self.use_gtk:
                answer(("deny", False))
            return False

        GLib.idle_add(show)
        while not ev.wait(0.5):
            if req.withdrawn.is_set():
                answer(("deny", False))  # dialog se zavre sam (sleduje req.withdrawn)
        return box["v"]


# --- Pripojit k pocitaci --------------------------------------------------------------

class GuiConnect(remote.ConnectCallbacks):
    def __init__(self, win):
        self.win = win

    def status(self, state, info):
        GLib.idle_add(self.win.on_status, state, info)

    def confirm(self, info, replied):
        ev, box = threading.Event(), {}
        GLib.idle_add(self.win.ask_code, info, replied, lambda v: (box.setdefault("v", v), ev.set()))
        ev.wait()
        return box["v"]


class ConnectWindow(Gtk.Window):
    def __init__(self, want_write=False):
        super().__init__(title=_("Connect to Computer"))
        load_css()
        self.ctx = Ctx()
        self.set_icon_name("luxdrop")
        self.set_default_size(460, 520)
        self.mounts = []
        self.cancel = None
        self.busy = False
        self.disc = None
        self.notifier = None
        try:
            from .service import Notifier
            self.notifier = Notifier()
        except (GLib.Error, ImportError):
            pass

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.get_style_context().add_class("page")
        self.add(outer)
        intro = Gtk.Label(xalign=0, wrap=True, max_width_chars=56)
        intro.set_markup("<b>%s</b>" % GLib.markup_escape_text(_("Open the files of another LuxOS computer "
                                                                 "next to yours")))
        outer.pack_start(intro, False, False, 0)
        hint = _small(_("The other computer must share folders (LuxDrop › Settings › Share folders) and "
                        "allow your access."))
        outer.pack_start(hint, False, False, 0)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        outer.pack_start(self.stack, True, True, 0)

        # Stranka 1: seznam pocitacu
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        lab = Gtk.Label(label=_("Computers nearby"), xalign=0)
        lab.get_style_context().add_class("section-title")
        page.pack_start(lab, False, False, 0)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.get_style_context().add_class("card")
        self.list.connect("row-activated", lambda _l, r: self.start_connect(r.device))
        sw.add(self.list)
        page.pack_start(sw, True, True, 0)
        addr = Gtk.Box(spacing=6)
        self.addr = Gtk.Entry(placeholder_text=_("Address, e.g. 192.168.1.20"), activates_default=False)
        self.addr.connect("activate", lambda _e: self.on_addr())
        addr.pack_start(self.addr, True, True, 0)
        b = Gtk.Button(label=_("Connect"))
        b.connect("clicked", lambda _b: self.on_addr())
        addr.pack_start(b, False, False, 0)
        page.pack_start(addr, False, False, 0)
        self.write_cb = Gtk.CheckButton(label=_("Ask for permission to change files"), active=want_write)
        page.pack_start(self.write_cb, False, False, 0)
        lab = Gtk.Label(label=_("Connected"), xalign=0)
        lab.get_style_context().add_class("section-title")
        self.conn_title = lab
        page.pack_start(lab, False, False, 0)
        self.conn_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.conn_list.get_style_context().add_class("card")
        page.pack_start(self.conn_list, False, False, 0)
        self.stack.add_named(page, "list")

        # Stranka 2: prubeh spojeni
        prog = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
        self.spinner = Gtk.Spinner()
        prog.pack_start(self.spinner, False, False, 0)
        self.status = Gtk.Label(wrap=True, max_width_chars=48, justify=Gtk.Justification.CENTER)
        prog.pack_start(self.status, False, False, 0)
        self.code_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        prog.pack_start(self.code_box, False, False, 0)
        btns = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        self.match_btn = Gtk.Button(label=_("Codes match"))
        self.match_btn.get_style_context().add_class("suggested-action")
        btns.pack_start(self.match_btn, False, False, 0)
        self.cancel_btn = Gtk.Button(label=_("Cancel"))
        self.cancel_btn.connect("clicked", lambda _b: self.on_cancel())
        btns.pack_start(self.cancel_btn, False, False, 0)
        prog.pack_start(btns, False, False, 0)
        self.stack.add_named(prog, "progress")
        self.match_btn.connect("clicked", lambda _b: self._code_answer(True))
        self._code_cb = None

        self.info = Gtk.Label(xalign=0, wrap=True, max_width_chars=56)
        self.info.get_style_context().add_class("warn")
        outer.pack_start(self.info, False, False, 0)
        self.connect("delete-event", self.on_close)
        self.devices = {}
        self.start_discovery()
        self.refresh()
        GLib.timeout_add_seconds(1, self.tick)

    # --- Seznam ---------------------------------------------------------------

    def start_discovery(self):
        try:
            from .discovery import Discovery
            self.disc = Discovery(on_change=lambda: GLib.idle_add(self.refresh), service_type=remote.SERVICE_TYPE)
            if not self.disc.browse():
                self.info.set_text(_("Nearby LuxOS computers cannot be found because Avahi is not running.")
                                   + " " + _("Enter the address of the other computer."))
        except (ImportError, GLib.Error):
            self.disc = None

    def refresh(self):
        for c in self.list.get_children():
            self.list.remove(c)
        devs = self.disc.devices(self.ctx.identity.id) if self.disc else []
        if not devs:
            r = Gtk.ListBoxRow(activatable=False)
            lab = Gtk.Label(label=_("Looking for computers… On the other computer turn on LuxDrop › Settings › "
                                    "Share folders."), wrap=True, max_width_chars=48)
            lab.get_style_context().add_class("empty")
            r.add(lab)
            self.list.add(r)
        for d in devs:
            r = Gtk.ListBoxRow()
            r.device = d
            h = Gtk.Box(spacing=10)
            r.add(h)
            h.pack_start(device_icon("desktop", 20, luxos=True), False, False, 0)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            n = Gtk.Label(label=d["name"], xalign=0, ellipsize=Pango.EllipsizeMode.END)
            n.get_style_context().add_class("dev-name")
            v.pack_start(n, False, False, 0)
            v.pack_start(_small("ID %s · %s" % (d["id"], transfer.fmt_addr(d["host"], d["port"]))), False, False, 0)
            h.pack_start(v, True, True, 0)
            if any(e.get("id") == d["id"] for e in self.ctx.trust.peers.values()):
                b = Gtk.Label(label=_("Trusted"))
                b.get_style_context().add_class("badge")
                h.pack_end(b, False, False, 0)
            self.list.add(r)
        self.list.show_all()
        self.refresh_connections()
        return False

    def refresh_connections(self):
        for c in self.conn_list.get_children():
            self.conn_list.remove(c)
        items = remote.connections()
        for e in items:
            r = Gtk.ListBoxRow(activatable=False)
            h = Gtk.Box(spacing=10)
            r.add(h)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            v.pack_start(Gtk.Label(label=e.get("peer") or e["name"], xalign=0), False, False, 0)
            v.pack_start(_small(_("Can change files") if e.get("write") else _("Read-only")), False, False, 0)
            h.pack_start(v, True, True, 0)
            ob = Gtk.Button(label=_("Open"))
            ob.connect("clicked", lambda _b, p=e["path"]: threading.Thread(
                target=remote.open_side_by_side, args=(p,), daemon=True).start())
            h.pack_end(ob, False, False, 0)
            db = Gtk.Button(label=_("Disconnect"))
            db.connect("clicked", lambda _b, k=e["name"]: (self.disconnect(k), self.refresh_connections()))
            h.pack_end(db, False, False, 0)
            self.conn_list.add(r)
        self.conn_list.show_all()
        visible = bool(items)
        self.conn_title.set_visible(visible)
        self.conn_list.set_visible(visible)

    def disconnect(self, name):
        for m in list(self.mounts):
            if m.path and os.path.basename(m.path) == name:
                threading.Thread(target=m.close, daemon=True).start()
                return
        remote.disconnect(name)

    def on_addr(self):
        text = self.addr.get_text().strip()
        if not text:
            return
        try:
            host, port = transfer.parse_addr(text, remote.FILES_PORT)
        except ValueError:
            self.info.set_text(_("Invalid address."))
            return
        self.start_connect({"name": text, "host": host, "port": port, "id": ""})

    # --- Spojeni ---------------------------------------------------------------

    def start_connect(self, d):
        if self.busy or d is None:
            return
        self.busy = True
        self.info.set_text("")
        expected = None
        for fp_hex, e in self.ctx.trust.peers.items():
            if d.get("id") and e.get("id") == d["id"]:
                expected = bytes.fromhex(fp_hex)
        self.cancel = threading.Event()
        self.code_box.foreach(self.code_box.remove)
        self.match_btn.hide()
        self.status.set_text(_("Connecting to %s…") % d["name"])
        self.spinner.start()
        self.stack.set_visible_child_name("progress")
        want_write = self.write_cb.get_active()
        cancel = self.cancel

        def run():
            try:
                conn = remote.connect(self.ctx.identity, self.ctx.settings, self.ctx.trust, d["host"], d["port"],
                                      want_write, GuiConnect(self), expected_fp=expected, cancel=cancel)
                GLib.idle_add(self.status.set_text, _("Opening the shared folders…"))
                m = remote.Mount(conn)
                path = m.start()
            except proto.ProtocolError as e:
                GLib.idle_add(self.failed, error_text(e, d["name"]))
                return
            except (OSError, RuntimeError) as e:
                GLib.idle_add(self.failed, _("Cannot connect to %s: %s") % (d["name"], e))
                return
            if cancel.is_set():
                m.close()
                GLib.idle_add(self.failed, "")
                return
            GLib.idle_add(self.connected, m, path)

        threading.Thread(target=run, daemon=True).start()

    def on_status(self, state, info):
        if state == "waiting":
            self.status.set_text(_("Waiting for “%s” to allow access…") % info["peer_name"])
            if not info.get("trusted"):
                self.code_box.foreach(self.code_box.remove)
                self.code_box.pack_start(Gtk.Label(label=_("Verification code")), False, False, 0)
                self.code_box.pack_start(sas_widget(info["sas"]), False, False, 0)
                self.code_box.show_all()
        return False

    def ask_code(self, info, replied, done):
        self.code_box.pack_start(Gtk.Label(label=_("Continue only if “%s” shows the same code.") % info["peer_name"],
                                           wrap=True, max_width_chars=48), False, False, 0)
        self.code_box.show_all()
        self.match_btn.show()
        self._code_cb = done

        def watch():
            if self._code_cb is None:
                return False
            if replied.is_set() and not getattr(replied, "accepted", False):
                self._code_answer(False)
                return False
            return True
        GLib.timeout_add(300, watch)
        return False

    def _code_answer(self, ok):
        cb, self._code_cb = self._code_cb, None
        self.match_btn.hide()
        if cb is not None:
            cb((ok, ok))

    def on_cancel(self):
        if self._code_cb is not None:
            self._code_answer(False)
        if self.cancel is not None:
            self.cancel.set()

    def failed(self, text):
        self.busy = False
        self._code_cb = None
        self.spinner.stop()
        self.stack.set_visible_child_name("list")
        self.info.set_text(text)
        return False

    def connected(self, m, path):
        self.busy = False
        self.spinner.stop()
        self.mounts.append(m)
        self.stack.set_visible_child_name("list")
        self.refresh_connections()
        self.hide()
        threading.Thread(target=remote.open_side_by_side, args=(path,), daemon=True).start()
        if self.notifier is not None:
            try:
                body = _("The files of “%s” are in the sidebar of Files.") % m.conn.peer_name
                if not m.conn.write:
                    body += " " + _("Read-only.")
                nid = self.notifier.notify(_("Connected to %s") % m.conn.peer_name, GLib.markup_escape_text(body),
                                           ["disconnect", _("Disconnect")], 15000)
                self.notifier.waiting[nid] = lambda key, m=m: key == "disconnect" and threading.Thread(
                    target=m.close, daemon=True).start()
            except GLib.Error:
                pass
        return False

    def tick(self):
        for m in list(self.mounts):
            if not m.alive():
                self.mounts.remove(m)
                lost = not m._closed
                threading.Thread(target=m.close, daemon=True).start()
                if lost and self.notifier is not None:
                    try:
                        self.notifier.notify(_("Disconnected from %s") % m.conn.peer_name,
                                             GLib.markup_escape_text(_("The connection was closed.")), [], -1)
                    except GLib.Error:
                        pass
                if self.get_visible():
                    self.refresh_connections()
        if not self.get_visible() and not self.mounts and not self.busy:
            Gtk.main_quit()
            return False
        return True

    def on_close(self, *_a):
        if self.busy:
            self.on_cancel()
        self.hide()
        if not self.mounts:
            Gtk.main_quit()
        return True

    def shutdown(self):
        for m in list(self.mounts):
            m.close()
        if self.disc:
            self.disc.stop()


def error_text(e, name):
    return {
        proto.E_DECLINED: _("“%s” denied access.") % name,
        proto.E_TIMEOUT: _("“%s” did not answer in time.") % name,
        proto.E_BUSY: _("“%s” is busy. Try again later.") % name,
        proto.E_SHARING_OFF: _("“%s” does not share any folders.") % name,
        proto.E_KEY_MISMATCH: _("“%s” presented a different key than expected. Someone may be impersonating it. "
                                "If it was reinstalled, remove it from Trusted devices and try again.") % name,
        proto.E_SAS_REJECTED: _("Cancelled: the codes were not confirmed."),
        proto.E_CANCELLED: "",
    }.get(e.code, _("Cannot connect to %s: %s") % (name, e.message))


def main(want_write=False):
    from gi.repository import GLib as _G
    _G.set_prgname("luxdrop")
    win = ConnectWindow(want_write)
    win.show_all()
    win.refresh_connections()
    win.match_btn.hide()
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda *_a: (Gtk.main_quit(), False)[1])
    Gtk.main()
    win.shutdown()
    return 0
