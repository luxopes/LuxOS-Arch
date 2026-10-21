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

from luxdrop import localsend, lshttp  # noqa: E402

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
