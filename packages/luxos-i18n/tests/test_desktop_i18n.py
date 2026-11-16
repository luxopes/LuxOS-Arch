#!/usr/bin/env python3
"""desktop-i18n.py: Name/GenericName/Comment v .desktop ve vsech 12 jazycich z tabulek (pri sestaveni).
Regrese (audit 1.0.2): nastaveni LuxOS (Vzhled, O tomto pocitaci, Baterie, Monitor...) mela jen Name[cs],
Launchpad v ostatnich 10 jazycich ukazoval anglictinu.
    python3 packages/luxos-i18n/tests/test_desktop_i18n.py"""
import glob
import importlib.util
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
TOOL = os.path.join(FILES, "desktop-i18n.py")
PK = os.path.join(HERE, "..", "..")
spec = importlib.util.spec_from_file_location("desktop_i18n", TOOL)
di = importlib.util.module_from_spec(spec)
spec.loader.exec_module(di)

# soubory, ktere balicky pri sestaveni prekladaji (PKGBUILD luxos-desktop, luxos-care, luxos-installer)
BUILT = (glob.glob(os.path.join(PK, "luxos-desktop/files/applications/*.desktop"))
         + glob.glob(os.path.join(PK, "luxos-desktop/files/screensaver/*.desktop"))
         + glob.glob(os.path.join(PK, "luxos-desktop/files/panel-plugins/*.desktop"))
         + [os.path.join(PK, "luxos-care/files/luxos-update.desktop"),
            os.path.join(PK, "luxos-installer/files/luxos-install.desktop"),
            os.path.join(PK, "luxos-installer/files/luxos-oem-seal.desktop")])


class DesktopI18n(unittest.TestCase):
    tabs = {"cs": {"Battery & Power": "Baterie a napájení", "Battery level": "Stav baterie", "Open": "Otevřít"},
            "de": {"Battery & Power": "Batterie & Energie", "Open": "Öffnen"}}

    def test_adds_missing_and_keeps_manual(self):
        src = ("[Desktop Entry]\nType=Application\nName=Battery & Power\nName[cs]=Ručně\n"
               "Comment=Battery level\nExec=x\n\n[Desktop Action open]\nName=Open\n")
        out = di.translate(src, self.tabs)
        self.assertIn("Name[cs]=Ručně\n", out)                  # rucni preklad zustava
        self.assertNotIn("Name[cs]=Baterie a napájení", out)
        self.assertIn("Name[de]=Batterie & Energie\n", out)
        self.assertIn("Comment[cs]=Stav baterie\n", out)
        self.assertNotIn("Comment[de]", out)                    # bez prekladu nic
        self.assertIn("[Desktop Action open]\nName=Open\nName[cs]=Otevřít\nName[de]=Öffnen\n", out)
        self.assertEqual(di.translate(out, self.tabs), out)     # podruhe beze zmeny

    def test_other_keys_untouched(self):
        src = "[Desktop Entry]\nName=Open\nExec=Open\nKeywords=Open;\n"
        out = di.translate(src, self.tabs)
        self.assertIn("Exec=Open\nKeywords=Open;\n", out)
        self.assertNotIn("Exec[cs]", out)

    def test_all_built_desktop_files_translated(self):
        r = subprocess.run([sys.executable, TOOL, "--check", FILES] + BUILT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, "texts without translation (add them to the tsv):\n" + r.stdout)

    def test_pkgbuilds_run_the_tool(self):
        for pkg in ("luxos-desktop", "luxos-care", "luxos-installer"):
            with open(os.path.join(PK, pkg, "PKGBUILD"), encoding="utf-8") as f:
                self.assertIn('desktop-i18n.py" "$i18n"', f.read(), pkg)


if __name__ == "__main__":
    unittest.main()
