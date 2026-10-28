"""Most mezi telefonem a LuxAI: luxai.* zpravy telefonu <-> `luxai --remote-session` (JSON radky).

Kontrakt luxai --remote-session (stdin -> LuxAI, stdout -> most, jeden JSON objekt na radek, UTF-8):
  out: {"type":"ready","protocol":1,"capabilities":["models","tools","approvals"]} jednou na zacatku
       (capabilities chybi u starsiho LuxAI = jen text)
  in:  {"type":"request","id":UUID,"text":str,"mode":"chat"|"agent"[,"model":id]},
       {"type":"cancel","request_id":UUID}, {"type":"models","id":UUID},
       {"type":"approval","request_id":UUID,"approval_id":str,"approved":bool}
  out: {"type":"delta","reply_to":UUID,"text":str}, {"type":"done","reply_to":UUID},
       {"type":"error","reply_to":UUID|null,"code":str,"message":str} (kod model_unavailable u modelu),
       {"type":"models","reply_to":UUID,"models":[{"id","name"}]},
       {"type":"tool","reply_to":UUID,"tool_id","name","state":"running|completed|failed|waiting","detail"},
       {"type":"approval","reply_to":UUID,"tool_id","approval_id","name","detail","timeout_ms"}
Jeden bezici pozadavek (druhy -> "busy"); konverzace trva po dobu behu procesu = jednoho spojeni.

Pro kazde spojeni s telefonem jeden proces, spusteny az prvnim pozadavkem a ukonceny s odpojenim.
Text uzivatele jde jen jako data na stdin (zadny shell, zadne argumenty). ID pozadavku telefonu se do
LuxAI neposilaji - most pouziva vlastni UUID a mapuje je obema smery (delta/done/error, tool, approval
-> reply_to telefonu; luxai.approval.respond -> request_id mostu).

Mobilni souhlas: approval_id plati jen pro tento telefon (toto spojeni), zivy pozadavek, ve lhute
timeout_ms (nejvys 120 s) a jen jednou; pozdni, opakovane, cizi a nezname ID se odmitnou chybou.
Jaky nastroj smi o souhlas pozadat (jen akce s potvrzenim, nikdy root/vstup) a vazbu na argumenty
nastroje resi LuxAI. Kdyz luxai rezim --remote-session nezna (kod 2 nebo "unknown option"), telefon
dostane chybu luxai_unavailable.

CapabilityProbe: hello.ok musi prijit behem handshake, ale LuxAI se spousti az prvnim pozadavkem.
Schopnosti LuxAI se proto zjisti jednou za beh sluzby (spustit, precist ready, zavrit) a znovu, kdyz se
zmeni spustitelny soubor luxai (aktualizace).
"""
import json
import os
import re
import time
import uuid

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import wire  # noqa: E402

MAX_TEXT = 8000
CHUNK = 4000                 # znaku v jedne luxai.delta (ramec max. 64 KiB i s escapovanim)
MAX_LINE = 4 * 1024 * 1024   # radek od LuxAI
KILL_AFTER_MS = 3000
MAX_ID = 200                 # model id/nazev, tool_id, approval_id, nazev nastroje
MAX_MODELS = 100
MAX_PENDING_MODELS = 4
MAX_TOOLS = 100              # volani nastroju v jedne odpovedi
MAX_DETAIL = 4000
TOOL_STATES = ("running", "completed", "failed", "waiting")
APPROVAL_DEFAULT_MS = 60000
APPROVAL_MIN_MS = 1000
APPROVAL_MAX_MS = 120000
PROBE_TIMEOUT_MS = 5000
PROBE_RETRY_S = 60           # neuspesne zjisteni (casovy limit) zkusit znovu nejdriv za minutu
# schopnosti remote-session -> schopnosti v hello.ok
CAPABILITIES = {"models": "luxai.models", "tools": "luxai.tools", "approvals": "luxai.approvals"}


def _(s):
    return s


def set_translator(fn):
    global _
    _ = fn


def luxai_argv():
    exe = os.environ.get("LUXOS_COMPANION_LUXAI") or "luxai"
    return [exe, "--remote-session"]


def _valid_id(v):
    """ID od telefonu/LuxAI: neprazdny retezec do 200 znaku bez ridicich znaku (neorezava se)."""
    return isinstance(v, str) and 0 < len(v) <= MAX_ID and wire.clean_text(v, MAX_ID, False) == v


def _stop(proc):
    """Ukoncit proces: EOF na stdin, SIGTERM, po 3 s SIGKILL."""
    try:
        proc.get_stdin_pipe().close(None)
    except (GLib.Error, AttributeError):
        pass
    proc.send_signal(15)

    def kill():
        try:
            proc.force_exit()
        except GLib.Error:
            pass
        return False
    GLib.timeout_add(KILL_AFTER_MS, kill)


class LuxAIBridge:
    """Jedna relace LuxAI pro jedno spojeni. send(dict) posila zpravy protokolu telefonu (bez v/id)."""

    def __init__(self, send, argv=None, clock=time.monotonic):
        self.send = send
        self.argv = argv or luxai_argv()
        self.clock = clock
        self.features = set()        # schopnosti ohlasene telefonu v hello.ok (nastavi Session)
        self.on_change = None        # zmena poctu cekajicich souhlasu (stav v okne Telefon)
        self.proc = None
        self.ready = False
        self.luxai_caps = set()
        self.active = None           # {"phone": id telefonu, "bridge": nase UUID, "cancelled", "sent", "tools"}
        self.pending_models = {}     # nase UUID -> id telefonu
        self.approvals = {}          # approval_id -> {"phone", "bridge", "tool_id", "deadline"}
        self.spent = set()           # vyrizena approval_id (opakovani = chyba)
        self.before_ready = []
        self.out_buf = b""
        self.err_tail = b""
        self.cancellable = None
        self.write_queue = []
        self.writing = False
        self.closed = False
        self._stdout_eof = False
        self._exit_status = None
        self.on_idle = None          # testy

    # ---- pozadavky z telefonu ----
    def request(self, msg):
        rid = msg["id"]
        text, mode, model = msg.get("text"), msg.get("mode", "chat"), msg.get("model")
        if not isinstance(text, str) or not text.strip():
            return self._error(rid, "invalid_request", _("The request has no text."))
        if len(text) > MAX_TEXT:
            return self._error(rid, "invalid_request", _("The request is too long (at most 8000 characters)."))
        if mode not in ("chat", "agent"):
            return self._error(rid, "invalid_request", _("Unknown LuxAI mode."))
        if model is not None:
            if not _valid_id(model):
                return self._error(rid, "invalid_request", _("Invalid model."))
            if "luxai.models" not in self.features:
                # nikdy potichu jiny model
                return self._error(rid, "model_unavailable", _("Choosing a model is not supported on this computer."))
        if self.active is not None:
            return self._error(rid, "busy", _("LuxAI is still working on the previous request."))
        if self.proc is None and not self._start():
            return self._error(rid, "luxai_unavailable", self.unavailable_text())
        self.active = {"phone": rid, "bridge": str(uuid.uuid4()), "cancelled": False, "sent": False,
                       "text": text, "mode": mode, "model": model, "tools": set()}
        if self.ready:
            self._send_active()
        return None

    def cancel(self, msg):
        rid = msg.get("request_id")
        a = self.active
        if a is None or a["phone"] != rid or a["cancelled"]:
            return
        a["cancelled"] = True
        self._drop_approvals(a["bridge"])
        if a["sent"]:
            self._write({"type": "cancel", "request_id": a["bridge"]})
        else:
            self.active = None       # jeste neodeslano do LuxAI - staci zapomenout

    def models(self, msg):
        rid = msg["id"]
        if "luxai.models" not in self.features:
            return self._error(rid, "unsupported", _("Choosing a model is not supported on this computer."))
        if len(self.pending_models) >= MAX_PENDING_MODELS:
            return self._error(rid, "busy", _("LuxAI is still working on the previous request."))
        if self.proc is None and not self._start():
            return self._error(rid, "luxai_unavailable", self.unavailable_text())
        bid = str(uuid.uuid4())
        self.pending_models[bid] = rid
        self._write_ready({"type": "models", "id": bid})
        return None

    def approve(self, msg):
        """luxai.approval.respond: rozhodnuti telefonu o navrzene akci - jednou, vcas, jen pro zivy pozadavek."""
        rid = msg["id"]
        request_id, approval_id, approved = msg.get("request_id"), msg.get("approval_id"), msg.get("approved")
        if not isinstance(approved, bool) or not _valid_id(approval_id) or not isinstance(request_id, str):
            return self._error(rid, "invalid_request", _("Invalid approval."))
        entry = self.approvals.get(approval_id)
        a = self.active
        if entry is None or entry["phone"] != request_id:
            return self._error(rid, "approval_invalid", self._approval_gone_text())
        if (a is None or a["bridge"] != entry["bridge"] or a["cancelled"] or self.proc is None
                or self.clock() >= entry["deadline"]):
            del self.approvals[approval_id]
            self.spent.add(approval_id)
            self._changed()
            return self._error(rid, "approval_invalid", self._approval_gone_text())
        del self.approvals[approval_id]
        self.spent.add(approval_id)
        self._write({"type": "approval", "request_id": entry["bridge"], "approval_id": approval_id,
                     "approved": approved})
        self._changed()
        return None

    def pending_approvals(self):
        now = self.clock()
        return sum(1 for e in self.approvals.values() if now < e["deadline"])

    def close(self):
        """Odpojeni telefonu: ukoncit proces LuxAI (EOF na stdin, pak SIGTERM, pak SIGKILL)."""
        self.closed = True
        self.active = None
        self.pending_models = {}
        self.approvals = {}
        self.before_ready = []
        proc, self.proc = self.proc, None
        if proc is None:
            return
        if self.cancellable:
            self.cancellable.cancel()
        _stop(proc)

    @staticmethod
    def unavailable_text():
        return _("LuxAI on this computer cannot answer requests from the phone yet. "
                 "Update LuxAI (luxai --remote-session) and try again.")

    @staticmethod
    def _approval_gone_text():
        return _("This approval is no longer valid (already answered, expired or the request has ended).")

    def _changed(self):
        if self.on_change:
            self.on_change()

    def _drop_approvals(self, bridge_id):
        gone = [k for k, e in self.approvals.items() if e["bridge"] == bridge_id]
        for k in gone:
            del self.approvals[k]
            self.spent.add(k)
        if gone:
            self._changed()

    # ---- proces ----
    def _start(self):
        flags = (Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE
                 | Gio.SubprocessFlags.STDERR_PIPE)
        try:
            launcher = Gio.SubprocessLauncher.new(flags)
            launcher.set_cwd(os.path.expanduser("~"))
            self.proc = launcher.spawnv(self.argv)
        except GLib.Error:
            self.proc = None
            return False
        self.ready = False
        self.luxai_caps = set()
        self.out_buf = b""
        self.err_tail = b""
        self._stdout_eof = False
        self._exit_status = None
        self.cancellable = Gio.Cancellable()
        proc = self.proc
        self._read(proc, proc.get_stdout_pipe(), self._on_stdout)
        self._read(proc, proc.get_stderr_pipe(), self._on_stderr)
        proc.wait_async(self.cancellable, self._on_exit, proc)
        return True

    def _read(self, proc, stream, handler):
        def done(src, res, _data):
            try:
                data = src.read_bytes_finish(res).get_data()
            except GLib.Error:
                data = b""
            if proc is not self.proc:
                return
            handler(proc, data)
            if data:
                stream.read_bytes_async(65536, GLib.PRIORITY_DEFAULT, self.cancellable, done, None)
        stream.read_bytes_async(65536, GLib.PRIORITY_DEFAULT, self.cancellable, done, None)

    def _on_stderr(self, _proc, data):
        self.err_tail = (self.err_tail + data)[-4096:]

    def _on_stdout(self, proc, data):
        if not data:
            self._stdout_eof = True
            self._maybe_finished(proc)
            return
        self.out_buf += data
        while b"\n" in self.out_buf:
            line, self.out_buf = self.out_buf.split(b"\n", 1)
            self._line(line)
            if proc is not self.proc:
                return
        if len(self.out_buf) > MAX_LINE:
            self.out_buf = b""       # prilis dlouhy radek - zahodit

    def _on_exit(self, proc, res, _data):
        try:
            proc.wait_finish(res)
        except GLib.Error:
            return
        self._exit_status = proc.get_exit_status() if proc.get_if_exited() else -1
        self._maybe_finished(proc)

    def _maybe_finished(self, proc):
        if proc is not self.proc or not self._stdout_eof or self._exit_status is None:
            return
        status, err = self._exit_status, self.err_tail.decode("utf-8", "replace").lower()
        was_ready = self.ready
        self.proc = None
        self.ready = False
        self.before_ready = []
        a, self.active = self.active, None
        models, self.pending_models = self.pending_models, {}
        if self.approvals:
            self.spent.update(self.approvals)
            self.approvals = {}
            self._changed()
        old = not was_ready and (status == 2 or re.search(r"unknown option|unrecognized (option|argument)", err))
        waiting = list(models.values())
        if a is not None and not a["cancelled"]:
            waiting.append(a["phone"])
        for phone in waiting:
            if old:
                self._error(phone, "luxai_unavailable", self.unavailable_text())
            else:
                self._error(phone, "luxai_failed", _("LuxAI stopped unexpectedly. Try again."))

    def _line(self, raw):
        try:
            msg = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return
        if not isinstance(msg, dict):
            return
        t = msg.get("type")
        a = self.active
        if t == "ready":
            if msg.get("protocol") != 1:
                return
            self.ready = True
            caps = msg.get("capabilities")
            self.luxai_caps = {c for c in caps if isinstance(c, str)} if isinstance(caps, list) else set()
            queued, self.before_ready = self.before_ready, []
            for obj in queued:
                self._write(obj)
            if a is not None and not a["sent"]:
                self._send_active()
            return
        reply = msg.get("reply_to")
        if t in ("models", "error") and reply in self.pending_models:
            self._models_reply(self.pending_models.pop(reply), msg)
            return
        if t == "error" and reply is None:
            if a is not None and a["sent"]:
                reply = a["bridge"]
            else:
                return
        if a is None or reply != a["bridge"]:
            return                   # pozdni odpoved zruseneho nebo neznameho pozadavku
        if t == "delta":
            text = msg.get("text")
            if isinstance(text, str) and text and not a["cancelled"]:
                for i in range(0, len(text), CHUNK):
                    self.send({"type": "luxai.delta", "reply_to": a["phone"], "text": text[i:i + CHUNK]})
        elif t == "tool":
            self._tool(a, msg)
        elif t == "approval":
            self._approval(a, msg)
        elif t == "done":
            self.active = None
            self._drop_approvals(a["bridge"])
            if not a["cancelled"]:
                self.send({"type": "luxai.done", "reply_to": a["phone"]})
        elif t == "error":
            self.active = None
            self._drop_approvals(a["bridge"])
            if not a["cancelled"]:
                code = msg.get("code") if isinstance(msg.get("code"), str) else "luxai_error"
                text = msg.get("message") if isinstance(msg.get("message"), str) else ""
                if code == "model_unavailable" and not text:
                    text = _("The selected model is not available on this computer.")
                self._error(a["phone"], code[:64], text[:2000] or _("LuxAI could not finish the request."))

    def _models_reply(self, phone, msg):
        if msg.get("type") == "error":
            code = msg.get("code") if isinstance(msg.get("code"), str) else "luxai_error"
            text = msg.get("message") if isinstance(msg.get("message"), str) else ""
            self._error(phone, code[:64], text[:2000] or _("The list of models could not be loaded."))
            return
        raw = msg.get("models")
        if not isinstance(raw, list):
            self._error(phone, "luxai_error", _("The list of models could not be loaded."))
            return
        items, seen = [], set()
        for m in raw:
            if len(items) >= MAX_MODELS:
                break
            if not isinstance(m, dict) or not _valid_id(m.get("id")) or m["id"] in seen:
                continue
            seen.add(m["id"])
            name = wire.clean_text(m.get("name"), MAX_ID, False).strip() or m["id"]
            items.append({"id": m["id"], "name": name})
        out = wire.message("luxai.models", reply_to=phone)
        wire.fit_items(out, "models", items)
        self.send(out)

    def _tool_slot(self, a, tool_id):
        """Misto pro dalsi volani nastroje v odpovedi (nejvys 100 ruznych tool_id)."""
        if tool_id in a["tools"]:
            return True
        if len(a["tools"]) >= MAX_TOOLS:
            return False
        a["tools"].add(tool_id)
        return True

    def _tool(self, a, msg):
        if a["cancelled"] or "luxai.tools" not in self.features:
            return
        tool_id, state = msg.get("tool_id"), msg.get("state")
        if not _valid_id(tool_id) or state not in TOOL_STATES or not self._tool_slot(a, tool_id):
            return
        if state != "waiting":
            # nastroj uz bezi / skoncil: pripadny souhlas k nemu prestava platit
            gone = [k for k, e in self.approvals.items() if e["bridge"] == a["bridge"] and e["tool_id"] == tool_id]
            for k in gone:
                del self.approvals[k]
                self.spent.add(k)
            if gone:
                self._changed()
        name = wire.clean_text(msg.get("name"), MAX_ID, False).strip() or "tool"
        self.send({"type": "luxai.tool", "reply_to": a["phone"], "tool_id": tool_id, "name": name,
                   "state": state, "detail": wire.clean_text(msg.get("detail"), MAX_DETAIL)})

    def _approval(self, a, msg):
        tool_id, approval_id = msg.get("tool_id"), msg.get("approval_id")
        if not _valid_id(approval_id) or approval_id in self.approvals or approval_id in self.spent:
            return
        detail = wire.clean_text(msg.get("detail"), MAX_DETAIL).strip()
        ok = (not a["cancelled"] and "luxai.approvals" in self.features and _valid_id(tool_id) and detail
              and self._tool_slot(a, tool_id))
        if not ok:
            # telefon souhlas nezobrazi - LuxAI hned odmitnout, at neceka do vyprseni
            self.spent.add(approval_id)
            self._write({"type": "approval", "request_id": a["bridge"], "approval_id": approval_id,
                         "approved": False})
            return
        timeout = msg.get("timeout_ms")
        if type(timeout) is not int:
            timeout = APPROVAL_DEFAULT_MS
        timeout = max(APPROVAL_MIN_MS, min(APPROVAL_MAX_MS, timeout))
        self.approvals[approval_id] = {"phone": a["phone"], "bridge": a["bridge"], "tool_id": tool_id,
                                       "deadline": self.clock() + timeout / 1000.0}
        name = wire.clean_text(msg.get("name"), MAX_ID, False).strip() or "tool"
        self.send({"type": "luxai.approval", "reply_to": a["phone"], "tool_id": tool_id,
                   "approval_id": approval_id, "name": name, "state": "waiting", "detail": detail,
                   "timeout_ms": timeout})
        self._changed()

    def _send_active(self):
        a = self.active
        a["sent"] = True
        obj = {"type": "request", "id": a["bridge"], "text": a.pop("text"), "mode": a.pop("mode")}
        model = a.pop("model")
        if model is not None:
            obj["model"] = model
        self._write(obj)

    def _write_ready(self, obj):
        if self.ready:
            self._write(obj)
        else:
            self.before_ready.append(obj)

    def _write(self, obj):
        if self.proc is None:
            return
        self.write_queue.append(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        self._flush()

    def _flush(self):
        if self.writing or not self.write_queue or self.proc is None:
            return
        self.writing = True
        chunk = self.write_queue.pop(0)
        proc = self.proc
        stream = proc.get_stdin_pipe()

        def done(src, res, _d):
            self.writing = False
            try:
                n = src.write_bytes_finish(res)
            except GLib.Error:
                return               # proces skoncil; chybu ohlasi _on_exit
            if proc is not self.proc:
                return
            if n < len(chunk):
                self.write_queue.insert(0, chunk[n:])     # castecny zapis
            self._flush()
        stream.write_bytes_async(GLib.Bytes.new(chunk), GLib.PRIORITY_DEFAULT, self.cancellable, done, None)

    def _error(self, reply_to, code, message):
        self.send({"type": "error", "reply_to": reply_to, "code": code, "message": message})
        return None


class CapabilityProbe:
    """Schopnosti `luxai --remote-session` z ready radku (jednou za beh sluzby, znovu po zmene souboru luxai).

    get(callback) zavola callback(set) hned z mezipameti, nebo po zjisteni (nejvys 5 s). Proces zjisteni
    dostane LUXOS_COMPANION_PROBE=1 a hned po ready se zavre (EOF na stdin, SIGTERM)."""

    def __init__(self, argv=None, clock=time.monotonic):
        self.argv = argv
        self.clock = clock
        self.caps = None
        self.stamp = None
        self.expires = None
        self.waiting = []
        self.proc = None
        self.buf = b""
        self.timer = None
        self.cancellable = None
        self.probes = 0              # testy

    def _argv(self):
        return self.argv or luxai_argv()

    def _stamp(self):
        exe = self._argv()[0]
        path = exe if os.sep in exe else GLib.find_program_in_path(exe)
        if not path:
            return None
        try:
            st = os.stat(path)
        except OSError:
            return None
        return (os.path.realpath(path), st.st_mtime_ns, st.st_size, st.st_ino)

    def cached(self):
        """Platna mezipamet (set), jinak None."""
        if self.caps is None or self._stamp() != self.stamp:
            return None
        if self.expires is not None and self.clock() >= self.expires:
            return None
        return set(self.caps)

    def get(self, callback):
        caps = self.cached()
        if caps is not None:
            callback(caps)
            return
        self.waiting.append(callback)
        if self.proc is None:
            self._start(self._stamp())

    def _start(self, stamp):
        if stamp is None:
            self._finish(set(), stamp, None)         # luxai neni nainstalovane
            return
        self.probes += 1
        flags = (Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE
                 | Gio.SubprocessFlags.STDERR_SILENCE)
        try:
            launcher = Gio.SubprocessLauncher.new(flags)
            launcher.set_cwd(os.path.expanduser("~"))
            launcher.setenv("LUXOS_COMPANION_PROBE", "1", True)
            proc = launcher.spawnv(self._argv())
        except GLib.Error:
            self._finish(set(), stamp, PROBE_RETRY_S)
            return
        self.proc = proc
        self.buf = b""
        self.cancellable = Gio.Cancellable()
        stream = proc.get_stdout_pipe()

        def read(src, res, _d):
            try:
                data = src.read_bytes_finish(res).get_data()
            except GLib.Error:
                data = b""
            if proc is not self.proc:
                return
            if not data:
                self._finish(set(), stamp, None)     # konec bez ready (stary LuxAI)
                return
            self.buf += data
            if b"\n" in self.buf:
                self._finish(self._parse(self.buf.split(b"\n", 1)[0]), stamp, None)
                return
            if len(self.buf) > 65536:
                self._finish(set(), stamp, None)
                return
            stream.read_bytes_async(4096, GLib.PRIORITY_DEFAULT, self.cancellable, read, None)
        stream.read_bytes_async(4096, GLib.PRIORITY_DEFAULT, self.cancellable, read, None)

        def timeout():
            self.timer = None
            if proc is self.proc:
                self._finish(set(), stamp, PROBE_RETRY_S)
            return False
        self.timer = GLib.timeout_add(PROBE_TIMEOUT_MS, timeout)

    @staticmethod
    def _parse(line):
        try:
            msg = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return set()
        if not isinstance(msg, dict) or msg.get("type") != "ready" or msg.get("protocol") != 1:
            return set()
        caps = msg.get("capabilities")
        return {c for c in caps if isinstance(c, str)} if isinstance(caps, list) else set()

    def _finish(self, caps, stamp, retry_s):
        proc, self.proc = self.proc, None
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None
        if proc is not None:
            if self.cancellable:
                self.cancellable.cancel()
            _stop(proc)              # GSubprocess proces sam uklidi (bez zombie)
        self.caps = set(caps)
        self.stamp = stamp
        self.expires = self.clock() + retry_s if retry_s else None
        waiting, self.waiting = self.waiting, []
        for cb in waiting:
            cb(set(caps))

    def close(self):
        if self.proc is not None:
            self._finish(set(), self.stamp, PROBE_RETRY_S)
