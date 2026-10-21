"""LuxOS - model rucniho rozdeleni disku pro graficky instalator.

Prevadi stav disku (scan) na upravitelny model (oddily, LUKS2, LVM), kontroluje ho
stejnymi kody jako backend (layout.sh, layout_validate) a zapisuje radkovy format LAYOUT
pro  luxos-install --config  (DISK_MODE=layout).

    python3 luxos_layout.py --scan     disky, oddily, LUKS a LVM jako JSON (jako root uplne)

Nic v tomto modulu nemeni disky; jedine "unlock" (otevreni LUKS) dela GUI pres sudo.
"""
import json
import os
import re
import subprocess
import sys

MiB = 1024 ** 2
GiB = 1024 ** 3
ESP_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
BIOS_GUID = "21686148-6449-6e6f-744e-656564454649"
LUKS_HEADER = 16 * MiB
LVM_META = 1 * MiB
EXTENT = 4 * MiB
MIN_ESP = 300 * 1000 * 1000
MIN_ROOT = 8 * GiB
WARN_ROOT = 20 * GiB
MIN_BOOT = 300 * MiB
FSTYPES = ("btrfs", "ext4", "xfs", "f2fs", "vfat")
MOUNTS = ("/", "/home", "/var", "/tmp", "/opt", "/srv", "/var/log", "/boot", "/efi")
FORBIDDEN = {"/usr", "/etc", "/bin", "/sbin", "/lib", "/lib64", "/proc", "/sys", "/dev", "/run", "/boot/efi",
             "/var/lib/pacman"}
RESIZABLE = ("ext4", "btrfs", "ntfs")

# Texty chyb a varovani - stejne anglicke vety jako ly_error_text v layout.sh (spolecne preklady)
MESSAGES = {
    "ref_missing": "The layout refers to %s, which does not exist.",
    "used_twice": "%s is used for two things at once.",
    "bad_size": "Invalid size for %s.",
    "rest_twice": "Only one volume on %s can use the remaining space.",
    "bad_name": "Invalid name for %s.",
    "dup_name": "The name %s is used twice.",
    "no_pvs": "The volume group %s has no physical volumes.",
    "bad_mount": "%s is not a valid mount point.",
    "forbidden_mount": "%s cannot be a separate partition.",
    "dup_mount": "The mount point %s is used twice.",
    "bad_fstype": "Unsupported file system for %s.",
    "root_keep": "The root file system (/) must be formatted.",
    "no_root": "Choose a volume for the root file system (/).",
    "esp_missing": "An EFI system partition (FAT32, at least 300 MB) mounted at /boot or /efi is needed.",
    "esp_not_part": "The EFI system partition must be a plain partition (not encrypted, not LVM).",
    "esp_type": "The partition mounted at /boot or /efi must be an EFI system partition.",
    "esp_fstype": "The EFI system partition must use FAT32.",
    "esp_small": "The EFI system partition must have at least 300 MB.",
    "boot_vfat": "With the EFI partition at /boot, there cannot be another /boot. "
                 "Mount the EFI partition at /efi instead.",
    "boot_encrypted": "The boot loader (GRUB) cannot open encrypted volumes: add an unencrypted /boot partition.",
    "bios_grub_missing": "A BIOS boot partition (1 MB) is needed to start from this disk.",
    "root_small": "The root file system (/) needs at least 8 GB.",
    "root_small_warn": "The root file system (/) has less than 20 GB; apps may not fit.",
    "boot_small": "/boot needs at least 300 MB.",
    "enc_mismatch": "/ and %s are not encrypted the same way: files in the unencrypted one are not protected.",
    "swap_plain": "The swap is not encrypted although / is: memory contents can leak to the disk.",
    "luks_no_pass": "Enter a passphrase for the encrypted volume %s.",
    "unused": "%s is created but not used.",
    "busy": "%s is in use (mounted). Unmount it first.",
    "no_space": "There is not enough free space on %s.",
    "vg_full": "The volume group %s does not have enough free space.",
    "esp_keep_fs": "The kept EFI system partition %s is not FAT32.",
    "esp_keep_small": "The EFI system partition %s is smaller than 300 MB.",
    "locked": "Unlock %s first or choose another volume.",
    "pass_mismatch": "The passphrases do not match.",
    "preset_small": "The disk %s is too small for this layout (it needs at least %s).",
}
WARNINGS = {"root_small_warn", "enc_mismatch", "swap_plain", "unused"}


# ---- scan ---------------------------------------------------------------------------
def _run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _lvm_report(cmd, fields, key):
    out = _run([cmd, "--reportformat", "json", "--units", "b", "--nosuffix", "-o", fields])
    try:
        return json.loads(out or "{}").get("report", [{}])[0].get(key, [])
    except (ValueError, IndexError, AttributeError):
        return []


def _minsize(path, fstype):
    """Nejmensi velikost pro zmenseni (jen cte): ext4 z dumpe2fs, NTFS z ntfsresize --info."""
    if fstype == "ext4":
        out = _run(["dumpe2fs", "-h", path], timeout=20)
        v = dict(re.findall(r"^(Block count|Free blocks|Block size):\s+(\d+)", out, re.M))
        if len(v) == 3:
            used = (int(v["Block count"]) - int(v["Free blocks"])) * int(v["Block size"])
            return int(used * 1.1) + 256 * MiB
    elif fstype == "ntfs":
        out = _run(["ntfsresize", "--info", "--force", "--no-progress-bar", path], timeout=60)
        m = re.search(r"You might resize at (\d+) bytes", out)
        if m:
            return int(m.group(1)) + 256 * MiB
    return 0


def _sys_int(name, attr):
    try:
        with open(f"/sys/class/block/{name}/{attr}") as f:
            return int(f.read())
    except (OSError, ValueError):
        return 0


def _lv_info(lv, vg, dm):
    key = vg.replace("-", "--") + "-" + lv["lv_name"].replace("-", "--")
    d = dm.get(key, {})
    return {"name": lv["lv_name"], "size": int(lv["lv_size"]), "path": lv.get("lv_path") or f"/dev/{vg}/{lv['lv_name']}",
            "fstype": d.get("fstype", ""), "mounts": d.get("mounts", []), "children": d.get("children", [])}


def scan_system(minsizes=True):
    """Disky (vcetne oddilu, LUKS a LVM pod nimi) a skupiny LVM. Bez roota chybi VG a minsize."""
    raw = _run(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,RO,MODEL,TRAN,FSTYPE,LABEL,PARTLABEL,PARTTYPE,"
                "PTTYPE,UUID,MOUNTPOINTS,LOG-SEC"])
    try:
        devices = json.loads(raw or "{}").get("blockdevices", [])
    except ValueError:
        devices = []
    src = _run(["findmnt", "-no", "SOURCE", "/run/archiso/bootmnt"]).strip()
    iso = _run(["lsblk", "-no", "PKNAME", src]).strip().split("\n")[0] if src else ""

    def mounts(d):
        return [m for m in (d.get("mountpoints") or []) if m]

    def child(d):
        out = {"name": d["name"], "path": d.get("path") or "/dev/" + d["name"], "type": d.get("type"),
               "size": int(d.get("size") or 0), "fstype": d.get("fstype") or "", "label": d.get("label") or "",
               "uuid": d.get("uuid") or "", "mounts": mounts(d),
               "children": [child(c) for c in d.get("children") or []]}
        return out

    disks = []
    for d in devices:
        if d.get("type") != "disk" or d.get("ro") in (True, "1", 1):
            continue
        if d["name"].startswith(("zram", "loop", "sr")) or d["name"] == iso:
            continue
        parts = []
        for p in d.get("children") or []:
            if p.get("type") != "part":
                continue
            c = child(p)
            c.update({"start": _sys_int(p["name"], "start"), "partn": _sys_int(p["name"], "partition"),
                      "parttype": (p.get("parttype") or "").lower(),
                      "label": p.get("label") or p.get("partlabel") or ""})
            if minsizes and os.geteuid() == 0 and c["fstype"] in ("ext4", "ntfs") and not c["mounts"]:
                c["minsize"] = _minsize(c["path"], c["fstype"])
            parts.append(c)
        parts.sort(key=lambda p: p["start"])
        disks.append({"path": d.get("path") or "/dev/" + d["name"], "name": d["name"], "size": int(d["size"]),
                      "model": (d.get("model") or "").strip(), "tran": d.get("tran") or "",
                      "pttype": d.get("pttype") or "", "parts": parts,
                      "mounts": mounts(d)})
    # LV z lsblk (obsah, pripojeni, LUKS nad LV) podle jmena v device-mapperu "vg-lv"
    dm = {}

    def walk(d):
        if d.get("type") == "lvm":
            dm[d["name"]] = child(d)
        for c in d.get("children") or []:
            walk(c)
    for d in devices:
        walk(d)
    vgs = []
    if os.geteuid() == 0:
        pvs = _lvm_report("pvs", "pv_name,vg_name", "pv")
        lvs = _lvm_report("lvs", "lv_name,vg_name,lv_size,lv_path,lv_active", "lv")
        for v in _lvm_report("vgs", "vg_name,vg_size,vg_free", "vg"):
            vgs.append({"name": v["vg_name"], "size": int(v["vg_size"]), "free": int(v["vg_free"]),
                        "pvs": [p["pv_name"] for p in pvs if p.get("vg_name") == v["vg_name"]],
                        "lvs": [_lv_info(lv, v["vg_name"], dm) for lv in lvs if lv.get("vg_name") == v["vg_name"]]})
    return {"bootmode": "uefi" if os.path.isdir("/sys/firmware/efi/efivars") else "bios",
            "disks": disks, "vgs": vgs}


def fake_scan(bootmode="uefi"):
    """Vzorove disky pro LUXOS_INSTALL_FAKE=1: Windows + ESP, datovy disk a stary sifrovany LuxOS."""
    gb = 1000 ** 3
    s = 2048
    return {
        "bootmode": bootmode,
        "disks": [
            {"path": "/dev/nvme0n1", "name": "nvme0n1", "size": 512 * gb, "model": "Samsung SSD 980 PRO",
             "tran": "nvme", "pttype": "gpt", "mounts": [],
             "parts": [
                 {"name": "nvme0n1p1", "path": "/dev/nvme0n1p1", "size": 300 * MiB, "start": s, "partn": 1,
                  "fstype": "vfat", "label": "SYSTEM", "parttype": ESP_GUID, "uuid": "1A2B-3C4D", "mounts": [],
                  "children": []},
                 {"name": "nvme0n1p2", "path": "/dev/nvme0n1p2", "size": 16 * MiB, "start": s + 614400, "partn": 2,
                  "fstype": "", "label": "", "parttype": "e3c9e316-0b5c-4db8-817d-f92df00215ae", "uuid": "",
                  "mounts": [], "children": []},
                 {"name": "nvme0n1p3", "path": "/dev/nvme0n1p3", "size": 250 * GiB, "start": s + 647168,
                  "partn": 3, "fstype": "ntfs", "label": "Windows", "parttype": "", "uuid": "", "mounts": [],
                  "children": [], "minsize": 96 * GiB},
                 {"name": "nvme0n1p4", "path": "/dev/nvme0n1p4", "size": 800 * MiB,
                  "start": s + 647168 + 250 * GiB // 512, "partn": 4, "fstype": "ntfs", "label": "",
                  "parttype": "de94bba4-06d1-4d40-a16a-bfd50179d6ac", "uuid": "", "mounts": [], "children": []},
             ]},
            {"path": "/dev/sda", "name": "sda", "size": 1000 * gb, "model": "WDC WD10EZEX", "tran": "sata",
             "pttype": "gpt", "mounts": [],
             "parts": [{"name": "sda1", "path": "/dev/sda1", "size": 1000 * gb - 2 * MiB, "start": s, "partn": 1,
                        "fstype": "ext4", "label": "Data", "parttype": "", "uuid": "", "mounts": [],
                        "children": [], "minsize": 412 * gb}]},
            {"path": "/dev/sdb", "name": "sdb", "size": 256 * gb, "model": "Crucial MX500", "tran": "sata",
             "pttype": "gpt", "mounts": [],
             "parts": [
                 {"name": "sdb1", "path": "/dev/sdb1", "size": 512 * MiB, "start": s, "partn": 1,
                  "fstype": "vfat", "label": "EFI", "parttype": ESP_GUID, "uuid": "9F3E-11AA", "mounts": [],
                  "children": []},
                 {"name": "sdb2", "path": "/dev/sdb2", "size": 256 * gb - 600 * MiB, "start": s + 1048576,
                  "partn": 2, "fstype": "crypto_LUKS", "label": "", "parttype": "", "uuid": "5b7c-luks",
                  "mounts": [], "children": []},
             ]},
        ],
        "vgs": [],
    }


# Obsah zamceneho LUKS ve FAKE rezimu (po odemceni heslem "luxos")
FAKE_UNLOCKED = {
    "/dev/sdb2": {"mapper": "luks-5b7c", "vg": {"name": "oldvg", "size": 238 * GiB, "free": 10 * GiB, "lvs": [
        {"name": "root", "size": 60 * GiB, "fstype": "btrfs"},
        {"name": "home", "size": 168 * GiB, "fstype": "ext4"}]}},
}


# ---- model --------------------------------------------------------------------------
class Node:
    """Disk, oddil, LUKS, VG nebo LV. existing = je na disku uz ted."""

    def __init__(self, kind, nid, **kw):
        self.kind, self.id = kind, nid
        self.existing = False
        self.dev = ""            # cesta existujiciho zarizeni
        self.size = 0            # bajty (nove: pozadovana velikost; rest = True -> zbytek)
        self.rest = False
        self.disk = ""           # oddil: cesta disku
        self.start = 0           # existujici oddil: zacatek (512B sektory)
        self.fstype = ""         # zjisteny obsah existujiciho zarizeni
        self.label = ""
        self.parttype = ""       # GUID existujiciho oddilu
        self.ptype = ""          # novy oddil: esp | bios | (prazdne = podle pouziti)
        self.delete = False
        self.resize = None       # nova velikost existujiciho oddilu
        self.minsize = 0
        self.maxsize = 0
        self.on = ""             # luks: id podkladu
        self.vg = ""             # lv: id skupiny
        self.pvs = []            # vg: id fyzickych svazku
        self.name = ""           # jmeno LUKS mapperu / VG / LV
        self.locked = False      # existujici LUKS, zatim neodemceny
        self.passphrase = ""     # vlastni heslo LUKS (bez spolecneho)
        self.use = None          # {"type": "fs", "mount", "fstype", "format", "subvol"} | {"type": "swap", "format"}
        self.wipe = False        # disk: nova prazdna GPT
        self.mounts = []
        self.model = ""
        self.free = 0            # existujici VG: volne misto
        self.mapper = ""         # otevreny LUKS v live systemu
        for k, v in kw.items():
            setattr(self, k, v)


def _sid(prefix, name):
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return (prefix + s)[:31]


class Layout:
    def __init__(self, scan, bootmode=None):
        self.scan = scan
        self.bootmode = bootmode or scan.get("bootmode", "uefi")
        self.nodes = {}          # id -> Node (poradi = poradi vlozeni)
        self.passphrase = ""     # spolecne heslo
        self.same_pass = True
        self.counter = 0
        self.load()

    # -- nacteni stavu disku --
    def add(self, node):
        self.nodes[node.id] = node
        return node

    def new_id(self, prefix):
        while True:
            self.counter += 1
            nid = f"{prefix}{self.counter}"
            if nid not in self.nodes:
                return nid

    def load(self):
        self.nodes = {}
        by_path = {}
        for d in self.scan.get("disks", []):
            dn = self.add(Node("disk", _sid("d_", d["name"]), existing=True, dev=d["path"], size=d["size"],
                               model=d.get("model", ""), mounts=d.get("mounts", []), fstype=d.get("pttype", "")))
            dn.tran = d.get("tran", "")
            for p in d.get("parts", []):
                pn = self.add(Node("part", _sid("x_", p["name"]), existing=True, dev=p["path"], size=p["size"],
                                   disk=d["path"], start=p.get("start", 0), fstype=p.get("fstype", ""),
                                   label=p.get("label", ""), parttype=p.get("parttype", ""),
                                   minsize=p.get("minsize", 0), mounts=self._all_mounts(p)))
                pn.partn = p.get("partn", 0)
                by_path[p["path"]] = pn
                self._load_children(pn, p, by_path)
        for v in self.scan.get("vgs", []):
            self._load_vg(v, by_path)

    @staticmethod
    def _all_mounts(dev):
        out = list(dev.get("mounts") or [])
        for c in dev.get("children") or []:
            out += Layout._all_mounts(c)
        return out

    def _load_children(self, base, dev, by_path):
        """LUKS pod oddilem/LV (otevreny = ma potomka typu crypt)."""
        if base.fstype != "crypto_LUKS":
            return
        crypt = next((c for c in dev.get("children") or [] if c.get("type") == "crypt"), None)
        ln = self.add(Node("luks", _sid("c_", base.dev.rsplit("/", 1)[-1]), existing=True, on=base.id,
                           size=max(base.size - LUKS_HEADER, 0), locked=crypt is None,
                           mounts=self._all_mounts(dev)))
        if crypt:
            ln.mapper = crypt["path"]
            ln.dev = crypt["path"]
            ln.fstype = crypt.get("fstype", "")
            by_path[crypt["path"]] = ln

    def _load_vg(self, v, by_path):
        vg = self.add(Node("vg", _sid("v_", v["name"]), existing=True, name=v["name"], size=v["size"],
                           free=v["free"], dev="/dev/" + v["name"]))
        vg.pvs = [by_path[p].id for p in v.get("pvs", []) if p in by_path]
        for lv in v.get("lvs", []):
            ln = self.add(Node("lv", _sid("l_", f"{v['name']}_{lv['name']}"), existing=True, vg=vg.id,
                               name=lv["name"], size=lv["size"], dev=lv.get("path", ""),
                               fstype=lv.get("fstype", ""), mounts=self._all_mounts(lv)))
            by_path[ln.dev] = ln
            self._load_children(ln, lv, by_path)

    def unlock_fake(self, luks_id):
        """FAKE: odemceni ukazkoveho LUKS (obsah z FAKE_UNLOCKED) jako by ho ukazal novy scan."""
        import copy
        ln = self.nodes[luks_id]
        base = self.nodes[ln.on]
        info = FAKE_UNLOCKED.get(base.dev, {"mapper": "luks-" + ln.id})
        scan = copy.deepcopy(self.scan)
        mapper = "/dev/mapper/" + info["mapper"]
        for d in scan["disks"]:
            for p in d["parts"]:
                if p["path"] == base.dev:
                    p["children"] = [{"name": info["mapper"], "path": mapper, "type": "crypt",
                                      "size": p["size"] - LUKS_HEADER, "fstype": "LVM2_member" if info.get("vg") else "",
                                      "label": "", "uuid": "", "mounts": [], "children": []}]
        if info.get("vg"):
            v = info["vg"]
            scan["vgs"].append({"name": v["name"], "size": v["size"], "free": v["free"], "pvs": [mapper],
                                "lvs": [{"name": lv["name"], "size": lv["size"],
                                         "path": f"/dev/{v['name']}/{lv['name']}", "fstype": lv.get("fstype", ""),
                                         "mounts": [], "children": []} for lv in v["lvs"]]})
        self.merge_scan(scan)

    # -- dotazy --
    def of(self, kind):
        return [n for n in self.nodes.values() if n.kind == kind]

    def consumers(self, nid):
        """Kdo stoji na objektu: LUKS (on), VG (pvs), LV (vg)."""
        out = []
        for n in self.nodes.values():
            if n.kind == "luks" and n.on == nid:
                out.append(n)
            elif n.kind == "vg" and nid in n.pvs:
                out.append(n)
            elif n.kind == "lv" and n.vg == nid:
                out.append(n)
        return out

    def parts_of(self, disk_path):
        return [n for n in self.nodes.values() if n.kind == "part" and n.disk == disk_path]

    def lvs_of(self, vg_id):
        return [n for n in self.nodes.values() if n.kind == "lv" and n.vg == vg_id]

    def is_free_block(self, n):
        """Lze pouzit (fs, swap, LUKS, PV): oddil/LV/LUKS bez pouziti a bez neceho nad sebou."""
        if n.kind not in ("part", "lv", "luks") or n.delete or n.use:
            return False
        if n.kind == "luks" and n.locked:
            return False
        if n.kind == "part" and (n.ptype in ("esp", "bios") or self.is_esp_part(n) or n.parttype == BIOS_GUID):
            return False
        return not self.consumers(n.id)

    def ancestors(self, n):
        """Objekt a vse pod nim (oddil <- LUKS <- VG <- LV ...)."""
        out, todo, seen = [], [n], set()
        while todo:
            x = todo.pop(0)
            if x is None or x.id in seen:
                continue
            seen.add(x.id)
            out.append(x)
            if x.kind == "luks":
                todo.append(self.nodes.get(x.on))
            elif x.kind == "lv":
                todo.append(self.nodes.get(x.vg))
            elif x.kind == "vg":
                todo += [self.nodes.get(p) for p in x.pvs]
        return out

    def encrypted(self, n):
        return any(a.kind == "luks" for a in self.ancestors(n))

    def users(self):
        """Uzly s pouzitim (fs/swap)."""
        return [n for n in self.nodes.values() if n.use and not n.delete]

    def by_mount(self, mp):
        return next((n for n in self.users() if n.use["type"] == "fs" and n.use["mount"] == mp), None)

    def esp(self):
        return next((n for n in self.users() if n.use["type"] == "fs" and n.use.get("fstype") == "vfat"
                     and n.use["mount"] in ("/boot", "/efi")), None)

    def is_esp_part(self, n):
        return n.kind == "part" and (n.ptype == "esp" or n.parttype == ESP_GUID)

    # -- velikosti a volne misto --
    def regions(self, disk_path):
        """Volne oblasti disku (zacatek, delka v bajtech) po smazani/zmene existujicich oddilu."""
        d = self.disk_node(disk_path)
        first, last = 2048 * 512, d.size - 34 * 512
        if d.wipe:
            return [(first, last - first)]
        used = []
        for p in self.parts_of(disk_path):
            if p.existing and not p.delete:
                start = p.start * 512 if p.start else first
                used.append((start, p.resize if p.resize else p.size))
        used.sort()
        # zacatek volne oblasti zarovnany na 1 MiB (sgdisk), stejne jako ly_alloc_disk v layout.sh
        out, pos = [], first
        for s, ln in used:
            a = -(-pos // MiB) * MiB
            if s - a >= MiB:
                out.append((a, s - a))
            pos = max(pos, s + ln)
        a = -(-pos // MiB) * MiB
        if last - a >= MiB:
            out.append((a, last - a))
        return out

    def allocate(self, disk_path):
        """Simulace sgdisk: nove oddily s pevnou velikosti do nejvetsi oblasti, pak "rest".
        -> ({id: velikost}, zbyvajici oblasti, chybejici misto)"""
        regs = [list(r) for r in self.regions(disk_path)]
        sizes, short = {}, 0
        new = [p for p in self.parts_of(disk_path) if not p.existing]
        for p in [p for p in new if not p.rest] + [p for p in new if p.rest]:
            if not regs:
                short += p.size if not p.rest else MiB   # ani "zbytek" nema kam
                sizes[p.id] = 0
                continue
            k = max(range(len(regs)), key=lambda i: regs[i][1])
            want = regs[k][1] if p.rest else -(-p.size // MiB) * MiB
            if want > regs[k][1]:
                short += want - regs[k][1]
                want = regs[k][1]
            sizes[p.id] = want
            regs[k][0] += want
            regs[k][1] -= want
            regs = [r for r in regs if r[1] >= MiB]
        return sizes, [tuple(r) for r in regs], short

    def disk_node(self, path):
        return next(n for n in self.nodes.values() if n.kind == "disk" and n.dev == path)

    def size_of(self, n):
        """Skutecna/ocekavana velikost (bajty) - pro nove oddily podle simulace, pro LV podle VG."""
        if n is None:
            return 0
        if n.kind == "part":
            if n.existing:
                return n.resize or n.size
            return self.allocate(n.disk)[0].get(n.id, n.size)
        if n.kind == "luks":
            return max(self.size_of(self.nodes.get(n.on)) - LUKS_HEADER, 0)
        if n.kind == "vg":
            if n.existing:
                return n.size
            total = 0
            for p in n.pvs:
                s = self.size_of(self.nodes.get(p)) - LVM_META
                total += max(s // EXTENT * EXTENT, 0)
            return total
        if n.kind == "lv":
            if n.existing or not n.rest:
                return n.size
            return self.vg_alloc(n.vg)[0].get(n.id, 0)
        return n.size

    def vg_alloc(self, vg_id):
        """-> ({lv id: velikost}, volne, chybejici)"""
        vg = self.nodes[vg_id]
        lvs = [lv for lv in self.lvs_of(vg_id) if not lv.delete]
        if vg.existing:
            free = vg.free + sum(lv.size for lv in self.lvs_of(vg_id) if lv.delete and lv.existing)
        else:
            free = self.size_of(vg)
        sizes, short = {}, 0
        for lv in lvs:
            if lv.existing or lv.rest:
                continue
            want = -(-lv.size // EXTENT) * EXTENT
            sizes[lv.id] = want
            if want > free:
                short += want - free
            free = max(free - want, 0)
        for lv in lvs:
            if lv.rest and not lv.existing:
                if free < EXTENT:
                    short += EXTENT   # na "zbytek" nezbyl ani jeden extent
                sizes[lv.id] = free
                free = 0
        return sizes, free, short

    # -- upravy --
    def remove(self, nid):
        """Smazat novy objekt (s tim, co na nem stoji) nebo oznacit existujici oddil/LV ke smazani."""
        n = self.nodes.get(nid)
        if n is None:
            return
        if n.kind == "vg":
            # skupina zanikne i se vsemi LV (existujici LV se nemazou zvlast, zmizi s ni)
            for lv in self.lvs_of(nid):
                self.drop(lv.id)
            del self.nodes[nid]
            return
        for c in self.consumers(nid):
            if c.kind == "vg" and not c.existing and len(c.pvs) > 1:
                c.pvs = [p for p in c.pvs if p != nid]
            else:
                self.remove(c.id)
        if n.existing and n.kind in ("part", "lv"):
            n.delete, n.use, n.resize = True, None, None
        else:
            del self.nodes[nid]

    def drop(self, nid):
        """Objekt zmizi z planu i se vsim nad nim (zanika s podkladem, nic se nemaze zvlast)."""
        if nid not in self.nodes:
            return
        for c in self.consumers(nid):
            if c.kind == "vg" and not c.existing and len(c.pvs) > 1:
                c.pvs = [p for p in c.pvs if p != nid]
            else:
                self.drop(c.id)
        if self.nodes[nid].kind == "vg":
            for lv in self.lvs_of(nid):
                self.drop(lv.id)
        self.nodes.pop(nid, None)

    def restore(self, nid):
        n = self.nodes[nid]
        n.delete = False

    def wipe_disk(self, path, on=True):
        """Cely disk smazat (nova GPT) - existujici oddily a vse na nich zmizi z planu."""
        d = self.disk_node(path)
        if on:
            for p in self.parts_of(path):
                if p.existing:
                    self.drop(p.id)
                else:
                    self.remove(p.id)
            d.wipe = True
        else:
            self.scan_restore_disk(path)

    def scan_restore_disk(self, path):
        """Vratit disk do stavu ze scanu (nove oddily na nem zahodit)."""
        for p in self.parts_of(path):
            if p.existing:
                self.drop(p.id)
            else:
                self.remove(p.id)
        self.disk_node(path).wipe = False
        self.merge_scan(self.scan)

    def merge_scan(self, scan):
        """Doplnit objekty z noveho scanu (napr. po odemceni LUKS), upravy v planu zustanou."""
        self.scan = scan
        fresh = Layout(scan, self.bootmode)
        wiped = {d.dev for d in self.of("disk") if d.wipe}
        for nid, n in fresh.nodes.items():
            if n.kind == "part" and n.disk in wiped:
                continue
            if any(a.kind == "part" and a.disk in wiped for a in fresh.ancestors(n)):
                continue
            old = self.nodes.get(nid)
            if old is None:
                if n.kind == "lv" and n.vg not in self.nodes and n.vg not in fresh.nodes:
                    continue
                self.nodes[nid] = n
            elif old.kind == "luks" and old.locked and not n.locked:
                old.locked, old.mapper, old.dev, old.fstype = False, n.mapper, n.dev, n.fstype

    def add_part(self, disk_path, size=0, rest=False, ptype=""):
        d = self.disk_node(disk_path)
        n = self.add(Node("part", self.new_id("p"), disk=d.dev, size=size, rest=rest, ptype=ptype))
        return n

    def encrypt(self, nid, on=True):
        """Zapnout/vypnout LUKS2 nad objektem; pouziti (fs/swap/PV) se presune nahoru/dolu."""
        n = self.nodes[nid]
        if on:
            ln = self.add(Node("luks", self.new_id("c"), on=nid))
            ln.use, n.use = n.use, None
            for vg in self.of("vg"):
                if nid in vg.pvs:
                    vg.pvs = [ln.id if p == nid else p for p in vg.pvs]
            return ln
        top = next((c for c in self.consumers(nid) if c.kind == "luks" and not c.existing), None)
        if top is None:
            return n
        n.use, top.use = top.use, None
        for vg in self.of("vg"):
            if top.id in vg.pvs:
                vg.pvs = [nid if p == top.id else p for p in vg.pvs]
        del self.nodes[top.id]
        return n

    def luks_on(self, nid):
        return next((c for c in self.consumers(nid) if c.kind == "luks"), None)

    def set_use(self, nid, use):
        """Pouziti objektu; existujici obsah (LUKS/VG nad nim) pri formatovani zanikne."""
        n = self.nodes[nid]
        if use is not None:
            for c in self.consumers(nid):
                if c.existing and c.kind in ("luks", "vg"):
                    self.remove(c.id)
        n.use = use

    def add_vg(self, name, pv_ids):
        vg = self.add(Node("vg", self.new_id("vg"), name=name, pvs=list(pv_ids)))
        for p in pv_ids:
            self.nodes[p].use = None
            for c in self.consumers(p):
                if c.existing and c.kind in ("luks", "vg") and c is not vg:
                    self.remove(c.id)
        return vg

    def add_lv(self, vg_id, name, size=0, rest=False, use=None):
        lv = self.add(Node("lv", self.new_id("lv"), vg=vg_id, name=name, size=size, rest=rest))
        lv.use = use
        return lv

    def free_vg_name(self, base="luxos"):
        names = {v.name for v in self.of("vg")}
        if base not in names:
            return base
        i = 2
        while f"{base}{i}" in names:
            i += 1
        return f"{base}{i}"

    # -- automaticka jmena LUKS --
    def luks_names(self):
        """Jmena mapperu pro crypttab: cryptroot, crypthome, cryptswap, cryptlvm…"""
        names, used = {}, set()
        for n in self.of("luks"):
            if n.name:
                names[n.id] = n.name
                used.add(n.name)
        for n in self.of("luks"):
            if n.id in names:
                continue
            if n.use and n.use["type"] == "swap":
                base = "cryptswap"
            elif n.use:
                mp = n.use["mount"]
                base = "cryptroot" if mp == "/" else "crypt" + re.sub(r"[^a-z0-9]", "", mp.rsplit("/", 1)[-1])
            elif any(n.id in v.pvs for v in self.of("vg")):
                base = "cryptlvm"
            else:
                base = "cryptdata"
            name, i = base, 2
            while name in used:
                name, i = f"{base}{i}", i + 1
            used.add(name)
            names[n.id] = name
        return names

    def pass_for(self, n):
        """Heslo LUKS: existujici = heslo z odemceni, nove = spolecne nebo vlastni."""
        if n.existing:
            return n.passphrase or self.passphrase
        if self.same_pass:
            return self.passphrase
        return n.passphrase or self.passphrase

    def random_swap(self, n):
        """LUKS jen pro swap a nesifrovany / -> nahodny klic (backend ly_random_swap)."""
        root = self.by_mount("/")
        return (n.kind == "luks" and not n.existing and n.use and n.use["type"] == "swap"
                and not (root and self.encrypted(root)))

    # -- kontrola (kody jako layout_validate + velikosti a zarizeni) --
    def validate(self, bootloader="auto"):
        """-> [(uroven "error"/"warn", kod, detail)]"""
        out = []

        def err(code, d=""):
            out.append(("warn" if code in WARNINGS else "error", code, d))
        users = self.users()
        mounts = {}
        for n in users:
            if n.use["type"] != "fs":
                continue
            mp, t = n.use["mount"], n.use.get("fstype", "btrfs")
            if not re.fullmatch(r"/|(/[A-Za-z0-9._+-]+)+", mp) or re.search(r"/\.\.?(/|$)", mp):
                err("bad_mount", mp)
            elif mp in FORBIDDEN:
                err("forbidden_mount", mp)
            if mp in mounts:
                err("dup_mount", mp)
            mounts[mp] = n
            if t not in FSTYPES or (t == "vfat" and mp in ("/", "/home", "/var", "/tmp", "/opt", "/srv", "/var/log")):
                err("bad_fstype", mp)
            if mp == "/" and not n.use.get("format", True):
                err("root_keep")
            if mp == "/efi" and t != "vfat":
                err("esp_fstype", "/efi")
        for n in self.nodes.values():
            if n.kind == "luks" and n.locked and (n.use or self.consumers(n.id)):
                err("locked", self.label(n))
        for n in users:
            if any(a.kind == "luks" and a.locked for a in self.ancestors(n)):
                err("locked", self.label(n))
        root = mounts.get("/")
        if root is None:
            err("no_root")
        esp = self.esp()
        if self.bootmode == "uefi" and bootloader != "none":
            if esp is None:
                err("esp_missing")
            else:
                if esp.kind != "part":
                    err("esp_not_part")
                elif not esp.existing and esp.ptype != "esp":
                    err("esp_type")
                elif esp.existing and not self.is_esp_part(esp):
                    err("esp_type")
                if esp.kind == "part":
                    size = self.size_of(esp)
                    if esp.existing and not esp.use.get("format", True):
                        if esp.fstype != "vfat":
                            err("esp_keep_fs", esp.dev)
                        if size < MIN_ESP:
                            err("esp_keep_small", esp.dev)
                    elif size and size < MIN_ESP:
                        err("esp_small")
                if esp.use["mount"] == "/boot" and "/efi" in mounts:
                    err("dup_mount", "/efi")
            boot = mounts.get("/boot")
            if boot is not None and boot is not esp and (esp is None or esp.use["mount"] != "/efi"):
                err("boot_vfat")
        elif self.bootmode == "bios" and bootloader != "none":
            boot = mounts.get("/boot") or root
            if boot is not None and self.encrypted(boot):
                err("boot_encrypted")
            has_bios = any(p.kind == "part" and not p.delete and
                           (p.ptype == "bios" or p.parttype == BIOS_GUID) for p in self.nodes.values())
            if not has_bios:
                err("bios_grub_missing")
        if root is not None:
            s = self.size_of(root)
            if 0 < s < MIN_ROOT:
                err("root_small")
            elif 0 < s < WARN_ROOT:
                err("root_small_warn")
        boot = mounts.get("/boot")
        if boot is not None and boot is not esp and 0 < self.size_of(boot) < MIN_BOOT:
            err("boot_small")
        if root is not None:
            renc = self.encrypted(root)
            home = mounts.get("/home")
            if home is not None and self.encrypted(home) != renc:
                err("enc_mismatch", "/home")
            if renc:
                for n in users:
                    if n.use["type"] == "swap" and not self.encrypted(n):
                        err("swap_plain")
        # Jmena
        names = self.luks_names()
        seen = set()
        for nid, name in names.items():
            if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,40}", name):
                err("bad_name", name)
            if name in seen:
                err("dup_name", name)
            seen.add(name)
        vgn = set()
        for v in self.of("vg"):
            if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_+.-]{0,60}", v.name or ""):
                err("bad_name", v.name)
            if v.name in vgn:
                err("dup_name", v.name)
            vgn.add(v.name)
            if not v.existing and not v.pvs:
                err("no_pvs", v.name)
            lvn = set()
            for lv in self.lvs_of(v.id):
                if lv.delete:
                    continue
                if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_+.-]{0,60}", lv.name or ""):
                    err("bad_name", lv.name)
                if lv.name in lvn:
                    err("dup_name", lv.name)
                lvn.add(lv.name)
            if [lv for lv in self.lvs_of(v.id) if lv.rest and not lv.existing][1:]:
                err("rest_twice", v.name)
            if self.vg_alloc(v.id)[2] > 0:
                err("vg_full", v.name)
        for d in self.of("disk"):
            new = [p for p in self.parts_of(d.dev) if not p.existing]
            if [p for p in new if p.rest][1:]:
                err("rest_twice", d.dev)
            if new and self.allocate(d.dev)[2] > 0:
                err("no_space", d.dev)
        # Pouzivana zarizeni v live systemu (pripojena, swap)
        for n in self.nodes.values():
            if not n.existing or not n.mounts:
                continue
            if self.destroys(n):
                err("busy", n.dev or self.label(n))
        # Hesla
        for n in self.of("luks"):
            if self.random_swap(n) or n.existing and not (n.use or self.consumers(n.id)):
                continue
            if not self.pass_for(n):
                err("luks_no_pass", names.get(n.id, n.id))
        # Nepouzite nove objekty
        for n in self.nodes.values():
            if n.kind in ("part", "lv", "luks") and not n.existing and not n.use and not self.consumers(n.id) \
                    and n.ptype not in ("esp", "bios"):
                err("unused", self.label(n))
        return out

    def destroys(self, n):
        """Bude objekt (nebo jeho obsah) prepsan/smazan?"""
        if n.kind == "disk":
            return n.wipe
        if n.kind == "part" and n.existing:
            if n.delete or n.resize:
                return True
            if self.disk_node(n.disk).wipe:
                return True
        if n.existing and n.use and n.use.get("format", True):
            return True
        if n.existing and n.kind in ("part", "lv"):
            for c in self.consumers(n.id):
                if not c.existing:
                    return True
        return False

    def label(self, n):
        if n.kind == "luks":
            return self.luks_names().get(n.id) or n.id
        if n.kind == "lv":
            vg = self.nodes.get(n.vg)
            return f"{vg.name if vg else '?'}/{n.name}"
        if n.kind == "vg":
            return n.name
        if n.dev:
            return n.dev
        if n.kind == "part":
            return f"{n.disk} (new)"
        return n.id

    # -- vystup --
    def destroy_list(self):
        """[(text, argumenty)] - co se smaze/zmeni (anglicke vety k prekladu)."""
        out = []
        for d in self.of("disk"):
            if d.wipe:
                out.append(("ERASE the whole disk %s", (d.dev,)))
        for n in self.nodes.values():
            if n.kind == "part" and n.existing and not self.disk_node(n.disk).wipe:
                if n.delete:
                    out.append(("DELETE partition %s", (n.dev,)))
                    continue
                if n.resize:
                    out.append(("Resize %s to %s", (n.dev, size_spec(n.resize))))
            if n.kind == "lv" and n.existing and n.delete:
                out.append(("DELETE logical volume %s", (self.label(n),)))
                continue
            if n.existing and n.kind in ("part", "lv") and not n.delete:
                if n.kind == "part" and self.disk_node(n.disk).wipe:
                    continue
                for c in self.consumers(n.id):
                    if not c.existing and c.kind == "luks":
                        out.append(("ERASE %s (new encrypted volume)", (n.dev,)))
                    elif not c.existing and c.kind == "vg":
                        out.append(("ERASE %s (new LVM physical volume)", (n.dev,)))
                if n.use and n.use.get("format", True):
                    out.append(("FORMAT %s", (n.dev,)))
        return out

    def needed(self):
        """Objekty, ktere patri do LAYOUT: vse nove + existujici pod pouzitymi."""
        keep = set()
        for n in self.nodes.values():
            if not n.existing and n.kind != "disk":
                for a in self.ancestors(n):
                    keep.add(a.id)
        for n in self.users():
            for a in self.ancestors(n):
                keep.add(a.id)
        return keep

    def to_text(self):
        """Radkovy LAYOUT pro backend (poradi: disky, pouzite/zmenene/smazane, nove oddily, LUKS, VG, LV, fs)."""
        lines, need, names = [], self.needed(), self.luks_names()
        for d in self.of("disk"):
            if d.wipe:
                lines.append(f"disk dev={d.dev} table=new")
        for n in self.nodes.values():
            if n.kind == "part" and n.existing and not self.disk_node(n.disk).wipe:
                if n.delete:
                    lines.append(f"delete dev={n.dev}")
                elif n.id in need or n.resize:
                    lines.append(f"use id={n.id} dev={n.dev}" + (f" resize={size_spec(n.resize)}" if n.resize else ""))
            elif n.kind == "lv" and n.existing:
                if n.delete:
                    lines.append(f"delete dev={n.dev}")
        for n in self.nodes.values():
            if n.kind == "part" and not n.existing:
                t = n.ptype or {"swap": "swap"}.get((n.use or {}).get("type"), "")
                lines.append(f"part id={n.id} disk={n.disk} size={'rest' if n.rest else size_spec(n.size)}"
                             + (f" type={t}" if t else ""))
        # LUKS a LVM v poradi zavislosti (LUKS na LV az po LV)
        done = set(x.id for x in self.nodes.values() if x.kind == "part")
        pending = [n for n in self.nodes.values() if n.kind in ("luks", "vg", "lv") and n.id in need and not n.delete]
        while pending:
            progress = False
            for n in list(pending):
                deps = {"luks": [n.on], "vg": [] if n.existing else n.pvs, "lv": [n.vg]}[n.kind]
                if all(d in done for d in deps):
                    if n.kind == "luks":
                        lines.append(f"luks id={n.id} on={n.on} name={names[n.id]}" + (" keep=1" if n.existing else ""))
                    elif n.kind == "vg":
                        lines.append(f"vg id={n.id} name={n.name}" +
                                     (" keep=1" if n.existing else f" pvs={','.join(n.pvs)}"))
                    else:
                        lines.append(f"lv id={n.id} vg={n.vg} name={n.name}" +
                                     (" keep=1" if n.existing else f" size={'rest' if n.rest else size_spec(n.size)}"))
                    done.add(n.id)
                    pending.remove(n)
                    progress = True
            if not progress:   # neplatna reference - backend ji nahlasi
                for n in pending:
                    lines.append(f"# unresolved {n.kind} {n.id}")
                break
        for n in sorted(self.users(), key=lambda n: (n.use["type"] != "fs", n.use.get("mount", ""))):
            u = n.use
            if u["type"] == "fs":
                line = f"fs on={n.id} mount={u['mount']} type={u.get('fstype', 'btrfs')}"
                if not u.get("format", True):
                    line += " format=0"
                    if u.get("subvol"):
                        line += f" subvol={u['subvol']}"
                lines.append(line)
            else:
                lines.append(f"swap on={n.id}" + ("" if u.get("format", True) else " format=0"))
        return "\n".join(lines) + "\n"

    def config_values(self):
        """Promenne konfigurace backendu (vcetne hesel - jen pres stdin)."""
        vals = {"DISK": "layout", "DISK_MODE": "layout", "LAYOUT": self.to_text(), "ENCRYPT": "0",
                "LUKS_PASS": self.passphrase}
        for n in self.of("luks"):
            p = self.pass_for(n)
            if p and p != self.passphrase:
                vals["LUKS_PASS_" + n.id.upper()] = p
        return vals

    # -- predvolby --
    def preset(self, disk_path, kind, ram=0):
        """kind: "lvm" = sifrovane LVM (/, /home, swap); "lvm_var" = navic /var a /tmp.

        Velikosti se prizpusobi skutecne velikosti skupiny LVM (stejny vypocet jako LVM: LUKS2 hlavicka,
        metadata PV, extenty). Na prilis malem disku vyjimka PresetTooSmall a plan zustane beze zmeny."""
        import copy
        saved = (copy.deepcopy(self.nodes), self.counter)
        self.wipe_disk(disk_path)
        if self.bootmode == "uefi":
            esp = self.add_part(disk_path, 1 * GiB, ptype="esp")
            esp.use = {"type": "fs", "mount": "/boot", "fstype": "vfat", "format": True}
        else:
            self.add_part(disk_path, 1 * MiB, ptype="bios")
            boot = self.add_part(disk_path, 1 * GiB)
            boot.use = {"type": "fs", "mount": "/boot", "fstype": "ext4", "format": True}
        pv = self.add_part(disk_path, rest=True)
        ln = self.encrypt(pv.id)
        ln.name = "cryptlvm"
        vg = self.add_vg(self.free_vg_name("luxos"), [ln.id])
        vgsize = self.size_of(vg)
        swap = 4 * GiB if vgsize >= 64 * GiB else 2 * GiB
        if ram:
            swap = min(max(swap, ram // GiB * GiB), 8 * GiB)
        swap = min(swap, max(GiB, int(vgsize * 0.1) // GiB * GiB))   # na malem disku swap nesmi ubrat /home

        def clamp(x, lo, hi):
            return int(min(max(x, lo), hi)) // GiB * GiB
        fs = {"type": "fs", "fstype": "btrfs", "format": True}
        # (jmeno, chtena velikost, nejmensi, pouziti); /home dostane zbytek (nejmene PRESET_MIN_HOME)
        if kind == "lvm_var":
            want = [("root", clamp(vgsize * 0.25, 16 * GiB, 60 * GiB), 8 * GiB, dict(fs, mount="/")),
                    ("var", clamp(vgsize * 0.15, 8 * GiB, 40 * GiB), 2 * GiB, dict(fs, mount="/var")),
                    ("tmp", 4 * GiB, 1 * GiB, dict(fs, mount="/tmp", fstype="ext4")),
                    ("swap", swap, 1 * GiB, {"type": "swap", "format": True})]
        else:
            want = [("root", clamp(vgsize * 0.35, 20 * GiB, 100 * GiB), 8 * GiB, dict(fs, mount="/")),
                    ("swap", swap, 1 * GiB, {"type": "swap", "format": True})]
        budget = vgsize - PRESET_MIN_HOME
        mins = sum(w[2] for w in want)
        wants = sum(w[1] for w in want)
        if mins > budget:
            need_vg = mins + PRESET_MIN_HOME
            d = self.disk_node(disk_path)
            need = d.size + (need_vg - vgsize)
            self.nodes, self.counter = saved
            raise PresetTooSmall(disk_path, need)
        sizes = [w[1] for w in want]
        if wants > budget:
            # zmensit vse mezi nejmensi a chtenou velikosti stejnym dilem (cele GiB, aspon minimum)
            t = (budget - mins) / (wants - mins)
            sizes = [max(w[2], int(w[2] + (w[1] - w[2]) * t) // GiB * GiB) for w in want]
        for (name, _w, _m, use), size in zip(want, sizes):
            self.add_lv(vg.id, name, size, use=use)
        self.add_lv(vg.id, "home", rest=True, use=dict(fs, mount="/home"))
        return vg


class PresetTooSmall(Exception):
    """Disk je pro predvolbu prilis maly: .disk, .need (bajty celeho disku)."""

    def __init__(self, disk, need):
        super().__init__(disk)
        self.disk, self.need = disk, need


PRESET_MIN_HOME = 2 * GiB


def size_spec(b):
    """Bajty -> zapis pro LAYOUT (M, G)."""
    b = int(b)
    if b % GiB == 0:
        return f"{b // GiB}G"
    return f"{-(-b // MiB)}M"


def _(s):   # nahradi GUI prekladem (modul je pouzitelny i bez GUI)
    return s


def message(code, detail="", tr=None):
    tr = tr or _
    text = tr(MESSAGES.get(code, code + " %s"))
    return text % detail if "%s" in text else text


if __name__ == "__main__":
    if sys.argv[1:] == ["--scan"]:
        json.dump(scan_system(), sys.stdout)
        print()
    else:
        print(__doc__)
