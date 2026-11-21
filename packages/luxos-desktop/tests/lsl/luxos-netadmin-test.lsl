# Test luxos_netadmin.lsl bez displeje (test_luxos_netadmin.py): vypise radky "ok NAZEV" / "FAIL NAZEV ..."
load json
load luxos_netadmin as na

failures = 0

function expect(name, got, want):
    global failures
    if got == want:
        print "ok " + name
    else:
        failures += 1
        print "FAIL " + name + " got " + String(got) + " want " + String(want)
    end
    return 0
end

DEVICE = "GENERAL.DEVICE:wlp4s0\nGENERAL.TYPE:wifi\nGENERAL.HWADDR:9C:2F:9D:76:21:DB\nGENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:Domov 5G\nIP4.ADDRESS[1]:192.168.1.23/24\nIP4.GATEWAY:192.168.1.1\nIP4.ROUTE[1]:dst = 0.0.0.0/0, nh = 192.168.1.1, mt = 600\nIP4.DNS[1]:192.168.1.1\nIP4.DNS[2]:1.1.1.1\nIP6.ADDRESS[1]:fe80::687b:1a76:a3e:2bc9/64\nIP6.GATEWAY:--\nIP6.DNS[1]:fd00\\:\\:1\n"

# ---- brana ----
r = na.parse_routes(json.encode([{"dst": "default", "gateway": "10.0.0.1", "dev": "enp1s0", "metric": 100},
    {"dst": "default", "gateway": "192.168.1.1", "dev": "wlp4s0", "protocol": "dhcp", "metric": 600},
    {"dst": "default", "dev": "wg0"}]))
call expect("routes-json", [x["gateway"] for x in r], ["10.0.0.1", "192.168.1.1"])
call expect("routes-json-dev", r[0]["dev"], "enp1s0")
r = na.parse_routes("default via 192.168.1.1 dev wlp4s0 proto dhcp src 192.168.1.23 metric 600 \ndefault via 10.0.0.1 dev enp1s0 proto static metric 100\n10.0.0.0/24 dev enp1s0 scope link\n")
call expect("routes-text", r[0], {"gateway": "10.0.0.1", "dev": "enp1s0", "metric": 100})
call expect("routes-text-count", len(r), 2)
call expect("routes-empty", na.parse_routes(""), [])
call expect("routes-broken", na.parse_routes("[broken"), [])
call expect("routes-error", na.parse_routes("Error: ..."), [])

# ---- nmcli ----
d = na.parse_device_show(DEVICE)
call expect("device-connection", d["connection"], "Domov 5G")
call expect("device-type", d["type"], "wifi")
call expect("device-ip4", d["ip4"], ["192.168.1.23/24"])
call expect("device-dns", d["dns"], ["192.168.1.1", "1.1.1.1", "fd00::1"])
call expect("device-gateway", d["gateway"], "192.168.1.1")
call expect("device-hwaddr", d["hwaddr"], "9C:2F:9D:76:21:DB")
call expect("terse", na.split_terse("yes:Moje\\:sit\\\\x"), ["yes", "Moje:sit\\x"])
call expect("ssid", na.parse_wifi_ssid("no:Soused\nyes:Moje\\:sit\n"), "Moje:sit")
call expect("ssid-none", na.parse_wifi_ssid("no:A\n"), "")
call expect("resolv", na.parse_resolv_conf("# x\nnameserver 127.0.0.53\noptions edns0\n"), ["127.0.0.53"])

# ---- domaci sit ----
for ip in ["192.168.1.1", "10.0.0.138", "172.16.0.1", "172.31.255.254", "169.254.1.1", "fd00::1", "fe80::1", "fe80::1%wlan0", "::ffff:192.168.0.1"]:
    call expect("lan " + ip, na.is_lan_ip(ip, ""), True)
end
for ip in ["8.8.8.8", "172.32.0.1", "100.64.0.1", "127.0.0.1", "2a00::1", "nonsense", "", "1.2.3", "01.2.3.4", "1:2:3:4:5:6:7:8:9", "fe80:::1"]:
    call expect("not-lan " + ip, na.is_lan_ip(ip, ""), False)
end
call expect("lan-gateway", na.is_lan_ip("100.64.0.1", "100.64.0.1"), True)

policy = {"http://192.168.1.1/": "allow", "https://192.168.1.1:8443/login.htm": "allow", "http://10.0.0.5/status": "allow",
    "http://[fe80::1]/": "allow", "http://8.8.8.8/": "external", "https://www.example.com/": "resolve",
    "http://fritz.box/": "resolve", "http://localhost:631/": "external", "http://127.0.0.1/": "external",
    "file:///etc/passwd": "block", "javascript:alert(1)": "block", "data:text/html,<b>x</b>": "block",
    "mailto:support@example.com": "external", "http://192.168.1.1@evil.example/": "block", "about:blank": "allow",
    "http:///nohost": "block", "HTTP://192.168.1.1/": "allow", "http://[fe80::1/": "block", "http://Fritz.Box:80/x": "resolve",
    "http://router.localhost/": "external", "ftp://192.168.1.1/": "block"}
for url in policy.keys():
    call expect("policy " + url, na.lan_policy(url, "192.168.1.1"), policy[url])
end
call expect("policy-gateway", na.lan_policy("http://100.64.0.1/", "100.64.0.1"), "allow")
call expect("policy-not-gateway", na.lan_policy("http://100.64.0.2/", "100.64.0.1"), "external")
call expect("host", na.url_host("https://User@Fritz.BOX:8443/a?b#c"), "fritz.box")
call expect("host-v6", na.url_host("http://[FE80::1]:80/"), "fe80::1")

# preklad jmen (getent ahosts): vse musi byt v siti
call expect("hosts", na.parse_hosts("192.168.178.1   STREAM fritz.box\n192.168.178.1   DGRAM\n192.168.178.1   RAW\n"), ["192.168.178.1"])
call expect("resolve-lan", na.all_lan(["192.168.178.1"], ""), True)
call expect("resolve-public", na.all_lan(["93.184.216.34"], ""), False)
call expect("resolve-rebind", na.all_lan(["192.168.1.1", "93.184.216.34"], ""), False)
call expect("resolve-missing", na.all_lan([], ""), False)

gw = "192.168.1.1"
call expect("tls-gateway", na.tls_exception_allowed("https://192.168.1.1/", gw), True)
call expect("tls-port", na.tls_exception_allowed("https://192.168.1.1:8443/x", gw), True)
call expect("tls-other", na.tls_exception_allowed("https://192.168.1.2/", gw), False)
call expect("tls-name", na.tls_exception_allowed("https://fritz.box/", gw), False)
call expect("tls-http", na.tls_exception_allowed("http://192.168.1.1/", gw), False)
call expect("tls-no-gateway", na.tls_exception_allowed("https://192.168.1.1/", ""), False)
call expect("url", na.router_url("192.168.1.1", False, ""), "http://192.168.1.1/")
call expect("url-https", na.router_url("192.168.1.1", True, ""), "https://192.168.1.1/")
call expect("url-v6", na.router_url("fd00::1", False, ""), "http://[fd00::1]/")
call expect("url-port", na.router_url("127.0.0.1", False, "8080"), "http://127.0.0.1:8080/")
call expect("url-none", na.router_url("", False, ""), "")

# ---- zarizeni ----
n = na.parse_neigh(json.encode([
    {"dst": "192.168.1.20", "dev": "wlp4s0", "lladdr": "AA:BB:CC:00:11:22", "state": ["STALE"]},
    {"dst": "192.168.1.1", "dev": "wlp4s0", "lladdr": "00:1a:2b:3c:4d:5e", "state": ["REACHABLE"]},
    {"dst": "192.168.1.30", "dev": "wlp4s0", "state": ["FAILED"]},
    {"dst": "192.168.1.31", "dev": "wlp4s0", "lladdr": "00:00:00:00:00:01", "state": ["INCOMPLETE"]},
    {"dst": "192.168.1.100", "dev": "wlp4s0", "lladdr": "00:00:00:00:00:02", "state": ["DELAY"]},
    {"dst": "fe80::1", "dev": "wlp4s0", "lladdr": "00:1a:2b:3c:4d:5e", "router": None, "state": ["REACHABLE"]}]))
call expect("neigh-json", [x["ip"] for x in n], ["192.168.1.1", "192.168.1.20", "192.168.1.100", "fe80::1"])
call expect("neigh-mac", n[1]["mac"], "aa:bb:cc:00:11:22")
call expect("neigh-state", n[0]["state"], "REACHABLE")
n = na.parse_neigh("10.2.0.2 dev wlp4s0 lladdr d2:99:b5:44:9a:c1 DELAY \nfe80::d099:b5ff:fe44:9ac1 dev wlp4s0 lladdr d2:99:b5:44:9a:c1 router REACHABLE\n10.2.0.9 dev wlp4s0 FAILED\n")
call expect("neigh-text", [[x["ip"], x["state"]] for x in n], [["10.2.0.2", "DELAY"], ["fe80::d099:b5ff:fe44:9ac1", "REACHABLE"]])
call expect("random-mac", na.is_random_mac("d2:99:b5:44:9a:c1"), True)
call expect("random-mac-02", na.is_random_mac("02:00:00:00:00:00"), True)
call expect("global-mac", na.is_random_mac("00:1a:2b:3c:4d:5e"), False)
call expect("bad-mac", na.is_random_mac("zz"), False)
oui = "OUI/MA-L\t\t\tOrganization\n00-1A-2B   (hex)\t\tAyecom Technology Co., Ltd.\n001A2B     (base 16)\t\tAyecom\n\n9C-2F-9D   (hex)\t\tLiteon Technology Corporation\n"
call expect("oui", na.oui_parse(oui, ["00:1a:2b:3c:4d:5e", "9c:2f:9d:76:21:db", "d2:99:b5:44:9a:c1", "11:22:33:44:55:66"]),
    {"00:1a:2b:3c:4d:5e": "Ayecom Technology Co., Ltd.", "9c:2f:9d:76:21:db": "Liteon Technology Corporation"})
call expect("oui-empty", na.oui_parse(oui, []), {})
call expect("oui-patterns", na.oui_patterns(["00:1a:2b:3c:4d:5e", "00:1A:2B:00:00:00", "d2:99:b5:44:9a:c1"]), ["00-1A-2B   (hex)"])
t = na.scan_targets("192.168.1.23/24")
call expect("scan-24", len(t), 253)
call expect("scan-own", "192.168.1.23" in t, False)
call expect("scan-first", [t[0], t[len(t) - 1]], ["192.168.1.1", "192.168.1.254"])
t = na.scan_targets("10.2.9.254/16")
call expect("scan-16", len(t), 253)
call expect("scan-16-around", len([x for x in t if x.startswith("10.2.9.")]), 253)
call expect("scan-30", na.scan_targets("10.0.0.1/30"), ["10.0.0.2"])
call expect("scan-v6", na.scan_targets("fd00::5/64"), [])
call expect("scan-bad", na.scan_targets("bad"), [])

# ---- ping ----
call expect("ping", na.parse_ping("PING 192.168.1.1 (192.168.1.1) 56(84) bytes of data.\n\n--- 192.168.1.1 ping statistics ---\n4 packets transmitted, 3 received, 25% packet loss, time 3004ms\nrtt min/avg/max/mdev = 1.153/2.481/4.002/1.102 ms\n"), {"sent": 4, "received": 3, "avg": 2.481})
call expect("ping-lost", na.parse_ping("4 packets transmitted, 0 received, 100% packet loss"), {"sent": 4, "received": 0, "avg": None})
call expect("ping-busybox", na.parse_ping("1 packets transmitted, 1 packets received, 0% packet loss\nround-trip min/avg/max = 0.1/0.2/0.3 ms\n"), {"sent": 1, "received": 1, "avg": None})
call expect("ping-empty", na.parse_ping(""), {"sent": 0, "received": 0, "avg": None})
call expect("fixed1", [na.fixed1(1.2), na.fixed1(14.0), na.fixed1(2.481), na.fixed1(0.04)], ["1.2", "14.0", "2.5", "0.0"])
if failures > 0:
    exit(1)
end
