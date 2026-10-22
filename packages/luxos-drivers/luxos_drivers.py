"""LuxOS - stav ovladacu: co doporucuje luxos-hwdetect a co uz je nainstalovane.

Pouziva aplikace Ovladace (/usr/bin/luxos-drivers), jeji pomocnik pro root
(/usr/lib/luxos/drivers/luxos-drivers-helper) a upozorneni po prihlaseni
(luxos_drivers_session v luxos-daemon). Nic nemeni - jen cte sysfs a databazi pacmanu.
"""
import json
import os
import re
import subprocess

ROOT = ""                                   # testy: docasny koren
HWDETECT = "/usr/bin/luxos-hwdetect"
LOCAL_DB = "/var/lib/pacman/local"
# Skutecny pacman (luxos-pacman); /usr/bin/pacman je v LuxOS kompatibilni vrstva pro lidi
PACMAN = "/usr/lib/lux/alpm/pacman" if os.access("/usr/lib/lux/alpm/pacman", os.X_OK) else "pacman"

WORKING, INSTALLED, RESTART, AVAILABLE = "working", "installed", "restart", "available"

# Baliky, ktere doporuceny balik plne nahrazuji (jiny zpusob instalace tehoz ovladace).
# Ovladac 580 umi i Turing a novejsi - kdo ho ma, nemusi prechazet na nvidia-open.
EQUIVALENT = {
    "nvidia-open-dkms": ("nvidia-open", "nvidia-open-lts", "nvidia-580xx-dkms"),
    "nvidia-utils": ("nvidia-580xx-utils",),
    "lib32-nvidia-utils": ("lib32-nvidia-580xx-utils",),
    "broadcom-wl-dkms": ("broadcom-wl",),
}
PKG_RE = re.compile(r"^[a-z0-9@._+][a-z0-9@._+-]*$")
SERVICE_RE = re.compile(r"^[a-zA-Z0-9@._-]+\.service$")


def P(path):
    return ROOT + path


def detect(timeout=60):
    """Vystup luxos-hwdetect --json (slovnik)."""
    r = subprocess.run([HWDETECT, "--json"], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"luxos-hwdetect exited with {r.returncode}")
    data = json.loads(r.stdout)
    if not isinstance(data, dict) or not isinstance(data.get("devices"), list):
        raise RuntimeError("luxos-hwdetect: unexpected output")
    return data


def installed_packages():
    """Jmena nainstalovanych baliku primo z databaze pacmanu (adresare jmeno-verze-vydani)."""
    names = set()
    try:
        entries = os.listdir(P(LOCAL_DB))
    except OSError:
        return names
    for e in entries:
        parts = e.rsplit("-", 2)
        if len(parts) == 3 and parts[0]:
            names.add(parts[0])
    return names


def module_loaded(name):
    return bool(name) and os.path.isdir(P("/sys/module/" + name.replace("-", "_")))


def is_installed(pkg, installed):
    return pkg in installed or any(e in installed for e in EQUIVALENT.get(pkg, ()))


def _active_alternative(dev, installed):
    """Alternativa, kterou si uzivatel uz nainstaloval (podle jejiho hlavniho baliku), jinak None."""
    for a in dev.get("alternatives") or []:
        pk = a.get("packages") or []
        if pk and pk[0] in installed:
            return a
    return None


def evaluate(data, installed=None, loaded=module_loaded):
    """Stav kazdeho zarizeni: [{"device", "status", "missing", "active"}].

    working   - nic navic nepotrebuje (ovladac je v jadre)
    installed - vse nainstalovano a ovladac bezi
    restart   - nainstalovano, ale modul jeste nebezi (po instalaci NVIDIA apod.)
    available - chybi baliky (missing)
    active    - pouzita alternativa (napr. NVIDIA 470 misto nouveau), jinak None
    """
    installed = installed_packages() if installed is None else installed
    out = []
    for dev in data.get("devices", []):
        active = _active_alternative(dev, installed)
        target = active or dev
        pkgs = target.get("packages") or []
        missing = [p for p in pkgs if not is_installed(p, installed)]
        if not pkgs:
            status = WORKING
        elif missing:
            status = AVAILABLE
        elif target.get("module") and target.get("reboot") and not loaded(target["module"]):
            status = RESTART
        else:
            status = INSTALLED
        out.append({"device": dev, "status": status, "missing": missing, "active": active})
    return out


def _dedup(items):
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def missing_packages(states):
    return _dedup(p for s in states if s["status"] == AVAILABLE for p in s["missing"])


def wanted_services(states):
    """Sluzby zarizeni, ktera se instaluji nebo uz jsou nainstalovana (ne working)."""
    return _dedup(sv for s in states for sv in ((s["active"] or s["device"]).get("services") or []))


def needs_restart(states):
    return any(s["status"] == RESTART for s in states)


def plan(data, installed=None, alternative=None, loaded=module_loaded):
    """Co nainstalovat: (baliky, sluzby, restart). alternative=(id zarizeni, id alternativy)
    nainstaluje misto doporuceneho ovladace danou alternativu. Neznama volba -> ValueError."""
    installed = installed_packages() if installed is None else installed
    states = evaluate(data, installed, loaded)
    if alternative is None:
        pkgs = missing_packages(states)
        reboot = any(s["device"].get("reboot") for s in states if s["status"] == AVAILABLE)
        svcs = wanted_services(states)
    else:
        dev_id, alt_id = alternative
        dev = next((d for d in data.get("devices", []) if d.get("id") == dev_id), None)
        alt = next((a for a in (dev or {}).get("alternatives") or [] if a.get("id") == alt_id), None)
        if alt is None:
            raise ValueError(f"unknown alternative {dev_id}:{alt_id}")
        pkgs = [p for p in alt.get("packages") or [] if p not in installed]
        svcs = list(alt.get("services") or [])
        reboot = bool(alt.get("reboot"))
    for p in pkgs:
        if not PKG_RE.match(p):
            raise ValueError(f"invalid package name {p!r}")
    for s in svcs:
        if not SERVICE_RE.match(s):
            raise ValueError(f"invalid service name {s!r}")
    return pkgs, svcs, reboot


def notify_key(states):
    """Retezec chybejicich baliku (porovnani s tim, co uz uzivatel odmitl)."""
    return " ".join(sorted(missing_packages(states)))


def boot_id():
    try:
        with open(P("/proc/sys/kernel/random/boot_id")) as f:
            return f.read().strip()
    except OSError:
        return ""


def _pac_version(args):
    try:
        r = subprocess.run([PACMAN, *args], capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        if args[0] == "-Q":
            parts = line.split()
            if len(parts) == 2:
                return parts[1]
        elif line.startswith("Version"):
            return line.split(":", 1)[1].strip()
    return None


def headers_out_of_sync(pkgs, query=_pac_version):
    """Hlavicky jadra, jejichz verze v databazi repozitaru neodpovida nainstalovanemu jadru.
    DKMS by modul sestavilo pro jinou verzi - pak je potreba nejdriv aktualizovat cely system."""
    bad = []
    for p in pkgs:
        if not p.endswith("-headers"):
            continue
        kernel = p[: -len("-headers")]
        have = query(["-Q", kernel])
        repo = query(["-Si", p])
        if have is None or repo is None or have != repo:
            bad.append(p)
    return bad
