#!/usr/bin/env python3
"""LuxOS - stranky Monitory a Klavesnice okna Nastaveni: odkazy starymi jmeny (luxos-display-settings,
luxos-keyboard-settings --shortcuts), rychla volba rezimu Super+P (luxos-displays-settings --menu, prikazovy
rezim pred oknem) a opakovani drzene klavesy - na Waylandu ho luxwm pouzije (overeno pres IPC get_state pod
luxwm headless), na X11 se zapise do xfconf (falesny xfconf-query).

    packages/luxwm/tests/build-host.sh
    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -p MemorySwapMax=0 -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_settings_displays_keyboard.py -v
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lsl_app_harness as h  # noqa: E402  (luxos_testguard)
import lsl_app  # noqa: E402

REPO = HERE.parent.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
OUT = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or OUT / "sysroot")
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")
FAKE_XFCONF = HERE / "fake-shortcuts" / "xfconf-query"
DEFAULTS_XML = HERE.parent / "files/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml"
# stav monitoru, jak ho vypise luxos-displays get na X11
DISPLAYS = {"x11": True, "primary": "HDMI-1", "mode": "extend", "text_size": 1, "outputs": [
    {"name": "HDMI-1", "description": "", "internal": False, "enabled": True, "choices": [["1920x1080", "1920 × 1080", True]],
     "current": "1920x1080", "rates": [["60.00", "60 Hz"]], "rate": "60.00", "rotations": [["normal", "Standard"]],
     "rotation": "normal", "width": 1920, "height": 1080, "x": 0, "y": 0, "transform": 0, "scale": 1000, "refresh": 60000}]}
RATES = [0, 3, 6, 10, 15, 20, 25, 30, 40, 50]
DELAYS = [2000, 1500, 1200, 900, 600, 500, 400, 300, 250, 200]


def setUpModule():
    if not h.lslc_ok():
        raise unittest.SkipTest("lslc 0.11 is not installed")


def binaries(tmp):
    """luxos-settings a odkazy starymi jmeny (jako v PKGBUILD)"""
    settings = lsl_app.build("luxos-settings", str(tmp))
    for alias in ("luxos-display-settings", "luxos-displays-settings", "luxos-keyboard-settings"):
        if not os.path.lexists(tmp / alias):
            os.symlink(settings, tmp / alias)
    return tmp


def wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


@unittest.skipUnless(shutil.which("Xvfb"), "Xvfb is missing")
class X11(unittest.TestCase):
    """Relace X11 (vlastni Xvfb): odkazy, jedna instance s novymi argumenty, opakovani klavesy v xfconf."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="dsp-kbd-", dir=h.private_dir()))
        cls.bin = binaries(cls.tmp)
        cls.x = lsl_app.Xvfb()

    @classmethod
    def tearDownClass(cls):
        cls.x.stop()
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.tmp))
        helper = self.work / "displays-helper"
        (self.work / "displays.json").write_text(json.dumps(DISPLAYS))
        helper.write_text("#!/bin/sh\ncat \"%s\"\n" % (self.work / "displays.json"))
        helper.chmod(0o755)
        # falesne nastroje relace X11: xfconf-query nad JSON, setxkbmap a localectl nic nedelaji
        fakes = self.work / "bin"
        fakes.mkdir()
        os.symlink(FAKE_XFCONF, fakes / "xfconf-query")
        for tool in ("setxkbmap", "localectl"):
            os.symlink(shutil.which("true"), fakes / tool)
        self.env = {"PATH": str(fakes) + ":" + os.environ["PATH"], "DISPLAY": self.x.display, "HOME": str(self.work),
                    "XDG_CONFIG_HOME": str(self.work / "config"), "XDG_CACHE_HOME": str(self.work / "cache"),
                    "XDG_RUNTIME_DIR": str(self.work), "LANG": "en_US.UTF-8", "GTK_THEME": "Adwaita",
                    "GIO_USE_VFS": "local", "GTK_A11Y": "none",
                    "GDK_BACKEND": "x11", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent",
                    "LUXOS_DISPLAYS_HELPER": str(helper), "LUXOS_XFCONF_QUERY": str(FAKE_XFCONF),
                    "FAKE_XFCONF": str(self.work / "xfconf.json"), "FAKE_XFCONF_LOG": str(self.work / "xfconf.log"),
                    "FAKE_XFCONF_DEFAULTS": str(DEFAULTS_XML), "LUXOS_SHORTCUTS_DEFAULTS": str(DEFAULTS_XML),
                    "LUXOS_XKB_CONF": str(self.work / "00-keyboard.conf")}
        (self.work / "00-keyboard.conf").write_text('Option "XkbOptions" "grp:shifts_toggle"\n')
        self.apps = []

    def tearDown(self):
        for app in self.apps:
            app.stop()

    def start(self, argv, **extra):
        app = lsl_app.App(argv, dict(self.env, **extra))
        self.apps.append(app)
        self.assertTrue(app.wait(lambda: app.proc.poll() is None and self.state(app)["page"] != "", 20), app.stderr())
        return app

    def state(self, app):
        try:
            return json.loads(app.ask("state", "state ", timeout=5))
        except AssertionError:
            return {"page": ""}

    def repeat(self, app):
        return json.loads(app.ask("repeat-state", "repeat "))

    def xfconf(self):
        p = self.work / "xfconf.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def test_display_settings_link_opens_displays(self):
        app = self.start([str(self.bin / "luxos-display-settings")])
        self.assertEqual(self.state(app)["page"], "displays")
        self.assertTrue(app.wait(lambda: json.loads(app.ask("page-state", "state "))["loaded"]))
        win = app.dump()
        self.assertEqual(win[0]["title"], "Displays")
        texts = lsl_app.texts(win)
        self.assertIn("Arrangement", texts)
        self.assertIn("Text Size", texts)
        # /usr/lib/luxos/luxos-displays-settings je tataz stranka
        app.stop()
        app = self.start([str(self.bin / "luxos-displays-settings")])
        self.assertEqual(self.state(app)["page"], "displays")

    def test_menu_needs_wayland(self):
        # rychla volba je prikazovy rezim pred oknem: na X11 skonci chybou a okno Nastaveni neotevre
        r = subprocess.run([str(self.bin / "luxos-displays-settings"), "--menu"], env=self.env, capture_output=True,
                           text=True, timeout=30)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("needs a Wayland compositor", r.stdout)

    def test_keyboard_shortcuts_link_and_second_launch(self):
        bus = lsl_app.Bus()
        try:
            env = {"DBUS_SESSION_BUS_ADDRESS": bus.address}
            app = self.start([str(self.bin / "luxos-keyboard-settings"), "--shortcuts"], **env)
            self.assertEqual(self.state(app)["page"], "keyboard")
            self.assertEqual(self.repeat(app)["tab"], "shortcuts")
            self.assertEqual(app.dump()[0]["title"], "Keyboard")
            self.assertIn("Switch keyboard layout", lsl_app.texts(app.dump()))
            app.ask("switcher layouts")                  # prepinac karet: karta se postavi az ted
            self.assertEqual(self.repeat(app)["tab"], "layouts")
            self.assertTrue(app.wait(lambda: "Add Layout…" in lsl_app.texts(app.dump())))
            # druhe spusteni (luxos-shortcuts) jen prepne kartu v bezicim okne a skonci
            r = subprocess.run([str(self.bin / "luxos-keyboard-settings"), "--shortcuts"],
                               env=dict(self.env, **env), capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(app.wait(lambda: self.repeat(app)["tab"] == "shortcuts"))
            # odkaz luxos-settings STRANKA v bezicim okne
            r = subprocess.run([str(self.bin / "luxos-settings"), "displays"], env=dict(self.env, **env),
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(app.wait(lambda: self.state(app)["page"] == "displays"))
        finally:
            for app in self.apps:
                app.stop()
            self.apps = []
            bus.stop()

    def test_key_repeat_written_to_xfconf(self):
        (self.work / "xfconf.json").write_text(json.dumps({"/Default/KeyRepeat/Rate": "30", "/Default/KeyRepeat/Delay": "900"}))
        app = self.start([str(self.bin / "luxos-keyboard-settings")])
        self.assertEqual(self.repeat(app), {"rate": 30, "delay": 900, "tab": "layouts"})
        texts = lsl_app.texts(app.dump())
        for t in ("Key Repeat", "Key repeat rate", "Delay until repeat", "Fast", "Long", "Short"):
            self.assertIn(t, texts)
        app.ask("slider Key repeat rate = 8")
        self.assertTrue(app.wait(lambda: self.xfconf().get("/Default/KeyRepeat/Rate") == str(RATES[8])), self.xfconf())
        self.assertEqual(self.xfconf()["/Default/KeyRepeat"], "true")
        self.assertEqual(self.xfconf()["/Default/KeyRepeat/Delay"], "900")
        app.ask("slider Delay until repeat = 9")
        self.assertTrue(app.wait(lambda: self.xfconf().get("/Default/KeyRepeat/Delay") == str(DELAYS[9])))
        # nejlevejsi poloha = opakovani vypnute (rychlost zustava)
        app.ask("slider Key repeat rate = 0")
        self.assertTrue(app.wait(lambda: self.xfconf().get("/Default/KeyRepeat") == "false"))
        self.assertEqual(self.xfconf()["/Default/KeyRepeat/Rate"], str(RATES[8]))
        calls = [json.loads(line) for line in (self.work / "xfconf.log").read_text().splitlines()]
        self.assertIn(["-c", "keyboards", "-p", "/Default/KeyRepeat", "-n", "-t", "bool", "-s", "false"], calls)
        # po novem otevreni: vypnuto
        app.stop()
        app = self.start([str(self.bin / "luxos-keyboard-settings")])
        self.assertEqual(self.repeat(app)["rate"], 0, (self.xfconf(), (self.work / "xfconf.log").read_text()[-600:]))

    def test_czech_strings(self):
        app = self.start([str(self.bin / "luxos-keyboard-settings")], LANG="cs_CZ.UTF-8", LUXOS_I18N_DIR=lsl_app.I18N)
        texts = lsl_app.texts(app.dump())
        for t in ("Opakování kláves", "Rychlost opakování", "Prodleva před opakováním"):
            self.assertIn(t, texts)


@unittest.skipUnless((LUXWM_BUILD / "luxwm").exists() and (SYSROOT / "usr/lib").exists() and WLT.exists(),
                     "luxwm (packages/luxwm/tests/build-host.sh) or wl-test harness missing")
class Wayland(unittest.TestCase):
    """luxwm headless: opakovani klavesy z luxwm.conf pri startu i po reload, rychla volba Super+P."""

    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(prefix="dsp-kbd-wl-", dir=OUT))
        cls.bin = binaries(cls.tmp)
        cls.conf = cls.tmp / "luxwm.conf"
        cls.conf.write_text("xwayland = no\n" + "".join(line for line in (REPO / "packages/luxwm/luxwm.conf").read_text()
                                                        .splitlines(True) if not line.startswith("xwayland")))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.apps = []
        self.session = None

    def tearDown(self):
        for app in self.apps:
            app.stop()
        if self.session:
            subprocess.run([str(WLT), "stop", str(self.session)], capture_output=True)
            shutil.rmtree(self.session, True)

    def start_luxwm(self, user_conf=None):
        name = f"dk{os.getpid() % 10000}-{self._testMethodName[5:15]}"
        # uzivatelska konfigurace uz pred startem luxwm (luxwm i stranka ctou tentyz soubor)
        config = Path(tempfile.mkdtemp(prefix="config-", dir=self.tmp))
        self.user_conf = config / "luxwm" / "luxwm.conf"
        if user_conf is not None:
            self.user_conf.parent.mkdir(parents=True)
            self.user_conf.write_text(user_conf)
        env = dict(os.environ, WLT_OUT=str(OUT), WLT_PRIVILEGED=str(LUXWM_BUILD / "luxwm-msg"),
                   WLT_COMPOSITOR_ENV=f"LUXWM_SYSTEM_CONFIG={self.conf} XDG_CONFIG_HOME={config} "
                                      f"LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib")
        r = subprocess.run([str(WLT), "start", "--mode", "headless", "--size", "1280x800", "--timeout", "300",
                            "--name", name, "--", str(LUXWM_BUILD / "luxwm")], env=env, capture_output=True, text=True,
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.session = Path(r.stdout.strip().splitlines()[-1])
        self.env = {}
        for line in subprocess.run([str(WLT), "env", str(self.session)], capture_output=True, text=True,
                                   env=env).stdout.splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            self.env[key] = value
        self.env.pop("LD_LIBRARY_PATH", None)
        self.env.update(GDK_BACKEND="wayland", GTK_A11Y="none", GTK_THEME="Adwaita", LANG="en_US.UTF-8",
                        LUXWM_SYSTEM_CONFIG=str(self.conf), DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent",
                        DBUS_SYSTEM_BUS_ADDRESS="unix:path=/nonexistent",
                        LUXOS_KEYBOARD_CONF=str(self.tmp / "no-00-keyboard.conf"), XDG_CONFIG_HOME=str(config))

    def msg(self, *args):
        r = subprocess.run([str(LUXWM_BUILD / "luxwm-msg"), *args], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stdout

    def repeat(self):
        return self.msg("get-state")["state"]["keyboard"]["repeat"]

    def test_luxwm_applies_repeat_from_config(self):
        self.start_luxwm()
        self.assertEqual(self.repeat(), {"rate": 25, "delay": 600})       # vychozi libluxcomp
        self.user_conf.parent.mkdir(parents=True)
        self.user_conf.write_text("repeat_rate = 33\nrepeat_delay = 250\n")
        self.msg("reload")
        self.assertEqual(self.repeat(), {"rate": 33, "delay": 250})
        # mimo rozsah se omezi, nesmysl = mez
        self.user_conf.write_text("repeat_rate = 500\nrepeat_delay = 5\n")
        self.msg("reload")
        self.assertEqual(self.repeat(), {"rate": 100, "delay": 100})
        self.user_conf.write_text("repeat_rate = 0\n")
        self.msg("reload")
        self.assertEqual(self.repeat(), {"rate": 0, "delay": 600})

    def test_key_repeat_through_the_page(self):
        self.start_luxwm("repeat_rate = 10\n")
        self.assertEqual(self.repeat(), {"rate": 10, "delay": 600})       # z luxwm.conf uz pri startu
        app = lsl_app.App([str(self.bin / "luxos-keyboard-settings")], self.env)
        self.apps.append(app)
        self.assertTrue(app.wait(lambda: app.proc.poll() is None and "Key repeat rate" in lsl_app.texts(app.dump()), 20),
                        app.stderr())
        self.assertEqual(json.loads(app.ask("repeat-state", "repeat ")), {"rate": 10, "delay": 600, "tab": "layouts"})
        app.ask("slider Key repeat rate = 8")
        self.assertTrue(wait_for(lambda: self.repeat()["rate"] == RATES[8]), self.repeat())
        app.ask("slider Delay until repeat = 7")
        self.assertTrue(wait_for(lambda: self.repeat() == {"rate": RATES[8], "delay": DELAYS[7]}), self.repeat())
        text = self.user_conf.read_text()
        self.assertIn("repeat_rate = 40", text)
        self.assertIn("repeat_delay = 300", text)
        app.ask("slider Key repeat rate = 0")
        self.assertTrue(wait_for(lambda: self.repeat()["rate"] == 0), self.repeat())
        # karta Zkratky ve stejne strance
        app.ask("tab shortcuts")
        self.assertIn("Close window", lsl_app.texts(app.dump()))

    def test_menu_cli_mode(self):
        self.start_luxwm()
        menu = self.bin / "luxos-displays-settings"
        helper = self.tmp / "displays-helper"
        helper.write_text("#!/bin/sh\necho '{\"mode\": \"extend\"}'\n")
        helper.chmod(0o755)
        env = dict(self.env, LUXOS_DISPLAYS_HELPER=str(helper))
        p = subprocess.Popen([str(menu), "--menu"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(2.5)
            self.assertIsNone(p.poll(), p.stderr.read() if p.poll() is not None else "")
            # vrstva shellu, zadne okno Nastaveni
            self.assertEqual(self.msg("list-windows")["windows"], [])
            # druhe Super+P: bezici volba prejde na dalsi rezim (SIGUSR1) a nove spusteni hned skonci
            r = subprocess.run([str(menu), "--menu"], env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIsNone(p.poll())
        finally:
            p.send_signal(signal.SIGTERM)
            p.wait(10)
            p.stdout.close()
            p.stderr.close()


if __name__ == "__main__":
    unittest.main()
