"""Lux Guard - zachranna sit proti smazani: snimky btrfs slozky /home jen pro cteni.

Snimky jsou v <koren /home>/.luxos-guard-snapshots/RRRR-MM-DD_HH-MM (adresar root 0755,
kazdy snimek je subvolume jen pro cteni). Uzivatel ani jeho programy je nemuzou zmenit ani smazat
(mazat subvolume smi jen root; snimek jen pro cteni nejde zmenit ani rootovi bez prepnuti ro).
Domov kazdeho uzivatele ve snimku ma svoje puvodni prava (0700), takze ho vidi jen jeho vlastnik
- obnova souboru proto bezi jako uzivatel, bez root prav.

Snimky dela luxos-guard-snapshot.timer (kazdou hodinu, root). Uchovava se: vsechny snimky
za poslednich 24 hodin, nejnovejsi za kazdy den z poslednich 7 dni. Pri malo mistu na disku
(< 5 % nebo < 2 GiB) se mazou nejstarsi (posledni dva zustanou). Na jinem nez btrfs, nebo kdyz
/home neni samostatny subvolume, se nic nedela.
"""
import datetime
import os
import re
import shutil
import stat
import subprocess

from luxos_guard_core import SNAP_DIR_NAME

HOME = "/home"
NAME_FMT = "%Y-%m-%d_%H-%M"
NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}$")
KEEP_HOURS = 24
KEEP_DAYS = 7
MIN_FREE_FRACTION = 0.05
MIN_FREE_BYTES = 2 << 30
BTRFS_SUBVOL_INO = 256


def snap_root(home=HOME):
    return os.path.join(home, SNAP_DIR_NAME)


def fs_type(path, mountinfo="/proc/self/mountinfo"):
    """Typ souboroveho systemu pripojeni, na kterem cesta lezi (nejdelsi shodny bod pripojeni)."""
    best, fstype = "", None
    try:
        with open(mountinfo, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                try:
                    sep = parts.index("-")
                except ValueError:
                    continue
                mp = parts[4].replace("\\040", " ")
                if (path == mp or path.startswith(mp.rstrip("/") + "/")) and len(mp) >= len(best):
                    best, fstype = mp, parts[sep + 1]
    except OSError:
        return None
    return fstype


def supported(home=HOME, mountinfo="/proc/self/mountinfo"):
    """Snimky jdou jen na btrfs, kdyz je /home samostatny subvolume (instalator LuxOS: @home)."""
    if fs_type(home, mountinfo) != "btrfs":
        return False
    try:
        return os.stat(home).st_ino == BTRFS_SUBVOL_INO
    except OSError:
        return False


def parse_name(name):
    if not NAME_RE.match(name):
        return None
    try:
        return datetime.datetime.strptime(name, NAME_FMT)
    except ValueError:
        return None


def list_snapshots(home=HOME):
    """[(cas, cesta)] od nejstarsiho."""
    root = snap_root(home)
    out = []
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for n in names:
        t = parse_name(n)
        if t:
            out.append((t, os.path.join(root, n)))
    out.sort()
    return out


def to_prune(times, now, free_ok=True):
    """Ktere snimky smazat: starsi nez 24 h si nechaji jen posledni snimek dne (7 dni), starsi nez
    7 dni pryc. free_ok=False (malo mista): navic nejstarsi, posledni dva zustanou."""
    keep = set()
    days = {}
    for t in sorted(times):
        age = now - t
        if age <= datetime.timedelta(hours=KEEP_HOURS):
            keep.add(t)
        elif age <= datetime.timedelta(days=KEEP_DAYS):
            days[t.date()] = t          # serazeno -> zustane nejnovejsi za den
    keep.update(days.values())
    out = [t for t in times if t not in keep]
    if not free_ok:
        rest = sorted(t for t in times if t in keep)
        out.extend(rest[:-2])
    return sorted(set(out))


def free_ok(path):
    try:
        st = os.statvfs(path)
    except OSError:
        return True
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    return free >= MIN_FREE_BYTES and (total == 0 or free >= total * MIN_FREE_FRACTION)


def _run(cmd):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def take(home=HOME, now=None, run=_run):
    """Novy snimek jen pro cteni (root). Vraci cestu, nebo None (nepodporovano / uz existuje)."""
    if not supported(home):
        return None
    now = now or datetime.datetime.now()
    root = snap_root(home)
    try:
        os.mkdir(root, 0o755)
    except FileExistsError:
        pass
    st = os.lstat(root)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0:
        raise OSError(f"{root} is not a directory owned by root")
    if st.st_mode & 0o7777 != 0o755:
        os.chmod(root, 0o755)
    dest = os.path.join(root, now.strftime(NAME_FMT))
    if os.path.lexists(dest):
        return None
    r = run(["btrfs", "subvolume", "snapshot", "-r", home, dest])
    if r.returncode != 0:
        raise OSError((r.stderr or "").strip() or "btrfs subvolume snapshot failed")
    return dest


def prune(home=HOME, now=None, run=_run):
    """Smaze stare snimky podle pravidel; vraci seznam smazanych cest."""
    now = now or datetime.datetime.now()
    snaps = list_snapshots(home)
    times = [t for t, _p in snaps]
    doomed = set(to_prune(times, now, free_ok(home)))
    gone = []
    for t, p in snaps:
        if t in doomed:
            r = run(["btrfs", "subvolume", "delete", p])
            if r.returncode == 0:
                gone.append(p)
    return gone


# ---- obnova (bezi jako uzivatel) -----------------------------------------------------------------
def user_snapshot_dir(snap_path, home_dir, home=HOME):
    """Domov uzivatele ve snimku: /home/.luxos-guard-snapshots/<cas>/<uzivatel>."""
    rel = os.path.relpath(os.path.normpath(home_dir), home)
    if rel.startswith(".."):
        raise ValueError("home outside " + home)
    return os.path.join(snap_path, rel)


def restore(src, dest, overwrite=False, dry_run=False, skip_top=()):
    """Zkopiruje src (soubor nebo slozku ve snimku) do dest. Bez overwrite jen chybejici soubory
    (obnova smazanych), s overwrite i zmenene (napr. zasifrovane ransomwarem). Novejsi soubory, ktere
    ve snimku nejsou, nemaze nikdy. Symlinky kopiruje jako symlinky. skip_top: jmena v nejvyssi urovni,
    ktera se preskoci (cela slozka domova bez .cache). Vraci (obnoveno, preskoceno)."""
    restored = skipped = 0

    def copy_file(s, d):
        nonlocal restored, skipped
        try:
            dst = os.lstat(d)
        except FileNotFoundError:
            dst = None
        sst = os.lstat(s)
        if dst is not None:
            same = (stat.S_IFMT(dst.st_mode) == stat.S_IFMT(sst.st_mode) and dst.st_size == sst.st_size
                    and int(dst.st_mtime) == int(sst.st_mtime))
            if same or not overwrite:
                skipped += 1
                return
            if stat.S_ISDIR(dst.st_mode):
                skipped += 1
                return
        if dry_run:
            restored += 1
            return
        if dst is not None:
            os.unlink(d)
        if stat.S_ISLNK(sst.st_mode):
            os.symlink(os.readlink(s), d)
        elif stat.S_ISREG(sst.st_mode):
            shutil.copy2(s, d, follow_symlinks=False)
        else:
            skipped += 1
            return
        restored += 1

    sst = os.lstat(src)
    if not stat.S_ISDIR(sst.st_mode):
        if not dry_run:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
        copy_file(src, dest)
        return restored, skipped
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        rel = os.path.relpath(dirpath, src)
        if rel == "." and skip_top:
            dirnames[:] = [n for n in dirnames if n not in skip_top]
        target = dest if rel == "." else os.path.join(dest, rel)
        try:
            tst = os.lstat(target)
            if not stat.S_ISDIR(tst.st_mode):
                skipped += len(filenames)
                dirnames[:] = []
                continue
        except FileNotFoundError:
            if not dry_run:
                os.makedirs(target, exist_ok=True)
                try:
                    shutil.copystat(dirpath, target, follow_symlinks=False)
                except OSError:
                    pass
        for n in list(dirnames):
            p = os.path.join(dirpath, n)
            if os.path.islink(p):
                dirnames.remove(n)
                copy_file(p, os.path.join(target, n))
        for n in filenames:
            try:
                copy_file(os.path.join(dirpath, n), os.path.join(target, n))
            except OSError:
                skipped += 1
    return restored, skipped
