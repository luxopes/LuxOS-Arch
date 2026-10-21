"""LuxDrop - odesilani na zarizeni LocalSend (prepare-upload -> upload kazdeho souboru).

Pred odeslanim jakychkoli dat se zkontroluje otisk certifikatu prijemce (z objevovani);
u duveryhodneho zarizeni navic pripnuty klic. Soubory se posilaji postupne s
Content-Length a SHA-256 v nabidce (prijemce ho muze overit).
"""
import os
import threading
import time
import uuid

from . import localsend, lshttp, pathsafe, proto, transfer

PREPARE_TIMEOUT = transfer.DECISION_TIMEOUT + 60  # prijemce rozhoduje (az 2 minuty)


class OutgoingSessions:
    """Bezici odesilani - aby prijemce mohl prenos zrusit pres nas /cancel."""

    def __init__(self):
        self.lock = threading.Lock()
        self.items = {}  # (ip, sessionId prijemce) -> Transfer

    def add(self, ip, sid, t):
        with self.lock:
            self.items[(ip, sid)] = t

    def remove(self, ip, sid):
        with self.lock:
            self.items.pop((ip, sid), None)

    def cancel(self, ip, sid):
        with self.lock:
            t = self.items.get((ip, sid))
        if t is None:
            return False
        t.remote_cancelled = True
        t.cancel()
        return True


def send(identity, settings, trust, history, device, callbacks, paths=None, text=None, transfer_obj=None,
         sessions=None):
    """Odesle soubory nebo text; vrati Transfer. Nevyhazuje vyjimky protokolu.

    device: zaznam z LocalSendDiscovery (host, port, fingerprint, spki, name, device_type).
    callbacks: transfer.SendCallbacks + ask_pin(device_name, wrong) -> str|None.
    """
    t = transfer_obj or transfer.Transfer("out")
    t.peer_name = t.peer_name or device["name"]
    t.peer_id = t.peer_id or device["fingerprint"][:16].lower()
    t.protocol = "localsend"
    t.device_type = device.get("device_type", "desktop")
    t.remote_cancelled = False
    try:
        _send(identity, settings, trust, device, callbacks, paths, text, t, sessions)
    except proto.ProtocolError as e:
        t.code, t.error = e.code, e.message
        t.state = {"declined": "declined", "cancelled": "cancelled"}.get(e.code, "failed")
    except lshttp.PinError as e:
        t.state, t.code = "failed", proto.E_KEY_MISMATCH
        t.error = "the device presented a different certificate than expected (%s)" % e
    except (OSError, ConnectionError, lshttp.HTTPError) as e:
        if t.cancelled:
            t.state, t.code, t.error = "cancelled", proto.E_CANCELLED, \
                "cancelled by the receiver" if t.remote_cancelled else "cancelled"
        else:
            detail = e.strerror if isinstance(e, OSError) and e.strerror else str(e)
            t.state, t.code = "failed", proto.E_PROTOCOL
            t.error = ("connection lost: %s" if t.state in ("transferring", "waiting") else
                       "connection failed: %s") % detail
    if t.items:
        try:
            history.add({"direction": "out", "peer": t.peer_name, "peer_id": t.peer_id, "protocol": "localsend",
                         "items": t.items[:20], "total": t.total, "state": t.state, "error": t.error,
                         "device_type": t.device_type})
        except OSError:
            pass
    callbacks.update(t)
    return t


def _check_key(trust, device):
    """Kontrola klice duveryhodneho zarizeni (SPKI) - doplnek k otisku certifikatu."""
    entry_fp = None
    if device.get("spki") and trust.is_trusted(device["spki"]):
        entry_fp = device["spki"]

    def check(cert_der):
        if entry_fp is not None and localsend.spki_fingerprint_der(cert_der) != entry_fp:
            raise proto.ProtocolError(proto.E_KEY_MISMATCH, "the trusted device presented a different key")
    return check


def _client(identity, device, trust, timeout):
    fp = device["fingerprint"] if localsend.norm_fp(device["fingerprint"]) else None
    return lshttp.Client(identity, device["host"], device["port"], expected_fp=fp, timeout=timeout,
                         check=_check_key(trust, device))


def _cancel_remote(identity, device, trust, sid=None):
    def run():
        try:
            c = _client(identity, device, trust, 5)
            try:
                c.request_json("POST", localsend.API + "/cancel", query={"sessionId": sid} if sid else None)
            finally:
                c.close()
        except Exception:  # noqa: BLE001 - prijemce uz nemusi byt dostupny
            pass
    threading.Thread(target=run, daemon=True).start()


def _send(identity, settings, trust, device, cb, paths, text, t, sessions):
    if device.get("protocol") != "https":
        raise proto.ProtocolError(proto.E_PROTOCOL, "the device has encryption turned off in LocalSend")
    t.state = "preparing"
    files = []  # (dto, lokalni cesta nebo bytes)
    if text is not None:
        data = text.encode("utf-8")
        fid = str(uuid.uuid4())
        files.append((localsend.file_dto(fid, fid + ".txt", len(data), ftype="text/plain", preview=text), data))
        t.items = [_("Text")]
    else:
        items, dirs = pathsafe.collect(paths, on_skip=lambda p, why: t.skipped.append((p, why)))
        if not items:
            raise proto.ProtocolError(proto.E_INVALID_OFFER, "nothing to send (LocalSend cannot send empty folders)")
        tops = []
        for _p, rel, _s, _x in items:
            if rel.split("/")[0] not in tops:
                tops.append(rel.split("/")[0])
        t.items = tops
        t.total = sum(s for _p, _r, s, _x in items)
        cb.update(t)
        hashed = [0]

        def prog(n):
            hashed[0] += n
            t.done = hashed[0]
            cb.update(t)

        for local, rel, size, _x in items:
            digest, n = transfer.sha256_file(local, nofollow="/" in rel, progress=prog, cancel=t._cancel)
            if n != size:
                raise proto.ProtocolError(proto.E_INTERNAL, "file changed while reading: %s" % local)
            try:
                mtime = os.stat(local).st_mtime
            except OSError:
                mtime = None
            files.append((localsend.file_dto(str(uuid.uuid4()), rel, size, digest.hex(), modified=mtime), local))
        t.done = 0
    t.total = sum(dto["size"] for dto, _src in files)
    t.files = [{"name": dto["fileName"], "size": dto["size"], "done": 0, "state": "waiting"} for dto, _s in files]

    # prepare-upload (prijemce rozhoduje - muze trvat)
    t.state = "connecting"
    cb.update(t)
    info = localsend.my_info(settings.name, localsend.cert_fingerprint(identity.cert_der),
                             settings["localsend_port"])
    body = {"info": info, "files": {dto["id"]: dto for dto, _s in files}}
    pin, wrong = None, False
    while True:
        status, obj = _prepare(identity, device, trust, body, pin, t, cb)
        if status == 401:
            if t.cancelled:
                raise proto.ProtocolError(proto.E_CANCELLED, "cancelled")
            pin = cb.ask_pin(t.peer_name, wrong) if hasattr(cb, "ask_pin") else None
            if not pin:
                raise proto.ProtocolError(proto.E_DECLINED, "the receiver requires a PIN")
            wrong = True
            continue
        break
    if status == 204:
        t.state, t.done = "done", t.total
        return
    if status == 403:
        raise proto.ProtocolError(proto.E_DECLINED, "the receiver declined")
    if status == 409:
        raise proto.ProtocolError(proto.E_BUSY, "the receiver is busy with another transfer")
    if status == 429:
        raise proto.ProtocolError(proto.E_BUSY, "too many attempts (wrong PIN?) - try again later")
    if status == 507:
        raise proto.ProtocolError(proto.E_NO_SPACE, "not enough disk space on the receiver")
    if status != 200:
        raise proto.ProtocolError(proto.E_PROTOCOL, "the receiver answered %d" % status)
    try:
        sid, tokens = localsend.parse_prepare_response(obj)
    except localsend.Invalid as e:
        raise proto.ProtocolError(proto.E_PROTOCOL, str(e)) from None

    # upload jednotlivych souboru
    if sessions is not None:
        sessions.add(device["host"], sid, t)
    t.on_cancel = lambda: _cancel_remote(identity, device, trust, sid) if not t.remote_cancelled else None
    t.state = "transferring"
    cb.update(t)
    last_ui = [0.0]
    rate = float(os.environ.get("LUXDROP_TEST_RATE", "0") or 0)  # jen pro testy (bajty/s)
    start = time.monotonic()
    try:
        for i, (dto, src) in enumerate(files):
            token = tokens.get(dto["id"])
            ui = t.files[i]
            if token is None:
                ui["state"] = "skipped"  # prijemce tento soubor nechce
                t.done += dto["size"]
                continue
            if t.cancelled:
                raise proto.ProtocolError(proto.E_CANCELLED, "cancelled")
            ui["state"] = "sending"

            def chunks(dto=dto, src=src, ui=ui):
                if isinstance(src, bytes):
                    yield src
                    ui["done"] += len(src)
                    t.done += len(src)
                    return
                flags = os.O_RDONLY | (os.O_NOFOLLOW if "/" in dto["fileName"] else 0)
                with os.fdopen(os.open(src, flags), "rb") as fh:
                    left = dto["size"]
                    while left > 0:
                        if t.cancelled:
                            raise ConnectionError("cancelled")
                        b = fh.read(min(proto.CHUNK, left))
                        if not b:
                            raise proto.ProtocolError(proto.E_INTERNAL, "file changed while sending: %s" % src)
                        left -= len(b)
                        yield b
                        ui["done"] += len(b)
                        t.done += len(b)
                        now = time.monotonic()
                        if now - last_ui[0] > 0.1:
                            last_ui[0] = now
                            cb.update(t)
                        if rate:
                            ahead = t.done / rate - (now - start)
                            if ahead > 0:
                                time.sleep(ahead)

            c = _client(identity, device, trust, transfer.IO_TIMEOUT)
            t.sock = c
            try:
                status, _obj = c.upload(localsend.API + "/upload",
                                        {"sessionId": sid, "fileId": dto["id"], "token": token},
                                        dto["size"], chunks())
            finally:
                c.close()
                t.sock = None
            if status == 422:
                raise proto.ProtocolError(proto.E_HASH_MISMATCH, "the receiver reports a checksum mismatch")
            if status != 200:
                raise proto.ProtocolError(proto.E_PROTOCOL, "upload of %s failed (%d)" % (dto["fileName"], status))
            ui["state"] = "done"
            cb.update(t)
    except proto.ProtocolError as e:
        if e.code != proto.E_CANCELLED or not t.remote_cancelled:
            if not t.cancelled:
                _cancel_remote(identity, device, trust, sid)
        raise
    finally:
        if sessions is not None:
            sessions.remove(device["host"], sid)
    t.saved = [dto["fileName"] for dto, _s in files][:100]
    t.state = "done"


def _prepare(identity, device, trust, body, pin, t, cb):
    """POST prepare-upload; ceka na rozhodnuti prijemce, zruseni z UI ho prerusi."""
    box = {}
    c = _client(identity, device, trust, PREPARE_TIMEOUT)

    def run():
        try:
            c.connect()
            t.state = "waiting"
            cb.update(t)
            box["v"] = c.request_json("POST", localsend.API + "/prepare-upload", body,
                                      query={"pin": pin} if pin else None, limit=1 << 20)
        except Exception as e:  # noqa: BLE001 - predano volajicimu
            box["e"] = e

    th = threading.Thread(target=run, daemon=True)
    th.start()
    try:
        while th.is_alive():
            th.join(0.2)
            if t.cancelled and th.is_alive():
                c.abort()
                _cancel_remote(identity, device, trust)  # bez sessionId: zruseni cekajiciho pozadavku
                th.join(5)
                raise proto.ProtocolError(proto.E_CANCELLED, "cancelled")
    finally:
        c.close()
    if "e" in box:
        raise box["e"]
    return box["v"]


try:
    from .cli import _  # noqa: E402
except ImportError:  # pragma: no cover
    def _(s):
        return s
