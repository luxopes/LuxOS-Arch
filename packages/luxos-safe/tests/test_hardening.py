"""Testy zesileni Trezoru: pravidla hesla, klic pro obnovu, scrypt, volby pripojeni, kontrola ochrany.

    python3 -m unittest discover -s packages/luxos-safe/tests -v

Cast Real pouziva skutecny gocryptfs (jako bezny uzivatel, docasne trezory s nizkym scrypt,
aby test byl rychly a nebral moc pameti). Bez gocryptfs/fusermount3 se preskoci.
"""
import ctypes
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from test_luxos_safe import LOCKED, MNT, UNLOCKED, VAULT, Base, safe


class PasswordPolicy(unittest.TestCase):
    def problem(self, pw):
        return safe.password_problem(pw, user="anna")

    def test_length(self):
        self.assertEqual(self.problem("Kx9#mP2!qL"), "Use at least 12 characters.")
        self.assertIsNone(self.problem("Kx9#mP2!qL7z"))

    def test_common_words_with_digits_and_leet(self):
        for pw in ("Password2024!", "p@ssw0rd12345", "heslo12345678", "Qwertyuiop12", "passwordpassword",
                   "Trezor2026!!", "iloveyou1234", "ANNA20262026"):
            self.assertIn("too common", self.problem(pw) or "", pw)

    def test_predictable(self):
        for pw in ("aaaaaaaaaaaa", "123456789012", "abcdefghijklm", "qwertzuiopas", "aabbccddeeffgg",
                   "121212121212"):
            self.assertIn("predictable", self.problem(pw) or "", pw)

    def test_good_passwords_accepted(self):
        for pw in ("correct horse battery staple", "Modry-slon-pije-caj", "Kx9#mP2!qL7z", "žluťoučký kůň 7",
                   "slavia praha 1892 vlak"):
            self.assertIsNone(self.problem(pw), pw)

    def test_strength(self):
        s = lambda pw: safe.password_strength(pw, user="anna")  # noqa: E731
        self.assertEqual(s(""), 0)
        self.assertEqual(s("Password2024!"), 0)
        self.assertEqual(s("kocourmikes"), 0)                   # kratke
        self.assertEqual(s("kocourmikesv"), 2)                  # 12 malych pismen
        self.assertEqual(s("Kx9#mP2!qL7z"), 3)
        self.assertEqual(s("correct horse battery staple"), 4)
        self.assertLessEqual(s("abababababababababab12"), 2)    # opakovani nepridava
        for n in range(5):
            self.assertIsInstance(safe.strength_label(n), str)

    def test_unlock_never_checks_policy(self):
        """Stara kratka hesla dal odemykaji (pravidla jen pro nova hesla)."""
        args = []
        with mock.patch.object(safe, "run_helper"), mock.patch.object(safe, "trust_launcher"), \
                mock.patch.object(safe, "protected", lambda: True), \
                mock.patch.object(safe, "run_pw", lambda a, p: args.append((a, p)) or (0, "")), \
                mock.patch.object(safe, "state", lambda: "locked"), mock.patch.object(safe, "recover_plaintext", list):
            self.assertIsNone(safe.unlock("short"))
        self.assertEqual(args[0][1], ["short"])


class RecoveryKey(unittest.TestCase):
    HEX = "3aaf036d74ceeca1bf283f8da67f2fdbf8c9585e8a85111d6504b1fbc3b25d86"

    def test_format_and_normalize(self):
        dashed = safe.format_master_key(self.HEX)
        self.assertEqual(dashed, "3aaf036d-74ceeca1-bf283f8d-a67f2fdb-f8c9585e-8a85111d-6504b1fb-c3b25d86")
        self.assertEqual(safe.normalize_recovery_key(dashed), self.HEX)
        self.assertEqual(safe.normalize_recovery_key(" 3AAF036D 74CEECA1 bf283f8d a67f2fdb\n"
                                                     "f8c9585e 8a85111d 6504b1fb c3b25d86 "), self.HEX)
        self.assertIsNone(safe.normalize_recovery_key(self.HEX[:-1]))
        self.assertIsNone(safe.normalize_recovery_key(self.HEX[:-1] + "g"))

    def test_master_key_wrong_password(self):
        with mock.patch.object(safe, "run_pw_out", lambda a, p: (safe.XRAY_WRONG_PASSWORD, "Password incorrect.", "")):
            self.assertEqual(safe.master_key("x"), (None, "Wrong password."))
        with mock.patch.object(safe, "run_pw_out", lambda a, p: (0, "", self.HEX + "\n")):
            self.assertEqual(safe.master_key("x"), (safe.format_master_key(self.HEX), None))


class Scrypt(Base):
    def conf(self, n):
        path = os.path.join(self.tmp, "gocryptfs.conf")
        with open(path, "w") as f:
            json.dump({"ScryptObject": {"N": 1 << n, "R": 8, "P": 1}}, f)
        return path

    def test_vault_logn_and_upgrade(self):
        with mock.patch.object(safe, "CONF_FILE", self.conf(16)):
            self.assertEqual(safe.vault_logn(), 16)
            self.assertTrue(safe.can_upgrade())
            self.assertEqual(safe.target_logn(), safe.SCRYPT_LOGN)
        with mock.patch.object(safe, "CONF_FILE", self.conf(20)):
            self.assertFalse(safe.can_upgrade())
            self.assertEqual(safe.target_logn(), 20)        # nikdy nesnizovat
        with mock.patch.object(safe, "CONF_FILE", os.path.join(self.tmp, "missing")):
            self.assertIsNone(safe.vault_logn())
            self.assertFalse(safe.can_upgrade())

    def test_change_password_and_upgrade_use_scryptn(self):
        calls = []
        with mock.patch.object(safe, "CONF_FILE", self.conf(16)), \
                mock.patch.object(safe, "run_pw", lambda a, p: calls.append((a, p)) or (0, "")):
            self.assertIsNone(safe.change_password("old", "new"))
            self.assertIsNone(safe.upgrade_protection("same"))
        self.assertEqual(calls[0][0], ["gocryptfs", "-passwd", "-q", "-scryptn", str(safe.SCRYPT_LOGN), VAULT])
        self.assertEqual(calls[0][1], ["old", "new"])
        self.assertEqual(calls[1][1], ["same", "same"])

    def test_create_and_unlock_args(self):
        self.set_mounts(*LOCKED)
        calls = []
        with mock.patch.object(safe, "run_pw", lambda a, p: calls.append(a) or (0, "")), \
                mock.patch.object(safe.os, "listdir", lambda p: []), mock.patch.object(safe.os.path, "isdir", lambda p: True), \
                mock.patch.object(safe, "add_bookmark"), mock.patch.object(safe, "unlock", lambda p: None):
            self.assertIsNone(safe.create("Kx9#mP2!qL7z"))
        self.assertIn("-scryptn", calls[0])
        self.assertEqual(calls[0][calls[0].index("-scryptn") + 1], str(safe.SCRYPT_LOGN))
        args = []
        with mock.patch.object(safe, "trust_launcher"), mock.patch.object(safe, "state", lambda: "locked"), \
                mock.patch.object(safe, "run_pw", lambda a, p: args.append(a) or (0, "")), \
                mock.patch.object(safe, "recover_plaintext", list):
            self.assertIsNone(safe.unlock("pw"))
        for opt in ("-nosuid", "-nodev", "-noexec"):
            self.assertIn(opt, args[0])
        self.assertEqual(args[0][-3:], ["-nonempty", VAULT, MNT])


class Reset(Base):
    HEX = RecoveryKey.HEX

    def setUp(self):
        super().setUp()
        self.vault = os.path.join(self.tmp, "vault")
        os.mkdir(self.vault)
        self.conf = os.path.join(self.vault, "gocryptfs.conf")
        with open(self.conf, "w") as f:
            json.dump({"ScryptObject": {"N": 1 << 16}}, f)
        self.set_mounts(*LOCKED)
        for name, val in (("VAULT", self.vault), ("CONF_FILE", self.conf)):
            p = mock.patch.object(safe, name, val)
            p.start()
            self.addCleanup(p.stop)

    def test_rejects_invalid_and_unlocked(self):
        self.assertIn("not a valid recovery key", safe.reset_password("1234", "new"))
        self.set_mounts(*UNLOCKED)
        self.assertEqual(safe.reset_password(self.HEX, "new"), "Lock the Safe first.")

    def test_wrong_key_never_rewrites(self):
        with mock.patch.object(safe, "verify_master_key", lambda k: False), mock.patch.object(safe, "run_pw") as pw:
            self.assertEqual(safe.reset_password(self.HEX, "new"), "This recovery key does not open this Safe.")
        pw.assert_not_called()

    def test_success_removes_old_wrapping(self):
        with open(self.conf + ".bak", "w") as f:
            f.write("stale")
        calls = []

        def fake(a, p):
            calls.append((a, p))
            self.assertFalse(os.path.exists(self.conf + ".bak"))   # stary .bak uklizeny pred behem
            with open(self.conf + ".bak", "w") as f:               # gocryptfs uklada stary conf
                f.write("old wrapping")
            return 0, ""
        with mock.patch.object(safe, "verify_master_key", lambda k: True), mock.patch.object(safe, "run_pw", fake):
            self.assertIsNone(safe.reset_password(safe.format_master_key(self.HEX).upper(), "new password"))
        self.assertIn("-masterkey=stdin", calls[0][0])
        self.assertEqual(calls[0][1], [safe.format_master_key(self.HEX), "new password"])
        self.assertEqual([n for n in os.listdir(self.vault) if n.startswith("gocryptfs.conf.")], [])

    def test_failure_restores_backup(self):
        with open(self.conf + ".bak", "w") as f:
            f.write("stale")
        with mock.patch.object(safe, "verify_master_key", lambda k: True), \
                mock.patch.object(safe, "run_pw", lambda a, p: (7, "boom")):
            self.assertIn("boom", safe.reset_password(self.HEX, "new"))
        with open(self.conf + ".bak") as f:
            self.assertEqual(f.read(), "stale")

    def test_verify_empty_vault(self):
        self.assertTrue(safe.verify_master_key(self.HEX))


class CheckReport(Base):
    def sysfs(self):
        root = os.path.join(self.tmp, "sys")
        for name, uuid, slaves in (("dm-0", "CRYPT-LUKS2-abc-cryptroot", ["nvme0n1p2"]),
                                   ("dm-1", "LVM-xyz", ["dm-0"]), ("dm-2", "LVM-plain", ["sda3"]),
                                   ("nvme0n1p2", None, []), ("sda3", None, []), ("zram0", None, [])):
            d = os.path.join(root, "class", "block", name)
            os.makedirs(os.path.join(d, "slaves"))
            for s in slaves:
                open(os.path.join(d, "slaves", s), "w").close()
            if uuid:
                os.makedirs(os.path.join(d, "dm"))
                with open(os.path.join(d, "dm", "uuid"), "w") as f:
                    f.write(uuid + "\n")
        return root

    def test_swap_report(self):
        sysfs = self.sysfs()
        swaps = os.path.join(self.tmp, "swaps")
        devs = os.path.join(self.tmp, "dev")
        os.mkdir(devs)
        for name in ("zram0", "dm-1", "dm-2", "sda3"):
            open(os.path.join(devs, name), "w").close()
        with open(swaps, "w") as f:
            f.write("Filename\tType\tSize\tUsed\tPriority\n")
            for name in ("zram0", "dm-1", "dm-2", "sda3"):
                f.write(f"{devs}/{name}  partition\t100\t0\t-2\n")
        rep = dict((os.path.basename(d), e) for d, e in safe.swap_report(swaps, sysfs))
        self.assertEqual(rep, {"zram0": True, "dm-1": True, "dm-2": False, "sda3": False})

    def test_check_locked_and_unlocked(self):
        conf = os.path.join(self.tmp, "gocryptfs.conf")
        with open(conf, "w") as f:
            json.dump({"ScryptObject": {"N": 1 << 16}}, f)
        with mock.patch.object(safe, "CONF_FILE", conf), mock.patch.object(safe, "state", lambda: "locked"), \
                mock.patch.object(safe, "swap_report", lambda: [("/dev/zram0", True)]), \
                mock.patch.object(safe, "_read", lambda p, d="": "2"):
            res = safe.check()
        self.assertFalse(res[0][0])                       # scrypt 2^16 < 2^18
        self.assertTrue(all(ok for ok, _t in res[1:]))
        lines = [f"100 22 0:50 / {MNT} rw,nosuid,nodev,noexec,relatime - fuse.gocryptfs {VAULT} rw\n"]
        with open(self.mi, "w") as f:
            f.writelines(lines)
        self.assertEqual(safe.mount_options() >= {"nosuid", "nodev", "noexec"}, True)
        with mock.patch.object(safe, "CONF_FILE", conf), mock.patch.object(safe, "state", lambda: "unlocked"), \
                mock.patch.object(safe, "swap_report", lambda: [("/dev/sda3", False)]), \
                mock.patch.object(safe, "_gocryptfs_pids", lambda: [1]), mock.patch.object(safe, "core_limit", lambda p: "0"), \
                mock.patch.object(safe, "_read", lambda p, d="": "1"):
            res = dict((t, ok) for ok, t in safe.check())
        self.assertTrue(res["Mounted with nosuid, nodev and noexec."])
        self.assertTrue(res["Core dumps of the Safe process are disabled."])
        self.assertFalse([ok for t, ok in res.items() if "ptrace_scope 1" in t][0])
        self.assertFalse([ok for t, ok in res.items() if "/dev/sda3" in t][0])

    def test_cli_check_exit_code(self):
        with mock.patch.object(safe, "check", lambda: [(True, "a"), (False, "b")]), \
                mock.patch.object(safe.sys, "argv", ["luxos-safe", "check"]), mock.patch("builtins.print"):
            self.assertEqual(safe.main(), 1)

    def test_no_core_dumps_inherited(self):
        rc, _err, out = safe.run_pw_out(["sh", "-c", "ulimit -c; read x; echo $x"], ["secret"])
        self.assertEqual((rc, out.split()), (0, ["0", "secret"]))


class GnuPG(Base):
    def test_homes_and_agent_stopped_before_unmount(self):
        mnt = os.path.join(self.tmp, "mnt")
        for d in ("gnupg/private-keys-v1.d", "luxos-signing/private-keys-v1.d", "keys/old/x/y", "android"):
            os.makedirs(os.path.join(mnt, d))
        open(os.path.join(mnt, "keys", "old", "pubring.kbx"), "w").close()
        open(os.path.join(mnt, "gnupg", "pubring.kbx"), "w").close()
        with mock.patch.object(safe, "MOUNT", mnt):
            homes = safe.gnupg_homes()
        self.assertEqual(homes, [os.path.join(mnt, "gnupg"), os.path.join(mnt, "keys", "old"),
                                 os.path.join(mnt, "luxos-signing")])
        order = []
        self.set_mounts(*UNLOCKED)
        with mock.patch.object(safe, "gnupg_homes", lambda: ["/safe/tester/gnupg"]), \
                mock.patch.object(safe.subprocess, "run",
                                  lambda a, **kw: order.append(a) or subprocess.CompletedProcess(a, 0, "", "")), \
                mock.patch.object(safe, "trust_launcher"):
            safe.lock()
        self.assertEqual(order[0], ["gpgconf", "--homedir", "/safe/tester/gnupg", "--kill", "gpg-agent"])
        self.assertEqual(order[1][:2], ["fusermount3", "-u"])


def _have_gocryptfs():
    return all(shutil.which(c) for c in ("gocryptfs", "gocryptfs-xray", "fusermount3")) and os.path.exists("/dev/fuse")


@unittest.skipUnless(_have_gocryptfs(), "gocryptfs, gocryptfs-xray or FUSE not available")
class Real(unittest.TestCase):
    """Skutecny gocryptfs v docasne slozce (bez /safe, bez rootu)."""
    PW = "Modry-slon-pije-caj"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-safe-real-")
        self.vault = os.path.join(self.tmp, "vault")
        self.mnt = os.path.join(self.tmp, "mnt")
        os.mkdir(self.vault, 0o700)
        os.mkdir(self.mnt, 0o700)
        self.patches = [mock.patch.object(safe, k, v) for k, v in (
            ("VAULT", self.vault), ("MOUNT", self.mnt), ("CONF_FILE", os.path.join(self.vault, "gocryptfs.conf")),
            ("SCRYPT_LOGN", 12), ("MOUNTINFO", "/proc/self/mountinfo"))]
        for p in self.patches:
            p.start()
        rc, err = safe.run_pw(["gocryptfs", "-init", "-q", "-scryptn", "10", "-passfile", "/dev/stdin", self.vault],
                              [self.PW])
        self.assertEqual(rc, 0, err)

    def tearDown(self):
        subprocess.run(["fusermount3", "-u", self.mnt], capture_output=True)
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mount(self, pw):
        return safe.run_pw(["gocryptfs", "-q", "-passfile", "/dev/stdin", "-nosyslog"] + safe.MOUNT_OPTS
                           + [self.vault, self.mnt], [pw])[0]

    def test_full_flow(self):
        # Zesileni ochrany se stejnym heslem
        self.assertEqual(safe.vault_logn(), 10)
        self.assertTrue(safe.can_upgrade())
        self.assertIsNone(safe.upgrade_protection(self.PW))
        self.assertEqual(safe.vault_logn(), 12)
        self.assertEqual(safe.upgrade_protection("wrong password!"), "Wrong password.")

        # Obsah, volby pripojeni, core dumpy, ptrace
        self.assertEqual(self.mount(self.PW), 0)
        with open(os.path.join(self.mnt, "release.jks"), "w") as f:
            f.write("keystore")
        opts = safe.mount_options()
        self.assertTrue({"nosuid", "nodev", "noexec"} <= opts, opts)
        pids = safe._gocryptfs_pids()
        self.assertEqual(len(pids), 1)
        self.assertEqual(safe.core_limit(pids[0]), "0")
        with open("/proc/sys/kernel/yama/ptrace_scope") as f:
            scope = int(f.read())
        if scope >= 2:
            libc = ctypes.CDLL(None, use_errno=True)
            self.assertEqual(libc.ptrace(16, pids[0], None, None), -1)   # PTRACE_ATTACH
            with self.assertRaises(PermissionError):
                open(f"/proc/{pids[0]}/mem", "rb")
        subprocess.run(["fusermount3", "-u", self.mnt], check=True)

        # Klic pro obnovu: spravny i spatny, obnova zapomenuteho hesla
        key, err = safe.master_key(self.PW)
        self.assertIsNone(err)
        self.assertEqual(safe.master_key("nope nope nope"), (None, "Wrong password."))
        self.assertTrue(safe.verify_master_key(safe.normalize_recovery_key(key)))
        self.assertFalse(safe.verify_master_key("1" * 64))
        self.assertEqual(safe.reset_password("1" * 64, "Novy-heslo-pro-trezor"), "This recovery key does not open this Safe.")
        self.assertIsNone(safe.reset_password(key, "Novy-heslo-pro-trezor"))
        self.assertEqual([n for n in os.listdir(self.vault) if n.startswith("gocryptfs.conf.")], [])
        self.assertEqual(self.mount(self.PW), safe.WRONG_PASSWORD)
        self.assertEqual(self.mount("Novy-heslo-pro-trezor"), 0)
        with open(os.path.join(self.mnt, "release.jks")) as f:
            self.assertEqual(f.read(), "keystore")
        subprocess.run(["fusermount3", "-u", self.mnt], check=True)
        # Druha obnova (gocryptfs by s existujicim .bak selhal)
        self.assertIsNone(safe.reset_password(key, "Treti-heslo-pro-trezor"))
        self.assertEqual(self.mount("Treti-heslo-pro-trezor"), 0)


if __name__ == "__main__":
    unittest.main()
