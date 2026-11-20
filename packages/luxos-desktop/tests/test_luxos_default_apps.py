#!/usr/bin/env python3
"""LuxOS - vychozi aplikace pro PDF, obrazky a archivy (files/xdg/mimeapps.list) pres GIO jako v Souborech.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_default_apps.py -v

Falesne aplikace v docasnem XDG_DATA_DIRS: Firefox a PrismLauncher se v mimeinfo.cache hlasi k PDF a ZIP
drive nez prohlizec dokumentu a sprava archivu - vyhrat ma vychozi aplikace LuxOS.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MIMEAPPS = os.path.join(HERE, "..", "files", "xdg", "mimeapps.list")

APPS = {
    # drive v mimeinfo.cache (pred LuxOS aplikacemi)
    "firefox": "text/html;application/pdf;image/png;image/svg+xml;",
    "org.prismlauncher.PrismLauncher": "application/zip;application/x-modrinth-modpack+zip;",
    "org.gnome.Evince": "application/pdf;application/x-cbz;image/tiff;",
    "org.xfce.ristretto": "image/png;image/jpeg;image/tiff;image/svg+xml;image/webp;",
    "xarchiver": "application/zip;application/x-7z-compressed;application/x-compressed-tar;application/x-cbz;",
    # posta: LuxOS Mail (jen staging) a Evolution se v mimeinfo.cache hlasi drive nez Thunderbird
    "luxos-mail": "x-scheme-handler/mailto;message/rfc822;",
    "org.gnome.Evolution": "x-scheme-handler/mailto;message/rfc822;",
    "org.mozilla.Thunderbird": "message/rfc822;x-scheme-handler/mailto;text/calendar;",
}


class DefaultApps(unittest.TestCase):
    def defaults(self, apps, types, user=""):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, data, bindir = (os.path.join(tmp, d) for d in ("xdg", "data", "bin"))
            os.makedirs(os.path.join(data, "applications"))
            os.makedirs(cfg)
            os.makedirs(bindir)
            shutil.copy(MIMEAPPS, cfg)
            cache = {}
            for app in apps:
                exe = app.rsplit(".", 1)[-1].lower()
                with open(os.path.join(bindir, exe), "w") as f:
                    f.write("#!/bin/sh\n")
                os.chmod(os.path.join(bindir, exe), 0o755)
                with open(os.path.join(data, "applications", app + ".desktop"), "w") as f:
                    f.write(f"[Desktop Entry]\nType=Application\nName={app}\nExec={exe} %F\nMimeType={APPS[app]}\n")
                for t in APPS[app].strip(";").split(";"):
                    cache.setdefault(t, []).append(app + ".desktop")
            with open(os.path.join(data, "applications", "mimeinfo.cache"), "w") as f:
                f.write("[MIME Cache]\n" + "".join(f"{t}={';'.join(a)};\n" for t, a in cache.items()))
            if user:
                os.makedirs(os.path.join(tmp, "home-config"))
                with open(os.path.join(tmp, "home-config", "mimeapps.list"), "w") as f:
                    f.write(user)
            env = dict(os.environ, PATH=bindir + ":/usr/bin", XDG_CONFIG_DIRS=cfg, XDG_DATA_DIRS=data,
                       XDG_CONFIG_HOME=os.path.join(tmp, "home-config"), XDG_DATA_HOME=os.path.join(tmp, "home-data"),
                       XDG_CURRENT_DESKTOP="XFCE")
            code = ("import sys, gi; gi.require_version('Gio', '2.0'); from gi.repository import Gio\n"
                    "for t in sys.argv[1:]:\n"
                    "    a = Gio.AppInfo.get_default_for_type(t, False)\n"
                    "    print(t, a.get_id() if a else None)\n")
            out = subprocess.run(["python3", "-c", code, *types], env=env, capture_output=True, text=True,
                                 timeout=30).stdout
            return dict(line.split(" ", 1) for line in out.splitlines())

    def test_luxos_viewers_win_over_earlier_handlers(self):
        got = self.defaults(list(APPS), ["application/pdf", "application/x-cbz", "image/png", "image/svg+xml",
                                         "image/tiff", "application/zip", "application/x-compressed-tar",
                                         "text/html"])
        self.assertEqual(got["application/pdf"], "org.gnome.Evince.desktop")
        self.assertEqual(got["application/x-cbz"], "org.gnome.Evince.desktop")
        self.assertEqual(got["image/png"], "org.xfce.ristretto.desktop")
        self.assertEqual(got["image/svg+xml"], "org.xfce.ristretto.desktop")
        self.assertEqual(got["image/tiff"], "org.xfce.ristretto.desktop")
        self.assertEqual(got["application/zip"], "xarchiver.desktop")
        self.assertEqual(got["application/x-compressed-tar"], "xarchiver.desktop")
        self.assertEqual(got["text/html"], "firefox.desktop")       # prohlizec nastavuje luxos-new-user-defaults

    def test_missing_default_app_falls_back(self):
        # bez prohlizece dokumentu se PDF otevre v tom, co je k dispozici (ne "zadna aplikace")
        got = self.defaults(["firefox", "org.xfce.ristretto"], ["application/pdf", "image/png"])
        self.assertEqual(got["application/pdf"], "firefox.desktop")
        self.assertEqual(got["image/png"], "org.xfce.ristretto.desktop")

    def test_thunderbird_is_default_mail_app(self):
        got = self.defaults(list(APPS), ["x-scheme-handler/mailto", "message/rfc822"])
        self.assertEqual(got["x-scheme-handler/mailto"], "org.mozilla.Thunderbird.desktop")
        self.assertEqual(got["message/rfc822"], "org.mozilla.Thunderbird.desktop")

    def test_user_mail_choice_wins(self):
        user = "[Default Applications]\nx-scheme-handler/mailto=luxos-mail.desktop;\n"
        got = self.defaults(list(APPS), ["x-scheme-handler/mailto", "message/rfc822"], user)
        self.assertEqual(got["x-scheme-handler/mailto"], "luxos-mail.desktop")
        self.assertEqual(got["message/rfc822"], "org.mozilla.Thunderbird.desktop")

    def test_mail_without_thunderbird_falls_back(self):
        # stavajici instalace bez Thunderbirdu: jina nainstalovana postovni aplikace, ne mrtvy odkaz
        got = self.defaults(["firefox", "luxos-mail"], ["x-scheme-handler/mailto"])
        self.assertEqual(got["x-scheme-handler/mailto"], "luxos-mail.desktop")
        got = self.defaults(["firefox"], ["x-scheme-handler/mailto"])
        self.assertEqual(got["x-scheme-handler/mailto"], "None")

    def test_dock_has_no_mail_launcher(self):
        """Thunderbird neni zavislost luxos-desktop: vychozi Dock na nej (ani na LuxOS Mail) nesmi ukazovat,
        jinak by na stavajicich instalacich zustala mrtva ikona."""
        with open(os.path.join(HERE, "..", "files", "dconf", "10-luxos"), encoding="utf-8") as f:
            items = [l for l in f if l.startswith("dock-items=")]
        self.assertTrue(items)
        for item in items:
            self.assertNotIn("Thunderbird", item)
            self.assertNotIn("thunderbird", item)
            self.assertNotIn("luxos-mail", item)
        with open(os.path.join(HERE, "..", "PKGBUILD"), encoding="utf-8") as f:
            pkgbuild = f.read()
        deps = pkgbuild.split("depends=(", 1)[1].split("\n)", 1)[0]
        self.assertNotRegex(deps, r"(?m)^[^#]*\bthunderbird\b")
        optdeps = pkgbuild.split("\noptdepends=(", 1)[1].split("\n\n", 1)[0]
        self.assertIn("'thunderbird: ", optdeps)

    def test_launcher_names_localized(self):
        """Kalkulacka, Hodiny a Obchod maji v Launchpadu a Docku nazev i popis ve vsech 12 jazycich."""
        root = os.path.join(HERE, "..", "..")
        for path in ("luxos-desktop/files/applications/luxos-calculator.desktop",
                     "luxos-desktop/files/applications/luxos-clock-app.desktop",
                     "luxos-store/files/luxos-store.desktop"):
            with open(os.path.join(root, path), encoding="utf-8") as f:
                keys = dict(line.rstrip("\n").split("=", 1) for line in f if "=" in line and not line.startswith("#"))
            for lang in ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv"):
                for key in ("Name", "Comment"):
                    self.assertTrue(keys.get(f"{key}[{lang}]"), f"{path}: {key}[{lang}]")
            self.assertNotEqual(keys["Comment[de]"], keys["Comment"], path)

    def test_default_apps_are_dependencies(self):
        with open(os.path.join(HERE, "..", "PKGBUILD"), encoding="utf-8") as f:
            deps = f.read().split("depends=(", 1)[1].split("\n)", 1)[0]
        for pkg in ("evince", "ristretto", "xarchiver"):
            self.assertRegex(deps, rf"(?m)^[^#]*\b{pkg}\b")


if __name__ == "__main__":
    unittest.main()
