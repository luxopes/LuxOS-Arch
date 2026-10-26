#!/bin/bash
# LuxOS - kazda graficka aplikace LuxOS musi mit viditelnou horni listu (zavirani okna).
# Spousti aplikace ze zdroju ve virtualni obrazovce (nikdy na skutecne) a hlasi ty, jejichz
# HeaderBar zustal skryty (typicky okno zobrazene pres show() misto show_all()).
#   env -u DISPLAY xvfb-run -a scripts/check-titlebars.sh
set -u
cd "$(dirname "$(readlink -f "$0")")/.."
if [[ ${XAUTHORITY-} != *xvfb-run* && ${LUXOS_TEST_X-} != 1 ]]; then
    echo "Run under xvfb-run - never on a real display." >&2; exit 2
fi
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
export HOME=$tmp XDG_CONFIG_HOME=$tmp/config XDG_CACHE_HOME=$tmp/cache XDG_DATA_HOME=$tmp/data
export PYTHONPATH=$PWD/scripts/titlebar-check:$PWD/packages/luxos-guard/files:$PWD/packages/luxos-i18n/files:$PWD/packages/luxos-desktop/files/python:$PWD/packages/luxos-account/files
# Co je noveho: novinky ze zdroju, verze "nejnovejsi"
export LUXOS_WHATS_NEW_DIR=$PWD/packages/luxos-branding/files/whats-new LUXOS_VERSION_FILE=$PWD/packages/luxos-branding/files/version
export LUXOS_I18N_DIR=$PWD/packages/luxos-i18n/files
apps=(
    packages/luxos-account/files/luxos-account
    packages/luxos-desktop/files/bin/luxos-{bluetooth,calculator,camera,display-settings,feedback,fingerprint,keyboard,lock-settings,monitor,power,router,settings,shortcuts,tour,whats-new}
    packages/luxos-drivers/luxos-drivers
    packages/luxos-printing/files/luxos-{printers,scan}
    packages/luxos-safe/files/luxos-safe
    packages/luxos-guard/files/luxos-guard-gui
    packages/luxos-sandbox/files/luxos-sandbox-gui
    packages/luxos-store/files/luxos-store      # potrebuje AppStream (na LuxOS je)
    packages/luxos-care/files/luxos-update
)
fail=0
for a in "${apps[@]}"; do
    [[ -f $a ]] || { echo "missing $a"; continue; }
    out=$(timeout 25 dbus-run-session -- python3 "$a" 2>&1 </dev/null | grep '^LUXOS-TITLEBAR' | tail -1)
    [[ -n $out ]] || out="LUXOS-TITLEBAR (did not start here - check manually)"
    printf '%-60s %s\n' "$a" "${out#LUXOS-TITLEBAR }"
    [[ $out == *FAIL* ]] && fail=1
done
exit $fail
