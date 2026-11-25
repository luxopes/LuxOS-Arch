#!/bin/bash
# LuxOS - testy luxos-wifi-quirk (Realtek RTL8723DE zaseknuty po restartu) nad falesnym /sys,
# s falesnym modprobe a notify-send (bez rootu, bez hardwaru)
#   bash packages/luxos-drivers/tests/test-wifi-quirk.sh
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
Q=$HERE/../luxos-wifi-quirk
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0 tests=0
ok() { tests=$((tests + 1)); if "$@"; then :; else fails=$((fails + 1)); echo "FAIL (line ${BASH_LINENO[0]}): $*"; fi; }

mkdir -p "$TMP/bin"
for c in modprobe notify-send sleep; do
    printf '#!/bin/sh\necho "%s $*" >>"$CALLS"\n' "$c" >"$TMP/bin/$c"
    chmod +x "$TMP/bin/$c"
done
export PATH=$TMP/bin:$PATH CALLS=$TMP/calls LUXOS_WIFI_QUIRK_WAIT=4 LANG=C LC_ALL=C

machine() {  # machine KARTA(ano/ne) OVLADAC_NACTENY(ano/ne) KARTA_S_OVLADACEM(ano/ne)
    export LUXOS_SYSFS=$TMP/sys
    rm -rf "$LUXOS_SYSFS" "$CALLS"; : >"$CALLS"
    local d=$LUXOS_SYSFS/bus/pci/devices
    mkdir -p "$d/0000:02:00.0" "$LUXOS_SYSFS/module"
    echo 0x10ec >"$d/0000:02:00.0/vendor"; echo 0x8168 >"$d/0000:02:00.0/device"   # ethernet Realtek
    if [[ $1 == ano ]]; then
        mkdir -p "$d/0000:03:00.0"
        echo 0x10ec >"$d/0000:03:00.0/vendor"; echo 0xd723 >"$d/0000:03:00.0/device"
        [[ $3 == ano ]] && ln -s ../../../drivers/rtw88_8723de "$d/0000:03:00.0/driver"
    fi
    [[ $2 == ano ]] && mkdir -p "$LUXOS_SYSFS/module/rtw88_8723de"
    return 0
}
calls() { cat "$CALLS"; }

# --- check ---
machine ano ano ne
ok test "$("$Q" check)" == "0000:03:00.0"
machine ano ano ano
ok bash -c '! "$0" check' "$Q"
machine ano ne ne                         # ovladac jeste nenacteny = nevime, nehlasit
ok bash -c '! "$0" check' "$Q"
machine ne ano ne
ok bash -c '! "$0" check' "$Q"

# --- shutdown: jen s timto cipem, nejdriv Bluetooth ---
machine ano ano ano
"$Q" shutdown
ok test "$(calls)" == $'modprobe -r btusb\nmodprobe -r rtw88_8723de\nsleep 2'
machine ne ne ne
"$Q" shutdown
ok test -z "$(calls)"

# --- notify ---
machine ano ano ne                        # zaseknuty: upozorneni
"$Q" notify
ok grep -q "^notify-send .*Wi-Fi adapter did not start.*hold the power button for 30 seconds" "$CALLS"
machine ano ano ano                       # funguje: hned konec, bez upozorneni
"$Q" notify
ok test -z "$(calls)"
machine ne ano ne                         # jiny pocitac: nic
"$Q" notify
ok test -z "$(calls)"
machine ano ne ne                         # ovladac se nenacetl vubec (jiny problem): nehlasit
"$Q" notify
ok bash -c '! grep -q notify-send "$0"' "$CALLS"

# --- cesky preklad ---
if [[ -r /usr/lib/luxos/i18n.sh ]]; then
    machine ano ano ne
    LUXOS_I18N_DIR=$HERE/../../luxos-i18n/files LANG=cs_CZ.UTF-8 LC_ALL=cs_CZ.UTF-8 LANGUAGE=cs "$Q" notify
    grep -q "Adaptér Wi-Fi se nespustil" "$CALLS" || echo "note: Czech not checked (i18n.sh reads installed translations)"
fi

ok test "$("$Q" bogus 2>&1; echo $?)" == $'usage: luxos-wifi-quirk shutdown|check|notify\n2'
echo "$((tests - fails))/$tests ok"
((fails == 0))
