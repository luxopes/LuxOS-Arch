"""Prihlaseni u poskytovatele (OAuth2 pro nativni aplikace, RFC 8252) ve sluzbe Posty:

falesny Google a Microsoft (fake_oauth: /authorize hned presmeruje na loopback s kodem, /token, obnoveni,
invalid_grant), falesny IMAP s tokeny (Gmail: OAUTHBEARER, Microsoft: jen XOAUTH2), soukroma klicenka a docasny
HOME. Prohlizec nahrazuje fake_oauth.follow (nasleduje presmerovani jako prohlizec). Nikdy skutecny Google ani
Microsoft, zadne skutecne udaje.
"""
import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import http.server
import time
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_oauth as fo  # noqa: E402
import mailtest as mt  # noqa: E402
from test_service import inbox_rows  # noqa: E402

GMAIL = "tester@gmail.com"
OUTLOOK = "tester@outlook.com"


class OAuthBase(unittest.TestCase):
    rotate = False
    expires_in = 3600

    def setUp(self):
        self.s = mt.Session()
        self.gmail = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, personality="gmail", user=GMAIL,
                                   password="app-password-unused", oauth="OAUTHBEARER,XOAUTH2")
        self.outlook = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, personality="microsoft", user=OUTLOOK,
                                     password="never", oauth="XOAUTH2")
        self.google = fo.FakeOAuth(self.gmail, GMAIL, "test-google-client.apps.example", "GOCSPX-test-secret",
                                   expires_in=self.expires_in, rotate=False)
        self.ms = fo.FakeOAuth(self.outlook, OUTLOOK, "00000000-1111-2222-3333-444444444444", "", redirect_host="localhost",
                               expires_in=self.expires_in, rotate=self.rotate)
        self.s.env["LUXOS_MAIL_OAUTH_PROVIDERS"] = fo.providers_file(
            os.path.join(self.s.root, "oauth-providers.json"), google=self.google, microsoft=self.ms,
            google_imap=self.gmail.ports["tls"], microsoft_imap=self.outlook.ports["tls"])
        # kratka pauza pred poslednim pokusem zachrany "not connected" (jinak 3 s)
        self.s.env["LUXOS_MAIL_NOTCONNECTED_WAIT"] = "100"
        self.c = self.s.start_service()

    def tearDown(self):
        try:
            self.c.call("quit")
        except OSError:
            pass
        for x in (self.google, self.ms, self.gmail, self.outlook):
            x.stop()
        self.s.close()

    def accounts(self):
        path = os.path.join(self.s.env["XDG_CONFIG_HOME"], "luxos-mail", "accounts.json")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return json.load(f)

    def status(self, account):
        for st in self.c.call("hello")["accounts"]:
            if st["account"] == account:
                return st
        return {}

    def auth_log(self, server):
        return [l for l in server.control("log")["log"] if l.startswith("AUTH ")]

    def sign_in(self, provider, email="", **extra):
        r = self.c.call("oauth_start", provider=provider, email=email, **extra)
        self.assertTrue(r["ok"], (r, self.s.service_log()))
        self.c.events = [e for e in self.c.events if e.get("event") != "oauth_done"]
        page = fo.follow(r["url"])
        ev = self.c.wait_event(lambda e: e.get("event") == "oauth_done" and e.get("flow") == r["flow"], 30)
        self.assertIsNotNone(ev, self.s.service_log())
        return r, page, ev

    def assert_no_secrets_in_files(self, fake):
        secrets = [t.encode() for t in fake.secrets_seen()]
        self.assertTrue(secrets)
        for base in (os.path.join(self.s.env["XDG_CONFIG_HOME"], "luxos-mail"), os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail"),
                     os.path.join(self.s.env["XDG_CACHE_HOME"], "luxos-mail")):
            for root, dirs, files in os.walk(base):
                for name in files:
                    with open(os.path.join(root, name), "rb") as f:
                        data = f.read()
                    for sec in secrets:
                        self.assertNotIn(sec, data, name)
        log = self.s.service_log().encode()
        for sec in secrets:
            self.assertNotIn(sec, log)
        for server in (self.gmail, self.outlook):
            for line in server.control("log")["log"]:
                for sec in fake.secrets_seen():
                    self.assertNotIn(sec, line)


class GoogleOAuthTest(OAuthBase):
    def test_sign_in_with_google(self):
        r, page, ev = self.sign_in("google", GMAIL, name="Tester")
        # adresa pro prohlizec: PKCE S256, state, loopback 127.0.0.1 s nahodnym portem, offline pristup
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r["url"]).query))
        self.assertTrue(r["url"].startswith(self.google.origin + "/authorize?"))
        self.assertEqual(q["redirect_uri"], "http://127.0.0.1:%d/" % r["port"])
        self.assertEqual(q["code_challenge_method"], "S256")
        self.assertEqual(q["scope"], "https://mail.google.com/ openid email")
        self.assertEqual((q["access_type"], q["prompt"], q["login_hint"]), ("offline", "consent", GMAIL))
        self.assertGreaterEqual(len(q["state"]), 32)
        self.assertEqual(self.google.errors, [])
        # stranka v prohlizeci, v jazyce systemu (testy: cs_CZ)
        self.assertEqual(page[0], 200)
        self.assertIn('<html lang="cs">', page[1])
        self.assertIn("Jste přihlášeni", page[1])
        self.assertIn("Zpět do Pošty", page[1])
        self.assertIn("prefers-color-scheme:dark", page[1])
        self.assertEqual(page[2].get("cache-control"), "no-store")
        self.assertTrue(ev["ok"], ev)
        acc = ev["account"]
        a = self.accounts()[0]
        self.assertEqual((a["auth"], a["email"], a["provider"], a["name"]), ("oauth", GMAIL, "google", "Tester"))
        self.assertEqual(a["imap"], {"host": "localhost", "port": self.gmail.ports["tls"], "security": "ssl", "user": GMAIL})
        self.assertEqual(a["smtp"], {"host": "smtp.gmail.com", "port": 465, "security": "ssl", "user": GMAIL, "auth": "xoauth2"})
        self.assertEqual(a["oauth"]["client_id"], "test-google-client.apps.example")
        # tajemstvi klienta jde na koncovy bod tokenu (Desktop klient Google), kod jen jednou
        ex = self.google.exchanges()[0]
        self.assertEqual(ex["form"]["client_secret"], "GOCSPX-test-secret")
        self.assertEqual(ex["content_type"], "application/x-www-form-urlencoded")
        # obnovovaci token jen v klicence
        self.assertEqual(self.s.secret_lookup(acc), list(self.google.refresh_tokens.keys())[0])
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15), (self.status(acc), self.s.service_log()))
        self.assertTrue(mt.wait_for(lambda: len(inbox_rows(self.s, acc)) == 9, 10))
        auths = self.auth_log(self.gmail)
        self.assertTrue(auths[0].startswith("AUTH OAUTHBEARER user=%s" % GMAIL), auths)
        # overeni pri pridani + spojeni sluzby, obe s pristupovym tokenem z vymeny (zadne zbytecne obnoveni)
        self.assertEqual(len(self.google.refreshes()), 0)
        self.assert_no_secrets_in_files(self.google)
        # naslouchani po prihlaseni skoncilo
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", r["port"]), timeout=2).close()

    def test_new_mail_notification(self):
        r, page, ev = self.sign_in("google", GMAIL)
        acc = ev["account"]
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15))
        before = len(self.s.notifications())
        self.gmail.control("deliver INBOX " + os.path.join(mt.FIXTURES, "mixed-attachment.eml"))
        self.assertTrue(mt.wait_for(lambda: len(self.s.notifications()) > before, 10), self.s.service_log())

    def test_other_account_chosen_in_browser(self):
        # zadana adresa jina nez ucet, kterym se uzivatel v prohlizeci prihlasil: plati ucet z id_token
        r, page, ev = self.sign_in("google", "jiny@gmail.com")
        self.assertTrue(ev["ok"], ev)
        self.assertEqual(ev["email"], GMAIL)
        self.assertEqual(self.accounts()[0]["email"], GMAIL)

    def test_denied_in_browser(self):
        self.google.deny = True
        r, page, ev = self.sign_in("google", GMAIL)
        self.assertEqual((ev["ok"], ev["kind"]), (False, "oauth_denied"))
        self.assertIn("Přihlášení bylo zrušeno", page[1])
        self.assertEqual(self.accounts(), [])
        self.assertEqual(self.google.exchanges(), [])

    def test_wrong_state_is_ignored(self):
        r = self.c.call("oauth_start", provider="google", email=GMAIL)
        port = r["port"]
        # cizi stranka podvrhne kod se spatnym state: odmitnuto, prihlaseni bezi dal
        status, body, _ = fo.get("http://127.0.0.1:%d/?code=evil&state=%s" % (port, "x" * 32))
        self.assertEqual(status, 400)
        self.assertIn("přihlašovací stránka je zastaralá", body)
        status, body, _ = fo.get("http://127.0.0.1:%d/favicon.ico" % port)
        self.assertEqual(status, 404)
        self.assertEqual(self.google.exchanges(), [])
        page = fo.follow(r["url"])
        self.assertEqual(page[0], 200)
        ev = self.c.wait_event(lambda e: e.get("event") == "oauth_done", 20)
        self.assertTrue(ev["ok"], (ev, self.s.service_log()))

    def test_cancel_closes_listener(self):
        r = self.c.call("oauth_start", provider="google", email=GMAIL)
        socket.create_connection(("127.0.0.1", r["port"]), timeout=2).close()
        self.assertTrue(self.c.call("oauth_cancel", flow=r["flow"])["ok"])
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", r["port"]), timeout=2).close()
        # novy start nahradi stary (stary port zavreny)
        r1 = self.c.call("oauth_start", provider="google", email=GMAIL)
        r2 = self.c.call("oauth_start", provider="google", email=GMAIL)
        self.assertNotEqual(r1["port"], r2["port"])
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", r1["port"]), timeout=2).close()
        self.c.call("oauth_cancel")

    def test_refresh_token_revoked_asks_to_sign_in_again(self):
        r, page, ev = self.sign_in("google", GMAIL)
        acc = ev["account"]
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15))
        # heslo Google zmenene / pristup odebrany: obnovovaci token i pristupove tokeny neplati
        self.google.revoke_refresh()
        self.gmail.control("revoke")
        r = self.c.call("retry_account", account=acc)
        self.assertEqual((r["state"], r["kind"]), ("error", "oauth_expired"), self.s.service_log())
        n = len(self.google.refreshes())
        auths = len(self.auth_log(self.gmail))
        # zadne opakovani: akce v okne ani zmena site nezkousi znovu
        self.assertFalse(self.c.call("sync", account=acc, mailbox="INBOX")["ok"])
        self.c.call("reconnect")
        time.sleep(1.0)
        self.assertEqual(len(self.google.refreshes()), n)
        self.assertEqual(len(self.auth_log(self.gmail)), auths)
        # Prihlasit se znovu (stejny ucet): novy obnovovaci token, ucet zase online
        r2, page, ev = self.sign_in("google", account=acc)
        self.assertTrue(ev["ok"], (ev, self.s.service_log()))
        self.assertTrue(ev["reauth"])
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15), self.s.service_log())
        self.assertEqual(self.s.secret_lookup(acc), list(self.google.refresh_tokens.keys())[0])
        self.assertEqual(len(self.accounts()), 1)

    def test_reauth_with_other_account_refused(self):
        r, page, ev = self.sign_in("google", GMAIL)
        acc = ev["account"]
        self.google.email = "someone.else@gmail.com"
        r2, page, ev = self.sign_in("google", account=acc)
        self.assertEqual((ev["ok"], ev["kind"]), (False, "oauth_other_account"))
        self.assertEqual(self.accounts()[0]["email"], GMAIL)

    def test_cached_token_rejected_refreshes_once(self):
        r, page, ev = self.sign_in("google", GMAIL)
        acc = ev["account"]
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15))
        # pristupovy token jeste "plati" (expires_in 3600), ale server ho odmitne: jednou obnovit a znovu
        self.gmail.control("revoke")
        r = self.c.call("retry_account", account=acc)
        self.assertEqual(r["state"], "online", self.s.service_log())
        self.assertEqual(len(self.google.refreshes()), 1)
        f = self.google.refreshes()[0]["form"]
        self.assertEqual((f["client_id"], f["client_secret"]), ("test-google-client.apps.example", "GOCSPX-test-secret"))
        self.assertNotIn("scope", f)

    def test_restart_uses_keyring(self):
        r, page, ev = self.sign_in("google", GMAIL)
        acc = ev["account"]
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15))
        self.c.call("quit")
        time.sleep(0.5)
        self.c = self.s.start_service()
        # po spusteni zadny pristupovy token v pameti: obnoveni z klicenky
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15), self.s.service_log())
        self.assertEqual(len(self.google.refreshes()), 1)

    def test_remove_account_clears_keyring(self):
        r, page, ev = self.sign_in("google", GMAIL)
        acc = ev["account"]
        self.assertNotEqual(self.s.secret_lookup(acc), "")
        self.c.call("remove_account", account=acc)
        self.assertEqual(self.s.secret_lookup(acc), "")


class ExpiringTokenTest(OAuthBase):
    """Pristupovy token plati jen chvili: kazde nove spojeni ho predem obnovi."""
    expires_in = 60

    def test_refresh_before_connect(self):
        r, page, ev = self.sign_in("google", GMAIL)
        acc = ev["account"]
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15))
        n = len(self.google.refreshes())
        self.assertEqual(self.c.call("reconnect")["ok"], True)
        self.assertTrue(mt.wait_for(lambda: len(self.google.refreshes()) > n and self.status(acc).get("state") == "online", 15),
                        self.s.service_log())
        # IMAP dostal novy token (posledni vydany)
        self.assertEqual(self.c.call("sync", account=acc, mailbox="INBOX")["ok"], True)


class MicrosoftOAuthTest(OAuthBase):
    rotate = True

    def test_sign_in_with_microsoft(self):
        r, page, ev = self.sign_in("microsoft", OUTLOOK)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r["url"]).query))
        # Microsoft porovnava port jen u "localhost"
        self.assertEqual(q["redirect_uri"], "http://localhost:%d/" % r["port"])
        self.assertEqual(q["scope"], "https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send offline_access openid email")
        self.assertNotIn("access_type", q)
        self.assertTrue(ev["ok"], (ev, self.s.service_log()))
        acc = ev["account"]
        a = self.accounts()[0]
        self.assertEqual((a["provider"], a["auth"]), ("microsoft", "oauth"))
        self.assertEqual(a["smtp"], {"host": "smtp.office365.com", "port": 587, "security": "starttls", "user": OUTLOOK, "auth": "xoauth2"})
        # verejny klient: zadne tajemstvi
        self.assertNotIn("client_secret", self.ms.exchanges()[0]["form"])
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15), self.s.service_log())
        self.assertTrue(self.auth_log(self.outlook)[0].startswith("AUTH XOAUTH2 user=%s" % OUTLOOK))
        # rotace obnovovaciho tokenu: novy se ulozi do klicenky
        first = self.s.secret_lookup(acc)
        self.outlook.control("revoke")
        self.assertEqual(self.c.call("retry_account", account=acc)["state"], "online", self.s.service_log())
        f = self.ms.refreshes()[0]["form"]
        # obnoveni jen s rozsahy Outlooku (bez OpenID): pristupovy token vzdy pro https://outlook.office.com
        self.assertEqual(f["scope"], "https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send offline_access")
        second = self.s.secret_lookup(acc)
        self.assertNotEqual(first, second)
        self.assertEqual(second, list(self.ms.refresh_tokens.keys())[0])
        self.assert_no_secrets_in_files(self.ms)

    def test_username_without_email_claim(self):
        # pracovni ucet bez "email" v id_token: zadana adresa
        self.ms.email_claim = False
        r, page, ev = self.sign_in("microsoft", OUTLOOK)
        self.assertTrue(ev["ok"], ev)
        self.assertEqual(self.accounts()[0]["email"], OUTLOOK)


ALIAS = "tester.alias@outlook.com"


class MicrosoftNotConnectedTest(OAuthBase):
    """"User is authenticated but not connected." (Microsoft prijal token, schranku neotevrel): zachrana ve sluzbe
    (jina adresa, token jen pro Outlook, /consumers, nahradni server, pauza) a jeji zaznam v logu bez tokenu."""
    rotate = True

    def setUp(self):
        self.alt = None
        super().setUp()

    def with_alternate(self, oauth="XOAUTH2", personality="microsoft"):
        # nahradni server (jako imap-mail.outlook.com); tokeny dostava od falesneho Microsoftu taky
        self.alt = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, personality=personality, user=OUTLOOK,
                                 password="never", oauth=oauth)
        self.ms.imaps.append(self.alt)
        self.c.call("quit")
        time.sleep(0.3)
        self.s.env["LUXOS_MAIL_OAUTH_PROVIDERS"] = fo.providers_file(
            os.path.join(self.s.root, "oauth-providers.json"), google=self.google, microsoft=self.ms,
            google_imap=self.gmail.ports["tls"], microsoft_imap=self.outlook.ports["tls"], microsoft_alt_imap=self.alt.ports["tls"])
        self.c = self.s.start_service()

    def tearDown(self):
        super().tearDown()
        if self.alt is not None:
            self.alt.stop()

    def test_graph_token_recovered_with_outlook_scope(self):
        # token z vymeny kodu (rozsahy s openid/email) je pro Graph: AUTHENTICATE -> BAD not connected;
        # obnoveni jen s rozsahy Outlooku da spravny token
        self.ms.graph_when_oidc = True
        r, page, ev = self.sign_in("microsoft", OUTLOOK)
        self.assertTrue(ev["ok"], (ev, self.s.service_log()))
        self.assertEqual(self.ms.issued[:2], ["graph", "outlook"])
        f = self.ms.refreshes()[0]["form"]
        self.assertNotIn("openid", f["scope"].split())
        self.assertNotIn("email", f["scope"].split())
        self.assertIn("variant 'outlook-scope' on localhost", self.s.service_log())
        acc = ev["account"]
        self.assertEqual(self.accounts()[0]["email"], OUTLOOK)
        # rotovany obnovovaci token ze zachrany je v klicence
        self.assertEqual(self.s.secret_lookup(acc), list(self.ms.refresh_tokens.keys())[0])
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15), self.s.service_log())
        auths = self.auth_log(self.outlook)
        self.assertTrue(all(a.startswith("AUTH XOAUTH2 user=%s " % OUTLOOK) for a in auths), auths)
        # dalsi obnoveni (novy start sluzby) zase jen s rozsahy Outlooku: hned online, zadna dalsi zachrana
        self.c.call("quit")
        time.sleep(0.3)
        self.c = self.s.start_service()
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15), self.s.service_log())
        self.assertEqual(self.ms.issued[-1], "outlook")
        self.assert_no_secrets_in_files(self.ms)

    def test_alias_address_recovered(self):
        # v prohlizeci prihlaseni aliasem: id_token email = alias, preferred_username = hlavni adresa schranky
        self.ms.email = ALIAS
        self.ms.username = OUTLOOK
        self.outlook.control("primary %s %s" % (ALIAS, OUTLOOK))
        r, page, ev = self.sign_in("microsoft", ALIAS)
        self.assertTrue(ev["ok"], (ev, self.s.service_log()))
        self.assertEqual(ev["email"], OUTLOOK)
        a = self.accounts()[0]
        self.assertEqual((a["email"], a["imap"]["user"], a["smtp"]["user"]), (OUTLOOK, OUTLOOK, OUTLOOK))
        self.assertIn("variant 'address'", self.s.service_log())
        auths = self.auth_log(self.outlook)
        self.assertTrue(auths[0].startswith("AUTH XOAUTH2 user=%s " % ALIAS), auths)
        self.assertTrue(auths[1].startswith("AUTH XOAUTH2 user=%s " % OUTLOOK), auths)
        acc = ev["account"]
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15), self.s.service_log())
        # zadne zbytecne obnoveni (stacila jina adresa)
        self.assertEqual(len(self.ms.refreshes()), 0)

    def test_alternate_host_recovered(self):
        # hlavni server: AUTHENTICATE OK, ale LIST -> BAD not connected (chyba az u dalsiho prikazu);
        # nahradni server nabizi i OAUTHBEARER, Microsoft ale vzdy XOAUTH2
        self.with_alternate(oauth="OAUTHBEARER,XOAUTH2", personality="")
        self.outlook.control("ncstyle after")
        self.outlook.control("notconnected on")
        r, page, ev = self.sign_in("microsoft", OUTLOOK)
        self.assertTrue(ev["ok"], (ev, self.s.service_log()))
        a = self.accounts()[0]
        self.assertEqual(a["imap"], {"host": "localhost", "port": self.alt.ports["tls"], "security": "ssl", "user": OUTLOOK})
        self.assertIn("variant 'host' on localhost", self.s.service_log())
        # cestou zkouseny i token jen pro Outlook a /consumers
        paths = [t["path"] for t in self.ms.refreshes()]
        self.assertIn("/token", paths)
        self.assertIn("/consumers/token", paths)
        acc = ev["account"]
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15), self.s.service_log())
        self.assertTrue(all(x.startswith("AUTH XOAUTH2 ") for x in self.auth_log(self.alt)), self.auth_log(self.alt))
        self.assert_no_secrets_in_files(self.ms)

    def test_existing_account_moves_to_alternate_host(self):
        self.with_alternate()
        r, page, ev = self.sign_in("microsoft", OUTLOOK)
        acc = ev["account"]
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15), self.s.service_log())
        # pozdeji hlavni server prestane schranku otevirat: novy pokus se sam presune na nahradni server
        self.outlook.control("notconnected on")
        self.c.call("quit")
        time.sleep(0.3)
        self.c = self.s.start_service()
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 20), self.s.service_log())
        self.assertEqual(self.accounts()[0]["imap"]["port"], self.alt.ports["tls"])
        self.assertIn("account %s: mailbox connected with variant 'host'" % acc, self.s.service_log())

    def test_nothing_helps(self):
        # IMAP vypnuty u uctu (vsechny servery): zadna varianta nepomuze -> chyba notconnected, zadny ucet
        self.with_alternate()
        self.outlook.control("notconnected on")
        self.alt.control("notconnected on")
        r, page, ev = self.sign_in("microsoft", OUTLOOK)
        self.assertEqual((ev["ok"], ev["kind"]), (False, "notconnected"), ev)
        self.assertIn("not connected", ev["error"])
        self.assertEqual(self.accounts(), [])
        log = self.s.service_log()
        self.assertIn("mailbox not connected, nothing helped", log)
        for variant in ("outlook-scope", "consumers", "host localhost", "retry"):
            self.assertIn(variant, log)
        self.assert_no_secrets_in_files(self.ms)

    def test_existing_account_not_connected_is_not_retried_forever(self):
        self.with_alternate()
        r, page, ev = self.sign_in("microsoft", OUTLOOK)
        acc = ev["account"]
        self.assertTrue(mt.wait_for(lambda: self.status(acc).get("state") == "online", 15))
        self.outlook.control("notconnected on")
        self.alt.control("notconnected on")
        r = self.c.call("retry_account", account=acc)
        self.assertEqual((r["state"], r["kind"]), ("error", "notconnected"), self.s.service_log())
        n = len(self.auth_log(self.outlook))
        self.c.call("reconnect")
        time.sleep(1.0)
        self.assertEqual(len(self.auth_log(self.outlook)), n)


class DiagnoseTest(OAuthBase):
    """luxos-mail --diagnose-oauth ADRESA: varianty a odpovedi serveru, nikdy tokeny."""

    def diagnose(self, *args, browser=True):
        env = dict(self.s.env)
        urls = os.path.join(self.s.root, "urls.txt")
        env["LUXOS_MAIL_OPEN_URL_LOG"] = urls
        p = subprocess.Popen([mt.binary(), "--diagnose-oauth"] + list(args), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if browser:
            self.assertTrue(mt.wait_for(lambda: os.path.exists(urls) and open(urls).read().strip(), 20))
            fo.follow(open(urls).read().strip().splitlines()[-1])
        out, err = p.communicate(timeout=60)
        text = out.decode()
        for sec in self.ms.secrets_seen():
            self.assertNotIn(sec, text)
            self.assertNotIn(sec, err.decode())
        return p.returncode, text

    def test_fresh_sign_in_report(self):
        self.ms.graph_when_oidc = True
        code, text = self.diagnose(OUTLOOK)
        self.assertEqual(code, 0, text)
        self.assertIn("provider: Microsoft", text)
        self.assertIn("SASL mechanism: XOAUTH2", text)
        self.assertIn("new sign-in in the browser", text)
        self.assertIn("id_token email = te***r@outlook.com (same as typed)", text)
        self.assertNotIn(OUTLOOK, text)
        self.assertRegex(text, r"initial te\*\*\*r@outlook.com @localhost -> notconnected: User is authenticated but not connected")
        self.assertRegex(text, r"outlook-scope te\*\*\*r@outlook.com @localhost -> OK")
        self.assertIn("RESULT: the mailbox opens with variant 'outlook-scope'", text)
        # nic ulozeno
        self.assertEqual(self.accounts(), [])

    def test_stored_sign_in_and_nothing_helps(self):
        r, page, ev = self.sign_in("microsoft", OUTLOOK)
        acc = ev["account"]
        self.outlook.control("notconnected on")
        code, text = self.diagnose(OUTLOOK, browser=False)
        self.assertEqual(code, 1, text)
        self.assertIn("stored in the keyring (account %s)" % acc, text)
        self.assertIn("RESULT: Microsoft accepts the token but does not open the mailbox", text)
        self.assertIn("account.live.com/activity", text)
        # rotovany obnovovaci token ulozen zpet (ucet dal funguje)
        self.assertEqual(self.s.secret_lookup(acc), list(self.ms.refresh_tokens.keys())[-1])

    def test_usage(self):
        r = mt.run_bin(["--diagnose-oauth"], env=self.s.env)
        self.assertEqual(r.returncode, 2)
        self.assertIn(b"Usage:", r.stdout)


class NotConfiguredTest(unittest.TestCase):
    def test_empty_client_id(self):
        s = mt.Session()
        try:
            c = s.start_service()
            # baliku se dodava bez client ID: zadny poskytovatel s tlacitkem
            self.assertEqual(c.call("oauth_providers")["providers"], [])
            r = c.call("oauth_start", provider="google", email=GMAIL)
            self.assertEqual((r["ok"], r["kind"]), (False, "oauth_config"))
            r = c.call("oauth_start", provider="nonsense")
            self.assertEqual(r["kind"], "oauth_config")
            c.call("quit")
        finally:
            s.close()


class Remote(http.server.BaseHTTPRequestHandler):
    body = b""
    hits = 0

    def do_GET(self):
        Remote.hits += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(Remote.body)

    def log_message(self, *args):
        pass


class ConfigTest(unittest.TestCase):
    """Data poskytovatelu: kontrola, prepsani spravcem, ID ze serveru LuxOS (jen ID, jen kde chybi)."""

    def setUp(self):
        self.s = mt.Session(keyring=False, notifications=False)
        self.http = http.server.HTTPServer(("127.0.0.1", 0), Remote)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.s.env["LUXOS_MAIL_OAUTH_REMOTE"] = "http://127.0.0.1:%d/mail-oauth.json" % self.http.server_address[1]
        Remote.hits = 0

    def tearDown(self):
        self.http.shutdown()
        self.s.close()

    def providers(self):
        r = mt.run_bin(["--test-oauth-providers"], env=self.s.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_shipped_file_has_no_ids(self):
        with open(fo.path_of_shipped()) as f:
            data = json.load(f)
        for p in data["providers"].values():
            self.assertEqual(p["client_id"], "")
            self.assertEqual(p["client_secret"], "")
            self.assertTrue(p["auth_url"].startswith("https://"))
            self.assertTrue(p["token_url"].startswith("https://"))
        out = self.providers()["providers"]
        self.assertEqual(sorted(out), ["aol", "google", "microsoft", "yahoo"])
        self.assertFalse(any(p["available"] for p in out.values()))
        self.assertEqual(out["google"]["imap"], {"host": "imap.gmail.com", "port": 993, "security": "ssl"})
        self.assertEqual(out["microsoft"]["smtp"], {"host": "smtp.office365.com", "port": 587, "security": "starttls"})
        self.assertEqual(out["microsoft"]["redirect_host"], "localhost")

    def test_admin_override(self):
        with open(self.s.env["LUXOS_MAIL_OAUTH_ADMIN"], "w") as f:
            json.dump({"providers": {"microsoft": {"client_id": "abc-123"}, "google": {"client_id": "x.apps.example"},
                                     "yahoo": {"client_id": "y", "client_secret": "z"}}}, f)
        out = self.providers()["providers"]
        self.assertTrue(out["microsoft"]["available"])
        # Google bez tajemstvi klienta nejde (Desktop klient ho vyzaduje); Yahoo je vypnute
        self.assertFalse(out["google"]["available"])
        self.assertFalse(out["yahoo"]["available"])
        # neplatne hodnoty spravce: polozka se zahodi (ne polovicni konfigurace)
        with open(self.s.env["LUXOS_MAIL_OAUTH_ADMIN"], "w") as f:
            json.dump({"providers": {"microsoft": {"client_id": "abc 123\n"}, "google": {"token_url": "http://evil.example/token"}}}, f)
        out = self.providers()["providers"]
        self.assertNotIn("microsoft", out)
        self.assertNotIn("google", out)

    def test_remote_ids_fill_only_missing(self):
        self.assertTrue(self.providers()["remote_due"])
        Remote.body = json.dumps({"version": 1, "providers": {
            "microsoft": {"client_id": "remote-ms-id", "token_url": "https://evil.example/token", "auth_url": "https://evil.example/a"},
            "google": {"client_id": "remote.apps.example", "client_secret": "GOCSPX-remote"},
            "evil": {"client_id": "x"}, "yahoo": {"client_id": "bad id with spaces"}}}).encode()
        r = mt.run_bin(["--oauth-config"], env=self.s.env)
        self.assertEqual(json.loads(r.stdout)["ok"], True, r.stderr)
        self.assertEqual(Remote.hits, 1)
        out = self.providers()
        p = out["providers"]
        self.assertEqual((p["microsoft"]["client_id"], p["microsoft"]["available"]), ("remote-ms-id", True))
        self.assertEqual(p["google"]["client_id"], "remote.apps.example")
        self.assertTrue(p["google"]["available"])
        # koncove body ze serveru se nikdy nepouziji
        self.assertEqual(p["microsoft"]["token_url"], "https://login.microsoftonline.com/common/oauth2/v2.0/token")
        self.assertEqual(p["yahoo"]["client_id"], "")
        # mezipamet obsahuje jen zkontrolovana ID
        with open(os.path.join(self.s.env["XDG_CACHE_HOME"], "luxos-mail", "mail-oauth.json")) as f:
            cached = f.read()
        self.assertNotIn("evil", cached)
        self.assertNotIn("bad id", cached)
        # spravce ma prednost a ID z baliku/spravce se nikdy nenahradi stazenym
        with open(self.s.env["LUXOS_MAIL_OAUTH_ADMIN"], "w") as f:
            json.dump({"providers": {"microsoft": {"client_id": "admin-ms-id"}}}, f)
        self.assertEqual(self.providers()["providers"]["microsoft"]["client_id"], "admin-ms-id")

    def test_remote_invalid_and_disabled(self):
        Remote.body = b"<html>not json</html>"
        r = mt.run_bin(["--oauth-config"], env=self.s.env)
        self.assertEqual(json.loads(r.stdout)["ok"], False)
        self.assertFalse(os.path.exists(os.path.join(self.s.env["XDG_CACHE_HOME"], "luxos-mail", "mail-oauth.json")))
        # spravce stahovani vypne
        with open(self.s.env["LUXOS_MAIL_OAUTH_ADMIN"], "w") as f:
            json.dump({"remote": False}, f)
        hits = Remote.hits
        r = mt.run_bin(["--oauth-config"], env=self.s.env)
        self.assertEqual(json.loads(r.stdout), {"ok": False, "error": "disabled"})
        self.assertEqual(Remote.hits, hits)
        self.assertFalse(self.providers()["remote_due"])


if __name__ == "__main__":
    unittest.main()
