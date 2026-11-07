"""Skutecny Dovecot 2.4 (bez roota, docasna slozka) proti skutecnemu upravenemu serveru uctu LuxAI:

    LUX_ACCOUNT_SERVER_JS=/kopie/server.js LUX_DOVECOT_ROOT=/rozbaleny/dovecot python3 -m unittest test_dovecot_oauth

Overuje serverovy soubor luxai-oauth2.conf: OAUTHBEARER i XOAUTH2 (s SASL-IR i bez), spatny/cizi/
odvolany token, token cizi schranky, heslo (PLAIN/LOGIN) jen z povolene site (allow_nets), PLAIN pro
Roundcube dal funguje, a ze se tokeny ani hesla nedostanou do logu Dovecotu.
"""
import base64
import os
import socket
import ssl
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "packages", "apps", "luxos-mail", "tests"))
import account_server as acc  # noqa: E402
import dovecot_local as dl  # noqa: E402
import mailtest as mt  # noqa: E402

MAILBOX_PASSWORD = "roundcube-only-Secret-123"


class Imap:
    def __init__(self, port, ca, tls=True):
        raw = socket.create_connection(("127.0.0.1", port), 10)
        if tls:
            ctx = ssl.create_default_context(cafile=ca)
            # testovaci CA z mailtest nema key usage (Python 3.13+ to ve strict rezimu vyzaduje)
            ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
            self.sock = ctx.wrap_socket(raw, server_hostname="localhost")
        else:
            self.sock = raw
        self.f = self.sock.makefile("rb")
        self.greeting = self.line()
        self.n = 0

    def line(self):
        return self.f.readline().decode("utf-8", "replace").rstrip("\r\n")

    def send(self, text):
        self.sock.sendall(text.encode() + b"\r\n")

    def command(self, text):
        self.n += 1
        tag = "T%d" % self.n
        self.send(tag + " " + text)
        return self.finish(tag)

    def finish(self, tag):
        lines = []
        while True:
            line = self.line()
            lines.append(line)
            if line.startswith(tag + " ") or line == "":
                return lines

    def authenticate(self, mech, payload, sasl_ir=True, abort_reply="AQ=="):
        """Vraci (posledni radek, pokracovani se zpravou serveru nebo None)."""
        self.n += 1
        tag = "T%d" % self.n
        b64 = base64.b64encode(payload).decode()
        challenge = None
        if sasl_ir:
            self.send("%s AUTHENTICATE %s %s" % (tag, mech, b64))
        else:
            self.send("%s AUTHENTICATE %s" % (tag, mech))
            cont = self.line()
            assert cont.startswith("+"), cont
            self.send(b64)
        line = self.line()
        if line.startswith("+"):
            challenge = base64.b64decode(line[1:].strip() or b"").decode("utf-8", "replace")
            self.send(abort_reply)
            line = self.line()
        while not line.startswith(tag + " ") and line != "":
            line = self.line()
        return line, challenge

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def oauthbearer(user, token):
    return ("n,a=%s,\x01host=localhost\x01port=993\x01auth=Bearer %s\x01\x01" % (user.replace("=", "=3D").replace(",", "=2C"), token)).encode()


def xoauth2(user, token):
    return ("user=%s\x01auth=Bearer %s\x01\x01" % (user, token)).encode()


@unittest.skipUnless(os.path.isfile(os.environ.get("LUX_ACCOUNT_SERVER_JS", "")) and dl.available(),
                     "needs LUX_ACCOUNT_SERVER_JS and a Dovecot 2.4 (LUX_DOVECOT_ROOT or /usr)")
class DovecotOAuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = __import__("tempfile").mkdtemp(prefix="lux-dovecot-certs-")
        cls.certs = mt.make_certs(cls.tmp)
        cls.srv = acc.AccountServer(acc.default_mailboxes())
        cls.dove = dl.LocalDovecot(cls.srv.origin + "/oauth/introspect", acc.INTROSPECTION_SECRET, cls.certs,
                                   {"info@lux-ai.test": MAILBOX_PASSWORD, "team@lux-ai.test": MAILBOX_PASSWORD}).start()

    @classmethod
    def tearDownClass(cls):
        cls.dove.close()
        cls.srv.close()
        __import__("shutil").rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.conns = []

    def tearDown(self):
        for c in self.conns:
            c.close()

    def imap(self, tls=True):
        c = Imap(self.dove.ports["imaps" if tls else "imap"], self.certs["ca"], tls)
        self.conns.append(c)
        return c

    def token(self, session="admin", address="info@lux-ai.test"):
        status, body = self.srv.request("POST", "/api/mail/token", {"address": address}, session=session)
        self.assertEqual(status, 200, body)
        return body["access_token"]

    def test_capabilities_offer_oauth(self):
        c = self.imap()
        caps = " ".join(c.command("CAPABILITY")).upper()
        for mech in ("AUTH=OAUTHBEARER", "AUTH=XOAUTH2", "AUTH=PLAIN", "SASL-IR"):
            self.assertIn(mech, caps)

    def test_oauthbearer_login_and_mailbox_access(self):
        c = self.imap()
        line, challenge = c.authenticate("OAUTHBEARER", oauthbearer("info@lux-ai.test", self.token()))
        self.assertTrue(line.split(" ", 2)[1] == "OK", line)
        self.assertIsNone(challenge)
        sel = c.command("SELECT INBOX")
        self.assertTrue(sel[-1].split(" ")[1] == "OK", sel)
        # prihlaseny uzivatel je schranka, ne registracni e-mail uctu
        self.assertTrue(os.path.isdir(os.path.join(self.dove.root, "vmail", "lux-ai.test", "info")))

    def test_xoauth2_without_sasl_ir(self):
        c = self.imap()
        line, _ = c.authenticate("XOAUTH2", xoauth2("info@lux-ai.test", self.token()), sasl_ir=False)
        self.assertEqual(line.split(" ")[1], "OK", line)

    def test_uppercase_user_is_normalized(self):
        c = self.imap()
        line, _ = c.authenticate("XOAUTH2", xoauth2("Info@Lux-AI.test", self.token()))
        self.assertEqual(line.split(" ")[1], "OK", line)

    def test_invalid_token_rejected_with_json_challenge(self):
        c = self.imap()
        line, challenge = c.authenticate("OAUTHBEARER", oauthbearer("info@lux-ai.test", "A" * 43))
        self.assertEqual(line.split(" ")[1], "NO", line)
        self.assertIsNotNone(challenge)
        # RFC 7628: chyba jako JSON v pokracovani; Dovecot posila {"status":"401","schemes":"bearer",...}
        self.assertIn('"status"', challenge)
        c2 = self.imap()
        line, challenge = c2.authenticate("XOAUTH2", xoauth2("info@lux-ai.test", "B" * 43), abort_reply="")
        self.assertEqual(line.split(" ")[1], "NO", line)

    def test_token_for_other_mailbox_rejected(self):
        # platny token pro team@ nelze pouzit pro info@ (username v introspekci nesedi)
        c = self.imap()
        line, _ = c.authenticate("XOAUTH2", xoauth2("info@lux-ai.test", self.token("user", "team@lux-ai.test")), abort_reply="")
        self.assertEqual(line.split(" ")[1], "NO", line)
        c2 = self.imap()
        line, _ = c2.authenticate("XOAUTH2", xoauth2("team@lux-ai.test", self.token("user", "team@lux-ai.test")))
        self.assertEqual(line.split(" ")[1], "OK", line)

    def test_revoked_token_rejected(self):
        t = self.token("admin2")
        self.assertEqual(self.srv.request("POST", "/api/ide/logout", session="admin2")[0], 200)
        c = self.imap()
        line, _ = c.authenticate("OAUTHBEARER", oauthbearer("info@lux-ai.test", t))
        self.assertEqual(line.split(" ")[1], "NO", line)

    def test_password_still_works_on_loopback_for_webmail(self):
        # Roundcube: 127.0.0.1:143 bez TLS, PLAIN/LOGIN s heslem schranky
        c = self.imap(tls=False)
        line = c.command('LOGIN "info@lux-ai.test" "%s"' % MAILBOX_PASSWORD)[-1]
        self.assertEqual(line.split(" ")[1], "OK", line)
        c2 = self.imap()
        line, _ = c2.authenticate("PLAIN", b"\0info@lux-ai.test\0" + MAILBOX_PASSWORD.encode())
        self.assertEqual(line.split(" ")[1], "OK", line)

    def test_password_is_not_an_oauth_token_and_token_not_a_password(self):
        c = self.imap()
        line, _ = c.authenticate("PLAIN", b"\0info@lux-ai.test\0" + self.token().encode())
        self.assertEqual(line.split(" ")[1], "NO", line)
        c2 = self.imap()
        line, _ = c2.authenticate("XOAUTH2", xoauth2("info@lux-ai.test", MAILBOX_PASSWORD), abort_reply="")
        self.assertEqual(line.split(" ")[1], "NO", line)

    def test_no_secrets_in_dovecot_log(self):
        t = self.token()
        c = self.imap()
        c.authenticate("OAUTHBEARER", oauthbearer("info@lux-ai.test", t))
        c.command("LOGOUT")
        log = self.dove.log()
        self.assertNotIn(t, log)
        self.assertNotIn(acc.INTROSPECTION_SECRET, log)
        self.assertNotIn(MAILBOX_PASSWORD, log)


@unittest.skipUnless(os.path.isfile(os.environ.get("LUX_ACCOUNT_SERVER_JS", "")) and dl.available(),
                     "needs LUX_ACCOUNT_SERVER_JS and a Dovecot 2.4 (LUX_DOVECOT_ROOT or /usr)")
class DovecotAllowNetsTest(unittest.TestCase):
    """allow_nets z luxai-oauth2.conf: heslo jen z povolene site. Testovaci klient je na 127.0.0.1, proto
    se sit zameni za 10.255.255.0/24 - pak se heslo z 127.0.0.1 chova jako heslo z internetu."""

    def test_password_from_outside_rejected_oauth_still_works(self):
        import tempfile
        import shutil
        tmp = tempfile.mkdtemp(prefix="lux-dovecot-certs-")
        certs = mt.make_certs(tmp)
        srv = acc.AccountServer(acc.default_mailboxes())
        dove = dl.LocalDovecot(srv.origin + "/oauth/introspect", acc.INTROSPECTION_SECRET, certs,
                               {"info@lux-ai.test": MAILBOX_PASSWORD}, allow_nets="10.255.255.0/24").start()
        try:
            c = Imap(dove.ports["imaps"], certs["ca"])
            line, _ = c.authenticate("PLAIN", b"\0info@lux-ai.test\0" + MAILBOX_PASSWORD.encode())
            self.assertEqual(line.split(" ")[1], "NO", line)
            c.close()
            c = Imap(dove.ports["imap"], certs["ca"], tls=False)
            line = c.command('LOGIN "info@lux-ai.test" "%s"' % MAILBOX_PASSWORD)[-1]
            self.assertEqual(line.split(" ")[1], "NO", line)
            c.close()
            token = srv.request("POST", "/api/mail/token", {"address": "info@lux-ai.test"}, session="admin")[1]["access_token"]
            c = Imap(dove.ports["imaps"], certs["ca"])
            line, _ = c.authenticate("OAUTHBEARER", oauthbearer("info@lux-ai.test", token))
            self.assertEqual(line.split(" ")[1], "OK", line)
            c.close()
            self.assertIn("allow_nets", dove.log())
        finally:
            dove.close()
            srv.close()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
