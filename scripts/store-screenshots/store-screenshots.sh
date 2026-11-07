#!/bin/bash
# LuxOS - snimky aplikaci LuxOS pro Obchod (detail aplikace), znovu pri kazdem vydani
#
#   scripts/store-screenshots/store-screenshots.sh              vsechny aplikace (svetly vzhled)
#   scripts/store-screenshots/store-screenshots.sh luxos-maps luxos-weather
#   scripts/store-screenshots/store-screenshots.sh --dark ...   navic tmavy vzhled (<n>-dark.webp)
#   scripts/store-screenshots/store-screenshots.sh --list       seznam aplikaci se snimky
#
# Kazda aplikace se spusti ze zdroju v pracovni kopii pod virtualni obrazovkou xvfb 1280x800
# (nikdy na skutecne obrazovce), s xfwm4 a vzhledem LuxOS (WhiteSur + luxos.css, ikony, pismo
# Inter), v docasnem HOME a vlastnim D-Bus (shoot.py se po pripraveni HOME spusti znovu pod
# dbus-run-session, aby ani xfconfd nesahal na skutecne ~/.config). Data jsou ukazkova (mistni falesne servery a soubory),
# nikdy skutecne ucty, posta ani soubory uzivatele; zadna sit ke tretim stranam.
# Postup pro kazdou aplikaci je v apps/<desktop-id>.py, spolecne nastroje v shoot.py.
# Vysledek: packages/luxos-store/screens/<desktop-id>/<n>.webp (max. 1280 px, do 150 KB)
# a manifest.json (rozmery); scripts/publish-repo.sh je zverejni vedle apps.json jako app-screens/.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
for t in xvfb-run dbus-run-session xdotool xfwm4 python3; do
    command -v "$t" >/dev/null || { echo "Missing $t" >&2; exit 1; }
done
export LUXOS_SHOTS_XVFB=1
exec env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XDG_RUNTIME_DIR \
    nice -n 10 xvfb-run -a -s "-screen 0 1280x800x24 -nolisten tcp" python3 "$here/shoot.py" "$@"
