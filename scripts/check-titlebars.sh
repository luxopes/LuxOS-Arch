#!/bin/bash
# LuxOS - kazda graficka aplikace LuxOS musi mit viditelnou horni listu (zavirani okna).
# Spousti aplikace ze zdroju ve virtualni obrazovce (nikdy na skutecne) a hlasi ty, jejichz
# HeaderBar zustal skryty (typicky okno zobrazene pres show() misto show_all()).
#   env -u DISPLAY xvfb-run -a scripts/check-titlebars.sh
set -u
cd "$(dirname "$(readlink -f "$0")")/.."
# Skutecnou obrazovku nikdy (ani s LUXOS_TEST_X): DISPLAY jiny nez Xvfb tohoto uzivatele nahradi vlastni Xvfb
. scripts/luxos-testguard.sh
if [[ -z ${DISPLAY-} ]]; then
    echo "Needs Xvfb (or run under xvfb-run) - never on a real display." >&2; exit 2
fi
tmp=$(mktemp -d); trap 'kill $sysbus_pid 2>/dev/null; rm -rf "$tmp"; _luxos_tg_cleanup' EXIT
# Soukroma prazdna "systemova" sbernice: Bluetooth, Telefon, Baterie a dalsi okna nesmi sahat na skutecny
# BlueZ (zapnuti viditelnosti, hledani zarizeni v okoli), UPower ani jine systemove sluzby pocitace
dbus-daemon --session --address="unix:path=$tmp/sysbus" --nofork --nopidfile >/dev/null 2>&1 & sysbus_pid=$!
for _ in $(seq 50); do [[ -S $tmp/sysbus ]] && break; sleep 0.1; done
[[ -S $tmp/sysbus ]] || { echo "private system bus did not start" >&2; exit 2; }
export DBUS_SYSTEM_BUS_ADDRESS=unix:path=$tmp/sysbus
export HOME=$tmp XDG_CONFIG_HOME=$tmp/config XDG_CACHE_HOME=$tmp/cache XDG_DATA_HOME=$tmp/data
# Vlastni XDG_RUNTIME_DIR: testy nesmi sdilet /run/user/UID skutecne relace (portaly, gvfs, klicenka,
# at-spi by se pripojily ke skutecnym sluzbam uzivatele)
mkdir -p "$tmp/run"; chmod 700 "$tmp/run"
export XDG_RUNTIME_DIR=$tmp/run GTK_USE_PORTAL=0 GIO_USE_VFS=local NO_AT_BRIDGE=1 GNOME_KEYRING_CONTROL= SSH_AUTH_SOCK=
export PYTHONPATH=$PWD/scripts/titlebar-check:$PWD/packages/luxos-guard/files:$PWD/packages/luxos-i18n/files:$PWD/packages/luxos-desktop/files/python:$PWD/packages/luxos-weather/files:$PWD/packages/luxos-maps/files:$PWD/packages/luxos-account/files
export LUXOS_I18N_DIR=$PWD/packages/luxos-i18n/files
# Pocasi a QR kod Wi-Fi bez skutecne site: nedostupne sluzby (port 9) a nmcli, ktery nic nevi
export LUXOS_WEATHER_API=http://127.0.0.1:9/v1/forecast LUXOS_WEATHER_GEO=http://127.0.0.1:9/v1/search \
    LUXOS_WEATHER_IP=http://127.0.0.1:9/ip LUXOS_WEATHER_ICONS=$PWD/packages/luxos-weather/files/icons LUXOS_NMCLI=false
export LUXOS_MAPS_TILES='http://127.0.0.1:9/{z}/{x}/{y}.png' LUXOS_MAPS_GEOCLUE=0
# Firemni sit bez skutecne domeny: zastupny lux-domain z testu (stav "nepripojeno"). luxos-domain je
# proprietarni - zdroje jen v soukromem repozitari (LUXOS_PRIVATE_DIR=cesta k luxos-private), jinak se preskoci.
priv=${LUXOS_PRIVATE_DIR:-/nonexistent}
export LUXOS_DOMAIN_CLI=$priv/packages/luxos-domain/tests/fake-gui/lux-domain FAKE_DOMAIN_DIR=$tmp
apps=(
    packages/luxos-account/files/luxos-account
    packages/luxos-desktop/files/bin/luxos-{display-settings,keyboard,shortcuts}
    packages/luxos-weather/files/luxos-weather
    packages/luxos-maps/files/luxos-maps
    packages/luxos-companion/files/luxos-companion
    packages/luxos-drivers/luxos-drivers
    packages/luxos-printing/files/luxos-{printers,scan}
    packages/luxos-safe/files/luxos-safe
    packages/luxos-guard/files/luxos-guard-gui
    packages/luxos-backup/files/luxos-backup-gui
    packages/luxos-sandbox/files/luxos-sandbox-gui
    packages/luxos-store/files/luxos-store      # potrebuje AppStream (na LuxOS je)
    packages/luxos-care/files/luxos-update
)
fail=0
for a in "${apps[@]}"; do
    [[ $a == "$priv"/* && ! -f $a ]] && { echo "skipped ${a#"$priv"/} (proprietary, set LUXOS_PRIVATE_DIR)"; continue; }
    [[ -f $a ]] || { echo "missing $a"; continue; }
    out=$(timeout 25 dbus-run-session -- python3 "$a" 2>&1 </dev/null | grep '^LUXOS-TITLEBAR' | tail -1)
    [[ -n $out ]] || out="LUXOS-TITLEBAR (did not start here - check manually)"
    printf '%-60s %s\n' "$a" "${out#LUXOS-TITLEBAR }"
    [[ $out == *FAIL* ]] && fail=1
done
# Aplikace prepsane z Pythonu do LSL (luxos-bluetooth, luxos-fingerprint, luxos-profile-picture, luxos-wifi-qr,
# luxos-calculator, luxos-monitor, luxos-feedback, luxos-router, luxos-camera): horni listu se zaviracim tlacitkem
# overuji jejich testy (packages/luxos-desktop/tests, "close_button" z luxos_testctl)
# Firemni sit (luxos-domain-settings) je od 1.0.0-3 nativni program v LSL: horni listu se zaviracim
# tlacitkem overuje jeho vlastni test GUI v soukromem repozitari (zastupny lux-domain, stejna Xvfb)
dt=$priv/packages/luxos-domain/tests/gui-settings.py
if [[ -f $dt ]]; then
    if out=$(LUXOS_PUBLIC_DIR=$PWD timeout 600 dbus-run-session -- python3 "$dt" 2>&1 </dev/null) \
        && grep -q '^ok *title bar visible with close button' <<<"$out"; then
        printf '%-60s %s\n' "luxos-domain-settings (LSL, private tests/gui-settings.py)" "ok"
    else
        printf '%-60s %s\n' "luxos-domain-settings (LSL, private tests/gui-settings.py)" "FAIL"
        grep -v '^ok' <<<"$out" | tail -20
        fail=1
    fi
else
    echo "skipped luxos-domain-settings (proprietary, set LUXOS_PRIVATE_DIR)"
fi
exit $fail
