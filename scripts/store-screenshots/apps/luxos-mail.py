"""Posta: pridani uctu s automaticky nalezenym serverem a schranka s ukazkovymi zpravami.

Vse mistni jako v testech (packages/apps/luxos-mail/tests): testovaci server IMAP s TLS (fake_imap.py,
certifikat vlastni testovaci CA jen pres SSL_CERT_FILE), autoconfig z mistniho HTTP, falesne DNS,
falesny secret-tool misto klicenky, vlastni instance soketu sluzby (LUXOS_MAIL_INSTANCE) a bez
systemove sbernice. Zpravy jsou vymyslene (pratelsti odesilatele s adresami example.*).
"""
import email.utils
import http.server
import json
import os
import subprocess
import sys
import time
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _a  # noqa: E402

USER = "alex.morgan@example.com"
PASSWORD = "demo-mail-password"

# (soubor, od, predmet, pred kolika hodinami, prectena, text, priloha)
MESSAGES = [
    ("Book Club", "bookclub@example.org", "November pick: The Left Hand of Darkness", 70, True,
     "Hi everyone,\n\nthe votes are in and our November book is The Left Hand of Darkness by Ursula K. Le Guin."
     "\n\nWe meet on the last Thursday of the month at 7 pm in the library cafe.\n\nHappy reading!\nThe Book Club",
     None),
    ("City Library", "library@example.net", "Your reservation is ready for pickup", 52, True,
     "Hello Alex,\n\nthe book you reserved is ready for pickup at the front desk:\n\n"
     "  The Pragmatic Programmer, 20th Anniversary Edition\n\nWe will keep it for you until Saturday.\n\n"
     "City Library", None),
    ("Mia Chen", "mia.chen@example.com", "The soup recipe you asked for", 30, True,
     "Hi Alex,\n\nhere it is - my grandmother's pumpkin soup. Roast the pumpkin with garlic first, "
     "that is the whole secret.\n\nEnjoy!\nMia", None),
    ("Daniel Park", "daniel.park@example.com", "Lunch on Friday?", 20, False,
     "Hey Alex,\n\nare you free for lunch on Friday? The new noodle place near the station opened this week "
     "and I have heard great things about it.\n\nNoon works for me.\n\nDaniel", None),
    ("Sofia Rossi", "sofia.rossi@example.org", "Re: Project timeline", 6, False,
     "Hi Alex,\n\nthanks for the update. The new timeline looks good to me. I moved the design review to "
     "Tuesday so we have a full week for testing before the release.\n\nI attached the updated plan.\n\n"
     "Best,\nSofia", ("project-plan.pdf", "application/pdf")),
    ("Emma Wilson", "emma.wilson@example.org", "Photos from the weekend hike", 1, False,
     "Hi Alex,\n\nwhat a great weekend! The view from the ridge was worth every step, even with the wind "
     "at the top.\n\nI put my favourite photos and the trail map in the attachment. Same trail in spring, "
     "this time with the waterfall loop?\n\nSee you soon,\nEmma", ("trail-map.pdf", "application/pdf")),
]

# prazdne PDF, doplnene komentarem na realistickou velikost prilohy
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
       b"trailer<</Root 1 0 R>>\n" + b"%" + b"0" * 63 + b"\n") * 1 + (b"%" + b"0" * 63 + b"\n") * 2900 + b"%%EOF\n"


def write_messages(folder):
    os.makedirs(folder, exist_ok=True)
    now = time.time()
    for i, (name, addr, subject, hours, seen, text, attach) in enumerate(MESSAGES):
        m = EmailMessage()
        m["From"] = email.utils.formataddr((name, addr))
        m["To"] = email.utils.formataddr(("Alex Morgan", USER))
        m["Subject"] = subject
        m["Date"] = email.utils.formatdate(now - hours * 3600, localtime=True)
        m["Message-ID"] = email.utils.make_msgid(domain="example.com")
        m.set_content(text)
        if attach:
            m.add_attachment(PDF, maintype="application", subtype="pdf", filename=attach[0])
        fname = "%02d-%s.eml" % (i, "seen" if seen else "new")
        with open(os.path.join(folder, fname), "wb") as f:
            f.write(bytes(m))


def autoconfig_handler(port_tls):
    body = ("<?xml version=\"1.0\"?><clientConfig version=\"1.1\"><emailProvider id=\"example.com\">"
            "<incomingServer type=\"imap\"><hostname>localhost</hostname><port>%d</port><socketType>SSL</socketType>"
            "<username>%%EMAILADDRESS%%</username><authentication>password-cleartext</authentication></incomingServer>"
            "<outgoingServer type=\"smtp\"><hostname>localhost</hostname><port>587</port><socketType>STARTTLS</socketType>"
            "<username>%%EMAILADDRESS%%</username></outgoingServer></emailProvider></clientConfig>" % port_tls).encode()

    class Autoconfig(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.startswith("/mail/config-v1.1.xml"):
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def log_message(self, *_a):
            pass
    return Autoconfig


def wait_for(s, cond, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        s.sleep(0.2)
    return cond()


def shots(s):
    tests = s.src("apps/luxos-mail/tests")
    sys.path.insert(0, tests)
    try:
        import mailtest as mt
    finally:
        sys.path.pop(0)
    # program a sluzba vedle sebe (sluzbu okno hleda ve stejne slozce)
    gui = s.lslc("apps/luxos-mail/files/luxos-mail.lsl", ["luxos-desktop/files/lsl"])
    s.lslc("apps/luxos-mail/files/luxos-mail-service.lsl", ["luxos-desktop/files/lsl"])
    certs = mt.make_certs(s.tmp)
    seed = os.path.join(s.tmp, "seed")
    write_messages(seed)
    ready = os.path.join(s.tmp, "imap-ready.json")
    s.launch([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_a_fake_imap.py"), tests,
              "--cert", certs["cert"], "--key", certs["key"],
              "--ready", ready, "--user", USER, "--password", PASSWORD, "--seed", seed])
    if not wait_for(s, lambda: os.path.exists(ready), 15):
        raise RuntimeError("fake IMAP server did not start")
    ports = json.load(open(ready))
    port = s.serve_http(autoconfig_handler(ports["tls"]))
    dns = s.write(".cache/fake-dns.json", "{}")
    secret = _a.fake_tool(s, "secret-tool", (
        'case "$1" in\n'
        '  store) cat >/dev/null; exit 0 ;;\n'
        '  lookup) printf %%s "%s"; exit 0 ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n') % PASSWORD)
    share = os.path.join(s.tmp, "share")
    for size in (16, 24, 32, 48, 64, 128, 256):
        d = os.path.join(share, "icons", "hicolor", "%dx%d" % (size, size), "apps")
        os.makedirs(d, exist_ok=True)
        subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size),
                        s.src("apps/luxos-mail/files/luxos-mail.svg"), "-o", os.path.join(d, "luxos-mail.png")],
                       check=True, timeout=30)
    s.env.update({
        "SSL_CERT_FILE": certs["ca"],
        "LUXOS_MAIL_INSTANCE": "-storeshots%d" % os.getpid(),
        "LUXOS_MAIL_NO_SYSTEM_BUS": "1",
        "LUXOS_MAIL_SECRET_TOOL": secret,
        "LUXOS_MAIL_ACCOUNT_TOOL": "/bin/false",
        "LUXOS_MAIL_AUTOCONFIG_URLS": "http://127.0.0.1:%d/mail/config-v1.1.xml?emailaddress=%%EMAIL%%" % port,
        "LUXOS_MAIL_ISPDB_URL": "http://127.0.0.1:%d/none/%%DOMAIN%%" % port,
        "LUXOS_MAIL_FAKE_DNS": dns,
        "LUXOS_MAIL_NOTIFY_LOG": os.path.join(s.tmp, "notify.jsonl"),
        "LUXAI_ORIGIN": "http://127.0.0.1:9",
        "GTK_USE_PORTAL": "0", "GIO_USE_VFS": "local",
        "XDG_DATA_DIRS": share + ":/usr/local/share:/usr/share",
    })
    p = s.launch([gui])
    win = s.window(pid=p.pid, size=(1100, 680))
    s.sleep(1.0)
    # Pridat ucet...: fokus ma tlacitko uvitani
    s.key("Return", win, delay=1.0)
    s.type(USER)
    s.key("Tab")
    s.type(PASSWORD)
    s.key("Return", delay=3.0)
    # dialog nad uvodni obrazovkou okna (snimek okna ho zachyti uprostred)
    s.capture("3", win)
    s.key("Return", delay=1.0)
    base = os.path.join(s.home, ".local", "share", "luxos-mail")

    def synced():
        for root, _dirs, files in os.walk(base):
            if "index.tsv" in files:
                with open(os.path.join(root, "index.tsv")) as f:
                    if len([x for x in f.read().split("\n") if x]) >= len(MESSAGES):
                        return True
        return False
    if not wait_for(s, synced, 30):
        raise RuntimeError("account was not added")
    s.sleep(2.0)
    s.activate(win)
    s.key("ctrl+f Down", win, delay=1.5)
    s.capture("1", win)
    # zprava s prilohou (radek Sofia Rossi v seznamu)
    s.click(420, 255, win, delay=1.5)
    s.capture("2", win)
