"""LuxDrop - nastaveni, duveryhodna zarizeni (pripnute otisky) a historie prenosu."""
import json
import os
import re
import socket
import time

from . import identity, proto

MODES = ("off", "trusted", "everyone")
EVERYONE_SECONDS = 10 * 60
HISTORY_MAX = 200


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "luxdrop")


def downloads_dir():
    """Vychozi slozka pro prijate soubory: <Stazene>/LuxDrop (Stazene podle xdg-user-dirs)."""
    return os.path.join(xdg_downloads(), "LuxDrop")


def xdg_downloads():
    """Slozka Stazene podle xdg-user-dirs (jinak ~/Downloads)."""
    home = os.path.expanduser("~")
    try:
        with open(os.path.join(home, ".config", "user-dirs.dirs"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r'\s*XDG_DOWNLOAD_DIR="(.*)"', line)
                if m:
                    return m.group(1).replace("$HOME", home)
    except OSError:
        pass
    return os.path.join(home, "Downloads")


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    identity.write_private(path, json.dumps(data, indent=1, ensure_ascii=False).encode("utf-8"))


class Settings:
    DEFAULTS = {
        "name": "",
        "receive_mode": "everyone",
        "everyone_until": 0,
        "download_dir": "",
        "port": proto.DEFAULT_PORT,
        "background": False,
        "auto_accept_trusted": True,   # "Rychle ulozeni" od duveryhodnych zarizeni
        "localsend": True,             # kompatibilita s aplikaci LocalSend
        "localsend_port": 53317,
        "pin": "",                     # PIN pro prijem pres LocalSend (prazdny = bez PINu)
        "last_mode": "everyone",       # rezim, ktery obnovi prepinac "Pripraveno k prijmu"
    }

    def __init__(self, directory=None):
        self.dir = directory or config_dir()
        self.path = os.path.join(self.dir, "settings.json")
        self.data = dict(self.DEFAULTS)
        self.reload()

    def reload(self):
        loaded = _load_json(self.path, {})
        for k, v in self.DEFAULTS.items():
            if isinstance(loaded.get(k), type(v)) or (isinstance(v, (int, float)) and isinstance(loaded.get(k), (int, float))):
                self.data[k] = loaded[k]
        if self.data["receive_mode"] not in MODES:
            self.data["receive_mode"] = "trusted"

    def save(self):
        identity.ensure_private_dir(self.dir)
        _save_json(self.path, self.data)

    def __getitem__(self, k):
        return self.data[k]

    def set(self, k, v):
        self.data[k] = v
        self.save()

    @property
    def name(self):
        n = self.data["name"].strip()
        return n[:63] if n else default_name()

    @property
    def download_dir(self):
        return os.path.expanduser(self.data["download_dir"]) or downloads_dir()

    def mode(self):
        """Ucinny rezim; casove omezene "everyone" po uplynuti spadne zpet na "trusted".

        everyone_until == 0 znamena bez casoveho omezeni (kazdy prenos se stejne musi potvrdit).
        """
        m = self.data["receive_mode"]
        if m == "everyone" and self.data["everyone_until"]:
            left = self.data["everyone_until"] - time.time()
            # Rucne upraveny soubor nesmi prodlouzit "vsichni" nad 10 minut
            if left <= 0 or left > EVERYONE_SECONDS + 5:
                return "trusted"
        return m

    def set_mode(self, mode, minutes=None):
        """minutes: u "everyone" casove omezeni (max. 10 minut), None = bez omezeni."""
        if mode not in MODES:
            raise ValueError(mode)
        self.data["receive_mode"] = mode
        self.data["everyone_until"] = 0
        if mode == "everyone" and minutes:
            self.data["everyone_until"] = time.time() + min(minutes * 60, EVERYONE_SECONDS)
        self.save()

    def everyone_left(self):
        """Zbyvajici sekundy casove omezeneho "everyone" (0 = neomezeno nebo jiny rezim)."""
        if self.mode() != "everyone" or not self.data["everyone_until"]:
            return 0
        return max(0, int(self.data["everyone_until"] - time.time()))

    @property
    def pin(self):
        p = self.data["pin"].strip()
        return p[:32]


def default_name():
    try:
        import pwd
        real = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
    except (KeyError, ImportError):
        real = ""
    host = socket.gethostname().split(".")[0] or "LuxOS"
    return ("%s (%s)" % (real, host) if real else host)[:63]


class TrustStore:
    """Pripnute otisky duveryhodnych zarizeni (trusted.json, 0600)."""

    def __init__(self, directory=None):
        self.dir = directory or identity.data_dir()
        self.path = os.path.join(self.dir, "trusted.json")
        self.peers = {}
        self.reload()

    def reload(self):
        data = _load_json(self.path, {})
        self.peers = {k: v for k, v in data.items()
                      if isinstance(v, dict) and re.fullmatch(r"[0-9a-f]{64}", k)}

    def save(self):
        identity.ensure_private_dir(self.dir)
        _save_json(self.path, self.peers)

    def is_trusted(self, fp):
        self.reload()
        return fp.hex() in self.peers

    def get(self, fp):
        self.reload()
        return self.peers.get(fp.hex())

    def add(self, fp, name, addr=None, kind="luxdrop", cert_fp=None, device_type=None):
        """fp = SHA-256 klice (SPKI). kind: "luxdrop" nebo "localsend" (cert_fp = otisk LocalSend)."""
        self.reload()
        e = self.peers.get(fp.hex(), {"added": time.time()})
        e.update({"name": str(name)[:63], "id": proto.short_id(fp), "last_seen": time.time(), "kind": kind})
        if addr:
            e["last_addr"] = addr
        if cert_fp:
            e["cert_fp"] = cert_fp
        if device_type:
            e["device_type"] = device_type
        self.peers[fp.hex()] = e
        self.save()

    def touch(self, fp, name=None, addr=None):
        self.reload()
        e = self.peers.get(fp.hex())
        if e is None:
            return
        e["last_seen"] = time.time()
        if name:
            e["name"] = str(name)[:63]
        if addr:
            e["last_addr"] = addr
        self.save()

    def remove(self, key):
        """Odebere podle celeho otisku, kratkeho ID nebo jmena; vrati pocet odebranych."""
        self.reload()
        hits = self.find(key)
        for fp_hex, _e in hits:
            del self.peers[fp_hex]
        if hits:
            self.save()
        return len(hits)

    def find(self, key):
        """Najde zarizeni podle otisku, kratkeho ID (prefix) nebo jmena."""
        self.reload()
        k = key.strip().lower().replace(" ", "").replace(":", "")
        out = []
        for fp_hex, e in self.peers.items():
            if (len(k) >= 8 and fp_hex.startswith(k)) or e.get("name", "").lower() == key.strip().lower():
                out.append((fp_hex, e))
        return out

    def names(self):
        self.reload()
        return {e.get("name", "").lower() for e in self.peers.values()}


class History:
    def __init__(self, directory=None):
        self.dir = directory or identity.data_dir()
        self.path = os.path.join(self.dir, "history.json")

    def items(self):
        return [e for e in _load_json(self.path, []) if isinstance(e, dict)]

    def add(self, entry):
        items = self.items()
        entry = dict(entry, time=time.time())
        items.insert(0, entry)
        identity.ensure_private_dir(self.dir)
        _save_json(self.path, items[:HISTORY_MAX])

    def clear(self):
        _save_json(self.path, [])
