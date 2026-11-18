#!/usr/bin/env python3
"""Sit sandboxu (--net): smerovani v namespace od pasty - bez root, bez pasty.

    python3 packages/luxos-sandbox/tests/test_netns.py -v

Ziva cast bezi v novem uzivatelskem + sitovem namespace (unshare -rn) s dummy rozhranim, ktere
napodobuje LAN hostitele (IPv4 /24, verejna IPv6 /64 i trasa z RA); hostitel se nemeni.
Overuje: v namespace zustane jen vychozi trasa, LAN obou rodin a soukrome rozsahy jsou zakazane,
internet ne, bez vychozi trasy se LAN nedosahne, kazda chyba ip = sandbox se nespusti.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "files", "luxos-sandbox")


def load():
    loader = importlib.machinery.SourceFileLoader("luxos_sandbox_cli", CLI)
    spec = importlib.util.spec_from_loader("luxos_sandbox_cli", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


sbx = load()

# Tvar vystupu "ip -j" na notebooku s Wi-Fi a IPv6 z RA (overeno na hostiteli vyvojare)
ADDRS = [{"ifname": "lo", "addr_info": [{"local": "127.0.0.1", "prefixlen": 8}, {"local": "::1", "prefixlen": 128}]},
         {"ifname": "wlan0", "addr_info": [{"local": "10.2.4.107", "prefixlen": 16},
                                           {"local": "2a09:1980:1005:3002:9fb9:1c4e:c453:3cbc", "prefixlen": 64},
                                           {"local": "fe80::687b:1a76:a3e:2bc9", "prefixlen": 64}]}]
ROUTES4 = [{"dst": "default", "gateway": "10.2.0.2", "dev": "wlan0", "protocol": "dhcp"},
           {"dst": "10.2.0.0/16", "dev": "wlan0", "protocol": "kernel", "scope": "link"},
           {"dst": "0.0.0.0/1", "gateway": "10.8.0.1", "dev": "tun0"},          # VPN do internetu
           {"dst": "203.0.113.0/24", "dev": "eth1", "protocol": "static", "scope": "link"}]
ROUTES6 = [{"dst": "2a09:1980:1005:3002::/64", "dev": "wlan0", "protocol": "ra"},
           {"dst": "fe80::/64", "dev": "wlan0", "protocol": "kernel"},
           {"dst": "ff00::/8", "dev": "wlan0", "type": "multicast"},
           {"dst": "default", "gateway": "fe80::1", "dev": "wlan0", "protocol": "ra"}]


class Prefixes(unittest.TestCase):
    def test_onlink_prefixes(self):
        self.assertEqual(sbx._onlink_prefixes(ADDRS, ROUTES4, 4), ["10.2.0.0/16", "203.0.113.0/24"])
        self.assertEqual(sbx._onlink_prefixes(ADDRS, ROUTES6, 6), ["2a09:1980:1005:3002::/64"])

    def test_too_short_prefix_ignored(self):
        # trasa bez brany do pulky internetu (nektere VPN) neni LAN - jinak by sandbox nemel internet
        self.assertEqual(sbx._onlink_prefixes([], [{"dst": "0.0.0.0/1", "dev": "tun0"}], 4), [])


class FailClosed(unittest.TestCase):
    def test_unknown_host_networks(self):
        with self.assertRaises(OSError):
            sbx.setup_netns({"host_addrs": []})

    def test_ip_error_is_fatal(self):
        def fake(*args, check=False):
            ok = args[:2] in (("-j", "-4"), ("-j", "-6"))
            return subprocess.CompletedProcess(args, 0 if ok else 2, "[]" if ok else "", "" if ok else "boom")
        with mock.patch.object(sbx, "ip", fake), mock.patch.object(sbx.os.path, "isdir", lambda p: False):
            with self.assertRaises(OSError):
                sbx.setup_netns({"host_addrs": [], "host_nets": []})

    def test_launch_refuses_when_host_networks_unknown(self):
        with mock.patch.object(sbx.shutil, "which", lambda c: "/usr/bin/" + c), \
                mock.patch.object(sbx, "host_networks", lambda: None), \
                mock.patch.object(sbx, "host_addresses", lambda: []), \
                mock.patch.object(sbx.subprocess, "call") as call, \
                mock.patch.object(sbx.subprocess, "run") as run:
            with self.assertRaises(SystemExit):
                sbx.launch({"net": True, "argv": ["true"]})
            call.assert_not_called()
            run.assert_not_called()


PROBE = r"""
import importlib.machinery, importlib.util, json, subprocess, sys
def sh(*c):
    subprocess.run(c, check=True, capture_output=True)
mode = sys.argv[2]
sh("ip", "link", "set", "lo", "up")
sh("ip", "link", "add", "d0", "type", "dummy")
sh("ip", "link", "set", "d0", "up")
sh("ip", "addr", "add", "192.168.50.10/24", "dev", "d0")
sh("ip", "-6", "addr", "add", "2001:db8:5::10/64", "dev", "d0", "nodad")
sh("ip", "-6", "route", "add", "2001:db8:7::/64", "dev", "d0", "proto", "ra")
sh("ip", "-6", "route", "add", "default", "via", "fe80::1", "dev", "d0")
if mode == "default":
    sh("ip", "route", "add", "default", "via", "192.168.50.1")
loader = importlib.machinery.SourceFileLoader("m", sys.argv[1])
s = importlib.util.spec_from_loader("m", loader); m = importlib.util.module_from_spec(s); loader.exec_module(m)
m.setup_netns({"host_addrs": ["192.168.50.10", "2001:db8:5::10", "198.51.100.7"],
               "host_nets": ["192.168.50.0/24", "2001:db8:5::/64", "2001:db8:7::/64"]})
out = {}
for dst in sys.argv[3:]:
    r = subprocess.run(["ip", "route", "get", dst], capture_output=True, text=True)
    out[dst] = "blocked" if r.returncode else ("local" if r.stdout.startswith("local") else "open")
print(json.dumps(out))
"""


def userns_ok():
    if not shutil.which("unshare") or not shutil.which("ip"):
        return False
    r = subprocess.run(["unshare", "-rn", "ip", "link", "add", "d0", "type", "dummy"], capture_output=True)
    return r.returncode == 0


@unittest.skipUnless(userns_ok(), "unshare -rn with dummy links not available")
class LiveNamespace(unittest.TestCase):
    DSTS = ["192.168.50.20", "2001:db8:5::20", "2001:db8:7::1", "10.1.1.1", "fd00::1",
            "198.51.100.7", "1.1.1.1", "2606:4700:4700::1111", "192.168.50.10", "169.254.1.53"]

    def probe(self, mode):
        r = subprocess.run(["unshare", "-rn", sys.executable, "-I", "-c", PROBE, CLI, mode, *self.DSTS],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_lan_blocked_internet_open(self):
        got = self.probe("default")
        for dst in ("192.168.50.20", "2001:db8:5::20", "2001:db8:7::1", "10.1.1.1", "fd00::1", "198.51.100.7"):
            self.assertEqual(got[dst], "blocked", dst)
        self.assertEqual(got["1.1.1.1"], "open")
        self.assertEqual(got["2606:4700:4700::1111"], "open")
        self.assertEqual(got["169.254.1.53"], "open")           # DNS forwarder pasty
        self.assertEqual(got["192.168.50.10"], "local")          # vlastni adresa namespace

    def test_without_ipv4_default_route_lan_still_blocked(self):
        got = self.probe("no-default")
        self.assertEqual(got["192.168.50.20"], "blocked")
        self.assertEqual(got["1.1.1.1"], "blocked")
        self.assertEqual(got["2001:db8:5::20"], "blocked")


if __name__ == "__main__":
    unittest.main()
