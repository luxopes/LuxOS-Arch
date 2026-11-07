"""Sprava site (Router): prehled site s rychlymi testy, zarizeni v siti a webova sprava routeru.

Vse ukazkove: falesne ip/nmcli/ping z tests/fake-net (FAKE_NET jako tests/test_luxos_netadmin.py),
zadne skutecne skenovani ani ping domaci site. Tlacitka, ktera by sla na internet (verejna IP,
DNS, rychlost) se nemackaji. Webova sprava = ukazkova stranka mistniho falesneho serveru na
127.0.0.1 (brana v druhem spusteni, LUXOS_ROUTER_PORT), nikdy skutecny router."""
import http.server
import json
import os

DEVICE = """GENERAL.DEVICE:wlp2s0
GENERAL.TYPE:wifi
GENERAL.HWADDR:E4:C7:67:3A:51:9D
GENERAL.STATE:100 (connected)
GENERAL.CONNECTION:Home-WiFi
IP4.ADDRESS[1]:192.168.1.23/24
IP4.GATEWAY:192.168.1.1
IP4.DNS[1]:192.168.1.1
IP6.ADDRESS[1]:fe80::6a1c:2bff:fe41:9a77/64
"""

NEIGH = [
    ("192.168.1.1", "34:f7:16:2a:90:11", "REACHABLE"),
    ("192.168.1.10", "90:09:d0:14:6e:02", "REACHABLE"),
    ("192.168.1.31", "f0:ee:7a:5c:13:a8", "REACHABLE"),
    ("192.168.1.42", "64:4e:d7:81:2c:4f", "STALE"),
    ("192.168.1.57", "78:28:ca:0b:77:e1", "REACHABLE"),
    ("192.168.1.64", "d8:3a:dd:42:19:6b", "STALE"),
    ("192.168.1.77", "64:1b:2f:93:a0:5c", "REACHABLE"),
    ("192.168.1.88", "84:28:59:6d:f2:30", "STALE"),
    ("192.168.1.103", "da:41:7c:9e:02:b5", "REACHABLE"),
]

ROUTER_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Home Router</title>
<style>
body{margin:0;font-family:Inter,sans-serif;background:#f3f5f9;color:#1d2433}
header{background:#24324d;color:#fff;padding:14px 28px;display:flex;align-items:center;gap:14px}
header b{font-size:18px} header span{opacity:.7;font-size:13px}
nav{display:flex;gap:4px;padding:0 22px;background:#2e3e5e}
nav a{color:#cfd8ea;padding:10px 14px;font-size:13px;text-decoration:none}
nav a.on{color:#fff;border-bottom:3px solid #4d8dff}
main{display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:24px 28px}
.card{background:#fff;border-radius:10px;padding:16px 20px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card h3{margin:0 0 10px;font-size:14px;color:#56607a;text-transform:uppercase;letter-spacing:.04em}
table{width:100%;font-size:14px;border-collapse:collapse} td{padding:5px 0} td+td{text-align:right;color:#3a4459}
.ok{color:#1f9d55;font-weight:600}
</style></head><body>
<header><b>Home Router</b><span>Firmware 3.2.1</span></header>
<nav><a class="on">Status</a><a>Wireless</a><a>Network</a><a>Devices</a><a>Parental Controls</a><a>System</a></nav>
<main>
<div class="card"><h3>Internet</h3><table>
<tr><td>Status</td><td class="ok">Connected</td></tr>
<tr><td>Connection type</td><td>DHCP</td></tr>
<tr><td>Uptime</td><td>12 days 4 h</td></tr>
<tr><td>DNS</td><td>Automatic</td></tr></table></div>
<div class="card"><h3>Wireless</h3><table>
<tr><td>Network name</td><td>Home-WiFi</td></tr>
<tr><td>Band</td><td>2.4 GHz + 5 GHz</td></tr>
<tr><td>Security</td><td>WPA2/WPA3</td></tr>
<tr><td>Guest network</td><td>Off</td></tr></table></div>
<div class="card"><h3>Local network</h3><table>
<tr><td>Router address</td><td>192.168.1.1</td></tr>
<tr><td>DHCP server</td><td class="ok">On</td></tr>
<tr><td>Address range</td><td>192.168.1.100 - 199</td></tr></table></div>
<div class="card"><h3>Devices</h3><table>
<tr><td>Connected now</td><td>9</td></tr>
<tr><td>Wireless</td><td>7</td></tr>
<tr><td>Cable</td><td>2</td></tr></table></div>
</main></body></html>
"""


class RouterHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = ROUTER_PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        pass


def net_env(s, name, gateway):
    net = {"routes": [{"dst": "default", "gateway": gateway, "dev": "wlp2s0", "metric": 600}],
           "device": DEVICE.replace("192.168.1.1\n", gateway + "\n"),
           "wifi": "yes:Home-WiFi\nno:Neighbour-5G\n",
           "neigh": [{"dst": ip, "dev": "wlp2s0", "lladdr": mac, "state": [st]} for ip, mac, st in NEIGH],
           "ping": {gateway: 2.4, "1.1.1.1": 14.2}}
    path = os.path.join(s.tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(net, f)
    fake = s.src("luxos-desktop/tests/fake-net")
    return {"FAKE_NET": path, "LUXOS_IP": os.path.join(fake, "ip"), "LUXOS_NMCLI": os.path.join(fake, "nmcli"),
            "LUXOS_PING": os.path.join(fake, "ping"), "LUXOS_PYDIR": s.src("luxos-desktop/files/python")}


def shots(s):
    env = net_env(s, "net.json", "192.168.1.1")
    p = s.launch_python("luxos-desktop/files/bin/luxos-router", env=env)
    win = s.window(pid=p.pid, size=(900, 700))
    s.click(836, 521, win)              # Ping router -> falesny ping
    s.click(836, 568, win)              # Ping internet -> falesny ping
    s.sleep(1.5)
    s.capture("1", win)
    s.stop()

    # zarizeni v siti (jen falesne "ip neigh", tlacitko Hledat v siti se nemacka)
    p = s.launch_python("luxos-desktop/files/bin/luxos-router", env=dict(env, LUXOS_ROUTER_PAGE="devices"))
    win = s.window(pid=p.pid, size=(900, 560))
    s.sleep(1.5)
    s.capture("2", win)
    s.stop()

    # webova sprava routeru: brana = mistni falesny server
    port = s.serve_http(RouterHandler)
    env = net_env(s, "net-router.json", "127.0.0.1")
    env.update({"LUXOS_ROUTER_PAGE": "router", "LUXOS_ROUTER_PORT": str(port)})
    p = s.launch_python("luxos-desktop/files/bin/luxos-router", env=env)
    win = s.window(pid=p.pid, size=(900, 600))
    s.sleep(4)
    s.capture("3", win)
