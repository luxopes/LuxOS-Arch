"""Skutecne pripojeni (tmpfs, gocryptfs, fusermount3) v jednorazovem uzivatelskem jmennem prostoru.

    python3 -m unittest discover -s packages/luxos-safe/tests -v

Potrebuje unshare (util-linux) s --map-users (newuidmap a radek v /etc/subuid). gocryptfs se hleda
v PATH, v LUXOS_SAFE_GOCRYPTFS (adresar s binarkou) nebo v out/pkgcache (rozbali se do docasne slozky).
Bez gocryptfs probehne jen cast s ochranou slozky.
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def subid(path, user):
    try:
        with open(path) as f:
            for line in f:
                n, start, count = line.strip().split(":")
                if n in (user, str(os.getuid())) and int(count) > 0:
                    return int(start)
    except (OSError, ValueError):
        pass
    return None


def gocryptfs_dir(tmp):
    if os.environ.get("LUXOS_SAFE_GOCRYPTFS"):
        return os.environ["LUXOS_SAFE_GOCRYPTFS"]
    if shutil.which("gocryptfs"):
        return os.path.dirname(shutil.which("gocryptfs"))
    pkgs = sorted(glob.glob(os.path.join(REPO, "out", "pkgcache", "gocryptfs-*.pkg.tar.zst")))
    if pkgs:
        d = os.path.join(tmp, "gcf")
        os.mkdir(d)
        r = subprocess.run(["tar", "--zstd", "-xf", pkgs[-1], "-C", d, "usr/bin/gocryptfs"], capture_output=True)
        if r.returncode == 0:
            return os.path.join(d, "usr", "bin")
    return "-"


class UserNamespace(unittest.TestCase):
    def test_protect_lock_unlock_flow(self):
        import pwd
        user = pwd.getpwuid(os.getuid()).pw_name
        su, sg = subid("/etc/subuid", user), subid("/etc/subgid", user)
        if not shutil.which("unshare") or su is None or sg is None:
            self.skipTest("unshare with subuid/subgid mapping not available")
        tmp = tempfile.mkdtemp(prefix="luxos-safe-ns-")
        os.chmod(tmp, 0o755)        # UID 1000 v prostoru musi projit k pracovni slozce
        try:
            gdir = gocryptfs_dir(tmp)
            work = os.path.join(tmp, "w")
            os.mkdir(work)
            uid, gid = os.getuid(), os.getgid()
            cmd = ["unshare", "-m", "--propagation", "private",
                   f"--map-users=0:{uid}:1", f"--map-users=1000:{su}:1",
                   f"--map-groups=0:{gid}:1", f"--map-groups=1000:{sg}:1",
                   "--setuid=0", "--setgid=0",
                   sys.executable, "-I", os.path.join(HERE, "userns_flow.py"), work, gdir]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            print(r.stdout, file=sys.stderr)
            if r.returncode != 0 and ("newuidmap" in r.stderr or "unshare failed" in r.stderr):
                self.skipTest(f"user namespace not available: {r.stderr.strip()[-200:]}")
            self.assertEqual(r.returncode, 0, r.stderr[-3000:])
            self.assertIn("ALL OK" if gdir != "-" else "SKIP gocryptfs flow", r.stdout)
        finally:
            subprocess.run(["chmod", "-R", "u+rwX", tmp], capture_output=True)
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
