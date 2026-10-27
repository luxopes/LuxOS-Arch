"""Testy obnovy (luxos_recovery): slouceni uctu, prenos nastaveni a sluzeb, kontrola disku
a preinstalace se zachovanim /home - bez roota, prikazy a btrfs jsou nahrazene.

    python3 -m unittest discover -s packages/luxos-care/tests -v
"""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "files"))
sys.path.insert(0, HERE)

import luxos_care as care  # noqa: E402
import luxos_recovery as rec  # noqa: E402
import luxos_snapshots as snap  # noqa: E402
from test_snapshots import KVER, Env  # noqa: E402

OLD = {
    "etc/passwd": "root:x:0:0::/root:/usr/bin/bash\npolkitd:x:102:102::/:/usr/bin/nologin\n"
                  "anna:x:1000:1000:Anna:/home/anna:/usr/bin/lsh\nhost:x:1001:1001::/home/host:/usr/bin/lsh\n",
    "etc/shadow": "root:!*::::::\npolkitd:!*::::::\nanna:$6$hash:20000::::::\nhost:$6$h2:20000::::::\n",
    "etc/group": "root:x:0:root\nwheel:x:998:anna\nvideo:x:985:anna,host\npolkitd:x:102:\n"
                 "anna:x:1000:\nhost:x:1001:\nshared:x:1002:anna,host\n",
    "etc/gshadow": "root:::root\nwheel:!*::anna\nvideo:!*::anna,host\nanna:!::\nhost:!::\nshared:!::anna,host\n",
}
NEW = {
    "etc/passwd": "root:x:0:0::/root:/usr/bin/bash\npolkitd:x:981:981::/:/usr/bin/nologin\n",
    "etc/shadow": "root:!*::::::\npolkitd:!*::::::\n",
    "etc/group": "root:x:0:root\nwheel:x:998:\nvideo:x:985:\npolkitd:x:981:\nnewgrp:x:970:\n",
    "etc/gshadow": "root:::root\nwheel:!*::\nvideo:!*::\npolkitd:!*::\nnewgrp:!*::\n",
}


class Accounts(unittest.TestCase):
    def test_human_users(self):
        self.assertEqual(rec.human_users(OLD["etc/passwd"]), ["anna", "host"])

    def test_merge(self):
        m = rec.merge_accounts(OLD, NEW)
        p = m["etc/passwd"]
        # systemove ucty z noveho systemu (UID odpovida souborum baliku), lidske z puvodniho
        self.assertIn("polkitd:x:981:981::/:/usr/bin/nologin\n", p)
        self.assertNotIn("polkitd:x:102", p)
        self.assertIn("anna:x:1000:1000:Anna:/home/anna:/usr/bin/lsh\n", p)
        self.assertIn("anna:$6$hash:20000::::::\n", m["etc/shadow"])
        g = m["etc/group"]
        self.assertIn("wheel:x:998:anna\n", g)
        self.assertIn("video:x:985:anna,host\n", g)
        self.assertIn("polkitd:x:981:\n", g)
        self.assertIn("newgrp:x:970:\n", g)
        self.assertIn("anna:x:1000:\n", g)
        self.assertIn("shared:x:1002:anna,host\n", g)
        self.assertIn("wheel:!*::anna\n", m["etc/gshadow"])
        self.assertIn("shared:!::anna,host\n", m["etc/gshadow"])

    def test_merge_idempotent_members(self):
        new = dict(NEW, **{"etc/group": "wheel:x:998:anna\n"})
        self.assertEqual(rec.merge_accounts(OLD, new)["etc/group"].splitlines()[0], "wheel:x:998:anna")


class Recovery(Env):
    def setUp(self):
        super().setUp()
        self.old = os.path.join(self.top, "@")
        self.files_old()
        self.installed = []

    def files_old(self):
        for f, t in OLD.items():
            self.sysfile("/" + f, t)
        self.sysfile("/etc/locale.conf", "LANG=cs_CZ.UTF-8\n")
        self.sysfile("/etc/mkinitcpio.conf.d/luxos.conf", "HOOKS=(base systemd sd-encrypt)\n")
        self.sysfile("/etc/NetworkManager/system-connections/Home.nmconnection", "[wifi]\n")
        self.sysfile("/etc/broken-by-user.conf", "junk\n")
        os.makedirs(os.path.join(self.old, "etc/systemd/system/multi-user.target.wants"))
        os.symlink("/usr/lib/systemd/system/NetworkManager.service",
                   os.path.join(self.old, "etc/systemd/system/multi-user.target.wants/NetworkManager.service"))
        os.symlink("/usr/lib/systemd/system/gone.service",
                   os.path.join(self.old, "etc/systemd/system/multi-user.target.wants/gone.service"))
        os.symlink("/usr/lib/systemd/system/graphical.target",
                   os.path.join(self.old, "etc/systemd/system/default.target"))

    def fake_sh(self, cmd, timeout=600):
        if cmd[0] == care.ENGINE and "-Qqen" in cmd:
            self.cmds.append(cmd)
            return 0, "base\nfirefox\nlinux-luxos\nluxos-desktop\n"
        if cmd[0] == care.ENGINE and "-Qqem" in cmd:
            self.cmds.append(cmd)
            return 0, "yay-bin\n"
        if cmd[0] == care.ENGINE and "-Sy" in cmd:
            self.cmds.append(cmd)
            if getattr(self, "install_fails", False):
                return 1, "error: failed to retrieve some files"
            new = cmd[cmd.index("--root") + 1]
            self.installed = cmd[cmd.index("--") + 1:]
            for f, t in NEW.items():
                p = os.path.join(new, f)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w") as fh:
                    fh.write(t)
            os.makedirs(os.path.join(new, "usr/lib/systemd/system"), exist_ok=True)
            for u in ("NetworkManager.service", "graphical.target"):
                open(os.path.join(new, "usr/lib/systemd/system", u), "w").close()
            with open(os.path.join(new, "etc/hostname"), "w") as fh:
                fh.write("archlinux\n")
            # instalace jadra prepise /boot (mkinitcpio v chrootu)
            self.w("/boot/vmlinuz-linux-luxos", b"kernel-new")
            self.w("/boot/initramfs-linux-luxos.img", b"initramfs-new")
            return 0, ""
        return super().fake_sh(cmd, timeout)

    def test_reinstall(self):
        res = rec.reinstall(self.top, out=lambda *a: None, now=self.at(45))
        self.assertEqual(res["kept"], "2026-10-26_14-45-00")
        self.assertEqual(res["foreign"], ["yay-bin"])
        for p in ("base", "firefox", "linux-luxos", "luxos-desktop", "lux-engine", "lux", "luxos-care"):
            self.assertIn(p, self.installed)
        new = os.path.join(self.top, "@")
        with open(os.path.join(new, "etc/hostname")) as f:
            self.assertEqual(f.read(), "luxos\n")                         # prenesene nastaveni
        self.assertTrue(os.path.exists(os.path.join(new, "etc/NetworkManager/system-connections/Home.nmconnection")))
        self.assertFalse(os.path.exists(os.path.join(new, "etc/broken-by-user.conf")))   # zbytek je cisty
        with open(os.path.join(new, "etc/passwd")) as f:
            self.assertIn("anna:x:1000", f.read())
        self.assertTrue(os.path.islink(os.path.join(new, "etc/systemd/system/multi-user.target.wants/NetworkManager.service")))
        self.assertFalse(os.path.lexists(os.path.join(new, "etc/systemd/system/multi-user.target.wants/gone.service")))
        self.assertTrue(os.path.islink(os.path.join(new, "etc/systemd/system/default.target")))
        # puvodni system je snimek "pred preinstalaci" s puvodnim jadrem
        kept = os.path.join(self.top, "@snapshots", res["kept"])
        with open(os.path.join(kept, "etc/broken-by-user.conf")) as f:
            self.assertEqual(f.read(), "junk\n")
        m = snap.read_meta(self.top, res["kept"])
        self.assertEqual(m["kind"], "before-reinstall")
        self.assertEqual(m["kver"], KVER)
        self.assertTrue(os.path.isfile(self.root + f"/boot/luxos-snapshots/{m['kset']}/vmlinuz"))
        self.assertFalse(os.path.exists(os.path.join(self.top, rec.NEW_SUBVOL)))
        self.assertIn(["chroot", os.path.join(self.top, rec.NEW_SUBVOL), "mkinitcpio", "-P"], self.cmds)
        # vse odpojeno
        mounted = [c[-1] for c in self.cmds if c[0] == "mount"]
        unmounted = [c[-1] for c in self.cmds if c[:2] == ["umount", "-R"]]
        self.assertEqual(sorted(mounted), sorted(unmounted))
        self.assertTrue(any(c[-1].endswith("/boot") and "--bind" in c for c in self.cmds if c[0] == "mount"))
        self.assertIn(f"snapshot-luxos-{res['kept']}.conf", self.entries())

    def test_reinstall_failure_keeps_system_and_kernel(self):
        self.install_fails = True
        self.real_install = self.fake_sh

        def failing_after_kernel(cmd, timeout=600):
            if cmd[0] == care.ENGINE and "-Sy" in cmd:
                self.w("/boot/vmlinuz-linux-luxos", b"kernel-new")
                return 1, "error: failed to retrieve some files"
            return self.real_install(cmd, timeout)
        with mock.patch.object(snap, "sh", failing_after_kernel):
            with self.assertRaises(snap.SnapshotError) as cm:
                rec.reinstall(self.top, out=lambda *a: None, now=self.at(45))
        self.assertEqual(cm.exception.code, "install_failed")
        with open(os.path.join(self.top, "@/etc/broken-by-user.conf")) as f:
            self.assertEqual(f.read(), "junk\n")
        self.assertFalse(os.path.exists(os.path.join(self.top, rec.NEW_SUBVOL)))
        with open(self.root + "/boot/vmlinuz-linux-luxos", "rb") as f:
            self.assertEqual(f.read(), b"kernel-1")                       # puvodni jadro zpet

    def test_reinstall_refused_without_saved_kernel(self):
        self.w("/boot/vmlinuz-linux-luxos", b"unknown")
        with self.assertRaises(snap.SnapshotError) as cm:
            rec.reinstall(self.top, out=lambda *a: None)
        self.assertEqual(cm.exception.code, "kernel_not_saved")
        self.assertFalse(any("-Sy" in c for c in self.cmds))

    def test_reinstall_leftover_removed(self):
        self.fake.create(os.path.join(self.top, rec.NEW_SUBVOL))
        rec.reinstall(self.top, out=lambda *a: None, now=self.at(45))
        self.assertIn(("delete", os.path.join(self.top, rec.NEW_SUBVOL)), self.fake.calls)

    def test_disk_check_readonly(self):
        res = rec.disk_check(self.top, repair=False, out=lambda *a: None)
        self.assertTrue(all(ok for _t, ok, _o in res))
        self.assertIn(["btrfs", "scrub", "start", "-B", "-d", "-r", self.top], self.cmds)
        self.assertIn(["btrfs", "check", "--readonly", "--force", "/dev/mapper/cryptroot"], self.cmds)
        self.assertIn(["fsck.fat", "-n", "/dev/nvme0n1p1"], self.cmds)
        self.assertFalse(any(c[0] in ("umount", "mount") for c in self.cmds))
        self.assertFalse(any("--repair" in c for c in self.cmds))

    def test_disk_check_repair(self):
        rec.disk_check(self.top, repair=True, out=lambda *a: None)
        self.assertIn(["btrfs", "scrub", "start", "-B", "-d", self.top], self.cmds)
        i = self.cmds.index(["umount", "/boot"])
        self.assertEqual(self.cmds[i + 1], ["fsck.fat", "-a", "-w", "/dev/nvme0n1p1"])
        self.assertEqual(self.cmds[i + 2], ["mount", "/boot"])
        self.assertFalse(any("--repair" in c for c in self.cmds))

    DIRTY = ("fsck.fat 4.2 (2021-01-31)\n"
             "There are differences between boot sector and its backup.\n"
             "This is mostly harmless. Differences: (offset:original/backup)\n"
             "  65:01/00\n"
             "  Not automatically fixing this.\n"
             "Dirty bit is set. Fs was not properly unmounted and some data may be corrupt.\n"
             " Automatically removing dirty bit.\n"
             "\n"
             "Leaving filesystem unchanged.\n"
             "/dev/nvme0n1p1: 12 files, 3000/129022 clusters\n")

    def test_fat_only_dirty(self):
        self.assertTrue(rec.fat_only_dirty(self.DIRTY))
        self.assertTrue(rec.fat_only_dirty(self.DIRTY.replace("  65:01/00", "  37:01/00")))
        self.assertFalse(rec.fat_only_dirty(self.DIRTY.replace("  65:01/00", "  3:4d/53")))
        self.assertFalse(rec.fat_only_dirty(self.DIRTY.replace(
            "Leaving", "/EFI/BOOT/BOOTX64.EFI\n  File size is 0 bytes, cluster chain length is > 0.\nLeaving")))
        self.assertFalse(rec.fat_only_dirty("fsck.fat 4.2 (2021-01-31)\n/dev/x: 1 files, 1/2 clusters\n"))

    def test_disk_check_mounted_fat_dirty_is_ok(self):
        """Pripojeny ESP ma od jadra vzdy priznak dirty - kontrola ho nehlasi jako chybu."""
        def sh(cmd, timeout=600):
            self.cmds.append(cmd)
            return (1, self.DIRTY) if cmd[0] == "fsck.fat" else (0, "")
        with mock.patch.object(snap, "sh", sh):
            res = rec.disk_check(self.top, out=lambda *a: None)
        self.assertTrue(all(ok for _t, ok, _o in res), res)

    def test_disk_check_reports_errors(self):
        def sh(cmd, timeout=600):
            self.cmds.append(cmd)
            return (4, "FAT corrupted") if cmd[0] == "fsck.fat" else (0, "")
        with mock.patch.object(snap, "sh", sh):
            res = rec.disk_check(self.top, out=lambda *a: None)
        self.assertEqual([t for t, ok, _o in res if not ok], ["fsck /boot"])


if __name__ == "__main__":
    unittest.main()
