#!/usr/bin/env python3
"""LuxOS Companion - kalendar, poloha, nastaveni (schvalene telefony) a most do LuxAI (zastupny luxai).

    python3 -m unittest packages/luxos-companion/tests/test_features.py -v
"""
import datetime as dt
import json
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402
from helpers import Clock, connect, fresh_dir, make_service, pump  # noqa: E402

import luxos_calendar_ics as ics  # noqa: E402
from luxos_companion import calendar_note, location, store  # noqa: E402

FOREIGN = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Other//EN\r\nX-WR-CALNAME:Můj\r\n"
    "BEGIN:VTIMEZONE\r\nTZID:Europe/Prague\r\nBEGIN:STANDARD\r\nDTSTART:19701025T030000\r\n"
    "TZOFFSETFROM:+0200\r\nTZOFFSETTO:+0100\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n"
    "BEGIN:VTODO\r\nUID:todo-1\r\nSUMMARY:Úkol\r\nEND:VTODO\r\n"
    "BEGIN:VEVENT\r\nUID:old-1\r\nDTSTAMP:20260101T000000Z\r\nDTSTART;TZID=America/New_York:20261101T090000\r\n"
    "DTEND;TZID=America/New_York:20261101T100000\r\nSUMMARY:Staré\r\nX-CUSTOM:zachovat\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n")


def note(**kw):
    msg = {"v": 1, "type": "calendar.note.create", "id": kw.pop("id", "n-" + str(time.monotonic_ns())),
           "title": "Projekt LuxOS", "text": "Dokončit Bluetooth bridge.", "date": "2026-10-28", "time": "16:30",
           "timezone": "Europe/Prague"}
    msg.update(kw)
    return msg


def raw_event(path, uid):
    """Radky VEVENT s danym UID (rozbalene) z events.ics."""
    with open(path, encoding="utf-8") as f:
        lines = ics.unfold(f.read())
    out, inside = [], False
    for line in lines:
        if line == "BEGIN:VEVENT":
            inside, block = True, []
        if inside:
            block.append(line)
        if line == "END:VEVENT" and inside:
            inside = False
            if f"UID:{uid}" in block:
                out = block
    return out


class TestCalendar(unittest.TestCase):
    def setUp(self):
        self.dir = fresh_dir("cal")
        self.done = os.path.join(fresh_dir("calstate"), "done.json")
        self.w = calendar_note.CalendarWriter(self.dir, done_path=self.done)
        self.path = os.path.join(self.dir, "events.ics")

    def test_timed_note_new_file(self):
        msg = note()
        uid = self.w.create(msg["id"], msg)
        self.assertTrue(uid.endswith("@luxos-companion"))
        ev = raw_event(self.path, uid)
        self.assertIn("DTSTART;TZID=Europe/Prague:20261028T163000", ev)
        self.assertIn("DTEND;TZID=Europe/Prague:20261028T170000", ev)
        self.assertIn("SUMMARY:Projekt LuxOS", ev)
        self.assertIn("DESCRIPTION:Dokončit Bluetooth bridge.", ev)
        with open(self.path, "rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"BEGIN:VCALENDAR\r\n"))
        cal = ics.read_file(self.path)
        self.assertEqual(len(cal.events), 1)
        self.assertEqual(cal.errors, 0)

    def test_all_day(self):
        msg = note(time=None)
        uid = self.w.create(msg["id"], msg)
        ev = raw_event(self.path, uid)
        self.assertIn("DTSTART;VALUE=DATE:20261028", ev)
        self.assertIn("DTEND;VALUE=DATE:20261029", ev)
        parsed = ics.read_file(self.path).events[0]
        self.assertTrue(parsed.all_day)
        self.assertEqual(parsed.duration(), dt.timedelta(days=1))

    def test_all_day_end_of_year(self):
        msg = note(time=None, date="2026-12-31")
        ev = raw_event(self.path, self.w.create(msg["id"], msg))
        self.assertIn("DTEND;VALUE=DATE:20270101", ev)

    def test_czech_chars_escaping_and_folding(self):
        text = "Řádek 1, čárka; středník \\ zpětné\nŘádek 2 " + "ěščřžýáíé" * 30
        msg = note(title="Schůzka: Žluťoučký kůň, úpěl", text=text)
        uid = self.w.create(msg["id"], msg)
        with open(self.path, "rb") as f:
            for line in f.read().split(b"\r\n"):
                self.assertLessEqual(len(line), 75)
                line.decode("utf-8")   # zadny rozdeleny znak
        ev = [e for e in ics.read_file(self.path).events if e.uid == uid][0]
        self.assertEqual(ev.summary, "Schůzka: Žluťoučký kůň, úpěl")
        self.assertEqual(ev.description, text)

    def test_control_chars_removed(self):
        msg = note(title="A\x00B\x1bC", text="x\r\ny\x07")
        uid = self.w.create(msg["id"], msg)
        ev = [e for e in ics.read_file(self.path).events if e.uid == uid][0]
        self.assertEqual(ev.summary, "ABC")
        self.assertEqual(ev.description, "x\ny")

    def test_other_timezone_kept(self):
        msg = note(timezone="America/New_York", time="09:15", date="2026-07-04")
        ev = raw_event(self.path, self.w.create(msg["id"], msg))
        self.assertIn("DTSTART;TZID=America/New_York:20260704T091500", ev)
        self.assertIn("DTEND;TZID=America/New_York:20260704T094500", ev)

    def test_dst_gap_rejected(self):
        msg = note(date="2026-03-29", time="02:30")      # Praha: 02:00 -> 03:00
        with self.assertRaises(calendar_note.NoteError) as cm:
            self.w.create(msg["id"], msg)
        self.assertEqual(cm.exception.code, "nonexistent_time")
        self.assertFalse(os.path.exists(self.path))

    def test_dst_overlap_first_occurrence(self):
        msg = note(date="2026-10-25", time="02:30")      # Praha: 03:00 -> 02:00, dvakrat 02:30
        ev = raw_event(self.path, self.w.create(msg["id"], msg))
        self.assertIn("DTSTART;TZID=Europe/Prague:20261025T023000", ev)
        self.assertIn("DTEND;TZID=Europe/Prague:20261025T030000", ev)

    def test_end_in_dst_gap(self):
        msg = note(date="2026-03-29", time="01:45")
        ev = raw_event(self.path, self.w.create(msg["id"], msg))
        self.assertIn("DTEND;TZID=Europe/Prague:20260329T031500", ev)   # 30 skutecnych minut

    def test_validation(self):
        bad = [
            (dict(title=""), "invalid_title"), (dict(title="   "), "invalid_title"), (dict(title=5), "invalid_title"),
            (dict(title="x" * 201), "invalid_title"), (dict(text="x" * 8001), "invalid_text"),
            (dict(text=["x"]), "invalid_text"),
            (dict(date="2026-02-30"), "invalid_date"), (dict(date="28.10.2026"), "invalid_date"),
            (dict(date=None), "invalid_date"), (dict(date="1800-01-01"), "invalid_date"),
            (dict(time="24:00"), "invalid_time"), (dict(time="16:60"), "invalid_time"),
            (dict(time="16.30"), "invalid_time"), (dict(time=1630), "invalid_time"),
            (dict(timezone="Europe/Atlantis"), "invalid_timezone"), (dict(timezone="../../etc/passwd"), "invalid_timezone"),
            (dict(timezone=""), "invalid_timezone"), (dict(timezone=None), "invalid_timezone"),
            (dict(timezone="GMT+02:00"), "invalid_timezone"),
        ]
        for kw, code in bad:
            with self.assertRaises(calendar_note.NoteError, msg=kw) as cm:
                calendar_note.validate(note(**kw))
            self.assertEqual(cm.exception.code, code, kw)
        ok = calendar_note.validate(note(title="x" * 200, text="y" * 8000, time="9:05", timezone="UTC"))
        self.assertEqual(ok["time"], (9, 5))
        self.assertIsNone(calendar_note.validate(note(text=None))["text"] or None)

    def test_foreign_components_kept_byte_for_byte(self):
        os.makedirs(self.dir, exist_ok=True)
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(FOREIGN)
        msg = note()
        uid = self.w.create(msg["id"], msg)
        with open(self.path, encoding="utf-8", newline="") as f:
            data = f.read()
        head = FOREIGN[:FOREIGN.rindex("END:VCALENDAR")]
        self.assertTrue(data.startswith(head))
        self.assertTrue(data.endswith("END:VCALENDAR\r\n"))
        cal = ics.read_file(self.path)
        self.assertEqual(sorted(e.uid for e in cal.events), sorted(["old-1", uid]))
        self.assertEqual(len(cal.other), 2)      # VTIMEZONE + VTODO

    def test_damaged_file_not_touched(self):
        os.makedirs(self.dir, exist_ok=True)
        with open(self.path, "w") as f:
            f.write("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\n")
        msg = note()
        with self.assertRaises(calendar_note.NoteError) as cm:
            self.w.create(msg["id"], msg)
        self.assertEqual(cm.exception.code, "storage_failed")
        with open(self.path) as f:
            self.assertEqual(f.read(), "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\n")

    def test_dedupe_same_request(self):
        msg = note(id="11111111-2222-3333-4444-555555555555")
        uid1 = self.w.create(msg["id"], msg)
        uid2 = self.w.create(msg["id"], msg)
        # i po restartu sluzby (novy zapisovac cte ulozena UUID)
        w2 = calendar_note.CalendarWriter(self.dir, done_path=self.done)
        uid3 = w2.create(msg["id"], msg)
        self.assertEqual(uid1, uid2)
        self.assertEqual(uid1, uid3)
        self.assertEqual(len(ics.read_file(self.path).events), 1)
        # bez pameti deduplikace (pad pred jejim zapisem): UID odvozene z pozadavku uz v souboru je
        w3 = calendar_note.CalendarWriter(self.dir, done_path=None)
        self.assertEqual(w3.create(msg["id"], msg), uid1)
        self.assertEqual(len(ics.read_file(self.path).events), 1)
        # nove UUID = nova poznamka
        other = note()
        self.w.create(other["id"], other)
        self.assertEqual(len(ics.read_file(self.path).events), 2)

    def test_concurrent_gui_write_is_not_lost(self):
        """Kalendar zapise (atomicke prejmenovani) mezi nasim ctenim a zapisem -> nacist znovu, nic neztratit."""
        cal = ics.Calendar()
        cal.events.append(ics.Event("První", dt.datetime(2026, 10, 27, 8), dt.datetime(2026, 10, 27, 9)))
        ics.write_file(self.path, cal, "Europe/Prague")
        calls = []

        def gui_write():
            if calls:
                return
            calls.append(1)
            time.sleep(0.01)      # jine mtime_ns
            c = ics.read_file(self.path)
            c.events.append(ics.Event("Z GUI", dt.datetime(2026, 10, 27, 12), dt.datetime(2026, 10, 27, 13)))
            ics.write_file(self.path, c, "Europe/Prague")
        self.w.after_read = gui_write
        msg = note()
        uid = self.w.create(msg["id"], msg)
        names = sorted(e.summary for e in ics.read_file(self.path).events)
        self.assertEqual(names, ["Projekt LuxOS", "První", "Z GUI"])
        self.assertTrue(raw_event(self.path, uid))
        self.assertEqual([n for n in os.listdir(self.dir) if ".tmp-" in n], [])

    def test_parallel_writers_with_lock(self):
        writers = [calendar_note.CalendarWriter(self.dir) for _ in range(4)]
        errors = []

        def work(w, i):
            try:
                for j in range(5):
                    m = note(id=f"req-{i}-{j}", title=f"N{i}-{j}")
                    w.create(m["id"], m)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
        ts = [threading.Thread(target=work, args=(w, i)) for i, w in enumerate(writers)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(ics.read_file(self.path).events), 20)

    def test_via_protocol_saved_only_after_write(self):
        svc = make_service(calendar_dir=self.dir)
        s, phone = connect(svc)
        phone.send("hello", "h1", protocol=1)
        phone.wait(1)
        msg = note()
        msg.pop("v")
        phone.send(msg.pop("type"), msg.pop("id"), **{k: v for k, v in msg.items()})
        got = phone.wait(1)
        self.assertEqual(got[0]["type"], "calendar.saved")
        uid = got[0]["event_id"]
        self.assertTrue(raw_event(self.path, uid))      # v souboru uz je
        self.assertIn("Note from Pixel Test saved to Calendar", svc.notifier.sent[-1]["summary"])
        # chyba s kodem a reply_to
        rid = phone.send("calendar.note.create", "bad1", title="T", text="", date="2026-03-29", time="02:30",
                         timezone="Europe/Prague")
        err = phone.wait(1)[0]
        self.assertEqual((err["type"], err["reply_to"], err["code"]), ("error", rid, "nonexistent_time"))
        self.assertIn("does not exist", err["message"])
        # zapis vypnuty v nastaveni
        svc.settings.set("allow_calendar", False)
        rid = phone.send("calendar.note.create", "n9", title="T", text="", date="2026-10-28", time=None,
                         timezone="Europe/Prague")
        err = phone.wait(1)[0]
        self.assertEqual((err["code"], err["reply_to"]), ("permission_denied", rid))


class TestLocation(unittest.TestCase):
    def upd(self, **kw):
        m = {"v": 1, "type": "location.update", "id": "g", "latitude": 50.0755, "longitude": 14.4378,
             "accuracy_m": 6.5, "timestamp_ms": 1793098800000, "age_ms": 15, "altitude_m": 220.4,
             "speed_mps": 1.3, "bearing_deg": 180.0, "mock": False}
        m.update(kw)
        return m

    def test_fresh_then_stale_after_15s(self):
        clock = Clock()
        changes = []
        st = location.LocationState(clock, changes.append)
        st.update("s1", self.upd(age_ms=2000), "Pixel")
        snap = st.snapshot()
        self.assertTrue(snap["valid"])
        self.assertEqual((snap["latitude"], snap["accuracy"], snap["altitude"]), (50.0755, 6.5, 220.4))
        self.assertEqual(snap["age_ms"], 2000)
        clock.advance(12.9)
        self.assertTrue(st.snapshot()["valid"])
        self.assertEqual(st.snapshot()["age_ms"], 14900)
        self.assertAlmostEqual(st.expires_in(), 0.1, places=5)
        clock.advance(0.1)
        st.check()
        self.assertFalse(st.snapshot()["valid"])
        self.assertFalse(changes[-1]["valid"])

    def test_phone_clock_is_ignored(self):
        clock = Clock()
        st = location.LocationState(clock)
        st.update("s1", self.upd(timestamp_ms=0, age_ms=0))           # hodiny telefonu v roce 1970
        self.assertTrue(st.snapshot()["valid"])

    def test_disable_and_disconnect(self):
        clock = Clock()
        st = location.LocationState(clock)
        st.update("s1", self.upd())
        st.set_status("s1", False)
        self.assertFalse(st.snapshot()["valid"])
        self.assertFalse(st.update("s1", self.upd()))                 # po enabled:false se fix nepouzije
        st.set_status("s1", True)
        self.assertTrue(st.update("s1", self.upd()))
        st.drop("s1")
        self.assertFalse(st.snapshot()["valid"])
        st.update("s2", self.upd())
        st.set_enabled(False)
        self.assertFalse(st.snapshot()["valid"])

    def test_validation(self):
        st = location.LocationState(Clock())
        for kw in (dict(latitude=91), dict(longitude=-180.5), dict(latitude="50"), dict(latitude=True),
                   dict(accuracy_m=-1), dict(accuracy_m=float("inf")), dict(age_ms=15001), dict(age_ms=-5),
                   dict(timestamp_ms=1.5), dict(timestamp_ms=-1), dict(bearing_deg=361), dict(speed_mps=-0.1),
                   dict(mock="no"), dict(latitude=None)):
            with self.assertRaises(location.InvalidLocation, msg=kw):
                st.update("s1", self.upd(**kw))
        m = self.upd()
        for k in ("altitude_m", "speed_mps", "bearing_deg", "mock"):
            del m[k]
        st.update("s1", m)
        snap = st.snapshot()
        self.assertNotIn("altitude", snap)
        self.assertFalse(snap["mock"])

    def test_newest_of_two_phones_and_reordering(self):
        clock = Clock()
        st = location.LocationState(clock)
        st.update("a", self.upd(latitude=1.0))
        clock.advance(1)
        st.update("b", self.upd(latitude=2.0))
        self.assertEqual(st.snapshot()["latitude"], 2.0)
        self.assertFalse(st.update("b", self.upd(latitude=3.0, age_ms=5000)))   # starsi nez posledni
        self.assertEqual(st.snapshot()["latitude"], 2.0)

    def test_via_protocol(self):
        clock = Clock()
        svc = make_service(clock)
        s, phone = connect(svc)
        phone.send("hello", "h1", protocol=1)
        phone.wait(1)
        phone.send("location.status", enabled=True)
        m = self.upd()
        phone.send("location.update", **{k: v for k, v in m.items() if k not in ("v", "type", "id")})
        self.assertTrue(pump(lambda: svc.location.snapshot()["valid"]))
        self.assertEqual(svc.location.snapshot()["device"], "Pixel Test")
        bad = phone.send("location.update", latitude=123, longitude=0, accuracy_m=1, timestamp_ms=1, age_ms=1)
        err = phone.wait(1)[0]
        self.assertEqual((err["code"], err["reply_to"]), ("invalid_location", bad))
        # vypnute sdileni v nastaveni: fixy se zahazuji
        svc.settings.set("share_location", False)
        svc.reload_settings()
        self.assertFalse(svc.location.snapshot()["valid"])
        phone.send("location.update", **{k: v for k, v in m.items() if k not in ("v", "type", "id")})
        phone.send("ping", "p")
        phone.wait(1)
        self.assertFalse(svc.location.snapshot()["valid"])
        svc.settings.set("share_location", True)
        svc.reload_settings()
        phone.send("location.update", **{k: v for k, v in m.items() if k not in ("v", "type", "id")})
        self.assertTrue(pump(lambda: svc.location.snapshot()["valid"]))
        # odpojeni okamzite zrusi polohu
        phone.sock.close()
        self.assertTrue(pump(lambda: not svc.location.snapshot()["valid"]))

    def test_timeout_drops_location(self):
        clock = Clock()
        svc = make_service(clock)
        s, phone = connect(svc)
        phone.send("hello", "h1", protocol=1)
        phone.wait(1)
        m = self.upd()
        phone.send("location.update", **{k: v for k, v in m.items() if k not in ("v", "type", "id")})
        self.assertTrue(pump(lambda: svc.location.snapshot()["valid"]))
        clock.advance(45)
        svc.tick()
        self.assertEqual(s.close_reason, "idle_timeout")
        self.assertFalse(svc.location.snapshot()["valid"])


class TestStore(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(fresh_dir("store"), "companion.json")

    def test_defaults_and_approval(self):
        st = store.Settings(self.path)
        self.assertEqual((st.get("share_location"), st.get("allow_luxai"), st.get("allow_calendar")),
                         (True, True, True))
        self.assertFalse(st.is_approved("AA:BB:CC:DD:EE:FF"))
        st.approve("aa-bb-cc-dd-ee-ff", "Můj\x1b[31m telefon")
        self.assertTrue(st.is_approved("AA:BB:CC:DD:EE:FF"))
        self.assertEqual(st.phones(), [("AA:BB:CC:DD:EE:FF", "Můj[31m telefon")])
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        st.remove("AA:BB:CC:DD:EE:FF")
        self.assertFalse(store.Settings(self.path).is_approved("AA:BB:CC:DD:EE:FF"))
        with self.assertRaises(ValueError):
            st.approve("not-an-address", "x")

    def test_concurrent_modifications_kept(self):
        a, b = store.Settings(self.path), store.Settings(self.path)
        a.approve("AA:BB:CC:DD:EE:01", "A")
        b.set("allow_luxai", False)          # b melo stara data - zamek + nove nacteni nic neztrati
        c = store.Settings(self.path)
        self.assertTrue(c.is_approved("AA:BB:CC:DD:EE:01"))
        self.assertFalse(c.get("allow_luxai"))

    def test_garbage_file(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        for content in ("{", "[]", json.dumps({"phones": {"bad": {}, "AA:BB:CC:DD:EE:02": "x"},
                                                "share_location": "yes"})):
            with open(self.path, "w") as f:
                f.write(content)
            st = store.Settings(self.path)
            self.assertEqual(st.phones(), [])
            self.assertTrue(st.get("share_location"))
        self.assertTrue(store.read_toggle("share_location", self.path))


class TestLuxAI(unittest.TestCase):
    def setUp(self):
        self.log = os.path.join(fresh_dir("luxai"), "log.jsonl")
        os.environ["FAKE_LUXAI_LOG"] = self.log
        os.environ.pop("FAKE_LUXAI_MODE", None)
        self.svc = make_service()
        self.s, self.phone = connect(self.svc)
        self.phone.send("hello", "h1", protocol=1)
        self.phone.wait(1)

    def tearDown(self):
        self.s.close("test")
        os.environ.pop("FAKE_LUXAI_MODE", None)

    def ask(self, text, mode="chat", rid=None):
        return self.phone.send("luxai.request", rid, text=text, mode=mode)

    def until_done(self, rid, timeout=8):
        got = []
        pump(lambda: got.extend(self.phone.messages()) or any(
            m.get("reply_to") == rid and m["type"] in ("luxai.done", "error") for m in got), timeout)
        return got

    def logged(self):
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(x) for x in f]

    def test_stream_and_conversation(self):
        rid = self.ask("Najdi moje poznámky k projektu.", "agent")
        got = self.until_done(rid)
        self.assertEqual([m["type"] for m in got], ["luxai.delta", "luxai.delta", "luxai.done"])
        self.assertTrue(all(m["reply_to"] == rid for m in got))
        self.assertEqual("".join(m["text"] for m in got[:2]), "Echo #1 (agent): Najdi moje poznámky k projektu.")
        self.assertNotIn("text", got[2])
        rid2 = self.ask("druhá")
        got = self.until_done(rid2)
        self.assertIn("Echo #2", "".join(m.get("text", "") for m in got))   # stejna konverzace
        log = self.logged()
        self.assertEqual(log[0]["argv"], ["--remote-session"])
        sent_ids = [x["id"] for x in log if x.get("type") == "request"]
        self.assertNotIn(rid, sent_ids)                                       # vlastni UUID mostu
        self.assertEqual(len([x for x in log if "pid" in x]), 1)              # jeden proces na spojeni

    def test_busy_and_cancel(self):
        rid = self.ask("slow")
        got = []
        pump(lambda: got.extend(self.phone.messages()) or any(m["type"] == "luxai.delta" for m in got), 8)
        rid2 = self.ask("druhá")
        err = self.until_done(rid2)
        self.assertEqual([(m["type"], m.get("code")) for m in err if m.get("reply_to") == rid2], [("error", "busy")])
        self.phone.send("luxai.cancel", request_id=rid)
        self.assertTrue(pump(lambda: self.s.luxai.active is None, 8))
        late = self.phone.messages()
        self.assertEqual([m for m in late if m.get("reply_to") == rid], [])   # done po zruseni se neposila
        self.assertTrue(any(x.get("type") == "cancel" for x in self.logged()))
        rid3 = self.ask("po zrušení")
        self.assertEqual(self.until_done(rid3)[-1]["type"], "luxai.done")

    def test_error_and_crash(self):
        rid = self.ask("fail")
        got = self.until_done(rid)
        self.assertEqual((got[-1]["type"], got[-1]["code"], got[-1]["message"]),
                         ("error", "provider_error", "Model is not reachable."))
        rid = self.ask("crash")
        got = self.until_done(rid)
        self.assertEqual((got[-1]["type"], got[-1]["code"]), ("error", "luxai_failed"))
        rid = self.ask("znovu")                                             # novy proces
        self.assertEqual(self.until_done(rid)[-1]["type"], "luxai.done")

    def test_big_delta_is_split_into_frames(self):
        rid = self.ask("big")
        got = self.until_done(rid)
        deltas = [m for m in got if m["type"] == "luxai.delta"]
        self.assertGreater(len(deltas), 1)
        self.assertEqual("".join(m["text"] for m in deltas), "ž" * 30000)

    def test_old_luxai_unavailable(self):
        os.environ["FAKE_LUXAI_MODE"] = "old"
        rid = self.ask("ahoj")
        got = self.until_done(rid)
        self.assertEqual((got[-1]["type"], got[-1]["code"]), ("error", "luxai_unavailable"))
        self.assertIn("luxai --remote-session", got[-1]["message"])

    def test_missing_luxai(self):
        old = os.environ["LUXOS_COMPANION_LUXAI"]
        os.environ["LUXOS_COMPANION_LUXAI"] = "/nonexistent/luxai"
        try:
            rid = self.ask("ahoj")
            got = self.until_done(rid)
        finally:
            os.environ["LUXOS_COMPANION_LUXAI"] = old
        self.assertEqual(got[-1]["code"], "luxai_unavailable")

    def test_invalid_requests_and_permission(self):
        for kw, code in ((dict(text=""), "invalid_request"), (dict(text="x" * 8001), "invalid_request"),
                         (dict(text="ok", mode="shell"), "invalid_request")):
            kw.setdefault("mode", "chat")
            rid = self.phone.send("luxai.request", **kw)
            self.assertEqual(self.until_done(rid)[-1]["code"], code)
        self.svc.settings.set("allow_luxai", False)
        rid = self.ask("ahoj")
        self.assertEqual(self.until_done(rid)[-1]["code"], "permission_denied")
        self.assertFalse(os.path.exists(self.log))                          # LuxAI se vubec nespustil

    def test_disconnect_stops_luxai(self):
        rid = self.ask("slow")
        pump(lambda: os.path.exists(self.log) and any(x.get("type") == "request" for x in self.logged()), 8)
        pid = self.logged()[0]["pid"]
        self.phone.sock.close()
        self.assertTrue(pump(lambda: not os.path.exists(f"/proc/{pid}") or
                             open(f"/proc/{pid}/stat").read().split()[2] == "Z", 8))

    def test_shell_text_is_data(self):
        rid = self.ask("$(touch /tmp/should-not-exist-companion); rm -rf ~")
        self.until_done(rid)
        self.assertFalse(os.path.exists("/tmp/should-not-exist-companion"))
        req = [x for x in self.logged() if x.get("type") == "request"][0]
        self.assertEqual(req["text"], "$(touch /tmp/should-not-exist-companion); rm -rf ~")


class TestTranslations(unittest.TestCase):
    LANGS = ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv")

    def strings(self):
        import re
        found = set()
        for name in os.listdir(os.path.join(helpers.FILES, "luxos_companion")):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(helpers.FILES, "luxos_companion", name), encoding="utf-8") as f:
                src = f.read()
            for m in re.finditer(r'(?<![A-Za-z_.])_\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)\)', src):
                found.add("".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))))
        return found

    def test_all_strings_translated(self):
        strings = self.strings()
        self.assertGreater(len(strings), 40)
        for lang in self.LANGS:
            with open(os.path.join(helpers.ROOT, "luxos-i18n", "files", f"{lang}.tsv"), encoding="utf-8") as f:
                tr = dict(line.rstrip("\n").split("\t", 1) for line in f if "\t" in line and not line.startswith("#"))
            missing = sorted(s for s in strings if not tr.get(s))
            self.assertEqual(missing, [], lang)
            for s in strings:
                self.assertEqual(tr[s].count("%s"), s.count("%s"), (lang, s))


def tearDownModule():
    import shutil
    shutil.rmtree(helpers.TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
