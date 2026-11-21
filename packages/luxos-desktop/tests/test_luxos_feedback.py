#!/usr/bin/env python3
"""Zpetna vazba (luxos-feedback, files/lsl/luxos-feedback.lsl): co se z logu odstrani pred odeslanim, fronta
neodeslanych hlaseni a okno.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_feedback.py -v

Prekladac lslc z PATH (nebo LUXOS_LSLC). Hlaseni jdou jen na mistni falesny server (LUXAI_ORIGIN na 127.0.0.1),
nikdy na lux-ai.cz. Okno ve vlastnim Xvfb, rizene pres luxos_testctl; snimky do LUXOS_TEST_SHOTS.
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
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

TMP = tempfile.mkdtemp(prefix="luxos-feedback-test-")
BIN = {}


def setUpModule():
    BIN["app"] = lsl_app.build("luxos-feedback", TMP)
    # jednotkovy test modulu: zdroje aplikaci a testu v jedne slozce (lslc hleda moduly vedle programu)
    src = os.path.join(TMP, "src")
    os.makedirs(src)
    for d in (lsl_app.LSL_DIR, os.path.join(HERE, "lsl")):
        for name in os.listdir(d):
            if name.endswith(".lsl"):
                shutil.copy(os.path.join(d, name), src)
    lslc = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
    BIN["unit"] = os.path.join(TMP, "luxos-feedback-test")
    r = subprocess.run([lslc, "--target", "linux-x86_64-gnu", "--system-bindings", src,
                        os.path.join(src, "luxos-feedback-test.lsl"), BIN["unit"]], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stdout + r.stderr)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class FakeServer:
    """POST /api/feedback: zaznamena hlavicky a telo, odpovi podle self.reply (status, slovnik)."""

    def __init__(self):
        outer = self
        self.requests = []
        self.reply = (200, {"ok": True, "id": "FB-2026-0001"})

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(body)})
                status, data = outer.reply
                raw = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.origin = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def home_env(root, origin):
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")}
    env.update(HOME=os.path.join(root, "home"), XDG_CONFIG_HOME=os.path.join(root, "config"),
               XDG_DATA_HOME=os.path.join(root, "data"), XDG_CACHE_HOME=os.path.join(root, "cache"),
               XDG_RUNTIME_DIR=os.path.join(root, "run"), LUXAI_ORIGIN=origin, LUXOS_I18N_DIR=lsl_app.I18N,
               LANG="en_US.UTF-8")
    for k in ("HOME", "XDG_RUNTIME_DIR"):
        os.makedirs(env[k], mode=0o700, exist_ok=True)
    return env


class Unit(unittest.TestCase):
    def test_redact_pretty_origin(self):
        r = subprocess.run([BIN["unit"]], capture_output=True, text=True, timeout=60)
        fails = [line for line in r.stdout.splitlines() if not line.startswith("ok ")]
        self.assertEqual((r.returncode, fails), (0, []), r.stderr)
        self.assertGreater(len(r.stdout.splitlines()), 20)


class Outbox(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=TMP)
        self.server = FakeServer()
        self.addCleanup(self.server.close)
        self.env = home_env(self.root, self.server.origin)
        self.box = os.path.join(self.env["XDG_DATA_HOME"], "luxos", "feedback-outbox")
        os.makedirs(self.box)

    def report(self, name, payload):
        path = os.path.join(self.box, name)
        with open(path, "w") as f:
            json.dump(payload, f)
        return path

    def flush(self):
        r = subprocess.run([BIN["app"], "--send-outbox"], env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return int(r.stdout.strip())

    def test_sent_reports_are_removed_with_cookie(self):
        os.makedirs(os.path.join(self.env["XDG_CONFIG_HOME"], "luxai"))
        with open(os.path.join(self.env["XDG_CONFIG_HOME"], "luxai", "account.json"), "w") as f:
            json.dump({"version": 1, "origin": self.server.origin, "sessionToken": "tok-123", "user": {}}, f)
        a = self.report("20261121-1-a.json", {"kind": "bug", "message": "ěščř first report"})
        b = self.report("20261121-2-b.json", {"kind": "idea", "message": "second"})
        self.report("note.txt", {})
        self.assertEqual(self.flush(), 2)
        self.assertFalse(os.path.exists(a) or os.path.exists(b))
        self.assertEqual([q["body"]["message"] for q in self.server.requests], ["ěščř first report", "second"])
        h = self.server.requests[0]["headers"]
        self.assertEqual(self.server.requests[0]["path"], "/api/feedback")
        self.assertEqual((h["Cookie"], h["X-Lux-Client"], h["Content-Type"]),
                         ("lux_account_session=tok-123", "luxos", "application/json"))

    def test_anonymous_without_account(self):
        self.report("1.json", {"message": "x"})
        self.assertEqual(self.flush(), 1)
        self.assertNotIn("Cookie", self.server.requests[0]["headers"])

    def test_expired_sign_in_keeps_report(self):
        path = self.report("1.json", {"message": "x"})
        for status, kept in ((401, True), (403, True), (429, True), (400, False)):
            self.server.reply = (status, {"error": "unauthorized"})
            self.assertEqual(self.flush(), 0)
            self.assertEqual(os.path.exists(path), kept, status)
        self.assertTrue(os.path.exists(path + ".rejected"))

    def test_server_error_retries_once_and_keeps(self):
        path = self.report("1.json", {"message": "x"})
        self.server.reply = (503, {})
        self.assertEqual(self.flush(), 0)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(len(self.server.requests), 2)

    def test_broken_file_set_aside(self):
        path = os.path.join(self.box, "1.json")
        with open(path, "w") as f:
            f.write("{not json")
        self.assertEqual(self.flush(), 0)
        self.assertTrue(os.path.exists(path + ".bad"))

    def test_offline_keeps_report(self):
        """Odmitnute spojeni (zadna sit): 4 pokusy a jeste jedno opakovani, hlaseni zustane."""
        path = self.report("1.json", {"message": "x"})
        self.env["LUXAI_ORIGIN"] = "http://127.0.0.1:9"
        start = time.monotonic()
        self.assertEqual(self.flush(), 0)
        self.assertTrue(os.path.exists(path))
        self.assertGreater(time.monotonic() - start, 15)


class Window(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.x = lsl_app.Xvfb("1366x768")

    @classmethod
    def tearDownClass(cls):
        cls.x.stop()

    def setUp(self):
        self.root = tempfile.mkdtemp(dir=TMP)
        self.server = FakeServer()
        self.addCleanup(self.server.close)
        self.env = home_env(self.root, self.server.origin)
        self.env.update(DISPLAY=self.x.display, GTK_THEME="Adwaita")
        self.app = None

    def tearDown(self):
        if self.app:
            self.app.stop()

    def start(self, **env):
        self.app = lsl_app.App([BIN["app"]], dict(self.env, **env))
        self.assertTrue(self.app.wait(lambda: self.app.dump()), self.app.stderr())

    def st(self):
        return json.loads(self.app.ask("state", "state"))

    def named(self, name):
        w = lsl_app.find(self.app.dump(), name=name)
        return w and w["text"]

    def shot(self, name):
        out = os.environ.get("LUXOS_TEST_SHOTS")
        if out:
            os.makedirs(out, exist_ok=True)
            time.sleep(0.4)
            lsl_app.shot(self.x.display, os.path.join(out, name + ".png"))

    def test_form_validation_and_send(self):
        self.start()
        d = self.app.dump()
        self.assertEqual([(w["title"], w["close_button"]) for w in d], [("Feedback", True)])
        self.assertIn("Help us improve LuxOS", lsl_app.texts(d))
        self.assertFalse(self.st()["send"])
        self.assertEqual(self.named("counter"), "At least 10 characters")
        self.assertTrue(lsl_app.find(d, name="placeholder")["vis"])
        self.assertIn("Steps to reproduce", self.named("placeholder"))
        self.app.ask("kind idea")
        self.assertIn("How would it help you", self.named("placeholder"))
        self.app.ask("type The Dock could show badges for unread messages.")
        self.assertTrue(self.st()["send"])
        self.assertEqual(self.named("counter"), "47 / 8000")
        self.assertFalse(lsl_app.find(self.app.dump(), name="placeholder")["vis"])
        self.app.ask("entry not-an-email")
        self.assertFalse(self.st()["send"])
        self.app.ask("entry alex@example.com")
        self.assertTrue(self.st()["send"])
        # systemove udaje se nactou na pozadi a okno ukazuje presne to, co se odesle
        self.assertTrue(self.app.wait(lambda: self.st()["system"], 30))
        info = json.loads(self.st()["sys_text"])
        self.assertIn("kernel", info)
        self.assertNotIn(self.env["HOME"], self.st()["sys_text"])
        self.shot("feedback-form")
        self.app.ask("click Send")
        self.assertTrue(self.app.wait(lambda: self.st()["page"] == "done", 30), self.app.stderr())
        self.assertEqual(self.named("done-title"), "Thank you for your feedback!")
        self.assertEqual(self.named("done-id"), "Report ID: FB-2026-0001")
        self.shot("feedback-done")
        body = self.server.requests[-1]["body"]
        self.assertEqual((body["kind"], body["message"], body["contact"], body["app"]),
                         ("idea", "The Dock could show badges for unread messages.", "alex@example.com", "luxos-feedback"))
        self.assertEqual(body["system"], info)
        self.assertIn("version", body)
        self.assertNotIn("screenshot", body)
        # text hlaseni nesmi zustat v docasnem souboru
        self.assertEqual([n for n in os.listdir(self.env["XDG_RUNTIME_DIR"]) if n.startswith("luxos-feedback")], [])
        self.app.ask("click Send Another")
        self.assertEqual(self.st()["page"], "form")
        self.assertEqual(self.named("counter"), "At least 10 characters")
        self.app.ask("click Close")
        self.assertEqual(self.app.proc.wait(10), 0)

    def test_without_system_info_and_rejected(self):
        self.start()
        self.server.reply = (429, {"error": "rate"})
        self.app.ask("sysinfo 0")
        self.app.ask("type Something is broken here.")
        self.app.ask("click Send")
        self.assertTrue(self.app.wait(lambda: "many reports" in (self.named("status") or ""), 30), self.app.stderr())
        self.assertEqual(self.st()["page"], "form")
        self.assertTrue(lsl_app.find(self.app.dump(), text="Try Again", kind="GtkButton"))
        self.assertTrue(self.st()["send"])
        self.assertNotIn("system", self.server.requests[-1]["body"])
        self.assertEqual(os.listdir(os.path.join(self.env["XDG_DATA_HOME"], "luxos", "feedback-outbox"))
                         if os.path.isdir(os.path.join(self.env["XDG_DATA_HOME"], "luxos", "feedback-outbox")) else [], [])

    def test_server_down_saves_for_later_and_sends_on_next_start(self):
        self.start()
        self.server.reply = (502, {})
        self.app.ask("sysinfo 0")
        self.app.ask("type Report while the server is down.")
        self.app.ask("click Send")
        self.assertTrue(self.app.wait(lambda: self.st()["page"] == "done", 40), self.app.stderr())
        self.assertEqual(self.named("done-title"), "Saved for later")
        self.assertFalse(lsl_app.find(self.app.dump(), name="done-id")["vis"])
        box = os.path.join(self.env["XDG_DATA_HOME"], "luxos", "feedback-outbox")
        files = os.listdir(box)
        self.assertEqual(len(files), 1)
        self.assertEqual(oct(os.stat(box).st_mode & 0o777), "0o700")
        self.assertEqual(oct(os.stat(os.path.join(box, files[0])).st_mode & 0o777), "0o600")
        self.app.stop()
        # dalsi spusteni s funkcnim serverem odesle ulozene hlaseni a rekne to
        self.server.reply = (200, {"id": "FB-2"})
        self.start()
        self.assertTrue(self.app.wait(lambda: (lsl_app.find(self.app.dump(), name="info") or {}).get("vis"), 20))
        self.assertEqual(self.named("info"), "1 saved report(s) from earlier have been sent. Thank you!")
        self.assertEqual(os.listdir(box), [])
        self.assertEqual(self.server.requests[-1]["body"]["message"], "Report while the server is down.")

    def test_screenshot_attached(self):
        self.start()
        self.app.ask("sysinfo 0")
        self.app.ask("switch 1")
        self.assertTrue(self.app.wait(lambda: self.st()["shot"] > 0, 10), self.app.stderr())
        self.assertTrue(self.app.wait(lambda: self.app.dump(), 5))
        self.assertTrue(lsl_app.find(self.app.dump(), text="Take Again", kind="GtkButton")["vis"])
        self.app.ask("type Screenshot of the problem attached.")
        self.app.ask("click Send")
        self.assertTrue(self.app.wait(lambda: self.st()["page"] == "done", 30))
        shot = self.server.requests[-1]["body"]["screenshot"]
        self.assertTrue(shot.startswith("data:image/jpeg;base64,"))
        jpeg = base64.b64decode(shot.split(",", 1)[1])
        self.assertEqual(jpeg[:3], b"\xff\xd8\xff")
        self.assertLess(len(shot), 1400000)

    def test_czech_and_fits_small_screen(self):
        self.start(LANG="cs_CZ.UTF-8")
        d = self.app.dump()
        self.assertEqual(d[0]["title"], "Zpětná vazba")
        self.assertIn("Pomozte nám vylepšit LuxOS", lsl_app.texts(d))
        size = json.loads(self.app.ask("size", "size"))
        self.assertLessEqual(size[1], 768 - 16)
        self.assertGreaterEqual(size[0], 480)
        self.shot("feedback-cs")

    def test_pss(self):
        """PSS okna po nacteni systemovych udaju (srovnani s Pythonem v technicke zprave)."""
        self.start()
        self.assertTrue(self.app.wait(lambda: self.st()["system"], 30))
        time.sleep(1)
        print("\n  luxos-feedback PSS %d KB" % self.app.pss_kb())


if __name__ == "__main__":
    unittest.main()
