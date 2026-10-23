#!/bin/bash
# LuxOS - jadro linux-luxos z GitHub Actions (https://github.com/luxopes/luxos-kernel) do out/kernel
#
#   scripts/fetch-kernel.sh [TAG]     bez TAGu nejnovejsi vydani (napr. v7.2.12-1)
#
# Overi kontrolni soucty (SHA256SUMS z vydani) a attestaci puvodu (balik postavil workflow
# kernel.yml repozitare luxopes/luxos-kernel, ne nekdo jiny). Podepisuje az container-build.sh
# klicem LuxOS pri stavbe repozitare [luxos]. Potrebuje gh (prihlaseny ucet).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
REPO=luxopes/luxos-kernel
OUT=out/kernel
tag=${1:-$(gh release list -R "$REPO" --limit 1 --exclude-drafts --exclude-pre-releases --json tagName --jq '.[0].tagName')}
[[ $tag =~ ^v[0-9]+\.[0-9]+(\.[0-9]+)?-[0-9]+$ ]] || { echo "Unexpected release tag: '$tag'" >&2; exit 1; }

have=$(cat "$OUT/TAG" 2>/dev/null || true)
if [[ $have == "$tag" ]] && compgen -G "$OUT/linux-luxos-[0-9]*.pkg.tar.zst" >/dev/null; then
    echo "linux-luxos $tag already in $OUT"
    exit 0
fi

tmp=$(mktemp -d "${TMPDIR:-/tmp}/luxos-kernel.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
echo "==> Downloading linux-luxos $tag"
gh release download "$tag" -R "$REPO" -D "$tmp" -p '*.pkg.tar.zst' -p SHA256SUMS -p build-info.txt
(cd "$tmp" && grep '\.pkg\.tar\.zst$' SHA256SUMS | sha256sum -c --quiet -) || { echo "Checksum mismatch" >&2; exit 1; }
echo "==> Verifying build provenance"
for f in "$tmp"/*.pkg.tar.zst; do
    gh attestation verify "$f" -R "$REPO" --signer-workflow "$REPO/.github/workflows/kernel.yml" >/dev/null ||
        { echo "Attestation check failed: ${f##*/}" >&2; exit 1; }
done
rm -rf "$OUT"
mkdir -p "$OUT"
mv "$tmp"/*.pkg.tar.zst "$tmp"/build-info.txt "$OUT/"
echo "$tag" > "$OUT/TAG"
ls -lh "$OUT"
