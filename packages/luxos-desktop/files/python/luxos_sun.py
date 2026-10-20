"""LuxOS - vychod a zapad slunce bez internetu (poloha podle casoveho pasma).

Souradnice bere z /usr/share/zoneinfo/zone1970.tab (stred mesta casoveho pasma),
vypocet podle NOAA (presnost na par minut). Pouziti z prikazove radky:

  python3 luxos_sun.py mode     -> light | dark (podle toho, jestli je den)
  python3 luxos_sun.py times    -> HH:MM HH:MM (dnesni vychod a zapad)
"""
import datetime as dt
import math
import os
import sys

ZONE_TAB = "/usr/share/zoneinfo/zone1970.tab"
DEFAULT = (50.08, 14.42)    # Praha, kdyz pasmo nejde zjistit


def timezone_name():
    tz = os.environ.get("TZ", "").lstrip(":")
    if tz and "/" in tz:
        return tz
    try:
        link = os.readlink("/etc/localtime")
        return link.split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return ""


def _dms(text, deg_digits):
    """+DDMM[SS] / +DDDMM[SS] -> stupne."""
    sign = -1 if text[0] == "-" else 1
    body = text[1:]
    deg = int(body[:deg_digits])
    minutes = int(body[deg_digits:deg_digits + 2])
    seconds = int(body[deg_digits + 2:deg_digits + 4] or 0)
    return sign * (deg + minutes / 60 + seconds / 3600)


def location(tzname=None):
    tzname = tzname or timezone_name()
    try:
        with open(ZONE_TAB) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 3 and parts[2].strip() == tzname:
                    coord = parts[1]
                    split = max(coord.rfind("+"), coord.rfind("-"))
                    lat, lon = coord[:split], coord[split:]
                    return _dms(lat, 2), _dms(lon, 3)
    except OSError:
        pass
    return DEFAULT


def sun_times(day, lat, lon):
    """(vychod, zapad) jako mistni datetime, nebo None pri polarnim dni/noci."""
    n = day.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    zenith = math.radians(90.833)
    latr = math.radians(lat)
    cos_ha = math.cos(zenith) / (math.cos(latr) * math.cos(decl)) - math.tan(latr) * math.tan(decl)
    if cos_ha > 1 or cos_ha < -1:
        return None                     # slunce cely den pod / nad obzorem
    ha = math.degrees(math.acos(cos_ha))
    midnight = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    rise = midnight + dt.timedelta(minutes=720 - 4 * (lon + ha) - eqtime)
    sset = midnight + dt.timedelta(minutes=720 - 4 * (lon - ha) - eqtime)
    return rise.astimezone(), sset.astimezone()


def mode(now=None, lat_lon=None):
    now = now or dt.datetime.now().astimezone()
    lat, lon = lat_lon or location()
    times = sun_times(now.date(), lat, lon)
    if times is None:
        # polarni den v lete, polarni noc v zime (na severni polokouli)
        summer = 3 < now.month < 10
        return "light" if (summer == (lat > 0)) else "dark"
    rise, sset = times
    return "light" if rise <= now < sset else "dark"


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "mode"
    if cmd == "mode":
        print(mode())
    elif cmd == "times":
        lat, lon = location()
        t = sun_times(dt.date.today(), lat, lon)
        print("-" if t is None else f"{t[0]:%H:%M} {t[1]:%H:%M}")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
