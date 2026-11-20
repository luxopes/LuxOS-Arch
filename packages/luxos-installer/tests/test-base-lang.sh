#!/bin/bash
# LuxOS installer - Thunderbird v zakladni sade a jeho jazykovy balicek podle jazyka systemu
# (base_lang_resolve, install_base_lang, install_templates) BEZ roota, disku a site: jadro baliku
# (chroot_engine) je napodoba, ktera vypisuje dostupne/nainstalovane baliky a zapisuje instalace.
#
#   packages/luxos-installer/tests/test-base-lang.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
FILES=$HERE/../files
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
NPASS=0 NFAIL=0
ok()  { NPASS=$((NPASS + 1)); printf 'ok    %s\n' "$1"; }
bad() { NFAIL=$((NFAIL + 1)); printf 'FAIL  %s\n' "$1"; [[ -n ${2-} ]] && printf '      %s\n' "$2"; return 0; }

extract() { sed -n "/^$1() {/,/^}/p" "$FILES/luxos-install"; }
eval "$(sed -n '/^BASE_LANG_PACKS=/p' "$FILES/luxos-install")"
for fn in lang_candidates base_lang_resolve install_base_lang install_templates; do
    eval "$(extract "$fn")"
done
# shellcheck disable=SC2059
T() { local f=$1; shift; printf -- "$f" "$@"; }
info() { echo "INFO $*" >>"$OUT/info"; }
step() { echo "STEP $*" >>"$OUT/steps"; }
progress() { :; }
pac_cleanup() { :; }
pac_filter() { cat; }
sleep() { :; }
LOG=$OUT/log

# Seznam baliku jako v repozitari Arch (extra.db 2026-11, vyber)
AVAIL="thunderbird
thunderbird-i18n-cs
thunderbird-i18n-de
thunderbird-i18n-en-gb
thunderbird-i18n-en-us
thunderbird-i18n-es-es
thunderbird-i18n-fr
thunderbird-i18n-hu
thunderbird-i18n-it
thunderbird-i18n-nl
thunderbird-i18n-pl
thunderbird-i18n-pt-br
thunderbird-i18n-pt-pt
thunderbird-i18n-sk
thunderbird-i18n-sv-se
thunderbird-i18n-uk"
INSTALLED="base
luxos-desktop
thunderbird"
SYNC_FAIL=0
chroot_engine() {
    case $1 in
        -Syy) ((SYNC_FAIL)) && return 1; return 0 ;;
        -Slq) printf '%s\n' "$AVAIL" ;;
        -Qq) printf '%s\n' "$INSTALLED" ;;
        *) echo "$*" >>"$OUT/engine" ;;
    esac
}

# --- zakladni sada obsahuje Thunderbird ---
if grep -qx thunderbird "$FILES/packages"; then
    ok "base package list contains thunderbird"
else
    bad "thunderbird missing in files/packages"
fi
if ! grep -v '^[[:space:]]*#' "$FILES/packages" | grep -q '%lang'; then
    ok "base package list has no %lang% placeholder (pacstrap would fail on it)"
else
    bad "%lang% in files/packages"
fi

# --- jazyk systemu -> balicek ---
resolve() {  # resolve LOCALE -> vystup base_lang_resolve
    local LOCALE=$1 avail=$AVAIL installed=${2-$INSTALLED}
    base_lang_resolve | paste -sd' '
}
declare -A WANT=(
    [cs_CZ.UTF-8]=thunderbird-i18n-cs [sk_SK.UTF-8]=thunderbird-i18n-sk [pl_PL.UTF-8]=thunderbird-i18n-pl
    [uk_UA.UTF-8]=thunderbird-i18n-uk [hu_HU.UTF-8]=thunderbird-i18n-hu [de_DE.UTF-8]=thunderbird-i18n-de
    [de_AT.UTF-8]=thunderbird-i18n-de [fr_FR.UTF-8]=thunderbird-i18n-fr [es_ES.UTF-8]=thunderbird-i18n-es-es
    [it_IT.UTF-8]=thunderbird-i18n-it [pt_BR.UTF-8]=thunderbird-i18n-pt-br [pt_PT.UTF-8]=thunderbird-i18n-pt-pt
    [nl_NL.UTF-8]=thunderbird-i18n-nl [sv_SE.UTF-8]=thunderbird-i18n-sv-se [en_GB.UTF-8]=thunderbird-i18n-en-gb
    [en_US.UTF-8]="" [C.UTF-8]="" [es_MX.UTF-8]="" [sr_RS@latin.UTF-8]=""
)
for loc in "${!WANT[@]}"; do
    got=$(resolve "$loc")
    if [[ $got == "${WANT[$loc]}" ]]; then
        ok "$loc -> ${WANT[$loc]:-(none)}"
    else
        bad "$loc" "expected '${WANT[$loc]}', got '$got'"
    fi
done
got=$(resolve cs_CZ.UTF-8 "base
luxos-desktop")
if [[ -z $got ]]; then ok "no language pack when Thunderbird is not installed"; else bad "pack without app" "$got"; fi

# --- bez sablon: jazykovy balicek se doinstaluje bez noveho kroku ---
TEMPLATE_IDS=()
LOCALE=cs_CZ.UTF-8
rm -f "$OUT/engine" "$OUT/steps" "$OUT/info"
install_templates
if [[ $(cat "$OUT/engine" 2>/dev/null) == "-Su --needed --noconfirm thunderbird-i18n-cs" ]]; then
    ok "no templates: thunderbird-i18n-cs installed"
else
    bad "no templates: engine calls" "$(cat "$OUT/engine" 2>/dev/null)"
fi
if [[ ! -e $OUT/steps ]]; then ok "no templates: no extra progress step"; else bad "extra step" "$(cat "$OUT/steps")"; fi

# --- bez site: nic, zadna chyba ---
SYNC_FAIL=1
rm -f "$OUT/engine"
install_templates; rc=$?
if ((rc == 0)) && [[ ! -e $OUT/engine ]]; then ok "offline: language pack skipped quietly"; else bad "offline" "rc=$rc $(cat "$OUT/engine" 2>/dev/null)"; fi
SYNC_FAIL=0

# --- anglictina: nic ---
LOCALE=en_US.UTF-8
rm -f "$OUT/engine"
install_templates
if [[ ! -e $OUT/engine ]]; then ok "en_US: nothing installed"; else bad "en_US installs" "$(cat "$OUT/engine")"; fi

# --- se sablonou: balicek v jedne transakci se sablonou ---
TEMPLATE_DIR=$OUT/templates
mkdir -p "$TEMPLATE_DIR"
printf '@name Test\nthunderbird\nthunderbird-i18n-%%lang%%\nvlc-missing\n' >"$TEMPLATE_DIR/t.list"
AVAIL+=$'\n'"vlc"
eval "$(extract tpl_resolve)"
eval "$(extract tpl_field)"
templates_text() { echo Test; }
TEMPLATE_IDS=(t) TEMPLATES=t USERNAME=u TARGET=$OUT/target LUX_CONFIG_TOOL=false
LOCALE=de_DE.UTF-8
rm -f "$OUT/engine"
install_templates
if [[ $(head -1 "$OUT/engine") == "-Su --needed --noconfirm thunderbird thunderbird-i18n-de" ]]; then
    ok "template + base pack deduplicated in one transaction"
else
    bad "template transaction" "$(cat "$OUT/engine")"
fi

printf '\n%d passed, %d failed\n' "$NPASS" "$NFAIL"
((NFAIL == 0))
