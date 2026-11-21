#!/usr/bin/env python3
"""LuxOS - Sporic a zamek (files/lsl/luxos-lock-settings.lsl): v relaci X11 kanal xfce4-screensaver pres
xfconf-query (falesny program se stavem v JSON), na Waylandu (luxwm headless) primo soubor kanalu, ktery cte
luxos-lock-session (luxos_xfconf.lsl).

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -p MemorySwapMax=0 -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_lock_settings.py -v
"""
import json
import os
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import lsl_app_harness as h

HERE = Path(__file__).resolve().parent
FILES = HERE.parent / "files"
# falesny xfconf-query: -p cesta [-s hodnota] nad JSON (FAKE_XFCONF); -a pridava do pole
XFCONF = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write("xfconf-query " + " ".join(a) + "\\n")
path = os.environ["FAKE_XFCONF"]
data = json.load(open(path)) if os.path.exists(path) else {}
prop = a[a.index("-p") + 1]
if "-s" in a:
    value = a[a.index("-s") + 1]
    data[prop] = value
    json.dump(data, open(path, "w"))
elif prop in data:
    print(data[prop])
else:
    sys.exit(1)
"""


def setUpModule():
    if not h.lslc_ok():
        raise unittest.SkipTest("lslc 0.11 is not installed")
    h.build("luxos-lock-settings")


def find(dump, kind, text):
    for i, line in enumerate(dump):
        if line == f"GtkLabel\t{text}":
            for nxt in dump[i + 1:i + 5]:
                if nxt.startswith(kind + "\t"):
                    return nxt.split("\t")[1:]
    return None


def labels(dump):
    return [line.split("\t")[1] for line in dump if line.startswith("GtkLabel\t")]


class Base(unittest.TestCase):
    backend = h.X11App

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lock-", dir=h.private_dir()))
        self.env = h.base_env(self.tmp)
        fakes = h.fake_bin(self.tmp / "bin", ["xfconf-query", "xflock4", "loginctl", "luxos-fingerprint"],
                           {"xfconf-query": XFCONF})
        self.env.update(PATH=str(fakes) + ":" + os.environ["PATH"], FAKE_XFCONF=str(self.tmp / "xfconf.json"),
                        LUXOS_FPRINT_SERVICE=str(self.tmp / "no-fprintd"))

    def xfconf(self, values=None):
        if values is not None:
            (self.tmp / "xfconf.json").write_text(json.dumps(values))
        p = self.tmp / "xfconf.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def run_app(self, script, size=(1366, 768)):
        app = self.backend([str(h.build("luxos-lock-settings"))], self.env, script, tmp=self.tmp, size=size) \
            if self.backend is h.X11App else self.backend([str(h.build("luxos-lock-settings"))], self.env, script,
                                                          tmp=self.tmp)
        self.addCleanup(app.close)
        return app

    def calls(self):
        log = self.tmp / "fake.log"
        return log.read_text().splitlines() if log.exists() else []


@unittest.skipUnless(h.HAVE_X11, "Xvfb, xdotool or dbus-run-session missing")
class X11(Base):
    def test_values_shown(self):
        self.xfconf({"/saver/idle-activation/enabled": "true", "/saver/idle-activation/delay": "15",
                     "/saver/mode": "2", "/saver/themes/list": "Value is an array with 1 items:\n\nscreensavers-luxos-aurora",
                     "/lock/saver-activation/delay": "5", "/lock/sleep-activation": "false"})
        d = self.run_app(["dump", "quit"]).wait_dump()
        self.assertEqual(find(d, "GtkComboBoxText", "Start after inactivity of"), ["15"])
        self.assertIn("GtkComboBoxText\tscreensavers-luxos-aurora", d)
        self.assertEqual(find(d, "GtkComboBoxText", "Require password after the screen saver starts"), ["5"])
        self.assertEqual(find(d, "GtkSwitch", "Lock when the computer goes to sleep"), ["off"])
        self.assertNotIn("Fingerprint Login", labels(d))

    def test_custom_value_kept(self):
        # Hodnota mimo nabidku (LOCK_AFTER od spravce, napr. 3 min) se ukaze, ne "Nikdy"/"Hned"
        self.xfconf({"/saver/idle-activation/delay": "7", "/lock/saver-activation/delay": "3"})
        d = self.run_app(["dump", "quit"]).wait_dump()
        self.assertEqual(find(d, "GtkComboBoxText", "Start after inactivity of"), ["7"])
        self.assertEqual(find(d, "GtkComboBoxText", "Require password after the screen saver starts"), ["3"])

    def test_defaults_and_disabled(self):
        d = self.run_app(["dump", "quit"]).wait_dump()
        self.assertEqual(find(d, "GtkComboBoxText", "Start after inactivity of"), ["10"])
        self.assertIn("GtkComboBoxText\tblank", d)
        self.assertEqual(find(d, "GtkComboBoxText", "Require password after the screen saver starts"), ["0"])
        self.xfconf({"/saver/idle-activation/enabled": "false", "/lock/enabled": "false"})
        d = self.run_app(["dump", "quit"]).wait_dump(2)
        self.assertEqual(find(d, "GtkComboBoxText", "Start after inactivity of"), ["0"])
        self.assertEqual(find(d, "GtkComboBoxText", "Require password after the screen saver starts"), ["never"])

    def test_changes_written(self):
        app = self.run_app(["combo Start after inactivity of 30", "combo Require password after the screen saver starts never",
                            "switch Lock when the computer goes to sleep off", "click Lock Now", "wait 300", "quit"])
        app.wait_exit()
        x = self.xfconf()
        self.assertEqual(x["/saver/idle-activation/enabled"], "true")
        self.assertEqual(x["/saver/idle-activation/delay"], "30")
        self.assertEqual(x["/lock/saver-activation/enabled"], "false")
        self.assertEqual(x["/lock/sleep-activation"], "false")
        self.assertIn("xfconf-query -c xfce4-screensaver -p /saver/idle-activation/delay -n -t int -s 30", self.calls())
        self.assertIn("xflock4", self.calls())
        self.assertFalse((self.tmp / "config/xfce4/xfconf/xfce-perchannel-xml/xfce4-screensaver.xml").exists())

    def test_never_disables_idle(self):
        app = self.run_app(["combo Start after inactivity of 0", "wait 300", "quit"])
        app.wait_exit()
        self.assertEqual(self.xfconf()["/saver/idle-activation/enabled"], "false")
        self.assertNotIn("/saver/idle-activation/delay", self.xfconf())

    def test_require_password_again(self):
        self.xfconf({"/lock/enabled": "false"})
        app = self.run_app(["combo Require password after the screen saver starts 1", "wait 300", "quit"])
        app.wait_exit()
        x = self.xfconf()
        self.assertEqual([x["/lock/enabled"], x["/lock/saver-activation/enabled"], x["/lock/saver-activation/delay"]],
                         ["true", "true", "1"])

    def test_fingerprint_row(self):
        (self.tmp / "fprintd.service").write_text("")
        self.env["LUXOS_FPRINT_SERVICE"] = str(self.tmp / "fprintd.service")
        app = self.run_app(["dump", "click Set Up…", "wait 300", "quit"])
        self.assertIn("Fingerprint Login", labels(app.wait_dump()))
        app.wait_exit()
        self.assertIn("luxos-fingerprint", self.calls())

    def test_sized_to_content(self):
        app = self.run_app(["wait 600000"])
        win = app.window("Screen Saver & Lock")
        self.assertLess(win["height"], 520 + 45 - 40, win)        # drive 520 px s prazdnou plochou dole

    def test_czech(self):
        self.env["LANG"] = "cs_CZ.UTF-8"
        d = self.run_app(["dump", "quit"]).wait_dump()
        self.assertIn("Zamknout teď", [line.split("\t")[1] for line in d if line.startswith("GtkButton")])


@unittest.skipUnless(h.HAVE_WAYLAND, "luxwm (LUXWM_BUILD) or wl-test sysroot missing")
class Wayland(Base):
    backend = h.WaylandApp

    def channel(self):
        return self.tmp / "config/xfce4/xfconf/xfce-perchannel-xml/xfce4-screensaver.xml"

    def props(self):
        out = {}

        def walk(node, prefix):
            for p in node.findall("property"):
                path = prefix + "/" + p.get("name")
                if p.get("type") not in ("empty", "array"):
                    out[path] = p.get("value")
                walk(p, path)
        walk(ET.parse(self.channel()).getroot(), "")
        return out

    def test_idle_lock_from_channel(self):
        self.channel().parent.mkdir(parents=True)
        self.channel().write_text("""<?xml version="1.0" encoding="UTF-8"?>

<channel name="xfce4-screensaver" version="1.0">
  <property name="saver" type="empty">
    <property name="idle-activation" type="empty">
      <property name="delay" type="int" value="10"/>
    </property>
    <property name="themes" type="empty">
      <property name="list" type="array">
        <value type="string" value="screensavers-luxos-aurora"/>
      </property>
    </property>
  </property>
  <property name="lock" type="empty">
    <property name="saver-activation" type="empty">
      <property name="delay" type="int" value="5"/>
    </property>
  </property>
</channel>
""")
        app = self.run_app(["dump", "combo Lock the screen after inactivity of 2", "switch Lock when the computer goes to sleep off",
                            "click Lock Now", "wait 300", "quit"])
        d = app.wait_dump()
        app.wait_exit()
        # setric na Waylandu neni: jedna volba, necinnost = setric + zpozdeni hesla (jako luxos-lock-session)
        self.assertEqual(find(d, "GtkComboBoxText", "Lock the screen after inactivity of"), ["15"])
        self.assertNotIn("Start after inactivity of", labels(d))
        self.assertNotIn("Require password after the screen saver starts", labels(d))
        p = self.props()
        self.assertEqual(p["/saver/idle-activation/delay"], "2")
        self.assertEqual(p["/saver/idle-activation/enabled"], "true")
        self.assertEqual(p["/lock/saver-activation/delay"], "0")
        self.assertEqual(p["/lock/sleep-activation"], "false")
        self.assertIn('<value type="string" value="screensavers-luxos-aurora"/>', self.channel().read_text())
        self.assertFalse([c for c in self.calls() if c.startswith("xfconf-query")], self.calls())
        self.assertIn("loginctl lock-session", self.calls())

    def test_never_and_lock_session_reads_it(self):
        app = self.run_app(["dump", "combo Lock the screen after inactivity of 0", "wait 300", "quit"])
        d = app.wait_dump()
        app.wait_exit()
        self.assertEqual(find(d, "GtkComboBoxText", "Lock the screen after inactivity of"), ["10"])   # vychozi 10 + 0
        self.assertEqual(self.props()["/saver/idle-activation/enabled"], "false")
        # stejny cteci kod jako luxos-lock-session (luxos_xfconf.channel)
        probe = Path(tempfile.mkdtemp(prefix="xfprobe-", dir=h.private_dir()))
        (probe / "p.lsl").write_text('load luxos_xfconf as xfconf\nc = xfconf.channel("xfce4-screensaver")\n'
                                     'print c.get("/saver/idle-activation/enabled", "?")\n')
        r = subprocess.run([h.LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(h.LSL_DIR), str(probe / "p.lsl"),
                            str(probe / "p")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        out = subprocess.run([str(probe / "p")], env={"XDG_CONFIG_HOME": str(self.tmp / "config"), "HOME": str(self.tmp)},
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "false")


class Static(unittest.TestCase):
    def test_themes_exist(self):
        src = (FILES / "lsl/luxos-lock-settings.lsl").read_text()
        self.assertIn('["screensavers-luxos-wallpaper", "desktop", "Desktop wallpaper and clock"]', src)
        styles = re.findall(r'\["(screensavers-[a-z-]+)", "([a-z]+)"', src)
        self.assertGreater(len(styles), 5)
        for theme, style in styles:
            desktop = FILES / "screensaver" / (theme[len("screensavers-"):] + ".desktop")
            self.assertIn(f"--style {style}\n", desktop.read_text())


if __name__ == "__main__":
    unittest.main()
