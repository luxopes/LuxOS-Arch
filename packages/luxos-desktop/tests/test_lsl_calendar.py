"""Testy modulu luxos_ics/luxos_date v LSL (files/lsl) - stejne pripady jako test_luxos_calendar_ics.py
pro puvodni luxos_calendar_ics.py: cteni/zapis iCalendar, opakovani, datumova matematika, uloziste.

Spusteni: python3 -m unittest packages/luxos-desktop/tests/test_lsl_calendar.py -v
LUXOS_LSLC: cesta k prekladaci lslc (jinak lslc z PATH); potrebuje LSL >= 0.10.5, jinak se testy preskoci.
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LSL = os.path.join(HERE, "..", "files", "lsl")
TMP = tempfile.mkdtemp(prefix="luxos-lsl-cal-")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
sys.path.insert(0, HERE)
from test_luxos_calendar_ics import CANCELLED, GOOGLE, MOVED, NY_WEEKLY, RDATES  # noqa: E402 - stejna data


def build():
    """Prelozi testovaci program s moduly z files/lsl (load hleda vedle zdroje)."""
    if not LSLC:
        return None
    src = os.path.join(TMP, "src")
    os.makedirs(src, exist_ok=True)
    for f in glob.glob(os.path.join(LSL, "*.lsl")):
        shutil.copy(f, src)
    shutil.copy(os.path.join(HERE, "lsl", "luxos-ics-test.lsl"), src)
    out = os.path.join(TMP, "ics-test")
    r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", os.path.join(src, "luxos-ics-test.lsl"), out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        return None
    return out


PROG = build()


@unittest.skipUnless(PROG, "chybi lslc s cilem linux-x86_64-gnu (LSL >= 0.10.5), viz LUXOS_LSLC")
class LslCalendar(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cal-", dir=TMP)

    def run_prog(self, *args, tz="Europe/Prague"):
        env = dict(os.environ, TZ=tz, LANG="cs_CZ.UTF-8")
        # bez text=True: Python by prevadel \r\n na \n (iCalendar ma CRLF)
        r = subprocess.run([PROG, *args], capture_output=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        self.assertEqual(r.stderr, b"")
        return r.stdout.decode("utf-8")

    def lines(self, *args):
        return self.run_prog(*args).rstrip("\n").split("\n")

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return path

    # ---- datumova matematika -------------------------------------------------------------------
    def test_leap(self):
        self.assertEqual(self.lines("leap", "2024", "2"), ["True 29"])
        self.assertEqual(self.lines("leap", "2000", "2"), ["True 29"])
        self.assertEqual(self.lines("leap", "1900", "2"), ["False 28"])
        self.assertEqual(self.lines("leap", "2026", "12"), ["False 31"])
        self.assertEqual(self.lines("leap", "2100", "2"), ["False 28"])

    def test_grid(self):
        rows = self.lines("grid", "2026", "10", "0")
        self.assertEqual(rows[-1], "weeks 5")
        weeks = [r.split() for r in rows[:-1]]
        self.assertEqual(len(weeks), 6)
        self.assertEqual(weeks[0][0], "2026-09-28")
        self.assertEqual(weeks[0][3], "2026-10-01")
        flat = [d for w in weeks for d in w]
        self.assertEqual(sum(1 for d in flat if d.startswith("2026-10")), 31)
        self.assertEqual(flat, sorted(flat))
        self.assertEqual(len(set(flat)), 42)
        rows = self.lines("grid", "2024", "2", "0")
        flat = [d for r in rows[:-1] for d in r.split()]
        self.assertIn("2024-02-29", flat)
        rows = self.lines("grid", "2026", "2", "0")
        self.assertEqual(rows[0].split()[0], "2026-01-26")
        self.assertEqual(rows[0].split()[6], "2026-02-01")
        rows = self.lines("grid", "2027", "2", "0")
        self.assertEqual(rows[0].split()[0], "2027-02-01")
        self.assertEqual(rows[-1], "weeks 4")
        self.assertEqual(self.lines("grid", "2026", "3", "0")[-1], "weeks 6")
        rows = self.lines("grid", "2026", "10", "6")      # nedele prvni
        self.assertEqual(rows[0].split()[0], "2026-09-27")

    def test_add_months(self):
        self.assertEqual(self.lines("months", "2026", "12", "1"), ["[2027, 1]"])
        self.assertEqual(self.lines("months", "2026", "1", "-1"), ["[2025, 12]"])
        self.assertEqual(self.lines("months", "2026", "10", "-22"), ["[2024, 12]"])

    # ---- nizka uroven ---------------------------------------------------------------------------
    def test_fold_unfold_utf8(self):
        long = "SUMMARY:" + "Příliš žluťoučký kůň úpěl ďábelské ódy " * 5
        rows = self.lines("fold", long)
        self.assertEqual(rows[-1], "same True")
        for r in rows[:-1]:
            self.assertLessEqual(int(r.split()[1]), 75)

    def test_escape(self):
        self.assertEqual(self.lines("escape"), ["True a\\,b\\;c\\\\d\\ne"])

    def test_escape_lone_cr(self):
        # samotne CR (stary Mac, vlozeny text) nesmi do souboru projit jako zalomeni radku
        self.assertEqual(self.lines("escape-cr"), ["a\\nb\\nc"])

    def test_parse_line_quoted(self):
        self.assertEqual(self.lines("line", 'ATTENDEE;CN="Novak: Jan";ROLE=REQ:mailto:jan@example.com'),
                         ["['ATTENDEE', {'CN': 'Novak: Jan', 'ROLE': 'REQ'}, 'mailto:jan@example.com']"])
        self.assertEqual(self.lines("line", "bez dvojtecky"), ["None"])

    def test_parse_dt(self):
        self.assertEqual(self.lines("dt", "20261020"), ["20261020"])
        self.assertEqual(self.lines("dt", "20261020T090000"), ["20261020T090000"])
        # UTC -> Praha (letni cas do 25. 10. 2026)
        self.assertEqual(self.lines("dt", "20261020T070000Z"), ["20261020T090000"])
        self.assertEqual(self.lines("dt", "20261026T080000Z"), ["20261026T090000"])
        self.assertEqual(self.lines("dt", "20261020T090000", "America/New_York"), ["20261020T150000"])
        self.assertEqual(self.lines("dt", "20261020T090000", "Nesmysl/Zona"), ["20261020T090000"])
        self.assertEqual(self.lines("dt", "2026-10-20"), ["error"])

    def test_duration(self):
        self.assertEqual(self.lines("dur", "-PT10M"), ["-600"])
        self.assertEqual(self.lines("dur", "P1DT2H"), [str(86400 + 7200)])
        self.assertEqual(self.lines("dur", "P2W"), [str(14 * 86400)])
        self.assertEqual(self.lines("dur", "PT1H30M"), ["5400"])
        self.assertEqual(self.lines("dur", "P"), ["error"])

    # ---- cteni a zapis -------------------------------------------------------------------------
    def test_google_import(self):
        path = self.write("google.ics", GOOGLE)
        rows = self.lines("parse", path)
        self.assertEqual(rows[0], "errors 0 other 2 header 4")
        f = rows[1].split("|")
        self.assertEqual(f[:5], ["abc123@google.com", "Standup, tym",
                                 "Radek 1\\nRadek 2 se strednikem; a lomitkem \\ pokracovani",
                                 "20261020T090000", "20261020T103000"])
        self.assertEqual(f[5:7], ["FREQ=WEEKLY;BYDAY=TU,TH;COUNT=4", "15"])
        self.assertEqual(self.lines("days", path, "20261001", "20261201", "0"),
                         ["20261020T090000", "20261022T090000", "20261027T090000", "20261029T090000"])

    def test_round_trip_preserves_unknown(self):
        path = self.write("google.ics", GOOGLE)
        text = self.run_prog("text", path, "Europe/Prague")
        for needle in ("X-WR-CALNAME:Prace", "CALSCALE:GREGORIAN", "SEQUENCE:2",
                       "X-GOOGLE-CONFERENCE:https://meet.example/xyz", "DTSTAMP:20261001T000000Z", "BEGIN:VTODO",
                       "SUMMARY:Nekomponenta", "BEGIN:VTIMEZONE", "X-WR-ALARMUID:1",
                       "RRULE:FREQ=WEEKLY;BYDAY=TU,TH;COUNT=4", "DTSTART;TZID=Europe/Prague:20261020T090000"):
            self.assertIn(needle, text.replace("\r\n ", ""))
        body = text[:text.rindex("\n") + 1]        # bez koncoveho \n z print
        self.assertTrue(all(line.endswith("\r") or line == "" for line in body.split("\n")))
        path2 = self.write("again.ics", body)
        rows = self.lines("parse", path2)
        self.assertEqual(rows[0], "errors 0 other 2 header 4")
        self.assertEqual(rows[1].split("|")[:7], self.lines("parse", path)[1].split("|")[:7])
        self.assertEqual(self.run_prog("text", path2, "Europe/Prague"), self.run_prog("retext", path2, "Europe/Prague"))

    def test_all_day_round_trip(self):
        rows = self.lines("allday")
        text = "\n".join(rows)
        self.assertIn("DTSTART;VALUE=DATE:20261026", text)
        self.assertIn("DTEND;VALUE=DATE:20261031", text)
        self.assertIn("COLOR:green", text)
        ev = [r for r in rows if r.startswith("Dovolen") or "|Dovolen" in r]
        self.assertTrue(ev)
        f = ev[0].split("|")
        self.assertEqual(f[1:5], ["Dovolená – Šumava", "", "20261026", "20261031"])
        self.assertEqual(f[7], "green")
        after = rows[rows.index(ev[0]) + 1:]
        self.assertEqual(after, ["20261026", "--"])   # zasahuje do 30., DTEND exkluzivni

    def test_all_day_without_dtend(self):
        path = self.write("a.ics", "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nDTSTART;VALUE=DATE:20261020\nSUMMARY:Den\n"
                          "END:VEVENT\nEND:VCALENDAR\n")
        self.assertEqual(self.lines("duration", path), ["1"])
        self.assertEqual(self.lines("days", path, "20261020", "20261021", "0"), ["20261020"])
        self.assertEqual(self.lines("days", path, "20261021", "20261022", "0"), [""])

    def test_duration_property_and_lf_files(self):
        path = self.write("d.ics", "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:d\nDTSTART:20261020T080000Z\nDURATION:PT45M\n"
                          "SUMMARY:Kratka\nEND:VEVENT\nEND:VCALENDAR\n")
        self.assertEqual(self.lines("duration", path), ["2700"])
        self.assertEqual(self.lines("parse", path)[1].split("|")[3:5], ["20261020T100000", "20261020T104500"])

    def test_timed_round_trip_with_tzid(self):
        rows = self.lines("timed")
        text = "\n".join(rows)
        self.assertIn("DTSTART;TZID=Europe/Prague:20261020T143000", text)
        self.assertIn("TRIGGER:-PT10M", text)
        self.assertIn("RRULE:FREQ=MONTHLY;COUNT=3", text)
        f = [r for r in rows if "|Schůzka|" in r][0].split("|")
        self.assertEqual(f[3:7], ["20261020T143000", "20261020T151500", "FREQ=MONTHLY;COUNT=3", "10"])
        self.assertEqual(rows[-1], "alarms 0")

    def test_broken_event_is_kept(self):
        path = self.write("b.ics", "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:bad\nSUMMARY:Bez data\nEND:VEVENT\n"
                          "BEGIN:VEVENT\nUID:ok\nDTSTART:20261020T100000\nSUMMARY:OK\nEND:VEVENT\n"
                          "nesmyslny radek\nEND:VCALENDAR\n")
        rows = self.lines("parse", path)
        self.assertEqual(rows[0], "errors 1 other 1 header 1")
        self.assertEqual([r.split("|")[0] for r in rows[1:]], ["ok"])
        self.assertIn("UID:bad", self.run_prog("text", path, ""))

    def test_bom_and_empty(self):
        path = self.write("bom.ics", "﻿BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
        self.assertEqual(self.lines("parse", path), ["errors 0 other 0 header 2"])
        path = self.write("empty.ics", "")
        self.assertEqual(self.lines("parse", path), ["errors 0 other 0 header 2"])

    # ---- opakovani ------------------------------------------------------------------------------
    def rule(self, start, rrule, end, a, b):
        out = self.lines("rule", start, rrule, end, a, b)
        return [] if out == [""] else out

    def test_daily_count(self):
        self.assertEqual(self.rule("20261030T080000", "FREQ=DAILY;COUNT=3", "20261030T090000", "20261001", "20261201"),
                         ["20261030T080000", "20261031T080000", "20261101T080000"])
        self.assertEqual(self.rule("20261030T080000", "FREQ=DAILY;COUNT=3", "20261030T090000", "20261101", "20261201"),
                         ["20261101T080000"])

    def test_daily_interval_until(self):
        self.assertEqual(self.rule("20261001", "FREQ=DAILY;INTERVAL=10;UNTIL=20261031", "-", "20260901", "20270101"),
                         ["20261001", "20261011", "20261021", "20261031"])

    def test_until_utc_inclusive(self):
        self.assertEqual(len(self.rule("20261001T090000", "FREQ=DAILY;UNTIL=20261003T070000Z", "-", "20260901", "20261201")), 3)

    def test_weekly(self):
        self.assertEqual(self.rule("20261020T090000", "FREQ=WEEKLY;UNTIL=20261110T235959Z", "-", "20261001", "20270101"),
                         ["20261020T090000", "20261027T090000", "20261103T090000", "20261110T090000"])

    def test_weekly_byday_interval(self):
        self.assertEqual(self.rule("20261019", "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR;COUNT=5", "-", "20260101", "20270101"),
                         ["20261019", "20261023", "20261102", "20261106", "20261116"])

    def test_monthly_skips_short_months(self):
        self.assertEqual(self.rule("20260131", "FREQ=MONTHLY;COUNT=4", "-", "20260101", "20270101"),
                         ["20260131", "20260331", "20260531", "20260731"])

    def test_monthly_byday_last_friday(self):
        self.assertEqual(self.rule("20261030", "FREQ=MONTHLY;BYDAY=-1FR;COUNT=3", "-", "20260101", "20270601"),
                         ["20261030", "20261127", "20261225"])

    def test_dtstart_not_matching_rule_is_first(self):
        self.assertEqual(self.rule("20261020", "FREQ=MONTHLY;BYDAY=-1FR;COUNT=3", "-", "20260101", "20270601"),
                         ["20261020", "20261030", "20261127"])

    def test_yearly_leap_day(self):
        self.assertEqual(self.rule("20240229", "FREQ=YEARLY;COUNT=3", "-", "20240101", "20400101"),
                         ["20240229", "20280229", "20320229"])

    def test_yearly_infinite_birthday(self):
        self.assertEqual(self.rule("19901020", "FREQ=YEARLY", "19901021", "20261020", "20261021"), ["20261020"])
        self.assertEqual(self.rule("19901020", "FREQ=YEARLY", "19901021", "20261021", "20271020"), [])

    def test_exdate(self):
        text = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nDTSTART:20261019T090000\nDTEND:20261019T100000\n"
                "RRULE:FREQ=DAILY;COUNT=5\nEXDATE:20261020T090000,20261022T090000\nEND:VEVENT\nEND:VCALENDAR\n")
        path = self.write("ex.ics", text)
        self.assertEqual(self.lines("days", path, "20261001", "20261101", "0"),
                         ["20261019T090000", "20261021T090000", "20261023T090000"])
        self.assertIn("EXDATE:20261020T090000,20261022T090000", self.run_prog("text", path, ""))

    def test_unsupported_freq_shows_first(self):
        self.assertEqual(self.rule("20261020T090000", "FREQ=HOURLY;COUNT=5", "-", "20261001", "20261101"), ["20261020T090000"])

    def test_pathological_rules_terminate(self):
        self.assertEqual(self.rule("20260101", "FREQ=MONTHLY;BYMONTHDAY=40", "-", "20260101", "20270101"), ["20260101"])
        self.assertEqual(len(self.rule("20260101", "FREQ=DAILY;BYMONTH=13", "-", "20260101", "20260108")), 7)

    def test_overnight_event_spans_two_days(self):
        self.assertEqual(self.lines("overnight"), ["1 0"])

    # ---- uloziste -------------------------------------------------------------------------------
    def test_store_crud_and_foreign(self):
        self.write("google.ics", GOOGLE)
        rows = self.lines("store", self.dir)
        self.assertEqual(rows, ["reload True False", "exists True", "day Standup, tym;Oběd", "foreign True google.ics",
                               "updated Oběd s týmem", "busy 2026-10-20 2026-10-22 2026-10-27 2026-10-29", "own 0", "tmp 0"])
        with open(os.path.join(self.dir, "google.ics"), encoding="utf-8", newline="") as f:
            self.assertEqual(f.read(), GOOGLE)        # importovany kalendar zustava netknuty

    def test_store_keeps_external_additions(self):
        self.assertEqual(self.lines("merge", self.dir), ["Z telefonu;C"])

    def test_recurrence_id_override(self):
        self.write("events.ics", "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:s\nDTSTART:20261019T090000\nDTEND:20261019T100000\n"
                   "RRULE:FREQ=DAILY;COUNT=3\nSUMMARY:Serie\nEND:VEVENT\n"
                   "BEGIN:VEVENT\nUID:s\nRECURRENCE-ID:20261020T090000\nDTSTART:20261020T150000\n"
                   "DTEND:20261020T160000\nSUMMARY:Presunuto\nEND:VEVENT\nEND:VCALENDAR\n")
        self.assertEqual(self.lines("override", self.dir), ["Presunuto 20261020T150000", "next 1"])

    def test_delete_one_edited_instance_keeps_series(self):
        self.write("events.ics", "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:s\nDTSTART:20261019T090000\nDTEND:20261019T100000\n"
                   "RRULE:FREQ=DAILY;COUNT=3\nSUMMARY:Serie\nEND:VEVENT\n"
                   "BEGIN:VEVENT\nUID:s\nRECURRENCE-ID:20261020T090000\nDTSTART:20261020T150000\n"
                   "DTEND:20261020T160000\nSUMMARY:Presunuto\nEND:VEVENT\nEND:VCALENDAR\n")
        self.assertEqual(self.lines("delete-override", self.dir), ["19 Serie", "20 ", "21 Serie"])

    def test_sorting_all_day_first(self):
        self.assertEqual(self.lines("sorting", self.dir), ["Celodenni;A rano;B pozde"])

    # ---- port opravy "wip fixes" z luxos_calendar_ics.py ------------------------------------------------
    def test_daily_filters_weekdays_before_counting(self):
        self.assertEqual(self.rule("20261023", "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR;COUNT=4", "-", "20261001", "20261101"),
                         ["20261023", "20261026", "20261027", "20261028"])

    def test_daily_filters_month_days(self):
        self.assertEqual(self.rule("20261031", "FREQ=DAILY;BYMONTHDAY=-1;COUNT=3", "-", "20261001", "20270101"),
                         ["20261031", "20261130", "20261231"])

    def test_daily_filter_with_no_matching_dates(self):
        self.assertEqual(self.rule("20260101", "FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30", "-", "20260101", "20260301"),
                         ["20260101"])

    def test_monthly_intersects_month_days_and_weekdays(self):
        self.assertEqual(self.rule("20261005", "FREQ=MONTHLY;BYMONTHDAY=1,2,3,4,5,6,7;BYDAY=MO;COUNT=3", "-",
                                   "20261001", "20270101"), ["20261005", "20261102", "20261207"])

    def test_monthly_intersection_with_ordinal_weekday(self):
        self.assertEqual(self.rule("20261030", "FREQ=MONTHLY;BYMONTHDAY=-1,-2,-3;BYDAY=-1FR;COUNT=2", "-",
                                   "20261001", "20270601"), ["20261030", "20270129"])

    # ---- C-13 az C-18 (stejne pripady jako TestRfcFixes v test_luxos_calendar_ics.py) --------------------
    def test_weekdays_only_never_on_weekend(self):
        import datetime as dt
        for rule in ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "FREQ=WEEKLY;WKST=SU;BYDAY=MO,TU,WE,TH,FR",
                     "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR", "FREQ=WEEKLY;INTERVAL=1;BYDAY=FR,TH,WE,TU,MO;COUNT=30",
                     "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR"):
            for start in ("20261019T090000", "20261019"):
                got = self.rule(start, rule, "-", "20261001", "20270101")
                self.assertTrue(got, rule)
                weekend = [d for d in got if dt.date(int(d[0:4]), int(d[4:6]), int(d[6:8])).weekday() >= 5]
                self.assertEqual(weekend, [], rule)
        self.assertEqual(self.rule("20261019", "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR", "-", "20261019", "20261027"),
                         ["20261019", "20261020", "20261021", "20261022", "20261023", "20261026"])

    def test_bysetpos_last_working_day_of_month(self):
        self.assertEqual(self.rule("20261030", "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1;COUNT=4", "-",
                                   "20260101", "20280101"), ["20261030", "20261130", "20261231", "20270129"])
        self.assertEqual(self.rule("20261001T080000", "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1,-1;COUNT=4", "-",
                                   "20260101", "20280101"),
                         ["20261001T080000", "20261030T080000", "20261102T080000", "20261130T080000"])

    def test_bysetpos_yearly_and_weekly(self):
        self.assertEqual(self.rule("20260301", "FREQ=YEARLY;BYMONTH=3,10;BYDAY=SU;BYSETPOS=1,-1;COUNT=4", "-",
                                   "20260101", "20280101"), ["20260301", "20261025", "20270307", "20271031"])
        self.assertEqual(self.rule("20261021", "FREQ=WEEKLY;BYDAY=MO,WE,FR;BYSETPOS=2;COUNT=3", "-",
                                   "20260101", "20280101"), ["20261021", "20261028", "20261104"])

    def test_exdate_without_rrule(self):
        path = self.write("x.ics", "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nDTSTART:20261020T090000\nDTEND:20261020T100000\n"
                          "EXDATE:20261020T090000\nSUMMARY:Nic\nEND:VEVENT\nEND:VCALENDAR\n")
        self.assertEqual(self.lines("days", path, "20261001", "20261101", "0"), [""])
        path = self.write("y.ics", "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nDTSTART;VALUE=DATE:20261020\n"
                          "EXDATE;VALUE=DATE:20261020\nSUMMARY:Nic\nEND:VEVENT\nEND:VCALENDAR\n")
        self.assertEqual(self.lines("days", path, "20261001", "20261101", "0"), [""])

    def test_rdate(self):
        path = self.write("rd.ics", RDATES)
        self.assertEqual(self.lines("days", path, "20261001", "20261101", "0"),
                         ["20261019T090000", "20261021T140000", "20261024T150000", "20261026T090000", "20261027T090000"])
        self.assertEqual(self.lines("days", path, "20261024", "20261025", "0"), ["20261024T150000"])
        self.assertEqual(self.lines("days", path, "20261001", "20270101", "1"), ["20261001", "20261015", "20261101"])
        text = self.run_prog("text", path, "Europe/Prague")
        for needle in ("RDATE:20261021T140000,20261023T090000", "RDATE;TZID=America/New_York:20261024T090000",
                       "RDATE;VALUE=PERIOD:20261026T080000Z/PT1H", "RDATE;VALUE=DATE:20261027",
                       "RDATE;VALUE=DATE:20261015"):
            self.assertIn(needle, text)
        self.assertEqual(text.count("RDATE"), 5)
        path2 = self.write("rd2.ics", text[:text.rindex("\n") + 1])
        self.assertEqual(self.lines("days", path2, "20261001", "20261101", "0"),
                         self.lines("days", path, "20261001", "20261101", "0"))

    def test_foreign_timezone_recurrence_across_dst(self):
        path = self.write("ny.ics", NY_WEEKLY)
        self.assertEqual(self.lines("days", path, "20260301", "20260406", "0"),
                         ["20260302T150000", "20260316T140000", "20260323T140000", "20260330T150000"])
        self.assertEqual(self.lines("days", path, "20261019", "20261110", "0"),
                         ["20261019T150000", "20261026T140000", "20261102T150000", "20261109T150000"])
        self.assertEqual(self.lines("days", path, "20261120", "20270101", "0"), ["20261123T150000", "20261130T150000"])
        until = self.write("until.ics", NY_WEEKLY.replace("COUNT=40", "UNTIL=20261109T140000Z"))
        self.assertEqual(self.lines("days", until, "20261101", "20270101", "0"), ["20261102T150000", "20261109T150000"])
        text = self.run_prog("text", path, "Europe/Prague")
        for needle in ("DTSTART;TZID=America/New_York:20260302T090000", "DTEND;TZID=America/New_York:20260302T100000",
                       "RECURRENCE-ID;TZID=America/New_York:20260316T090000",
                       "DTSTART;TZID=America/New_York:20260316T110000"):
            self.assertIn(needle, text)
        path2 = self.write("ny2.ics", text[:text.rindex("\n") + 1])
        self.assertEqual(self.lines("days", path2, "20261019", "20261110", "0"),
                         self.lines("days", path, "20261019", "20261110", "0"))
        self.assertIn("DTSTART;TZID=America/New_York:20260302T100000", self.run_prog("shift", path, "3600"))

    def test_foreign_timezone_in_store_with_override(self):
        self.write("events.ics", NY_WEEKLY)
        self.assertEqual(self.lines("instances", self.dir, "20260309", "20260317"), ["NY presunuto|20260316T160000"])
        self.assertEqual(self.lines("instances", self.dir, "20261026", "20261027"), ["NY|20261026T140000"])

    def test_cancelled_events_hidden(self):
        self.write("events.ics", CANCELLED)
        self.assertEqual(self.lines("instances", self.dir, "20261019", "20261020"), ["Serie|20261019T090000"])
        self.assertEqual(self.lines("instances", self.dir, "20261020", "20261021"), [""])
        self.assertEqual(self.lines("instances", self.dir, "20261021", "20261022"), ["Serie|20261021T090000"])
        self.assertEqual(self.run_prog("text", os.path.join(self.dir, "events.ics"), "").count("STATUS:CANCELLED"), 2)

    def test_delete_single_moved_occurrence(self):
        self.write("events.ics", MOVED)
        out = self.run_prog("delmoved", self.dir, "20261020")
        self.assertTrue(out.startswith("rid True\n"))
        self.assertEqual(out.count("BEGIN:VEVENT"), 1)
        self.assertIn("EXDATE;TZID=Europe/Prague:20261020T090000", out)
        self.assertEqual(self.lines("instances", self.dir, "20261019", "20261022"),
                         ["Serie|20261019T090000", "Serie|20261021T090000"])
        self.assertEqual(self.lines("delall", self.dir, "s"), ["own 0"])

    def test_concurrent_update_keeps_other_changes(self):
        self.assertEqual(self.lines("concurrent", self.dir, "update"), ["A zde;B jinde"])

    def test_delete_does_not_drop_concurrent_edit(self):
        self.assertEqual(self.lines("concurrent", self.dir, "delete"), ["B jinde"])

    def test_update_of_event_deleted_elsewhere_is_conflict(self):
        self.assertEqual(self.lines("concurrent", self.dir, "conflict"), ["conflict True", "memory True", "B"])

    def test_colors(self):
        self.assertEqual(self.lines("color", "purple", "-"), ["purple"])
        self.assertEqual(self.lines("color", "DodgerBlue", "-"), ["blue"])
        self.assertEqual(self.lines("color", "", "-"), ["blue"])
        self.assertIn(self.lines("color", "", "google.ics")[0], ["red", "orange", "yellow", "green", "blue", "purple"])


if __name__ == "__main__":
    unittest.main()
