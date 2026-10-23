"""Testy Trezoru (luxos-safe, luxos-safe-helper) bez rootu: logika s nahradami (mock).

    python3 -m unittest discover -s packages/luxos-safe/tests -v

Skutecne pripojovani (tmpfs, gocryptfs, fusermount3) overuje test_userns.py
v jednorazovem uzivatelskem jmennem prostoru.
"""
import datetime
import errno
import importlib.machinery
import importlib.util
import os
import shutil
import signal
import stat
import struct
import subprocess
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


safe = load("luxos_safe_under_test", os.path.join(FILES, "luxos-safe"))
helper = load("luxos_safe_helper_under_test", os.path.join(FILES, "luxos-safe-helper"))

MNT = "/safe/tester"
VAULT = "/safe/.vaults/tester"


def mountinfo(*entries):
    """Radky /proc/self/mountinfo: (mountpoint, fstype, source)."""
    lines = ["22 1 0:21 / / rw,relatime - btrfs /dev/vda2 rw"]
    for i, (mp, fs, src) in enumerate(entries):
        lines.append(f"{100 + i} 22 0:{50 + i} / {mp.replace(' ', chr(92) + '040')} rw,relatime - {fs} {src} rw")
    return "\n".join(lines) + "\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-safe-test-")
        self.mi = os.path.join(self.tmp, "mountinfo")
        self.saved = {k: getattr(safe, k) for k in ("MOUNT", "VAULT", "MOUNTINFO", "RECOVERED", "HOME", "CONF")}
        safe.MOUNT, safe.VAULT, safe.MOUNTINFO = MNT, VAULT, self.mi
        safe.RECOVERED = os.path.join(self.tmp, "recovered")
        safe.HOME = os.path.join(self.tmp, "home")
        safe.CONF = os.path.join(self.tmp, "safe.json")
        os.mkdir(safe.HOME)
        self.set_mounts()
        self.notes = []
        p = mock.patch.object(safe, "notify", lambda *a: self.notes.append(a))
        p.start()
        self.addCleanup(p.stop)
        del safe.recovered_now[:]

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(safe, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def set_mounts(self, *entries):
        with open(self.mi, "w") as f:
            f.write(mountinfo(*entries))


LOCKED = ((MNT, "tmpfs", "luxos-safe-locked"),)
UNLOCKED = LOCKED + ((MNT, "fuse.gocryptfs", VAULT),)


class State(Base):
    def test_legacy_unprotected_dir_is_not_unlocked(self):
        # Puvodni chyba: obycejny adresar na disku vypadal jako "zamceno" a dal se do nej zapisovat
        self.set_mounts()
        self.assertFalse(safe.is_unlocked())
        self.assertFalse(safe.protected())

    def test_placeholder_only_is_locked_and_protected(self):
        self.set_mounts(*LOCKED)
        self.assertFalse(safe.is_unlocked())
        self.assertTrue(safe.protected())

    def test_gocryptfs_on_top_is_unlocked(self):
        self.set_mounts(*UNLOCKED)
        self.assertTrue(safe.is_unlocked())
        self.assertTrue(safe.protected())
        self.assertEqual(safe.state(), "unlocked")

    def test_gocryptfs_below_other_mount_is_not_unlocked(self):
        self.set_mounts((MNT, "fuse.gocryptfs", VAULT), (MNT, "tmpfs", "luxos-safe-locked"))
        self.assertFalse(safe.is_unlocked())

    def test_other_paths_ignored_and_escapes(self):
        self.set_mounts(("/safe/tester2", "fuse.gocryptfs", "/x"), ("/safe/tester/sub", "tmpfs", "luxos-safe-locked"))
        self.assertEqual(safe.mounts(), [])
        safe.MOUNT = "/safe/a b"
        self.set_mounts(("/safe/a b", "tmpfs", "luxos-safe-locked"))
        self.assertEqual(safe.mounts(), [("tmpfs", "luxos-safe-locked")])

    def test_helper_parses_same_format(self):
        with open(self.mi, "w") as f:
            f.write(mountinfo(*UNLOCKED))
        self.assertEqual(helper.mounts_at(MNT, self.mi), [("tmpfs", "luxos-safe-locked"), ("fuse.gocryptfs", VAULT)])


class Unlock(Base):
    def test_refuses_without_protection(self):
        """Bez zastupne slozky se neodemyka (po zamceni by se dalo zase psat na disk)."""
        calls = []
        with mock.patch.object(safe, "run_helper", lambda c: calls.append(c) or "polkit failed"), \
                mock.patch.object(safe, "run_pw") as pw, mock.patch.object(safe, "state", lambda: "locked"):
            msg = safe.unlock("password1")
        self.assertEqual(calls, ["protect"])
        self.assertIn("polkit failed", msg)
        pw.assert_not_called()

    def test_helper_ok_but_still_unprotected(self):
        with mock.patch.object(safe, "run_helper", lambda c: None), \
                mock.patch.object(safe, "run_pw") as pw, mock.patch.object(safe, "state", lambda: "locked"):
            self.assertTrue(safe.unlock("password1"))
        pw.assert_not_called()

    def test_protects_legacy_then_mounts_nonempty(self):
        def helper_call(cmd):
            self.set_mounts(*LOCKED)
            return None
        args = []
        with mock.patch.object(safe, "run_helper", helper_call), mock.patch.object(safe, "trust_launcher"), \
                mock.patch.object(safe, "run_pw", lambda a, p: args.append(a) or (0, "")), \
                mock.patch.object(safe, "state", lambda: "locked"):
            self.assertIsNone(safe.unlock("password1"))
        self.assertEqual(args[0][-3:], ["-nonempty", VAULT, MNT])
        self.assertIn("-i", args[0])

    def test_wrong_password(self):
        self.set_mounts(*LOCKED)
        with mock.patch.object(safe, "run_helper") as rh, mock.patch.object(safe, "trust_launcher"), \
                mock.patch.object(safe, "run_pw", lambda a, p: (safe.WRONG_PASSWORD, "")), \
                mock.patch.object(safe, "state", lambda: "locked"):
            self.assertEqual(safe.unlock("x"), "Wrong password.")
        rh.assert_not_called()

    def test_create_runs_helper_when_unprotected(self):
        calls = []
        with mock.patch.object(safe, "run_helper", lambda c: calls.append(c)), \
                mock.patch.object(safe.os.path, "isdir", lambda p: True):
            self.assertEqual(safe.create("password1"), "Could not create the Safe folder.")
        self.assertEqual(calls, ["create"])


class Holders(Base):
    def test_fuser_parsing_excludes_self_and_gocryptfs(self):
        me = os.getpid()
        out = types.SimpleNamespace(stdout=f" 4242 {me} 777c 31337", stderr=f"{MNT}:  ", returncode=0)
        comms = {4242: "soffice.bin", 777: "bash", 31337: "gocryptfs"}

        real_open = open

        class F:
            def __init__(self, t):
                self.t = t

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.t

        def fopen(path, *a, **kw):
            if path.startswith("/proc/") and path.endswith("/comm") and int(path.split("/")[2]) in comms:
                return F(comms[int(path.split("/")[2])] + "\n")
            return real_open(path, *a, **kw)

        with mock.patch.object(safe.subprocess, "run", return_value=out) as run, \
                mock.patch.object(safe, "_gocryptfs_pids", return_value=[31337]), \
                mock.patch("builtins.open", fopen):
            res = safe.holders()
        self.assertEqual(run.call_args[0][0], ["fuser", "-m", MNT])
        self.assertEqual(res, [(777, "bash"), (4242, "soffice.bin")])
        self.assertEqual(safe.busy_message(res),
                         "These apps keep files in the Safe open: bash, soffice.bin. Close them and try again.")

    def test_no_names_falls_back(self):
        self.assertEqual(safe.busy_message([]), "Some files in the Safe are still open. Close them and try again.")


class Lock(Base):
    """Zadne line odpojeni se zivym gocryptfs; otevrene soubory -> nazvy aplikaci."""

    def setUp(self):
        super().setUp()
        self.set_mounts(*UNLOCKED)
        self.runs = []
        self.busy = True

        def run(args, **kw):
            self.runs.append(args)
            if args[0] == "fusermount3":
                if self.busy and "-uz" not in args:
                    return types.SimpleNamespace(returncode=1, stdout="", stderr="Device or resource busy")
                self.set_mounts(*LOCKED)
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")
            raise AssertionError(args)

        for p in (mock.patch.object(safe.subprocess, "run", run),
                  mock.patch.object(safe.time, "sleep", lambda s: None),
                  mock.patch.object(safe, "holders", lambda: [(4242, "soffice.bin")]),
                  mock.patch.object(safe, "trust_launcher")):
            p.start()
            self.addCleanup(p.stop)

    def lazy_used(self):
        return any("-uz" in a for a in self.runs)

    def test_lock_success(self):
        self.busy = False
        self.assertIsNone(safe.lock())
        self.assertEqual(self.runs, [["fusermount3", "-u", MNT]])
        self.assertEqual(safe.state(), "none")   # VAULT v testu neexistuje; podstatne je, ze neni "unlocked"
        self.assertFalse(safe.is_unlocked())

    def test_not_unlocked_is_noop(self):
        self.set_mounts(*LOCKED)
        self.assertIsNone(safe.lock("logout"))
        self.assertEqual(self.runs, [])

    def test_manual_busy_names_apps(self):
        msg = safe.lock()
        self.assertIn("soffice.bin", msg)
        self.assertTrue(safe.is_unlocked())
        self.assertFalse(self.lazy_used())
        self.assertEqual(self.notes, [])

    def test_auto_busy_retries_and_notifies_without_lazy(self):
        with mock.patch.object(safe.os, "kill") as kill:
            msg = safe.lock("auto")
        self.assertIn("soffice.bin", msg)
        self.assertEqual(len([a for a in self.runs if a[0] == "fusermount3"]), 1 + safe.LOCK_RETRY)
        self.assertFalse(self.lazy_used())
        kill.assert_not_called()
        self.assertEqual(self.notes[0][0], "The Safe could not be locked")
        self.assertTrue(safe.is_unlocked())

    def test_auto_succeeds_after_app_closes(self):
        n = {"i": 0}

        def closing_sleep(_s):
            n["i"] += 1
            if n["i"] == 2:
                self.busy = False
        with mock.patch.object(safe.time, "sleep", closing_sleep):
            self.assertIsNone(safe.lock("auto"))
        self.assertFalse(self.lazy_used())
        self.assertEqual(self.notes, [])

    def test_logout_terminates_holders_then_kills_gocryptfs_before_lazy(self):
        events = []

        def kill(pid, sig):
            events.append((pid, sig))
        with mock.patch.object(safe.os, "kill", kill), mock.patch.object(safe, "_gocryptfs_pids", lambda: [31337]):
            orig_run = safe.subprocess.run

            def run(args, **kw):
                if "-uz" in args:
                    events.append("lazy")
                return orig_run(args, **kw)
            with mock.patch.object(safe.subprocess, "run", run):
                self.assertIsNone(safe.lock("logout"))
        self.assertEqual(events, [(4242, signal.SIGTERM), (31337, signal.SIGKILL), "lazy"])
        self.assertFalse(safe.is_unlocked())

    def test_logout_holder_closes_after_sigterm(self):
        def kill(pid, sig):
            self.busy = False
        with mock.patch.object(safe.os, "kill", kill), mock.patch.object(safe, "_gocryptfs_pids", lambda: [31337]):
            self.assertIsNone(safe.lock("logout"))
        self.assertFalse(self.lazy_used())

    def test_cli_flags(self):
        seen = []
        with mock.patch.object(safe, "lock", lambda mode="manual": seen.append(mode)), \
                mock.patch.object(safe.sys, "argv", ["luxos-safe", "lock", "--logout"]):
            safe.main()
        with mock.patch.object(safe, "lock", lambda mode="manual": seen.append(mode)), \
                mock.patch.object(safe.sys, "argv", ["luxos-safe", "lock", "--force"]):
            safe.main()
        with mock.patch.object(safe, "lock", lambda mode="manual": seen.append(mode)), \
                mock.patch.object(safe.sys, "argv", ["luxos-safe", "lock"]):
            safe.main()
        self.assertEqual(seen, ["logout", "auto", "manual"])


class Subscribe(Base):
    """Uspani: zpozdeni (logind delay) drzet, dokud se nezamkne; zamceni obrazovky podle nastaveni."""

    def test_sleep_and_screensaver(self):
        try:
            from gi.repository import Gio
        except ImportError:
            self.skipTest("PyGObject not installed")
        subs = {}

        class Bus:
            def signal_subscribe(self, sender, iface, member, path, arg0, flags, cb):
                subs[member] = cb
        fds = []

        def take(_bus):
            r, w = os.pipe()
            os.close(w)
            fds.append(r)
            return r
        locks = []
        done = []

        class T:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                self.target()
                done.append(1)
        params = lambda v: types.SimpleNamespace(unpack=lambda: (v,))  # noqa: E731
        with mock.patch.object(Gio, "bus_get_sync", lambda t: Bus()), \
                mock.patch.object(safe, "take_sleep_inhibitor", take), \
                mock.patch.object(safe, "lock", lambda mode="manual": locks.append(mode)), \
                mock.patch.object(safe.threading, "Thread", T), \
                mock.patch.object(safe, "state", lambda: "unlocked"):
            safe.subscribe()
            self.assertEqual(len(fds), 1)
            subs["PrepareForSleep"](None, None, None, None, None, params(True))
            self.assertEqual(locks, ["auto"])
            with self.assertRaises(OSError):
                os.fstat(fds[0])            # inhibitor uvolnen az po zamceni
            subs["PrepareForSleep"](None, None, None, None, None, params(False))
            self.assertEqual(len(fds), 2)   # po probuzeni znovu
            subs["ActiveChanged"](None, None, None, None, None, params(True))
            self.assertEqual(locks, ["auto", "auto"])
            safe.save_settings({"lock_on_screen_lock": False})
            subs["ActiveChanged"](None, None, None, None, None, params(True))
            self.assertEqual(locks, ["auto", "auto"])
            os.close(fds[1])


class Recover(Base):
    def make_stage(self, name="2026-10-01_101010", files=None):
        d = os.path.join(safe.RECOVERED, name)
        os.makedirs(d)
        for rel, data in (files or {"secret.txt": "tajne", "sub/a.txt": "A"}).items():
            os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
            with open(os.path.join(d, rel), "w") as f:
                f.write(data)
        return d

    def test_moves_to_home_0700_and_notifies(self):
        src = self.make_stage()
        os.symlink("/etc/passwd", os.path.join(src, "link"))
        moved = safe.recover_plaintext()
        today = datetime.date.today().isoformat()
        self.assertEqual(moved, [os.path.join(safe.HOME, f"Safe-unencrypted-recovered-{today}")])
        dest = moved[0]
        self.assertEqual(stat.S_IMODE(os.stat(dest).st_mode), 0o700)
        self.assertEqual(sorted(os.listdir(dest)), ["link", "secret.txt", "sub"])
        self.assertEqual(os.readlink(os.path.join(dest, "link")), "/etc/passwd")   # symlink se nesleduje
        with open(os.path.join(dest, "sub", "a.txt")) as f:
            self.assertEqual(f.read(), "A")
        self.assertFalse(os.path.exists(src))
        self.assertEqual(self.notes[0][0], "Unencrypted files found")
        self.assertIn(dest, self.notes[0][1])

    def test_never_overwrites_existing_folder(self):
        today = datetime.date.today().isoformat()
        old = os.path.join(safe.HOME, f"Safe-unencrypted-recovered-{today}")
        os.mkdir(old)
        with open(os.path.join(old, "keep"), "w") as f:
            f.write("x")
        self.make_stage("a")
        self.make_stage("b", {"other.txt": "o"})
        moved = safe.recover_plaintext()
        self.assertEqual([os.path.basename(m) for m in moved],
                         [f"Safe-unencrypted-recovered-{today}-2", f"Safe-unencrypted-recovered-{today}-3"])
        self.assertEqual(os.listdir(old), ["keep"])

    def test_empty_stage_and_missing_dir(self):
        self.assertEqual(safe.recover_plaintext(), [])
        os.makedirs(os.path.join(safe.RECOVERED, "empty"))
        self.assertEqual(safe.recover_plaintext(), [])
        self.assertEqual(os.listdir(safe.RECOVERED), [])
        self.assertEqual(self.notes, [])

    def test_import_requires_unlocked_and_moves(self):
        self.make_stage()
        dest = safe.recover_plaintext()[0]
        self.set_mounts(*LOCKED)
        self.assertTrue(safe.import_recovered(dest))
        self.assertTrue(os.path.isdir(dest))         # zamceno: nic se nesmaze
        safe.MOUNT = os.path.join(self.tmp, "mnt")
        os.mkdir(safe.MOUNT)
        self.set_mounts((safe.MOUNT, "fuse.gocryptfs", VAULT))
        self.assertIsNone(safe.import_recovered(dest))
        self.assertFalse(os.path.exists(dest))
        inside = os.path.join(safe.MOUNT, os.path.basename(dest))
        with open(os.path.join(inside, "secret.txt")) as f:
            self.assertEqual(f.read(), "tajne")


class HelperUnit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-safe-helper-test-")
        self.old_i18n = helper.I18N

    def tearDown(self):
        helper.I18N = self.old_i18n
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_launcher_has_all_languages_and_is_stable(self):
        helper.I18N = I18N
        t = helper.launcher_text().decode()
        self.assertIn("Exec=luxos-safe unlock --open\n", t)
        for lang in helper.LANGS:
            self.assertIn(f"Name[{lang}]=", t)
            self.assertIn(f"Comment[{lang}]=", t)
        self.assertIn("Name[cs]=Odemknout Trezor\n", t)
        self.assertEqual(t, helper.launcher_text().decode())

    def test_legacy_launcher_detection(self):
        fd = os.open(self.tmp, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with open(os.path.join(self.tmp, "Unlock Safe.desktop"), "wb") as f:
                f.write(helper.LEGACY_LAUNCHER)
            self.assertTrue(helper.is_legacy_launcher(fd, "Unlock Safe.desktop"))
            with open(os.path.join(self.tmp, "Unlock Safe.desktop"), "ab") as f:
                f.write(b"# user edit\n")
            self.assertFalse(helper.is_legacy_launcher(fd, "Unlock Safe.desktop"))
            os.symlink("/etc/passwd", os.path.join(self.tmp, "l"))
            self.assertFalse(helper.is_legacy_launcher(fd, "l"))
        finally:
            os.close(fd)

    def test_set_immutable_bits_and_unsupported(self):
        calls = []

        def ioctl(fd, req, arg):
            calls.append((req, struct.unpack("i", arg)[0]))
            return struct.pack("i", 0x80000) if req == helper.FS_IOC_GETFLAGS else arg
        with mock.patch.object(helper.fcntl, "ioctl", ioctl):
            self.assertTrue(helper.set_immutable(5, True))
        self.assertEqual(calls[-1], (helper.FS_IOC_SETFLAGS, 0x80000 | helper.FS_IMMUTABLE_FL))

        def eperm(fd, req, arg):
            raise OSError(errno.EPERM, "no")
        with mock.patch.object(helper.fcntl, "ioctl", eperm):
            self.assertFalse(helper.set_immutable(5, True))

        def eio(fd, req, arg):
            raise OSError(errno.EIO, "io")
        with mock.patch.object(helper.fcntl, "ioctl", eio), self.assertRaises(OSError):
            helper.set_immutable(5, True)

    def test_protect_user_skips_mounted_and_protected(self):
        with mock.patch.object(helper, "mounts_at", lambda p: [("tmpfs", "luxos-safe-locked"), ("fuse.gocryptfs", "v")]), \
                mock.patch.object(helper, "seal_underlying") as seal:
            self.assertEqual(helper.protect_user("u", 1000, 1000), ("protected", None))
        with mock.patch.object(helper, "mounts_at", lambda p: [("fuse.gocryptfs", "v")]), \
                mock.patch.object(helper, "seal_underlying") as seal:
            self.assertEqual(helper.protect_user("u", 1000, 1000), ("busy", None))
        seal.assert_not_called()

    def test_main_rejects(self):
        for argv, env in ((["x", "guard"], {"PKEXEC_UID": "1000"}), (["x", "rm"], {}), (["x", "create"], {})):
            with mock.patch.object(helper.sys, "argv", argv), mock.patch.dict(os.environ, env, clear=False), \
                    mock.patch.object(helper.os, "geteuid", lambda: 0), self.assertRaises(SystemExit):
                if "PKEXEC_UID" not in env:
                    os.environ.pop("PKEXEC_UID", None)
                helper.main()

    def test_main_refuses_system_users(self):
        with mock.patch.object(helper.sys, "argv", ["x", "protect"]), \
                mock.patch.dict(os.environ, {"PKEXEC_UID": "0"}), \
                mock.patch.object(helper.os, "geteuid", lambda: 0), \
                mock.patch.object(helper, "protect_user") as pu, self.assertRaises(SystemExit):
            helper.main()
        pu.assert_not_called()


class Packaging(unittest.TestCase):
    def test_units(self):
        with open(os.path.join(FILES, "luxos-safe-watch.service")) as f:
            self.assertIn("ExecStop=/usr/bin/luxos-safe lock --logout", f.read())
        with open(os.path.join(FILES, "luxos-safe-guard.service")) as f:
            g = f.read()
        self.assertIn("ExecStart=/usr/lib/luxos/luxos-safe-helper guard", g)
        self.assertIn("Before=systemd-user-sessions.service", g)
        with open(os.path.join(HERE, "..", "PKGBUILD")) as f:
            pk = f.read()
        self.assertIn("luxos-safe-guard.service", pk)
        self.assertIn("install=luxos-safe.install", pk)

    def test_no_lazy_unmount_outside_logout(self):
        with open(os.path.join(FILES, "luxos-safe")) as f:
            src = f.read()
        self.assertEqual(src.count('"-uz"'), 1)

    def test_translations_present_once(self):
        keys = [k for k in subprocess.run(
            ["grep", "-ohE", r'_\("[^"]+"\)', os.path.join(FILES, "luxos-safe")],
            capture_output=True, text=True).stdout.split("\n") if k]
        keys = sorted({k[3:-2] for k in keys} | {helper.LAUNCHER_NAME, helper.LAUNCHER_COMMENT})
        for lang in helper.LANGS:
            with open(os.path.join(I18N, f"{lang}.tsv"), encoding="utf-8") as f:
                rows = [line.split("\t", 1)[0] for line in f if "\t" in line and not line.startswith("#")]
            for k in keys:
                self.assertEqual(rows.count(k), 1, f"{lang}: {k!r}")


if __name__ == "__main__":
    unittest.main()
