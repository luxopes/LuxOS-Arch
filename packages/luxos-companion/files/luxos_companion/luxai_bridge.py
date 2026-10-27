"""Most mezi telefonem a LuxAI: luxai.request/luxai.cancel -> `luxai --remote-session` (JSON radky).

Kontrakt luxai --remote-session (stdin -> LuxAI, stdout -> most, jeden JSON objekt na radek, UTF-8):
  in:  {"type":"request","id":UUID,"text":str,"mode":"chat"|"agent"}, {"type":"cancel","request_id":UUID}
  out: {"type":"ready","protocol":1} jednou na zacatku, {"type":"delta","reply_to":UUID,"text":str},
       {"type":"done","reply_to":UUID}, {"type":"error","reply_to":UUID|null,"code":str,"message":str}
Jeden bezici pozadavek (druhy -> "busy"); konverzace trva po dobu behu procesu = jednoho spojeni.

Pro kazde spojeni s telefonem jeden proces, spusteny az prvnim pozadavkem a ukonceny s odpojenim.
Text uzivatele jde jen jako data na stdin (zadny shell, zadne argumenty). Opravneni a potvrzovani
nastroju resi LuxAI na pocitaci (protokol v1 nema potvrzovani v telefonu). Kdyz luxai rezim
--remote-session nezna (kod 2 nebo "unknown option"), telefon dostane chybu luxai_unavailable.
ID pozadavku telefonu se do LuxAI neposilaji - most pouziva vlastni UUID.
"""
import json
import os
import re
import uuid

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

MAX_TEXT = 8000
CHUNK = 4000                 # znaku v jedne luxai.delta (ramec max. 64 KiB i s escapovanim)
MAX_LINE = 4 * 1024 * 1024   # radek od LuxAI
KILL_AFTER_MS = 3000


def _(s):
    return s


def set_translator(fn):
    global _
    _ = fn


def luxai_argv():
    exe = os.environ.get("LUXOS_COMPANION_LUXAI") or "luxai"
    return [exe, "--remote-session"]


class LuxAIBridge:
    """Jedna relace LuxAI pro jedno spojeni. send(dict) posila zpravy protokolu telefonu (bez v/id)."""

    def __init__(self, send, argv=None):
        self.send = send
        self.argv = argv or luxai_argv()
        self.proc = None
        self.ready = False
        self.active = None           # {"phone": id telefonu, "bridge": nase UUID, "cancelled": bool, "sent": bool}
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
        text, mode = msg.get("text"), msg.get("mode", "chat")
        if not isinstance(text, str) or not text.strip():
            return self._error(rid, "invalid_request", _("The request has no text."))
        if len(text) > MAX_TEXT:
            return self._error(rid, "invalid_request", _("The request is too long (at most 8000 characters)."))
        if mode not in ("chat", "agent"):
            return self._error(rid, "invalid_request", _("Unknown LuxAI mode."))
        if self.active is not None:
            return self._error(rid, "busy", _("LuxAI is still working on the previous request."))
        if self.proc is None and not self._start():
            return self._error(rid, "luxai_unavailable", self.unavailable_text())
        self.active = {"phone": rid, "bridge": str(uuid.uuid4()), "cancelled": False, "sent": False,
                       "text": text, "mode": mode}
        if self.ready:
            self._send_active()
        return None

    def cancel(self, msg):
        rid = msg.get("request_id")
        a = self.active
        if a is None or a["phone"] != rid or a["cancelled"]:
            return
        a["cancelled"] = True
        if a["sent"]:
            self._write({"type": "cancel", "request_id": a["bridge"]})
        else:
            self.active = None       # jeste neodeslano do LuxAI - staci zapomenout

    def close(self):
        """Odpojeni telefonu: ukoncit proces LuxAI (EOF na stdin, pak SIGTERM, pak SIGKILL)."""
        self.closed = True
        self.active = None
        proc, self.proc = self.proc, None
        if proc is None:
            return
        if self.cancellable:
            self.cancellable.cancel()
        try:
            proc.get_stdin_pipe().close(None)
        except GLib.Error:
            pass
        proc.send_signal(15)

        def kill():
            try:
                proc.force_exit()
            except GLib.Error:
                pass
            return False
        GLib.timeout_add(KILL_AFTER_MS, kill)

    @staticmethod
    def unavailable_text():
        return _("LuxAI on this computer cannot answer requests from the phone yet. "
                 "Update LuxAI (luxai --remote-session) and try again.")

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
        a, self.active = self.active, None
        if a is None or a["cancelled"]:
            return
        if not was_ready and (status == 2 or re.search(r"unknown option|unrecognized (option|argument)", err)):
            self._error(a["phone"], "luxai_unavailable", self.unavailable_text())
        else:
            self._error(a["phone"], "luxai_failed", _("LuxAI stopped unexpectedly. Try again."))

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
            if a is not None and not a["sent"]:
                self._send_active()
            return
        reply = msg.get("reply_to")
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
        elif t == "done":
            self.active = None
            if not a["cancelled"]:
                self.send({"type": "luxai.done", "reply_to": a["phone"]})
        elif t == "error":
            self.active = None
            if not a["cancelled"]:
                code = msg.get("code") if isinstance(msg.get("code"), str) else "luxai_error"
                text = msg.get("message") if isinstance(msg.get("message"), str) else ""
                self._error(a["phone"], code[:64], text[:2000] or _("LuxAI could not finish the request."))

    def _send_active(self):
        a = self.active
        a["sent"] = True
        self._write({"type": "request", "id": a["bridge"], "text": a.pop("text"), "mode": a.pop("mode")})

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
