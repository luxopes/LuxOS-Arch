"""Automaticke nalezeni serveru: autoconfig poskytovatele, ISPDB (i podle MX), DNS SRV, odhad podle jmen.

Mistni HTTP server na 127.0.0.1 a falesne DNS (LUXOS_MAIL_FAKE_DNS) - zadny skutecny server.
"""
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailtest as mt  # noqa: E402

PROVIDER = """<?xml version="1.0"?>
<clientConfig version="1.1"><emailProvider id="example.test">
<incomingServer type="pop3"><hostname>pop.example.test</hostname><port>995</port><socketType>SSL</socketType></incomingServer>
<incomingServer type="imap"><hostname>plain.example.test</hostname><port>143</port><socketType>plain</socketType><username>%EMAILADDRESS%</username></incomingServer>
<incomingServer type="imap"><hostname>imap.example.test</hostname><port>143</port><socketType>STARTTLS</socketType><username>%EMAILLOCALPART%</username></incomingServer>
<incomingServer type="imap"><hostname>secure.%EMAILDOMAIN%</hostname><port>993</port><socketType>SSL</socketType><username>%EMAILLOCALPART%</username></incomingServer>
<outgoingServer type="smtp"><hostname>smtp.example.test</hostname><port>465</port><socketType>SSL</socketType><username>%EMAILADDRESS%</username></outgoingServer>
</emailProvider></clientConfig>"""

ISPDB = """<?xml version="1.0"?><clientConfig version="1.1"><emailProvider id="bigmail.test">
<incomingServer type="imap"><hostname>imap.bigmail.test</hostname><port>993</port><socketType>SSL</socketType><username>%EMAILADDRESS%</username></incomingServer>
<outgoingServer type="smtp"><hostname>smtp.bigmail.test</hostname><port>587</port><socketType>STARTTLS</socketType><username>%EMAILADDRESS%</username></outgoingServer>
</emailProvider></clientConfig>"""


class Handler(http.server.BaseHTTPRequestHandler):
    routes = {}
    seen = []

    def do_GET(self):
        Handler.seen.append(self.path)
        for prefix, body in Handler.routes.items():
            if self.path.startswith(prefix):
                self.send_response(200)
                self.send_header("Content-Type", "text/xml")
                self.end_headers()
                self.wfile.write(body.encode())
                return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass


class DiscoverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.port = cls.http.server_address[1]
        cls.tmp = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()

    def discover(self, email, dns=None, routes=None, probe=False):
        Handler.routes = routes or {}
        Handler.seen = []
        path = os.path.join(self.tmp, "dns.json")
        with open(path, "w") as f:
            json.dump(dns or {}, f)
        base = "http://127.0.0.1:%d" % self.port
        env = dict(os.environ, LUXOS_MAIL_FAKE_DNS=path,
                   LUXOS_MAIL_AUTOCONFIG_URLS=base + "/auto/%DOMAIN%/mail/config-v1.1.xml?emailaddress=%EMAIL% " + base + "/wk/%DOMAIN%/.well-known/autoconfig/mail/config-v1.1.xml",
                   LUXOS_MAIL_ISPDB_URL=base + "/ispdb/%DOMAIN%")
        args = ["--discover", email]
        if not probe:
            args.append("--no-probe")
        r = mt.run_bin(args, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        return json.loads(r.stdout)

    def test_provider_autoconfig_prefers_ssl_and_skips_plain(self):
        res = self.discover("jana@example.test", routes={"/auto/example.test/": PROVIDER})
        self.assertEqual(res["source"], "autoconfig")
        self.assertEqual(res["imap"], {"host": "secure.example.test", "port": 993, "security": "ssl", "user": "jana"})
        self.assertEqual(res["smtp"], {"host": "smtp.example.test", "port": 465, "security": "ssl", "user": "jana@example.test"})
        self.assertIn("emailaddress=jana@example.test", Handler.seen[0])

    def test_well_known_then_ispdb(self):
        res = self.discover("a@bigmail.test", routes={"/ispdb/bigmail.test": ISPDB})
        self.assertEqual(res["source"], "ispdb")
        self.assertEqual(res["imap"]["host"], "imap.bigmail.test")
        self.assertEqual(res["imap"]["user"], "a@bigmail.test")
        self.assertEqual([p.split("?")[0] for p in Handler.seen], ["/auto/bigmail.test/mail/config-v1.1.xml",
                                                                   "/wk/bigmail.test/.well-known/autoconfig/mail/config-v1.1.xml", "/ispdb/bigmail.test"])

    def test_ispdb_by_mx(self):
        res = self.discover("info@firma.test", dns={"MX:firma.test": [[10, "mx1.bigmail.test"]]}, routes={"/ispdb/bigmail.test": ISPDB})
        self.assertEqual(res["source"], "ispdb-mx")
        self.assertEqual(res["imap"]["host"], "imap.bigmail.test")

    def test_srv_records(self):
        dns = {"SRV:_imaps._tcp.lux.test": [[10, 1, 993, "mail.lux.test."], [0, 1, 993, "imap.lux.test."]],
               "SRV:_submission._tcp.lux.test": [[0, 1, 587, "smtp.lux.test."]]}
        res = self.discover("info@lux.test", dns=dns)
        self.assertEqual(res["source"], "srv")
        self.assertEqual(res["imap"], {"host": "imap.lux.test", "port": 993, "security": "ssl", "user": "info@lux.test"})
        self.assertEqual(res["smtp"]["host"], "smtp.lux.test")
        self.assertEqual(res["smtp"]["security"], "starttls")

    def test_srv_starttls_and_dot_target(self):
        dns = {"SRV:_imaps._tcp.lux.test": [[0, 0, 0, "."]], "SRV:_imap._tcp.lux.test": [[0, 1, 143, "imap.lux.test"]]}
        res = self.discover("info@lux.test", dns=dns)
        self.assertEqual(res["imap"]["security"], "starttls")
        self.assertEqual(res["imap"]["port"], 143)

    def test_guess_by_dns_without_probe(self):
        res = self.discover("info@guess.test", dns={"A:mail.guess.test": True})
        self.assertEqual(res["source"], "guess")
        self.assertEqual(res["imap"]["host"], "mail.guess.test")
        self.assertEqual(res["imap"]["port"], 993)

    def test_guess_prefers_mx_host_in_domain(self):
        dns = {"MX:lux.test": [[10, "mail.lux.test."]], "A:imap.lux.test": True, "A:mail.lux.test": True}
        res = self.discover("info@lux.test", dns=dns)
        self.assertEqual(res["imap"]["host"], "mail.lux.test")
        self.assertEqual(res["smtp"]["host"], "mail.lux.test")

    def test_guess_with_wildcard_dns_skips_unverified_names(self):
        # *.wild.test: kazde jmeno ma zaznam -> imap.wild.test by byl jen domnely, bez overeni mail.<domena>
        res = self.discover("info@wild.test", dns={"A:*.wild.test": True})
        self.assertEqual(res["imap"]["host"], "mail.wild.test")
        self.assertIn({"step": "guess", "result": "wildcard DNS record"}, res["steps"])
        # bez zastupneho zaznamu obvykle poradi
        res = self.discover("info@plain.test", dns={"A:imap.plain.test": True, "A:mail.plain.test": True})
        self.assertEqual(res["imap"]["host"], "imap.plain.test")

    def test_not_found_and_invalid(self):
        self.assertEqual(self.discover("info@nowhere.test")["error"], "notfound")
        self.assertEqual(self.discover("bez-zavinace")["error"], "invalid")


if __name__ == "__main__":
    unittest.main()
