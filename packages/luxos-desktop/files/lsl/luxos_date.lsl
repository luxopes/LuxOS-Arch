# LuxOS - datumova matematika pro Kalendar (nahrada modulu datetime z Pythonu).
# Datum je poradove cislo dne (ordinal, 1 = 1. 1. 0001 jako v Pythonu), cas bez pasma ("naivni mistni")
# je pocet sekund = ordinal * 86400 + sekundy dne. Prevody na unixovy cas delaji funkce libc
# (luxos_glib.localtime/mktime), takze letni cas a pasma resi system.
load env
load luxos_glib as glib

DAY = 86400
DAYS_BEFORE = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]

function is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
end

function days_in_month(year, month):
    if month == 2:
        if is_leap(year):
            return 29
        end
        return 28
    end
    return [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
end

# [rok, mesic] posunuty o delta mesicu
function add_months(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return [index // 12, index % 12 + 1]
end

function ordinal(year, month, day):
    y = year - 1
    n = y * 365 + y // 4 - y // 100 + y // 400 + DAYS_BEFORE[month - 1] + day
    if month > 2 and is_leap(year):
        n += 1
    end
    return n
end

# [rok, mesic, den] (algoritmus z CPythonu)
function from_ordinal(value):
    n = value - 1
    n400 = n // 146097
    n = n % 146097
    year = n400 * 400 + 1
    n100 = n // 36524
    n = n % 36524
    n4 = n // 1461
    n = n % 1461
    n1 = n // 365
    n = n % 365
    year += n100 * 100 + n4 * 4 + n1
    if n1 == 4 or n100 == 4:
        return [year - 1, 12, 31]
    end
    leap = n1 == 3 and (n4 != 24 or n100 == 3)
    month = (n + 50) >> 5
    before = DAYS_BEFORE[month - 1]
    if month > 2 and leap:
        before += 1
    end
    if before > n:
        month -= 1
        before = DAYS_BEFORE[month - 1]
        if month > 2 and leap:
            before += 1
        end
    end
    return [year, month, n - before + 1]
end

function year_of(day):
    return from_ordinal(day)[0]
end

function month_of(day):
    return from_ordinal(day)[1]
end

function day_of(day):
    return from_ordinal(day)[2]
end

# 0 = pondeli ... 6 = nedele
function weekday(day):
    return (day + 6) % 7
end

# Mrizka mesice: seznam tydnu (7 dnu), tyden zacina first_weekday (0 = pondeli), vzdy rows radku
function month_grid(year, month, first_weekday, rows):
    first = ordinal(year, month, 1)
    offset = (weekday(first) - first_weekday) % 7
    start = first - offset
    out = []
    r = 0
    while r < rows:
        week = []
        c = 0
        while c < 7:
            week.append(start + r * 7 + c)
            c += 1
        end
        out.append(week)
        r += 1
    end
    return out
end

# Pocet tydnu, do kterych mesic zasahuje (4 az 6)
function weeks_needed(year, month, first_weekday):
    first = ordinal(year, month, 1)
    offset = (weekday(first) - first_weekday) % 7
    return (offset + days_in_month(year, month) + 6) // 7
end

# ---- cas (naivni mistni) ------------------------------------------------------------------------

function make(day, hour, minute, second):
    return day * DAY + hour * 3600 + minute * 60 + second
end

function date_of(moment):
    return moment // DAY
end

function hour_of(moment):
    return (moment % DAY) // 3600
end

function minute_of(moment):
    return (moment % DAY) % 3600 // 60
end

function second_of(moment):
    return moment % 60
end

# Naivni mistni cas z unixoveho casu
function local_from_unix(t):
    f = glib.localtime(t)
    return make(ordinal(f[0], f[1], f[2]), f[3], f[4], f[5])
end

# Unixovy cas z naivniho mistniho casu
function unix_from_local(moment):
    ymd = from_ordinal(date_of(moment))
    return glib.mktime(ymd[0], ymd[1], ymd[2], hour_of(moment), minute_of(moment), second_of(moment))
end

# Naivni cas v jinem pasmu (nazev z /usr/share/zoneinfo) -> naivni mistni cas; nezname pasmo = beze zmeny
function local_from_zone(moment, zone):
    if zone == "" or not exists("/usr/share/zoneinfo/" + zone):
        return moment
    end
    ymd = from_ordinal(date_of(moment))
    call glib.set_tz(zone)
    t = glib.mktime(ymd[0], ymd[1], ymd[2], hour_of(moment), minute_of(moment), second_of(moment))
    call glib.unset_tz()
    return local_from_unix(t)
end

# Naivni cas v UTC -> naivni mistni cas
function local_from_utc(moment):
    ymd = from_ordinal(date_of(moment))
    t = glib.timegm(ymd[0], ymd[1], ymd[2], hour_of(moment), minute_of(moment), second_of(moment))
    return local_from_unix(t)
end

function now():
    return local_from_unix(glib.now())
end

function today():
    return date_of(now())
end

function pad2(n):
    if n < 10:
        return "0" + String(n)
    end
    return String(n)
end

function pad4(n):
    text = String(n)
    while len(text) < 4:
        text = "0" + text
    end
    return text
end

# YYYYMMDD
function format_date(day):
    ymd = from_ordinal(day)
    return pad4(ymd[0]) + pad2(ymd[1]) + pad2(ymd[2])
end

# YYYYMMDDTHHMMSS
function format_moment(moment):
    return format_date(date_of(moment)) + "T" + pad2(hour_of(moment)) + pad2(minute_of(moment)) + pad2(second_of(moment))
end

# ISO datum YYYY-MM-DD
function iso_date(day):
    ymd = from_ordinal(day)
    return pad4(ymd[0]) + "-" + pad2(ymd[1]) + "-" + pad2(ymd[2])
end

# Nazev mistniho pasma (Europe/Prague) z TZ nebo /etc/localtime, jinak ""
function local_tz_name():
    tz = env.get("TZ", "")
    if tz == None:
        tz = ""
    end
    while tz.startswith(":"):
        tz = tz[1:]
    end
    if tz != "" and tz.find("/") >= 0 and not tz.startswith("/"):
        return tz
    end
    target = glib.realpath("/etc/localtime")
    cut = target.find("/zoneinfo/")
    if cut >= 0:
        return target[cut + 10:]
    end
    return ""
end
