#!/bin/bash
# LuxOS installer - kanal aktualizaci (install_engine_config) BEZ roota a disku: live system testovaciho
# ISO s channel = "staging" -> nainstalovany system taky staging; jinak lux.conf presne z baliku (stable).
#
#   packages/luxos-installer/tests/test-channel.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
FILES=$HERE/../files
ENGINE=$(cd "$HERE/../../lux-engine" && pwd)
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
NPASS=0 NFAIL=0
ok()  { NPASS=$((NPASS + 1)); printf 'ok    %s\n' "$1"; }
bad() { NFAIL=$((NFAIL + 1)); printf 'FAIL  %s\n' "$1"; [[ -n ${2-} ]] && printf '      %s\n' "$2"; return 0; }

extract() { sed -n "/^$1() {/,/^}/p" "$FILES/luxos-install"; }
eval "$(extract install_engine_config)"
# shellcheck disable=SC2059
T() { local f=$1; shift; printf -- "$f" "$@"; }
info() { echo "INFO $*" >>"$OUT/info"; }
LOG=$OUT/log
SHARE=$FILES
LUX_CONFIG_TOOL=$ENGINE/lux_config.py
MIRRORLIST=$OUT/mirrorlist
# shellcheck disable=SC2016
printf 'https://mirror.example/$repo/os/$arch\n' >"$MIRRORLIST"
export XDG_CONFIG_HOME=$OUT/none

run_case() {  # run_case KANAL_LIVE -> $TARGET/etc/lux/lux.conf
    TARGET=$OUT/target-$1
    LIVE_LUX_CONF=$OUT/live-$1.conf
    sed -e "s|^channel = \"stable\"|channel = \"$1\"|" -e "s|/etc/lux/mirrorlist|$MIRRORLIST|" \
        -e 's|^files = .*|files = []|' "$FILES/lux.conf" >"$LIVE_LUX_CONF"
    install_engine_config
}

run_case stable
if cmp -s "$FILES/lux.conf" "$OUT/target-stable/etc/lux/lux.conf"; then
    ok "stable live system: lux.conf unchanged from the package"
else
    bad "stable: lux.conf differs from the package"
fi

run_case staging
conf=$OUT/target-staging/etc/lux/lux.conf
if grep -qx 'channel = "staging"' "$conf"; then
    ok "staging live system: installed lux.conf has channel staging"
else
    bad "staging channel not written" "$(grep -n channel "$conf")"
fi
if diff <(sed 's/^channel = "staging"$/channel = "stable"/' "$conf") "$FILES/lux.conf" >/dev/null; then
    ok "only the channel line differs"
else
    bad "other lines changed"
fi
servers=$(cd "$ENGINE" && python3 -c 'import sys, lux_config as lc
d = lc.load("/etc/lux/lux.conf", root=sys.argv[1])
print(" ".join(sorted({s for r in d["repos"] if r["name"].startswith("luxos") for s in r["servers"]})))' \
    "$OUT/target-staging")
# shellcheck disable=SC2016
if [[ $servers == 'https://luxos.lux-ai.cz/staging/$repo/$arch' ]]; then
    ok "installed system reads the LuxOS repositories from /staging/"
else
    bad "LuxOS repository servers" "$servers"
fi
if [[ ! -s $OUT/info ]]; then ok "no warning"; else bad "warning shown" "$(cat "$OUT/info")"; fi

echo "passed: $NPASS, failed: $NFAIL"
((NFAIL == 0))
