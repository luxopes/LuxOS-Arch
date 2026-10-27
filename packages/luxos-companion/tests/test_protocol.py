#!/usr/bin/env python3
"""LuxOS Companion - ramce a stavovy automat spojeni (PROTOCOL.md v1) pres socketpair.

    python3 -m unittest packages/luxos-companion/tests/test_protocol.py -v
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402
from helpers import Clock, connect, make_service, pump  # noqa: E402

from luxos_companion import session, wire  # noqa: E402


def frame(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def hello(mid="h1", protocol=1):
    return {"v": 1, "type": "hello", "id": mid, "client": "LuxOS Companion Android", "protocol": protocol}


class TestDecoder(unittest.TestCase):
    def feed(self, *chunks):
        d = wire.Decoder()
        out = []
        for c in chunks:
            out.extend(d.feed(c))
        return out, d

    def test_split_reads_byte_by_byte(self):
        data = frame({"v": 1, "type": "ping", "id": "p1"}) + frame({"v": 1, "type": "x", "id": "č2", "t": "žluť"})
        out, d = self.feed(*[data[i:i + 1] for i in range(len(data))])
        self.assertEqual([m["id"] for m in out], ["p1", "č2"])
        self.assertEqual(out[1]["t"], "žluť")
        d.eof()  # nic nezustalo

    def test_many_frames_in_one_read_and_crlf(self):
        data = frame({"v": 1, "type": "a", "id": "1"})[:-1] + b"\r\n" + frame({"v": 1, "type": "b", "id": "2"})
        out, _d = self.feed(data)
        self.assertEqual([m["type"] for m in out], ["a", "b"])

    def test_escaped_newline_inside_string(self):
        out, _d = self.feed(frame({"v": 1, "type": "a", "id": "1", "text": "line1\nline2"}))
        self.assertEqual(out[0]["text"], "line1\nline2")

    def test_size_limit_includes_lf(self):
        base = {"v": 1, "type": "a", "id": "1", "pad": ""}
        overhead = len(frame(base))
        ok = dict(base, pad="x" * (wire.MAX_FRAME - overhead))
        self.assertEqual(len(frame(ok)), wire.MAX_FRAME)
        out, _d = self.feed(frame(ok))
        self.assertEqual(len(out), 1)
        too = dict(base, pad="x" * (wire.MAX_FRAME - overhead + 1))
        with self.assertRaises(wire.ProtocolError) as cm:
            self.feed(frame(too))
        self.assertEqual(cm.exception.code, "frame_too_long")

    def test_oversize_detected_before_lf(self):
        d = wire.Decoder()
        list(d.feed(b"{" + b"a" * (wire.MAX_FRAME - 2)))      # 65535 bajtu bez LF je jeste mozne
        with self.assertRaises(wire.ProtocolError):
            list(d.feed(b"b"))

    def test_invalid_utf8(self):
        for bad in (b'{"v":1,"type":"a","id":"\xff"}\n', b'{"v":1,"type":"a","id":"\xc0\x80"}\n',
                    b'{"v":1,"type":"a","id":"\xed\xa0\x80"}\n'):
            with self.assertRaises(wire.ProtocolError) as cm:
                self.feed(bad)
            self.assertEqual(cm.exception.code, "invalid_utf8")

    def test_multibyte_split_across_reads(self):
        data = frame({"v": 1, "type": "a", "id": "1", "t": "😀ř"})
        cut = data.index("😀".encode()) + 2
        out, _d = self.feed(data[:cut], data[cut:])
        self.assertEqual(out[0]["t"], "😀ř")

    def test_eof_mid_frame(self):
        d = wire.Decoder()
        list(d.feed(b'{"v":1,"type":"ping"'))
        with self.assertRaises(wire.ProtocolError) as cm:
            d.eof()
        self.assertEqual(cm.exception.code, "incomplete_frame")

    def test_schema(self):
        cases = {
            b'{"v":2,"type":"a","id":"1"}\n': "unsupported_version",
            b'{"v":true,"type":"a","id":"1"}\n': "invalid_message",
            b'{"type":"a","id":"1"}\n': "invalid_message",
            b'{"v":1,"id":"1"}\n': "invalid_message",
            b'{"v":1,"type":"a"}\n': "invalid_message",
            b'{"v":1,"type":"a","id":""}\n': "invalid_message",
            b'[1,2]\n': "invalid_json",
            b'{"v":1,"type":"a","id":"1","x":NaN}\n': "invalid_json",
            b'{"v":1,\n': "invalid_json",
            b'\n': "invalid_json",
        }
        for data, code in cases.items():
            with self.assertRaises(wire.ProtocolError, msg=data) as cm:
                self.feed(data)
            self.assertEqual(cm.exception.code, code, data)

    def test_frames_before_error_are_delivered(self):
        d = wire.Decoder()
        got = []
        with self.assertRaises(wire.ProtocolError):
            for m in d.feed(frame({"v": 1, "type": "a", "id": "1"}) + b"\xff\n"):
                got.append(m)
        self.assertEqual(len(got), 1)

    def test_encode(self):
        data = wire.encode(wire.message("pong", reply_to="p1"))
        self.assertTrue(data.endswith(b"\n"))
        self.assertEqual(data.count(b"\n"), 1)
        m = json.loads(data)
        self.assertEqual((m["v"], m["type"], m["reply_to"]), (1, "pong", "p1"))
        self.assertEqual(len(m["id"]), 36)
        self.assertNotIn(b": ", data)
        with self.assertRaises(ValueError):
            wire.encode({"t": "x" * wire.MAX_FRAME})
        self.assertEqual(json.loads(wire.encode({"t": "a\nb"}))["t"], "a\nb")


class TestSession(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.svc = make_service(self.clock)

    def handshake(self, peer=None):
        s, phone = connect(self.svc, peer)
        phone.send_raw(frame(hello()))
        msgs = phone.wait(1)
        self.assertEqual(len(msgs), 1, msgs)
        self.assertEqual(msgs[0]["type"], "hello.ok")
        self.assertEqual(msgs[0]["reply_to"], "h1")
        self.assertEqual(msgs[0]["protocol"], 1)
        self.assertEqual(msgs[0]["v"], 1)
        self.assertEqual(s.state, "open")
        return s, phone

    def test_handshake_split_reads(self):
        s, phone = connect(self.svc)
        data = frame(hello())
        for i in range(len(data)):
            phone.send_raw(data[i:i + 1])
            pump(timeout=0.01)
        msgs = phone.wait(1)
        self.assertEqual(msgs[0]["type"], "hello.ok")

    def test_crlf_frames(self):
        s, phone = connect(self.svc)
        phone.send_raw(frame(hello())[:-1] + b"\r\n" + frame({"v": 1, "type": "ping", "id": "p1"})[:-1] + b"\r\n")
        msgs = phone.wait(2)
        self.assertEqual([m["type"] for m in msgs], ["hello.ok", "pong"])

    def test_message_before_hello_closes(self):
        s, phone = connect(self.svc)
        phone.send("ping")
        self.assertTrue(phone.wait_closed())
        self.assertEqual(s.close_reason, "handshake_expected")
        self.assertEqual(phone.messages(), [])

    def test_unsupported_protocol_in_hello(self):
        s, phone = connect(self.svc)
        phone.send_raw(frame(hello(protocol=2)))
        msgs = phone.wait(1)
        self.assertEqual(msgs[0]["type"], "error")
        self.assertEqual(msgs[0]["code"], "unsupported_protocol")
        self.assertTrue(phone.wait_closed())

    def test_unsupported_frame_version_closes(self):
        s, phone = connect(self.svc)
        phone.send_raw(b'{"v":2,"type":"hello","id":"h1","protocol":2}\n')
        self.assertTrue(phone.wait_closed())
        self.assertEqual(s.close_reason, "unsupported_version")

    def test_handshake_timeout(self):
        s, phone = connect(self.svc)
        self.clock.advance(19.9)
        self.svc.tick()
        self.assertEqual(s.state, "handshake")
        self.clock.advance(0.2)
        self.svc.tick()
        self.assertTrue(phone.wait_closed())
        self.assertEqual(s.close_reason, "handshake_timeout")

    def test_ping_pong_and_unknown_types(self):
        s, phone = self.handshake()
        phone.send("future.feature", "f1", data={"x": 1})
        phone.send("ping", "p1")
        msgs = phone.wait(1)
        self.assertEqual(len(msgs), 1)
        self.assertEqual((msgs[0]["type"], msgs[0]["reply_to"]), ("pong", "p1"))
        self.assertEqual(s.state, "open")

    def test_idle_timeout_with_injected_clock(self):
        s, phone = self.handshake()
        self.clock.advance(30)
        phone.send("ping", "p1")
        phone.wait(1)
        self.clock.advance(44.9)
        self.svc.tick()
        self.assertEqual(s.state, "open")
        self.clock.advance(0.2)
        self.svc.tick()
        self.assertTrue(phone.wait_closed())
        self.assertEqual(s.close_reason, "idle_timeout")

    def test_eof_mid_frame(self):
        s, phone = self.handshake()
        phone.send_raw(b'{"v":1,"type":"pi')
        pump(timeout=0.1)
        phone.sock.shutdown(1)
        self.assertTrue(pump(lambda: s.state == "closed"))
        self.assertEqual(s.close_reason, "incomplete_frame")

    def test_clean_eof(self):
        s, phone = self.handshake()
        phone.sock.shutdown(1)
        self.assertTrue(pump(lambda: s.state == "closed"))
        self.assertEqual(s.close_reason, "eof")
        self.assertNotIn(s.key, self.svc.sessions)

    def test_oversize_closes(self):
        s, phone = self.handshake()
        phone.send_raw(b'{"v":1,"type":"x","id":"1","p":"' + b"a" * 70000)
        self.assertTrue(phone.wait_closed())
        self.assertEqual(s.close_reason, "frame_too_long")

    def test_invalid_utf8_closes(self):
        s, phone = self.handshake()
        phone.send_raw(b'{"v":1,"type":"ping","id":"\xfe"}\n')
        self.assertTrue(phone.wait_closed())
        self.assertEqual(s.close_reason, "invalid_utf8")

    def test_new_connection_replaces_old(self):
        s1, p1 = self.handshake()
        s2, p2 = self.handshake()
        self.assertEqual(s1.state, "closed")
        self.assertEqual(s1.close_reason, "replaced")
        self.assertTrue(p1.wait_closed())
        self.assertEqual(s2.state, "open")


class TestApproval(unittest.TestCase):
    STRANGER = {"address": "aa:bb:cc:dd:ee:99", "name": "Cizí\x07 telefon"}

    def setUp(self):
        self.clock = Clock()
        self.svc = make_service(self.clock)
        self.n = self.svc.notifier

    def ask(self):
        s, phone = connect(self.svc, self.STRANGER)
        phone.send_raw(frame(hello()))
        pump(lambda: self.n.sent, 2)
        self.assertEqual(s.state, "approving")
        self.assertEqual(phone.messages(), [])      # do hello.ok nic jineho
        note = self.n.sent[-1]
        self.assertIn("Cizí telefon", note["summary"])
        self.assertNotIn("\x07", note["summary"])
        self.assertEqual(note["actions"], ["deny", "Deny", "allow", "Allow"])
        self.assertEqual(self.svc.status()["pending"][0]["address"], "AA:BB:CC:DD:EE:99")
        return s, phone, note

    def test_allow(self):
        s, phone, note = self.ask()
        self.n.press(note["id"], "allow")
        msgs = phone.wait(1)
        self.assertEqual(msgs[0]["type"], "hello.ok")
        self.assertTrue(self.svc.settings.is_approved("AA:BB:CC:DD:EE:99"))
        self.assertEqual(self.svc.status()["pending"], [])
        # dalsi spojeni uz se nepta
        s2, p2 = connect(self.svc, self.STRANGER)
        p2.send_raw(frame(hello("h2")))
        self.assertEqual(p2.wait(1)[0]["type"], "hello.ok")
        self.assertEqual(len(self.n.sent), 1)

    def test_deny(self):
        s, phone, note = self.ask()
        self.n.press(note["id"], "deny")
        msgs = phone.wait(1)
        self.assertEqual((msgs[0]["type"], msgs[0]["code"], msgs[0]["reply_to"]), ("error", "not_approved", "h1"))
        self.assertTrue(phone.wait_closed())
        self.assertFalse(self.svc.settings.is_approved("AA:BB:CC:DD:EE:99"))

    def test_dismissed_notification_denies(self):
        s, phone, note = self.ask()
        self.n.press(note["id"], "closed")
        self.assertEqual(phone.wait(1)[0]["code"], "not_approved")

    def test_message_while_approving_closes(self):
        s, phone, note = self.ask()
        phone.send("ping")
        self.assertTrue(phone.wait_closed())
        self.assertEqual(s.close_reason, "handshake_expected")

    def test_late_allow_after_timeout_is_remembered(self):
        s, phone, note = self.ask()
        self.clock.advance(20)
        self.svc.tick()
        self.assertTrue(phone.wait_closed())
        self.assertEqual(s.close_reason, "handshake_timeout")
        self.assertEqual(len(self.svc.status()["pending"]), 1)    # dotaz zustava
        self.svc.answer("AA:BB:CC:DD:EE:99", True)                  # z okna Telefon
        self.assertTrue(self.svc.settings.is_approved("AA:BB:CC:DD:EE:99"))
        self.assertIn("allowed", self.n.sent[-1]["summary"])
        self.assertIn(note["id"], self.n.closed)

    def test_revoke_closes_open_connection(self):
        s, phone, note = self.ask()
        self.n.press(note["id"], "allow")
        phone.wait(1)
        from luxos_companion import store
        store.Settings(self.svc.settings.path).remove("AA:BB:CC:DD:EE:99")
        self.svc.reload_settings()
        self.assertTrue(phone.wait_closed())
        self.assertEqual(s.close_reason, "revoked")


class TestOutput(unittest.TestCase):
    def test_send_after_close_is_noop(self):
        svc = make_service()
        s, phone = connect(svc)
        s.close("x")
        self.assertFalse(s.send({"type": "pong", "reply_to": "1"}))

    def test_constants(self):
        self.assertEqual(session.HANDSHAKE_S, 20.0)
        self.assertEqual(session.IDLE_S, 45.0)
        self.assertEqual(wire.MAX_FRAME, 65536)


def tearDownModule():
    import shutil
    shutil.rmtree(helpers.TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
