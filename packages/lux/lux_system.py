#!/usr/bin/python3
"""lux_system - cely system LuxOS v jednom souboru LSL (/etc/luxos/system.lsl), jako configuration.nix.

  lux_system.py [volby] PRIKAZ [SOUBOR]

  show                 vypise konfiguraci podle soucasneho systemu (vychozi soubor pro stavajici instalace)
  init [--force]       zapise /etc/luxos/system.lsl ze soucasneho systemu                    (root)
  check [SOUBOR]       vyhodnoti a zkontroluje soubor (system nemeni)
  diff [SOUBOR]        co by se zmenilo (--json strojove)                                   (root)
  apply [SOUBOR]       snimek systemu (LuxOS Care), rozdil, potvrzeni a provedeni           (root)
  plan [SOUBOR]        vyhodnocena konfigurace jako JSON (ladeni)
  fix [SOUBOR]         oprava: vrati system do stavu podle souboru (= diff + apply se snimkem) (root)
  show --origin        sloucena konfigurace (soubor + zasady organizace) s puvodem kazde polozky
  locks [--json]       polozky zamcene organizaci (config.mkForce v /etc/luxos/system.d)

Volby: -y/--yes (bez potvrzeni), --json, --no-snapshot (apply bez snimku), --force (init prepise
       soubor; apply/fix smi odebrat nebo zmenit prave pouzivane sitove pripojeni),
       --no-policies (jen dany soubor, bez /etc/luxos/system.d)
       init --auto: jednorazove vytvoreni, jen kdyz soubor chybi (instalator, aktualizace lux);
       init --refresh: OEM po Pruvodci nastavenim - prepise jen dosud needitovany vygenerovany soubor

Hesla nikdy nejdou do vygenerovaneho souboru (ani otisky hesel uzivatelu, ani hesla Wi-Fi/VPN:
ta zustavaji v NetworkManageru).

Zasady organizace: /etc/luxos/system.d/NN-jmeno.lsl (root, needitovat; zapisuje LuxOS Directory nebo
GPO domeny). Slucuji se v poradi jmen (vyssi cislo prepise nizsi), lokalni soubor ma prednost pred
nimi, krome polozek s config.mkForce (zamceno - lokalni zmena je chyba). config.mkDefault = jen
doporuceni. Seznamy balicku, sluzeb, portu ... se spojuji. Co z fragmentu zmizi (odchod z organizace),
zustane, jak je (nic se samo neodinstaluje).

Bezpecnost: soubor se vyhodnocuje prikazem "lsl config" - cisty vyhodnocovac LSL bez souboru, site,
procesu a promennych prostredi, s casovym limitem. Root ho navic spousti jako uzivatel nobody nad
kopii souboru. Z LSL vznikne jen JSON; vse ostatni dela tento skript (Python) pres lux, systemctl,
useradd, ... Nic se neprovede bez zobrazeni rozdilu a potvrzeni (krome -y).

Spravuje se jen to, co v souboru je (chybejici klic = beze zmeny). Balicky a aplikace Flathubu, ktere
v souboru nikdy nebyly, se odeberou jen s "remove_unlisted": True; co se ze souboru smazalo od
posledniho apply, se odebere (stav v /var/lib/lux/system/applied.json). Uzivatele se nikdy nemazou.

Testy: LUX_SYSTEM_ROOT = jiny koren pro soubory, LUX_SYSTEM_BIN = adresar se vsemi nastroji
(zastupne skripty), LUX_SYSTEM_LSL = prikaz lsl.
"""
import configparser
import contextlib
import datetime
import difflib
import fcntl
import glob
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = os.environ.get("LUX_SYSTEM_ROOT", "").rstrip("/")


def P(path):
    """Cesta v (pripadne testovacim) koreni."""
    return ROOT + path


CONFIG = "/etc/luxos/system.lsl"
FRAGMENT_DIR = "/etc/luxos/system.d"
STATE_DIR = "/var/lib/lux/system"
APPLIED = STATE_DIR + "/applied.json"
POLICY_STATE = STATE_DIR + "/policy.json"       # zamky a fragmenty posledniho apply (cte i GUI, 0644)
DOMAIN_STATE = "/var/lib/luxos/domain/state.json"
HISTORY_DIR = STATE_DIR + "/history"
HISTORY_KEEP = 20
LOCK = "/run/lux/system.lock"
CARE_CONF = "/etc/luxos/care.conf"
SCHED_CONF = "/etc/luxos/scheduler.conf"            # planovac procesu (luxos-tweaks, luxos-care scheduler)
SCHEDULERS = ("lavd", "default")
KEYBOARD_CONF = "/etc/X11/xorg.conf.d/00-keyboard.conf"
GUARD_UNITS = {"enable": "luxos-guard.service", "home_snapshots": "luxos-guard-snapshot.timer"}
FIREWALL_UNIT = "ufw.service"
EVAL_TIMEOUT = 120

TOOLS = {
    "lsl": "/usr/bin/lsl", "setpriv": "/usr/bin/setpriv", "lux": "/usr/bin/lux",
    "lux_alpm.py": "/usr/lib/lux/lux_alpm.py", "lux-engine": "/usr/lib/lux/alpm/bin/lux-engine",
    "flatpak": "/usr/bin/flatpak", "systemctl": "/usr/bin/systemctl", "hostnamectl": "/usr/bin/hostnamectl",
    "timedatectl": "/usr/bin/timedatectl", "localectl": "/usr/bin/localectl", "locale-gen": "/usr/bin/locale-gen",
    "useradd": "/usr/bin/useradd", "usermod": "/usr/bin/usermod", "groupadd": "/usr/bin/groupadd",
    "gpasswd": "/usr/bin/gpasswd", "chpasswd": "/usr/bin/chpasswd", "ufw": "/usr/bin/ufw",
    "luxos-care": "/usr/bin/luxos-care", "grub-mkconfig": "/usr/bin/grub-mkconfig",
    "lux-domain": "/usr/bin/lux-domain", "nmcli": "/usr/bin/nmcli", "lpstat": "/usr/bin/lpstat",
    "lpoptions": "/usr/bin/lpoptions", "lpadmin": "/usr/bin/lpadmin", "lpinfo": "/usr/bin/lpinfo",
    "bootctl": "/usr/bin/bootctl", "powerprofilesctl": "/usr/bin/powerprofilesctl",
}
# Dalsi oblasti celeho systemu (sit, tiskarny, napajeni, zavadec, vychozi nastaveni novych uzivatelu ...)
NM_DIR = "/etc/NetworkManager/system-connections"
LOGIND_DROPIN = "/etc/systemd/logind.conf.d/zz-luxos-system.conf"
PPD_STATE = "/var/lib/power-profiles-daemon/state.ini"
POWERSAVER_MARK = "/run/luxos/powersaver"           # Sporic baterie zapnuty (profil meni sam)
NEW_USERS_CONF = "/etc/luxos/new-users.conf"         # cte luxos-session pri prvnim prihlaseni noveho uzivatele
FAILLOCK_CONF = "/etc/security/faillock.conf"
VCONSOLE_CONF = "/etc/vconsole.conf"
LUX_CONF = "/etc/lux/lux.conf"
EFIVARS = "/sys/firmware/efi/efivars"
EFI_LOADER_GUID = "4a67b082-0a4c-41cf-b6c7-440b29bb8c4f"
AUTO_STAMP = STATE_DIR + "/auto-init"                # init --auto uz probehl (smazany soubor se nevytvori znovu)
OEM_CONF = "/etc/luxos/oem.conf"
OEM_DONE = "/var/lib/luxos/oem/done"

# Balicky, bez kterych LuxOS nebo tento nastroj nefunguje - nikdy se neodeberou
PROTECTED_PACKAGES = {
    "base", "bash", "filesystem", "glibc", "systemd", "sudo", "python", "pyalpm", "linux-firmware",
    "lux", "lux-engine", "luxos-care", "luxos-keyring", "luxos-i18n", "luxos-branding", "luxos-desktop", "lsl",
}
KERNEL_RE = re.compile(r"^linux(-[a-z0-9]+)*$")
# Sluzby, ktere se nesmi vypnout (system by nenabehl nebo by neslo nic opravit)
PROTECTED_UNITS = re.compile(r"^(dbus.*|systemd-journald.*|systemd-logind.*|systemd-udevd.*|luxos-care.*"
                             r"|display-manager\.service|lightdm\.service)$")
# Parametry jadra, ktere patri instalatoru (disk, sifrovani) - v souboru se nespravuji
BOOT_PARAM_RE = re.compile(r"^(root|rootflags|rootfstype|cryptdevice|cryptkey|rd\.luks(\.[\w-]+)?|resume|resume_offset"
                           r"|initrd|init|BOOT_IMAGE|luxos\.[\w.-]+)(=.*)?$|^(rw|ro)$")

PKG_RE = re.compile(r"^[a-z0-9@_+][a-z0-9@._+-]*$")
APP_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+){2,}$")
UNIT_RE = re.compile(r"^[A-Za-z0-9:_.@\\-]+\.(service|socket|timer|path|target|mount)$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
HOST_RE = re.compile(r"^(?=.{1,64}$)[A-Za-z0-9]([A-Za-z0-9-]{0,62}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,62}[A-Za-z0-9])?)*$")
LOCALE_RE = re.compile(r"^[a-z]{2,3}(_[A-Z]{2})?(\.UTF-8)?(@[a-z]+)?$|^C\.UTF-8$")
TZ_RE = re.compile(r"^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+){0,2}$")
LAYOUT_RE = re.compile(r"^[a-z]{2,}(\([A-Za-z0-9_-]+\))?$")
XKB_OPT_RE = re.compile(r"^[a-z0-9_]+:[a-z0-9_]+$")
PORT_RE = re.compile(r"^(\d{1,5})(:(\d{1,5}))?(/(tcp|udp))?$")
PARAM_RE = re.compile(r"^[A-Za-z0-9_.,:=/+@-]+$")
HASH_RE = re.compile(r"^\$(y|gy|7|2[abxy]|6|5|1)\$[./A-Za-z0-9$=,-]+$")

# ---- preklady (luxos-i18n) -----------------------------------------------------------------
_TR = None


def _(text):
    global _TR
    if _TR is None:
        _TR = lambda s: s  # noqa: E731
        sys.path.insert(0, "/usr/lib/luxos/python")
        try:
            from luxos_i18n import _ as tr
            _TR = tr
        except ImportError:
            pass
    return _TR(text)


# ---- vystup --------------------------------------------------------------------------------
COLOR = os.environ.get("LUX_COLOR") == "always" or (
    os.environ.get("LUX_COLOR") is None and sys.stdout.isatty() and not os.environ.get("NO_COLOR"))
B, D, R, C, G, Y, E = (("\033[1m", "\033[2m", "\033[0m", "\033[38;2;167;123;255m", "\033[32m", "\033[33m", "\033[31m")
                       if COLOR else ("",) * 7)


def say(msg):
    print(f"{C}✦{R} {msg}", flush=True)


def ok(msg):
    print(f"{G}✓{R} {msg}", flush=True)


def warn(msg):
    sys.stdout.flush()
    print(f"{Y}!{R} {msg}", file=sys.stderr, flush=True)


class UserError(Exception):
    """Chyba pro uzivatele (uz prelozena); jeden nebo vic radku."""


class ApplyError(Exception):
    pass


def tool(name):
    d = os.environ.get("LUX_SYSTEM_BIN")
    if d:
        return os.path.join(d, name)
    if name == "lsl" and os.environ.get("LUX_SYSTEM_LSL"):
        return os.environ["LUX_SYSTEM_LSL"]
    return TOOLS[name]


def have(name):
    return os.access(tool(name), os.X_OK)


def capture(argv, check=False, input=None, timeout=300):
    """(navratovy kod, stdout, stderr); nikdy nevyhazuje (krome check=True)."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, input=input, timeout=timeout,
                           env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.TimeoutExpired) as e:
        if check:
            raise ApplyError(str(e)) from e
        return 127, "", str(e)
    if check and r.returncode != 0:
        raise ApplyError(((r.stderr or "") + (r.stdout or "")).strip()[-800:] or f"exit {r.returncode}")
    return r.returncode, r.stdout, r.stderr


def run(argv, input=None, stream=False, env=None):
    """Prikaz pri provadeni zmen; chyba -> ApplyError s koncem vystupu."""
    e = dict(os.environ, **(env or {}))
    try:
        if stream:
            r = subprocess.run(argv, input=input, text=True, env=e)
            if r.returncode != 0:
                raise ApplyError(_("%s failed (exit code %d)") % (os.path.basename(argv[0]), r.returncode))
            return ""
        r = subprocess.run(argv, input=input, capture_output=True, text=True, env=e, timeout=1800)
    except OSError as ex:
        raise ApplyError(f"{argv[0]}: {ex}") from ex
    except subprocess.TimeoutExpired as ex:
        raise ApplyError(f"{argv[0]}: timeout") from ex
    if r.returncode != 0:
        out = ((r.stderr or "") + (r.stdout or "")).strip()
        raise ApplyError(out[-800:] or _("%s failed (exit code %d)") % (os.path.basename(argv[0]), r.returncode))
    return r.stdout


def read(path, default=""):
    try:
        with open(P(path), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def read_kv(path):
    d = {}
    for line in read(path).splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def atomic_write(path, text, mode=0o644):
    path = P(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def set_kv(path, values, header=""):
    """KLIC=hodnota v souboru (ostatni radky zustanou); hodnota None klic odebere."""
    lines, seen = [], set()
    text = read(path, None)
    for line in (text.splitlines() if text is not None else ([header] if header else [])):
        k = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if k in values:
            if k not in seen and values[k] is not None:
                lines.append(f"{k}={values[k]}")
            seen.add(k)
        else:
            lines.append(line)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen and v is not None]
    atomic_write(path, "\n".join(lines) + "\n")


# ---- vyhodnoceni souboru LSL -----------------------------------------------------------------
SNAPSHOT_PATH_RE = re.compile(r"/tmp/lsl-program-\d+/lsl_config_snapshot_\d+\.lsl")


def _copy_sources(path, dest):
    """Kopie souboru a souboru *.lsl vedle nej (imports) do docasneho adresare -> cesta hlavniho souboru.
    "lsl config" chce jako vstup bezpecne jmeno modulu (napr. system.lsl, ne system.lsl.example)."""
    src_dir = os.path.dirname(path)
    name = os.path.basename(path)
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*\.lsl$", name):
        name = "system.lsl"
    n = 0
    for dirpath, dirs, files in os.walk(src_dir):
        rel = os.path.relpath(dirpath, src_dir)
        dirs[:] = [] if rel.count(os.sep) >= 2 else [d for d in dirs if not os.path.islink(os.path.join(dirpath, d))]
        for f in files:
            p = os.path.join(dirpath, f)
            if f.endswith(".lsl") and not os.path.islink(p) and n < 200 and os.path.isfile(p):
                out = os.path.normpath(os.path.join(dest, rel, f))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copyfile(p, out)
                n += 1
    main = os.path.join(dest, name)
    shutil.copyfile(path, main)
    return main


# Fragment zasad: config.mkForce/mkDefault by "lsl config" rozpustil (do JSON se priorita nedostane),
# proto se v kopii fragmentu nahradi funkcemi, ktere hodnotu oznaci. Funkce jsou na zacatku souboru
# (cisla radku v chybach se o POLICY_LINES posunou zpet).
POLICY_HELPERS = """function lux_policy_force(value):
    return {"__lux_policy": "force", "value": value}
end
function lux_policy_default(value):
    return {"__lux_policy": "default", "value": value}
end
"""
POLICY_LINES = POLICY_HELPERS.count("\n")
LINE_RE = re.compile(r"(line |:)(\d+)")


def policy_source(text):
    return POLICY_HELPERS + text.replace("config.mkForce(", "lux_policy_force(").replace(
        "config.mkDefault(", "lux_policy_default(")


def evaluate(path, fragment=False):
    """Soubor LSL -> slovnik (JSON z "lsl config"). Chyba -> UserError.
    fragment=True: zasada z /etc/luxos/system.d (bez imports, mkForce/mkDefault oznacene)."""
    if not os.path.isfile(path):
        raise UserError(_("The configuration file %s does not exist. Create it from this computer with: "
                          "sudo lux system init") % path)
    lsl = tool("lsl")
    if not os.access(lsl, os.X_OK):
        raise UserError(_("LSL is needed to read the configuration (lux install lsl)."))
    shown = os.path.abspath(path)
    with tempfile.TemporaryDirectory(prefix="lux-system-") as tmp:
        env = {"PATH": "/usr/bin", "LANG": "C.UTF-8", "HOME": tmp, "NO_COLOR": "1"}
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        try:
            if fragment:
                target = os.path.join(src, "policy.lsl")
                with open(shown, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                with open(target, "w", encoding="utf-8") as f:
                    f.write(policy_source(text))
            else:
                target = _copy_sources(shown, src)
        except OSError as e:
            raise UserError(_("Cannot read the configuration: %s") % e) from e
        argv = [lsl, "config", target]
        if os.geteuid() == 0 and not os.environ.get("LUX_SYSTEM_BIN"):
            # Root: cisty vyhodnocovac navic bez prav (nobody) nad kopii souboru
            for dirpath, _dirs, files in os.walk(tmp):
                os.chown(dirpath, 65534, 65534)
                for f in files:
                    os.chown(os.path.join(dirpath, f), 65534, 65534)
            argv = [tool("setpriv"), "--reuid=65534", "--regid=65534", "--clear-groups", "--no-new-privs"] + argv
        try:
            r = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=EVAL_TIMEOUT, cwd=tmp)
        except subprocess.TimeoutExpired as e:
            raise UserError(_("Reading the configuration took too long (endless loop?).")) from e
        except OSError as e:
            raise UserError(str(e)) from e
    out = (r.stdout or "").strip()
    if r.returncode == 0:
        try:
            data = json.loads(out)
        except ValueError:
            data = None
        if isinstance(data, dict):
            return data
        raise UserError(_("The configuration must set config = { ... } (a dictionary)."))
    msg = "\n".join(x for x in ((r.stdout or "").strip(), (r.stderr or "").strip()) if x)
    msg = SNAPSHOT_PATH_RE.sub(shown, msg).replace(target, shown).replace(src, os.path.dirname(shown))
    if fragment:
        msg = LINE_RE.sub(lambda m: m.group(1) + str(max(1, int(m.group(2)) - POLICY_LINES)), msg)
    if r.returncode == 124:
        msg = _("Reading the configuration took too long (endless loop?).")
    hint = ""
    if "expected an expression" in msg or "expected comma" in msg:
        hint = "\n" + _("Hint: items of a list [ ] are separated by commas, without a comma after the last one.")
    elif "may load only the config module" in msg:
        hint = "\n" + _("Hint: the configuration may only use 'load config'; it cannot run programs or read files.")
    elif "Impure configuration identifier" in msg:
        hint = "\n" + _("Hint: the configuration cannot run programs, read files or use the network.")
    raise UserError(_("Error in the configuration %s:") % shown + "\n" + msg.strip() + hint)


# ---- zasady organizace: /etc/luxos/system.d ----------------------------------------------------
FRAGMENT_RE = re.compile(r"^\d{2}-[A-Za-z0-9][A-Za-z0-9_.-]*\.lsl$")
LV_DEFAULT, LV_ORG, LV_LOCAL, LV_FORCE = 0, 1, 2, 3
# Seznamy, ktere se mezi vrstvami spojuji (ostatni seznamy se nahrazuji celou hodnotou)
UNION_PATHS = {("packages",), ("drivers",), ("flatpaks",), ("groups",), ("services", "enable"), ("services", "disable"),
               ("firewall", "allow"), ("kernel", "params"), ("domain", "admins"), ("domain", "allow_groups")}
POLICY_META_KEYS = ("organization", "name")
MISSING = object()


class Origin:
    """Odkud hodnota je: lokalni soubor nebo zasada organizace (fragment v system.d)."""

    def __init__(self, kind, file, organization="", name=""):
        self.kind, self.file, self.organization, self.name = kind, file, organization, name

    def label(self):
        if self.kind == "local":
            return _("local file %s") % self.file
        who = self.organization or _("organization")
        pol = f" „{self.name}“" if self.name else ""
        return f"{who}{pol} ({os.path.basename(self.file)})"

    def json(self):
        return {"kind": self.kind, "file": self.file, "organization": self.organization, "name": self.name,
                "label": self.label()}


def is_union(path):
    return tuple(path) in UNION_PATHS or (len(path) == 3 and path[0] == "users" and path[2] == "groups")


def dotted(path):
    return ".".join(str(p) for p in path)


def _jkey(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


class Layers:
    """Slouceni zasad organizace a lokalniho souboru s puvodem a zamky kazde polozky.

    Urovne: mkDefault v zasade < bezna hodnota zasady < lokalni soubor < mkForce v zasade.
    Mezi zasadami stejne urovne vyhrava pozdejsi (vyssi cislo). Dva ruzne mkForce = chyba.
    """

    def __init__(self):
        self.value = {}
        self.level = {}        # cesta (tuple) listu -> uroven
        self.origin = {}       # cesta listu -> Origin
        self.locks = {}        # cesta (list nebo cely podstrom) -> Origin (config.mkForce)
        self.items = {}        # (cesta seznamu, polozka JSON) -> [Origin, ...]
        self.item_locks = {}   # (cesta seznamu, polozka JSON) -> Origin
        self.fragments = []    # [(Origin, sha256)]
        self.errors = []

    # -- pristup k hodnotam --
    def get(self, path):
        node = self.value
        for k in path:
            if not isinstance(node, dict) or k not in node:
                return MISSING
            node = node[k]
        return node

    def set(self, path, value):
        node = self.value
        for k in path[:-1]:
            if not isinstance(node.get(k), dict):
                node[k] = {}
            node = node[k]
        node[path[-1]] = value

    @staticmethod
    def _under(d, path):
        n = len(path)
        return [p for p in d if tuple(p[:n]) == tuple(path)]

    def _drop(self, path):
        for d in (self.level, self.origin):
            for p in self._under(d, path):
                del d[p]
        for key in [k for k in self.items if tuple(k[0][:len(path)]) == tuple(path)]:
            del self.items[key]

    def lock_of(self, path):
        """Zamek na ceste nebo na nekterem z predku -> Origin | None."""
        for i in range(len(path), 0, -1):
            if tuple(path[:i]) in self.locks:
                return self.locks[tuple(path[:i])]
        return None

    def _same(self, path, value):
        return _jkey(self.get(path)) == _jkey(value)

    def locked_error(self, path, org):
        self.errors.append(_("%s: set by the organization %s, it cannot be changed here") % (dotted(path), org.label()))

    def conflict_error(self, path, a, b):
        self.errors.append(_("%s: the policies %s and %s set different values") % (dotted(path), a.label(), b.label()))

    # -- slouceni --
    def put(self, path, value, level, origin):
        path = tuple(path)
        if isinstance(value, dict) and "__lux_policy" in value and set(value) <= {"__lux_policy", "value"}:
            kind = value.get("__lux_policy")
            if origin.kind == "org":
                level = LV_FORCE if kind == "force" else LV_DEFAULT
            value = value.get("value")
            if level == LV_FORCE and path:
                prev = self.lock_of(path)
                if prev is not None and prev is not origin and self.get(path) is not MISSING \
                        and not self._same(path, value):
                    self.conflict_error(path, prev, origin)
                    return
                if not is_union(path):
                    # zamek celeho podstromu (i polozky, ktere zasada nevyjmenovala)
                    self.locks.setdefault(path, origin)
        if isinstance(value, dict) and not is_union(path):
            cur = self.get(path) if path else self.value
            if path and not isinstance(cur, dict):
                if cur is not MISSING and not self._may_replace(path, level, origin, value):
                    return
                self._drop(path)
                self.set(path, {})
            for k, v in value.items():
                self.put(path + (k,), v, level, origin)
            return
        if is_union(path) and isinstance(value, (list, str)):
            self._put_union(path, [value] if isinstance(value, str) else value, level, origin)
            return
        cur = self.get(path)
        if cur is MISSING:
            lk = self.lock_of(path)
            if lk is not None and lk is not origin and (origin.kind == "local" or level < LV_FORCE):
                if origin.kind == "local":
                    self.locked_error(path, lk)
                return
            self.set(path, value)
            self.level[path], self.origin[path] = level, origin
            return
        if not self._may_replace(path, level, origin, value):
            return
        self._drop(path)
        self.set(path, value)
        self.level[path], self.origin[path] = level, origin

    def _may_replace(self, path, level, origin, value):
        """Smi hodnota s urovni level nahradit soucasnou hodnotu na ceste (vcetne podstromu)?"""
        levels = [self.level[p] for p in self._under(self.level, path)] or [LV_DEFAULT]
        cur_level = max(levels)
        lk = self.lock_of(path) or next((self.locks[p] for p in self._under(self.locks, path)), None)
        if cur_level == LV_FORCE or (lk is not None and lk is not origin):
            if self._same(path, value):
                return False
            owner = lk or self.origin.get(path) or origin
            if origin.kind == "local":
                self.locked_error(path, owner)
            elif level == LV_FORCE:
                self.conflict_error(path, owner, origin)
            return False
        return level >= cur_level

    def _put_union(self, path, values, level, origin):
        cur = self.get(path)
        lk = self.lock_of(path)
        if cur is MISSING and lk is not None and lk is not origin:
            if values and origin.kind == "local":
                self.locked_error(path, lk)
            return
        if not isinstance(cur, list):
            if cur is not MISSING:
                self._drop(path)
            cur = []
        lk = self.lock_of(path)
        for v in values:
            key = (path, _jkey(v))
            if v not in cur:
                if lk is not None and lk is not origin:
                    if origin.kind == "local":
                        self.locked_error(path, lk)
                    continue
                cur.append(v)
            owners = self.items.setdefault(key, [])
            if origin not in owners:
                owners.append(origin)
            if level == LV_FORCE:
                self.item_locks.setdefault(key, origin)
        self.set(path, cur)
        self.level[path] = max(self.level.get(path, LV_DEFAULT), min(level, LV_LOCAL))
        self.origin.setdefault(path, origin)

    def check_conflicts(self):
        """Zamcena polozka "zapnout" nesmi byt lokalne ve "vypnout" (a naopak)."""
        for a, b in ((("services", "enable"), ("services", "disable")),
                     (("services", "disable"), ("services", "enable"))):
            for (p, k), org in self.item_locks.items():
                if p != a:
                    continue
                owners = self.items.get((b, k), [])
                if any(o.kind == "local" for o in owners):
                    self.locked_error(b, org)

    # -- dotazy --
    def origins(self, path, item=MISSING):
        """Puvody hodnoty (nebo polozky seznamu) na ceste a pod ni -> [Origin]."""
        path = tuple(path)
        if item is not MISSING:
            out = list(self.items.get((path, _jkey(item)), []))
        else:
            out = [self.origin[p] for p in self._under(self.origin, path) if not is_union(p)]
            for (p, _k), owners in self.items.items():
                if tuple(p[:len(path)]) == path:
                    out += owners
        uniq = []
        for o in out:
            if o not in uniq:
                uniq.append(o)
        return uniq

    def local_items(self, path, values):
        """Polozky seznamu, ktere chce lokalni soubor (jen ty se po odebrani ze souboru odinstaluji)."""
        out = []
        for v in values:
            owners = self.items.get((tuple(path), _jkey(v)))
            if owners is None or any(o.kind == "local" for o in owners):
                out.append(v)
        return out

    def lock_list(self):
        """[(cesta, polozka nebo None, Origin)] - zamcene polozky."""
        out = [(dotted(p), None, o) for p, o in self.locks.items()]
        out += [(dotted(p), json.loads(k), o) for (p, k), o in self.item_locks.items() if self.lock_of(p) is None]
        return sorted(out, key=lambda x: (x[0], _jkey(x[1])))

    def policy_json(self):
        return {"fragments": [dict(o.json(), sha256=sha) for o, sha in self.fragments],
                "locks": [{"path": p, "item": i, "origin": o.json()} for p, i, o in self.lock_list()]}


def fragment_files():
    """Fragmenty zasad v poradi slouceni; soubor, ktery muze menit nekdo jiny nez root -> UserError."""
    d = P(FRAGMENT_DIR)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    out = []
    for n in names:
        p = os.path.join(d, n)
        if not n.endswith(".lsl"):
            continue
        if not FRAGMENT_RE.match(n):
            warn(_("Ignored policy file %s (the name must be NN-name.lsl)") % p)
            continue
        st = os.lstat(p)
        if os.path.islink(p) or not os.path.isfile(p):
            warn(_("Ignored policy file %s (not a regular file)") % p)
            continue
        if st.st_mode & 0o022 or (not ROOT and st.st_uid != 0):
            raise UserError(_("The policy file %s may be changed by other users than root; fix it with: "
                              "sudo chown root:root %s && sudo chmod 644 %s") % (p, p, p))
        out.append(p)
    return out


def file_sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def _kb_short(raw):
    if isinstance(raw.get("keyboard"), (list, str)):
        raw["keyboard"] = {"layouts": raw["keyboard"]}
    return raw


def merge(path, policies=True):
    """Zasady organizace + lokalni soubor -> Layers (bez normalizace). Chyba vyhodnoceni -> UserError."""
    lay = Layers()
    frags = fragment_files() if policies else []
    for f in frags:
        raw = evaluate(f, fragment=True)
        meta = raw.pop("policy", None) or {}
        if not isinstance(meta, dict):
            meta = {}
            lay.errors.append(f"{f}: policy: " + _("must be %s") % _("a dictionary { }"))
        for k in meta:
            if k not in POLICY_META_KEYS:
                lay.errors.append(f"{f}: policy: " + _("unknown setting \"%s\"") % k)
        origin = Origin("org", f, str(meta.get("organization", "")), str(meta.get("name", "")))
        lay.fragments.append((origin, file_sha(f)))
        lay.put((), _kb_short(raw), LV_ORG, origin)
    if os.path.isfile(path) or not frags:
        raw = evaluate(path)
        if "policy" in raw:
            lay.errors.append("config: " + _("\"policy\" belongs only to organization policies in %s") % FRAGMENT_DIR)
            raw.pop("policy")
        lay.put((), _kb_short(raw), LV_LOCAL, Origin("local", path))
    lay.check_conflicts()
    return lay


# ---- kontrola a normalizace -------------------------------------------------------------------
TOP_KEYS = ("hostname", "timezone", "locale", "formats", "keyboard", "console", "packages", "drivers", "flatpaks",
            "remove_unlisted", "services", "groups", "users", "network", "printers", "power", "boot", "care", "guard",
            "firewall", "security", "kernel", "new_users", "repos", "domain")
DOMAIN_KEYS = ("admins", "allow_groups", "offline_days", "admin_offline_days")
# Jmeno skupiny v domene (AD): i mezery a diakritika ("Domain Admins", "Účtárna"), bez ridicich znaku
DOMAIN_GROUP_RE = re.compile(r"^(?! )[^\x00-\x1f\x7f\"\\:,/=+<>#;]{1,64}(?<! )$")
USER_KEYS = ("description", "groups", "shell", "uid", "password_hash")


class Checker:
    def __init__(self):
        self.errors = []

    def err(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def unknown(self, where, key, known):
        near = difflib.get_close_matches(key, known, 1)
        hint = (" " + _("(did you mean \"%s\"?)") % near[0]) if near else ""
        self.err(where, _("unknown setting \"%s\"") % key + hint)

    def typed(self, where, value, types, label):
        if isinstance(value, bool) and bool not in types:
            ok_ = False
        else:
            ok_ = isinstance(value, types)
        if not ok_:
            self.err(where, _("must be %s") % _(label))
        return ok_

    def str_list(self, where, value, regex, what):
        if isinstance(value, str):
            value = [value]
        if not self.typed(where, value, (list,), "a list of texts"):
            return []
        out = []
        for i, v in enumerate(value):
            if not isinstance(v, str) or not regex.match(v):
                self.err(f"{where}[{i}]", _("\"%s\" is not a valid %s") % (v, _(what)))
            elif v not in out:
                out.append(v)
        return out


def unit_name(name):
    return name if "." in name and name.rsplit(".", 1)[1] in ("service", "socket", "timer", "path", "target", "mount") \
        else name + ".service"


def normalize(raw):
    """Vyhodnoceny slovnik -> (konfigurace, chyby). Spravuje se jen to, co v souboru je."""
    ck = Checker()
    cfg = {}
    for key in raw:
        if key not in TOP_KEYS:
            ck.unknown("config", key, TOP_KEYS)
    if "hostname" in raw and ck.typed("hostname", raw["hostname"], (str,), "a text"):
        if HOST_RE.match(raw["hostname"]):
            cfg["hostname"] = raw["hostname"]
        else:
            ck.err("hostname", _("\"%s\" is not a valid %s") % (raw["hostname"], _("computer name")))
    if "timezone" in raw and ck.typed("timezone", raw["timezone"], (str,), "a text"):
        tz = raw["timezone"]
        if TZ_RE.match(tz) and ".." not in tz and (os.path.isfile(P("/usr/share/zoneinfo/" + tz))
                                                   or not os.path.isdir(P("/usr/share/zoneinfo"))):
            cfg["timezone"] = tz
        else:
            ck.err("timezone", _("unknown time zone \"%s\" (e.g. \"Europe/Prague\")") % tz)
    if "locale" in raw and ck.typed("locale", raw["locale"], (str,), "a text"):
        loc = raw["locale"]
        supported = read("/usr/share/i18n/SUPPORTED")
        if LOCALE_RE.match(loc) and (not supported or re.search(r"^" + re.escape(loc) + r" ", supported, re.M)):
            cfg["locale"] = loc
        else:
            ck.err("locale", _("unknown language setting \"%s\" (e.g. \"cs_CZ.UTF-8\")") % loc)
    if "keyboard" in raw:
        kb = raw["keyboard"]
        if isinstance(kb, (list, str)):
            kb = {"layouts": kb}
        if ck.typed("keyboard", kb, (dict,), "a dictionary { }"):
            for k in kb:
                if k not in ("layouts", "options"):
                    ck.unknown("keyboard", k, ("layouts", "options"))
            layouts = ck.str_list("keyboard.layouts", kb.get("layouts", []), LAYOUT_RE, "keyboard layout")
            if not layouts:
                ck.err("keyboard.layouts", _("at least one layout is needed (e.g. [\"us\", \"cz\"])"))
            elif len(layouts) > 4:
                ck.err("keyboard.layouts", _("at most 4 layouts"))
            opts = kb.get("options", [])
            opts = ck.str_list("keyboard.options", [o for o in opts.split(",") if o] if isinstance(opts, str) else opts,
                               XKB_OPT_RE, "keyboard option")
            cfg["keyboard"] = {"layouts": layouts, "options": opts}
    if "packages" in raw:
        cfg["packages"] = ck.str_list("packages", raw["packages"], PKG_RE, "package name")
    if "flatpaks" in raw:
        cfg["flatpaks"] = ck.str_list("flatpaks", raw["flatpaks"], APP_ID_RE, "Flathub app ID")
    if "remove_unlisted" in raw and ck.typed("remove_unlisted", raw["remove_unlisted"], (bool,), "True or False"):
        cfg["remove_unlisted"] = raw["remove_unlisted"]
    if "services" in raw:
        sv = raw["services"]
        if ck.typed("services", sv, (dict,), "a dictionary { }"):
            for k in sv:
                if k not in ("enable", "disable"):
                    ck.unknown("services", k, ("enable", "disable"))
            en = [unit_name(u) for u in ck.str_list("services.enable", sv.get("enable", []), re.compile(r"^[A-Za-z0-9:_.@\\-]+$"), "service name")]
            dis = [unit_name(u) for u in ck.str_list("services.disable", sv.get("disable", []), re.compile(r"^[A-Za-z0-9:_.@\\-]+$"), "service name")]
            for u in en + dis:
                if not UNIT_RE.match(u):
                    ck.err("services", _("\"%s\" is not a valid %s") % (u, _("service name")))
            for u in sorted(set(en) & set(dis)):
                ck.err("services", _("%s is both in enable and disable") % u)
            for u in dis:
                if PROTECTED_UNITS.match(u):
                    ck.err("services.disable", _("%s is needed by LuxOS and cannot be turned off here") % u)
            cfg["services"] = {"enable": en, "disable": dis}
    if "groups" in raw:
        cfg["groups"] = ck.str_list("groups", raw["groups"], USER_RE, "group name")
    if "users" in raw:
        us = raw["users"]
        if ck.typed("users", us, (dict,), "a dictionary { }"):
            cfg["users"] = {}
            for name, u in us.items():
                where = f"users.{name}"
                if not USER_RE.match(name) or name == "root":
                    ck.err(where, _("\"%s\" is not a valid %s") % (name, _("user name")))
                    continue
                if u is None:
                    u = {}
                if not ck.typed(where, u, (dict,), "a dictionary { }"):
                    continue
                for k in u:
                    if k not in USER_KEYS:
                        ck.unknown(where, k, USER_KEYS + ("password",))
                    if k == "password":
                        ck.err(where, _("never write passwords into the file; use password_hash (from: openssl passwd -6) "
                                        "or set the password with: sudo passwd %s") % name)
                nu = {}
                if u.get("description") is not None and ck.typed(where + ".description", u["description"], (str,), "a text"):
                    if re.search(r"[:\n\x00-\x1f]", u["description"]):
                        ck.err(where + ".description", _("must not contain ':' or control characters"))
                    else:
                        nu["description"] = u["description"]
                if "groups" in u:
                    nu["groups"] = ck.str_list(where + ".groups", u["groups"] or [], USER_RE, "group name")
                if u.get("shell") is not None and ck.typed(where + ".shell", u["shell"], (str,), "a text"):
                    shells = [s.strip() for s in read("/etc/shells").splitlines() if s.strip().startswith("/")]
                    # nologin/false: ucet bez prihlaseni (neni v /etc/shells, ale je platny)
                    if u["shell"].startswith("/") and (not shells or u["shell"] in shells
                                                       or os.path.basename(u["shell"]) in ("nologin", "false")):
                        nu["shell"] = u["shell"]
                    else:
                        ck.err(where + ".shell", _("\"%s\" is not in /etc/shells") % u["shell"])
                if u.get("uid") is not None and ck.typed(where + ".uid", u["uid"], (int,), "a number"):
                    if 1000 <= u["uid"] < 60000:
                        nu["uid"] = u["uid"]
                    else:
                        ck.err(where + ".uid", _("must be between 1000 and 59999"))
                if u.get("password_hash") is not None and ck.typed(where + ".password_hash", u["password_hash"], (str,), "a text"):
                    if HASH_RE.match(u["password_hash"]):
                        nu["password_hash"] = u["password_hash"]
                    else:
                        ck.err(where + ".password_hash",
                               _("this is not a password hash (it must start with $y$, $6$ ...; create it with: openssl passwd -6)"))
                cfg["users"][name] = nu
    if "care" in raw:
        ca = raw["care"]
        if ck.typed("care", ca, (dict,), "a dictionary { }"):
            nc = {}
            for k, v in ca.items():
                if k == "mode":
                    if v in ("carefree", "classic"):
                        nc["mode"] = v
                    else:
                        ck.err("care.mode", _("must be \"carefree\" or \"classic\""))
                elif k == "snapshots":
                    if ck.typed("care.snapshots", v, (bool,), "True or False"):
                        nc["snapshots"] = v
                elif k == "keep_snapshots":
                    if ck.typed("care.keep_snapshots", v, (int,), "a number") and not 2 <= v <= 50:
                        ck.err("care.keep_snapshots", _("must be between 2 and 50"))
                    elif isinstance(v, int) and not isinstance(v, bool):
                        nc["keep_snapshots"] = v
                elif k in ("protect", "verify"):
                    if ck.typed("care." + k, v, (bool,), "True or False"):
                        nc[k] = v
                else:
                    ck.unknown("care", k, ("mode", "snapshots", "keep_snapshots", "protect", "verify"))
            cfg["care"] = nc
    if "guard" in raw:
        gu = raw["guard"]
        if ck.typed("guard", gu, (dict,), "a dictionary { }"):
            ng = {}
            for k, v in gu.items():
                if k in GUARD_UNITS:
                    if ck.typed("guard." + k, v, (bool,), "True or False"):
                        ng[k] = v
                else:
                    ck.unknown("guard", k, tuple(GUARD_UNITS))
            cfg["guard"] = ng
    if "firewall" in raw:
        fw = raw["firewall"]
        if ck.typed("firewall", fw, (dict,), "a dictionary { }"):
            nf = {}
            for k, v in fw.items():
                if k == "enable":
                    if ck.typed("firewall.enable", v, (bool,), "True or False"):
                        nf["enable"] = v
                elif k == "allow":
                    nf["allow"] = ck.str_list("firewall.allow", v, PORT_RE, "port (e.g. \"22/tcp\")")
                    for p in nf["allow"]:
                        m = PORT_RE.match(p)
                        if not 1 <= int(m.group(1)) <= 65535 or (m.group(3) and not int(m.group(1)) < int(m.group(3)) <= 65535):
                            ck.err("firewall.allow", _("\"%s\" is not a valid %s") % (p, _("port (e.g. \"22/tcp\")")))
                else:
                    ck.unknown("firewall", k, ("enable", "allow"))
            cfg["firewall"] = nf
    if "kernel" in raw:
        kn = raw["kernel"]
        if ck.typed("kernel", kn, (dict,), "a dictionary { }"):
            for k in kn:
                if k not in ("params", "scheduler"):
                    ck.unknown("kernel", k, ("params", "scheduler"))
            nk = {}
            if "params" in kn:
                params = ck.str_list("kernel.params", kn.get("params", []), PARAM_RE, "kernel parameter")
                for p in params:
                    if BOOT_PARAM_RE.match(p):
                        ck.err("kernel.params", _("%s is set by the installer (disk, encryption) and cannot be changed here") % p)
                nk["params"] = params
            if "scheduler" in kn:
                if kn["scheduler"] in SCHEDULERS:
                    nk["scheduler"] = kn["scheduler"]
                else:
                    ck.err("kernel.scheduler", _("must be one of: %s") % ", ".join(SCHEDULERS))
            cfg["kernel"] = nk
    if "domain" in raw:
        dm = raw["domain"]
        if ck.typed("domain", dm, (dict,), "a dictionary { }"):
            nd = {}
            for k, v in dm.items():
                if k in ("admins", "allow_groups"):
                    nd[k] = ck.str_list("domain." + k, v, DOMAIN_GROUP_RE, "group name")
                elif k in ("offline_days", "admin_offline_days"):
                    if ck.typed("domain." + k, v, (int,), "a number"):
                        if 0 <= v <= 180:
                            nd[k] = v
                        else:
                            ck.err("domain." + k, _("must be between 0 and 180"))
                else:
                    ck.unknown("domain", k, DOMAIN_KEYS)
            if nd.get("admin_offline_days", 0) > nd.get("offline_days", 180):
                ck.err("domain.admin_offline_days", _("must not be longer than domain.offline_days"))
            cfg["domain"] = nd
    normalize_more(raw, ck, cfg)
    if "services" in cfg:
        managed = {u: k for k, u in GUARD_UNITS.items()} if "guard" in cfg else {}
        for u in cfg["services"]["enable"] + cfg["services"]["disable"]:
            if u in managed and managed[u] in cfg["guard"]:
                ck.err("services", _("%s is set in \"guard\"; remove it from services") % u)
            if u == FIREWALL_UNIT and "enable" in cfg.get("firewall", {}):
                ck.err("services", _("%s is set in \"firewall\"; remove it from services") % u)
    return cfg, ck.errors


# ---- kontrola dalsich oblasti (sit, tiskarny, napajeni, zavadec, ...) -------------------------------
LC_KEYS = ("LC_CTYPE", "LC_NUMERIC", "LC_TIME", "LC_COLLATE", "LC_MONETARY", "LC_MESSAGES", "LC_PAPER", "LC_NAME",
           "LC_ADDRESS", "LC_TELEPHONE", "LC_MEASUREMENT", "LC_IDENTIFICATION")
CONSOLE_RE = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")
CON_NAME_RE = re.compile(r"^(?! )[^\x00-\x1f\x7f]{1,64}(?<! )$")
IFACE_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,15}$")
NET_TYPES = ("wifi", "ethernet")
WIFI_SECURITY = ("none", "wep", "wpa-psk", "sae", "owe", "wpa-eap", "wpa-eap-suite-b-192")
IP_METHODS = {"ipv4": ("auto", "manual", "disabled", "link-local", "shared"),
              "ipv6": ("auto", "dhcp", "manual", "disabled", "ignore", "link-local", "shared")}
CON_KEYS = ("type", "autoconnect", "interface", "ssid", "security", "ipv4", "ipv6", "proxy")
IP_KEYS = ("method", "addresses", "gateway", "dns")
# Tajemstvi nikdy do souboru: hesla Wi-Fi/VPN a klice 802.1x zustavaji v NetworkManageru
SECRET_WORDS = ("password", "psk", "secret", "passphrase", "wep-key", "private-key", "pin", "key")
PRINTER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,127}$")
URI_RE = re.compile(r"^[a-z][a-z0-9+.-]*:\S+$")
LID_ACTIONS = ("suspend", "hibernate", "suspend-then-hibernate", "lock", "poweroff", "ignore")
PROFILES = ("power-saver", "balanced", "performance")
ENTRY_RE = re.compile(r"^[A-Za-z0-9_.@+-]{1,128}$")
DESKTOP_ID_RE = re.compile(r"^[A-Za-z0-9_.+-]{1,128}$")
THEMES = ("light", "dark", "auto")
NEW_USER_KEYS = ("theme", "wallpaper", "dock", "browser", "text_editor", "mail", "lock_after_minutes",
                 "screen_off_minutes")
FAILLOCK_KEYS = {"deny": (1, 1000), "fail_interval": (1, 86400), "unlock_time": (1, 86400)}
REPO_KEYS = ("list", "community", "review_build_scripts", "flatpak_updates")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _ip_ok(text, prefix=False):
    try:
        if prefix:
            ipaddress.ip_interface(text)
            return "/" in text
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def desktop_id(name):
    return name if name.endswith(".desktop") or name == "trash" else name + ".desktop"


def _secret_key(k):
    k = str(k).lower()
    return any(w in k for w in SECRET_WORDS)


def normalize_network(net, ck):
    out = {}
    if not ck.typed("network", net, (dict,), "a dictionary { }"):
        return out
    for k in net:
        if k != "connections":
            ck.unknown("network", k, ("connections",))
    cons = net.get("connections", {})
    if not ck.typed("network.connections", cons, (dict,), "a dictionary { }"):
        return out
    out["connections"] = {}
    for name, c in cons.items():
        where = f"network.connections.{name}"
        if not CON_NAME_RE.match(name):
            ck.err(where, _("\"%s\" is not a valid %s") % (name, _("connection name")))
            continue
        if c is None:
            c = {}
        if not ck.typed(where, c, (dict,), "a dictionary { }"):
            continue
        nc = {}
        for k, v in c.items():
            w = f"{where}.{k}"
            if _secret_key(k):
                ck.err(where, _("never write Wi-Fi or VPN passwords into the file; they are kept by the system "
                                "(NetworkManager asks for them when connecting)"))
            elif k == "type":
                if ck.typed(w, v, (str,), "a text"):
                    if re.match(r"^[a-z0-9-]{1,32}$", v):
                        nc["type"] = v
                    else:
                        ck.err(w, _("\"%s\" is not a valid %s") % (v, _("connection type")))
            elif k == "autoconnect":
                if ck.typed(w, v, (bool,), "True or False"):
                    nc[k] = v
            elif k == "interface":
                if ck.typed(w, v, (str,), "a text"):
                    if IFACE_RE.match(v):
                        nc[k] = v
                    else:
                        ck.err(w, _("\"%s\" is not a valid %s") % (v, _("network interface")))
            elif k == "ssid":
                if ck.typed(w, v, (str,), "a text"):
                    if 1 <= len(v.encode()) <= 32 and not re.search(r"[\x00-\x1f]", v):
                        nc[k] = v
                    else:
                        ck.err(w, _("a Wi-Fi network name has 1 to 32 characters"))
            elif k == "security":
                if v in WIFI_SECURITY:
                    nc[k] = v
                else:
                    ck.err(w, _("must be one of: %s") % ", ".join(WIFI_SECURITY))
            elif k in ("ipv4", "ipv6"):
                if isinstance(v, str):
                    v = {"method": v}
                if not ck.typed(w, v, (dict,), "a dictionary { }"):
                    continue
                ip = {}
                for ik, iv in v.items():
                    iw = f"{w}.{ik}"
                    if ik == "method":
                        if iv in IP_METHODS[k]:
                            ip[ik] = iv
                        else:
                            ck.err(iw, _("must be one of: %s") % ", ".join(IP_METHODS[k]))
                    elif ik in ("addresses", "dns"):
                        vals = ck.str_list(iw, iv, re.compile(r"^[0-9A-Fa-f.:/]+$"), "IP address")
                        for a in vals:
                            if not _ip_ok(a, prefix=(ik == "addresses")):
                                what = _("IP address") if ik == "dns" else _("address with prefix (e.g. \"192.168.1.10/24\")")
                                ck.err(iw, _("\"%s\" is not a valid %s") % (a, what))
                        ip[ik] = vals
                    elif ik == "gateway":
                        if ck.typed(iw, iv, (str,), "a text"):
                            if iv == "" or _ip_ok(iv):
                                ip[ik] = iv
                            else:
                                ck.err(iw, _("\"%s\" is not a valid %s") % (iv, _("IP address")))
                    else:
                        ck.unknown(w, ik, IP_KEYS)
                if ip.get("method") == "manual" and not ip.get("addresses"):
                    ck.err(w, _("\"manual\" needs \"addresses\" (e.g. [\"192.168.1.10/24\"])"))
                nc[k] = ip
            elif k == "proxy":
                if ck.typed(w, v, (str,), "a text"):
                    if v == "" or re.match(r"^https?://\S+$", v):
                        nc[k] = v
                    else:
                        ck.err(w, _("must be the address of a proxy configuration (PAC) file, e.g. "
                                    "\"http://proxy.example.com/proxy.pac\", or \"\" for none"))
            else:
                ck.unknown(where, k, CON_KEYS)
        if ("ssid" in nc or "security" in nc) and nc.get("type", "wifi") != "wifi":
            ck.err(where, _("\"ssid\" and \"security\" belong only to Wi-Fi connections"))
        out["connections"][name] = nc
    return out


def normalize_more(raw, ck, cfg):
    """Dalsi oblasti: jazykove formaty, konzole, ovladace, sit, tiskarny, napajeni, zavadec, zabezpeceni,
    vychozi nastaveni novych uzivatelu, repozitare (jen ke kontrole)."""
    if "formats" in raw and ck.typed("formats", raw["formats"], (dict,), "a dictionary { }"):
        supported = read("/usr/share/i18n/SUPPORTED")
        nf = {}
        for k, v in raw["formats"].items():
            if k not in LC_KEYS:
                ck.unknown("formats", k, LC_KEYS)
            elif v is None or v == "":
                nf[k] = None          # stejne jako jazyk (radek LC_* se odebere)
            elif not isinstance(v, str) or not LOCALE_RE.match(v) or (
                    supported and not re.search(r"^" + re.escape(v) + r" ", supported, re.M)):
                ck.err("formats." + k, _("unknown language setting \"%s\" (e.g. \"cs_CZ.UTF-8\")") % v)
            else:
                nf[k] = v
        cfg["formats"] = nf
    if "console" in raw and ck.typed("console", raw["console"], (dict,), "a dictionary { }"):
        nc = {}
        for k, v in raw["console"].items():
            if k not in ("keymap", "font"):
                ck.unknown("console", k, ("keymap", "font"))
            elif ck.typed("console." + k, v, (str,), "a text"):
                if CONSOLE_RE.match(v):
                    nc[k] = v
                else:
                    ck.err("console." + k, _("\"%s\" is not a valid %s") % (v, _("console setting")))
        cfg["console"] = nc
    if "drivers" in raw:
        cfg["drivers"] = ck.str_list("drivers", raw["drivers"], PKG_RE, "package name")
        for p in sorted(set(cfg["drivers"]) & set(cfg.get("packages", []))):
            ck.err("drivers", _("%s is both in packages and drivers") % p)
    if "network" in raw:
        cfg["network"] = normalize_network(raw["network"], ck)
    if "printers" in raw and ck.typed("printers", raw["printers"], (dict,), "a dictionary { }"):
        pr = raw["printers"]
        npr = {}
        for k in pr:
            if k not in ("default", "queues"):
                ck.unknown("printers", k, ("default", "queues"))
        if "default" in pr:
            d = pr["default"]
            if d is None or (isinstance(d, str) and PRINTER_RE.match(d)):
                npr["default"] = d
            else:
                ck.err("printers.default", _("\"%s\" is not a valid %s") % (d, _("printer name")))
        if "queues" in pr and ck.typed("printers.queues", pr["queues"], (dict,), "a dictionary { }"):
            npr["queues"] = {}
            for name, q in pr["queues"].items():
                where = f"printers.queues.{name}"
                if not PRINTER_RE.match(name):
                    ck.err(where, _("\"%s\" is not a valid %s") % (name, _("printer name")))
                    continue
                if q is None:
                    q = {}
                if not ck.typed(where, q, (dict,), "a dictionary { }"):
                    continue
                nq = {}
                for k, v in q.items():
                    if k == "uri":
                        if isinstance(v, str) and URI_RE.match(v):
                            nq[k] = v
                        else:
                            ck.err(where + ".uri", _("\"%s\" is not a valid %s") % (v, _("printer address (URI)")))
                    elif k == "model":
                        if ck.typed(where + ".model", v, (str,), "a text"):
                            if v.strip() and not re.search(r"[\x00-\x1f]", v):
                                nq[k] = v
                            else:
                                ck.err(where + ".model", _("\"%s\" is not a valid %s") % (v, _("printer driver")))
                    elif k == "shared":
                        if ck.typed(where + ".shared", v, (bool,), "True or False"):
                            nq[k] = v
                    else:
                        ck.unknown(where, k, ("uri", "model", "shared"))
                npr["queues"][name] = nq
        cfg["printers"] = npr
    if "power" in raw and ck.typed("power", raw["power"], (dict,), "a dictionary { }"):
        np_ = {}
        for k, v in raw["power"].items():
            if k in ("lid", "lid_on_power"):
                if v in LID_ACTIONS:
                    np_[k] = v
                else:
                    ck.err("power." + k, _("must be one of: %s") % ", ".join(LID_ACTIONS))
            elif k == "suspend_after_minutes":
                if ck.typed("power." + k, v, (int,), "a number"):
                    if 0 <= v <= 1440:
                        np_[k] = v
                    else:
                        ck.err("power." + k, _("must be between %d and %d") % (0, 1440))
            elif k == "profile":
                if v in PROFILES:
                    np_[k] = v
                else:
                    ck.err("power.profile", _("must be one of: %s") % ", ".join(PROFILES))
            else:
                ck.unknown("power", k, ("lid", "lid_on_power", "suspend_after_minutes", "profile"))
        cfg["power"] = np_
    if "boot" in raw and ck.typed("boot", raw["boot"], (dict,), "a dictionary { }"):
        nb = {}
        for k, v in raw["boot"].items():
            if k == "timeout":
                if ck.typed("boot.timeout", v, (int,), "a number"):
                    if 0 <= v <= 300:
                        nb[k] = v
                    else:
                        ck.err("boot.timeout", _("must be between %d and %d") % (0, 300))
            elif k == "default":
                if isinstance(v, str) and ENTRY_RE.match(v) and not re.search(r"snapshot|recovery", v):
                    nb[k] = v
                else:
                    ck.err("boot.default", _("must be \"luxos\" or the name of a boot menu entry (not a snapshot)"))
            else:
                ck.unknown("boot", k, ("timeout", "default"))
        cfg["boot"] = nb
    if "security" in raw and ck.typed("security", raw["security"], (dict,), "a dictionary { }"):
        ns = {}
        for k, v in raw["security"].items():
            if k != "faillock":
                ck.unknown("security", k, ("faillock",))
            elif ck.typed("security.faillock", v, (dict,), "a dictionary { }"):
                nf = {}
                for fk, fv in v.items():
                    if fk not in FAILLOCK_KEYS:
                        ck.unknown("security.faillock", fk, tuple(FAILLOCK_KEYS))
                    elif ck.typed("security.faillock." + fk, fv, (int,), "a number"):
                        lo, hi = FAILLOCK_KEYS[fk]
                        if lo <= fv <= hi:
                            nf[fk] = fv
                        else:
                            ck.err("security.faillock." + fk, _("must be between %d and %d") % (lo, hi))
                ns["faillock"] = nf
        cfg["security"] = ns
    if "new_users" in raw and ck.typed("new_users", raw["new_users"], (dict,), "a dictionary { }"):
        nn = {}
        for k, v in raw["new_users"].items():
            w = "new_users." + k
            if k not in NEW_USER_KEYS:
                ck.unknown("new_users", k, NEW_USER_KEYS)
            elif v is None:
                nn[k] = None          # zpet na vychozi hodnotu LuxOS
            elif k == "theme":
                if v in THEMES:
                    nn[k] = v
                else:
                    ck.err(w, _("must be one of: %s") % ", ".join(THEMES))
            elif k == "wallpaper":
                if isinstance(v, str) and v.startswith("/") and ".." not in v and not re.search(r"[\x00-\x1f\"\\$`]", v):
                    nn[k] = v
                else:
                    ck.err(w, _("must be the full path of a picture readable by everybody, e.g. "
                                "\"/usr/share/backgrounds/luxos/luxos-dark.jpg\""))
            elif k == "dock":
                nn[k] = [desktop_id(x) for x in ck.str_list(w, v, DESKTOP_ID_RE, "app ID")]
            elif k in ("browser", "text_editor", "mail"):
                if isinstance(v, str) and DESKTOP_ID_RE.match(v):
                    nn[k] = desktop_id(v)
                else:
                    ck.err(w, _("\"%s\" is not a valid %s") % (v, _("app ID")))
            elif ck.typed(w, v, (int,), "a number"):
                if 0 <= v <= 1440:
                    nn[k] = v
                else:
                    ck.err(w, _("must be between %d and %d") % (0, 1440))
        cfg["new_users"] = nn
    if "repos" in raw and ck.typed("repos", raw["repos"], (dict,), "a dictionary { }"):
        nr = {}
        for k, v in raw["repos"].items():
            if k == "list":
                nr[k] = ck.str_list("repos.list", v, REPO_RE, "repository name")
            elif k in REPO_KEYS:
                if ck.typed("repos." + k, v, (bool,), "True or False"):
                    nr[k] = v
            else:
                ck.unknown("repos", k, REPO_KEYS)
        cfg["repos"] = nr


LAYERS = None   # Layers posledniho load() - puvod hodnot pro diff, show --origin a record


def load(path, policies=True):
    """Zasady organizace (system.d) + soubor -> zkontrolovana konfigurace; puvod hodnot v LAYERS."""
    global LAYERS
    lay = merge(path, policies)
    cfg, errors = normalize(lay.value)
    errors = lay.errors + errors
    if errors:
        raise UserError(_("Error in the configuration %s:") % path + "\n" + "\n".join("  " + e for e in errors))
    LAYERS = lay
    return cfg


def org_labels(path, item=MISSING):
    """Popisky zasad organizace, ze kterych hodnota na ceste je ([] = jen lokalni soubor)."""
    if LAYERS is None or not LAYERS.fragments:
        return []
    return [o.label() for o in LAYERS.origins(path, item) if o.kind == "org"]


def change_origin(c):
    """Zasady organizace, ze kterych zmena vychazi (pro diff)."""
    if c.section in ("packages", "flatpaks", "drivers"):
        out = []
        for it in (c.data or []) if isinstance(c.data, list) else []:
            out += [x for x in org_labels((c.section,), it) if x not in out]
        return out
    if c.section == "system":
        return org_labels((c.target,))
    if c.section == "users":
        return org_labels(("users", c.target)) if c.target else org_labels(("groups",))
    if c.section == "services":
        return org_labels(("services", "enable"), c.target) + org_labels(("services", "disable"), c.target)
    if c.section in ("guard", "firewall", "care", "kernel", "domain", "power", "boot", "security", "new_users"):
        return org_labels((c.section,))
    if c.section == "network":
        return org_labels(("network", "connections", c.target))
    if c.section == "printers":
        return org_labels(("printers",))
    return []


# ---- soucasny stav systemu --------------------------------------------------------------------
class State:
    """Soucasny stav (cte se jen to, co je potreba; nic nemeni)."""

    def __init__(self):
        self._cache = {}

    def _get(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def hostname(self):
        return read("/etc/hostname").strip()

    def timezone(self):
        try:
            target = os.readlink(P("/etc/localtime"))
        except OSError:
            return ""
        return target.split("zoneinfo/", 1)[1] if "zoneinfo/" in target else ""

    def locale(self):
        return read_kv("/etc/locale.conf").get("LANG", "")

    def keyboard(self):
        opts = dict(re.findall(r'Option\s+"(Xkb\w+)"\s+"([^"]*)"', read(KEYBOARD_CONF)))
        layouts = [x for x in opts.get("XkbLayout", "").split(",")]
        variants = opts.get("XkbVariant", "").split(",")
        out = []
        for i, lay in enumerate(layouts):
            if not lay:
                continue
            v = variants[i] if i < len(variants) else ""
            out.append(f"{lay}({v})" if v else lay)
        return {"layouts": out, "options": [o for o in opts.get("XkbOptions", "").split(",") if o],
                "model": opts.get("XkbModel", "")}

    def _pkgs(self, flag):
        rc, out, err = capture([tool("lux-engine"), flag])
        if rc not in (0, 1):
            raise UserError(_("Cannot read the installed packages: %s") % (err or out).strip()[-300:])
        return set(out.split())

    def explicit(self):
        return self._get("explicit", lambda: self._pkgs("-Qeq"))

    def installed(self):
        return self._get("installed", lambda: self._pkgs("-Qq"))

    def available(self, names):
        """Ktere z nazvu jsou v repozitarich (nazev, provides, skupina) -> mnozina; None = nelze zjistit."""
        if not names:
            return set()
        rc, out, _e = capture([tool("lux_alpm.py"), "resolve", "--"] + sorted(names))
        if rc != 0:
            return None
        return {ln.split("\t", 1)[1] for ln in out.splitlines() if ln.startswith("repo\t")}

    def flatpaks(self):
        def f():
            if not have("flatpak"):
                return None
            rc, out, _e = capture([tool("flatpak"), "list", "--system", "--app", "--columns=application"])
            return set(out.split()) if rc == 0 else set()
        return self._get("flatpaks", f)

    def units(self):
        """jednotka -> (stav, preset) ze systemctl list-unit-files."""
        def f():
            rc, out, err = capture([tool("systemctl"), "list-unit-files", "--no-legend", "--no-pager", "--full"])
            if rc != 0:
                raise UserError(_("Cannot read the services: %s") % (err or out).strip()[-300:])
            d = {}
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    d[parts[0]] = (parts[1], parts[2] if len(parts) > 2 else "")
            return d
        return self._get("units", f)

    def enabled(self, unit):
        st = self.units().get(unit, ("",))[0]
        return st in ("enabled", "enabled-runtime", "alias", "linked")

    def login_defs(self):
        d = {}
        for line in read("/etc/login.defs").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] in ("UID_MIN", "UID_MAX", "GID_MIN", "GID_MAX") and parts[1].isdigit():
                d[parts[0]] = int(parts[1])
        return d.get("UID_MIN", 1000), d.get("UID_MAX", 60000), d.get("GID_MIN", 1000), d.get("GID_MAX", 60000)

    def passwd(self):
        users = {}
        for line in read("/etc/passwd").splitlines():
            f = line.split(":")
            if len(f) >= 7 and f[2].isdigit():
                users[f[0]] = {"uid": int(f[2]), "gid": int(f[3]) if f[3].isdigit() else -1, "description": f[4],
                               "home": f[5], "shell": f[6]}
        return users

    def group(self):
        groups = {}
        for line in read("/etc/group").splitlines():
            f = line.split(":")
            if len(f) >= 4 and f[2].isdigit():
                groups[f[0]] = {"gid": int(f[2]), "members": [m for m in f[3].split(",") if m]}
        return groups

    def normal_users(self):
        umin, umax, _g1, _g2 = self.login_defs()
        return {n: u for n, u in self.passwd().items() if umin <= u["uid"] < umax}

    def user_groups(self, name):
        primary = {g for g, v in self.group().items() if v["gid"] == self.passwd().get(name, {}).get("gid")}
        return sorted(g for g, v in self.group().items() if name in v["members"] and g not in primary)

    def shadow_hash(self, name):
        """Otisk hesla, None = nelze precist (bez prav roota)."""
        try:
            with open(P("/etc/shadow"), encoding="utf-8", errors="replace") as f:
                for line in f:
                    p = line.split(":")
                    if p[0] == name and len(p) > 1:
                        return p[1]
        except OSError:
            return None
        return ""

    def care(self):
        c = read_kv(CARE_CONF)
        keep = c.get("SNAPSHOT_KEEP", "")
        return {"mode": c.get("MODE") if c.get("MODE") in ("carefree", "classic") else "carefree",
                "snapshots": c.get("SNAPSHOTS", "yes").lower() not in ("no", "0", "false", "off"),
                "keep_snapshots": int(keep) if keep.isdigit() else 5,
                # ochrana systemu: chybi = vypnuto (nove instalace maji PROTECT=yes)
                "protect": c.get("PROTECT", "no").lower() in ("yes", "1", "true", "on"),
                "verify": c.get("VERIFY", "yes").lower() not in ("no", "0", "false", "off")}

    def firewall(self):
        installed = "ufw" in self.installed() if have("lux-engine") else have("ufw")
        enabled = read_kv("/etc/ufw/ufw.conf").get("ENABLED", "no").lower() == "yes"
        allow = []
        for path in ("/etc/ufw/user.rules", "/etc/ufw/user6.rules"):
            for m in re.finditer(r"^### tuple ### (.*)$", read(path), re.M):
                f = m.group(1).split()
                # allow PROTO DPORT DST SPORT SRC in (bez jmena aplikace, odkudkoli)
                if (len(f) == 7 and f[0] == "allow" and f[6] == "in" and f[3] in ("0.0.0.0/0", "::/0")
                        and f[5] in ("0.0.0.0/0", "::/0") and f[4] == "any" and f[2] != "any"):
                    spec = f[2] if f[1] == "any" else f"{f[2]}/{f[1]}"
                    if spec not in allow:
                        allow.append(spec)
        return {"installed": installed, "enable": enabled, "allow": allow}

    def scheduler(self):
        """Planovac procesu z /etc/luxos/scheduler.conf ("lavd" | "default"); None = bez planovace LuxOS."""
        if read(SCHED_CONF, None) is None:
            return None
        v = read_kv(SCHED_CONF).get("SCHEDULER", "lavd")
        return v if v in SCHEDULERS else "default"

    def boot(self):
        return self._get("boot", boot_layout)

    def booted_snapshot(self):
        m = re.search(r"(?:^|\s)luxos\.snapshot=(\S+)", read("/proc/cmdline"))
        return m.group(1) if m else ""

    # -- dalsi oblasti --
    def formats(self):
        return {k: v for k, v in read_kv("/etc/locale.conf").items() if k in LC_KEYS}

    def console(self):
        c = read_kv(VCONSOLE_CONF)
        return {k: c[K] for k, K in (("keymap", "KEYMAP"), ("font", "FONT")) if c.get(K)}

    def drivers(self):
        """Nainstalovane ovladace: baliky z [luxos-drivers] a ovladace grafiky/Wi-Fi (nvidia, broadcom-wl)."""
        def f():
            rc, out, _e = capture([tool("lux-engine"), "-Slq", "luxos-drivers"])
            repo = set(out.split()) if rc == 0 else set()
            return {p for p in self.explicit() if p in repo or DRIVER_RE.match(p)}
        return self._get("drivers", f)

    def connections(self):
        """Ulozena pripojeni NetworkManageru {jmeno: {...}} (bez tajemstvi); None = nelze cist (bez roota)."""
        return self._get("connections", nm_connections)

    def active_connections(self):
        """UUID prave pouzivanych pripojeni (nmcli); prazdne = NetworkManager nebezi."""
        def f():
            if not have("nmcli"):
                return set()
            rc, out, _e = capture([tool("nmcli"), "-t", "-f", "UUID", "connection", "show", "--active"], timeout=20)
            return set(out.split()) if rc == 0 else set()
        return self._get("active", f)

    def printers(self):
        return self._get("printers", cups_state)

    def power(self):
        lg = logind_settings()
        lid = lg.get("HandleLidSwitch", "suspend")
        out = {"lid": lid, "lid_on_power": lg.get("HandleLidSwitchExternalPower", lid)}
        idle = lg.get("IdleAction", "ignore")
        if idle == "ignore":
            out["suspend_after_minutes"] = 0
        elif idle == "suspend":
            out["suspend_after_minutes"] = max(1, round(time_span(lg.get("IdleActionSec", "30min")) / 60))
        prof = read_kv_section(PPD_STATE, "State").get("Profile", "")
        if prof in PROFILES:
            out["profile"] = prof
        return out

    def powersaver_on(self):
        return os.path.exists(P(POWERSAVER_MARK))

    def boot_settings(self):
        return self._get("bootcfg", lambda: boot_settings(self.boot()))

    def faillock(self):
        vals = {"deny": 3, "fail_interval": 900, "unlock_time": 600}   # vychozi pam_faillock
        for line in read(FAILLOCK_CONF).splitlines():
            m = re.match(r"^\s*(deny|fail_interval|unlock_time)\s*=\s*(\d+)\s*$", line)
            if m:
                vals[m.group(1)] = int(m.group(2))
        return vals

    def new_users(self):
        return new_users_state()

    def repos(self):
        return self._get("repos", lux_conf_settings)


def boot_layout():
    """Kde jsou parametry jadra: {"kind": "sdboot", "files": [...], "params": [...]} | grub | None."""
    roots = ["/boot", "/efi", "/boot/efi"]
    esp_dir = read_kv("/etc/luxos/esp.conf").get("ESP_DIR", "")
    if esp_dir and "/EFI/" in esp_dir:
        roots.insert(0, esp_dir.split("/EFI/")[0])
    entry_re = re.compile(r"^luxos(-[A-Za-z0-9_]+)?(-prev|-fallback)?(\+\d+(-\d+)?)?\.conf$")
    denied = False
    for root in roots:
        d = root + "/loader/entries"
        try:
            names = sorted(os.listdir(P(d)))
        except PermissionError:
            denied = True
            continue
        except OSError:
            continue
        files = [f"{d}/{n}" for n in names if entry_re.match(n) and "snapshot" not in n and "recovery" not in n]
        main = [f for f in files if not re.search(r"-(prev|fallback)(\+[\d-]+)?\.conf$", f)]
        if main:
            m = re.search(r"^options\s+(.*)$", read(main[0]), re.M)
            return {"kind": "sdboot", "files": files, "params": m.group(1).split() if m else []}
    text = read("/etc/default/grub", None)
    if text is not None and os.path.isfile(P("/boot/grub/grub.cfg")):
        m = re.search(r'^GRUB_CMDLINE_LINUX_DEFAULT="([^"]*)"', text, re.M)
        return {"kind": "grub", "files": ["/etc/default/grub"], "params": m.group(1).split() if m else []}
    # systemd-boot na oddilu EFI cte jen root
    return {"kind": "unreadable", "files": [], "params": []} if denied else None


def set_params_text(text, kind, add, remove):
    """Pridat/odebrat parametry v options (systemd-boot) nebo GRUB_CMDLINE_LINUX_DEFAULT."""
    def fix(params):
        params = [p for p in params if p not in remove]
        return params + [p for p in add if p not in params]
    if kind == "sdboot":
        return re.sub(r"^(options[ \t]+)(.*)$", lambda m: m.group(1) + " ".join(fix(m.group(2).split())), text, flags=re.M)
    return re.sub(r'^(GRUB_CMDLINE_LINUX_DEFAULT=")([^"]*)"',
                  lambda m: m.group(1) + " ".join(fix(m.group(2).split())) + '"', text, flags=re.M)


# ---- soucasny stav dalsich oblasti (jen cteni) ---------------------------------------------------
# Ovladace grafiky a Wi-Fi, ktere vybira aplikace Ovladace (luxos-hwdetect); dalsi ovladace jsou z [luxos-drivers]
DRIVER_RE = re.compile(r"^(nvidia(-open)?(-lts)?(-dkms)?|nvidia-\d+xx-(dkms|utils)|nvidia-utils"
                       r"|lib32-nvidia(-\d+xx)?-utils|broadcom-wl(-dkms)?)$")
NM_TYPE_NAMES = {"802-11-wireless": "wifi", "802-3-ethernet": "ethernet"}
NEW_USERS_MAP = (("theme", "THEME"), ("wallpaper", "WALLPAPER"), ("dock", "DOCK"), ("browser", "BROWSER"),
                 ("text_editor", "TEXT_EDITOR"), ("mail", "MAIL"), ("lock_after_minutes", "LOCK_AFTER"),
                 ("screen_off_minutes", "SCREEN_OFF"))


def read_kv_section(path, section):
    """KLIC=hodnota z jedne sekce [section] souboru INI."""
    out, cur = {}, None
    for line in read(path).splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1].strip()
        elif cur == section and s and not s.startswith(("#", ";")) and "=" in s:
            k, v = s.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def nm_ssid(v):
    """SSID z keyfile: text, nebo bajty "77;105;102;105;" (nazvy, ktere nejsou UTF-8)."""
    if re.match(r"^(\d{1,3};)+\d{0,3}$", v):
        try:
            return bytes(int(x) for x in v.split(";") if x).decode("utf-8", "replace")
        except ValueError:
            return v
    return v


def nm_ip(sec):
    d = {"method": sec.get("method", "auto")}
    addrs, gw = [], sec.get("gateway", "")
    keys = sorted((k for k in sec if re.match(r"^address(es)?\d*$", k)),
                  key=lambda k: int(re.sub(r"\D", "", k) or 0))
    for k in keys:
        for part in sec[k].split(";"):
            a, _s, g = part.partition(",")
            if a.strip():
                addrs.append(a.strip())
                gw = gw or g.strip()
    dns = [x for x in re.split(r"[;,\s]+", sec.get("dns", "")) if x]
    if addrs:
        d["addresses"] = addrs
    if gw:
        d["gateway"] = gw
    if dns:
        d["dns"] = dns
    return d


def nm_connections():
    """Keyfile NetworkManageru v /etc (jen nastaveni, nikdy hesla) -> {jmeno: {...}}; None = bez prav."""
    d = P(NM_DIR)
    try:
        names = sorted(os.listdir(d))
    except PermissionError:
        return None
    except OSError:
        return {}
    out = {}
    for n in names:
        if not n.endswith(".nmconnection"):
            continue
        try:
            with open(os.path.join(d, n), encoding="utf-8", errors="replace") as f:
                text = f.read()
        except PermissionError:
            return None
        except OSError:
            continue
        cp = configparser.RawConfigParser(strict=False, interpolation=None, delimiters=("=",),
                                          comment_prefixes=("#",), inline_comment_prefixes=None)
        cp.optionxform = str
        try:
            cp.read_string(text)
        except configparser.Error:
            continue

        def sec(*names_):
            for s in names_:
                if cp.has_section(s):
                    return dict(cp.items(s))
            return {}
        con = sec("connection")
        name = con.get("id") or n[:-len(".nmconnection")]
        typ = NM_TYPE_NAMES.get(con.get("type", ""), con.get("type", ""))
        c = {"uuid": con.get("uuid", ""), "file": f"{NM_DIR}/{n}", "type": typ,
             "autoconnect": con.get("autoconnect", "true").lower() not in ("false", "0", "no")}
        if con.get("interface-name"):
            c["interface"] = con["interface-name"]
        if typ == "wifi":
            c["ssid"] = nm_ssid(sec("wifi", "802-11-wireless").get("ssid", ""))
            ws = sec("wifi-security", "802-11-wireless-security")
            km = ws.get("key-mgmt", "")
            c["security"] = "none" if not km else ("wep" if km in ("none", "ieee8021x") else km)
        for fam in ("ipv4", "ipv6"):
            if cp.has_section(fam) or typ in NET_TYPES:
                c[fam] = nm_ip(sec(fam))
        pr = sec("proxy")
        c["proxy"] = pr.get("pac-url", "") if pr.get("method") == "auto" else ""
        out[name] = c
    return out


def cups_state():
    """Tiskove fronty CUPS {"default": jmeno|None, "queues": {jmeno: {uri, model, shared}}}; None = CUPS nebezi."""
    if not have("lpstat"):
        return None
    rc, out, _e = capture([tool("lpstat"), "-r"], timeout=20)
    if rc != 0 or "not running" in out:
        return None
    rc, out, _e = capture([tool("lpstat"), "-v"], timeout=30)
    queues = {}
    for line in out.splitlines():
        m = re.match(r"^device for ([^:\s]+): (\S+)", line)
        if m:
            queues[m.group(1)] = {"uri": m.group(2)}
    rc, out, _e = capture([tool("lpstat"), "-d"], timeout=20)
    m = re.search(r"system default destination: (\S+)", out)
    default = m.group(1) if m else None
    for name, q in queues.items():
        rc, out, _e = capture([tool("lpoptions"), "-p", name], timeout=20)
        try:
            opts = dict(x.split("=", 1) for x in shlex.split(out) if "=" in x)
        except ValueError:
            opts = {}
        mm = opts.get("printer-make-and-model", "")
        q["model"] = "everywhere" if re.search(r"IPP Everywhere|driverless", mm, re.I) else mm
        q["shared"] = opts.get("printer-is-shared", "false").lower() == "true"
    return {"default": default, "queues": queues}


def logind_settings():
    """Ucinne nastaveni systemd-logind: hlavni soubor a doplnky *.conf.d v poradi jmen (/etc ma prednost)."""
    vals = {}
    for path in ("/usr/lib/systemd/logind.conf", "/etc/systemd/logind.conf"):
        vals.update(read_kv_section(path, "Login"))
    drop = {}
    for d in ("/usr/lib/systemd/logind.conf.d", "/usr/local/lib/systemd/logind.conf.d", "/run/systemd/logind.conf.d",
              "/etc/systemd/logind.conf.d"):
        try:
            for n in os.listdir(P(d)):
                if n.endswith(".conf"):
                    drop[n] = d + "/" + n
        except OSError:
            pass
    for n in sorted(drop):
        vals.update(read_kv_section(drop[n], "Login"))
    return vals


def time_span(text):
    """Casovy udaj systemd ("30min", "1h 30min", "900") -> sekundy."""
    units = {"": 1, "s": 1, "sec": 1, "second": 1, "seconds": 1, "m": 60, "min": 60, "minute": 60, "minutes": 60,
             "h": 3600, "hr": 3600, "hour": 3600, "hours": 3600, "d": 86400, "day": 86400, "days": 86400,
             "ms": 0.001, "us": 0.000001}
    total = 0.0
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([a-z]*)", text.lower()):
        total += float(num) * units.get(unit, 1)
    return total


def efivar(name):
    """Promenna systemd-boot v EFI (UTF-16, prvni 4 bajty jsou atributy); None = neni nastavena."""
    try:
        with open(P(f"{EFIVARS}/{name}-{EFI_LOADER_GUID}"), "rb") as f:
            data = f.read()
    except OSError:
        return None
    return data[4:].decode("utf-16-le", "replace").split("\x00")[0]


LUXOS_DEFAULT_RE = re.compile(r"^luxos(\.conf|\*)?$")


def boot_settings(lay):
    """Cas nabidky a vychozi polozka zavadece -> {kind, timeout, default, entries, ...}; None = nelze zjistit."""
    if lay is None or lay["kind"] == "unreadable":
        return None
    if lay["kind"] == "sdboot":
        esp = lay["files"][0].split("/loader/entries/")[0]
        conf = {}
        for line in read(esp + "/loader/loader.conf").splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and not parts[0].startswith("#"):
                conf[parts[0]] = parts[1].strip()
        t = efivar("LoaderConfigTimeout")
        t = conf.get("timeout", "0") if t is None else t
        timeout = int(t) if t.isdigit() else (0 if t in ("", "menu-hidden") else None)
        loader_default = conf.get("default", "")
        d = efivar("LoaderEntryDefault") or loader_default
        try:
            entries = sorted(n for n in os.listdir(P(esp + "/loader/entries")) if n.endswith(".conf"))
        except OSError:
            entries = []
        main = next((os.path.basename(f) for f in lay["files"]
                     if not re.search(r"-(prev|fallback)(\+[\d-]+)?\.conf$", f)), "luxos.conf")
        return {"kind": "sdboot", "timeout": timeout, "entries": entries, "main": main,
                "loader_luxos": not loader_default or bool(LUXOS_DEFAULT_RE.match(loader_default)),
                "default": "luxos" if (not d or LUXOS_DEFAULT_RE.match(d) or d == main) else d}
    g = read_kv("/etc/default/grub")
    t = g.get("GRUB_TIMEOUT", "5")
    d = g.get("GRUB_DEFAULT", "0")
    return {"kind": "grub", "timeout": int(t) if t.isdigit() else None, "entries": [],
            "default": "luxos" if d in ("", "0") else d}


def new_users_state():
    kv = read_kv(NEW_USERS_CONF)
    out = {}
    for k, K in NEW_USERS_MAP:
        v = kv.get(K, "")
        if not v:
            continue
        if k == "dock":
            out[k] = [desktop_id(x) for x in v.split()]
        elif k in ("browser", "text_editor", "mail"):
            out[k] = desktop_id(v)
        elif k.endswith("_minutes"):
            if v.isdigit():
                out[k] = int(v)
        else:
            out[k] = v
    return out


def _lux_config():
    """Modul lux_config z lux-engine (/usr/lib/lux, pri spusteni z repozitare ../lux-engine), jinak None."""
    for d in ("/usr/lib/lux", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lux-engine")):
        if os.path.isfile(os.path.join(d, "lux_config.py")) and d not in sys.path:
            sys.path.append(d)
    try:
        import lux_config
        return lux_config
    except ImportError:
        return None


def lux_conf_settings():
    """JEDINE misto, kde lux system cte /etc/lux/lux.conf (repozitare, komunita/AUR, Flatpak) - jen cteni,
    lux.conf se odtud nikdy nezapisuje. Umi puvodni format ("klic hodnota", "repo JMENO" s odsazenym
    blokem) i tabulky ([repo.JMENO], "klic = hodnota"); vlozene soubory (include) se ctou take.
    -> {"list": [...], "community": bool, "review_build_scripts": bool, "flatpak_updates": bool} | None"""
    if read(LUX_CONF, None) is None:
        return None
    lc = _lux_config()
    if lc is not None:
        # parser lux.conf z lux-engine (TOML i puvodni format, include, conf.d)
        try:
            d = lc.load(path=LUX_CONF, root=ROOT or "")
            pk = d.get("packages", {})
            names = []
            for r in d.get("repos", []):
                if r.get("name") and r["name"] not in names:
                    names.append(r["name"])
            return {"list": names, "community": bool(pk.get("aur", True)),
                    "review_build_scripts": bool(pk.get("review_pkgbuild", True)),
                    "flatpak_updates": bool(pk.get("flatpak", True))}
        except Exception:
            pass
    files, seen, repos, vals = [LUX_CONF], set(), [], {}
    while files and len(seen) < 50:
        f = files.pop(0)
        if f in seen:
            continue
        seen.add(f)
        for line in read(f).splitlines():
            s = re.sub(r"\s+#.*$|^#.*$", "", line).strip()
            if not s:
                continue
            m = re.match(r'^\[\s*repo\.\"?([^\]\"]+)\"?\s*\]$', s) or re.match(r"^repo\s+(\S+)$", s)
            if m and not line[:1].isspace():
                if m.group(1) not in repos:
                    repos.append(m.group(1))
                continue
            m = re.match(r'^include\s*=?\s*\[?\s*\"?([^\"\]]+)\"?\s*\]?$', s)
            if m:
                pat = m.group(1).strip()
                for p in sorted(glob.glob(P(pat))):
                    files.append(p[len(ROOT):] if ROOT and p.startswith(ROOT) else p)
                continue
            m = re.match(r'^(aur|review-pkgbuild|review_pkgbuild|flatpak)\s*(?:=\s*)?\"?([A-Za-z0-9]+)\"?$', s)
            if m:
                vals[m.group(1).replace("_", "-")] = m.group(2).lower()

    def flag(key):
        return vals.get(key, "on") not in ("off", "no", "false", "0")
    return {"list": repos, "community": flag("aur"), "review_build_scripts": flag("review-pkgbuild"),
            "flatpak_updates": flag("flatpak")}


# ---- plan zmen dalsich oblasti ---------------------------------------------------------------------
NMCLI_IP = {"method": "method", "addresses": "addresses", "gateway": "gateway", "dns": "dns"}


def nm_props(want, have=None):
    """Pozadovane hodnoty pripojeni -> [(vlastnost nmcli, hodnota)] jen toho, co se lisi."""
    have = have or {}
    props = []

    def differ(k):
        return k in want and want[k] != have.get(k)
    if differ("autoconnect"):
        props.append(("connection.autoconnect", "yes" if want["autoconnect"] else "no"))
    if differ("interface"):
        props.append(("connection.interface-name", want["interface"]))
    if differ("ssid"):
        props.append(("802-11-wireless.ssid", want["ssid"]))
    if differ("security"):
        if want["security"] == "none":
            props.append(("remove", "802-11-wireless-security"))
        else:
            km = "none" if want["security"] == "wep" else want["security"]
            props.append(("802-11-wireless-security.key-mgmt", km))
    for fam in ("ipv4", "ipv6"):
        w, h = want.get(fam) or {}, have.get(fam) or {}
        for k in IP_KEYS:
            if k not in w:
                continue
            hv = h.get(k, [] if k in ("addresses", "dns") else ("auto" if k == "method" else ""))
            if w[k] != hv:
                v = ",".join(w[k]) if isinstance(w[k], list) else w[k]
                props.append((f"{fam}.{NMCLI_IP[k]}", v))
    if differ("proxy") and not (want["proxy"] == "" and not have.get("proxy")):
        if want["proxy"]:
            props += [("proxy.method", "auto"), ("proxy.pac-url", want["proxy"])]
        else:
            props += [("proxy.method", "none"), ("proxy.pac-url", "")]
    return props


def nm_argv(props):
    out = []
    for k, v in props:
        out += ["remove", v] if k == "remove" else [k, v]
    return out


def describe_props(props):
    return ", ".join(f"{k} {v}" if k != "remove" else f"-{v}" for k, v in props)


def compute_network(net, st, plan, applied, force):
    want = net.get("connections")
    if want is None:
        return
    cur = st.connections()
    if cur is None:
        plan.warnings.append(_("Network connections can be read only with administrator rights "
                               "(lux system diff asks for them)."))
        return
    active = st.active_connections()
    nm = tool("nmcli")
    for name, c in want.items():
        have_c = cur.get(name)
        if have_c is None:
            typ = c.get("type", "wifi" if "ssid" in c else "")
            if typ not in NET_TYPES:
                raise UserError(_("network.connections.%s: only Wi-Fi and Ethernet connections can be created here; "
                                  "create other kinds in Settings > Network") % name)
            if typ == "wifi" and not c.get("ssid"):
                raise UserError(_("network.connections.%s: a new Wi-Fi connection needs \"ssid\"") % name)
            if c.get("security", "").startswith("wpa-eap"):
                raise UserError(_("network.connections.%s: enterprise Wi-Fi (802.1x) needs certificates and an account; "
                                  "connect it once in Settings > Network, then the file manages it") % name)
            argv = [nm, "connection", "add", "type", typ, "con-name", name]
            if c.get("interface"):
                argv += ["ifname", c["interface"]]
            argv += nm_argv([p for p in nm_props(c, {"ipv4": {}, "ipv6": {}}) if p[0] != "remove"])
            text = _("add connection %s") % name + (f" (Wi-Fi {c['ssid']})" if typ == "wifi" else "")
            plan.add("network", "+", text, 55, lambda a=argv: run(a), target=name)
            if typ == "wifi" and c.get("security", "none") != "none":
                plan.notes.append(_("Connection %s: the Wi-Fi password is not in the file; it is asked for when "
                                    "connecting for the first time (it stays in the system).") % name)
            continue
        if "type" in c and c["type"] != have_c["type"]:
            raise UserError(_("network.connections.%s: the type cannot be changed (%s → %s); delete the connection "
                              "and create a new one") % (name, have_c["type"], c["type"]))
        props = nm_props(c, have_c)
        if props:
            in_use = have_c["uuid"] in active
            text = _("change connection %s: %s") % (name, describe_props(props))
            if in_use:
                text += "  " + _("(in use; applies at the next connection)")
            plan.add("network", "~", text, 55, lambda u=have_c["uuid"], p=props: run([nm, "connection", "modify", u]
                                                                                    + nm_argv(p)),
                     target=name, risky=in_use)
    for name in applied.get("connections", []):
        if name in want or name not in cur:
            continue
        in_use = cur[name]["uuid"] in active
        if in_use and not force:
            plan.notes.append(_("Connection %s is in use and was kept; delete it with --force (the computer "
                                "may lose the network).") % name)
            plan.kept_connections.append(name)
            continue
        plan.add("network", "-", _("delete connection %s") % name, 56,
                 lambda u=cur[name]["uuid"]: run([nm, "connection", "delete", u]), target=name, risky=in_use)


def lpinfo_model(model):
    """Nazev ovladace pro lpadmin -m: "everywhere", nazev z lpinfo -m nebo jeho popis (make-and-model)."""
    if model == "everywhere":
        return model
    rc, out, _e = capture([tool("lpinfo"), "-m"], timeout=120)
    for line in out.splitlines():
        name, _s, mm = line.partition(" ")
        if model in (name, mm.strip()):
            return name
    return None


def compute_printers(pr, st, plan, applied):
    cur = st.printers()
    if cur is None:
        if pr.get("queues") or pr.get("default"):
            plan.warnings.append(_("Printing (CUPS) is not running; printers were not checked."))
        return
    lpadmin = tool("lpadmin")
    queues = pr.get("queues", {})
    models = {}

    def model_name(name, m):
        if m not in models:
            models[m] = lpinfo_model(m)
        if not models[m]:
            raise UserError(_("printers.queues.%s: the driver \"%s\" is not installed (list: lpinfo -m; "
                              "\"everywhere\" = driverless printing)") % (name, m))
        return models[m]
    for name, q in queues.items():
        have_q = cur["queues"].get(name)
        if have_q is None:
            if not q.get("uri"):
                raise UserError(_("printers.queues.%s: a new printer needs \"uri\" (its address)") % name)
            argv = [lpadmin, "-p", name, "-E", "-v", q["uri"], "-m", model_name(name, q.get("model", "everywhere")),
                    "-o", "printer-is-shared=" + ("true" if q.get("shared") else "false")]
            plan.add("printers", "+", _("add printer %s (%s)") % (name, q["uri"]), 56, lambda a=argv: run(a), target=name)
            continue
        argv, parts = [], []
        if "uri" in q and q["uri"] != have_q["uri"]:
            argv += ["-v", q["uri"]]
            parts.append(f"{have_q['uri']} → {q['uri']}")
        if "model" in q and q["model"] != have_q["model"]:
            argv += ["-m", model_name(name, q["model"])]
            parts.append(_("driver %s") % q["model"])
        if "shared" in q and q["shared"] != have_q["shared"]:
            argv += ["-o", "printer-is-shared=" + ("true" if q["shared"] else "false")]
            parts.append(_("shared: %s") % fmt(q["shared"]))
        if argv:
            plan.add("printers", "~", _("printer %s: %s") % (name, ", ".join(parts)), 56,
                     lambda a=[lpadmin, "-p", name] + argv: run(a), target=name)
    if pr.get("default") and pr["default"] != cur["default"]:
        if pr["default"] not in cur["queues"] and pr["default"] not in queues:
            raise UserError(_("printers.default: there is no printer %s") % pr["default"])
        plan.add("printers", "~", _("default printer: %s → %s") % (cur["default"] or "-", pr["default"]), 57,
                 lambda d=pr["default"]: run([lpadmin, "-d", d]), target="default")
    if "queues" in pr:
        for name in applied.get("printers", []):
            if name not in queues and name in cur["queues"]:
                plan.add("printers", "-", _("remove printer %s") % name, 57,
                         lambda n=name: run([lpadmin, "-x", n]), target=name)


def compute_power(pw, st, plan):
    cur = st.power()
    want = {k: v for k, v in pw.items() if k != "profile" and cur.get(k) != v}
    if want:
        text = ", ".join(f"{k}: {fmt(cur.get(k, '-'))} → {fmt(v)}" for k, v in want.items())
        plan.add("power", "~", text, 57, lambda w=want: apply_logind(w), target="logind")
    if "profile" in pw and pw["profile"] != cur.get("profile"):
        if st.powersaver_on():
            plan.notes.append(_("Battery Saver is on; the power profile is set when it turns off."))
        elif not have("powerprofilesctl"):
            raise UserError(_("power.profile: power profiles are not installed (lux install power-profiles-daemon)."))
        else:
            plan.add("power", "~", _("power profile: %s → %s") % (cur.get("profile", "-"), pw["profile"]), 57,
                     lambda p=pw["profile"]: run([tool("powerprofilesctl"), "set", p]), target="profile")


def compute_boot(bt, st, plan):
    cur = st.boot_settings()
    if cur is None:
        if st.boot() is not None and st.boot()["kind"] == "unreadable":
            plan.warnings.append(_("Boot settings can be read only with administrator rights (lux system diff asks for them)."))
        elif bt:
            raise UserError(_("Boot settings: no LuxOS boot entry found (systemd-boot or GRUB)."))
        return
    if "timeout" in bt and bt["timeout"] != cur["timeout"]:
        plan.add("boot", "~", _("boot menu shown for: %s → %s s") % (fmt(cur["timeout"]) if cur["timeout"] is not None
                                                                     else "-", bt["timeout"]), 81,
                 lambda t=bt["timeout"], c=cur: apply_boot(c, timeout=t), target="timeout")
    if "default" in bt and bt["default"] != cur["default"]:
        d = bt["default"]
        if cur["kind"] == "sdboot" and d != "luxos" and d not in cur["entries"] and not d.startswith("auto-"):
            raise UserError(_("boot.default: there is no boot menu entry %s (entries: %s)")
                            % (d, ", ".join(e for e in cur["entries"] if "snapshot" not in e) or "-"))
        plan.add("boot", "~", _("default boot entry: %s → %s") % (cur["default"], d), 81,
                 lambda d=d, c=cur: apply_boot(c, default=d), target="default")


def compute_more(cfg, st, plan, applied, force):
    """Jazykove formaty, konzole, sit, tiskarny, napajeni, zavadec, zabezpeceni, novi uzivatele, repozitare."""
    if cfg.get("formats"):
        cur = st.formats()
        want = {k: v for k, v in cfg["formats"].items() if cur.get(k) != v}
        if want:
            text = ", ".join(f"{k}: {cur.get(k) or '-'} → {v or _('as the language')}" for k, v in want.items())
            plan.add("system", "~", _("formats: %s") % text, 30, lambda w=want: apply_formats(w), target="formats")
    if cfg.get("console"):
        cur = st.console()
        want = {k: v for k, v in cfg["console"].items() if cur.get(k) != v}
        if want:
            text = ", ".join(f"{k}: {cur.get(k) or '-'} → {v}" for k, v in want.items())
            plan.add("system", "~", _("console: %s") % text + "  " + _("(after a restart)"), 32,
                     lambda w=want: set_kv(VCONSOLE_CONF, {k.upper(): v for k, v in w.items()}), target="console")
    if cfg.get("network"):
        compute_network(cfg["network"], st, plan, applied, force)
    if cfg.get("printers"):
        compute_printers(cfg["printers"], st, plan, applied)
    if cfg.get("power"):
        compute_power(cfg["power"], st, plan)
    if cfg.get("boot"):
        compute_boot(cfg["boot"], st, plan)
    fl = cfg.get("security", {}).get("faillock")
    if fl:
        cur = st.faillock()
        want = {k: v for k, v in fl.items() if cur.get(k) != v}
        if want:
            text = ", ".join(f"{k}: {cur.get(k)} → {v}" for k, v in want.items())
            plan.add("security", "~", _("sign-in lockout: %s") % text, 62, lambda w=want: apply_faillock(w),
                     target="faillock")
    if cfg.get("new_users"):
        cur = st.new_users()
        want = {k: v for k, v in cfg["new_users"].items() if cur.get(k) != v}
        if want:
            text = ", ".join(f"{k}: {fmt_value(cur.get(k))} → {fmt_value(v)}" for k, v in want.items())
            plan.add("new_users", "~", text, 63, lambda w=want: apply_new_users(w), target="new_users")
    if cfg.get("repos"):
        cur = st.repos()
        if cur is None:
            plan.warnings.append(_("%s is missing; the package manager settings were not checked.") % LUX_CONF)
        else:
            for k, v in cfg["repos"].items():
                if cur.get(k) != v:
                    plan.warnings.append(_("repos.%s differs from %s (%s); lux system does not change the package "
                                           "manager settings - edit %s and check it with: lux config check")
                                         % (k, LUX_CONF, fmt_value(cur.get(k)), LUX_CONF))


def fmt_value(v):
    if v is None:
        return "-"
    if isinstance(v, list):
        return " ".join(v) or "[]"
    return fmt(v)


# ---- provedeni dalsich oblasti -------------------------------------------------------------------------
def ensure_locale(loc):
    """Jazyk v /etc/locale.gen a vygenerovany (locale-gen zapisuje do /usr - pri ochrane pres luxos-care)."""
    path = "/etc/locale.gen"
    text = read(path, None)
    if text is None or re.search(r"^" + re.escape(loc) + r"\s", text, re.M):
        return
    charset = "UTF-8" if loc.endswith(".UTF-8") else "ISO-8859-1"
    pat = re.compile(r"^#\s*(" + re.escape(loc) + r"\s.*)$", re.M)
    new = pat.sub(r"\1", text, count=1) if pat.search(text) else text.rstrip("\n") + f"\n{loc} {charset}\n"
    atomic_write(path, new)
    if have("luxos-care"):
        run([tool("luxos-care"), "protect", "exec", "--", tool("locale-gen")])
    else:
        run([tool("locale-gen")])


def apply_formats(want):
    for v in want.values():
        if v:
            ensure_locale(v)
    set_kv("/etc/locale.conf", want)


def apply_logind(want):
    vals = read_kv_section(LOGIND_DROPIN, "Login")
    if "lid" in want:
        vals["HandleLidSwitch"] = want["lid"]
    if "lid_on_power" in want:
        vals["HandleLidSwitchExternalPower"] = want["lid_on_power"]
    if "suspend_after_minutes" in want:
        m = want["suspend_after_minutes"]
        vals["IdleAction"] = "suspend" if m else "ignore"
        if m:
            vals["IdleActionSec"] = f"{m}min"
        else:
            vals.pop("IdleActionSec", None)
    text = ("# LuxOS - power settings of the whole system (login screen, nobody signed in).\n"
            "# Written by lux system from /etc/luxos/system.lsl (section \"power\"); change them there.\n"
            "[Login]\n" + "".join(f"{k}={v}\n" for k, v in vals.items()))
    atomic_write(LOGIND_DROPIN, text)
    # logind nacte nastaveni znovu bez restartu (SIGHUP); prihlasene relace nic nepoznaji
    run([tool("systemctl"), "kill", "--signal=SIGHUP", "systemd-logind.service"])


def apply_boot(cur, timeout=None, default=None):
    if cur["kind"] == "sdboot":
        # promenne EFI maji prednost pred loader.conf, ktery spravuje LuxOS Care (polozky, zalozni jadro)
        if timeout is not None:
            run([tool("bootctl"), "set-timeout", str(timeout)])
        if default is not None:
            if default == "luxos":
                run([tool("bootctl"), "set-default", "" if cur.get("loader_luxos") else cur.get("main", "luxos.conf")])
            else:
                run([tool("bootctl"), "set-default", default])
        return
    values = {}
    if timeout is not None:
        values["GRUB_TIMEOUT"] = str(timeout)
    if default is not None:
        values["GRUB_DEFAULT"] = "0" if default == "luxos" else f'"{default}"'
    set_kv("/etc/default/grub", values)
    run([tool("grub-mkconfig"), "-o", "/boot/grub/grub.cfg"])


def apply_faillock(want):
    text = read(FAILLOCK_CONF, "")
    for k, v in want.items():
        line = f"{k} = {v}"
        if re.search(rf"^\s*{k}\s*=.*$", text, re.M):
            text = re.sub(rf"^\s*{k}\s*=.*$", line, text, count=1, flags=re.M)
        elif re.search(rf"^#\s*{k}\s*=.*$", text, re.M):
            text = re.sub(rf"^#\s*{k}\s*=.*$", line, text, count=1, flags=re.M)
        else:
            text = text.rstrip("\n") + ("\n" if text.strip() else "") + line + "\n"
    atomic_write(FAILLOCK_CONF, text)


def apply_new_users(want):
    values = {}
    for k, K in NEW_USERS_MAP:
        if k in want:
            v = want[k]
            values[K] = None if v is None else (" ".join(v) if isinstance(v, list) else str(v))
    set_kv(NEW_USERS_CONF, values, header="# LuxOS - defaults for NEW users (applied at their first sign-in; existing "
                                          "users keep their settings).\n# Written by lux system from "
                                          "/etc/luxos/system.lsl (section \"new_users\").")


# ---- plan zmen ---------------------------------------------------------------------------------
SECTIONS = [("packages", "Packages"), ("drivers", "Drivers"), ("flatpaks", "Flathub apps"), ("system", "System"),
            ("users", "Users and groups"), ("services", "Services"), ("network", "Network connections"),
            ("printers", "Printers"), ("power", "Power"), ("care", "LuxOS Care"), ("guard", "Lux Guard"),
            ("firewall", "Firewall"), ("security", "Security"), ("new_users", "Defaults for new users"),
            ("boot", "Boot menu"), ("kernel", "Kernel parameters"), ("domain", "Organization network")]


class Change:
    def __init__(self, section, op, text, phase, action, target="", data=None, risky=False):
        self.section, self.op, self.text, self.phase, self.action = section, op, text, phase, action
        self.target, self.data = target, data
        self.risky = risky      # meni prave pouzivane sitove pripojeni (vzdaleny pristup muze spadnout)

    def json(self):
        d = {"section": self.section, "op": {"+": "add", "-": "remove", "~": "change"}[self.op], "target": self.target,
             "text": self.text}
        if self.risky:
            d["network_in_use"] = True
        if self.data is not None:
            d["items"] = self.data
        return d


class Plan:
    def __init__(self):
        self.changes, self.notes, self.warnings = [], [], []
        self.restart = False
        self.kept_connections = []   # pouzivana pripojeni, ktera se bez --force neodebrala

    def add(self, *a, **kw):
        self.changes.append(Change(*a, **kw))

    def removals(self):
        return [c for c in self.changes if c.op == "-" and c.section in ("packages", "flatpaks")]


def read_applied():
    try:
        with open(P(APPLIED), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def env_lux():
    """lux pri apply: snimek uz je hotovy (hook pred transakci ho nedela znovu)."""
    return {"LUXOS_SNAPSHOT_TAKEN": "1", "LUX_COLOR": "always" if COLOR else "never"}


def compute(cfg, st, applied=None, force=False):
    applied = read_applied() if applied is None else applied
    plan = Plan()

    # --- balicky a ovladace (ovladace = vlastni seznam "drivers", instaluji se stejne) ---
    pkgs = list(cfg.get("packages", []))
    drivers = [p for p in cfg.get("drivers", []) if p not in pkgs]
    wanted = pkgs + drivers
    extra = []
    if cfg.get("firewall", {}).get("enable") and "ufw" not in wanted:
        extra.append("ufw")
    if cfg.get("flatpaks") and not have("flatpak") and "flatpak" not in wanted:
        extra.append("flatpak")
    if "packages" in cfg or "drivers" in cfg or extra:
        installed, explicit = st.installed(), st.explicit()
        want_all = wanted + [p for p in extra if p not in installed]
        missing = [p for p in want_all if p not in installed]
        if missing:
            avail = st.available(missing)
            if avail is None:
                plan.warnings.append(_("The package lists could not be checked; run lux update if installing fails."))
            else:
                bad = [p for p in missing if p not in avail]
                if bad:
                    raise UserError(_("These packages are not in the repositories: %s") % ", ".join(bad) + "\n"
                                    + _("Check the names with: lux search NAME"))
            for sec, items in (("packages", [p for p in missing if p not in drivers]),
                               ("drivers", [p for p in missing if p in drivers])):
                if items:
                    plan.add(sec, "+", _("install: %s") % " ".join(items), 20,
                             lambda m=items: run([tool("lux"), "-y", "--repo", "install"] + m, stream=True,
                                                 env=env_lux()), data=items)
        mark = [p for p in wanted if p in installed and p not in explicit]
        if mark:
            plan.add("packages", "~", _("keep as wanted (now only a dependency): %s") % " ".join(mark), 21,
                     lambda m=mark: run([tool("lux-engine"), "-D", "--asexplicit"] + m), data=mark)
        dropped = []
        if "packages" in cfg:
            dropped += [p for p in applied.get("packages", []) if p not in wanted and p in explicit]
        if "drivers" in cfg:
            dropped += [p for p in applied.get("drivers", []) if p not in wanted and p in explicit and p not in dropped]
        unlisted = []
        if "packages" in cfg:
            # bez seznamu "drivers" v souboru zustavaji nainstalovane ovladace, jak jsou
            skip = set() if "drivers" in cfg else st.drivers()
            unlisted = sorted(p for p in explicit if p not in wanted and p not in extra and p not in dropped
                              and p not in skip)
        remove = list(dropped) + (unlisted if cfg.get("remove_unlisted") else [])
        kernels = {p for p in explicit if KERNEL_RE.match(p)}
        keep = [p for p in remove if p in PROTECTED_PACKAGES or p in kernels]
        remove = [p for p in remove if p not in keep]
        if keep:
            plan.notes.append(_("Kept, LuxOS needs them: %s") % " ".join(keep))
        drv_old = set(applied.get("drivers", []))
        for sec, items in (("packages", [p for p in remove if p not in drv_old]),
                           ("drivers", [p for p in remove if p in drv_old])):
            if items:
                plan.add(sec, "-", _("remove: %s") % " ".join(items), 90,
                         lambda m=items: run([tool("lux"), "-y", "remove"] + m, stream=True, env=env_lux()),
                         data=items)
        if unlisted and not cfg.get("remove_unlisted"):
            plan.notes.append(_("%d installed packages are not in the file; they stay (\"remove_unlisted\": True "
                                "would remove them).") % len(unlisted))

    # --- Flathub ---
    if "flatpaks" in cfg:
        have_fp = st.flatpaks() or set()
        wanted_fp = cfg["flatpaks"]
        add = [a for a in wanted_fp if a not in have_fp]
        if add:
            def install_fp(m=add):
                run([tool("flatpak"), "remote-add", "--system", "--if-not-exists", "flathub",
                     "https://dl.flathub.org/repo/flathub.flatpakrepo"])
                run([tool("flatpak"), "install", "--system", "-y", "--noninteractive", "flathub"] + m, stream=True)
            plan.add("flatpaks", "+", _("install: %s") % " ".join(add), 25, install_fp, data=add)
        dropped = [a for a in applied.get("flatpaks", []) if a not in wanted_fp and a in have_fp]
        unlisted = sorted(a for a in have_fp if a not in wanted_fp and a not in dropped)
        remove = dropped + (unlisted if cfg.get("remove_unlisted") else [])
        if remove:
            plan.add("flatpaks", "-", _("remove: %s") % " ".join(remove), 91,
                     lambda m=remove: run([tool("flatpak"), "uninstall", "--system", "-y", "--noninteractive"] + m,
                                          stream=True), data=remove)
        elif unlisted and not cfg.get("remove_unlisted"):
            plan.notes.append(_("%d installed Flathub apps are not in the file; they stay.") % len(unlisted))

    # --- system ---
    if "hostname" in cfg and cfg["hostname"] != st.hostname():
        plan.add("system", "~", _("computer name: %s → %s") % (st.hostname() or "-", cfg["hostname"]), 30,
                 lambda h=cfg["hostname"]: run([tool("hostnamectl"), "set-hostname", h]), target="hostname")
    if "timezone" in cfg and cfg["timezone"] != st.timezone():
        plan.add("system", "~", _("time zone: %s → %s") % (st.timezone() or "-", cfg["timezone"]), 30,
                 lambda z=cfg["timezone"]: run([tool("timedatectl"), "set-timezone", z]), target="timezone")
    if "locale" in cfg and cfg["locale"] != st.locale():
        plan.add("system", "~", _("language (locale): %s → %s") % (st.locale() or "-", cfg["locale"]), 30,
                 lambda loc=cfg["locale"]: apply_locale(loc), target="locale")
    if "keyboard" in cfg:
        cur = st.keyboard()
        kb = cfg["keyboard"]
        if kb["layouts"] != cur["layouts"] or kb["options"] != cur["options"]:
            plan.add("system", "~", _("keyboard layouts: %s → %s") % (
                " ".join(cur["layouts"] + cur["options"]) or "-", " ".join(kb["layouts"] + kb["options"])), 31,
                lambda k=kb, model=cur["model"]: apply_keyboard(k, model), target="keyboard")

    # --- skupiny a uzivatele ---
    groups = st.group() if ("groups" in cfg or "users" in cfg) else {}
    for g in cfg.get("groups", []):
        if g not in groups:
            plan.add("users", "+", _("create group %s") % g, 10, lambda g=g: run([tool("groupadd"), g]), target=g)
    if "users" in cfg:
        compute_users(cfg, st, plan, groups)

    # --- sluzby ---
    want_on, want_off = [], []
    if "services" in cfg:
        want_on += cfg["services"]["enable"]
        want_off += cfg["services"]["disable"]
        for u in applied.get("services_enable", []):
            if u not in want_on and u not in want_off and st.enabled(u) and not PROTECTED_UNITS.match(u):
                want_off.append(u)
    units = st.units() if (want_on or want_off or "guard" in cfg or "firewall" in cfg) else {}
    new_pkgs = any(c.section == "packages" and c.op == "+" for c in plan.changes)
    for u in want_on:
        if not st.enabled(u):
            known = u in units or ("@" in u and re.sub(r"@[^.]+\.", "@.", u) in units)
            if not known and not new_pkgs:
                raise UserError(_("Unknown service %s (no such unit on this computer).") % u)
            plan.add("services", "+", _("turn on %s") % u, 50,
                     lambda u=u: run([tool("systemctl"), "enable", "--now", u]), target=u)
    for u in want_off:
        if st.enabled(u):
            plan.add("services", "-", _("turn off %s") % u, 50,
                     lambda u=u: run([tool("systemctl"), "disable", "--now", u]), target=u)
    for key, u in GUARD_UNITS.items():
        if key in cfg.get("guard", {}):
            on = cfg["guard"][key]
            if on != st.enabled(u) and (u in units or on):
                if u not in units:
                    raise UserError(_("Lux Guard is not installed (lux install luxos-guard)."))
                plan.add("guard", "+" if on else "-", (_("turn on %s") if on else _("turn off %s")) % u, 51,
                         lambda u=u, on=on: run([tool("systemctl"), "enable" if on else "disable", "--now", u]), target=u)

    # --- LuxOS Care ---
    if cfg.get("care"):
        cur = st.care()
        want = {k: v for k, v in cfg["care"].items() if cur.get(k) != v}
        if want:
            text = ", ".join(f"{k}: {fmt(cur.get(k))} → {fmt(v)}" for k, v in want.items())
            plan.add("care", "~", text, 60, lambda w=want: apply_care(w), target="care")

    # --- firewall ---
    if cfg.get("firewall"):
        compute_firewall(cfg["firewall"], st, plan)

    # --- parametry jadra ---
    if "params" in cfg.get("kernel", {}):
        compute_kernel(cfg["kernel"]["params"], applied.get("kernel_params", []), st, plan)
    if "scheduler" in cfg.get("kernel", {}):
        cur = st.scheduler()
        if cur is None:
            raise UserError(_("kernel.scheduler: the process scheduler setting is missing (lux install luxos-tweaks)."))
        if cur != cfg["kernel"]["scheduler"]:
            plan.add("kernel", "~", _("process scheduler: %s → %s") % (cur, cfg["kernel"]["scheduler"]), 80,
                     lambda v=cfg["kernel"]["scheduler"]: run([tool("luxos-care"), "scheduler", v]), target="scheduler")

    # --- firemni sit (domena, luxos-domain) ---
    if cfg.get("domain"):
        compute_domain(cfg["domain"], plan)
    compute_more(cfg, st, plan, applied, force)
    plan.changes.sort(key=lambda c: c.phase)
    return plan


def fmt(v):
    if isinstance(v, bool):
        return "True" if v else "False"
    return str(v)


def compute_users(cfg, st, plan, groups):
    users = st.passwd()
    normal = st.normal_users()
    declared = set(cfg.get("groups", []))
    need_groups = set()
    admins = {n for n in normal if n in groups.get("wheel", {}).get("members", [])}
    had_admin = bool(admins)
    for name, u in cfg["users"].items():
        want_groups = u.get("groups")
        if want_groups is not None:
            need_groups |= {g for g in want_groups if g not in groups and g not in declared}
        if name not in users:
            argv = [tool("useradd"), "-m", "-U"]
            if want_groups:
                argv += ["-G", ",".join(want_groups)]
            if u.get("shell"):
                argv += ["-s", u["shell"]]
            if u.get("description"):
                argv += ["-c", u["description"]]
            if u.get("uid") is not None:
                argv += ["-u", str(u["uid"])]
            detail = _("create user %s") % name + (f" ({', '.join(want_groups)})" if want_groups else "")
            plan.add("users", "+", detail, 41, lambda a=argv + [name], g=want_groups or []: (ensure_groups(g), run(a)),
                     target=name)
            if not u.get("password_hash"):
                plan.notes.append(_("User %s has no password yet; set it with: sudo passwd %s") % (name, name))
        elif name not in normal:
            raise UserError(_("users.%s: this is a system account, it cannot be managed here.") % name)
        else:
            cur = users[name]
            if u.get("description") is not None and u["description"] != cur["description"]:
                plan.add("users", "~", _("%s: full name → %s") % (name, u["description"]), 42,
                         lambda n=name, d=u["description"]: run([tool("usermod"), "-c", d, n]), target=name)
            if u.get("shell") and u["shell"] != cur["shell"]:
                plan.add("users", "~", _("%s: shell %s → %s") % (name, cur["shell"], u["shell"]), 42,
                         lambda n=name, s=u["shell"]: run([tool("usermod"), "-s", s, n]), target=name)
            if u.get("uid") is not None and u["uid"] != cur["uid"]:
                raise UserError(_("users.%s.uid: the user already exists with UID %d; changing it is not supported.")
                                % (name, cur["uid"]))
            if want_groups is not None:
                have_g = st.user_groups(name)
                add = [g for g in want_groups if g not in have_g]
                rem = [g for g in have_g if g not in want_groups]
                if add:
                    plan.add("users", "+", _("%s: add to groups %s") % (name, ", ".join(add)), 42,
                             lambda n=name, a=add: [(ensure_groups([g]), run([tool("gpasswd"), "-a", n, g])) for g in a],
                             target=name)
                if rem:
                    plan.add("users", "-", _("%s: remove from groups %s") % (name, ", ".join(rem)), 42,
                             lambda n=name, r=rem: [run([tool("gpasswd"), "-d", n, g]) for g in r], target=name)
        if want_groups is not None:
            if "wheel" in want_groups:
                admins.add(name)
            else:
                admins.discard(name)
        if u.get("password_hash"):
            cur_hash = st.shadow_hash(name) if name in users else ""
            if cur_hash != u["password_hash"]:
                plan.add("users", "~", _("%s: set password (from password_hash)") % name, 43,
                         lambda n=name, h=u["password_hash"]: run([tool("chpasswd"), "-e"], input=f"{n}:{h}\n"),
                         target=name)
    for g in sorted(need_groups):
        plan.notes.append(_("Group %s does not exist yet; it is created if no package creates it.") % g)
    if had_admin and not admins:
        raise UserError(_("No user would be an administrator (group wheel). Add \"wheel\" to the groups of one user."))


def ensure_groups(names):
    have_g = State().group()
    for g in names:
        if g not in have_g:
            run([tool("groupadd"), g])


def compute_firewall(fw, st, plan):
    cur = st.firewall()
    pending = cur["installed"] or any(c.section == "packages" and c.op == "+" and "ufw" in (c.data or [])
                                      for c in plan.changes)
    if not pending:
        if fw.get("enable") or fw.get("allow"):
            raise UserError(_("The firewall (ufw) is not installed; add \"ufw\" to packages."))
        return
    if "allow" in fw:
        for spec in fw["allow"]:
            if spec not in cur["allow"]:
                plan.add("firewall", "+", _("allow incoming %s") % spec, 70,
                         lambda s=spec: run([tool("ufw"), "allow", s]), target=spec)
        for spec in cur["allow"]:
            if spec not in fw["allow"]:
                plan.add("firewall", "-", _("stop allowing incoming %s") % spec, 70,
                         lambda s=spec: run([tool("ufw"), "delete", "allow", s]), target=spec)
    if "enable" in fw and (fw["enable"] != cur["enable"] or fw["enable"] != st.enabled(FIREWALL_UNIT)):
        if fw["enable"]:
            plan.add("firewall", "+", _("turn on the firewall"), 71,
                     lambda: (run([tool("systemctl"), "enable", "--now", FIREWALL_UNIT]),
                              run([tool("ufw"), "--force", "enable"])), target="ufw")
        else:
            plan.add("firewall", "-", _("turn off the firewall"), 71,
                     lambda: (run([tool("ufw"), "disable"]), run([tool("systemctl"), "disable", "--now", FIREWALL_UNIT])),
                     target="ufw")


def compute_domain(dm, plan):
    """Spravci a prihlaseni domenovych skupin, offline prihlaseni - pres lux-domain (balik luxos-domain)."""
    try:
        with open(P(DOMAIN_STATE), encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    if not isinstance(state, dict) or not state.get("joined"):
        raise UserError(_("domain: this computer is not in an organization network; join it first with: "
                          "sudo lux domain join DOMAIN"))
    if not have("lux-domain"):
        raise UserError(_("domain: the organization network tools are not installed (lux install luxos-domain)."))
    ld = tool("lux-domain")
    for key, cur_key, label_add, label_rem, cmd in (
            ("admins", "admin_groups", _("administrators: add domain group %s"),
             _("administrators: remove domain group %s"), ("admins", "add", "remove")),
            ("allow_groups", "allow_groups", _("sign-in allowed for domain group %s"),
             _("sign-in no longer limited to domain group %s"), ("login", "allow", "deny"))):
        if key not in dm:
            continue
        cur = [str(g) for g in state.get(cur_key) or []]
        cur_cf = {g.casefold() for g in cur}
        want_cf = {g.casefold() for g in dm[key]}
        for g in dm[key]:
            if g.casefold() not in cur_cf:
                plan.add("domain", "+", label_add % g, 65,
                         lambda g=g, c=cmd: run([ld, c[0], c[1], g]), target=key)
        for g in cur:
            if g.casefold() not in want_cf:
                plan.add("domain", "-", label_rem % g, 65,
                         lambda g=g, c=cmd: run([ld, c[0], c[2], g]), target=key)
    for key, opt, label in (("offline_days", "offline-days", _("offline sign-in: %s → %s days")),
                            ("admin_offline_days", "admin-offline-days",
                             _("administrator rights offline: %s → %s days"))):
        if key in dm and dm[key] != state.get(key):
            plan.add("domain", "~", label % (state.get(key, "-"), dm[key]), 66,
                     lambda o=opt, v=dm[key]: run([ld, "set", o, str(v)]), target=key)


def compute_kernel(params, previous, st, plan):
    lay = st.boot()
    if lay is None:
        if params:
            raise UserError(_("Kernel parameters: no LuxOS boot entry found (systemd-boot or GRUB)."))
        return
    if lay["kind"] == "unreadable":
        plan.warnings.append(_("Kernel parameters can be read only with administrator rights (lux system diff asks for them)."))
        return
    cur = lay["params"]
    add = [p for p in params if p not in cur]
    remove = [p for p in previous if p not in params and p in cur and not BOOT_PARAM_RE.match(p)]
    if add or remove:
        text = " ".join([f"+{p}" for p in add] + [f"-{p}" for p in remove])
        plan.add("kernel", "~", text + "  " + _("(after a restart)"), 80,
                 lambda a=add, r=remove, lay=lay: apply_kernel(lay, a, r), target="params", data={"add": add, "remove": remove})
        plan.restart = True


# ---- provedeni ----------------------------------------------------------------------------------
def apply_locale(loc):
    ensure_locale(loc)
    set_kv("/etc/locale.conf", {"LANG": loc})


def apply_keyboard(kb, model):
    layouts, variants = [], []
    for lay in kb["layouts"]:
        m = re.match(r"^([a-z]+)(?:\(([^)]*)\))?$", lay)
        layouts.append(m.group(1))
        variants.append(m.group(2) or "")
    run([tool("localectl"), "set-x11-keymap", ",".join(layouts), model or "",
         ",".join(variants) if any(variants) else "", ",".join(kb["options"])])


def apply_care(want):
    values = {}
    if "mode" in want:
        values["MODE"] = want["mode"]
    if "snapshots" in want:
        values["SNAPSHOTS"] = "yes" if want["snapshots"] else "no"
    if "keep_snapshots" in want:
        values["SNAPSHOT_KEEP"] = str(want["keep_snapshots"])
    if "protect" in want:
        values["PROTECT"] = "yes" if want["protect"] else "no"
    if "verify" in want:
        values["VERIFY"] = "yes" if want["verify"] else "no"
    set_kv(CARE_CONF, values, header="# LuxOS Care - carefree (automatic updates and repairs) | classic (notify only)")
    # Ochrana systemu hned (bez restartu): /usr jen pro cteni, resp. zase zapisovatelny
    if "protect" in want and have("luxos-care"):
        run([tool("luxos-care"), "protect", "apply"])


def apply_kernel(lay, add, remove):
    for f in lay["files"]:
        text = read(f)
        new = set_params_text(text, lay["kind"], add, remove)
        if new != text:
            atomic_write(f, new)
    if lay["kind"] == "grub":
        run([tool("grub-mkconfig"), "-o", "/boot/grub/grub.cfg"])


@contextlib.contextmanager
def apply_lock():
    path = P(LOCK)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise UserError(_("Another lux system apply is running.")) from e
        yield


def take_snapshot():
    """-> (jmeno snimku nebo "", chyba nebo "")."""
    if not have("luxos-care"):
        return "", _("LuxOS Care is not installed (lux install luxos-care).")
    rc, out, err = capture([tool("luxos-care"), "snapshot", "--kind", "system"], timeout=900)
    if rc != 0:
        return "", (err or out).strip()[-500:] or f"exit {rc}"
    m = re.search(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", out)
    return (m.group(0) if m else "?"), ""


def record(cfg, path, kept_connections=()):
    """Stav po uspesnem apply (co soubor spravoval) + kopie souboru a zasad organizace v historii.
    Do seznamu, podle kterych se odebira (balicky, sluzby, parametry), jdou jen polozky lokalniho
    souboru: co zmizi ze zasady organizace (odchod z organizace), zustane nainstalovane."""
    lay = LAYERS

    def local(path_, values):
        return lay.local_items(path_, values) if lay is not None else values
    data = {"time": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "file": path}
    if "packages" in cfg:
        data["packages"] = local(("packages",), cfg["packages"])
    if "flatpaks" in cfg:
        data["flatpaks"] = local(("flatpaks",), cfg["flatpaks"])
    if "services" in cfg:
        data["services_enable"] = local(("services", "enable"), cfg["services"]["enable"])
    if "params" in cfg.get("kernel", {}):
        data["kernel_params"] = local(("kernel", "params"), cfg["kernel"]["params"])
    if "drivers" in cfg:
        data["drivers"] = local(("drivers",), cfg["drivers"])

    def local_keys(path_, names):
        if lay is None or not lay.fragments:
            return list(names)
        return [n for n in names if any(o.kind == "local" for o in lay.origins(path_ + (n,)))
                or not lay.origins(path_ + (n,))]
    cons = cfg.get("network", {}).get("connections")
    if cons is not None:
        data["connections"] = local_keys(("network", "connections"), cons) + [
            n for n in kept_connections if n not in cons]
    queues = cfg.get("printers", {}).get("queues")
    if queues is not None:
        data["printers"] = local_keys(("printers", "queues"), queues)
    try:
        with open(path, "rb") as f:
            src = f.read()
        data["sha256"] = hashlib.sha256(src).hexdigest()
    except OSError:
        src = None
    frags = lay.fragments if lay is not None else []
    if frags:
        data["policies"] = [{"file": o.file, "sha256": sha} for o, sha in frags]
    atomic_write(APPLIED, json.dumps(data, indent=1, ensure_ascii=False) + "\n", 0o600)
    # zamky pro aplikace (Nastaveni ukaze "nastaveno organizaci"), bez tajemstvi -> citelne pro vsechny
    pol = lay.policy_json() if lay is not None else {"fragments": [], "locks": []}
    atomic_write(POLICY_STATE, json.dumps(pol, indent=1, ensure_ascii=False) + "\n", 0o644)
    if src is None and not frags:
        return
    hist = P(HISTORY_DIR)
    os.makedirs(hist, mode=0o700, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base, n = stamp, 1
    while os.path.exists(os.path.join(hist, base + ".lsl")) or os.path.exists(os.path.join(hist, base + ".d")):
        base, n = f"{stamp}-{n}", n + 1
    if src is not None:
        with open(os.path.join(hist, base + ".lsl"), "wb") as f:
            f.write(src)
        os.chmod(os.path.join(hist, base + ".lsl"), 0o600)
    if frags:
        d = os.path.join(hist, base + ".d")
        os.makedirs(d, mode=0o700)
        for o, _sha in frags:
            with contextlib.suppress(OSError):
                shutil.copyfile(o.file, os.path.join(d, os.path.basename(o.file)))
                os.chmod(os.path.join(d, os.path.basename(o.file)), 0o600)
    names = os.listdir(hist)
    stamps = sorted({n[:-4] if n.endswith(".lsl") else n[:-2] for n in names if n.endswith((".lsl", ".d"))})
    for old in stamps[:-HISTORY_KEEP]:
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(hist, old + ".lsl"))
        shutil.rmtree(os.path.join(hist, old + ".d"), ignore_errors=True)


# ---- vypis ---------------------------------------------------------------------------------------
def print_plan(plan):
    if LAYERS is not None and LAYERS.fragments:
        print(D + _("Organization policies: %s") % ", ".join(o.label() for o, _s in LAYERS.fragments) + R)
    if not plan.changes:
        ok(_("The system already matches the configuration. Nothing to do."))
    else:
        sym = {"+": G + "+" + R, "-": E + "-" + R, "~": Y + "~" + R}
        for sec, title in SECTIONS:
            items = [c for c in plan.changes if c.section == sec]
            if items:
                print(f"{B}{_(title)}{R}")
                for c in items:
                    org = change_origin(c)
                    print(f"  {sym[c.op]} {c.text}" + (f"  {D}[{'; '.join(org)}]{R}" if org else ""))
    for n in plan.notes:
        print(f"{D}{n}{R}")
    for w in plan.warnings:
        warn(w)


def ask(question, default_yes):
    try:
        a = input(f"{B}{question}{R} {'[Y/n]' if default_yes else '[y/N]'} ").strip().lower()
    except EOFError:
        return False
    return (not a and default_yes) or a[:1] in ("y", "a", "j")


# ---- show: soubor ze soucasneho systemu -------------------------------------------------------------
def lsl_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def lsl_list(items, indent):
    if not items:
        return "[]"
    if sum(len(i) + 4 for i in items) + indent < 90 and len(items) <= 6:
        return "[" + ", ".join(lsl_str(i) for i in items) + "]"
    pad = " " * (indent + 4)
    return "[\n" + ",\n".join(pad + lsl_str(i) for i in items) + "\n" + " " * indent + "]"


def lsl_bool(v):
    return "True" if v else "False"


_SYS_TR = {}


def _c(text):
    """Komentar vygenerovaneho souboru v jazyce SYSTEMU (LANG v /etc/locale.conf), ne volajiciho:
    soubor cte kdokoli, kdo pocitac spravuje."""
    lang = (read_kv("/etc/locale.conf").get("LANG") or "en").split("_")[0].split(".")[0].split("@")[0] or "en"
    d = os.environ.get("LUXOS_I18N_DIR") or "/usr/share/luxos/i18n"
    key = (d, lang)
    if key not in _SYS_TR:
        tr = {}
        try:
            with open(os.path.join(d, f"{lang}.tsv"), encoding="utf-8") as f:
                for line in f:
                    if "\t" in line and not line.startswith("#"):
                        k, v = line.rstrip("\n").split("\t", 1)
                        if v:
                            tr[k] = v
        except OSError:
            pass
        _SYS_TR[key] = tr
    return _SYS_TR[key].get(text, text)


def N_(text):
    """Znacka textu k prekladu (preklada se az pri pouziti, napr. v note())."""
    return text


def lsl_value(v, indent):
    if isinstance(v, bool):
        return lsl_bool(v)
    if v is None:
        return "None"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return lsl_list(v, indent)
    if isinstance(v, dict):
        return "{" + ", ".join(f"{lsl_str(k)}: {lsl_value(x, indent)}" for k, x in v.items()) + "}"
    return lsl_str(str(v))


def generate(st):
    """Text /etc/luxos/system.lsl podle soucasneho systemu: skupiny s vysvetlenim v jazyce systemu.
    Nikdy hesla: ani otisky hesel uzivatelu, ani hesla Wi-Fi/VPN (ta zustavaji v NetworkManageru)."""
    today = datetime.date.today().isoformat()
    L = []
    w = L.append

    def head(title, *lines):
        w("")
        w("    # ── " + _c(title) + " " + "─" * max(4, 70 - len(_c(title))))
        for ln in lines:
            w("    # " + _c(ln))

    def note(text, indent=4):
        w(" " * indent + "# " + _c(text))

    w("# " + _c("LuxOS - configuration of the whole system in one file (LSL)"))
    w("# " + _c("Generated by 'lux system show' on %s from this computer.") % today)
    w("#")
    w("# " + _c("Each section below describes one part of the system."))
    w("# " + _c("A missing setting or a deleted section means \"leave it as it is\": only what is written here is managed."))
    w("# " + _c("Passwords are never stored here (users, Wi-Fi, VPN): they stay in the system."))
    w("#")
    w("# " + _c("Check: lux system check   ·   What would change: lux system diff"))
    w("# " + _c("Apply: sudo lux system apply (a snapshot is taken first, undo with: lux rollback)"))
    w("# " + _c("Something broke? sudo lux system fix returns the system to the state described here."))
    w("# " + _c("Help: man luxos-system or ask LuxAI"))
    w("load config")
    w("")
    w("config = {")

    # --- pocitac a jazyk ---
    head("Computer and language")
    note("Computer name in the network")
    w(f"    \"hostname\": {lsl_str(st.hostname() or 'luxos')}")
    tz = st.timezone()
    if tz:
        note("Time zone (list: timedatectl list-timezones)")
        w(f"    \"timezone\": {lsl_str(tz)}")
    loc = st.locale()
    if loc:
        note("Language and formats (e.g. \"cs_CZ.UTF-8\", \"en_US.UTF-8\")")
        w(f"    \"locale\": {lsl_str(loc)}")
    fm = st.formats()
    note("Other formats than the language, e.g. \"LC_TIME\": \"cs_CZ.UTF-8\" (date and time), \"LC_PAPER\"")
    w("    \"formats\": {" + ("" if fm else "}"))
    if fm:
        for k in sorted(fm):
            w(f"        {lsl_str(k)}: {lsl_str(fm[k])}")
        w("    }")
    kb = st.keyboard()
    if kb["layouts"]:
        note("Keyboard layouts (the first is the default, at most 4) and how to switch them")
        w("    \"keyboard\": {")
        w(f"        \"layouts\": {lsl_list(kb['layouts'], 8)}")
        w(f"        \"options\": {lsl_list(kb['options'], 8)}")
        w("    }")
    con = st.console()
    if con:
        note("Text console (without the desktop): keyboard and font")
        w("    \"console\": {" + ", ".join(f"{lsl_str(k)}: {lsl_str(v)}" for k, v in con.items()) + "}")

    # --- software ---
    head("Software", "Deleting a line removes the package at the next apply.")
    drivers = st.drivers()
    note("Packages from the LuxOS and Arch Linux repositories (lux search NAME)")
    w(f"    \"packages\": {lsl_list(sorted(st.explicit() - drivers), 4)}")
    note("Drivers (graphics, Wi-Fi, printers from [luxos-drivers]); the Drivers app suggests them")
    w(f"    \"drivers\": {lsl_list(sorted(drivers), 4)}")
    fps = st.flatpaks()
    if fps is not None:
        note("Apps from Flathub (app ID, e.g. \"org.mozilla.firefox\")")
        w(f"    \"flatpaks\": {lsl_list(sorted(fps), 4)}")
    note("True = also remove packages and apps that are not listed here (careful)")
    w("    \"remove_unlisted\": False")
    repos = st.repos()
    if repos is not None:
        note("Package sources - only checked, lux system does not change them (edit /etc/lux/lux.conf)")
        w("    \"repos\": {")
        w(f"        \"list\": {lsl_list(repos['list'], 8)}")
        note("community = packages from the community (AUR, built in the sandbox)", 8)
        w(f"        \"community\": {lsl_bool(repos['community'])}")
        w(f"        \"review_build_scripts\": {lsl_bool(repos['review_build_scripts'])}")
        w(f"        \"flatpak_updates\": {lsl_bool(repos['flatpak_updates'])}")
        w("    }")

    # --- sluzby ---
    units = st.units()
    skip = set(GUARD_UNITS.values()) | {FIREWALL_UNIT}
    on = sorted(u for u, (state, preset) in units.items()
                if state == "enabled" and preset != "enabled" and "@." not in u and u not in skip
                and u.rsplit(".", 1)[-1] in ("service", "socket", "timer", "path"))
    head("Services", "Started at boot. A removed line turns the service off at the next apply.",
         "Remote access: \"sshd\" (SSH server). Bluetooth: \"bluetooth\".")
    w("    \"services\": {")
    w(f"        \"enable\": {lsl_list(on, 8)}")
    w("        \"disable\": []")
    w("    }")

    # --- uzivatele ---
    normal = st.normal_users()
    gmin, gmax = st.login_defs()[2:]
    own = sorted(g for g, v in st.group().items() if gmin <= v["gid"] < gmax and g not in normal)
    head("Users", "Users (passwords never go here; \"wheel\" = administrator).",
         "Optional \"password_hash\": output of 'openssl passwd -6'. Users are never deleted.")
    note("Extra groups")
    w(f"    \"groups\": {lsl_list(own, 4)}")
    w("    \"users\": {")
    for name in sorted(normal):
        u = normal[name]
        w(f"        {lsl_str(name)}: {{")
        w(f"            \"description\": {lsl_str(u['description'])}")
        w(f"            \"groups\": {lsl_list(st.user_groups(name), 12)}")
        w(f"            \"shell\": {lsl_str(u['shell'])}")
        w("        }")
    w("    }")

    # --- sit ---
    cons = st.connections()
    head("Network", "Saved connections (NetworkManager). Wi-Fi and VPN passwords are not here: they are kept by the system.",
         "security: \"none\" = open, \"wpa-psk\" = WPA2 password, \"sae\" = WPA3; ipv4 \"auto\" = automatic (DHCP).",
         "A connection in use is never deleted without --force (remote access could be cut off).")
    if cons is None:
        note("Network connections: run 'sudo lux system show' to include them")
    else:
        w("    \"network\": {")
        w("        \"connections\": {" + ("" if cons else "}"))
        for name in sorted(cons):
            c = cons[name]
            w(f"            {lsl_str(name)}: {{")
            w(f"                \"type\": {lsl_str(c['type'])}")
            if c["type"] == "wifi":
                w(f"                \"ssid\": {lsl_str(c['ssid'])}")
                sec = f"                \"security\": {lsl_str(c['security'])}"
                if c["security"] != "none":
                    sec += "   # " + _c("password: kept by the system")
                w(sec)
            if c.get("interface"):
                w(f"                \"interface\": {lsl_str(c['interface'])}")
            w(f"                \"autoconnect\": {lsl_bool(c['autoconnect'])}")
            if c["type"] in NET_TYPES:
                for fam in ("ipv4", "ipv6"):
                    if fam in c:
                        w(f"                \"{fam}\": {lsl_value(c[fam], 16)}")
                if c.get("proxy"):
                    w(f"                \"proxy\": {lsl_str(c['proxy'])}")
            w("            }")
        if cons:
            w("        }")
        w("    }")

    # --- tiskarny ---
    pr = st.printers()
    head("Printers", "\"model\": \"everywhere\" = driverless printing, otherwise the driver from 'lpinfo -m'.")
    if pr is None:
        note("Printing (CUPS) is not running - printers are not included")
    else:
        w("    \"printers\": {")
        w(f"        \"default\": {lsl_str(pr['default']) if pr['default'] else 'None'}")
        w("        \"queues\": {" + ("" if pr["queues"] else "}"))
        for name in sorted(pr["queues"]):
            q = pr["queues"][name]
            w(f"            {lsl_str(name)}: {{")
            w(f"                \"uri\": {lsl_str(q['uri'])}")
            if q["model"]:
                w(f"                \"model\": {lsl_str(q['model'])}")
            w(f"                \"shared\": {lsl_bool(q['shared'])}")
            w("            }")
        if pr["queues"]:
            w("        }")
        w("    }")

    # --- napajeni ---
    pw = st.power()
    head("Power", "For the whole computer (login screen, nobody signed in); in the desktop each user's own setting applies.",
         "lid: \"suspend\", \"hibernate\", \"lock\", \"poweroff\" or \"ignore\".")
    w("    \"power\": {")
    w(f"        \"lid\": {lsl_str(pw['lid'])}")
    note("lid closed while the power adapter is connected", 8)
    w(f"        \"lid_on_power\": {lsl_str(pw['lid_on_power'])}")
    if "suspend_after_minutes" in pw:
        note("sleep after so many minutes without use (0 = never)", 8)
        w(f"        \"suspend_after_minutes\": {pw['suspend_after_minutes']}")
    if "profile" in pw and not st.powersaver_on():
        note("\"power-saver\", \"balanced\" or \"performance\"", 8)
        w(f"        \"profile\": {lsl_str(pw['profile'])}")
    w("    }")

    # --- start pocitace ---
    head("Boot", "Boot menu: how many seconds it is shown (0 = hidden, hold Space to see it).",
         "default: \"luxos\" = the newest working LuxOS, or another entry. Snapshots are not listed here.")
    bt = st.boot_settings()
    lay = st.boot()
    if bt is not None:
        w("    \"boot\": {")
        if bt["timeout"] is not None:
            w(f"        \"timeout\": {bt['timeout']}")
        w(f"        \"default\": {lsl_str(bt['default'])}")
        w("    }")
    if lay is not None and lay["kind"] == "unreadable":
        note("Kernel parameters: run 'sudo lux system show' to include them")
        if st.scheduler() is not None:
            w("    \"kernel\": {\"scheduler\": " + lsl_str(st.scheduler()) + "}")
    elif lay is not None:
        params = [p for p in lay["params"] if not BOOT_PARAM_RE.match(p)]
        note("Kernel parameters (disk and encryption parameters are not managed here)")
        w("    \"kernel\": {")
        w(f"        \"params\": {lsl_list(params, 8)}")
        if st.scheduler() is not None:
            note("process scheduler: \"lavd\" = smooth desktop and games (default), \"default\" = the kernel's own", 8)
            w(f"        \"scheduler\": {lsl_str(st.scheduler())}")
        w("    }")

    # --- aktualizace a zabezpeceni ---
    head("Updates and security")
    care = st.care()
    note("LuxOS Care: \"carefree\" = automatic updates, \"classic\" = only notify")
    w("    \"care\": {")
    w(f"        \"mode\": {lsl_str(care['mode'])}")
    w(f"        \"snapshots\": {lsl_bool(care['snapshots'])}")
    w(f"        \"keep_snapshots\": {care['keep_snapshots']}")
    note("protect = /usr read-only except during updates; verify = weekly check of system files", 8)
    w(f"        \"protect\": {lsl_bool(care['protect'])}")
    w(f"        \"verify\": {lsl_bool(care['verify'])}")
    w("    }")
    if any(u in units for u in GUARD_UNITS.values()):
        note("Lux Guard: protection against harmful downloads, hourly snapshots of /home")
        w("    \"guard\": {")
        w(f"        \"enable\": {lsl_bool(st.enabled(GUARD_UNITS['enable']))}")
        w(f"        \"home_snapshots\": {lsl_bool(st.enabled(GUARD_UNITS['home_snapshots']))}")
        w("    }")
    fw = st.firewall()
    note("Firewall (ufw): allowed incoming ports, e.g. [\"22/tcp\"]")
    w("    \"firewall\": {")
    w(f"        \"enable\": {lsl_bool(fw['enable'] and fw['installed'])}")
    w(f"        \"allow\": {lsl_list(fw['allow'], 8)}")
    w("    }")
    fl = st.faillock()
    note("Wrong passwords: after \"deny\" failures within \"fail_interval\" seconds the account waits \"unlock_time\" seconds.")
    note("LuxOS: 20 / 30 / 60 - only a brute-force attack is stopped, you are never locked out for long.")
    w("    \"security\": {")
    w("        \"faillock\": {" + ", ".join(f"\"{k}\": {fl[k]}" for k in ("deny", "fail_interval", "unlock_time")) + "}")
    w("    }")

    # --- novi uzivatele ---
    nu = st.new_users()
    head("Defaults for new users", "Used when a NEW user signs in for the first time; existing users keep their settings.",
         "Delete the # at the start of a line to use it.")
    w("    \"new_users\": {")
    examples = (("theme", "\"dark\"", N_("\"light\", \"dark\" or \"auto\" (by sunrise and sunset)")),
                ("wallpaper", "\"/usr/share/backgrounds/luxos/luxos-dark.jpg\"", None),
                ("dock", "[\"luxos-launchpad\", \"firefox\", \"thunar\", \"luxos-terminal\", \"trash\"]",
                 N_("apps in the Dock (names of .desktop files)")),
                ("browser", "\"firefox\"", N_("default apps")),
                ("text_editor", "\"luxos-text\"", None), ("mail", "\"thunderbird\"", None),
                ("lock_after_minutes", "10", N_("lock the screen after so many minutes without use")),
                ("screen_off_minutes", "20", N_("turn the screen off after so many minutes")))
    for k, example, comment in examples:
        if comment:
            note(comment, 8)
        if k in nu:
            v = [x[:-8] if x.endswith(".desktop") else x for x in nu[k]] if k == "dock" else nu[k]
            if isinstance(v, str) and k in ("browser", "text_editor", "mail") and v.endswith(".desktop"):
                v = v[:-8]
            w(f"        \"{k}\": {lsl_value(v, 8)}")
        else:
            w(f"        # \"{k}\": {example}")
    w("    }")
    w("}")
    return "\n".join(L) + "\n"


# ---- prikazy --------------------------------------------------------------------------------------
def need_root():
    if os.geteuid() != 0 and not ROOT:
        raise UserError(_("This needs administrator rights (run it through lux system ...)."))


def cmd_show(args):
    if args.origin:
        return show_origin(args)
    sys.stdout.write(generate(State()))
    return 0


def show_origin(args):
    """Sloucena konfigurace (zasady organizace + soubor): kazda polozka s puvodem a zamkem."""
    load(args.file, policies=not args.no_policies)
    lay = LAYERS
    rows = []

    def walk(path, value):
        if isinstance(value, dict) and value and not is_union(path):
            for k, v in value.items():
                walk(path + (k,), v)
            return
        if is_union(path) and isinstance(value, list):
            for it in value:
                lk = lay.item_locks.get((path, _jkey(it))) or lay.lock_of(path)
                rows.append((dotted(path) + "[]", it, lay.origins(path, it), lk))
            return
        rows.append((dotted(path), value, lay.origins(path), lay.lock_of(path)))
    walk((), lay.value)
    if args.json:
        print(json.dumps({"config": lay.value, "policy": lay.policy_json(),
                          "items": [{"path": p, "value": v, "origins": [o.json() for o in orgs],
                                     "locked": lk.json() if lk else None} for p, v, orgs, lk in rows]},
                         indent=1, ensure_ascii=False))
        return 0
    if lay.fragments:
        print(D + _("Organization policies: %s") % ", ".join(o.label() for o, _s in lay.fragments) + R)
    for p, v, orgs, lk in rows:
        where = "; ".join(o.label() for o in orgs)
        lock = f" {Y}🔒 {_('locked')}{R}" if lk else ""
        print(f"{p} = {json.dumps(v, ensure_ascii=False)}  {D}← {where}{R}{lock}")
    return 0


def cmd_locks(args):
    """Polozky, ktere organizace vynutila (config.mkForce) - lokalne je nelze zmenit."""
    load(args.file, policies=True)
    locks = LAYERS.lock_list()
    if args.json:
        print(json.dumps(LAYERS.policy_json(), indent=1, ensure_ascii=False))
        return 0
    if not LAYERS.fragments:
        ok(_("This computer has no organization policies (%s is empty).") % FRAGMENT_DIR)
        return 0
    print(D + _("Organization policies: %s") % ", ".join(o.label() for o, _s in LAYERS.fragments) + R)
    if not locks:
        ok(_("No settings are locked by the organization."))
        return 0
    for p, item, o in locks:
        what = p if item is None else f"{p}: {json.dumps(item, ensure_ascii=False)}"
        print(f"  🔒 {what}  {D}← {o.label()}{R}")
    return 0


def oem_pending():
    """OEM predinstalace pred dokoncenim Pruvodce nastavenim: soubor vznikne az s uctem majitele."""
    return read_kv(OEM_CONF).get("OEM") == "1" and not os.path.exists(P(OEM_DONE))


def generated_untouched(path):
    """Soubor od posledniho init/apply nikdo neupravil (stejny otisk jako v applied.json)."""
    return bool(read_applied().get("sha256")) and file_sha(path) == read_applied().get("sha256")


def cmd_init(args):
    """init: zapsat soubor ze soucasneho systemu.
    --auto (instalator, aktualizace lux): jednou, jen kdyz soubor chybi a nebezi OEM priprava; nikdy neselze.
    --refresh (OEM po Pruvodci): prepsat jen soubor, ktery od vygenerovani nikdo neupravil."""
    need_root()
    path = P(CONFIG)
    soft = args.auto or args.refresh
    if args.auto and (os.path.exists(path) or os.path.exists(P(AUTO_STAMP)) or oem_pending()):
        return 0
    if args.refresh and os.path.exists(path) and not generated_untouched(path):
        say(_("%s was edited, it stays as it is.") % CONFIG)
        return 0
    if os.path.exists(path) and not (args.force or args.refresh):
        raise UserError(_("%s already exists. Show the differences with: lux system diff (or init --force "
                          "to overwrite it).") % CONFIG)
    try:
        st = State()
        text = generate(st)
    except UserError as e:
        if soft:
            warn(str(e))
            return 0
        raise
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
        say(_("The previous file was kept as %s") % (CONFIG + ".bak"))
    atomic_write(CONFIG, text, 0o644)
    atomic_write(AUTO_STAMP, datetime.date.today().isoformat() + "\n", 0o644)
    # bez zasad organizace: soubor popisuje tento pocitac, zamky se overi az pri diff/apply
    try:
        cfg = load(path, policies=False)
    except UserError as e:
        if not soft:
            raise
        warn(str(e))
        return 0
    record(cfg, path)
    ok(_("Written %s from this computer.") % CONFIG)
    if not soft:
        print(_("Edit it (sudo lux system edit), then: lux system diff and sudo lux system apply"))
    return 0


def cmd_check(args):
    cfg = load(args.file, policies=not args.no_policies)
    ok(_("The configuration %s is valid.") % args.file)
    parts = [k for k in TOP_KEYS if k in cfg]
    print(D + _("Managed: %s") % ", ".join(parts) + R)
    if LAYERS.fragments:
        print(D + _("Organization policies: %s") % ", ".join(o.label() for o, _s in LAYERS.fragments) + R)
    return 0


def cmd_plan(args):
    print(json.dumps(load(args.file, policies=not args.no_policies), indent=1, ensure_ascii=False))
    return 0


def cmd_diff(args):
    cfg = load(args.file, policies=not args.no_policies)
    plan = compute(cfg, State(), force=args.force)
    if args.json:
        changes = []
        for c in plan.changes:
            d = c.json()
            org = change_origin(c)
            if org:
                d["origin"] = org
            changes.append(d)
        print(json.dumps({"changes": changes, "notes": plan.notes, "warnings": plan.warnings,
                          "restart": plan.restart,
                          "policies": [o.label() for o, _s in LAYERS.fragments]}, indent=1, ensure_ascii=False))
    else:
        print_plan(plan)
    return 0


def cmd_apply(args, fixing=False):
    need_root()
    st = State()
    if st.booted_snapshot():
        raise UserError(_("LuxOS is running from a snapshot, changes would be lost after a restart. "
                          "To keep this version, run: lux rollback"))
    cfg = load(args.file)   # zasady organizace plati vzdy (--no-policies jen pro check/diff)
    with apply_lock():
        if fixing:
            say(_("Repair: the system returns to the state described in %s") % args.file)
        plan = compute(cfg, st, force=args.force)
        print_plan(plan)
        if not plan.changes:
            record(cfg, args.file, plan.kept_connections)
            return 0
        if not args.yes:
            if not sys.stdin.isatty():
                raise UserError(_("Nothing was changed. Confirm with -y when running without a terminal."))
            if not ask(_("Apply these changes?"), default_yes=not plan.removals()):
                raise UserError(_("Cancelled. Nothing was changed."))
        # Pouzivane sitove pripojeni (treba SSH na vzdalenem pocitaci): zvlastni potvrzeni, s -y jen s --force
        risky = [c for c in plan.changes if c.risky]
        if risky:
            warn(_("These changes affect the network connection in use; a remote (SSH) connection to this "
                   "computer can be cut off:"))
            for c in risky:
                print(f"  {Y}!{R} {c.text}", file=sys.stderr)
            go = args.force or (not args.yes and sys.stdin.isatty()
                                and ask(_("Change the network connection in use too?"), default_yes=False))
            if not go:
                plan.changes = [c for c in plan.changes if not c.risky]
                plan.kept_connections += [c.target for c in risky if c.op == "-"]
                warn(_("The network connection in use was left as it is (apply it with --force)."))
                if not plan.changes:
                    record(cfg, args.file, plan.kept_connections)
                    return 0
        snap = ""
        if not args.no_snapshot:
            say(_("Taking a system snapshot first"))
            snap, why = take_snapshot()
            if not snap:
                warn(_("The snapshot could not be taken: %s") % why)
                if args.yes or not sys.stdin.isatty():
                    raise UserError(_("Nothing was changed. To apply without a snapshot use --no-snapshot."))
                if not ask(_("Continue without a snapshot (no way back with lux rollback)?"), default_yes=False):
                    raise UserError(_("Cancelled. Nothing was changed."))
        done = 0
        for c in plan.changes:
            say(c.text)
            try:
                c.action()
            except ApplyError as e:
                print(f"{E}✗{R} " + _("Failed: %s") % c.text, file=sys.stderr)
                print(str(e).strip(), file=sys.stderr)
                msg = _("%d of %d changes were made.") % (done, len(plan.changes))
                if snap:
                    msg += " " + _("Back to the state before: lux rollback %s") % snap
                raise UserError(msg) from e
            done += 1
        record(cfg, args.file, plan.kept_connections)
    ok(_("Done: %d changes.") % done)
    if snap:
        print(D + _("Snapshot before the change: %s (undo: lux rollback %s)") % (snap, snap) + R)
    if plan.restart:
        print(_("Restart the computer to use the new kernel parameters."))
    return 0


def cmd_fix(args):
    """Oprava: vrati system do stavu podle souboru (rozdil, potvrzeni, snimek, provedeni) - jako apply."""
    return cmd_apply(args, fixing=True)


class Args:
    def __init__(self, argv):
        self.yes = self.json = self.no_snapshot = self.force = self.origin = self.no_policies = False
        self.auto = self.refresh = False
        self.cmd, self.file = None, None
        for a in argv:
            if a in ("-y", "--yes"):
                self.yes = True
            elif a == "--json":
                self.json = True
            elif a == "--no-snapshot":
                self.no_snapshot = True
            elif a == "--origin":
                self.origin = True
            elif a == "--no-policies":
                self.no_policies = True
            elif a == "--force":
                self.force = True
            elif a == "--auto":
                self.auto = True
            elif a == "--refresh":
                self.refresh = True
            elif a.startswith("-") and a != "-":
                raise UserError(_("Unknown option %s") % a)
            elif self.cmd is None:
                self.cmd = a
            elif self.file is None:
                self.file = a
            else:
                raise UserError(_("Too many arguments"))
        self.file = self.file or P(CONFIG)


USAGE = """lux system show [--origin] | init [--force] | check [FILE] | diff [FILE] [--json] | apply [FILE] [-y] [--no-snapshot] [--force] | fix [FILE] [-y] | locks [--json]"""


def main(argv):
    try:
        args = Args(argv[1:])
        handlers = {"show": cmd_show, "init": cmd_init, "check": cmd_check, "diff": cmd_diff, "apply": cmd_apply,
                    "fix": cmd_fix, "plan": cmd_plan, "locks": cmd_locks}
        if args.cmd not in handlers:
            print(_("Usage:") + " " + USAGE, file=sys.stderr)
            return 2
        return handlers[args.cmd](args)
    except UserError as e:
        print(f"{E}✗{R} {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv))
