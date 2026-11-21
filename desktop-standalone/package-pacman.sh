#!/bin/bash
# LuxOS Desktop: balicek pro pacman z hotoveho stromu (build.sh pacman). $1 strom, $2 verze, $3 commit, $4 vystup
set -euo pipefail
HERE=$(dirname "$(readlink -f "$0")")
stage=$(readlink -f "$1") ver=$2 commit=$3 out=$(readlink -f "$4")
dir=$(dirname "$stage")/pacman
rm -rf "$dir" && mkdir -p "$dir"
deps=$(grep -v '^#' "$HERE/deps/arch-runtime.txt" | tr -s ' \n' ' ')
cat >"$dir/PKGBUILD" <<PKG
pkgname=lux-desktop
pkgver=$ver
pkgrel=1
pkgdesc="The LuxOS desktop on top of Xfce (LuxOS-Arch $commit)"
arch=(x86_64)
url=https://github.com/luxopes/lux-desktop
license=(GPL-3.0-or-later MIT LGPL-2.1-or-later)
depends=($deps)
conflicts=(luxos-desktop)
options=(!strip !debug !emptydirs)
install=lux-desktop.install
package() { cp -a "$stage/." "\$pkgdir/"; }
PKG
cat >"$dir/lux-desktop.install" <<'INST'
post_install() {
    gtk-update-icon-cache -q -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
    for t in /usr/share/icons/WhiteSur*; do gtk-update-icon-cache -q -f "$t" >/dev/null 2>&1 || true; done
    udevadm control --reload >/dev/null 2>&1 || true
}
post_upgrade() { post_install; }
INST
(cd "$dir" && PKGDEST="$out" makepkg -f --nodeps --noconfirm >/dev/null)
ls -1 "$out"/lux-desktop-*.pkg.tar.*
