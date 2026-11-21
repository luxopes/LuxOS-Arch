"""Testy Vychoziho nastaveni aplikaci (files/lsl/luxos-app-reset.lsl + luxos_app_reset.lsl): seznam
aplikaci v docasne domovske slozce, chranene slozky, reset presunem do zalohy, obnova, prikazova radka, okno.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_app_reset.py -v

Prekladac lslc (balik lsl) je potreba; bez nej se testy preskoci. Okno jen ve vlastnim Xvfb; skutecnou
domovskou slozku nikdy nemeni (HOME a XDG_* v docasne slozce, .desktop z LUXOS_DESKTOP_DIRS).
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
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

DESKTOP = {
    "org.mozilla.firefox.desktop": "[Desktop Entry]\nType=Application\nName=Firefox\nExec=firefox %u\nIcon=firefox\n",
    "vlc.desktop": "[Desktop Entry]\nType=Application\nName=VLC media player\nName[cs]=Přehrávač VLC\n"
                   "Exec=/usr/bin/vlc --started-from-file %U\nIcon=vlc\n",
    "code.desktop": "[Desktop Entry]\nType=Application\nName=Visual Studio Code\nExec=code %F\n"
                    "StartupWMClass=Code\nIcon=vscode\n",
    "org.gnome.Calculator.desktop": "[Desktop Entry]\nType=Application\nName=Calculator\nExec=gnome-calculator\n",
    "hidden.desktop": "[Desktop Entry]\nType=Application\nName=Hidden\nNoDisplay=true\nExec=hidden\n",
    "com.spotify.Client.desktop": "[Desktop Entry]\nType=Application\nName=Spotify\n"
                                  "Exec=/usr/bin/flatpak run --branch=stable com.spotify.Client\n",
}
TMP = None
BINARY = None


def setUpModule():
    global TMP, BINARY
    TMP = tempfile.mkdtemp(prefix="luxos-app-reset-", dir=luxos_testguard._private_dir())
    BINARY = lsl_app.build("luxos-app-reset", TMP)


def tearDownModule():
    if TMP:
        shutil.rmtree(TMP, True)


class Home(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir=TMP)
        self.home = os.path.join(self.tmp, "home")
        self.apps_dir = os.path.join(self.tmp, "applications")
        os.makedirs(self.apps_dir)
        for name, text in DESKTOP.items():
            with open(os.path.join(self.apps_dir, name), "w") as f:
                f.write(text)
        for rel, data in (
                (".config/vlc/vlcrc", "x" * 100), (".local/share/vlc/ml.xspf", "y"), (".cache/vlc/art", "z"),
                (".config/Code/settings.json", "{}"), (".mozilla/firefox/profiles.ini", "[x]"),
                (".config/xfce4/panel.xml", "p"), (".local/share/keyrings/login.keyring", "secret"),
                (".config/luxai/account.json", "{}"), (".local/share/Trash/files/a", "a"),
                (".config/someapp/conf", "c"), (".cache/onlycache/x", "c"), (".config/gtk-3.0/bookmarks", "b"),
                (".var/app/com.spotify.Client/config/x", "s"), (".local/share/applications/my.desktop", "d"),
                (".config/mimeapps.list", "m")):
            p = os.path.join(self.home, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(data)

    def tearDown(self):
        # nepristupne slozky z testu chyb (jinak by je rmtree nesmazal)
        for d, dirs, _files in os.walk(self.tmp):
            for name in dirs:
                os.chmod(os.path.join(d, name), 0o700)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, rel):
        return os.path.join(self.home, rel)

    def env(self, lang="C.UTF-8"):
        env = dict(os.environ, HOME=self.home, LANG=lang, LC_ALL="", LC_MESSAGES="", XDG_CONFIG_HOME="",
                   XDG_DATA_HOME="", XDG_CACHE_HOME="", LUXOS_DESKTOP_DIRS=self.apps_dir,
                   LUXOS_I18N_DIR=lsl_app.I18N, NO_AT_BRIDGE="1")
        env.pop("DISPLAY", None)
        return env

    def cli(self, *args, lang="C.UTF-8", prefix=()):
        r = subprocess.run(list(prefix) + [BINARY] + list(args), env=self.env(lang), capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=60)
        return r.returncode, r.stdout + r.stderr

    def apps(self, lang="C.UTF-8"):
        rc, out = self.cli("list", "--json", lang=lang)
        self.assertEqual(rc, 0, out)
        return {a["key"]: a for a in json.loads(out)}

    def backups(self):
        root = self.path(".local/share/luxos/app-settings-backups")
        return sorted(os.listdir(root)) if os.path.isdir(root) else []


class Core(Home):
    def test_catalog(self):
        apps = self.apps("cs_CZ.UTF-8")
        self.assertEqual(apps["vlc"]["name"], "Přehrávač VLC")                      # Name[cs]
        self.assertEqual(apps["firefox"]["name"], "Firefox")                         # posledni cast org.mozilla.firefox
        self.assertEqual(apps["visualstudiocode"]["name"], "Visual Studio Code")     # StartupWMClass i Exec
        self.assertEqual(apps["comspotifyclient"]["name"], "Spotify")                # program z flatpak run
        self.assertEqual(self.apps()["vlc"]["name"], "VLC media player")
        # NoDisplay se nebere: slozka ~/.config/hidden je neznama aplikace
        os.makedirs(self.path(".config/hidden"))
        with open(self.path(".config/hidden/x"), "w") as f:
            f.write("h")
        self.assertFalse(self.apps()["hidden"]["known"])
        # Calculator (posledni cast org.gnome.Calculator)
        os.makedirs(self.path(".config/calculator"))
        with open(self.path(".config/calculator/x"), "w") as f:
            f.write("c")
        self.assertEqual(self.apps()["calculator"]["name"], "Calculator")

    def test_scan(self):
        apps = self.apps("cs_CZ.UTF-8")
        self.assertEqual(set(apps), {"vlc", "firefox", "visualstudiocode", "someapp", "comspotifyclient"})
        vlc = apps["vlc"]
        self.assertTrue(vlc["known"])
        self.assertEqual(vlc["paths"], [self.path(".config/vlc"), self.path(".local/share/vlc"), self.path(".cache/vlc")])
        self.assertEqual(vlc["size"], 102)
        self.assertEqual(apps["firefox"]["paths"], [self.path(".mozilla")])
        self.assertFalse(apps["someapp"]["known"])
        self.assertEqual(apps["comspotifyclient"]["paths"], [self.path(".var/app/com.spotify.Client")])
        # zname aplikace pred ostatnimi
        rc, out = self.cli("list", "--json")
        self.assertEqual(json.loads(out)[-1]["key"], "someapp")

    def test_protected_never_listed(self):
        keys = set(self.apps())
        for k in ("xfce4", "keyrings", "luxai", "trash", "gtk30", "onlycache", "applications"):
            self.assertNotIn(k, keys)

    def test_backup_folder_not_listed(self):
        self.assertEqual(self.cli("reset", "vlc", "--yes")[0], 0)
        self.assertNotIn("luxos", set(self.apps()))
        rc, out = self.cli("reset", "app-settings-backups", "--yes")
        self.assertEqual(rc, 1)
        self.assertIn("No settings found", out)

    def test_find(self):
        # stdin neni terminal: bez --yes jen vypis slozek a "Zruseno" (najde se), jinak "nenalezeno"
        for query, lang in (("VLC", "C.UTF-8"), ("Přehrávač VLC", "cs_CZ.UTF-8"), ("Code", "C.UTF-8")):
            rc, out = self.cli("reset", query, lang=lang)
            self.assertEqual(rc, 1)
            self.assertNotIn("No settings found", out, query)
            self.assertNotIn("Nenalezeno", out, query)
        self.assertIn("~/.config/Code", self.cli("reset", "Code")[1])
        self.assertIn("No settings found for nothing.", self.cli("reset", "nothing")[1])
        self.assertTrue(os.path.exists(self.path(".config/vlc")))

    def test_reset_moves_never_deletes(self):
        rc, out = self.cli("reset", "vlc", "--yes")
        self.assertEqual(rc, 0, out)
        [name] = self.backups()
        self.assertRegex(name, r"^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d-vlc$")
        dest = self.path(".local/share/luxos/app-settings-backups/" + name)
        self.assertIn(dest, out)
        for rel in (".config/vlc", ".local/share/vlc", ".cache/vlc"):
            self.assertFalse(os.path.exists(self.path(rel)))
        with open(os.path.join(dest, "config/vlc/vlcrc")) as f:
            self.assertEqual(f.read(), "x" * 100)
        self.assertTrue(os.path.isfile(os.path.join(dest, "data/vlc/ml.xspf")))
        self.assertTrue(os.path.isfile(os.path.join(dest, "cache/vlc/art")))
        with open(os.path.join(dest, "manifest.json")) as f:
            m = json.load(f)
        self.assertEqual(m["key"], "vlc")
        self.assertEqual([i["path"] for i in m["items"]],
                         [self.path(".config/vlc"), self.path(".local/share/vlc"), self.path(".cache/vlc")])
        self.assertEqual([i["backup"] for i in m["items"]], ["config/vlc", "data/vlc", "cache/vlc"])
        self.assertEqual(os.stat(os.path.dirname(dest)).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(dest).st_mode & 0o777, 0o700)
        # ostatni aplikace beze zmeny
        self.assertTrue(os.path.exists(self.path(".config/Code/settings.json")))

    def test_reset_twice_same_second(self):
        self.assertEqual(self.cli("reset", "vlc", "--yes")[0], 0)
        os.makedirs(self.path(".config/vlc"))
        with open(self.path(".config/vlc/new"), "w") as f:
            f.write("n")
        self.assertEqual(self.cli("reset", "vlc", "--yes")[0], 0)
        self.assertEqual(len(self.backups()), 2)

    def test_reset_failure_rolls_back(self):
        # druha slozka nejde presunout (adresar bez prava zapisu: rename meni jeho "..")
        os.chmod(self.path(".local/share/vlc"), 0o500)
        rc, out = self.cli("reset", "vlc", "--yes")
        self.assertEqual(rc, 1)
        self.assertIn("The settings could not be moved", out)
        os.chmod(self.path(".local/share/vlc"), 0o700)
        self.assertTrue(os.path.isfile(self.path(".config/vlc/vlcrc")))
        self.assertTrue(os.path.isfile(self.path(".local/share/vlc/ml.xspf")))
        self.assertTrue(os.path.isfile(self.path(".cache/vlc/art")))
        self.assertEqual(self.backups(), [])

    def test_manifest_write_failure_rolls_back(self):
        """Plny disk pri zapisu manifestu (RLIMIT_FSIZE 0): nastaveni se vrati na misto (jinak by bylo
        presunute v zaloze, kterou seznam neukaze a nejde obnovit)."""
        rc, out = self.cli("reset", "vlc", "--yes", prefix=("bash", "-c", 'trap "" XFSZ; ulimit -f 0; exec "$@"', "x"))
        self.assertEqual(rc, 1, out)
        self.assertIn("cannot write", out)
        self.assertTrue(os.path.isfile(self.path(".config/vlc/vlcrc")))
        self.assertTrue(os.path.isfile(self.path(".local/share/vlc/ml.xspf")))
        self.assertEqual(self.backups(), [])

    def test_restore(self):
        self.assertEqual(self.cli("reset", "vlc", "--yes")[0], 0)
        [first] = self.backups()
        # aplikace mezitim vytvorila nove nastaveni
        os.makedirs(self.path(".config/vlc"))
        with open(self.path(".config/vlc/vlcrc"), "w") as f:
            f.write("new")
        rc, out = self.cli("restore", self.path(".local/share/luxos/app-settings-backups/" + first))
        self.assertEqual(rc, 0, out)
        with open(self.path(".config/vlc/vlcrc")) as f:
            self.assertEqual(f.read(), "x" * 100)
        self.assertTrue(os.path.isfile(self.path(".local/share/vlc/ml.xspf")))
        [saved] = [b for b in self.backups() if b != first]
        self.assertNotIn(first, self.backups())
        self.assertIn(saved, out)
        with open(self.path(".local/share/luxos/app-settings-backups/%s/config/vlc/vlcrc" % saved)) as f:
            self.assertEqual(f.read(), "new")

    def test_restore_python_backup(self):
        # zaloha z drivejsi verze v Pythonu (json.dump s indent=1, ensure_ascii=False) jde obnovit
        dest = self.path(".local/share/luxos/app-settings-backups/2026-10-26_15-00-00-vlc")
        os.makedirs(os.path.join(dest, "config"), mode=0o700)
        shutil.move(self.path(".config/vlc"), os.path.join(dest, "config/vlc"))
        with open(os.path.join(dest, "manifest.json"), "w") as f:
            json.dump({"app": "Přehrávač VLC", "key": "vlc", "time": "2026-10-26_15-00-00",
                       "items": [{"kind": "config", "path": self.path(".config/vlc"), "backup": "config/vlc"}]},
                      f, indent=1, ensure_ascii=False)
        rc, out = self.cli("backups")
        self.assertIn("2026-10-26_15-00-00-vlc  Přehrávač VLC  (2026-10-26_15-00-00)", out)
        self.assertEqual(self.cli("restore", dest)[0], 0)
        self.assertTrue(os.path.isfile(self.path(".config/vlc/vlcrc")))
        self.assertFalse(os.path.exists(dest))

    def test_restore_refuses_foreign_folder(self):
        other = os.path.join(self.tmp, "evil")
        os.makedirs(other)
        with open(os.path.join(other, "manifest.json"), "w") as f:
            json.dump({"app": "x", "key": "x", "items": [{"kind": "config", "path": "/etc/passwd", "backup": "a"}]}, f)
        rc, out = self.cli("restore", other)
        self.assertEqual(rc, 1)
        self.assertIn("not a LuxOS app settings backup", out)

    def test_restore_refuses_tampered_manifest(self):
        self.assertEqual(self.cli("reset", "vlc", "--yes")[0], 0)
        [name] = self.backups()
        dest = self.path(".local/share/luxos/app-settings-backups/" + name)
        mf = os.path.join(dest, "manifest.json")
        with open(mf) as f:
            good = json.load(f)
        victim = self.path("Documents/keep.txt")
        os.makedirs(os.path.dirname(victim))
        with open(victim, "w") as f:
            f.write("mine")
        bad_items = [
            {"kind": "config", "path": self.path(".config/../Documents/x"), "backup": "config/vlc"},
            {"kind": "config", "path": self.path(".config/vlc/deep"), "backup": "config/vlc"},
            {"kind": "config", "path": "/tmp/x", "backup": "config/vlc"},
            {"kind": "config", "path": self.path(".config/vlc"), "backup": "../../../../Documents/keep.txt"},
            {"kind": "config", "path": self.path(".config/vlc"), "backup": "/etc/passwd"},
            {"kind": "config", "path": self.path(".local/share"), "backup": "config/vlc"},
            {"kind": "config", "path": 5, "backup": "config/vlc"},
        ]
        for item in bad_items:
            with open(mf, "w") as f:
                json.dump(dict(good, items=[item]), f)
            rc, out = self.cli("restore", dest)
            self.assertEqual(rc, 1, item)
            self.assertIn("invalid LuxOS app settings backup", out)
        with open(victim) as f:
            self.assertEqual(f.read(), "mine")
        with open(mf, "w") as f:
            json.dump(good, f)
        self.assertEqual(self.cli("restore", dest)[0], 0)
        self.assertTrue(os.path.isfile(self.path(".config/vlc/vlcrc")))

    def test_human_size(self):
        os.makedirs(self.path(".config/bigapp"))
        with open(self.path(".config/bigapp/a"), "w") as f:
            f.write("x" * 2048)
        os.makedirs(self.path(".config/hugeapp"))
        with open(self.path(".config/hugeapp/sparse"), "w") as f:
            f.truncate(5 * 1024 ** 3)         # ridky soubor: velikost bez mista na disku
        rc, out = self.cli("list", lang="en_US.UTF-8")
        lines = {line.split()[0]: line for line in out.splitlines()}
        self.assertIn(" 102 B ", lines["vlc"])
        self.assertIn(" 2.0 kB ", lines["bigapp"])
        self.assertIn(" 5.0 GB ", lines["hugeapp"])
        # desetinna carka podle jazyka aplikace (ne podle vygenerovanych locale)
        rc, out = self.cli("list", lang="cs_CZ.UTF-8")
        self.assertIn(" 2,0 kB ", out)
        rc, out = self.cli("list", lang="de_DE.UTF-8")
        self.assertIn(" 5,0 GB ", out)


class Cli(Home):
    def test_list(self):
        rc, out = self.cli("list")
        self.assertEqual(rc, 0, out)
        self.assertIn("~/.config/vlc", out)
        self.assertNotIn("keyrings", out)

    def test_reset_needs_confirmation(self):
        rc, out = self.cli("reset", "vlc")
        self.assertEqual(rc, 1)
        self.assertIn("Cancelled", out)
        self.assertTrue(os.path.exists(self.path(".config/vlc")))
        rc, out = self.cli("reset", "vlc", "--yes")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.path(".config/vlc")))
        self.assertIn("app-settings-backups", out)
        rc, out = self.cli("backups")
        self.assertIn("vlc", out)
        bdir = out.split()[0]
        rc, out = self.cli("restore", bdir)
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.exists(self.path(".config/vlc/vlcrc")))

    def test_reset_unknown_and_usage(self):
        rc, out = self.cli("reset", "nonexistent", "--yes")
        self.assertEqual(rc, 1)
        self.assertIn("nonexistent", out)
        self.assertEqual(self.cli("reset")[0], 2)
        self.assertEqual(self.cli("restore")[0], 2)
        rc, out = self.cli("bogus")
        self.assertEqual(rc, 2)
        self.assertIn("luxos-app-reset list [--json]", out)

    def test_help_translated(self):
        rc, en = self.cli("--help", lang="en_US.UTF-8")
        self.assertEqual(rc, 0)
        self.assertIn("reset apps to their default settings; nothing is deleted", en)
        self.assertIn("  luxos-app-reset backups           list backups", en)
        for lang in ("cs_CZ.UTF-8", "de_DE.UTF-8"):
            rc, out = self.cli("--help", lang=lang)
            self.assertEqual(rc, 0)
            self.assertNotIn("nothing is deleted", out)
            self.assertNotIn("list backups", out)
            self.assertIn("luxos-app-reset restore", out)
        self.assertRegex(self.cli("--help", lang="cs_CZ.UTF-8")[1], "[ěščřžůá]")

    def test_reset_refused_while_running(self):
        # proces se jmenem "someapp" (kopie sleep)
        exe = os.path.join(self.tmp, "someapp")
        shutil.copy("/usr/bin/sleep", exe)
        p = subprocess.Popen([exe, "30"])
        try:
            rc, out = self.cli("reset", "someapp", "--yes")
            self.assertEqual(rc, 1)
            self.assertIn("Quit it first", out)
            self.assertTrue(os.path.exists(self.path(".config/someapp")))
            rc, out = self.cli("reset", "someapp", "--yes", "--force")
            self.assertEqual(rc, 0, out)
        finally:
            p.kill()
            p.wait()

    def test_desktop_file(self):
        with open(os.path.join(HERE, "..", "files", "applications", "luxos-app-reset.desktop")) as f:
            d = f.read()
        self.assertIn("Exec=luxos-app-reset\n", d)
        self.assertIn("X-XFCE-SettingsDialog", d)
        self.assertIn("Name[cs]=", d)


class Window(Home):
    @classmethod
    def setUpClass(cls):
        cls.x = lsl_app.Xvfb()

    @classmethod
    def tearDownClass(cls):
        cls.x.stop()

    def start(self, lang="C.UTF-8"):
        env = dict(self.env(lang), DISPLAY=self.x.display)
        luxos_testguard.check_env(env)
        self.app = lsl_app.App([BINARY], env)
        self.addCleanup(self.app.stop)
        self.assertTrue(self.app.wait(lambda: self.status()[-1:].isdigit() or self.status().endswith("settings")),
                        self.app.stderr())

    def status(self):
        d = self.app.dump()
        w = lsl_app.find(d, name="status") if d else None
        return w["text"] if w else ""

    def names(self):
        return [w["text"] for w in lsl_app.widgets(self.app.dump()) if w.get("name") == "app-name" and w["vis"]]

    def dialog_texts(self):
        return lsl_app.texts(self.app.dump(), dialog=True)

    def test_reset_and_restore(self):
        self.start()
        self.assertEqual(self.status(), "5 apps with settings")
        texts = lsl_app.texts(self.app.dump())
        self.assertIn("Apps", texts)
        self.assertIn("Other folders with settings", texts)
        self.assertNotIn("Backups", texts)
        self.assertEqual(self.names()[-1], "someapp")
        self.app.send("reset vlc")
        self.assertTrue(self.app.wait(lambda: "Reset the settings of VLC media player?" in self.dialog_texts()))
        self.assertTrue(any("~/.config/vlc" in t for t in self.dialog_texts()))
        self.app.ask("click Reset")
        self.assertTrue(self.app.wait(lambda: "Settings of VLC media player were reset" in self.dialog_texts()))
        self.app.ask("click OK")
        self.assertTrue(self.app.wait(lambda: "VLC media player" not in self.names()[:4]))
        self.assertFalse(os.path.exists(self.path(".config/vlc")))
        self.assertIn("Backups", lsl_app.texts(self.app.dump()))
        self.assertEqual(self.status(), "4 apps with settings")
        # obnova zalohy
        self.app.send("restore 0")
        self.assertTrue(self.app.wait(lambda: "Restore the settings of VLC media player?" in self.dialog_texts()))
        self.app.ask("click OK")
        self.assertTrue(self.app.wait(lambda: self.status() == "5 apps with settings"))
        self.assertTrue(os.path.isfile(self.path(".config/vlc/vlcrc")))

    def test_cancel_and_search(self):
        self.start()
        self.app.send("reset vlc")
        self.assertTrue(self.app.wait(lambda: self.dialog_texts()))
        self.app.ask("click Cancel")
        self.assertTrue(os.path.exists(self.path(".config/vlc")))
        self.app.ask("search spot")
        self.assertTrue(self.app.wait(lambda: self.names() == ["Spotify"]))

    def test_running_app(self):
        exe = os.path.join(self.tmp, "someapp")
        shutil.copy("/usr/bin/sleep", exe)
        p = subprocess.Popen([exe, "30"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        self.start()
        self.app.send("reset someapp")
        self.assertTrue(self.app.wait(lambda: "someapp is running" in self.dialog_texts()))
        self.app.ask("click OK")
        self.assertTrue(os.path.exists(self.path(".config/someapp")))

    def test_czech(self):
        self.start("cs_CZ.UTF-8")
        self.assertIn("Přehrávač VLC", self.names())
        self.assertEqual([w["title"] for w in self.app.dump()], ["Výchozí nastavení aplikací"])
        self.assertEqual(self.status(), "Aplikací s nastavením: 5")


if __name__ == "__main__":
    unittest.main()
