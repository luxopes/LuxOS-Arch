#!/usr/bin/env python3
"""Aplikace prepsane z Pythonu do LSL (WP-15) na Waylandu: okno se otevre pod luxwm headless, ma titulek
s zaviracim tlacitkem, nakresli se cele a ovladani funguje stejne jako v X11 (luxos_testctl).

    packages/luxwm/tests/build-host.sh
    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_settings_apps_wl.py -v

Systemove sluzby (BlueZ...) jsou falesne na soukromem dbus-daemonu. LUXOS_WL_SHOTS=adresar ulozi snimky.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lsl_app  # noqa: E402

PKG = HERE.parent
REPO = PKG.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
OUT = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or OUT / "sysroot")
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")
LUXWM = LUXWM_BUILD / "luxwm"


@unittest.skipUnless(LSLC and LUXWM.exists() and WLT.exists(), "chybi lslc, luxwm (build-host.sh) nebo harness")
class SettingsAppsWayland(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(prefix="luxos-apps-wl-", dir=OUT))
        conf = cls.tmp / "luxwm.conf"
        conf.write_text("xwayland = no\n" + "".join(line for line in (REPO / "packages/luxwm/luxwm.conf").read_text()
                                                    .splitlines(True) if not line.startswith("xwayland")))
        cls.conf = conf
        cls.binaries = {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def binary(self, name):
        if name not in self.binaries:
            self.binaries[name] = lsl_app.build(name, str(self.tmp))
        return self.binaries[name]

    def setUp(self):
        self.procs = []
        self.app = None
        name = f"a{os.getpid() % 10000}-{self._testMethodName[5:17]}"
        # list-windows smi jen privilegovany klient (luxwm-msg na allowlistu)
        env = dict(os.environ, WLT_PRIVILEGED=str(LUXWM_BUILD / "luxwm-msg"), WLT_COMPOSITOR_ENV=f"LUXCOMP_VIRTUAL_INPUT=1 LUXWM_SYSTEM_CONFIG={self.conf} "
                                                  f"LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib")
        r = subprocess.run([str(WLT), "start", "--mode", "headless", "--size", "1280x800", "--timeout", "600",
                            "--name", name, "--", str(LUXWM)], env=env, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            self.fail("wlt start: " + r.stdout + r.stderr)
        self.session = Path(r.stdout.strip().splitlines()[-1])
        self.env = {}
        for line in subprocess.run([str(WLT), "env", str(self.session)], capture_output=True, text=True).stdout.splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            self.env[key] = value
        self.env.pop("LD_LIBRARY_PATH", None)
        self.env.update(GDK_BACKEND="wayland", GTK_A11Y="none", GTK_THEME="Adwaita")
        self.bus = lsl_app.Bus()
        self.env["DBUS_SYSTEM_BUS_ADDRESS"] = self.bus.address

    def tearDown(self):
        if self.app:
            self.app.stop()
        for p in self.procs:
            p.terminate()
            p.wait(5)
        self.bus.stop()
        subprocess.run([str(WLT), "stop", str(self.session)], capture_output=True)
        shutil.rmtree(self.session, True)

    def fake(self, argv, **env):
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True, env=dict(os.environ, **env))
        self.procs.append(p)
        self.assertEqual(p.stdout.readline().strip().upper(), "READY")

    def open(self, name, *args, **env):
        self.app = lsl_app.App([self.binary(name), *args], dict(self.env, **env))
        self.assertTrue(self.app.wait(lambda: self.app.dump()), self.app.stderr())
        time.sleep(0.8)

    def shot(self, label):
        """Snimek vystupu: PPM pro wlt stat (pocet barev), PNG do LUXOS_WL_SHOTS."""
        ppm = self.session / f"{label}.ppm"
        subprocess.run([str(WLT), "shot", str(self.session), str(ppm)], check=True, capture_output=True, timeout=30)
        keep = os.environ.get("LUXOS_WL_SHOTS")
        if keep:
            os.makedirs(keep, exist_ok=True)
            subprocess.run([str(WLT), "shot", str(self.session), os.path.join(keep, label + ".png")], capture_output=True,
                           timeout=30)
        return subprocess.run([str(WLT), "stat", str(ppm)], capture_output=True, text=True).stdout

    def windows(self):
        r = subprocess.run([str(LUXWM_BUILD / "luxwm-msg"), "list-windows"], env=self.env, capture_output=True,
                           text=True, timeout=10)
        return r.stdout

    def check_window(self, app_id, title):
        self.assertTrue(self.app.wait(lambda: app_id in self.windows()), self.windows())
        self.assertIn(title, self.windows())
        stat = self.shot(app_id)
        colors = int(stat.split("colors=")[1].split()[0]) if "colors=" in stat else 0
        self.assertGreater(colors, 50, stat)

    def test_bluetooth(self):
        log = self.session / "bluez.jsonl"
        self.fake([sys.executable, str(HERE / "bluetooth/fake_bluez.py")], FAKE_BLUEZ_ADDR=self.bus.address,
                  FAKE_BLUEZ_LOG=str(log))
        self.open("luxos-bluetooth")
        self.check_window("luxos-bluetooth", "Bluetooth")
        d = self.app.dump()
        self.assertEqual(lsl_app.find(d, name="name-label")["text"], "luxos-pc")
        self.assertTrue(self.app.wait(lambda: "while this window is open" in lsl_app.find(self.app.dump(), name="hint")["text"]))
        # ovladani: rename dialog nad oknem, zavreni okna vypne viditelnost
        self.app.send("click Rename…")
        self.assertTrue(self.app.wait(lambda: any(w["dialog"] for w in self.app.dump())))
        self.shot("luxos-bluetooth-rename")
        self.app.ask("entry Wayland PC")
        self.app.ask("click Rename")
        self.assertTrue(self.app.wait(lambda: lsl_app.find(self.app.dump(), name="name-label")["text"] == "Wayland PC"))
        self.app.send("close")
        self.assertEqual(self.app.proc.wait(10), 0)
        sets = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual([(c["set"], c["value"]) for c in sets if "set" in c][-2:],
                         [("Discoverable", False), ("DiscoverableTimeout", 0)])

    def test_fingerprint(self):
        calls = self.session / "fprintd.log"
        self.fake([sys.executable, str(HERE / "fingerprint/fake_fprintd.py"), "--enrolled", "left-thumb", "--stages", "5",
                   "--state", str(calls)], DBUS_SESSION_BUS_ADDRESS=self.bus.address)
        self.open("luxos-fingerprint", LUXOS_FPRINT_BUS=self.bus.address)
        rows = lambda: [w["text"] for w in lsl_app.widgets(self.app.dump()) if w.get("name") == "finger-row" and w["vis"]]  # noqa: E731
        self.assertTrue(self.app.wait(lambda: rows() == ["Left thumb"]))
        self.check_window("luxos-fingerprint", "Fingerprint Login")
        self.app.ask("enroll right-thumb")
        self.assertTrue(self.app.wait(lambda: lsl_app.find(self.app.dump(), name="enroll-status")["text"] == "Fingerprint added"))
        self.shot("luxos-fingerprint-done")
        self.app.ask("click Done")
        self.assertTrue(self.app.wait(lambda: rows() == ["Right thumb", "Left thumb"]))
        c = calls.read_text().split("\n")
        self.assertEqual(c.count("Claim "), c.count("Release"))


if __name__ == "__main__":
    unittest.main()
