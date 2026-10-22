#!/bin/bash
# LuxOS - rychle sestaveni jednotlivych baliku v kontejneru luxos-builder (bez cele ./build.sh packages)
#   scripts/perf/build-pkg.sh VYSTUPNI_ADRESAR packages/balik [packages/dalsi ...]
# Baliky se stavi v zadanem poradi (pozdejsi mohou zaviset na drivejsich: nainstaluji se do kontejneru).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/../.."
out=$(readlink -f "${1:?out dir}"); shift
mkdir -p "$out" out/pkgcache out/sources
dirs=()
for d in "$@"; do dirs+=("/luxos/$d"); done
engine=$(command -v podman || command -v docker)
"$engine" run --rm --privileged -v "$PWD:/luxos:z" -v "$PWD/out/pkgcache:/var/cache/pacman/pkg:z" \
    -v "$out:/out:z" luxos-builder bash -euo pipefail -c '
pacman -Sy --noconfirm >/dev/null
for src in "$@"; do
    p=${src##*/}; b=/tmp/build/$p
    rm -rf "$b"; mkdir -p /tmp/build; cp -r "$src" "$b"; find "$b" -name __pycache__ -prune -exec rm -rf {} +
    chown -R builder: "$b" /out /luxos/out/sources
    (set +u; makedepends=(); checkdepends=(); depends=(); source "$b/PKGBUILD"
     deps=("${makedepends[@]}" "${checkdepends[@]}" "${depends[@]}")
     ((${#deps[@]})) && pacman -S --needed --noconfirm "${deps[@]}" >/dev/null 2>&1 || true)
    (cd "$b" && sudo -u builder env SRCDEST=/luxos/out/sources PKGDEST=/out makepkg --force --nodeps --noconfirm --cleanbuild)
    pacman -U --noconfirm /out/"$p"-*.pkg.tar.zst >/dev/null 2>&1 || true
done
' _ "${dirs[@]}"
ls -la "$out"
