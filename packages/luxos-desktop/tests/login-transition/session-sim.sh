#!/bin/bash
# Napodobene prihlaseni pres LightDM na soukromem Xvfb s nepretrzitym snimanim obrazovky:
# skutecny luxos-greeter (demo) -> luxos-session-cover --login -> xfwm4 (kompozitor) + xfdesktop +
# xfce4-panel + plank. Nikdy na skutecne obrazovce: vlastni Xvfb, DBus, XDG_RUNTIME_DIR a HOME.
#   session-sim.sh OUTDIR COVER_BIN [varianta]
#   varianta: normal | slow (plocha a lista o 3 s pozdeji) | cm-late (kompozitor se zapne az 1,5 s po
#             startu plochy) | nocomp (bez kompozitoru) | powersaver (Sporic baterie: bez animace)
#             | nocover (bez prechodu - pro srovnani)
# Promenne: SECS (delka snimani, 12), EVERY (ulozit kazdy N-ty snimek jako PPM, 0), WALL (tapeta).
set -u
OUT=$1 COVER=$2 VARIANT=${3:-normal}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../../.." && pwd)
WALL=${WALL:-/usr/share/backgrounds/luxos/luxos-flow-light.jpg}
SECS=${SECS:-12}
rm -rf "$OUT"
mkdir -p "$OUT"
T=$(mktemp -d -p "${TMPDIR:-/tmp}" lsim-XXXXXX)
X=$T/home/.config/xfce4/xfconf/xfce-perchannel-xml
mkdir -p "$X" "$T/run" "$T/frames" "$T/cache"
chmod 700 "$T/run"
cat >"$X/xfce4-desktop.xml" <<EOF
<?xml version="1.1" encoding="UTF-8"?>
<channel name="xfce4-desktop" version="1.0">
  <property name="backdrop" type="empty"><property name="screen0" type="empty">
    <property name="monitorscreen" type="empty"><property name="workspace0" type="empty">
      <property name="last-image" type="string" value="$WALL"/><property name="image-style" type="int" value="5"/>
    </property></property>
  </property></property>
  <property name="desktop-icons" type="empty"><property name="style" type="int" value="0"/></property>
</channel>
EOF
if [[ $VARIANT == cm-late || $VARIANT == nocomp ]]; then
    cat >"$X/xfwm4.xml" <<EOF
<?xml version="1.1" encoding="UTF-8"?>
<channel name="xfwm4" version="1.0"><property name="general" type="empty">
<property name="use_compositing" type="bool" value="false"/></property></channel>
EOF
fi
if [[ $VARIANT == powersaver ]]; then
    mkdir -p "$T/home/.config/luxos"
    : >"$T/home/.config/luxos/powersaver"
fi
for d in $(seq 90 120); do [[ -e /tmp/.X11-unix/X$d || -e /tmp/.X$d-lock ]] || break; done
export DISPLAY=:$d
# -background none jako LightDM (Xvfb ho neumi - jako ovladace bez glamor: koren po greeteru cerny)
Xvfb ":$d" -screen 0 1280x800x24 -background none -nolisten tcp -noreset >"$T/xvfb.log" 2>&1 &
XPID=$!
for _ in $(seq 50); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done
export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config" XDG_CACHE_HOME="$T/cache" XDG_RUNTIME_DIR="$T/run" \
    XDG_DATA_HOME="$T/home/.local/share" XDG_CONFIG_DIRS=/etc/xdg/luxos:/etc/xdg LANG=en_US.UTF-8 \
    LUXOS_LOGIN_FRAME_DIR="$T/frames" NO_AT_BRIDGE=1 GTK_A11Y=none \
    DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent/system_bus_socket
unset DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER XDG_SESSION_ID
dbus-run-session -- bash -c '
    HERE=$1 O=$2 REPO=$3 WALL=$4 VARIANT=$5 SECS=$6 COVER=$7
    ev() { echo "$(date +%s.%N) $*" >>"$O/events.log"; }
    pids=()
    "${CAPTURE:-$HERE/capture}" "$O" "$SECS" "${EVERY:-0}" >"$O/capture.txt" & cap=$!
    LUXOS_GREETER_DEMO_HOLD=1 python3 -I "$HERE/greeter_phase.py" "$REPO/packages/luxos-greeter/files/luxos-greeter" \
        "$WALL" "$LUXOS_LOGIN_FRAME_DIR" >"$O/greeter.log" 2>&1
    ev greeter-exited
    sleep 0.15     # Xsession: skripty xinitrc.d
    if [[ $VARIANT != nocover ]]; then
        ev cover
        LUXOS_COVER_DEBUG=1 "$COVER" --login >"$O/cover.log" 2>&1 & pids+=($!)
    fi
    sleep 0.25     # start xfce4-session
    ev xfwm4
    xfsettingsd --no-daemon >/dev/null 2>&1 & pids+=($!)
    xfwm4 >/dev/null 2>&1 & pids+=($!)
    sleep 0.3
    [[ $VARIANT == slow ]] && sleep 3
    ev panel-desktop-plank
    xfce4-panel >/dev/null 2>&1 & pids+=($!)
    xfdesktop >/dev/null 2>&1 & pids+=($!)
    plank >/dev/null 2>&1 & pids+=($!)
    if [[ $VARIANT == cm-late ]]; then
        sleep 1.5
        ev compositing-on
        xfconf-query -c xfwm4 -p /general/use_compositing -n -t bool -s true
    fi
    wait $cap
    kill "${pids[@]}" 2>/dev/null
    sleep 0.3
    kill -9 "${pids[@]}" 2>/dev/null
' sim "$HERE" "$OUT" "$REPO" "$WALL" "$VARIANT" "$SECS" "$COVER"
kill $XPID 2>/dev/null
wait $XPID 2>/dev/null
cp "$T/xvfb.log" "$OUT/" 2>/dev/null
rm -rf "$T"
