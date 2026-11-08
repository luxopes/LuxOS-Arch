"""Prihlaseni u poskytovatele v okne Posty ve virtualni obrazovce (nikdy na skutecne):

    env -u DISPLAY xvfb-run -a -s "-screen 0 1440x900x24" python3 -m unittest test_gui_oauth

Falesny Google a Microsoft (fake_oauth) s client ID v testovacim oauth-providers.json, falesny IMAP
(Gmail/Workspace: OAUTHBEARER, Microsoft: jen XOAUTH2). Prohlizec nahrazuje test: adresu, kterou by okno
otevrelo pres xdg-open, cte z LUXOS_MAIL_OPEN_URL_LOG a nasleduje presmerovani na loopback Posty
(zadny spusteny soubor navic). Soukromy HOME, XDG_RUNTIME_DIR (0700), D-Bus a klicenka z mailtest.Session.
Nikdy skutecny Google ani Microsoft. LUXOS_MAIL_SCREENSHOTS=adresar ulozi snimky (i stranky v prohlizeci,
kdyz je firefox: headless s docasnym profilem).
"""
import json
import os
import shutil
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_oauth as fo  # noqa: E402
import mailtest as mt  # noqa: E402
import test_gui  # noqa: E402
from test_gui import have_display, xdo  # noqa: E402

WORKSPACE = "anna@firma.test"
OUTLOOK = "tester@outlook.com"


@unittest.skipUnless(have_display(), "needs xvfb-run (never a real display)")
class OAuthGuiTest(test_gui.GuiTest):
    test_add_account_read_notify = None
    configured = True

    def setUp(self):
        super().setUp()
        self.gmail = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, personality="gmail", user=WORKSPACE,
                                   password="unused-app-password", oauth="OAUTHBEARER,XOAUTH2")
        self.outlook = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, personality="microsoft", user=OUTLOOK,
                                     password="never", oauth="XOAUTH2")
        self.google = fo.FakeOAuth(self.gmail, WORKSPACE, "test-google-client.apps.example", "GOCSPX-test-secret")
        self.ms = fo.FakeOAuth(self.outlook, OUTLOOK, "00000000-1111-2222-3333-444444444444", redirect_host="localhost", rotate=True)
        if self.configured:
            self.s.env["LUXOS_MAIL_OAUTH_PROVIDERS"] = fo.providers_file(
                os.path.join(self.s.root, "oauth-providers.json"), google=self.google, microsoft=self.ms,
                google_imap=self.gmail.ports["tls"], microsoft_imap=self.outlook.ports["tls"])
        # Google Workspace na vlastni domene: pozna se az podle MX (aspmx.l.google.com)
        with open(self.s.env["LUXOS_MAIL_FAKE_DNS"], "w") as f:
            json.dump({"MX:firma.test": [[1, "aspmx.l.google.com"], [5, "alt1.aspmx.l.google.com"]]}, f)
        test_gui.Autoconfig.body = ("<?xml version=\"1.0\"?><clientConfig version=\"1.1\"><emailProvider id=\"firma.test\">"
                                    "<incomingServer type=\"imap\"><hostname>localhost</hostname><port>%d</port><socketType>SSL</socketType>"
                                    "<username>%%EMAILADDRESS%%</username><authentication>OAuth2</authentication></incomingServer>"
                                    "</emailProvider></clientConfig>" % self.gmail.ports["tls"]).encode()
        self.urls = os.path.join(self.s.root, "opened-urls.txt")
        self.s.env["LUXOS_MAIL_OPEN_URL_LOG"] = self.urls
        self.trace = os.path.join(self.s.root, "ui-trace.txt")
        self.s.env["LUXOS_MAIL_UI_TRACE"] = self.trace

    def tearDown(self):
        super().tearDown()
        for x in (self.google, self.ms, self.gmail, self.outlook):
            x.stop()

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

    def modes(self):
        if not os.path.exists(self.trace):
            return []
        with open(self.trace) as f:
            return [l for l in f.read().split("\n") if l.startswith("auth-mode ")]

    def browser(self, count, name):
        """Prohlizec: posledni otevrena adresa -> poskytovatel -> presmerovani na loopback Posty."""
        self.assertTrue(mt.wait_for(lambda: len(self.opened()) >= count, 10), "browser not opened: %r %s" % (self.opened(), self.gui_log()))
        url = self.opened()[count - 1]
        status, body, headers = fo.follow(url)
        self.assertEqual(status, 200, body)
        if self.shots:
            path = os.path.join(self.shots, name + ".html")
            with open(path, "w") as f:
                f.write(body)
            firefox = shutil.which("firefox")
            if firefox:
                profile = os.path.join(self.s.root, "ff-profile")
                os.makedirs(profile, exist_ok=True)
                env = {k: v for k, v in self.s.env.items() if k not in ("DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS")}
                env["MOZ_HEADLESS"] = "1"
                subprocess.run([firefox, "--headless", "--no-remote", "--profile", profile, "--window-size", "900,560",
                                "--screenshot", os.path.join(self.shots, name + ".png"), "file://" + path],
                               env=env, capture_output=True, timeout=90)
        return url, body

    def active_is(self, win):
        r = subprocess.run(["xdotool", "getactivewindow"], env=self.s.env, capture_output=True, timeout=10)
        return r.stdout.decode().strip() == win

    def visible(self, win):
        r = subprocess.run(["xdotool", "search", "--onlyvisible", "--classname", "luxos-mail"], env=self.s.env,
                           capture_output=True, timeout=10)
        return win in r.stdout.decode().split()

    def open_add(self, env):
        xdo(env, "key", "--clearmodifiers", "F10")
        time.sleep(0.8)
        xdo(env, "key", "Return")
        time.sleep(1.0)


class ConfiguredTest(OAuthGuiTest):
    def test_google_workspace_and_microsoft(self):
        env = self.s.env
        self.start_gui()
        win = self.window()
        self.assertTrue(win)
        xdo(env, "windowactivate", "--sync", win)
        time.sleep(0.8)
        # uvitani -> Pridat ucet (F10 funguje i bez uctu)
        self.open_add(env)
        xdo(env, "type", "--delay", "15", WORKSPACE)
        time.sleep(0.5)
        self.shot("oauth-01-workspace-address.png")
        # neznama domena: heslo zatim viditelne; Enter bez hesla hleda server (MX -> Google)
        self.assertEqual(self.modes()[-1], "auth-mode  password")
        xdo(env, "key", "Return")
        self.assertTrue(mt.wait_for(lambda: self.modes() and self.modes()[-1] == "auth-mode google oauth", 15),
                        "%r %s" % (self.modes(), self.gui_log()))
        time.sleep(0.8)
        self.shot("oauth-02-sign-in-with-google.png")
        # Enter = hlavni tlacitko "Prihlasit se Googlem"
        xdo(env, "key", "Return")
        self.assertTrue(mt.wait_for(lambda: len(self.opened()) == 1, 10), self.gui_log() + self.s.service_log())
        time.sleep(0.6)
        self.shot("oauth-03-waiting-for-browser.png")
        # prohlizec je v popredi: okno Posty minimalizovane
        xdo(env, "windowminimize", "--sync", win)
        time.sleep(0.6)
        self.assertFalse(self.visible(win))
        url, body = self.browser(1, "oauth-04-browser-success")
        self.assertIn("You are signed in", body)
        self.assertTrue(mt.wait_for(lambda: len(self.accounts()) == 1, 15), self.s.service_log() + self.gui_log())
        a = self.accounts()[0]
        self.assertEqual((a["email"], a["auth"], a["provider"]), (WORKSPACE, "oauth", "google"))
        self.assertEqual(self.s.secret_lookup(a["id"]), list(self.google.refresh_tokens.keys())[0])
        # okno Posty se samo vratilo do popredi
        self.assertTrue(mt.wait_for(lambda: self.visible(win) and self.active_is(win), 10), "window not raised")
        time.sleep(2.5)
        self.shot("oauth-05-workspace-added.png")

        # Microsoft: domena outlook.com -> tlacitko hned, bez "heslo aplikace" (Microsoft ho pro IMAP nema)
        self.open_add(env)
        xdo(env, "type", "--delay", "15", OUTLOOK)
        self.assertTrue(mt.wait_for(lambda: self.modes()[-1] == "auth-mode microsoft oauth", 5), self.modes())
        time.sleep(0.6)
        self.shot("oauth-06-sign-in-with-microsoft.png")
        xdo(env, "key", "Return")
        url, body = self.browser(2, "oauth-07-browser-microsoft")
        self.assertIn("redirect_uri=http%3A%2F%2Flocalhost%3A", url)
        self.assertTrue(mt.wait_for(lambda: len(self.accounts()) == 2, 15), self.s.service_log() + self.gui_log())
        ms = [x for x in self.accounts() if x["email"] == OUTLOOK][0]
        self.assertEqual(ms["provider"], "microsoft")
        time.sleep(2.5)
        self.shot("oauth-08-two-accounts.png")

        # prihlaseni u Microsoftu vyprselo (zmena hesla): klidny pruh "Prihlasit se znovu"
        self.ms.revoke_refresh()
        self.outlook.control("revoke")
        c = mt.Client(self.s)
        r = c.call("retry_account", account=ms["id"])
        c.close()
        self.assertEqual(r["kind"], "oauth_expired", self.s.service_log())
        time.sleep(1.5)
        self.shot("oauth-09-sign-in-again-bar.png")
        # F10 -> 2. polozka "Prihlasit se znovu k ..." (aktualni ucet je Microsoft)
        xdo(env, "windowactivate", "--sync", win)
        xdo(env, "key", "--clearmodifiers", "F10")
        time.sleep(0.6)
        self.shot("oauth-10-menu.png")
        xdo(env, "key", "Down")
        xdo(env, "key", "Return")
        url, body = self.browser(3, "oauth-11-browser-again")
        self.assertIn("login_hint=" + OUTLOOK.replace("@", "%40"), url)
        c = mt.Client(self.s)
        self.assertTrue(mt.wait_for(lambda: [st for st in c.call("hello")["accounts"] if st["account"] == ms["id"]][0]["state"] == "online", 15),
                        self.s.service_log())
        c.close()
        time.sleep(1.5)
        self.shot("oauth-12-signed-in-again.png")
        self.assertEqual(len(self.accounts()), 2)
        # zadny token v souborech Posty ani v logu
        for fake in (self.google, self.ms):
            for sec in fake.secrets_seen():
                self.assertNotIn(sec, self.gui_log() + self.s.service_log())
                for base in (os.path.join(env["XDG_CONFIG_HOME"], "luxos-mail"), os.path.join(env["XDG_DATA_HOME"], "luxos-mail")):
                    for root, dirs, files in os.walk(base):
                        for name in files:
                            with open(os.path.join(root, name), "rb") as f:
                                self.assertNotIn(sec.encode(), f.read(), name)

    def test_microsoft_mailbox_not_connected_banner(self):
        # ucet Microsoft pridany pres sluzbu; pak Microsoft schranku neotevira ("User is authenticated but not
        # connected", zadna varianta zachrany nepomuze): pruh s navodem (IMAP v Outlook.com) a "Zkusit znovu",
        # ne "Prihlasit se znovu" (nove prihlaseni by nepomohlo)
        env = self.s.env
        env["LUXOS_MAIL_NOTCONNECTED_WAIT"] = "100"
        # cesky: overi i preklad navodu
        env["LANG"] = "cs_CZ.UTF-8"
        c = self.s.start_service()
        r = c.call("oauth_start", provider="microsoft", email=OUTLOOK)
        fo.follow(r["url"])
        self.assertTrue(mt.wait_for(lambda: len(self.accounts()) == 1, 15), self.s.service_log())
        acc = self.accounts()[0]["id"]
        self.assertTrue(mt.wait_for(lambda: [st for st in c.call("hello")["accounts"] if st["account"] == acc][0]["state"] == "online", 15))
        self.outlook.control("notconnected on")
        r = c.call("retry_account", account=acc)
        c.close()
        self.assertEqual(r["kind"], "notconnected", self.s.service_log())
        # okno se pripoji k bezici sluzbe a ukaze stav uctu
        self.start_gui()
        win = self.window()

        def banner():
            if not os.path.exists(self.trace):
                return ""
            with open(self.trace) as f:
                lines = [l for l in f.read().split("\n") if l.startswith("banner ")]
            return lines[-1] if lines else ""
        self.assertTrue(mt.wait_for(lambda: "Předávání a IMAP" in banner(), 10), banner() + self.gui_log())
        self.assertIn("account.live.com/activity", banner())
        self.assertIn("(Server: User is authenticated but not connected.)", banner())
        xdo(env, "windowactivate", "--sync", win)
        time.sleep(1.0)
        self.shot("oauth-15-microsoft-not-connected.png")

    def test_app_password_instead(self):
        env = self.s.env
        self.start_gui()
        win = self.window()
        xdo(env, "windowactivate", "--sync", win)
        time.sleep(0.8)
        self.open_add(env)
        xdo(env, "type", "--delay", "15", "someone@gmail.com")
        self.assertTrue(mt.wait_for(lambda: self.modes()[-1] == "auth-mode google oauth", 5), self.modes())
        # Tab -> "Prihlasit se Googlem", Tab -> "Pouzit radeji heslo aplikace"
        xdo(env, "key", "Tab")
        xdo(env, "key", "Tab")
        xdo(env, "key", "space")
        self.assertTrue(mt.wait_for(lambda: self.modes()[-1] == "auth-mode google password", 5), self.modes())
        time.sleep(0.6)
        self.shot("oauth-13-app-password-instead.png")
        self.assertEqual(self.opened(), [])


class NotConfiguredTest(OAuthGuiTest):
    """Bez client ID (jak se balik dodava): zadne tlacitko, napoveda k heslu aplikace jako drive."""
    configured = False

    def test_no_button_without_client_id(self):
        env = self.s.env
        self.start_gui()
        win = self.window()
        xdo(env, "windowactivate", "--sync", win)
        time.sleep(0.8)
        self.open_add(env)
        xdo(env, "type", "--delay", "15", "someone@gmail.com")
        self.assertTrue(mt.wait_for(lambda: self.modes() and self.modes()[-1] == "auth-mode google password", 5), self.modes())
        xdo(env, "key", "ctrl+a")
        xdo(env, "type", "--delay", "15", OUTLOOK)
        self.assertTrue(mt.wait_for(lambda: self.modes()[-1] == "auth-mode microsoft password", 5), self.modes())
        time.sleep(0.6)
        self.shot("oauth-14-microsoft-not-configured.png")
        self.assertNotIn("oauth", " ".join(self.modes()))


if __name__ == "__main__":
    unittest.main()
