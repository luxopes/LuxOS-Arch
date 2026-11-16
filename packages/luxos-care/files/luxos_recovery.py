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
import re
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
    # klicenka lux (mistni klic + duvera klicum repozitaru): bez ni novy system neaktualizoval ("unable
    # to update database" - overeno ve VM); subuid/subgid = rozsahy ID lidskych uctu (kontejnery)
    "etc/lux/keyring", "etc/subuid", "etc/subgid",
    "usr/local/sbin/luxos-esp-sync", "etc/initcpio/post/luxos-esp-sync",
]
ACCOUNT_FILES = ("etc/passwd", "etc/group", "etc/shadow", "etc/gshadow")
# Data aplikaci mimo /home, ktera se prenesou cela (kopie s reflink na stejnem btrfs = bez mista navic):
# aplikace z Flathubu pro vsechny uzivatele (lux, Obchod: flatpak --system)
CARRY_DATA = ["var/lib/flatpak"]
# Soubory v /etc, ktere nepatri zadnemu baliku, ale vytvari je system sam (v seznamu ztrat nemaji co delat)
GENERATED = ("etc/ssl/", "etc/ca-certificates/", "etc/pacman.d/gnupg/", "etc/lux/gnupg/", "etc/ld.so.cache",
             "etc/.pwd.lock", "etc/.updated", "etc/lux/keyring/", "etc/systemd/user/", "etc/adjtime", "etc/passwd-", "etc/group-", "etc/shadow-",
             "etc/gshadow-", "etc/subuid", "etc/subgid", "etc/subuid-", "etc/subgid-", "etc/resolv.conf",
             "etc/systemd/system/", "etc/mtab", "etc/os-release", "etc/machine-info", "etc/udev/hwdb.bin",
             "etc/xml/catalog", "etc/fonts/conf.d/", "etc/pki/", "etc/ssh/ssh_host_", "etc/lux/engine",
             "etc/.luxos", "etc/mkinitcpio.d/", "etc/initcpio/", "etc/lightdm/lightdm.conf.d/",
             "etc/plymouth/", "etc/gtk-", "etc/dconf/db/",
             # upravuji instalacni skripty baliku LuxOS - nova instalace je nastavi stejne (overeno ve VM)
             "etc/default/useradd", "etc/issue", "etc/nsswitch.conf", "etc/security/faillock.conf",
             "etc/shells", "etc/skel/")
PLAN_MAX = 30
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


# Bajt stavu svazku FAT (FAT32 0x41 = 65, FAT12/16 0x25 = 37): jadro v nem drzi priznak "dirty",
# dokud je oddil pripojeny pro zapis, a zapisuje ho jen do hlavniho boot sektoru, ne do zalohy
_FAT_STATE_OFFSETS = {"37", "65"}
_FAT_HARMLESS = (
    re.compile(r"^fsck\.fat \d"),
    re.compile(r"^There are differences between boot sector and its backup\.$"),
    re.compile(r"^This is mostly harmless\. Differences: \(offset:original/backup\)$"),
    re.compile(r"^Not automatically fixing this\.$"),
    re.compile(r"^Dirty bit is set\. Fs was not properly unmounted and some data may be corrupt\.$"),
    re.compile(r"^Automatically removing dirty bit\.$"),
    re.compile(r"^Leaving filesystem unchanged\.$"),
    re.compile(r"^\S+: \d+ files, \d+/\d+ clusters$"),
)


def fat_only_dirty(output):
    """True, kdyz fsck.fat -n nasel jen priznak "dirty" (pripojeny oddil nebo tvrde vypnuti -
    pri startu ho tise smaze systemd-fsck, fstab pass 2) a zadnou skutecnou chybu."""
    dirty = False
    for ln in output.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("Dirty bit is set"):
            dirty = True
        m = re.fullmatch(r"(\d+):[0-9a-fA-F]{2}/[0-9a-fA-F]{2}", ln)
        if m:
            if m.group(1) not in _FAT_STATE_OFFSETS:
                return False
            continue
        if not any(r.match(ln) for r in _FAT_HARMLESS):
            return False
    return dirty


_FAT_DIFF_LINE = re.compile(r"^[, ]*\d+:[0-9a-fA-F]{2}/[0-9a-fA-F]{2}(?:, \d+:[0-9a-fA-F]{2}/[0-9a-fA-F]{2})*,?$")


def fat_backup_only(output):
    """True, kdyz fsck.fat -n hlasi jen rozdil hlavniho a zalozniho boot sektoru (pripadne s priznakem
    dirty) a nic jineho. fsck.fat -a takovy rozdil neopravi ("Not automatically fixing this")."""
    found = False
    for ln in output.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("There are differences between boot sector and its backup"):
            found = True
            continue
        if _FAT_DIFF_LINE.match(ln) or any(r.match(ln) for r in _FAT_HARMLESS):
            continue
        return False
    return found


def fat_copy_backup(dev):
    """Hlavni boot sektor FAT32 do zalozniho (BPB_BkBootSec) - totez, co nabizi interaktivni fsck.fat
    ("Copy original to backup"). Jen na odpojenem oddilu. -> True = zapsano."""
    import struct
    fd = os.open(dev, os.O_RDWR)
    try:
        boot = os.pread(fd, 512, 0)
        if len(boot) != 512 or boot[510:512] != b"\x55\xaa":
            return False
        bps = struct.unpack_from("<H", boot, 11)[0]
        fat16_size = struct.unpack_from("<H", boot, 22)[0]
        bk = struct.unpack_from("<H", boot, 50)[0]
        if fat16_size != 0 or bps not in (512, 1024, 2048, 4096) or not 1 <= bk <= 32:
            return False                         # zalozni sektor ma jen FAT32
        sector = os.pread(fd, bps, 0)
        if os.pwrite(fd, sector, bk * bps) != bps:
            return False
        os.fsync(fd)
        return True
    finally:
        os.close(fd)


def repair_boot_partition(fstype, dev):
    """Oprava odpojeneho EFI/boot oddilu a kontrola po ni. -> (ok, vystup). ok podle kontroly
    PO oprave (fsck.fat -a vraci uspech i kdyz rozdil boot sektoru nechal byt)."""
    rc, o = snap.sh(fsck_cmd(fstype, dev, True), timeout=3600)
    log = o
    rc2, o2 = snap.sh(fsck_cmd(fstype, dev, False), timeout=3600)
    # fsck.fat -n vraci 0 i pri rozdilu boot sektoru a zalohy ("mostly harmless") - kontrola na
    # pripojenem oddilu ho ale hlasi (overeno ve VM: oprava hlasila uspech a rozdil zustal)
    if fstype == "vfat" and "differences between boot sector and its backup" in o2 and fat_backup_only(o2):
        try:
            copied = fat_copy_backup(dev)
        except OSError as e:
            copied = False
            log += f"\ncopying the boot sector to its backup failed: {e}"
        if copied:
            log += "\nboot sector copied to its backup"
            rc2, o2 = snap.sh(fsck_cmd(fstype, dev, False), timeout=3600)
    return rc2 == 0, (log + "\n" + o2).strip()


def disk_check(top, repair=False, out=print):
    """Kontrola (repair=False: nic se nezapisuje). -> [(krok, ok, vystup)]."""
    results = []
    dev = snap.root_device()

    def step(title, cmd, ok_codes=(0,), timeout=4 * 3600, ok_output=None):
        out(title)
        rc, o = snap.sh(cmd, timeout=timeout)
        ok = rc in ok_codes or (ok_output is not None and ok_output(rc, o))
        results.append((title, ok, o.strip()[-4000:]))
        return ok

    step("btrfs device stats", ["btrfs", "device", "stats", "-c", top])
    step("btrfs scrub", ["btrfs", "scrub", "start", "-B", "-d"] + ([] if repair else ["-r"]) + [top])
    if dev:
        # Na pripojenem souboroveho systemu jen pro cteni (--force); opravu (--repair) LuxOS nedela nikdy
        step("btrfs check --readonly", ["btrfs", "check", "--readonly", "--force", dev])
    for mp, fstype, bdev in boot_mounts():
        if not repair:
            # Pripojeny FAT ma vzdy priznak "dirty" (jadro) - samotny neni chyba
            step(f"fsck {mp}", fsck_cmd(fstype, bdev, False), ok_codes=(0,),
                 ok_output=(lambda rc, o: rc == 1 and fat_only_dirty(o)) if fstype == "vfat" else None)
            continue
        rc, o = snap.sh(["umount", mp], timeout=120)
        if rc != 0:
            results.append((f"fsck {mp}", False, o.strip()))
            continue
        try:
            # vysledek podle kontroly po oprave, ne podle navratoveho kodu opravy
            out(f"fsck {mp}")
            ok, o = repair_boot_partition(fstype, bdev)
            results.append((f"fsck {mp}", ok, o[-4000:]))
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
        # sokety a jine specialni soubory (napr. gpg-agent S.*) copytree neumi - preskocit
        def special(d, names):
            out = []
            for n in names:
                try:
                    m = os.lstat(os.path.join(d, n)).st_mode
                except OSError:
                    out.append(n)
                    continue
                if not (stat.S_ISDIR(m) or stat.S_ISREG(m) or stat.S_ISLNK(m)):
                    out.append(n)
            return out
        shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True, ignore=special)
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


def carry_data(old, new):
    """Data aplikaci (CARRY_DATA): cp --reflink=auto (stejny btrfs: sdilene bloky, hned hotovo)."""
    done = []
    for rel in CARRY_DATA:
        src = os.path.join(old, rel)
        if not os.path.isdir(src) or os.path.islink(src):
            continue
        dst = os.path.join(new, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(dst):
            shutil.rmtree(dst, ignore_errors=True)
        rc, o = snap.sh(["cp", "-a", "--reflink=auto", src, dst], timeout=3600)
        if rc != 0:
            raise snap.SnapshotError("copy_failed", f"{rel}: {o.strip()[-300:]}")
        done.append(rel)
    return done


def _carried(rel):
    return any(rel == c or rel.startswith(c.rstrip("/") + "/") for c in CARRY + list(ACCOUNT_FILES))


def changed_settings(old):
    """Nastaveni systemu, ktera preinstalace vrati do vychoziho stavu (prenasi se jen CARRY):
    upravene konfiguracni soubory baliku (backup, MODIFIED) a vlastni soubory v /etc mimo baliky.
    -> serazeny seznam cest ("/etc/...")."""
    db = os.path.join(old, "var/lib/lux")
    out = set()
    prefix = old.rstrip("/")

    def rel_of(path):
        # s --root vypisuje lux-engine cesty i s korenem (/run/.../@/etc/x)
        path = path.strip()
        if path.startswith(prefix + "/"):
            path = path[len(prefix):]
        return path.lstrip("/").rstrip("/")
    rc, text = snap.sh([care.ENGINE, "--root", old, "--dbpath", db, "-Qii"], timeout=300)
    if rc == 0:
        for ln in text.splitlines():
            # "Backup Files    : /etc/x [modified]" / "                  /etc/y [modified]"
            m = re.match(r"^\s*(?:Backup Files\s*:\s*)?(/\S+) \[modified\]\s*$", ln) or \
                re.match(r"^\s*MODIFIED\s+(/\S+)", ln)
            if m:
                rel = rel_of(m.group(1))
                if rel.startswith("etc/") and not _carried(rel) and not rel.startswith(GENERATED):
                    out.add("/" + rel)
    rc2, files = snap.sh([care.ENGINE, "--root", old, "--dbpath", db, "-Qlq"], timeout=300)
    if rc2 == 0:
        owned = {rel_of(f) for f in files.splitlines() if f.strip()}
        base = os.path.join(old, "etc")
        for d, dirs, names in os.walk(base):
            dirs.sort()
            for n in sorted(names):
                rel = os.path.relpath(os.path.join(d, n), old)
                if rel in owned or _carried(rel) or rel.startswith(GENERATED) \
                        or rel.endswith((".luxnew", ".luxsave", ".pacnew", ".pacsave", "~")):
                    continue
                out.add("/" + rel)
    return sorted(out)


def extra_places(old):
    """Vlastni programy mimo baliky, ktere preinstalace neprenese: /opt, /usr/local (krome LuxOS)."""
    out = []
    for rel in ("opt", "usr/local/bin", "usr/local/sbin", "usr/local/lib", "usr/local/share"):
        try:
            names = sorted(os.listdir(os.path.join(old, rel)))
        except OSError:
            continue
        for n in names:
            r = f"{rel}/{n}"
            p = os.path.join(old, r)
            # odkazy (napr. /usr/local/bin/mousepad -> luxos-text) a prazdne slozky (/opt/lux) vytvari
            # LuxOS sam a nova instalace je vytvori znovu
            if _carried(r) or n == "man" or os.path.islink(p) or (os.path.isdir(p) and not os.listdir(p)):
                continue
            out.append("/" + r)
    return out


def reinstall_plan(top):
    """Co preinstalace prenese a co ne (zobrazi se pred potvrzenim). -> dict."""
    snaps = snap.list_snapshots(top)
    system = snap.system_subvol(top, snaps)
    old = os.path.join(top, system)
    if not snap.BTRFS.is_subvolume(old):
        raise snap.SnapshotError("no_subvolume", system)
    native, foreign = explicit_packages(old)
    if not native:
        raise snap.SnapshotError("no_packages")
    flatpaks = []
    try:
        flatpaks = sorted(os.listdir(os.path.join(old, "var/lib/flatpak/app")))
    except OSError:
        pass
    users = human_users(_read(os.path.join(old, "etc/passwd")))
    wifi = []
    try:
        wifi = sorted(n.rsplit(".nmconnection", 1)[0] for n in os.listdir(
            os.path.join(old, "etc/NetworkManager/system-connections")) if n.endswith(".nmconnection"))
    except OSError:
        pass
    return {"system": system, "packages": len(native), "foreign": foreign, "flatpaks": flatpaks,
            "settings": changed_settings(old), "extra": extra_places(old), "users": users, "wifi": wifi}


def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


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
            # *.wants/*.requires, vychozi cil a aliasy (display-manager.service -> lightdm.service,
            # dbus-org.*.service) - bez aliasu display-manager po preinstalaci nenabehlo prihlaseni (VM)
            if not (rel_dir.endswith((".wants", ".requires")) or rel_dir == "."):
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
        out("Removing an unfinished reinstall")
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
        out("Installing %d packages", len(native))
        # --disable-sandbox: stahovani pod uzivatelem alpm (lux.conf [downloads] user) by do noveho
        # systemu pod /run/luxos-snapshots (0700) nezapsalo - ve VM "luxos.db.part: Permission denied".
        # Baliky dal overuje podpis.
        rc, o = snap.sh([care.ENGINE, "--root", new, "--dbpath", os.path.join(new, "var/lib/lux"),
                         "--cachedir", os.path.join(new, "var/cache/lux/pkg"), "--disable-sandbox",
                         # /boot (/efi) je pripojeny EFI oddil puvodniho systemu: soubory baliku na nem
                         # (amd-ucode.img, intel-ucode.img) nova databaze nezna - ve VM "conflicting files";
                         # s --root plati jen vzor bez uvodniho / (overeno ve VM, "/boot/*" nezabral)
                         "--overwrite", "boot/*", "--overwrite", "efi/*",
                         "--noconfirm", "--needed", "-Sy", "--"] + native, timeout=6 * 3600)
        if rc != 0:
            raise snap.SnapshotError("install_failed", o.strip()[-1500:])
        out("Copying accounts and settings")
        carry_config(old, new)
        carry_services(old, new)
        carry_data(old, new)
        # prvni start noveho systemu se overi (nabidka zavadece pri dalsim startu, kdyz selze)
        care.atomic_write(os.path.join(new, care.VERIFY_BOOT.lstrip("/")), f"{care.now()}\n")
        rc, o = snap.sh(["chroot", new, "systemctl", "set-default", "graphical.target"], timeout=120)
        # jazyk: prenesene /etc/locale.gen se musi i vygenerovat (jinak po preinstalaci "Cannot set
        # LC_CTYPE" a aplikace anglicky - overeno ve VM); dela to i instalator (setup-chroot.sh)
        if os.path.exists(os.path.join(new, "usr/bin/locale-gen")):
            rc, o = snap.sh(["chroot", new, "locale-gen"], timeout=600)
            if rc != 0:
                out("Generating the language failed: %s", o.strip()[-300:])
        out("Creating the initramfs")
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
