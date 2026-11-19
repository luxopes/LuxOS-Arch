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
        self.assertEqual((u["usage"]["credits"], u["usage"]["creditsLimit"]), (0, 20000))
        self.assertIn("fastLimit", u["usage"], "stara pole pro starsi aplikace zustavaji")

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


class Credits(Base):
    """Od 2026-11-19 kredity (20 000 mesicne pro vsechny modely) misto tokenu po modelech;
    starsi server (jen fastTokens/...) -> puvodni zobrazeni, limit -> 429 monthly_limit."""
    import time as t

    def ymd(self, when):
        return None if when is None else self.t.strftime("%Y-%m-%d", when)

    def test_new_shape_credits(self):
        u = MockLuxAI.credits_usage(12345, month="2026-11")
        r = acc.parse_usage(u)
        self.assertEqual(r["mode"], "credits", "creditsLimit ma prednost pred starymi tokenovymi poli")
        self.assertEqual((r["used"], r["limit"], r["percent"], r["exhausted"]), (12345, 20000, 62, False))
        self.assertEqual(self.ymd(r["reset"]), "2026-12-01")
        # prosinec -> leden dalsiho roku; float kredity (1 kredit = 0,0001 USD) se zaokrouhli jen pro zobrazeni
        r = acc.parse_usage({"credits": 19999.6, "creditsLimit": 20000, "month": "2026-12"})
        self.assertEqual((r["percent"], r["exhausted"], self.ymd(r["reset"])), (100, False, "2027-01-01"))

    def test_server_numbers_not_hardcoded(self):
        r = acc.parse_usage({"credits": 50, "creditsLimit": 250000, "unlimited": False})
        self.assertEqual((r["used"], r["limit"], r["percent"]), (50, 250000, 0))
        self.assertIsNone(r["reset"], "bez usage.month se datum nehada")
        r = acc.parse_usage({"credits": 25000, "creditsLimit": 20000})
        self.assertEqual((r["percent"], r["exhausted"]), (100, True))
        r = acc.parse_usage({"credits": None, "creditsLimit": "20000"})   # odolnost proti typum
        self.assertEqual((r["mode"], r["used"], r["limit"]), ("credits", 0, 20000))

    def test_unlimited(self):
        self.assertEqual(acc.parse_usage({"credits": 99999, "creditsLimit": 20000, "unlimited": True}),
                         {"mode": "unlimited"})
        self.assertEqual(acc.parse_usage({"unlimited": True, "fastTokens": 1}), {"mode": "unlimited"})
        self.assertEqual(acc.parse_usage({"unlimited": "no", "credits": 1, "creditsLimit": 2})["mode"], "credits")

    def test_old_server_tokens_fallback(self):
        r = acc.parse_usage({"fastTokens": 412500, "fastLimit": 1000000, "liteTokens": 2350000,
                             "liteLimit": 10000000})
        self.assertEqual(r, {"mode": "tokens", "models": [("Flash", 412500, 1000000), ("Lite", 2350000, 10000000)]})
        self.assertEqual(acc.parse_usage({"liteTokens": 5, "liteLimit": 10}),
                         {"mode": "tokens", "models": [("Lite", 5, 10)]})

    def test_empty_or_broken(self):
        for u in (None, {}, [], "x", {"week": 3}):
            self.assertEqual(acc.parse_usage(u), {"mode": "none"}, u)

    def test_month_reset_shapes(self):
        f = lambda u: self.ymd(acc.month_reset(u))   # noqa: E731
        self.assertEqual(f({"month": "2026-11"}), "2026-12-01")
        self.assertEqual(f({"month": "2026-11-01T00:00:00Z"}), "2026-12-01")
        self.assertEqual(f({"month": {"key": "2026-11", "credits": 10}}), "2026-12-01")
        self.assertEqual(f({"month": {"start": "2026-11-01", "credits": 10}}), "2026-12-01")
        self.assertEqual(f({"month": {"resetAt": "2026-12-03T00:00:00Z"}}), "2026-12-03")
        self.assertEqual(f({"resetAt": "2026-12-05"}), "2026-12-05")
        for u in ({"month": 1234}, {"month": "listopad"}, {"month": "2026-13"}, {"month": {"credits": 5}},
                  {"month": None}, {}, None, {"week": "2026-W47"}):
            self.assertIsNone(acc.month_reset(u), u)
        # zobrazeni v okne (usage_reset) ma i nadale nahradni 1. den dalsiho mesice
        now = self.t.mktime((2026, 11, 19, 12, 0, 0, 0, 0, -1))
        self.assertEqual(self.ymd(acc.usage_reset({"month": 7}, now)), "2026-12-01")

    def test_limit_text(self):
        fmt = lambda w: self.t.strftime("%d.%m.%Y", w)   # noqa: E731
        err = acc.AccountError("monthly_limit", 429, 0, {"error": "monthly_limit", "limit": 20000, "unit": "credits"})
        self.assertEqual(acc.limit_text(err, {"month": "2026-11"}, date_format=fmt),
                         "You've used this month's LuxAI credits. They renew on 01.12.2026.")
        self.assertEqual(acc.limit_text(err, {"credits": 1, "creditsLimit": 1}, date_format=fmt),
                         "You've used this month's LuxAI credits.")
        tr = {"You've used this month's LuxAI credits. They renew on %s.": "Vyčerpáno, obnova %s."}
        self.assertEqual(acc.limit_text(err, {"month": "2026-12"}, tr=lambda k: tr.get(k, k), date_format=fmt),
                         "Vyčerpáno, obnova 01.01.2027.")
        # datum primo v odpovedi chyby ma prednost
        err2 = acc.AccountError("monthly_limit", 429, 0, {"error": "monthly_limit", "month": "2027-01"})
        self.assertEqual(acc.limit_text(err2, {"month": "2026-11"}, date_format=fmt),
                         "You've used this month's LuxAI credits. They renew on 01.02.2027.")
        # error_text / account_error_text pouziji stejnou hlasku (bez ulozeneho uctu = bez data)
        self.assertEqual(acc.error_text(err), "You've used this month's LuxAI credits.")
        self.assertEqual(acc.account_error_text(err), "You've used this month's LuxAI credits.")

    def test_monthly_limit_from_server(self):
        SRV.accounts["jan@example.cz"] = {"password": GOOD_PW, "displayName": "Jan",
                                          "usage": MockLuxAI.credits_usage(20000, month="2026-11")}
        acc.login_password("jan@example.cz", GOOD_PW)
        SRV.log.clear()
        e = self.err(acc._authed, "POST", "/api/chat", {"message": "ahoj"})
        self.assertEqual((e.code, e.status, e.data.get("unit"), e.data.get("limit")),
                         ("monthly_limit", 429, "credits", 20000))
        self.assertEqual(len([x for x in SRV.log if x[1] == "/api/chat"]), 1, "429 limit se neopakuje")
        # datum z usage.month ulozeneho uctu (z prihlaseni / GET /api/me)
        self.assertEqual(acc.error_text(e, lambda k: k),
                         "You've used this month's LuxAI credits. They renew on %s."
                         % __import__("luxos_i18n").format_date(acc.month_reset({"month": "2026-11"}), "full")
                         if _has_i18n() else
                         "You've used this month's LuxAI credits. They renew on 2026-12-01.")
        # GET s cekanim pri 429 (_get_retry) monthly_limit neopakuje
        SRV.log.clear()
        orig = acc._authed
        calls = []

        def fake(method, path, body=None, account=None):
            calls.append(path)
            raise acc.AccountError("monthly_limit", 429, 0, {})
        acc._authed = fake
        try:
            self.assertEqual(self.err(acc._get_retry, "/api/me", None).code, "monthly_limit")
        finally:
            acc._authed = orig
        self.assertEqual(calls, ["/api/me"])
        # pod limitem projde
        SRV.accounts["jan@example.cz"]["usage"] = MockLuxAI.credits_usage(10)
        self.assertEqual(acc._authed("POST", "/api/chat", {"message": "ahoj"})["ok"], True)

    def test_me_stores_new_usage(self):
        SRV.accounts["jan@example.cz"] = {"password": GOOD_PW, "displayName": "Jan",
                                          "usage": MockLuxAI.credits_usage(321, month="2026-11", legacy=False)}
        acc.login_password("jan@example.cz", GOOD_PW)
        u = acc.me()["user"]["usage"]
        self.assertEqual(acc.load()["user"]["usage"], u)
        self.assertEqual(acc.parse_usage(u)["mode"], "credits")
        self.assertNotIn("fastLimit", u)


def _has_i18n():
    try:
        import luxos_i18n  # noqa: F401
        return True
    except ImportError:
        return False


class Hardening(Base):
    """Cookie uctu nejde na cil presmerovani, http jen na tento pocitac, neplatna odpoved = AccountError,
    prihlaseni prohlizecem: cizi callback nic nerusi, zruseny pokus hned skonci."""

    def _server(self, handler_cls):
        import threading
        from http.server import HTTPServer
        srv = HTTPServer(("127.0.0.1", 0), handler_cls)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    def test_origin_rules(self):
        self.assertEqual(acc._origin("https://staging.lux-ai.cz/"), "https://staging.lux-ai.cz")
        self.assertEqual(acc._origin("http://127.0.0.1:8080"), "http://127.0.0.1:8080")
        self.assertEqual(acc._origin("http://localhost:1"), "http://localhost:1")
        for bad in ("http://lux-ai.cz", "http://192.168.1.5:80", "ftp://x", "", "lux-ai.cz", "https://"):
            self.assertEqual(acc._origin(bad), acc.DEFAULT_ORIGIN, bad)

    def test_cookie_not_forwarded_on_redirect(self):
        from http.server import BaseHTTPRequestHandler
        seen = {}

        class Target(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_GET(self):  # noqa: N802
                seen["cookie"] = self.headers.get("Cookie")
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        target = self._server(Target)

        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_GET(self):  # noqa: N802
                seen["first"] = self.headers.get("Cookie")
                self.send_response(302)
                self.send_header("Location", target + "/elsewhere")
                self.send_header("Content-Length", "0")
                self.end_headers()

        origin = self._server(Redirect)
        self.assertEqual(acc.request("GET", "/api/me", token="SECRET", origin=origin), {"ok": True})
        self.assertIn("SECRET", seen["first"])
        self.assertIsNone(seen["cookie"])

    def test_non_json_and_non_object_answers(self):
        from http.server import BaseHTTPRequestHandler
        bodies = iter([b"<html>captive portal</html>", b"[1, 2]", b'"text"'])

        class Junk(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_GET(self):  # noqa: N802
                body = next(bodies)
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        origin = self._server(Junk)
        for _ in range(3):
            e = self.err(acc.request, "GET", "/api/me", None, None, origin)
            self.assertEqual(e.code, "http")

    def _callback(self, login, query):
        import urllib.error
        import urllib.request
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{login.port}/callback?{query}", timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_web_login_foreign_callback_ignored(self):
        login = acc.WebLogin()
        self.addCleanup(login.close)
        self.assertEqual(self._callback(login, "state=wrong&code=abc"), 400)
        self.assertEqual(self._callback(login, "code=abc"), 400)
        self.assertEqual(self._callback(login, "error=access_denied"), 400)
        self.assertFalse(login.done.is_set(), "cizi callback nesmi ukoncit prihlaseni")
        self.assertEqual(self._callback(login, f"state={login.state}&error=access_denied"), 200)
        e = self.err(login.wait, 5)
        self.assertEqual(e.code, "access_denied")

    def test_web_login_close_ends_wait_at_once(self):
        import threading
        import time
        login = acc.WebLogin()
        res = {}

        def run():
            try:
                login.wait(600)
            except acc.AccountError as e:
                res["code"] = e.code
        t = threading.Thread(target=run, daemon=True)
        t.start()
        time.sleep(0.1)
        t0 = time.monotonic()
        login.close()
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertLess(time.monotonic() - t0, 2)
        self.assertEqual(res.get("code"), "cancelled")


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        SRV.stop()
