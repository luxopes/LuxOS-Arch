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

# jadro LuxOS (GitHub Actions) do out/kernel, overene - pri stavbe repozitare [luxos]
case ${1:-all} in all|packages|iso-test) scripts/fetch-kernel.sh ;; esac

"$engine" build -t luxos-builder -f scripts/Containerfile scripts
mkdir -p out/pkgcache
# Podpisovy klic repozitare (mimo projekt); bez nej vzniknou nepodepsane baliky
signing=()
key="${LUXOS_SIGNING_DIR:-$HOME/.local/share/luxos/signing}"
[[ -d $key ]] && signing=(-v "$key:/signing:ro,z")
# TEST sestaveni: klic LuxOS do kontejneru vubec nepripojit; kratky hash commitu do nazvu ISO
if [[ ${1:-} == iso-test ]]; then
    signing=(-e "LUXOS_TEST_SHA=$(git rev-parse --short=7 HEAD 2>/dev/null || echo local)")
fi
"$engine" run --rm --privileged \
    -v "$PWD:/luxos:z" \
    -v "$PWD/out/pkgcache:/var/cache/pacman/pkg:z" \
    "${signing[@]}" \
    luxos-builder /luxos/scripts/container-build.sh "${@:-all}"
