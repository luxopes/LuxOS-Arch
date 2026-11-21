#!/usr/bin/env python3
"""LuxOS 1.1.0 (WP-12) - v relaci na Waylandu nic z luxos-hub, Ovladaciho centra, Kalendare,
luxos_awake ani luxos-appearance nevola xfconf, xfwm4 ani xfce4-panel.

    python3 -m unittest packages/luxos-desktop/tests/test_wayland_no_xfconf.py -v

LSL (staticky): kazdy radek s xfconf-query / org.xfce.Xfconf / xfwm4 / xfce4-panel / org.xfce.Panel
a kazde pouziti funkce *_x11 musi byt jen v relaci X11: uvnitr funkce *_x11, ve vetvi
`if not wayland():` (i `... and not wayland()`), ve vetvi `else` od `if wayland():`, nebo za
`if wayland(): ... return` na zacatku funkce.

luxos-appearance (za behu): vsechny podprikazy s WAYLAND_DISPLAY a falesnymi programy v PATH, ktere
zapisuji, co se volalo; nic se nemeni na skutecnem systemu.
"""
import os
import re
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.normpath(os.path.join(HERE, "..", "files"))
MODULES = ["luxos-hub.lsl", "luxos_cc.lsl", "luxos_cal.lsl", "luxos_awake.lsl", "luxos-settings.lsl"]
APPEARANCE = os.path.join(FILES, "bin", "luxos-appearance")
TOKENS = ["xfconf-query", "org.xfce.Xfconf", "xfwm4", "xfce4-panel", "org.xfce.Panel"]
X11_REF = re.compile(r"\b(\w+_x11)\b")


def indent(line):
    return len(line) - len(line.lstrip(" "))


def x11_condition(header):
    cond = header.strip()
    return cond.startswith("if ") and "not wayland()" in cond and " or " not in cond


def guarded(lines, start, i):
    """Je radek i (ve funkci od radku start) jen v relaci X11?"""
    level = indent(lines[i])
    top = indent(lines[start]) + 4
    j = i - 1
    while j > start and level > top:
        line = lines[j]
        if line.strip() and indent(line) < level:
            level = indent(line)
            head = line.strip()
            if x11_condition(head):
                return True
            if head == "else:":
                k = j - 1
                while k > start and (not lines[k].strip() or indent(lines[k]) > level):
                    k -= 1
                if lines[k].strip() == "if wayland():" and indent(lines[k]) == level:
                    return True
        j -= 1
    # if wayland(): ... return ... end na urovni funkce pred radkem
    j = start + 1
    while j < i:
        if lines[j].strip() == "if wayland():" and indent(lines[j]) == top:
            k = j + 1
            last = ""
            while k < i and not (lines[k].strip() == "end" and indent(lines[k]) == top):
                if lines[k].strip():
                    last = lines[k].strip()
                k += 1
            if k < i and last.startswith("return"):
                return True
        j += 1
    return False


def violations(source):
    """[(cislo radku, radek)] s X11 volanim mimo vetev pro X11."""
    lines = source.split("\n")
    out = []
    func, start = "", 0
    for i, line in enumerate(lines):
        code = line.strip()
        if not code or code.startswith("#"):
            continue
        m = re.match(r"function (\w+)\(", line)
        if m:
            func, start = m.group(1), i
            continue
        refs = X11_REF.findall(code)
        if not refs and not any(t in code for t in TOKENS):
            continue
        if func.endswith("_x11") and indent(line) > 0:
            continue
        if indent(line) == 0 or not guarded(lines, start, i):
            out.append((i + 1, code))
    return out


class LslStatic(unittest.TestCase):
    def test_modules_x11_only(self):
        for name in MODULES:
            with open(os.path.join(FILES, "lsl", name), encoding="utf-8") as f:
                source = f.read()
            with self.subTest(module=name):
                self.assertTrue('env.get("WAYLAND_DISPLAY", "")' in source)
                # aspon jedna podminka podle relace (jinak by test nic nekontroloval)
                self.assertGreater(len(re.findall(r"\bif .*wayland\(\)", source)), 0)
                self.assertEqual(violations(source), [])

    def test_checker_catches_unguarded(self):
        bad = ("function a():\n    call glib.spawn([\"xfce4-panel\", \"-r\"])\n    return 0\nend\n"
               "function b():\n    if wayland():\n        call c_x11()\n    end\n    return 0\nend\n"
               "function d():\n    if wayland():\n        call log(1)\n    end\n    call c_x11()\n    return 0\nend\n"
               "function e():\n    if x or not wayland():\n        call c_x11()\n    end\n    return 0\nend\n"
               "call timeout(5, c_x11)\n")
        self.assertEqual([n for n, _ in violations(bad)], [2, 7, 15, 20, 24])

    def test_checker_accepts_guards(self):
        good = ("function c_x11():\n    call glib.spawn([\"xfwm4\", \"--replace\"])\n    return 0\nend\n"
                "function f():\n    if not wayland():\n        call c_x11()\n    end\n    return 0\nend\n"
                "function g():\n    if wayland():\n        call log(1)\n    else:\n        call c_x11()\n    end\n    return 0\nend\n"
                "function h():\n    if wayland():\n        return 0\n    end\n    call c_x11()\n    return 0\nend\n"
                "function i():\n    if s != 0 and not wayland():\n        try:\n            call c_x11()\n        end\n    end\nend\n")
        self.assertEqual(violations(good), [])


FAKE = '#!/bin/sh\nprintf "%s\\n" "$(basename "$0") $*" >>"$FAKE_LOG"\n'
FAKES = {
    "xfconf-query": FAKE,
    "xfwm4": FAKE,
    "xfce4-panel": FAKE,
    "xrandr": FAKE + 'echo "Monitors: 1"\necho " 0: +*Virtual-1 1920/508x1080/286+0+0  Virtual-1"\n',
    "pgrep": FAKE + "exit 1\n",
    "gdbus": FAKE + "exit 1\n",
    "busctl": FAKE + "exit 1\n",
    "gsettings": FAKE,
    "python3": FAKE + "echo dark\n",
    # luxwm-msg zapise i obsah souboru rezimu v okamziku volani (luxwm ho cte pri reload)
    "luxwm-msg": ('#!/bin/sh\nprintf "%s\\n" "luxwm-msg $* file=$(cat "$XDG_CONFIG_HOME/luxos/appearance")" >>"$FAKE_LOG"\n'
                  'exit "${FAKE_LUXWM_EXIT:-0}"\n'),
}
WAYLAND_COMMANDS = [
    ["dark"], ["light"], ["toggle"], ["auto"], ["reapply"], ["wm-theme"], ["greeter-sync"],
    ["wallpaper", "/etc/os-release"], ["wallpaper", "/etc/os-release", "HDMI-A-1"],
    ["wallpaper-mode", "fit"], ["bar-opacity", "40"], ["dock-opacity", "50"], ["bar-style", "rounded"],
    ["bar-clock", "center"], ["bar-text", "white"], ["desktop-scrim", "off"], ["restart-panel"],
    ["bar-ink", "dark"], ["panel-css"], ["status"], ["mode"],
]


class AppearanceWayland(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-appearance-wl-")
        fake = os.path.join(self.tmp, "fake")
        os.makedirs(fake)
        for name, body in FAKES.items():
            p = os.path.join(fake, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, stat.S_IRWXU)
        self.fake = fake
        self.cfg = os.path.join(self.tmp, "config")
        self.log = os.path.join(self.tmp, "calls.log")
        self.env = {"PATH": fake + ":/usr/bin:/bin", "HOME": self.tmp, "XDG_CONFIG_HOME": self.cfg,
                    "XDG_DATA_HOME": os.path.join(self.tmp, "data"), "XDG_RUNTIME_DIR": self.tmp,
                    "USER": "test", "LANG": "C", "FAKE_LOG": self.log,
                    "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent"}

    def run_cmd(self, args, wayland=True, **extra):
        env = dict(self.env, **extra)
        if wayland:
            env["WAYLAND_DISPLAY"] = "wayland-1"
        return subprocess.run(["bash", APPEARANCE] + args, env=env, capture_output=True, text=True, timeout=30)

    def calls(self):
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def mode(self):
        with open(os.path.join(self.cfg, "luxos", "appearance")) as f:
            return f.read().strip()

    def test_no_x11_calls(self):
        for args in WAYLAND_COMMANDS:
            r = self.run_cmd(args)
            with self.subTest(args=args):
                self.assertEqual(r.returncode, 0, r.stderr)
        bad = [c for c in self.calls()
               if c.split()[0] in ("xfconf-query", "xfwm4", "xfce4-panel", "xrandr", "pgrep", "gdbus")
               or "plank" in c]
        self.assertEqual(bad, [])

    def test_theme_to_luxwm(self):
        self.run_cmd(["dark"])
        self.assertEqual(self.mode(), "dark")
        self.run_cmd(["toggle"])
        self.assertEqual(self.mode(), "light")
        calls = self.calls()
        self.assertIn("luxwm-msg set-theme dark file=dark", calls)
        self.assertIn("luxwm-msg set-theme light file=light", calls)
        # GTK tema a barevne schema plati i na Waylandu
        self.assertIn("gsettings set org.gnome.desktop.interface color-scheme prefer-light", calls)
        self.assertIn("gsettings set org.gnome.desktop.interface gtk-theme WhiteSur-Light", calls)

    def test_luxwm_unreachable_or_missing(self):
        r = self.run_cmd(["dark"], FAKE_LUXWM_EXIT="2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.mode(), "dark")
        os.unlink(os.path.join(self.fake, "luxwm-msg"))
        r = self.run_cmd(["light"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.mode(), "light")

    def test_x11_unchanged(self):
        r = self.run_cmd(["dark"], wayland=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls()
        self.assertIn("xfconf-query -c xsettings -p /Net/ThemeName -n -t string -s WhiteSur-Dark", calls)
        self.assertTrue(any("plank" in c for c in calls))
        self.assertFalse(any(c.startswith("luxwm-msg") for c in calls))


if __name__ == "__main__":
    unittest.main()
