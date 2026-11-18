"""Nalezy z vizualni kontroly Posty ve virtualni obrazovce (nikdy na skutecne), cesky jazyk aplikace pri libc
locale en_US.UTF-8 (jako na kontrolovanem pocitaci):

    env -u DISPLAY xvfb-run -a -s "-screen 0 1440x900x24" dbus-run-session -- python3 -m unittest test_gui_review

- bez uctu jsou tlacitka nastrojove listy neaktivni, po pridani uctu aktivni
- spatne heslo: cesky text bez anglickeho "[AUTHENTICATIONFAILED] ..." ve vete (puvodni text jen v Podrobnostech)
- siroky zpravodaj (tabulka 700 px) v uzkem panelu: zvetseni < 1, aby nebyl oriznuty vpravo
LUXOS_MAIL_SCREENSHOTS=adresar ulozi snimky.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailtest as mt  # noqa: E402
import test_gui as tg  # noqa: E402

VIEW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures-view")


@unittest.skipUnless(tg.have_display(), "needs xvfb-run (never a real display)")
class ReviewTest(tg.GuiTest):
    test_add_account_read_notify = None     # bezi v test_gui

    def setUp(self):
        super().setUp()
        # cesky text Posty, libc jen en_US (cs_CZ nemusi byt vygenerovane)
        self.s.env["LC_MESSAGES"] = "cs_CZ.UTF-8"
        self.trace = os.path.join(self.s.root, "ui-trace.txt")
        self.s.env["LUXOS_MAIL_UI_TRACE"] = self.trace

    def lines(self, prefix):
        if not os.path.exists(self.trace):
            return []
        with open(self.trace) as f:
            return [line for line in f.read().split("\n") if line.startswith(prefix)]

    def last(self, prefix):
        found = self.lines(prefix)
        return found[-1] if found else ""

    def open_dialog(self):
        env = self.s.env
        self.start_gui()
        win = self.window()
        self.assertTrue(win)
        tg.xdo(env, "windowactivate", "--sync", win)
        self.assertEqual(self.last("toolbar "), "toolbar active=False", self.gui_log())
        self.shot("r01-welcome-toolbar-disabled.png")
        tg.xdo(env, "key", "--clearmodifiers", "Return")   # Pridat ucet...
        time.sleep(1.0)

    def test_wrong_password_and_toolbar(self):
        env = self.s.env
        self.open_dialog()
        tg.xdo(env, "type", "--delay", "20", mt.USER)
        tg.xdo(env, "key", "Tab")
        tg.xdo(env, "type", "--delay", "20", "spatne-heslo")
        tg.xdo(env, "key", "Return")       # hledani serveru
        time.sleep(2.5)
        self.shot("r02-add-account-details.png")
        tg.xdo(env, "key", "Return")       # Prihlasit
        self.assertTrue(mt.wait_for(lambda: "error=True" in self.last("dialog "), 20), self.gui_log() + self.s.service_log())
        msg = self.last("dialog ")
        text, details = msg.split(" | details=")
        self.assertIn("E-mailová adresa nebo heslo nejsou správné.", text)
        self.assertNotIn("AUTHENTICATIONFAILED", text)
        self.assertNotIn("Server", text)
        self.assertIn("[AUTHENTICATIONFAILED]", details)
        time.sleep(0.5)
        self.shot("r03-wrong-password.png")
        # spravne heslo ve stejnem okne: ucet pridan, tlacitka aktivni
        tg.xdo(env, "key", "ctrl+a")
        tg.xdo(env, "type", "--delay", "20", mt.PASSWORD)
        tg.xdo(env, "key", "Return")
        self.assertTrue(mt.wait_for(lambda: self.last("toolbar ") == "toolbar active=True", 20), self.gui_log() + self.s.service_log())

    def test_wide_newsletter_fits(self):
        env = self.s.env
        self.open_dialog()
        self.shot("r02-add-account-picks.png")
        tg.xdo(env, "type", "--delay", "20", mt.USER)
        tg.xdo(env, "key", "Tab")
        tg.xdo(env, "type", "--delay", "20", mt.PASSWORD)
        tg.xdo(env, "key", "Return")
        time.sleep(2.5)
        tg.xdo(env, "key", "Return")
        self.assertTrue(mt.wait_for(lambda: self.last("toolbar ") == "toolbar active=True", 20), self.gui_log() + self.s.service_log())
        time.sleep(1.5)
        self.server.control("deliver INBOX " + os.path.join(VIEW, "wide-newsletter.eml"))
        time.sleep(3.0)
        tg.xdo(env, "key", "F5")
        time.sleep(2.0)
        tg.xdo(env, "key", "ctrl+f")
        tg.xdo(env, "key", "Down")
        # prvni zvetseni muze prijit pred rozmistenim panelu (pane=1); po size-allocate se prizpusobi
        fitted = lambda: "content=700" in self.last("zoom ") and not self.last("zoom ").endswith("pane=1")  # noqa: E731
        self.assertTrue(mt.wait_for(fitted, 15), self.last("zoom ") + self.gui_log())
        z = self.last("zoom ")
        zoom = float(z.split()[1])
        pane = int(z.split("pane=")[1])
        self.assertLess(zoom, 1.0, z)
        # obsah 700 px + okraje se po zmenseni vejde do panelu
        self.assertLessEqual((700 + 44) * zoom, pane + 1, z)
        time.sleep(1.0)
        self.shot("r04-wide-newsletter-fit.png")


if __name__ == "__main__":
    unittest.main()
