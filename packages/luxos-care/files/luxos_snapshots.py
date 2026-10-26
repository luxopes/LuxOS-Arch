"""LuxOS Care - snimky systemu pred kazdou zmenou baliku a navrat z nabidky zavadece.

Snimky (btrfs, jen pro cteni) jsou v subvolumu @snapshots na nejvyssi urovni souboroveho systemu,
vedle systemoveho subvolumu (@):

  @snapshots/RRRR-MM-DD_HH-MM-SS        snimek systemoveho subvolumu (jen pro cteni)
  @snapshots/RRRR-MM-DD_HH-MM-SS.json   popis: kdy, z ceho, jadro, baliky transakce

Snimek dela hook libalpm 05-luxos-snapshot.hook pred kazdou transakci, ktera meni baliky - tedy
pro lux, LuxOS Care i Obchod (vsechny jdou pres libalpm). Uchovava se poslednich 5 snimku a navic
posledni snimek s predchozim jadrem (pred posledni zmenou jadra); pri malo mistu jen 2.

Jadro a initramfs: /boot (EFI oddil, u GRUB samostatny oddil) neni soucasti systemoveho subvolumu,
takze po aktualizaci jadra by snimek s novym jadrem nenabehl (moduly v /usr/lib/modules snimku
patri ke staremu jadru). Proto se pri snimku ulozi i jadro a initramfs, se kterymi system ted
startuje ("sada jadra", <adresar jadra na ESP>/luxos-snapshots/<verze>-<otisk>/). Sady se sdileji:
snimky se stejnym jadrem a initramfs (vetsina aktualizaci jadro nemeni) pouzivaji jednu kopii.
Polozka zavadece snimku pak startuje presne to jadro, se kterym snimek naposledy bezel.

Start ze snimku: rootflags=subvol=@snapshots/<jmeno> systemd.volatile=overlay luxos.snapshot=<jmeno>
- snimek zustane jen pro cteni, zmeny jdou do docasne vrstvy v pameti (systemd-volatile-root, hook
initramfs luxos-snapshot) a po restartu zmizi. Trvaly navrat: `lux rollback` (luxos-care rollback):
soucasny system se odlozi jako snimek ("pred navratem"), ze snimku se udela novy zapisovatelny @
a jadro snimku se vrati na misto hlavni polozky. Nic se nemaze.

LUXOS_CARE_ROOT (luxos_care.P) predradi cesty, LUXOS_SNAPSHOT_TOP urci uz pripojenou nejvyssi
uroven btrfs (testy, obnova) - jinak se pripoji docasne do /run/luxos-snapshots/top.
"""
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import time

import luxos_care as care
from luxos_care import P

SNAP_SUBVOL = "@snapshots"
KSET_DIR = "luxos-snapshots"
NAME_FMT = "%Y-%m-%d_%H-%M-%S"
NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")
KSET_RE = re.compile(r"^[A-Za-z0-9._+-]{1,100}-[0-9a-f]{12}$")
KEEP = 5
KEEP_LOW_SPACE = 2
MIN_FREE_FRACTION = 0.05
MIN_FREE_BYTES = 2 << 30
TOP_RUN = "/run/luxos-snapshots/top"
LOCK = "/run/luxos-snapshots/lock"
ENTRY_MARK = "# LuxOS snapshot entry - managed automatically by luxos-care"
GRUB_CFG = "/boot/grub/luxos-snapshots.cfg"
GRUB_MAIN_CFG = "/boot/grub/grub.cfg"
VOLATILE_UNIT = "systemd-volatile-root.service"     # v initramfs: hook luxos-snapshot
RECOVERY_BIN = "/usr/lib/luxos/care/luxos-recovery"
RECOVERY_TARGET = "luxos-recovery.target"
AFTER_ROLLBACK = "/var/lib/luxos-care/after-rollback"
PAUSE_AFTER_ROLLBACK = 3 * 24 * 3600     # automaticke aktualizace po navratu (stejna chyba znovu)
KINDS = ("update", "manual", "before-rollback", "before-reinstall")
# Parametry, ktere polozka snimku a obnovy sama nastavuje (z hlavni polozky se neprebiraji)
OWN_PARAMS = ("BOOT_IMAGE=", "initrd=", "luxos.snapshot=", "systemd.volatile=", "systemd.unit=",
              "rootflags=", "plymouth.enable=")
RECOVERY_DROP = ("quiet", "splash", "vt.global_cursor_default=0")


class SnapshotError(Exception):
    """Chyba s kodem pro uzivatele (code) a podrobnosti (detail)."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def sh(cmd, timeout=600):
    """Spusteni prikazu -> (rc, vystup). Testy ho nahrazuji."""
    return care.run(cmd, timeout=timeout)


# ---- btrfs ---------------------------------------------------------------------------------
class Btrfs:
    """Operace se subvolumy (testy ji nahrazuji tridou nad obycejnymi adresari)."""

    def snapshot(self, src, dst, readonly=True):
        rc, out = sh(["btrfs", "subvolume", "snapshot"] + (["-r"] if readonly else []) + [src, dst])
        if rc != 0:
            raise SnapshotError("snapshot_failed", out.strip()[-500:])

    def create(self, path):
        rc, out = sh(["btrfs", "subvolume", "create", path])
        if rc != 0:
            raise SnapshotError("subvolume_failed", out.strip()[-500:])

    def delete(self, path):
        rc, out = sh(["btrfs", "subvolume", "delete", path])
        if rc != 0:
            raise SnapshotError("delete_failed", out.strip()[-500:])

    def is_subvolume(self, path):
        try:
            return os.stat(path).st_ino == 256
        except OSError:
            return False


BTRFS = Btrfs()


# ---- prikazova radka jadra a pripojeni -----------------------------------------------------
def cmdline():
    try:
        with open(P("/proc/cmdline")) as f:
            return f.read().strip()
    except OSError:
        return ""


def cmdline_value(key, text=None):
    """Hodnota parametru jadra (posledni vyskyt), nebo None."""
    val = None
    for tok in (cmdline() if text is None else text).split():
        if tok == key:
            val = ""
        elif tok.startswith(key + "="):
            val = tok[len(key) + 1:]
    return val


def booted_snapshot():
    """Jmeno snimku, ze ktereho system prave bezi (luxos.snapshot=), jinak ''."""
    v = cmdline_value("luxos.snapshot") or ""
    return v if NAME_RE.match(v) else ""


def mounts():
    """[(bod, typ, zdroj, koren v fs, volby superbloku)] z /proc/self/mountinfo (v poradi)."""
    out = []
    try:
        with open(P("/proc/self/mountinfo"), encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                try:
                    sep = parts.index("-")
                except ValueError:
                    continue
                if len(parts) < sep + 3:
                    continue
                unesc = lambda s: s.replace("\\040", " ").replace("\\011", "\t")  # noqa: E731
                out.append((unesc(parts[4]), parts[sep + 1], unesc(parts[sep + 2]), unesc(parts[3]),
                            parts[sep + 3] if len(parts) > sep + 3 else ""))
    except OSError:
        pass
    return out


def mount_of(path):
    """Pripojeni, na kterem cesta lezi (posledni s nejdelsim shodnym bodem)."""
    best = None
    for m in mounts():
        mp = m[0]
        if path == mp or path.startswith(mp.rstrip("/") + "/") or mp == "/":
            if best is None or len(mp) >= len(best[0]):
                best = m
    return best


def is_mountpoint(path):
    return any(m[0] == path for m in mounts())


def root_info():
    """dict(fstype, source, subvol) korene systemu."""
    m = None
    for x in mounts():
        if x[0] == "/":
            m = x
    if not m:
        return {"fstype": "", "source": "", "subvol": ""}
    source = re.sub(r"\[.*\]$", "", m[2])
    subvol = m[3].strip("/") if m[1] == "btrfs" else ""
    return {"fstype": m[1], "source": source, "subvol": subvol}


def root_device():
    """Blokove zarizeni systemoveho btrfs (i pri startu ze snimku, kdy je / overlay)."""
    info = root_info()
    if info["fstype"] == "btrfs" and info["source"].startswith("/"):
        return info["source"]
    root = cmdline_value("root") or ""
    if root.startswith("UUID="):
        return "/dev/disk/by-uuid/" + root[5:]
    if root.startswith("PARTUUID="):
        return "/dev/disk/by-partuuid/" + root[9:]
    if root.startswith("/dev/"):
        return root
    # Posledni moznost: subvolume @home/@log/@cache ze stejneho souboroveho systemu
    for mp, fstype, src, _r, sopts in mounts():
        if fstype == "btrfs" and src.startswith("/dev/"):
            return re.sub(r"\[.*\]$", "", src)
    return ""


def in_chroot():
    """Bezi v chrootu (instalator, preinstalace z obnovy) - tam se snimky nedelaji."""
    if care.ROOT:
        return os.path.exists(P("/run/luxos-test-chroot"))
    try:
        a, b = os.stat("/"), os.stat("/proc/1/root/.")
        return (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino)
    except OSError:
        return False


def supported():
    """Lze delat snimky systemu? -> (ok, duvod)."""
    if os.path.exists(P("/run/archiso")):
        return False, "live"
    if care.config().get("SNAPSHOTS", "yes").lower() in ("no", "0", "false", "off"):
        return False, "disabled"
    if booted_snapshot():
        return False, "snapshot_boot"
    info = root_info()
    if info["fstype"] != "btrfs":
        return False, "not_btrfs"
    if not info["subvol"] or info["subvol"].startswith(SNAP_SUBVOL + "/"):
        return False, "no_subvolume"
    return True, ""


@contextlib.contextmanager
def top_level():
    """Nejvyssi uroven btrfs (subvolid=5) pripojena docasne -> cesta."""
    env = os.environ.get("LUXOS_SNAPSHOT_TOP")
    if env:
        yield env
        return
    dev = root_device()
    if not dev:
        raise SnapshotError("no_device")
    path = P(TOP_RUN)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    os.makedirs(path, mode=0o700, exist_ok=True)
    if is_mountpoint(TOP_RUN):
        yield path
        return
    rc, out = sh(["mount", "-t", "btrfs", "-o", "subvolid=5,noatime", dev, path], timeout=120)
    if rc != 0:
        raise SnapshotError("mount_failed", out.strip()[-300:])
    try:
        yield path
    finally:
        rc, _o = sh(["umount", path], timeout=120)
        if rc != 0:
            sh(["umount", "-l", path], timeout=60)


@contextlib.contextmanager
def snapshot_lock():
    """Jedna operace se snimky naraz (bez CareLock: hook bezi i uvnitr aktualizace LuxOS Care)."""
    path = P(LOCK)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


# ---- seznam snimku -----------------------------------------------------------------------
def snap_dir(top):
    return os.path.join(top, SNAP_SUBVOL)


def ensure_snap_dir(top):
    d = snap_dir(top)
    if not os.path.isdir(d):
        BTRFS.create(d)
        os.chmod(d, 0o700)
    return d


def read_meta(top, name):
    try:
        with open(os.path.join(snap_dir(top), name + ".json")) as f:
            m = json.load(f)
        if not isinstance(m, dict):
            m = {}
    except (OSError, ValueError):
        m = {}
    m["name"] = name
    m.setdefault("kind", "update")
    m.setdefault("source", "@")
    return m


def write_meta(top, meta):
    data = {k: v for k, v in meta.items() if k != "name"}
    care.atomic_write(os.path.join(snap_dir(top), meta["name"] + ".json"),
                      json.dumps(data, indent=1, ensure_ascii=False) + "\n", 0o600)


def list_snapshots(top):
    """Popisy snimku od nejstarsiho (jen platna jmena, ktera jsou opravdu subvolume)."""
    d = snap_dir(top)
    try:
        names = sorted(n for n in os.listdir(d) if NAME_RE.match(n) and os.path.isdir(os.path.join(d, n)))
    except OSError:
        return []
    return [read_meta(top, n) for n in names]


def find(snaps, name):
    for s in snaps:
        if s["name"] == name:
            return s
    return None


def new_name(top, now=None):
    t = now or datetime.datetime.now()
    name = t.strftime(NAME_FMT)
    while os.path.lexists(os.path.join(snap_dir(top), name)):
        t += datetime.timedelta(seconds=1)
        name = t.strftime(NAME_FMT)
    return name


def label(meta):
    """Nazev v nabidce zavadece (zavadec neumi preklady - anglicky)."""
    try:
        t = datetime.datetime.strptime(meta["name"], NAME_FMT).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        t = meta["name"]
    kind = meta.get("kind")
    if kind == "before-rollback":
        return f"LuxOS (before rollback of {t})"
    if kind == "before-reinstall":
        return f"LuxOS (before reinstall of {t})"
    if kind == "manual":
        return f"LuxOS (snapshot of {t})"
    return f"LuxOS (before update of {t})"


# ---- uchovavani ----------------------------------------------------------------------------
def to_prune(snaps, keep=KEEP, protect=()):
    """Ktere snimky smazat: zustane poslednich `keep` a navic nejnovejsi snimek s jinym jadrem,
    nez ma nejnovejsi snimek (stav pred posledni zmenou jadra). `protect` se nemaze nikdy."""
    names = [s["name"] for s in snaps]
    keep_set = set(names[-keep:]) if keep > 0 else set()
    if snaps:
        latest = snaps[-1].get("kver") or ""
        for s in reversed(snaps):
            if s.get("kver") and latest and s["kver"] != latest:
                keep_set.add(s["name"])
                break
    keep_set |= set(protect)
    return [s for s in snaps if s["name"] not in keep_set]


def configured_keep():
    """SNAPSHOT_KEEP v /etc/luxos/care.conf (1-50), jinak 5."""
    try:
        return max(1, min(50, int(care.config().get("SNAPSHOT_KEEP", KEEP))))
    except ValueError:
        return KEEP


def free_ok(path):
    try:
        st = os.statvfs(path)
    except OSError:
        return True
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    return free >= MIN_FREE_BYTES and (total == 0 or free >= total * MIN_FREE_FRACTION)


def in_use(top):
    """Snimky, ktere se nesmi mazat: ten, ze ktereho system bezi, a pripojeny jako koren."""
    out = set()
    b = booted_snapshot()
    if b:
        out.add(b)
    sub = root_info().get("subvol") or ""
    if sub.startswith(SNAP_SUBVOL + "/"):
        out.add(sub.split("/", 1)[1])
    for mp, fstype, _s, fsroot, _o in mounts():
        if fstype == "btrfs" and fsroot.strip("/").startswith(SNAP_SUBVOL + "/"):
            out.add(fsroot.strip("/").split("/")[1])
    return out


def prune(top, keep=None):
    snaps = list_snapshots(top)
    if keep is None:
        keep = configured_keep() if free_ok(top) else KEEP_LOW_SPACE
    gone = []
    for s in to_prune(snaps, keep=max(1, keep), protect=in_use(top)):
        path = os.path.join(snap_dir(top), s["name"])
        try:
            BTRFS.delete(path)
        except SnapshotError as e:
            care.log(f"snapshot {s['name']} not deleted: {e.detail or e.code}")
            continue
        try:
            os.unlink(path + ".json")
        except OSError:
            pass
        gone.append(s["name"])
    return gone


# ---- jadro a initramfs snimku ("sada jadra") ----------------------------------------------
def boot_kernel(kernel, modules=None):
    """Jadro, se kterym hlavni polozka startuje (/boot/vmlinuz-K, /boot/initramfs-K.img), a jeho
    verze podle /usr/lib/modules systemu -> (verze, vmlinuz, initramfs) nebo None (nesouhlasi / chybi).
    modules: adresar modulu systemu (pri startu ze snimku ten v systemovem subvolumu)."""
    vml = P(f"/boot/vmlinuz-{kernel}")
    img = P(f"/boot/initramfs-{kernel}.img")
    modules = modules or P(care.MODULES)
    if not (os.path.isfile(vml) and os.path.isfile(img)):
        return None
    try:
        vers = sorted(os.listdir(modules), key=care._verkey, reverse=True)
    except OSError:
        return None
    for v in vers:
        mv = os.path.join(modules, v, "vmlinuz")
        if os.path.isfile(mv) and care._same_file(vml, mv):
            return v, vml, img
    return None


def digest(*paths):
    h = hashlib.sha256()
    for p in paths:
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()[:12]


def initramfs_has_overlay(img):
    """Initramfs umi start ze snimku (hook luxos-snapshot: systemd-volatile-root)."""
    rc, out = sh(["lsinitcpio", "-l", img], timeout=120)
    return rc == 0 and any(line.rstrip().endswith(VOLATILE_UNIT) for line in out.splitlines())


def kernel_store(lay, top=None):
    """Kam ukladat sady jadra a jak na ne vidi zavadec.
    -> dict(dir=cesta v systemu, loader=cesta pro zavadec, grub=dict(uuid) u GRUB) nebo None."""
    if lay["kind"] == "sdboot":
        return {"dir": lay["kdir"] + "/" + KSET_DIR, "loader": (lay.get("rel") or "") + "/" + KSET_DIR}
    if lay["kind"] == "grub":
        if is_mountpoint("/boot"):
            m = mount_of("/boot")
            rel = "/" + m[3].strip("/") if m and m[1] == "btrfs" and m[3].strip("/") else ""
            return {"dir": "/boot/" + KSET_DIR, "loader": rel + "/" + KSET_DIR, "grub": {"path": "/boot"}}
        if top is None:
            return None
        # /boot v systemovem btrfs: GRUB cte btrfs primo, sady jsou mimo system (rollback je nepresune)
        return {"dir": None, "top_rel": SNAP_SUBVOL + "/.kernels", "loader": "/" + SNAP_SUBVOL + "/.kernels",
                "grub": {"path": "/"}}
    return None


def store_dir(store, top):
    if store.get("dir"):
        return P(store["dir"])
    return os.path.join(top, store["top_rel"])


def save_kernel(lay, top, kernel, build=None):
    """Ulozi jadro a initramfs soucasneho systemu jako sadu -> (id sady, verze, s_overlay) nebo
    (None, verze, False). Initramfs bez hooku luxos-snapshot se sestavi znovu (mkinitcpio)."""
    modules = None
    if booted_snapshot():
        modules = os.path.join(top, system_subvol(top), care.MODULES.lstrip("/"))
    found = boot_kernel(kernel, modules)
    if not found:
        return None, "", False
    ver, vml, img = found
    store = kernel_store(lay, top)
    if not store:
        return None, ver, False
    overlay = initramfs_has_overlay(img)
    tmp_img = None
    if not overlay and not booted_snapshot():
        # mkinitcpio sestavi initramfs z beziciho systemu - ze snimku by nesouhlasil
        build = build or care.build_prev_initramfs
        tmp_img = P(f"{care.KSTATE}/snapshot-initramfs-{ver}.img")
        os.makedirs(os.path.dirname(tmp_img), exist_ok=True)
        if build(ver, tmp_img) and initramfs_has_overlay(tmp_img):
            img, overlay = tmp_img, True
    try:
        kid = f"{ver}-{digest(vml, img)}"
        base = store_dir(store, top)
        dst = os.path.join(base, kid)
        if os.path.isfile(os.path.join(dst, "initramfs.img")):
            return kid, ver, overlay
        need = os.path.getsize(vml) + os.path.getsize(img) + 8 * 1024 * 1024
        os.makedirs(base, exist_ok=True)
        if care.free_bytes(base) < need:
            care.log(f"not enough space for the kernel of the snapshot in {base}")
            return None, ver, False
        tmp = dst + ".new"
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        shutil.copyfile(vml, os.path.join(tmp, "vmlinuz"))
        shutil.copyfile(img, os.path.join(tmp, "initramfs.img"))
        with open(os.path.join(tmp, "kernel.json"), "w") as f:
            json.dump({"kver": ver, "overlay": overlay}, f)
        os.rename(tmp, dst)
        return kid, ver, overlay
    except OSError as e:
        care.log(f"saving the kernel of the snapshot failed: {e}")
        return None, ver, False
    finally:
        if tmp_img:
            try:
                os.unlink(tmp_img)
            except OSError:
                pass


def kset_path(lay, top, kid):
    store = kernel_store(lay, top)
    if not store or not kid:
        return None
    d = os.path.join(store_dir(store, top), kid)
    if os.path.isfile(os.path.join(d, "vmlinuz")) and os.path.isfile(os.path.join(d, "initramfs.img")):
        return d
    return None


def gc_kernels(lay, top, snaps):
    """Smaze sady jadra, ktere uz zadny snimek nepouziva."""
    store = kernel_store(lay, top)
    if not store:
        return []
    base = store_dir(store, top)
    used = {s.get("kset") for s in snaps}
    gone = []
    try:
        names = os.listdir(base)
    except OSError:
        return gone
    for n in names:
        p = os.path.join(base, n)
        if n.endswith(".new") or (KSET_RE.match(n) and n not in used):
            shutil.rmtree(p, ignore_errors=True)
            gone.append(n)
    return gone


# ---- prikazova radka polozek ----------------------------------------------------------------
def entry_options(base, subvol, extra=(), drop=()):
    """Volby jadra hlavni polozky pro jiny subvolume: rootflags se zmeni jen v subvol=,
    vlastni parametry (luxos.snapshot, systemd.volatile, systemd.unit...) se nahradi."""
    out, flags = [], ""
    for t in base.split():
        if t.startswith("rootflags="):
            flags = t[len("rootflags="):]
            continue
        if t.startswith(OWN_PARAMS) or t in drop:
            continue
        out.append(t)
    fl = [f for f in flags.split(",") if f and not f.startswith(("subvol=", "subvolid="))]
    out.append("rootflags=" + ",".join([f"subvol={subvol}"] + fl))
    out.extend(extra)
    return " ".join(out)


def snapshot_params(name):
    return [f"luxos.snapshot={name}", "systemd.volatile=overlay"]


def recovery_params():
    return [f"systemd.unit={RECOVERY_TARGET}", "plymouth.enable=0"]


def bootable(lay, top, meta):
    return bool(meta.get("overlay")) and kset_path(lay, top, meta.get("kset")) is not None


def recovery_snapshot(lay, top, snaps):
    """Obnova startuje z nejnovejsiho snimku, ktery ji obsahuje (system po vadne aktualizaci
    nemusi nabehnout ani do obnovy); bez nej ze soucasneho systemu."""
    for s in reversed(snaps):
        if s.get("recovery") and s.get("kind") in ("update", "manual") and bootable(lay, top, s):
            return s
    return None


# -- systemd-boot --
def _main_entry(lay):
    with open(P(f"{lay['entries']}/{lay['main']}")) as f:
        return care.parse_entry(f.read())


def sdboot_entries(lay, top, snaps, system):
    """{soubor: text} polozek snimku a obnovy pro systemd-boot."""
    e = _main_entry(lay)
    options = " ".join(e.get("options") or [])
    linux_main = (e.get("linux") or [""])[0]
    initrds = e.get("initrd") or []
    extra_initrd = [i for i in initrds if not os.path.basename(i).startswith("initramfs-")]
    initrd_main = [i for i in initrds if os.path.basename(i).startswith("initramfs-")][:1]
    store = kernel_store(lay, top)
    sorted_ = bool(e.get("sort-key"))
    out = {}

    def text(title, sort_key, version, linux, initrd, opts):
        lines = [ENTRY_MARK, f"title   {title}"]
        if sorted_:
            lines.append(f"sort-key {sort_key}")
        if version:
            lines.append(f"version {version}")
        lines.append(f"linux   {linux}")
        lines += [f"initrd  {i}" for i in extra_initrd + initrd]
        lines.append(f"options {opts}")
        return "\n".join(lines) + "\n"

    for s in snaps:
        if not bootable(lay, top, s):
            continue
        k = f"{store['loader']}/{s['kset']}"
        out[f"snapshot-{lay['name']}-{s['name']}.conf"] = text(
            label(s), "luxos-snapshot", s["name"], f"{k}/vmlinuz", [f"{k}/initramfs.img"],
            entry_options(options, f"{SNAP_SUBVOL}/{s['name']}", snapshot_params(s["name"])))
    rs = recovery_snapshot(lay, top, snaps)
    if rs:
        k = f"{store['loader']}/{rs['kset']}"
        out[f"recovery-{lay['name']}.conf"] = text(
            "LuxOS Recovery", "luxos-system-recovery", "", f"{k}/vmlinuz", [f"{k}/initramfs.img"],
            entry_options(options, f"{SNAP_SUBVOL}/{rs['name']}", snapshot_params(rs["name"]) + recovery_params(),
                          drop=RECOVERY_DROP))
    elif linux_main and os.path.exists(P(RECOVERY_BIN)):
        out[f"recovery-{lay['name']}.conf"] = text(
            "LuxOS Recovery", "luxos-system-recovery", "", linux_main, initrd_main,
            entry_options(options, system, recovery_params(), drop=RECOVERY_DROP))
    return out


def write_sdboot(lay, files):
    """Zapise polozky; smaze jen vlastni stare (znacka v souboru a nase predpona)."""
    d = P(lay["entries"])
    prefixes = (f"snapshot-{lay['name']}-", f"recovery-{lay['name']}.conf")
    try:
        existing = os.listdir(d)
    except OSError:
        return
    for f in existing:
        if f.startswith(prefixes) and f not in files:
            path = os.path.join(d, f)
            try:
                with open(path) as fh:
                    mine = fh.readline().strip() == ENTRY_MARK
            except OSError:
                mine = False
            if mine:
                os.unlink(path)
    for f, text in files.items():
        path = os.path.join(d, f)
        try:
            with open(path) as fh:
                if fh.read() == text:
                    continue
        except OSError:
            pass
        care.atomic_write(path, text)


# -- GRUB --
def fs_uuid(path):
    rc, out = sh(["findmnt", "-n", "-o", "UUID", "-T", P(path)], timeout=30)
    u = out.strip().splitlines()[0].strip() if rc == 0 and out.strip() else ""
    return u if re.fullmatch(r"[0-9A-Fa-f-]{4,64}", u) else ""


def grub_options():
    """Volby jadra soucasneho startu (GRUB je sklada z /etc/default/grub a 10_linux)."""
    text = cmdline()
    return " ".join(t for t in text.split() if not t.startswith(("BOOT_IMAGE=", "initrd=")))


def grub_entry(title, ident, uuid, linux, initrd, opts):
    q = title.replace("'", "")
    return (f"menuentry '{q}' --class luxos --class gnu-linux --class os $menuentry_id_option '{ident}' {{\n"
            "\tload_video\n\tinsmod gzio\n\tinsmod part_gpt\n\tinsmod part_msdos\n\tinsmod ext2\n\tinsmod btrfs\n"
            f"\tsearch --no-floppy --fs-uuid --set=root {uuid}\n"
            f"\techo 'Loading {q} ...'\n"
            f"\tlinux\t{linux} {opts}\n"
            f"\tinitrd\t{initrd}\n"
            "}\n")


def grub_cfg(lay, top, snaps, system, kernel):
    store = kernel_store(lay, top)
    base = grub_options()
    parts = ["# LuxOS snapshots and recovery - managed automatically by luxos-care (do not edit)\n"]
    uuid = fs_uuid(store["grub"]["path"]) if store else ""
    if store and uuid:
        for s in reversed(snaps):
            if not bootable(lay, top, s):
                continue
            k = f"{store['loader']}/{s['kset']}"
            parts.append(grub_entry(label(s), f"luxos-snapshot-{s['name']}", uuid, f"{k}/vmlinuz",
                                    f"{k}/initramfs.img",
                                    entry_options(base, f"{SNAP_SUBVOL}/{s['name']}", snapshot_params(s["name"]))))
    rs = recovery_snapshot(lay, top, snaps) if store and uuid else None
    if rs:
        k = f"{store['loader']}/{rs['kset']}"
        parts.append(grub_entry("LuxOS Recovery", "luxos-recovery", uuid, f"{k}/vmlinuz", f"{k}/initramfs.img",
                                entry_options(base, f"{SNAP_SUBVOL}/{rs['name']}",
                                              snapshot_params(rs["name"]) + recovery_params(), drop=RECOVERY_DROP)))
    elif os.path.exists(P(RECOVERY_BIN)):
        m = mount_of("/boot")
        buuid = fs_uuid("/boot")
        if m and buuid:
            if m[0] == "/boot":
                rel = ("/" + m[3].strip("/")) if m[1] == "btrfs" and m[3].strip("/") else ""
            else:
                rel = (("/" + m[3].strip("/")) if m[3].strip("/") else "") + "/boot"
            parts.append(grub_entry("LuxOS Recovery", "luxos-recovery", buuid, f"{rel}/vmlinuz-{kernel}",
                                    f"{rel}/initramfs-{kernel}.img",
                                    entry_options(base, system, recovery_params(), drop=RECOVERY_DROP)))
    return "".join(parts)


def write_grub(text):
    path = P(GRUB_CFG)
    if not os.path.isdir(os.path.dirname(path)):
        return False
    try:
        with open(path) as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    care.atomic_write(path, text)
    # grub.cfg nacita luxos-snapshots.cfg (12_luxos_snapshots) - grub-mkconfig jen jednou
    try:
        with open(P(GRUB_MAIN_CFG)) as f:
            sourced = "luxos-snapshots.cfg" in f.read()
    except OSError:
        sourced = True
    if not sourced and care.have("grub-mkconfig"):
        rc, out = sh(["grub-mkconfig", "-o", GRUB_MAIN_CFG], timeout=300)
        if rc != 0:
            care.log(f"grub-mkconfig failed: {out[-500:]}")
    return True


def system_subvol(top=None, snaps=None):
    """Systemovy subvolume, ktery startuje hlavni polozka (obvykle @)."""
    b = booted_snapshot()
    if b and top is not None:
        meta = find(snaps if snaps is not None else list_snapshots(top), b)
        return (meta or {}).get("source") or "@"
    sub = root_info().get("subvol") or ""
    if not sub or sub.startswith(SNAP_SUBVOL + "/"):
        return "@"
    return sub


def sync_boot(top, lay=None, snaps=None):
    """Polozky zavadece podle soucasnych snimku (systemd-boot nebo GRUB)."""
    lay = lay or care.detect_layout()
    snaps = list_snapshots(top) if snaps is None else snaps
    system = system_subvol(top, snaps)
    if lay["kind"] == "sdboot" and lay.get("main"):
        files = sdboot_entries(lay, top, snaps, system)
        write_sdboot(lay, files)
        return sorted(files)
    if lay["kind"] == "grub":
        write_grub(grub_cfg(lay, top, snaps, system, lay["kernel"]))
        return ["grub"]
    return []


# ---- vytvoreni snimku ----------------------------------------------------------------------
def create(top, kind="update", packages=(), now=None, lay=None, build=None):
    """Novy snimek systemoveho subvolumu (jen pro cteni) + sada jadra + popis -> popis."""
    if kind not in KINDS:
        raise ValueError(kind)
    lay = lay or care.detect_layout()
    system = system_subvol(top)
    src = os.path.join(top, system)
    if not BTRFS.is_subvolume(src):
        raise SnapshotError("no_subvolume", system)
    ensure_snap_dir(top)
    name = new_name(top, now)
    kid, kver, overlay = save_kernel(lay, top, lay["kernel"], build=build) if lay["kind"] != "none" else (None, "", False)
    BTRFS.snapshot(src, os.path.join(snap_dir(top), name), readonly=True)
    pk = list(packages)
    meta = {"name": name, "time": care.now(), "kind": kind, "source": system, "kver": kver, "kset": kid,
            "overlay": overlay, "recovery": os.path.exists(P(RECOVERY_BIN)),
            "packages": pk[:20], "count": len(pk), "version": os_version()}
    write_meta(top, meta)
    return meta


def os_version():
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(P(path)) as f:
                for line in f:
                    if line.startswith("VERSION_ID="):
                        return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            continue
    return ""


def pre_transaction(targets, now=None):
    """Hook pred transakci: snimek, uklid, polozky zavadece. Chyba snimku transakci nezastavi;
    pri startu ze snimku se ale transakce odmitne (zmeny by se ztratily a jadro by se zapsalo
    do /boot hlavniho systemu). -> navratovy kod hooku (AbortOnFail)."""
    if in_chroot():
        return 0
    if booted_snapshot():
        return 1
    ok, why = supported()
    if not ok:
        return 0
    try:
        with snapshot_lock(), top_level() as top:
            lay = care.detect_layout()
            meta = create(top, "update", targets, now=now, lay=lay)
            gone = prune(top)
            snaps = list_snapshots(top)
            gc_kernels(lay, top, snaps)
            sync_boot(top, lay, snaps)
        care.log(f"snapshot {meta['name']} of {meta['source']}" + (f" (removed {' '.join(gone)})" if gone else ""))
    except Exception as e:  # noqa: BLE001 - snimek nesmi zastavit aktualizaci
        care.log(f"snapshot before the transaction failed: {e}")
    return 0


# ---- navrat ke snimku ----------------------------------------------------------------------
def main_boot_files(lay):
    """Kam zavadec hlavni polozky cte jadro -> [(cesta, "vmlinuz"|"initramfs")]."""
    k = lay.get("kernel", "")
    out = []
    if lay["kind"] == "sdboot" and lay.get("main"):
        e = _main_entry(lay)
        esp = lay["esp"]
        for linux in (e.get("linux") or [])[:1]:
            out.append((esp + linux, "vmlinuz"))
        for i in e.get("initrd") or []:
            if os.path.basename(i).startswith("initramfs-"):
                out.append((esp + i, "initramfs"))
        fb = os.path.join(os.path.dirname(esp + ((e.get("linux") or ["/x"])[0])), f"initramfs-{k}-fallback.img")
        if os.path.isfile(P(fb)) and (fb, "initramfs") not in out:
            out.append((fb, "initramfs"))
    elif lay["kind"] == "grub" and is_mountpoint("/boot"):
        out.append((f"/boot/vmlinuz-{k}", "vmlinuz"))
        out.append((f"/boot/initramfs-{k}.img", "initramfs"))
        if os.path.isfile(P(f"/boot/initramfs-{k}-fallback.img")):
            out.append((f"/boot/initramfs-{k}-fallback.img", "initramfs"))
    return out


def snapshot_kernel_source(lay, top, meta):
    """Odkud vzit jadro snimku pro hlavni polozku -> (vmlinuz, initramfs) nebo None."""
    d = kset_path(lay, top, meta.get("kset"))
    if d:
        return os.path.join(d, "vmlinuz"), os.path.join(d, "initramfs.img")
    # /boot uvnitr systemu (sdileny ESP: /efi): snimek ma vlastni /boot
    k = lay.get("kernel", "")
    sb = os.path.join(snap_dir(top), meta["name"], "boot")
    v, i = os.path.join(sb, f"vmlinuz-{k}"), os.path.join(sb, f"initramfs-{k}.img")
    if not is_mountpoint("/boot") and os.path.isfile(v) and os.path.isfile(i):
        return v, i
    return None


def copy_boot(files, vml, img):
    for dst, what in files:
        src = vml if what == "vmlinuz" else img
        d = P(dst)
        if os.path.isfile(d) and care._same_file(src, d):
            continue
        os.makedirs(os.path.dirname(d), exist_ok=True)
        tmp = d + ".luxos-new"
        shutil.copyfile(src, tmp)
        os.replace(tmp, d)


def reset_counter(lay):
    """Navrat = znamy dobry stav: hlavni polozka bez pocitadla pokusu (luxos+0-3.conf -> luxos.conf)."""
    if lay["kind"] == "sdboot" and lay.get("main"):
        clean = care.entry_id(lay["main"])
        if clean != lay["main"]:
            os.replace(P(f"{lay['entries']}/{lay['main']}"), P(f"{lay['entries']}/{clean}"))
            lay["main"] = clean
    elif lay["kind"] == "grub" and care.have("grub-editenv"):
        sh(["grub-editenv", care.GRUBENV, "unset", "luxos_tries"], timeout=30)


def db_busy():
    return os.path.exists(P(care.DB_LOCK)) and care.engine_running()


def rollback(top, name, now=None, lay=None, kind="before-rollback", build=None):
    """Snimek `name` se stane systemem (pri pristim startu). Soucasny system se odlozi jako snimek
    `kind`; nic se nemaze. -> dict(target, replaced)."""
    if not NAME_RE.match(name or ""):
        raise SnapshotError("not_found", name)
    lay = lay or care.detect_layout()
    snaps = list_snapshots(top)
    meta = find(snaps, name)
    target = os.path.join(snap_dir(top), name)
    if not meta or not BTRFS.is_subvolume(target):
        raise SnapshotError("not_found", name)
    system = meta.get("source") or system_subvol(top, snaps)
    sys_path = os.path.join(top, system)
    if not BTRFS.is_subvolume(sys_path):
        raise SnapshotError("no_subvolume", system)
    if db_busy():
        raise SnapshotError("busy")
    # Jadro: snimek musi startovat se svym jadrem (jine nez soucasne -> kopie na misto hlavni polozky)
    cur_kid, cur_ver, cur_overlay = save_kernel(lay, top, lay["kernel"], build=build) \
        if lay["kind"] != "none" else (None, "", False)
    files = main_boot_files(lay)
    src = None
    if files and meta.get("kset") != cur_kid:
        src = snapshot_kernel_source(lay, top, meta)
        if not src:
            raise SnapshotError("kernel_missing", meta.get("kver", ""))
    replaced = new_name(top, now)
    os.rename(sys_path, os.path.join(snap_dir(top), replaced))
    try:
        BTRFS.snapshot(target, sys_path, readonly=False)
    except Exception:
        os.rename(os.path.join(snap_dir(top), replaced), sys_path)
        raise
    old_kernel = kset_path(lay, top, cur_kid)
    try:
        if src:
            copy_boot(files, *src)
    except OSError as e:
        # zpet do puvodniho stavu: novy system pryc, puvodni na misto, puvodni jadro
        try:
            BTRFS.delete(sys_path)
        except SnapshotError:
            shutil.rmtree(sys_path, ignore_errors=True)
        os.rename(os.path.join(snap_dir(top), replaced), sys_path)
        if old_kernel:
            copy_boot(files, os.path.join(old_kernel, "vmlinuz"), os.path.join(old_kernel, "initramfs.img"))
        raise SnapshotError("kernel_copy_failed", str(e))
    write_meta(top, {"name": replaced, "time": care.now(), "kind": kind, "source": system, "kver": cur_ver,
                     "kset": cur_kid, "overlay": cur_overlay, "recovery": os.path.exists(P(RECOVERY_BIN)),
                     "packages": [], "count": 0, "version": os_version()})
    flag = {"time": care.now(), "from": replaced, "to": name, "label": label(meta), "kind": kind}
    try:
        care.atomic_write(os.path.join(sys_path, AFTER_ROLLBACK.lstrip("/")), json.dumps(flag) + "\n")
        # Stejna aktualizace by se hned nainstalovala znovu: automaticke aktualizace pockaji
        st_path = os.path.join(sys_path, care.STATE.lstrip("/"))
        try:
            with open(st_path) as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        st["next_attempt"] = care.now() + PAUSE_AFTER_ROLLBACK
        care.atomic_write(st_path, json.dumps(st, indent=1, ensure_ascii=False) + "\n")
    except OSError as e:
        care.log(f"could not write the rollback note: {e}")
    reset_counter(lay)
    snaps = list_snapshots(top)
    gc_kernels(lay, top, snaps)
    sync_boot(top, lay, snaps)
    care.history("rollback", ok=True, to=name, replaced=replaced, kind=kind)
    return {"target": name, "replaced": replaced, "label": label(meta)}


def after_rollback():
    """Prvni start po navratu: novy initramfs (i zalozni) z obnoveneho systemu, zaznam, upozorneni."""
    path = P(AFTER_ROLLBACK)
    try:
        with open(path) as f:
            flag = json.load(f)
    except (OSError, ValueError):
        flag = {}
    try:
        os.unlink(path)
    except OSError:
        pass
    if care.have("mkinitcpio"):
        rc, out = sh(["mkinitcpio", "-P"], timeout=1800)
        if rc != 0:
            care.log(f"mkinitcpio after rollback failed: {out[-500:]}")
    if os.path.exists("/usr/local/sbin/luxos-esp-sync") and not care.ROOT:
        sh(["/usr/local/sbin/luxos-esp-sync"], timeout=300)
    care.history("rollback_done", ok=True, **{k: flag.get(k) for k in ("from", "to", "kind")})
    care.add_event("rolled_back", label=flag.get("label", ""), kind=flag.get("kind", "before-rollback"))
    return 0


# ---- vypis ---------------------------------------------------------------------------------
def describe(top, lay=None):
    lay = lay or care.detect_layout()
    snaps = list_snapshots(top)
    booted = booted_snapshot()
    out = []
    for s in snaps:
        out.append({"name": s["name"], "label": label(s), "kind": s.get("kind"), "time": s.get("time"),
                    "kernel": s.get("kver", ""), "packages": s.get("packages", []), "count": s.get("count", 0),
                    "bootable": bootable(lay, top, s), "booted": s["name"] == booted,
                    "version": s.get("version", "")})
    return out


def status_hint():
    """Pro relaci a Nastaveni (bez roota): system bezi ze snimku? -> dict nebo None."""
    b = booted_snapshot()
    if not b:
        return None
    try:
        t = datetime.datetime.strptime(b, NAME_FMT)
    except ValueError:
        return None
    return {"name": b, "date": t.strftime("%Y-%m-%d %H:%M"), "epoch": int(time.mktime(t.timetuple()))}
