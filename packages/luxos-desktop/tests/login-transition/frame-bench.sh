#!/bin/bash
# LuxOS - trha se bar prubehu pri prihlaseni? luxos-session-cover --login pri startu relace pod zatezi.
#
#   packages/luxos-desktop/tests/login-transition/frame-bench.sh [OPAKOVANI] [COVER_BIN]
#
# Soukromy Xvfb 1920x1080, DBus, XDG_RUNTIME_DIR a HOME (nikdy skutecna obrazovka). Kazde opakovani:
# zakryti (LUXOS_COVER_FRAMELOG = cas kazdeho snimku, LUXOS_COVER_BENCH = vypln stale v pohybu), jako
# xfce4-session xfsettingsd + xfwm4 (kompozitor), o 2 s pozdeji xfce4-panel, xfdesktop a plank - a po celou
# dobu jedna smycka na kazdem jadru (nice 0, jako procesy relace) a vytizeny X klient (xbusy.c). Vypise
# p50/p99/max intervalu snimku; selze pri mezere nad 50 ms (drive kontrola plochy ve stejne smycce jako
# kresleni: mezery 70-130 ms, viditelne trhani). Pousti se bez nice - meri se bezna priorita.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
RUNS=${1:-3}
for t in Xvfb xfwm4 xfdesktop xfce4-panel plank xfsettingsd dbus-run-session gcc xprop; do
    command -v "$t" >/dev/null || { echo "SKIP: $t missing"; exit 0; }
done
OUT=${OUT:-$(mktemp -d -p "${TMPDIR:-/tmp}" luxos-frame-bench-XXXXXX)}
BIN=${2:-$OUT/luxos-session-cover}
if [[ -z ${2:-} ]]; then
    gcc -O2 -Wall -Werror -o "$BIN" "$HERE/../../files/src/luxos-session-cover.c" \
        -lX11 -lXfixes -lXcomposite -lXrandr -lXrender -lcairo -lm -pthread || exit 1
fi
gcc -O2 -Wall -o "$OUT/xbusy" "$HERE/xbusy.c" -lX11 || exit 1
fail=0
for i in $(seq "$RUNS"); do
    d=$OUT/run-$i
    T=$d/t
    X=$T/home/.config/xfce4/xfconf/xfce-perchannel-xml
    mkdir -p "$X" "$T/run" "$T/frames" "$T/cache"
    chmod 700 "$T/run"
    for n in $(seq 90 120); do [[ -e /tmp/.X11-unix/X$n || -e /tmp/.X$n-lock ]] || break; done
    (
        export DISPLAY=:$n
        Xvfb ":$n" -screen 0 1920x1080x24 -nolisten tcp -noreset >"$d/xvfb.log" 2>&1 &
        XPID=$!
        for _ in $(seq 50); do xprop -root >/dev/null 2>&1 && break; sleep 0.1; done
        export HOME=$T/home XDG_CONFIG_HOME=$T/home/.config XDG_CACHE_HOME=$T/cache XDG_RUNTIME_DIR=$T/run \
            XDG_DATA_HOME=$T/home/.local/share XDG_CONFIG_DIRS=/etc/xdg/luxos:/etc/xdg LANG=en_US.UTF-8 \
            LUXOS_LOGIN_FRAME_DIR=$T/frames NO_AT_BRIDGE=1 GTK_A11Y=none \
            DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent/system_bus_socket
        unset DBUS_SESSION_BUS_ADDRESS SESSION_MANAGER XDG_SESSION_ID
        dbus-run-session -- bash -c '
            d=$1 BIN=$2 XB=$3
            load=()
            for _ in $(seq "$(nproc)"); do bash -c "while :; do :; done" & load+=($!); done
            "$XB" & load+=($!)
            sleep 0.5
            LUXOS_COVER_FRAMELOG=$d/frames.log LUXOS_COVER_BENCH=1 LUXOS_COVER_DEBUG=1 "$BIN" --login 2>"$d/cover.log" &
            cover=$!
            sleep 0.25
            s=()
            xfsettingsd --no-daemon >/dev/null 2>&1 & s+=($!)
            xfwm4 >/dev/null 2>&1 & s+=($!)
            sleep 2.3
            xfce4-panel >/dev/null 2>&1 & s+=($!)
            xfdesktop >/dev/null 2>&1 & s+=($!)
            plank >/dev/null 2>&1 & s+=($!)
            wait $cover
            kill "${load[@]}" "${s[@]}" 2>/dev/null
            sleep 0.3
            kill -9 "${s[@]}" 2>/dev/null
        ' bench "$d" "$BIN" "$OUT/xbusy" >/dev/null 2>&1
        kill $XPID 2>/dev/null
        wait $XPID 2>/dev/null
    )
    rm -rf "$T"
    res=$(python3 - "$d/frames.log" <<'EOF'
import sys
ts = [int(v) for v in open(sys.argv[1]).read().split()]
ts = [t for t in ts if t >= ts[0] + 300000][:-20]      # bez prolnuti na zacatku a rozplynuti na konci
iv = sorted((b - a) / 1000 for a, b in zip(ts, ts[1:]))
p = lambda q: iv[min(len(iv) - 1, int(q * len(iv)))]
print(f"{len(ts)} frames p50={p(.5):.1f} p99={p(.99):.1f} max={iv[-1]:.1f} ms gaps>33ms={sum(x > 33.4 for x in iv)}")
sys.exit(1 if iv[-1] > 50 or len(iv) < 60 else 0)
EOF
)
    if [[ $? == 0 ]]; then
        echo "ok    frames #$i: $res"
    else
        echo "FAIL  frames #$i: $res  ($d)"
        fail=1
    fi
done
echo "results: $OUT"
exit $fail
