# Testovaci program pro luxos_ics (spousti test_lsl_calendar.py): vypisuje vysledky funkci modulu,
# aby je test mohl porovnat s chovanim puvodniho luxos_calendar_ics.py.
load luxos_glib as glib
load luxos_date as date
load luxos_ics as ics
load luxos_text as text

function fmt(ev, value):
    if ev["all_day"]:
        return date.format_date(value)
    end
    return date.format_moment(value)
end

function fmt_kv(kv):
    if kv[0] == "D":
        return date.format_date(kv[1])
    end
    return date.format_moment(kv[1])
end

# "20261020" nebo "20261020T090000" -> [kind, hodnota]
function parse_value(textual):
    return ics.parse_dt(textual, {})
end

function print_event(ev):
    finish = "-"
    if ev["end"] != None:
        finish = fmt(ev, ev["end"])
    end
    rrule = String(ev["rrule_raw"])
    reminder = String(ics.reminder_minutes(ev))
    print ev["uid"] + "|" + ev["summary"] + "|" + ev["description"].replace("\n", "\\n") + "|" + fmt(ev, ev["start"]) + "|" + finish + "|" + rrule + "|" + reminder + "|" + String(ev["color"]) + "|" + String(len(ev["alarms"])) + "|" + String(len(ev["extra"]))
end

function print_days(ev, range_start, range_end):
    for se in ics.occurrences(ev, range_start, range_end):
        print fmt(ev, se[0])
    end
end

command = arg(1)
if command == "parse":
    cal = ics.read_file(arg(2))
    print "errors", cal["errors"], "other", len(cal["other"]), "header", len(cal["header"])
    for ev in cal["events"]:
        call print_event(ev)
    end
elif command == "text":
    cal = ics.read_file(arg(2))
    print ics.to_text(cal, arg(3))
elif command == "retext":
    # text -> parse -> text (idempotence)
    cal = ics.parse(ics.to_text(ics.read_file(arg(2)), arg(3)))
    print ics.to_text(cal, arg(3))
elif command == "days":
    cal = ics.read_file(arg(2))
    a = parse_value(arg(3))
    b = parse_value(arg(4))
    call print_days(cal["events"][Int(arg(5))], a[1], b[1])
elif command == "rule":
    start = parse_value(arg(2))
    finish = None
    if arg(4) != "-":
        finish = parse_value(arg(4))[1]
    end
    ev = ics.event_new("R", start[0] == "D", start[1], finish, None)
    if arg(3) != "-":
        call ics.set_rrule(ev, arg(3))
    end
    a = parse_value(arg(5))
    b = parse_value(arg(6))
    call print_days(ev, a[1], b[1])
elif command == "dur":
    try:
        print ics.parse_duration(arg(2))
    else:
        print "error"
    end
elif command == "dt":
    params = {}
    if arg_count() > 3:
        params["TZID"] = arg(3)
    end
    try:
        print fmt_kv(ics.parse_dt(arg(2), params))
    else:
        print "error"
    end
elif command == "fold":
    folded = ics.fold(arg(2))
    for part in folded.split("\r\n"):
        n = 0
        for ch in part:
            n += text.utf8_length(ch)
        end
        print "part", n
    end
    print "same", ics.unfold(folded) == [arg(2)]
elif command == "escape":
    s = "a,b;c\\d\ne"
    print ics.unescape(ics.escape(s)) == s, ics.escape(s)
elif command == "line":
    p = ics.parse_line(arg(2))
    if p == None:
        print "None"
    else:
        print p
    end
elif command == "grid":
    g = date.month_grid(Int(arg(2)), Int(arg(3)), Int(arg(4)), 6)
    for week in g:
        row = []
        for d in week:
            row.append(date.iso_date(d))
        end
        print text.join(row, " ")
    end
    print "weeks", date.weeks_needed(Int(arg(2)), Int(arg(3)), Int(arg(4)))
elif command == "months":
    print date.add_months(Int(arg(2)), Int(arg(3)), Int(arg(4)))
elif command == "leap":
    print date.is_leap(Int(arg(2))), date.days_in_month(Int(arg(2)), Int(arg(3)))
elif command == "allday":
    cal = ics.calendar_new()
    ev = ics.event_new("Dovolená – Šumava", True, date.ordinal(2026, 10, 26), date.ordinal(2026, 10, 31), "green")
    cal["events"].append(ev)
    body = ics.to_text(cal, "")
    print body
    ev2 = ics.parse(body)["events"][0]
    call print_event(ev2)
    call print_days(ev2, date.ordinal(2026, 10, 30), date.ordinal(2026, 10, 31))
    print "--"
    call print_days(ev2, date.ordinal(2026, 10, 31), date.ordinal(2026, 11, 1))
elif command == "timed":
    cal = ics.calendar_new()
    ev = ics.event_new("Schůzka", False, date.make(date.ordinal(2026, 10, 20), 14, 30, 0), date.make(date.ordinal(2026, 10, 20), 15, 15, 0), "purple")
    call ics.set_reminder(ev, 10)
    call ics.set_rrule(ev, "FREQ=MONTHLY;COUNT=3")
    cal["events"].append(ev)
    body = ics.to_text(cal, "Europe/Prague")
    print body
    ev2 = ics.parse(body)["events"][0]
    call print_event(ev2)
    call ics.set_reminder(ev2, None)
    print "alarms", len(ev2["alarms"])
elif command == "color":
    ev = ics.event_new("", True, 1, None, arg(2))
    if arg(3) != "-":
        ev["source"] = arg(3)
    end
    print ics.event_color(ev)
elif command == "merge":
    # Kalendar (st) ma soubor nacteny; jiny proces (LuxOS Companion = st2) prida udalost; Kalendar pak
    # sam pridava a maze - udalost z telefonu se neztrati, smazana se nevrati
    dir = arg(2)
    d = date.ordinal(2026, 10, 20)
    st = ics.store_new(dir)
    call ics.reload_if_changed(st)
    a = ics.event_new("A", False, date.make(d, 8, 0, 0), date.make(d, 9, 0, 0), None)
    call ics.add(st, a)
    st2 = ics.store_new(dir)
    call ics.reload_if_changed(st2)
    call ics.add(st2, ics.event_new("Z telefonu", False, date.make(d, 10, 0, 0), date.make(d, 11, 0, 0), None))
    call ics.add(st, ics.event_new("C", False, date.make(d, 12, 0, 0), date.make(d, 13, 0, 0), None))
    call ics.delete(st, ics.find(st, a["uid"], None))
    st3 = ics.store_new(dir)
    call ics.reload_if_changed(st3)
    names = []
    for item in ics.day_instances(st3, d):
        names.append(item[0]["summary"])
    end
    print text.join(names, ";")
elif command == "store":
    dir = arg(2)
    st = ics.store_new(dir)
    print "reload", ics.reload_if_changed(st), ics.reload_if_changed(st)
    ev = ics.event_new("Oběd", False, date.make(date.ordinal(2026, 10, 20), 12, 0, 0), date.make(date.ordinal(2026, 10, 20), 13, 0, 0), "orange")
    call ics.add(st, ev)
    print "exists", exists(dir + "/events.ics")
    items = ics.day_instances(st, date.ordinal(2026, 10, 20))
    names = []
    for item in items:
        names.append(item[0]["summary"])
    end
    print "day", text.join(names, ";")
    foreign = items[0][0]
    print "foreign", foreign["readonly"], foreign["source"]
    own = ics.find(st, ev["uid"], None)
    own["summary"] = "Oběd s týmem"
    call ics.update(st, own)
    st2 = ics.store_new(dir)
    call ics.reload_if_changed(st2)
    print "updated", ics.find(st2, ev["uid"], None)["summary"]
    busy = ics.busy_days(st2, date.ordinal(2026, 10, 1), date.ordinal(2026, 11, 1))
    days = []
    for d in sorted(busy.keys()):
        days.append(date.iso_date(d))
    end
    print "busy", text.join(days, " ")
    call ics.delete(st2, ics.find(st2, ev["uid"], None))
    st3 = ics.store_new(dir)
    call ics.reload_if_changed(st3)
    print "own", len(st3["own"]["events"])
    leftovers = []
    for name in glib.list_dir(dir):
        if name.find(".tmp-") >= 0:
            leftovers.append(name)
        end
    end
    print "tmp", len(leftovers)
elif command == "override":
    st = ics.store_new(arg(2))
    call ics.reload_if_changed(st)
    for item in ics.day_instances(st, date.ordinal(2026, 10, 20)):
        print item[0]["summary"], fmt(item[0], item[1])
    end
    print "next", len(ics.day_instances(st, date.ordinal(2026, 10, 21)))
elif command == "sorting":
    st = ics.store_new(arg(2))
    call ics.reload_if_changed(st)
    d = date.ordinal(2026, 10, 20)
    call ics.add(st, ics.event_new("B pozde", False, date.make(d, 18, 0, 0), date.make(d, 19, 0, 0), None))
    call ics.add(st, ics.event_new("A rano", False, date.make(d, 8, 0, 0), date.make(d, 9, 0, 0), None))
    call ics.add(st, ics.event_new("Celodenni", True, d, d + 1, None))
    names = []
    for item in ics.day_instances(st, d):
        names.append(item[0]["summary"])
    end
    print text.join(names, ";")
elif command == "overnight":
    ev = ics.event_new("Noc", False, date.make(date.ordinal(2026, 10, 20), 22, 0, 0), date.make(date.ordinal(2026, 10, 21), 2, 0, 0), None)
    print len(ics.occurrences(ev, date.ordinal(2026, 10, 21), date.ordinal(2026, 10, 22))), len(ics.occurrences(ev, date.ordinal(2026, 10, 22), date.ordinal(2026, 10, 23)))
elif command == "duration":
    cal = ics.read_file(arg(2))
    ev = cal["events"][0]
    print ics.duration(ev)
else:
    print "usage"
    call exit(2)
end
