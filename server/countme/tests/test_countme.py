#!/usr/bin/env python3
# Testy sluzby luxos-countme: python3 -m unittest server/countme/tests/test_countme.py
#
# Binarka se prelozi z luxos_countme.lsl (`lsl compile`) do docasneho adresare, nebo se vezme
# hotova z COUNTME_BIN. Kazdy test spousti vlastni instanci na volnem portu 127.0.0.1 s docasnym
# stavovym adresarem a souborem hodin (--clock-file), takze muze posouvat cas mezi hodinami a tydny.
import datetime
import http.client
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(os.path.dirname(HERE), "luxos_countme.lsl")

VALID = "/countme?v=1.0.0&arch=x86_64&ch=stable&age=1"
WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")
KEY_RE = re.compile(r"^[0-9]{1,2}\.[0-9]{1,3}\.[0-9]{1,3}\|x86_64\|(stable|staging)\|[1-4]$")


def utc(*args):
    return datetime.datetime(*args, tzinfo=datetime.timezone.utc).timestamp()


# st 2026-11-04 12:00 UTC = 2026-W45
T0 = utc(2026, 11, 4, 12, 0, 0)

BIN = None
BUILD_DIR = None


def setUpModule():
    global BIN, BUILD_DIR
    BIN = os.environ.get("COUNTME_BIN")
    if BIN:
        return
    BUILD_DIR = tempfile.mkdtemp(prefix="countme-build-")
    BIN = os.path.join(BUILD_DIR, "luxos-countme")
    subprocess.run(["nice", "-n", "10", "lsl", "compile", SOURCE, BIN], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def tearDownModule():
    if BUILD_DIR:
        shutil.rmtree(BUILD_DIR, ignore_errors=True)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def iso_key(t):
    y, w, _ = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


class Server:
    """Jedna bezici instance sluzby (spoustena i zastavovana jen pres sve PID)."""

    def __init__(self, state, clock, extra=()):
        self.state = state
        self.clock = clock
        self.extra = list(extra)
        self.proc = None
        self.logs = []

    def start(self):
        self.port = free_port()
        self.out = tempfile.TemporaryFile(mode="w+")
        self.proc = subprocess.Popen(
            [BIN, "--bind", "127.0.0.1", "--port", str(self.port), "--state", self.state,
             "--clock-file", self.clock] + self.extra,
            stdout=self.out, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 10
        while True:
            try:
                if self.request("GET", "/health")[0] == 200:
                    return self
            except OSError:
                pass
            if self.proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("server did not start: " + self.output())
            time.sleep(0.05)

    def output(self):
        self.out.seek(0)
        return self.out.read()

    def stop(self, sig=signal.SIGTERM):
        if self.out.closed:
            return ""
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(sig)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        text = self.output()
        self.logs.append(text)
        self.out.close()
        return text

    def request(self, method, target, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, target, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    def raw(self, data):
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as s:
            s.sendall(data)
            chunks = []
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        head = b"".join(chunks).split(b"\r\n", 1)[0]
        return int(head.split(b" ")[1])

    def count(self, ip=None, v="1.0.0", arch="x86_64", ch="stable", age="1"):
        headers = {"X-Forwarded-For": ip} if ip is not None else {}
        status, body = self.request("GET", f"/countme?v={v}&arch={arch}&ch={ch}&age={age}", headers)
        assert status == 204 and body == b"", (status, body)

    def stats(self):
        status, body = self.request("GET", "/stats/usage.json")
        assert status == 200, status
        return json.loads(body)


class CountmeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="countme-test-")
        self.state = os.path.join(self.tmp, "state")
        os.mkdir(self.state, 0o700)
        self.clock = os.path.join(self.tmp, "clock")
        self.set_time(T0)
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            try:
                s.stop(signal.SIGKILL)
            except Exception:
                if s.proc and s.proc.poll() is None:
                    s.proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def set_time(self, t):
        with open(self.clock + ".new", "w") as f:
            f.write(repr(float(t)))
        os.replace(self.clock + ".new", self.clock)
        self.now = t

    def server(self, extra=()):
        s = Server(self.state, self.clock, extra).start()
        self.servers.append(s)
        return s

    def total(self, s, offset_weeks=0):
        return s.stats()["totals"][-1 - offset_weeks]

    def fresh_stats(self, s):
        # obejde 10min cache: posun o 601 s (testy hlida, aby se nepreslo pres hranici hodiny/tydne)
        self.set_time(self.now + 601)
        return s.stats()

    def state_file(self):
        with open(os.path.join(self.state, "counts.json")) as f:
            return json.load(f)

    # --- validace ---
    def test_validation(self):
        s = self.server()
        self.assertEqual(s.request("GET", VALID), (204, b""))
        self.assertEqual(s.request("GET", "/countme?age=4&ch=staging&v=99.999.999&arch=x86_64")[0], 204)
        self.assertEqual(s.request("HEAD", VALID)[0], 204)
        bad = [
            "/countme", "/countme?",
            "/countme?v=1.0.0&arch=x86_64&ch=stable",                       # chybi age
            "/countme?v=1.0.0&arch=x86_64&ch=stable&age=1&x=1",             # navic
            "/countme?v=1.0.0&arch=x86_64&ch=stable&x=1",                   # neznamy misto age
            "/countme?v=1.0.0&arch=x86_64&ch=stable&age=1&age=1",           # duplicitni
            "/countme?v=1.0.0&v=1.0.0&ch=stable&age=1",                      # duplicitni, chybi arch
            "/countme?v=1.0.0&arch=x86_64&ch=stable&age=",                  # prazdna hodnota
            "/countme?v=1.0.0&arch=x86_64&ch=stable&age",                   # bez =
            "/countme?v=1.0.0&arch=x86_64&ch=stable&age=1=1",
            "/countme?v=1.0.0&arch=x86_64&ch=stable&&age=1",
            "/countme?v=1.0&arch=x86_64&ch=stable&age=1",
            "/countme?v=1.0.0.0&arch=x86_64&ch=stable&age=1",
            "/countme?v=100.0.0&arch=x86_64&ch=stable&age=1",
            "/countme?v=1.1000.0&arch=x86_64&ch=stable&age=1",
            "/countme?v=1.0.0000&arch=x86_64&ch=stable&age=1",
            "/countme?v=a.b.c&arch=x86_64&ch=stable&age=1",
            "/countme?v=1.0.0-rc1&arch=x86_64&ch=stable&age=1",
            "/countme?v=1..0&arch=x86_64&ch=stable&age=1",
            "/countme?v=1.0.0&arch=aarch64&ch=stable&age=1",
            "/countme?v=1.0.0&arch=X86_64&ch=stable&age=1",
            "/countme?v=1.0.0&arch=x86_64&ch=beta&age=1",
            "/countme?v=1.0.0&arch=x86_64&ch=stable&age=0",
            "/countme?v=1.0.0&arch=x86_64&ch=stable&age=5",
            "/countme?v=1.0.0&arch=x86_64&ch=stable&age=01",
            "/countme?v=1.0.0&arch=x86_64&ch=st%61ble&age=1",               # percent-encoding
            "/countme?v=1.0.0&arch=x86_64&ch=stable&age=1%00",
            "/countme?v=1.0.0&arch=x86_64&ch=stable&age=+1",
            "/countme?V=1.0.0&arch=x86_64&ch=stable&age=1",
            "/countme?v=1.0.0&arch=x86_64&ch=stable&age=1&pad=" + "x" * 120,  # > 160 znaku
        ]
        for target in bad:
            with self.subTest(target=target):
                self.assertEqual(s.request("GET", target)[0], 400)
        for method in ("POST", "PUT", "DELETE", "OPTIONS", "PATCH"):
            with self.subTest(method=method):
                self.assertEqual(s.request(method, VALID)[0], 400)
        self.assertEqual(s.request("POST", "/stats/usage.json")[0], 400)
        # telo u GET
        self.assertEqual(s.raw(b"GET " + VALID.encode() + b" HTTP/1.1\r\nHost: x\r\n"
                               b"Content-Length: 3\r\n\r\nabc"), 400)
        for target in ("/", "/countme/", "/Countme?v=1.0.0&arch=x86_64&ch=stable&age=1",
                       "//countme?v=1.0.0&arch=x86_64&ch=stable&age=1", "/stats",
                       "/stats/usage.json/x", "/stats/usage", "/health/x", "/counts.json"):
            with self.subTest(target=target):
                self.assertEqual(s.request("GET", target)[0], 404)
        self.assertEqual(s.request("GET", "/health"), (200, b"ok\n"))
        # jen dva platne pozadavky (GET a HEAD z jedne IP s v/ch shodnymi = 1) + jeden s jinym v/ch
        st = s.stats()
        self.assertEqual(st["totals"][-1], 2)
        self.assertEqual(list(st["by_version"]), ["1.0.0", "99.999.999"])

    # --- pocitani a agregace ---
    def test_aggregation(self):
        # dva tydny zpet, pak minuly a aktualni tyden
        self.set_time(T0 - 14 * 86400)
        s = self.server()
        s.count("198.51.100.1", v="0.9.10", ch="staging", age="3")
        s.count("198.51.100.2", v="0.9.10", ch="stable", age="4")
        self.set_time(T0 - 7 * 86400)
        s.count("198.51.100.1", v="0.9.10", ch="staging", age="3")
        self.set_time(T0)
        s.count("198.51.100.1", v="1.0.0", age="1")
        s.count("198.51.100.2", v="1.0.0", age="2")
        s.count("198.51.100.3", v="1.0.1", ch="staging", age="2")
        s.count("198.51.100.4", v="1.0.0", age="4")
        st = s.stats()
        self.assertEqual(st["schema"], 1)
        self.assertEqual(set(st), {"schema", "generated", "current_week", "weeks", "week_start", "totals",
                                   "by_age", "by_channel", "by_version", "by_arch"})
        self.assertEqual(st["generated"], "2026-11-04T12:00:00Z")
        self.assertEqual(st["current_week"], "2026-W45")
        self.assertEqual(len(st["weeks"]), 26)
        self.assertEqual(st["weeks"][-1], "2026-W45")
        self.assertEqual(st["weeks"][0], "2026-W20")
        monday = datetime.date(2026, 11, 2)
        expect_starts = [(monday - datetime.timedelta(weeks=25 - i)).isoformat() for i in range(26)]
        self.assertEqual(st["week_start"], expect_starts)
        self.assertEqual(st["weeks"], [iso_key(utc(d.year, d.month, d.day, 12))
                                       for d in map(datetime.date.fromisoformat, expect_starts)])
        z = [0] * 23
        self.assertEqual(st["totals"], z + [2, 1, 4])
        self.assertEqual(st["by_age"], {"1": z + [0, 0, 1], "2": z + [0, 0, 2], "3": z + [1, 1, 0],
                                        "4": z + [1, 0, 1]})
        self.assertEqual(st["by_channel"], {"stable": z + [1, 0, 3], "staging": z + [1, 1, 1]})
        self.assertEqual(st["by_arch"], {"x86_64": z + [2, 1, 4]})
        self.assertEqual(list(st["by_version"]), ["0.9.10", "1.0.0", "1.0.1"])   # ciselne, ne textove
        self.assertEqual(st["by_version"], {"0.9.10": z + [2, 1, 0], "1.0.0": z + [0, 0, 3],
                                            "1.0.1": z + [0, 0, 1]})
        for series in [st["totals"]] + [v for k in ("by_age", "by_channel", "by_version", "by_arch")
                                         for v in st[k].values()]:
            self.assertEqual(len(series), 26)
        # verze, ktera vypadla z okna 26 tydnu, se neukazuje
        self.set_time(T0 + 26 * 7 * 86400)
        st = s.stats()
        self.assertEqual(st["by_version"], {})
        self.assertEqual(st["totals"], [0] * 26)

    def test_iso_week_edges(self):
        self.set_time(utc(2026, 12, 27, 23, 59, 59))
        s = self.server()
        s.count("198.51.100.1")
        self.assertEqual(s.stats()["current_week"], "2026-W52")
        self.set_time(utc(2026, 12, 28, 0, 0, 0))          # pondeli tydne 2026-W53
        s.count("198.51.100.1")                            # novy tyden -> nova sul, pocita se znovu
        self.set_time(utc(2027, 1, 1, 12, 0, 0))
        s.count("198.51.100.2")
        st = s.stats()
        self.assertEqual(st["current_week"], "2026-W53")
        self.assertEqual(st["week_start"][-1], "2026-12-28")
        self.assertEqual(st["weeks"][-2:], ["2026-W52", "2026-W53"])
        self.assertEqual(st["totals"][-2:], [1, 2])
        self.set_time(utc(2027, 1, 4, 0, 0, 1))
        s.count("198.51.100.2")
        st = s.stats()
        self.assertEqual(st["current_week"], "2027-W01")
        self.assertEqual(st["week_start"][-1], "2027-01-04")
        self.assertEqual(st["weeks"][-3:], ["2026-W52", "2026-W53", "2027-W01"])
        self.assertEqual(st["totals"][-3:], [1, 2, 1])
        s.stop()
        self.assertEqual(sorted(self.state_file()["counts"]), ["2026-W52", "2026-W53", "2027-W01"])

    # --- deduplikace a limity ---
    def test_dedupe(self):
        s = self.server()
        s.count("203.0.113.10")
        s.count("203.0.113.10")                                  # stejna IP+v+arch+ch
        s.count("203.0.113.10", age="2")                         # age neni v klici -> duplicita
        s.count("198.51.100.200, 203.0.113.10")                  # posledni prvek XFF = stejna IP
        self.assertEqual(self.total(s), 1)
        s.count("203.0.113.11")                                  # jina IP
        s.count("203.0.113.10, 203.0.113.12")                    # posledni prvek XFF rozhoduje
        s.count("203.0.113.10", v="1.0.1")                       # jina verze
        s.count("203.0.113.10", ch="staging")                    # jiny kanal
        s.count(None)                                            # bez XFF -> "none"
        s.count(None)
        s.count("  ")                                            # prazdne XFF -> "none"
        st = self.fresh_stats(s)
        self.assertEqual(st["totals"][-1], 6)
        self.assertEqual(st["by_version"]["1.0.1"][-1], 1)
        self.assertEqual(st["by_channel"]["staging"][-1], 1)

    def test_hourly_cap(self):
        self.set_time(utc(2026, 11, 4, 10, 0, 0))
        s = self.server()
        for i in range(60):
            s.count("203.0.113.20", v=f"1.0.{i}")
        for i in range(60, 70):
            s.count("203.0.113.20", v=f"1.0.{i}")          # nad limit: 204, ale nepocita se
        s.count("203.0.113.21", v="1.0.65")                # jina IP neni omezena
        self.set_time(utc(2026, 11, 4, 10, 30, 0))
        self.assertEqual(s.stats()["totals"][-1], 61)
        self.set_time(utc(2026, 11, 4, 11, 0, 0))          # nova hodina, stejny tyden
        s.count("203.0.113.20", v="1.0.65")
        s.count("203.0.113.20", v="1.0.3")                 # porad deduplikovano za tyden
        self.set_time(utc(2026, 11, 4, 11, 20, 0))
        self.assertEqual(s.stats()["totals"][-1], 62)

    def test_weekly_salt_rotation(self):
        s = self.server()
        s.count("203.0.113.30")
        s.count("203.0.113.30")
        self.set_time(T0 + 7 * 86400)
        s.count("203.0.113.30")
        s.count("203.0.113.30")
        st = s.stats()
        self.assertEqual(st["current_week"], "2026-W46")
        self.assertEqual(st["totals"][-2:], [1, 1])

    def test_dedupe_table_bound(self):
        s = self.server(["--max-entries", "5"])
        for i in range(8):
            s.count(f"203.0.113.{40 + i}")
        self.assertEqual(self.total(s), 5)
        self.set_time(T0 + 7 * 86400)                      # novy tyden: tabulka znovu prazdna
        for i in range(3):
            s.count(f"203.0.113.{40 + i}")
        self.assertEqual(self.total(s), 3)
        out = s.stop()
        self.assertEqual(out.count("dedupe table full"), 1)
        self.assertNotIn("203.0.113", out)

    # --- ulozeni ---
    def test_persistence(self):
        s = self.server()
        s.count("203.0.113.50")
        s.count("203.0.113.51", ch="staging")
        path = os.path.join(self.state, "counts.json")
        time.sleep(1.5)
        self.assertFalse(os.path.exists(path))             # odlozeny zapis: jeste ne
        self.set_time(T0 + 31)
        deadline = time.monotonic() + 5                    # zapis i bez dalsiho pozadavku (smycka 1 s)
        while not os.path.exists(path) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(self.state_file(), {"schema": 1, "counts": {"2026-W45": {
            "1.0.0|x86_64|stable|1": 1, "1.0.0|x86_64|staging|1": 1}}})
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        s.count("203.0.113.52")
        s.stop(signal.SIGKILL)                             # pad: posledni (nezapsany) pocet se ztrati
        s2 = self.server()
        self.assertEqual(self.total(s2), 2)
        s2.count("203.0.113.53", v="1.0.1")
        out = s2.stop()                                    # SIGTERM: zapise pred koncem
        self.assertIn("stopped", out)
        self.assertEqual(s2.proc.returncode, 0)
        self.assertEqual(self.state_file()["counts"]["2026-W45"]["1.0.1|x86_64|stable|1"], 1)
        s3 = self.server()
        st = s3.stats()
        self.assertEqual(st["totals"][-1], 3)
        self.assertEqual(st["by_version"]["1.0.1"][-1], 1)
        self.assertEqual(sorted(os.listdir(self.state)), ["counts.json"])

    def test_corrupt_state(self):
        path = os.path.join(self.state, "counts.json")
        for content in ["{not json", json.dumps({"schema": 1, "counts": {"2026-W45": {"203.0.113.9": 1}}}),
                        json.dumps({"schema": 2, "counts": {}}), ""]:
            with self.subTest(content=content):
                for name in os.listdir(self.state):
                    os.remove(os.path.join(self.state, name))
                with open(path, "w") as f:
                    f.write(content)
                s = self.server()
                self.assertEqual(self.total(s), 0)
                s.count("203.0.113.60")
                out = s.stop()
                self.assertIn("corrupt", out)
                with open(path + ".corrupt-2026-W45") as f:
                    self.assertEqual(f.read(), content)        # odlozeno beze zmeny
                self.assertEqual(self.state_file()["counts"], {"2026-W45": {"1.0.0|x86_64|stable|1": 1}})
                self.servers.remove(s)
        # druhe poskozeni ve stejnem tydnu neprepise prvni odlozeny soubor
        with open(path, "w") as f:
            f.write("[]")
        s = self.server()
        s.stop()
        self.servers.remove(s)
        self.assertTrue(os.path.exists(path + ".corrupt-2026-W45-2"))

    def test_stats_cache(self):
        s = self.server()
        self.assertEqual(s.stats()["totals"][-1], 0)
        s.count("203.0.113.70")
        self.set_time(T0 + 300)
        st = s.stats()
        self.assertEqual(st["totals"][-1], 0)                 # z cache
        self.assertEqual(st["generated"], "2026-11-04T12:00:00Z")
        self.set_time(T0 + 599)
        self.assertEqual(s.stats()["totals"][-1], 0)
        self.set_time(T0 + 600)
        st = s.stats()
        self.assertEqual(st["totals"][-1], 1)
        self.assertEqual(st["generated"], "2026-11-04T12:10:00Z")

    # --- soukromi ---
    def test_no_ip_persisted(self):
        s = self.server()
        ips = ["203.0.113.77", "2001:db8::77", "198.51.100.177"]
        for ip in ips:
            s.count(ip)
            s.count(ip, v="1.0.1", ch="staging", age="2")
        s.count("192.0.2.55, 203.0.113.77")
        s.request("GET", VALID + "&ip=203.0.113.77", {"X-Forwarded-For": "2001:db8::77"})
        s.request("GET", VALID, {"X-Forwarded-For": "2001:db8::77", "User-Agent": "LuxOS-secret-UA"})
        s.stats()
        self.set_time(T0 + 7 * 86400)                       # rotace soli + zapis
        s.count("203.0.113.77")
        self.set_time(T0 + 7 * 86400 + 3600)
        s.count("2001:db8::77")
        out = s.stop()
        texts = {"<process output>": out}
        for name in os.listdir(self.state):
            with open(os.path.join(self.state, name), "rb") as f:
                texts[name] = f.read().decode("utf-8", "replace")
        self.assertEqual(sorted(texts), ["<process output>", "counts.json"])
        for name, text in texts.items():
            for needle in ips + ["192.0.2.55", "203.0.113", "2001:db8", "db8::", "LuxOS-secret-UA"]:
                self.assertNotIn(needle, text, name)
            self.assertIsNone(re.search(r"[0-9a-fA-F]{16,}", text), name)    # zadne hex digesty
            self.assertIsNone(re.search(r"\d{10,}", text), name)             # zadne klice ani unix casy
        data = json.loads(texts["counts.json"])
        self.assertEqual(set(data), {"schema", "counts"})
        self.assertEqual(data["schema"], 1)
        for week, per_week in data["counts"].items():
            self.assertRegex(week, WEEK_RE)
            for key, n in per_week.items():
                self.assertRegex(key, KEY_RE)
                self.assertIsInstance(n, int)
        self.assertEqual(data["counts"], {
            "2026-W45": {"1.0.0|x86_64|stable|1": 3, "1.0.1|x86_64|staging|2": 3},
            "2026-W46": {"1.0.0|x86_64|stable|1": 2}})


if __name__ == "__main__":
    unittest.main()
