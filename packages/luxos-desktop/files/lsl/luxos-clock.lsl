# LuxOS - hodiny v horni liste (plugin genmon misto pluginu clock): stejny format jako luxos-bar, klik = Kalendar.
# Spousti se kazde 3 s, proto v LSL (1 ms, 1 MB) misto bashe (2 ms, 3 MB); cas z libc, datum podle jazyka
# plochy (luxos_i18n.format_date: driv pevny cesky tvar "%a %-d. %b" s nazvy z libc i v ostatnich jazycich).
# Tucnost v markupu: genmon z vlastnosti font prebira jen rodinu a velikost.
# Tooltip s celym datem (prazdny by genmon nahradil technickym popisem pluginu).
load luxos_sys
load luxos_i18n as i18n

parts = luxos_sys.strftime_local("%Y %-m %-d %u").split(" ")
year = Int(parts[0])
month = Int(parts[1])
day = Int(parts[2])
weekday = Int(parts[3]) - 1
now = i18n.weekday_short(weekday) + " " + i18n.format_date(year, month, day, weekday, "short") + "  " + luxos_sys.strftime_local("%H:%M")
full = i18n.format_date(year, month, day, weekday, "year")
print "<txt><span weight=\"600\">" + now + "</span></txt><tool>" + full + "</tool><txtclick>luxos-calendar-toggle</txtclick>"
