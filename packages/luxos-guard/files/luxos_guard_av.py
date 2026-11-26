"""Lux Guard - antivirus: kontrola souboru zvenku databazi signatur ClamAV a karantena.

ClamAV bezi jen na vyzadani (cil jsou i stare pocitace): clamd s databazi zabere ~1 GB pameti, proto ho
sluzba spusti (luxos-guard-clamd.service) az pro prvni soubor ke kontrole a po IDLE_STOP s bez prace ho
zase zastavi. Databazi aktualizuje luxos-guard-freshclam.timer (jednou denne).

Kontroluje se:
- kazdy soubor zvenku po zapisu (Stazene, prilohy, vymenna media, soubor s user.xdg.origin.url), nejen
  programy - i dokumenty s makry, archivy, PDF, programy pro Windows,
- programy z vymennych medii pri spusteni,
- na vyzadani (`luxos-guard scan --virus CESTA`) a jednou tydne slozky Stazene, Plocha a Dokumenty.

Nalez = karantena: soubor se presune do /var/lib/luxos-guard/quarantine (root 0700, obsah 0600, bez prav
spusteni), uzivatel dostane upozorneni a muze ho obnovit nebo smazat (`luxos-guard quarantine`).

Soubor se clamd predava jako otevreny popisovac (prikaz FILDES pres soket UNIX): clamd bezi jako uzivatel
clamav a soubory uzivatelu by sam neprecetl; cesta se mu neposila, takze ji nemuze nikdo podvrhnout.
"""
import array
import json
import os
import pwd
import re
import socket
import stat
import subprocess
import threading
import time

import luxos_guard_core as core

CONF = "/etc/luxos/guard.conf"
# vlastni adresar clamd (bezi jako clamav, do /run/luxos-guard 0700 root nesmi); sluzba Guardu je root
CLAMD_SOCKET = "/run/luxos-guard-clamd/clamd.sock"
CLAMD_UNIT = "luxos-guard-clamd.service"
QUARANTINE = core.STATE_DIR + "/quarantine"
DB_DIRS = ("/var/lib/clamav",)
MAX_SIZE = 200 * 1024 * 1024    # vetsi soubory clamd stejne nekontroluje cele (StreamMaxLength, MaxFileSize)
IDLE_STOP = 300                 # s bez kontroly -> clamd se zastavi (uvolni ~1 GB)
START_TIMEOUT = 180             # s - nacteni databaze na starem pocitaci
SCAN_TIMEOUT = 120              # s na jeden soubor
RETRY_AFTER = 600               # s - clamd nenabehl (napr. jeste neni databaze): dalsi pokus az potom
MAX_QUARANTINE = 500

CLEAN = "clean"
INFECTED = "infected"
ERROR = "error"

_REPLY = re.compile(r"^(?:fd\[\d+\]|stream|[^:]*):\s*(.*?)\s*(FOUND|OK|ERROR)$")


def enabled(path=CONF):
    """ANTIVIRUS=yes|no v /etc/luxos/guard.conf (vychozi zapnuto, kdyz je ClamAV nainstalovany)."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key.strip() == "ANTIVIRUS":
                    return value.strip().strip("'\"").lower() not in ("no", "0", "false", "off")
    except OSError:
        pass
    return True


def installed():
    return os.path.exists("/usr/bin/clamd")


def has_database(dirs=DB_DIRS):
    """Aspon jedna databaze signatur (main/daily/bytecode .cvd/.cld) - jinak clamd nenabehne."""
    for d in dirs:
        try:
            if any(n.endswith((".cvd", ".cld")) for n in os.listdir(d)):
                return True
        except OSError:
            pass
    return False


def parse_reply(text):
    """Odpoved clamd -> (CLEAN|INFECTED|ERROR, nazev signatury nebo chyba)."""
    text = text.strip("\0\n ")
    m = _REPLY.match(text)
    if not m:
        return ERROR, text[:200]
    detail, status = m.group(1), m.group(2)
    if status == "OK":
        return CLEAN, ""
    if status == "FOUND":
        return INFECTED, detail[:200]
    return ERROR, detail[:200]


def systemctl(action, unit=CLAMD_UNIT):
    try:
        return subprocess.run(["systemctl", "--no-ask-password", action, unit], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=START_TIMEOUT).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class Clamd:
    """Spojeni s clamd na vyzadani. Vlaknove bezpecne: kontroly jdou postupne (clamd sam pracuje paralelne,
    ale stary pocitac by vic soubeznych kontrol zpomalilo)."""

    def __init__(self, sock_path=CLAMD_SOCKET, start=None, stop=None, clock=time.monotonic, idle=IDLE_STOP,
                 start_timeout=START_TIMEOUT):
        self.sock_path = sock_path
        self.start = start or (lambda: systemctl("start"))
        self.stop = stop or (lambda: systemctl("stop"))
        self.clock = clock
        self.idle = idle
        self.start_timeout = start_timeout
        self.lock = threading.Lock()
        self.last_use = None        # None = nespustili jsme ho (nebo uz je zastaveny)
        self.fail_until = 0         # po neuspesnem spusteni se dalsi soubory hned hlasi jako chyba
        self.adopted = False        # clamd spusteny predchozi instanci sluzby (restart, aktualizace)
        self.stats = {"scanned": 0, "infected": 0, "errors": 0, "starts": 0}

    def _connect(self, timeout=SCAN_TIMEOUT):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
        s.settimeout(timeout)
        try:
            s.connect(self.sock_path)
        except OSError:
            s.close()
            raise
        return s

    @staticmethod
    def _reply(s):
        data = b""
        while not data.endswith(b"\0"):
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > 65536:
                break
        return data.decode("utf-8", "replace")

    def ping(self):
        try:
            with self._connect(5) as s:
                s.sendall(b"zPING\0")
                return self._reply(s).strip("\0\n ") == "PONG"
        except OSError:
            return False

    def _ensure(self):
        if self.ping():
            return True
        if self.clock() < self.fail_until:
            return False
        self.stats["starts"] += 1
        if self.start():
            deadline = self.clock() + self.start_timeout
            while self.clock() < deadline:
                if self.ping():
                    return True
                time.sleep(0.5)
        self.fail_until = self.clock() + RETRY_AFTER
        return False

    def scan_fd(self, fd):
        """Obsah otevreneho souboru -> (CLEAN|INFECTED|ERROR, detail)."""
        with self.lock:
            if not self._ensure():
                self.stats["errors"] += 1
                return ERROR, "clamd is not available"
            self.last_use = self.clock()
            try:
                with self._connect() as s:
                    s.sendall(b"zFILDES\0")
                    s.sendmsg([b"\0"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))])
                    result = parse_reply(self._reply(s))
            except OSError as e:
                result = (ERROR, str(e))
            self.last_use = self.clock()
        self.stats["scanned"] += 1
        if result[0] == INFECTED:
            self.stats["infected"] += 1
        elif result[0] == ERROR:
            self.stats["errors"] += 1
        return result

    def scan_path(self, path):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        except OSError as e:
            return ERROR, str(e)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return CLEAN, ""
            return self.scan_fd(fd)
        finally:
            os.close(fd)

    def tick(self):
        """Volat obcas (sluzba kazdou sekundu): clamd bez prace se po IDLE_STOP s zastavi."""
        with self.lock:
            if not self.adopted:
                # bezi z doby pred restartem sluzby: zastavit ho po IDLE_STOP s jako vlastni
                self.adopted = True
                if self.last_use is None and self.ping():
                    self.last_use = self.clock()
            if self.last_use is not None and self.clock() - self.last_use >= self.idle:
                self.last_use = None
                self.stop()
                return True
        return False


def should_scan(st):
    return stat.S_ISREG(st.st_mode) and 0 < st.st_size <= MAX_SIZE


# ---- karantena ---------------------------------------------------------------------------------------

class Quarantine:
    """Soubory s nalezem: obsah v QUARANTINE/<id> (0600 root, bez prav spusteni), udaje v <id>.json."""

    def __init__(self, root=QUARANTINE, clock=time.time):
        self.root = root
        self.clock = clock
        self.lock = threading.Lock()

    def _dir(self):
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        os.chmod(self.root, 0o700)
        return self.root

    def _new_id(self):
        return "%d-%s" % (int(self.clock() * 1000), os.urandom(4).hex())

    def put(self, fd, path, signature, uid):
        """Zkopiruje obsah z fd do karanteny a smaze puvodni soubor. Vraci zaznam nebo None."""
        with self.lock:
            d = self._dir()
            qid = self._new_id()
            target = os.path.join(d, qid)
            st = os.fstat(fd)
            out = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            try:
                offset = 0
                while True:
                    chunk = os.pread(fd, 1 << 20, offset)
                    if not chunk:
                        break
                    os.write(out, chunk)
                    offset += len(chunk)
            finally:
                os.close(out)
            entry = {"id": qid, "path": path, "signature": signature, "uid": uid, "size": st.st_size,
                     "mode": stat.S_IMODE(st.st_mode) & ~0o111, "time": int(self.clock())}
            core_write_json(os.path.join(d, qid + ".json"), entry)
            removed = False
            try:
                # puvodni soubor jen kdyz je to porad ten samy (dev, ino) - cesta se mohla mezitim zmenit
                cur = os.lstat(path)
                if (cur.st_dev, cur.st_ino) == (st.st_dev, st.st_ino):
                    os.unlink(path)
                    removed = True
            except OSError:
                pass
            if not removed:
                # nesmazany original: aspon bez prava spusteni
                try:
                    os.fchmod(fd, stat.S_IMODE(st.st_mode) & ~0o111)
                except OSError:
                    pass
            entry["removed"] = removed
            core_write_json(os.path.join(d, qid + ".json"), entry)
            self._trim()
            return entry

    def list(self, uid=None):
        out = []
        try:
            names = os.listdir(self.root)
        except OSError:
            return out
        for n in names:
            if not n.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.root, n), encoding="utf-8") as f:
                    e = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(e, dict) and (uid is None or uid == 0 or e.get("uid") == uid):
                out.append(e)
        return sorted(out, key=lambda e: e.get("time", 0), reverse=True)

    def get(self, qid, uid=None):
        if not re.fullmatch(r"\d+-[0-9a-f]{8}", qid or ""):
            return None
        for e in self.list(uid):
            if e.get("id") == qid:
                return e
        return None

    def delete(self, qid, uid=None):
        with self.lock:
            e = self.get(qid, uid)
            if e is None:
                return False
            for n in (qid, qid + ".json"):
                try:
                    os.unlink(os.path.join(self.root, n))
                except OSError:
                    pass
            return True

    def restore(self, qid, uid=None, home_of=None):
        """Vrati soubor na puvodni misto (jen kdyz tam nic neni) jako majitel uid, bez prav spusteni.
        Vraci cestu nebo None."""
        with self.lock:
            e = self.get(qid, uid)
            if e is None:
                return None
            path = e.get("path") or ""
            owner = e.get("uid")
            if not path.startswith("/") or "\0" in path:
                return None
            # obnovit jen do domova vlastnika nebo na vymenne medium (ne treba do /etc)
            home = home_of(owner) if home_of else None
            if not ((home and path.startswith(home.rstrip("/") + "/")) or path.startswith(core.REMOVABLE_ROOTS)):
                return None
            parent = os.path.dirname(path)
            try:
                dfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            except OSError:
                return None
            try:
                pst = os.fstat(dfd)
                if owner is not None and pst.st_uid not in (owner, 0):
                    return None
                name = os.path.basename(path)
                out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                              e.get("mode", 0o644) & 0o666, dir_fd=dfd)
                try:
                    with open(os.path.join(self.root, qid), "rb") as src:
                        while True:
                            chunk = src.read(1 << 20)
                            if not chunk:
                                break
                            os.write(out, chunk)
                    # sluzba bezi s UMask 0077 a jako root: prava a skupina vyslovne (puvodni bez spusteni)
                    os.fchmod(out, e.get("mode", 0o644) & 0o666)
                    if owner is not None:
                        try:
                            gid = pwd.getpwuid(owner).pw_gid
                        except KeyError:
                            gid = -1
                        os.fchown(out, owner, gid)
                finally:
                    os.close(out)
            except OSError:
                return None
            finally:
                os.close(dfd)
            for n in (qid, qid + ".json"):
                try:
                    os.unlink(os.path.join(self.root, n))
                except OSError:
                    pass
            return path

    def _trim(self):
        entries = self.list()
        for e in entries[MAX_QUARANTINE:]:
            for n in (e["id"], e["id"] + ".json"):
                try:
                    os.unlink(os.path.join(self.root, n))
                except OSError:
                    pass


def core_write_json(path, obj):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)
