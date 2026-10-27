#!/usr/bin/python3
"""lux-config - konfigurace spravce baliku LuxOS (/etc/lux/lux.conf) a z ni vygenerovana
konfigurace nastroju jadra (/run/lux/engine.conf).

/etc/lux/lux.conf ma od LuxOS 1.0 format TOML (popis: /usr/share/doc/lux/lux.md):

    # komentar (do konce radku)
    [downloads]
    parallel = 10
    [packages]
    hold = ["linux-firmware"]
    [repo.luxos]
    server = "https://luxos.lux-ai.cz/repo/$repo/$arch"
    [repo.core]
    mirrors = "/etc/lux/mirrorlist"
    [include]
    files = ["/etc/lux/conf.d/*.conf"]

Cte ji primo tento modul (tomllib ze standardni knihovny Pythonu, chyby se souborem a radkem,
neznamy klic = varovani v "lux config check"). lux (lux_alpm.py) z vysledku nastavi libalpm
primo (load(), engine_options()) - bez mezisouboru. Starsi format LuxOS 0.9 ("klic hodnota",
bloky "repo NAZEV" s odsazenymi radky) se porad cte (rozpozna se sam); "lux-config migrate"
ho prevede (stary soubor zustane jako *.old-format), aktualizace lux-engine to udela jednou sama.

Nastroje jadra z Arch Linuxu (lux-engine, lux-engine-key, makepkg pres lux-engine-conf) jsou
nezmenene programy v C a ctou jen syntaxi INI pacmanu: pro ne lux-config generuje
/run/lux/engine.conf (root, 0644) pokazde, kdyz se lux.conf, vlozene soubory nebo seznamy zrcadel
zmeni (hlavicka "#@source" s casem zmeny a velikosti kazdeho zdroje). Spousteci skript nastroju
zavola ensure() pred spustenim jadra. Rozbita konfigurace: chyba se souborem a radkem, posledni
funkcni engine.conf zustava (lux sam odmitne pokracovat).

  lux-config ensure [-q] [--config F] [--output F]   cesta k pouzitelne konfiguraci jadra
                                                     (0 ok, 2 rozbita lux.conf - posledni funkcni, 1 chyba)
  lux-config check [SOUBOR...]                       kontrola (chyby se souborem a radkem, varovani, stary format)
  lux-config migrate [SOUBOR...] [--dry-run]         stary format LuxOS 0.9 -> TOML (bez SOUBORU: lux.conf
                                                     a conf.d/*.conf; puvodni soubor zustane jako *.old-format)
  lux-config env                                     nastaveni lux pro shell (AUR=1 ...) + LUX_ENGINE_CONF
  lux-config get KLIC                                hodnota (napr. packages.cache_keep nebo clean-keep)
  lux-config json [--config F]                       cela konfigurace jako JSON (load())
  lux-config dump [--config F]                       vygenerovana konfigurace nastroju jadra na stdout
  lux-config mirrors-import [SOUBOR|-] [--output F]  seznam zrcadel z reflectoru/pacmanu -> format lux
  lux-config convert-pacman SOUBOR                   stary pacman.conf -> lux.conf na stdout
  lux-config update-servers [--config F]             stara adresa repozitaru LuxOS -> nova (po aktualizaci)
  lux-config enable-repo NAZEV [--mirrors F|--server URL] [--config F]   prida repozitar
  lux-config has-repo NAZEV [--config F]             0 = repozitar je nastaven
"""
import difflib
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import tomllib

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
        self.formats = {}          # soubor -> "toml" | "old" (format LuxOS 0.9)
        self.includes = []         # vlozene soubory konfigurace (poradi cteni)
        self.warnings = []         # (soubor, radek, zprava) - neznamy klic apod. (lux config check)

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
    q = key if key.startswith("'") else f"'{key}'"     # TOML: "'parallel' in [downloads]"
    words = val.split()
    if not words:
        raise ConfigError(f"{q} needs a value", file, ln)
    if kind == "bool":
        if val.lower() not in ON | OFF:
            raise ConfigError(f"{q} must be on or off, not '{val}'", file, ln)
        return "on" if val.lower() in ON else "off"
    if kind in ("int0", "int1"):
        if not val.isdigit() or (kind == "int1" and int(val) < 1):
            raise ConfigError(f"{q} must be a whole number{' of at least 1' if kind == 'int1' else ''}, "
                              f"not '{val}'", file, ln)
        return str(int(val))
    if kind == "sig":
        if val.lower() not in SIG:
            raise ConfigError(f"{q} must be required, optional or never, not '{val}'", file, ln)
        return val.lower()
    if kind == "usage":
        bad = [w for w in words if w.lower() not in USAGE]
        if bad:
            raise ConfigError(f"unknown usage '{bad[0]}' (use: sync search install upgrade all)", file, ln)
        return " ".join(w.lower() for w in words)
    if kind in ("word", "path", "url"):
        if len(words) != 1:
            raise ConfigError(f"{q} takes one value, got {len(words)}", file, ln)
        if kind == "path" and not val.startswith("/"):
            raise ConfigError(f"{q} needs an absolute path (starting with /), not '{val}'", file, ln)
        if kind == "url" and not re.match(r"^(https?|ftp|file)://", val):
            raise ConfigError(f"{q} must be an https://, http://, ftp:// or file:// address, not '{val}'",
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


# ---- format TOML (LuxOS 1.0) ---------------------------------------------------------------------
# tabulka -> {klic TOML: vnitrni klic}. Vnitrni klice = jmena formatu LuxOS 0.9 (GLOBAL_KEYS);
# kazdy klic stareho formatu ma presne jedno misto v TOML.
TOML_TABLES = {
    "general": {"architecture": "architecture", "color": "color", "candy": "candy",
                "verbose": "verbose-lists", "syslog": "syslog"},
    "downloads": {"parallel": "parallel-downloads", "check_space": "check-space", "user": "download-user",
                  "timeout": "download-timeout", "sandbox": "download-sandbox"},
    "security": {"signatures": "signatures", "local_signatures": "local-signatures", "protect": "protect"},
    "packages": {"aur": "aur", "review_pkgbuild": "review-pkgbuild", "flatpak": "flatpak",
                 "cache_keep": "clean-keep", "hold": "hold", "ignore_group": "ignore-group",
                 "no_upgrade": "no-upgrade", "no_extract": "no-extract"},
    "paths": {"database": "database", "cache": "cache", "log": "log", "keyring": "keyring", "hooks": "hooks"},
}
# vnitrni klic -> (tabulka, klic TOML)
TOML_PLACE = {ik: (t, k) for t, keys in TOML_TABLES.items() for k, ik in keys.items()}
TOML_REPO_KEYS = ("server", "mirrors", "signatures", "usage")
# klice se seznamem slov (balicky, architektury); v TOML pole retezcu
WORD_LISTS = {"architecture", "protect", "hold", "ignore-group", "no-upgrade", "no-extract"}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_KEY_PART = r"""(?:"(?:[^"\\]|\\.)*"|'[^']*'|[A-Za-z0-9_-]+)"""
_KEY_LINE_RE = re.compile(r"^\s*(" + _KEY_PART + r"(?:\s*\.\s*" + _KEY_PART + r")*)\s*=")
_HEADER_RE = re.compile(r"^\s*\[\s*(" + _KEY_PART + r"(?:\s*\.\s*" + _KEY_PART + r")*)\s*\]\s*(#.*)?$")
LEGACY_SHELL_RE = re.compile(r"^(AUR|REVIEW_PKGBUILD|FLATPAK|CLEAN_KEEP)=")


def detect_format(text):
    """"toml" nebo "old" (format LuxOS 0.9) podle prvniho radku, ktery neni komentar.
    Prazdny soubor je TOML. pacman.conf ([options]) vyjde jako TOML a skonci chybou s napovedou."""
    for raw in text.splitlines():
        line = strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("["):
            return "toml"
        if LEGACY_SHELL_RE.match(line):
            return "old"
        if _KEY_LINE_RE.match(line):
            return "toml"
        return "old"
    return "toml"


def _split_key(s):
    """'repo."my.repo"' -> ['repo', 'my.repo'] (tecky mimo uvozovky oddeluji casti klice)."""
    out = []
    for p in re.findall(r"""("(?:[^"\\]|\\.)*"|'[^']*'|[A-Za-z0-9_-]+)""", s):
        if p.startswith('"'):
            try:
                p = json.loads(p)
            except ValueError:
                p = p[1:-1]
        elif p.startswith("'"):
            p = p[1:-1]
        out.append(p)
    return out


class Locator:
    """Cisla radku klicu a tabulek v textu TOML (tomllib je nevraci) - pro chyby a varovani."""

    def __init__(self, text):
        self.keys = {}       # (cesta tabulky..., klic) -> radek
        self.tables = {}     # cesta tabulky -> radek hlavicky
        table = ()
        in_ml = None
        for ln, raw in enumerate(text.splitlines(), 1):
            if in_ml:
                if raw.count(in_ml) % 2 == 1:
                    in_ml = None
                continue
            m = _HEADER_RE.match(raw)
            if m and not raw.lstrip().startswith("[["):
                table = tuple(_split_key(m.group(1)))
                self.tables.setdefault(table, ln)
                continue
            m = _KEY_LINE_RE.match(raw)
            if m:
                self.keys.setdefault(table + tuple(_split_key(m.group(1))), ln)
                for q in ('"""', "'''"):
                    if raw.count(q) % 2 == 1:
                        in_ml = q

    def line(self, *path):
        """Radek klice (cesta vcetne tabulky), jinak radek nejblizsi tabulky."""
        path = tuple(path)
        while path:
            if path in self.keys:
                return self.keys[path]
            if path in self.tables:
                return self.tables[path]
            path = path[:-1]
        return None


def _toml_error(e, text):
    """tomllib.TOMLDecodeError -> (zprava, radek) s napovedou pro stary format a pacman.conf."""
    msg = getattr(e, "msg", None) or str(e)
    ln = getattr(e, "lineno", None)
    m = re.search(r"\s*\(at line (\d+), column \d+\)$", msg)
    if m:
        ln = ln or int(m.group(1))
        msg = msg[:m.start()]
    if re.search(r"\(at end of document\)$", msg):
        msg = re.sub(r"\s*\(at end of document\)$", "", msg)
        ln = ln or len(text.splitlines()) or 1
    lines = text.splitlines()
    bad = strip_comment(lines[ln - 1]).strip() if ln and 0 < ln <= len(lines) else ""
    hint = ""
    if re.search(r"^\s*\[options\]\s*$", text, re.M):
        hint = " - this looks like pacman.conf; convert it with: lux-config convert-pacman FILE"
    elif bad and re.match(r"^[a-z][a-z-]*\s+[^=\s]", bad) and "=" not in bad:
        hint = (f" - '{bad}' is the old 'key value' format; write 'key = value' in the right [table] "
                "(convert the whole file with: lux config migrate)")
    elif bad and re.match(r"""^[A-Za-z0-9_.-]+\s*=\s*[^"'\[\s0-9tf+-]""", bad):
        hint = ' - text values need quotes, e.g. key = "value"'
    return msg + hint, ln


def _where(table, key=None):
    return f"'{key}' in [{table}]" if key is not None else f"[{table}]"


def _type_name(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "a list"
    if isinstance(v, dict):
        return "a table"
    return type(v).__name__


def _toml_strings(v, what, file, ln, words=False):
    """Retezec nebo pole retezcu -> seznam retezcu (words: retezec s mezerami = vic slov)."""
    items = v if isinstance(v, list) else [v]
    out = []
    for it in items:
        if not isinstance(it, str):
            raise ConfigError(f"{what} must be text in quotes or a list of texts, not {_type_name(it)}", file, ln)
        out += it.split() if words else [it]
    return out


def _toml_value(kind, ik, what, v, file, ln):
    """Hodnota TOML -> vnitrni tvar (retezec jako ve formatu LuxOS 0.9; opakovatelne klice seznam)."""
    many = GLOBAL_KEYS[ik][2] if ik in GLOBAL_KEYS else REPO_KEYS[ik][1]
    if kind == "bool":
        if not isinstance(v, bool):
            raise ConfigError(f"{what} must be true or false, not {_type_name(v)}", file, ln)
        return "on" if v else "off"
    if kind in ("int0", "int1"):
        if isinstance(v, bool) or not isinstance(v, int) or v < (1 if kind == "int1" else 0):
            raise ConfigError(f"{what} must be a whole number{' of at least 1' if kind == 'int1' else ''} "
                              f"(without quotes), not {_type_name(v)}", file, ln)
        return str(v)
    if ik in WORD_LISTS or kind == "usage":
        words = _toml_strings(v, what, file, ln, words=True)
        if many:
            return [" ".join(words)] if words else []
        if not words:
            raise ConfigError(f"{what} needs a value", file, ln)
        return _check_value(kind, what, " ".join(words), file, ln)
    if many:   # cache, hooks, server, mirrors: jedna hodnota nebo pole
        return [_check_value(kind, what, x, file, ln) for x in _toml_strings(v, what, file, ln)]
    if not isinstance(v, str):
        raise ConfigError(f"{what} must be text in quotes, not {_type_name(v)}", file, ln)
    return _check_value(kind, what, v, file, ln)


def _suggest_toml(table, key):
    """Napoveda pro neznamy klic: spravna tabulka, podobny klic nebo jmeno ze stareho formatu."""
    for t, keys in TOML_TABLES.items():
        if key in keys and t != table:
            return f" (it belongs to [{t}])"
    if table in TOML_TABLES:
        near = _suggest(key, TOML_TABLES[table])
        if near:
            return near
    old = key.replace("_", "-")
    if old in TOML_PLACE:
        t, k = TOML_PLACE[old]
        return f" (did you mean '{k}' in [{t}]?)"
    for t, keys in TOML_TABLES.items():
        near = difflib.get_close_matches(key, list(keys), n=1, cutoff=0.75)
        if near:
            return f" (did you mean '{near[0]}' in [{t}]?)"
    return ""


def _parse_toml(text, path, label, root, cfg, depth):
    """Format TOML (LuxOS 1.0). Neznamy klic/tabulka = varovani (cfg.warnings), spatna hodnota = chyba."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        msg, ln = _toml_error(e, text)
        raise ConfigError(msg, label, ln)
    loc = Locator(text)

    def warn(msg, *where):
        cfg.warnings.append((label, loc.line(*where), msg))

    includes = []
    for name, val in data.items():
        if name in TOML_TABLES:
            if not isinstance(val, dict):
                raise ConfigError(f"'{name}' must be a table: write [{name}] on its own line", label, loc.line(name))
            for k, v in val.items():
                if k == "include":
                    includes.append((v, (name, k)))
                    warn("'include' belongs to [include] as 'files = [...]' (it is still used)", name, k)
                    continue
                if k not in TOML_TABLES[name]:
                    warn(f"unknown key {_where(name, k)}{_suggest_toml(name, k)} - ignored", name, k)
                    continue
                ik = TOML_TABLES[name][k]
                kind, _d, many = GLOBAL_KEYS[ik]
                ln = loc.line(name, k)
                v = _toml_value(kind, ik, _where(name, k), v, label, ln)
                if ik == "signatures" and v == "never":
                    raise ConfigError("'signatures = \"never\"' is only allowed for a local repository (file://)",
                                      label, ln)
                if many:
                    cfg.lists.setdefault(ik, []).extend(v)
                else:
                    cfg.values[ik] = v
        elif name == "repo":
            if not isinstance(val, dict):
                raise ConfigError("repositories are tables: write [repo.NAME]", label, loc.line(name))
            for rname, rval in val.items():
                ln = loc.line("repo", rname)
                if not NAME_RE.match(rname):
                    raise ConfigError(f"invalid repository name '{rname}'", label, ln)
                if rname in ("local", "options"):
                    raise ConfigError(f"'{rname}' cannot be used as a repository name", label, ln)
                if not isinstance(rval, dict):
                    raise ConfigError(f"repository '{rname}' must be a table: write [repo.{toml_key(rname)}]",
                                      label, ln)
                old = cfg.repo(rname)
                if old is not None:
                    raise ConfigError(f"repository '{rname}' is already defined at {old.file}:{old.line}", label, ln)
                cur = Repo(rname, label, ln)
                cfg.repos.append(cur)
                for k, v in rval.items():
                    kln = loc.line("repo", rname, k)
                    what = _where(f"repo.{toml_key(rname)}", k)
                    if k == "include":
                        includes.append((v, ("repo", rname, k)))
                        warn("in TOML this 'include' belongs to the repository table above it; write it as "
                             "[include] files = [...] (it is still used)", "repo", rname, k)
                        continue
                    if k not in TOML_REPO_KEYS:
                        hint = _suggest(k, TOML_REPO_KEYS) or " (repository keys: server, mirrors, signatures, usage)"
                        warn(f"unknown repository key {what}{hint} - ignored", "repo", rname, k)
                        continue
                    kind, _many = REPO_KEYS[k]
                    vv = _toml_value(kind, k, what, v, label, kln)
                    if k == "server":
                        cur.servers += [(u, f"{label}:{kln}") for u in vv]
                    elif k == "mirrors":
                        for mf in vv:
                            urls = read_mirrorlist_text(_read(mf, root, cfg, label, kln, "mirror list"), mf)
                            if not urls:
                                raise ConfigError(f"mirror list {mf} has no mirrors (all lines are comments)",
                                                  label, kln)
                            cur.mirror_files.append(mf)
                            cur.servers += [(u, mf) for u in urls]
                    elif k == "signatures":
                        cur.signatures = vv
                    else:
                        cur.usage = vv
        elif name == "include":
            if isinstance(val, dict):
                for k, v in val.items():
                    if k == "files":
                        includes.append((v, ("include", k)))
                    else:
                        warn(f"unknown key {_where('include', k)} (use: files = [...]) - ignored", "include", k)
            else:
                includes.append((val, ("include",)))
        elif isinstance(val, dict):
            warn(f"unknown table [{name}]{_suggest(name, list(TOML_TABLES) + ['repo', 'include'])} - ignored", name)
        else:
            warn(f"unknown key '{name}' outside of a table{_suggest_toml('', name)} - ignored", name)
    for v, where in includes:
        ln = loc.line(*where)
        for pat in _toml_strings(v, "'files' in [include]", label, ln):
            if not pat:
                raise ConfigError("'files' in [include] has an empty path", label, ln)
            _include(pat, path, root, cfg, depth, label, ln)


# ---- zapis TOML ---------------------------------------------------------------------------------
def toml_str(s):
    """Retezec TOML (escapovani JSON je platne i v TOML)."""
    return json.dumps(str(s), ensure_ascii=False)


def toml_key(k):
    return k if BARE_KEY_RE.match(k) else toml_str(k)


def toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return toml_str(v)


def typed_value(ik, val):
    """Vnitrni hodnota (retezec; u opakovatelnych klicu seznam retezcu) -> hodnota TOML/JSON
    (bool, int, str, seznam slov)."""
    kind, _d, many = GLOBAL_KEYS[ik]
    if many:
        return [w for v in val for w in (v.split() if ik in WORD_LISTS else [v])]
    if kind == "bool":
        return val == "on"
    if kind in ("int0", "int1"):
        return int(val)
    if ik in WORD_LISTS:
        w = val.split()
        return w[0] if len(w) == 1 else w
    return val


TOML_HEADER = ["# LuxOS Package Manager", "# Configuration: /etc/lux/lux.conf"]
# klice, ktere vychozi lux.conf vypisuje vzdy (ostatni jen kdyz jsou nastavene)
TEMPLATE_KEYS = {"general": ("architecture", "color", "candy", "verbose"),
                 "downloads": ("parallel", "check_space", "user"),
                 "security": ("signatures", "local_signatures", "protect"),
                 "packages": ("aur", "review_pkgbuild", "flatpak", "cache_keep")}
ARCH_REPOS = {"core", "extra", "multilib", "core-testing", "extra-testing", "multilib-testing", "core-staging",
              "extra-staging", "multilib-staging", "gnome-unstable", "kde-unstable"}
SEPARATOR_WIDTH = 48
INCLUDE_DEFAULT = "/etc/lux/conf.d/*.conf"


def section_comment(title):
    """'# ── Titulek ────' (stejna sirka jako ve vychozi lux.conf)."""
    head = f"# ── {title} "
    return head + "─" * max(2, SEPARATOR_WIDTH - len(head))


def repo_group(name):
    if name.startswith("luxos"):
        return "LuxOS repositories"
    if name in ARCH_REPOS:
        return "Arch Linux repositories"
    return "Other repositories"


class Entry:
    """Hodnota pro zapis TOML: rows = [(hodnoty, [komentare pred], komentar na konci)] - jeden radek
    puvodniho souboru (u seznamu se zachova jako radek pole, i s komentari)."""

    def __init__(self, value, comments=None, inline=None, rows=None):
        self.value, self.comments, self.inline, self.rows = value, comments or [], inline, rows


def _kv(key, e):
    """Radky 'klic = hodnota' (seznam s komentari po radcich jako viceradkove pole)."""
    out = list(e.comments)
    rows = e.rows or []
    if isinstance(e.value, list) and len(rows) > 1 and all(v for v, _c, _i in rows) and \
            any(c or i for _v, c, i in rows):
        out.append(f"{toml_key(key)} = [")
        for vals, comments, inline in rows:
            out += ["    " + c.strip() for c in comments]
            line = "    " + ", ".join(toml_value(v) for v in vals) + ","
            out.append(line + (f"  {inline}" if inline else ""))
        out.append("]" + (f"  {e.inline}" if e.inline else ""))
        return out
    for _v, c, _i in rows:
        out += c
    inl = [i for i in [e.inline] + [i for _v, _c, i in rows] if i]
    out.append(f"{toml_key(key)} = {toml_value(e.value)}" + ("  " + "  ".join(inl) if inl else ""))
    return out


def render_toml(entries, repos=(), includes=None, full=True, header=None, trailing=None):
    """lux.conf ve formatu TOML. entries: vnitrni klic -> Entry; repos: [{"name", "comments", "inline",
    "keys": [(klic, Entry)]}]; includes: Entry se seznamem souboru nebo None.
    full = hlavni lux.conf (hlavicka, vsechny klice vychozi konfigurace, oddelovace skupin repozitaru);
    jinak (conf.d) jen nastavene klice - vychozi hodnoty by prepsaly hlavni soubor."""
    out = list(TOML_HEADER if header is None else header) if full else list(header or [])
    for table, keys in TOML_TABLES.items():
        lines = []
        for k, ik in keys.items():
            e = entries.get(ik)
            if e is None:
                if not (full and k in TEMPLATE_KEYS.get(table, ())):
                    continue
                d = DEFAULTS[ik]
                e = Entry(typed_value(ik, [d] if GLOBAL_KEYS[ik][2] else d))
            lines += _kv(k, e)
        if lines:
            if out:
                out.append("")
            out += [f"[{table}]"] + lines
    group = None
    for r in repos:
        if full and repo_group(r["name"]) != group:
            group = repo_group(r["name"])
            out += ["", section_comment(group)]
        if out:
            out.append("")
        out += r.get("comments", [])
        out.append(f"[repo.{toml_key(r['name'])}]" + (f"  {r['inline']}" if r.get("inline") else ""))
        for k, e in r["keys"]:
            out += _kv(k, e)
    if includes is not None:
        if full:
            out += ["", section_comment("Additional configuration")]
        if out:
            out.append("")
        out += ["[include]"] + _kv("files", includes)
    if trailing:
        out += [""] + trailing
    return "\n".join(out) + "\n"


def _entries_from(values, lists):
    """{vnitrni klic: hodnota} a {klic: [hodnoty]} (jako Config) -> Entry pro render_toml."""
    entries = {}
    for ik in GLOBAL_KEYS:
        if ik in lists:
            entries[ik] = Entry(typed_value(ik, lists[ik]))
        elif ik in values:
            entries[ik] = Entry(typed_value(ik, values[ik]))
    return entries


def _repo_value(kind, vals):
    if kind == "usage":
        w = " ".join(vals).split()
        return w[0] if len(w) == 1 else w
    return vals[0] if len(vals) == 1 else list(vals)


def parse(path=LUX_CONF, root="", cfg=None, depth=0, file_label=None, text=None):
    """Precte lux.conf (vcetne include a seznamu zrcadel). root = predpona pro cteni (testy, instalator).
    Format (TOML / starsi LuxOS 0.9) se rozpozna u kazdeho souboru zvlast."""
    cfg = cfg or Config()
    label = file_label or path
    if text is None:
        text = _read(path, root, cfg, what="configuration file")
    if detect_format(text) == "toml":
        cfg.formats[label] = "toml"
        _parse_toml(text, path, label, root, cfg, depth)
    else:
        cfg.formats[label] = "old"
        _parse_old(text, path, label, root, cfg, depth)
    if depth == 0:
        validate(cfg)
    return cfg


def _include(pat, path, root, cfg, depth, label, ln):
    """Vlozene soubory (vzor s * nebo jedna cesta, relativni k adresari souboru)."""
    if depth >= MAX_INCLUDE_DEPTH:
        raise ConfigError("too many nested includes", label, ln)
    pat = pat if pat.startswith("/") else os.path.join(os.path.dirname(path), pat)
    if glob.has_magic(pat):
        found = sorted(glob.glob(_prefixed(root, pat)))
        cfg.globs.append((_prefixed(root, pat), found))
        files = [("/" + os.path.relpath(f, root)) if root else f for f in found]
    else:
        files = [pat]
    for f in files:
        cfg.includes.append(f)
        parse(f, root, cfg, depth + 1)


def _parse_old(text, path, label, root, cfg, depth):
    """Format LuxOS 0.9 ("klic hodnota", bloky "repo NAZEV" s odsazenymi radky)."""
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
            _include(val, path, root, cfg, depth, label, ln)
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


def validate(cfg):
    for r in cfg.repos:
        if not r.servers:
            raise ConfigError(f"repository '{r.name}' has no 'server' or 'mirrors' line", r.file, r.line)
        if r.signatures == "never" and not all(u.startswith("file://") for u, _o in r.servers):
            raise ConfigError(f"'signatures never' is only allowed for a local repository (file://), "
                              f"'{r.name}' downloads from the internet", r.file, r.line)


def to_dict(cfg):
    """Konfigurace jako slovnik (stabilni API pro lux, lux system, LuxOS Care...; viz load()).

    {"general": {"architecture": "auto", "color": True, ...}, "downloads": {...}, "security": {...},
     "packages": {"aur": True, "review_pkgbuild": True, "flatpak": True, "cache_keep": 2, "hold": [...], ...},
     "paths": {"database": None, "cache": [], ...},
     "repos": [{"name", "servers": [adresy vcetne zrcadel], "server": [jen z klice server],
                "mirrors": [soubory], "signatures": "required"|"optional"|"never"|None (= globalni),
                "usage": ["sync", ...] nebo ["all"], "file", "line"}],
     "include": [vlozene soubory], "files": [prectene soubory], "formats": {soubor: "toml"|"old"},
     "warnings": ["soubor:radek: zprava"]}
    Hodnoty jsou vzdy doplnene vychozimi (bool, int, str, seznam slov)."""
    out = {}
    for table, keys in TOML_TABLES.items():
        out[table] = {}
        for k, ik in keys.items():
            kind, _d, many = GLOBAL_KEYS[ik]
            if many:
                vals = cfg.lists.get(ik)
                if vals is None:
                    vals = [DEFAULTS[ik]] if ik in DEFAULTS else []
                out[table][k] = typed_value(ik, vals)
            else:
                v = cfg.get(ik)
                if v is None:
                    out[table][k] = None
                elif ik in WORD_LISTS:
                    out[table][k] = " ".join(v.split())
                else:
                    out[table][k] = typed_value(ik, v)
    out["repos"] = [{
        "name": r.name,
        "servers": [u for u, _o in r.servers],
        "server": [u for u, o in r.servers if o not in r.mirror_files],
        "mirrors": list(r.mirror_files),
        "signatures": r.signatures,
        "usage": (r.usage or "all").split(),
        "file": r.file, "line": r.line,
    } for r in cfg.repos]
    out["include"] = list(cfg.includes)
    out["files"] = list(cfg.sources)
    out["formats"] = dict(cfg.formats)
    out["warnings"] = [format_warning(w) for w in cfg.warnings]
    return out


def format_warning(w):
    file, line, msg = w
    return f"{file}:{line}: {msg}" if line else f"{file}: {msg}"


def load(path=LUX_CONF, root="", user=False):
    """Stabilni API: rozparsovana /etc/lux/lux.conf (vcetne conf.d) jako slovnik - viz to_dict().
    user=True: [packages] aur, review_pkgbuild, flatpak, cache_keep i z ~/.config/lux/lux.conf.
    Rozbita konfigurace: ConfigError (str = "soubor:radek: zprava")."""
    if user:
        vals, cfg = cli_settings(path, root=root)
        d = to_dict(cfg)
        for ik, v in vals.items():
            t, k = TOML_PLACE[ik]
            d[t][k] = typed_value(ik, v)
        return d
    return to_dict(parse(path, root))


def comparable(cfg, sort=False):
    """Obsah konfigurace pro porovnani (bez souboru, radku a komentaru; sort = bez poradi repozitaru)."""
    d = to_dict(cfg)
    for r in d["repos"]:
        del r["file"], r["line"], r["server"]
    for k in ("include", "files", "formats", "warnings"):
        del d[k]
    if sort:
        d["repos"].sort(key=lambda r: r["name"])
    return d


def engine_options(cfg):
    """Nastaveni jadra (libalpm) z konfigurace: ([(direktiva, hodnota nebo None)], [repozitare]).
    Repozitar: {"name", "SigLevel": [..], "Usage": [..], "Server": [..]} (jen nastavene klice).
    Pouziva ho lux_alpm.py primo (bez mezisouboru) i render_engine() pro nastroje jadra v C."""
    opts = []
    words = lambda k: " ".join(cfg.lists.get(k, []) or ([cfg.get(k)] if cfg.get(k) else []))  # noqa: E731
    for key, (kind, directive, many) in GLOBAL_KEYS.items():
        if directive is None:
            continue
        if kind == "bool":
            on = cfg.get(key) == "on"
            if key in ("download-timeout", "download-sandbox"):
                on = not on          # Disable...
            if on:
                opts.append((directive, None))
        elif kind == "sig":
            v = SIG[cfg.get(key)]
            if key == "local-signatures" and cfg.get(key) == "optional":
                v = "Optional"       # soubory .pkg.tar.* z disku (AUR): jako dosud
            opts.append((directive, v))
        elif key == "download-user":
            if cfg.get(key) not in ("none", "root"):
                opts.append((directive, cfg.get(key)))
        elif many and kind == "path":
            for v in cfg.lists.get(key, []):
                opts.append((directive, v))
        elif many:
            if key == "protect" and key not in cfg.lists:
                opts.append((directive, DEFAULTS["protect"]))
            for v in cfg.lists.get(key, []):
                opts.append((directive, v))
        else:
            v = words(key)
            if v:
                opts.append((directive, v))
    repos = []
    for r in cfg.repos:
        d = {"name": r.name}
        if r.signatures:
            d["SigLevel"] = [SIG[r.signatures]]
        if r.usage:
            d["Usage"] = [" ".join(USAGE[u] for u in r.usage.split())]
        d["Server"] = [url for url, _o in r.servers]
        repos.append(d)
    return opts, repos


def render_engine(cfg, source_label=LUX_CONF):
    """Konfigurace nastroju jadra v C (syntaxe pacman.conf) + hlavicka se zdroji pro kontrolu cerstvosti."""
    out = [f"# LuxOS: generated from {source_label} by lux-config - do not edit, change lux.conf instead",
           f"#@lux-config\t{VERSION}"]
    for s in sources_with_self(cfg):
        out.append("#@source\t" + "\t".join(stat_sig(s)))
    for pat, files in cfg.globs:
        out.append("#@glob\t" + "\t".join([pat] + [os.path.basename(f) for f in files]))
    out.append("[options]")
    opts, repos = engine_options(cfg)
    out += [d if v is None else f"{d} = {v}" for d, v in opts]
    for r in repos:
        out.append("")
        out.append(f"[{r['name']}]")
        for k in ("SigLevel", "Usage", "Server"):
            out += [f"{k} = {v}" for v in r.get(k, [])]
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


def cli_settings(conf=LUX_CONF, user=True, root=""):
    """Nastaveni lux (aur, review-pkgbuild, flatpak, clean-keep): systemove, pak uzivatelske
    (~/.config/lux/lux.conf v kterem koli formatu; v TOML [packages] aur = false ...)."""
    cfg = parse(conf, root)
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


# Zalohy konfigurace, ktere nechava libalpm (lux-engine, zaplata 0003; do LuxOS 1.0 jmena pacmanu)
NEW_SUFFIX, SAVE_SUFFIX, ORIG_SUFFIX = ".luxnew", ".luxsave", ".luxorig"
OLD_SUFFIXES = {".pacnew": NEW_SUFFIX, ".pacsave": SAVE_SUFFIX, ".pacorig": ORIG_SUFFIX}


def new_versions(conf):
    """Cesty k nove verzi konfigurace z aktualizace (conf.luxnew, starsi conf.pacnew)."""
    return [conf + NEW_SUFFIX, conf + ".pacnew"]


# Repozitare LuxOS se presunuly (LuxOS 0.9.7); stara adresa dal funguje, prevod pouzije novou
MOVED_SERVERS = {"https://lsl.lux-ai.cz/luxos/": "https://luxos.lux-ai.cz/repo/"}


def moved_server(url):
    for old, new in MOVED_SERVERS.items():
        if url.startswith(old):
            return new + url[len(old):]
    return url


def update_moved_servers(conf=LUX_CONF):
    """Stara adresa repozitaru LuxOS v /etc/lux/lux.conf -> nova (jen adresy serveru, zbytek beze zmeny;
    oba formaty). Kdyz se lux.conf lisila od baliku jen adresou, aktualizace nechala lux.conf.luxnew
    (starsi jadro lux.conf.pacnew) se stejnym obsahem - ten se po uprave smaze. Vraci True pri zmene."""
    try:
        with open(conf, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False
    out = []
    toml = detect_format(text) == "toml"
    for line in text.splitlines(keepends=True):
        if toml:
            for old, newp in MOVED_SERVERS.items():
                line = line.replace('"' + old, '"' + newp).replace("'" + old, "'" + newp)
        else:
            m = re.match(r"^(\s*server\s+)(\S+)(.*)$", line, re.S)
            if m and moved_server(m.group(2)) != m.group(2):
                line = m.group(1) + moved_server(m.group(2)) + m.group(3)
        out.append(line)
    new = "".join(out)
    changed = new != text
    if changed:
        atomic_write(conf, new, os.stat(conf).st_mode & 0o7777)
    for pn in new_versions(conf):
        try:
            with open(pn, encoding="utf-8") as f:
                if f.read() == new:
                    os.unlink(pn)
                    changed = True
        except OSError:
            pass
    return changed


DRIVERS_REPO = "luxos-drivers"
DRIVERS_STAMP = "/var/lib/lux/luxos-drivers-repo"
LUXOS_SERVER = "https://luxos.lux-ai.cz/repo/$repo/$arch"


def _repo_header_re(name):
    """Hlavicka [repo.NAZEV] (i s uvozovkami) v TOML."""
    q = re.escape(name)
    return re.compile(r"""^[ \t]*\[[ \t]*repo[ \t]*\.[ \t]*(%s|"%s"|'%s')[ \t]*\][ \t]*(#.*)?$""" % (q, q, q), re.M)


def has_repo_text(text, name):
    """Je repozitar v textu lux.conf (oba formaty; bez cteni seznamu zrcadel - chroot, testy)?"""
    if detect_format(text) == "toml":
        return _repo_header_re(name).search(text) is not None
    return re.search(r"^repo[ \t]+%s[ \t]*(#.*)?$" % re.escape(name), text, re.M) is not None


def _table_span(lines, start):
    """Radky tabulky TOML od hlavicky start: (start, konec) - konec pred dalsi hlavickou bez komentaru
    a prazdnych radku, ktere k ni patri."""
    end = start + 1
    while end < len(lines) and not _HEADER_RE.match(lines[end]) and not lines[end].lstrip().startswith("[["):
        end += 1
    while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    return start, end


def toml_insert_repo(text, name, keys, after=None, comment=None):
    """Prida [repo.NAZEV] do textu TOML: za tabulku repozitare after (nebo za posledni repozitar,
    jinak pred [include] / na konec). keys = [(klic, hodnota)]. Ostatni text beze zmeny."""
    lines = text.rstrip("\n").split("\n") if text.strip() else []
    block = ([comment] if comment else []) + [f"[repo.{toml_key(name)}]"] + \
        [f"{toml_key(k)} = {toml_value(v)}" for k, v in keys]
    pos = None
    targets = [after] if after else []
    for i, ln in enumerate(lines):
        m = _HEADER_RE.match(ln)
        if not m:
            continue
        path = _split_key(m.group(1))
        if path[:1] == ["repo"] and len(path) == 2 and (not targets or path[1] in targets):
            pos = _table_span(lines, i)[1]
    if pos is None and after:
        return toml_insert_repo(text, name, keys, None, comment)
    if pos is None:
        for i, ln in enumerate(lines):
            m = _HEADER_RE.match(ln)
            if m and _split_key(m.group(1))[:1] == ["include"]:
                pos = i
                while pos > 0 and (lines[pos - 1].lstrip().startswith("#") or not lines[pos - 1].strip()):
                    pos -= 1
                break
    if pos is None:
        pos = len(lines)
    new = lines[:pos] + ([""] if pos > 0 else []) + block + ([""] if pos < len(lines) and lines[pos].strip() else [])
    return "\n".join(new + lines[pos:]) + "\n"


def toml_remove_repo(text, name):
    """Text TOML bez tabulky [repo.NAZEV] (a komentare tesne nad ni)."""
    lines = text.split("\n")
    rx = _repo_header_re(name)
    for i, ln in enumerate(lines):
        if rx.match(ln):
            start, end = _table_span(lines, i)
            while start > 0 and lines[start - 1].lstrip().startswith("#") and \
                    not lines[start - 1].lstrip().startswith("# ──"):
                start -= 1
            del lines[start:end]
            out = "\n".join(lines)
            return re.sub(r"\n{3,}", "\n\n", out)
    return text


def toml_set(text, table, key, value):
    """Nastavi klic v tabulce textu TOML (radek klice se nahradi i s komentarem na konci zachovanym;
    chybejici klic na konec tabulky; chybejici tabulka pred prvni [repo.*]/[include] nebo na konec)."""
    lines = text.rstrip("\n").split("\n") if text.strip() else []
    kv = f"{toml_key(key)} = {toml_value(value)}"
    for i, ln in enumerate(lines):
        m = _HEADER_RE.match(ln)
        if not (m and _split_key(m.group(1)) == [table]):
            continue
        start, end = _table_span(lines, i)
        for j in range(start + 1, end):
            km = _KEY_LINE_RE.match(lines[j])
            if km and _split_key(km.group(1)) == [key]:
                body = strip_comment(lines[j])
                inline = lines[j][len(body):].strip()
                if "[" in body and "]" not in body:      # viceradkove pole: nahradit cele
                    k = j + 1
                    while k < end and "]" not in strip_comment(lines[k]):
                        k += 1
                    del lines[j + 1:k + 1]
                lines[j] = kv + (f"  {inline}" if inline else "")
                return "\n".join(lines) + "\n"
        lines.insert(end, kv)
        return "\n".join(lines) + "\n"
    order = list(TOML_TABLES)
    pos = len(lines)
    for i, ln in enumerate(lines):
        m = _HEADER_RE.match(ln)
        if not m:
            continue
        p = _split_key(m.group(1))
        if p[0] in ("repo", "include") or (p[0] in order and table in order and order.index(p[0]) > order.index(table)):
            pos = i
            while pos > 0 and (lines[pos - 1].lstrip().startswith("#") or not lines[pos - 1].strip()):
                pos -= 1
            break
    block = [f"[{table}]", kv]
    new = lines[:pos] + ([""] if pos > 0 else []) + block + \
        ([""] if pos < len(lines) and lines[pos].strip() else []) + lines[pos:]
    return "\n".join(new) + "\n"


def without_drivers_repo(text):
    """lux.conf bez repozitare [luxos-drivers] (vychozi konfigurace pred LuxOS 0.9.10)."""
    if detect_format(text) == "toml":
        return toml_remove_repo(text, DRIVERS_REPO)
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
    changed = False
    if has_repo_text(text, "luxos") and not has_repo_text(text, DRIVERS_REPO):
        if detect_format(text) == "toml":
            after = "luxos-apps" if has_repo_text(text, "luxos-apps") else "luxos"
            new = toml_insert_repo(text, DRIVERS_REPO, [("server", LUXOS_SERVER)], after=after)
        else:
            new = text.rstrip("\n") + "\n" + (
                "\n# overene ovladace tiskaren a skeneru vyrobcu (z AUR, kazda verze zkontrolovana, podepsane)\n"
                f"repo {DRIVERS_REPO}\n    server  {LUXOS_SERVER}\n")
        atomic_write(conf, new, os.stat(conf).st_mode & 0o7777)
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
    # klice, ktere v pacman.conf chybely, maji v pacmanu jinou vychozi hodnotu nez v lux.conf
    pacman_defaults = {"color": "off", "candy": "off", "check-space": "off", "verbose-lists": "off",
                       "parallel-downloads": "1", "download-user": "none"}
    for k, v in pacman_defaults.items():
        glob_vals.setdefault(k, v)
    values, out_lists = {}, {}
    for k in GLOBAL_KEYS:
        if k in glob_vals and glob_vals[k] != DEFAULTS.get(k):
            if k == "signatures" and glob_vals[k] == "never":
                warnings.append("SigLevel = Never for all repositories is not allowed any more - "
                                "signatures are required")
                continue
            values[k] = glob_vals[k]
        vals = [v for v in lists.get(k, []) if not (k == "protect" and v == DEFAULTS["protect"])]
        if vals:
            out_lists[k] = vals
    out_repos = []
    for r in repos:
        if not r["servers"] and not r["mirrors"]:
            warnings.append(f"repository [{r['name']}] has no servers - skipped")
            continue
        keys = []
        if r["servers"]:
            keys.append(("server", Entry(_repo_value("url", r["servers"]))))
        if r["mirrors"]:
            keys.append(("mirrors", Entry(_repo_value("path", r["mirrors"]))))
        if r["sig"] and r["sig"] != "required":
            if r["sig"] == "never" and not all(s.startswith("file://") for s in r["servers"]):
                warnings.append(f"[{r['name']}]: SigLevel = Never kept only for local repositories - "
                                "signatures are now required")
            else:
                keys.append(("signatures", Entry(r["sig"])))
        if r["usage"]:
            keys.append(("usage", Entry(_repo_value("usage", [r["usage"]]))))
        out_repos.append({"name": r["name"], "keys": keys})
    header = TOML_HEADER + ["# (converted from pacman.conf; all keys: /usr/share/doc/lux/lux.md)"]
    text = render_toml(_entries_from(values, out_lists), out_repos, Entry([INCLUDE_DEFAULT]), header=header)
    return text, extra, warnings


# ---- prevod formatu LuxOS 0.9 ("klic hodnota") na TOML (LuxOS 1.0) ---------------------------------
OLD_FORMAT_SUFFIX = ".old-format"
FORMAT_STAMP = "/var/lib/lux/config-format-toml"
# komentare vychozich lux.conf LuxOS 0.9 (balik, instalator, live ISO, prevod pacman.conf, pridani
# [luxos-drivers]) - popisovaly stary format nebo nahrazuji je oddelovace; uzivatelske komentare zustanou
OLD_DEFAULT_COMMENTS = {
    "# lux itself",
    "# LuxOS repositories (packages signed with the key from luxos-keyring)",
    "# overene ovladace tiskaren a skeneru vyrobcu (z AUR, kazda verze zkontrolovana, podepsane)",
    "# Arch Linux repositories (download mirrors: /etc/lux/mirrorlist)",
    "# more files in the same format (repositories added by packages or the administrator)",
    "# required | optional | never (never only for local file:// repos)",
    "# packages installed from a file (AUR builds)",
    "# packages from AUR (built on this computer)",
    "# offer to read the build script before building from AUR",
    "# lux update also updates Flatpak apps",
    '# package versions kept in the cache by "lux clean"',
}
OLD_HEADER_STARTS = ("# LuxOS - configuration of the lux package manager", "# LuxOS live system - configuration")


def migrate_text(text, full=True):
    """Text ve formatu LuxOS 0.9 -> (text TOML, [varovani]). Hodnoty 1:1, opakovane radky (hold ...)
    jako jedno pole (radek po radku i s komentari), komentare zustanou u klice/repozitare, pod kterym
    byly. full = hlavni lux.conf (hlavicka, vsechny klice); jinak soubor z conf.d (jen nastavene klice).
    Text se nekontroluje - volajici porovna vysledek s puvodni konfiguraci (migrate_file)."""
    lines = text.splitlines()
    warnings = []
    header = None
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    # uvodni blok komentaru (odstavce oddelene prazdnym radkem): vychozi hlavicka LuxOS 0.9 se nahradi
    # novou; vlastni zustane jako hlavicka, posledni odstavec tesne nad prvnim klicem patri tomu klici
    paras = [[ln.strip() for ln in p.splitlines()] for p in "\n".join(lines[:i]).strip("\n").split("\n\n")
             if p.strip()]
    pending = []
    if i >= len(lines):        # jen komentare: uz je to platny TOML (vse vychozi)
        return "\n".join(lines).rstrip("\n") + "\n", warnings
    if paras and paras[0][0].startswith(OLD_HEADER_STARTS):
        paras = []
    if paras:
        if not full or (i > 0 and not lines[i - 1].strip()):
            head, pending = paras, []
        else:
            head, pending = paras[:-1], paras[-1]
        if head:
            header = []
            for p in head:
                header += ([""] if header else []) + p
    rows = {}                 # vnitrni klic -> [(hodnota, komentare, inline)]
    repos, cur = [], None
    include_rows = []

    def keep(c):
        return c.strip() not in OLD_DEFAULT_COMMENTS

    for raw in lines[i:]:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if keep(stripped):
                pending.append(stripped)
            continue
        body = strip_comment(raw)
        inline = raw[len(body):].strip() or None
        if inline and not keep(inline):
            inline = None
        indented = raw[:1] in (" ", "\t")
        line = body.strip()
        comments, pending = pending, []
        m = re.match(r"^([A-Z_]+)=(\S*)$", line)
        if m and m.group(1) in LEGACY_SHELL and not indented:
            key = LEGACY_SHELL[m.group(1)]
            val = m.group(2).strip("\"'")
            if GLOBAL_KEYS[key][0] == "bool":
                val = "on" if val not in ("0", "") else "off"
            rows.setdefault(key, []).append((val, comments, inline))
            cur = None
            continue
        parts = line.split(None, 1)
        key = parts[0].lower()
        val = parts[1].strip() if len(parts) > 1 else ""
        if indented and cur is not None:
            cur["rows"].setdefault(key, []).append((val, comments, inline))
            continue
        cur = None
        if key == "repo":
            cur = {"name": val, "comments": comments, "inline": inline, "rows": {}}
            repos.append(cur)
        elif key == "include":
            include_rows.append((val, comments, inline))
        elif key in GLOBAL_KEYS:
            rows.setdefault(key, []).append((val, comments, inline))
        else:
            # neznamy klic (stary format ho odmita) - zachovat aspon jako komentar
            pending = comments + [f"# {line}" + (f"  {inline}" if inline else "")]
    trailing = pending

    entries = {}
    for ik, rs in rows.items():
        kind, _d, many = GLOBAL_KEYS[ik]
        if many:
            value = typed_value(ik, [v for v, _c, _i in rs])
            ent_rows = [((v.split() if ik in WORD_LISTS else [v]), c, inl) for v, c, inl in rs]
            entries[ik] = Entry(value, rows=ent_rows)
        else:
            # posledni hodnota plati (jako v parse); komentare vsech radku zustanou
            v, _c, _i = rs[-1]
            entries[ik] = Entry(typed_value(ik, _check_value(kind, ik, v, None, None)),
                                rows=[([], c, inl) for _v, c, inl in rs])
    out_repos = []
    for r in repos:
        keys = []
        for k in TOML_REPO_KEYS:
            rs = r["rows"].get(k)
            if not rs:
                continue
            kind = REPO_KEYS[k][0]
            if k in ("signatures", "usage"):
                v = rs[-1][0].lower()
                value = _repo_value(kind, [v]) if k == "usage" else v
                keys.append((k, Entry(value, rows=[([], c, inl) for _v, c, inl in rs])))
            else:
                value = _repo_value(kind, [v for v, _c, _i in rs])
                keys.append((k, Entry(value, rows=[([v], c, inl) for v, c, inl in rs])))
        for k, rs in r["rows"].items():
            if k not in TOML_REPO_KEYS:
                for v, c, inl in rs:
                    r["comments"] = r["comments"] + c + [f"# {k} {v}"]
        out_repos.append({"name": r["name"], "comments": r["comments"], "inline": r["inline"], "keys": keys})
    includes = None
    if include_rows:
        includes = Entry([v for v, _c, _i in include_rows], rows=[([v], c, inl) for v, c, inl in include_rows])
    return render_toml(entries, out_repos, includes, full=full, header=header, trailing=trailing), warnings


def migrate_file(path, root="", main=None, dry_run=False, template=TEMPLATE):
    """Jeden soubor ve formatu LuxOS 0.9 -> TOML; puvodni zustane jako SOUBOR.old-format.
    Vysledek musi dat presne stejnou konfiguraci (jadro i nastaveni lux), jinak se nic nezapise.
    Hlavni lux.conf shodna s vychozi konfiguraci = presne vychozi soubor baliku (bez .luxnew priste).
    Vraci (stav, [varovani]): "migrated", "already" (uz je TOML) nebo "dry-run"; chyba = ConfigError."""
    real = _prefixed(root, path)
    with open(real, encoding="utf-8") as f:
        text = f.read()
    if detect_format(text) == "toml":
        return "already", []
    if main is None:
        # hlavni lux.conf (ne conf.d, ne ~/.config/lux/lux.conf - tam jen nastavene klice: vychozi
        # hodnoty by prepsaly systemove nastaveni)
        main = os.path.basename(path) == "lux.conf" and "/conf.d/" not in path and "/.config/" not in path \
            and not (os.environ.get("XDG_CONFIG_HOME") and path.startswith(os.environ["XDG_CONFIG_HOME"]))
    sub = not main

    def load_text(t):
        c = Config()
        parse(path, root, cfg=c, depth=1 if sub else 0, text=t)
        validate(c)
        return c

    before = load_text(text)
    new, warns = migrate_text(text, full=main)
    try:
        after = load_text(new)
    except ConfigError as e:
        raise ConfigError(f"conversion to the new format failed ({e}) - the file was not changed", path)
    tmpl_used = None
    if main and template:
        try:
            with open(_prefixed(root, template), encoding="utf-8") as f:
                tmpl = f.read()
            # poradi repozitaru stejne, jen [luxos-drivers] muze byt jinde (LuxOS 0.9.10 ho pridal na konec)
            tcfg = load_text(tmpl)
            others = lambda c: [r.name for r in c.repos if r.name != DRIVERS_REPO]  # noqa: E731
            if comparable(tcfg, sort=True) == comparable(after, sort=True) and others(tcfg) == others(after) \
                    and not _user_comments(new, tmpl):
                new = tmpl_used = tmpl
                after = load_text(new)
        except (OSError, ConfigError):
            pass
    # vlozene soubory (conf.d) se v TOML ctou az po vsech repozitarich souboru: repozitar pod radkem
    # include (napr. [luxos-drivers] pridany LuxOS 0.9.10 na konec) se posune pred ne
    a, b = comparable(before, sort=True), comparable(after, sort=True)
    order_a, order_b = [r.name for r in before.repos], [r.name for r in after.repos]
    if order_a != order_b and new != tmpl_used:
        warns = warns + ["repository order changed (included files are read after the repositories of this "
                         f"file): {' '.join(order_a)} -> {' '.join(order_b)}"]
    if a != b:
        raise ConfigError("conversion to the new format would change the configuration - the file was not "
                          "changed (convert it by hand, see /usr/share/doc/lux/lux.md)", path)
    if dry_run:
        return "dry-run", warns + [new]
    mode = os.stat(real).st_mode & 0o7777
    keep = real + OLD_FORMAT_SUFFIX
    if not os.path.exists(keep):
        shutil.copy2(real, keep)
    atomic_write(real, new, mode)
    return "migrated", warns


def _user_comments(new, template):
    """Komentare noveho textu, ktere ve vychozi konfiguraci nejsou (vlastni poznamky spravce)."""
    have = {ln.strip() for ln in template.splitlines() if ln.strip().startswith("#")}
    return [ln.strip() for ln in new.splitlines() if ln.strip().startswith("#") and ln.strip() not in have]


def migrate_all(conf=LUX_CONF, root="", dry_run=False, template=TEMPLATE, files=None):
    """lux.conf a vsechny soubory z conf.d (i vlozene jinym vzorem) ve starem formatu -> TOML.
    Vraci [(soubor, stav, [varovani] nebo chyba)]."""
    results = []
    explicit = files is not None
    if files is None:
        files = [conf]
        try:
            cfg = parse(conf, root)
            files += [f for f in cfg.includes if f not in files]
        except ConfigError:
            d = os.path.join(os.path.dirname(conf), "conf.d")
            files += sorted("/" + os.path.relpath(f, root) if root else f
                            for f in glob.glob(os.path.join(_prefixed(root, d), "*.conf")))
    for f in files:
        try:
            main = True if f == conf else (None if explicit else False)
            state, warns = migrate_file(f, root, main=main, dry_run=dry_run, template=template)
            results.append((f, state, warns))
        except (ConfigError, OSError) as e:
            results.append((f, "error", str(e)))
    return results


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
    """Prida repozitar do lux.conf (napr. multilib pro Steam) za posledni repozitar, ve formatu souboru.
    Uz nastaveny = nic."""
    cfg = parse(conf)
    if cfg.repo(name) is not None:
        return False
    with open(conf, encoding="utf-8") as f:
        text = f.read()
    if detect_format(text) == "toml":
        new = toml_insert_repo(text, name, [("server", server)] if server else [("mirrors", mirrors or MIRRORLIST)])
    else:
        block = f"\nrepo {name}\n" + (f"    server  {server}\n" if server else
                                      f"    mirrors  {mirrors or MIRRORLIST}\n")
        new = text.rstrip("\n") + "\n" + block
    parse(conf, text=new)       # kontrola pred zapisem
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
                    cfg = parse(f)
                except ConfigError as e:
                    print(f"lux: error in the configuration: {e}", file=sys.stderr)
                    rc = 1
                    continue
                for w in cfg.warnings:
                    print(f"lux: warning: {format_warning(w)}", file=sys.stderr)
                old = [x for x, fmt in cfg.formats.items() if fmt == "old"]
                for x in old:
                    print(f"lux: {x} uses the old LuxOS 0.9 format (still read); convert it with: "
                          "lux config migrate", file=sys.stderr)
                print(f"{f}: OK" + (f" ({len(cfg.warnings)} warning{'s' if len(cfg.warnings) != 1 else ''})"
                                    if cfg.warnings else ""))
            return rc
        if cmd == "migrate":
            dry = "--dry-run" in args
            files = [a for a in args if not a.startswith("-")] or None
            if files is None and not dry and os.geteuid() != 0 and not _can_write(conf):
                print("lux-config: migrate needs administrator rights", file=sys.stderr)
                return 1
            rc = 0
            for f, state, info in migrate_all(conf, dry_run=dry, files=files):
                if state == "error":
                    print(f"lux: {info}", file=sys.stderr)
                    rc = 1
                    continue
                if state == "dry-run":
                    for w in info[:-1]:
                        print(f"lux: note: {f}: {w}", file=sys.stderr)
                    print(f"# ---- {f} (new format)")
                    sys.stdout.write(info[-1])
                    continue
                for w in info:
                    print(f"lux: note: {f}: {w}", file=sys.stderr)
                if state == "migrated":
                    print(f"{f}: converted to the new format (original: {f}{OLD_FORMAT_SUFFIX})")
                else:
                    print(f"{f}: already in the new format")
            return rc
        if cmd == "json":
            print(json.dumps(load(conf), ensure_ascii=False, indent=2))
            return 0
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
            if "." in key:          # jmeno TOML: packages.cache_keep, downloads.parallel ...
                t, _s, k = key.partition(".")
                key = TOML_TABLES.get(t, {}).get(k, key)
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
