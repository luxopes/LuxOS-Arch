"""LuxDrop - prenos souboru: TLS 1.3, overeni identit, SAS, odesilani a prijem.

Prubeh (podrobne v PROTOCOL.md):
  TLS 1.3 (server se prokazuje certifikatem, klient pripina otisk)
  klient -> hello {cert, commit}      server -> hello {nonce}
  klient -> auth {nonce, sig}         server -> auth_ok
  klient -> offer                     server -> accept / reject
  klient -> file + data ... -> end    server -> result
"""
import base64
import hashlib
import hmac
import os
import select
import socket
import ssl
import threading
import time
import uuid

from . import identity as ident
from . import pathsafe, proto

HANDSHAKE_TIMEOUT = 20
IO_TIMEOUT = 60
DECISION_TIMEOUT = 120
DISK_RESERVE = 256 * 1024 * 1024
PART_DIR = ".luxdrop-partial"
MAX_CONNECTIONS = 8
MAX_PROMPTS = 3


def log(msg):
    import sys
    print("luxdrop: " + msg, file=sys.stderr, flush=True)


def clean_name(name):
    if not isinstance(name, str):
        return "?"
    name = "".join(c for c in name if c.isprintable()).strip()
    return name[:63] or "?"


def fmt_addr(host, port):
    return ("[%s]:%d" if ":" in host else "%s:%d") % (host, port)


def parse_addr(text, default_port=proto.DEFAULT_PORT):
    """"host", "host:port", "[v6]:port" -> (host, port)."""
    text = text.strip()
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        return host, int(rest[1:]) if rest.startswith(":") else default_port
    if text.count(":") == 1:
        host, port = text.split(":")
        return host, int(port)
    return text, default_port


# TLS 1.3 sady (PROTOCOL.md 4.1): AES-256-GCM ma vzdy prednost. Aplikace LuxOS Companion pro
# Android prijme jen TLS_AES_256_GCM_SHA384 a Android (BoringSSL) nabizi jako klient AES-128
# nebo ChaCha20 na prvnim miste - rozhoduje proto poradi serveru.
TLS13_AES256 = "TLS_AES_256_GCM_SHA384"
TLS13_SERVER_ORDER = "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256"


def server_context(identity):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(identity.cert_path, identity.key_path)
    ctx.set_alpn_protocols([proto.ALPN])
    ctx.verify_mode = ssl.CERT_NONE  # klient se prokazuje podpisem ve zprave auth
    # Vybira server podle sveho poradi (Python to nastavuje i sam, tady vyslovne)
    ctx.options |= ssl.OP_CIPHER_SERVER_PREFERENCE
    if hasattr(ctx, "set_ciphersuites"):  # Python 3.15+; jinak vychozi poradi OpenSSL (AES-256 prvni)
        ctx.set_ciphersuites(TLS13_SERVER_ORDER)
    return ctx


def client_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    # Retezec certifikatu se neoveruje (self-signed); misto toho se pripina otisk
    # klice. Podpis CertificateVerify v TLS 1.3 OpenSSL overuje vzdy.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols([proto.ALPN])
    # Vychozi nabidka OpenSSL uz zacina AES-256-GCM. Android bez AES v hardwaru ale jako server
    # vybere ChaCha20 pred AES - od Pythonu 3.15 proto nabizime jen AES-256-GCM (umi ho kazda
    # implementace LuxDrop v1, viz PROTOCOL.md 4.1).
    if hasattr(ctx, "set_ciphersuites"):
        ctx.set_ciphersuites(TLS13_AES256)
    return ctx


def check_alpn(sock):
    alpn = sock.selected_alpn_protocol()
    if alpn is not None and alpn != proto.ALPN:
        raise proto.ProtocolError(proto.E_PROTO_VERSION, "unsupported ALPN %r" % alpn)


def check_proto(msg):
    v = msg.get("proto")
    if not isinstance(v, int) or v != proto.PROTO_VERSION:
        raise proto.ProtocolError(proto.E_PROTO_VERSION, "unsupported protocol version %r" % v)


def part_name(fp_sender, path, sha, size):
    h = hashlib.sha256(fp_sender + b"\0" + path.encode("utf-8") + b"\0" + sha + b"\0" + str(size).encode())
    return h.hexdigest()[:40] + ".part"


class Transfer:
    """Stav jednoho prenosu (pro UI)."""

    def __init__(self, direction, peer_name="", peer_id=""):
        self.id = uuid.uuid4().hex[:16]
        self.direction = direction  # "in" / "out"
        self.peer_name = peer_name
        self.peer_id = peer_id
        self.items = []
        self.total = 0
        self.done = 0
        self.state = "connecting"  # preparing, connecting, waiting, transferring, done, failed, cancelled, declined
        self.error = ""
        self.code = ""
        self.saved = []
        self.skipped = []
        self.resumed = 0
        self.sas = None
        self.protocol = "luxdrop"  # "luxdrop" nebo "localsend"
        self.device_type = "desktop"
        self.files = []  # jednotlive soubory pro UI: {"name", "size", "done", "state"}
        self.on_cancel = None  # LocalSend: zruseni relace u druhe strany
        self._cancel = threading.Event()
        self.sock = None

    def cancel(self):
        first = not self._cancel.is_set()
        self._cancel.set()
        if first and self.on_cancel is not None:
            try:
                self.on_cancel()
            except Exception:  # noqa: BLE001 - zruseni nesmi shodit UI
                pass
        if self.direction == "in" and self.sock is not None:
            # Prijemce prerusi spojeni; odesilatel to pozna jako chybu spojeni
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def fraction(self):
        return (self.done / self.total) if self.total else (1.0 if self.state == "done" else 0.0)


class IncomingRequest:
    """Dotaz na prijemce: prijmout prenos?"""

    def __init__(self, transfer, fp, trusted, sas, name_clash, files, dirs, protocol="luxdrop",
                 can_trust=None, verified=True, message=None, device_model=""):
        self.transfer = transfer
        self.fp = fp
        self.peer_name = transfer.peer_name
        self.peer_id = transfer.peer_id
        self.trusted = trusted
        self.sas = sas  # None, kdyz neni potreba overeni
        self.name_clash = name_clash  # jmeno duveryhodneho zarizeni, ale jiny klic
        self.items = transfer.items
        self.total = transfer.total
        self.nfiles = len(files)
        self.ndirs = len(dirs)
        self.withdrawn = threading.Event()  # odesilatel to mezitim zrusil
        self.protocol = protocol
        self.device_type = transfer.device_type
        self.device_model = device_model
        # LocalSend: nema overovaci kod; duverovat lze jen zarizeni s overenym certifikatem (mTLS)
        self.can_trust = bool(sas) if can_trust is None else can_trust
        self.verified = verified
        self.message = message  # textova zprava (LocalSend) - jen zobrazit


class Handler:
    """Rozhrani pro UI prijemce (prepise CLI a GUI)."""

    def ask(self, request):
        """Blokujici dotaz; vrati (prijmout, duverovat). Muze sledovat request.withdrawn."""
        return False, False

    def update(self, transfer):
        pass

    def finished(self, transfer):
        pass


# --- Prijem ------------------------------------------------------------------

class Receiver:
    def __init__(self, identity, settings, trust, history, handler, bind="", port=None):
        self.identity = identity
        self.settings = settings
        self.trust = trust
        self.history = history
        self.handler = handler
        self.bind = bind
        self.port = port or settings["port"]
        self.ctx = server_context(identity)
        self.sock = None
        self.active = set()
        self._conn_sem = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._prompt_sem = threading.BoundedSemaphore(MAX_PROMPTS)
        self._stop = threading.Event()
        self._parts_lock = threading.Lock()
        self._parts_busy = set()  # docasne soubory pouzivane prave probihajicimi prenosy

    def start(self):
        if self.bind:
            fam = socket.AF_INET6 if ":" in self.bind else socket.AF_INET
            self.sock = socket.create_server((self.bind, self.port), family=fam, reuse_port=False)
        elif socket.has_dualstack_ipv6():
            self.sock = socket.create_server(("", self.port), family=socket.AF_INET6, dualstack_ipv6=True)
        else:
            self.sock = socket.create_server(("", self.port))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True, name="luxdrop-accept").start()
        return self.port

    def stop(self):
        self._stop.set()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        for t in list(self.active):
            t.cancel()

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

    def handle(self, conn, addr):
        t = Transfer("in")
        ch = None
        try:
            conn.settimeout(HANDSHAKE_TIMEOUT)
            tls = self.ctx.wrap_socket(conn, server_side=True)
            t.sock = tls
            ch = proto.Channel(tls)
            check_alpn(tls)
            self._run(ch, tls, t, addr)
        except proto.ProtocolError as e:
            t.state, t.code, t.error = ("cancelled" if e.code == proto.E_CANCELLED else "failed"), e.code, e.message
            if ch and e.code not in (proto.E_CANCELLED,):
                ch.error(e.code, e.message)
        except (OSError, ssl.SSLError, ConnectionError) as e:
            if os.environ.get("LUXDROP_DEBUG"):
                import traceback
                traceback.print_exc()
            if t.cancelled:
                t.state, t.code, t.error = "cancelled", proto.E_CANCELLED, "cancelled"
            else:
                t.state, t.code, t.error = "failed", proto.E_PROTOCOL, "connection lost: %s" % e
        except Exception as e:  # noqa: BLE001 - chyba nesmi shodit prijimac
            t.state, t.code, t.error = "failed", proto.E_INTERNAL, "internal error: %s" % e
            if ch:
                ch.error(proto.E_INTERNAL, "internal error")
        finally:
            self.active.discard(t)
            # wrap_socket() prevzal deskriptor - zavrit se musi TLS soket. Jinak by zustal otevreny,
            # dokud UI drzi Transfer (t.sock), a odesilatel (napr. Android) by cekal na konec spojeni.
            for s in (t.sock, conn):
                try:
                    if s is not None:
                        s.close()
                except OSError:
                    pass
            t.sock = None
            if t.state in ("failed", "cancelled"):
                log("incoming from %s (%s): %s: %s" % (fmt_addr(addr[0], addr[1]), t.peer_id or "?", t.code, t.error))
            if t.items and t.state != "done" and t.state != "declined":
                self._log(t)
            if t.items:
                self.handler.finished(t)

    def _log(self, t):
        try:
            self.history.add({"direction": "in", "peer": t.peer_name, "peer_id": t.peer_id,
                              "items": t.items[:20], "total": t.total, "state": t.state,
                              "error": t.error, "saved": t.saved[:20]})
        except OSError:
            pass

    def _run(self, ch, tls, t, addr):
        # 1) hello od klienta: certifikat a zavazek k nonce
        hello = ch.recv_msg("hello")
        check_proto(hello)
        try:
            cert_der = base64.b64decode(hello.get("cert", ""), validate=True)
        except (ValueError, TypeError):
            raise proto.ProtocolError(proto.E_AUTH_FAILED, "invalid certificate encoding") from None
        fp_c, pub_c = ident.cert_fingerprint(cert_der)
        commitment = proto.hex32(hello.get("commit"), "commit")
        if fp_c == self.identity.fp:
            raise proto.ProtocolError(proto.E_AUTH_FAILED, "peer uses our own identity")
        t.peer_name = clean_name(hello.get("name"))
        t.peer_id = proto.short_id(fp_c)
        nonce_s = os.urandom(proto.NONCE_LEN)
        ch.send({"type": "hello", "proto": proto.PROTO_VERSION, "name": self.settings.name,
                 "id": self.identity.id, "nonce": nonce_s.hex()})

        # 2) auth: odhaleni nonce a podpis -> klient vlastni klic z certifikatu
        auth = ch.recv_msg("auth")
        nonce_c = proto.hex32(auth.get("nonce"), "nonce")
        if not proto.check_commit(commitment, nonce_c):
            raise proto.ProtocolError(proto.E_AUTH_FAILED, "nonce does not match commitment")
        try:
            sig = base64.b64decode(auth.get("sig", ""), validate=True)
        except (ValueError, TypeError):
            raise proto.ProtocolError(proto.E_AUTH_FAILED, "invalid signature encoding") from None
        msg = proto.auth_message(self.identity.fp, fp_c, nonce_s, nonce_c)
        if not ident.verify_signature(pub_c, sig, msg):
            raise proto.ProtocolError(proto.E_AUTH_FAILED, "invalid signature")

        # 3) kdo smi posilat
        self.settings.reload()
        trusted = self.trust.is_trusted(fp_c)
        mode = self.settings.mode()
        if mode == "off":
            raise proto.ProtocolError(proto.E_RECEIVING_OFF, "receiving is turned off")
        if not trusted and mode != "everyone":
            raise proto.ProtocolError(proto.E_NOT_TRUSTED, "only trusted devices can send to this computer")
        ch.send({"type": "auth_ok", "trusted": trusted})
        if trusted:
            self.trust.touch(fp_c, addr=None)

        # 4) nabidka
        tls.settimeout(IO_TIMEOUT)
        offer = ch.recv_msg("offer", "cancel")
        if offer["type"] == "cancel":
            raise proto.ProtocolError(proto.E_CANCELLED, "cancelled by sender")
        files, dirs, total = pathsafe.check_offer(offer)
        tops = []
        for parts in [f["parts"] for f in files] + dirs:
            if parts[0] not in tops:
                tops.append(parts[0])
        t.items, t.total = tops, total
        t.files = [{"name": f["path"], "size": f["size"], "done": 0, "state": "waiting"} for f in files]
        self.active.add(t)

        dest = self.settings.download_dir
        os.makedirs(dest, exist_ok=True)
        names = {os.path.join(dest, part_name(fp_c, f["path"], f["sha256"], f["size"])) for f in files}
        with self._parts_lock:
            if names & self._parts_busy:
                # Stejne soubory od stejneho odesilatele uz prave prichazeji jinym spojenim
                raise proto.ProtocolError(proto.E_BUSY, "the same files are already being received")
            self._parts_busy |= names
        try:
            return self._run_offer(ch, tls, t, fp_c, trusted, nonce_c, nonce_s, files, dirs, total, dest)
        finally:
            with self._parts_lock:
                self._parts_busy -= names

    def _run_offer(self, ch, tls, t, fp_c, trusted, nonce_c, nonce_s, files, dirs, total, dest):
        part_fd = self._open_part_dir(dest)
        try:
            offsets = self._resume_offsets(part_fd, fp_c, files)
            need = total - sum(offsets.values())
            free = os.statvfs(dest).f_bavail * os.statvfs(dest).f_frsize
            if need + DISK_RESERVE > free:
                raise proto.ProtocolError(proto.E_NO_SPACE, "not enough disk space (%d bytes needed)" % need)

            sas = proto.sas_code(fp_c, self.identity.fp, nonce_c, nonce_s)
            t.sas = sas
            accept, remember = self._decide(ch, tls, t, fp_c, trusted, sas, files, dirs)
            if not accept:
                t.state = "declined"
                ch.send({"type": "reject", "code": t.code or proto.E_DECLINED, "message": t.error or "declined"})
                return
            if remember and not trusted:
                self.trust.add(fp_c, t.peer_name)
            ch.send({"type": "accept", "resume": [{"index": i, "offset": o} for i, o in offsets.items() if o]})
            t.resumed = sum(offsets.values())
            t.done = t.resumed
            for f in files:
                t.files[f["index"]]["done"] = offsets.get(f["index"], 0)
            t.state = "transferring"
            self.handler.update(t)
            self._receive_files(ch, t, part_fd, fp_c, files, offsets)
            names = self._finalize(dest, part_fd, fp_c, files, dirs)
        finally:
            os.close(part_fd)
        try:
            os.rmdir(os.path.join(dest, PART_DIR))  # jen kdyz je prazdna (nic k navazani)
        except OSError:
            pass
        t.saved = [os.path.join(dest, n) for n in names]
        t.state = "done"
        ch.send({"type": "result", "ok": True, "saved": names})
        self._log(t)

    def _decide(self, ch, tls, t, fp_c, trusted, sas, files, dirs):
        if trusted and self.settings["auto_accept_trusted"]:
            return True, False
        if not self._prompt_sem.acquire(blocking=False):
            raise proto.ProtocolError(proto.E_BUSY, "too many pending requests")
        try:
            clash = (not trusted) and t.peer_name.lower() in self.trust.names()
            req = IncomingRequest(t, fp_c, trusted, None if trusted else sas, clash, files, dirs)
            t.state = "waiting"
            result = {}
            done = threading.Event()

            def ask():
                try:
                    result["v"] = self.handler.ask(req)
                except Exception:  # noqa: BLE001
                    result["v"] = (False, False)
                done.set()

            threading.Thread(target=ask, daemon=True).start()
            deadline = time.monotonic() + DECISION_TIMEOUT
            # Behem cekani sledujeme, zda odesilatel nezrusil (zprava cancel / konec spojeni)
            while True:
                finished = done.wait(0.3)
                if t.cancelled:
                    req.withdrawn.set()
                    raise proto.ProtocolError(proto.E_CANCELLED, "cancelled")
                r, _w, _x = select.select([tls], [], [], 0)
                if r or tls.pending():
                    # Odesilatel poslal cancel nebo zavrel spojeni (i tesne pred rozhodnutim)
                    req.withdrawn.set()
                    try:
                        msg = ch.recv_msg("cancel")
                        reason = msg.get("reason", "")
                    except (ConnectionError, OSError):
                        reason = "connection closed"
                    raise proto.ProtocolError(proto.E_CANCELLED, "cancelled by sender: %s" % reason)
                if finished:
                    return result["v"]
                if time.monotonic() > deadline:
                    req.withdrawn.set()
                    t.code, t.error = proto.E_TIMEOUT, "no answer"
                    return False, False
        finally:
            self._prompt_sem.release()

    @staticmethod
    def _open_part_dir(dest):
        dfd = os.open(dest, os.O_RDONLY | os.O_DIRECTORY)
        try:
            try:
                os.mkdir(PART_DIR, 0o700, dir_fd=dfd)
            except FileExistsError:
                pass
            # O_NOFOLLOW: podstrceny symlink misto adresare se odmitne
            return os.open(PART_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dfd)
        finally:
            os.close(dfd)

    @staticmethod
    def _resume_offsets(part_fd, fp_c, files):
        offsets = {}
        for f in files:
            name = part_name(fp_c, f["path"], f["sha256"], f["size"])
            try:
                st = os.stat(name, dir_fd=part_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            import stat as _st
            if not _st.S_ISREG(st.st_mode):
                raise proto.ProtocolError(proto.E_INTERNAL, "unexpected file in partial directory")
            if st.st_size > f["size"]:
                os.unlink(name, dir_fd=part_fd)
                continue
            offsets[f["index"]] = st.st_size
        return offsets

    def _receive_files(self, ch, t, part_fd, fp_c, files, offsets):
        by_index = {f["index"]: f for f in files}
        received = set()
        digests = {}
        expected_next = 0
        last_ui = 0.0
        while True:
            ftype, msg = ch.recv()
            if ftype != proto.FRAME_JSON:
                raise proto.ProtocolError(proto.E_PROTOCOL, "data without a file header")
            if msg["type"] == "cancel":
                raise proto.ProtocolError(proto.E_CANCELLED, "cancelled by sender")
            if msg["type"] == "error":
                raise proto.ProtocolError(msg.get("code", proto.E_PROTOCOL), str(msg.get("message", ""))[:500])
            if msg["type"] == "end":
                break
            if msg["type"] != "file":
                raise proto.ProtocolError(proto.E_PROTOCOL, "unexpected message '%s'" % msg["type"])
            idx, off = msg.get("index"), msg.get("offset")
            f = by_index.get(idx) if isinstance(idx, int) else None
            if f is None or idx < expected_next or idx in received:
                raise proto.ProtocolError(proto.E_PROTOCOL, "invalid file index")
            if off != offsets.get(idx, 0):
                raise proto.ProtocolError(proto.E_PROTOCOL, "offset differs from the accepted one")
            expected_next = idx + 1
            received.add(idx)
            ui = t.files[idx]
            ui["state"] = "receiving"
            name = part_name(fp_c, f["path"], f["sha256"], f["size"])
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=part_fd)
            with os.fdopen(fd, "r+b") as out:
                out.truncate(off)
                # Navazani: SHA-256 nejdriv z uz prijate casti
                h = hashlib.sha256()
                left = off
                while left > 0:
                    b = out.read(min(1 << 20, left))
                    if not b:
                        raise proto.ProtocolError(proto.E_INTERNAL, "partial file is shorter than expected")
                    h.update(b)
                    left -= len(b)
                out.seek(off)
                remaining = f["size"] - off
                while remaining > 0:
                    ftype, data = ch.recv()
                    if ftype == proto.FRAME_JSON:
                        if data["type"] == "cancel":
                            out.flush()
                            raise proto.ProtocolError(proto.E_CANCELLED, "cancelled by sender")
                        raise proto.ProtocolError(proto.E_PROTOCOL, "file data ended early")
                    if len(data) > remaining:
                        raise proto.ProtocolError(proto.E_PROTOCOL, "more data than announced")
                    out.write(data)
                    h.update(data)
                    remaining -= len(data)
                    t.done += len(data)
                    ui["done"] += len(data)
                    now = time.monotonic()
                    if now - last_ui > 0.1:
                        last_ui = now
                        self.handler.update(t)
                out.flush()
                os.fsync(out.fileno())
            digests[idx] = h.digest()
            ui["state"] = "done"
        # Kontrola SHA-256 vsech souboru (i tech dokoncenych v drivejsim pokusu)
        bad = []
        for f in files:
            name = part_name(fp_c, f["path"], f["sha256"], f["size"])
            if f["index"] in digests:
                good = hmac.compare_digest(digests[f["index"]], f["sha256"])
            else:
                if f["size"] == 0:
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=part_fd)
                    os.close(fd)
                good = verify_part(part_fd, name, f["size"], f["sha256"])
            if not good:
                bad.append(f)
        if bad:
            for f in bad:
                try:
                    os.unlink(part_name(fp_c, f["path"], f["sha256"], f["size"]), dir_fd=part_fd)
                except OSError:
                    pass
            ch.send({"type": "result", "ok": False, "code": proto.E_HASH_MISMATCH,
                     "failed": [f["index"] for f in bad]})
            raise proto.ProtocolError(proto.E_HASH_MISMATCH,
                                      "checksum mismatch: %s" % ", ".join(f["path"] for f in bad[:5]))

    @staticmethod
    def _finalize(dest, part_fd, fp_c, files, dirs):
        """Presune overene soubory z .luxdrop-partial do cile; nic neprepise."""
        dfd = os.open(dest, os.O_RDONLY | os.O_DIRECTORY)
        names = {}
        try:
            tops_dir = {p[0] for p in dirs} | {f["parts"][0] for f in files if len(f["parts"]) > 1}
            for top in sorted(tops_dir):
                names[top] = _reserve_dir(dfd, top)
            fds = {}

            def dir_fd(parts):
                # Otevre/vytvori podslozku bez nasledovani symlinku
                if parts in fds:
                    return fds[parts]
                if len(parts) == 1:
                    fd = os.open(names[parts[0]], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dfd)
                else:
                    parent = dir_fd(parts[:-1])
                    try:
                        os.mkdir(parts[-1], 0o755, dir_fd=parent)
                    except FileExistsError:
                        pass
                    fd = os.open(parts[-1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                fds[parts] = fd
                return fd

            try:
                for parts in sorted(dirs, key=len):
                    dir_fd(parts)
                for f in files:
                    src = part_name(fp_c, f["path"], f["sha256"], f["size"])
                    fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=part_fd)
                    try:
                        os.fchmod(fd, 0o755 if f["exec"] else 0o644)
                    finally:
                        os.close(fd)
                    if len(f["parts"]) == 1:
                        names[f["parts"][0]] = _place_file(part_fd, src, dfd, f["parts"][0])
                    else:
                        parent = dir_fd(f["parts"][:-1])
                        _place_file(part_fd, src, parent, f["parts"][-1], unique=False)
            finally:
                for fd in fds.values():
                    os.close(fd)
        finally:
            os.close(dfd)
        return [names[k] for k in names]


def _unique_names(name):
    yield name
    stem, ext = os.path.splitext(name)
    if not stem:
        stem, ext = name, ""
    n = 1
    while True:
        yield "%s (%d)%s" % (stem, n, ext)
        n += 1


def _reserve_dir(dfd, name):
    for cand in _unique_names(name):
        try:
            os.mkdir(cand, 0o755, dir_fd=dfd)
            return cand
        except FileExistsError:
            continue


def _place_file(src_fd, src, dst_fd, name, unique=True):
    """Presun bez prepsani: link() selze, pokud cil existuje."""
    for cand in (_unique_names(name) if unique else [name]):
        try:
            os.link(src, cand, src_dir_fd=src_fd, dst_dir_fd=dst_fd, follow_symlinks=False)
            os.unlink(src, dir_fd=src_fd)
            return cand
        except FileExistsError:
            if not unique:
                raise proto.ProtocolError(proto.E_INVALID_OFFER, "file already exists: %s" % name) from None
            continue
        except OSError:
            # Souborovy system bez hardlinku (FAT/exFAT): kontrola + rename
            try:
                os.stat(cand, dir_fd=dst_fd, follow_symlinks=False)
                if not unique:
                    raise proto.ProtocolError(proto.E_INVALID_OFFER, "file already exists: %s" % name)
                continue
            except FileNotFoundError:
                os.rename(src, cand, src_dir_fd=src_fd, dst_dir_fd=dst_fd)
                return cand
    raise proto.ProtocolError(proto.E_INTERNAL, "cannot place file")


def verify_part(part_fd, name, size, sha):
    """Overi velikost a SHA-256 docasneho souboru."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=part_fd)
    except OSError:
        return False
    h = hashlib.sha256()
    n = 0
    with os.fdopen(fd, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
            n += len(b)
    return n == size and h.digest() == sha


def sha256_file(path, nofollow, progress=None, cancel=None):
    flags = os.O_RDONLY | (os.O_NOFOLLOW if nofollow else 0)
    h = hashlib.sha256()
    n = 0
    with os.fdopen(os.open(path, flags), "rb") as f:
        while True:
            if cancel is not None and cancel.is_set():
                raise proto.ProtocolError(proto.E_CANCELLED, "cancelled")
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
            n += len(b)
            if progress:
                progress(len(b))
    return h.digest(), n


# --- Odesilani ---------------------------------------------------------------

class SendCallbacks:
    def confirm(self, info, replied):
        """Overeni kodu u odesilatele (neduveryhodny prijemce).

        info: slovnik peer_name, peer_id, fp, sas, trusted_by_peer. replied: Event, nastaven, kdyz
        prijemce mezitim odpovedel (napr. odmitl). Vrati (shoda, zapamatovat)."""
        return False, False

    def update(self, transfer):
        pass


def send(identity, settings, trust, history, host, port, paths, callbacks, transfer=None,
         expected_fp=None, hello_extra=None):
    """Odesle soubory; vrati Transfer (state done/failed/...). Nevyhazuje vyjimky protokolu."""
    t = transfer or Transfer("out")
    try:
        _send(identity, settings, trust, host, port, paths, callbacks, t, expected_fp, hello_extra)
    except proto.ProtocolError as e:
        t.code, t.error = e.code, e.message
        t.state = {"declined": "declined", "cancelled": "cancelled"}.get(e.code, "failed")
    except (OSError, ssl.SSLError, ConnectionError) as e:
        detail = e.strerror if isinstance(e, OSError) and e.strerror else str(e)
        if t.cancelled:
            t.state, t.code, t.error = "cancelled", proto.E_CANCELLED, "cancelled"
        elif t.state in ("transferring", "waiting"):
            t.state, t.code = "failed", proto.E_PROTOCOL
            t.error = "connection lost - the receiver cancelled or went offline (%s)" % detail
        else:
            t.state, t.code, t.error = "failed", proto.E_PROTOCOL, "connection failed: %s" % detail
    finally:
        if t.sock is not None:
            try:
                t.sock.close()
            except OSError:
                pass
    if t.items:
        try:
            history.add({"direction": "out", "peer": t.peer_name, "peer_id": t.peer_id, "items": t.items[:20],
                         "total": t.total, "state": t.state, "error": t.error})
        except OSError:
            pass
    callbacks.update(t)
    return t


def _abort_waiting(ch, tls, replied, reason):
    """Zruseni behem cekani na odpoved prijemce.

    Kdyz ctecka odpovedi jeste bezi, nesmime do TLS soketu zaroven zapisovat
    z jineho vlakna - spojeni proto jen zavreme (prijemce to bere jako zruseni).
    """
    if replied.is_set():
        try:
            ch.send({"type": "cancel", "reason": reason})
        except OSError:
            pass
    else:
        try:
            tls.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _send(identity, settings, trust, host, port, paths, cb, t, expected_fp, hello_extra):
    t.state = "preparing"
    items, dirs = pathsafe.collect(paths, on_skip=lambda p, why: t.skipped.append((p, why)))
    if not items and not dirs:
        raise proto.ProtocolError(proto.E_INVALID_OFFER, "nothing to send")
    tops = []
    for _p, rel, _s, _x in items:
        if rel.split("/")[0] not in tops:
            tops.append(rel.split("/")[0])
    for d in dirs:
        if d.split("/")[0] not in tops:
            tops.append(d.split("/")[0])
    t.items = tops
    t.total = sum(s for _p, _r, s, _x in items)
    cb.update(t)

    # SHA-256 pred odeslanim (v nabidce; umoznuje navazani prenosu)
    files = []
    hashed = [0]

    def prog(n):
        hashed[0] += n
        t.done = hashed[0]
        cb.update(t)

    for local, rel, size, ex in items:
        digest, n = sha256_file(local, nofollow="/" in rel, progress=prog, cancel=t._cancel)
        if n != size:
            raise proto.ProtocolError(proto.E_INTERNAL, "file changed while reading: %s" % local)
        files.append({"path": rel, "size": size, "sha256": digest.hex(), "exec": ex})
    t.done = 0
    t.files = [{"name": f["path"], "size": f["size"], "done": 0, "state": "waiting"} for f in files]

    # Spojeni + TLS
    t.state = "connecting"
    cb.update(t)
    raw = socket.create_connection((host, port), timeout=HANDSHAKE_TIMEOUT)
    tls = client_context().wrap_socket(raw, server_hostname=None)
    t.sock = tls
    check_alpn(tls)
    fp_s, _pub = ident.cert_fingerprint(tls.getpeercert(binary_form=True))
    t.peer_id = proto.short_id(fp_s)
    if expected_fp is not None and fp_s != expected_fp:
        # Pripnute zarizeni predstavuje jiny klic -> mozny utok, nic neposilat
        raise proto.ProtocolError(proto.E_KEY_MISMATCH,
                                  "the device at %s presented a different key than the trusted device "
                                  "(expected %s, got %s)" % (fmt_addr(host, port), proto.short_id(expected_fp), t.peer_id))
    if fp_s == identity.fp:
        raise proto.ProtocolError(proto.E_AUTH_FAILED, "cannot send to this computer itself")
    peer_trusted = trust.is_trusted(fp_s)
    ch = proto.Channel(tls)

    nonce_c = os.urandom(proto.NONCE_LEN)
    hello = {"type": "hello", "proto": proto.PROTO_VERSION, "name": settings.name, "id": identity.id,
             "cert": base64.b64encode(identity.cert_der).decode(), "commit": proto.commit(nonce_c).hex()}
    if hello_extra:
        hello.update(hello_extra)
    ch.send(hello)
    sh = ch.recv_msg("hello")
    check_proto(sh)
    t.peer_name = clean_name(sh.get("name"))
    nonce_s = proto.hex32(sh.get("nonce"), "nonce")
    sig = identity.sign(proto.auth_message(fp_s, identity.fp, nonce_s, nonce_c))
    ch.send({"type": "auth", "nonce": nonce_c.hex(), "sig": base64.b64encode(sig).decode()})
    ok = ch.recv_msg("auth_ok")
    trusted_by_peer = bool(ok.get("trusted"))
    sas = proto.sas_code(identity.fp, fp_s, nonce_c, nonce_s)
    t.sas = sas

    ch.send({"type": "offer", "transfer_id": t.id, "files": files, "dirs": dirs, "total": t.total})
    t.state = "waiting"
    cb.update(t)

    # Odpoved prijemce cteme ve vlakne, aby slo zaroven overit kod u odesilatele
    tls.settimeout(DECISION_TIMEOUT + 30)
    reply, replied = {}, threading.Event()

    def read_reply():
        try:
            reply["msg"] = ch.recv_msg("accept", "reject", "error")
        except Exception as e:  # noqa: BLE001
            reply["exc"] = e
        replied.accepted = reply.get("msg", {}).get("type") == "accept"
        replied.set()

    reader = threading.Thread(target=read_reply, daemon=True)
    reader.start()
    remember = False
    if not peer_trusted:
        info = {"peer_name": t.peer_name, "peer_id": t.peer_id, "fp": fp_s, "sas": sas,
                "trusted_by_peer": trusted_by_peer}
        match, remember = cb.confirm(info, replied)
        declined = replied.is_set() and reply.get("msg", {}).get("type") != "accept"
        if not match and not declined:
            _abort_waiting(ch, tls, replied, proto.E_SAS_REJECTED)
            raise proto.ProtocolError(proto.E_SAS_REJECTED, "verification code not confirmed")
    while not replied.wait(0.2):
        if t.cancelled:
            _abort_waiting(ch, tls, replied, "cancelled")
            raise proto.ProtocolError(proto.E_CANCELLED, "cancelled")
    if "exc" in reply:
        raise reply["exc"]
    msg = reply["msg"]
    if msg["type"] == "reject":
        code = msg.get("code") if msg.get("code") in proto.ERROR_CODES else proto.E_DECLINED
        raise proto.ProtocolError(code, str(msg.get("message", code))[:500])
    if remember and not peer_trusted:
        trust.add(fp_s, t.peer_name, addr=fmt_addr(host, port))
    elif peer_trusted:
        trust.touch(fp_s, name=t.peer_name, addr=fmt_addr(host, port))

    resume = {}
    for r in msg.get("resume", []) or []:
        if isinstance(r, dict) and isinstance(r.get("index"), int) and isinstance(r.get("offset"), int):
            resume[r["index"]] = r["offset"]
    tls.settimeout(IO_TIMEOUT)
    t.state = "transferring"
    t.resumed = 0
    for i, f in enumerate(files):
        off = resume.get(i, 0)
        if off < 0 or off > f["size"]:
            raise proto.ProtocolError(proto.E_PROTOCOL, "invalid resume offset")
        t.resumed += off
        t.files[i]["done"] = off
    t.done = t.resumed
    cb.update(t)
    rate = float(os.environ.get("LUXDROP_TEST_RATE", "0") or 0)  # jen pro testy (bajty/s)
    start, sent, last_ui = time.monotonic(), 0, 0.0
    for i, (f, (local, rel, _size, _x)) in enumerate(zip(files, items)):
        off = resume.get(i, 0)
        ui = t.files[i]
        if off == f["size"]:
            ui["state"] = "done"
            continue
        ui["state"] = "sending"
        ch.send({"type": "file", "index": i, "offset": off})
        flags = os.O_RDONLY | (os.O_NOFOLLOW if "/" in rel else 0)
        with os.fdopen(os.open(local, flags), "rb") as fh:
            fh.seek(off)
            remaining = f["size"] - off
            while remaining > 0:
                if t.cancelled:
                    ch.send({"type": "cancel", "reason": "cancelled"})
                    raise proto.ProtocolError(proto.E_CANCELLED, "cancelled")
                data = fh.read(min(proto.CHUNK, remaining))
                if not data:
                    ch.send({"type": "error", "code": proto.E_INTERNAL, "message": "file shrank while sending"})
                    raise proto.ProtocolError(proto.E_INTERNAL, "file changed while sending: %s" % local)
                ch.send_data(data)
                remaining -= len(data)
                sent += len(data)
                t.done += len(data)
                ui["done"] += len(data)
                now = time.monotonic()
                if now - last_ui > 0.1:
                    last_ui = now
                    cb.update(t)
                if rate:
                    ahead = sent / rate - (now - start)
                    if ahead > 0:
                        time.sleep(ahead)
        ui["state"] = "done"
    ch.send({"type": "end"})
    tls.settimeout(max(IO_TIMEOUT, 30 + t.total / (50 * 1024 * 1024)))  # prijemce kontroluje SHA-256
    res = ch.recv_msg("result")
    if not res.get("ok"):
        code = res.get("code") if res.get("code") in proto.ERROR_CODES else proto.E_INTERNAL
        raise proto.ProtocolError(code, "receiver rejected the data (%s)" % code)
    t.saved = [str(n) for n in res.get("saved", [])][:100]
    t.state = "done"
