"""LuxDrop - kompatibilita s LocalSend (protokol v2): konstanty, zpravy, otisky, nazvy souboru.

Modul nema zavislosti mimo stdlib (a volitelne cryptography pro otisky), aby sel snadno
otestovat. Sit (HTTPS server, klient, multicast) je v lsnet.py.
Specifikace: https://github.com/localsend/protocol (v2.2) - shrnuti v PROTOCOL.md, cast B.
"""
import datetime
import hashlib
import json
import mimetypes
import os
import re
import unicodedata

from . import pathsafe, proto

PROTOCOL_VERSION = "2.2"
DEFAULT_PORT = 53317
MULTICAST_GROUP = "224.0.0.167"
API = "/api/localsend/v2"
API_V1_INFO = "/api/localsend/v1/info"  # stare klienty (<= 1.17) se ptaji jeste na v1
DEVICE_TYPES = ("mobile", "desktop", "web", "headless", "server")
DEVICE_MODEL = "LuxOS"

MAX_JSON = 8 * 1024 * 1024      # prepare-upload s mnoha soubory
MAX_DATAGRAM = 65536
MAX_ALIAS = 63
MAX_FILES = pathsafe.MAX_FILES
MAX_PREVIEW = 64 * 1024         # textova zprava v poli "preview"


class Invalid(Exception):
    """Neplatna zprava LocalSend (HTTP 400)."""


# --- Otisky ------------------------------------------------------------------

def cert_fingerprint(cert_der):
    """Otisk LocalSend: SHA-256 certifikatu v DER, velka hex pismena (64 znaku)."""
    return hashlib.sha256(cert_der).hexdigest().upper()


def norm_fp(fp):
    """Normalizovany otisk z JSON (velka pismena) nebo "" kdyz nejde o hex SHA-256."""
    if not isinstance(fp, str):
        return ""
    fp = fp.strip().upper()
    return fp if re.fullmatch(r"[0-9A-F]{64}", fp) else ""


def spki_fingerprint_der(cert_der):
    """SHA-256 z SubjectPublicKeyInfo certifikatu (libovolny typ klice, napr. RSA u LocalSend).

    Duveryhodna zarizeni se pripinaji podle klice - stejne jako u protokolu LuxDrop.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    cert = x509.load_der_x509_certificate(cert_der)
    der = cert.public_key().public_bytes(serialization.Encoding.DER,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).digest()


# --- Informace o zarizeni -------------------------------------------------------

def clean_alias(name):
    if not isinstance(name, str):
        return "?"
    name = "".join(c for c in name if c.isprintable() and c not in pathsafe.BIDI).strip()
    return name[:MAX_ALIAS] or "?"


def device_type(value):
    """Neznamy typ = desktop (jako oficialni implementace)."""
    v = value.lower() if isinstance(value, str) else ""
    return v if v in DEVICE_TYPES else "desktop"


def my_info(alias, fingerprint, port, luxdrop=None, announce=None):
    """Nase informace pro /info, /register, multicast a prepare-upload.

    luxdrop: {"id", "port"} - rozsireni LuxOS; ostatni klienty nezname pole ignoruji.
    """
    info = {
        "alias": alias[:MAX_ALIAS],
        "version": PROTOCOL_VERSION,
        "deviceModel": DEVICE_MODEL,
        "deviceType": "desktop",
        "fingerprint": fingerprint,
        "port": port,
        "protocol": "https",
        "download": False,
    }
    if luxdrop:
        info["luxdrop"] = {"v": proto.PROTO_VERSION, "id": luxdrop["id"], "port": luxdrop["port"]}
    if announce is not None:
        info["announce"] = bool(announce)
        info["announcement"] = bool(announce)  # protokol v1
    return info


def parse_info(obj, need_port=True):
    """Overi informace o zarizeni z JSON; vrati slovnik s normalizovanymi hodnotami."""
    if not isinstance(obj, dict):
        raise Invalid("device info must be an object")
    alias = obj.get("alias")
    if not isinstance(alias, str) or not alias.strip():
        raise Invalid("missing alias")
    port = obj.get("port", DEFAULT_PORT)
    if need_port and (not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536):
        raise Invalid("invalid port")
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        port = DEFAULT_PORT
    protocol = obj.get("protocol", "https")
    if protocol not in ("http", "https"):
        raise Invalid("invalid protocol")
    model = obj.get("deviceModel")
    lux = obj.get("luxdrop")
    luxdrop = None
    if isinstance(lux, dict) and isinstance(lux.get("id"), str) and re.fullmatch(r"[0-9a-f]{16}", lux["id"]) \
            and isinstance(lux.get("port"), int) and 0 < lux["port"] < 65536 and lux.get("v") == proto.PROTO_VERSION:
        luxdrop = {"id": lux["id"], "port": lux["port"]}
    version = obj.get("version", "1.0")
    return {
        "alias": clean_alias(alias),
        "version": version if isinstance(version, str) else "1.0",
        "deviceModel": clean_alias(model)[:40] if isinstance(model, str) and model.strip() else "",
        "deviceType": device_type(obj.get("deviceType")),
        "fingerprint": norm_fp(obj.get("fingerprint")),
        "raw_fingerprint": obj.get("fingerprint") if isinstance(obj.get("fingerprint"), str) else "",
        "port": port,
        "protocol": protocol,
        "announce": bool(obj.get("announce", obj.get("announcement", False))),
        "luxdrop": luxdrop,
    }


def parse_datagram(data):
    """Multicast zprava -> slovnik nebo None (cizi/poskozena data se tise zahodi)."""
    if len(data) > MAX_DATAGRAM:
        return None
    try:
        obj = json.loads(data.decode("utf-8"))
        info = parse_info(obj)
    except (UnicodeDecodeError, ValueError, Invalid):
        return None
    if not info["raw_fingerprint"]:
        return None
    return info


def encode_datagram(info):
    return json.dumps(info, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# --- Nazvy souboru ---------------------------------------------------------------

def sanitize_name(name):
    """Nazev souboru z prepare-upload -> bezpecna relativni cesta (str) nebo Invalid.

    LocalSend posila cele cesty u slozek ("Fotky/2024/a.jpg"). Nektere systemy posilaji NFD,
    proto se normalizuje na NFC. Ridici a bidi znaky se nahradi "_". Komponenty
    ".." a absolutni cesty se odmitnou (path traversal), prazdne a "." se vynechaji.
    """
    if not isinstance(name, str) or not name:
        raise Invalid("empty file name")
    name = unicodedata.normalize("NFC", name).replace("\\", "/")
    if name.startswith("/") or name.startswith("~") or re.match(r"^[A-Za-z]:", name):
        raise Invalid("absolute file name: %r" % name)
    parts = []
    for p in name.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            raise Invalid("path traversal in file name: %r" % name)
        p = "".join("_" if (ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0 or c in pathsafe.BIDI) else c for c in p)
        b = p.encode("utf-8", "surrogatepass")
        if len(b) > pathsafe.MAX_COMPONENT:
            stem, ext = os.path.splitext(p)
            ext = ext[:16]
            while len((stem + ext).encode("utf-8", "surrogatepass")) > pathsafe.MAX_COMPONENT:
                stem = stem[:-1]
            p = stem + ext
        parts.append(p)
    if not parts:
        raise Invalid("empty file name")
    rel = "/".join(parts)
    try:
        pathsafe.check_relpath(rel)
    except proto.ProtocolError as e:
        raise Invalid(e.message) from None
    return rel


def is_text_type(file_type):
    return isinstance(file_type, str) and (file_type == "text" or file_type.startswith("text/plain"))


def parse_prepare_upload(obj):
    """Overi telo prepare-upload; vrati (info, soubory, celkova velikost, zprava|None).

    soubory: seznam {id, rel, size, sha256 (bytes|None), type, modified} v poradi podle cest.
    zprava: text, kdyz jde o samotnou textovou zpravu (1 soubor text/plain s "preview").
    """
    if not isinstance(obj, dict):
        raise Invalid("body must be an object")
    info = parse_info(obj.get("info"), need_port=False)
    files = obj.get("files")
    if not isinstance(files, dict) or not files:
        raise Invalid("no files")
    if len(files) > MAX_FILES:
        raise Invalid("too many files")
    out, seen, total = [], {}, 0
    for key, f in files.items():
        if not isinstance(f, dict):
            raise Invalid("file entry must be an object")
        fid = f.get("id", key)
        if not isinstance(fid, str) or not fid or len(fid) > 200 or fid != key:
            raise Invalid("invalid file id")
        size = f.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > pathsafe.MAX_TOTAL:
            raise Invalid("invalid size")
        total += size
        if total > pathsafe.MAX_TOTAL:
            raise Invalid("total size too large")
        rel = sanitize_name(f.get("fileName"))
        sha = f.get("sha256") or f.get("hash")
        digest = None
        if isinstance(sha, str) and sha:
            if not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
                raise Invalid("invalid sha256")
            digest = bytes.fromhex(sha)
        modified = None
        meta = f.get("metadata")
        if isinstance(meta, dict) and isinstance(meta.get("modified"), str):
            modified = parse_time(meta["modified"])
        ftype = f.get("fileType") if isinstance(f.get("fileType"), str) else ""
        # Kolize nazvu (napr. NFC/NFD nebo nahrazene znaky): pridat " (2)"
        base, n = rel, 2
        while rel.casefold() in seen:
            stem, ext = os.path.splitext(base)
            rel = "%s (%d)%s" % (stem, n, ext)
            n += 1
        seen[rel.casefold()] = True
        out.append({"id": fid, "rel": rel, "parts": tuple(rel.split("/")), "size": size, "sha256": digest,
                    "type": ftype[:100], "modified": modified, "preview": f.get("preview")})
    # Soubor nesmi byt zaroven slozkou jineho souboru ("a" a "a/b")
    file_set = {f["parts"] for f in out}
    for f in out:
        for k in range(1, len(f["parts"])):
            if f["parts"][:k] in file_set:
                raise Invalid("file name collides with a folder: %s" % f["rel"])
    message = None
    if len(out) == 1 and is_text_type(out[0]["type"]) and isinstance(out[0]["preview"], str):
        message = out[0]["preview"][:MAX_PREVIEW]
    out.sort(key=lambda f: f["rel"])
    return info, out, total, message


def parse_time(text):
    """ISO 8601 -> unix cas nebo None."""
    try:
        t = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    ts = t.timestamp()
    return ts if 0 < ts < 4102444800 else None


def iso_time(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_type(path):
    t, _enc = mimetypes.guess_type(path)
    return t or "application/octet-stream"


def file_dto(fid, rel, size, sha_hex=None, ftype=None, modified=None, preview=None):
    dto = {"id": fid, "fileName": rel, "size": size, "fileType": ftype or file_type(rel)}
    if sha_hex:
        dto["sha256"] = sha_hex
    if preview is not None:
        dto["preview"] = preview
    if modified:
        dto["metadata"] = {"modified": iso_time(modified)}
    return dto


def parse_prepare_response(obj):
    """Odpoved prepare-upload -> (sessionId, {fileId: token})."""
    if not isinstance(obj, dict) or not isinstance(obj.get("sessionId"), str) or not obj["sessionId"]:
        raise Invalid("invalid prepare-upload response")
    files = obj.get("files")
    if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
        raise Invalid("invalid prepare-upload response")
    return obj["sessionId"], files
