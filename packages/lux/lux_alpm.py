#!/usr/bin/python3
"""lux_alpm - transakce a dotazy balicku pro lux pres libalpm (pyalpm).

Pouziva databazi (/var/lib/lux), konfiguraci (/etc/lux/lux.conf - TOML, cte ji primo lux_config z jadra
lux-engine, bez mezisouboru; s LUX_ENGINE_CONF=soubor syntaxe pacman.conf pres lux-engine-conf),
overovani podpisu, cache a hooky jadra. Spousti ho /usr/bin/lux; Obchod LuxOS a LuxOS Care s --machine.

  lux_alpm.py [volby] PRIKAZ [argumenty]

  available                       0 = pyalpm a konfigurace pouzitelne (jinak kod 3: lux pouzije lux-engine)
  sync [--force]                  obnovi databaze repozitaru                         (root)
  install [--needed] [--asdeps] [--refresh] CIL...  nazev, repo/nazev, skupina, provides, soubor .pkg.tar.*
  reinstall BALIK...              znovu z repozitare, jinak z cache                  (root)
  remove BALIK...                 odebere i nepotrebne zavislosti a zalohy konfigurace (= lux-engine -Rns)
  autoremove                      odebere nepotrebne zavislosti (= lux-engine -Rns $(lux-engine -Qdtq))
  upgrade [--refresh] [--download-only] [--keyring-first]   (update = vse z toho)
  search [--installed] VYRAZ... (vzory ^ $ * ? %, viz lux_community.py) | info BALIK | list [--installed|--upgradable|--explicit|--foreign|--orphans] [VZOR]
  list --sync                     vsechny balicky repozitaru: repo<TAB>nazev<TAB>verze<TAB>velikost<TAB>popis
  files BALIK | owns CESTA... | resolve CIL...
  check-updates [--db ADRESAR]    dostupne aktualizace bez zasahu do databaze systemu (obnova do
                                  docasne kopie; 0 = jsou, 2 = nejsou, 1 = chyba)      (uzivatel)
  clean [--keep N] [--keep-uninstalled N]   cache balicku: N poslednich verzi       (root)
  migrate [--now]                 prechod z rozlozeni pacmanu (LuxOS do 0.9.5) a uklid   (root)

Volby: -y/--yes, -v/--verbose, --machine, --color=auto|always|never, --lang KOD, --datasaver
Navratove kody: 0 ok, 1 chyba, 2 spatne pouziti, 3 pyalpm/konfigurace nelze pouzit, 130 preruseno.
Strojovy vystup (--machine) popisuje /usr/share/doc/lux/lux.md (radky "@@...").
"""
import argparse
import bisect
import contextlib
import fnmatch
import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import time

VERSION = "0.3.0"
EXIT_UNAVAILABLE = 3
# Nastroje jadra (lux-engine-conf, lux-engine-key... z lux-engine) jsou mimo PATH; potrebuje je lux_alpm
# i hooky a skriptlety transakci (dedi prostredi tohoto procesu)
ENGINE_BIN = "/usr/lib/lux/alpm/bin"
DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/bin"
DEFAULT_DBPATH = "/var/lib/lux/"
CHECK_UPDATES_WAIT = 300        # s: jak dlouho check-updates ceka na jinou probihajici kontrolu
DEFAULT_CACHEDIR = "/var/cache/lux/pkg/"
MIGRATE = os.environ.get("LUX_MIGRATE", "/usr/share/libalpm/scripts/lux-engine-migrate")

# lux-config (balik lux-engine): /usr/lib/lux, pri spusteni z repozitare ../lux-engine
for _d in ("/usr/lib/lux", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lux-engine")):
    if os.path.isfile(os.path.join(_d, "lux_config.py")) and _d not in sys.path:
        sys.path.append(_d)
try:
    import lux_config
except ImportError:
    lux_config = None


@contextlib.contextmanager
def system_writable(flags=None):
    """Ochrana systemu LuxOS (luxos-care, luxos_protect): /usr je jen pro cteni a zapisovatelny jen po
    dobu transakce. Odemkne se uz pred commitem (libalpm s CheckSpace kontroluje pripojeni jen pro cteni
    drive nez hooky); zamkne se hned po nem. Bez luxos-care nebo bez aktivni ochrany nic nedela."""
    protect = None
    if not (flags or {}).get("downloadonly"):
        if "/usr/lib/luxos/python" not in sys.path:
            sys.path.append("/usr/lib/luxos/python")
        try:
            import luxos_protect as protect
        except Exception:  # noqa: BLE001 - bez LuxOS Care (napr. jine distribuce, testy)
            protect = None
    with contextlib.ExitStack() as stack:
        if protect is not None:
            try:
                stack.enter_context(protect.writable())
            except Exception as e:  # noqa: BLE001 - nic se jeste nezmenilo
                raise LuxError("protected", _("Protected system files could not be opened for the update."),
                               [str(e)]) from e
        yield


def engine_path(path):
    """PATH s nastroji jadra na zacatku (bez duplicit)."""
    parts = [p for p in (path or DEFAULT_PATH).split(":") if p and p != ENGINE_BIN]
    return ":".join([ENGINE_BIN] + parts)

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


def lang():
    v = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "en"
    return v.split("_")[0].split(".")[0].split("@")[0] or "en"


def n_packages(n):
    """'1 package' / '3 packages'; jazyky s tvarem pro 2-4 maji navic klic '%d packages|few'."""
    if n == 1:
        return _("1 package")
    lg = lang()
    few = False
    if lg in ("cs", "sk"):
        few = 2 <= n <= 4
    elif lg in ("pl", "uk"):
        few = 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14
    if few:
        s = _("%d packages|few")
        if s != "%d packages|few":
            return s % n
    return _("%d packages") % n


# ---- formatovani ---------------------------------------------------------------------------
def fmt_size(n):
    """Velikost v jednotkach SI: 12.4 MB, 48 MB, 950 kB."""
    n = abs(int(n or 0))
    for unit, div in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if n >= div:
            v = n / div
            s = f"{v:.1f}" if v < 100 else f"{v:.0f}"
            return (s[:-2] if s.endswith(".0") else s) + " " + unit
    return f"{n} B"


def fmt_delta(n):
    return ("+" if n >= 0 else "-") + fmt_size(n)


def fmt_duration(sec):
    if sec < 60:
        return f"{sec:.1f} s"
    m, s = divmod(int(round(sec)), 60)
    return f"{m} min {s} s"


def plan_question(action, n, download, delta):
    """'Install 3 packages (12.4 MB download, +48 MB disk)?'"""
    parts = []
    if download:
        parts.append(_("%s download") % fmt_size(download))
    if delta or action != "remove":
        parts.append(_("%s disk") % fmt_delta(delta))
    what = n_packages(n) + (f" ({', '.join(parts)})" if parts else "")
    verb = {"install": _("Install %s?"), "upgrade": _("Upgrade %s?"), "reinstall": _("Reinstall %s?"),
            "remove": _("Remove %s?"), "download": _("Download %s?")}[action]
    return verb % what


def summary_line(action, explicit, ndeps, seconds):
    """'Installed firefox 131.0-1 (+2 deps) in 8.2 s' (explicit = [(nazev, verze)])."""
    verb = {"install": _("Installed %s"), "upgrade": _("Upgraded %s"), "reinstall": _("Reinstalled %s"),
            "remove": _("Removed %s"), "download": _("Downloaded %s")}[action]
    if explicit and len(explicit) <= 3:
        what = ", ".join(f"{n} {v}".strip() for n, v in explicit)
    else:
        what = n_packages(len(explicit) + (0 if explicit else ndeps))
        if not explicit:
            ndeps = 0
    s = verb % what
    if ndeps:
        s += " (" + _("+%d deps") % ndeps + ")"
    return s + " " + _("in %s") % fmt_duration(seconds)


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def visible_len(s):
    return len(ANSI.sub("", s))


# ---- chyby srozumitelne ----------------------------------------------------------------------
DETAIL_LINES = 6   # radky detailu chyby vypsane i bez --verbose


class LuxError(Exception):
    def __init__(self, kind, message, details=None, rc=1):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.details = list(details or [])
        self.rc = rc


ERROR_KINDS = [  # (text v chybe libalpm/pacmanu, druh) - stejne texty cte LuxOS Care a Obchod
    ("unable to lock database", "locked"),
    ("could not lock database", "locked"),
    ("insufficient privileges", "permission"),
    ("not enough free disk space", "disk"),
    ("no space left on device", "disk"),
    ("conflicting files", "conflict"),
    ("exists in filesystem", "conflict"),
    ("conflicting dependencies", "pkgconflict"),
    ("are in conflict", "pkgconflict"),
    ("could not satisfy dependencies", "deps"),
    ("unable to satisfy dependency", "deps"),
    ("invalid or corrupted package (checksum)", "corrupt"),
    ("signature", "keyring"),
    ("unknown trust", "keyring"),
    ("required key missing", "keyring"),
    ("invalid or corrupted database (pgp", "keyring"),
    ("failed retrieving file", "network"),
    ("failed to retrieve some files", "network"),
    ("failed to synchronize", "network"),
    ("download library error", "network"),
    ("could not resolve host", "network"),
    ("no servers configured", "network"),
    ("target not found", "notfound"),
    ("could not find or read package", "notfound"),
]


# Spravci baliku, kteri drzi zamek databaze (jmeno procesu), a nastroje LuxOS v Pythonu (skript v argumentech)
PKG_MANAGERS = {"lux-engine", "lux-engine-key", "pacman", "makepkg", "pacstrap", "yay", "paru", "pamac",
                "pamac-daemon", "packagekitd"}
PKG_SCRIPTS = {"lux_alpm.py": "lux", "luxos-care": "LuxOS Care", "luxos_care.py": "LuxOS Care",
               "luxos-update": "LuxOS Care", "luxos-store-helper": "LuxOS Store"}
LOCK_WAIT = float(os.environ.get("LUX_LOCK_WAIT", "300"))     # s: jak dlouho cekat na jinou aktualizaci


def _ancestors(pid):
    """PID procesu a vsech jeho predku (vlastni lux, sudo, Obchod... nejsou "jiny spravce baliku")."""
    out = set()
    while pid > 1 and pid not in out:
        out.add(pid)
        try:
            with open(f"/proc/{pid}/stat") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out


def running_package_managers(proc="/proc"):
    """Nazvy jinych bezicich spravcu baliku (bez tohoto procesu a jeho predku)."""
    mine = _ancestors(os.getpid())
    names = set()
    try:
        pids = [int(d) for d in os.listdir(proc) if d.isdigit()]
    except OSError:
        return []
    for pid in pids:
        if pid in mine:
            continue
        try:
            with open(f"{proc}/{pid}/comm") as f:
                comm = f.read().strip()
            with open(f"{proc}/{pid}/cmdline", "rb") as f:
                argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if comm in PKG_MANAGERS:
            names.add(comm)
            continue
        for a in argv[:3]:
            label = PKG_SCRIPTS.get(os.path.basename(a))
            if label:
                names.add(label)
                break
    return sorted(names)


def classify(text):
    low = (text or "").lower()
    for needle, kind in ERROR_KINDS:
        if needle in low:
            return kind
    return "unknown"


def stale_download(text):
    """Server odpovedel 404 u souboru baliku (ne databaze): mistni seznam baliku je zastaraly."""
    return any(("404" in line) and ".pkg.tar" in line for line in (text or "").splitlines())


def plain_message(kind, detail=""):
    m = {
        "locked": _("Another update is still running (%s). Try again when it finishes.") % detail if detail else
        _("The package database is locked: another package manager is running, "
          "or a previous one crashed. If nothing else is running: lux fix"),
        "refresh": _("The package lists could not be refreshed: %s") % detail if detail else
        _("The package lists could not be refreshed."),
        "permission": _("This needs administrator rights."),
        "disk": _("Not enough free disk space. Free some space (lux clean) and try again."),
        "conflict": _("Some files of the new packages already exist on the system (file conflict)."),
        "pkgconflict": _("The selected packages conflict with installed packages."),
        "deps": _("Dependencies can not be satisfied: %s") % detail if detail else
        _("Dependencies can not be satisfied."),
        "corrupt": _("A downloaded package is damaged. Try again; if it repeats, run: lux clean"),
        "keyring": _("A package signature could not be verified. Repair the signing keys with: lux fix"),
        "network": _("Some packages could not be downloaded. Check your internet connection and try again."),
        "outdated": _("The package lists are out of date: the server no longer has this version. "
                      "Update the system first (lux update), then try again."),
        "notfound": _("Package '%s' not found. Try: lux search %s") % (detail, detail) if detail else
        _("Package not found."),
        "config": _("The package manager configuration has an error. Check it with: lux config check"),
        "dbinvalid": _("The package lists are damaged or do not match their signatures. "
                       "Refresh them first (lux update), then try again."),
    }
    return m.get(kind, _("The package operation failed."))


def alpm_error_parts(exc):
    """pyalpm.error(zprava, errno, data) -> (zprava, errno, [radky detailu])."""
    args = getattr(exc, "args", ()) or ()
    msg = str(args[0]) if args else str(exc)
    errno = args[1] if len(args) > 1 and isinstance(args[1], int) else None
    data = args[2] if len(args) > 2 else None
    return msg, errno, describe_data(data)


def describe_data(data):
    """Data k chybe libalpm (konflikty souboru, chybejici zavislosti...) jako radky ve stylu pacmanu."""
    if data is None:
        return []
    if isinstance(data, (str, bytes)):
        return [data.decode() if isinstance(data, bytes) else data]
    out = []
    try:
        items = list(data)
    except TypeError:
        return [str(data)]
    for it in items:
        if isinstance(it, (tuple, list)):
            parts = [str(x) for x in it if x not in (None, "")]
            files = [p for p in parts if p.startswith("/")]
            # konflikt souboru (cil, typ, soubor, cil2): "cil: /soubor exists in filesystem" (jako pacman)
            if files and parts:
                other = [p for p in parts[1:] if not p.startswith("/") and not p.isdigit()]
                owner = f" (owned by {other[-1]})" if other else ""
                out.append(f"{parts[0]}: {files[0]} exists in filesystem{owner}")
            else:
                out.append(": ".join(parts))
        else:
            out.append(str(it))
    return out


# ---- konfigurace jadra (lux-engine-conf = parser jadra) ------------------------------------------
def sig_bits(api=None):
    g = (lambda n, d: getattr(api, n, d)) if api is not None else (lambda n, d: d)
    return {
        "P": g("SIG_PACKAGE", 1 << 0), "PO": g("SIG_PACKAGE_OPTIONAL", 1 << 1),
        "PM": g("SIG_PACKAGE_MARGINAL_OK", 1 << 2), "PU": g("SIG_PACKAGE_UNKNOWN_OK", 1 << 3),
        "D": g("SIG_DATABASE", 1 << 10), "DO": g("SIG_DATABASE_OPTIONAL", 1 << 11),
        "DM": g("SIG_DATABASE_MARGINAL_OK", 1 << 12), "DU": g("SIG_DATABASE_UNKNOWN_OK", 1 << 13),
    }


def parse_siglevel(tokens, base=None, api=None):
    """SigLevel jako pacman (conf.c process_siglevel): Never/Optional/Required/TrustedOnly/TrustAll
    s volitelnou predponou Package/Database; nezadane casti zustanou z base (globalni SigLevel)."""
    b = sig_bits(api)
    level = base if base is not None else (b["P"] | b["PO"] | b["D"] | b["DO"])
    for tok in tokens:
        for word in str(tok).split():
            pkg = db = True
            if word.startswith("Package"):
                db, word = False, word[7:]
            elif word.startswith("Database"):
                pkg, word = False, word[8:]
            for on, pre in ((pkg, "P"), (db, "D")):
                if not on:
                    continue
                if word == "Never":
                    level &= ~b[pre]
                elif word == "Optional":
                    level |= b[pre] | b[pre + "O"]
                elif word == "Required":
                    level |= b[pre]
                    level &= ~b[pre + "O"]
                elif word == "TrustedOnly":
                    level &= ~(b[pre + "M"] | b[pre + "U"])
                elif word == "TrustAll":
                    level |= b[pre + "M"] | b[pre + "U"]
                else:
                    raise LuxError("config", f"invalid SigLevel value: {word}", rc=EXIT_UNAVAILABLE)
    return level


# Vychozi hodnoty jadra lux-engine (zkompilovane v libalpm/pacman-conf, viz PKGBUILD lux-engine)
ENGINE_DEFAULTS = (("RootDir", "/"), ("DBPath", DEFAULT_DBPATH), ("CacheDir", DEFAULT_CACHEDIR),
                   ("HookDir", "/etc/lux/hooks/"), ("GPGDir", "/etc/lux/keyring/"), ("LogFile", "/var/log/lux.log"))


class EngineConf:
    """Konfigurace jadra: z lux.conf primo (from_lux) nebo vystup `lux-engine-conf` (syntaxe pacman.conf)."""

    def __init__(self, text):
        self.options = {}
        self.repos = []
        cur = self.options
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                name = line[1:-1].strip()
                if name == "options":
                    cur = self.options
                else:
                    cur = {"name": name}
                    self.repos.append(cur)
                continue
            key, sep, val = line.partition("=")
            key, val = key.strip(), val.strip()
            cur.setdefault(key, [])
            if sep:
                cur[key].append(val)

    @classmethod
    def from_lux(cls, cfg):
        """Z rozparsovane /etc/lux/lux.conf (lux_config.parse) - stejne hodnoty jako lux-engine-conf
        nad vygenerovanou /run/lux/engine.conf, vcetne vychozich cest jadra."""
        opts, repos = lux_config.engine_options(cfg)
        c = cls("")
        for directive, value in opts:
            c.options.setdefault(directive, [])
            if value is not None:
                c.options[directive].append(value)
        for directive, value in ENGINE_DEFAULTS:
            c.options.setdefault(directive, [value])
        c.repos = [{k: (list(v) if isinstance(v, list) else v) for k, v in r.items()} for r in repos]
        return c

    def get(self, key, default=None):
        v = self.options.get(key)
        return v[-1] if v else default

    def list(self, key):
        """Opakovatelna volba; hodnoty oddelene mezerami (HoldPkg = lux-engine glibc)."""
        return [w for v in (self.options.get(key) or []) for w in v.split()]

    def has(self, key):
        return key in self.options

    def with_options(self, set_=None, drop=()):
        """Kopie s jinymi volbami (napr. docasna databaze pro check-updates)."""
        c = EngineConf("")
        c.options = {k: list(v) for k, v in self.options.items() if k not in drop}
        for k, v in (set_ or {}).items():
            c.options[k] = [v]
        c.repos = [dict(r) for r in self.repos]
        return c


def engine_conf_path():
    """/run/lux/engine.conf (z /etc/lux/lux.conf, viz lux-config). Rozbita lux.conf: lux nepokracuje."""
    if os.environ.get("LUX_ENGINE_CONF"):
        return os.environ["LUX_ENGINE_CONF"]
    if lux_config is None:
        raise LuxError("config", "lux-config is missing (package lux-engine)", rc=EXIT_UNAVAILABLE)
    import io
    err = io.StringIO()
    path, state = lux_config.ensure(err=err)
    if state != "ok":
        lines = [ln.replace("lux: error in the configuration: ", "") for ln in err.getvalue().splitlines()]
        raise LuxError("config", _("The package manager configuration has an error: %s") % (lines[0] if lines else "?")
                       + "\n" + _("Fix it and check it with: lux config check"), lines[1:])
    return path


def load_engine_conf():
    if hasattr(lux_config, "engine_options") and not os.environ.get("LUX_ENGINE_CONF"):
        # LuxOS 1.0: /etc/lux/lux.conf primo (TOML i starsi format), bez /run/lux/engine.conf
        # (lux-engine pred LuxOS 1.0 engine_options nema - pak jako drive pres lux-engine-conf)
        try:
            return EngineConf.from_lux(lux_config.parse(lux_config.LUX_CONF))
        except lux_config.ConfigError as e:
            raise LuxError("config", _("The package manager configuration has an error: %s") % e
                           + "\n" + _("Fix it and check it with: lux config check"))
        except OSError as e:
            raise LuxError("config", f"{lux_config.LUX_CONF}: {e}", rc=EXIT_UNAVAILABLE)
    if lux_config is None and not os.environ.get("LUX_ENGINE_CONF"):
        # jadro z LuxOS 0.9.0 (luxos-pacman, /etc/pacman.conf) do vymeny za lux-engine
        cmd = ["lux-engine-conf" if shutil.which("lux-engine-conf") else "pacman-conf"]
    else:
        cmd = ["lux-engine-conf", "--config", engine_conf_path()]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise LuxError("config", f"lux-engine-conf: {e}", rc=EXIT_UNAVAILABLE)
    if r.returncode != 0:
        raise LuxError("config", "lux-engine-conf: " + (r.stderr or "").strip(), rc=EXIT_UNAVAILABLE)
    return EngineConf(r.stdout)


def usage_mask(tokens):
    """Usage repozitare (Sync/Search/Install/Upgrade/All) -> mnozina."""
    words = set(" ".join(tokens or []).split()) or {"All"}
    if "All" in words:
        return {"Sync", "Search", "Install", "Upgrade"}
    return words


def _try_set(obj, name, value):
    try:
        setattr(obj, name, value)
        return True
    except (AttributeError, TypeError):
        return False


def build_handle(api, conf):
    """pyalpm.Handle nastaveny jako jadro. Co pyalpm neumi a v konfiguraci se pouziva, je chyba
    (vyjimka s rc 3) - lux pak radeji pouzije lux-engine, nez aby se choval jinak."""
    root = conf.get("RootDir", "/")
    dbpath = conf.get("DBPath", DEFAULT_DBPATH)
    h = api.Handle(root, dbpath)
    missing = []

    archs = [os.uname().machine if a == "auto" else a for a in conf.list("Architecture")] or [os.uname().machine]
    if hasattr(h, "add_architecture"):
        for a in archs:
            h.add_architecture(a)
    elif not _try_set(h, "architectures", archs):
        # pyalpm 0.12: "arch" je seznam (alpm_option_set_architectures); retezec by se rozpadl na znaky
        as_list = isinstance(getattr(h, "arch", None), (list, tuple))
        if not _try_set(h, "arch", archs if as_list else archs[0]):
            missing.append("Architecture")

    for opt, attr, adder in (("CacheDir", "cachedirs", "add_cachedir"), ("HookDir", "hookdirs", "add_hookdir"),
                             ("NoUpgrade", "noupgrades", "add_noupgrade"), ("NoExtract", "noextracts", "add_noextract"),
                             ("IgnorePkg", "ignorepkgs", "add_ignorepkg"), ("IgnoreGroup", "ignoregrps", "add_ignoregrp")):
        vals = conf.list(opt)
        if not vals:
            continue
        if attr == "hookdirs":
            # hooky z /usr/share/libalpm/hooks pridava libalpm sam; HookDir (napr. /etc/lux/hooks)
            # je nutne jen kdyz v nem nejake hooky jsou a jen pro transakce: kontrola aktualizaci,
            # hledani a informace nic neinstaluji (sdileny ESP ma v /etc/lux/hooks hook kopie jadra,
            # pyalpm bez hookdirs pak odmital i "check-updates" Obchodu)
            needed = TRANSACTION and any(glob.glob(os.path.join(root, d.lstrip("/"), "*.hook")) for d in vals)
        else:
            needed = True
        if hasattr(h, adder):
            for v in vals:
                getattr(h, adder)(v)
            continue
        cur = []
        if attr == "hookdirs":
            try:
                cur = list(getattr(h, attr) or [])
            except AttributeError:
                cur = []
        if not _try_set(h, attr, cur + [v for v in vals if v not in cur]) and needed:
            missing.append(opt)

    for opt, attr in (("GPGDir", "gpgdir"), ("LogFile", "logfile")):
        v = conf.get(opt)
        if v and not _try_set(h, attr, v):
            missing.append(opt)
    if conf.has("CheckSpace"):
        _try_set(h, "checkspace", True)
    if conf.has("UseSyslog"):
        _try_set(h, "usesyslog", True)
    if conf.has("DisableDownloadTimeout"):
        _try_set(h, "disable_dl_timeout", True)
    if conf.get("ParallelDownloads", "").isdigit():
        _try_set(h, "parallel_downloads", int(conf.get("ParallelDownloads")))
    if conf.get("XferCommand"):
        missing.append("XferCommand")
    # pacman 7: stahovani pod neprivilegovanym uzivatelem (DownloadUser). Kdyz to pyalpm neumi,
    # stahuje se jako u pacmanu 6 pod rootem (podpisy se overuji stejne) - viz "available -v".
    notes = []
    if conf.get("DownloadUser") and not conf.has("DisableSandbox"):
        if not _try_set(h, "sandboxuser", conf.get("DownloadUser")):
            notes.append("DownloadUser is not supported by pyalpm: downloads run as root (like pacman 6)")

    base = parse_siglevel(conf.list("SigLevel"), api=api)
    local_sig = parse_siglevel(conf.list("LocalFileSigLevel"), base, api)
    remote_sig = parse_siglevel(conf.list("RemoteFileSigLevel"), base, api)
    _try_set(h, "default_siglevel", base)
    _try_set(h, "local_file_siglevel", local_sig)
    _try_set(h, "remote_file_siglevel", remote_sig)

    arch = archs[0]
    for repo in conf.repos:
        name = repo["name"]
        sig = parse_siglevel(repo.get("SigLevel") or [], base, api)
        db = h.register_syncdb(name, sig)
        servers = [s.replace("$repo", name).replace("$arch", arch) for s in repo.get("Server", [])]
        db.servers = servers
        repo["_usage"] = usage_mask(repo.get("Usage"))
    if missing:
        raise LuxError("config", "pyalpm does not support: " + ", ".join(missing), rc=EXIT_UNAVAILABLE)
    return h, {"local_siglevel": local_sig, "remote_siglevel": remote_sig, "siglevel": base, "notes": notes}


# ---- vystup ----------------------------------------------------------------------------------
class UI:
    def __init__(self, color="auto", machine=False, verbose=False, yes=False, out=None, inp=None):
        self.out = out or sys.stdout
        self.inp = inp or sys.stdin
        self.machine = machine
        self.verbose = verbose
        self.yes = yes
        self.tty = (not machine) and _isatty(self.out)
        if color == "always":
            self.color = True
        elif color == "never" or machine:
            self.color = False
        else:
            self.color = self.tty and not os.environ.get("NO_COLOR")
        self.ph = None
        self._last_draw = 0.0

    # barvy
    def c(self, code, text):
        return f"\x1b[{code}m{text}\x1b[0m" if self.color else str(text)

    def bold(self, t):
        return self.c("1", t)

    def dim(self, t):
        return self.c("2", t)

    def accent(self, t):
        return self.c("38;2;167;123;255", t)

    def green(self, t):
        return self.c("32", t)

    def yellow(self, t):
        return self.c("33", t)

    def red(self, t):
        return self.c("31", t)

    def write(self, text="", err=False):
        self.clear_line()
        stream = sys.stderr if err and not self.machine else self.out
        stream.write(text + "\n")
        stream.flush()

    def ok(self, text):
        if not self.machine:
            self.write(f"{self.green('✓')} {text}")

    def say(self, text):
        if not self.machine:
            self.write(f"{self.accent('✦')} {text}")

    def note(self, text):
        if not self.machine:
            self.write(self.dim(text))

    def warn(self, text):
        if self.machine:
            self.write(f"warning: {text}")
        else:
            self.write(f"{self.yellow('!')} {text}", err=True)

    def fail(self, text):
        if not self.machine:
            self.write(f"{self.red('✗')} {text}", err=True)

    def emit(self, *parts):
        """Strojovy radek "@@..." (jen --machine)."""
        if self.machine:
            self.out.write("@@" + " ".join(str(p) for p in parts) + "\n")
            self.out.flush()

    def compat(self, text):
        """Radek ve tvaru vystupu pacmanu (pro starsi ctenare ve strojovem rezimu)."""
        if self.machine:
            self.out.write(text + "\n")
            self.out.flush()

    def ask(self, question, default=True):
        if self.yes:
            return True
        if self.machine or not _isatty(self.inp):
            raise LuxError("confirm", _("Confirmation is needed: run the command in a terminal or add -y."))
        hint = "[Y/n]" if default else "[y/N]"
        self.clear_line()
        self.out.write(f"{self.bold(question)} {hint} ")
        self.out.flush()
        a = self.inp.readline()
        if not a:
            return False
        a = a.strip().lower()
        if not a:
            return default
        return a[0] in "ya"

    # prubeh: jedna radka na fazi
    LABELS = {"refresh": "Refreshing", "download": "Downloading", "verify": "Verifying",
              "install": "Installing", "remove": "Removing", "hooks": "Finishing", "prepare": "Preparing"}

    def phase(self, name, detail=""):
        if self.ph and self.ph["name"] == name:
            return
        self.phase_done()
        self.ph = {"name": name, "frac": 0.0, "detail": detail, "start": time.time()}
        self.emit("PHASE", name)
        self.draw(force=True)

    def progress(self, frac, detail=None):
        if not self.ph:
            return
        self.ph["frac"] = max(self.ph["frac"] if self.ph["name"] != "download" else 0.0, min(1.0, frac))
        if detail is not None:
            self.ph["detail"] = detail
        self.draw()

    def phase_done(self, ok=True, detail=None):
        ph = self.ph
        if not ph:
            return
        if detail is not None:
            ph["detail"] = detail
        if ok:
            ph["frac"] = 1.0
        self.ph = None
        if self.machine:
            self.emit("PROGRESS", ph["name"], int(ph["frac"] * 100), ph["detail"])
            return
        icon = self.green("✓") if ok else self.red("✗")
        line = self.render(ph, icon)
        if self.tty:
            self.out.write("\r\x1b[2K" + line + "\n")
        else:
            self.out.write(line + "\n")
        self.out.flush()

    def label_width(self):
        return max(len(_(v)) for v in self.LABELS.values())

    def render(self, ph, icon):
        label = _(self.LABELS.get(ph["name"], ph["name"]))
        label = label + " " * max(0, self.label_width() - len(label))
        pct = int(ph["frac"] * 100)
        cols = shutil.get_terminal_size((80, 24)).columns
        if not self.tty:
            return f"{icon} {label}  {pct:3d}%  {ph['detail']}".rstrip()
        barw = 20 if cols >= 70 else 10
        full = int(round(ph["frac"] * barw))
        bar = self.accent("█" * full) + self.dim("░" * (barw - full))
        head = f"{icon} {self.bold(label)} {bar} {pct:3d}%  "
        room = cols - visible_len(head) - 1
        detail = ph["detail"] or ""
        if len(detail) > room:
            detail = detail[:max(0, room - 1)] + "…" if room > 1 else ""
        return head + self.dim(detail)

    def draw(self, force=False):
        ph = self.ph
        if not ph:
            return
        now = time.time()
        if self.machine:
            if force or now - self._last_draw >= 0.5:
                self._last_draw = now
                self.emit("PROGRESS", ph["name"], int(ph["frac"] * 100), ph["detail"])
            return
        if not self.tty:
            return
        if not force and now - self._last_draw < 0.08:
            return
        self._last_draw = now
        self.out.write("\r\x1b[2K" + self.render(ph, self.accent("↓" if ph["name"] in ("download", "refresh")
                                                                     else "•")))
        self.out.flush()

    def clear_line(self):
        if self.tty and self.ph:
            self.out.write("\r\x1b[2K")


def _isatty(f):
    try:
        return f.isatty()
    except (AttributeError, ValueError):
        return False


# ---- callbacky libalpm --------------------------------------------------------------------------
# alpm_event_type_t (alpm.h, pacman 6/7) - jen udalosti, ktere lux ukazuje
EV_SCRIPTLET_INFO = 17
EV_PACNEW_CREATED = 32      # soubor *.luxnew (lux-engine; jmeno udalosti z API libalpm)
EV_HOOK_START = 34
EV_HOOK_DONE = 35
EV_HOOK_RUN_START = 36
EV_HOOK_RUN_DONE = 37
# alpm_loglevel_t
LOG_ERROR, LOG_WARNING, LOG_DEBUG = 1, 2, 4
# alpm_question_type_t
Q_INSTALL_IGNOREPKG, Q_REPLACE_PKG, Q_CONFLICT_PKG, Q_CORRUPTED_PKG = 1, 2, 4, 8
Q_REMOVE_PKGS, Q_SELECT_PROVIDER, Q_IMPORT_KEY = 16, 32, 64
# alpm_download_event_type_t
DL_INIT, DL_PROGRESS, DL_RETRY, DL_COMPLETED = 0, 1, 2, 3
# pyalpm 0.12 u nekterych udalosti misto skutecneho textu posila jen tyto zastupne retezce
PYALPM_PLACEHOLDERS = ("unknown event", "event not implemented")


# ---- hooky libalpm: ktere se spusti a v jakem poradi --------------------------------------------
# pyalpm u udalosti hooku posila jen typ (text je "unknown event"), ne nazev, poradi ani pocet -
# faze "Dokoncuji" proto dlouho stala na 0 %. Ktere hooky se spusti, spocita lux stejne jako libalpm
# (spoustece Package/Path nad cili transakce, razeni podle nazvu, pozdejsi HookDir prekryva drivejsi).
# Seznamy souboru novych baliku jsou az po instalaci, proto je to odhad; libalpm pred spustenim
# hooku zaloguje 'executing "<Exec>"' a podle toho se poradi i celkovy pocet opravi.
HOOK_SYSDIR = "/usr/share/libalpm/hooks/"
EXECUTING_RE = re.compile(r'^executing "([^"]+)"')


def alpm_fnmatch_patterns(patterns, text):
    """_alpm_fnmatch_patterns: rozhoduje posledni odpovidajici vzor; 0 = shoda, 1 = vylouceno (!),
    -1 = zadny vzor neodpovida. '*' v libalpm (fnmatch bez FNM_PATHNAME) odpovida i '/'."""
    for pat in reversed(patterns):
        inverted = pat.startswith("!")
        if inverted or pat.startswith("\\"):
            pat = pat[1:]
        if fnmatch.fnmatchcase(text, pat):
            return 1 if inverted else 0
    return -1


def parse_hook(path):
    """Soubor *.hook (alpm-hooks(5)) -> {name, desc, when, exec, triggers}; None = neplatny/maskovany."""
    name = os.path.basename(path)[:-5]
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    hook = {"name": name, "desc": "", "when": "", "exec": "", "triggers": []}
    section = None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            if section == "Trigger":
                hook["triggers"].append({"type": "", "ops": set(), "targets": []})
            continue
        key, _sep, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if section == "Trigger" and hook["triggers"]:
            trig = hook["triggers"][-1]
            if key == "Type":
                trig["type"] = "Path" if val == "File" else val
            elif key == "Operation":
                trig["ops"].add(val)
            elif key == "Target":
                trig["targets"].append(val)
        elif section == "Action":
            if key == "Description":
                hook["desc"] = val
            elif key == "When":
                hook["when"] = {"PreTransaction": "pre", "PostTransaction": "post"}.get(val, "")
            elif key == "Exec":
                hook["exec"] = val.split()[0] if val.split() else ""
    if not hook["when"] or not hook["exec"] or not hook["triggers"]:
        return None
    return hook


def read_pkg_files(dbpath, name, version):
    """Seznam souboru baliku z mistni databaze (<dbpath>/local/<nazev>-<verze>/files)."""
    out = []
    try:
        with open(os.path.join(dbpath, "local", f"{name}-{version}", "files"), encoding="utf-8",
                  errors="replace") as f:
            infiles = False
            for line in f:
                line = line.rstrip("\n")
                if line.startswith("%"):
                    if infiles:
                        break
                    infiles = line == "%FILES%"
                elif infiles and line:
                    out.append(line)
    except OSError:
        pass
    return out


def any_path_match(files, targets):
    """Odpovida nektery soubor (serazeny seznam) cilum Path spoustece? Bez prochazeni vsech souboru:
    jen rozsah se stejnou doslovnou predponou jako kazdy kladny vzor."""
    if not files:
        return False
    for pat in targets:
        if pat.startswith("!"):
            continue
        pat = pat[1:] if pat.startswith("\\") else pat
        prefix = re.split(r"[*?\[\\]", pat, maxsplit=1)[0]
        i = bisect.bisect_left(files, prefix)
        while i < len(files) and files[i].startswith(prefix):
            if alpm_fnmatch_patterns(targets, files[i]) == 0:
                return True
            i += 1
    return False


class HookPlan:
    """Hooky libalpm, ktere transakce spusti (odhad pro prubeh fazi Pripravuji a Dokoncuji)."""

    def __init__(self, hooks, dbpath, installs, upgrades, removes):
        self.hooks = sorted(hooks, key=lambda h: h["name"])
        self.dbpath = dbpath
        self.installs = installs        # nazev -> nova verze
        self.upgrades = upgrades        # nazev -> (stara verze, nova verze)
        self.removes = removes          # nazev -> verze
        # soubory odebiranych baliku po transakci uz v databazi nejsou - nacist hned
        self._files = {"remove": self._merge(read_pkg_files(dbpath, n, v) for n, v in removes.items())}

    @classmethod
    def load(cls, hookdirs, dbpath, installs, upgrades, removes, root="/"):
        found = {}
        for d in hookdirs:                      # pozdejsi adresar prekryva drivejsi (jako libalpm)
            if root not in ("", "/"):
                d = os.path.join(root, d.lstrip("/"))
            for path in glob.glob(os.path.join(d, "*.hook")):
                found[os.path.basename(path)[:-5]] = path
        hooks = [h for h in (parse_hook(p) for p in found.values()) if h]
        return cls(hooks, dbpath, installs, upgrades, removes)

    @staticmethod
    def _merge(lists):
        out = []
        for lst in lists:
            out.extend(lst)
        out.sort()
        return out

    def files(self, op, when):
        key = (op, when)
        if key not in self._files:
            if op == "Remove":
                self._files[key] = self._files["remove"]
            elif op == "Install":
                # pred transakci soubory novych baliku nezname
                self._files[key] = [] if when == "pre" else self._merge(
                    read_pkg_files(self.dbpath, n, v) for n, v in self.installs.items())
            else:
                idx = 0 if when == "pre" else 1
                self._files[key] = self._merge(
                    read_pkg_files(self.dbpath, n, vv[idx]) for n, vv in self.upgrades.items())
        return self._files[key]

    def triggered(self, hook, when):
        for trig in hook["triggers"]:
            for op in trig["ops"]:
                if trig["type"] == "Package":
                    names = {"Install": self.installs, "Upgrade": self.upgrades, "Remove": self.removes}.get(op, {})
                    if any(alpm_fnmatch_patterns(trig["targets"], n) == 0 for n in names):
                        return True
                elif trig["type"] == "Path" and op in ("Install", "Upgrade", "Remove"):
                    if any_path_match(self.files(op, when), trig["targets"]):
                        return True
        return False

    def all(self, when):
        return [h for h in self.hooks if h["when"] == when]

    def run(self, when):
        """Hooky dane faze (pre/post), ktere se pravdepodobne spusti, v poradi libalpm."""
        return [h for h in self.all(when) if self.triggered(h, when)]


def hook_label(hook):
    """Popis hooku pro radku prubehu (Description bez koncovych tecek, jinak nazev souboru)."""
    if not hook:
        return ""
    if isinstance(hook, str):
        return hook.strip().rstrip(".…").strip()
    desc = (hook.get("desc") or "").strip().rstrip(".…").strip()
    return desc or hook.get("name", "")


class Callbacks:
    """Prevadi callbacky libalpm na jeden radek prubehu na fazi (a strojove radky)."""

    def __init__(self, ui):
        self.ui = ui
        self.reset()

    def reset(self, mode="", dl_total=0, ops=None, sizes=None, cachedirs=None, hooks=None):
        self.mode = mode            # refresh | commit
        self.hooks = hooks          # HookPlan nebo None
        self.hook_when = None       # pre | post behem behu hooku
        self.hook_list = []         # odhad hooku, ktere se spusti
        self.hook_pos = 0           # poradi bezuciho hooku (z udalosti libalpm, presne)
        self.hook_next = 0          # index dalsiho jeste nespusteneho hooku v hook_list
        self.hook_cur = None        # bezici hook (dict z HookPlan nebo text od pyalpm)
        self.hook_last = ""         # nazev predchoziho hooku (libalpm je spousti serazene podle nazvu)
        self.hook_running = False
        self.dl_total = dl_total
        self.sizes = sizes or {}    # soubor balicku -> velikost ke stazeni
        self.cachedirs = cachedirs or []
        self.files = {}             # soubor -> stazeno
        self.file_totals = {}
        self.ops = ops or {}        # nazev -> installing|upgrading|...
        self.current = None
        self.dl_start = time.time()
        self.log_errors = []
        self.log_warnings = []
        self.scriptlet = []
        self.pacnew = 0
        self.hosts = set()
        self.failed_hosts = []
        self.corrupted = []         # poskozene stazene balicky (cesty z otazky libalpm)

    # stahovani
    def dl(self, *args):
        if not args:
            return
        fname = str(args[0])
        if len(args) >= 3 and isinstance(args[2], (tuple, list)):
            ev, data = args[1], tuple(args[2])
            if ev == DL_PROGRESS and len(data) >= 2:
                self.file_progress(fname, data[0], data[1])
            elif ev == DL_RETRY:
                self.files[fname] = 0
            elif ev == DL_COMPLETED:
                total = data[0] if data else 0
                result = data[1] if len(data) > 1 else 0
                if result == 0 and total:
                    self.file_progress(fname, total, total)
                if result >= 0:
                    self.file_done(fname)
        elif (len(args) >= 3 and getattr(self, "dl_events", False)
              and args[1] in (DL_INIT, DL_PROGRESS, DL_RETRY, DL_COMPLETED)):
            # pyalpm 0.12 posila (soubor, udalost, ukazatel na data) - data jsou nepouzitelna,
            # stazeno se proto zjisti z velikosti rozpracovaneho souboru v cache
            ev, total = args[1], self.sizes.get(fname, 0)
            if ev == DL_PROGRESS and total:
                self.file_progress(fname, min(self.partial_size(fname), total), total)
            elif ev == DL_RETRY:
                self.files[fname] = 0
            elif ev == DL_COMPLETED:
                if total:
                    self.file_progress(fname, total, total)
                self.file_done(fname)
        elif len(args) >= 3 and isinstance(args[1], int) and isinstance(args[2], int):
            xfered, total = args[1], args[2]       # starsi pyalpm: (soubor, stazeno, celkem)
            self.file_progress(fname, xfered, total)
            if total and xfered >= total:
                self.file_done(fname)

    def partial_size(self, fname):
        for d in self.cachedirs:
            for path in [os.path.join(d, fname + ".part")] + glob.glob(os.path.join(d, "download-*", fname + ".part")):
                try:
                    return os.path.getsize(path)
                except OSError:
                    pass
        return self.files.get(fname, 0)

    def file_progress(self, fname, got, total):
        if self.mode == "refresh":
            return
        if total and total > 0:
            self.file_totals[fname] = total
        self.files[fname] = max(0, got or 0)
        if self.ui.ph is None or self.ui.ph["name"] != "download":
            self.ui.phase("download")
        total_all = max(self.dl_total, sum(self.file_totals.values())) or 1
        got_all = sum(self.files.values())
        speed = got_all / max(0.5, time.time() - self.dl_start)
        self.ui.progress(got_all / total_all, f"{fmt_size(got_all)} / {fmt_size(total_all)} · {fmt_size(speed)}/s")

    def file_done(self, fname):
        if self.mode != "refresh" and not fname.endswith(".sig"):
            self.ui.compat(f"{fname} downloading...")

    # prubeh operaci (pyalpm: cil, procenta, pocet, poradi; nekdy s typem operace na zacatku)
    def progress(self, *args):
        if len(args) >= 5 and not isinstance(args[0], str):
            args = args[1:]
        if len(args) < 4:
            return
        target, percent, n, i = args[0], args[1], args[2], args[3]
        target = target or ""
        try:
            n, i, percent = int(n), int(i), int(percent)
        except (TypeError, ValueError):
            return
        if not target:
            # kontrola integrity, nacitani, konflikty, misto na disku (kontroly pred stahovanim se neukazuji)
            if self.dl_total and not self.files:
                return
            if self.ui.ph is None or self.ui.ph["name"] not in ("verify",):
                self.ui.phase("verify")
            self.ui.progress((max(i, 1) - 1 + percent / 100) / max(n, 1))
            return
        op = self.ops.get(target, "installing")
        name = "remove" if op == "removing" and all(v == "removing" for v in self.ops.values()) else "install"
        if self.ui.ph is None or self.ui.ph["name"] != name:
            self.ui.phase(name)
        if target != self.current:
            self.current = target
            self.ui.compat(f"{op} {target}...")
        self.ui.progress((max(i, 1) - 1 + percent / 100) / max(n, 1), f"{max(i, 1)}/{n} {target}")

    def event(self, *args):
        ev = next((a for a in args if isinstance(a, int)), None)
        text = next((a for a in args if isinstance(a, str)), "")
        if ev == EV_HOOK_START:
            # hooky pred transakci (ochrana systemu, snimek...) bezi pred prvni operaci s balikem
            self.hook_start("pre" if self.mode == "commit" and self.current is None else "post")
        elif ev == EV_HOOK_RUN_START:
            self.hook_run_start(text if text and text not in PYALPM_PLACEHOLDERS else "")
        elif ev == EV_HOOK_RUN_DONE:
            self.hook_run_done()
        elif ev == EV_HOOK_DONE:
            if self.hook_when and self.hook_pos and self.ui.ph and self.ui.ph["name"] in ("hooks", "prepare"):
                self.ui.progress(1.0, f"{self.hook_pos}/{self.hook_pos}")
            self.hook_when = None
            self.hook_running = False
        elif ev == EV_SCRIPTLET_INFO and text.strip() and text not in PYALPM_PLACEHOLDERS:
            self.scriptlet.append(text.rstrip())
            if self.ui.verbose and not self.ui.machine:
                self.ui.write(self.ui.dim("  " + text.rstrip()))
            self.ui.compat(text.rstrip())
        elif ev == EV_PACNEW_CREATED:
            self.pacnew += 1

    # hooky: jedna radka "Dokoncuji 3/12 · Updating linux initcpios" (pred transakci "Pripravuji")
    def hook_start(self, when):
        phase = "prepare" if when == "pre" else "hooks"
        if self.ui.ph is None or self.ui.ph["name"] != phase:
            self.ui.phase(phase)
            self.ui.compat(":: Running pre-transaction hooks..." if when == "pre"
                           else ":: Running post-transaction hooks...")
        self.hook_when = when
        self.hook_pos = self.hook_next = 0
        self.hook_cur = None
        self.hook_last = ""
        self.hook_running = False
        try:
            self.hook_list = self.hooks.run(when) if self.hooks else []
        except Exception:  # noqa: BLE001 - odhad nesmi zastavit transakci
            self.hook_list = []

    def hook_total(self):
        return max(self.hook_pos, self.hook_pos + len(self.hook_list) - self.hook_next, 1)

    def hook_draw(self, frac):
        label = hook_label(self.hook_cur)
        self.ui.progress(frac, f"{self.hook_pos}/{self.hook_total()}" + (f" · {label}" if label else ""))

    def hook_run_start(self, text=""):
        if not self.hook_when:
            self.hook_start("pre" if self.mode == "commit" and self.current is None else "post")
        self.hook_pos += 1
        self.hook_running = True
        if isinstance(self.hook_cur, dict):
            self.hook_last = self.hook_cur["name"]
        self.hook_cur = None
        if self.hook_next < len(self.hook_list):
            self.hook_cur = self.hook_list[self.hook_next]
            self.hook_next += 1
        if text:                        # pyalpm, ktery posila popis hooku
            self.hook_cur = text
        self.hook_draw((self.hook_pos - 1) / self.hook_total())

    def hook_run_done(self):
        if not self.hook_when:
            return
        self.hook_running = False
        self.hook_draw(self.hook_pos / self.hook_total())

    def hook_executing(self, cmd):
        """libalpm loguje 'executing "<Exec>"' tesne pred spustenim hooku - oprava odhadu."""
        if not self.hook_running or not self.hook_when or isinstance(self.hook_cur, str):
            return
        cur = self.hook_cur
        if cur is not None and cur["exec"] == cmd:
            return
        start = self.hook_next - 1 if cur is not None else self.hook_next
        for j in range(max(start, 0), len(self.hook_list)):
            if self.hook_list[j]["exec"] == cmd:
                # odhadnute hooky pred nim se nespusti
                self.hook_cur = self.hook_list[j]
                self.hook_next = j + 1
                self.hook_draw((self.hook_pos - 1) / self.hook_total())
                return
        # hook mimo odhad: odhadnuty hook teprve pobezi, nazev podle vsech hooku teto faze
        if cur is not None:
            self.hook_next -= 1
        after = self.hook_last
        cands = [h for h in (self.hooks.all(self.hook_when) if self.hooks else []) if h["exec"] == cmd]
        self.hook_cur = next((h for h in cands if h["name"] > after), cands[0] if cands else None)
        self.hook_draw((self.hook_pos - 1) / self.hook_total())

    def log(self, *args):
        if len(args) < 2:
            return
        level, msg = args[0], str(args[1]).rstrip()
        if not msg:
            return
        if level == LOG_DEBUG:
            if self.hook_running and msg.startswith("executing"):
                m = EXECUTING_RE.match(msg)
                if m:
                    self.hook_executing(m.group(1))
            return
        if level == LOG_ERROR:
            self.log_errors.append(msg)
            self.ui.compat(f"error: {msg}")
            m = re.search(r"failed retrieving file '[^']*' from (\S+?)\s*:", msg)
            if m and m.group(1) not in self.hosts and not self.ui.machine:
                self.hosts.add(m.group(1))
                self.ui.write(self.ui.dim("  ↻ " + _("Server %s is not responding, trying another one…") % m.group(1)),
                              err=True)
        elif level == LOG_WARNING:
            self.log_warnings.append(msg)
            self.ui.compat(f"warning: {msg}")
            if ".luxnew" in msg or ".pacnew" in msg:     # .pacnew: jadro pred LuxOS 1.0
                self.pacnew += 1
            if self.ui.verbose and not self.ui.machine:
                self.ui.write(self.ui.yellow("! ") + msg, err=True)

    def question(self, *args):
        """Otazky libalpm. S -y (a ve strojovem rezimu) odpovi jako pacman --noconfirm."""
        q = next((a for a in args if isinstance(a, int)), 0)
        text = " ".join(str(a) for a in args if isinstance(a, str))
        if q == Q_CORRUPTED_PKG:
            # poskozeny soubor v mezipameti se vzdy smaze (bez otazky) a stahne znovu - viz _transaction
            for a in args:
                if isinstance(a, (str, bytes)):
                    a = a.decode(errors="replace") if isinstance(a, bytes) else a
                    if ".pkg.tar" in a and a not in self.corrupted:
                        self.corrupted.append(a)
            return 1
        defaults = {Q_INSTALL_IGNOREPKG: True, Q_REPLACE_PKG: True, Q_CONFLICT_PKG: False,
                    Q_CORRUPTED_PKG: True, Q_REMOVE_PKGS: False, Q_SELECT_PROVIDER: 0, Q_IMPORT_KEY: True}
        default = defaults.get(q, False)
        if q == Q_SELECT_PROVIDER:
            return 0
        if self.ui.yes or self.ui.machine or not _isatty(self.ui.inp):
            return int(default)
        prompts = {Q_REPLACE_PKG: _("Replace a package with its successor?"),
                   Q_CONFLICT_PKG: _("Remove a conflicting package?"),
                   Q_CORRUPTED_PKG: _("Delete the damaged downloaded package?"),
                   Q_IMPORT_KEY: _("Import the missing signing key?"),
                   Q_INSTALL_IGNOREPKG: _("Install a package from IgnorePkg anyway?")}
        p = prompts.get(q)
        if not p:
            return int(default)
        try:
            return int(self.ui.ask(p + (f" ({text})" if text else ""), default))
        except LuxError:
            return int(default)


# ---- relace nad libalpm -------------------------------------------------------------------------
class Lux:
    def __init__(self, ui, api=None, conf=None):
        self.ui = ui
        self.api = api
        self.conf = conf
        self._h = None
        self.cb = Callbacks(ui)
        self.trans = None
        self.interrupted = False
        self.extra = {}

    @property
    def h(self):
        if self._h is None:
            if self.api is None:
                self.api = import_pyalpm()
            if self.conf is None:
                self.conf = load_engine_conf()
            self._h, self.extra = build_handle(self.api, self.conf)
            # libalpm 13+ hlasi stahovani udalostmi (soubor, udalost, data); pyalpm 0.12 misto dat
            # posila ukazatel, takze se nesmi brat jako (soubor, stazeno, celkem)
            try:
                self.cb.dl_events = int(str(self.api.alpmversion()).split(".")[0]) >= 13
            except (AttributeError, ValueError, TypeError):
                self.cb.dl_events = False
            for attr, fn in (("dlcb", self.cb.dl), ("progresscb", self.cb.progress), ("eventcb", self.cb.event),
                             ("logcb", self.cb.log), ("questioncb", self.cb.question)):
                _try_set(self._h, attr, fn)
        return self._h

    def check_callbacks(self):
        """Bez questioncb by libalpm odpovidal "ne" i tam, kde pacman --noconfirm rika "ano" (nahrazeni
        balicku, import klice) - to by se chovalo jinak nez pacman."""
        h = self.h
        for attr in ("questioncb", "dlcb", "progresscb", "logcb", "eventcb"):
            try:
                getattr(h, attr)
            except AttributeError:
                raise LuxError("config", f"pyalpm has no {attr}", rc=EXIT_UNAVAILABLE)

    @property
    def localdb(self):
        return self.h.get_localdb()

    def syncdbs(self, usage=None):
        dbs = list(self.h.get_syncdbs())
        if usage and self.conf is not None:
            allowed = {r["name"] for r in self.conf.repos if usage in r.get("_usage", {"Sync", "Search", "Install",
                                                                                       "Upgrade"})}
            dbs = [d for d in dbs if d.name in allowed]
        return dbs

    def need_root(self):
        if os.geteuid() != 0 and not os.environ.get("LUX_ALLOW_NONROOT"):
            raise LuxError("permission", _("This needs administrator rights."))

    # -- obnoveni databazi
    def refresh(self, force=False, attempts=3):
        self.need_root()
        self.wait_for_lock()
        dbs = self.syncdbs("Sync")
        refetch = set()
        for attempt in range(1, attempts + 1):
            self.cb.reset("refresh")
            self.ui.phase("refresh", ", ".join(d.name for d in dbs))
            failed = []
            for i, db in enumerate(dbs):
                self.ui.progress(i / max(1, len(dbs)), db.name)
                try:
                    db.update(force or db.name in refetch)
                except self.api.error as e:
                    msg, _n, det = alpm_error_parts(e)
                    failed.append((db.name, msg, det))
                if self.interrupted:
                    raise LuxError("interrupted", _("Cancelled"), rc=130)
            if not failed:
                self.ui.phase_done(True, ", ".join(d.name for d in dbs))
                return
            text = "\n".join(f"{n}: {m}" for n, m, _d in failed) + "\n" + "\n".join(self.cb.log_errors)
            kind = classify(text)
            if kind == "unknown":
                # libalpm hlasi jen "unable to update database": zamek pozna podle souboru, jinak se
                # opakuje jako sit, ale zprava rika skutecny duvod
                kind = "locked" if os.path.exists(self.lock_path()) else "refresh"
            self.ui.phase_done(False)
            for n, m, _d in failed:
                self.ui.compat(f"error: failed to update {n} ({m})")
            self.ui.compat("error: failed to synchronize all databases")
            # Podpis nesedi k databazi (napr. databaze z ISO novejsi nez na serveru: server vrati
            # "nezmeneno" pro databazi, ale podpis se stahne novy): jednou stahnout nacisto
            if kind == "keyring" and not refetch and attempt < attempts:
                refetch = {n for n, _m, _d in failed}
            elif kind not in ("network", "refresh") or attempt == attempts:
                detail = (self.cb.log_errors or [failed[0][1]])[0] if kind == "refresh" else ""
                raise LuxError(kind, plain_message(kind, detail),
                               [f"{n}: {m}" for n, m, _d in failed] + self.cb.log_errors)
            self.retry_notice(attempt + 1, attempts)

    def lock_path(self):
        try:
            dbpath = self.h.dbpath
        except AttributeError:
            dbpath = (self.conf.get("DBPath") if self.conf is not None else None) or DEFAULT_DBPATH
        return os.path.join(dbpath, "db.lck")

    def wait_for_lock(self):
        """Zamcena databaze: pocka, az jina aktualizace (LuxOS Care, Obchod...) skonci; zamek po
        prerusene operaci (zadny spravce baliku nebezi) odstrani - jinak by libalpm hlasil jen
        "unable to update database" a vypadalo by to jako chyba site."""
        lock = self.lock_path()
        deadline = time.time() + LOCK_WAIT
        waiting = False
        while os.path.exists(lock):
            procs = running_package_managers()
            if not procs:
                try:
                    os.unlink(lock)
                except FileNotFoundError:
                    return
                except OSError as e:
                    raise LuxError("locked", plain_message("locked"), [f"{lock}: {e}"])
                self.ui.note(_("Removed a stale database lock left by an interrupted update."))
                return
            if time.time() > deadline:
                raise LuxError("locked", plain_message("locked", ", ".join(procs)), [lock])
            if not waiting:
                waiting = True
                self.ui.emit("WAIT", ",".join(procs))
                self.ui.say(_("Waiting for another update to finish (%s)…") % ", ".join(procs))
            if self.interrupted:
                raise LuxError("interrupted", _("Cancelled"), rc=130)
            time.sleep(1)

    def retry_notice(self, attempt, attempts):
        self.ui.emit("RETRY", attempt)
        if not self.ui.machine:
            self.ui.write(self.ui.yellow("↻ ") + _("Download failed, trying again (%s/3)…") % attempt)
        time.sleep(float(os.environ.get("LUX_RETRY_DELAY", "2")))

    # -- hledani cilu
    def find_sync(self, target, usage="Install"):
        """Balicky pro cil: nazev, repo/nazev, skupina nebo provides (poradi repozitaru jako pacman)."""
        dbs = self.syncdbs(usage)
        if "/" in target and not target.startswith("/"):
            repo, name = target.split("/", 1)
            for db in dbs:
                if db.name == repo:
                    p = db.get_pkg(name)
                    return [p] if p else []
            return []
        for db in dbs:
            p = db.get_pkg(target)
            if p:
                return [p]
        name = re.split(r"[<>=]", target, 1)[0]
        if name == target:
            for db in dbs:
                grp = db.read_grp(target) if hasattr(db, "read_grp") else None
                if grp:
                    return list(grp[1] if isinstance(grp, tuple) else grp)
        for db in dbs:
            p = self.api.find_satisfier(db.pkgcache, target)
            if p:
                return [p]
        return []

    def load_file(self, path):
        self.h  # nacte konfiguraci (self.extra)
        sig = self.extra.get("local_siglevel")
        try:
            if sig is not None:
                return self.h.load_pkg(path, sig)
            return self.h.load_pkg(path)
        except TypeError:
            return self.h.load_pkg(path)
        except self.api.error as e:
            msg, _n, det = alpm_error_parts(e)
            kind = classify(msg)
            raise LuxError(kind if kind != "unknown" else "notfound", plain_message(kind, path)
                           if kind not in ("unknown", "notfound") else _("Cannot read package file %s") % path,
                           [f"error: {msg}"] + det)

    # -- graficke ovladace jako zavislosti
    def hw_packages(self):
        """Baliky doporucene detekci hardwaru (prazdne, kdyz detekce chybi)."""
        try:
            r = subprocess.run(["luxos-hwdetect", "--packages"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return []
        return r.stdout.split() if r.returncode == 0 else []

    def better_gpu_providers(self, add, to_add):
        """Kdyz zavislost typu vulkan-driver vybrala ovladac NVIDIA (prvni poskytovatel v [luxos]),
        ktery k tomuto hardwaru nepatri, vrati vhodnejsi poskytovatele. Jinak prazdny seznam."""
        asked = {p.name for p in add}
        local = self.localdb
        pulled = [p for p in to_add if GPU_VENDOR_PKG.match(p.name)
                  and p.name not in asked and local.get_pkg(p.name) is None]
        if not pulled:
            return []
        hw = self.hw_packages()
        if any(p.name in hw for p in pulled):
            return []
        dbs = self.syncdbs("Install")
        planned = {p.name for p in to_add}
        # doporucene baliky maji prednost, vcetne 32bit variant (multilib se mohl zapnout az ted)
        prefer = hw + ["lib32-" + n for n in hw if not n.startswith("lib32-")]
        extra = []
        for p in pulled:
            for prov in p.provides:
                virt = re.split(r"[<>=]", prov, 1)[0]
                if not virt.endswith("-driver"):
                    continue
                for name in prefer + GPU_FALLBACK.get(virt, []):
                    if name in planned:
                        continue
                    cand = next((db.get_pkg(name) for db in dbs if db.get_pkg(name)), None)
                    if cand is None:
                        continue
                    if name == virt or any(re.split(r"[<>=]", x, 1)[0] == virt for x in cand.provides):
                        extra.append(cand)
                        planned.add(name)
                        break
        return extra

    # -- transakce
    def transaction(self, action, add=(), remove=(), sysupgrade=False, flags=None, explicit=(), attempts=3):
        """Jedna transakce jako pacman: init -> cile -> prepare -> otazka -> commit. Pri chybe site se
        cela transakce zopakuje (az 3x, bez nove otazky). Vraci pocet zmenenych balicku."""
        self.need_root()
        flags = dict(flags or {})
        confirmed = False
        add = list(add)
        check_gpu = True
        attempt = 1
        corrupt_retried = []
        while True:
            try:
                return self._transaction(action, add, remove, sysupgrade, flags, explicit, confirmed, check_gpu)
            except _RetryCorrupt as r:
                # poskozeny balik v mezipameti: libalpm ho smazal, jednou stahnout znovu
                confirmed = True
                names = [n for n in (r.names or corrupt_retried) if n != "?"]
                if corrupt_retried:
                    if names:
                        msg = _("The package %s was damaged again after a new download. "
                                "The server may be updating it - try again later.") % ", ".join(names)
                    else:
                        msg = _("A downloaded package was damaged again after a new download. "
                                "The server may be updating it - try again later.")
                    raise LuxError("corrupt", msg, r.error.details)
                corrupt_retried = names or ["?"]
                self.ui.emit("RETRY", "corrupt")
                if not self.ui.machine:
                    self.ui.write(self.ui.yellow("↻ ") + (
                        _("Downloaded package %s was damaged, downloading it again…") % ", ".join(names) if names
                        else _("A downloaded package was damaged, downloading it again…")))
                continue
            except _Reprovide as r:
                # jen jednou a nepocita se mezi opakovani pri chybe site
                check_gpu = False
                add += r.extra
                continue
            except _Retry as r:
                confirmed = True
                if attempt == attempts:
                    raise r.error
                attempt += 1
                self.retry_notice(attempt, attempts)

    def _transaction(self, action, add, remove, sysupgrade, flags, explicit, confirmed, check_gpu=False):
        h = self.h
        api, ui = self.api, self.ui
        self.cb.reset()
        self.wait_for_lock()
        try:
            t = h.init_transaction(**flags)
        except api.error as e:
            msg, _n, det = alpm_error_parts(e)
            ui.compat(f"error: failed to init transaction ({msg})")
            kind = classify(msg)
            raise LuxError(kind, plain_message(kind), [msg] + det)
        self.trans = t
        try:
            try:
                if sysupgrade:
                    t.sysupgrade(False)
                for p in add:
                    t.add_pkg(p)
                for p in remove:
                    t.remove_pkg(p)
                t.prepare()
            except api.error as e:
                msg, _n, det = alpm_error_parts(e)
                ui.compat(f"error: failed to prepare transaction ({msg})")
                for d in det:
                    ui.compat(f":: {d}")
                kind = classify(msg + "\n" + "\n".join(det))
                if kind == "unknown" and "target" in msg:
                    kind = "notfound"
                # ALPM_ERR_DB_INVALID / DB_INVALID_SIG: seznam baliku nesedi k podpisu (pyalpm hlasi
                # jen "transaction preparation failed")
                if kind == "unknown" and _n in (16, 17):
                    kind = "dbinvalid"
                detail = ", ".join(det[:5]) if kind == "deps" else ""
                raise LuxError(kind, plain_message(kind, detail), [msg] + det + self.cb.log_errors)
            to_add = list(t.to_add)
            to_remove = list(t.to_remove)
            if not to_add and not to_remove:
                return 0
            if check_gpu:
                extra = self.better_gpu_providers(add, to_add)
                if extra:
                    raise _Reprovide(extra)
            plan = self.plan(to_add, to_remove)
            if not confirmed:
                self.show_plan(action, plan, to_add, to_remove)
                if action == "remove":
                    self.check_holdpkg(to_remove)
                if not ui.ask(plan_question(action, plan["count"], plan["download"], plan["delta"])):
                    raise LuxError("cancelled", _("Cancelled"))
            self.cb.reset("commit", plan["download"], plan["ops"], plan.get("sizes"),
                          list(getattr(self.h, "cachedirs", None) or []), self.hook_plan(to_add, to_remove))
            start = time.time()
            try:
                with system_writable(flags):
                    t.commit()
            except api.error as e:
                msg, _n, det = alpm_error_parts(e)
                ui.phase_done(False)
                ui.compat(f"error: failed to commit transaction ({msg})")
                for d in det:
                    ui.compat(d)
                text = "\n".join([msg] + det + self.cb.log_errors)
                kind = classify(text)
                if self.interrupted:
                    raise LuxError("interrupted", _("Cancelled"), [msg] + det, rc=130)
                # 404: zrcadlo uz tuto verzi nema (seznam baliku je starsi nez server) - opakovani
                # nepomuze a "zkontrolujte internet" by bylo zavadejici
                if kind == "network" and stale_download(text):
                    kind = "outdated"
                err = LuxError(kind, plain_message(kind), [msg] + det + self.cb.log_errors)
                # sit: nic se jeste neinstalovalo (stahuje se pred instalaci) -> zopakovat
                if kind == "network" and self.cb.current is None:
                    raise _Retry(err)
                # poskozeny balik z mezipameti (kontrola probiha pred instalaci): smazat a stahnout znovu
                if kind == "corrupt" and self.cb.current is None:
                    for f in self.cb.corrupted:
                        try:
                            os.unlink(f)
                        except OSError:
                            pass
                    raise _RetryCorrupt(err, sorted({package_from_file(f) for f in self.cb.corrupted}))
                raise err
            ui.phase_done(True)
            self.summary(action, plan, to_add, to_remove, explicit, time.time() - start, flags)
            return plan["count"]
        finally:
            self.trans = None
            try:
                t.release()
            except Exception:  # noqa: BLE001 - uvolneni nesmi prekryt puvodni chybu
                pass

    def hook_plan(self, to_add, to_remove):
        """Odhad hooku transakce (HookPlan); None, kdyz ho nejde sestavit."""
        try:
            h = self.h
            local = self.localdb
            dirs = [d for d in (getattr(h, "hookdirs", None) or []) if d]
            if not any(os.path.normpath(d) == os.path.normpath(HOOK_SYSDIR) for d in dirs):
                dirs.insert(0, HOOK_SYSDIR)
            installs, upgrades, removes = {}, {}, {}
            for p in to_add:
                old = local.get_pkg(p.name)
                if old is None:
                    installs[p.name] = p.version
                else:
                    upgrades[p.name] = (old.version, p.version)
            for p in to_remove:
                if p.name not in installs and p.name not in upgrades:
                    removes[p.name] = p.version
            dbpath = getattr(h, "dbpath", None) or DEFAULT_DBPATH
            return HookPlan.load(dirs, dbpath, installs, upgrades, removes, getattr(h, "root", "/") or "/")
        except Exception:  # noqa: BLE001 - jen prubeh, transakce pokracuje i bez odhadu
            return None

    def plan(self, to_add, to_remove):
        local = self.localdb
        ops, download, delta, sizes = {}, 0, 0, {}
        for p in to_add:
            old = local.get_pkg(p.name)
            download += int(getattr(p, "download_size", 0) or 0)
            if getattr(p, "filename", None) and getattr(p, "download_size", 0):
                sizes[p.filename] = int(p.download_size)
            delta += int(getattr(p, "isize", 0) or 0)
            if old is None:
                ops[p.name] = "installing"
            else:
                delta -= int(getattr(old, "isize", 0) or 0)
                c = self.api.vercmp(p.version, old.version)
                ops[p.name] = "upgrading" if c > 0 else "downgrading" if c < 0 else "reinstalling"
        add_names = {p.name for p in to_add}
        for p in to_remove:
            if p.name not in add_names:
                ops[p.name] = "removing"
            delta -= int(getattr(p, "isize", 0) or 0)
        return {"ops": ops, "download": download, "delta": delta, "count": len(ops), "sizes": sizes}

    def show_plan(self, action, plan, to_add, to_remove):
        ui = self.ui
        ui.emit("PLAN", action, plan["count"], plan["download"], plan["delta"])
        ui.compat(f"Packages ({len(to_add) or len(to_remove)}) " +
                  " ".join(f"{p.name}-{p.version}" for p in (to_add or to_remove)))
        if ui.machine:
            return
        add_names = {p.name for p in to_add}
        removed = [p for p in to_remove if p.name not in add_names]
        if ui.verbose:
            for p in to_add:
                old = self.localdb.get_pkg(p.name)
                ver = f"{old.version} → {p.version}" if old else p.version
                db = getattr(getattr(p, "db", None), "name", "")
                ui.write(f"  {p.name} {ui.dim(ver)} {ui.dim(db)}  {ui.dim(fmt_size(getattr(p, 'download_size', 0)))}")
            for p in removed:
                ui.write(f"  {ui.red('-')} {p.name} {ui.dim(p.version)}")
        elif action in ("upgrade", "remove", "download") or (removed and action != "remove"):
            names = [p.name for p in (to_add if action in ("upgrade", "download") else [])] + \
                    [p.name for p in removed]
            ui.write(ui.dim(self.short_list(names)))
        if removed and action not in ("remove",):
            ui.warn(_("Also removes: %s") % ", ".join(p.name for p in removed))
        if getattr(ui, "datasaver", False) and plan["download"]:
            ui.note(_("Data Saver is on - this downloads %s.") % fmt_size(plan["download"]))

    @staticmethod
    def short_list(names, width=None):
        width = width or max(40, shutil.get_terminal_size((80, 24)).columns - 4)
        out, used = [], 0
        for i, n in enumerate(names):
            if used + len(n) + 2 > width * 2 and i < len(names):
                return "  " + ", ".join(out) + ", " + _("+%d more") % (len(names) - i)
            out.append(n)
            used += len(n) + 2
        return "  " + ", ".join(out)

    def check_holdpkg(self, to_remove):
        held = set(self.conf.list("HoldPkg")) if self.conf else set()
        hit = [p.name for p in to_remove if p.name in held]
        if hit:
            self.ui.warn(_("These packages are essential for the system: %s") % ", ".join(hit))
            # jako pacman: s -y (--noconfirm) plati vychozi odpoved "ne"
            ok = False
            if not self.ui.yes and not self.ui.machine and _isatty(self.ui.inp):
                ok = self.ui.ask(_("Remove them anyway?"), default=False)
            if not ok:
                raise LuxError("cancelled", _("Cancelled"))

    def summary(self, action, plan, to_add, to_remove, explicit, seconds, flags):
        ui = self.ui
        names = set(explicit)
        pool = to_add if action != "remove" else to_remove
        if action == "upgrade":
            exp, ndeps = [], plan["count"]
        else:
            exp = [(p.name, p.version) for p in pool if p.name in names]
            ndeps = len([p for p in pool if p.name not in names])
        if flags.get("downloadonly"):
            action = "download"
        line = summary_line(action, exp, ndeps, seconds)
        ui.ok(line)
        ui.emit("SUMMARY", action, plan["count"], plan["download"], plan["delta"], f"{seconds:.1f}")
        if self.cb.pacnew:
            ui.warn(_("New config files to review: %d (run: lux configs)") % self.cb.pacnew)
        if self.cb.scriptlet and not ui.verbose and not ui.machine:
            for line in self.cb.scriptlet[:5]:
                ui.note("  " + line.strip())
            if len(self.cb.scriptlet) > 5:
                ui.note("  " + _("+%d more") % (len(self.cb.scriptlet) - 5) + " (--verbose)")

    # -- signaly: Ctrl+C behem instalace nepreruzi rozdelany balik
    def install_signals(self):
        def handler(signum, _frame):
            # behem commit: libalpm dokonci rozdelany balik a skonci (stahovani preruseni sam)
            if self.trans is not None and self.cb.mode == "commit":
                self.interrupted = True
                try:
                    self.trans.interrupt()
                except Exception:  # noqa: BLE001
                    pass
                if not self.ui.machine:
                    self.ui.write(self.ui.yellow("! ") + _("Stopping after the current package…"), err=True)
                return
            raise KeyboardInterrupt
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(s, handler)
            except (ValueError, OSError):
                pass


# Ovladace NVIDIA, ktere libalpm vybere jako prvniho poskytovatele vulkan-driver apod.
GPU_VENDOR_PKG = re.compile(r"^(lib32-)?(opencl-)?nvidia(-\d+xx)?(-utils|-dkms|-open.*)?$")
# Nahradni poskytovatele, kdyz detekce hardwaru nic vhodneho nedoporuci (napr. ve VM)
GPU_FALLBACK = {
    "vulkan-driver": ["vulkan-swrast"],
    "lib32-vulkan-driver": ["lib32-vulkan-swrast"],
    "opengl-driver": ["mesa"],
    "lib32-opengl-driver": ["lib32-mesa"],
    "opencl-driver": ["opencl-mesa"],
    "lib32-opencl-driver": ["lib32-opencl-mesa"],
}


class _Reprovide(Exception):
    """Transakce si vybrala nevhodny graficky ovladac -> zopakovat s lepsimi poskytovateli."""
    def __init__(self, extra):
        super().__init__("reprovide")
        self.extra = extra


def package_from_file(path):
    """/var/cache/lux/pkg/firefox-132.0-1-x86_64.pkg.tar.zst -> firefox"""
    base = os.path.basename(path)
    base = re.sub(r"\.pkg\.tar(\.[a-z0-9]+)?(\.sig)?$", "", base)
    parts = base.rsplit("-", 3)
    return parts[0] if len(parts) == 4 else base


class _RetryCorrupt(Exception):
    def __init__(self, error, names):
        super().__init__(error.message)
        self.error = error
        self.names = names


class _Retry(Exception):
    def __init__(self, error):
        super().__init__(error.message)
        self.error = error


def import_pyalpm():
    try:
        import pyalpm
    except ImportError:
        raise LuxError("config", "pyalpm is not installed", rc=EXIT_UNAVAILABLE)
    return pyalpm


# ---- prikazy ----------------------------------------------------------------------------------
KEYRINGS = ("archlinux-keyring", "luxos-keyring")
PKGFILE = re.compile(r"\.pkg\.tar(\.(zst|xz|gz|bz2|lz4|lzo|lrz|Z))?$")


def cmd_available(lux, args):
    lux.h
    lux.check_callbacks()
    if args.verbose:
        h = lux.h
        for attr in ("root", "dbpath", "gpgdir", "logfile", "cachedirs", "hookdirs", "arch", "architectures",
                     "ignorepkgs", "noupgrades", "checkspace", "parallel_downloads"):
            try:
                lux.ui.write(f"{attr}: {getattr(h, attr)}")
            except AttributeError:
                lux.ui.write(f"{attr}: (not exposed by pyalpm)")
        for db in h.get_syncdbs():
            lux.ui.write(f"[{db.name}] siglevel={getattr(db, 'siglevel', '?')} servers={list(db.servers)[:1]}…")
        lux.ui.write(f"siglevel={lux.extra.get('siglevel')} localfile={lux.extra.get('local_siglevel')}")
        for n in lux.extra.get("notes", []):
            lux.ui.write(f"note: {n}")
    lux.ui.write("ok")
    return 0


def cmd_sync(lux, args):
    lux.refresh(force=args.force)
    return 0


def resolve_targets(lux, targets, needed):
    """-> (balicky k pridani, nazvy cilu, nenalezene)."""
    pkgs, names, missing, skipped = [], [], [], []
    local = lux.localdb
    for t in targets:
        if PKGFILE.search(t) and os.path.isfile(t):
            p = lux.load_file(os.path.abspath(t))
            found = [p]
        elif "://" in t:
            raise LuxError("usage", _("Installing from a URL is not supported, download the file first: %s") % t)
        else:
            found = lux.find_sync(t)
        if not found:
            missing.append(t)
            continue
        for p in found:
            old = local.get_pkg(p.name)
            if needed and old is not None and lux.api.vercmp(old.version, p.version) == 0:
                skipped.append(p.name)
                continue
            pkgs.append(p)
            names.append(p.name)
    return pkgs, names, missing, skipped


def cmd_install(lux, args):
    if args.refresh:
        lux.refresh()
    pkgs, names, missing, skipped = resolve_targets(lux, args.targets, args.needed)
    if missing:
        lux.ui.compat("error: target not found: " + " ".join(missing))
        raise LuxError("notfound", plain_message("notfound", missing[0]), [f"target not found: {m}" for m in missing])
    if skipped:
        lux.ui.compat(" ".join(f"warning: {n} is up to date -- skipping" for n in skipped))
        lux.ui.ok(_("Already installed: %s") % ", ".join(skipped))
    if not pkgs:
        return 0
    flags = {}
    if args.needed:
        flags["needed"] = True
    if args.asdeps:
        flags["alldeps"] = True
    if args.download_only:
        flags["downloadonly"] = True
    lux.transaction("install", add=pkgs, flags=flags, explicit=names)
    return 0


def cmd_reinstall(lux, args):
    local = lux.localdb
    pkgs, names = [], []
    for t in args.targets:
        if PKGFILE.search(t) and os.path.isfile(t):
            pkgs.append(lux.load_file(os.path.abspath(t)))
            names.append(pkgs[-1].name)
            continue
        old = local.get_pkg(t)
        if old is None:
            raise LuxError("notinstalled", _("Package '%s' is not installed") % t)
        found = [p for p in lux.find_sync(t) if p.name == t and lux.api.vercmp(p.version, old.version) == 0]
        if not found:
            cached = cached_file(lux, t, old.version)
            if not cached:
                raise LuxError("notfound", _("%s %s is not in the repositories or the package cache") % (t, old.version))
            found = [lux.load_file(cached)]
        pkgs += found
        names.append(t)
    lux.transaction("reinstall", add=pkgs, explicit=names)
    return 0


def cached_file(lux, name, version):
    try:
        dirs = list(lux.h.cachedirs or [])
    except AttributeError:
        dirs = []
    dirs = dirs or [DEFAULT_CACHEDIR]
    pat = re.compile(re.escape(f"{name}-{version}-") + r"[a-z0-9_]+\.pkg\.tar\.(zst|xz)$")
    for d in dirs:
        try:
            for f in sorted(os.listdir(d)):
                if pat.fullmatch(f):
                    return os.path.join(d, f)
        except OSError:
            continue
    return None


def cmd_remove(lux, args):
    local = lux.localdb
    pkgs, names, missing = [], [], []
    for t in args.targets:
        p = local.get_pkg(t)
        if p is None:
            grp = local.read_grp(t) if hasattr(local, "read_grp") else None
            members = list(grp[1] if isinstance(grp, tuple) else grp) if grp else []
            if members:
                pkgs += members
                names += [m.name for m in members]
                continue
            missing.append(t)
            continue
        pkgs.append(p)
        names.append(t)
    if missing:
        lux.ui.compat("error: target not found: " + " ".join(missing))
        raise LuxError("notinstalled", _("Package '%s' is not installed") % missing[0])
    # Bez --nosave zustanou zmenene konfiguracni soubory jako *.luxsave (jako pacman -Rs)
    flags = {"recurse": True}
    if args.nosave:
        flags["nosave"] = True
    if args.cascade:
        flags["cascade"] = True
    lux.transaction("remove", remove=pkgs, flags=flags, explicit=names)
    return 0


def orphans(lux):
    """Nepotrebne zavislosti (= pacman -Qdtq): ze zavislosti, nikdo je nevyzaduje ani volitelne."""
    out = []
    for p in lux.localdb.pkgcache:
        if p.reason != getattr(lux.api, "PKG_REASON_DEPEND", 1):
            continue
        if p.compute_requiredby():
            continue
        opt = p.compute_optionalfor() if hasattr(p, "compute_optionalfor") else []
        if opt:
            continue
        out.append(p)
    return out


def cmd_autoremove(lux, args):
    pkgs = orphans(lux)
    if not pkgs:
        lux.ui.ok(_("No unneeded packages"))
        return 0
    lux.transaction("remove", remove=pkgs, flags={"recurse": True, "nosave": True},
                    explicit=[p.name for p in pkgs])
    return 0


def newer_keyrings(lux):
    local = lux.localdb
    out = []
    for k in KEYRINGS:
        old = local.get_pkg(k)
        if old is None:
            continue
        new = lux.api.sync_newversion(old, lux.syncdbs("Upgrade"))
        if new is not None:
            out.append(new)
    return out


def cmd_upgrade(lux, args):
    if args.refresh:
        lux.refresh()
    flags = {"downloadonly": True} if args.download_only else {}
    action = "download" if args.download_only else "upgrade"
    if args.keyring_first and not args.download_only:
        # Nejdrive klice - nejcastejsi pricina selhani aktualizaci v Archu
        keys = newer_keyrings(lux)
        if keys:
            # bez otazky jako drive (pacman -S --needed --noconfirm archlinux-keyring); otazka je az na system
            lux.ui.say(_("Updating signing keys"))
            saved, lux.ui.yes = lux.ui.yes, True
            try:
                lux.transaction("upgrade", add=keys, flags={"needed": True}, explicit=[k.name for k in keys])
            finally:
                lux.ui.yes = saved
    n = lux.transaction(action, sysupgrade=True, flags=flags)
    if not n:
        lux.ui.compat(" there is nothing to do")
        lux.ui.ok(_("System packages are up to date"))
    return 0


def repo_badge(ui, repo):
    if repo == "luxos-apps":
        return ui.accent("✦ LuxOS")
    if repo.startswith("luxos"):
        return ui.accent("✦ " + repo)
    return ui.dim(repo)


def _search_tools():
    """Vzory vyhledavani (^ $ * ? %) z lux_community.py vedle tohoto souboru (spolecne s Flathubem a AUR)."""
    d = os.path.dirname(os.path.abspath(__file__))
    if d not in sys.path:
        sys.path.append(d)
    import lux_community  # noqa: PLC0415
    return lux_community


def cmd_search(lux, args):
    """Obycejna slova: hledani libalpm v nazvu i popisu (jako drive). Vzory (^vim, vim$, *qt*, lib*-git,
    %qt%): jen v nazvu, bez ohledu na velikost pismen. Vic vyrazu = musi platit vsechny."""
    ui = lux.ui
    local = lux.localdb
    lc = _search_tools()
    plain = [t for t in args.terms if not lc.is_pattern(t)]
    rxs = [lc.search_pattern(t) for t in args.terms if lc.is_pattern(t)]
    syncdbs = lux.syncdbs("Search")
    seen, rows = set(), []
    for db in ([local] if args.installed else syncdbs):
        if plain:
            try:
                res = db.search(*plain)
            except lux.api.error:
                res = []
        else:
            res = list(db.pkgcache)
        for p in res:
            if (db.name, p.name) in seen or not all(r.search(p.name) for r in rxs):
                continue
            seen.add((db.name, p.name))
            rows.append((db.name, p))
    q = (" ".join(plain) if plain else lc.search_literal(args.terms)).lower()
    rows.sort(key=lambda r: (r[1].name.lower() != q, not r[1].name.lower().startswith(q)))
    if not rows:
        return 1
    for repo, p in rows:
        if args.installed:
            # nainstalovany balicek: repozitar, ze ktereho je (jinak "local" - AUR, soubor)
            repo = next((d.name for d in syncdbs if d.get_pkg(p.name) is not None), "local")
            inst = p
        else:
            inst = local.get_pkg(p.name)
        mark = ""
        if inst is not None:
            mark = " " + (ui.green("● " + _("installed")) if inst.version == p.version else
                          ui.yellow("● " + _("installed") + f" {inst.version}"))
        if ui.tty or ui.color:
            ui.write(f"{ui.bold(p.name)} {ui.green(p.version)} {repo_badge(ui, repo)}{mark}")
        else:
            ui.write(f"{repo}/{p.name} {p.version}" + (" [installed]" if inst is not None else ""))
        ui.write(f"    {p.desc or ''}")
    return 0


def _fmt_list(v):
    v = list(v or [])
    return "  ".join(str(x) for x in v) if v else "-"


def cmd_info(lux, args):
    ui = lux.ui
    local = lux.localdb.get_pkg(args.package)
    pkg = local
    if pkg is None or args.sync:
        found = lux.find_sync(args.package, usage="Search")
        pkg = found[0] if found else pkg
    if pkg is None:
        return 1
    is_local = pkg is local
    repo = getattr(getattr(pkg, "db", None), "name", "") or "-"
    if is_local:
        for db in lux.syncdbs():
            if db.get_pkg(pkg.name):
                repo = db.name
                break
        else:
            repo = _("not in repositories (AUR or local)")
    rows = [
        (_("Name"), ui.bold(pkg.name)),
        (_("Version"), ui.green(pkg.version)),
        (_("Description"), pkg.desc or ""),
        (_("Repository"), repo),
        (_("URL"), pkg.url or ""),
        (_("License"), _fmt_list(pkg.licenses)),
        (_("Groups"), _fmt_list(pkg.groups)),
        (_("Provides"), _fmt_list(pkg.provides)),
        (_("Depends on"), _fmt_list(pkg.depends)),
        (_("Optional deps"), _fmt_list(pkg.optdepends)),
        (_("Conflicts with"), _fmt_list(pkg.conflicts)),
        (_("Replaces"), _fmt_list(pkg.replaces)),
    ]
    if is_local:
        rows.append((_("Required by"), _fmt_list(pkg.compute_requiredby())))
        rows.append((_("Installed size"), fmt_size(pkg.isize)))
        rows.append((_("Installed"), time.strftime("%Y-%m-%d %H:%M", time.localtime(pkg.installdate))
                     if getattr(pkg, "installdate", 0) else "-"))
        rows.append((_("Install reason"), _("explicitly installed") if pkg.reason == 0 else _("as a dependency")))
        newer = lux.api.sync_newversion(pkg, lux.syncdbs())
        if newer is not None:
            rows.append((_("Update"), ui.yellow(newer.version)))
    else:
        rows.append((_("Download size"), fmt_size(getattr(pkg, "download_size", 0) or getattr(pkg, "size", 0))))
        rows.append((_("Installed size"), fmt_size(pkg.isize)))
        rows.append((_("Installed"), _("no")))
    rows.append((_("Packager"), getattr(pkg, "packager", "") or "-"))
    rows.append((_("Build date"), time.strftime("%Y-%m-%d", time.localtime(pkg.builddate))
                 if getattr(pkg, "builddate", 0) else "-"))
    w = max(len(k) for k, _v in rows)
    for k, v in rows:
        ui.write(f"{ui.dim(k.ljust(w))}  {v}")
    return 0


def cmd_list(lux, args):
    ui = lux.ui
    local = lux.localdb
    plain = not (ui.tty or ui.color)
    rx = re.compile(re.escape(args.pattern), re.I) if args.pattern else None
    if args.mode == "sync":
        # vsechny balicky repozitaru pro TUI lux a Obchod (drive expac -S '%r %n %v %m %d')
        for db in lux.syncdbs("Search"):
            for p in db.pkgcache:
                if rx and not rx.search(p.name):
                    continue
                desc = (p.desc or "").replace("\t", " ").replace("\n", " ")
                ui.write(f"{db.name}\t{p.name}\t{p.version}\t{getattr(p, 'isize', 0) or 0}\t{desc}")
        return 0
    if args.mode == "upgradable":
        dbs = lux.syncdbs("Upgrade")
        n = 0
        for p in sorted(local.pkgcache, key=lambda x: x.name):
            new = lux.api.sync_newversion(p, dbs)
            if new is None or (rx and not rx.search(p.name)):
                continue
            n += 1
            if plain:
                ui.write(f"{p.name} {p.version} -> {new.version}")
            else:
                repo = getattr(getattr(new, "db", None), "name", "")
                ui.write(f"{ui.bold(p.name)} {ui.dim(p.version)} → {ui.green(new.version)} {repo_badge(ui, repo)}")
        return 0
    pkgs = sorted(local.pkgcache, key=lambda x: x.name)
    if args.mode == "explicit":
        pkgs = [p for p in pkgs if p.reason == 0]
    elif args.mode == "foreign":
        sync_names = set()
        for db in lux.syncdbs():
            sync_names.update(x.name for x in db.pkgcache)
        pkgs = [p for p in pkgs if p.name not in sync_names]
    elif args.mode == "orphans":
        pkgs = sorted(orphans(lux), key=lambda x: x.name)
    for p in pkgs:
        if rx and not rx.search(p.name):
            continue
        ui.write(f"{p.name} {p.version}" if plain else f"{p.name} {ui.green(p.version)}")
    return 0


def cmd_files(lux, args):
    p = lux.localdb.get_pkg(args.package)
    if p is None:
        raise LuxError("notinstalled", _("Package '%s' is not installed") % args.package)
    root = lux.conf.get("RootDir", "/") if lux.conf else "/"
    for f in p.files:
        path = f[0] if isinstance(f, (tuple, list)) else f
        lux.ui.write(os.path.join(root, path))
    return 0


def owner_paths(path, root="/"):
    """Absolutni cesta jako u pacman -Qo: adresar se vyhodnoti (symlinky), posledni cast ne;
    holy nazev prikazu se hleda v PATH."""
    if "/" not in path and not os.path.lexists(path):
        found = shutil.which(path)
        if found:
            path = found
    ap = os.path.abspath(path)
    d, base = os.path.split(ap)
    rd = os.path.realpath(d)
    full = os.path.join(rd, base) if base else rd
    rel = os.path.relpath(full, root)
    if os.path.isdir(full) and not os.path.islink(full):
        return rel + "/"
    return rel


def cmd_owns(lux, args):
    ui = lux.ui
    root = lux.conf.get("RootDir", "/") if lux.conf else "/"
    wanted = {}
    for a in args.paths:
        wanted[owner_paths(a, root)] = a
    found = {}
    for p in lux.localdb.pkgcache:
        for f in p.files:
            path = f[0] if isinstance(f, (tuple, list)) else f
            if path in wanted:
                found.setdefault(path, []).append(p)
    rc = 0
    for rel, orig in wanted.items():
        owners = found.get(rel)
        if not owners:
            ui.fail(_("No package owns %s") % orig)
            ui.compat(f"error: No package owns {orig}")
            rc = 1
            continue
        for p in owners:
            ui.write(f"{'/' + rel} {_('is owned by')} {ui.bold(p.name)} {ui.green(p.version)}")
    return rc


def cmd_resolve(lux, args):
    """Pro lux: ktere cile jsou v repozitarich (nazev, repo/nazev, skupina, provides, soubor balicku)."""
    for t in args.targets:
        if PKGFILE.search(t) and os.path.isfile(t):
            lux.ui.write(f"file\t{t}")
        elif lux.find_sync(t):
            lux.ui.write(f"repo\t{t}")
        else:
            lux.ui.write(f"none\t{t}")
    return 0


# ---- prikazova radka --------------------------------------------------------------------------
# ---- kontrola aktualizaci, cache, prechod ---------------------------------------------------------
_CHECK_LOCKS = []   # otevrene zamky kontroly aktualizaci (viz cmd_check_updates)


def check_updates_db(path=None):
    """Docasna databaze pro check-updates (zustava pro dalsi beh a pro vypocet velikosti stahovani)."""
    if path:
        return path
    base = os.environ.get("TMPDIR") or "/tmp"
    return os.path.join(base, f"lux-checkupdates-{os.getuid()}")


def cmd_check_updates(lux, args):
    """Jako checkupdates z pacman-contrib: obnovi databaze repozitaru do docasne kopie (bez zamku
    a bez prav roota), systemova databaze se nemeni. 0 = jsou aktualizace, 2 = nejsou, 1 = chyba."""
    conf = lux.conf if lux.conf is not None else load_engine_conf()
    real = conf.get("DBPath", DEFAULT_DBPATH)
    tmp = check_updates_db(args.db)
    os.makedirs(os.path.join(tmp, "sync"), mode=0o700, exist_ok=True)
    st = os.lstat(tmp)
    if st.st_uid != os.getuid() or os.path.islink(tmp):
        raise LuxError("permission", f"{tmp} does not belong to this user")
    # Obchod, Pece a terminal kontroluji do stejne slozky: dalsi beh pocka na prvni (drive spadl
    # na zamku jadra s hlaskou o internetu). Kdo drzi flock, je jediny uzivatel slozky, takze
    # db.lck je zbytek preruseneho behu a muze se smazat.
    import fcntl
    lockf = open(os.path.join(tmp, ".check-updates.lock"), "a")
    # zamek drzet do konce prikazu (bez odkazu by ho uvolnil uz garbage collector po navratu z funkce;
    # uvolni ho main)
    _CHECK_LOCKS.append(lockf)
    deadline = time.monotonic() + CHECK_UPDATES_WAIT
    while True:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() > deadline:
                raise LuxError("locked", _("Another update check is still running. Try again later."))
            time.sleep(0.5)
    try:
        os.unlink(os.path.join(tmp, "db.lck"))
    except FileNotFoundError:
        pass
    local = os.path.join(tmp, "local")
    if os.path.islink(local) and os.readlink(local) != os.path.join(real, "local"):
        os.unlink(local)
    if not os.path.lexists(local):
        os.symlink(os.path.join(real, "local"), local)
    # posledni stazene databaze systemu jako zaklad (stahuje se jen to, co se zmenilo)
    src = os.path.join(real, "sync")
    try:
        for f in os.listdir(src):
            if not f.endswith(".db"):
                continue
            a, b = os.path.join(src, f), os.path.join(tmp, "sync", f)
            if os.path.isfile(a) and (not os.path.exists(b) or os.path.getmtime(a) > os.path.getmtime(b)):
                # databaze a jeji podpis vzdy spolu: stary podpis k novejsi databazi by neprosel
                # overenim ("signature is invalid") a kontrola aktualizaci v Obchode by selhala
                shutil.copy2(a, b)
                if os.path.isfile(a + ".sig"):
                    shutil.copy2(a + ".sig", b + ".sig")
                elif os.path.exists(b + ".sig"):
                    os.unlink(b + ".sig")
    except OSError:
        pass
    opts = {"DBPath": tmp, "LogFile": "/dev/null"}
    if os.geteuid() != 0:
        # gpgme (overeni podpisu databazi) potrebuje do slozky klicu zapisovat (zamky, trustdb);
        # /etc/lux/keyring patri rootovi -> bezny uzivatel (Obchod) pracuje s kopii verejnych klicu
        gdir = conf.get("GPGDir", "/etc/lux/keyring")
        mine = os.path.join(tmp, "gnupg")
        os.makedirs(mine, mode=0o700, exist_ok=True)
        for f in ("pubring.gpg", "pubring.kbx", "trustdb.gpg", "gpg.conf"):
            a, b = os.path.join(gdir, f), os.path.join(mine, f)
            try:
                if os.path.isfile(a) and (not os.path.exists(b) or os.path.getmtime(a) > os.path.getmtime(b)):
                    shutil.copy2(a, b)
            except OSError:
                pass
        opts["GPGDir"] = mine
    tconf = conf.with_options(opts, drop=("DownloadUser",))
    tl = Lux(lux.ui, api=lux.api, conf=tconf)
    tl.h
    tl.cb.reset("refresh")
    failed = []
    for db in tl.syncdbs("Sync"):
        try:
            db.update(False)
        except tl.api.error:
            # kopie ze systemu nemusi sedet (databaze a podpis z ruznych chvil, prerusena
            # aktualizace): docasnou kopii zahodit a stahnout nacisto
            for suffix in (".db", ".db.sig"):
                try:
                    os.unlink(os.path.join(tmp, "sync", db.name + suffix))
                except OSError:
                    pass
            try:
                db.update(True)
            except tl.api.error as e:
                failed.append(f"{db.name}: {alpm_error_parts(e)[0]}")
    if failed:
        raise LuxError("refresh", _("The package lists could not be refreshed. Check your internet connection and try again."), failed)
    tl.conf = tconf
    dbs = tl.syncdbs("Upgrade")
    n = 0
    for p in sorted(tl.localdb.pkgcache, key=lambda x: x.name):
        new = tl.api.sync_newversion(p, dbs)
        if new is None:
            continue
        n += 1
        lux.ui.write(f"{p.name} {p.version} -> {new.version}")
    return 0 if n else 2


PKG_FILE = re.compile(r"^(?P<name>.+)-(?P<ver>[^-]+-[^-]+)-(?P<arch>[^-]+)\.pkg\.tar(\.[a-z0-9]+)?$")


def cache_plan(files, installed, vercmp, keep, keep_uninstalled):
    """Soubory k odstraneni z cache: u kazdeho balicku nechat `keep` nejnovejsich verzi, u
    odinstalovanych `keep_uninstalled` (jako paccache -rk2 a -ruk0)."""
    groups = {}
    for f in files:
        m = PKG_FILE.match(os.path.basename(f))
        if m:
            groups.setdefault((m["name"], m["arch"]), []).append((m["ver"], f))
    out = []
    import functools
    for (name, _arch), items in groups.items():
        items.sort(key=functools.cmp_to_key(lambda a, b: vercmp(a[0], b[0])), reverse=True)
        n = keep if name in installed else keep_uninstalled
        out += [f for _v, f in items[n:]]
    return sorted(out)


def cmd_clean(lux, args):
    lux.need_root()
    try:
        dirs = list(lux.h.cachedirs or [])
    except AttributeError:
        dirs = []
    dirs = dirs or [DEFAULT_CACHEDIR]
    files = []
    for d in dirs:
        try:
            files += [os.path.join(d, f) for f in os.listdir(d) if PKG_FILE.match(f)]
        except OSError:
            continue
    installed = {p.name for p in lux.localdb.pkgcache}
    remove = cache_plan(files, installed, lux.api.vercmp, args.keep, args.keep_uninstalled)
    freed = 0
    for f in remove:
        for path in (f, f + ".sig"):
            try:
                freed += os.path.getsize(path)
                os.unlink(path)
            except OSError:
                pass
    lux.ui.emit("SUMMARY", "clean", len(remove), 0, -freed, 0)
    if remove:
        lux.ui.ok(_("Removed %d old package files from the cache (%s freed)") % (len(remove), human_size(freed)))
    else:
        lux.ui.ok(_("The package cache is already clean"))
    return 0


def human_size(n):
    for unit in ("B", "kB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def migration_pending(root="/"):
    """Zbytky rozlozeni pacmanu (LuxOS do 0.9.5) - rychla kontrola bez spusteni skriptu."""
    p = lambda rel: os.path.join(root, rel)  # noqa: E731
    return any((os.path.lexists(p("var/lib/pacman")), os.path.lexists(p("etc/pacman.conf")),
                os.path.lexists(p("etc/pacman.conf.pacsave")), os.path.lexists(p("etc/pacman.conf.luxsave")),
                os.path.islink(p("usr/lib/lux/alpm/bin/pacman")),
                os.path.lexists(p("var/log/pacman.log")), os.path.islink(p("var/cache/pacman/pkg"))))


def maybe_migrate(ui, now=False, force=False):
    """Root: dokonci prechod z pacmanu, kdyz ho hook pri aktualizaci nestihl (stary proces jadra,
    instalace s --nohooks...), a po restartu uklidi pozustatky. Zamek: stara cesta /var/lib/pacman/db.lck
    (ji respektuje i pripadny starsi proces), migrace ho presune do /var/lib/lux."""
    if os.geteuid() != 0 or not os.access(MIGRATE, os.X_OK) or not (force or migration_pending()):
        return 0
    if running_package_managers():
        return 0
    lock = None
    if os.path.isdir("/var/lib/pacman") and not os.path.islink("/var/lib/pacman"):
        if os.path.exists("/var/lib/pacman/db.lck") or os.path.exists(DEFAULT_DBPATH + "db.lck"):
            return 0
        try:
            os.close(os.open("/var/lib/pacman/db.lck", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            lock = True
        except OSError:
            return 0
    try:
        r = subprocess.run([MIGRATE, "auto"] + (["--now"] if now else []) + ["--ignore-pid", str(os.getpid())],
                           capture_output=True, text=True, timeout=600)
        for line in (r.stderr or "").splitlines():
            ui.note(line)
        return r.returncode
    except (OSError, subprocess.TimeoutExpired) as e:
        ui.note(f"lux-engine-migrate: {e}")
        return 1
    finally:
        if lock:
            for path in (DEFAULT_DBPATH + "db.lck", "/var/lib/pacman/db.lck"):
                try:
                    os.unlink(path)
                    break
                except OSError:
                    continue


def cmd_migrate(lux, args):
    lux.need_root()
    rc = maybe_migrate(lux.ui, now=args.now, force=True)
    if rc == 0:
        lux.ui.ok(_("The package manager uses /etc/lux and /var/lib/lux"))
    return rc


ROOT_CMDS = {"sync", "install", "reinstall", "remove", "autoremove", "upgrade", "update", "clean"}
TRANSACTION = True      # main(): False pro prikazy bez zmen systemu (hooky se nespousti)


def build_parser():
    p = argparse.ArgumentParser(prog="lux_alpm.py", add_help=True)
    p.add_argument("-y", "--yes", "--noconfirm", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--machine", action="store_true")
    p.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    p.add_argument("--lang", default=None)
    p.add_argument("--datasaver", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("available")
    s.set_defaults(fn=cmd_available)
    s = sub.add_parser("sync")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_sync)
    s = sub.add_parser("install")
    s.add_argument("--needed", action="store_true")
    s.add_argument("--asdeps", action="store_true")
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--download-only", action="store_true")
    s.add_argument("targets", nargs="+")
    s.set_defaults(fn=cmd_install)
    s = sub.add_parser("reinstall")
    s.add_argument("targets", nargs="+")
    s.set_defaults(fn=cmd_reinstall)
    s = sub.add_parser("remove")
    s.add_argument("--cascade", action="store_true")
    s.add_argument("--nosave", action="store_true")
    s.add_argument("targets", nargs="+")
    s.set_defaults(fn=cmd_remove)
    s = sub.add_parser("autoremove")
    s.set_defaults(fn=cmd_autoremove)
    for name in ("upgrade", "update"):
        s = sub.add_parser(name)
        s.add_argument("--refresh", action="store_true", default=name == "update")
        s.add_argument("--download-only", action="store_true")
        s.add_argument("--keyring-first", action="store_true", default=name == "update")
        s.set_defaults(fn=cmd_upgrade)
    s = sub.add_parser("search")
    s.add_argument("--installed", action="store_true")
    s.add_argument("terms", nargs="+")
    s.set_defaults(fn=cmd_search)
    s = sub.add_parser("info")
    s.add_argument("--sync", action="store_true")
    s.add_argument("package")
    s.set_defaults(fn=cmd_info)
    s = sub.add_parser("list")
    g = s.add_mutually_exclusive_group()
    for m in ("installed", "upgradable", "explicit", "foreign", "orphans", "sync"):
        g.add_argument(f"--{m}", dest="mode", action="store_const", const=m)
    s.add_argument("pattern", nargs="?")
    s.set_defaults(fn=cmd_list, mode="installed")
    s = sub.add_parser("files")
    s.add_argument("package")
    s.set_defaults(fn=cmd_files)
    s = sub.add_parser("owns")
    s.add_argument("paths", nargs="+")
    s.set_defaults(fn=cmd_owns)
    s = sub.add_parser("resolve")
    s.add_argument("targets", nargs="+")
    s.set_defaults(fn=cmd_resolve)
    s = sub.add_parser("check-updates")
    s.add_argument("--db", default=None)
    s.set_defaults(fn=cmd_check_updates)
    s = sub.add_parser("clean")
    s.add_argument("--keep", type=int, default=2)
    s.add_argument("--keep-uninstalled", type=int, default=0)
    s.set_defaults(fn=cmd_clean)
    s = sub.add_parser("migrate")
    s.add_argument("--now", action="store_true")
    s.set_defaults(fn=cmd_migrate)
    return p


def main(argv=None, api=None, conf=None, out=None, inp=None):
    os.environ["PATH"] = engine_path(os.environ.get("PATH"))
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if args.lang:
        os.environ["LANG"] = args.lang
        os.environ.pop("LC_ALL", None)
        os.environ.pop("LC_MESSAGES", None)
    ui = UI(color=args.color, machine=args.machine, verbose=args.verbose, yes=args.yes, out=out, inp=inp)
    ui.datasaver = args.datasaver
    lux = Lux(ui, api=api, conf=conf)
    lux.install_signals()
    rc = 0
    if args.cmd in ROOT_CMDS and conf is None:
        maybe_migrate(ui)
    global TRANSACTION
    TRANSACTION = args.cmd in ROOT_CMDS
    try:
        rc = args.fn(lux, args) or 0
    except LuxError as e:
        rc = e.rc
        if ui.ph:
            ui.phase_done(False)
        if e.rc == EXIT_UNAVAILABLE:
            if args.cmd == "available" or args.verbose:
                sys.stderr.write(f"lux: {e.message}\n")
            ui.emit("UNAVAILABLE", e.message)
        else:
            ui.emit("ERROR", e.kind, e.message)
            ui.fail(e.message)
            if e.details and (args.verbose or ui.machine):
                for d in e.details:
                    ui.write(("  " if not ui.machine else "") + str(d), err=True)
            elif e.details and e.kind not in ("cancelled", "notfound", "confirm"):
                # Prvni radky skutecne chyby rovnou (bez nich se neda nic dohledat), zbytek s --verbose
                shown = list(dict.fromkeys(str(d).strip() for d in e.details if str(d).strip()))
                for d in shown[:DETAIL_LINES]:
                    ui.write(ui.dim("  " + d), err=True)
                if len(shown) > DETAIL_LINES:
                    ui.note("  " + _("More details: run the command again with --verbose"))
    except KeyboardInterrupt:
        if ui.ph:
            ui.phase_done(False)
        ui.fail(_("Cancelled"))
        rc = 130
    finally:
        while _CHECK_LOCKS:
            _CHECK_LOCKS.pop().close()
    ui.emit("DONE", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
