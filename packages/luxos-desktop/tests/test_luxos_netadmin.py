"""Testy Spravy site (luxos-router): brana, nmcli, pravidla jen pro domaci sit, zarizeni (ip neigh,
OUI), ping a aplikace pod Xvfb s mistnim "routerem" (HTTP a HTTPS s vlastnim certifikatem).

Spusteni: env -u DISPLAY xvfb-run -a python3 -m unittest discover -s packages/luxos-desktop/tests
Falesne ip/nmcli/ping z fake-net, router = server na 127.0.0.1 (brana v testu). Zadna sit navic.
LUXOS_TEST_SHOTS=adresar ulozi snimky oken.
"""
import http.server
import importlib.machinery
import importlib.util
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
PYDIR = os.path.normpath(os.path.join(HERE, "..", "files", "python"))
BIN = os.path.normpath(os.path.join(HERE, "..", "files", "bin"))
FAKE = os.path.join(HERE, "fake-net")
sys.path.insert(0, PYDIR)
sys.path.insert(1, os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files")))
import luxos_netadmin as na  # noqa: E402

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


class Routes(unittest.TestCase):
    def test_json(self):
        text = json.dumps([
            {"dst": "default", "gateway": "10.0.0.1", "dev": "enp1s0", "metric": 100},
            {"dst": "default", "gateway": "192.168.1.1", "dev": "wlp4s0", "protocol": "dhcp", "metric": 600},
            {"dst": "default", "dev": "wg0"}])
        r = na.parse_routes(text)
        self.assertEqual([x["gateway"] for x in r], ["10.0.0.1", "192.168.1.1"])
        self.assertEqual(r[0]["dev"], "enp1s0")

    def test_text(self):
        text = ("default via 192.168.1.1 dev wlp4s0 proto dhcp src 192.168.1.23 metric 600 \n"
                "default via 10.0.0.1 dev enp1s0 proto static metric 100\n"
                "10.0.0.0/24 dev enp1s0 scope link\n")
        r = na.parse_routes(text)
        self.assertEqual(r[0], {"gateway": "10.0.0.1", "dev": "enp1s0", "metric": 100})
        self.assertEqual(len(r), 2)

    def test_garbage(self):
        self.assertEqual(na.parse_routes(""), [])
        self.assertEqual(na.parse_routes("[broken"), [])
        self.assertEqual(na.parse_routes("Error: ..."), [])

    def test_nmcli(self):
        d = na.parse_device_show(DEVICE)
        self.assertEqual(d["connection"], "Domov 5G")
        self.assertEqual(d["type"], "wifi")
        self.assertEqual(d["ip4"], ["192.168.1.23/24"])
        self.assertEqual(d["dns"], ["192.168.1.1", "1.1.1.1", "fd00::1"])
        self.assertEqual(d["gateway"], "192.168.1.1")
        self.assertEqual(d["hwaddr"], "9C:2F:9D:76:21:DB")

    def test_terse_and_ssid(self):
        self.assertEqual(na.split_terse(r"yes:Moje\:sit\\x"), ["yes", "Moje:sit\\x"])
        self.assertEqual(na.parse_wifi_ssid("no:Soused\nyes:Moje\\:sit\n"), "Moje:sit")
        self.assertEqual(na.parse_wifi_ssid("no:A\n"), "")
        self.assertEqual(na.parse_resolv_conf("# x\nnameserver 127.0.0.53\noptions edns0\n"), ["127.0.0.53"])

    def test_network_info_fake(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "net.json")
            with open(p, "w") as f:
                json.dump({"routes": [{"dst": "default", "gateway": "192.168.1.1", "dev": "wlp4s0", "metric": 600}],
                           "device": DEVICE, "wifi": "no:Soused\nyes:Domov 5G\n"}, f)
            env = {"FAKE_NET": p, "LUXOS_IP": os.path.join(FAKE, "ip"), "LUXOS_NMCLI": os.path.join(FAKE, "nmcli")}
            old = os.environ.copy()
            os.environ.update(env)
            try:
                info = na.network_info()
            finally:
                os.environ.clear()
                os.environ.update(old)
        self.assertEqual((info["gateway"], info["dev"], info["ssid"]), ("192.168.1.1", "wlp4s0", "Domov 5G"))
        self.assertEqual(info["ip4"], ["192.168.1.23/24"])


class Policy(unittest.TestCase):
    def test_private(self):
        for ip in ("192.168.1.1", "10.0.0.138", "172.16.0.1", "172.31.255.254", "169.254.1.1", "fd00::1",
                   "fe80::1", "fe80::1%wlan0", "::ffff:192.168.0.1"):
            self.assertTrue(na.is_lan_ip(ip), ip)
        for ip in ("8.8.8.8", "172.32.0.1", "100.64.0.1", "127.0.0.1", "2a00::1", "nonsense", ""):
            self.assertFalse(na.is_lan_ip(ip), ip)
        self.assertTrue(na.is_lan_ip("100.64.0.1", gateway="100.64.0.1"))     # brana vzdy

    def test_lan_policy(self):
        gw = "192.168.1.1"
        cases = {
            "http://192.168.1.1/": "allow",
            "https://192.168.1.1:8443/login.htm": "allow",
            "http://10.0.0.5/status": "allow",
            "http://[fe80::1]/": "allow",
            "http://8.8.8.8/": "external",
            "https://www.example.com/": "resolve",
            "http://fritz.box/": "resolve",
            "http://localhost:631/": "external",
            "http://127.0.0.1/": "external",
            "file:///etc/passwd": "block",
            "javascript:alert(1)": "block",
            "data:text/html,<b>x</b>": "block",
            "mailto:support@example.com": "external",
            "http://192.168.1.1@evil.example/": "block",
            "about:blank": "allow",
            "http:///nohost": "block",
        }
        for url, want in cases.items():
            self.assertEqual(na.lan_policy(url, gw), want, url)
        # brana mimo privatni rozsahy (nektere site poskytovatelu)
        self.assertEqual(na.lan_policy("http://100.64.0.1/", "100.64.0.1"), "allow")
        self.assertEqual(na.lan_policy("http://100.64.0.2/", "100.64.0.1"), "external")

    def test_resolve(self):
        def fake(host, port):
            table = {"fritz.box": ["192.168.178.1"], "routerlogin.net": ["192.168.1.1"],
                     "example.com": ["93.184.216.34"], "rebind.example": ["192.168.1.1", "93.184.216.34"]}
            if host not in table:
                raise OSError("no such host")
            return [(2, 1, 6, "", (a, 0)) for a in table[host]]
        self.assertTrue(na.resolves_to_lan("fritz.box", resolver=fake))
        self.assertTrue(na.resolves_to_lan("routerlogin.net", resolver=fake))
        self.assertFalse(na.resolves_to_lan("example.com", resolver=fake))
        self.assertFalse(na.resolves_to_lan("rebind.example", resolver=fake))     # vse musi byt v siti
        self.assertFalse(na.resolves_to_lan("missing.lan", resolver=fake))

    def test_tls_scope(self):
        gw = "192.168.1.1"
        self.assertTrue(na.tls_exception_allowed("https://192.168.1.1/", gw))
        self.assertTrue(na.tls_exception_allowed("https://192.168.1.1:8443/x", gw))
        self.assertFalse(na.tls_exception_allowed("https://192.168.1.2/", gw))     # jine zarizeni
        self.assertFalse(na.tls_exception_allowed("https://fritz.box/", gw))
        self.assertFalse(na.tls_exception_allowed("http://192.168.1.1/", gw))
        self.assertFalse(na.tls_exception_allowed("https://192.168.1.1/", ""))

    def test_router_url(self):
        self.assertEqual(na.router_url("192.168.1.1"), "http://192.168.1.1/")
        self.assertEqual(na.router_url("192.168.1.1", https=True), "https://192.168.1.1/")
        self.assertEqual(na.router_url("fd00::1"), "http://[fd00::1]/")
        self.assertEqual(na.router_url(""), "")


class Devices(unittest.TestCase):
    def test_neigh_json(self):
        text = json.dumps([
            {"dst": "192.168.1.20", "dev": "wlp4s0", "lladdr": "AA:BB:CC:00:11:22", "state": ["STALE"]},
            {"dst": "192.168.1.1", "dev": "wlp4s0", "lladdr": "00:1a:2b:3c:4d:5e", "state": ["REACHABLE"]},
            {"dst": "192.168.1.30", "dev": "wlp4s0", "state": ["FAILED"]},
            {"dst": "192.168.1.31", "dev": "wlp4s0", "lladdr": "00:00:00:00:00:01", "state": ["INCOMPLETE"]},
            {"dst": "fe80::1", "dev": "wlp4s0", "lladdr": "00:1a:2b:3c:4d:5e", "router": None, "state": ["REACHABLE"]}])
        n = na.parse_neigh(text)
        self.assertEqual([x["ip"] for x in n], ["192.168.1.1", "192.168.1.20", "fe80::1"])
        self.assertEqual(n[1]["mac"], "aa:bb:cc:00:11:22")
        self.assertEqual(n[0]["state"], "REACHABLE")

    def test_neigh_text(self):
        text = ("10.2.0.2 dev wlp4s0 lladdr d2:99:b5:44:9a:c1 DELAY \n"
                "fe80::d099:b5ff:fe44:9ac1 dev wlp4s0 lladdr d2:99:b5:44:9a:c1 router REACHABLE\n"
                "10.2.0.9 dev wlp4s0 FAILED\n")
        n = na.parse_neigh(text)
        self.assertEqual([(x["ip"], x["state"]) for x in n], [("10.2.0.2", "DELAY"), ("fe80::d099:b5ff:fe44:9ac1", "REACHABLE")])

    def test_random_mac(self):
        self.assertTrue(na.is_random_mac("d2:99:b5:44:9a:c1"))
        self.assertTrue(na.is_random_mac("02:00:00:00:00:00"))
        self.assertFalse(na.is_random_mac("00:1a:2b:3c:4d:5e"))
        self.assertFalse(na.is_random_mac("zz"))

    def test_oui(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "oui.txt")
            with open(p, "w") as f:
                f.write("OUI/MA-L\t\t\tOrganization\n"
                        "00-1A-2B   (hex)\t\tAyecom Technology Co., Ltd.\n001A2B     (base 16)\t\tAyecom\n\n"
                        "9C-2F-9D   (hex)\t\tLiteon Technology Corporation\n")
            r = na.oui_lookup(["00:1a:2b:3c:4d:5e", "9c:2f:9d:76:21:db", "d2:99:b5:44:9a:c1", "11:22:33:44:55:66"],
                              paths=(os.path.join(d, "missing"), p))
        self.assertEqual(r, {"00:1a:2b:3c:4d:5e": "Ayecom Technology Co., Ltd.",
                             "9c:2f:9d:76:21:db": "Liteon Technology Corporation"})
        self.assertEqual(na.oui_lookup([], paths=(p,)), {})

    @unittest.skipUnless(os.path.exists("/usr/share/hwdata/oui.txt"), "hwdata neni nainstalovano")
    def test_oui_system(self):
        r = na.oui_lookup(["00:00:0c:12:34:56"])
        self.assertIn("Cisco", r.get("00:00:0c:12:34:56", ""))

    def test_scan_targets(self):
        t = na.scan_targets("192.168.1.23/24")
        self.assertEqual(len(t), 253)
        self.assertNotIn("192.168.1.23", t)
        self.assertEqual(len(na.scan_targets("10.2.9.254/16")), 253)     # jen /24 kolem sebe
        self.assertTrue(all(x.startswith("10.2.9.") for x in na.scan_targets("10.2.9.254/16")))
        self.assertEqual(na.scan_targets("fd00::5/64"), [])
        self.assertEqual(na.scan_targets("bad"), [])


class Tools(unittest.TestCase):
    def test_parse_ping(self):
        out = ("PING 192.168.1.1 (192.168.1.1) 56(84) bytes of data.\n\n--- 192.168.1.1 ping statistics ---\n"
               "4 packets transmitted, 3 received, 25% packet loss, time 3004ms\n"
               "rtt min/avg/max/mdev = 1.153/2.481/4.002/1.102 ms\n")
        self.assertEqual(na.parse_ping(out), {"sent": 4, "received": 3, "avg": 2.481})
        self.assertEqual(na.parse_ping("4 packets transmitted, 0 received, 100% packet loss"),
                         {"sent": 4, "received": 0, "avg": None})
        self.assertEqual(na.parse_ping(""), {"sent": 0, "received": 0, "avg": None})

    def test_ping_fake(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "net.json")
            with open(p, "w") as f:
                json.dump({"ping": {"192.168.1.1": 1.5}}, f)
            old = os.environ.copy()
            os.environ.update({"FAKE_NET": p, "LUXOS_PING": os.path.join(FAKE, "ping")})
            try:
                self.assertEqual(na.ping("192.168.1.1")["avg"], 1.5)
                self.assertEqual(na.ping("192.168.1.9")["received"], 0)
            finally:
                os.environ.clear()
                os.environ.update(old)

    def test_ping_localized_system(self):
        # cesky system: ping by psal "1 paketu odeslano, 1 prijato" - spousti se s LC_ALL=C
        with tempfile.TemporaryDirectory() as d:
            fake = os.path.join(d, "ping")
            with open(fake, "w") as f:
                f.write('#!/bin/sh\nif [ "$LC_ALL" = C ]; then\n'
                        'echo "1 packets transmitted, 1 received, 0% packet loss, time 0ms"\n'
                        'echo "rtt min/avg/max/mdev = 0.2/0.25/0.3/0.0 ms"\nelse\n'
                        'echo "1 paketu odeslano, 1 prijato, 0% packet loss, time 0ms"\nfi\n')
            os.chmod(fake, 0o755)
            old = os.environ.copy()
            os.environ.update({"LUXOS_PING": fake, "LANG": "cs_CZ.UTF-8", "LC_ALL": "cs_CZ.UTF-8"})
            try:
                self.assertEqual(na.ping("10.0.2.2", count=1), {"sent": 1, "received": 1, "avg": 0.25})
            finally:
                os.environ.clear()
                os.environ.update(old)

    def test_dns(self):
        ok, ms, addrs = na.dns_test("x", resolver=lambda h, p: [(2, 1, 6, "", ("1.2.3.4", p))])
        self.assertTrue(ok)
        self.assertEqual(addrs, ["1.2.3.4"])

        def fail(h, p):
            raise OSError("x")
        self.assertFalse(na.dns_test("x", resolver=fail)[0])

    def test_public_ip_and_speed_offline(self):
        # Nedostupne adresy: zadna vyjimka, prazdny vysledek (skutecny internet se v testech nepouziva)
        self.assertEqual(na.public_ip(urls=("http://127.0.0.1:9/",), timeout=1), "")
        self.assertIsNone(na.speed_test(1000, url="http://127.0.0.1:9/%d", timeout=1))


# ---- aplikace pod Xvfb --------------------------------------------------------------------
PAGE = """<html><head><title>Router</title></head><body style="font-family:sans-serif">
<h1 id="h">Test router admin</h1>
<a id="lan" href="/status">Status</a> <a id="out" href="http://93.184.216.34/">Internet</a>
<form><input name="user"><input type="password" name="pw"></form></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/away":
            # presmerovani bez kliknuti uzivatele (napr. cloudovy portal vyrobce)
            body = '<html><head><meta http-equiv="refresh" content="0;url=http://8.8.8.8/"></head></html>'.encode()
        else:
            body = (PAGE if self.path == "/" else "<html><body><h1>Status OK</h1></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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


def load_app():
    loader = importlib.machinery.SourceFileLoader("luxos_router", os.path.join(BIN, "luxos-router"))
    spec = importlib.util.spec_from_loader("luxos_router", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


SHOT_CODE = ("import sys, gi; gi.require_version('Gdk', '3.0'); from gi.repository import Gdk; "
             "r = Gdk.get_default_root_window(); "
             "Gdk.pixbuf_get_from_window(r, 0, 0, r.get_width(), r.get_height()).savev(sys.argv[1], 'png', [], [])")


def shot(path):
    """Snimek cele virtualni obrazovky (Xvfb) do PNG - v samostatnem procesu (nemeni stav X testu)."""
    import subprocess
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run([sys.executable, "-c", SHOT_CODE, path], timeout=20)


def js(view, code):
    view.evaluate_javascript(code, -1, None, None, None, None, None)


def webkit_ok():
    try:
        import gi
        gi.require_version("WebKit2", "4.1")
        return True
    except (ValueError, ImportError):
        return False


@unittest.skipUnless(os.environ.get("DISPLAY") and ("xvfb-run" in os.environ.get("XAUTHORITY", "")
                                                    or os.environ.get("LUXOS_TEST_X") == "1"),
                     "potrebuje virtualni X (xvfb-run)")
class App(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="luxos-router-test-")
        cls.http = start_server()
        cls.https = start_server(tls_dir=cls.dir)
        net = {"routes": [{"dst": "default", "gateway": "127.0.0.1", "dev": "wlp4s0", "metric": 600}],
               "device": DEVICE.replace("192.168.1.23/24", "127.0.0.5/24"),
               "wifi": "yes:Domov 5G\n",
               "neigh": [{"dst": "127.0.0.1", "dev": "wlp4s0", "lladdr": "00:1a:2b:3c:4d:5e", "state": ["REACHABLE"]},
                         {"dst": "127.0.0.20", "dev": "wlp4s0", "lladdr": "d2:99:b5:44:9a:c1", "state": ["STALE"]}],
               "ping": {"127.0.0.1": 1.2, "1.1.1.1": 14.0}}
        cls.net = os.path.join(cls.dir, "net.json")
        with open(cls.net, "w") as f:
            json.dump(net, f)
        cls.opened = []
        cls.saved_env = os.environ.copy()
        os.environ.update({"FAKE_NET": cls.net, "LUXOS_IP": os.path.join(FAKE, "ip"),
                           "LUXOS_NMCLI": os.path.join(FAKE, "nmcli"), "LUXOS_PING": os.path.join(FAKE, "ping"),
                           "FAKE_PING_LOG": os.path.join(cls.dir, "ping.log"),
                           "LUXOS_ROUTER_PORT": str(cls.http.server_address[1]),
                           "XDG_CONFIG_HOME": os.path.join(cls.dir, "config"),
                           "XDG_DATA_HOME": os.path.join(cls.dir, "data"),
                           "XDG_CACHE_HOME": os.path.join(cls.dir, "cache"), "LUXOS_PYDIR": PYDIR})
        cls.app = load_app()
        cls.app.open_in_browser = lambda uri: cls.opened.append(uri)
        from gi.repository import GLib, Gtk
        cls.GLib, cls.Gtk = GLib, Gtk
        # Ikona aplikace ze zdroju (na LuxOS je v hicolor)
        Gtk.IconTheme.get_default().append_search_path(os.path.join(HERE, "..", "files", "icons"))

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.https.shutdown()
        os.environ.clear()
        os.environ.update(cls.saved_env)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.opened.clear()
        self.win = self.app.Router()
        self.win.show_all()
        self.pump(0.3)

    def tearDown(self):
        self.win.destroy()
        self.pump(0.2)

    def pump(self, seconds, until=None):
        end = time.time() + seconds
        ctx = self.GLib.MainContext.default()
        while time.time() < end:
            while ctx.pending():
                ctx.iteration(False)
            if until and until():
                return True
            time.sleep(0.01)
        return bool(until and until())

    def labels(self, widget):
        out = []

        def walk(w):
            if isinstance(w, self.Gtk.Label):
                out.append(w.get_text())
            if isinstance(w, self.Gtk.Container):
                w.foreach(walk)
        walk(widget)
        return out

    def test_overview(self):
        hb = self.win.get_titlebar()
        self.assertIsInstance(hb, self.Gtk.HeaderBar)
        self.assertTrue(hb.get_show_close_button())
        texts = self.labels(self.win.overview_scroll)
        self.assertIn("Domov 5G", texts)
        self.assertIn("127.0.0.1", texts)
        self.assertIn("127.0.0.5/24", texts)
        self.assertIn("192.168.1.1, 1.1.1.1, fd00::1", texts)
        # WebKit se v prehledu nenacita
        self.assertIsNone(self.win.router.view)
        shots = os.environ.get("LUXOS_TEST_SHOTS")
        if shots:
            self.win.resize(980, 760)
            self.pump(0.5)
            shot(os.path.join(shots, "router-overview.png"))

    def find_tools(self):
        tools = []

        def walk(w):
            if isinstance(w, self.app.Tool):
                tools.append(w)
            elif isinstance(w, self.Gtk.Container):
                w.foreach(walk)
        walk(self.win.overview_scroll)
        return tools

    def test_ping_tools(self):
        tools = self.find_tools()
        ping_router, ping_inet = tools[1], tools[2]
        ping_router.button.clicked()
        ping_inet.button.clicked()
        self.assertTrue(self.pump(10, lambda: ping_router.result.get_text() and ping_inet.result.get_text()))
        self.assertEqual(ping_router.result.get_text(), "1.2 ms")
        self.assertEqual(ping_inet.result.get_text(), "14.0 ms")

    def test_devices(self):
        self.win.stack.set_visible_child_name("devices")
        self.assertTrue(self.pump(10, lambda: len(self.win.dev_store) == 3))
        rows = [tuple(r)[:4] for r in self.win.dev_store]
        self.assertTrue(rows[0][1].startswith("Router"))
        self.assertIn("Private address", rows[1][1])
        self.assertTrue(rows[2][1].startswith("This computer"))
        if os.path.exists("/usr/share/hwdata/oui.txt"):
            self.assertIn("Ayecom", rows[0][1])
        shots = os.environ.get("LUXOS_TEST_SHOTS")
        if shots:
            self.pump(0.5)
            shot(os.path.join(shots, "router-devices.png"))

    def test_scan(self):
        self.win.stack.set_visible_child_name("devices")
        log = os.path.join(self.dir, "ping.log")
        if os.path.exists(log):
            os.unlink(log)
        self.win.scan_btn.clicked()
        self.assertTrue(self.pump(60, lambda: self.win.scan_btn.get_sensitive()))
        with open(log) as f:
            hosts = f.read().split()
        self.assertEqual(len(hosts), 253)
        self.assertNotIn("127.0.0.5", hosts)

    @unittest.skipUnless(webkit_ok(), "WebKit2 4.1 neni k dispozici")
    def test_router_page_lan_only(self):
        self.win.stack.set_visible_child_name("router")
        r = self.win.router
        self.assertIsNotNone(r.view)
        self.assertTrue(r.ctx.is_ephemeral())
        self.assertTrue(self.pump(20, lambda: r.view.get_title() == "Router" and not r.view.is_loading()))
        self.assertTrue(r.view.get_uri().startswith("http://127.0.0.1:"))
        shots = os.environ.get("LUXOS_TEST_SHOTS")
        if shots:
            self.win.resize(980, 760)
            self.pump(1.0)
            shot(os.path.join(shots, "router-webview.png"))
        # odkaz do internetu (klik uzivatele) -> bezny prohlizec, stranka zustane
        js(r.view, "document.getElementById('out').click()")
        self.assertTrue(self.pump(10, lambda: self.opened))
        self.assertEqual(self.opened, ["http://93.184.216.34/"])
        self.assertTrue(r.view.get_uri().startswith("http://127.0.0.1:"))
        # odkaz v domaci siti -> v aplikaci
        js(r.view, "document.getElementById('lan').click()")
        self.assertTrue(self.pump(10, lambda: r.view.get_uri().endswith("/status") and not r.view.is_loading()))
        # presmerovani skriptem (bez kliknuti) jinam -> jen oznameni, nic se neotevre
        self.opened.clear()
        r.view.load_uri("http://127.0.0.1:%d/away" % self.http.server_address[1])
        self.assertTrue(self.pump(10, lambda: r.infobar.get_revealed()))
        self.assertEqual(self.opened, [])
        self.assertIn("8.8.8.8", r.info_label.get_text())
        self.assertEqual(r.info_uri, "http://8.8.8.8/")

    @unittest.skipUnless(webkit_ok(), "WebKit2 4.1 neni k dispozici")
    def test_self_signed_needs_confirmation(self):
        self.win.stack.set_visible_child_name("router")
        r = self.win.router
        self.assertTrue(self.pump(20, lambda: not r.view.is_loading()))
        url = "https://127.0.0.1:%d/" % self.https.server_address[1]
        seen = []
        shots = os.environ.get("LUXOS_TEST_SHOTS")

        def answer(resp):
            def tick():
                d = self.win.tls_dialog
                if d is None:
                    return True
                seen.append(d.get_property("text"))
                if shots and resp == self.Gtk.ResponseType.OK:
                    shot(os.path.join(shots, "router-certificate.png"))
                d.response(resp)
                return False
            self.GLib.timeout_add(300, tick)

        # 1) Zrusit: zadna vyjimka
        answer(self.Gtk.ResponseType.CANCEL)
        r.view.load_uri(url)
        self.assertTrue(self.pump(20, lambda: seen))
        self.assertEqual(r.tls_allowed, set())
        self.pump(1)
        # 2) Pokracovat: vyjimka jen pro adresu brany, stranka se nacte
        seen.clear()
        answer(self.Gtk.ResponseType.OK)
        r.view.load_uri(url)
        self.assertTrue(self.pump(25, lambda: r.view.get_uri() == url and r.view.get_title() == "Router"
                                  and not r.view.is_loading()))
        self.assertEqual(r.tls_allowed, {"127.0.0.1"})
        self.assertEqual(seen, ["The router uses its own security certificate"])

    @unittest.skipUnless(webkit_ok(), "WebKit2 4.1 neni k dispozici")
    def test_self_signed_other_host_refused(self):
        # Brana je 127.0.0.1; certifikat jineho zarizeni (10.x / jmeno) nejde povolit
        self.win.stack.set_visible_child_name("router")
        r = self.win.router
        self.assertTrue(self.pump(20, lambda: not r.view.is_loading()))
        self.assertFalse(r.on_tls(r.view, "https://10.0.0.7/", None, 0) is False)
        self.assertTrue(r.infobar.get_revealed())
        self.assertIn("10.0.0.7", r.info_label.get_text())
        self.assertIsNone(self.win.tls_dialog)


if __name__ == "__main__":
    unittest.main()
