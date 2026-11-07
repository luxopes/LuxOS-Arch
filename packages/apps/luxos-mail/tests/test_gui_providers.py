"""Druhy ucet Gmail vedle schranky LuxAI ve virtualni obrazovce (nikdy na skutecne):

    env -u DISPLAY xvfb-run -a -s "-screen 0 1440x900x24" python3 -m unittest test_gui_providers

Schranka LuxAI uz je pridana (falesny server uctu LuxAI, IMAP s tokeny). F10 -> Pridat ucet -> adresa
@gmail.com: hned napoveda "Google vyzaduje heslo aplikace" s tlacitkem (adresa se misto prohlizece zapise
do LUXOS_MAIL_OPEN_URL_LOG), oko zobrazi heslo, normalni heslo Google -> srozumitelna chyba s duvodem
serveru, heslo aplikace -> ucet pridany, slozky Gmailu ("Vse" az pod "Dalsi"). Falesny Gmail na localhost,
zadne spojeni s Googlem. LUXOS_MAIL_SCREENSHOTS=adresar ulozi snimky.
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
from test_providers import APP_PASSWORD, GMAIL_USER, GOOGLE_PASSWORD  # noqa: E402

LUXAI_BOX = "info@lux-ai.test"


@unittest.skipUnless(have_display(), "needs xvfb-run (never a real display)")
class GmailSecondAccountGuiTest(test_gui.GuiTest):
    test_add_account_read_notify = None

    def setUp(self):
        super().setUp()
        self.oserver = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, oauth="OAUTHBEARER,XOAUTH2")
        self.lux = fl.FakeLuxAI(self.oserver, [fl.mailbox(LUXAI_BOX, self.oserver.ports["tls"])])
        self.gmail = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, personality="gmail", user=GMAIL_USER,
                                   password=APP_PASSWORD, account_password=GOOGLE_PASSWORD)
        # autoconfig "poskytovatele" ukazuje na falesny Gmail (skutecna ISPDB by dala imap.gmail.com)
        test_gui.Autoconfig.body = ("<?xml version=\"1.0\"?><clientConfig version=\"1.1\"><emailProvider id=\"googlemail.com\">"
                                    "<incomingServer type=\"imap\"><hostname>localhost</hostname><port>%d</port><socketType>SSL</socketType>"
                                    "<username>%%EMAILADDRESS%%</username><authentication>OAuth2</authentication>"
                                    "<authentication>password-cleartext</authentication></incomingServer>"
                                    "<outgoingServer type=\"smtp\"><hostname>localhost</hostname><port>465</port><socketType>SSL</socketType>"
                                    "<username>%%EMAILADDRESS%%</username></outgoingServer></emailProvider></clientConfig>" % self.gmail.ports["tls"]).encode()
        self.urls = os.path.join(self.s.root, "opened-urls.txt")
        self.s.env["LUXOS_MAIL_OPEN_URL_LOG"] = self.urls

    def tearDown(self):
        super().tearDown()
        self.lux.stop()
        self.oserver.stop()
        self.gmail.stop()

    def accounts(self):
        path = os.path.join(self.s.env["XDG_CONFIG_HOME"], "luxos-mail", "accounts.json")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return json.load(f)

    def opened(self):
        if not os.path.exists(self.urls):
            return []
        with open(self.urls) as f:
            return [l for l in f.read().split("\n") if l]

    def gmail_auth(self):
        return [l for l in self.gmail.control("log")["log"] if " AUTHENTICATE " in l or " LOGIN " in l]

    def test_add_gmail_next_to_luxai(self):
        env = self.s.env
        fl.write_account(env, self.lux.origin, name="Antonín Test", email="owner@personal.example")
        c = self.s.start_service()
        r = c.call("add_luxai_account", address=LUXAI_BOX)
        self.assertTrue(r["ok"], (r, self.s.service_log()))
        c.close()
        self.start_gui()
        win = self.window()
        self.assertTrue(win)
        xdo(env, "windowactivate", "--sync", win)
        time.sleep(1.0)
        self.shot("gmail-01-luxai-only.png")
        # F10 = nabidka, prvni polozka "Pridat ucet..." je vybrana
        xdo(env, "key", "--clearmodifiers", "F10")
        time.sleep(0.8)
        self.shot("gmail-02-menu.png")
        xdo(env, "key", "Return")
        time.sleep(1.0)
        xdo(env, "type", "--delay", "15", GMAIL_USER)        # fokus je v poli E-mail
        time.sleep(0.5)
        xdo(env, "key", "Tab")                              # -> Heslo
        xdo(env, "type", "--delay", "15", GOOGLE_PASSWORD)
        time.sleep(0.5)
        self.shot("gmail-03-guidance-hidden-password.png")
        xdo(env, "key", "Tab")                              # -> oko
        xdo(env, "key", "space")                            # zobrazit heslo
        time.sleep(0.5)
        self.shot("gmail-04-password-shown.png")
        xdo(env, "key", "Tab")                              # -> Vytvorit heslo aplikace
        xdo(env, "key", "Return")
        self.assertTrue(mt.wait_for(lambda: self.opened() == ["https://myaccount.google.com/apppasswords"], 5),
                        "app password page not opened: %r %s" % (self.opened(), self.gui_log()))
        xdo(env, "key", "shift+Tab")                        # -> oko
        xdo(env, "key", "space")                            # skryt heslo
        xdo(env, "key", "shift+Tab")                        # -> Heslo
        xdo(env, "key", "Return")                           # hledani serveru
        time.sleep(2.5)
        self.shot("gmail-05-found.png")
        xdo(env, "key", "Return")                           # Prihlasit s normalnim heslem Google
        self.assertTrue(mt.wait_for(lambda: len(self.gmail_auth()) == 1, 15), self.s.service_log() + self.gui_log())
        time.sleep(1.5)
        self.shot("gmail-06-google-password-rejected.png")
        self.assertEqual(len(self.accounts()), 1)
        # heslo aplikace misto normalniho hesla
        xdo(env, "key", "ctrl+a")
        xdo(env, "type", "--delay", "15", APP_PASSWORD)
        xdo(env, "key", "Return")
        self.assertTrue(mt.wait_for(lambda: len(self.accounts()) == 2, 20), "not added: " + self.s.service_log() + self.gui_log())
        accounts = {a["email"]: a for a in self.accounts()}
        self.assertEqual(accounts[LUXAI_BOX].get("auth"), "luxai")
        self.assertEqual(accounts[GMAIL_USER].get("provider"), "google")
        self.assertEqual(self.s.secret_lookup(accounts[GMAIL_USER]["id"]), APP_PASSWORD)
        # odmitnute heslo 1x, heslo aplikace: overeni pri pridani + spojeni sluzby (zadne opakovani spatneho hesla)
        self.assertTrue(mt.wait_for(lambda: len(self.gmail_auth()) == 3, 10), self.gmail_auth())
        time.sleep(0.5)
        self.assertEqual(len(self.gmail_auth()), 3)
        time.sleep(2.5)
        self.shot("gmail-07-two-accounts.png")
        # "Dalsi" v levem sloupci (pod slozkami Gmailu; okno je ve virtualni obrazovce vzdy na stejnem miste)
        xdo(env, "mousemove", "188", "570", "click", "1")
        time.sleep(1.0)
        self.shot("gmail-07b-more-folders.png")
        xdo(env, "mousemove", "700", "20")
        # "All Mail" se nestahuje ani nepocita
        self.assertFalse([l for l in self.gmail.control("log")["log"] if "All Mail" in l])
        # zadne heslo v souborech Posty
        for base in (os.path.join(env["XDG_CONFIG_HOME"], "luxos-mail"), os.path.join(env["XDG_DATA_HOME"], "luxos-mail")):
            for root, dirs, files in os.walk(base):
                for name in files:
                    with open(os.path.join(root, name), "rb") as f:
                        data = f.read()
                    self.assertNotIn(APP_PASSWORD.encode(), data, name)
                    self.assertNotIn(GOOGLE_PASSWORD.encode(), data, name)
        self.assertNotIn(GOOGLE_PASSWORD, self.gui_log() + self.s.service_log())
        self.assertNotIn(APP_PASSWORD, self.gui_log() + self.s.service_log())
        # Zmenit heslo pro Gmail (F10 -> 3. polozka): pole s okem a napovedou Google
        xdo(env, "key", "F10")
        time.sleep(0.6)
        xdo(env, "key", "Down")
        xdo(env, "key", "Down")
        xdo(env, "key", "Return")
        time.sleep(1.2)
        self.shot("gmail-08-change-password.png")
        xdo(env, "key", "Escape")
        time.sleep(0.5)


if __name__ == "__main__":
    unittest.main()
