"""LuxDrop - prijem na pozadi (luxdrop-receiver.service).

Dotazy na prijeti se zobrazuji jako oznameni s tlacitky (org.freedesktop.Notifications).
Bez oznamovaci sluzby se neduveryhodne prenosy odmitnou.
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
from .discovery import Discovery  # noqa: E402

NOTIFY = "org.freedesktop.Notifications"
NOTIFY_PATH = "/org/freedesktop/Notifications"


class Notifier:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.waiting = {}  # id oznameni -> (Event, vysledek)
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
            ev, res = self.waiting.pop(nid)
            res["v"] = key
            ev.set()
        elif nid in self.open_dirs and key == "open":
            subprocess.Popen(["xdg-open", self.open_dirs.pop(nid)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)

    def _on_closed(self, _c, _s, _p, _i, _sig, params):
        nid, _reason = params.unpack()
        if nid in self.waiting:
            ev, res = self.waiting.pop(nid)
            res.setdefault("v", "decline")
            ev.set()


class NotifyHandler(transfer.Handler):
    def __init__(self, notifier, settings):
        self.n = notifier
        self.settings = settings

    def _main(self, fn, *a):
        """Volani v hlavnim vlakne GLib a pockani na vysledek."""
        ev, box = threading.Event(), {}

        def run():
            try:
                box["v"] = fn(*a)
            except GLib.Error as e:
                box["e"] = e
            ev.set()
            return False

        GLib.idle_add(run)
        ev.wait(10)
        if "e" in box or "v" not in box:
            raise RuntimeError("notification failed")
        return box["v"]

    def ask(self, req):
        esc = GLib.markup_escape_text  # telo oznameni muze byt interpretovano jako markup
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
        try:
            ev, res = threading.Event(), {}
            nid = self._main(self.n.notify, _("LuxDrop: incoming files"), body, actions, 0, True)
            self.n.waiting[nid] = (ev, res)
        except RuntimeError:
            return False, False
        while not ev.wait(0.5):
            if req.withdrawn.is_set():
                self.n.waiting.pop(nid, None)
                GLib.idle_add(self.n.close, nid)
                return False, False
        return res.get("v") in ("accept", "trust"), res.get("v") == "trust"

    def finished(self, t):
        def show():
            try:
                if t.state == "done":
                    nid = self.n.notify(_("LuxDrop: received from %s") % t.peer_name,
                                        GLib.markup_escape_text(", ".join(os.path.basename(p) for p in t.saved[:5])),
                                        ["open", _("Show in folder")])
                    self.n.open_dirs[nid] = self.settings.download_dir
                elif t.state == "failed":
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
        return 1
    handler = NotifyHandler(notifier, ctx.settings)
    rx = transfer.Receiver(ctx.identity, ctx.settings, ctx.trust, ctx.history, handler,
                           bind=args.bind or "", port=args.port)
    port = rx.start()
    disc = Discovery()
    state = {"key": None}

    def sync():
        # Zverejneni podle aktualniho nastaveni (meni ho graficka aplikace)
        ctx.settings.reload()
        key = (ctx.settings.name, ctx.settings.mode() != "off")
        if key != state["key"]:
            state["key"] = key
            if key[1]:
                disc.publish(ctx.settings.name, ctx.identity.id, port)
            else:
                disc.unpublish()
        return True

    sync()
    GLib.timeout_add_seconds(5, sync)
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda *_a: (loop.quit(), False)[1])
    print("luxdrop: receiving in the background on port %d (mode %s)" % (port, ctx.settings.mode()), flush=True)
    loop.run()
    rx.stop()
    disc.unpublish()
    return 0
