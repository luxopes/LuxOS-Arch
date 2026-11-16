#!/bin/bash
# Textovy instalator: rozlozeni klavesnice v souhrnu nazvem v jazyce pruvodce, ne kodem
# (regrese audit 1.0.2: "Klávesnice: cz, us").
#   bash packages/luxos-installer/tests/test-xkb-text.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$HERE/../files/luxos-install
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
{
    sed -n '/^KEYMAPS=(/,/^)/p' "$SRC"
    sed -n '/^xkb_text() {/,/^}/p' "$SRC"
} >"$T/f.sh"
fail=0
check() {  # check JAZYK LAYOUT VARIANT OCEKAVANO
    local got
    got=$(LANG=$1 LUXOS_I18N_DIR=$HERE/../../luxos-i18n/files bash -c '
        . "$1"; . "$2"; XKB_LAYOUT=$3 XKB_VARIANT=$4; xkb_text' _ "$HERE/../../luxos-i18n/files/i18n.sh" "$T/f.sh" "$2" "$3")
    if [[ $got == "$4" ]]; then echo "ok    $1 $2/$3 -> $got"; else echo "FAIL  $1 $2/$3: '$got' != '$4'"; fail=1; fi
}
check cs_CZ.UTF-8 "cz,us" "," "Čeština, Angličtina (USA)"
check cs_CZ.UTF-8 "cz" "qwerty" "Čeština (QWERTY)"
check en_US.UTF-8 "us,cz" ",qwerty" "English (US), Czech (QWERTY)"
check cs_CZ.UTF-8 "fi" "" "fi"
check en_US.UTF-8 "de,ch" ",fr" "German, ch (fr)"
exit $fail
