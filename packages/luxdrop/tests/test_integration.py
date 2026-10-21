#!/usr/bin/env python3
"""LuxDrop - integracni testy: vice instanci v oddelenych HOME na 127.0.0.1 (bez mDNS).

A = "Alice-PC" (odesilatel), B = "Bob-PC" (prijemce), C = "Carol-PC" (cizi zarizeni),
M = utocnik, ktery se vydava za "Bob-PC" s jinym klicem.

Spusteni (z adresare packages/luxdrop): python3 tests/test_integration.py -v
"""
import base64
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.environ.get("LUXDROP_LIB", os.path.abspath(os.path.join(HERE, "..", "files", "lib")))
LAUNCHER = os.environ.get("LUXDROP_BIN", os.path.abspath(os.path.join(HERE, "..", "files", "luxdrop")))
sys.path.insert(0, LIB)

from luxdrop import identity, proto, transfer  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tree(root):
    """{relativni cesta: (typ, sha/None, prava)} bez symlinku."""
    out = {}
    for dp, dns, fns in os.walk(root):
        for d in dns:
            p = os.path.join(dp, d)
            if not os.path.islink(p):
                out[os.path.relpath(p, root)] = ("d", None, None)
        for f in fns:
            p = os.path.join(dp, f)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            out[os.path.relpath(p, root)] = ("f", sha(p), os.stat(p).st_mode & 0o111 != 0)
    return out


class Proc:
    """Proces luxdrop se ctenim vystupu bez cekani na konec radku (vyzvy)."""

    def __init__(self, home, args, env_extra=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_") and not k.startswith("LUXDROP_")}
        if os.environ.get("LUXDROP_DEBUG"):
            env["LUXDROP_DEBUG"] = "1"
        env.update(HOME=home, LUXDROP_LIB=LIB, LANG="C.UTF-8", PYTHONUNBUFFERED="1", LUXDROP_NO_MULTICAST="1")
        env.update(env_extra or {})
        self.args = args
        self.p = subprocess.Popen([sys.executable, LAUNCHER] + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, env=env)
        self.buf = ""
        self.pos = 0
        self.lock = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        fd = self.p.stdout.fileno()
        while True:
            b = os.read(fd, 4096)
            if not b:
                return
            with self.lock:
                self.buf += b.decode("utf-8", "replace")

    def expect(self, pattern, timeout=20):
        """Ceka na vzor ve vystupu od posledni shody."""
        rx = re.compile(pattern)
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                m = rx.search(self.buf, self.pos)
                if m:
                    self.pos = m.end()
                    return m
            if self.p.poll() is not None:
                time.sleep(0.2)
                with self.lock:
                    m = rx.search(self.buf, self.pos)
                    if m:
                        self.pos = m.end()
                        return m
                raise AssertionError("process exited (%s) before %r; output:\n%s" % (self.p.returncode, pattern, self.buf))
            time.sleep(0.05)
        raise AssertionError("timeout waiting for %r; output:\n%s" % (pattern, self.buf))

    def send(self, line):
        self.p.stdin.write((line + "\n").encode())
        self.p.stdin.flush()

    def wait(self, timeout=60):
        return self.p.wait(timeout)

    def stop(self):
        if self.p.poll() is None:
            self.p.send_signal(signal.SIGINT)
            try:
                self.p.wait(5)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait()
        for f in (self.p.stdin, self.p.stdout):
            try:
                f.close()
            except OSError:
                pass


class LuxDropIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="luxdrop-it-")
        cls.homes = {}
        for k, name in (("A", "Alice-PC"), ("B", "Bob-PC"), ("C", "Carol-PC"), ("M", "Bob-PC")):
            h = os.path.join(cls.root, k)
            os.makedirs(os.path.join(h, ".config", "luxdrop"))
            with open(os.path.join(h, ".config", "luxdrop", "settings.json"), "w") as f:
                json.dump({"name": name, "download_dir": os.path.join(h, "Downloads")}, f)
            cls.homes[k] = h
        cls.ports = {k: free_port() for k in cls.homes}
        cls.procs = []
        # Testovaci data
        src = os.path.join(cls.root, "src")
        os.makedirs(os.path.join(src, "Projekt", "deep", "deeper"))
        os.makedirs(os.path.join(src, "Projekt", "empty-dir"))
        cls.write(os.path.join(src, "zprava.txt"), b"Ahoj z LuxOS\n")
        cls.write(os.path.join(src, "Projekt", "README.md"), b"# test\n")
        cls.write(os.path.join(src, "Projekt", "deep", "deeper", "data.bin"), os.urandom(3 * 1024 * 1024 + 17))
        cls.write(os.path.join(src, "Projekt", "deep", "Žluťoučký kůň.txt"), "příliš".encode())
        cls.write(os.path.join(src, "Projekt", "empty.txt"), b"")
        cls.write(os.path.join(src, "Projekt", "run.sh"), b"#!/bin/sh\necho hi\n")
        os.chmod(os.path.join(src, "Projekt", "run.sh"), 0o755)
        os.symlink("/etc/passwd", os.path.join(src, "Projekt", "passwd-link"))
        cls.write(os.path.join(src, "big.img"), os.urandom(48 * 1024 * 1024))
        cls.src = src

    @staticmethod
    def write(path, data):
        with open(path, "wb") as f:
            f.write(data)

    @classmethod
    def tearDownClass(cls):
        for p in cls.procs:
            p.stop()
        if os.environ.get("LUXDROP_KEEP"):
            print("kept", cls.root)
        else:
            shutil.rmtree(cls.root, ignore_errors=True)

    def tearDown(self):
        for p in self.procs:
            p.stop()
        self.procs.clear()

    # --- pomocne ------------------------------------------------------------

    def set_name(self, who, name):
        with open(os.path.join(self.homes[who], ".config", "luxdrop", "settings.json"), "w") as f:
            json.dump({"name": name, "download_dir": os.path.join(self.homes[who], "Downloads")}, f)

    def receiver(self, who, mode):
        p = Proc(self.homes[who], ["receive", "--bind", "127.0.0.1", "--port", str(self.ports[who]),
                                   "--mode", mode, "--no-mdns", "--ls-port", "0"])
        self.procs.append(p)
        p.expect(r"Receiving as")
        return p

    def sender(self, who, target, files, env=None):
        p = Proc(self.homes[who], ["send", target] + files, env)
        self.procs.append(p)
        return p

    def addr(self, who):
        return "127.0.0.1:%d" % self.ports[who]

    def dl(self, who, *rel):
        return os.path.join(self.homes[who], "Downloads", *rel)

    def trusted(self, who):
        try:
            with open(os.path.join(self.homes[who], ".local", "share", "luxdrop", "trusted.json")) as f:
                return {v["name"]: k for k, v in json.load(f).items()}
        except OSError:
            return {}

    def ident(self, who):
        return identity.Identity.load_or_create(os.path.join(self.homes[who], ".local", "share", "luxdrop"))

    # --- scenare (v poradi) ---------------------------------------------------

    def test_01_pairing_with_sas(self):
        rb = self.receiver("B", "everyone")
        s = self.sender("A", self.addr("B"), [os.path.join(self.src, "zprava.txt")])
        code_a = s.expect(r"Verification code: (\d{3} \d{3})").group(1)
        code_b = rb.expect(r"Verification code: (\d{3} \d{3})").group(1)
        print("\n   SAS sender=%s receiver=%s" % (code_a, code_b))
        self.assertEqual(code_a, code_b)
        s.expect(r"\[N\]o: ")
        s.send("y")
        rb.expect(r"\[N\]o: ")
        rb.send("a")  # prijmout a duverovat
        self.assertEqual(s.wait(), 0, s.buf)
        rb.expect(r"Received from Alice-PC")
        self.assertEqual(sha(self.dl("B", "zprava.txt")), sha(os.path.join(self.src, "zprava.txt")))
        self.assertIn("Bob-PC", self.trusted("A"))
        self.assertIn("Alice-PC", self.trusted("B"))
        self.assertEqual(self.trusted("A")["Bob-PC"], self.ident("B").fp.hex())
        self.assertEqual(self.trusted("B")["Alice-PC"], self.ident("A").fp.hex())
        rb.stop()

    def test_02_folder_trusted_no_prompt(self):
        rb = self.receiver("B", "trusted")
        s = self.sender("A", "Bob-PC@" + self.addr("B"), [os.path.join(self.src, "Projekt")])
        self.assertEqual(s.wait(), 0, s.buf)
        self.assertNotIn("Verification code", s.buf)
        self.assertIn("Skipped", s.buf)  # symlink uvnitr slozky se neposila
        rb.expect(r"Received from Alice-PC")
        self.assertNotIn("Accept?", rb.buf)
        want = tree(os.path.join(self.src, "Projekt"))
        got = tree(self.dl("B", "Projekt"))
        self.assertEqual(got, want)
        self.assertFalse(os.path.lexists(self.dl("B", "Projekt", "passwd-link")))
        self.assertTrue(os.access(self.dl("B", "Projekt", "run.sh"), os.X_OK))
        print("\n   folder: %d entries identical (sha256 + exec bit), symlink skipped" % len(got))
        # Druhe odeslani nic neprepise
        s = self.sender("A", "Bob-PC@" + self.addr("B"), [os.path.join(self.src, "zprava.txt")])
        self.assertEqual(s.wait(), 0, s.buf)
        rb.expect(r"Received from Alice-PC")
        self.assertTrue(os.path.exists(self.dl("B", "zprava (1).txt")))
        rb.stop()

    def test_03_cancel_and_resume(self):
        rb = self.receiver("B", "trusted")
        big = os.path.join(self.src, "big.img")
        s = self.sender("A", "Bob-PC@" + self.addr("B"), [big], env={"LUXDROP_TEST_RATE": str(8 * 1024 * 1024)})
        s.expect(r"Sending\s+\d+ %", timeout=30)
        time.sleep(1.5)
        s.p.send_signal(signal.SIGINT)  # zruseni odesilatelem
        self.assertEqual(s.wait(), 3, s.buf)
        self.assertIn("cancel", s.buf.lower())
        rb.expect(r"Transfer from Alice-PC failed: .*cancel")
        self.assertFalse(os.path.exists(self.dl("B", "big.img")))
        parts = os.listdir(self.dl("B", ".luxdrop-partial"))
        self.assertEqual(len(parts), 1)
        partial = os.path.getsize(self.dl("B", ".luxdrop-partial", parts[0]))
        print("\n   cancelled after %d of %d bytes" % (partial, os.path.getsize(big)))
        self.assertTrue(0 < partial < os.path.getsize(big))
        # Navazani
        s = self.sender("A", "Bob-PC@" + self.addr("B"), [big])
        self.assertEqual(s.wait(), 0, s.buf)
        m = re.search(r"resumed, ([\d.]+ \w+) were already there", s.buf)
        self.assertIsNotNone(m, s.buf)
        print("   resumed: %s" % m.group(0))
        rb.expect(r"Received from Alice-PC")
        self.assertEqual(sha(self.dl("B", "big.img")), sha(big))
        self.assertFalse(os.path.exists(self.dl("B", ".luxdrop-partial")))
        rb.stop()

    def test_04_receiver_cancel(self):
        rb = self.receiver("B", "trusted")
        s = self.sender("A", "Bob-PC@" + self.addr("B"), [os.path.join(self.src, "big.img")],
                        env={"LUXDROP_TEST_RATE": str(8 * 1024 * 1024)})
        s.expect(r"Sending\s+\d+ %", timeout=30)
        time.sleep(1)
        rb.p.kill()  # prijemce zmizi uprostred prenosu
        rb.p.wait()
        rc = s.wait()
        self.assertEqual(rc, 1, s.buf)
        self.assertIn("Transfer failed", s.buf)
        print("\n   sender after receiver abort: %s" % s.buf.strip().splitlines()[-1])
        self.assertFalse(os.path.exists(self.dl("B", "big (1).img")))

    def test_05_mitm_pinned_key_mismatch(self):
        rm = self.receiver("M", "everyone")  # utocnik "Bob-PC" s jinym klicem
        s = self.sender("A", "Bob-PC@" + self.addr("M"), [os.path.join(self.src, "zprava.txt")])
        self.assertEqual(s.wait(), 4, s.buf)
        self.assertIn("key_mismatch", s.buf)
        self.assertNotIn("Verification code", s.buf)
        time.sleep(0.5)
        self.assertNotIn("wants to send", rm.buf)  # utocnik nedostal ani nabidku
        self.assertFalse(os.path.exists(self.dl("M")))
        print("\n   " + [l for l in s.buf.splitlines() if "key_mismatch" in l][0])
        # Podvrzena adresa duveryhodneho zarizeni (napr. prevzata IP): stejny vysledek
        tpath = os.path.join(self.homes["A"], ".local", "share", "luxdrop", "trusted.json")
        with open(tpath) as f:
            data = json.load(f)
        bob = self.ident("B")
        data[bob.fp.hex()]["last_addr"] = self.addr("M")
        with open(tpath, "w") as f:
            json.dump(data, f)
        s = self.sender("A", bob.id, [os.path.join(self.src, "zprava.txt")])
        self.assertEqual(s.wait(), 4, s.buf)
        self.assertIn("key_mismatch", s.buf)
        rm.stop()

    def test_06_unknown_sender_trusted_only(self):
        rb = self.receiver("B", "trusted")
        s = self.sender("C", self.addr("B"), [os.path.join(self.src, "zprava.txt")])
        rc = s.wait()
        self.assertNotEqual(rc, 0)
        self.assertIn("not_trusted", s.buf)
        time.sleep(0.5)
        self.assertNotIn("Accept?", rb.buf)
        self.assertIn("not_trusted", rb.buf)
        # Utocnik se jmenem "Alice-PC" (duveryhodne jmeno) ale jinym klicem -> take odmitnut
        self.set_name("M", "Alice-PC")
        s = self.sender("M", self.addr("B"), [os.path.join(self.src, "zprava.txt")])
        self.assertNotEqual(s.wait(), 0)
        self.assertIn("not_trusted", s.buf)
        print("\n   " + [l for l in s.buf.splitlines() if "not_trusted" in l][0])
        rb.stop()

    def test_07_name_clash_warning_and_sas_rejected(self):
        rb = self.receiver("B", "everyone")
        self.set_name("M", "Alice-PC")
        s = self.sender("M", self.addr("B"), [os.path.join(self.src, "zprava.txt")])
        rb.expect(r"WARNING: this device uses the name of a trusted device")
        s.expect(r"\[N\]o: ")
        s.send("n")  # odesilatel nepotvrdi kod
        self.assertEqual(s.wait(), 1, s.buf)
        self.assertIn("sas_rejected", s.buf)
        rb.expect(r"The sender cancelled the request")  # vyzva u prijemce zmizi sama
        self.assertFalse(os.path.exists(self.dl("B", "zprava (2).txt")))
        rb.stop()

    def test_08_receiver_declines(self):
        rb = self.receiver("B", "everyone")
        s = self.sender("C", self.addr("B"), [os.path.join(self.src, "zprava.txt")])
        rb.expect(r"\[N\]o: ")
        rb.send("n")
        self.assertEqual(s.wait(), 3, s.buf)
        self.assertIn("declined", s.buf)
        self.assertFalse(os.path.exists(self.dl("B", "zprava (2).txt")))
        self.assertNotIn("Carol-PC", self.trusted("B"))
        rb.stop()

    # --- zlomyslny odesilatel (primo pres knihovnu) -----------------------------

    def raw_session(self, who_sender, who_receiver, offer):
        """Projde handshake jako who_sender a posle libovolnou nabidku; vrati (kanal, odpoved)."""
        me = self.ident(who_sender)
        raw = socket.create_connection(("127.0.0.1", self.ports[who_receiver]), timeout=10)
        tls = transfer.client_context().wrap_socket(raw)
        fp_s, _ = identity.cert_fingerprint(tls.getpeercert(binary_form=True))
        ch = proto.Channel(tls)
        nc = os.urandom(32)
        ch.send({"type": "hello", "proto": 1, "name": "Alice-PC", "id": me.id,
                 "cert": base64.b64encode(me.cert_der).decode(), "commit": proto.commit(nc).hex()})
        ns = bytes.fromhex(ch.recv_msg("hello")["nonce"])
        ch.send({"type": "auth", "nonce": nc.hex(),
                 "sig": base64.b64encode(me.sign(proto.auth_message(fp_s, me.fp, ns, nc))).decode()})
        ch.recv_msg("auth_ok")
        ch.send(offer)
        try:
            return ch, ch.recv_msg("accept", "reject")
        except proto.ProtocolError as e:
            return ch, {"type": "error", "code": e.code, "message": e.message}

    def test_09_path_traversal_rejected(self):
        rb = self.receiver("B", "trusted")
        for evil in ("../escape.txt", "/tmp/abs.txt", "a/../../x", "ok/../../../etc/x", "a\\..\\b"):
            _ch, r = self.raw_session("A", "B", {"type": "offer", "files": [
                {"path": evil, "size": 4, "sha256": hashlib.sha256(b"evil").hexdigest()}], "dirs": []})
            _ch.sock.close()
            self.assertEqual(r.get("code"), "invalid_offer", (evil, r))
        self.assertFalse(os.path.exists(os.path.join(self.homes["B"], "escape.txt")))
        print("\n   traversal offers rejected with invalid_offer")
        rb.stop()

    def test_10_tampered_data_rejected(self):
        rb = self.receiver("B", "trusted")
        good = b"original content"
        ch, r = self.raw_session("A", "B", {"type": "offer", "files": [
            {"path": "tampered.txt", "size": len(good), "sha256": hashlib.sha256(good).hexdigest()}], "dirs": []})
        self.assertEqual(r["type"], "accept")
        ch.send({"type": "file", "index": 0, "offset": 0})
        ch.send_data(b"ORIGINAL content")  # stejna delka, jiny obsah
        ch.send({"type": "end"})
        res = ch.recv_msg("result")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "hash_mismatch")
        ch.sock.close()
        rb.expect(r"hash_mismatch|checksum mismatch")
        self.assertFalse(os.path.exists(self.dl("B", "tampered.txt")))
        # Vic dat nez ohlaseno -> chyba protokolu, nic se neulozi
        ch, r = self.raw_session("A", "B", {"type": "offer", "files": [
            {"path": "over.txt", "size": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}], "dirs": []})
        ch.send({"type": "file", "index": 0, "offset": 0})
        ch.send_data(b"abcdef")
        with self.assertRaises(proto.ProtocolError):
            ch.recv_msg("result")
        ch.sock.close()
        self.assertFalse(os.path.exists(self.dl("B", "over.txt")))
        print("\n   tampered data -> hash_mismatch, oversize data -> protocol_error; nothing saved")
        rb.stop()

    def test_11_bad_signature_and_commit(self):
        rb = self.receiver("B", "everyone")
        me, other = self.ident("A"), self.ident("C")
        for case in ("wrong_key", "bad_commit"):
            raw = socket.create_connection(("127.0.0.1", self.ports["B"]), timeout=10)
            tls = transfer.client_context().wrap_socket(raw)
            fp_s, _ = identity.cert_fingerprint(tls.getpeercert(binary_form=True))
            ch = proto.Channel(tls)
            nc = os.urandom(32)
            commit = proto.commit(nc if case != "bad_commit" else os.urandom(32))
            ch.send({"type": "hello", "proto": 1, "name": "x", "cert": base64.b64encode(me.cert_der).decode(),
                     "commit": commit.hex()})
            ns = bytes.fromhex(ch.recv_msg("hello")["nonce"])
            signer = other if case == "wrong_key" else me  # cizi certifikat bez klice = vydavani se za A
            ch.send({"type": "auth", "nonce": nc.hex(),
                     "sig": base64.b64encode(signer.sign(proto.auth_message(fp_s, me.fp, ns, nc))).decode()})
            with self.assertRaises(proto.ProtocolError) as cm:
                ch.recv_msg("auth_ok")
            self.assertEqual(cm.exception.code, "auth_failed")
            tls.close()
        print("\n   impersonation with stolen certificate / broken commitment -> auth_failed")
        rb.stop()

    def test_12_tls_only_13_and_no_plaintext(self):
        rb = self.receiver("B", "everyone")
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        with self.assertRaises(ssl.SSLError):
            ctx.wrap_socket(socket.create_connection(("127.0.0.1", self.ports["B"]), timeout=5))
        # Prosty text misto TLS
        s = socket.create_connection(("127.0.0.1", self.ports["B"]), timeout=5)
        s.sendall(proto.encode_json({"type": "hello", "proto": 1}))
        try:
            data = s.recv(100)
        except ConnectionResetError:
            data = b""
        self.assertNotIn(b"hello", data)
        s.close()
        print("\n   TLS 1.2 and plaintext connections refused")
        rb.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
