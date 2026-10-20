"""LuxDrop - protokol: konstanty, ramce, SAS a podepisovana data (viz PROTOCOL.md).

Modul nema zavislosti mimo stdlib, aby sel snadno otestovat a prepsat (Android).
"""
import hashlib
import hmac
import json
import struct

PROTO_VERSION = 1
SERVICE_TYPE = "_luxdrop._tcp"
DEFAULT_PORT = 47923
ALPN = "luxdrop/1"

# Typy ramcu: 1 bajt typ + 4 bajty delka (big-endian) + data
FRAME_JSON = 0x4A  # 'J' - zprava v JSON (UTF-8, objekt s polem "type")
FRAME_DATA = 0x44  # 'D' - surova data souboru
HEADER = struct.Struct(">BI")
MAX_JSON = 16 * 1024 * 1024   # nabidka slozky s mnoha soubory
MAX_DATA = 1024 * 1024        # jeden datovy ramec
CHUNK = 256 * 1024            # velikost ramce, kterou posilame my

AUTH_LABEL = b"LUXDROP-AUTH-v1"
SAS_LABEL = b"LUXDROP-SAS-v1"
NONCE_LEN = 32

# Chybove kody (pole "code" ve zprave "error" / "reject")
E_DECLINED = "declined"          # prijemce odmitl
E_TIMEOUT = "timeout"            # prijemce nerozhodl vcas
E_BUSY = "busy"                  # prilis mnoho soucasnych pozadavku
E_NOT_TRUSTED = "not_trusted"    # rezim "jen duveryhodna zarizeni" a odesilatel neni duveryhodny
E_RECEIVING_OFF = "receiving_off"
E_TOO_LARGE = "too_large"
E_NO_SPACE = "no_space"
E_INVALID_OFFER = "invalid_offer"  # nebezpecna cesta, duplicita, limity
E_AUTH_FAILED = "auth_failed"
E_PROTO_VERSION = "proto_version"
E_PROTOCOL = "protocol_error"
E_HASH_MISMATCH = "hash_mismatch"
E_CANCELLED = "cancelled"
E_INTERNAL = "internal"
E_KEY_MISMATCH = "key_mismatch"  # jen lokalne u odesilatele: jiny klic nez pripnuty
E_SAS_REJECTED = "sas_rejected"  # odesilatel nepotvrdil shodu kodu

ERROR_CODES = {
    E_DECLINED, E_TIMEOUT, E_BUSY, E_NOT_TRUSTED, E_RECEIVING_OFF, E_TOO_LARGE, E_NO_SPACE,
    E_INVALID_OFFER, E_AUTH_FAILED, E_PROTO_VERSION, E_PROTOCOL, E_HASH_MISMATCH, E_CANCELLED,
    E_INTERNAL, E_KEY_MISMATCH, E_SAS_REJECTED,
}


class ProtocolError(Exception):
    """Chyba protokolu s kodem z ERROR_CODES."""

    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


# --- Ramce -------------------------------------------------------------------

def encode_json(obj):
    payload = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_JSON:
        raise ProtocolError(E_PROTOCOL, "JSON message too large")
    return HEADER.pack(FRAME_JSON, len(payload)) + payload


def encode_data(data):
    if len(data) > MAX_DATA:
        raise ProtocolError(E_PROTOCOL, "data frame too large")
    return HEADER.pack(FRAME_DATA, len(data)) + bytes(data)


def recv_exact(sock, n):
    """Precte presne n bajtu nebo vyhodi ConnectionError."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(n - len(buf), 1 << 20))
        if not chunk:
            raise ConnectionError("connection closed")
        buf += chunk
    return bytes(buf)


def decode_header(raw):
    ftype, length = HEADER.unpack(raw)
    if ftype == FRAME_JSON:
        if length > MAX_JSON:
            raise ProtocolError(E_PROTOCOL, "JSON frame too large")
    elif ftype == FRAME_DATA:
        if length > MAX_DATA:
            raise ProtocolError(E_PROTOCOL, "data frame too large")
    else:
        raise ProtocolError(E_PROTOCOL, "unknown frame type 0x%02x" % ftype)
    return ftype, length


def decode_json(payload):
    try:
        obj = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ProtocolError(E_PROTOCOL, "invalid JSON: %s" % e) from None
    if not isinstance(obj, dict) or not isinstance(obj.get("type"), str):
        raise ProtocolError(E_PROTOCOL, "JSON message must be an object with a 'type'")
    return obj


def read_frame(sock):
    """Vrati (typ, obsah); u JSON uz dekodovany slovnik."""
    ftype, length = decode_header(recv_exact(sock, HEADER.size))
    payload = recv_exact(sock, length) if length else b""
    if ftype == FRAME_JSON:
        return ftype, decode_json(payload)
    return ftype, payload


class Channel:
    """Ramcovy kanal nad (TLS) socketem."""

    def __init__(self, sock):
        self.sock = sock

    def send(self, obj):
        self.sock.sendall(encode_json(obj))

    def send_data(self, data):
        self.sock.sendall(encode_data(data))

    def recv(self):
        return read_frame(self.sock)

    def recv_msg(self, *expected):
        """Precte JSON zpravu; zprava "error" se meni na ProtocolError."""
        ftype, msg = self.recv()
        if ftype != FRAME_JSON:
            raise ProtocolError(E_PROTOCOL, "expected a JSON message")
        if msg["type"] == "error" and "error" not in expected:
            code = msg.get("code") if msg.get("code") in ERROR_CODES else E_PROTOCOL
            raise ProtocolError(code, str(msg.get("message", code))[:500])
        if expected and msg["type"] not in expected:
            raise ProtocolError(E_PROTOCOL, "unexpected message '%s'" % msg["type"])
        return msg

    def error(self, code, message=""):
        try:
            self.send({"type": "error", "code": code, "message": message or code})
        except OSError:
            pass


# --- Kryptograficke odvozeni -------------------------------------------------

def commit(nonce):
    """Zavazek odesilatele k jeho nonce: SHA-256(nonce)."""
    return hashlib.sha256(nonce).digest()


def check_commit(commitment, nonce):
    return hmac.compare_digest(commit(nonce), commitment)


def auth_message(fp_server, fp_client, nonce_server, nonce_client):
    """Data, ktera odesilatel (klient) podepisuje svym identitnim klicem."""
    for v in (fp_server, fp_client, nonce_server, nonce_client):
        if len(v) != 32:
            raise ValueError("all inputs must be 32 bytes")
    return AUTH_LABEL + fp_server + fp_client + nonce_server + nonce_client


def sas_code(fp_client, fp_server, nonce_client, nonce_server):
    """Overovaci kod (6 cislic) - stejny na obou obrazovkach.

    SHA-256("LUXDROP-SAS-v1" || fp_klient || fp_server || nonce_klient || nonce_server),
    prvnich 8 bajtu jako uint64 big-endian modulo 1 000 000, doplneno nulami na 6 cislic.
    """
    for v in (fp_client, fp_server, nonce_client, nonce_server):
        if len(v) != 32:
            raise ValueError("all inputs must be 32 bytes")
    h = hashlib.sha256(SAS_LABEL + fp_client + fp_server + nonce_client + nonce_server).digest()
    return "%06d" % (int.from_bytes(h[:8], "big") % 1_000_000)


def format_sas(code):
    return code[:3] + " " + code[3:]


def short_id(fp):
    """Kratke ID zarizeni: prvnich 8 bajtu otisku jako hex (16 znaku)."""
    return fp[:8].hex()


def format_fp(fp):
    """Otisk pro cteni lidmi: 16 skupin po 4 hex znacich."""
    h = fp.hex().upper()
    return " ".join(h[i:i + 4] for i in range(0, len(h), 4))


def hex32(value, what):
    """Dekoduje 32bajtovou hodnotu v hex z JSON zpravy."""
    if not isinstance(value, str) or len(value) != 64:
        raise ProtocolError(E_PROTOCOL, "%s must be 64 hex characters" % what)
    try:
        return bytes.fromhex(value)
    except ValueError:
        raise ProtocolError(E_PROTOCOL, "%s is not hex" % what) from None
