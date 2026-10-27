"""Lux Guard - akce v sezeni uzivatele (pomocnik i okno): upozorneni, spusteni v sandboxu, kos."""
import os
import shutil
import subprocess
import sys

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


def run_in_sandbox(path, kind):
    """Spusti soubor v LuxOS Sandboxu (luxos-sandbox ho zkopiruje dovnitr, original se nepripoji)."""
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
    if kind in ("elf", "appimage", "jar", "windows"):
        cmd = [SANDBOX_CLI, "run", "--gui", "--", path]
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, start_new_session=True)
    # skripty: v terminalu, aby byl videt vystup
    cmd = [SANDBOX_CLI, "run", "--", path]
    term = shutil.which("luxos-terminal") or shutil.which("xfce4-terminal")
    if term:
        return subprocess.Popen([term, "--title", _("Sandbox"), "--hold", "-x", *cmd], start_new_session=True)
    if shutil.which("x-terminal-emulator"):
        return subprocess.Popen(["x-terminal-emulator", "-e", *cmd], start_new_session=True)
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, start_new_session=True)


def trash(path):
    r = subprocess.run(["gio", "trash", "--", path], capture_output=True, text=True)
    if r.returncode == 0:
        notify(_("Moved to Trash"), os.path.basename(path))
    else:
        notify(_("Could not move to Trash"), (r.stderr or "").strip()[:200])
