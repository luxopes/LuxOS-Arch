#!/bin/bash
# LuxOS - sestaveni ISO
#
#   ./build.sh            baliky + ISO  (vystup: out/luxos-*.iso)
#   ./build.sh packages   jen baliky (out/repo)
#   ./build.sh apps       jen aplikace [luxos-apps] (packages/apps/*), [luxos] beze zmeny
#   ./build.sh iso        jen ISO z jiz sestavenych baliku
#   ./build.sh one BALIK  jeden balik do out/single (na zkousku, repozitar beze zmeny)
#   ./build.sh iso-test   baliky + TEST ISO podepsane jednorazovym klicem (nikdy klicem LuxOS):
#                         out/luxos-VERZE-TEST-COMMIT-x86_64.iso, verejny testovaci klic out/luxos-test-key.asc
#
# Potrebuje podman (doporuceno) nebo docker; vse ostatni bezi v Arch kontejneru.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

engine=$(command -v podman || command -v docker || true)
[[ -n $engine ]] || { echo "Install podman or docker first." >&2; exit 1; }

# Podpisovy klic repozitare (mimo projekt); bez nej vzniknou nepodepsane baliky.
# Poradi: LUXOS_SIGNING_DIR (none = nepodepisovat), Trezor /safe/$USER/luxos-signing (doporuceno,
# viz dokumentace Trezoru), stare misto ~/.local/share/luxos/signing.
# GnuPG v kontejneru pracuje s kopii klice v tmpfs (/run/luxos-gnupg), ne ve vrstve kontejneru na disku.
signing=(--tmpfs /run/luxos-gnupg:rw,mode=0700 -e LUXOS_GNUPG_TMP=/run/luxos-gnupg/home)
signing_copy=
cleanup_signing() { if [[ -n $signing_copy ]]; then rm -rf "$signing_copy"; fi; }
trap cleanup_signing EXIT
safe_key=/safe/$USER/luxos-signing
if [[ ${1:-} == iso-test ]]; then
    # TEST sestaveni: klic LuxOS do kontejneru vubec nepripojit; kratky hash commitu do nazvu ISO
    key=
    signing+=(-e "LUXOS_TEST_SHA=$(git rev-parse --short=7 HEAD 2>/dev/null || echo local)")
elif [[ -n ${LUXOS_SIGNING_DIR:-} ]]; then
    key=$LUXOS_SIGNING_DIR
elif [[ -d $safe_key ]]; then
    key=$safe_key
elif [[ -d $HOME/.local/share/luxos/signing ]]; then
    key=$HOME/.local/share/luxos/signing
elif [[ -f /safe/.vaults/$USER/gocryptfs.conf ]] \
        && [[ $(findmnt -no FSTYPE --mountpoint "/safe/$USER" 2>/dev/null | tail -n1) != fuse.gocryptfs ]]; then
    echo "Unlock the Safe first (luxos-safe unlock): the signing key is expected in $safe_key." >&2
    echo "To build unsigned packages, run: LUXOS_SIGNING_DIR=none ./build.sh ${*:-}" >&2
    exit 1
else
    key=
fi
if [[ -n $key && $key != none && -d $key ]]; then
    if [[ $key == /safe/* ]]; then
        # Trezor je FUSE bez allow_other: kontejner pod rootem (docker) by do nej nevidel.
        # Kopie jen na dobu sestaveni v soukrome slozce v RAM ($XDG_RUNTIME_DIR je tmpfs).
        signing_copy=$(mktemp -d "${XDG_RUNTIME_DIR:-/dev/shm}/luxos-signing.XXXXXX")
        cp -a "$key/." "$signing_copy/"
        key=$signing_copy
    fi
    signing+=(-v "$key:/signing:ro,z")
fi

# jadro LuxOS (GitHub Actions) do out/kernel, overene - pri stavbe repozitare [luxos]
case ${1:-all} in all|packages|iso-test) scripts/fetch-kernel.sh ;; esac

"$engine" build -t luxos-builder -f scripts/Containerfile scripts
mkdir -p out/pkgcache
"$engine" run --rm --privileged \
    -v "$PWD:/luxos:z" \
    -v "$PWD/out/pkgcache:/var/cache/pacman/pkg:z" \
    "${signing[@]}" \
    luxos-builder /luxos/scripts/container-build.sh "${@:-all}"
