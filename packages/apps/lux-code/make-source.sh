#!/bin/bash
# Lux Code - vytvoreni zdrojoveho archivu pro PKGBUILD z pracovni kopie
#
#   packages/apps/lux-code/make-source.sh [CESTA_K_LUX_CODE]     (vychozi ~/Lux-Code)
#
# Lux Code nema verejny repozitar, proto PKGBUILD bere zdroj z lokalniho archivu
# lux-code-<verze>.tar.gz vedle sebe (verze ze souboru VERSION). Archiv obsahuje
# jen to, co je potreba k sestaveni a behu: zdrojove *.lsl (bez testu a Debian
# skriptu), assets/, packaging/lux-code.desktop, README.md, TOOLS.md,
# .env.example a VERSION. Uzivatelska data (.env, sezeni, artefakty), .build,
# dist a zalohy se nikdy nebali.
# Knihovna shell (lsl install shell) neni soucasti vydani LSL, proto se prilozi
# vedle chat.lsl (stejne jako lokalni aikit.lsl); cesta: LSL_SHELL.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
src=${1:-$HOME/Lux-Code}
[[ -f $src/chat.lsl && -f $src/VERSION ]] || { echo "No Lux Code at $src" >&2; exit 1; }
ver=$(tr -d ' \n' <"$src/VERSION")
[[ $ver =~ ^[0-9][0-9a-z.]*$ ]] || { echo "Invalid version in $src/VERSION" >&2; exit 1; }
files=()
for f in "$src"/*.lsl; do
    f=${f##*/}
    case $f in test*.lsl | build_deb.lsl) continue ;; esac
    files+=("$f")
done
files+=(assets/luxai.png packaging/lux-code.desktop README.md TOOLS.md .env.example VERSION)
for f in "${files[@]}"; do
    [[ -f $src/$f ]] || { echo "Missing $src/$f" >&2; exit 1; }
done
shell_lib=${LSL_SHELL:-$HOME/.local/lib/lsl/stdlib/shell.lsl}
[[ -f $shell_lib ]] && head -1 "$shell_lib" | grep -q '^# shell 1\.' ||
    { echo "LSL library shell not found at $shell_lib (lsl install shell)" >&2; exit 1; }
[[ -e $src/shell.lsl ]] && { echo "$src/shell.lsl already exists; remove LSL_SHELL vendoring" >&2; exit 1; }
out=$here/lux-code-$ver.tar.gz
tar --transform "s,^,lux-code-$ver/," --mode=u=rwX,go=rX \
    --owner=0 --group=0 --numeric-owner --mtime=@0 --sort=name -czf "$out" \
    -C "$src" "${files[@]}" -C "$(dirname "$shell_lib")" "$(basename "$shell_lib")"
# Kontrola: v archivu nesmi byt tajne udaje ani uzivatelska data
if tar -tzf "$out" | grep -E '(^|/)\.env$|/\.env\.[^e]|sessions/|artifacts/|\.build/|dist/|backup' >&2; then
    rm -f "$out"; echo "Archive contains private files" >&2; exit 1
fi
sha=$(sha256sum "$out" | cut -d' ' -f1)
sed -i "s/^pkgver=.*/pkgver=$ver/; s/^\(sha256sums=('\)[0-9a-f]*'/\1$sha'/" "$here/PKGBUILD"
echo "$out ($ver, sha256 $sha); PKGBUILD updated"
