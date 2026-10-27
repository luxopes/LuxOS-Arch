# LuxOS Kalendar - minimalni, odolne cteni a zapis iCalendar (RFC 5545) a vyskyty udalosti.
# Prepis luxos_calendar_ics.py do LSL se stejnym chovanim: VEVENT (SUMMARY, DTSTART/DTEND/DURATION,
# RRULE DAILY/WEEKLY/MONTHLY/YEARLY s INTERVAL/COUNT/UNTIL/BYDAY/BYMONTHDAY/BYMONTH, EXDATE, RECURRENCE-ID,
# COLOR, VALARM); nezname vlastnosti a komponenty se zachovavaji beze zmeny.
#
# Udalost je Dictionary: uid, summary, all_day (Bool), start, end (Int: den jako ordinal, nebo naivni
# mistni cas v sekundach; end muze byt None), color, description, location, rrule (Dictionary/None),
# rrule_raw, exdates ([[kind, hodnota]], kind "D"/"T"), exdate_lines, recurrence_id ([kind, hodnota]/None),
# extra (radky), alarms (seznam bloku radku), source (nazev souboru / None), readonly, duration_prop.
# Kalendar: {header, events, other, errors}. Uloziste: viz store_new.
load env
load luxos_glib, glib as glib
load luxos_date as date
load luxos_text as text

COLORS = ["red", "orange", "yellow", "green", "blue", "purple"]
COLOR_HEX = {"red": "#ff453a", "orange": "#ff9f0a", "yellow": "#ffd60a", "green": "#30d158", "blue": "#0a84ff", "purple": "#bf5af2"}
DEFAULT_COLOR = "blue"
WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
MAX_INSTANCES = 50000
PRODID = "-//LuxOS//Calendar 1.0//EN"
KNOWN = ["UID", "SUMMARY", "DTSTART", "DTEND", "DURATION", "RRULE", "EXDATE", "COLOR", "RECURRENCE-ID", "DESCRIPTION", "LOCATION"]
CSS_NAMES = {"tomato": "red", "crimson": "red", "darkorange": "orange", "gold": "yellow", "limegreen": "green",
             "seagreen": "green", "dodgerblue": "blue", "royalblue": "blue", "navy": "blue", "violet": "purple",
             "magenta": "purple", "orchid": "purple"}

# ---- radky a hodnoty ----------------------------------------------------------------------------

# Rozbali zalomene radky (CRLF/LF + mezera nebo tabulator)
function unfold(source):
    body = source.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for line in body.split("\n"):
        if (line.startswith(" ") or line.startswith("\t")) and len(out) > 0:
            out[len(out) - 1] = out[len(out) - 1] + line[1:]
        elif line.strip() != "":
            out.append(line)
        end
    end
    return out
end

# Zalomi radek na max. 75 oktetu (bez rozdeleni vicebajtoveho znaku)
function fold(line):
    out = []
    current = ""
    size = 0
    limit = 75
    for ch in line:
        n = text.utf8_length(ch)
        if size + n > limit:
            out.append(current)
            current = " "
            size = 1
            limit = 75
        end
        current = current + ch
        size += n
    end
    out.append(current)
    return text.join(out, "\r\n")
end

function valid_name(name):
    if name == "":
        return False
    end
    for ch in name:
        code = ord(ch)
        if not ((code >= 65 and code <= 90) or (code >= 48 and code <= 57) or ch == "-"):
            return False
        end
    end
    return True
end

# 'NAME;P=V;Q="a:b":hodnota' -> [NAME, {P: V}, hodnota]; neplatny radek -> None
function parse_line(line):
    i = 0
    n = len(line)
    quoted = False
    while i < n:
        c = line[i]
        if c == "\"":
            quoted = not quoted
        elif c == ":" and not quoted:
            break
        end
        i += 1
    end
    if i >= n:
        return None
    end
    head = line[0:i]
    value = line[i + 1:]
    parts = []
    current = ""
    quoted = False
    for c in head:
        if c == "\"":
            quoted = not quoted
            current = current + c
        elif c == ";" and not quoted:
            parts.append(current)
            current = ""
        else:
            current = current + c
        end
    end
    parts.append(current)
    name = parts[0].strip().upper()
    if not valid_name(name):
        return None
    end
    params = {}
    index = 1
    while index < len(parts):
        p = parts[index]
        if p.find("=") >= 0:
            kv = text.partition(p, "=")
            params[kv[0].strip().upper()] = text.rstrip_chars(text.lstrip_chars(kv[1].strip(), "\""), "\"")
        end
        index += 1
    end
    return [name, params, value]
end

function unescape(value):
    out = ""
    i = 0
    n = len(value)
    while i < n:
        c = value[i]
        if c == "\\" and i + 1 < n:
            nx = value[i + 1]
            if nx == "n" or nx == "N":
                out = out + "\n"
            else:
                out = out + nx
            end
            i += 2
            continue
        end
        out = out + c
        i += 1
    end
    return out
end

function escape(value):
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")
end

function zone_known(name):
    return name != "" and name.find("..") < 0 and exists("/usr/share/zoneinfo/" + name)
end

# DATE nebo DATE-TIME -> ["D", ordinal] / ["T", naivni mistni cas]; neplatna hodnota -> ValueError
function parse_dt(value, params):
    v = value.strip()
    is_date = False
    if params.get("VALUE", "").upper() == "DATE":
        is_date = True
    end
    if len(v) == 8 and text.is_digits(v):
        is_date = True
    end
    if is_date:
        if len(v) < 8 or not text.is_digits(v[0:8]):
            Error(ValueError: bad_date)
        end
        return ["D", date.ordinal(Int(v[0:4]), Int(v[4:6]), Int(v[6:8]))]
    end
    n = len(v)
    utc = False
    if n > 0 and v[n - 1] == "Z":
        utc = True
        v = v[0:n - 1]
        n -= 1
    end
    if not (n == 13 or n == 15) or v[8] != "T" or not text.is_digits(v[0:8]) or not text.is_digits(v[9:]):
        Error(ValueError: bad_datetime)
    end
    second = 0
    if n == 15:
        second = min(Int(v[13:15]), 59)
    end
    month = Int(v[4:6])
    day = Int(v[6:8])
    if month < 1 or month > 12 or day < 1 or day > date.days_in_month(Int(v[0:4]), month):
        Error(ValueError: bad_datetime)
    end
    hour = Int(v[9:11])
    minute = Int(v[11:13])
    if hour > 23 or minute > 59:
        Error(ValueError: bad_datetime)
    end
    moment = date.make(date.ordinal(Int(v[0:4]), month, day), hour, minute, second)
    if utc:
        return ["T", date.local_from_utc(moment)]
    end
    zone = params.get("TZID", "")
    if zone_known(zone):
        return ["T", date.local_from_zone(moment, zone)]
    end
    return ["T", moment]
end

# RFC 5545 DURATION (-PT10M, P1D, P1W, PT1H30M) -> sekundy (se znamenkem); ValueError pri chybe
function parse_duration(value):
    v = value.strip()
    sign = 1
    i = 0
    if v.startswith("-"):
        sign = -1
        i = 1
    elif v.startswith("+"):
        i = 1
    end
    if i >= len(v) or v[i] != "P" or len(v) == i + 1:
        Error(ValueError: bad_duration)
    end
    i += 1
    total = 0
    in_time = False
    seen = ""
    while i < len(v):
        c = v[i]
        if c == "T":
            if in_time:
                Error(ValueError: bad_duration)
            end
            in_time = True
            i += 1
            continue
        end
        start = i
        while i < len(v) and text.is_digit(v[i]):
            i += 1
        end
        if start == i or i >= len(v):
            Error(ValueError: bad_duration)
        end
        number = Int(v[start:i])
        unit = v[i]
        i += 1
        if not in_time and unit == "W" and seen == "":
            total += number * 7 * 86400
        elif not in_time and unit == "D" and (seen == "" or seen == "W"):
            total += number * 86400
        elif in_time and unit == "H" and seen.find("H") < 0 and seen.find("M") < 0 and seen.find("S") < 0:
            total += number * 3600
        elif in_time and unit == "M" and seen.find("M") < 0 and seen.find("S") < 0:
            total += number * 60
        elif in_time and unit == "S" and seen.find("S") < 0:
            total += number
        else:
            Error(ValueError: bad_duration)
        end
        seen = seen + unit
    end
    if in_time and (seen == "" or seen.endswith("T")):
        Error(ValueError: bad_duration)
    end
    return sign * total
end

# [parametry, hodnota] pro zapis DTSTART/DTEND
function format_dt(kind, value, tzname):
    if kind == "D":
        return [";VALUE=DATE", date.format_date(value)]
    end
    if zone_known(tzname):
        return [";TZID=" + tzname, date.format_moment(value)]
    end
    return ["", date.format_moment(value)]
end

function new_uid():
    raw = glib.read_text("/proc/sys/kernel/random/uuid").strip()
    if raw == "":
        raw = String(glib.now()) + "-" + String(glib.monotonic_time())
    end
    return raw + "@luxos"
end

# ---- udalost ----------------------------------------------------------------------------------------

function event_new(summary, all_day, start, finish, color):
    return {"uid": new_uid(), "summary": summary, "all_day": all_day, "start": start, "end": finish, "color": color,
            "description": "", "location": "", "rrule": None, "rrule_raw": None, "exdates": [], "exdate_lines": [],
            "recurrence_id": None, "extra": [], "alarms": [], "source": None, "readonly": False, "duration_prop": None}
end

function kind_of(ev):
    if ev["all_day"]:
        return "D"
    end
    return "T"
end

# Delka: dny (celodenni) nebo sekundy
function duration(ev):
    if ev["end"] == None:
        if ev["all_day"]:
            return 1
        end
        return 0
    end
    return max(ev["end"] - ev["start"], 0)
end

# Minuty pred zacatkem z VALARM (TRIGGER relativne k zacatku), jinak None
function reminder_minutes(ev):
    best = None
    for block in ev["alarms"]:
        for line in block:
            p = parse_line(line)
            if p == None or p[0] != "TRIGGER":
                continue
            end
            params = p[1]
            if params.get("VALUE", "").upper() == "DATE-TIME" or params.get("RELATED", "START").upper() != "START":
                continue
            end
            seconds = 0
            ok = True
            try:
                seconds = parse_duration(p[2])
            else:
                ok = False
            end
            if not ok:
                continue
            end
            mins = (0 - seconds) // 60
            if mins >= 0 and (best == None or mins < best):
                best = mins
            end
        end
    end
    return best
end

# Nastavi pripominku (None = zadna); nezmenenou ponecha beze zmen
function set_reminder(ev, minutes):
    current = reminder_minutes(ev)
    if minutes == current and (minutes != None or len(ev["alarms"]) == 0):
        return 0
    end
    ev["alarms"] = []
    if minutes != None:
        summary = ev["summary"]
        if summary == "":
            summary = "Reminder"
        end
        ev["alarms"].append(["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + escape(summary), "TRIGGER:-PT" + String(minutes) + "M", "END:VALARM"])
    end
    return 0
end

function set_rrule(ev, raw):
    if raw == None or raw == "":
        ev["rrule_raw"] = None
        ev["rrule"] = None
    else:
        ev["rrule_raw"] = raw
        ev["rrule"] = parse_rrule(raw)
    end
    return 0
end

function parse_rrule(raw):
    r = {}
    for part in raw.split(";"):
        if part.find("=") >= 0:
            kv = text.partition(part, "=")
            key = kv[0].strip().upper()
            if key == "UNTIL":
                r[key] = kv[1].strip()
            else:
                r[key] = kv[1].strip().upper()
            end
        end
    end
    return r
end

function has_dtstamp(ev):
    for x in ev["extra"]:
        if x.upper().startswith("DTSTAMP"):
            return True
        end
    end
    return False
end

function to_lines(ev, tzname):
    lines = ["BEGIN:VEVENT", "UID:" + ev["uid"]]
    if not has_dtstamp(ev):
        g = glib.gmtime(glib.now())
        lines.append("DTSTAMP:" + date.pad4(g[0]) + date.pad2(g[1]) + date.pad2(g[2]) + "T" + date.pad2(g[3]) + date.pad2(g[4]) + date.pad2(g[5]) + "Z")
    end
    kind = kind_of(ev)
    if ev["recurrence_id"] != None:
        rid = ev["recurrence_id"]
        pv = format_dt(rid[0], rid[1], tzname)
        lines.append("RECURRENCE-ID" + pv[0] + ":" + pv[1])
    end
    pv = format_dt(kind, ev["start"], tzname)
    lines.append("DTSTART" + pv[0] + ":" + pv[1])
    if ev["end"] != None:
        pv = format_dt(kind, ev["end"], tzname)
        lines.append("DTEND" + pv[0] + ":" + pv[1])
    end
    lines.append("SUMMARY:" + escape(ev["summary"]))
    if ev["description"] != "":
        lines.append("DESCRIPTION:" + escape(ev["description"]))
    end
    if ev["location"] != "":
        lines.append("LOCATION:" + escape(ev["location"]))
    end
    if ev["color"] != None and ev["color"] != "":
        lines.append("COLOR:" + ev["color"])
    end
    if ev["rrule_raw"] != None and ev["rrule_raw"] != "":
        lines.append("RRULE:" + ev["rrule_raw"])
    end
    lines.extend(ev["exdate_lines"])
    lines.extend(ev["extra"])
    for block in ev["alarms"]:
        lines.extend(block)
    end
    lines.append("END:VEVENT")
    return lines
end

# ---- vyskyty ------------------------------------------------------------------------------------------

function rule_int(r, key, default):
    value = r.get(key)
    if value == None:
        return default
    end
    return text.to_int(value, default)
end

# 'MO,-1FR,2TU' -> [[None nebo n, den v tydnu]]
function byday(spec):
    out = []
    if spec == None:
        return out
    end
    for raw in spec.split(","):
        item = raw.strip()
        if len(item) < 2:
            continue
        end
        code = item[len(item) - 2:]
        prefix = item[0:len(item) - 2]
        if code not in WEEKDAYS:
            continue
        end
        nth = None
        if prefix != "":
            body = prefix
            if body.startswith("+") or body.startswith("-"):
                body = body[1:]
            end
            if not text.is_digits(body) or len(body) > 2:
                continue
            end
            nth = Int(prefix.replace("+", ""))
        end
        out.append([nth, WEEKDAYS.index(code)])
    end
    return out
end

function bymonth_set(r):
    out = []
    spec = r.get("BYMONTH")
    if spec == None:
        return out
    end
    for x in spec.split(","):
        m = text.to_int(x, 0)
        if m >= 1 and m <= 12 and m not in out:
            out.append(m)
        end
    end
    return out
end

# Dny (ordinaly) v mesici podle BYMONTHDAY/BYDAY (jinak den mesice ze startu), serazene
function month_days(year, month, r, start_day):
    dim = date.days_in_month(year, month)
    days = []
    bymd = []
    spec = r.get("BYMONTHDAY")
    if spec != None:
        for x in spec.split(","):
            if x.strip() != "":
                bymd.append(x)
            end
        end
    end
    rule_days = byday(r.get("BYDAY"))
    if len(bymd) > 0:
        for x in bymd:
            v = text.to_int(x, 0)
            if v > 0 and v <= dim and v not in days:
                days.append(v)
            elif v < 0 and 0 - v <= dim and dim + v + 1 not in days:
                days.append(dim + v + 1)
            end
        end
    elif len(rule_days) > 0:
        for item in rule_days:
            nth = item[0]
            wd = item[1]
            matches = []
            d = 1
            while d <= dim:
                if date.weekday(date.ordinal(year, month, d)) == wd:
                    matches.append(d)
                end
                d += 1
            end
            if nth == None:
                for m in matches:
                    if m not in days:
                        days.append(m)
                    end
                end
            elif nth > 0 and nth <= len(matches):
                if matches[nth - 1] not in days:
                    days.append(matches[nth - 1])
                end
            elif nth < 0 and 0 - nth <= len(matches):
                if matches[len(matches) + nth] not in days:
                    days.append(matches[len(matches) + nth])
                end
            end
        end
    elif date.day_of(start_day) <= dim:
        days.append(date.day_of(start_day))
    end
    out = []
    for d in sorted(days):
        out.append(date.ordinal(year, month, d))
    end
    return out
end

# Zacatky vyskytu (vzestupne) do dne until_day (bez nej), v domene udalosti
function starts(ev, until_day):
    r = ev["rrule"]
    if r == None:
        return [ev["start"]]
    end
    freq = r.get("FREQ")
    if freq != "DAILY" and freq != "WEEKLY" and freq != "MONTHLY" and freq != "YEARLY":
        return [ev["start"]]
    end
    interval = max(1, rule_int(r, "INTERVAL", 1))
    count = rule_int(r, "COUNT", None)
    until = None
    if r.get("UNTIL") != None and r.get("UNTIL") != "":
        safe:
            until = parse_dt(r["UNTIL"], {})
        end
    end
    all_day = ev["all_day"]
    start = ev["start"]
    start_day = start
    tod = 0
    if not all_day:
        start_day = date.date_of(start)
        tod = start - start_day * date.DAY
    end
    # mez UNTIL v domene udalosti
    until_value = None
    if until != None:
        if until[0] == "T" and all_day:
            until_value = date.date_of(until[1])
        elif until[0] == "D" and not all_day:
            until_value = date.make(until[1], 23, 59, 59)
        else:
            until_value = until[1]
        end
    end
    state = {"out": [], "n": 0, "produced": 0, "done": False, "count": count, "until": until_value,
             "limit": until_day, "all_day": all_day, "tod": tod, "start_day": start_day, "excluded": ev["exdates"]}
    # DTSTART je vzdy prvni vyskyt (RFC 5545), i kdyz pravidlu neodpovida
    call emit_day(state, start_day)
    bymonth = bymonth_set(r)
    if freq == "DAILY":
        d = start_day
        while not state["done"]:
            if len(bymonth) == 0 or date.month_of(d) in bymonth:
                call candidate(state, d)
            end
            d += interval
            if d >= until_day and d > start_day:
                break
            end
        end
    elif freq == "WEEKLY":
        wds = []
        for item in byday(r.get("BYDAY")):
            if item[1] not in wds:
                wds.append(item[1])
            end
        end
        if len(wds) == 0:
            wds = [date.weekday(start_day)]
        end
        wds = sorted(wds)
        wkst = 0
        if r.get("WKST") in WEEKDAYS:
            wkst = WEEKDAYS.index(r["WKST"])
        end
        week = start_day - (date.weekday(start_day) - wkst) % 7
        while not state["done"]:
            days = []
            for wd in wds:
                days.append(week + (wd - wkst) % 7)
            end
            for d in sorted(days):
                if len(bymonth) == 0 or date.month_of(d) in bymonth:
                    call candidate(state, d)
                end
            end
            week += 7 * interval
            if week >= until_day:
                break
            end
        end
    elif freq == "MONTHLY":
        ym = date.from_ordinal(start_day)
        y = ym[0]
        m = ym[1]
        while not state["done"]:
            if len(bymonth) == 0 or m in bymonth:
                for d in month_days(y, m, r, start_day):
                    call candidate(state, d)
                end
            end
            ym = date.add_months(y, m, interval)
            y = ym[0]
            m = ym[1]
            if y > 9999 or date.ordinal(y, m, 1) >= until_day:
                break
            end
        end
    else:
        ym = date.from_ordinal(start_day)
        y = ym[0]
        start_month = ym[1]
        start_dom = ym[2]
        explicit = len(bymonth) > 0 or r.get("BYDAY") != None or r.get("BYMONTHDAY") != None
        while not state["done"]:
            if explicit:
                months = bymonth
                if len(months) == 0:
                    months = [start_month]
                end
                for m in sorted(months):
                    for d in month_days(y, m, r, start_day):
                        call candidate(state, d)
                    end
                end
            elif start_dom <= date.days_in_month(y, start_month):
                call candidate(state, date.ordinal(y, start_month, start_dom))
            end
            y += interval
            if y > 9999 or date.ordinal(y, 1, 1) >= until_day:
                break
            end
        end
    end
    return state["out"]
end

# Kandidatni den z pravidla (jen po dni DTSTART)
function candidate(state, day):
    if day > state["start_day"]:
        call emit_day(state, day)
    end
    return 0
end

function emit_day(state, day):
    if state["done"]:
        return 0
    end
    state["n"] += 1
    if state["n"] > MAX_INSTANCES:
        state["done"] = True
        return 0
    end
    s = day
    if not state["all_day"]:
        s = day * date.DAY + state["tod"]
    end
    if state["until"] != None and s > state["until"]:
        state["done"] = True
        return 0
    end
    state["produced"] += 1
    if state["count"] != None and state["produced"] > state["count"]:
        state["done"] = True
        return 0
    end
    if day >= state["limit"]:
        state["done"] = True
        return 0
    end
    for ex in state["excluded"]:
        if ex[0] == "D" and ex[1] == day:
            return 0
        end
        if ex[0] == "T" and not state["all_day"] and ex[1] == s:
            return 0
        end
    end
    state["out"].append(s)
    return 0
end

# Vyskyty [[zacatek, konec]] protinajici interval dnu <range_start, range_end), v domene udalosti
function occurrences(ev, range_start, range_end):
    dur = duration(ev)
    rs = range_start
    re_ = range_end
    if not ev["all_day"]:
        rs = range_start * date.DAY
        re_ = range_end * date.DAY
    end
    out = []
    for s in starts(ev, range_end):
        e = s + dur
        if s >= re_:
            break
        end
        if e > rs or (s >= rs and dur == 0):
            out.append([s, e])
        end
    end
    return out
end

# ---- kalendar (soubor) ---------------------------------------------------------------------------------

function calendar_new():
    return {"header": ["VERSION:2.0", "PRODID:" + PRODID], "events": [], "other": [], "errors": 0}
end

function to_text(cal, tzname):
    lines = ["BEGIN:VCALENDAR"]
    lines.extend(cal["header"])
    for block in cal["other"]:
        lines.extend(block)
    end
    for ev in cal["events"]:
        lines.extend(to_lines(ev, tzname))
    end
    lines.append("END:VCALENDAR")
    out = ""
    for x in lines:
        out = out + fold(x) + "\r\n"
    end
    return out
end

# Udalost z radku VEVENT (bez BEGIN/END); ValueError bez DTSTART nebo s neplatnym datem
function event_from_lines(lines):
    ev = event_new("", False, None, None, None)
    ev["uid"] = ""
    i = 0
    n = len(lines)
    duration_prop = None
    while i < n:
        line = lines[i]
        up = line.upper()
        if up.startswith("BEGIN:"):
            name = up[6:].strip()
            block = [line]
            depth = 1
            i += 1
            while i < n and depth > 0:
                block.append(lines[i])
                u = lines[i].upper()
                if u.startswith("BEGIN:"):
                    depth += 1
                elif u.startswith("END:"):
                    depth -= 1
                end
                i += 1
            end
            if name == "VALARM":
                ev["alarms"].append(block)
            else:
                ev["extra"].extend(block)
            end
            continue
        end
        i += 1
        p = parse_line(line)
        if p == None:
            ev["extra"].append(line)
            continue
        end
        name = p[0]
        params = p[1]
        value = p[2]
        if name not in KNOWN:
            ev["extra"].append(line)
        elif name == "UID":
            ev["uid"] = value.strip()
        elif name == "SUMMARY":
            ev["summary"] = unescape(value)
        elif name == "DESCRIPTION":
            ev["description"] = unescape(value)
        elif name == "LOCATION":
            ev["location"] = unescape(value)
        elif name == "COLOR":
            ev["color"] = value.strip().lower()
        elif name == "DTSTART":
            kv = parse_dt(value, params)
            ev["all_day"] = kv[0] == "D"
            ev["start"] = kv[1]
            ev["start_kind"] = kv[0]
        elif name == "DTEND":
            kv = parse_dt(value, params)
            ev["end"] = kv[1]
            ev["end_kind"] = kv[0]
        elif name == "DURATION":
            duration_prop = parse_duration(value)
        elif name == "RECURRENCE-ID":
            ev["recurrence_id"] = parse_dt(value, params)
        elif name == "RRULE":
            call set_rrule(ev, value.strip())
        elif name == "EXDATE":
            ev["exdate_lines"].append(line)
            for v in value.split(","):
                if v.strip() != "":
                    ev["exdates"].append(parse_dt(v, params))
                end
            end
        end
    end
    if ev["start"] == None:
        Error(ValueError: vevent_without_dtstart)
    end
    if ev["end"] == None and duration_prop != None:
        if ev["all_day"]:
            ev["end"] = ev["start"] + duration_prop // 86400
        else:
            ev["end"] = ev["start"] + duration_prop
        end
    end
    if ev["end"] != None and ev.get("end_kind") != None and ev["end_kind"] != ev["start_kind"]:
        # nesoulad typu (DTSTART datum, DTEND cas): zarovnat na typ zacatku
        if ev["end_kind"] == "T":
            ev["end"] = date.date_of(ev["end"])
        else:
            ev["end"] = ev["end"] * date.DAY
        end
    end
    if ev["end"] != None and ev["end"] < ev["start"]:
        ev["end"] = ev["start"]
    end
    if ev["uid"] == "":
        ev["uid"] = new_uid()
    end
    call ev.pop("start_kind", None)
    call ev.pop("end_kind", None)
    return ev
end

# Text .ics -> kalendar; chybne VEVENT se preskoci (errors), zbytek se nacte
function parse(source):
    cal = calendar_new()
    body = source
    while body.startswith(chr(65279)):
        body = body[1:]
    end
    lines = unfold(body)
    header = []
    i = 0
    n = len(lines)
    in_cal = False
    while i < n:
        line = lines[i]
        up = line.upper().strip()
        if up == "BEGIN:VCALENDAR":
            in_cal = True
            i += 1
            continue
        end
        if up == "END:VCALENDAR":
            in_cal = False
            i += 1
            continue
        end
        if up.startswith("BEGIN:"):
            name = up[6:]
            block = [line]
            depth = 1
            i += 1
            while i < n and depth > 0:
                u = lines[i].upper().strip()
                if u.startswith("BEGIN:"):
                    depth += 1
                elif u.startswith("END:"):
                    depth -= 1
                end
                block.append(lines[i])
                i += 1
            end
            if name == "VEVENT":
                inner = block[1:]
                if block[len(block) - 1].upper().startswith("END:"):
                    inner = block[1:len(block) - 1]
                end
                ok = True
                ev = None
                try:
                    ev = event_from_lines(inner)
                else:
                    ok = False
                end
                if ok:
                    cal["events"].append(ev)
                else:
                    cal["errors"] += 1
                    cal["other"].append(block)
                end
            else:
                cal["other"].append(block)
            end
            continue
        end
        if in_cal and parse_line(line) != None:
            header.append(line)
        end
        i += 1
    end
    if len(header) > 0:
        has_version = False
        for h in header:
            if h.upper().startswith("VERSION"):
                has_version = True
            end
        end
        if not has_version:
            header.insert(0, "VERSION:2.0")
        end
        cal["header"] = header
    end
    return cal
end

function read_file(path):
    return parse(readfile(path))
end

# Atomicky zapis (docasny soubor + prejmenovani)
function write_file(path, cal, tzname):
    cut = text.rfind(path, "/")
    if cut > 0:
        call glib.mkdir_p(path[0:cut])
    end
    tmp = path + ".tmp-" + String(glib.getpid())
    call writefile(tmp, to_text(cal, tzname))
    call glib.rename(tmp, path)
    return 0
end

# ---- uloziste -----------------------------------------------------------------------------------------

OWN = "events.ics"

function default_dir():
    base = env.get("XDG_DATA_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.local/share"
    end
    return base + "/luxos/calendar"
end

function store_new(directory):
    dir = directory
    if dir == "" or dir == None:
        dir = default_dir()
    end
    return {"dir": dir, "own_path": dir + "/" + OWN, "own": calendar_new(), "foreign": {}, "stamp": None, "known": {},
            "version": 0, "tzname": date.local_tz_name(), "cache": {}}
end

function scan(store):
    out = {}
    for name in glib.list_dir(store["dir"]):
        if name.lower().endswith(".ics") and not name.startswith("."):
            st = glib.stat(store["dir"] + "/" + name)
            if len(st) == 2:
                out[name] = String(st[1]) + ":" + String(st[0])
            end
        end
    end
    return out
end

# Nacte znovu, pokud se slozka zmenila; True pri zmene
function reload_if_changed(store):
    stamp = scan(store)
    if store["stamp"] != None and stamp == store["stamp"]:
        return False
    end
    store["stamp"] = stamp
    store["own"] = calendar_new()
    store["foreign"] = {}
    for name in sorted(stamp.keys()):
        cal = None
        ok = True
        try:
            cal = read_file(store["dir"] + "/" + name)
        else:
            ok = False
        end
        if not ok:
            continue
        end
        if name == OWN:
            store["own"] = cal
        else:
            for ev in cal["events"]:
                ev["source"] = name
                ev["readonly"] = True
            end
            store["foreign"][name] = cal
        end
    end
    call remember_known(store)
    store["version"] += 1
    store["cache"] = {}
    return True
end

# UID udalosti vlastniho kalendare podle posledniho nacteni ze souboru
function remember_known(store):
    known = {}
    for ev in store["own"]["events"]:
        known[ev["uid"]] = True
    end
    store["known"] = known
    return 0
end

# Pred zapisem: zmenil-li soubor nekdo jiny (LuxOS Companion z telefonu, import) a Kalendar to jeste
# nenacetl, prevzit jeho nove udalosti - jinak by je zapis z pameti smazal. Udalosti smazane zde
# (byly pri poslednim nacteni) se nevraceji.
function merge_external(store):
    st = glib.stat(store["own_path"])
    if len(st) != 2:
        return 0
    end
    disk = String(st[1]) + ":" + String(st[0])
    if store["stamp"] != None and store["stamp"].get(OWN) == disk:
        return 0
    end
    cal = None
    ok = True
    try:
        cal = read_file(store["own_path"])
    else:
        ok = False
    end
    if not ok:
        return 0
    end
    present = {}
    for ev in store["own"]["events"]:
        present[ev["uid"]] = True
    end
    for ev in cal["events"]:
        if store["known"].get(ev["uid"]) == None and present.get(ev["uid"]) == None:
            store["own"]["events"].append(ev)
            present[ev["uid"]] = True
        end
    end
    return 0
end

function save(store):
    call merge_external(store)
    call write_file(store["own_path"], store["own"], store["tzname"])
    store["stamp"] = None
    call reload_if_changed(store)
    return 0
end

function all_events(store):
    out = []
    out.extend(store["own"]["events"])
    for name in sorted(store["foreign"].keys()):
        cal = store["foreign"][name]
        out.extend(cal["events"])
    end
    return out
end

# Udalost podle uid (bez RECURRENCE-ID); source = nazev ciziho kalendare nebo None
function find(store, uid, source):
    cal = store["own"]
    if source != None:
        cal = store["foreign"].get(source)
        if cal == None:
            return None
        end
    end
    for ev in cal["events"]:
        if ev["uid"] == uid and ev["recurrence_id"] == None:
            return ev
        end
    end
    return None
end

function add(store, ev):
    store["own"]["events"].append(ev)
    return save(store)
end

function update(store, ev):
    found = False
    events = store["own"]["events"]
    index = 0
    while index < len(events):
        e = events[index]
        if e["uid"] == ev["uid"] and e["recurrence_id"] == ev["recurrence_id"]:
            found = True
            # po nacteni zmen ze souboru (inotify) je v pameti nova kopie udalosti - ulozit upravenou
            events[index] = ev
        end
        index += 1
    end
    if not found:
        Error(KeyError: event_not_in_own_calendar)
    end
    return save(store)
end

function delete(store, ev):
    kept = []
    for e in store["own"]["events"]:
        if e["uid"] != ev["uid"]:
            kept.append(e)
        end
    end
    store["own"]["events"] = kept
    return save(store)
end

# Odstrani udalost z vlastniho kalendare bez ulozeni (zruseni po chybe zapisu)
function forget(store, ev):
    events = store["own"]["events"]
    index = 0
    while index < len(events):
        if events[index]["uid"] == ev["uid"]:
            call events.pop(index)
            return 0
        end
        index += 1
    end
    return 0
end

function sort_key_moment(ev, s):
    if ev["all_day"]:
        return s * date.DAY
    end
    return s
end

# Vyskyty vsech udalosti v intervalu dnu <start, end): [[ev, zacatek, konec]] serazene
# (cely den napred, pak podle casu a nazvu)
function instances(store, start, finish):
    key = String(start) + ":" + String(finish)
    cached = store["cache"].get(key)
    if cached != None:
        return cached
    end
    overrides = {}
    events = all_events(store)
    for ev in events:
        if ev["recurrence_id"] != None:
            okey = String(ev["source"]) + "|" + ev["uid"]
            if okey not in overrides:
                overrides[okey] = []
            end
            overrides[okey].append(ev["recurrence_id"])
        end
    end
    buckets = {}
    for ev in events:
        skip = []
        if ev["recurrence_id"] == None and ev["rrule"] != None:
            skip = overrides.get(String(ev["source"]) + "|" + ev["uid"], [])
        end
        kind = kind_of(ev)
        for se in occurrences(ev, start, finish):
            skipped = False
            for rid in skip:
                if rid[0] == kind and rid[1] == se[0]:
                    skipped = True
                end
            end
            if skipped:
                continue
            end
            flag = "1"
            if ev["all_day"]:
                flag = "0"
            end
            sort_key = flag + text.pad(sort_key_moment(ev, se[0]), 20) + ev["summary"].lower()
            if sort_key not in buckets:
                buckets[sort_key] = []
            end
            buckets[sort_key].append([ev, se[0], se[1]])
        end
    end
    out = []
    for sort_key in sorted(buckets.keys()):
        out.extend(buckets[sort_key])
    end
    if len(store["cache"]) > 64:
        store["cache"] = {}
    end
    store["cache"][key] = out
    return out
end

function day_instances(store, day):
    return instances(store, day, day + 1)
end

# {den: barva prvni udalosti} pro dny v intervalu (tecky v mesicni/rocni mrizce)
function busy_days(store, start, finish):
    out = {}
    for item in instances(store, start, finish):
        ev = item[0]
        s = item[1]
        e = item[2]
        d0 = s
        d1 = s
        if ev["all_day"]:
            d1 = e - 1
        else:
            d0 = date.date_of(s)
            if e > s:
                d1 = date.date_of(e - 1)
            else:
                d1 = d0
            end
        end
        d = max(d0, start)
        while d <= d1 and d < finish:
            if d not in out:
                out[d] = event_color(ev)
            end
            d += 1
        end
    end
    return out
end

# Stala barva pro kalendar jen ke cteni (podle nazvu souboru)
function source_color(name):
    h = 0
    if name != None:
        for ch in name:
            code = ord(ch)
            if code < 128:
                h += code
            elif code < 2048:
                h += 192 + (code >> 6) + 128 + (code & 63)
            elif code < 65536:
                h += 224 + (code >> 12) + 128 + ((code >> 6) & 63) + 128 + (code & 63)
            else:
                h += 240 + (code >> 18) + 128 + ((code >> 12) & 63) + 128 + ((code >> 6) & 63) + 128 + (code & 63)
            end
        end
    end
    return COLORS[h % len(COLORS)]
end

function event_color(ev):
    c = ev["color"]
    if c == None:
        c = ""
    end
    c = c.lower()
    if c in COLOR_HEX:
        return c
    end
    if c in CSS_NAMES:
        return CSS_NAMES[c]
    end
    if ev["source"] != None:
        return source_color(ev["source"])
    end
    return DEFAULT_COLOR
end
