#!/usr/bin/env python3
"""LuxOS - testy Klavesovych zkratek (luxos-keyboard-settings --shortcuts v LSL, na X11 okno drive
bin/luxos-shortcuts v Pythonu): nazvy zkratek, xfconf, kolize, vlastni zkratky a okno ve vlastnim Xvfb.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_shortcuts.py -v

Model (files/lsl/luxos_shortcuts_model.lsl) v tests/lsl/luxos-shortcuts-model-test.lsl; okno
files/lsl/luxos_keyboard_x11.lsl rizene pres luxos_testctl. Vsechna volani xfconf-query jdou na falesny prikaz
z fake-shortcuts (LUXOS_XFCONF_QUERY), skutecne nastaveni uzivatele se nemeni. LUXOS_TEST_SHOTS = snimky.
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

FAKE_XFCONF = os.path.join(HERE, "fake-shortcuts", "xfconf-query")
DEFAULTS_XML = os.path.normpath(os.path.join(
    HERE, "..", "files", "xdg", "xfce4", "xfconf", "xfce-perchannel-xml", "xfce4-keyboard-shortcuts.xml"))
TMP = tempfile.mkdtemp(prefix="luxos-shortcuts-test-")
_built = {}


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def binary():
    if "app" not in _built:
        _built["app"] = lsl_app.build("luxos-keyboard-settings", TMP)
    return _built["app"]


def fake_env(tmp):
    return {"LUXOS_XFCONF_QUERY": FAKE_XFCONF, "FAKE_XFCONF_DEFAULTS": DEFAULTS_XML,
            "FAKE_XFCONF": os.path.join(tmp, "xfconf.json"), "FAKE_XFCONF_LOG": os.path.join(tmp, "xfconf.log"),
            "LUXOS_SHORTCUTS_DEFAULTS": DEFAULTS_XML, "LUXOS_XKB_CONF": os.path.join(tmp, "00-keyboard.conf"),
            "XDG_CONFIG_HOME": os.path.join(tmp, "config"), "HOME": tmp, "LANG": "en_US.UTF-8",
            "LUXOS_I18N_DIR": lsl_app.I18N}


class Model(unittest.TestCase):
    def test_model(self):
        lslc = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
        if not lslc:
            self.skipTest("lslc is not installed")
        out = os.path.join(TMP, "sctest")
        r = subprocess.run([lslc, "--target", "linux-x86_64-gnu", "--system-bindings", lsl_app.LSL_DIR,
                            os.path.join(HERE, "lsl", "luxos-shortcuts-model-test.lsl"), out],
                           capture_output=True, text=True, timeout=900)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        work = tempfile.mkdtemp(dir=TMP)
        os.makedirs(os.path.join(work, "config"))
        env = dict(fake_env(work), PATH=os.environ["PATH"], SC_TEST_TMP=work, SC_FAKE=FAKE_XFCONF,
                   SC_DEFAULTS=DEFAULTS_XML)
        r = subprocess.run([out], capture_output=True, text=True, timeout=120, env=env)
        lines = r.stdout.splitlines()
        self.assertEqual([line for line in lines if not line.startswith("ok ")], [], r.stderr)
        self.assertEqual(r.returncode, 0)
        self.assertGreaterEqual(len(lines), 145)
        # cteni nikdy nesahne na skutecny xfconf: kazde volani je v zaznamu falesneho prikazu
        self.assertTrue(os.path.exists(env["FAKE_XFCONF_LOG"]))


@unittest.skipUnless(shutil.which("Xvfb"), "Xvfb is missing")
class App(unittest.TestCase):
    """Okno Klavesove zkratky na X11 (parita s testy okna v Pythonu)."""

    @classmethod
    def setUpClass(cls):
        cls.binary = binary()
        cls.x = lsl_app.Xvfb("1280x900")

    @classmethod
    def tearDownClass(cls):
        cls.x.stop()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir=TMP)
        self.env = fake_env(self.tmp)
        with open(self.env["LUXOS_XKB_CONF"], "w") as f:
            f.write('Option "XkbOptions" "grp:shifts_toggle"\n')
        self.app = None
        self.start()

    def tearDown(self):
        if self.app:
            self.app.stop()

    def start(self):
        if self.app:
            self.app.stop()
        env = dict(self.env, PATH=os.environ["PATH"], DISPLAY=self.x.display, XDG_RUNTIME_DIR=self.tmp,
                   GTK_THEME="Adwaita", DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent")
        luxos_testguard.check_env(env)
        self.app = lsl_app.App([self.binary, "--shortcuts"], env)
        self.assertTrue(self.app.wait(lambda: self.state() is not None, 20), self.app.stderr())

    def state(self):
        if self.app.proc.poll() is not None:
            raise AssertionError("app exited: " + self.app.stderr())
        try:
            return json.loads(self.app.ask("state", "state ", timeout=5))
        except AssertionError:
            return None

    def user_values(self):
        try:
            with open(self.env["FAKE_XFCONF"]) as f:
                return json.load(f)
        except OSError:
            return {}

    def calls(self):
        try:
            with open(self.env["FAKE_XFCONF_LOG"]) as f:
                return [json.loads(line) for line in f]
        except OSError:
            return []

    def writes(self):
        return [c for c in self.calls() if "-s" in c or "-r" in c]

    def names(self):
        try:
            with open(os.path.join(self.env["XDG_CONFIG_HOME"], "luxos", "shortcuts.json")) as f:
                return json.load(f)["custom"]
        except OSError:
            return {}

    def accels(self, aid):
        return json.loads(self.app.ask("accels " + aid, "accels "))

    def set(self, aid, value):
        """Vysledek zachyceni bez dialogu (apply_change); dotaz na kolizi se otevre jako skutecny dialog."""
        self.app.send("set %s %s" % (aid, value))

    def dialog(self):
        return [w for w in self.app.dump() if w["dialog"]]

    def wait_dialog(self, text):
        self.assertTrue(self.app.wait(lambda: any(text in t for t in lsl_app.texts(self.dialog(), dialog=True))),
                        lsl_app.texts(self.app.dump()))

    def shot(self, name):
        d = os.environ.get("LUXOS_TEST_SHOTS")
        if d:
            os.makedirs(d, exist_ok=True)
            lsl_app.shot(self.x.display, os.path.join(d, name + ".png"))

    def test_window(self):
        win = self.app.dump()
        self.assertEqual(win[0]["title"], "Keyboard Shortcuts")
        self.assertTrue(win[0]["close_button"])
        page = lsl_app.texts(win) + [w.get("text") for w in lsl_app.widgets(win) if w["t"] == "GtkButton"]
        for title in ("Windows", "Apps & System", "Screenshots", "Custom Shortcuts"):
            self.assertIn(title, page)
        self.assertNotIn("Other Xfce Shortcuts", page)   # zdrojove XML LuxOS nema prikazy mimo katalog
        self.assertIn("Super + Q, Alt + F4", page)
        self.assertIn("Super + Shift + 4, Shift + Print Screen", page)
        self.assertIn("Switch keyboard layout", page)
        self.assertIn("Left Shift + Right Shift", page)
        self.assertIn("Super key alone opens Launchpad", page)
        self.assertIn("Add Shortcut…", page)
        self.assertFalse(any("⌘" in (t or "") for t in page))
        tips = [w.get("tip") for w in lsl_app.widgets(win) if w["t"] == "GtkButton"]
        self.assertIn("Add Shortcut…", tips)             # + v HeaderBar
        self.assertEqual(self.writes(), [])
        self.shot("shortcuts-window")

    def test_super_tap_row(self):
        s = self.state()
        order = s["order"]
        self.assertEqual(order.index("super-tap"), order.index("launchpad") + 1)     # hned pod Launchpadem
        self.assertIn("switch:on", s["rows"]["super-tap"])
        flag = os.path.join(self.env["XDG_CONFIG_HOME"], "luxos", "super-launchpad-off")
        self.app.ask("super off")
        self.assertTrue(os.path.exists(flag))
        self.app.ask("super on")
        self.assertFalse(os.path.exists(flag))
        self.assertEqual(self.writes(), [])              # xfconf se nemeni
        self.app.ask("super off")
        self.start()                                     # stav po znovuotevreni
        self.assertIn("switch:off", self.state()["rows"]["super-tap"])

    def test_group_apps_row(self):
        s = self.state()
        order = s["order"]
        self.assertEqual(order.index("group-apps"), order.index("cycle-app-reverse") + 1)  # pod Alt+`
        self.assertIn("Alt + `", s["rows"]["cycle-app"])
        self.assertIn("Alt + Shift + `", s["rows"]["cycle-app-reverse"])
        self.assertIn("Super + `", s["rows"]["switch-app"])
        self.assertIn("switch:off", s["rows"]["group-apps"])                    # vychozi vypnuto
        self.app.ask("group on")
        self.assertIn(["-c", "xfwm4", "-p", "/general/cycle_group_apps", "-n", "-t", "bool", "-s", "true"], self.writes())
        self.assertEqual(self.user_values().get("/general/cycle_group_apps"), "true")
        self.start()
        self.assertIn("switch:on", self.state()["rows"]["group-apps"])
        self.app.ask("group off")
        self.assertEqual(self.user_values().get("/general/cycle_group_apps"), "false")

    def test_capture_dialog_keys(self):
        self.app.send("capture 1 Files")
        self.assertTrue(self.app.wait(lambda: self.state()["capture"] is not None))
        self.assertIn("Press the new shortcut for “Files”", lsl_app.texts(self.dialog(), dialog=True))
        # pismeno bez modifikatoru se neprijme
        self.app.ask("key - e")
        cap = self.state()["capture"]
        self.assertIsNone(cap["result"])
        self.assertIn("Use at least one", cap["hint"])
        self.assertEqual(cap["keys"], "E")
        self.shot("shortcuts-capture")
        # Super + Shift + 4 (keyval dollar se prevede na zakladni klavesu 4)
        self.app.send("key super+shift dollar")
        self.assertEqual(json.loads(self.app.line("captured ")), ["set", "<Shift><Super>4"])
        # Backspace vypne, Esc zrusi
        self.app.send("capture 1 Files")
        self.assertTrue(self.app.wait(lambda: self.state()["capture"] is not None))
        self.app.send("key - BackSpace")
        self.assertEqual(json.loads(self.app.line("captured ")), ["off", None])
        self.app.send("capture 1 Files")
        self.assertTrue(self.app.wait(lambda: self.state()["capture"] is not None))
        self.app.send("key - Escape")
        self.assertIsNone(json.loads(self.app.line("captured ")))
        # pri pridavani vlastni zkratky Backspace nic nevypina
        self.app.send("capture 0 New")
        self.assertTrue(self.app.wait(lambda: self.state()["capture"] is not None))
        self.assertIn("Esc cancels.", lsl_app.texts(self.dialog(), dialog=True))
        self.app.ask("key - BackSpace")
        self.assertIsNotNone(self.state()["capture"])
        self.assertIsNone(self.state()["capture"]["result"])
        self.app.send("key - Escape")
        self.assertIsNone(json.loads(self.app.line("captured ")))
        self.assertEqual(self.writes(), [])

    def test_capture_changes_shortcut(self):
        # cela cesta: klik na zkratku Kalkulacky, stisk Super + Alt + C v dialogu, zapis do xfconf
        self.app.send("change calculator")
        self.assertTrue(self.app.wait(lambda: self.state()["capture"] is not None))
        self.app.send("key super+alt c")
        self.assertTrue(self.app.wait(lambda: self.accels("calculator") == ["<Alt><Super>c"]))
        self.assertEqual(self.user_values()["/commands/custom/<Alt><Super>c"], "luxos-calculator")
        self.app.send("change calculator")
        self.assertTrue(self.app.wait(lambda: self.state()["capture"] is not None))
        self.app.send("key super+shift dollar")         # Super+Shift+4 patri Snimku oblasti: dotaz
        self.wait_dialog("is already used by")
        self.app.send("respond -6")
        self.assertTrue(self.app.wait(lambda: not self.dialog()))
        self.assertEqual(self.accels("calculator"), ["<Alt><Super>c"])

    def test_change_with_conflict(self):
        self.set("files", "<Super>t")
        self.wait_dialog("“Super + T” is already used by “Terminal”.")
        self.app.send("respond -6")                      # odmitnuti nic nezapise
        self.assertEqual(self.app.line("set "), "false")
        self.assertEqual(self.writes(), [])
        self.set("files", "<Super>t")
        self.wait_dialog("is already used by")
        self.shot("shortcuts-conflict")
        self.app.send("respond -5")
        self.assertEqual(self.app.line("set "), "true")
        self.assertEqual(self.accels("files"), ["<Super>t"])
        # zmeneny radek ma tlacitko Obnovit
        self.assertIn("tip:Restore Default", self.state()["rows"]["files"])

    def test_change_free_and_off(self):
        self.set("calculator", "<Super><Alt>c")
        self.assertEqual(self.app.line("set "), "true")
        self.assertFalse(self.dialog())                  # volna zkratka - bez dotazu
        self.assertEqual(self.accels("calculator"), ["<Alt><Super>c"])
        self.set("calculator", "off")
        self.assertEqual(self.app.line("set "), "true")
        self.assertEqual(self.accels("calculator"), [])
        self.assertIn("Off", self.state()["rows"]["calculator"])

    def test_custom_dialog(self):
        self.app.send("custom-dialog")
        self.assertTrue(self.app.wait(lambda: self.state()["custom"] is not None))
        self.assertFalse(self.state()["custom"]["save"])
        self.app.ask("custom-name Notes")
        self.app.ask("custom-command mousepad")
        self.assertFalse(self.state()["custom"]["save"])         # chybi zkratka
        self.app.ask("custom-accel <Super>e")
        c = self.state()["custom"]
        self.assertTrue(c["save"])
        self.assertIn("Files", c["note"])                         # upozorneni na kolizi
        self.app.ask("custom-accel <Super>n")
        c = self.state()["custom"]
        self.assertEqual(c["note"], "")
        self.assertEqual(c["values"], ["Notes", "mousepad", "<Super>n"])
        self.assertIn("Super + N", [w.get("text") for w in lsl_app.widgets(self.dialog()) if w["t"] == "GtkButton"])
        self.shot("shortcuts-add")
        self.app.send("respond -5")                               # Ulozit
        self.assertTrue(self.app.wait(lambda: self.state()["custom"] is None))
        s = self.state()
        self.assertIn("custom:<Super>n", s["rows"])
        self.assertIn("Notes", s["rows"]["custom:<Super>n"])
        self.assertIn("Super + N", s["rows"]["custom:<Super>n"])
        self.assertEqual(self.names(), {"<Super>n": {"command": "mousepad", "name": "Notes"}})
        # zmena zkratky vlastni polozky pres zachyceni
        self.set("custom:<Super>n", "<Super>j")
        self.assertEqual(self.app.line("set "), "true")
        self.assertEqual(list(self.names()), ["<Super>j"])
        self.assertEqual(self.names()["<Super>j"]["name"], "Notes")
        # smazani (s dotazem)
        self.app.send("delete-custom custom:<Super>j")
        self.wait_dialog("Delete the shortcut “Notes”?")
        self.app.send("respond -5")
        self.assertTrue(self.app.wait(lambda: self.state()["customs"] == []))
        self.assertEqual(self.user_values(), {})

    def test_app_chooser(self):
        apps = os.path.join(self.tmp, "data", "applications")
        os.makedirs(apps)
        with open(os.path.join(apps, "notes-test.desktop"), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=Notes Test\nExec=true --notes %U\nIcon=text-editor\n")
        with open(os.path.join(apps, "top-test.desktop"), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=Top Test\nExec=top\nTerminal=true\n")
        self.env["XDG_DATA_HOME"] = os.path.join(self.tmp, "data")
        self.start()
        self.app.send("chooser")
        self.assertTrue(self.app.wait(lambda: self.state()["chooser"] is not None))
        listed = self.state()["chooser"]
        self.assertIn(["Notes Test", "true --notes"], listed)                # bez %U
        self.assertIn(["Top Test", "luxos-terminal -x top"], listed)         # Terminal=true
        self.assertFalse([c for _n, c in listed if "%u" in c.lower() or "%f" in c.lower()])
        self.assertEqual([n.lower() for n, _c in listed], sorted(n.lower() for n, _c in listed))
        first = json.loads(self.app.ask("chooser-pick 0", "chooser-pick "))
        self.assertEqual(first, listed[0])
        self.app.send("respond -6")
        self.assertTrue(self.app.wait(lambda: self.state()["chooser"] is None))

    def test_restore_all(self):
        self.app.ask("assign files <Super>f <Super>e")
        self.app.send("restore-all")
        self.wait_dialog("Restore all shortcuts to their defaults?")
        self.app.send("respond -5")
        self.assertTrue(self.app.wait(lambda: self.accels("files") == ["<Super>e"]))
        self.assertNotIn("tip:Restore Default", self.state()["rows"]["files"])
        self.app.ask("assign files <Super>f <Super>e")
        self.app.send("restore-all")                     # zruseno v dotazu
        self.wait_dialog("Restore all shortcuts to their defaults?")
        self.app.send("respond -6")
        self.assertTrue(self.app.wait(lambda: not self.dialog()))
        self.assertEqual(self.accels("files"), ["<Super>f"])

    def test_write_failure_warns(self):
        self.env["LUXOS_XFCONF_QUERY"] = "/bin/false"
        self.start()
        self.assertFalse(self.state()["available"])
        self.assertIn("Shortcuts could not be read from the Xfce settings service. Changes will not be saved.",
                      lsl_app.texts(self.app.dump()))
        self.set("calculator", "<Super><Alt>c")
        self.wait_dialog("The shortcut could not be saved.")
        self.app.send("respond -5")
        self.assertEqual(self.app.line("set "), "false")

    def test_window_size_and_pss(self):
        time.sleep(1.5)
        if shutil.which("xdotool"):
            env = {"DISPLAY": self.x.display, "PATH": os.environ["PATH"]}
            ids = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "^Keyboard Shortcuts$"], env=env,
                                 capture_output=True, text=True).stdout.split()
            self.assertTrue(ids)
            out = subprocess.run(["xdotool", "getwindowgeometry", "--shell", ids[0]], env=env, capture_output=True,
                                 text=True).stdout
            vals = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
            self.assertLessEqual(int(vals["HEIGHT"]), 900 - 16)
            hints = subprocess.run(["xprop", "-id", ids[0], "WM_NORMAL_HINTS"], env=env, capture_output=True,
                                   text=True).stdout if shutil.which("xprop") else ""
            for line in hints.splitlines():
                if "minimum size" in line:
                    w, h = line.split(":")[1].strip().split(" by ")
                    self.assertGreaterEqual(int(h), 300)
                    self.assertGreaterEqual(int(w), 340)
        pss = self.app.pss_kb()
        print("\nluxos-shortcuts (LSL) PSS %d kB" % pss, file=sys.stderr)
        self.assertLess(pss, 53997)                      # Python + GTK pod Xvfb: 53997 kB


if __name__ == "__main__":
    unittest.main()
