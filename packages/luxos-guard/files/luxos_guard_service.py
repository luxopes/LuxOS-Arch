"""Lux Guard - sluzba (root): fanotify v jadre, analyza novych souboru a rozhodovani o spusteni.

Dve skupiny fanotify:
  notif (FAN_CLASS_NOTIF, asynchronni): FAN_CLOSE_WRITE na pripojenich s /home, /tmp,
      /dev/shm. Zapisujici proces se nikdy neblokuje. Vlakno ctecky udalost rychle odfiltruje
      (cesta, prvnich 64 B obsahu); jen spustitelny obsah jde do vlakna analyzy (puvod, pravidla, SHA-256).
  perm (FAN_CLASS_CONTENT, povoleni): znacky jen na INODE hlidanych souboru - FAN_OPEN_EXEC_PERM
      (execve), u skriptu i FAN_OPEN_PERM (bash skript.sh soubor jen otevre). Bezne programy
      a soubory tedy nic nestoji. Vymenna media (/run/media ...) maji znacku na celem pripojeni
      (soubory na USB nikdo nezapsal, nejsou predem znamy) - otevreni neinterpretem se povoli hned.

Udalost povoleni se drzi, dokud nerozhodne pravidlo nebo uzivatel (dotaz pres luxos-guard-agent
v jeho sezeni); bez odpovedi do ASK_TIMEOUT se spusteni zamitne. Kdyz sluzba skonci, jadro
cekajici udalosti povoli (fanotify) - systemd ji proto restartuje (Restart=always).
"""
import ctypes
import ctypes.util
import errno
import heapq
import json
import os
import queue
import re
import select
import socket
import stat
import struct
import sys
import threading
import time

import luxos_guard_av as av
import luxos_guard_core as core
import luxos_guard_rules as rules

# ---- fanotify (linux/fanotify.h) ----------------------------------------------------------------
FAN_CLOEXEC = 0x1
FAN_NONBLOCK = 0x2
FAN_CLASS_NOTIF = 0x0
FAN_CLASS_CONTENT = 0x4
FAN_UNLIMITED_QUEUE = 0x10
FAN_UNLIMITED_MARKS = 0x20
FAN_CLOSE_WRITE = 0x8
FAN_Q_OVERFLOW = 0x4000
FAN_OPEN_PERM = 0x10000
FAN_OPEN_EXEC_PERM = 0x40000
FAN_MARK_ADD = 0x1
FAN_MARK_REMOVE = 0x2
FAN_MARK_DONT_FOLLOW = 0x4
FAN_MARK_MOUNT = 0x10
FAN_ALLOW = 0x1
FAN_DENY = 0x2
FAN_NOFD = -1
AT_FDCWD = -100
METADATA_VERSION = 3
_META = struct.Struct("=IBBHQii")
_RESP = struct.Struct("=iI")
O_LARGEFILE = 0o100000

MIN_COPY_SIZE = 16   # bajtu; mensi soubory (prazdne, jen shebang) se jako kopie oznaceneho souboru neposuzuji

PERM_EXEC = FAN_OPEN_EXEC_PERM
PERM_OPEN = FAN_OPEN_PERM


class Fanotify:
    """Tenka obalka nad fanotify_init/fanotify_mark (ctypes)."""

    def __init__(self, init_flags, event_flags=os.O_RDONLY | O_LARGEFILE | os.O_CLOEXEC):
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        self._init = libc.fanotify_init
        self._init.argtypes = (ctypes.c_uint, ctypes.c_uint)
        self._init.restype = ctypes.c_int
        self._mark = libc.fanotify_mark
        self._mark.argtypes = (ctypes.c_int, ctypes.c_uint, ctypes.c_uint64, ctypes.c_int, ctypes.c_char_p)
        self._mark.restype = ctypes.c_int
        fd = self._init(init_flags, event_flags)
        if fd < 0:
            e = ctypes.get_errno()
            raise OSError(e, "fanotify_init: " + os.strerror(e))
        self.fd = fd

    def fileno(self):
        return self.fd

    def mark(self, flags, mask, dirfd=AT_FDCWD, path=None):
        p = os.fsencode(path) if path is not None else None
        if self._mark(self.fd, flags, mask, dirfd, p) < 0:
            e = ctypes.get_errno()
            raise OSError(e, f"fanotify_mark {path or dirfd}: " + os.strerror(e))

    def read(self, size=24 * 1024):
        """[(mask, fd, pid)]; prazdny seznam, kdyz nic neceka (FAN_NONBLOCK)."""
        try:
            buf = os.read(self.fd, size)
        except BlockingIOError:
            return []
        except InterruptedError:
            return []
        out = []
        off = 0
        while off + _META.size <= len(buf):
            event_len, vers, _r, _ml, mask, fd, pid = _META.unpack_from(buf, off)
            if vers != METADATA_VERSION or event_len < _META.size:
                break
            out.append((mask, fd, pid))
            off += event_len
        return out

    def respond(self, fd, allow):
        os.write(self.fd, _RESP.pack(fd, FAN_ALLOW if allow else FAN_DENY))

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def fd_path(fd):
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return None


def close_fd(fd):
    if fd is not None and fd >= 0:
        try:
            os.close(fd)
        except OSError:
            pass


# ---- pripojeni --------------------------------------------------------------------------------
WATCH_PATHS = ("/home", "/tmp", "/var/tmp", "/dev/shm")
WATCH_PREFIXES = ("/home/", "/tmp/", "/var/tmp/", "/dev/shm/", "/root/") + core.REMOVABLE_ROOTS
SKIP_FS = {"proc", "sysfs", "devpts", "cgroup", "cgroup2", "debugfs", "tracefs", "securityfs", "pstore",
           "bpf", "configfs", "fusectl", "mqueue", "hugetlbfs", "autofs", "binfmt_misc", "efivarfs", "nsfs",
           "ramfs", "squashfs", "iso9660", "overlay", "fuse.gvfsd-fuse", "fuse.portal", "fuse.gocryptfs"}
# .git/hooks/*.sample (git init/clone je kopiruje ze sablony systemu; spousti se jen hooky bez .sample)
GIT_HOOK_SAMPLE = re.compile(r"/\.git/(?:worktrees/[^/]+/)?hooks/[^/]+\.sample$|/[^/]+\.git/hooks/[^/]+\.sample$")
TEMP_DOWNLOAD = re.compile(r"\.(?:part|crdownload|download|partial|tmp)$|/\.[^/]*\.part$|Unconfirmed \d+")


MOUNT_ESCAPE = re.compile(r"\\([0-7]{3})")


def unescape_mount(text):
    """Jadro v mountinfo koduje mezeru, tabulator, novy radek a zpetne lomitko oktalove (\\040 \\011 \\012
    \\134). Drive se dekodovala jen mezera - USB s takovym znakem v nazvu se pak nedalo hlidat."""
    return MOUNT_ESCAPE.sub(lambda m: chr(int(m.group(1), 8)), text)


def read_mounts(path="/proc/self/mountinfo"):
    """[(bod pripojeni, typ FS)]"""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                try:
                    sep = parts.index("-")
                except ValueError:
                    continue
                out.append((unescape_mount(parts[4]), parts[sep + 1]))
    except OSError:
        pass
    return out


def mount_of(path, mounts):
    best = None
    for mp, fs in mounts:
        if path == mp or path.startswith(mp.rstrip("/") + "/"):
            if best is None or len(mp) >= len(best[0]):
                best = (mp, fs)
    return best


def watch_mounts(mounts):
    """Body pripojeni s FAN_CLOSE_WRITE (kazde jen jednou). Korenove pripojeni "/" jen tehdy, kdyz na nem
    lezi /home (jinak by kvuli /var/tmp chodily udalosti o kazdem zapisu systemu, napr. pri aktualizaci)."""
    out = []
    home = mount_of("/home", mounts)
    for p in WATCH_PATHS:
        m = mount_of(p, mounts)
        if not m or m[1] in SKIP_FS or m[0] in out:
            continue
        if m[0] == "/" and not (home and home[0] == "/"):
            continue
        out.append(m[0])
    return out


def removable_mounts(mounts):
    return [mp for mp, fs in mounts if mp.startswith(core.REMOVABLE_ROOTS) and fs not in SKIP_FS]


# ---- klient na socketu ------------------------------------------------------------------------
# Socket je 0666 (prikazy luxos-guard pro kazdeho uzivatele), takze vse od klienta je neduveryhodne:
# omezeny pocet spojeni, predanych deskriptoru i neodeslanych odpovedi; hlavni smycka nikdy neceka
# na socket klienta (na ni cekaji odpovedi fanotify = spousteni programu v celem systemu).
MAX_CLIENTS = 128               # vsech spojeni
MAX_CLIENTS_PER_UID = 32        # jednoho uzivatele (root bez limitu)
MAX_CLIENT_FDS = 2              # predane soubory cekajici na prikaz allow/check
MAX_CLIENT_OUT = 256 * 1024     # neodeslane odpovedi navic k jedne cekajici; vic = klient necte -> odpojit


class Client:
    def __init__(self, sock, uid, pid, gid=None, pidfd=None):
        self.sock = sock
        self.uid = uid
        self.pid = pid
        self.gid = gid
        self.pidfd = pidfd          # SO_PEERPIDFD: presne proces, ktery se pripojil (ne jen cislo PID)
        self.buf = b""
        self.out = b""
        self.fds = []
        self.agent = False
        self.closed = False
        self.broken = False         # necte odpovedi / chyba socketu: smycka serve() ho odpoji
        self.pollout = False        # smycka hlida i POLLOUT (ceka neodeslana odpoved)

    def send(self, obj):
        """Bez blokovani: co se nevejde do socketu, ceka v self.out (odesle smycka pri POLLOUT)."""
        if self.closed or self.broken:
            return False
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode()
        if self.out and len(self.out) + len(data) > MAX_CLIENT_OUT:
            # predchozi odpovedi porad necte (jedna velka odpoved, napr. "list", projde vzdy)
            self.broken = True
            self.out = b""
            return False
        self.out += data
        return self.flush()

    def flush(self):
        while self.out:
            try:
                n = self.sock.send(self.out, socket.MSG_DONTWAIT | socket.MSG_NOSIGNAL)
            except (BlockingIOError, InterruptedError):
                return True
            except OSError:
                self.broken = True
                self.out = b""
                return False
            self.out = self.out[n:]
        return True

    def add_fds(self, fds):
        for fd in fds:
            if len(self.fds) < MAX_CLIENT_FDS:
                self.fds.append(fd)
            else:
                close_fd(fd)

    def close(self):
        self.closed = True
        for fd in self.fds:
            close_fd(fd)
        self.fds = []
        close_fd(self.pidfd)
        self.pidfd = None
        try:
            self.sock.close()
        except OSError:
            pass


# ---- sluzba ------------------------------------------------------------------------------------------
class Delayed:
    """Odlozene ulohy (stahovani pod docasnym jmenem: znovu za 3 s, az ma soubor konecne jmeno) v jednom
    vlakne s frontou. Drive vlakno (threading.Timer) na kazdou udalost: davka zapisu *.tmp/*.part
    vytvorila stovky vlaken a pri selhani clone() ("can't start new thread", 17. 11. 2026 soucasne
    s padem scx_lavd) se udalost ztratila. Plna fronta = uloha se zahodi a zapocita jako preteceni."""
    LIMIT = 1024

    def __init__(self, deliver, clock=time.monotonic, limit=LIMIT):
        self.deliver = deliver
        self.clock = clock
        self.limit = limit
        self.heap = []
        self.seq = 0
        self.cond = threading.Condition()

    def add(self, delay, job):
        with self.cond:
            if len(self.heap) >= self.limit:
                return False
            heapq.heappush(self.heap, (self.clock() + delay, self.seq, job))
            self.seq += 1
            self.cond.notify()
        return True

    def pending(self):
        with self.cond:
            return len(self.heap)

    def due(self):
        """Ulohy, jejichz cas uz nastal (vyjme je z fronty)."""
        out = []
        with self.cond:
            now = self.clock()
            while self.heap and self.heap[0][0] <= now:
                out.append(heapq.heappop(self.heap)[2])
        return out

    def run_once(self, max_wait=None):
        """Pocka na nejblizsi ulohu (nejvys max_wait s) a preda vsechny splatne; vraci jejich pocet."""
        with self.cond:
            if not self.heap:
                self.cond.wait(max_wait)
            if self.heap:
                wait = self.heap[0][0] - self.clock()
                if wait > 0:
                    self.cond.wait(wait if max_wait is None else min(wait, max_wait))
        jobs = self.due()
        for job in jobs:
            try:
                self.deliver(job)
            except Exception as e:  # noqa: BLE001 - vlakno nesmi skoncit
                log(f"delayed job error: {e}")
        return len(jobs)

    def run(self):
        while True:
            self.run_once()


class Guard:
    """Rozhodovani o udalostech. fan_perm/fan_notif jsou objekty s rozhranim Fanotify (v testech nahrady)."""

    def __init__(self, fan_perm, fan_notif=None, state=None, proc=None, users=None, clock=time.time,
                 classify_limit=rules.MAX_READ, agent_check=None, clamd=None, quarantine=None):
        self.perm = fan_perm
        self.notif = fan_notif
        self.state = state or core.State()
        self.proc = proc or core.Proc()
        self.users = users or core.Users()
        self.clock = clock
        self.pid = os.getpid()
        self.classify_limit = classify_limit
        self.removable = set()      # body pripojeni vymennych medii se znackou na celem pripojeni
        self.clean_cache = {}       # soubory na USB bez spustitelneho obsahu: klic -> mtime
        self.pending = {}           # klic -> [(mask, fd, pid, t)] - ceka na dokonceni analyzy
        self.analyzing = set()      # klice, ktere prave analyzuje vlakno analyzy
        self.asks = {}              # id -> dotaz
        self.ask_index = {}         # (uid, klic) -> id
        self.next_id = 1
        self.denied = {}            # (uid, klic) -> do kdy zamitat bez dotazu
        self.exec_ok = {}           # (pid, klic) -> do kdy povolit (interpret po povolenem execve)
        self.agents = {}            # uid -> [Client] - jen overene pomocniky (agent_check)
        # Overeni pomocnika v sezeni: kdo se prohlasi za "agent", musi to byt skutecny luxos-guard-agent
        # (jinak by si kazdy program uzivatele mohl sam odpovidat "Presto spustit")
        self.agent_check = agent_check or (lambda c: core.agent_peer_ok(c.pid, c.uid, c.gid, c.pidfd))
        self.jobs = queue.Queue(maxsize=4096)
        self.results = queue.Queue()
        self.wake_r, self.wake_w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.lock = threading.Lock()
        self.delayed = Delayed(self._queue)
        self.stats = {"perm_events": 0, "notif_events": 0, "analyzed": 0, "flagged": 0, "overflows": 0,
                      "virus_scanned": 0, "virus_found": 0}
        # antivirus (ClamAV na vyzadani, luxos_guard_av): vlastni fronta a vlakno - spusteni clamd trva az
        # minuty a nesmi zdrzet analyzu programu (spusteni ceka na jeji vysledek)
        self.clamd = clamd
        self.quarantine = quarantine or av.Quarantine()
        self.av_jobs = queue.Queue(maxsize=4096)

    # ---- znacky
    def mark_inode(self, fd, kind, add=True, path=None):
        """Znacka na inode podle fd (nebo podle cesty bez nasledovani symlinku, kdyz fd je None)."""
        ex, op = core.mark_mask_for(kind)
        mask = (PERM_EXEC if ex else 0) | (PERM_OPEN if op else 0)
        try:
            if fd is None:
                self.perm.mark((FAN_MARK_ADD if add else FAN_MARK_REMOVE) | FAN_MARK_DONT_FOLLOW, mask, AT_FDCWD, path)
            else:
                self.perm.mark(FAN_MARK_ADD if add else FAN_MARK_REMOVE, mask, fd, None)
            return True
        except OSError as e:
            if add or e.errno not in (errno.ENOENT,):
                log(f"mark {'add' if add else 'remove'} failed: {e}")
            return False

    def unmark_inode(self, fd):
        # odstranit obe masky (podle druhu mohla byt jen jedna - ENOENT nevadi)
        for mask in (PERM_EXEC | PERM_OPEN, PERM_EXEC, PERM_OPEN):
            try:
                self.perm.mark(FAN_MARK_REMOVE, mask, fd, None)
                return
            except OSError:
                continue

    # ---- udalosti povoleni (hlavni vlakno)
    def respond(self, fd, allow):
        try:
            self.perm.respond(fd, allow)
        except OSError as e:
            log(f"respond failed: {e}")
        close_fd(fd)

    def on_perm(self, mask, fd, pid):
        self.stats["perm_events"] += 1
        if fd < 0:
            return
        if pid == self.pid:
            self.respond(fd, True)
            return
        try:
            st = os.fstat(fd)
        except OSError:
            self.respond(fd, True)
            return
        key = (st.st_dev, st.st_ino)
        entry = self.state.get(key)
        is_exec = bool(mask & PERM_EXEC)
        if entry is None:
            if key in self.analyzing or key in self.pending:
                self.pending.setdefault(key, []).append((mask, fd, pid, self.clock()))
                return
            if self._on_removable(fd):
                entry = self._classify_removable(fd, st, key, is_exec, pid)
            if entry is None:
                self.respond(fd, True)       # neznamy soubor (stara znacka, bezne otevreni na USB)
                return
        if is_exec:
            intent = "sandbox" if core.in_sandbox(self.proc, pid) else "exec"
        else:
            intent = core.opener_intent(self.proc, pid, key, entry.get("kind"),
                                        strict=entry.get("level") == core.CRITICAL)
        if intent == "exec" and not is_exec:
            until = self.exec_ok.get((pid, key))
            if until and until > self.clock():
                self.respond(fd, True)       # interpret prave povoleneho skriptu (./skript -> bash skript)
                return
        action = core.decide(entry, intent)
        uid = self.proc.uid(pid)
        if uid is None:
            uid = entry.get("uid")
        if action == core.ALLOW:
            if intent == "exec":
                self.exec_ok[(pid, key)] = self.clock() + core.EXEC_MEMORY
            self.respond(fd, True)
            return
        if action == core.DENY:
            self.respond(fd, False)
            self._blocked(entry, key, uid, pid, intent)
            return
        # ASK
        until = self.denied.get((uid, key))
        if until and until > self.clock():
            self.respond(fd, False)
            return
        self._ask(entry, key, uid, mask, fd, pid)

    def _on_removable(self, fd):
        if not self.removable:
            return False
        p = fd_path(fd) or ""
        return any(p.startswith(m.rstrip("/") + "/") for m in self.removable)

    def _classify_removable(self, fd, st, key, is_exec, pid):
        """Soubor na USB: analyza az pri spusteni. Otevreni programem, ktery neni interpret, se povoli hned."""
        if not is_exec and core.exe_family(self.proc.exe(pid)) is None:
            return None
        if not stat.S_ISREG(st.st_mode) or self.clean_cache.get(key) == st.st_mtime_ns:
            return None
        path = fd_path(fd) or ""
        try:
            data = os.pread(fd, min(self.classify_limit, 4 << 20), 0)
        except OSError:
            return None
        verdict = rules.classify(data, os.path.basename(path))
        if verdict is None:
            if len(self.clean_cache) > 20000:
                self.clean_cache.clear()
            self.clean_cache[key] = st.st_mtime_ns
            return None
        mount = next((m for m in self.removable if path.startswith(m.rstrip("/") + "/")), None)
        entry = core.make_entry(path, st, verdict, ("removable", mount), self.proc.uid(pid) or st.st_uid)
        sha = None
        if st.st_size <= 64 << 20:
            try:
                sha = core.sha256_fd(fd)
            except OSError:
                sha = None
        entry["sha256"] = sha
        entry["mount_mark"] = True
        if not verdict.critical and self.state.is_allowed(sha):
            entry["status"] = core.ALLOWED
        self.state.put(key, entry)
        log(f"{entry['level']}: {path} ({verdict.kind}{'; ' + ', '.join(verdict.reasons) if verdict.reasons else ''})")
        return entry

    def _blocked(self, entry, key, uid, pid, intent):
        until = self.denied.get((uid, key))
        quiet = bool(until and until > self.clock())
        self.denied[(uid, key)] = self.clock() + core.DENY_MEMORY
        if quiet:
            return
        comm = self.proc.comm(pid) or "?"
        log(f"blocked {entry.get('level')} {entry.get('path')} (by {comm}[{pid}], uid {uid}): "
            f"{', '.join(entry.get('reasons') or []) or 'not allowed'}")
        self.state.add_log(path=entry.get("path"), level=entry.get("level"), action="blocked", uid=uid,
                           reasons=entry.get("reasons"))
        self._to_agent(uid, {"op": "blocked", "terminal": self.proc.has_tty(pid), **self._public(entry)})

    def _public(self, entry):
        return {"path": entry.get("path"), "level": entry.get("level"), "kind": entry.get("kind"),
                "interp": entry.get("interp"), "reasons": entry.get("reasons") or [],
                "notes": entry.get("notes") or [], "origin": entry.get("origin"),
                "origin_detail": entry.get("origin_detail")}

    def _ask(self, entry, key, uid, mask, fd, pid):
        rid = self.ask_index.get((uid, key))
        if rid in self.asks:
            self.asks[rid]["fds"].append(fd)
            return
        agents = self.agents.get(uid) or []
        if not agents:
            log(f"denied {entry.get('path')} (uid {uid}): no session to ask (luxos-guard-agent not running)")
            self.state.add_log(path=entry.get("path"), level=entry.get("level"), action="denied-no-session", uid=uid)
            self.respond(fd, False)
            self.denied[(uid, key)] = self.clock() + 5
            return
        rid = self.next_id
        self.next_id += 1
        self.asks[rid] = {"key": key, "uid": uid, "fds": [fd], "t": self.clock(), "entry": entry,
                          "pid": pid, "fd0": os.dup(fd), "client": None}
        self.ask_index[(uid, key)] = rid
        msg = {"op": "ask", "id": rid, "program": self.proc.comm(pid), "terminal": self.proc.has_tty(pid),
               **self._public(entry)}
        if not self._to_agent(uid, msg):
            self._finish_ask(rid, "deny", reason="agent unreachable")

    def _to_agent(self, uid, msg):
        ok = False
        for c in list(self.agents.get(uid) or []):
            if c.send(msg):
                ok = True
                break       # staci jeden (posledni pripojeny je prvni v seznamu)
        return ok

    def _finish_ask(self, rid, choice, reason=None):
        a = self.asks.pop(rid, None)
        if a is None:
            return
        key, uid, entry = a["key"], a["uid"], a["entry"]
        if self.ask_index.get((uid, key)) == rid:
            self.ask_index.pop((uid, key), None)
        allow = choice == "run" and entry.get("level") != core.CRITICAL
        confirm = a.get("client") is not None      # "luxos-guard allow" potvrzeny v okne pomocnika
        if allow:
            entry["status"] = core.ALLOWED
            entry["allowed_by"] = uid
            self.state.put(key, entry)
            self.state.allow_hash(entry.get("sha256"), uid, entry.get("path"))
            if not entry.get("mount_mark"):
                self.unmark_inode(a["fd0"])
            if not confirm:
                self.exec_ok[(a["pid"], key)] = self.clock() + core.EXEC_MEMORY
        elif not confirm:
            self.denied[(uid, key)] = self.clock() + core.DENY_MEMORY
        close_fd(a["fd0"])
        for fd in a["fds"]:
            self.respond(fd, allow)
        if confirm and not a["client"].closed:
            a["client"].send({"op": "allow", "ok": True} if allow else {"op": "error", "error": "not confirmed"})
        action = "allowed" if allow else {"sandbox": "sandbox", "trash": "trash"}.get(choice, "denied")
        log(f"{action}: {entry.get('path')} (uid {uid}){' - ' + reason if reason else ''}")
        self.state.add_log(path=entry.get("path"), level=entry.get("level"), action=action, uid=uid)

    def tick(self):
        """Casove limity: nezodpovezene dotazy, cekani na analyzu, stare zaznamy pameti."""
        t = self.clock()
        for rid, a in list(self.asks.items()):
            if t - a["t"] > core.ASK_TIMEOUT:
                self._finish_ask(rid, "deny", reason="no answer")
        for key, waiters in list(self.pending.items()):
            if key in self.analyzing:
                # analyza trva prilis dlouho (obrovsky soubor, pretizeni): radeji zamitnout
                old = [w for w in waiters if t - w[3] > 15]
                if not old:
                    continue
                self.pending[key] = [w for w in waiters if w not in old]
                for _mask, fd, pid, _t in old:
                    log(f"denied {fd_path(fd)}: analysis did not finish in time")
                    self.respond(fd, False)
                continue
            self.pending.pop(key, None)
            for mask, fd, pid, _t in waiters:
                self.on_perm(mask, fd, pid)
        for d in (self.denied, self.exec_ok):
            for k, until in list(d.items()):
                if until < t:
                    d.pop(k, None)

    # ---- odpovedi a prikazy klientu
    def on_message(self, client, msg):
        op = msg.get("op")
        if not isinstance(op, str):
            return {"op": "error", "error": "unknown op"}
        if op == "hello":
            reply = {"op": "hello", "version": core.VERSION}
            if msg.get("role") == "agent" and not client.agent:
                ok = False
                try:
                    ok = bool(self.agent_check(client))
                except Exception as e:  # noqa: BLE001 - chyba kontroly = neovereny
                    log(f"agent check failed: {e}")
                if ok:
                    client.agent = True
                    lst = self.agents.setdefault(client.uid, [])
                    lst.insert(0, client)
                else:
                    log(f"refused agent role for pid {client.pid} (uid {client.uid}): not luxos-guard-agent")
                reply["agent"] = ok
            elif client.agent:
                reply["agent"] = True
            return reply
        if op == "answer":
            rid = msg.get("id")
            a = self.asks.get(rid) if type(rid) is int else None
            if a is None or not client.agent or (a["uid"] != client.uid and client.uid != 0):
                return {"op": "error", "error": "unknown request"}
            choice = msg.get("choice")
            if choice not in ("run", "sandbox", "deny", "trash"):
                choice = "deny"
            self._finish_ask(rid, choice)
            return None
        if op == "status":
            items, _log = self.state.for_uid(client.uid)
            return {"op": "status", "active": True, "version": core.VERSION, "watched": len(items),
                    "critical": sum(1 for e in items if e.get("level") == core.CRITICAL),
                    "agent": bool(self.agents.get(client.uid)), "removable": sorted(self.removable),
                    "antivirus": self.clamd is not None, "quarantine": len(self.quarantine.list(client.uid)),
                    "stats": dict(self.stats) if client.uid == 0 else None}
        if op == "list":
            items, lg = self.state.for_uid(client.uid)
            return {"op": "list", "entries": [{**self._public(e), "status": e.get("status"), "t": e.get("t")}
                                              for e in items], "log": lg}
        if op in ("quarantine", "quarantine_restore", "quarantine_delete"):
            return self._quarantine_op(client, msg)
        if op == "virus_scan":
            if not client.fds:
                return {"op": "error", "error": "no file"}
            fd = client.fds.pop(0)
            try:
                return self._virus_scan_op(client, fd)
            finally:
                close_fd(fd)
        if op in ("allow", "check"):
            if not client.fds:
                return {"op": "error", "error": "no file"}
            fd = client.fds.pop(0)
            try:
                return self._file_op(op, client, fd, msg)
            finally:
                close_fd(fd)
        return {"op": "error", "error": "unknown op"}

    def _file_op(self, op, client, fd, msg):
        try:
            st = os.fstat(fd)
        except OSError:
            return {"op": "error", "error": "bad file"}
        key = (st.st_dev, st.st_ino)
        entry = self.state.get(key)
        if op == "check":
            return {"op": "check", "entry": ({**self._public(entry), "status": entry.get("status")} if entry else None)}
        if entry is None:
            return {"op": "allow", "ok": True, "note": "not watched"}
        if entry.get("level") == core.CRITICAL and not (client.uid == 0 and msg.get("force")):
            return {"op": "error", "error": "critical"}
        if client.uid != 0 and client.uid not in (st.st_uid, entry.get("uid")):
            return {"op": "error", "error": "not yours"}
        if client.uid != 0 and entry.get("status") != core.ALLOWED:
            # Povoleni od uzivatele (ne root) jen potvrzenim v okne overeneho pomocnika v sezeni - program
            # uzivatele by si jinak rizikovy soubor povolil sam (stejne jako "Presto spustit" v dotazu)
            return self._confirm_allow(client, fd, key, entry)
        entry["status"] = core.ALLOWED
        entry["allowed_by"] = client.uid
        if entry.get("level") == core.CRITICAL:
            entry["forced"] = True
        self.state.put(key, entry)
        self.state.allow_hash(entry.get("sha256"), client.uid, entry.get("path"))
        if entry.get("level") == core.CRITICAL:
            # root: vyjimka i pro kriticky soubor - zrusit znacku, jinak by decide() dal zamitalo
            self.state.remove(key)
        if not entry.get("mount_mark"):
            self.unmark_inode(fd)
        log(f"allowed by command: {entry.get('path')} (uid {client.uid})")
        self.state.add_log(path=entry.get("path"), level=entry.get("level"), action="allowed", uid=client.uid)
        return {"op": "allow", "ok": True}

    def _confirm_allow(self, client, fd, key, entry):
        uid = client.uid
        if not self.agents.get(uid):
            return {"op": "error", "error": "no session"}
        rid = self.next_id
        self.next_id += 1
        self.asks[rid] = {"key": key, "uid": uid, "fds": [], "t": self.clock(), "entry": entry,
                          "pid": client.pid, "fd0": os.dup(fd), "client": client}
        msg = {"op": "ask", "id": rid, "program": "luxos-guard allow", "terminal": True, **self._public(entry)}
        if not self._to_agent(uid, msg):
            close_fd(self.asks.pop(rid)["fd0"])
            return {"op": "error", "error": "no session"}
        return None                 # odpoved az po volbe v okne (_finish_ask) nebo po ASK_TIMEOUT

    def drop_client(self, client):
        if client.agent:
            lst = self.agents.get(client.uid) or []
            if client in lst:
                lst.remove(client)
            if not lst:
                self.agents.pop(client.uid, None)
        client.close()

    # ---- zapsane soubory (vlakno ctecky notif) ---------------------------------------------------
    def on_close_write(self, fd, pid):
        """Rychly filtr; vraci True, kdyz si fd prevzala analyza (jinak ho zavre volajici)."""
        self.stats["notif_events"] += 1
        if pid == self.pid:
            return False
        path = fd_path(fd)
        if not path or not path.startswith(WATCH_PREFIXES) or path.endswith(" (deleted)"):
            return False
        if "/" + core.SNAP_DIR_NAME + "/" in path:
            return False
        if GIT_HOOK_SAMPLE.search(path):
            return False                    # vzory hooku gitu: git je nikdy nespousti (jen bez .sample)
        try:
            head = os.pread(fd, 64, 0)
        except OSError:
            return False
        kind = rules.detect_kind(head, os.path.basename(path))
        if kind is None:
            if TEMP_DOWNLOAD.search(path) and head:
                # stahovani pod docasnym jmenem: priponu (.sh) zjistime po prejmenovani (za 3 s, jedno
                # vlakno pro vsechny odlozene ulohy - zadne nove vlakno na udalost)
                if self.delayed.add(3, {"fd": fd, "path": path, "pid": pid, "retry": 1, "info": None}):
                    return True
                self.stats["overflows"] += 1
                return False
            return self._virus_candidate(fd, path, pid)
        return self._candidate(fd, path, pid, kind)

    def _from_outside(self, fd, path):
        """Soubor zvenku (Stazene, prilohy, vymenna media, adresa puvodu od prohlizece) - pro antivirus."""
        if core.location_origin(path, self.users):
            return True
        try:
            os.getxattr(fd, "user.xdg.origin.url")
            return True
        except OSError:
            return False

    def _virus_candidate(self, fd, path, pid):
        """Soubor bez spustitelneho obsahu (dokument, archiv, program pro Windows): jen antivirus."""
        if self.clamd is None or not head_nonempty(fd) or not self._from_outside(fd, path):
            return False
        return self._queue_virus(fd, path)

    def _queue_virus(self, fd, path, uid=None):
        try:
            self.av_jobs.put_nowait({"fd": fd, "path": path, "uid": uid})
            return True
        except queue.Full:
            self.stats["overflows"] += 1
            return False

    def _candidate(self, fd, path, pid, kind):
        try:
            st = os.fstat(fd)
        except OSError:
            return False
        if not stat.S_ISREG(st.st_mode):
            return False
        info = core.writer_info(self.proc, pid)
        loc = core.location_origin(path, self.users)
        quick = loc or core.writer_origin({"exe": info.get("exe"), "comm": info.get("comm")}, self.state,
                                          self.users, path)
        key = (st.st_dev, st.st_ino)
        with self.lock:
            self.analyzing.add(key)
        if quick and self.state.get(key) is None:
            # predbezna znacka hned - spusteni behem analyzy pocka na jeji vysledek
            self.mark_inode(fd, kind[0])
        self._queue({"fd": fd, "path": path, "pid": pid, "kind": kind, "info": info, "loc": loc, "key": key,
                     "premarked": bool(quick)})
        return True

    def _queue(self, job):
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            self.stats["overflows"] += 1
            close_fd(job["fd"])
            if job.get("key"):
                with self.lock:
                    self.analyzing.discard(job["key"])

    # ---- analyza (vlakno analyzy) ----------------------------------------------------------------
    def analyze(self, job):
        fd = job["fd"]
        key = job.get("key")
        try:
            if job.get("retry"):
                path = fd_path(fd)
                if not path or path.endswith(" (deleted)"):
                    return
                head = os.pread(fd, 64, 0)
                kind = rules.detect_kind(head, os.path.basename(path))
                if kind is None:
                    if self.clamd is not None and head and self._from_outside(fd, path):
                        self._queue_virus(os.dup(fd), path)
                    return
                info = core.writer_info(self.proc, job["pid"])
                st = os.fstat(fd)
                key = (st.st_dev, st.st_ino)
                with self.lock:
                    self.analyzing.add(key)
                job = {**job, "path": path, "kind": kind, "info": info, "loc": core.location_origin(path, self.users),
                       "key": key, "premarked": False}
            self._analyze(job, fd, key)
        except OSError as e:
            log(f"analysis of {job.get('path')} failed: {e}")
        finally:
            close_fd(fd)
            if key is not None:
                with self.lock:
                    self.analyzing.discard(key)
                self.post(("done", key))

    def _analyze(self, job, fd, key):
        self.stats["analyzed"] += 1
        path = fd_path(fd) or job["path"]
        st = os.fstat(fd)
        existing = self.state.get(key)
        origin = None
        try:
            url = os.getxattr(fd, "user.xdg.origin.url")
            origin = ("url", url.decode("utf-8", "replace")[:500])
        except OSError:
            pass
        origin = origin or job.get("loc") or core.writer_origin(job.get("info"), self.state, self.users, path)
        sha = None
        # Kopie oznaceneho souboru podle otisku: jen u souboru s obsahem - stejny otisk maji vsechny
        # prazdne/miniaturni soubory (prazdne __init__.py ve venv byly "kopie" prazdneho stazeneho skriptu)
        if origin is None and st.st_size >= MIN_COPY_SIZE and st.st_size in self.state.sizes():
            sha = core.sha256_fd(fd)
            e = self.state.by_hash(sha)
            if e and e.get("status") != core.ALLOWED:
                origin = ("copy", e.get("path"))
        if origin is None and existing:
            origin = (existing.get("origin"), existing.get("origin_detail"))
        if origin is None:
            if job.get("premarked"):
                self.unmark_inode(fd)
            return
        if self.clamd is not None:
            dup = os.dup(fd)
            if not self._queue_virus(dup, path):
                close_fd(dup)
        data = os.pread(fd, self.classify_limit, 0)
        verdict = rules.classify(data, os.path.basename(path))
        if verdict is None:
            if existing:
                self.state.remove(key)
            self.unmark_inode(fd)
            return
        sha = sha or core.sha256_fd(fd)
        uid, _home = self.users.owner_of(path)
        if uid is None:
            uid = st.st_uid
        entry = core.make_entry(path, st, verdict, origin, uid, sha)
        new_critical = verdict.critical and not (existing and existing.get("sha256") == sha)
        if not verdict.critical and (self.state.is_allowed(sha) or
                                     existing and existing.get("status") == core.ALLOWED and existing.get("sha256") == sha):
            entry["status"] = core.ALLOWED
            self.state.put(key, entry)
            self.unmark_inode(fd)
            return
        self.state.put(key, entry)
        if not self.mark_inode(fd, verdict.kind):
            return
        self.stats["flagged"] += 1
        if verdict.critical:
            try:
                if st.st_mode & 0o111:
                    os.fchmod(fd, stat.S_IMODE(st.st_mode) & ~0o111)   # kriticky soubor: bez prava spusteni
            except OSError:
                pass
        if existing is None or existing.get("sha256") != sha:
            log(f"{entry['level']}: {path} ({verdict.kind}, {origin[0]}"
                f"{'; ' + ', '.join(verdict.reasons) if verdict.reasons else ''})")
            self.state.add_log(path=path, level=entry["level"], action="found", uid=uid, reasons=verdict.reasons)
        if new_critical:
            self.post(("notify", uid, {"op": "found", **self._public(entry)}))

    # ---- antivirus (vlakno antiviru) -------------------------------------------------------------
    def virus_check(self, job):
        """Kontrola souboru databazi ClamAV; nalez -> karantena a upozorneni. Vraci (stav, detail, zaznam)."""
        fd = job["fd"]
        try:
            st = os.fstat(fd)
            if not av.should_scan(st):
                return av.CLEAN, "", None
            path = fd_path(fd) or job["path"]
            if path.endswith(" (deleted)"):
                return av.CLEAN, "", None
            self.stats["virus_scanned"] += 1
            status, detail = self.clamd.scan_fd(fd)
            if status == av.ERROR:
                log(f"virus check of {path} failed: {detail}")
                return status, detail, None
            if status != av.INFECTED:
                return status, detail, None
            self.stats["virus_found"] += 1
            uid = job.get("uid")
            if uid is None:
                uid, _home = self.users.owner_of(path)
            if uid is None:
                uid = st.st_uid
            entry = self.quarantine.put(fd, path, detail, uid)
            key = (st.st_dev, st.st_ino)
            with self.lock:
                self.state.remove(key)
            log(f"virus {detail}: {path} moved to quarantine ({entry['id']})")
            self.state.add_log(path=path, level=core.CRITICAL, action="quarantine", uid=uid, reasons=[detail])
            self.post(("notify", uid, {"op": "found", "path": path, "name": os.path.basename(path), "virus": detail,
                                       "quarantine": entry["id"], "level": core.CRITICAL, "reasons": [detail]}))
            return status, detail, entry
        finally:
            close_fd(fd)

    def _quarantine_op(self, client, msg):
        op = msg.get("op")
        if op == "quarantine":
            return {"op": "quarantine", "entries": [{k: e.get(k) for k in ("id", "path", "signature", "size", "time",
                                                                          "removed")}
                                                    for e in self.quarantine.list(client.uid)]}
        qid = msg.get("id")
        if not isinstance(qid, str):
            return {"op": "error", "error": "unknown item"}
        if op == "quarantine_delete":
            ok = self.quarantine.delete(qid, client.uid)
            if ok:
                self.state.add_log(path=qid, level=core.CRITICAL, action="deleted", uid=client.uid)
            return {"op": op, "ok": ok}
        path = self.quarantine.restore(qid, client.uid, home_of=self.users.home_of)
        if path:
            log(f"restored from quarantine: {path} (uid {client.uid})")
            self.state.add_log(path=path, level=core.CRITICAL, action="restored", uid=client.uid)
        return {"op": op, "ok": bool(path), "path": path}

    def _virus_scan_op(self, client, fd):
        """`luxos-guard scan --virus`: soubor od klienta (popisovac otevrel klient, tedy smi ho cist)."""
        if self.clamd is None:
            return {"op": "error", "error": "antivirus off"}
        try:
            st = os.fstat(fd)
        except OSError:
            return {"op": "error", "error": "bad file"}
        if client.uid != 0 and st.st_uid != client.uid:
            # cizi soubor jen zkontrolovat (do karanteny ho smi dat jen vlastnik nebo root)
            status, detail = self.clamd.scan_fd(fd) if av.should_scan(st) else (av.CLEAN, "")
            return {"op": "virus_scan", "status": status, "detail": detail, "quarantine": None}
        status, detail, entry = self.virus_check({"fd": os.dup(fd), "path": fd_path(fd), "uid": client.uid})
        return {"op": "virus_scan", "status": status, "detail": detail, "quarantine": entry and entry["id"]}

    def post(self, item):
        self.results.put(item)
        try:
            os.write(self.wake_w, b"x")
        except OSError:
            pass

    def on_results(self):
        try:
            os.read(self.wake_r, 4096)
        except OSError:
            pass
        while True:
            try:
                item = self.results.get_nowait()
            except queue.Empty:
                break
            if item[0] == "done":
                waiters = self.pending.pop(item[1], [])
                for mask, fd, pid, _t in waiters:
                    self.on_perm(mask, fd, pid)
            elif item[0] == "notify":
                self._to_agent(item[1], item[2])

    # ---- start: obnova znacek, soubory stazene behem vypnuti --------------------------------------------
    def restore_marks(self, entries):
        n = 0
        for e in entries:
            path = e.get("path")
            if not path or e.get("mount_mark"):
                continue
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if not core.entry_matches_file(e, st):
                continue
            key = (st.st_dev, st.st_ino)
            self.state.put(key, e)
            if e.get("status") == core.FLAGGED:
                if self.mark_inode(None, e.get("kind"), path=path):
                    n += 1
        self.state.dirty = True
        return n

    def initial_scan(self, max_files=3000, max_depth=4):
        """Spustitelne soubory, ktere uz lezi ve Stazenych (stazene pred instalaci nebo behem vypnuti)."""
        count = 0
        for home in list(self.users.homes()):
            for d in self.users.download_dirs(home):
                for root, dirs, files in os.walk(d, followlinks=False):
                    if root[len(d):].count("/") >= max_depth:
                        dirs[:] = []
                    for name in files:
                        count += 1
                        if count > max_files:
                            return
                        p = os.path.join(root, name)
                        try:
                            if not stat.S_ISREG(os.lstat(p).st_mode):
                                continue
                            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
                        except OSError:
                            continue
                        try:
                            st = os.fstat(fd)
                            key = (st.st_dev, st.st_ino)
                            if self.state.get(key) or not stat.S_ISREG(st.st_mode):
                                close_fd(fd)
                                continue
                            kind = rules.detect_kind(os.pread(fd, 64, 0), name)
                        except OSError:
                            close_fd(fd)
                            continue
                        if kind is None:
                            close_fd(fd)
                            continue
                        with self.lock:
                            self.analyzing.add(key)
                        self.analyze({"fd": fd, "path": p, "pid": 0, "kind": kind, "info": {},
                                      "loc": ("download", None), "key": key, "premarked": False})

    def update_mounts(self, mounts=None):
        mounts = read_mounts() if mounts is None else mounts
        now_rem = set(removable_mounts(mounts))
        added = set()
        for mp in now_rem - self.removable:
            try:
                self.perm.mark(FAN_MARK_ADD | FAN_MARK_MOUNT, PERM_EXEC | PERM_OPEN, AT_FDCWD, mp)
                log(f"watching removable media {mp}")
                added.add(mp)
            except OSError as e:
                log(f"cannot watch {mp}: {e}")
        self.removable = (self.removable & now_rem) | added
        self.clean_cache.clear()
        # zaznamy z odpojenych medii zahodit
        with self.state.lock:
            for k, e in list(self.state.entries.items()):
                if e.get("mount_mark") and e.get("origin_detail") not in self.removable:
                    self.state.entries.pop(k, None)
                    self.state.dirty = True


# ---- hlavni smycka --------------------------------------------------------------------------------------
SO_PEERPIDFD = getattr(socket, "SO_PEERPIDFD", 77)     # Linux 6.5+


def peer_pidfd(conn):
    """pidfd procesu, ktery se pripojil (jadro ho drzi od connect(), PID nemuze mezitim dostat jiny proces)."""
    try:
        return struct.unpack("i", conn.getsockopt(socket.SOL_SOCKET, SO_PEERPIDFD, 4))[0]
    except OSError:
        return None


def serve(guard, sock_path=core.SOCKET):
    os.makedirs(os.path.dirname(sock_path), mode=0o755, exist_ok=True)
    os.chmod(os.path.dirname(sock_path), 0o755)     # UMask=0077 v jednotce
    try:
        os.unlink(sock_path)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC | socket.SOCK_NONBLOCK)
    srv.bind(sock_path)
    os.chmod(sock_path, 0o666)
    srv.listen(32)
    poller = select.poll()
    poller.register(guard.perm.fileno(), select.POLLIN)
    poller.register(srv.fileno(), select.POLLIN)
    poller.register(guard.wake_r, select.POLLIN)
    mi = open("/proc/self/mountinfo", "rb")
    poller.register(mi.fileno(), select.POLLPRI | select.POLLERR)
    clients = {}
    guard._clients = clients
    last_save = 0
    while True:
        for fdno, c in list(clients.items()):
            if c.broken or c.closed:
                _drop(guard, poller, clients, fdno)
            elif bool(c.out) != c.pollout:
                c.pollout = bool(c.out)
                poller.modify(fdno, select.POLLIN | (select.POLLOUT if c.pollout else 0))
        for fdno, ev in poller.poll(1000):
            if fdno == guard.perm.fileno():
                for mask, fd, pid in guard.perm.read():
                    if mask & (PERM_EXEC | PERM_OPEN):
                        guard.on_perm(mask, fd, pid)
                    else:
                        close_fd(fd)
            elif fdno == srv.fileno():
                try:
                    conn, _a = srv.accept()
                except OSError:
                    continue
                conn.setblocking(False)
                pid, uid, gid = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                                    struct.calcsize("3i")))
                if uid != 0 and (len(clients) >= MAX_CLIENTS or
                                 sum(1 for x in clients.values() if x.uid == uid) >= MAX_CLIENTS_PER_UID):
                    guard.stats["refused_clients"] = guard.stats.get("refused_clients", 0) + 1
                    conn.close()
                    continue
                c = Client(conn, uid, pid, gid, peer_pidfd(conn))
                clients[conn.fileno()] = c
                poller.register(conn.fileno(), select.POLLIN)
            elif fdno == guard.wake_r:
                guard.on_results()
            elif fdno == mi.fileno():
                mi.seek(0)
                mi.read()
                guard.update_mounts()
            elif fdno in clients:
                c = clients[fdno]
                if ev & select.POLLOUT:
                    c.flush()
                if ev & (select.POLLIN | select.POLLHUP | select.POLLERR):
                    on_client_data(guard, poller, clients, fdno, c)
        guard.tick()
        if guard.state.dirty and time.monotonic() - last_save > 2:
            try:
                guard.state.save()
            except OSError as e:
                log(f"saving state failed: {e}")
            last_save = time.monotonic()


def _drop(guard, poller, clients, fdno):
    try:
        poller.unregister(fdno)
    except (KeyError, ValueError):
        pass
    c = clients.pop(fdno, None)
    if c is not None:
        guard.drop_client(c)


def on_client_data(guard, poller, clients, fdno, c):
    try:
        data, anc, _fl, _ad = c.sock.recvmsg(65536, socket.CMSG_SPACE(4 * 4))
    except (BlockingIOError, InterruptedError):
        return
    except OSError:
        data = b""
        anc = []
    for level, typ, cdata in anc:
        if level == socket.SOL_SOCKET and typ == socket.SCM_RIGHTS:
            n = len(cdata) // 4
            c.add_fds(struct.unpack(f"{n}i", cdata[:n * 4]))
    if not data:
        _drop(guard, poller, clients, fdno)
        return
    c.buf += data
    if len(c.buf) > 256 * 1024:
        _drop(guard, poller, clients, fdno)
        return
    while b"\n" in c.buf and not c.closed:
        line, c.buf = c.buf.split(b"\n", 1)
        try:
            msg = json.loads(line)
            if not isinstance(msg, dict):
                raise ValueError
        except (ValueError, RecursionError):
            continue
        try:
            reply = guard.on_message(c, msg)
        except Exception as e:  # noqa: BLE001 - zprava od klienta nesmi ukoncit sluzbu
            log(f"bad request from pid {c.pid} (uid {c.uid}): {type(e).__name__}")
            reply = {"op": "error", "error": "bad request"}
        if reply is not None:
            c.send(reply)


def notif_reader(guard):
    while True:
        try:
            events = guard.notif.read(64 * 1024)
        except OSError as e:
            log(f"reading events failed: {e}")
            time.sleep(1)
            continue
        for mask, fd, pid in events:
            if mask & FAN_Q_OVERFLOW:
                guard.stats["overflows"] += 1
            if fd < 0:
                continue
            taken = False
            try:
                if mask & FAN_CLOSE_WRITE:
                    taken = guard.on_close_write(fd, pid)
            except Exception as e:  # noqa: BLE001 - ctecka nesmi skoncit
                log(f"event error: {e}")
            if not taken:
                close_fd(fd)


def head_nonempty(fd):
    try:
        return bool(os.pread(fd, 1, 0))
    except OSError:
        return False


def av_worker(guard):
    while True:
        job = guard.av_jobs.get()
        try:
            guard.virus_check(job)
        except Exception as e:  # noqa: BLE001
            log(f"virus check error: {e}")
            close_fd(job["fd"])


def av_idle(guard):
    while True:
        time.sleep(5)
        try:
            if guard.clamd.tick():
                log("antivirus engine stopped (idle)")
        except Exception as e:  # noqa: BLE001
            log(f"antivirus idle check: {e}")


def worker(guard):
    while True:
        job = guard.jobs.get()
        try:
            guard.analyze(job)
        except Exception as e:  # noqa: BLE001
            log(f"analysis error: {e}")


def run_service():
    if os.geteuid() != 0:
        log("luxos-guard service must run as root")
        return 1
    sys.setswitchinterval(0.001)    # udalosti povoleni nesmi cekat na vlakno analyzy
    try:
        perm = Fanotify(FAN_CLASS_CONTENT | FAN_CLOEXEC | FAN_NONBLOCK | FAN_UNLIMITED_MARKS)
        notif = Fanotify(FAN_CLASS_NOTIF | FAN_CLOEXEC | FAN_UNLIMITED_MARKS)
    except OSError as e:
        log(f"fanotify is not available ({e}); the kernel needs CONFIG_FANOTIFY_ACCESS_PERMISSIONS=y")
        return 1
    state = core.State()
    entries = state.load()
    clamd = None
    if av.enabled() and av.installed():
        clamd = av.Clamd()
    guard = Guard(perm, notif, state, clamd=clamd)
    n = guard.restore_marks(entries)
    mounts = read_mounts()
    for mp in watch_mounts(mounts):
        try:
            notif.mark(FAN_MARK_ADD | FAN_MARK_MOUNT, FAN_CLOSE_WRITE, AT_FDCWD, mp)
        except OSError as e:
            log(f"cannot watch {mp}: {e}")
    guard.update_mounts(mounts)
    log(f"Lux Guard {core.VERSION} active: {n} watched files, writes watched on {', '.join(watch_mounts(mounts))}"
        f"; antivirus {'on (ClamAV on demand)' if clamd else 'off'}")
    threading.Thread(target=notif_reader, args=(guard,), daemon=True, name="reader").start()
    threading.Thread(target=worker, args=(guard,), daemon=True, name="analysis").start()
    if clamd is not None:
        threading.Thread(target=av_worker, args=(guard,), daemon=True, name="antivirus").start()
        threading.Thread(target=av_idle, args=(guard,), daemon=True, name="antivirus-idle").start()
    threading.Thread(target=guard.delayed.run, daemon=True, name="delayed").start()
    threading.Thread(target=guard.initial_scan, daemon=True, name="scan").start()
    try:
        state.save()
    except OSError:
        pass
    serve(guard)
    return 0
