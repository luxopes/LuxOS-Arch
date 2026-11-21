#!/usr/bin/env python3
"""LuxOS - Nastaveni > Oznameni, Vychozi aplikace, Otevrit po prihlaseni a Vymenitelne disky (luxos_page_notifications,
luxos_page_default_apps, luxos_page_login_items, luxos_page_drives) pres skutecne okno (testctl) a jejich ucinek:
X11 ve vlastnim Xvfb s falesnym xfconf-query, Wayland pod luxwm headless se skutecnym luxos-notify (Nerusit, delka
bubliny, ztlumene aplikace, historie), mimeapps.list/helpers.rc i `xdg-mime query default`, prepis autostartu a vyber
luxos-wayland-session, automaticke pripojeni (luxos_automount.lsl) proti falesnemu UDisks2 na soukrome sbernici.

    scripts/wl-test/run-all packages/luxos-desktop/tests/test_settings_system.py
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lsl_app  # noqa: E402

try:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
except (ImportError, ValueError):
    gi = None

REPO = HERE.parent.parent.parent
FILES = HERE.parent / "files"
WLT = REPO / "scripts/wl-test/wlt"
OUT = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or OUT / "sysroot")
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")
LSL_DIR = Path(lsl_app.LSL_DIR)

# falesny xfconf-query nad JSON ($FAKE_XFCONF, klic "kanal prop"): -s, pole -a s vice -s, -r, cteni jako xfconf-query
XFCONF = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write("xfconf-query " + " ".join(a) + "\\n")
path = os.environ["FAKE_XFCONF"]
data = json.load(open(path)) if os.path.exists(path) else {}
key = a[a.index("-c") + 1] + " " + a[a.index("-p") + 1]
values = [a[i + 1] for i, x in enumerate(a) if x == "-s"]
if "-r" in a:
    data.pop(key, None)
elif values:
    data[key] = values if "-a" in a else values[0]
elif key in data:
    v = data[key]
    print("Value is an array with %d items:\\n\\n%s" % (len(v), "\\n".join(v)) if isinstance(v, list) else v)
    sys.exit(0)
else:
    sys.exit(1)
json.dump(data, open(path, "w"))
"""
FAKE = "#!/bin/sh\necho \"$(basename \"$0\") $*\" >> \"$FAKE_LOG\"\n"

FDO = ("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications")
HISTORY = ("org.freedesktop.Notifications", "/cz/luxos/NotificationHistory", "cz.luxos.NotificationHistory")
LOG = ("org.xfce.Notifyd", "/org/xfce/Notifyd", "org.xfce.Notifyd.Log")

# falesne aplikace: id -> (MimeType, navic klice)
APPS = {
    "firefox": ("x-scheme-handler/http;x-scheme-handler/https;text/html;application/pdf;", ""),
    "org.chromium.Chromium": ("x-scheme-handler/http;x-scheme-handler/https;text/html;", ""),
    "sneaky": ("x-scheme-handler/http;x-scheme-handler/https;", "NoDisplay=true\n"),
    "gone": ("x-scheme-handler/http;", "Hidden=true\n"),
    "thunar": ("inode/directory;", ""),
    "pcmanfm": ("inode/directory;", ""),
    "org.xfce.ristretto": ("image/png;image/jpeg;image/gif;", ""),
    "org.gnome.eog": ("image/png;image/jpeg;", ""),
    "luxos-text": ("text/plain;", ""),
    "org.gnome.Evince": ("application/pdf;application/x-cbz;", ""),
    "mpv": ("video/mp4;video/webm;audio/mpeg;audio/flac;", ""),
    "org.gnome.Totem": ("video/mp4;video/webm;audio/mpeg;", ""),
    "org.mozilla.Thunderbird": ("x-scheme-handler/mailto;message/rfc822;", ""),
    "luxos-mail-reader": ("x-scheme-handler/mailto;", ""),
    "org.gnome.Evolution": ("x-scheme-handler/mailto;", ""),
    "notes": ("text/markdown;", ""),
    "fakefm": ("inode/directory;", ""),
}
# pomocne aplikace exo: jmeno -> (kategorie, program)
HELPERS = {"firefox": ("WebBrowser", "firefox"), "chromium": ("WebBrowser", "chromium"),
           "thunar": ("FileManager", "thunar"), "pcmanfm": ("FileManager", "pcmanfm"),
           "luxos-terminal": ("TerminalEmulator", "luxos-terminal"), "xterm": ("TerminalEmulator", "xterm"),
           "kitty": ("TerminalEmulator", "kitty-not-installed")}
# systemove polozky autostartu: soubor -> obsah
AUTOSTART = {
    "app-a.desktop": "[Desktop Entry]\nType=Application\nName=Sync Tool\nName[cs]=Synchronizace\nExec=synctool --tray\n"
                     "Icon=sync\n\n[Desktop Action Quit]\nName=Quit\nExec=synctool --quit\n",
    "x11-applet.desktop": "[Desktop Entry]\nType=Application\nName=Xfce Applet\nExec=xfapplet\nOnlyShowIn=XFCE;\n",
    "wl-only.desktop": "[Desktop Entry]\nType=Application\nName=LuxOS Only\nExec=wlonly\nOnlyShowIn=LuxOS;\n",
    "plumbing.desktop": "[Desktop Entry]\nType=Application\nName=Keyring\nExec=keyring\nNoDisplay=true\n",
    "luxos-guard-agent.desktop": "[Desktop Entry]\nType=Application\nName=Lux Guard\nExec=guard\n",
    "xfsettingsd.desktop": "[Desktop Entry]\nType=Application\nName=Xfce Settings Daemon\nExec=xfsettingsd\nOnlyShowIn=XFCE;\n",
    "missing.desktop": "[Desktop Entry]\nType=Application\nName=Missing\nExec=missing\nTryExec=no-such-program\n",
    "print-applet.desktop": "[Desktop Entry]\nType=Application\nName=Print Queue Applet\nExec=printapplet\nHidden=true\n",
}


def labels(windows):
    return lsl_app.texts(windows)


def switch_after(windows, title):
    """Stav prepinace v radku s titulkem (prvni GtkSwitch za popiskem)."""
    items = lsl_app.widgets(windows)
    for i, w in enumerate(items):
        if w["t"] == "GtkLabel" and w.get("text") == title and w["vis"]:
            for nxt in items[i + 1:i + 12]:
                if nxt["t"] == "GtkSwitch":
                    return nxt["active"]
    return None


def widget_after(windows, title, kind):
    items = lsl_app.widgets(windows)
    for i, w in enumerate(items):
        if w["t"] == "GtkLabel" and w.get("text") == title and w["vis"]:
            for nxt in items[i + 1:i + 12]:
                if nxt["t"] == kind:
                    return nxt
    return None


def kv(path):
    out = {}
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                out[k] = v
    return out


def xfconf_file(path):
    """Kanal xfconf ze souboru jako {cesta: hodnota} (vnorene <property>)."""
    import xml.etree.ElementTree as ET
    out = {}

    def walk(node, prefix):
        for p in node.findall("property"):
            name = prefix + "/" + p.get("name")
            if p.get("value") is not None:
                out[name] = p.get("value")
            walk(p, name)
    if Path(path).exists():
        walk(ET.parse(path).getroot(), "")
    return out


class Base(unittest.TestCase):
    wayland = False

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="settings-system-"))
        cls.binary = lsl_app.build("luxos-settings", str(cls.tmp))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.apps = []
        self.home = Path(tempfile.mkdtemp(prefix="home-", dir=self.tmp))
        self.cfg = self.home / "config"
        self.sys = self.home / "sys"
        self.data = self.home / "share"
        self.bin = self.home / "bin"
        for d in (self.cfg, self.sys / "autostart", self.sys / "xfce4", self.data / "applications",
                  self.data / "xfce4/helpers", self.bin):
            d.mkdir(parents=True, exist_ok=True)
        self.fake_programs()
        self.bus = lsl_app.Bus()
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.cfg),
                        XDG_CACHE_HOME=str(self.home / "cache"), XDG_DATA_HOME=str(self.home / "data"),
                        XDG_CONFIG_DIRS=str(self.sys), XDG_DATA_DIRS=f"{self.data}:/usr/share",
                        PATH=str(self.bin) + ":/usr/bin:/bin", FAKE_LOG=str(self.home / "fake.log"),
                        FAKE_XFCONF=str(self.home / "xfconf.json"), DBUS_SESSION_BUS_ADDRESS=self.bus.address,
                        DBUS_SYSTEM_BUS_ADDRESS="unix:path=/nonexistent", GTK_A11Y="none", GTK_THEME="Adwaita",
                        LANG="C.UTF-8", LC_ALL="C.UTF-8", GIO_USE_VFS="local", GSETTINGS_BACKEND="memory",
                        XDG_CURRENT_DESKTOP="LuxOS" if self.wayland else "XFCE")
        self.env.pop("LUXOS_UI_TEST", None)

    def tearDown(self):
        for app in self.apps:
            app.stop()
        self.bus.stop()

    def fake_programs(self):
        for name in ("synctool", "xfapplet", "wlonly", "keyring", "guard", "printapplet", "xfsettingsd", "firefox", "chromium",
                     "sneaky", "gone", "thunar", "pcmanfm", "ristretto", "eog", "luxos-text", "evince", "mpv",
                     "thunderbird", "luxos-mail-reader", "notes", "totem", "evolution", "luxos-terminal", "xterm"):
            (self.bin / name).write_text(FAKE)
            (self.bin / name).chmod(0o755)
        (self.bin / "xfconf-query").write_text(XFCONF)
        (self.bin / "xfconf-query").chmod(0o755)
        (self.bin / "fakefm").write_text("#!/bin/sh\necho \"fakefm $*\" >> \"$FAKE_LOG\"\n")
        (self.bin / "fakefm").chmod(0o755)
        exe = {"org.chromium.Chromium": "chromium", "org.xfce.ristretto": "ristretto", "org.gnome.eog": "eog",
               "org.gnome.Evince": "evince", "org.mozilla.Thunderbird": "thunderbird",
               "org.gnome.Totem": "totem", "org.gnome.Evolution": "evolution"}
        cache = {}
        for app, (types, extra) in APPS.items():
            prog = exe.get(app, app)
            (self.data / "applications" / f"{app}.desktop").write_text(
                f"[Desktop Entry]\nType=Application\nName={app.rsplit('.', 1)[-1].capitalize()}\nExec={prog} %U\n"
                f"MimeType={types}\n{extra}")
            for t in types.strip(";").split(";"):
                cache.setdefault(t, []).append(app + ".desktop")
        (self.data / "applications/mimeinfo.cache").write_text(
            "[MIME Cache]\n" + "".join(f"{t}={';'.join(a)};\n" for t, a in cache.items()))
        for name, (cat, prog) in HELPERS.items():
            (self.data / "xfce4/helpers" / f"{name}.desktop").write_text(
                f"[Desktop Entry]\nType=X-XFCE-Helper\nName={name.capitalize()}\nX-XFCE-Category={cat}\n"
                f"X-XFCE-Binaries={prog};\nX-XFCE-Commands=%B;\n")
        (self.sys / "xfce4/helpers.rc").write_text("WebBrowser=firefox\nMailReader=luxos-mail-reader\n"
                                                   "TerminalEmulator=luxos-terminal\nFileManager=thunar\n")
        (self.sys / "mimeapps.list").write_text("[Default Applications]\nx-scheme-handler/http=firefox.desktop\n"
                                                "inode/directory=thunar.desktop\n")
        for name, text in AUTOSTART.items():
            (self.sys / "autostart" / name).write_text(text)

    def open(self, page):
        app = lsl_app.App([str(self.binary), page], self.env)
        self.apps.append(app)
        self.assertTrue(app.wait(lambda: app.dump(), 15), app.stderr())
        self.assertEqual(json.loads(app.ask("state", "state"))["page"], page)
        return app

    def xfconf(self, values=None):
        p = self.home / "xfconf.json"
        if values is not None:
            p.write_text(json.dumps(values))
        return json.loads(p.read_text()) if p.exists() else {}

    def notify_conf(self):
        return kv(self.cfg / "luxos/notifications.conf")

    def wait(self, cond, timeout=5, message=""):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return
            time.sleep(0.05)
        self.fail(message or "condition not met")


class Common:
    """Testy pro obe relace (stejny ucinek)."""

    # ---- Vychozi aplikace (stejne v obou relacich: mimeapps.list a helpers.rc) ----

    def test_default_apps(self):
        (self.cfg / "xfce4").mkdir(parents=True)
        (self.cfg / "xfce4/helpers.rc").write_text("# vlastni\nMailReader=luxos-mail-reader\n")
        app = self.open("default-apps")
        # XDG_DATA_DIRS konci /usr/share (ikony, typy MIME): nabidka muze mit i aplikace systemu
        offered = json.loads(app.ask("options", "options"))
        mine = {k: [i for i in v if i.removesuffix(".desktop") in APPS or i in HELPERS] for k, v in offered.items()}
        self.assertEqual(mine["browser"], ["org.chromium.Chromium.desktop", "firefox.desktop"])   # podle nazvu
        self.assertEqual(sorted(mine["files"]), ["fakefm.desktop", "pcmanfm.desktop", "thunar.desktop"])
        self.assertEqual(mine["mail"], ["org.gnome.Evolution.desktop", "org.mozilla.Thunderbird.desktop"])     # luxos-mail-reader jen predava
        self.assertNotIn("luxos-mail-reader.desktop", offered["mail"])
        self.assertEqual(mine["terminal"], ["luxos-terminal", "xterm"])          # kitty neni nainstalovany
        self.assertNotIn("kitty", offered["terminal"])
        self.assertEqual(sorted(mine["images"]), ["org.gnome.eog.desktop", "org.xfce.ristretto.desktop"])
        self.assertIn("org.gnome.Evince.desktop", offered["pdf"])
        self.assertIn("luxos-text.desktop", offered["text"])
        for hidden in ("sneaky.desktop", "gone.desktop"):                         # NoDisplay, Hidden
            self.assertNotIn(hidden, offered["browser"])

        app.ask("combo Web browser = org.chromium.Chromium.desktop")
        app.ask("combo File manager = pcmanfm.desktop")
        app.ask("combo Image viewer = org.gnome.eog.desktop")
        app.ask("combo Mail = org.gnome.Evolution.desktop")
        app.ask("combo Terminal = xterm")
        app.ask("combo Videos = org.gnome.Totem.desktop")
        app.ask("combo Music = org.gnome.Totem.desktop")
        mime = self.cfg / "mimeapps.list"
        self.wait(lambda: mime.exists() and "audio/mpeg=org.gnome.Totem.desktop" in mime.read_text(), 5, "mimeapps.list")
        text = mime.read_text()
        defaults = text.split("[Default Applications]", 1)[1].split("\n[", 1)[0]
        for t in ("x-scheme-handler/http", "x-scheme-handler/https", "text/html"):
            self.assertIn(f"{t}=org.chromium.Chromium.desktop", defaults)
        self.assertNotIn("application/xhtml+xml", defaults)        # Chromium ho neuvadi
        self.assertIn("inode/directory=pcmanfm.desktop", defaults)
        self.assertIn("image/png=org.gnome.eog.desktop", defaults)
        self.assertIn("image/jpeg=org.gnome.eog.desktop", defaults)
        self.assertNotIn("image/gif", defaults)
        self.assertIn("x-scheme-handler/mailto=org.gnome.Evolution.desktop", defaults)
        helpers = kv(self.cfg / "xfce4/helpers.rc")
        self.assertEqual(helpers, {"MailReader": "luxos-mail-reader", "WebBrowser": "chromium",
                                   "FileManager": "pcmanfm", "TerminalEmulator": "xterm"})
        self.assertIn("# vlastni", (self.cfg / "xfce4/helpers.rc").read_text())
        # ostatni programy vidi totez (xdg-utils i GIO)
        env = {k: v for k, v in self.env.items() if k != "DISPLAY"}
        if shutil.which("xdg-mime"):
            for t, want in (("x-scheme-handler/https", "org.chromium.Chromium.desktop"),
                            ("inode/directory", "pcmanfm.desktop"), ("image/jpeg", "org.gnome.eog.desktop")):
                r = subprocess.run(["xdg-mime", "query", "default", t], env=dict(env, XDG_CURRENT_DESKTOP="X-Generic"),
                                   capture_output=True, text=True, timeout=20)
                self.assertEqual(r.stdout.strip(), want, t)
        if gi:
            code = ("import sys, gi; gi.require_version('Gio', '2.0'); from gi.repository import Gio\n"
                    "for t in sys.argv[1:]:\n    a = Gio.AppInfo.get_default_for_type(t, False)\n"
                    "    print(a.get_id() if a else None)\n")
            r = subprocess.run([sys.executable, "-c", code, "x-scheme-handler/http", "video/mp4", "video/webm",
                                "audio/mpeg"], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.stdout.split(), ["org.chromium.Chromium.desktop"] + ["org.gnome.Totem.desktop"] * 3)
            self.assertNotIn("audio/flac", defaults)                   # Totem ho neuvadi
        # nove otevrena stranka ukazuje ulozenou volbu
        app.stop()
        app = self.open("default-apps")
        app.ask("combo Terminal = luxos-terminal")
        self.wait(lambda: kv(self.cfg / "xfce4/helpers.rc").get("TerminalEmulator") == "luxos-terminal")

    # ---- Otevrit po prihlaseni ----

    def autostart_run(self):
        """Vyber polozek jako luxos-wayland-session (funkce autostart z bin/luxos-wayland-session)."""
        script = (FILES / "bin/luxos-wayland-session").read_text()
        func = re.search(r"^autostart\(\) \{.*?^\}", script, re.S | re.M).group(0)
        log = self.home / "systemd-run.log"
        fake = self.home / "sr"
        fake.mkdir(exist_ok=True)
        (fake / "systemd-run").write_text("#!/bin/sh\nfor a; do case $a in --unit=*) echo \"${a#--unit=}\";; esac; done"
                                          f" >> {log}\n")
        (fake / "systemd-run").chmod(0o755)
        log.unlink(missing_ok=True)
        env = dict(self.env, PATH=f"{fake}:{self.bin}:/usr/bin:/bin")
        subprocess.run(["bash", "-c", func + "\nautostart"], env=env, check=True, timeout=20)
        return sorted(line.removeprefix("app-luxos-autostart-") for line in log.read_text().split()) \
            if log.exists() else []

    def test_login_items(self):
        (self.cfg / "autostart").mkdir(parents=True)
        (self.cfg / "autostart/mine.desktop").write_text("[Desktop Entry]\nType=Application\nName=My Script\nExec=mine\n")
        app = self.open("login-items")
        d = app.dump()
        shown = labels(d)
        for name in ("Sync Tool", "Print Queue Applet", "My Script"):
            self.assertIn(name, shown)
        for name in ("Keyring", "Lux Guard", "Missing", "Xfce Settings Daemon"):
            self.assertNotIn(name, shown)
        self.assertEqual("LuxOS Only" in shown, self.wayland)
        self.assertEqual("Xfce Applet" in shown, not self.wayland)
        self.assertTrue(switch_after(d, "Sync Tool"))
        self.assertFalse(switch_after(d, "Print Queue Applet"))
        self.assertEqual(sum(1 for w in lsl_app.widgets(d) if w["t"] == "GtkButton" and w.get("text") == "Remove"), 1)
        # soucasti relace se v okne neukazuji, ale spousti se dal
        self.assertEqual(self.autostart_run(), ["app-a", "luxos-guard-agent", "mine", "plumbing", "wl-only"])

        app.ask("switch Sync Tool = off")
        app.ask("switch Print Queue Applet = on")
        override = self.cfg / "autostart/app-a.desktop"
        self.wait(lambda: override.exists() and (self.cfg / "autostart/print-applet.desktop").exists())
        text = override.read_text()
        self.assertIn("Hidden=true\n", text)
        self.assertIn("X-GNOME-Autostart-enabled=false\n", text)
        self.assertIn("Exec=synctool --tray\n", text)
        self.assertIn("Name[cs]=Synchronizace\n", text)
        # klice patri do [Desktop Entry], ne do skupiny akce
        self.assertLess(text.index("Hidden=true"), text.index("[Desktop Action Quit]"))
        self.assertIn("Hidden=false\n", (self.cfg / "autostart/print-applet.desktop").read_text())
        self.assertEqual(self.autostart_run(), ["luxos-guard-agent", "mine", "plumbing", "print-applet", "wl-only"])

        app.ask("remove mine.desktop")
        self.assertFalse((self.cfg / "autostart/mine.desktop").exists())
        app.ask("combo App = notes.desktop")
        app.ask("click Add")
        added = self.cfg / "autostart/notes.desktop"
        self.wait(lambda: added.exists())
        self.assertIn("Exec=notes %U", added.read_text())
        self.assertIn("Notes", labels(app.dump()))
        self.assertEqual(self.autostart_run(), ["luxos-guard-agent", "notes", "plumbing", "print-applet", "wl-only"])
        # systemova polozka nejde odebrat, jen vypnout
        app.ask("remove app-a.desktop")
        self.assertTrue(override.exists())
        app.ask("switch Sync Tool = on")
        self.wait(lambda: "Hidden=false" in override.read_text())
        self.assertEqual(self.autostart_run(), ["app-a", "luxos-guard-agent", "notes", "plumbing", "print-applet", "wl-only"])


@unittest.skipUnless(shutil.which("Xvfb"), "Xvfb is missing")
class X11(Base, Common):
    def setUp(self):
        super().setUp()
        self.x = lsl_app.Xvfb()
        self.env.update(DISPLAY=self.x.display, GDK_BACKEND="x11")
        self.env.pop("WAYLAND_DISPLAY", None)
        self.env.pop("XAUTHORITY", None)

    def tearDown(self):
        super().tearDown()
        self.x.stop()

    def test_notifications_xfconf(self):
        self.xfconf({"xfce4-notifyd /applications/known_applications": ["Firefox", "Thunderbird"],
                     "xfce4-notifyd /applications/muted_applications": ["Thunderbird"],
                     "xfce4-notifyd /expire-timeout": "10"})
        app = self.open("notifications")
        d = app.dump()
        self.assertTrue(switch_after(d, "Firefox"))
        self.assertFalse(switch_after(d, "Thunderbird"))
        self.assertFalse(switch_after(d, "Do Not Disturb"))
        self.assertTrue(switch_after(d, "Play sounds"))
        app.ask("switch Do Not Disturb = on")
        app.ask("combo Show banners for = 15")
        app.ask("switch Play sounds = off")
        app.ask("combo Number of notifications to keep = 50")
        app.ask("switch Keep notifications in the menu bar = off")
        app.ask("switch Firefox = off")
        app.ask("switch Thunderbird = on")
        app.ask("switch Notify about summer and winter time = off")
        self.wait(lambda: self.xfconf().get("xfce4-notifyd /applications/muted_applications") == ["Firefox"])
        x = {k.split(" ", 1)[1]: v for k, v in self.xfconf().items()}
        self.assertEqual(x["/do-not-disturb"], "true")
        self.assertEqual(x["/expire-timeout"], "15")
        self.assertEqual(x["/expire-timeout-enabled"], "true")
        self.assertEqual(x["/mute-sounds"], "true")
        self.assertEqual(x["/log-max-size"], "50")
        self.assertEqual(x["/notification-log"], "false")
        self.assertEqual(self.notify_conf(), {"TIME_CHANGE": "0"})
        log = (self.home / "fake.log").read_text()
        self.assertIn("-p /log-max-size -n -t uint -s 50", log)
        self.assertIn("-p /do-not-disturb -n -t bool -s true", log)
        app.ask("switch Firefox = on")
        self.wait(lambda: "xfce4-notifyd /applications/muted_applications" not in self.xfconf())

    def test_drives_xfconf(self):
        app = self.open("drives")
        d = app.dump()
        self.assertFalse(switch_after(d, "Mount USB drives and memory cards"))
        self.assertFalse(widget_after(d, "Open a window with the drive's files", "GtkSwitch")["sens"])
        self.assertIn("Import photos when a camera is connected", labels(d))
        app.ask("switch Mount USB drives and memory cards = on")
        app.ask("switch Open a window with the drive's files = on")
        app.ask("switch Mount inserted CDs and DVDs = on")
        app.ask("switch Import photos when a camera is connected = on")
        app.ask("switch Play audio CDs when inserted = on")
        self.wait(lambda: "thunar-volman /autoplay-audio-cds/enabled" in self.xfconf())
        self.assertEqual(self.xfconf(), {f"thunar-volman /{p}/enabled": "true" for p in
                                         ("automount-drives", "autobrowse", "automount-media", "autophoto",
                                          "autoplay-audio-cds")})
        self.assertIn("-c thunar-volman -p /automount-drives/enabled -n -t bool -s true",
                      (self.home / "fake.log").read_text())
        self.assertTrue(widget_after(app.dump(), "Open a window with the drive's files", "GtkSwitch")["sens"])


@unittest.skipUnless((LUXWM_BUILD / "luxwm").exists() and WLT.exists() and gi, "luxwm (build-host.sh), harness or gi missing")
class Wayland(Base, Common):
    wayland = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.notifyd = lsl_app.build("luxos-notify", str(cls.tmp))
        out = cls.tmp / "luxos-automount-probe"
        r = subprocess.run([os.environ.get("LUXOS_LSLC") or shutil.which("lslc"), "--target", "linux-x86_64-gnu",
                            "--system-bindings", str(LSL_DIR), str(HERE / "lsl/luxos-automount-probe.lsl"), str(out)],
                           capture_output=True, text=True, timeout=900)
        if r.returncode:
            raise AssertionError("lslc: " + (r.stdout + r.stderr)[-3000:])
        cls.probe = out

    def setUp(self):
        super().setUp()
        conf = self.home / "luxwm.conf"
        conf.write_text("xwayland = no\n" + "".join(line for line in (REPO / "packages/luxwm/luxwm.conf").read_text()
                                                    .splitlines(True) if not line.startswith("xwayland")))
        env = dict(os.environ, WLT_COMPOSITOR_ENV=f"LUXWM_SYSTEM_CONFIG={conf} LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib")
        r = subprocess.run([str(WLT), "start", "--mode", "headless", "--size", "1280x800", "--timeout", "600",
                            "--name", f"ss{os.getpid() % 10000}-{self._testMethodName[5:15]}", "--", str(LUXWM_BUILD / "luxwm")],
                           env=env, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            self.fail("wlt start: " + r.stdout + r.stderr)
        self.session = Path(r.stdout.strip().splitlines()[-1])
        for line in subprocess.run([str(WLT), "env", str(self.session)], capture_output=True, text=True).stdout.splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            if key in ("WAYLAND_DISPLAY", "XDG_RUNTIME_DIR"):
                self.env[key] = value.strip("'\"")
        self.env["GDK_BACKEND"] = "wayland"
        self.env.pop("DISPLAY", None)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        super().tearDown()
        subprocess.run([str(WLT), "stop", str(self.session)], capture_output=True)
        shutil.rmtree(self.session, True)

    # ---- luxos-notify na soukrome sbernici relace ----

    def start_notify(self):
        err = open(self.home / "notify.err", "w")
        p = subprocess.Popen([str(self.notifyd)], env=self.env, stdout=subprocess.DEVNULL, stderr=err)
        self.procs.append(p)
        self.conn = Gio.DBusConnection.new_for_address_sync(
            self.bus.address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
        self.signals = []
        self.conn.signal_subscribe(None, None, None, None, None, 0,
                                   lambda c, s, path, i, name, params: self.signals.append((time.monotonic(), name, params.unpack())))
        self.pump_until(lambda: self.call(("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus"),
                                          "NameHasOwner", (FDO[0],), "(s)", "(b)")[0], 10, "luxos-notify did not start")
        return p

    def pump(self):
        ctx = GLib.MainContext.default()
        while ctx.iteration(False):
            pass

    def pump_until(self, cond, timeout, message):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.pump()
            if cond():
                return
            time.sleep(0.02)
        self.fail(message)

    def call(self, target, method, args=None, sig=None, reply=None):
        r = self.conn.call_sync(target[0], target[1], target[2], method, GLib.Variant(sig, args) if sig else None,
                                GLib.VariantType(reply) if reply else None, 0, 5000, None)
        return r.unpack() if r else None

    def notify(self, summary, app="Test", keep=False, timeout=-1):
        hints = {"x-luxos-keep": GLib.Variant("b", True)} if keep else {}
        return self.call(FDO, "Notify", (app, 0, "", summary, "", [], hints, timeout), "(susssasa{sv}i)", "(u)")[0]

    def closed(self, nid, timeout):
        self.pump_until(lambda: any(s[1] == "NotificationClosed" and s[2][0] == nid for s in self.signals), timeout,
                        f"notification {nid} not closed")
        return next(s for s in self.signals if s[1] == "NotificationClosed" and s[2][0] == nid)

    def test_notifications_with_luxos_notify(self):
        data = self.home / "data/luxos"
        data.mkdir(parents=True)
        (data / "notification-apps").write_text("Firefox\nChat\n")
        (self.cfg / "luxos").mkdir(parents=True)
        (self.cfg / "luxos/notifications.conf").write_text("TIME_CHANGE=1\nMUTED_APPS=Chat\n")
        self.start_notify()
        app = self.open("notifications")
        d = app.dump()
        self.assertTrue(switch_after(d, "Firefox"))
        self.assertFalse(switch_after(d, "Chat"))
        self.assertTrue(switch_after(d, "Notify about summer and winter time"))

        # delka bubliny: notifikace bez vlastniho casu zmizi po 3 s misto 6 s
        app.ask("combo Show banners for = 3")
        self.wait(lambda: self.notify_conf().get("BANNER_SECONDS") == "3")
        time.sleep(0.3)
        t0 = time.monotonic()
        nid = self.notify("Short")
        when, _, args = self.closed(nid, 6)
        self.assertEqual(args[1], 1)
        self.assertGreater(when - t0, 2.7)
        self.assertLess(when - t0, 4.5)

        # ztlumena aplikace: hned zavrena (4), ostatni ne; vypnuti v okne se projevi hned
        nid = self.notify("Muted", app="Chat")
        self.assertEqual(self.closed(nid, 3)[2][1], 4)
        app.ask("switch Firefox = off")
        self.wait(lambda: self.notify_conf().get("MUTED_APPS") == "Chat;Firefox")
        time.sleep(0.3)
        nid = self.notify("Muted too", app="Firefox")
        self.assertEqual(self.closed(nid, 3)[2][1], 4)
        app.ask("switch Chat = on")
        self.wait(lambda: self.notify_conf().get("MUTED_APPS") == "Firefox")

        # Nerusit z okna: signal pro listu, tichy rezim; konec Nerusit pres D-Bus nesmaze ostatni volby
        app.ask("switch Do Not Disturb = on")
        self.pump_until(lambda: any(s[1] == "DoNotDisturbChanged" and s[2] == (True,) for s in self.signals), 3,
                        "no DoNotDisturbChanged")
        self.assertEqual(self.call(HISTORY, "GetDoNotDisturb", reply="(b)"), (True,))
        nid = self.notify("Quiet", app="Mail")
        self.assertEqual(self.closed(nid, 3)[2][1], 4)
        self.call(HISTORY, "SetDoNotDisturb", (False,), "(b)")
        conf = self.notify_conf()
        self.assertEqual(conf["DO_NOT_DISTURB"], "false")
        self.assertEqual((conf["TIME_CHANGE"], conf["BANNER_SECONDS"], conf["MUTED_APPS"]), ("1", "3", "Firefox"))

        # historie: vypnuta = nic se neuklada; velikost zkrati stavajici seznam
        for i in range(4):
            self.notify(f"Kept {i}", app="Mail", keep=True, timeout=200)
        self.pump_until(lambda: len(self.call(LOG, "List", ("", 0, False), "(sub)", "(a(sxssssssa(ss)ib))")[0]) == 4,
                        3, "history")
        app.ask("combo Number of notifications to keep = 20")
        app.ask("switch Keep notifications in the menu bar = off")
        self.wait(lambda: self.notify_conf().get("HISTORY") == "0")
        time.sleep(0.3)
        self.notify("Not kept", app="Mail", keep=True, timeout=200)
        rows = self.call(LOG, "List", ("", 0, False), "(sub)", "(a(sxssssssa(ss)ib))")[0]
        self.assertEqual([r[6] for r in rows], ["Kept 3", "Kept 2", "Kept 1", "Kept 0"])
        self.assertEqual(self.notify_conf()["HISTORY_SIZE"], "20")
        (self.cfg / "luxos/notifications.conf").write_text(
            (self.cfg / "luxos/notifications.conf").read_text().replace("HISTORY_SIZE=20", "HISTORY_SIZE=2")
            .replace("HISTORY=0", "HISTORY=1"))
        self.pump_until(lambda: len(self.call(LOG, "List", ("", 0, False), "(sub)", "(a(sxssssssa(ss)ib))")[0]) == 2,
                        3, "history not truncated")

        app.ask("switch Play sounds = off")
        app.ask("switch Notify about summer and winter time = off")
        self.wait(lambda: self.notify_conf().get("TIME_CHANGE") == "0" and self.notify_conf().get("SOUNDS") == "0")
        self.assertEqual((data / "notification-apps").read_text().split(), ["Firefox", "Chat", "Test", "Mail"])
        self.assertNotIn("LSL callback error", (self.home / "notify.err").read_text())

    def test_drives_and_automount(self):
        app = self.open("drives")
        self.assertNotIn("Import photos when a camera is connected", labels(app.dump()))
        app.ask("switch Mount USB drives and memory cards = on")
        app.ask("switch Open a window with the drive's files = on")
        channel = self.cfg / "xfce4/xfconf/xfce-perchannel-xml/thunar-volman.xml"
        self.wait(lambda: xfconf_file(channel).get("/autobrowse/enabled") == "true")
        self.assertEqual(xfconf_file(channel), {"/automount-drives/enabled": "true", "/autobrowse/enabled": "true"})

        # falesny UDisks2 na soukrome "systemove" sbernici, vychozi aplikace pro slozky = fakefm
        system = lsl_app.Bus()
        self.addCleanup(system.stop)
        log = self.home / "udisks.log"
        env = dict(self.env, FAKE_UDISKS_ADDR=system.address, FAKE_UDISKS_LOG=str(log), FAKE_UDISKS_MEDIA=str(self.home / "media"),
                   DBUS_SYSTEM_BUS_ADDRESS=system.address)
        (self.cfg / "mimeapps.list").write_text("[Default Applications]\ninode/directory=fakefm.desktop\n")
        fake = subprocess.Popen([sys.executable, str(HERE / "udisks/fake_udisks2.py")], env=env, stdout=subprocess.PIPE,
                                text=True)
        self.procs.append(fake)
        self.assertEqual(fake.stdout.readline().strip(), "READY")
        probe = lsl_app.App([str(self.probe)], env)
        self.apps.append(probe)
        self.assertEqual(probe.line("ready", 10), "True")
        conn = Gio.DBusConnection.new_for_address_sync(
            system.address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)

        def plug(name, kind):
            conn.call_sync("org.freedesktop.UDisks2", "/org/freedesktop/UDisks2", "cz.luxos.Test", "Plug",
                           GLib.Variant("(ss)", (name, kind)), None, 0, 5000, None)

        def mounts():
            return [json.loads(line)["path"].rsplit("/", 1)[1] for line in log.read_text().splitlines()] \
                if log.exists() else []

        plug("USB_STICK", "usb")
        self.wait(lambda: "fakefm" in (self.home / "fake.log").read_text() if (self.home / "fake.log").exists() else False,
                  5, "file manager not opened")
        self.assertEqual(json.loads(log.read_text().splitlines()[0])["options"], {"auth.no_user_interaction": True})
        self.assertIn(f"fakefm {self.home}/media/USB STICK\n", (self.home / "fake.log").read_text())
        plug("internal", "system")
        plug("ignored", "ignore")
        plug("dvd", "dvd")                    # CD/DVD vypnute
        plug("card", "media")                 # jen Filesystem, Block pres GetAll
        self.wait(lambda: "card" in mounts(), 5, "card not mounted")
        time.sleep(0.5)
        self.assertEqual(mounts(), ["USB_STICK", "card"])
        # vypnuto v okne: dalsi disk se nepripoji, CD/DVD po zapnuti ano (bez okna, kdyz je autobrowse vypnute)
        app.ask("switch Mount USB drives and memory cards = off")
        app.ask("switch Mount inserted CDs and DVDs = on")
        app.ask("switch Open a window with the drive's files = off")
        self.wait(lambda: xfconf_file(channel).get("/autobrowse/enabled") == "false")
        plug("usb2", "usb")
        plug("dvd2", "dvd")
        self.wait(lambda: "dvd2" in mounts(), 5, "dvd not mounted")
        time.sleep(0.5)
        self.assertEqual(mounts(), ["USB_STICK", "card", "dvd2"])
        self.assertEqual((self.home / "fake.log").read_text().count("fakefm "), 2)


if __name__ == "__main__":
    unittest.main()
