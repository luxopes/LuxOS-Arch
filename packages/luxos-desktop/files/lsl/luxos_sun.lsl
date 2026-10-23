# LuxOS - vychod a zapad slunce bez internetu (poloha podle casoveho pasma); prepis luxos_sun.py.
# Souradnice bere z /usr/share/zoneinfo/zone1970.tab (stred mesta casoveho pasma), vypocet podle NOAA
# (presnost na par minut).
#   sun.mode()                       "light" | "dark" podle toho, jestli je ted den
#   sun.sun_times(day, lat, lon)     [vychod, zapad] jako unixovy cas, nebo None (polarni den/noc)
#   sun.location()                   [lat, lon] podle pasma, jinak Praha
load env, math
load luxos_glib, glib as glib
load luxos_date as date
load luxos_text as text

ZONE_TAB = "/usr/share/zoneinfo/zone1970.tab"
DEFAULT_LAT = 50.08
DEFAULT_LON = 14.42
PI = 3.141592653589793

function timezone_name():
    tz = env.get("TZ", "")
    if tz == None:
        tz = ""
    end
    while tz.startswith(":"):
        tz = tz[1:]
    end
    if tz != "" and tz.find("/") >= 0:
        return tz
    end
    link = glib.readlink("/etc/localtime")
    cut = link.find("zoneinfo/")
    if cut >= 0:
        return link[cut + 9:]
    end
    return ""
end

# +DDMM[SS] / +DDDMM[SS] -> stupne
function dms(value, deg_digits):
    sign = 1.0
    if value.startswith("-"):
        sign = -1.0
    end
    body = value[1:]
    deg = Float(Int(body[0:deg_digits]))
    minutes = Float(Int(body[deg_digits:deg_digits + 2]))
    seconds = 0.0
    rest = body[deg_digits + 2:deg_digits + 4]
    if rest != "":
        seconds = Float(Int(rest))
    end
    return sign * (deg + minutes / 60.0 + seconds / 3600.0)
end

function location():
    tzname = timezone_name()
    table = glib.read_text(env_or(ZONE_TAB))
    for line in table.split("\n"):
        if line.startswith("#"):
            continue
        end
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].strip() == tzname:
            coord = parts[1]
            split = max(text.rfind(coord, "+"), text.rfind(coord, "-"))
            if split <= 0:
                continue
            end
            return [dms(coord[0:split], 2), dms(coord[split:], 3)]
        end
    end
    return [DEFAULT_LAT, DEFAULT_LON]
end

function env_or(path):
    override = env.get("LUXOS_ZONE_TAB", "")
    if override == None or override == "":
        return path
    end
    return override
end

# arkus kosinus (modul math ho nema): asin Newtonovou metodou na sin(y) = x
function acos(x):
    y = 0.0
    i = 0
    while i < 40:
        step = (math.sin(y) - x) / math.cos(y)
        y = y - step
        if step < 0.0000000001 and step > -0.0000000001:
            break
        end
        i += 1
    end
    return PI / 2.0 - y
end

# [vychod, zapad] jako unixovy cas pro mistni den `day` (ordinal), nebo None pri polarnim dni/noci
function sun_times(day, lat, lon):
    ymd = date.from_ordinal(day)
    n = day - date.ordinal(ymd[0], 1, 1) + 1
    gamma = 2.0 * PI / 365.0 * Float(n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma) - 0.014615 * math.cos(2.0 * gamma) - 0.040849 * math.sin(2.0 * gamma))
    decl = 0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2.0 * gamma) + 0.000907 * math.sin(2.0 * gamma) - 0.002697 * math.cos(3.0 * gamma) + 0.00148 * math.sin(3.0 * gamma)
    zenith = math.radians(90.833)
    latr = math.radians(lat)
    cos_ha = math.cos(zenith) / (math.cos(latr) * math.cos(decl)) - math.tan(latr) * math.tan(decl)
    if cos_ha > 1.0 or cos_ha < -1.0:
        return None
    end
    ha = math.degrees(acos(cos_ha))
    midnight = glib.timegm(ymd[0], ymd[1], ymd[2], 0, 0, 0)
    rise = midnight + Int((720.0 - 4.0 * (lon + ha) - eqtime) * 60.0)
    sset = midnight + Int((720.0 - 4.0 * (lon - ha) - eqtime) * 60.0)
    return [rise, sset]
end

# "light" | "dark" pro unixovy cas `now` a polohu [lat, lon]
function mode_at(now, lat_lon):
    local = glib.localtime(now)
    day = date.ordinal(local[0], local[1], local[2])
    times = sun_times(day, lat_lon[0], lat_lon[1])
    if times == None:
        # polarni den v lete, polarni noc v zime (na severni polokouli)
        summer = local[1] > 3 and local[1] < 10
        if summer == (lat_lon[0] > 0.0):
            return "light"
        end
        return "dark"
    end
    if times[0] <= now and now < times[1]:
        return "light"
    end
    return "dark"
end

function mode():
    return mode_at(glib.now(), location())
end
