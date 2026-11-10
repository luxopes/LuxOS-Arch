"""Schranky LuxAI ve sluzbe Posty (prihlaseni uctem LuxAI tohoto pocitace, SASL OAUTHBEARER/XOAUTH2):
falesny server uctu LuxAI + falesny IMAP s tokeny, docasny HOME s falesnym ~/.config/luxai/account.json.
Nikdy skutecny ucet, skutecny account.json ani skutecny server.
"""
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_luxai as fl  # noqa: E402
import mailtest as mt  # noqa: E402
from test_service import inbox_rows  # noqa: E402


class LuxAIMailTest(unittest.TestCase):
    oauth = "OAUTHBEARER,XOAUTH2"
    sasl_ir = True

    def setUp(self):
        self.s = mt.Session()
        self.server = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, oauth=self.oauth, sasl_ir=self.sasl_ir)
        self.lux = fl.FakeLuxAI(self.server, [fl.mailbox(mt.USER, self.server.ports["tls"])])
        self.account_file = fl.write_account(self.s.env, self.lux.origin)
        self.c = self.s.start_service()

    def tearDown(self):
        try:
            self.c.call("quit")
        except OSError:
            pass
        self.lux.stop()
        self.server.stop()
        self.s.close()

    def auth_log(self):
        return [l for l in self.server.control("log")["log"] if l.startswith("AUTH ")]

    def status(self, account):
        for st in self.c.call("hello")["accounts"]:
            if st["account"] == account:
                return st
        return {}

    def add(self):
        r = self.c.call("add_luxai_account", address=mt.USER)
        self.assertTrue(r["ok"], (r, self.s.service_log()))
        return r

    def test_mailboxes_list(self):
        r = self.c.call("luxai_mailboxes")
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(r["mailboxes"]), 1)
        m = r["mailboxes"][0]
        self.assertEqual(m["address"], mt.USER)
        self.assertEqual(m["imap"], {"host": "localhost", "port": self.server.ports["tls"], "security": "ssl", "user": mt.USER})
        self.assertFalse(m["added"])
        req = self.lux.requests[-1]
        self.assertEqual(req["client"], "luxos")
        self.assertTrue(req["cookie_ok"])
        self.assertEqual(req["path"], "/api/mail/mailboxes")

    def test_add_without_password_and_sync(self):
        r = self.add()
        acc = r["account"]
        self.assertEqual(r["state"], "online", self.s.service_log())
        with open(os.path.join(self.s.env["XDG_CONFIG_HOME"], "luxos-mail", "accounts.json")) as f:
            accounts = json.load(f)
        self.assertEqual(accounts[0]["auth"], "luxai")
        self.assertEqual(accounts[0]["email"], mt.USER)
        self.assertEqual(accounts[0]["imap"]["user"], mt.USER)
        self.assertEqual(accounts[0]["smtp"]["port"], 9)
        # zadne heslo v klicence, zadny token ani session token v souborech Posty
        self.assertEqual(self.s.secret_lookup(acc), "")
        secrets_ = [fl.SESSION.encode()] + [t.encode() for t in self.lux.tokens]
        for base in (os.path.join(self.s.env["XDG_CONFIG_HOME"], "luxos-mail"), os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail")):
            for root, dirs, files in os.walk(base):
                for name in files:
                    with open(os.path.join(root, name), "rb") as f:
                        data = f.read()
                    for sec in secrets_:
                        self.assertNotIn(sec, data, name)
        log = self.s.service_log().encode()
        for sec in secrets_:
            self.assertNotIn(sec, log)
        self.assertEqual(len(inbox_rows(self.s, acc)), 9)
        auths = self.auth_log()
        self.assertTrue(auths[0].startswith("AUTH OAUTHBEARER user=%s host=localhost port=%d" % (mt.USER, self.server.ports["tls"])), auths)
        # IMAP log nikdy neobsahuje token (base64 v AUTHENTICATE je zakryty)
        for line in self.server.control("log")["log"]:
            for t in self.lux.tokens:
                self.assertNotIn(t, line)
        # znovu v seznamu uz jako pridana
        self.assertTrue(self.c.call("luxai_mailboxes")["mailboxes"][0]["added"])
        # novy token pri kazdem spojeni: overeni pri pridani + spojeni sluzby
        self.assertEqual(len(self.lux.token_requests()), 2)

    def test_idle_notification_after_oauth(self):
        acc = self.add()["account"]
        before = len(self.s.notifications())
        self.server.control("deliver INBOX " + os.path.join(mt.FIXTURES, "mixed-attachment.eml"))
        self.assertTrue(mt.wait_for(lambda: len(self.s.notifications()) > before, 10), self.s.service_log())
        self.assertTrue(mt.wait_for(lambda: len(inbox_rows(self.s, acc)) == 10, 10))

    def test_reconnect_uses_fresh_token(self):
        acc = self.add()["account"]
        n = len(self.lux.token_requests())
        # stare tokeny uz neplati (vyprsely); nove spojeni si vyzada novy
        self.server.control("revoke")
        self.assertTrue(self.c.call("reconnect")["ok"])
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online" and len(self.lux.token_requests()) > n, 10),
                        (self.status(acc), self.s.service_log()))

    def test_session_expired_is_not_retried(self):
        acc = self.add()["account"]
        self.lux.fail_token = 401
        self.server.control("revoke")
        r = self.c.call("retry_account", account=acc)
        self.assertEqual(r["state"], "error")
        self.assertEqual(r["kind"], "luxai_session")
        n = len(self.lux.token_requests())
        auths = len(self.auth_log())
        # akce v okne ani prepojeni site nezkousi znovu (zadne zahlceni serveru, zadny fail2ban)
        self.assertFalse(self.c.call("sync", account=acc, mailbox="INBOX")["ok"])
        self.c.call("reconnect")
        time.sleep(1.0)
        self.assertEqual(len(self.lux.token_requests()), n)
        self.assertEqual(len(self.auth_log()), auths)
        # po novem prihlaseni k LuxAI okno pozada o retry_account
        self.lux.fail_token = 0
        r = self.c.call("retry_account", account=acc)
        self.assertEqual(r["state"], "online", self.s.service_log())

    def test_rejected_token_single_attempt(self):
        acc = self.add()["account"]
        # LuxAI token vyda, ale IMAP ho odmitne (napr. odebrany pristup) -> chyba bez opakovani
        self.lux.imap = None
        self.server.control("revoke")
        r = self.c.call("retry_account", account=acc)
        self.assertEqual((r["state"], r["kind"]), ("error", "auth"))
        auths = len(self.auth_log())
        self.c.call("reconnect")
        time.sleep(1.0)
        self.assertEqual(len(self.auth_log()), auths)
        log = self.server.control("log")["log"]
        # klient odpovedel na chybove pokracovani RFC 7628 (OAUTHBEARER: %x01 = "AQ==")
        self.assertIn("SASL abort reply='AQ=='", log)

    def test_signed_out_and_denied(self):
        os.unlink(self.account_file)
        r = self.c.call("luxai_mailboxes")
        self.assertEqual((r["ok"], r["kind"]), (False, "luxai_signedout"))
        r = self.c.call("add_luxai_account", address=mt.USER)
        self.assertEqual(r["kind"], "luxai_signedout")
        fl.write_account(self.s.env, self.lux.origin)
        r = self.c.call("add_luxai_account", address="other@example.test")
        self.assertEqual((r["ok"], r["kind"]), (False, "luxai_denied"))
        self.lux.fail_list = 401
        self.assertEqual(self.c.call("luxai_mailboxes")["kind"], "luxai_session")
        self.lux.fail_list = 500
        self.assertEqual(self.c.call("luxai_mailboxes")["kind"], "luxai_server")
        # neplatny session token v souboru (znaky mimo cookie) se vubec neposle
        fl.write_account(self.s.env, self.lux.origin, token="bad token;x=1")
        count = len(self.lux.requests)
        self.assertEqual(self.c.call("luxai_mailboxes")["kind"], "luxai_signedout")
        self.assertEqual(len(self.lux.requests), count)

    def test_unreachable_luxai(self):
        fl.write_account(self.s.env, "http://127.0.0.1:9")
        r = self.c.call("luxai_mailboxes")
        self.assertEqual((r["ok"], r["kind"]), (False, "connect"))


class LuxAIXOAuth2Test(LuxAIMailTest):
    """Server jen s XOAUTH2 a bez SASL-IR (pokracovani "+" pred odeslanim tokenu)."""
    oauth = "XOAUTH2"
    sasl_ir = False

    def test_add_without_password_and_sync(self):
        r = self.add()
        self.assertEqual(r["state"], "online", self.s.service_log())
        self.assertTrue(self.auth_log()[0].startswith("AUTH XOAUTH2 user=%s" % mt.USER), self.auth_log())

    def test_rejected_token_single_attempt(self):
        acc = self.add()["account"]
        self.lux.imap = None
        self.server.control("revoke")
        r = self.c.call("retry_account", account=acc)
        self.assertEqual((r["state"], r["kind"]), ("error", "auth"))
        self.assertIn("SASL abort reply=''", self.server.control("log")["log"])


class NoOAuthServerTest(unittest.TestCase):
    def test_server_without_token_login(self):
        s = mt.Session()
        server = mt.FakeServer(s.root, s.certs, seed=mt.FIXTURES)
        lux = fl.FakeLuxAI(server, [fl.mailbox(mt.USER, server.ports["tls"])])
        try:
            fl.write_account(s.env, lux.origin)
            c = s.start_service()
            r = c.call("add_luxai_account", address=mt.USER)
            self.assertEqual((r["ok"], r["kind"]), (False, "nooauth"))
            c.call("quit")
        finally:
            lux.stop()
            server.stop()
            s.close()


if __name__ == "__main__":
    unittest.main()
