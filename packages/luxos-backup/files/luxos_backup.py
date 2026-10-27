"""LuxOS Zalohy - jadro: prirustkove zalohy domovske slozky na externi nebo sitovy disk.

Bez GTK (pouziva ho prikaz luxos-backup, sluzba s casovacem i okno Zalohy).

Rozlozeni na disku zaloh (stejne pro vsechny zpusoby, aby obnova i z LuxOS Recovery
nebo z instalatoru vystacila s jednou slozkou):

    <disk>/LuxOS-Backups/<pocitac>-<uzivatel>/
        backup.json                         kdo a odkud zalohuje
        2026-10-26-140000/                  jedna zaloha (cas UTC)
            home/...                        domovska slozka
            system/etc/..., packages.txt    volitelne nastaveni systemu a seznam baliku
            info.json
        2026-10-26-150000.partial/          rozpracovana zaloha (dokonci se pristi beh)
        .current/                           jen btrfs: pracovni podsvazek

Zpusoby (engine):
  btrfs   disk zaloh je btrfs: rsync --inplace do podsvazku .current a pak snimek jen pro
          cteni (kopie pri zapisu, sdileji se i nezmenene casti velkych souboru). Bez roota.
  rsync   ostatni souborove systemy s pevnymi odkazy: kazda zaloha je slozka, nezmenene
          soubory jsou pevne odkazy na predchozi zalohu (--link-dest).
  python  totez bez rsync (nouzove prostredi); jen pro mistni disky.
  sftp    rsync pres ssh s --link-dest na serveru (heslo v klicence, SSH_ASKPASS).
Sitova slozka SMB: soubor obrazu disku na sdileni (gvfs) pripojeny jako smycka, dal jako
mistni disk btrfs (pevne odkazy ani snimky pres SMB nejdou).

Proc ne btrfs send/receive: podsvazek @home obsahuje domovy vsech uzivatelu, send neumi
vynechat slozky (~/.cache) a potrebuje roota na obou stranach. Snimky na disku zaloh daji
stejnou uspornost bez roota a s vyjimkami.

Promenne pro testy: LUXOS_BACKUP_HOME (zalohovana slozka), LUXOS_BACKUP_HOST,
XDG_CONFIG_HOME, XDG_STATE_HOME, LUXOS_BACKUP_NO_NOTIFY=1, LUXOS_BACKUP_ENGINE (vynuti zpusob),
LUXOS_SYSROOT (koren pro /sys a /run).
"""
import contextlib
import datetime
import errno
import fcntl
import fnmatch
import getpass
import json
import os
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import time

sys.path.insert(0, "/usr/lib/luxos/python")
try:
    from luxos_i18n import _
except ImportError:          # pragma: no cover - bez balicku luxos-i18n
    def _(text):
        return text

TOP = "LuxOS-Backups"
SNAP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{6}$")
SNAP_FMT = "%Y-%m-%d-%H%M%S"
ASKPASS = "/usr/lib/luxos/backup/luxos-backup-askpass"
NOTIFY_ICON = "luxos-backup"
MIN_FREE = 1 << 30            # po zaloze nechat volne aspon 1 GiB ...
MIN_FREE_PCT = 2              # ... a 2 % disku
RETRY_FULL = 8                # kolik nejstarsich zaloh smazat pri plnem disku (na jeden beh)
STALE_DAYS = 7                # upozorneni "zadna zaloha 7 dni"

# Vyjimky ve formatu rsync, ukotvene ke koreni domovske slozky ("/" = ~).
BASE_EXCLUDES = [
    "/.cache/", "/.local/share/Trash/", "/.thumbnails/", "/.gvfs", "/.local/share/gvfs-metadata/",
    "/.var/app/*/cache/", "/.local/state/luxos/backup/", "/.dbus/", "/.xsession-errors*",
    "/.local/share/containers/storage/", "/.ccache/", "/.npm/_cacache/", "/.cargo/registry/cache/",
    "lost+found/",
]
DOWNLOAD_EXCLUDES = ["/Downloads/", "/Stažené/"]
VM_EXCLUDES = ["/VirtualBox VMs/", "/.local/share/gnome-boxes/images/", "/.local/share/libvirt/images/",
               "/vmware/", "*.qcow2", "*.vdi", "*.vmdk", "*.vhd", "*.vhdx"]
SYSTEM_EXCLUDES = ["/shadow*", "/gshadow*", "/sudoers.d/", "/ssh/ssh_host_*_key", "/cryptsetup-keys.d/",
                   "/NetworkManager/system-connections/", "/luxos-backup-secret*", "*.luxnew",
                   "*.pacnew"]

DEFAULTS = {"auto": True, "system": False, "downloads": True, "vms": False,
            "excludes": [], "disks": [], "declined": []}


# ---- cesty a nastaveni ----------------------------------------------------------
def home():
    return os.environ.get("LUXOS_BACKUP_HOME") or os.path.expanduser("~")


def safe_vault():
    """Sifrovany Trezor uzivatele (/safe/.vaults/<user>, gocryptfs) nebo None.

    Zalohuji se jen tato sifrovana data (zaloha je bez hesla Trezoru k nicemu), nikdy odemceny
    obsah /safe/<user>: ten lezi mimo domovskou slozku a rsync/py_copy neprechazeji pripojeni.
    LUXOS_BACKUP_SAFE: jina slozka (testy); s LUXOS_BACKUP_HOME bez ni zadny Trezor."""
    path = os.environ.get("LUXOS_BACKUP_SAFE")
    if path is None:
        if os.environ.get("LUXOS_BACKUP_HOME"):
            return None
        try:
            path = f"/safe/.vaults/{getpass.getuser()}"
        except (KeyError, OSError):
            return None
    if not path or not os.path.isfile(os.path.join(path, "gocryptfs.conf")) or os.path.islink(path):
        return None
    return path


def sysroot(path):
    return os.environ.get("LUXOS_SYSROOT", "") + path


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "luxos", "backup")


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "luxos", "backup")


def machine_name():
    host = os.environ.get("LUXOS_BACKUP_HOST") or socket.gethostname().split(".")[0] or "luxos"
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = str(os.getuid())
    return safe_name(f"{host}-{user}")


def safe_name(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._") or "luxos"


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except (OSError, ValueError):
        return default


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))          # kopie i vnorenych seznamu
    cfg.update(read_json(os.path.join(config_dir(), "config.json"), {}) or {})
    for k in ("excludes", "disks", "declined"):
        if not isinstance(cfg.get(k), list):
            cfg[k] = []
    return cfg


def save_config(cfg):
    write_json(os.path.join(config_dir(), "config.json"), cfg)


def load_status():
    return read_json(os.path.join(state_dir(), "status.json"), {}) or {}


def update_status(**kw):
    st = load_status()
    st.update(kw)
    write_json(os.path.join(state_dir(), "status.json"), st)
    return st


# ---- spousteni prikazu (testy ho nahrazuji) --------------------------------------
def run(cmd, input=None, env=None, timeout=None, check=False):
    """(navratovy kod, stdout, stderr); chybejici program = 127."""
    try:
        r = subprocess.run(cmd, input=input, capture_output=True, text=True, env=env, timeout=timeout)
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]}: timed out"
    if check and r.returncode:
        raise BackupError(r.stderr.strip() or f"{cmd[0]} failed ({r.returncode})")
    return r.returncode, r.stdout, r.stderr


def have(prog):
    return shutil.which(prog) is not None


class BackupError(Exception):
    pass


class DiskFull(BackupError):
    pass


class NotConnected(BackupError):
    pass


# ---- cas a nazvy zaloh -------------------------------------------------------------
def snap_name(t=None):
    return datetime.datetime.fromtimestamp(t if t is not None else time.time(),
                                           datetime.timezone.utc).strftime(SNAP_FMT)


def snap_time(name):
    return datetime.datetime.strptime(name, SNAP_FMT).replace(tzinfo=datetime.timezone.utc).timestamp()


def snap_label(name):
    """Mistni cas pro lidi: '2026-10-26 15:00'."""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(snap_time(name)))


def parse_when(text, names):
    """Vyber zalohy podle --from: nazev, 'latest', 'YYYY-MM-DD[ HH:MM]' (posledni do toho casu)."""
    names = sorted(names)
    if not names:
        raise BackupError(_("There are no backups yet."))
    if not text or text == "latest":
        return names[-1]
    if text in names:
        return text
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            t = time.mktime(time.strptime(text, fmt))
        except ValueError:
            continue
        if fmt == "%Y-%m-%d":
            t += 86400 - 1
        older = [n for n in names if snap_time(n) <= t]
        if older:
            return older[-1]
        raise BackupError(_("No backup from %s or earlier.") % text)
    raise BackupError(_("Unknown backup time: %s") % text)


# ---- protrideni ------------------------------------------------------------------
def thin(names, now=None):
    """Nazvy zaloh ke smazani: vse za 24 h, za mesic posledni z kazdeho dne, starsi posledni
    z kazdeho tydne. Nejnovejsi zustava vzdy."""
    now = time.time() if now is None else now
    names = sorted(n for n in names if SNAP_RE.match(n))
    keep, seen = set(names[-1:]), set()
    for n in reversed(names):
        t = snap_time(n)
        age = now - t
        if age < 86400:
            keep.add(n)
            continue
        lt = time.localtime(t)
        if age < 31 * 86400:
            bucket = ("d", lt.tm_year, lt.tm_yday)
        else:
            iso = datetime.date(lt.tm_year, lt.tm_mon, lt.tm_mday).isocalendar()
            bucket = ("w", iso[0], iso[1])
        if bucket not in seen:
            seen.add(bucket)
            keep.add(n)
    return [n for n in names if n not in keep]


# ---- vyjimky ---------------------------------------------------------------------
def download_dir_rel():
    """Slozka Stazene relativne k domovu podle xdg-user-dirs (napr. 'Stažené')."""
    path = os.path.join(home(), ".config", "user-dirs.dirs")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r'^XDG_DOWNLOAD_DIR="\$HOME/(.+)"\s*$', line.strip())
                if m:
                    return m.group(1).rstrip("/")
    except OSError:
        pass
    return None


def to_pattern(entry):
    """Vyjimka uzivatele: cesta v domove -> '/rel/', vzor ('*.iso') zustane."""
    entry = entry.strip()
    if not entry:
        return None
    h = home().rstrip("/") + "/"
    if entry.startswith("~/"):
        entry = "/" + entry[2:]
    elif entry.startswith(h):
        entry = "/" + entry[len(h):]
    elif entry.startswith("/") and os.path.isabs(entry) and not os.path.exists(os.path.join(home(), entry[1:])):
        return None                                           # cesta mimo domov
    if entry.startswith("/") and "*" not in entry and not entry.endswith("/") and \
            os.path.isdir(os.path.join(home(), entry[1:])):
        entry += "/"
    return entry


def excludes(cfg):
    pats = list(BASE_EXCLUDES)
    if not cfg.get("downloads", True):
        pats += DOWNLOAD_EXCLUDES
        d = download_dir_rel()
        if d:
            pats.append(f"/{d}/")
    if not cfg.get("vms", False):
        pats += VM_EXCLUDES
    for e in cfg.get("excludes", []):
        p = to_pattern(e)
        if p:
            pats.append(p)
    out = []
    for p in pats:
        if p not in out:
            out.append(p)
    return out


def is_excluded(rel, is_dir, patterns):
    """Zjednodusene pravidlo rsync: '/a/b' ukotvene, bez '/' na zacatku kdekoli; '*' neprechazi '/';
    '/' na konci = jen slozka."""
    for p in patterns:
        dir_only = p.endswith("/")
        pat = p.rstrip("/")
        if dir_only and not is_dir:
            continue
        if pat.startswith("/"):
            if _match(rel, pat[1:]):
                return True
        else:
            parts = rel.split("/")
            n = pat.count("/") + 1
            if len(parts) >= n and _match("/".join(parts[-n:]), pat):
                return True
    return False


def _match(path, pat):
    if path.count("/") != pat.count("/"):
        return False
    return all(fnmatch.fnmatchcase(a, b) for a, b in zip(path.split("/"), pat.split("/")))


# ---- podminky (baterie, Sporic baterie, merene pripojeni) ----------------------------
def power_state():
    """(napajeni ze site True/False/None, [(procenta, stav)])."""
    base = sysroot("/sys/class/power_supply")
    ac, bats = None, []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return None, []

    def rd(d, f):
        try:
            with open(os.path.join(base, d, f)) as fh:
                return fh.read().strip()
        except OSError:
            return ""
    for d in names:
        typ = rd(d, "type")
        if typ == "Mains" or (typ in ("USB", "USB_C", "USB_PD") and rd(d, "online")):
            if rd(d, "online") == "1":
                ac = True
            elif ac is None:
                ac = False
        elif typ == "Battery" and rd(d, "scope") != "Device":
            try:
                bats.append((int(rd(d, "capacity") or 0), rd(d, "status")))
            except ValueError:
                pass
    return ac, bats


def metered():
    """True kdyz je primarni pripojeni merene (Sporic dat, sdileni z telefonu)."""
    rc, out, _e = run(["busctl", "get-property", "org.freedesktop.NetworkManager",
                       "/org/freedesktop/NetworkManager", "org.freedesktop.NetworkManager", "Metered"], timeout=5)
    m = re.match(r"^u\s+(\d+)", out.strip()) if rc == 0 else None
    return bool(m and m.group(1) in ("1", "3"))


def current_env(network=False):
    ac, bats = power_state()
    return {"ac": ac, "batteries": bats, "powersaver": os.path.exists(sysroot("/run/luxos/powersaver")),
            "metered": metered() if network else False}


def conditions_ok(env, manual=False):
    """(smi zalohovat, duvod pauzy). Rucni zaloha jen nehledi na baterii a merene pripojeni."""
    if manual:
        return True, ""
    bats = env.get("batteries") or []
    charging = env.get("ac") is True or any(st in ("Charging", "Full") for _c, st in bats)
    if bats and not charging:
        return False, "battery"
    if env.get("powersaver") and bats and not charging:
        return False, "powersaver"
    if env.get("metered"):
        return False, "metered"
    return True, ""


PAUSE_TEXT = {
    "battery": "Paused on battery – backs up when the computer is charging",
    "powersaver": "Paused by Battery Saver",
    "metered": "Paused on a metered connection",
    "disconnected": "Backup disk is not connected",
    "off": "Automatic backups are off",
    "nodisk": "No backup disk",
}


# ---- upozorneni ------------------------------------------------------------------
NO_ANSWER = "no-answer"


def notify(title, body, critical=False, action=None):
    """notify-send; chyby jsou trvale (critical) a zustanou v historii oznameni.
    action=(id, text): oznameni zustane, dokud ho uzivatel nezavre (-t 0), a vrati id tlacitka,
    None = zavrel ho bez volby, NO_ANSWER = bez odpovedi (10 min, notify-send chybi) - to neni odmitnuti."""
    if os.environ.get("LUXOS_BACKUP_NO_NOTIFY") == "1":
        return None
    cmd = ["notify-send", "-a", _("Backups"), "-i", NOTIFY_ICON]
    if critical:
        cmd += ["-u", "critical", "-h", "boolean:x-luxos-keep:true"]
    if action:
        cmd += ["-t", "0", "-A", f"{action[0]}={action[1]}", "-w"]
    cmd += [title, body]
    try:
        if action:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                return NO_ANSWER
            return r.stdout.strip() or None
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, subprocess.TimeoutExpired):
        return NO_ANSWER if action else None
    return None


def notify_failure(kind, title, body):
    """Stejnou chybu nejvys jednou za 12 h (casovac bezi kazdou hodinu)."""
    st = load_status()
    sent = st.get("notified") or {}
    if time.time() - sent.get(kind, 0) < 12 * 3600:
        return
    sent[kind] = time.time()
    update_status(notified=sent)
    notify(title, body, critical=True)


# ---- klicenka (libsecret) ---------------------------------------------------------
def secret_get(disk_id):
    rc, out, _e = run(["secret-tool", "lookup", "service", "luxos-backup", "disk", disk_id], timeout=30)
    return out.rstrip("\n") if rc == 0 and out else None


def secret_set(disk_id, label, value):
    rc, _o, err = run(["secret-tool", "store", "--label", label, "service", "luxos-backup", "disk", disk_id],
                      input=value, timeout=60)
    if rc:
        raise BackupError(_("Could not save the password in the keyring: %s") % err.strip())


def secret_clear(disk_id):
    run(["secret-tool", "clear", "service", "luxos-backup", "disk", disk_id], timeout=30)


# ---- bloková zarizeni (lsblk, udisks) ------------------------------------------------
LSBLK_COLS = "NAME,PATH,TYPE,FSTYPE,LABEL,UUID,SIZE,RM,HOTPLUG,TRAN,MOUNTPOINTS,MODEL,VENDOR,PKNAME"


def lsblk():
    rc, out, _e = run(["lsblk", "-J", "-b", "-o", LSBLK_COLS], timeout=15)
    try:
        return json.loads(out).get("blockdevices", []) if rc == 0 else []
    except ValueError:
        return []


def flatten(devs, parent=None):
    for d in devs:
        d = dict(d)
        d["_parent"] = parent
        yield d
        yield from flatten(d.get("children") or [], d)


def mountpoint(dev):
    mps = [m for m in (dev.get("mountpoints") or []) if m]
    return mps[0] if mps else None


def external_disks():
    """Pripojitelne vymenne disky (USB, Thunderbolt, SD) - kandidati pro zalohy.
    [{"path", "uuid", "fstype", "label", "size", "model", "mount", "drive", "encrypted"}]"""
    out = []
    for top in lsblk():
        if not (top.get("rm") or top.get("hotplug") or top.get("tran") in ("usb", "sd", "mmc")) or \
                top.get("type") != "disk":
            continue
        model = " ".join(x for x in ((top.get("vendor") or "").strip(), (top.get("model") or "").strip()) if x)
        parts = [d for d in flatten(top.get("children") or [], top) if d.get("type") == "part"]
        for p in parts or [top]:
            inner = next((c for c in (p.get("children") or []) if c.get("type") == "crypt"), None)
            fs = inner or p
            out.append({"path": p["path"], "uuid": p.get("uuid"), "fstype": p.get("fstype"),
                        "inner_uuid": inner.get("uuid") if inner else None,
                        "inner_fstype": inner.get("fstype") if inner else None,
                        "label": p.get("label") or (inner or {}).get("label") or "",
                        "size": int(p.get("size") or 0), "model": model or top.get("name", ""),
                        "mount": mountpoint(fs), "drive": top["path"],
                        "encrypted": p.get("fstype") == "crypto_LUKS"})
    return out


POSIX_FS = ("btrfs", "ext4", "ext3", "xfs", "f2fs")


def fs_type(path):
    rc, out, _e = run(["findmnt", "-n", "-o", "FSTYPE", "-T", path], timeout=10)
    return out.strip().splitlines()[0] if rc == 0 and out.strip() else ""


def fs_uuid(path):
    rc, out, _e = run(["findmnt", "-n", "-o", "UUID,TARGET", "-T", path], timeout=10)
    if rc or not out.strip():
        return None, None
    parts = out.split()
    return (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0])


def udisks_mount(device):
    rc, out, err = run(["udisksctl", "mount", "-b", device, "--no-user-interaction"], timeout=60)
    m = re.search(r" at (.+?)\.?$", out.strip())
    if rc == 0 and m:
        return m.group(1)
    if "AlreadyMounted" in err:
        m = re.search(r"mounted at `(.+?)'", err)
        if m:
            return m.group(1)
    if "NotAuthorized" in err:
        # Mimo aktivni relaci plochy (ssh, jina konzole) chce pripojeni heslo spravce. V terminalu se
        # udisksctl zepta sam (textovy agent polkit), jinak srozumitelna hlaska misto chyby D-Bus.
        if sys.stdin is not None and sys.stdin.isatty():
            try:
                r = subprocess.run(["udisksctl", "mount", "-b", device], stdout=subprocess.PIPE,
                                   text=True, timeout=300)
                m = re.search(r" at (.+?)\.?$", r.stdout.strip())
                if r.returncode == 0 and m:
                    return m.group(1)
            except (OSError, subprocess.TimeoutExpired):
                pass
        raise NotConnected(_("Connecting the backup disk needs an administrator password here. "
                             "Use the Backups window, or run the command in a terminal of your desktop session."))
    raise NotConnected(err.strip() or _("Could not mount %s") % device)


def udisks_unlock(device, passphrase):
    r, w = os.pipe()
    os.write(w, passphrase.encode())
    os.close(w)
    try:
        p = subprocess.run(["udisksctl", "unlock", "-b", device, "--key-file", f"/dev/fd/{r}",
                            "--no-user-interaction"], capture_output=True, text=True, pass_fds=(r,), timeout=120)
    finally:
        os.close(r)
    m = re.search(r" as (/dev/\S+?)\.?$", p.stdout.strip())
    if p.returncode or not m:
        raise NotConnected(p.stderr.strip() or _("Could not unlock the backup disk"))
    return m.group(1)


# ---- disky zaloh -------------------------------------------------------------------
def disk_label(disk):
    if disk.get("name"):
        return disk["name"]
    if disk["kind"] == "sftp":
        return f"{disk.get('host')}:{disk.get('path')}"
    if disk["kind"] == "smb":
        return disk.get("url", "")
    return disk.get("path") or disk.get("uuid", "?")


def luks_secret(disk):
    """Heslo sifrovaneho disku v klicence (heslo k serveru je pod samotnym id)."""
    return disk["id"] + "-luks"


def new_disk_id():
    return os.urandom(4).hex()


def find_disk(cfg, ident=None):
    disks = cfg.get("disks", [])
    if not disks:
        raise BackupError(_("No backup disk is set up. Add one with: luxos-backup disk add"))
    if ident is None:
        return disks[0]
    for d in disks:
        if ident in (d["id"], d.get("name"), d.get("uuid"), d.get("path")):
            return d
    raise BackupError(_("Unknown backup disk: %s") % ident)


class Session:
    """Pristup k disku zaloh po dobu jedne operace: pripoji/odemkne a pak vrati, jak bylo."""

    def __init__(self, disk, mount=True):
        self.disk = disk
        self.do_mount = mount
        self.undo = []
        self.root = None          # mistni slozka <disk>/LuxOS-Backups/<pocitac> nebo None u sftp
        self.remote = None        # (ssh argumenty, vzdalena slozka) u sftp

    def __enter__(self):
        kind = self.disk["kind"]
        if kind == "sftp":
            self.remote = (ssh_base(self.disk), posix_join(self.disk.get("path") or ".", TOP,
                                                           self.disk.get("machine") or machine_name()))
            return self
        mnt = self.local_mount()
        self.root = os.path.join(mnt, TOP, self.disk.get("machine") or machine_name())
        return self

    def local_mount(self):
        d = self.disk
        if d["kind"] == "smb":
            return self.smb_mount()
        if d.get("path"):
            if not os.path.isdir(d["path"]):
                raise NotConnected(_("The backup disk is not connected."))
            return d["path"]
        return os.path.join(self.mount_uuid(d.get("uuid"), d.get("luks_uuid")), d.get("subdir") or "")

    def mount_uuid(self, uuid, luks_uuid=None):
        devs = list(flatten(lsblk()))
        fs = next((x for x in devs if uuid and x.get("uuid") == uuid), None)
        if fs is None and luks_uuid:
            luks = next((x for x in devs if x.get("uuid") == luks_uuid), None)
            if luks is None:
                raise NotConnected(_("The backup disk is not connected."))
            inner = next((c for c in luks.get("children") or [] if c.get("type") == "crypt"), None)
            if inner is None:
                if not self.do_mount:
                    raise NotConnected(_("The backup disk is locked."))
                pw = secret_get(luks_secret(self.disk))
                if not pw:
                    raise NotConnected(_("The password for the encrypted backup disk is not in the keyring."))
                cleartext = udisks_unlock(luks["path"], pw)
                self.undo.append(["udisksctl", "lock", "-b", luks["path"], "--no-user-interaction"])
                inner = {"path": cleartext, "mountpoints": []}
            fs = inner
        if fs is None:
            raise NotConnected(_("The backup disk is not connected."))
        mnt = mountpoint(fs)
        if not mnt:
            if not self.do_mount:
                raise NotConnected(_("The backup disk is not mounted."))
            mnt = udisks_mount(fs["path"])
            self.undo.insert(0, ["udisksctl", "unmount", "-b", fs["path"], "--no-user-interaction"])
        return mnt

    def smb_mount(self):
        share = smb_fuse_path(self.disk, self.do_mount)
        image = os.path.join(share, TOP, (self.disk.get("machine") or machine_name()) + ".img")
        if not os.path.exists(image):
            raise NotConnected(_("The backup image was not found on the network disk."))
        dev = loop_for(image)
        if dev is None:
            rc, out, err = run(["udisksctl", "loop-setup", "-f", image, "--no-user-interaction"], timeout=60)
            m = re.search(r" as (/dev/loop\d+)", out)
            if rc or not m:
                raise NotConnected(err.strip() or _("Could not open the backup image"))
            dev = m.group(1)
            self.undo.append(["udisksctl", "loop-delete", "-b", dev, "--no-user-interaction"])
        return self.mount_uuid(self.disk.get("uuid"), self.disk.get("luks_uuid"))

    def __exit__(self, *exc):
        for cmd in self.undo:
            run(cmd, timeout=120)
        return False


def loop_for(image):
    rc, out, _e = run(["losetup", "-j", image, "-O", "NAME", "-n"], timeout=10)
    return out.split()[0] if rc == 0 and out.strip() else None


def smb_parse(url):
    m = re.match(r"^smb://(?:([^@/]+)@)?([^/]+)/([^/]+)/?(.*)$", url)
    if not m:
        raise BackupError(_("Use a network address like smb://user@server/share"))
    return {"user": m.group(1) or "", "host": m.group(2), "share": m.group(3), "sub": m.group(4)}


def smb_fuse_path(disk, do_mount=True):
    p = smb_parse(disk["url"])
    base = f"/run/user/{os.getuid()}/gvfs"

    def find():
        try:
            for name in os.listdir(base):
                if name.startswith("smb-share:") and f"server={p['host'].lower()}" in name.lower() and \
                        f"share={p['share'].lower()}" in name.lower():
                    return os.path.join(base, name, p["sub"])
        except OSError:
            pass
        return None
    path = find()
    if path is None and do_mount:
        pw = secret_get(disk["id"]) or ""
        # gio mount se pta: uzivatel, domena, heslo (radky na stdin)
        run(["gio", "mount", disk["url"]], input=f"{p['user']}\n\n{pw}\n", timeout=60)
        path = find()
    if path is None:
        raise NotConnected(_("The network disk is not available."))
    return path


# ---- sftp ------------------------------------------------------------------------
def posix_join(*parts):
    out = parts[0].rstrip("/") or "/"
    for p in parts[1:]:
        out = out + "/" + p.strip("/") if out != "/" else "/" + p.strip("/")
    return out


def ssh_base(disk):
    args = ["ssh", "-p", str(disk.get("port") or 22), "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", "-o", "ConnectTimeout=20"]
    user = disk.get("user")
    return args + [f"{user}@{disk['host']}" if user else disk["host"]]


def ssh_env(disk):
    env = dict(os.environ)
    if disk.get("kind") == "sftp":
        env.update(SSH_ASKPASS=ASKPASS, SSH_ASKPASS_REQUIRE="force", LUXOS_BACKUP_DISK=disk["id"])
    return env


def ssh_run(sess, script, timeout=120):
    """Prikaz na serveru (sh -c); argumenty se citují shlex.quote."""
    rc, out, err = run(sess.remote[0] + ["--", script], env=ssh_env(sess.disk), timeout=timeout)
    if rc == 255:
        raise NotConnected(err.strip() or _("Could not connect to the server."))
    return rc, out, err


# ---- operace na cili (mistni slozka nebo sftp) ----------------------------------------
def list_snapshots(sess):
    if sess.remote:
        rc, out, _e = ssh_run(sess, "ls -1 -- " + shlex.quote(sess.remote[1]) + " 2>/dev/null")
        names = out.split("\n")
    else:
        try:
            names = os.listdir(sess.root)
        except OSError:
            names = []
    return sorted(n for n in names if SNAP_RE.match(n))


def free_space(sess):
    """(volno, celkem) v bajtech."""
    if sess.remote:
        rc, out, _e = ssh_run(sess, "df -Pk -- " + shlex.quote(sess.remote[1]) + " | tail -1")
        f = out.split()
        try:
            return int(f[3]) * 1024, int(f[1]) * 1024
        except (IndexError, ValueError):
            return None, None
    st = os.statvfs(sess.root if os.path.isdir(sess.root) else os.path.dirname(sess.root))
    return st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize


def delete_snapshot(sess, name):
    if not (SNAP_RE.match(name) or name.endswith(".partial")):
        raise BackupError(f"refusing to delete {name}")
    if sess.remote:
        ssh_run(sess, "rm -rf -- " + shlex.quote(posix_join(sess.remote[1], name)), timeout=3600)
        return
    path = os.path.join(sess.root, name)
    if engine_for(sess) == "btrfs" and is_subvolume(path):
        btrfs_delete(path)
    else:
        rmtree(path)


def rmtree(path):
    def onerror(func, p, _exc):
        # zalohy jen pro cteni (slozky bez prava zapisu): povolit a zkusit znovu
        try:
            os.chmod(os.path.dirname(p), 0o700)
            if os.path.isdir(p) and not os.path.islink(p):
                os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass
    if os.path.lexists(path):
        shutil.rmtree(path, onexc=onerror) if sys.version_info >= (3, 12) else shutil.rmtree(path, onerror=onerror)


def is_subvolume(path):
    try:
        return os.stat(path).st_ino == 256
    except OSError:
        return False


def btrfs_delete(path):
    rc, _o, _e = run(["btrfs", "subvolume", "delete", path], timeout=600)
    if rc == 0:
        return
    # bez user_subvol_rm_allowed: vlastnik smi zrusit "jen pro cteni", smazat obsah a rmdir
    run(["btrfs", "property", "set", "-ts", path, "ro", "false"], timeout=60)
    for entry in os.listdir(path):
        p = os.path.join(path, entry)
        if os.path.isdir(p) and not os.path.islink(p):
            rmtree(p)
        else:
            os.unlink(p)
    os.rmdir(path)


def engine_for(sess):
    forced = os.environ.get("LUXOS_BACKUP_ENGINE")
    if sess.remote:
        return "sftp"
    if forced:
        return forced
    if fs_type(os.path.dirname(sess.root) if not os.path.isdir(sess.root) else sess.root) == "btrfs" and have("btrfs"):
        return "btrfs"
    return "rsync" if have("rsync") else "python"


def check_target_fs(path):
    fs = fs_type(path)
    if fs in ("vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "msdos"):
        raise BackupError(_("This disk uses %s, which cannot keep backups efficiently. "
                            "Prepare (erase) it for backups first.") % fs)


# ---- kopirovani ----------------------------------------------------------------------
RSYNC_OK = (0, 24)                 # 24 = soubory zmizely behem zalohy
RSYNC_PARTIAL = 23                 # nektere soubory nesly precist


def rsync_cmd(src, dst, patterns_file=None, link_dest=None, inplace=False, delete=True, remote=None,
              progress=True):
    cmd = ["rsync", "-aHAX", "--one-file-system", "--numeric-ids", "--no-inc-recursive"]
    if os.geteuid() != 0:
        cmd = ["rsync", "-aHX", "--one-file-system", "--no-inc-recursive"]
    if progress:
        cmd += ["--info=progress2"]
    if delete:
        cmd += ["--delete", "--delete-excluded"]
    if inplace:
        cmd += ["--inplace", "--no-whole-file"]
    if patterns_file:
        cmd += ["--exclude-from", patterns_file]
    if link_dest:
        cmd += ["--link-dest", link_dest]
    if remote:
        cmd += ["-e", " ".join(shlex.quote(a) for a in remote[:-1])]
        dst = f"{remote[-1]}:{dst}"
    return cmd + [src.rstrip("/") + "/", dst.rstrip("/") + "/"]


def run_rsync(cmd, env=None, on_progress=None):
    """Spusti rsync, prubeh v % posila on_progress; vrati (kod, chybovy vystup)."""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    except FileNotFoundError:
        return 127, "rsync: not found"
    err = []
    import threading
    t = threading.Thread(target=lambda: err.append(p.stderr.read().decode(errors="replace")), daemon=True)
    t.start()
    buf = b""
    last = 0
    while True:
        chunk = p.stdout.read1(4096) if hasattr(p.stdout, "read1") else p.stdout.read(4096)
        if not chunk:
            break
        buf = (buf + chunk)[-256:]
        m = re.findall(rb"(\d+)%", buf)
        if m and on_progress and time.time() - last > 1.5:
            last = time.time()
            on_progress(int(m[-1]))
    p.wait()
    t.join(5)
    return p.returncode, "".join(err)


def same_file(a, b):
    return (a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns and
            stat.S_IMODE(a.st_mode) == stat.S_IMODE(b.st_mode))


def py_copy(src, dst, patterns=(), link_dest=None, skip_existing=False, backup_dir=None, one_fs=True):
    """Kopie stromu bez rsync. link_dest: nezmeneny soubor = pevny odkaz na predchozi zalohu.
    skip_existing: existujici cil nechat; backup_dir: existujici cil presunout sem (obnova vseho).
    Vrati pocet preskocenych (necitelnych nebo existujicich) souboru."""
    skipped = 0
    try:
        root_dev = os.lstat(src).st_dev
    except OSError as e:
        raise BackupError(str(e))
    os.makedirs(dst, exist_ok=True)
    dirs_meta = []
    for cur, dnames, fnames in os.walk(src):
        rel_dir = os.path.relpath(cur, src)
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in dnames:
            rel = f"{rel_dir}/{d}" if rel_dir else d
            sp = os.path.join(cur, d)
            try:
                st = os.lstat(sp)
            except OSError:
                skipped += 1
                continue
            if stat.S_ISLNK(st.st_mode):
                fnames.append(d)
                continue
            if is_excluded(rel, True, patterns) or (one_fs and st.st_dev != root_dev):
                continue
            keep.append(d)
            dp = os.path.join(dst, rel)
            if os.path.lexists(dp) and not os.path.isdir(dp):
                if skip_existing and not backup_dir:
                    skipped += 1
                    continue
                replace_path(dp, dst, backup_dir)
            os.makedirs(dp, exist_ok=True)
            dirs_meta.append((sp, dp))
        dnames[:] = keep
        for fn in fnames:
            rel = f"{rel_dir}/{fn}" if rel_dir else fn
            sp, dp = os.path.join(cur, fn), os.path.join(dst, rel)
            try:
                st = os.lstat(sp)
            except OSError:
                skipped += 1
                continue
            if is_excluded(rel, False, patterns):
                continue
            if os.path.lexists(dp):
                if skip_existing and not backup_dir:
                    skipped += 1
                    continue
                replace_path(dp, dst, backup_dir)
            try:
                if stat.S_ISLNK(st.st_mode):
                    os.symlink(os.readlink(sp), dp)
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue                          # zarizeni, roury, sokety se nezalohuji
                if link_dest:
                    lp = os.path.join(link_dest, rel)
                    try:
                        if same_file(st, os.lstat(lp)):
                            os.link(lp, dp)
                            continue
                    except OSError:
                        pass
                shutil.copy2(sp, dp, follow_symlinks=False)
            except OSError as e:
                if e.errno == errno.ENOSPC:
                    raise DiskFull(str(e))
                skipped += 1
    for sp, dp in reversed(dirs_meta):
        with contextlib.suppress(OSError):
            shutil.copystat(sp, dp, follow_symlinks=False)
    return skipped


def replace_path(path, root, backup_dir):
    """Uvolni misto pro novy soubor. Bez backup_dir (zaloha do .partial) se stary smaze -
    nikdy se do nej nezapisuje, muze to byt pevny odkaz na soubor v predchozi zaloze."""
    if not backup_dir:
        if os.path.isdir(path) and not os.path.islink(path):
            rmtree(path)
        else:
            os.unlink(path)
        return
    dest = os.path.join(backup_dir, os.path.relpath(path, root))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.replace(path, dest)


# ---- zaloha ----------------------------------------------------------------------
def ensure_root(sess):
    if sess.remote:
        rc, _o, err = ssh_run(sess, "mkdir -p -- " + shlex.quote(sess.remote[1]))
        if rc:
            raise BackupError(err.strip() or _("Could not create the backup folder on the server."))
        return
    try:
        os.makedirs(sess.root, exist_ok=True)
    except OSError as e:
        raise BackupError(_("Could not create the backup folder: %s") % e.strerror)
    meta = os.path.join(sess.root, "backup.json")
    if not os.path.exists(meta):
        write_json(meta, {"format": 1, "machine": os.path.basename(sess.root), "home": home(),
                          "created": snap_name()})


def system_snapshot(meta_dir):
    """Seznam rucne nainstalovanych baliku (pro "Obnovit vse" na novem systemu)."""
    os.makedirs(os.path.join(meta_dir, "system"), exist_ok=True)
    rc, out, _e = run(["lux-engine", "-Qqe"], timeout=60)
    if rc == 0:
        with open(os.path.join(meta_dir, "system", "packages.txt"), "w") as f:
            f.write(out)


def write_patterns(pats):
    path = os.path.join(state_dir(), "excludes.rsync")
    os.makedirs(state_dir(), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(f"- {p}" for p in pats) + "\n")
    return path


def lock():
    os.makedirs(state_dir(), exist_ok=True)
    fd = os.open(os.path.join(state_dir(), "lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def make_space(sess, need_free=None, log=print):
    """Smaze nejstarsi zalohy (nikdy posledni), dokud neni volno. Vrati smazane."""
    deleted = []
    for _i in range(RETRY_FULL):
        free, total = free_space(sess)
        if free is None:
            break
        want = need_free if need_free is not None else max(MIN_FREE, (total or 0) * MIN_FREE_PCT // 100)
        names = list_snapshots(sess)
        if free >= want or len(names) <= 1:
            break
        log(_("Disk is full - deleting the oldest backup %s") % snap_label(names[0]))
        delete_snapshot(sess, names[0])
        deleted.append(names[0])
    return deleted


def backup(disk, cfg, log=print, on_progress=None):
    """Jedna zaloha na disk. Vrati nazev nove zalohy."""
    src = home()
    pats = excludes(cfg)
    name = snap_name()
    with Session(disk) as sess:
        ensure_root(sess)
        if not sess.remote:
            check_target_fs(sess.root)
        eng = engine_for(sess)
        deleted = make_space(sess, log=log)
        names = list_snapshots(sess)
        prev = names[-1] if names else None
        meta = os.path.join(state_dir(), "meta")
        rmtree(meta)
        os.makedirs(meta)
        if cfg.get("system"):
            system_snapshot(meta)
        info = {"created": name, "machine": disk.get("machine") or machine_name(), "home": src,
                "engine": eng, "system": bool(cfg.get("system")), "safe": bool(safe_vault()),
                "version": luxos_version()}
        warnings = 0
        for attempt in range(RETRY_FULL + 1):
            try:
                warnings = _copy(sess, eng, src, name, prev, pats, meta, info, cfg, on_progress, log)
                break
            except DiskFull:
                names = list_snapshots(sess)
                if len(names) <= 1 or attempt == RETRY_FULL:
                    raise
                log(_("Disk is full - deleting the oldest backup %s") % snap_label(names[0]))
                delete_snapshot(sess, names[0])
                deleted.append(names[0])
                prev = names[-1]
        for old in thin(list_snapshots(sess)):
            delete_snapshot(sess, old)
        deleted += make_space(sess, log=log)
        if deleted:
            notify(_("Old backups deleted"),
                   _("The backup disk was full, so the oldest backups were deleted (%d).") % len(deleted))
    rmtree(meta)
    return name, warnings


def luxos_version():
    try:
        with open(sysroot("/usr/lib/os-release")) as f:
            for line in f:
                if line.startswith("VERSION_ID="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def _copy(sess, eng, src, name, prev, pats, meta, info, cfg, on_progress, log):
    """Prenese domov (+ system) do nove zalohy. Vrati pocet varovani (necitelne soubory)."""
    warnings = 0
    sys_pats = SYSTEM_EXCLUDES
    vault = safe_vault()
    if eng == "python":
        part = os.path.join(sess.root, name + ".partial")
        _reuse_partial(sess, part)
        try:
            warnings += py_copy(src, os.path.join(part, "home"), pats,
                                os.path.join(sess.root, prev, "home") if prev else None)
            if vault:
                warnings += py_copy(vault, os.path.join(part, "safe", "vault"), (),
                                    os.path.join(sess.root, prev, "safe", "vault") if prev else None)
            if cfg.get("system"):
                warnings += py_copy(sysroot("/etc"), os.path.join(part, "system", "etc"), sys_pats,
                                    os.path.join(sess.root, prev, "system", "etc") if prev else None)
                py_copy(os.path.join(meta, "system"), os.path.join(part, "system"))
        except OSError as e:
            if getattr(e, "errno", None) == errno.ENOSPC:
                raise DiskFull(str(e))
            raise
        _finish_local(part, os.path.join(sess.root, name), info, warnings)
        return warnings

    pfile = write_patterns(pats)
    sfile = os.path.join(state_dir(), "excludes-system.rsync")
    with open(sfile, "w") as f:
        f.write("\n".join(f"- {p}" for p in sys_pats) + "\n")

    def go(s, d, patfile, link, inplace=False, remote=None, progress=True):
        rc, err = run_rsync(rsync_cmd(s, d, patfile, link, inplace=inplace, remote=remote, progress=progress),
                            env=ssh_env(sess.disk), on_progress=on_progress if progress else None)
        if rc in RSYNC_OK:
            return 0
        if rc == RSYNC_PARTIAL:
            log(err.strip()[-2000:])
            return 1
        if rc == 11 or "No space left" in err:
            raise DiskFull(err)
        if rc == 255 or rc == 12 and sess.remote:
            raise NotConnected(err.strip()[-500:] or _("Could not connect to the server."))
        raise BackupError(err.strip()[-800:] or f"rsync {rc}")

    if eng == "sftp":
        base = sess.remote[1]
        part = posix_join(base, name + ".partial")
        ssh_run(sess, "mkdir -p -- " + shlex.quote(part))
        remote = sess.remote[0]
        warnings += go(src, posix_join(part, "home"), pfile, f"../../{prev}/home" if prev else None,
                       remote=remote)
        if vault:
            ssh_run(sess, "mkdir -p -- " + shlex.quote(posix_join(part, "safe")))
            warnings += go(vault, posix_join(part, "safe", "vault"), None,
                           f"../../../{prev}/safe/vault" if prev else None, remote=remote, progress=False)
        if cfg.get("system"):
            warnings += go(sysroot("/etc"), posix_join(part, "system", "etc"), sfile,
                           f"../../../{prev}/system/etc" if prev else None, remote=remote, progress=False)
        info["warnings"] = warnings
        write_json(os.path.join(meta, "info.json"), info)
        run_rsync(rsync_cmd(meta, part, None, None, delete=False, remote=remote, progress=False),
                  env=ssh_env(sess.disk))
        rc, _o, err = ssh_run(sess, "mv -- %s %s" % (shlex.quote(part), shlex.quote(posix_join(base, name))))
        if rc:
            raise BackupError(err.strip())
        return warnings

    if eng == "btrfs":
        cur = os.path.join(sess.root, ".current")
        if not os.path.isdir(cur):
            rc, _o, err = run(["btrfs", "subvolume", "create", cur], timeout=60)
            if rc:
                raise BackupError(err.strip())
        warnings += go(src, os.path.join(cur, "home"), pfile, None, inplace=True)
        if cfg.get("system"):
            warnings += go(sysroot("/etc"), os.path.join(cur, "system", "etc"), sfile, None, inplace=True,
                           progress=False)
        else:
            rmtree(os.path.join(cur, "system"))
        if vault:
            os.makedirs(os.path.join(cur, "safe"), exist_ok=True)
            warnings += go(vault, os.path.join(cur, "safe", "vault"), None, None, inplace=True, progress=False)
        else:
            rmtree(os.path.join(cur, "safe"))
        if os.path.isdir(os.path.join(meta, "system")):
            shutil.copy2(os.path.join(meta, "system", "packages.txt"), os.path.join(cur, "system")) \
                if os.path.exists(os.path.join(meta, "system", "packages.txt")) else None
        info["warnings"] = warnings
        write_json(os.path.join(cur, "info.json"), info)
        rc, _o, err = run(["btrfs", "subvolume", "snapshot", "-r", cur, os.path.join(sess.root, name)],
                          timeout=600)
        if rc:
            if "No space left" in err:
                raise DiskFull(err)
            raise BackupError(err.strip())
        return warnings

    # rsync s pevnymi odkazy
    part = os.path.join(sess.root, name + ".partial")
    _reuse_partial(sess, part)
    os.makedirs(os.path.join(part, "home"), exist_ok=True)
    warnings += go(src, os.path.join(part, "home"), pfile,
                   os.path.join(sess.root, prev, "home") if prev else None)
    if cfg.get("system"):
        os.makedirs(os.path.join(part, "system", "etc"), exist_ok=True)
        warnings += go(sysroot("/etc"), os.path.join(part, "system", "etc"), sfile,
                       os.path.join(sess.root, prev, "system", "etc") if prev else None, progress=False)
        if os.path.exists(os.path.join(meta, "system", "packages.txt")):
            shutil.copy2(os.path.join(meta, "system", "packages.txt"), os.path.join(part, "system"))
    if vault:
        os.makedirs(os.path.join(part, "safe", "vault"), exist_ok=True)
        warnings += go(vault, os.path.join(part, "safe", "vault"), None,
                       os.path.join(sess.root, prev, "safe", "vault") if prev else None, progress=False)
    _finish_local(part, os.path.join(sess.root, name), info, warnings)
    return warnings


def _reuse_partial(sess, part):
    """Rozpracovanou zalohu z prerusenoho behu prejmenovat a dokoncit (rsync doplni zbytek)."""
    for n in os.listdir(sess.root):
        if n.endswith(".partial") and os.path.join(sess.root, n) != part:
            os.rename(os.path.join(sess.root, n), part)
            break


def _finish_local(part, final, info, warnings):
    info["warnings"] = warnings
    write_json(os.path.join(part, "info.json"), info)
    os.rename(part, final)


def run_backup(disk_ident=None, manual=False, log=print, on_progress=None):
    """Zaloha na vsechny pripojene disky (nebo jeden). Vrati 0 = ok/pauza, 1 = chyba, 2 = probiha."""
    cfg = load_config()
    if not cfg["disks"]:
        update_status(state="idle", reason="nodisk")
        log(_("No backup disk is set up."))
        return 0 if not manual else 1
    if not manual and not cfg.get("auto", True):
        update_status(state="idle", reason="off")
        return 0
    fd = lock()
    if fd is None:
        log(_("A backup is already running."))
        return 2
    try:
        disks = [find_disk(cfg, disk_ident)] if disk_ident else cfg["disks"]
        rc_all, done = 0, 0
        for disk in disks:
            env = current_env(network=disk["kind"] != "local")
            ok, why = conditions_ok(env, manual)
            if not ok:
                update_status(state="paused", reason=why)
                log(_(PAUSE_TEXT[why]))
                continue
            update_status(state="running", disk=disk["id"], progress=0, reason="", started=time.time(),
                          pid=os.getpid())

            def prog(pct):
                update_status(progress=pct)
                if on_progress:
                    on_progress(pct)
            try:
                log(_("Backing up to %s…") % disk_label(disk))
                name, warn = backup(disk, cfg, log=log, on_progress=prog)
            except NotConnected as e:
                update_status(state="idle", reason="disconnected", last_error="")
                log(str(e))
                if manual:
                    rc_all = 1
                continue
            except DiskFull as e:
                rc_all = 1
                update_status(state="error", last_error=_("The backup disk is full."), last_attempt=time.time())
                notify_failure("full", _("Backup failed"),
                               _("The backup disk %s is full even after deleting old backups.") % disk_label(disk))
                log(str(e))
                continue
            except (BackupError, OSError) as e:
                rc_all = 1
                msg = str(e).strip() or e.__class__.__name__
                update_status(state="error", last_error=msg, last_attempt=time.time())
                notify_failure("error", _("Backup failed"), _("Backup to %s failed: %s") % (disk_label(disk), msg[:300]))
                log(msg)
                continue
            done += 1
            st = load_status()
            last = st.get("last_by_disk") or {}
            last[disk["id"]] = time.time()
            update_status(state="idle", reason="", progress=100, last_success=time.time(), last_name=name,
                          last_error="", last_warnings=warn, last_by_disk=last, notified={})
            log(_("Backup finished: %s") % snap_label(name) +
                (" " + _("(%d files could not be read)") % warn if warn else ""))
        if not done and not manual:
            stale_warning()
        return rc_all
    finally:
        os.close(fd)


def stale_warning():
    st = load_status()
    last = st.get("last_success") or 0
    if last and time.time() - last > STALE_DAYS * 86400:
        days = int((time.time() - last) // 86400)
        sent = st.get("stale_notified", 0)
        if time.time() - sent > 86400:
            update_status(stale_notified=time.time())
            notify(_("No backup for %d days") % days, _("Connect your backup disk to back up this computer."))


def due(cfg, now=None):
    """Automaticka zaloha je na rade (minimalne 55 minut od posledni)."""
    now = time.time() if now is None else now
    return now - (load_status().get("last_success") or 0) >= 55 * 60


# ---- prochazeni a obnova -------------------------------------------------------------
def find_machine_root(path, machine=None):
    """--source: slozka se zalohami, slozka LuxOS-Backups nebo koren disku."""
    path = os.path.abspath(path)

    def has_snaps(p):
        try:
            return any(SNAP_RE.match(n) for n in os.listdir(p))
        except OSError:
            return False
    if has_snaps(path):
        return path
    top = path if os.path.basename(path) == TOP else os.path.join(path, TOP)
    try:
        cands = sorted(n for n in os.listdir(top) if os.path.isdir(os.path.join(top, n)))
    except OSError:
        raise BackupError(_("No LuxOS backups found in %s") % path)
    if machine:
        if machine in cands:
            return os.path.join(top, machine)
        raise BackupError(_("No backups of %s in %s") % (machine, top))
    mine = machine_name()
    if mine in cands:
        return os.path.join(top, mine)
    if len(cands) == 1:
        return os.path.join(top, cands[0])
    raise BackupError(_("Several computers have backups here, choose one with --machine: %s") % ", ".join(cands))


class SourceSession:
    """Obnova ze slozky bez nastaveni (LuxOS Recovery, novy system)."""

    def __init__(self, root):
        self.root, self.remote, self.disk = root, None, {"kind": "local", "id": "source"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def open_source(disk_ident=None, source=None, machine=None, mount=True):
    if source:
        return SourceSession(find_machine_root(source, machine))
    cfg = load_config()
    disk = dict(find_disk(cfg, disk_ident))
    if machine:
        disk["machine"] = machine
    return Session(disk, mount=mount)


def snapshot_home(sess, name):
    return posix_join(sess.remote[1], name, "home") if sess.remote else os.path.join(sess.root, name, "home")


def list_dir(sess, name, rel=""):
    """Obsah slozky v zaloze: [(jmeno, je_slozka, velikost, mtime)]."""
    rel = clean_rel(rel)
    if sess.remote:
        path = posix_join(snapshot_home(sess, name), rel) if rel else snapshot_home(sess, name)
        rc, out, _e = ssh_run(sess, "cd -- %s && find . -mindepth 1 -maxdepth 1 -printf '%%y\\t%%s\\t%%T@\\t%%f\\n'"
                              % shlex.quote(path))
        items = []
        for line in out.splitlines():
            parts = line.split("\t", 3)
            if len(parts) == 4:
                items.append((parts[3], parts[0] == "d", int(parts[1] or 0), float(parts[2] or 0)))
        return sorted(items, key=lambda x: (not x[1], x[0].lower()))
    path = os.path.join(snapshot_home(sess, name), rel)
    items = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                items.append((e.name, e.is_dir(follow_symlinks=False), st.st_size, st.st_mtime))
    except OSError as e:
        raise BackupError(str(e))
    return sorted(items, key=lambda x: (not x[1], x[0].lower()))


def clean_rel(rel):
    """Cesta v domove: z '~/x', '/home/u/x' nebo 'x' -> 'x'; zadne '..'."""
    rel = (rel or "").strip()
    h = home().rstrip("/") + "/"
    if rel.startswith("~/") or rel == "~":
        rel = rel[2:]
    elif rel.startswith(h):
        rel = rel[len(h):]
    elif rel == h.rstrip("/"):
        rel = ""
    rel = os.path.normpath(rel.lstrip("/")) if rel.strip("/") else ""
    if rel == ".":
        rel = ""
    if rel.startswith("..") or "/../" in f"/{rel}/":
        raise BackupError(_("Invalid path: %s") % rel)
    return rel


def restored_name(path, when):
    """'zprava.txt' -> 'zprava (obnoveno 2026-10-26 14.30).txt' - volne jmeno vedle originalu."""
    d, base = os.path.split(path)
    stem, ext = os.path.splitext(base)
    if base.startswith(".") and stem == base:
        ext = ""
    if os.path.isdir(path) or not ext or len(ext) > 6:
        stem, ext = base, ""
    label = _("restored %s") % when
    n = 1
    while True:
        cand = os.path.join(d, f"{stem} ({label}){ext}" if n == 1 else f"{stem} ({label} {n}){ext}")
        if not os.path.lexists(cand):
            return cand
        n += 1


def _copy_out(sess, src, dst):
    """Kopie ze zalohy do noveho (neexistujiciho) cile."""
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    if sess.remote:
        # slozka: obsah do noveho cile (src/), soubor: primo
        is_dir = ssh_run(sess, "test -d " + shlex.quote(src))[0] == 0
        rc, err = run_rsync(["rsync", "-aHX", "-e", " ".join(shlex.quote(a) for a in sess.remote[0][:-1]),
                             f"{sess.remote[0][-1]}:{src}" + ("/" if is_dir else ""), dst], env=ssh_env(sess.disk))
        if rc not in RSYNC_OK:
            raise BackupError(err.strip()[-500:])
        return
    if os.path.isdir(src) and not os.path.islink(src):
        py_copy(src, dst, one_fs=False)
        _fix_mode(dst)
    elif os.path.islink(src):
        os.symlink(os.readlink(src), dst)
    else:
        shutil.copy2(src, dst)
        _fix_mode(dst)


def _fix_mode(path):
    """Snimky btrfs jsou jen pro cteni - obnovene soubory musi jit upravit."""
    with contextlib.suppress(OSError):
        os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR)


def restore(sess, name, rels, to=None, log=print):
    """Obnovi soubory/slozky ze zalohy. Nikdy neprepisuje: existujici cil -> nove jmeno.
    to=None -> puvodni misto v domove, jinak do slozky to. Vrati [(z, kam)]."""
    when = time.strftime("%Y-%m-%d %H.%M", time.localtime(snap_time(name)))
    done = []
    for rel in rels:
        rel = clean_rel(rel)
        if not rel:
            raise BackupError(_("To restore the whole home folder use: luxos-backup restore --all"))
        src = (posix_join(snapshot_home(sess, name), rel) if sess.remote
               else os.path.join(snapshot_home(sess, name), rel))
        if not sess.remote and not os.path.lexists(src):
            raise BackupError(_("%s is not in the backup from %s") % ("~/" + rel, snap_label(name)))
        dst = os.path.join(to, os.path.basename(rel)) if to else os.path.join(home(), rel)
        if os.path.lexists(dst):
            dst = restored_name(dst, when)
        _copy_out(sess, src, dst)
        log(_("Restored %s to %s") % ("~/" + rel, dst))
        done.append((rel, dst))
    return done


def restore_all(sess, name, target=None, replace=False, log=print):
    """Obnovi celou domovskou slozku. Bez replace se existujici soubory nechaji (vrati pocet);
    s replace se nahradi a puvodni presunou do <cil>/.luxos-backup-replaced-<cas>."""
    target = target or home()
    src = snapshot_home(sess, name)
    backup_dir = os.path.join(target, ".luxos-backup-replaced-" + time.strftime("%Y%m%d-%H%M%S")) if replace else None
    os.makedirs(target, exist_ok=True)
    owner = None
    if os.geteuid() == 0:
        st = os.stat(target)
        owner = (st.st_uid, st.st_gid)
    if have("rsync"):
        cmd = ["rsync", "-aHX", "--info=stats1"]
        cmd += ["--backup", "--backup-dir", backup_dir] if replace else ["--ignore-existing"]
        if owner:
            cmd += [f"--chown={owner[0]}:{owner[1]}"]
        if sess.remote:
            cmd += ["-e", " ".join(shlex.quote(a) for a in sess.remote[0][:-1]), f"{sess.remote[0][-1]}:{src}/"]
        else:
            cmd += [src + "/"]
        cmd += [target.rstrip("/") + "/"]
        rc, err = run_rsync(cmd, env=ssh_env(sess.disk))
        if rc not in RSYNC_OK + (RSYNC_PARTIAL,):
            raise BackupError(err.strip()[-800:])
        skipped = 0
    else:
        if sess.remote:
            raise BackupError("rsync: not found")
        skipped = py_copy(src, target, skip_existing=not replace, backup_dir=backup_dir, one_fs=False)
        if owner:
            for cur, dnames, fnames in os.walk(target):
                for n in dnames + fnames:
                    with contextlib.suppress(OSError):
                        os.lchown(os.path.join(cur, n), *owner)
    log(_("Home folder restored from the backup from %s.") % snap_label(name))
    if backup_dir and os.path.isdir(backup_dir):
        log(_("Replaced files were moved to %s") % backup_dir)
    pk = posix_join(sess.remote[1], name, "system", "packages.txt") if sess.remote else \
        os.path.join(sess.root, name, "system", "packages.txt")
    if not sess.remote and os.path.exists(pk):
        log(_("Apps installed on the old system: %s (install them with: lux install $(cat FILE))") % pk)
    vault = os.path.join(sess.root, name, "safe", "vault")
    if not sess.remote and os.path.isfile(os.path.join(vault, "gocryptfs.conf")):
        log(_("The backup contains your encrypted Safe: %s (see the Safe documentation for restoring it)") % vault)
    return skipped


# ---- pridani a priprava disku ------------------------------------------------------
def add_local_disk(cfg, path, name=None):
    """Slozka na pripojenem disku (napr. /run/media/anna/USB)."""
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise BackupError(_("Folder not found: %s") % path)
    check_target_fs(path)
    uuid, target = fs_uuid(path)
    disk = {"id": new_disk_id(), "kind": "local", "name": name or os.path.basename(path.rstrip("/")) or path,
            "machine": machine_name(), "added": snap_name()}
    # Vymenny disk se pozna podle UUID (pripojuje se pokazde jinam); jinak pevna cesta
    if uuid and target and target != "/" and (target.startswith("/run/media/") or target.startswith("/media/")):
        disk["uuid"] = uuid
        rel = os.path.relpath(path, target)
        if rel != ".":
            disk["subdir"] = rel
        parent = luks_parent(uuid)
        if parent:
            disk["luks_uuid"], disk["encrypted"] = parent, True
    else:
        disk["path"] = path
    test = os.path.join(path, f".luxos-backup-test{os.getpid()}")
    try:
        os.makedirs(os.path.join(path, TOP), exist_ok=True)
        with open(test, "w"):
            pass
        os.unlink(test)
    except OSError as e:
        raise BackupError(_("Cannot write to %s: %s") % (path, e.strerror))
    _add(cfg, disk)
    return disk


def luks_parent(uuid):
    for d in flatten(lsblk()):
        if d.get("uuid") == uuid and d.get("type") == "crypt" and d.get("_parent"):
            return d["_parent"].get("uuid")
    return None


def _add(cfg, disk):
    for d in cfg["disks"]:
        same = [k for k in ("uuid", "path", "url", "host") if disk.get(k) and d.get(k) == disk.get(k)]
        if same and (disk["kind"] != "sftp" or d.get("path") == disk.get("path")):
            raise BackupError(_("This disk is already used for backups."))
    cfg["disks"].append(disk)
    save_config(cfg)


def parse_sftp(url):
    m = re.match(r"^(?:sftp|ssh)://(?:([^@/:]+)@)?([^/:]+)(?::(\d+))?(/.*)?$", url)
    if not m:
        raise BackupError(_("Use a network address like sftp://user@server/folder"))
    return {"user": m.group(1) or "", "host": m.group(2), "port": int(m.group(3) or 22),
            "path": m.group(4) or "."}


def add_sftp_disk(cfg, url, password=None, name=None, check=True):
    p = parse_sftp(url)
    disk = {"id": new_disk_id(), "kind": "sftp", "name": name or f"{p['host']}", "machine": machine_name(),
            "added": snap_name(), **p}
    if password:
        secret_set(disk["id"], _("LuxOS Backups: %s") % disk["name"], password)
    if check:
        with Session(disk) as sess:
            rc, _o, err = ssh_run(sess, "command -v rsync >/dev/null && mkdir -p -- " + shlex.quote(sess.remote[1]))
            if rc:
                secret_clear(disk["id"])
                raise BackupError(_("The server needs rsync for backups.") if rc == 127 or rc == 1 else err.strip())
    _add(cfg, disk)
    return disk


def add_smb_disk(cfg, url, password=None, size_gb=None, encrypt_pw=None, name=None):
    """Sitova slozka SMB: obraz disku <sdileni>/LuxOS-Backups/<pocitac>.img naformatovany jako btrfs."""
    p = smb_parse(url)
    disk = {"id": new_disk_id(), "kind": "smb", "name": name or f"{p['host']}/{p['share']}", "url": url,
            "machine": machine_name(), "added": snap_name()}
    if password:
        secret_set(disk["id"], _("LuxOS Backups: %s") % disk["name"], password)
    share = smb_fuse_path(disk)
    folder = os.path.join(share, TOP)
    os.makedirs(folder, exist_ok=True)
    image = os.path.join(folder, disk["machine"] + ".img")
    if not os.path.exists(image):
        st = os.statvfs(folder)
        free = st.f_bavail * st.f_frsize
        size = int(size_gb * (1 << 30)) if size_gb else int(free * 0.8)
        if size < (8 << 30):
            raise BackupError(_("The network disk needs at least 8 GB of free space."))
        with open(image, "wb") as f:
            f.truncate(size)                      # ridky soubor - zabira jen zapsana data
    rc, out, err = run(["udisksctl", "loop-setup", "-f", image, "--no-user-interaction"], timeout=60)
    m = re.search(r" as (/dev/loop\d+)", out)
    if rc or not m:
        raise BackupError(err.strip() or _("Could not open the backup image"))
    dev = m.group(1)
    try:
        uuids = format_device(dev, encrypt_pw, label="LuxOS Backups")
    finally:
        run(["udisksctl", "loop-delete", "-b", dev, "--no-user-interaction"], timeout=60)
    disk.update(uuids)
    if encrypt_pw:
        secret_set(luks_secret(disk), _("LuxOS Backups: %s") % disk["name"], encrypt_pw)
    _add(cfg, disk)
    return disk


def format_device(dev, passphrase=None, label="LuxOS Backups"):
    """Smaze a naformatuje zarizeni jako btrfs (volitelne v LUKS2) pres udisks (polkit).
    Vrati {"uuid": ..., "luks_uuid": ..., "encrypted": bool}."""
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
    obj = "/org/freedesktop/UDisks2/block_devices/" + os.path.basename(dev).replace("-", "_2d")
    opts = {"label": GLib.Variant("s", label), "take-ownership": GLib.Variant("b", True),
            "update-partition-type": GLib.Variant("b", True)}
    if passphrase:
        opts["encrypt.passphrase"] = GLib.Variant("s", passphrase)
        opts["encrypt.type"] = GLib.Variant("s", "luks2")
    try:
        bus.call_sync("org.freedesktop.UDisks2", obj, "org.freedesktop.UDisks2.Block", "Format",
                      GLib.Variant("(sa{sv})", ("btrfs", opts)), None, 0, 30 * 60 * 1000, None)
    except GLib.Error as e:
        raise BackupError(_("Could not prepare the disk: %s") % e.message)
    run(["udevadm", "settle"], timeout=30)
    info = next((d for d in flatten(lsblk()) if d.get("path") == dev), None) or {}
    if passphrase:
        inner = next((c for c in info.get("children") or [] if c.get("type") == "crypt"), {})
        return {"uuid": inner.get("uuid"), "luks_uuid": info.get("uuid"), "encrypted": True}
    return {"uuid": info.get("uuid"), "encrypted": False}


def prepare_disk(cfg, device, passphrase=None, name=None):
    """Smaze disk/oddil a pripravi ho pro zalohy (btrfs se zstd, volitelne sifrovani)."""
    system = {d.get("path") for d in flatten(lsblk()) if mountpoint(d) in ("/", "/home", "/boot", "/efi")}
    cands = {d["path"] for d in external_disks()} | {d["drive"] for d in external_disks()}
    if device not in cands:
        raise BackupError(_("%s is not an external disk.") % device)
    if device in system:
        raise BackupError(_("%s holds the running system.") % device)
    for d in flatten(lsblk()):
        if d.get("path") == device or (d.get("_parent") or {}).get("path") == device:
            for sub in flatten([d]):
                mp = mountpoint(sub)
                if mp:
                    run(["udisksctl", "unmount", "-b", sub["path"], "--no-user-interaction"], timeout=60)
            if d.get("type") == "crypt":
                run(["udisksctl", "lock", "-b", d["_parent"]["path"]], timeout=60)
    uuids = format_device(device, passphrase)
    disk = {"id": new_disk_id(), "kind": "local", "name": name or _("Backup disk"), "machine": machine_name(),
            "added": snap_name(), **{k: v for k, v in uuids.items() if v is not None}}
    if passphrase:
        secret_set(luks_secret(disk), _("LuxOS Backups: %s") % disk["name"], passphrase)
    _add(cfg, disk)
    # zapnout kompresi zstd pro novou slozku zaloh
    try:
        with Session(disk) as sess:
            ensure_root(sess)
            run(["btrfs", "property", "set", os.path.dirname(sess.root), "compression", "zstd"], timeout=30)
    except BackupError:
        pass
    return disk


def remove_disk(cfg, ident):
    disk = find_disk(cfg, ident)
    cfg["disks"] = [d for d in cfg["disks"] if d["id"] != disk["id"]]
    save_config(cfg)
    secret_clear(disk["id"])
    secret_clear(luks_secret(disk))
    return disk


def launch_gui(*args):
    """Okno Zaloh z jednorazove sluzby (luxos-backup-plug@): proces spusteny primo by systemd ukoncil
    spolu se sluzbou (KillMode=control-group) a bezel by s Nice=19 - vlastni prechodna jednotka."""
    cmd = ["luxos-backup-gui", *args]
    if os.environ.get("INVOCATION_ID") and shutil.which("systemd-run"):
        cmd = ["systemd-run", "--user", "--collect", "--quiet", "--", *cmd]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def plugged(cfg, device):
    """Pripojeny disk (udev -> luxos-backup-plug@.service): znamy = zaloha, novy = nabidka."""
    devs = list(flatten(lsblk()))
    dev = next((d for d in devs if d.get("path") == device or d.get("name") == os.path.basename(device)), None)
    if dev is None:
        return "unknown"
    uuids = {d.get("uuid") for d in flatten([dev]) if d.get("uuid")}
    known = [d for d in cfg["disks"] if d.get("uuid") in uuids or d.get("luks_uuid") in uuids]
    if known:
        if cfg.get("auto", True) and due(cfg):
            run_backup(known[0]["id"], log=lambda *_a: None)
        return "backup"
    ext = {d["path"] for d in external_disks()}
    if dev.get("path") not in ext or not dev.get("fstype") or dev.get("fstype") in ("swap",):
        return "ignored"
    key = dev.get("uuid") or dev.get("path")
    if key in cfg.get("declined", []):
        return "declined"
    label = dev.get("label") or dev.get("model") or dev.get("path")
    answer = notify(_("Use this disk for backups?"),
                    _("%s can keep automatic backups of your files.") % label,
                    action=("use", _("Use for Backups")))
    if answer == "use":
        launch_gui("--add", dev["path"])
        return "offered"
    if answer == NO_ANSWER:
        return "offered"            # nevidel/nestihl - nabidnout znovu pri dalsim pripojeni
    cfg = load_config()
    cfg.setdefault("declined", []).append(key)
    save_config(cfg)
    return "offered"
