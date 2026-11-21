#!/usr/bin/env python3
"""LuxOS - Nastaveni > Vzhled, Zpristupneni a Okna a plochy (luxos_page_appearance/accessibility/windows.lsl).

    ISO_NAME=look ~/LuxOS-Arch/out/wt-settings-build/runiso.sh \\
      python3 -m unittest packages/luxos-desktop/tests/test_settings_appearance.py -v

Kazdy ovladac se zmeni pres okno (LUXOS_TEST_CONTROL: combo/switch RADEK = HODNOTA, font) a overi se ucinek:
X11 = falesny xfconf-query (stav v JSON i s typem), Wayland = soubory kanalu xfconf v ~/.config, GSettings
(GSETTINGS_BACKEND=keyfile), ~/.config/luxwm/luxwm.conf a to, ze ho luxwm headless opravdu pouzil
(IPC get_state, stopa luxwm). Wayland cast potrebuje luxwm (LUXWM_BUILD) a sysroot harnessu wl-test.
"""
import configparser
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import lsl_app
import lsl_app_harness as h

XFCONF = r'''#!/usr/bin/env python3
"""Falesny xfconf-query: FAKE_XFCONF = JSON {"kanal": {"/vlastnost": [typ, hodnota]}}, kazde volani do FAKE_LOG."""
import json, os, sys
a = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write("xfconf-query " + " ".join(a) + "\n")
path = os.environ["FAKE_XFCONF"]
try:
    db = json.load(open(path))
except (OSError, ValueError):
    db = {}
chan = db.setdefault(a[a.index("-c") + 1], {})
prop = a[a.index("-p") + 1] if "-p" in a else None
if "-l" in a:
    for k in sorted(chan):
        print(k + ("  " + chan[k][1] if "-v" in a else ""))
    sys.exit(0)
if "-r" in a:
    chan.pop(prop, None)
elif "-s" in a:
    chan[prop] = [a[a.index("-t") + 1] if "-t" in a else chan.get(prop, ["string"])[0], a[a.index("-s") + 1]]
else:
    if prop not in chan:
        sys.exit(1)
    print(chan[prop][1])
    sys.exit(0)
json.dump(db, open(path, "w"))
'''

LUXWM_SYSTEM = Path(__file__).resolve().parents[2] / "luxwm/luxwm.conf"


def setUpModule():
    if not h.lslc_ok():
        raise unittest.SkipTest("lslc 0.11 is not installed")
    h.build("luxos-settings")


def make_env(tmp):
    env = h.base_env(tmp)
    fakes = h.fake_bin(tmp / "bin", ["xfconf-query", "luxos-appearance", "onboard"], {"xfconf-query": XFCONF})
    icons = tmp / "icons"
    for name, files in (("Plain", {"index.theme": "[Icon Theme]\nName=Plain Icons\nDirectories=48x48/apps\n"}),
                        ("WhiteSur-light", {"index.theme": "[Icon Theme]\nName=WhiteSur-light\nDirectories=apps\n"}),
                        ("hicolor", {"index.theme": "[Icon Theme]\nName=Hicolor\nDirectories=apps\n"}),
                        ("Pointy", {"index.theme": "[Icon Theme]\nName=Pointy\n", "cursors/left_ptr": ""}),
                        ("WhiteSur-cursors", {"index.theme": "[Icon Theme]\nName=WhiteSur Cursors\n", "cursors/left_ptr": ""})):
        for rel, content in files.items():
            (icons / name / rel).parent.mkdir(parents=True, exist_ok=True)
            (icons / name / rel).write_text(content)
    env.update(PATH=str(fakes) + ":" + os.environ["PATH"], FAKE_XFCONF=str(tmp / "xfconf.json"),
               LUXOS_ICON_DIRS=str(icons), FAKE_OUT_luxos_appearance="light",
               LUXWM_SYSTEM_CONFIG=str(LUXWM_SYSTEM))
    return env


def gsettings(tmp):
    kf = configparser.ConfigParser(interpolation=None)
    kf.read(tmp / "config/glib-2.0/settings/keyfile")
    sec = "org/gnome/desktop/interface"
    return dict(kf[sec]) if kf.has_section(sec) else {}


def channel_file(tmp, name):
    """{"/Cesta/Vlastnost": (typ, hodnota)} ze souboru kanalu uzivatele (Wayland)."""
    path = tmp / f"config/xfce4/xfconf/xfce-perchannel-xml/{name}.xml"
    if not path.exists():
        return {}
    out = {}

    def walk(node, prefix):
        for p in node.findall("property"):
            key = prefix + "/" + p.get("name")
            if p.get("type") not in ("empty", None):
                out[key] = (p.get("type"), p.get("value"))
            walk(p, key)
    walk(ET.parse(path).getroot(), "")
    return out


def luxwm_conf(tmp):
    path = tmp / "config/luxwm/luxwm.conf"
    out = {}
    for line in (path.read_text().splitlines() if path.exists() else []):
        if line.startswith("["):
            break
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def fake_log(tmp):
    p = tmp / "fake.log"
    return p.read_text().splitlines() if p.exists() else []


def wait_for(cond, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


class Session:
    """luxos-settings PAGE ve vlastnim Xvfb nebo v luxwm headless, rizene pres stdin (luxos_testctl)."""

    def __init__(self, tmp, env, page, wayland=False, ui_test=None):
        self.tmp, self.wlt_session, self.xvfb = tmp, None, None
        env = dict(env)
        if ui_test:
            (tmp / "ui-test").write_text("\n".join(ui_test) + "\n")
            env["LUXOS_UI_TEST"] = str(tmp / "ui-test")
        if wayland:
            cenv = (f"LUXWM_SYSTEM_CONFIG={self.system_conf()} LD_LIBRARY_PATH={h.LUXWM_BUILD}:{h.SYSROOT}/usr/lib "
                    f"XDG_CONFIG_HOME={tmp}/config LUXWM_TRACE=1")
            name = f"look{os.getpid() % 10000}-{int(time.monotonic() * 1000) % 100000}"
            r = subprocess.run([str(h.WLT), "start", "--mode", "headless", "--size", "1366x768", "--timeout", "600",
                                "--name", name, "--", str(h.LUXWM_BUILD / "luxwm")],
                               env=dict(os.environ, WLT_COMPOSITOR_ENV=cenv), capture_output=True, text=True, timeout=120)
            if r.returncode:
                raise AssertionError("wlt start: " + r.stdout + r.stderr)
            self.wlt_session = Path(r.stdout.strip().splitlines()[-1])
            wl = {}
            for line in subprocess.run([str(h.WLT), "env", str(self.wlt_session)], capture_output=True,
                                       text=True).stdout.splitlines():
                k, _, v = line.removeprefix("export ").partition("=")
                wl[k] = v
            env.update(WAYLAND_DISPLAY=wl["WAYLAND_DISPLAY"], XDG_RUNTIME_DIR=wl["XDG_RUNTIME_DIR"], GDK_BACKEND="wayland")
            self.sock = Path(wl["XDG_RUNTIME_DIR"]) / f"luxwm-{wl['WAYLAND_DISPLAY']}.sock"
        else:
            self.xvfb = lsl_app.Xvfb()
            env["DISPLAY"] = self.xvfb.display
        self.app = lsl_app.App(["dbus-run-session", "--", str(h.build("luxos-settings")), page], env)
        # okno je hotove, kdyz odpovi na prikaz
        self.app.ask("state", "state ", timeout=30)

    def system_conf(self):
        conf = self.tmp / "luxwm-system.conf"
        conf.write_text("xwayland = no\n" + "".join(line for line in LUXWM_SYSTEM.read_text().splitlines(True)
                                                    if not line.startswith("xwayland")))
        return conf

    def ask(self, command):
        return self.app.ask(command)

    def ipc(self, message):
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(5)
        s.connect(str(self.sock))
        s.sendall((json.dumps(dict(message, id=1)) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            buf += s.recv(65536)
        s.close()
        return json.loads(buf.split(b"\n")[0])

    def workspaces(self):
        return self.ipc({"cmd": "get_state"})["state"]["workspace"]["count"]

    def compositor_log(self):
        return (self.wlt_session / "compositor.log").read_text()

    def ui_dump(self):
        out = self.tmp / "ui-test.out"
        wait_for(out.exists, 15)
        return out.read_text().splitlines()

    def close(self):
        self.app.stop()
        if self.xvfb:
            self.xvfb.stop()
        if self.wlt_session:
            subprocess.run([str(h.WLT), "stop", str(self.wlt_session)], capture_output=True)


def row_value(dump, kind, title):
    for i, line in enumerate(dump):
        if line == "GtkLabel\t" + title:
            for nxt in dump[i + 1:i + 6]:
                if nxt.startswith(kind + "\t"):
                    return nxt.split("\t")[1]
    return None


class Base(unittest.TestCase):
    wayland = False

    def setUp(self):
        if self.wayland and not h.HAVE_WAYLAND:
            self.skipTest("luxwm (LUXWM_BUILD) or wl-test sysroot missing")
        if not self.wayland and not h.HAVE_X11:
            self.skipTest("Xvfb missing")
        self.tmp = Path(tempfile.mkdtemp(prefix="look-", dir=h.private_dir()))
        self.env = make_env(self.tmp)

    def xfconf(self, values=None):
        p = self.tmp / "xfconf.json"
        if values is not None:
            p.write_text(json.dumps(values))
        return json.loads(p.read_text()) if p.exists() else {}

    def open(self, page, ui_test=None):
        s = Session(self.tmp, self.env, page, self.wayland, ui_test)
        self.addCleanup(s.close)
        return s


class X11(Base):
    def test_appearance_shows_current(self):
        self.xfconf({"xsettings": {"/Net/IconThemeName": ["string", "Plain"], "/Gtk/CursorThemeName": ["string", "Pointy"],
                                   "/Gtk/CursorThemeSize": ["int", "48"], "/Xft/DPI": ["int", "120"],
                                   "/Xft/Antialias": ["int", "1"], "/Xft/RGBA": ["string", "none"],
                                   "/Xft/Hinting": ["int", "1"], "/Xft/HintStyle": ["string", "hintfull"]}})
        d = self.open("appearance", ["dump"]).ui_dump()
        self.assertEqual(row_value(d, "GtkComboBoxText", "Icons"), "Plain")
        self.assertEqual(row_value(d, "GtkComboBoxText", "Pointer"), "Pointy")
        self.assertEqual(row_value(d, "GtkComboBoxText", "Pointer size"), "48")
        self.assertEqual(row_value(d, "GtkComboBoxText", "Text size"), "3")
        self.assertEqual(row_value(d, "GtkComboBoxText", "Font smoothing"), "grayscale")
        self.assertEqual(row_value(d, "GtkComboBoxText", "Hinting"), "full")
        for mode in ("Light [current]", "Dark", "Auto"):
            self.assertIn("GtkButton\t" + mode, d)

    def test_appearance_defaults_and_theme_list(self):
        d = self.open("appearance", ["dump"]).ui_dump()
        # WhiteSur = volba "LuxOS" (svetle/tmave ikony), hicolor neni tema
        self.assertEqual(row_value(d, "GtkComboBoxText", "Icons"), "luxos")
        self.assertEqual(row_value(d, "GtkComboBoxText", "Pointer"), "WhiteSur-cursors")
        self.assertEqual(row_value(d, "GtkComboBoxText", "Pointer size"), "24")
        self.assertEqual(row_value(d, "GtkComboBoxText", "Text size"), "1")
        self.assertEqual(row_value(d, "GtkComboBoxText", "Font smoothing"), "rgba")

    def test_appearance_changes(self):
        self.xfconf({"xsettings": {"/Net/IconThemeName": ["string", "WhiteSur-light"], "/Xft/RGBA": ["string", "bgr"]}})
        # karty rezimu jsou tlacitka s nahledem: klik pres LUXOS_UI_TEST (hleda i popisek uvnitr tlacitka)
        s = self.open("appearance", ["click Dark"])
        for cmd in ("combo Icons = Plain", "combo Pointer = Pointy", "combo Pointer size = 48",
                    "combo Font smoothing = grayscale", "combo Hinting = full", "combo Text size = 3",
                    "font interface Cantarell 12", "font monospace DejaVu Sans Mono 11"):
            s.ask(cmd)
        xs = self.xfconf()["xsettings"]
        self.assertEqual(xs["/Net/IconThemeName"], ["string", "Plain"])
        self.assertEqual(xs["/Gtk/CursorThemeName"], ["string", "Pointy"])
        self.assertEqual(xs["/Gtk/CursorThemeSize"], ["int", "48"])
        self.assertEqual(xs["/Xft/Antialias"], ["int", "1"])
        self.assertEqual(xs["/Xft/RGBA"], ["string", "none"])
        self.assertEqual(xs["/Xft/Hinting"], ["int", "1"])
        self.assertEqual(xs["/Xft/HintStyle"], ["string", "hintfull"])
        self.assertEqual(xs["/Xft/DPI"], ["int", "120"])
        self.assertEqual(xs["/Gtk/FontName"], ["string", "Cantarell 12"])
        self.assertEqual(xs["/Gtk/MonospaceFontName"], ["string", "DejaVu Sans Mono 11"])
        self.assertTrue(wait_for(lambda: "luxos-appearance dark" in fake_log(self.tmp)))
        gs = gsettings(self.tmp)
        self.assertEqual(gs.get("icon-theme"), "'Plain'")
        self.assertEqual(gs.get("cursor-theme"), "'Pointy'")
        self.assertEqual(gs.get("cursor-size"), "48")
        self.assertEqual(gs.get("font-antialiasing"), "'grayscale'")
        self.assertEqual(gs.get("font-name"), "'Cantarell 12'")
        # X11: meritko textu jen pres Xft/DPI (jako Displeje), GSettings by GTK pocitalo dvakrat
        self.assertNotIn("text-scaling-factor", gs)
        # subpixel zpet: puvodni poradi bgr zustane; vychozi velikost textu vlastnost smaze (jako Displeje)
        s.ask("combo Font smoothing = rgba")
        s.ask("combo Text size = 1")
        s.ask("combo Icons = luxos")
        s.ask("combo Font smoothing = none")
        xs = self.xfconf()["xsettings"]
        self.assertNotIn("/Xft/DPI", xs)
        self.assertEqual(xs["/Xft/Antialias"], ["int", "0"])
        self.assertIn("xfconf-query -c xsettings -p /Xft/RGBA -n -t string -s bgr", fake_log(self.tmp))
        self.assertEqual(xs["/Net/IconThemeName"], ["string", "WhiteSur-light"])

    def test_accessibility(self):
        s = self.open("accessibility")
        for cmd in ("switch Reduce motion = on", "switch Sticky Keys = on", "switch Bounce Keys = on",
                    "switch Mouse Keys = on", "combo Pointer size = 64", "combo Text size = 4"):
            s.ask(cmd)
        db = self.xfconf()
        self.assertEqual(db["xsettings"]["/Gtk/EnableAnimations"], ["bool", "false"])
        self.assertEqual(db["xsettings"]["/Gtk/CursorThemeSize"], ["int", "64"])
        self.assertEqual(db["xsettings"]["/Xft/DPI"], ["int", "132"])
        self.assertEqual(db["accessibility"], {"/StickyKeys": ["bool", "true"], "/BounceKeys": ["bool", "true"],
                                               "/MouseKeys": ["bool", "true"]})
        self.assertEqual(gsettings(self.tmp).get("enable-animations"), "false")
        # pristi prihlaseni do Waylandu: posun ploch luxwm vypnuty
        self.assertEqual(luxwm_conf(self.tmp).get("reduce_motion"), "yes")
        s.ask("switch Reduce motion = off")
        s.ask("switch Sticky Keys = off")
        db = self.xfconf()
        self.assertEqual(db["xsettings"]["/Gtk/EnableAnimations"], ["bool", "true"])
        self.assertEqual(db["accessibility"]["/StickyKeys"], ["bool", "false"])
        self.assertNotIn("reduce_motion", luxwm_conf(self.tmp))
        s.ask("click Show")
        self.assertTrue(wait_for(lambda: "onboard" in fake_log(self.tmp)))

    def test_windows(self):
        self.xfconf({"xfwm4": {"/general/workspace_count": ["int", "2"]}})
        s = self.open("windows")
        for cmd in ("combo Number of workspaces = 5", "switch Go from the last workspace to the first = off",
                    "switch Animate switching workspaces = off", "combo Double-click a title bar to = shade",
                    "switch Snap windows to other windows = on", "switch Tile windows dragged to a screen edge = off",
                    "switch Focus follows the pointer = on"):
            s.ask(cmd)
        wm = self.xfconf()["xfwm4"]
        self.assertEqual(wm["/general/workspace_count"], ["int", "5"])
        self.assertEqual(wm["/general/wrap_cycle"], ["bool", "false"])
        self.assertEqual(wm["/general/workspace_slide"], ["bool", "false"])
        self.assertEqual(wm["/general/double_click_action"], ["string", "shade"])
        self.assertEqual(wm["/general/snap_to_windows"], ["bool", "true"])
        self.assertEqual(wm["/general/tile_on_move"], ["bool", "false"])
        self.assertEqual(wm["/general/click_to_focus"], ["bool", "false"])
        self.assertFalse((self.tmp / "config/luxwm/luxwm.conf").exists())

    def test_windows_animation_follows_reduce_motion(self):
        self.xfconf({"xsettings": {"/Gtk/EnableAnimations": ["bool", "false"]}})
        d = self.open("windows", ["dump"]).ui_dump()
        self.assertIn("GtkLabel\tOff while Reduce motion is on in Accessibility.", d)
        self.assertIn("GtkSwitch\ton\t(insensitive)", d)
        self.assertEqual(row_value(d, "GtkComboBoxText", "Number of workspaces"), "2")


class Wayland(Base):
    wayland = True

    def test_appearance(self):
        s = self.open("appearance")
        for cmd in ("combo Icons = Plain", "combo Pointer = Pointy", "combo Pointer size = 48",
                    "combo Font smoothing = grayscale", "combo Hinting = medium", "combo Text size = 2",
                    "font interface Cantarell 12"):
            s.ask(cmd)
        xs = channel_file(self.tmp, "xsettings")
        self.assertEqual(xs["/Net/IconThemeName"], ("string", "Plain"))
        self.assertEqual(xs["/Gtk/CursorThemeName"], ("string", "Pointy"))
        self.assertEqual(xs["/Gtk/CursorThemeSize"], ("int", "48"))
        self.assertEqual(xs["/Xft/RGBA"], ("string", "none"))
        self.assertEqual(xs["/Xft/HintStyle"], ("string", "hintmedium"))
        self.assertEqual(xs["/Xft/DPI"], ("int", "108"))
        self.assertEqual(xs["/Gtk/FontName"], ("string", "Cantarell 12"))
        gs = gsettings(self.tmp)
        self.assertEqual(gs.get("icon-theme"), "'Plain'")
        self.assertEqual(gs.get("cursor-theme"), "'Pointy'")
        self.assertEqual(gs.get("cursor-size"), "48")
        self.assertEqual(gs.get("font-hinting"), "'medium'")
        self.assertEqual(float(gs.get("text-scaling-factor", "0")), 1.125)
        self.assertEqual(gs.get("font-name"), "'Cantarell 12'")
        # luxwm prevzal kurzor hned (set_cursor), xfconf-query se na Waylandu nevola
        self.assertTrue(wait_for(lambda: "cursor Pointy 48" in s.compositor_log()), s.compositor_log()[-2000:])
        self.assertFalse([c for c in fake_log(self.tmp) if c.startswith("xfconf-query")])

    def test_appearance_reads_channel_file(self):
        f = self.tmp / "config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml"
        f.parent.mkdir(parents=True)
        f.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<channel name="xsettings" version="1.0">\n'
                     '  <property name="Gtk" type="empty">\n'
                     '    <property name="CursorThemeSize" type="int" value="32"/>\n  </property>\n'
                     '  <property name="Xft" type="empty">\n    <property name="DPI" type="int" value="84"/>\n'
                     '    <property name="Antialias" type="int" value="0"/>\n  </property>\n</channel>\n')
        d = self.open("appearance", ["dump"]).ui_dump()
        self.assertEqual(row_value(d, "GtkComboBoxText", "Pointer size"), "32")
        self.assertEqual(row_value(d, "GtkComboBoxText", "Text size"), "0")
        self.assertEqual(row_value(d, "GtkComboBoxText", "Font smoothing"), "none")

    def test_accessibility(self):
        s = self.open("accessibility")
        s.ask("switch Reduce motion = on")
        self.assertEqual(channel_file(self.tmp, "xsettings")["/Gtk/EnableAnimations"], ("bool", "false"))
        self.assertEqual(gsettings(self.tmp).get("enable-animations"), "false")
        self.assertEqual(luxwm_conf(self.tmp).get("reduce_motion"), "yes")
        self.assertTrue(wait_for(lambda: "configuration reloaded" in s.compositor_log()))
        s.ask("combo Pointer size = 32")
        self.assertTrue(wait_for(lambda: "cursor WhiteSur-cursors 32" in s.compositor_log()), s.compositor_log()[-2000:])
        s.ask("switch Reduce motion = off")
        self.assertNotIn("reduce_motion", luxwm_conf(self.tmp))
        self.assertEqual(gsettings(self.tmp).get("enable-animations"), "true")
        # klavesy pro zpristupneni luxcomp zatim neumi: na Waylandu nejsou
        d = s.app.dump()
        self.assertIsNone(lsl_app.find(d, text="Sticky Keys"))
        self.assertIsNone(lsl_app.find(d, text="Mouse Keys"))

    def test_windows(self):
        s = self.open("windows")
        self.assertEqual(s.workspaces(), 4)
        s.ask("combo Number of workspaces = 6")
        self.assertTrue(wait_for(lambda: s.workspaces() == 6))
        s.ipc({"cmd": "switch_workspace", "number": 6})
        s.ask("combo Number of workspaces = 2")
        self.assertTrue(wait_for(lambda: s.workspaces() == 2))
        state = s.ipc({"cmd": "get_state"})["state"]["workspace"]
        self.assertEqual(state["current"], 2)
        s.ask("combo Number of workspaces = 3")
        self.assertTrue(wait_for(lambda: s.workspaces() == 3))
        for cmd in ("switch Go from the last workspace to the first = on", "switch Animate switching workspaces = off",
                    "combo Double-click a title bar to = hide"):
            s.ask(cmd)
        conf = luxwm_conf(self.tmp)
        self.assertEqual(conf.get("workspaces"), "3")
        self.assertEqual(conf.get("wrap_workspaces"), "yes")
        self.assertEqual(conf.get("slide_ms"), "0")
        self.assertEqual(conf.get("double_click_action"), "hide")
        # prechod za posledni plochu luxwm opravdu pouziva
        s.ipc({"cmd": "switch_workspace", "number": 3})
        s.ipc({"cmd": "switch_workspace", "delta": 1})
        self.assertTrue(wait_for(lambda: s.ipc({"cmd": "get_state"})["state"]["workspace"]["current"] == 1))
        s.ask("switch Animate switching workspaces = on")
        self.assertNotIn("slide_ms", luxwm_conf(self.tmp))
        self.assertFalse(self.xfconf())
        d = s.app.dump()
        self.assertIsNone(lsl_app.find(d, text="Focus follows the pointer"))


FILES = Path(__file__).resolve().parents[1] / "files"
GSETTINGS = r"""#!/bin/sh
# falesny gsettings: hodnoty v $FAKE_GS (radky "schema klic hodnota")
printf '%s\n' "gsettings $*" >>"$FAKE_LOG"
case $1 in
  get) v=$(grep "^$2 $3 " "$FAKE_GS" 2>/dev/null | tail -n1 | cut -d' ' -f3-); [ -n "$v" ] && echo "$v" || exit 1 ;;
  set) printf '%s %s %s\n' "$2" "$3" "$4" >>"$FAKE_GS" ;;
esac
"""


class Scripts(unittest.TestCase):
    """luxos-appearance necha vlastni sadu ikon, luxos-wayland-settings prenese Omezit pohyb do GSettings."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="look-scripts-", dir=h.private_dir()))
        self.env = make_env(self.tmp)
        h.fake_bin(self.tmp / "bin", ["gsettings", "busctl", "xrandr", "luxwm-msg"], {"gsettings": GSETTINGS})
        self.env.update(FAKE_GS=str(self.tmp / "gs"), USER="test", LUXOS_SUN="/bin/false")
        self.env.pop("WAYLAND_DISPLAY", None)

    def gs(self, schema, key):
        lines = [line.split(" ", 2) for line in (self.tmp / "gs").read_text().splitlines()] if (self.tmp / "gs").exists() else []
        values = [v for sch, k, v in lines if sch == schema and k == key]
        return values[-1] if values else None

    def appearance(self, *args, wayland=False):
        env = dict(self.env, WAYLAND_DISPLAY="wayland-9") if wayland else self.env
        subprocess.run(["bash", str(FILES / "bin/luxos-appearance"), *args], env=env, capture_output=True, timeout=60)

    def test_x11_custom_icons_stay(self):
        db = {"xsettings": {"/Net/IconThemeName": ["string", "Plain"]}}
        (self.tmp / "xfconf.json").write_text(json.dumps(db))
        self.appearance("dark")
        xs = json.loads((self.tmp / "xfconf.json").read_text())["xsettings"]
        self.assertEqual(xs["/Net/IconThemeName"], ["string", "Plain"])
        self.assertEqual(xs["/Net/ThemeName"], ["string", "WhiteSur-Dark"])
        self.assertEqual(self.gs("org.gnome.desktop.interface", "icon-theme"), "Plain")

    def test_x11_whitesur_follows_mode(self):
        (self.tmp / "xfconf.json").write_text(json.dumps({"xsettings": {"/Net/IconThemeName": ["string", "WhiteSur-light"]}}))
        self.appearance("dark")
        xs = json.loads((self.tmp / "xfconf.json").read_text())["xsettings"]
        self.assertEqual(xs["/Net/IconThemeName"], ["string", "WhiteSur-dark"])

    def test_wayland_custom_icons_stay(self):
        (self.tmp / "gs").write_text("org.gnome.desktop.interface icon-theme 'Plain'\n")
        self.appearance("dark", wayland=True)
        self.assertEqual(self.gs("org.gnome.desktop.interface", "icon-theme"), "Plain")
        self.assertEqual(self.gs("org.gnome.desktop.interface", "color-scheme"), "prefer-dark")
        (self.tmp / "gs").write_text("org.gnome.desktop.interface icon-theme 'WhiteSur-dark'\n")
        self.appearance("light", wayland=True)
        self.assertEqual(self.gs("org.gnome.desktop.interface", "icon-theme"), "WhiteSur-light")

    def test_wayland_settings_animations(self):
        for value, want in (("false", "false"), ("true", "true")):
            (self.tmp / "gs").write_text("")
            (self.tmp / "xfconf.json").write_text(json.dumps({"xsettings": {"/Gtk/EnableAnimations": ["bool", value]}}))
            subprocess.run(["bash", str(FILES / "session/luxos-wayland-settings")], env=self.env, capture_output=True, timeout=60)
            self.assertEqual(self.gs("org.gnome.desktop.interface", "enable-animations"), want)
        (self.tmp / "gs").write_text("")
        (self.tmp / "xfconf.json").write_text("{}")
        subprocess.run(["bash", str(FILES / "session/luxos-wayland-settings")], env=self.env, capture_output=True, timeout=60)
        self.assertIsNone(self.gs("org.gnome.desktop.interface", "enable-animations"))


if __name__ == "__main__":
    unittest.main()
