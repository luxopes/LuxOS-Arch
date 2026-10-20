#!/bin/bash
# LuxOS - sestaveni ISO
#
#   ./build.sh            baliky + ISO  (vystup: out/luxos-*.iso)
#   ./build.sh packages   jen baliky (out/repo)
#   ./build.sh iso        jen ISO z jiz sestavenych baliku
#
# Potrebuje podman (doporuceno) nebo docker; vse ostatni bezi v Arch kontejneru.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

engine=$(command -v podman || command -v docker || true)
[[ -n $engine ]] || { echo "Install podman or docker first." >&2; exit 1; }

"$engine" build -t luxos-builder -f scripts/Containerfile scripts
mkdir -p out/pkgcache
"$engine" run --rm --privileged \
    -v "$PWD:/luxos:z" \
    -v "$PWD/out/pkgcache:/var/cache/pacman/pkg:z" \
    luxos-builder /luxos/scripts/container-build.sh "${1:-all}"
