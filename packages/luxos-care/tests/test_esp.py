"""Misto na EFI/boot oddilu (incident 2026-11-10: 1 GB ESP plny - tri sady jadra snimku se stejnym jadrem,
useknute kopie, neuplny initramfs-...-prev.img.new): zbytky, slouceni sad se stejnym jadrem, rozpocet
mista (poradi mazani), plny oddil uprostred kopie, kontrola po startu a po transakci.

    python3 -m unittest discover -s packages/luxos-care/tests -v

Volne misto je model: kapacita oddilu minus soucet velikosti souboru v /boot (care.free_bytes nahrazena).
Skutecny zapis na plny souborovy system (tmpfs v user namespace): docs/proposals/esp-space.md, Testy.
"""
import errno
import os
import shutil
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_snapshots as ts  # noqa: E402
from test_snapshots import care, snap  # noqa: E402

KB = 1024


class EspEnv(ts.Env):
    """systemd-boot na ESP v /boot s omezenou kapacitou (CAP bajtu)."""
    CAP = 10 ** 9

    def setUp(self):
        super().setUp()
        p = mock.patch.object(care, "free_bytes", self.free)
        p.start()
        self.addCleanup(p.stop)

    def used(self):
        total = 0
        for d, _s, files in os.walk(self.root + "/boot"):
            for f in files:
                total += os.path.getsize(os.path.join(d, f))
        return total

    def free(self, _path):
        return max(0, self.CAP - self.used())

    def big_kernel(self, ver, tag, vsize=100 * KB, isize=300 * KB):
        """Jadro ver: vmlinuz (obsah podle ver) a initramfs (obsah podle tag) dane velikosti."""
        vml = (b"V" + ver.encode()) * (vsize // (len(ver) + 1))
        self.w(f"/usr/lib/modules/{ver}/vmlinuz", vml)
        self.w(f"/usr/lib/modules/{ver}/pkgbase", "linux-luxos\n")
        self.w("/boot/vmlinuz-linux-luxos", vml)
        self.w("/boot/initramfs-linux-luxos.img", (b"I" + tag.encode()) * (isize // (len(tag) + 1)))

    def sets(self):
        try:
            return sorted(os.listdir(self.root + "/boot/luxos-snapshots"))
        except OSError:
            return []

    def snap_entries(self):
        return sorted(e for e in self.entries() if e.startswith("snapshot-"))


class Dedupe(EspEnv):
    def test_same_kernel_four_initramfs_keeps_newest_and_oldest(self):
        """Stejne jadro, initramfs se lisi (aktualizace systemd/firmwaru): 4 sady -> 2, zadna polozka nezmizi."""
        names = []
        for i in range(4):
            self.big_kernel(ts.KVER, f"initramfs-{i}")
            names.append(snap.create(self.top, now=self.at(i))["name"])
        snaps = snap.list_snapshots(self.top)
        ksets = [s["kset"] for s in snaps]
        self.assertEqual(len(set(ksets)), 4)
        moved = snap.dedupe_kernels(care.detect_layout(), self.top, snaps)
        self.assertEqual(sorted(moved), sorted(names[1:3]))
        snaps = snap.list_snapshots(self.top)
        self.assertEqual([s["kset"] for s in snaps], [ksets[0], ksets[3], ksets[3], ksets[3]])
        gone = snap.gc_kernels(care.detect_layout(), self.top, snaps)
        self.assertEqual(sorted(gone), sorted(ksets[1:3]))
        self.assertEqual(self.sets(), sorted([ksets[0], ksets[3]]))
        snap.sync_boot(self.top)
        self.assertEqual(len(self.snap_entries()), 4)              # vsechny snimky dal startuji
        e = self.r(f"/boot/loader/entries/snapshot-luxos-{names[1]}.conf")
        self.assertIn(f"/luxos-snapshots/{ksets[3]}/initramfs.img", e)

    def test_different_kernels_not_merged(self):
        for i, ver in enumerate((ts.KVER, ts.KVER2, "6.17.3-luxos1-1")):
            self.big_kernel(ver, f"i{i}")
            snap.create(self.top, now=self.at(i))
        snaps = snap.list_snapshots(self.top)
        self.assertEqual(snap.dedupe_kernels(care.detect_layout(), self.top, snaps), [])
        self.assertEqual(len(self.sets()), 3)

    def test_two_variants_untouched(self):
        for i in range(2):
            self.big_kernel(ts.KVER, f"i{i}")
            snap.create(self.top, now=self.at(i))
        self.assertEqual(snap.dedupe_kernels(care.detect_layout(), self.top, snap.list_snapshots(self.top)), [])

    def test_booted_snapshot_set_kept(self):
        for i in range(4):
            self.big_kernel(ts.KVER, f"i{i}")
            snap.create(self.top, now=self.at(i))
        snaps = snap.list_snapshots(self.top)
        self.w("/proc/cmdline", ts.OPTS + f" luxos.snapshot={snaps[1]['name']}\n")
        moved = snap.dedupe_kernels(care.detect_layout(), self.top, snaps)
        self.assertEqual(moved, [snaps[2]["name"]])


class Budget(EspEnv):
    def make_sets(self, n):
        """n snimku, kazdy s jinym jadrem (400 KB sada)."""
        out = []
        for i in range(n):
            ver = f"6.17.{i + 1}-luxos1-1"
            self.big_kernel(ver, f"i{i}")
            out.append(snap.create(self.top, now=self.at(i)))
        return out

    def test_prune_oldest_sets_first_never_newest(self):
        metas = self.make_sets(5)
        lay = care.detect_layout()
        used = self.used()
        # misto chybi na ~2 sady: smazou se dve nejstarsi
        self.CAP = used + 100 * KB
        free, removed = snap.esp_budget(lay, self.top, snap.list_snapshots(self.top), need=700 * KB, reserve=150 * KB)
        self.assertEqual(removed, [metas[0]["kset"], metas[1]["kset"]])
        self.assertGreaterEqual(free, 850 * KB)
        snaps = snap.list_snapshots(self.top)
        self.assertIsNone(snaps[0]["kset"])                        # snimek zustava, jen bez polozky
        self.assertEqual(len(snaps), 5)
        snap.sync_boot(self.top)
        self.assertEqual(len(self.snap_entries()), 3)

    def test_newest_set_protected_even_when_space_missing(self):
        metas = self.make_sets(3)
        self.CAP = self.used()                                     # plny oddil
        free, removed = snap.esp_budget(care.detect_layout(), self.top, snap.list_snapshots(self.top),
                                        need=10 ** 9)
        self.assertEqual(removed, [metas[0]["kset"], metas[1]["kset"]])
        self.assertEqual(self.sets(), [metas[2]["kset"]])
        # hlavni jadro (vmlinuz/initramfs v /boot) se nikdy nemaze
        self.assertTrue(os.path.exists(self.root + "/boot/vmlinuz-linux-luxos"))
        self.assertTrue(os.path.exists(self.root + "/boot/initramfs-linux-luxos.img"))

    def test_booted_snapshot_set_protected(self):
        metas = self.make_sets(3)
        self.w("/proc/cmdline", ts.OPTS + f" luxos.snapshot={metas[0]['name']}\n")
        self.CAP = self.used()
        _free, removed = snap.esp_budget(care.detect_layout(), self.top, snap.list_snapshots(self.top), need=10 ** 9)
        self.assertEqual(removed, [metas[1]["kset"]])

    def test_pruned_variant_repointed_to_same_kernel(self):
        """Starsi varianta stejneho jadra se smaze, jeji snimky startuji novejsi (polozka zustava)."""
        self.big_kernel(ts.KVER, "a")
        a = snap.create(self.top, now=self.at(1))
        self.big_kernel(ts.KVER, "b")
        b = snap.create(self.top, now=self.at(2))
        self.CAP = self.used() + 50 * KB
        _free, removed = snap.esp_budget(care.detect_layout(), self.top, snap.list_snapshots(self.top),
                                         need=300 * KB, reserve=0)
        self.assertEqual(removed, [a["kset"]])
        self.assertEqual(snap.read_meta(self.top, a["name"])["kset"], b["kset"])
        snap.sync_boot(self.top)
        self.assertEqual(len(self.snap_entries()), 2)

    def test_enough_space_nothing_removed(self):
        self.make_sets(3)
        free, removed = snap.esp_budget(care.detect_layout(), self.top, snap.list_snapshots(self.top), need=KB)
        self.assertEqual(removed, [])
        self.assertEqual(len(self.sets()), 3)

    def test_pre_transaction_keeps_room_for_new_set_and_transaction(self):
        """Pred transakci: misto na novou sadu i na transakci (novy initramfs, zalozni jadro)."""
        metas = self.make_sets(4)
        ksize = snap.kernel_set_size(care.detect_layout())
        self.big_kernel("6.18.0-luxos1-1", "new")                  # nove jadro -> nova sada
        self.CAP = self.used() + ksize // 2
        with mock.patch.object(snap, "ESP_RESERVE", 50 * KB), mock.patch.object(snap, "KSET_MARGIN", 16 * KB):
            snap.pre_transaction(["linux-luxos"], now=self.at(30))
        snaps = snap.list_snapshots(self.top)
        self.assertEqual(len(snaps), 5)
        self.assertIsNotNone(snaps[-1]["kset"])                    # nova sada ulozena
        self.assertGreaterEqual(self.free(None), 50 * KB + ksize)  # a misto na transakci zustalo
        self.assertNotIn(metas[0]["kset"], self.sets())            # za nejstarsi sadu

    def test_pre_transaction_no_extra_space_when_set_exists(self):
        metas = self.make_sets(3)
        ksize = snap.kernel_set_size(care.detect_layout())
        self.CAP = self.used() + ksize + snap.ESP_RESERVE + KB     # misto jen na transakci
        snap.pre_transaction(["firefox"], now=self.at(30))
        self.assertEqual(self.sets(), sorted(m["kset"] for m in metas))   # nic se nesmazalo

    def test_grub_in_btrfs_no_budget(self):
        lay = {"kind": "grub", "kernel": "linux-luxos"}
        with mock.patch.object(snap, "is_mountpoint", return_value=False):
            self.assertEqual(snap.esp_budget(lay, self.top, [], need=10 ** 12), (None, []))


class Stale(EspEnv):
    def test_only_own_leftovers_removed(self):
        own = ["/boot/initramfs-linux-luxos-prev.img.new", "/boot/vmlinuz-linux-luxos-prev.new",
               "/boot/initramfs-linux-luxos.img.tmp", "/boot/initramfs-linux-luxos.img.luxos-new",
               "/boot/vmlinuz-linux-luxos.luxos-new", "/boot/initramfs-linux-luxos-fallback.img.tmp"]
        foreign = ["/boot/initramfs-linux.img.tmp", "/boot/EFI/Microsoft/Boot/bootmgfw.efi",
                   "/boot/notes.new", "/boot/initramfs-linux-luxos.img"]
        for f in own + foreign:
            self.w(f, "x")
        os.makedirs(self.root + f"/boot/luxos-snapshots/{ts.KVER}-0123456789ab.new")
        os.makedirs(self.root + "/boot/luxos-snapshots/something.new")
        gone = snap.clean_stale(care.detect_layout())
        self.assertEqual(sorted(os.path.relpath(p, self.root) for p in gone),
                         sorted([f.lstrip("/") for f in own] + [f"boot/luxos-snapshots/{ts.KVER}-0123456789ab.new"]))
        for f in foreign:
            self.assertTrue(os.path.exists(self.root + f), f)
        self.assertTrue(os.path.isdir(self.root + "/boot/luxos-snapshots/something.new"))


def enospc_after(nbytes):
    """shutil.copyfile, ktery zapise nbytes a skonci "No space left on device" (jako plny FAT)."""
    real = shutil.copyfile

    def copy(src, dst, *a, **k):
        if "/boot/" not in str(dst):                               # snimek (btrfs model) normalne
            return real(src, dst, *a, **k)
        with open(src, "rb") as f, open(dst, "wb") as g:
            g.write(f.read(nbytes))
        raise OSError(errno.ENOSPC, "No space left on device", dst)
    return copy, real


class FullDuringCopy(EspEnv):
    def test_snapshot_kernel_set_no_partial_dir(self):
        copy, _real = enospc_after(1000)
        self.big_kernel(ts.KVER, "a")
        with mock.patch.object(shutil, "copyfile", copy):
            meta = snap.create(self.top, now=self.at(1))
        self.assertIsNone(meta["kset"])
        self.assertEqual(self.sets(), [])                          # zadna neuplna sada ani .new

    def test_rollback_copy_failure_no_luxos_new(self):
        self.big_kernel(ts.KVER, "a")
        a = snap.create(self.top, now=self.at(1))
        self.big_kernel(ts.KVER2, "b")
        copy, _real = enospc_after(500)
        with mock.patch.object(shutil, "copyfile", copy):
            with self.assertRaises(snap.SnapshotError):
                snap.rollback(self.top, a["name"], now=self.at(30))
        self.assertFalse([f for f in os.listdir(self.root + "/boot") if f.endswith((".luxos-new", ".new"))])

    def test_rollback_without_set_same_kernel_version(self):
        """Sada smazana kvuli mistu, jadro stejne verze jako ted: navrat funguje (hlavni jadro zustava)."""
        self.big_kernel(ts.KVER, "a")
        a = snap.create(self.top, now=self.at(1))
        self.big_kernel(ts.KVER, "b")                              # jiny initramfs, stejne jadro
        meta = snap.read_meta(self.top, a["name"])
        shutil.rmtree(self.root + "/boot/luxos-snapshots/" + meta["kset"])
        meta["kset"] = None
        snap.write_meta(self.top, meta)
        res = snap.rollback(self.top, a["name"], now=self.at(30))
        self.assertEqual(res["target"], a["name"])

    def test_rollback_without_set_other_kernel_refused(self):
        self.big_kernel(ts.KVER, "a")
        a = snap.create(self.top, now=self.at(1))
        meta = snap.read_meta(self.top, a["name"])
        shutil.rmtree(self.root + "/boot/luxos-snapshots/" + meta["kset"])
        meta["kset"] = None
        snap.write_meta(self.top, meta)
        self.big_kernel(ts.KVER2, "b")
        with self.assertRaises(snap.SnapshotError) as cm:
            snap.rollback(self.top, a["name"], now=self.at(30))
        self.assertEqual(cm.exception.code, "kernel_missing")


class PrevKernel(EspEnv):
    """Zalozni jadro na plnem ESP (u majitele: initramfs-linux-luxos-prev.img.new 65 MB zustal na ESP)."""
    VER = "7.2.13-1-luxos"

    def setUp(self):
        super().setUp()
        self.w(f"/usr/lib/modules/{self.VER}/vmlinuz", b"P" * (100 * KB))
        self.w(f"/var/lib/luxos-care/kernel/initramfs-{self.VER}.img", b"Q" * (300 * KB))

    def test_enospc_mid_copy_no_leftover_and_no_dangling_entry(self):
        self.CAP = self.used() + 10 ** 6
        copy, _real = enospc_after(64 * KB)
        with mock.patch.object(shutil, "copyfile", copy):
            ok, why = care.install_prev_boot(care.detect_layout(), self.VER)
        self.assertEqual((ok, why), (False, "esp_full"))
        self.assertFalse([f for f in os.listdir(self.root + "/boot") if f.endswith(".new")])
        self.assertFalse(os.path.exists(self.root + "/boot/loader/entries/luxos-prev.conf"))
        self.assertFalse(os.path.exists(self.root + "/boot/initramfs-linux-luxos-prev.img"))

    def test_old_prev_not_counted_as_free(self):
        """Opravena chyba: stare soubory se pocitaly jako volne misto, i kdyz se nove pise vedle nich."""
        ok, why = care.install_prev_boot(care.detect_layout(), self.VER)
        self.assertTrue(ok, why)
        self.w(f"/var/lib/luxos-care/kernel/initramfs-{self.VER}.img", b"R" * (300 * KB))   # novy obsah
        self.CAP = self.used() + 4 * 1024 * KB + 100 * KB          # misto (+4 MB rezerva) jen bez stareho
        ok, why = care.install_prev_boot(care.detect_layout(), self.VER)
        self.assertTrue(ok, why)                                   # stare napred pryc, pak nove
        with open(self.root + "/boot/initramfs-linux-luxos-prev.img", "rb") as f:
            self.assertEqual(f.read(1), b"R")
        self.assertIn("LuxOS (previous kernel)", self.r("/boot/loader/entries/luxos-prev.conf"))

    def test_frees_space_from_snapshot_sets_first(self):
        for i in range(3):
            self.big_kernel(f"6.17.{i + 1}-luxos1-1", f"i{i}")
            snap.create(self.top, now=self.at(i))
        self.CAP = self.used() + 4 * 1024 * KB + 100 * KB          # na zalozni jadro (+4 MB) chybi
        with mock.patch.object(snap, "supported", return_value=(True, "")), \
                mock.patch.object(snap, "ESP_RESERVE", 0):
            ok, why = care.install_prev_boot(care.detect_layout(), self.VER)
        self.assertTrue(ok, why)
        self.assertLess(len(self.sets()), 3)


class Checks(EspEnv):
    def fake_run(self, results):
        calls = []

        def run(cmd, timeout=600, input=None, env=None):
            calls.append(cmd)
            for prefix, res in results:
                if cmd[:len(prefix)] == prefix:
                    return res(cmd) if callable(res) else res
            return 0, ""
        return run, calls

    def test_problems_low_space_damaged_image_and_loader(self):
        self.w("/boot/initramfs-linux-luxos.img", b"x" * 4096)
        self.CAP = self.used() + 10 * 1024 * 1024
        status = "loader=broken\nloader_damaged=EFI/LuxOS/shimx64.efi,EFI/BOOT/BOOTX64.EFI\n"
        run, _calls = self.fake_run([(["lsinitcpio"], (1, "")), (["luxos-secureboot", "status"], (0, status))])
        with mock.patch.object(care, "run", run), mock.patch.object(care, "have", return_value=True):
            probs = {p["id"]: p for p in care.esp_problems(care.detect_layout())}
        self.assertEqual(sorted(probs), ["boot_loader_damaged", "esp_low_space", "initramfs_damaged"])
        self.assertEqual(probs["esp_low_space"]["rules"], ["clean_esp"])
        self.assertEqual(probs["esp_low_space"]["detail"], "10 MiB free")
        self.assertEqual(probs["initramfs_damaged"]["rules"], ["clean_esp", "rebuild_initramfs"])
        self.assertIn("EFI/LuxOS/shimx64.efi", probs["boot_loader_damaged"]["detail"])
        self.assertEqual(probs["boot_loader_damaged"]["rules"], ["clean_esp", "repair_boot_loader"])
        for p in probs.values():
            for rule in p["rules"]:
                self.assertTrue(care.valid_action(rule))

    def test_no_problems_when_fine(self):
        self.w("/boot/initramfs-linux-luxos.img", b"x" * 4096)
        run, _calls = self.fake_run([(["luxos-secureboot", "status"], (0, "loader=installed\n"))])
        with mock.patch.object(care, "run", run), mock.patch.object(care, "have", return_value=True):
            self.assertEqual(care.esp_problems(care.detect_layout()), [])

    def test_esp_check_rebuilds_truncated_image(self):
        self.w("/boot/initramfs-linux-luxos.img", b"x" * 4096)
        self.w("/boot/initramfs-linux-luxos.img.tmp", b"partial")
        state = {"built": False}

        def lsinit(cmd):
            return (0, "") if state["built"] else (1, "")

        def mk(cmd):
            state["built"] = True
            return 0, ""
        run, calls = self.fake_run([(["lsinitcpio"], lsinit), (["mkinitcpio", "-P"], mk)])
        with mock.patch.object(care, "run", run), mock.patch.object(care, "have", return_value=True), \
                mock.patch.object(care, "add_event") as ev:
            rc, bad = care.esp_check()
        self.assertEqual((rc, bad), (0, []))
        self.assertIn(["mkinitcpio", "-P"], calls)
        self.assertFalse(os.path.exists(self.root + "/boot/initramfs-linux-luxos.img.tmp"))
        ev.assert_called_once()

    def test_esp_check_fails_loudly(self):
        self.w("/boot/initramfs-linux-luxos.img", b"x" * 4096)
        run, _calls = self.fake_run([(["lsinitcpio"], (1, "")), (["mkinitcpio", "-P"], (1, "No space left"))])
        with mock.patch.object(care, "run", run), mock.patch.object(care, "have", return_value=True):
            rc, bad = care.esp_check()
        self.assertEqual(rc, 1)
        self.assertEqual(bad, [self.root + "/boot/initramfs-linux-luxos.img"])

    def test_esp_check_ok_no_rebuild(self):
        self.w("/boot/initramfs-linux-luxos.img", b"x" * 4096)
        run, calls = self.fake_run([])
        with mock.patch.object(care, "run", run), mock.patch.object(care, "have", return_value=True):
            self.assertEqual(care.esp_check(), (0, []))
        self.assertNotIn(["mkinitcpio", "-P"], calls)

    def test_actions(self):
        self.assertTrue(care.valid_action("clean_esp"))
        self.assertTrue(care.valid_action("repair_boot_loader"))
        self.assertFalse(care.valid_action("clean_esp", "x"))
        run, calls = self.fake_run([(["luxos-secureboot", "sync"], (0, ""))])
        with mock.patch.object(care, "run", run), mock.patch.object(care, "have", return_value=True):
            ok, _o = care.execute_action("repair_boot_loader")
        self.assertTrue(ok)
        self.assertIn(["luxos-secureboot", "sync", "--quiet"], calls)
        for i in range(3):
            self.big_kernel(f"6.17.{i + 1}-luxos1-1", f"i{i}")
            snap.create(self.top, now=self.at(i))
        self.CAP = self.used() + snap.ESP_LOW + 10 * KB
        ok, out = care.execute_action("clean_esp")
        self.assertTrue(ok, out)

    def test_safe_clean_after_boot(self):
        """Kontrola po startu: zbytky a duplicitni sady pryc, zadny snimek neprijde o polozku."""
        for i in range(4):
            self.big_kernel(ts.KVER, f"i{i}")
            snap.create(self.top, now=self.at(i))
        snap.sync_boot(self.top)
        self.w("/boot/initramfs-linux-luxos-prev.img.new", b"partial")
        gone = snap.esp_safe_clean()
        self.assertIn("initramfs-linux-luxos-prev.img.new", gone)
        self.assertEqual(len(self.sets()), 2)
        self.assertEqual(len(self.snap_entries()), 4)


if __name__ == "__main__":
    unittest.main()
