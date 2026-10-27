"""Sluzba LuxOS Companion v relaci (systemd --user, luxos-companion.service).

Registruje profil RFCOMM v BlueZ, obsluhuje spojeni telefonu (session.Session), pta se na schvaleni
neznamych telefonu (oznameni Povolit/Odmitnout, i v okne Telefon) a na sbernici relace zverejnuje
cz.luxos.Companion1 na /cz/luxos/Companion1:

  GetLocation() -> a{sv}           poloha telefonu: valid (b); pri valid=true latitude, longitude,
                                   accuracy (m), timestamp_ms (UTC fixu podle telefonu), age_ms (stari
                                   podle hodin PC), mock, device; volitelne altitude, speed, bearing
  property CurrentLocation a{sv}   totez (PropertiesChanged pri zmene)
  signal LocationChanged(a{sv})    novy fix, zastarani (15 s), enabled:false, odpojeni
  GetStatus() -> s                 JSON: bluetooth, spojeni, cekajici schvaleni
  signal StatusChanged(s)
  AnswerApproval(s address, b allow)   odpoved na dotaz (okno Telefon)
  Disconnect(s address)            odpojit telefon
  ReloadSettings()                 po zmene companion.json (sluzba ho hlida i sama)

Poloha je platna jen se zapnutym "Sdilet polohu telefonu s Mapami"; Mapy ji navic pouziji jen po
vlastnim souhlasu s polohou (luxos_maps.my_location).
"""
import json
import os
import signal
import subprocess
import sys
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import BUS_NAME, INTERFACE, OBJECT_PATH, calendar_note, luxai_bridge, session, store  # noqa: E402
from .location import LocationState  # noqa: E402

try:
    sys.path.insert(1, "/usr/lib/luxos/python")
    from luxos_i18n import _  # noqa: E402
except ImportError:  # pragma: no cover
    def _(s):
        return s

for _mod in (calendar_note, luxai_bridge, session):
    _mod.set_translator(_)

NOTIFY = "org.freedesktop.Notifications"
NOTIFY_PATH = "/org/freedesktop/Notifications"
APP = "luxos-companion"

IFACE_XML = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="GetLocation"><arg name="location" type="a{{sv}}" direction="out"/></method>
    <method name="GetStatus"><arg name="status" type="s" direction="out"/></method>
    <method name="AnswerApproval">
      <arg name="address" type="s" direction="in"/><arg name="allow" type="b" direction="in"/>
    </method>
    <method name="Disconnect"><arg name="address" type="s" direction="in"/></method>
    <method name="ReloadSettings"/>
    <property name="CurrentLocation" type="a{{sv}}" access="read"/>
    <signal name="LocationChanged"><arg name="location" type="a{{sv}}"/></signal>
    <signal name="StatusChanged"><arg name="status" type="s"/></signal>
  </interface>
</node>
"""


def log(*args):
    if os.environ.get("LUXOS_COMPANION_QUIET"):
        return
    print("luxos-companion:", *args, file=sys.stderr, flush=True)


def location_variant(snap):
    """Slovnik polohy -> a{sv}."""
    types = {"valid": "b", "latitude": "d", "longitude": "d", "accuracy": "d", "timestamp_ms": "x",
             "age_ms": "x", "mock": "b", "device": "s", "altitude": "d", "speed": "d", "bearing": "d"}
    return {k: GLib.Variant(types[k], v) for k, v in snap.items() if k in types}


class Notifier:
    """Oznameni s tlacitky (org.freedesktop.Notifications)."""

    def __init__(self, bus):
        self.bus = bus
        self.waiting = {}            # id oznameni -> callback(klic akce | "closed")
        bus.signal_subscribe(NOTIFY, NOTIFY, "ActionInvoked", NOTIFY_PATH, None, 0, self._on_action)
        bus.signal_subscribe(NOTIFY, NOTIFY, "NotificationClosed", NOTIFY_PATH, None, 0, self._on_closed)

    def notify(self, summary, body, actions=(), urgent=False, timeout=-1, replaces=0, callback=None):
        hints = {"desktop-entry": GLib.Variant("s", APP)}
        if urgent:
            hints["urgency"] = GLib.Variant("y", 2)
        try:
            r = self.bus.call_sync(NOTIFY, NOTIFY_PATH, NOTIFY, "Notify",
                                   GLib.Variant("(susssasa{sv}i)", (_("Phone"), replaces, APP, summary, body,
                                                                    list(actions), hints, timeout)),
                                   GLib.VariantType("(u)"), 0, 3000, None)
        except GLib.Error as e:
            log("notification failed:", e.message)
            return None
        nid = r.unpack()[0]
        if callback:
            self.waiting[nid] = callback
        return nid

    def close(self, nid):
        if not nid:
            return
        self.waiting.pop(nid, None)
        try:
            self.bus.call_sync(NOTIFY, NOTIFY_PATH, NOTIFY, "CloseNotification", GLib.Variant("(u)", (nid,)),
                               None, 0, 2000, None)
        except GLib.Error:
            pass

    def _on_action(self, _c, _s, _p, _i, _sig, params):
        nid, key = params.unpack()
        cb = self.waiting.pop(nid, None)
        if cb:
            cb(key)

    def _on_closed(self, _c, _s, _p, _i, _sig, params):
        nid, _reason = params.unpack()
        cb = self.waiting.pop(nid, None)
        if cb:
            cb("closed")


class Service:
    def __init__(self, session_bus, settings=None, calendar=None, clock=time.monotonic, notifier=None,
                 luxai_factory=None):
        self.bus = session_bus
        self.clock = clock
        self.settings = settings or store.Settings()
        self.calendar = calendar or calendar_note.CalendarWriter(
            done_path=os.path.join(store.state_dir(), "calendar-requests.json"))
        self.location = LocationState(clock=clock, on_change=self._location_changed)
        self.location.enabled = self.settings.get("share_location")
        self.notifier = notifier if notifier is not None else (Notifier(session_bus) if session_bus else None)
        self.luxai_factory = luxai_factory or (lambda send: luxai_bridge.LuxAIBridge(send))
        self.sessions = {}           # klic -> Session
        self.pending = {}            # adresa -> {"name", "callbacks": [(session, cb)], "nid"}
        self.bt = {"available": False, "registered": False, "error": None}
        self.profile = None
        self.timer = None
        self.reg_id = None
        self.settings_stamp = None
        self.approved = {a for a, _n in self.settings.phones()}

    # ---- D-Bus ----
    def export(self):
        info = Gio.DBusNodeInfo.new_for_xml(IFACE_XML)
        self.reg_id = self.bus.register_object(OBJECT_PATH, info.interfaces[0], self._on_call,
                                               self._on_get_property, None)

    def unexport(self):
        if self.reg_id is not None:
            self.bus.unregister_object(self.reg_id)
            self.reg_id = None

    def _on_call(self, _bus, _sender, _path, _iface, method, params, inv):
        if method == "GetLocation":
            inv.return_value(GLib.Variant("(a{sv})", (location_variant(self.location.snapshot()),)))
        elif method == "GetStatus":
            inv.return_value(GLib.Variant("(s)", (json.dumps(self.status(), ensure_ascii=False),)))
        elif method == "AnswerApproval":
            address, allow = params.unpack()
            self.answer(address, allow)
            inv.return_value(None)
        elif method == "Disconnect":
            self.disconnect(params.unpack()[0])
            inv.return_value(None)
        elif method == "ReloadSettings":
            self.reload_settings()
            inv.return_value(None)
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _on_get_property(self, _bus, _sender, _path, _iface, prop):
        if prop == "CurrentLocation":
            return GLib.Variant("a{sv}", location_variant(self.location.snapshot()))
        return None

    def _emit(self, name, variant):
        if self.bus is None:
            return
        try:
            self.bus.emit_signal(None, OBJECT_PATH, INTERFACE, name, variant)
        except GLib.Error:
            pass

    def _location_changed(self, snap):
        loc = location_variant(snap)
        self._emit("LocationChanged", GLib.Variant("(a{sv})", (loc,)))
        if self.bus is None:
            return
        try:
            self.bus.emit_signal(None, OBJECT_PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                 GLib.Variant("(sa{sv}as)", (INTERFACE, {"CurrentLocation": GLib.Variant(
                                     "a{sv}", loc)}, [])))
        except GLib.Error:
            pass

    def status(self):
        now = self.clock()
        conns = [{"address": s.peer["address"], "name": s.peer.get("name") or s.peer["address"],
                  "state": s.state, "since": round(now - s.started), "location": s.location_enabled}
                 for s in self.sessions.values()]
        pending = [{"address": a, "name": p["name"]} for a, p in self.pending.items()]
        return {"bluetooth": dict(self.bt), "connections": conns, "pending": pending,
                "location": self.location.snapshot()["valid"]}

    def status_changed(self):
        self._emit("StatusChanged", GLib.Variant("(s)", (json.dumps(self.status(), ensure_ascii=False),)))

    # ---- BlueZ ----
    def bluetooth_state(self, registered, error):
        self.bt.update(registered=registered, error=error,
                       available=bool(self.profile and self.profile.available))
        if registered:
            # i telefony schvalene drive (pred touto verzi nebo bez BlueZ) - BlueZ je pak nepta znovu
            for address, _name in self.settings.phones():
                self.set_trusted(address, True)
        if error:
            log("BlueZ profile registration failed:", error)
        self.status_changed()

    def new_connection(self, fd, peer, transport=None):
        """Nove spojeni RFCOMM (fd) od telefonu peer={"address","name"}."""
        peer = dict(peer, address=store.normalize_address(peer.get("address")) or "",
                    name=store.clean_name(peer.get("name"), peer.get("address", "")))
        self.check_settings()
        if transport is None:
            transport = session.FdTransport(fd)
        for old in list(self.sessions.values()):
            if old.peer["address"] == peer["address"]:
                old.close("replaced")
        s = session.Session(self, peer, transport, clock=self.clock)
        self.sessions[s.key] = s
        if hasattr(transport, "start"):
            transport.start(s)
        self._ensure_timer()
        self.status_changed()
        log("connection from", peer["address"])
        return s

    def set_trusted(self, address, trusted):
        """Duvera v BlueZ podle schvaleni v aplikaci: schvaleny telefon uz agent Bluetooth LuxOS
        pri dalsim spojeni nepta (druhy dotaz vedle nasho), odebrany zase ano."""
        if self.profile is not None and hasattr(self.profile, "set_trusted"):
            self.profile.set_trusted(address, trusted)

    def disconnect(self, address):
        a = store.normalize_address(address)
        for s in list(self.sessions.values()):
            if s.peer["address"] == a:
                s.close("disconnected")

    # ---- hub pro Session ----
    def make_luxai(self, send):
        return self.luxai_factory(send)

    def session_opened(self, s):
        log("phone connected:", s.peer["address"])
        self.status_changed()

    def session_closed(self, s):
        self.sessions.pop(s.key, None)
        self.location.drop(s.key)
        for p in self.pending.values():
            p["callbacks"] = [(ss, cb) for ss, cb in p["callbacks"] if ss is not s]
        log("connection closed:", s.peer["address"], s.close_reason)
        self.status_changed()

    def calendar_saved(self, s, title):
        if self.notifier:
            self.notifier.notify(_("Note from %s saved to Calendar") % s.peer["name"],
                                 GLib.markup_escape_text(title or ""))

    def authorize(self, s, callback):
        address, name = s.peer["address"], s.peer["name"]
        p = self.pending.get(address)
        if p is None:
            p = self.pending[address] = {"name": name, "callbacks": [], "nid": None}
            if self.notifier:
                p["nid"] = self.notifier.notify(
                    _("Allow “%s” to connect to LuxOS?") % name,
                    GLib.markup_escape_text(_(
                        "The phone %s (%s) wants to connect with the LuxOS Companion app. It will be able to "
                        "share its location with Maps, save notes to Calendar and send requests to LuxAI. "
                        "You can change this later in Settings › Phone.") % (name, address)),
                    ["deny", _("Deny"), "allow", _("Allow")], urgent=True, timeout=0,
                    callback=lambda key, a=address: self._approval_action(a, key))
        p["callbacks"].append((s, callback))
        self.status_changed()

    def _approval_action(self, address, key):
        if key in ("allow", "deny"):
            self.answer(address, key == "allow")
        elif key == "closed":
            self._approval_dismissed(address)
        else:
            # klik na oznameni: okno Telefon s cekajicim dotazem (dotaz plati dal)
            try:
                subprocess.Popen(["luxos-companion"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass

    def _approval_dismissed(self, address):
        p = self.pending.pop(address, None)
        if p:
            for _s, cb in p["callbacks"]:
                cb(False)
            self.status_changed()

    def answer(self, address, allow):
        a = store.normalize_address(address)
        p = self.pending.pop(a, None)
        if p is None:
            return
        if self.notifier and p.get("nid"):
            self.notifier.close(p["nid"])
        if allow:
            try:
                self.settings.approve(a, p["name"])
                self.approved = {x for x, _n in self.settings.phones()}
            except (OSError, ValueError) as e:
                log("cannot save approval:", e)
                allow = False
            if allow:
                self.set_trusted(a, True)
        waiting = p["callbacks"]
        for _s, cb in waiting:
            cb(allow)
        if allow and not waiting and self.notifier:
            self.notifier.notify(_("“%s” is allowed") % p["name"],
                                 GLib.markup_escape_text(_("Connect again from the phone.")))
        self.status_changed()

    # ---- nastaveni ----
    def check_settings(self):
        """companion.json zmeneny jinde (okno Telefon, rucni uprava): nacist znovu (stat, bez inotify)."""
        try:
            st = os.stat(self.settings.path)
            stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            stamp = None
        if stamp != self.settings_stamp:
            self.settings_stamp = stamp
            self.reload_settings()

    def reload_settings(self):
        self.settings.reload()
        approved = {a for a, _n in self.settings.phones()}
        for a in sorted(self.approved - approved):     # odebrany v okne Telefon nebo rucne
            self.set_trusted(a, False)
        self.approved = approved
        if self.location.enabled != self.settings.get("share_location"):
            self.location.set_enabled(self.settings.get("share_location"))
        for s in list(self.sessions.values()):
            if s.state == "open" and not self.settings.is_approved(s.peer["address"]):
                s.close("revoked")
        self.status_changed()

    # ---- casovac ----
    def _ensure_timer(self):
        if self.timer is None:
            self.timer = GLib.timeout_add(1000, self.tick)

    def tick(self):
        self.check_settings()
        for s in list(self.sessions.values()):
            s.tick()
        self.location.check()
        if not self.sessions:
            self.timer = None
            return False
        return True


def run():
    """Vstup sluzby (luxos-companion --service)."""
    from . import bluez
    loop = GLib.MainLoop()
    try:
        sbus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as e:
        log("no session bus:", e.message)
        return 1
    svc = Service(sbus)
    svc.export()
    state = {"owned": None, "profile": None}

    def acquired(_c, _n):
        state["owned"] = True
        # profil v BlueZ az po ziskani jmena: druha instance nesmi odregistrovat profil te prvni
        try:
            profile = bluez.BluezProfile(bluez.bluez_bus(), svc.new_connection, svc.disconnect,
                                         svc.bluetooth_state)
            svc.profile = state["profile"] = profile
            profile.start()
        except GLib.Error as e:
            log("no system bus:", e.message)
            svc.bt["error"] = e.message

    def lost(_c, _n):
        if state["owned"] is None:
            log("already running")
        state["owned"] = False
        loop.quit()
    own_id = Gio.bus_own_name_on_connection(sbus, BUS_NAME, Gio.BusNameOwnerFlags.DO_NOT_QUEUE, acquired, lost)
    for sig in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: loop.quit() or False)
    loop.run()
    for s in list(svc.sessions.values()):
        s.close("shutdown")
    if state["profile"] is not None:
        state["profile"].stop()
    Gio.bus_unown_name(own_id)
    svc.unexport()
    return 0
