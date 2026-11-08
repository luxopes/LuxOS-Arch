#!/bin/bash
# LuxOS - testy Docku (Plank) v izolovanych relacich Xvfb (nikdy ne DISPLAY=:0, vlastni HOME,
# XDG_*, D-Bus, xfwm4 s kompozici).
#   run-all.sh PLANK [PRACOVNI_ADRESAR] [CYKLY]
#   PLANK = cesta k Planku (sestaveny balik rozbaleny do out/ - viz run-plank.sh nize, nebo /usr/bin/plank)
# Sestaveni a spusteni bez instalace:
#   scripts/perf/build-pkg.sh out/plank-build packages/plank
#   mkdir -p out/plank-root && tar --zstd -xf out/plank-build/plank-*-x86_64.pkg.tar.zst -C out/plank-root usr
#   printf '#!/bin/sh\nr=$(dirname "$(readlink -f "$0")")\nLD_LIBRARY_PATH=$r/usr/lib exec "$r/usr/bin/plank" "$@"\n' \
#       > out/plank-root/run-plank.sh && chmod +x out/plank-root/run-plank.sh
#   packages/plank/tests/run-all.sh "$PWD/out/plank-root/run-plank.sh"
set -u
here=$(dirname "$(readlink -f "$0")")
plank=$(readlink -f "${1:?cesta k Planku}")
w=$(readlink -m "${2:-$here/../../../out/plank-tests}")
cycles=${3:-300}
mkdir -p "$w"
fails=0
run() {   # nazev display prikaz...
    local name=$1 d=$2; shift 2
    if LUXOS_TEST_DISPLAY=$d timeout 900 nice -n 10 "$here/session.sh" "$w/$name" "$@" >"$w/$name.out" 2>&1; then
        echo "OK    $name: $(grep -aE '^(OK|stall|\{)' "$w/$name.out" | tail -1)"
    else
        echo "FAIL  $name: $(grep -aE '^(FAIL|stall|\{)' "$w/$name.out" | tail -1)"
        fails=$((fails + 1))
    fi
}
run logger-utf8 :61 "$here/logger_utf8.sh" "$w/logger-utf8" "$plank"
run watchdog :61 python3 "$here/dock_watchdog.py" "$w/watchdog" "$plank"
run watchdog-off :61 python3 "$here/dock_watchdog.py" "$w/watchdog-off" "$plank" --no-watchdog
run stress :61 python3 "$here/dock_stress.py" "$w/stress" --cycles "$cycles" --plank "$plank"
run stress-churn :61 python3 "$here/dock_stress.py" "$w/stress-churn" --cycles "$cycles" --churn --tooltips --plank "$plank"
echo "selhalo: $fails"
exit $((fails > 0))
