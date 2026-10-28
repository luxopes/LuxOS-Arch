"""Testy pro Bluetooth: jmeno pocitace (Alias adapteru BlueZ) - kontrola jmena, zapis pres D-Bus
a zobrazeni v okne. Falesny BlueZ bezi na soukromem dbus-daemonu (ne na systemove sbernici),
skutecny Bluetooth adapter ani nastaveni se nemeni.

Spusteni: env -u DISPLAY xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_luxos_bluetooth.py -v
(bez DISPLAY se testy okna preskoci; nikdy ne na skutecne obrazovce)
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "files", "bin"))
I18N = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
sys.path.insert(0, I18N)

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib  # noqa: E402

# Falesny BlueZ: ObjectManager na /, adapter hci0 (Properties Get/Set/GetAll, StartDiscovery...).
# Set Alias "" vrati jmeno systemu (jako BlueZ); kazdy Set se zapise do $LOG (JSON radky).
FAKE_BLUEZ = r'''
import json, os, sys
from gi.repository import Gio, GLib
LOG = os.environ["FAKE_BLUEZ_LOG"]
A = "/org/bluez/hci0"
props = {"Address": "00:11:22:33:44:55", "Name": "luxos-pc", "Alias": "luxos-pc",
         "Powered": True, "Discoverable": False, "DiscoverableTimeout": 0, "Discovering": False}
SIG = {"Address": "s", "Name": "s", "Alias": "s", "Powered": "b", "Discoverable": "b", "DiscoverableTimeout": "u",
       "Discovering": "b"}
DEV = A + "/dev_AA_BB_CC_DD_EE_01"
dev_props = {"Address": GLib.Variant("s", "AA:BB:CC:DD:EE:01"), "Alias": GLib.Variant("s", "Pixel Test"),
             "Adapter": GLib.Variant("o", A), "Paired": GLib.Variant("b", False), "Trusted": GLib.Variant("b", False)}
XML = """<node>
<interface name="org.freedesktop.DBus.ObjectManager">
 <method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" direction="out"/></method>
</interface>
<interface name="org.freedesktop.DBus.Properties">
 <method name="Get"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
 <method name="GetAll"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method>
 <method name="Set"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/></method>
</interface>
<interface name="org.bluez.Adapter1">
 <method name="StartDiscovery"/><method name="StopDiscovery"/>
</interface>
</node>"""
node = Gio.DBusNodeInfo.new_for_xml(XML)
loop = GLib.MainLoop()
bus = Gio.DBusConnection.new_for_address_sync(
    os.environ["FAKE_BLUEZ_ADDR"],
    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)

def variants():
    return {k: GLib.Variant(SIG[k], v) for k, v in props.items()}

def log(entry):
    with open(LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

def call(conn, sender, path, iface, method, params, inv):
    args = params.unpack()
    if method == "GetManagedObjects":
        inv.return_value(GLib.Variant("(a{oa{sa{sv}}})", ({A: {"org.bluez.Adapter1": variants()},
                                                            DEV: {"org.bluez.Device1": dev_props}},)))
    elif method == "GetAll":
        inv.return_value(GLib.Variant("(a{sv})", (variants(),)))
    elif method == "Get":
        inv.return_value(GLib.Variant("(v)", (variants()[args[1]],)))
    elif method == "Set":
        iface_, name, value = args
        log({"set": name, "value": value})
        if name not in ("Alias", "Powered", "Discoverable", "DiscoverableTimeout") or path != A:
            inv.return_dbus_error("org.bluez.Error.InvalidArguments", "Invalid arguments")
            return
        if name == "Alias" and os.path.exists(LOG + ".deny"):
            inv.return_dbus_error("org.freedesktop.DBus.Error.AccessDenied", "Rejected send message")
            return
        props[name] = value if not (name == "Alias" and value == "") else props["Name"]
        inv.return_value(None)
        conn.emit_signal(None, A, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                         GLib.Variant("(sa{sv}as)", ("org.bluez.Adapter1", {name: GLib.Variant(SIG[name], props[name])}, [])))
    else:
        log({"call": method})
        inv.return_value(None)

for path in ("/", A):
    for i in node.interfaces:
        bus.register_object(path, i, call, None, None)
Gio.bus_own_name_on_connection(bus, "org.bluez", Gio.BusNameOwnerFlags.NONE,
                               lambda *a: print("READY", flush=True), lambda *a: loop.quit())
loop.run()
'''


def load_app():
    loader = importlib.machinery.SourceFileLoader("luxos_bluetooth", os.path.join(BIN, "luxos-bluetooth"))
    spec = importlib.util.spec_from_loader("luxos_bluetooth", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


bt = load_app()


class AliasCheck(unittest.TestCase):
    def test_valid(self):
        for name in ("Jana's laptop", "Počítač Honzy", "LuxOS 💻", "x" * 248, ""):
            self.assertIsNone(bt.alias_problem(name), name)

    def test_too_long(self):
        self.assertIsNotNone(bt.alias_problem("x" * 249))
        # limit je v bajtech UTF-8: 125 x "č" = 250 B
        self.assertIsNotNone(bt.alias_problem("č" * 125))
        self.assertIsNone(bt.alias_problem("č" * 124))

    def test_control_chars(self):
        for name in ("a\nb", "tab\there", "nul\x00", "del\x7f"):
            self.assertIsNotNone(bt.alias_problem(name), repr(name))

    def test_clean(self):
        self.assertEqual(bt.clean_alias("  My PC \n"), "My PC")
        self.assertEqual(bt.clean_alias(None), "")


class BusFixture(unittest.TestCase):
    """Soukromy dbus-daemon + falesny BlueZ; aplikace dostane tuto sbernici misto systemove."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("dbus-daemon"):
            raise unittest.SkipTest("dbus-daemon is missing")
        cls.tmp = tempfile.mkdtemp(prefix="luxos-bt-test.")
        cls.log = os.path.join(cls.tmp, "calls.jsonl")
        cls.bus_proc = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                                      stdout=subprocess.PIPE, text=True)
        cls.addr = cls.bus_proc.stdout.readline().strip()
        env = dict(os.environ, FAKE_BLUEZ_ADDR=cls.addr, FAKE_BLUEZ_LOG=cls.log)
        cls.fake = subprocess.Popen([sys.executable, "-c", FAKE_BLUEZ], env=env, stdout=subprocess.PIPE, text=True)
        assert cls.fake.stdout.readline().strip() == "READY"
        # kazde okno/Bluez vlastni spojeni (agent BlueZ se registruje na pevne ceste)
        bt.BUS = lambda: Gio.DBusConnection.new_for_address_sync(
            cls.addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)

    @classmethod
    def tearDownClass(cls):
        bt.BUS = bt.system_bus
        cls.fake.terminate()
        cls.bus_proc.terminate()
        cls.fake.wait(5)
        cls.bus_proc.wait(5)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        open(self.log, "w").close()

    def wait(self, cond, timeout=5.0):
        ctx = GLib.MainContext.default()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            while ctx.pending():
                ctx.iteration(False)
            if cond():
                return True
            time.sleep(0.01)
        return cond()

    def calls(self):
        with open(self.log) as f:
            return [json.loads(line) for line in f if line.strip()]

    def alias(self, bz):
        bz.reload()
        return bz.adapter()[1].get("Alias")


class FakeBluez(BusFixture):
    def test_bluez_layer_sets_alias(self):
        changes = []
        bz = bt.Bluez(lambda: changes.append(1))
        path, adapter = bz.adapter()
        self.assertEqual(path, "/org/bluez/hci0")
        self.assertEqual(adapter["Alias"], "luxos-pc")
        errs = []
        bz.set_prop(path, "org.bluez.Adapter1", "Alias", GLib.Variant("s", "Jana's laptop"), done=errs.append)
        self.assertTrue(self.wait(lambda: errs))
        self.assertIsNone(errs[0])
        self.assertIn({"set": "Alias", "value": "Jana's laptop"}, self.calls())
        self.assertEqual(self.alias(bz), "Jana's laptop")
        # PropertiesChanged -> reload -> on_change
        self.assertTrue(self.wait(lambda: len(changes) > 2))
        # prazdne jmeno = vychozi jmeno systemu
        errs.clear()
        bz.set_prop(path, "org.bluez.Adapter1", "Alias", GLib.Variant("s", ""), done=errs.append)
        self.assertTrue(self.wait(lambda: errs))
        self.assertEqual(self.alias(bz), "luxos-pc")

    def test_error_is_reported(self):
        bz = bt.Bluez(lambda: None)
        open(self.log + ".deny", "w").close()
        try:
            errs = []
            bz.set_prop("/org/bluez/hci0", "org.bluez.Adapter1", "Alias", GLib.Variant("s", "x"), done=errs.append)
            self.assertTrue(self.wait(lambda: errs))
            self.assertIsNotNone(errs[0])
            self.assertIn("AccessDenied", errs[0].message)
        finally:
            os.unlink(self.log + ".deny")
        self.assertEqual(self.alias(bz), "luxos-pc")


@unittest.skipUnless(os.environ.get("DISPLAY") and "xvfb-run" in os.environ.get("XAUTHORITY", ""),
                     "needs xvfb-run (never the real display)")
class Window(BusFixture):
    def make(self):
        from gi.repository import Gtk
        win = bt.BluetoothWindow()
        self.addCleanup(win.destroy)
        self.Gtk = Gtk
        self.wait(lambda: False, 0.3)
        return win

    def test_name_row_and_rename(self):
        win = self.make()
        self.assertTrue(win.name_group.get_visible())
        self.assertEqual(win.name_label.get_text(), "luxos-pc")
        self.assertIn("luxos-pc", win.hint.get_text())
        self.assertTrue(win.set_alias("Honzův notebook"))
        self.assertTrue(self.wait(lambda: win.name_label.get_text() == "Honzův notebook"))
        self.assertIn("Honzův notebook", win.hint.get_text())
        # neplatne jmeno se vubec neodesle
        open(self.log, "w").close()
        self.assertFalse(win.set_alias("a\nb"))
        self.assertFalse(win.set_alias("x" * 300))
        self.wait(lambda: False, 0.3)
        self.assertEqual([c for c in self.calls() if c.get("set") == "Alias"], [])
        # vychozi jmeno
        self.assertTrue(win.set_alias(""))
        self.assertTrue(self.wait(lambda: win.name_label.get_text() == "luxos-pc"))

    def test_rename_dialog_validation(self):
        win = self.make()
        dlg, entry, err, ok = win.rename_dialog()
        self.addCleanup(dlg.destroy)
        self.assertEqual(entry.get_text(), "luxos-pc")
        self.assertTrue(ok.get_sensitive())
        entry.set_text("x" * 249)
        self.assertFalse(ok.get_sensitive())
        self.assertTrue(err.get_text())
        entry.set_text("   ")
        self.assertTrue(ok.get_sensitive())            # prazdne = vychozi jmeno
        self.assertIn("luxos-pc", err.get_text())
        entry.set_text("Kitchen PC")
        self.assertTrue(ok.get_sensitive())
        self.assertEqual(err.get_text(), "")

    def test_rename_ok_and_default_buttons(self):
        win = self.make()
        Gtk = self.Gtk
        # dialog.run() nahradime odpovedi tlacitka (bez interakce)
        orig = Gtk.Dialog.run

        def fake_run(resp, text=None):
            def run(dlg):
                if text is not None:
                    dlg.get_content_area().get_children()[1].set_text(text)
                return resp
            return run
        try:
            Gtk.Dialog.run = fake_run(Gtk.ResponseType.OK, "  Office PC  ")
            win.rename()
            self.assertTrue(self.wait(lambda: win.name_label.get_text() == "Office PC"))
            Gtk.Dialog.run = fake_run(Gtk.ResponseType.CANCEL, "Ignored")
            open(self.log, "w").close()
            win.rename()
            self.wait(lambda: False, 0.3)
            self.assertEqual([c for c in self.calls() if c.get("set") == "Alias"], [])
            Gtk.Dialog.run = fake_run(Gtk.ResponseType.REJECT)
            win.rename()
            self.assertTrue(self.wait(lambda: win.name_label.get_text() == "luxos-pc"))
            self.assertIn({"set": "Alias", "value": ""}, self.calls())
        finally:
            Gtk.Dialog.run = orig

    def test_access_denied_shows_error(self):
        win = self.make()
        shown = []
        win.error = lambda title, text, advice=True: shown.append((title, text, advice))
        open(self.log + ".deny", "w").close()
        try:
            win.set_alias("Denied")
            self.assertTrue(self.wait(lambda: shown))
        finally:
            os.unlink(self.log + ".deny")
        self.assertFalse(shown[0][2])
        self.assertEqual(win.name_label.get_text(), "luxos-pc")


    # ---- viditelnost pri otevrenem okne ----
    def bluez_set(self, name, value):
        """Zmena vlastnosti adapteru "zvenku" (bluetoothctl, vyprseni casovace)."""
        bt.BUS().call_sync("org.bluez", "/org/bluez/hci0", "org.freedesktop.DBus.Properties", "Set",
                           GLib.Variant("(ssv)", ("org.bluez.Adapter1", name, value)), None, 0, 3000, None)

    def adapter(self):
        bz = bt.Bluez(lambda: None)
        return bz.adapter()[1]

    def sets(self, name=None):
        return [(c["set"], c["value"]) for c in self.calls() if "set" in c and (name is None or c["set"] == name)]

    def test_visible_while_open(self):
        win = self.make()
        self.assertTrue(self.wait(lambda: self.adapter().get("Discoverable")))
        # nejdriv casovac 180 s (pad okna), pak viditelnost
        self.assertEqual(self.sets()[:2], [("DiscoverableTimeout", 180), ("Discoverable", True)])
        self.assertTrue(self.wait(lambda: win.hint.get_text() == "Visible as “luxos-pc” while this window is open."))
        self.assertIn("visible now", win.name_sub.get_text())
        # casovac vyprsel / vypnuto zvenku -> pri otevrenem okne znovu viditelny
        open(self.log, "w").close()
        self.bluez_set("Discoverable", GLib.Variant("b", False))
        self.assertTrue(self.wait(lambda: ("Discoverable", True) in self.sets()))
        self.assertTrue(self.wait(lambda: self.adapter().get("Discoverable")))
        # obnova casovace (BlueZ znovu spusti odpocet)
        open(self.log, "w").close()
        self.assertTrue(win.renew_visible())
        self.assertTrue(self.wait(lambda: self.sets() == [("DiscoverableTimeout", 180)]))
        # zavreni: viditelnost vypnuta, puvodni casovac (0) zpet
        open(self.log, "w").close()
        win.destroy()
        self.assertEqual(self.sets(), [("Discoverable", False), ("DiscoverableTimeout", 0)])
        a = self.adapter()
        self.assertFalse(a.get("Discoverable"))
        self.assertEqual(a.get("DiscoverableTimeout"), 0)
        self.wait(lambda: False, 0.4)
        self.assertEqual(self.sets(), [("Discoverable", False), ("DiscoverableTimeout", 0)])

    def test_already_visible_is_left_alone(self):
        self.bluez_set("Discoverable", GLib.Variant("b", True))
        self.addCleanup(self.bluez_set, "Discoverable", GLib.Variant("b", False))
        open(self.log, "w").close()
        win = self.make()
        self.wait(lambda: False, 0.3)
        self.assertEqual(win.hint.get_text(), "Visible to nearby devices as “luxos-pc”.")
        self.assertEqual(self.sets("Discoverable"), [])
        win.renew_visible()
        win.destroy()
        self.wait(lambda: False, 0.3)
        self.assertEqual(self.sets(), [])                    # nezaplo ji okno -> nevypina ji
        self.assertTrue(self.adapter().get("Discoverable"))

    def test_power_off_hides(self):
        win = self.make()
        self.assertTrue(self.wait(lambda: self.adapter().get("Discoverable")))
        open(self.log, "w").close()
        win.power.set_active(False)
        self.assertTrue(self.wait(lambda: ("Powered", False) in self.sets()))
        self.assertEqual(self.sets()[:2], [("Discoverable", False), ("Powered", False)])
        self.assertTrue(self.wait(lambda: win.hint.get_text().startswith("Turn on Bluetooth")))
        self.assertFalse(self.adapter().get("Discoverable"))
        open(self.log, "w").close()
        win.power.set_active(True)
        self.assertTrue(self.wait(lambda: self.adapter().get("Discoverable"), 5))
        self.assertIn(("Discoverable", True), self.sets())
        win.destroy()
        self.assertFalse(self.adapter().get("Discoverable"))

    def test_hint_not_visible(self):
        win = self.make()
        win.visible_failed = True                            # BlueZ viditelnost odmitl
        self.bluez_set("Discoverable", GLib.Variant("b", False))
        self.assertTrue(self.wait(lambda: win.hint.get_text() == "Not visible to other devices."))

    # ---- agent: parovani, ktere zacal telefon ----
    def agent_call(self, win, method, args, sig):
        out = {}
        client = bt.BUS()

        def done(conn, res):
            try:
                out["r"] = conn.call_finish(res).unpack()
            except GLib.Error as e:
                out["e"] = e.message
        client.call(win.bz.bus.get_unique_name(), bt.AGENT_PATH, "org.bluez.Agent1", method,
                    GLib.Variant(sig, args) if sig else None, None, 0, 5000, None, done)
        self.assertTrue(self.wait(lambda: out))
        return out

    def test_agent_phone_pairing(self):
        win = self.make()
        Gtk = self.Gtk
        shown = []
        answer = [Gtk.ResponseType.OK]
        orig = Gtk.Dialog.run

        def run(dlg):
            area = dlg.get_message_area()
            shown.append([w.get_text() for w in area.get_children() if isinstance(w, Gtk.Label)])
            return answer[0]
        Gtk.Dialog.run = run
        try:
            # ciselne porovnani (telefon i pocitac ukazuji kod)
            out = self.agent_call(win, "RequestConfirmation", ("/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01", 42), "(ou)")
            self.assertEqual(out, {"r": ()})
            self.assertEqual(shown[-1][0], "Pair this device?")
            self.assertIn("000042", shown[-1][1])
            answer[0] = Gtk.ResponseType.CANCEL
            out = self.agent_call(win, "RequestConfirmation", ("/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01", 7), "(ou)")
            self.assertIn("Rejected", out["e"])
            # kod na pocitaci, telefon ho zada
            out = self.agent_call(win, "DisplayPasskey", ("/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01", 123456, 0), "(ouq)")
            self.assertEqual(out, {"r": ()})
            self.assertIn("123456", shown[-1][1])
            # parovani bez kodu: dotaz se jmenem zarizeni, odmitnuti
            out = self.agent_call(win, "RequestAuthorization", ("/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01",), "(o)")
            self.assertIn("Rejected", out["e"])
            self.assertEqual(shown[-1][0], "Allow “Pixel Test” to pair with this computer?")
            answer[0] = Gtk.ResponseType.OK
            out = self.agent_call(win, "RequestAuthorization", ("/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01",), "(o)")
            self.assertEqual(out, {"r": ()})
            # sluzba LuxOS Companion bez dotazu (schvaluje ji aplikace)
            n = len(shown)
            out = self.agent_call(win, "AuthorizeService", ("/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01",
                                                            "AD9B7C10-6CE5-4F35-9952-728F760FCB70"), "(os)")
            self.assertEqual((out, len(shown)), ({"r": ()}, n))
        finally:
            Gtk.Dialog.run = orig


if __name__ == "__main__":
    unittest.main()
