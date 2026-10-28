#!/bin/bash
# Setric -> zamykaci dialog na soukromem Xvfb + xfwm4 (kompozitor) s nepretrzitym snimanim obrazovky.
#   lock-sim.sh OUTDIR [SAVER_BIN] [TEMA]   (SAVER_BIN = /usr/bin/xfce4-screensaver)
# Bez systemove sbernice (logind): nic se nedostane do skutecne relace. Klavesa Shift probudi zamek,
# heslo se nezadava. Promenne: EVERY (ulozit kazdy N-ty snimek), WALL.
set -u
# SAVER_ENGINE=program: setric z repozitare misto nainstalovaneho /usr/lib/xfce4-screensaver/luxos
# (xfce4-screensaver spousti jen programy ze svych slozek) - v soukromem jmennem prostoru (unshare,
# bez roota) se tam jen pro tento test pripoji; system se nemeni
if [[ -n ${SAVER_ENGINE:-} && -z ${LOCK_SIM_NS:-} ]]; then
    # vnoreny jmenny prostor zase s vlastnim UID (jako root by dialog s heslem zamek hned odemkl)
    exec env LOCK_SIM_NS=1 LOCK_SIM_UID="$(id -u)" LOCK_SIM_GID="$(id -g)" unshare -Urm bash -c \
        'mount --bind "$SAVER_ENGINE" /usr/lib/xfce4-screensaver/luxos &&
         exec unshare -U --map-user="$LOCK_SIM_UID" --map-group="$LOCK_SIM_GID" "$0" "$@"' "$0" "$@"
fi
OUT=$1 SAVER=${2:-/usr/bin/xfce4-screensaver} THEME=${3:-screensavers-luxos-wallpaper}
HERE=$(cd "$(dirname "$0")" && pwd)
WALL=${WALL:-/usr/share/backgrounds/luxos/luxos-flow-light.jpg}
rm -rf "$OUT"
mkdir -p "$OUT"
T=$(mktemp -d -p "${TMPDIR:-/tmp}" lksim-XXXXXX)
X=$T/home/.config/xfce4/xfconf/xfce-perchannel-xml
mkdir -p "$X" "$T/run" "$T/cache"
chmod 700 "$T/run"
cat >"$X/xfce4-desktop.xml" <<EOF
<?xml version="1.1" encoding="UTF-8"?>
<channel name="xfce4-desktop" version="1.0">
  <property name="backdrop" type="empty"><property name="screen0" type="empty">
    <property name="monitorscreen" type="empty"><property name="workspace0" type="empty">
      <property name="last-image" type="string" value="$WALL"/><property name="image-style" type="int" value="5"/>
    </property></property>
  </property></property>
</channel>
EOF
cat >"$X/xfce4-screensaver.xml" <<EOF
<?xml version="1.1" encoding="UTF-8"?>
<channel name="xfce4-screensaver" version="1.0">
  <property name="saver" type="empty">
    <property name="enabled" type="bool" value="true"/>
    <property name="mode" type="int" value="2"/>
    <property name="fade" type="bool" value="false"/>
    <property name="themes" type="empty"><property name="list" type="array"><value type="string" value="$THEME"/></property></property>
    <property name="idle-activation" type="empty"><property name="enabled" type="bool" value="false"/></property>
  </property>
  <property name="lock" type="empty">
    <property name="enabled" type="bool" value="true"/>
    <property name="saver-activation" type="empty"><property name="enabled" type="bool" value="true"/><property name="delay" type="int" value="0"/></property>
  </property>
</channel>
EOF
for d in $(seq 80 89); do [[ -e /tmp/.X11-unix/X$d || -e /tmp/.X$d-lock ]] || break; done
export DISPLAY=:$d
Xvfb ":$d" -screen 0 1280x800x24 -nolisten tcp -noreset >"$T/xvfb.log" 2>&1 &
XPID=$!
for _ in $(seq 50); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done
export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config" XDG_CACHE_HOME="$T/cache" XDG_RUNTIME_DIR="$T/run" \
    XDG_DATA_HOME="$T/home/.local/share" XDG_CONFIG_DIRS=/etc/xdg/luxos:/etc/xdg LANG=en_US.UTF-8 \
    NO_AT_BRIDGE=1 GTK_A11Y=none DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent/system_bus_socket
unset DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER XDG_SESSION_ID
dbus-run-session -- bash -c '
    HERE=$1 O=$2 SAVER=$3
    ev() { echo "$(date +%s.%N) $*" >>"$O/events.log"; }
    pids=()
    xfsettingsd --no-daemon >/dev/null 2>&1 & pids+=($!)
    xfwm4 >/dev/null 2>&1 & pids+=($!)
    sleep 0.5
    xfdesktop >/dev/null 2>&1 & pids+=($!)
    sleep 1.5
    "$SAVER" --debug >"$O/saver.log" 2>&1 & pids+=($!)
    sleep 1.5
    ev lock
    xfce4-screensaver-command --lock >/dev/null 2>&1
    sleep 3
    if [[ -n ${DIFFCAP:-} ]]; then
        # porovnani s poslednim snimkem setrice pred probuzenim (1,3 s), bez ctverce DIFFBOX (hodiny)
        "$DIFFCAP" "$O" "${CAPSECS:-7}" 1300 $DIFFBOX >"$O/capture.txt" & cap=$!
    else
        "${CAPTURE:-$HERE/capture}" "$O" "${CAPSECS:-6}" "${EVERY:-0}" >"$O/capture.txt" & cap=$!
    fi
    sleep 1.5
    ev wake
    xdotool key shift
    if [[ -n ${ESC:-} ]]; then
        sleep 2.5          # dialog s heslem je na obrazovce
        ev escape
        xdotool key Escape # zpet ke setrici
    fi
    wait $cap
    kill "${pids[@]}" 2>/dev/null
    sleep 0.3
    kill -9 "${pids[@]}" 2>/dev/null
' sim "$HERE" "$OUT" "$SAVER"
kill $XPID 2>/dev/null
wait $XPID 2>/dev/null
rm -rf "$T"
