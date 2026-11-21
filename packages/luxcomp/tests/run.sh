#!/bin/bash
# Testy libluxcomp v kontejneru (nikdy na skutecne obrazovce): headless pixman 1920x1080
# (scenario.sh: umisteni, lista, cela obrazovka, prejezd ploch, PSS) a vnoreny backend x11
# v soukromem Xvfb (nested.sh, input.sh: klik, presun, semafor, Alt+Tab, Ctrl+sipky, psani), material
# (blur.sh + blur_check.py: rozmazani ano/ne, jednolita barva, cas snimku pri pohybu okna pod plochou).
# Vystup (snimky grim, logy, pss.txt): ${LUXCOMP_TEST_OUT:-out/luxcomp-test} v koreni repozitare.
# Docasne misto harness WP-1 (scripts/wl-test), az bude hotovy, presunout tam.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
out=${LUXCOMP_TEST_OUT:-$root/out/luxcomp-test}
mkdir -p "$out"
env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY podman build -q -t luxcomp-test "$here" >/dev/null
env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \
  timeout 900 podman run --rm --userns=keep-id --user "$(id -u):$(id -g)" --pids-limit 300 \
  -v "$here/..:/src:z,ro" -v "$out:/w:z" -e HOME=/w/home luxcomp-test bash -c '
    set -e; mkdir -p $HOME
    [ -d /w/build ] || meson setup /w/build /src >/dev/null
    ninja -C /w/build >/dev/null
    rm -rf /w/shots /w/shots-nested /w/shots-input
    LUXCOMP_STATS=1 /src/tests/session.sh /src/tests/scenario.sh
    /src/tests/nested-session.sh /src/tests/nested.sh
    OUT=/w/shots-input /src/tests/nested-session.sh /src/tests/input.sh
    echo /usr/bin/grim >/w/privileged.conf
    rm -rf /w/shots-blur; LUXWM_PRIVILEGED=/w/privileged.conf OUT=/w/shots-blur LUXCOMP_STATS=1 \
      /src/tests/session.sh /src/tests/blur.sh
    python3 /src/tests/blur_check.py /w/shots-blur; grep -h "luxcomp: blur" /w/shots-blur/demo.log
    grep -h "luxcomp:" /w/shots/demo.log; cat /w/shots/pss.txt'
echo "screenshots and logs: $out/shots $out/shots-nested $out/shots-input"
