#!/bin/bash
# Stavba libluxcomp, luxcomp-demo a luxwm pro testy na hostiteli proti pripnutemu sysrootu harnessu
# (scripts/wl-test/fetch-sysroot.sh): gcc + pkg-config, bez meson. Balik se stavi pres PKGBUILD.
# Vystup: $LUXWM_BUILD (vychozi out/luxwm-test/build v koreni repozitare).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
comp=$root/packages/luxcomp
sysroot=${WLT_SYSROOT:-$root/out/wl-test/sysroot}
b=${LUXWM_BUILD:-$root/out/luxwm-test/build}
mkdir -p "$b/proto" "$b/src"
export PKG_CONFIG_PATH=$sysroot/usr/lib/pkgconfig:$sysroot/usr/share/pkgconfig PKG_CONFIG_SYSROOT_DIR=$sysroot
proto=$sysroot/usr/share/wayland-protocols
for xml in $proto/stable/xdg-shell/xdg-shell.xml $proto/staging/cursor-shape/cursor-shape-v1.xml \
    $proto/unstable/tablet/tablet-unstable-v2.xml \
    $proto/staging/ext-image-copy-capture/ext-image-copy-capture-v1.xml \
    $proto/staging/ext-image-capture-source/ext-image-capture-source-v1.xml \
    $comp/protocols/wlr-layer-shell-unstable-v1.xml; do
  h=$b/proto/$(basename "$xml" .xml)-protocol.h
  [[ $h -nt $xml ]] || "$sysroot/usr/bin/wayland-scanner" server-header "$xml" "$h"
done
cflags="-O2 -g -std=c11 -Wall -Wno-unused-parameter -DWLR_USE_UNSTABLE -I$comp/include -I$b/proto
  $(pkg-config --cflags wlroots-0.20 wayland-server xkbcommon libdrm pixman-1 cairo pangocairo)
  $(PKG_CONFIG_SYSROOT_DIR= PKG_CONFIG_PATH= pkg-config --cflags glib-2.0)"
libs="$(pkg-config --libs wlroots-0.20 wayland-server xkbcommon cairo pangocairo) -lm"
gcc $cflags -fPIC -fvisibility=hidden -shared -Wl,-soname,libluxcomp.so.0 -o "$b/libluxcomp.so.0" \
  "$comp"/lib/*.c $libs
ln -sf libluxcomp.so.0 "$b/libluxcomp.so"
gcc $cflags -o "$b/luxcomp-demo" "$comp/tests/demo.c" -L"$b" -lluxcomp -Wl,-rpath-link,"$sysroot/usr/lib"
# luxwm: LSL vedle luxos_tokens.lsl (moduly se hledaji vedle zdroje)
cp "$root"/packages/luxwm/*.lsl "$root"/packages/luxos-desktop/files/lsl/luxos_tokens.lsl "$b/src/"
if [[ -f $b/src/luxwm.lsl ]]; then
  # luxir hleda knihovny jen v systemovych adresarich: libluxcomp podstrcit v soukromem mount namespace
  unshare -rm sh -c "mount --bind \"$b\" /usr/local/lib && lslc --target linux-x86_64-gnu \"$b/src/luxwm.lsl\" \"$b/luxwm\""
fi
echo "$b"
