"""Podokno zpravy nesmi nikdy ukazat hlavicku jedne zpravy s telem jine - jen ve virtualni obrazovce xvfb-run:

    env -u DISPLAY xvfb-run -a -s "-screen 0 1440x900x24" python3 -m unittest test_gui_pane

Chyba z ukazky na Gmailu: po presunu zpravy do Kose (nebo trvalem smazani v Kosi) ukazalo podokno hlavicku nove
vybrane zpravy, ale telo predchozi (WebKit drzel stary dokument, "Nacitani..." slo do skryteho textoveho pole).
Testovaci server IMAP se zpozdenim stazeni tela (bodydelay): pomale telo A, uzivatel mezitim vybere B (i B uz
v mezipameti), A dorazi pozde -> podokno ukazuje B; Kos + automaticky vyber dalsi zpravy; trvale smazani v Kosi
(EXPUNGE); stejne UID ve dvou slozkach. Okno zapisuje do LUXOS_MAIL_UI_TRACE, co je v podokne skutecne videt
("pane ... head=PREDMET | body=web:PREDMET TELA").

Docasny HOME a vsechny XDG_* (test odmitne bezet, kdyby nektera vedla do skutecneho domova), soukrome
XDG_RUNTIME_DIR (0700), vlastni D-Bus a klicenka, nikdy DISPLAY=:0.
"""
import os
import shutil
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailtest as mt  # noqa: E402
from test_gui import have_display, install_icons, xdo  # noqa: E402

REAL_HOME = os.path.realpath(os.path.expanduser("~"))
NAMES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
TRASH = "[Gmail]/Trash"


def eml(name, i):
    return ("From: Sender %s <%s@example.org>\r\nTo: tester@example.test\r\nSubject: %s\r\n"
            "Date: Wed, 11 Nov 2026 1%d:00:00 +0100\r\nMessage-ID: <%s@example.org>\r\nMIME-Version: 1.0\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\nThis is the body of %s.\r\n" % (name, name.lower(), name, i, name.lower(), name))


@unittest.skipUnless(have_display(), "needs xvfb-run (never a real display)")
class PaneGuiTest(unittest.TestCase):
    def setUp(self):
        self.s = self.server = self.c = self.gui = self.wm = None
        self.addCleanup(self.cleanup)
        self.s = mt.Session()
        env = self.s.env
        env["DISPLAY"] = os.environ["DISPLAY"]
        env["LANG"] = os.environ.get("LUXOS_MAIL_TEST_LANG", "en_US.UTF-8")
        if os.environ.get("XAUTHORITY"):
            env["XAUTHORITY"] = os.environ["XAUTHORITY"]
        share = os.path.join(self.s.root, "share")
        install_icons(share, env)
        env["XDG_DATA_DIRS"] = share + ":/usr/local/share:/usr/share"
        env["LUXOS_MAIL_UI_TRACE"] = os.path.join(self.s.root, "ui-trace.log")
        # bezpecnost: HOME a XDG_* domova jen v docasnem koreni testu; zadna XDG_* (ani zdedena) do skutecneho domova
        root = os.path.realpath(self.s.root) + "/"
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
            self.assertTrue(os.path.realpath(env[key]).startswith(root), "%s=%s" % (key, env[key]))
        for key, value in env.items():
            if not (key == "HOME" or key.startswith("XDG_")):
                continue
            for part in value.split(":"):
                if not part.startswith("/"):
                    continue          # XDG_SESSION_TYPE=x11 a podobne, nejde o cestu
                real = os.path.realpath(part)
                if real == REAL_HOME or real.startswith(REAL_HOME + "/"):
                    self.assertTrue(real.startswith(root), "%s points into the real home: %s" % (key, part))
        self.assertEqual(os.stat(env["XDG_RUNTIME_DIR"]).st_mode & 0o777, 0o700)
        self.assertNotIn(env["DISPLAY"], (":0", ":0.0"))
        self.server = mt.FakeServer(self.s.root, self.s.certs, personality="gmail")
        d = os.path.join(self.s.root, "msgs")
        os.makedirs(d)
        for i, name in enumerate(NAMES):
            path = os.path.join(d, name + ".eml")
            with open(path, "w") as f:
                f.write(eml(name, i))
            self.server.control("deliver INBOX " + path)      # UID 1..5 = Alpha..Echo (Echo nejnovejsi)
        self.wm = None
        if shutil.which("xfwm4"):
            self.wm = subprocess.Popen(["xfwm4", "--compositor=off"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
        self.c = self.s.start_service()
        req = mt.account_request(self.server)
        req["provider"] = "google"
        r = self.c.call("add_account", **req)
        self.assertTrue(r["ok"], r)
        self.account = r["account"]

    def cleanup(self):
        for p in (self.gui, self.wm):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
        if self.c:
            try:
                self.c.call("quit")
            except OSError:
                pass
        if self.server:
            self.server.stop()
        if self.s:
            self.s.close()

    # ---- pomucky ----
    def start_gui(self):
        env = dict(self.s.env)
        env["GTK_THEME"] = "WhiteSur-Light"
        ready = os.path.join(self.s.root, "ready-%d" % (time.time() * 1000))
        env["LUXOS_MAIL_READY_FILE"] = ready
        with open(os.path.join(self.s.root, "gui.log"), "ab") as log:
            self.gui = subprocess.Popen([mt.binary()], env=env, stdout=subprocess.DEVNULL, stderr=log)
        self.assertTrue(mt.wait_for(lambda: os.path.exists(ready), 20), "window did not appear: " + self.gui_log())
        time.sleep(1.5)

    def gui_log(self):
        try:
            with open(os.path.join(self.s.root, "gui.log"), errors="replace") as f:
                return f.read()[-3000:]
        except OSError:
            return ""

    def trace(self):
        try:
            with open(self.s.env["LUXOS_MAIL_UI_TRACE"]) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def panes(self, after=0):
        out = []
        for line in self.trace()[after:]:
            if line.startswith("pane ") and " head=" in line:
                head, body = line.split(" head=", 1)[1].split(" | body=", 1)
                out.append((line.split(" ")[1], head, body))
        return out

    def assert_never_mixed(self, after=0):
        """Telo zobrazene ve WebKitu patri vzdy ke zprave v hlavicce (jinak jen zastupny text)."""
        for why, head, body in self.panes(after):
            if body.startswith("web:"):
                self.assertEqual(body[4:], head, "header of one message with the body of another (%s): %s" % (why, self.panes(after)))
            else:
                self.assertIn(body, ("text:Loading…", "text:"), (why, head, body))

    def wait_pane(self, subject, after=0, timeout=15):
        def done():
            p = self.panes(after)
            return p and p[-1][1] == subject and p[-1][2] == "web:" + subject
        ok = mt.wait_for(done, timeout)
        self.assertTrue(ok, "pane did not settle on %r: %s\n%s" % (subject, self.panes(after)[-8:], self.gui_log()))

    def open(self, mailbox, uid):
        """Okno na dane zprave (jako akce Otevrit v upozorneni), vyber pres skutecny signal seznamu."""
        subprocess.run([mt.binary(), "--open", self.account, mailbox, str(uid)], env=self.s.env, timeout=20,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def key(self, *keys):
        for k in keys:
            xdo(self.s.env, "key", "--clearmodifiers", k)
            time.sleep(0.15)

    def box(self, name):
        return self.server.control("dump")["boxes"].get(name, [])

    def bodies(self, mailbox):
        """UID tel v mezipameti dane schranky."""
        import hashlib
        d = os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail", self.account, "m-" + hashlib.sha256(mailbox.encode()).hexdigest()[:16], "bodies")
        try:
            return sorted(int(n.split(".")[0]) for n in os.listdir(d) if n.endswith(".eml"))
        except OSError:
            return []

    # ---- testy ----
    def test_late_body_does_not_replace_newer_selection(self):
        self.start_gui()
        self.open("INBOX", 5)                        # Echo (nejnovejsi)
        self.wait_pane("Echo")
        self.key("Down")                             # Delta, Charlie do mezipameti
        self.wait_pane("Delta")
        self.key("Down")
        self.wait_pane("Charlie")
        # Bravo pomale; uzivatel mezitim prejde zpet na Charlie (v mezipameti) - pozdni Bravo ho nesmi prepsat
        self.server.control("bodydelay INBOX 2 3")
        n = len(self.trace())
        self.key("Down")
        time.sleep(0.6)
        self.key("Up")
        self.wait_pane("Charlie", n)
        time.sleep(4.0)                              # Bravo dorazi pozde
        self.assertIn(2, self.bodies("INBOX"), "slow body was not fetched at all")
        # pozdni odpoved opravdu dorazila a byla zahozena (ne ze by nikdy neprisla)
        self.assertTrue(any(l.startswith("body dropped uid=2 ") for l in self.trace()[n:]), self.trace()[n:])
        p = self.panes(n)
        self.assertEqual(p[-1][1:], ("Charlie", "web:Charlie"), p)
        self.assert_never_mixed(n)
        # pomale A, vyber B (bez mezipameti, ve fronte za A): po dokonceni obou podokno ukazuje B
        self.server.control("bodydelay INBOX 2 0")
        self.server.control("bodydelay INBOX 1 3")
        n = len(self.trace())
        self.open("INBOX", 1)                        # Alpha pomale
        time.sleep(0.6)
        self.open("INBOX", 2)                        # Bravo (uz v mezipameti)
        self.wait_pane("Bravo", n)
        time.sleep(4.0)
        self.assertEqual(self.panes(n)[-1][1:], ("Bravo", "web:Bravo"), self.panes(n))
        self.assert_never_mixed()

    def test_trash_auto_advance_shows_next_body(self):
        self.start_gui()
        self.open("INBOX", 5)                        # Echo v mezipameti
        self.wait_pane("Echo")
        self.server.control("bodydelay INBOX 4 2")   # Delta (dalsi po smazani) se stahuje pomalu
        n = len(self.trace())
        self.key("Delete")
        self.assertTrue(mt.wait_for(lambda: len(self.box(TRASH)) == 1, 10), "Delete did not move to Trash")
        self.wait_pane("Delta", n)
        self.assert_never_mixed(n)
        # znovu: Delta v mezipameti -> Smazat -> Charlie (bez zpozdeni)
        n = len(self.trace())
        self.key("Delete")
        self.assertTrue(mt.wait_for(lambda: len(self.box(TRASH)) == 2, 10), "second Delete did not move to Trash")
        self.wait_pane("Charlie", n)
        time.sleep(1.5)                              # zmena seznamu ze sluzby (changed) nesmi nic pokazit
        self.assertEqual(self.panes(n)[-1][1:], ("Charlie", "web:Charlie"), self.panes(n))
        self.assert_never_mixed()

    def test_permanent_delete_in_trash_and_same_uid_in_two_folders(self):
        self.start_gui()
        # Echo a Delta do Kose (v Kosi UID 1 = Echo, 2 = Delta; v Dorucene UID 1 = Alpha, 2 = Bravo)
        self.open("INBOX", 5)
        self.wait_pane("Echo")
        self.key("Delete")
        self.assertTrue(mt.wait_for(lambda: len(self.box(TRASH)) == 1, 10))
        self.wait_pane("Delta")
        self.key("Delete")
        self.assertTrue(mt.wait_for(lambda: len(self.box(TRASH)) == 2, 10))
        trash = {m["uid"] for m in self.box(TRASH)}
        self.assertEqual(trash, {1, 2})
        # stejne UID ve dvou slozkach: Alpha (INBOX UID 1) v mezipameti nesmi byt telem Echo (Kos UID 1)
        self.open("INBOX", 1)
        self.wait_pane("Alpha")
        self.open("INBOX", 2)
        self.wait_pane("Bravo")
        self.assertIn(1, self.bodies("INBOX"))
        n = len(self.trace())
        self.open(TRASH, 1)
        self.wait_pane("Echo", n)
        self.assert_never_mixed(n)
        # trvale smazani v Kosi (\Deleted + EXPUNGE), dalsi zprava (Delta, pomale telo) dostane vyber
        self.server.control("bodydelay %s 2 2" % TRASH)
        n = len(self.trace())
        self.key("Delete")
        time.sleep(1.0)
        self.key("Tab", "Return")                    # potvrzeni: Cancel -> Delete
        self.assertTrue(mt.wait_for(lambda: len(self.box(TRASH)) == 1, 10), ("permanent delete failed", self.box(TRASH), self.gui_log()))
        self.wait_pane("Delta", n)
        time.sleep(1.5)
        self.assertEqual(self.panes(n)[-1][1:], ("Delta", "web:Delta"), self.panes(n))
        self.assert_never_mixed()
        self.assertNotIn(1, self.bodies(TRASH), "body of the expunged message stayed in the cache")


if __name__ == "__main__":
    unittest.main()
