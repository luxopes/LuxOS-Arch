#!/usr/bin/env python3
"""LuxDrop - end-to-end testy protokolu LocalSend: procesy luxdrop na 127.0.0.1 (oddelene HOME).

A = "Alice-PC" (odesilatel), B = "Bob-PC" (prijemce). Volitelne interop s oficialni
implementaci LocalSend (Rust crate packages/core) pres harness "lsinterop"
(cesta v LSINTEROP, jinak ~/.cache/luxdrop-interop/target/debug/examples/lsinterop).

Spusteni (z adresare packages/luxdrop): python3 tests/test_localsend_e2e.py -v
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_integration import LIB, Proc, free_port, sha, tree  # noqa: E402

sys.path.insert(0, LIB)
from luxdrop import identity, localsend, lsdiscovery, lshttp  # noqa: E402

INTEROP = os.environ.get("LSINTEROP", os.path.expanduser("~/.cache/luxdrop-interop/target/debug/examples/lsinterop"))
HAVE_INTEROP = os.access(INTEROP, os.X_OK)


class LocalSendE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="luxdrop-ls-")
        cls.homes = {}
        cls.ports = {}
        for who, name in (("A", "Alice-PC"), ("B", "Bob-PC")):
            h = os.path.join(cls.root, who)
            os.makedirs(os.path.join(h, ".config", "luxdrop"))
            cls.homes[who] = h
            cls.ports[who] = (free_port(), free_port())
            with open(os.path.join(h, ".config", "luxdrop", "settings.json"), "w") as f:
                json.dump({"name": name}, f)
        src = os.path.join(cls.root, "src")
        os.makedirs(os.path.join(src, "Fotky", "2024"))
        cls.write(os.path.join(src, "Fotky", "2024", "léto.jpg"), os.urandom(700 * 1024 + 3))
        cls.write(os.path.join(src, "Fotky", "poznámka.txt"), "ahoj".encode())
        cls.write(os.path.join(src, "doc.pdf"), os.urandom(123457))
        cls.write(os.path.join(src, "empty.bin"), b"")
        cls.write(os.path.join(src, "big.img"), os.urandom(24 * 1024 * 1024))
        cls.src = src
        cls.procs = []

    @classmethod
    def tearDownClass(cls):
        if os.environ.get("LUXDROP_KEEP"):
            print("kept", cls.root)
        else:
            shutil.rmtree(cls.root, ignore_errors=True)

    def tearDown(self):
        for p in self.procs:
            p.stop()
        self.procs.clear()

    @staticmethod
    def write(path, data):
        with open(path, "wb") as f:
            f.write(data)

    # --- pomocne ------------------------------------------------------------

    def dl(self, who, *rel):
        return os.path.join(self.homes[who], "Downloads", "LuxDrop", *rel)

    def clean_dl(self, who):
        shutil.rmtree(os.path.join(self.homes[who], "Downloads"), ignore_errors=True)

    def receiver(self, who="B", mode="everyone", extra=(), bind="127.0.0.1", multicast_port=None):
        lp, sp = self.ports[who]
        env = None
        mc = ["--no-multicast"]
        if multicast_port:
            env, mc = {"LUXDROP_NO_MULTICAST": "", "LUXDROP_LS_MCAST_PORT": str(multicast_port)}, []
        p = Proc(self.homes[who], ["receive", "--bind", bind, "--port", str(lp), "--ls-port", str(sp),
                                   "--mode", mode, "--no-mdns", "--pin", ""] + mc + list(extra), env)
        self.procs.append(p)
        p.expect(r"LocalSend: port \d+")
        return p

    def sender(self, files, who="A", to="B", extra=(), env=None):
        p = Proc(self.homes[who], ["send", "--localsend", "127.0.0.1:%d" % self.ports[to][1]] + list(extra)
                 + files, env)
        self.procs.append(p)
        return p

    def ident(self, who):
        return identity.Identity.load_or_create(os.path.join(self.homes[who], ".local", "share", "luxdrop"))

    def trusted(self, who):
        try:
            with open(os.path.join(self.homes[who], ".local", "share", "luxdrop", "trusted.json")) as f:
                return {v["name"]: v for v in json.load(f).values()}
        except OSError:
            return {}

    def client(self, who="A", to="B", expected=None):
        return lshttp.Client(self.ident(who), "127.0.0.1", self.ports[to][1], expected_fp=expected, timeout=10)

    def no_partials(self, who):
        part = self.dl(who, ".luxdrop-partial")
        return not os.path.isdir(part) or not os.listdir(part)

    # --- scenare --------------------------------------------------------------

    def test_01_files_and_folder(self):
        """LuxDrop -> LuxDrop pres LocalSend: soubory, slozka s diakritikou, prazdny soubor."""
        self.clean_dl("B")
        rb = self.receiver()
        s = self.sender([os.path.join(self.src, "Fotky"), os.path.join(self.src, "doc.pdf"),
                         os.path.join(self.src, "empty.bin")])
        rb.expect(r"Alice-PC \(ID [0-9a-f]{16}\) wants to send you 3 item\(s\)")
        rb.expect(r"Sent with LocalSend from a desktop device\n")  # overeny klientsky certifikat
        rb.expect(r"\[N\]o: ")
        rb.send("y")
        rb.expect(r"Received from Alice-PC")
        self.assertEqual(s.wait(30), 0)
        got = tree(self.dl("B"))
        want = {k: v[:2] for k, v in tree(self.src).items() if not k.startswith("big")}
        self.assertEqual({k: v[:2] for k, v in got.items()}, want)
        self.assertTrue(self.no_partials("B"))
        print("\n   %d entries identical (sha256), folder structure kept" % len(got))

    def test_02_text_message(self):
        rb = self.receiver()
        s = self.sender([], extra=["--text", "Ahoj Bobe, posílám odkaz https://lux-ai.cz"])
        rb.expect(r"Message from Alice-PC:\nAhoj Bobe, posílám odkaz https://lux-ai.cz")
        self.assertEqual(s.wait(20), 0)

    def test_03_decline(self):
        self.clean_dl("B")
        rb = self.receiver()
        s = self.sender([os.path.join(self.src, "doc.pdf")])
        rb.expect(r"\[N\]o: ")
        rb.send("n")
        self.assertEqual(s.wait(20), 3)
        s.expect(r"declined")
        self.assertFalse(os.path.exists(self.dl("B", "doc.pdf")))

    def test_04_pin(self):
        rb = self.receiver(extra=["--pin", "4711"])
        s = self.sender([os.path.join(self.src, "doc.pdf")], extra=["--pin", "0000"])
        s.expect(r"Wrong PIN")
        s.expect(r"requires a PIN: ")
        s.send("4711")
        rb.expect(r"\[N\]o: ")
        rb.send("y")
        self.assertEqual(s.wait(30), 0)
        # 3 spatne pokusy -> 429 (zablokovano)
        c = self.client()
        codes = []
        for pin in ("1", "2", "3", "4711"):
            st, _o = c.request_json("POST", localsend.API + "/prepare-upload", self.offer([("x", 1)]),
                                    query={"pin": pin})
            codes.append(st)
        c.close()
        self.assertEqual(codes, [401, 401, 401, 429])
        print("\n   PIN: wrong pins -> %s" % codes)

    def offer(self, files, alias="Raw"):
        return {"info": localsend.my_info(alias, "X", 1), "files": {
            "f%d" % i: {"id": "f%d" % i, "fileName": n, "size": sz, "fileType": "application/octet-stream"}
            for i, (n, sz) in enumerate(files)}}

    def test_05_trusted_only_and_quick_save(self):
        self.clean_dl("B")
        # Rezim "jen duveryhodna": cizi zarizeni se odmitne bez dotazu
        rb = self.receiver(mode="trusted")
        s = self.sender([os.path.join(self.src, "doc.pdf")])
        self.assertEqual(s.wait(20), 3)
        rb.stop()
        # Prijmout a duverovat ("a") -> pripne se klic odesilatele (mTLS)
        rb = self.receiver()
        s = self.sender([os.path.join(self.src, "doc.pdf")])
        rb.expect(r"\[a\]ccept and trust this device / \[N\]o: ")
        rb.send("a")
        self.assertEqual(s.wait(30), 0)
        t = self.trusted("B")["Alice-PC"]
        self.assertEqual(t["kind"], "localsend")
        self.assertEqual(t["cert_fp"], localsend.cert_fingerprint(self.ident("A").cert_der))
        rb.stop()
        # Duveryhodne + rychle ulozeni -> bez dotazu i v rezimu "trusted"
        rb = self.receiver(mode="trusted")
        s = self.sender([os.path.join(self.src, "empty.bin")])
        self.assertEqual(s.wait(30), 0)
        rb.expect(r"Received from Alice-PC")
        self.assertNotIn("Accept?", rb.buf[rb.buf.rfind("LocalSend: port"):])
        self.assertTrue(os.path.exists(self.dl("B", "empty.bin")))
        # Jiny klic se stejnym jmenem neni duveryhodny (impersonace)
        mallory = tempfile.mkdtemp(dir=self.root)
        os.makedirs(os.path.join(mallory, ".config", "luxdrop"))
        with open(os.path.join(mallory, ".config", "luxdrop", "settings.json"), "w") as f:
            json.dump({"name": "Alice-PC"}, f)
        m = Proc(mallory, ["send", "--localsend", "127.0.0.1:%d" % self.ports["B"][1],
                           os.path.join(self.src, "doc.pdf")])
        self.procs.append(m)
        self.assertEqual(m.wait(20), 3)  # trusted mode -> 403
        print("\n   untrusted rejected silently, 'accept and trust' pinned the key, quick save worked, "
              "same name with another key rejected")
        os.unlink(os.path.join(self.homes["B"], ".local", "share", "luxdrop", "trusted.json"))

    def test_06_malicious_offers(self):
        self.clean_dl("B")
        rb = self.receiver()
        c = self.client()
        bad = ["../evil.txt", "a/../../evil.txt", "/etc/passwd", "~/x", "..\\..\\x"]
        codes = []
        for name in bad:
            st, obj = c.request_json("POST", localsend.API + "/prepare-upload", self.offer([(name, 3)]))
            codes.append(st)
        self.assertEqual(codes, [400] * len(bad))
        st, _o = c.request_json("POST", localsend.API + "/prepare-upload", self.offer([("x", -5)]))
        self.assertEqual(st, 400)
        st, _o = c.request_json("POST", localsend.API + "/prepare-upload", self.offer([("x", 1 << 52)]))
        self.assertEqual(st, 507)  # nedostatek mista
        c.close()

        # Prijata nabidka: spatny token, prilis mnoho dat, spatny SHA-256
        sha_ok = hashlib.sha256(b"good").hexdigest()
        body = self.offer([("good.txt", 4), ("big.txt", 4), ("hash.txt", 4), ("nfd.txt", 4)])
        body["files"]["f0"]["sha256"] = sha_ok
        body["files"]["f2"]["sha256"] = sha_ok
        body["files"]["f3"]["fileName"] = unicodedata.normalize("NFD", "Zvířátka/kůň.txt")
        res = {}

        def prep():
            cc = self.client()
            res["v"] = cc.request_json("POST", localsend.API + "/prepare-upload", body)
            cc.close()
        th = threading.Thread(target=prep)
        th.start()
        rb.expect(r"\[N\]o: ")
        rb.send("y")
        th.join(20)
        st, obj = res["v"]
        self.assertEqual(st, 200)
        sid, tok = obj["sessionId"], obj["files"]

        def up(fid, data, token=None, sid_=None):
            cc = self.client()
            try:
                return cc.upload(localsend.API + "/upload", {"sessionId": sid_ or sid, "fileId": fid,
                                                             "token": token or tok[fid]}, len(data), [data])[0]
            finally:
                cc.close()

        # Druha nabidka behem relace -> 409
        cc = self.client()
        self.assertEqual(cc.request_json("POST", localsend.API + "/prepare-upload", self.offer([("z", 1)]))[0], 409)
        cc.close()
        self.assertEqual(up("f0", b"good", token="wrong"), 403)
        self.assertEqual(up("f0", b"good", sid_="other"), 403)
        self.assertEqual(up("f1", b"too long data"), 400)
        self.assertEqual(up("f2", b"evil"), 422)
        self.assertEqual(up("f0", b"good"), 200)
        self.assertEqual(up("f0", b"good"), 403)  # token uz pouzit
        self.assertEqual(up("f3", b"nfd!"), 200)
        rb.expect(r"Transfer from Raw failed")
        files = sorted(os.path.relpath(os.path.join(dp, f), self.dl("B")) for dp, _d, fs in os.walk(self.dl("B"))
                       for f in fs)
        self.assertEqual(files, ["Zvířátka/kůň.txt", "good.txt"])
        self.assertTrue(self.no_partials("B"))
        # Nic mimo cilovou slozku
        self.assertFalse(os.path.exists(os.path.join(self.homes["B"], "Downloads", "evil.txt")))
        print("\n   traversal/absolute names -> 400, wrong token/session -> 403, oversize -> 400, "
              "bad sha256 -> 422, nothing partial left")

    def test_07_sender_cancel(self):
        self.clean_dl("B")
        rb = self.receiver()
        s = self.sender([os.path.join(self.src, "big.img")], env={"LUXDROP_TEST_RATE": str(4 * 1024 * 1024)})
        rb.expect(r"\[N\]o: ")
        rb.send("y")
        s.expect(r"Sending\s+\d+ %", timeout=30)
        time.sleep(1.5)
        s.p.send_signal(2)  # Ctrl+C
        self.assertEqual(s.wait(20), 3)
        rb.expect(r"Transfer from Alice-PC failed: .*cancel|cancelled")
        time.sleep(0.5)
        self.assertFalse(os.path.exists(self.dl("B", "big.img")))
        self.assertTrue(self.no_partials("B"))
        # Po zruseni je misto pro dalsi relaci
        s = self.sender([os.path.join(self.src, "doc.pdf")])
        rb.expect(r"\[N\]o: ")
        rb.send("y")
        self.assertEqual(s.wait(30), 0)

    def test_08_pinning(self):
        rb = self.receiver()
        real = localsend.cert_fingerprint(self.ident("B").cert_der)
        c = self.client(expected=real)
        st, obj = c.request_json("POST", localsend.API + "/register", localsend.my_info("A", "X", 1))
        self.assertEqual(st, 200)
        self.assertEqual(obj["fingerprint"], real)
        self.assertEqual(c.fingerprint, real)
        c.close()
        with self.assertRaises(lshttp.PinError):
            self.client(expected="00" * 32).connect()
        # Info (GET v1 i v2)
        for path in ("/api/localsend/v2/info", "/api/localsend/v1/info"):
            c = self.client()
            st, obj = c.request_json("GET", path)
            c.close()
            self.assertEqual((st, obj["alias"], obj["deviceType"]), (200, "Bob-PC", "desktop"))
        rb.stop()

    def test_09_discovery_register(self):
        """Objevovani: /register oboustranne + hledani podle jmena pres multicast (pokud jde)."""
        rb = self.receiver()
        got = []
        d = lsdiscovery.LocalSendDiscovery(self.ident("A"), lambda: localsend.my_info(
            "Alice-PC", localsend.cert_fingerprint(self.ident("A").cert_der), 1), on_change=lambda: got.append(1),
            multicast=False)
        self.assertTrue(d.probe("127.0.0.1", self.ports["B"][1]))
        dev = d.list()[0]
        self.assertEqual((dev["name"], dev["verified"]), ("Bob-PC", True))
        self.assertEqual(dev["fingerprint"], localsend.cert_fingerprint(self.ident("B").cert_der))
        self.assertEqual(dev["luxdrop"]["port"], self.ports["B"][0])  # LuxOS se pozna
        self.assertFalse(d.probe("127.0.0.1", free_port(), timeout=1))
        # Scan /24 jen soukrome site, ne loopback
        self.assertEqual(lsdiscovery.scan_targets([("lo", "127.0.0.1", "255.0.0.0")]), [])
        t = lsdiscovery.scan_targets([("eth0", "192.168.7.20", "255.255.255.0")])
        self.assertEqual((len(t), "192.168.7.20" in t, t[0], t[-1]), (253, False, "192.168.7.1", "192.168.7.254"))
        self.assertEqual(lsdiscovery.scan_targets([("wan", "8.8.8.8", "255.255.255.0")]), [])
        rb.stop()

    def test_10_multicast(self):
        """Multicast oznameni mezi dvema instancemi na tomto pocitaci (IP_MULTICAST_LOOP)."""
        ifs = lsdiscovery.interfaces()
        if not ifs:
            self.skipTest("no non-loopback IPv4 interface for multicast")
        port = free_port()
        os.environ["LUXDROP_LS_MCAST_PORT"] = str(port)
        try:
            rb = self.receiver(bind="0.0.0.0")  # server B (register od A na adresu rozhrani)
            ida, idb = self.ident("A"), self.ident("B")
            fa, fb = localsend.cert_fingerprint(ida.cert_der), localsend.cert_fingerprint(idb.cert_der)
            da = lsdiscovery.LocalSendDiscovery(ida, lambda: localsend.my_info("Alice-PC", fa, 1), port=port)
            db = lsdiscovery.LocalSendDiscovery(idb, lambda: localsend.my_info("Bob-PC", fb, self.ports["B"][1]),
                                                port=port)
            if not (da.start() and db.start()):
                self.skipTest("multicast not available: %s %s" % (da.error, db.error))
            try:
                db.announce()  # A uslysi B a overi ho pres /register na jeho server
                end = time.time() + 6
                while time.time() < end and not da.list():
                    time.sleep(0.1)
                devs = da.list()
                if not devs:
                    self.skipTest("multicast datagrams are not delivered on this host")
                self.assertEqual(devs[0]["name"], "Bob-PC")
                self.assertTrue(devs[0]["verified"])
                print("\n   multicast: Alice found %s via %s (verified by /register)" % (devs[0]["name"],
                                                                                         devs[0]["host"]))
            finally:
                da.stop()
                db.stop()
            rb.stop()
        finally:
            os.environ.pop("LUXDROP_LS_MCAST_PORT", None)


@unittest.skipUnless(HAVE_INTEROP, "LocalSend interop harness not built (see tests/README in the report)")
class OfficialInterop(unittest.TestCase):
    """Oficialni LocalSend (Rust crate localsend, mTLS, rustls) <-> LuxDrop."""

    setUpClass = classmethod(LocalSendE2E.setUpClass.__func__)
    tearDownClass = classmethod(LocalSendE2E.tearDownClass.__func__)
    tearDown = LocalSendE2E.tearDown
    write = LocalSendE2E.write
    receiver = LocalSendE2E.receiver
    sender = LocalSendE2E.sender
    dl = LocalSendE2E.dl
    clean_dl = LocalSendE2E.clean_dl
    ident = LocalSendE2E.ident
    trusted = LocalSendE2E.trusted
    no_partials = LocalSendE2E.no_partials

    def run_interop(self, args, timeout=60):
        return subprocess.run([INTEROP] + args, capture_output=True, text=True, timeout=timeout)

    def start_interop_rx(self, port, out, extra=()):
        p = subprocess.Popen([INTEROP, "receive", str(port), out, "--timeout", "60"] + list(extra),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = []
        end = time.time() + 30
        while time.time() < end:
            line = p.stdout.readline()
            lines.append(line)
            if line.startswith("LISTENING"):
                return p, lines
        p.kill()
        self.fail("interop receiver did not start: %s" % "".join(lines))

    def test_official_sends_to_luxdrop(self):
        self.clean_dl("B")
        rb = self.receiver()
        doc = os.path.join(self.src, "doc.pdf")
        jpg = os.path.join(self.src, "Fotky", "2024", "léto.jpg")
        res = {}
        th = threading.Thread(target=lambda: res.setdefault("r", self.run_interop(
            ["send", "127.0.0.1", str(self.ports["B"][1]), doc, jpg + "=Fotky/2024/léto.jpg"])))
        th.start()
        rb.expect(r"LocalSend Interop \(ID [0-9a-f]{16}\) wants to send you 2 item", timeout=60)
        rb.expect(r"Sent with LocalSend from a mobile device\n")  # mTLS overeno
        rb.expect(r"\[N\]o: ")
        rb.send("y")
        th.join(60)
        out = res["r"].stdout
        self.assertIn("PREPARE 200", out, out)
        self.assertEqual(out.count(" ok"), 2, out)
        rb.expect(r"Received from LocalSend Interop")
        self.assertEqual(sha(self.dl("B", "doc.pdf")), sha(doc))
        self.assertEqual(sha(self.dl("B", "Fotky", "2024", "léto.jpg")), sha(jpg))
        # Otisk z /register = certifikat serveru LuxDrop
        fp = localsend.cert_fingerprint(self.ident("B").cert_der)
        self.assertIn("REGISTER Bob-PC %s" % fp, out)
        print("\n   official LocalSend -> LuxDrop: 2 files OK, fingerprint %s… verified by rustls pinning" % fp[:16])

    def test_official_text_and_pin_and_decline(self):
        rb = self.receiver(extra=["--pin", "2468"])
        r = self.run_interop(["send", "--text", "Zpráva z LocalSend", "127.0.0.1", str(self.ports["B"][1])])
        self.assertIn("PREPARE_ERROR 401", r.stdout, r.stdout)  # bez PINu
        r = self.run_interop(["send", "--pin", "2468", "--text", "Zpráva z LocalSend", "127.0.0.1",
                              str(self.ports["B"][1])])
        self.assertIn("PREPARE 204", r.stdout, r.stdout)
        rb.expect(r"Message from LocalSend Interop:\nZpráva z LocalSend")
        res = {}
        th = threading.Thread(target=lambda: res.setdefault("r", self.run_interop(
            ["send", "--pin", "2468", "127.0.0.1", str(self.ports["B"][1]), os.path.join(self.src, "doc.pdf")])))
        th.start()
        rb.expect(r"\[N\]o: ", timeout=60)
        rb.send("n")
        th.join(60)
        self.assertIn("PREPARE_ERROR 403", res["r"].stdout, res["r"].stdout)

    def test_luxdrop_sends_to_official(self):
        out = os.path.join(self.root, "interop-out")
        os.makedirs(out, exist_ok=True)
        port = free_port()
        p, lines = self.start_interop_rx(port, out)
        try:
            s = Proc(self.homes["A"], ["send", "--localsend", "127.0.0.1:%d" % port,
                                       os.path.join(self.src, "Fotky"), os.path.join(self.src, "doc.pdf")])
            self.procs.append(s)
            self.assertEqual(s.wait(60), 0, s.buf)
        finally:
            try:
                rest, _e = p.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()
                rest, _e = p.communicate()
        log = "".join(lines) + rest
        fa = localsend.cert_fingerprint(self.ident("A").cert_der)
        self.assertIn("REGISTERED Alice-PC 127.0.0.1 %s" % fa, log)  # rustls overil mTLS otisk
        self.assertIn("OFFER Alice-PC certfp=%s files=3" % fa, log)
        self.assertEqual(log.count("Ok(true)"), 3, log)
        self.assertEqual(sha(os.path.join(out, "doc.pdf")), sha(os.path.join(self.src, "doc.pdf")))
        self.assertEqual(sha(os.path.join(out, "Fotky__2024__léto.jpg")),
                         sha(os.path.join(self.src, "Fotky", "2024", "léto.jpg")))
        print("\n   LuxDrop -> official LocalSend: folder + file OK, our ECDSA client certificate accepted (mTLS)")

    def test_luxdrop_text_to_official(self):
        port = free_port()
        out = os.path.join(self.root, "interop-out2")
        os.makedirs(out, exist_ok=True)
        p, lines = self.start_interop_rx(port, out)
        t = Proc(self.homes["A"], ["send", "--localsend", "--text", "Ahoj z LuxOS", "127.0.0.1:%d" % port])
        self.procs.append(t)
        self.assertEqual(t.wait(60), 0, t.buf)
        try:
            rest, _e = p.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
            rest, _e = p.communicate()
        log = "".join(lines) + rest
        self.assertRegex(log, r"OFFER Alice-PC certfp=\w+ files=1")
        texts = []
        for f in os.listdir(out):
            with open(os.path.join(out, f), encoding="utf-8") as fh:
                texts.append(fh.read())
        self.assertIn("Ahoj z LuxOS", texts, log)

    def test_official_multicast_discovery(self):
        """Oficialni multicast + /register: oba se navzajem najdou (na vlastnim UDP portu)."""
        if not lsdiscovery.interfaces():
            self.skipTest("no non-loopback IPv4 interface for multicast")
        mport, hport = free_port(), free_port()
        p = subprocess.Popen([INTEROP, "discover", str(hport), str(mport), "12"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True)
        lines = []
        while True:
            line = p.stdout.readline()
            lines.append(line)
            if not line or line.startswith("LISTENING"):
                break
        rb = self.receiver(bind="0.0.0.0", multicast_port=mport)
        rest, _e = p.communicate(timeout=40)
        rb.stop()
        log = "".join(lines) + rest
        if "MULTICAST_ERROR" in log:
            self.skipTest("multicast not available for the official implementation")
        fb = localsend.cert_fingerprint(self.ident("B").cert_der)
        # Oni slysi nase oznameni a overi nas pres /register (pripnuty otisk) ...
        self.assertIn("DISCOVERED Bob-PC %s" % fb, log, log[-2000:])
        # ... a my odpovidame na jejich oznameni registraci u jejich serveru (mTLS otisk sedi)
        self.assertIn("REGISTERED Bob-PC", log, log[-2000:])
        print("\n   official multicast discovery: both directions OK")

    def test_official_decline(self):
        port = free_port()
        out = os.path.join(self.root, "interop-out3")
        os.makedirs(out, exist_ok=True)
        p, _lines = self.start_interop_rx(port, out, ["--decline"])
        s = Proc(self.homes["A"], ["send", "--localsend", "127.0.0.1:%d" % port, os.path.join(self.src, "doc.pdf")])
        self.procs.append(s)
        self.assertEqual(s.wait(60), 3, s.buf)
        s.expect(r"declined")
        p.kill()
        p.communicate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
