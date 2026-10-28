"""calendar.note.create -> udalost (VEVENT) ve vlastnim kalendari LuxOS (events.ics).

Kontrola: nazev 1-200 znaku, text nejvys 8000, datum YYYY-MM-DD, cas HH:mm nebo null, pasmo IANA.
Cas v mezere pri prechodu na letni cas (napr. 02:30 v posledni nedeli v breznu v Praze) neexistuje
-> chyba; dvojznacny cas pri navratu na zimni cas plati poprve (RFC 5545, 3.3.5).

Mapovani (PROTOCOL.md): SUMMARY=title, DESCRIPTION=text; cely den DTSTART;VALUE=DATE + DTEND
nasledujici den; s casem DTSTART;TZID=pasmo a DTEND o 30 min pozdeji (ve stejnem pasmu).
UID je odvozene z UUID pozadavku (uuid5), takze stejny pozadavek nikdy nevytvori druhou udalost.

Zapis spolecny s Kalendarem (luxos-hub, luxos_ics.lsl) a luxos_calendar_ics.py:
  - zamek .events.ics.lock (flock) mezi zapisujicimi procesy v Pythonu,
  - pred zapisem znovu nacist soubor, novou udalost vlozit pred posledni END:VCALENDAR - zbytek
    souboru (cizi komponenty, VTIMEZONE, jine udalosti) zustava bajt po bajtu stejny,
  - docasny soubor + fsync + kontrola, ze se soubor mezitim nezmenil (jinak znovu), prejmenovani,
    fsync slozky. Kalendar zmenu pozna pres inotify a pred vlastnim zapisem si ji prevezme.
calendar.saved se posila az po fsync (trvaly zapis). Vyrizena UUID se pamatuji (deduplikace).

calendar.events.list (CalendarReader, jen cteni): vyskyty udalosti vsech kalendaru ve slozce (events.ics
i odebirane *.ics) pro den v pasmu telefonu - opakovani (RRULE/EXDATE/RECURRENCE-ID z luxos_calendar_ics),
udalosti pres pulnoc a vicedenni (skutecny rozsah v textu), cely den time:null. Nejvys 100 zaznamu,
nazev do 300, text do 8000 znaku; co se nevejde do ramce 64 KiB, se zkrati (truncated:true).
"""
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import time
import uuid

from . import wire

try:
    from zoneinfo import ZoneInfo, available_timezones
except ImportError:  # pragma: no cover
    ZoneInfo = None
    available_timezones = None

MAX_TITLE = 200
MAX_TEXT = 8000
MAX_LIST = 100               # calendar.events: zaznamu
MAX_LIST_TITLE = 300
MAX_EVENT_ID = 200
DEFAULT_MINUTES = 30
UID_NAMESPACE = uuid.UUID("5f0d5d53-4a35-4d1c-9a43-1d6b0b8a7c21")
UID_SUFFIX = "@luxos-companion"
DONE_KEEP = 2000             # vyrizenych UUID v pameti deduplikace
DONE_DAYS = 90
RETRIES = 5
TZ_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+){0,3}$")
END_RE = re.compile(rb"(?im)^END:VCALENDAR[ \t]*\r?$")
_ZONES = None


class NoteError(Exception):
    """Chyba pozadavku s kodem pro telefon."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _(s):
    return s


def set_translator(fn):
    global _
    _ = fn


def ics_module():
    """luxos_calendar_ics z luxos-desktop (/usr/lib/luxos/python)."""
    import luxos_calendar_ics
    return luxos_calendar_ics


def calendar_dir():
    # stejna cesta jako luxos_calendar_ics.default_dir(); bez importu, aby sluzba nespadla, kdyz
    # luxos-desktop chybi (zapis poznamky pak skonci chybou storage_failed, ne cela sluzba)
    if os.environ.get("LUXOS_CALENDAR_DIR"):
        return os.environ["LUXOS_CALENDAR_DIR"]
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "luxos", "calendar")


def _clean(text, keep_newlines):
    """Bez ridicich znaku (iCalendar je nepovoluje), CRLF -> LF."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(ch for ch in text if ch == "\t" or (ch == "\n" and keep_newlines) or
                   not (ord(ch) < 32 or 0x7f <= ord(ch) < 0xa0 or ch in "  "))


def _zone(name):
    global _ZONES
    if not isinstance(name, str) or not name or len(name) > 64 or not TZ_RE.match(name) or ZoneInfo is None:
        raise NoteError("invalid_timezone", _("Unknown time zone."))
    if _ZONES is None and available_timezones is not None:
        try:
            _ZONES = available_timezones()
        except OSError:
            _ZONES = set()
    if _ZONES and name not in _ZONES:
        raise NoteError("invalid_timezone", _("Unknown time zone."))
    try:
        return ZoneInfo(name)
    except Exception as e:  # noqa: BLE001 - neznamy nazev, chybna data pasma
        raise NoteError("invalid_timezone", _("Unknown time zone.")) from e


def local_moment(day, hour, minute, zone):
    """Mistni cas v pasmu -> aware datetime; cas v mezere DST -> NoteError, dvojznacny -> poprve."""
    naive = dt.datetime(day.year, day.month, day.day, hour, minute)
    first = naive.replace(tzinfo=zone, fold=0)
    back = first.astimezone(dt.timezone.utc).astimezone(zone).replace(tzinfo=None)
    if back != naive:
        raise NoteError("nonexistent_time",
                        _("This time does not exist in the selected time zone (the clocks change). "
                          "Choose another time."))
    return first


def _exists(naive, zone):
    return naive.replace(tzinfo=zone).astimezone(dt.timezone.utc).astimezone(zone).replace(tzinfo=None) == naive


def validate(msg):
    """Zprava -> {"title","text","date","time","timezone"}; chyby jako NoteError."""
    title = msg.get("title")
    if not isinstance(title, str):
        raise NoteError("invalid_title", _("The note needs a title."))
    title = _clean(title, False).strip()
    if not title:
        raise NoteError("invalid_title", _("The note needs a title."))
    if len(title) > MAX_TITLE:
        raise NoteError("invalid_title", _("The title is too long (at most 200 characters)."))
    text = msg.get("text", "")
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise NoteError("invalid_text", _("The note text is not valid."))
    if len(text) > MAX_TEXT:
        raise NoteError("invalid_text", _("The note is too long (at most 8000 characters)."))
    text = _clean(text, True).strip()
    day = parse_date(msg.get("date"))
    raw_time = msg.get("time")
    clock = None
    if raw_time is not None:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw_time) if isinstance(raw_time, str) else None
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise NoteError("invalid_time", _("Invalid time (expected HH:mm)."))
        clock = (int(m.group(1)), int(m.group(2)))
    zone = _zone(msg.get("timezone"))
    if clock is not None:
        local_moment(day, clock[0], clock[1], zone)
    return {"title": title, "text": text, "date": day, "time": clock, "timezone": msg["timezone"]}


def parse_date(raw_date):
    try:
        if not isinstance(raw_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
            raise ValueError
        day = dt.date.fromisoformat(raw_date)
        if not 1900 <= day.year <= 2200:
            raise ValueError
    except ValueError:
        raise NoteError("invalid_date", _("Invalid date (expected YYYY-MM-DD).")) from None
    return day


def event_uid(request_id):
    return f"{uuid.uuid5(UID_NAMESPACE, request_id)}{UID_SUFFIX}"


def build_event(note, request_id):
    """Overena poznamka -> Event (luxos_calendar_ics) a pasmo pro zapis (None u celodenni)."""
    ics = ics_module()
    day = note["date"]
    if note["time"] is None:
        ev = ics.Event(summary=note["title"], start=day, end=day + dt.timedelta(days=1), uid=event_uid(request_id))
        tzname = None
    else:
        zone = ZoneInfo(note["timezone"])
        start = local_moment(day, note["time"][0], note["time"][1], zone).replace(tzinfo=None)
        end = start + dt.timedelta(minutes=DEFAULT_MINUTES)
        if not _exists(end, zone):
            # konec v mezere DST: 30 skutecnych minut
            first = start.replace(tzinfo=zone, fold=0)
            end = (first.astimezone(dt.timezone.utc) + dt.timedelta(minutes=DEFAULT_MINUTES)).astimezone(
                zone).replace(tzinfo=None)
        ev = ics.Event(summary=note["title"], start=start, end=end, uid=event_uid(request_id))
        tzname = note["timezone"]
    ev.description = note["text"]
    return ev, tzname


def event_bytes(ev, tzname, newline):
    ics = ics_module()
    return "".join(ics.fold(line) + newline for line in ev.to_lines(tzname)).encode("utf-8")


def _stat_key(st):
    return (st.st_ino, st.st_mtime_ns, st.st_size) if st else None


def _fsync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class CalendarWriter:
    """Zapis poznamek z telefonu do events.ics s deduplikaci UUID pozadavku."""

    def __init__(self, directory=None, done_path=None):
        self.dir = directory or calendar_dir()
        self.path = os.path.join(self.dir, "events.ics")
        self.lock_path = os.path.join(self.dir, ".events.ics.lock")
        self.done_path = done_path
        self.after_read = None       # testy: simulace zapisu Kalendare mezi ctenim a prejmenovanim
        self._done = None

    # ---- deduplikace ----
    def _load_done(self):
        if self._done is None:
            self._done = {}
            if self.done_path:
                try:
                    with open(self.done_path, encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self._done = {k: v for k, v in data.items()
                                      if isinstance(k, str) and isinstance(v, dict) and isinstance(v.get("uid"), str)}
                except (OSError, ValueError):
                    pass
        return self._done

    def _remember(self, request_id, uid):
        done = self._load_done()
        now = time.time()
        done[request_id] = {"uid": uid, "t": int(now)}
        limit = now - DONE_DAYS * 86400
        items = sorted((v.get("t", 0), k) for k, v in done.items())
        for t, k in items:
            if t < limit or len(done) > DONE_KEEP:
                del done[k]
        if not self.done_path:
            return
        os.makedirs(os.path.dirname(self.done_path), exist_ok=True)
        tmp = f"{self.done_path}.tmp-{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(done, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.done_path)

    def already_done(self, request_id):
        entry = self._load_done().get(request_id)
        return entry["uid"] if entry else None

    # ---- zapis ----
    def create(self, request_id, msg):
        """Overi a ulozi poznamku; vraci UID az po trvalem zapisu. Chyby: NoteError."""
        uid = self.already_done(request_id)
        if uid:
            return uid
        note = validate(msg)
        ev, tzname = build_event(note, request_id)
        try:
            self._insert(ev, tzname)
        except OSError as e:
            raise NoteError("storage_failed", _("The note could not be saved: %s") % (e.strerror or e)) from e
        try:
            self._remember(request_id, ev.uid)
        except OSError:
            pass                 # udalost je ulozena; opakovany pozadavek pozna podle UID v souboru
        return ev.uid

    def _insert(self, ev, tzname):
        ics = ics_module()
        os.makedirs(self.dir, exist_ok=True)
        with open(self.lock_path, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for _attempt in range(RETRIES):
                try:
                    with open(self.path, "rb") as f:
                        st = os.fstat(f.fileno())
                        old = f.read()
                except FileNotFoundError:
                    st, old = None, b""
                if old.strip():
                    if re.search(rb"(?im)^UID:" + re.escape(ev.uid.encode()) + rb"[ \t]*\r?$", old):
                        return               # uz ulozeno (opakovani po padu pred zapisem deduplikace)
                    ends = list(END_RE.finditer(old))
                    if not ends:
                        raise OSError(0, _("the calendar file is damaged (no END:VCALENDAR)"))
                    cut = ends[-1].start()
                    newline = "\r\n" if b"\r\n" in old else "\n"
                    new = old[:cut] + event_bytes(ev, tzname, newline) + old[cut:]
                else:
                    cal = ics.Calendar()
                    cal.events.append(ev)
                    new = cal.to_text(tzname).encode("utf-8")
                # kontrola: udalost jde precist zpet (stejnym parserem jako Kalendar)
                check = ics.parse(new.decode("utf-8", errors="replace"))
                if not any(e.uid == ev.uid for e in check.events):
                    raise OSError(0, "serialized event cannot be read back")
                if self.after_read:
                    self.after_read()
                tmp = f"{self.path}.tmp-{os.getpid()}"
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, (st.st_mode & 0o777) if st else 0o644)
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(new)
                        f.flush()
                        os.fsync(f.fileno())
                    try:
                        now_st = os.stat(self.path)
                    except FileNotFoundError:
                        now_st = None
                    if _stat_key(now_st) != _stat_key(st):
                        os.unlink(tmp)       # Kalendar mezitim zapsal - nacist znovu
                        continue
                    os.replace(tmp, self.path)
                except BaseException:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise
                _fsync_dir(self.dir)
                return
            raise OSError(0, _("the calendar file keeps changing, try again"))


# ---- cteni: calendar.events.list ----
def _occurrence_id(ev, start, used):
    """Jedinecne ID vyskytu (UID, u opakovani UID/zacatek), nejvys 200 znaku."""
    base = wire.clean_text(ev.uid or "", 1000, False)
    if ev.rrule or ev.recurrence_id is not None:
        base += "/" + (start.strftime("%Y%m%dT%H%M%S") if isinstance(start, dt.datetime) else start.strftime("%Y%m%d"))
    if ev.source:
        base = ev.source + ":" + base
    if not base or len(base) > MAX_EVENT_ID:
        base = "event-" + hashlib.sha256(base.encode("utf-8")).hexdigest()
    out, n = base, 1
    while out in used:
        n += 1
        out = f"{base[:MAX_EVENT_ID - 8]}#{n}"
    used.add(out)
    return out


class CalendarReader:
    """Vyskyty udalosti pro jeden den v pasmu telefonu (luxos_calendar_ics.Store, jen cteni)."""

    def __init__(self, directory=None):
        self.dir = directory or calendar_dir()
        self.store = None

    def _store(self):
        try:
            ics = ics_module()
        except ImportError as e:
            raise NoteError("storage_failed", _("The calendar cannot be read on this computer.")) from e
        if self.store is None:
            self.store = ics.Store(self.dir)
        self.store.reload_if_changed()
        return self.store

    def list_events(self, msg):
        """-> (udalosti [{"id","title","text","date","time","timezone"}], truncated). Chyby: NoteError."""
        day = parse_date(msg.get("date"))
        zone = _zone(msg.get("timezone"))
        tzname = msg["timezone"]
        limit = msg.get("limit", MAX_LIST)
        if type(limit) is not int or not 1 <= limit <= MAX_LIST:
            raise NoteError("invalid_request", _("Invalid number of calendar entries (1-100)."))
        try:
            store = self._store()
            utc = dt.timezone.utc
            start = dt.datetime.combine(day, dt.time()).replace(tzinfo=zone).astimezone(utc)
            end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time()).replace(tzinfo=zone).astimezone(utc)
            # udalosti v pameti jsou v mistnim case pocitace (naivni datetime) nebo cele dny (date)
            q0 = min(day, start.astimezone().date())
            q1 = max(day, end.astimezone().date()) + dt.timedelta(days=1)
            instances = store.instances(q0, q1)
        except OSError as e:
            raise NoteError("storage_failed", _("The calendar cannot be read on this computer.")) from e
        rows = []
        for ev, s, e in instances:
            span = ""
            if isinstance(s, dt.datetime):
                sa = s.astimezone(utc)
                ea = e.astimezone(utc) if isinstance(e, dt.datetime) else sa
                if not (sa < end and (ea > start or (ea == sa and sa >= start))):
                    continue
                sz, ez = sa.astimezone(zone), ea.astimezone(zone)
                if sa >= start:
                    clock = sz.strftime("%H:%M")
                elif ea >= end:
                    clock = None             # zacala drive a trva cely den
                else:
                    clock = "00:00"          # pokracuje z predchoziho dne
                last = (ez - dt.timedelta(microseconds=1)) if ez > sz else ez
                if sz.date() != last.date():
                    span = f"{sz:%Y-%m-%d %H:%M} – {ez:%Y-%m-%d %H:%M}"
                key = (1, sa)
            else:
                e_ = e if isinstance(e, dt.date) and e > s else s + dt.timedelta(days=1)
                if not s <= day < e_:
                    continue
                clock = None
                if (e_ - s).days > 1:
                    span = f"{s.isoformat()} – {(e_ - dt.timedelta(days=1)).isoformat()}"
                key = (0, start)
            rows.append((key, ev, s, clock, span))
        rows.sort(key=lambda r: (r[0][0], r[0][1], (r[1].summary or "").lower()))
        truncated = len(rows) > limit
        out, used = [], set()
        for _key, ev, s, clock, span in rows[:limit]:
            title = wire.clean_text(ev.summary, MAX_LIST_TITLE, False).strip() or _("(No title)")
            parts = [p for p in (span, wire.clean_text(ev.location, MAX_TEXT, False).strip(),
                                 wire.clean_text(ev.description, MAX_TEXT).strip()) if p]
            text = "\n\n".join(parts)
            if len(text) > MAX_TEXT:
                text, truncated = text[:MAX_TEXT], True
            out.append({"id": _occurrence_id(ev, s, used), "title": title, "text": text,
                        "date": day.isoformat(), "time": clock, "timezone": tzname})
        return out, truncated


def fit_events(msg, events):
    """Udalosti do ramce (64 KiB): nejdriv rovnomerne zkratit texty, az pak ubrat zaznamy.
    Vraci True, kdyz se neco zkratilo nebo vynechalo."""
    if not wire.fit_items(msg, "events", events):
        return False

    def capped(cap):
        return [dict(e, text=e["text"][:cap]) for e in events]
    lo, hi = 0, MAX_TEXT
    if wire.fit_items(msg, "events", capped(0)):
        return True                  # ani bez textu se vse nevejde - zustanou prvni zaznamy
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if wire.fit_items(msg, "events", capped(mid)):
            hi = mid - 1
        else:
            lo = mid
    wire.fit_items(msg, "events", capped(lo))
    return True
