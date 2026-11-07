"""Cela cesta mistne: Posta LuxOS (sluzba luxos-mail-service) -> upraveny server uctu LuxAI
(/api/mail/mailboxes, /api/mail/token) -> skutecny Dovecot 2.4 s luxai-oauth2.conf -> introspekce
na serveru uctu. Falesny ~/.config/luxai/account.json v docasnem HOME, testovaci CA, zadny skutecny
ucet ani server.

    LUX_ACCOUNT_SERVER_JS=... LUX_DOVECOT_ROOT=... LUXOS_MAIL_BIN=.../luxos-mail \
        python3 -m unittest test_end_to_end
"""
import json
import os
import shutil
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MAIL_TESTS = os.path.join(HERE, "..", "..", "..", "packages", "apps", "luxos-mail", "tests")
sys.path.insert(0, HERE)
sys.path.insert(0, MAIL_TESTS)
import account_server as acc  # noqa: E402
import dovecot_local as dl  # noqa: E402
import fake_luxai as fl  # noqa: E402
import mailtest as mt  # noqa: E402
from test_service import inbox_rows  # noqa: E402

READY = (os.path.isfile(os.environ.get("LUX_ACCOUNT_SERVER_JS", "")) and dl.available()
         and os.path.isfile(os.environ.get("LUXOS_MAIL_BIN", "")))


@unittest.skipUnless(READY, "needs LUX_ACCOUNT_SERVER_JS, Dovecot 2.4 and LUXOS_MAIL_BIN")
class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.s = mt.Session()
        # Dovecot pouziva testovaci certifikat pro "localhost" podepsany testovaci CA Session
        self.srv = acc.AccountServer({})
        self.dove = dl.LocalDovecot(self.srv.origin + "/oauth/introspect", acc.INTROSPECTION_SECRET, self.s.certs,
                                    {"info@lux-ai.test": "roundcube-only-Secret-123"})
        self.srv.write_mailboxes(acc.default_mailboxes(imap_port=self.dove.ports["imaps"], host="localhost"))
        maildir = os.path.join(self.dove.root, "vmail", "lux-ai.test", "info", "Maildir")
        for sub in ("cur", "new", "tmp"):
            os.makedirs(os.path.join(maildir, sub))
        for i, name in enumerate(sorted(n for n in os.listdir(mt.FIXTURES) if n.endswith(".eml"))):
            shutil.copy(os.path.join(mt.FIXTURES, name), os.path.join(maildir, "new", "%d.%d.test" % (1700000000 + i, i)))
        self.maildir = maildir
        self.dove.start()
        # session token administratora z falesnych dat serveru uctu
        fl.write_account(self.s.env, self.srv.origin, token=self.srv.tokens["admin"], email=acc.ADMIN_EMAIL)
        self.c = self.s.start_service()

    def tearDown(self):
        try:
            self.c.call("quit")
        except OSError:
            pass
        self.dove.close()
        self.srv.close()
        self.s.close()

    def test_luxai_mailbox_end_to_end(self):
        r = self.c.call("luxai_mailboxes")
        self.assertTrue(r["ok"], r)
        self.assertEqual([m["address"] for m in r["mailboxes"]], ["info@lux-ai.test"])
        r = self.c.call("add_luxai_account", address="info@lux-ai.test")
        self.assertTrue(r["ok"], (r, self.s.service_log(), self.dove.log()[-2000:]))
        self.assertEqual(r["state"], "online", self.s.service_log())
        account = r["account"]
        rows = inbox_rows(self.s, account)
        self.assertEqual(len(rows), len([n for n in os.listdir(mt.FIXTURES) if n.endswith(".eml")]))
        self.assertIn("Příliš žluťoučký kůň", {row[7] for row in rows}, rows[:3])
        # nova zprava do Maildir -> IDLE -> upozorneni
        before = len(self.s.notifications())
        shutil.copy(os.path.join(mt.FIXTURES, "mixed-attachment.eml"), os.path.join(self.maildir, "new", "1800000000.99.test"))
        self.assertTrue(mt.wait_for(lambda: len(self.s.notifications()) > before, 15),
                        "no notification: " + self.s.service_log()[-2000:])
        # Dovecot overil token introspekci, prihlasil schranku (ne registracni e-mail)
        log = self.dove.log()
        self.assertIn("user=<info@lux-ai.test>", log)
        self.assertRegex(log, r"method=(OAUTHBEARER|XOAUTH2)")
        # zadne tajemstvi v logu Dovecotu, sluzby ani v souborech Posty
        session = self.srv.tokens["admin"]
        self.assertNotIn(session, log)
        self.assertNotIn(acc.INTROSPECTION_SECRET, log)
        self.assertNotIn(session, self.s.service_log())
        for root, dirs, files in os.walk(os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail")):
            for name in files:
                with open(os.path.join(root, name), "rb") as f:
                    self.assertNotIn(session.encode(), f.read())
        self.assertEqual(self.s.secret_lookup(account), "")

    def server_flags(self, mailbox="INBOX"):
        """Priznaky primo z Dovecotu (heslo schranky jen na loopbacku, jako Roundcube)."""
        import imaplib
        m = imaplib.IMAP4("127.0.0.1", self.dove.ports["imap"])
        m.login("info@lux-ai.test", "roundcube-only-Secret-123")
        m.select(mailbox)
        typ, data = m.uid("FETCH", "1:*", "(FLAGS)")
        m.logout()
        out = {}
        for item in data:
            if item:
                text = item.decode()
                uid = int(text.split("UID ")[1].split(" ")[0].rstrip(")"))
                out[uid] = text.split("FLAGS (")[1].split(")")[0].split()
        return out

    def test_body_flags_trash_on_real_dovecot(self):
        account = self.c.call("add_luxai_account", address="info@lux-ai.test")["account"]
        names = sorted(n for n in os.listdir(mt.FIXTURES) if n.endswith(".eml"))
        r = self.c.call("body", account=account, mailbox="INBOX", uid=6)
        self.assertTrue(r["ok"], r)
        with open(r["path"], "rb") as f, open(os.path.join(mt.FIXTURES, names[5]), "rb") as g:
            # Dovecot vydava radky s CRLF
            self.assertEqual(f.read().replace(b"\r\n", b"\n"), g.read().replace(b"\r\n", b"\n"))
        self.assertNotIn("\\Seen", self.server_flags()[6])
        r = self.c.call("flags", account=account, mailbox="INBOX", uids=[2, 3], add=True, flags=["\\Seen"])
        self.assertTrue(r["ok"], r)
        flags = self.server_flags()
        self.assertIn("\\Seen", flags[2])
        self.assertIn("\\Seen", flags[3])
        self.assertEqual({row[0]: row[1] for row in inbox_rows(self.s, account)}["2"], "S")
        r = self.c.call("trash", account=account, mailbox="INBOX", uids=[4])
        self.assertTrue(r["ok"], r)
        self.assertNotIn(4, self.server_flags())
        self.assertEqual(len(self.server_flags("Trash")), 1)
        self.assertNotIn("4", [row[0] for row in inbox_rows(self.s, account)])
        # mailbox list from Dovecot: special-use Trash/Sent recognised
        r = self.c.call("mailboxes", account=account)
        self.assertTrue(r["ok"], r)

    def test_logout_on_luxai_blocks_new_connections(self):
        account = self.c.call("add_luxai_account", address="info@lux-ai.test")["account"]
        # odhlaseni (luxos-account logout) zrusi relaci na serveru -> novy token nedostane
        self.assertEqual(self.srv.request("POST", "/api/ide/logout", session="admin")[0], 200)
        r = self.c.call("retry_account", account=account)
        self.assertEqual((r["state"], r["kind"]), ("error", "luxai_session"), self.s.service_log())

    def test_mapping_removed_blocks_mailbox(self):
        account = self.c.call("add_luxai_account", address="info@lux-ai.test")["account"]
        cfg = acc.default_mailboxes(imap_port=self.dove.ports["imaps"], host="localhost")
        cfg["mailboxes"][0]["emails"] = []
        self.srv.write_mailboxes(cfg)
        r = self.c.call("retry_account", account=account)
        self.assertEqual((r["state"], r["kind"]), ("error", "luxai_denied"), self.s.service_log())
        time.sleep(0.5)
        self.assertEqual(json.loads(json.dumps(self.c.call("luxai_mailboxes")))["mailboxes"], [])


if __name__ == "__main__":
    unittest.main()
