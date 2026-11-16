#!/bin/bash
# Souhrn textoveho instalatoru: sloupce zarovnane podle znaku, ne bajtu (regrese audit 1.0.2:
# cesky "Časové pásmoEurope/Prague", "Režim spouštěníBIOS"), jazyk nazvem misto kodu locale.
#   bash packages/luxos-installer/tests/test-summary-table.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$HERE/../files/luxos-install
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
{
    sed -n '/^LANGS=(/,/^)/p' "$SRC"
    sed -n '/^kv_table() {/,/^}/p' "$SRC"
    sed -n '/^lang_text() {/,/^}/p' "$SRC"
} >"$T/f.sh"
fail=0
expect() { if "${@:2}"; then echo "ok    $1"; else echo "FAIL  $1"; fail=1; fi; }
out=$(LC_ALL=C bash -c '. "$1"; kv_table "Jazyk" "Čeština" "Časové pásmo" "Europe/Prague" "Režim spouštění" "BIOS" "LuxAI" "nepřihlášeno"' _ "$T/f.sh")
echo "$out"
# hodnoty zacinaji ve stejnem sloupci (pocitano ve znacich), mezi popiskem a hodnotou aspon 2 mezery
cols=$(while IFS= read -r l; do
    v=${l##*  }; p=${l%"$v"}
    LC_ALL=C.UTF-8 bash -c 'printf "%s\n" "${#1}"' _ "$p"
done <<<"$out" | sort -u)
expect "jeden sloupec hodnot" test "$(wc -l <<<"$cols")" -eq 1
expect "sloupec = nejdelsi popisek + 2" test "$cols" -eq 17
expect "Časové pásmo oddelene od hodnoty" grep -q 'Časové pásmo  *Europe/Prague' <<<"$out"
lt() { LOCALE=$1 bash -c 'T() { printf "%s" "$1"; }; . "$1"; lang_text' _ "$T/f.sh"; }
expect "jazyk nazvem" test "$(lt cs_CZ.UTF-8)" = "Čeština"
expect "anglictina" test "$(lt en_US.UTF-8)" = "English (US)"
expect "nezname locale kodem" test "$(lt fi_FI.UTF-8)" = "fi_FI.UTF-8"
exit $fail
