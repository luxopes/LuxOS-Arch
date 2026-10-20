#!/bin/bash
# LuxAI - vytvoreni zdrojoveho archivu pro PKGBUILD z pracovni kopie aplikace
#
#   packages/apps/luxai/make-source.sh [CESTA_K_LUXAI]     (vychozi ~/LuxAI)
#
# Aplikace nema verejny repozitar, proto PKGBUILD bere zdroj z lokalniho archivu
# luxai-<verze>.tar.gz vedle sebe (verze z luxai/__init__.py). Archiv obsahuje jen
# to, co bezi u uzivatele: luxai/ (bez __pycache__), i18n/, data/, README.md;
# testy a .git se vynechavaji.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
src=${1:-$HOME/LuxAI}
[[ -f $src/luxai/__init__.py ]] || { echo "No LuxAI at $src" >&2; exit 1; }
ver=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$src/luxai/__init__.py")
[[ -n $ver ]] || { echo "No __version__ in $src/luxai/__init__.py" >&2; exit 1; }
out=$here/luxai-$ver.tar.gz
tar -C "$src" --exclude=__pycache__ --exclude='*.pyc' --transform "s,^,luxai-$ver/," \
    --owner=0 --group=0 --numeric-owner --mtime=@0 --sort=name -czf "$out" luxai i18n data README.md
sha=$(sha256sum "$out" | cut -d' ' -f1)
sed -i "s/^pkgver=.*/pkgver=$ver/; s/^sha256sums=.*/sha256sums=('$sha')/" "$here/PKGBUILD"
echo "$out ($ver, sha256 $sha); PKGBUILD updated"
