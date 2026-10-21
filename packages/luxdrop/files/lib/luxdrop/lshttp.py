"""LuxDrop - minimalni HTTP/1.1 nad TLS pro LocalSend (server s mTLS a klient).

Server pouziva pyOpenSSL: LocalSend klienty se prokazuji self-signed certifikatem
(mTLS) a stdlib ssl neumi prijmout libovolny klientsky certifikat bez CA. Totoznost
klienta je otisk jeho certifikatu; drzeni klice overi TLS (CertificateVerify).
Klient pouziva stdlib ssl (http.client) a otisk serveru kontroluje hned po handshake,
jeste pred odeslanim jakychkoli dat.
"""
import http.client
import json
import socket
import ssl
import struct
import urllib.parse

from . import localsend

MAX_LINE = 8192
MAX_HEADERS = 64
CHUNK = 256 * 1024


class HTTPError(Exception):
    def __init__(self, status, message=""):
        super().__init__(message or str(status))
        self.status = status
        self.message = message or REASONS.get(status, "Error")


REASONS = {200: "OK", 204: "No Content", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
           404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 411: "Length Required",
           413: "Payload Too Large", 422: "Unprocessable Entity", 429: "Too Many Requests",
           431: "Request Header Fields Too Large", 500: "Internal Server Error", 507: "Insufficient Storage"}


# --- Server (pyOpenSSL) ----------------------------------------------------------

def server_context(identity):
    """TLS kontext serveru: nas certifikat, klientsky certifikat volitelny a bez CA."""
    from OpenSSL import SSL
    ctx = SSL.Context(SSL.TLS_SERVER_METHOD)
    ctx.set_min_proto_version(SSL.TLS1_2_VERSION)
    ctx.use_certificate_file(identity.cert_path)
    ctx.use_privatekey_file(identity.key_path)
    ctx.check_privatekey()
    # Libovolny klientsky certifikat: identitu urcuje otisk (kontrola po handshake)
    ctx.set_verify(SSL.VERIFY_PEER, lambda *_a: True)
    ctx.set_options(SSL.OP_NO_TICKET | SSL.OP_NO_RENEGOTIATION if hasattr(SSL, "OP_NO_RENEGOTIATION")
                    else SSL.OP_NO_TICKET)
    ctx.set_session_cache_mode(SSL.SESS_CACHE_OFF)

    def alpn(_conn, protos):
        return b"http/1.1" if b"http/1.1" in protos else SSL.NO_OVERLAPPING_PROTOCOLS

    ctx.set_alpn_select_callback(alpn)
    return ctx


def set_timeout(sock, seconds):
    """Casovy limit pro blokujici socket (pyOpenSSL nesnasi socket.settimeout)."""
    tv = struct.pack("ll", int(seconds), int((seconds % 1) * 1e6))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO, tv)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, tv)


class TLSServerConn:
    """Obal spojeni pyOpenSSL: recv/sendall s chybami jako ConnectionError."""

    def __init__(self, ctx, sock, timeout=20):
        from OpenSSL import SSL
        self.SSL = SSL
        self.sock = sock
        sock.setblocking(True)
        set_timeout(sock, timeout)
        self.conn = SSL.Connection(ctx, sock)
        self.conn.set_accept_state()
        self.cert_der = None

    def handshake(self):
        try:
            self.conn.do_handshake()
        except self.SSL.Error as e:
            raise ConnectionError("TLS handshake failed: %s" % e) from None
        # Na strane serveru get_peer_cert_chain() list neobsahuje -> get_peer_certificate()
        try:
            cert = self.conn.get_peer_certificate(as_cryptography=True)
        except TypeError:  # starsi pyOpenSSL
            c = self.conn.get_peer_certificate()
            cert = c.to_cryptography() if c is not None else None
        if cert is not None:
            from cryptography.hazmat.primitives import serialization
            self.cert_der = cert.public_bytes(serialization.Encoding.DER)

    def timeout(self, seconds):
        set_timeout(self.sock, seconds)

    def recv(self, n):
        SSL = self.SSL
        try:
            return self.conn.recv(n)
        except SSL.ZeroReturnError:
            return b""
        except SSL.WantReadError:
            raise TimeoutError("read timed out") from None
        except SSL.SysCallError as e:
            if e.args and e.args[0] == -1:
                return b""  # neocekavany konec spojeni
            raise ConnectionError(str(e)) from None
        except SSL.Error as e:
            raise ConnectionError(str(e)) from None

    def pending(self):
        return self.conn.pending()

    def sendall(self, data):
        try:
            self.conn.sendall(data)
        except (self.SSL.Error, OSError) as e:
            raise ConnectionError(str(e)) from None

    def close(self):
        try:
            self.conn.shutdown()
        except Exception:  # noqa: BLE001 - spojeni uz muze byt mrtve
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def abort(self):
        """Okamzite preruseni (z jineho vlakna)."""
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


class Reader:
    def __init__(self, conn):
        self.conn = conn
        self.buf = bytearray()

    def _fill(self):
        b = self.conn.recv(65536)
        if not b:
            return False
        self.buf += b
        return True

    def readline(self):
        while True:
            i = self.buf.find(b"\n")
            if i >= 0:
                line = bytes(self.buf[:i + 1])
                del self.buf[:i + 1]
                return line
            if len(self.buf) > MAX_LINE:
                raise HTTPError(431, "line too long")
            if not self._fill():
                if self.buf:
                    raise ConnectionError("connection closed mid-line")
                return b""

    def read(self, n):
        """Az n bajtu (b"" = konec spojeni)."""
        if not self.buf and not self._fill():
            return b""
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def read_exact(self, n):
        out = bytearray()
        while len(out) < n:
            b = self.read(n - len(out))
            if not b:
                raise ConnectionError("connection closed")
            out += b
        return bytes(out)


class Body:
    """Telo pozadavku: Content-Length nebo chunked."""

    def __init__(self, reader, length=None, chunked=False):
        self.r = reader
        self.left = length or 0
        self.chunked = chunked
        self.chunk_left = 0
        self.done = not chunked and not length

    def read(self, n=CHUNK):
        if self.done:
            return b""
        if not self.chunked:
            b = self.r.read(min(n, self.left))
            if not b:
                raise ConnectionError("body ended early")
            self.left -= len(b)
            self.done = self.left == 0
            return b
        if self.chunk_left == 0:
            line = self.r.readline()
            if not line:
                raise ConnectionError("body ended early")
            try:
                size = int(line.split(b";")[0].strip(), 16)
            except ValueError:
                raise HTTPError(400, "invalid chunk") from None
            if size == 0:
                while True:  # trailery az po prazdny radek
                    t = self.r.readline()
                    if t in (b"\r\n", b"\n", b""):
                        break
                self.done = True
                return b""
            self.chunk_left = size
        b = self.r.read(min(n, self.chunk_left))
        if not b:
            raise ConnectionError("body ended early")
        self.chunk_left -= len(b)
        if self.chunk_left == 0:
            if self.r.read_exact(2) != b"\r\n":
                raise HTTPError(400, "invalid chunk end")
        return b

    def read_all(self, limit):
        out = bytearray()
        while True:
            b = self.read()
            if not b:
                return bytes(out)
            out += b
            if len(out) > limit:
                raise HTTPError(413, "body too large")

    def drain(self, limit=1 << 20):
        """Docte zbytek tela (pro keep-alive); vrati False, kdyz je ho prilis."""
        n = 0
        while not self.done:
            b = self.read()
            if not b:
                break
            n += len(b)
            if n > limit:
                return False
        return True


class Request:
    def __init__(self, method, target, headers, body, ip, cert_der):
        self.method = method
        parsed = urllib.parse.urlsplit(target)
        self.path = parsed.path
        self.query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
        self.headers = headers
        self.body = body
        self.ip = ip
        self.cert_der = cert_der

    def json(self, limit=localsend.MAX_JSON):
        try:
            obj = json.loads(self.body.read_all(limit).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HTTPError(400, "Invalid body") from None
        return obj


def read_request(reader, ip, cert_der):
    """Precte hlavicku pozadavku; None = klient zavrel spojeni mezi pozadavky."""
    line = reader.readline()
    while line in (b"\r\n", b"\n"):
        line = reader.readline()
    if not line:
        return None
    try:
        method, target, version = line.decode("latin-1").strip().split(" ")
    except ValueError:
        raise HTTPError(400, "invalid request line") from None
    if not version.startswith("HTTP/1."):
        raise HTTPError(400, "unsupported HTTP version")
    headers = {}
    for _i in range(MAX_HEADERS + 1):
        h = reader.readline()
        if h in (b"\r\n", b"\n"):
            break
        if not h:
            raise ConnectionError("connection closed in headers")
        k, sep, v = h.decode("latin-1").partition(":")
        if not sep:
            raise HTTPError(400, "invalid header")
        headers[k.strip().lower()] = v.strip()
    else:
        raise HTTPError(431, "too many headers")
    te = headers.get("transfer-encoding", "").lower()
    if te and te != "chunked":
        raise HTTPError(400, "unsupported transfer encoding")
    if te == "chunked":
        body = Body(reader, chunked=True)
    else:
        cl = headers.get("content-length", "0") or "0"
        if not cl.isdigit() or len(cl) > 18:
            raise HTTPError(400, "invalid content length")
        body = Body(reader, length=int(cl))
    req = Request(method, target, headers, body, ip, cert_der)
    req.keep_alive = version == "HTTP/1.1" and headers.get("connection", "").lower() != "close"
    return req


def response_bytes(status, obj=None, close=False):
    if obj is None and status >= 400:
        obj = {"message": REASONS.get(status, "Error")}
    body = b"" if obj is None else json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    head = ["HTTP/1.1 %d %s" % (status, REASONS.get(status, "Status")),
            "Content-Length: %d" % len(body)]
    if body:
        head.append("Content-Type: application/json; charset=utf-8")
    if close:
        head.append("Connection: close")
    return ("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + body


# --- Klient (stdlib ssl) -------------------------------------------------------

class PinError(Exception):
    """Server predlozil jiny certifikat, nez jsme cekali."""

    def __init__(self, expected, got):
        super().__init__("certificate fingerprint mismatch: expected %s, got %s" % (expected[:16], got[:16]))
        self.expected = expected
        self.got = got


def client_context(identity):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    # Self-signed certifikat: retezec se neoveruje, misto toho se kontroluje otisk
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols(["http/1.1"])
    if identity is not None:
        # Nove verze LocalSend vyzaduji klientsky certifikat (mTLS)
        ctx.load_cert_chain(identity.cert_path, identity.key_path)
    return ctx


def fmt_host(host):
    return "[%s]" % host if ":" in host else host


class Client:
    """Jedno HTTPS spojeni k zarizeni LocalSend s kontrolou otisku."""

    def __init__(self, identity, host, port, expected_fp=None, timeout=10, check=None):
        self.host, self.port = host, port
        self.conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=client_context(identity))
        self.expected_fp = localsend.norm_fp(expected_fp) if expected_fp else None
        self.check = check  # check(cert_der) -> vyhodi vyjimku, kdyz certifikat nesedi
        self.cert_der = None
        self.fingerprint = None

    def connect(self):
        self.conn.connect()
        self.cert_der = self.conn.sock.getpeercert(binary_form=True)
        if not self.cert_der:
            raise ConnectionError("no server certificate")
        self.fingerprint = localsend.cert_fingerprint(self.cert_der)
        if self.expected_fp and self.fingerprint != self.expected_fp:
            self.close()
            raise PinError(self.expected_fp, self.fingerprint)
        if self.check:
            self.check(self.cert_der)

    def settimeout(self, t):
        if self.conn.sock:
            self.conn.sock.settimeout(t)

    def abort(self):
        try:
            if self.conn.sock:
                self.conn.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def close(self):
        try:
            self.conn.close()
        except OSError:
            pass

    def _url(self, path, query):
        return path + ("?" + urllib.parse.urlencode(query) if query else "")

    def request_json(self, method, path, obj=None, query=None, limit=localsend.MAX_JSON):
        """Vrati (status, json|None)."""
        if self.cert_der is None:
            self.connect()
        body = None if obj is None else json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"} if body is not None else {"Content-Length": "0"}
        self.conn.request(method, self._url(path, query), body=body, headers=headers)
        return self._response(limit)

    def _response(self, limit):
        res = self.conn.getresponse()
        data = res.read(limit + 1)
        if len(data) > limit:
            raise HTTPError(413, "response too large")
        out = None
        if data:
            try:
                out = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                out = None
        return res.status, out

    def upload(self, path, query, size, chunks):
        """POST s telem z iteratoru chunks (presne size bajtu); vrati (status, json|None)."""
        if self.cert_der is None:
            self.connect()
        self.conn.putrequest("POST", self._url(path, query))
        self.conn.putheader("Content-Type", "application/octet-stream")
        self.conn.putheader("Content-Length", str(size))
        self.conn.endheaders()
        sent = 0
        for b in chunks:
            self.conn.send(b)
            sent += len(b)
        if sent != size:
            raise ConnectionError("file size changed while sending")
        return self._response(1 << 20)
