#!/usr/bin/env python3
"""LuxOS - Baterie a napajeni (files/lsl/luxos-power.lsl, luxos_power_model.lsl) proti falesnemu UPower
a power-profiles-daemon na soukrome systemove sbernici; v Xvfb a v luxwm headless.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -p MemorySwapMax=0 -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_power_app.py -v

Falesne sluzby (rezim --serve tohoto souboru) ctou stav z JSON pri kazdem volani a volani Set zapisuji
do logu; xfconf-query, luxos-powersaver a luxos-gpu jsou falesne programy. Model (historie pro grafy, dve
baterie, texty stavu) testuje tests/lsl/luxos-power-model-test.lsl bez displeje.
Testy luxos-powersaver, MPRIS a hlidani prehravani zustavaji v test_luxos_power.py.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
UP = "org.freedesktop.UPower"
PPD = "org.freedesktop.UPower.PowerProfiles"
DISPLAY_DEVICE = "/org/freedesktop/UPower/devices/DisplayDevice"

BUS_CONF = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig><type>session</type><listen>unix:path={path}</listen><auth>EXTERNAL</auth>
<policy context="default"><allow send_destination="*" eavesdrop="true"/><allow eavesdrop="true"/><allow own="*"/></policy>
</busconfig>
"""
XML = """<node>
<interface name="org.freedesktop.UPower"><method name="EnumerateDevices"><arg type="ao" direction="out"/></method></interface>
<interface name="org.freedesktop.UPower.Device"><method name="GetHistory"><arg type="s" direction="in"/>
<arg type="u" direction="in"/><arg type="u" direction="in"/><arg type="a(udu)" direction="out"/></method></interface>
<interface name="org.freedesktop.DBus.Properties"><method name="GetAll"><arg type="s" direction="in"/>
<arg type="a{sv}" direction="out"/></method><method name="Set"><arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="v" direction="in"/></method></interface></node>"""
TYPES = {"Type": "u", "State": "u", "PowerSupply": "b", "IsPresent": "b", "ChargeCycles": "i", "TimeToEmpty": "x",
         "TimeToFull": "x", "Model": "s", "Vendor": "s"}


def serve(address, state_path, log_path):
    """Falesny UPower + power-profiles-daemon (spousti test v samostatnem procesu)."""
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    def state():
        return json.loads(Path(state_path).read_text())

    def log(line):
        with open(log_path, "a") as f:
            f.write(line + "\n")

    def variant(key, value):
        return GLib.Variant(TYPES.get(key, "d"), value)

    def on_call(conn, sender, path, iface, method, params, inv):
        st = state()
        if method == "EnumerateDevices":
            inv.return_value(GLib.Variant("(ao)", (list(st["devices"]),)))
        elif method == "GetHistory":
            kind, _span, points = params.unpack()
            log(f"history {path} {kind} {points}")
            inv.return_value(GLib.Variant("(a(udu))", ([tuple(r) for r in st["history"].get(kind, [])],)))
        elif method == "GetAll" and path.startswith("/org/freedesktop/UPower/PowerProfiles"):
            props = {"ActiveProfile": GLib.Variant("s", st["profile"]),
                     "Profiles": GLib.Variant("aa{sv}", [{"Profile": GLib.Variant("s", p)} for p in st["profiles"]])}
            inv.return_value(GLib.Variant("(a{sv})", (props,)))
        elif method == "GetAll":
            dev = st.get("display", {}) if path == DISPLAY_DEVICE else st["devices"].get(path, {})
            inv.return_value(GLib.Variant("(a{sv})", ({k: variant(k, v) for k, v in dev.items()},)))
        elif method == "Set":
            _iface, prop, value = params.unpack()
            log(f"set {prop} {value}")
            st["profile"] = value
            Path(state_path).write_text(json.dumps(st))
            inv.return_value(None)

    conn = Gio.DBusConnection.new_for_address_sync(address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                                                   | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
    node = Gio.DBusNodeInfo.new_for_xml(XML)
    paths = ["/org/freedesktop/UPower", DISPLAY_DEVICE, "/org/freedesktop/UPower/PowerProfiles"]
    paths += [p for p in state()["devices"]]
    for p in paths:
        for i in node.interfaces:
            conn.register_object(p, i, on_call, None, None)
    for name in (UP, PPD):
        conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                       GLib.Variant("(su)", (name, 4)), None, 0, -1, None)
    log("ready")
    GLib.MainLoop().run()


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--serve":
    serve(*sys.argv[2:5])
    sys.exit(0)

import lsl_app_harness as h  # noqa: E402

BAT = {"Type": 2, "PowerSupply": True, "IsPresent": True, "Percentage": 81.0, "State": 1, "TimeToFull": 1800,
       "TimeToEmpty": 0, "EnergyRate": 12.25, "Energy": 40.5, "EnergyFull": 50.0, "EnergyFullDesign": 62.5,
       "ChargeCycles": 37}
AC = {"Type": 1, "PowerSupply": True}
FAKES = ["xfconf-query", "luxos-powersaver", "luxos-gpu", "xfce4-power-manager-settings"]
PM_LIST = ("/xfce4-power-manager/dpms-on-ac-off 10\n/xfce4-power-manager/dpms-on-battery-off 5\n"
           "/xfce4-power-manager/inactivity-on-ac 14\n/xfce4-power-manager/inactivity-on-battery 45\n"
           "/xfce4-power-manager/lid-action-on-battery 3")


def setUpModule():
    if not h.lslc_ok():
        raise unittest.SkipTest("lslc 0.11 is not installed")
    h.build("luxos-power")


def find(dump, kind, text):
    for i, line in enumerate(dump):
        if line == f"GtkLabel\t{text}":
            for nxt in dump[i + 1:i + 4]:
                if nxt.startswith(kind + "\t"):
                    return nxt.split("\t")[1:]
    return None


def labels(dump):
    return [line.split("\t")[1] for line in dump if line.startswith("GtkLabel\t")]


class Model(unittest.TestCase):
    def test_model(self):
        out = Path(tempfile.mkdtemp(prefix="pmodel-", dir=h.private_dir())) / "t"
        r = subprocess.run([h.LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(h.LSL_DIR),
                            str(HERE / "lsl/luxos-power-model-test.lsl"), str(out)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        r = subprocess.run([str(out)], capture_output=True, text=True, timeout=30,
                           env={"LANG": "C", "LUXOS_I18N_DIR": str(h.I18N), "PATH": os.environ["PATH"]})
        self.assertEqual([line for line in r.stdout.splitlines() if not line.startswith("ok ")], [])
        self.assertEqual(r.returncode, 0)
        self.assertGreater(len(r.stdout.splitlines()), 25)


class Base(unittest.TestCase):
    backend = h.X11App

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="power-", dir=h.private_dir()))
        self.env = h.base_env(self.tmp)
        self.env["PATH"] = str(h.fake_bin(self.tmp / "bin", FAKES)) + ":" + os.environ["PATH"]
        self.env["FAKE_OUT_xfconf_query"] = PM_LIST
        self.state = self.tmp / "state.json"
        self.log = self.tmp / "bus.log"
        self.config = self.tmp / "config/luxos"
        self.config.mkdir(parents=True)

    def start_bus(self, devices=None, profile="balanced", profiles=("power-saver", "balanced", "performance"),
                  history=None, display=None):
        self.state.write_text(json.dumps({"devices": devices if devices is not None else {"/bat0": BAT, "/ac": AC},
                                          "profile": profile, "profiles": list(profiles), "display": display or {},
                                          "history": history or {}}))
        sock = self.tmp / "system_bus"
        conf = self.tmp / "bus.conf"
        conf.write_text(BUS_CONF.format(path=sock))
        self.bus = subprocess.Popen(["dbus-daemon", "--config-file", str(conf), "--nofork"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.bus.terminate)
        for _ in range(100):
            if sock.exists():
                break
            time.sleep(0.05)
        address = f"unix:path={sock}"
        self.service = subprocess.Popen([sys.executable, __file__, "--serve", address, str(self.state), str(self.log)],
                                        env={"PATH": os.environ["PATH"], "HOME": str(self.tmp)})
        self.addCleanup(self.service.terminate)
        for _ in range(100):
            if self.log.exists() and "ready" in self.log.read_text():
                break
            time.sleep(0.05)
        self.env["DBUS_SYSTEM_BUS_ADDRESS"] = address

    def run_app(self, script):
        app = self.backend([str(h.build("luxos-power"))], self.env, script, tmp=self.tmp)
        self.addCleanup(app.close)
        return app

    def calls(self):
        log = self.tmp / "fake.log"
        return log.read_text().splitlines() if log.exists() else []

    def bus_log(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


@unittest.skipUnless(h.HAVE_X11, "Xvfb, xdotool or dbus-run-session missing")
class X11(Base):
    def test_battery_from_upower(self):
        now = int(time.time())
        self.start_bus(history={"charge": [[now - 3600, 70.0, 1], [now - 600, 80.0, 1]]})
        d = self.run_app(["dump", "quit"]).wait_dump()
        texts = labels(d)
        self.assertIn("81 %", texts)
        self.assertIn("Charging · full in 30 min", texts)
        self.assertIn("12,2 W", texts)              # 12,25 -> 12,2 jako f"{:.1f}"; LANG=C ma carku jako Python
        self.assertIn("charging power", texts)
        self.assertIn("80 %", texts)                # zdravi 50 / 62,5
        self.assertIn("37", texts)
        self.assertNotIn("This computer runs on mains power - there is no battery.", texts)
        # graf: surove zaznamy upower (points vetsi nez jejich pocet)
        self.assertIn("history /bat0 charge 100000", self.bus_log())
        self.assertEqual(find(d, "GtkComboBoxText", "Turn off the screen on battery after"), ["5"])
        self.assertEqual(find(d, "GtkComboBoxText", "Sleep on battery after"), ["45"])     # mimo nabidku: "45 minut"
        self.assertEqual(find(d, "GtkComboBoxText", "When the lid is closed"), ["3"])
        self.assertIn("GtkRadioButton\tBalanced [current]", d)

    def test_two_batteries_and_no_battery(self):
        bat1 = dict(BAT, Percentage=20.0, State=2, ChargeCycles=0)
        self.start_bus(devices={"/bat0": BAT, "/bat1": bat1, "/ac": AC},
                       display={"Type": 2, "Percentage": 55.4, "State": 2, "TimeToEmpty": 5400, "EnergyRate": 9.0})
        d = self.run_app(["dump", "quit"]).wait_dump()
        self.assertIn("55 %", labels(d))
        self.assertIn("On battery · about 1 h 30 min left", labels(d))

    def test_no_battery(self):
        self.start_bus(devices={"/ac": AC})
        d = self.run_app(["dump", "quit"]).wait_dump()
        self.assertIn("This computer runs on mains power - there is no battery.", labels(d))
        self.assertNotIn("Battery health", labels(d))

    def test_only_available_profiles(self):
        self.start_bus(profiles=("power-saver", "balanced"))
        d = self.run_app(["dump", "quit"]).wait_dump()
        self.assertNotIn("Performance", labels(d))
        self.assertIn("Power Saver", labels(d))

    def test_performance_turns_saver_off(self):
        self.start_bus()
        (self.config / "powersaver").write_text("")
        app = self.run_app(["dump", "click Performance", "wait 300", "dump", "quit"])
        self.assertEqual(find(app.wait_dump(1), "GtkSwitch", "Battery Saver"), ["on"])
        d = app.wait_dump(2)
        self.assertIn("set ActiveProfile performance", self.bus_log())
        self.assertIn("luxos-powersaver off", self.calls())
        self.assertEqual(find(d, "GtkSwitch", "Battery Saver"), ["off"])
        self.assertIn("GtkRadioButton\tPerformance [current]", d)

    def test_mode_and_saver_follow_system(self):
        # Sporic zapnuty jinde (Ovladaci centrum, 20 %) prepne profil na Usporny - okno to ukaze
        self.start_bus()
        app = self.run_app(["dump", "wait 6000", "dump", "switch Battery Saver off", "wait 5500", "dump", "quit"])
        d = app.wait_dump(1)
        self.assertIn("GtkRadioButton\tBalanced [current]", d)
        st = json.loads(self.state.read_text())
        st["profile"] = "power-saver"
        self.state.write_text(json.dumps(st))
        (self.config / "powersaver").write_text("")
        d = app.wait_dump(2)
        self.assertIn("GtkRadioButton\tPower Saver [current]", d)
        self.assertEqual(find(d, "GtkSwitch", "Battery Saver"), ["on"])
        self.assertFalse([line for line in self.bus_log() if line.startswith("set ")])   # jen zobrazeni
        self.assertNotIn("luxos-powersaver on", self.calls())
        # uzivatel Sporic prave vypnul - soubor jeste existuje, prepinac se nevrati zpet
        d = app.wait_dump(3, timeout=30)
        self.assertEqual(self.calls().count("luxos-powersaver off"), 1)
        self.assertEqual(find(d, "GtkSwitch", "Battery Saver"), ["off"])

    def test_xfconf_and_override(self):
        self.start_bus()
        app = self.run_app(["combo Turn off the screen on battery after 15", "combo When the lid is closed 0",
                            "wait 300", "quit"])
        app.wait_exit()
        log = self.calls()
        self.assertIn("xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/dpms-on-battery-off -n -t uint -s 15", log)
        for prop in ("lid-action-on-battery", "lid-action-on-ac"):
            self.assertIn(f"xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/{prop} -n -t uint -s 0", log)
        # behem prehravani: puvodni hodnota v sleep-override, xfconf se nemeni (luxos-hub ji pak vrati)
        (self.config / "sleep-override").write_text("inactivity-on-ac=30\n")
        (self.tmp / "fake.log").unlink()
        app = self.run_app(["dump", "combo Sleep on power adapter after 60", "wait 300", "quit"])
        d = app.wait_dump()
        app.wait_exit()
        self.assertEqual(find(d, "GtkComboBoxText", "Sleep on power adapter after"), ["30"])
        self.assertEqual((self.config / "sleep-override").read_text(), "inactivity-on-ac=60\n")
        self.assertFalse([c for c in self.calls() if "inactivity-on-ac" in c])

    def test_flags(self):
        self.start_bus()
        app = self.run_app(["switch Turn on automatically at 20 % on", "switch Lower the screen to 60 Hz on",
                            "switch Stay awake while music or video is playing off", "switch Battery Saver on",
                            "wait 300", "quit"])
        app.wait_exit()
        for name in ("powersaver-auto", "powersaver-60hz", "sleep-while-playing"):
            self.assertTrue((self.config / name).exists(), name)
        self.assertIn("luxos-powersaver on", self.calls())

    def test_gpu_line(self):
        self.start_bus(profile="performance")
        self.env["FAKE_OUT_luxos_gpu"] = "gpu=nvidia\nname=GeForce GTX 1650"
        d = self.run_app(["dump", "quit"]).wait_dump()
        self.assertIn("Graphics: GeForce GTX 1650 for games and demanding apps", labels(d))

    def test_demo_cards_and_top(self):
        self.env["LUXOS_POWER_DEMO"] = "full"
        d = self.run_app(["dump", "quit"]).wait_dump()
        texts = labels(d)
        self.assertIn("Charging complete", texts)
        self.assertIn("running on the power adapter", texts)
        self.assertNotIn("-", texts)
        self.assertNotIn("Charge cycles", texts)
        self.assertEqual([line for line in d if line.startswith("GtkScrolledWindow")], ["GtkScrolledWindow\t0"])
        self.assertFalse(self.log.exists())          # ukazkovy rezim nesaha na sbernici

    def test_window_fits(self):
        self.env["LUXOS_POWER_DEMO"] = "1"
        for size in ((1366, 768), (1280, 800)):
            with self.subTest(size=size):
                app = h.X11App([str(h.build("luxos-power"))], self.env, ["wait 600000"], size=size)
                self.addCleanup(app.close)
                win = app.window("Battery & Power")
                self.assertLessEqual(win["height"], size[1] - 16, win)
                self.assertGreaterEqual(app.hints(win["id"])[1], 300)

    def test_czech(self):
        self.env.update(LANG="cs_CZ.UTF-8", LUXOS_POWER_DEMO="1")
        d = self.run_app(["dump", "quit"]).wait_dump()
        self.assertIn("7,8 W", labels(d))
        self.assertIn("Spořič baterie", labels(d))


@unittest.skipUnless(h.HAVE_WAYLAND, "luxwm (LUXWM_BUILD) or wl-test sysroot missing")
class Wayland(Base):
    backend = h.WaylandApp

    def test_wayland_without_xfce_power_manager(self):
        self.start_bus()
        d = self.run_app(["dump", "quit"]).wait_dump()
        self.assertIn("81 %", labels(d))
        self.assertIn("Stay awake while music or video is playing", labels(d))
        self.assertNotIn("When the lid is closed", labels(d))
        self.assertNotIn("GtkButton\tAdvanced Power Settings…", d)
        self.assertFalse([c for c in self.calls() if c.startswith("xfconf-query")])


if __name__ == "__main__":
    unittest.main()
