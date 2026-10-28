#!/usr/bin/env python3
"""LuxOS Companion 0.4 rozsireni protokolu: schopnosti v hello.ok, modely, nastroje a mobilni souhlasy
(zastupny luxai), cteni kalendare (calendar.events.list). Vse pres socketpair.

    python3 -m unittest packages/luxos-companion/tests/test_extensions.py -v
"""
import json
import os
import shutil
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402
from helpers import Clock, connect, fresh_dir, make_service, pump  # noqa: E402

from luxos_companion import wire  # noqa: E402

ALL = ["luxai.models", "luxai.tools", "luxai.approvals", "calendar.read"]


def frame_size(m):
    return len(json.dumps(m, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1


def gone(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split()[2] == "Z"
    except OSError:
        return True


def read_log(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f]


class Base(unittest.TestCase):
    ENV = ("FAKE_LUXAI_MODE", "FAKE_LUXAI_CAPS", "FAKE_LUXAI_MODELS")

    def setUp(self):
        d = fresh_dir("ext-" + str(time.monotonic_ns()))
        self.log = os.path.join(d, "log.jsonl")
        self.probe_log = os.path.join(d, "probe.jsonl")
        os.environ["FAKE_LUXAI_LOG"] = self.log
        os.environ["FAKE_LUXAI_PROBE_LOG"] = self.probe_log
        for k in self.ENV:
            os.environ.pop(k, None)
        self.luxai_exe = os.environ["LUXOS_COMPANION_LUXAI"]
        self.clock = Clock()
        self.svc = make_service(self.clock)
        self.sessions = []

    def tearDown(self):
        for s in self.sessions:
            s.close("test")
        self.svc.probe.close()
        for k in self.ENV:
            os.environ.pop(k, None)
        os.environ["LUXOS_COMPANION_LUXAI"] = self.luxai_exe

    def open(self):
        s, phone = connect(self.svc)
        self.sessions.append(s)
        phone.send("hello", "h1", protocol=1)
        got = phone.wait(1)
        self.assertEqual(got[0]["type"], "hello.ok", got)
        self.assertEqual(s.state, "open")
        return s, phone, got[0]

    def until(self, phone, rid, types=("luxai.done", "error"), timeout=8):
        got = []
        pump(lambda: got.extend(phone.messages()) or any(
            m.get("reply_to") == rid and m["type"] in types for m in got), timeout)
        return got


class TestCapabilities(Base):
    def test_full_chain_and_cache(self):
        _s, _p, ok = self.open()
        self.assertEqual(ok["capabilities"], ALL)
        _s, _p, ok = self.open()
        self.assertEqual(ok["capabilities"], ALL)
        probes = read_log(self.probe_log)
        self.assertEqual(len(probes), 1)                      # jednou za beh sluzby
        self.assertEqual(read_log(self.log), [])              # zjisteni nezasahuje do relace LuxAI
        self.assertEqual(self.svc.probe.probes, 1)

    def test_old_luxai_without_capabilities(self):
        os.environ["FAKE_LUXAI_CAPS"] = "none"
        self.assertEqual(self.open()[2]["capabilities"], ["calendar.read"])

    def test_partial_capabilities(self):
        os.environ["FAKE_LUXAI_CAPS"] = "tools,unknown"
        self.assertEqual(self.open()[2]["capabilities"], ["luxai.tools", "calendar.read"])

    def test_luxai_without_remote_session(self):
        os.environ["FAKE_LUXAI_MODE"] = "old"
        self.assertEqual(self.open()[2]["capabilities"], ["calendar.read"])

    def test_missing_luxai(self):
        os.environ["LUXOS_COMPANION_LUXAI"] = "/nonexistent/luxai"
        self.assertEqual(self.open()[2]["capabilities"], ["calendar.read"])

    def test_permissions_off(self):
        self.svc.settings.set("allow_luxai", False)
        self.svc.settings.set("allow_calendar_read", False)
        self.assertEqual(self.open()[2]["capabilities"], [])
        self.assertEqual(read_log(self.probe_log), [])        # LuxAI se kvuli tomu ani nespustil

    def test_reprobe_after_luxai_update(self):
        exe = os.path.join(fresh_dir("exe-" + str(time.monotonic_ns())), "luxai")
        shutil.copy2(self.luxai_exe, exe)
        os.environ["LUXOS_COMPANION_LUXAI"] = exe
        os.environ["FAKE_LUXAI_CAPS"] = "none"
        self.assertEqual(self.open()[2]["capabilities"], ["calendar.read"])
        os.environ["FAKE_LUXAI_CAPS"] = "models"
        self.assertEqual(self.open()[2]["capabilities"], ["calendar.read"])     # stale z mezipameti
        st = os.stat(exe)
        os.utime(exe, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))              # "aktualizace" luxai
        self.assertEqual(self.open()[2]["capabilities"], ["luxai.models", "calendar.read"])
        self.assertEqual(len(read_log(self.probe_log)), 2)

    def test_probe_timeout_keeps_handshake(self):
        from luxos_companion import luxai_bridge
        os.environ["FAKE_LUXAI_MODE"] = "noready"
        old = luxai_bridge.PROBE_TIMEOUT_MS
        luxai_bridge.PROBE_TIMEOUT_MS = 300
        try:
            self.assertEqual(self.open()[2]["capabilities"], ["calendar.read"])
        finally:
            luxai_bridge.PROBE_TIMEOUT_MS = old

    def test_messages_during_probe_wait_for_hello_ok(self):
        s, phone = connect(self.svc)
        self.sessions.append(s)
        phone.send("hello", "h1", protocol=1)
        phone.send("ping", "p1")
        got = phone.wait(2)
        self.assertEqual([m["type"] for m in got], ["hello.ok", "pong"])


class TestModelsAndTools(Base):
    def test_models_list(self):
        _s, phone, _ok = self.open()
        rid = phone.send("luxai.models.list", "m1")
        got = self.until(phone, rid, ("luxai.models", "error"))
        self.assertEqual(got[-1]["type"], "luxai.models")
        self.assertEqual(got[-1]["models"], [{"id": "local/llama", "name": "Llama (local)"},
                                             {"id": "cloud/fast", "name": "cloud/fast"}])
        req = [x for x in read_log(self.log) if x.get("type") == "models"]
        self.assertEqual(len(req), 1)
        self.assertNotEqual(req[0]["id"], rid)                # vlastni UUID mostu

    def test_models_limits(self):
        os.environ["FAKE_LUXAI_MODELS"] = "150"
        _s, phone, _ok = self.open()
        rid = phone.send("luxai.models.list", "m1")
        got = self.until(phone, rid, ("luxai.models", "error"))
        m = got[-1]
        self.assertEqual(m["type"], "luxai.models")
        self.assertLessEqual(len(m["models"]), 100)
        self.assertGreater(len(m["models"]), 10)
        self.assertLessEqual(frame_size(m), wire.MAX_FRAME)
        self.assertTrue(all(len(x["id"]) <= 200 and len(x["name"]) <= 200 for x in m["models"]))

    def test_model_passthrough_and_unavailable(self):
        _s, phone, _ok = self.open()
        rid = phone.send("luxai.request", text="ahoj", mode="chat", model="cloud/fast")
        got = self.until(phone, rid)
        self.assertEqual("".join(x.get("text", "") for x in got), "Echo #1 (chat, cloud/fast): ahoj")
        req = [x for x in read_log(self.log) if x.get("type") == "request"]
        self.assertEqual(req[0]["model"], "cloud/fast")
        rid = phone.send("luxai.request", text="ahoj", mode="chat", model="nope/none")
        got = self.until(phone, rid)
        self.assertEqual((got[-1]["type"], got[-1]["code"]), ("error", "model_unavailable"))
        self.assertTrue(got[-1]["message"])
        rid = phone.send("luxai.request", text="ahoj", mode="chat")                 # model nastaveny na PC
        got = self.until(phone, rid)
        self.assertNotIn("model", [x for x in read_log(self.log) if x.get("type") == "request"][-1])
        rid = phone.send("luxai.request", text="ahoj", mode="chat", model="")
        self.assertEqual(self.until(phone, rid)[-1]["code"], "invalid_request")

    def test_without_models_capability(self):
        os.environ["FAKE_LUXAI_CAPS"] = "tools"
        _s, phone, ok = self.open()
        self.assertNotIn("luxai.models", ok["capabilities"])
        rid = phone.send("luxai.models.list", "m1")
        self.assertEqual(self.until(phone, rid)[-1]["code"], "unsupported")
        rid = phone.send("luxai.request", text="ahoj", mode="chat", model="cloud/fast")
        self.assertEqual(self.until(phone, rid)[-1]["code"], "model_unavailable")     # nikdy potichu jiny
        self.assertEqual(read_log(self.log), [])

    def test_models_permission(self):
        _s, phone, _ok = self.open()
        self.svc.settings.set("allow_luxai", False)
        rid = phone.send("luxai.models.list", "m1")
        self.assertEqual(self.until(phone, rid)[-1]["code"], "permission_denied")

    def test_tool_events_mapped(self):
        _s, phone, _ok = self.open()
        rid = phone.send("luxai.request", text="tools", mode="agent")
        got = self.until(phone, rid)
        tools = [m for m in got if m["type"] == "luxai.tool"]
        self.assertEqual([(t["tool_id"], t["state"]) for t in tools], [("call-1", "running"), ("call-1", "completed")])
        self.assertTrue(all(t["reply_to"] == rid for t in tools))
        self.assertEqual(tools[0]["detail"], "ls -la /tmp")                       # bez ridicich znaku
        self.assertEqual(tools[0]["name"], "shell")
        self.assertEqual(got[-1]["type"], "luxai.done")

    def test_tool_limits_and_frames(self):
        _s, phone, _ok = self.open()
        rid = phone.send("luxai.request", text="manytools", mode="agent")
        got = self.until(phone, rid, timeout=15)
        tools = [m for m in got if m["type"] == "luxai.tool"]
        self.assertEqual(len(tools), 100)
        self.assertTrue(all(len(t["detail"]) == 4000 for t in tools))
        self.assertTrue(all(frame_size(m) <= wire.MAX_FRAME for m in got))

    def test_tools_not_announced_not_forwarded(self):
        os.environ["FAKE_LUXAI_CAPS"] = "models"
        _s, phone, _ok = self.open()
        rid = phone.send("luxai.request", text="tools", mode="agent")
        got = self.until(phone, rid)
        self.assertEqual([m["type"] for m in got], ["luxai.delta", "luxai.done"])


class TestApprovals(Base):
    def ask_approval(self, phone, text="approve"):
        rid = phone.send("luxai.request", text=text, mode="agent")
        got = self.until(phone, rid, ("luxai.approval", "error", "luxai.done"))
        return rid, got

    def approvals_logged(self):
        return [x for x in read_log(self.log) if x.get("type") == "approval"]

    def test_approve_once(self):
        s, phone, _ok = self.open()
        rid, got = self.ask_approval(phone)
        ap = got[-1]
        self.assertEqual(ap["type"], "luxai.approval")
        self.assertEqual((ap["reply_to"], ap["tool_id"], ap["approval_id"], ap["state"], ap["timeout_ms"]),
                         (rid, "call-1", "ap-1", "waiting", 60000))
        self.assertIn("2026-10-29 16:00", ap["detail"])
        self.assertEqual([m["state"] for m in got if m["type"] == "luxai.tool"], ["waiting"])
        self.assertEqual(self.svc.status()["phone_approvals"], 1)
        bridge_id = [x for x in read_log(self.log) if x.get("type") == "request"][0]["id"]
        phone.send("luxai.approval.respond", "r1", request_id=rid, approval_id="ap-1", approved=True)
        got = self.until(phone, rid)
        self.assertEqual([(m["type"], m.get("state")) for m in got],
                         [("luxai.tool", "completed"), ("luxai.delta", None), ("luxai.done", None)])
        self.assertTrue(all(m["reply_to"] == rid for m in got))
        self.assertEqual(self.approvals_logged(),
                         [{"type": "approval", "request_id": bridge_id, "approval_id": "ap-1", "approved": True}])
        self.assertEqual(self.svc.status()["phone_approvals"], 0)
        # opakovani -> chyba, do LuxAI nic dalsiho
        phone.send("luxai.approval.respond", "r2", request_id=rid, approval_id="ap-1", approved=True)
        got = self.until(phone, "r2", ("error",))
        self.assertEqual((got[-1]["reply_to"], got[-1]["code"]), ("r2", "approval_invalid"))
        pump(timeout=0.2)
        self.assertEqual(len(self.approvals_logged()), 1)

    def test_deny(self):
        _s, phone, _ok = self.open()
        rid, _got = self.ask_approval(phone)
        phone.send("luxai.approval.respond", "r1", request_id=rid, approval_id="ap-1", approved=False)
        got = self.until(phone, rid)
        self.assertEqual([m.get("state") or m.get("text") for m in got[:2]], ["failed", "denied"])
        self.assertEqual(self.approvals_logged()[0]["approved"], False)

    def test_unknown_foreign_and_invalid(self):
        _s, phone, _ok = self.open()
        rid, _got = self.ask_approval(phone)
        for mid, kw, code in (("r1", dict(request_id=rid, approval_id="ap-x", approved=True), "approval_invalid"),
                              ("r2", dict(request_id="other", approval_id="ap-1", approved=True), "approval_invalid"),
                              ("r3", dict(request_id=rid, approval_id="ap-1", approved="yes"), "invalid_request"),
                              ("r4", dict(request_id=rid, approved=True), "invalid_request")):
            phone.send("luxai.approval.respond", mid, **kw)
            got = self.until(phone, mid, ("error",))
            self.assertEqual((got[-1]["reply_to"], got[-1]["code"]), (mid, code))
        self.assertEqual(self.approvals_logged(), [])
        # cizi pokus platny souhlas nespotreboval
        phone.send("luxai.approval.respond", "r5", request_id=rid, approval_id="ap-1", approved=True)
        self.assertEqual(self.until(phone, rid)[-1]["type"], "luxai.done")

    def test_late_approval_rejected(self):
        s, phone, _ok = self.open()
        rid, _got = self.ask_approval(phone)
        self.clock.advance(61)
        self.assertEqual(self.svc.status()["phone_approvals"], 0)
        phone.send("luxai.approval.respond", "r1", request_id=rid, approval_id="ap-1", approved=True)
        got = self.until(phone, "r1", ("error",))
        self.assertEqual(got[-1]["code"], "approval_invalid")
        self.assertEqual(self.approvals_logged(), [])
        phone.send("luxai.cancel", request_id=rid)
        self.assertTrue(pump(lambda: s.luxai.active is None, 8))

    def test_after_cancel_rejected(self):
        s, phone, _ok = self.open()
        rid, _got = self.ask_approval(phone)
        phone.send("luxai.cancel", request_id=rid)
        self.assertTrue(pump(lambda: s.luxai.active is None, 8))
        phone.send("luxai.approval.respond", "r1", request_id=rid, approval_id="ap-1", approved=True)
        self.assertEqual(self.until(phone, "r1", ("error",))[-1]["code"], "approval_invalid")
        self.assertEqual(self.approvals_logged(), [])

    def test_timeout_clamped(self):
        _s, phone, _ok = self.open()
        rid = phone.send("luxai.request", text="approve-twice", mode="agent")
        got = []
        pump(lambda: got.extend(phone.messages()) or
             len([m for m in got if m["type"] == "luxai.approval"]) >= 2, 8)
        aps = [m for m in got if m["type"] == "luxai.approval"]
        self.assertEqual([a["timeout_ms"] for a in aps], [60000, 120000])
        for i, a in enumerate(aps):
            phone.send("luxai.approval.respond", f"r{i}", request_id=rid, approval_id=a["approval_id"], approved=True)
        self.assertEqual(self.until(phone, rid)[-1]["type"], "luxai.done")

    def test_empty_detail_denied_automatically(self):
        _s, phone, _ok = self.open()
        rid = phone.send("luxai.request", text="approve-empty", mode="agent")
        got = self.until(phone, rid)
        self.assertNotIn("luxai.approval", [m["type"] for m in got])
        self.assertEqual(self.approvals_logged()[0]["approved"], False)
        self.assertIn("denied", [m.get("text") for m in got])

    def test_not_announced_denied_automatically(self):
        os.environ["FAKE_LUXAI_CAPS"] = "models,tools"
        _s, phone, ok = self.open()
        self.assertNotIn("luxai.approvals", ok["capabilities"])
        rid = phone.send("luxai.request", text="approve", mode="agent")
        got = self.until(phone, rid)
        self.assertNotIn("luxai.approval", [m["type"] for m in got])
        self.assertEqual(self.approvals_logged()[0]["approved"], False)

    def test_respond_without_luxai(self):
        _s, phone, _ok = self.open()
        phone.send("luxai.approval.respond", "r1", request_id="a1", approval_id="ap-1", approved=True)
        self.assertEqual(self.until(phone, "r1", ("error",))[-1]["code"], "approval_invalid")

    def test_reconnect_stops_old_luxai(self):
        s, phone, _ok = self.open()
        rid, _got = self.ask_approval(phone)
        pid = read_log(self.log)[0]["pid"]
        s2, phone2, ok = self.open()                       # novy chat = nove spojeni
        self.assertEqual(s.state, "closed")
        self.assertTrue(pump(lambda: gone(pid), 8))
        rid = phone2.send("luxai.request", text="ahoj", mode="chat")
        self.assertIn("Echo #1", "".join(m.get("text", "") for m in self.until(phone2, rid)))


ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//LuxOS//Calendar//EN
BEGIN:VEVENT
UID:meeting
DTSTART;TZID=Europe/Prague:20261028T163000
DTEND;TZID=Europe/Prague:20261028T170000
SUMMARY:Schůzka
DESCRIPTION:Poznámka\\nřádek 2
LOCATION:Praha
END:VEVENT
BEGIN:VEVENT
UID:weekly
DTSTART;TZID=Europe/Prague:20261007T090000
DTEND;TZID=Europe/Prague:20261007T093000
RRULE:FREQ=WEEKLY;COUNT=10
EXDATE;TZID=Europe/Prague:20261021T090000
SUMMARY:Standup
END:VEVENT
BEGIN:VEVENT
UID:allday
DTSTART;VALUE=DATE:20261028
DTEND;VALUE=DATE:20261029
SUMMARY:Státní svátek
END:VEVENT
BEGIN:VEVENT
UID:trip
DTSTART;VALUE=DATE:20261027
DTEND;VALUE=DATE:20261030
SUMMARY:Výlet
END:VEVENT
BEGIN:VEVENT
UID:night
DTSTART;TZID=Europe/Prague:20261027T220000
DTEND;TZID=Europe/Prague:20261028T020000
SUMMARY:Noční směna
END:VEVENT
BEGIN:VEVENT
UID:utc
DTSTART:20261028T230000Z
DTEND:20261028T233000Z
SUMMARY:
END:VEVENT
END:VCALENDAR
"""

OTHER = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:meeting
DTSTART;TZID=Europe/Prague:20261028T080000
DTEND;TZID=Europe/Prague:20261028T083000
SUMMARY:Odebíraný
END:VEVENT
END:VCALENDAR
"""


class TestCalendarList(Base):
    # pasmo pocitace; opakovani rozbaluje luxos_calendar_ics v mistnim case pocitace (jako Kalendar)
    PC_TZ = "Europe/Prague"

    def setUp(self):
        super().setUp()
        self.old_tz = os.environ.get("TZ")
        self.set_tz(self.PC_TZ)

    def tearDown(self):
        super().tearDown()
        self.set_tz(self.old_tz)

    @staticmethod
    def set_tz(tz):
        if tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = tz
        time.tzset()

    def write(self, text, name="events.ics"):
        os.makedirs(self.svc.calendar.dir, exist_ok=True)
        with open(os.path.join(self.svc.calendar.dir, name), "w", encoding="utf-8") as f:
            f.write(text.replace("\n", "\r\n"))

    def ask(self, phone, mid="e1", **kw):
        fields = dict(date="2026-10-28", timezone="Europe/Prague", limit=100)
        fields.update(kw)
        phone.send("calendar.events.list", mid, **{k: v for k, v in fields.items() if v is not None})
        got = self.until(phone, mid, ("calendar.events", "error"))
        self.assertTrue(got, "no answer")
        self.assertLessEqual(frame_size(got[-1]), wire.MAX_FRAME)
        return got[-1]

    def test_day_listing(self):
        self.write(ICS)
        self.write(OTHER, "other.ics")
        _s, phone, _ok = self.open()
        m = self.ask(phone)
        self.assertEqual((m["type"], m["reply_to"], m["truncated"]), ("calendar.events", "e1", False))
        ev = {e["title"]: e for e in m["events"]}
        self.assertEqual(set(ev), {"Schůzka", "Standup", "Státní svátek", "Výlet", "Noční směna", "Odebíraný"})
        self.assertEqual(ev["Schůzka"]["time"], "16:30")
        self.assertEqual(ev["Schůzka"]["text"], "Praha\n\nPoznámka\nřádek 2")
        self.assertEqual(ev["Standup"]["time"], "09:00")
        self.assertIn("/", ev["Standup"]["id"])                      # vyskyt opakovani
        self.assertIsNone(ev["Státní svátek"]["time"])
        self.assertIsNone(ev["Výlet"]["time"])
        self.assertIn("2026-10-27 – 2026-10-29", ev["Výlet"]["text"])
        self.assertEqual(ev["Noční směna"]["time"], "00:00")
        self.assertIn("2026-10-27 22:00 – 2026-10-28 02:00", ev["Noční směna"]["text"])
        self.assertTrue(all(e["date"] == "2026-10-28" and e["timezone"] == "Europe/Prague" for e in m["events"]))
        ids = [e["id"] for e in m["events"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(0 < len(i) <= 200 for i in ids))
        self.assertEqual([e["time"] for e in m["events"][:2]], [None, None])    # cele dny napred

    def test_other_days_and_zones(self):
        self.write(ICS)
        _s, phone, _ok = self.open()
        titles = lambda m: {e["title"]: e["time"] for e in m["events"]}  # noqa: E731
        m = self.ask(phone, date="2026-10-21")
        self.assertNotIn("Standup", titles(m))                      # EXDATE
        m = self.ask(phone, date="2026-11-04")
        self.assertEqual(titles(m).get("Standup"), "09:00")         # dalsi tyden (i po zmene casu)
        m = self.ask(phone, date="2026-10-27")
        self.assertEqual(titles(m).get("Noční směna"), "22:00")
        m = self.ask(phone, date="2026-10-29")
        self.assertEqual(titles(m).get("(No title)"), "00:00")      # 23:00Z = 00:00 v Praze
        m = self.ask(phone, date="2026-10-28", timezone="America/New_York")
        self.assertEqual(titles(m).get("(No title)"), "19:00")
        self.assertEqual(titles(m).get("Schůzka"), "11:30")
        m = self.ask(phone, date="2027-01-01")
        self.assertEqual((m["events"], m["truncated"]), ([], False))

    def test_computer_in_other_zone(self):
        # pocitac v jinem pasmu nez telefon: prevod jde pres skutecne okamziky
        self.set_tz("America/New_York")
        self.write(ICS)
        _s, phone, _ok = self.open()
        ev = {e["title"]: e["time"] for e in self.ask(phone)["events"]}
        self.assertEqual((ev["Schůzka"], ev["Noční směna"], ev["Státní svátek"]), ("16:30", "00:00", None))
        self.assertNotIn("(No title)", ev)
        ev = {e["title"]: e["time"] for e in self.ask(phone, "e2", timezone="Asia/Tokyo")["events"]}
        self.assertEqual(ev["Noční směna"], "06:00")                # 21:00Z 27.10. = 06:00 28.10. v Tokiu
        self.assertNotIn("Schůzka", ev)                             # 15:30Z = 00:30 29.10. v Tokiu
        ev = {e["title"]: e["time"] for e in self.ask(phone, "e3", date="2026-10-29", timezone="Asia/Tokyo")["events"]}
        self.assertEqual((ev["Schůzka"], ev["(No title)"]), ("00:30", "08:00"))

    def test_limits_and_truncation(self):
        events = "".join(
            f"BEGIN:VEVENT\nUID:e{i}\nDTSTART;TZID=Europe/Prague:20261028T{8 + i // 60:02d}{i % 60:02d}00\n"
            f"SUMMARY:{'Událost ' + str(i)}\nEND:VEVENT\n" for i in range(120))
        self.write("BEGIN:VCALENDAR\nVERSION:2.0\n" + events + "END:VCALENDAR\n")
        _s, phone, _ok = self.open()
        m = self.ask(phone)
        self.assertEqual((len(m["events"]), m["truncated"]), (100, True))
        m = self.ask(phone, "e2", limit=2)
        self.assertEqual((len(m["events"]), m["truncated"]), (2, True))

    def test_frame_limit_shortens_texts(self):
        long_text = "ž\\n\\\\\"" * 2000
        events = "".join(
            f"BEGIN:VEVENT\nUID:e{i}\nDTSTART;TZID=Europe/Prague:20261028T10{i:02d}00\n"
            f"SUMMARY:{'T' * 400}\nDESCRIPTION:{long_text}\nEND:VEVENT\n" for i in range(40))
        self.write("BEGIN:VCALENDAR\nVERSION:2.0\n" + events + "END:VCALENDAR\n")
        _s, phone, _ok = self.open()
        m = self.ask(phone)
        self.assertTrue(m["truncated"])
        self.assertEqual(len(m["events"]), 40)                     # radeji kratsi texty nez mene zaznamu
        self.assertTrue(all(len(e["title"]) == 300 and len(e["text"]) <= 8000 for e in m["events"]))
        self.assertGreater(frame_size(m), 50000)

    def test_errors_and_permission(self):
        self.write(ICS)
        _s, phone, _ok = self.open()
        for kw, code in ((dict(date="28.10.2026"), "invalid_date"), (dict(date=None), "invalid_date"),
                         (dict(timezone="Mars/Base"), "invalid_timezone"), (dict(limit=0), "invalid_request"),
                         (dict(limit=101), "invalid_request"), (dict(limit=True), "invalid_request")):
            m = self.ask(phone, "x" + str(time.monotonic_ns()), **kw)
            self.assertEqual((m["type"], m["code"]), ("error", code), kw)
        self.svc.settings.set("allow_calendar_read", False)
        m = self.ask(phone, "e9")
        self.assertEqual((m["type"], m["reply_to"], m["code"]), ("error", "e9", "permission_denied"))
        self.svc.settings.set("allow_calendar_read", True)
        self.svc.settings.set("allow_calendar", False)              # zapis vypnuty, cteni zustava
        self.assertEqual(self.ask(phone, "e10")["type"], "calendar.events")

    def test_no_calendar_yet(self):
        _s, phone, _ok = self.open()
        m = self.ask(phone)
        self.assertEqual((m["type"], m["events"], m["truncated"]), ("calendar.events", [], False))


def tearDownModule():
    shutil.rmtree(helpers.TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
