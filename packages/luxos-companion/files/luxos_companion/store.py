"""Nastaveni LuxOS Companion: schvalene telefony a prepinace (~/.config/luxos/companion.json, 0600).

{"version": 1,
 "phones": {"AA:BB:CC:DD:EE:FF": {"name": "Pixel 8", "approved": "2026-10-27T12:00:00+00:00"}},
 "share_location": true, "allow_luxai": true, "allow_calendar": true}

Samotne sparovani v Bluetooth neni opravneni: telefon musi byt schvaleny zde (dotaz pri prvnim
pripojeni, odebrani v okne Telefon). Zapis: zamek (flock) + docasny soubor + prejmenovani, takze
sluzba i okno nastaveni mohou soubor menit soucasne bez ztraty zmen.
"""
import datetime
import fcntl
import json
import os
import re

TOGGLES = ("share_location", "allow_luxai", "allow_calendar")
DEFAULTS = {"share_location": True, "allow_luxai": True, "allow_calendar": True}
ADDRESS_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
MAX_NAME = 248               # Bluetooth jmeno zarizeni (bajty v BlueZ), tady znaky


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "luxos", "companion.json")


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "luxos", "companion")


def normalize_address(addr):
    """'aa:bb:..' -> 'AA:BB:..'; neplatna adresa -> None."""
    if not isinstance(addr, str):
        return None
    a = addr.strip().upper().replace("-", ":")
    return a if ADDRESS_RE.match(a) else None


def clean_name(name, address=""):
    """Jmeno telefonu pro zobrazeni: bez ridicich znaku, nejvys MAX_NAME znaku."""
    if not isinstance(name, str):
        name = ""
    name = "".join(ch for ch in name if ch.isprintable()).strip()[:MAX_NAME]
    return name or address


def _sanitize(data):
    out = {"version": 1, "phones": {}}
    if not isinstance(data, dict):
        data = {}
    phones = data.get("phones")
    if isinstance(phones, dict):
        for addr, info in phones.items():
            a = normalize_address(addr)
            if a and isinstance(info, dict):
                out["phones"][a] = {"name": clean_name(info.get("name"), a),
                                    "approved": str(info.get("approved") or "")}
    for key in TOGGLES:
        v = data.get(key)
        out[key] = v if isinstance(v, bool) else DEFAULTS[key]
    return out


def _write_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Settings:
    """Cteni a zmeny companion.json. Kazda zmena: zamek, nove nacteni, uprava, atomicky zapis."""

    def __init__(self, path=None):
        self.path = path or config_path()
        self.data = _sanitize(None)
        self.reload()

    def reload(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = _sanitize(json.load(f))
        except (OSError, ValueError):
            self.data = _sanitize(None)
        return self.data

    def _modify(self, fn):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.reload()
            fn(self.data)
            self.data = _sanitize(self.data)
            _write_atomic(self.path, self.data)
        return self.data

    # ---- dotazy ----
    def is_approved(self, address):
        a = normalize_address(address)
        return bool(a) and a in self.data["phones"]

    def phones(self):
        """[(adresa, jmeno)] serazene podle jmena."""
        return sorted(((a, p["name"]) for a, p in self.data["phones"].items()), key=lambda x: x[1].lower())

    def get(self, key):
        return self.data[key]

    # ---- zmeny ----
    def approve(self, address, name):
        a = normalize_address(address)
        if not a:
            raise ValueError("invalid Bluetooth address")
        stamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        return self._modify(lambda d: d["phones"].__setitem__(a, {"name": clean_name(name, a), "approved": stamp}))

    def remove(self, address):
        a = normalize_address(address)
        return self._modify(lambda d: d["phones"].pop(a, None))

    def set(self, key, value):
        if key not in TOGGLES or not isinstance(value, bool):
            raise ValueError(key)
        return self._modify(lambda d: d.__setitem__(key, value))


def read_toggle(key, path=None):
    """Jen cteni jednoho prepinace (Mapy: sdileni polohy telefonu) bez zamku."""
    try:
        with open(path or config_path(), encoding="utf-8") as f:
            return _sanitize(json.load(f))[key]
    except (OSError, ValueError):
        return DEFAULTS[key]
