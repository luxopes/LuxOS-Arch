#!/usr/bin/env python3
"""LuxOS - testy Rozlozeni klavesnice (luxos-keyboard-settings v LSL, na X11 okno drive bin/luxos-keyboard
v Pythonu): cteni a zapis systemoveho nastaveni, prikazy localectl a setxkbmap, katalog rozlozeni, prevod
stareho vychoziho prepinani (luxos-desktop.install) a okno ve vlastnim Xvfb.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_keyboard.py -v

Model (files/lsl/luxos_keyboard_model.lsl) v tests/lsl/luxos-keyboard-model-test.lsl bez displeje; okno
files/lsl/luxos_keyboard_x11.lsl rizene pres luxos_testctl s falesnymi localectl, setxkbmap a xfconf-query -
skutecne nastaveni systemu ani uzivatele nemeni. LUXOS_TEST_SHOTS = slozka pro snimky.
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
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

TMP = tempfile.mkdtemp(prefix="luxos-keyboard-test-")
RULES = "/usr/share/X11/xkb/rules/evdev.lst"
_built = {}


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def binary():
    if "app" not in _built:
        _built["app"] = lsl_app.build("luxos-keyboard-settings", TMP)
    return _built["app"]


def conf_text(layouts, options=(), model=""):
    """00-keyboard.conf jako ho pise systemd-localed (stejne jako luxos_keyboard_model.conf_text)."""
    lines = ["# Written by systemd-localed(8), read by systemd-localed and Xorg. It's",
             "# probably wise not to edit this file manually. Use localectl(1) to", "# update this file.",
             'Section "InputClass"', '        Identifier "system-keyboard"', '        MatchIsKeyboard "on"',
             '        Option "XkbLayout" "%s"' % ",".join(lay for lay, _v in layouts)]
    if model:
        lines.append('        Option "XkbModel" "%s"' % model)
    var = ",".join(v for _l, v in layouts)
    if var.replace(",", ""):
        lines.append('        Option "XkbVariant" "%s"' % var)
    if options:
        lines.append('        Option "XkbOptions" "%s"' % ",".join(options))
    return "\n".join(lines + ["EndSection"]) + "\n"


class Model(unittest.TestCase):
    def test_model(self):
        lslc = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
        if not lslc:
            self.skipTest("lslc is not installed")
        out = os.path.join(TMP, "kbtest")
        r = subprocess.run([lslc, "--target", "linux-x86_64-gnu", "--system-bindings", lsl_app.LSL_DIR,
                            os.path.join(HERE, "lsl", "luxos-keyboard-model-test.lsl"), out],
                           capture_output=True, text=True, timeout=900)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        work = tempfile.mkdtemp(dir=TMP)
        env = {"PATH": os.environ["PATH"], "LANG": "C", "KBD_TEST_TMP": work}
        if os.path.exists(RULES):
            env["KBD_TEST_RULES"] = RULES
        r = subprocess.run([out], capture_output=True, text=True, timeout=60, env=env)
        lines = r.stdout.splitlines()
        self.assertEqual([line for line in lines if not line.startswith("ok ")], [], r.stderr)
        self.assertEqual(r.returncode, 0)
        self.assertGreaterEqual(len(lines), 77 + (3 if os.path.exists(RULES) else 0))


class Migrate(unittest.TestCase):
    """luxos-keyboard-settings --migrate-switch a jeho volani z luxos-desktop.install (post_upgrade)."""

    def files(self, conf, vconsole=None):
        d = tempfile.mkdtemp(dir=TMP)
        paths = {"LUXOS_KEYBOARD_CONF": os.path.join(d, "00-keyboard.conf"),
                 "LUXOS_VCONSOLE_CONF": os.path.join(d, "vconsole.conf"),
                 "LUXOS_KEYBOARD_MIGRATED": os.path.join(d, "var", "lib", "luxos", "keyboard-switch-migrated")}
        if conf is not None:
            with open(paths["LUXOS_KEYBOARD_CONF"], "w") as f:
                f.write(conf)
            os.chmod(paths["LUXOS_KEYBOARD_CONF"], 0o644)
        if vconsole is not None:
            with open(paths["LUXOS_VCONSOLE_CONF"], "w") as f:
                f.write(vconsole)
        return paths

    def hook(self, paths):
        """Funkce _luxos_keyboard z luxos-desktop.install s binarkou z testu."""
        with open(os.path.join(PKG, "luxos-desktop.install")) as f:
            src = f.read()
        start = src.index("_luxos_keyboard() {")
        block = src[start:src.index("\n}\n", start) + 3]
        self.assertNotIn("python", block)
        env = dict(paths, PATH="/usr/bin:/bin", LUXOS_KEYBOARD_SETTINGS=binary())
        return subprocess.run(["bash", "-c", block + "_luxos_keyboard"], env=env, capture_output=True, text=True,
                              timeout=30)

    def test_install_hook(self):
        old = conf_text([("cz", "qwerty"), ("us", "")], ["grp:alt_shift_toggle", "compose:ralt"], "pc105")
        vc = "KEYMAP=cz-qwerty\nXKBLAYOUT=cz,us\nXKBOPTIONS=grp:alt_shift_toggle,compose:ralt\n"
        paths = self.files(old, vc)
        r = self.hook(paths)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "==> Keyboard layouts now switch with both Shift keys (from the next login).\n")
        with open(paths["LUXOS_KEYBOARD_CONF"]) as f:
            self.assertEqual(f.read(), old.replace("grp:alt_shift_toggle", "grp:shifts_toggle"))
        with open(paths["LUXOS_VCONSOLE_CONF"]) as f:
            self.assertEqual(f.read(), vc.replace("grp:alt_shift_toggle", "grp:shifts_toggle"))
        self.assertEqual(stat.S_IMODE(os.stat(paths["LUXOS_KEYBOARD_CONF"]).st_mode), 0o644)
        with open(paths["LUXOS_KEYBOARD_MIGRATED"]) as f:
            self.assertEqual(f.read(), "grp:shifts_toggle\n")
        # podruhe nic (znacka), ani vedome znovu zvolene Alt+Shift
        with open(paths["LUXOS_KEYBOARD_CONF"], "w") as f:
            f.write(old)
        r = self.hook(paths)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        with open(paths["LUXOS_KEYBOARD_CONF"]) as f:
            self.assertEqual(f.read(), old)

    def test_install_hook_custom_and_missing(self):
        own = conf_text([("cz", ""), ("us", "")], ["grp:caps_toggle"])
        paths = self.files(own)
        r = self.hook(paths)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        with open(paths["LUXOS_KEYBOARD_MIGRATED"]) as f:
            self.assertEqual(f.read(), "unchanged\n")
        paths = self.files(None)
        r = self.hook(paths)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertFalse(os.path.exists(paths["LUXOS_KEYBOARD_MIGRATED"]))
        # bez binarky (rozbita instalace) hook neselze
        with open(os.path.join(PKG, "luxos-desktop.install")) as f:
            src = f.read()
        start = src.index("_luxos_keyboard() {")
        block = src[start:src.index("\n}\n", start) + 3]
        r = subprocess.run(["bash", "-c", block + "_luxos_keyboard; echo rc=$?"], capture_output=True, text=True,
                           env=dict(paths, PATH="/usr/bin:/bin", LUXOS_KEYBOARD_SETTINGS="/nonexistent"))
        self.assertEqual(r.stdout, "rc=0\n")


FAKE_TOOL = """#!/bin/sh
printf '%s\\n' "$(basename "$0") $*" >> "$KBD_TEST_LOG"
case "$(basename "$0") $1" in
    "setxkbmap -query") printf 'rules:      evdev\\nmodel:      pc105\\nlayout:     de\\noptions:    compose:ralt\\n' ;;
    "xfconf-query -c") case "$*" in *" -s "*) ;; *) echo "${KBD_TEST_XKBDISABLE:-true}" ;; esac ;;
    "localectl set-x11-keymap") [ -n "$KBD_TEST_DENY" ] && { echo "Access denied" >&2; exit 1; } ;;
esac
exit 0
"""


@unittest.skipUnless(shutil.which("Xvfb"), "Xvfb is missing")
class App(unittest.TestCase):
    """Okno Rozlozeni klavesnice na X11 (parita s testy okna v Pythonu)."""

    @classmethod
    def setUpClass(cls):
        cls.binary = binary()
        cls.x = lsl_app.Xvfb()
        cls.fake = os.path.join(TMP, "fakebin")
        os.makedirs(cls.fake, exist_ok=True)
        for tool in ("setxkbmap", "localectl", "xfconf-query"):
            p = os.path.join(cls.fake, tool)
            with open(p, "w") as f:
                f.write(FAKE_TOOL)
            os.chmod(p, stat.S_IRWXU)

    @classmethod
    def tearDownClass(cls):
        cls.x.stop()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir=TMP)
        self.log = os.path.join(self.tmp, "log")
        open(self.log, "w").close()
        self.conf = os.path.join(self.tmp, "00-keyboard.conf")
        with open(self.conf, "w") as f:
            f.write(conf_text([("cz", ""), ("us", "")], ["grp:alt_shift_toggle"]))
        self.app = None

    def tearDown(self):
        if self.app:
            self.app.stop()

    def start(self, **extra):
        env = {"PATH": self.fake + ":" + os.environ["PATH"], "DISPLAY": self.x.display, "HOME": self.tmp,
               "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"), "XDG_RUNTIME_DIR": self.tmp, "LANG": "en_US.UTF-8",
               "GTK_THEME": "Adwaita", "KBD_TEST_LOG": self.log, "LUXOS_KEYBOARD_CONF": self.conf,
               "LUXOS_VCONSOLE_CONF": os.path.join(self.tmp, "vconsole.conf"),
               "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent"}
        env.update(extra)
        luxos_testguard.check_env(env)
        self.app = lsl_app.App([self.binary], env)
        self.assertTrue(self.app.wait(lambda: self.state() is not None, 20), self.app.stderr())
        return self.app

    def state(self):
        try:
            return json.loads(self.app.ask("state", "state ", timeout=5))
        except AssertionError:
            return None

    def calls(self, prefix):
        with open(self.log) as f:
            return [ln.rstrip("\n") for ln in f if ln.startswith(prefix)]

    def clear_log(self):
        open(self.log, "w").close()

    def shot(self, name):
        d = os.environ.get("LUXOS_TEST_SHOTS")
        if d:
            os.makedirs(d, exist_ok=True)
            lsl_app.shot(self.x.display, os.path.join(d, name + ".png"))

    def test_edit_and_apply(self):
        self.start()
        s = self.state()
        self.assertEqual(s["layouts"], [["cz", ""], ["us", ""]])
        self.assertEqual(s["switch"], "grp:alt_shift_toggle")
        self.assertFalse(s["apply"])                     # nic se nezmenilo
        self.assertFalse(s["note"])
        win = self.app.dump()
        self.assertEqual(win[0]["title"], "Keyboard Layouts")
        self.assertTrue(win[0]["close_button"])
        texts = lsl_app.texts(win)
        for t in ("Layouts", "Czech", "English (US)", "CZ", "US", "Default", "Switching", "Switch layouts with"):
            self.assertIn(t, texts)
        self.shot("keyboard-layouts")
        # pridat (dialog s hledanim): jen hledane, uz pouzite chybi
        self.app.send("click Add Layout…")
        self.assertTrue(self.app.wait(lambda: self.state()["dialog"]))
        self.app.ask("search german")
        visible = self.state()["visible"]
        self.assertTrue(visible)
        self.assertIn("de:", visible)
        self.assertNotIn("cz:", visible)
        self.assertTrue(all("german" in h for h in self.state()["hay"]), [h for h in self.state()["hay"] if "german" not in h])
        dlg = [w for w in self.app.dump() if w["dialog"]][0]
        add = lsl_app.find([dlg], text="Add", kind="GtkButton")
        self.assertFalse(add["sens"])                    # nic vybrano
        self.app.ask("pick de:")
        self.assertEqual(json.loads(self.app.ask("chosen", "chosen ")), ["de", ""])
        dlg = [w for w in self.app.dump() if w["dialog"]][0]
        self.assertTrue(lsl_app.find([dlg], text="Add", kind="GtkButton")["sens"])
        self.shot("keyboard-add")
        self.app.send("respond -5")
        self.assertTrue(self.app.wait(lambda: not self.state()["dialog"]))
        self.assertEqual(self.state()["layouts"], [["cz", ""], ["us", ""], ["de", ""]])
        self.app.ask("layout up 2")
        self.assertEqual(self.state()["layouts"], [["cz", ""], ["de", ""], ["us", ""]])
        self.app.ask("layout up 0")                      # mimo rozsah - nic
        self.app.ask("layout remove 2")
        self.assertEqual(self.state()["layouts"], [["cz", ""], ["de", ""]])
        self.app.ask("switch-id grp:caps_toggle")
        self.assertTrue(self.state()["apply"])
        # nahled v relaci
        self.assertTrue(self.app.wait(lambda: "setxkbmap -layout cz,de -variant , -option  -option grp:caps_toggle"
                                      in self.calls("setxkbmap")))
        # pouziti pro cely system
        self.clear_log()
        self.app.send("click Apply to All Users and the Login Screen")
        self.assertTrue(self.app.wait(lambda: not self.state()["busy"] and self.state()["applied"]))
        self.assertEqual(self.calls("localectl"), ["localectl set-x11-keymap cz,de  , grp:caps_toggle"])
        self.assertIn("xfconf-query -c keyboard-layout -p /Default/XkbDisable -n -t bool -s true", self.calls("xfconf-query"))
        self.assertTrue(self.calls("setxkbmap -layout cz,de"))
        s = self.state()
        self.assertFalse(s["apply"])
        self.assertFalse(s["dirty"])
        self.assertEqual(s["status"], "Saved for all users and the login screen.")
        # zavreni bez dalsich zmen: zadny navrat
        self.clear_log()
        self.app.send("close")
        self.app.proc.wait(10)
        self.assertEqual(self.calls("setxkbmap"), [])

    def test_remove_last_and_limit(self):
        self.start()
        self.app.ask("layout remove 1")
        self.app.ask("layout remove 0")                  # posledni zustane
        self.assertEqual(self.state()["layouts"], [["cz", ""]])
        remove = lsl_app.find(self.app.dump(), text="Remove", kind="GtkButton")
        self.assertFalse(remove["sens"])
        for key in ("us:", "de:", "fr:"):
            self.app.ask("add-layout " + key)
        self.app.ask("add-layout pl:")                   # 5. uz ne
        self.assertEqual(len(self.state()["layouts"]), 4)
        add = lsl_app.find(self.app.dump(), text="Add Layout…", kind="GtkButton")
        self.assertFalse(add["sens"])                    # 4 = maximum
        self.assertEqual(add["tip"], "At most 4 layouts are possible.")

    def test_switch_offered_when_second_layout_added(self):
        with open(self.conf, "w") as f:
            f.write(conf_text([("de", "")]))
        self.start()
        self.assertEqual(self.state()["switch"], "none")
        self.app.ask("add-layout us:")
        s = self.state()
        self.assertEqual(s["layouts"], [["de", ""], ["us", ""]])
        self.assertEqual(s["options"], ["grp:shifts_toggle"])     # vychozi: obe klavesy Shift
        self.assertEqual(s["switch"], "grp:shifts_toggle")

    def test_denied_and_revert_on_close(self):
        self.start(KBD_TEST_DENY="1")
        self.app.ask("layout down 0")
        self.app.send("click Apply to All Users and the Login Screen")
        self.assertTrue(self.app.wait(lambda: "cancelled" in self.state()["status"]))
        s = self.state()
        self.assertFalse(s["busy"])
        self.assertTrue(s["dirty"])
        self.assertEqual(s["status"], "Not saved: administrator authentication was cancelled.")
        self.assertEqual(self.calls("xfconf-query -c keyboard-layout -p /Default/XkbDisable -n"), [])
        self.clear_log()
        self.app.send("close")
        self.app.proc.wait(10)
        # navrat do stavu relace pred otevrenim (falesny setxkbmap -query: de + compose:ralt)
        self.assertEqual(self.calls("setxkbmap"), ["setxkbmap -layout de -variant  -option  -option compose:ralt"])

    def test_user_override_note(self):
        self.start(KBD_TEST_XKBDISABLE="false")
        s = self.state()
        self.assertTrue(s["note"])
        self.assertTrue(s["apply"])                      # i beze zmeny: vratit uzivatele k systemu
        self.assertIn("Your account uses its own keyboard layouts from Xfce settings. Applying switches it back to "
                      "the layouts set here.", lsl_app.texts(self.app.dump()))

    def test_unknown_switch_kept_and_czech(self):
        with open(self.conf, "w") as f:
            f.write(conf_text([("cz", ""), ("us", "")], ["grp:lwin_toggle"]))
        self.start(LANG="cs_CZ.UTF-8", LUXOS_I18N_DIR=lsl_app.I18N)
        self.assertEqual(self.state()["switch"], "grp:lwin_toggle")   # jina volba z localectl se neztrati
        win = self.app.dump()
        self.assertEqual(win[0]["title"], "Rozložení klávesnice")
        self.assertIn("Čeština", lsl_app.texts(win))

    def test_window_size_and_pss(self):
        self.start()
        time.sleep(1.5)
        geo = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "^Keyboard Layouts$"],
                             env={"DISPLAY": self.x.display, "PATH": os.environ["PATH"]}, capture_output=True,
                             text=True).stdout.split() if shutil.which("xdotool") else []
        if geo:
            out = subprocess.run(["xdotool", "getwindowgeometry", "--shell", geo[0]], capture_output=True, text=True,
                                 env={"DISPLAY": self.x.display, "PATH": os.environ["PATH"]}).stdout
            vals = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
            # okno podle obsahu (Python: drive 600 px vysoke s prazdnou plochou), na obrazovku 1366x768
            self.assertLess(int(vals["HEIGHT"]), 600)
            self.assertLessEqual(int(vals["HEIGHT"]), 768 - 16)
            self.assertLessEqual(int(vals["WIDTH"]), 1366)
        pss = self.app.pss_kb()
        print("\nluxos-keyboard (LSL) PSS %d kB" % pss, file=sys.stderr)
        self.assertLess(pss, 52218)                      # Python + GTK pod Xvfb: 52218 kB


REPO = os.path.normpath(os.path.join(PKG, "..", ".."))
WLT = os.path.join(REPO, "scripts", "wl-test", "wlt")
WLT_OUT = os.environ.get("WLT_OUT") or os.path.join(REPO, "out", "wl-test")
LUXWM_BUILD = os.environ.get("LUXWM_BUILD") or os.path.join(REPO, "out", "luxwm-test", "build")


@unittest.skipUnless(os.path.exists(os.path.join(LUXWM_BUILD, "luxwm")) and os.path.exists(WLT),
                     "luxwm (packages/luxwm/tests/build-host.sh) or wl-test harness missing")
class Wayland(unittest.TestCase):
    """Na Waylandu (luxwm headless) okno s kartami: rozlozeni z 00-keyboard.conf, pridani jen pro uzivatele."""

    def test_layouts_tab(self):
        tmp = tempfile.mkdtemp(dir=TMP)
        conf = os.path.join(tmp, "luxwm-system.conf")
        with open(os.path.join(REPO, "packages", "luxwm", "luxwm.conf")) as f:
            conf_lines = [line for line in f if not line.startswith("xwayland")]
        with open(conf, "w") as f:
            f.write("xwayland = no\n" + "".join(conf_lines))
        name = "kbd%d" % (os.getpid() % 10000)
        env = dict(os.environ, WLT_OUT=WLT_OUT, WLT_COMPOSITOR_ENV="LUXWM_SYSTEM_CONFIG=%s LD_LIBRARY_PATH=%s:%s/sysroot/usr/lib"
                   % (conf, LUXWM_BUILD, WLT_OUT))
        r = subprocess.run([WLT, "start", "--mode", "headless", "--size", "1366x768", "--timeout", "300", "--name", name,
                            "--", os.path.join(LUXWM_BUILD, "luxwm")], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        session = r.stdout.strip().splitlines()[-1]
        app = None
        try:
            wl = {}
            for line in subprocess.run([WLT, "env", session], capture_output=True, text=True, env=env).stdout.splitlines():
                key, _, value = line.removeprefix("export ").partition("=")
                wl[key] = value
            kconf = os.path.join(tmp, "00-keyboard.conf")
            with open(kconf, "w") as f:
                f.write(conf_text([("cz", ""), ("us", "")], ["grp:shifts_toggle"]))
            cfg = os.path.join(tmp, "config")
            aenv = {"PATH": os.environ["PATH"], "HOME": tmp, "XDG_CONFIG_HOME": cfg, "LANG": "en_US.UTF-8",
                    "WAYLAND_DISPLAY": wl["WAYLAND_DISPLAY"], "XDG_RUNTIME_DIR": wl["XDG_RUNTIME_DIR"],
                    "GDK_BACKEND": "wayland", "LUXOS_KEYBOARD_CONF": kconf, "LUXWM_SYSTEM_CONFIG": conf,
                    "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent"}
            app = lsl_app.App([binary()], aenv)
            self.assertTrue(app.wait(lambda: app.proc.poll() is None and "Czech" in lsl_app.texts(app.dump()), 20),
                            app.stderr())
            texts = lsl_app.texts(app.dump())
            for t in ("Layouts", "Czech", "English (US)", "Default · CZ", "Switching"):
                self.assertIn(t, texts)
            self.assertEqual(json.loads(app.ask("state", "state ")), {"layouts": [["cz", ""], ["us", ""]],
                                                                       "options": ["grp:shifts_toggle"], "own": False})
            app.send("click Add Layout…")
            self.assertTrue(app.wait(lambda: lsl_app.find(app.dump(), text="German   DE") is not None))
            self.assertIsNone(lsl_app.find(app.dump(), text="Czech   CZ"))      # uz pouzite chybi
            app.send("click German   DE")
            self.assertTrue(app.wait(lambda: json.loads(app.ask("state", "state "))["own"]))
            self.assertEqual(json.loads(app.ask("state", "state "))["layouts"], [["cz", ""], ["us", ""], ["de", ""]])
            with open(os.path.join(cfg, "luxwm", "luxwm.conf")) as f:
                self.assertIn("xkb_layout = cz,us,de", f.read())
        finally:
            if app:
                app.stop()
            subprocess.run([WLT, "stop", session], capture_output=True, env=env)
            shutil.rmtree(session, True)


if __name__ == "__main__":
    unittest.main()
