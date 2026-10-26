"""LuxDrop - soubory jineho pocitace LuxOS (Soubory: vzdalene | mistni vedle sebe).

Pocitac, ktery sdili (luxdrop-files.service, port 47924, mDNS _luxdrop-files._tcp):
  TLS 1.3 (ALPN luxdrop-files/1) + stejne overeni identit jako LuxDrop (hello/auth, SAS)
  klient -> open {write}       server se zepta uzivatele: Povolit jednou / Vzdy / Odmitnout
  server -> opened {write, shares} nebo reject {code}
  klient -> start              dale uz jen surovy proud SFTP
SFTP obsluhuje OpenSSH sftp-server v bubblewrap: vidi jen sdilene slozky (zbytek disku
v sandboxu neexistuje), bez site, bez -R jen po schvaleni zapisu. sshd neni potreba.

Pocitac, ktery se pripojuje: sshfs -o passive (FUSE) pres socketpair <-> TLS, pripojeno
v $XDG_RUNTIME_DIR/luxdrop-files/<jmeno>, zalozka v postranim panelu Souboru.
"""
import base64
import getpass
import json
import os
import re
import select
import shutil
import signal
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.parse

from . import identity as ident
from . import proto, store, transfer

FILES_PORT = 47924
SERVICE_TYPE = "_luxdrop-files._tcp"
ALPN = "luxdrop-files/1"
ROOT = "/share"                  # koren sdilenych slozek v sandboxu (a cesta pro sshfs)
HANDSHAKE_TIMEOUT = 20
DECISION_TIMEOUT = 120
DENY_COOLDOWN = 300              # po odmitnuti se stejne zarizeni 5 minut neptame znovu
MAX_SESSIONS = 8
BUF = 256 * 1024
SFTP_SERVERS = ("/usr/lib/ssh/sftp-server", "/usr/libexec/openssh/sftp-server", "/usr/lib/openssh/sftp-server")
# sftp-server: zakazane pozadavky (symlink by mohl ukazovat mimo sdilenou slozku)
SFTP_DENY = "symlink,hardlink@openssh.com"
MEDIA_ROOTS = ("/run/media", "/media", "/mnt")


class ShareError(Exception):
    pass


def log(msg):
    transfer.log("files: " + msg)


# --- Nastaveni sdileni ---------------------------------------------------------

def public_dir():
    """Slozka Verejne podle xdg-user-dirs (jinak ~/Public)."""
    home = os.path.expanduser("~")
    try:
        with open(os.path.join(home, ".config", "user-dirs.dirs"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r'\s*XDG_PUBLICSHARE_DIR="(.*)"', line)
                if m:
                    p = m.group(1).replace("$HOME", home)
                    if os.path.realpath(p) != os.path.realpath(home):
                        return p
    except OSError:
        pass
    return os.path.join(home, "Public")


def check_share_path(path):
    """Vrati (realna cesta, je_domovska) nebo vyhodi ShareError.

    Sdilet jde jen slozku v domovske slozce (ne skrytou ani v skryte slozce) nebo na
    vymenitelnem disku (/run/media, /media, /mnt). Nikdy / ani systemove slozky.
    """
    if not isinstance(path, str) or not path:
        raise ShareError("empty path")
    real = os.path.realpath(os.path.expanduser(path))
    if not os.path.isdir(real):
        raise ShareError("not a folder: %s" % path)
    home = os.path.realpath(os.path.expanduser("~"))
    if real == home:
        return real, True
    if home.startswith(real.rstrip("/") + "/"):
        raise ShareError("folders that contain the home folder cannot be shared: %s" % path)
    if real.startswith(home + "/"):
        rel = real[len(home) + 1:]
        if any(p.startswith(".") for p in rel.split("/")):
            raise ShareError("hidden folders cannot be shared: %s" % path)
        return real, False
    for root in MEDIA_ROOTS:
        if real.startswith(root + "/"):
            if any(p.startswith(".") for p in real[len(root) + 1:].split("/")):
                raise ShareError("hidden folders cannot be shared: %s" % path)
            return real, False
    raise ShareError("only folders in your home folder or on external drives can be shared: %s" % path)


def share_name(path, taken):
    name = os.path.basename(path.rstrip("/")) or "share"
    name = "".join(c for c in name if c.isprintable() and c != "/").lstrip(".").strip() or "share"
    name = name[:80]
    out, n = name, 2
    while out.lower() in taken:
        out = "%s %d" % (name, n)
        n += 1
    return out


class Shares:
    """Sdilene slozky (~/.config/luxdrop/shares.json): {"enabled": bool, "folders": [cesta, ...]}."""

    def __init__(self, directory=None):
        self.dir = directory or store.config_dir()
        self.path = os.path.join(self.dir, "shares.json")
        self.enabled = False
        self.paths = []
        self.configured = False
        self.reload()

    def reload(self):
        data = store._load_json(self.path, {})
        self.enabled = data.get("enabled") is True
        folders = data.get("folders")
        self.configured = isinstance(folders, list)
        self.paths = [p for p in folders if isinstance(p, str)] if self.configured else []

    def save(self):
        ident.ensure_private_dir(self.dir)
        store._save_json(self.path, {"enabled": self.enabled, "folders": self.paths})

    def folders(self):
        """Platne sdilene slozky: [{"name", "path", "home"}] (neplatne/smazane se preskoci)."""
        out, taken = [], set()
        for p in self.paths:
            try:
                real, home = check_share_path(p)
            except ShareError:
                continue
            if any(f["path"] == real for f in out):
                continue
            name = share_name(real, taken)
            taken.add(name.lower())
            out.append({"name": name, "path": real, "home": home})
        return out

    def add(self, path, allow_home=False):
        real, home = check_share_path(path)
        if home and not allow_home:
            raise ShareError("sharing the whole home folder must be confirmed")
        self.reload()
        if real not in [os.path.realpath(os.path.expanduser(p)) for p in self.paths]:
            self.paths.append(real)
            self.configured = True
            self.save()
        return real

    def remove(self, key):
        self.reload()
        real = os.path.realpath(os.path.expanduser(key))
        names = {f["name"].lower(): f["path"] for f in self.folders()}
        target = names.get(key.strip().lower(), real)
        before = len(self.paths)
        self.paths = [p for p in self.paths if os.path.realpath(os.path.expanduser(p)) != target]
        self.configured = True
        if len(self.paths) != before:
            self.save()
        return before - len(self.paths)

    def set_enabled(self, on):
        self.reload()
        if on and not self.configured:
            # Prvni zapnuti: sdili se jen slozka Verejne (vytvori se)
            pub = public_dir()
            try:
                os.makedirs(pub, exist_ok=True)
                self.paths = [os.path.realpath(pub)]
            except OSError:
                self.paths = []
            self.configured = True
        self.enabled = bool(on)
        self.save()


class Access:
    """Zarizeni, kterym majitel povolil pristup "Vzdy" (file-access.json, 0600).

    {otisk_hex: {"name", "id", "write": bool, "added", "last_seen"}}
    """

    def __init__(self, directory=None):
        self.dir = directory or ident.data_dir()
        self.path = os.path.join(self.dir, "file-access.json")
        self.peers = {}
        self.reload()

    def reload(self):
        data = store._load_json(self.path, {})
        self.peers = {k: v for k, v in data.items() if isinstance(v, dict) and re.fullmatch(r"[0-9a-f]{64}", k)}

    def save(self):
        ident.ensure_private_dir(self.dir)
        store._save_json(self.path, self.peers)

    def get(self, fp):
        self.reload()
        return self.peers.get(fp.hex())

    def allow(self, fp, name, write):
        self.reload()
        e = self.peers.get(fp.hex(), {"added": time.time()})
        e.update({"name": transfer.clean_name(name), "id": proto.short_id(fp), "write": bool(write),
                  "last_seen": time.time()})
        self.peers[fp.hex()] = e
        self.save()

    def touch(self, fp):
        self.reload()
        e = self.peers.get(fp.hex())
        if e is not None:
            e["last_seen"] = time.time()
            self.save()

    def find(self, key):
        self.reload()
        k = key.strip().lower().replace(" ", "").replace(":", "")
        return [(h, e) for h, e in self.peers.items()
                if (len(k) >= 8 and h.startswith(k)) or e.get("name", "").lower() == key.strip().lower()]

    def remove(self, key):
        hits = self.find(key)
        for h, _e in hits:
            del self.peers[h]
        if hits:
            self.save()
        return len(hits)

    def set_write(self, key, write):
        hits = self.find(key)
        for h, _e in hits:
            self.peers[h]["write"] = bool(write)
        if hits:
            self.save()
        return len(hits)


# --- Sandbox se sftp-server ------------------------------------------------------

def sftp_server_path():
    for p in SFTP_SERVERS:
        if os.access(p, os.X_OK):
            return p
    return None


def _hidden_masks(path, dest, write):
    """Skryte polozky v koreni domovske slozky (.ssh, klicenka, nastaveni) se v sandboxu prekryji."""
    out = []
    try:
        entries = list(os.scandir(path))
    except OSError:
        return out
    for e in entries:
        if not e.name.startswith(".") or e.is_symlink():
            continue  # symlink v sandboxu vede do prazdna
        target = dest + "/" + e.name
        if e.is_dir(follow_symlinks=False):
            out += ["--tmpfs", target, "--remount-ro", target]
        else:
            out += ["--ro-bind", "/dev/null", target]
    return out


def _writable_subdirs(path, dest):
    out = []
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name)
    except OSError:
        return out
    for e in entries:
        if not e.name.startswith(".") and not e.is_symlink() and e.is_dir(follow_symlinks=False):
            out += ["--bind", os.path.join(path, e.name), dest + "/" + e.name]
    return out


def sandbox_argv(folders, write, etc_dir, sftp_server=None):
    """Prikaz bwrap: jen /usr (jen pro cteni) a sdilene slozky v /share, bez site a bez schopnosti."""
    sftp = sftp_server or sftp_server_path()
    if not sftp:
        raise ShareError("sftp-server (openssh) is not installed")
    argv = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
            "--clearenv", "--setenv", "HOME", ROOT, "--setenv", "PATH", "/usr/bin",
            "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib", "/lib64",
            "--symlink", "usr/bin", "/bin", "--symlink", "usr/bin", "/sbin",
            "--ro-bind", os.path.join(etc_dir, "passwd"), "/etc/passwd",
            "--ro-bind", os.path.join(etc_dir, "group"), "/etc/group",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", ROOT]
    for f in folders:
        dest = ROOT + "/" + f["name"]
        if f.get("home"):
            # Domovska slozka: skryte polozky prekryte; zapisovat jde jen do jejich (neskrytych)
            # podslozek - v koreni domova nejde zalozit napr. .bashrc nebo .profile
            argv += ["--ro-bind", f["path"], dest] + _hidden_masks(f["path"], dest, write)
            if write:
                argv += _writable_subdirs(f["path"], dest)
        else:
            argv += ["--bind" if write else "--ro-bind", f["path"], dest]
    # Koren (/ a /share) jen pro cteni: zapisovat jde jen do sdilenych slozek
    argv += ["--remount-ro", "/", "--chdir", ROOT, sftp, "-d", ROOT, "-u", "022", "-P", SFTP_DENY]
    if not write:
        argv.append("-R")
    return argv


def runtime_dir():
    base = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    if not os.path.isdir(base):
        base = tempfile.gettempdir()
        path = os.path.join(base, "luxdrop-files-%d" % os.getuid())
    else:
        path = os.path.join(base, "luxdrop-files")
    ident.ensure_private_dir(path)
    return path


def sandbox_etc():
    """Minimalni /etc/passwd a /etc/group pro sftp-server (jen aktualni uzivatel)."""
    d = os.path.join(runtime_dir(), "etc")
    ident.ensure_private_dir(d)
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = "user"
    user = re.sub(r"[^A-Za-z0-9._-]", "_", user) or "user"
    ident.write_private(os.path.join(d, "passwd"),
                        ("%s:x:%d:%d::%s:/usr/bin/nologin\n" % (user, os.getuid(), os.getgid(), ROOT)).encode())
    ident.write_private(os.path.join(d, "group"), ("%s:x:%d:\n" % (user, os.getgid())).encode())
    os.chmod(os.path.join(d, "passwd"), 0o644)
    os.chmod(os.path.join(d, "group"), 0o644)
    return d


# --- Prenos dat ------------------------------------------------------------------

def keepalive(sock):
    """Mrtve spojeni se pozna do ~45 s (sshfs pak nezasekne Soubory ani terminal)."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 15)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 45000)
    except (OSError, AttributeError):
        pass


def relay(tls, plain, stop=None):
    """Kopiruje data mezi TLS soketem a mistnim soketem (sshfs / sftp-server).

    Jedno vlakno a neblokujici sokety: objekt SSL se nesmi pouzivat ze dvou vlaken naraz.
    Konci, kdyz jedna strana zavre spojeni (a zbytek dat se dorucil) nebo kdyz je nastaven stop.
    """
    tls.setblocking(False)
    plain.setblocking(False)
    to_plain, to_tls = bytearray(), bytearray()
    tls_open = plain_open = True
    while True:
        if stop is not None and stop.is_set():
            break
        if (not tls_open and not to_plain) or (not plain_open and not to_tls):
            break
        rl, wl = [], []
        if tls_open and len(to_plain) < BUF:
            rl.append(tls)
        if plain_open and len(to_tls) < BUF:
            rl.append(plain)
        if to_plain:
            wl.append(plain)
        if to_tls:
            wl.append(tls)
        if tls in rl and tls.pending():
            r, w = [tls], []
        else:
            try:
                r, w, _x = select.select(rl, wl, [], 1.0)
            except (OSError, ValueError):
                break
        if tls in r:
            try:
                data = tls.recv(BUF)
                if data:
                    to_plain += data
                else:
                    tls_open = False
            except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                pass
            except (OSError, ssl.SSLError):
                tls_open = False
        if plain in r:
            try:
                data = plain.recv(BUF)
                if data:
                    to_tls += data
                else:
                    plain_open = False
            except BlockingIOError:
                pass
            except OSError:
                plain_open = False
        if plain in w and to_plain:
            try:
                n = plain.send(to_plain)
                del to_plain[:n]
            except BlockingIOError:
                pass
            except OSError:
                break
        if tls in w and to_tls:
            try:
                n = tls.send(bytes(to_tls[:65536]))
                del to_tls[:n]
            except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                pass
            except (OSError, ssl.SSLError):
                break
    for s in (tls, plain):
        try:
            s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _server_context(identity):
    ctx = transfer.server_context(identity)
    ctx.set_alpn_protocols([ALPN])
    return ctx


def _client_context():
    ctx = transfer.client_context()
    ctx.set_alpn_protocols([ALPN])
    return ctx


def _check_alpn(sock):
    alpn = sock.selected_alpn_protocol()
    if alpn is not None and alpn != ALPN:
        raise proto.ProtocolError(proto.E_PROTO_VERSION, "unsupported ALPN %r" % alpn)


# --- Server (sdileni) -------------------------------------------------------------

class AccessRequest:
    """Dotaz pro majitele: "<jmeno> chce pristup k vasim sdilenym slozkam"."""

    def __init__(self, fp, peer_name, sas, want_write, has_grant, name_clash, shares):
        self.fp = fp
        self.peer_name = peer_name
        self.peer_id = proto.short_id(fp)
        self.sas = sas                  # None u zarizeni s pripnutym klicem
        self.want_write = want_write
        self.has_grant = has_grant      # uz ma "Vzdy" pro cteni, zada o zapis
        self.name_clash = name_clash
        self.shares = shares            # jmena sdilenych slozek
        self.withdrawn = threading.Event()


class Session:
    def __init__(self, fp, peer_name, write, always, addr):
        self.fp, self.peer_name, self.write, self.always, self.addr = fp, peer_name, write, always, addr
        self.started = time.time()
        self.stop = threading.Event()
        self.proc = None
        self.tls = None


class FileServer:
    """Prijima spojeni klientu; ask(AccessRequest) -> ("once"|"always"|"deny", zapis)."""

    def __init__(self, identity, settings, trust, shares, access, ask, bind="", port=None):
        self.identity = identity
        self.settings = settings
        self.trust = trust
        self.shares = shares
        self.access = access
        self.ask = ask
        self.bind = bind
        self.port = FILES_PORT if port is None else port
        self.ctx = _server_context(identity)
        self.sock = None
        self.sessions = set()
        self._lock = threading.Lock()
        self._conn_sem = threading.BoundedSemaphore(MAX_SESSIONS + 2)
        self._prompt_sem = threading.BoundedSemaphore(1)
        self._denied = {}
        self._stop = threading.Event()
        self._etc = None

    def start(self):
        if self.bind:
            fam = socket.AF_INET6 if ":" in self.bind else socket.AF_INET
            self.sock = socket.create_server((self.bind, self.port), family=fam)
        elif socket.has_dualstack_ipv6():
            self.sock = socket.create_server(("", self.port), family=socket.AF_INET6, dualstack_ipv6=True)
        else:
            self.sock = socket.create_server(("", self.port))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True, name="luxdrop-files").start()
        return self.port

    def stop(self):
        self._stop.set()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        for s in list(self.sessions):
            self._end(s)

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, addr = self.sock.accept()
            except OSError:
                if self._stop.is_set():
                    return
                time.sleep(0.2)
                continue
            if not self._conn_sem.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=self._serve, args=(conn, addr), daemon=True).start()

    def _serve(self, conn, addr):
        try:
            self.handle(conn, addr)
        finally:
            self._conn_sem.release()

    def check(self):
        """Ukonci spojeni, ktera uz nejsou povolena (sdileni vypnuto, zarizeni odebrano, zapis odebran)."""
        self.shares.reload()
        for s in list(self.sessions):
            reason = None
            if not self.shares.enabled:
                reason = "sharing turned off"
            elif s.always:
                g = self.access.get(s.fp)
                if g is None:
                    reason = "access removed"
                elif s.write and not g.get("write"):
                    reason = "write access removed"
            if reason:
                log("closing session of %s: %s" % (s.peer_name, reason))
                self._end(s)

    @staticmethod
    def _end(s):
        s.stop.set()
        if s.tls is not None:
            try:
                s.tls.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if s.proc is not None and s.proc.poll() is None:
            try:
                s.proc.terminate()
            except OSError:
                pass

    def handle(self, conn, addr):
        ch = None
        peer = "?"
        try:
            keepalive(conn)
            conn.settimeout(HANDSHAKE_TIMEOUT)
            tls = self.ctx.wrap_socket(conn, server_side=True)
            ch = proto.Channel(tls)
            _check_alpn(tls)
            fp_c, peer, nonce_c, nonce_s = server_auth(ch, self.identity, self.settings.name)
            self.shares.reload()
            if not self.shares.enabled:
                raise proto.ProtocolError(proto.E_SHARING_OFF, "this computer does not share folders")
            ch.send({"type": "auth_ok", "trusted": self.trust.is_trusted(fp_c)})
            msg = ch.recv_msg("open")
            want_write = msg.get("write") is True
            folders = self.shares.folders()
            if not folders:
                raise proto.ProtocolError(proto.E_SHARING_OFF, "no shared folders")
            write, always = self._decide(ch, tls, fp_c, peer, nonce_c, nonce_s, want_write, folders)
            if len(self.sessions) >= MAX_SESSIONS:
                raise proto.ProtocolError(proto.E_BUSY, "too many connections")
            tls.settimeout(DECISION_TIMEOUT)
            ch.send({"type": "opened", "write": write, "shares": [f["name"] for f in folders]})
            ch.recv_msg("start")
            tls.settimeout(None)
            self._run_session(tls, fp_c, peer, write, always, folders, addr)
        except proto.ProtocolError as e:
            log("%s (%s): %s: %s" % (transfer.fmt_addr(addr[0], addr[1]), peer, e.code, e.message))
            if ch is not None and e.code != proto.E_CANCELLED:
                if e.code in (proto.E_DECLINED, proto.E_TIMEOUT, proto.E_BUSY, proto.E_SHARING_OFF):
                    try:
                        ch.send({"type": "reject", "code": e.code, "message": e.message})
                    except OSError:
                        pass
                else:
                    ch.error(e.code, e.message)
        except (OSError, ssl.SSLError, ConnectionError) as e:
            log("%s (%s): connection: %s" % (transfer.fmt_addr(addr[0], addr[1]), peer, e))
        except Exception as e:  # noqa: BLE001 - chyba nesmi shodit sluzbu
            log("internal error: %r" % e)
            if ch is not None:
                ch.error(proto.E_INTERNAL, "internal error")
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _decide(self, ch, tls, fp_c, peer, nonce_c, nonce_s, want_write, folders):
        """Vrati (zapis, vzdy). Bez dotazu jen u zarizeni s povolenim "Vzdy" (a zapisem, je-li zadan)."""
        grant = self.access.get(fp_c)
        if grant is not None and (not want_write or grant.get("write")):
            self.access.touch(fp_c)
            return want_write, True
        until = self._denied.get(fp_c, 0)
        if until > time.monotonic():
            raise proto.ProtocolError(proto.E_DECLINED, "access was denied")
        if not self._prompt_sem.acquire(blocking=False):
            raise proto.ProtocolError(proto.E_BUSY, "another request is waiting")
        try:
            trusted = self.trust.is_trusted(fp_c)
            sas = None if trusted else proto.sas_code(fp_c, self.identity.fp, nonce_c, nonce_s)
            clash = (not trusted) and peer.lower() in self.trust.names()
            req = AccessRequest(fp_c, peer, sas, want_write, grant is not None, clash, [f["name"] for f in folders])
            result, done = {}, threading.Event()

            def ask():
                try:
                    result["v"] = self.ask(req)
                except Exception as e:  # noqa: BLE001
                    log("prompt failed: %r" % e)
                    result["v"] = ("deny", False)
                done.set()

            threading.Thread(target=ask, daemon=True).start()
            deadline = time.monotonic() + DECISION_TIMEOUT
            while True:
                finished = done.wait(0.3)
                r, _w, _x = select.select([tls], [], [], 0)
                if r or tls.pending():
                    # Klient to vzdal (zavrel spojeni nebo nepotvrdil kod)
                    req.withdrawn.set()
                    raise proto.ProtocolError(proto.E_CANCELLED, "cancelled by the other computer")
                if finished:
                    break
                if time.monotonic() > deadline:
                    req.withdrawn.set()
                    raise proto.ProtocolError(proto.E_TIMEOUT, "no answer")
        finally:
            self._prompt_sem.release()
        decision, write = result["v"]
        write = bool(write) and want_write
        if decision not in ("once", "always"):
            now = time.monotonic()
            self._denied = {k: v for k, v in self._denied.items() if v > now}
            if grant is None:  # zarizeni s povolenim pro cteni muze dal cist
                self._denied[fp_c] = now + DENY_COOLDOWN
            raise proto.ProtocolError(proto.E_DECLINED, "access denied")
        if decision == "always":
            # Ulozene povoleni pro cteni se odmitnutim zapisu nezrusi
            self.access.allow(fp_c, peer, write or bool(grant and grant.get("write")))
        return write, decision == "always"

    def _run_session(self, tls, fp_c, peer, write, always, folders, addr):
        if self._etc is None:
            self._etc = sandbox_etc()
        argv = sandbox_argv(folders, write, self._etc)
        a, b = socket.socketpair()
        s = Session(fp_c, peer, write, always, addr)
        s.tls = tls
        try:
            s.proc = subprocess.Popen(argv, stdin=b.fileno(), stdout=b.fileno(), close_fds=True,
                                      start_new_session=True)
        finally:
            b.close()
        with self._lock:
            self.sessions.add(s)
        log("%s (%s) connected, %s" % (peer, proto.short_id(fp_c), "read-write" if write else "read-only"))
        try:
            relay(tls, a, stop=s.stop)
        finally:
            with self._lock:
                self.sessions.discard(s)
            a.close()
            if s.proc.poll() is None:
                s.proc.terminate()
                try:
                    s.proc.wait(3)
                except subprocess.TimeoutExpired:
                    s.proc.kill()
                    s.proc.wait()
            log("%s disconnected" % peer)


def server_auth(ch, identity, name):
    """Krok hello/auth jako u LuxDrop (PROTOCOL.md 6): vrati (otisk, jmeno, nonce_c, nonce_s)."""
    hello = ch.recv_msg("hello")
    transfer.check_proto(hello)
    try:
        cert_der = base64.b64decode(hello.get("cert", ""), validate=True)
    except (ValueError, TypeError):
        raise proto.ProtocolError(proto.E_AUTH_FAILED, "invalid certificate encoding") from None
    fp_c, pub_c = ident.cert_fingerprint(cert_der)
    commitment = proto.hex32(hello.get("commit"), "commit")
    if fp_c == identity.fp:
        raise proto.ProtocolError(proto.E_AUTH_FAILED, "peer uses our own identity")
    peer = transfer.clean_name(hello.get("name"))
    nonce_s = os.urandom(proto.NONCE_LEN)
    ch.send({"type": "hello", "proto": proto.PROTO_VERSION, "name": name, "id": identity.id,
             "nonce": nonce_s.hex()})
    auth = ch.recv_msg("auth")
    nonce_c = proto.hex32(auth.get("nonce"), "nonce")
    if not proto.check_commit(commitment, nonce_c):
        raise proto.ProtocolError(proto.E_AUTH_FAILED, "nonce does not match commitment")
    try:
        sig = base64.b64decode(auth.get("sig", ""), validate=True)
    except (ValueError, TypeError):
        raise proto.ProtocolError(proto.E_AUTH_FAILED, "invalid signature encoding") from None
    if not ident.verify_signature(pub_c, sig, proto.auth_message(identity.fp, fp_c, nonce_s, nonce_c)):
        raise proto.ProtocolError(proto.E_AUTH_FAILED, "invalid signature")
    return fp_c, peer, nonce_c, nonce_s


# --- Klient --------------------------------------------------------------------------

class ConnectCallbacks:
    def status(self, state, info):
        """state: connecting, waiting (info: peer_name, sas, trusted), mounting."""

    def confirm(self, info, replied):
        """Neznamy pocitac: shoduje se kod? Vrati (shoda, zapamatovat)."""
        return False, False


class Connection:
    def __init__(self, tls, host, port, fp, peer_name, write, shares):
        self.tls, self.host, self.port, self.fp = tls, host, port, fp
        self.peer_name, self.peer_id = peer_name, proto.short_id(fp)
        self.write, self.shares = write, shares


def connect(identity, settings, trust, host, port, want_write, cb, expected_fp=None, cancel=None):
    """Spojeni a schvaleni pristupu; vrati Connection (TLS uz v rezimu SFTP) nebo vyhodi ProtocolError."""
    cb.status("connecting", {"host": host, "port": port})
    raw = socket.create_connection((host, port), timeout=HANDSHAKE_TIMEOUT)
    keepalive(raw)
    tls = None
    try:
        tls = _client_context().wrap_socket(raw, server_hostname=None)
        _check_alpn(tls)
        fp_s, _pub = ident.cert_fingerprint(tls.getpeercert(binary_form=True))
        if expected_fp is not None and fp_s != expected_fp:
            raise proto.ProtocolError(proto.E_KEY_MISMATCH,
                                      "the computer at %s presented a different key than the trusted device "
                                      "(expected %s, got %s)" % (transfer.fmt_addr(host, port),
                                                                 proto.short_id(expected_fp), proto.short_id(fp_s)))
        if fp_s == identity.fp:
            raise proto.ProtocolError(proto.E_AUTH_FAILED, "cannot connect to this computer itself")
        peer_trusted = trust.is_trusted(fp_s)
        ch = proto.Channel(tls)
        nonce_c = os.urandom(proto.NONCE_LEN)
        ch.send({"type": "hello", "proto": proto.PROTO_VERSION, "name": settings.name, "id": identity.id,
                 "cert": base64.b64encode(identity.cert_der).decode(), "commit": proto.commit(nonce_c).hex()})
        sh = ch.recv_msg("hello")
        transfer.check_proto(sh)
        peer = transfer.clean_name(sh.get("name"))
        nonce_s = proto.hex32(sh.get("nonce"), "nonce")
        sig = identity.sign(proto.auth_message(fp_s, identity.fp, nonce_s, nonce_c))
        ch.send({"type": "auth", "nonce": nonce_c.hex(), "sig": base64.b64encode(sig).decode()})
        ch.recv_msg("auth_ok")
        sas = proto.sas_code(identity.fp, fp_s, nonce_c, nonce_s)
        ch.send({"type": "open", "write": bool(want_write)})
        info = {"peer_name": peer, "peer_id": proto.short_id(fp_s), "fp": fp_s, "sas": sas,
                "trusted": peer_trusted}
        cb.status("waiting", info)

        tls.settimeout(DECISION_TIMEOUT + 30)
        reply, replied = {}, threading.Event()

        def read_reply():
            try:
                reply["msg"] = ch.recv_msg("opened", "reject")
            except Exception as e:  # noqa: BLE001
                reply["exc"] = e
            replied.accepted = reply.get("msg", {}).get("type") == "opened"
            replied.set()

        threading.Thread(target=read_reply, daemon=True).start()
        remember = False
        if not peer_trusted:
            match, remember = cb.confirm(info, replied)
            refused = replied.is_set() and not replied.accepted
            if not match and not refused:
                transfer._abort_waiting(ch, tls, replied, proto.E_SAS_REJECTED)
                raise proto.ProtocolError(proto.E_SAS_REJECTED, "verification code not confirmed")
        while not replied.wait(0.2):
            if cancel is not None and cancel.is_set():
                transfer._abort_waiting(ch, tls, replied, "cancelled")
                raise proto.ProtocolError(proto.E_CANCELLED, "cancelled")
        if "exc" in reply:
            raise reply["exc"]
        msg = reply["msg"]
        if msg["type"] == "reject":
            code = msg.get("code") if msg.get("code") in proto.ERROR_CODES else proto.E_DECLINED
            raise proto.ProtocolError(code, str(msg.get("message", code))[:300])
        if remember and not peer_trusted:
            trust.add(fp_s, peer, addr=transfer.fmt_addr(host, port))
        elif peer_trusted:
            trust.touch(fp_s, name=peer, addr=transfer.fmt_addr(host, port))
        shares = [transfer.clean_name(n) for n in msg.get("shares", []) if isinstance(n, str)][:100]
        ch.send({"type": "start"})
        tls.settimeout(None)
        return Connection(tls, host, port, fp_s, peer, msg.get("write") is True, shares)
    except BaseException:
        try:
            (tls or raw).close()
        except OSError:
            pass
        raise


# --- Pripojeni (sshfs) -----------------------------------------------------------------

def registry_path():
    return os.path.join(runtime_dir(), "connections.json")


def _load_registry():
    data = store._load_json(registry_path(), [])
    return [e for e in data if isinstance(e, dict) and isinstance(e.get("path"), str)]


def _save_registry(items):
    ident.write_private(registry_path(), json.dumps(items, ensure_ascii=False).encode("utf-8"))


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def connections():
    """Aktivni pripojeni [{"name", "path", "pid", "peer_id", "write"}] (mrtva se uklidi)."""
    out = []
    lock = _registry_lock()
    try:
        items = _load_registry()
        for e in items:
            if _pid_alive(e.get("pid")):
                out.append(e)
            else:
                _cleanup_mount(e["path"])
        if len(out) != len(items):
            _save_registry(out)
    finally:
        lock.close()
    return out


def _registry_lock():
    import fcntl
    f = open(os.path.join(runtime_dir(), ".lock"), "a")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


def bookmarks_file():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "gtk-3.0", "bookmarks")


def _bookmark_uri(path):
    return "file://" + urllib.parse.quote(path)


def add_bookmark(path, label):
    """Zalozka v postrannim panelu Souboru (Thunar sleduje ~/.config/gtk-3.0/bookmarks)."""
    f = bookmarks_file()
    try:
        lines = open(f, encoding="utf-8").read().splitlines()
    except OSError:
        lines = []
    uri = _bookmark_uri(path)
    if any(ln.split(" ", 1)[0] == uri for ln in lines):
        return
    lines.append("%s %s" % (uri, label.replace("\n", " ")))
    os.makedirs(os.path.dirname(f), exist_ok=True)
    tmp = f + ".luxdrop.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, f)


def remove_bookmark(path):
    f = bookmarks_file()
    try:
        lines = open(f, encoding="utf-8").read().splitlines()
    except OSError:
        return
    uri = _bookmark_uri(path)
    keep = [ln for ln in lines if ln.split(" ", 1)[0] != uri]
    if len(keep) != len(lines):
        tmp = f + ".luxdrop.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(keep) + ("\n" if keep else ""))
        os.replace(tmp, f)


def _unmount(path):
    for args in (["-u"], ["-u", "-z"]):
        if not os.path.ismount(path):
            return True
        try:
            subprocess.run(["fusermount3"] + args + [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return not os.path.ismount(path)


def _cleanup_mount(path):
    # Jen nase prijpojeni v runtime adresari (registr je soubor uzivatele, ale i tak)
    if os.path.dirname(path) != runtime_dir():
        return
    _unmount(path)
    try:
        os.rmdir(path)
    except OSError:
        pass
    remove_bookmark(path)


def mount_name(peer_name):
    name = "".join(c for c in peer_name if c.isprintable() and c not in "/\\").strip().lstrip(".") or "LuxOS"
    return name[:60]


class Mount:
    """Pripojeni vzdalenych slozek pres sshfs (FUSE); konci odpojenim nebo ztratou spojeni."""

    def __init__(self, conn):
        self.conn = conn
        self.path = None
        self.proc = None
        self.thread = None
        self.stop = threading.Event()
        self._closed = False

    def start(self, timeout=15):
        if not shutil.which("sshfs"):
            raise RuntimeError("sshfs is not installed")
        lock = _registry_lock()
        try:
            items = [e for e in _load_registry() if _pid_alive(e.get("pid"))]
            base, n = mount_name(self.conn.peer_name), 1
            used = {os.path.basename(e["path"]) for e in items}
            name = base
            while name in used or os.path.ismount(os.path.join(runtime_dir(), name)):
                n += 1
                name = "%s %d" % (base, n)
            self.path = os.path.join(runtime_dir(), name)
            if os.path.lexists(self.path) and not os.path.ismount(self.path):
                try:
                    os.rmdir(self.path)
                except OSError:
                    pass
            os.makedirs(self.path, mode=0o700, exist_ok=True)
            items.append({"name": name, "path": self.path, "pid": os.getpid(), "peer": self.conn.peer_name,
                          "peer_id": self.conn.peer_id, "write": self.conn.write, "since": time.time()})
            _save_registry(items)
        finally:
            lock.close()
        # follow_symlinks: odkazy vyhodnocuje druhy pocitac (v sandboxu) - odkaz mimo sdilenou slozku je rozbity
        opts = ["passive", "follow_symlinks", "noexec", "nosuid", "nodev", "idmap=user", "subtype=luxdrop",
                "fsname=luxdrop:%s" % self.conn.peer_id]
        if not self.conn.write:
            opts.append("ro")
        a, b = socket.socketpair()
        try:
            self.proc = subprocess.Popen(["sshfs", "-f", "-o", ",".join(opts), "luxdrop:" + ROOT, self.path],
                                         stdin=b.fileno(), stdout=b.fileno(), close_fds=True)
        finally:
            b.close()
        self.thread = threading.Thread(target=self._relay, args=(a,), daemon=True)
        self.thread.start()
        deadline = time.monotonic() + timeout
        while not os.path.ismount(self.path):
            if self.proc.poll() is not None or not self.thread.is_alive() or time.monotonic() > deadline:
                self.close()
                raise RuntimeError("cannot mount the shared folders (sshfs)")
            time.sleep(0.1)
        add_bookmark(self.path, os.path.basename(self.path))
        return self.path

    def _relay(self, a):
        try:
            relay(self.conn.tls, a, stop=self.stop)
        finally:
            a.close()

    def alive(self):
        return self.thread is not None and self.thread.is_alive() and self.proc.poll() is None

    def wait(self, stop=None):
        while self.alive():
            if stop is not None and stop.is_set():
                break
            time.sleep(0.3)

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.path:
            _unmount(self.path)
        self.stop.set()
        try:
            self.conn.tls.close()
        except OSError:
            pass
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.path:
            _unmount(self.path)
            try:
                os.rmdir(self.path)
            except OSError:
                pass
            remove_bookmark(self.path)
            lock = _registry_lock()
            try:
                _save_registry([e for e in _load_registry() if e.get("path") != self.path])
            finally:
                lock.close()


def disconnect(key=None):
    """Odpoji podle jmena (nebo vse pri key=None); vrati pocet."""
    n = 0
    for e in connections():
        if key is None or e["name"].lower() == key.lower() or e.get("peer", "").lower() == key.lower() \
                or (len(key) >= 6 and e.get("peer_id", "").startswith(key.lower())):
            try:
                os.kill(e["pid"], signal.SIGTERM)
            except OSError:
                _cleanup_mount(e["path"])
            n += 1
    return n


# --- Okno Souboru -----------------------------------------------------------------

def _xdotool(*args, timeout=5):
    try:
        r = subprocess.run(["xdotool"] + list(args), capture_output=True, text=True, timeout=timeout)
        return r.stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return []


def open_side_by_side(remote, local=None):
    """Otevre okno Souboru (Thunar) s rozdelenim: vzdalene slozky | domovska slozka.

    Thunar nema prepinac pro rozdelene okno: nove okno na vzdalenych slozkach, F3 (rozdelit,
    nova polovina je aktivni) a Alt+Home (domovska slozka v aktivni polovine).
    Bez xdotool/X11 jen okno se vzdalenymi slozkami.
    """
    if not shutil.which("thunar"):
        subprocess.Popen(["xdg-open", remote], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return False
    if not os.environ.get("DISPLAY") or not shutil.which("xdotool"):
        subprocess.Popen(["thunar", remote], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return False
    before = set(_xdotool("search", "--onlyvisible", "--class", "Thunar"))
    subprocess.Popen(["thunar", "--window", remote], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    win = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and win is None:
        time.sleep(0.25)
        new = [w for w in _xdotool("search", "--onlyvisible", "--class", "Thunar") if w not in before]
        if new:
            win = new[-1]
    if win is None:
        return False
    time.sleep(0.5)
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "timeout": 5}
    try:
        if subprocess.call(["xdotool", "windowactivate", "--sync", win], **quiet) != 0:
            subprocess.call(["xdotool", "windowfocus", "--sync", win], **quiet)
        time.sleep(0.3)
        # Klavesy jdou do aktivniho okna (XTEST); --window by poslalo syntetickou udalost, kterou GTK ignoruje
        subprocess.call(["xdotool", "key", "--clearmodifiers", "F3"], **quiet)
        time.sleep(0.6)
        subprocess.call(["xdotool", "key", "--clearmodifiers", "alt+Home"], **quiet)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True
