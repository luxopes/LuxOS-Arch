# LuxOS - hodiny v horni liste (plugin genmon misto pluginu clock): stejny format, klik = Kalendar.
# Spousti se kazde 3 s, proto v LSL (1 ms, 1 MB) misto bashe (2 ms, 3 MB); cas formatuje strftime
# z libc podle jazyka uzivatele, bez dalsich procesu.
# Tucnost v markupu: genmon z vlastnosti font prebira jen rodinu a velikost.
# Tooltip s celym datem (prazdny by genmon nahradil technickym popisem pluginu).
load luxos_sys

now = luxos_sys.strftime_local("%a %-d. %b  %H:%M")
full = luxos_sys.strftime_local("%A %-d. %B %Y")
print "<txt><span weight=\"600\">" + now + "</span></txt><tool>" + full + "</tool><txtclick>luxos-calendar-toggle</txtclick>"
