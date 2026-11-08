#!/usr/bin/env python3
"""LuxOS Mail - automaticky zaznam ukazkoveho videa pro overeni aplikace OAuth u Googlu.

Spoustet jen pres record-demo.sh (virtualni obrazovka xvfb 1920x1080, nikdy skutecna obrazovka).

Co se nahrava (anglicke rozhrani, vzhled LuxOS: xfwm4, tapeta, horni lista, Dock):
  A  plocha -> Posta z Docku -> Pridat ucet -> adresa Gmail -> upozorneni o pouziti dat + "Sign in with Google"
  G  prohlizec s adresou https://accounts.google.com/o/oauth2/v2/auth?...client_id=<skutecne ID>... -
     stranka je jen ZASTUPNA (mistni testovaci server, zadny pozadavek na Google); ve vyslednem videu ji
     nahradi zaznam skutecneho souhlasu od vlastnika (record-consent.sh)
  B  "You are signed in" -> Posta se vrati -> Dorucena posta, cteni zprav, priloha, slozky (stitky Gmailu),
     oznaceni neprectene, presun do Kose, odebrani uctu (smaze mistni data a odvola pristup)

Vse mistni: falesny IMAP v podobe Gmailu (demo_imap.py) s ukazkovymi zpravami, falesny koncovy bod tokenu
a odvolani (fake_oauth.py z testu Posty), prohlizec Firefox s docasnym profilem za mistni proxy, ktera
"accounts.google.com" obslouzi sama (vlastni testovaci CA jen v tomto profilu) a vse ostatni odmitne -
nic neodchazi do internetu. Soukromy HOME, XDG_RUNTIME_DIR (0700), D-Bus a klicenka. Procesy se ukoncuji
jen podle vlastnich PID (skupiny procesu), nikdy podle nazvu.

Vystup (OUT, vychozi ~/LuxOS-Arch/out/google-verification):
  raw/session.mp4         cely surovy zaznam
  parts/part-a.mp4, parts/part-g.mp4, parts/part-b.mp4   useky s titulky (1920x1080, 30 fps, H.264)
  parts/markers.json      casy useku a titulku
  luxos-mail-demo-preview.mp4   cele video se zastupnou kartou misto souhlasu (assemble.py)
"""
import argparse
import email.utils
import http.server
import json
import os
import select
import shutil
import signal
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from email.message import EmailMessage

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PKG = os.path.join(REPO, "packages")
TESTS = os.path.join(PKG, "apps", "luxos-mail", "tests")
XDG = os.path.join(PKG, "luxos-desktop", "files", "xdg")
sys.path.insert(0, TESTS)
sys.path.insert(0, HERE)
import mailtest as mt  # noqa: E402
import fake_oauth as fo  # noqa: E402
import assemble  # noqa: E402

W, H = 1920, 1080
FPS = 30
CLIENT_ID = "167842547008-kl3g01rd4b424v6q8msuj7ue47eodm52.apps.googleusercontent.com"
# jen pro falesny koncovy bod tokenu na 127.0.0.1 (skutecne tajemstvi klienta neni v gitu a sem nepatri)
DEMO_SECRET = "GOCSPX-demo-placeholder-not-real"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
WALLPAPER = os.path.join(PKG, "luxos-branding", "files", "wallpapers", "luxos-aurora-blue.jpg")


def log(msg):
    print("record-demo: " + msg, flush=True)


def guard_display():
    d = os.environ.get("DISPLAY", "")
    if os.environ.get("LUXOS_DEMO_XVFB") != "1" or not d or d in (":0", ":0.0") or \
            "xvfb-run" not in os.environ.get("XAUTHORITY", ""):
        sys.exit("record-demo: run me through docs/google-verification/record-demo.sh (xvfb only)")


# ---- ukazkove zpravy --------------------------------------------------------------------------------
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
       b"trailer<</Root 1 0 R>>\n" + (b"%" + b"0" * 63 + b"\n") * 2400 + b"%%EOF\n")

# (od, adresa, predmet, pred kolika hodinami, prectena, text, priloha)
INBOX = [
    ("Book Club", "bookclub@example.org", "November pick: The Left Hand of Darkness", 70, True,
     "Hi everyone,\n\nthe votes are in and our November book is The Left Hand of Darkness by Ursula K. Le Guin.\n\n"
     "We meet on the last Thursday of the month at 7 pm in the library cafe.\n\nHappy reading!\nThe Book Club", None),
    ("City Library", "library@example.net", "Your reservation is ready for pickup", 52, True,
     "Hello Alex,\n\nthe book you reserved is ready for pickup at the front desk:\n\n"
     "  The Pragmatic Programmer, 20th Anniversary Edition\n\nWe will keep it for you until Saturday.\n\nCity Library", None),
    ("Mia Chen", "mia.chen@example.com", "The soup recipe you asked for", 30, True,
     "Hi Alex,\n\nhere it is - my grandmother's pumpkin soup. Roast the pumpkin with garlic first, that is the "
     "whole secret.\n\nEnjoy!\nMia", None),
    ("Daniel Park", "daniel.park@example.com", "Lunch on Friday?", 20, False,
     "Hey Alex,\n\nare you free for lunch on Friday? The new noodle place near the station opened this week and "
     "I have heard great things about it.\n\nNoon works for me.\n\nDaniel", None),
    ("Sofia Rossi", "sofia.rossi@example.org", "Re: Project timeline", 6, False,
     "Hi Alex,\n\nthanks for the update. The new timeline looks good to me. I moved the design review to Tuesday "
     "so we have a full week for testing before the release.\n\nI attached the updated plan.\n\nBest,\nSofia",
     "project-plan.pdf"),
    ("Emma Wilson", "emma.wilson@example.org", "Photos from the weekend hike", 1, False,
     "Hi Alex,\n\nwhat a great weekend! The view from the ridge was worth every step, even with the wind at the "
     "top.\n\nI put my favourite photos and the trail map in the attachment. Same trail in spring, this time with "
     "the waterfall loop?\n\nSee you soon,\nEmma", "trail-map.pdf"),
]
TRAVEL = [
    ("Rail Europe Demo", "tickets@example.net", "Your train tickets: Prague - Vienna", 120, True,
     "Hello Alex,\n\nthank you for your booking. Your e-tickets for Saturday are attached.\n\n"
     "Departure 08:12 from Praha hl.n., arrival 12:10 at Wien Hbf.\n\nHave a nice trip!", "tickets.pdf"),
]
RECEIPTS = [
    ("Corner Bookshop", "orders@example.com", "Receipt for your order #1042", 200, True,
     "Thank you for your order!\n\n1x The Left Hand of Darkness   12.90 EUR\n\nTotal: 12.90 EUR", None),
]


def write_messages(folder, user, name, items):
    os.makedirs(folder, exist_ok=True)
    now = time.time()
    paths = []
    for i, (sender, addr, subject, hours, seen, text, attach) in enumerate(items):
        m = EmailMessage()
        m["From"] = email.utils.formataddr((sender, addr))
        m["To"] = email.utils.formataddr((name, user))
        m["Subject"] = subject
        m["Date"] = email.utils.formatdate(now - hours * 3600, localtime=True)
        m["Message-ID"] = email.utils.make_msgid(domain="example.com")
        m.set_content(text)
        if attach:
            m.add_attachment(PDF, maintype="application", subtype="pdf", filename=attach)
        path = os.path.join(folder, "%02d-%s.eml" % (i, "seen" if seen else "new"))
        with open(path, "wb") as f:
            f.write(bytes(m))
        paths.append((path, seen))
    return paths


# ---- zastupna stranka "accounts.google.com" (proxy jen pro Firefox v tomto zaznamu) ----------------------
PLACEHOLDER = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Placeholder - Google consent screen</title>
<style>body{margin:0;font:16px/1.5 Inter,sans-serif;background:#eef1f8;color:#1d2340;display:flex;align-items:center;
justify-content:center;min-height:100vh}main{background:#fff;border:3px dashed #8a93b8;border-radius:18px;padding:36px 44px;
max-width:720px;box-shadow:0 10px 40px rgba(20,30,80,.12)}h1{font-size:26px;margin:0 0 10px}p{margin:0 0 14px;color:#4a5272}
code{background:#eef1f8;padding:2px 6px;border-radius:5px;font-size:14px}.tag{display:inline-block;background:#ffe9a8;color:#5a4300;
font-weight:700;font-size:13px;padding:3px 10px;border-radius:20px;margin-bottom:12px}a.btn{display:inline-block;background:#3b5bdb;
color:#fff;text-decoration:none;font-weight:600;padding:10px 22px;border-radius:9px;margin-top:6px}ul{margin:0 0 14px;color:#4a5272}</style>
</head><body><main><span class="tag">PLACEHOLDER - DEMO RECORDING</span>
<h1>Google's consent screen appears here</h1>
<p>In the final video this part is the <b>real</b> Google sign-in and consent screen for <b>LuxOS Mail</b>,
recorded on the developer's computer (record-consent.sh).</p>
<p>LuxOS Mail asks for these scopes:</p><ul>%(scopes)s</ul>
<p>Client ID in the address bar: <code>%(client)s</code></p>
<p>This demo uses a local test server - nothing is sent to Google.</p>
<a class="btn" id="continue" href="%(next)s">Continue with the demo account</a></main></body></html>"""


class GoogleProxy:
    """HTTP proxy pro Firefox: CONNECT accounts.google.com:443 -> mistni TLS (certifikat testovaci CA) se zastupnou
    strankou; vse ostatni 403 (Firefox nikam jinam nesmi)."""

    def __init__(self, cert, key, fake_oauth_origin):
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(cert, key)
        self.origin = fake_oauth_origin
        self.requests = []
        self.blocked = []
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                line = self.rfile.readline(65536).decode("latin-1").strip()
                while True:
                    h = self.rfile.readline(65536)
                    if h in (b"\r\n", b"\n", b""):
                        break
                parts = line.split(" ")
                if len(parts) == 3 and parts[0] == "CONNECT" and parts[1] == "accounts.google.com:443":
                    self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                    self.wfile.flush()
                    try:
                        tls = outer.ctx.wrap_socket(self.connection, server_side=True)
                    except (ssl.SSLError, OSError):
                        return
                    outer.serve_tls(tls)
                    return
                outer.blocked.append(line)
                self.wfile.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")

        class Srv(socketserver.ThreadingMixIn, socketserver.TCPServer):
            daemon_threads = True
            allow_reuse_address = True
        self.srv = Srv(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def serve_tls(self, tls):
        f = tls.makefile("rwb")
        try:
            while True:
                line = f.readline(65536).decode("latin-1").strip()
                if not line:
                    return
                while True:
                    h = f.readline(65536)
                    if h in (b"\r\n", b"\n", b""):
                        break
                method, target, _v = (line.split(" ") + ["", ""])[:3]
                self.requests.append(target)
                u = urllib.parse.urlsplit(target)
                if method == "GET" and u.path == "/o/oauth2/v2/auth":
                    q = dict(urllib.parse.parse_qsl(u.query))
                    scopes = "".join("<li><code>%s</code></li>" % s for s in q.get("scope", "").split())
                    body = PLACEHOLDER % {"scopes": scopes, "client": q.get("client_id", ""),
                                          "next": self.origin + "/authorize?" + u.query}
                    data = body.encode()
                    f.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\n"
                            b"Content-Length: %d\r\n\r\n" % len(data) + data)
                else:
                    f.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                f.flush()
        except (OSError, ValueError):
            return
        finally:
            try:
                tls.close()
            except OSError:
                pass

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


FIREFOX_PREFS = {
    "browser.shell.checkDefaultBrowser": False, "browser.startup.homepage_override.mstone": "ignore",
    "startup.homepage_welcome_url": "", "startup.homepage_welcome_url.additional": "",
    "browser.aboutwelcome.enabled": False, "trailhead.firstrun.didSeeAboutWelcome": True,
    "datareporting.policy.dataSubmissionEnabled": False, "datareporting.healthreport.uploadEnabled": False,
    "toolkit.telemetry.enabled": False, "toolkit.telemetry.unified": False, "app.normandy.enabled": False,
    "app.shield.optoutstudies.enabled": False, "browser.safebrowsing.malware.enabled": False,
    "browser.safebrowsing.phishing.enabled": False, "browser.safebrowsing.downloads.enabled": False,
    "extensions.update.enabled": False, "app.update.enabled": False, "network.captive-portal-service.enabled": False,
    "network.connectivity-service.enabled": False, "browser.newtabpage.enabled": False,
    "browser.tabs.warnOnClose": False, "browser.sessionstore.resume_from_crash": False,
    "browser.uitour.enabled": False, "browser.urlbar.suggest.quicksuggest.sponsored": False,
    "browser.translations.enable": False, "media.gmp-manager.updateEnabled": False,
    "extensions.pocket.enabled": False, "identity.fxaccounts.enabled": False, "signon.rememberSignons": False,
    "browser.download.panel.shown": True, "browser.toolbars.bookmarks.visibility": "never",
    "network.proxy.type": 1, "network.proxy.ssl": "127.0.0.1", "network.proxy.http": "127.0.0.1",
    "network.proxy.no_proxies_on": "127.0.0.1, localhost", "network.proxy.allow_hijacking_localhost": False,
    "network.dns.disablePrefetch": True, "network.prefetch-next": False, "network.http.speculative-parallel-limit": 0,
    "security.OCSP.enabled": 0, "security.remote_settings.crlite_filters.enabled": False,
    "services.settings.server": "https://127.0.0.1:9/", "browser.ping-centre.telemetry": False,
    "layout.css.devPixelsPerPx": "1.25", "browser.urlbar.trimURLs": False, "browser.urlbar.trimHttps": False,
    "ui.systemUsesDarkTheme": 0,
}


# ---- relace ------------------------------------------------------------------------------------------
class Demo:
    def __init__(self, out, mail_bin, email_addr, name):
        self.out = out
        self.email = email_addr
        self.name = name
        self.mail_bin = mail_bin
        os.makedirs(out, exist_ok=True)
        self.root = tempfile.mkdtemp(prefix="run-", dir=out)
        self.procs = []
        self.markers = []
        self.t0 = None
        self.ffmpeg = None

    # -- procesy (jen vlastni skupiny procesu) --
    def spawn(self, cmd, env=None, log_name=None, **kw):
        logf = open(os.path.join(self.root, (log_name or os.path.basename(cmd[0])) + ".log"), "ab")
        p = subprocess.Popen(cmd, env=env or self.env, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True, cwd=self.home, **kw)
        self.procs.append(p)
        return p

    def stop_all(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except OSError:
                    pass
        end = time.time() + 6
        for p in self.procs:
            try:
                p.wait(max(0.1, end - time.time()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
        pid = getattr(self, "keyring_pid", 0)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    def xdo(self, *args):
        r = subprocess.run(["xdotool"] + [str(a) for a in args], env=self.env, capture_output=True, text=True, timeout=30)
        return r.stdout.strip()

    def key(self, keys, delay=0.5):
        self.xdo("key", "--clearmodifiers", *keys.split())
        time.sleep(delay)

    def type(self, text, delay=0.5, per_key=70):
        self.xdo("type", "--delay", per_key, text)
        time.sleep(delay)

    def move(self, x, y, steps=18, duration=0.6):
        """Plynuly pohyb mysi (v zaznamu je videt kurzor)."""
        cur = self.xdo("getmouselocation", "--shell")
        try:
            vals = dict(l.split("=") for l in cur.splitlines() if "=" in l)
            sx, sy = int(vals["X"]), int(vals["Y"])
        except (KeyError, ValueError):
            sx, sy = x, y
        for i in range(1, steps + 1):
            self.xdo("mousemove", int(sx + (x - sx) * i / steps), int(sy + (y - sy) * i / steps))
            time.sleep(duration / steps)

    def click(self, x, y, delay=0.8):
        self.move(x, y)
        time.sleep(0.25)
        self.xdo("click", 1)
        time.sleep(delay)

    def geometry(self, win):
        out = self.xdo("getwindowgeometry", "--shell", win)
        vals = dict(l.split("=") for l in out.splitlines() if "=" in l)
        return int(vals.get("X", 0)), int(vals.get("Y", 0)), int(vals.get("WIDTH", 0)), int(vals.get("HEIGHT", 0))

    def wait_window(self, timeout=30, **search):
        args = ["search", "--onlyvisible"]
        for k, v in search.items():
            args += ["--" + k, str(v)]
        end = time.time() + timeout
        while time.time() < end:
            ids = self.xdo(*args).split()
            if ids:
                return ids[-1]
            time.sleep(0.3)
        raise RuntimeError("window did not appear: %r" % (search,))

    def shot(self, name):
        """Ladici snimek obrazovky (jen v adresari behu)."""
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", "%dx%d" % (W, H),
                        "-i", self.env["DISPLAY"], "-frames:v", "1", os.path.join(self.root, "shot-" + name + ".png")],
                       env=self.env, timeout=30)

    # -- znacky v zaznamu --
    def now(self):
        return time.time() - self.t0

    def mark(self, kind, **data):
        data.update({"kind": kind, "t": round(self.now(), 2)})
        self.markers.append(data)
        log("  %6.1fs %s %s" % (data["t"], kind, data.get("text", data.get("name", ""))))

    def caption(self, text, sub=""):
        self.mark("caption", text=text, sub=sub)

    # -- priprava --
    def setup(self):
        root = self.root
        self.home = os.path.join(root, "home")
        run = os.path.join(root, "run")
        os.makedirs(run, mode=0o700)
        os.chmod(run, 0o700)
        cfg = os.path.join(self.home, ".config")
        for v in ("gtk-3.0", "gtk-4.0"):
            os.makedirs(os.path.join(cfg, v), exist_ok=True)
            src = os.path.join(XDG, v, "settings.ini")
            if os.path.exists(src):
                shutil.copy(src, os.path.join(cfg, v, "settings.ini"))
        # xfconf: nastaveni LuxOS ze zdroju; xvfb bez kompozitoru (stiny oken by byly cerne)
        xf = os.path.join(cfg, "xfce4", "xfconf", "xfce-perchannel-xml")
        os.makedirs(xf, exist_ok=True)
        src_xf = os.path.join(XDG, "xfce4", "xfconf", "xfce-perchannel-xml")
        for name in ("xfwm4.xml", "xsettings.xml", "xfce4-panel.xml"):
            p = os.path.join(src_xf, name)
            if os.path.exists(p):
                text = open(p, encoding="utf-8").read().replace(
                    'name="use_compositing" type="bool" value="true"', 'name="use_compositing" type="bool" value="false"')
                with open(os.path.join(xf, name), "w", encoding="utf-8") as f:
                    f.write(text)
        # Dock: polozky LuxOS + Posta (sestavena ze zdroju)
        skel = os.path.join(PKG, "luxos-desktop", "files", "skel", ".config", "plank")
        shutil.copytree(skel, os.path.join(cfg, "plank"))
        apps = os.path.join(self.home, ".local", "share", "applications")
        os.makedirs(apps, exist_ok=True)
        with open(os.path.join(apps, "luxos-mail.desktop"), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=Mail\nIcon=luxos-mail\nExec=%s\nStartupWMClass=luxos-mail\n" % self.mail_bin)
        with open(os.path.join(cfg, "plank", "dock1", "launchers", "luxos-mail.dockitem"), "w") as f:
            f.write("[PlankDockItemPreferences]\nLauncher=file://%s\n" % os.path.join(apps, "luxos-mail.desktop"))
        share = os.path.join(root, "share")
        for size in (16, 24, 32, 48, 64, 128, 256):
            d = os.path.join(share, "icons", "hicolor", "%dx%d" % (size, size), "apps")
            os.makedirs(d, exist_ok=True)
            subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size),
                            os.path.join(PKG, "apps", "luxos-mail", "files", "luxos-mail.svg"),
                            "-o", os.path.join(d, "luxos-mail.png")], check=True, timeout=30)
        bindir = os.path.join(root, "bin")
        os.makedirs(bindir)
        env = {k: v for k, v in os.environ.items() if k not in (
            "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "SSH_AUTH_SOCK", "GNOME_KEYRING_CONTROL", "XDG_DATA_DIRS",
            "LC_ALL", "LC_MESSAGES", "SESSION_MANAGER", "XDG_SESSION_ID", "XDG_SEAT", "XDG_VTNR")}
        env.update({"HOME": self.home, "XDG_RUNTIME_DIR": run, "XDG_CONFIG_HOME": cfg,
                    "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
                    "XDG_CACHE_HOME": os.path.join(self.home, ".cache"),
                    "XDG_STATE_HOME": os.path.join(self.home, ".local", "state"),
                    "XDG_CONFIG_DIRS": "/etc/xdg", "XDG_DATA_DIRS": share + ":/usr/local/share:/usr/share",
                    "XDG_CURRENT_DESKTOP": "XFCE", "XDG_SESSION_TYPE": "x11", "GDK_BACKEND": "x11",
                    "LANG": "en_US.UTF-8", "LANGUAGE": "en", "NO_AT_BRIDGE": "1", "GTK_USE_PORTAL": "0",
                    "GIO_USE_VFS": "local", "PATH": bindir + ":" + os.environ.get("PATH", "/usr/bin"),
                    "TMPDIR": os.path.join(root, "tmp"), "PYTHONDONTWRITEBYTECODE": "1",
                    "GIT_CEILING_DIRECTORIES": root})
        os.makedirs(env["TMPDIR"])
        self.env = env
        self.bindir = bindir
        # vlastni sbernice relace a odemcena klicenka (obnovovaci token se ulozi jako v LuxOS)
        p = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"], stdout=subprocess.PIPE,
                             env=env, start_new_session=True)
        self.procs.append(p)
        env["DBUS_SESSION_BUS_ADDRESS"] = p.stdout.readline().decode().strip()
        k = subprocess.run(["gnome-keyring-daemon", "--unlock", "--components=secrets", "--daemonize"],
                           input=b"demo-keyring\n", capture_output=True, env=env, timeout=20)
        for line in k.stdout.decode().splitlines():
            if "=" in line:
                n, v = line.split("=", 1)
                env[n] = v
                if n == "GNOME_KEYRING_PID":
                    self.keyring_pid = int(v)

    def start_servers(self):
        root = self.root
        self.certs = mt.make_certs(root)
        gcerts = os.path.join(root, "google-cert")
        os.makedirs(gcerts)
        g = mt.make_certs(gcerts, hostname="accounts.google.com")
        # stejna CA pro oba certifikaty neni nutna: Posta veri jen self.certs (SSL_CERT_FILE), Firefox jen gcerts
        seed = os.path.join(root, "seed")
        write_messages(seed, self.email, self.name, INBOX)
        ready = os.path.join(root, "imap-ready.json")
        self.spawn([sys.executable, os.path.join(HERE, "demo_imap.py"), TESTS, "--cert", self.certs["cert"],
                    "--key", self.certs["key"], "--ready", ready, "--user", self.email, "--password", "unused-in-demo",
                    "--personality", "gmail", "--oauth", "OAUTHBEARER,XOAUTH2", "--seed", seed], log_name="imap")
        if not mt.wait_for(lambda: os.path.exists(ready), 15):
            raise RuntimeError("demo IMAP server did not start")
        with open(ready) as f:
            self.ports = json.load(f)

        class Imap:
            ports = self.ports

            def control(_s, line):
                with socket.create_connection(("127.0.0.1", self.ports["control"]), timeout=10) as s:
                    s.sendall((line + "\n").encode())
                    data = b""
                    while not data.endswith(b"\n"):
                        chunk = s.recv(65536)
                        if not chunk:
                            break
                        data += chunk
                return json.loads(data)
        self.imap = Imap()
        for box, items in (("Travel", TRAVEL), ("Receipts", RECEIPTS)):
            for path, seen in write_messages(os.path.join(root, "seed-" + box), self.email, self.name, items):
                self.imap.control("deliver %s %s %s" % (box, path, "\\Seen" if seen else ""))
        self.oauth = fo.FakeOAuth(self.imap, self.email, CLIENT_ID, DEMO_SECRET)
        with open(os.path.join(PKG, "apps", "luxos-mail", "files", "oauth-providers.json")) as f:
            data = json.load(f)
        gp = data["providers"]["google"]
        gp.update({"auth_url": AUTH_URL, "token_url": self.oauth.origin + "/token",
                   "revoke_url": self.oauth.origin + "/revoke", "client_id": CLIENT_ID, "client_secret": DEMO_SECRET,
                   "imap": {"host": "localhost", "port": self.ports["tls"], "security": "ssl"}})
        providers = os.path.join(root, "oauth-providers.json")
        with open(providers, "w") as f:
            json.dump(data, f)
        self.proxy = GoogleProxy(g["cert"], g["key"], self.oauth.origin)
        # Firefox: docasny profil, proxy, testovaci CA jen v tomto profilu
        prof = os.path.join(root, "firefox-profile")
        os.makedirs(prof)
        prefs = dict(FIREFOX_PREFS)
        prefs["network.proxy.ssl_port"] = self.proxy.port
        prefs["network.proxy.http_port"] = self.proxy.port
        with open(os.path.join(prof, "user.js"), "w") as f:
            for k, v in prefs.items():
                f.write("user_pref(%s, %s);\n" % (json.dumps(k), json.dumps(v)))
        subprocess.run(["certutil", "-N", "-d", "sql:" + prof, "--empty-password"], check=True, env=self.env, timeout=30)
        subprocess.run(["certutil", "-A", "-d", "sql:" + prof, "-n", "LuxOS demo CA", "-t", "C,,", "-i", g["ca"]],
                       check=True, env=self.env, timeout=30)
        self.profile = prof
        xdg_open = os.path.join(self.bindir, "xdg-open")
        with open(xdg_open, "w") as f:
            f.write("#!/bin/sh\n# ukazkove video: odkaz z Posty otevre Firefox s docasnym profilem\n"
                    "echo \"$1\" >> %s\nexec firefox --no-remote --profile %s --new-window \"$1\"\n"
                    % (os.path.join(root, "opened-urls.txt"), prof))
        os.chmod(xdg_open, 0o755)
        dns = os.path.join(root, "dns.json")
        with open(dns, "w") as f:
            json.dump({}, f)
        self.env.update({
            "SSL_CERT_FILE": self.certs["ca"], "LUXOS_MAIL_INSTANCE": "-gvdemo%d" % os.getpid(),
            "LUXOS_MAIL_NO_SYSTEM_BUS": "1", "LUXOS_MAIL_ACCOUNT_TOOL": "/bin/false",
            "LUXOS_MAIL_OAUTH_PROVIDERS": providers, "LUXOS_MAIL_OAUTH_ADMIN": os.path.join(root, "no-admin.json"),
            "LUXOS_MAIL_OAUTH_REMOTE": "off", "LUXOS_MAIL_FAKE_DNS": dns,
            "LUXOS_MAIL_AUTOCONFIG_URLS": "http://127.0.0.1:9/none?%EMAIL%", "LUXOS_MAIL_ISPDB_URL": "http://127.0.0.1:9/none/%DOMAIN%",
            "LUXOS_I18N_DIR": os.path.join(PKG, "luxos-i18n", "files"),
            "LUXOS_MAIL_UI_TRACE": os.path.join(root, "ui-trace.txt"), "LUXAI_ORIGIN": "http://127.0.0.1:9",
        })

    def start_desktop(self):
        self.ready = os.path.join(self.root, "mail-ready")
        self.env["LUXOS_MAIL_READY_FILE"] = self.ready
        self.env["GTK_THEME"] = "WhiteSur-Light"
        self.spawn(["xfwm4", "--replace"], log_name="xfwm4")
        time.sleep(1.5)
        # tapeta LuxOS: celoobrazovkove okno typu plocha (xfdesktop by cetl systemova nastaveni)
        self.spawn([sys.executable, os.path.join(HERE, "assemble.py"), "--wallpaper-window", WALLPAPER], log_name="wallpaper")
        time.sleep(1.5)
        self.spawn(["xfce4-panel", "--disable-wm-check"], log_name="panel")
        self.spawn(["plank"], log_name="plank")
        time.sleep(6)

    def start_recording(self):
        raw = os.path.join(self.out, "raw")
        os.makedirs(raw, exist_ok=True)
        self.raw = os.path.join(raw, "session.mkv")
        self.ffmpeg = subprocess.Popen(
            ["nice", "-n", "10", "ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-draw_mouse", "1",
             "-framerate", str(FPS), "-video_size", "%dx%d" % (W, H), "-i", self.env["DISPLAY"],
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", "-pix_fmt", "yuv420p", self.raw],
            env=self.env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=open(os.path.join(self.root, "ffmpeg.log"), "ab"),
            start_new_session=True)
        # ffmpeg zacne snimat skoro hned; t0 = start procesu (+ odhad nabehu)
        time.sleep(1.0)
        self.t0 = time.time() - 0.6

    def stop_recording(self):
        if self.ffmpeg and self.ffmpeg.poll() is None:
            try:
                self.ffmpeg.stdin.write(b"q")
                self.ffmpeg.stdin.flush()
            except OSError:
                pass
            try:
                self.ffmpeg.wait(30)
            except subprocess.TimeoutExpired:
                os.killpg(self.ffmpeg.pid, signal.SIGTERM)
                self.ffmpeg.wait(10)

    # -- scenar --
    def trace(self):
        try:
            with open(self.env["LUXOS_MAIL_UI_TRACE"]) as f:
                return f.read()
        except OSError:
            return ""

    def accounts(self):
        p = os.path.join(self.env["XDG_CONFIG_HOME"], "luxos-mail", "accounts.json")
        try:
            with open(p) as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def synced(self):
        base = os.path.join(self.env["XDG_DATA_HOME"], "luxos-mail")
        for root, _d, files in os.walk(base):
            if "index.tsv" in files:
                with open(os.path.join(root, "index.tsv")) as f:
                    if len([x for x in f.read().split("\n") if x]) >= len(INBOX):
                        return True
        return False

    # Polohy na obrazovce 1920x1080: okno Posty 1380x860 s rameckem v (270, 80) (titulek 27 px),
    # Dock dole uprostred (Posta je posledni ikona). Urcene ze snimku (--debug), viz assemble/README.
    DOCK_MAIL = (1238, 1046)
    SIGN_IN = (960, 634)
    ROWS = {"emma": (690, 245), "sofia": (690, 334), "daniel": (690, 423), "mia": (690, 512)}
    FOLDERS = {"inbox": (360, 201), "sent": (360, 259), "trash": (360, 317), "receipts": (360, 346), "travel": (360, 375)}
    ATTACHMENT = (1010, 268)

    def scenario(self, debug):
        # ---- A: plocha, Posta z Docku, pridani uctu ----
        self.mark("segment", name="a", edge="start")
        self.caption("LuxOS desktop", "LuxOS Mail is the mail app of LuxOS (“Mail” in the Dock)")
        time.sleep(3.5)
        if debug:
            self.shot("01-desktop")
        self.caption("Open LuxOS Mail from the Dock")
        self.move(*self.DOCK_MAIL, duration=1.2)
        time.sleep(0.7)
        self.xdo("click", 1)
        if not mt.wait_for(lambda: os.path.exists(self.ready), 12):
            # spoustec Docku nezabral: stejny program primo
            self.spawn([self.mail_bin], log_name="mail")
            if not mt.wait_for(lambda: os.path.exists(self.ready), 20):
                raise RuntimeError("Mail window did not appear")
        win = self.wait_window(classname="luxos-mail")
        time.sleep(0.4)
        self.xdo("windowsize", win, 1380, 860)
        self.xdo("windowmove", win, 270, 80)
        self.xdo("windowactivate", "--sync", win)
        self.win = win
        self.move(960, 560, duration=0.6)
        time.sleep(1.8)
        if debug:
            self.shot("02-welcome")
        self.caption("1. Add account", "Add Account… → type a Gmail address")
        self.click(960, 655, delay=1.6)        # tlacitko "Add Account..." na uvodni obrazovce
        if debug:
            self.shot("03-add-dialog")
        self.type(self.email, delay=0.8)
        if not mt.wait_for(lambda: "auth-mode google oauth" in self.trace(), 10):
            raise RuntimeError("Sign in with Google not offered: " + self.trace())
        time.sleep(0.8)
        self.caption("Before signing in, Mail explains how it uses the access",
                     "Your mail and the sign-in stay on this computer – never sent to LuxOS or anyone else")
        self.move(960, 593, duration=0.8)
        time.sleep(4.5)
        if debug:
            self.shot("04-sign-in-with-google")
        self.caption("Click “Sign in with Google”")
        self.move(*self.SIGN_IN, duration=0.7)
        time.sleep(0.9)
        self.mark("segment", name="a", edge="end")
        # ---- G: prohlizec s adresou autorizace Google (zastupna stranka) ----
        self.mark("segment", name="g", edge="start")
        self.xdo("click", 1)
        ff = self.wait_window(timeout=40, classname="Navigator")
        time.sleep(0.8)
        self.xdo("windowsize", ff, 1640, 940)
        self.xdo("windowmove", ff, 140, 60)
        self.xdo("windowactivate", "--sync", ff)
        self.caption("2. Google sign-in and consent",
                     "The browser opens accounts.google.com with LuxOS Mail’s OAuth client ID")
        time.sleep(3.0)
        self.move(1000, 142, duration=0.8)
        self.caption("client_id=" + CLIENT_ID, "Scopes: https://mail.google.com/  openid  email")
        time.sleep(5.0)
        if debug:
            self.shot("05-browser")
        self.mark("segment", name="g", edge="end")
        # ---- B: po souhlasu ----
        self.mark("segment", name="b", edge="start")
        self.click(694, 821, delay=0.2)        # "Continue with the demo account" -> loopback Posty
        if not mt.wait_for(lambda: len(self.accounts()) == 1, 25):
            raise RuntimeError("account was not added")
        self.caption("Signed in – Google returned a token to LuxOS Mail on this computer",
                     "The token is kept only in the local keyring")
        time.sleep(2.0)
        if debug:
            self.shot("06-signed-in")
        self.xdo("windowminimize", ff)
        self.xdo("windowactivate", "--sync", self.win)
        if not mt.wait_for(self.synced, 30):
            raise RuntimeError("mail did not sync")
        time.sleep(1.0)
        self.caption("3. LuxOS Mail uses https://mail.google.com/ to read mail over IMAP",
                     "Messages go straight from Gmail to this computer (demo mailbox)")
        self.move(700, 600, duration=0.6)
        time.sleep(3.5)
        if debug:
            self.shot("07-inbox")
        self.caption("Read a message")
        self.click(*self.ROWS["emma"], delay=2.6)
        if debug:
            self.shot("08-message")
        self.caption("Attachments are listed and saved only when you choose to",
                     "HTML mail is shown without remote content")
        self.click(*self.ROWS["sofia"], delay=1.0)
        self.move(*self.ATTACHMENT, duration=0.8)
        time.sleep(2.2)
        self.click(*self.ROWS["daniel"], delay=2.2)
        if debug:
            self.shot("09-message2")
        self.caption("Mark as unread / read (stored in Gmail over IMAP)")
        self.key("ctrl+shift+u", delay=1.8)
        self.key("ctrl+shift+u", delay=1.4)
        self.caption("Filter the message list")
        self.key("ctrl+f", delay=0.6)
        self.type("hike", delay=2.2, per_key=140)
        self.key("ctrl+a BackSpace", delay=0.5)
        self.key("Escape", delay=1.0)
        self.caption("Move a message to Trash (Delete)")
        self.click(*self.ROWS["mia"], delay=1.4)
        self.key("Delete", delay=2.0)
        if debug:
            self.shot("10-deleted")
        self.caption("Folders: Gmail labels and system folders", "Trash, Travel, Receipts, Sent …")
        for i, name in enumerate(("trash", "travel", "receipts", "sent")):
            self.click(*self.FOLDERS[name], delay=2.0)
            if name == "travel":
                self.click(*self.ROWS["emma"], delay=2.2)
            if debug:
                self.shot("11-folder-%d" % i)
        self.click(*self.FOLDERS["inbox"], delay=1.6)
        self.remove_account(debug)
        self.mark("segment", name="b", edge="end")

    def remove_account(self, debug):
        self.caption("Remove the account", "Deletes the local copy and the token, and revokes access at Google")
        self.xdo("windowactivate", "--sync", self.win)
        self.move(1365, 128, duration=0.7)     # nabidka "..." (F10)
        self.xdo("click", 1)
        time.sleep(1.4)
        if debug:
            self.shot("12-menu")
        self.key("Down", delay=0.5)
        self.key("Down", delay=0.7)
        self.key("Return", delay=1.0)
        if debug:
            self.shot("13-confirm")
        time.sleep(3.5)
        self.move(1419, 623, duration=0.8)     # tlacitko Remove
        time.sleep(0.5)
        self.xdo("click", 1)
        if not mt.wait_for(lambda: len(self.accounts()) == 0, 15):
            raise RuntimeError("account was not removed")
        time.sleep(0.8)
        self.caption("Account removed – Mail’s access was revoked at Google",
                     "You can also revoke it any time at myaccount.google.com/permissions")
        self.move(960, 760, duration=0.6)
        time.sleep(4.0)
        if debug:
            self.shot("14-removed")

    # -- beh --
    def run(self, debug):
        self.setup()
        self.start_servers()
        self.start_desktop()
        self.start_recording()
        try:
            self.scenario(debug)
            time.sleep(1.0)
        finally:
            self.stop_recording()
            self.revoked = list(self.oauth.revoked)
            self.blocked = list(self.proxy.blocked)
            self.stop_all()
            self.oauth.stop()
            self.proxy.stop()
        with open(os.path.join(self.out, "parts-markers.json"), "w") as f:
            json.dump({"markers": self.markers, "email": self.email, "client_id": CLIENT_ID,
                       "revoked_at_fake_google": len(self.revoked), "proxy_blocked": self.blocked}, f, indent=2)


def build_mail(out):
    """Prelozi Postu ze zdroju (jako build() v PKGBUILD) do OUT/build."""
    b = os.path.join(out, "build")
    src = os.path.join(b, "lsl")
    shutil.rmtree(src, ignore_errors=True)
    os.makedirs(src)
    for d in (os.path.join(PKG, "apps", "luxos-mail", "files"),):
        for f in os.listdir(d):
            if f.endswith(".lsl"):
                shutil.copy(os.path.join(d, f), src)
    for m in ("luxos_gtk", "luxos_glib", "luxos_gio", "luxos_i18n", "luxos_sys", "luxos_text"):
        shutil.copy(os.path.join(PKG, "luxos-desktop", "files", "lsl", m + ".lsl"), src)
    for main, name in (("luxos-mail.lsl", "luxos-mail"), ("luxos-mail-service.lsl", "luxos-mail-service")):
        subprocess.run(["lslc", "--target", "linux-x86_64-gnu", main, os.path.join(b, name)], cwd=src, check=True, timeout=1200)
    return os.path.join(b, "luxos-mail")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.environ.get("LUXOS_GV_OUT", os.path.join(os.path.expanduser("~"), "LuxOS-Arch", "out", "google-verification")))
    ap.add_argument("--email", default="alex.morgan.luxos.demo@gmail.com", help="demo Gmail address (never contacted)")
    ap.add_argument("--name", default="Alex Morgan")
    ap.add_argument("--mail-bin", default=os.environ.get("LUXOS_MAIL_BIN", ""))
    ap.add_argument("--debug", action="store_true", help="screenshots of each step into the run directory")
    ap.add_argument("--keep", action="store_true", help="keep the run directory")
    a = ap.parse_args()
    guard_display()
    out = os.path.abspath(a.out)
    mail_bin = a.mail_bin or build_mail(out)
    d = Demo(out, mail_bin, a.email, a.name)
    ok = False
    try:
        d.run(a.debug)
        ok = True
    finally:
        log("run directory: " + d.root)
        if ok and not a.keep and not a.debug:
            shutil.rmtree(d.root, ignore_errors=True)
    parts = assemble.cut_parts(d.raw, os.path.join(out, "parts-markers.json"), os.path.join(out, "parts"))
    preview = assemble.assemble(os.path.join(out, "parts"), None, os.path.join(out, "luxos-mail-demo-preview.mp4"))
    log("parts: %s" % ", ".join(parts))
    log("preview: %s" % preview)


if __name__ == "__main__":
    main()
