"""Testy Spravy site (luxos-router, files/lsl/luxos-router.lsl): brana, nmcli, pravidla jen pro domaci sit,
zarizeni (ip neigh, OUI), nastroje a okno ve vlastnim Xvfb s mistnim "routerem" (HTTP a HTTPS s vlastnim
certifikatem, prihlaseni HTTP Basic, stazeni zalohy).

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_netadmin.py -v

Rozbor a pravidla: tests/lsl/luxos-netadmin-test.lsl (luxos_netadmin.lsl). Falesne ip/nmcli/ping z fake-net,
curl a getent jako skripty, router = server na 127.0.0.1 (brana v testu). Zadna skutecna sit, prohlizec se
nespousti (otevrene adresy jen hlasi stav okna). LUXOS_TEST_SHOTS=adresar ulozi snimky oken, LANG prepise
jazyk okna (vychozi anglictina).
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import base64
import http.server
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, ".."))
FAKE = os.path.join(HERE, "fake-net")
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

TMP = tempfile.mkdtemp(prefix="luxos-router-test-")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")

DEVICE = """GENERAL.DEVICE:wlp4s0
GENERAL.TYPE:wifi
GENERAL.HWADDR:9C:2F:9D:76:21:DB
GENERAL.STATE:100 (connected)
GENERAL.CONNECTION:Domov 5G
IP4.ADDRESS[1]:192.168.1.23/24
IP4.GATEWAY:192.168.1.1
IP4.ROUTE[1]:dst = 0.0.0.0/0, nh = 192.168.1.1, mt = 600
IP4.DNS[1]:192.168.1.1
IP4.DNS[2]:1.1.1.1
IP6.ADDRESS[1]:fe80::687b:1a76:a3e:2bc9/64
IP6.GATEWAY:--
IP6.DNS[1]:fd00\\:\\:1
"""
NO_NET = {"routes": [], "device": "", "wifi": "", "neigh": [], "ping": {}}
OUI = ("OUI/MA-L\t\t\tOrganization\n00-1A-2B   (hex)\t\tAyecom Technology Co., Ltd.\n"
       "001A2B     (base 16)\t\tAyecom\n\n9C-2F-9D   (hex)\t\tLiteon Technology Corporation\n")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def script(name, text):
    path = os.path.join(TMP, name)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, 0o755)
    return path


# curl: verejna adresa a mereni rychlosti bez internetu (FAKE_CURL = "ok" | "fail"), volani do FAKE_CURL_LOG
CURL = script("curl", """#!/bin/sh
echo "$*" >>"$FAKE_CURL_LOG"
[ "$FAKE_CURL" = fail ] && exit 7
case "$*" in
*size_download*) printf '10000000 2.000000' ;;
*ipify*) printf 'not an address' ;;
*icanhazip*) printf '203.0.113.7\\n' ;;
esac
""")
# getent ahosts: jen pro anglicky systemovy resolver; example.com odpovi, ostatni ne
GETENT = script("getent", """#!/bin/sh
case "$2" in
example.com) printf '93.184.216.34   STREAM example.com\\n93.184.216.34   DGRAM\\n' ;;
router.lan) printf '127.0.0.1       STREAM router.lan\\n' ;;
*) exit 2 ;;
esac
""")


@unittest.skipUnless(LSLC, "lslc (lsl) is not installed")
class Units(unittest.TestCase):
    def test_netadmin_units(self):
        out = os.path.join(TMP, "netadmin-test")
        r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", lsl_app.LSL_DIR,
                            os.path.join(HERE, "lsl", "luxos-netadmin-test.lsl"), out], capture_output=True, text=True,
                           timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run([out], capture_output=True, text=True, timeout=60)
        fails = [line for line in r.stdout.splitlines() if not line.startswith("ok ")]
        self.assertEqual((r.returncode, fails), (0, []), r.stderr)
        self.assertGreater(len(r.stdout.splitlines()), 90)
        print(f"\n  {len(r.stdout.splitlines())} pripadu rozboru a pravidel")


# ---- mistni "router" ------------------------------------------------------------------------------------------
PAGE = """<html><head><title>Router</title></head><body style="font-family:sans-serif">
<h1 id="h">Test router admin</h1>
<a id="lan" href="/status">Status</a> <a id="out" href="http://93.184.216.34/">Internet</a>
<a id="named" href="http://router.lan:%d/status">Named</a> <a id="backup" href="/backup.cfg">Backup</a>
<form><input name="user"><input type="password" name="pw"></form></body></html>"""
AUTH_SEEN = []


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ctype = "text/html; charset=utf-8"
        if self.path == "/away":
            # presmerovani bez kliknuti uzivatele (napr. cloudovy portal vyrobce)
            body = '<html><head><meta http-equiv="refresh" content="0;url=http://8.8.8.8/"></head></html>'.encode()
        elif self.path == "/auth":
            got = self.headers.get("Authorization", "")
            if not got:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="router"')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            AUTH_SEEN.append(base64.b64decode(got.split()[1]).decode())
            body = b"<html><head><title>Signed in</title></head><body>ok</body></html>"
        elif self.path == "/backup.cfg":
            ctype = "application/octet-stream"
            body = b"router-config-v1\n"
        else:
            body = (PAGE % self.server.server_address[1] if self.path == "/"
                    else "<html><body><h1>Status OK</h1></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if ctype.startswith("application/"):
            self.send_header("Content-Disposition", 'attachment; filename="backup.cfg"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def start_server(tls_dir=None):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if tls_dir:
        key, crt = os.path.join(tls_dir, "k.pem"), os.path.join(tls_dir, "c.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt,
                        "-days", "1", "-subj", "/CN=router.local"], capture_output=True, check=True)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(crt, key)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def webkit_ok():
    return any(os.path.exists(os.path.join(d, "libwebkit2gtk-4.1.so.0")) for d in ("/usr/lib", "/usr/lib64"))


@unittest.skipUnless(LSLC, "lslc (lsl) is not installed")
class App(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = lsl_app.build("luxos-router", TMP)
        cls.x = lsl_app.Xvfb("1366x768")
        cls.http = start_server()
        cls.https = start_server(tls_dir=TMP)
        cls.net = os.path.join(TMP, "net.json")
        cls.oui = os.path.join(TMP, "oui.txt")
        with open(cls.oui, "w") as f:
            f.write(OUI)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.https.shutdown()
        cls.x.stop()

    def online(self):
        return {"routes": [{"dst": "default", "gateway": "127.0.0.1", "dev": "wlp4s0", "metric": 600}],
                "device": DEVICE.replace("192.168.1.23/24", "127.0.0.5/24"), "wifi": "yes:Domov 5G\n",
                "neigh": [{"dst": "127.0.0.1", "dev": "wlp4s0", "lladdr": "00:1a:2b:3c:4d:5e", "state": ["REACHABLE"]},
                          {"dst": "127.0.0.20", "dev": "wlp4s0", "lladdr": "d2:99:b5:44:9a:c1", "state": ["STALE"]}],
                "ping": {"127.0.0.1": 1.2, "1.1.1.1": 14.0}}

    def start(self, net=None, **extra):
        with open(self.net, "w") as f:
            json.dump(self.online() if net is None else net, f)
        self.home = tempfile.mkdtemp(prefix="home-", dir=TMP)
        env = dict(os.environ, DISPLAY=self.x.display, HOME=self.home, XDG_CONFIG_HOME=os.path.join(self.home, ".config"),
                   XDG_DATA_HOME=os.path.join(self.home, ".local/share"), XDG_CACHE_HOME=os.path.join(self.home, ".cache"),
                   FAKE_NET=self.net, LUXOS_IP=os.path.join(FAKE, "ip"), LUXOS_NMCLI=os.path.join(FAKE, "nmcli"),
                   LUXOS_PING=os.path.join(FAKE, "ping"), LUXOS_CURL=CURL, LUXOS_GETENT=GETENT,
                   FAKE_CURL_LOG=os.path.join(TMP, "curl.log"), FAKE_PING_LOG=os.path.join(TMP, "ping.log"),
                   LUXOS_ROUTER_PORT=str(self.http.server_address[1]), LUXOS_OUI_FILE=self.oui,
                   GTK_THEME=os.environ.get("GTK_THEME", "Adwaita"), LANG=os.environ.get("LANG_UI", "en_US.UTF-8"),
                   LC_ALL=os.environ.get("LANG_UI", "en_US.UTF-8"))
        env.pop("WAYLAND_DISPLAY", None)
        env.update(extra)
        luxos_testguard.check_env(env)
        self.app = lsl_app.App([self.binary], env)
        self.addCleanup(self.app.stop)
        self.assertTrue(self.app.wait(lambda: self.app.dump()), self.app.stderr())

    def st(self):
        return json.loads(self.app.ask("state", "state"))

    def wait(self, cond, timeout=10):
        return self.app.wait(cond, timeout)

    def shot(self, name):
        out = os.environ.get("LUXOS_TEST_SHOTS")
        if out:
            os.makedirs(out, exist_ok=True)
            time.sleep(0.6)
            lsl_app.shot(self.x.display, os.path.join(out, name + ".png"))

    # ---- prehled ----
    def test_overview(self):
        self.start()
        d = self.app.dump()
        self.assertEqual([(w["title"], w["close_button"]) for w in d], [("Router", True)])
        texts = lsl_app.texts(d)
        for want in ("Domov 5G", "127.0.0.1", "127.0.0.5/24", "192.168.1.1, 1.1.1.1, fd00::1", "wlp4s0",
                     "9C:2F:9D:76:21:DB", "Domov 5G · Wi-Fi", "Router: 127.0.0.1"):
            self.assertIn(want, texts)
        # prepinac karet v horni liste
        for title in ("Overview", "Devices"):
            self.assertIn(title, texts)
        # WebKit se v prehledu nenacita
        self.assertFalse(self.st()["view"])
        with open("/proc/%d/maps" % self.app.proc.pid) as f:
            self.assertNotIn("libwebkit2gtk", f.read())
        self.shot("router-overview")

    def test_localized_tools_run_in_c_locale(self):
        # cesky nmcli by misto "yes:SSID" psal "ano:SSID", cesky ping "1 paketu odeslano, 1 prijato"
        nmcli = script("nmcli-cs", '#!/bin/sh\nif [ "$LC_ALL" != C ]; then echo "ano:Cesky"; exit 0; fi\n'
                       'exec "%s" "$@"\n' % os.path.join(FAKE, "nmcli"))
        ping = script("ping-cs", '#!/bin/sh\nif [ "$LC_ALL" = C ]; then\n'
                      'echo "4 packets transmitted, 4 received, 0% packet loss, time 0ms"\n'
                      'echo "rtt min/avg/max/mdev = 0.2/0.3/0.4/0.0 ms"\nelse\n'
                      'echo "4 paketu odeslano, 4 prijato, 0% packet loss, time 0ms"\nfi\n')
        self.start(LUXOS_NMCLI=nmcli, LUXOS_PING=ping, LANG="cs_CZ.UTF-8", LC_ALL="cs_CZ.UTF-8")
        self.assertIn("Domov 5G", lsl_app.texts(self.app.dump()))
        self.app.ask("tool 1")
        self.assertTrue(self.wait(lambda: self.st()["tools"][1] != ""))
        self.assertEqual(self.st()["tools"][1], "0,3 ms")

    def test_offline_tools_disabled(self):
        self.start(NO_NET)
        s = self.st()
        # bez brany: Zobrazit, Vyzkouset (internet), Vyzkouset (DNS), Zmerit neaktivni s vysvetlenim
        self.assertEqual(s["tool_sensitive"], [False, False, False, False])
        self.assertEqual(s["tools"], ["Not connected to a network"] * 4)
        texts = lsl_app.texts(self.app.dump())
        self.assertIn("Not connected", texts)
        self.assertIn("No router (default gateway) found.", texts)
        self.assertIsNone(lsl_app.find(self.app.dump(), text="Open Router Settings"))
        self.shot("router-offline")

    def test_online_tools_enabled(self):
        net = {"routes": [{"dst": "default", "gateway": "192.168.1.1", "dev": "wlp4s0", "metric": 600}],
               "device": "GENERAL.DEVICE: wlp4s0\nGENERAL.TYPE: wifi\nGENERAL.STATE: 100 (connected)\n"
                         "GENERAL.CONNECTION: Domov\nIP4.ADDRESS[1]: 192.168.1.23/24\n",
               "wifi": "yes:Domov\n", "neigh": [], "ping": {}}
        self.start(net)
        self.assertEqual(self.st()["tool_sensitive"], [True] * 5)

    def test_window_fits_screen(self):
        # cele okno se vejde na 1366x768 (i s HeaderBar) a jde zmensit nejvys na 600x420
        self.start()
        s = self.st()
        self.assertLessEqual(s["size"][1] + 45, 768 - 16, s)
        self.assertLessEqual(s["size"][0], 1366)
        self.assertEqual(s["min"], [600, 420])

    # ---- nastroje ----
    def test_ping_tools(self):
        self.start()
        self.app.ask("tool 1")
        self.app.ask("tool 2")
        self.assertTrue(self.wait(lambda: all(self.st()["tools"][1:3])))
        self.assertEqual(self.st()["tools"][1:3], ["1.2 ms", "14.0 ms"])

    def test_ping_no_reply_and_lost(self):
        net = self.online()
        net["ping"] = {"127.0.0.1": 3.0}
        self.start(net, LANG="cs_CZ.UTF-8", LC_ALL="cs_CZ.UTF-8")
        self.app.ask("tool 1")
        self.app.ask("tool 2")
        self.assertTrue(self.wait(lambda: all(self.st()["tools"][1:3])))
        # desetinna carka v cestine, internet neodpovida
        self.assertEqual(self.st()["tools"][1:3], ["3,0 ms", "Bez odpovědi"])

    def test_dns_public_ip_and_speed(self):
        log = os.path.join(TMP, "curl.log")
        if os.path.exists(log):
            os.unlink(log)
        self.start()
        for i in (0, 3, 4):
            self.app.ask("tool %d" % i)
        self.assertTrue(self.wait(lambda: all(self.st()["tools"][i] for i in (0, 3, 4))))
        s = self.st()
        # prvni sluzba vrati nesmysl -> druha; 10 MB za 2 s = 40 Mbit/s
        self.assertEqual(s["tools"][0], "203.0.113.7")
        self.assertTrue(s["tools"][3].startswith("Works ("), s["tools"][3])
        self.assertEqual(s["tools"][4], "40.0 Mbit/s")
        with open(log) as f:
            calls = f.read()
        self.assertIn("https://api.ipify.org", calls)
        self.assertIn("https://speed.cloudflare.com/__down?bytes=10000000", calls)
        self.assertIn("-A LuxOS", calls)

    def test_tools_fail_cleanly(self):
        self.start(LUXOS_GETENT="false", FAKE_CURL="fail")
        for i in (0, 3, 4):
            self.app.ask("tool %d" % i)
        self.assertTrue(self.wait(lambda: all(self.st()["tools"][i] for i in (0, 3, 4))))
        self.assertEqual([self.st()["tools"][i] for i in (0, 3, 4)],
                         ["Not available", "Name lookup failed", "Measurement failed"])
        self.assertTrue(all(self.st()["tool_sensitive"]))

    # ---- zarizeni ----
    def test_devices(self):
        self.start()
        self.app.ask("page devices")
        self.assertTrue(self.wait(lambda: len(self.st()["devices"]) == 3))
        rows = self.st()["devices"]
        self.assertEqual(rows[0], ["127.0.0.1", "Router – Ayecom Technology Co., Ltd.", "00:1a:2b:3c:4d:5e", "Active"])
        self.assertEqual(rows[1], ["127.0.0.20", "Private address (random MAC)", "d2:99:b5:44:9a:c1", "Seen recently"])
        self.assertEqual(rows[2], ["127.0.0.5", "This computer – Liteon Technology Corporation", "9c:2f:9d:76:21:db",
                                   "This computer"])
        self.assertTrue(self.wait(lambda: lsl_app.find(self.app.dump(), name="dev-status")["text"] == "3 devices"))
        self.shot("router-devices")

    def test_devices_without_oui_file(self):
        self.start(LUXOS_OUI_FILE=os.path.join(TMP, "missing"))
        self.app.ask("page devices")
        self.assertTrue(self.wait(lambda: len(self.st()["devices"]) == 3))
        self.assertEqual([r[1] for r in self.st()["devices"]], ["Router", "Private address (random MAC)", "This computer"])

    def test_scan(self):
        log = os.path.join(TMP, "ping.log")
        if os.path.exists(log):
            os.unlink(log)
        self.start()
        self.app.ask("page devices")
        self.app.ask("click Search Network")
        self.assertFalse(self.st()["scan_sensitive"])
        self.assertTrue(self.wait(lambda: self.st()["scan_sensitive"], 90))
        with open(log) as f:
            hosts = f.read().split()
        self.assertEqual(len(hosts), 253)
        self.assertEqual(len(set(hosts)), 253)
        self.assertNotIn("127.0.0.5", hosts)
        self.assertTrue(self.wait(lambda: len(self.st()["devices"]) == 3))

    # ---- webova sprava ----
    def test_no_webkit(self):
        self.start(LUXOS_WEBKIT_LIB="none")
        self.app.ask("page router")
        d = self.app.dump()
        self.assertIn("The built-in web view (WebKitGTK) is not available. The router settings will open in your "
                      "web browser.", lsl_app.texts(d))
        self.app.ask("click Open in Browser")
        self.assertEqual(self.st()["opened"], ["http://127.0.0.1:%d/" % self.http.server_address[1]])

    def router_page(self):
        self.app.ask("page router")
        s = self.st()
        self.assertTrue(s["view"])
        self.assertTrue(s["ephemeral"])
        self.assertTrue(self.wait(lambda: self.st()["title"] == "Router" and not self.st()["loading"], 30),
                        self.st())

    @unittest.skipUnless(webkit_ok(), "WebKit2 4.1 neni k dispozici")
    def test_router_page_lan_only(self):
        self.start()
        self.router_page()
        port = self.http.server_address[1]
        self.assertTrue(self.st()["uri"].startswith("http://127.0.0.1:%d/" % port))
        self.assertEqual(lsl_app.find(self.app.dump(), name="address")["text"], self.st()["uri"])
        self.shot("router-webview")
        # odkaz do internetu (klik uzivatele) -> bezny prohlizec, stranka zustane
        self.app.ask("js document.getElementById('out').click()")
        self.assertTrue(self.wait(lambda: self.st()["opened"]))
        self.assertEqual(self.st()["opened"], ["http://93.184.216.34/"])
        self.assertTrue(self.st()["uri"].startswith("http://127.0.0.1:"))
        self.assertTrue(self.st()["info"])
        # odkaz v domaci siti -> v aplikaci
        self.app.ask("js document.getElementById('lan').click()")
        self.assertTrue(self.wait(lambda: self.st()["uri"].endswith("/status") and not self.st()["loading"]))
        # presmerovani skriptem (bez kliknuti) jinam -> jen oznameni, nic se neotevre
        self.app.ask("load http://127.0.0.1:%d/away" % port)
        self.assertTrue(self.wait(lambda: "8.8.8.8" in self.st().get("info_text", "") and self.st()["info"]))
        self.assertEqual(self.st()["opened"], ["http://93.184.216.34/"])
        self.assertEqual(self.st()["info_uri"], "http://8.8.8.8/")
        self.shot("router-webview-outside")
        # jmeno prekladane jen do domaci site (router.lan -> 127.0.0.1) se otevre v aplikaci
        self.app.ask("load http://127.0.0.1:%d/" % port)
        self.assertTrue(self.wait(lambda: self.st()["title"] == "Router" and not self.st()["loading"]))
        self.app.ask("js document.getElementById('named').click()")
        self.assertTrue(self.wait(lambda: self.st()["uri"] == "http://router.lan:%d/status" % port, 15), self.st())
        # file: a javascript: se neotevrou vubec
        self.app.ask("load file:///etc/hostname")
        time.sleep(1)
        self.assertTrue(self.st()["uri"].startswith("http://router.lan:"))
        self.assertEqual(len(self.st()["opened"]), 1)

    @unittest.skipUnless(webkit_ok(), "WebKit2 4.1 neni k dispozici")
    def test_self_signed_needs_confirmation(self):
        self.start()
        self.router_page()
        url = "https://127.0.0.1:%d/" % self.https.server_address[1]
        # 1) Zrusit: zadna vyjimka, zpet na HTTP
        self.app.send("load " + url)
        self.assertTrue(self.wait(lambda: any(w["dialog"] for w in self.app.dump()), 20))
        d = self.app.dump()
        self.assertIn("The router uses its own security certificate", lsl_app.texts(d, dialog=True))
        self.app.send("respond -6")
        self.assertTrue(self.wait(lambda: not self.st()["tls_dialog"]))
        self.assertEqual(self.st()["tls_allowed"], [])
        self.assertTrue(self.wait(lambda: self.st()["uri"].startswith("http://") and not self.st()["loading"], 20))
        # 2) Pokracovat: vyjimka jen pro adresu brany, stranka se nacte
        self.app.send("load " + url)
        self.assertTrue(self.wait(lambda: any(w["dialog"] for w in self.app.dump()), 20))
        self.shot("router-certificate")
        self.app.send("respond -5")
        self.assertTrue(self.wait(lambda: self.st()["uri"] == url and self.st()["title"] == "Router"
                                  and not self.st()["loading"], 25), self.st())
        self.assertEqual(self.st()["tls_allowed"], ["127.0.0.1"])
        self.assertEqual(self.st()["proto"], "https")

    @unittest.skipUnless(webkit_ok(), "WebKit2 4.1 neni k dispozici")
    def test_self_signed_other_host_refused(self):
        # Brana je 127.0.0.1; certifikat jineho zarizeni (10.x / jmeno) nejde povolit
        self.start()
        self.router_page()
        self.app.ask("tls https://10.0.0.7/")
        s = self.st()
        self.assertTrue(s["info"])
        self.assertIn("10.0.0.7", s["info_text"])
        self.assertFalse(s["tls_dialog"])
        self.assertFalse(any(w["dialog"] for w in self.app.dump()))

    @unittest.skipUnless(webkit_ok(), "WebKit2 4.1 neni k dispozici")
    def test_basic_auth_dialog(self):
        AUTH_SEEN.clear()
        self.start()
        self.router_page()
        self.app.send("load http://127.0.0.1:%d/auth" % self.http.server_address[1])
        self.assertTrue(self.wait(lambda: any(w["dialog"] for w in self.app.dump()), 20))
        d = self.app.dump()
        self.assertEqual([w["title"] for w in d if w["dialog"]], ["Sign In"])
        self.assertIn("127.0.0.1 asks for a user name and password. They are not saved.", lsl_app.texts(d, dialog=True))
        self.shot("router-sign-in")
        self.app.send("entry admin")
        self.app.send("respond -5")
        # prvni pole = jmeno; heslo zustane prazdne
        self.assertTrue(self.wait(lambda: self.st()["title"] == "Signed in", 20), self.st())
        self.assertEqual(AUTH_SEEN, ["admin:"])

    @unittest.skipUnless(webkit_ok(), "WebKit2 4.1 neni k dispozici")
    def test_backup_download(self):
        self.start()
        self.router_page()
        os.makedirs(os.path.join(self.home, "Downloads"))
        with open(os.path.join(self.home, "Downloads", "backup.cfg"), "w") as f:
            f.write("old")
        self.app.ask("js document.getElementById('backup').click()")
        saved = os.path.join(self.home, "Downloads", "backup (1).cfg")
        self.assertTrue(self.wait(lambda: os.path.exists(saved) and self.st()["info"], 20), self.st())
        with open(saved) as f:
            self.assertEqual(f.read(), "router-config-v1\n")
        self.assertEqual(self.st()["info_text"], "Saved to Downloads: backup (1).cfg")

    @unittest.skipUnless(webkit_ok(), "WebKit2 4.1 neni k dispozici")
    def test_resident_memory(self):
        self.start()
        time.sleep(1.5)
        overview = self.app.pss_kb()
        self.router_page()
        time.sleep(1.5)
        router = self.app.pss_kb()
        print(f"\n  PSS luxos-router: prehled {overview // 1024} MB, s kartou Router {router // 1024} MB")
        self.assertLess(overview, 60 * 1024)


if __name__ == "__main__":
    unittest.main()
