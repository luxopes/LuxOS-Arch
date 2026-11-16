#!/bin/bash
# Instalator se z relace uzivatele presune do vlastni jednotky v system.slice (bez limitu uloh).
# Regrese (audit 1.0.2): instalace z GUI na pocitaci se 4 GB RAM selhala - session-N.scope ma limit
# ~1 500 uloh a pacstrap nechava ~1 400 zombie gpg ("GPGME error", "missing required signature").
#   bash packages/luxos-installer/tests/test-install-scope.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$HERE/../files/luxos-install
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
pass=0 fail=0
expect() { if "${@:2}"; then echo "ok    $1"; ((pass++)); else echo "FAIL  $1"; ((fail++)); fi; }

# funkce z instalatoru; EUID a /proc/self/cgroup nahrazene pro test
sed -n '/^luxos_install_scope() {/,/^}/p' "$SRC" |
    sed -e 's/((EUID == 0))/((FAKE_EUID == 0))/' -e "s|/proc/self/cgroup|\$FAKE_CG|" >"$T/f.sh"
expect "funkce nalezena" grep -q 'FAKE_CG' "$T/f.sh"
. "$T/f.sh"
mkdir -p "$T/run"

check() {  # check EUID CGROUP [ARGS...] -> 0 = presunout
    FAKE_EUID=$1 FAKE_CG=$T/cg
    printf '%s\n' "$2" >"$T/cg"
    shift 2
    luxos_install_scope "$@"
}
if [[ -d /run/systemd/system ]] && command -v systemd-run >/dev/null; then
    expect "GUI (session scope) -> vlastni jednotka" check 0 "0::/user.slice/user-1000.slice/session-1.scope" --config - --yes --progress
    expect "Terminal (user@1000.service) -> vlastni jednotka" check 0 "0::/user.slice/user-1000.slice/user@1000.service/app.slice/luxos-terminal2.service"
    expect "uz v system.slice -> beze zmeny" bash -c "! { $(declare -f check luxos_install_scope); T='$T'; check 0 '0::/system.slice/run-p1-i1.scope'; }"
    expect "jen root" bash -c "! { $(declare -f check luxos_install_scope); T='$T'; check 1000 '0::/user.slice/user-1000.slice/session-1.scope'; }"
    for a in --probe --scan --check-layout; do
        expect "$a (jen cteni) -> beze zmeny" bash -c "! { $(declare -f check luxos_install_scope); T='$T'; check 0 '0::/user.slice/user-1000.slice/session-1.scope' $a /dev/vda; }"
    done
    expect "bez opakovani (LUXOS_INSTALL_SCOPE)" bash -c "! { $(declare -f check luxos_install_scope); T='$T'; LUXOS_INSTALL_SCOPE=1; check 0 '0::/user.slice/user-1000.slice/session-1.scope'; }"
else
    echo "skip  bez systemd"
fi
# spusteni: systemd-run --scope v system.slice bez limitu, pred zpracovanim argumentu
expect "systemd-run --scope system.slice TasksMax=infinity" \
    grep -qE 'exec systemd-run --quiet --scope --collect --slice=system.slice -p TasksMax=infinity' "$SRC"
expect "pred ctenim konfigurace ze stdin" bash -c \
    "[[ \$(grep -n 'exec systemd-run' '$SRC' | cut -d: -f1) -lt \$(grep -n 'CONFIG_DATA=\$(cat)' '$SRC' | cut -d: -f1) ]]"

echo
echo "Vysledek: $pass ok, $fail FAIL"
((fail == 0))
