"""LuxOS Kalendar - minimalni, odolne cteni a zapis iCalendar (RFC 5545) a datumova matematika.

Bez zavislosti mimo standardni knihovnu (python-icalendar je zbytecne tezky pro demona).
Podporuje VEVENT: SUMMARY, DTSTART/DTEND/DURATION (datum, UTC, TZID, plovouci cas),
RRULE (FREQ=DAILY/WEEKLY/MONTHLY/YEARLY, INTERVAL, COUNT, UNTIL, BYDAY, BYMONTHDAY, BYMONTH),
EXDATE, RECURRENCE-ID, COLOR (RFC 7986) a VALARM. Nezname vlastnosti a komponenty se
zachovavaji beze zmeny (import/export bez ztraty dat).
"""
import datetime as dt
import os
import re
import uuid

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

COLORS = ("red", "orange", "yellow", "green", "blue", "purple")
COLOR_HEX = {
    "red": "#ff453a", "orange": "#ff9f0a", "yellow": "#ffd60a",
    "green": "#30d158", "blue": "#0a84ff", "purple": "#bf5af2",
}
DEFAULT_COLOR = "blue"
WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
MAX_INSTANCES = 50000  # pojistka proti nekonecnym/obrim opakovanim
PRODID = "-//LuxOS//Calendar 1.0//EN"


# ---- datumova matematika ---------------------------------------------------------
def is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(year, month):
    return (31, 29 if is_leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1]


def add_months(year, month, delta):
    """(rok, mesic) posunuty o delta mesicu."""
    i = year * 12 + (month - 1) + delta
    return i // 12, i % 12 + 1


def month_grid(year, month, first_weekday=0, rows=6):
    """Mrizka mesice: seznam tydnu (7 dat), tyden zacina pondelim (first_weekday=0).

    Vzdy `rows` radku (6 = stabilni vyska jako v macOS), doplneno dny sousednich mesicu.
    """
    first = dt.date(year, month, 1)
    offset = (first.weekday() - first_weekday) % 7
    start = first - dt.timedelta(days=offset)
    return [[start + dt.timedelta(days=r * 7 + c) for c in range(7)] for r in range(rows)]


def weeks_needed(year, month, first_weekday=0):
    """Pocet tydnu, do kterych mesic zasahuje (4 az 6)."""
    first = dt.date(year, month, 1)
    offset = (first.weekday() - first_weekday) % 7
    return (offset + days_in_month(year, month) + 6) // 7


# ---- nizka uroven: radky a hodnoty --------------------------------------------------
def unfold(text):
    """Rozbali zalomene radky (CRLF/LF + mezera nebo tabulator)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for line in text.split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        elif line.strip():
            out.append(line)
    return out


def fold(line):
    """Zalomi radek na max. 75 oktetu (bez rozdeleni vicebajtoveho znaku UTF-8)."""
    out, cur, size, limit = [], "", 0, 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            out.append(cur)
            cur, size, limit = " ", 1, 75
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def parse_line(line):
    """'NAME;P=V;Q="a:b":hodnota' -> (NAME, {P: V, Q: a:b}, hodnota). Neplatny radek -> None."""
    i, n, quoted = 0, len(line), False
    while i < n:
        c = line[i]
        if c == '"':
            quoted = not quoted
        elif c == ":" and not quoted:
            break
        i += 1
    if i >= n:
        return None
    head, value = line[:i], line[i + 1:]
    parts, cur, quoted = [], "", False
    for c in head:
        if c == '"':
            quoted = not quoted
            cur += c
        elif c == ";" and not quoted:
            parts.append(cur)
            cur = ""
        else:
            cur += c
    parts.append(cur)
    name = parts[0].strip().upper()
    if not name or not re.match(r"^[A-Z0-9-]+$", name):
        return None
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.strip().upper()] = v.strip().strip('"')
    return name, params, value


def unescape(v):
    out, i = [], 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v):
            nx = v[i + 1]
            out.append("\n" if nx in "nN" else nx)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def escape(v):
    return (v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def local_tz_name():
    """Nazev mistniho pasma (Europe/Prague) z TZ nebo /etc/localtime, jinak None."""
    tz = os.environ.get("TZ", "").lstrip(":")
    if tz and "/" in tz and not tz.startswith("/"):
        return tz
    try:
        target = os.path.realpath("/etc/localtime")
        if "/zoneinfo/" in target:
            return target.split("/zoneinfo/", 1)[1]
    except OSError:
        pass
    return None


def _zone(name):
    if not name or ZoneInfo is None:
        return None
    try:
        return ZoneInfo(name)
    except Exception:  # neznamy TZID (napr. Windows nazvy) -> plovouci cas
        return None


def parse_dt(value, params=None):
    """Hodnota DATE nebo DATE-TIME -> date (cely den) nebo naivni mistni datetime."""
    params = params or {}
    v = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", v):
        return dt.date(int(v[0:4]), int(v[4:6]), int(v[6:8]))
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z?)", v)
    if not m:
        raise ValueError(f"bad date-time: {value!r}")
    y, mo, d, h, mi = (int(x) for x in m.group(1, 2, 3, 4, 5))
    s = min(int(m.group(6) or 0), 59)
    t = dt.datetime(y, mo, d, h, mi, s)
    if m.group(7):  # UTC -> mistni cas
        return t.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)
    zone = _zone(params.get("TZID"))
    if zone is not None:
        return t.replace(tzinfo=zone).astimezone().replace(tzinfo=None)
    return t


def parse_duration(v):
    """RFC 5545 DURATION (-PT10M, P1D, P1W, PT1H30M) -> timedelta."""
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m or v.strip() in ("P", "-P", "+P"):
        raise ValueError(f"bad duration: {v!r}")
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.group(2, 3, 4, 5, 6))
    return sign * dt.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def format_dt(value, tzname=None):
    """date/datetime -> (parametry, hodnota) pro zapis."""
    if not isinstance(value, dt.datetime):
        return ";VALUE=DATE", value.strftime("%Y%m%d")
    if tzname and _zone(tzname) is not None:
        return f";TZID={tzname}", value.strftime("%Y%m%dT%H%M%S")
    return "", value.strftime("%Y%m%dT%H%M%S")


# ---- udalost ------------------------------------------------------------------------
KNOWN = {"UID", "SUMMARY", "DTSTART", "DTEND", "DURATION", "RRULE", "EXDATE", "COLOR",
         "RECURRENCE-ID", "DESCRIPTION", "LOCATION"}


class Event:
    """Jedna VEVENT. start/end jsou date (cely den, end exkluzivne) nebo naivni mistni datetime."""

    def __init__(self, summary="", start=None, end=None, color=None, uid=None):
        self.uid = uid or f"{uuid.uuid4()}@luxos"
        self.summary = summary
        self.start = start
        self.end = end
        self.color = color
        self.description = ""
        self.location = ""
        self.rrule = None          # slovnik {"FREQ": "WEEKLY", ...} nebo None
        self.rrule_raw = None      # puvodni text RRULE (zapis beze zmen)
        self.exdates = []          # seznam date/datetime
        self.exdate_lines = []     # puvodni radky EXDATE
        self.recurrence_id = None
        self.extra = []            # nezname vlastnosti (puvodni rozbalene radky)
        self.alarms = []           # VALARM bloky (seznam radku vcetne BEGIN/END)
        self.source = None         # nazev souboru (cteni) - None = vlastni kalendar
        self.readonly = False

    @property
    def all_day(self):
        return not isinstance(self.start, dt.datetime)

    def duration(self):
        if self.end is None:
            return dt.timedelta(days=1) if self.all_day else dt.timedelta(0)
        if self.all_day and isinstance(self.end, dt.datetime):
            return dt.timedelta(days=max(1, (self.end.date() - self.start).days))
        if not self.all_day and not isinstance(self.end, dt.datetime):
            return dt.datetime.combine(self.end, dt.time()) - self.start
        return max(self.end - self.start, dt.timedelta(0))

    def reminder_minutes(self):
        """Minuty pred zacatkem z VALARM (TRIGGER relativne k zacatku), jinak None."""
        best = None
        for block in self.alarms:
            for line in block:
                p = parse_line(line)
                if not p or p[0] != "TRIGGER":
                    continue
                name, params, value = p
                if params.get("VALUE", "").upper() == "DATE-TIME" or params.get("RELATED", "START").upper() != "START":
                    continue
                try:
                    d = parse_duration(value)
                except ValueError:
                    continue
                mins = int(-d.total_seconds() // 60)
                if mins >= 0 and (best is None or mins < best):
                    best = mins
        return best

    def set_reminder(self, minutes):
        """Nastavi pripominku (None = zadna). Nezmenenou pripominku ponecha beze zmen."""
        if minutes == self.reminder_minutes() and (minutes is not None or not self.alarms):
            return
        self.alarms = []
        if minutes is not None:
            self.alarms.append(["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{escape(self.summary or 'Reminder')}",
                                f"TRIGGER:-PT{int(minutes)}M", "END:VALARM"])

    def to_lines(self, tzname=None):
        lines = ["BEGIN:VEVENT", f"UID:{self.uid}"]
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if not any(x.upper().startswith("DTSTAMP") for x in self.extra):
            lines.append(f"DTSTAMP:{stamp}")
        if self.recurrence_id is not None:
            p, v = format_dt(self.recurrence_id, tzname)
            lines.append(f"RECURRENCE-ID{p}:{v}")
        p, v = format_dt(self.start, tzname)
        lines.append(f"DTSTART{p}:{v}")
        if self.end is not None:
            p, v = format_dt(self.end, tzname)
            lines.append(f"DTEND{p}:{v}")
        lines.append(f"SUMMARY:{escape(self.summary)}")
        if self.description:
            lines.append(f"DESCRIPTION:{escape(self.description)}")
        if self.location:
            lines.append(f"LOCATION:{escape(self.location)}")
        if self.color:
            lines.append(f"COLOR:{self.color}")
        if self.rrule_raw:
            lines.append(f"RRULE:{self.rrule_raw}")
        lines.extend(self.exdate_lines)
        lines.extend(self.extra)
        for block in self.alarms:
            lines.extend(block)
        lines.append("END:VEVENT")
        return lines

    def set_rrule(self, raw):
        """Nastavi RRULE z textu ('FREQ=WEEKLY;COUNT=3') nebo zrusi (None)."""
        self.rrule_raw = raw or None
        self.rrule = parse_rrule(raw) if raw else None

    # ---- vyskyty ----
    def occurrences(self, range_start, range_end):
        """Vyskyty [(zacatek, konec)] protinajici interval dnu <range_start, range_end).

        zacatek/konec jsou stejneho typu jako start (date nebo datetime).
        """
        dur = self.duration()
        rs = range_start if self.all_day else dt.datetime.combine(range_start, dt.time())
        re_ = range_end if self.all_day else dt.datetime.combine(range_end, dt.time())
        out = []
        for s in self._starts(range_end):
            e = s + dur
            if s >= re_:
                break
            if e > rs or (s >= rs and dur == dt.timedelta(0)):
                out.append((s, e))
        return out

    def _starts(self, until_day):
        """Generator zacatku vyskytu (vzestupne) do dne until_day (bez nej)."""
        if not self.rrule:
            yield self.start
            return
        r = self.rrule
        freq = r.get("FREQ")
        if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
            yield self.start  # nepodporovana frekvence: aspon prvni vyskyt
            return
        interval = max(1, _int(r.get("INTERVAL"), 1))
        count = _int(r.get("COUNT"), None)
        until = None
        if r.get("UNTIL"):
            try:
                until = parse_dt(r["UNTIL"])
            except ValueError:
                until = None
        excluded = set(self.exdates)
        start = self.start
        start_day = start if self.all_day else start.date()
        tod = None if self.all_day else start.time()
        limit_day = until_day
        produced = 0
        n = 0

        def mk(day):
            return day if tod is None else dt.datetime.combine(day, tod)

        # DTSTART je vzdy prvni vyskyt (RFC 5545), i kdyz pravidlu neodpovida
        days = _rrule_days(freq, interval, r, start_day)
        first = [start_day]
        for day in _chain_first(first, days, start_day):
            n += 1
            if n > MAX_INSTANCES:
                return
            s = mk(day)
            if until is not None:
                u = until
                if isinstance(u, dt.datetime) and self.all_day:
                    u = u.date()
                elif not isinstance(u, dt.datetime) and not self.all_day:
                    u = dt.datetime.combine(u, dt.time(23, 59, 59))
                if s > u:
                    return
            produced += 1
            if count is not None and produced > count:
                return
            if day >= limit_day:
                return
            if s in excluded or (not self.all_day and s.date() in excluded):
                continue
            yield s


def _chain_first(first, days, start_day):
    """Nejdriv den DTSTART, pak dny pravidla po nem (bez duplicity)."""
    yield from first
    for d in days:
        if d > start_day:
            yield d


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def parse_rrule(raw):
    r = {}
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            r[k.strip().upper()] = v.strip().upper() if k.strip().upper() != "UNTIL" else v.strip()
    return r


def _byday(spec):
    """'MO,-1FR,2TU' -> [(None, 0), (-1, 4), (2, 1)]."""
    out = []
    for item in (spec or "").split(","):
        m = re.fullmatch(r"([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)", item.strip())
        if m:
            out.append((int(m.group(1)) if m.group(1) else None, WEEKDAYS.index(m.group(2))))
    return out


def _month_days(year, month, r, start_day):
    """Dny v mesici podle BYMONTHDAY/BYDAY (jinak den mesice ze startu), serazene."""
    dim = days_in_month(year, month)
    days = set()
    bymd = [x for x in (r.get("BYMONTHDAY") or "").split(",") if x.strip()]
    byday = _byday(r.get("BYDAY"))
    if bymd:
        for x in bymd:
            v = _int(x, 0)
            if v > 0 and v <= dim:
                days.add(v)
            elif v < 0 and -v <= dim:
                days.add(dim + v + 1)
    elif byday:
        for nth, wd in byday:
            matches = [d for d in range(1, dim + 1) if dt.date(year, month, d).weekday() == wd]
            if nth is None:
                days.update(matches)
            elif 0 < nth <= len(matches):
                days.add(matches[nth - 1])
            elif nth < 0 and -nth <= len(matches):
                days.add(matches[nth])
    elif start_day.day <= dim:  # 31. v kratsim mesici se podle RFC preskakuje
        days.add(start_day.day)
    return [dt.date(year, month, d) for d in sorted(days)]


def _rrule_days(freq, interval, r, start_day):
    """Generator kandidatnich dnu (vzestupne), konci nejpozdeji v roce 9999."""
    try:
        yield from _rrule_days_raw(freq, interval, r, start_day)
    except (OverflowError, ValueError):
        return


def _rrule_days_raw(freq, interval, r, start_day):
    bymonth = {m for m in (_int(x, 0) for x in (r.get("BYMONTH") or "").split(",")) if 1 <= m <= 12}
    if freq == "DAILY":
        d = start_day
        while True:
            if not bymonth or d.month in bymonth:
                yield d
            d += dt.timedelta(days=interval)
    elif freq == "WEEKLY":
        wds = sorted({wd for _n, wd in _byday(r.get("BYDAY"))}) or [start_day.weekday()]
        wkst = WEEKDAYS.index(r["WKST"]) if r.get("WKST") in WEEKDAYS else 0
        week = start_day - dt.timedelta(days=(start_day.weekday() - wkst) % 7)
        while True:
            days = sorted(week + dt.timedelta(days=(wd - wkst) % 7) for wd in wds)
            for d in days:
                if not bymonth or d.month in bymonth:
                    yield d
            week += dt.timedelta(weeks=interval)
    elif freq == "MONTHLY":
        y, m = start_day.year, start_day.month
        while True:
            if not bymonth or m in bymonth:
                yield from _month_days(y, m, r, start_day)
            y, m = add_months(y, m, interval)
            if y > 9999:
                return
    else:  # YEARLY
        y = start_day.year
        while True:
            if bymonth or r.get("BYDAY") or r.get("BYMONTHDAY"):
                for m in sorted(bymonth or {start_day.month}):
                    yield from _month_days(y, m, r, start_day)
            elif start_day.day <= days_in_month(y, start_day.month):  # 29. 2. jen v prestupnem roce
                yield dt.date(y, start_day.month, start_day.day)
            y += interval
            if y > 9999:
                return


# ---- soubor -------------------------------------------------------------------------
class Calendar:
    """Obsah jednoho .ics: udalosti + vse ostatni (hlavicka, VTIMEZONE, VTODO...) beze zmen."""

    def __init__(self):
        self.header = ["VERSION:2.0", f"PRODID:{PRODID}"]
        self.events = []
        self.other = []      # bloky jinych komponent (seznam radku)
        self.errors = 0      # pocet preskocenych chybnych zaznamu

    def to_text(self, tzname=None):
        lines = ["BEGIN:VCALENDAR"] + self.header
        for block in self.other:
            lines.extend(block)
        for ev in self.events:
            lines.extend(ev.to_lines(tzname))
        lines.append("END:VCALENDAR")
        return "".join(fold(x) + "\r\n" for x in lines)


def _event_from_lines(lines):
    ev = Event(uid="")
    ev.extra = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        up = line.upper()
        if up.startswith("BEGIN:"):  # vnorena komponenta (VALARM...)
            name = up[6:].strip()
            block = [line]
            depth = 1
            i += 1
            while i < n and depth:
                block.append(lines[i])
                u = lines[i].upper()
                if u.startswith("BEGIN:"):
                    depth += 1
                elif u.startswith("END:"):
                    depth -= 1
                i += 1
            if name == "VALARM":
                ev.alarms.append(block)
            else:
                ev.extra.extend(block)
            continue
        i += 1
        p = parse_line(line)
        if not p:
            ev.extra.append(line)
            continue
        name, params, value = p
        if name not in KNOWN:
            ev.extra.append(line)
        elif name == "UID":
            ev.uid = value.strip()
        elif name == "SUMMARY":
            ev.summary = unescape(value)
        elif name == "DESCRIPTION":
            ev.description = unescape(value)
        elif name == "LOCATION":
            ev.location = unescape(value)
        elif name == "COLOR":
            ev.color = value.strip().lower()
        elif name == "DTSTART":
            ev.start = parse_dt(value, params)
        elif name == "DTEND":
            ev.end = parse_dt(value, params)
        elif name == "DURATION":
            ev._duration = parse_duration(value)
        elif name == "RECURRENCE-ID":
            ev.recurrence_id = parse_dt(value, params)
        elif name == "RRULE":
            ev.set_rrule(value.strip())
        elif name == "EXDATE":
            ev.exdate_lines.append(line)
            for v in value.split(","):
                if v.strip():
                    ev.exdates.append(parse_dt(v, params))
    if ev.start is None:
        raise ValueError("VEVENT without DTSTART")
    dur = getattr(ev, "_duration", None)
    if ev.end is None and dur is not None:
        ev.end = ev.start + dur
    if ev.end is not None and type(ev.end) is not type(ev.start):
        # nesoulad typu (DTSTART datum, DTEND cas): zarovnat na typ zacatku
        ev.end = ev.end.date() if isinstance(ev.end, dt.datetime) else dt.datetime.combine(ev.end, dt.time())
    if ev.end is not None and ev.end < ev.start:
        ev.end = ev.start
    if not ev.uid:
        ev.uid = f"{uuid.uuid4()}@luxos"
    return ev


def parse(text):
    """Text .ics -> Calendar. Chybne VEVENT se preskoci (cal.errors), zbytek se nacte."""
    cal = Calendar()
    lines = unfold(text.lstrip("\ufeff"))
    header = []
    i, n = 0, len(lines)
    in_cal = False
    while i < n:
        line = lines[i]
        up = line.upper().strip()
        if up == "BEGIN:VCALENDAR":
            in_cal = True
            i += 1
            continue
        if up == "END:VCALENDAR":
            in_cal = False
            i += 1
            continue
        if up.startswith("BEGIN:"):
            name = up[6:]
            block, depth = [line], 1
            i += 1
            while i < n and depth:
                u = lines[i].upper().strip()
                if u.startswith("BEGIN:"):
                    depth += 1
                elif u.startswith("END:"):
                    depth -= 1
                block.append(lines[i])
                i += 1
            if name == "VEVENT":
                try:
                    cal.events.append(_event_from_lines(block[1:-1] if block[-1].upper().startswith("END:") else block[1:]))
                except (ValueError, IndexError):
                    cal.errors += 1
                    cal.other.append(block)  # chybny zaznam zachovat, at se neztrati
            else:
                cal.other.append(block)
            continue
        if in_cal and parse_line(line):
            header.append(line)
        i += 1
    if header:
        if not any(h.upper().startswith("VERSION") for h in header):
            header.insert(0, "VERSION:2.0")
        cal.header = header
    return cal


def read_file(path):
    with open(path, "rb") as f:
        data = f.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return parse(text)


def write_file(path, cal, tzname=None):
    """Atomicky zapis (docasny soubor + prejmenovani)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(cal.to_text(tzname))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ---- uloziste ------------------------------------------------------------------------
def default_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "luxos", "calendar")


class Store:
    """Vlastni kalendar events.ics (cteni i zapis) + ostatni *.ics ve slozce (jen cteni)."""

    OWN = "events.ics"

    def __init__(self, directory=None):
        self.dir = directory or default_dir()
        self.own_path = os.path.join(self.dir, self.OWN)
        self.own = Calendar()
        self.foreign = {}       # nazev souboru -> Calendar
        self._stamp = None
        self.version = 0        # zvysi se pri kazde zmene (invalidace cache v UI)
        self.tzname = local_tz_name()
        self._cache = {}

    def _scan(self):
        out = {}
        try:
            names = sorted(os.listdir(self.dir))
        except OSError:
            return out
        for name in names:
            if name.lower().endswith(".ics") and not name.startswith("."):
                try:
                    st = os.stat(os.path.join(self.dir, name))
                    out[name] = (st.st_mtime_ns, st.st_size)
                except OSError:
                    pass
        return out

    def reload_if_changed(self):
        """Nacte znovu, pokud se slozka zmenila. Vraci True pri zmene."""
        stamp = self._scan()
        if stamp == self._stamp:
            return False
        self._stamp = stamp
        self.own = Calendar()
        self.foreign = {}
        for name in stamp:
            path = os.path.join(self.dir, name)
            try:
                cal = read_file(path)
            except OSError:
                continue
            if name == self.OWN:
                self.own = cal
            else:
                for ev in cal.events:
                    ev.source = name
                    ev.readonly = True
                self.foreign[name] = cal
        self.version += 1
        self._cache = {}
        return True

    def save(self):
        write_file(self.own_path, self.own, self.tzname)
        self._stamp = None
        self.reload_if_changed()

    def all_events(self):
        evs = list(self.own.events)
        for cal in self.foreign.values():
            evs.extend(cal.events)
        return evs

    def find(self, uid, source=None):
        cals = [self.own] if source is None else [self.foreign.get(source)]
        for cal in cals:
            for ev in (cal.events if cal else []):
                if ev.uid == uid and ev.recurrence_id is None:
                    return ev
        return None

    def add(self, ev):
        self.own.events.append(ev)
        self.save()

    def update(self, ev):
        if ev not in self.own.events:
            raise KeyError(ev.uid)
        self.save()

    def delete(self, ev):
        # serie vcetne vyjimek (RECURRENCE-ID se stejnym UID)
        self.own.events = [e for e in self.own.events if e.uid != ev.uid]
        self.save()

    def instances(self, start, end):
        """Vyskyty vsech udalosti v intervalu dnu <start, end): seznam (Event, zacatek, konec)
        serazeny (cely den napred, pak podle casu)."""
        key = (start, end)
        if key in self._cache:
            return self._cache[key]
        overrides = {}
        for ev in self.all_events():
            if ev.recurrence_id is not None:
                overrides.setdefault((ev.source, ev.uid), set()).add(ev.recurrence_id)
        out = []
        for ev in self.all_events():
            skip = overrides.get((ev.source, ev.uid), ()) if ev.recurrence_id is None and ev.rrule else ()
            for s, e in ev.occurrences(start, end):
                if s in skip:
                    continue
                out.append((ev, s, e))
        out.sort(key=lambda x: (not x[0].all_day, _sort_key(x[1]), x[0].summary.lower()))
        if len(self._cache) > 64:
            self._cache = {}
        self._cache[key] = out
        return out

    def day_instances(self, day):
        return self.instances(day, day + dt.timedelta(days=1))

    def busy_days(self, start, end):
        """{date: barva prvni udalosti} pro dny v intervalu (tecky v mesicni/rocni mrizce)."""
        out = {}
        for ev, s, e in self.instances(start, end):
            d0 = s if not isinstance(s, dt.datetime) else s.date()
            if isinstance(e, dt.datetime):
                d1 = (e - dt.timedelta(microseconds=1)).date() if e > s else d0
            else:
                d1 = e - dt.timedelta(days=1)
            d = max(d0, start)
            while d <= d1 and d < end:
                out.setdefault(d, event_color(ev))
                d += dt.timedelta(days=1)
        return out


def _sort_key(v):
    return v if isinstance(v, dt.datetime) else dt.datetime.combine(v, dt.time())


def source_color(name):
    """Stala barva pro kalendar jen ke cteni (podle nazvu souboru)."""
    h = sum(name.encode("utf-8")) if name else 0
    return COLORS[h % len(COLORS)]


_CSS_NAMES = {"tomato": "red", "crimson": "red", "darkorange": "orange", "gold": "yellow",
              "limegreen": "green", "seagreen": "green", "dodgerblue": "blue", "royalblue": "blue",
              "navy": "blue", "violet": "purple", "magenta": "purple", "orchid": "purple"}


def event_color(ev):
    c = (ev.color or "").lower()
    if c in COLOR_HEX:
        return c
    if c in _CSS_NAMES:
        return _CSS_NAMES[c]
    return source_color(ev.source) if ev.source else DEFAULT_COLOR
