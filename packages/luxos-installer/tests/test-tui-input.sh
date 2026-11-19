#!/bin/bash
# LuxOS installer (TUI, --config) - vstupy uzivatele: navrh jmena, systemova jmena, heslo disku se
# zalomenim, Esc v otazce. Funkce primo z luxos-install, bez roota a bez disku.
#
#   bash packages/luxos-installer/tests/test-tui-input.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$HERE/../files/luxos-install
pass=0 fail=0
expect() { if "${@:2}"; then echo "ok    $1"; ((pass++)); else echo "FAIL  $1"; ((fail++)); fi; }
fn() { sed -n "/^$1() {/,/^}/p" "$SRC"; }

# --- navrh uzivatelskeho jmena: i bez vygenerovaneho jazyka pruvodce (LANG=cs_CZ.UTF-8 v live systemu)
eval "$(fn suggest_username)"
expect "Žofie Nová -> zofie (LANG bez locale)" test "$(LANG=cs_CZ.UTF-8 LC_ALL= suggest_username 'Žofie Nová')" = zofie
expect "Čeněk -> cenek (LC_ALL=C)" test "$(LC_ALL=C suggest_username 'Čeněk')" = cenek
expect "neplatne UTF-8 neukonci instalator" bash -c "set -Eeuo pipefail; $(fn suggest_username); x=\$(suggest_username \$'\\xff')"

# --- systemova jmena: seznam jako v GUI a systemove ucty live systemu
eval "$(grep '^RESERVED_USERS=' "$SRC")"
eval "$(fn reserved_user)"
eval "$(grep '^valid_user()' "$SRC")"
getent() { case $2 in systemd-network) echo 'systemd-network:x:192:192::/:/usr/bin/nologin' ;;
                      nobody) echo 'nobody:x:65534:65534::/:/usr/bin/nologin' ;;
                      jana) echo 'jana:x:1000:1000::/home/jana:/usr/bin/lsh' ;; *) return 2 ;; esac; }
expect "root odmitnut" bash -c "! { $(declare -f getent reserved_user valid_user); RESERVED_USERS='$RESERVED_USERS'; valid_user root; }"
expect "lightdm (seznam) odmitnut" bash -c "! { $(declare -f getent reserved_user valid_user); RESERVED_USERS='$RESERVED_USERS'; valid_user lightdm; }"
expect "systemd-network (systemovy ucet) odmitnut" bash -c "! { $(declare -f getent reserved_user valid_user); RESERVED_USERS='$RESERVED_USERS'; valid_user systemd-network; }"
expect "nobody (65534) odmitnut" bash -c "! { $(declare -f getent reserved_user valid_user); RESERVED_USERS='$RESERVED_USERS'; valid_user nobody; }"
expect "bezny ucet (1000) projde" valid_user jana
expect "nove jmeno projde" valid_user zofie
expect "velka pismena odmitnuta" bash -c "! { $(declare -f getent reserved_user valid_user); RESERVED_USERS='$RESERVED_USERS'; valid_user Zofie; }"
# stejny seznam jako GUI
gui=$(python3 -I - "$HERE/../files/luxos-install-gui" <<'PY'
import ast, sys
t = ast.parse(open(sys.argv[1]).read())
for n in t.body:
    if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "RESERVED_USERS":
        print(" ".join(sorted(ast.literal_eval(n.value))))
PY
)
expect "RESERVED_USERS shodne s GUI" test "$gui" = "$(tr ' ' '\n' <<<"$RESERVED_USERS" | sed '/^$/d' | sort | tr '\n' ' ' | sed 's/ $//')"

# --- heslo disku se zalomenim: konec pred zmenou disku (pri startu by neslo napsat)
OUT_L=$(mktemp "${TMPDIR:-/tmp}/tui-input.XXXXXX")
trap 'rm -f "$OUT_L"' EXIT
luks_check() {  # luks_check PROMENNA=hodnota... -> 0 = projde
    env "$@" bash -c "set -Eeuo pipefail
        T() { printf -- \"\$1\"; }; fail() { echo \"FAIL \$*\"; exit 1; }
        no_newline() { [[ \$1 != *\$'\\n'* && \$1 != *\$'\\r'* ]]; }
        f() { $(grep -A2 'Heslo disku se pri startu' "$SRC" | tail -2); }
        f" >"$OUT_L" 2>&1
}
luks_bad() { ! luks_check "$@" && grep -q 'Invalid LUKS_PASS' "$OUT_L"; }
expect "LUKS_PASS bez zalomeni projde" luks_check LUKS_PASS='tajne heslo'
expect "LUKS_PASS se zalomenim -> Invalid LUKS_PASS" luks_bad LUKS_PASS=$'a\nb'
expect "LUKS_PASS_CR (vlastni svazek) s CR -> Invalid LUKS_PASS" luks_bad LUKS_PASS=x LUKS_PASS_CR=$'a\r'

# --- casove pasmo podle IP (odpoved pres http): jen pasmo ze seznamu
tz() {  # tz "ODPOVED SERVERU" -> zjistene pasmo
    TZ_ANSWER=$1 bash -c "set -Eeuo pipefail
        curl() { printf '%s\n' \"\$TZ_ANSWER\"; }
        timedatectl() { seq 1 5000 | sed 's/^/Etc\/X/'; printf '%s\n' Europe/Prague America/New_York UTC; }
        $(fn detect_timezone)
        x=\$(detect_timezone); printf '%s' \"\$x\""
}
expect "Europe/Prague prijato (i za dlouhym seznamem)" test "$(tz Europe/Prague)" = Europe/Prague
expect "../../../bin/sh odmitnuto" test -z "$(tz ../../../bin/sh)"
expect "neexistujici pasmo odmitnuto" test -z "$(tz Mars/Base)"
expect "vice radku odmitnuto" test -z "$(tz $'Europe/Prague\n../../bin/sh')"
expect "bez site: prazdne, instalator pokracuje" test -z "$(tz '')"

# --- instalacni medium: oddil, cely disk (dd) i dm nad nim (Ventoy) -> disk se v seznamu nenabidne
iso() {  # iso ZDROJ "vystup lsblk -nsro NAME,TYPE"
    SRC_DEV=$1 LS=$2 bash -c "set -Eeuo pipefail
        findmnt() { echo \"\$SRC_DEV\"; }
        lsblk() { printf '%s\n' \"\$LS\"; }
        $(fn iso_disk)
        x=\$(iso_disk); printf '%s' \"\$x\""
}
expect "USB oddil -> sdb" test "$(iso /dev/sdb1 $'sdb1 part\nsdb disk')" = sdb
expect "cely disk (dd) -> sdb" test "$(iso /dev/sdb 'sdb disk')" = sdb
expect "Ventoy (dm nad oddilem) -> sdb" test "$(iso /dev/mapper/ventoy $'ventoy dm\nsdb1 part\nsdb disk')" = sdb
expect "bez media (copytoram) -> nic, bez chyby" test -z "$(iso '' '')"

# --- kontrola internetu: staci jeden server
net() {  # net "URL, ktere odpovi" -> 0 = internet
    OKURL=$1 bash -c "set -Eeuo pipefail
        curl() { [[ \" \$* \" == *\" \$OKURL \"* ]]; }
        $(fn have_internet)
        have_internet"
}
expect "pkgbuild.com nedostupny, LuxOS server ano -> internet" net https://luxos.lux-ai.cz/
expect "jen mirror Archu -> internet" net https://geo.mirror.pkgbuild.com/
expect "nic -> bez internetu" bash -c "! { $(declare -f net fn); SRC='$SRC'; net https://nikde.invalid/; }"

# --- gpg-agent keyringu v cili skonci i po selhani (jinak drzi $TARGET pripojeny)
G=$(mktemp -d "${TMPDIR:-/tmp}/tui-gpg.XXXXXX")
mkdir -p "$G/t/etc/lux/keyring"
bash -c "set -Eeuo pipefail
    gpgconf() { echo \"gpgconf \$*\" >>'$G/log'; }
    TARGET='$G/t'
    $(sed -n '/^stop_gpg_agents() {/,/^trap stop_gpg_agents EXIT/p' "$SRC")
    false   # selhani pri instalaci" 2>/dev/null
expect "po selhani: gpgconf --kill all pro keyring v cili" grep -qx "gpgconf --homedir $G/t/etc/lux/keyring --kill all" "$G/log"
rm -rf "$G"

# --- Esc v otazce (gum vraci 130): zruseno, ne "Installation failed"
esc() {  # esc ASKING -> vystup
    bash -c "set -Eeuo pipefail
        T() { local f=\$1; shift; printf -- \"\$f\" \"\$@\"; }; info() { printf '%s\n' \"\$*\"; }; progress() { :; }
        gum() { return 130; }; PROGRESS=1 LOG=/dev/null
        $(sed -n '/^ASKING=1/p; /^on_error() {/,/^}/p' "$SRC")
        trap 'on_error \$LINENO' ERR
        ASKING=$1
        x=\$(gum choose a b)" 2>&1
}
out=$(esc 1); rc=$?
expect "Esc pri otazkach: Zruseno, kod 130" bash -c "[[ $rc == 130 ]] && grep -q 'Cancelled. Nothing was changed.' <<<'$out' && ! grep -q 'Installation failed' <<<'$out'"
out=$(esc 0)
expect "130 behem instalace: dal selhani" grep -q 'Installation failed' <<<"$out"

echo
echo "Vysledek: $pass ok, $fail FAIL"
((fail == 0))
