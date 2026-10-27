#!/usr/bin/env python3
"""LuxDrop - jednotkove testy: ramce, SAS (testovaci vektory), cesty, kontrola SHA-256, identita.

Spusteni: python3 -m unittest -v tests/test_unit.py  (z adresare packages/luxdrop)
"""
import hashlib
import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("LUXDROP_LIB", os.path.join(HERE, "..", "files", "lib")))

from luxdrop import identity, pathsafe, proto, store, transfer  # noqa: E402

def rd(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def wr(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


FC = bytes(range(0, 32))
FS = bytes(range(32, 64))
NC = bytes(range(64, 96))
NS = bytes(range(96, 128))


class FreePort:
    @staticmethod
    def get():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


class FakeSock:
    def __init__(self, data=b""):
        self.buf = io.BytesIO(data)
        self.out = bytearray()

    def recv(self, n):
        return self.buf.read(min(n, 7))  # schvalne po malych kusech

    def sendall(self, b):
        self.out += b


class TestFraming(unittest.TestCase):
    def test_json_vector(self):
        self.assertEqual(proto.encode_json({"type": "end"}).hex(), "4a0000000e7b2274797065223a22656e64227d")

    def test_data_vector(self):
        self.assertEqual(proto.encode_data(b"abc").hex(), "4400000003616263")

    def test_roundtrip(self):
        msgs = [{"type": "hello", "name": "Počítač 💻", "n": 5}, {"type": "end"}]
        raw = b"".join(proto.encode_json(m) for m in msgs) + proto.encode_data(b"x" * 1000)
        s = FakeSock(raw)
        self.assertEqual(proto.read_frame(s), (proto.FRAME_JSON, msgs[0]))
        self.assertEqual(proto.read_frame(s), (proto.FRAME_JSON, msgs[1]))
        self.assertEqual(proto.read_frame(s), (proto.FRAME_DATA, b"x" * 1000))
        with self.assertRaises(ConnectionError):
            proto.read_frame(s)

    def test_truncated(self):
        raw = proto.encode_json({"type": "end"})[:-1]
        with self.assertRaises(ConnectionError):
            proto.read_frame(FakeSock(raw))

    def test_unknown_type(self):
        with self.assertRaises(proto.ProtocolError) as cm:
            proto.read_frame(FakeSock(b"X\x00\x00\x00\x00"))
        self.assertEqual(cm.exception.code, proto.E_PROTOCOL)

    def test_oversized_frames_rejected_before_reading(self):
        for hdr in (b"D" + (proto.MAX_DATA + 1).to_bytes(4, "big"), b"J" + (proto.MAX_JSON + 1).to_bytes(4, "big")):
            with self.assertRaises(proto.ProtocolError):
                proto.read_frame(FakeSock(hdr))
        with self.assertRaises(proto.ProtocolError):
            proto.encode_data(b"\0" * (proto.MAX_DATA + 1))

    def test_bad_json(self):
        for payload in (b"[1,2]", b"{\"a\":1}", b"\xff\xfe", b"{bad", b"{\"type\":5}"):
            with self.assertRaises(proto.ProtocolError):
                proto.read_frame(FakeSock(b"J" + len(payload).to_bytes(4, "big") + payload))

    def test_error_message_raises(self):
        s = FakeSock(proto.encode_json({"type": "error", "code": "not_trusted", "message": "no"}))
        with self.assertRaises(proto.ProtocolError) as cm:
            proto.Channel(s).recv_msg("accept")
        self.assertEqual(cm.exception.code, "not_trusted")

    def test_unexpected_message(self):
        s = FakeSock(proto.encode_json({"type": "offer"}))
        with self.assertRaises(proto.ProtocolError):
            proto.Channel(s).recv_msg("hello")


class TestSas(unittest.TestCase):
    def test_vector_1(self):
        # Nezavisle: SHA-256("LUXDROP-SAS-v1" || bajty 0..127)
        h = hashlib.sha256(b"LUXDROP-SAS-v1" + bytes(range(128))).hexdigest()
        self.assertEqual(h, "b4ce752405cc515c9fc75e547d6fc0990047150aa573f1a570e26efdf90399b9")
        self.assertEqual(int(h[:16], 16) % 1_000_000, 972316)
        self.assertEqual(proto.sas_code(FC, FS, NC, NS), "972316")

    def test_vector_2(self):
        self.assertEqual(proto.sas_code(b"\0" * 32, b"\xff" * 32, b"\x11" * 32, b"\x22" * 32), "757504")

    def test_order_matters(self):
        self.assertNotEqual(proto.sas_code(FC, FS, NC, NS), proto.sas_code(FS, FC, NC, NS))
        self.assertNotEqual(proto.sas_code(FC, FS, NC, NS), proto.sas_code(FC, FS, NS, NC))

    def test_format(self):
        self.assertEqual(proto.format_sas("012345"), "012 345")
        self.assertEqual(proto.sas_code(FC, FS, NC, b"\x60" + NS[1:]).__len__(), 6)

    def test_leading_zeros(self):
        # Hledame vstup, kde kod zacina nulou - musi mit 6 znaku
        for i in range(5000):
            c = proto.sas_code(FC, FS, NC, i.to_bytes(32, "big"))
            self.assertEqual(len(c), 6)
            if c.startswith("0"):
                break
        else:
            self.fail("no code with a leading zero found")

    def test_commit(self):
        self.assertEqual(proto.commit(NC).hex(), "ca2a4fe727faaecf16ecd130a86e0885c5540c05375340445071c0657555fd42")
        self.assertTrue(proto.check_commit(proto.commit(NC), NC))
        self.assertFalse(proto.check_commit(proto.commit(NC), NS))

    def test_auth_message_vector(self):
        m = proto.auth_message(FS, FC, NS, NC)
        self.assertEqual(len(m), 15 + 4 * 32)
        self.assertEqual(m[:15], b"LUXDROP-AUTH-v1")
        self.assertEqual(hashlib.sha256(m).hexdigest(),
                         "fd7b03b3fe7cd8c0b3bfe91aa59b45d417def06238c32519240127c3959d2987")

    def test_bad_lengths(self):
        with self.assertRaises(ValueError):
            proto.sas_code(FC[:31], FS, NC, NS)
        with self.assertRaises(ValueError):
            proto.auth_message(FS, FC, NS, NC + b"x")


class TestIdentity(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_create_and_permissions(self):
        d = os.path.join(self.dir, "luxdrop")
        i1 = identity.Identity.load_or_create(d)
        self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)
        for f in (identity.KEY_FILE, identity.CERT_FILE):
            self.assertEqual(os.stat(os.path.join(d, f)).st_mode & 0o777, 0o600)
        i2 = identity.Identity.load_or_create(d)
        self.assertEqual(i1.fp, i2.fp)
        self.assertEqual(i1.id, i1.fp[:8].hex())

    def test_fingerprint_matches_openssl(self):
        if not shutil.which("openssl"):
            self.skipTest("openssl not installed")
        i = identity.Identity.load_or_create(os.path.join(self.dir, "x"))
        pub = subprocess.run(["openssl", "x509", "-in", i.cert_path, "-pubkey", "-noout"],
                             capture_output=True, check=True).stdout
        der = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "DER"], input=pub,
                             capture_output=True, check=True).stdout
        self.assertEqual(hashlib.sha256(der).digest(), i.fp)
        fp2, _k = identity.cert_fingerprint(i.cert_der)
        self.assertEqual(fp2, i.fp)

    def test_signature(self):
        i = identity.Identity.load_or_create(os.path.join(self.dir, "a"))
        j = identity.Identity.load_or_create(os.path.join(self.dir, "b"))
        msg = proto.auth_message(FS, i.fp, NS, NC)
        sig = i.sign(msg)
        _fp, pub_i = identity.cert_fingerprint(i.cert_der)
        _fp, pub_j = identity.cert_fingerprint(j.cert_der)
        self.assertTrue(identity.verify_signature(pub_i, sig, msg))
        self.assertFalse(identity.verify_signature(pub_i, sig, msg[:-1] + b"\0"))
        self.assertFalse(identity.verify_signature(pub_j, sig, msg))
        self.assertFalse(identity.verify_signature(pub_i, b"garbage", msg))

    def test_invalid_cert(self):
        with self.assertRaises(proto.ProtocolError):
            identity.cert_fingerprint(b"not a certificate")


class TestTlsSuites(unittest.TestCase):
    """Android aplikace (LuxOS Companion) prijme jen TLS_AES_256_GCM_SHA384 (PROTOCOL.md 4.1)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ident = identity.Identity.load_or_create(os.path.join(self.dir, "id"))

    def tearDown(self):
        shutil.rmtree(self.dir)

    def handshake(self, cctx):
        import ssl
        import threading
        sctx = transfer.server_context(self.ident)
        srv = socket.create_server(("127.0.0.1", 0))
        got = {}

        def serve():
            conn, _a = srv.accept()
            try:
                with sctx.wrap_socket(conn, server_side=True) as tls:
                    got["server"] = (tls.version(), tls.cipher()[0])
                    tls.recv(1)
            except (OSError, ssl.SSLError) as e:
                got["error"] = e
        th = threading.Thread(target=serve)
        th.start()
        with socket.create_connection(srv.getsockname(), timeout=10) as raw:
            with cctx.wrap_socket(raw, server_hostname=None) as tls:
                client = (tls.version(), tls.cipher()[0], tls.selected_alpn_protocol())
        th.join(10)
        srv.close()
        return client, got.get("server")

    def test_server_prefers_aes256(self):
        import ssl
        ctx = transfer.server_context(self.ident)
        self.assertTrue(ctx.options & ssl.OP_CIPHER_SERVER_PREFERENCE)
        tls13 = [c["name"] for c in ctx.get_ciphers() if c["protocol"] == "TLSv1.3"]
        self.assertEqual(tls13[0], "TLS_AES_256_GCM_SHA384")

    def test_luxos_to_luxos(self):
        client, server = self.handshake(transfer.client_context())
        self.assertEqual(client, ("TLSv1.3", "TLS_AES_256_GCM_SHA384", proto.ALPN))
        self.assertEqual(server, ("TLSv1.3", "TLS_AES_256_GCM_SHA384"))

    def test_receiver_closes_after_reject(self):
        # Prijimac po odmitnuti zavre TLS spojeni, i kdyz UI drzi Transfer (Java/Android klient
        # pri close() ceka na konec spojeni od protistrany).
        import base64
        kept = []

        class H(transfer.Handler):
            def ask(self, req):
                return False, False

            def finished(self, t):
                kept.append(t)
        s = store.Settings(os.path.join(self.dir, "cfg"))
        s.set("download_dir", os.path.join(self.dir, "dl"))
        rx = transfer.Receiver(self.ident, s, store.TrustStore(os.path.join(self.dir, "tr")),
                               store.History(os.path.join(self.dir, "h")), H(), bind="127.0.0.1",
                               port=FreePort.get())
        rx.start()
        me = identity.Identity.load_or_create(os.path.join(self.dir, "client"))
        try:
            with socket.create_connection(("127.0.0.1", rx.port), timeout=10) as raw:
                with transfer.client_context().wrap_socket(raw, server_hostname=None) as tls:
                    ch = proto.Channel(tls)
                    nc = os.urandom(32)
                    ch.send({"type": "hello", "proto": 1, "name": "T", "id": me.id,
                             "cert": base64.b64encode(me.cert_der).decode(), "commit": proto.commit(nc).hex()})
                    ns = bytes.fromhex(ch.recv_msg("hello")["nonce"])
                    sig = me.sign(proto.auth_message(self.ident.fp, me.fp, ns, nc))
                    ch.send({"type": "auth", "nonce": nc.hex(), "sig": base64.b64encode(sig).decode()})
                    ch.recv_msg("auth_ok")
                    ch.send({"type": "offer", "transfer_id": "ab" * 16, "dirs": [], "total": 1,
                             "files": [{"path": "a.txt", "size": 1, "sha256": "00" * 32, "exec": False}]})
                    self.assertEqual(ch.recv_msg("reject", "accept")["type"], "reject")
                    tls.settimeout(5)
                    self.assertEqual(tls.recv(1), b"")  # EOF, ne vyprseni casu
            self.assertTrue(kept)
        finally:
            rx.stop()

    def test_android_like_client_order(self):
        # Klient jako BoringSSL (AES-128 nebo ChaCha20 prvni) -> server presto vybere AES-256
        cctx = transfer.client_context()
        if not hasattr(cctx, "set_ciphersuites"):
            self.skipTest("Python < 3.15 cannot order TLS 1.3 client suites (checked by the Java interop test)")
        for order in ("TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256",
                      "TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384"):
            cctx.set_ciphersuites(order)
            client, _server = self.handshake(cctx)
            self.assertEqual(client[1], "TLS_AES_256_GCM_SHA384", order)


BAD_PATHS = [
    "", "..", "../x", "a/../../x", "a/..", "/etc/passwd", "//x", "a//b", "./a", "a/./b", "a/", "a\\..\\b",
    "..\\x", "a\x00b", "a\nb", "a\rb", "\x7f", "~/x", "~", "x" * 256, "a/" * 70 + "b", "a" + "/b" * 5000,
    "e\u0301", None, 5, ["a"], "\udc80", "foto\u202egpj.exe", "a\u2066b", "a\x85b", "a\u200fb",
]
GOOD_PATHS = ["a", "a b/c.txt", "Složka/Žluťoučký kůň.txt", ".hidden", "a..b", "...", "x" * 255, "C:x", "dir/sub/f"]


class TestPaths(unittest.TestCase):
    def test_bad(self):
        for p in BAD_PATHS:
            with self.assertRaises(proto.ProtocolError, msg=repr(p)) as cm:
                pathsafe.check_relpath(p)
            self.assertEqual(cm.exception.code, proto.E_INVALID_OFFER)

    def test_good(self):
        for p in GOOD_PATHS:
            self.assertEqual(pathsafe.check_relpath(p), tuple(p.split("/")))

    def offer(self, files, dirs=()):
        return {"files": [{"path": p, "size": 1, "sha256": "00" * 32} for p in files], "dirs": list(dirs)}

    def test_offer_rejects(self):
        cases = [
            self.offer(["a", "a"]),                 # duplicita
            self.offer(["a", "a/b"]),               # soubor pod souborem
            self.offer(["a"], ["a"]),               # soubor i slozka
            self.offer(["../evil"]),
            self.offer([], ["d", "d/../../x"]),
            {"files": [{"path": "a", "size": -1, "sha256": "00" * 32}]},
            {"files": [{"path": "a", "size": True, "sha256": "00" * 32}]},
            {"files": [{"path": "a", "size": "5", "sha256": "00" * 32}]},
            {"files": [{"path": "a", "size": 1, "sha256": "zz" * 32}]},
            {"files": [{"path": "a", "size": 1, "sha256": "00" * 31}]},
            {"files": [{"path": "a", "size": 2 ** 60, "sha256": "00" * 32}]},
            {"files": "a"},
            {"files": []},
            {"files": ["a"]},
            {"files": [{"path": "f%d" % i, "size": 0, "sha256": "00" * 32} for i in range(pathsafe.MAX_FILES + 1)]},
        ]
        for o in cases:
            with self.assertRaises(proto.ProtocolError, msg=str(o)[:80]):
                pathsafe.check_offer(o)

    def test_offer_ok(self):
        files, dirs, total = pathsafe.check_offer(self.offer(["d/a", "d/e/b", "c"], ["d", "d/e", "d/empty"]))
        self.assertEqual(total, 3)
        self.assertEqual([f["parts"] for f in files], [("d", "a"), ("d", "e", "b"), ("c",)])
        self.assertIn(("d", "empty"), dirs)

    def test_collect_skips_symlinks_and_specials(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, "top", "sub"))
            wr(os.path.join(d, "top", "sub", "f"), "x")
            os.symlink("/etc/passwd", os.path.join(d, "top", "link"))
            os.symlink("/etc", os.path.join(d, "top", "dirlink"))
            os.mkfifo(os.path.join(d, "top", "fifo"))
            skipped = []
            items, dirs = pathsafe.collect([os.path.join(d, "top")], on_skip=lambda p, w: skipped.append(p))
            self.assertEqual([r for _p, r, _s, _x in items], ["top/sub/f"])
            self.assertEqual(dirs, ["top", "top/sub"])
            self.assertEqual(len(skipped), 3)
        finally:
            shutil.rmtree(d)

    def test_collect_duplicate_top_names(self):
        d = tempfile.mkdtemp()
        try:
            for sub in ("x", "y"):
                os.makedirs(os.path.join(d, sub))
                wr(os.path.join(d, sub, "same.txt"), sub)
            items, _dirs = pathsafe.collect([os.path.join(d, "x", "same.txt"), os.path.join(d, "y", "same.txt")])
            self.assertEqual([r for _p, r, _s, _x in items], ["same.txt", "same.txt (2)"])
        finally:
            shutil.rmtree(d)


class TestHashAndFinalize(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.dfd = os.open(self.dir, os.O_RDONLY | os.O_DIRECTORY)

    def tearDown(self):
        os.close(self.dfd)
        shutil.rmtree(self.dir)

    def write(self, name, data):
        with open(os.path.join(self.dir, name), "wb") as f:
            f.write(data)

    def test_verify_part(self):
        data = os.urandom(300_000)
        sha = hashlib.sha256(data).digest()
        self.write("ok", data)
        self.assertTrue(transfer.verify_part(self.dfd, "ok", len(data), sha))
        tampered = bytearray(data)
        tampered[150_000] ^= 1
        self.write("bad", bytes(tampered))
        self.assertFalse(transfer.verify_part(self.dfd, "bad", len(data), sha))
        self.write("short", data[:-1])
        self.assertFalse(transfer.verify_part(self.dfd, "short", len(data), sha))
        self.write("long", data + b"\0")
        self.assertFalse(transfer.verify_part(self.dfd, "long", len(data), sha))
        self.assertFalse(transfer.verify_part(self.dfd, "missing", len(data), sha))
        os.symlink(os.path.join(self.dir, "ok"), os.path.join(self.dir, "link"))
        self.assertFalse(transfer.verify_part(self.dfd, "link", len(data), sha))  # O_NOFOLLOW

    def test_finalize_never_overwrites(self):
        dest = os.path.join(self.dir, "dest")
        os.mkdir(dest)
        with open(os.path.join(dest, "a.txt"), "w") as f:
            f.write("original")
        os.mkdir(os.path.join(dest, "folder"))
        part_fd = transfer.Receiver._open_part_dir(dest)
        try:
            fp = b"\1" * 32
            files, dirs, _t = pathsafe.check_offer({"files": [
                {"path": "a.txt", "size": 3, "sha256": hashlib.sha256(b"new").hexdigest()},
                {"path": "folder/x/y.bin", "size": 3, "sha256": hashlib.sha256(b"yyy").hexdigest(), "exec": True},
            ], "dirs": ["folder", "folder/x", "folder/empty"]})
            for f, content in zip(files, (b"new", b"yyy")):
                fd = os.open(transfer.part_name(fp, f["path"], f["sha256"], f["size"]),
                             os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=part_fd)
                os.write(fd, content)
                os.close(fd)
            names = transfer.Receiver._finalize(dest, part_fd, fp, files, dirs)
        finally:
            os.close(part_fd)
        self.assertEqual(sorted(names), ["a (1).txt", "folder (1)"])
        self.assertEqual(rd(os.path.join(dest, "a.txt")), "original")
        self.assertEqual(rd(os.path.join(dest, "a (1).txt")), "new")
        y = os.path.join(dest, "folder (1)", "x", "y.bin")
        self.assertEqual(rd(y), "yyy")
        self.assertEqual(os.stat(y).st_mode & 0o777, 0o755)
        self.assertTrue(os.path.isdir(os.path.join(dest, "folder (1)", "empty")))
        self.assertEqual(os.listdir(os.path.join(dest, ".luxdrop-partial")), [])

    def test_partial_dir_symlink_refused(self):
        dest = os.path.join(self.dir, "d2")
        os.mkdir(dest)
        os.symlink("/tmp", os.path.join(dest, ".luxdrop-partial"))
        with self.assertRaises(OSError):
            transfer.Receiver._open_part_dir(dest)


class TestStore(unittest.TestCase):
    def test_trust_and_mode(self):
        d = tempfile.mkdtemp()
        try:
            t = store.TrustStore(os.path.join(d, "data"))
            fp = hashlib.sha256(b"peer").digest()
            self.assertFalse(t.is_trusted(fp))
            t.add(fp, "Peer PC", "1.2.3.4:47923")
            self.assertTrue(t.is_trusted(fp))
            self.assertEqual(os.stat(t.path).st_mode & 0o777, 0o600)
            self.assertEqual(len(t.find(fp[:8].hex())), 1)
            self.assertEqual(len(t.find("peer pc")), 1)
            self.assertEqual(t.remove("Peer PC"), 1)
            self.assertFalse(t.is_trusted(fp))
            s = store.Settings(os.path.join(d, "cfg"))
            # Vychozi rezim: kazdy v okoli se muze zeptat (prenos se vzdy musi potvrdit)
            self.assertEqual(s.mode(), "everyone")
            self.assertEqual(s.everyone_left(), 0)
            s.set_mode("trusted")
            self.assertEqual(store.Settings(os.path.join(d, "cfg")).mode(), "trusted")
            s.set_mode("everyone", minutes=5)  # casove omezene
            self.assertEqual(s.mode(), "everyone")
            self.assertTrue(250 < s.everyone_left() <= 300)
            s.data["everyone_until"] = 1  # vyprselo
            self.assertEqual(s.mode(), "trusted")
            s.data["everyone_until"] = time.time() + 3600  # rucne prodlouzene nad 10 minut
            self.assertEqual(s.mode(), "trusted")
            s.set_mode("everyone", minutes=60)  # max. 10 minut
            self.assertLessEqual(s.everyone_left(), 600)
            self.assertTrue(s.download_dir.endswith(os.path.join("Downloads", "LuxDrop")) or s.data["download_dir"])
            # LocalSend zaznam v duveryhodnych
            t.add(fp, "Phone", kind="localsend", cert_fp="AB" * 32, device_type="mobile")
            e = t.get(fp)
            self.assertEqual((e["kind"], e["cert_fp"], e["device_type"]), ("localsend", "AB" * 32, "mobile"))
        finally:
            shutil.rmtree(d)

    def test_parse_addr(self):
        self.assertEqual(transfer.parse_addr("10.0.0.5"), ("10.0.0.5", proto.DEFAULT_PORT))
        self.assertEqual(transfer.parse_addr("10.0.0.5:1234"), ("10.0.0.5", 1234))
        self.assertEqual(transfer.parse_addr("[fe80::1%eth0]:99"), ("fe80::1%eth0", 99))
        self.assertEqual(transfer.fmt_addr("::1", 5), "[::1]:5")


if __name__ == "__main__":
    unittest.main(verbosity=2)
