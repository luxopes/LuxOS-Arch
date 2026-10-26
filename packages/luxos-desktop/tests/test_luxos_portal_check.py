#!/usr/bin/env python3
"""luxos-portal-check: portal se pozna i kdyz systemove DNS nefunguje (Tailscale / VPN DNS).

    python3 packages/luxos-desktop/tests/test_luxos_portal_check.py

Falesny DNS server (UDP na localhostu) a falesna sit (HTTP na localhostu); zadna skutecna sit.
"""
import os
import socket
import struct
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "files", "bin", "luxos-portal-check")


class FakeDNS(threading.Thread):
    """Odpovida na dotazy A: jmena ze slovniku -> IP, ostatni bez odpovedi (NXDOMAIN)."""

    def __init__(self, names):
        super().__init__(daemon=True)
        self.names = names
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.queries = []

    def run(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(512)
            except OSError:
                return
            pos, labels = 12, []
            while data[pos]:
                labels.append(data[pos + 1:pos + 1 + data[pos]].decode())
                pos += data[pos] + 1
            name = ".".join(labels)
            self.queries.append(name)
            question = data[12:pos + 5]
            ip = self.names.get(name)
            flags = 0x8180 if ip else 0x8183
            resp = data[:2] + struct.pack(">HHHHH", flags, 1, 1 if ip else 0, 0, 0) + question
            if ip:
                # CNAME navic pred A (portal.test -> CNAME), ukazatel na otazku
                resp += struct.pack(">HHHIH", 0xC00C, 1, 1, 60, 4) + socket.inet_aton(ip)
            self.sock.sendto(resp, addr)

    def close(self):
        self.sock.close()


def http_server(handler_body):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            handler_body(self)

        def log_message(self, *_a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class PortalCheck(unittest.TestCase):
    def run_check(self, dns_names, handler, dns_alive=True):
        dns = FakeDNS(dns_names)
        dns.start()
        srv = http_server(handler)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.addCleanup(dns.close)
        servers = "127.0.0.1:%d" % dns.port if dns_alive else "127.0.0.1:9"
        env = dict(os.environ, LUXOS_PORTAL_DNS=servers, LUXOS_PORTAL_URI="http://check.test/nm-check.txt",
                   LUXOS_PORTAL_HTTP_PORT=str(srv.server_address[1]))
        out = subprocess.run(["python3", "-I", SCRIPT], env=env, capture_output=True, text=True, timeout=30)
        self.dns = dns
        return out.stdout.strip()

    def test_online(self):
        def h(req):
            self.assertEqual(req.headers["Host"], "check.test")
            req.send_response(200)
            req.end_headers()
            req.wfile.write(b"NetworkManager is online\n")
        self.assertEqual(self.run_check({"check.test": "127.0.0.1"}, h), "online")

    def test_redirect_portal_with_login_host_ip(self):
        def h(req):
            req.send_response(302)
            req.send_header("Location", "http://login.portal.test/guest?orig=x")
            req.end_headers()
        out = self.run_check({"check.test": "127.0.0.1", "login.portal.test": "127.0.0.5"}, h)
        self.assertEqual(out, "portal http://login.portal.test/guest?orig=x 127.0.0.5")

    def test_relative_redirect(self):
        def h(req):
            req.send_response(307)
            req.send_header("Location", "/login")
            req.end_headers()
        out = self.run_check({"check.test": "127.0.0.1"}, h)
        self.assertEqual(out, "portal http://check.test/login 127.0.0.1")

    def test_login_page_without_redirect(self):
        def h(req):
            req.send_response(200)
            req.end_headers()
            req.wfile.write(b'<html><meta http-equiv="refresh" content="0; url=http://10.5.0.2:8002/index.php?zone=guest"></html>')
        out = self.run_check({"check.test": "127.0.0.1"}, h)
        self.assertEqual(out, "portal http://10.5.0.2:8002/index.php?zone=guest 10.5.0.2")

    def test_dns_dead_means_none(self):
        def h(req):
            req.send_response(200)
            req.end_headers()
        self.assertEqual(self.run_check({"check.test": "127.0.0.1"}, h, dns_alive=False), "none")

    def test_name_not_resolved_means_none(self):
        def h(req):
            req.send_response(200)
            req.end_headers()
        self.assertEqual(self.run_check({}, h), "none")
        self.assertIn("check.test", self.dns.queries)


if __name__ == "__main__":
    unittest.main()
