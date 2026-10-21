"""LuxDrop - prijem pres LocalSend (HTTPS server, protokol v2).

Endpointy: GET  /api/localsend/v2/info (+ /v1/info), POST /register, /prepare-upload,
/upload, /cancel. Kazdy prenos od neduveryhodneho zarizeni musi potvrdit uzivatel
(Handler.ask). Duveryhodne je jen zarizeni, jehoz klientsky certifikat (mTLS) ma
pripnuty klic. Soubory se zapisuji do <cil>/.luxdrop-partial a do cile se presunou
az po kontrole velikosti (a SHA-256, pokud ho odesilatel poslal).
"""
import hashlib
import hmac
import os
import secrets
import select
import socket
import threading
import time
import uuid

from . import localsend, lshttp, proto, transfer

MAX_CONNECTIONS = 16
DECISION_TIMEOUT = transfer.DECISION_TIMEOUT
SESSION_IDLE = 120          # relace bez aktivity se po 2 minutach ukonci
PIN_MAX_ATTEMPTS = 3
PIN_BLOCK_SECONDS = 300
IO_TIMEOUT = 60


def log(msg):
    transfer.log("localsend: " + msg)


class LocalSendSession:
    def __init__(self, sid, ip, info, files, t, dest, fp_spki, cert_fp):
        self.id = sid
        self.ip = ip
        self.info = info
        self.files = {f["id"]: dict(f, token=secrets.token_urlsafe(24), state="pending", attempts=0, ui=i)
                      for i, f in enumerate(files)}
        self.t = t
        self.dest = dest
        self.fp_spki = fp_spki
        self.cert_fp = cert_fp
        self.last = time.monotonic()
        self.lock = threading.Lock()
        self.uploads = set()  # aktivni spojeni (pro zruseni)
        self.top_dirs = {}    # nazev slozky v nabidce -> skutecny nazev v cili
        self.saved = []
        self.ended = False


class LocalSendServer:
    def __init__(self, identity, settings, trust, history, handler, port=None, bind="", info_extra=None,
                 on_register=None, on_cancel_received=None):
        self.identity = identity
        self.settings = settings
        self.trust = trust
        self.history = history
        self.handler = handler
        self.port = settings["localsend_port"] if port is None else port
        self.bind = bind
        self.info_extra = info_extra or (lambda: None)  # {"id","port"} LuxDrop protokolu
        self.on_register = on_register or (lambda *a: None)
        self.on_cancel_received = on_cancel_received or (lambda ip, sid: False)
        self.fingerprint = localsend.cert_fingerprint(identity.cert_der)
        self.ctx = None
        self.sock = None
        self.session = None       # aktivni relace (jen jedna, jako LocalSend)
        self.pending = None       # (ip, Event) - ceka se na rozhodnuti uzivatele
        self.slot = threading.Lock()
        self.pin_fail = {}        # ip -> (pocet, cas)
        self._stop = threading.Event()
        self._conn_sem = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._prompt_sem = threading.BoundedSemaphore(transfer.MAX_PROMPTS)

    # --- Zivotni cyklus -------------------------------------------------------

    def start(self):
        self.ctx = lshttp.server_context(self.identity)
        if self.bind:
            fam = socket.AF_INET6 if ":" in self.bind else socket.AF_INET
            self.sock = socket.create_server((self.bind, self.port), family=fam)
        elif socket.has_dualstack_ipv6():
            self.sock = socket.create_server(("", self.port), family=socket.AF_INET6, dualstack_ipv6=True)
        else:
            self.sock = socket.create_server(("", self.port))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True, name="localsend-accept").start()
        threading.Thread(target=self._reaper, daemon=True, name="localsend-reaper").start()
        return self.port

    def stop(self):
        self._stop.set()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        s = self.session
        if s:
            self._end(s, "cancelled", "receiver stopped")

    def my_info(self):
        self.settings.reload()
        return localsend.my_info(self.settings.name, self.fingerprint, self.port, luxdrop=self.info_extra())

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

    def _reaper(self):
        # Opustene relace (odesilatel zmizel) uvolni misto pro dalsi
        while not self._stop.wait(5):
            s = self.session
            if s and not s.uploads and time.monotonic() - s.last > SESSION_IDLE:
                self._end(s, "failed", "the sender stopped sending")

    def _serve(self, raw, addr):
        ip = addr[0]
        if ip.startswith("::ffff:"):
            ip = ip[7:]
        c = None
        try:
            c = lshttp.TLSServerConn(self.ctx, raw, timeout=transfer.HANDSHAKE_TIMEOUT)
            c.handshake()
            c.timeout(IO_TIMEOUT)
            reader = lshttp.Reader(c)
            while not self._stop.is_set():
                try:
                    req = lshttp.read_request(reader, ip, c.cert_der)
                except lshttp.HTTPError as e:
                    c.sendall(lshttp.response_bytes(e.status, {"message": e.message}, close=True))
                    return
                if req is None:
                    return
                if req.headers.get("expect", "").lower() == "100-continue":
                    c.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
                try:
                    status, obj = self.route(req, c)
                except lshttp.HTTPError as e:
                    status, obj = e.status, {"message": e.message}
                except Exception as e:  # noqa: BLE001 - chyba nesmi shodit server
                    log("internal error: %r" % e)
                    if os.environ.get("LUXDROP_DEBUG"):
                        import traceback
                        traceback.print_exc()
                    status, obj = 500, {"message": "Internal server error"}
                keep = req.keep_alive and req.body.drain()
                c.sendall(lshttp.response_bytes(status, obj, close=not keep))
                if not keep:
                    return
        except (ConnectionError, TimeoutError, OSError):
            pass
        finally:
            if c is not None:
                c.close()
            else:
                raw.close()
            self._conn_sem.release()

    # --- Smerovani ------------------------------------------------------------

    def route(self, req, conn):
        p = req.path
        api = localsend.API
        if req.method == "GET" and p in (api + "/info", localsend.API_V1_INFO):
            return self._visible() or (200, self._info_response())
        if req.method != "POST":
            raise lshttp.HTTPError(404 if not p.startswith("/api/localsend/") else 405)
        if p == api + "/register":
            return self.register(req)
        if p == api + "/prepare-upload":
            return self.prepare_upload(req, conn)
        if p == api + "/upload":
            return self.upload(req, conn)
        if p == api + "/cancel":
            return self.cancel(req)
        raise lshttp.HTTPError(404)

    def _visible(self):
        """Vypnuty prijem: zarizeni se nehlasi (403)."""
        self.settings.reload()
        if not self.settings["localsend"] or self.settings.mode() == "off":
            return 403, {"message": "Receiving is turned off"}
        return None

    def _info_response(self):
        info = self.my_info()
        for k in ("port", "protocol"):
            info.pop(k, None)
        return info

    def register(self, req):
        hidden = self._visible()
        obj = req.json(64 * 1024)
        try:
            info = localsend.parse_info(obj)
        except localsend.Invalid as e:
            raise lshttp.HTTPError(400, str(e)) from None
        cert_fp = localsend.cert_fingerprint(req.cert_der) if req.cert_der else None
        if cert_fp and info["fingerprint"] != cert_fp:
            # Udajny otisk neodpovida certifikatu - registraci ignorovat (jako LocalSend)
            log("ignoring register from %s: fingerprint does not match its certificate" % req.ip)
        elif info["raw_fingerprint"] != self.fingerprint:
            # I pri vypnutem prijmu si zarizeni zapamatujeme (odpovime ale 403 = nejsme videt)
            self.on_register(req.ip, info, cert_fp, req.cert_der)
        return hidden or (200, self._info_response())

    # --- Prijem ---------------------------------------------------------------

    def _check_pin(self, req, trusted):
        pin = self.settings.pin
        if not pin or trusted:
            return
        now = time.monotonic()
        n, since = self.pin_fail.get(req.ip, (0, now))
        if now - since > PIN_BLOCK_SECONDS:
            n = 0
        if n >= PIN_MAX_ATTEMPTS:
            raise lshttp.HTTPError(429, "Too many requests")
        given = req.query.get("pin")
        if given is None:
            raise lshttp.HTTPError(401, "PIN required")
        if not hmac.compare_digest(given.encode("utf-8"), pin.encode("utf-8")):
            if len(self.pin_fail) > 1000:
                self.pin_fail.clear()
            self.pin_fail[req.ip] = (n + 1, now if n == 0 else since)
            raise lshttp.HTTPError(401, "Invalid PIN")
        self.pin_fail.pop(req.ip, None)

    def prepare_upload(self, req, conn):
        hidden = self._visible()
        if hidden:
            return hidden
        # Identita odesilatele: jen klientsky certifikat (mTLS) je overeny
        fp_spki, cert_fp = None, None
        if req.cert_der:
            try:
                fp_spki = localsend.spki_fingerprint_der(req.cert_der)
                cert_fp = localsend.cert_fingerprint(req.cert_der)
            except Exception:  # noqa: BLE001 - neplatny certifikat = neovereny odesilatel
                fp_spki = None
        trusted = bool(fp_spki) and self.trust.is_trusted(fp_spki)
        mode = self.settings.mode()
        self._check_pin(req, trusted)
        obj = req.json()
        try:
            info, files, total, message = localsend.parse_prepare_upload(obj)
        except localsend.Invalid as e:
            raise lshttp.HTTPError(400, str(e)) from None
        if cert_fp and info["fingerprint"] and info["fingerprint"] != cert_fp:
            log("prepare-upload from %s: claimed fingerprint differs from its certificate" % req.ip)
        if not trusted and mode != "everyone":
            raise lshttp.HTTPError(403, "Only trusted devices can send to this computer")

        t = transfer.Transfer("in", info["alias"], (cert_fp or "")[:16].lower())
        t.protocol = "localsend"
        t.device_type = info["deviceType"]
        if trusted:
            e = self.trust.get(fp_spki) or {}
            t.peer_name = e.get("name") or t.peer_name
        tops = []
        for f in files:
            if f["parts"][0] not in tops:
                tops.append(f["parts"][0])
        t.items, t.total = tops, total
        t.files = [{"name": f["rel"], "size": f["size"], "done": 0, "state": "waiting"} for f in files]
        clash = (not trusted) and t.peer_name.lower() in self.trust.names()

        if message is not None:
            # Textova zprava: zobrazit (neblokujici), nic se neuklada -> 204
            if not self._prompt_sem.acquire(blocking=False):
                raise lshttp.HTTPError(429, "Too many requests")
            r = transfer.IncomingRequest(t, fp_spki, trusted, None, clash, files, [], protocol="localsend",
                                         can_trust=False, verified=bool(cert_fp), message=message,
                                         device_model=info["deviceModel"])

            def show():
                try:
                    self.handler.ask(r)
                except Exception:  # noqa: BLE001
                    pass
                finally:
                    self._prompt_sem.release()
            threading.Thread(target=show, daemon=True).start()
            self._log(t, "message")
            return 204, None

        with self.slot:
            if self.session is not None or self.pending is not None:
                raise lshttp.HTTPError(409, "Blocked by another session")
            withdrawn = threading.Event()
            self.pending = (req.ip, withdrawn)
        try:
            dest = self.settings.download_dir
            os.makedirs(dest, exist_ok=True)
            st = os.statvfs(dest)
            if total + transfer.DISK_RESERVE > st.f_bavail * st.f_frsize:
                t.state, t.code, t.error = "failed", proto.E_NO_SPACE, "not enough disk space"
                self._log(t, "failed")
                self.handler.finished(t)
                raise lshttp.HTTPError(507, "Not enough disk space on the receiver")
            accept, remember = self._decide(t, req, conn, fp_spki, trusted, clash, files, info, bool(cert_fp),
                                            withdrawn)
            if not accept:
                t.state = "declined" if t.code != proto.E_CANCELLED else "cancelled"
                self.handler.finished(t)
                if t.code == proto.E_CANCELLED:
                    raise lshttp.HTTPError(403, "Cancelled by sender")
                raise lshttp.HTTPError(403, "Rejected")
            if remember and fp_spki and not trusted:
                self.trust.add(fp_spki, info["alias"], addr=transfer.fmt_addr(req.ip, info["port"]),
                               kind="localsend", cert_fp=cert_fp, device_type=info["deviceType"])
            sid = str(uuid.uuid4())
            s = LocalSendSession(sid, req.ip, info, files, t, dest, fp_spki, cert_fp)
            t.on_cancel = lambda: self._receiver_cancel(s)
            t.state = "transferring"
            with self.slot:
                self.session = s
        finally:
            with self.slot:
                self.pending = None
        self.handler.update(t)
        log("session %s from %s (%s): %d file(s), %d bytes" % (sid, req.ip, info["alias"], len(files), total))
        return 200, {"sessionId": sid, "files": {fid: f["token"] for fid, f in s.files.items()}}

    def _decide(self, t, req, conn, fp_spki, trusted, clash, files, info, verified, withdrawn):
        if trusted and self.settings["auto_accept_trusted"]:
            return True, False
        if not self._prompt_sem.acquire(blocking=False):
            raise lshttp.HTTPError(429, "Too many requests")
        try:
            r = transfer.IncomingRequest(t, fp_spki, trusted, None, clash, files, [], protocol="localsend",
                                         can_trust=bool(fp_spki) and not trusted, verified=verified,
                                         device_model=info["deviceModel"])
            r.withdrawn = withdrawn
            t.state = "waiting"
            box, done = {}, threading.Event()

            def ask():
                try:
                    box["v"] = self.handler.ask(r)
                except Exception:  # noqa: BLE001
                    box["v"] = (False, False)
                done.set()

            threading.Thread(target=ask, daemon=True).start()
            deadline = time.monotonic() + DECISION_TIMEOUT
            while True:
                finished = done.wait(0.3)
                if withdrawn.is_set() or self._stop.is_set():
                    t.code, t.error = proto.E_CANCELLED, "cancelled by sender"
                    return False, False
                # Odesilatel zavrel spojeni (zrusil pozadavek)?
                rd, _w, _x = select.select([conn.sock], [], [], 0)
                if rd and not conn.pending():
                    withdrawn.set()
                    t.code, t.error = proto.E_CANCELLED, "cancelled by sender"
                    return False, False
                if finished:
                    return box["v"]
                if time.monotonic() > deadline:
                    withdrawn.set()
                    t.code, t.error = proto.E_TIMEOUT, "no answer"
                    return False, False
        finally:
            self._prompt_sem.release()

    def upload(self, req, conn):
        q = req.query
        sid, fid, token = q.get("sessionId"), q.get("fileId"), q.get("token")
        if not sid or not fid or not token:
            raise lshttp.HTTPError(400, "Missing parameters")
        s = self.session
        if s is None or s.id != sid or s.ip != req.ip or s.ended:
            raise lshttp.HTTPError(403, "Invalid token or IP address")
        with s.lock:
            f = s.files.get(fid)
            if f is None or not hmac.compare_digest(f["token"].encode(), token.encode()) or f["state"] != "pending":
                raise lshttp.HTTPError(403, "Invalid token or IP address")
            f["state"] = "receiving"
            f["attempts"] += 1
            s.uploads.add(conn)
            s.last = time.monotonic()
        ui = s.t.files[f["ui"]]
        ui["state"] = "receiving"
        err, state = None, "done"
        try:
            self._receive_file(s, f, req, ui)
        except lshttp.HTTPError as e:
            err, state = e, "failed"
        except (ConnectionError, TimeoutError) as e:
            err = e
            # Odesilatel to muze zkusit znovu (max. 3x)
            state = "pending" if f["attempts"] < 3 and not s.t.cancelled and not s.ended else "failed"
            log("upload of %s failed: %s" % (f["rel"], e))
        except OSError as e:  # zapis na disk (plny disk, prava...)
            log("cannot save %s: %s" % (f["rel"], e))
            err, state = lshttp.HTTPError(500, "Cannot save the file"), "failed"
            s.t.error = "cannot save %s: %s" % (f["rel"], e.strerror or e)
        with s.lock:
            s.uploads.discard(conn)
            s.last = time.monotonic()
            f["state"] = state
        if state != "done":
            s.t.done -= ui["done"]
            ui["done"] = 0
        ui["state"] = {"pending": "waiting"}.get(state, state)
        self._maybe_end(s)
        if err is not None:
            raise err
        return 200, None

    def _receive_file(self, s, f, req, ui):
        part_fd = transfer.Receiver._open_part_dir(s.dest)
        name = "ls-" + secrets.token_hex(16) + ".part"
        placed = False
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=part_fd)
            h = hashlib.sha256()
            n = 0
            last_ui = 0.0
            with os.fdopen(fd, "wb") as out:
                while True:
                    if s.t.cancelled or s.ended:
                        raise ConnectionError("cancelled")
                    b = req.body.read()
                    if not b:
                        break
                    n += len(b)
                    if n > f["size"]:
                        raise lshttp.HTTPError(400, "More data than announced")
                    out.write(b)
                    h.update(b)
                    ui["done"] += len(b)
                    s.t.done += len(b)
                    now = time.monotonic()
                    if now - last_ui > 0.1:
                        last_ui = now
                        s.last = now
                        self.handler.update(s.t)
                out.flush()
                os.fsync(out.fileno())
            if n != f["size"]:
                raise lshttp.HTTPError(400, "File size does not match")
            if f["sha256"] is not None and not hmac.compare_digest(h.digest(), f["sha256"]):
                raise lshttp.HTTPError(422, "Checksum mismatch")
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=part_fd)
            try:
                os.fchmod(fd, 0o644)
                if f["modified"]:
                    os.utime(fd, (f["modified"], f["modified"]))
            finally:
                os.close(fd)
            with s.lock:
                saved = self._place(s, part_fd, name, f["parts"])
                placed = True
                if saved not in s.saved:
                    s.saved.append(saved)
        finally:
            if not placed:
                try:
                    os.unlink(name, dir_fd=part_fd)
                except OSError:
                    pass
            os.close(part_fd)
            try:
                os.rmdir(os.path.join(s.dest, transfer.PART_DIR))
            except OSError:
                pass

    def _place(self, s, part_fd, name, parts):
        """Presune overeny soubor do cile bez prepsani; vrati cestu top-level polozky."""
        dfd = os.open(s.dest, os.O_RDONLY | os.O_DIRECTORY)
        try:
            if len(parts) == 1:
                final = transfer._place_file(part_fd, name, dfd, parts[0])
                return os.path.join(s.dest, final)
            top = s.top_dirs.get(parts[0])
            if top is None:
                top = s.top_dirs[parts[0]] = transfer._reserve_dir(dfd, parts[0])
            fds = [os.open(top, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dfd)]
            try:
                for p in parts[1:-1]:
                    try:
                        os.mkdir(p, 0o755, dir_fd=fds[-1])
                    except FileExistsError:
                        pass
                    fds.append(os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1]))
                transfer._place_file(part_fd, name, fds[-1], parts[-1])
            finally:
                for fd in fds:
                    os.close(fd)
            return os.path.join(s.dest, top)
        finally:
            os.close(dfd)

    def _maybe_end(self, s):
        with s.lock:
            states = [f["state"] for f in s.files.values()]
        if all(x in ("done", "failed") for x in states):
            if all(x == "done" for x in states):
                self._end(s, "done")
            else:
                self._end(s, "failed", "%d file(s) failed" % states.count("failed"))
        else:
            self.handler.update(s.t)

    def _end(self, s, state, error=""):
        with self.slot:
            if s.ended:
                return
            s.ended = True
            if self.session is s:
                self.session = None
        t = s.t
        t.saved = list(s.saved)
        if t.state not in ("cancelled",):
            t.state = state
        if error and not t.error:
            t.error = error
        for c in list(s.uploads):
            c.abort()
        self._log(t, t.state)
        self.handler.finished(t)
        log("session %s ended: %s %s" % (s.id, t.state, t.error))

    def _receiver_cancel(self, s):
        """Uzivatel zrusil prijem: ukoncit relaci a dat vedet odesilateli."""
        s.t.state, s.t.code, s.t.error = "cancelled", proto.E_CANCELLED, "cancelled"
        self._end(s, "cancelled")
        port = s.info.get("port") or localsend.DEFAULT_PORT

        def notify():
            try:
                c = lshttp.Client(self.identity, s.ip, port, expected_fp=s.cert_fp, timeout=5)
                try:
                    c.request_json("POST", localsend.API + "/cancel", query={"sessionId": s.id})
                finally:
                    c.close()
            except Exception:  # noqa: BLE001 - odesilatel uz nemusi byt dostupny
                pass
        threading.Thread(target=notify, daemon=True).start()

    def cancel(self, req):
        sid = req.query.get("sessionId")
        with self.slot:
            pending = self.pending
            s = self.session
        if pending and pending[0] == req.ip and (sid is None or s is None):
            pending[1].set()  # zruseni pred rozhodnutim uzivatele
            return 200, None
        if s and s.ip == req.ip and (sid is None or sid == s.id):
            s.t.state, s.t.code, s.t.error = "cancelled", proto.E_CANCELLED, "cancelled by sender"
            self._end(s, "cancelled")
            return 200, None
        # Prijemce rusi prenos, ktery mu prave posilame my
        if sid and self.on_cancel_received(req.ip, sid):
            return 200, None
        return 200, None

    def _log(self, t, state):
        try:
            self.history.add({"direction": "in", "peer": t.peer_name, "peer_id": t.peer_id, "protocol": "localsend",
                              "items": t.items[:20], "total": t.total, "state": state, "error": t.error,
                              "saved": t.saved[:20], "device_type": t.device_type})
        except OSError:
            pass
