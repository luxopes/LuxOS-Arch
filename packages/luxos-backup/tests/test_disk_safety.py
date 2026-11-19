"""LuxOS Zalohy - bezpecnost disku zaloh (bez roota, bez skutecnych disku, udisks a ssh se podstrci).

    python -m unittest discover -s packages/luxos-backup/tests

Overuje: nove pridani sitoveho disku SMB nesmaze obraz se zalohami (smazani jen s potvrzenim),
evidence uzivatelu disku mezi procesy (okno x casovac), adresa sftp nemuze podstrcit volbu ssh,
priprava disku odmitne disk s bezicim systemem i pod LUKS a LVM.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.abspath(os.path.join(HERE, "..", "files"))
sys.path.insert(0, FILES)
os.environ.setdefault("LUXOS_I18N_DIR", os.path.abspath(os.path.join(HERE, "..", "..", "luxos-i18n", "files")))
os.environ["LUXOS_BACKUP_NO_NOTIFY"] = "1"

import luxos_backup as core  # noqa: E402


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-backup-safety-")
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
                                                "XDG_STATE_HOME": os.path.join(self.tmp, "state"),
                                                "XDG_RUNTIME_DIR": os.path.join(self.tmp, "run"),
                                                "LUXOS_BACKUP_HOST": "pc"})
        os.makedirs(os.path.join(self.tmp, "run"))
        self.env.start()
        self.secrets = {}
        self.sec = [mock.patch.object(core, "secret_set", lambda k, _l, v: self.secrets.__setitem__(k, v)),
                    mock.patch.object(core, "secret_clear", lambda k: self.secrets.pop(k, None)),
                    mock.patch.object(core, "secret_get", lambda k: self.secrets.get(k))]
        for p in self.sec:
            p.start()

    def tearDown(self):
        for p in self.sec:
            p.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---- SMB: znovu pridany disk ------------------------------------------------------------
class SmbReAdd(Tmp):
    def setUp(self):
        super().setUp()
        self.share = os.path.join(self.tmp, "share")
        os.makedirs(os.path.join(self.share, core.TOP))
        self.image = os.path.join(self.share, core.TOP, core.machine_name() + ".img")
        self.loop = {"name": "loop7", "path": "/dev/loop7", "type": "loop"}
        self.cmds = []
        self.formatted = []
        self.unlock_ok = True
        patches = [mock.patch.object(core, "smb_fuse_path", lambda disk, do_mount=True: self.share),
                   mock.patch.object(core, "run", self.fake_run),
                   mock.patch.object(core, "format_device", self.fake_format),
                   mock.patch.object(core, "udisks_unlock", self.fake_unlock)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def fake_run(self, cmd, input=None, env=None, timeout=None, check=False):
        self.cmds.append(cmd)
        if cmd[0] == "losetup":
            return 0, "", ""
        if cmd[:2] == ["udisksctl", "loop-setup"]:
            return 0, f"Mapped file {cmd[3]} as /dev/loop7.\n", ""
        if cmd[0] == "lsblk":
            return 0, json.dumps({"blockdevices": [self.loop]}), ""
        return 0, "", ""

    def fake_format(self, dev, passphrase=None, label=""):
        self.formatted.append((dev, passphrase))
        return {"uuid": "new-fs", "luks_uuid": "new-luks" if passphrase else None, "encrypted": bool(passphrase)}

    def fake_unlock(self, dev, pw):
        if not self.unlock_ok or pw != "secret":
            raise core.NotConnected("Error unlocking /dev/loop7: Failed to activate device: Operation not permitted")
        self.loop["children"] = [{"name": "dm-3", "path": "/dev/dm-3", "type": "crypt", "fstype": "btrfs",
                                  "uuid": "old-inner"}]
        return "/dev/dm-3"

    def existing(self, fstype, uuid="old-fs"):
        with open(self.image, "wb") as f:
            f.write(b"old backups")
        self.loop.update(fstype=fstype, uuid=uuid)

    def image_kept(self):
        with open(self.image, "rb") as f:
            return f.read() == b"old backups"

    def test_existing_backups_reused_not_formatted(self):
        self.existing("btrfs")
        disk = core.add_smb_disk(core.load_config(), "smb://anna@nas/Backups", "netpw")
        self.assertEqual(self.formatted, [])
        self.assertTrue(self.image_kept())
        self.assertEqual((disk["uuid"], disk["encrypted"]), ("old-fs", False))
        self.assertEqual(core.load_config()["disks"][0]["uuid"], "old-fs")
        self.assertIn(["udisksctl", "loop-delete", "-b", "/dev/loop7", "--no-user-interaction"], self.cmds)

    def test_encrypted_backups_reused_with_password(self):
        self.existing("crypto_LUKS", "old-luks")
        disk = core.add_smb_disk(core.load_config(), "smb://anna@nas/Backups", encrypt_pw="secret")
        self.assertEqual(self.formatted, [])
        self.assertEqual((disk["uuid"], disk["luks_uuid"], disk["encrypted"]), ("old-inner", "old-luks", True))
        self.assertEqual(self.secrets[core.luks_secret(disk)], "secret")
        self.assertIn(["udisksctl", "lock", "-b", "/dev/loop7", "--no-user-interaction"], self.cmds)

    def test_encrypted_backups_wrong_password_not_erased(self):
        self.existing("crypto_LUKS", "old-luks")
        with self.assertRaises(core.BackupError) as cm:
            core.add_smb_disk(core.load_config(), "smb://anna@nas/Backups", "netpw", encrypt_pw="bad")
        self.assertNotIsInstance(cm.exception, core.ExistingBackups)
        self.assertEqual(self.formatted, [])
        self.assertTrue(self.image_kept())
        self.assertEqual(self.secrets, {})                      # heslo k serveru neprezilo neuspech
        self.assertEqual(core.load_config()["disks"], [])

    def test_mismatch_needs_confirmation(self):
        for fstype, pw in (("crypto_LUKS", None), ("btrfs", "secret"), ("ext4", None)):
            with self.subTest(fstype=fstype, pw=pw):
                self.existing(fstype)
                self.loop.pop("children", None)
                with self.assertRaises(core.ExistingBackups):
                    core.add_smb_disk(core.load_config(), "smb://anna@nas/Backups", encrypt_pw=pw)
                self.assertEqual(self.formatted, [])
                self.assertTrue(self.image_kept())

    def test_erase_after_confirmation(self):
        self.existing("btrfs")
        disk = core.add_smb_disk(core.load_config(), "smb://anna@nas/Backups", encrypt_pw="secret", erase=True)
        self.assertEqual(self.formatted, [("/dev/loop7", "secret")])
        self.assertEqual(disk["uuid"], "new-fs")

    def test_empty_image_is_prepared(self):
        # obraz po prerusenem pridani (zadny souborovy system) - neni co ztratit
        with open(self.image, "wb") as f:
            f.truncate(1 << 20)
        core.add_smb_disk(core.load_config(), "smb://anna@nas/Backups")
        self.assertEqual(self.formatted, [("/dev/loop7", None)])

    def test_new_image_is_prepared(self):
        with mock.patch.object(core.os, "statvfs", return_value=mock.Mock(f_bavail=(10 << 30) >> 12, f_frsize=4096)):
            core.add_smb_disk(core.load_config(), "smb://anna@nas/Backups")
        self.assertEqual(self.formatted, [("/dev/loop7", None)])
        st = os.stat(self.image)
        self.assertEqual(st.st_size, int((10 << 30) * 0.8))
        self.assertLess(st.st_blocks * 512, 1 << 20)            # ridky soubor

    def test_same_share_twice_refused_before_anything(self):
        self.existing("btrfs")
        cfg = core.load_config()
        core.add_smb_disk(cfg, "smb://anna@nas/Backups")
        self.cmds.clear()
        with self.assertRaises(core.BackupError):
            core.add_smb_disk(core.load_config(), "smb://anna@nas/Backups", erase=True)
        self.assertEqual(self.cmds, [])
        self.assertEqual(self.formatted, [])


# ---- evidence uzivatelu disku -------------------------------------------------------------
class SharedUse(Tmp):
    DISK = {"id": "d1", "kind": "local", "uuid": "fs-1", "machine": "pc"}
    UNDO = ["udisksctl", "unmount", "-b", "/dev/sdb1", "--no-user-interaction"]

    def setUp(self):
        super().setUp()
        self.mounted = False
        self.ran = []
        patches = [mock.patch.object(core.Session, "mount_uuid",
                                     lambda sess, uuid, luks_uuid=None: self.fake_mount(sess, uuid, luks_uuid)),
                   mock.patch.object(core, "run", lambda cmd, **_k: self.ran.append(cmd) or (0, "", ""))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def fake_mount(self, sess, uuid, luks_uuid=None):
        if not self.mounted:
            self.mounted = True
            sess.undo.insert(0, list(self.UNDO))
        return "/run/media/anna/B"

    def test_last_user_unmounts(self):
        a = core.Session(self.DISK).__enter__()           # casovac pripojil
        b = core.Session(self.DISK).__enter__()           # okno: disk uz pripojeny
        a.__exit__(None, None, None)
        self.assertEqual(self.ran, [])                   # okno disk jeste pouziva
        b.__exit__(None, None, None)
        self.assertEqual(self.ran, [self.UNDO])

    def test_other_process_keeps_disk_mounted(self):
        child = subprocess.Popen(["sleep", "30"])
        try:
            with core._DiskUse("d1") as use:
                use.holders.append(f"{child.pid}:x")
                use.save()
            with core.Session(self.DISK):
                pass
            self.assertEqual(self.ran, [])
        finally:
            child.kill()
            child.wait()
        with core._DiskUse("d1") as use:                 # proces skoncil -> nepocita se, nic nezdedi
            self.assertEqual(use.holders, [])
            self.assertEqual(use.undo, [])

    def test_failed_enter_cleans_up(self):
        def broken(sess, uuid, luks_uuid=None):
            sess.undo.append(["udisksctl", "lock", "-b", "/dev/sdb1", "--no-user-interaction"])
            raise core.NotConnected("mount failed")
        with mock.patch.object(core.Session, "mount_uuid", broken):
            with self.assertRaises(core.NotConnected):
                with core.Session(self.DISK):
                    pass
        self.assertEqual(self.ran, [["udisksctl", "lock", "-b", "/dev/sdb1", "--no-user-interaction"]])
        with core._DiskUse("d1") as use:
            self.assertEqual(use.holders, [])


# ---- sftp: zadna volba ssh z adresy ------------------------------------------------------
class SftpOptions(unittest.TestCase):
    def test_option_like_host_or_user_refused(self):
        for url in ("sftp://-oProxyCommand=touch%20x/backup", "sftp://anna@-oProxyCommand=x/b",
                    "sftp://-oX@nas/b", "ssh://nas:0/b", "sftp://na s/b"):
            with self.subTest(url=url), self.assertRaises(core.BackupError):
                core.parse_sftp(url)
        self.assertEqual(core.parse_sftp("sftp://my.user-1@nas_2.local:2222/x")["host"], "nas_2.local")

    def test_saved_config_with_bad_host_refused(self):
        with self.assertRaises(core.BackupError):
            core.ssh_base({"host": "-oProxyCommand=x", "port": 22})

    def test_destination_after_double_dash(self):
        ssh = core.ssh_base({"host": "nas", "user": "anna", "port": 22})
        self.assertEqual(ssh[-1], "anna@nas")
        calls = []
        sess = mock.Mock(remote=(ssh, "/b"), disk={"id": "x", "kind": "sftp"})
        with mock.patch.object(core, "run", lambda cmd, **_k: calls.append(cmd) or (0, "", "")):
            core.ssh_run(sess, "command -v rsync")
        self.assertEqual(calls[0][-3:], ["--", "anna@nas", "command -v rsync"])   # jedno "--"

    @unittest.skipUnless(shutil.which("ssh"), "ssh not installed")
    def test_real_ssh_parses_destination(self):
        # ssh -G jen vypise vyslednou konfiguraci, nikam se nepripoji
        ssh = core.ssh_base({"host": "nas.example", "user": "anna", "port": 2222})
        r = subprocess.run([ssh[0], "-G", "-F", "/dev/null", *ssh[1:], "true"], capture_output=True, text=True,
                           timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hostname nas.example", r.stdout)
        self.assertIn("port 2222", r.stdout)
        self.assertIn("user anna", r.stdout)

    @unittest.skipUnless(shutil.which("ssh"), "ssh not installed")
    def test_rsync_shell_accepts_user_option(self):
        # rsync spusti -e prikaz s "-l user host prikaz"; za "--" by ssh vzal "-l" jako hostitele
        ssh = core.ssh_base({"host": "nas.example", "user": "anna", "port": 2222})
        cmd = core.rsync_cmd("/home/anna", "/b/X.partial/home", remote=ssh)
        shell = shlex.split(cmd[cmd.index("-e") + 1])
        self.assertNotIn("--", shell)
        r = subprocess.run([shell[0], "-G", "-F", "/dev/null", *shell[1:], "-l", "anna", "nas.example",
                            "rsync", "--server"], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hostname nas.example", r.stdout)
        self.assertIn("user anna", r.stdout)


# ---- priprava disku: disk s bezicim systemem ----------------------------------------------
class SystemDisk(Tmp):
    LSBLK = {"blockdevices": [
        # LuxOS nainstalovany na USB SSD: oddil LUKS, system na /dev/mapper/root
        {"name": "sdb", "path": "/dev/sdb", "type": "disk", "rm": False, "hotplug": True, "tran": "usb",
         "children": [{"name": "sdb1", "path": "/dev/sdb1", "type": "part", "fstype": "vfat", "mountpoints": ["/boot"]},
                      {"name": "sdb2", "path": "/dev/sdb2", "type": "part", "fstype": "crypto_LUKS", "uuid": "l1",
                       "mountpoints": [None],
                       "children": [{"name": "root", "path": "/dev/mapper/root", "type": "crypt",
                                     "fstype": "btrfs", "mountpoints": ["/", "/home"]}]}]},
        # USB disk s LVM, na kterem je /var
        {"name": "sdc", "path": "/dev/sdc", "type": "disk", "rm": True, "hotplug": True, "tran": "usb",
         "children": [{"name": "sdc1", "path": "/dev/sdc1", "type": "part", "fstype": "LVM2_member",
                       "mountpoints": [None],
                       "children": [{"name": "vg-var", "path": "/dev/mapper/vg-var", "type": "lvm",
                                     "fstype": "ext4", "mountpoints": ["/var"]}]}]},
        # opravdu volny USB disk
        {"name": "sdd", "path": "/dev/sdd", "type": "disk", "rm": True, "hotplug": True, "tran": "usb",
         "children": [{"name": "sdd1", "path": "/dev/sdd1", "type": "part", "fstype": "exfat", "mountpoints": [None]}]},
    ]}

    def test_system_disk_under_luks_and_lvm_refused(self):
        formatted = []
        with mock.patch.object(core, "run", return_value=(0, json.dumps(self.LSBLK), "")), \
                mock.patch.object(core, "format_device", lambda dev, *a, **k: formatted.append(dev) or {"uuid": "n"}):
            self.assertEqual(core.system_devices() & {"/dev/sdb", "/dev/sdb2", "/dev/sdc", "/dev/sdc1"},
                             {"/dev/sdb", "/dev/sdb2", "/dev/sdc", "/dev/sdc1"})
            for dev in ("/dev/sdb", "/dev/sdb2", "/dev/sdb1", "/dev/sdc", "/dev/sdc1"):
                with self.subTest(dev=dev), self.assertRaises(core.BackupError):
                    core.prepare_disk(core.load_config(), dev)
            self.assertEqual(formatted, [])
            core.prepare_disk(core.load_config(), "/dev/sdd")
            self.assertEqual(formatted, ["/dev/sdd"])


if __name__ == "__main__":
    unittest.main()
