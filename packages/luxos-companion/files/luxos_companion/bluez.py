"""Profil RFCOMM LuxOS Companion v BlueZ (org.bluez.ProfileManager1.RegisterProfile).

Role server, RequireAuthentication + RequireAuthorization, AutoConnect false: BlueZ vlozi zaznam SDP
s UUID sluzby, prijme sifrovane spojeni od sparovaneho telefonu a preda socket pres NewConnection.
Viditelnost adapteru (discoverable) se nemeni - telefon se paruje v nastaveni Bluetooth.
Po restartu bluetoothd (zmizi a znovu se objevi org.bluez) se profil zaregistruje znovu.
Schvaleny telefon dostane v BlueZ Device1.Trusted=true (dalsi spojeni uz nevyvola dotaz agenta
Bluetooth LuxOS), po odebrani Trusted=false.
LUXOS_COMPANION_BLUEZ_BUS: adresa jine sbernice nez systemove (testy s falesnym BlueZ).
"""
import os
import re

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import SERVICE_UUID  # noqa: E402

BLUEZ = "org.bluez"
PROFILE_PATH = "/cz/luxos/companion/profile"
# Pevny kanal RFCOMM a vlastni zaznam SDP: bez nich BlueZ pro vlastni UUID zverejni zaznam, ve kterem
# Android nenajde kanal (bt_btif_sock_rfcomm: "SDP service discovery ... FAILURE, scn: 0") a telefon
# se nepripoji ("read failed, socket might closed or timeout")
RFCOMM_CHANNEL = 22


def sdp_record(uuid=SERVICE_UUID, channel=RFCOMM_CHANNEL, name="LuxOS Companion"):
    """Zaznam SDP jako u SPP: trida sluzby = UUID, L2CAP + RFCOMM kanal, verejna skupina prochazeni."""
    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<record>
  <attribute id="0x0001"><sequence><uuid value="{uuid}" /></sequence></attribute>
  <attribute id="0x0004"><sequence>
    <sequence><uuid value="0x0100" /></sequence>
    <sequence><uuid value="0x0003" /><uint8 value="0x{channel:02x}" /></sequence>
  </sequence></attribute>
  <attribute id="0x0005"><sequence><uuid value="0x1002" /></sequence></attribute>
  <attribute id="0x0100"><text value="{name}" /></attribute>
</record>"""
PROFILE_XML = """
<node>
  <interface name="org.bluez.Profile1">
    <method name="Release"/>
    <method name="NewConnection">
      <arg name="device" type="o" direction="in"/>
      <arg name="fd" type="h" direction="in"/>
      <arg name="fd_properties" type="a{sv}" direction="in"/>
    </method>
    <method name="RequestDisconnection">
      <arg name="device" type="o" direction="in"/>
    </method>
  </interface>
</node>
"""
DEV_RE = re.compile(r"/dev_([0-9A-Fa-f]{2}(?:_[0-9A-Fa-f]{2}){5})$")


def bluez_bus():
    addr = os.environ.get("LUXOS_COMPANION_BLUEZ_BUS")
    if addr:
        return Gio.DBusConnection.new_for_address_sync(
            addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
    return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


def address_from_path(path):
    m = DEV_RE.search(path or "")
    return m.group(1).replace("_", ":").upper() if m else ""


class BluezProfile:
    """on_connection(fd, peer) dostane vlastni fd socketu; on_disconnect(address) pri RequestDisconnection.
    on_state(registered: bool, error: str|None) pri zmene registrace."""

    def __init__(self, bus, on_connection, on_disconnect=None, on_state=None):
        self.bus = bus
        self.on_connection = on_connection
        self.on_disconnect = on_disconnect
        self.on_state = on_state
        self.reg_id = None
        self.watch_id = None
        self.registered = False
        self.error = None
        self.available = False
        self.owner = None            # unikatni jmeno bluetoothd - jen ten smi volat Profile1

    def start(self):
        info = Gio.DBusNodeInfo.new_for_xml(PROFILE_XML)
        self.reg_id = self.bus.register_object(PROFILE_PATH, info.interfaces[0], self._on_call, None, None)
        self.watch_id = Gio.bus_watch_name_on_connection(self.bus, BLUEZ, Gio.BusNameWatcherFlags.NONE,
                                                         self._appeared, self._vanished)

    def stop(self):
        if self.watch_id is not None:
            Gio.bus_unwatch_name(self.watch_id)
            self.watch_id = None
        if self.registered:
            try:
                self.bus.call_sync(BLUEZ, "/org/bluez", "org.bluez.ProfileManager1", "UnregisterProfile",
                                   GLib.Variant("(o)", (PROFILE_PATH,)), None, Gio.DBusCallFlags.NONE, 2000, None)
            except GLib.Error:
                pass
            self.registered = False
        if self.reg_id is not None:
            self.bus.unregister_object(self.reg_id)
            self.reg_id = None

    def _set_state(self, registered, error=None):
        self.registered = registered
        self.error = error
        if self.on_state:
            self.on_state(registered, error)

    def _appeared(self, _bus, _name, owner):
        self.available = True
        self.owner = owner
        opts = {
            "Name": GLib.Variant("s", "LuxOS Companion"),
            "Role": GLib.Variant("s", "server"),
            "RequireAuthentication": GLib.Variant("b", True),
            "RequireAuthorization": GLib.Variant("b", True),
            "AutoConnect": GLib.Variant("b", False),
            "Channel": GLib.Variant("q", RFCOMM_CHANNEL),
            "ServiceRecord": GLib.Variant("s", sdp_record()),
        }

        def done(bus, res, _data):
            try:
                bus.call_finish(res)
            except GLib.Error as e:
                if "AlreadyExists" in (e.message or ""):
                    self._set_state(True)
                else:
                    self._set_state(False, e.message)
                return
            self._set_state(True)
        self.bus.call(BLUEZ, "/org/bluez", "org.bluez.ProfileManager1", "RegisterProfile",
                      GLib.Variant("(osa{sv})", (PROFILE_PATH, SERVICE_UUID, opts)), None,
                      Gio.DBusCallFlags.NONE, 10000, None, done, None)

    def _vanished(self, _bus, _name):
        self.available = False
        self.owner = None
        self._set_state(False, None)

    def _on_call(self, _bus, sender, _path, _iface, method, params, invocation):
        if not self.owner or sender != self.owner:
            # socket smi predat jen BlueZ (jinak by kdokoli na sbernici mohl podvrhnout "telefon")
            invocation.return_dbus_error("org.freedesktop.DBus.Error.AccessDenied", "only BlueZ may call this")
            return
        if method == "Release":
            self._set_state(False, None)
            invocation.return_value(None)
        elif method == "NewConnection":
            device, idx, _props = params.unpack()
            fds = invocation.get_message().get_unix_fd_list()
            fd = -1
            try:
                if fds is not None:
                    fd = fds.get(idx)           # vlastni kopie (dup)
            except GLib.Error:
                fd = -1
            if fd < 0:
                invocation.return_dbus_error("org.bluez.Error.Rejected", "no socket")
                return
            invocation.return_value(None)
            self._device_info(device, fd)
        elif method == "RequestDisconnection":
            device = params.unpack()[0]
            invocation.return_value(None)
            if self.on_disconnect:
                self.on_disconnect(address_from_path(device))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def set_trusted(self, address, trusted, done=None):
        """org.bluez.Device1.Trusted vsech zarizeni s adresou (kazdy adapter ma vlastni objekt).
        Meni se jen rozdilna hodnota; bez BlueZ nic. done(pocet zmenenych) po dokonceni."""
        address = (address or "").upper()
        if not self.available or not address:
            if done:
                done(0)
            return

        def got(bus, res, _data):
            try:
                objects = bus.call_finish(res).unpack()[0]
            except GLib.Error:
                objects = {}
            paths = [path for path, ifaces in objects.items()
                     if str(ifaces.get("org.bluez.Device1", {}).get("Address", "")).upper() == address
                     and bool(ifaces["org.bluez.Device1"].get("Trusted")) != trusted]
            left = [len(paths)]
            if not paths and done:
                done(0)

            def set_done(bus, res, _data):
                try:
                    bus.call_finish(res)
                except GLib.Error:
                    pass
                left[0] -= 1
                if left[0] == 0 and done:
                    done(len(paths))
            for path in paths:
                bus.call(BLUEZ, path, "org.freedesktop.DBus.Properties", "Set",
                         GLib.Variant("(ssv)", ("org.bluez.Device1", "Trusted", GLib.Variant("b", trusted))),
                         None, Gio.DBusCallFlags.NONE, 3000, None, set_done, None)
        self.bus.call(BLUEZ, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects", None,
                      GLib.VariantType.new("(a{oa{sa{sv}}})"), Gio.DBusCallFlags.NONE, 3000, None, got, None)

    def _device_info(self, device, fd):
        """Adresa a jmeno telefonu z org.bluez.Device1; nesparovane zarizeni se odmitne."""
        def done(bus, res, _data):
            peer = {"address": address_from_path(device), "name": "", "path": device}
            paired = None
            try:
                props = bus.call_finish(res).unpack()[0]
                peer["address"] = str(props.get("Address") or peer["address"]).upper()
                peer["name"] = str(props.get("Alias") or props.get("Name") or "")
                paired = props.get("Paired")
            except GLib.Error:
                pass
            if paired is False or not peer["address"]:
                try:
                    os.close(fd)
                except OSError:
                    pass
                return
            self.on_connection(fd, peer)
        self.bus.call(BLUEZ, device, "org.freedesktop.DBus.Properties", "GetAll",
                      GLib.Variant("(s)", ("org.bluez.Device1",)), None, Gio.DBusCallFlags.NONE, 3000, None,
                      done, None)
