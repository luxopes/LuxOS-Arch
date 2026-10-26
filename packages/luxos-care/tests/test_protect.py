"""Testy ochrany systemu (luxos_protect): /usr jen pro cteni kolem transakci, kontrola souboru baliku
podle mtree v databazi, oprava, tydenni planovani, skript pri startu a prikazova radka.

Bez roota a bez pripojovani: koren je docasny adresar (LUXOS_CARE_ROOT), /proc/self/mountinfo
je soubor v nem a prikaz mount nahrazuje funkce, ktera jen meni tento soubor.

    python3 -m unittest packages/luxos-care/tests/test_protect.py -v
"""
import contextlib
import gzip
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
sys.path.insert(0, FILES)
sys.path.insert(0, os.path.join(HERE, "..", "..", "luxos-i18n", "files"))

import luxos_care as care  # noqa: E402
import luxos_protect as protect  # noqa: E402

ROOT_LINE = "25 1 0:30 /@ / rw,noatime shared:1 - btrfs /dev/vda2 rw,subvol=/@\n"
USR_RO = "60 25 0:30 /@/usr /usr ro,noatime shared:1 - btrfs /dev/vda2 rw,subvol=/@\n"
USR_RW = "60 25 0:30 /@/usr /usr rw,noatime shared:1 - btrfs /dev/vda2 rw,subvol=/@\n"
LOCAL_RW = "61 60 0:30 /@/usr/local /usr/local rw,noatime shared:1 - btrfs /dev/vda2 rw,subvol=/@\n"
MTIME = 1761480000


class Root(unittest.TestCase):
    """Docasny koren, falesne mountinfo a falesny prikaz mount."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="luxos-protect-test-")
        self._old = care.ROOT
        care.ROOT = self.root
        self.mounts = [ROOT_LINE]
        self.cmds = []
        self.mount_fail = set()
        self.w("/etc/luxos/care.conf", "MODE=carefree\nPROTECT=yes\n")
        self.write_mountinfo()
        patches = [mock.patch.object(care, "run", self.fake_run),
                   mock.patch.object(care, "log", lambda *a, **k: None),
                   mock.patch.object(protect, "in_chroot", lambda: False),
                   mock.patch.object(protect.time, "sleep", lambda s: None),
                   mock.patch.object(care, "engine_running", lambda: False)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        care.ROOT = self._old
        shutil.rmtree(self.root, ignore_errors=True)

    def w(self, path, text="", mode=None, mtime=None):
        p = self.root + path
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb" if isinstance(text, bytes) else "w") as f:
            f.write(text)
        if mode is not None:
            os.chmod(p, mode)
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def write_mountinfo(self):
        self.w("/proc/self/mountinfo", "".join(self.mounts))

    def fake_run(self, cmd, timeout=600, input=None, env=None):
        self.cmds.append(" ".join(cmd))
        if cmd[0] != "mount":
            return self.other(cmd)
        key = " ".join(cmd[1:])
        if key in self.mount_fail:
            return 32, "mount: /usr: mount point is busy."
        if cmd[1] == "--rbind" and cmd[2] == "/usr":
            self.mounts.append(USR_RW)
        elif cmd[1] == "--bind" and cmd[2] == "/usr/local":
            self.mounts.append(LOCAL_RW)
        elif cmd[1:3] == ["-o", "remount,bind,ro"] and cmd[3] == "/usr":
            self.mounts = [USR_RO if m in (USR_RW, USR_RO) else m for m in self.mounts]
        elif cmd[1:3] == ["-o", "remount,bind,rw"] and cmd[3] == "/usr":
            self.mounts = [USR_RW if m in (USR_RW, USR_RO) else m for m in self.mounts]
        self.write_mountinfo()
        return 0, ""

    def other(self, cmd):
        return 0, ""

    def protected(self, ro=True):
        self.mounts = [ROOT_LINE, USR_RO if ro else USR_RW, LOCAL_RW]
        self.write_mountinfo()


# ---- pripojeni /usr ----------------------------------------------------------------------------
class MountState(Root):
    def test_states(self):
        self.assertEqual(protect.state(), "off")
        self.protected()
        self.assertEqual(protect.state(), "ro")
        self.protected(ro=False)
        self.assertEqual(protect.state(), "rw")

    def test_setup_binds_and_keeps_usr_local_writable(self):
        self.w("/usr/local/bin/.keep")
        protect.setup()
        self.assertEqual(protect.state(), "ro")
        self.assertEqual(self.cmds, ["mount --rbind /usr /usr", "mount --bind /usr/local /usr/local",
                                     "mount -o remount,bind,rw /usr/local", "mount -o remount,bind,ro /usr"])
        self.assertEqual(protect.mount_entry("/usr/local")["opts"][0], "rw")

    def test_writable_unlocks_and_locks_again(self):
        self.protected()
        with protect.writable() as active:
            self.assertTrue(active)
            self.assertEqual(protect.state(), "rw")
        self.assertEqual(protect.state(), "ro")
        self.assertEqual(self.cmds, ["mount -o remount,bind,rw /usr", "mount -o remount,bind,ro /usr"])

    def test_writable_locks_even_after_error(self):
        self.protected()
        with self.assertRaises(RuntimeError):
            with protect.writable():
                raise RuntimeError("transaction failed")
        self.assertEqual(protect.state(), "ro")

    def test_nested_holders_lock_only_at_the_end(self):
        """Dva drzitele (napr. LuxOS Care a lux v nem): zamkne az posledni."""
        self.protected()
        with protect.writable():
            with protect.writable():
                pass
            self.assertEqual(protect.state(), "rw")
            # hook na konci transakce: drzitel existuje -> nezamykat
            self.assertEqual(protect.hook_lock(), 0)
            self.assertEqual(protect.state(), "rw")
        self.assertEqual(protect.state(), "ro")

    def test_without_protection_nothing_happens(self):
        with protect.writable() as active:
            self.assertFalse(active)
        self.assertEqual(self.cmds, [])
        self.assertEqual(protect.hook_unlock(), 0)
        self.assertEqual(protect.hook_lock(), 0)
        self.assertEqual(self.cmds, [])

    def test_disabled_in_config_stays_writable(self):
        """PROTECT=no za behu: /usr se uz nezamyka (zmizi pri pristim startu)."""
        self.w("/etc/luxos/care.conf", "PROTECT=no\n")
        self.protected(ro=False)
        with protect.writable():
            pass
        self.assertEqual(protect.state(), "rw")

    def test_unlock_failure(self):
        self.protected()
        self.mount_fail.add("-o remount,bind,rw /usr")
        with self.assertRaises(protect.ProtectError):
            with protect.writable():
                self.fail("must not run")
        self.assertEqual(protect.hook_unlock(), 1)      # AbortOnFail: transakce se nespusti

    def test_busy_lock_retries_then_stays_writable(self):
        self.protected(ro=False)
        self.mount_fail.add("-o remount,bind,ro /usr")
        self.assertFalse(protect.relock())
        self.assertEqual(self.cmds.count("mount -o remount,bind,ro /usr"), 5)
        self.assertEqual(protect.state(), "rw")

    def test_relock_waits_for_running_transaction(self):
        self.protected(ro=False)
        self.w(care.DB_LOCK)
        with mock.patch.object(care, "engine_running", lambda: True):
            self.assertFalse(protect.relock())
            self.assertEqual(protect.state(), "rw")
            self.assertTrue(protect.relock(transaction_done=True))     # hook na konci transakce
        self.assertEqual(protect.state(), "ro")

    def test_hooks(self):
        self.protected()
        self.assertEqual(protect.hook_unlock(), 0)
        self.assertEqual(protect.state(), "rw")
        self.assertEqual(protect.hook_lock(), 0)
        self.assertEqual(protect.state(), "ro")

    def test_chroot_is_ignored(self):
        self.protected()
        with mock.patch.object(protect, "in_chroot", lambda: True):
            self.assertEqual(protect.hook_unlock(), 0)
            with protect.writable() as active:
                self.assertFalse(active)
        self.assertEqual(self.cmds, [])

    def test_apply_config(self):
        self.assertEqual(protect.apply_config(), "ro")              # zapnuto -> hned
        protect.set_conf("PROTECT", "no")
        self.assertEqual(protect.apply_config(), "rw")              # vypnuto -> hned zapisovatelny
        with open(self.root + "/etc/luxos/care.conf") as f:
            self.assertEqual(f.read(), "MODE=carefree\nPROTECT=no\n")
        protect.set_conf("PROTECT", "yes")
        self.assertEqual(protect.apply_config(), "ro")

    def test_care_system_writable_never_raises(self):
        self.protected()
        self.mount_fail.add("-o remount,bind,rw /usr")
        ran = []
        with care.system_writable():
            ran.append(1)
        self.assertEqual(ran, [1])


# ---- kontrola souboru baliku ---------------------------------------------------------------------
def sha(data):
    return hashlib.sha256(data).hexdigest()


class FakeDb(Root):
    """Lokalni databaze baliku s mtree jako v libalpm (gzip, /set, \\ooo)."""

    def add_package(self, name, ver, entries, backup=()):
        d = f"{protect.LOCAL_DB}/{name}-{ver}"
        self.w(f"{d}/desc", f"%NAME%\n{name}\n\n%VERSION%\n{ver}\n\n%ARCH%\nx86_64\n\n")
        files = "%FILES%\n" + "".join(e[0] + "\n" for e in entries) + "\n"
        if backup:
            files += "%BACKUP%\n" + "".join(f"{b}\td41d8cd98f00b204e9800998ecf8427e\n" for b in backup) + "\n"
        self.w(f"{d}/files", files)
        lines = ["#mtree", "/set type=file uid=0 gid=0 mode=644",
                 f"./.PKGINFO time={MTIME}.0 size=10 sha256digest=00"]
        for e in entries:
            lines.append(e[1])
        p = self.root + f"{d}/mtree"
        with gzip.open(p, "wt") as f:
            f.write("\n".join(lines) + "\n")

    def file_entry(self, rel, data, mode=0o644, mtime=MTIME, write=True, mtree_rel=None):
        if write:
            self.w("/" + rel, data, mode=mode, mtime=mtime)
        enc = (mtree_rel or rel).replace(" ", "\\040")
        return (rel, f"./{enc} time={MTIME}.123 mode={mode:o} size={len(data)} sha256digest={sha(data)}")


class Verify(FakeDb):
    def setUp(self):
        super().setUp()
        e = self.file_entry
        self.add_package("coreutils", "9.5-1", [
            ("usr/", "./usr time=1 mode=755 type=dir"),
            e("usr/bin/ls", b"ls-binary", mode=0o755),
            e("usr/bin/cat", b"cat-binary", mode=0o755),
            e("usr/share/doc/a b.txt", b"spaces"),
            ("usr/bin/dir", "./usr/bin/dir time=1 type=link link=ls"),
        ])
        os.symlink("ls", self.root + "/usr/bin/dir")
        self.add_package("sudo", "1.9-1", [
            e("usr/bin/sudo", b"sudo-binary", mode=0o4755),
            e("usr/bin/sudoedit", b"sudoedit", mode=0o755),
            e("etc/sudoers", b"root ALL"),                       # zaloha (konfigurace) - nekontroluje se
            e("etc/sudo.conf", b"x"),                            # mimo /usr a /opt
        ], backup=("etc/sudoers",))

    def test_clean_system(self):
        for full in (True, False):
            res = protect.verify(full=full)
            self.assertEqual(res["result"], "ok", res["problems"])
            self.assertEqual(res["packages"], 2)
            self.assertEqual(res["files"], 6)                    # 4 + odkaz + sudo, sudoedit (bez /etc)

    def test_detects_changes(self):
        self.w("/usr/bin/ls", b"LS-binary", mtime=MTIME)         # stejna velikost i cas, jiny obsah
        self.w("/usr/bin/cat", b"cat-binary-trojan")             # jina velikost
        os.unlink(self.root + "/usr/share/doc/a b.txt")
        os.unlink(self.root + "/usr/bin/dir")
        os.symlink("/tmp/evil", self.root + "/usr/bin/dir")
        os.chmod(self.root + "/usr/bin/sudoedit", 0o4755)       # nove setuid
        self.w("/etc/sudoers", b"changed by admin")
        self.w("/etc/sudo.conf", b"changed")
        res = protect.verify(full=True)
        got = {p["path"]: p["kind"] for p in res["problems"]}
        self.assertEqual(got, {"/usr/bin/ls": "modified", "/usr/bin/cat": "modified",
                               "/usr/share/doc/a b.txt": "missing", "/usr/bin/dir": "link",
                               "/usr/bin/sudoedit": "permissions"})
        self.assertEqual(res["affected"], ["coreutils", "sudo"])
        # rychla kontrola (velikost, cas): obsah se stejnou velikosti a casem neuvidi
        quick = {p["path"] for p in protect.verify(full=False)["problems"]}
        self.assertNotIn("/usr/bin/ls", quick)
        self.assertIn("/usr/bin/cat", quick)

    def test_quick_hashes_when_time_differs(self):
        self.w("/usr/bin/ls", b"LS-binary", mtime=MTIME + 100)
        self.assertEqual([p["path"] for p in protect.verify(full=False)["problems"]], ["/usr/bin/ls"])
        self.w("/usr/bin/ls", b"ls-binary", mtime=MTIME + 100)   # jen "touch": obsah sedi
        self.assertEqual(protect.verify(full=False)["problems"], [])

    def test_type_and_ignore(self):
        os.unlink(self.root + "/usr/bin/cat")
        os.makedirs(self.root + "/usr/bin/cat")
        self.assertEqual(protect.verify()["problems"][0]["kind"], "type")
        self.w(protect.VERIFY_IGNORE_CONF, "# vlastni upravy\n/usr/bin/c*\n")
        self.assertEqual(protect.verify()["problems"], [])

    def test_builtin_ignore(self):
        """LuxOS hook zamerne prepisuje os-release baliku filesystem - neni to nalez."""
        self.add_package("filesystem", "2025-1", [self.file_entry("usr/lib/os-release", b"NAME=Arch")])
        self.w("/usr/lib/os-release", b"NAME=LuxOS")
        self.assertEqual(protect.verify()["problems"], [])

    def test_selected_packages(self):
        self.w("/usr/bin/cat", b"x")
        res = protect.verify(names=["sudo"])
        self.assertEqual((res["packages"], res["problems"], res["partial"]), (1, [], True))

    def test_unreadable_is_not_a_problem(self):
        with mock.patch.object(protect, "_digest", side_effect=PermissionError):
            res = protect.verify(full=True)
        self.assertEqual(res["problems"], [])
        self.assertEqual(res["unreadable"], 5)

    def test_parse_mtree(self):
        items = protect.parse_mtree("#mtree\n/set type=file mode=644\n./a\\040b time=1 size=2\n"
                                    "/set mode=755\n./bin/x type=link link=y\\040z\n/unset mode\n./c size=1\n")
        self.assertEqual(items[0], ("a b", {"type": "file", "mode": "644", "time": "1", "size": "2"}))
        self.assertEqual(items[1][1]["link"], "y z")
        self.assertEqual(items[1][1]["mode"], "755")
        self.assertNotIn("mode", items[2][1])

    def test_stop_on_battery(self):
        res = protect.verify(stop=lambda: True)
        self.assertEqual(res["result"], "stopped")


class RunVerify(FakeDb):
    def setUp(self):
        super().setUp()
        self.add_package("coreutils", "9.5-1", [self.file_entry("usr/bin/ls", b"ls")])
        self.events = []
        self.hist = []
        self.power = True
        for p in (mock.patch.object(care, "add_event", lambda k, **d: self.events.append((k, d))),
                  mock.patch.object(care, "history", lambda k, **d: self.hist.append((k, d))),
                  mock.patch.object(protect, "power_ok", lambda: self.power)):
            p.start()
            self.addCleanup(p.stop)

    def test_auto_due_power_and_notify(self):
        self.w("/usr/bin/ls", b"LS", mtime=MTIME)
        self.power = False
        self.assertEqual(protect.run_verify(auto=True)["result"], "postponed")
        self.power = True
        res = protect.run_verify(auto=True)
        self.assertEqual(res["result"], "problems")
        self.assertEqual(self.events, [("integrity", {"count": 1, "packages": ["coreutils"]})])
        self.assertEqual(self.hist[0][0], "verify")
        self.assertEqual(protect.load_result()["affected"], ["coreutils"])
        self.assertFalse(os.path.exists(self.root + protect.VERIFY_PROGRESS))
        self.assertEqual(protect.run_verify(auto=True)["result"], "not_due")     # za tyden znovu

    def test_ok_is_silent(self):
        res = protect.run_verify(auto=True)
        self.assertEqual(res["result"], "ok")
        self.assertEqual((self.events, self.hist), ([], []))

    def test_manual_does_not_notify(self):
        self.w("/usr/bin/ls", b"LS", mtime=MTIME)
        protect.run_verify()
        self.assertEqual(self.events, [])

    def test_disabled(self):
        self.w("/etc/luxos/care.conf", "VERIFY=no\n")
        self.assertEqual(protect.run_verify(auto=True)["result"], "disabled")
        self.assertEqual(protect.run_verify()["result"], "ok")                   # rucne jde vzdy

    def test_busy(self):
        os.makedirs(self.root + care.RUN_DIR, exist_ok=True)
        import fcntl
        fd = os.open(self.root + protect.VERIFY_LOCK, os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self.assertEqual(protect.run_verify()["result"], "busy")
        finally:
            os.close(fd)

    def test_partial_merges_into_full_result(self):
        self.add_package("sudo", "1.9-1", [self.file_entry("usr/bin/sudo", b"sudo")])
        self.w("/usr/bin/ls", b"LS", mtime=MTIME)
        self.w("/usr/bin/sudo", b"SUDO", mtime=MTIME)
        full = protect.run_verify()
        self.assertEqual(full["affected"], ["coreutils", "sudo"])
        self.w("/usr/bin/sudo", b"sudo", mtime=MTIME)
        res = protect.run_verify(names=["sudo"])
        self.assertEqual(res["affected"], ["coreutils"])
        self.assertEqual(res["time"], full["time"])          # datum posledni cele kontroly zustava
        self.assertFalse(res.get("partial"))

    def test_schedule(self):
        with mock.patch.object(protect, "verify_due", lambda: True):
            self.assertTrue(protect.schedule_verify())
            self.assertIn("systemctl start --no-block luxos-care-verify.service", self.cmds)
            self.cmds.clear()
            self.power = False
            self.assertFalse(protect.schedule_verify())
            self.power = True
            self.w("/proc/cmdline", "root=x luxos.snapshot=2026-10-26_10-00-00\n")
            self.assertFalse(protect.schedule_verify())
        self.assertEqual(self.cmds, [])
        self.assertTrue(protect.verify_due({}, t=protect.VERIFY_EVERY))
        self.assertFalse(protect.verify_due({"time": 100}, t=100 + protect.VERIFY_EVERY - 1))


class PowerRules(unittest.TestCase):
    def test_power(self):
        cases = [((None, []), True), ((True, [(30, "Discharging")]), True), ((False, [(90, "Discharging")]), False),
                 ((False, [(90, "Charging")]), True), ((None, [(100, "Full")]), True)]
        for supplies, want in cases:
            with mock.patch.object(care, "power_supplies", lambda s=supplies: s):
                self.assertEqual(protect.power_ok(), want, supplies)


class Repair(FakeDb):
    def setUp(self):
        super().setUp()
        self.add_package("coreutils", "9.5-1", [self.file_entry("usr/bin/ls", b"ls")])
        self.add_package("sudo", "1.9-1", [self.file_entry("usr/bin/sudo", b"sudo")])
        self.add_package("mytool", "1-1", [self.file_entry("usr/bin/mytool", b"mine")])
        self.w("/usr/bin/ls", b"LS", mtime=MTIME)
        self.w("/usr/bin/mytool", b"MINE", mtime=MTIME)
        self.hist = []
        self.broken_repo = set()
        for p in (mock.patch.object(care, "history", lambda k, **d: self.hist.append((k, d))),
                  mock.patch.object(care, "add_event", lambda *a, **k: None),
                  mock.patch.object(care, "lux_available", lambda: True)):
            p.start()
            self.addCleanup(p.stop)

    def other(self, cmd):
        if cmd[0] == care.ENGINE and cmd[1] == "-Qmq":
            return 0, "mytool\n"
        if cmd[0] == care.LUX_ALPM and "reinstall" in cmd:
            names = cmd[cmd.index("--") + 1:]
            # reinstalace musi bezet se zapisovatelnym /usr
            self.reinstall_state = protect.state()
            if set(names) & self.broken_repo:
                return 1, "error: target not found"
            for n in names:
                if n == "coreutils":
                    self.w("/usr/bin/ls", b"ls", mtime=MTIME)
            return 0, ""
        return 0, ""

    def test_repair_from_signed_repos(self):
        self.protected()
        protect.run_verify()
        res = protect.repair(protect.load_result()["affected"])
        self.assertEqual(res["repaired"], ["coreutils"])
        self.assertEqual(res["foreign"], ["mytool"])           # neni v repozitarich
        self.assertEqual(res["failed"], [])
        self.assertEqual(res["result"], "ok")
        self.assertEqual(self.reinstall_state, "rw")
        self.assertEqual(protect.state(), "ro")
        self.assertTrue(any(c.endswith("reinstall -- coreutils") for c in self.cmds), self.cmds)
        st = protect.load_result()
        self.assertEqual(st["affected"], ["mytool"])
        self.assertEqual(self.hist[-1][0], "verify_repair")

    def test_one_bad_package_does_not_stop_others(self):
        self.w("/usr/bin/sudo", b"SUDO", mtime=MTIME)
        self.broken_repo.add("sudo")
        res = protect.repair(["coreutils", "sudo"])
        self.assertEqual(res["repaired"], ["coreutils"])
        self.assertEqual(res["failed"], ["sudo"])
        self.assertEqual(res["result"], "failed")

    def test_invalid_names_are_ignored(self):
        self.assertEqual(protect.repair(["../x", "a b"])["result"], "nothing")


# ---- skript pri startu -------------------------------------------------------------------------
class BootScript(unittest.TestCase):
    SCRIPT = os.path.join(FILES, "protect", "luxos-protect-boot")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-protect-boot-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "log")
        self.usr = os.path.join(self.tmp, "usr")
        os.makedirs(os.path.join(self.usr, "local"))
        # mount/mountpoint jen zapisuji, co by se volalo (MOUNT_FAIL = argumenty, ktere selzou)
        self.fake("mount", 'echo "mount $*" >>"$LOG"; [[ "$*" == "${MOUNT_FAIL-}" ]] && exit 32; exit 0')
        self.fake("mountpoint", 'echo "mountpoint $*" >>"$LOG"; for m in ${MOUNTED-}; do '
                  '[[ ${!#} == "$m" ]] && exit 0; done; exit 1')
        self.conf = os.path.join(self.tmp, "care.conf")
        self.cmdline = os.path.join(self.tmp, "cmdline")
        with open(self.cmdline, "w") as f:
            f.write("root=UUID=x rootflags=subvol=@ rw quiet\n")

    def fake(self, name, body):
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write("#!/bin/bash\n" + body + "\n")
        os.chmod(p, 0o755)

    def run_script(self, conf="PROTECT=yes\n", cmdline=None, **env):
        with open(self.conf, "w") as f:
            f.write(conf)
        if cmdline is not None:
            with open(self.cmdline, "w") as f:
                f.write(cmdline)
        e = {"PATH": self.bin + ":/usr/bin:/bin", "LOG": self.log, "LUXOS_PROTECT_CONF": self.conf,
             "LUXOS_PROTECT_CMDLINE": self.cmdline, "LUXOS_PROTECT_USR": self.usr,
             "LUXOS_PROTECT_LIVE": os.path.join(self.tmp, "no-archiso")}
        e.update(env)
        if os.path.exists(self.log):
            os.unlink(self.log)
        r = subprocess.run(["bash", self.SCRIPT], env=e, capture_output=True, text=True, timeout=30)
        try:
            with open(self.log) as f:
                calls = [x for x in f.read().splitlines() if x.startswith("mount ")]
        except OSError:
            calls = []
        return r.returncode, calls, r.stderr

    def test_protects(self):
        rc, calls, _e = self.run_script('MODE=carefree\nPROTECT="yes"\n')
        u = self.usr
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [f"mount --rbind {u} {u}", f"mount --bind {u}/local {u}/local",
                                 f"mount -o remount,bind,rw {u}/local", f"mount -o remount,bind,ro {u}"])

    def test_off_cases(self):
        for conf, cmdline in (("MODE=carefree\n", None), ("PROTECT=no\n", None), ("PROTECT=yes\nPROTECT=no\n", None),
                              ("PROTECT=yes\n", "root=x luxos.protect=0\n"),
                              ("PROTECT=yes\n", "root=x luxos.snapshot=2026-10-26_10-00-00 systemd.volatile=overlay\n"),
                              ("PROTECT=yes\n", "root=x systemd.unit=luxos-recovery.target\n")):
            rc, calls, _e = self.run_script(conf, cmdline)
            self.assertEqual((rc, calls), (0, []), (conf, cmdline))
        open(os.path.join(self.tmp, "archiso"), "w").close()
        rc, calls, _e = self.run_script(cmdline="root=x\n", LUXOS_PROTECT_LIVE=os.path.join(self.tmp, "archiso"))
        self.assertEqual((rc, calls), (0, []))

    def test_failure_never_stops_boot(self):
        u = self.usr
        rc, calls, err = self.run_script(cmdline="root=x\n", MOUNT_FAIL=f"--rbind {u} {u}")
        self.assertEqual((rc, calls), (0, [f"mount --rbind {u} {u}"]))
        self.assertIn("stay writable", err)
        rc, calls, err = self.run_script(MOUNT_FAIL=f"-o remount,bind,ro {u}")
        self.assertEqual(rc, 0)
        self.assertIn("could not make", err)

    def test_already_mounted(self):
        u = self.usr
        rc, calls, _e = self.run_script(cmdline="root=x\n", MOUNTED=f"{u} {u}/local")
        self.assertEqual(calls, [f"mount -o remount,bind,ro {u}"])

    def test_syntax(self):
        self.assertEqual(subprocess.run(["bash", "-n", self.SCRIPT]).returncode, 0)


# ---- hooky, jednotky, prikazova radka ------------------------------------------------------------
class Packaging(unittest.TestCase):
    def read(self, *p):
        with open(os.path.join(FILES, *p)) as f:
            return f.read()

    def test_hooks_order_and_abort(self):
        pre = self.read("hooks", "00-0-luxos-protect.hook")
        post = self.read("hooks", "zz-luxos-protect.hook")
        self.assertIn("When = PreTransaction", pre)
        self.assertIn("AbortOnFail", pre)
        self.assertIn("Exec = /usr/bin/luxos-care protect unlock", pre)
        self.assertIn("When = PostTransaction", post)
        self.assertIn("Exec = /usr/bin/luxos-care protect lock", post)
        # libalpm radi hooky podle jmena souboru: odemknout pred vsemi (i 00-lux-engine-migrate),
        # zamknout po vsech (95-luxos-care-kernel-post zapisuje do /usr/lib/modules)
        names = sorted(os.listdir(os.path.join(FILES, "hooks")) + ["00-lux-engine-migrate.hook",
                       "10-luxos-branding.hook", "gtk-update-icon-cache.hook", "luxos-xsession.hook",
                       "update-desktop-database.hook", "xorg-mkfontscale.hook"])
        self.assertEqual(names[0], "00-0-luxos-protect.hook")
        self.assertEqual(names[-1], "zz-luxos-protect.hook")

    def test_units(self):
        boot = self.read("systemd", "luxos-protect.service")
        self.assertIn("DefaultDependencies=no", boot)
        self.assertIn("Before=sysinit.target", boot)
        self.assertIn("ConditionKernelCommandLine=!luxos.snapshot", boot)
        self.assertIn("WantedBy=sysinit.target", boot)
        weekly = self.read("systemd", "luxos-care-verify.service")
        self.assertIn("IOSchedulingClass=idle", weekly)
        self.assertIn("Nice=19", weekly)
        self.assertIn("verify --auto", weekly)
        rules = self.read("50-luxos-care.rules")
        for unit in ("luxos-care-verify-now.service", "luxos-care-repair-now.service"):
            self.assertIn(unit, rules)
        self.assertNotIn("luxos-protect.service", rules)


def load_cli():
    loader = importlib.machinery.SourceFileLoader("luxos_care_cli", os.path.join(FILES, "luxos-care"))
    spec = importlib.util.spec_from_loader("luxos_care_cli", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Cli(FakeDb):
    def setUp(self):
        super().setUp()
        self.cli = load_cli()
        self.add_package("coreutils", "9.5-1", [self.file_entry("usr/bin/ls", b"ls")])
        for p in (mock.patch.object(care, "history", lambda *a, **k: None),
                  mock.patch.object(care, "add_event", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)

    def call(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                rc = self.cli.main(["luxos-care"] + list(args))
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue()

    def test_status_and_verify(self):
        rc, out = self.call("protect", "status", "--json")
        st = json.loads(out)
        self.assertEqual((rc, st["enabled"], st["state"], st["verified"]), (0, True, "off", 0))
        rc, out = self.call("verify")
        self.assertEqual(rc, 0)
        self.assertIn("No modified system files.", out)
        self.w("/usr/bin/ls", b"xx", mtime=MTIME)
        rc, out = self.call("verify")
        self.assertEqual(rc, 1)
        self.assertIn("coreutils: /usr/bin/ls (changed)", out)
        rc, out = self.call("protect")
        self.assertIn("1 system files were changed or are missing: coreutils", out)

    def test_enable_disable_exec(self):
        rc, out = self.call("protect", "enable")
        self.assertEqual(rc, 0)
        self.assertEqual(protect.state(), "ro")
        with mock.patch("subprocess.call", lambda cmd: 0 if protect.state() == "rw" else 9):
            rc, _o = self.call("protect", "exec", "--", "locale-gen")
        self.assertEqual(rc, 0)
        self.assertEqual(protect.state(), "ro")
        rc, out = self.call("protect", "disable")
        self.assertEqual(protect.state(), "rw")
        with open(self.root + "/etc/luxos/care.conf") as f:
            self.assertIn("PROTECT=no\n", f.read())


if __name__ == "__main__":
    unittest.main()
