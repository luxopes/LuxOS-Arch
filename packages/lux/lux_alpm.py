#!/usr/bin/python3
"""lux_alpm - transakce a dotazy balicku pro lux pres libalpm (pyalpm), bez CLI pacmanu.

Pouziva stejnou databazi (/var/lib/pacman), konfiguraci (/etc/pacman.conf, nactenou pres
pacman-conf - presne jako ji cte pacman), overovani podpisu, cache a hooky jako pacman, takze
lux i pacman spravuji tentyz system. Spousti ho /usr/bin/lux; Obchod LuxOS a LuxOS Care s --machine.

  lux_alpm.py [volby] PRIKAZ [argumenty]

  available                       0 = pyalpm a konfigurace pouzitelne (jinak kod 3: lux pouzije pacman)
  sync [--force]                  obnovi databaze repozitaru                         (root)
  install [--needed] [--asdeps] [--refresh] CIL...  nazev, repo/nazev, skupina, provides, soubor .pkg.tar.*
  reinstall BALIK...              znovu z repozitare, jinak z cache                  (root)
  remove BALIK...                 odebere i nepotrebne zavislosti a zalohy konfigurace (= pacman -Rns)
  autoremove                      odebere nepotrebne zavislosti (= pacman -Rns $(pacman -Qdtq))
  upgrade [--refresh] [--download-only] [--keyring-first]   (update = vse z toho)
  search VYRAZ... | info BALIK | list [--installed|--upgradable|--explicit|--foreign|--orphans] [VZOR]
  files BALIK | owns CESTA... | resolve CIL...

Volby: -y/--yes, -v/--verbose, --machine, --color=auto|always|never, --lang KOD, --datasaver
Navratove kody: 0 ok, 1 chyba, 2 spatne pouziti, 3 pyalpm/konfigurace nelze pouzit, 130 preruseno.
Strojovy vystup (--machine) popisuje /usr/share/doc/lux/lux.md (radky "@@...").
"""
import argparse
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


def classify(text):
    low = (text or "").lower()
    for needle, kind in ERROR_KINDS:
        if needle in low:
            return kind
    return "unknown"


def plain_message(kind, detail=""):
    m = {
        "locked": _("The package database is locked: another package manager is running, "
                    "or a previous one crashed. If nothing else is running: lux fix"),
        "permission": _("This needs administrator rights."),
        "disk": _("Not enough free disk space. Free some space (lux clean) and try again."),
        "conflict": _("Some files of the new packages already exist on the system (file conflict)."),
        "pkgconflict": _("The selected packages conflict with installed packages."),
        "deps": _("Dependencies can not be satisfied: %s") % detail if detail else
        _("Dependencies can not be satisfied."),
        "corrupt": _("A downloaded package is damaged. Try again; if it repeats, run: lux clean"),
        "keyring": _("A package signature could not be verified. Repair the signing keys with: lux fix"),
        "network": _("Some packages could not be downloaded. Check your internet connection and try again."),
        "notfound": _("Package '%s' not found. Try: lux search %s") % (detail, detail) if detail else
        _("Package not found."),
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


# ---- konfigurace pacmanu (pacman-conf = parser pacmanu) ----------------------------------------
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


class PacmanConf:
    """Vystup `pacman-conf` (plne vyhodnoceny pacman.conf vcetne Include)."""

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

    def get(self, key, default=None):
        v = self.options.get(key)
        return v[-1] if v else default

    def list(self, key):
        """Opakovatelna volba; hodnoty oddelene mezerami jako u pacmanu (HoldPkg = pacman glibc)."""
        return [w for v in (self.options.get(key) or []) for w in v.split()]

    def has(self, key):
        return key in self.options


def load_pacman_conf():
    cmd = ["pacman-conf"]
    if os.environ.get("LUX_PACMAN_CONF"):
        cmd += ["--config", os.environ["LUX_PACMAN_CONF"]]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise LuxError("config", f"pacman-conf: {e}", rc=EXIT_UNAVAILABLE)
    if r.returncode != 0:
        raise LuxError("config", "pacman-conf: " + (r.stderr or "").strip(), rc=EXIT_UNAVAILABLE)
    return PacmanConf(r.stdout)


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
    """pyalpm.Handle nastaveny jako pacman. Co pyalpm neumi a v konfiguraci se pouziva, je chyba
    (vyjimka s rc 3) - lux pak radeji pouzije pacman, nez aby se choval jinak."""
    root = conf.get("RootDir", "/")
    dbpath = conf.get("DBPath", "/var/lib/pacman/")
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
            # hooky z /usr/share/libalpm/hooks pridava libalpm sam; HookDir (napr. /etc/pacman.d/hooks)
            # je nutne jen kdyz v nem nejake hooky jsou
            needed = any(glob.glob(os.path.join(root, d.lstrip("/"), "*.hook")) for d in vals)
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
              "install": "Installing", "remove": "Removing", "hooks": "Finishing"}

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
EV_PACNEW_CREATED = 32
EV_HOOK_START = 34
EV_HOOK_RUN_START = 36
# alpm_question_type_t
Q_INSTALL_IGNOREPKG, Q_REPLACE_PKG, Q_CONFLICT_PKG, Q_CORRUPTED_PKG = 1, 2, 4, 8
Q_REMOVE_PKGS, Q_SELECT_PROVIDER, Q_IMPORT_KEY = 16, 32, 64
# alpm_download_event_type_t
DL_INIT, DL_PROGRESS, DL_RETRY, DL_COMPLETED = 0, 1, 2, 3
# pyalpm 0.12 u nekterych udalosti misto skutecneho textu posila jen tyto zastupne retezce
PYALPM_PLACEHOLDERS = ("unknown event", "event not implemented")


class Callbacks:
    """Prevadi callbacky libalpm na jeden radek prubehu na fazi (a strojove radky)."""

    def __init__(self, ui):
        self.ui = ui
        self.reset()

    def reset(self, mode="", dl_total=0, ops=None, sizes=None, cachedirs=None):
        self.mode = mode            # refresh | commit
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
            if self.ui.ph is None or self.ui.ph["name"] != "hooks":
                self.ui.phase("hooks")
                self.ui.compat(":: Running post-transaction hooks...")
        elif ev == EV_HOOK_RUN_START and text and text not in PYALPM_PLACEHOLDERS:
            self.ui.progress(0.5, text)
        elif ev == EV_SCRIPTLET_INFO and text.strip() and text not in PYALPM_PLACEHOLDERS:
            self.scriptlet.append(text.rstrip())
            if self.ui.verbose and not self.ui.machine:
                self.ui.write(self.ui.dim("  " + text.rstrip()))
            self.ui.compat(text.rstrip())
        elif ev == EV_PACNEW_CREATED:
            self.pacnew += 1

    def log(self, *args):
        if len(args) < 2:
            return
        level, msg = args[0], str(args[1]).rstrip()
        if not msg:
            return
        if level == 1:
            self.log_errors.append(msg)
            self.ui.compat(f"error: {msg}")
            m = re.search(r"failed retrieving file '[^']*' from (\S+?)\s*:", msg)
            if m and m.group(1) not in self.hosts and not self.ui.machine:
                self.hosts.add(m.group(1))
                self.ui.write(self.ui.dim("  ↻ " + _("Server %s is not responding, trying another one…") % m.group(1)),
                              err=True)
        elif level == 2:
            self.log_warnings.append(msg)
            self.ui.compat(f"warning: {msg}")
            if ".pacnew" in msg:
                self.pacnew += 1
            if self.ui.verbose and not self.ui.machine:
                self.ui.write(self.ui.yellow("! ") + msg, err=True)

    def question(self, *args):
        """Otazky libalpm. S -y (a ve strojovem rezimu) odpovi jako pacman --noconfirm."""
        q = next((a for a in args if isinstance(a, int)), 0)
        text = " ".join(str(a) for a in args if isinstance(a, str))
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
                self.conf = load_pacman_conf()
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
        dbs = self.syncdbs("Sync")
        for attempt in range(1, attempts + 1):
            self.cb.reset("refresh")
            self.ui.phase("refresh", ", ".join(d.name for d in dbs))
            failed = []
            for i, db in enumerate(dbs):
                self.ui.progress(i / max(1, len(dbs)), db.name)
                try:
                    db.update(force)
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
                kind = "network"
            self.ui.phase_done(False)
            for n, m, _d in failed:
                self.ui.compat(f"error: failed to update {n} ({m})")
            self.ui.compat("error: failed to synchronize all databases")
            if kind != "network" or attempt == attempts:
                raise LuxError(kind, plain_message(kind), [f"{n}: {m}" for n, m, _d in failed] + self.cb.log_errors)
            self.retry_notice(attempt + 1, attempts)

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

    # -- transakce
    def transaction(self, action, add=(), remove=(), sysupgrade=False, flags=None, explicit=(), attempts=3):
        """Jedna transakce jako pacman: init -> cile -> prepare -> otazka -> commit. Pri chybe site se
        cela transakce zopakuje (az 3x, bez nove otazky). Vraci pocet zmenenych balicku."""
        self.need_root()
        flags = dict(flags or {})
        confirmed = False
        for attempt in range(1, attempts + 1):
            try:
                return self._transaction(action, add, remove, sysupgrade, flags, explicit, confirmed)
            except _Retry as r:
                confirmed = True
                if attempt == attempts:
                    raise r.error
                self.retry_notice(attempt + 1, attempts)

    def _transaction(self, action, add, remove, sysupgrade, flags, explicit, confirmed):
        h = self.h
        api, ui = self.api, self.ui
        self.cb.reset()
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
                detail = ", ".join(det[:5]) if kind == "deps" else ""
                raise LuxError(kind, plain_message(kind, detail), [msg] + det + self.cb.log_errors)
            to_add = list(t.to_add)
            to_remove = list(t.to_remove)
            if not to_add and not to_remove:
                return 0
            plan = self.plan(to_add, to_remove)
            if not confirmed:
                self.show_plan(action, plan, to_add, to_remove)
                if action == "remove":
                    self.check_holdpkg(to_remove)
                if not ui.ask(plan_question(action, plan["count"], plan["download"], plan["delta"])):
                    raise LuxError("cancelled", _("Cancelled"))
            self.cb.reset("commit", plan["download"], plan["ops"], plan.get("sizes"),
                          list(getattr(self.h, "cachedirs", None) or []))
            start = time.time()
            try:
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
                err = LuxError(kind, plain_message(kind), [msg] + det + self.cb.log_errors)
                # sit: nic se jeste neinstalovalo (stahuje se pred instalaci) -> zopakovat
                if kind == "network" and self.cb.current is None:
                    raise _Retry(err)
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
            ui.warn(_("New config files to review: %d (run: pacdiff)") % self.cb.pacnew)
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
    dirs = dirs or ["/var/cache/pacman/pkg/"]
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
    flags = {"recurse": True, "nosave": True}
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


def cmd_search(lux, args):
    ui = lux.ui
    local = lux.localdb
    seen, rows = set(), []
    for db in lux.syncdbs("Search"):
        try:
            res = db.search(*args.terms)
        except lux.api.error:
            res = []
        for p in res:
            if (db.name, p.name) in seen:
                continue
            seen.add((db.name, p.name))
            rows.append((db.name, p))
    q = " ".join(args.terms).lower()
    rows.sort(key=lambda r: (r[1].name.lower() != q, not r[1].name.lower().startswith(q)))
    if not rows:
        return 1
    for repo, p in rows:
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
    s.add_argument("terms", nargs="+")
    s.set_defaults(fn=cmd_search)
    s = sub.add_parser("info")
    s.add_argument("--sync", action="store_true")
    s.add_argument("package")
    s.set_defaults(fn=cmd_info)
    s = sub.add_parser("list")
    g = s.add_mutually_exclusive_group()
    for m in ("installed", "upgradable", "explicit", "foreign", "orphans"):
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
    return p


def main(argv=None, api=None, conf=None, out=None, inp=None):
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
                ui.note("  " + _("Details: run the command again with --verbose"))
    except KeyboardInterrupt:
        if ui.ph:
            ui.phase_done(False)
        ui.fail(_("Cancelled"))
        rc = 130
    ui.emit("DONE", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
