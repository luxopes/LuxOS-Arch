#!/usr/bin/env python3
"""luxos-touch: rozpoznani dotykove obrazovky, fyzicke klavesnice a senzoru z falesnych dat udev a /sys
(LUXOS_TOUCH_UDEV, LUXOS_TOUCH_SYS), prikazy relace jen vypsane (LUXOS_TOUCH_DRY=1), zamek otaceni,
prevod orientace senzoru a vychozi konfigurace gest. Nic se nespousti na skutecne obrazovce.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_touch.py
"""
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.dom.minidom

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
BIN = os.path.join(FILES, "bin", "luxos-touch")

# bitove mapy capabilities/key (slova po 64 bitech, nejvyssi prvni)
FULL_KEYBOARD = "0 0 0 0 1000000000007 ff9f207ac14057ff febeffdfffefffff fffffffffffffffe"   # QAZ + mezernik
POWER_BUTTON = "10000000000000 0"                                                           # KEY_POWER (116)
HOTKEYS = "0 0 0 0 4000000000000 0 0 0"                                                      # multimedia


class Machine:
    """Falesne /sys/class/input a /run/udev/data: devices = [(nazev, vlastnosti udev, klavesy, virtualni)]."""

    def __init__(self, root, devices):
        self.sys = os.path.join(root, "sys")
        self.udev = os.path.join(root, "udev")
        os.makedirs(self.udev)
        for i, (name, props, keys, virtual) in enumerate(devices):
            dev = os.path.join(root, "devices", "virtual" if virtual else "platform", f"input{i}")
            os.makedirs(os.path.join(dev, "capabilities"))
            with open(os.path.join(dev, "name"), "w") as f:
                f.write(name + "\n")
            with open(os.path.join(dev, "capabilities", "key"), "w") as f:
                f.write((keys or "0") + "\n")
            ev = os.path.join(self.sys, f"event{i}")
            os.makedirs(ev)
            os.symlink(dev, os.path.join(ev, "device"))
            with open(os.path.join(ev, "dev"), "w") as f:
                f.write(f"13:{64 + i}\n")
            with open(os.path.join(self.udev, f"c13:{64 + i}"), "w") as f:
                f.write("I:123\n" + "".join(f"E:{p}=1\n" for p in props))


class TouchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-touch-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_touch(self, machine, *args, accel="0", extra=None):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.home, "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
               "LUXOS_TOUCH_UDEV": machine.udev, "LUXOS_TOUCH_SYS": machine.sys, "LUXOS_TOUCH_ACCEL": accel,
               "LUXOS_TOUCH_DRY": "1", "LUXOS_TOUCH_SHARE": os.path.join(FILES, "touch")}
        env.update(extra or {})
        return subprocess.run(["bash", BIN, *args], env=env, capture_output=True, text=True, timeout=30)

    def machine(self, devices):
        return Machine(os.path.join(self.tmp, "m%d" % len(os.listdir(self.tmp))), devices)

    def test_tablet_without_keyboard(self):
        m = self.machine([("Power Button", ["ID_INPUT", "ID_INPUT_KEY", "ID_INPUT_KEYBOARD"], POWER_BUTTON, False),
                          ("ELAN Touchscreen", ["ID_INPUT", "ID_INPUT_TOUCHSCREEN"], None, False)])
        self.assertEqual(self.run_touch(m, "detect", accel="1").stdout.strip(), "touchscreen=1 keyboard=0 accel=1")

    def test_two_in_one_laptop(self):
        m = self.machine([("AT Translated Set 2 keyboard", ["ID_INPUT", "ID_INPUT_KEY", "ID_INPUT_KEYBOARD"], FULL_KEYBOARD, False),
                          ("Wacom HID Finger", ["ID_INPUT", "ID_INPUT_TOUCHSCREEN"], None, False)])
        self.assertEqual(self.run_touch(m, "detect").stdout.strip(), "touchscreen=1 keyboard=1 accel=0")

    def test_plain_laptop_and_fake_keyboards(self):
        # multimedia klavesy, vypinac a virtualni klavesnice (uinput) nejsou fyzicka klavesnice
        m = self.machine([("Video Bus", ["ID_INPUT", "ID_INPUT_KEY", "ID_INPUT_KEYBOARD"], HOTKEYS, False),
                          ("Power Button", ["ID_INPUT", "ID_INPUT_KEYBOARD"], POWER_BUTTON, False),
                          ("ydotoold virtual device", ["ID_INPUT", "ID_INPUT_KEYBOARD"], FULL_KEYBOARD, True),
                          ("SynPS/2 Touchpad", ["ID_INPUT", "ID_INPUT_TOUCHPAD"], None, False)])
        self.assertEqual(self.run_touch(m, "detect").stdout.strip(), "touchscreen=0 keyboard=0 accel=0")

    def test_session_without_touchscreen_does_nothing(self):
        m = self.machine([("AT keyboard", ["ID_INPUT_KEYBOARD"], FULL_KEYBOARD, False)])
        r = self.run_touch(m, "session")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config", "luxos", "touch-state")))

    def test_session_on_tablet(self):
        m = self.machine([("ELAN Touchscreen", ["ID_INPUT_TOUCHSCREEN"], None, False)])
        r = self.run_touch(m, "session", accel="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        # zamykaci obrazovka: tlacitko klavesnice, bez fyzicke klavesnice zobrazena hned
        self.assertIn("RUN xfconf-query -c xfce4-screensaver -p /lock/embedded-keyboard/enabled -n -t bool -s true", out)
        self.assertIn("-p /lock/embedded-keyboard/command -n -t string -s luxos-touch osk-embed", out)
        self.assertIn("-p /lock/embedded-keyboard/displayed -n -t bool -s true", out)
        self.assertIn("RUN gsettings set org.gnome.desktop.interface toolkit-accessibility true", out)
        if shutil.which("onboard"):
            self.assertIn("SPAWN onboard", out)
        if shutil.which("touchegg"):
            self.assertIn("SPAWN touchegg", out)
        self.assertIn("rotate-watch", out)
        self.assertIn(" guard", out)
        if shutil.which("unclutter"):
            self.assertIn("SPAWN unclutter --hide-on-touch", out)
        # sbernice zpristupneni hned zapnuta (Onboard se pak ukaze i v uz bezicich aplikacich)
        self.assertIn("org.a11y.Status IsEnabled <true>", out)
        with open(os.path.join(self.home, ".config", "luxos", "touch-state")) as f:
            self.assertEqual(f.read().strip(), "touchscreen=1 keyboard=0 accel=1")
        # gesta: vychozi konfigurace LuxOS do ~/.config/touchegg
        with open(os.path.join(self.home, ".config", "touchegg", "touchegg.conf"), encoding="utf-8") as f:
            self.assertIn("luxos-launchpad", f.read())

    def test_session_keeps_users_own_gestures(self):
        m = self.machine([("Touchscreen", ["ID_INPUT_TOUCHSCREEN"], None, False),
                          ("Keyboard", ["ID_INPUT_KEYBOARD"], FULL_KEYBOARD, False)])
        own = os.path.join(self.home, ".config", "touchegg", "touchegg.conf")
        os.makedirs(os.path.dirname(own))
        with open(own, "w", encoding="utf-8") as f:
            f.write("<touchégg><!-- mine --></touchégg>\n")
        out = self.run_touch(m, "session").stdout
        with open(own, encoding="utf-8") as f:
            self.assertIn("mine", f.read())
        # s fyzickou klavesnici: klavesnice na zamku jen tlacitkem, ne hned; bez senzoru zadne otaceni
        self.assertIn("-p /lock/embedded-keyboard/displayed -n -t bool -s false", out)
        self.assertNotIn("rotate-watch", out)

    def test_rotation_lock(self):
        m = self.machine([])
        self.assertEqual(self.run_touch(m, "rotation-lock", "status").stdout.strip(), "unlocked")
        self.assertEqual(self.run_touch(m, "rotation-lock", "toggle").stdout.strip(), "locked")
        self.assertTrue(os.path.exists(os.path.join(self.home, ".config", "luxos", "rotation-lock")))
        self.assertEqual(self.run_touch(m, "rotation-lock", "off").stdout.strip(), "unlocked")
        self.assertNotEqual(self.run_touch(m, "rotation-lock", "sideways").returncode, 0)

    def test_orientation_mapping(self):
        script = (f"source <(sed -n '/^orientation_to_rotation()/,/^}}/p' {BIN}); "
                  "for o in normal bottom-up left-up right-up undefined; do orientation_to_rotation $o || echo none; done")
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.split()
        self.assertEqual(out, ["normal", "inverted", "left", "right", "none"])

    def test_osk_size_from_screen(self):
        m = self.machine([])
        for screen, land, port in (("1920 1080", 432, 576), ("1280 800", 320, 384), ("1080 1920", 432, 576),
                                   ("1024 600", 240, 307), ("800 480", 205, 240)):
            with self.subTest(screen=screen):
                shutil.rmtree(os.path.join(self.home, ".config"), ignore_errors=True)
                out = self.run_touch(m, "osk-size", extra={"LUXOS_TOUCH_SCREEN": screen}).stdout
                self.assertIn("RUN gsettings set org.onboard.window.landscape dock-height %d" % land, out)
                self.assertIn("RUN gsettings set org.onboard.window.portrait dock-height %d" % port, out)
        # plovouci tlacitko klavesnice u praveho okraje (1920x1080: x 1844, y 626), ne vlevo nahore
        shutil.rmtree(os.path.join(self.home, ".config"), ignore_errors=True)
        out = self.run_touch(m, "osk-size", extra={"LUXOS_TOUCH_SCREEN": "1920 1080"}).stdout
        self.assertIn("RUN gsettings set org.onboard.icon-palette.landscape x 1844", out)
        self.assertIn("RUN gsettings set org.onboard.icon-palette.landscape y 626", out)
        self.assertIn("RUN gsettings set org.onboard.icon-palette.portrait x 1004", out)

    def test_guard_reattaches_floating_touch(self):
        """Dotyk odpojeny od ukazatele (Onboard) se po dvou kontrolach vrati; pripojeny se nemeni."""
        m = self.machine([("ELAN Touchscreen", ["ID_INPUT_TOUCHSCREEN"], None, False)])
        fake = os.path.join(self.tmp, "fakebin")
        os.makedirs(fake)
        count = os.path.join(self.tmp, "count")
        script = """#!/bin/bash
case "$1 $2" in
  "list --id-only") echo 7 ;;
  "list-props 7") printf '\\tDevice Node (270):\\t"/dev/input/event0"\\n' ;;
  "list --short") n=$(cat %(c)s 2>/dev/null || echo 0); echo $((n + 1)) > %(c)s
                  if (( n < 3 )); then echo "∼ ELAN Touchscreen  id=7 [floating slave]"
                  else echo "↳ ELAN Touchscreen  id=7 [slave  pointer  (2)]"; fi ;;
esac
""" % {"c": count}
        for name, body in (("xinput", script), ("xset", "#!/bin/sh\nexit 0\n")):
            with open(os.path.join(fake, name), "w") as f:
                f.write(body)
            os.chmod(os.path.join(fake, name), 0o755)
        r = self.run_touch(m, "guard", extra={"PATH": fake + ":/usr/bin:/bin", "LUXOS_TOUCH_GUARD_EVERY": "0.05",
                                              "LUXOS_TOUCH_GUARD_ONCE": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("RUN xinput reattach 7 Virtual core pointer"), 2, r.stdout)

    @unittest.skipUnless(shutil.which("onboard"), "needs onboard")
    def test_rofi_begin_end(self):
        """Launchpad/Hledani (rofi): na dotykovem zarizeni klavesnice + okno nad ni, jinak nic."""
        m = self.machine([])
        extra = {"LUXOS_TOUCH_SCREEN": "1280 800", "LUXOS_TOUCH_OSK_HEIGHT": "320",
                 "XDG_RUNTIME_DIR": self.tmp}
        # bez dotykove obrazovky (zadny touch-state): zadne volby, klavesnice se nemeni
        r = self.run_touch(m, "rofi-begin", "110", "142", "4", extra=extra)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        os.makedirs(os.path.join(self.home, ".config", "luxos"))
        with open(os.path.join(self.home, ".config", "luxos", "touch-state"), "w") as f:
            f.write("touchscreen=1 keyboard=1 accel=1\n")
        out = self.run_touch(m, "rofi-begin", "110", "142", "4", extra=extra).stdout.splitlines()
        # klepnuti na klavesnici mimo okno rofi ho nezavre; 800 - 320 - 28 - 24 - 142 = 286 -> 2 radky
        self.assertEqual(out, ["-no-click-to-exit", "-theme-str",
                               "window { location: north; anchor: north; y-offset: 40px; } listview { lines: 2; }"])
        # vetsi displej (Z13 1920x1200, klavesnice 480 px): 4 radky (nejvys MAX)
        big = dict(extra, LUXOS_TOUCH_SCREEN="1920 1200", LUXOS_TOUCH_OSK_HEIGHT="480")
        out = self.run_touch(m, "rofi-begin", "110", "142", "4", extra=big).stdout.splitlines()
        self.assertTrue(out[-1].endswith("listview { lines: 4; }"), out)
        # bez rozmeru (Hledani bez argumentu): jen -no-click-to-exit
        self.assertEqual(self.run_touch(m, "rofi-begin", extra=extra).stdout.splitlines(), ["-no-click-to-exit"])
        # konec: klavesnice byla pred otevrenim schovana -> zase schovat; podruhe uz nic
        self.assertIn("RUN osk hide", self.run_touch(m, "rofi-end", extra=extra).stdout)
        self.assertEqual(self.run_touch(m, "rofi-end", extra=extra).stdout, "")

    def test_osk_embed_without_touchscreen_exits(self):
        m = self.machine([("Keyboard", ["ID_INPUT_KEYBOARD"], FULL_KEYBOARD, False)])
        r = self.run_touch(m, "osk-embed")
        self.assertEqual((r.returncode, r.stdout), (1, ""))

    def test_touchegg_config_is_valid(self):
        path = os.path.join(FILES, "touch", "touchegg.conf")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(text.startswith("<!-- luxos-touchegg"))
        doc = xml.dom.minidom.parseString(text.encode("utf-8"))
        gestures = {(g.getAttribute("type"), g.getAttribute("fingers"), g.getAttribute("direction"))
                    for g in doc.getElementsByTagName("gesture")}
        self.assertIn(("SWIPE", "3", "UP"), gestures)
        self.assertIn(("TAP", "2", ""), gestures)
        # plochy i ctyrmi prsty (tri prsty s otevrenou aplikaci casto posouvaji v aplikaci)
        self.assertIn(("SWIPE", "4", "LEFT"), gestures)
        self.assertIn(("SWIPE", "4", "RIGHT"), gestures)

    def test_dconf_defaults(self):
        with open(os.path.join(FILES, "dconf", "20-luxos-touch"), encoding="utf-8") as f:
            text = f.read()
        # klavesnice se ukaze i u konvertibilu s pripojenou vestavenou klavesnici; psani na ni ji schova
        for line in ("[org/onboard/auto-show]", "enabled=true", "keyboard-device-detection-enabled=false",
                     "hide-on-key-press=true", "tablet-mode-detection-enabled=false", "docking-enabled=true",
                     "start-minimized=true"):
            self.assertIn(line, text)


if __name__ == "__main__":
    unittest.main()
