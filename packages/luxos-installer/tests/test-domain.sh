#!/usr/bin/env bash
# LuxOS installer - firemni sit (DOMAIN=, luxos-domain) bez roota a bez site:
# kontrola konfigurace, pripojeni v chrootu (napodoba arch-chroot + lux-domain) a heslo jen na stdin.
#
#   bash packages/luxos-installer/tests/test-domain.sh
#
# Funkce se vezmou primo z luxos-install (sekce "Firemni sit"); arch-chroot je funkce, ktera zapise
# argumenty a stdin a vypise radky jako lux-domain --progress. Heslo nesmi byt v argumentech ani v zaznamu.
set -uo pipefail
unset DISPLAY WAYLAND_DISPLAY
HERE=$(cd "$(dirname "$0")" && pwd)
FILES=$HERE/../files
TMP=$(mktemp -d "${TMPDIR:-/tmp}/luxos-domain-inst.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
FAILS=0
SECRET='Tajne heslo $(id) `x` "q"'

check() {  # check POPIS PRIKAZ...
    if "${@:2}"; then echo "ok    $1"; else echo "FAIL  $1"; FAILS=$((FAILS + 1)); fi
}
eq() {  # eq POPIS OCEKAVANO SKUTECNE
    if [[ $2 == "$3" ]]; then echo "ok    $1"; else echo "FAIL  $1: ocekavano '$2', je '$3'"; FAILS=$((FAILS + 1)); fi
}
no_secret() {  # no_secret SOUBOR - heslo v souboru neni
    ! grep -qF "Tajne heslo" "$1"
}

# ---- napodoba prostredi luxos-install ----
T() { local f=$1; shift; printf -- "$f" "$@"; }
title() { :; }
info() { printf '%s\n' "$*" >>"$TMP/info"; }
fail() { printf 'FAIL: %s\n' "$*"; exit 3; }
PROGRESS=1
progress() { printf '@@%s\n' "$*" >>"$TMP/progress"; }
LOG=$TMP/install.log
TARGET=$TMP/target
mkdir -p "$TARGET"

# arch-chroot: argumenty (bez hesla) a stdin do souboru, vystup podle $TMP/mode
arch-chroot() {
    printf '%s\n' "$@" >"$TMP/argv"
    cat >"$TMP/stdin"
    case $(cat "$TMP/mode" 2>/dev/null) in
        ok)
            echo "@@STEP 1 4 Finding the domain"
            echo "some log line"
            echo "@@STEP 4 4 Setting up sign-in"
            echo "@@DONE" ;;
        password)
            echo "@@STEP 1 4 Finding the domain"
            echo "@@ERROR password Wrong administrator name or password."
            return 1 ;;
        missing)
            echo "chroot: failed to run command 'lux-domain': No such file or directory"
            return 127 ;;
    esac
}

eval "$(sed -n '/^# --- Firemni sit: pripojeni k domene/,/^# --- OEM: priprava pro jineho cloveka/p' "$FILES/luxos-install")"
declare -F domain_config domain_join domain_text ask_domain valid_domain >/dev/null || { echo "FAIL  funkce firemni site"; exit 1; }

reset() { DOMAIN="" DOMAIN_USER="" DOMAIN_PASSWORD="" OU="" DOMAIN_OU="" DOMAIN_ADMINS="" DOMAIN_NOTICE=""; : >"$LOG"; : >"$TMP/progress"; : >"$TMP/info"; }

echo "## kontrola konfigurace"
reset
domain_config
eq "bez DOMAIN: nic" "||" "$DOMAIN|$DOMAIN_USER|$OU"
reset; DOMAIN_USER=admin DOMAIN_PASSWORD=x OU=y
domain_config
eq "bez DOMAIN: ostatni klice se zahodi" "||" "$DOMAIN_USER|$DOMAIN_PASSWORD|$OU"
reset; DOMAIN=Firma.LOCAL DOMAIN_USER=admin DOMAIN_PASSWORD=x DOMAIN_OU="OU=PC,DC=firma,DC=local"
domain_config
eq "DOMAIN malymi pismeny" firma.local "$DOMAIN"
eq "DOMAIN_OU = alias OU" "OU=PC,DC=firma,DC=local" "$OU"
for bad in "firma" "-firma.local" "fir ma.local" "firma..local" "firma.local/x"; do
    out=$( (reset; DOMAIN=$bad DOMAIN_USER=a DOMAIN_PASSWORD=b; domain_config) 2>&1 )
    check "neplatna domena '$bad' -> chyba" grep -q "Invalid DOMAIN" <<<"$out"
done
out=$( (reset; DOMAIN=firma.local DOMAIN_PASSWORD=b; domain_config) 2>&1 )
check "DOMAIN bez DOMAIN_USER -> chyba" grep -q "needs DOMAIN_USER" <<<"$out"
out=$( (reset; DOMAIN=firma.local DOMAIN_USER=a; domain_config) 2>&1 )
check "DOMAIN bez DOMAIN_PASSWORD -> chyba" grep -q "needs DOMAIN_PASSWORD" <<<"$out"
out=$( (reset; DOMAIN=firma.local DOMAIN_USER=a DOMAIN_PASSWORD=b OU=$'x\ny'; domain_config) 2>&1 )
check "novy radek v OU -> chyba" grep -q "Invalid DOMAIN_USER" <<<"$out"
reset; DOMAIN=firma.local DOMAIN_USER=jan
eq "souhrn" "domain firma.local (administrator jan)" "$(domain_text)"

echo "## pripojeni v chrootu"
reset; echo ok >"$TMP/mode"
DOMAIN=firma.local DOMAIN_USER=admin DOMAIN_PASSWORD=$SECRET OU="OU=PC,DC=firma,DC=local" DOMAIN_ADMINS="Domain Admins,IT"
out=$(set -Eeuo pipefail; trap 'echo TRAP' ERR; domain_join; echo "rc=$? pw=[${DOMAIN_PASSWORD}] notice=[$DOMAIN_NOTICE]")
check "uspech: bez chyby a bez ERR" grep -qx "rc=0 pw=\[\] notice=\[\]" <<<"$out"
mapfile -t argv <"$TMP/argv"
eq "chroot do cile" "$TARGET" "${argv[0]}"
eq "argumenty podle smlouvy" "lux-domain join firma.local -U admin --ou OU=PC,DC=firma,DC=local --admins Domain Admins,IT --password-stdin --yes --no-snapshot --offline-install --progress" "${argv[*]:1}"
check "heslo neni v argumentech" no_secret "$TMP/argv"
eq "heslo na stdin (prvni radek)" "$SECRET" "$(head -1 "$TMP/stdin")"
check "heslo neni v zaznamu" no_secret "$LOG"
check "heslo neni v prubehu" no_secret "$TMP/progress"
check "heslo neni v hlaskach" no_secret "$TMP/info"
check "zaznam: prikaz bez hesla" grep -q "^+ arch-chroot .* lux-domain join firma.local" "$LOG"
check "zaznam: vystup lux-domain" grep -qx "some log line" "$LOG"
check "prubeh: kroky lux-domain jako @@STATUS" grep -qx "@@STATUS Setting up sign-in" "$TMP/progress"
check "prubeh: zadne cizi @@STEP (pocitadlo kroku instalatoru)" bash -c "! grep -q '^@@STEP' '$TMP/progress'"
check "uspech: hlaska" grep -q "joined the domain firma.local" "$TMP/info"

reset; echo password >"$TMP/mode"
DOMAIN=firma.local DOMAIN_USER=admin DOMAIN_PASSWORD=$SECRET
domain_join_rc() { set -Eeuo pipefail; trap 'echo TRAP' ERR; domain_join; echo "rc=$?"; }
out=$(domain_join_rc)
check "spatne heslo: instalace pokracuje (rc 0, bez ERR)" grep -qx "rc=0" <<<"$out"
(set -Eeuo pipefail; domain_join; printf '%s' "$DOMAIN_NOTICE" >"$TMP/notice")
check "spatne heslo: upozorneni s duvodem" grep -q "could not join the domain firma.local: Wrong administrator name or password. Join it later in Settings > Organization Network." "$TMP/notice"
check "spatne heslo: @@NOTICE pro GUI" grep -q "^@@NOTICE The computer could not join" "$TMP/progress"
check "spatne heslo: v zaznamu" grep -q "^! The computer could not join" "$LOG"
check "spatne heslo: heslo nikde" no_secret "$LOG"

reset; echo missing >"$TMP/mode"
DOMAIN=firma.local DOMAIN_USER=admin DOMAIN_PASSWORD=x
(domain_join; printf '%s' "$DOMAIN_NOTICE" >"$TMP/notice")
check "lux-domain chybi: nezname chyba, pokracuje" grep -q "firma.local: unknown error" "$TMP/notice"

reset; : >"$TMP/argv"
domain_join
check "bez DOMAIN se nic nevola" test ! -s "$TMP/argv"

echo "## TUI (gum napodoba)"
gum() {
    local sub=$1 a
    shift
    printf '%s %s\n' "$sub" "$*" >>"$TMP/gum.log"
    case $sub in
        choose|input)
            a=$(head -1 "$TMP/answers"); sed -i 1d "$TMP/answers"
            [[ $a == __CANCEL__ ]] && return 1
            printf '%s\n' "$a" ;;
        confirm) return 0 ;;
    esac
}
answers() { printf '%s\n' "$@" >"$TMP/answers"; : >"$TMP/info"; }
PATH_SAVE=$PATH
PATH=$TMP/nobin:/usr/bin:/bin     # lux-domain v "live systemu" neni
answers "Me (personal computer)"
ask_domain
eq "TUI: osobni pocitac" "" "$DOMAIN"
answers "An organization (Windows domain)" "spatne" "Firma.Local" "admin" "$SECRET" ""
ask_domain
eq "TUI: domena (mala pismena, po chybe znovu)" "firma.local|admin" "$DOMAIN|$DOMAIN_USER"
eq "TUI: heslo" "$SECRET" "$DOMAIN_PASSWORD"
check "TUI: hlaska neplatne domeny" grep -q "not a valid domain name" "$TMP/info"
check "TUI: heslo pres --password" grep -q "^input --password" "$TMP/gum.log"
answers "An organization (Windows domain)" "__CANCEL__"
ask_domain
eq "TUI: Esc = bez domeny" "" "$DOMAIN"
# lux-domain v live systemu: discover nenasel -> potvrzeni "presto pouzit"
mkdir -p "$TMP/bin"
cat >"$TMP/bin/lux-domain" <<'EOF'
#!/bin/bash
if [[ $2 == firma.local ]]; then
    echo '{"ok": true, "domain": "firma.local", "realm": "FIRMA.LOCAL", "short": "FIRMA", "controllers": ["dc1.firma.local", "dc2.firma.local"]}'
else
    echo '{"ok": false, "error": "dns", "message": "No domain controller found (DNS)."}'; exit 1
fi
EOF
chmod +x "$TMP/bin/lux-domain"
PATH=$TMP/bin:$PATH_SAVE
answers "An organization (Windows domain)" "firma.local" "admin" "pw" "OU=X"
ask_domain
check "TUI: nalezena domena" grep -q "Found: Active Directory FIRMA.LOCAL (domain controllers: 2)" "$TMP/info"
eq "TUI: OU" "OU=X" "$OU"
answers "An organization (Windows domain)" "jina.local" "admin" "pw" ""
ask_domain
check "TUI: nenalezena -> hlaska lux-domain" grep -q "No domain controller found (DNS)." "$TMP/info"
check "TUI: dotaz presto pouzit" grep -q "confirm .*Use this domain anyway" "$TMP/gum.log"
eq "TUI: potvrzeno" "jina.local" "$DOMAIN"
PATH=$PATH_SAVE

echo "## napojeni v instalatoru"
check "balik luxos-domain v zakladu, s DOMAIN bez duplicity" grep -qF 'DOMAIN-} && " ${pkgs[*]} " != *" luxos-domain "* ]] && pkgs+=(luxos-domain)' "$FILES/luxos-install"
check "pripojeni po setup-chroot" bash -c "grep -n 'luxos-setup.sh\" \"\$TARGET/root/luxos-setup.env\"' '$FILES/luxos-install' >/dev/null && grep -A1 'luxos-setup.env\"$' '$FILES/luxos-install' | grep -q domain_join"
check "kontrola konfigurace volana" grep -q "^        domain_config   # DOMAIN=" "$FILES/luxos-install"
check "TUI krok po uctu" grep -q "^    ask_domain$" "$FILES/luxos-install"
check "setup env bez hesla domeny" bash -c "! sed -n '/luxos-setup.env\" <<ENV/,/^ENV/p' '$FILES/luxos-install' | grep -q DOMAIN"
check "priklad konfigurace" grep -q "^#DOMAIN=firma.local" "$FILES/install.conf.example"

echo
if ((FAILS)); then echo "$FAILS chyb"; exit 1; fi
echo "vse OK"
