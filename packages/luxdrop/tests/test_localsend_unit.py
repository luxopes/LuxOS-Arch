#!/usr/bin/env python3
"""LuxDrop - jednotkove testy kompatibility s LocalSend: zpravy, otisky, nazvy souboru, HTTP.

Spusteni: python3 -m unittest -v tests/test_localsend_unit.py  (z adresare packages/luxdrop)
"""
import base64
import io
import json
import os
import sys
import unicodedata
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("LUXDROP_LIB", os.path.join(HERE, "..", "files", "lib")))

from luxdrop import localsend, lshttp, lsserver, lssend, pathsafe, transfer  # noqa: E402

# Testovaci certifikat a otisk z oficialni implementace LocalSend
# (packages/core/src/crypto/cert.rs, test_fingerprint_from_cert_der)
LS_CERT_B64 = (
    "MIIDGTCCAgGgAwIBAgIBATANBgkqhkiG9w0BAQsFADBQMRcwFQYDVQQDEw5Mb2NhbFNlbmQgVXNlcjEJMAcGA1UEChMAMQkwBwYDVQQL"
    "EwAxCTAHBgNVBAcTADEJMAcGA1UECBMAMQkwBwYDVQQGEwAwHhcNMjUwMjA5MDAwMzE0WhcNMzUwMjA3MDAwMzE0WjBQMRcwFQYDVQQD"
    "Ew5Mb2NhbFNlbmQgVXNlcjEJMAcGA1UEChMAMQkwBwYDVQQLEwAxCTAHBgNVBAcTADEJMAcGA1UECBMAMQkwBwYDVQQGEwAwggEiMA0G"
    "CSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQCL24MxhGfrdJm0Q8ZGiBkZ27ldcEChB4w7rSbJyiKeosoNbJl2kyj5dZjfBhWGgDLGDMM5"
    "w+Mh/5SrWgTL/QrhbB+lsrxILLznWqBiR8wJP0P2YW9fBahQskJQcUXt/3jsCsMTWea4rWc3HZGh03bAkJfLM+PDSOfTpvAZ6DQSp9QL"
    "zC9bgVNnq3W0SvOZGpF0xRa4InCyTUgxsNsV4+GIrmN5w4EbRFVVYu7D5OS5fxNSCukiS0fb6oQzUp0vIAycvvWHHbAy8T6UMoUor2nf"
    "vNcryiaOX5WBMLyhyMZ5gMOyXjdm1bT1XSlvtXPYUzxvsGAzTqS8mXjw8h7mm5htAgMBAAEwDQYJKoZIhvcNAQELBQADggEBABZ+I7D6"
    "wkeSrsi1NBLP2zoZ5oGh+INNcGTravfOQHs4Fbas/CysaUYjsD3fmaDh4MxgWEqAmWnnBiojfpGX2SGuFqRBKyT9DgitBt0L7Ezg1k3h"
    "bfSiFW4hXWp75grVO8xfML7ZcWMlhKrOsOMUGiy1qs3qsyJ3w7B2Tz78HhXGO5ddjyPmZarhixKO92UpEvKGxjO0E/3UUNUzxKTAAgFf"
    "hKpuwHUgIijM/EppZtA8OcShfEztiV0xKfcPVx4d6dqRt/NMElK1Ivw2vUuxTymphZkkFOzht9m73/kyKaeFp8IjVRus1zGVD8IVpIdP"
    "Myz01WJyS7M0fWaHXKWo+Bo=")
LS_CERT_FP = "4BADDE53A7F7CDEEED93189FD898E02BF6B4806CA4C05DE0ACE08319B86552FA"


def prepare(files, info=None):
    return {"info": info or {"alias": "Phone", "version": "2.1", "deviceModel": "Samsung",
                             "deviceType": "mobile", "fingerprint": "x", "port": 53317,
                             "protocol": "https", "download": False},
            "files": {f["id"]: f for f in files}}


def fdto(fid, name, size=1, ftype="application/octet-stream", **kw):
    return dict({"id": fid, "fileName": name, "size": size, "fileType": ftype}, **kw)


class TestFingerprint(unittest.TestCase):
    def test_official_vector(self):
        der = base64.b64decode(LS_CERT_B64)
        self.assertEqual(localsend.cert_fingerprint(der), LS_CERT_FP)

    def test_spki_of_rsa_cert(self):
        der = base64.b64decode(LS_CERT_B64)
        fp = localsend.spki_fingerprint_der(der)
        self.assertEqual(len(fp), 32)
        self.assertNotEqual(fp.hex().upper(), LS_CERT_FP)  # klic != certifikat

    def test_norm_fp(self):
        self.assertEqual(localsend.norm_fp(LS_CERT_FP.lower()), LS_CERT_FP)
        self.assertEqual(localsend.norm_fp("random string"), "")
        self.assertEqual(localsend.norm_fp(None), "")


class TestMessages(unittest.TestCase):
    def test_my_info_shape(self):
        info = localsend.my_info("Alice PC", LS_CERT_FP, 53317, luxdrop={"id": "0123456789abcdef", "port": 47923},
                                 announce=True)
        for k in ("alias", "version", "deviceModel", "deviceType", "fingerprint", "port", "protocol", "download"):
            self.assertIn(k, info)
        self.assertEqual(info["version"], "2.2")
        self.assertEqual(info["protocol"], "https")
        self.assertEqual(info["deviceType"], "desktop")
        self.assertTrue(info["announce"] and info["announcement"])  # v2 i v1
        self.assertEqual(info["luxdrop"], {"v": 1, "id": "0123456789abcdef", "port": 47923})
        json.dumps(info)

    def test_parse_info(self):
        i = localsend.parse_info({"alias": " Pixel\u202e 8 \x07", "version": "2.0", "deviceType": "SMARTWATCH",
                                  "fingerprint": LS_CERT_FP.lower(), "port": 53317, "protocol": "https"})
        self.assertEqual(i["alias"], "Pixel 8")
        self.assertEqual(i["deviceType"], "desktop")  # neznamy typ -> desktop
        self.assertEqual(i["fingerprint"], LS_CERT_FP)
        self.assertIsNone(i["luxdrop"])
        with self.assertRaises(localsend.Invalid):
            localsend.parse_info({"alias": "x", "port": 70000})
        with self.assertRaises(localsend.Invalid):
            localsend.parse_info({"alias": "x", "port": 1, "protocol": "ftp"})
        with self.assertRaises(localsend.Invalid):
            localsend.parse_info({"alias": "", "port": 1})
        # Spatne rozsireni luxdrop se ignoruje
        i = localsend.parse_info({"alias": "x", "port": 1, "luxdrop": {"v": 1, "id": "../../", "port": 1}})
        self.assertIsNone(i["luxdrop"])

    def test_datagram_v1_and_v2(self):
        v2 = {"alias": "A", "version": "2.1", "fingerprint": "abc", "port": 53317, "protocol": "https",
              "announce": True}
        v1 = {"alias": "B", "deviceModel": "Win", "deviceType": "desktop", "fingerprint": "def",
              "announcement": True}
        self.assertTrue(localsend.parse_datagram(json.dumps(v2).encode())["announce"])
        d1 = localsend.parse_datagram(json.dumps(v1).encode())
        self.assertTrue(d1["announce"])
        self.assertEqual(d1["port"], 53317)
        self.assertIsNone(localsend.parse_datagram(b"\xff\xfe garbage"))
        self.assertIsNone(localsend.parse_datagram(b"[]"))
        self.assertIsNone(localsend.parse_datagram(json.dumps({"alias": "x"}).encode()))  # bez otisku
        self.assertIsNone(localsend.parse_datagram(b"{" + b" " * 70000 + b"}"))

    def test_prepare_response(self):
        self.assertEqual(localsend.parse_prepare_response({"sessionId": "s", "files": {"a": "t"}}), ("s", {"a": "t"}))
        for bad in ({}, {"sessionId": "", "files": {}}, {"sessionId": "s", "files": {"a": 1}}):
            with self.assertRaises(localsend.Invalid):
                localsend.parse_prepare_response(bad)


class TestNames(unittest.TestCase):
    def test_traversal_rejected(self):
        for bad in ("../x", "a/../../b", "/etc/passwd", "~/x", "C:\\Windows\\x", "..", "a\\..\\..\\b", ""):
            with self.assertRaises(localsend.Invalid, msg=bad):
                localsend.sanitize_name(bad)

    def test_cleanup(self):
        self.assertEqual(localsend.sanitize_name("Fotky/2024/a.jpg"), "Fotky/2024/a.jpg")
        self.assertEqual(localsend.sanitize_name("./a//b/./c.txt"), "a/b/c.txt")
        self.assertEqual(localsend.sanitize_name("dir\\file.txt"), "dir/file.txt")  # Windows oddelovac
        nfd = unicodedata.normalize("NFD", "Žluťoučký kůň.txt")  # rozlozene znaky (NFD)
        self.assertEqual(localsend.sanitize_name(nfd), "Žluťoučký kůň.txt")
        self.assertEqual(localsend.sanitize_name("evil\u202egpj.exe"), "evil_gpj.exe")
        self.assertEqual(localsend.sanitize_name("a\x00b\nc"), "a_b_c")
        long = "x" * 300 + ".jpeg"
        out = localsend.sanitize_name(long)
        self.assertLessEqual(len(out.encode()), 255)
        self.assertTrue(out.endswith(".jpeg"))
        self.assertEqual(localsend.sanitize_name("Meeting: notes?.txt"), "Meeting: notes?.txt")

    def test_prepare_upload(self):
        info, files, total, msg = localsend.parse_prepare_upload(prepare([
            fdto("1", "b.txt", 5, sha256="ab" * 32), fdto("2", "Dir/a.jpg", 7, "image/jpeg",
                                                         metadata={"modified": "2024-01-02T03:04:05Z"})]))
        self.assertEqual(info["alias"], "Phone")
        self.assertEqual(info["deviceType"], "mobile")
        self.assertEqual(total, 12)
        self.assertIsNone(msg)
        self.assertEqual([f["rel"] for f in files], ["Dir/a.jpg", "b.txt"])
        self.assertEqual(files[1]["sha256"], bytes.fromhex("ab" * 32))
        self.assertEqual(files[0]["modified"], 1704164645)

    def test_message(self):
        _i, files, _t, msg = localsend.parse_prepare_upload(prepare([
            fdto("m", "m.txt", 5, "text/plain", preview="Ahoj!")]))
        self.assertEqual(msg, "Ahoj!")
        # Text spolu se souborem neni zprava
        _i, _f, _t, msg = localsend.parse_prepare_upload(prepare([
            fdto("m", "m.txt", 5, "text/plain", preview="Ahoj!"), fdto("f", "x.bin", 1)]))
        self.assertIsNone(msg)
        # v1: fileType "text"
        _i, _f, _t, msg = localsend.parse_prepare_upload(prepare([fdto("m", "m.txt", 2, "text", preview="hi")]))
        self.assertEqual(msg, "hi")

    def test_prepare_invalid(self):
        bad_cases = [
            prepare([]),
            prepare([fdto("1", "../x")]),
            prepare([fdto("1", "a", -1)]),
            prepare([fdto("1", "a", 2 ** 60)]),
            prepare([fdto("1", "a", True)]),
            prepare([fdto("1", "a", sha256="xyz")]),
            prepare([fdto("1", "a"), fdto("2", "a/b")]),      # soubor i slozka
            {"info": {"alias": "x"}, "files": {"1": fdto("2", "a")}},  # id != klic
            {"files": {"1": fdto("1", "a")}},                  # bez info
            "string",
        ]
        for b in bad_cases:
            with self.assertRaises(localsend.Invalid, msg=repr(b)[:80]):
                localsend.parse_prepare_upload(b)

    def test_duplicates_renamed(self):
        nfc = "č.txt"
        _i, files, _t, _m = localsend.parse_prepare_upload(prepare([
            fdto("1", nfc), fdto("2", unicodedata.normalize("NFD", nfc)), fdto("3", "Č.TXT")]))
        names = sorted(f["rel"] for f in files)
        self.assertEqual(len(set(n.casefold() for n in names)), 3)

    def test_duplicate_long_names_remain_valid_paths(self):
        for name in ("a" * 251 + ".txt", "ž" * 125 + "x.txt", "dir/" + "界" * 85):
            with self.subTest(name=name):
                _i, files, _t, _m = localsend.parse_prepare_upload(prepare([
                    fdto("1", name), fdto("2", name), fdto("3", name)]))
                self.assertEqual(len({f["rel"].casefold() for f in files}), 3)
                for f in files:
                    pathsafe.check_relpath(f["rel"])

    def test_file_dto(self):
        d = localsend.file_dto("id1", "a/b.png", 10, "ab" * 32, modified=0.5 * 2)
        self.assertEqual(d["fileType"], "image/png")
        self.assertEqual(d["metadata"]["modified"], "1970-01-01T00:00:01Z")
        self.assertEqual(localsend.file_dto("x", "noext", 1)["fileType"], "application/octet-stream")


class FakeConn:
    def __init__(self, data, step=5):
        self.buf = io.BytesIO(data)
        self.step = step

    def recv(self, n):
        return self.buf.read(min(n, self.step))


class TestHTTP(unittest.TestCase):
    def req(self, raw):
        return lshttp.read_request(lshttp.Reader(FakeConn(raw)), "1.2.3.4", None)

    def test_content_length(self):
        r = self.req(b"POST /api/localsend/v2/register?x=1&pin=12%2034 HTTP/1.1\r\nHost: a\r\n"
                     b"Content-Length: 11\r\n\r\n{\"alias\":1}")
        self.assertEqual(r.path, "/api/localsend/v2/register")
        self.assertEqual(r.query, {"x": "1", "pin": "12 34"})
        self.assertEqual(r.json(), {"alias": 1})
        self.assertTrue(r.keep_alive)

    def test_chunked(self):
        r = self.req(b"POST /u HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n"
                     b"4\r\nabcd\r\n3;ext=1\r\nefg\r\n0\r\nX-Trailer: 1\r\n\r\n")
        self.assertEqual(r.body.read_all(100), b"abcdefg")
        self.assertTrue(r.body.done)

    def test_two_requests_keepalive(self):
        rd = lshttp.Reader(FakeConn(b"GET /a HTTP/1.1\r\n\r\nGET /b HTTP/1.1\r\nConnection: close\r\n\r\n"))
        a = lshttp.read_request(rd, "ip", None)
        self.assertTrue(a.body.drain())
        b = lshttp.read_request(rd, "ip", None)
        self.assertEqual((a.path, b.path, b.keep_alive), ("/a", "/b", False))
        self.assertIsNone(lshttp.read_request(rd, "ip", None))

    def test_limits(self):
        with self.assertRaises(lshttp.HTTPError) as c:
            self.req(b"GET /" + b"a" * 9000 + b" HTTP/1.1\r\n\r\n")
        self.assertEqual(c.exception.status, 431)
        with self.assertRaises(lshttp.HTTPError):
            self.req(b"GET / HTTP/1.1\r\n" + b"X: y\r\n" * 70 + b"\r\n")
        with self.assertRaises(lshttp.HTTPError):
            self.req(b"POST / HTTP/1.1\r\nContent-Length: -1\r\n\r\n")
        with self.assertRaises(lshttp.HTTPError):
            self.req(b"POST / HTTP/1.1\r\nTransfer-Encoding: gzip\r\n\r\n")
        r = self.req(b"POST / HTTP/1.1\r\nContent-Length: 100\r\n\r\n" + b"x" * 100)
        with self.assertRaises(lshttp.HTTPError) as c:
            r.body.read_all(50)
        self.assertEqual(c.exception.status, 413)
        r = self.req(b"POST / HTTP/1.1\r\nContent-Length: 10\r\n\r\nabc")
        with self.assertRaises(ConnectionError):
            r.body.read_all(100)
        r = self.req(b"POST / HTTP/1.1\r\nContent-Length: 5\r\n\r\nnot j")
        with self.assertRaises(lshttp.HTTPError):
            r.json()

    def test_line_limits_do_not_depend_on_packet_boundaries(self):
        requests = [b"GET /" + b"a" * 9000 + b" HTTP/1.1\r\n\r\n",
                    b"GET / HTTP/1.1\r\nX: " + b"a" * 9000 + b"\r\n\r\n"]
        for raw in requests:
            for step in (5, 65536):
                with self.subTest(header=raw.startswith(b"GET / HTTP"), step=step):
                    with self.assertRaises(lshttp.HTTPError) as c:
                        lshttp.read_request(lshttp.Reader(FakeConn(raw, step)), "ip", None)
                    self.assertEqual(c.exception.status, 431)

    def test_many_short_lines_in_one_packet_are_valid(self):
        raw = b"GET / HTTP/1.1\r\n" + b"X: " + b"x" * 4000 + b"\r\nY: " + b"y" * 5000 + b"\r\n\r\n"
        req = lshttp.read_request(lshttp.Reader(FakeConn(raw, 65536)), "ip", None)
        self.assertEqual(len(req.headers["x"]), 4000)
        self.assertEqual(len(req.headers["y"]), 5000)

    def test_chunk_sizes_reject_signs_and_numeric_prefixes(self):
        for size in (b"-1", b"+1", b"0x1", b"GG"):
            with self.subTest(size=size):
                req = self.req(b"POST /upload HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n" +
                               size + b"\r\na\r\n0\r\n\r\n")
                with self.assertRaises(lshttp.HTTPError) as c:
                    req.body.read_all(100)
                self.assertEqual(c.exception.status, 400)

    def test_response(self):
        raw = lshttp.response_bytes(200, {"a": "č"})
        head, body = raw.split(b"\r\n\r\n", 1)
        self.assertIn(b"HTTP/1.1 200 OK", head)
        self.assertIn(b"Content-Length: %d" % len(body), head)
        self.assertEqual(json.loads(body), {"a": "č"})
        raw = lshttp.response_bytes(403, close=True)
        self.assertIn(b"Connection: close", raw)
        self.assertIn(b'"message":"Forbidden"', raw)
        self.assertIn(b"Content-Length: 0", lshttp.response_bytes(204))


class TestLocalSendUnverified(unittest.TestCase):
    """L-04: zarizeni LocalSend jsou neoverena - pripnuti klice ke jmenu, zmena klice, zadne rychle ulozeni."""

    def setUp(self):
        import shutil
        import tempfile
        from luxdrop import store
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.trust = store.TrustStore(self.dir)
        self.k1, self.k2 = bytes(range(32)), bytes(range(1, 33))

    def test_short_code(self):
        self.assertEqual(localsend.short_code(LS_CERT_FP), "4BAD DE53 A7F7 CDEE")
        self.assertEqual(localsend.short_code(LS_CERT_FP.lower()), "4BAD DE53 A7F7 CDEE")
        self.assertEqual(localsend.short_code("addr:1.2.3.4:53317"), "")
        self.assertEqual(localsend.short_code(None), "")

    def test_pin_and_change(self):
        t = self.trust
        self.assertIsNone(t.ls_pin_get("Phone"))
        self.assertFalse(t.ls_pin_changed("Phone", self.k1))   # nezname jmeno = zadne varovani
        self.assertFalse(t.ls_pin_changed("Phone", None))
        t.ls_pin_set("Phone", self.k1, LS_CERT_FP)
        self.assertFalse(t.ls_pin_changed("Phone", self.k1))
        self.assertFalse(t.ls_pin_changed("  phone ", self.k1))  # velikost pismen a mezery nerozhoduji
        self.assertTrue(t.ls_pin_changed("PHONE", self.k2))      # stejne jmeno, jiny klic
        self.assertTrue(t.ls_pin_changed("Phone", None))         # stejne jmeno bez certifikatu
        self.assertFalse(t.ls_pin_changed("Phone 2", self.k2))
        self.assertEqual(t.ls_pin_get("phone")["cert_fp"], LS_CERT_FP)
        path = os.path.join(self.dir, "localsend_pins.json")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        # potvrzena zmena klice = novy pin
        t.ls_pin_set("Phone", self.k2)
        self.assertFalse(t.ls_pin_changed("Phone", self.k2))
        self.assertTrue(t.ls_pin_changed("Phone", self.k1))
        self.assertTrue(t.ls_pin_remove("phone"))
        self.assertFalse(t.ls_pin_changed("Phone", self.k1))

    def test_pin_ignores_bad_data(self):
        with open(os.path.join(self.dir, "localsend_pins.json"), "w") as f:
            json.dump({"phone": {"spki": "nothex"}, "x": "y"}, f)
        self.assertIsNone(self.trust.ls_pin_get("phone"))
        self.trust.ls_pin_set("", self.k1)          # bez jmena / klice se nic neulozi
        self.trust.ls_pin_set("Phone", None)
        self.assertIsNone(self.trust.ls_pin_get("phone"))

    def test_engine_marks(self):
        from luxdrop import engine
        e = engine.Engine.__new__(engine.Engine)
        e.trust = self.trust
        d = {"name": "Phone", "fingerprint": LS_CERT_FP, "spki": self.k1}
        m = e.ls_marks(d)
        self.assertEqual(m, {"unverified": True, "short_code": "4BAD DE53 A7F7 CDEE", "key_changed": False})
        self.trust.ls_pin_set("Phone", self.k2)
        self.assertTrue(e.ls_marks(d)["key_changed"])

    def _server(self, trusted_auto=True):
        from luxdrop import lsserver, store
        s = store.Settings.__new__(store.Settings)
        s.data = dict(store.Settings.DEFAULTS, auto_accept_trusted=trusted_auto)
        srv = lsserver.LocalSendServer.__new__(lsserver.LocalSendServer)
        srv.settings = s
        asked = []

        class H:
            def ask(self, req):
                asked.append(req)
                return False, False
        srv.handler = H()
        import threading
        srv._prompt_sem = threading.BoundedSemaphore(2)
        srv._stop = threading.Event()
        return srv, asked

    def test_never_auto_accept(self):
        """Duveryhodne zarizeni LocalSend + "Rychle ulozeni" -> stejne dotaz (driv prijato bez dotazu)."""
        import socket
        import threading
        from luxdrop import transfer
        srv, asked = self._server(trusted_auto=True)
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)

        class Conn:
            sock = a

            @staticmethod
            def pending():
                return False
        t = transfer.Transfer("in", "Phone", "4badde53")
        info = {"deviceModel": "Samsung"}
        accept, remember = srv._decide(t, None, Conn, self.k1, True, False, [], info, True, threading.Event(),
                                       key_changed=True, code="4BAD DE53 A7F7 CDEE")
        self.assertEqual((accept, remember), (False, False))
        self.assertEqual(len(asked), 1)
        r = asked[0]
        self.assertTrue(r.key_changed)
        self.assertEqual(r.short_code, "4BAD DE53 A7F7 CDEE")
        self.assertEqual(r.protocol, "localsend")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestPinGlobalLimit(unittest.TestCase):
    """PIN: kromě 3 pokusu z jedne site i strop pro vsechny site dohromady (zkouseni z mnoha adres)."""

    def server(self):
        class S:
            pin = "4711"
        srv = lsserver.LocalSendServer.__new__(lsserver.LocalSendServer)
        srv.settings = S()
        srv.pin_fail, srv.pin_global = {}, []
        return srv

    def test_many_networks_hit_global_limit(self):
        srv = self.server()
        codes = []
        for i in range(lsserver.PIN_GLOBAL_MAX + 3):
            try:
                srv._check_pin(Req("fd00:0:0:%x::1" % i, "0000"), False)
            except lshttp.HTTPError as e:
                codes.append(e.status)
        self.assertEqual(codes[:lsserver.PIN_GLOBAL_MAX], [401] * lsserver.PIN_GLOBAL_MAX)
        self.assertEqual(codes[lsserver.PIN_GLOBAL_MAX:], [429] * 3)
        # duveryhodne zarizeni PIN nepotrebuje ani behem blokovani
        srv._check_pin(Req("fd00::ffff", None), True)

    def test_one_device_with_many_addresses_does_not_lock_out_others(self):
        # jedno zarizeni si v IPv6 /64 vytvori libovolne adres: blokuje se jen ono, ne PIN pro vsechny
        srv = self.server()
        codes = []
        for i in range(lsserver.PIN_GLOBAL_MAX * 2):
            try:
                srv._check_pin(Req("2001:db8:1:2::%x" % (i + 1), "0000"), False)
            except lshttp.HTTPError as e:
                codes.append(e.status)
        self.assertEqual(codes[:lsserver.PIN_MAX_ATTEMPTS], [401] * lsserver.PIN_MAX_ATTEMPTS)
        self.assertEqual(set(codes[lsserver.PIN_MAX_ATTEMPTS:]), {429})
        srv._check_pin(Req("192.168.1.5", "4711"), False)          # jiny telefon se spravnym PINem projde
        srv._check_pin(Req("2001:db8:9:9::5", "4711"), False)
        self.assertEqual(lsserver.pin_source("::ffff:192.168.1.5"), "192.168.1.5")
        self.assertEqual(lsserver.pin_source("fe80::1%wlan0"), "fe80::/64")


class Req:
    def __init__(self, ip, pin):
        self.ip, self.query = ip, {"pin": pin}


class TestSendConnectionLost(unittest.TestCase):
    def test_lost_during_transfer_is_not_connection_failed(self):
        import unittest.mock as um

        class CB:
            def update(self, t):
                pass

        class Hist:
            def add(self, e):
                pass

        def broken(*args):
            args[7].state = "transferring"            # spojeni spadlo uprostred prenosu (Wi-Fi)
            raise ConnectionResetError(104, "Connection reset by peer")
        with um.patch.object(lssend, "_send", side_effect=broken):
            t = lssend.send(None, None, None, Hist(), {"name": "Phone", "fingerprint": "AB" * 32}, CB(), paths=[])
        self.assertEqual(t.state, "failed")
        self.assertTrue(t.error.startswith("connection lost"), t.error)


class TestSendHttpException(unittest.TestCase):
    def test_broken_reply_is_failed_transfer(self):
        """Poskozena odpoved prijemce (http.client.HTTPException) = neuspesny prenos, ne pad vlakna."""
        import http.client
        import unittest.mock as um

        class CB:
            def update(self, t):
                pass

        class Hist:
            def add(self, e):
                pass
        with um.patch.object(lssend, "_send", side_effect=http.client.BadStatusLine("garbage")):
            t = lssend.send(None, None, None, Hist(), {"name": "Phone", "fingerprint": "AB" * 32}, CB(), paths=[])
        self.assertEqual(t.state, "failed")
