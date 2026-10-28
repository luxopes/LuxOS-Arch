#!/bin/bash
# LuxOS - prechod po prihlaseni a probuzeni zamku bez cerne obrazovky (snimani obrazovky).
#
#   packages/luxos-desktop/tests/login-transition/run.sh [OPAKOVANI] [VARIANTY...]
#   LOCK_SAVER=/cesta/xfce4-screensaver ... run.sh      i setric -> dialog s heslem (jinak preskoceno)
#
# Kazde opakovani: skutecny luxos-greeter (demo) se prihlasi a skonci, pak luxos-session-cover --login
# (sestaveny z files/src) a xfwm4 s kompozitorem, xfdesktop, xfce4-panel a plank - vse na soukromem Xvfb,
# DBus a HOME (nikdy na skutecne obrazovce). Obrazovka se snima nepretrzite (MIT-SHM, stovky snimku/s);
# test selze, kdyz je od prvniho snimku greeteru jakykoli snimek cerny (>= 98 % cernych bodu) nebo
# z vetsi casti cerny (>= 25 %). Varianty: normal slow cm-late nocomp powersaver (vychozi vsechny).
# Vysledky (frames.log, events.log, cover.log, cerne snimky jako PPM) v $OUT (mktemp).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
RUNS=${1:-1}
shift || true
VARIANTS=("$@")
[[ ${#VARIANTS[@]} -gt 0 ]] || VARIANTS=(normal slow cm-late nocomp powersaver)
for t in Xvfb xfwm4 xfdesktop xfce4-panel plank xfsettingsd dbus-run-session gcc xdotool; do
    command -v "$t" >/dev/null || { echo "SKIP: $t missing"; exit 0; }
done
OUT=${OUT:-$(mktemp -d -p "${TMPDIR:-/tmp}" luxos-login-frames-XXXXXX)}
BIN=$OUT/bin
mkdir -p "$BIN"
gcc -O2 -Wall -Werror -o "$BIN/luxos-session-cover" "$HERE/../../files/src/luxos-session-cover.c" \
    -lX11 -lXfixes -lXcomposite -lXrandr -lcairo -lm || exit 1
gcc -O2 -Wall -o "$BIN/capture" "$HERE/capture.c" -lX11 -lXext || exit 1
export CAPTURE=$BIN/capture
fail=0
for i in $(seq "$RUNS"); do
    for v in "${VARIANTS[@]}"; do
        d=$OUT/$v-$i
        nice -n 10 "$HERE/session-sim.sh" "$d" "$BIN/luxos-session-cover" "$v" >/dev/null 2>&1
        res=$(python3 "$HERE/analyze.py" "$d" | tail -1)
        if python3 "$HERE/analyze.py" "$d" >/dev/null && grep -q "frames after greeter: [1-9]" <<<"$res"; then
            echo "ok    login $v #$i: $res"
        else
            echo "FAIL  login $v #$i: $res  ($d)"
            fail=1
        fi
    done
    if [[ -n ${LOCK_SAVER:-} ]]; then
        d=$OUT/lock-$i
        nice -n 10 "$HERE/lock-sim.sh" "$d" "$LOCK_SAVER" >/dev/null 2>&1
        res=$(python3 "$HERE/analyze.py" "$d" | tail -1)
        if python3 "$HERE/analyze.py" "$d" >/dev/null && grep -q "frames after greeter: [1-9]" <<<"$res"; then
            echo "ok    lock #$i: $res"
        else
            echo "FAIL  lock #$i: $res  ($d)"
            fail=1
        fi
    fi
done
echo "results: $OUT"
exit $fail
