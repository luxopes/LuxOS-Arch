"""Prvni spusteni Posty s uctem LuxAI ve virtualni obrazovce (nikdy na skutecne):

    env -u DISPLAY xvfb-run -a -s "-screen 0 1440x900x24" python3 -m unittest test_gui_luxai

Falesny ~/.config/luxai/account.json v docasnem HOME, falesny server uctu LuxAI a falesny IMAP s tokeny.
1) "Pokracovat jako <jmeno>" -> seznam schranek LuxAI -> Pridat (Enter) -> schranka bez hesla, zpravy.
2) Ucet bez schranky na serveru LuxAI -> bezne pridani s predvyplnenym registracnim e-mailem (napise se
   jen heslo). LUXOS_MAIL_SCREENSHOTS=adresar ulozi snimky.
"""
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_luxai as fl  # noqa: E402
import mailtest as mt  # noqa: E402
import test_gui  # noqa: E402
from test_gui import have_display, xdo  # noqa: E402


@unittest.skipUnless(have_display(), "needs xvfb-run (never a real display)")
class LuxAIGuiTest(test_gui.GuiTest):
    test_add_account_read_notify = None

    def setUp(self):
        super().setUp()
        # druhy IMAP server s prihlasenim tokenem (puvodni z GuiTest slouzi automatickemu nalezeni)
        self.oserver = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, oauth="OAUTHBEARER,XOAUTH2")
        self.lux = fl.FakeLuxAI(self.oserver, [fl.mailbox("info@lux-ai.test", self.oserver.ports["tls"])])
        self.oserver.control("password unused")

    def tearDown(self):
        super().tearDown()
        self.lux.stop()
        self.oserver.stop()

    def accounts(self):
        path = os.path.join(self.s.env["XDG_CONFIG_HOME"], "luxos-mail", "accounts.json")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return json.load(f)

    def test_continue_as_luxai_account(self):
        env = self.s.env
        # IMAP s tokeny prijima jako uzivatele schranky info@lux-ai.test
        fl.write_account(env, self.lux.origin, name="Antonín Test", email="owner@personal.example")
        self.start_gui()
        self.shot("luxai-01-welcome.png")
        win = self.window()
        self.assertTrue(win)
        xdo(env, "windowactivate", "--sync", win)
        xdo(env, "key", "--clearmodifiers", "Return")      # fokus: Pokracovat jako Antonín Test
        self.assertTrue(mt.wait_for(lambda: any(r["path"] == "/api/mail/mailboxes" for r in self.lux.requests), 10),
                        "mailboxes not requested: " + self.gui_log())
        time.sleep(1.5)
        self.shot("luxai-02-mailboxes.png")
        xdo(env, "key", "Return")                          # fokus: Pridat u info@lux-ai.test
        self.assertTrue(mt.wait_for(lambda: len(self.accounts()) == 1, 15), "not added: " + self.s.service_log() + self.gui_log())
        a = self.accounts()[0]
        self.assertEqual((a["email"], a["auth"]), ("info@lux-ai.test", "luxai"))
        self.assertTrue(mt.wait_for(lambda: len(self.index_rows()) >= 9, 15), self.s.service_log())
        time.sleep(1.5)
        self.shot("luxai-03-inbox.png")
        self.assertEqual(self.s.secret_lookup(a["id"]), "")
        # zadny session token ani token schranky v souborech Posty
        for base in (os.path.join(env["XDG_CONFIG_HOME"], "luxos-mail"), os.path.join(env["XDG_DATA_HOME"], "luxos-mail")):
            for root, dirs, files in os.walk(base):
                for name in files:
                    with open(os.path.join(root, name), "rb") as f:
                        data = f.read()
                    self.assertNotIn(fl.SESSION.encode(), data)
                    for t in self.lux.tokens:
                        self.assertNotIn(t.encode(), data)

    def test_no_luxai_mailbox_prefills_registration_email(self):
        env = self.s.env
        self.lux.mailboxes = []
        # registracni e-mail = adresa schranky u bezneho poskytovatele (automaticke nalezeni z GuiTest)
        fl.write_account(env, self.lux.origin, name="Tester", email=mt.USER)
        self.start_gui()
        win = self.window()
        xdo(env, "windowactivate", "--sync", win)
        xdo(env, "key", "--clearmodifiers", "Return")      # Pokracovat jako Tester
        time.sleep(2.0)
        self.shot("luxai-04-prefilled.png")
        # e-mail je predvyplneny, fokus je v poli hesla: napsat jen heslo
        xdo(env, "type", "--delay", "20", mt.PASSWORD)
        xdo(env, "key", "Return")                          # hledani serveru
        time.sleep(2.5)
        xdo(env, "key", "Return")                          # Prihlasit
        self.assertTrue(mt.wait_for(lambda: len(self.accounts()) == 1, 20), "not added: " + self.s.service_log() + self.gui_log())
        a = self.accounts()[0]
        self.assertEqual(a["email"], mt.USER)
        self.assertNotEqual(a.get("auth", ""), "luxai")
        self.assertEqual(self.s.secret_lookup(a["id"]), mt.PASSWORD)

    def test_expired_session_sign_in_again(self):
        env = self.s.env
        # account.json ma starou relaci; "luxos-account login" (falesny) zapise novou
        fl.write_account(env, self.lux.origin, token="old-session-" + "y" * 30)
        tool = os.path.join(self.s.root, "fake-luxos-account")
        with open(tool, "w") as f:
            f.write("#!%s\nimport sys\nsys.path.insert(0, %r)\nimport fake_luxai as fl\n"
                    "assert sys.argv[1:] == ['login']\nfl.write_account({'XDG_CONFIG_HOME': %r}, %r)\n"
                    % (sys.executable, os.path.dirname(os.path.abspath(__file__)), env["XDG_CONFIG_HOME"], self.lux.origin))
        os.chmod(tool, 0o755)
        env["LUXOS_MAIL_ACCOUNT_TOOL"] = tool
        self.start_gui()
        win = self.window()
        xdo(env, "windowactivate", "--sync", win)
        xdo(env, "key", "--clearmodifiers", "Return")      # Pokracovat jako ... -> 401
        time.sleep(1.5)
        self.shot("luxai-06-expired.png")
        xdo(env, "key", "Tab")                             # Zrusit -> Prihlasit se...
        xdo(env, "key", "Return")
        # po prihlaseni se seznam schranek nacte znovu (uz s novou relaci)
        self.assertTrue(mt.wait_for(lambda: sum(1 for r in self.lux.requests if r["cookie_ok"]) >= 1, 15),
                        "no request with the new session: %r %s" % (self.lux.requests, self.gui_log()))
        time.sleep(1.5)
        self.shot("luxai-07-after-login.png")
        xdo(env, "key", "Return")                          # Pridat
        self.assertTrue(mt.wait_for(lambda: len(self.accounts()) == 1, 15), self.s.service_log() + self.gui_log())

    def test_use_another_account_prefills(self):
        env = self.s.env
        fl.write_account(env, self.lux.origin, name="Tester", email=mt.USER)
        self.start_gui()
        win = self.window()
        xdo(env, "windowactivate", "--sync", win)
        xdo(env, "key", "--clearmodifiers", "Tab")         # z "Pokracovat jako" na "Pouzit jiny ucet"
        xdo(env, "key", "Return")
        time.sleep(1.5)
        self.shot("luxai-05-another.png")
        xdo(env, "type", "--delay", "20", mt.PASSWORD)
        xdo(env, "key", "Return")
        time.sleep(2.5)
        xdo(env, "key", "Return")
        self.assertTrue(mt.wait_for(lambda: len(self.accounts()) == 1, 20), "not added: " + self.s.service_log() + self.gui_log())
        self.assertEqual(self.accounts()[0]["email"], mt.USER)
        # na server uctu LuxAI se pri "jiny ucet" nic neposilalo
        self.assertEqual(self.lux.requests, [])


if __name__ == "__main__":
    unittest.main()
