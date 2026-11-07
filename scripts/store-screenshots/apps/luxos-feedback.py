"""Zpetna vazba: rozepsany napad a podekovani po odeslani - na mistni falesny server
(LUXAI_ORIGIN), nikdy na lux-ai.cz. Systemove udaje se pred odeslanim vypnou (nic se neodesila ven
a skutecne udaje pocitace se neukazuji)."""
import http.server
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _a  # noqa: E402

MESSAGE = ("It would be great if the Dock could show a small badge with the number of unread "
           "messages for every app, like Mail already does.")


class FakeFeedback(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        body = json.dumps({"ok": True, "id": "FB-2026-1107-4821"}).encode()
        self.send_response(200 if self.path == "/api/feedback" else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def shots(s):
    port = s.serve_http(FakeFeedback)
    s.env["LUXAI_ORIGIN"] = "http://127.0.0.1:%d" % port
    p = _a.run_python(s, "luxos-desktop/files/bin/luxos-feedback",
                      paths=("luxos-account/files",), modules=("luxai_account", "luxos_i18n"))
    win = s.window(pid=p.pid, size=None)
    s.sleep(1.0)
    # karta Napad, text a e-mail (souradnice v okne 580x720 s hlavickou)
    s.click(291, 186, win)
    s.click(290, 330, win)
    s.type(MESSAGE, win)
    s.click(290, 511, win)
    s.type("alex@example.com", win)
    s.click(290, 330, win)
    s.key("ctrl+End", win)
    s.capture("1", win)
    # systemove udaje vypnout, odeslat na falesny server -> podekovani s cislem hlaseni
    s.click(32, 592, win)
    s.click(528, 731, win)
    s.sleep(1.5)
    s.capture("2", win)
