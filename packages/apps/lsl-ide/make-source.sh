#!/bin/bash
# LSL IDE - vytvoreni zdrojoveho archivu pro PKGBUILD z pracovni kopie IDE
#
#   packages/apps/lsl-ide/make-source.sh [CESTA_K_IDE]     (vychozi ~/lsl-ide)
#
# IDE nema verejny repozitar, proto PKGBUILD bere zdroj z lokalniho archivu
# lsl-ide-<verze>.tar.gz vedle sebe (verze z lslide/__init__.py). Archiv
# obsahuje jen to, co bezi u uzivatele: lslide/ (bez __pycache__), share/,
# README.md; serverova cast (server/) a .git se vynechavaji.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
src=${1:-$HOME/lsl-ide}
[[ -f $src/lslide/__init__.py ]] || { echo "No IDE at $src" >&2; exit 1; }
ver=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$src/lslide/__init__.py")
[[ -n $ver ]] || { echo "No __version__ in $src/lslide/__init__.py" >&2; exit 1; }
out=$here/lsl-ide-$ver.tar.gz
tar -C "$src" --exclude=__pycache__ --exclude='*.pyc' --transform "s,^,lsl-ide-$ver/," \
    --owner=0 --group=0 --numeric-owner --mtime=@0 --sort=name -czf "$out" lslide share README.md
sha=$(sha256sum "$out" | cut -d' ' -f1)
sed -i "s/^pkgver=.*/pkgver=$ver/; s/^sha256sums=.*/sha256sums=('$sha')/" "$here/PKGBUILD"
echo "$out ($ver, sha256 $sha); PKGBUILD updated"
