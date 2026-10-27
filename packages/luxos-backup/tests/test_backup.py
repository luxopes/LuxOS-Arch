"""LuxOS Zalohy - testy jadra a prikazu v docasnych slozkach (bez roota, bez skutecnych disku).

    python -m unittest discover -s packages/luxos-backup/tests
    (nebo python -m pytest packages/luxos-backup/tests --ignore=.../test_gui.py)

Rezim rsync se testuje, jen kdyz je rsync nainstalovany; rezim python vzdy.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.abspath(os.path.join(HERE, "..", "files"))
sys.path.insert(0, FILES)
os.environ.setdefault("LUXOS_I18N_DIR", os.path.abspath(os.path.join(HERE, "..", "..", "luxos-i18n", "files")))
os.environ["LUXOS_BACKUP_NO_NOTIFY"] = "1"

import luxos_backup as core  # noqa: E402

HAVE_RSYNC = shutil.which("rsync") is not None


def write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


class Env(unittest.TestCase):
    """Docasny domov, nastaveni, stav a 'disk' (obycejna slozka)."""
    engine = "python"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-backup-test-")
        self.home = os.path.join(self.tmp, "home")
        self.disk = os.path.join(self.tmp, "disk")
        os.makedirs(self.disk)
        env = {"LUXOS_BACKUP_HOME": self.home, "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
               "XDG_STATE_HOME": os.path.join(self.tmp, "state"), "LUXOS_BACKUP_HOST": "pc",
               "LUXOS_BACKUP_ENGINE": self.engine, "LUXOS_SYSROOT": os.path.join(self.tmp, "root")}
        self.envpatch = mock.patch.dict(os.environ, env)
        self.envpatch.start()
        # findmnt: docasna slozka neni vymenny disk -> pevna cesta
        self.fsp = mock.patch.object(core, "fs_uuid", return_value=(None, None))
        self.fsp.start()
        self.fst = mock.patch.object(core, "fs_type", return_value="ext4")
        self.fst.start()
        # klicenka uzivatele se v testech nikdy nepouzije
        self.sec = [mock.patch.object(core, n) for n in ("secret_get", "secret_set", "secret_clear")]
        for m in self.sec:
            m.start()
        write(os.path.join(self.home, "Documents", "report.txt"), "v1")
        write(os.path.join(self.home, "Documents", "big.bin"), "B" * 10000)
        write(os.path.join(self.home, ".cache", "junk"), "cache")
        write(os.path.join(self.home, ".local", "share", "Trash", "files", "old"), "trash")
        write(os.path.join(self.home, "Downloads", "setup.iso"), "iso")
        write(os.path.join(self.home, "VMs", "win.qcow2"), "vm")
        write(os.path.join(self.home, ".config", "app.conf"), "conf")
        os.symlink("Documents/report.txt", os.path.join(self.home, "link"))
        self.cfg = core.load_config()
        self.d = core.add_local_disk(self.cfg, self.disk, "Test")
        self.root = os.path.join(self.disk, core.TOP, core.machine_name())

    def tearDown(self):
        for m in self.sec:
            m.stop()
        self.fst.stop()
        self.fsp.stop()
        self.envpatch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def backup(self, t=None):
        t = time.time() if t is None else t
        with mock.patch.object(core, "snap_name", lambda _t=None: _name(t)):
            return core.run_backup(manual=True, log=lambda *_a: None)


def _name(t):
    import datetime
    return datetime.datetime.fromtimestamp(t if t is not None else time.time(),
                                           datetime.timezone.utc).strftime(core.SNAP_FMT)


class LinkDestMixin:
    def test_incremental_hardlinks(self):
        now = time.time()
        self.assertEqual(self.backup(now - 7200), 0)
        write(os.path.join(self.home, "Documents", "report.txt"), "v2 changed")
        os.unlink(os.path.join(self.home, ".config", "app.conf"))
        self.assertEqual(self.backup(now - 3600), 0)
        snaps = sorted(n for n in os.listdir(self.root) if core.SNAP_RE.match(n))
        self.assertEqual(len(snaps), 2)
        a, b = (os.path.join(self.root, s, "home") for s in snaps)
        # nezmeneny soubor = pevny odkaz (stejny inode), zmeneny = nova kopie
        self.assertEqual(os.stat(f"{a}/Documents/big.bin").st_ino, os.stat(f"{b}/Documents/big.bin").st_ino)
        self.assertNotEqual(os.stat(f"{a}/Documents/report.txt").st_ino, os.stat(f"{b}/Documents/report.txt").st_ino)
        self.assertEqual(read(f"{a}/Documents/report.txt"), "v1")
        self.assertEqual(read(f"{b}/Documents/report.txt"), "v2 changed")
        self.assertTrue(os.path.exists(f"{a}/.config/app.conf"))
        self.assertFalse(os.path.exists(f"{b}/.config/app.conf"))
        self.assertTrue(os.path.islink(f"{b}/link"))
        self.assertFalse([n for n in os.listdir(self.root) if n.endswith(".partial")])
        with open(os.path.join(self.root, snaps[1], "info.json")) as f:
            info = json.load(f)
        self.assertEqual(info["machine"], core.machine_name())
        st = core.load_status()
        self.assertEqual(st["state"], "idle")
        self.assertEqual(st["last_name"], snaps[1])

    def test_default_excludes(self):
        self.backup()
        snap = os.path.join(self.root, sorted(os.listdir(self.root))[0], "home")
        self.assertFalse(os.path.exists(f"{snap}/.cache"))
        self.assertFalse(os.path.exists(f"{snap}/.local/share/Trash"))
        self.assertFalse(os.path.exists(f"{snap}/VMs/win.qcow2"))          # VM vychozi vynechane
        self.assertTrue(os.path.exists(f"{snap}/Downloads/setup.iso"))     # Stazene vychozi zalohovane
        self.assertTrue(os.path.exists(f"{snap}/.config/app.conf"))

    def test_user_excludes_and_options(self):
        cfg = core.load_config()
        cfg["downloads"] = False
        cfg["vms"] = True
        cfg["excludes"] = [os.path.join(self.home, ".config"), "*.bin"]
        core.save_config(cfg)
        self.backup()
        snap = os.path.join(self.root, [n for n in os.listdir(self.root) if core.SNAP_RE.match(n)][0], "home")
        self.assertFalse(os.path.exists(f"{snap}/Downloads"))
        self.assertTrue(os.path.exists(f"{snap}/VMs/win.qcow2"))
        self.assertFalse(os.path.exists(f"{snap}/.config"))
        self.assertFalse(os.path.exists(f"{snap}/Documents/big.bin"))
        self.assertTrue(os.path.exists(f"{snap}/Documents/report.txt"))

    def test_interrupted_backup_never_touches_previous(self):
        now = time.time()
        self.backup(now - 7200)
        first = sorted(n for n in os.listdir(self.root) if core.SNAP_RE.match(n))[0]
        # prerusena zaloha: .partial s pevnym odkazem na predchozi zalohu
        part = os.path.join(self.root, _name(now - 5000) + ".partial", "home", "Documents")
        os.makedirs(part)
        os.link(os.path.join(self.root, first, "home", "Documents", "report.txt"), os.path.join(part, "report.txt"))
        write(os.path.join(self.home, "Documents", "report.txt"), "v3")
        # stejna velikost jako "v1" a zapis ve stejne sekunde: rsync (velikost + cas) by zmenu nevidel
        os.utime(os.path.join(self.home, "Documents", "report.txt"), (now + 10, now + 10))
        self.backup(now - 3600)
        self.assertEqual(read(os.path.join(self.root, first, "home", "Documents", "report.txt")), "v1")
        snaps = sorted(n for n in os.listdir(self.root) if core.SNAP_RE.match(n))
        self.assertEqual(read(os.path.join(self.root, snaps[-1], "home", "Documents", "report.txt")), "v3")
        self.assertFalse([n for n in os.listdir(self.root) if n.endswith(".partial")])


class PythonEngine(Env, LinkDestMixin):
    engine = "python"


@unittest.skipUnless(HAVE_RSYNC, "rsync not installed")
class RsyncEngine(Env, LinkDestMixin):
    engine = "rsync"


class Restore(Env):
    def setUp(self):
        super().setUp()
        self.backup(time.time() - 600)
        self.name = sorted(n for n in os.listdir(self.root) if core.SNAP_RE.match(n))[0]

    def sess(self):
        return core.open_source(source=self.disk)

    def test_restore_never_overwrites(self):
        write(os.path.join(self.home, "Documents", "report.txt"), "newer work")
        with self.sess() as s:
            done = core.restore(s, self.name, ["~/Documents/report.txt"], log=lambda *_a: None)
        self.assertEqual(read(os.path.join(self.home, "Documents", "report.txt")), "newer work")
        dst = done[0][1]
        self.assertNotEqual(dst, os.path.join(self.home, "Documents", "report.txt"))
        self.assertTrue(os.path.basename(dst).startswith("report ("))
        self.assertTrue(dst.endswith(").txt"))
        self.assertEqual(read(dst), "v1")
        # podruhe dalsi volne jmeno
        with self.sess() as s:
            done2 = core.restore(s, self.name, ["Documents/report.txt"], log=lambda *_a: None)
        self.assertNotEqual(done2[0][1], dst)

    def test_restore_deleted_folder_to_original_and_elsewhere(self):
        shutil.rmtree(os.path.join(self.home, "Documents"))
        with self.sess() as s:
            core.restore(s, self.name, [os.path.join(self.home, "Documents")], log=lambda *_a: None)
        self.assertEqual(read(os.path.join(self.home, "Documents", "report.txt")), "v1")
        other = os.path.join(self.tmp, "elsewhere")
        os.makedirs(other)
        with self.sess() as s:
            core.restore(s, self.name, ["Documents"], to=other, log=lambda *_a: None)
        self.assertEqual(read(os.path.join(other, "Documents", "big.bin")), "B" * 10000)

    def test_restore_rejects_escape(self):
        with self.sess() as s, self.assertRaises(core.BackupError):
            core.restore(s, self.name, ["../../etc/passwd"], log=lambda *_a: None)
        with self.sess() as s, self.assertRaises(core.BackupError):
            core.restore(s, self.name, ["~/missing.txt"], log=lambda *_a: None)

    def test_restore_all_new_install(self):
        new_home = os.path.join(self.tmp, "newhome")
        write(os.path.join(new_home, ".config", "app.conf"), "skel default")
        with self.sess() as s:
            kept = core.restore_all(s, self.name, new_home, replace=False, log=lambda *_a: None)
        self.assertEqual(read(os.path.join(new_home, "Documents", "report.txt")), "v1")
        self.assertEqual(read(os.path.join(new_home, ".config", "app.conf")), "skel default")
        if not HAVE_RSYNC:
            self.assertEqual(kept, 1)
        # --replace: zaloha vyhraje, puvodni soubor se presune stranou
        with self.sess() as s:
            core.restore_all(s, self.name, new_home, replace=True, log=lambda *_a: None)
        self.assertEqual(read(os.path.join(new_home, ".config", "app.conf")), "conf")
        aside = [n for n in os.listdir(new_home) if n.startswith(".luxos-backup-replaced-")]
        self.assertEqual(len(aside), 1)
        self.assertEqual(read(os.path.join(new_home, aside[0], ".config", "app.conf")), "skel default")

    def test_list_dir_and_when(self):
        with self.sess() as s:
            items = core.list_dir(s, self.name, "Documents")
            self.assertEqual([i[0] for i in items], ["big.bin", "report.txt"])
            top = [i[0] for i in core.list_dir(s, self.name)]
            self.assertIn("Documents", top)
            self.assertTrue(core.list_dir(s, self.name)[0][1])        # slozky prvni
            self.assertEqual(core.parse_when("latest", [self.name]), self.name)
            with self.assertRaises(core.BackupError):
                core.parse_when("2001-01-01", [self.name])

    def test_find_machine_root(self):
        self.assertEqual(core.find_machine_root(self.disk), self.root)
        self.assertEqual(core.find_machine_root(os.path.join(self.disk, core.TOP)), self.root)
        self.assertEqual(core.find_machine_root(self.root), self.root)
        os.makedirs(os.path.join(self.disk, core.TOP, "other-anna", "2026-01-01-000000"))
        with mock.patch.dict(os.environ, {"LUXOS_BACKUP_HOST": "unknown"}):
            with self.assertRaises(core.BackupError):
                core.find_machine_root(self.disk)
            self.assertTrue(core.find_machine_root(self.disk, "other-anna").endswith("other-anna"))


class Thinning(unittest.TestCase):
    def test_thin_schedule(self):
        now = time.mktime((2026, 10, 26, 12, 0, 0, 0, 0, -1))
        names = []
        for h in range(0, 24 * 90, 1):          # kazdou hodinu 90 dni
            names.append(_name(now - h * 3600))
        delete = set(core.thin(names, now))
        keep = sorted(set(names) - delete)
        recent = [n for n in keep if now - core.snap_time(n) < 86400]
        self.assertEqual(len(recent), 24)                      # posledni den vse
        month = [n for n in keep if 86400 <= now - core.snap_time(n) < 31 * 86400]
        days = {time.strftime("%Y-%m-%d", time.localtime(core.snap_time(n))) for n in month}
        self.assertEqual(len(month), len(days))                # jedna za den
        self.assertGreaterEqual(len(days), 29)
        old = [n for n in keep if now - core.snap_time(n) >= 31 * 86400]
        weeks = {time.strftime("%G-%V", time.localtime(core.snap_time(n))) for n in old}
        self.assertEqual(len(old), len(weeks))                 # jedna za tyden
        self.assertIn(max(names), keep)

    def test_newest_always_kept(self):
        now = time.time()
        old = [_name(now - 400 * 86400)]
        self.assertEqual(core.thin(old, now), [])


class DiskFull(Env):
    def test_make_space_deletes_oldest_but_never_last(self):
        now = time.time()
        for k in (5, 4, 3):
            self.backup(now - k * 86400 * 40)          # tydenni zalohy, protrideni je nesmaze
        names = sorted(n for n in os.listdir(self.root) if core.SNAP_RE.match(n))
        self.assertEqual(len(names), 3)
        with core.open_source(source=self.disk) as s:
            with mock.patch.object(core, "free_space", side_effect=[(0, 100)] * 10):
                deleted = core.make_space(s, log=lambda *_a: None)
        self.assertEqual(deleted, names[:2])
        self.assertEqual(sorted(n for n in os.listdir(self.root) if core.SNAP_RE.match(n)), names[2:])

    def test_full_disk_retry(self):
        now = time.time()
        self.backup(now - 50 * 86400)
        self.backup(now - 40 * 86400)
        real = core._copy
        calls = []

        def flaky(*a, **kw):
            calls.append(1)
            if len(calls) == 1:
                raise core.DiskFull("No space left on device")
            return real(*a, **kw)
        with mock.patch.object(core, "_copy", flaky):
            self.assertEqual(self.backup(now), 0)
        names = sorted(n for n in os.listdir(self.root) if core.SNAP_RE.match(n))
        self.assertEqual(len(names), 2)               # nejstarsi smazana, nova pridana
        self.assertEqual(names[-1], _name(now))


class Conditions(unittest.TestCase):
    def test_conditions(self):
        ok = core.conditions_ok
        self.assertEqual(ok({"ac": None, "batteries": []}), (True, ""))                 # stolni pocitac
        self.assertEqual(ok({"ac": False, "batteries": [(80, "Discharging")]}), (False, "battery"))
        self.assertEqual(ok({"ac": True, "batteries": [(80, "Charging")]}), (True, ""))
        self.assertEqual(ok({"ac": True, "batteries": [(80, "Charging")], "metered": True}), (False, "metered"))
        self.assertEqual(ok({"ac": False, "batteries": [(80, "Discharging")]}, manual=True), (True, ""))

    def test_power_state_from_sysfs(self):
        root = tempfile.mkdtemp()
        try:
            for name, files in (("AC", {"type": "Mains", "online": "0"}),
                                ("BAT0", {"type": "Battery", "capacity": "55", "status": "Discharging"})):
                for k, v in files.items():
                    write(os.path.join(root, "sys/class/power_supply", name, k), v)
            with mock.patch.dict(os.environ, {"LUXOS_SYSROOT": root}):
                self.assertEqual(core.power_state(), (False, [(55, "Discharging")]))
                os.makedirs(os.path.join(root, "run/luxos"))
                write(os.path.join(root, "run/luxos/powersaver"), "")
                with mock.patch.object(core, "metered", return_value=False):
                    self.assertTrue(core.current_env()["powersaver"])
        finally:
            shutil.rmtree(root)

    def test_paused_on_battery(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp, "XDG_STATE_HOME": tmp}):
                core.save_config(dict(core.load_config(), disks=[{"id": "x", "kind": "local", "path": tmp}]))
                with mock.patch.object(core, "current_env", return_value={"ac": False,
                                                                         "batteries": [(90, "Discharging")]}), \
                        mock.patch.object(core, "backup") as b:
                    self.assertEqual(core.run_backup(log=lambda *_a: None), 0)
                    b.assert_not_called()
                self.assertEqual(core.load_status()["reason"], "battery")


class Excludes(unittest.TestCase):
    def test_matcher(self):
        pats = ["/.cache/", "*.qcow2", "/VirtualBox VMs/", "lost+found/", "/.var/app/*/cache/"]
        m = core.is_excluded
        self.assertTrue(m(".cache", True, pats))
        self.assertFalse(m(".cache", False, pats))              # jen slozka
        self.assertFalse(m("a/.cache", True, pats))             # ukotvene
        self.assertTrue(m("x/y/disk.qcow2", False, pats))
        self.assertTrue(m("VirtualBox VMs", True, pats))
        self.assertTrue(m("deep/lost+found", True, pats))
        self.assertTrue(m(".var/app/org.x.Y/cache", True, pats))
        self.assertFalse(m(".var/app/org.x.Y/data", True, pats))

    def test_downloads_xdg(self):
        with tempfile.TemporaryDirectory() as h:
            write(os.path.join(h, ".config", "user-dirs.dirs"), 'XDG_DOWNLOAD_DIR="$HOME/Stahování"\n')
            with mock.patch.dict(os.environ, {"LUXOS_BACKUP_HOME": h}):
                pats = core.excludes(dict(core.load_config(), downloads=False))
                self.assertIn("/Stahování/", pats)
                self.assertIn("/Downloads/", pats)
                pats = core.excludes(dict(core.load_config(), excludes=["~/Music", h + "/Videos", "/etc/x", "*.iso"]))
                self.assertIn("/Music", pats)
                self.assertIn("/Videos", pats)
                self.assertIn("*.iso", pats)
                self.assertNotIn("/etc/x", pats)


class Btrfs(Env):
    """Rezim btrfs s nahrazenym prikazem btrfs (snimek = kopie, podsvazek = slozka)."""
    engine = "btrfs"

    def test_btrfs_flow(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if cmd[:3] == ["btrfs", "subvolume", "create"]:
                os.makedirs(cmd[3])
            elif cmd[:4] == ["btrfs", "subvolume", "snapshot", "-r"]:
                shutil.copytree(cmd[4], cmd[5], symlinks=True)
            return 0, "", ""

        def fake_rsync(cmd, env=None, on_progress=None):
            calls.append(cmd)
            self.assertIn("--inplace", cmd)
            dst = cmd[-1]
            core.py_copy(cmd[-2], dst, core.excludes(core.load_config()))
            return 0, ""
        with mock.patch.object(core, "run", fake_run), mock.patch.object(core, "run_rsync", fake_rsync):
            self.assertEqual(self.backup(time.time() - 60), 0)
        snaps = [n for n in os.listdir(self.root) if core.SNAP_RE.match(n)]
        self.assertEqual(len(snaps), 1)
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".current")))
        self.assertTrue(os.path.exists(os.path.join(self.root, snaps[0], "home", "Documents", "report.txt")))
        self.assertTrue(any(c[:4] == ["btrfs", "subvolume", "snapshot", "-r"] for c in calls))
        self.assertEqual(core.list_snapshots(core.SourceSession(self.root)), snaps)


class Sftp(unittest.TestCase):
    def test_parse_and_commands(self):
        p = core.parse_sftp("sftp://anna@nas.local:2222/volume1/backup")
        self.assertEqual(p, {"user": "anna", "host": "nas.local", "port": 2222, "path": "/volume1/backup"})
        disk = dict(p, id="abcd", kind="sftp")
        ssh = core.ssh_base(disk)
        self.assertEqual(ssh[:3], ["ssh", "-p", "2222"])
        self.assertEqual(ssh[-1], "anna@nas.local")
        cmd = core.rsync_cmd("/home/anna", "/volume1/backup/LuxOS-Backups/pc-anna/X.partial/home",
                             "/tmp/ex", "../../2026-01-01-000000/home", remote=ssh)
        self.assertEqual(cmd[-1], "anna@nas.local:/volume1/backup/LuxOS-Backups/pc-anna/X.partial/home/")
        self.assertIn("--link-dest", cmd)
        env = core.ssh_env(disk)
        self.assertEqual(env["SSH_ASKPASS_REQUIRE"], "force")
        self.assertEqual(env["LUXOS_BACKUP_DISK"], "abcd")
        with self.assertRaises(core.BackupError):
            core.parse_sftp("http://x")

    def test_askpass_script(self):
        script = os.path.join(FILES, "luxos-backup-askpass")
        r = subprocess.run(["sh", script, "Are you sure (yes/no)?"], env={"LUXOS_BACKUP_DISK": "x", "PATH": "/usr/bin"})
        self.assertEqual(r.returncode, 1)

    def test_smb_parse(self):
        self.assertEqual(core.smb_parse("smb://anna@nas/Backups"),
                         {"user": "anna", "host": "nas", "share": "Backups", "sub": ""})
        with self.assertRaises(core.BackupError):
            core.smb_parse("smb://nas")


class Disks(unittest.TestCase):
    LSBLK = {"blockdevices": [
        {"name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "rm": False, "hotplug": False, "tran": "nvme",
         "children": [{"name": "nvme0n1p2", "path": "/dev/nvme0n1p2", "type": "part", "fstype": "btrfs",
                       "uuid": "root", "mountpoints": ["/"]}]},
        {"name": "sdb", "path": "/dev/sdb", "type": "disk", "rm": True, "hotplug": True, "tran": "usb",
         "vendor": "SanDisk ", "model": "Extreme", "size": 64000000000,
         "children": [{"name": "sdb1", "path": "/dev/sdb1", "type": "part", "fstype": "crypto_LUKS",
                       "uuid": "luks-1", "size": 64000000000, "mountpoints": [None],
                       "children": [{"name": "luks-1", "path": "/dev/mapper/luks-1", "type": "crypt",
                                     "fstype": "btrfs", "uuid": "fs-1", "label": "LuxOS Backups",
                                     "mountpoints": ["/run/media/anna/LuxOS Backups"]}]}]},
    ]}

    def test_external_disks(self):
        with mock.patch.object(core, "run", return_value=(0, json.dumps(self.LSBLK), "")):
            disks = core.external_disks()
            self.assertEqual(len(disks), 1)
            d = disks[0]
            self.assertEqual(d["path"], "/dev/sdb1")
            self.assertTrue(d["encrypted"])
            self.assertEqual(d["mount"], "/run/media/anna/LuxOS Backups")
            self.assertEqual(d["model"], "SanDisk Extreme")
            self.assertEqual(core.luks_parent("fs-1"), "luks-1")
            with self.assertRaises(core.BackupError):
                core.prepare_disk(core.load_config(), "/dev/nvme0n1p2")

    def test_session_uses_mounted_luks(self):
        with mock.patch.object(core, "run", return_value=(0, json.dumps(self.LSBLK), "")):
            with core.Session({"id": "a", "kind": "local", "uuid": "fs-1", "luks_uuid": "luks-1",
                               "machine": "pc-anna"}) as s:
                self.assertEqual(s.root, "/run/media/anna/LuxOS Backups/LuxOS-Backups/pc-anna")
                self.assertEqual(s.undo, [])
            with self.assertRaises(core.NotConnected):
                with core.Session({"id": "a", "kind": "local", "uuid": "nope"}):
                    pass

    def test_duplicate_disk_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}), \
                    mock.patch.object(core, "fs_uuid", return_value=(None, None)), \
                    mock.patch.object(core, "fs_type", return_value="ext4"):
                cfg = core.load_config()
                core.add_local_disk(cfg, tmp)
                with self.assertRaises(core.BackupError):
                    core.add_local_disk(cfg, tmp)
                with mock.patch.object(core, "fs_type", return_value="exfat"), self.assertRaises(core.BackupError):
                    core.add_local_disk(core.load_config(), tmp)


class Cli(Env):
    def cli(self, *args):
        sys.path.insert(0, FILES)
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("luxos_backup_cli", os.path.join(FILES, "luxos-backup"))
        spec = importlib.util.spec_from_loader("luxos_backup_cli", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = mod.main(list(args))
        return rc, buf.getvalue()

    def test_cli_flow(self):
        rc, out = self.cli("now")
        self.assertEqual(rc, 0, out)
        rc, out = self.cli("list", "--json")
        names = [x["name"] for x in json.loads(out)]
        self.assertEqual(len(names), 1)
        rc, out = self.cli("files", "Documents")
        self.assertIn("report.txt", out)
        os.unlink(os.path.join(self.home, "Documents", "report.txt"))
        rc, _o = self.cli("restore", "~/Documents/report.txt")
        self.assertEqual(rc, 0)
        self.assertEqual(read(os.path.join(self.home, "Documents", "report.txt")), "v1")
        rc, _o = self.cli("restore", "--from", "1999-01-01", "Documents")
        self.assertEqual(rc, 1)
        rc, _o = self.cli("restore")
        self.assertEqual(rc, 2)
        target = os.path.join(self.tmp, "fresh")
        rc, _o = self.cli("restore", "--all", "--source", self.disk, "--target", target)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(os.path.join(target, "Documents", "big.bin")))
        rc, out = self.cli("exclude", "add", "~/Music")
        self.assertIn(os.path.join(self.home, "Music"), core.load_config()["excludes"])
        rc, out = self.cli("auto", "off")
        self.assertFalse(core.load_config()["auto"])
        rc, out = self.cli("service")          # vypnute automaticke zalohy: nic
        self.assertEqual(rc, 0)
        rc, out = self.cli("disk", "list")
        self.assertIn("Test", out)
        rc, out = self.cli("disk", "remove", self.d["id"])
        self.assertEqual(core.load_config()["disks"], [])
        self.assertTrue(os.path.isdir(self.root))     # zalohy na disku zustanou



class PlugPrompt(Env):
    """Novy USB disk: nabidka "Pouzit tento disk pro zalohy?" (QA: vyprsela nabidka = trvale odmitnuti)."""

    def plug(self, answer):
        dev = {"path": "/dev/sdz1", "name": "sdz1", "uuid": "AAAA-1111", "fstype": "vfat", "label": "USB"}
        with mock.patch.object(core, "lsblk", return_value=[dev]), \
                mock.patch.object(core, "external_disks", return_value=[{"path": "/dev/sdz1", "drive": "/dev/sdz"}]), \
                mock.patch.object(core, "notify", return_value=answer) as n, \
                mock.patch.object(core.subprocess, "Popen") as popen:
            r = core.plugged(core.load_config(), "/dev/sdz1")
        return r, n, popen

    def test_no_answer_is_not_a_decline(self):
        r, n, _p = self.plug(core.NO_ANSWER)
        self.assertEqual(r, "offered")
        self.assertNotIn("AAAA-1111", core.load_config().get("declined", []))
        self.assertEqual(self.plug(core.NO_ANSWER)[0], "offered")     # nabidne se znovu

    def test_closed_is_declined_and_use_opens_window(self):
        with mock.patch.dict(os.environ, {"INVOCATION_ID": "x"}), \
                mock.patch.object(core.shutil, "which", return_value="/usr/bin/systemd-run"):
            r, _n, popen = self.plug("use")
        self.assertEqual(r, "offered")
        cmd = popen.call_args[0][0]
        # okno ve vlastni jednotce, ne v jednorazove sluzbe (systemd by ho hned ukoncil)
        self.assertEqual(cmd[:2], ["systemd-run", "--user"])
        self.assertEqual(cmd[-3:], ["luxos-backup-gui", "--add", "/dev/sdz1"])
        self.plug(None)                                               # zavrel bez volby
        self.assertIn("AAAA-1111", core.load_config().get("declined", []))
        self.assertEqual(self.plug("use")[0], "declined")

    def test_prompt_stays_until_answered(self):
        with mock.patch.dict(os.environ, {"LUXOS_BACKUP_NO_NOTIFY": "0"}), \
                mock.patch.object(core.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            self.assertIsNone(core.notify("t", "b", action=("use", "Use")))
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[cmd.index("-t") + 1], "0")
        with mock.patch.dict(os.environ, {"LUXOS_BACKUP_NO_NOTIFY": "0"}), \
                mock.patch.object(core.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 600)):
            self.assertEqual(core.notify("t", "b", action=("use", "Use")), core.NO_ANSWER)

if __name__ == "__main__":
    unittest.main()
