#!/usr/bin/env python3
"""LuxOS - Novinky (files/lsl/luxos-news.lsl, luxos_news.lsl): oznameni od vyvojaru LuxOS.

    xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_luxos_news.py -v

Kanal z mistniho HTTP serveru (LUXOS_NEWS_URL na 127.0.0.1), oznameni do falesne sluzby
org.freedesktop.Notifications na vlastni sbernici bez aktivace sluzeb, docasny domov.
  - vyvojar: new (odsazeny JSON, cestina, odmitnuti duplicity a spatneho odkazu), validate (chyby, kod 1),
  - kontrola: ohlasi jen platne nove novinky (ne stare pri prvnim spusteni, budouci, prosle, neplatne),
    text v jazyce uzivatele a escapovany, hinty x-luxos-keep a desktop-entry, podruhe nic,
    vypnute upozornovani, prilis velky kanal,
  - klik na oznameni otevre okno, kontrola skonci po zavreni vsech svych oznameni,
  - okno: zobrazene novinky (stitek Dulezite), otevrene okno = prectene, vejde se na 1366x768,
  - 1.0.3 bez skla: aplikace nenacita luxos_glass a vsechny jeji moduly jsou v balicku.
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
import datetime
import glob
import re
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
LSL_DIR = os.path.join(HERE, "..", "files", "lsl")
SRC = os.path.join(LSL_DIR, "luxos-news.lsl")
I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
BIN = tempfile.mkdtemp(prefix="luxos-news-bin-")
UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")


def build():
    if not LSLC:
        return False
    r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", LSL_DIR, SRC, os.path.join(BIN, "luxos-news")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(r.stderr + r.stdout)
    return True


BUILT = build()
NEWS = os.path.join(BIN, "luxos-news")

BUS_CONF = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig><type>session</type><listen>unix:tmpdir=%s</listen><auth>EXTERNAL</auth>
<policy context="default"><allow send_destination="*" eavesdrop="true"/><allow eavesdrop="true"/><allow own="*"/></policy>
</busconfig>
"""

FAKE_NOTIFYD = r'''
import json, sys
from gi.repository import Gio, GLib
log = sys.argv[1]
XML = """<node><interface name='org.freedesktop.Notifications'>
<method name='Notify'><arg type='s' direction='in'/><arg type='u' direction='in'/><arg type='s' direction='in'/>
<arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='as' direction='in'/>
<arg type='a{sv}' direction='in'/><arg type='i' direction='in'/><arg type='u' direction='out'/></method>
<method name='TestInvoke'><arg type='u' direction='in'/><arg type='s' direction='in'/></method>
<method name='TestClose'><arg type='u' direction='in'/></method>
<signal name='ActionInvoked'><arg type='u'/><arg type='s'/></signal>
<signal name='NotificationClosed'><arg type='u'/><arg type='u'/></signal>
</interface></node>"""
n = [0]
P = ("/org/freedesktop/Notifications", "org.freedesktop.Notifications")
def closed(conn, nid, reason):
    conn.emit_signal(None, P[0], P[1], "NotificationClosed", GLib.Variant("(uu)", (nid, reason)))
    return False
def call(conn, sender, path, iface, method, params, inv):
    if method == "TestInvoke":
        conn.emit_signal(None, P[0], P[1], "ActionInvoked", params)
        inv.return_value(None)
        return
    if method == "TestClose":
        closed(conn, params.unpack()[0], 2)
        inv.return_value(None)
        return
    app, rep, icon, summary, body, actions, hints, expire = params.unpack()
    n[0] += 1
    with open(log, "a") as f:
        f.write(json.dumps({"id": n[0], "app": app, "icon": icon, "summary": summary, "body": body, "actions": actions,
                            "hints": {k: str(v) for k, v in hints.items()}, "expire": expire}) + "\n")
    inv.return_value(GLib.Variant("(u)", (n[0],)))
    if expire != 0:
        GLib.timeout_add(300, closed, conn, n[0], 1)       # vyprselo
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
bus.register_object("/org/freedesktop/Notifications", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call, None, None)
Gio.bus_own_name_on_connection(bus, "org.freedesktop.Notifications", 0, None, None)
print("ready", flush=True)
GLib.MainLoop().run()
'''


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def day(offset):
    return (datetime.date.today() + datetime.timedelta(days=offset)).isoformat()


def feed():
    return {"version": 1, "announcements": [
        {"id": "today-release", "date": day(0), "level": "important",
         "title": {"en": "LuxOS 1.2 is out", "cs": "Vyšel LuxOS 1.2"},
         "body": {"en": "Read <b>more</b>", "cs": "Čtěte <b>víc</b> & dál"}, "url": "https://luxos.lux-ai.cz/"},
        {"id": "maintenance", "date": day(-2), "until": day(5), "title": "Server maintenance"},
        {"id": "old-news", "date": day(-60), "title": "Old news"},
        {"id": "future", "date": day(3), "title": "Not yet"},
        {"id": "expired", "date": day(-10), "until": day(-1), "title": "Gone"},
        {"id": "Bad ID", "date": day(0), "title": "Invalid"},
        {"id": "bad-url", "date": day(0), "title": "Bad link", "url": "http://insecure.example"},
    ]}


class Server:
    def __init__(self):
        self.body = b"{}"
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if server.body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(server.body)))
                self.end_headers()
                self.wfile.write(server.body)

            def log_message(self, *a):
                pass
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d/announcements.json" % self.httpd.server_address[1]

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@unittest.skipUnless(BUILT, "needs lslc with the linux-x86_64-gnu target")
class Developer(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxos-news-dev-")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.env = dict(os.environ, HOME=self.t, LANG="C")

    def run_news(self, *args):
        return subprocess.run([NEWS, *args], env=self.env, capture_output=True, text=True, timeout=20, cwd=self.t)

    def test_new_writes_readable_feed_and_validate_accepts_it(self):
        path = os.path.join(self.t, "feed.json")
        r = self.run_news("new", path, "--title", "LuxOS 1.2 is out", "--title-cs", "Vyšel LuxOS 1.2",
                          "--body", "Hello", "--url", "https://luxos.lux-ai.cz/", "--level", "important",
                          "--date", "2026-12-01")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2026-12-01-luxos-1-2-is-out", r.stdout)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn('\n  "announcements": [\n', text, "odsazeny JSON pro lidi")
        data = json.loads(text)
        self.assertEqual(data["announcements"][0]["title"], {"en": "LuxOS 1.2 is out", "cs": "Vyšel LuxOS 1.2"})
        r = self.run_news("validate", path)
        self.assertEqual(r.returncode, 0, r.stderr)
        # stejne id znovu, spatny odkaz: odmitnuto, soubor beze zmeny
        self.assertEqual(self.run_news("new", path, "--title", "LuxOS 1.2 is out", "--date", "2026-12-01").returncode, 1)
        self.assertEqual(self.run_news("new", path, "--title", "X", "--url", "http://a").returncode, 1)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), text)
        self.assertEqual(self.run_news("new", path, "--body", "no title").returncode, 2)

    def test_validate_reports_every_problem(self):
        path = os.path.join(self.t, "bad.json")
        with open(path, "w") as f:
            json.dump({"version": 1, "announcements": [
                {"id": "Spatne ID", "date": "2026-13-01", "title": "", "url": "http://x", "level": "urgent"},
                {"id": "ok", "date": "2026-01-01", "title": "x" * 121}]}, f)
        r = self.run_news("validate", path)
        self.assertEqual(r.returncode, 1)
        for part in ('"id"', '"date"', '"title"', '"url"', '"level"', "(ok)"):
            self.assertIn(part, r.stderr)
        # odkaz s ridicim znakem nebo mezerou (jen https://, cely retezec jde prohlizeci)
        for url in ("https://a.example/\nx", "https://a.example/ x", "https://a.example/\tx", "javascript:alert(1)"):
            with open(path, "w") as f:
                json.dump({"version": 1, "announcements": [{"id": "u", "date": "2026-01-01", "title": "x", "url": url}]}, f)
            r = self.run_news("validate", path)
            self.assertEqual(r.returncode, 1, url)
            self.assertIn('"url"', r.stderr)
        with open(path, "w") as f:
            f.write("{nejson")
        self.assertEqual(self.run_news("validate", path).returncode, 1)
        with open(path, "w") as f:
            json.dump({"version": 2, "announcements": []}, f)
        self.assertEqual(self.run_news("validate", path).returncode, 1)


@unittest.skipUnless(BUILT, "needs lslc with the linux-x86_64-gnu target")
class Check(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxos-news-")
        self.addCleanup(shutil.rmtree, self.t, True)
        run = os.path.join(self.t, "run")
        os.makedirs(run, mode=0o700)
        self.procs = []
        self.server = Server()
        self.addCleanup(self.server.stop)
        self.log = os.path.join(self.t, "notify.log")
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("DBUS_", "XDG_", "SESSION_MANAGER", "XAUTHORITY"))}
        env.update(HOME=self.t, XDG_RUNTIME_DIR=run, LANG="cs_CZ.UTF-8", LUXOS_I18N_DIR=I18N,
                   LUXOS_NEWS_URL=self.server.url, LUXOS_NEWS_WAIT="3")
        conf = os.path.join(self.t, "bus.conf")
        with open(conf, "w") as f:
            f.write(BUS_CONF % run)
        bus = subprocess.Popen(["dbus-daemon", "--config-file", conf, "--nofork", "--print-address"], env=env,
                               stdout=subprocess.PIPE, text=True)
        self.procs.append(bus)
        env["DBUS_SESSION_BUS_ADDRESS"] = bus.stdout.readline().strip()
        self.env = env
        script = os.path.join(self.t, "notifyd.py")
        with open(script, "w") as f:
            f.write(FAKE_NOTIFYD)
        nd = subprocess.Popen([sys.executable, script, self.log], env=env, stdout=subprocess.PIPE, text=True)
        self.procs.append(nd)
        self.assertEqual(nd.stdout.readline().strip(), "ready")

    def tearDown(self):
        for p in reversed(self.procs):
            p.terminate()
            p.wait(timeout=10)
            p.stdout.close()

    def serve(self, data):
        self.server.body = json.dumps(data).encode() if not isinstance(data, bytes) else data

    def check(self):
        r = subprocess.run([NEWS, "--check"], env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)

    def fake_notifyd(self, method, values, signature):
        from gi.repository import Gio, GLib
        conn = Gio.DBusConnection.new_for_address_sync(
            self.env["DBUS_SESSION_BUS_ADDRESS"],
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        try:
            conn.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                           "org.freedesktop.Notifications", method, GLib.Variant(signature, values), None,
                           Gio.DBusCallFlags.NONE, 5000, None)
        finally:
            conn.close_sync(None)

    def notes(self):
        try:
            with open(self.log) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def state(self):
        with open(os.path.join(self.t, ".local", "state", "luxos", "news.json")) as f:
            return json.load(f)

    def test_announces_only_valid_new_items_once(self):
        self.serve(feed())
        self.check()
        notes = self.notes()
        self.assertEqual(sorted(n["summary"] for n in notes), ["Server maintenance", "Vyšel LuxOS 1.2"])
        release = [n for n in notes if n["summary"] == "Vyšel LuxOS 1.2"][0]
        self.assertEqual(release["body"], "Čtěte &lt;b&gt;víc&lt;/b&gt; &amp; dál", "jazyk uzivatele, bez znacek")
        self.assertEqual(release["hints"].get("x-luxos-keep"), "True")
        self.assertEqual(release["hints"].get("desktop-entry"), "luxos-news")
        self.assertEqual(release["expire"], 0, "dulezite nezmizi samo")
        self.assertEqual(release["actions"], ["default", "Otevřít"])
        # stara novinka (pred prvnim spustenim) jen v aplikaci
        self.assertIn("old-news", self.state()["notified"])
        # podruhe nic noveho
        self.check()
        self.assertEqual(len(self.notes()), 2)
        r = subprocess.run([NEWS, "--list"], env=self.env, capture_output=True, text=True, timeout=20)
        ids = [i["id"] for i in json.loads(r.stdout)]
        self.assertEqual(ids, ["today-release", "maintenance", "old-news"], "platne dnes, nejnovejsi prvni")

    def test_click_opens_window_and_check_ends_when_closed(self):
        f = feed()
        f["announcements"] = f["announcements"][:1]          # jen dulezita: nezmizi sama
        self.serve(f)
        ui = os.path.join(self.t, "ui.log")
        env = dict(self.env, LUXOS_NEWS_WAIT="60", LUXOS_NEWS_TEST_LOG=ui)
        env.pop("DISPLAY", None)                              # okno po kliknuti se tu jen pokusi otevrit
        p = subprocess.Popen([NEWS, "--check"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: p.poll() is None and (p.terminate(), p.wait(10)))
        end = time.time() + 15
        while time.time() < end and not self.notes():
            time.sleep(0.1)
        nid = self.notes()[0]["id"]
        time.sleep(0.5)
        self.assertIsNone(p.poll(), "ceka na klik, dokud je oznameni videt")
        self.fake_notifyd("TestInvoke", (nid + 100, "default"), "(us)")   # cizi oznameni
        self.fake_notifyd("TestInvoke", (nid, "default"), "(us)")
        end = time.time() + 10
        while time.time() < end and "open %d" % nid not in read(ui):
            time.sleep(0.1)
        self.assertEqual([line for line in read(ui).splitlines() if line.startswith("open")], ["open %d" % nid])
        self.fake_notifyd("TestClose", (nid,), "(u)")
        self.assertEqual(p.wait(timeout=10), 0)

    def test_check_waits_at_most_luxos_news_wait(self):
        f = feed()
        f["announcements"] = f["announcements"][:1]
        self.serve(f)
        start = time.time()
        self.check()                                          # LUXOS_NEWS_WAIT=3
        self.assertLess(time.time() - start, 15)
        self.assertEqual(len(self.notes()), 1)

    def test_new_item_later_and_limit(self):
        self.serve(feed())
        self.check()
        f = feed()
        for i in range(5):
            f["announcements"].insert(0, {"id": "later-%d" % i, "date": day(0), "title": "Later %d" % i})
        self.serve(f)
        self.check()
        self.assertEqual(len(self.notes()), 2 + 3, "nejvys 3 oznameni za kontrolu")
        self.check()
        self.assertEqual(len(self.notes()), 2 + 5, "zbytek pri pristi kontrole")

    def test_unpublished_feed_is_no_news(self):
        self.server.body = None
        r = subprocess.run([NEWS, "--fetch"], env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "0"), "404 = zatim zadne novinky, ne chyba")
        self.check()
        self.assertEqual(self.notes(), [])

    def test_disabled_and_broken_feeds(self):
        state_dir = os.path.join(self.t, ".local", "state", "luxos")
        os.makedirs(state_dir)
        with open(os.path.join(state_dir, "news.json"), "w") as f:
            json.dump({"enabled": False}, f)
        self.serve(feed())
        self.check()
        self.assertEqual(self.notes(), [], "upozornovani vypnute")
        os.remove(os.path.join(state_dir, "news.json"))
        self.serve(b"{" + b" " * 300000 + b"}")
        self.check()
        self.serve({"version": 2, "announcements": feed()["announcements"]})
        self.check()
        self.serve(b"not json")
        self.check()
        self.assertEqual(self.notes(), [], "prilis velky, jina verze, neplatny JSON: nic")
        self.assertFalse(os.path.exists(os.path.join(self.t, ".cache", "luxos", "news.json")))

    @unittest.skipUnless(UNDER_XVFB, "GUI only under xvfb-run (never on a real display)")
    def test_window_lists_news_and_marks_read(self):
        self.serve(feed())
        self.check()
        ui = os.path.join(self.t, "ui.log")
        env = dict(self.env, LUXOS_NEWS_TEST_LOG=ui, DISPLAY=os.environ["DISPLAY"], NO_AT_BRIDGE="1")
        for round_ in (1, 2):
            open(ui, "w").close()
            p = subprocess.Popen([NEWS], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            end = time.time() + 15
            while time.time() < end and "fetched" not in read(ui):
                time.sleep(0.2)
            p.terminate()
            p.wait(timeout=10)
            lines = read(ui).splitlines()
            items = [line for line in lines if line.startswith("item ")]
            self.assertIn("shown", lines)
            self.assertIn("fetched 0", lines, lines)
            want = "unread" if round_ == 1 else "read"
            self.assertIn("item today-release important %s Vyšel LuxOS 1.2" % want, items, items)
            self.assertIn("item maintenance info %s Server maintenance" % want, items, items)
            self.assertNotIn("item today-release important %s Vyšel LuxOS 1.2" % ("read" if round_ == 1 else "unread"),
                             items, "zvyrazneni se behem otevreni okna nemeni")
            self.assertFalse([i for i in items if "future" in i or "expired" in i or "Bad" in i], items)
            size = [line for line in lines if line.startswith("size ")]
            self.assertTrue(size, lines)
            w, h = (int(v) for v in size[0].split()[1].split("x"))
            # 1366x768: lista nahore (28 px), horni lista okna a Dock - obsah okna nejvys 680 px
            self.assertLessEqual(w, 1366)
            self.assertLessEqual(h, 680)


class Release103(unittest.TestCase):
    """1.0.3 nesmi obsahovat sklo (luxos_glass z nedokonceneho vzhledu)."""

    def loads(self, path):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        mods = []
        for m in re.finditer(r"^load (.+)$", text, re.M):
            for part in m.group(1).split(","):
                mods.append(part.split(" as ")[0].strip())
        return text, mods

    def test_no_glass_dependency(self):
        for name in ("luxos-news.lsl", "luxos_news.lsl"):
            text, mods = self.loads(os.path.join(LSL_DIR, name))
            self.assertNotIn("luxos_glass", mods, name)
            self.assertNotIn("glass.", text, name)

    def test_every_luxos_module_is_in_the_package(self):
        have = {os.path.basename(p)[:-4] for p in glob.glob(os.path.join(LSL_DIR, "*.lsl"))}
        for name in ("luxos-news.lsl", "luxos_news.lsl"):
            for mod in self.loads(os.path.join(LSL_DIR, name))[1]:
                if mod.startswith("luxos"):
                    self.assertIn(mod, have, name)


if __name__ == "__main__":
    unittest.main()
