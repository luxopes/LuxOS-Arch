#!/bin/bash
# Zdrzuje prechod po prihlaseni start relace? Skutecny xfce4-session (jako /etc/lightdm/Xsession) na
# soukromem Xvfb s luxos-session-cover --login a bez nej; meri cas do spravce oken
# (_NET_SUPPORTING_WM_CHECK) a do plochy (okno DESKTOP v _NET_CLIENT_LIST).
#   session-start.sh COVER_BIN [cover|nocover|held] [OUTDIR]
#   held = navic okno se snimkem greeteru drzene serverem (FrameHold, jako po skutecnem greeteru)
# Bez systemove sbernice, vlastni HOME/XDG_*/DBus: autostart LuxOS (/etc/xdg/luxos, luxos-session) se
# nespousti, programy z /etc/xdg/autostart bezi bez systemove sbernice - nic se nedotkne skutecne relace.
set -u
COVER=$1 MODE=${2:-cover} OUT=${3:-}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../../.." && pwd)
T=$(mktemp -d -p "${TMPDIR:-/tmp}" lstart-XXXXXX)
mkdir -p "$T/home/.config" "$T/run" "$T/cache" "$T/frames" "$T/xdg/xfce4/xfconf/xfce-perchannel-xml"
chmod 700 "$T/run"
cp /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/*.xml "$T/xdg/xfce4/xfconf/xfce-perchannel-xml/" 2>/dev/null
cp /etc/xdg/luxos/xfce4/xfconf/xfce-perchannel-xml/*.xml "$T/xdg/xfce4/xfconf/xfce-perchannel-xml/" 2>/dev/null
for d in $(seq 70 79); do [[ -e /tmp/.X11-unix/X$d || -e /tmp/.X$d-lock ]] || break; done
export DISPLAY=:$d
Xvfb ":$d" -screen 0 1280x800x24 -nolisten tcp -noreset >"$T/xvfb.log" 2>&1 &
XPID=$!
for _ in $(seq 50); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done
export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config" XDG_CACHE_HOME="$T/cache" XDG_RUNTIME_DIR="$T/run" \
    XDG_DATA_HOME="$T/home/.local/share" XDG_CONFIG_DIRS="$T/xdg" LANG=en_US.UTF-8 NO_AT_BRIDGE=1 \
    DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent/system_bus_socket DESKTOP_SESSION=luxos \
    LUXOS_LOGIN_FRAME_DIR="$T/frames"
unset DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER XDG_SESSION_ID
if [[ $MODE == held ]]; then
    python3 -c 'import sys
from importlib.machinery import SourceFileLoader
g = SourceFileLoader("luxos_greeter", sys.argv[1]).load_module()
sys.exit(0 if g.FrameHold().hold(1280, 800) else 1)' "$REPO/packages/luxos-greeter/files/luxos-greeter" 2>/dev/null
fi
dbus-run-session -- bash -c '
    COVER=$1 MODE=$2 T=$3
    now() { date +%s%N; }
    t0=$(now)
    [[ $MODE != nocover ]] && { LUXOS_COVER_DEBUG=1 "$COVER" --login 2>"$T/cover.log" & }
    xfce4-session >"$T/session.log" 2>&1 & sp=$!
    wm="" desk=""
    for _ in $(seq 600); do
        if [[ -z $wm ]] && xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q "window id"; then
            wm=$(( ($(now) - t0) / 1000000 ))
        fi
        if [[ -n $wm && -z $desk ]] && xprop -root _NET_CLIENT_LIST 2>/dev/null | grep -q "window id"; then
            for w in $(xprop -root _NET_CLIENT_LIST | grep -o "0x[0-9a-f]*"); do
                xprop -id "$w" _NET_WM_WINDOW_TYPE 2>/dev/null | grep -q DESKTOP && desk=$(( ($(now) - t0) / 1000000 ))
            done
        fi
        [[ -n $wm && -n $desk ]] && break
        sleep 0.05
    done
    echo "mode=$MODE wm_ms=${wm:-none} desktop_ms=${desk:-none}"
    sleep 1
    kill $sp 2>/dev/null
    sleep 0.5
    for p in $(jobs -p); do kill "$p" 2>/dev/null; done
' sim "$COVER" "$MODE" "$T"
kill $XPID 2>/dev/null
wait $XPID 2>/dev/null
[[ -n $OUT ]] && { mkdir -p "$OUT"; cp "$T"/*.log "$T"/home/.xfce4-session.verbose-log* "$OUT/" 2>/dev/null; }
rm -rf "$T"
