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

    def test_profile_picture(self):
        # kamera = videotestsrc (LUXOS_CAMERA_TEST), uzly video* jen v prazdne slozce
        videos = self.session / "no-cameras"
        videos.mkdir()
        self.open("luxos-profile-picture", "--camera", HOME=str(self.session / "home"), LUXOS_CAMERA_TEST="1",
                  LUXOS_VIDEO_DEV_DIR=str(videos), LUXOS_ACCOUNTS_FAKE=str(self.session / "accounts"))
        state = lambda: json.loads(self.app.ask("state", "state"))  # noqa: E731
        self.assertTrue(self.app.wait(lambda: state()["cam"] == "preview"))
        self.check_window("luxos-profile-picture", "Profile Picture")
        self.app.ask("photo")
        self.assertTrue(self.app.wait(lambda: state()["page"] == "crop"))
        time.sleep(0.4)                 # prolinani stranek
        self.shot("luxos-profile-picture-crop")
        self.app.ask("click Save")
        self.assertTrue(self.app.wait(lambda: (self.session / "home/.face").exists()))
        self.assertEqual((self.session / "accounts").read_text(), str(self.session / "home/.face"))

    def test_router(self):
        # falesna sit (tests/fake-net), router = mistni server HTTP; zadna skutecna sit
        import http.server
        import threading
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), type("H", (http.server.BaseHTTPRequestHandler,), {
            "do_GET": lambda h: (h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
                                 h.wfile.write(b"<html><head><title>Router</title></head><body><h1>Admin</h1></body></html>")),
            "log_message": lambda h, *a: None}))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        net = self.session / "net.json"
        net.write_text(json.dumps({
            "routes": [{"dst": "default", "gateway": "127.0.0.1", "dev": "wlp4s0", "metric": 600}],
            "device": "GENERAL.TYPE:wifi\nGENERAL.CONNECTION:Domov 5G\nIP4.ADDRESS[1]:127.0.0.5/24\n",
            "wifi": "yes:Domov 5G\n", "neigh": [], "ping": {"127.0.0.1": 1.2}}))
        fake = HERE / "fake-net"
        self.open("luxos-router", FAKE_NET=str(net), LUXOS_IP=str(fake / "ip"), LUXOS_NMCLI=str(fake / "nmcli"),
                  LUXOS_PING=str(fake / "ping"), LUXOS_CURL="false", LUXOS_GETENT="false",
                  LUXOS_ROUTER_PORT=str(srv.server_address[1]), LANG=os.environ.get("LANG_UI", "en_US.UTF-8"),
                  LC_ALL=os.environ.get("LANG_UI", "en_US.UTF-8"), GTK_THEME=os.environ.get("GTK_THEME_UI", "Adwaita"))
        self.check_window("luxos-router", "Správa sítě" if os.environ.get("LANG_UI", "").startswith("cs") else "Router")
        state = lambda: json.loads(self.app.ask("state", "state"))  # noqa: E731
        self.app.ask("tool 1")
        self.assertTrue(self.app.wait(lambda: state()["tools"][1] != ""))
        self.assertIn(state()["tools"][1], ("1.2 ms", "1,2 ms"))
        # webova sprava (WebKit) i pod Waylandem bez GPU
        self.app.ask("page router")
        self.assertTrue(self.app.wait(lambda: state()["title"] == "Router" and not state()["loading"], 30), state())
        time.sleep(1)
        self.shot("luxos-router-web")
        self.app.ask("page devices")
        self.assertTrue(self.app.wait(lambda: len(state()["devices"]) == 1))
        self.shot("luxos-router-devices")

    def test_wifi_qr(self):
        nm = self.session / "nm"
        nm.mkdir()
        (nm / "nmcli").write_text(
            "#!/bin/sh\ncase \"$*\" in\n"
            "*--active*) echo '802-11-wireless:uuid-1:wlan0:Home' ;;\n"
            "*uuid*) printf '802-11-wireless.ssid:Home\\n802-11-wireless.hidden:no\\n"
            "802-11-wireless-security.key-mgmt:wpa-psk\\n802-11-wireless-security.psk:not-a-real-secret\\n' ;;\n"
            "*) exit 2 ;;\nesac\n")
        (nm / "nmcli").chmod(0o755)
        self.open("luxos-wifi-qr", LUXOS_NMCLI=str(nm / "nmcli"), LUXOS_CAMERA_TEST="1",
                  LUXOS_VIDEO_DEV_DIR=str(nm))
        state = lambda: json.loads(self.app.ask("state", "state"))  # noqa: E731
        self.assertTrue(self.app.wait(lambda: state()["page"] == "qr"))
        self.check_window("luxos-wifi-qr", "Wi-Fi QR Code")
        self.assertEqual(lsl_app.find(self.app.dump(), name="ssid")["text"], "Home")
        # kopirovani obrazku do schranky Waylandu
        self.app.ask("click Copy QR code image")
        self.assertTrue(state()["clipboard"])

    def test_app_reset(self):
        home = self.session / "fixture"
        (home / ".config/someapp").mkdir(parents=True)
        (home / ".config/someapp/conf").write_text("c")
        self.open("luxos-app-reset", HOME=str(home), XDG_CONFIG_HOME="", XDG_DATA_HOME="", XDG_CACHE_HOME="",
                  LUXOS_DESKTOP_DIRS=str(self.session / "no-apps"))
        status = lambda: lsl_app.find(self.app.dump(), name="status")["text"]  # noqa: E731
        self.assertTrue(self.app.wait(lambda: status() == "1 apps with settings"))
        self.check_window("luxos-app-reset", "Reset App Settings")
        self.app.send("reset someapp")
        self.assertTrue(self.app.wait(lambda: any(w["dialog"] for w in self.app.dump())))
        self.shot("luxos-app-reset-dialog")
        self.app.ask("click Reset")
        self.assertTrue(self.app.wait(lambda: "Settings of someapp were reset" in lsl_app.texts(self.app.dump(), dialog=True)))
        self.app.ask("click OK")
        self.assertTrue(self.app.wait(lambda: status() == "0 apps with settings"))
        self.assertFalse((home / ".config/someapp").exists())

    def test_calculator(self):
        self.open("luxos-calculator", XDG_CONFIG_HOME=str(self.session / "config"))
        state = lambda: json.loads(self.app.ask("state", "state"))  # noqa: E731
        self.check_window("luxos-calculator", "Calculator")
        # klavesy jako udalosti Waylandu do okna, vedecky rezim zvetsi okno
        self.app.ask("type 1250*1.21")
        self.app.ask("press Return")
        self.assertEqual(state()["value"], "1,512.5")
        self.app.ask("press ctrl+2")
        self.assertTrue(state()["scientific"])
        self.app.ask("type 2^10+(3.5*4)=")
        self.assertEqual(state()["value"], "1,038")
        self.shot("luxos-calculator-scientific")
        self.app.ask("press ctrl+c")
        self.app.ask("press Escape Escape ctrl+v")
        self.assertTrue(self.app.wait(lambda: state()["entry"] == "1038"))
        self.app.send("press ctrl+q")
        self.assertEqual(self.app.proc.wait(10), 0)

    def test_monitor(self):
        # aplikace na Waylandu = proces s polozkou .desktop (cizi okna luxwm neprivilegovanemu klientovi neda);
        # ukoncuje se jen proces spusteny testem
        data = self.session / "data"
        (data / "applications").mkdir(parents=True)
        (data / "applications/luxos-test-app.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Test App\nExec=luxos-test-app\nIcon=utilities-terminal\n")
        bindir = self.session / "bin"
        bindir.mkdir()
        (bindir / "luxos-test-app").symlink_to(shutil.which("sleep"))
        helper = subprocess.Popen([str(bindir / "luxos-test-app"), "300"])
        self.procs.append(helper)
        path = f"{bindir}:{os.environ['PATH']}"
        self.open("luxos-monitor", PATH=path, XDG_DATA_HOME=str(data), LANG="en_US.UTF-8")
        self.check_window("luxos-monitor", "System Monitor")
        state = lambda: json.loads(self.app.ask("state", "state"))  # noqa: E731
        self.assertTrue(self.app.wait(lambda: any(r["name"] == "Test App" for r in state()["rows"])), state())
        self.assertTrue(state()["title"].startswith("Open apps ("))
        self.app.ask("sort name")
        self.assertEqual(state()["heads"]["name"], "Name ▲")
        self.app.ask("quit Test App")
        self.assertEqual(helper.wait(10), -15)
        self.assertTrue(self.app.wait(lambda: all(r["name"] != "Test App" for r in state()["rows"])))
        self.app.send("close")
        self.assertEqual(self.app.proc.wait(10), 0)

    def test_feedback(self):
        import http.server
        import threading
        got = []

        class Fake(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_POST(self):  # noqa: N802
                got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"id": "FB-WL-1"}')
        srv = http.server.HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        env = dict(LUXAI_ORIGIN="http://127.0.0.1:%d" % srv.server_address[1], HOME=str(self.session / "home"),
                   XDG_DATA_HOME=str(self.session / "data"), XDG_CONFIG_HOME=str(self.session / "config"))
        shots = os.environ.get("LUXOS_WL_SHOTS")
        # snimky svetly/tmavy a cesky/anglicky (jen s LUXOS_WL_SHOTS)
        for theme, lang in ((("WhiteSur-Light", "en_US.UTF-8"), ("WhiteSur-Dark", "en_US.UTF-8"),
                             ("WhiteSur-Light", "cs_CZ.UTF-8"), ("WhiteSur-Dark", "cs_CZ.UTF-8")) if shots else ()):
            self.open("luxos-feedback", GTK_THEME=theme, LANG=lang, **env)
            time.sleep(1.5)
            self.shot("luxos-feedback-%s-%s" % ("dark" if "Dark" in theme else "light", lang[:2]))
            self.app.stop()
            self.app = None
        self.open("luxos-feedback", **env)
        self.check_window("luxos-feedback", "Feedback")
        state = lambda: json.loads(self.app.ask("state", "state"))  # noqa: E731
        self.app.ask("sysinfo 0")
        self.app.ask("type Wayland report from the test.")
        self.assertTrue(state()["send"])
        self.app.ask("click Send")
        self.assertTrue(self.app.wait(lambda: state()["page"] == "done", 30), self.app.stderr())
        self.assertEqual(lsl_app.find(self.app.dump(), name="done-id")["text"], "Report ID: FB-WL-1")
        self.assertEqual(got[-1]["message"], "Wayland report from the test.")
        self.shot("luxos-feedback-done")

    def test_camera(self):
        # videotestsrc, uzly video* jen v prazdne slozce; fotka do docasneho domova
        videos = self.session / "no-cameras"
        videos.mkdir()
        home = self.session / "home"
        self.open("luxos-camera", HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), LUXOS_CAMERA_TEST="2",
                  LUXOS_VIDEO_DEV_DIR=str(videos))
        state = lambda: json.loads(self.app.ask("state", "state"))  # noqa: E731
        self.assertTrue(self.app.wait(lambda: state()["state"] == "preview"))
        self.assertTrue(state()["combo"])
        self.check_window("luxos-camera", "Camera")
        self.app.ask("click Take Photo")
        self.assertTrue(self.app.wait(lambda: state()["thumb"]))
        self.assertEqual(len(list((home / "Pictures/Camera").glob("Photo *.jpg"))), 1)
        time.sleep(0.5)                 # blesk
        self.shot("luxos-camera-photo")
        self.app.send("close")
        self.assertEqual(self.app.proc.wait(10), 0)


if __name__ == "__main__":
    unittest.main()
