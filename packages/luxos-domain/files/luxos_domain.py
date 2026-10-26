"""luxos_domain - LuxOS v organizacni siti: domena Microsoft Active Directory nebo Samba AD (vrstva 1).

Logika bez GTK pro "lux domain" (lux-domain), pomocnika pro Nastaveni, instalator, OEM pruvodce a
prihlasovaci obrazovku. Pripojeni dela adcli (ucet pocitace + keytab), prihlaseni SSSD (NSS, PAM,
Kerberos, offline cache), konfiguraci zapisujeme sami (zadny shell, pevne prikazy):

  /etc/sssd/sssd.conf          z /usr/share/luxos/domain/sssd.conf.tmpl (0600)
  /etc/krb5.conf               Kerberos s KCM (ticket SSSD, obnova)
  /etc/pam.d/system-auth       LuxOS sablona s pam_sss a pam_mkhomedir (puvodni soubor v zaloze)
  /etc/nsswitch.conf           "sss" v passwd, group, shadow
  /etc/sudoers.d/50-luxos-domain, /etc/polkit-1/rules.d/49-luxos-domain-admins.rules  spravci z domeny
  /etc/lightdm/lightdm.conf.d/70-luxos-domain.conf      "Jiny uzivatel..." na prihlasovaci obrazovce
  /var/lib/luxos/domain/state.json   stav (bez tajemstvi, 0644), zalohy puvodnich souboru v backup/
  /run/luxos/domain/status.json      online/offline (pro greeter, zapisuje "lux domain refresh")

Heslo spravce domeny se nikdy neuklada: jde jen na stdin adcli (join, odebrani uctu pocitace).
Odpojeni (leave) vrati soubory ze zaloh a odebere spravu (spravci, zasady, cache SSSD); domovske
slozky a osobni data uzivatelu zustanou (rozhodnuti R8).

Rozhodnuti R4: domenovi uzivatele maji kratka jmena (jan); kdyz na pocitaci existuje mistni ucet se
stejnym jmenem, dostane domenovy ucet plne jmeno jan@firma.local (sss_override).
Rozhodnuti R5: offline prihlaseni 30 dni (offline_credentials_expiration), prava spravce z domeny jen
7 dni bez spojeni s radicem (refresh pak docasne vypne pravidla sudo/polkit, po spojeni je vrati).

Testy: LUXOS_DOMAIN_ROOT = jiny koren pro vsechny soubory, LUXOS_DOMAIN_BIN = adresar se zastupnymi
nastroji (realm, adcli, sssctl, systemctl, ...), LUXOS_DOMAIN_NOW = cas (epoch) misto hodin.
"""
import contextlib
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.environ.get("LUXOS_DOMAIN_ROOT", "").rstrip("/")


def P(path):
    """Cesta v (pripadne testovacim) koreni."""
    return ROOT + path


STATE_DIR = "/var/lib/luxos/domain"
STATE = STATE_DIR + "/state.json"
LEFT = STATE_DIR + "/left.json"
BACKUP_DIR = STATE_DIR + "/backup"
RUN_DIR = "/run/luxos/domain"
RUN_STATUS = RUN_DIR + "/status.json"
SHARE_DIR = "/usr/share/luxos/domain"
SSSD_CONF = "/etc/sssd/sssd.conf"
KRB5_CONF = "/etc/krb5.conf"
KEYTAB = "/etc/krb5.keytab"
PAM_AUTH = "/etc/pam.d/system-auth"
NSSWITCH = "/etc/nsswitch.conf"
SUDOERS = "/etc/sudoers.d/50-luxos-domain"
POLKIT_RULES = "/etc/polkit-1/rules.d/49-luxos-domain-admins.rules"
LIGHTDM_CONF = "/etc/lightdm/lightdm.conf.d/70-luxos-domain.conf"
SMB_CONF = "/etc/samba/smb.conf"
FIREFOX_POLICIES = "/etc/firefox/policies/policies.json"
TIMESYNC_CONF = "/etc/systemd/timesyncd.conf.d/50-luxos-domain.conf"
GPO_FRAGMENT = "/etc/luxos/system.d/40-domain-gpo.lsl"
SSS_DB_DIRS = ("/var/lib/sss/db", "/var/lib/sss/mc")
MARK = "luxos-domain"                     # znacka v hlavicce souboru, ktere spravujeme
# Soubory, jejichz puvodni obsah se pred pripojenim zalohuje a pri odpojeni vrati
BACKED_UP = (PAM_AUTH, NSSWITCH, KRB5_CONF, SSSD_CONF, SMB_CONF, FIREFOX_POLICIES)
NSS_DBS = ("passwd", "group", "shadow")
UNITS = ("sssd.service", "sssd-kcm.socket")
TIMER = "luxos-domain-refresh.timer"

DEFAULT_ADMINS = ["Domain Admins"]
OPTIONAL_ADMINS = ["LuxOS Admins"]       # pridava se samo, pokud skupina v domene existuje
DEFAULT_OFFLINE_DAYS = 30                 # R5
DEFAULT_ADMIN_OFFLINE_DAYS = 7            # R5
MAX_CLOCK_SKEW = 300                      # Kerberos: max. 5 min
DOMAIN_UID_MIN = 100000                   # ID z SID (ldap_id_mapping) jsou vzdy vetsi

TOOLS = {
    "realm": "/usr/bin/realm", "adcli": "/usr/bin/adcli", "sssctl": "/usr/bin/sssctl",
    "sss_override": "/usr/bin/sss_override", "sss_cache": "/usr/bin/sss_cache", "systemctl": "/usr/bin/systemctl",
    "kinit": "/usr/bin/kinit", "klist": "/usr/bin/klist", "ldapsearch": "/usr/bin/ldapsearch",
    "visudo": "/usr/bin/visudo", "luxos-care": "/usr/bin/luxos-care", "logger": "/usr/bin/logger",
    "getent": "/usr/bin/getent", "timedatectl": "/usr/bin/timedatectl", "lpadmin": "/usr/bin/lpadmin",
}

DOMAIN_RE = re.compile(r"^(?=.{3,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9._$-][A-Za-z0-9._$ -]{0,63}(@[A-Za-z0-9.-]{1,253})?$")
COMPUTER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,14}$")
OU_RE = re.compile(r"^[A-Za-z]{1,10}=[^,=\x00-\x1f\"\\]{1,64}(,[A-Za-z]{1,10}=[^,=\x00-\x1f\"\\]{1,64}){0,15}$")
GROUP_RE = re.compile(r"^(?! )[^\x00-\x1f\x7f\"\\:,/=+<>#;]{1,64}(?<! )$")
PRINTER_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SHARE_RE = re.compile(r"^smb://[A-Za-z0-9.-]{1,253}(/[^\s\x00-\x1f\"\\]{1,200})?/?$")
LOCAL_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

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


class DomainError(Exception):
    """Chyba pro uzivatele: code (password, rights, dns, not-found, clock, exists, network, already-joined,
    not-joined, invalid, failed) a prelozeny text."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def error_text(code, detail=""):
    """Lidsky text k chybe (detail = konec vystupu nastroje, jen pro "failed")."""
    texts = {
        "password": _("The administrator name or password is not correct."),
        "rights": _("This account may not add computers to the domain. Ask your IT administrator."),
        "dns": _("The domain was not found in DNS. Check that the computer uses the DNS server of the "
                 "organization (usually from DHCP) or enter the address of a domain controller."),
        "not-found": _("No domain controller answered for this domain. Check the name and the network."),
        "clock": _("The clock of this computer differs from the domain by more than 5 minutes. "
                   "Set the clock from the domain and try again."),
        "exists": _("A computer with this name is already in the domain. Choose another name or ask your IT "
                    "administrator to remove the old account."),
        "network": _("The domain controller cannot be reached. Check the network connection."),
        "already-joined": _("This computer is already in an organization network. Leave it first."),
        "not-joined": _("This computer is not in an organization network."),
        "unsupported": _("This is not an Active Directory domain (Microsoft or Samba)."),
    }
    if code in texts:
        return texts[code]
    return _("Joining failed: %s") % detail if detail else _("Joining failed.")


# ---- nastroje a soubory ---------------------------------------------------------------------
def tool(name):
    d = os.environ.get("LUXOS_DOMAIN_BIN")
    if d:
        return os.path.join(d, name)
    return TOOLS[name]


def have(name):
    return os.access(tool(name), os.X_OK)


def capture(argv, input=None, timeout=60, env=None):
    """(navratovy kod, stdout, stderr); nikdy nevyhazuje. Vystup v anglictine (rozpoznani chyb)."""
    e = dict(os.environ, LC_ALL="C", LANG="C")
    e.update(env or {})
    try:
        r = subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout, env=e)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as ex:
        return 127, "", str(ex)
    return r.returncode, r.stdout or "", r.stderr or ""


def now():
    t = os.environ.get("LUXOS_DOMAIN_NOW")
    return float(t) if t else time.time()


def iso(t):
    return datetime.datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")


def parse_iso(s):
    try:
        return datetime.datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None


def read(path, default=""):
    try:
        with open(P(path), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def atomic_write(path, text, mode=0o644):
    path = P(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-luxos-domain-")
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


def remove(path):
    with contextlib.suppress(FileNotFoundError):
        os.unlink(P(path))


def template(name):
    d = os.environ.get("LUXOS_DOMAIN_TEMPLATES") or SHARE_DIR
    with open(os.path.join(d, name), encoding="utf-8") as f:
        return f.read()


# ---- stav ---------------------------------------------------------------------------------------
def load_state(path=STATE):
    try:
        with open(P(path), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state):
    atomic_write(STATE, json.dumps(state, indent=1, ensure_ascii=False) + "\n", 0o644)


def joined():
    return bool(load_state().get("joined"))


def audit(msg):
    """Zaznam do zurnalu (journalctl -t luxos-domain)."""
    if have("logger"):
        capture([tool("logger"), "-t", "luxos-domain", "--", msg], timeout=10)


# ---- kontrola vstupu --------------------------------------------------------------------------
def check_domain(domain):
    d = (domain or "").strip().lower().rstrip(".")
    if not DOMAIN_RE.match(d):
        raise DomainError("invalid", _("\"%s\" is not a valid domain name (e.g. firma.local).") % domain)
    return d


def check_login(user):
    u = (user or "").strip()
    if "\\" in u:                         # FIRMA\admin -> admin
        u = u.split("\\", 1)[1]
    if not LOGIN_RE.match(u):
        raise DomainError("invalid", _("\"%s\" is not a valid user name.") % user)
    return u


def check_group(group):
    g = (group or "").strip()
    if not GROUP_RE.match(g):
        raise DomainError("invalid", _("\"%s\" is not a valid group name.") % group)
    return g


def check_ou(ou):
    o = (ou or "").strip()
    if o and not OU_RE.match(o):
        raise DomainError("invalid", _("\"%s\" is not a valid organizational unit (e.g. OU=Computers,DC=firma,"
                                       "DC=local).") % ou)
    return o


def check_computer(name):
    n = (name or "").strip()
    if n and not COMPUTER_RE.match(n):
        raise DomainError("invalid", _("The computer name for the domain may have at most 15 letters, digits "
                                       "and hyphens."))
    return n


def parse_groups(text):
    return [check_group(g) for g in (text or "").split(",") if g.strip()]


# ---- zjisteni domeny --------------------------------------------------------------------------
def classify(text, default="failed"):
    """Vystup adcli/realm/kinit -> kod chyby."""
    t = (text or "").lower()
    if any(s in t for s in ("preauthentication failed", "password incorrect", "couldn't authenticate",
                            "invalid credentials", "client not found in kerberos database",
                            "cannot read password", "password has expired")):
        return "password"
    if any(s in t for s in ("insufficient access", "insuff_access", "insufficient permissions",
                            "not have permission", "access denied", "constraint violation")):
        return "rights"
    if "clock skew" in t:
        return "clock"
    if any(s in t for s in ("already exists", "entry already exists")):
        return "exists"
    if any(s in t for s in ("couldn't lookup", "couldn't resolve", "cannot find kdc", "no such domain",
                            "name or service not known", "dns", "cannot resolve")):
        return "dns"
    if any(s in t for s in ("no logon servers", "couldn't discover", "no domain controllers",
                            "not a domain", "cannot contact")):
        return "not-found"
    if any(s in t for s in ("network is unreachable", "couldn't connect", "connection refused", "timed out",
                            "timeout", "no route to host")):
        return "network"
    return default


def parse_info(text):
    """Vystup "adcli info DOMENA" (ini klic = hodnota) -> slovnik."""
    out = {}
    for line in (text or "").splitlines():
        k, sep, v = line.partition("=")
        if sep and not line.startswith("["):
            out[k.strip()] = v.strip()
    return out


def dc_time(dc):
    """Cas radice domeny z LDAP rootDSE (currentTime, bez prihlaseni) -> epoch | None."""
    if not dc or not have("ldapsearch"):
        return None
    rc, out, _e = capture([tool("ldapsearch"), "-x", "-LLL", "-o", "nettimeout=5", "-H", "ldap://" + dc,
                           "-s", "base", "-b", "", "currentTime"], timeout=15)
    m = re.search(r"^currentTime:\s*(\d{14})", out, re.M)
    if rc != 0 or not m:
        return None
    t = datetime.datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
    return t.timestamp()


def discover(domain):
    """Najde domenu: radice, kratke jmeno, posun hodin. Chyba -> DomainError."""
    domain = check_domain(domain)
    if not have("adcli"):
        raise DomainError("failed", _("The domain tools are missing (lux install luxos-domain)."))
    rc, out, err = capture([tool("adcli"), "info", domain], timeout=45)
    if rc != 0:
        code = classify(err + out, "not-found")
        if code == "not-found" and have("realm"):
            # realmd rozpozna i jine druhy (FreeIPA, MIT Kerberos) - pak jasna hlaska
            rrc, rout, _re = capture([tool("realm"), "discover", domain], timeout=45)
            if rrc == 0 and "active-directory" not in rout:
                code = "unsupported"
        raise DomainError(code, error_text(code))
    info = parse_info(out)
    dcs = (info.get("domain-controllers") or info.get("domain-controller") or "").split()
    dc = info.get("domain-controller") or (dcs[0] if dcs else "")
    t = dc_time(dc)
    return {"ok": True, "domain": info.get("domain-name", domain).lower(), "realm": domain.upper(),
            "short": info.get("domain-short", domain.split(".")[0].upper()), "type": "active-directory",
            "controllers": dcs or ([dc] if dc else []), "controller": dc,
            "site": info.get("domain-controller-site", ""),
            "clock_skew": None if t is None else int(round(t - now()))}


# ---- konfiguracni soubory -------------------------------------------------------------------------
def render_sssd(state):
    groups = state.get("allow_groups") or []
    offline = int(state.get("offline_days", DEFAULT_OFFLINE_DAYS))
    if groups:
        access = "simple\nsimple_allow_groups = " + ", ".join(g.lower() for g in groups)
    else:
        access = "ad"
    return template("sssd.conf.tmpl").format(
        domain=state["domain"], realm=state["realm"], access=access,
        cache="True" if offline > 0 else "False", offline_days=max(offline, 1),
        gpo_access=state.get("gpo_access", "enforcing"))


def render_krb5(state):
    return template("krb5.conf.tmpl").format(domain=state["domain"], realm=state["realm"])


def render_pam():
    return template("system-auth")


def render_smb(state):
    return template("smb.conf.tmpl").format(short=state.get("short", "WORKGROUP"), realm=state["realm"])


def nss_add(text):
    """Pridat "sss" do radku passwd/group/shadow -> (novy text, seznam zmenenych databazi)."""
    changed = []

    def fix(m):
        db, space, rest = m.group(1), m.group(2), m.group(3)
        if "sss" in rest.split():
            return m.group(0)
        changed.append(db)
        return f"{db}:{space}{rest.rstrip()} sss"
    out = re.sub(r"^(" + "|".join(NSS_DBS) + r"):(\s*)(.*)$", fix, text, flags=re.M)
    return out, changed


def nss_remove(text, dbs):
    """Odebrat "sss" jen z radku, kam ho pridal join."""
    def fix(m):
        if m.group(1) not in dbs:
            return m.group(0)
        words = [w for w in m.group(3).split() if w != "sss"]
        return f"{m.group(1)}:{m.group(2)}{' '.join(words)}"
    return re.sub(r"^(" + "|".join(NSS_DBS) + r"):(\s*)(.*)$", fix, text, flags=re.M)


def sudo_name(group):
    return '%"' + group.lower() + '"'


def render_sudoers(groups, active):
    lines = ["# LuxOS - spravci tohoto pocitace ze skupin domeny (" + MARK + ", lux domain admins).",
             "# Generovano, rucni zmeny se prepisou."]
    if not active:
        lines.append("# Prava jsou docasne vypnuta: pocitac je dele bez spojeni s domenou, nez dovoluje")
        lines.append("# admin_offline_days (lux domain status). Po spojeni se vrati samy.")
    for g in groups:
        lines.append(("" if active else "# ") + f"{sudo_name(g)} ALL=(ALL:ALL) ALL")
    return "\n".join(lines) + "\n"


def render_polkit(groups, active):
    gl = json.dumps([g.lower() for g in groups] if active else [], ensure_ascii=False)
    return template("49-luxos-domain-admins.rules.tmpl").replace("@GROUPS@", gl)


def write_admin_rules(state, active, chroot=False):
    """sudoers.d + polkit pro domenove skupiny spravcu (active=False: pravidla bez skupin)."""
    groups = state.get("admin_groups") or []
    text = render_sudoers(groups, active)
    if have("visudo") and groups:
        # kontrola syntaxe pred zapisem (chybny sudoers by vypnul sudo pro vsechny)
        fd, tmp = tempfile.mkstemp(prefix="luxos-domain-sudoers-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        rc, out, err = capture([tool("visudo"), "-cf", tmp], timeout=20)
        os.unlink(tmp)
        if rc != 0:
            raise DomainError("invalid", _("The sudo rule for the administrator groups is not valid: %s")
                              % (err or out).strip()[-300:])
    atomic_write(SUDOERS, text, 0o440)
    atomic_write(POLKIT_RULES, render_polkit(groups, active), 0o644)


def backup_files(state):
    """Puvodni soubory do zalohy (jen jednou - opakovany join nesmi prepsat originaly)."""
    os.makedirs(P(BACKUP_DIR), mode=0o700, exist_ok=True)
    existed = {}
    for path in BACKED_UP:
        dest = P(BACKUP_DIR) + "/" + path.strip("/").replace("/", "__")
        src = P(path)
        if os.path.exists(src):
            if not os.path.exists(dest):
                shutil.copy2(src, dest)
            existed[path] = True
        else:
            existed[path] = False
    state["backup"] = existed


def restore_file(path, state, ours_marker=True):
    """Vrati soubor ze zalohy; soubor, ktery pred pripojenim nebyl, smaze (jen kdyz je nas)."""
    dest = P(BACKUP_DIR) + "/" + path.strip("/").replace("/", "__")
    existed = (state.get("backup") or {}).get(path)
    cur = read(path, None)
    if ours_marker and cur is not None and MARK not in cur and path not in (NSSWITCH, FIREFOX_POLICIES):
        return False                       # spravce soubor mezitim zmenil - nechat
    if existed and os.path.exists(dest):
        shutil.copy2(dest, P(path))
        return True
    if existed is False:
        remove(path)
        return True
    return False


def firefox_spnego(domain, add):
    """Firefox: Kerberos (SPNEGO) pro weby organizace - klic Authentication v policies.json."""
    text = read(FIREFOX_POLICIES, None)
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return                             # cizi neplatny soubor neprepisovat
    if not isinstance(data, dict):
        return
    pol = data.setdefault("policies", {})
    if add:
        pol["Authentication"] = {"SPNEGO": [domain], "Delegated": [], "AllowNonFQDN": {"SPNEGO": False},
                                 "Locked": False}
        data.setdefault("_comment", "SPNEGO: " + MARK)
    else:
        pol.pop("Authentication", None)
        if data.get("_comment") == "SPNEGO: " + MARK:
            data.pop("_comment")
        if not pol:
            data.pop("policies")
        if not data:
            remove(FIREFOX_POLICIES)
            return
    atomic_write(FIREFOX_POLICIES, json.dumps(data, indent=2, ensure_ascii=False) + "\n", 0o644)


# ---- prubeh (CLI, GUI, instalator) ------------------------------------------------------------------
class Progress:
    """Kroky prubehu: CLI vypisuje lidsky text, --progress radky @@STEP n celkem text (jako luxos-oem)."""

    def __init__(self, machine=False, out=None):
        self.machine = machine
        self.out = out or sys.stdout

    def step(self, n, total, text):
        if self.machine:
            print(f"@@STEP {n} {total} {text}", file=self.out, flush=True)
        else:
            print(f"✦ {text}", file=self.out, flush=True)

    def warn(self, text):
        print(("" if self.machine else "! ") + text, file=self.out if self.machine else sys.stderr, flush=True)

    def log(self, text):
        if self.machine:
            print(text, file=self.out, flush=True)


def systemctl(*args):
    return capture([tool("systemctl")] + list(args), timeout=120)


def take_snapshot(prog):
    if not have("luxos-care"):
        return ""
    rc, out, err = capture([tool("luxos-care"), "snapshot", "--kind", "system"], timeout=900)
    if rc != 0:
        prog.warn(_("The system snapshot could not be taken: %s") % (err or out).strip()[-200:])
        return ""
    m = re.search(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", out)
    return m.group(0) if m else ""


def os_version():
    for line in read("/etc/os-release").splitlines():
        if line.startswith("VERSION_ID="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


# ---- pripojeni ------------------------------------------------------------------------------------
def join(domain, user, password, ou="", computer="", admins=None, snapshot=True, chroot=False, prog=None):
    """Pripoji pocitac k domene. Heslo jen na stdin adcli. Chyba -> DomainError (system vracen zpet)."""
    prog = prog or Progress()
    domain = check_domain(domain)
    user = check_login(user)
    ou = check_ou(ou)
    computer = check_computer(computer)
    admins = [check_group(g) for g in (admins if admins is not None else DEFAULT_ADMINS)]
    if not password or "\n" in password or "\0" in password:
        raise DomainError("password", _("Enter the password of the domain administrator."))
    if joined():
        raise DomainError("already-joined", error_text("already-joined"))
    total = 7
    prog.step(1, total, _("Looking for the domain controllers…"))
    info = discover(domain)
    if info["clock_skew"] is not None and abs(info["clock_skew"]) > MAX_CLOCK_SKEW:
        raise DomainError("clock", error_text("clock"))
    snap = ""
    if snapshot and not chroot:
        prog.step(2, total, _("Taking a system snapshot…"))
        snap = take_snapshot(prog)
    state = {"version": 1, "joined": False, "domain": info["domain"], "realm": info["realm"],
             "short": info["short"], "controllers": info["controllers"], "computer": computer, "ou": ou,
             "joined_by": user, "admin_groups": admins, "auto_admins_checked": False, "allow_groups": [],
             "offline_days": DEFAULT_OFFLINE_DAYS, "admin_offline_days": DEFAULT_ADMIN_OFFLINE_DAYS,
             "admins_active": True, "gpo_access": "enforcing", "clashes": [], "shares": [], "printers": [],
             "snapshot": snap}
    prog.step(3, total, _("Saving the current settings…"))
    os.makedirs(P(STATE_DIR), mode=0o755, exist_ok=True)
    backup_files(state)
    had_keytab = os.path.exists(P(KEYTAB))
    try:
        prog.step(4, total, _("Creating the computer account in the domain…"))
        atomic_write(KRB5_CONF, render_krb5(state), 0o644)
        argv = [tool("adcli"), "join", f"--domain={state['domain']}", f"--login-user={user}", "--stdin-password",
                f"--host-keytab={P(KEYTAB)}", "--os-name=LuxOS", "--show-details"]
        if os_version():
            argv.append(f"--os-version={os_version()}")
        if ou:
            argv.append(f"--domain-ou={ou}")
        if computer:
            argv.append(f"--computer-name={computer}")
        rc, out, err = capture(argv, input=password + "\n", timeout=180)
        password = None                     # dal uz neni potreba
        if rc != 0:
            code = classify(err + out)
            raise DomainError(code, error_text(code, (err or out).strip().splitlines()[-1:][0]
                                               if (err or out).strip() else ""))
        details = parse_info(out)
        state["computer"] = details.get("computer-name", computer) or computer
        state["short"] = details.get("domain-short", state["short"]) or state["short"]
        prog.step(5, total, _("Setting up sign-in with domain accounts…"))
        configure_login(state)
        prog.step(6, total, _("Setting up administrators…"))
        write_admin_rules(state, True)
        prog.step(7, total, _("Starting the services…"))
        for unit in UNITS + (TIMER,):
            rc, out, err = systemctl("enable", unit) if chroot else systemctl("enable", "--now", unit)
            if rc != 0 and unit == "sssd.service":
                raise DomainError("failed", _("SSSD could not be started: %s") % (err or out).strip()[-300:])
        state["joined"] = True
        state["joined_at"] = iso(now())
        state["last_online"] = state["joined_at"]
        save_state(state)
    except BaseException:
        rollback_join(state, had_keytab, chroot)
        raise
    audit(f"joined domain {state['domain']} as {state['computer'] or 'computer'} (by {user})")
    if not chroot:
        with contextlib.suppress(DomainError):
            refresh(prog=None)
    return state


def configure_login(state):
    """sssd.conf, krb5.conf, PAM, NSS, LightDM, smb.conf a Firefox podle stavu."""
    atomic_write(SSSD_CONF, render_sssd(state), 0o600)
    atomic_write(KRB5_CONF, render_krb5(state), 0o644)
    atomic_write(PAM_AUTH, render_pam(), 0o644)
    text = read(NSSWITCH)
    new, changed = nss_add(text)
    if changed:
        atomic_write(NSSWITCH, new, 0o644)
    state["nss_added"] = sorted(set(state.get("nss_added", [])) | set(changed))
    atomic_write(LIGHTDM_CONF, f"# LuxOS - prihlaseni domenovym uctem ({MARK}): pole pro jmeno na prihlasovaci "
                               "obrazovce\n[Seat:*]\ngreeter-show-manual-login=true\n", 0o644)
    if (state.get("backup") or {}).get(SMB_CONF) is False:
        atomic_write(SMB_CONF, render_smb(state), 0o644)      # cizi smb.conf neprepisujeme
    firefox_spnego(state["domain"], True)


def rollback_join(state, had_keytab, chroot):
    """Nepovedene pripojeni: vratit soubory, vypnout sluzby, odstranit keytab z tohoto pokusu."""
    for unit in UNITS + (TIMER,):
        if chroot:
            systemctl("disable", unit)
        else:
            systemctl("disable", "--now", unit)
    for path in BACKED_UP:
        with contextlib.suppress(OSError):
            restore_file(path, state, ours_marker=False)
    for path in (SUDOERS, POLKIT_RULES, LIGHTDM_CONF):
        remove(path)
    if not had_keytab:
        remove(KEYTAB)
    shutil.rmtree(P(BACKUP_DIR), ignore_errors=True)


# ---- odpojeni -----------------------------------------------------------------------------------
def leave(user="", password="", prog=None, snapshot=True):
    """Odpoji pocitac: vrati soubory, odebere spravce, zasady a cache. Domovske slozky zustanou (R8).
    S user+password navic smaze ucet pocitace v domene. -> seznam varovani."""
    prog = prog or Progress()
    state = load_state()
    if not state.get("joined"):
        raise DomainError("not-joined", error_text("not-joined"))
    warnings = []
    total = 5
    if snapshot:
        prog.step(1, total, _("Taking a system snapshot…"))
        take_snapshot(prog)
    if user:
        user = check_login(user)
        prog.step(2, total, _("Removing the computer account from the domain…"))
        argv = [tool("adcli"), "delete-computer", f"--domain={state['domain']}", f"--login-user={user}",
                "--stdin-password"]
        if state.get("computer"):
            argv.append(state["computer"])
        rc, out, err = capture(argv, input=(password or "") + "\n", timeout=120)
        password = None
        if rc != 0:
            code = classify(err + out)
            w = _("The computer account stays in the domain (%s); your IT administrator can remove it.") \
                % error_text(code, (err or out).strip()[-200:])
            warnings.append(w)
            prog.warn(w)
    prog.step(3, total, _("Stopping the services…"))
    for unit in (TIMER,) + UNITS:
        systemctl("disable", "--now", unit)
    prog.step(4, total, _("Restoring the original settings…"))
    for path in (PAM_AUTH, KRB5_CONF, SSSD_CONF, SMB_CONF):
        if not restore_file(path, state) and path == PAM_AUTH and MARK in read(PAM_AUTH):
            warnings.append(_("%s could not be restored; check it.") % PAM_AUTH)
    text = read(NSSWITCH, None)
    if text is not None:
        atomic_write(NSSWITCH, nss_remove(text, state.get("nss_added", list(NSS_DBS))), 0o644)
    firefox_spnego(state["domain"], False)
    for path in (SUDOERS, POLKIT_RULES, LIGHTDM_CONF, TIMESYNC_CONF, GPO_FRAGMENT, KEYTAB):
        remove(path)
    for p in state.get("printers", []):
        if have("lpadmin"):
            capture([tool("lpadmin"), "-x", p["name"]], timeout=30)
    prog.step(5, total, _("Removing the domain sign-in data…"))
    # cache SSSD (i ulozene otisky hesel) - sprava organizace, ne osobni data
    for d in SSS_DB_DIRS:
        with contextlib.suppress(OSError):
            for n in os.listdir(P(d)):
                with contextlib.suppress(OSError):
                    os.unlink(os.path.join(P(d), n))
    homes = domain_homes()
    left = dict(state, joined=False, left_at=iso(now()), homes_kept=homes)
    atomic_write(LEFT, json.dumps(left, indent=1, ensure_ascii=False) + "\n", 0o644)
    remove(STATE)
    remove(RUN_STATUS)
    shutil.rmtree(P(BACKUP_DIR), ignore_errors=True)
    audit(f"left domain {state['domain']}")
    return warnings, homes


def domain_homes():
    """Domovske slozky domenovych uzivatelu (vlastnik s UID z domeny) - zustavaji."""
    out = []
    with contextlib.suppress(OSError):
        for n in sorted(os.listdir(P("/home"))):
            with contextlib.suppress(OSError):
                if os.stat(P("/home/" + n)).st_uid >= DOMAIN_UID_MIN:
                    out.append("/home/" + n)
    return out


# ---- spravci, prihlaseni, nastaveni -----------------------------------------------------------------
def require_joined():
    state = load_state()
    if not state.get("joined"):
        raise DomainError("not-joined", error_text("not-joined"))
    return state


def apply_settings(state, restart=True):
    """Po zmene stavu: sssd.conf + pravidla spravcu, restart SSSD."""
    atomic_write(SSSD_CONF, render_sssd(state), 0o600)
    write_admin_rules(state, state.get("admins_active", True))
    save_state(state)
    if restart:
        systemctl("try-restart", "sssd.service")


def admins_change(group, add):
    state = require_joined()
    g = check_group(group)
    cur = state.get("admin_groups") or []
    rest = [x for x in cur if x.casefold() != g.casefold()]
    state["admin_groups"] = rest + [g] if add else rest
    apply_settings(state, restart=False)
    audit(f"admin group {'added' if add else 'removed'}: {g}")
    return state["admin_groups"]


def login_change(group, allow):
    state = require_joined()
    g = check_group(group)
    rest = [x for x in state.get("allow_groups") or [] if x.casefold() != g.casefold()]
    state["allow_groups"] = rest + [g] if allow else rest
    apply_settings(state)
    audit(f"login {'allowed' if allow else 'no longer limited'}: {g}")
    return state["allow_groups"]


def set_option(name, value):
    state = require_joined()
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise DomainError("invalid", _("Enter a number of days.")) from None
    if not 0 <= v <= 180:
        raise DomainError("invalid", _("The number of days must be between 0 and 180."))
    key = {"offline-days": "offline_days", "admin-offline-days": "admin_offline_days"}.get(name)
    if key is None:
        raise DomainError("invalid", _("Unknown setting %s") % name)
    state[key] = v
    if state.get("admin_offline_days", 0) > state.get("offline_days", DEFAULT_OFFLINE_DAYS):
        raise DomainError("invalid", _("Administrator rights cannot last longer offline than the sign-in."))
    state["admins_active"] = admins_should_be_active(state, now())
    apply_settings(state)
    return v


def shares_change(url, name, add):
    state = require_joined()
    if add and not SHARE_RE.match(url or ""):
        raise DomainError("invalid", _("\"%s\" is not a shared folder address (smb://server/folder).") % url)
    rest = [s for s in state.get("shares") or [] if s["url"] != url]
    state["shares"] = rest + [{"url": url, "name": (name or "").strip()[:64] or url.rstrip("/").rsplit("/", 1)[-1]}] \
        if add else rest
    save_state(state)
    return state["shares"]


def printers_change(name, uri, add, model="drv:///sample.drv/generic.ppd"):
    """Tiskarna z tiskoveho serveru Windows: smb:// fronta s Kerberos (auth-info-required=negotiate)."""
    state = require_joined()
    if not PRINTER_RE.match(name or ""):
        raise DomainError("invalid", _("The printer name may contain only letters, digits, - and _."))
    rest = [p for p in state.get("printers") or [] if p["name"] != name]
    if add:
        if not SHARE_RE.match(uri or ""):
            raise DomainError("invalid", _("\"%s\" is not a printer address (smb://server/printer).") % uri)
        rc, out, err = capture([tool("lpadmin"), "-p", name, "-E", "-v", uri, "-m", model,
                                "-o", "auth-info-required=negotiate", "-o", "printer-is-shared=false"], timeout=60)
        if rc != 0:
            raise DomainError("failed", _("The printer could not be added: %s") % (err or out).strip()[-300:])
        rest.append({"name": name, "uri": uri})
    else:
        capture([tool("lpadmin"), "-x", name], timeout=60)
    state["printers"] = rest
    save_state(state)
    return rest


def sync_time():
    """Nastavi hodiny podle radice domeny (Kerberos snese max. 5 min) a NTP na radice."""
    state = load_state()
    dcs = state.get("controllers") or []
    if not dcs:
        raise DomainError("not-joined", error_text("not-joined"))
    return sync_time_from(dcs)


def sync_time_from(dcs):
    t = None
    for dc in dcs:
        t = dc_time(dc)
        if t is not None:
            break
    if t is None:
        raise DomainError("network", error_text("network"))
    stamp = datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    capture([tool("timedatectl"), "set-ntp", "false"], timeout=30)
    rc, out, err = capture([tool("timedatectl"), "set-time", stamp], timeout=30)
    atomic_write(TIMESYNC_CONF, f"# LuxOS - cas z radicu domeny ({MARK})\n[Time]\nNTP={' '.join(dcs)}\n", 0o644)
    capture([tool("timedatectl"), "set-ntp", "true"], timeout=30)
    if rc != 0:
        raise DomainError("failed", _("The clock could not be set: %s") % (err or out).strip()[-200:])
    return stamp


# ---- obnova stavu (casovac), offline, kolize jmen ---------------------------------------------------
def check_online(state):
    """Je radic domeny dostupny? True/False, None = nelze zjistit."""
    if have("sssctl"):
        rc, out, _e = capture([tool("sssctl"), "domain-status", state["domain"], "-o"], timeout=30)
        if rc == 0:
            if re.search(r"online status:\s*online", out, re.I):
                return True
            if re.search(r"online status:\s*offline", out, re.I):
                return False
    if have("adcli"):
        rc, _o, _e = capture([tool("adcli"), "testjoin", f"--domain={state['domain']}",
                              f"--host-keytab={P(KEYTAB)}"], timeout=30)
        return rc == 0
    return None


def admins_should_be_active(state, t):
    """R5: prava spravcu z domeny jen admin_offline_days od posledniho spojeni s radicem."""
    last = parse_iso(state.get("last_online"))
    if last is None:
        return False
    days = int(state.get("admin_offline_days", DEFAULT_ADMIN_OFFLINE_DAYS))
    return t - last <= days * 86400


def offline_left(state, t):
    last = parse_iso(state.get("last_online"))
    days = int(state.get("offline_days", DEFAULT_OFFLINE_DAYS))
    if last is None or days <= 0:
        return 0 if days <= 0 else None
    return max(0, days - int((t - last) // 86400))


def local_users():
    """Mistni bezni uzivatele z /etc/passwd -> {jmeno: uid}."""
    out = {}
    for line in read("/etc/passwd").splitlines():
        f = line.split(":")
        if len(f) >= 7 and f[2].isdigit() and 1000 <= int(f[2]) < 60000 and LOCAL_USER_RE.match(f[0]):
            out[f[0]] = int(f[2])
    return out


def full_name(user, domain):
    return f"{user}@{domain}"


def find_clashes(state):
    """R4: mistni ucet a domenovy ucet se stejnym jmenem -> [jmeno]. Ptame se SSSD na jmeno@domena."""
    if not have("getent"):
        return []
    out = []
    for name, uid in sorted(local_users().items()):
        rc, line, _e = capture([tool("getent"), "passwd", full_name(name, state["domain"])], timeout=20)
        f = line.strip().split(":")
        if rc == 0 and len(f) >= 3 and f[2].isdigit() and int(f[2]) != uid:
            out.append(name)
    return out


def apply_clashes(state, names):
    """Domenovy ucet s kolizi dostane plne jmeno a vlastni domovskou slozku (sss_override)."""
    new = [n for n in names if n not in state.get("clashes", [])]
    if not new or not have("sss_override"):
        return []
    done = []
    for n in new:
        fq = full_name(n, state["domain"])
        rc, _o, _e = capture([tool("sss_override"), "user-add", fq, "-n", fq, "-h", "/home/" + fq], timeout=30)
        if rc == 0:
            done.append(n)
    if done:
        state["clashes"] = sorted(set(state.get("clashes", [])) | set(done))
        systemctl("try-restart", "sssd.service")
        audit("full names for clashing domain users: " + ", ".join(done))
    return done


def display_name(user, state=None, local=None):
    """Jmeno domenoveho uzivatele na tomto pocitaci: jan, nebo jan@firma.local pri kolizi (R4)."""
    state = state if state is not None else load_state()
    local = local if local is not None else local_users()
    short = user.split("@", 1)[0].split("\\")[-1].lower()
    if short in local or short in (state.get("clashes") or []):
        return full_name(short, state.get("domain", ""))
    return short


def refresh(prog=None):
    """Casovac (10 min) a zmena site: online/offline, prava spravcu (R5), kolize jmen (R4)."""
    state = load_state()
    if not state.get("joined"):
        return None
    t = now()
    online = check_online(state)
    rules_dirty = False                    # pravidla sudo/polkit prepsat jen pri zmene (polkit je nacita znovu)
    if online:
        state["last_online"] = iso(t)
        if not state.get("auto_admins_checked") and have("getent"):
            # "LuxOS Admins" (pokud v domene je) = spravci LuxOS pocitacu
            for g in OPTIONAL_ADMINS:
                rc, _o, _e = capture([tool("getent"), "group", g.lower()], timeout=20)
                if rc == 0 and g.casefold() not in {x.casefold() for x in state.get("admin_groups", [])}:
                    state["admin_groups"] = state.get("admin_groups", []) + [g]
                    rules_dirty = True
            state["auto_admins_checked"] = True
        clashes = find_clashes(state)
        apply_clashes(state, clashes)
    active = admins_should_be_active(state, t)
    if active != state.get("admins_active", True) or rules_dirty:
        if active != state.get("admins_active", True):
            audit("domain administrator rights " + ("restored" if active else "suspended (offline too long)"))
        state["admins_active"] = active
        write_admin_rules(state, active)
    save_state(state)
    status = {"online": online, "checked": iso(t), "last_online": state.get("last_online"),
              "offline_left_days": offline_left(state, t), "admins_active": active}
    atomic_write(RUN_STATUS, json.dumps(status) + "\n", 0o644)
    return status


def repair():
    """Hook spravce baliku: nova verze nsswitch.conf / system-auth -> znovu SSSD (jen v domene)."""
    state = load_state()
    if not state.get("joined"):
        return False
    text = read(NSSWITCH)
    new, changed = nss_add(text)
    if changed:
        atomic_write(NSSWITCH, new, 0o644)
    if MARK not in read(PAM_AUTH):
        atomic_write(PAM_AUTH, render_pam(), 0o644)
    return True


# ---- stav pro CLI, Nastaveni a greeter ------------------------------------------------------------
def run_status():
    try:
        with open(P(RUN_STATUS), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def status():
    state = load_state()
    if not state.get("joined"):
        return {"joined": False}
    rs = run_status()
    t = now()
    last = rs.get("last_online") or state.get("last_online")
    s = dict(state, last_online=last)
    return {"joined": True, "domain": state["domain"], "realm": state.get("realm", ""),
            "short": state.get("short", ""), "joined_at": state.get("joined_at"),
            "computer": state.get("computer", ""), "controllers": state.get("controllers", []),
            "online": rs.get("online"), "last_online": last,
            "offline_days": state.get("offline_days", DEFAULT_OFFLINE_DAYS),
            "offline_left_days": offline_left(s, t),
            "admin_groups": state.get("admin_groups", []),
            "admins_active": admins_should_be_active(s, t) if last else state.get("admins_active", True),
            "admin_offline_days": state.get("admin_offline_days", DEFAULT_ADMIN_OFFLINE_DAYS),
            "allow_groups": state.get("allow_groups", []), "clashes": state.get("clashes", []),
            "shares": state.get("shares", []), "printers": state.get("printers", []),
            "gpo": state.get("gpo", {})}


def greeter_info():
    """Pro luxos-greeter (jen cteni souboru): None mimo domenu."""
    state = load_state()
    if not state.get("joined"):
        return None
    rs = run_status()
    s = dict(state, last_online=rs.get("last_online") or state.get("last_online"))
    return {"domain": state["domain"], "short": state.get("short", ""), "online": rs.get("online"),
            "offline_left_days": offline_left(s, now()), "example": full_name("jan", state["domain"])}


# ---- relace uzivatele: zalozky sdilenych slozek -----------------------------------------------------
def session_bookmarks(home=None, uid=None):
    """Prihlaseni domenoveho uzivatele: zalozky sdilenych slozek organizace v Souborech (GTK)."""
    state = load_state()
    uid = os.getuid() if uid is None else uid
    if not state.get("joined") or uid < DOMAIN_UID_MIN or not state.get("shares"):
        return []
    home = home or os.path.expanduser("~")
    path = os.path.join(home, ".config", "gtk-3.0", "bookmarks")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    have_urls = {ln.split(" ", 1)[0] for ln in lines}
    added = []
    for s in state["shares"]:
        if s["url"] not in have_urls:
            lines.append(f"{s['url']} {s['name']}")
            added.append(s["url"])
    if added:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return added
