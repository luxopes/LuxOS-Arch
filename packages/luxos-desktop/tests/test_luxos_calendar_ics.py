"""Testy pro luxos_calendar_ics (cteni/zapis iCalendar, opakovani, datumova matematika).

Spusteni: python3 -m unittest discover -s packages/luxos-desktop/tests -v
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
import datetime as dt
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "files", "python"))
os.environ["TZ"] = "Europe/Prague"
import time  # noqa: E402

time.tzset()
import luxos_calendar_ics as ics  # noqa: E402

D = dt.date
T = dt.datetime


def days(ev, a, b):
    return [s for s, _e in ev.occurrences(a, b)]


GOOGLE = """BEGIN:VCALENDAR\r
PRODID:-//Google Inc//Google Calendar 70.9054//EN\r
VERSION:2.0\r
CALSCALE:GREGORIAN\r
X-WR-CALNAME:Prace\r
BEGIN:VTIMEZONE\r
TZID:Europe/Prague\r
END:VTIMEZONE\r
BEGIN:VEVENT\r
DTSTART;TZID=Europe/Prague:20261020T090000\r
DTEND;TZID=Europe/Prague:20261020T103000\r
RRULE:FREQ=WEEKLY;BYDAY=TU,TH;COUNT=4\r
DTSTAMP:20261001T000000Z\r
UID:abc123@google.com\r
SEQUENCE:2\r
X-GOOGLE-CONFERENCE:https://meet.example/xyz\r
SUMMARY:Standup\\, tym\r
DESCRIPTION:Radek 1\\nRadek 2 se strednikem\\; a lomitkem \\\\\r
  pokracovani\r
BEGIN:VALARM\r
ACTION:DISPLAY\r
TRIGGER:-PT15M\r
X-WR-ALARMUID:1\r
END:VALARM\r
END:VEVENT\r
BEGIN:VTODO\r
UID:todo1\r
SUMMARY:Nekomponenta\r
END:VTODO\r
END:VCALENDAR\r
"""

# Tydenni schuzka v New Yorku (C-13): DST v USA (8. 3., 1. 11.) a v Evrope (29. 3., 25. 10.) se lisi
NY_WEEKLY = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:ny@example.com
DTSTART;TZID=America/New_York:20260302T090000
DTEND;TZID=America/New_York:20260302T100000
RRULE:FREQ=WEEKLY;COUNT=40
EXDATE;TZID=America/New_York:20260309T090000
SUMMARY:NY
END:VEVENT
BEGIN:VEVENT
UID:ny@example.com
RECURRENCE-ID;TZID=America/New_York:20260316T090000
DTSTART;TZID=America/New_York:20260316T110000
DTEND;TZID=America/New_York:20260316T120000
SUMMARY:NY presunuto
END:VEVENT
END:VCALENDAR
"""

# RDATE (C-14): seznam, TZID, PERIOD, DATE; EXDATE plati i pro RDATE
RDATES = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:rd
DTSTART:20261019T090000
DTEND:20261019T100000
RDATE:20261021T140000,20261023T090000
RDATE;TZID=America/New_York:20261024T090000
RDATE;VALUE=PERIOD:20261026T080000Z/PT1H
RDATE;VALUE=DATE:20261027
EXDATE:20261023T090000
SUMMARY:Extra
END:VEVENT
BEGIN:VEVENT
UID:rd2
DTSTART;VALUE=DATE:20261001
RRULE:FREQ=MONTHLY;COUNT=2
RDATE;VALUE=DATE:20261015
SUMMARY:Cely den
END:VEVENT
END:VCALENDAR
"""

# STATUS:CANCELLED (C-18): zrusena udalost a zruseny jediny vyskyt serie
CANCELLED = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:s
DTSTART:20261019T090000
DTEND:20261019T100000
RRULE:FREQ=DAILY;COUNT=3
SUMMARY:Serie
END:VEVENT
BEGIN:VEVENT
UID:s
RECURRENCE-ID:20261020T090000
DTSTART:20261020T090000
DTEND:20261020T100000
STATUS:CANCELLED
SUMMARY:Serie
END:VEVENT
BEGIN:VEVENT
UID:z
DTSTART:20261019T100000
DTEND:20261019T110000
STATUS:CANCELLED
SUMMARY:Zruseno
END:VEVENT
END:VCALENDAR
"""

# Serie s presunutym vyskytem (RECURRENCE-ID) - C-03
MOVED = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:s\nDTSTART:20261019T090000\nDTEND:20261019T100000\n"
         "RRULE:FREQ=DAILY;COUNT=3\nSUMMARY:Serie\nEND:VEVENT\n"
         "BEGIN:VEVENT\nUID:s\nRECURRENCE-ID:20261020T090000\nDTSTART:20261020T150000\n"
         "DTEND:20261020T160000\nSUMMARY:Presunuto\nEND:VEVENT\nEND:VCALENDAR\n")


class TestDateMath(unittest.TestCase):
    def test_leap(self):
        self.assertTrue(ics.is_leap(2024))
        self.assertTrue(ics.is_leap(2000))
        self.assertFalse(ics.is_leap(1900))
        self.assertFalse(ics.is_leap(2026))
        self.assertEqual(ics.days_in_month(2024, 2), 29)
        self.assertEqual(ics.days_in_month(2026, 2), 28)
        self.assertEqual(ics.days_in_month(2100, 2), 28)
        self.assertEqual(ics.days_in_month(2026, 12), 31)

    def test_grid_monday_first(self):
        g = ics.month_grid(2026, 10)
        self.assertEqual(len(g), 6)
        self.assertTrue(all(len(w) == 7 for w in g))
        self.assertTrue(all(w[0].weekday() == 0 for w in g))  # kazdy tyden zacina pondelim
        self.assertEqual(g[0][0], D(2026, 9, 28))  # 1. 10. 2026 je ctvrtek
        self.assertEqual(g[0][3], D(2026, 10, 1))
        flat = [d for w in g for d in w]
        self.assertEqual(sum(1 for d in flat if d.month == 10), 31)
        self.assertEqual(flat, sorted(flat))
        self.assertEqual(len(set(flat)), 42)

    def test_grid_leap_february(self):
        g = ics.month_grid(2024, 2)
        flat = [d for w in g for d in w]
        self.assertIn(D(2024, 2, 29), flat)
        self.assertEqual(sum(1 for d in flat if d.month == 2), 29)
        g = ics.month_grid(2026, 2)  # 1. 2. 2026 je nedele -> 6 dnu ledna predem
        self.assertEqual(g[0][0], D(2026, 1, 26))
        self.assertEqual(g[0][6], D(2026, 2, 1))
        self.assertEqual(sum(1 for w in g for d in w if d.month == 2), 28)

    def test_month_starting_monday(self):
        g = ics.month_grid(2027, 2)  # 1. 2. 2027 je pondeli a mesic ma presne 4 tydny
        self.assertEqual(g[0][0], D(2027, 2, 1))
        self.assertEqual(ics.weeks_needed(2027, 2), 4)
        self.assertEqual(ics.weeks_needed(2026, 3), 6)   # 1. 3. 2026 nedele, 31 dni
        self.assertEqual(ics.weeks_needed(2026, 10), 5)

    def test_sunday_first_option(self):
        g = ics.month_grid(2026, 10, first_weekday=6)
        self.assertEqual(g[0][0].weekday(), 6)
        self.assertEqual(g[0][0], D(2026, 9, 27))

    def test_add_months(self):
        self.assertEqual(ics.add_months(2026, 12, 1), (2027, 1))
        self.assertEqual(ics.add_months(2026, 1, -1), (2025, 12))
        self.assertEqual(ics.add_months(2026, 10, -22), (2024, 12))


class TestLowLevel(unittest.TestCase):
    def test_fold_unfold_utf8(self):
        long = "SUMMARY:" + "Příliš žluťoučký kůň úpěl ďábelské ódy " * 5
        folded = ics.fold(long)
        for part in folded.split("\r\n"):
            self.assertLessEqual(len(part.encode("utf-8")), 75)
        self.assertEqual(ics.unfold(folded), [long])

    def test_escape(self):
        s = "a,b;c\\d\ne"
        self.assertEqual(ics.unescape(ics.escape(s)), s)

    def test_parse_line_quoted(self):
        name, params, value = ics.parse_line('ATTENDEE;CN="Novak: Jan";ROLE=REQ:mailto:jan@example.com')
        self.assertEqual(name, "ATTENDEE")
        self.assertEqual(params["CN"], "Novak: Jan")
        self.assertEqual(value, "mailto:jan@example.com")
        self.assertIsNone(ics.parse_line("bez dvojtecky"))

    def test_parse_dt(self):
        self.assertEqual(ics.parse_dt("20261020"), D(2026, 10, 20))
        self.assertEqual(ics.parse_dt("20261020", {"VALUE": "DATE"}), D(2026, 10, 20))
        self.assertEqual(ics.parse_dt("20261020T090000"), T(2026, 10, 20, 9))
        # UTC -> Praha (letni cas do 25. 10. 2026: UTC+2, pak UTC+1)
        self.assertEqual(ics.parse_dt("20261020T070000Z"), T(2026, 10, 20, 9))
        self.assertEqual(ics.parse_dt("20261026T080000Z"), T(2026, 10, 26, 9))
        self.assertEqual(ics.parse_dt("20261020T090000", {"TZID": "America/New_York"}), T(2026, 10, 20, 15))
        self.assertEqual(ics.parse_dt("20261020T090000", {"TZID": "Nesmysl/Zona"}), T(2026, 10, 20, 9))
        with self.assertRaises(ValueError):
            ics.parse_dt("2026-10-20")

    def test_duration(self):
        self.assertEqual(ics.parse_duration("-PT10M"), -dt.timedelta(minutes=10))
        self.assertEqual(ics.parse_duration("P1DT2H"), dt.timedelta(days=1, hours=2))
        self.assertEqual(ics.parse_duration("P2W"), dt.timedelta(weeks=2))
        with self.assertRaises(ValueError):
            ics.parse_duration("P")


class TestReadWrite(unittest.TestCase):
    def test_google_import(self):
        cal = ics.parse(GOOGLE)
        self.assertEqual(cal.errors, 0)
        self.assertEqual(len(cal.events), 1)
        ev = cal.events[0]
        self.assertEqual(ev.uid, "abc123@google.com")
        self.assertEqual(ev.summary, "Standup, tym")
        self.assertEqual(ev.description, "Radek 1\nRadek 2 se strednikem; a lomitkem \\ pokracovani")
        self.assertEqual(ev.start, T(2026, 10, 20, 9))
        self.assertEqual(ev.end, T(2026, 10, 20, 10, 30))
        self.assertEqual(ev.reminder_minutes(), 15)
        self.assertEqual(days(ev, D(2026, 10, 1), D(2026, 12, 1)),
                         [T(2026, 10, 20, 9), T(2026, 10, 22, 9), T(2026, 10, 27, 9), T(2026, 10, 29, 9)])

    def test_round_trip_preserves_unknown(self):
        cal = ics.parse(GOOGLE)
        text = cal.to_text("Europe/Prague")
        for needle in ("X-WR-CALNAME:Prace", "CALSCALE:GREGORIAN", "SEQUENCE:2", "X-GOOGLE-CONFERENCE:https://meet.example/xyz",
                       "DTSTAMP:20261001T000000Z", "BEGIN:VTODO", "SUMMARY:Nekomponenta", "BEGIN:VTIMEZONE",
                       "X-WR-ALARMUID:1", "RRULE:FREQ=WEEKLY;BYDAY=TU,TH;COUNT=4"):
            self.assertIn(needle, text.replace("\r\n ", ""))
        self.assertTrue(all(line.endswith("\r") or line == "" for line in text.split("\n")))
        cal2 = ics.parse(text)
        e1, e2 = cal.events[0], cal2.events[0]
        for attr in ("uid", "summary", "description", "start", "end", "rrule_raw"):
            self.assertEqual(getattr(e1, attr), getattr(e2, attr), attr)
        self.assertEqual(sorted(e1.extra), sorted(e2.extra))
        self.assertEqual(e1.alarms, e2.alarms)
        self.assertEqual(len(cal2.other), 2)
        self.assertEqual(cal2.to_text("Europe/Prague").replace(_stamp(cal2), ""),
                         ics.parse(cal2.to_text("Europe/Prague")).to_text("Europe/Prague").replace(_stamp(cal2), ""))

    def test_all_day_round_trip(self):
        cal = ics.Calendar()
        ev = ics.Event("Dovolená – Šumava", D(2026, 10, 26), D(2026, 10, 31), color="green")
        cal.events.append(ev)
        text = cal.to_text()
        self.assertIn("DTSTART;VALUE=DATE:20261026", text)
        self.assertIn("DTEND;VALUE=DATE:20261031", text)
        ev2 = ics.parse(text).events[0]
        self.assertTrue(ev2.all_day)
        self.assertEqual((ev2.start, ev2.end, ev2.summary, ev2.color), (ev.start, ev.end, ev.summary, "green"))
        self.assertEqual(days(ev2, D(2026, 10, 30), D(2026, 10, 31)), [D(2026, 10, 26)])  # zasahuje do 30.
        self.assertEqual(days(ev2, D(2026, 10, 31), D(2026, 11, 1)), [])  # DTEND je exkluzivni

    def test_all_day_without_dtend(self):
        ev = ics.parse("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nDTSTART;VALUE=DATE:20261020\nSUMMARY:Den\n"
                       "END:VEVENT\nEND:VCALENDAR\n").events[0]
        self.assertEqual(ev.duration(), dt.timedelta(days=1))
        self.assertEqual(days(ev, D(2026, 10, 20), D(2026, 10, 21)), [D(2026, 10, 20)])
        self.assertEqual(days(ev, D(2026, 10, 21), D(2026, 10, 22)), [])

    def test_duration_property_and_lf_files(self):
        ev = ics.parse("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:d\nDTSTART:20261020T080000Z\nDURATION:PT45M\n"
                       "SUMMARY:Kratka\nEND:VEVENT\nEND:VCALENDAR\n").events[0]
        self.assertEqual(ev.end - ev.start, dt.timedelta(minutes=45))

    def test_timed_round_trip_with_tzid(self):
        cal = ics.Calendar()
        ev = ics.Event("Schůzka", T(2026, 10, 20, 14, 30), T(2026, 10, 20, 15, 15), color="purple")
        ev.set_reminder(10)
        ev.set_rrule("FREQ=MONTHLY;COUNT=3")
        cal.events.append(ev)
        text = cal.to_text("Europe/Prague")
        self.assertIn("DTSTART;TZID=Europe/Prague:20261020T143000", text)
        self.assertIn("TRIGGER:-PT10M", text)
        ev2 = ics.parse(text).events[0]
        self.assertEqual((ev2.start, ev2.end, ev2.reminder_minutes(), ev2.rrule_raw),
                         (ev.start, ev.end, 10, "FREQ=MONTHLY;COUNT=3"))
        ev2.set_reminder(None)
        self.assertEqual(ev2.alarms, [])

    def test_broken_event_is_kept(self):
        text = ("BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:bad\nSUMMARY:Bez data\nEND:VEVENT\n"
                "BEGIN:VEVENT\nUID:ok\nDTSTART:20261020T100000\nSUMMARY:OK\nEND:VEVENT\n"
                "nesmyslny radek\nEND:VCALENDAR\n")
        cal = ics.parse(text)
        self.assertEqual(cal.errors, 1)
        self.assertEqual([e.uid for e in cal.events], ["ok"])
        self.assertIn("UID:bad", cal.to_text())  # chybny zaznam se pri zapisu neztrati

    def test_bom_and_empty(self):
        self.assertEqual(ics.parse("﻿BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n").events, [])
        self.assertEqual(ics.parse("").events, [])


class TestRecurrence(unittest.TestCase):
    def ev(self, start, rrule, end=None):
        e = ics.Event("R", start, end)
        e.set_rrule(rrule)
        return e

    def test_daily_count(self):
        e = self.ev(T(2026, 10, 30, 8), "FREQ=DAILY;COUNT=3", T(2026, 10, 30, 9))
        self.assertEqual(days(e, D(2026, 10, 1), D(2026, 12, 1)),
                         [T(2026, 10, 30, 8), T(2026, 10, 31, 8), T(2026, 11, 1, 8)])
        # pocet se pocita od zacatku, ne od okna
        self.assertEqual(days(e, D(2026, 11, 1), D(2026, 12, 1)), [T(2026, 11, 1, 8)])

    def test_daily_interval_until(self):
        e = self.ev(D(2026, 10, 1), "FREQ=DAILY;INTERVAL=10;UNTIL=20261031")
        self.assertEqual(days(e, D(2026, 9, 1), D(2027, 1, 1)), [D(2026, 10, 1), D(2026, 10, 11), D(2026, 10, 21), D(2026, 10, 31)])

    def test_daily_filters_weekdays_before_counting(self):
        e = self.ev(D(2026, 10, 23), "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR;COUNT=4")
        self.assertEqual(days(e, D(2026, 10, 1), D(2026, 11, 1)),
                         [D(2026, 10, 23), D(2026, 10, 26), D(2026, 10, 27), D(2026, 10, 28)])

    def test_daily_filters_month_days(self):
        e = self.ev(D(2026, 10, 31), "FREQ=DAILY;BYMONTHDAY=-1;COUNT=3")
        self.assertEqual(days(e, D(2026, 10, 1), D(2027, 1, 1)),
                         [D(2026, 10, 31), D(2026, 11, 30), D(2026, 12, 31)])

    def test_daily_filter_with_no_matching_dates(self):
        e = self.ev(D(2026, 1, 1), "FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30")
        self.assertEqual(days(e, D(2026, 1, 1), D(2026, 3, 1)), [D(2026, 1, 1)])

    def test_monthly_intersects_month_days_and_weekdays(self):
        e = self.ev(D(2026, 10, 5), "FREQ=MONTHLY;BYMONTHDAY=1,2,3,4,5,6,7;BYDAY=MO;COUNT=3")
        self.assertEqual(days(e, D(2026, 10, 1), D(2027, 1, 1)),
                         [D(2026, 10, 5), D(2026, 11, 2), D(2026, 12, 7)])

    def test_monthly_intersection_with_ordinal_weekday(self):
        e = self.ev(D(2026, 10, 30), "FREQ=MONTHLY;BYMONTHDAY=-1,-2,-3;BYDAY=-1FR;COUNT=2")
        self.assertEqual(days(e, D(2026, 10, 1), D(2027, 6, 1)),
                         [D(2026, 10, 30), D(2027, 1, 29)])

    def test_until_utc_inclusive(self):
        e = self.ev(T(2026, 10, 1, 9), "FREQ=DAILY;UNTIL=20261003T070000Z")  # 9:00 Praha = 7:00 UTC
        self.assertEqual(len(days(e, D(2026, 9, 1), D(2026, 12, 1))), 3)

    def test_weekly(self):
        e = self.ev(T(2026, 10, 20, 9), "FREQ=WEEKLY;UNTIL=20261110T235959Z")
        self.assertEqual(days(e, D(2026, 10, 1), D(2027, 1, 1)),
                         [T(2026, 10, 20, 9), T(2026, 10, 27, 9), T(2026, 11, 3, 9), T(2026, 11, 10, 9)])

    def test_weekly_byday_interval(self):
        e = self.ev(D(2026, 10, 19), "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR;COUNT=5")
        self.assertEqual(days(e, D(2026, 1, 1), D(2027, 1, 1)),
                         [D(2026, 10, 19), D(2026, 10, 23), D(2026, 11, 2), D(2026, 11, 6), D(2026, 11, 16)])

    def test_monthly_skips_short_months(self):
        e = self.ev(D(2026, 1, 31), "FREQ=MONTHLY;COUNT=4")
        self.assertEqual(days(e, D(2026, 1, 1), D(2027, 1, 1)),
                         [D(2026, 1, 31), D(2026, 3, 31), D(2026, 5, 31), D(2026, 7, 31)])

    def test_monthly_byday_last_friday(self):
        e = self.ev(D(2026, 10, 30), "FREQ=MONTHLY;BYDAY=-1FR;COUNT=3")
        self.assertEqual(days(e, D(2026, 1, 1), D(2027, 6, 1)), [D(2026, 10, 30), D(2026, 11, 27), D(2026, 12, 25)])

    def test_dtstart_not_matching_rule_is_first(self):
        e = self.ev(D(2026, 10, 20), "FREQ=MONTHLY;BYDAY=-1FR;COUNT=3")  # utery, pravidlo = posledni patek
        self.assertEqual(days(e, D(2026, 1, 1), D(2027, 6, 1)), [D(2026, 10, 20), D(2026, 10, 30), D(2026, 11, 27)])

    def test_yearly_leap_day(self):
        e = self.ev(D(2024, 2, 29), "FREQ=YEARLY;COUNT=3")
        self.assertEqual(days(e, D(2024, 1, 1), D(2040, 1, 1)), [D(2024, 2, 29), D(2028, 2, 29), D(2032, 2, 29)])

    def test_yearly_infinite_birthday(self):
        e = self.ev(D(1990, 10, 20), "FREQ=YEARLY", D(1990, 10, 21))
        self.assertEqual(days(e, D(2026, 10, 20), D(2026, 10, 21)), [D(2026, 10, 20)])
        self.assertEqual(days(e, D(2026, 10, 21), D(2027, 10, 20)), [])

    def test_exdate(self):
        text = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nDTSTART:20261019T090000\nDTEND:20261019T100000\n"
                "RRULE:FREQ=DAILY;COUNT=5\nEXDATE:20261020T090000,20261022T090000\nEND:VEVENT\nEND:VCALENDAR\n")
        e = ics.parse(text).events[0]
        self.assertEqual(days(e, D(2026, 10, 1), D(2026, 11, 1)),
                         [T(2026, 10, 19, 9), T(2026, 10, 21, 9), T(2026, 10, 23, 9)])
        self.assertIn("EXDATE:20261020T090000,20261022T090000", ics.parse(text).to_text())

    def test_unsupported_freq_shows_first(self):
        e = self.ev(T(2026, 10, 20, 9), "FREQ=HOURLY;COUNT=5")
        self.assertEqual(days(e, D(2026, 10, 1), D(2026, 11, 1)), [T(2026, 10, 20, 9)])

    def test_pathological_rules_terminate(self):
        e = self.ev(D(2026, 1, 1), "FREQ=MONTHLY;BYMONTHDAY=40")  # pravidlo nic nevytvori, zbude DTSTART
        self.assertEqual(days(e, D(2026, 1, 1), D(2027, 1, 1)), [D(2026, 1, 1)])
        e = self.ev(D(2026, 1, 1), "FREQ=DAILY;BYMONTH=13")  # neplatny mesic se ignoruje
        self.assertEqual(len(days(e, D(2026, 1, 1), D(2026, 1, 8))), 7)

    def test_overnight_event_spans_two_days(self):
        e = ics.Event("Noc", T(2026, 10, 20, 22), T(2026, 10, 21, 2))
        self.assertEqual(len(e.occurrences(D(2026, 10, 21), D(2026, 10, 22))), 1)
        self.assertEqual(len(e.occurrences(D(2026, 10, 22), D(2026, 10, 23))), 0)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_store_crud_and_foreign(self):
        with open(os.path.join(self.dir, "google.ics"), "wb") as f:
            f.write(GOOGLE.encode())
        st = ics.Store(self.dir)
        self.assertTrue(st.reload_if_changed())
        self.assertFalse(st.reload_if_changed())
        ev = ics.Event("Oběd", T(2026, 10, 20, 12), T(2026, 10, 20, 13), color="orange")
        st.add(ev)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "events.ics")))
        items = st.day_instances(D(2026, 10, 20))
        self.assertEqual([i[0].summary for i in items], ["Standup, tym", "Oběd"])
        foreign = items[0][0]
        self.assertTrue(foreign.readonly)
        self.assertEqual(foreign.source, "google.ics")
        own = st.find(ev.uid)
        own.summary = "Oběd s týmem"
        st.update(own)
        st2 = ics.Store(self.dir)
        st2.reload_if_changed()
        self.assertEqual(st2.find(ev.uid).summary, "Oběd s týmem")
        busy = st2.busy_days(D(2026, 10, 1), D(2026, 11, 1))
        self.assertEqual(set(busy), {D(2026, 10, 20), D(2026, 10, 22), D(2026, 10, 27), D(2026, 10, 29)})
        st2.delete(st2.find(ev.uid))
        st3 = ics.Store(self.dir)
        st3.reload_if_changed()
        self.assertEqual(st3.own.events, [])
        with open(os.path.join(self.dir, "google.ics"), "rb") as f:
            self.assertEqual(f.read(), GOOGLE.encode())  # importovany kalendar zustava netknuty
        self.assertFalse([n for n in os.listdir(self.dir) if ".tmp-" in n])

    def test_store_keeps_external_additions(self):
        """Jiny proces (LuxOS Companion) prida udalost; Kalendar ji pri dalsim vlastnim zapisu neztrati."""
        st = ics.Store(self.dir)
        st.reload_if_changed()
        a = ics.Event("A", T(2026, 10, 20, 8), T(2026, 10, 20, 9))
        st.add(a)
        st2 = ics.Store(self.dir)
        st2.reload_if_changed()
        st2.add(ics.Event("Z telefonu", T(2026, 10, 20, 10), T(2026, 10, 20, 11)))
        st.add(ics.Event("C", T(2026, 10, 20, 12), T(2026, 10, 20, 13)))
        st.delete(st.find(a.uid))
        st3 = ics.Store(self.dir)
        st3.reload_if_changed()
        self.assertEqual([i[0].summary for i in st3.day_instances(D(2026, 10, 20))], ["Z telefonu", "C"])

    def test_recurrence_id_override(self):
        text = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:s\nDTSTART:20261019T090000\nDTEND:20261019T100000\n"
                "RRULE:FREQ=DAILY;COUNT=3\nSUMMARY:Serie\nEND:VEVENT\n"
                "BEGIN:VEVENT\nUID:s\nRECURRENCE-ID:20261020T090000\nDTSTART:20261020T150000\n"
                "DTEND:20261020T160000\nSUMMARY:Presunuto\nEND:VEVENT\nEND:VCALENDAR\n")
        with open(os.path.join(self.dir, "events.ics"), "w") as f:
            f.write(text)
        st = ics.Store(self.dir)
        st.reload_if_changed()
        items = st.day_instances(D(2026, 10, 20))
        self.assertEqual([(i[0].summary, i[1]) for i in items], [("Presunuto", T(2026, 10, 20, 15))])
        self.assertEqual(len(st.day_instances(D(2026, 10, 21))), 1)

    def test_sorting_all_day_first(self):
        st = ics.Store(self.dir)
        st.reload_if_changed()
        st.add(ics.Event("B pozde", T(2026, 10, 20, 18), T(2026, 10, 20, 19)))
        st.add(ics.Event("A rano", T(2026, 10, 20, 8), T(2026, 10, 20, 9)))
        st.add(ics.Event("Celodenni", D(2026, 10, 20), D(2026, 10, 21)))
        self.assertEqual([i[0].summary for i in st.day_instances(D(2026, 10, 20))], ["Celodenni", "A rano", "B pozde"])

    def test_colors(self):
        self.assertEqual(ics.event_color(ics.Event(color="purple")), "purple")
        self.assertEqual(ics.event_color(ics.Event(color="DodgerBlue")), "blue")
        e = ics.Event()
        self.assertEqual(ics.event_color(e), ics.DEFAULT_COLOR)
        e.source = "google.ics"
        self.assertIn(ics.event_color(e), ics.COLORS)


class TestRfcFixes(unittest.TestCase):
    """Regresni testy C-13 az C-18 (opakovani podle RFC 5545)."""

    def ev(self, start, rrule, end=None):
        e = ics.Event("R", start, end)
        e.set_rrule(rrule)
        return e

    def test_weekdays_only_never_on_weekend(self):
        # C-15: "kazdy pracovni den" v ruznych zapisech (Google, Outlook s WKST=SU, DAILY + BYDAY)
        for rule in ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "FREQ=WEEKLY;WKST=SU;BYDAY=MO,TU,WE,TH,FR",
                     "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR", "FREQ=WEEKLY;INTERVAL=1;BYDAY=FR,TH,WE,TU,MO;COUNT=30",
                     "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR"):
            for start in (T(2026, 10, 19, 9), D(2026, 10, 19)):
                got = days(self.ev(start, rule), D(2026, 10, 1), D(2027, 1, 1))
                self.assertTrue(got, rule)
                weekend = [d for d in got if d.weekday() >= 5]
                self.assertEqual(weekend, [], rule)
        got = days(self.ev(D(2026, 10, 19), "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR"), D(2026, 10, 19), D(2026, 10, 27))
        self.assertEqual(got, [D(2026, 10, 19), D(2026, 10, 20), D(2026, 10, 21), D(2026, 10, 22), D(2026, 10, 23),
                               D(2026, 10, 26)])

    def test_bysetpos_last_working_day_of_month(self):
        # C-16
        e = self.ev(D(2026, 10, 30), "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1;COUNT=4")
        self.assertEqual(days(e, D(2026, 1, 1), D(2028, 1, 1)),
                         [D(2026, 10, 30), D(2026, 11, 30), D(2026, 12, 31), D(2027, 1, 29)])
        e = self.ev(T(2026, 10, 1, 8), "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1,-1;COUNT=4")
        self.assertEqual(days(e, D(2026, 1, 1), D(2028, 1, 1)),
                         [T(2026, 10, 1, 8), T(2026, 10, 30, 8), T(2026, 11, 2, 8), T(2026, 11, 30, 8)])

    def test_bysetpos_yearly_and_weekly(self):
        # mnozina pro BYSETPOS je cely rok: prvni nedele v breznu a posledni nedele v rijnu
        e = self.ev(D(2026, 3, 1), "FREQ=YEARLY;BYMONTH=3,10;BYDAY=SU;BYSETPOS=1,-1;COUNT=4")
        self.assertEqual(days(e, D(2026, 1, 1), D(2028, 1, 1)),
                         [D(2026, 3, 1), D(2026, 10, 25), D(2027, 3, 7), D(2027, 10, 31)])
        e = self.ev(D(2026, 10, 21), "FREQ=WEEKLY;BYDAY=MO,WE,FR;BYSETPOS=2;COUNT=3")
        self.assertEqual(days(e, D(2026, 1, 1), D(2028, 1, 1)), [D(2026, 10, 21), D(2026, 10, 28), D(2026, 11, 4)])

    def test_exdate_without_rrule(self):
        # C-17
        ev = ics.parse("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nDTSTART:20261020T090000\nDTEND:20261020T100000\n"
                       "EXDATE:20261020T090000\nSUMMARY:Nic\nEND:VEVENT\nEND:VCALENDAR\n").events[0]
        self.assertEqual(days(ev, D(2026, 10, 1), D(2026, 11, 1)), [])
        ev = ics.parse("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nDTSTART;VALUE=DATE:20261020\n"
                       "EXDATE;VALUE=DATE:20261020\nSUMMARY:Nic\nEND:VEVENT\nEND:VCALENDAR\n").events[0]
        self.assertEqual(days(ev, D(2026, 10, 1), D(2026, 11, 1)), [])

    def test_rdate(self):
        # C-14
        cal = ics.parse(RDATES)
        self.assertEqual(days(cal.events[0], D(2026, 10, 1), D(2026, 11, 1)),
                         [T(2026, 10, 19, 9), T(2026, 10, 21, 14), T(2026, 10, 24, 15), T(2026, 10, 26, 9),
                          T(2026, 10, 27, 9)])
        self.assertEqual(days(cal.events[0], D(2026, 10, 24), D(2026, 10, 25)), [T(2026, 10, 24, 15)])
        self.assertEqual(days(cal.events[1], D(2026, 10, 1), D(2027, 1, 1)),
                         [D(2026, 10, 1), D(2026, 10, 15), D(2026, 11, 1)])
        text = cal.to_text("Europe/Prague")
        for needle in ("RDATE:20261021T140000,20261023T090000", "RDATE;TZID=America/New_York:20261024T090000",
                       "RDATE;VALUE=PERIOD:20261026T080000Z/PT1H", "RDATE;VALUE=DATE:20261027",
                       "RDATE;VALUE=DATE:20261015"):
            self.assertIn(needle, text)
        self.assertEqual(text.count("RDATE"), 5)
        self.assertEqual(days(ics.parse(text).events[0], D(2026, 10, 1), D(2026, 11, 1)),
                         days(cal.events[0], D(2026, 10, 1), D(2026, 11, 1)))

    def test_foreign_timezone_recurrence_across_dst(self):
        # C-13: TZ=Europe/Prague, schuzka v 9:00 v New Yorku
        cal = ics.parse(NY_WEEKLY)
        ev = cal.events[0]
        self.assertEqual(days(ev, D(2026, 3, 1), D(2026, 4, 6)),
                         [T(2026, 3, 2, 15), T(2026, 3, 16, 14), T(2026, 3, 23, 14), T(2026, 3, 30, 15)])
        self.assertEqual(days(ev, D(2026, 10, 19), D(2026, 11, 10)),
                         [T(2026, 10, 19, 15), T(2026, 10, 26, 14), T(2026, 11, 2, 15), T(2026, 11, 9, 15)])
        # COUNT=40 konci 30. 11.; UNTIL v UTC (9:00 EST = 14:00Z) je vcetne
        self.assertEqual(days(ev, D(2026, 11, 20), D(2027, 1, 1)), [T(2026, 11, 23, 15), T(2026, 11, 30, 15)])
        until = ics.parse(NY_WEEKLY.replace("COUNT=40", "UNTIL=20261109T140000Z")).events[0]
        self.assertEqual(days(until, D(2026, 11, 1), D(2027, 1, 1)), [T(2026, 11, 2, 15), T(2026, 11, 9, 15)])
        text = cal.to_text("Europe/Prague")
        self.assertIn("DTSTART;TZID=America/New_York:20260302T090000", text)
        self.assertIn("DTEND;TZID=America/New_York:20260302T100000", text)
        self.assertIn("RECURRENCE-ID;TZID=America/New_York:20260316T090000", text)
        self.assertIn("DTSTART;TZID=America/New_York:20260316T110000", text)
        self.assertEqual(days(ics.parse(text).events[0], D(2026, 10, 19), D(2026, 11, 10)),
                         days(ev, D(2026, 10, 19), D(2026, 11, 10)))
        # posunuti udalosti v mistnim case se zapise zpet v puvodnim pasmu
        ev.start = T(2026, 3, 2, 16)
        ev.end = T(2026, 3, 2, 17)
        self.assertIn("DTSTART;TZID=America/New_York:20260302T100000", cal.to_text("Europe/Prague"))

    def test_foreign_timezone_in_store_with_override(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "events.ics"), "w") as f:
                f.write(NY_WEEKLY)
            st = ics.Store(d)
            st.reload_if_changed()
            self.assertEqual([(i[0].summary, i[1]) for i in st.instances(D(2026, 3, 9), D(2026, 3, 17))],
                             [("NY presunuto", T(2026, 3, 16, 16))])
            self.assertEqual([(i[0].summary, i[1]) for i in st.instances(D(2026, 10, 26), D(2026, 10, 27))],
                             [("NY", T(2026, 10, 26, 14))])

    def test_cancelled_events_hidden(self):
        # C-18
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "events.ics"), "w") as f:
                f.write(CANCELLED)
            st = ics.Store(d)
            st.reload_if_changed()
            self.assertEqual([i[0].summary for i in st.day_instances(D(2026, 10, 19))], ["Serie"])
            self.assertEqual(st.day_instances(D(2026, 10, 20)), [])
            self.assertEqual([i[0].summary for i in st.day_instances(D(2026, 10, 21))], ["Serie"])
            self.assertEqual(st.busy_days(D(2026, 10, 1), D(2026, 11, 1)), {D(2026, 10, 19): "blue", D(2026, 10, 21): "blue"})
            # STATUS se pri zapisu zachova
            st.add(ics.Event("Nova", T(2026, 10, 22, 9), T(2026, 10, 22, 10)))
            with open(os.path.join(d, "events.ics")) as f:
                self.assertEqual(f.read().count("STATUS:CANCELLED"), 2)


class TestStoreConcurrency(unittest.TestCase):
    """C-03 (smazani jednoho presunuteho vyskytu) a C-04 (soubezny zapis jineho procesu)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.path = os.path.join(self.dir, "events.ics")

    def tearDown(self):
        self.tmp.cleanup()

    def store(self):
        st = ics.Store(self.dir)
        st.reload_if_changed()
        return st

    def summaries(self, st, day):
        return [(i[0].summary, i[1]) for i in st.day_instances(day)]

    def test_delete_single_moved_occurrence(self):
        with open(self.path, "w") as f:
            f.write(MOVED)
        st = self.store()
        moved = [i[0] for i in st.day_instances(D(2026, 10, 20))][0]
        self.assertIsNotNone(moved.recurrence_id)
        st.delete(moved)
        st2 = self.store()
        self.assertEqual(self.summaries(st2, D(2026, 10, 19)), [("Serie", T(2026, 10, 19, 9))])
        self.assertEqual(self.summaries(st2, D(2026, 10, 20)), [])
        self.assertEqual(self.summaries(st2, D(2026, 10, 21)), [("Serie", T(2026, 10, 21, 9))])
        with open(self.path) as f:
            text = f.read()
        self.assertEqual(text.count("BEGIN:VEVENT"), 1)
        self.assertIn("EXDATE;TZID=Europe/Prague:20261020T090000", text)
        # smazani cele serie dal maze vse
        st2.delete(st2.find("s"))
        self.assertEqual(self.store().own.events, [])

    def test_concurrent_update_keeps_other_changes(self):
        st = self.store()
        st.add(ics.Event("A", T(2026, 10, 20, 8), T(2026, 10, 20, 9), uid="a"))
        st.add(ics.Event("B", T(2026, 10, 20, 10), T(2026, 10, 20, 11), uid="b"))
        other = self.store()                       # LuxOS Companion / druha instance
        b = other.find("b")
        b.summary = "B jinde"
        other.update(b)
        a = st.find("a")                           # Kalendar zmenu jeste nenacetl
        a.summary = "A zde"
        st.update(a)
        self.assertEqual([i[0].summary for i in self.store().day_instances(D(2026, 10, 20))], ["A zde", "B jinde"])

    def test_update_of_event_deleted_elsewhere_is_conflict(self):
        st = self.store()
        st.add(ics.Event("A", T(2026, 10, 20, 8), T(2026, 10, 20, 9), uid="a"))
        st.add(ics.Event("B", T(2026, 10, 20, 10), T(2026, 10, 20, 11), uid="b"))
        other = self.store()
        other.delete(other.find("a"))
        a = st.find("a")
        a.summary = "A zde"
        with self.assertRaises(ics.Conflict):
            st.update(a)
        self.assertEqual([i[0].summary for i in self.store().day_instances(D(2026, 10, 20))], ["B"])
        self.assertIsNone(st.find("a"))           # Kalendar po konfliktu ukazuje stav ze souboru
        # smazani uz smazane udalosti neni chyba a nic nevrati
        st.delete(a)
        self.assertEqual([i[0].summary for i in self.store().day_instances(D(2026, 10, 20))], ["B"])

    def test_delete_does_not_drop_concurrent_edit(self):
        st = self.store()
        st.add(ics.Event("A", T(2026, 10, 20, 8), T(2026, 10, 20, 9), uid="a"))
        st.add(ics.Event("B", T(2026, 10, 20, 10), T(2026, 10, 20, 11), uid="b"))
        other = self.store()
        b = other.find("b")
        b.summary = "B jinde"
        other.update(b)
        st.delete(st.find("a"))
        self.assertEqual([i[0].summary for i in self.store().day_instances(D(2026, 10, 20))], ["B jinde"])

    def test_write_retries_when_file_changes_before_rename(self):
        st = self.store()
        st.add(ics.Event("A", T(2026, 10, 20, 8), T(2026, 10, 20, 9), uid="a"))
        calls = []

        def meanwhile():
            # zapis procesu bez zamku (Kalendar v LSL) mezi ctenim a prejmenovanim
            if not calls:
                calls.append(1)
                cal = ics.read_file(self.path)
                cal.events.append(ics.Event("Z telefonu", T(2026, 10, 20, 10), T(2026, 10, 20, 11), uid="z"))
                with open(self.path + ".jinde", "w", encoding="utf-8", newline="") as f:
                    f.write(cal.to_text("Europe/Prague"))
                os.replace(self.path + ".jinde", self.path)
        st.before_replace = meanwhile
        st.add(ics.Event("C", T(2026, 10, 20, 12), T(2026, 10, 20, 13), uid="c"))
        self.assertEqual(calls, [1])
        self.assertEqual([i[0].summary for i in self.store().day_instances(D(2026, 10, 20))], ["A", "Z telefonu", "C"])
        self.assertFalse([n for n in os.listdir(self.dir) if ".tmp-" in n])


def _stamp(cal):
    """DTSTAMP generovany pri zapisu (lisi se mezi zapisy) - pro porovnani ho odstranime."""
    for line in cal.to_text().split("\r\n"):
        if line.startswith("DTSTAMP:") and line != "DTSTAMP:20261001T000000Z":
            return line
    return "\x00"


if __name__ == "__main__":
    unittest.main()
