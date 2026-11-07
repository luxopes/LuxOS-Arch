"""Velci poskytovatele: rozpoznani (Google i Workspace podle MX, Microsoft, Seznam), Gmail s heslem aplikace,
srozumitelna chyba pri normalnim hesle Google ([ALERT] Application-specific password required), Microsoft
bez prihlaseni heslem, slozky Gmailu (SPECIAL-USE, "All Mail" se nestahuje) a druhy ucet vedle prvniho.

Jen mistni testovaci servery: ISPDB z fixtures/ispdb (stazene bez prihlaseni z autoconfig.thunderbird.net),
falesne DNS (LUXOS_MAIL_FAKE_DNS), falesny IMAP s --personality gmail/microsoft. Zadne spojeni ke Google
ani Microsoftu, zadna skutecna hesla.
"""
import http.server
import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailtest as mt  # noqa: E402
from test_service import inbox_rows  # noqa: E402

ISPDB_DIR = os.path.join(mt.FIXTURES, "ispdb")
GMAIL_USER = "tester@gmail.com"
APP_PASSWORD = "abcd efgh ijkl mnop"          # tvar hesla aplikace Google (16 pismen)
GOOGLE_PASSWORD = "Normalni-heslo-Google-1"   # normalni heslo uctu: Gmail ho pres IMAP odmitne


def ispdb_file(name):
    with open(os.path.join(ISPDB_DIR, name)) as f:
        return f.read()


class Handler(http.server.BaseHTTPRequestHandler):
    routes = {}

    def do_GET(self):
        body = Handler.routes.get(self.path.split("?")[0])
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/xml")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


class ProviderDiscoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.http.server_address[1]
        cls.tmp = tempfile.mkdtemp()
        gmail = ispdb_file("gmail.com.xml")
        Handler.routes = {"/ispdb/gmail.com": gmail, "/ispdb/googlemail.com": gmail, "/ispdb/google.com": gmail,
                          "/ispdb/outlook.com": ispdb_file("outlook.com.xml"), "/ispdb/seznam.cz": ispdb_file("seznam.cz.xml")}

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()

    def discover(self, email, dns=None):
        path = os.path.join(self.tmp, "dns.json")
        with open(path, "w") as f:
            json.dump(dns or {}, f)
        env = dict(os.environ, LUXOS_MAIL_FAKE_DNS=path,
                   LUXOS_MAIL_AUTOCONFIG_URLS=self.base + "/auto/%DOMAIN%",
                   LUXOS_MAIL_ISPDB_URL=self.base + "/ispdb/%DOMAIN%")
        r = mt.run_bin(["--discover", email, "--no-probe"], env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        return json.loads(r.stdout)

    def test_gmail(self):
        info = self.discover("Jan.Novak@gmail.com")
        self.assertEqual(info["source"], "ispdb")
        self.assertEqual(info["imap"], {"host": "imap.gmail.com", "port": 993, "security": "ssl", "user": "Jan.Novak@gmail.com"})
        self.assertEqual((info["smtp"]["host"], info["smtp"]["port"], info["smtp"]["security"]), ("smtp.gmail.com", 465, "ssl"))
        self.assertEqual(info["provider"], "google")
        self.assertNotIn("mx", info)

    def test_googlemail(self):
        self.assertEqual(self.discover("x@googlemail.com")["provider"], "google")

    def test_workspace_domain_by_mx(self):
        dns = {"MX:firma.test": [[1, "aspmx.l.google.com"], [5, "alt1.aspmx.l.google.com"]]}
        info = self.discover("jana@firma.test", dns)
        self.assertEqual(info["source"], "ispdb-mx")
        self.assertEqual(info["imap"]["host"], "imap.gmail.com")
        self.assertEqual(info["imap"]["user"], "jana@firma.test")
        self.assertEqual(info["provider"], "google")

    def test_workspace_new_mx_name(self):
        # novejsi Workspace: jediny MX smtp.google.com
        info = self.discover("jana@firma2.test", {"MX:firma2.test": [[1, "smtp.google.com"]]})
        self.assertEqual(info["imap"]["host"], "imap.gmail.com")
        self.assertEqual(info["provider"], "google")

    def test_outlook(self):
        info = self.discover("pepa@outlook.com")
        self.assertEqual(info["imap"]["host"], "outlook.office365.com")
        self.assertEqual(info["provider"], "microsoft")
        self.assertEqual(self.discover("pepa@hotmail.cz")["provider"], "microsoft")

    def test_microsoft365_domain_by_mx(self):
        dns = {"MX:urad.test": [[0, "urad-test.mail.protection.outlook.com"]]}
        info = self.discover("pepa@urad.test", dns)
        self.assertEqual(info["imap"]["host"], "outlook.office365.com")
        self.assertEqual(info["provider"], "microsoft")

    def test_seznam(self):
        info = self.discover("karel@seznam.cz")
        self.assertEqual(info["imap"], {"host": "imap.seznam.cz", "port": 993, "security": "ssl", "user": "karel@seznam.cz"})
        self.assertEqual(info["provider"], "seznam")
        # email.cz je take Seznam (ISPDB tu neni -> odhad; poskytovatel podle domeny)
        self.assertEqual(self.discover("karel@email.cz", {"A:imap.email.cz": True})["provider"], "seznam")

    def test_unknown_domain_has_no_provider(self):
        info = self.discover("ja@vlastni.test", {"MX:vlastni.test": [[10, "mail.vlastni.test"]], "A:mail.vlastni.test": True})
        self.assertEqual(info["imap"]["host"], "mail.vlastni.test")
        self.assertEqual(info["provider"], "")
        # podobna jmena nejsou poskytovatel (live.firma.cz, mygmail.com)
        self.assertEqual(self.discover("a@live.firma.test")["provider"], "")
        self.assertEqual(self.discover("a@mygmail.test")["provider"], "")


class GmailServiceTest(unittest.TestCase):
    alert_untagged = False

    def setUp(self):
        self.s = mt.Session()
        self.gmail = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, personality="gmail", user=GMAIL_USER,
                                   password=APP_PASSWORD, account_password=GOOGLE_PASSWORD, alert_untagged=self.alert_untagged)
        self.c = self.s.start_service()

    def tearDown(self):
        try:
            self.c.call("quit")
        except OSError:
            pass
        self.gmail.stop()
        self.s.close()

    def request(self, password, server=None, email=GMAIL_USER, provider=""):
        server = server or self.gmail
        return {"email": email, "name": "", "password": password, "provider": provider,
                "imap": {"host": "localhost", "port": server.ports["tls"], "security": "ssl", "user": email},
                "smtp": {"host": "localhost", "port": 465, "security": "ssl", "user": email}}

    def accounts(self):
        path = os.path.join(self.s.env["XDG_CONFIG_HOME"], "luxos-mail", "accounts.json")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return json.load(f)

    def mailboxes(self, account):
        path = os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail", account, "mailboxes.tsv")
        out = {}
        with open(path) as f:
            for line in f.read().split("\n"):
                if line:
                    p = line.split("\t")
                    out[p[0]] = {"role": p[3], "selectable": p[4] == "1"}
        return out

    def test_normal_google_password_explains_app_password(self):
        r = self.c.call("add_account", **self.request(GOOGLE_PASSWORD))
        self.assertFalse(r["ok"])
        self.assertEqual(r["kind"], "auth")
        self.assertIn("Application-specific password required", r["error"])
        self.assertIn("https://support.google.com/accounts/answer/185833", r["error"])
        for ch in "\r\n\t":
            self.assertNotIn(ch, r["error"])
        self.assertNotIn(GOOGLE_PASSWORD, r["error"])
        self.assertEqual(self.accounts(), [])
        self.assertEqual(self.s.secret_lookup(""), "")
        # jediny pokus o prihlaseni (zadne opakovani, ktere by ucet u Google zablokovalo)
        auth = [l for l in self.gmail.control("log")["log"] if " AUTHENTICATE " in l or " LOGIN " in l]
        self.assertEqual(len(auth), 1, auth)
        self.assertIn("AUTHENTICATE PLAIN ***", auth[0])     # SASL-IR, heslo v logu zakryte
        self.assertNotIn(GOOGLE_PASSWORD, self.s.service_log())

    def test_wrong_password_reason_with_code(self):
        r = self.c.call("add_account", **self.request("spatne"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["kind"], "auth")
        self.assertEqual(r["error"], "[AUTHENTICATIONFAILED] Invalid credentials (Failure)")

    def test_app_password_adds_account_with_gmail_folders(self):
        r = self.c.call("add_account", **self.request(APP_PASSWORD))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["state"], "online", self.s.service_log())
        acc = r["account"]
        self.assertEqual(self.accounts()[0]["provider"], "google")
        self.assertEqual(self.s.secret_lookup(acc), APP_PASSWORD)
        self.assertEqual(len(inbox_rows(self.s, acc)), 9)
        boxes = self.mailboxes(acc)
        self.assertEqual(boxes["[Gmail]/Sent Mail"]["role"], "sent")
        self.assertEqual(boxes["[Gmail]/Drafts"]["role"], "drafts")
        self.assertEqual(boxes["[Gmail]/Trash"]["role"], "trash")
        self.assertEqual(boxes["[Gmail]/Spam"]["role"], "junk")
        self.assertEqual(boxes["[Gmail]/All Mail"]["role"], "all")
        self.assertEqual(boxes["[Gmail]/Important"]["role"], "important")
        self.assertEqual(boxes["[Gmail]/Starred"]["role"], "starred")
        self.assertFalse(boxes["[Gmail]"]["selectable"])
        self.assertEqual(boxes["Faktury"]["role"], "")
        log = self.gmail.control("log")["log"]
        # "All Mail" (u velkych schranek statisice zprav) se nevybira ani nepocita; obycejne stitky ano
        self.assertFalse([l for l in log if "All Mail" in l], log)
        self.assertFalse([l for l in log if "Important" in l or "Starred" in l], log)
        self.assertTrue([l for l in log if "STATUS \"Faktury\"" in l], log)
        self.assertFalse([l for l in log if " SELECT \"[Gmail]\"" in l or " STATUS \"[Gmail]\"" in l], log)
        # smazani do Kose Gmailu
        rows = inbox_rows(self.s, acc)
        uid = int(rows[0][0])
        t = self.c.call("trash", account=acc, mailbox="INBOX", uids=[uid])
        self.assertTrue(t["ok"], t)
        self.assertTrue(mt.wait_for(lambda: len(self.gmail.control("dump")["boxes"]["[Gmail]/Trash"]) == 1, 10))

    def test_second_account_next_to_first(self):
        # prvni ucet (jako schranka LuxAI nebo jiny poskytovatel) a k nemu Gmail
        other = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES)
        try:
            r1 = self.c.call("add_account", **mt.account_request(other))
            self.assertTrue(r1["ok"], r1)
            r2 = self.c.call("add_account", **self.request(APP_PASSWORD))
            self.assertTrue(r2["ok"], r2)
            self.assertNotEqual(r1["account"], r2["account"])
            self.assertEqual(sorted(a["email"] for a in self.accounts()), sorted([mt.USER, GMAIL_USER]))
            st = self.c.call("status")
            states = {a["account"]: a["state"] for a in st["accounts"]}
            self.assertEqual(states.get(r1["account"]), "online", st)
            self.assertEqual(states.get(r2["account"]), "online", st)
            self.assertEqual(self.s.secret_lookup(r1["account"]), mt.PASSWORD)
            self.assertEqual(self.s.secret_lookup(r2["account"]), APP_PASSWORD)
        finally:
            other.stop()

    def test_microsoft_password_never_sent(self):
        ms = mt.FakeServer(self.s.root, self.s.certs, personality="microsoft", user="pepa@outlook.com", password="x")
        try:
            r = self.c.call("add_account", **self.request("heslo-microsoft", server=ms, email="pepa@outlook.com"))
            self.assertFalse(r["ok"])
            self.assertEqual(r["kind"], "oauthonly")
            log = ms.control("log")["log"]
            self.assertFalse([l for l in log if "LOGIN" in l.upper() or "AUTHENTICATE" in l.upper()], log)
            self.assertEqual(self.accounts(), [])
        finally:
            ms.stop()


class GmailUntaggedAlertTest(GmailServiceTest):
    """[ALERT] jako nevyzadana odpoved "* NO [ALERT] ..." pred tagovanym NO [AUTHENTICATIONFAILED]."""
    alert_untagged = True

    def test_normal_google_password_explains_app_password(self):
        r = self.c.call("add_account", **self.request(GOOGLE_PASSWORD))
        self.assertFalse(r["ok"])
        self.assertEqual(r["kind"], "auth")
        self.assertTrue(r["error"].startswith("Application-specific password required"), r["error"])
        self.assertIn("[AUTHENTICATIONFAILED] Invalid credentials (Failure)", r["error"])

    test_app_password_adds_account_with_gmail_folders = None
    test_second_account_next_to_first = None
    test_microsoft_password_never_sent = None
    test_wrong_password_reason_with_code = None


if __name__ == "__main__":
    unittest.main()
