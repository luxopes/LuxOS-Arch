#!/usr/bin/python3
"""lux_system - cely system LuxOS v jednom souboru LSL (/etc/luxos/system.lsl), jako configuration.nix.

  lux_system.py [volby] PRIKAZ [SOUBOR]

  show                 vypise konfiguraci podle soucasneho systemu (vychozi soubor pro stavajici instalace)
  init [--force]       zapise /etc/luxos/system.lsl ze soucasneho systemu                    (root)
  check [SOUBOR]       vyhodnoti a zkontroluje soubor (system nemeni)
  diff [SOUBOR]        co by se zmenilo (--json strojove)                                   (root)
  apply [SOUBOR]       snimek systemu (LuxOS Care), rozdil, potvrzeni a provedeni           (root)
  plan [SOUBOR]        vyhodnocena konfigurace jako JSON (ladeni)
  show --origin        sloucena konfigurace (soubor + zasady organizace) s puvodem kazde polozky
  locks [--json]       polozky zamcene organizaci (config.mkForce v /etc/luxos/system.d)

Volby: -y/--yes (bez potvrzeni), --json, --no-snapshot (apply bez snimku), --force (init),
       --no-policies (jen dany soubor, bez /etc/luxos/system.d)

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
import contextlib
import datetime
import difflib
import fcntl
import hashlib
import json
import os
import re
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
    "lux-domain": "/usr/bin/lux-domain",
}

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
UNION_PATHS = {("packages",), ("flatpaks",), ("groups",), ("services", "enable"), ("services", "disable"),
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
TOP_KEYS = ("hostname", "timezone", "locale", "keyboard", "packages", "flatpaks", "remove_unlisted", "services",
            "groups", "users", "care", "guard", "firewall", "kernel", "domain")
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
                if k != "params":
                    ck.unknown("kernel", k, ("params",))
            params = ck.str_list("kernel.params", kn.get("params", []), PARAM_RE, "kernel parameter")
            for p in params:
                if BOOT_PARAM_RE.match(p):
                    ck.err("kernel.params", _("%s is set by the installer (disk, encryption) and cannot be changed here") % p)
            cfg["kernel"] = {"params": params}
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
    if "services" in cfg:
        managed = {u: k for k, u in GUARD_UNITS.items()} if "guard" in cfg else {}
        for u in cfg["services"]["enable"] + cfg["services"]["disable"]:
            if u in managed and managed[u] in cfg["guard"]:
                ck.err("services", _("%s is set in \"guard\"; remove it from services") % u)
            if u == FIREWALL_UNIT and "enable" in cfg.get("firewall", {}):
                ck.err("services", _("%s is set in \"firewall\"; remove it from services") % u)
    return cfg, ck.errors


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
    if c.section in ("packages", "flatpaks"):
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
    if c.section in ("guard", "firewall", "care", "kernel", "domain"):
        return org_labels((c.section,))
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

    def boot(self):
        return self._get("boot", boot_layout)

    def booted_snapshot(self):
        m = re.search(r"(?:^|\s)luxos\.snapshot=(\S+)", read("/proc/cmdline"))
        return m.group(1) if m else ""


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


# ---- plan zmen ---------------------------------------------------------------------------------
SECTIONS = [("packages", "Packages"), ("flatpaks", "Flathub apps"), ("system", "System"), ("users", "Users and groups"),
            ("services", "Services"), ("care", "LuxOS Care"), ("guard", "Lux Guard"), ("firewall", "Firewall"),
            ("kernel", "Kernel parameters"), ("domain", "Organization network")]


class Change:
    def __init__(self, section, op, text, phase, action, target="", data=None):
        self.section, self.op, self.text, self.phase, self.action = section, op, text, phase, action
        self.target, self.data = target, data

    def json(self):
        d = {"section": self.section, "op": {"+": "add", "-": "remove", "~": "change"}[self.op], "target": self.target,
             "text": self.text}
        if self.data is not None:
            d["items"] = self.data
        return d


class Plan:
    def __init__(self):
        self.changes, self.notes, self.warnings = [], [], []
        self.restart = False

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


def compute(cfg, st, applied=None):
    applied = read_applied() if applied is None else applied
    plan = Plan()

    # --- balicky ---
    wanted = list(cfg.get("packages", []))
    extra = []
    if cfg.get("firewall", {}).get("enable") and "ufw" not in wanted:
        extra.append("ufw")
    if cfg.get("flatpaks") and not have("flatpak") and "flatpak" not in wanted:
        extra.append("flatpak")
    if "packages" in cfg or extra:
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
            plan.add("packages", "+", _("install: %s") % " ".join(missing), 20,
                     lambda m=missing: run([tool("lux"), "-y", "--repo", "install"] + m, stream=True, env=env_lux()),
                     data=missing)
        mark = [p for p in wanted if p in installed and p not in explicit]
        if mark:
            plan.add("packages", "~", _("keep as wanted (now only a dependency): %s") % " ".join(mark), 21,
                     lambda m=mark: run([tool("lux-engine"), "-D", "--asexplicit"] + m), data=mark)
        if "packages" in cfg:
            dropped = [p for p in applied.get("packages", []) if p not in wanted and p in explicit]
            unlisted = sorted(p for p in explicit if p not in wanted and p not in extra and p not in dropped)
            remove = list(dropped) + (unlisted if cfg.get("remove_unlisted") else [])
            kernels = {p for p in explicit if KERNEL_RE.match(p)}
            keep = [p for p in remove if p in PROTECTED_PACKAGES or p in kernels]
            remove = [p for p in remove if p not in keep]
            if keep:
                plan.notes.append(_("Kept, LuxOS needs them: %s") % " ".join(keep))
            if remove:
                plan.add("packages", "-", _("remove: %s") % " ".join(remove), 90,
                         lambda m=remove: run([tool("lux"), "-y", "remove"] + m, stream=True, env=env_lux()), data=remove)
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
    if "kernel" in cfg:
        compute_kernel(cfg["kernel"]["params"], applied.get("kernel_params", []), st, plan)

    # --- firemni sit (domena, luxos-domain) ---
    if cfg.get("domain"):
        compute_domain(cfg["domain"], plan)
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
    path = "/etc/locale.gen"
    text = read(path, None)
    charset = "UTF-8" if loc.endswith(".UTF-8") else "ISO-8859-1"
    if text is not None:
        pat = re.compile(r"^#\s*(" + re.escape(loc) + r"\s.*)$", re.M)
        if not re.search(r"^" + re.escape(loc) + r"\s", text, re.M):
            new = pat.sub(r"\1", text, count=1) if pat.search(text) else text.rstrip("\n") + f"\n{loc} {charset}\n"
            atomic_write(path, new)
            # locale-gen zapisuje do /usr/lib/locale - pri ochrane systemu jen pres luxos-care
            if have("luxos-care"):
                run([tool("luxos-care"), "protect", "exec", "--", tool("locale-gen")])
            else:
                run([tool("locale-gen")])
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


def record(cfg, path):
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
    if "kernel" in cfg:
        data["kernel_params"] = local(("kernel", "params"), cfg["kernel"]["params"])
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


def generate(st):
    """Text /etc/luxos/system.lsl podle soucasneho systemu (bez hesel)."""
    today = datetime.date.today().isoformat()
    L = []
    w = L.append
    w("# " + _("LuxOS - configuration of the whole system in one file (LSL)"))
    w("# " + _("Generated by 'lux system show' on %s from this computer.") % today)
    w("# " + _("Check: lux system check   ·   What would change: lux system diff"))
    w("# " + _("Apply: sudo lux system apply (a snapshot is taken first, undo with: lux rollback)"))
    w("# " + _("A setting you delete is no longer managed (it stays as it is). Help: man luxos-system"))
    w("load config")
    w("")
    w("config = {")
    w("    # " + _("Computer name in the network"))
    w(f"    \"hostname\": {lsl_str(st.hostname() or 'luxos')}")
    tz = st.timezone()
    if tz:
        w("    # " + _("Time zone (list: timedatectl list-timezones)"))
        w(f"    \"timezone\": {lsl_str(tz)}")
    loc = st.locale()
    if loc:
        w("    # " + _("Language and formats (e.g. \"cs_CZ.UTF-8\", \"en_US.UTF-8\")"))
        w(f"    \"locale\": {lsl_str(loc)}")
    kb = st.keyboard()
    if kb["layouts"]:
        w("    # " + _("Keyboard layouts (the first is the default, at most 4) and how to switch them"))
        w("    \"keyboard\": {")
        w(f"        \"layouts\": {lsl_list(kb['layouts'], 8)}")
        w(f"        \"options\": {lsl_list(kb['options'], 8)}")
        w("    }")
    w("")
    w("    # " + _("Packages from the LuxOS and Arch Linux repositories (lux search NAME)"))
    w("    # " + _("Deleting a line removes the package at the next apply."))
    w(f"    \"packages\": {lsl_list(sorted(st.explicit()), 4)}")
    fps = st.flatpaks()
    if fps is not None:
        w("    # " + _("Apps from Flathub (app ID, e.g. \"org.mozilla.firefox\")"))
        w(f"    \"flatpaks\": {lsl_list(sorted(fps), 4)}")
    w("    # " + _("True = also remove packages and apps that are not listed here (careful)"))
    w("    \"remove_unlisted\": False")
    w("")
    units = st.units()
    skip = set(GUARD_UNITS.values()) | {FIREWALL_UNIT}
    on = sorted(u for u, (state, preset) in units.items()
                if state == "enabled" and preset != "enabled" and "@." not in u and u not in skip
                and u.rsplit(".", 1)[-1] in ("service", "socket", "timer", "path"))
    w("    # " + _("Services started at boot (a removed line turns the service off at the next apply)"))
    w("    \"services\": {")
    w(f"        \"enable\": {lsl_list(on, 8)}")
    w(f"        \"disable\": []")
    w("    }")
    w("")
    normal = st.normal_users()
    gmin, gmax = st.login_defs()[2:]
    own = sorted(g for g, v in st.group().items() if gmin <= v["gid"] < gmax and g not in normal)
    w("    # " + _("Extra groups"))
    w(f"    \"groups\": {lsl_list(own, 4)}")
    w("    # " + _("Users (passwords never go here; \"wheel\" = administrator)."))
    w("    # " + _("Optional \"password_hash\": output of 'openssl passwd -6'. Users are never deleted."))
    w("    \"users\": {")
    for name in sorted(normal):
        u = normal[name]
        w(f"        {lsl_str(name)}: {{")
        w(f"            \"description\": {lsl_str(u['description'])}")
        w(f"            \"groups\": {lsl_list(st.user_groups(name), 12)}")
        w(f"            \"shell\": {lsl_str(u['shell'])}")
        w("        }")
    w("    }")
    w("")
    care = st.care()
    w("    # " + _("LuxOS Care: \"carefree\" = automatic updates, \"classic\" = only notify"))
    w("    \"care\": {")
    w(f"        \"mode\": {lsl_str(care['mode'])}")
    w(f"        \"snapshots\": {lsl_bool(care['snapshots'])}")
    w(f"        \"keep_snapshots\": {care['keep_snapshots']}")
    w("    }")
    if any(u in units for u in GUARD_UNITS.values()):
        w("    # " + _("Lux Guard: protection against harmful downloads, hourly snapshots of /home"))
        w("    \"guard\": {")
        w(f"        \"enable\": {lsl_bool(st.enabled(GUARD_UNITS['enable']))}")
        w(f"        \"home_snapshots\": {lsl_bool(st.enabled(GUARD_UNITS['home_snapshots']))}")
        w("    }")
    fw = st.firewall()
    w("    # " + _("Firewall (ufw): allowed incoming ports, e.g. [\"22/tcp\"]"))
    w("    \"firewall\": {")
    w(f"        \"enable\": {lsl_bool(fw['enable'] and fw['installed'])}")
    w(f"        \"allow\": {lsl_list(fw['allow'], 8)}")
    w("    }")
    lay = st.boot()
    if lay is not None and lay["kind"] == "unreadable":
        w("    # " + _("Kernel parameters: run 'sudo lux system show' to include them"))
    elif lay is not None:
        params = [p for p in lay["params"] if not BOOT_PARAM_RE.match(p)]
        w("    # " + _("Kernel parameters (disk and encryption parameters are not managed here)"))
        w("    \"kernel\": {")
        w(f"        \"params\": {lsl_list(params, 8)}")
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


def cmd_init(args):
    need_root()
    path = P(CONFIG)
    if os.path.exists(path) and not args.force:
        raise UserError(_("%s already exists. Show the differences with: lux system diff (or init --force "
                          "to overwrite it).") % CONFIG)
    st = State()
    text = generate(st)
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
        say(_("The previous file was kept as %s") % (CONFIG + ".bak"))
    atomic_write(CONFIG, text, 0o644)
    # bez zasad organizace: soubor popisuje tento pocitac, zamky se overi az pri diff/apply
    cfg = load(path, policies=False)
    record(cfg, path)
    ok(_("Written %s from this computer.") % CONFIG)
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
    plan = compute(cfg, State())
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


def cmd_apply(args):
    need_root()
    st = State()
    if st.booted_snapshot():
        raise UserError(_("LuxOS is running from a snapshot, changes would be lost after a restart. "
                          "To keep this version, run: lux rollback"))
    cfg = load(args.file)   # zasady organizace plati vzdy (--no-policies jen pro check/diff)
    with apply_lock():
        plan = compute(cfg, st)
        print_plan(plan)
        if not plan.changes:
            record(cfg, args.file)
            return 0
        if not args.yes:
            if not sys.stdin.isatty():
                raise UserError(_("Nothing was changed. Confirm with -y when running without a terminal."))
            if not ask(_("Apply these changes?"), default_yes=not plan.removals()):
                raise UserError(_("Cancelled. Nothing was changed."))
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
        record(cfg, args.file)
    ok(_("Done: %d changes.") % done)
    if snap:
        print(D + _("Snapshot before the change: %s (undo: lux rollback %s)") % (snap, snap) + R)
    if plan.restart:
        print(_("Restart the computer to use the new kernel parameters."))
    return 0


class Args:
    def __init__(self, argv):
        self.yes = self.json = self.no_snapshot = self.force = self.origin = self.no_policies = False
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
            elif a.startswith("-") and a != "-":
                raise UserError(_("Unknown option %s") % a)
            elif self.cmd is None:
                self.cmd = a
            elif self.file is None:
                self.file = a
            else:
                raise UserError(_("Too many arguments"))
        self.file = self.file or P(CONFIG)


USAGE = """lux system show [--origin] | init [--force] | check [FILE] | diff [FILE] [--json] | apply [FILE] [-y] [--no-snapshot] | locks [--json]"""


def main(argv):
    try:
        args = Args(argv[1:])
        handlers = {"show": cmd_show, "init": cmd_init, "check": cmd_check, "diff": cmd_diff, "apply": cmd_apply,
                    "plan": cmd_plan, "locks": cmd_locks}
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
