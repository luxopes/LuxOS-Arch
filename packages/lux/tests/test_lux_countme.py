#!/usr/bin/env python3
"""Testy lux_countme.py - anonymni tydenni pocitani instalaci (tyden, stari, vypnuti, presne parametry
a hlavicky, nikdy neblokuje: pomaly server, bez site)."""
import calendar
import http.server
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "..")
sys.path.insert(0, PKG)
sys.path.insert(0, os.path.join(PKG, "..", "lux-engine"))

import lux_countme as cm  # noqa: E402
import lux_config  # noqa: E402

DAY = 86400


def utc(y, m, d, hh=0, mm=0, ss=0):
    return calendar.timegm((y, m, d, hh, mm, ss, 0, 0, 0))


class Recorder(http.server.BaseHTTPRequestHandler):
    """Zaznamena presne prijaty pozadavek (radek + hlavicky v poradi) a odpovi 204."""
    seen = []
    status = 204

    def do_GET(self):
        Recorder.seen.append({"line": self.requestline, "path": self.path,
                              "headers": [(k, v) for k, v in self.headers.items()],
                              "raw": self.raw_requestline + bytes(self.headers)})
        self.send_response(Recorder.status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


def server(handler):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class SlowServer:
    """Prijme spojeni a nic neodpovi (zasekly server)."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.conns = []
        self.stop = False
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while not self.stop:
            try:
                c, _a = self.sock.accept()
                self.conns.append(c)
            except OSError:
                return

    def close(self):
        self.stop = True
        for c in self.conns:
            c.close()
        self.sock.close()


class Base(unittest.TestCase):
    NOW = utc(2026, 11, 7, 12)            # sobota, 2026-W45

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="lux-countme-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(self.p("etc/lux"))
        os.makedirs(self.p("var/lib/lux"))
        os.makedirs(self.p("usr/lib/luxos"))
        shutil.copy(os.path.join(PKG, "..", "lux-engine", "lux.conf"), self.p("etc/lux/lux.conf"))
        self.write("etc/lux/mirrorlist", "https://mirror.example/$repo/os/$arch\n")
        self.write("usr/lib/luxos/version", "# LuxOS\nVERSION=1.0.0\nCODENAME=Sirius\n")
        self.state = self.p("var/lib/lux/countme")
        self.lock = self.p("var/lib/lux/countme.lock")
        cm._THREAD = None
        self.addCleanup(setattr, cm, "_THREAD", None)
        self.sent = []

    def p(self, rel):
        return os.path.join(self.root, rel)

    def write(self, rel, text):
        os.makedirs(os.path.dirname(self.p(rel)), exist_ok=True)
        with open(self.p(rel), "w", encoding="utf-8") as f:
            f.write(text)

    def kw(self, **extra):
        d = {"root": self.root, "euid": 0, "state_path": self.state}
        d.update(extra)
        return d

    def sender(self, params):
        self.sent.append(list(params))
        return True

    def run_once(self, now, sender=None, **extra):
        return cm.run_once(now=now, lock_path=self.lock, sender=sender or self.sender, **self.kw(**extra))


class WeekAndAge(unittest.TestCase):
    def test_iso_week(self):
        self.assertEqual(cm.iso_week(utc(2026, 11, 2)), "2026-W45")              # pondeli
        self.assertEqual(cm.iso_week(utc(2026, 11, 8, 23, 59, 59)), "2026-W45")  # nedele vecer UTC
        self.assertEqual(cm.iso_week(utc(2026, 11, 9)), "2026-W46")
        self.assertEqual(cm.iso_week(utc(2026, 12, 28)), "2026-W53")
        self.assertEqual(cm.iso_week(utc(2027, 1, 1)), "2026-W53")               # rok podle ISO
        self.assertEqual(cm.iso_week(utc(2027, 1, 4)), "2027-W01")
        self.assertEqual(cm.iso_week(utc(2025, 12, 29)), "2026-W01")

    def test_age_buckets(self):
        now = utc(2026, 11, 7)
        for days, bucket in ((0, 1), (6.9, 1), (7, 2), (29.9, 2), (30, 3), (181.9, 3), (182, 4), (900, 4)):
            self.assertEqual(cm.age_bucket(now - days * DAY, now), bucket, days)
        self.assertEqual(cm.age_bucket(now + 3 * DAY, now), 1)    # hodiny posunute dozadu

    def test_query_is_exactly_four_params(self):
        q = cm.query([("v", "1.0.0"), ("arch", "x86_64"), ("ch", "stable"), ("age", "2")])
        self.assertEqual(q, "/countme?v=1.0.0&arch=x86_64&ch=stable&age=2")


class Version(Base):
    def test_version_file_then_os_release(self):
        self.assertEqual(cm.os_version(self.root), "1.0.0")
        os.unlink(self.p("usr/lib/luxos/version"))
        self.assertIsNone(cm.os_version(self.root))
        self.write("usr/lib/os-release", 'NAME="LuxOS"\nVERSION_ID=1.0.1\n')
        self.assertEqual(cm.os_version(self.root), "1.0.1")
        self.write("usr/lib/os-release", 'VERSION_ID="1.0 beta; rm -rf"\n')
        self.assertIsNone(cm.os_version(self.root))           # jen X.Y.Z, nic jineho se neposle


class Plan(Base):
    def test_default_on_and_exact_params(self):
        params, st = cm.plan(self.NOW, **self.kw())
        self.assertEqual(params, [("v", "1.0.0"), ("arch", os.uname().machine), ("ch", "stable"), ("age", "1")])
        self.assertEqual(st, {"since": self.NOW, "last_week": None})

    def test_opt_out(self):
        lux_config.set_countme(False, "/etc/lux/lux.conf", root=self.root)
        params, why = cm.plan(self.NOW, **self.kw())
        self.assertIsNone(params)
        self.assertIn("turned off", why)
        self.assertEqual(self.run_once(self.NOW), why)
        self.assertEqual(self.sent, [])
        self.assertFalse(os.path.exists(self.state))          # vypnuto = ani soubor stavu
        lux_config.set_countme(True, "/etc/lux/lux.conf", root=self.root)
        self.assertEqual(self.run_once(self.NOW), "sent")

    def test_opt_out_in_conf_d_and_broken_config(self):
        self.write("etc/lux/conf.d/zz.conf", "[general]\ncountme = false\n")
        self.assertIn("turned off", cm.plan(self.NOW, **self.kw())[1])
        os.unlink(self.p("etc/lux/conf.d/zz.conf"))
        self.write("etc/lux/lux.conf", "[general\nbroken")
        self.assertIsNone(cm.plan(self.NOW, **self.kw())[0])  # rozbita konfigurace = nic neposilat

    def test_channel(self):
        lux_config.set_channel("staging", "/etc/lux/lux.conf", root=self.root)
        params, _st = cm.plan(self.NOW, **self.kw())
        self.assertIn(("ch", "staging"), params)

    def test_blocked(self):
        self.assertEqual(cm.plan(self.NOW, **self.kw(euid=1000))[1], "not root")
        self.assertEqual(cm.plan(self.NOW, **self.kw(rootdir=self.root))[1], "other root")
        os.makedirs(self.p("run/archiso"))
        self.assertEqual(cm.plan(self.NOW, **self.kw())[1], "live system")
        os.rmdir(self.p("run/archiso"))
        self.write("run/.containerenv", "")
        self.assertEqual(cm.plan(self.NOW, **self.kw())[1], "container")
        os.unlink(self.p("run/.containerenv"))
        self.assertIsNotNone(cm.plan(self.NOW, **self.kw())[0])

    def test_oem_counts_only_after_setup_assistant(self):
        self.write("etc/luxos/oem.conf", "OEM=1\nOEM_USER=oem\n")
        self.assertIn("OEM", cm.plan(self.NOW, **self.kw())[1])
        self.write("var/lib/luxos/oem/done", "")
        os.utime(self.p("var/lib/luxos/oem/done"), (self.NOW - 3 * DAY, self.NOW - 3 * DAY))
        self.write("var/log/luxos-install.log", "")
        os.utime(self.p("var/log/luxos-install.log"), (self.NOW - 90 * DAY,) * 2)
        params, st = cm.plan(self.NOW, **self.kw())
        self.assertEqual(st["since"], self.NOW - 3 * DAY)    # stari od dokonceni Pruvodce
        self.assertIn(("age", "1"), params)

    def test_install_date_from_installer_log(self):
        self.write("var/log/luxos-install.log", "x")
        os.utime(self.p("var/log/luxos-install.log"), (self.NOW - 40 * DAY,) * 2)
        params, st = cm.plan(self.NOW, **self.kw())
        self.assertEqual(st["since"], self.NOW - 40 * DAY)
        self.assertIn(("age", "3"), params)


class Gating(Base):
    def test_once_per_week(self):
        self.assertEqual(self.run_once(self.NOW), "sent")
        with open(self.state) as f:
            st = json.load(f)
        self.assertEqual(st, {"since": self.NOW, "last_week": "2026-W45"})   # nic jineho v souboru
        self.assertEqual(oct(os.stat(self.state).st_mode & 0o777), "0o644")
        # dalsi behy tentyz tyden (i v nedeli vecer UTC): nic
        self.assertIn("already counted", self.run_once(self.NOW + 3600))
        self.assertIn("already counted", self.run_once(utc(2026, 11, 8, 23, 59)))
        self.assertEqual(len(self.sent), 1)
        # pondeli UTC = novy tyden; stari roste podle "since"
        self.assertEqual(self.run_once(utc(2026, 11, 9, 0, 1)), "sent")
        self.assertEqual(self.sent[-1][-1], ("age", "1"))
        self.assertEqual(self.run_once(self.NOW + 14 * DAY), "sent")
        self.assertEqual(self.sent[-1][-1], ("age", "2"))
        self.assertEqual(self.run_once(self.NOW + 60 * DAY), "sent")
        self.assertEqual(self.sent[-1][-1], ("age", "3"))
        self.assertEqual(self.run_once(self.NOW + 400 * DAY), "sent")
        self.assertEqual(self.sent[-1][-1], ("age", "4"))
        self.assertEqual(len(self.sent), 5)

    def test_failure_is_retried_next_run_only(self):
        calls = []

        def failing(params):
            calls.append(params)
            return False

        self.assertEqual(self.run_once(self.NOW, sender=failing), "failed")
        self.assertEqual(len(calls), 1)                        # zadne opakovani v ramci behu
        self.assertFalse(os.path.exists(self.state))           # tyden se nezapsal
        self.assertEqual(self.run_once(self.NOW + 60), "sent")  # pristi beh lux

    def test_exception_in_sender_is_ignored(self):
        def boom(params):
            raise OSError("network unreachable")
        self.assertEqual(self.run_once(self.NOW, sender=boom), "failed")

    def test_corrupt_state(self):
        self.write("var/lib/lux/countme", "{not json")
        self.assertEqual(self.run_once(self.NOW), "sent")
        self.write("var/lib/lux/countme", json.dumps({"since": "x", "last_week": 5}))
        self.assertEqual(self.run_once(self.NOW), "sent")

    def test_concurrent_run_is_busy(self):
        import fcntl
        with open(self.lock, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            self.assertEqual(self.run_once(self.NOW), "busy")
        self.assertEqual(self.sent, [])


class Wire(Base):
    """Presne to, co odejde po siti: jen radek GET s ctyrmi parametry a hlavicky Host, User-Agent,
    Connection - zadne jmeno pocitace, uzivatel, verze Pythonu ani cookies."""

    def setUp(self):
        super().setUp()
        Recorder.seen = []
        Recorder.status = 204
        self.srv = server(Recorder)
        self.addCleanup(self.srv.shutdown)
        self.port = self.srv.server_address[1]

    def real_sender(self, params):
        return cm.send(params, host="127.0.0.1", port=self.port, https=False, timeout=5)

    def test_exact_request(self):
        self.assertEqual(self.run_once(self.NOW, sender=self.real_sender), "sent")
        self.assertEqual(len(Recorder.seen), 1)
        req = Recorder.seen[0]
        u = urllib.parse.urlsplit(req["path"])
        self.assertEqual(u.path, "/countme")
        q = urllib.parse.parse_qsl(u.query, keep_blank_values=True, strict_parsing=True)
        self.assertEqual([k for k, _v in q], ["v", "arch", "ch", "age"])
        self.assertEqual(dict(q), {"v": "1.0.0", "arch": os.uname().machine, "ch": "stable", "age": "1"})
        self.assertEqual(req["line"], f"GET {req['path']} HTTP/1.1")
        self.assertEqual([k.lower() for k, _v in req["headers"]], ["host", "user-agent", "connection"])
        h = {k.lower(): v for k, v in req["headers"]}
        self.assertEqual(h["user-agent"], "LuxOS-countme")
        self.assertEqual(h["connection"], "close")
        raw = req["raw"].decode("latin-1")
        for secret in {socket.gethostname(), os.environ.get("USER") or "", os.environ.get("LOGNAME") or "",
                       "Python", sys.version.split()[0]} - {""}:
            self.assertNotIn(secret, raw)
        self.assertLess(len(req["raw"]), 200)

    def test_server_error_is_not_counted(self):
        Recorder.status = 500
        self.assertEqual(self.run_once(self.NOW, sender=self.real_sender), "failed")
        self.assertFalse(os.path.exists(self.state))
        Recorder.status = 204
        self.assertEqual(self.run_once(self.NOW, sender=self.real_sender), "sent")

    def test_offline(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
        s.close()                                              # nikdo neposloucha
        self.assertEqual(self.run_once(self.NOW, sender=lambda p: cm.send(p, host="127.0.0.1", port=closed,
                                                                          https=False)), "failed")
        self.assertEqual(self.run_once(self.NOW, sender=lambda p: cm.send(p, host="countme.invalid",
                                                                          timeout=2)), "failed")
        self.assertFalse(os.path.exists(self.state))


class NeverBlocks(Base):
    def test_slow_server(self):
        slow = SlowServer()
        self.addCleanup(slow.close)
        sender = lambda p: cm.send(p, host="127.0.0.1", port=slow.port, https=False)  # noqa: E731
        t0 = time.monotonic()
        t = cm.start(now=self.NOW, lock_path=self.lock, sender=sender, **self.kw())
        self.assertIsNotNone(t)
        self.assertLess(time.monotonic() - t0, 0.5)            # volajici (lux) pokracuje hned
        self.assertTrue(t.daemon)
        self.assertIsNone(cm.start(now=self.NOW, lock_path=self.lock, sender=sender, **self.kw()))  # jen jednou
        t1 = time.monotonic()
        cm.finish(interactive=True)                            # v terminalu se neceka
        self.assertLess(time.monotonic() - t1, 0.2)
        cm.finish(interactive=False)                           # sluzba: nejvys casovy limit + 1 s od startu
        self.assertLess(time.monotonic() - t0, cm.TIMEOUT + 1.5)
        t.join(2)
        self.assertFalse(t.is_alive())                         # pozadavek skoncil timeoutem
        self.assertFalse(os.path.exists(self.state))           # a nic se nezapsalo

    def test_start_skips_without_thread_when_not_due(self):
        lux_config.set_countme(False, "/etc/lux/lux.conf", root=self.root)
        self.assertIsNone(cm.start(now=self.NOW, lock_path=self.lock, sender=self.sender, **self.kw()))
        cm.finish(interactive=False)
        self.assertEqual(self.sent, [])

    def test_start_never_raises(self):
        self.assertIsNone(cm.start(now="garbage", **self.kw()))


class LuxHook(unittest.TestCase):
    """lux_alpm.py: countme jen po uspesne obnove databazi jako root na skutecnem systemu s repozitari LuxOS."""

    def setUp(self):
        import lux_alpm
        self.la = lux_alpm
        self.calls = []
        fake = types.SimpleNamespace(start=lambda **kw: self.calls.append(kw), finish=lambda: None)
        self.addCleanup(sys.modules.__setitem__, "lux_countme", sys.modules["lux_countme"])
        sys.modules["lux_countme"] = fake
        self.euid = os.geteuid
        self.addCleanup(setattr, os, "geteuid", self.euid)

    def lux(self, servers, injected=False):
        conf = self.la.EngineConf("[options]\nRootDir = /\n" +
                                  "".join(f"[r{i}]\nServer = {s}\n" for i, s in enumerate(servers)))
        return types.SimpleNamespace(injected=injected, conf=conf)

    def test_hook(self):
        os.geteuid = lambda: 0
        self.la.countme_start(self.lux(["https://luxos.lux-ai.cz/repo/$repo/$arch"]))
        self.assertEqual(self.calls, [{"rootdir": "/"}])
        self.la.countme_start(self.lux(["https://luxos.lux-ai.cz/staging/$repo/$arch"]))
        self.assertEqual(len(self.calls), 2)

    def test_no_hook(self):
        os.geteuid = lambda: 0
        self.la.countme_start(self.lux(["https://luxos.lux-ai.cz/repo/$repo/$arch"], injected=True))   # testy
        self.la.countme_start(self.lux(["https://mirror.example/$repo/os/$arch"]))                       # bez LuxOS
        os.geteuid = lambda: 1000
        self.la.countme_start(self.lux(["https://luxos.lux-ai.cz/repo/$repo/$arch"]))                  # uzivatel
        self.assertEqual(self.calls, [])
        os.geteuid = lambda: 0
        os.environ["LUX_NO_COUNTME"] = "1"
        try:
            self.la.countme_start(self.lux(["https://luxos.lux-ai.cz/repo/$repo/$arch"]))
        finally:
            del os.environ["LUX_NO_COUNTME"]
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
