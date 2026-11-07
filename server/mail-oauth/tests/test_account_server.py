"""Testy upravy serveru uctu LuxAI pro Postu LuxOS (mistne, falesna data):

    LUX_ACCOUNT_SERVER_JS=/cesta/k/kopii/server.js python3 -m unittest test_account_server

/api/mail/mailboxes (kdo vidi kterou schranku), /api/mail/token, /oauth/introspect (RFC 7662 pro Dovecot)
a regrese existujicich cest (/health, /api/me, /oauth/userinfo, /api/ide/logout).
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import account_server as acc  # noqa: E402


@unittest.skipUnless(os.path.isfile(os.environ.get("LUX_ACCOUNT_SERVER_JS", "")), "needs LUX_ACCOUNT_SERVER_JS (local copy of server.js)")
class AccountServerTest(unittest.TestCase):
    def setUp(self):
        self.srv = acc.AccountServer(acc.default_mailboxes())

    def tearDown(self):
        self.srv.close()

    def token(self, session="admin", address="info@lux-ai.test"):
        status, body = self.srv.request("POST", "/api/mail/token", {"address": address}, session=session)
        self.assertEqual(status, 200, body)
        return body

    # ---- seznam schranek ----

    def test_patch_idempotent_and_syntax(self):
        self.assertIn("patched", self.srv.patch_output)
        out = subprocess.run([sys.executable, "-I", acc.PATCH, self.srv.js], capture_output=True, text=True, check=True)
        self.assertIn("already patched", out.stdout)
        check = os.path.join(self.srv.root, "check.cjs")
        with open(self.srv.js) as f, open(check, "w") as g:
            g.write(f.read())
        subprocess.run(["node", "--check", check], check=True)

    def test_mailboxes_admin_sees_mapped_mailbox(self):
        status, body = self.srv.request("GET", "/api/mail/mailboxes", session="admin")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"mailboxes": [{"address": "info@lux-ai.test", "display_name": "LuxAI",
                                               "imap": {"host": "mail.lux-ai.test", "port": 993, "security": "ssl"},
                                               "smtp": {"host": "mail.lux-ai.test", "port": 465, "security": "ssl"},
                                               "auth": "luxai-oauth", "mechanisms": ["OAUTHBEARER", "XOAUTH2"]}]})

    def test_mailboxes_by_user_id_and_invalid_entries_skipped(self):
        status, body = self.srv.request("GET", "/api/mail/mailboxes", session="user")
        self.assertEqual(status, 200)
        self.assertEqual([m["address"] for m in body["mailboxes"]], ["team@lux-ai.test"])

    def test_group_requirement(self):
        # e-mail sedi, ale ucet neni ve skupine luxai-admin (stejne pravidlo jako webmail)
        cfg = acc.default_mailboxes()
        cfg["mailboxes"][0]["emails"] = [acc.USER_EMAIL]
        self.srv.write_mailboxes(cfg)
        status, body = self.srv.request("GET", "/api/mail/mailboxes", session="user")
        self.assertEqual([m["address"] for m in body["mailboxes"]], ["team@lux-ai.test"])
        status, body = self.srv.request("GET", "/api/mail/mailboxes", session="admin")
        self.assertEqual(body["mailboxes"], [])

    def test_mailboxes_requires_native_client_and_session(self):
        self.assertEqual(self.srv.request("GET", "/api/mail/mailboxes", session="admin", client=None)[0], 403)
        self.assertEqual(self.srv.request("GET", "/api/mail/mailboxes", session="admin", client="evil")[0], 403)
        self.assertEqual(self.srv.request("GET", "/api/mail/mailboxes")[0], 401)
        self.assertEqual(self.srv.request("GET", "/api/mail/mailboxes", session="no-such-session")[0], 401)
        self.assertEqual(self.srv.request("GET", "/api/mail/mailboxes", session="susp")[0], 401)
        self.assertEqual(self.srv.request("GET", "/api/mail/mailboxes", session="unver")[0], 401)
        for client in ("lsl-ide", "lux-code", "luxai"):
            self.assertEqual(self.srv.request("GET", "/api/mail/mailboxes", session="admin", client=client)[0], 200)

    def test_missing_or_broken_mapping_file(self):
        os.unlink(self.srv.mailboxes_file)
        status, body = self.srv.request("GET", "/api/mail/mailboxes", session="admin")
        self.assertEqual((status, body), (200, {"mailboxes": []}))
        with open(self.srv.mailboxes_file, "w") as f:
            f.write("{not json")
        status, body = self.srv.request("GET", "/api/mail/mailboxes", session="admin")
        self.assertEqual((status, body), (200, {"mailboxes": []}))
        self.assertEqual(self.srv.request("POST", "/api/mail/token", {"address": "info@lux-ai.test"}, session="admin")[0], 403)

    def test_bad_server_settings_hide_mailbox(self):
        cfg = acc.default_mailboxes(security="plain")
        self.srv.write_mailboxes(cfg)
        status, body = self.srv.request("GET", "/api/mail/mailboxes", session="admin")
        self.assertEqual(body["mailboxes"], [])

    # ---- tokeny a introspekce ----

    def test_token_and_introspection(self):
        t = self.token()
        self.assertEqual(t["token_type"], "Bearer")
        self.assertEqual(t["address"], "info@lux-ai.test")
        self.assertEqual(t["expires_in"], 900)
        self.assertGreaterEqual(len(t["access_token"]), 40)
        status, body = self.srv.introspect(t["access_token"])
        self.assertEqual(status, 200)
        self.assertTrue(body["active"])
        self.assertEqual(body["username"], "info@lux-ai.test")
        self.assertEqual(body["sub"], acc.ADMIN_ID)
        self.assertEqual(body["exp"] - body["iat"], 900)
        # session token se v logu nikdy neobjevi, mail token taky ne
        log = self.srv.read_log()
        self.assertNotIn(t["access_token"], log)
        self.assertNotIn(self.srv.tokens["admin"], log)

    def test_token_case_insensitive_address(self):
        t = self.token("user", "TEAM@lux-ai.test")
        self.assertEqual(t["address"], "team@lux-ai.test")

    def test_token_denied_for_foreign_mailbox(self):
        self.assertEqual(self.srv.request("POST", "/api/mail/token", {"address": "team@lux-ai.test"}, session="admin")[0], 403)
        self.assertEqual(self.srv.request("POST", "/api/mail/token", {"address": "info@lux-ai.test"}, session="user")[0], 403)
        self.assertEqual(self.srv.request("POST", "/api/mail/token", {"address": "info@lux-ai.test"}, session="admin", client=None)[0], 403)
        self.assertEqual(self.srv.request("POST", "/api/mail/token", {"address": "info@lux-ai.test"})[0], 401)
        self.assertEqual(self.srv.request("POST", "/api/mail/token", "[]", session="admin")[0], 400)

    def test_introspection_unknown_and_garbage(self):
        for token in ("", "x", "A" * 43, "A" * 600):
            status, body = self.srv.introspect(token)
            self.assertEqual((status, body), (200, {"active": False}), token[:10])

    def test_introspection_client_auth(self):
        t = self.token()["access_token"]
        self.assertEqual(self.srv.introspect(t, secret="wrong")[0], 401)
        self.assertEqual(self.srv.introspect(t, client_id="lux-mail")[0], 401)
        self.assertEqual(self.srv.introspect(t, secret="")[0], 401)
        # pres reverzni proxy (Caddy prida X-Forwarded-For) cesta "neexistuje"
        self.assertEqual(self.srv.introspect(t, headers={"X-Forwarded-For": "203.0.113.5"})[0], 404)
        self.assertEqual(self.srv.introspect(t, headers={"Forwarded": "for=203.0.113.5"})[0], 404)
        self.assertEqual(self.srv.introspect(t, headers={"X-Real-IP": "203.0.113.5"})[0], 404)
        # GET neni introspekce
        self.assertEqual(self.srv.request("GET", "/oauth/introspect?token=" + t, client=None)[0], 404)
        # a token je porad platny
        self.assertTrue(self.srv.introspect(t)[1]["active"])

    def test_logout_revokes_token(self):
        t = self.token()["access_token"]
        other = self.token("admin2")["access_token"]
        status, _ = self.srv.request("POST", "/api/ide/logout", session="admin")
        self.assertEqual(status, 200)
        self.assertEqual(self.srv.introspect(t)[1], {"active": False})
        # token jine relace tehoz uctu plati dal
        self.assertTrue(self.srv.introspect(other)[1]["active"])

    def test_mapping_change_revokes_token(self):
        t = self.token()["access_token"]
        cfg = acc.default_mailboxes()
        cfg["mailboxes"][0]["emails"] = []
        self.srv.write_mailboxes(cfg)
        self.assertEqual(self.srv.introspect(t)[1], {"active": False})
        # vraceni mapovani token neobnovi (byl smazan)
        self.srv.write_mailboxes(acc.default_mailboxes())
        self.assertEqual(self.srv.introspect(t)[1], {"active": False})

    def test_token_rate_limit(self):
        codes = [self.srv.request("POST", "/api/mail/token", {"address": "info@lux-ai.test"}, session="admin")[0] for _ in range(32)]
        self.assertEqual(codes[:30], [200] * 30)
        self.assertEqual(codes[30:], [429, 429])

    def test_introspection_disabled_without_secret(self):
        srv2 = acc.AccountServer(acc.default_mailboxes(), {"MAIL_INTROSPECTION_SECRET": ""})
        try:
            status, body = srv2.request("POST", "/api/mail/token", {"address": "info@lux-ai.test"}, session="admin")
            self.assertEqual(status, 200)
            self.assertEqual(srv2.introspect(body["access_token"], secret="")[0], 404)
            self.assertEqual(srv2.introspect(body["access_token"])[0], 404)
        finally:
            srv2.close()

    # ---- regrese ----

    def test_existing_endpoints(self):
        self.assertEqual(self.srv.request("GET", "/health", client=None)[0], 200)
        status, body = self.srv.request("GET", "/api/me", session="admin")
        self.assertEqual(status, 200)
        self.assertEqual(body["user"]["email"], acc.ADMIN_EMAIL)
        self.assertEqual(self.srv.request("GET", "/api/me")[1], {"user": None})
        # mail token neni OIDC access token (userinfo ho nepřijme)
        t = self.token()["access_token"]
        self.assertEqual(self.srv.request("GET", "/oauth/userinfo", headers={"Authorization": "Bearer " + t}, client=None)[0], 401)
        status, body = self.srv.request("GET", "/.well-known/openid-configuration", client=None)
        self.assertEqual(status, 200)
        self.assertEqual(body["issuer"], "https://lux-ai.test")
        self.assertEqual(self.srv.request("GET", "/api/mail/nothing", session="admin")[0], 404)


if __name__ == "__main__":
    unittest.main()
