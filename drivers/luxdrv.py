#!/usr/bin/env python3
"""LuxOS - overene ovladace z AUR (tiskarny, skenery) pro repozitar [luxos-drivers].

  drivers/luxdrv.py discover              kandidati z AUR podle vyrobcu (drivers/vendors.json)
  drivers/luxdrv.py verify [BALIK...]     overit (aktualni commit v AUR; zmena = nove overeni + diff)
  drivers/luxdrv.py build-list            co sestavit (overene a jeste nesestavene) -> out/drivers/build-list.tsv
  drivers/luxdrv.py fetch [BALIK...]      pro sestaveni (napr. GitHub Actions): zapichnute commity z AUR + zdroje,
                                          kazdy zdroj musi mit sha256 z manifestu (nic se znovu neoveruje)
  drivers/luxdrv.py closure BALIK...      baliky + overene baliky, na kterych zavisi (poradi pro sestaveni)
  drivers/luxdrv.py index DIR [OUT]       mapa zarizeni -> balik z hotovych baliku (PPD 1284, udev USB ID)
                                          -> OUT/drivers-index.json a OUT/drivers-usb.tsv (vychozi state/)
  drivers/luxdrv.py report                souhrn (overeno / odmitnuto a proc)

Zasady (pri KAZDE zmene v AUR se overuje znovu cely PKGBUILD i rozdil proti poslednimu overenemu):
  - PKGBUILD mimo funkce jen prirazeni bez $(...) a `...` (nacteni nesmi nic spustit); nacita se
    bez site (unshare -rn) a s prazdnym prostredim
  - zdroje jen z domen vyrobce (vendors.json), zadny git/svn; kazdy zdroj ma kontrolni soucet (ne SKIP),
    stazeny soubor mu odpovida a jeho sha256 se zapichne do state/manifest.json
  - ve funkcich zadna sit (curl, wget, git, nc, /dev/tcp ...), zadne "| sh", eval, base64 -d,
    sudo, setuid/setgid, zapis mimo $pkgdir/$srcdir
  - .install jen povolene prikazy (restart CUPS, ldconfig, udev, cache ikon ...), bez site
  - novy commiter v AUR = rucni kontrola (nesestavi se)
  - knihovny z AUR, ktere ovladace potrebuji (vendors.json "dependencies"), prochazi stejnymi pravidly;
    povolene domeny zdroju ma kazda zvlast (domena[/cesta])
  - zaplaty LuxOS (drivers/patches/BALIK/*.patch, patch -p1) se aplikuji PRED kontrolou - overuje se
    vysledny PKGBUILD; sha256 zaplat je v manifestu a sestaveni pouzije jen presne tyto zaplaty
  - volitelne LUXOS_DRIVERS_REVIEW=prikaz: dostane JSON (PKGBUILD, .install, diff) na stdin, nenulovy
    navratovy kod = odmitnuto (napr. kontrola LuxAI)
Co neprojde, se NESESTAVI - duvody jsou v state/rejected.json.
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.environ.get("LUXDRV_STATE", os.path.join(HERE, "state"))
PATCHES = os.environ.get("LUXDRV_PATCHES", os.path.join(HERE, "patches"))
WORK = os.environ.get("LUXDRV_WORK", os.path.join(ROOT, "out", "drivers"))
AUR = os.environ.get("LUXDRV_AUR", "https://aur.archlinux.org")
MAX_SOURCE = 700 * 1024 * 1024
CARCH = "x86_64"

CHECKSUM_ALGOS = ("sha512", "sha384", "sha256", "sha224", "b2", "sha1", "md5", "ck")
STRONG = ("sha512", "sha384", "sha256", "sha224", "b2")

# Prikazy ve funkcich PKGBUILD, ktere nikdy neprojdou
FORBIDDEN = [
    (r"(^|[\s;|&(`])(curl|wget|aria2c|ftp|tftp|nc|ncat|netcat|socat|ssh|scp|sftp|rsync|telnet)(\s|$)", "network tool"),
    (r"(^|[\s;|&(`])git\s+(clone|fetch|pull|ls-remote|submodule)", "network (git)"),
    (r"/dev/(tcp|udp)/", "network (/dev/tcp)"),
    (r"\|\s*(ba|z|da|k)?sh\b", "pipe into a shell"),
    (r"(^|[\s;|&(])eval(\s|$)", "eval"),
    (r"(^|[\s;|&(`])(ba|z|da|k)?sh\s+(-[a-z]+\s+)*-[a-z]*c\b", "inline shell code"),
    (r"\bxargs\s+(-\S+\s+)*(ba|z|da|k)?sh\b", "inline shell code"),
    (r"(^|[\s;|&(])(source|\.)\s+<\(", "sourcing generated code"),
    (r"base64\s+(-d|--decode)|xxd\s+-r|openssl\s+enc", "decoding hidden data"),
    (r"(^|[\s;|&(])python[0-9.]*\s+-c|(^|[\s;|&(])perl\s+-e\b|(^|[\s;|&(])ruby\s+-e", "inline interpreter code"),
    (r"(^|[\s;|&(])(sudo|su|doas|pkexec|runuser)(\s|$)", "privilege escalation"),
    (r"(^|[\s;|&(])systemctl(\s|$)", "systemctl during build"),
    (r"chmod\s+([-+=a-z]*\s+)*[ugoa]*\+[rwx]*s|chmod\s+(-[a-zA-Z]+\s+)*0?[2467][0-7]{3}\b", "setuid/setgid"),
    (r"install\s+(-[a-zA-Z]*\s+)*-m\s*0?[2467][0-7]{3}\b|install\s+(-[a-zA-Z]*)*m0?[2467][0-7]{3}\b", "setuid/setgid"),
    (r"\bcrontab\b|/etc/cron", "cron"),
    (r"(^|[\s;|&(])(dd|mkfs|wipefs|fdisk|parted)(\s|$)", "disk tool"),
    (r"(^|\s)(LD_PRELOAD|PROMPT_COMMAND)=", "environment hijack"),
]
WRITERS = {"cp", "mv", "install", "tee", "rm", "mkdir", "touch", "chmod", "chown", "ln", "rmdir", "truncate", "dd"}
SAFE_PREFIXES = ("$pkgdir", "${pkgdir}", "$srcdir", "${srcdir}", "$startdir", "${startdir}", "\"$pkgdir", "\"${pkgdir}",
                 "\"$srcdir", "\"${srcdir}", "\"$startdir")

# .install: povolene prikazy
INSTALL_OK = {
    "echo", "printf", "true", "false", "return", "local", "if", "then", "else", "elif", "fi", "for", "in", "do",
    "done", "case", "esac", "while", "[", "[[", "test", ":", "ldconfig", "update-desktop-database",
    "gtk-update-icon-cache", "udevadm", "lpadmin", "lpinfo", "lpstat", "cupsctl", "cupsenable", "cupsaccept",
    "cupsdisable", "cupsreject", "grep", "sed", "awk", "cat", "rm", "ln", "mkdir", "chmod", "install",
    "command", "type", "which", "systemctl", "getent", "groupadd", "usermod", "gpasswd", "sleep", "post_install",
    "post_upgrade", "pre_remove", "post_remove", "pre_install", "pre_upgrade", "exit", "set", "read", "cut", "tr",
    "head", "tail", "touch", "mv", "cp", "find", "xargs", "export", "unset", "shift", "break", "continue",
    "semanage", "restorecon", "chcon", "id", "stat", "basename", "dirname", "sort", "uniq", "wc", "ls", "pidof",
    "rmdir", "chown", "chgrp", "readlink", "realpath", "date", "uname", "lsusb",
}
SYSTEMCTL_OK = re.compile(r"systemctl\s+(--[a-z-]+\s+)*(daemon-reload|try-restart|restart|reload|reload-or-restart|"
                          r"is-active|is-enabled|enable|disable)\b(\s+--now)?(\s+[\w@.-]*(cups|saned|scanner|"
                          r"avahi|brscan|epson|canon|smfp|lpd)[\w@.-]*)*\s*($|[;&|)])")


# ---- pomocne ------------------------------------------------------------------------------------
def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def run(cmd, cwd=None, timeout=300, env=None, inp=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env, input=inp)
    return r.returncode, r.stdout, r.stderr


def readtext(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def vendors():
    return load(os.path.join(HERE, "vendors.json"), {})


def vendor_of(name, conf=None):
    conf = conf or vendors()
    if name in conf.get("dependencies", {}):
        return "dep:" + name                # knihovna z AUR, kterou potrebuji overene ovladace
    for v, d in conf.get("vendors", {}).items():
        if any(name.startswith(p) for p in d["prefixes"]):
            return v
    return None


def host_allowed(host, vendor, conf=None, path=None, redirect=False):
    """Domena (a u knihoven i cesta: "github.com/libusb/") patri vyrobci / projektu knihovny.
    redirect=True: u knihoven navic "redirects" (CDN, kam presmeruje povolena adresa - obsah hlida soucet)."""
    conf = conf or vendors()
    host = (host or "").lower().rstrip(".")
    if vendor and vendor.startswith("dep:"):
        d = conf.get("dependencies", {}).get(vendor[4:], {})
        doms = d.get("domains", []) + (d.get("redirects", []) if redirect else [])
    else:
        doms = conf["vendors"].get(vendor, {}).get("domains", [])
    for d in doms:
        dh, _, dp = d.partition("/")
        if (host == dh or host.endswith("." + dh)) and (not dp or (path or "").startswith("/" + dp)):
            return True
    return False


# ---- staticka kontrola PKGBUILD ------------------------------------------------------------------
FUNC_RE = re.compile(r"^\s*(function\s+)?([A-Za-z_][\w-]*)\s*\(\s*\)\s*\{?\s*$")


def split_pkgbuild(text):
    """-> (radky mimo funkce [(cislo, radek)], {funkce: [(cislo, radek)]}, [problemy]).
    Jednoduchy lexer pro bezny styl PKGBUILD: 'nazev() {' ... '}' na samostatnem radku."""
    top, funcs, problems = [], {}, []
    cur, depth, paren, pending = None, 0, 0, False
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        s = line.strip()
        if cur is None:
            m = FUNC_RE.match(line)
            if m and paren == 0:
                cur = m.group(2)
                funcs[cur] = []
                pending = not line.rstrip().endswith("{")
                depth = 0 if pending else 1
                continue
            if pending:
                pass
            top.append((n, line))
            paren += _count(s, "(") - _count(s, ")")
            if paren < 0:
                paren = 0
            continue
        if pending:
            if s == "{":
                pending, depth = False, 1
                continue
            problems.append(f"line {n}: unexpected text after function name")
            pending, depth = False, 1
        depth += _count(s, "{") - _count(s, "}")
        if depth <= 0 and s.startswith("}"):
            cur = None
            continue
        funcs[cur].append((n, line))
    if cur is not None:
        problems.append("unterminated function")
    return top, funcs, problems


def _count(s, ch):
    """Pocet znaku mimo uvozovky a komentare (hruby odhad, staci pro bezne PKGBUILD)."""
    out, q = 0, None
    i = 0
    while i < len(s):
        c = s[i]
        if q:
            if c == "\\" and q == '"':
                i += 2
                continue
            if c == q:
                q = None
        elif c in "'\"":
            q = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            break
        elif c == ch and not (ch in "{}" and i > 0 and s[i - 1] == "$"):
            out += 1
        i += 1
    return out


ASSIGN_RE = re.compile(r"^\s*(export\s+)?[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\+?=")


TEST_RE = r"(\[\[\s[^;&|<>]*\s\]\]|\[\s[^;&|<>\]]*\s\]|test\s[^;&|<>]*?)"


def _strip_condition(s):
    """Radek ridici struktury bez prikazu -> zbytek za podminkou ('' = nic), jinak None."""
    if re.fullmatch(r"(then|else|fi|esac|;;|set\s+[-+][eu]+)", s):
        return ""
    m = re.fullmatch(r"(if|elif)\s+%s\s*;\s*then(\s+(?P<rest>.*))?" % TEST_RE, s)
    if m:
        return m.group("rest") or ""
    m = re.fullmatch(r"%s\s*&&\s*(?P<rest>.*)" % TEST_RE, s)
    if m:
        rest = m.group("rest")
        # vic prirazeni za sebou: a=1 && b=(
        parts = [x.strip() for x in rest.split("&&")]
        if all(ASSIGN_RE.match(x) for x in parts):
            return parts[-1] if len(parts) == 1 else "x=" + parts[-1].split("=", 1)[1]
        return None
    if re.fullmatch(r'case\s+"?\$\{?CARCH\}?"?\s+in', s):
        return ""
    m = re.fullmatch(r"[\w|*.\"'-]+\)\s*(?P<rest>.*?)\s*(;;)?", s)
    if m and not s.startswith("("):
        return m.group("rest") or ""
    return None


def check_top_level(top, local_funcs=()):
    problems = []
    in_array = 0
    for n, line in top:
        s = line.strip()
        if not s or s.startswith("#"):
            in_array += _count(s, "(") - _count(s, ")") if s else 0
            continue
        if "$(" in s or "`" in s:
            problems.append(f"line {n}: command substitution outside functions (runs when the PKGBUILD is read)")
        if in_array > 0:
            in_array += _count(s, "(") - _count(s, ")")
            continue
        if ASSIGN_RE.match(s):
            in_array += _count(s, "(") - _count(s, ")")
            continue
        if re.fullmatch(r"unset(\s+-[fv])?(\s+[A-Za-z_]\w*)+", s):
            continue
        if s.startswith("_") and re.fullmatch(r"_[\w-]*", s) and s in local_funcs:
            continue                    # volani funkce z tohoto PKGBUILD (jeji telo prochazi kontrolou)
        # podminky (napr. podle $CARCH) jen z testu [ ] / [[ ]] / test, uvnitr zase jen prirazeni
        rest = _strip_condition(s)
        if rest is not None:
            if rest == "" or ASSIGN_RE.match(rest):
                in_array += _count(rest, "(") - _count(rest, ")")
                continue
        problems.append(f"line {n}: command outside functions: {s[:80]}")
    return problems


HEREDOC_RE = re.compile(r"(?<!<)<<(-?)\s*(['\"]?)([A-Za-z_]\w*)\2")
HEREDOC_OK = {"cat", "echo", "printf", "tee", "install"}


def logical_lines(lines, problems, where):
    """Spoji radky s \\ na konci a vynecha telo here-dokumentu (text, ne prikazy). Here-dokument smi
    jit jen do cat/tee (zapis souboru, zprava); do interpretu (bash <<EOF) = problem."""
    out, buf, start, end_word = [], "", None, None
    for n, line in lines:
        if end_word is not None:
            if line.strip() == end_word:
                end_word = None
            continue
        if buf:
            buf += " " + line.strip()
        else:
            buf, start = line.rstrip(), n
        if buf.endswith("\\") and not buf.lstrip().startswith("#"):
            buf = buf[:-1]
            continue
        m = HEREDOC_RE.search(mask_strings(buf))
        if m:
            end_word = m.group(3)
            before = mask_strings(buf)[:m.start()]
            cmd = re.split(r"[;&|(]", before)[-1].split()
            if not cmd or os.path.basename(cmd[0]) not in HEREDOC_OK:
                problems.append(f"{where} line {start}: here-document into a command: {buf.strip()[:80]}")
        out.append((start, buf))
        buf = ""
    if buf:
        out.append((start, buf))
    return out


def mask_strings(code):
    """Obsah retezcu v uvozovkach -> S (text hlasek jako echo "sudo ..." neni prikaz). Retezec s $( nebo `
    zustava cely (spousti se); retezec zacinajici / si necha lomitko (kontrola zapisu mimo balik)."""
    out, i = [], 0
    while i < len(code):
        c = code[i]
        if c in "'\"":
            j = i + 1
            while j < len(code) and code[j] != c:
                j += 2 if c == '"' and code[j] == "\\" else 1
            inner = code[i + 1:j]
            after_redirect = "".join(out).rstrip().endswith(">")
            if c == '"' and ("$(" in inner or "`" in inner) or after_redirect:
                out.append(code[i:j + 1])
            else:
                out.append(c + ("/S" if inner.startswith("/") else "S") + c)
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def scan_code(lines, where):
    problems = []
    for n, line in logical_lines(lines, problems, where):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        code = s.split(" #", 1)[0]
        masked = mask_strings(code)
        for pat, why in FORBIDDEN:
            if re.search(pat, masked):
                problems.append(f"{where} line {n}: {why}: {s[:100]}")
        problems += _abs_writes(code, f"{where} line {n}", masked)
    return problems


def _abs_writes(code, where, masked=None):
    """Zapis mimo $pkgdir/$srcdir: presmerovani a cil prikazu cp/mv/install/... na absolutni cestu."""
    out = []
    for m in re.finditer(r"(?<![<>&0-9-])>{1,2}\s*([^\s;|&]+)", masked if masked is not None else code):
        tgt = m.group(1)
        if tgt.startswith(("/dev/null", "&")):
            continue
        if tgt.lstrip("\"'").startswith("/"):
            out.append(f"{where}: writes outside the package: {code[:100]}")
    for part in re.split(r"[;&|]+", code):
        try:
            words = shlex.split(part, posix=True)
        except ValueError:
            continue
        if not words:
            continue
        cmd = os.path.basename(words[0])
        if cmd not in WRITERS:
            continue
        args = [w for w in words[1:] if not w.startswith("-")]
        if not args:
            continue
        if cmd in ("cp", "mv", "install", "ln"):
            targets = args[-1:]          # zdroje smi byt odkudkoli (ln -s CIL: odkaz smi mirit kamkoli)
        elif cmd in ("chmod", "chown"):
            targets = args[1:]
        else:
            targets = args
        for t in targets:
            raw = t.strip("\"'")
            if re.match(r"/+\$\{?(srcdir|pkgdir|startdir)\b", raw):
                continue                 # "/$srcdir/..." je porad uvnitr sestaveni
            if raw.startswith("/") and not raw.startswith("/dev/null"):
                out.append(f"{where}: {cmd} on an absolute path outside the package: {raw[:80]}")
    return out


# .install bezi jako root na pocitaci uzivatele: zapisovat smi jen do adresaru ovladacu
INSTALL_WRITE_OK = ("/opt/", "/usr/share/cups/", "/usr/share/ppd/", "/usr/lib/cups/", "/usr/share/brother",
                    "/usr/local/Brother", "/usr/share/doc/", "/etc/sane.d/", "/etc/udev/rules.d/", "/usr/lib/sane/",
                    "/var/log/", "/var/spool/lpd/", "/var/tmp/", "/tmp/", "/usr/share/epson", "/usr/lib/epson",
                    "/usr/share/iscan", "/usr/lib/iscan", "/etc/cups/ppd/", "/usr/share/samsung", "/opt")


# Spustitelne soubory vyrobce, ktere smi .install spustit (zdroj = archiv vyrobce s overenym souctem)
VENDOR_EXEC = ("/opt/brother/", "/usr/local/Brother/", "/usr/share/brother/", "/opt/epson", "/opt/canon",
               "/opt/smfp-common/", "/opt/kyocera", "/opt/ricoh", "/opt/xerox")


def _install_vars(text):
    """Jednoducha prirazeni v .install (a=/opt/x, local a="/opt/x") -> {nazev: [hodnoty]}."""
    out = {}
    for m in re.finditer(r"^\s*(?:local\s+|export\s+)?([A-Za-z_]\w*)=(\S*)\s*$", text, re.M):
        out.setdefault(m.group(1), []).append(m.group(2).strip("\"'"))
    return out


def _resolve(word, variables, depth=0):
    """Cesta s $promennou -> seznam moznych hodnot (None = nejde zjistit)."""
    m = re.search(r"\$\{?([A-Za-z_]\w*)\}?", word)
    if not m:
        return [word]
    if depth > 4 or m.group(1) not in variables:
        return None
    vals = []
    for v in variables[m.group(1)]:
        r = _resolve(word[:m.start()] + v + word[m.end():], variables, depth + 1)
        if r is None:
            return None
        vals += r
    return vals


def _install_writes(code, n, variables):
    out = []
    targets = [m.group(1) for m in re.finditer(r"(?<![<>&0-9-])>{1,2}\s*([^\s;|&]+)", mask_strings(code))]
    for part in re.split(r"[;&|]+", code):
        try:
            words = shlex.split(part, posix=True)
        except ValueError:
            continue
        if not words:
            continue
        cmd = os.path.basename(words[0])
        args = [w for w in words[1:] if not w.startswith("-")]
        if cmd == "sed":
            if not any(w.startswith("-i") or w == "--in-place" for w in words[1:]):
                continue
            args = args[1:]                 # prvni argument je vyraz
        elif cmd not in WRITERS:
            continue
        if cmd in ("cp", "mv", "install", "ln"):
            args = args[-1:]
        elif cmd in ("chmod", "chown", "chgrp"):
            args = args[1:]                 # prvni argument je mod/vlastnik
        targets += args
    for t in targets:
        t = t.strip("\"'")
        if t.startswith("&") or t in ("/dev/null", "/dev/stderr", "/dev/stdout"):
            continue
        vals = _resolve(t, variables)
        if vals is None:
            out.append(f".install line {n}: writes to a path that cannot be checked: {t[:60]}")
            continue
        for v in vals:
            if ".." in v.split("/") or not v.startswith("/") or not v.startswith(INSTALL_WRITE_OK):
                out.append(f".install line {n}: writes outside driver directories: {v[:60]}")
    return out


def check_install_script(text):
    problems = []
    _top, funcs, p = split_pkgbuild(text)
    problems += p
    variables = _install_vars(text)
    local_funcs = set(funcs)
    for name, lines in funcs.items():
        for n, line in logical_lines(lines, problems, ".install"):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            code = mask_strings(s.split(" #", 1)[0])
            for pat, why in FORBIDDEN:
                if why in ("systemctl during build", "disk tool"):
                    continue
                if re.search(pat, code):
                    problems.append(f".install line {n}: {why}: {s[:100]}")
            problems += _install_writes(s.split(" #", 1)[0], n, variables)
            if "systemctl" in code and not SYSTEMCTL_OK.search(code):
                problems.append(f".install line {n}: systemctl only for CUPS/scanner services: {s[:100]}")
            for part in re.split(r"[;&|]+|\$\(|`", code):
                w = part.strip().lstrip("!({").strip().split()
                if not w:
                    continue
                first = w[0]
                if "=" in first and not first.startswith("="):
                    continue
                if first in ("}", "))", ")", "]]", "]") or first.endswith(")"):
                    continue
                exe = first.strip("\"'")
                if os.path.basename(exe) in INSTALL_OK or exe in local_funcs:
                    continue
                if exe.startswith(VENDOR_EXEC) and ".." not in exe.split("/"):
                    continue                # instalacni skript vyrobce z overeneho archivu (jako u vyrobce)
                problems.append(f".install line {n}: command not allowed: {first[:40]}")
    return problems


# ---- nacteni promennych PKGBUILD (bez site, bez prostredi) --------------------------------------
READ_VARS = ["pkgbase", "pkgname", "pkgver", "pkgrel", "epoch", "arch", "install", "depends", "makedepends",
             "validpgpkeys", "provides"]


def read_pkgbuild(repo):
    arrays = ["source", f"source_{CARCH}"] + [f"{a}sums" for a in CHECKSUM_ALGOS] + \
             [f"{a}sums_{CARCH}" for a in CHECKSUM_ALGOS] + READ_VARS + [f"depends_{CARCH}", f"makedepends_{CARCH}"]
    script = "set -u; CARCH=%s; source ./PKGBUILD >/dev/null 2>&1 || exit 7; set +u\n" % CARCH
    for v in arrays:
        script += ('if declare -p %s >/dev/null 2>&1; then printf "%%s\\0" "@%s"; '
                   'eval "printf \\"%%s\\\\0\\" \\"\\${%s[@]}\\""; fi\n') % (v, v, v)
    cmd = ["unshare", "-rn", "env", "-i", "PATH=/usr/bin:/bin", "HOME=/nonexistent",
           "bash", "--noprofile", "--norc", "-c", script]
    try:
        r = subprocess.run(cmd, cwd=repo, capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        return None, "reading the PKGBUILD timed out"
    if r.returncode:
        return None, f"the PKGBUILD cannot be read (rc {r.returncode})"
    out, cur = {}, None
    for item in r.stdout.decode("utf-8", "replace").split("\0"):
        if item.startswith("@") and item[1:] in arrays:
            cur = item[1:]
            out[cur] = []
        elif cur is not None and item != "" or (cur is not None and item == "" and False):
            out[cur].append(item)
    return out, None


def source_entries(meta):
    srcs = meta.get("source", []) + meta.get(f"source_{CARCH}", [])
    sums = None
    algo = None
    for a in CHECKSUM_ALGOS:
        both = meta.get(f"{a}sums", []) + meta.get(f"{a}sums_{CARCH}", [])
        if meta.get(f"{a}sums") is not None or meta.get(f"{a}sums_{CARCH}") is not None:
            if a in STRONG or sums is None:
                sums, algo = both, a
                if a in STRONG:
                    break
    out = []
    for i, s in enumerate(srcs):
        name, _, url = s.partition("::") if "::" in s else ("", "", s)
        if "://" not in url:
            name, url = url, ""
        elif not name:
            # jako makepkg (get_filename): posledni cast adresy i s ?dotazem, bez #fragmentu
            name = url.split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        out.append({"entry": s, "file": name, "url": url, "sum": (sums[i] if sums and i < len(sums) else None),
                    "algo": algo})
    return out


def file_hash(path, algo):
    if algo == "b2":
        h = hashlib.blake2b()
    elif algo in ("sha512", "sha384", "sha256", "sha224", "sha1", "md5"):
        h = hashlib.new(algo)
    else:
        return None
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Redirect(urllib.request.HTTPRedirectHandler):
    """Presmerovani jen v ramci povolenych domen vyrobce."""

    def __init__(self, vendor):
        self.vendor = vendor

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlparse(newurl)
        host = u.hostname
        if not host_allowed(host, self.vendor, path=u.path, redirect=True):
            raise urllib.error.HTTPError(newurl, code, f"redirect to a foreign domain {host}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def store_source(tmp, name):
    """Stazeny soubor -> src/SHA256/NAZEV (ruzne baliky maji soubory se stejnym nazvem a jinym obsahem)."""
    digest = file_hash(tmp, "sha256")
    d = os.path.join(WORK, "src", digest)
    os.makedirs(d, exist_ok=True)
    final = os.path.join(d, name)
    os.replace(tmp, final)
    return final


def cached_source(name, algo, want):
    """Uz stazeny soubor s timto nazvem a kontrolnim souctem (nebo None)."""
    root = os.path.join(WORK, "src")
    try:
        dirs = os.listdir(root)
    except OSError:
        return None
    for d in dirs:
        path = os.path.join(root, d, name)
        if len(d) == 64 and os.path.isfile(path) and (file_hash(path, algo) or "").lower() == want.lower():
            return path
    return None


def download(url, dest, vendor):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return None
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    opener = urllib.request.build_opener(Redirect(vendor))
    req = urllib.request.Request(url, headers={"User-Agent": "LuxOS-driver-verifier/1.0"})
    tmp = dest + ".part"
    try:
        with opener.open(req, timeout=120) as r, open(tmp, "wb") as f:
            n = 0
            for chunk in iter(lambda: r.read(1 << 20), b""):
                n += len(chunk)
                if n > MAX_SOURCE:
                    raise ValueError("source too large")
                f.write(chunk)
        os.replace(tmp, dest)
    except Exception as e:  # noqa: BLE001 - kazda chyba stazeni = neovereno
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return f"download failed: {url}: {e}"
    return None


# ---- AUR git -------------------------------------------------------------------------------------
# Repozitare AUR se ctou z oficialniho zrcadla na GitHubu (vetev = pkgbase, stejne commity jako AUR):
# jeden ls-remote zjisti vsechny hlavy, stahuji se jen zmenene vetve - AUR samo omezuje pocet pozadavku (429).
MIRROR = os.environ.get("LUXDRV_GIT", "https://github.com/archlinux/aur.git")
BARE = os.path.join(WORK, "aur.git")


def git(*args, timeout=300):
    return run(["git", "--git-dir", BARE] + list(args), timeout=timeout)


def mirror_heads():
    """{pkgbase: commit} vsech vetvi zrcadla (jeden pozadavek)."""
    rc, out, err = run(["git", "ls-remote", "--heads", MIRROR], timeout=300)
    if rc:
        raise SystemExit(f"git ls-remote {MIRROR}: {err.strip()[:200]}")
    heads = {}
    for line in out.splitlines():
        sha, _t, ref = line.partition("\t")
        if ref.startswith("refs/heads/"):
            heads[ref[len("refs/heads/"):]] = sha
    return heads


def fetch_branches(bases):
    if not os.path.isdir(BARE):
        os.makedirs(BARE)
        run(["git", "init", "-q", "--bare", BARE])
    bases = list(bases)
    for k in range(0, len(bases), 100):
        chunk = bases[k:k + 100]
        rc, _o, err = git("fetch", "-q", "--no-tags", MIRROR,
                          *[f"+refs/heads/{b}:refs/heads/{b}" for b in chunk], timeout=900)
        if rc:
            raise SystemExit(f"git fetch: {err.strip()[:300]}")
        time.sleep(2)


def export_tree(base, commit):
    """Soubory vetve v commitu -> WORK/aur/base (bez .git; historie zustava v BARE)."""
    path = os.path.join(WORK, "aur", base)
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    a = subprocess.run(["git", "--git-dir", BARE, "archive", "--format=tar", commit], capture_output=True)
    if a.returncode:
        return None
    t = subprocess.run(["tar", "-x", "--no-same-owner", "--no-same-permissions", "-C", path], input=a.stdout,
                       capture_output=True)
    return path if t.returncode == 0 else None


def authors(gitargs, rev_range):
    rc, out, _e = run(["git"] + gitargs + ["log", "--format=%ae", rev_range])
    return set(x.strip().lower() for x in out.splitlines() if x.strip()) if rc == 0 else set()


# ---- zaplaty LuxOS --------------------------------------------------------------------------------
def luxos_patches(base):
    """{nazev: sha256} zaplat drivers/patches/BASE/*.patch (aplikuji se v abecednim poradi)."""
    d = os.path.join(PATCHES, base)
    try:
        names = sorted(f for f in os.listdir(d) if f.endswith(".patch"))
    except OSError:
        return {}
    return {f: file_hash(os.path.join(d, f), "sha256") for f in names}


def apply_patches(repo, base, expect=None):
    """Zaplaty LuxOS na soubory z AUR -> (zaplaty {nazev: sha256}, [problemy]).
    expect = zaplaty z manifestu: jine/chybejici = chyba (sestavuje se jen overeny stav)."""
    pats = luxos_patches(base)
    if expect is not None and pats != expect:
        return pats, ["LuxOS patches differ from the verified ones - run drivers/luxdrv.py verify " + base]
    for f in pats:
        rc, out, err = run(["patch", "-p1", "-N", "-s", "--no-backup-if-mismatch", "-r", "-", "-d", repo,
                            "-i", os.path.join(PATCHES, base, f)])
        if rc:
            return pats, [f"LuxOS patch {f} does not apply: {(out + err).strip()[:150]}"]
    return pats, []


# ---- overeni jednoho balicku ----------------------------------------------------------------------
def verify_repo(repo, base, vendor, previous=None, download_sources=True, review=True, gitdir=None, head="HEAD"):
    """-> dict(ok, problems, sources{file: sha256}, pkgnames, version, diff)
    repo = soubory overovane verze; historie v gitdir (vychozi repo/.git), overovany commit head."""
    gitargs = ["--git-dir", gitdir] if gitdir else ["-C", repo]
    res = {"base": base, "vendor": vendor, "problems": [], "sources": {}, "pkgnames": [], "version": "",
           "depends": [], "provides": [], "diff": "", "patches": {}}
    P = res["problems"]
    # zaplaty LuxOS pred kontrolou: overuje se to, co se opravdu sestavi
    res["patches"], p = apply_patches(repo, base)
    P += p
    if P:
        return finish(res)
    pkgbuild_path = os.path.join(repo, "PKGBUILD")
    try:
        text = readtext(pkgbuild_path)
    except OSError:
        P.append("no PKGBUILD")
        return finish(res)
    top, funcs, p = split_pkgbuild(text)
    P += p
    P += check_top_level(top, set(funcs))
    for fname, lines in funcs.items():
        P += scan_code(lines, f"{fname}()")
    if P:
        return finish(res)                 # nic nenacitat, kdyz staticka kontrola neprosla
    meta, err = read_pkgbuild(repo)
    if err:
        P.append(err)
        return finish(res)
    res["pkgnames"] = meta.get("pkgname", [])
    ver = (meta.get("pkgver") or [""])[0]
    rel = (meta.get("pkgrel") or [""])[0]
    ep = (meta.get("epoch") or [""])[0]
    res["version"] = (f"{ep}:" if ep else "") + f"{ver}-{rel}"
    res["depends"] = meta.get("depends", []) + meta.get(f"depends_{CARCH}", []) + meta.get("makedepends", []) + \
        meta.get(f"makedepends_{CARCH}", [])
    res["provides"] = [re.split(r"[<>=]", x)[0] for x in meta.get("provides", [])]
    arch = meta.get("arch", [])
    if arch and "any" not in arch and CARCH not in arch:
        P.append(f"no {CARCH} build (arch={' '.join(arch)})")
    # .install a dalsi soubory v repozitari AUR
    inst = (meta.get("install") or [""])[0]
    for f in sorted(os.listdir(repo)):
        if f.startswith(".") or f == "PKGBUILD":
            continue
        path = os.path.join(repo, f)
        if not os.path.isfile(path):
            continue
        data = readtext(path)
        if f == inst or f.endswith(".install"):
            P += check_install_script(data)
        elif data.startswith("#!") or f.endswith((".sh", ".hook")):
            _t, fs, pp = split_pkgbuild(data)
            P += [f"{f}: {x}" for x in scan_code([(i + 1, ln) for i, ln in enumerate(data.splitlines())], f)]
    # zdroje
    for s in source_entries(meta):
        if s["url"]:
            u = urllib.parse.urlparse(s["url"].split("#", 1)[0])
            if u.scheme not in ("https", "http", "ftp"):
                P.append(f"source not allowed ({u.scheme}): {s['url'][:100]}")
                continue
            if not host_allowed(u.hostname, vendor, path=u.path):
                P.append(f"source from a domain that is not the vendor's: {u.hostname}{u.path[:40]}")
                continue
        else:
            if not os.path.isfile(os.path.join(repo, s["file"])):
                P.append(f"local source missing: {s['file']}")
                continue
        if not s["sum"] or s["sum"].upper() == "SKIP":
            P.append(f"no checksum for {s['file'] or s['url']}")
            continue
        if not download_sources:
            continue
        if s["url"]:
            dest = cached_source(s["file"], s["algo"], s["sum"])
            if dest is None:
                tmp = os.path.join(WORK, "src", ".download", s["file"])
                err = download(s["url"].split("#", 1)[0], tmp, vendor)
                if err:
                    P.append(err)
                    continue
                dest = store_source(tmp, s["file"])
        else:
            dest = os.path.join(repo, s["file"])
        got = file_hash(dest, s["algo"])
        if got is None or got.lower() != s["sum"].lower():
            P.append(f"checksum mismatch for {s['file']}")
            continue
        res["sources"][s["file"]] = file_hash(dest, "sha256")
    # zmena proti poslednimu overenemu commitu: rozdil a novi commiteri
    if previous and previous.get("commit"):
        old = previous["commit"]
        rc, diff, _e = run(["git"] + gitargs + ["diff", f"{old}..{head}", "--"])
        if rc != 0:
            P.append("last verified commit no longer in the AUR history (history rewritten)")
        else:
            res["diff"] = diff
            new = authors(gitargs, f"{old}..{head}") - authors(gitargs, old)
            if new:
                P.append("new committer(s) in the AUR since the last verification: " + ", ".join(sorted(new)) +
                         " - manual review needed")
            changed_sources = set(res["sources"]) & set(previous.get("sources", {}))
            for f in changed_sources:
                if res["sources"][f] != previous["sources"][f] and f in (previous.get("sources") or {}):
                    # stejny nazev, jiny obsah: vyrobce soubor vymenil - povoleno jen se zmenou kontrolniho
                    # souctu v PKGBUILD (to uz overila kontrola vyse); zaznamenat do diffu
                    res["diff"] += f"\n# source {f} changed: {previous['sources'][f]} -> {res['sources'][f]}\n"
    hook = os.environ.get("LUXOS_DRIVERS_REVIEW")
    if review and hook and not P:
        payload = json.dumps({"package": base, "pkgbuild": text,
                              "install": readtext(os.path.join(repo, inst))
                              if inst and os.path.isfile(os.path.join(repo, inst)) else "",
                              "diff": res["diff"]})
        rc, out, err = run(shlex.split(hook), inp=payload, timeout=600)
        if rc != 0:
            P.append("review hook rejected: " + (out or err).strip()[:300])
    return finish(res)


RULES = 4          # verze pravidel: odmitnute podle starsich pravidel se overi znovu


def finish(res):
    res["ok"] = not res["problems"]
    return res


# ---- prikazy --------------------------------------------------------------------------------------
def cmd_discover():
    conf = vendors()
    names = {}
    seen_q = set()
    for v, d in conf["vendors"].items():
        for p in d["prefixes"]:
            q = p.rstrip("-_") or p
            if q in seen_q:
                continue
            seen_q.add(q)
            url = f"{AUR}/rpc/v5/search/{urllib.parse.quote(q)}?by=name"
            with urllib.request.urlopen(url, timeout=60) as r:
                data = json.load(r)
            for pkg in data.get("results", []):
                if any(pkg["Name"].startswith(x) for x in d["prefixes"]):
                    names[pkg["Name"]] = pkg
            time.sleep(1)
    cands = {}
    for n, pkg in names.items():
        base = pkg["PackageBase"]
        if any(base.endswith(s) for s in conf.get("exclude_suffixes", [])):
            continue
        v = vendor_of(base, conf) or vendor_of(n, conf)
        if not v:
            continue
        c = cands.setdefault(base, {"vendor": v, "names": [], "maintainer": pkg.get("Maintainer"),
                                    "out_of_date": bool(pkg.get("OutOfDate")), "votes": pkg.get("NumVotes", 0)})
        c["names"].append(n)
    for dep in conf.get("dependencies", {}):
        cands[dep] = {"vendor": "dep:" + dep, "names": [dep], "maintainer": None, "out_of_date": False, "votes": 0}
    for extra in conf.get("include_extra", []):
        if extra not in cands:
            v = vendor_of(extra, conf)
            if v:
                cands[extra] = {"vendor": v, "names": [extra], "maintainer": None, "out_of_date": False, "votes": 0}
    save(os.path.join(STATE, "candidates.json"), cands)
    print(f"{len(cands)} candidate packages")
    return 0


def cmd_verify(bases, limit=None, keep_sources=False):
    cands = load(os.path.join(STATE, "candidates.json"), {})
    manifest = load(os.path.join(STATE, "manifest.json"), {})
    rejected = load(os.path.join(STATE, "rejected.json"), {})
    todo = bases or sorted(cands)
    heads = mirror_heads()
    need = []
    for base in todo:
        head = heads.get(base)
        prev, rej = manifest.get(base), rejected.get(base) or {}
        if head is None:
            rejected[base] = {"commit": None, "problems": ["not in the AUR (deleted or renamed)"],
                              "checked": time.strftime("%Y-%m-%d"), "rules": RULES}
            if prev:
                rejected[base]["kept_verified"] = prev["commit"]
            continue
        pats = luxos_patches(base)
        if prev and prev.get("commit") == head and prev.get("rules") == RULES and \
                prev.get("patches", {}) == pats and all(
                os.path.isfile(os.path.join(WORK, "src", h, f)) for f, h in prev.get("sources", {}).items()):
            continue
        if not prev and rej.get("commit") == head and rej.get("rules") == RULES and rej.get("patches", {}) == pats:
            continue
        need.append(base)
    if limit:
        need = need[:limit]
    print(f"{len(need)} packages changed or not checked yet")
    fetch_branches(need)
    for base in need:
        head = heads[base]
        vendor = (cands.get(base) or {}).get("vendor") or vendor_of(base)
        if not vendor:
            print(f"{base}: unknown vendor - skipped")
            continue
        repo = export_tree(base, head)
        if not repo:
            print(f"{base}: cannot export {head}")
            continue
        prev = manifest.get(base)
        try:
            res = verify_repo(repo, base, vendor, previous=prev, gitdir=BARE, head=head)
        except Exception as e:  # noqa: BLE001 - chyba nastroje = neovereno, pokracovat dalsim
            res = finish({"problems": [f"verification error: {type(e).__name__}: {e}"[:200]], "sources": {},
                          "diff": ""})
        if res["ok"]:
            manifest[base] = {"commit": head, "vendor": vendor, "version": res["version"], "pkgnames": res["pkgnames"],
                              "sources": res["sources"], "verified": time.strftime("%Y-%m-%d"),
                              "depends": res["depends"], "rules": RULES}
            if res["patches"]:
                manifest[base]["patches"] = res["patches"]
            if res["provides"]:
                manifest[base]["provides"] = res["provides"]
            rejected.pop(base, None)
            if res["diff"]:
                os.makedirs(os.path.join(WORK, "diffs"), exist_ok=True)
                with open(os.path.join(WORK, "diffs", f"{base}.diff"), "w") as f:
                    f.write(res["diff"])
            print(f"{base}: OK {res['version']}")
        else:
            rejected[base] = {"commit": head, "problems": res["problems"][:12], "checked": time.strftime("%Y-%m-%d"),
                              "rules": RULES}
            if res.get("patches"):
                rejected[base]["patches"] = res["patches"]
            if prev and prev.get("commit") == head:
                # stejny commit neprosel prisnejsimi pravidly -> uz neni overeny, nestavi se
                manifest.pop(base)
            elif prev:
                # predchozi overena verze zustava (sestavena), nova se nepusti dal
                rejected[base]["kept_verified"] = prev["commit"]
            print(f"{base}: REJECTED - {res['problems'][0]}")
        if not keep_sources and not res["ok"]:
            used = {(f, h) for m in manifest.values() for f, h in m.get("sources", {}).items()}
            for f, h in (res.get("sources") or {}).items():
                if (f, h) not in used:
                    try:
                        os.unlink(os.path.join(WORK, "src", h, f))
                        os.rmdir(os.path.join(WORK, "src", h))
                    except OSError:
                        pass
        save(os.path.join(STATE, "manifest.json"), manifest)
        save(os.path.join(STATE, "rejected.json"), rejected)
        time.sleep(0.5)                         # servery vyrobcu setrne
    save(os.path.join(STATE, "manifest.json"), manifest)
    save(os.path.join(STATE, "rejected.json"), rejected)
    return 0


def cmd_build_list():
    manifest = load(os.path.join(STATE, "manifest.json"), {})
    built = os.path.join(ROOT, "out", "drivers-repo", "built")
    lines = []
    for base, m in sorted(manifest.items()):
        mark = os.path.join(built, base)
        if os.path.exists(mark) and readtext(mark).split("\n", 1)[0].strip() == m["commit"]:
            continue
        lines.append(f"{base}\t{m['commit']}")
    os.makedirs(WORK, exist_ok=True)
    with open(os.path.join(WORK, "build-list.tsv"), "w") as f:
        f.write("".join(x + "\n" for x in lines))
    print(f"{len(lines)} packages to build")
    return 0


def cmd_fetch(bases):
    """Pro sestaveni jinde (GitHub Actions): zapichnute commity z AUR a zdroje overenych baliku.
    Nic se neoveruje znovu - kazdy stazeny soubor musi mit presne sha256 z manifestu, jinak se zahodi."""
    manifest = load(os.path.join(STATE, "manifest.json"), {})
    todo = [b for b in (bases or sorted(manifest)) if b in manifest]
    for b in sorted(set(bases) - set(todo)):
        print(f"{b}: not verified - skipped")

    def have(commit):
        return os.path.isdir(BARE) and git("cat-file", "-e", commit + "^{commit}")[0] == 0
    missing = [b for b in todo if not have(manifest[b]["commit"])]
    if missing:
        print(f"fetching {len(missing)} AUR branches")
        fetch_branches(missing)
    bad = []
    for base in todo:
        m = manifest[base]
        need = {f: h for f, h in m.get("sources", {}).items() if not os.path.isfile(os.path.join(WORK, "src", h, f))}
        if not need:
            continue
        repo = export_tree(base, m["commit"])
        if not repo:
            bad.append(f"{base}: commit {m['commit']} not in the AUR mirror")
            continue
        _p, prob = apply_patches(repo, base, expect=m.get("patches", {}))
        meta, err = (None, prob[0]) if prob else read_pkgbuild(repo)
        if err:
            bad.append(f"{base}: {err}")
            continue
        for s in source_entries(meta):
            f = s["file"]
            if f not in need or not s["url"]:
                continue
            tmp = os.path.join(WORK, "src", ".download", f)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            err = download(s["url"].split("#", 1)[0], tmp, m["vendor"])
            if err:
                bad.append(f"{base}: {err}")
                continue
            got = file_hash(tmp, "sha256")
            if got != need[f]:
                os.unlink(tmp)
                bad.append(f"{base}: {f}: sha256 {got} differs from the verified {need[f]}")
                continue
            store_source(tmp, f)
            print(f"{base}: {f} OK")
        time.sleep(0.3)                         # servery vyrobcu setrne
    os.makedirs(WORK, exist_ok=True)
    with open(os.path.join(WORK, "fetch-failed.txt"), "w") as f:
        f.write("".join(x + "\n" for x in bad))
    print(f"fetch: {len(todo)} packages, {len(bad)} problems")
    for x in bad:
        print("  " + x)
    return 0


def cmd_closure(bases):
    """BALIKY + overene baliky, na kterych zavisi (i pres provides), zavislosti prvni."""
    manifest = load(os.path.join(STATE, "manifest.json"), {})
    prov = {}
    for b, m in sorted(manifest.items()):
        for n in m.get("pkgnames", []) + m.get("provides", []):
            prov.setdefault(n, b)
    out, seen = [], set()

    def add(b):
        if b in seen or b not in manifest:
            return
        seen.add(b)
        for d in manifest[b].get("depends", []):
            n = re.split(r"[<>=]", d)[0]
            if prov.get(n, b) != b:
                add(prov[n])
        out.append(b)
    for b in bases:
        add(b)
    print("\n".join(out))
    return 0


def ppd_ids(text):
    """-> [(mfg, mdl)] z PPD (*1284DeviceID, jinak *Manufacturer + *ModelName/*Product)."""
    out = []
    for m in re.finditer(r'^\*1284DeviceID:\s*"([^"]*)"', text, re.M):
        d = {}
        for part in m.group(1).split(";"):
            k, _, v = part.partition(":")
            d[k.strip().upper()] = v.strip()
        mfg = d.get("MFG") or d.get("MANUFACTURER")
        mdl = d.get("MDL") or d.get("MODEL")
        if mfg and mdl:
            out.append((mfg, mdl))
    if not out:
        mfg = re.search(r'^\*Manufacturer:\s*"([^"]*)"', text, re.M)
        for m in re.finditer(r'^\*(?:ModelName|Product):\s*"\(?([^")]*)\)?"', text, re.M):
            if mfg:
                out.append((mfg.group(1), m.group(1)))
    return out


def cmd_index(pkgdir, outdir=None):
    """Mapa zarizeni -> balik z hotovych baliku: tiskarny (PPD) a skenery (udev USB ID)."""
    import gzip
    import tarfile
    printers, usb = [], []
    for f in sorted(os.listdir(pkgdir)):
        if not f.endswith(".pkg.tar.zst") or f.startswith("luxos-drivers-index-"):
            continue
        path = os.path.join(pkgdir, f)
        p = subprocess.run(["zstd", "-dc", path], capture_output=True)
        if p.returncode:
            continue
        import io
        tf = tarfile.open(fileobj=io.BytesIO(p.stdout))
        name = ""
        try:
            info = tf.extractfile(".PKGINFO").read().decode()
            name = re.search(r"^pkgname = (.+)$", info, re.M).group(1)
        except (KeyError, AttributeError):
            continue
        for m in tf.getmembers():
            if not m.isfile():
                continue
            low = m.name.lower()
            if low.endswith((".ppd", ".ppd.gz")):
                data = tf.extractfile(m).read()
                if low.endswith(".gz"):
                    try:
                        data = gzip.decompress(data)
                    except OSError:
                        continue
                for mfg, mdl in ppd_ids(data.decode("latin-1")):
                    printers.append({"mfg": mfg, "mdl": mdl, "package": name})
            elif "/udev/rules.d/" in m.name and low.endswith(".rules"):
                text = tf.extractfile(m).read().decode("latin-1")
                for v, pr in re.findall(r'ATTRS?\{idVendor\}=="?([0-9a-fA-F]{4})"?[^\n]*?ATTRS?\{idProduct\}=="?([0-9a-fA-F]{4})',
                                        text):
                    usb.append({"usb": f"{v.lower()}:{pr.lower()}", "package": name})
    seen = set()
    printers = [x for x in printers if not ((k := (x["mfg"].lower(), x["mdl"].lower(), x["package"])) in seen or seen.add(k))]
    seen = set()
    usb = [x for x in usb if not ((k := (x["usb"], x["package"])) in seen or seen.add(k))]
    index = {"format": 1, "repo": "luxos-drivers", "printers": printers, "scanners_usb": usb}
    outdir = outdir or STATE
    save(os.path.join(outdir, "drivers-index.json"), index)
    with open(os.path.join(outdir, "drivers-usb.tsv"), "w", encoding="utf-8") as f:
        f.write("# USB vendor:product -> balik z [luxos-drivers] (luxos-hwdetect)\n")
        f.write("".join(f"{x['usb']}\t{x['package']}\n" for x in sorted(usb, key=lambda x: x["usb"])))
    print(f"index: {len(printers)} printer models, {len(usb)} scanner USB IDs")
    return 0


def cmd_report():
    manifest = load(os.path.join(STATE, "manifest.json"), {})
    rejected = load(os.path.join(STATE, "rejected.json"), {})
    import collections
    reasons = collections.Counter()
    for r in rejected.values():
        for p in r["problems"][:1]:
            reasons[re.sub(r"line \d+", "line N", p.split(":")[0] if "line" in p.split(":")[0] else p)[:70]] += 1
    print(f"verified: {len(manifest)}  rejected: {len(rejected)}")
    for k, v in reasons.most_common(15):
        print(f"  {v:4d}  {k}")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd == "discover":
        return cmd_discover()
    if cmd == "verify":
        limit = None
        if "--limit" in args:
            i = args.index("--limit")
            limit = int(args[i + 1])
            del args[i:i + 2]
        return cmd_verify(args, limit)
    if cmd == "build-list":
        return cmd_build_list()
    if cmd == "fetch":
        return cmd_fetch(args)
    if cmd == "closure":
        return cmd_closure(args)
    if cmd == "index":
        return cmd_index(args[0], args[1] if len(args) > 1 else None)
    if cmd == "report":
        return cmd_report()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
