#!/bin/bash
# LuxOS - stazeni zverejnenych (podepsanych) repozitaru [luxos] a [luxos-apps] do out/repo
#
#   scripts/fetch-published-repo.sh [URL]     vychozi https://luxos.lux-ai.cz/repo
#
# Pro sestaveni ISO na GitHub Actions: baliky se podepisuji jen na pocitaci spravce (soukromy klic
# LuxOS nikdy neni na GitHubu), workflow z nich pak postavi ISO (./build.sh iso). Seznam souboru
# bere z databaze repozitare (%FILENAME%), ne z vypisu adresare. Podpis databaze i kazdeho baliku
# se overi verejnym klicem LuxOS (packages/luxos-keyring), takze podvrzeny server neprojde.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
BASE=${1:-https://luxos.lux-ai.cz/repo}
ARCH=x86_64
OUT=${LUXOS_FETCH_OUT:-out/repo}
KEYRING=packages/luxos-keyring
get() { curl -fsSL --retry 4 --retry-delay 3 -o "$2" "$1"; }

gnupg=$(mktemp -d "${TMPDIR:-/tmp}/luxos-fetch.XXXXXX")
trap 'rm -rf "$gnupg"' EXIT
export GNUPGHOME=$gnupg
key=$(find "$KEYRING" -name '*.gpg' -o -name '*.asc' | head -1)
[[ -n $key ]] || { echo "No LuxOS public key in $KEYRING" >&2; exit 1; }
gpg --quiet --import "$key"
verify() { gpg --quiet --status-fd 1 --verify "$1.sig" "$1" 2>/dev/null | grep -q '^\[GNUPG:\] VALIDSIG'; }

for repo in luxos luxos-apps; do
    dir=$OUT/$repo/$ARCH
    rm -rf "$OUT/$repo"
    mkdir -p "$dir"
    echo "==> [$repo] database"
    for f in "$repo.db.tar.gz" "$repo.files.tar.gz"; do
        get "$BASE/$repo/$ARCH/$f" "$dir/$f"
        get "$BASE/$repo/$ARCH/$f.sig" "$dir/$f.sig"
        verify "$dir/$f" || { echo "Bad signature: $f" >&2; exit 1; }
    done
    ln -sf "$repo.db.tar.gz" "$dir/$repo.db"; ln -sf "$repo.db.tar.gz.sig" "$dir/$repo.db.sig"
    ln -sf "$repo.files.tar.gz" "$dir/$repo.files"; ln -sf "$repo.files.tar.gz.sig" "$dir/$repo.files.sig"
    mapfile -t files < <(tar -xzOf "$dir/$repo.db.tar.gz" --wildcards '*/desc' | awk 'p {print; p=0} /^%FILENAME%$/ {p=1}')
    echo "==> [$repo] ${#files[@]} packages"
    for f in "${files[@]}"; do
        [[ $f =~ ^[A-Za-z0-9@._+-]+\.pkg\.tar\.zst$ ]] || { echo "Unexpected file name: $f" >&2; exit 1; }
        get "$BASE/$repo/$ARCH/$f" "$dir/$f"
        get "$BASE/$repo/$ARCH/$f.sig" "$dir/$f.sig"
        verify "$dir/$f" || { echo "Bad signature: $f" >&2; exit 1; }
        # ikona aplikace pro Obchod LuxOS (stejne jako make_repo v container-build.sh)
        pkgname=$(tar --zstd -xOf "$dir/$f" .PKGINFO | awk -F' = ' '$1 == "pkgname" {print $2; exit}')
        icon=$(tar --zstd -tf "$dir/$f" | grep -E "^usr/share/icons/hicolor/(scalable|512x512|256x256|128x128)/apps/$pkgname\.(svg|png)$" | head -1 || true)
        if [[ -n $icon ]]; then
            mkdir -p "$dir/icons"
            tar --zstd -xOf "$dir/$f" "$icon" >"$dir/icons/$pkgname.${icon##*.}"
        fi
    done
done
du -sh "$OUT"/*
