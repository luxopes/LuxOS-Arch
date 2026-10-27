#!/bin/bash
# LuxAI - vytvoreni zdrojoveho archivu pro PKGBUILD z pracovni kopie nativni (LSL) aplikace
#
#   packages/apps/luxai/make-source.sh [CESTA_K_LUXAI]     (vychozi ~/Projects/LuxAI-lsl-finish)
#
# Aplikace nema verejny repozitar, proto PKGBUILD bere zdroj z lokalniho archivu
# luxai-<verze>.tar.gz vedle sebe (verze ze souboru VERSION). Archiv obsahuje jen to, co je
# potreba k prekladu a instalaci: lsl/ (zdroje LSL), data/ (desktop soubor, ikony, polkit
# politika), i18n/, tools/build-lsl.sh, VERSION, README.md a dokumentaci migrace. Python
# reference (luxai/), testy a .git se vynechavaji; testy bezi v projektu (tools/test-lsl.sh)
# a jejich vysledek je v docs/lsl-verification.json.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
src=${1:-$HOME/Projects/LuxAI-lsl-finish}
[[ -f $src/VERSION && -f $src/lsl/main.lsl ]] || { echo "No native LuxAI at $src" >&2; exit 1; }
ver=$(tr -d '[:space:]' <"$src/VERSION")
[[ $ver =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Invalid VERSION in $src" >&2; exit 1; }
grep -qx "VERSION = \"$ver\"" "$src/lsl/version.lsl" || { echo "lsl/version.lsl differs from VERSION" >&2; exit 1; }
out=$here/luxai-$ver.tar.gz
tar -C "$src" --exclude=__pycache__ --exclude='*.pyc' --transform "s,^,luxai-$ver/," \
    --owner=0 --group=0 --numeric-owner --mtime=@0 --sort=name -czf "$out" \
    VERSION README.md lsl data i18n tools/build-lsl.sh \
    docs/LSL-MIGRATION.md docs/LSL-ISSUES.md docs/REMOTE-SESSION.md docs/lsl-verification.json
sha=$(sha256sum "$out" | cut -d' ' -f1)
sed -i "s/^pkgver=.*/pkgver=$ver/; s/^sha256sums=.*/sha256sums=('$sha')/" "$here/PKGBUILD"
echo "$out ($ver, sha256 $sha); PKGBUILD updated"
