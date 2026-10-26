"""Snimky na skutecnem btrfs: obraz v souboru v docasnem adresari, pripojeny pres loop (sudo -n).
Nikdy nesaha na skutecne disky ani na /boot - koren (LUXOS_CARE_ROOT) i nejvyssi uroven btrfs
(LUXOS_SNAPSHOT_TOP) jsou v docasnem adresari. Bez sudo -n nebo btrfs-progs se preskoci.

    python3 -m unittest packages/luxos-care/tests/test_snapshots_btrfs.py -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")


def can_sudo():
    if not shutil.which("mkfs.btrfs") or not shutil.which("sudo"):
        return False
    return subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0


def sudo(*cmd, check=True):
    r = subprocess.run(["sudo", "-n"] + list(cmd), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{cmd}: {r.stderr}")
    return r


# ---- cast, ktera bezi jako root (sudo -n python3 tento_soubor --as-root ...) --------------------
def as_root(root, top):
    sys.path.insert(0, FILES)
    sys.path.insert(0, os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
    import datetime
    import luxos_care as care
    import luxos_snapshots as snap
    care.ROOT = root
    os.environ["LUXOS_SNAPSHOT_TOP"] = top
    snap.initramfs_has_overlay = lambda img: True
    care.history = lambda *a, **k: None
    care.engine_running = lambda: False
    out = {}

    def prop_ro(path):
        r = subprocess.run(["btrfs", "property", "get", "-ts", path, "ro"], capture_output=True, text=True)
        return r.stdout.strip()

    def at(m):
        return datetime.datetime(2026, 10, 26, 14, m, 0)
    sysdir = os.path.join(top, "@")
    with open(os.path.join(sysdir, "etc/hostname"), "w") as f:
        f.write("before\n")
    a = snap.create(top, "update", ["firefox"], now=at(1))
    out["a"] = a
    out["a_ro"] = prop_ro(os.path.join(top, "@snapshots", a["name"]))
    out["a_subvol"] = snap.BTRFS.is_subvolume(os.path.join(top, "@snapshots", a["name"]))
    with open(os.path.join(sysdir, "etc/hostname"), "w") as f:
        f.write("after\n")
    # zapis do snimku jen pro cteni musi selhat
    try:
        open(os.path.join(top, "@snapshots", a["name"], "etc/hostname"), "w").close()
        out["write_ro"] = "allowed"
    except OSError as e:
        out["write_ro"] = e.strerror
    for m in range(2, 9):
        snap.create(top, now=at(m))
    out["free_ok"] = snap.free_ok(top)          # obraz 300 MB = malo mista
    out["pruned"] = snap.prune(top, keep=5)
    out["left"] = [s["name"] for s in snap.list_snapshots(top)]
    snap.create(top, now=at(9))
    res = snap.rollback(top, out["left"][0], now=at(30))
    out["rollback"] = res
    with open(os.path.join(sysdir, "etc/hostname")) as f:
        out["host_after_rollback"] = f.read()
    out["new_root_ro"] = prop_ro(sysdir)
    out["new_root_subvol"] = snap.BTRFS.is_subvolume(sysdir)
    with open(os.path.join(top, "@snapshots", res["replaced"], "etc/hostname")) as f:
        out["host_replaced"] = f.read()
    r = subprocess.run(["btrfs", "subvolume", "list", "-o", os.path.join(top, "@snapshots")],
                       capture_output=True, text=True)
    out["subvols"] = sorted(line.split()[-1] for line in r.stdout.splitlines())
    print(json.dumps(out))


@unittest.skipUnless(can_sudo(), "needs sudo -n and btrfs-progs")
class RealBtrfs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-btrfs-test-")
        self.img = os.path.join(self.tmp, "disk.img")
        self.top = os.path.join(self.tmp, "top")
        self.root = os.path.join(self.tmp, "root")
        os.makedirs(self.top)
        with open(self.img, "wb") as f:
            f.truncate(300 * 1024 * 1024)
        subprocess.run(["mkfs.btrfs", "-q", "-f", self.img], check=True, capture_output=True)
        self.addCleanup(self.cleanup)
        sudo("mount", "-o", "loop", self.img, self.top)
        self.mounted = True
        sudo("btrfs", "subvolume", "create", os.path.join(self.top, "@"))
        sudo("mkdir", "-p", os.path.join(self.top, "@", "etc"))
        # falesny koren: /boot (systemd-boot), moduly jadra, mountinfo
        for path, data in (("/boot/vmlinuz-linux-luxos", b"K1"), ("/boot/initramfs-linux-luxos.img", b"I1"),
                           ("/usr/lib/modules/6.17.1-luxos/vmlinuz", b"K1"),
                           ("/usr/lib/modules/6.17.1-luxos/pkgbase", b"linux-luxos\n"),
                           ("/etc/luxos/care.conf", b"KERNEL=linux-luxos\n"),
                           ("/proc/cmdline", b"root=UUID=x rootflags=subvol=@ rw quiet splash\n"),
                           ("/boot/loader/loader.conf", b"default luxos.conf\ntimeout 0\n"),
                           ("/boot/loader/entries/luxos.conf", b"title LuxOS\nlinux /vmlinuz-linux-luxos\n"
                            b"initrd /initramfs-linux-luxos.img\noptions root=UUID=x rootflags=subvol=@ rw\n"),
                           ("/proc/self/mountinfo", b"25 1 0:30 /@ / rw - btrfs /dev/loop9 rw,subvol=/@\n"
                            b"40 25 259:1 / /boot rw - vfat /dev/vda1 rw\n")):
            p = self.root + path
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)

    def cleanup(self):
        if getattr(self, "mounted", False):
            sudo("umount", self.top, check=False)
        sudo("rm", "-rf", self.tmp, check=False)

    def test_snapshot_prune_rollback(self):
        r = sudo(sys.executable, "-I", os.path.abspath(__file__), "--as-root", self.root, self.top, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(out["a_subvol"])
        self.assertFalse(out["free_ok"])
        self.assertEqual(out["a_ro"], "ro=true")
        self.assertEqual(out["write_ro"], "Read-only file system")
        self.assertEqual(len(out["left"]), 5)
        self.assertEqual(len(out["pruned"]), 3)
        self.assertNotIn(out["a"]["name"], out["left"])
        self.assertEqual(out["host_after_rollback"], "after\n")       # stav snimku 14:04
        self.assertEqual(out["new_root_ro"], "ro=false")
        self.assertTrue(out["new_root_subvol"])
        self.assertEqual(out["host_replaced"], "after\n")
        self.assertEqual(out["rollback"]["replaced"], "2026-10-26_14-30-00")
        self.assertIn("@snapshots/2026-10-26_14-30-00", out["subvols"])
        # sada jadra na falesnem /boot
        self.assertEqual(len(os.listdir(self.root + "/boot/luxos-snapshots")), 1)
        ents = os.listdir(self.root + "/boot/loader/entries")
        self.assertIn("snapshot-luxos-2026-10-26_14-30-00.conf", ents)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--as-root":
        as_root(sys.argv[2], sys.argv[3])
    else:
        unittest.main()
