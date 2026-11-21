#!/usr/bin/env python3
"""LuxOS - stranky Nastaveni Baterie a napajeni, Bluetooth, Otisk prstu a Firewall (drive luxos-power,
luxos-bluetooth, luxos-fingerprint, luxos-firewall-settings): odkazy (stary program, `luxos-settings STRANKA`,
druhe spusteni prepne stranku bezici instance pres D-Bus), odchod ze stranky (Bluetooth prestane byt viditelny,
ctecka otisku se uvolni) a jeden ucinek kazde stranky pres UI.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_settings_ports_a.py -v

Systemove sluzby jsou falesne na soukromych dbus-daemonech: UPower a power-profiles-daemon
(test_luxos_power_app.py --serve), BlueZ (bluetooth/fake_bluez.py), fprintd (fingerprint/fake_fprintd.py).
pkexec a luxos-firewall jsou falesne skripty se stavem v JSON. Okno ve vlastnim Xvfb, vlastni sbernice relace;
Wayland cast v luxwm headless (LUXWM_BUILD, sysroot harnessu wl-test).
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
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402
import lsl_app_harness as h  # noqa: E402

TMP = None
BIN = {}
XVFB = None
ALIASES = ("luxos-settings", "luxos-power", "luxos-bluetooth", "luxos-fingerprint", "luxos-firewall-settings")
A = "/org/bluez/hci0"

# luxos-firewall: stav v $FW_STATE (JSON), zmeny jen prepisou "enable"/"active" a pridaji vyjimku
FIREWALL = r'''#!/usr/bin/env python3
import json, os, sys
path = os.environ["FW_STATE"]
st = json.load(open(path))
a = sys.argv[1:]
if a[:2] == ["status", "--json"]:
    print(json.dumps(st))
    sys.exit(0)
if a == ["on"] or a == ["off"]:
    st["enable"] = st["active"] = a[0] == "on"
elif a and a[0] == "allow":
    port, _, proto = a[1].partition("/")
    st["allow"].append({"port": int(port), "proto": proto or "tcp", "from": a[a.index("--from") + 1]})
else:
    sys.exit(2)
json.dump(st, open(path, "w"))
'''
PKEXEC = '#!/bin/sh\necho "pkexec $*" >> "$FAKE_LOG"\nexec "$@"\n'
FAKE = '#!/bin/sh\necho "$(basename "$0") $*" >> "$FAKE_LOG"\n'


def setUpModule():
    global TMP, XVFB
    TMP = tempfile.mkdtemp(prefix="luxos-ports-a-", dir=luxos_testguard._private_dir())
    for name in ALIASES:
        BIN[name] = lsl_app.build(name, TMP)
    XVFB = lsl_app.Xvfb()


def tearDownModule():
    if XVFB:
        XVFB.stop()
    if TMP:
        shutil.rmtree(TMP, True)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(dir=TMP)
        self.bin = os.path.join(self.home, "bin")
        os.mkdir(self.bin)
        self.log = os.path.join(self.home, "fake.log")
        open(self.log, "w").close()
        for name in ("xfconf-query", "luxos-powersaver", "luxos-gpu", "xfce4-power-manager-settings", "rfkill"):
            self.write_exec(name, FAKE)
        self.write_exec("pkexec", PKEXEC)
        self.firewall = self.write_exec("luxos-firewall", FIREWALL)
        self.fw_state = os.path.join(self.home, "firewall.json")
        self.set_firewall(enable=False)
        self.session = lsl_app.Bus()
        self.addCleanup(self.session.stop)
        # "systemova" sbernice testu (falesny UPower, BlueZ, fprintd)
        self.system = lsl_app.Bus()
        self.addCleanup(self.system.stop)
        self.procs = []
        self.app = None

    def tearDown(self):
        if self.app:
            self.app.stop()
        for p in self.procs:
            p.terminate()
            p.wait(5)

    def write_exec(self, name, text):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o755)
        return path

    def set_firewall(self, enable):
        with open(self.fw_state, "w") as f:
            json.dump({"enable": enable, "active": enable, "allow": [], "blocked": [],
                       "rules": [{"name": "SSH", "port": 22, "proto": "tcp", "from": "lan"}]}, f)

    def env(self, **extra):
        env = dict(os.environ, HOME=self.home, XDG_CONFIG_HOME=os.path.join(self.home, ".config"),
                   XDG_CACHE_HOME=os.path.join(self.home, ".cache"), XDG_DATA_HOME="", LANG="C.UTF-8", LC_ALL="C.UTF-8",
                   PATH=self.bin + os.pathsep + os.environ["PATH"], DBUS_SESSION_BUS_ADDRESS=self.session.address,
                   DBUS_SYSTEM_BUS_ADDRESS=self.system.address, LUXOS_FIREWALL_CLI=self.firewall,
                   FW_STATE=self.fw_state, FAKE_LOG=self.log, LUXOS_I18N_DIR=lsl_app.I18N, NO_AT_BRIDGE="1",
                   GIO_USE_VFS="local", DISPLAY=XVFB.display, **extra)
        luxos_testguard.check_env(env)
        return env

    def start(self, name, *args, **extra):
        self.app = lsl_app.App([BIN[name], *args], self.env(**extra))
        self.assertTrue(self.app.wait(lambda: self.app.dump()), self.app.stderr())

    def fake(self, argv, ready, **env):
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True, env=dict(os.environ, **env))
        self.procs.append(p)
        self.assertEqual(p.stdout.readline().strip().lower(), ready)

    def state(self):
        return json.loads(self.app.ask("state", "state"))

    def title(self):
        return [w["title"] for w in self.app.dump() if not w["dialog"]]

    def texts(self):
        return lsl_app.texts(self.app.dump())

    def calls(self):
        with open(self.log) as f:
            return f.read().splitlines()


class DeepLinks(Fixture):
    def test_old_program_opens_its_page(self):
        self.start("luxos-power")
        self.assertEqual(self.state()["page"], "power")
        self.assertEqual(self.title(), ["Battery & Power"])
        self.assertIn("Power mode", self.texts())

    def test_settings_with_page_name(self):
        self.start("luxos-settings", "bluetooth")
        self.assertEqual(self.state()["page"], "bluetooth")
        self.assertEqual(self.title(), ["Bluetooth"])
        # bez BlueZ na sbernici
        self.assertTrue(self.app.wait(lambda: lsl_app.find(self.app.dump(), name="hint")["text"]
                                      == "No Bluetooth adapter was found on this computer."))

    def test_second_launch_switches_page(self):
        self.start("luxos-settings", "power")
        self.assertEqual(self.state()["page"], "power")
        for name, args, page, title in (("luxos-firewall-settings", [], "firewall", "Firewall"),
                                        ("luxos-settings", ["fingerprint"], "fingerprint", "Fingerprint")):
            with self.subTest(name=name):
                r = subprocess.run([BIN[name], *args], env=self.env(), capture_output=True, text=True,
                                   stdin=subprocess.DEVNULL, timeout=60)
                # druha instance jen preda stranku a skonci
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(self.app.wait(lambda: self.state()["page"] == page))
                self.assertEqual(self.title(), [title])
        self.assertEqual(sorted(self.state()["built"]), ["fingerprint", "firewall", "power"])


class Power(Fixture):
    def start_upower(self, profile="balanced"):
        self.upower_state = Path(self.home) / "upower.json"
        self.upower_log = Path(self.home) / "upower.log"
        bat = {"Type": 2, "PowerSupply": True, "IsPresent": True, "Percentage": 64.0, "State": 2, "TimeToEmpty": 7200,
               "EnergyRate": 8.5, "Energy": 32.0, "EnergyFull": 50.0, "EnergyFullDesign": 55.0}
        self.upower_state.write_text(json.dumps({"devices": {"/bat0": bat}, "profile": profile, "display": {},
                                                 "profiles": ["power-saver", "balanced", "performance"], "history": {}}))
        p = subprocess.Popen([sys.executable, os.path.join(HERE, "test_luxos_power_app.py"), "--serve", self.system.address,
                              str(self.upower_state), str(self.upower_log)], env={"PATH": os.environ["PATH"], "HOME": self.home})
        self.procs.append(p)
        for _ in range(100):
            if self.upower_log.exists() and "ready" in self.upower_log.read_text():
                break
            time.sleep(0.05)

    def pst(self):
        return json.loads(self.app.ask("page-state", "page-state"))

    def reads(self):
        return self.upower_log.read_text().count("getall /bat0")

    def test_power_mode_reaches_power_profiles(self):
        self.start_upower()
        self.start("luxos-power")
        self.assertIn("64 %", self.texts())
        self.assertEqual(self.pst(), {"mode": "balanced", "saver": False, "timers": 2})
        self.app.ask("mode performance")
        self.assertTrue(self.app.wait(lambda: "set ActiveProfile performance" in self.upower_log.read_text()))
        self.assertEqual(json.loads(self.upower_state.read_text())["profile"], "performance")
        self.assertEqual(self.pst()["mode"], "performance")
        # Sporic baterie pres prepinac radku
        self.app.ask("switch Battery Saver = on")
        self.assertTrue(self.app.wait(lambda: "luxos-powersaver on" in self.calls()))

    def test_refresh_only_while_shown(self):
        self.start_upower()
        self.start("luxos-power")
        self.app.ask("page firewall")
        before = self.reads()
        # obnova kazdych 5 s bezi jen na zobrazene strance
        time.sleep(6)
        self.assertEqual(self.reads(), before)
        # profil zmeneny jinde (Ovladaci centrum) je po navratu videt hned
        st = json.loads(self.upower_state.read_text())
        st["profile"] = "power-saver"
        self.upower_state.write_text(json.dumps(st))
        self.app.ask("page power")
        self.assertEqual(self.pst(), {"mode": "power-saver", "saver": False, "timers": 2})
        self.assertGreater(self.reads(), before)


class Bluetooth(Fixture):
    def start_bluez(self):
        self.bluez_log = os.path.join(self.home, "bluez.jsonl")
        open(self.bluez_log, "w").close()
        self.fake([sys.executable, os.path.join(HERE, "bluetooth/fake_bluez.py")], "ready",
                  FAKE_BLUEZ_ADDR=self.system.address, FAKE_BLUEZ_LOG=self.bluez_log)

    def sets(self):
        with open(self.bluez_log) as f:
            return [(c["set"], c["value"]) for c in map(json.loads, f.read().splitlines()) if "set" in c]

    def discoverable(self):
        from gi.repository import Gio, GLib
        bus = Gio.DBusConnection.new_for_address_sync(
            self.system.address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
            | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        try:
            return bus.call_sync("org.bluez", A, "org.freedesktop.DBus.Properties", "Get",
                                 GLib.Variant("(ss)", ("org.bluez.Adapter1", "Discoverable")), None, 0, 3000,
                                 None).unpack()[0]
        finally:
            bus.close_sync(None)

    def test_visible_only_while_page_is_shown(self):
        self.start_bluez()
        self.start("luxos-bluetooth")
        self.assertTrue(self.app.wait(self.discoverable))
        self.assertEqual(self.sets()[:2], [("DiscoverableTimeout", 180), ("Discoverable", True)])
        # jina stranka: viditelnost vypnuta, puvodni casovac zpet, hledani zastavene
        self.app.ask("page power")
        self.assertTrue(self.app.wait(lambda: not self.discoverable()))
        self.assertEqual(self.sets()[-2:], [("Discoverable", False), ("DiscoverableTimeout", 0)])
        with open(self.bluez_log) as f:
            self.assertIn("StopDiscovery", [json.loads(line).get("call") for line in f])
        # zpet na Bluetooth: znovu viditelny
        self.app.ask("page bluetooth")
        self.assertTrue(self.app.wait(self.discoverable))
        self.assertEqual(json.loads(self.app.ask("page-state", "page-state"))["shown"], True)
        # zavreni okna na jine strance uz nic nevypina (stranka to udelala pri odchodu)
        self.app.ask("page firewall")
        self.assertTrue(self.app.wait(lambda: not self.discoverable()))
        count = len(self.sets())
        self.app.send("page bluetooth")
        self.assertTrue(self.app.wait(self.discoverable))
        self.app.ask("close")
        self.assertEqual(self.app.proc.wait(10), 0)
        self.assertFalse(self.discoverable())
        self.assertGreater(len(self.sets()), count)

    def test_power_switch_turns_adapter_off(self):
        self.start_bluez()
        self.start("luxos-settings", "bluetooth")
        self.assertTrue(self.app.wait(self.discoverable))
        self.app.ask("switch 0")
        self.assertTrue(self.app.wait(lambda: ("Powered", False) in self.sets()))
        self.assertTrue(self.app.wait(lambda: lsl_app.find(self.app.dump(), name="hint")["text"]
                                      .startswith("Turn on Bluetooth")))


class Fingerprint(Fixture):
    def start_fprintd(self, *args):
        self.fp_log = os.path.join(self.home, "fprintd.log")
        self.fake([sys.executable, os.path.join(HERE, "fingerprint/fake_fprintd.py"), "--state", self.fp_log, *args],
                  "ready", DBUS_SESSION_BUS_ADDRESS=self.system.address)

    def fp_calls(self):
        try:
            with open(self.fp_log) as f:
                return f.read().split("\n")
        except OSError:
            return []

    def pst(self):
        return json.loads(self.app.ask("page-state", "page-state"))

    def test_leaving_page_releases_reader(self):
        self.start_fprintd("--stages", "40", "--enrolled", "left-thumb")
        self.start("luxos-fingerprint", LUXOS_FPRINT_BUS=self.system.address)
        self.assertTrue(self.app.wait(lambda: self.pst()["page"] == "main"))
        self.app.ask("enroll right-thumb")
        self.assertTrue(self.app.wait(lambda: self.pst()["passed"] >= 1 and self.pst()["claimed"]))
        self.app.ask("page power")
        self.assertTrue(self.app.wait(lambda: "Release" in self.fp_calls()))
        c = self.fp_calls()
        self.assertIn("EnrollStop", c)
        self.assertEqual(c.count("Claim "), c.count("Release"))
        # po navratu seznam otisku, ne rozpracovane pridavani
        self.app.ask("page fingerprint")
        st = self.pst()
        self.assertEqual((st["page"], st["enrolling"], st["claimed"]), ("main", False, False))
        # znovu pridat jde (ctecka neni obsazena)
        self.app.ask("enroll right-thumb")
        self.assertTrue(self.app.wait(lambda: self.fp_calls().count("Claim ") == 2 and self.pst()["passed"] >= 1))

    def test_remove_through_ui(self):
        self.start_fprintd("--enrolled", "right-thumb")
        self.start("luxos-settings", "fingerprint", LUXOS_FPRINT_BUS=self.system.address)
        rows = lambda: [w["text"] for w in lsl_app.widgets(self.app.dump()) if w.get("name") == "finger-row"]  # noqa: E731
        self.assertTrue(self.app.wait(lambda: rows() == ["Right thumb"]))
        self.app.send("click Remove")
        self.assertTrue(self.app.wait(lambda: any(w["dialog"] for w in self.app.dump())))
        self.app.ask("respond -5")
        self.assertTrue(self.app.wait(lambda: rows() == ["No fingerprints added yet."]))
        self.assertIn("DeleteEnrolledFinger right-thumb", self.fp_calls())
        self.assertTrue(self.app.wait(lambda: self.fp_calls().count("Claim ") == self.fp_calls().count("Release")))


class Firewall(Fixture):
    ON = "On - the computer is protected."
    OFF = "Off - the computer accepts connections from the network."

    def test_toggle_runs_pkexec_firewall(self):
        self.start("luxos-firewall-settings")
        self.assertTrue(self.app.wait(lambda: self.OFF in self.texts()))
        self.assertIn("SSH (remote login)", self.texts())
        self.app.ask("switch Firewall = on")
        self.assertTrue(self.app.wait(lambda: "pkexec %s on" % self.firewall in self.calls()))
        self.assertTrue(self.app.wait(lambda: self.ON in self.texts()))
        self.assertTrue(json.loads(Path(self.fw_state).read_text())["enable"])
        # vlastni vyjimka
        self.app.ask("fw-port 8080")
        self.app.ask("click Allow")
        self.assertTrue(self.app.wait(lambda: "pkexec %s allow 8080/tcp --from lan" % self.firewall in self.calls()))
        self.assertTrue(self.app.wait(lambda: "8080/TCP" in self.texts()))

    def test_status_refreshed_on_show(self):
        self.start("luxos-settings", "firewall")
        self.assertTrue(self.app.wait(lambda: self.OFF in self.texts()))
        self.app.ask("page power")
        # zmena mimo okno (luxos-firewall v Terminalu)
        self.set_firewall(enable=True)
        self.app.ask("page firewall")
        self.assertIn(self.ON, self.texts())
        self.assertFalse([c for c in self.calls() if c.startswith("pkexec")])


@unittest.skipUnless(h.HAVE_WAYLAND, "luxwm (LUXWM_BUILD) or wl-test sysroot missing")
class Wayland(unittest.TestCase):
    """Firewall v luxwm headless: prepinac funguje stejne jako v X11 (Baterie na Waylandu: test_luxos_power_app)."""

    def test_firewall_on_wayland(self):
        tmp = Path(tempfile.mkdtemp(prefix="ports-a-wl-", dir=h.private_dir()))
        env = h.base_env(tmp)
        fakes = h.fake_bin(tmp / "bin", [])
        (fakes / "pkexec").write_text(PKEXEC)
        (fakes / "pkexec").chmod(0o755)
        (fakes / "luxos-firewall").write_text(FIREWALL)
        (fakes / "luxos-firewall").chmod(0o755)
        state = tmp / "firewall.json"
        state.write_text(json.dumps({"enable": False, "active": False, "allow": [], "blocked": [], "rules": []}))
        env.update(PATH=f"{fakes}:{os.environ['PATH']}", LUXOS_FIREWALL_CLI=str(fakes / "luxos-firewall"),
                   FW_STATE=str(state))
        app = h.WaylandApp([str(h.build("luxos-settings")), "firewall"], env,
                           ["dump", "switch Firewall on", "wait 1500", "dump", "quit"], tmp=tmp)
        self.addCleanup(app.close)
        first = app.wait_dump(1)
        self.assertIn("GtkLabel\tOff - the computer accepts connections from the network.", first)
        second = app.wait_dump(2)
        self.assertIn(f"pkexec {fakes}/luxos-firewall on", (tmp / "fake.log").read_text().splitlines())
        self.assertIn("GtkLabel\tOn - the computer is protected.", second)


if __name__ == "__main__":
    unittest.main()
