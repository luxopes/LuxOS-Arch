#!/usr/bin/env bash
# LuxOS installer (TUI) - krok LuxAI: heslo, kod z e-mailu a zalozeni uctu proti lokalni napodobe serveru.
#
#   bash packages/luxos-installer/tests/test-tui-luxai.sh
#
# Funkce ask_luxai .. luxai_call se vezmou primo z luxos-install, gum je nahrazen skriptovanymi odpovedmi.
# Zadne skutecne ucty ani e-maily (server: packages/luxos-account/tests/mock_luxai.py na 127.0.0.1).
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/luxai-tui.XXXXXX")
FAILS=0

python3 "$ROOT/luxos-account/tests/mock_luxai.py" 300 >"$TMP/origin" &
MOCK_PID=$!
trap 'kill "$MOCK_PID" 2>/dev/null; rm -rf "$TMP"' EXIT
for _i in $(seq 50); do [[ -s $TMP/origin ]] && break; sleep 0.1; done
ORIGIN=$(head -1 "$TMP/origin")
export LUXAI_ORIGIN=$ORIGIN LANG=en_US.UTF-8 LUXOS_I18N_DIR=$ROOT/luxos-i18n/files
export PYTHONPATH=$ROOT/luxos-account/files:$ROOT/luxos-i18n/files
export XDG_CONFIG_HOME=$TMP/config

check() {  # check POPIS PRIKAZ...
    if "${@:2}"; then echo "ok    $1"; else echo "FAIL  $1"; FAILS=$((FAILS + 1)); fi
}
mock() { curl -s -X POST -H 'Content-Type: application/json' -d "$2" "$ORIGIN$1" >/dev/null; }

# ---- napodoba prostredi luxos-install ----
T() { local f=$1; shift; printf -- "$f" "$@"; }
title() { :; }
info() { printf '%s\n' "$*" >>"$TMP/info"; }
# gum: odpovedi z fronty $TMP/answers (radek "__CANCEL__" = Esc)
gum() {
    local sub=$1 a
    shift
    case $sub in
        choose|input)
            a=$(head -1 "$TMP/answers")
            sed -i 1d "$TMP/answers"
            printf '%s %s\n' "$sub" "$*" >>"$TMP/gum.log"
            [[ $a == __CANCEL__ ]] && return 1
            printf '%s\n' "$a" ;;
        pager) cat >"$TMP/pager" ;;
        confirm) return 0 ;;
    esac
}
answers() { printf '%s\n' "$@" >"$TMP/answers"; : >"$TMP/info"; }

# funkce z instalatoru (od LUXAI_ACCOUNT="" po ask_password)
eval "$(sed -n '/^LUXAI_ACCOUNT=""/,/^ask_password() {/p' "$ROOT/luxos-installer/files/luxos-install" | sed '$d')"

acct_email() { python3 -c 'import json,sys; print(json.loads(sys.argv[1])["user"]["email"])' "$LUXAI_ACCOUNT"; }

# 1) prihlaseni heslem: spatne, pak preskocit
answers "Sign in with a password" jan@example.cz "bad password" "Skip"
LUXAI_ACCOUNT=""
ask_luxai
check "heslo: neexistujici ucet -> hlaska" grep -q "Wrong e-mail or password." "$TMP/info"
check "heslo: bez uctu" test -z "$LUXAI_ACCOUNT"

# 2) novy ucet: kratke heslo, neshoda, podminky (cteni), novy kod (slow_down), spatny a spravny kod
answers "Create a new account" "Petr Novy" "petr@example.cz" "kratke" "dlouhe heslo 2026" "jine heslo 2026" \
    "dlouhe heslo 2026" "dlouhe heslo 2026" "Read the terms" "I agree to the LuxAI Terms" "" "000000" "123456"
LUXAI_ACCOUNT=""
FULLNAME="Petr Novy"
ask_luxai
check "registrace: kratke heslo -> hlaska" grep -q "at least 12 characters" "$TMP/info"
check "registrace: neshoda hesel" grep -q "Passwords do not match." "$TMP/info"
check "registrace: podminky jako text v pageru" grep -q "Podmínky používání LuxAI" "$TMP/pager"
check "registrace: podminky bez HTML" bash -c "! grep -q '<p>' '$TMP/pager'"
check "registrace: kod odeslan na e-mail" grep -q "We sent a code to petr@example.cz." "$TMP/info"
check "registrace: novy kod hned -> pockat" grep -q "Please wait a minute" "$TMP/info"
check "registrace: spatny kod" grep -q "The code is not valid or has expired." "$TMP/info"
check "registrace: prihlaseno" test "$(acct_email)" = petr@example.cz
check "registrace: heslo neni v JSON" bash -c "! grep -q 'dlouhe heslo' <<<'$LUXAI_ACCOUNT'"
check "registrace: jmeno predvyplneno z uctu" grep -q -- "--value Petr Novy" "$TMP/gum.log"

# 3) prihlaseni kodem (ucet z kroku 2)
mock /__mock/reset_cooldown '{}'
answers "Sign in with a code from e-mail" "petr@example.cz" "12 34 56"
LUXAI_ACCOUNT=""
ask_luxai
check "kod: prihlaseno (mezery v kodu nevadi)" test "$(acct_email)" = petr@example.cz

# 4) heslem (novy ucet) a luxai_login pro install.conf
LUXAI_ACCOUNT=""
check "luxai_login: heslo noveho uctu" luxai_login petr@example.cz "dlouhe heslo 2026"
check "luxai_login: JSON uctu" test "$(acct_email)" = petr@example.cz

# 5) server zatim nepovoluje registraci z LuxOS (403 origin) -> odkaz na web, pak preskocit
mock /__mock/allow_native '{"value": false}'
answers "Create a new account" "Eva" "eva@example.cz" "dlouhe heslo 2026" "dlouhe heslo 2026" \
    "I agree to the LuxAI Terms" "Skip"
LUXAI_ACCOUNT=""
ask_luxai
check "403 origin: hlaska s odkazem na /register" grep -q "not available yet - create it at $ORIGIN/register" "$TMP/info"
check "403 origin: bez uctu" test -z "$LUXAI_ACCOUNT"

# 6) existujici ucet a ceska hlaska
mock /__mock/allow_native '{"value": true}'
export LANG=cs_CZ.UTF-8
LUXAI_ACCOUNT=""
luxai_call register petr@example.cz "dlouhe heslo 2026" Petr
check "cesky: ucet uz existuje" test "$LUXAI_ERROR" = "Účet s tímto e-mailem už existuje. Přihlaste se."
check "kod chyby account_exists" test "$LUXAI_CODE" = account_exists

# 7) Esc v nabidce = preskocit
answers "__CANCEL__"
LUXAI_ACCOUNT=""
check "Esc: krok se preskoci" ask_luxai
check "Esc: bez uctu" test -z "$LUXAI_ACCOUNT"

# 8) server nedostupny
kill "$MOCK_PID" 2>/dev/null
wait "$MOCK_PID" 2>/dev/null
export LANG=en_US.UTF-8
luxai_call code_request jan@example.cz
check "bez site: kod network" test "$LUXAI_CODE" = network

echo
if ((FAILS)); then echo "$FAILS chyb"; exit 1; fi
echo "vse OK"
