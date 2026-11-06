"""Testy luxos-firewall (program v LSL) bez roota a bez zasahu do site pocitace.

Program bezi s LUXOS_FIREWALL_ROOT (testovaci koren s /etc, /home, /usr/bin, /proc/net ...).
Pravidla nftables se overi skutecnym nft jen v samostatnem jmennem prostoru site (`unshare -rn`,
uzivatel je tam root jen pro sebe); kdyz to system nedovoli, pouzije se falesny nft a testy
s jadrem se preskoci. Sit ani firewall pocitace se nikdy nemeni.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "luxos-firewall.lsl")
_BIN = None


def binary():
    global _BIN
    if _BIN:
        return _BIN
    path = os.environ.get("LUXOS_FIREWALL_BIN")
    if not path:
        out = tempfile.mkdtemp(prefix="luxos-fw-bin-")
        path = os.path.join(out, "luxos-firewall")
        subprocess.run(["lslc", "--target", "linux-x86_64-gnu", SRC, path], check=True, cwd=out)
    _BIN = path
    return path


def netns_ok():
    if not shutil.which("unshare") or not shutil.which("nft"):
        return False
    r = subprocess.run(["unshare", "-rn", "nft", "list", "ruleset"], capture_output=True)
    return r.returncode == 0


NETNS = netns_ok()

ROUTE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
wlan0\t00000000\t0101A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0
wlan0\t0001A8C0\t00000000\t0001\t0\t0\t600\t00FFFFFF\t0\t0\t0
eth1\t0000A88C\t00000000\t0001\t0\t0\t100\t0000FFFF\t0\t0\t0
tailscale0\t00004064\t00000000\t0001\t0\t0\t0\t0000C0FF\t0\t0\t0
wg0\t0000080A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0
"""
# 2001:db8:1:2::/64 RA prefix (wlan0), vychozi trasa, fe80::/64, multicast, /128 mistni adresa, tailscale
IPV6_ROUTE = """20010db8000100020000000000000000 40 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000001 00000000 00040001    wlan0
00000000000000000000000000000000 00 00000000000000000000000000000000 00 fe800000000000000000000000000001 00000400 00000001 00000000 00450003    wlan0
fe800000000000000000000000000000 40 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000001 00000000 00000001    wlan0
ff000000000000000000000000000000 08 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000001 00000000 00000001    wlan0
20010db8000100020000000000000005 80 00000000000000000000000000000000 00 00000000000000000000000000000000 00000000 00000002 00000000 80200001    wlan0
fd7a115ca1e0ab120000000000000000 3000000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000001 00000000 00000001 tailscale0
"""


class FirewallTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="luxos-fw-root-")
        for d in ("etc/luxos", "etc/ssh", "etc/cups", "etc/default", "usr/bin", "home/jana/.config/luxdrop",
                  "proc/net", "run", "var/lib/flatpak/app"):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
        self.write("proc/net/route", ROUTE)
        self.write("proc/net/ipv6_route", IPV6_ROUTE)
        self.write("usr/bin/luxdrop", "")
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        # falesny systemctl: sshd zapnuty jen kdyz existuje soubor sshd-enabled
        self.script("systemctl", '#!/bin/sh\nfor u in "$@"; do case $u in sshd.service) '
                                 'if [ -e "%s/sshd-enabled" ]; then echo enabled; else echo disabled; fi;; '
                                 'is-*) ;; *) echo disabled;; esac; done\nexit 0\n' % self.root)
        self.script("nft-fake", '#!/bin/sh\ncat >> "%s/nft-input"\necho "$@" >> "%s/nft-args"\nexit 0\n'
                    % (self.root, self.root))
        self.script("ss", '#!/bin/sh\ncat "%s/ss-output" 2>/dev/null\nexit 0\n' % self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def script(self, name, text):
        path = os.path.join(self.bin, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, 0o755)

    def run_fw(self, *args, netns=False, check=True):
        env = {"PATH": "/usr/bin:/bin", "LUXOS_FIREWALL_ROOT": self.root, "LANG": "C",
               "LUXOS_FIREWALL_SYSTEMCTL": os.path.join(self.bin, "systemctl"),
               "LUXOS_FIREWALL_SS": os.path.join(self.bin, "ss")}
        cmd = [binary(), *args]
        if netns:
            env["LUXOS_FIREWALL_NFT"] = shutil.which("nft")
            cmd = ["unshare", "-rn", *cmd]
        else:
            env["LUXOS_FIREWALL_NFT"] = os.path.join(self.bin, "nft-fake")
            if os.getuid() != 0 and args and args[0] not in ("render", "status", "help", "blocked", "version"):
                # prikazy roota: jako root jen v uzivatelskem jmennem prostoru (bez site pocitace)
                if shutil.which("unshare") and subprocess.run(["unshare", "-r", "true"]).returncode == 0:
                    cmd = ["unshare", "-r", *cmd]
                else:
                    self.skipTest("needs user namespaces")
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        if check and r.returncode != 0:
            self.fail(f"{args} -> {r.returncode}\n{r.stdout}\n{r.stderr}")
        return r

    def config(self):
        with open(os.path.join(self.root, "etc/luxos/firewall.json"), encoding="utf-8") as f:
            return json.load(f)

    # ---- pravidla ----
    def test_render_only_own_table(self):
        out = self.run_fw("render").stdout
        self.assertIn("table inet luxos {", out)
        self.assertNotIn("flush ruleset", out)
        tables = {line.split("{")[0].strip() for line in out.splitlines() if line.startswith(("table", "delete table"))}
        self.assertEqual(tables, {"table inet luxos", "delete table inet luxos"})
        # forward/output se nefiltruji (kontejnery, VM, exit node Tailscale)
        self.assertNotIn("hook forward", out)
        self.assertNotIn("hook output", out)
        self.assertIn("policy accept", out)

    def test_luxdrop_lan_only_and_essentials(self):
        out = self.run_fw("render").stdout
        lan_tcp = out.split("set lan_tcp")[1].split("}")[0]
        self.assertIn("47923-47924", lan_tcp)
        self.assertIn("53317", lan_tcp)
        any_tcp = out.split("set any_tcp")[1].split("}")[0]
        self.assertNotIn("47923", any_tcp)
        for essential in ("udp sport 67 udp dport 68 accept", "nd-neighbor-solicit", "nd-router-advert",
                          "packet-too-big", "ip daddr 224.0.0.251 udp dport 5353 accept", "meta l4proto igmp accept",
                          "udp sport 547 udp dport 546 accept", 'iif "lo" accept', "ct state established,related accept",
                          'iifname "virbr*" accept', 'iifname "podman*" accept'):
            self.assertIn(essential, out)

    def test_no_luxdrop_when_not_installed(self):
        os.remove(os.path.join(self.root, "usr/bin/luxdrop"))
        out = self.run_fw("render").stdout
        self.assertNotIn("47923", out)

    def test_luxdrop_custom_port_from_user_settings(self):
        self.write("home/jana/.config/luxdrop/settings.json", json.dumps({"port": 48000, "localsend_port": 53318}))
        out = self.run_fw("render").stdout
        lan_tcp = out.split("set lan_tcp")[1].split("}")[0]
        lan_udp = out.split("set lan_udp")[1].split("}")[0]
        self.assertIn("48000", lan_tcp)
        self.assertIn("53318", lan_tcp)
        self.assertIn("53318", lan_udp)

    def test_sshd_dynamic(self):
        self.write("usr/bin/sshd", "")
        self.assertNotIn("22", self.run_fw("render").stdout.split("set any_tcp")[1].split("}")[0])
        self.write("sshd-enabled", "")
        self.write("etc/ssh/sshd_config", "# Port 22\nPort 2222\n")
        any_tcp = self.run_fw("render").stdout.split("set any_tcp")[1].split("}")[0]
        self.assertIn("2222", any_tcp)
        self.assertNotIn(" 22 ", any_tcp.replace(",", " "))

    def test_cups_sharing_and_tailscale(self):
        self.write("etc/cups/cupsd.conf", "Listen localhost:631\nListen /run/cups/cups.sock\n")
        self.assertNotIn("631", self.run_fw("render").stdout)
        self.write("etc/cups/cupsd.conf", "Port 631\nListen /run/cups/cups.sock\n")
        self.assertIn("631", self.run_fw("render").stdout.split("set lan_tcp")[1].split("}")[0])
        self.write("usr/bin/tailscaled", "")
        self.write("etc/default/tailscaled", 'PORT="41700"\nFLAGS=""\n')
        self.assertIn("41700", self.run_fw("render").stdout.split("set any_udp")[1].split("}")[0])

    def test_steam_flatpak_per_user(self):
        self.assertNotIn("27036", self.run_fw("render").stdout)
        os.makedirs(os.path.join(self.root, "home/jana/.local/share/flatpak/app/com.valvesoftware.Steam"))
        out = self.run_fw("render").stdout
        self.assertIn("27036-27037", out.split("set lan_tcp")[1].split("}")[0])
        self.assertIn("27031-27036", out.split("set lan_udp")[1].split("}")[0])

    def test_connected_networks(self):
        out = self.run_fw("render").stdout
        net4 = out.split("set net4")[1].split("}")[0]
        net6 = out.split("set net6")[1].split("}")[0]
        self.assertIn("192.168.1.0/24", net4)
        self.assertIn("140.168.0.0/16", net4)          # verejna adresa primo v mistni siti
        self.assertNotIn("100.64", net4)               # tailscale0
        self.assertNotIn("10.8.0", net4)               # wg0 (VPN)
        self.assertNotIn("0.0.0.0", net4)
        self.assertIn("2001:0db8:0001:0002:0000:0000:0000:0000/64", net6)
        self.assertNotIn("fe80", net6)
        self.assertNotIn("ff00", net6)
        self.assertNotIn("/128", net6)
        self.assertNotIn("fd7a", net6)

    def test_hotspot_shared_interface(self):
        out = self.run_fw("render").stdout
        self.assertNotIn("elements", out.split("set shared_if")[1].split("}")[0])
        self.write("run/nm-dnsmasq-wlan0.pid", "123\n")
        out = self.run_fw("render").stdout
        self.assertIn('"wlan0"', out.split("set shared_if")[1].split("}")[0])
        self.assertIn("iifname @shared_if udp dport { 53, 67, 547 } accept", out)

    def test_tailscale_trust(self):
        out = self.run_fw("render").stdout
        self.assertNotIn("jump from_lan", out.split("chain from_tailscale")[1].split("}")[0])
        self.write("etc/luxos/firewall.json", json.dumps({"enable": True, "trust_tailscale": True, "allow": []}))
        out = self.run_fw("render").stdout
        self.assertIn("jump from_lan", out.split("chain from_tailscale")[1].split("}")[0])

    # ---- prikazy ----
    def test_allow_deny_cycle(self):
        r = self.run_fw("allow", "5432/tcp", "--app", "post gres!")
        self.assertIn("5432/tcp", r.stdout)
        cfg = self.config()
        self.assertEqual(cfg["allow"], [{"port": "5432", "proto": "tcp", "from": "lan", "app": "post-gres"}])
        self.run_fw("allow", "8000-8010", "--from", "any")
        cfg = self.config()
        self.assertIn({"port": "8000-8010", "proto": "tcp", "from": "any"}, cfg["allow"])
        self.assertIn({"port": "8000-8010", "proto": "udp", "from": "any"}, cfg["allow"])
        # stejny port znovu = nahrazeni (ne duplikat)
        self.run_fw("allow", "5432/tcp", "--from", "any")
        self.assertEqual(sum(1 for i in self.config()["allow"] if i["port"] == "5432"), 1)
        out = self.run_fw("render").stdout
        self.assertIn("5432", out.split("set any_tcp")[1].split("}")[0])
        self.run_fw("deny", "8000-8010/udp")
        self.assertNotIn({"port": "8000-8010", "proto": "udp", "from": "any"}, self.config()["allow"])
        self.assertEqual(self.run_fw("deny", "9999", check=False).returncode, 1)
        state = json.load(open(os.path.join(self.root, "run/luxos-firewall/state.json")))
        self.assertTrue(state["loaded"])
        self.assertEqual(os.stat(os.path.join(self.root, "etc/luxos/firewall.json")).st_mode & 0o777, 0o644)

    def test_invalid_specs(self):
        for bad in ("0", "65536", "80/icmp", "abc", "90-80", "1-2-3", "-1", "80/"):
            r = self.run_fw("allow", bad, check=False)
            self.assertEqual(r.returncode, 2, bad)
        self.assertEqual(self.run_fw("allow", "80", "--from", "internet", check=False).returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(self.root, "etc/luxos/firewall.json")))

    def test_off_on(self):
        self.run_fw("off")
        self.assertFalse(self.config()["enable"])
        with open(os.path.join(self.root, "nft-input"), encoding="utf-8") as f:
            last = f.read().split("# LuxOS firewall")[-1]
        self.assertIn("delete table inet luxos", last)
        self.assertEqual(self.run_fw("status", "--json").returncode, 0)
        status = json.loads(self.run_fw("status", "--json").stdout)
        self.assertFalse(status["enable"])
        self.run_fw("on")
        self.assertTrue(self.config()["enable"])

    def test_damaged_config_keeps_defaults(self):
        self.write("etc/luxos/firewall.json", "{not json")
        r = self.run_fw("status")
        self.assertIn("damaged", r.stdout)
        self.assertIn("table inet luxos {", self.run_fw("render").stdout)

    def test_bad_entries_ignored(self):
        self.write("etc/luxos/firewall.json", json.dumps({"enable": True, "allow": [
            {"port": "70000", "proto": "tcp"}, {"port": "22", "proto": "icmp"}, "x",
            {"port": "8080", "proto": "tcp", "from": "everywhere", "app": "a;rm -rf /"}]}))
        status = json.loads(self.run_fw("status", "--json").stdout)
        self.assertEqual(status["allow"], [{"port": "8080", "proto": "tcp", "from": "lan", "app": "a-rm--rf"}])

    # ---- se skutecnym nft v samostatnem jmennem prostoru site ----
    @unittest.skipUnless(NETNS, "unshare -rn + nft not available")
    def test_kernel_accepts_rules_and_keeps_other_tables(self):
        self.write("usr/bin/sshd", "")
        self.write("sshd-enabled", "")
        self.write("etc/luxos/firewall.json", json.dumps({"enable": True, "trust_tailscale": True, "allow": [
            {"port": "5432", "proto": "tcp", "from": "lan", "app": "postgres"}]}))
        rules = self.run_fw("render").stdout
        path = self.write("rules.nft", rules)
        # cizi tabulky (Tailscale ts-input v ip filter, podman) zustanou; nahrani 2x za sebou i smazani funguje
        other = ("table ip filter {\n chain ts-input {\n  type filter hook input priority filter; policy accept;\n }\n}\n"
                 "table inet netavark {\n chain input {\n  type filter hook input priority filter;\n }\n}\n")
        script = ("set -e; printf '%s' \"$1\" | nft -f -; nft -f \"$2\"; nft -f \"$2\"; nft list tables; "
                  "echo ---; nft delete table inet luxos; nft list tables")
        r = subprocess.run(["unshare", "-rn", "sh", "-c", script, "sh", other, path], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        before, after = r.stdout.split("---")
        self.assertIn("table inet luxos", before)
        self.assertIn("table ip filter", before)
        self.assertIn("table inet netavark", before)
        self.assertNotIn("table inet luxos", after)
        self.assertIn("table ip filter", after)
        self.assertIn("table inet netavark", after)

    @unittest.skipUnless(NETNS, "unshare -rn + nft not available")
    def test_load_unload_in_netns(self):
        r = self.run_fw("load", netns=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_fw("unload", netns=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
