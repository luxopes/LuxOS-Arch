"""LuxDrop - prijem na pozadi (luxdrop-receiver.service), LuxDrop i LocalSend.

Pri dotazu na prijeti se ukaze oznameni a (je-li k dispozici displej) i dialog
prijeti - stejny jako v okne aplikace. Odpovedet lze v dialogu nebo tlacitky
v oznameni; plati prvni odpoved. Bez displeje i oznamovaci sluzby se neduveryhodne
prenosy odmitnou.
"""
import os
import signal
import subprocess
import threading

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import proto, transfer  # noqa: E402
from .cli import _, human  # noqa: E402
from .engine import Engine  # noqa: E402

NOTIFY = "org.freedesktop.Notifications"
NOTIFY_PATH = "/org/freedesktop/Notifications"


class Notifier:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.waiting = {}  # id oznameni -> callback(klic akce)
        self.open_dirs = {}
        self.bus.signal_subscribe(NOTIFY, NOTIFY, "ActionInvoked", NOTIFY_PATH, None, 0, self._on_action)
        self.bus.signal_subscribe(NOTIFY, NOTIFY, "NotificationClosed", NOTIFY_PATH, None, 0, self._on_closed)

    def notify(self, summary, body, actions=(), timeout=-1, urgent=False):
        hints = {"desktop-entry": GLib.Variant("s", "luxdrop")}
        if urgent:
            hints["urgency"] = GLib.Variant("y", 2)
        r = self.bus.call_sync(NOTIFY, NOTIFY_PATH, NOTIFY, "Notify",
                               GLib.Variant("(susssasa{sv}i)", ("LuxDrop", 0, "luxdrop", summary, body,
                                                                list(actions), hints, timeout)),
                               GLib.VariantType("(u)"), 0, 5000, None)
        return r.unpack()[0]

    def close(self, nid):
        try:
            self.bus.call_sync(NOTIFY, NOTIFY_PATH, NOTIFY, "CloseNotification", GLib.Variant("(u)", (nid,)),
                               None, 0, 2000, None)
        except GLib.Error:
            pass

    def _on_action(self, _c, _s, _p, _i, _sig, params):
        nid, key = params.unpack()
        if nid in self.waiting:
            self.waiting.pop(nid)(key)
        elif nid in self.open_dirs and key == "open":
            subprocess.Popen(["xdg-open", self.open_dirs.pop(nid)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)

    def _on_closed(self, _c, _s, _p, _i, _sig, params):
        nid, _reason = params.unpack()
        cb = self.waiting.pop(nid, None)
        if cb is not None:
            cb("closed")


def gtk_available():
    """Dialog jen kdyz ma sluzba displej (DISPLAY/WAYLAND_DISPLAY z prostredi relace)."""
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        r = Gtk.init_check([])
        return r[0] if isinstance(r, tuple) else bool(r)
    except (ValueError, ImportError):
        return False


class ServiceHandler(transfer.Handler):
    def __init__(self, notifier, settings, use_gtk):
        self.n = notifier
        self.settings = settings
        self.use_gtk = use_gtk

    def ask(self, req):
        ev, box = threading.Event(), {}
        ui = {}

        def answer(v, source=None):
            # Prvni odpoved (dialog nebo oznameni) plati; druhe se zavre
            if "v" in box:
                return
            box["v"] = v
            ev.set()

            def cleanup():
                if ui.get("nid") is not None and self.n is not None:
                    self.n.waiting.pop(ui["nid"], None)
                    self.n.close(ui["nid"])
                if ui.get("dlg") is not None and source != "dialog":  # dialog se zavrel sam
                    try:
                        ui["dlg"].destroy()
                    except Exception:  # noqa: BLE001 - dialog uz muze byt zavreny
                        pass
                return False
            GLib.idle_add(cleanup)

        def show():
            esc = GLib.markup_escape_text  # telo oznameni muze byt interpretovano jako markup
            if req.message is not None:
                summary = _("LuxDrop: message from %s") % req.peer_name
                body = esc(req.message[:300])
                actions = []
            else:
                summary = _("LuxDrop: incoming files")
                body = _("%s wants to send you %d item(s), %s: %s") % (
                    esc(req.peer_name), len(req.items), human(req.total), esc(", ".join(req.items[:5])))
                if req.sas:
                    body += "\n" + _("Verification code: %s  (must be the same on the sender's screen)") \
                        % proto.format_sas(req.sas)
                if req.name_clash:
                    body += "\n" + _("WARNING: this device uses the name of a trusted device, but a different key!")
                actions = ["decline", _("Decline"), "accept", _("Accept")]
                if req.sas:
                    actions += ["trust", _("Accept and trust")]
            if self.use_gtk:
                from . import dialogs
                ui["dlg"] = dialogs.accept_dialog(req, lambda v: answer(v, "dialog"))
                # Oznameni az po vykresleni dialogu (spusteni oznamovaci sluzby muze chvili trvat)
                GLib.timeout_add(300, notify, summary, body, actions)
            else:
                notify(summary, body, actions)
            return False

        def notify(summary, body, actions):
            if "v" in box:
                return False
            if self.n is not None:
                try:
                    nid = self.n.notify(summary, body, [] if self.use_gtk else actions, 0 if actions else -1,
                                        bool(actions))
                    ui["nid"] = nid
                    if actions and not self.use_gtk:
                        self.n.waiting[nid] = lambda key: answer((key in ("accept", "trust"), key == "trust"))
                except GLib.Error:
                    if not self.use_gtk:
                        answer((False, False))
            elif not self.use_gtk:
                answer((False, False))
            return False

        GLib.idle_add(show)
        while not ev.wait(0.5):
            if req.withdrawn.is_set():
                answer((False, False))
        return box["v"]

    def finished(self, t):
        if self.n is None:
            return

        def show():
            try:
                if t.state == "done" and t.saved:
                    nid = self.n.notify(_("LuxDrop: received from %s") % t.peer_name,
                                        GLib.markup_escape_text(", ".join(os.path.basename(p) for p in t.saved[:5])),
                                        ["open", _("Show in folder")])
                    self.n.open_dirs[nid] = self.settings.download_dir
                elif t.state == "failed" and t.items:
                    self.n.notify(_("LuxDrop: transfer from %s failed") % t.peer_name,
                                  GLib.markup_escape_text(t.error))
            except GLib.Error:
                pass
            return False
        GLib.idle_add(show)


def run_service(ctx, args):
    loop = GLib.MainLoop()
    try:
        notifier = Notifier()
    except GLib.Error as e:
        print("luxdrop: no session bus: %s" % e.message)
        notifier = None
    use_gtk = gtk_available()
    if notifier is None and not use_gtk:
        print("luxdrop: neither notifications nor a display are available", flush=True)
        return 1
    handler = ServiceHandler(notifier, ctx.settings, use_gtk)
    eng = Engine(ctx.identity, ctx.settings, ctx.trust, ctx.history, handler, bind=args.bind or "",
                 port=args.port, ls_port=args.ls_port, mdns=not args.no_mdns, multicast=not args.no_multicast)
    eng.start(browse=False)
    if eng.receiver is None and eng.ls_server is None:
        print("luxdrop: cannot listen: %s" % "; ".join(e[2] for e in eng.errors), flush=True)
        return 1
    for kind, port, err in eng.errors:
        print("luxdrop: %s %s: %s" % (kind, port or "", err), flush=True)

    def sync():
        eng.sync()  # zmeny nastaveni z okna aplikace
        return True

    GLib.timeout_add_seconds(5, sync)
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda *_a: (loop.quit(), False)[1])
    print("luxdrop: receiving in the background (LuxDrop port %s, LocalSend port %s, mode %s, dialogs %s)"
          % (eng.receiver.port if eng.receiver else "-", eng.ls_server.port if eng.ls_server else "-",
             ctx.settings.mode(), "yes" if use_gtk else "no"), flush=True)
    loop.run()
    eng.stop()
    return 0
