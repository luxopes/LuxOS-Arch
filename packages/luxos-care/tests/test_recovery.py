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
        os.symlink("/usr/lib/systemd/system/lightdm.service",
                   os.path.join(self.old, "etc/systemd/system/display-manager.service"))
        self.sysfile("/etc/lux/keyring/pubring.gpg", "keys")
        self.sysfile("/etc/subuid", "anna:100000:65536\n")

    def fake_sh(self, cmd, timeout=600):
        if cmd[0] == care.ENGINE and "-Qii" in cmd:
            # skutecny vystup lux-engine (VM): "cesta [modified]"
            return 0, ("Name            : lux-engine\nBackup Files    : /etc/lux/lux.conf [modified]\n"
                       "                  /etc/sysctl.d/99-mine.conf [modified]\n"
                       "                  /etc/default/useradd [unmodified]\n"
                       "Name            : x\nBackup Files    : /etc/makepkg.conf [modified]\n"
                       "Name            : y\nBackup Files    : None\n")
        if cmd[0] == care.ENGINE and "-Qlq" in cmd:
            # s --root jsou cesty i s korenem
            r = cmd[cmd.index("--root") + 1]
            return 0, "".join(r + p + "\n" for p in ("/etc/", "/etc/sysctl.d/", "/etc/sysctl.d/99-mine.conf",
                                                     "/etc/makepkg.conf", "/etc/locale.conf", "/etc/ssl/"))
        if cmd[:3] == ["cp", "-a", "--reflink=auto"]:
            self.cmds.append(cmd)
            import shutil
            shutil.copytree(cmd[3], cmd[4], symlinks=True)
            return 0, ""
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
            for u in ("NetworkManager.service", "graphical.target", "lightdm.service"):
                open(os.path.join(new, "usr/lib/systemd/system", u), "w").close()
            with open(os.path.join(new, "etc/hostname"), "w") as fh:
                fh.write("archlinux\n")
            # instalace jadra prepise /boot (mkinitcpio v chrootu)
            self.w("/boot/vmlinuz-linux-luxos", b"kernel-new")
            self.w("/boot/initramfs-linux-luxos.img", b"initramfs-new")
            return 0, ""
        return super().fake_sh(cmd, timeout)

    def test_reinstall_plan(self):
        """Pred potvrzenim: cizi baliky jmenem, zmenena nastaveni (mimo prenasena), co zustane; nic se nemeni."""
        self.sysfile("/var/lib/flatpak/app/org.gimp.GIMP/x", "1")
        self.sysfile("/opt/myapp/run", "1")
        os.makedirs(os.path.join(self.old, "opt/lux"))                      # prazdna slozka LuxOS
        os.makedirs(os.path.join(self.old, "usr/local/bin"), exist_ok=True)
        os.symlink("/usr/bin/luxos-text", os.path.join(self.old, "usr/local/bin/mousepad"))
        self.sysfile("/etc/ssl/certs/ca.pem", "x")                       # generovany - neni ztrata
        before = sorted(os.walk(self.top))
        plan = rec.reinstall_plan(self.top)
        self.assertEqual(plan["foreign"], ["yay-bin"])
        self.assertEqual(plan["flatpaks"], ["org.gimp.GIMP"])
        self.assertEqual(plan["users"], ["anna", "host"])
        self.assertEqual(plan["wifi"], ["Home"])
        self.assertEqual(plan["extra"], ["/opt/myapp"])
        # /etc/lux/lux.conf a locale.conf se prenaseji; makepkg.conf a sysctl zmenene, broken-by-user mimo baliky
        self.assertEqual(plan["settings"], ["/etc/broken-by-user.conf", "/etc/makepkg.conf",
                                            "/etc/sysctl.d/99-mine.conf"])
        self.assertEqual(sorted(os.walk(self.top)), before)
        self.assertFalse(any("-Sy" in c for c in self.cmds))

    def test_reinstall_keeps_flatpak_apps(self):
        self.sysfile("/var/lib/flatpak/app/org.gimp.GIMP/current", "gimp")
        rec.reinstall(self.top, out=lambda *a: None, now=self.at(45))
        with open(os.path.join(self.top, "@/var/lib/flatpak/app/org.gimp.GIMP/current")) as f:
            self.assertEqual(f.read(), "gimp")

    def test_reinstall(self):
        res = rec.reinstall(self.top, out=lambda *a: None, now=self.at(45))
        self.assertEqual(res["kept"], "2026-10-26_14-45-00")
        self.assertEqual(res["foreign"], ["yay-bin"])
        inst = [c for c in self.cmds if c[0] == care.ENGINE and "-Sy" in c][0]
        self.assertIn("--disable-sandbox", inst)        # stahovani pod alpm do /run/luxos-snapshots (0700) selze
        self.assertEqual(inst[inst.index("--overwrite") + 1], "boot/*")   # ucode na ESP puvodniho systemu
        for p in ("base", "firefox", "linux-luxos", "luxos-desktop", "lux-engine", "lux", "luxos-care"):
            self.assertIn(p, self.installed)
        new = os.path.join(self.top, "@")
        with open(os.path.join(new, "etc/hostname")) as f:
            self.assertEqual(f.read(), "luxos\n")                         # prenesene nastaveni
        self.assertTrue(os.path.exists(os.path.join(new, "etc/NetworkManager/system-connections/Home.nmconnection")))
        self.assertTrue(os.path.exists(os.path.join(new, care.VERIFY_BOOT.lstrip("/"))))
        self.assertFalse(os.path.exists(os.path.join(new, "etc/broken-by-user.conf")))   # zbytek je cisty
        with open(os.path.join(new, "etc/passwd")) as f:
            self.assertIn("anna:x:1000", f.read())
        self.assertTrue(os.path.islink(os.path.join(new, "etc/systemd/system/multi-user.target.wants/NetworkManager.service")))
        self.assertFalse(os.path.lexists(os.path.join(new, "etc/systemd/system/multi-user.target.wants/gone.service")))
        self.assertTrue(os.path.islink(os.path.join(new, "etc/systemd/system/default.target")))
        # alias display-manager (jinak po preinstalaci zadne prihlaseni) a klicenka lux (jinak zadne aktualizace)
        self.assertEqual(os.readlink(os.path.join(new, "etc/systemd/system/display-manager.service")),
                         "/usr/lib/systemd/system/lightdm.service")
        with open(os.path.join(new, "etc/lux/keyring/pubring.gpg")) as f:
            self.assertEqual(f.read(), "keys")
        with open(os.path.join(new, "etc/subuid")) as f:
            self.assertEqual(f.read(), "anna:100000:65536\n")
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
        self.assertEqual(self.cmds[i + 2], ["fsck.fat", "-n", "/dev/nvme0n1p1"])   # kontrola po oprave
        self.assertEqual(self.cmds[i + 3], ["mount", "/boot"])
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

    BACKUP = ("fsck.fat 4.2 (2021-01-31)\n"
              "There are differences between boot sector and its backup.\n"
              "This is mostly harmless. Differences: (offset:original/backup)\n"
              "  65:01/00, 71:45/58, 72:46/58, 73:49/58, 74:20/58, 75:20/58, 76:20/58\n"
              "  , 77:20/58, 78:20/58, 79:20/58, 80:20/58, 81:20/58\n"
              "  Not automatically fixing this.\n"
              "Leaving filesystem unchanged.\n"
              "/dev/vda1: 40 files, 33845/261627 clusters\n")

    def test_fat_backup_only(self):
        self.assertTrue(rec.fat_backup_only(self.BACKUP))
        self.assertTrue(rec.fat_backup_only(self.DIRTY))
        self.assertFalse(rec.fat_only_dirty(self.BACKUP))           # vic nez priznak dirty = problem
        self.assertFalse(rec.fat_backup_only(self.BACKUP.replace(
            "Leaving", "/EFI/x\n  File size is 0 bytes, cluster chain length is > 0.\nLeaving")))
        self.assertFalse(rec.fat_backup_only("fsck.fat 4.2\n/dev/x: 1 files, 1/2 clusters\n"))

    def fat32_image(self, path, backup_label=b"XXXXXXXXXXX"):
        import struct
        boot = bytearray(512)
        struct.pack_into("<H", boot, 11, 512)
        struct.pack_into("<H", boot, 22, 0)                         # FAT32: velikost FAT16 = 0
        struct.pack_into("<H", boot, 50, 6)                         # zalozni boot sektor = 6
        boot[71:82] = b"EFI        "
        boot[510:512] = b"\x55\xaa"
        bk = bytearray(boot)
        bk[71:82] = backup_label
        with open(path, "wb") as f:
            f.write(bytes(boot) + b"\0" * 512 * 5 + bytes(bk) + b"\0" * 512 * 10)
        return bytes(boot)

    def test_repair_copies_boot_sector_to_backup_and_verifies(self):
        """Skutecny pripad z VM: fsck.fat -a rozdil boot sektoru neopravi a vrati uspech - oprava ho
        prepise hlavnim sektorem a uspech hlasi az podle kontroly po oprave."""
        dev = os.path.join(self.root, "esp.img")
        boot = self.fat32_image(dev)
        state = {"fixed": False}

        def sh(cmd, timeout=600):
            self.cmds.append(cmd)
            if cmd[:2] == ["fsck.fat", "-n"]:
                with open(dev, "rb") as f:
                    f.seek(6 * 512)
                    same = f.read(512) == boot
                return (0, "fsck.fat 4.2\n/dev/x: 1 files\n") if same else (1, self.BACKUP)
            if cmd[:2] == ["fsck.fat", "-a"]:
                return 1, self.BACKUP                               # "opraveno" - ale nic neudelal
            return 0, ""
        with mock.patch.object(snap, "sh", sh):
            ok, out = rec.repair_boot_partition("vfat", dev)
        self.assertTrue(ok, out)
        with open(dev, "rb") as f:
            data = f.read()
        self.assertEqual(data[6 * 512:7 * 512], boot)
        self.assertEqual(data[:512], boot)                          # hlavni sektor beze zmeny

    def test_repair_reports_unfixed_problem(self):
        def sh(cmd, timeout=600):
            self.cmds.append(cmd)
            if cmd[0] == "fsck.fat":
                return (1, "fsck.fat 4.2\n/EFI/x\n  File size is 0 bytes, cluster chain length is > 0.\n")
            return 0, ""
        with mock.patch.object(snap, "sh", sh):
            res = rec.disk_check(self.top, repair=True, out=lambda *a: None)
        self.assertEqual([t for t, ok, _o in res if not ok], ["fsck /boot"])

    def test_fat_copy_backup_refuses_non_fat32(self):
        dev = os.path.join(self.root, "fat16.img")
        self.fat32_image(dev)
        with open(dev, "r+b") as f:
            f.seek(22)
            f.write(b"\x10\x00")                                     # FAT16: bez zalozniho sektoru
        self.assertFalse(rec.fat_copy_backup(dev))

    def test_disk_check_reports_errors(self):
        def sh(cmd, timeout=600):
            self.cmds.append(cmd)
            return (4, "FAT corrupted") if cmd[0] == "fsck.fat" else (0, "")
        with mock.patch.object(snap, "sh", sh):
            res = rec.disk_check(self.top, out=lambda *a: None)
        self.assertEqual([t for t, ok, _o in res if not ok], ["fsck /boot"])


class CopyPath(unittest.TestCase):
    def test_skips_sockets(self):
        import socket
        import tempfile
        d = tempfile.mkdtemp(prefix="luxos-copy-")
        try:
            os.makedirs(os.path.join(d, "old/etc/luxos"))
            with open(os.path.join(d, "old/etc/luxos/care.conf"), "w") as f:
                f.write("MODE=carefree\n")
            s = socket.socket(socket.AF_UNIX)
            s.bind(os.path.join(d, "old/etc/luxos/S.agent"))
            self.assertTrue(rec.copy_path(os.path.join(d, "old"), os.path.join(d, "new"), "etc/luxos"))
            s.close()
            self.assertTrue(os.path.isfile(os.path.join(d, "new/etc/luxos/care.conf")))
            self.assertFalse(os.path.exists(os.path.join(d, "new/etc/luxos/S.agent")))
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
