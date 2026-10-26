"""LuxOS - logika Pruvodce nastavenim (OEM, prvni start) bez GTK: kroky, ulozeny prubeh, data pro luxos-oem.

Pruvodce (luxos-setup-assistant) bezi misto prihlasovaci obrazovky jako uzivatel lightdm. Rozpracovane
volby (bez hesel) si uklada do PROGRESS, takze po vypadku proudu nebo padu zacne znovu s vyplnenymi
kroky. Na konci posle vse (vcetne hesel) na stdin "sudo luxos-oem finish" jako radky KLIC=hodnota.
"""
import json
import os
import re
import tempfile

PROGRESS = os.environ.get("LUXOS_SETUP_STATE") or os.path.expanduser("~/.local/state/luxos-setup/progress.json")
# Ulozene volby (zadna hesla ani ucet LuxAI - ten se po vypadku prihlasi znovu)
SAVED_KEYS = ("locale", "xkb", "xkb_switch", "timezone", "fullname", "username", "user_edited", "hostname",
              "host_edited", "autologin", "care", "disk_same", "org", "domain", "domain_user", "domain_ou", "step")
# Firemni sit (domena Active Directory, luxos-domain): heslo spravce domeny jen v DOMAIN_PASSWORD
# na stdin luxos-oem finish -> stdin "lux-domain join --password-stdin"; nikdy se neuklada
FINISH_KEYS = ("LOCALE", "XKB_LAYOUT", "XKB_VARIANT", "XKB_OPTIONS", "TIMEZONE", "FULLNAME", "USERNAME",
               "PASSWORD", "HOSTNAME", "AUTOLOGIN", "CARE_MODE", "LUXAI_ACCOUNT", "PHOTO", "DISK_PASS",
               "DOMAIN", "DOMAIN_USER", "DOMAIN_PASSWORD", "DOMAIN_OU")
DOMAIN_CLI = os.environ.get("LUXOS_DOMAIN_CLI", "/usr/bin/lux-domain")
DOMAIN_RE = re.compile(r"(?=.{3,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+")
# Systemova jmena (shodne s luxos-install-gui RESERVED_USERS a luxos-oem RESERVED)
RESERVED_USERS = {"root", "bin", "daemon", "mail", "ftp", "http", "nobody", "dbus", "uuidd", "polkitd", "avahi",
                  "lightdm", "git", "rtkit", "colord", "alpm", "tss", "usbmux", "geoclue", "lux", "sddm", "gdm"}


def domain_available():
    """Krok Firemni sit jen s nainstalovanym luxos-domain (lux-domain)."""
    return os.access(DOMAIN_CLI, os.X_OK)


def steps(luks_pending, domain=False):
    """Poradi stranek: jazyk, klavesnice, Wi-Fi, casove pasmo, ucet, [firemni sit], LuxAI, [heslo disku],
    udrzba, dokonceni."""
    out = ["welcome", "keyboard", "network", "timezone", "account"]
    if domain:
        out.append("organization")
    out.append("luxai")
    if luks_pending:
        out.append("diskpass")
    out += ["care", "finish"]
    return out


def parse_status(text):
    """Vystup "luxos-oem status" (KLIC=hodnota) -> dict; nezname radky se ignoruji."""
    out = {"OEM": "0", "ARMED": "0", "DONE": "0", "LUKS": "none", "USER": ""}
    for line in (text or "").splitlines():
        k, sep, v = line.partition("=")
        if sep and k in out:
            out[k] = v.strip()
    return out


def load_progress(path=PROGRESS):
    """Ulozene volby nebo {} (poskozeny soubor = zacit znovu, nikdy vyjimka)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {k: data[k] for k in SAVED_KEYS if k in data}
    if "xkb" in out:
        try:
            out["xkb"] = [(str(a), str(b)) for a, b in out["xkb"]][:4] or [("us", "")]
        except (TypeError, ValueError):
            del out["xkb"]
    return out


def save_progress(state, path=PROGRESS):
    """Atomicky zapis (tmp + fsync + prejmenovani): vypadek proudu nikdy nenecha pul souboru."""
    data = {k: state[k] for k in SAVED_KEYS if k in state}
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".progress-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def valid_user(u):
    return bool(re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", u or "")) and u not in RESERVED_USERS


def valid_domain(d):
    """firma.local, ad.firma.cz (aspon dve casti, mala pismena)."""
    return bool(DOMAIN_RE.fullmatch(d or ""))


def domain_problem(state):
    """Proc nejde pokracovat na strance Firemni sit ("" = v poradku nebo osobni pocitac)."""
    if not state.get("org"):
        return ""
    if not valid_domain(state.get("domain", "").strip().lower()):
        return "domain"
    if not state.get("domain_user", "").strip():
        return "user"
    if not state.get("domain_pw"):
        return "password"
    return ""


def domain_values(state):
    """DOMAIN, DOMAIN_USER, DOMAIN_PASSWORD, DOMAIN_OU (prazdne = osobni pocitac)."""
    if not state.get("org"):
        return {"DOMAIN": "", "DOMAIN_USER": "", "DOMAIN_PASSWORD": "", "DOMAIN_OU": ""}
    return {"DOMAIN": state.get("domain", "").strip().lower(), "DOMAIN_USER": state.get("domain_user", "").strip(),
            "DOMAIN_PASSWORD": state.get("domain_pw", ""), "DOMAIN_OU": state.get("domain_ou", "").strip()}


def parse_discover(text):
    """JSON z "lux-domain discover --json" -> dict (vzdy s klicem ok)."""
    try:
        data = json.loads(text or "")
    except ValueError:
        return {"ok": False, "error": "failed", "message": ""}
    if not isinstance(data, dict):
        return {"ok": False, "error": "failed", "message": ""}
    data["ok"] = bool(data.get("ok"))
    return data


def disk_password(state):
    """Heslo disku: stejne jako heslo uctu (vychozi, jako FileVault) nebo vlastni."""
    return state.get("pw1", "") if state.get("disk_same", True) else state.get("disk1", "")


def disk_problem(state):
    """Proc nejde pokracovat na strance hesla disku ("" = v poradku)."""
    if state.get("disk_same", True):
        return "" if state.get("pw1") else "account"
    if not state.get("disk1"):
        return "empty"
    if state.get("disk1") != state.get("disk2"):
        return "mismatch"
    return ""


def finish_input(state, xkb_values, luks_pending, photo=""):
    """Radky KLIC=hodnota pro "luxos-oem finish". Hodnota nesmi obsahovat novy radek (ValueError)."""
    layout, variant, options = xkb_values
    values = {
        "LOCALE": state["locale"], "XKB_LAYOUT": layout, "XKB_VARIANT": variant, "XKB_OPTIONS": options,
        "TIMEZONE": state["timezone"], "FULLNAME": state.get("fullname", "").strip(),
        "USERNAME": state["username"], "PASSWORD": state["pw1"], "HOSTNAME": state.get("hostname", ""),
        "AUTOLOGIN": "1" if state.get("autologin") else "0", "CARE_MODE": state.get("care", "carefree"),
        "LUXAI_ACCOUNT": json.dumps(state["luxai"], ensure_ascii=False) if state.get("luxai") else "",
        "PHOTO": photo or "",
        "DISK_PASS": disk_password(state) if luks_pending else "",
    }
    values.update(domain_values(state))
    lines = []
    for k in FINISH_KEYS:
        v = str(values[k])
        if "\n" in v or "\r" in v or "\0" in v:
            raise ValueError(k)
        lines.append(f"{k}={v}")
    return "\n".join(lines) + "\n"


def parse_line(line):
    """Radek vystupu luxos-oem finish -> ("step", text) | ("error", text) | ("warn", text) | ("done", "")
    | ("log", radek). @@WARN = nezavazny problem (napr. pocitac se nepripojil k domene)."""
    if line.startswith("@@STEP "):
        parts = line[7:].split(" ", 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            return ("step", parts[2], int(parts[0]), int(parts[1]))
        return ("step", line[7:], 0, 0)
    if line.startswith("@@ERROR "):
        return ("error", line[8:])
    if line.startswith("@@WARN "):
        return ("warn", line[7:])
    if line.strip() == "@@DONE":
        return ("done", "")
    return ("log", line)
