"""Testy nabidky LuxOS Recovery (bash, bez gum) se zastupnym luxos-care a souboru pro start
snimku a obnovy (hook libalpm, hook initramfs, jednotky systemd, GRUB).

    python3 -m unittest discover -s packages/luxos-care/tests -v
"""
import configparser
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
TUI = os.path.join(FILES, "recovery", "luxos-recovery")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")

FAKE_CARE = """#!/bin/bash
echo "$*" >>"$LOG"
case $1 in
  snapshots) printf '%s' "$SNAPS" ;;
  disk-check) [[ " $* " == *" --repair "* ]] && exit 0; exit ${CHECK_RC:-0} ;;
esac
exit 0
"""


class Tui(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-recovery-tui-")
        self.care = os.path.join(self.tmp, "luxos-care")
        with open(self.care, "w") as f:
            f.write(FAKE_CARE)
        os.chmod(self.care, 0o755)
        self.log = os.path.join(self.tmp, "log")
        snaps = [{"name": "2026-10-25_10-00-00", "label": "LuxOS (before update of 2026-10-25 10:00)"},
                 {"name": "2026-10-26_14-03-12", "label": "LuxOS (before update of 2026-10-26 14:03)"}]
        self.env = {"PATH": "/usr/bin:/bin", "LUXOS_CARE": self.care, "LOG": self.log, "LUXOS_RECOVERY_PLAIN": "1",
                    "LUXOS_RECOVERY_ONCE": "1", "LANG": "C.UTF-8", "SNAPS": json.dumps(snaps),
                    "LUXOS_RECOVERY_ROOT": self.tmp, "LUXOS_I18N_DIR": I18N}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_tui(self, keys, **env):
        r = subprocess.run(["bash", TUI], input=keys, env=dict(self.env, **env), capture_output=True, text=True,
                           timeout=30)
        return r.stdout + r.stderr

    def calls(self):
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def test_menu(self):
        out = self.run_tui("\n")
        for t in ("LuxOS Recovery", "Check the disk", "Restore a snapshot", "Reinstall LuxOS", "Shut down"):
            self.assertIn(t, out)
        self.assertEqual(self.calls(), [])

    def test_disk_check_ok_no_repair(self):
        self.run_tui("1\n\n")
        self.assertEqual(self.calls(), ["disk-check"])

    def test_disk_check_problems_repair_needs_yes(self):
        self.run_tui("1\nn\n\n", CHECK_RC="1")
        self.assertEqual(self.calls(), ["disk-check"])
        self.run_tui("1\ny\n\n", CHECK_RC="1")
        self.assertEqual(self.calls()[-1], "disk-check --repair")

    def test_rollback_newest_first_and_confirm(self):
        out = self.run_tui("2\n1\ny\n\n")
        self.assertLess(out.index("2026-10-26 14:03"), out.index("2026-10-25 10:00"))
        self.assertEqual(self.calls(), ["snapshots --json", "rollback 2026-10-26_14-03-12 --yes"])

    def test_rollback_declined(self):
        self.run_tui("2\n2\nn\n\n")
        self.assertEqual(self.calls(), ["snapshots --json"])
        self.run_tui("2\n3\n")                          # Zpet
        self.assertEqual(self.calls(), ["snapshots --json"] * 2)

    def test_reinstall_needs_typed_word(self):
        self.run_tui("3\nyes\n\n", LUXOS_RECOVERY_NET="0")
        self.assertEqual(self.calls(), [])
        self.run_tui("3\nREINSTALL\n\n", LUXOS_RECOVERY_NET="0")
        self.assertEqual(self.calls(), ["reinstall --yes"])

    @unittest.skipUnless(os.path.exists("/usr/lib/luxos/i18n.sh"), "needs luxos-i18n")
    def test_czech_from_locale_conf(self):
        """Jazyk z /etc/locale.conf (sluzba ho nedostane v prostredi), cesky potvrzovaci text."""
        os.makedirs(os.path.join(self.tmp, "etc"))
        with open(os.path.join(self.tmp, "etc", "locale.conf"), "w") as f:
            f.write("LANG=cs_CZ.UTF-8\n")
        out = self.run_tui("3\nPŘEINSTALOVAT\n\n", LANG="C", LUXOS_RECOVERY_NET="0")
        self.assertIn("Přeinstalovat LuxOS", out)
        self.assertEqual(self.calls(), ["reinstall --yes"])

    def test_system_fix(self):
        """Oprava nastaveni podle /etc/luxos/system.lsl: lux system fix (ten sam ukaze rozdil a zepta se)."""
        fake = os.path.join(self.tmp, "lux_system.py")
        with open(fake, "w") as f:
            f.write('#!/bin/bash\necho "lux_system $*" >>"$LOG"\n')
        os.chmod(fake, 0o755)
        out = self.run_tui("4\n\n", LUXOS_LUX_SYSTEM=fake)
        self.assertIn("no system configuration file", out)
        self.assertEqual(self.calls(), [])
        os.makedirs(os.path.join(self.tmp, "etc", "luxos"))
        open(os.path.join(self.tmp, "etc", "luxos", "system.lsl"), "w").close()
        self.run_tui("4\n\n", LUXOS_LUX_SYSTEM=fake)
        self.assertEqual(self.calls(), ["lux_system fix"])

    def test_reinstall_offline_cancelled(self):
        self.run_tui("3\nREINSTALL\nn\n\n", LUXOS_RECOVERY_NET="1")
        self.assertEqual(self.calls(), [])


class Files(unittest.TestCase):
    def ini(self, path):
        c = configparser.ConfigParser(strict=False, interpolation=None, allow_no_value=True)
        c.optionxform = str
        with open(path) as f:
            c.read_string(f.read())
        return c

    def test_alpm_hook(self):
        c = self.ini(os.path.join(FILES, "hooks", "05-luxos-snapshot.hook"))
        self.assertEqual(c["Action"]["When"], "PreTransaction")
        self.assertEqual(c["Action"]["Exec"], "/usr/bin/luxos-care snapshot-pre")
        self.assertIn("AbortOnFail", open(os.path.join(FILES, "hooks", "05-luxos-snapshot.hook")).read())
        self.assertEqual(c["Trigger"]["Target"], "*")
        # pred hookem zalozniho jadra
        self.assertLess("05-luxos-snapshot.hook", "10-luxos-care-kernel-pre.hook")

    def test_care_units_skip_snapshot_boot(self):
        for u in ("luxos-care-update.service", "luxos-care-check.service", "luxos-care-boot.service"):
            with open(os.path.join(FILES, "systemd", u)) as f:
                self.assertIn("ConditionKernelCommandLine=!luxos.snapshot", f.read(), u)

    def test_recovery_units(self):
        t = self.ini(os.path.join(FILES, "systemd", "luxos-recovery.target"))
        self.assertIn("luxos-recovery.service", t["Unit"]["Requires"])
        self.assertEqual(t["Unit"]["AllowIsolate"], "yes")
        s = self.ini(os.path.join(FILES, "systemd", "luxos-recovery.service"))
        self.assertEqual(s["Service"]["ExecStart"], "/usr/lib/luxos/care/luxos-recovery")
        self.assertEqual(s["Service"]["TTYPath"], "/dev/tty1")

    def test_mkinitcpio_dropin(self):
        conf = os.path.join(FILES, "snapshot", "zz-luxos-snapshot.conf")
        for hooks, want in (("base systemd block filesystems", "base systemd block filesystems luxos-snapshot"),
                            ("base udev block filesystems", "base udev block filesystems"),
                            ("base systemd luxos-snapshot", "base systemd luxos-snapshot")):
            r = subprocess.run(["bash", "-c", f'HOOKS=({hooks}); . "{conf}"; echo "${{HOOKS[*]}}"'],
                               capture_output=True, text=True)
            self.assertEqual(r.stdout.strip(), want)

    def test_initcpio_hook_build(self):
        hook = os.path.join(FILES, "snapshot", "luxos-snapshot.initcpio")
        r = subprocess.run(["bash", "-c", f'add_module() {{ echo "module $1"; }}; '
                            f'add_systemd_unit() {{ echo "unit $1"; }}; . "{hook}"; build'],
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.split("\n")[:2], ["module overlay", "unit systemd-volatile-root.service"])

    def test_grub_script(self):
        r = subprocess.run(["sh", os.path.join(FILES, "grub", "12_luxos_snapshots")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn('source "${prefix}/luxos-snapshots.cfg"', r.stdout)

    def test_scripts_syntax(self):
        for p in (TUI, os.path.join(HERE, "..", "luxos-care.install")):
            self.assertEqual(subprocess.run(["bash", "-n", p]).returncode, 0, p)


if __name__ == "__main__":
    unittest.main()
