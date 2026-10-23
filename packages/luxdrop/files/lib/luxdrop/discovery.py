"""LuxDrop - objevovani zarizeni pres mDNS/DNS-SD (Avahi pres D-Bus, Gio).

Sluzba _luxdrop._tcp, TXT: v=<verze protokolu>, id=<kratke ID>, name=<jmeno>.
Data z mDNS nejsou duveryhodna - identitu overuje az TLS + pripnuty otisk/SAS.
"""
import socket

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import proto  # noqa: E402

AVAHI = "org.freedesktop.Avahi"
IF_UNSPEC = -1
PROTO_UNSPEC = -1
PROTO_INET = 0
PROTO_INET6 = 1
NO_AUTO_START = Gio.DBusCallFlags.NO_AUTO_START
LOOKUP_RESULT_LOCAL = 8


def _txt(items):
    return [bytearray(("%s=%s" % kv).encode("utf-8")[:255]) for kv in items]


def _parse_txt(aay):
    out = {}
    for raw in aay:
        try:
            k, _, v = bytes(raw).decode("utf-8").partition("=")
        except UnicodeDecodeError:
            continue
        out[k.lower()] = v
    return out


class Discovery:
    def __init__(self, on_change=None):
        self.on_change = on_change or (lambda: None)
        self.peers = {}  # klic (rozhrani, protokol, jmeno) -> zaznam
        self.bus = None
        self.group = None
        self.browser = None
        self._subs = []
        self._pending = []
        self.error = ""
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        except GLib.Error as e:
            self.error = e.message

    def available(self):
        """Bezi Avahi? (nespoustime ho sami pres D-Bus aktivaci)."""
        if self.bus is None:
            return False
        try:
            r = self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                   "NameHasOwner", GLib.Variant("(s)", (AVAHI,)), GLib.VariantType("(b)"),
                                   0, 2000, None)
            return r.unpack()[0]
        except GLib.Error as e:
            self.error = e.message
            return False

    def _call(self, path, iface, method, args, rtype):
        return self.bus.call_sync(AVAHI, path, "org.freedesktop.Avahi." + iface, method, args,
                                  GLib.VariantType(rtype) if rtype else None, NO_AUTO_START, 5000, None)

    # --- Zverejneni -----------------------------------------------------------

    def publish(self, name, dev_id, port):
        self.unpublish()
        if not self.available():
            self.error = "Avahi is not running"
            return False
        try:
            path = self._call("/", "Server", "EntryGroupNew", None, "(o)").unpack()[0]
            inst = ("%s (%s)" % (name, dev_id[:6]))[:63]
            txt = _txt([("v", proto.PROTO_VERSION), ("id", dev_id), ("name", name)])
            self._call(path, "EntryGroup", "AddService",
                       GLib.Variant("(iiussssqaay)", (IF_UNSPEC, PROTO_UNSPEC, 0, inst, proto.SERVICE_TYPE,
                                                      "", "", port, txt)), None)
            self._call(path, "EntryGroup", "Commit", None, None)
            self.group = path
            return True
        except GLib.Error as e:
            self.error = e.message
            return False

    def unpublish(self):
        if self.group and self.bus:
            try:
                self._call(self.group, "EntryGroup", "Free", None, None)
            except GLib.Error:
                pass
        self.group = None

    # --- Hledani --------------------------------------------------------------

    def browse(self):
        """Spusti hledani (potrebuje bezici GLib main loop)."""
        if self.browser or not self.available():
            if not self.browser:
                self.error = "Avahi is not running"
            return bool(self.browser)
        for sig in ("ItemNew", "ItemRemove"):
            self._subs.append(self.bus.signal_subscribe(AVAHI, "org.freedesktop.Avahi.ServiceBrowser", sig,
                                                        None, None, 0, self._on_signal))
        args = GLib.Variant("(iissu)", (IF_UNSPEC, PROTO_UNSPEC, proto.SERVICE_TYPE, "", 0))
        try:
            # Avahi >= 0.8: Prepare + Start (bez zavodu o prvni signaly)
            self.browser = self._call("/", "Server2", "ServiceBrowserPrepare", args, "(o)").unpack()[0]
            self._call(self.browser, "ServiceBrowser", "Start", None, None)
        except GLib.Error:
            try:
                self.browser = self._call("/", "Server", "ServiceBrowserNew", args, "(o)").unpack()[0]
            except GLib.Error as e:
                self.error = e.message
                return False
        for p in self._pending:
            self._on_signal(*p)
        self._pending = []
        return True

    def stop(self):
        for s in self._subs:
            self.bus.signal_unsubscribe(s)
        self._subs = []
        if self.browser:
            try:
                self._call(self.browser, "ServiceBrowser", "Free", None, None)
            except GLib.Error:
                pass
        self.browser = None
        self.unpublish()

    def _on_signal(self, _conn, _sender, path, _iface, signal, params):
        if self.browser is None:
            self._pending.append((_conn, _sender, path, _iface, signal, params))
            return
        if path != self.browser:
            return
        iface, prot, name, stype, domain, _flags = params.unpack()
        key = (iface, prot, name)
        if signal == "ItemRemove":
            if self.peers.pop(key, None) is not None:
                self.on_change()
            return
        self._resolve(iface, prot, name, stype, domain, PROTO_INET if prot == PROTO_INET else PROTO_INET6)

    def _resolve(self, iface, prot, name, stype, domain, aproto):
        args = GLib.Variant("(iisssiu)", (iface, prot, name, stype, domain, aproto, 0))

        def done(bus, res):
            try:
                r = bus.call_finish(res).unpack()
            except GLib.Error:
                return
            _i, _p, _n, _t, _d, host, _ap, address, port, txt, flags = r
            meta = _parse_txt(txt)
            if meta.get("v") != str(proto.PROTO_VERSION) or len(meta.get("id", "")) != 16:
                return
            if address.startswith("fe80:"):
                try:
                    address += "%" + socket.if_indextoname(iface)
                except OSError:
                    return
            self.peers[(iface, prot, name)] = {
                "name": meta.get("name", name)[:63], "id": meta["id"].lower(), "host": address,
                "port": port, "hostname": host, "local": bool(flags & LOOKUP_RESULT_LOCAL),
            }
            self.on_change()

        self.bus.call(AVAHI, "/", "org.freedesktop.Avahi.Server", "ResolveService", args,
                      GLib.VariantType("(iissssisqaayu)"), NO_AUTO_START, 5000, None, done)

    def devices(self, own_id=None):
        """Seznam zarizeni bez duplicit (podle ID), IPv4 ma prednost."""
        out = {}
        for p in self.peers.values():
            if own_id and p["id"] == own_id:
                continue
            cur = out.get(p["id"])
            if cur is None or (":" in cur["host"] and ":" not in p["host"]):
                out[p["id"]] = p
        return sorted(out.values(), key=lambda p: p["name"].lower())
