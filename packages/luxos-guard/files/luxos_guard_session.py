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
_PY_INPUT = re.compile(r"\b(input|raw_input|getpass)\s*\(|\bsys\.stdin\b|\bcurses\b")
_SH_GUI = re.compile(r"(^|[\s;&|(`$])(zenity|yad|kdialog|Xdialog|gxmessage|xmessage|gdialog)\b", re.M)
_SH_INPUT = re.compile(r"(^|[\s;&|(])(read|select|dialog|whiptail)\s", re.M)
_PERL_GUI = re.compile(r"^\s*use\s+(Tk|Gtk[234]?|Wx|Prima|Qt)\b", re.M)
_PERL_INPUT = re.compile(r"<STDIN>|<>|\bTerm::ReadLine\b")


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


def script_is_gui(path, interp):
    """Skript s oknem (Tk/GTK/Qt/pygame, zenity/yad ...), ktery necte z terminalu."""
    import luxos_guard_rules as rules
    data = _read_head(path, 512 << 10)
    if not data:
        return False
    nul = data.find(b"\0")
    text = (data if nul < 0 else data[:nul]).decode("utf-8", "replace")
    if not interp and text.startswith("#!"):
        interp = rules.shebang_interp(text.split("\n", 1)[0])
    fam = rules.interp_family(interp)
    if fam == "python":
        return bool(_PY_GUI.search(text)) and not _PY_INPUT.search(text)
    if fam == "sh":
        return bool(_SH_GUI.search(text)) and not _SH_INPUT.search(text)
    if fam == "perl":
        return bool(_PERL_GUI.search(text)) and not _PERL_INPUT.search(text)
    return False


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
    None = soubor nelze spustit (spoustec bez Exec)."""
    argv = [path]
    if kind == "desktop":
        d = desktop_entry(path)
        if d is None:
            return None
        argv, gui = d["argv"], not d["terminal"]
    elif kind in ("appimage", "jar", "windows"):
        gui = True
    elif kind == "elf":
        gui = elf_is_gui(path)
    else:                                       # skript (i neznamy druh): podle obsahu
        gui = script_is_gui(path, interp)
    return {"argv": argv, "gui": gui, "terminal": (not gui) if terminal is None else bool(terminal)}


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
    Program s oknem bez terminalu (selhani = upozorneni), textovy program v terminalu, ktery zustane
    otevreny kvuli vystupu. terminal=True/False: vyslovna volba uzivatele."""
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
        if not plan["gui"]:
            notify(_("Could not start %s in the sandbox") % name, _("No terminal application was found."),
                   "critical")
            return None
    log = _log_file()
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    except OSError as e:
        log.close()
        notify(_("Could not start %s in the sandbox") % name, str(e)[:200], "critical")
        return None
    threading.Thread(target=_watch, args=(proc, log, name, time.monotonic()), daemon=True).start()
    return proc


def trash(path):
    r = subprocess.run(["gio", "trash", "--", path], capture_output=True, text=True)
    if r.returncode == 0:
        notify(_("Moved to Trash"), os.path.basename(path))
    else:
        notify(_("Could not move to Trash"), (r.stderr or "").strip()[:200])
