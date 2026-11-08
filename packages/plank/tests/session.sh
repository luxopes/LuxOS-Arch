#!/bin/bash
# LuxOS - izolovana testovaci relace pro Dock (Plank): Xvfb, soukromy XDG_RUNTIME_DIR/HOME/D-Bus,
# xfwm4 s kompozici. Nikdy nepouziva DISPLAY=:0 ani skutecnou relaci uzivatele.
#   session.sh PRACOVNI_ADRESAR PRIKAZ [ARG...]
# Prikaz bezi uvnitr relace (DISPLAY, DBUS_SESSION_BUS_ADDRESS, HOME jsou nastavene);
# framebuffer Xvfb je v PRACOVNI_ADRESAR/fb/Xvfb_screen0 (XWD).
set -u
W=$(readlink -f "${1:?pracovni adresar}"); shift
D=${LUXOS_TEST_DISPLAY:-:57}
mkdir -p "$W"
rm -rf "$W/run" "$W/fb" "$W/home"
mkdir -p "$W/run" "$W/fb" "$W/home"
chmod 700 "$W/run"
export XDG_RUNTIME_DIR=$W/run HOME=$W/home
# I XDG_CONFIG_HOME/XDG_CACHE_HOME/... musi byt soukrome: relace LuxOS je nastavuje na skutecny
# ~/.config - jinak by dconf/xfconfd z testu zapisovaly do nastaveni uzivatele (Dock, xfwm4).
export XDG_CONFIG_HOME=$HOME/.config XDG_CACHE_HOME=$HOME/.cache XDG_DATA_HOME=$HOME/.local/share \
    XDG_STATE_HOME=$HOME/.local/state
mkdir -p "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME"
unset DBUS_SESSION_BUS_ADDRESS WAYLAND_DISPLAY SESSION_MANAGER XDG_SESSION_PATH XDG_SEAT_PATH \
    XDG_SESSION_ID GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
Xvfb "$D" -screen 0 1280x800x24 -fbdir "$W/fb" -nolisten tcp +extension Composite >"$W/xvfb.log" 2>&1 &
xpid=$!
export DISPLAY=$D
for _ in $(seq 100); do
    xprop -root >/dev/null 2>&1 && break
    sleep 0.1
done
xprop -root >/dev/null 2>&1 || { echo "Xvfb $D nebezi" >&2; kill "$xpid"; exit 1; }
dbus-run-session -- bash -c '
    W=$1; shift
    # pojistka: zadny zapis mimo pracovni adresar
    case $XDG_CONFIG_HOME in "$W"/*) ;; *) echo "XDG_CONFIG_HOME mimo $W" >&2; exit 3;; esac
    xfconf-query -c xfwm4 -p /general/use_compositing -n -t bool -s true
    xfconf-query -c xfwm4 -p /general/vblank_mode -n -t string -s off
    xfwm4 --compositor=on >"$W/xfwm4.log" 2>&1 &
    wm=$!
    for _ in $(seq 50); do
        xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q window && break
        sleep 0.1
    done
    sleep 0.5
    "$@"
    rc=$?
    kill "$wm" 2>/dev/null
    exit $rc
' _ "$W" "$@"
rc=$?
kill "$xpid" 2>/dev/null
wait "$xpid" 2>/dev/null
exit $rc
