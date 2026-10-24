#!/usr/bin/env python3
"""lux - zdroj "komunita" (AUR) a Flathub: kontrola sestavovaciho skriptu a vyhledani aplikace.

    lux_community.py review DIR          kontrola vsech souboru repozitare v DIR (PKGBUILD, install=, ...):
                                         1) pevna pravidla (precheck), 2) LuxAI Lite (bez nastroju)
    lux_community.py precheck DIR        jen pevna pravidla
    lux_community.py flathub NAZEV       ID aplikace na Flathubu pro bezny nazev (zoom -> us.zoom.Zoom)
    lux_community.py flathub-search SLOVA   vysledky Flathubu (ID<TAB>nazev<TAB>shrnuti<TAB>URL ikony)
    lux_community.py flathub-size ID     velikost aplikace a chybejiciho prostredi (JSON)

Vystup "review" (radky TAB): VERDICT <safe|suspicious|dangerous|unreviewed>, REASON <text>,
FINDING <zavaznost> <text>, NOTE <proc nebyla kontrola LuxAI>. Neuspech LuxAI nikdy neznamena
"safe": bez kontroly je verdikt "unreviewed" (lux pak zada vyslovne potvrzeni).

AUR je nekontrolovany obsah uzivatelu - skript se tu jen cte, nikdy nespousti.
"""
import json
import os
import re
import stat
import subprocess
import sys

sys.path.insert(0, "/usr/lib/luxos/python")
try:
    from luxos_i18n import _  # noqa: E402
except ImportError:
    def _(text):
        return text

CHAT_PATH = "/api/ide/chat/completions"
MAX_SCRIPT = 60_000          # delsi skript se LuxAI neposila cely (a samo o sobe je podezrele)
MAX_FILE = 256 * 1024        # vetsi soubor se nekontroluje (= podezrely)
MAX_FILES = 200              # vic souboru v repozitari AUR je podezrele
MAX_LUXAI = 150_000          # celkem textu pro LuxAI
VERDICTS = ("safe", "suspicious", "dangerous")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")   # neduveryhodny text (API, AUR) bez ridicich znaku (i C1)

# ---- pevna pravidla ----------------------------------------------------------------------------
# (zavaznost, regularni vyraz, popis) - "high" = sam o sobe verdikt dangerous
RULES = [
    ("high", r"(curl|wget)[^\n|;]*\|\s*(ba|z|da)?sh\b", "downloads a script and runs it directly (curl | sh)"),
    ("high", r"\bbase64\s+(-d|--decode)\b", "decodes hidden base64 content"),
    ("high", r"[A-Za-z0-9+/]{200,}={0,2}", "contains a long encoded blob"),
    ("high", r"\beval\s+[\"']?\$\(", "runs generated code with eval"),
    ("high", r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~|\$HOME)(\s|$|/\*)", "deletes system or home directories"),
    ("high", r"(/etc/(sudoers|passwd|shadow|pam\.d)|\.ssh/authorized_keys|/root/)", "touches accounts, sudo or SSH keys"),
    ("high", r"\b(nc|ncat|socat)\b[^\n]*(-e|exec)", "opens a remote shell"),
    ("medium", r"\bchmod\s+(-R\s+)?(0?777|a\+rwx|[ugo]*\+s)\b", "sets world-writable or setuid permissions"),
    ("medium", r"(^|\s)(sudo|pkexec|su)\s", "asks for administrator rights inside the build script"),
    ("medium", r"systemctl\s+(enable|start)", "enables a system service"),
    ("medium", r"/etc/cron|crontab\b", "adds scheduled tasks"),
    ("medium", r"\.bashrc|\.profile|/etc/profile", "changes shell start-up files"),
    ("low", r"(\bpython[0-9.]*|\bperl|\bruby)\s+-c\s", "runs inline code of another language"),
]
SOURCE_RE = re.compile(r"\b(source|source_x86_64)\s*=\s*\(([^)]*)\)", re.S)
URL_RE = re.compile(r"(?:::)?([a-z+]+)://([^\s\"')]+)")
INSTALL_NET = re.compile(r"\b(curl|wget|git\s+clone|nc|ncat|ssh|scp|rsync)\b")


def read(path, limit=MAX_SCRIPT * 2):
    """Text souboru; symbolicky odkaz ani jiny nez obycejny soubor se necte (O_NOFOLLOW, bez cekani na FIFO)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return ""
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return ""
        with os.fdopen(fd, encoding="utf-8", errors="replace") as f:
            fd = None
            return f.read(limit)
    except OSError:
        return ""
    finally:
        if fd is not None:
            os.close(fd)


def read_bytes(path, limit):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return None
            return f.read(limit)
    except OSError:
        return None


INSTALL_RE = re.compile(r"^[ \t]*install[ \t]*=[ \t]*(?:\"([^\"\n]*)\"|'([^'\n]*)'|([^\s;#]*))", re.M)
VAR_RE = re.compile(r"^[ \t]*(pkgname|pkgbase)=[\"']?([A-Za-z0-9@._+-]+)[\"']?[ \t]*$", re.M)


def install_names(pkgbuild):
    """Jmena souboru z install= v PKGBUILD (makepkg dovoli libovolne jmeno, u rozdelenych baliku i vic).
    $pkgname/$pkgbase se doplni; jine promenne zustanou (= jmeno nelze urcit)."""
    vars_ = {k: v for k, v in VAR_RE.findall(pkgbuild)}
    vars_.setdefault("pkgbase", vars_.get("pkgname", ""))
    out = []
    for m in INSTALL_RE.finditer(pkgbuild):
        name = next(g for g in m.groups() if g is not None)
        for k, v in vars_.items():
            if v:
                name = name.replace("${%s}" % k, v).replace("$" + k, v)
        if name and name not in out:
            out.append(name)
    return out


def repo_files(d):
    """Vsechny polozky repozitare krome .git (bez nasledovani odkazu):
    -> (soubory [(relativni cesta, velikost)], odkazy [cesta], jine [cesta], prilis mnoho)."""
    files, links, other = [], [], []
    stack = [""]
    while stack:
        rel = stack.pop()
        try:
            entries = sorted(os.scandir(os.path.join(d, rel) if rel else d), key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            r = os.path.join(rel, e.name) if rel else e.name
            if r == ".git":
                continue
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                other.append(r)
                continue
            if stat.S_ISLNK(st.st_mode):
                links.append(r)
            elif stat.S_ISDIR(st.st_mode):
                stack.append(r)
            elif stat.S_ISREG(st.st_mode):
                files.append((r, st.st_size))
            else:
                other.append(r)
            if len(files) + len(links) + len(other) > MAX_FILES:
                return sorted(files), links, other, True
    return sorted(files), links, other, False


def repo_texts(d):
    """-> (texty [(cesta, text)] - PKGBUILD a soubor z install= prvni, nalezy pro odkazy/binarni/velke soubory)."""
    files, links, other, too_many = repo_files(d)
    findings = []
    for r in links:
        findings.append(("high", _("contains a symbolic link: %s") % r[:80]))
    for r in other:
        findings.append(("high", _("contains a file that is not a regular file: %s") % r[:80]))
    if too_many:
        findings.append(("medium", _("contains too many files to check")))
    texts = []
    for r, size in files:
        if size > MAX_FILE:
            findings.append(("medium", _("file too large to check: %s") % r[:80]))
            continue
        data = read_bytes(os.path.join(d, r), MAX_FILE + 1)
        if data is None:
            findings.append(("medium", _("file could not be read: %s") % r[:80]))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if text is None or "\0" in text:
            findings.append(("medium", _("binary file that cannot be checked: %s") % r[:80]))
            continue
        texts.append((r, text))
    first = {"PKGBUILD": 0}
    for inst in install_names(dict(texts).get("PKGBUILD", "")):
        first.setdefault(inst, 1)
    texts.sort(key=lambda t: (first.get(t[0], 2), t[0]))
    return texts, findings


SYS_PATH = re.compile(r"^/(etc|usr|opt|var|home|root|boot)(/|$)")
WRITERS = {"install", "cp", "mv", "ln", "tee", "rsync"}


def outside_pkgdir(text):
    """Zapisy do absolutni cesty systemu: cil (posledni argument; u tee kazdy) prikazu install/cp/mv/ln/tee
    bez $pkgdir/$srcdir. Cteni ze systemu (cp /usr/share/... .) nevadi."""
    hits = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for seg in re.split(r"&&|\|\||;|\|", line):
            words = [w.strip("\"'{}()") for w in seg.split()]
            if not words or words[0] not in WRITERS:
                continue
            args = [w for w in words[1:] if w and not w.startswith("-")]
            targets = args if words[0] == "tee" else args[-1:]
            for t in targets:
                if SYS_PATH.match(t) and "pkgdir" not in t and "srcdir" not in t:
                    hits.append(t)
    return hits


def precheck(d):
    """Seznam (zavaznost, popis). Jen cteni souboru - vsech v repozitari (krome .git)."""
    pkgbuild = read(os.path.join(d, "PKGBUILD"))
    if not pkgbuild:
        return [("high", _("no PKGBUILD found"))]
    texts, findings = repo_texts(d)
    if len(pkgbuild) > MAX_SCRIPT:
        findings.append(("medium", _("the build script is unusually long")))
    for name, text in texts:
        for sev, rx, desc in RULES:
            if re.search(rx, text, re.M):
                findings.append((sev, f"{name}: {_(desc)}"))
    for m in SOURCE_RE.finditer(pkgbuild):
        for um in URL_RE.finditer(m.group(2)):
            scheme = um.group(1).split("+")[-1]
            if scheme in ("http", "ftp"):
                findings.append(("medium", "PKGBUILD: " + _("downloads over unencrypted %s: %s") % (scheme, um.group(2)[:80])))
    if re.search(r"(sha256sums|sha512sums|b2sums|md5sums)\s*=\s*\(\s*['\"]?SKIP['\"]?\s*\)", pkgbuild) and \
            not re.search(r"git\+https", pkgbuild):
        findings.append(("low", "PKGBUILD: " + _("downloads are not checked with checksums (SKIP)")))
    for path in outside_pkgdir(pkgbuild):
        findings.append(("high", "PKGBUILD: " + _("writes outside the package directory: %s") % path[:80]))
    # instalacni skript: *.install i libovolne jmeno z install= (makepkg ho bere jen z adresare PKGBUILD)
    insts = install_names(pkgbuild)
    for inst in insts:
        if "/" in inst or inst in (".", ".."):
            findings.append(("high", "PKGBUILD: " + _("install script outside the package directory: %s") % inst[:80]))
        elif re.search(r"[$`*?\[]", inst):
            findings.append(("medium", "PKGBUILD: " + _("the install script name cannot be determined: %s") % inst[:80]))
    for name, text in texts:
        if (name.endswith(".install") and "/" not in name or name in insts) and INSTALL_NET.search(text):
            findings.append(("high", f"{name}: " + _("uses the network while installing")))
    # bez duplicit, nejzavaznejsi prvni
    order = {"high": 0, "medium": 1, "low": 2}
    seen, out = set(), []
    for f in sorted(findings, key=lambda x: order[x[0]]):
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


# ---- LuxAI Lite -----------------------------------------------------------------------------------
def lang():
    for k in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(k)
        if v:
            return "cs" if v.startswith(("cs", "sk")) else "en"
    return "en"


def build_messages(name, pkgbuild, installs, skipped=()):
    reply_lang = "Czech" if lang() == "cs" else "English"
    system = (
        "You review Arch Linux AUR package repositories (PKGBUILD, install scripts and every other file the "
        "build can use) for a beginner who wants to "
        "install the package. You have no tools; judge only the text. Look for malware patterns: downloading and "
        "running code, hidden or encoded payloads, sources from unexpected hosts instead of the project's official "
        "site or releases, writing outside $pkgdir, changing users/sudo/SSH/startup files, services that phone "
        "home, cryptominers, credential theft. Normal packaging (make, cmake, cargo, npm builds, installing into "
        "$pkgdir, official release tarballs, .deb/.rpm repackaging from the vendor) is fine. "
        "Answer ONLY with JSON: {\"verdict\": \"safe\"|\"suspicious\"|\"dangerous\", \"reasons\": [short strings]} "
        f"with at most 4 reasons written in {reply_lang}.")
    parts = [f"Package: {name}", "=== PKGBUILD ===", pkgbuild[:MAX_SCRIPT]]
    for fname, text in installs:
        parts += [f"=== {fname} ===", text[:20_000]]
    for fname in skipped:
        parts += [f"=== {fname} === (not shown: binary, too large or over the size limit)"]
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(parts)}]


def parse_verdict(content):
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None, []
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None, []
    v = d.get("verdict")
    if v not in VERDICTS:
        return None, []
    reasons = [str(r)[:200] for r in (d.get("reasons") or []) if isinstance(r, (str, int, float))][:4]
    return v, reasons


def account_module():
    mod_dir = os.environ.get("LUX_LUXAI_ACCOUNT_DIR")       # testy
    if mod_dir:
        sys.path.insert(0, mod_dir)
    try:
        import luxai_account  # noqa: PLC0415
    except ImportError:
        return None
    return luxai_account


def luxai_review(name, d):
    """-> (verdikt|None, duvody, poznamka). None = kontrola neprobehla (poznamka rika proc)."""
    acc_mod = account_module()
    if acc_mod is None:
        return None, [], _("LuxAI is not installed")
    try:
        acc = acc_mod.load()
    except Exception:  # noqa: BLE001
        acc = None
    if not acc or not acc.get("sessionToken"):
        return None, [], _("you are not signed in to LuxAI")
    pkgbuild = read(os.path.join(d, "PKGBUILD"))
    files, _links, _other, _many = repo_files(d)
    texts = repo_texts(d)[0]
    shown = {f for f, _t in texts}
    installs, skipped, total = [], [f for f, _s in files if f not in shown], len(pkgbuild[:MAX_SCRIPT])
    for fname, text in texts:
        if fname == "PKGBUILD":
            continue
        if total + min(len(text), 20_000) <= MAX_LUXAI and len(text) <= 20_000:
            installs.append((fname, text))
            total += len(text)
        else:
            skipped.append(fname)
    body = {"model": "lite", "messages": build_messages(name, pkgbuild, installs, skipped), "max_tokens": 400,
            "temperature": 0, "stream": False}
    try:
        r = acc_mod.request("POST", CHAT_PATH, body, token=acc["sessionToken"],
                            origin=acc.get("origin", getattr(acc_mod, "ORIGIN", "https://lux-ai.cz")), timeout=60)
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", "") or type(e).__name__
        if code == "network":
            return None, [], _("LuxAI is not reachable (offline?)")
        return None, [], _("LuxAI did not answer (%s)") % code
    content = (((r.get("choices") or [{}])[0]).get("message") or {}).get("content", "") if isinstance(r, dict) else ""
    v, reasons = parse_verdict(content)
    if v is None:
        return None, [], _("LuxAI gave no clear answer")
    if skipped and v == "safe":
        # co LuxAI nevidela, nemuze byt "safe"
        v, reasons = "suspicious", reasons + [_("LuxAI could not see all files of the package")]
    return v, reasons, ""


def review(d, name=None):
    name = name or os.path.basename(os.path.normpath(d))
    findings = precheck(d)
    v, reasons, note = luxai_review(name, d)
    if any(sev == "high" for sev, _t in findings):
        final = "dangerous"
    elif v in (None, "safe") and any(sev == "medium" for sev, _t in findings):
        final = "suspicious"
    elif v is None:
        final = "unreviewed"
    else:
        final = v
    return {"verdict": final, "luxai": v, "reasons": reasons, "findings": findings, "note": note}


def clean(text):
    """Text pro terminal: bez ridicich znaku (odpoved LuxAI, jmena souboru a URL z AUR jsou neduveryhodne)."""
    return CTRL_RE.sub(" ", str(text))


def print_review(r):
    print(f"VERDICT\t{r['verdict']}")
    for x in r["reasons"]:
        print("REASON\t" + clean(x))
    for sev, text in r["findings"]:
        print(f"FINDING\t{sev}\t" + clean(text))
    if r["note"]:
        print("NOTE\t" + clean(r["note"]))


# ---- Flathub --------------------------------------------------------------------------------------
APP_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+){2,}$")
FLATHUB_API = os.environ.get("LUX_FLATHUB_API", "https://flathub.org/api/v2")


def flathub_get(path, body=None, timeout=20):
    """JSON z API Flathubu (bez flatpaku - funguje i pred jeho instalaci). None = nedostupne."""
    import urllib.request  # noqa: PLC0415
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(FLATHUB_API + path, data=data, method="POST" if data else "GET",
                                 headers={"User-Agent": "lux (LuxOS)", "Accept": "application/json",
                                          **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"null")
    except Exception:  # noqa: BLE001
        return None


def flathub_search(term, limit=20):
    """[(app_id, nazev, shrnuti, ikona)] z vyhledavani Flathubu (jen x86_64; ikona jen z dl.flathub.org)."""
    d = flathub_get("/search", {"query": term})
    if not isinstance(d, dict):
        return None
    out = []
    for h in d.get("hits") or []:
        if not isinstance(h, dict):
            continue
        a = str(h.get("app_id") or "")
        if not APP_ID.match(a) or (h.get("arches") and "x86_64" not in h.get("arches")):
            continue
        icon = str(h.get("icon") or "")
        out.append((a, CTRL_RE.sub("", str(h.get("name") or a))[:80],
                    CTRL_RE.sub("", str(h.get("summary") or ""))[:200],
                    icon if re.match(r"^https://dl\.flathub\.org/[\w./-]+\.png$", icon) else ""))
    return out[:limit]



def flathub_candidates(name, rows):
    """rows: [(app_id, nazev, ...)]. Presna shoda ID, nazvu nebo posledni casti ID (zoom -> us.zoom.Zoom)."""
    n = name.lower()
    exact = [r[0] for r in rows if r[0].lower() == n]
    if exact:
        return exact[:1]
    out = []
    for r in rows:
        a, title = r[0], r[1]
        last = a.rsplit(".", 1)[-1].lower()
        if title.strip().lower() == n or last == n or last.replace("-", "") == n.replace("-", ""):
            if a not in out:
                out.append(a)
    return out


def flathub(name):
    """-> (stav, [id]): ok / ambiguous / none / unavailable"""
    if APP_ID.match(name):
        return "ok", [name]
    rows = flathub_search(name)
    if rows is None:
        return "unavailable", []
    c = flathub_candidates(name, rows)
    if not c:
        return "none", []
    return ("ok" if len(c) == 1 else "ambiguous"), c


def installed_runtimes():
    try:
        r = subprocess.run(["flatpak", "list", "--runtime", "--columns=ref"], capture_output=True, text=True,
                           timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}


def flathub_size(app_id):
    """{"download", "installed", "runtime", "runtime_download", "runtime_installed", "runtime_present"} nebo None.
    Velikost prostredi (runtime) se pocita, jen kdyz jeste neni nainstalovane - sdili ho vic aplikaci."""
    d = flathub_get("/summary/" + app_id)
    if not isinstance(d, dict) or "installed_size" not in d:
        return None
    out = {"download": int(d.get("download_size") or 0), "installed": int(d.get("installed_size") or 0),
           "runtime": "", "runtime_download": 0, "runtime_installed": 0, "runtime_present": False}
    rt = ((d.get("metadata") or {}).get("runtime") or "") if isinstance(d.get("metadata"), dict) else ""
    parts = rt.split("/")
    if len(parts) == 3 and APP_ID.match(parts[0]):
        out["runtime"] = rt
        present = installed_runtimes()
        out["runtime_present"] = any(r.split("/")[0] == parts[0] and r.endswith("/" + parts[2]) for r in present) \
            or rt in present
        if not out["runtime_present"]:
            rd = flathub_get("/summary/" + parts[0])
            br = ((rd or {}).get("branches") or {}).get(parts[2]) if isinstance(rd, dict) else None
            if isinstance(br, dict):
                out["runtime_download"] = int(br.get("download_size") or 0)
                out["runtime_installed"] = int(br.get("installed_size") or 0)
    return out


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    cmd, arg = argv[0], argv[1]
    if cmd == "precheck":
        for sev, text in precheck(arg):
            print(f"FINDING\t{sev}\t{clean(text)}")
        return 0
    if cmd == "review":
        print_review(review(arg, argv[2] if len(argv) > 2 else None))
        return 0
    if cmd == "flathub":
        state, ids = flathub(arg)
        print(state + ("\t" + "\t".join(ids) if ids else ""))
        return 0 if state in ("ok", "ambiguous") else 1
    if cmd == "flathub-search":
        rows = flathub_search(" ".join(argv[1:]))
        if rows is None:
            return 1
        for r in rows:
            print("\t".join(x.replace("\t", " ") for x in r))
        return 0
    if cmd == "flathub-size":
        if not APP_ID.match(arg):
            return 2
        sz = flathub_size(arg)
        if sz is None:
            return 1
        print(json.dumps(sz))
        return 0
    print(f"lux_community: unknown command {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
