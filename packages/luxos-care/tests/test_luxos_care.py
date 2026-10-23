"""Testy rozhodovaci logiky LuxOS Care (bez rootu, bez zasahu do systemu: vse v docasnem koreni).

    python3 -m unittest discover -s packages/luxos-care/tests -v
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
sys.path.insert(0, FILES)
# luxos_i18n (balik luxos-i18n) - pri testech z repozitare
sys.path.insert(0, os.path.join(HERE, "..", "..", "luxos-i18n", "files"))

import luxos_care as care  # noqa: E402


class Root(unittest.TestCase):
    """Docasny koren pro cesty P(...)."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="luxos-care-test-")
        self._old = care.ROOT
        care.ROOT = self.root

    def tearDown(self):
        care.ROOT = self._old
        shutil.rmtree(self.root, ignore_errors=True)

    def w(self, path, text=""):
        p = self.root + path
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        return p

    def r(self, path):
        with open(self.root + path) as f:
            return f.read()

    def snapshot(self, base):
        out = {}
        for d, _s, files in os.walk(self.root + base):
            for f in files:
                p = os.path.join(d, f)
                with open(p, "rb") as fh:
                    out[p[len(self.root):]] = hashlib.sha256(fh.read()).hexdigest()
        return out


# ---- podminky ---------------------------------------------------------------------------
class Conditions(unittest.TestCase):
    def test_battery(self):
        self.assertEqual(care.battery_ok(None, []), (True, ""))                       # desktop
        self.assertEqual(care.battery_ok(True, [(10, "Charging")]), (True, ""))
        self.assertEqual(care.battery_ok(False, [(39, "Discharging")]), (False, "battery"))
        self.assertEqual(care.battery_ok(False, [(40, "Discharging")]), (True, ""))
        self.assertEqual(care.battery_ok(None, [(15, "Charging")]), (True, ""))        # USB-C bez Mains
        self.assertEqual(care.battery_ok(False, [(15, "Charging")]), (False, "battery"))
        self.assertEqual(care.battery_ok(False, [(80, "Discharging"), (10, "Discharging")]), (True, ""))
        self.assertEqual(care.battery_ok(False, [(30, "Discharging"), (20, "Discharging")]), (False, "battery"))

    def test_metered_values(self):
        self.assertEqual(care.metered_value("u 1"), "yes")
        self.assertEqual(care.metered_value("u 3"), "yes")       # guess-yes (hotspot z telefonu)
        self.assertEqual(care.metered_value("u 2"), "no")
        self.assertEqual(care.metered_value("u 4"), "no")
        self.assertEqual(care.metered_value("u 0"), "unknown")
        self.assertEqual(care.metered_value("yes"), "yes")
        self.assertEqual(care.metered_value("yes (guessed)"), "yes")
        self.assertEqual(care.metered_value("no (guessed)"), "no")
        self.assertEqual(care.metered_value("unknown"), "unknown")
        self.assertEqual(care.metered_value(""), "unknown")

    def test_conditions(self):
        good = {"metered": "no", "connectivity": "full", "ac": True, "batteries": [(90, "Full")]}
        self.assertEqual(care.conditions_ok(good), (True, ""))
        self.assertEqual(care.conditions_ok(dict(good, metered="yes")), (False, "metered"))
        self.assertEqual(care.conditions_ok(dict(good, metered="unknown")), (True, ""))
        for c in ("none", "limited", "portal"):
            self.assertEqual(care.conditions_ok(dict(good, connectivity=c)), (False, "offline"))
            self.assertEqual(care.conditions_ok(dict(good, connectivity=c), manual=True), (False, "offline"))
        low = dict(good, ac=False, batteries=[(25, "Discharging")])
        self.assertEqual(care.conditions_ok(low), (False, "battery"))
        # rucni aktualizace: uzivatel rozhodl (merene pripojeni i baterie)
        self.assertEqual(care.conditions_ok(dict(low, metered="yes"), manual=True), (True, ""))
        # metered ma prednost pred baterii v duvodu
        self.assertEqual(care.conditions_ok(dict(low, metered="yes")), (False, "metered"))
        # Sporic baterie: automaticky jen s nabijeckou (i pri dost nabite baterii)
        full_bat = dict(good, ac=False, batteries=[(90, "Discharging")])
        self.assertEqual(care.conditions_ok(full_bat), (True, ""))
        self.assertEqual(care.conditions_ok(dict(full_bat, powersaver=True)), (False, "battery"))
        self.assertEqual(care.conditions_ok(dict(good, powersaver=True)), (True, ""))
        self.assertEqual(care.conditions_ok(dict(good, ac=None, batteries=[(50, "Charging")], powersaver=True)),
                         (True, ""))
        self.assertEqual(care.conditions_ok(dict(good, batteries=[], ac=None, powersaver=True)), (True, ""))
        self.assertEqual(care.conditions_ok(dict(full_bat, powersaver=True), manual=True), (True, ""))

    def test_backoff_and_due(self):
        self.assertEqual(care.backoff(0), 0)
        self.assertEqual(care.backoff(1), 3600)
        self.assertEqual(care.backoff(2), 7200)
        self.assertEqual(care.backoff(3), 14400)
        self.assertEqual(care.backoff(10), 24 * 3600)
        t = 1_000_000
        self.assertTrue(care.update_due({}, t))
        self.assertFalse(care.update_due({"last_success": t - 3600}, t))
        self.assertTrue(care.update_due({"last_success": t - 21 * 3600}, t))
        self.assertFalse(care.update_due({"last_success": 0, "next_attempt": t + 10}, t))
        self.assertTrue(care.update_due({"last_success": 0, "next_attempt": t - 10}, t))


class PowerSysfs(Root):
    def ps(self, name, **kv):
        for k, v in kv.items():
            self.w(f"/sys/class/power_supply/{name}/{k}", v + "\n")

    def test_laptop_on_battery(self):
        self.ps("AC", type="Mains", online="0")
        self.ps("BAT0", type="Battery", capacity="35", status="Discharging")
        self.ps("hidpp_battery_0", type="Battery", capacity="5", status="Discharging", scope="Device")
        ac, bats = care.power_supplies()
        self.assertEqual(ac, False)
        self.assertEqual(bats, [(35, "Discharging")])        # baterie mysi se nepocita
        self.assertEqual(care.battery_ok(ac, bats), (False, "battery"))

    def test_laptop_charging(self):
        self.ps("ADP1", type="Mains", online="1")
        self.ps("BAT0", type="Battery", capacity="12", status="Charging")
        self.assertEqual(care.battery_ok(*care.power_supplies()), (True, ""))

    def test_desktop(self):
        self.assertEqual(care.power_supplies(), (None, []))


# ---- pacman -----------------------------------------------------------------------------
class Pacman(unittest.TestCase):
    def test_stale_lock(self):
        self.assertTrue(care.stale_lock(True, False, 600))
        self.assertFalse(care.stale_lock(True, True, 6000))       # pacman bezi
        self.assertFalse(care.stale_lock(True, False, 30))        # cerstvy zamek
        self.assertFalse(care.stale_lock(False, False, 6000))

    def test_errors(self):
        self.assertEqual(care.classify_pacman_error("error: failed to init transaction (unable to lock database)"),
                         "locked")
        self.assertEqual(care.classify_pacman_error("error: foo: signature from \"X\" is unknown trust"), "keyring")
        self.assertEqual(care.classify_pacman_error("error: failed retrieving file 'core.db'"), "network")
        self.assertEqual(care.classify_pacman_error("a: /usr/bin/x exists in filesystem\nconflicting files"), "conflict")
        self.assertEqual(care.classify_pacman_error("error: Partition / too full: not enough free disk space"), "disk")
        self.assertEqual(care.classify_pacman_error("something odd"), "unknown")

    def test_interrupted(self):
        ok = ["[x] [ALPM] transaction started\n", "[x] [ALPM] upgraded a\n", "[x] [ALPM] transaction completed\n"]
        self.assertFalse(care.interrupted_transaction(ok))
        self.assertTrue(care.interrupted_transaction(ok + ["[y] [ALPM] transaction started\n", "[y] [ALPM] upgraded b\n"]))
        self.assertFalse(care.interrupted_transaction(ok + ["[y] [ALPM] transaction started\n",
                                                            "[y] [ALPM] transaction failed\n"]))
        self.assertFalse(care.interrupted_transaction([]))


class Mode(Root):
    def test_default_and_switch(self):
        self.assertEqual(care.mode(), "carefree")                 # soubor chybi
        self.w("/etc/luxos/care.conf", "# installer\nMODE=classic\nOTHER=1\n")
        self.assertEqual(care.mode(), "classic")
        care.set_mode("carefree")
        text = self.r("/etc/luxos/care.conf")
        self.assertIn("MODE=carefree", text)
        self.assertIn("OTHER=1", text)
        self.assertIn("# installer", text)
        self.assertEqual(text.count("MODE="), 1)
        self.w("/etc/luxos/care.conf", "MODE=bogus\n")
        self.assertEqual(care.mode(), "carefree")
        with self.assertRaises(ValueError):
            care.set_mode("rm -rf /")


# ---- zalozni jadro ----------------------------------------------------------------------
class KeepChoice(unittest.TestCase):
    def test_choose(self):
        # nabehlo nove jadro N (good=N), aktualizace N -> M: ponechat N
        self.assertEqual(care.choose_keep(["6.10.1-zen1-1-zen"], "6.10.1-zen1-1-zen", False), "6.10.1-zen1-1-zen")
        # N nikdy nenabehlo (good = zalozni P je k dispozici): N se nezachova, P zustava
        self.assertIsNone(care.choose_keep(["6.10.1-zen1-1-zen"], "6.9.9-zen1-1-zen", True))
        # zadna informace o startu (cerstva instalace): odebirane jadro
        self.assertEqual(care.choose_keep(["6.10.1-zen1-1-zen"], "", False), "6.10.1-zen1-1-zen")
        # good uz neexistuje: odebirane jadro
        self.assertEqual(care.choose_keep(["6.10.1-zen1-1-zen"], "6.1-old", False), "6.10.1-zen1-1-zen")
        self.assertIsNone(care.choose_keep([], "x", False))

    def test_targets(self):
        t = ["usr/lib/modules/6.10.1-zen1-1-zen/vmlinuz", "usr/lib/modules/6.10.1-zen1-1-zen/vmlinuz",
             "usr/src/nvidia-560/dkms.conf", "/usr/lib/modules/6.9-x/vmlinuz", "usr/lib/modules/a/b/vmlinuz"]
        self.assertEqual(care.versions_from_targets(t), ["6.10.1-zen1-1-zen", "6.9-x"])

    def test_entry_names(self):
        self.assertEqual(care.entry_tries("luxos+3.conf"), (3, 0))
        self.assertEqual(care.entry_tries("luxos+0-3.conf"), (0, 3))
        self.assertEqual(care.entry_tries("luxos.conf"), (None, None))
        self.assertEqual(care.entry_id("luxos+2-1.conf"), "luxos.conf")
        self.assertEqual(care.entry_id("luxos-ab12+3.conf"), "luxos-ab12.conf")


MAIN_ENTRY = """title   LuxOS
linux   /vmlinuz-linux-zen
initrd  /initramfs-linux-zen.img
options root=UUID=1234 rw rootflags=subvol=@ quiet splash
"""
ERASE_LOADER = "default luxos.conf\ntimeout 0\nconsole-mode max\neditor no\n"


class BootLayouts(Root):
    VER = "6.10.1-zen1-1-zen"

    def kernel(self, ver, owned_pkgbase=False):
        self.w(f"/usr/lib/modules/{ver}/vmlinuz", "KERNEL " + ver)
        self.w(f"/usr/lib/modules/{ver}/kernel/x.ko", "mod")
        if owned_pkgbase:
            self.w(f"/usr/lib/modules/{ver}/pkgbase", "linux-zen\n")
        self.w(f"/var/lib/luxos-care/kernel/initramfs-{ver}.img", "INITRD " + ver)

    def test_erase_install(self):
        """(a) cely disk: ESP v /boot, loader.conf od instalatoru -> automaticky navrat."""
        self.w("/boot/loader/loader.conf", ERASE_LOADER)
        self.w("/boot/loader/entries/luxos.conf", MAIN_ENTRY)
        self.w("/boot/loader/entries/luxos-fallback.conf", MAIN_ENTRY.replace("initramfs-linux-zen.img",
                                                                               "initramfs-linux-zen-fallback.img"))
        self.kernel(self.VER)
        lay = care.detect_layout()
        self.assertEqual(lay["kind"], "sdboot")
        self.assertTrue(lay["loader_owned"])
        self.assertEqual(lay["prev_vmlinuz"], "/boot/vmlinuz-linux-zen-prev")
        ok, why = care.install_prev_boot(lay, self.VER)
        self.assertTrue(ok, why)
        prev = self.r("/boot/loader/entries/luxos-prev.conf")
        self.assertIn("title   LuxOS (previous kernel)", prev)
        self.assertIn("linux   /vmlinuz-linux-zen-prev", prev)
        self.assertIn("initrd  /initramfs-linux-zen-prev.img", prev)
        self.assertIn("options root=UUID=1234 rw rootflags=subvol=@ quiet splash", prev)
        self.assertIn(f"version {self.VER}", prev)
        self.assertIn("sort-key luxos-prev", prev)
        self.assertEqual(self.r("/boot/vmlinuz-linux-zen-prev"), "KERNEL " + self.VER)
        self.assertEqual(self.r("/boot/initramfs-linux-zen-prev.img"), "INITRD " + self.VER)
        self.assertIn("sort-key luxos\n", self.r("/boot/loader/entries/luxos.conf"))
        loader = self.r("/boot/loader/loader.conf")
        self.assertIn("default luxos*", loader)
        self.assertNotIn("default luxos.conf", loader)
        self.assertIn("timeout 0", loader)
        # vzor default luxos* + sort-key: pri vadne hlavni polozce (+0-3, razena na konec) vybere zalozni
        self.assertTrue(care.loader_owned("/boot", "luxos"))            # znacka -> stale vlastni
        care.install_prev_boot(care.detect_layout(), self.VER)          # idempotentni
        self.assertEqual([ln for ln in self.r("/boot/loader/loader.conf").splitlines() if ln.startswith("default")],
                         ["default luxos*"])
        # pokusy noveho jadra
        lay = care.detect_layout()
        self.assertTrue(care.arm_trial(lay))
        self.assertTrue(os.path.exists(self.root + "/boot/loader/entries/luxos+3.conf"))
        self.assertFalse(os.path.exists(self.root + "/boot/loader/entries/luxos.conf"))
        os.rename(self.root + "/boot/loader/entries/luxos+3.conf", self.root + "/boot/loader/entries/luxos+0-3.conf")
        self.assertTrue(care.main_entry_bad())
        care.reset_trial()
        self.assertTrue(os.path.exists(self.root + "/boot/loader/entries/luxos+3.conf"))
        self.assertFalse(care.main_entry_bad())
        # odebrani zalozniho: jen vlastni soubory
        care.remove_prev_boot(care.detect_layout())
        self.assertFalse(os.path.exists(self.root + "/boot/loader/entries/luxos-prev.conf"))
        self.assertFalse(os.path.exists(self.root + "/boot/vmlinuz-linux-zen-prev"))
        self.assertTrue(os.path.exists(self.root + "/boot/loader/entries/luxos-fallback.conf"))

    def test_shared_esp_foreign_loader(self):
        """(d) notebook uzivatele: ESP v /boot sdileny s Kali, loader.conf patri Kali."""
        kali_loader = "default kali.conf\ntimeout 5\n"
        self.w("/boot/loader/loader.conf", kali_loader)
        self.w("/boot/loader/entries/kali.conf", "title Kali\nlinux /kali/vmlinuz\n")
        self.w("/boot/loader/entries/luxos.conf", MAIN_ENTRY)
        self.w("/boot/loader/entries/luxos-fallback.conf", MAIN_ENTRY)
        self.w("/boot/EFI/systemd/systemd-bootx64.efi", "kali sd-boot")
        self.w("/boot/kali/vmlinuz", "kali kernel")
        self.kernel(self.VER)
        before = self.snapshot("/boot")
        lay = care.detect_layout()
        self.assertEqual(lay["kind"], "sdboot")
        self.assertFalse(lay["loader_owned"])
        ok, why = care.install_prev_boot(lay, self.VER)
        self.assertTrue(ok, why)
        after = self.snapshot("/boot")
        added = set(after) - set(before)
        changed = {k for k in before if before[k] != after.get(k)}
        self.assertEqual(added, {"/boot/loader/entries/luxos-prev.conf", "/boot/vmlinuz-linux-zen-prev",
                                 "/boot/initramfs-linux-zen-prev.img"})
        self.assertEqual(changed, set())                       # zadny cizi ani instalatoruv soubor
        self.assertNotIn("sort-key", self.r("/boot/loader/entries/luxos-prev.conf"))
        self.assertEqual(self.r("/boot/loader/loader.conf"), kali_loader)
        care.arm_trial(care.detect_layout())                   # jen vlastni polozka
        self.assertEqual(sorted(os.listdir(self.root + "/boot/loader/entries")),
                         ["kali.conf", "luxos+3.conf", "luxos-fallback.conf", "luxos-prev.conf"])
        # vynucene zalozni: cizi loader.conf se neupravuje -> jednorazove pres bootctl
        care.kwrite("prev", self.VER)
        with mock.patch.object(care, "have", return_value=True), \
                mock.patch.object(care, "run", return_value=(0, "")) as run:
            ok, _o = care.use_previous_kernel()
        self.assertTrue(ok)
        run.assert_called_with(["bootctl", "set-oneshot", "luxos-prev.conf"], timeout=30)
        self.assertEqual(self.r("/boot/loader/loader.conf"), kali_loader)

    def test_freespace(self):
        """(b) sdileny ESP s Windows v /efi, jadro v EFI/LuxOS/<id> (luxos-esp-sync)."""
        self.w("/etc/luxos/esp.conf", "ESP_DIR=/efi/EFI/LuxOS/ab12cd\nKERNEL=linux-zen\n")
        self.w("/efi/loader/loader.conf", "default luxos-ab12cd.conf\ntimeout 3\nconsole-mode max\neditor no\n")
        self.w("/efi/loader/entries/luxos-ab12cd.conf",
               "title   LuxOS\nlinux   /EFI/LuxOS/ab12cd/vmlinuz-linux-zen\n"
               "initrd  /EFI/LuxOS/ab12cd/initramfs-linux-zen.img\noptions root=UUID=9 rw\n")
        self.w("/efi/EFI/Microsoft/Boot/bootmgfw.efi", "windows")
        self.kernel(self.VER)
        before = self.snapshot("/efi/EFI/Microsoft")
        lay = care.detect_layout()
        self.assertEqual(lay["kind"], "sdboot")
        self.assertTrue(lay["freespace"])
        self.assertTrue(lay["loader_owned"])
        self.assertEqual(lay["prev_vmlinuz"], "/efi/EFI/LuxOS/ab12cd/vmlinuz-linux-zen-prev")
        ok, why = care.install_prev_boot(lay, self.VER)
        self.assertTrue(ok, why)
        prev = self.r("/efi/loader/entries/luxos-ab12cd-prev.conf")
        self.assertIn("linux   /EFI/LuxOS/ab12cd/vmlinuz-linux-zen-prev", prev)
        self.assertIn("initrd  /EFI/LuxOS/ab12cd/initramfs-linux-zen-prev.img", prev)
        self.assertIn("default luxos-ab12cd*", self.r("/efi/loader/loader.conf"))
        self.assertEqual(before, self.snapshot("/efi/EFI/Microsoft"))
        care.arm_trial(care.detect_layout())
        self.assertTrue(os.path.exists(self.root + "/efi/loader/entries/luxos-ab12cd+3.conf"))
        # jine nez instalatorovo loader.conf (napr. upravene uzivatelem) se nepovazuje za vlastni
        self.w("/efi/loader/loader.conf", "default @saved\ntimeout 3\n")
        self.assertFalse(care.detect_layout()["loader_owned"])

    def test_esp_full(self):
        self.w("/boot/loader/loader.conf", ERASE_LOADER)
        self.w("/boot/loader/entries/luxos.conf", MAIN_ENTRY)
        self.kernel(self.VER)
        with mock.patch.object(care, "free_bytes", return_value=1024):
            ok, why = care.install_prev_boot(care.detect_layout(), self.VER)
        self.assertEqual((ok, why), (False, "esp_full"))
        self.assertFalse(os.path.exists(self.root + "/boot/loader/entries/luxos-prev.conf"))

    def test_grub(self):
        self.w("/boot/grub/grub.cfg", "### BEGIN /etc/grub.d/10_linux ###\n")
        self.kernel(self.VER)
        lay = care.detect_layout()
        self.assertEqual(lay["kind"], "grub")
        calls = []
        with mock.patch.object(care, "have", return_value=True), \
                mock.patch.object(care, "run", side_effect=lambda c, **k: (calls.append(c), (0, ""))[1]):
            ok, why = care.install_prev_boot(lay, self.VER)
            self.assertTrue(ok, why)
            self.assertTrue(care.arm_trial(lay))
        self.assertEqual(self.r("/boot/luxos-prev/vmlinuz"), "KERNEL " + self.VER)
        self.assertIn(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"], calls)
        self.assertIn(["grub-editenv", "/boot/grub/grubenv", "set", "luxos_tries=3"], calls)

    def test_no_bootloader(self):
        self.kernel(self.VER)
        self.assertEqual(care.install_prev_boot(care.detect_layout(), self.VER), (False, "no_bootloader"))


class KernelHooks(Root):
    """Pre/post hook na falesnem koreni (pacman je nahrazen)."""
    OLD, NEW = "6.10.1-zen1-1-zen", "6.10.2-zen1-1-zen"

    def setUp(self):
        super().setUp()
        self.w("/boot/loader/loader.conf", ERASE_LOADER)
        self.w("/boot/loader/entries/luxos.conf", MAIN_ENTRY)
        self.owned = set()
        for v in (self.OLD,):
            self.install(v)
        self.w("/boot/vmlinuz-linux-zen", "KERNEL " + self.OLD)
        self.w("/boot/initramfs-linux-zen.img", "BOOTED INITRD " + self.OLD)
        self.patches = [
            mock.patch.object(care, "owned_by_package", side_effect=lambda p: p in self.owned),
            mock.patch.object(care, "installed_version", return_value="6.10.2.zen1-1"),
            mock.patch.object(care, "run", return_value=(0, "")),
            mock.patch.object(care, "running_kernel", return_value=self.OLD),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def install(self, v):
        self.w(f"/usr/lib/modules/{v}/vmlinuz", "KERNEL " + v)
        self.w(f"/usr/lib/modules/{v}/pkgbase", "linux-zen\n")
        self.w(f"/usr/lib/modules/{v}/kernel/fs/x.ko.zst", "x")
        self.w(f"/usr/lib/modules/{v}/updates/dkms/nvidia.ko.zst", "nvidia for " + v)
        self.owned.add(f"/usr/lib/modules/{v}/vmlinuz")

    def pacman_upgrade(self, old, new):
        """Simulace: pacman smaze soubory stareho jadra, DKMS jeho moduly, nainstaluje nove."""
        shutil.rmtree(self.root + f"/usr/lib/modules/{old}")
        self.owned.discard(f"/usr/lib/modules/{old}/vmlinuz")
        self.install(new)
        self.w("/boot/vmlinuz-linux-zen", "KERNEL " + new)
        self.w("/boot/initramfs-linux-zen.img", "INITRD " + new)

    def test_upgrade_keeps_booted_kernel(self):
        care.kwrite("good", self.OLD)
        care.kernel_pre([f"usr/lib/modules/{self.OLD}/vmlinuz"])
        self.pacman_upgrade(self.OLD, self.NEW)
        care.kernel_post([f"usr/lib/modules/{self.NEW}/vmlinuz", f"usr/lib/modules/{self.OLD}/vmlinuz"])
        d = self.root + f"/usr/lib/modules/{self.OLD}"
        self.assertEqual(self.r(f"/usr/lib/modules/{self.OLD}/vmlinuz"), "KERNEL " + self.OLD)
        self.assertEqual(self.r(f"/usr/lib/modules/{self.OLD}/updates/dkms/nvidia.ko.zst"), "nvidia for " + self.OLD)
        self.assertFalse(os.path.exists(d + "/pkgbase"))
        self.assertEqual(care.kread("prev"), self.OLD)
        self.assertEqual(care.kept_list(), [self.OLD])
        # initramfs, se kterym jadro opravdu nabehlo (ne nove sestavene)
        self.assertEqual(self.r("/boot/initramfs-linux-zen-prev.img"), "BOOTED INITRD " + self.OLD)
        self.assertEqual(self.r("/boot/vmlinuz-linux-zen-prev"), "KERNEL " + self.OLD)
        self.assertTrue(os.path.exists(self.root + "/boot/loader/entries/luxos+3.conf"))
        self.assertFalse(os.listdir(self.root + "/var/lib/luxos-care/kernel/staging"))
        st = care.load_state()
        self.assertTrue(st["prev_kernel_ok"])
        self.assertTrue(st["auto_fallback"])

    def test_second_upgrade_without_reboot_keeps_tested_kernel(self):
        care.kwrite("good", self.OLD)
        care.kernel_pre([f"usr/lib/modules/{self.OLD}/vmlinuz"])
        self.pacman_upgrade(self.OLD, self.NEW)
        care.kernel_post([f"usr/lib/modules/{self.NEW}/vmlinuz"])
        newer = "6.10.3-zen1-1-zen"
        care.kernel_pre([f"usr/lib/modules/{self.NEW}/vmlinuz"])          # NEW nikdy nenabehlo
        self.pacman_upgrade(self.NEW, newer)
        care.kernel_post([f"usr/lib/modules/{newer}/vmlinuz"])
        self.assertEqual(care.kread("prev"), self.OLD)
        self.assertFalse(os.path.exists(self.root + f"/usr/lib/modules/{self.NEW}"))
        self.assertTrue(os.path.exists(self.root + f"/usr/lib/modules/{self.OLD}/vmlinuz"))

    def test_after_reboot_into_new_old_prev_is_cleaned(self):
        care.kwrite("good", self.OLD)
        care.kernel_pre([f"usr/lib/modules/{self.OLD}/vmlinuz"])
        self.pacman_upgrade(self.OLD, self.NEW)
        care.kernel_post([f"usr/lib/modules/{self.NEW}/vmlinuz"])
        # restart do NEW, start v poradku
        care.kwrite("good", self.NEW)
        newer = "6.10.3-zen1-1-zen"
        with mock.patch.object(care, "running_kernel", return_value=self.NEW):
            care.kernel_pre([f"usr/lib/modules/{self.NEW}/vmlinuz"])
            self.pacman_upgrade(self.NEW, newer)
            care.kernel_post([f"usr/lib/modules/{newer}/vmlinuz"])
        self.assertEqual(care.kread("prev"), self.NEW)
        self.assertEqual(care.kept_list(), [self.NEW])
        self.assertFalse(os.path.exists(self.root + f"/usr/lib/modules/{self.OLD}"))      # presne jedno zalozni
        self.assertEqual(self.r("/boot/vmlinuz-linux-zen-prev"), "KERNEL " + self.NEW)
        self.assertIn(f"version {self.NEW}", self.r("/boot/loader/entries/luxos-prev.conf"))

    def test_running_prev_is_never_deleted(self):
        care.kwrite("kept", "old-running")
        self.w("/usr/lib/modules/old-running/vmlinuz", "x")
        with mock.patch.object(care, "running_kernel", return_value="old-running"):
            care.cleanup_kept("other")
        self.assertTrue(os.path.exists(self.root + "/usr/lib/modules/old-running/vmlinuz"))

    def test_other_kernel_package_ignored(self):
        self.w(f"/usr/lib/modules/6.6-lts/vmlinuz", "lts")
        self.w(f"/usr/lib/modules/6.6-lts/pkgbase", "linux-lts\n")
        care.kernel_pre(["usr/lib/modules/6.6-lts/vmlinuz"])
        self.assertFalse(os.path.exists(self.root + "/var/lib/luxos-care/kernel/staging/6.6-lts"))

    def test_fresh_install_no_prev(self):
        care.kernel_post([f"usr/lib/modules/{self.OLD}/vmlinuz"])
        self.assertTrue(os.path.exists(self.root + "/boot/loader/entries/luxos.conf"))      # bez pokusu
        self.assertFalse(os.path.exists(self.root + "/boot/loader/entries/luxos-prev.conf"))

    def test_dkms_change_rebuilds_prev_initramfs(self):
        care.kwrite("good", self.OLD)
        care.kernel_pre([f"usr/lib/modules/{self.OLD}/vmlinuz"])
        self.pacman_upgrade(self.OLD, self.NEW)
        care.kernel_post([f"usr/lib/modules/{self.NEW}/vmlinuz"])
        with mock.patch.object(care, "build_prev_initramfs",
                               side_effect=lambda v, out: (care.atomic_write(out, "REBUILT " + v), True)[1]) as b:
            care.kernel_post(["usr/src/nvidia-565/dkms.conf"])
        b.assert_called_once()
        self.assertEqual(self.r("/boot/initramfs-linux-zen-prev.img"), "REBUILT " + self.OLD)
        self.assertTrue(os.path.exists(self.root + "/boot/loader/entries/luxos+3.conf"))   # pokusy nezmeneny


class Reboot(Root):
    def test_needs_reboot(self):
        self.w("/usr/lib/modules/7.2.11-zen1-1-zen/vmlinuz", "k")
        self.w("/usr/lib/modules/7.2.11-zen1-1-zen/pkgbase", "linux-zen\n")
        self.w("/usr/lib/modules/7.2.10-zen1-1-zen/vmlinuz", "k")          # zachovane zalozni
        with mock.patch.object(care, "running_kernel", return_value="7.2.11-zen1-1-zen"):
            self.assertFalse(care.needs_reboot())
        with mock.patch.object(care, "running_kernel", return_value="7.2.10-zen1-1-zen"):
            self.assertTrue(care.needs_reboot())                             # nove jadro ceka
            care.kwrite("prev", "7.2.10-zen1-1-zen")
            with mock.patch.object(care, "main_entry_bad", return_value=True):
                self.assertFalse(care.needs_reboot())                        # nove selhalo: restart nepomuze


# ---- katalog a AI -----------------------------------------------------------------------
class Catalog(Root):
    def test_valid_action(self):
        self.assertTrue(care.valid_action("restart_unit", "lightdm.service"))
        self.assertTrue(care.valid_action("reinstall_package", "nvidia-utils"))
        self.assertTrue(care.valid_action("dkms_autoinstall", "6.10.1-zen1-1-zen"))
        self.assertTrue(care.valid_action("clean_cache"))
        for bad in (("restart_unit", "x; rm -rf /"), ("restart_unit", "--help.service"[0:0] + "a b.service"),
                    ("restart_unit", None), ("reinstall_package", "-Rdd"), ("reinstall_package", "a b"),
                    ("dkms_autoinstall", "../../etc"), ("clean_cache", "x"), ("rm", None),
                    ("run_shell", "ls"), ("reinstall_package", "$(id)")):
            self.assertFalse(care.valid_action(*bad), bad)

    def test_execute_rejects_invalid(self):
        with mock.patch.object(care, "run") as run:
            self.assertEqual(care.execute_action("restart_unit", "a;b"), (False, "invalid action"))
            self.assertEqual(care.execute_action("format_disk"), (False, "invalid action"))
            run.assert_not_called()

    def problem_state(self, mode="carefree"):
        self.w("/etc/luxos/care.conf", f"MODE={mode}\n")
        st = {"problems": [{"id": "unit:lightdm.service", "title": "A system service failed: %s",
                            "args": ["lightdm.service"], "severity": "serious",
                            "ai": {"request_id": "0123456789ab", "status": "pending",
                                   "options": [{"n": 1, "action": "restart_unit", "target": "lightdm.service",
                                                "label": "Restart"},
                                               {"n": 0, "action": "none", "target": "", "label": "none"}]}}]}
        care.save_state(st)

    def test_apply_ai_choice(self):
        self.problem_state()
        with mock.patch.object(care, "execute_action", return_value=(True, "")) as ex, \
                mock.patch.object(care, "_still_present", return_value=False), \
                mock.patch.object(care, "safe_check"):
            self.assertEqual(care.apply_ai_choice("0123456789ab", 5)[1], "option not offered")
            self.assertEqual(care.apply_ai_choice("ffffffffffff", 1)[1], "unknown request")
            self.assertEqual(care.apply_ai_choice("../etc", 1)[1], "invalid request")
            ex.assert_not_called()
            ok, _o = care.apply_ai_choice("0123456789ab", 1)
            self.assertTrue(ok)
            ex.assert_called_once_with("restart_unit", "lightdm.service")
            # podruhe uz ne (pozadavek vyrizeny)
            self.assertEqual(care.apply_ai_choice("0123456789ab", 1)[1], "already handled")
        h = care.read_history()
        self.assertEqual(h[-1]["source"], "ai")
        self.assertEqual(h[-1]["action"], "restart_unit")
        ev = care.read_json(care.EVENTS, {})
        self.assertEqual(ev["events"][-1]["kind"], "repaired")
        self.assertTrue(ev["events"][-1]["ai"])

    def test_apply_ai_choice_classic(self):
        self.problem_state("classic")
        with mock.patch.object(care, "execute_action") as ex:
            self.assertEqual(care.apply_ai_choice("0123456789ab", 1)[1], "classic mode")
            ex.assert_not_called()

    def test_ai_daily_limit(self):
        self.problem_state()
        for _i in range(care.AI_ACTIONS_PER_DAY):
            care.history("repair", source="ai", action="restart_unit", ok=True)
        with mock.patch.object(care, "execute_action") as ex:
            self.assertEqual(care.apply_ai_choice("0123456789ab", 1)[1], "daily limit")
            ex.assert_not_called()

    def test_do_check_rules_and_ai_request(self):
        """carefree: pravidlo jednou, pak dotaz pro AI; classic: jen hlaseni."""
        prob = care.make_problem("unit:cups.service", "A system service failed: %s",
                                 rules=[("restart_unit", "cups.service")],
                                 options=[("restart_unit", "cups.service"), ("reinstall_package", "cups")],
                                 args=["cups.service"])
        with mock.patch.object(care, "detect_problems", return_value=[dict(prob)]), \
                mock.patch.object(care, "diagnosis", return_value="diag"), \
                mock.patch.object(care, "find_pacnew", return_value=[]), \
                mock.patch.object(care, "needs_reboot", return_value=False), \
                mock.patch.object(care, "execute_action", return_value=(False, "failed")) as ex:
            care.do_check()
            ex.assert_called_once_with("restart_unit", "cups.service")
            st = care.load_state()
            req = st["problems"][0]["ai"]
            self.assertEqual(req["status"], "pending")
            self.assertEqual([o["action"] for o in req["options"]], ["restart_unit", "reinstall_package", "none"])
            self.assertEqual(req["options"][-1]["n"], 0)
            rid = req["request_id"]
            care.do_check()                       # stejny den: pravidlo ani dotaz se neopakuji
            self.assertEqual(ex.call_count, 1)
            self.assertEqual(care.load_state()["problems"][0]["ai"]["request_id"], rid)
        kinds = [e["kind"] for e in care.read_json(care.EVENTS, {})["events"]]
        self.assertEqual(kinds, ["problem"])     # upozorneni jen jednou

    def test_do_check_classic_reports_only(self):
        self.w("/etc/luxos/care.conf", "MODE=classic\n")
        prob = care.make_problem("stale_lock", "The package manager was left locked", rules=["remove_db_lock"],
                                 options=[("remove_db_lock", None)])
        with mock.patch.object(care, "detect_problems", return_value=[prob]), \
                mock.patch.object(care, "find_pacnew", return_value=[]), \
                mock.patch.object(care, "needs_reboot", return_value=False), \
                mock.patch.object(care, "execute_action") as ex:
            care.do_check()
            ex.assert_not_called()
        st = care.load_state()
        self.assertNotIn("ai", st["problems"][0])

    def test_rule_fixes(self):
        prob = care.make_problem("stale_lock", "The package manager was left locked", rules=["remove_db_lock"],
                                 options=[("remove_db_lock", None)])
        with mock.patch.object(care, "detect_problems", side_effect=[[prob], []]), \
                mock.patch.object(care, "find_pacnew", return_value=[]), \
                mock.patch.object(care, "needs_reboot", return_value=False), \
                mock.patch.object(care, "execute_action", return_value=(True, "")):
            care.do_check()
        self.assertEqual(care.load_state()["problems"], [])
        ev = care.read_json(care.EVENTS, {})["events"]
        self.assertEqual(ev[-1]["kind"], "repaired")

    def test_once_per_kernel_not_looping(self):
        """Opakovane selhani noveho jadra: "zkusit znovu" jen jednou pro danou verzi."""
        prob = care.make_problem("fallback_kernel", "x", rules=["retry_new_kernel"],
                                 options=[("retry_new_kernel", None)], once_per="6.10.2")
        with mock.patch.object(care, "detect_problems", return_value=[dict(prob)]), \
                mock.patch.object(care, "diagnosis", return_value="d"), \
                mock.patch.object(care, "find_pacnew", return_value=[]), \
                mock.patch.object(care, "needs_reboot", return_value=False), \
                mock.patch.object(care, "execute_action", return_value=(True, "")) as ex:
            care.do_check()
            st = care.load_state()
            st["attempts"] = {}                  # novy den
            care.save_state(st)
            care.do_check()
        self.assertEqual(ex.call_count, 1)


class LuxBackend(unittest.TestCase):
    """Transakce pres lux (libalpm) misto pacmanu; bez lux/pyalpm zustava pacman."""

    def setUp(self):
        self._ok = care._lux_ok

    def tearDown(self):
        care._lux_ok = self._ok

    def test_mapping(self):
        L = care.LUX_ALPM
        base = [L, "--machine", "-y", "--color=never"]
        self.assertEqual(care.lux_command(["-Syuw"]), base + ["upgrade", "--refresh", "--download-only"])
        self.assertEqual(care.lux_command(["-Su"]), base + ["upgrade"])
        self.assertEqual(care.lux_command(["-Syu", "--noconfirm", "--noprogressbar"]), base + ["upgrade", "--refresh"])
        self.assertEqual(care.lux_command(["-Sy", "--needed", "archlinux-keyring", "luxos-keyring"]),
                         base + ["install", "--refresh", "--needed", "--", "archlinux-keyring", "luxos-keyring"])
        self.assertEqual(care.lux_command(["-S", "linux"]), base + ["install", "--", "linux"])
        self.assertEqual(care.lux_command(["-U", "/var/cache/pacman/pkg/linux-6.11-1-x86_64.pkg.tar.zst"]),
                         base + ["install", "--", "/var/cache/pacman/pkg/linux-6.11-1-x86_64.pkg.tar.zst"])
        # nezname nebo podezrele argumenty -> jen pacman
        self.assertIsNone(care.lux_command(["-Rns", "x"]))
        self.assertIsNone(care.lux_command(["-S", "--overwrite", "*", "x"]))
        self.assertIsNone(care.lux_command(["-S", "a;b"]))
        self.assertIsNone(care.lux_command(["-U", "relative.pkg.tar.zst"]))
        self.assertIsNone(care.lux_command([]))

    def test_pm_uses_lux_or_pacman(self):
        care._lux_ok = True
        self.assertEqual(care.pm(["-Su"])[0], care.LUX_ALPM)
        self.assertEqual(care.pm(["-Rns", "x"])[:2], [care.PACMAN, "--noconfirm"])
        care._lux_ok = False
        self.assertEqual(care.pm(["-Su"]), [care.PACMAN, "--noconfirm", "--noprogressbar", "--color", "never", "-Su"])
        self.assertEqual(care.pm(["-Syu", "--noconfirm", "--noprogressbar"]),
                         [care.PACMAN, "--noconfirm", "--noprogressbar", "--color", "never", "-Syu"])

    def test_fallback_uses_real_pacman(self):
        """Bez lux vola pacman z jadra lux (lux-engine, /usr/lib/lux/alpm/bin), ne pacman z PATH."""
        care._lux_ok = False
        with mock.patch.object(care, "PACMAN", "/usr/lib/lux/alpm/bin/pacman"):
            self.assertEqual(care.pm(["-Su"])[0], "/usr/lib/lux/alpm/bin/pacman")
        with open(care.__file__) as f:
            src = f.read()
        self.assertNotRegex(src, r'\[\s*"pacman"\s*,')

    def test_commands_get_engine_tools_on_path(self):
        """Spoustene prikazy (checkupdates, paccache, pacman-key, hooky transakci) najdou nastroje jadra;
        proces sam PATH nemeni (modul nacitaji i aplikace v relaci uzivatele)."""
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            rc, out = care.run(["sh", "-c", 'echo "$PATH"'])
            self.assertEqual((rc, out.strip()), (0, "/usr/lib/lux/alpm/bin:/usr/bin:/bin"))
            self.assertEqual(os.environ["PATH"], "/usr/bin:/bin")
        with mock.patch.dict(os.environ, {"PATH": "/usr/lib/lux/alpm/bin:/usr/bin"}):
            self.assertEqual(care.engine_env()["PATH"], "/usr/lib/lux/alpm/bin:/usr/bin")
        with open(care.__file__) as f:
            src = f.read()
        self.assertNotIn("dict(os.environ, LC_ALL", src)      # kazde spusteni pres engine_env

    def test_lux_available_checks_backend(self):
        care._lux_ok = None
        with mock.patch.object(care, "LUX_ALPM", "/nonexistent/lux_alpm.py"):
            self.assertFalse(care.lux_available())
        care._lux_ok = None
        with mock.patch.object(care.os, "access", return_value=True), \
                mock.patch.object(care, "run", return_value=(3, "pyalpm is not installed")) as r:
            self.assertFalse(care.lux_available())
            self.assertEqual(r.call_args[0][0][1:], ["available"])
        care._lux_ok = None
        with mock.patch.object(care.os, "access", return_value=True), \
                mock.patch.object(care, "run", return_value=(0, "ok")):
            self.assertTrue(care.lux_available())

    def test_updater_progress_and_errors_from_lux_output(self):
        """Vystup lux --machine: prubeh z radku 'upgrading x...', chyby a konflikty jako u pacmanu."""
        out = "\n".join(["@@PLAN upgrade 2 100 100", "Packages (2) a-2-1 linux-6.11.2-1", "@@PHASE install",
                         "upgrading a...", "upgrading linux...", ":: Running post-transaction hooks...",
                         "@@PHASE hooks", "@@DONE 0"]) + "\n"
        care._lux_ok = True
        seen = []

        class P:
            def __init__(self, cmd, **_kw):
                seen.append(cmd)
                self.stdout = iter(out.splitlines(True))

            def wait(self):
                return 0

            def poll(self):
                return 0
        prog = []
        with mock.patch.object(care.subprocess, "Popen", P), \
                mock.patch.object(care, "set_progress", lambda *a, **k: prog.append((a, k))), \
                mock.patch.object(care, "have", return_value=False):
            rc, text = care.Updater().pacman(["-Su"], "install", total=2, base=0.6, span=0.37)
        self.assertEqual(rc, 0)
        self.assertEqual(seen[0][0], care.LUX_ALPM)
        self.assertEqual([k.get("done") for _a, k in prog if k.get("done")], [1, 2])
        self.assertEqual(prog[-1][0][2], "hooks")
        err = "error: failed to commit transaction (conflicting files)\n" \
              "linux: /usr/lib/modules/6.11.2-arch1-1/vmlinuz exists in filesystem\n" \
              "@@ERROR conflict Some files of the new packages already exist on the system (file conflict).\n"
        self.assertEqual(care.classify_pacman_error(err), "conflict")
        self.assertEqual(care.classify_pacman_error(
            "error: failed to init transaction (unable to lock database)\n@@ERROR locked x"), "locked")
        self.assertEqual(care.classify_pacman_error(
            "error: failed retrieving file 'a.pkg.tar.zst' from m : timeout\n@@ERROR network x"), "network")


class Redact(unittest.TestCase):
    def test_redact(self):
        text = ("Oct 20 host1 lightdm[1]: user antonin from 192.168.1.20 mac aa:bb:cc:dd:ee:ff "
                "/home/antonin/secret.txt token=abcdEFGH1234 mail a.b@example.com "
                "Cookie: lux_account_session=0123456789abcdef0123456789abcdef password: hunter2 "
                "Antonin Tomecek logged in")
        out = care.redact(text, names={"antonin", "Antonin Tomecek"}, host="host1")
        for leak in ("antonin", "192.168", "aa:bb", "secret.txt" if False else "/home/antonin", "abcdEFGH1234",
                     "a.b@example.com", "0123456789abcdef0123456789abcdef", "hunter2", "Tomecek", "host1"):
            self.assertNotIn(leak, out, leak)
        self.assertIn("lightdm", out)
        self.assertIn("/home/USER", out)


# ---- relace (luxos-hub) --------------------------------------------------------------
class Session(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi  # noqa: F401
            import luxos_care_session as s
            cls.s = s
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(str(e))

    def test_parse_choice(self):
        opts = [{"n": 1}, {"n": 2}, {"n": 0}]
        self.assertEqual(self.s.parse_choice('{"option": 2, "reason": "ok"}', opts), (2, "ok"))
        self.assertEqual(self.s.parse_choice('```json\n{"option": "1", "reason": "r"}\n```', opts), (1, "r"))
        self.assertEqual(self.s.parse_choice('{"option": 7}', opts)[0], None)            # nenabidnuto
        self.assertEqual(self.s.parse_choice('{"option": true}', opts)[0], None)
        self.assertEqual(self.s.parse_choice('{"command": "rm -rf /"}', opts)[0], None)
        self.assertEqual(self.s.parse_choice("run sudo pacman -Rdd glibc", opts)[0], None)
        self.assertEqual(self.s.parse_choice(None, opts)[0], None)

    def test_new_events(self):
        t = 10_000
        evs = [{"seq": 1, "time": t - 7200, "kind": "updated"}, {"seq": 2, "time": t - 60, "kind": "repaired", "title": "a"},
               {"seq": 3, "time": t - 30, "kind": "repaired", "title": "a"}, {"seq": 4, "time": t, "kind": "updated"}]
        self.assertEqual([e["seq"] for e in self.s.new_events(evs, 0, True, t)], [3, 4])
        self.assertEqual([e["seq"] for e in self.s.new_events(evs, 0, False, t)], [3, 4])   # 2x updated -> posledni
        self.assertEqual([e["seq"] for e in self.s.new_events(evs, 3, False, t)], [4])

    def test_notifications(self):
        n = self.s.notification_for({"kind": "updated", "count": 5, "reboot": True})
        self.assertIn("restart", [a for a, _l in n[2]])
        self.assertIsNotNone(self.s.notification_for({"kind": "updates_available", "count": 3}))
        n = self.s.notification_for({"kind": "repaired", "title": "A system service failed: %s",
                                     "args": ["cups.service"], "ai": True})
        self.assertIn("cups.service", n[1])
        self.assertIsNone(self.s.notification_for({"kind": "bogus"}))

    def test_messages_contain_only_options(self):
        p = {"title": "t", "ai": {"diagnosis": "d", "options": [{"n": 1, "label": "Restart a failed system service: x"}]}}
        msgs = self.s.build_messages(p)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("1: Restart", msgs[1]["content"])
        self.assertNotIn("sessionToken", json.dumps(msgs))


if __name__ == "__main__":
    unittest.main()
