#!/bin/bash
# LuxOS - snimky cele plochy pro web luxos.lux-ai.cz (uvodni notebook, galerie), znovu pri kazdem vydani
#
#   scripts/site-screenshots/site-screenshots.sh                 vse: svetly + tmavy vzhled, anglicky + cesky
#   scripts/site-screenshots/site-screenshots.sh desktop store   jen vybrane sceny
#   scripts/site-screenshots/site-screenshots.sh --light --lang en ...   jen svetly vzhled / jen anglicky
#   scripts/site-screenshots/site-screenshots.sh --list          seznam scen
#
# Plocha LuxOS se sestavi pod virtualni obrazovkou xvfb 1920x1080 (nikdy na skutecne obrazovce):
# xfwm4 s tematem WhiteSur, tapeta LuxOS (flow-light / flow-dark), horni lista xfce4-panel s nastavenim
# z luxos-desktop (xdg) a Dock Plank s polozkami ze skel. Aplikace jsou ze zdroju v pracovni kopii
# (postupy scripts/store-screenshots/apps/ se pouziji znovu) nebo nainstalovane programy LuxOS.
# Vse v docasnem HOME pod out/site-screenshots, se soukromym XDG_RUNTIME_DIR (0700), vlastnimi
# XDG_CONFIG_HOME/DATA/CACHE/STATE a vlastnim D-Bus; ukazkova data (Alex Morgan, example.com),
# zadna sit ke tretim stranam. Vysledek: site/assets/shots/ (WebP 1920/960/640 px).
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
for t in xvfb-run dbus-run-session xdotool xfwm4 xfce4-panel plank rofi python3; do
    command -v "$t" >/dev/null || { echo "Missing $t" >&2; exit 1; }
done
export LUXOS_SITE_SHOTS_XVFB=1
# skutecne sezeni uzivatele exportuje XDG_* (napr. XDG_CONFIG_HOME=~/.config): vse zrusit, shoot_site.py
# nastavi vlastni hodnoty a pred spustenim cokoli overi, ze zadna cesta nevede do skutecneho HOME
exec env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XDG_RUNTIME_DIR -u XAUTHORITY \
    -u XDG_CONFIG_HOME -u XDG_DATA_HOME -u XDG_CACHE_HOME -u XDG_STATE_HOME -u XDG_CONFIG_DIRS \
    -u XDG_DATA_DIRS -u XDG_SESSION_ID -u XDG_SEAT -u XDG_VTNR -u SESSION_MANAGER -u SSH_AUTH_SOCK \
    -u GNOME_KEYRING_CONTROL -u GTK_MODULES \
    nice -n 10 xvfb-run -a -s "-screen 0 1920x1080x24 -nolisten tcp" python3 "$here/shoot_site.py" "$@"
