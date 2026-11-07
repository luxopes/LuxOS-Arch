#!/usr/bin/env python3
"""Testovaci server IMAP pro Postu LuxOS (nikdy ne skutecna schranka).

Podmnozina IMAP4rev1, kterou luxos-mail pouziva: TLS (implicitni i STARTTLS), LOGIN,
AUTHENTICATE PLAIN (SASL-IR), OAUTHBEARER/XOAUTH2 (--oauth, tokeny z rizeni), ENABLE, LIST (SPECIAL-USE priznaky), SELECT (CONDSTORE/QRESYNC),
STATUS, FETCH/UID FETCH (ENVELOPE, BODYSTRUCTURE, BODY.PEEK[...]<o.n>, CHANGEDSINCE, VANISHED),
UID SEARCH, UID STORE, UID MOVE/COPY, UID EXPUNGE, EXPUNGE, CREATE, IDLE, LOGOUT.

Rizeni testu: radkovy protokol na --control portu (127.0.0.1):
    deliver MAILBOX CESTA.eml [FLAGS]   prida zpravu (vsem v IDLE posle * N EXISTS)
    expunge MAILBOX UID                 smaze zpravu (* N EXPUNGE)
    flags MAILBOX UID \\Seen ...         nastavi priznaky (* N FETCH (FLAGS ...))
    password NOVE                       zmena hesla (heslo zmenene ve webmailu)
    token TOKEN UZIVATEL                platny pristupovy token (OAUTHBEARER/XOAUTH2)
    revoke                              zneplatni vsechny tokeny
    dump                                JSON stav schranek
    log                                 prijate prikazy (heslo zakryte)
"""
import argparse
import base64
import email
import email.utils
import json
import os
import re
import select
import socket
import ssl
import sys
import threading
import time
from email import policy

LOCK = threading.RLock()


class Message:
    def __init__(self, uid, raw, flags, internal, modseq):
        self.uid = uid
        self.raw = raw
        self.flags = set(flags)
        self.internal = internal
        self.modseq = modseq
        self.msg = email.message_from_bytes(raw, policy=policy.compat32)


class Mailbox:
    def __init__(self, name, special=None):
        self.name = name
        self.special = special
        self.messages = []
        self.uidvalidity = 1700000000 + len(name)
        self.uidnext = 1
        self.modseq = 1
        self.expunged = []  # (uid, modseq)

    def add(self, raw, flags=(), internal=None):
        self.modseq += 1
        m = Message(self.uidnext, raw, flags, internal or time.time(), self.modseq)
        self.uidnext += 1
        self.messages.append(m)
        return m


class State:
    def __init__(self, users, qresync, oauth=(), sasl_ir=True):
        self.users = users
        self.qresync = qresync
        self.oauth = list(oauth)
        self.sasl_ir = sasl_ir
        self.tokens = {}
        self.dovecot_flags = False
        self.boxes = {
            "INBOX": Mailbox("INBOX"),
            "Sent": Mailbox("Sent", "\\Sent"),
            "Trash": Mailbox("Trash", "\\Trash"),
            "Drafts": Mailbox("Drafts", "\\Drafts"),
            "Odeslan&AOk-": Mailbox("Odeslan&AOk-"),
        }
        self.sessions = []
        self.log = []


def quote(value):
    if value is None:
        return "NIL"
    if isinstance(value, bytes):
        b = value
    else:
        b = str(value).encode("utf-8", "surrogateescape")
    if any(c > 126 or c < 32 for c in b) or b'"' in b or b"\\" in b:
        return "{%d}\r\n" % len(b) + b.decode("utf-8", "surrogateescape")
    return '"' + b.decode() + '"'


def addr_list(value):
    if not value:
        return "NIL"
    out = []
    for name, addr in email.utils.getaddresses([value]):
        if not addr:
            continue
        mailbox, _, host = addr.partition("@")
        out.append("(%s NIL %s %s)" % (quote(name) if name else "NIL", quote(mailbox), quote(host)))
    return "(" + "".join(out) + ")" if out else "NIL"


def raw_header(msg, name):
    # surova hodnota (bajty 8bit jako surrogateescape): Message.get by 8bit nahradil znakem U+FFFD
    for k, v in msg._headers:
        if k.lower() == name.lower():
            return re.sub(r"\r?\n", "", v)
    return None


def envelope(m):
    h = m.msg
    def hv(k):
        return raw_header(h, k)
    frm = hv("From")
    return "(%s %s %s %s %s %s %s %s %s %s)" % (
        quote(hv("Date")), quote(hv("Subject")), addr_list(frm), addr_list(hv("Sender") or frm),
        addr_list(hv("Reply-To") or frm), addr_list(hv("To")), addr_list(hv("Cc")), addr_list(hv("Bcc")),
        quote(hv("In-Reply-To")), quote(hv("Message-ID")))


def params(part, header="content-type"):
    items = part.get_params(header=header, unquote=True) or []
    out = []
    for k, v in items[1:]:
        if isinstance(v, tuple):
            v = email.utils.collapse_rfc2231_value(v)
        out.append("%s %s" % (quote(k.upper() if k == "charset" else k), quote(v)))
    return "(" + " ".join(out) + ")" if out else "NIL"


def payload_bytes(part):
    # presne bajty tela casti (get_payload by 8bit text prekodoval podle charset)
    p = part._payload
    if isinstance(p, list):
        return b""
    return p.encode("ascii", "surrogateescape") if isinstance(p, str) else bytes(p)


def bodystructure(part):
    if part.is_multipart():
        kids = "".join(bodystructure(p) for p in part.get_payload())
        return "(%s %s %s NIL NIL)" % (kids, quote(part.get_content_subtype()), params(part))
    maintype = part.get_content_maintype()
    sub = part.get_content_subtype()
    body = payload_bytes(part)
    enc = (part.get("Content-Transfer-Encoding") or "7bit").strip().lower()
    disp = part.get("Content-Disposition")
    disp_s = "NIL"
    if disp:
        dtype = disp.split(";")[0].strip().lower()
        disp_s = "(%s %s)" % (quote(dtype), params(part, "content-disposition"))
    base = "%s %s %s NIL NIL %s %d" % (quote(maintype), quote(sub), params(part), quote(enc), len(body))
    if maintype == "text":
        return "(%s %d NIL %s NIL NIL)" % (base, body.count(b"\n"), disp_s)
    return "(%s NIL %s NIL NIL)" % (base, disp_s)


def section_part(msg, section):
    if section in ("", "TEXT"):
        return None
    part = msg
    for num in section.split("."):
        n = int(num)
        if part.is_multipart():
            part = part.get_payload()[n - 1]
        elif n != 1:
            return None
    return part


def fetch_section(m, section):
    sec = section.upper()
    if sec == "":
        return m.raw
    if sec == "HEADER":
        return m.raw.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
    if sec == "TEXT":
        parts = m.raw.split(b"\r\n\r\n", 1)
        return parts[1] if len(parts) > 1 else b""
    part = section_part(m.msg, section)
    if part is None:
        return b""
    return payload_bytes(part)


def parse_set(text, maxval):
    out = set()
    for piece in text.split(","):
        if ":" in piece:
            a, b = piece.split(":")
            a = maxval if a == "*" else int(a)
            b = maxval if b == "*" else int(b)
            lo, hi = min(a, b), max(a, b)
            out.update(range(lo, hi + 1))
        else:
            out.add(maxval if piece == "*" else int(piece))
    return out


def tokenize(line):
    out = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == " ":
            i += 1
        elif c == '"':
            j = i + 1
            buf = ""
            while j < len(line) and line[j] != '"':
                if line[j] == "\\":
                    j += 1
                buf += line[j]
                j += 1
            out.append(buf)
            i = j + 1
        elif c == "(":
            depth = 0
            j = i
            while j < len(line):
                if line[j] == "(":
                    depth += 1
                elif line[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append(line[i:j + 1])
            i = j + 1
        else:
            j = i
            depth = 0
            while j < len(line) and (line[j] != " " or depth > 0):
                if line[j] == "[":
                    depth += 1
                elif line[j] == "]":
                    depth -= 1
                j += 1
            out.append(line[i:j])
            i = j
    return out


class Session(threading.Thread):
    def __init__(self, state, sock, implicit_tls, ctx):
        super().__init__(daemon=True)
        self.state = state
        self.sock = sock
        self.ctx = ctx
        self.tls = implicit_tls
        self.user = None
        self.box = None
        self.enabled = set()
        self.idle_tag = None
        self.pending = []
        self.rbuf = b""
        self.alive = True

    def caps(self):
        c = ["IMAP4rev1", "IDLE", "UIDPLUS", "MOVE", "CONDSTORE", "ENABLE", "LITERAL+", "SPECIAL-USE"]
        if self.state.sasl_ir:
            c.append("SASL-IR")
        if self.state.qresync:
            c.append("QRESYNC")
        if not self.tls:
            c.append("STARTTLS")
            c.append("LOGINDISABLED")
        elif self.user is None:
            c.append("AUTH=PLAIN")
            c += ["AUTH=" + m for m in self.state.oauth]
        return " ".join(c)

    def send(self, text):
        data = text.encode("utf-8", "surrogateescape") if isinstance(text, str) else text
        self.sock.sendall(data)

    def readline(self, timeout=None):
        while b"\r\n" not in self.rbuf:
            if timeout is not None:
                if self.tls and self.sock.pending():
                    pass
                else:
                    r, _, _ = select.select([self.sock], [], [], timeout)
                    if not r:
                        return None
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            self.rbuf += chunk
        line, self.rbuf = self.rbuf.split(b"\r\n", 1)
        return line.decode("utf-8", "surrogateescape")

    def notify(self, text):
        with LOCK:
            self.pending.append(text)

    def run(self):
        try:
            if self.tls:
                self.sock = self.ctx.wrap_socket(self.sock, server_side=True)
            self.send("* OK [CAPABILITY %s] LuxOS test IMAP ready\r\n" % self.caps())
            while self.alive:
                line = self.readline()
                self.handle(line)
        except (ConnectionError, OSError, ssl.SSLError):
            pass
        finally:
            with LOCK:
                if self in self.state.sessions:
                    self.state.sessions.remove(self)
            try:
                self.sock.close()
            except OSError:
                pass

    def log(self, line):
        safe = re.sub(r'(?i)^(\S+ LOGIN \S+ ).*', r'\1"***"', line)
        safe = re.sub(r'(?i)^(\S+ AUTHENTICATE (PLAIN|OAUTHBEARER|XOAUTH2) ).*', r'\1***', safe)
        if self.user is None and re.match(r'^[A-Za-z0-9+/=]{16,}$', safe):
            safe = "***"
        with LOCK:
            self.state.log.append(safe)

    def handle(self, line):
        self.log(line)
        parts = line.split(" ", 2)
        if len(parts) < 2:
            self.send("* BAD empty\r\n")
            return
        tag, cmd = parts[0], parts[1].upper()
        rest = parts[2] if len(parts) > 2 else ""
        uid = False
        if cmd == "UID":
            sub = rest.split(" ", 1)
            cmd = sub[0].upper()
            rest = sub[1] if len(sub) > 1 else ""
            uid = True
        try:
            getattr(self, "cmd_" + cmd.lower(), self.cmd_unknown)(tag, rest, uid)
        except Exception as e:  # noqa: BLE001 - testovaci server: chyba = BAD
            self.send("%s BAD %s\r\n" % (tag, str(e).replace("\r", " ").replace("\n", " ")))

    def cmd_unknown(self, tag, rest, uid):
        self.send("%s BAD unknown command\r\n" % tag)

    def cmd_capability(self, tag, rest, uid):
        self.send("* CAPABILITY %s\r\n%s OK done\r\n" % (self.caps(), tag))

    def cmd_noop(self, tag, rest, uid):
        self.flush_pending()
        self.send("%s OK noop\r\n" % tag)

    def cmd_starttls(self, tag, rest, uid):
        self.send("%s OK begin TLS\r\n" % tag)
        self.sock = self.ctx.wrap_socket(self.sock, server_side=True)
        self.tls = True
        self.rbuf = b""

    def login_ok(self, tag, user, password):
        if self.state.users.get(user) == password:
            self.user = user
            self.send("%s OK [CAPABILITY %s] logged in\r\n" % (tag, self.caps()))
        else:
            time.sleep(0.2)
            self.send("%s NO [AUTHENTICATIONFAILED] Authentication failed.\r\n" % tag)

    def cmd_login(self, tag, rest, uid):
        if not self.tls:
            self.send("%s NO [PRIVACYREQUIRED] TLS required\r\n" % tag)
            return
        t = tokenize(rest)
        self.login_ok(tag, t[0], t[1])

    def oauth_login(self, tag, mech, data):
        text = base64.b64decode(data).decode("utf-8", "replace")
        fields = {}
        user = ""
        if mech == "OAUTHBEARER":
            head, _, rest = text.partition("\x01")
            gs2 = head.split(",")
            if len(gs2) >= 2 and gs2[1].startswith("a="):
                user = gs2[1][2:].replace("=2C", ",").replace("=3D", "=")
            text = rest
        for item in text.split("\x01"):
            if "=" in item:
                k, v = item.split("=", 1)
                fields[k] = v
        if mech == "XOAUTH2":
            user = fields.get("user", "")
        auth = fields.get("auth", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        with LOCK:
            self.state.log.append("AUTH %s user=%s host=%s port=%s" % (mech, user, fields.get("host", "-"), fields.get("port", "-")))
            ok = bool(token) and self.state.tokens.get(token) == user.lower()
        if ok:
            self.user = user
            self.send("%s OK [CAPABILITY %s] logged in\r\n" % (tag, self.caps()))
            return
        # RFC 7628: chyba v pokracovani, klient odpovi prazdnou zpravou, pak NO
        self.send("+ %s\r\n" % base64.b64encode(b'{"status":"invalid_token","scope":"mail"}').decode())
        reply = self.readline()
        with LOCK:
            self.state.log.append("SASL abort reply=%r" % reply)
        self.send("%s NO [AUTHENTICATIONFAILED] Authentication failed.\r\n" % tag)

    def cmd_authenticate(self, tag, rest, uid):
        t = rest.split(" ")
        mech = t[0].upper()
        if mech in self.state.oauth:
            if len(t) > 1:
                data = t[1]
            else:
                self.send("+ \r\n")
                data = self.readline()
            self.oauth_login(tag, mech, data)
            return
        if t[0].upper() != "PLAIN":
            self.send("%s NO unsupported\r\n" % tag)
            return
        if len(t) > 1:
            token = t[1]
        else:
            self.send("+ \r\n")
            token = self.readline()
        _, user, password = base64.b64decode(token).split(b"\0")
        self.login_ok(tag, user.decode(), password.decode())

    def cmd_enable(self, tag, rest, uid):
        names = [x.upper() for x in rest.split()]
        ok = [n for n in names if n in ("CONDSTORE",) or (n == "QRESYNC" and self.state.qresync)]
        self.enabled.update(ok)
        if "QRESYNC" in ok:
            self.enabled.add("CONDSTORE")
        self.send("* ENABLED %s\r\n%s OK enabled\r\n" % (" ".join(ok), tag))

    def cmd_list(self, tag, rest, uid):
        out = []
        for name, box in self.state.boxes.items():
            flags = ["\\HasNoChildren"]
            if box.special:
                flags.append(box.special)
            out.append('* LIST (%s) "/" %s\r\n' % (" ".join(flags), quote(name)))
        self.send("".join(out) + "%s OK list\r\n" % tag)

    def cmd_status(self, tag, rest, uid):
        t = tokenize(rest)
        box = self.state.boxes[t[0]]
        unseen = sum(1 for m in box.messages if "\\Seen" not in m.flags)
        self.send("* STATUS %s (MESSAGES %d UNSEEN %d UIDNEXT %d)\r\n%s OK status\r\n" % (quote(t[0]), len(box.messages), unseen, box.uidnext, tag))

    def cmd_select(self, tag, rest, uid):
        t = tokenize(rest)
        name = t[0]
        if name not in self.state.boxes:
            self.send("%s NO no such mailbox\r\n" % tag)
            return
        with LOCK:
            box = self.state.boxes[name]
            self.box = box
            out = ["* FLAGS (\\Answered \\Flagged \\Deleted \\Seen \\Draft)\r\n", "* %d EXISTS\r\n" % len(box.messages),
                   "* OK [UIDVALIDITY %d] ok\r\n" % box.uidvalidity, "* OK [UIDNEXT %d] ok\r\n" % box.uidnext]
            if "CONDSTORE" in self.enabled or (len(t) > 1 and "CONDSTORE" in t[1].upper()):
                self.enabled.add("CONDSTORE")
                out.append("* OK [HIGHESTMODSEQ %d] ok\r\n" % box.modseq)
            if len(t) > 1 and "QRESYNC" in t[1].upper() and "QRESYNC" in self.enabled:
                m = re.search(r"QRESYNC \((\d+) (\d+)", t[1].upper())
                if m and int(m.group(1)) == box.uidvalidity:
                    since = int(m.group(2))
                    gone = [u for u, ms in box.expunged if ms > since]
                    if gone:
                        out.append("* VANISHED (EARLIER) %s\r\n" % ",".join(str(u) for u in gone))
                    for i, msg in enumerate(box.messages):
                        if msg.modseq > since:
                            out.append("* %d FETCH (UID %d FLAGS (%s) MODSEQ (%d))\r\n" % (i + 1, msg.uid, " ".join(sorted(msg.flags)), msg.modseq))
        self.send("".join(out) + "%s OK [READ-WRITE] selected\r\n" % tag)

    cmd_examine = cmd_select

    def cmd_create(self, tag, rest, uid):
        name = tokenize(rest)[0]
        with LOCK:
            self.state.boxes.setdefault(name, Mailbox(name))
        self.send("%s OK created\r\n" % tag)

    def fetch_items(self, spec):
        spec = spec.strip()
        if spec.startswith("("):
            spec = spec[1:-1]
        return tokenize(spec)

    def cmd_fetch(self, tag, rest, uid):
        box = self.box
        m = re.match(r"(\S+) (\(.*?\)|\S+)(?: \((.*)\))?$", rest)
        seqset, spec, mods = m.group(1), m.group(2), m.group(3) or ""
        items = self.fetch_items(spec)
        changedsince = None
        vanished = False
        mm = re.search(r"CHANGEDSINCE (\d+)", mods.upper())
        if mm:
            changedsince = int(mm.group(1))
        if "VANISHED" in mods.upper():
            vanished = True
        out = []
        with LOCK:
            msgs = box.messages
            if uid:
                maxuid = msgs[-1].uid if msgs else 0
                wanted = parse_set(seqset, max(maxuid, 1))
                if vanished and changedsince is not None:
                    gone = [u for u, ms in box.expunged if ms > changedsince and u in wanted]
                    if gone:
                        out.append("* VANISHED (EARLIER) %s\r\n" % ",".join(str(u) for u in gone))
                selected = [(i, x) for i, x in enumerate(msgs) if x.uid in wanted]
            else:
                wanted = parse_set(seqset, max(len(msgs), 1))
                selected = [(i, x) for i, x in enumerate(msgs) if (i + 1) in wanted]
            for i, msg in selected:
                if changedsince is not None and msg.modseq <= changedsince:
                    continue
                out.append(self.fetch_one(i + 1, msg, items, uid or changedsince is not None))
            if self.state.dovecot_flags and "BODYSTRUCTURE" in [x.upper() for x in items]:
                # jako Dovecot: po BODYSTRUCTURE nevyzadana zmena priznaku ($HasNoAttachment) s UID
                for i, msg in selected:
                    out.append("* %d FETCH (UID %d MODSEQ (%d) FLAGS (%s))\r\n" % (i + 1, msg.uid, msg.modseq, " ".join(sorted(msg.flags | {"$HasNoAttachment"}))))
        self.send("".join(out) + "%s OK fetch\r\n" % tag)

    def fetch_one(self, seq, msg, items, add_uid):
        parts = []
        names = [x.upper() for x in items]
        if add_uid and "UID" not in names:
            parts.append("UID %d" % msg.uid)
        for item in items:
            u = item.upper()
            if u == "UID":
                parts.append("UID %d" % msg.uid)
            elif u == "FLAGS":
                parts.append("FLAGS (%s)" % " ".join(sorted(msg.flags)))
            elif u == "INTERNALDATE":
                parts.append('INTERNALDATE "%s"' % time.strftime("%d-%b-%Y %H:%M:%S +0000", time.gmtime(msg.internal)))
            elif u == "RFC822.SIZE":
                parts.append("RFC822.SIZE %d" % len(msg.raw))
            elif u == "ENVELOPE":
                parts.append("ENVELOPE " + envelope(msg))
            elif u in ("BODYSTRUCTURE", "BODY"):
                parts.append("BODYSTRUCTURE " + bodystructure(msg.msg))
            elif u == "MODSEQ":
                parts.append("MODSEQ (%d)" % msg.modseq)
            elif u.startswith("BODY"):
                mm = re.match(r"BODY(?:\.PEEK)?\[([^\]]*)\](?:<(\d+)\.(\d+)>)?", item, re.I)
                section = mm.group(1)
                data = fetch_section(msg, section)
                origin = ""
                if mm.group(2) is not None:
                    o, n = int(mm.group(2)), int(mm.group(3))
                    data = data[o:o + n]
                    origin = "<%d>" % o
                if not u.startswith("BODY.PEEK"):
                    msg.flags.add("\\Seen")
                parts.append("BODY[%s]%s {%d}\r\n" % (section, origin, len(data)) + data.decode("utf-8", "surrogateescape"))
        return "* %d FETCH (%s)\r\n" % (seq, " ".join(parts))

    def cmd_search(self, tag, rest, uid):
        box = self.box
        with LOCK:
            msgs = box.messages
            if rest.upper().startswith("UID "):
                maxuid = msgs[-1].uid if msgs else 0
                wanted = parse_set(rest.split(" ", 1)[1], max(maxuid, 1))
                res = [m.uid for m in msgs if m.uid in wanted]
            else:
                res = [m.uid for m in msgs] if uid else list(range(1, len(msgs) + 1))
        self.send("* SEARCH %s\r\n%s OK search\r\n" % (" ".join(str(x) for x in res), tag))

    def cmd_store(self, tag, rest, uid):
        m = re.match(r"(\S+) ([+-]?)FLAGS(\.SILENT)? \((.*)\)", rest, re.I)
        seqset, sign, silent, flags = m.group(1), m.group(2), m.group(3), m.group(4).split()
        box = self.box
        out = []
        with LOCK:
            maxuid = box.messages[-1].uid if box.messages else 1
            wanted = parse_set(seqset, maxuid)
            for i, msg in enumerate(box.messages):
                if msg.uid in wanted:
                    if sign == "+":
                        msg.flags.update(flags)
                    elif sign == "-":
                        msg.flags.difference_update(flags)
                    else:
                        msg.flags = set(flags)
                    box.modseq += 1
                    msg.modseq = box.modseq
                    if not silent:
                        out.append("* %d FETCH (UID %d FLAGS (%s))\r\n" % (i + 1, msg.uid, " ".join(sorted(msg.flags))))
            self.broadcast_flags(box, wanted)
        self.send("".join(out) + "%s OK store\r\n" % tag)

    def broadcast_flags(self, box, uids):
        for s in self.state.sessions:
            if s is not self and s.box is box:
                for i, msg in enumerate(box.messages):
                    if msg.uid in uids:
                        s.notify("* %d FETCH (FLAGS (%s))\r\n" % (i + 1, " ".join(sorted(msg.flags))))

    def remove_uids(self, box, uids):
        notes = []
        for msg in list(box.messages):
            if msg.uid in uids:
                seq = box.messages.index(msg) + 1
                box.messages.remove(msg)
                box.modseq += 1
                box.expunged.append((msg.uid, box.modseq))
                notes.append((seq, msg.uid))
        for s in self.state.sessions:
            if s.box is box:
                for seq, u in notes:
                    if "QRESYNC" in s.enabled:
                        s.notify("* VANISHED %d\r\n" % u)
                    else:
                        s.notify("* %d EXPUNGE\r\n" % seq)
        return notes

    def copy_to(self, uids, target):
        dest = self.state.boxes[target]
        for msg in self.box.messages:
            if msg.uid in uids:
                dest.add(msg.raw, msg.flags - {"\\Deleted"}, msg.internal)

    def cmd_copy(self, tag, rest, uid):
        t = tokenize(rest)
        with LOCK:
            wanted = parse_set(t[0], self.box.messages[-1].uid if self.box.messages else 1)
            self.copy_to(wanted, t[1])
        self.send("%s OK copy\r\n" % tag)

    def cmd_move(self, tag, rest, uid):
        t = tokenize(rest)
        with LOCK:
            wanted = parse_set(t[0], self.box.messages[-1].uid if self.box.messages else 1)
            self.copy_to(wanted, t[1])
            self.remove_uids(self.box, wanted)
        self.flush_pending()
        self.send("%s OK move\r\n" % tag)

    def cmd_expunge(self, tag, rest, uid):
        with LOCK:
            dele = {m.uid for m in self.box.messages if "\\Deleted" in m.flags}
            if uid and rest:
                dele &= parse_set(rest.strip(), self.box.messages[-1].uid if self.box.messages else 1)
            self.remove_uids(self.box, dele)
        self.flush_pending()
        self.send("%s OK expunge\r\n" % tag)

    def flush_pending(self):
        with LOCK:
            items, self.pending = self.pending, []
        if items:
            self.send("".join(items))

    def cmd_idle(self, tag, rest, uid):
        self.send("+ idling\r\n")
        while True:
            self.flush_pending()
            line = self.readline(timeout=0.1)
            if line is None:
                continue
            self.log(line)
            if line.strip().upper() == "DONE":
                break
        self.flush_pending()
        self.send("%s OK IDLE terminated\r\n" % tag)

    def cmd_logout(self, tag, rest, uid):
        self.send("* BYE bye\r\n%s OK logout\r\n" % tag)
        self.alive = False


def control(state, conn):
    f = conn.makefile("rwb")
    for raw in f:
        line = raw.decode().strip()
        parts = line.split(" ")
        out = {"ok": True}
        try:
            with LOCK:
                if parts[0] == "deliver":
                    box = state.boxes[parts[1]]
                    data = open(parts[2], "rb").read()
                    msg = box.add(data, parts[3:])
                    for s in state.sessions:
                        if s.box is box:
                            s.notify("* %d EXISTS\r\n" % len(box.messages))
                    out["uid"] = msg.uid
                elif parts[0] == "expunge":
                    box = state.boxes[parts[1]]
                    s0 = Session(state, None, True, None)
                    s0.remove_uids(box, {int(parts[2])})
                elif parts[0] == "flags":
                    box = state.boxes[parts[1]]
                    u = int(parts[2])
                    for i, msg in enumerate(box.messages):
                        if msg.uid == u:
                            msg.flags = set(parts[3:])
                            box.modseq += 1
                            msg.modseq = box.modseq
                            for s in state.sessions:
                                if s.box is box:
                                    s.notify("* %d FETCH (FLAGS (%s))\r\n" % (i + 1, " ".join(sorted(msg.flags))))
                elif parts[0] == "password":
                    for u in state.users:
                        state.users[u] = parts[1]
                elif parts[0] == "token":
                    state.tokens[parts[1]] = parts[2].lower()
                elif parts[0] == "revoke":
                    state.tokens.clear()
                elif parts[0] == "dump":
                    out["boxes"] = {n: [{"uid": m.uid, "flags": sorted(m.flags)} for m in b.messages] for n, b in state.boxes.items()}
                elif parts[0] == "log":
                    out["log"] = list(state.log)
                elif parts[0] == "sessions":
                    out["sessions"] = len(state.sessions)
        except Exception as e:  # noqa: BLE001
            out = {"ok": False, "error": str(e)}
        f.write((json.dumps(out) + "\n").encode())
        f.flush()


def serve(listener, state, implicit, ctx):
    while True:
        sock, _ = listener.accept()
        s = Session(state, sock, implicit, ctx)
        with LOCK:
            state.sessions.append(s)
        s.start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--port", type=int, default=0, help="implicitni TLS (993)")
    ap.add_argument("--starttls-port", type=int, default=0)
    ap.add_argument("--control", type=int, default=0)
    ap.add_argument("--user", default="tester@example.test")
    ap.add_argument("--password", default="heslo-123")
    ap.add_argument("--qresync", action="store_true")
    ap.add_argument("--seed", default="", help="adresar s .eml zpravami do INBOX")
    ap.add_argument("--ready", default="", help="soubor s porty po startu")
    ap.add_argument("--oauth", default="", help="mechanismy tokenu, napr. OAUTHBEARER,XOAUTH2")
    ap.add_argument("--no-sasl-ir", action="store_true")
    ap.add_argument("--dovecot-flags", action="store_true", help="nevyzadane FETCH s priznaky po BODYSTRUCTURE")
    a = ap.parse_args()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(a.cert, a.key)
    state = State({a.user: a.password}, a.qresync, [m for m in a.oauth.upper().split(",") if m], not a.no_sasl_ir)
    state.dovecot_flags = a.dovecot_flags
    if a.seed:
        for i, name in enumerate(sorted(os.listdir(a.seed))):
            if name.endswith(".eml"):
                flags = ["\\Seen"] if "seen" in name else []
                state.boxes["INBOX"].add(open(os.path.join(a.seed, name), "rb").read(), flags, time.time() - 86400 * 3 + i * 60)
    ports = {}
    for kind, port, implicit in (("tls", a.port, True), ("starttls", a.starttls_port, False)):
        ls = socket.socket()
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind(("127.0.0.1", port))
        ls.listen(16)
        ports[kind] = ls.getsockname()[1]
        threading.Thread(target=serve, args=(ls, state, implicit, ctx), daemon=True).start()
    cs = socket.socket()
    cs.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    cs.bind(("127.0.0.1", a.control))
    cs.listen(4)
    ports["control"] = cs.getsockname()[1]
    if a.ready:
        with open(a.ready + ".tmp", "w") as f:
            json.dump(ports, f)
        os.rename(a.ready + ".tmp", a.ready)
    while True:
        c, _ = cs.accept()
        threading.Thread(target=control, args=(state, c), daemon=True).start()


if __name__ == "__main__":
    main()
