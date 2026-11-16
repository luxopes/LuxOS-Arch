#!/bin/bash
# LuxOS - zatezovy test Docku v izolovane relaci Xvfb (viz session.sh, dock_stress.py)
#   run-stress.sh PRACOVNI_ADRESAR DISPLAY [argumenty dock_stress.py...]
#   napr. run-stress.sh out/dock-stress :57 --cycles 2000 --churn --plank /cesta/k/plank
# Vysledek: PRACOVNI_ADRESAR/result.json, vystup PRACOVNI_ADRESAR.out
set -u
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos-testguard.sh)
_tg=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
while [[ -n $_tg && ! -f $_tg/scripts/luxos-testguard.sh ]]; do _tg=${_tg%/*}; done
if [[ -n $_tg ]]; then . "$_tg/scripts/luxos-testguard.sh"; else unset DISPLAY; fi
unset _tg
here=$(dirname "$(readlink -f "$0")")
w=$(readlink -m "${1:?pracovni adresar}"); d=${2:?display}; shift 2
[[ $d == :0 ]] && { echo "DISPLAY :0 je skutecna relace - nepouzivat" >&2; exit 2; }
mkdir -p "$w"
LUXOS_TEST_DISPLAY=$d exec nice -n 10 "$here/session.sh" "$w" python3 "$here/dock_stress.py" "$w" "$@" >"$w.out" 2>&1
