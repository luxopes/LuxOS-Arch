#!/usr/bin/env python3
"""LuxOS - testy knihovny luxai_account proti lokalni napodobe serveru (bez site, bez skutecnych uctu).

    python3 packages/luxos-account/tests/test_luxai_account.py -v
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "files"))
from mock_luxai import TERMS_HTML, MockLuxAI  # noqa: E402

SRV = MockLuxAI().start()
TMP = tempfile.mkdtemp(prefix="luxai-test-")
os.environ["LUXAI_ORIGIN"] = SRV.origin           # pred importem knihovny (ORIGIN se cte pri importu)
os.environ["XDG_CONFIG_HOME"] = TMP
import luxai_account as acc  # noqa: E402

GOOD_PW = "correct horse battery"


class Base(unittest.TestCase):
    def setUp(self):
        SRV.accounts.clear()
        SRV.pending.clear()
        SRV.last_sent.clear()
        SRV.log.clear()
        SRV.sent_codes.clear()
        SRV.allow_native = True
        acc.forget()

    def err(self, fn, *args):
        with self.assertRaises(acc.AccountError) as cm:
            fn(*args)
        return cm.exception


class Register(Base):
    def test_origin_points_to_mock(self):
        self.assertEqual(acc.ORIGIN, SRV.origin)
        self.assertEqual(acc.REGISTER_URL, SRV.origin + "/register")

    def test_register_success_then_code_creates_account(self):
        r = acc.register_start("  Jana@Example.CZ ", GOOD_PW, "  Jana Test ")
        self.assertEqual(r, {"ok": True})
        method, path, body, client = SRV.log[-1]
        self.assertEqual((method, path, client), ("POST", "/api/auth/register/start", "luxos"))
        self.assertEqual(body, {"email": "jana@example.cz", "password": GOOD_PW, "displayName": "Jana Test",
                                "termsAccepted": True})
        self.assertEqual(SRV.sent_codes, [("jana@example.cz", "123456")])
        self.assertNotIn("jana@example.cz", SRV.accounts, "ucet vznikne az po overeni kodu")
        data = acc.verify_code("jana@example.cz", " 123456 ")
        self.assertTrue(data["sessionToken"])
        self.assertEqual(data["user"]["email"], "jana@example.cz")
        self.assertEqual(data["user"]["displayName"], "Jana Test")
        self.assertEqual(data["client"], "luxos")
        self.assertEqual(data["origin"], SRV.origin)
        self.assertIn("jana@example.cz", SRV.accounts)
        self.assertIsNone(acc.load(), "verify_code nesmi ukladat ucet (instalator ho preda do systemu)")
        # novy ucet se pak prihlasi i heslem
        self.assertTrue(acc.login_password("jana@example.cz", GOOD_PW)["sessionToken"])

    def test_display_name_trimmed_to_max(self):
        acc.register_start("long@example.cz", GOOD_PW, "x" * 200)
        self.assertEqual(len(SRV.log[-1][2]["displayName"]), acc.NAME_MAX)

    def test_local_validation_without_request(self):
        self.assertEqual(self.err(acc.register_start, "nonsense", GOOD_PW, "A").code, "invalid_email")
        self.assertEqual(self.err(acc.register_start, "a@b.cz", "short", "A").code, "weak_password")
        self.assertEqual(self.err(acc.register_start, "a@b.cz", "x" * 129, "A").code, "weak_password")
        self.assertEqual(SRV.log, [], "lokalni chyby nic neposilaji")
        self.assertEqual(acc.password_problem("x" * 12), "")
        self.assertEqual(acc.password_problem("x" * 11), "weak_password")

    def test_server_errors(self):
        cases = [("a@x", "invalid_email", 400),               # projde lokalne (obsahuje @), server odmitne
                 ("a@blocked.test", "email_domain_blocked", 400),
                 ("a@review.test", "email_domain_review", 422),
                 ("a@down.test", "email_domain_check_unavailable", 503),
                 ("a@busy.test", "rate", 429)]
        for email, code, status in cases:
            with self.subTest(code=code):
                e = self.err(acc.register_start, email, GOOD_PW, "A")
                self.assertEqual((e.code, e.status), (code, status))
                self.assertTrue(acc.error_text(e))
                self.assertNotIn("(%s)" % code, acc.error_text(e), "znamy kod ma vlastni hlasku")

    def test_account_exists(self):
        SRV.accounts["old@example.cz"] = {"password": GOOD_PW, "displayName": "Old"}
        e = self.err(acc.register_start, "old@example.cz", GOOD_PW, "Old")
        self.assertEqual((e.code, e.status), ("account_exists", 409))
        self.assertIn("Sign in", acc.error_text(e))

    def test_slow_down_retry_after(self):
        acc.register_start("slow@example.cz", GOOD_PW, "S")
        e = self.err(acc.register_start, "slow@example.cz", GOOD_PW, "S")
        self.assertEqual((e.code, e.status, e.retry_after), ("slow_down", 429, 60))

    def test_terms_required_carries_version(self):
        # knihovna posila termsAccepted vzdy true; overeni, ze server-side chyba se precte i s daty
        e = self.err(acc.request, "POST", "/api/auth/register/start",
                     {"email": "t@example.cz", "password": GOOD_PW, "displayName": "T"})
        self.assertEqual(e.code, "terms_required")
        self.assertEqual(e.data.get("termsVersion"), acc.TERMS_VERSION)
        self.assertIn("Terms", acc.error_text(e))

    def test_origin_forbidden_friendly(self):
        SRV.allow_native = False
        e = self.err(acc.register_start, "n@example.cz", GOOD_PW, "N")
        self.assertEqual((e.code, e.status), ("origin", 403))
        text = acc.error_text(e)
        self.assertIn(SRV.origin + "/register", text)
        self.assertIn("not available yet", text)
        # prekladova funkce se pouzije na sablonu, URL se doplni az potom
        self.assertIn("/register", acc.error_text(e, lambda t: "PREKLAD %s" if "%s" in t else t))

    def test_network_error(self):
        old = acc.ORIGIN
        try:
            e = self.err(acc.request, "POST", "/api/auth/register/start", {}, None, "http://127.0.0.1:9")
            self.assertEqual(e.code, "network")
        finally:
            acc.ORIGIN = old
        self.assertIn("internet", acc.error_text(e))

    def test_not_sent_request_is_retried(self):
        """Spojeni nevzniklo (DNS hned po pripojeni k Wi-Fi): pozadavek se zopakuje, uzivatel chybu nevidi."""
        calls = []
        real_send, real_sleep = acc._send, acc.time.sleep

        def flaky(req, timeout):
            calls.append(req.full_url)
            if len(calls) < 3:
                raise acc._NotSent()
            return {"ok": True}
        acc._send, acc.time.sleep = flaky, lambda _s: None
        try:
            self.assertEqual(acc.request("GET", "/x"), {"ok": True})
            self.assertEqual(len(calls), 3)
        finally:
            acc._send, acc.time.sleep = real_send, real_sleep

    def test_not_sent_classification(self):
        import errno
        import socket
        import urllib.error
        self.assertTrue(acc._not_sent(urllib.error.URLError(socket.gaierror(-3, "Temporary failure"))))
        self.assertTrue(acc._not_sent(urllib.error.URLError(ConnectionRefusedError())))
        self.assertTrue(acc._not_sent(urllib.error.URLError(OSError(errno.ENETUNREACH, "unreachable"))))
        self.assertFalse(acc._not_sent(TimeoutError()))   # mohl dojit - neopakovat (dvojity e-mail s kodem)

    def test_unknown_and_server_error_texts(self):
        self.assertEqual(acc.error_text(acc.AccountError("weird", 400)), "Sign-in failed (weird).")
        self.assertIn("problems", acc.error_text(acc.AccountError("http", 502)))


class CodeLogin(Base):
    def setUp(self):
        super().setUp()
        SRV.accounts["jan@example.cz"] = {"password": GOOD_PW, "displayName": "Jan"}

    def test_request_always_ok(self):
        self.assertEqual(acc.request_code("nobody@example.cz"), {"ok": True})
        self.assertEqual(SRV.sent_codes, [])
        self.assertEqual(acc.request_code("jan@example.cz"), {"ok": True})
        self.assertEqual(SRV.sent_codes, [("jan@example.cz", "123456")])

    def test_invalid_then_valid_code(self):
        acc.request_code("jan@example.cz")
        e = self.err(acc.verify_code, "jan@example.cz", "000000")
        self.assertEqual(e.code, "invalid_code")
        self.assertEqual(acc.error_text(e), "The code is not valid or has expired.")
        data = acc.login_code("jan@example.cz", "123456")
        self.assertEqual(data["user"]["email"], "jan@example.cz")
        saved = acc.load()
        self.assertEqual(saved["sessionToken"], data["sessionToken"])
        self.assertEqual(os.stat(acc.ACCOUNT_FILE).st_mode & 0o777, 0o600)
        self.assertEqual(acc.me()["user"]["email"], "jan@example.cz")

    def test_code_reuse_rejected(self):
        acc.request_code("jan@example.cz")
        acc.verify_code("jan@example.cz", "123456")
        self.assertEqual(self.err(acc.verify_code, "jan@example.cz", "123456").code, "invalid_code")

    def test_too_many_wrong_codes(self):
        acc.request_code("jan@example.cz")
        for _i in range(5):
            self.err(acc.verify_code, "jan@example.cz", "999999")
        e = self.err(acc.verify_code, "jan@example.cz", "123456")
        self.assertEqual((e.code, e.status), ("rate", 429))

    def test_resend_slow_down(self):
        acc.request_code("jan@example.cz")
        e = self.err(acc.request_code, "jan@example.cz")
        self.assertEqual((e.code, e.retry_after), ("slow_down", 60))


class Terms(Base):
    def test_html_to_text(self):
        text = acc.html_to_text(TERMS_HTML)
        self.assertTrue(text.startswith("Verze 2026-09-24\n\nPodmínky používání LuxAI\n\n"), text[:80])
        self.assertIn("Tyto podmínky upravují používání účtu & služeb.", text)   # mezery + entity
        self.assertIn("1. Provozovatel\n\nKontakt: info@lux-ai.cz.", text)
        self.assertIn("• obcházet limity;\n• útoky <bez> oprávnění.", text)
        self.assertIn("1. první\n2. druhý", text)
        for bad in ("nezobrazovat", "color:red", "Zpět na web", "Paticka", "<", "\n\n\n"):
            if bad == "<":
                self.assertEqual(text.count("<"), 1)   # jen z entity &lt;
                continue
            self.assertNotIn(bad, text)

    def test_html_without_main_and_broken_markup(self):
        text = acc.html_to_text("<p>One<br>Two</p></div><ul><li>a<li>b</ul><p>End")
        self.assertEqual(text, "One\nTwo\n\n• a\n• b\n\nEnd")
        self.assertEqual(acc.html_to_text(""), "")

    def test_nested_list_indent(self):
        text = acc.html_to_text("<ul><li>a<ul><li>b</li></ul></li></ul>")
        self.assertEqual(text, "• a\n  • b")

    def test_fetch_terms(self):
        text = acc.fetch_terms()
        self.assertIn("Podmínky používání LuxAI", text)
        self.assertEqual(SRV.log[-1][:2], ("GET", "/terms"))

    def test_fetch_terms_offline(self):
        self.assertEqual(self.err(acc.fetch_terms, "http://127.0.0.1:9").code, "network")


class Manage(Base):
    """Sprava uctu jako na lux-ai.cz/settings: jmeno, vzhled, styl AI, heslo, export, zruseni."""

    def setUp(self):
        super().setUp()
        SRV.native_settings = SRV.native_history = True
        SRV.chats.clear()
        SRV.accounts["jan@example.cz"] = {"password": GOOD_PW, "displayName": "Jan"}
        SRV.accounts["eva@example.cz"] = {"password": GOOD_PW, "displayName": "Eva", "username": "eva"}
        acc.login_password("jan@example.cz", GOOD_PW)
        SRV.log.clear()

    def test_me_has_username_settings_usage(self):
        u = acc.me()["user"]
        self.assertEqual((u["username"], u["settings"]["theme"]), ("jan", "dark"))
        self.assertIn("fastLimit", u["usage"])

    def test_set_username(self):
        u = acc.set_username("  Jan.Novak ")
        self.assertEqual(SRV.log[-1][:2], ("PATCH", "/api/account/settings"))
        self.assertEqual(SRV.log[-1][2], {"username": "jan.novak"})
        self.assertEqual(SRV.log[-1][3], "luxos")
        self.assertEqual(u["username"], "jan.novak")
        saved = acc.load()["user"]
        self.assertEqual(saved["username"], "jan.novak")
        self.assertIn("usage", saved, "PATCH bez spotreby nesmi smazat ulozenou spotrebu")

    def test_username_errors(self):
        for bad in ("ab", "-abc", "Ab c", "x" * 33):
            with self.subTest(bad=bad):
                self.assertEqual(self.err(acc.set_username, bad).code, "invalid_username")
        self.assertEqual(SRV.log, [], "lokalni kontrola nic neposila")
        e = self.err(acc.set_username, "eva")
        self.assertEqual((e.code, e.status), ("username_taken", 409))
        self.assertIn("already used", acc.account_error_text(e))
        self.assertEqual(self.err(acc.set_username, "busy-one").code, "rate")

    def test_theme_and_style(self):
        self.assertEqual(acc.set_theme("light")["settings"]["theme"], "light")
        self.assertEqual(acc.set_theme("weird")["settings"]["theme"], "dark")
        for style in acc.RESPONSE_STYLES:
            self.assertEqual(acc.set_response_style(style)["settings"]["aiResponseStyle"], style)
        self.assertEqual(acc.set_response_style("nonsense")["settings"]["aiResponseStyle"], "balanced")
        self.assertEqual(acc.load()["user"]["settings"]["aiResponseStyle"], "balanced")

    def test_web_only_fallback(self):
        SRV.native_settings = False
        e = self.err(acc.set_theme, "light")
        self.assertEqual((e.code, e.status), ("origin", 403))
        self.assertTrue(acc.web_only(e))
        self.assertIn("on the web", acc.account_error_text(e))
        self.assertFalse(acc.web_only(acc.AccountError("username_taken", 409)))

    def test_expired_session(self):
        SRV.sessions.clear()
        e = self.err(acc.set_theme, "light")
        self.assertEqual((e.code, e.status), ("signed_out", 401))
        acc.forget()
        self.assertEqual(self.err(acc.change_password, GOOD_PW, "another long pass").code, "signed_out")

    def test_change_password_signs_out_other_sessions(self):
        other = acc.password_session("jan@example.cz", GOOD_PW)["sessionToken"]
        e = self.err(acc.change_password, "wrong password!", "brand new password")
        self.assertEqual(e.code, "invalid_current_password")
        SRV.log.clear()
        self.assertEqual(self.err(acc.change_password, GOOD_PW, "short").code, "weak_password")
        self.assertEqual(self.err(acc.change_password, GOOD_PW, GOOD_PW).code, "same_password")
        self.assertEqual(SRV.log, [], "lokalni chyby nic neposilaji")
        acc.change_password(GOOD_PW, "brand new password")
        self.assertEqual(SRV.log[-1][2], {"currentPassword": GOOD_PW, "newPassword": "brand new password"})
        self.assertNotIn(other, SRV.sessions, "ostatni relace odhlasene")
        self.assertEqual(acc.me()["user"]["email"], "jan@example.cz", "tento pocitac zustava prihlaseny")
        self.assertTrue(acc.login_password("jan@example.cz", "brand new password"))

    def test_change_password_after_code_login_without_current(self):
        self.assertEqual(self.err(acc.change_password, "", "brand new password").code, "invalid_current_password")
        acc.request_code("jan@example.cz")
        acc.login_code("jan@example.cz", "123456")
        acc.change_password("", "brand new password")
        self.assertEqual(SRV.accounts["jan@example.cz"]["password"], "brand new password")

    def test_usage_reset(self):
        import time as t
        dec = t.mktime((2026, 12, 15, 12, 0, 0, 0, 0, -1))
        self.assertEqual(t.strftime("%Y-%m-%d", acc.usage_reset({}, dec)), "2027-01-01")
        oct_ = t.mktime((2026, 10, 26, 9, 0, 0, 0, 0, -1))
        r = acc.usage_reset(None, oct_)
        self.assertEqual(t.strftime("%Y-%m-%d", r), "2026-11-01")
        self.assertEqual(acc.days_until(r, oct_), 6)
        self.assertEqual(t.strftime("%Y-%m-%d", acc.usage_reset({"resetAt": "2026-11-03T00:00:00Z"})), "2026-11-03")

    def test_export(self):
        SRV.chats["jan@example.cz"] = [
            {"id": "c 1", "title": "Ahoj", "updatedAt": "2026-10-01", "messages": [{"role": "user", "content": "Ahoj"}]},
            {"id": "c2", "title": "Druhy", "updatedAt": "2026-10-02", "messages": []}]
        path = os.path.join(TMP, "export.json")
        seen = []
        r = acc.export_data(path, progress=lambda i, n: seen.append((i, n)), pause=0)
        self.assertEqual(r, {"conversations": 2, "history": True, "path": path})
        self.assertEqual(seen, [(0, 2), (1, 2)])
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        raw = open(path, encoding="utf-8").read()
        self.assertNotIn(acc.load()["sessionToken"], raw, "token nikdy v exportu")
        import json as j
        data = j.loads(raw)
        self.assertEqual(data["user"]["email"], "jan@example.cz")
        self.assertEqual(data["chatHistory"]["conversations"][0]["conversation"]["title"], "Ahoj")
        self.assertIn(("GET", "/api/chat/history/c%201"), [x[:2] for x in SRV.log])

    def test_export_without_history_access(self):
        SRV.native_history = False
        path = os.path.join(TMP, "export2.json")
        r = acc.export_data(path, pause=0)
        self.assertEqual(r["history"], False)
        import json as j
        self.assertEqual(j.load(open(path))["chatHistoryError"], "origin")

    def test_deletion_mailto(self):
        url = acc.deletion_mailto(acc.load()["user"])
        self.assertTrue(url.startswith("mailto:info@lux-ai.cz?subject="))
        self.assertIn("jan%40example.cz", url)
        self.assertNotIn(acc.load()["sessionToken"], url)
        self.assertEqual(SRV.log, [], "nic se neodesila")

    def test_logout_invalidates_session(self):
        token = acc.load()["sessionToken"]
        acc.logout()
        self.assertNotIn(token, SRV.sessions)
        self.assertIsNone(acc.load())


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        SRV.stop()
