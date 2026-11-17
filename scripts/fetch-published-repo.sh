#!/bin/bash
# LuxOS - stazeni zverejnenych (podepsanych) repozitaru [luxos] a [luxos-apps] do out/repo
#
#   scripts/fetch-published-repo.sh [URL]     vychozi https://luxos.lux-ai.cz/repo
#                                             (testovaci kanal: https://luxos.lux-ai.cz/staging)
#
# Pro sestaveni ISO na GitHub Actions: baliky se podepisuji jen na pocitaci spravce (soukromy klic
# LuxOS nikdy neni na GitHubu), workflow z nich pak postavi ISO (./build.sh iso). Seznam souboru
# bere z databaze repozitare (%FILENAME%), ne z vypisu adresare. Podpis databaze i kazdeho baliku
# se overi verejnym klicem LuxOS (packages/luxos-keyring), takze podvrzeny server neprojde.
#
# Jen nektere baliky (proprietarni soucasti pri sestaveni z verejneho repozitare, viz PROPRIETARY
# v packages/ a scripts/container-build.sh):
#   LUXOS_FETCH_REPOS="luxos-apps" LUXOS_FETCH_ONLY="luxai lux-code" LUXOS_FETCH_OUT=/cesta scripts/fetch-published-repo.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
BASE=${1:-https://luxos.lux-ai.cz/repo}
ARCH=x86_64
OUT=${LUXOS_FETCH_OUT:-out/repo}
KEYRING=packages/luxos-keyring
# --retry-all-errors: i nepodarene spojeni (curl 7) - server obcas na GitHub Actions neodpovi (iso-test 2026-11-17)
get() { curl -fsSL --retry 6 --retry-delay 5 --retry-all-errors --connect-timeout 20 -o "$2" "$1"; }

gnupg=$(mktemp -d "${TMPDIR:-/tmp}/luxos-fetch.XXXXXX")
trap 'rm -rf "$gnupg"' EXIT
export GNUPGHOME=$gnupg
key=$(find "$KEYRING" -name '*.gpg' -o -name '*.asc' | head -1)
[[ -n $key ]] || { echo "No LuxOS public key in $KEYRING" >&2; exit 1; }
gpg --quiet --import "$key"
verify() { gpg --quiet --status-fd 1 --verify "$1.sig" "$1" 2>/dev/null | grep -q '^\[GNUPG:\] VALIDSIG'; }

read -ra REPOS <<<"${LUXOS_FETCH_REPOS:-luxos luxos-apps}"
read -ra ONLY <<<"${LUXOS_FETCH_ONLY:-}"
for repo in "${REPOS[@]}"; do
    [[ $repo == @(luxos|luxos-apps) ]] || { echo "Unknown repository: $repo" >&2; exit 1; }
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
    # "NAZEV SOUBOR" pro kazdy balik databaze (%NAME% a %FILENAME% v kazdem desc)
    mapfile -t entries < <(tar -xzOf "$dir/$repo.db.tar.gz" --wildcards '*/desc' |
        awk 'f {file=$0; f=0} n {name=$0; n=0} /^%FILENAME%$/ {f=1} /^%NAME%$/ {n=1}
             /^%FILENAME%$/ || /^%NAME%$/ {next} file != "" && name != "" {print name, file; file=""; name=""}
             END {if (file != "" && name != "") print name, file}')
    files=()
    for e in "${entries[@]}"; do
        if ((${#ONLY[@]})); then
            want=0
            for o in "${ONLY[@]}"; do [[ ${e%% *} == "$o" ]] && want=1; done
            ((want)) || continue
        fi
        files+=("${e#* }")
    done
    if ((${#ONLY[@]})) && ((${#files[@]} == 0)); then
        echo "None of the packages ${ONLY[*]} is in [$repo] at $BASE" >&2; exit 1
    fi
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
