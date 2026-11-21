"""Testy pro Bluetooth (stranka okna Nastaveni files/lsl/luxos_page_bluetooth.lsl, luxos-bluetooth je odkaz na
luxos-settings): jmeno pocitace (Alias adapteru BlueZ), viditelnost pri zobrazene strance, hledani v pozadi, parovani a agent BlueZ. Falesny BlueZ (tests/bluetooth/fake_bluez.py) bezi na
soukromem dbus-daemonu (ne na systemove sbernici), rfkill je falesny skript - skutecny Bluetooth adapter ani
nastaveni se nemeni. Okno bezi ve vlastnim Xvfb a ridi se pres luxos_testctl (LUXOS_TEST_CONTROL=1).

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_bluetooth.py -v

Prekladac lslc (balik lsl) je potreba; bez nej se testy preskoci.
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
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

FAKE = os.path.join(HERE, "bluetooth", "fake_bluez.py")
A = "/org/bluez/hci0"
DEV = A + "/dev_AA_BB_CC_DD_EE_01"
TMP = None
BINARY = None


def setUpModule():
    global TMP, BINARY
    TMP = tempfile.mkdtemp(prefix="luxos-bt-test.", dir=luxos_testguard._private_dir())
    BINARY = lsl_app.build("luxos-bluetooth", TMP)


def tearDownModule():
    if TMP:
        shutil.rmtree(TMP, True)


class Fixture(unittest.TestCase):
    """Vlastni Xvfb; pro kazdy test soukromy dbus-daemon, falesny BlueZ a nove okno."""

    @classmethod
    def setUpClass(cls):
        cls.x = lsl_app.Xvfb()

    @classmethod
    def tearDownClass(cls):
        cls.x.stop()

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=TMP)
        self.log = os.path.join(self.dir, "calls.jsonl")
        open(self.log, "w").close()
        # falesny rfkill: zapnuti v okne nesmi odblokovat skutecne radio
        self.bin = os.path.join(self.dir, "bin")
        os.mkdir(self.bin)
        with open(os.path.join(self.bin, "rfkill"), "w") as f:
            f.write('#!/bin/sh\necho "$*" >> "%s/rfkill.log"\n' % self.dir)
        os.chmod(os.path.join(self.bin, "rfkill"), 0o755)
        self.bus = lsl_app.Bus()
        self.fake = None
        self.app = None

    def tearDown(self):
        if self.app:
            self.app.stop()
        if self.fake:
            self.fake.terminate()
            self.fake.wait(5)
        self.bus.stop()

    def start_fake(self, **env):
        self.fake = subprocess.Popen([sys.executable, FAKE], stdout=subprocess.PIPE, text=True,
                                     env=dict(os.environ, FAKE_BLUEZ_ADDR=self.bus.address, FAKE_BLUEZ_LOG=self.log, **env))
        self.assertEqual(self.fake.stdout.readline().strip(), "READY")

    def start(self, fake=True, lang="C.UTF-8", **fake_env):
        if fake:
            self.start_fake(**fake_env)
        env = dict(os.environ, DISPLAY=self.x.display, DBUS_SYSTEM_BUS_ADDRESS=self.bus.address, LANG=lang,
                   LC_ALL=lang, PATH=self.bin + os.pathsep + os.environ["PATH"])
        luxos_testguard.check_env(env)
        self.app = lsl_app.App([BINARY], env)
        self.assertTrue(self.app.wait(lambda: self.hint() != ""), self.app.stderr())
        return self.app

    # ---- stav okna ----
    def named(self, name, key="text"):
        w = lsl_app.find(self.app.dump(), name=name)
        return None if w is None else w.get(key)

    def hint(self):
        return self.named("hint") or ""

    def name_label(self):
        return self.named("name-label")

    def wait_for(self, cond, timeout=6.0):
        return self.app.wait(cond, timeout)

    def calls(self):
        with open(self.log) as f:
            return [json.loads(line) for line in f if line.strip()]

    def sets(self, name=None):
        return [(c["set"], c["value"]) for c in self.calls() if "set" in c and (name is None or c["set"] == name)]

    def clear_log(self):
        open(self.log, "w").close()

    def gdbus(self, *args):
        return subprocess.run(["gdbus", "call", "--address", self.bus.address] + list(args),
                              capture_output=True, text=True, timeout=15)

    def adapter(self):
        from gi.repository import Gio, GLib
        bus = Gio.DBusConnection.new_for_address_sync(
            self.bus.address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
        try:
            return bus.call_sync("org.bluez", A, "org.freedesktop.DBus.Properties", "GetAll",
                                 GLib.Variant("(s)", ("org.bluez.Adapter1",)), None, 0, 3000, None).unpack()[0]
        finally:
            bus.close_sync(None)

    def bluez_set(self, name, value):
        """Zmena vlastnosti adapteru "zvenku" (bluetoothctl, vyprseni casovace)."""
        r = self.gdbus("--dest", "org.bluez", "--object-path", A, "--method", "org.freedesktop.DBus.Properties.Set",
                       "org.bluez.Adapter1", name, value)
        self.assertEqual(r.returncode, 0, r.stderr)

    def emit(self, iface, changed, invalidated="@as []"):
        r = self.gdbus("--dest", "org.bluez", "--object-path", "/", "--method", "cz.luxos.Test.Emit", DEV, iface,
                       changed, invalidated)
        self.assertEqual(r.returncode, 0, r.stderr)

    def dialog_texts(self):
        return lsl_app.texts(self.app.dump(), dialog=True)

    def flag(self, name):
        open(self.log + "." + name, "w").close()
        self.addCleanup(os.unlink, self.log + "." + name)


class AliasCheck(Fixture):
    def check(self, name):
        return json.loads(self.app.ask("check " + json.dumps(name), "check"))

    def test_valid(self):
        self.start()
        for name in ("Jana's laptop", "Počítač Honzy", "LuxOS 💻", "x" * 248, ""):
            self.assertEqual(self.check(name), "", name)

    def test_too_long(self):
        self.start()
        self.assertNotEqual(self.check("x" * 249), "")
        # limit je v bajtech UTF-8: 125 x "č" = 250 B, emoji 4 B
        self.assertNotEqual(self.check("č" * 125), "")
        self.assertEqual(self.check("č" * 124), "")
        self.assertEqual(self.check("💻" * 62), "")
        self.assertIn("248", self.check("💻" * 63))

    def test_control_chars(self):
        self.start()
        for name in ("a\nb", "tab\there", "nul\x01", "del\x7f"):
            self.assertIn("control characters", self.check(name), repr(name))

    def test_clean(self):
        # jmeno z pole formulare bez mezer na zacatku a konci (Prejmenovat)
        self.start()
        self.app.send("click Rename…")
        self.assertTrue(self.wait_for(lambda: "Rename This Computer" in [w["title"] for w in self.app.dump()]))
        self.app.ask("entry   My PC  ")
        self.app.ask("respond -5")
        self.assertTrue(self.wait_for(lambda: self.name_label() == "My PC"))
        self.assertIn(("Alias", "My PC"), self.sets())


class FakeBluez(Fixture):
    def test_system_bus_address_is_honoured(self):
        # okno bezi nad soukromou sbernici pres DBUS_SYSTEM_BUS_ADDRESS - skutecny adapter se nesmi zapnout,
        # zviditelnit ani prohledavat okoli
        self.start()
        # horni lista se zaviracim tlacitkem (drive scripts/check-titlebars.sh)
        self.assertEqual([(w["title"], w["close_button"]) for w in self.app.dump()], [("Bluetooth", True)])
        self.assertEqual(self.name_label(), "luxos-pc")
        calls = self.calls()
        self.assertIn({"call": "StartDiscovery", "path": A}, [{k: c[k] for k in ("call", "path")} for c in calls if "call" in c])

    def test_bluez_layer_sets_alias(self):
        self.start()
        before = int(self.app.ask("reloads", "reloads"))
        self.assertEqual(self.app.ask("alias " + json.dumps("Jana's laptop"), "alias"), "True")
        self.assertTrue(self.wait_for(lambda: self.name_label() == "Jana's laptop"))
        self.assertIn(("Alias", "Jana's laptop"), self.sets())
        self.assertEqual(self.adapter()["Alias"], "Jana's laptop")
        # PropertiesChanged -> nove nacteni
        self.assertGreater(int(self.app.ask("reloads", "reloads")), before)
        # prazdne jmeno = vychozi jmeno systemu
        self.app.ask("alias " + json.dumps(""), "alias")
        self.assertTrue(self.wait_for(lambda: self.name_label() == "luxos-pc"))
        self.assertEqual(self.adapter()["Alias"], "luxos-pc")

    def test_error_is_reported(self):
        self.start()
        self.flag("deny")
        self.app.ask("alias " + json.dumps("x"), "alias")
        self.assertTrue(self.wait_for(lambda: "Could not rename this computer" in self.dialog_texts()))
        self.assertIn("Rejected send message", self.dialog_texts())
        self.app.ask("respond -5")
        self.assertEqual(self.adapter()["Alias"], "luxos-pc")
        self.assertEqual(self.name_label(), "luxos-pc")

    def test_rssi_does_not_reload(self):
        """Pri hledani posila BlueZ RSSI zarizeni v okoli nekolikrat za sekundu - bez nacteni a prekresleni."""
        self.start()
        time.sleep(0.5)
        count = lambda: int(self.app.ask("reloads", "reloads"))  # noqa: E731
        before = count()
        for changed in ("{'RSSI': <int16 -60>}", "{'TxPower': <int16 4>}",
                        "{'RSSI': <int16 -61>, 'ManufacturerData': <@a{qv} {}>}"):
            self.emit("org.bluez.Device1", changed)
        time.sleep(0.4)
        self.assertEqual(count(), before)
        # zmeny, ktere okno ukazuje, se nactou
        for iface, changed in (("org.bluez.Device1", "{'Connected': <false>}"),
                               ("org.bluez.Device1", "{'RSSI': <int16 -50>, 'Name': <'x'>}"),
                               ("org.bluez.Battery1", "{'Percentage': <byte 70>}"),
                               ("org.bluez.Adapter1", "{'Discovering': <true>}")):
            self.emit(iface, changed)
        self.assertTrue(self.wait_for(lambda: count() == before + 4))
        # zneplatnena vlastnost (RSSI zmizelo = zarizeni mimo dosah) se nacte
        self.emit("org.bluez.Device1", "@a{sv} {}", "['RSSI']")
        self.assertTrue(self.wait_for(lambda: count() == before + 5))


class Window(Fixture):
    def test_name_row_and_rename(self):
        self.start()
        self.assertTrue(self.named("name-group", "vis"))
        self.assertEqual(self.name_label(), "luxos-pc")
        self.assertTrue(self.wait_for(lambda: "luxos-pc" in self.hint()))
        self.assertEqual(self.app.ask("alias " + json.dumps("Honzův notebook"), "alias"), "True")
        self.assertTrue(self.wait_for(lambda: self.name_label() == "Honzův notebook"))
        self.assertTrue(self.wait_for(lambda: "Honzův notebook" in self.hint()))
        # neplatne jmeno se vubec neodesle
        self.clear_log()
        self.assertEqual(self.app.ask("alias " + json.dumps("a\nb"), "alias"), "False")
        self.assertEqual(self.app.ask("alias " + json.dumps("x" * 300), "alias"), "False")
        time.sleep(0.3)
        self.assertEqual(self.sets("Alias"), [])
        # vychozi jmeno
        self.app.ask("alias " + json.dumps(""), "alias")
        self.assertTrue(self.wait_for(lambda: self.name_label() == "luxos-pc"))

    def open_rename(self):
        self.app.send("click Rename…")
        self.assertTrue(self.wait_for(lambda: any(w["dialog"] for w in self.app.dump())))

    def rename_form(self):
        d = self.app.dump()
        entry = lsl_app.find(d, kind="GtkEntry", dialog=True)
        ok = lsl_app.find(d, text="Rename", kind="GtkButton", dialog=True)
        labels = [w for w in lsl_app.widgets(d, dialog=True) if w["t"] == "GtkLabel"]
        # popisky dialogu: informace, chyba, pak tlacitka
        return entry["text"], labels[1]["text"], ok["sens"]

    def test_rename_dialog_validation(self):
        self.start()
        self.open_rename()
        d = self.app.dump()
        self.assertEqual([w["title"] for w in d if w["dialog"]], ["Rename This Computer"])
        self.assertEqual(lsl_app.find(d, text="Use Default", dialog=True)["tip"], "Use the system name “luxos-pc”")
        text, err, ok = self.rename_form()
        self.assertEqual(text, "luxos-pc")
        self.assertTrue(ok)
        self.app.ask("entry " + "x" * 249)
        text, err, ok = self.rename_form()
        self.assertFalse(ok)
        self.assertTrue(err)
        self.app.ask("entry    ")
        text, err, ok = self.rename_form()
        self.assertTrue(ok)                     # prazdne = vychozi jmeno
        self.assertIn("luxos-pc", err)
        self.app.ask("entry Kitchen PC")
        text, err, ok = self.rename_form()
        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.app.ask("respond -6")

    def test_rename_ok_and_default_buttons(self):
        self.start()
        self.open_rename()
        self.app.ask("entry   Office PC  ")
        self.app.ask("click Rename")
        self.assertTrue(self.wait_for(lambda: self.name_label() == "Office PC"))
        # Zrusit: nic se neodesle
        self.open_rename()
        self.app.ask("entry Ignored")
        self.clear_log()
        self.app.ask("click Cancel")
        time.sleep(0.3)
        self.assertEqual(self.sets("Alias"), [])
        self.assertEqual(self.name_label(), "Office PC")
        # Pouzit vychozi
        self.open_rename()
        self.app.ask("click Use Default")
        self.assertTrue(self.wait_for(lambda: self.name_label() == "luxos-pc"))
        self.assertIn(("Alias", ""), self.sets())

    def test_access_denied_shows_error(self):
        self.start()
        self.flag("deny")
        self.app.ask("alias " + json.dumps("Denied"), "alias")
        self.assertTrue(self.wait_for(lambda: "Could not rename this computer" in self.dialog_texts()))
        # bez rady o parovacim rezimu (ta je jen u pripojeni zarizeni)
        self.assertFalse(any("pairing mode" in t for t in self.dialog_texts()))
        self.app.ask("click Close")
        self.assertEqual(self.name_label(), "luxos-pc")

    # ---- viditelnost pri otevrenem okne ----
    def test_visible_while_open(self):
        self.start()
        self.assertTrue(self.wait_for(lambda: self.adapter().get("Discoverable") is True))
        # nejdriv casovac 180 s (pad okna), pak viditelnost
        self.assertEqual(self.sets()[:2], [("DiscoverableTimeout", 180), ("Discoverable", True)])
        self.assertTrue(self.wait_for(lambda: self.hint() == "Visible as “luxos-pc” while this window is open."))
        self.assertIn("visible now", self.named("name-sub"))
        # casovac vyprsel / vypnuto zvenku -> pri otevrenem okne znovu viditelny
        self.clear_log()
        self.bluez_set("Discoverable", "<false>")
        self.assertTrue(self.wait_for(lambda: ("Discoverable", True) in self.sets()))
        self.assertTrue(self.wait_for(lambda: self.adapter().get("Discoverable") is True))
        # obnova casovace (BlueZ znovu spusti odpocet)
        self.clear_log()
        self.assertEqual(self.app.ask("renew", "renew"), "True")
        self.assertTrue(self.wait_for(lambda: self.sets() == [("DiscoverableTimeout", 180)]))
        # zavreni: viditelnost vypnuta, puvodni casovac (0) zpet
        self.clear_log()
        self.app.send("close")
        self.app.proc.wait(10)
        self.assertEqual(self.sets(), [("Discoverable", False), ("DiscoverableTimeout", 0)])
        a = self.adapter()
        self.assertFalse(a.get("Discoverable"))
        self.assertEqual(a.get("DiscoverableTimeout"), 0)

    def test_already_visible_is_left_alone(self):
        self.start_fake()
        self.bluez_set("Discoverable", "<true>")
        self.clear_log()
        self.start(fake=False)
        self.assertTrue(self.wait_for(lambda: self.hint() == "Visible to nearby devices as “luxos-pc”."))
        self.assertEqual(self.sets("Discoverable"), [])
        self.app.ask("renew", "renew")
        self.app.send("close")
        self.app.proc.wait(10)
        self.assertEqual(self.sets(), [])                    # nezaplo ji okno -> nevypina ji
        self.assertTrue(self.adapter().get("Discoverable"))

    def test_power_off_hides(self):
        self.start()
        self.assertTrue(self.wait_for(lambda: self.adapter().get("Discoverable") is True))
        self.clear_log()
        self.app.ask("switch 0")
        self.assertTrue(self.wait_for(lambda: ("Powered", False) in self.sets()))
        self.assertEqual(self.sets()[:2], [("Discoverable", False), ("Powered", False)])
        self.assertTrue(self.wait_for(lambda: self.hint().startswith("Turn on Bluetooth")))
        self.assertFalse(self.adapter().get("Discoverable"))
        # vypnuty Bluetooth: seznamy zarizeni skryte, jmeno pocitace zustava
        d = self.app.dump()
        self.assertFalse(lsl_app.find(d, name="list-nearby")["vis"])
        self.assertFalse(lsl_app.find(d, name="head-paired")["vis"])
        self.assertTrue(lsl_app.find(d, name="name-group")["vis"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "rfkill.log")))
        self.clear_log()
        self.app.ask("switch 1")
        self.assertTrue(self.wait_for(lambda: self.adapter().get("Discoverable") is True))
        self.assertIn(("Discoverable", True), self.sets())
        self.assertTrue(self.wait_for(lambda: {"call": "StartDiscovery"} in
                                      [{"call": c["call"]} for c in self.calls() if "call" in c]))
        with open(os.path.join(self.dir, "rfkill.log")) as f:
            self.assertEqual(f.read(), "unblock bluetooth\n")
        self.app.send("close")
        self.app.proc.wait(10)
        self.assertFalse(self.adapter().get("Discoverable"))

    def test_hint_not_visible(self):
        # BlueZ viditelnost odmitl: okno to nezkousi porad dokola a ukaze, ze pocitac neni viditelny
        self.flag("deny-visible")
        self.start()
        self.assertTrue(self.wait_for(lambda: self.hint() == "Not visible to other devices."))
        time.sleep(0.6)
        self.assertEqual(self.sets("Discoverable"), [("Discoverable", True)])
        self.app.stop()
        self.assertIn("discoverable: ", self.app.stderr())

    # ---- pamet: okno otevrene hodiny (sluchatka pripojena, hledani bezi) ----
    def test_refresh_does_not_leak_rows(self):
        """Prekresleni radky nahradi a stare uvolni (drive zustavaly v pameti: 2,2 GB za 19 h)."""
        self.start()
        nearby = lambda: [w for w in lsl_app.widgets(self.app.dump()) if w.get("text") == "Pixel Test"]  # noqa: E731
        self.assertTrue(self.wait_for(lambda: len(nearby()) == 1))
        for _ in range(50):
            self.app.ask("refresh")
        first = int(self.app.ask("records", "records"))
        for _ in range(200):
            self.app.ask("refresh")
        # kazdy radek ma 2-3 obsluhy: unik by po 200 prekreslenich byl stovky zaznamu (casovac nebo volani
        # D-Bus, ktere prave bezi, je jeden zaznam navic)
        self.assertLessEqual(abs(int(self.app.ask("records", "records")) - first), 2, "obsluhy starych radku zustaly")
        self.assertEqual(len(nearby()), 1)

    def test_scan_pauses_in_background(self):
        """Okno v pozadi po SCAN_IDLE prestane hledat zarizeni, po navratu hleda znovu."""
        self.start()
        state = lambda: json.loads(self.app.ask("page-state", "page-state"))  # noqa: E731
        discovery = lambda what: {"call": what} in [{"call": c["call"]} for c in self.calls() if "call" in c]  # noqa: E731
        self.clear_log()
        self.app.ask("active 0")
        self.assertTrue(state()["scan_timer"])
        self.assertEqual(self.app.ask("pause", "pause"), "False")       # vyprseni SCAN_IDLE
        self.assertTrue(state()["scan_paused"])
        self.assertTrue(discovery("StopDiscovery"))
        self.clear_log()
        self.app.ask("active 1")
        self.assertEqual(state(), {"scan_paused": False, "scan_timer": False, "visible_ours": True, "shown": True})
        self.assertTrue(self.wait_for(lambda: discovery("StartDiscovery")))
        # kratky odskok do jineho okna hledani nezastavi
        self.clear_log()
        self.app.ask("active 0")
        self.app.ask("active 1")
        self.assertFalse(state()["scan_timer"])
        time.sleep(0.2)
        self.assertFalse(discovery("StopDiscovery"))
        # zavreni okna zrusi casovac (proces skonci hned)
        self.app.ask("active 0")
        self.app.send("close")
        self.assertEqual(self.app.proc.wait(10), 0)

    # ---- parovani z okna ----
    def test_pair_connect_and_forget(self):
        self.start()
        self.clear_log()
        self.app.ask("click Connect")
        self.assertTrue(self.wait_for(lambda: lsl_app.find(self.app.dump(), text="Disconnect") is not None))
        methods = [c["call"] for c in self.calls() if "call" in c and c["path"] == DEV]
        self.assertEqual(methods, ["Pair", "Connect"])
        self.assertIn(("Trusted", True), self.sets())
        d = self.app.dump()
        self.assertIn("Phone · Connected", lsl_app.texts(d))
        self.assertIn("Pixel Test", [w.get("text") for w in lsl_app.widgets(d)])
        # sparovane zarizeni je jen v Moje zarizeni
        self.assertIsNone(lsl_app.find(d, text="Connect"))
        self.app.ask("click Disconnect")
        self.assertTrue(self.wait_for(lambda: "Phone · Not connected" in lsl_app.texts(self.app.dump())))
        self.app.ask("click Forget this device")
        self.assertTrue(self.wait_for(lambda: "Pixel Test" not in lsl_app.texts(self.app.dump())))
        self.assertIn({"call": "RemoveDevice", "args": [DEV]},
                      [{"call": c["call"], "args": c["args"]} for c in self.calls() if "call" in c])

    def test_connect_error(self):
        self.flag("fail-connect")
        self.start()
        self.app.ask("click Connect")
        self.assertTrue(self.wait_for(lambda: "Could not connect" in self.dialog_texts()))
        body = [t for t in self.dialog_texts() if t.startswith("Page Timeout")]
        self.assertEqual(body, ["Page Timeout\n\nMake sure the device is on, close by and in pairing mode."])
        self.app.ask("click Close")
        self.assertTrue(self.wait_for(lambda: "Phone · Not connected" in lsl_app.texts(self.app.dump())))

    def test_czech(self):
        self.start(lang="cs_CZ.UTF-8")
        self.assertTrue(self.wait_for(lambda: self.hint() == "Viditelný jako „luxos-pc“, dokud je toto okno otevřené."))
        texts = lsl_app.texts(self.app.dump())
        self.assertIn("Moje zařízení", texts)
        self.assertIn("Zařízení v okolí", texts)
        self.assertIn("Telefon", texts)

    # ---- agent: parovani, ktere zacal telefon ----
    def agent(self):
        senders = [c["sender"] for c in self.calls() if c.get("call") == "RegisterAgent"]
        self.assertTrue(senders)
        return senders[-1]

    def agent_call(self, method, *args):
        return subprocess.Popen(["gdbus", "call", "--address", self.bus.address, "--dest", self.agent(), "--object-path",
                                 "/org/luxos/bluetooth/agent", "--method", "org.bluez.Agent1." + method] + list(args),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def answer(self, call):
        out, err = call.communicate(timeout=10)
        return out.strip() or err.strip()

    def test_agent_phone_pairing(self):
        self.start()
        self.assertTrue(self.wait_for(lambda: any(c.get("call") == "RequestDefaultAgent" for c in self.calls())))
        # ciselne porovnani (telefon i pocitac ukazuji kod)
        call = self.agent_call("RequestConfirmation", DEV, "42")
        self.assertTrue(self.wait_for(lambda: "Pair this device?" in self.dialog_texts()))
        self.assertIn("000042", self.dialog_texts()[1])
        self.app.ask("click Pair")
        self.assertEqual(self.answer(call), "()")
        call = self.agent_call("RequestConfirmation", DEV, "7")
        self.assertTrue(self.wait_for(lambda: "Pair this device?" in self.dialog_texts()))
        self.app.ask("click Cancel")
        self.assertIn("Rejected", self.answer(call))
        # kod na pocitaci, telefon ho zada: BlueZ vola DisplayPasskey s kazdou zadanou cislici - jedno okno,
        # odpoved hned, zavre ho Cancel
        for entered in range(3):
            self.assertEqual(self.answer(self.agent_call("DisplayPasskey", DEV, "123456", str(entered))), "()")
        d = self.app.dump()
        self.assertEqual(len([w for w in d if w["dialog"]]), 1)
        self.assertIn("123456\n\nThen press Enter on it.", lsl_app.texts(d, dialog=True))
        self.assertEqual(self.answer(self.agent_call("Cancel")), "()")
        self.assertTrue(self.wait_for(lambda: not any(w["dialog"] for w in self.app.dump())))
        # PIN od zarizeni jde do Pango markupu: musi se escapovat
        self.answer(self.agent_call("DisplayPinCode", DEV, "<b>12&"))
        self.assertIn("<b>12&\n\nThen press Enter on it.", self.dialog_texts())
        self.answer(self.agent_call("Cancel"))
        # parovani bez kodu: dotaz se jmenem zarizeni, odmitnuti a povoleni
        call = self.agent_call("RequestAuthorization", DEV)
        self.assertTrue(self.wait_for(lambda: "Allow “Pixel Test” to pair with this computer?" in self.dialog_texts()))
        self.app.ask("click Cancel")
        self.assertIn("Rejected", self.answer(call))
        call = self.agent_call("RequestAuthorization", DEV)
        self.assertTrue(self.wait_for(lambda: self.dialog_texts()))
        self.app.ask("click Allow")
        self.assertEqual(self.answer(call), "()")
        # sluzba LuxOS Companion bez dotazu (schvaluje ji aplikace)
        self.assertEqual(self.answer(self.agent_call("AuthorizeService", DEV, "AD9B7C10-6CE5-4F35-9952-728F760FCB70")),
                         "()")
        self.assertFalse(any(w["dialog"] for w in self.app.dump()))


class NoAdapter(Fixture):
    """Pocitac bez adapteru (BlueZ nebezi): jen hlaska, bez Prejmenovat u prazdneho jmena a bez "Hledam…"."""

    def test_window_without_bluez(self):
        self.start(fake=False)
        d = self.app.dump()
        self.assertEqual(lsl_app.find(d, name="hint")["text"], "No Bluetooth adapter was found on this computer.")
        self.assertFalse(lsl_app.find(d, name="name-group")["vis"])
        self.assertFalse(lsl_app.find(d, name="head-nearby")["vis"])
        self.assertFalse(lsl_app.find(d, name="list-paired")["vis"])
        self.assertFalse(lsl_app.find(d, name="list-nearby")["vis"])
        self.assertFalse(lsl_app.find(d, name="power")["sens"])

    def test_window_without_system_bus(self):
        # systemova sbernice vubec neni (kontejner, chroot): okno se otevre s hlaskou, nespadne
        self.start(fake=False)
        self.app.stop()
        env = dict(os.environ, DISPLAY=self.x.display, DBUS_SYSTEM_BUS_ADDRESS="unix:path=" + self.dir + "/none",
                   LC_ALL="C.UTF-8")
        self.app = lsl_app.App([BINARY], env)
        self.assertTrue(self.app.wait(lambda: self.hint() == "No Bluetooth adapter was found on this computer."),
                        self.app.stderr())


if __name__ == "__main__":
    unittest.main()
