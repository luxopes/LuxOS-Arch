#!/usr/bin/python3
"""lux-config - konfigurace spravce baliku LuxOS (/etc/lux/lux.conf) a z ni vygenerovana
konfigurace jadra (/run/lux/engine.conf).

/etc/lux/lux.conf ma vlastni format LuxOS (popis: /usr/share/doc/lux/lux.md):

    # komentar (do konce radku)
    parallel-downloads  10
    hold  linux-firmware
    repo luxos
        server  https://luxos.lux-ai.cz/repo/$repo/$arch
    repo core
        mirrors  /etc/lux/mirrorlist
    include  /etc/lux/conf.d/*.conf

Jadro (lux-engine = libalpm a nastroje z Arch Linuxu) cte syntaxi INI pacmanu. Tu nikdo nepise:
lux-config ji generuje do /run/lux/engine.conf (root, 0644) pokazde, kdyz se lux.conf, vlozene
soubory nebo seznamy zrcadel zmeni (hlavicka "#@source" s casem zmeny a velikosti kazdeho zdroje).
Kazdy vstupni bod (lux, lux_alpm.py, nastroje jadra v /usr/lib/lux/alpm/bin, LuxOS Care...) zavola
ensure() pred spustenim jadra. Rozbita konfigurace: chyba se souborem a radkem, posledni funkcni
engine.conf zustava (lux sam odmitne pokracovat).

  lux-config ensure [-q] [--config F] [--output F]   cesta k pouzitelne konfiguraci jadra
                                                     (0 ok, 2 rozbita lux.conf - posledni funkcni, 1 chyba)
  lux-config check [SOUBOR...]                       kontrola (chyby se souborem a radkem)
  lux-config env                                     nastaveni lux pro shell (AUR=1 ...) + LUX_ENGINE_CONF
  lux-config get KLIC                                hodnota (napr. clean-keep)
  lux-config dump [--config F]                       vygenerovana konfigurace jadra na stdout
  lux-config mirrors-import [SOUBOR|-] [--output F]  seznam zrcadel z reflectoru/pacmanu -> format lux
  lux-config convert-pacman SOUBOR                   stary pacman.conf -> lux.conf na stdout
  lux-config update-servers [--config F]             stara adresa repozitaru LuxOS -> nova (po aktualizaci)
  lux-config enable-repo NAZEV [--mirrors F|--server URL] [--config F]   prida blok repo
  lux-config has-repo NAZEV [--config F]             0 = repozitar je nastaven
"""
import difflib
import glob
import hashlib
import os
import re
import sys
import tempfile

VERSION = "1"
LUX_CONF = "/etc/lux/lux.conf"
ENGINE_CONF = "/run/lux/engine.conf"
# posledni funkcni konfigurace jadra i po restartu (/run je po startu prazdny)
LAST_GOOD = "/var/lib/lux/engine.conf.last-good"
MIRRORLIST = "/etc/lux/mirrorlist"
TEMPLATE = "/usr/share/lux/lux.conf.default"
USER_CONF = "lux/lux.conf"   # v $XDG_CONFIG_HOME: jen nastaveni lux (aur, flatpak...)
MAX_INCLUDE_DEPTH = 10

ON = {"on", "yes", "true", "1"}
OFF = {"off", "no", "false", "0"}
SIG = {  # signatures -> SigLevel pacmanu
    "required": "Required DatabaseOptional",
    "optional": "Optional TrustAll",
    "never": "Never",
}
USAGE = {"sync": "Sync", "search": "Search", "install": "Install", "upgrade": "Upgrade", "all": "All"}

# klic -> (druh, direktiva jadra nebo None, opakovatelny)
GLOBAL_KEYS = {
    "architecture": ("words", "Architecture", False),
    "parallel-downloads": ("int1", "ParallelDownloads", False),
    "signatures": ("sig", "SigLevel", False),
    "local-signatures": ("sig", "LocalFileSigLevel", False),
    "color": ("bool", "Color", False),
    "candy": ("bool", "ILoveCandy", False),
    "check-space": ("bool", "CheckSpace", False),
    "verbose-lists": ("bool", "VerbosePkgLists", False),
    "syslog": ("bool", "UseSyslog", False),
    "download-timeout": ("bool", "DisableDownloadTimeout", False),
    "download-sandbox": ("bool", "DisableSandbox", False),
    "download-user": ("word", "DownloadUser", False),
    "protect": ("words", "HoldPkg", True),
    "hold": ("words", "IgnorePkg", True),
    "ignore-group": ("words", "IgnoreGroup", True),
    "no-upgrade": ("words", "NoUpgrade", True),
    "no-extract": ("words", "NoExtract", True),
    "database": ("path", "DBPath", False),
    "cache": ("path", "CacheDir", True),
    "log": ("path", "LogFile", False),
    "keyring": ("path", "GPGDir", False),
    "hooks": ("path", "HookDir", True),
    # nastaveni samotneho lux (jadro je nevidi)
    "aur": ("bool", None, False),
    "review-pkgbuild": ("bool", None, False),
    "flatpak": ("bool", None, False),
    "clean-keep": ("int0", None, False),
}
REPO_KEYS = {
    "server": ("url", True),
    "mirrors": ("path", True),
    "signatures": ("sig", False),
    "usage": ("usage", False),
}
# vychozi hodnoty (shodne s konfiguraci LuxOS do verze 0.9.5)
DEFAULTS = {
    "architecture": "auto", "parallel-downloads": "10", "signatures": "required", "local-signatures": "optional",
    "color": "on", "candy": "on", "check-space": "on", "verbose-lists": "on", "syslog": "off",
    "download-timeout": "on", "download-sandbox": "on", "download-user": "alpm", "protect": "lux-engine glibc",
    "aur": "on", "review-pkgbuild": "on", "flatpak": "on", "clean-keep": "2",
}
CLI_SHELL = {"aur": "AUR", "review-pkgbuild": "REVIEW_PKGBUILD", "flatpak": "FLATPAK", "clean-keep": "CLEAN_KEEP"}
LEGACY_SHELL = {v: k for k, v in CLI_SHELL.items()}   # lux.conf do LuxOS 0.9.5 (AUR=1 ...)


class ConfigError(Exception):
    def __init__(self, msg, file=None, line=None):
        super().__init__(msg)
        self.msg, self.file, self.line = msg, file, line

    def __str__(self):
        if self.file and self.line:
            return f"{self.file}:{self.line}: {self.msg}"
        if self.file:
            return f"{self.file}: {self.msg}"
        return self.msg


class Repo:
    def __init__(self, name, file, line):
        self.name, self.file, self.line = name, file, line
        self.servers = []          # (url, puvod) - z "server" i ze seznamu zrcadel
        self.mirror_files = []
        self.signatures = None
        self.usage = None


class Config:
    def __init__(self):
        self.values = {}           # klic -> posledni hodnota (neopakovatelne)
        self.lists = {}            # klic -> [hodnoty] (opakovatelne)
        self.repos = []
        self.sources = []          # prectene soubory (pro kontrolu cerstvosti)
        self.globs = []            # (vzor, [soubory]) z include
        self.legacy = False        # obsahuje radky AUR=1 ... (LuxOS do 0.9.5)

    def get(self, key):
        if key in self.values:
            return self.values[key]
        return DEFAULTS.get(key)

    def repo(self, name):
        for r in self.repos:
            if r.name == name:
                return r
        return None


def strip_comment(line):
    """'#' na zacatku nebo po mezere zacina komentar (URL s '#' uprostred zustane)."""
    m = re.search(r"(^|\s)#", line)
    return line[:m.start()] if m else line


def _suggest(word, choices):
    near = difflib.get_close_matches(word, list(choices), n=1, cutoff=0.6)
    return f" (did you mean '{near[0]}'?)" if near else ""


def _check_value(kind, key, val, file, ln):
    words = val.split()
    if not words:
        raise ConfigError(f"'{key}' needs a value", file, ln)
    if kind == "bool":
        if val.lower() not in ON | OFF:
            raise ConfigError(f"'{key}' must be on or off, not '{val}'", file, ln)
        return "on" if val.lower() in ON else "off"
    if kind in ("int0", "int1"):
        if not val.isdigit() or (kind == "int1" and int(val) < 1):
            raise ConfigError(f"'{key}' must be a whole number{' of at least 1' if kind == 'int1' else ''}, "
                              f"not '{val}'", file, ln)
        return str(int(val))
    if kind == "sig":
        if val.lower() not in SIG:
            raise ConfigError(f"'{key}' must be required, optional or never, not '{val}'", file, ln)
        return val.lower()
    if kind == "usage":
        bad = [w for w in words if w.lower() not in USAGE]
        if bad:
            raise ConfigError(f"unknown usage '{bad[0]}' (use: sync search install upgrade all)", file, ln)
        return " ".join(w.lower() for w in words)
    if kind in ("word", "path", "url"):
        if len(words) != 1:
            raise ConfigError(f"'{key}' takes one value, got {len(words)}", file, ln)
        if kind == "path" and not val.startswith("/"):
            raise ConfigError(f"'{key}' needs an absolute path (starting with /), not '{val}'", file, ln)
        if kind == "url" and not re.match(r"^(https?|ftp|file)://", val):
            raise ConfigError(f"'{key}' must be an https://, http://, ftp:// or file:// address, not '{val}'",
                              file, ln)
        return val
    return " ".join(words)


def _prefixed(root, path):
    return os.path.join(root, path.lstrip("/")) if root else path


def _read(path, root, cfg, file=None, ln=None, what="file"):
    real = _prefixed(root, path)
    try:
        with open(real, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        raise ConfigError(f"{what} {path} does not exist", file, ln)
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"cannot read {what} {path}: {e}", file, ln)
    if real not in cfg.sources:
        cfg.sources.append(real)
    return text


def read_mirrorlist_text(text, file="mirrorlist"):
    """Adresy zrcadel: jedna na radek, '#' komentare. "Server = URL" (reflector, pacman) se prijme taky."""
    urls = []
    for ln, raw in enumerate(text.splitlines(), 1):
        line = strip_comment(raw).strip()
        if not line:
            continue
        m = re.match(r"^Server\s*=\s*(\S+)\s*$", line)
        if m:
            line = m.group(1)
        if " " in line or "\t" in line or not re.match(r"^(https?|ftp|file)://", line):
            raise ConfigError(f"not a mirror address: '{line}' (one https://.../$repo/os/$arch per line)", file, ln)
        urls.append(line)
    return urls


def parse(path=LUX_CONF, root="", cfg=None, depth=0, file_label=None, text=None):
    """Precte lux.conf (vcetne include a seznamu zrcadel). root = predpona pro cteni (testy, instalator)."""
    cfg = cfg or Config()
    label = file_label or path
    if text is None:
        text = _read(path, root, cfg, what="configuration file")
    cur = None
    for ln, raw in enumerate(text.splitlines(), 1):
        if not strip_comment(raw).strip():
            continue
        indented = raw[:1] in (" ", "\t")
        line = strip_comment(raw).strip()
        if line.startswith("[") and line.endswith("]"):
            raise ConfigError(f"'{line}' looks like pacman.conf syntax; lux.conf uses 'key value' lines and "
                              "'repo NAME' blocks (see /usr/share/doc/lux/lux.md)", label, ln)
        m = re.match(r"^([A-Z_]+)=(\S*)$", line)
        if m and m.group(1) in LEGACY_SHELL and not indented:
            key = LEGACY_SHELL[m.group(1)]
            kind = GLOBAL_KEYS[key][0]
            val = m.group(2).strip("\"'")
            if kind == "bool":
                val = "on" if val not in ("0", "") else "off"
            cfg.values[key] = _check_value(kind, key, val, label, ln)
            cfg.legacy = True
            cur = None
            continue
        parts = line.split(None, 1)
        key = parts[0].lower()
        val = parts[1].strip() if len(parts) > 1 else ""
        if "=" in key or (val.startswith("=") and key[:1].isalpha()):
            raise ConfigError(f"'{line}' looks like pacman.conf syntax; write '{key.split('=')[0].lower()} value' "
                              "without '='", label, ln)
        if indented:
            if cur is None:
                raise ConfigError(f"indented line '{line}' does not belong to any 'repo' block", label, ln)
            if key not in REPO_KEYS:
                hint = " (repository keys: server, mirrors, signatures, usage)"
                if key in GLOBAL_KEYS:
                    hint = " - global keys must not be indented"
                raise ConfigError(f"unknown repository key '{key}'{_suggest(key, REPO_KEYS) or hint}", label, ln)
            kind, many = REPO_KEYS[key]
            v = _check_value(kind, key, val, label, ln)
            if key == "server":
                cur.servers.append((v, f"{label}:{ln}"))
            elif key == "mirrors":
                urls = read_mirrorlist_text(_read(v, root, cfg, label, ln, "mirror list"), v)
                if not urls:
                    raise ConfigError(f"mirror list {v} has no mirrors (all lines are comments)", label, ln)
                cur.mirror_files.append(v)
                cur.servers += [(u, v) for u in urls]
            elif key == "signatures":
                cur.signatures = v
            else:
                cur.usage = v
            continue
        cur = None
        if key == "repo":
            name = val
            if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$", name):
                raise ConfigError(f"invalid repository name '{name}'", label, ln)
            if name in ("local", "options"):
                raise ConfigError(f"'{name}' cannot be used as a repository name", label, ln)
            old = cfg.repo(name)
            if old is not None:
                raise ConfigError(f"repository '{name}' is already defined at {old.file}:{old.line}", label, ln)
            cur = Repo(name, label, ln)
            cfg.repos.append(cur)
            continue
        if key == "include":
            if depth >= MAX_INCLUDE_DEPTH:
                raise ConfigError("too many nested includes", label, ln)
            pat = val if val.startswith("/") else os.path.join(os.path.dirname(path), val)
            if glob.has_magic(pat):
                found = sorted(glob.glob(_prefixed(root, pat)))
                cfg.globs.append((_prefixed(root, pat), found))
                files = [("/" + os.path.relpath(f, root)) if root else f for f in found]
            else:
                files = [pat]
            for f in files:
                parse(f, root, cfg, depth + 1)
            continue
        if key in REPO_KEYS and key not in GLOBAL_KEYS:
            raise ConfigError(f"'{key}' belongs to a repository: indent it under a 'repo NAME' line", label, ln)
        if key not in GLOBAL_KEYS:
            raise ConfigError(f"unknown key '{key}'{_suggest(key, list(GLOBAL_KEYS) + ['repo', 'include'])}",
                              label, ln)
        kind, _d, many = GLOBAL_KEYS[key]
        v = _check_value(kind, key, val, label, ln)
        if key == "signatures" and v == "never":
            raise ConfigError("'signatures never' is only allowed for a local repository (file://)", label, ln)
        if many:
            cfg.lists.setdefault(key, []).append(v)
        else:
            cfg.values[key] = v
    if depth == 0:
        validate(cfg)
    return cfg


def validate(cfg):
    for r in cfg.repos:
        if not r.servers:
            raise ConfigError(f"repository '{r.name}' has no 'server' or 'mirrors' line", r.file, r.line)
        if r.signatures == "never" and not all(u.startswith("file://") for u, _o in r.servers):
            raise ConfigError(f"'signatures never' is only allowed for a local repository (file://), "
                              f"'{r.name}' downloads from the internet", r.file, r.line)


def render_engine(cfg, source_label=LUX_CONF):
    """Konfigurace jadra (syntaxe pacman.conf) + hlavicka se zdroji pro kontrolu cerstvosti."""
    out = [f"# LuxOS: generated from {source_label} by lux-config - do not edit, change lux.conf instead",
           f"#@lux-config\t{VERSION}"]
    for s in sources_with_self(cfg):
        out.append("#@source\t" + "\t".join(stat_sig(s)))
    for pat, files in cfg.globs:
        out.append("#@glob\t" + "\t".join([pat] + [os.path.basename(f) for f in files]))
    out.append("[options]")
    words = lambda k: " ".join(cfg.lists.get(k, []) or ([cfg.get(k)] if cfg.get(k) else []))  # noqa: E731
    for key, (kind, directive, many) in GLOBAL_KEYS.items():
        if directive is None:
            continue
        if kind == "bool":
            on = cfg.get(key) == "on"
            if key in ("download-timeout", "download-sandbox"):
                on = not on          # Disable...
            if on:
                out.append(directive)
        elif kind == "sig":
            v = SIG[cfg.get(key)]
            if key == "local-signatures" and cfg.get(key) == "optional":
                v = "Optional"       # soubory .pkg.tar.* z disku (AUR): jako dosud
            out.append(f"{directive} = {v}")
        elif key == "download-user":
            if cfg.get(key) not in ("none", "root"):
                out.append(f"{directive} = {cfg.get(key)}")
        elif many and kind == "path":
            for v in cfg.lists.get(key, []):
                out.append(f"{directive} = {v}")
        elif many:
            if key == "protect" and key not in cfg.lists:
                out.append(f"{directive} = {DEFAULTS['protect']}")
            for v in cfg.lists.get(key, []):
                out.append(f"{directive} = {v}")
        else:
            v = words(key)
            if v:
                out.append(f"{directive} = {v}")
    for r in cfg.repos:
        out.append("")
        out.append(f"[{r.name}]")
        if r.signatures:
            out.append(f"SigLevel = {SIG[r.signatures]}")
        if r.usage:
            out.append("Usage = " + " ".join(USAGE[u] for u in r.usage.split()))
        for url, _o in r.servers:
            out.append(f"Server = {url}")
    return "\n".join(out) + "\n"


def self_path():
    return os.path.realpath(__file__)


def sources_with_self(cfg):
    # zmena lux-config (nova verze baliku) = nova konfigurace jadra
    return list(cfg.sources) + [self_path()]


def stat_sig(path):
    try:
        st = os.stat(path)
        return path, f"{st.st_mtime_ns // 10**9}.{st.st_mtime_ns % 10**9:09d}", str(st.st_size)
    except OSError:
        return path, "-", "-"


def is_fresh(engine):
    """Odpovida konfigurace jadra aktualnim zdrojum? (stejna kontrola jako lux-engine-wrapper v bashi)"""
    try:
        with open(engine, encoding="utf-8") as f:
            head = [next(f, "") for _i in range(64)]
    except OSError:
        return False
    seen_self = ok = False
    for line in head:
        line = line.rstrip("\n")
        if not line.startswith("#@"):
            if line.startswith("[options]"):
                break
            continue
        parts = line.split("\t")
        if parts[0] == "#@source":
            if len(parts) != 4 or tuple(parts[1:]) != stat_sig(parts[1]):
                return False
            seen_self |= parts[1] == self_path()
            ok = True
        elif parts[0] == "#@glob":
            if [os.path.basename(f) for f in sorted(glob.glob(parts[1]))] != parts[2:]:
                return False
    return ok and seen_self


def atomic_write(path, text, mode=0o644):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(path) + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _can_write(path):
    d = os.path.dirname(os.path.abspath(path))
    while not os.path.exists(d):
        d = os.path.dirname(d)
    return os.access(d, os.W_OK)


def _user_output():
    """Kopie konfigurace jadra pro uzivatele bez prav k /run/lux ($XDG_RUNTIME_DIR, jinak cache)."""
    rd = os.environ.get("XDG_RUNTIME_DIR")
    if rd and os.path.isdir(rd) and os.access(rd, os.W_OK):
        return os.path.join(rd, "lux", "engine.conf")
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    if os.path.isabs(cache) and _can_write(os.path.join(cache, "lux", "engine.conf")):
        return os.path.join(cache, "lux", "engine.conf")
    return None


def ensure(conf=LUX_CONF, output=ENGINE_CONF, quiet=False, err=sys.stderr):
    """Vrati (cesta, stav): stav "ok", "stale" (lux.conf je rozbita, cesta = posledni funkcni
    konfigurace) nebo "error" (cesta None). Chyba se vypise na err (krome quiet a ok)."""
    if is_fresh(output):
        return output, "ok"
    writable = os.geteuid() == 0 or _can_write(output)
    target = output
    if not writable:
        target = _user_output()
        if target and is_fresh(target):
            return target, "ok"
    try:
        cfg = parse(conf)
        text = render_engine(cfg, conf)
    except ConfigError as e:
        last = output if os.path.exists(output) else None
        if last is None and output == ENGINE_CONF and os.path.exists(LAST_GOOD):
            last = LAST_GOOD
            if writable:
                try:
                    with open(LAST_GOOD, encoding="utf-8") as f:
                        atomic_write(output, f.read())
                    last = output
                except OSError:
                    pass
        if err is not None:
            print(f"lux: error in the configuration: {e}", file=err)
            if last:
                print("lux: the package manager keeps using the last working configuration until this is fixed",
                      file=err)
        return last, ("stale" if last else "error")
    if target is None:
        fd, target = tempfile.mkstemp(prefix="lux-engine-", suffix=".conf")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        return target, "ok"
    try:
        atomic_write(target, text)
    except OSError:
        # jen pro cteni (napr. sluzba s ProtectSystem=strict): docasna kopie
        try:
            fd, target = tempfile.mkstemp(prefix="lux-engine-", suffix=".conf")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            if err is not None and not quiet:
                print(f"lux: cannot write the package manager configuration: {e}", file=err)
            return None, "error"
        return target, "ok"
    if target == ENGINE_CONF:
        try:
            atomic_write(LAST_GOOD, text)
        except OSError:
            pass
    return target, "ok"


def cli_settings(conf=LUX_CONF, user=True):
    """Nastaveni lux (aur, review-pkgbuild, flatpak, clean-keep): systemove, pak uzivatelske."""
    cfg = parse(conf)
    vals = {k: cfg.get(k) for k in CLI_SHELL}
    if user:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        upath = os.path.join(base, USER_CONF)
        if os.path.isfile(upath):
            ucfg = Config()
            with open(upath, encoding="utf-8") as f:
                text = f.read()
            parse(upath, cfg=ucfg, depth=1, text=text)
            for k in CLI_SHELL:
                if k in ucfg.values:
                    vals[k] = ucfg.values[k]
    return vals, cfg


# ---- prevod ze stareho pacman.conf (migrace z LuxOS 0.9.5 a starsich) -----------------------------
PACMAN_OPTS = {  # direktiva -> (klic lux, druh)
    "Architecture": ("architecture", "words"), "ParallelDownloads": ("parallel-downloads", "value"),
    "Color": ("color", "flag"), "ILoveCandy": ("candy", "flag"), "CheckSpace": ("check-space", "flag"),
    "VerbosePkgLists": ("verbose-lists", "flag"), "UseSyslog": ("syslog", "flag"),
    "DisableDownloadTimeout": ("download-timeout", "noflag"), "DisableSandbox": ("download-sandbox", "noflag"),
    "DownloadUser": ("download-user", "value"), "HoldPkg": ("protect", "list"), "IgnorePkg": ("hold", "list"),
    "IgnoreGroup": ("ignore-group", "list"), "NoUpgrade": ("no-upgrade", "list"),
    "NoExtract": ("no-extract", "list"), "SigLevel": ("signatures", "sig"),
    "LocalFileSigLevel": ("local-signatures", "sig"),
}
OLD_DEFAULT_PATHS = {  # vychozi cesty pacmanu = vychozi cesty lux (nepreva se)
    "DBPath": ("database", "/var/lib/pacman"), "CacheDir": ("cache", "/var/cache/pacman/pkg"),
    "LogFile": ("log", "/var/log/pacman.log"), "GPGDir": ("keyring", "/etc/pacman.d/gnupg"),
    "HookDir": ("hooks", "/etc/pacman.d/hooks"),
}


def sig_from_pacman(val):
    words = val.split()
    if "Never" in words and not any(w.startswith("Package") or w.startswith("Database") for w in words):
        return "never"
    if "Optional" in words or "PackageOptional" in words and "DatabaseOptional" in words:
        return "optional"
    return "required"


def map_path(p):
    """Cesty z /etc/pacman.d/... -> /etc/lux/..."""
    if p.rstrip("/") == "/etc/pacman.d/mirrorlist":
        return MIRRORLIST
    if p.startswith("/etc/pacman.d/"):
        return "/etc/lux/" + p[len("/etc/pacman.d/"):]
    return p


# Repozitare LuxOS se presunuly (LuxOS 0.9.7); stara adresa dal funguje, prevod pouzije novou
MOVED_SERVERS = {"https://lsl.lux-ai.cz/luxos/": "https://luxos.lux-ai.cz/repo/"}


def moved_server(url):
    for old, new in MOVED_SERVERS.items():
        if url.startswith(old):
            return new + url[len(old):]
    return url


def update_moved_servers(conf=LUX_CONF):
    """Stara adresa repozitaru LuxOS v /etc/lux/lux.conf -> nova (jen radky server, zbytek beze zmeny).
    Kdyz se lux.conf lisila od baliku jen adresou, aktualizace nechala lux.conf.pacnew se stejnym
    obsahem - ten se po uprave smaze. Vraci True, kdyz se neco zmenilo."""
    try:
        with open(conf, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False
    out = []
    for line in text.splitlines(keepends=True):
        m = re.match(r"^(\s*server\s+)(\S+)(.*)$", line, re.S)
        if m and moved_server(m.group(2)) != m.group(2):
            line = m.group(1) + moved_server(m.group(2)) + m.group(3)
        out.append(line)
    new = "".join(out)
    changed = new != text
    if changed:
        atomic_write(conf, new, os.stat(conf).st_mode & 0o7777)
    try:
        with open(conf + ".pacnew", encoding="utf-8") as f:
            if f.read() == new:
                os.unlink(conf + ".pacnew")
                changed = True
    except OSError:
        pass
    return changed


DRIVERS_REPO = "luxos-drivers"
DRIVERS_STAMP = "/var/lib/lux/luxos-drivers-repo"


def without_drivers_repo(text):
    """lux.conf bez bloku [luxos-drivers] (vychozi konfigurace pred LuxOS 0.9.10)."""
    return re.sub(r"\n(#[^\n]*\n)?repo[ \t]+luxos-drivers[ \t]*\n([ \t]+[^\n]*\n)*", "\n", text)


def add_drivers_repo(conf=LUX_CONF, stamp=DRIVERS_STAMP):
    """LuxOS 0.9.10: repozitar [luxos-drivers] do lux.conf starsich instalaci - jednou (znacka stamp),
    jen kdyz je nastaveny [luxos]; kdo ho pak odebere, tomu se uz nevrati. Vraci True pri zmene."""
    if os.path.exists(stamp):
        return False
    try:
        with open(conf, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False
    # jen text (bez parse): v chrootu/testu nemusi existovat seznamy zrcadel z lux.conf
    has = lambda name: re.search(r"^repo[ \t]+%s[ \t]*(#.*)?$" % re.escape(name), text, re.M) is not None  # noqa: E731
    changed = False
    if has("luxos") and not has(DRIVERS_REPO):
        block = (f"\n# overene ovladace tiskaren a skeneru vyrobcu (z AUR, kazda verze zkontrolovana, podepsane)\n"
                 f"repo {DRIVERS_REPO}\n    server  https://luxos.lux-ai.cz/repo/$repo/$arch\n")
        atomic_write(conf, text.rstrip("\n") + "\n" + block, os.stat(conf).st_mode & 0o7777)
        changed = True
    os.makedirs(os.path.dirname(stamp), exist_ok=True)
    with open(stamp, "w", encoding="utf-8") as f:
        f.write("added\n" if changed else "present\n")
    return changed


def convert_pacman_conf(path, root=""):
    """Stary pacman.conf -> (text lux.conf, {cesta: obsah dalsich seznamu zrcadel}, [varovani]).
    Include se seznamem zrcadel -> 'mirrors' (soubor prevedeny do formatu lux), ostatni Include se vlozi."""
    warnings, extra = [], {}
    glob_vals, repos = {}, []
    lists = {}

    def handle(text, label, section):
        for ln, raw in enumerate(text.splitlines(), 1):
            line = raw.split("#", 1)[0].strip()   # pacman: '#' kdekoli zacina komentar
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section[0] = line[1:-1].strip()
                if section[0] != "options" and not any(r["name"] == section[0] for r in repos):
                    repos.append({"name": section[0], "servers": [], "mirrors": [], "sig": None, "usage": None})
                continue
            key, sep, val = (s.strip() for s in line.partition("="))
            if key == "Include":
                inc = val
                if section[0] != "options" and map_path(inc) == MIRRORLIST:
                    # hlavni seznam zrcadel prevadi migrace zvlast (/etc/lux/mirrorlist)
                    repo = next(r for r in repos if r["name"] == section[0])
                    if MIRRORLIST not in repo["mirrors"]:
                        repo["mirrors"].append(MIRRORLIST)
                    continue
                files = sorted(glob.glob(_prefixed(root, inc))) if glob.has_magic(inc) else [_prefixed(root, inc)]
                for f in files:
                    try:
                        with open(f, encoding="utf-8") as fh:
                            itext = fh.read()
                    except OSError as e:
                        warnings.append(f"{label}:{ln}: Include {inc} not readable ({e}) - skipped")
                        continue
                    srv_only = all((not ln2.strip()) or ln2.strip().startswith("#") or
                                   re.match(r"^Server\s*=", ln2.strip()) for ln2 in itext.splitlines())
                    if section[0] != "options" and srv_only:
                        rel = "/" + os.path.relpath(f, root) if root else f
                        new = map_path(rel)
                        repo = next(r for r in repos if r["name"] == section[0])
                        if new not in repo["mirrors"]:
                            repo["mirrors"].append(new)
                        if new != MIRRORLIST and new not in extra:
                            urls = read_mirrorlist_text(itext, f)
                            extra[new] = mirrorlist_text(urls, f"converted from {rel}")
                    else:
                        handle(itext, f, section)
                continue
            if section[0] == "options":
                if key in PACMAN_OPTS:
                    lk, kind = PACMAN_OPTS[key]
                    if kind == "flag":
                        glob_vals[lk] = "on"
                    elif kind == "noflag":
                        glob_vals[lk] = "off"
                    elif kind == "sig":
                        glob_vals[lk] = sig_from_pacman(val)
                    elif kind == "list":
                        lists.setdefault(lk, []).append(val)
                    else:
                        glob_vals[lk] = val
                elif key in OLD_DEFAULT_PATHS:
                    lk, old_default = OLD_DEFAULT_PATHS[key]
                    if val.rstrip("/") != old_default:
                        if lk in ("cache", "hooks"):
                            lists.setdefault(lk, []).append(map_path(val))
                        else:
                            glob_vals[lk] = map_path(val)
                elif key in ("RootDir",):
                    warnings.append(f"{label}:{ln}: {key} is not supported in lux.conf - skipped")
                else:
                    warnings.append(f"{label}:{ln}: option {key} has no lux.conf equivalent - skipped")
            else:
                repo = next(r for r in repos if r["name"] == section[0])
                if key == "Server":
                    repo["servers"].append(moved_server(val))
                elif key == "SigLevel":
                    repo["sig"] = sig_from_pacman(val)
                elif key == "Usage":
                    repo["usage"] = " ".join(w.lower() for w in val.split())
                else:
                    warnings.append(f"{label}:{ln}: {key} in [{section[0]}] has no lux.conf equivalent - skipped")

    with open(_prefixed(root, path), encoding="utf-8") as f:
        handle(f.read(), path, ["options"])
    if "protect" in lists:   # HoldPkg = pacman glibc: "pacman" je v LuxOS lux-engine
        lists["protect"] = [" ".join("lux-engine" if w == "pacman" else w for w in v.split())
                            for v in lists["protect"]]
    out = ["# LuxOS - configuration of the lux package manager (converted from pacman.conf)",
           "# Format and all keys: /usr/share/doc/lux/lux.md", ""]
    # klice, ktere v pacman.conf chybely, maji v pacmanu jinou vychozi hodnotu nez v lux.conf
    pacman_defaults = {"color": "off", "candy": "off", "check-space": "off", "verbose-lists": "off",
                       "parallel-downloads": "1", "download-user": "none"}
    for k, v in pacman_defaults.items():
        glob_vals.setdefault(k, v)
    for k in GLOBAL_KEYS:
        if k in glob_vals and glob_vals[k] != DEFAULTS.get(k):
            if k == "signatures" and glob_vals[k] == "never":
                warnings.append("SigLevel = Never for all repositories is not allowed any more - "
                                "signatures are required")
                continue
            out.append(f"{k}  {glob_vals[k]}")
        for v in lists.get(k, []):
            if k == "protect" and v == DEFAULTS["protect"]:
                continue
            out.append(f"{k}  {v}")
    for r in repos:
        if not r["servers"] and not r["mirrors"]:
            warnings.append(f"repository [{r['name']}] has no servers - skipped")
            continue
        out.append("")
        out.append(f"repo {r['name']}")
        for s in r["servers"]:
            out.append(f"    server  {s}")
        for m in r["mirrors"]:
            out.append(f"    mirrors  {m}")
        if r["sig"] and r["sig"] != "required":
            if r["sig"] == "never" and not all(s.startswith("file://") for s in r["servers"]):
                warnings.append(f"[{r['name']}]: SigLevel = Never kept only for local repositories - "
                                "signatures are now required")
            else:
                out.append(f"    signatures  {r['sig']}")
        if r["usage"]:
            out.append(f"    usage  {r['usage']}")
    out += ["", "# more files in the same format (repositories added by packages or the administrator)",
            "include  /etc/lux/conf.d/*.conf"]
    return "\n".join(out) + "\n", extra, warnings


def mirrorlist_text(urls, note=""):
    head = ["# LuxOS - download mirrors for Arch Linux repositories (one address per line, best first)",
            "# Change with: lux mirrors"]
    if note:
        head.append(f"# {note}")
    return "\n".join(head + [""] + list(urls)) + "\n"


def semantic(cfg):
    """Porovnatelny obsah konfigurace (bez komentaru a poradi radku v souboru)."""
    return render_engine(cfg).split("[options]", 1)[1]


def enable_repo(name, conf=LUX_CONF, mirrors=None, server=None):
    """Prida blok repo na konec lux.conf (napr. multilib pro Steam). Uz nastaveny = nic."""
    cfg = parse(conf)
    if cfg.repo(name) is not None:
        return False
    with open(conf, encoding="utf-8") as f:
        text = f.read()
    block = f"\nrepo {name}\n" + (f"    server  {server}\n" if server else f"    mirrors  {mirrors or MIRRORLIST}\n")
    new = text.rstrip("\n") + "\n" + block
    tmp_cfg = parse(conf, text=new)       # kontrola pred zapisem
    del tmp_cfg
    atomic_write(conf, new, os.stat(conf).st_mode & 0o7777)
    return True


def _opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 >= len(args):
            raise SystemExit(f"lux-config: {name} needs a value")
        v = args[i + 1]
        del args[i:i + 2]
        return v
    return default


def main(argv):
    args = list(argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 2
    cmd = args.pop(0)
    conf = _opt(args, "--config", LUX_CONF)
    try:
        if cmd == "ensure":
            quiet = "-q" in args or "--quiet" in args
            out = _opt(args, "--output", ENGINE_CONF)
            path, state = ensure(conf, out, quiet)
            if path:
                print(path)
            return {"ok": 0, "stale": 2}.get(state, 1)
        if cmd == "check":
            files = [a for a in args if not a.startswith("-")] or [conf]
            rc = 0
            for f in files:
                try:
                    parse(f)
                    print(f"{f}: OK")
                except ConfigError as e:
                    print(f"lux: error in the configuration: {e}", file=sys.stderr)
                    rc = 1
            return rc
        if cmd == "env":
            vals, _cfg = cli_settings(conf)
            path, state = ensure(conf, err=sys.stderr)
            if state != "ok":
                return 1
            for k, var in CLI_SHELL.items():
                v = vals[k]
                print(f"{var}={'1' if v == 'on' else '0' if v == 'off' else v}")
            print(f"LUX_ENGINE_CONF={path}")
            return 0
        if cmd == "get":
            vals, cfg = cli_settings(conf)
            key = args[0]
            if key in vals:
                print(vals[key])
            elif key in GLOBAL_KEYS:
                v = cfg.lists.get(key) or ([cfg.get(key)] if cfg.get(key) is not None else [])
                print("\n".join(v))
            else:
                print(f"lux-config: unknown key '{key}'", file=sys.stderr)
                return 2
            return 0
        if cmd == "dump":
            sys.stdout.write(render_engine(parse(conf), conf))
            return 0
        if cmd == "has-repo":
            return 0 if parse(conf).repo(args[0]) is not None else 1
        if cmd == "enable-repo":
            mirrors = _opt(args, "--mirrors")
            server = _opt(args, "--server")
            enable_repo(args[0], conf, mirrors, server)
            return 0
        if cmd == "mirrors-import":
            out = _opt(args, "--output", MIRRORLIST)
            src = args[0] if args else "-"
            text = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
            urls = read_mirrorlist_text(text, src)
            if not urls:
                print("lux-config: no mirrors found - the mirror list was not changed", file=sys.stderr)
                return 1
            data = mirrorlist_text(urls)
            if out == "-":
                sys.stdout.write(data)
            else:
                atomic_write(out, data)
            return 0
        if cmd == "update-servers":
            if update_moved_servers(conf):
                print(f"lux-config: repository addresses updated in {conf}")
            return 0
        if cmd == "convert-pacman":
            text, extra, warns = convert_pacman_conf(args[0])
            sys.stdout.write(text)
            for w in warns:
                print("lux-config: " + w, file=sys.stderr)
            for p in extra:
                print(f"lux-config: also needs mirror list {p}", file=sys.stderr)
            return 0
    except ConfigError as e:
        print(f"lux: error in the configuration: {e}", file=sys.stderr)
        return 1
    except (OSError, IndexError) as e:
        print(f"lux-config: {e}", file=sys.stderr)
        return 1
    print(f"lux-config: unknown command '{cmd}'", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
