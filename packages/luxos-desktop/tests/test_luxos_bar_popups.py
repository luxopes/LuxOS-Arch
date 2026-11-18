#!/usr/bin/env python3
"""LuxOS - vyskakovaci okna horni listy Wi-Fi, Zvuk a Oznameni (files/lsl/luxos_bar_popups.lsl).

    xvfb-run -a dbus-run-session -- python3 -m unittest packages/luxos-desktop/tests/test_luxos_bar_popups.py -v

Vsechno proti napodobeninam: nmcli, pactl a xfconf-query jsou skripty, ktere zapisuji sva volani;
NetworkManager (systemova sbernice) a historie xfce4-notifyd (org.xfce.Notifyd.Log) jsou falesne
sluzby D-Bus na vlastnich sbernicich. Skutecna sit, zvuk ani oznameni se nemeni. Okna jen pod Xvfb.
Polohy tlacitek zapisuje okno s LUXOS_BAR_POPUP_TEST_LOG ("pos jmeno x y").
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "lsl", "luxos-bar-popup.lsl")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")
BIN = tempfile.mkdtemp(prefix="luxos-bar-popup-bin-")


def build():
    if not LSLC:
        return False
    r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", SRC, os.path.join(BIN, "luxos-bar-popup")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(r.stderr + r.stdout)
    return True


BUILT = build()

FAKE_NMCLI = r'''#!/bin/sh
echo "nmcli $*" >> "$FAKE_LOG"
S="$FAKE_STATE"
case "$*" in
  "-t -f WIFI general") cat "$S/radio" ;;
  "-t -f DEVICE,TYPE device") printf 'wlan0:wifi\nlo:loopback\n' ;;
  "-t -f STATE,CONNECTIVITY general") echo "connected:$(cat "$S/connectivity" 2>/dev/null || echo full)" ;;
  "-t -f CONNECTIVITY general") cat "$S/connectivity" 2>/dev/null || echo full ;;
  "-t -f IN-USE,SSID,SIGNAL,SECURITY device wifi list --rescan no"|"-t -f IN-USE,SSID,SIGNAL device wifi list --rescan no")
    printf '*:Domov:82:WPA2\n :Kavarna:61:\n :Soused\\:5G:70:WPA2\n :Firma:55:WPA2 802.1X\n :Domov:40:WPA2\n :Nova sit:75:WPA2\n' ;;
  "-t -f NAME,TYPE connection show") printf 'Domov:802-11-wireless\nKavarna:802-11-wireless\n' ;;
  "radio wifi off") echo disabled > "$S/radio" ;;
  "radio wifi on") echo enabled > "$S/radio" ;;
  *) ;;
esac
exit 0
'''

FAKE_PACTL = r'''#!/bin/sh
echo "pactl $*" >> "$FAKE_LOG"
case "$*" in
  "-f json list sinks") cat <<'J'
[{"name":"speakers","description":"Reproduktory","mute":false,"volume":{"front-left":{"value_percent":"40%"},"front-right":{"value_percent":"44%"}}},
 {"name":"hdmi","description":"Monitor HDMI","mute":false,"volume":{"mono":{"value_percent":"70%"}}}]
J
  ;;
  "-f json list sources") cat <<'J'
[{"name":"speakers.monitor","description":"Monitor of Reproduktory","mute":false,"monitor_of_sink":"speakers","volume":{"mono":{"value_percent":"100%"}}},
 {"name":"mic","description":"Vestaveny mikrofon","mute":true,"volume":{"mono":{"value_percent":"30%"}}}]
J
  ;;
  "get-default-sink") echo speakers ;;
  "get-default-source") echo mic ;;
esac
exit 0
'''

FAKE_XFCONF = r'''#!/bin/sh
echo "xfconf-query $*" >> "$FAKE_LOG"
case "$*" in
  *do-not-disturb*-s*) ;;
  *do-not-disturb*) echo false ;;
esac
exit 0
'''

# Falesny NetworkManager (systemova sbernice) a historie oznameni (sezeni) - zapisuji volani do JSON
FAKE_SERVICES = r'''
import json, sys
from gi.repository import Gio, GLib
log = sys.argv[1]
def record(entry):
    with open(log, "a") as f:
        f.write(json.dumps(entry) + "\n")
NM_XML = """<node><interface name='org.freedesktop.NetworkManager'>
<method name='GetDeviceByIpIface'><arg type='s' direction='in'/><arg type='o' direction='out'/></method>
<method name='AddAndActivateConnection'><arg type='a{sa{sv}}' direction='in'/><arg type='o' direction='in'/>
<arg type='o' direction='in'/><arg type='o' direction='out'/><arg type='o' direction='out'/></method>
</interface></node>"""
LOG_XML = """<node><interface name='org.xfce.Notifyd.Log'>
<method name='List'><arg type='s' direction='in'/><arg type='u' direction='in'/><arg type='b' direction='in'/>
<arg type='a(sxssssssa(ss)ib)' direction='out'/></method>
<method name='MarkAllRead'/><method name='Clear'/>
<method name='Delete'><arg type='as' direction='in'/></method>
</interface></node>"""
HISTORY_XML = """<node><interface name='cz.luxos.NotificationHistory'>
<method name='Activate'><arg type='s' direction='in'/><arg type='b' direction='out'/></method>
</interface></node>"""
now = GLib.get_real_time()
ENTRIES = [("n1", now - 30 * 1000000, "UTC", "clock", "Clock", "alarm-symbolic", "Budik", "Prace 07:00", [], 0, False),
           ("n2", now - 7200 * 1000000, "UTC", "luxos", "LuxOS", "", "Aktualizace", "Restartujte pocitac", [], 0, True)]
def nm_call(conn, sender, path, iface, method, params, inv):
    if method == "GetDeviceByIpIface":
        record({"nm": method, "iface": params.unpack()[0]})
        inv.return_value(GLib.Variant("(o)", ("/org/freedesktop/NetworkManager/Devices/7",)))
    else:
        settings, dev, ap = params.unpack()
        record({"nm": method, "settings": settings, "device": dev, "ap": ap})
        inv.return_value(GLib.Variant("(oo)", ("/org/freedesktop/NetworkManager/Settings/9", "/org/freedesktop/NetworkManager/ActiveConnection/9")))
def log_call(conn, sender, path, iface, method, params, inv):
    record({"log": method, "args": params.unpack() if params is not None else None})
    if method == "List":
        inv.return_value(GLib.Variant("(a(sxssssssa(ss)ib))", (ENTRIES,)))
    else:
        inv.return_value(None)
system = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
system.register_object("/org/freedesktop/NetworkManager", Gio.DBusNodeInfo.new_for_xml(NM_XML).interfaces[0], nm_call, None, None)
Gio.bus_own_name_on_connection(system, "org.freedesktop.NetworkManager", 0, None, None)
session = Gio.bus_get_sync(Gio.BusType.SESSION, None)
session.register_object("/org/xfce/Notifyd", Gio.DBusNodeInfo.new_for_xml(LOG_XML).interfaces[0], log_call, None, None)
# modul luxos-notifyd v xfce4-notifyd: n1 (Budik) aplikace jeste prevezme, n2 uz ne
def history_call(conn, sender, path, iface, method, params, inv):
    record({"history": method, "args": params.unpack()})
    inv.return_value(GLib.Variant("(b)", (params.unpack()[0] == "n1",)))
session.register_object("/cz/luxos/NotificationHistory", Gio.DBusNodeInfo.new_for_xml(HISTORY_XML).interfaces[0],
                        history_call, None, None)
Gio.bus_own_name_on_connection(session, "org.freedesktop.Notifications", 0, None, None)
Gio.bus_own_name_on_connection(session, "org.xfce.Notifyd", 0, None, None)
print("ready", flush=True)
GLib.MainLoop().run()
'''


FAKE_XFCONF_JSON = r'''#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_XFCONF"]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write("xfconf-query " + " ".join(sys.argv[1:]) + "\n")
data = json.load(open(path))
a = sys.argv[1:]
prop, values, lst, force_array, i = None, [], False, False, 0
while i < len(a):
    if a[i] == "-c": i += 1
    elif a[i] == "-p": prop = a[i + 1]; i += 1
    elif a[i] == "-l": lst = True
    elif a[i] == "-s": values.append(a[i + 1]); i += 1
    elif a[i] == "-t": i += 1
    elif a[i] == "--force-array": force_array = True
    i += 1
if lst:
    for k in sorted(data):
        if prop is None or k == prop or k.startswith(prop + "/"):
            print(k)
    sys.exit(0)
if values:
    data[prop] = values if (force_array or len(values) > 1) else values[0]
    json.dump(data, open(path, "w"))
    sys.exit(0)
if prop not in data:
    print('Property "%s" does not exist on channel "xfce4-panel".' % prop, file=sys.stderr)
    sys.exit(1)
v = data[prop]
if isinstance(v, list):
    print("Value is an array with %d items:\n" % len(v))
    for x in v:
        print(x)
else:
    print(v)
'''


@unittest.skipUnless(BUILT, "needs lslc with the linux-x86_64-gnu target")
class PanelMigration(unittest.TestCase):
    """Starsi profil: ikona Wi-Fi LuxOS za ikony (systray), nm-applet v systray skryty - jen jednou."""
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxos-bar-migrate-")
        self.addCleanup(shutil.rmtree, self.t, True)
        fake = os.path.join(self.t, "fake")
        os.makedirs(fake)
        for name, body in (("xfconf-query", FAKE_XFCONF_JSON), ("xfce4-panel", '#!/bin/sh\necho "xfce4-panel $*" >> "$FAKE_LOG"\n')):
            p = os.path.join(fake, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        self.channel = os.path.join(self.t, "panel.json")
        self.log = os.path.join(self.t, "log")
        self.env = dict(os.environ, PATH=fake + ":" + os.environ["PATH"], FAKE_XFCONF=self.channel, FAKE_LOG=self.log,
                        XDG_CONFIG_HOME=os.path.join(self.t, "config"))

    def write(self, data):
        with open(self.channel, "w") as f:
            json.dump(data, f)

    def channel_data(self):
        with open(self.channel) as f:
            return json.load(f)

    def migrate(self):
        r = subprocess.run([os.path.join(BIN, "luxos-bar-popup"), "--migrate-panel"], env=self.env,
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        time.sleep(0.3)

    def old_profile(self, **extra):
        data = {"/panels": ["1"], "/panels/panel-1/plugin-ids": ["1", "4", "14", "5", "7"],
                "/plugins/plugin-1": "whiskermenu", "/plugins/plugin-4": "systray", "/plugins/plugin-14": "genmon",
                "/plugins/plugin-14/command": "luxos-netcheck", "/plugins/plugin-5": "pulseaudio",
                "/plugins/plugin-7": "notification-plugin"}
        data.update(extra)
        self.write(data)

    def test_adds_wifi_after_tray_and_hides_nm_applet_once(self):
        self.old_profile(**{"/plugins/plugin-4/hidden-items": ["steam"]})
        self.migrate()
        d = self.channel_data()
        self.assertEqual(d["/panels/panel-1/plugin-ids"], ["1", "4", "15", "14", "5", "7"])
        self.assertEqual(d["/plugins/plugin-15"], "genmon")
        self.assertEqual(d["/plugins/plugin-15/command"], "luxos-bar-popup --panel wifi")
        self.assertEqual(d["/plugins/plugin-4/hidden-items"], ["steam", "nm-applet"])
        self.assertIn("xfce4-panel -r", self.read_log())
        self.migrate()
        self.assertEqual(self.channel_data(), d, "podruhe nic")
        self.assertEqual(self.read_log().count("xfce4-panel -r"), 1)

    def test_removed_icon_stays_removed(self):
        self.old_profile()
        self.migrate()
        d = self.channel_data()
        d["/panels/panel-1/plugin-ids"] = ["1", "4", "14", "5", "7"]
        del d["/plugins/plugin-15"], d["/plugins/plugin-15/command"]
        self.write(d)
        self.migrate()
        self.assertEqual(self.channel_data(), d, "uzivatel ikonu odebral: nevracet")

    def test_profile_without_tray_untouched(self):
        self.write({"/panels": ["1"], "/panels/panel-1/plugin-ids": ["1", "8"], "/plugins/plugin-1": "whiskermenu",
                    "/plugins/plugin-8": "genmon", "/plugins/plugin-8/command": "luxos-clock"})
        before = self.channel_data()
        self.migrate()
        self.assertEqual(self.channel_data(), before)
        self.assertNotIn("xfce4-panel -r", self.read_log())

    def test_keyboard_flag_becomes_text_once(self):
        # vlajka z pluginu xkb -> plugin luxos-xkb (US, CZ) na stejnem miste; nastaveni xkb nevadi
        self.old_profile(**{"/panels/panel-1/plugin-ids": ["1", "11", "4", "14", "5", "7"], "/plugins/plugin-11": "xkb",
                            "/plugins/plugin-11/display-type": "0"})
        self.migrate()
        d = self.channel_data()
        self.assertEqual(d["/plugins/plugin-11"], "luxos-xkb")
        self.assertEqual(d["/panels/panel-1/plugin-ids"][:2], ["1", "11"], "stejne misto v liste")
        self.assertIn("xfce4-panel -r", self.read_log())
        # uzivatel si vlajku vratil: podruhe nic
        d["/plugins/plugin-11"] = "xkb"
        self.write(d)
        runs = self.read_log().count("xfce4-panel -r")
        self.migrate()
        self.assertEqual(self.channel_data()["/plugins/plugin-11"], "xkb")
        self.assertEqual(self.read_log().count("xfce4-panel -r"), runs)

    def read_log(self):
        try:
            with open(self.log) as f:
                return f.read()
        except OSError:
            return ""


@unittest.skipUnless(BUILT, "needs lslc with the linux-x86_64-gnu target")
@unittest.skipUnless(UNDER_XVFB, "GUI only under xvfb-run (never on a real display)")
class BarPopups(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxos-bar-popup-")
        self.addCleanup(shutil.rmtree, self.t, True)
        fake, state, run = (os.path.join(self.t, d) for d in ("fake", "state", "run"))
        for d in (fake, state, run):
            os.makedirs(d)
        os.chmod(run, 0o700)
        for name, body in (("nmcli", FAKE_NMCLI), ("pactl", FAKE_PACTL), ("xfconf-query", FAKE_XFCONF),
                           ("luxos-network-login", '#!/bin/sh\necho "luxos-network-login $*" >> "$FAKE_LOG"\n'),
                           ("nm-connection-editor", '#!/bin/sh\necho "nm-connection-editor $*" >> "$FAKE_LOG"\n'),
                           ("gtk-launch", '#!/bin/sh\necho "gtk-launch $*" >> "$FAKE_LOG"\n')):
            p = os.path.join(fake, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        with open(os.path.join(state, "radio"), "w") as f:
            f.write("enabled\n")
        self.calls = os.path.join(self.t, "calls")
        self.dbus = os.path.join(self.t, "dbus.json")
        self.testlog = os.path.join(self.t, "test.log")
        self.procs = []
        # vlastni "systemova" sbernice pro falesny NetworkManager
        sysbus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address"],
                                  stdout=subprocess.PIPE, text=True)
        self.procs.append(sysbus)
        address = sysbus.stdout.readline().strip()
        # vlastni sbernice sezeni s vlastnim xfconfd nad docasnou konfiguraci: xfconfd spusteny
        # sbernici z dbus-run-session by cetl a zapisoval ~/.config uzivatele (okno Zvuk meni volbu listy)
        session = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address"],
                                   stdout=subprocess.PIPE, text=True)
        self.procs.append(session)
        self.session_address = session.stdout.readline().strip()
        self.env = dict(os.environ, PATH=fake + ":" + os.environ["PATH"], FAKE_LOG=self.calls, FAKE_STATE=state,
                        XDG_RUNTIME_DIR=run, XDG_CONFIG_HOME=os.path.join(self.t, "config"),
                        DBUS_SYSTEM_BUS_ADDRESS=address, DBUS_SESSION_BUS_ADDRESS=self.session_address,
                        LUXOS_BAR_POPUP_TEST_LOG=self.testlog,
                        LUXOS_HUB_NO_AUTOHIDE="1", LANG="C", NO_AT_BRIDGE="1", GIO_USE_VFS="local")
        xfconfd = subprocess.Popen(["/usr/lib/xfce4/xfconf/xfconfd"], env=self.env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(xfconfd)
        self.assertTrue(self.wait_for(self.xfconfd_ready), "vlastni xfconfd")
        services = os.path.join(self.t, "services.py")
        with open(services, "w") as f:
            f.write(FAKE_SERVICES)
        svc = subprocess.Popen([sys.executable, services, self.dbus], env=self.env, stdout=subprocess.PIPE, text=True)
        self.procs.append(svc)
        self.assertEqual(svc.stdout.readline().strip(), "ready")

    def session_conn(self):
        from gi.repository import Gio
        if not hasattr(self, "_conn"):
            self._conn = Gio.DBusConnection.new_for_address_sync(
                self.session_address,
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        return self._conn

    def xfconfd_ready(self):
        from gi.repository import GLib
        r = self.session_conn().call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                          "NameHasOwner", GLib.Variant("(s)", ("org.xfce.Xfconf",)), None, 0, 2000, None)
        return r.unpack()[0]

    def tearDown(self):
        for p in reversed(self.procs):
            try:
                os.killpg(p.pid, signal.SIGTERM) if getattr(p, "group", False) else p.terminate()
            except ProcessLookupError:
                pass
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()

    # ---- pomucky ----
    def popup(self, *args):
        p = subprocess.Popen([os.path.join(BIN, "luxos-bar-popup"), *args], env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        p.group = True
        self.procs.append(p)
        return p

    def run_popup(self, *args):
        return subprocess.run([os.path.join(BIN, "luxos-bar-popup"), *args], env=self.env,
                              capture_output=True, text=True, timeout=20)

    def read(self, path):
        try:
            with open(path) as f:
                return f.read()
        except OSError:
            return ""

    def wait_for(self, check, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            if check():
                return True
            time.sleep(0.1)
        return check()

    def positions(self):
        pos = {}
        for line in self.read(self.testlog).splitlines():
            parts = line.split(" ")
            if parts[0] == "pos" and len(parts) >= 4:
                pos[" ".join(parts[1:-2])] = (int(parts[-2]), int(parts[-1]))
        return pos

    def click(self, name):
        self.assertTrue(self.wait_for(lambda: name in self.positions()), (name, self.read(self.testlog)[-600:]))
        x, y = self.positions()[name]
        subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "1"], check=True)
        time.sleep(0.6)

    def dbus_calls(self):
        return [json.loads(line) for line in self.read(self.dbus).splitlines() if line.strip()]

    def shown(self, kind):
        return self.wait_for(lambda: "shown " + kind in self.read(self.testlog))

    # ---- testy ----
    def test_panel_icon_wifi(self):
        r = self.run_popup("--panel", "wifi")
        self.assertEqual(r.returncode, 0, r.stderr)
        # klik spusti tentyz program plnou cestou (lista ze sezeni nemusi mit jeho slozku v PATH)
        self.assertEqual(r.stdout.strip(), "<icon>network-wireless-signal-excellent-symbolic</icon>"
                         "<iconclick>" + os.path.join(BIN, "luxos-bar-popup") + " wifi</iconclick><tool>Domov</tool>")
        with open(os.path.join(self.t, "state", "radio"), "w") as f:
            f.write("disabled\n")
        r = self.run_popup("--panel", "wifi")
        self.assertIn("<icon>network-wireless-offline-symbolic</icon>", r.stdout)
        self.assertEqual(self.run_popup("nonsense").returncode, 2)
        # za prihlasovaci strankou: ikona bez internetu, klik otevre prihlaseni do site
        with open(os.path.join(self.t, "state", "radio"), "w") as f:
            f.write("enabled\n")
        with open(os.path.join(self.t, "state", "connectivity"), "w") as f:
            f.write("portal\n")
        r = self.run_popup("--panel", "wifi")
        self.assertIn("<icon>network-wireless-no-route-symbolic</icon><iconclick>luxos-network-login</iconclick>", r.stdout)
        self.assertIn("Sign in to the network", r.stdout)

    def test_wifi_networks_known_and_new_secured(self):
        self.popup("wifi")
        self.assertTrue(self.shown("wifi"))
        self.assertTrue(self.wait_for(lambda: "wifi:Nova sit" in self.positions()), self.read(self.testlog))
        pos = self.positions()
        # jedna polozka na SSID, pripojena nahore, ostatni podle signalu; "\:" v SSID je dvojtecka
        order = sorted((y, n) for n, (x, y) in pos.items() if n.startswith("wifi:"))
        self.assertEqual([n for _, n in order], ["wifi:Domov", "wifi:Nova sit", "wifi:Soused:5G", "wifi:Kavarna", "wifi:Firma"])
        # znama sit: NetworkManager ji pripoji podle ulozeneho profilu
        self.click("wifi:Kavarna")
        self.assertTrue(self.wait_for(lambda: "nmcli --wait 30 device wifi connect Kavarna" in self.read(self.calls)))
        # nova zabezpecena sit: pole pro heslo, heslo jde NetworkManageru po D-Bus
        self.click("wifi:Nova sit")
        self.click("wifi-entry")
        subprocess.run(["xdotool", "type", "--delay", "30", "tajneheslo1"], check=True)
        self.click("wifi-join")
        self.assertTrue(self.wait_for(lambda: any(c.get("nm") == "AddAndActivateConnection" for c in self.dbus_calls())),
                        self.read(self.calls))
        add = [c for c in self.dbus_calls() if c.get("nm") == "AddAndActivateConnection"][0]
        s = add["settings"]
        self.assertEqual(bytes(s["802-11-wireless"]["ssid"]).decode(), "Nova sit")
        self.assertEqual(s["802-11-wireless-security"], {"key-mgmt": "wpa-psk", "psk": "tajneheslo1"})
        self.assertEqual(add["device"], "/org/freedesktop/NetworkManager/Devices/7")
        self.assertIn({"nm": "GetDeviceByIpIface", "iface": "wlan0"}, self.dbus_calls())
        self.assertNotIn("tajneheslo1", self.read(self.calls), "heslo nikdy v argumentech nmcli")

    def test_wifi_list_immediately_from_cache_and_portal_sign_in(self):
        # seznam hned z mezipameti (bez skryteho hledani v "nmcli wifi list"), za portalem tlacitko prihlaseni
        with open(os.path.join(self.t, "state", "connectivity"), "w") as f:
            f.write("portal\n")
        self.popup("wifi")
        self.assertTrue(self.shown("wifi"))
        self.assertTrue(self.wait_for(lambda: "wifi:Domov" in self.positions()), self.read(self.testlog))
        listing = [l for l in self.read(self.calls).splitlines() if "device wifi list" in l]
        self.assertTrue(listing and all("--rescan no" in l for l in listing), listing)
        self.click("wifi-portal")
        self.assertTrue(self.wait_for(lambda: "luxos-network-login" in self.read(self.calls)), self.read(self.calls))

    def test_wifi_rescan_button(self):
        self.popup("wifi")
        self.assertTrue(self.shown("wifi"))
        self.assertTrue(self.wait_for(lambda: "nmcli device wifi rescan" in self.read(self.calls)), "hledani pri otevreni")
        time.sleep(0.5)
        self.click("wifi-rescan")
        self.assertTrue(self.wait_for(lambda: self.read(self.calls).count("nmcli device wifi rescan") == 2),
                        self.read(self.calls))

    def test_wifi_short_password_and_switch_off(self):
        self.popup("wifi")
        self.assertTrue(self.shown("wifi"))
        self.click("wifi:Nova sit")
        self.click("wifi-entry")
        subprocess.run(["xdotool", "type", "abc"], check=True)
        self.click("wifi-join")
        time.sleep(0.5)
        self.assertFalse(any(c.get("nm") == "AddAndActivateConnection" for c in self.dbus_calls()), "kratke heslo neodeslat")
        self.click("wifi-switch")
        self.assertTrue(self.wait_for(lambda: "nmcli radio wifi off" in self.read(self.calls)))

    def test_sound_devices_and_mute(self):
        self.popup("sound")
        self.assertTrue(self.shown("sound"))
        self.assertTrue(self.wait_for(lambda: "sink:hdmi" in self.positions()), self.read(self.testlog))
        pos = self.positions()
        self.assertIn("sink:speakers", pos)
        self.assertNotIn("source:speakers.monitor", pos, "monitor vystupu neni mikrofon")
        self.assertNotIn("source:mic", pos, "jediny mikrofon: bez seznamu")
        self.click("sink:hdmi")
        self.assertTrue(self.wait_for(lambda: "pactl set-default-sink hdmi" in self.read(self.calls)))
        self.click("mute:sink")
        self.assertTrue(self.wait_for(lambda: "pactl set-sink-mute @DEFAULT_SINK@ 1" in self.read(self.calls)))
        # mikrofon je ztlumeny: klik ho zapne
        self.click("mute:source")
        self.assertTrue(self.wait_for(lambda: "pactl set-source-mute @DEFAULT_SOURCE@ 0" in self.read(self.calls)))

    def window_position(self):
        out = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "luxos-bar-popup"],
                             capture_output=True, text=True).stdout.split()
        self.assertTrue(out, "okno")
        g = subprocess.run(["xdotool", "getwindowgeometry", "--shell", out[-1]], capture_output=True, text=True).stdout
        d = dict(line.split("=", 1) for line in g.split() if "=" in line)
        return int(d["X"]), int(d["Y"])

    def test_volume_bubble_off_while_sound_window_open(self):
        from gi.repository import GLib

        def call(method, sig, args):
            return self.session_conn().call_sync("org.xfce.Xfconf", "/org/xfce/Xfconf", "org.xfce.Xfconf", method,
                                                 GLib.Variant(sig, args), None, 0, 5000, None).unpack()
        # plugin zvuku v liste s bublinou hlasitosti (docasna konfigurace testu)
        call("SetProperty", "(ssv)", ("xfce4-panel", "/plugins/plugin-5", GLib.Variant("s", "pulseaudio")))
        call("SetProperty", "(ssv)", ("xfce4-panel", "/plugins/plugin-5/show-notifications", GLib.Variant("b", True)))
        osd = lambda: call("GetProperty", "(ss)", ("xfce4-panel", "/plugins/plugin-5/show-notifications"))[0]
        p = self.popup("sound")
        self.assertTrue(self.shown("sound"))
        self.assertTrue(self.wait_for(lambda: osd() is False), "bublina vypnuta pri otevrenem okne")
        self.assertEqual(self.run_popup("sound").returncode, 0)          # zavrit
        self.assertTrue(self.wait_for(lambda: osd() is True), "po zavreni zase zapnuta")
        # pad s otevrenym oknem: dalsi spusteni hodnotu vrati
        self.assertEqual(self.run_popup("sound").returncode, 0)
        self.assertTrue(self.wait_for(lambda: osd() is False))
        os.killpg(p.pid, signal.SIGKILL)
        p.wait(timeout=10)
        self.popup("wifi")
        self.assertTrue(self.wait_for(lambda: osd() is True), "obnova po padu")

    def test_sound_window_stays_put_after_mute(self):
        # okno se umisti pod ikonu jen pri otevreni; zmena ikony ztlumeni ho nesmi presunout pod mys
        subprocess.run(["xdotool", "mousemove", "1500", "10"], check=True)
        self.popup("sound")
        self.assertTrue(self.shown("sound"))
        self.assertTrue(self.wait_for(lambda: "mute:sink" in self.positions()), self.read(self.testlog))
        time.sleep(0.5)
        before = self.window_position()
        self.click("mute:sink")
        time.sleep(0.6)
        self.assertEqual(self.window_position(), before)

    def test_notifications_list_delete_dnd_and_read_on_close(self):
        p = self.popup("notifications")
        self.assertTrue(self.shown("notifications"))
        self.assertTrue(self.wait_for(lambda: "delete:n2" in self.positions()), self.read(self.testlog))
        self.assertIn({"log": "List", "args": ["", 50, False]}, self.dbus_calls())
        self.click("delete:n1")
        if not self.wait_for(lambda: {"log": "Delete", "args": [["n1"]]} in self.dbus_calls()):
            p.terminate()
            self.fail((self.dbus_calls(), p.communicate(timeout=10)[1][-1500:], self.read(self.testlog)[-800:]))
        self.click("dnd")
        self.assertTrue(self.wait_for(lambda: "-p /do-not-disturb -n -t bool -s true" in self.read(self.calls)))
        # druhe spusteni = prepnuti bezicim procesem: okno se zavre a oznameni jsou prectena
        r = self.run_popup("notifications")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.wait_for(lambda: "hidden notifications" in self.read(self.testlog)))
        self.assertTrue(self.wait_for(lambda: {"log": "MarkAllRead", "args": []} in self.dbus_calls()), self.dbus_calls())
        self.assertIsNone(p.poll(), "server zustava na pozadi")

    def test_click_opens_like_android(self):
        # n2: aplikace oznameni neprevezme -> otevrit aplikaci (desktop-entry "luxos"), z historie pryc
        self.popup("notifications")
        self.assertTrue(self.shown("notifications"))
        self.assertTrue(self.wait_for(lambda: "open:n2" in self.positions()), self.read(self.testlog))
        self.click("open:n2")
        self.assertTrue(self.wait_for(lambda: {"history": "Activate", "args": ["n2"]} in self.dbus_calls()),
                        self.dbus_calls())
        self.assertTrue(self.wait_for(lambda: "gtk-launch luxos" in self.read(self.calls)), self.read(self.calls))
        self.assertTrue(self.wait_for(lambda: {"log": "Delete", "args": [["n2"]]} in self.dbus_calls()))
        self.assertTrue(self.wait_for(lambda: "hidden notifications" in self.read(self.testlog)), "okno se zavre")
        # n1: aplikace bezi a ma vychozi akci -> jen Activate (akci posle modul), nic se nespousti
        self.assertEqual(self.run_popup("notifications").returncode, 0)
        self.assertTrue(self.wait_for(lambda: self.read(self.testlog).count("shown notifications") >= 2))
        self.assertTrue(self.wait_for(lambda: "open:n1" in self.positions()))
        self.click("open:n1")
        self.assertTrue(self.wait_for(lambda: {"history": "Activate", "args": ["n1"]} in self.dbus_calls()))
        self.assertTrue(self.wait_for(lambda: {"log": "Delete", "args": [["n1"]]} in self.dbus_calls()))
        self.assertNotIn("gtk-launch clock", self.read(self.calls))

    def test_app_name_from_desktop_entry(self):
        # historie bez nazvu aplikace (desktop-entry): nazev z .desktop podle jazyka
        apps = os.path.join(self.t, "share", "applications")
        os.makedirs(apps)
        with open(os.path.join(apps, "luxos-mail.desktop"), "w") as f:
            f.write("[Desktop Entry]\nName=Mail\nName[cs]=Posta\nExec=true\n")
        out = subprocess.run([os.path.join(BIN, "luxos-bar-popup"), "--app-name", "luxos-mail"], capture_output=True,
                             text=True, timeout=20, env=dict(self.env, XDG_DATA_HOME=os.path.join(self.t, "share"),
                                                             LANG="cs_CZ.UTF-8"))
        self.assertEqual(out.stdout.strip(), "Posta", out.stderr)
        out = subprocess.run([os.path.join(BIN, "luxos-bar-popup"), "--app-name", "luxos-mail"], capture_output=True,
                             text=True, timeout=20, env=dict(self.env, XDG_DATA_HOME=os.path.join(self.t, "share"),
                                                             LANG="C"))
        self.assertEqual(out.stdout.strip(), "Mail")

    def test_switching_between_popups(self):
        self.popup("sound")
        self.assertTrue(self.shown("sound"))
        self.assertEqual(self.run_popup("wifi").returncode, 0)
        self.assertTrue(self.wait_for(lambda: "hidden sound" in self.read(self.testlog) and "shown wifi" in self.read(self.testlog)))


if __name__ == "__main__":
    unittest.main()
