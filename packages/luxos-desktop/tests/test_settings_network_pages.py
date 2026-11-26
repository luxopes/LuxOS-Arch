#!/usr/bin/env python3
"""LuxOS - Nastaveni: VPN a Proxy. Falesny nmcli zapisuje volani do FAKE_LOG (a obsah passwd-file do PWFILE_LOG);
proxy se overuje v GSettings (keyfile backend testu) a v ~/.config/luxos/proxy.env.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      python3 -m unittest packages/luxos-desktop/tests/test_settings_network_pages.py -v
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
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lsl_app_harness as h  # noqa: E402

NMCLI = r'''#!/bin/sh
printf "%s\n" "nmcli $*" >>"$FAKE_LOG"
case "$*" in
  "-t -f NAME,UUID,TYPE,ACTIVE connection show")
    printf 'Home WG:uuid-wg:wireguard:no\nWork\\: VPN:uuid-ovpn:vpn:no\nCert VPN:uuid-ovpn2:vpn:no\nSAIFI:uuid-wifi:802-11-wireless:yes\n';;
  "-g vpn.data,vpn.user-name connection show uuid-ovpn")
    printf 'connection-type = password, remote = vpn.example.com:1194\n\n';;
  "-g vpn.data,vpn.user-name connection show uuid-ovpn2")
    printf 'connection-type = tls, remote = vpn.example.com:1194\n\n';;
  "connection up uuid-ovpn"|"connection up uuid-ovpn2")
    echo "Error: Connection activation failed: No valid secrets"
    echo "Hint: use 'journalctl -xe NM_CONNECTION=uuid-ovpn' to get more details."; exit 4;;
  "connection up uuid-ovpn passwd-file "*)
    for a in "$@"; do f="$a"; done
    cat "$f" >>"$PWFILE_LOG"; stat -c %a "$f" >>"$PWFILE_LOG";;
  "connection import type wireguard file "*) echo "Connection 'wg0' (uuid-new) successfully added.";;
  "connection import type openvpn file "*) echo "Error: failed to import: unknown file" ; exit 2;;
esac
exit 0
'''


def setUpModule():
    if not h.lslc_ok():
        raise unittest.SkipTest("lslc 0.11 is not installed")
    h.build("luxos-settings")


def make_env(lang="C.UTF-8"):
    tmp = Path(tempfile.mkdtemp(prefix="settings-net-", dir=h.private_dir()))
    env = h.base_env(tmp, lang)
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    (bin_dir / "nmcli").write_text(NMCLI)
    (bin_dir / "nmcli").chmod(0o755)
    env.update(PATH=f"{bin_dir}:{os.environ['PATH']}", PWFILE_LOG=str(tmp / "pwfile.log"))
    return tmp, env


def calls(tmp):
    log = tmp / "fake.log"
    return log.read_text().splitlines() if log.exists() else []


def gs_get(tmp, env, schema, key):
    e = dict(env)
    return subprocess.run(["gsettings", "get", schema, key], env=e, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(h.HAVE_X11, "Xvfb, xdotool or dbus-run-session missing")
class NetworkPages(unittest.TestCase):
    def run_app(self, page, script, tmp, env):
        app = h.X11App([str(h.build("luxos-settings")), page], env, script, tmp=tmp)
        self.addCleanup(app.close)
        return app

    # ---- VPN ----

    def test_vpn_list_and_connect(self):
        tmp, env = make_env()
        app = self.run_app("vpn", ["wait 600", "dump", "switch Home WG on", "wait 300",
                                   "switch Work: VPN on", "wait 300", "dump",
                                   "entry User name=anna", "entry Password=tajne heslo 1", "click Connect",
                                   "wait 800", "quit"], tmp, env)
        d = app.wait_dump(1)
        self.assertIn("GtkLabel\tHome WG", d)
        self.assertIn("GtkLabel\tWork: VPN", d)
        self.assertNotIn("GtkLabel\tSAIFI", d)                          # jen VPN, ne Wi-Fi
        d2 = app.wait_dump(2)
        self.assertIn("GtkLabel\tSign in to Work: VPN", d2)             # OpenVPN s heslem: stranka se zepta
        app.wait_exit()
        log = calls(tmp)
        self.assertIn("nmcli connection up uuid-wg", log)
        self.assertIn("nmcli connection modify uuid-ovpn +vpn.data username=anna vpn.user-name anna", log)
        up = [ln for ln in log if ln.startswith("nmcli connection up uuid-ovpn passwd-file ")]
        self.assertEqual(len(up), 1, log)
        self.assertFalse(any("tajne" in ln for ln in log), "the password must never be an argument")
        pw = (tmp / "pwfile.log").read_text().splitlines()
        self.assertEqual(pw, ["vpn.secrets.password:tajne heslo 1", "600"])
        self.assertFalse(Path(up[0].split(" passwd-file ")[1]).exists(), "password file must be removed")

    def test_vpn_asks_password_when_nm_needs_secrets(self):
        """OpenVPN, u ktereho vpn.data heslo neprozradi: NM odmitne (No valid secrets) -> stranka se zepta."""
        tmp, env = make_env()
        app = self.run_app("vpn", ["wait 600", "switch Cert VPN on", "wait 600", "dump", "quit"], tmp, env)
        d = app.wait_dump(1)
        app.wait_exit()
        self.assertIn("nmcli connection up uuid-ovpn2", calls(tmp))
        self.assertIn("GtkLabel\tSign in to Cert VPN", d)
        self.assertFalse(any("Hint:" in ln for ln in d))

    def test_vpn_import_and_remove(self):
        tmp, env = make_env()
        conf = tmp / "home" / "wg0.conf"
        conf.write_text("[Interface]\n")
        self.run_app("vpn", ["wait 500", f"vpn-import {conf}", "wait 400", f"vpn-import {tmp}/notes.txt", "wait 200",
                             "click Remove", "wait 200", "click Really Remove", "wait 400", "quit"], tmp, env).wait_exit()
        log = calls(tmp)
        self.assertIn(f"nmcli connection import type wireguard file {conf}", log)
        # po importu se VPN nezapne sama (ani pri dalsim startu)
        self.assertIn("nmcli connection modify uuid-new connection.autoconnect no", log)
        self.assertIn("nmcli connection down uuid-new", log)
        self.assertFalse(any("notes.txt" in ln for ln in log))
        self.assertIn("nmcli connection delete uuid-wg", log)

    # ---- Proxy ----

    def test_proxy_manual(self):
        tmp, env = make_env()
        app = self.run_app("proxy", ["wait 400", "combo Use a proxy server manual",
                                     "entry Web proxy (HTTP)=bad address", "click Save", "wait 200", "dump",
                                     "entry Web proxy (HTTP)=proxy.firma.cz:3128",
                                     "entry Don't use the proxy for=localhost, *.firma.cz, 10.0.0.0/8",
                                     "click Save", "wait 400", "quit"], tmp, env)
        d = app.wait_dump(1)
        self.assertTrue(any("enter server:port" in ln for ln in d), d)
        app.wait_exit()
        self.assertEqual(gs_get(tmp, env, "org.gnome.system.proxy", "mode"), "'manual'")
        self.assertEqual(gs_get(tmp, env, "org.gnome.system.proxy.http", "host"), "'proxy.firma.cz'")
        self.assertEqual(gs_get(tmp, env, "org.gnome.system.proxy.http", "port"), "3128")
        self.assertEqual(gs_get(tmp, env, "org.gnome.system.proxy.https", "host"), "'proxy.firma.cz'")
        self.assertEqual(gs_get(tmp, env, "org.gnome.system.proxy", "ignore-hosts"),
                         "['localhost', '*.firma.cz', '10.0.0.0/8']")
        lines = (tmp / "config/luxos/proxy.env").read_text().splitlines()
        self.assertIn("http_proxy=http://proxy.firma.cz:3128/", lines)
        self.assertIn("HTTPS_PROXY=http://proxy.firma.cz:3128/", lines)
        self.assertIn("no_proxy=localhost,*.firma.cz,10.0.0.0/8", lines)

    def test_proxy_off_removes_env(self):
        tmp, env = make_env()
        (tmp / "config/luxos").mkdir(parents=True)
        (tmp / "config/luxos/proxy.env").write_text("http_proxy=http://old:1/\n")
        self.run_app("proxy", ["wait 400", "combo Use a proxy server auto", "wait 200", "quit"], tmp, env).wait_exit()
        self.assertEqual(gs_get(tmp, env, "org.gnome.system.proxy", "mode"), "'auto'")
        self.assertFalse((tmp / "config/luxos/proxy.env").exists())


class SessionProxyEnv(unittest.TestCase):
    """luxos-wayland-session nacte jen platne radky proxy.env (zadny prikaz ani jine promenne)."""

    def test_regex(self):
        session = Path(__file__).resolve().parent.parent / "files/bin/luxos-wayland-session"
        line = next(ln for ln in session.read_text().splitlines() if ln.startswith("proxy_re="))
        script = line + '\nwhile IFS= read -r l; do [[ $l =~ $proxy_re ]] && echo "$l"; done'
        good = ["http_proxy=http://proxy.firma.cz:3128/", "no_proxy=localhost,*.local,[::1]",
                "all_proxy=socks5://10.0.0.1:1080"]
        bad = ["http_proxy=x;touch /tmp/p", "PATH=/tmp", "http_proxy=$(id)", "LD_PRELOAD=/x.so", "http_proxy=a b"]
        out = subprocess.run(["bash", "-c", script], input="\n".join(good + bad) + "\n", capture_output=True,
                             text=True).stdout.splitlines()
        self.assertEqual(out, good)


if __name__ == "__main__":
    unittest.main()
