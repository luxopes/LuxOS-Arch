"""Ucet LuxAI: prihlaseny ukazkovy ucet (prehled se spotrebou AI, predvolby) a obrazovka prihlaseni -
proti mistni napodobe serveru LuxAI z testu (luxos-account/tests/mock_luxai.py), nikdy lux-ai.cz."""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _a  # noqa: E402

PW = "demo password 2026"


def mock_server(s):
    sys.path.insert(0, s.src("luxos-account/tests"))
    try:
        from mock_luxai import MockLuxAI
    finally:
        sys.path.pop(0)
    srv = MockLuxAI().start()
    srv.accounts["alex@example.com"] = {
        "password": PW, "displayName": "Alex Morgan", "username": "alex.morgan",
        "settings": {"theme": "light", "aiResponseStyle": "balanced"},
        "usage": {"fastTokens": 412500, "fastLimit": 1000000, "liteTokens": 2350000, "liteLimit": 10000000}}
    s._servers.append(srv.httpd)       # harness server ukonci (shutdown + server_close)
    return srv


def sign_in(srv):
    req = urllib.request.Request(srv.origin + "/api/auth/password/login",
                                 data=json.dumps({"email": "alex@example.com", "password": PW}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def launch(s):
    return _a.run_python(s, "luxos-account/files/luxos-account", paths=("luxos-account/files",),
                         modules=("luxai_account", "luxai_account_gtk", "luxos_i18n", "luxos_avatar"))


def shots(s):
    _a.no_real_avatar(s)
    srv = mock_server(s)
    s.env["LUXAI_ORIGIN"] = srv.origin
    data = sign_in(srv)
    path = _a.demo_account(s, srv.origin, "Alex Morgan", "alex@example.com", "alex.morgan")
    acc = json.load(open(path))
    acc["sessionToken"] = data["sessionToken"]
    acc["user"] = data["user"]
    s.write(".config/luxai/account.json", json.dumps(acc, indent=1), 0o600)

    p = launch(s)
    win = s.window(pid=p.pid, size=(860, 640))
    s.sleep(1.5)
    s.capture("1", win)
    # Predvolby (4. stranka postranniho seznamu)
    s.click(110, 190, win)
    s.sleep(0.6)
    s.capture("2", win)
