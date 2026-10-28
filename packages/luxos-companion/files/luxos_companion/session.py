"""Jedno spojeni s telefonem: handshake, schvaleni telefonu, ping/pong, necinnost a rozdeleni zprav.

Stavy: "handshake" (ceka na hello, nejvys 20 s od pripojeni) -> "approving" (neznamy telefon, ceka na
odpoved uzivatele, stale v limitu 20 s) -> "probing" (zjisteni schopnosti LuxAI, kdyz nejsou v mezipameti;
stale v limitu 20 s) -> "open" (po hello.ok se schopnostmi) -> "closed". Do hello.ok server
neposila nic jineho; jina zprava nez hello pred handshake spojeni ukonci. Bez prijate zpravy 45 s
se spojeni zavre. Nezname typy zprav se po handshake ignoruji (dopredna kompatibilita).

Session je bez GLib (testy s falesnymi hodinami); FdTransport cte/zapisuje neblokujici fd v hlavni
smycce GLib (RFCOMM socket z BlueZ, v testech socketpair).
"""
import os
import time

from . import wire
from .calendar_note import NoteError, fit_events
from .location import InvalidLocation

HANDSHAKE_S = 20.0
IDLE_S = 45.0
MAX_OUTPUT = 1024 * 1024     # neodeslana data; telefon necte -> zavrit
MAX_EARLY = 32               # zprav pred hello.ok behem zjistovani schopnosti


def _(s):
    return s


def set_translator(fn):
    global _
    _ = fn


class Session:
    _next_key = 0

    def __init__(self, hub, peer, transport=None, clock=time.monotonic):
        Session._next_key += 1
        self.key = f"s{Session._next_key}"
        self.hub = hub
        self.peer = peer             # {"address": "AA:..", "name": "Pixel"}
        self.transport = transport
        self.clock = clock
        self.decoder = wire.Decoder()
        self.state = "handshake"
        self.started = clock()
        self.last_rx = self.started
        self.hello_id = None
        self.close_reason = None
        self.luxai = None
        self.location_enabled = None
        self.caps = []               # schopnosti ohlasene v hello.ok
        self.early = []              # zpravy prijate behem "probing"

    # ---- vstup z transportu ----
    def data_received(self, data):
        if self.state == "closed":
            return
        try:
            for msg in self.decoder.feed(data):
                self.last_rx = self.clock()
                self._dispatch(msg)
                if self.state == "closed":
                    return
        except wire.ProtocolError as e:
            self.close(e.code)

    def eof(self):
        if self.state == "closed":
            return
        try:
            self.decoder.eof()
        except wire.ProtocolError as e:
            self.close(e.code)
            return
        self.close("eof")

    def tick(self):
        """Casovace (volat aspon jednou za sekundu): limit handshake a necinnost."""
        if self.state == "closed":
            return
        now = self.clock()
        if self.state in ("handshake", "approving", "probing"):
            if now - self.started >= HANDSHAKE_S:
                self.close("handshake_timeout")
        elif now - self.last_rx >= IDLE_S:
            self.close("idle_timeout")

    # ---- vystup ----
    def send(self, msg):
        """Odesle zpravu (dict bez v/id dostane v/id). False, kdyz spojeni neni."""
        if self.state == "closed" or self.transport is None:
            return False
        full = wire.message(msg.pop("type"), **msg) if "id" not in msg else msg
        try:
            data = wire.encode(full)
        except ValueError:
            return False
        self.transport.write(data)
        if self.transport.pending() > MAX_OUTPUT:
            self.close("output_overflow")
            return False
        return True

    def error(self, reply_to, code, message):
        return self.send({"type": "error", "reply_to": reply_to, "code": code, "message": message})

    def close(self, reason="closed"):
        if self.state == "closed":
            return
        self.state = "closed"
        self.close_reason = reason
        if self.luxai is not None:
            self.luxai.close()
            self.luxai = None
        if self.transport is not None:
            self.transport.close()
        self.hub.session_closed(self)

    # ---- zpravy ----
    def _dispatch(self, msg):
        t = msg["type"]
        if self.state == "handshake":
            if t != "hello":
                raise wire.ProtocolError("handshake_expected", "expected hello")
            self._hello(msg)
            return
        if self.state == "probing":
            # telefon uz handshake ma za sebou (schvaleny) - zpravy pockaji na hello.ok
            if len(self.early) >= MAX_EARLY:
                raise wire.ProtocolError("handshake_expected", "too many messages before hello.ok")
            self.early.append(msg)
            return
        if self.state == "approving":
            # telefon ma do hello.ok mlcet
            raise wire.ProtocolError("handshake_expected", "message before hello.ok")
        handler = getattr(self, "_on_" + t.replace(".", "_"), None) if t in HANDLED else None
        if handler is not None:
            handler(msg)

    def _hello(self, msg):
        self.hello_id = msg["id"]
        if msg.get("protocol") != 1 or type(msg.get("protocol")) is not int:
            self.error(msg["id"], "unsupported_protocol", _("This LuxOS supports only protocol version 1."))
            self.close("unsupported_protocol")
            return
        if self.hub.settings.is_approved(self.peer["address"]):
            self._open()
            return
        self.state = "approving"
        self.hub.authorize(self, self._authorized)

    def _authorized(self, allowed):
        if self.state != "approving":
            return
        if allowed:
            self._open()
        else:
            self.error(self.hello_id, "not_approved",
                       _("This phone is not allowed to connect. Allow it on the computer and connect again."))
            self.close("not_approved")

    def _open(self):
        # schopnosti cele cesty (most + nainstalovane LuxAI); bez mezipameti chvili trva -> "probing"
        self.state = "probing"
        self.hub.capabilities(self._capabilities_ready)

    def _capabilities_ready(self, caps):
        if self.state != "probing":
            return
        self.caps = list(caps)
        self.state = "open"
        self.last_rx = self.clock()
        self.send({"type": "hello.ok", "reply_to": self.hello_id, "protocol": 1, "server": "LuxOS",
                   "capabilities": list(self.caps)})
        self.hub.session_opened(self)
        early, self.early = self.early, []
        try:
            for msg in early:
                self._dispatch(msg)
                if self.state == "closed":
                    return
        except wire.ProtocolError as e:
            self.close(e.code)

    def _bridge(self):
        if self.luxai is None:
            self.luxai = self.hub.make_luxai(self.send)
            if hasattr(self.luxai, "features"):
                self.luxai.features = set(self.caps)
                self.luxai.on_change = self.hub.status_changed
        return self.luxai

    def pending_approvals(self):
        fn = getattr(self.luxai, "pending_approvals", None)
        return fn() if fn else 0

    def _on_ping(self, msg):
        self.send({"type": "pong", "reply_to": msg["id"]})

    def _on_location_status(self, msg):
        enabled = msg.get("enabled")
        if not isinstance(enabled, bool):
            self.error(msg["id"], "invalid_request", _("Invalid location status."))
            return
        self.location_enabled = enabled
        self.hub.location.set_status(self.key, enabled)
        self.hub.status_changed()

    def _on_location_update(self, msg):
        if not self.hub.settings.get("share_location"):
            return                   # sdileni vypnute v nastaveni - fixy se zahazuji
        try:
            self.hub.location.update(self.key, msg, self.peer.get("name", ""))
        except InvalidLocation as e:
            self.error(msg["id"], "invalid_location", _("Invalid location: %s") % e)

    def _on_luxai_request(self, msg):
        if not self.hub.settings.get("allow_luxai"):
            self.error(msg["id"], "permission_denied",
                       _("LuxAI requests from the phone are turned off on this computer (Phone settings)."))
            return
        self._bridge().request(msg)

    def _on_luxai_cancel(self, msg):
        if self.luxai is not None:
            self.luxai.cancel(msg)

    def _on_luxai_models_list(self, msg):
        if not self.hub.settings.get("allow_luxai"):
            self.error(msg["id"], "permission_denied",
                       _("LuxAI requests from the phone are turned off on this computer (Phone settings)."))
            return
        self._bridge().models(msg)

    def _on_luxai_approval_respond(self, msg):
        if self.luxai is None or not hasattr(self.luxai, "approve"):
            self.error(msg["id"], "approval_invalid",
                       _("This approval is no longer valid (already answered, expired or the request has ended)."))
            return
        self.luxai.approve(msg)

    def _on_calendar_events_list(self, msg):
        if not self.hub.settings.get("allow_calendar_read"):
            self.error(msg["id"], "permission_denied",
                       _("Reading the calendar from the phone is turned off on this computer (Phone settings)."))
            return
        try:
            events, truncated = self.hub.calendar_reader.list_events(msg)
        except NoteError as e:
            self.error(msg["id"], e.code, e.message)
            return
        out = wire.message("calendar.events", reply_to=msg["id"], truncated=truncated)
        out["truncated"] = fit_events(out, events) or truncated
        self.send(out)

    def _on_calendar_note_create(self, msg):
        if not self.hub.settings.get("allow_calendar"):
            self.error(msg["id"], "permission_denied",
                       _("Saving notes from the phone to the calendar is turned off on this computer "
                         "(Phone settings)."))
            return
        try:
            uid = self.hub.calendar.create(msg["id"], msg)
        except NoteError as e:
            self.error(msg["id"], e.code, e.message)
            return
        self.send({"type": "calendar.saved", "reply_to": msg["id"], "event_id": uid})
        self.hub.calendar_saved(self, str(msg.get("title") or "")[:200])


HANDLED = {"ping", "location.status", "location.update", "luxai.request", "luxai.cancel", "calendar.note.create",
           "luxai.models.list", "luxai.approval.respond", "calendar.events.list"}


def fd_add(fd, cond, cb):
    """Sledovani fd v hlavni smycce (GLibUnix od PyGObject 3.52, jinak GLib.unix_fd_add_full)."""
    from gi.repository import GLib
    try:
        import gi
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        return GLibUnix.fd_add_full(GLib.PRIORITY_DEFAULT, fd, cond, cb)
    except (ImportError, ValueError, AttributeError):
        return GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, fd, cond, cb)


class FdTransport:
    """Neblokujici fd (RFCOMM socket) v hlavni smycce GLib."""

    def __init__(self, fd, session=None):
        from gi.repository import GLib
        self.GLib = GLib
        self.fd = fd
        self.session = session
        self.out = bytearray()
        self.closing = False
        self.closed = False
        self.in_watch = None
        self.out_watch = None
        self.close_timer = None
        os.set_blocking(fd, False)

    def start(self, session):
        self.session = session
        GLib = self.GLib
        self.in_watch = fd_add(self.fd, GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                               self._on_in)

    def pending(self):
        return len(self.out)

    def _on_in(self, _fd, cond):
        if self.closed:
            return False
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return True
        except OSError:
            data = b""
        if data:
            self.session.data_received(data)
            return not self.closed and not self.closing
        self.in_watch = None
        self.session.eof()
        return False

    def write(self, data):
        if self.closed:
            return
        self.out += data
        self._flush()

    def _flush(self):
        while self.out and not self.closed:
            try:
                n = os.write(self.fd, self.out)
            except BlockingIOError:
                break
            except OSError:
                self.out.clear()         # EPIPE, ECONNRESET...: spojeni je pryc
                if self.session and not self.closing:
                    self.GLib.idle_add(lambda: self.session.close("write_failed") and False)
                break
            del self.out[:n]
        if self.out and self.out_watch is None and not self.closed:
            self.out_watch = fd_add(self.fd, self.GLib.IOCondition.OUT, self._on_out)
        if not self.out and self.closing:
            self._really_close()

    def _on_out(self, _fd, _cond):
        self.out_watch = None
        self._flush()
        return False

    def close(self):
        """Zavre po odeslani rozepsanych dat (nejvys 2 s)."""
        if self.closing or self.closed:
            return
        self.closing = True
        if self.in_watch is not None:
            self.GLib.source_remove(self.in_watch)
            self.in_watch = None
        if not self.out:
            self._really_close()
        else:
            self.close_timer = self.GLib.timeout_add(2000, self._close_timeout)

    def _close_timeout(self):
        self.close_timer = None
        return self._really_close()

    def _really_close(self):
        if self.closed:
            return False
        self.closed = True
        for w in (self.in_watch, self.out_watch, self.close_timer):
            if w is not None:
                try:
                    self.GLib.source_remove(w)
                except Exception:  # noqa: BLE001 - zdroj uz skoncil
                    pass
        self.in_watch = self.out_watch = self.close_timer = None
        try:
            os.close(self.fd)
        except OSError:
            pass
        return False
