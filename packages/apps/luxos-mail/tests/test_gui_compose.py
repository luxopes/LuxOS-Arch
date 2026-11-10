"""Psani, odesilani a zobrazeni zprav v okne Posty - jen ve virtualni obrazovce xvfb-run, nikdy na skutecne:

    env -u DISPLAY xvfb-run -a -s "-screen 0 1440x900x24" python3 -m unittest test_gui_compose

Docasny HOME a vsechny XDG_* (test odmitne bezet, kdyby nektera vedla do skutecneho domova), soukrome
XDG_RUNTIME_DIR (0700), vlastni D-Bus a klicenka; testovaci server IMAP + SMTP (nikdy skutecne doruceni).
Nova zprava s prilohou (Ctrl+N, vyber souboru, Ctrl+Enter), odpoved (Ctrl+R, \\Answered), preposlani s puvodni
prilohou (Ctrl+Shift+F), koncept na serveru a obnoveni po padu, Odchozi bez site a odeslani po pripojeni, Gmail bez
kopie do Odeslanych; zobrazeni HTML ve WebKitu: odkaz kliknutim (klavesnice) do prohlizece (zaznam misto spusteni),
vzdalene obrazky se bez povoleni nestahnou (testovaci server HTTP nevidi zadny pozadavek). Snimky svetle/tmave do
LUXOS_MAIL_SCREENSHOTS.
"""
import base64
import email
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest
from email import policy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_view_fixtures as mvf  # noqa: E402
import mailtest as mt  # noqa: E402
from test_gui import have_display, install_icons, screenshot, xdo  # noqa: E402

REAL_HOME = os.path.expanduser("~")


class Remote(http.server.BaseHTTPRequestHandler):
    hits = []

    def do_GET(self):
        Remote.hits.append(self.path)
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass


@unittest.skipUnless(have_display(), "needs xvfb-run (never a real display)")
class ComposeGuiTest(unittest.TestCase):
    personality = ""

    def setUp(self):
        self.s = mt.Session()
        env = self.s.env
        env["DISPLAY"] = os.environ["DISPLAY"]
        env["LANG"] = os.environ.get("LUXOS_MAIL_TEST_LANG", "en_US.UTF-8")
        if os.environ.get("XAUTHORITY"):
            env["XAUTHORITY"] = os.environ["XAUTHORITY"]
        # bezpecnost: nic nesmi vest do skutecneho domova ani skutecne relace
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
            self.assertFalse(os.path.realpath(env[key]).startswith(os.path.realpath(REAL_HOME) + "/.") or
                             os.path.realpath(env[key]) == os.path.realpath(REAL_HOME), key)
            self.assertTrue(env[key].startswith(self.s.root), key)
        self.assertEqual(os.stat(env["XDG_RUNTIME_DIR"]).st_mode & 0o777, 0o700)
        self.assertNotEqual(env["DISPLAY"], ":0")
        share = os.path.join(self.s.root, "share")
        install_icons(share, env)
        env["XDG_DATA_DIRS"] = share + ":/usr/local/share:/usr/share"
        env["LUXOS_MAIL_UI_TRACE"] = os.path.join(self.s.root, "ui-trace.log")
        env["LUXOS_MAIL_OPEN_URL_LOG"] = os.path.join(self.s.root, "opened.log")
        env["LUXOS_MAIL_DRAFT_SECONDS"] = "3"
        self.http = http.server.HTTPServer(("127.0.0.1", 0), Remote)
        Remote.hits = []
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.server = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, smtp=True, personality=self.personality,
                                    oauth="OAUTHBEARER,XOAUTH2")
        self.wm = None
        if shutil.which("xfwm4"):
            self.wm = subprocess.Popen(["xfwm4", "--compositor=off"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
        self.c = self.s.start_service()
        req = mt.account_request(self.server)
        req["smtp"] = {"host": "localhost", "port": self.server.ports["smtp_starttls"], "security": "starttls", "user": mt.USER}
        if self.personality == "gmail":
            req["provider"] = "google"
        r = self.c.call("add_account", **req)
        self.assertTrue(r["ok"], r)
        self.account = r["account"]
        self.gui = None
        self.shots = os.environ.get("LUXOS_MAIL_SCREENSHOTS", "")

    def tearDown(self):
        for p in (self.gui, self.wm):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
        try:
            self.c.call("quit")
        except OSError:
            pass
        self.http.shutdown()
        self.server.stop()
        self.s.close()

    # ---- pomucky ----
    def start_gui(self, theme="WhiteSur-Light"):
        env = dict(self.s.env)
        env["GTK_THEME"] = theme
        ready = os.path.join(self.s.root, "ready-%s-%d" % (theme, time.time() * 1000))
        env["LUXOS_MAIL_READY_FILE"] = ready
        with open(os.path.join(self.s.root, "gui.log"), "ab") as log:
            self.gui = subprocess.Popen([mt.binary()], env=env, stdout=subprocess.DEVNULL, stderr=log)
        self.assertTrue(mt.wait_for(lambda: os.path.exists(ready), 20), "window did not appear: " + self.gui_log())
        time.sleep(1.5)

    def stop_gui(self, crash=False):
        if crash:
            self.gui.kill()
        else:
            self.gui.terminate()
        self.gui.wait(5)

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

    def wait_trace(self, prefix, after=0, timeout=10):
        def found():
            for line in self.trace()[after:]:
                if line.startswith(prefix):
                    return line
            return None
        line = mt.wait_for(found, timeout)
        self.assertIsNotNone(line, "no trace %r: %s\n%s" % (prefix, self.trace()[-15:], self.gui_log()))
        return line

    def key(self, *keys):
        for k in keys:
            xdo(self.s.env, "key", "--clearmodifiers", k)
            time.sleep(0.25)

    def type(self, text):
        xdo(self.s.env, "type", "--delay", "25", text)
        time.sleep(0.3)

    def shot(self, name):
        if self.shots:
            os.makedirs(self.shots, exist_ok=True)
            screenshot(self.s.env, os.path.join(self.shots, name))

    def focus_main(self):
        r = subprocess.run(["xdotool", "search", "--classname", "luxos-mail"], env=self.s.env, capture_output=True, timeout=20)
        ids = r.stdout.decode().split()
        for w in ids:
            name = subprocess.run(["xdotool", "getwindowname", w], env=self.s.env, capture_output=True, timeout=10).stdout.decode()
            if "Mail" in name and "–" in name or name.strip() == "Mail":
                xdo(self.s.env, "windowactivate", "--sync", w)
                time.sleep(0.4)
                return w
        return ""

    def sent(self):
        out = []
        for m in self.server.control("smtp dump")["messages"]:
            m = dict(m)
            m["msg"] = email.message_from_bytes(base64.b64decode(m["data"]), policy=policy.default)
            out.append(m)
        return out

    def box(self, name):
        return self.server.control("dump")["boxes"].get(name, [])

    def select_first_message(self):
        self.focus_main()
        self.key("ctrl+f", "Down")
        time.sleep(1.5)

    def compose_new(self, to, subject, body):
        n = len(self.trace())
        self.key("ctrl+n")
        self.wait_trace("compose open", n)
        time.sleep(1.0)
        self.type(to)
        self.key("Tab", "Tab", "Tab")
        self.type(subject)
        self.key("Tab")
        self.type(body)

    def write_memory(self):
        """Pamet okna a procesu WebKitu (potomci okna) do metrics-view.json ve slozce snimku."""
        def rss(pid):
            try:
                with open("/proc/%d/status" % pid) as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            return int(line.split()[1])
            except OSError:
                pass
            return 0
        kids = {}
        for p in os.listdir("/proc"):
            if p.isdigit():
                try:
                    with open("/proc/%s/stat" % p) as f:
                        st = f.read()
                    comm = st[st.index("(") + 1:st.rindex(")")]
                    ppid = int(st[st.rindex(")") + 2:].split()[1])
                    kids.setdefault(ppid, []).append((int(p), comm))
                except (OSError, ValueError):
                    pass
        web = {}
        todo = [self.gui.pid]
        while todo:
            pid = todo.pop()
            for k, comm in kids.get(pid, []):
                todo.append(k)
                if comm.startswith("WebKit"):
                    web[comm + "-" + str(k)] = rss(k)
        with open(os.path.join(self.shots, "metrics-view.json"), "w") as f:
            json.dump({"gui_rss_kb": rss(self.gui.pid), "webkit_processes_rss_kb": web}, f, indent=1)

    # ---- testy ----
    def test_compose_send_reply_forward_and_view(self):
        self.start_gui()
        self.shot("10-main-light.png")
        # nova zprava s prilohou
        att = os.path.join(self.s.root, "Výkaz září.txt")
        with open(att, "w") as f:
            f.write("data přílohy\n")
        n = len(self.trace())
        self.key("ctrl+n")
        self.wait_trace("compose open", n)
        time.sleep(1.0)
        self.type("rcpt@example.org")
        self.key("Tab", "Tab", "Tab")
        self.type("Pozdrav z testu")
        self.key("Tab")
        self.type("Ahoj, posilam vykaz.")
        self.key("ctrl+shift+a")
        time.sleep(1.5)
        self.key("ctrl+l")
        self.type(att)
        self.key("Return")
        self.wait_trace("compose attachments 1", n)
        time.sleep(0.8)
        self.shot("11-compose-light.png")
        self.key("ctrl+Return")
        self.assertTrue(mt.wait_for(lambda: len(self.sent()) == 1, 20), (self.trace()[-10:], self.s.service_log()))
        m = self.sent()[0]
        self.assertEqual(m["rcpts"], ["rcpt@example.org"])
        self.assertEqual(str(m["msg"]["subject"]), "Pozdrav z testu")
        self.assertIn("Ahoj, posilam vykaz.", m["msg"].get_body(("plain",)).get_content())
        atts = list(m["msg"].iter_attachments())
        self.assertEqual(atts[0].get_filename(), "Výkaz září.txt")
        self.assertEqual(atts[0].get_content().replace("\r\n", "\n"), "data přílohy\n")
        self.assertTrue(mt.wait_for(lambda: len(self.box("Sent")) == 1, 10), "no copy in Sent")
        self.wait_trace("compose sent=True", n)
        # odpoved na zpravu ve vlakne (Message-ID, References)
        d = os.path.join(self.s.root, "view")
        mvf.main(d, "http://127.0.0.1:%d" % self.http.server_address[1])
        self.server.control("deliver INBOX " + os.path.join(d, "reply-thread.eml"))
        orig = email.message_from_bytes(open(os.path.join(d, "reply-thread.eml"), "rb").read(), policy=policy.default)
        time.sleep(3)
        self.select_first_message()
        n = len(self.trace())
        self.key("ctrl+r")
        self.wait_trace("compose open", n)
        time.sleep(1.0)
        self.type("Diky za zpravu.")
        self.shot("12-reply-light.png")
        self.key("ctrl+Return")
        self.assertTrue(mt.wait_for(lambda: len(self.sent()) == 2, 20), (self.trace()[-10:], self.s.service_log()))
        reply = self.sent()[1]["msg"]
        self.assertTrue(str(reply["subject"]).startswith("Re:"), reply["subject"])
        self.assertEqual(reply["in-reply-to"], orig["message-id"])
        self.assertEqual(reply["references"], "<p1@example.org> <p2@example.org> " + orig["message-id"])
        self.assertEqual(reply["to"].addresses[0].addr_spec, "petr@example.org")
        body = reply.get_body(("plain",)).get_content()
        self.assertTrue(body.startswith("Diky za zpravu."), body[:200])
        self.assertIn("wrote:", body)
        inbox = self.box("INBOX")
        self.assertTrue(mt.wait_for(lambda: any("\\Answered" in x["flags"] for x in self.box("INBOX")), 10), inbox)
        # preposlani zpravy s prilohou (fixture mixed-attachment je mezi zpravami)
        self.server.control("deliver INBOX " + os.path.join(mt.FIXTURES, "mixed-attachment.eml"))
        time.sleep(3)
        self.select_first_message()
        n = len(self.trace())
        self.key("ctrl+shift+f")
        self.wait_trace("compose open", n)
        time.sleep(1.0)
        self.type("fwd@example.org")
        self.key("ctrl+Return")
        self.assertTrue(mt.wait_for(lambda: len(self.sent()) == 3, 20), (self.trace()[-10:], self.s.service_log()))
        fwd = self.sent()[2]["msg"]
        self.assertTrue(str(fwd["subject"]).startswith("Fwd:"), fwd["subject"])
        self.assertIn("Forwarded message", fwd.get_body(("plain",)).get_content())
        self.assertGreaterEqual(len(list(fwd.iter_attachments())), 1)
        self.assertTrue(mt.wait_for(lambda: any("$Forwarded" in x["flags"] for x in self.box("INBOX")), 10))

    def deliver_view_fixtures(self):
        d = os.path.join(self.s.root, "view")
        mvf.main(d, "http://127.0.0.1:%d" % self.http.server_address[1])
        for name in ("malicious", "inline-image", "links-plain", "reply-thread", "newsletter", "security-alert"):
            self.server.control("deliver INBOX " + os.path.join(d, name + ".eml"))
        return d

    def test_view_links_and_remote_images(self):
        self.deliver_view_fixtures()
        for theme, suffix in (("WhiteSur-Light", "light"), ("WhiteSur-Dark", "dark")):
            self.start_gui(theme)
            n = len(self.trace())
            self.select_first_message()            # security-alert (nejnovejsi)
            names = {"Upozornění": "security-alert", "Týdenní": "newsletter", "Re: Re: Porada": "reply-thread",
                     "Odkazy": "links-plain", "Fotka": "inline-image", "Výhra": "malicious"}
            for i in range(6):
                if i > 0:
                    n = len(self.trace())
                    self.key("Down")
                line = self.wait_trace("show ", n)
                time.sleep(2.0)
                name = [v for k, v in names.items() if line[5:].startswith(k)]
                self.shot("view-%s-%s.png" % (name[0] if name else "msg%d" % i, suffix))
            if self.shots and suffix == "light":
                self.write_memory()
            self.stop_gui()
        # zadny pozadavek na vzdalene obrazky bez povoleni (ani sledovaci pixel)
        self.assertEqual(Remote.hits, [])
        trace = [l for l in self.trace() if l.startswith("view ")]
        self.assertTrue(any("remote=3" in l and "allowed=False" in l for l in trace), trace)
        # klepnuti na odkaz ve zprave -> prohlizec (zaznam misto spusteni), ne navigace uvnitr
        click = os.path.join(self.s.root, "click.eml")
        with open(click, "w") as f:
            f.write("From: Odkaz <link@example.org>\r\nTo: tester@example.test\r\nSubject: Klik\r\nDate: Wed, 11 Nov 2026 10:00:00 +0100\r\n"
                    "MIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
                    "<html><body style='margin:0'><a href='https://example.org/clicked?a=1&amp;b=2' style='display:block;font-size:40px;"
                    "padding:40px 20px;height:400px'>KLIKNI SEM</a></body></html>\r\n")
        self.server.control("deliver INBOX " + click)
        self.start_gui()
        self.select_first_message()
        time.sleep(2.0)
        self.wait_trace("show Klik")
        win = self.focus_main()
        xdo(self.s.env, "mousemove", "--window", win, "900", "300")
        time.sleep(0.5)
        self.shot("view-link-hover-light.png")
        xdo(self.s.env, "click", "1")
        log = self.s.env["LUXOS_MAIL_OPEN_URL_LOG"]
        ok = mt.wait_for(lambda: os.path.exists(log) and "https://example.org/clicked?a=1&b=2" in open(log).read(), 10)
        self.assertTrue(ok, (open(log).read() if os.path.exists(log) else "no log", self.trace()[-10:]))
        self.assertTrue(any(l.startswith("link https://example.org/clicked") for l in self.trace()))
        # obrazky vzdy od odesilatele newsletteru: az pak se stahnou
        with open(os.path.join(self.s.env["XDG_CONFIG_HOME"], "luxos-mail", "remote-images.json"), "w") as f:
            json.dump({"senders": ["news@news.example.org"]}, f)
        self.stop_gui()
        self.start_gui()
        self.select_first_message()                # Klik
        n = len(self.trace())
        self.key("Down", "Down")                   # security-alert, newsletter
        self.wait_trace("show Týdenní", n)
        self.assertTrue(mt.wait_for(lambda: any(h.startswith("/tip") for h in Remote.hits), 10), (Remote.hits, self.trace()[-6:]))
        self.assertFalse(any("open-pixel" in h or "track" in h for h in Remote.hits), Remote.hits)
        self.assertFalse(any("import.css" in h or "style.css" in h for h in Remote.hits), Remote.hits)

    def test_draft_autosave_crash_recovery_and_outbox(self):
        self.start_gui()
        self.compose_new("rcpt@example.org", "Rozepsaná zpráva", "Text konceptu")
        # koncept na serveru (LUXOS_MAIL_DRAFT_SECONDS=3) a mistni kopie
        self.assertTrue(mt.wait_for(lambda: len(self.box("Drafts")) == 1, 15), (self.trace()[-10:], self.s.service_log()))
        drafts_dir = os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail", "drafts")
        self.assertTrue([n for n in os.listdir(drafts_dir) if n.endswith(".json")])
        # pad Posty: rozepsana zprava se pri dalsim spusteni obnovi
        self.stop_gui(crash=True)
        n = len(self.trace())
        self.start_gui()
        self.wait_trace("compose open", n)
        self.wait_trace("compose status Recovered", n)
        self.shot("13-recovered-light.png")
        # bez site: zprava do Odchozi, odejde sama po pripojeni
        self.server.control("smtp down on")
        n = len(self.trace())
        self.key("ctrl+Return")
        self.wait_trace("compose sent=False", n, 20)
        self.assertEqual(self.sent(), [])
        time.sleep(1.0)
        # Odchozi z upozorneni (luxos-mail --outbox preda pozadavek bezicimu oknu), vybrana zprava s pruhem stavu
        n = len(self.trace())
        subprocess.run([mt.binary(), "--outbox"], env=self.s.env, timeout=20)
        time.sleep(1.0)
        self.focus_main()
        self.key("ctrl+f", "Down")
        self.wait_trace("show Rozepsaná zpráva", n)
        self.wait_trace("outbox banner", n)
        time.sleep(1.5)
        self.shot("14-outbox-light.png")
        outbox = os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail", "outbox")
        self.assertEqual(len([x for x in os.listdir(outbox) if x.endswith(".json")]), 1)
        self.server.control("smtp down off")
        self.c.call("reconnect")
        self.assertTrue(mt.wait_for(lambda: len(self.sent()) == 1, 20), self.s.service_log())
        self.assertTrue(mt.wait_for(lambda: [x for x in os.listdir(outbox) if x.endswith(".json")] == [], 10))
        self.assertEqual(str(self.sent()[0]["msg"]["subject"]), "Rozepsaná zpráva")
        # koncept po odeslani smazan, mistni kopie taky
        self.assertTrue(mt.wait_for(lambda: self.box("Drafts") == [], 10), self.box("Drafts"))
        self.assertEqual([n for n in os.listdir(drafts_dir) if n.endswith(".json")], [])
        # zavreni rozepsane zpravy: Ulozit -> koncept zustane na serveru
        self.focus_main()
        self.compose_new("x@example.org", "Na později", "zatím nic")
        n = len(self.trace())
        self.key("Escape")
        time.sleep(1.0)
        self.shot("15-save-draft-light.png")
        self.key("Return")                         # vychozi tlacitko Ulozit
        self.wait_trace("compose closed", n)
        self.assertTrue(mt.wait_for(lambda: len(self.box("Drafts")) == 1, 10), self.box("Drafts"))
        self.assertTrue(mt.wait_for(lambda: [n for n in os.listdir(drafts_dir) if n.endswith(".json")] == [], 10))


    @unittest.skipUnless(os.environ.get("LUXOS_MAIL_TEST_DND") == "1",
                         "xdotool drag between windows does not start a GTK drag under plain xvfb (even GTK to GTK); "
                         "LUXOS_MAIL_TEST_DND=1 where it works")
    def test_drag_and_drop_attachment(self):
        att = os.path.join(self.s.root, "přetažený soubor.txt")
        with open(att, "w") as f:
            f.write("obsah\n")
        src = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "dnd_source.py"), att],
                               env=self.s.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            src.stdout.readline()
            time.sleep(1.0)
            self.start_gui()
            self.compose_new("rcpt@example.org", "Přetažení", "text")
            time.sleep(1.0)
            r = subprocess.run(["xdotool", "search", "--sync", "--onlyvisible", "--pid", str(src.pid)], env=self.s.env, capture_output=True, text=True, timeout=15)
            self.assertTrue(r.stdout.split(), (src.poll(), src.stderr.read().decode() if src.poll() is not None else ""))
            sw = r.stdout.split()[0]
            xdo(self.s.env, "windowactivate", "--sync", sw)
            time.sleep(0.5)
            geo = subprocess.run(["xdotool", "getwindowgeometry", "--shell", sw], env=self.s.env, capture_output=True, text=True).stdout
            g = dict(l.split("=") for l in geo.split())
            sx, sy = int(g["X"]) + 60, int(g["Y"]) + 60
            r = subprocess.run(["xdotool", "search", "--name", "Přetažení"], env=self.s.env, capture_output=True, text=True, timeout=10)
            cw = r.stdout.split()[-1]
            geo = subprocess.run(["xdotool", "getwindowgeometry", "--shell", cw], env=self.s.env, capture_output=True, text=True).stdout
            g = dict(l.split("=") for l in geo.split())
            tx, ty = int(g["X"]) + int(g["WIDTH"]) // 2, int(g["Y"]) + int(g["HEIGHT"]) - 150
            n = len(self.trace())
            xdo(self.s.env, "mousemove", str(sx), str(sy))
            time.sleep(0.3)
            xdo(self.s.env, "mousedown", "1")
            time.sleep(0.2)
            for i in range(1, 6):
                xdo(self.s.env, "mousemove", str(sx + i * 4), str(sy + i * 4))
                time.sleep(0.05)
            for i in range(1, 21):
                xdo(self.s.env, "mousemove", str(sx + (tx - sx) * i // 20), str(sy + (ty - sy) * i // 20))
                time.sleep(0.05)
            time.sleep(0.5)
            xdo(self.s.env, "mouseup", "1")
            time.sleep(1.0)
            self.shot("16-dnd-drop.png")
            self.wait_trace("compose attachments 1", n)
            time.sleep(0.5)
            self.shot("16-dnd-light.png")
            self.key("ctrl+Return")
            self.assertTrue(mt.wait_for(lambda: len(self.sent()) == 1, 20), self.trace()[-8:])
            atts = list(self.sent()[0]["msg"].iter_attachments())
            self.assertEqual(atts[0].get_filename(), "přetažený soubor.txt")
            # text zpravy zustal (presunuti souboru nevlozilo adresu souboru do textu)
            self.assertEqual(self.sent()[0]["msg"].get_body(("plain",)).get_content().strip(), "text")
        finally:
            src.terminate()


class GmailComposeGuiTest(ComposeGuiTest):
    personality = "gmail"

    def test_compose_send_reply_forward_and_view(self):
        pass

    def test_view_links_and_remote_images(self):
        pass

    def test_draft_autosave_crash_recovery_and_outbox(self):
        pass

    def test_drag_and_drop_attachment(self):
        pass

    def test_gmail_send_without_sent_append(self):
        self.start_gui()
        self.compose_new("rcpt@example.org", "Z Gmailu", "Ahoj")
        self.key("ctrl+Return")
        self.assertTrue(mt.wait_for(lambda: len(self.sent()) == 1, 20), (self.trace()[-10:], self.s.service_log()))
        time.sleep(1.5)
        self.assertEqual(len(self.box("[Gmail]/Sent Mail")), 1)
        self.assertFalse(any(l.startswith("APPEND [Gmail]/Sent") for l in self.server.control("log")["log"]))


if __name__ == "__main__":
    unittest.main()
