"""Testy Vychoziho nastaveni aplikaci (luxos_app_reset + luxos-app-reset): seznam aplikaci
v docasne domovske slozce, chranene slozky, reset presunem do zalohy, obnova, prikazova radka.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_app_reset.py -v
    env -u DISPLAY xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_luxos_app_reset.py -v

Okno jen pod xvfb-run (jinak se preskoci); skutecnou domovskou slozku nikdy nemeni.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.normpath(os.path.join(HERE, "..", "files", "python"))
BIN = os.path.normpath(os.path.join(HERE, "..", "files", "bin", "luxos-app-reset"))
I18N = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
sys.path.insert(0, PYDIR)
sys.path.insert(1, I18N)
import luxos_app_reset as core  # noqa: E402

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


class Home(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-app-reset-")
        self.home = os.path.join(self.tmp, "home")
        self.apps_dir = os.path.join(self.tmp, "applications")
        os.makedirs(self.apps_dir)
        for name, text in DESKTOP.items():
            with open(os.path.join(self.apps_dir, name), "w") as f:
                f.write(text)
        self.env = {"HOME": self.home, "LANG": "cs_CZ.UTF-8"}
        for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "LC_ALL", "LC_MESSAGES"):
            self.env[k] = ""
        p = mock.patch.dict(os.environ, self.env)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(core, "DESKTOP_DIRS", [self.apps_dir])
        p.start()
        self.addCleanup(p.stop)
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
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, rel):
        return os.path.join(self.home, rel)


class Core(Home):
    def test_catalog(self):
        cat = core.desktop_catalog([self.apps_dir])
        self.assertEqual(cat["vlc"]["name"], "Přehrávač VLC")         # Name[cs]
        self.assertEqual(cat["firefox"]["name"], "Firefox")            # posledni cast org.mozilla.firefox
        self.assertEqual(cat["code"]["name"], "Visual Studio Code")    # StartupWMClass i Exec
        self.assertEqual(cat["calculator"]["name"], "Calculator")
        self.assertEqual(cat["comspotifyclient"]["name"], "Spotify")
        self.assertNotIn("hidden", cat)

    def test_scan(self):
        apps = {a["key"]: a for a in core.scan()}
        self.assertEqual(set(apps), {"vlc", "firefox", "visualstudiocode", "someapp", "comspotifyclient"})
        vlc = apps["vlc"]
        self.assertEqual(vlc["name"], "Přehrávač VLC")
        self.assertTrue(vlc["known"])
        self.assertEqual([k for k, _p in vlc["paths"]], ["config", "data", "cache"])
        self.assertEqual(vlc["size"], 102)
        self.assertEqual(apps["firefox"]["paths"], [("home", self.path(".mozilla"))])
        self.assertEqual(apps["visualstudiocode"]["name"], "Visual Studio Code")
        self.assertFalse(apps["someapp"]["known"])
        self.assertEqual(apps["comspotifyclient"]["paths"], [("flatpak", self.path(".var/app/com.spotify.Client"))])
        # zname aplikace pred ostatnimi
        self.assertEqual(core.scan()[-1]["key"], "someapp")

    def test_protected_never_listed(self):
        keys = {a["key"] for a in core.scan()}
        for k in ("xfce4", "keyrings", "luxai", "trash", "gtk30", "onlycache", "applications"):
            self.assertNotIn(k, keys)

    def test_backup_folder_not_listed(self):
        core.reset(core.find(core.scan(), "vlc"))
        self.assertNotIn("luxos", {a["key"] for a in core.scan()})
        self.assertIsNone(core.find(core.scan(), "app-settings-backups"))

    def test_find(self):
        apps = core.scan()
        self.assertEqual(core.find(apps, "VLC")["key"], "vlc")
        self.assertEqual(core.find(apps, "Přehrávač VLC")["key"], "vlc")
        self.assertEqual(core.find(apps, "Code")["key"], "visualstudiocode")
        self.assertIsNone(core.find(apps, "nothing"))

    def test_reset_moves_never_deletes(self):
        app = core.find(core.scan(), "vlc")
        dest = core.reset(app, now=datetime.datetime(2026, 10, 26, 15, 0, 0))
        self.assertEqual(os.path.basename(dest), "2026-10-26_15-00-00-vlc")
        self.assertEqual(os.path.dirname(dest), self.path(".local/share/luxos/app-settings-backups"))
        for rel in (".config/vlc", ".local/share/vlc", ".cache/vlc"):
            self.assertFalse(os.path.exists(self.path(rel)))
        with open(os.path.join(dest, "config/vlc/vlcrc")) as f:
            self.assertEqual(f.read(), "x" * 100)
        self.assertTrue(os.path.isfile(os.path.join(dest, "data/vlc/ml.xspf")))
        with open(os.path.join(dest, "manifest.json")) as f:
            m = json.load(f)
        self.assertEqual(m["key"], "vlc")
        self.assertEqual([i["path"] for i in m["items"]],
                         [self.path(".config/vlc"), self.path(".local/share/vlc"), self.path(".cache/vlc")])
        self.assertEqual(os.stat(os.path.dirname(dest)).st_mode & 0o777, 0o700)
        # ostatni aplikace beze zmeny
        self.assertTrue(os.path.exists(self.path(".config/Code/settings.json")))

    def test_reset_twice_same_second(self):
        t = datetime.datetime(2026, 10, 26, 15, 0, 0)
        a = core.reset(core.find(core.scan(), "vlc"), now=t)
        os.makedirs(self.path(".config/vlc"))
        b = core.reset(core.find(core.scan(), "vlc"), now=t)
        self.assertNotEqual(a, b)

    def test_reset_failure_rolls_back(self):
        app = core.find(core.scan(), "vlc")
        real = core._move
        calls = []

        def failing(src, dst):
            calls.append(src)
            if len(calls) == 2:
                raise OSError("disk full")
            return real(src, dst)
        with mock.patch.object(core, "_move", failing):
            with self.assertRaises(OSError):
                core.reset(app)
        self.assertTrue(os.path.isfile(self.path(".config/vlc/vlcrc")))
        self.assertTrue(os.path.isfile(self.path(".local/share/vlc/ml.xspf")))
        self.assertEqual(core.list_backups(), [])

    def test_restore(self):
        dest = core.reset(core.find(core.scan(), "vlc"), now=datetime.datetime(2026, 10, 26, 15, 0, 0))
        # aplikace mezitim vytvorila nove nastaveni
        os.makedirs(self.path(".config/vlc"))
        with open(self.path(".config/vlc/vlcrc"), "w") as f:
            f.write("new")
        saved = core.restore(dest, now=datetime.datetime(2026, 10, 26, 16, 0, 0))
        with open(self.path(".config/vlc/vlcrc")) as f:
            self.assertEqual(f.read(), "x" * 100)
        self.assertTrue(os.path.isfile(self.path(".local/share/vlc/ml.xspf")))
        self.assertFalse(os.path.exists(dest))
        with open(os.path.join(saved, "config/vlc/vlcrc")) as f:
            self.assertEqual(f.read(), "new")
        self.assertEqual([b["dir"] for b in core.list_backups()], [saved])

    def test_restore_refuses_foreign_folder(self):
        other = os.path.join(self.tmp, "evil")
        os.makedirs(other)
        with open(os.path.join(other, "manifest.json"), "w") as f:
            json.dump({"app": "x", "key": "x", "items": [{"kind": "config", "path": "/etc/passwd", "backup": "a"}]}, f)
        with self.assertRaises(ValueError):
            core.restore(other)

    def test_running(self):
        app = core.find(core.scan(), "vlc")
        self.assertTrue(core.is_running(app, {"vlc", "bash"}))
        self.assertFalse(core.is_running(app, {"bash"}))
        self.assertTrue(core.is_running(core.find(core.scan(), "firefox"), {"firefoxbin"}))
        self.assertIn("python3", core.running_programs())          # tento proces

    def test_human_size(self):
        self.assertEqual(core.human_size(100), "100 B")
        self.assertEqual(core.human_size(2048), "2.0 kB")
        self.assertEqual(core.human_size(5 * 1024 ** 3), "5.0 GB")


class Cli(Home):
    def run_cli(self, *args, inp=None):
        env = dict(os.environ, PYTHONPATH=PYDIR + ":" + I18N, LUXOS_I18N_DIR=I18N, LANG="C.UTF-8", NO_AT_BRIDGE="1")
        env.pop("DISPLAY", None)
        r = subprocess.run([sys.executable, BIN] + list(args), env=env, capture_output=True, text=True,
                           input=inp, timeout=60)
        return r.returncode, r.stdout + r.stderr

    def test_list(self):
        # katalog z DESKTOP_DIRS tady neni (jiny proces) - stejne aplikace, nazvy podle slozek
        rc, out = self.run_cli("list", "--json")
        self.assertEqual(rc, 0, out)
        keys = {a["key"] for a in json.loads(out)}
        self.assertIn("vlc", keys)
        self.assertNotIn("keyrings", keys)
        rc, out = self.run_cli("list")
        self.assertIn("~/.config/vlc", out)

    def test_reset_needs_confirmation(self):
        rc, out = self.run_cli("reset", "vlc")
        self.assertEqual(rc, 1)
        self.assertIn("Cancelled", out)
        self.assertTrue(os.path.exists(self.path(".config/vlc")))
        rc, out = self.run_cli("reset", "vlc", "--yes")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.path(".config/vlc")))
        self.assertIn("app-settings-backups", out)
        rc, out = self.run_cli("backups")
        self.assertIn("vlc", out)
        bdir = out.split()[0]
        rc, out = self.run_cli("restore", bdir)
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.exists(self.path(".config/vlc/vlcrc")))

    def test_reset_unknown_and_usage(self):
        rc, out = self.run_cli("reset", "nonexistent", "--yes")
        self.assertEqual(rc, 1)
        self.assertIn("nonexistent", out)
        rc, out = self.run_cli("reset")
        self.assertEqual(rc, 2)
        rc, out = self.run_cli("bogus")
        self.assertEqual(rc, 2)

    def test_reset_refused_while_running(self):
        # proces se jmenem "someapp" (kopie sleep)
        exe = os.path.join(self.tmp, "someapp")
        shutil.copy("/usr/bin/sleep", exe)
        p = subprocess.Popen([exe, "30"])
        try:
            rc, out = self.run_cli("reset", "someapp", "--yes")
            self.assertEqual(rc, 1)
            self.assertIn("Quit it first", out)
            self.assertTrue(os.path.exists(self.path(".config/someapp")))
            rc, out = self.run_cli("reset", "someapp", "--yes", "--force")
            self.assertEqual(rc, 0, out)
        finally:
            p.kill()
            p.wait()

    @unittest.skipUnless(shutil.which("broadwayd"), "okno jen na neviditelnem GTK Broadway (broadwayd)")
    def test_window_opens(self):
        """Okno se sestavi a nespadne - na GTK Broadway (bez okna na skutecne obrazovce)."""
        import time
        disp = f":{40 + os.getpid() % 50}"
        bw = subprocess.Popen(["broadwayd", disp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(1)
            env = dict(os.environ, PYTHONPATH=PYDIR + ":" + I18N, LUXOS_APP_RESET_TEST_QUIT="1500",
                       GDK_BACKEND="broadway", BROADWAY_DISPLAY=disp)
            env.pop("DISPLAY", None)
            env.pop("WAYLAND_DISPLAY", None)
            r = subprocess.run([sys.executable, BIN], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("Traceback", r.stderr)
        finally:
            bw.terminate()
            bw.wait()

    def test_desktop_file(self):
        with open(os.path.join(HERE, "..", "files", "applications", "luxos-app-reset.desktop")) as f:
            d = f.read()
        self.assertIn("Exec=luxos-app-reset\n", d)
        self.assertIn("X-XFCE-SettingsDialog", d)
        self.assertIn("Name[cs]=", d)


if __name__ == "__main__":
    unittest.main()
