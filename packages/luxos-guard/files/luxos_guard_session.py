"""Lux Guard - akce v sezeni uzivatele (pomocnik i okno): upozorneni, spusteni v sandboxu, kos."""
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time

sys.path.insert(0, "/usr/lib/luxos/python")
try:
    from luxos_i18n import _  # noqa: E402
except ImportError:
    def _(text):
        return text

SANDBOX_CLI = os.environ.get("LUXOS_SANDBOX_CLI", "luxos-sandbox")
SANDBOX_BASE = "/var/lib/luxos/sandbox"


def notify(title, body, urgency="normal"):
    """Upozorneni na chvili (10 s, i "critical" - to by v Xfce nezmizelo samo) a bez zapisu do historie
    oznameni (-e): dulezite volby ma Lux Guard ve vlastnim okne a v luxos-guard log."""
    if urgency == "critical":
        urgency = "normal"
    try:
        subprocess.Popen(["notify-send", "-a", "Lux Guard", "-i", "luxos-guard", "-u", urgency, "-t", "10000", "-e",
                          title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def sandbox_exists():
    import pwd
    user = pwd.getpwuid(os.getuid()).pw_name
    return os.path.isdir(os.path.join(SANDBOX_BASE, user, "usr", "bin"))


# ---- jak soubor v sandboxu spustit: s oknem (Xephyr, --gui) a/nebo v terminalu ------------------------------
# Program s oknem nema otevirat terminal (driv kazdy skript a spoustec .desktop skoncil v terminalu, ktery
# po skonceni zustal otevreny); terminal jen pro textove programy a kdyz si ho uzivatel sam vybral.

MAX_INSPECT = 4 << 20           # cteni ELF pro rozhodnuti (hlavicky + dynamicka sekce)
MAX_ELF_SCAN = 32 << 20         # staticky ELF: hledani nazvu knihoven nacitanych pres dlopen
LAUNCH_FAIL_WINDOW = 20         # s: nenulovy konec drive = spusteni se nepovedlo (upozorneni)

# Knihovny oken a grafiky: program, ktery nekterou potrebuje (DT_NEEDED), ma vlastni okno
_GUI_LIB = re.compile(r"^lib(X11|X11-xcb|xcb|Xext|Xrender|Xrandr|Xi|Xcursor|Xinerama|Xt|Xm|Xaw\d*|SM|ICE"
                      r"|gtk-[34]|gtk-x11-2\.0|gtk-4|gdk-[34]|gdk-x11-2\.0"
                      r"|Qt\d*(Gui|Widgets|Quick|Qml|OpenGL|XcbQpa)|KF\d*\w*Widgets\w*"
                      r"|SDL|SDL2|SDL3|SDL-1\.2|SDL2-2\.0|glfw|glut|GL|GLX|OpenGL|GLU|wayland-client|wayland-egl"
                      r"|fltk\w*|wx_\w+|sfml-window|sfml-graphics|raylib|allegro\w*|webkit2gtk-\S+"
                      r"|electron|cef|xkbcommon-x11)(\.so|-)", re.I)
# Staticky program: okno jen pres dlopen - nazev knihovny okna v datech programu
_GUI_DLOPEN = re.compile(rb"lib(X11|xcb|wayland-client|gtk-[34]|SDL2-2\.0|SDL3|GL|EGL)\.so")

_PY_GUI = re.compile(r"^\s*(?:import|from)\s+(tkinter|Tkinter|PyQt[456]|PySide[26]?|wx|pygame|kivy|PySimpleGUI"
                     r"|customtkinter|pyglet|arcade|dearpygui|flet|toga|webview|eel)\b"
                     r"|gi\.require_version\(\s*['\"](Gtk|Gdk|Adw|Handy)['\"]"
                     r"|^\s*from\s+gi\.repository\s+import\s+.*\b(Gtk|Adw)\b", re.M)
# Cteni vstupu od uzivatele (otazka, heslo, nabidka): jen takovy program potrebuje terminal i bez
# spusteni z terminalu. Cteni dat z roury/souboru (while read ... < soubor, sys.stdin.read()) se nepocita.
_PY_INPUT = re.compile(r"\b(input|raw_input|getpass)\s*\(|\bsys\.stdin\.readline\b|\b(curses|termios)\b")
_SH_GUI = re.compile(r"(^|[\s;&|(`$])(zenity|yad|kdialog|Xdialog|gxmessage|xmessage|gdialog)\b", re.M)
_SH_INPUT = re.compile(r"(?:^|[;&{(]|\b(?:then|do|else|if|elif)\b)[ \t]*"
                       r"(?:read\b(?![^\n]*<[ \t]*[^\s<(&])|select\b|dialog\b|whiptail\b)|/dev/tty\b", re.M)
_PERL_GUI = re.compile(r"^\s*use\s+(Tk|Gtk[234]?|Wx|Prima|Qt)\b", re.M)
_PERL_INPUT = re.compile(r"<STDIN>|\bTerm::ReadLine\b")
_OTHER_INPUT = {"ruby": re.compile(r"(^|[\s=(;])(STDIN\.|\$stdin\.)?gets\b|\bSTDIN\.(read|getch)|\bio/console\b", re.M),
                "node": re.compile(r"\breadline\.createInterface\b|\bprocess\.stdin\b|\bprompt-sync\b|\binquirer\b"),
                "php": re.compile(r"\bfgets\s*\(\s*STDIN\b|\breadline\s*\("),
                "lua": re.compile(r"\bio\.read\s*\(|\bio\.stdin\b")}


def _read_head(path, size=MAX_INSPECT):
    """Zacatek souboru (jen bezny soubor, bez nasledovani odkazu); None = nelze precist."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except (OSError, TypeError, ValueError):
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        return os.pread(fd, size, 0)
    except OSError:
        return None
    finally:
        os.close(fd)


def elf_needed(data):
    """Knihovny DT_NEEDED z obsahu ELF (pres programove hlavicky - funguje i bez tabulky sekci).
    Vraci seznam; [] = staticky program (bez PT_DYNAMIC); None = poskozeny nebo necitelny ELF."""
    import struct
    try:
        if data[:4] != b"\x7fELF" or data[4] not in (1, 2) or data[5] not in (1, 2):
            return None
        b64 = data[4] == 2
        en = "<" if data[5] == 1 else ">"
        if b64:
            phoff, = struct.unpack_from(en + "Q", data, 0x20)
            phentsize, phnum = struct.unpack_from(en + "HH", data, 0x36)
        else:
            phoff, = struct.unpack_from(en + "I", data, 0x1C)
            phentsize, phnum = struct.unpack_from(en + "HH", data, 0x2A)
        if phnum > 512 or phentsize < (56 if b64 else 32):
            return None
        loads, dyn = [], None
        for i in range(phnum):
            o = phoff + i * phentsize
            if b64:
                ptype, _fl, off, vaddr, _pa, filesz = struct.unpack_from(en + "IIQQQQ", data, o)
            else:
                ptype, off, vaddr, _pa, filesz = struct.unpack_from(en + "IIIII", data, o)
            if ptype == 1:                      # PT_LOAD
                loads.append((vaddr, off, filesz))
            elif ptype == 2:                    # PT_DYNAMIC
                dyn = (off, filesz)
        if dyn is None:
            return []
        ent = 16 if b64 else 8
        fmt = en + ("qQ" if b64 else "iI")
        needed, strtab, strsz = [], None, None
        off, size = dyn
        for o in range(off, min(off + size, len(data) - ent + 1), ent):
            tag, val = struct.unpack_from(fmt, data, o)
            if tag == 0:                        # DT_NULL
                break
            if tag == 1:                        # DT_NEEDED
                needed.append(val)
            elif tag == 5:                      # DT_STRTAB
                strtab = val
            elif tag == 10:                     # DT_STRSZ
                strsz = val
        if strtab is None:
            return None
        base = None
        for vaddr, foff, filesz in loads:
            if vaddr <= strtab < vaddr + filesz:
                base = foff + (strtab - vaddr)
                break
        if base is None:
            return None
        out = []
        for n in needed[:256]:
            if strsz is not None and n >= strsz:
                continue
            s = base + n
            if s >= len(data):
                continue
            e = data.find(b"\0", s, s + 256)
            if e < 0:
                continue
            out.append(data[s:e].decode("ascii", "replace"))
        return out
    except (struct.error, IndexError, TypeError, ValueError, OverflowError):
        return None


def elf_is_gui(path):
    """Program ELF s oknem: linkuje knihovnu oken (X11/xcb/GTK/Qt/SDL/wayland ...), staticky ji nacita."""
    data = _read_head(path)
    if not data:
        return False
    libs = elf_needed(data)
    if libs is None:
        return False
    if any(_GUI_LIB.match(x) for x in libs):
        return True
    if not libs:
        return bool(_GUI_DLOPEN.search(_read_head(path, MAX_ELF_SCAN) or b""))
    return False


def _script_text(path, interp):
    """(textova cast skriptu, rodina interpretu); None = nelze precist."""
    import luxos_guard_rules as rules
    data = _read_head(path, 512 << 10)
    if not data:
        return None
    nul = data.find(b"\0")
    text = (data if nul < 0 else data[:nul]).decode("utf-8", "replace")
    if not interp and text.startswith("#!"):
        interp = rules.shebang_interp(text.split("\n", 1)[0])
    return text, rules.interp_family(interp)


def _text_reads_input(text, fam):
    rx = {"python": _PY_INPUT, "sh": _SH_INPUT, "perl": _PERL_INPUT}.get(fam) or _OTHER_INPUT.get(fam)
    return bool(rx and rx.search(text))


def script_is_gui(path, interp):
    """Skript s oknem (Tk/GTK/Qt/pygame, zenity/yad ...), ktery necte z terminalu."""
    st = _script_text(path, interp)
    if st is None:
        return False
    text, fam = st
    rx = {"python": _PY_GUI, "sh": _SH_GUI, "perl": _PERL_GUI}.get(fam)
    return bool(rx and rx.search(text)) and not _text_reads_input(text, fam)


def script_reads_input(path, interp):
    """Skript se zjevne pta uzivatele (read, input(), <STDIN> ...) - bez terminalu by dostal jen konec vstupu."""
    st = _script_text(path, interp)
    return st is not None and _text_reads_input(*st)


def _desktop_unescape(v):
    """Escapovani hodnot .desktop (\\s \\n \\t \\r \\\\); uvozovky pak resi shlex."""
    out, i = [], 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v) and v[i + 1] in "sntr":
            out.append({"s": " ", "n": "\n", "t": "\t", "r": "\r"}[v[i + 1]])
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def desktop_entry(path):
    """Spoustec .desktop -> {'argv': [...], 'terminal': bool}, None = neni co spustit.
    Exec se spusti v sandboxu (proto ho tam uzivatel posila); kody %f %u ... se vynechaji."""
    import shlex
    data = _read_head(path, 256 << 10)
    if not data:
        return None
    keys, section = {}, None
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
            continue
        if section != "[Desktop Entry]" or "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        keys.setdefault(k.strip(), v.strip())
    if keys.get("Type", "Application") != "Application" or not keys.get("Exec"):
        return None
    try:
        argv = shlex.split(_desktop_unescape(keys["Exec"]))
    except ValueError:
        return None
    argv = [a.replace("%%", "%") for a in argv if not re.fullmatch(r"%[fFuUdDnNickvm]", a)]
    if not argv:
        return None
    if "/" in argv[0] and not argv[0].startswith(("/", "~")):
        argv[0] = os.path.normpath(os.path.join(keys.get("Path") or os.path.dirname(os.path.abspath(path)),
                                                argv[0]))
    return {"argv": argv, "terminal": keys.get("Terminal", "false").strip().lower() in ("true", "1")}


def launch_plan(path, kind, interp=None, terminal=None):
    """Jak soubor spustit: {'argv': prikaz v sandboxu, 'gui': --gui (vlastni okno), 'terminal': v terminalu}.
    terminal=True/False = volba uzivatele (spusteni z terminalu, "Spustit v terminalu") ma prednost.
    Bez ni (dvojklik ve spravci souboru, spoustec, sluzba na pozadi) jen kdyz program zjevne potrebuje
    psani od uzivatele (skript s read/input(), spoustec s Terminal=true); jinak bez okna a bez terminalu
    (vystup se zachyti, po skonceni jedno upozorneni). None = soubor nelze spustit (spoustec bez Exec)."""
    argv = [path]
    asks = False
    if kind == "desktop":
        d = desktop_entry(path)
        if d is None:
            return None
        argv, gui, asks = d["argv"], not d["terminal"], d["terminal"]
    elif kind in ("appimage", "jar", "windows"):
        gui = True
    elif kind == "elf":
        gui = elf_is_gui(path)
    else:                                       # skript (i neznamy druh): podle obsahu
        gui = script_is_gui(path, interp)
        asks = not gui and script_reads_input(path, interp)
    return {"argv": argv, "gui": gui, "terminal": (not gui and asks) if terminal is None else bool(terminal)}


def _tail(f, limit=8192):
    """Posledni radky vystupu (nedurveryhodne): bez ridicich znaku, escapovane pro znackovani oznameni."""
    import html
    try:
        f.flush()
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - limit))
        text = f.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""
    lines = [re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|[\x00-\x1f\x7f]", "", x).strip() for x in text.splitlines()]
    lines = [x for x in lines if x][-3:]
    return html.escape("\n".join(lines)[-300:], quote=False)


def _watch(proc, log, name, started):
    """Program s oknem skoncil chybou hned po spusteni -> upozorneni (jinak by se nestalo vubec nic)."""
    try:
        rc = proc.wait()
        if rc not in (0, 130, 143, -2, -15) and time.monotonic() - started < LAUNCH_FAIL_WINDOW:
            notify(_("Could not start %s in the sandbox") % name,
                   _tail(log) or _("The program ended with error code %d.") % rc, "critical")
    finally:
        log.close()


def _log_file():
    """Nepojmenovany soubor pro vystup programu: zmizi sam a program do nej muze psat i po zavreni okna
    Lux Guard (roura by ho pak shodila signalem SIGPIPE)."""
    import tempfile
    d = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        return tempfile.TemporaryFile(dir=d, prefix="luxos-guard-")
    except OSError:
        return tempfile.TemporaryFile(prefix="luxos-guard-")


def _terminal_cmd(cmd, hold_always):
    """Prikaz terminalu; hold_always=False: okno zustane otevrene jen kdyz prikaz skonci chybou."""
    term = shutil.which("luxos-terminal") or shutil.which("xfce4-terminal")
    if not hold_always:
        cmd = ["/bin/sh", "-c", '"$@" || { rc=$?; printf "\\n%s\\n" "$0"; read -r _; exit $rc; }',
               _("Press Enter to close"), *cmd]
    if term:
        return [term, "--title", _("Sandbox"), *(["--hold"] if hold_always else []), "-x", *cmd]
    if shutil.which("x-terminal-emulator"):
        return ["x-terminal-emulator", "-e", *cmd]
    return None


def run_in_sandbox(path, kind, interp=None, terminal=None):
    """Spusti soubor v LuxOS Sandboxu (luxos-sandbox ho zkopiruje dovnitr, original se nepripoji).
    Program s oknem bez terminalu (selhani = upozorneni); v terminalu jen kdyz ho uzivatel spustil
    z terminalu nebo se program zjevne pta (read, input() ...); jinak bez okna a terminalu - vystup se
    zachyti a po skonceni prijde jedno klidne upozorneni s tlacitkem Zobrazit vystup.
    terminal=True/False: vyslovna volba uzivatele."""
    name = os.path.basename(path or "") or "?"
    if not shutil.which(SANDBOX_CLI):
        notify(_("Sandbox is not installed"), _("Install the luxos-sandbox package."), "critical")
        return None
    if not sandbox_exists():
        notify(_("Create the sandbox first"),
               _("The Sandbox window opens. Click Create, then try the program again."))
        try:
            return subprocess.Popen(["luxos-sandbox-gui"], start_new_session=True)
        except OSError:
            return None
    plan = launch_plan(path, kind, interp, terminal)
    if plan is None:
        notify(_("Could not start %s in the sandbox") % name,
               _("The launcher does not contain a program to run."), "critical")
        return None
    cmd = [SANDBOX_CLI, "run", *(["--gui"] if plan["gui"] else []), "--", *plan["argv"]]
    if plan["terminal"]:
        tcmd = _terminal_cmd(cmd, hold_always=not plan["gui"])
        try:
            if tcmd:
                return subprocess.Popen(tcmd, stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass
        # bez aplikace terminalu: radeji bez okna s vystupem v upozorneni nez vubec
    if not plan["gui"]:
        return start_headless(name, cmd)
    log = _log_file()
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    except OSError as e:
        log.close()
        notify(_("Could not start %s in the sandbox") % name, str(e)[:200], "critical")
        return None
    threading.Thread(target=_watch, args=(proc, log, name, time.monotonic()), daemon=True).start()
    return proc


# ---- beh bez okna a bez terminalu ---------------------------------------------------------------
# Neprogramator po kliknuti na "Spustit v sandboxu" nema videt vyskakujici terminal. Program bez okna
# bezi potichu; hlida ho samostatny maly proces (prezije zavreni okna Lux Guard i aktualizaci pomocnika),
# ktery zachyti posledni vystup (OUTPUT_LIMIT) do soukromeho souboru a ukaze jedno upozorneni.

OUTPUT_LIMIT = 64 << 10         # posledni vystup programu (bajty)
RUNNING_NOTICE = 20             # s: program bezi dele -> upozorneni "bezi" s tlacitkem Zastavit
STOP_GRACE = 3                  # s: po SIGTERM, pak SIGKILL
OUTPUT_KEEP = 24 * 3600         # s: starsi soubory s vystupem se pri dalsim behu smazou
NOTIFY_WAIT = 600               # s: nejdele cekani na volbu ve vyslednem upozorneni (notify-send --wait)
_CRASH_RC = {-4, -6, -7, -8, -11, 132, 134, 135, 136, 139}   # SIGILL/ABRT/BUS/FPE/SEGV (i 128+N ze sandboxu)

_ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"          # OSC (nazev okna, odkazy)
                   r"|\x1b[P^_X][^\x1b]*(?:\x1b\\)?"               # DCS/PM/APC/SOS
                   r"|\x1b\[[0-?]*[ -/]*[@-~]"                     # CSI (barvy, pohyb kurzoru)
                   r"|\x1b[ -/]*[0-~]?"                            # ostatni ESC
                   r"|\x9b[0-?]*[ -/]*[@-~]")                      # CSI v 8 bitech
# ridici znaky krome tabulatoru a noveho radku, DEL, C1 a znaky obraceni smeru textu (Trojan Source)
_CTRL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f‎‏‪-‮⁦-⁩]")


def clean_output(data, truncated=False):
    """Vystup programu (neduveryhodny) -> citelny text: bez escape sekvenci a ridicich znaku, prepisovany
    radek (\\r, ukazatel prubehu) jen v posledni podobe; useknuty zacatek s poznamkou."""
    text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else str(data)
    text = _ANSI.sub("", text).replace("\r\n", "\n")
    lines = []
    for line in text.split("\n"):
        if "\r" in line:
            parts = [x for x in line.split("\r") if x.strip()]
            line = parts[-1] if parts else ""
        lines.append(_CTRL.sub("", line).rstrip())
    if truncated and len(lines) > 1:
        lines = lines[1:]                      # prvni radek je useknuty uprostred
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    out = "\n".join(lines)
    if truncated:
        out = _("… (only the last %d KB of the output is kept)") % (OUTPUT_LIMIT >> 10) + "\n" + out
    return out


class _Capture(threading.Thread):
    """Cte vystup programu a drzi jen poslednich OUTPUT_LIMIT bajtu (pamet ani disk nerostou)."""

    def __init__(self, stream, limit=None):
        super().__init__(daemon=True)
        self.stream, self.limit = stream, limit or OUTPUT_LIMIT
        self.buf, self.truncated, self.lock = bytearray(), False, threading.Lock()

    def run(self):
        fd = self.stream.fileno()
        while True:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            with self.lock:
                self.buf += chunk
                if len(self.buf) > self.limit:
                    del self.buf[:len(self.buf) - self.limit]
                    self.truncated = True

    def text(self):
        with self.lock:
            data, truncated = bytes(self.buf), self.truncated
        return clean_output(data, truncated)


def output_dir():
    """Soukroma slozka pro vystupy: $XDG_RUNTIME_DIR/luxos-guard (tmpfs, zmizi po odhlaseni),
    jinak ~/.cache/luxos-guard; vzdy vlastni slozka 0700 (ne odkaz)."""
    bases = [os.environ.get("XDG_RUNTIME_DIR"),
             os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")]
    for base in bases:
        if not base or not os.path.isabs(base):
            continue
        d = os.path.join(base, "luxos-guard")
        try:
            os.makedirs(d, mode=0o700, exist_ok=True)
            st = os.lstat(d)
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
                continue
            if stat.S_IMODE(st.st_mode) != 0o700:
                os.chmod(d, 0o700)
            return d
        except OSError:
            continue
    return None


def _cleanup_outputs(d, now=None):
    now = now or time.time()
    try:
        names = os.listdir(d)
    except OSError:
        return
    for n in names:
        if n.startswith("output-") and n.endswith(".txt"):
            p = os.path.join(d, n)
            try:
                if now - os.lstat(p).st_mtime > OUTPUT_KEEP:
                    os.unlink(p)
            except OSError:
                pass


def write_output(path, text):
    """Zapis vystupu do souboru 0600 (bez nasledovani odkazu); vraci cestu nebo None."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except OSError:
        return None
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text + ("\n" if text else ""))
    return path


def _notify_wait(title, body, actions=(), urgency="normal", timeout_ms=10000, replace=None, on_id=None):
    """Upozorneni s tlacitky (notify-send -p --wait); vraci zvolenou akci nebo None.
    on_id(id, popen) hned po zobrazeni: id pro pozdejsi nahrazeni, popen pro predcasne ukonceni."""
    import html
    cmd = ["notify-send", "-a", "Lux Guard", "-i", "luxos-guard", "-u", urgency, "-t", str(timeout_ms), "-e", "-p"]
    if replace:
        cmd += ["-r", str(replace)]
    for key, text in actions:
        cmd += ["-A", f"{key}={text}"]
    if actions:
        cmd.append("-w")
    cmd += [html.escape(title, quote=False), html.escape(body, quote=False)]
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, start_new_session=True)
    except OSError:
        return None
    keys = {k for k, _t in actions}
    action, got_id = None, False
    killer = None
    if timeout_ms:                              # vysledek: necekat donekonecna (upozorneni bez casu = beh)
        killer = threading.Timer(NOTIFY_WAIT, lambda: p.poll() is None and p.kill())
        killer.daemon = True
        killer.start()
    try:
        for line in p.stdout:
            line = line.strip()
            if not got_id and line.isdigit():
                got_id = True
                if on_id:
                    on_id(int(line), p)
            elif line in keys:
                action = line
        p.wait()
    finally:
        if killer:
            killer.cancel()
    return action


class HeadlessRun:
    """Beh programu bez okna: zachyceni vystupu, upozorneni "bezi" (Zastavit) a po skonceni vysledek."""

    def __init__(self, name, cmd, gui_cmd=None):
        self.name, self.cmd = name, cmd
        self.gui_cmd = gui_cmd or [os.environ.get("LUXOS_GUARD_GUI") or shutil.which("luxos-guard-gui")
                                   or "luxos-guard-gui"]
        self.proc = self.cap = None
        self.stopped = False
        self.nid = None
        self.waiter = None
        self.lock = threading.Lock()
        self.done = threading.Event()
        d = output_dir()
        if d:
            _cleanup_outputs(d)
        self.out_path = os.path.join(d, "output-%d-%d.txt" % (int(time.time()), os.getpid())) if d else None

    def start(self):
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        self.cap = _Capture(self.proc.stdout)
        self.cap.start()

    def stop(self):
        """Zastavit jen vlastni beh: skupina procesu programu (vlastni sezeni = pgid je jeho PID)."""
        import signal
        p = self.proc
        if p is None or p.poll() is not None:
            return
        self.stopped = True
        for sig, wait in ((signal.SIGTERM, STOP_GRACE), (signal.SIGKILL, 5)):
            try:
                os.killpg(p.pid, sig)
            except (ProcessLookupError, PermissionError):
                return
            try:
                p.wait(wait)
                return
            except subprocess.TimeoutExpired:
                continue

    def save_output(self):
        text = self.cap.text() if self.cap else ""
        if self.out_path:
            write_output(self.out_path, text)
        return text

    def show_output(self):
        self.save_output()
        if not self.out_path:
            return
        try:
            subprocess.Popen([*self.gui_cmd, "output", self.out_path, self.name], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass

    def _got_id(self, nid, p):
        with self.lock:
            self.nid, self.waiter = nid, p

    def running_notice(self):
        """Upozorneni po celou dobu behu (-t 0); Zobrazit vystup ho po otevreni okna ukaze znovu."""
        while not self.done.is_set() and self.proc.poll() is None:
            action = _notify_wait(_("%s is running in the sandbox") % self.name,
                                  _("It has no window. It cannot see or change your files."),
                                  (("output", _("Show Output")), ("stop", _("Stop"))), timeout_ms=0,
                                  replace=self.nid, on_id=self._got_id)
            if self.done.is_set():
                return
            if action == "stop":
                self.stop()
                return
            if action != "output":
                return                          # zavreno uzivatelem / bez sluzby upozorneni
            self.show_output()

    def result_text(self, rc):
        n = self.name
        if self.stopped:
            return _("%s was stopped") % n, _("The program in the sandbox was ended."), "normal"
        if rc in _CRASH_RC:
            return (_("%s crashed in the sandbox") % n,
                    _("It ran in the sandbox and could not change your files."), "critical")
        if rc == 0:
            return _("%s ran safely in the sandbox") % n, _("It could not see or change your files."), "normal"
        return (_("%s finished with an error") % n,
                _("It finished with error code %d. It ran in the sandbox, so your files were not affected.") % rc,
                "normal")

    def run(self):
        try:
            self.start()
        except OSError as e:
            notify(_("Could not start %s in the sandbox") % self.name, str(e)[:200])
            return 1
        notice = None
        try:
            rc = self.proc.wait(RUNNING_NOTICE)
        except subprocess.TimeoutExpired:
            notice = threading.Thread(target=self.running_notice, daemon=True)
            notice.start()
            rc = self.proc.wait()
        self.done.set()
        self.cap.join(5)
        for _i in range(5 if notice else 0):
            with self.lock:
                waiter = self.waiter
            if waiter is not None and waiter.poll() is None:
                waiter.terminate()          # vlastni notify-send --wait; upozorneni nahradi vysledek
            notice.join(1)
            if not notice.is_alive():
                break
        nid = self.nid
        text = self.save_output()
        title, body, urgency = self.result_text(rc)
        actions = (("output", _("Show Output")),) if text else ()
        if not text:
            body += " " + _("It did not print anything.")
        if self.out_path and not text:
            try:
                os.unlink(self.out_path)
            except OSError:
                pass
        if _notify_wait(title, body, actions, urgency=urgency, timeout_ms=15000, replace=nid) == "output":
            self.show_output()
        return 0


def start_headless(name, cmd):
    """Spusti hlidaci proces behu bez okna (vlastni sezeni - prezije zavreni okna i pomocnika)."""
    try:
        return subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "headless", name, "--", *cmd],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    except OSError as e:
        notify(_("Could not start %s in the sandbox") % name, str(e)[:200])
        return None


def _headless_main(argv):
    if len(argv) < 3 or argv[1] != "--":
        print("usage: luxos_guard_session.py headless NAME -- COMMAND...", file=sys.stderr)
        return 2
    import signal
    run = HeadlessRun(argv[0], argv[2:])

    def on_signal(_s, _f):              # konec sezeni / zastaveni hlidace: program nenechat bezet
        run.stop()
        os._exit(0)
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGHUP, on_signal)
    return run.run()


def trash(path):
    r = subprocess.run(["gio", "trash", "--", path], capture_output=True, text=True)
    if r.returncode == 0:
        notify(_("Moved to Trash"), os.path.basename(path))
    else:
        notify(_("Could not move to Trash"), (r.stderr or "").strip()[:200])


if __name__ == "__main__":
    if sys.argv[1:2] == ["headless"]:
        sys.exit(_headless_main(sys.argv[2:]))
    sys.exit(2)
