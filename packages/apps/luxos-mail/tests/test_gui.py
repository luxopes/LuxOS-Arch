"""Test okna Posty ve virtualni obrazovce (nikdy na skutecne):

    env -u DISPLAY xvfb-run -a -s "-screen 0 1440x900x24" python3 -m unittest test_gui

Pridani uctu pres dialog (automaticke nalezeni z mistniho autoconfig, prihlaseni k testovacimu
serveru), seznam a zobrazeni zprav klavesnici, nova zprava -> upozorneni pres IDLE do par sekund,
oznaceni prectene, Delete -> Kos, filtr Ctrl+F. LUXOS_MAIL_SCREENSHOTS=adresar ulozi snimky
svetleho a tmaveho vzhledu.
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailtest as mt  # noqa: E402

FILES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files")


def have_display():
    # jen virtualni obrazovka xvfb-run (nikdy skutecna relace)
    return os.environ.get("DISPLAY", "") != "" and ("xvfb-run" in os.environ.get("XAUTHORITY", "") or os.environ.get("LUXOS_TEST_X") == "1")


class Autoconfig(http.server.BaseHTTPRequestHandler):
    body = b""

    def do_GET(self):
        if self.path.startswith("/mail/config-v1.1.xml"):
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.end_headers()
            self.wfile.write(Autoconfig.body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def xdo(env, *args):
    subprocess.run(["xdotool"] + list(args), env=env, check=False, timeout=20)


def screenshot(env, path):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", "1440x900", "-i", env["DISPLAY"],
                    "-frames:v", "1", path], env=env, check=False, timeout=30)


def install_icons(share, env):
    for size in (16, 24, 32, 48, 64, 128, 256):
        d = os.path.join(share, "icons", "hicolor", "%dx%d" % (size, size), "apps")
        os.makedirs(d, exist_ok=True)
        subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), os.path.join(FILES, "luxos-mail.svg"),
                        "-o", os.path.join(d, "luxos-mail.png")], check=True, env=env)


@unittest.skipUnless(have_display(), "needs xvfb-run (never a real display)")
class GuiTest(unittest.TestCase):
    def setUp(self):
        self.s = mt.Session()
        self.s.env["DISPLAY"] = os.environ["DISPLAY"]
        # GTK potrebuje locale, ktere v systemu existuje (cs_CZ nemusi byt vygenerovane)
        self.s.env["LANG"] = os.environ.get("LUXOS_MAIL_TEST_LANG", "en_US.UTF-8")
        if os.environ.get("XAUTHORITY"):
            self.s.env["XAUTHORITY"] = os.environ["XAUTHORITY"]
        share = os.path.join(self.s.root, "share")
        install_icons(share, self.s.env)
        self.s.env["XDG_DATA_DIRS"] = share + ":/usr/local/share:/usr/share"
        self.server = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES)
        Autoconfig.body = ("<?xml version=\"1.0\"?><clientConfig version=\"1.1\"><emailProvider id=\"example.test\">"
                           "<incomingServer type=\"imap\"><hostname>localhost</hostname><port>%d</port><socketType>SSL</socketType>"
                           "<username>%%EMAILADDRESS%%</username><authentication>password-cleartext</authentication></incomingServer>"
                           "<outgoingServer type=\"smtp\"><hostname>localhost</hostname><port>587</port><socketType>STARTTLS</socketType>"
                           "<username>%%EMAILADDRESS%%</username></outgoingServer></emailProvider></clientConfig>" % self.server.ports["tls"]).encode()
        self.http = http.server.HTTPServer(("127.0.0.1", 0), Autoconfig)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        port = self.http.server_address[1]
        self.s.env["LUXOS_MAIL_AUTOCONFIG_URLS"] = "http://127.0.0.1:%d/mail/config-v1.1.xml?emailaddress=%%EMAIL%%" % port
        self.s.env["LUXOS_MAIL_ISPDB_URL"] = "http://127.0.0.1:%d/none/%%DOMAIN%%" % port
        fake_dns = os.path.join(self.s.root, "dns.json")
        with open(fake_dns, "w") as f:
            json.dump({}, f)
        self.s.env["LUXOS_MAIL_FAKE_DNS"] = fake_dns
        self.wm = None
        if shutil.which("xfwm4"):
            self.wm = subprocess.Popen(["xfwm4", "--compositor=off"], env=self.s.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
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
        self.http.shutdown()
        self.server.stop()
        self.s.close()

    def start_gui(self, theme="WhiteSur-Light"):
        env = dict(self.s.env)
        env["GTK_THEME"] = theme
        ready = os.path.join(self.s.root, "ready-%s" % theme)
        env["LUXOS_MAIL_READY_FILE"] = ready
        t0 = time.time()
        with open(os.path.join(self.s.root, "gui.log"), "ab") as log:
            self.gui = subprocess.Popen([mt.binary()], env=env, stdout=subprocess.DEVNULL, stderr=log)
        self.assertTrue(mt.wait_for(lambda: os.path.exists(ready), 15), "window did not appear: " + self.gui_log())
        elapsed = time.time() - t0
        time.sleep(0.8)
        return elapsed

    def gui_log(self):
        try:
            with open(os.path.join(self.s.root, "gui.log"), errors="replace") as f:
                return f.read()[-3000:]
        except OSError:
            return ""

    def window(self):
        r = subprocess.run(["xdotool", "search", "--sync", "--classname", "luxos-mail"], env=self.s.env, capture_output=True, timeout=20)
        ids = r.stdout.decode().split()
        return ids[-1] if ids else ""

    def rss_kb(self, pid):
        with open("/proc/%d/status" % pid) as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
        return 0

    def shot(self, name):
        if self.shots:
            os.makedirs(self.shots, exist_ok=True)
            screenshot(self.s.env, os.path.join(self.shots, name))

    def index_rows(self):
        base = os.path.join(self.s.env["XDG_DATA_HOME"], "luxos-mail")
        for root, dirs, files in os.walk(base):
            if "index.tsv" in files and "INBOX" in open(os.path.join(root, "state.json")).read():
                with open(os.path.join(root, "index.tsv")) as f:
                    return [l for l in f.read().split("\n") if l]
        return []

    def test_add_account_read_notify(self):
        env = self.s.env
        elapsed = self.start_gui()
        self.shot("01-welcome-light.png")
        win = self.window()
        self.assertTrue(win)
        # Pridat ucet... (tlacitko uvitani ma fokus po Tab; jistejsi je kliknout doprostred okna)
        xdo(env, "windowactivate", "--sync", win)
        xdo(env, "key", "--clearmodifiers", "Return")   # fokus ma tlacitko Pridat ucet...
        time.sleep(1.0)
        xdo(env, "type", "--delay", "20", mt.USER)
        xdo(env, "key", "Tab")
        xdo(env, "type", "--delay", "20", mt.PASSWORD)
        self.shot("02-add-account-light.png")
        xdo(env, "key", "Return")       # hledani serveru
        time.sleep(2.5)
        self.shot("03-add-account-found-light.png")
        xdo(env, "key", "Return")       # Prihlasit (fokus zustava v poli hesla)
        ok = mt.wait_for(lambda: len(self.index_rows()) >= 9, 20)
        self.assertTrue(ok, "account was not added: " + self.s.service_log() + self.gui_log())
        time.sleep(1.5)
        self.shot("04-inbox-light.png")
        # heslo jen v klicence, nikde v souborech
        accounts = json.load(open(os.path.join(env["XDG_CONFIG_HOME"], "luxos-mail", "accounts.json")))
        self.assertEqual(self.s.secret_lookup(accounts[0]["id"]), mt.PASSWORD)
        for root, dirs, files in os.walk(self.s.home):
            for name in files:
                with open(os.path.join(root, name), "rb") as f:
                    self.assertNotIn(mt.PASSWORD.encode(), f.read(), name)
        # prvni zprava klavesnici: sipka dolu v seznamu (fokus na seznam pres Ctrl+F a Down)
        xdo(env, "key", "ctrl+f")
        xdo(env, "key", "Down")
        time.sleep(1.5)
        self.shot("05-message-light.png")
        rows = self.index_rows()
        newest_uid = rows[0].split("\t")[0]
        self.assertTrue(mt.wait_for(lambda: "S" in self.index_rows()[0].split("\t")[1], 10), "selected message was not marked read")
        # nova zprava -> upozorneni pres IDLE
        before = len(self.s.notifications())
        t0 = time.time()
        self.server.control("deliver INBOX " + os.path.join(mt.FIXTURES, "mixed-attachment.eml"))
        self.assertTrue(mt.wait_for(lambda: len(self.s.notifications()) > before, 10), "no notification")
        self.notify_seconds = time.time() - t0
        note = self.s.notifications()[-1]
        self.assertIn("Jan Novák", note["summary"])
        self.assertIn("Smlouva k podpisu", note["body"])
        self.assertTrue(mt.wait_for(lambda: len(self.index_rows()) >= 10, 10))
        time.sleep(1.0)
        self.shot("06-new-mail-light.png")
        # Delete -> Kos
        xdo(env, "key", "Delete")
        self.assertTrue(mt.wait_for(lambda: len(self.server.control("dump")["boxes"]["Trash"]) == 1, 10), "Delete did not move to Trash")
        # filtr
        xdo(env, "key", "ctrl+f")
        xdo(env, "type", "--delay", "20", "Grüße")
        time.sleep(1.0)
        self.shot("07-filter-light.png")
        rss = self.rss_kb(self.gui.pid)
        with open(os.path.join(self.s.root, "..", "luxos-mail-gui-metrics.json") if not self.shots else os.path.join(self.shots, "metrics.json"), "w") as f:
            json.dump({"startup_seconds_to_first_idle": elapsed, "ready_ms_in_process": open(os.path.join(self.s.root, "ready-WhiteSur-Light")).read().strip(),
                       "gui_rss_kb": rss, "service_rss_kb": self.rss_kb(mt.Client(self.s).call("hello")["pid"]),
                       "notification_seconds": self.notify_seconds}, f)
        # tmavy vzhled se stejnymi daty; spusteni s plnou mezipameti (10 zprav, sluzba uz bezi)
        self.gui.terminate()
        self.gui.wait(5)
        cached = self.start_gui("WhiteSur-Dark")
        cached_ms = open(os.path.join(self.s.root, "ready-WhiteSur-Dark")).read().strip()
        xdo(env, "key", "ctrl+f")
        xdo(env, "key", "Down")
        time.sleep(1.5)
        self.shot("08-message-dark.png")
        if self.shots:
            path = os.path.join(self.shots, "metrics.json")
            with open(path) as f:
                m = json.load(f)
            m.update({"startup_with_cache_seconds": cached, "startup_with_cache_ms_in_process": cached_ms,
                      "gui_rss_kb_with_message_open": self.rss_kb(self.gui.pid)})
            with open(path, "w") as f:
                json.dump(m, f, indent=1)


if __name__ == "__main__":
    unittest.main()
