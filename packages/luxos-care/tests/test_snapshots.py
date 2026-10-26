"""Testy snimku systemu (luxos_snapshots): vytvoreni, sady jadra, uchovavani, polozky zavadece
(systemd-boot i GRUB) a navrat - bez roota, btrfs nahrazuje trida nad obycejnymi adresari.

    python3 -m unittest discover -s packages/luxos-care/tests -v

Skutecny btrfs (obraz v souboru pres loop, jen se sudo -n): test_snapshots_btrfs.py.
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
sys.path.insert(0, FILES)
sys.path.insert(0, os.path.join(HERE, "..", "..", "luxos-i18n", "files"))

import luxos_care as care  # noqa: E402
import luxos_snapshots as snap  # noqa: E402

MARK = ".fake-subvol"
KVER = "6.17.1-luxos1-1"
KVER2 = "6.17.2-luxos1-1"
OPTS = ("rd.luks.name=abcd=cryptroot rd.luks.options=discard root=/dev/mapper/cryptroot rootflags=subvol=@ "
        "rw quiet splash loglevel=3 vt.global_cursor_default=0 nowatchdog")


class FakeBtrfs(snap.Btrfs):
    """Subvolume = adresar se znackou; snimek = kopie (ro si pamatuje)."""

    def __init__(self):
        self.ro = set()
        self.calls = []

    def snapshot(self, src, dst, readonly=True):
        self.calls.append(("snapshot", src, dst, readonly))
        shutil.copytree(src, dst, symlinks=True)
        if readonly:
            self.ro.add(dst)

    def create(self, path):
        self.calls.append(("create", path))
        os.makedirs(path)
        open(os.path.join(path, MARK), "w").close()

    def delete(self, path):
        self.calls.append(("delete", path))
        shutil.rmtree(path)
        self.ro.discard(path)

    def is_subvolume(self, path):
        return os.path.isfile(os.path.join(path, MARK))


class Env(unittest.TestCase):
    """Docasny koren (LUXOS_CARE_ROOT) a nejvyssi uroven btrfs (LUXOS_SNAPSHOT_TOP)."""
    layout = "sdboot"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-snap-test-")
        self.root = os.path.join(self.tmp, "root")
        self.top = os.path.join(self.tmp, "top")
        os.makedirs(self.root)
        self._old = care.ROOT
        care.ROOT = self.root
        self.fake = FakeBtrfs()
        self._btrfs = snap.BTRFS
        snap.BTRFS = self.fake
        self.cmds = []
        self.overlay_hook = True
        self.uuid = "1111-2222"
        patches = [mock.patch.object(snap, "sh", self.fake_sh),
                   mock.patch.dict(os.environ, {"LUXOS_SNAPSHOT_TOP": self.top}),
                   mock.patch.object(care, "engine_running", lambda: False),
                   mock.patch.object(care, "history", lambda *a, **k: None),
                   mock.patch.object(care, "log", lambda *a, **k: None),
                   mock.patch.object(care, "have", lambda c: c in ("mkinitcpio", "grub-editenv"))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.w("/etc/luxos/care.conf", "MODE=carefree\nKERNEL=linux-luxos\n")
        self.w("/proc/cmdline", "initrd=\\initramfs-linux-luxos.img " + OPTS + "\n")
        self.kernel(KVER, b"kernel-1")
        # system @ na nejvyssi urovni
        self.fake.create(os.path.join(self.top, "@"))
        self.sysfile("/etc/hostname", "luxos\n")
        self.w(snap.RECOVERY_BIN, "#!/bin/bash\n")
        if self.layout == "sdboot":
            self.mountinfo(boot="vfat")
            self.w("/boot/loader/loader.conf", "default luxos.conf\ntimeout 0\nconsole-mode max\neditor no\n")
            self.w("/boot/loader/entries/luxos.conf", "title   LuxOS\nlinux   /vmlinuz-linux-luxos\n"
                   "initrd  /initramfs-linux-luxos.img\noptions " + OPTS + "\n")
        else:
            self.mountinfo(boot="ext4")
            self.w("/boot/grub/grub.cfg", "### BEGIN /etc/grub.d/12_luxos_snapshots ###\n"
                   "source ${prefix}/luxos-snapshots.cfg\n")

    def tearDown(self):
        care.ROOT = self._old
        snap.BTRFS = self._btrfs
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- pomocne --
    def w(self, path, text=""):
        p = self.root + path
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb" if isinstance(text, bytes) else "w") as f:
            f.write(text)
        return p

    def r(self, path):
        with open(self.root + path) as f:
            return f.read()

    def sysfile(self, path, text):
        p = os.path.join(self.top, "@", path.lstrip("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def mountinfo(self, boot="vfat", root_line=None, extra=""):
        root_line = root_line or ("25 1 0:30 /@ / rw,noatime shared:1 - btrfs /dev/mapper/cryptroot "
                                  "rw,compress=zstd:1,subvolid=256,subvol=/@")
        lines = [root_line]
        if boot:
            lines.append(f"40 25 259:1 / /boot rw,relatime shared:2 - {boot} /dev/nvme0n1p1 rw")
        lines.append("41 25 0:30 /@home /home rw,noatime shared:3 - btrfs /dev/mapper/cryptroot "
                     "rw,subvolid=257,subvol=/@home")
        self.w("/proc/self/mountinfo", "\n".join(lines) + "\n" + extra)

    def kernel(self, ver, content, initramfs=None):
        """Nainstalovane jadro: moduly + /boot (initramfs s hookem podle self.overlay_hook)."""
        self.w(f"/usr/lib/modules/{ver}/vmlinuz", content)
        self.w(f"/usr/lib/modules/{ver}/pkgbase", "linux-luxos\n")
        self.w("/boot/vmlinuz-linux-luxos", content)
        self.w("/boot/initramfs-linux-luxos.img", initramfs or (b"initramfs-" + content))

    def fake_sh(self, cmd, timeout=600):
        self.cmds.append(cmd)
        if cmd[0] == "lsinitcpio":
            with open(cmd[-1], "rb") as f:
                data = f.read()
            ok = self.overlay_hook or b"rebuilt" in data
            return 0, "usr/lib/systemd/system/systemd-volatile-root.service\n" if ok else "usr/bin/systemd\n"
        if cmd[0] == "findmnt":
            return 0, self.uuid + "\n"
        return 0, ""

    def entries(self):
        d = self.root + "/boot/loader/entries"
        return sorted(os.listdir(d))

    def at(self, minute, second=0):
        return datetime.datetime(2026, 10, 26, 14, minute, second)


# ---- cista logika ------------------------------------------------------------------------
class Pure(unittest.TestCase):
    def test_entry_options_subvol_and_own_params(self):
        o = snap.entry_options(OPTS, "@snapshots/2026-10-26_14-03-12", ["luxos.snapshot=x", "systemd.volatile=overlay"])
        self.assertIn("rootflags=subvol=@snapshots/2026-10-26_14-03-12", o)
        self.assertNotIn("subvol=@ ", o + " ")
        self.assertEqual(o.count("rootflags="), 1)
        self.assertTrue(o.endswith("luxos.snapshot=x systemd.volatile=overlay"))
        self.assertIn("root=/dev/mapper/cryptroot", o)
        self.assertIn("rd.luks.name=abcd=cryptroot", o)

    def test_entry_options_keeps_other_rootflags(self):
        o = snap.entry_options("root=UUID=x rootflags=subvolid=256,subvol=/@,compress=zstd rw "
                               "rootflags=subvol=@,ssd BOOT_IMAGE=/vmlinuz luxos.snapshot=old systemd.unit=x.target",
                               "@snapshots/a")
        self.assertEqual(o, "root=UUID=x rw rootflags=subvol=@snapshots/a,ssd")

    def test_entry_options_without_rootflags_and_drop(self):
        o = snap.entry_options("root=UUID=x rw quiet splash", "@", ["systemd.unit=luxos-recovery.target"],
                               drop=snap.RECOVERY_DROP)
        self.assertEqual(o, "root=UUID=x rw rootflags=subvol=@ systemd.unit=luxos-recovery.target")

    def test_labels(self):
        self.assertEqual(snap.label({"name": "2026-10-26_14-03-12"}), "LuxOS (before update of 2026-10-26 14:03)")
        self.assertEqual(snap.label({"name": "2026-10-26_14-03-12", "kind": "before-rollback"}),
                         "LuxOS (before rollback of 2026-10-26 14:03)")
        self.assertEqual(snap.label({"name": "2026-10-26_14-03-12", "kind": "manual"}),
                         "LuxOS (snapshot of 2026-10-26 14:03)")
        self.assertEqual(snap.label({"name": "2026-10-26_14-03-12", "kind": "before-reinstall"}),
                         "LuxOS (before reinstall of 2026-10-26 14:03)")
        self.assertEqual(snap.label({"name": "2026-10-26_14-03-12", "kind": "system"}),
                         "LuxOS (before system change of 2026-10-26 14:03)")

    def test_prune_keeps_five_and_one_before_kernel_change(self):
        s = [{"name": f"2026-10-{d:02d}_10-00-00", "kver": "A" if d < 4 else "B"} for d in range(1, 11)]
        gone = [x["name"] for x in snap.to_prune(s, keep=5)]
        # zustane 06..10 (B) a 03 (posledni s jadrem A)
        self.assertEqual(gone, ["2026-10-01_10-00-00", "2026-10-02_10-00-00", "2026-10-04_10-00-00",
                                "2026-10-05_10-00-00"])

    def test_prune_same_kernel_and_protect(self):
        s = [{"name": f"2026-10-{d:02d}_10-00-00", "kver": "A"} for d in range(1, 9)]
        gone = [x["name"] for x in snap.to_prune(s, keep=5, protect={"2026-10-01_10-00-00"})]
        self.assertEqual(gone, ["2026-10-02_10-00-00", "2026-10-03_10-00-00"])
        self.assertEqual(snap.to_prune([], keep=5), [])

    def test_prune_kernel_change_within_kept(self):
        s = [{"name": f"2026-10-{d:02d}_10-00-00", "kver": "A" if d < 8 else "B"} for d in range(1, 11)]
        # posledni snimek s A (07) je mezi poslednimi peti - nic navic
        self.assertEqual(len(snap.to_prune(s, keep=5)), 5)

    def test_cmdline_values(self):
        self.assertEqual(snap.cmdline_value("luxos.snapshot", "a luxos.snapshot=1 b luxos.snapshot=2"), "2")
        self.assertIsNone(snap.cmdline_value("luxos.snapshot", "quiet splash"))
        self.assertEqual(snap.cmdline_value("quiet", "quiet splash"), "")


# ---- systemd-boot ------------------------------------------------------------------------
class SdBoot(Env):
    def test_supported(self):
        self.assertEqual(snap.supported(), (True, ""))
        self.w("/etc/luxos/care.conf", "KERNEL=linux-luxos\nSNAPSHOTS=no\n")
        self.assertEqual(snap.supported(), (False, "disabled"))
        self.w("/etc/luxos/care.conf", "KERNEL=linux-luxos\n")
        self.mountinfo(root_line="25 1 0:30 / / rw - ext4 /dev/sda2 rw")
        self.assertEqual(snap.supported(), (False, "not_btrfs"))
        self.mountinfo(root_line="25 1 0:30 / / rw - btrfs /dev/sda2 rw,subvolid=5,subvol=/")
        self.assertEqual(snap.supported(), (False, "no_subvolume"))
        self.w("/run/archiso", "")
        self.assertEqual(snap.supported(), (False, "live"))

    def test_create_snapshot_with_kernel_set(self):
        meta = snap.create(self.top, "update", ["firefox", "linux-luxos"], now=self.at(3, 12))
        self.assertEqual(meta["name"], "2026-10-26_14-03-12")
        dst = os.path.join(self.top, "@snapshots", meta["name"])
        self.assertIn(dst, self.fake.ro)                                  # jen pro cteni
        with open(os.path.join(dst, "etc/hostname")) as f:
            self.assertEqual(f.read(), "luxos\n")
        self.assertEqual(meta["kver"], KVER)
        self.assertEqual(meta["source"], "@")
        self.assertTrue(meta["overlay"])
        self.assertTrue(meta["recovery"])
        self.assertEqual(meta["packages"], ["firefox", "linux-luxos"])
        kdir = self.root + "/boot/luxos-snapshots/" + meta["kset"]
        with open(kdir + "/vmlinuz", "rb") as f:
            self.assertEqual(f.read(), b"kernel-1")
        with open(kdir + "/initramfs.img", "rb") as f:
            self.assertEqual(f.read(), b"initramfs-kernel-1")
        self.assertRegex(meta["kset"], r"^6\.17\.1-luxos1-1-[0-9a-f]{12}$")
        # popis lezi vedle snimku
        self.assertEqual(snap.read_meta(self.top, meta["name"])["kset"], meta["kset"])

    def test_kernel_set_shared_between_snapshots(self):
        a = snap.create(self.top, now=self.at(1))
        b = snap.create(self.top, now=self.at(2))
        self.assertEqual(a["kset"], b["kset"])
        self.assertEqual(os.listdir(self.root + "/boot/luxos-snapshots"), [a["kset"]])
        # nove initramfs se stejnym jadrem (napr. DKMS) = nova sada
        self.w("/boot/initramfs-linux-luxos.img", b"initramfs-dkms")
        c = snap.create(self.top, now=self.at(3))
        self.assertNotEqual(c["kset"], a["kset"])
        self.assertEqual(c["kver"], KVER)

    def test_same_minute_names_unique(self):
        a = snap.create(self.top, now=self.at(1, 5))
        b = snap.create(self.top, now=self.at(1, 5))
        self.assertEqual(b["name"], "2026-10-26_14-01-06")
        self.assertNotEqual(a["name"], b["name"])

    def test_kernel_mismatch_no_kernel_set(self):
        """Jadro v /boot nepatri k zadnym modulum systemu: snimek ano, polozka ne."""
        self.w("/boot/vmlinuz-linux-luxos", b"something-else")
        meta = snap.create(self.top, now=self.at(1))
        self.assertIsNone(meta["kset"])
        self.assertTrue(os.path.isdir(os.path.join(self.top, "@snapshots", meta["name"])))
        snap.sync_boot(self.top)
        self.assertFalse(any(e.startswith("snapshot-") for e in self.entries()))

    def test_initramfs_without_hook_is_rebuilt(self):
        self.overlay_hook = False
        built = []

        def build(ver, out):
            built.append(ver)
            with open(out, "wb") as f:
                f.write(b"rebuilt-initramfs")
            return True
        meta = snap.create(self.top, now=self.at(1), build=build)
        self.assertEqual(built, [KVER])
        self.assertTrue(meta["overlay"])
        with open(self.root + f"/boot/luxos-snapshots/{meta['kset']}/initramfs.img", "rb") as f:
            self.assertEqual(f.read(), b"rebuilt-initramfs")
        self.assertFalse(os.path.exists(self.root + f"/var/lib/luxos-care/kernel/snapshot-initramfs-{KVER}.img"))

    def test_initramfs_rebuild_fails_not_bootable(self):
        self.overlay_hook = False
        meta = snap.create(self.top, now=self.at(1), build=lambda v, o: False)
        self.assertFalse(meta["overlay"])
        snap.sync_boot(self.top)
        self.assertFalse(any(e.startswith("snapshot-") for e in self.entries()))

    def test_no_space_for_kernel(self):
        with mock.patch.object(care, "free_bytes", lambda p: 1000):
            meta = snap.create(self.top, now=self.at(1))
        self.assertIsNone(meta["kset"])
        self.assertFalse(os.path.exists(self.root + "/boot/luxos-snapshots/" + str(meta["kset"])))

    def test_boot_entries(self):
        meta = snap.create(self.top, now=self.at(3, 12))
        snap.sync_boot(self.top)
        self.assertEqual(self.entries(), ["luxos.conf", f"recovery-luxos.conf",
                                          f"snapshot-luxos-{meta['name']}.conf"])
        e = self.r(f"/boot/loader/entries/snapshot-luxos-{meta['name']}.conf")
        self.assertTrue(e.startswith(snap.ENTRY_MARK))
        self.assertIn("title   LuxOS (before update of 2026-10-26 14:03)", e)
        self.assertIn(f"linux   /luxos-snapshots/{meta['kset']}/vmlinuz", e)
        self.assertIn(f"initrd  /luxos-snapshots/{meta['kset']}/initramfs.img", e)
        self.assertIn(f"rootflags=subvol=@snapshots/{meta['name']}", e)
        self.assertIn(f"luxos.snapshot={meta['name']} systemd.volatile=overlay", e)
        self.assertIn("rd.luks.name=abcd=cryptroot", e)
        self.assertNotIn("sort-key", e)                 # hlavni polozka nema sort-key
        r = self.r("/boot/loader/entries/recovery-luxos.conf")
        self.assertIn("title   LuxOS Recovery", r)
        self.assertIn("systemd.unit=luxos-recovery.target", r)
        self.assertIn("plymouth.enable=0", r)
        self.assertNotIn(" quiet", r)
        self.assertNotIn("splash", r)
        self.assertNotIn("vt.global_cursor_default", r)
        # obnova startuje z nejnovejsiho snimku (system po vadne aktualizaci nemusi nabehnout)
        self.assertIn(f"rootflags=subvol=@snapshots/{meta['name']}", r)
        # hlavni polozka beze zmeny
        self.assertNotIn(snap.ENTRY_MARK, self.r("/boot/loader/entries/luxos.conf"))

    def test_entries_sort_key_with_care_layout(self):
        self.w("/boot/loader/loader.conf", "# luxos-care: x\ndefault luxos*\ntimeout 0\n")
        self.w("/boot/loader/entries/luxos+3.conf", "title   LuxOS\nsort-key luxos\nlinux   /vmlinuz-linux-luxos\n"
               "initrd  /initramfs-linux-luxos.img\noptions " + OPTS + "\n")
        os.unlink(self.root + "/boot/loader/entries/luxos.conf")
        meta = snap.create(self.top, now=self.at(1))
        snap.sync_boot(self.top)
        e = self.r(f"/boot/loader/entries/snapshot-luxos-{meta['name']}.conf")
        self.assertIn("sort-key luxos-snapshot", e)
        self.assertIn("sort-key luxos-system-recovery", self.r("/boot/loader/entries/recovery-luxos.conf"))
        # vzor "luxos*" (vychozi polozka) nesmi zahrnout snimky ani obnovu
        self.assertFalse(any(x.startswith("luxos") for x in self.entries() if snap.ENTRY_MARK in
                             self.r("/boot/loader/entries/" + x)))

    def test_recovery_without_snapshots_uses_main_kernel(self):
        snap.sync_boot(self.top)
        r = self.r("/boot/loader/entries/recovery-luxos.conf")
        self.assertIn("linux   /vmlinuz-linux-luxos", r)
        self.assertIn("initrd  /initramfs-linux-luxos.img", r)
        self.assertIn("rootflags=subvol=@ systemd.unit=luxos-recovery.target", r)
        self.assertNotIn("luxos.snapshot", r)

    def test_ensure_entries_once_after_install(self):
        """Cerstva instalace (zadny snimek): obnova se do nabidky prida po prvnim startu, jen jednou."""
        self.assertTrue(snap.ensure_entries())
        self.assertIn("recovery-luxos.conf", self.entries())
        self.assertFalse(snap.ensure_entries())
        self.w("/run/archiso", "")
        os.unlink(self.root + "/boot/loader/entries/recovery-luxos.conf")
        self.assertFalse(snap.ensure_entries())

    def test_stale_entries_removed_foreign_kept(self):
        a = snap.create(self.top, now=self.at(1))
        snap.sync_boot(self.top)
        self.w("/boot/loader/entries/snapshot-luxos-custom.conf", "title mine\n")   # cizi, bez znacky
        self.fake.delete(os.path.join(self.top, "@snapshots", a["name"]))
        snap.sync_boot(self.top)
        self.assertNotIn(f"snapshot-luxos-{a['name']}.conf", self.entries())
        self.assertIn("snapshot-luxos-custom.conf", self.entries())

    def test_shared_esp_layout(self):
        """Sdileny ESP (/efi): sady jadra v EFI/LuxOS/<id>/luxos-snapshots, nazvy podle polozky."""
        shutil.rmtree(self.root + "/boot/loader")
        self.w("/etc/luxos/esp.conf", "ESP_DIR=/efi/EFI/LuxOS/abcd1234\nKERNEL=linux-luxos\n")
        self.w("/efi/loader/loader.conf", "default luxos-abcd1234.conf\ntimeout 3\n")
        self.w("/efi/loader/entries/luxos-abcd1234.conf", "title   LuxOS\n"
               "linux   /EFI/LuxOS/abcd1234/vmlinuz-linux-luxos\ninitrd  /EFI/LuxOS/abcd1234/initramfs-linux-luxos.img\n"
               "options " + OPTS + "\n")
        self.w("/efi/loader/entries/other-debian.conf", "title Debian\nefi /EFI/debian/shimx64.efi\n")
        self.mountinfo(boot=None, extra="42 25 259:1 / /efi rw - vfat /dev/nvme0n1p1 rw\n")
        meta = snap.create(self.top, now=self.at(1))
        self.assertTrue(os.path.isfile(self.root + f"/efi/EFI/LuxOS/abcd1234/luxos-snapshots/{meta['kset']}/vmlinuz"))
        snap.sync_boot(self.top)
        ents = sorted(os.listdir(self.root + "/efi/loader/entries"))
        self.assertIn(f"snapshot-luxos-abcd1234-{meta['name']}.conf", ents)
        self.assertIn("recovery-luxos-abcd1234.conf", ents)
        e = self.r(f"/efi/loader/entries/snapshot-luxos-abcd1234-{meta['name']}.conf")
        self.assertIn(f"linux   /EFI/LuxOS/abcd1234/luxos-snapshots/{meta['kset']}/vmlinuz", e)
        self.assertEqual(self.r("/efi/loader/entries/other-debian.conf"), "title Debian\nefi /EFI/debian/shimx64.efi\n")

    def test_microcode_initrd_kept(self):
        self.w("/boot/loader/entries/luxos.conf", "title   LuxOS\nlinux   /vmlinuz-linux-luxos\n"
               "initrd  /intel-ucode.img\ninitrd  /initramfs-linux-luxos.img\noptions " + OPTS + "\n")
        meta = snap.create(self.top, now=self.at(1))
        snap.sync_boot(self.top)
        e = self.r(f"/boot/loader/entries/snapshot-luxos-{meta['name']}.conf").splitlines()
        initrds = [x for x in e if x.startswith("initrd")]
        self.assertEqual(initrds, ["initrd  /intel-ucode.img", f"initrd  /luxos-snapshots/{meta['kset']}/initramfs.img"])

    # -- hook pred transakci --
    def test_pre_transaction_creates_prunes_and_syncs(self):
        for m in range(8):
            snap.create(self.top, now=self.at(m))
        rc = snap.pre_transaction(["htop"], now=self.at(59))
        self.assertEqual(rc, 0)
        snaps = snap.list_snapshots(self.top)
        self.assertEqual(len(snaps), 5)
        self.assertEqual(snaps[-1]["packages"], ["htop"])
        self.assertEqual(len([e for e in self.entries() if e.startswith("snapshot-")]), 5)
        # popisy smazanych snimku pryc
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(self.top, "@snapshots")) if f.endswith(".json")),
                         sorted(s["name"] + ".json" for s in snaps))

    def test_pre_transaction_keeps_snapshot_before_kernel_change(self):
        for m in range(3):
            snap.create(self.top, now=self.at(m))
        self.kernel(KVER2, b"kernel-2")
        for m in range(3, 9):
            snap.create(self.top, now=self.at(m))
        snap.pre_transaction(["x"], now=self.at(9))
        snaps = snap.list_snapshots(self.top)
        self.assertEqual(len(snaps), 6)
        self.assertEqual([s["kver"] for s in snaps], [KVER] + [KVER2] * 5)
        self.assertEqual(snaps[0]["name"], "2026-10-26_14-02-00")
        # sady jadra: obe se pouzivaji
        self.assertEqual(len(os.listdir(self.root + "/boot/luxos-snapshots")), 2)
        # po dalsich peti s KVER2 se stare jadro drzi dal (je to "pred zmenou jadra")
        for m in range(10, 15):
            snap.create(self.top, now=self.at(m))
        snap.pre_transaction(["x"], now=self.at(59))
        self.assertEqual(snap.list_snapshots(self.top)[0]["kver"], KVER)

    def test_unused_kernel_sets_removed(self):
        snap.create(self.top, now=self.at(0))
        self.kernel(KVER2, b"kernel-2")
        self.w("/usr/lib/modules/" + KVER + "/pkgbase", "linux-luxos\n")
        for m in range(1, 7):
            snap.create(self.top, now=self.at(m))
        self.kernel("6.17.3-luxos1-1", b"kernel-3")
        for m in range(7, 14):
            snap.create(self.top, now=self.at(m))
        snap.pre_transaction([], now=self.at(59))
        kept = {s["kset"] for s in snap.list_snapshots(self.top)}
        self.assertEqual(set(os.listdir(self.root + "/boot/luxos-snapshots")), kept)
        self.assertEqual(len(kept), 2)

    def test_pre_transaction_skipped_after_system_apply_snapshot(self):
        # lux system apply uz snimek udelal (kind "system"); transakce uvnitr apply druhy nedela
        meta = snap.create(self.top, "system", now=self.at(0))
        self.assertEqual(meta["kind"], "system")
        with mock.patch.dict(os.environ, {"LUXOS_SNAPSHOT_TAKEN": "1"}):
            self.assertEqual(snap.pre_transaction(["htop"], now=self.at(1)), 0)
        self.assertEqual([s["name"] for s in snap.list_snapshots(self.top)], [meta["name"]])

    def test_pre_transaction_never_fails_update(self):
        with mock.patch.object(snap, "create", side_effect=OSError("disk full")):
            self.assertEqual(snap.pre_transaction(["x"]), 0)

    def test_pre_transaction_refused_in_snapshot_boot(self):
        self.w("/proc/cmdline", OPTS + " luxos.snapshot=2026-10-26_14-03-12 systemd.volatile=overlay\n")
        self.assertEqual(snap.pre_transaction(["x"]), 1)
        self.assertFalse(os.path.exists(os.path.join(self.top, "@snapshots")))

    def test_pre_transaction_in_chroot_does_nothing(self):
        self.w("/run/luxos-test-chroot", "")
        self.w("/proc/cmdline", OPTS + " luxos.snapshot=2026-10-26_14-03-12\n")
        self.assertEqual(snap.pre_transaction(["x"]), 0)
        self.assertFalse(os.path.exists(os.path.join(self.top, "@snapshots")))

    def test_pre_transaction_disabled(self):
        self.w("/etc/luxos/care.conf", "KERNEL=linux-luxos\nSNAPSHOTS=no\n")
        self.assertEqual(snap.pre_transaction(["x"]), 0)
        self.assertFalse(os.path.exists(os.path.join(self.top, "@snapshots")))

    def test_low_space_keeps_two(self):
        for m in range(6):
            snap.create(self.top, now=self.at(m))
        with mock.patch.object(snap, "free_ok", lambda p: False):
            snap.prune(self.top)
        self.assertEqual(len(snap.list_snapshots(self.top)), 2)

    def test_keep_from_config(self):
        self.w("/etc/luxos/care.conf", "KERNEL=linux-luxos\nSNAPSHOT_KEEP=3\n")
        for m in range(6):
            snap.create(self.top, now=self.at(m))
        snap.prune(self.top)
        self.assertEqual(len(snap.list_snapshots(self.top)), 3)
        self.w("/etc/luxos/care.conf", "KERNEL=linux-luxos\nSNAPSHOT_KEEP=nonsense\n")
        self.assertEqual(snap.configured_keep(), 5)

    def test_booted_snapshot_never_pruned(self):
        for m in range(7):
            snap.create(self.top, now=self.at(m))
        self.w("/proc/cmdline", OPTS + " luxos.snapshot=2026-10-26_14-00-00\n")
        snap.prune(self.top)
        names = [s["name"] for s in snap.list_snapshots(self.top)]
        self.assertIn("2026-10-26_14-00-00", names)
        self.assertEqual(len(names), 6)

    # -- navrat --
    def test_rollback_same_kernel(self):
        a = snap.create(self.top, now=self.at(1))
        self.sysfile("/etc/hostname", "changed\n")
        res = snap.rollback(self.top, a["name"], now=self.at(30))
        self.assertEqual(res["replaced"], "2026-10-26_14-30-00")
        with open(os.path.join(self.top, "@/etc/hostname")) as f:
            self.assertEqual(f.read(), "luxos\n")
        # novy @ je zapisovatelny, puvodni system je odlozeny jako snimek (nic se nesmazalo)
        self.assertNotIn(os.path.join(self.top, "@"), self.fake.ro)
        with open(os.path.join(self.top, "@snapshots", res["replaced"], "etc/hostname")) as f:
            self.assertEqual(f.read(), "changed\n")
        m = snap.read_meta(self.top, res["replaced"])
        self.assertEqual(m["kind"], "before-rollback")
        self.assertEqual(m["kset"], a["kset"])
        # poznamka pro prvni start a odklad automatickych aktualizaci
        with open(os.path.join(self.top, "@", snap.AFTER_ROLLBACK.lstrip("/"))) as f:
            flag = json.load(f)
        self.assertEqual(flag["to"], a["name"])
        with open(os.path.join(self.top, "@/var/lib/luxos-care/state.json")) as f:
            self.assertGreater(json.load(f)["next_attempt"], care.now() + 2 * 24 * 3600)
        self.assertIn(f"snapshot-luxos-{res['replaced']}.conf", self.entries())
        self.assertIn("title   LuxOS (before rollback of 2026-10-26 14:30)",
                      self.r(f"/boot/loader/entries/snapshot-luxos-{res['replaced']}.conf"))

    def test_rollback_restores_kernel_of_snapshot(self):
        self.w("/boot/initramfs-linux-luxos-fallback.img", b"fallback-1")
        a = snap.create(self.top, now=self.at(1))
        self.kernel(KVER2, b"kernel-2")                 # aktualizace jadra po snimku
        self.w("/boot/loader/entries/luxos+0-3.conf", self.r("/boot/loader/entries/luxos.conf"))
        os.unlink(self.root + "/boot/loader/entries/luxos.conf")
        res = snap.rollback(self.top, a["name"], now=self.at(30))
        with open(self.root + "/boot/vmlinuz-linux-luxos", "rb") as f:
            self.assertEqual(f.read(), b"kernel-1")
        with open(self.root + "/boot/initramfs-linux-luxos.img", "rb") as f:
            self.assertEqual(f.read(), b"initramfs-kernel-1")
        with open(self.root + "/boot/initramfs-linux-luxos-fallback.img", "rb") as f:
            self.assertEqual(f.read(), b"initramfs-kernel-1")
        # nahrazeny system si nese nove jadro (lze se k nemu vratit)
        m = snap.read_meta(self.top, res["replaced"])
        self.assertEqual(m["kver"], KVER2)
        self.assertTrue(os.path.isfile(self.root + f"/boot/luxos-snapshots/{m['kset']}/vmlinuz"))
        # pocitadlo pokusu pryc (navrat = znamy dobry stav)
        self.assertIn("luxos.conf", self.entries())
        self.assertNotIn("luxos+0-3.conf", self.entries())

    def test_rollback_kernel_missing_refused(self):
        a = snap.create(self.top, now=self.at(1))
        shutil.rmtree(self.root + "/boot/luxos-snapshots")
        self.kernel(KVER2, b"kernel-2")
        with self.assertRaises(snap.SnapshotError) as cm:
            snap.rollback(self.top, a["name"], now=self.at(30))
        self.assertEqual(cm.exception.code, "kernel_missing")
        # nic se nezmenilo
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(self.top, "@snapshots")) if f != MARK),
                         [a["name"], a["name"] + ".json"])
        with open(self.root + "/boot/vmlinuz-linux-luxos", "rb") as f:
            self.assertEqual(f.read(), b"kernel-2")

    def test_rollback_unknown_and_busy(self):
        with self.assertRaises(snap.SnapshotError) as cm:
            snap.rollback(self.top, "2020-01-01_00-00-00")
        self.assertEqual(cm.exception.code, "not_found")
        with self.assertRaises(snap.SnapshotError):
            snap.rollback(self.top, "../@")
        a = snap.create(self.top, now=self.at(1))
        self.w("/var/lib/lux/db.lck", "")
        with mock.patch.object(care, "engine_running", lambda: True):
            with self.assertRaises(snap.SnapshotError) as cm:
                snap.rollback(self.top, a["name"])
        self.assertEqual(cm.exception.code, "busy")

    def test_rollback_snapshot_failure_restores_system(self):
        a = snap.create(self.top, now=self.at(1))
        self.sysfile("/etc/hostname", "current\n")
        with mock.patch.object(self.fake, "snapshot", side_effect=snap.SnapshotError("snapshot_failed")):
            with self.assertRaises(snap.SnapshotError):
                snap.rollback(self.top, a["name"], now=self.at(30))
        with open(os.path.join(self.top, "@/etc/hostname")) as f:
            self.assertEqual(f.read(), "current\n")
        self.assertFalse(os.path.exists(os.path.join(self.top, "@snapshots", "2026-10-26_14-30-00")))

    def test_rollback_kernel_copy_failure_undone(self):
        a = snap.create(self.top, now=self.at(1))
        self.kernel(KVER2, b"kernel-2")
        self.sysfile("/etc/hostname", "current\n")
        real = snap.copy_boot
        calls = []

        def failing(files, vml, img):
            calls.append(vml)
            if len(calls) == 1:
                raise OSError("ESP read-only")
            return real(files, vml, img)
        with mock.patch.object(snap, "copy_boot", failing):
            with self.assertRaises(snap.SnapshotError) as cm:
                snap.rollback(self.top, a["name"], now=self.at(30))
        self.assertEqual(cm.exception.code, "kernel_copy_failed")
        with open(os.path.join(self.top, "@/etc/hostname")) as f:
            self.assertEqual(f.read(), "current\n")
        with open(self.root + "/boot/vmlinuz-linux-luxos", "rb") as f:
            self.assertEqual(f.read(), b"kernel-2")

    def test_rollback_from_snapshot_boot(self):
        """Start ze snimku (overlay): jadro hlavni polozky patri k modulum v @, ne ve snimku."""
        a = snap.create(self.top, now=self.at(1))
        # aktualizace: system @ dostal nove jadro, /boot taky
        self.kernel(KVER2, b"kernel-2")
        os.makedirs(os.path.join(self.top, "@/usr/lib/modules", KVER2))
        shutil.copy(self.root + f"/usr/lib/modules/{KVER2}/vmlinuz", os.path.join(self.top, "@/usr/lib/modules", KVER2))
        # bezici system = snimek (modulu noveho jadra nema)
        shutil.rmtree(self.root + f"/usr/lib/modules/{KVER2}")
        self.w("/proc/cmdline", OPTS + f" luxos.snapshot={a['name']} systemd.volatile=overlay\n")
        self.mountinfo(root_line="25 1 0:50 / / rw - overlay overlay rw,lowerdir=/run/x")
        self.assertEqual(snap.booted_snapshot(), a["name"])
        self.assertEqual(snap.system_subvol(self.top), "@")
        res = snap.rollback(self.top, snap.booted_snapshot(), now=self.at(40))
        m = snap.read_meta(self.top, res["replaced"])
        self.assertEqual(m["kver"], KVER2)                  # nove jadro poznane z modulu v @
        with open(self.root + "/boot/vmlinuz-linux-luxos", "rb") as f:
            self.assertEqual(f.read(), b"kernel-1")

    def test_root_device_in_snapshot_boot(self):
        self.mountinfo(root_line="25 1 0:50 / / rw - overlay overlay rw")
        self.w("/proc/cmdline", "root=UUID=abcd rw luxos.snapshot=x\n")
        self.assertEqual(snap.root_device(), "/dev/disk/by-uuid/abcd")
        self.w("/proc/cmdline", "root=/dev/mapper/cryptroot rw\n")
        self.assertEqual(snap.root_device(), "/dev/mapper/cryptroot")
        self.w("/proc/cmdline", "rw\n")
        self.assertEqual(snap.root_device(), "/dev/mapper/cryptroot")     # z @home
        self.mountinfo()
        self.assertEqual(snap.root_device(), "/dev/mapper/cryptroot")

    def test_after_rollback(self):
        self.w(snap.AFTER_ROLLBACK, json.dumps({"from": "a", "to": "b", "label": "LuxOS (x)", "kind": "before-rollback"}))
        with mock.patch.object(care, "add_event") as ev:
            snap.after_rollback()
        self.assertFalse(os.path.exists(self.root + snap.AFTER_ROLLBACK))
        self.assertIn(["mkinitcpio", "-P"], self.cmds)
        ev.assert_called_once_with("rolled_back", label="LuxOS (x)", kind="before-rollback")

    def test_describe_and_hint(self):
        a = snap.create(self.top, "manual", now=self.at(1))
        d = snap.describe(self.top)
        self.assertEqual(d[0]["label"], "LuxOS (snapshot of 2026-10-26 14:01)")
        self.assertTrue(d[0]["bootable"])
        self.assertFalse(d[0]["booted"])
        self.assertIsNone(snap.status_hint())
        self.w("/proc/cmdline", OPTS + f" luxos.snapshot={a['name']}\n")
        self.assertEqual(snap.status_hint()["date"], "2026-10-26 14:01")
        self.assertTrue(snap.describe(self.top)[0]["booted"])


# ---- GRUB (BIOS) ---------------------------------------------------------------------------
class Grub(Env):
    layout = "grub"

    def test_grub_cfg(self):
        meta = snap.create(self.top, now=self.at(3, 12))
        self.assertTrue(os.path.isfile(self.root + f"/boot/luxos-snapshots/{meta['kset']}/vmlinuz"))
        snap.sync_boot(self.top)
        cfg = self.r(snap.GRUB_CFG)
        self.assertIn("menuentry 'LuxOS (before update of 2026-10-26 14:03)'", cfg)
        self.assertIn(f"search --no-floppy --fs-uuid --set=root {self.uuid}", cfg)
        self.assertIn(f"\tlinux\t/luxos-snapshots/{meta['kset']}/vmlinuz ", cfg)
        self.assertIn(f"\tinitrd\t/luxos-snapshots/{meta['kset']}/initramfs.img", cfg)
        self.assertIn(f"rootflags=subvol=@snapshots/{meta['name']}", cfg)
        self.assertNotIn("initrd=\\initramfs", cfg)              # z /proc/cmdline jen volby
        self.assertIn("menuentry 'LuxOS Recovery'", cfg)
        # grub.cfg uz luxos-snapshots.cfg nacita: zadny grub-mkconfig
        self.assertFalse(any(c[0] == "grub-mkconfig" for c in self.cmds))

    def test_grub_mkconfig_once(self):
        self.w("/boot/grub/grub.cfg", "menuentry LuxOS {}\n")
        with mock.patch.object(care, "have", lambda c: True):
            snap.create(self.top, now=self.at(1))
            snap.sync_boot(self.top)
        self.assertIn(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"], self.cmds)

    def test_grub_recovery_main_kernel(self):
        snap.sync_boot(self.top)
        cfg = self.r(snap.GRUB_CFG)
        self.assertIn("\tlinux\t/vmlinuz-linux-luxos ", cfg)
        self.assertIn("systemd.unit=luxos-recovery.target", cfg)
        self.assertNotIn("splash", cfg)

    def test_grub_boot_in_root_uses_top_level(self):
        """/boot uvnitr systemoveho btrfs: sady jadra v @snapshots/.kernels (GRUB cte btrfs)."""
        self.mountinfo(boot=None)
        meta = snap.create(self.top, now=self.at(1))
        self.assertTrue(os.path.isfile(os.path.join(self.top, "@snapshots/.kernels", meta["kset"], "vmlinuz")))
        snap.sync_boot(self.top)
        cfg = self.r(snap.GRUB_CFG)
        self.assertIn(f"\tlinux\t/@snapshots/.kernels/{meta['kset']}/vmlinuz", cfg)
        # snimek s /boot uvnitr lze vratit i bez sady (ma vlastni /boot)
        self.assertIn(".kernels", os.listdir(os.path.join(self.top, "@snapshots")))
        self.assertEqual([s["name"] for s in snap.list_snapshots(self.top)], [meta["name"]])

    def test_grub_rollback_copies_kernel(self):
        a = snap.create(self.top, now=self.at(1))
        self.kernel(KVER2, b"kernel-2")
        with mock.patch.object(care, "have", lambda c: c == "grub-editenv"):
            snap.rollback(self.top, a["name"], now=self.at(30))
        with open(self.root + "/boot/vmlinuz-linux-luxos", "rb") as f:
            self.assertEqual(f.read(), b"kernel-1")
        self.assertIn(["grub-editenv", "/boot/grub/grubenv", "unset", "luxos_tries"], self.cmds)


if __name__ == "__main__":
    unittest.main()
