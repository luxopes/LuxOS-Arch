"""Odesilani posty ve sluzbe Posty proti testovacimu serveru SMTP + IMAP (nikdy skutecne doruceni, nikdy skutecny
Google/Microsoft/LuxAI): STARTTLS 587 i implicitni TLS 465 s overenim certifikatu, AUTH PLAIN heslem, OAUTHBEARER tokenem
Googlu (obnoveni pres falesny koncovy bod), XOAUTH2 tokenem Microsoftu (STARTTLS), OAUTHBEARER tokenem LuxAI, kopie do
Odeslanych (ne u Gmailu a Microsoftu, ktere si ji ulozi samy), priznak \\Answered, Bcc jen v obalce, odmitnuty prijemce, limit SIZE, spatne heslo, Odchozi bez site
s opakovanim, trvala chyba na pozadi s upozornenim, koncepty na serveru (APPEND + nahrazeni + smazani po odeslani).
"""
import base64
import email
import json
import os
import subprocess
import sys
import time
import unittest
from email import policy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_luxai as fl  # noqa: E402
import fake_oauth as fo  # noqa: E402
import mailtest as mt  # noqa: E402

GMAIL = "tester@gmail.com"


def parse(data):
    return email.message_from_bytes(data, policy=policy.default)


class SendBase(unittest.TestCase):
    personality = ""

    def setUp(self):
        self.s = mt.Session()
        self.server = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, smtp=True, personality=self.personality,
                                    oauth="OAUTHBEARER,XOAUTH2")
        self.c = self.s.start_service()
        self.n = 0

    def tearDown(self):
        try:
            self.c.call("quit")
        except OSError:
            pass
        self.server.stop()
        self.s.close()

    def add(self, security="starttls", provider=""):
        req = mt.account_request(self.server)
        port = self.server.ports["smtp_starttls"] if security == "starttls" else self.server.ports["smtp_tls"]
        req["smtp"] = {"host": "localhost", "port": port, "security": security, "user": mt.USER}
        if provider:
            req["provider"] = provider
        r = self.c.call("add_account", **req)
        self.assertTrue(r["ok"], (r, self.s.service_log()))
        return r["account"]

    def outbox(self):
        return os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail", "outbox")

    def queue(self, account, sender=mt.USER, to=(("Příjemce Testovací", "rcpt@example.org"),), cc=(), bcc=(), subject="Zkouška odeslání",
              text="Dobrý den,\nposílám zprávu se žluťoučkým koněm.\n", attachments=(), reply=None, draft_id=""):
        self.n += 1
        job = "job%d-%d" % (self.n, int(time.time() * 1000))
        os.makedirs(self.outbox(), mode=0o700, exist_ok=True)
        m = {"from": ["Tester", sender], "to": [list(x) for x in to], "cc": [list(x) for x in cc], "bcc": [list(x) for x in bcc],
             "subject": subject, "text": text, "attachments": list(attachments)}
        if reply:
            m["in_reply_to"] = "<orig@example.org>"
            m["references"] = "<orig@example.org>"
        src = os.path.join(self.s.root, job + ".json")
        with open(src, "w") as f:
            json.dump(m, f)
        r = mt.run_bin(["--test-compose", src, os.path.join(self.outbox(), job + ".eml")], env=self.s.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        rcpts = [x[1] for x in list(to) + list(cc) + list(bcc)]
        desc = {"account": account, "rcpts": rcpts, "recipients": [list(x) for x in list(to) + list(cc) + list(bcc)],
                "subject": subject, "state": "new", "created": int(time.time())}
        if reply:
            desc["reply"] = reply
        if draft_id:
            desc["draft_id"] = draft_id
        with open(os.path.join(self.outbox(), job + ".json"), "w") as f:
            json.dump(desc, f)
        return job

    def sent(self):
        out = []
        for m in self.server.control("smtp dump")["messages"]:
            m = dict(m)
            m["raw"] = base64.b64decode(m["data"])
            m["msg"] = parse(m["raw"])
            out.append(m)
        return out

    def box(self, name):
        return self.server.control("dump")["boxes"].get(name, [])

    def raw(self, box, uid):
        return base64.b64decode(self.server.control("raw %s %d" % (box, uid))["raw"])

    def jobs(self):
        if not os.path.isdir(self.outbox()):
            return []
        return sorted(n for n in os.listdir(self.outbox()) if n.endswith(".json"))


class SendTest(SendBase):
    def test_send_starttls_password_reply_and_sent_copy(self):
        acc = self.add("starttls")
        inbox = self.box("INBOX")
        orig = inbox[0]["uid"]
        job = self.queue(acc, cc=(("Kopie", "cc@example.org"),), bcc=(("", "skryty@example.org"),),
                         reply={"account": acc, "mailbox": "INBOX", "uid": orig})
        r = self.c.call("send", job=job)
        self.assertTrue(r.get("ok") and r.get("sent"), (r, self.s.service_log()))
        msgs = self.sent()
        self.assertEqual(len(msgs), 1)
        m = msgs[0]
        self.assertEqual(m["from"], mt.USER)
        self.assertEqual(sorted(m["rcpts"]), ["cc@example.org", "rcpt@example.org", "skryty@example.org"])
        self.assertEqual((m["mech"], m["implicit_tls"]), ("PLAIN", False))
        self.assertIn("SIZE=", m["params"])
        # Bcc jen v obalce, nikdy v hlavicce
        self.assertNotIn(b"skryty", m["raw"])
        self.assertIsNone(m["msg"]["bcc"])
        self.assertEqual(str(m["msg"]["subject"]), "Zkouška odeslání")
        self.assertEqual(m["msg"]["to"].addresses[0].display_name, "Příjemce Testovací")
        self.assertEqual(m["msg"]["in-reply-to"], "<orig@example.org>")
        self.assertIn("žluťoučkým", m["msg"].get_body(("plain",)).get_content())
        # kopie v Odeslanych (obecny server), priznak \Seen
        sent = self.box("Sent")
        self.assertEqual(len(sent), 1, self.server.control("log")["log"][-20:])
        self.assertIn("\\Seen", sent[0]["flags"])
        self.assertEqual(self.raw("Sent", sent[0]["uid"]), m["raw"])
        # odpovezena puvodni zprava
        flags = [x for x in self.box("INBOX") if x["uid"] == orig][0]["flags"]
        self.assertIn("\\Answered", flags)
        # zakazka hotova, prijemci zapamatovani pro doplnovani
        self.assertEqual(self.jobs(), [])
        with open(os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail", "recipients.json")) as f:
            known = json.load(f)
        self.assertEqual(known["rcpt@example.org"]["name"], "Příjemce Testovací")
        self.assertEqual(known["skryty@example.org"]["count"], 1)
        # heslo nikde v souborech ani v logu
        self.assertNotIn(mt.PASSWORD, self.s.service_log())
        self.assertFalse(any(mt.PASSWORD in l for l in self.server.control("log")["log"]))

    def test_send_implicit_tls_with_attachment(self):
        acc = self.add("ssl")
        att = os.path.join(self.s.root, "data.bin")
        payload = os.urandom(200000)
        with open(att, "wb") as f:
            f.write(payload)
        job = self.queue(acc, attachments=[{"name": "výkaz – září 2026.bin", "path": att}])
        r = self.c.call("send", job=job)
        self.assertTrue(r.get("sent"), (r, self.s.service_log()))
        m = self.sent()[0]
        self.assertTrue(m["implicit_tls"])
        parts = [p for p in m["msg"].iter_attachments()]
        self.assertEqual(parts[0].get_filename(), "výkaz – září 2026.bin")
        self.assertEqual(parts[0].get_content(), payload)

    def test_dot_stuffing(self):
        acc = self.add()
        text = "první\n.\n..dvě tečky\n.konec\n"
        r = self.c.call("send", job=self.queue(acc, text=text))
        self.assertTrue(r.get("sent"), r)
        body = self.sent()[0]["msg"].get_body(("plain",)).get_content().replace("\r\n", "\n")
        self.assertEqual(body, text)

    def test_recipient_rejected(self):
        acc = self.add()
        self.server.control("smtp reject nobody@example.org")
        job = self.queue(acc, to=(("", "rcpt@example.org"), ("", "nobody@example.org")))
        r = self.c.call("send", job=job)
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["kind"], "rcpt")
        self.assertTrue(r["error"].startswith("nobody@example.org|"), r)
        self.assertIn("User unknown", r["error"])
        # nikomu neodeslano, zprava zustava v okne (zakazka zrusena), zadna kopie v Odeslanych
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.box("Sent"), [])
        self.assertEqual(self.jobs(), [])

    def test_message_too_big(self):
        acc = self.add()
        self.server.control("smtp size 5000")
        att = os.path.join(self.s.root, "big.bin")
        with open(att, "wb") as f:
            f.write(os.urandom(20000))
        r = self.c.call("send", job=self.queue(acc, attachments=[{"name": "big.bin", "path": att}]))
        self.assertEqual((r["ok"], r["kind"], r["error"]), (False, "toolarge", "5000"))
        # SIZE zkontrolovano pred MAIL FROM: data se vubec neposlala
        self.assertFalse(any(l.startswith("SMTP MAIL FROM") for l in self.server.control("log")["log"]))

    def test_wrong_password(self):
        acc = self.add()
        self.server.control("password jine-heslo")
        r = self.c.call("send", job=self.queue(acc))
        self.assertEqual((r["ok"], r["kind"]), (False, "auth"), r)
        self.assertEqual(self.jobs(), [])

    def test_offline_outbox_retry(self):
        acc = self.add()
        self.server.control("smtp down on")
        job = self.queue(acc)
        r = self.c.call("send", job=job)
        self.assertTrue(r["ok"] and r.get("queued"), r)
        self.assertIn(r["kind"], ("closed", "tls", "connect"))
        with open(os.path.join(self.outbox(), job + ".json")) as f:
            desc = json.load(f)
        self.assertEqual(desc["state"], "queued")
        self.assertGreaterEqual(desc["next"] - time.time(), 20)
        self.assertEqual(self.sent(), [])
        # sit zpet: znovupripojeni posle cekajici zpravy hned
        self.server.control("smtp down off")
        self.c.call("reconnect")
        self.assertTrue(mt.wait_for(lambda: len(self.sent()) == 1, 20), self.s.service_log())
        self.assertTrue(mt.wait_for(lambda: self.jobs() == [], 10))
        self.assertTrue(self.c.wait_event(lambda e: e.get("event") == "outbox", 5))

    def test_temporary_error_queued_then_final_failure_notifies(self):
        acc = self.add()
        self.server.control("smtp temp on")
        job = self.queue(acc, subject="Fronta")
        r = self.c.call("send", job=job)
        self.assertTrue(r.get("queued"), r)
        self.assertEqual(r["kind"], "smtp_temp")
        # na pozadi trvala chyba (prijemce odmitnut) -> neodeslana, upozorneni s akci Otevrit
        self.server.control("smtp temp off")
        self.server.control("smtp reject rcpt@example.org")
        before = len(self.s.notifications())
        self.c.call("reconnect")
        self.assertTrue(mt.wait_for(lambda: len(self.s.notifications()) > before, 15), self.s.service_log())
        note = self.s.notifications()[-1]
        self.assertTrue(note["summary"])
        self.assertIn("Fronta", note["body"])
        with open(os.path.join(self.outbox(), job + ".json")) as f:
            desc = json.load(f)
        self.assertEqual((desc["state"], desc["kind"]), ("failed", "rcpt"))
        # smazani neodeslane zpravy z Odchozi
        self.c.call("outbox_delete", job=job)
        self.assertEqual(self.jobs(), [])

    def test_drafts_saved_replaced_and_deleted_after_send(self):
        acc = self.add()
        d = os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail", "drafts")
        os.makedirs(d, mode=0o700, exist_ok=True)
        mid = "<draft-1@example.test>"
        for text in ("první verze", "druhá verze"):
            src = os.path.join(self.s.root, "d.json")
            with open(src, "w") as f:
                json.dump({"from": ["Tester", mt.USER], "to": [["", "rcpt@example.org"]], "bcc": [["", "skryty@example.org"]],
                           "subject": "Koncept", "text": text, "message_id": mid, "draft": True}, f)
            path = os.path.join(d, "d1.eml")
            self.assertEqual(mt.run_bin(["--test-compose", src, path], env=self.s.env).returncode, 0)
            r = self.c.call("save_draft", account=acc, path=path, message_id=mid)
            self.assertTrue(r["ok"], (r, self.s.service_log()))
        drafts = self.box("Drafts")
        self.assertEqual(len(drafts), 1, drafts)
        self.assertIn("\\Draft", drafts[0]["flags"])
        raw = self.raw("Drafts", drafts[0]["uid"])
        self.assertIn("druhá verze", parse(raw).get_body(("plain",)).get_content())
        # koncept si Bcc pamatuje
        self.assertIn("skryty@example.org", str(parse(raw)["bcc"]))
        # cesta mimo slozku konceptu odmitnuta
        r = self.c.call("save_draft", account=acc, path="/etc/passwd", message_id=mid)
        self.assertFalse(r["ok"])
        r = self.c.call("save_draft", account=acc, path=os.path.join(d, "..", "..", "..", "..", ".bashrc"), message_id=mid)
        self.assertFalse(r["ok"])
        r = self.c.call("send", job=self.queue(acc, draft_id=mid))
        self.assertTrue(r.get("sent"), r)
        self.assertEqual(self.box("Drafts"), [])
        # odeslana zprava ma vlastni Message-ID (ne koncept)
        self.assertNotEqual(self.sent()[0]["msg"]["message-id"], mid)


class GmailSendTest(SendBase):
    personality = "gmail"

    def test_gmail_no_sent_append(self):
        acc = self.add("ssl", provider="google")
        r = self.c.call("send", job=self.queue(acc))
        self.assertTrue(r.get("sent"), (r, self.s.service_log()))
        # Gmail ulozi odeslanou zpravu sam: prave jedna kopie, Posta nic nepridala
        self.assertEqual(len(self.box("[Gmail]/Sent Mail")), 1)
        self.assertFalse(any(l.startswith("APPEND") for l in self.server.control("log")["log"]))

    def test_gmail_detected_by_capability(self):
        # bez zname domeny/poskytovatele: pozna se podle X-GM-EXT-1 otevreneho spojeni IMAP
        acc = self.add("ssl")
        self.assertTrue(mt.wait_for(lambda: any(st["state"] == "online" for st in self.c.call("hello")["accounts"]), 10))
        r = self.c.call("send", job=self.queue(acc))
        self.assertTrue(r.get("sent"), r)
        self.assertEqual(len(self.box("[Gmail]/Sent Mail")), 1)


class OAuthSendTest(unittest.TestCase):
    """Ucet "Prihlasit se Googlem": SMTP tokenem (OAUTHBEARER); vyprsely token se obnovi (falesny koncovy bod)."""

    def setUp(self):
        self.s = mt.Session()
        self.gmail = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, personality="gmail", user=GMAIL,
                                   password="app-password-unused", oauth="OAUTHBEARER,XOAUTH2", smtp=True)
        self.google = fo.FakeOAuth(self.gmail, GMAIL, "test-google-client.apps.example", "GOCSPX-test-secret", expires_in=3600)
        self.s.env["LUXOS_MAIL_OAUTH_PROVIDERS"] = fo.providers_file(
            os.path.join(self.s.root, "oauth-providers.json"), google=self.google, google_imap=self.gmail.ports["tls"],
            google_smtp={"host": "localhost", "port": self.gmail.ports["smtp_tls"], "security": "ssl"})
        self.c = self.s.start_service()

    def tearDown(self):
        try:
            self.c.call("quit")
        except OSError:
            pass
        self.google.stop()
        self.gmail.stop()
        self.s.close()

    def test_send_with_google_token_and_refresh(self):
        r = self.c.call("oauth_start", provider="google", email=GMAIL, name="Tester")
        fo.follow(r["url"])
        ev = self.c.wait_event(lambda e: e.get("event") == "oauth_done", 30)
        self.assertTrue(ev and ev["ok"], (ev, self.s.service_log()))
        acc = ev["account"]
        base = SendBase.queue.__get__(self)
        self.n = 0
        self.outbox = lambda: os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail", "outbox")
        job = base(acc, sender=GMAIL)
        # pristupovy token z vymeny uz server nezna (napr. vyprsel): jedno obnoveni a znovu
        self.gmail.control("revoke")
        r = self.c.call("send", job=job)
        self.assertTrue(r.get("sent"), (r, self.s.service_log()))
        msgs = self.gmail.control("smtp dump")["messages"]
        # Gmail: OAUTHBEARER (RFC 7628) jako u IMAP; XOAUTH2 jen kdyz server OAUTHBEARER nenabizi
        self.assertEqual(msgs[0]["mech"], "OAUTHBEARER")
        self.assertEqual(msgs[0]["user"], GMAIL)
        self.assertEqual(len(self.google.refreshes()), 1)
        log = [l for l in self.gmail.control("log")["log"] if l.startswith("SMTP AUTH") and "user=" in l]
        self.assertTrue(all("user=" + GMAIL in l for l in log), log)
        self.assertEqual(len(self.gmail.control("dump")["boxes"]["[Gmail]/Sent Mail"]), 1)
        for sec in self.google.secrets_seen():
            self.assertNotIn(sec, self.s.service_log())


class MicrosoftSendTest(unittest.TestCase):
    """Ucet "Prihlasit se Microsoftem": smtp.office365.com:587 STARTTLS, jen XOAUTH2; kopie do Odeslanych ne."""

    OUTLOOK = "tester@outlook.com"

    def setUp(self):
        self.s = mt.Session()
        self.outlook = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, personality="microsoft", user=self.OUTLOOK,
                                     password="never", oauth="XOAUTH2", smtp=True)
        self.ms = fo.FakeOAuth(self.outlook, self.OUTLOOK, "00000000-1111-2222-3333-444444444444", "", redirect_host="localhost")
        self.s.env["LUXOS_MAIL_OAUTH_PROVIDERS"] = fo.providers_file(
            os.path.join(self.s.root, "oauth-providers.json"), microsoft=self.ms, microsoft_imap=self.outlook.ports["tls"],
            microsoft_smtp={"host": "localhost", "port": self.outlook.ports["smtp_starttls"], "security": "starttls"})
        self.c = self.s.start_service()

    def tearDown(self):
        try:
            self.c.call("quit")
        except OSError:
            pass
        self.ms.stop()
        self.outlook.stop()
        self.s.close()

    def test_send_with_microsoft_token(self):
        r = self.c.call("oauth_start", provider="microsoft", email=self.OUTLOOK)
        fo.follow(r["url"])
        ev = self.c.wait_event(lambda e: e.get("event") == "oauth_done", 30)
        self.assertTrue(ev and ev["ok"], (ev, self.s.service_log()))
        self.n = 0
        self.outbox = lambda: os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail", "outbox")
        job = SendBase.queue.__get__(self)(ev["account"], sender=self.OUTLOOK)
        r = self.c.call("send", job=job)
        self.assertTrue(r.get("sent"), (r, self.s.service_log()))
        m = self.outlook.control("smtp dump")["messages"][0]
        self.assertEqual((m["mech"], m["implicit_tls"], m["user"]), ("XOAUTH2", False, self.OUTLOOK))
        # Exchange ulozi odeslanou zpravu do Odeslanych sam: zadny APPEND
        self.assertFalse(any(l.startswith("APPEND") for l in self.outlook.control("log")["log"]))


class LuxAISendTest(unittest.TestCase):
    """Schranka LuxAI: SMTP (Postfix submission) tokenem OAUTHBEARER od serveru uctu LuxAI."""

    def setUp(self):
        self.s = mt.Session()
        self.server = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, oauth="OAUTHBEARER,XOAUTH2", smtp=True)
        self.lux = fl.FakeLuxAI(self.server, [fl.mailbox(mt.USER, self.server.ports["tls"], smtp_port=self.server.ports["smtp_tls"])])
        fl.write_account(self.s.env, self.lux.origin)
        self.c = self.s.start_service()

    def tearDown(self):
        try:
            self.c.call("quit")
        except OSError:
            pass
        self.lux.stop()
        self.server.stop()
        self.s.close()

    def test_send_with_luxai_token(self):
        r = self.c.call("add_luxai_account", address=mt.USER)
        self.assertTrue(r["ok"], r)
        acc = r["account"]
        self.n = 0
        self.outbox = lambda: os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail", "outbox")
        before = len(self.lux.token_requests())
        job = SendBase.queue.__get__(self)(acc)
        r = self.c.call("send", job=job)
        self.assertTrue(r.get("sent"), (r, self.s.service_log()))
        m = self.server.control("smtp dump")["messages"][0]
        self.assertEqual((m["mech"], m["user"]), ("OAUTHBEARER", mt.USER))
        # novy token pro odeslani
        self.assertEqual(len(self.lux.token_requests()), before + 1)
        auth = [l for l in self.server.control("log")["log"] if l.startswith("SMTP AUTH OAUTHBEARER user=")][0]
        self.assertIn("port=%d" % self.server.ports["smtp_tls"], auth)
        self.assertEqual(len(self.server.control("dump")["boxes"]["Sent"]), 1)


if __name__ == "__main__":
    unittest.main()
