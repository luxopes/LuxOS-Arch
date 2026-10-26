"""Testy casti LuxOS Care v luxos-hub (files/lsl/luxos_care_hub.lsl) pro snimky systemu bez GUI:
upozorneni "LuxOS byl obnoven" a poznani startu ze snimku (luxos.snapshot= v /proc/cmdline),
upozorneni na zmenene systemove soubory (ochrana systemu).
Maly program v LSL nacte modul a vypise vysledky; prelozi se do docasneho adresare.

Spusteni: python3 -m unittest packages/luxos-desktop/tests/test_luxos_care_hub_snapshot.py -v
LUXOS_LSLC: prekladac lslc (LSL >= 0.10.6 s cilem linux-x86_64-gnu), jinak se testy preskoci.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LSL = os.path.join(HERE, "..", "files", "lsl")
I18N_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")

PROGRAM = """load env, json
load luxos_care_hub as care
print(care.booted_snapshot())
print(care.snapshot_date(care.booted_snapshot()))
n = care.notification_for({"kind": "rolled_back", "label": "LuxOS (before update of 2026-10-26 14:03)"})
print(n[0])
print(n[1])
print(len(n[2]))
n = care.notification_for({"kind": "integrity", "count": 3, "packages": ["coreutils"]})
print(n[0])
print(n[1])
print(n[2][0][0])
"""


def translation(key):
    with open(os.path.join(I18N_DIR, "cs.tsv"), encoding="utf-8") as f:
        for line in f:
            k, _, v = line.rstrip("\n").partition("\t")
            if k == key:
                return v
    return key


@unittest.skipUnless(LSLC, "chybi lslc")
class CareHubSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxos-carehub-")
        src = os.path.join(cls.tmp, "src")
        shutil.copytree(LSL, src)
        with open(os.path.join(src, "t.lsl"), "w") as f:
            f.write(PROGRAM)
        cls.bin = os.path.join(cls.tmp, "t")
        r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", os.path.join(src, "t.lsl"), cls.bin],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise unittest.SkipTest("lslc failed: " + r.stderr[-500:])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_prog(self, cmdline, lang="cs_CZ.UTF-8"):
        root = tempfile.mkdtemp(dir=self.tmp)
        os.makedirs(os.path.join(root, "proc"))
        with open(os.path.join(root, "proc", "cmdline"), "w") as f:
            f.write(cmdline + "\n")
        r = subprocess.run([self.bin], env={"LUXOS_CARE_ROOT": root, "LANG": lang, "LUXOS_I18N_DIR": I18N_DIR,
                                            "HOME": root, "PATH": "/usr/bin"},
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split("\n")

    def test_snapshot_boot(self):
        out = self.run_prog("root=UUID=x rw luxos.snapshot=2026-10-26_14-03-12 systemd.volatile=overlay")
        self.assertEqual(out[0], "2026-10-26_14-03-12")
        self.assertEqual(out[1], "2026-10-26 14:03")

    def test_normal_boot_and_rolled_back(self):
        out = self.run_prog("root=UUID=x rw quiet splash")
        self.assertEqual(out[0], "")
        self.assertEqual(out[2], translation("LuxOS was restored"))
        self.assertEqual(out[3], translation("LuxOS is back in the state: %s").replace(
            "%s", "LuxOS (before update of 2026-10-26 14:03)"))
        self.assertEqual(out[4], "0")
        self.assertNotEqual(translation("LuxOS was restored"), "LuxOS was restored")   # cesky preklad existuje

    def test_integrity_notification(self):
        """Zmenene systemove soubory (luxos-care verify --auto): upozorneni s tlacitkem Podrobnosti."""
        out = self.run_prog("root=UUID=x rw quiet splash")
        self.assertEqual(out[5], translation("System files were changed"))
        key = ("%d system files were changed or are missing. LuxOS can repair them by reinstalling "
               "the affected packages.")
        self.assertEqual(out[6], translation(key).replace("%d", "3"))
        self.assertEqual(out[7], "open")
        self.assertNotEqual(translation("System files were changed"), "System files were changed")


if __name__ == "__main__":
    unittest.main()
