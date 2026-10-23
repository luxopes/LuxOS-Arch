"""Lux Guard - pravidla: rozpozna spustitelny obsah a nebezpecne chovani skriptu a programu.

Jen standardni knihovna, bez importu jinych casti LuxOS (pouziva ho sluzba luxos-guard jako root,
prikaz luxos-guard scan i testy). Analyza prikazu shellu (tokeny, promenne, rm/dd/mkfs/find, fork
bomby ...) je prevzata a upravena z tvrdych bloku LuxAI (luxai/rootguard.py); Lux Guard na balicku
luxai nezavisi.

classify(data, name) -> Verdict | None
  data = zacatek souboru (bytes, nejvyse MAX_READ), name = jmeno souboru (pripona).
  None = neni to spustitelny obsah (obrazek, dokument ...), Lux Guard ho nehlida.
  Verdict.kind: elf | appimage | script | desktop | jar | windows
  Verdict.reasons: KRITICKE duvody (anglicky, UI je prelozi) - soubor se mimo sandbox nespusti nikdy.
  Verdict.notes: mene zavazne poznamky (zobrazi se v dotazu u rizikoveho souboru).

Kriticke (reasons): smazani domova nebo systemu (rm -rf ~, find ~ -delete, shutil.rmtree(home) ...),
formatovani/prepis disku (dd of=/dev/sda, mkfs, wipefs, shred, blkdiscard), odstraneni zavadece
a jader, fork bomby, rozbiti prav celeho systemu, zmeny sudo/polkit/PAM, vypnuti Lux Guard nebo
mazani jeho zaloh, sifrovani souboru ve smycce (ransomware), skryty kod (base64 ... | sh, exec(b64decode))
a stazeni + okamzite spusteni kodu z internetu (curl | sh) jako spravce, z nesifrovane adresy
nebo z IP adresy. Ostatni nalezy jsou jen poznamky - zamerne malo falesnych poplachu: bezne
instalacni a sestavovaci skripty (rm -rf "$TMPDIR", sudo usermod -aG ...) kriticke nejsou.
"""
import base64
import binascii
import fnmatch
import os
import re
import shlex

MAX_COMMAND = 65536
MAX_READ = 16 * 1024 * 1024       # z programu (ELF) se cte nejvyse tolik
MAX_SCRIPT = 1024 * 1024          # skript se analyzuje nejvyse v tomto rozsahu
_MAX_SCRIPT = 256 * 1024          # (rootguard) cteni jinych skriptu - v Lux Guard se nepouziva

# ---- duvody (v UI prelozene) ----------------------------------------------------------------
# Kriticke
R_DELETE = "deletes your files, your home folder or the whole system"
R_BOOT = "removes the bootloader, kernels or core system packages"
R_DISK = "formats, wipes or overwrites a disk"
R_FORK = "freezes the computer (fork bomb)"
R_PERMS = "breaks permissions of the whole system or a system folder"
R_KERNEL = "crashes or instantly restarts the computer"
R_AUTH = "changes sudo, polkit or login (PAM) security settings"
R_GUARD = "tries to switch off Lux Guard or delete its backups"
R_REMOTE = "downloads code from the internet and runs it immediately without any check"
R_HIDDEN = "runs hidden (encoded) code"
R_RANSOM = "encrypts your files (ransomware behaviour)"
R_DYNAMIC = R_HIDDEN
CRITICAL = (R_DELETE, R_BOOT, R_DISK, R_FORK, R_PERMS, R_KERNEL, R_AUTH, R_GUARD, R_REMOTE, R_HIDDEN, R_RANSOM)
# Poznamky (rizikove, ale ne kriticke)
N_ACCOUNTS = "changes user accounts or passwords"
N_SIGNATURES = "disables package signature checks"
N_PASSWORD = "feeds a password to sudo or su"
N_REMOTE = "downloads more code from the internet and runs it"
N_ROOT = "asks for administrator rights"
N_AUTOSTART = "adds a program to startup"
NOTES = (N_ACCOUNTS, N_SIGNATURES, N_PASSWORD, N_REMOTE, N_ROOT, N_AUTOSTART)
# Jmena z rootguard (zbytek prevzateho kodu je pouziva)
R_ACCOUNTS = N_ACCOUNTS
R_SIGNATURES = N_SIGNATURES
R_PASSWORD = N_PASSWORD
R_SELF = R_GUARD
R_UNSURE = "the target of a destructive command cannot be verified"

# ---- predani hesla do sudo/su ----------------------------------------------------------------
_SUDO_OPT = (r"(?:-[A-Za-z]*[ugpChDrtTU]\s+\S+|--(?:user|group|prompt|close-from|host|chdir|role|type|"
             r"command-timeout|other-user)(?:=\S+|\s+\S+)|-[A-Za-z]+|--[\w-]+(?:=\S+)?)")
_SUDO_STDIN = re.compile(r"(?:^|[^\w.-])(?:\S*/)?sudo(?:\s+" + _SUDO_OPT +
                         r")*?\s+(?:-[A-Za-z]*S[A-Za-z]*|--stdin)(?=$|[\s'\";|&)])")
_PASSWORD_FEED = (
    _SUDO_STDIN,
    re.compile(r"\bSUDO_ASKPASS\s*="),
    re.compile(r"\|\s*(?:\S*/)?su(?:\s|$)"),
    re.compile(r"\bsshpass\b"),
)


def feeds_password(command):
    """True, kdyz prikaz predava heslo programu sudo/su (pres -S, rouru, here-string, SUDO_ASKPASS ...)."""
    text = str(command or "")
    return any(r.search(text) for r in _PASSWORD_FEED)


# ---- chranene cesty ---------------------------------------------------------------------------
SYSTEM_DIRS = frozenset({
    "/", "/bin", "/boot", "/dev", "/efi", "/etc", "/home", "/lib", "/lib32", "/lib64", "/mnt", "/opt", "/proc",
    "/run", "/sbin", "/srv", "/sys", "/tmp", "/usr", "/var", "/media",
    "/usr/bin", "/usr/lib", "/usr/lib32", "/usr/lib64", "/usr/sbin", "/usr/share", "/usr/include", "/usr/local",
    "/usr/lib/modules", "/usr/lib/systemd", "/usr/lib/firmware", "/var/lib", "/var/lib/pacman", "/var/log",
    "/etc/pacman.d", "/etc/systemd", "/var/lib/systemd", "/boot/efi", "/boot/grub", "/boot/loader"})
# slozky, jejichz obsah lze mazat maskou (rm -rf /tmp/*) - ostatni systemove slozky ne
_GLOB_OK = frozenset({"/tmp", "/var/tmp"})
_BOOT = ("/boot", "/efi", "/usr/lib/modules")
_DEVICE = re.compile(r"^/dev/(sd[a-z]+\d*|hd[a-z]+\d*|vd[a-z]+\d*|xvd[a-z]+\d*|nvme\d+(n\d+(p\d+)?)?|"
                     r"mmcblk\d+(p\d+|boot\d+|rpmb)?|dm-\d+|md\d+|md/.+|mapper/.+|disk/.+|block/.+|sr\d+|"
                     r"loop\d+|root|zram\d+|nbd\d+(p\d+)?|ubi.*|mtd.*)$")
_DEVICE_TEXT = re.compile(r"/dev/(sd[a-z]|hd[a-z]|vd[a-z]|xvd[a-z]|nvme\d|mmcblk\d|dm-\d|md\d|mapper/|disk/|"
                          r"block/|root\b|nbd\d|mtd)")
# chranene soubory a slozky (zapis = blok; cteni povolene) -> duvod
_PROTECTED = (
    ("/etc/sudoers", R_AUTH), ("/etc/sudoers.d", R_AUTH), ("/etc/doas.conf", R_AUTH),
    ("/etc/polkit-1", R_AUTH), ("/usr/share/polkit-1", R_AUTH), ("/usr/lib/polkit-1", R_AUTH),
    ("/etc/pam.d", R_AUTH), ("/usr/lib/pam.d", R_AUTH), ("/etc/security", R_AUTH), ("/usr/lib/security", R_AUTH),
    ("/etc/passwd", R_ACCOUNTS), ("/etc/passwd-", R_ACCOUNTS), ("/etc/shadow", R_ACCOUNTS),
    ("/etc/shadow-", R_ACCOUNTS), ("/etc/group", R_ACCOUNTS), ("/etc/group-", R_ACCOUNTS),
    ("/etc/gshadow", R_ACCOUNTS), ("/etc/gshadow-", R_ACCOUNTS), ("/etc/subuid", R_ACCOUNTS),
    ("/etc/subgid", R_ACCOUNTS), ("/etc/login.defs", R_ACCOUNTS),
    ("/usr/bin/luxos-guard", R_GUARD), ("/usr/lib/luxos/guard", R_GUARD), ("/var/lib/luxos-guard", R_GUARD),
    ("/usr/lib/systemd/system/luxos-guard.service", R_GUARD), ("/etc/systemd/system/luxos-guard.service", R_GUARD),
)
# zminka v textu (i v kodu pythonu apod.) + zapisujici prikaz = blok
_PROTECTED_TEXT = (
    (re.compile(r"/etc/sudoers|/etc/doas\.conf|\bsudoers\b"), R_AUTH),
    (re.compile(r"polkit-1|\.rules\b.*polkit|polkit.*\.rules\b"), R_AUTH),
    (re.compile(r"/pam\.d\b|/etc/security/|/lib/security/|\bpam_\w+\.so\b"), R_AUTH),
    (re.compile(r"/etc/(passwd|shadow|group|gshadow|subuid|subgid|login\.defs)\b"), R_ACCOUNTS),
    (re.compile(r"luxos-guard-snapshots|/var/lib/luxos-guard\b"), R_GUARD),
)
_SIGLEVEL = re.compile(r"siglevel\s*=?\s*[^\n;|&]*\b(never|trustall)\b|--skip(pgpcheck|checksums|integ)\b|"
                       r"--nosig\b|pacman\.conf\b.*\b(never|trustall)\b|\b(never|trustall)\b.*pacman\.conf\b")
_FORK = (re.compile(r"(?:^|[\s;&|({])([^\s;&|(){}=]+)\s*\(\s*\)\s*\{[^}]*?(?<![\w.:-])\1\s*\|\s*&?\s*\1"),
         re.compile(r"\bfunction\s+([\w:.-]+)\s*(?:\(\s*\))?\s*\{[^}]*?(?<![\w.:-])\1\s*\|\s*\1"),
         re.compile(r"\bfork\s*(?:\(\s*\))?\s*while\s+fork\b|\bwhile\s*\(?\s*(?:1|true|True)\s*\)?\s*[:;{]?\s*"
                    r"(?:os\.)?fork\s*\(\)"))
_REDIRECT_DEV = re.compile(r"(?:>|>>|>\||&>|<>)\s*" + _DEVICE_TEXT.pattern)
_SYSRQ = re.compile(r"sysrq-trigger")
_REMOTE = (re.compile(r"\b(curl|wget|fetch|aria2c|xh|https?)\b[^|;&]*\|\s*(?:\S*/)?(?:env\s+(?:-\S+\s+)*)?"
                      r"(?:(?:sudo|doas|pkexec)\s+(?:-\S+\s+)*)?(?:ba|z|da|k|fi|c|tc)?sh\b"),
           re.compile(r"\b(curl|wget|fetch|aria2c)\b[^|;&]*\|\s*(?:\S*/)?(python\d*|perl|ruby|node|php)\b"),
           re.compile(r"\$\(\s*(curl|wget|fetch)\b|<\(\s*(curl|wget|fetch)\b|`\s*(curl|wget|fetch)\b"))
_PIPE_SHELL = re.compile(r"\|\s*(?:\S*/)?(?:env\s+(?:-\S+\s+)*)?(?:(?:sudo|doas|pkexec|nohup|exec)\s+(?:-\S+\s+)*)?"
                         r"(?:ba|z|da|k|fi|c|tc|busybox\s+)?sh\b(?!\s+-c)|\|\s*(?:\S*/)?(python\d*(\.\d+)?|perl|"
                         r"ruby|node|php)\s*(?:-\s*)?(?:$|[;&|)])|\|\s*(?:\S*/)?(?:source|\.)\s+/dev/stdin")

_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "mksh", "fish", "ash", "csh", "tcsh", "rbash", "busybox", "lsh"}
_INTERP = {"python", "python2", "python3", "perl", "ruby", "node", "nodejs", "php", "lua", "tclsh", "awk", "gawk",
           "mawk", "nawk"}
_PREFIX = {"env", "nice", "nohup", "time", "command", "exec", "builtin", "stdbuf", "ionice", "timeout", "setsid",
           "chrt", "taskset", "unbuffer", "sudo", "doas", "pkexec", "run0", "flock", "chroot", "nsenter",
           "systemd-run", "caffeinate", "watch", "xargs", "parallel", "strace", "ltrace", "busybox", "firejail",
           "unshare", "cgexec", "numactl", "eatmydata", "fakeroot", "script", "su"}
_KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "{", "}", "done", "fi", "esac", "coproc"}
_READONLY = {"cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg", "ls", "stat", "file", "wc",
             "diff", "cmp", "md5sum", "sha1sum", "sha256sum", "sha512sum", "b2sum", "getent", "id", "namei",
             "lsattr", "test", "[", "[[", "pkaction", "pkcheck", "readlink", "realpath", "echo", "printf", "uniq",
             "cut", "tr", "column", "nl", "strings", "od", "journalctl", "true", "false", "which", "type", "pwd",
             "dirname", "basename", "du", "df", "tree", "bat", "jq", "groups", "whoami", "pacman-conf", "visudo",
             "find", "sort", "wc", "zcat", "zgrep", "xxd", "hexdump", "systemctl", "loginctl", "lsblk", "blkid",
             "findmnt", "mount", "uname", "date", "sleep", "cd", "exit", "return", ":"}
_PART_TOOLS = {"fdisk", "gdisk", "cfdisk", "cgdisk", "sfdisk", "sgdisk", "parted", "partx", "delpart", "resizepart",
               "addpart", "kpartx"}
_PART_RO = {"-l", "--list", "-p", "--print", "-i", "--info", "-v", "--verify", "-d", "--dump", "-J", "--json",
            "-s", "--show-size", "-V", "--list-types", "-T", "-g", "--show-geometry", "--show", "-L", "print",
            "--list-free", "-F", "-x", "--version", "-h", "--help"}
_PARTED_WRITE = {"mklabel", "mktable", "mkpart", "mkpartfs", "rm", "resizepart", "resize", "set", "toggle", "name",
                 "rescue", "mkfs", "move", "cp", "disk_set", "disk_toggle", "type"}
_FS_TOOLS = re.compile(r"^(mkfs(\..+)?|mke2fs|mkswap|mkntfs|mkdosfs|mkexfatfs|mkfs_\w+|mkudffs|mkreiserfs|"
                       r"mkfs\w+|newfs.*|wipefs|shred|blkdiscard|badblocks|scrub|wipe|sg_format|e2image|zerofree)$")
_DEV_WRITERS = {"tee", "cp", "install", "truncate", "ln", "mv", "rsync", "pv", "dd", "cat", "ddrescue", "dcfldd",
                "dc3dd", "flashrom", "xz", "gzip", "zstd", "bzip2", "unzip", "tar", "socat", "nc", "ncat"}
_ACCOUNT_CMDS = {"userdel", "deluser", "usermod", "chpasswd", "useradd", "adduser", "gpasswd", "groupdel",
                 "groupmod", "vipw", "vigr", "newusers", "chsh", "chfn", "pwconv", "pwunconv", "grpconv",
                 "grpunconv", "pwck", "grpck", "lusermod", "luserdel", "smbpasswd", "homectl", "faillock"}
_CORE_PKGS = {"linux", "linux-lts", "linux-zen", "linux-hardened", "linux-rt", "linux-rt-lts", "linux-firmware",
              "grub", "efibootmgr", "systemd", "systemd-libs", "systemd-sysvcompat", "glibc", "pacman", "lux-engine", "base",
              "filesystem", "bash", "coreutils", "sudo", "polkit", "pam", "shadow", "util-linux", "mkinitcpio",
              "dracut", "booster", "refind", "limine", "syslinux", "intel-ucode", "amd-ucode", "archlinux-keyring",
              "gcc-libs", "python", "lux", "luxos-base", "luxos-keyring", "luxai"}
_PKG_TOOLS = {"pacman", "yay", "paru", "pamac", "pikaur", "trizen", "aura", "lux"}
_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\+?=(.*)$", re.S)
_VAR = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-=+?])([^}]*))?\}|([A-Za-z_][A-Za-z0-9_]*)|([0-9@*#?$!-]))")
_GLOB = re.compile(r"[*?\[]")
_FIND_FILTERS = {"-name", "-iname", "-path", "-ipath", "-regex", "-iregex", "-wholename", "-iwholename",
                 "-newer", "-mtime", "-mmin", "-atime", "-amin", "-ctime", "-cmin", "-size", "-user", "-group",
                 "-empty", "-lname", "-ilname", "-perm", "-uid", "-gid", "-nouser", "-nogroup"}
_MAX_DEPTH = 8
# find -exec PRIKAZ: prikazy, ktere soubory nici nebo meni (ostatni, napr. getcap, jen ctou)
_FIND_DESTRUCTIVE = {"rm", "shred", "unlink", "mv", "truncate", "dd", "chmod", "chown", "chattr", "gpg", "gpg2",
                     "openssl", "age", "ccrypt", "7z", "7za", "zip", "cp", "tee", "sed", "perl", "python", "python3",
                     "xargs", "wipe", "srm", "rmdir"}
_MAX_SCRIPT = 256 * 1024


class _Found(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class _Ctx:
    def __init__(self, root, cwd, home):
        self.root = root
        self.cwd = cwd
        self.home = home
        self.vars = {}          # jmeno -> seznam moznych hodnot (None = neznama)
        self.depth = 0
        self.scripts = 0

        self.found = []         # vsechny nalezene duvody a poznamky (poradi nalezu)

    def block(self, reason):
        """Kriticky duvod ukonci analyzu, poznamka se jen zaznamena."""
        if reason not in self.found:
            self.found.append(reason)
        if reason in CRITICAL:
            raise _Found(reason)

    def unsure(self, reason=R_UNSURE):
        if self.root:
            raise _Found(reason)


HOME = "/home/user"     # domov pro analyzu (skript nezname odkud; ~ a $HOME se rozbali sem)


_LONG_LINE = 4000


def _clip(text):
    """Velmi dlouhe radky (zakodovana data) zkratit na zacatek a konec: regularni vyrazy nad nimi by
    mohly trvat neumerne dlouho (zamerne patologicky soubor). "echo <data> | base64 -d | sh" zustane."""
    if len(text) < _LONG_LINE or not any(len(x) > _LONG_LINE for x in text.splitlines()):
        return text
    return "\n".join(x if len(x) <= _LONG_LINE else x[:_LONG_LINE // 2] + " " + x[-_LONG_LINE // 2:]
                     for x in text.splitlines())


def analyze_shell(text, cwd=None, home=HOME):
    """Text skriptu nebo prikazu shellu -> (kriticke duvody, poznamky). Neduveryhodny kod: vse,
    co nelze s jistotou urcit (promenne, $(...)), se nepocita jako kriticke - jen jasne nalezy."""
    ctx = _Ctx(False, os.path.normpath(cwd) if cwd else None, os.path.normpath(home))
    try:
        _analyze(_clip(str(text or "")[:MAX_SCRIPT]), ctx)
    except _Found:
        pass
    except RecursionError:
        pass
    return _split(ctx.found)


def _split(found):
    crit = [r for r in found if r in CRITICAL]
    notes = [r for r in found if r not in CRITICAL]
    return crit, notes


def hard_block(command, cwd=None, home=HOME):
    """Prvni kriticky duvod pro prikaz shellu, jinak None (kompatibilni tvar s rootguard)."""
    crit, _notes = analyze_shell(command, cwd, home)
    return crit[0] if crit else None


# ---- analyza textu ---------------------------------------------------------------------------------
def _dequote(text):
    """Text bez uvozovek a zpetnych lomitek, se zjednodusenymi cestami (/./, //) - proti obfuskaci
    typu r''m, /de\\v/sda, /etc//pam.d."""
    t = re.sub(r"\\\n", "", text)
    t = re.sub(r"[\"'\\]", "", t)
    t = re.sub(r"\$''", "", t)
    for _ in range(4):
        t = re.sub(r"/\./", "/", t)
    return re.sub(r"/{2,}", "/", t)


def _text_checks(text, ctx):
    low = text.lower()
    flat = _dequote(text)
    flow = flat.lower()
    if feeds_password(text) or feeds_password(flat):
        ctx.block(N_PASSWORD)
    for r in _FORK:
        if r.search(text) or r.search(flat):
            ctx.block(R_FORK)
    if _REDIRECT_DEV.search(flat):
        ctx.block(R_DISK)
    if _SYSRQ.search(flat) and (">" in flat or "tee" in flow):
        ctx.block(R_KERNEL)
    if _SIGLEVEL.search(flow):
        ctx.block(R_SIGNATURES)
    _guard_text_checks(text, flat, ctx)


def _mentions(flat):
    """Chranena mista zminena v textu (i v retezcich kodu) -> seznam duvodu."""
    return [reason for r, reason in _PROTECTED_TEXT if r.search(flat)]


def _substitutions(text):
    """Vnitrky $(...), <(...), >(...) a `...` (rekurzivni kontrola)."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c in "$<>" and i + 1 < n and text[i + 1] == "(":
            depth, j = 1, i + 2
            while j < n and depth:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                j += 1
            out.append(text[i + 2:j - 1] if depth == 0 else text[i + 2:])
            i = j
            continue
        if c == "`":
            j = text.find("`", i + 1)
            out.append(text[i + 1:j] if j > 0 else text[i + 1:])
            i = j + 1 if j > 0 else n
            continue
        i += 1
    return out


def _tokens(text):
    """Tokeny shellu; oddelovace (;, &&, |, ...) a presmerovani (>, >>, <) jako samostatne tokeny."""
    t = text.replace("\r", "")
    t = re.sub(r"\\\n", "", t)
    # komentare pryc (apostrof v "# Don't change" by jinak rozbil cely rozbor)
    t = re.sub(r"(?m)(^|[ \t;&|])#[^\n]*", r"\1", t)
    t = t.replace("\n", " ; ")
    try:
        lex = shlex.shlex(t, posix=True, punctuation_chars=";&|()<>")
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex), True
    except ValueError:
        return [x.strip("\"'") for x in re.split(r"(\s+|[;&|()<>]+)", t) if x and not x.isspace()], False


def _simple_commands(tokens):
    """[(tokeny, presmerovani pro zapis, vstup (soubory, here-stringy, "<<"), oddelovac pred)]"""
    cmds, cur, wr, rd, sep = [], [], [], [], ";"
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t and set(t) <= set(";&|()"):
            if cur or wr or rd:
                cmds.append((cur, wr, rd, sep))
            cur, wr, rd = [], [], []
            sep = t
            i += 1
            continue
        if t and set(t) <= set("<>&|") and ("<" in t or ">" in t):
            if cur and cur[-1].isdigit():
                cur.pop()               # 2> soubor: cislo deskriptoru neni argument
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            if t in ("<<", "<<-"):
                rd.append(("heredoc", nxt))
            elif t == "<<<":
                rd.append(("string", nxt))
            elif ">" in t and "<" not in t:
                if nxt and not (t.endswith("&") and (nxt.isdigit() or nxt == "-")):
                    wr.append(nxt)
            elif nxt:
                rd.append(("file", nxt))
                if ">" in t:
                    wr.append(nxt)      # <> soubor: cteni i zapis
            i += 2
            continue
        cur.append(t)
        i += 1
    if cur or wr or rd:
        cmds.append((cur, wr, rd, sep))
    return cmds


_SUBST_VAR = "${__luxai_subst}"


def _mask_substitutions(text):
    """$(...), `...`, <(...) a >(...) nahradi neznamou promennou: vysledek nelze predem znat."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            out.append(text[i:i + 2])
            i += 2
            continue
        if c in "$<>" and i + 1 < n and text[i + 1] == "(":
            depth, j = 1, i + 2
            while j < n and depth:
                if text[j] == "\\":
                    j += 2
                    continue
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            out.append(_SUBST_VAR)
            i = j
            continue
        if c == "`":
            j = text.find("`", i + 1)
            out.append(_SUBST_VAR)
            i = j + 1 if j > 0 else n
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _analyze(text, ctx):
    ctx.depth += 1
    try:
        if ctx.depth > _MAX_DEPTH:
            ctx.unsure(R_DYNAMIC)
            return
        _text_checks(text, ctx)
        for inner in _substitutions(text):
            _analyze(inner, ctx)
        tokens, parsed = _tokens(_mask_substitutions(text))
        if not parsed and ctx.root:
            ctx.unsure(R_DYNAMIC)
        cmds = _simple_commands(tokens)
        flat = _dequote(text)
        mentioned = _mentions(flat)
        writers = False
        cwd0 = ctx.cwd
        for toks, wr, rd, sep in cmds:
            if _command(toks, wr, rd, sep, ctx):
                writers = True
        ctx.cwd = cwd0
        if mentioned and writers and ctx.root:
            ctx.block(mentioned[0])
    finally:
        ctx.depth -= 1


# ---- promenne a cesty ------------------------------------------------------------------------------
def _expand_braces(tok, limit=32):
    m = re.search(r"\{([^{}]*,[^{}]*)\}", tok)
    if not m:
        return [tok]
    out = []
    for part in m.group(1).split(","):
        out.extend(_expand_braces(tok[:m.start()] + part + tok[m.end():], limit))
        if len(out) >= limit:
            break
    return out[:limit]


def _values(tok, ctx):
    """Mozne hodnoty tokenu po rozbaleni ~, promennych a {a,b}: [(hodnota, dynamicka)]."""
    homes = [ctx.home] + (["/root"] if ctx.root and ctx.home != "/root" else [])
    variants = [(tok, False)]
    if tok == "~" or tok.startswith("~/"):
        variants = [(h + tok[1:], False) for h in homes]
    elif re.match(r"^~[a-z_][a-z0-9_-]*(/|$)", tok):
        variants = [("/home/" + tok[1:], False)]
    out = []
    for v, dyn in variants:
        out.extend(_subst_vars(v, ctx, dyn))
    res = []
    for v, dyn in out[:64]:
        if "$(" in v or "`" in v or "<(" in v:
            dyn = True
        for b in _expand_braces(v):
            res.append((b, dyn))
    return res[:64]


def _subst_vars(value, ctx, dyn):
    m = _VAR.search(value)
    if not m:
        return [(value, dyn)]
    name = m.group(1) or m.group(4)
    special = m.group(5)
    op, default = m.group(2), m.group(3)
    if special is not None:
        vals = [None]
    elif name == "HOME":
        vals = [ctx.home] + (["/root"] if ctx.root else [])
    elif name == "PWD":
        vals = [ctx.cwd]
    elif name in ctx.vars:
        vals = ctx.vars[name]
    elif op in ("-", ":-", "=", ":=") and default is not None:
        vals = [default]
    else:
        vals = [None]
    out = []
    for v in vals[:16]:
        if v is None:
            # neznama hodnota: zustane prazdna a token je "dynamicky" (rm -rf $X/ -> muze byt /)
            out.extend(_subst_vars(value[:m.start()] + value[m.end():], ctx, True))
        else:
            out.extend(_subst_vars(value[:m.start()] + v + value[m.end():], ctx, dyn))
    return out[:64]


def _abs(value, ctx):
    """Absolutni normalizovana cesta, nebo None (relativni cesta s neznamou pracovni slozkou)."""
    v = value
    if not v.startswith("/"):
        if ctx.cwd is None:
            return None
        v = os.path.join(ctx.cwd, v)
    v = re.sub(r"/{2,}", "/", v)
    n = os.path.normpath(v)
    return "/" if n.startswith("//") else n


def _is_home_root(p, ctx):
    return p in (ctx.home, "/root") or bool(re.match(r"^/home/[^/]+$", p))


def _covers(p, dirs):
    """p je nektera ze slozek nebo jejich nadrazena slozka."""
    if p == "/":
        return True
    return any(d == p or d.startswith(p + "/") for d in dirs)


def _protected_dir(p, ctx, homes=True):
    if _covers(p, SYSTEM_DIRS):
        return True
    if homes and (_is_home_root(p, ctx) or ctx.home.startswith(p + "/")):
        return True
    return False


def _in_boot(p):
    return any(p == b or p.startswith(b + "/") for b in _BOOT)


def _glob_prefix(p):
    """Cast cesty pred prvni slozkou s maskou (/usr/l* -> /usr), nebo None bez masky."""
    if not _GLOB.search(p):
        return None
    parts = p.split("/")
    pre = []
    for part in parts:
        if _GLOB.search(part):
            break
        pre.append(part)
    return "/".join(pre) or "/"


_SAMPLE_NAMES = ("Documents", "Desktop", ".config", ".local", "usr", "etc", "home", "x", "a1")


def _glob_hits(p, ctx, homes=True):
    """Maska v ceste muze zasahnout chranenou slozku (/*, /e*, ~/.*, /usr/l*, /var/lib/pacman/*);
    uzka maska (/etc/*.pacnew, ~/build/*) ne."""
    pre = _glob_prefix(p)
    if pre is None or pre in _GLOB_OK:
        return False
    if not _protected_dir(pre, ctx, homes) and not _in_boot(pre):
        return False
    comp = p[len(pre):].lstrip("/").split("/")[0]
    names = set(_SAMPLE_NAMES) | {os.path.basename(ctx.home)}
    for d in list(SYSTEM_DIRS) + [ctx.home, "/root"] + [b for b, _r in _PROTECTED]:
        if os.path.dirname(d) == pre:
            names.add(os.path.basename(d))
    return any(fnmatch.fnmatchcase(n, comp) for n in names)


def _check_delete(value, ctx, recursive, homes=True, reason=R_DELETE):
    """Kontrola cile mazani/presunu (rm, mv, find -delete)."""
    if value == "":
        return                  # rm -rf "" nic nesmaze
    p = _abs(value, ctx)
    if p is None:
        if recursive:
            ctx.unsure()
        return
    pre = _glob_prefix(p)
    if _in_boot(p) or (pre is not None and _in_boot(pre + "/x")):
        # jeden soubor v /boot (zaloha initramfs) neni kriticky; cela slozka, jadro nebo zavadec ano
        if ctx.root or recursive and "." not in os.path.basename(p) or pre is not None or p in _BOOT or \
                re.search(r"vmlinuz|\.efi$|/EFI\b|grub|/loader\b", p, re.I):
            ctx.block(R_BOOT)
    if pre is not None:
        if _glob_hits(p, ctx, homes):
            ctx.block(reason)
        return
    if recursive and _protected_dir(p, ctx, homes):
        ctx.block(reason)
    if p == "/" or _is_home_root(p, ctx) and homes:
        ctx.block(reason)


def _protected_path(p):
    for base, reason in _PROTECTED:
        if p == base or p.startswith(base.rstrip("/") + "/"):
            return reason
    return None


# ---- jednotlive prikazy ----------------------------------------------------------------------------
def _strip(toks, ctx):
    """Odstrani prefixy (env A=B, sudo -u x, nice -n 5, timeout 10, xargs -0 ...).
    Vraci (zbytek, z_xargs). Vnitrni retezce (env -S, su -c) zkontroluje rekurzivne."""
    i, xargs = 0, False
    while i < len(toks):
        t = toks[i]
        b = os.path.basename(t)
        if _ASSIGN.match(t) or t in _KEYWORDS:
            i += 1
            continue
        if b not in _PREFIX:
            break
        i += 1
        if b in ("xargs", "parallel", "watch"):
            xargs = True
        if b == "su":
            # su [-] [uzivatel] [-c PRIKAZ]
            rest = toks[i:]
            if "-c" in rest or "--command" in rest:
                k = rest.index("-c") if "-c" in rest else rest.index("--command")
                if k + 1 < len(rest):
                    _analyze(rest[k + 1], ctx)
            return [], xargs
        if b == "chroot":
            while i < len(toks) and toks[i].startswith("-"):
                i += 1
            if i < len(toks):
                p = _abs(toks[i], ctx)
                if p != "/":
                    ctx.unsure(R_DYNAMIC)
                i += 1
            continue
        if b == "flock" or b == "cgexec":
            while i < len(toks) and toks[i].startswith("-"):
                i += 1
            i += 1
            continue
        # volby prefixu (u nekterych s hodnotou)
        with_val = {"sudo": {"-u", "-g", "-p", "-C", "-h", "-D", "-r", "-t", "-U", "-T", "--user", "--group",
                             "--prompt", "--chdir", "--host"},
                    "env": {"-u", "--unset", "-C", "--chdir"}, "nice": {"-n", "--adjustment"},
                    "ionice": {"-c", "-n", "-p", "-P", "-u"}, "timeout": {"-s", "--signal", "-k", "--kill-after"},
                    "stdbuf": set(), "taskset": set(), "chrt": set(), "pkexec": {"--user"},
                    "xargs": {"-I", "-n", "-P", "-d", "-L", "-s", "-E", "-a", "--arg-file", "--delimiter",
                              "--max-args", "--max-procs", "--replace"},
                    "systemd-run": {"-p", "--property", "-u", "--unit", "-E", "--setenv", "--uid", "--gid",
                                    "-M", "--machine"},
                    "doas": {"-u", "-C"}, "run0": {"-u", "--user", "-g", "--group", "-D", "--chdir"},
                    "nsenter": {"-t", "--target"}, "numactl": set(), "strace": {"-o", "-e", "-p", "-s"},
                    "script": {"-c", "--command"}, "firejail": set(), "unshare": set(),
                    "watch": {"-n", "--interval"}}.get(b, set())
        while i < len(toks) and toks[i].startswith("-") and toks[i] != "--":
            opt = toks[i]
            if b == "env" and opt in ("-S", "--split-string") and i + 1 < len(toks):
                _analyze(toks[i + 1], ctx)
                return [], xargs
            if b == "env" and opt.startswith("--split-string="):
                _analyze(opt.split("=", 1)[1], ctx)
                return [], xargs
            if b == "script" and opt in ("-c", "--command") and i + 1 < len(toks):
                _analyze(toks[i + 1], ctx)
                return [], xargs
            i += 1
            if opt in with_val and i < len(toks):
                i += 1
        if i < len(toks) and toks[i] == "--":
            i += 1
        if b == "timeout" and i < len(toks) and re.match(r"^\d+(\.\d+)?[smhd]?$", toks[i]):
            i += 1
        if b == "script" and i < len(toks):
            i += 1  # soubor zaznamu
        if b in ("nice",) and i < len(toks) and re.match(r"^-?\d+$", toks[i]):
            i += 1
    return toks[i:], xargs


def _script_file(path, ctx):
    """Kontrola obsahu spousteneho skriptu (bash skript.sh, source, ./skript se #!)."""
    if not ctx.root:
        return
    ctx.scripts += 1
    if ctx.scripts > 8:
        ctx.unsure(R_DYNAMIC)
        return
    try:
        st = os.stat(path)
    except OSError:
        return
    if not os.path.isfile(path):
        return
    if st.st_size > _MAX_SCRIPT:
        ctx.unsure(R_DYNAMIC)
        return
    try:
        with open(path, "rb") as f:
            data = f.read(_MAX_SCRIPT + 1)
    except OSError:
        return
    if b"\x00" in data[:8192]:
        return
    _analyze(data.decode("utf-8", "replace"), ctx)


def _command(raw, wr, rd, sep, ctx):
    """Kontrola jednoho jednoducheho prikazu. Vraci True, pokud prikaz neco meni (neni jen cteci)."""
    # prirazeni promennych (X=/ ; export X=/ ; for X in a b)
    toks = list(raw)
    while toks and toks[0] in _KEYWORDS:
        toks = toks[1:]
    if toks and toks[0] == "for" and len(toks) >= 2:
        name = toks[1]
        vals = []
        if "in" in toks:
            for t in toks[toks.index("in") + 1:]:
                for v, dyn in _values(t, ctx):
                    vals.append(None if dyn else v)
        ctx.vars[name] = vals or [None]
        return False
    if toks and toks[0] in ("export", "declare", "local", "readonly", "typeset", "let"):
        for t in toks[1:]:
            m = _ASSIGN.match(t)
            if m:
                ctx.vars[m.group(1)] = [None if d else v for v, d in _values(m.group(2), ctx)][:16] or [None]
        return False
    if toks and toks[0] in ("read", "mapfile", "readarray"):
        for t in toks[1:]:
            if re.match(r"^[A-Za-z_]\w*$", t):
                ctx.vars[t] = [None]
        return False
    k = 0
    assigns = []
    while k < len(toks) and _ASSIGN.match(toks[k]):
        assigns.append(_ASSIGN.match(toks[k]))
        k += 1
    if k == len(toks):
        for m in assigns:
            ctx.vars[m.group(1)] = [None if d else v for v, d in _values(m.group(2), ctx)][:16] or [None]
        # jen prirazeni; zapis presmerovanim se kontroluje nize
        toks = []
    rest, xargs = _strip(toks, ctx) if toks else ([], False)
    writes = _check_redirects(wr, ctx)
    if not rest:
        return writes
    name_tok = rest[0]
    if (re.search(r"[$`]", name_tok) or _GLOB.search(name_tok)) and name_tok not in ("[", "[[", "]]", "]"):
        # neznamy program ($(echo rm) -rf /): u roota odmitnout, jinak aspon zkontrolovat zname cile
        ctx.unsure(R_DYNAMIC)
        if any(re.match(r"^-[A-Za-z]*[rR]", a) for a in rest[1:]):
            for a in rest[1:]:
                for v, d in _values(a, ctx):
                    if v and not v.startswith("-") and (ctx.root or not d):
                        _check_delete(v, ctx, True)
        return True
    name = os.path.basename(name_tok)
    args = rest[1:]
    vals = []          # rozbalene argumenty: seznam (puvodni, [(hodnota, dynamicka)])
    for a in args:
        vals.append((a, _values(a, ctx)))
    flat_args = [v for _a, vs in vals for v, _d in vs]
    dyn_args = any(d for _a, vs in vals for _v, d in vs)
    shorts = "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))
    longs = {a.split("=", 1)[0] for a in args if a.startswith("--")}

    def targets(skip_values=()):
        out, after = [], False
        it = iter(range(len(vals)))
        for idx in it:
            a, vs = vals[idx]
            if a == "--" and not after:
                after = True
                continue
            if not after and a.startswith("-") and a != "-":
                if a in skip_values:
                    next(it, None)
                continue
            out.extend(vs)
        return out

    # cd: pracovni slozka pro dalsi prikazy
    if name == "cd":
        t = targets()
        if not t:
            ctx.cwd = ctx.home
        elif len(t) == 1 and not t[0][1]:
            ctx.cwd = _abs(t[0][0], ctx) if t[0][0] != "-" else None
        else:
            ctx.cwd = None
        return False
    # shell, eval, source, interprety
    if name in _SHELLS:
        if name == "busybox":
            return _command(args, [], [], sep, ctx) if args else False
        cflag = next((i for i, a in enumerate(args) if a.startswith("-") and not a.startswith("--")
                      and "c" in a[1:]), None)
        if cflag is not None:
            if cflag + 1 < len(args):
                _analyze(args[cflag + 1], ctx)
            return True
        for kind, body in rd:
            if kind == "string":
                _analyze(body, ctx)
        files = [a for a in args if not a.startswith("-")]
        if files:
            for v, d in _values(files[0], ctx):
                p = _abs(v, ctx)
                if d or p is None:
                    ctx.unsure(R_DYNAMIC)
                else:
                    _script_file(p, ctx)
        elif sep in ("|", "|&") or rd:
            ctx.unsure(R_DYNAMIC)
        return True
    if name == "eval":
        code = " ".join(args)
        if re.search(r"[$`]", code):
            ctx.unsure(R_DYNAMIC)
        _analyze(code, ctx)
        return True
    if name in ("source", "."):
        if args:
            for v, d in _values(args[0], ctx):
                p = _abs(v, ctx)
                if d or p is None or p.startswith("/dev/") or p.startswith("/proc/"):
                    ctx.unsure(R_DYNAMIC)
                else:
                    _script_file(p, ctx)
        return True
    if re.sub(r"[\d.]+$", "", name) in _INTERP:
        _interpreter(name, args, sep, rd, ctx)
        return True
    if "/" in name_tok:
        p = _abs(name_tok, ctx)
        if p and not p.startswith(("/usr/", "/bin/", "/sbin/")):
            _script_file(p, ctx)
    if xargs and name in ("rm", "chmod", "chown", "chgrp", "shred", "dd", "mv", "find", "truncate", "wipefs",
                          "unlink", "rmdir") or xargs and _FS_TOOLS.match(name):
        ctx.unsure()

    # --- mazani a presuny
    if name in ("rm", "unlink", "rmdir"):
        recursive = name == "rm" and ("r" in shorts.lower() or "--recursive" in longs)
        if "--no-preserve-root" in longs:
            ctx.block(R_DELETE)
        for v, d in targets():
            if d:
                if recursive or _GLOB.search(v):
                    ctx.unsure()
                if not v or not ctx.root:
                    # neduveryhodny skript: rm -rf "$DIR/"* s neznamou promennou neni jisty nalez
                    # (bezne v instalacnich skriptech) - kriticke jsou jen zname cile
                    continue
            _check_delete(v, ctx, recursive or name == "rmdir")
        return True
    if name == "mv":
        t = targets({"-t", "--target-directory", "-S", "--suffix"})
        srcs = t[:-1] if len(t) > 1 else t
        for v, d in srcs:
            if d:
                ctx.unsure()
                if not v or not ctx.root:
                    continue
            _check_delete(v, ctx, True)
        return True
    if name == "find":
        starts = []
        for a, vs in vals:
            if a.startswith("-") or a in ("(", "!", ")"):
                break
            starts.extend(vs)
        acts = {"-delete", "-exec", "-execdir", "-ok", "-okdir"}
        destructive = "-delete" in args or ctx.root
        for i, a in enumerate(args):
            if a in acts - {"-delete"} and i + 1 < len(args):
                inner = os.path.basename(args[i + 1])
                if inner in _FIND_DESTRUCTIVE or _FS_TOOLS.match(inner) or inner in _SHELLS:
                    destructive = True
        if any(a in acts for a in args) and not destructive:
            for i, a in enumerate(args):
                if a in acts - {"-delete"}:
                    j = i + 1
                    inner = []
                    while j < len(args) and args[j] not in (";", "\\;", "+"):
                        inner.append(args[j])
                        j += 1
                    if inner:
                        _command(inner, [], [], ";", ctx)
            return True
        if any(a in acts for a in args):
            filtered = any(a in _FIND_FILTERS for a in args)
            if filtered and _doc_filters_only(args):
                filtered = False    # find ~ -name '*.jpg' -delete: maze vlastni dokumenty, jako bez filtru
            for v, d in starts or [(".", False)]:
                if d:
                    ctx.unsure()
                    if not v or not ctx.root:
                        continue
                p = _abs(v, ctx)
                if p is None:
                    ctx.unsure()
                    continue
                if p == "/" or _in_boot(p) or _GLOB.search(p) and _glob_hits(p, ctx):
                    ctx.block(R_BOOT if _in_boot(p) else R_DELETE)
                if p in _GLOB_OK or p == "/var/log":
                    continue
                if _protected_dir(p, ctx, homes=False) or not filtered and _protected_dir(p, ctx):
                    ctx.block(R_DELETE)
            for i, a in enumerate(args):
                if a in acts - {"-delete"}:
                    j = i + 1
                    inner = []
                    while j < len(args) and args[j] not in (";", "\\;", "+"):
                        inner.append(args[j])
                        j += 1
                    if inner:
                        _command(inner, [], [], ";", ctx)
            return True
        return False
    # --- prava a vlastnik
    if name in ("chmod", "chown", "chgrp", "setfacl", "chattr", "chcon", "setfattr"):
        recursive = "R" in shorts or "--recursive" in longs or (name == "setfacl" and "R" in shorts)
        t = targets({"--reference", "--from"})
        if name in ("chmod", "chown", "chgrp", "chattr") and t and not t[0][0].startswith("/") and \
                not t[0][0].startswith("~") and not t[0][0].startswith("$"):
            t = t[1:]           # rezim nebo vlastnik
        for v, d in t:
            p = _abs(v, ctx)
            if d or p is None:
                if recursive:
                    ctx.unsure()
                continue
            if _glob_hits(p, ctx, homes=False):
                ctx.block(R_PERMS)
            if recursive and _protected_dir(p, ctx, homes=False):
                ctx.block(R_PERMS)
            if p == "/" or p in ("/usr", "/etc", "/bin", "/sbin", "/lib", "/lib64", "/boot", "/var", "/home",
                                 "/usr/bin", "/usr/lib"):
                ctx.block(R_PERMS)
            r = _protected_path(p)
            if r:
                ctx.block(r)
        return True
    # --- disky
    if name == "dd" or name in ("ddrescue", "dcfldd", "dc3dd"):
        for a, vs in vals:
            if a.startswith("of="):
                for v, d in _values(a[3:], ctx):
                    p = _abs(v, ctx)
                    if d or p is None:
                        ctx.unsure()
                    elif _DEVICE.match(p) or p.startswith("/dev/") and _GLOB.search(p):
                        ctx.block(R_DISK)
                    elif _in_boot(p):
                        ctx.block(R_BOOT)
                    elif _protected_path(p):
                        ctx.block(_protected_path(p))
        if name != "dd" and any(_DEVICE.match(v) for v in flat_args[1:]):
            ctx.block(R_DISK)
        return True
    if _FS_TOOLS.match(name):
        if name == "wipefs" and not ({"a", "o"} & set(shorts) or {"--all", "--offset"} & longs):
            return False    # jen vypis
        if name == "badblocks" and "w" not in shorts and "n" not in shorts:
            return False
        for a, vs in vals:
            if a.startswith("-"):
                continue
            for v, d in vs:
                p = _abs(v, ctx)
                if d or p is None:
                    ctx.unsure()
                elif _DEVICE.match(p) or p.startswith("/dev/"):
                    ctx.block(R_DISK)
                elif name in ("shred", "wipe", "scrub"):
                    r = _protected_path(p)
                    if r or _in_boot(p):
                        ctx.block(r or R_BOOT)
        if name == "blkdiscard":
            ctx.block(R_DISK)
        return True
    if name in _PART_TOOLS:
        if name == "parted":
            if any(a.lower() in _PARTED_WRITE for a in args) or not any(a in ("-l", "--list", "print")
                                                                        for a in args):
                ctx.block(R_DISK)
            return False
        opts = [a for a in args if a.startswith("-")]
        if name in ("partx", "kpartx", "delpart", "resizepart", "addpart"):
            if name in ("delpart", "resizepart", "addpart") or any(o in ("-d", "--delete", "-a", "--add", "-u",
                                                                          "--update") for o in opts):
                ctx.block(R_DISK)
            return False
        if not opts or any(o not in _PART_RO and not o.startswith("--list") for o in opts):
            ctx.block(R_DISK)
        return False
    if name == "cryptsetup" and any(a in ("luksFormat", "erase", "luksErase", "reencrypt", "luksKillSlot",
                                          "luksRemoveKey", "format", "tcryptDump") for a in args):
        ctx.block(R_DISK)
    if name == "nvme" and any(a in ("format", "sanitize", "delete-ns", "detach-ns", "write-zeroes", "write")
                              for a in args):
        ctx.block(R_DISK)
    if name == "hdparm" and any(a.startswith(("--security-erase", "--trim-sector-ranges", "--write-sector",
                                              "--make-bad-sector", "--dco-restore", "--security-set-pass",
                                              "--fwdownload")) for a in args):
        ctx.block(R_DISK)
    if name in ("zpool", "zfs") and any(a in ("destroy", "labelclear", "create") for a in args):
        ctx.block(R_DISK)
    if name in ("lvremove", "vgremove", "pvremove", "pvcreate", "vgcreate", "lvcreate") or \
            name == "mdadm" and any(a.startswith("--zero-superblock") or a == "--create" for a in args) or \
            name == "dmsetup" and any(a in ("remove_all", "wipe_table") for a in args) or \
            name == "flashrom" and any(a in ("-w", "--write", "-E", "--erase") for a in args):
        ctx.block(R_DISK)
    if name in _DEV_WRITERS and name != "dd":
        for v in flat_args:
            if _DEVICE.match(v):
                if name in ("cat", "pv", "xz", "gzip", "zstd", "bzip2", "tar", "unzip"):
                    continue    # cteni z disku (zapis by byl presmerovanim, viz vyse)
                ctx.block(R_DISK)
    # --- ucty, sudoers
    if name in _ACCOUNT_CMDS:
        if name in ("pwck", "grpck") and ("r" in shorts or "--read-only" in longs):
            return False
        if name == "faillock" and "--reset" not in longs:
            return False
        ctx.block(R_ACCOUNTS)
    if name == "passwd":
        opts = {a for a in args if a.startswith("-")}
        if opts & {"-S", "--status"} and opts <= {"-S", "--status", "-a", "--all"}:
            return False    # jen stav uctu
        ctx.block(R_ACCOUNTS)
    if name == "chage" and not ({"l"} & set(shorts) or "--list" in longs):
        ctx.block(R_ACCOUNTS)
    if name == "visudo":
        if "c" in shorts or "--check" in longs:
            return False
        ctx.block(R_AUTH)
    if name in ("sudoedit", "pam-auth-update", "authselect"):
        ctx.block(R_AUTH)
    # --- balicky, zavadec
    if name in _PKG_TOOLS:
        removing = any(re.match(r"^-[A-Za-z]*R", a) for a in args) or "--remove" in longs or \
            name in ("lux", "pamac") and args[:1] and args[0] in ("remove", "uninstall", "rm", "purge")
        if removing:
            for v in flat_args:
                if not v.startswith("-") and (v in _CORE_PKGS or re.match(r"^linux(-[a-z0-9]+)*$", v)):
                    ctx.block(R_BOOT)
            if dyn_args:
                ctx.unsure()
        if any(a in ("--dbonly",) for a in args) and removing:
            ctx.block(R_BOOT)
    if name == "efibootmgr" and ("B" in shorts or "--delete-bootnum" in longs or "--delete" in longs):
        ctx.block(R_BOOT)
    if name == "bootctl" and any(a in ("remove", "unlink", "cleanup") for a in args):
        ctx.block(R_BOOT)
    if name in ("makepkg", "pacman", "yay", "paru") and any(a in ("--skippgpcheck", "--skipchecksums",
                                                                  "--skipinteg", "--nosign") for a in args):
        ctx.block(R_SIGNATURES)
    if name == "pacman-key" and any(a in ("--delete", "-d", "--edit-key") for a in args):
        ctx.block(R_SIGNATURES)
    # --- zapis do chranenych souboru (tee, cp, sed -i, ln, install, truncate, chmod ...)
    readonly = name in _READONLY
    if name == "find" or name == "sort" and ("o" in shorts or "--output" in longs):
        readonly = False
    if name == "systemctl" and not (args[:1] and args[0] in ("status", "cat", "show", "is-active", "is-enabled",
                                                              "list-units", "list-unit-files", "list-timers",
                                                              "is-failed", "--failed")):
        readonly = False
    if name == "mount" and args:
        readonly = False
    if not readonly:
        for v, d in [x for _a, vs in vals for x in vs]:
            p = _abs(v, ctx) if "/" in v or v.startswith("~") else None
            if p:
                r = _protected_path(p)
                if r:
                    ctx.block(r)
    return not readonly or writes


def _check_redirects(wr, ctx):
    """Zapis presmerovanim (> soubor). Vraci True, pokud nejaky je (mimo /dev/null)."""
    any_write = False
    for t in wr:
        for v, d in _values(t, ctx):
            if v in ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty") or re.match(r"^&?\d+$", v):
                continue
            any_write = True
            p = _abs(v, ctx)
            if d or p is None:
                continue
            if _DEVICE.match(p):
                ctx.block(R_DISK)
            if p.startswith("/proc/sysrq"):
                ctx.block(R_KERNEL)
            r = _protected_path(p)
            if r:
                ctx.block(r)
            if _in_boot(p) and re.search(r"(vmlinuz|initramfs|\.efi$|/EFI/|loader/|grub)", p, re.I):
                ctx.block(R_BOOT)
    return any_write


def _interpreter(name, args, sep, rd, ctx):
    """python -c, perl -e ... : retezce v kodu se zkontroluji jako prikazy shellu."""
    code = None
    for i, a in enumerate(args):
        if a in ("-c", "-e", "-E", "-r", "--eval", "-p") or re.match(r"^-[a-zA-Z]*[ceE]$", a):
            if i + 1 < len(args):
                code = args[i + 1]
            break
    base = re.sub(r"[\d.]+$", "", name)
    if code is None:
        script = next((a for a in args if not a.startswith("-")), None)
        if base in ("awk", "gawk", "mawk", "nawk"):
            code = script
        elif script is None or script == "-":
            if sep in ("|", "|&") or rd:
                ctx.unsure(R_DYNAMIC)
            return
        else:
            code = _interp_file(script, ctx)     # python3 skript.py: obsah skriptu stejne jako -c
    if code is None:
        return
    for lit in re.findall(r"\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'", code):
        s = lit[0] or lit[1]
        if s and re.search(r"\s", s):
            _analyze(s, ctx)
    if ctx.root:
        flat = _dequote(code)
        if re.search(r"rmtree|unlink|remove|rmdir|truncate|system|popen|exec|spawn|subprocess|open\s*\(", flat):
            for p in re.findall(r"(?<![\w.])(/[\w./-]*)", flat):
                q = os.path.normpath(re.sub(r"/{2,}", "/", p)) if p != "/" else "/"
                if q == "/" or _protected_dir(q, ctx) or _protected_path(q) or _in_boot(q) or _DEVICE.match(q):
                    ctx.block(R_DYNAMIC)


def _interp_file(script, ctx):
    """Obsah skriptu interpretu (python3 oprava.py) pro kontrolu jako kod z -c; jen u roota."""
    if not ctx.root:
        return None
    for v, d in _values(script, ctx):
        p = _abs(v, ctx)
        if d or p is None:
            ctx.unsure(R_DYNAMIC)
            return None
        try:
            if not os.path.isfile(p):
                return None
            if os.path.getsize(p) > _MAX_SCRIPT:
                ctx.unsure(R_DYNAMIC)
                return None
            with open(p, "rb") as f:
                data = f.read(_MAX_SCRIPT + 1)
        except OSError:
            return None
        if b"\x00" in data[:8192]:
            ctx.unsure(R_DYNAMIC)        # zkompilovany soubor (.pyc ...) nelze zkontrolovat
            return None
        return data.decode("utf-8", "replace")
    return None


# ==== Lux Guard: kontroly navic k prevzate analyze prikazu =======================================
_DOC_EXT = {"jpg", "jpeg", "png", "gif", "heic", "webp", "raw", "cr2", "nef", "dng", "pdf", "doc", "docx", "odt",
            "ods", "odp", "xls", "xlsx", "ppt", "pptx", "txt", "md", "rtf", "csv", "mp3", "mp4", "mkv", "mov", "avi",
            "wav", "flac", "ogg", "zip", "7z", "rar", "tar", "gz", "kdbx", "sql", "psd", "svg", "epub", "json"}


def _doc_filters_only(args):
    """find jen s -name/-iname maskami na dokumenty ('*', '*.*', '*.jpg' ...) a -type - jako bez filtru."""
    names, other = [], False
    for i, a in enumerate(args):
        if a in ("-name", "-iname"):
            if i + 1 < len(args):
                names.append(args[i + 1].lower())
        elif a in _FIND_FILTERS:
            other = True
    if other or not names:
        return False
    for n in names:
        if n in ("*", "*.*"):
            continue
        m = re.match(r"^\*\.([a-z0-9]+)$", n)
        if not (m and m.group(1) in _DOC_EXT):
            return False
    return True


_GUARD_OFF = re.compile(r"\b(?:systemctl|service)\b[^\n;|&]*\b(?:stop|disable|mask|kill)\b[^\n;|&]*luxos-guard|"
                        r"\b(?:pkill|killall|kill)\b[^\n;|&]*luxos-guard|"
                        r"\bbtrfs\s+(?:subvolume|subvol|sub|su)\s+(?:delete|del|d)\b[^\n;|&]*(?:/home|snapshot)", re.I)
_RUN_REMOTE = (
    re.compile(r"\b(?:curl|wget|fetch|aria2c|xh)\b[^|;&\n]*\|\s*(?:\S*/)?(?:env\s+(?:-\S+\s+)*)?"
               r"(?:(?:sudo|doas|pkexec|run0)\s+(?:-\S+\s+)*)?(?:ba|z|da|k|fi|c|tc)?sh\b(?!\s+-c)"),
    re.compile(r"\b(?:curl|wget|fetch|aria2c)\b[^|;&\n]*\|\s*(?:(?:sudo|doas|pkexec|run0)\s+(?:-\S+\s+)*)?(?:\S*/)?"
               r"(?:python\d*(?:\.\d+)?|perl|ruby|node|php)\b"),
    re.compile(r"(?:\beval|\b(?:ba|z|da|k)?sh\s+(?:-\w+\s+)*-c|\bsource|(?:^|\s)\.)\s+[\"']?(?:\$\(|<\(|`)\s*"
               r"(?:curl|wget|fetch)\b"),
    re.compile(r"\b(?:ba|z|da|k)?sh\s+(?:-\w+\s+)*<\(\s*(?:curl|wget|fetch)\b"),
)
_INSECURE_URL = re.compile(r"\bhttp://|\bhttps?://\d{1,3}(?:\.\d{1,3}){3}|\bhttps?://\[[0-9a-f:]+\]|pastebin\.|"
                           r"\bpaste\.|transfer\.sh|bit\.ly/|tinyurl\.|is\.gd/|cutt\.ly/|ngrok|cdn\.discordapp\.com|"
                           r"\.onion\b|termbin\.com|0x0\.st|file\.io/", re.I)
_ROOT_WORD = re.compile(r"(?:^|[\s;&|(`\"']|\$\()(?:sudo|doas|pkexec|run0|su)(?=\s|$)")
_DECODE = re.compile(r"\bbase(?:64|32)\s+(?:-\w+\s+)*(?:-d|--decode|-D)\b|\bxxd\s+(?:-\w+\s+)*-r|"
                     r"\bopenssl\s+(?:enc\s+)?(?:-\w+\s+)*-(?:d|a\s+-d)\b|"
                     r"printf\s+[\"']?(?:\\x[0-9a-f]{2}){4,}")
_TO_SHELL = re.compile(r"\|\s*(?:\S*/)?(?:env\s+(?:-\S+\s+)*)?(?:(?:sudo|doas|pkexec|nohup|exec)\s+(?:-\S+\s+)*)?"
                       r"(?:ba|z|da|k|fi|c|tc|busybox\s+)?sh\b|\|\s*(?:\S*/)?(?:python\d*(?:\.\d+)?|perl|ruby|node|php)\b|"
                       r"\beval\b|\b(?:ba|z|da|k)?sh\s+(?:-\w+\s+)*-c\s*[\"']?\$\(|\b(?:source|\.)\s+<\(|"
                       r"\b(?:ba|z|da|k)?sh\s+(?:-\w+\s+)*<\(")
_AUTOSTART = re.compile(r"\.config/autostart|systemctl\s+--user\s+enable|\bcrontab\b|/etc/cron|"
                        r">>?\s*\S*(?:\.bashrc|\.zshrc|\.profile|\.bash_profile|\.xprofile|\.xinitrc)\b")
_ENCRYPT = re.compile(r"\bopenssl\s+(?:enc\b|aes|-aes|des|chacha|rsautl|pkeyutl)|"
                      r"\bgpg2?\b[^\n|;&]*\s(?:-c|--symmetric|-e|--encrypt)\b|"
                      r"\bage\s+(?:-\w+\s+)*(?:-p|-r|--passphrase|--recipient)\b|\bccrypt\b|\bmcrypt\b|\baescrypt\b|"
                      r"\b7za?\s+a\b[^\n]*\s-p|\bzip\b[^\n]*\s(?:-e|-P)\b")
_MASS = re.compile(r"\bfind\s+(?:-\w+\s+)*[\"']?(?:~|\$\{?HOME\}?|/home|/media|/run/media|/mnt|/)(?:[\"'\s/]|$)|"
                   r"\bfor\s+\w+\s+in\s+[^;\n]*(?:~|\$\{?HOME\}?|/home|\*\*|\$\(\s*find)|"
                   r"\$\(\s*find\s+(?:~|\$\{?HOME\}?|/)|\bfind\s+(?:~|\$\{?HOME\}?|/home|/)[^\n]*\|\s*(?:xargs|while)\b|"
                   r"\bshopt\s+-s\s+globstar", re.I)
_REMOVE = re.compile(r"\b(?:rm|shred|unlink|truncate)\b|>\s*\"?\$")


def _guard_text_checks(text, flat, ctx):
    """Kontroly celeho textu navic k rootguard: vypnuti Lux Guard, stazeni a spusteni kodu, skryty kod,
    sifrovani souboru ve smycce; poznamky (sudo, automaticke spousteni)."""
    flow = flat.lower()
    if _GUARD_OFF.search(text) or _GUARD_OFF.search(flat):
        ctx.block(R_GUARD)
    for src in (text, flat):
        for line in src.splitlines():
            low = line.lower()
            if any(r.search(low) for r in _RUN_REMOTE):
                if _ROOT_WORD.search(low) or _INSECURE_URL.search(low) or _DECODE.search(low):
                    ctx.block(R_REMOTE)
                ctx.block(N_REMOTE)
            if _DECODE.search(low) and _TO_SHELL.search(low):
                ctx.block(R_HIDDEN)
    if _MASS.search(flow) and (_REMOVE.search(flow) or "home" in flow or "~" in flow):
        for line in flow.splitlines():
            m = _ENCRYPT.search(line)
            # sifruje se polozka smycky ("$f", {} z find -exec), ne jeden pojmenovany soubor
            if m and re.search(r"\$\{?\w+\}?|\{\}", line[m.start():]):
                ctx.block(R_RANSOM)
    if _ROOT_WORD.search(flow):
        ctx.block(N_ROOT)
    if _AUTOSTART.search(flow):
        ctx.block(N_AUTOSTART)


# ---- skryty obsah (base64 v textu) --------------------------------------------------------------
_B64 = re.compile(r"[A-Za-z0-9+/]{24,262144}={0,2}")


def decoded_payloads(text, limit=16, max_total=262144):
    """Texty zakodovane v base64 uvnitr skriptu (jen citelny text) - analyzuji se taky."""
    out, total = [], 0
    for m in _B64.finditer(text):
        s = m.group(0)
        s += "=" * (-len(s) % 4)
        try:
            raw = base64.b64decode(s, validate=True)
        except (binascii.Error, ValueError):
            continue
        try:
            dec = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not dec or sum(c.isprintable() or c in "\n\t\r" for c in dec) < 0.95 * len(dec):
            continue
        if not re.search(r"\s", dec):
            continue
        out.append(dec)
        total += len(dec)
        if len(out) >= limit or total >= max_total:
            break
    return out


# ---- jine jazyky (python, perl, ruby, node, php ...) -------------------------------------------
_Q = "[\"']"
# Cely domov (ne podslozka): os.path.expanduser("~"), Path.home(), os.environ["HOME"], "/", "/home" ...
_HOME_ROOT = re.compile(
    r"(?:os\.path\.)?expanduser\(\s*[\"']~/?(?:\*{1,2}(?:/\*{1,2})?)?[\"']\s*\)|(?:pathlib\.)?Path\.home\(\)|"
    r"(?:pathlib\.)?Path\(\s*[\"']~/?[\"']\s*\)\.expanduser\(\)|(?:os\.)?environ(?:\.get)?\s*[\[\(]\s*[\"']HOME[\"']\s*[\]\)]|"
    r"(?:os\.)?getenv\(\s*[\"']HOME[\"']\s*\)|\$ENV\{\s*[\"']?HOME[\"']?\s*\}|[\"']\$ENV\{HOME\}/?[\"']|"
    r"ENV\[\s*[\"']HOME[\"']\s*\]|(?:os\.|require\([\"']os[\"']\)\.)?homedir\(\)|Dir\.home|"
    r"File\.expand_path\(\s*[\"']~/?[\"']\s*\)|process\.env\.HOME|os\.getenv\(\s*[\"']HOME[\"']\s*\)|"
    r"[\"'](?:~|/|/home|/home/[\w.-]+|/root|\$HOME|/media|/run/media|/mnt)/?(?:\*{1,2}(?:/\*{1,2})?)?[\"']|"
    r"(?:str|Path|String)\(\s*(?:Path\.home\(\)|(?:os\.path\.)?expanduser\(\s*[\"']~/?[\"']\s*\))\s*\)")
_RDEL = re.compile(r"rmtree|remove_tree|rm_rf\b|rm_r\b|rmSync|rimraf|rmdirSync|FileUtils\.rm|fs\.rm\b|"
                   r"fs\.promises\.rm\b|deleteRecursively|Remove-Item|delete_tree|rmdir\s*\([^)]*recursive")
_WALK = re.compile(r"os\.walk\(|\.rglob\(|glob\.i?glob\(|os\.scandir\(|os\.listdir\(|File::Find|(?<![\w.])find\s*\(|"
                   r"readdirSync\(|readdir\(|walkdir|Dir\.glob\(|Dir\[|Find\.find\(|opendir\(|\.walk\(|iterdir\(")
_DESTROY = re.compile(r"os\.remove\(|os\.unlink\(|\.unlink\(|unlinkSync\(|\bunlink\b|File\.delete|FileUtils\.rm|"
                      r"truncate|open\([^)\n]*[\"'](?:w|wb|w\+|wb\+|r\+b?|a)[\"']|write_bytes\(|write_text\(|"
                      r"writeFileSync\(|\bshred\b|os\.rename\(|\.rename\(|os\.replace\(")
_ENC_API = re.compile(r"Fernet|AES\.new|\bAES\b|Cipher\(|ChaCha20|createCipheriv|Crypt::|cryptography\.|Crypto\.Cipher|"
                      r"pyAesCrypt|openssl_encrypt|\.encrypt\(")
_HIDDEN_CODE = re.compile(
    r"\b(?:exec|eval)\s*\(\s*(?:compile\(\s*)?(?:base64|zlib|marshal|codecs|bz2|lzma|binascii|bytes\.fromhex|"
    r"__import__\(\s*[\"'](?:base64|zlib|marshal|codecs|bz2|lzma|binascii))|"
    r"\beval\s*\(\s*(?:atob|Buffer\.from\([^)]*[\"']base64|unescape|String\.fromCharCode)|"
    r"\beval\s*\(?\s*(?:decode_base64|MIME::Base64|pack\s*\(?\s*[\"']H|unpack)|"
    r"\beval\s*\(\s*(?:base64_decode|gzinflate|str_rot13|gzuncompress)|\beval\s*\(?\s*(?:Base64|Zlib)")
_DECODE_CALL = re.compile(r"b64decode|b32decode|decompress|fromhex|marshal\.loads|decode_base64|base64_decode|atob\(|"
                          r"Buffer\.from\([^)]*base64|unhexlify|gzinflate")
_FETCH_CALL = re.compile(r"urlopen|requests\.get|requests\.post|urllib|http\.get|https\.get|fetch\(|LWP::|"
                         r"HTTP::Tiny|Net::HTTP|open-uri|URI\.open|file_get_contents\(\s*[\"']https?|httpx\.")
_RUN_CODE = re.compile(r"(?<![\w.])(?:exec|eval)\s*\(|(?<![\w.])eval\s+|\bnew\s+Function\(|\binstance_eval\b")
_PROC_API = re.compile(r"\bsystem\s*\(|\bpopen|subprocess|\bspawn|\bexecSync|\bexec[lv]?p?e?\s*\(|shell_exec|"
                       r"passthru|`[^`\n]+`|\bqx\s*[\(\{/]|Runtime\.getRuntime|child_process|os\.execute|io\.popen|"
                       r"\bsystem\s+[\"'\[]")
# Retezec v kodu, ktery vypada jako prikaz shellu (ne veta v hlaseni "visudo not found ...")
_CMD_START = re.compile(r"^\s*(?:(?:sudo|doas|pkexec|nohup|exec)\s+(?:-\S+\s+)*)?(?:\S*/)?(?:rm|dd|mkfs[.\w]*|wipefs|shred|"
                        r"blkdiscard|find|chmod|chown|mv|cp|tee|truncate|curl|wget|bash|sh|zsh|dash|systemctl|btrfs|"
                        r"cat|echo|printf|base64|eval|xargs|parted|fdisk|sgdisk|cryptsetup|userdel|usermod|passwd)\s")
_STR_LIT = re.compile(r"\"((?:[^\"\\\n]|\\.){3,2000})\"|'((?:[^'\\\n]|\\.){3,2000})'")
_LIST_LIT = re.compile(r"\[\s*((?:[\"'][^\"'\n]{1,200}[\"']\s*,\s*){1,20}[\"'][^\"'\n]{1,200}[\"'])\s*,?\s*\]")
_DEV_LIT = re.compile(r"[\"']/dev/(?:sd[a-z]|nvme\d|mmcblk\d|vd[a-z]|hd[a-z]|xvd[a-z]|mapper/|disk/)")
_DEV_WRITE = re.compile(r"\bopen\(|os\.open\(|fopen\(|File\.open\(|File\.write\(|fs\.open|writeFileSync\(|sysopen|"
                        r"\bdd\b|\bopen\s*\(?\s*my\b|\bopen\s+\w+\s*,")
_ASSIGN_LINE = re.compile(r"(?m)^\s*(?:my\s+|our\s+|local\s+|let\s+|const\s+|var\s+)?[\$@]?(\w+)\s*(?::\s*\w+\s*)?=(?!=)"
                          r"\s*(.+)$")


def _bound_names(text, pattern, full=False):
    """Jmena promennych, do kterych se prirazuje vyraz odpovidajici pattern. full=True: cela prava
    strana musi odpovidat (home = Path.home(), ne cache = home / ".cache"); prirazeni jineho takoveho
    jmena (h = home, h = str(home)) se pocita taky."""
    names = set()

    def rhs_ok(rhs):
        rhs = rhs.strip().rstrip(";").strip()
        alias = any(re.fullmatch(r"(?:str|Path|String|bytes)?\(?\s*\$?" + re.escape(n) +
                                 r"(?:\.\w+(?:\(\))?)*\s*\)?", rhs) for n in names)
        if full:
            return bool(pattern.fullmatch(rhs)) or alias
        return bool(pattern.search(rhs)) or alias
    assigns = [(m.group(1), m.group(2)) for m in _ASSIGN_LINE.finditer(text)][:5000]
    for _ in range(3):
        before = len(names)
        for name, rhs in assigns:
            if name not in names and rhs_ok(rhs):
                names.add(name)
                if len(names) >= 200:
                    return names
        if len(names) == before:
            break
    return names


_NAMES_RX = {}


def _mentions_names(line, names):
    """Radek obsahuje nektere z jmen (jeden spojeny regularni vyraz - i pro stovky jmen rychle)."""
    if not names:
        return False
    key = frozenset(names)
    rx = _NAMES_RX.get(key)
    if rx is None:
        if len(_NAMES_RX) > 64:
            _NAMES_RX.clear()
        rx = re.compile(r"(?<![\w.])[\$@]?(?:" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
                        + r")\b")
        _NAMES_RX[key] = rx
    return bool(rx.search(line))


def _first_arg(line, start):
    """Prvni argument volani: text od '(' na pozici >= start po ',' nebo ')' v nulte hloubce."""
    i = line.find("(", start)
    if i < 0:
        return None
    depth, j, q = 0, i + 1, None
    while j < len(line):
        c = line[j]
        if q:
            if c == "\\":
                j += 2
                continue
            if c == q:
                q = None
        elif c in "\"'":
            q = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return line[i + 1:j].strip()
            depth -= 1
        elif c == "," and depth == 0:
            return line[i + 1:j].strip()
        j += 1
    return line[i + 1:].strip()


# Domov vlozeny do retezce: "rm -rf $ENV{HOME}", "#{Dir.home}", `${os.homedir()}`
_HOME_INTERP = re.compile(r"\$ENV\{\s*[\"']?HOME[\"']?\s*\}|#\{\s*(?:Dir\.home|ENV\[[\"']HOME[\"']\])\s*\}|"
                          r"\$\{\s*(?:os\.homedir\(\)|process\.env\.HOME)\s*\}")
_RM_LIST = re.compile(r"[\"']rm[\"']\s*,\s*[\"']-[a-zA-Z]*[rR][a-zA-Z]*[\"']\s*,\s*([^\],]+?)\s*[\],]")
_RECV_WALK = re.compile(r"((?:pathlib\.)?Path\.home\(\)|\w+)\.(?:rglob|glob|iterdir|walk)\(")
_GLOB_SUFFIX = re.compile(r"\s*\+\s*[\"']/?\*{0,2}(?:/\*{0,2})?(?:\.\*)?[\"']$")


def _is_home_arg(arg, homes):
    if not arg:
        return False
    a = arg.strip()
    a = _GLOB_SUFFIX.sub("", a)
    m = re.fullmatch(r"f[\"']\{(\w+)\}/?\*{0,2}(?:/\*{0,2})?[\"']", a)
    if m:
        a = m.group(1)
    m = re.fullmatch(r"(?:os\.path\.join|path\.join|File\.join)\(\s*(.+?)\s*,\s*[\"']\*{1,2}[\"']\s*\)", a)
    if m:
        a = m.group(1)
    a = re.sub(r"^(?:str|Path|String|os\.fspath)\(\s*(.*?)\s*\)$", r"\1", a)
    return bool(_HOME_ROOT.fullmatch(a)) or a.lstrip("$@") in homes


_WIPE_API = re.compile(r"os\.remove\(|os\.unlink\(|\.unlink\(|unlinkSync\(|\bunlink\b|File\.delete|truncate|"
                       r"\bshred\b|write_bytes\(|open\([^)\n]*[\"']wb?[\"']|rmtree|rmSync|rm_rf")


def _loop_body(lines, i, limit=80):
    """Radek s cyklem a jeho telo (odsazene radky pod nim, nejvyse limit)."""
    first = lines[i]
    indent = len(first) - len(first.lstrip())
    body = [first]
    for line in lines[i + 1:i + 1 + limit]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return "\n".join(body)


def analyze_code(text, home=HOME):
    """Skript v pythonu/perlu/ruby/node/php -> (kriticke duvody, poznamky)."""
    text = _clip(str(text or "")[:MAX_SCRIPT])
    ctx = _Ctx(False, None, home)
    try:
        flat = _dequote(text)
        for r in _FORK:
            if r.search(text):
                ctx.block(R_FORK)
        if _HIDDEN_CODE.search(text):
            ctx.block(R_HIDDEN)
        decoded = _bound_names(text, _DECODE_CALL)
        fetched = _bound_names(text, _FETCH_CALL)
        homes = _bound_names(text, _HOME_ROOT, full=True)
        for line in text.splitlines():
            if _RUN_CODE.search(line) and not re.search(r"\beval\s*\(?\s*[\"'{]\s*(?:use|require)\s", line):
                if _DECODE_CALL.search(line) or _mentions_names(line, decoded):
                    ctx.block(R_HIDDEN)
                if _FETCH_CALL.search(line) or _mentions_names(line, fetched):
                    ctx.block(R_REMOTE)
            m = _RDEL.search(line)
            if m:
                arg = _first_arg(line, m.end())
                if arg is None or "(" not in line[m.end():m.end() + 12]:
                    arg = re.split(r"[;,]|\bor\b|\|\|", line[m.end():].strip())[0]
                if _is_home_arg(arg, homes):
                    ctx.block(R_DELETE)
            m = _RM_LIST.search(line)
            if m and _PROC_API.search(line) and _is_home_arg(m.group(1), homes):
                ctx.block(R_DELETE)
            if _DEV_LIT.search(line) and _DEV_WRITE.search(line) and not re.search(r"[\"']rb?[\"']", line):
                ctx.block(R_DISK)
        # prochazeni celeho domova a v tele smycky mazani/prepis (sifrovani) souboru
        lines = text.splitlines()
        for i, line in enumerate(lines):
            m = _WALK.search(line)
            hit = bool(m and _is_home_arg(_first_arg(line, m.start()), homes))
            m = _RECV_WALK.search(line)
            hit = hit or bool(m and (_HOME_ROOT.fullmatch(m.group(1)) or m.group(1) in homes))
            if not hit:
                continue
            body = _loop_body(lines, i)
            if _ENC_API.search(body) and _DESTROY.search(body):
                ctx.block(R_RANSOM)
            if _WIPE_API.search(body):
                ctx.block(R_DELETE)
        # retezce predavane shellu: os.system("rm -rf ~"), subprocess.run(["rm", "-rf", home]) ...
        if _PROC_API.search(text):
            text = _HOME_INTERP.sub("$HOME", text)
            for m in _LIST_LIT.finditer(text):
                parts = re.findall(r"[\"']([^\"'\n]*)[\"']", m.group(1))
                _analyze(" ".join(shlex.quote(p) if p and not re.search(r"[~$*]", p) else p for p in parts), ctx)
            for m in _STR_LIT.finditer(text):
                s = m.group(1) if m.group(1) is not None else m.group(2)
                if s and re.search(r"\s", s) and _CMD_START.match(s):
                    _analyze(s.replace("\\n", "\n"), ctx)
            for m in re.finditer(r"`([^`\n]+)`", text):
                _analyze(m.group(1), ctx)
        else:
            _text_checks(flat, ctx)
    except _Found:
        pass
    except RecursionError:
        pass
    return _split(ctx.found)


# ---- programy (ELF): prikazy ulozene v textovych retezcich -----------------------------------------
_ELF_HINT = re.compile(rb"rm\s+-[a-zA-Z-]*[rRf]|\bdd\s+[^\x00\n]{0,80}of=/dev/|mkfs[.\w]*\s+[^\x00\n]{0,40}/dev/|"
                       rb"wipefs\s+-|blkdiscard\s|shred\s+[^\x00\n]{0,40}/dev/|:\(\)\s*\{|"
                       rb"find\s+[~/$][^\x00\n]{0,80}-delete|chmod\s+-R\s|\|\s*(?:sudo\s+)?(?:ba)?sh\b|"
                       rb"systemctl\s+(?:stop|disable|mask)\s+luxos-guard")


_USAGE = re.compile(r"usage|example|e\.g\.|synopsis|options|--help|\[-|<device>|%s", re.I)


def analyze_binary(data, limit=200, name=""):
    """Textove retezce v programu, ktere vypadaji jako prikazy shellu -> kriticke duvody. Zakodovany
    nebo zkomprimovany obsah (AppImage, UPX) tim videt neni - takovy program je jen rizikovy."""
    crit = []
    n = 0
    for m in _ELF_HINT.finditer(data):
        n += 1
        if n > limit:
            break
        a = m.start()
        lo = a
        while lo > 0 and a - lo < 400 and 0x20 <= data[lo - 1] <= 0x7e:
            lo -= 1
        hi = m.end()
        while hi < len(data) and hi - a < 800 and (0x20 <= data[hi] <= 0x7e or data[hi] == 0x09):
            hi += 1
        s = data[lo:hi].decode("ascii", "replace")
        first = s.strip().split(" ", 1)[0]
        if _USAGE.search(s) or name and os.path.basename(first) == name:
            continue        # napoveda programu (mkfs.ubifs /dev/ubi0_0), ne prikaz
        c, _notes = analyze_shell(s)
        for r in c:
            if r in (R_DELETE, R_DISK, R_FORK, R_BOOT, R_GUARD, R_REMOTE, R_HIDDEN, R_RANSOM) and r not in crit:
                crit.append(r)
    return crit


# ---- druh souboru a celkove hodnoceni -----------------------------------------------------------------
SHELLS = {"sh", "bash", "dash", "zsh", "ksh", "mksh", "ash", "fish", "csh", "tcsh", "rbash", "busybox", "yash", "oksh",
          "lsh"}
_EXT_INTERP = {".sh": "sh", ".bash": "bash", ".zsh": "zsh", ".ksh": "ksh", ".command": "sh", ".run": "sh",
               ".py": "python3", ".pyw": "python3", ".pl": "perl", ".rb": "ruby", ".lsl": "lsl"}


class Verdict:
    __slots__ = ("kind", "interp", "reasons", "notes")

    def __init__(self, kind, interp=None, reasons=(), notes=()):
        self.kind = kind
        self.interp = interp
        self.reasons = list(reasons)
        self.notes = list(notes)

    @property
    def critical(self):
        return bool(self.reasons)

    def as_dict(self):
        return {"kind": self.kind, "interp": self.interp, "reasons": self.reasons, "notes": self.notes}

    def __repr__(self):
        return f"Verdict({self.kind!r}, {self.interp!r}, reasons={self.reasons!r}, notes={self.notes!r})"


def shebang_interp(line):
    """'#!/usr/bin/env -S python3 -u' -> 'python3'; '#!/bin/bash -e' -> 'bash'."""
    try:
        parts = line[2:].strip().split()
    except AttributeError:
        return None
    if not parts:
        return None
    prog = os.path.basename(parts[0])
    if prog == "env":
        rest = [p for p in parts[1:] if not p.startswith("-") and "=" not in p]
        prog = os.path.basename(rest[0]) if rest else "env"
    return prog


def interp_family(interp):
    """sh | python | perl | ruby | node | php | other"""
    base = re.sub(r"[\d.]+$", "", interp or "")
    if base in SHELLS:
        return "sh"
    if base in ("python", "pypy"):
        return "python"
    if base in ("perl", "ruby", "php", "lua", "luajit"):
        return base
    if base in ("node", "nodejs", "bun", "deno"):
        return "node"
    return "other"


def detect_kind(head, name):
    """Druh spustitelneho obsahu podle zacatku souboru (staci 64 B) a pripony; None = nehlidat.
    Vraci (druh, interpret)."""
    low = (name or "").lower()
    if head[:4] == b"\x7fELF":
        if len(head) >= 18:
            etype = int.from_bytes(head[16:18], "little" if head[5:6] != b"\x02" else "big")
            if etype not in (2, 3):
                return None                 # .o, core
        if head[8:11] in (b"AI\x01", b"AI\x02"):
            return ("appimage", None)
        if re.search(r"\.so(\.\d+)*$", low):
            return None                     # knihovna (spousti se jen jako soucast programu)
        return ("elf", None)
    if head[:2] == b"#!":
        line = head.split(b"\n", 1)[0].decode("utf-8", "replace")
        return ("script", shebang_interp(line) or "sh")
    if low.endswith(".desktop"):
        return ("desktop", None)
    if low.endswith(".jar") and head[:2] == b"PK":
        return ("jar", "java")
    if head[:2] == b"MZ" and low.endswith((".exe", ".scr", ".com", ".pif")):
        return ("windows", "wine")
    for ext, interp in _EXT_INTERP.items():
        if low.endswith(ext):
            if b"\x00" in head:
                return None
            return ("script", interp)
    return None


def _script_text(data):
    nul = data.find(b"\x00")
    if nul >= 0:
        data = data[:nul]           # samorozbalovaci skript: za textem jsou binarni data
    return data[:MAX_SCRIPT].decode("utf-8", "replace")


def _desktop_exec(text):
    out = []
    for line in text.splitlines():
        m = re.match(r"^\s*(?:Exec|TryExec)\s*=\s*(.*)$", line)
        if m:
            out.append(re.sub(r"%[fFuUdDnNickvm]", "", m.group(1)))
    return out


def _merge(dst_c, dst_n, c, n):
    for r in c:
        if r not in dst_c:
            dst_c.append(r)
    for r in n:
        if r not in dst_n:
            dst_n.append(r)


def classify(data, name=""):
    """Obsah souboru -> Verdict, nebo None (neni spustitelny obsah)."""
    kind = detect_kind(data[:64], name)
    if kind is None:
        return None
    kind, interp = kind
    crit, notes = [], []
    if kind in ("elf", "appimage"):
        crit = analyze_binary(data[:MAX_READ], name=os.path.basename(name or ""))
    elif kind == "script":
        text = _script_text(data)
        fam = interp_family(interp)
        if fam == "sh":
            _merge(crit, notes, *analyze_shell(text))
        else:
            _merge(crit, notes, *analyze_code(text))
        for payload in decoded_payloads(text):
            _merge(crit, notes, *analyze_shell(payload))
            _merge(crit, notes, *analyze_code(payload))
    elif kind == "desktop":
        text = _script_text(data)
        for cmd in _desktop_exec(text):
            _merge(crit, notes, *analyze_shell(cmd))
            for payload in decoded_payloads(cmd):
                _merge(crit, notes, *analyze_shell(payload))
    return Verdict(kind, interp, crit, notes)
