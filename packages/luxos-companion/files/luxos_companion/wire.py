"""Ramce protokolu LuxOS Companion v1: jeden JSON objekt v UTF-8 + LF, nejvys 65 536 bajtu vcetne LF.

Cte se postupne ze streamu (jedno read != jedna zprava). CRLF je povolene. Neplatne UTF-8, neplatny
JSON, objekt bez v/type/id, jina verze nez 1, prilis dlouhy ramec a neuplny ramec pri EOF jsou
chyba protokolu -> spojeni se ukonci (ProtocolError).
"""
import json
import math
import uuid

MAX_FRAME = 65536            # bajtu vcetne LF
PROTOCOL = 1


class ProtocolError(Exception):
    """Porušení protokolu - spojeni se musi zavrit."""

    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code = code


def _reject_constant(name):
    # NaN / Infinity nejsou JSON
    raise ValueError(f"invalid JSON constant {name}")


def decode_frame(raw):
    """Bajty jednoho ramce (bez LF, pripadne s CR na konci) -> dict. Vyhazuje ProtocolError."""
    if raw.endswith(b"\r"):
        raw = raw[:-1]
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as e:
        raise ProtocolError("invalid_utf8", "invalid UTF-8") from e
    try:
        msg = json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as e:
        raise ProtocolError("invalid_json", "invalid JSON") from e
    if not isinstance(msg, dict):
        raise ProtocolError("invalid_json", "frame is not a JSON object")
    v = msg.get("v")
    if type(v) is not int:     # bool neni verze
        raise ProtocolError("invalid_message", "missing protocol version")
    if v != PROTOCOL:
        raise ProtocolError("unsupported_version", f"unsupported protocol version {v}")
    if not isinstance(msg.get("type"), str) or not msg["type"]:
        raise ProtocolError("invalid_message", "missing type")
    if not isinstance(msg.get("id"), str) or not msg["id"] or len(msg["id"]) > 128:
        raise ProtocolError("invalid_message", "missing id")
    return msg


class Decoder:
    """Postupne skladani ramcu z libovolne rozdelenych bajtu."""

    def __init__(self, limit=MAX_FRAME):
        self.limit = limit
        self.buf = bytearray()

    def feed(self, data):
        """Prida bajty a postupne vraci hotove zpravy (generator: zpravy pred chybnym ramcem se jeste
        zpracuji). Pri chybe vyhodi ProtocolError (buffer se zahodi)."""
        start = 0
        while True:
            nl = data.find(b"\n", start)
            if nl < 0:
                rest = data[start:]
                # bez LF smi ramec mit nejvys limit-1 bajtu (LF se do limitu pocita)
                if len(self.buf) + len(rest) > self.limit - 1:
                    self.buf.clear()
                    raise ProtocolError("frame_too_long", "frame too long")
                self.buf += rest
                return
            part = data[start:nl]
            if len(self.buf) + len(part) + 1 > self.limit:
                self.buf.clear()
                raise ProtocolError("frame_too_long", "frame too long")
            frame = bytes(self.buf) + bytes(part)
            self.buf.clear()
            start = nl + 1
            yield decode_frame(frame)

    def eof(self):
        """Konec streamu: neuplny ramec je chyba."""
        if self.buf:
            self.buf.clear()
            raise ProtocolError("incomplete_frame", "incomplete frame at end of stream")


def new_id():
    return str(uuid.uuid4())


def message(mtype, reply_to=None, **fields):
    msg = {"v": PROTOCOL, "type": mtype, "id": new_id()}
    if reply_to is not None:
        msg["reply_to"] = reply_to
    msg.update(fields)
    return msg


def encode(msg, limit=MAX_FRAME):
    """dict -> bajty ramce (kompaktni JSON + LF). Prilis dlouhou zpravu nelze poslat (ValueError)."""
    data = json.dumps(msg, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    if len(data) > limit:
        raise ValueError("message too long")
    return data


def is_finite_number(v):
    return type(v) in (int, float) and math.isfinite(v)
