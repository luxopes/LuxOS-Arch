"""LuxOS Care - obnova systemu (polozka "LuxOS Recovery" v nabidce zavadece, luxos-recovery).

  kontrola disku      btrfs device stats, btrfs scrub (jen cteni), btrfs check --readonly,
                      fsck EFI/boot oddilu jen pro cteni; oprava jen s potvrzenim (scrub opravi
                      z druhe kopie, fsck.fat -a / e2fsck -p na odpojenem oddilu; nikdy check --repair)
  navrat ke snimku    luxos_snapshots.rollback
  preinstalace        novy systemovy subvolume z repozitaru se stejnymi baliky (jen z repozitaru),
                      prenesou se ucty, nastaveni systemu (jazyk, klavesnice, sit, disk, zavadec)
                      a zapnute sluzby; @home se nemeni. Puvodni system zustane jako snimek
                      "pred preinstalaci" - prepnuti nastane az kdyz je novy system hotovy.
"""
import json
import os
import shutil
import stat

import luxos_care as care
import luxos_snapshots as snap
from luxos_care import P

NEW_SUBVOL = "@luxos-reinstall"
# Nastaveni systemu prenesena do noveho systemu (cesty od korene, soubory i slozky)
CARRY = [
    "etc/hostname", "etc/hosts", "etc/locale.conf", "etc/locale.gen", "etc/vconsole.conf", "etc/localtime",
    "etc/X11/xorg.conf.d/00-keyboard.conf", "etc/machine-id",
    "etc/fstab", "etc/crypttab", "etc/crypttab.initramfs", "etc/cryptsetup-keys.d",
    "etc/mkinitcpio.conf.d", "etc/mkinitcpio.d", "etc/default/grub",
    "etc/lux/lux.conf", "etc/lux/conf.d", "etc/lux/mirrorlist", "etc/lux/hooks",
    "etc/luxos", "etc/sudoers.d/10-luxos", "etc/lightdm/lightdm.conf.d/60-autologin.conf",
    "etc/NetworkManager/system-connections", "var/lib/bluetooth",
    "usr/local/sbin/luxos-esp-sync", "etc/initcpio/post/luxos-esp-sync",
]
ACCOUNT_FILES = ("etc/passwd", "etc/group", "etc/shadow", "etc/gshadow")
UID_MIN, UID_MAX = 1000, 60000
ESSENTIAL = ("base", "lux-engine", "lux", "luxos-care")


# ---- kontrola disku ------------------------------------------------------------------------
def boot_mounts():
    """[(bod, typ, zarizeni)] oddilu zavadece (/boot, /efi), ktere nejsou btrfs."""
    out = []
    for mp in ("/boot", "/efi", "/boot/efi"):
        for m in snap.mounts():
            if m[0] == mp and m[1] in ("vfat", "ext4", "ext2", "ext3"):
                out.append((mp, m[1], m[2]))
    return out


def fsck_cmd(fstype, dev, repair):
    if fstype == "vfat":
        return ["fsck.fat", "-a", "-w", dev] if repair else ["fsck.fat", "-n", dev]
    return ["e2fsck", "-p" if repair else "-n", "-f", dev]


def disk_check(top, repair=False, out=print):
    """Kontrola (repair=False: nic se nezapisuje). -> [(krok, ok, vystup)]."""
    results = []
    dev = snap.root_device()

    def step(title, cmd, ok_codes=(0,), timeout=4 * 3600):
        out(title)
        rc, o = snap.sh(cmd, timeout=timeout)
        ok = rc in ok_codes
        results.append((title, ok, o.strip()[-4000:]))
        return ok

    step("btrfs device stats", ["btrfs", "device", "stats", "-c", top])
    step("btrfs scrub", ["btrfs", "scrub", "start", "-B", "-d"] + ([] if repair else ["-r"]) + [top])
    if dev:
        # Na pripojenem souboroveho systemu jen pro cteni (--force); opravu (--repair) LuxOS nedela nikdy
        step("btrfs check --readonly", ["btrfs", "check", "--readonly", "--force", dev])
    for mp, fstype, bdev in boot_mounts():
        if not repair:
            step(f"fsck {mp}", fsck_cmd(fstype, bdev, False), ok_codes=(0,))
            continue
        rc, o = snap.sh(["umount", mp], timeout=120)
        if rc != 0:
            results.append((f"fsck {mp}", False, o.strip()))
            continue
        try:
            # fsck.fat -a: 0 = v poradku, 1 = opraveno; e2fsck -p: 0/1 = v poradku/opraveno
            step(f"fsck {mp}", fsck_cmd(fstype, bdev, True), ok_codes=(0, 1))
        finally:
            snap.sh(["mount", mp], timeout=120)
    return results


# ---- ucty ----------------------------------------------------------------------------------
def _rows(text):
    return [ln.split(":") for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


def _join(rows):
    return "".join(":".join(r) + "\n" for r in rows)


def human_users(passwd_text):
    """Jmena lidskych uctu (UID 1000-60000)."""
    out = []
    for r in _rows(passwd_text):
        if len(r) >= 7 and r[2].isdigit() and UID_MIN <= int(r[2]) < UID_MAX:
            out.append(r[0])
    return out


def merge_accounts(old, new):
    """Ucty z puvodniho systemu do noveho: systemove ucty a skupiny zustanou z noveho systemu
    (UID/GID souhlasi se soubory baliku), lidske ucty, jejich skupiny (GID 1000-60000), hesla
    a clenstvi ve skupinach se prevezmou z puvodniho. old/new: {soubor: text} -> {soubor: text}."""
    users = set(human_users(old.get("etc/passwd", "")))
    res = {}
    # passwd / shadow: radky lidskych uctu nahradi nebo doplni
    for f, key in (("etc/passwd", 0), ("etc/shadow", 0)):
        nrows = [r for r in _rows(new.get(f, "")) if r[key] not in users]
        orows = [r for r in _rows(old.get(f, "")) if r[key] in users]
        res[f] = _join(nrows + orows)
    # group / gshadow: skupiny uzivatelu (GID >= 1000) z puvodniho, clenstvi lidskych uctu doplnit
    old_g = {r[0]: r for r in _rows(old.get("etc/group", ""))}
    user_groups = {n for n, r in old_g.items() if len(r) >= 3 and r[2].isdigit() and UID_MIN <= int(r[2]) < UID_MAX}
    for f, mcol in (("etc/group", 3), ("etc/gshadow", 3)):
        orows = {r[0]: r for r in _rows(old.get(f, ""))}
        out = []
        for r in _rows(new.get(f, "")):
            if r[0] in user_groups:
                continue
            while len(r) <= mcol:
                r.append("")
            o = orows.get(r[0])
            if o and len(o) > mcol:
                members = [m for m in r[mcol].split(",") if m]
                for m in o[mcol].split(","):
                    if m in users and m not in members:
                        members.append(m)
                r[mcol] = ",".join(members)
            out.append(r)
        out += [orows[g] for g in sorted(user_groups) if g in orows]
        res[f] = _join(out)
    return res


# ---- preinstalace --------------------------------------------------------------------------
class Mounts:
    """Pripojeni do noveho systemu (proc, sys, dev, run, /boot...) a jejich uklid."""

    def __init__(self):
        self.done = []

    def mount(self, cmd, target):
        os.makedirs(target, exist_ok=True)
        rc, o = snap.sh(cmd + [target], timeout=120)
        if rc != 0:
            raise snap.SnapshotError("mount_failed", f"{target}: {o.strip()[-300:]}")
        self.done.append(target)

    def umount_all(self):
        for t in reversed(self.done):
            rc, _o = snap.sh(["umount", "-R", t], timeout=120)
            if rc != 0:
                snap.sh(["umount", "-R", "-l", t], timeout=60)
        self.done = []


def explicit_packages(old):
    """Vyslovne nainstalovane baliky puvodniho systemu -> (z repozitaru, ostatni)."""
    db = os.path.join(old, "var/lib/lux")
    rc, out = snap.sh([care.ENGINE, "--root", old, "--dbpath", db, "-Qqen"], timeout=300)
    native = [x.strip() for x in out.splitlines() if x.strip()] if rc == 0 else []
    rc2, out2 = snap.sh([care.ENGINE, "--root", old, "--dbpath", db, "-Qqem"], timeout=300)
    foreign = [x.strip() for x in out2.splitlines() if x.strip()] if rc2 == 0 else []
    return native, foreign


def copy_path(src_root, dst_root, rel):
    src = os.path.join(src_root, rel)
    dst = os.path.join(dst_root, rel)
    if not os.path.lexists(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    st = os.lstat(src)
    if stat.S_ISDIR(st.st_mode):
        shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
        shutil.copystat(src, dst)
    else:
        if os.path.lexists(dst) or os.path.islink(dst):
            os.unlink(dst)
        shutil.copy2(src, dst, follow_symlinks=False)
    try:
        os.lchown(dst, st.st_uid, st.st_gid)
    except OSError:
        pass
    return True


def carry_config(old, new):
    copied = [rel for rel in CARRY if copy_path(old, new, rel)]
    texts_old, texts_new = {}, {}
    for f in ACCOUNT_FILES:
        for root, d in ((old, texts_old), (new, texts_new)):
            try:
                with open(os.path.join(root, f)) as fh:
                    d[f] = fh.read()
            except OSError:
                d[f] = ""
    merged = merge_accounts(texts_old, texts_new)
    for f, text in merged.items():
        mode = 0o600 if f.endswith("shadow") else 0o644
        care.atomic_write(os.path.join(new, f), text, mode)
    return copied


def carry_services(old, new):
    """Zapnute sluzby puvodniho systemu (odkazy v *.wants, vychozi cil), jen jednotky, ktere
    novy system ma."""
    base = os.path.join(old, "etc/systemd/system")
    made = []
    for d, _dirs, files in os.walk(base):
        rel_dir = os.path.relpath(d, base)
        for f in files + _dirs:
            p = os.path.join(d, f)
            if not os.path.islink(p):
                continue
            if not (rel_dir.endswith((".wants", ".requires")) or (rel_dir == "." and f == "default.target")):
                continue
            target = os.readlink(p)
            unit = os.path.basename(target)
            tpl = unit.split("@")[0] + "@." + unit.rsplit(".", 1)[-1] if "@" in unit else unit
            if not any(os.path.exists(os.path.join(new, x, u)) for x in ("usr/lib/systemd/system", "etc/systemd/system")
                       for u in (unit, tpl)):
                continue
            dst = os.path.join(new, "etc/systemd/system", rel_dir, f)
            if os.path.lexists(dst):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.symlink(target, dst)
            made.append(os.path.join(rel_dir, f))
    return made


def reinstall(top, out=print, now=None, lay=None):
    """Preinstalace systemoveho subvolumu (viz popis modulu). -> dict vysledku."""
    lay = lay or care.detect_layout()
    snaps = snap.list_snapshots(top)
    system = snap.system_subvol(top, snaps)
    old = os.path.join(top, system)
    new = os.path.join(top, NEW_SUBVOL)
    if not snap.BTRFS.is_subvolume(old):
        raise snap.SnapshotError("no_subvolume", system)
    if snap.db_busy():
        raise snap.SnapshotError("busy")
    native, foreign = explicit_packages(old)
    if not native:
        raise snap.SnapshotError("no_packages")
    for p in ESSENTIAL + (lay.get("kernel") or care.config()["KERNEL"],):
        if p not in native:
            native.append(p)
    # Jadro puvodniho systemu: instalace prepise /boot; pri neuspechu se musi vratit
    files = snap.main_boot_files(lay)
    old_kid, old_ver, old_overlay = snap.save_kernel(lay, top, lay["kernel"]) if lay["kind"] != "none" else (None, "", False)
    old_kernel = snap.kset_path(lay, top, old_kid)
    if files and not old_kernel:
        raise snap.SnapshotError("kernel_not_saved")
    if os.path.lexists(new):
        out("removing an unfinished reinstall")
        snap.BTRFS.delete(new)
    mounts = Mounts()
    swapped = False
    try:
        snap.BTRFS.create(new)
        for d in ("var/lib/lux", "var/cache/lux/pkg", "var/log", "home", "boot", "proc", "sys", "dev", "run", "tmp"):
            os.makedirs(os.path.join(new, d), exist_ok=True)
        mounts.mount(["mount", "-t", "proc", "proc"], os.path.join(new, "proc"))
        mounts.mount(["mount", "--rbind", P("/sys")], os.path.join(new, "sys"))
        mounts.mount(["mount", "--rbind", P("/dev")], os.path.join(new, "dev"))
        mounts.mount(["mount", "-t", "tmpfs", "-o", "mode=0755", "run"], os.path.join(new, "run"))
        for mp in ("/boot", "/efi", "/var/cache", "/var/log"):
            if snap.is_mountpoint(mp):
                mounts.mount(["mount", "--bind", P(mp)], os.path.join(new, mp.lstrip("/")))
        out("installing %d packages" % len(native))
        rc, o = snap.sh([care.ENGINE, "--root", new, "--dbpath", os.path.join(new, "var/lib/lux"),
                         "--cachedir", os.path.join(new, "var/cache/lux/pkg"), "--noconfirm", "--needed",
                         "-Sy", "--"] + native, timeout=6 * 3600)
        if rc != 0:
            raise snap.SnapshotError("install_failed", o.strip()[-1500:])
        out("copying accounts and settings")
        carry_config(old, new)
        carry_services(old, new)
        rc, o = snap.sh(["chroot", new, "systemctl", "set-default", "graphical.target"], timeout=120)
        out("creating the initramfs")
        rc, o = snap.sh(["chroot", new, "mkinitcpio", "-P"], timeout=1800)
        if rc != 0:
            raise snap.SnapshotError("initramfs_failed", o.strip()[-1500:])
        if os.path.exists(os.path.join(new, "usr/local/sbin/luxos-esp-sync")):
            snap.sh(["chroot", new, "/usr/local/sbin/luxos-esp-sync"], timeout=300)
        if lay["kind"] == "grub":
            rc, o = snap.sh(["chroot", new, "grub-mkconfig", "-o", "/boot/grub/grub.cfg"], timeout=600)
            if rc != 0:
                raise snap.SnapshotError("bootloader_failed", o.strip()[-1500:])
        mounts.umount_all()
        # Prepnuti: puvodni system jako snimek, novy na jeho misto
        snap.ensure_snap_dir(top)
        kept = snap.new_name(top, now)
        os.rename(old, os.path.join(snap.snap_dir(top), kept))
        os.rename(new, old)
        swapped = True
        snap.write_meta(top, {"name": kept, "time": care.now(), "kind": "before-reinstall", "source": system,
                              "kver": old_ver, "kset": old_kid, "overlay": old_overlay,
                              "recovery": os.path.exists(os.path.join(top, snap.SNAP_SUBVOL, kept,
                                                                      snap.RECOVERY_BIN.lstrip("/"))),
                              "packages": [], "count": 0, "version": ""})
    except BaseException:
        mounts.umount_all()
        if not swapped:
            if os.path.lexists(new):
                try:
                    snap.BTRFS.delete(new)
                except snap.SnapshotError:
                    shutil.rmtree(new, ignore_errors=True)
            if old_kernel and files:
                snap.copy_boot(files, os.path.join(old_kernel, "vmlinuz"), os.path.join(old_kernel, "initramfs.img"))
        raise
    snap.reset_counter(lay)
    snaps = snap.list_snapshots(top)
    snap.gc_kernels(lay, top, snaps)
    snap.sync_boot(top, lay, snaps)
    care.history("reinstall", ok=True, kept=kept, packages=len(native), foreign=foreign)
    return {"kept": kept, "packages": native, "foreign": foreign}


def results_json(results):
    return json.dumps([{"step": t, "ok": ok, "output": o} for t, ok, o in results], ensure_ascii=False)
