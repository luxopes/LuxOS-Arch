#!/usr/bin/env python3
"""LuxOS - testy luxos-apps-sync (kratke nazvy aplikaci a odkazy na aplikace z Flathubu).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_apps_sync.py -v

Vse v docasnych slozkach (LUXOS_APPS_*), skutecna instalace Flatpaku ani /var/lib/luxos se nemeni.
Export Flatpaku se napodobi jako skutecny: .desktop v exports/share/applications je relativni odkaz
do app/<id>/current/active/export, ikony v exports/share/icons/hicolor.
"""
import configparser
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
SYNC = os.path.join(FILES, "apps", "luxos-apps-sync")
UNITS = os.path.join(FILES, "apps")


def desktop(name, extra=""):
    return f"[Desktop Entry]\nType=Application\nName={name}\nExec={name.lower()}\nIcon={name.lower()}\n{extra}"


class AppsSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-apps-sync-")
        self.apps = os.path.join(self.tmp, "usr-share-applications")
        self.base = os.path.join(self.tmp, "var-lib-luxos-apps")
        self.flatpak = os.path.join(self.tmp, "flatpak")              # /var/lib/flatpak
        self.exports = os.path.join(self.flatpak, "exports", "share")
        self.conf = os.path.join(self.tmp, "rename.conf")
        os.makedirs(self.apps)
        with open(os.path.join(self.apps, "thunar.desktop"), "w") as f:
            f.write(desktop("Thunar File Manager"))
        with open(self.conf, "w") as f:
            f.write("# test\nthunar|Files|Soubory|luxos-files\nmissing-app|X|X|\n")
        self.env = dict(os.environ, LUXOS_APPS_RENAME_CONF=self.conf, LUXOS_APPS_SOURCE=self.apps,
                        LUXOS_APPS_DIR=self.base, LUXOS_APPS_FLATPAK_EXPORTS=self.exports)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sync(self):
        r = subprocess.run(["bash", SYNC], env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        return r

    def out(self, name=""):
        return os.path.join(self.base, "applications", name)

    def listing(self):
        return sorted(f for f in os.listdir(self.out()) if f.endswith(".desktop"))

    def flatpak_install(self, app_id, name):
        """Jako flatpak install: nasazena aplikace a relativni odkazy v exportech."""
        exp = os.path.join(self.flatpak, "app", app_id, "current", "active", "export", "share")
        os.makedirs(os.path.join(exp, "applications"), exist_ok=True)
        with open(os.path.join(exp, "applications", app_id + ".desktop"), "w") as f:
            f.write(desktop(name).replace(f"Icon={name.lower()}", f"Icon={app_id}"))
        icon_dir = os.path.join(exp, "icons", "hicolor", "128x128", "apps")
        os.makedirs(icon_dir, exist_ok=True)
        with open(os.path.join(icon_dir, app_id + ".png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        for sub in ("applications", "icons/hicolor/128x128/apps"):
            os.makedirs(os.path.join(self.exports, sub), exist_ok=True)
        ext = {"applications": ".desktop", "icons/hicolor/128x128/apps": ".png"}
        for sub, suffix in ext.items():
            link = os.path.join(self.exports, sub, app_id + suffix)
            target = os.path.join(exp, sub, app_id + suffix)
            if not os.path.lexists(link):
                os.symlink(os.path.relpath(target, os.path.dirname(link)), link)

    def flatpak_uninstall(self, app_id):
        shutil.rmtree(os.path.join(self.flatpak, "app", app_id))
        for sub, suffix in (("applications", ".desktop"), ("icons/hicolor/128x128/apps", ".png")):
            os.unlink(os.path.join(self.exports, sub, app_id + suffix))

    # --- prejmenovani (puvodni chovani) ---
    def test_rename_without_flatpak(self):
        """Bez Flatpaku: jen prepis z rename.conf; chybejici aplikace se preskoci."""
        self.sync()
        self.assertEqual(self.listing(), ["thunar.desktop"])
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str
        cp.read(self.out("thunar.desktop"))
        self.assertEqual(cp["Desktop Entry"]["Name"], "Files")
        self.assertEqual(cp["Desktop Entry"]["Name[cs]"], "Soubory")
        self.assertEqual(cp["Desktop Entry"]["Icon"], "luxos-files")
        self.assertFalse(os.path.islink(self.out("thunar.desktop")))

    def test_rename_removed_when_app_uninstalled(self):
        self.sync()
        os.unlink(os.path.join(self.apps, "thunar.desktop"))
        self.sync()
        self.assertEqual(self.listing(), [])

    # --- Flathub ---
    def test_flatpak_app_linked_and_readable(self):
        self.flatpak_install("org.example.Editor", "Editor")
        self.sync()
        self.assertEqual(self.listing(), ["org.example.Editor.desktop", "thunar.desktop"])
        link = self.out("org.example.Editor.desktop")
        self.assertTrue(os.path.islink(link))
        # odkaz na export (ne primo na verzi aplikace) - aktualizace Flatpaku ho nemeni
        self.assertEqual(os.readlink(link), os.path.join(self.exports, "applications", "org.example.Editor.desktop"))
        with open(link) as f:
            self.assertIn("Name=Editor", f.read())

    def test_icons_resolve_through_hicolor_link(self):
        """GTK hleda <slozka XDG_DATA_DIRS>/icons/hicolor/...: ikona aplikace je pres odkaz dostupna,
        i ta nainstalovana az po vytvoreni odkazu."""
        self.sync()   # jeste bez Flatpaku: odkaz uz je (zatim na neexistujici slozku)
        hicolor = os.path.join(self.base, "icons", "hicolor")
        self.assertTrue(os.path.islink(hicolor))
        self.assertFalse(os.path.exists(hicolor))
        self.flatpak_install("org.example.Paint", "Paint")
        icon = os.path.join(hicolor, "128x128", "apps", "org.example.Paint.png")
        self.assertTrue(os.path.isfile(icon))
        self.sync()
        self.assertEqual(os.readlink(hicolor), os.path.join(self.exports, "icons", "hicolor"))

    def test_uninstall_removes_stale_link(self):
        self.flatpak_install("org.example.Editor", "Editor")
        self.flatpak_install("org.example.Paint", "Paint")
        self.sync()
        self.flatpak_uninstall("org.example.Editor")
        self.sync()
        self.assertEqual(self.listing(), ["org.example.Paint.desktop", "thunar.desktop"])
        # zadny rozbity odkaz
        for f in os.listdir(self.out()):
            self.assertTrue(os.path.exists(self.out(f)), f)

    def test_broken_export_skipped(self):
        """Export ukazujici na uz odebranou aplikaci (rozpracovane odebrani) se neprida."""
        self.flatpak_install("org.example.Editor", "Editor")
        shutil.rmtree(os.path.join(self.flatpak, "app", "org.example.Editor"))
        self.sync()
        self.assertEqual(self.listing(), ["thunar.desktop"])

    def test_update_keeps_link_unchanged(self):
        """flatpak update prepne current/active - odkaz zustava stejny (stejny inode, nabidka nic
        znovu nenacita) a ukazuje na novou verzi."""
        self.flatpak_install("org.example.Editor", "Editor")
        self.sync()
        before = os.lstat(self.out("org.example.Editor.desktop")).st_ino
        with open(os.path.join(self.flatpak, "app", "org.example.Editor", "current", "active", "export",
                               "share", "applications", "org.example.Editor.desktop"), "a") as f:
            f.write("Comment=v2\n")
        self.sync()
        self.assertEqual(os.lstat(self.out("org.example.Editor.desktop")).st_ino, before)
        with open(self.out("org.example.Editor.desktop")) as f:
            self.assertIn("Comment=v2", f.read())

    def test_rename_wins_over_flatpak_same_id(self):
        """Stejne desktop-id v rename.conf i z Flatpaku: prepis nazvu ma prednost (jeden soubor)."""
        self.flatpak_install("thunar", "Thunar Flatpak")
        self.sync()
        self.assertFalse(os.path.islink(self.out("thunar.desktop")))
        with open(self.out("thunar.desktop")) as f:
            self.assertIn("Name=Files", f.read())

    def test_no_duplicate_desktop_ids(self):
        """Odkaz ma stejne jmeno jako export: v XDG_DATA_DIRS (nase slozka i export) je to jedno
        desktop-id, takze nabidka/rofi/Launchpad ukazou aplikaci jen jednou (plati prvni slozka)."""
        self.flatpak_install("org.example.Editor", "Editor")
        self.sync()
        import importlib.util
        spec = importlib.util.spec_from_file_location("luxos_launchpad",
                                                      os.path.join(FILES, "python", "luxos_launchpad.py"))
        lp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lp)
        old = {k: os.environ.get(k) for k in ("XDG_DATA_DIRS", "XDG_DATA_HOME")}
        try:
            os.environ["XDG_DATA_HOME"] = os.path.join(self.tmp, "home-share")
            os.environ["XDG_DATA_DIRS"] = f"{self.base}:{self.exports}"
            apps = lp.desktop_apps()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual(sorted(apps), ["org.example.Editor.desktop", "thunar.desktop"])

    def test_idempotent_and_no_temp_files(self):
        self.flatpak_install("org.example.Editor", "Editor")
        self.sync()
        first = {f: os.lstat(self.out(f)).st_ino for f in os.listdir(self.out())}
        self.sync()
        second = {f: os.lstat(self.out(f)).st_ino for f in os.listdir(self.out())}
        self.assertEqual(first["org.example.Editor.desktop"], second["org.example.Editor.desktop"])
        self.assertFalse([f for f in os.listdir(self.out()) if f.startswith(".") or f.endswith(".tmp")])
        self.assertFalse([f for f in os.listdir(os.path.join(self.base, "icons")) if f.startswith(".")])

    def test_existing_real_hicolor_dir_not_replaced(self):
        os.makedirs(os.path.join(self.base, "icons", "hicolor", "keep"))
        self.sync()
        self.assertTrue(os.path.isdir(os.path.join(self.base, "icons", "hicolor", "keep")))

    def test_names_with_spaces_and_dashes(self):
        self.flatpak_install("com.example.My-App_2", "My App")
        self.sync()
        self.assertIn("com.example.My-App_2.desktop", self.listing())


class UnitFilesTest(unittest.TestCase):
    def test_path_unit(self):
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str
        cp.read(os.path.join(UNITS, "luxos-flatpak-apps.path"))
        self.assertEqual(cp["Path"]["PathChanged"], "/var/lib/flatpak/exports/share/applications")
        self.assertEqual(cp["Path"]["Unit"], "luxos-flatpak-apps.service")
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str
        cp.read(os.path.join(UNITS, "luxos-flatpak-apps.service"))
        self.assertEqual(cp["Service"]["Type"], "oneshot")
        self.assertEqual(cp["Service"]["ExecStart"], "/usr/lib/luxos/luxos-apps-sync")

    def test_units_verify(self):
        if not shutil.which("systemd-analyze"):
            self.skipTest("systemd-analyze missing")
        with tempfile.TemporaryDirectory() as d:
            for u in ("luxos-flatpak-apps.path", "luxos-flatpak-apps.service"):
                shutil.copy(os.path.join(UNITS, u), d)
            r = subprocess.run(["systemd-analyze", "verify", "--man=no",
                                os.path.join(d, "luxos-flatpak-apps.path")],
                               capture_output=True, text=True, timeout=60)
            # chybejici /usr/lib/luxos/luxos-apps-sync mimo nainstalovany system neni chyba jednotky
            bad = [l for l in r.stderr.splitlines() if l.strip() and "luxos-apps-sync" not in l]
            self.assertEqual(bad, [], r.stderr)


if __name__ == "__main__":
    unittest.main()
