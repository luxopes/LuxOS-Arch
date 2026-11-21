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
mkdir -p "$b/proto"
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
  $(pkg-config --cflags wlroots-0.20 wayland-server xkbcommon libinput libdrm pixman-1 cairo pangocairo)"
libs="$(pkg-config --libs wlroots-0.20 wayland-server xkbcommon libinput cairo pangocairo) -lm"
gcc $cflags -fPIC -fvisibility=hidden -shared -Wl,-soname,libluxcomp.so.0 -o "$b/libluxcomp.so.0" \
  "$comp"/lib/*.c $libs
ln -sf libluxcomp.so.0 "$b/libluxcomp.so"
gcc $cflags -o "$b/luxcomp-demo" "$comp/tests/demo.c" -L"$b" -lluxcomp -Wl,-rpath-link,"$sysroot/usr/lib"
# luxwm: vazba a tokeny vzhledu (luxos-desktop) jako systemove bindingy LSL
lsl=$root/packages/luxwm
if [[ -f $lsl/luxwm.lsl ]]; then
  # luxir hleda knihovny jen v systemovych adresarich: libluxcomp podstrcit v soukromem mount namespace
  unshare -rm sh -c "mount --bind \"$b\" /usr/local/lib && lslc --target linux-x86_64-gnu --system-bindings \"$lsl\" \
    --system-bindings \"$root/packages/luxos-desktop/files/lsl\" \"$lsl/luxwm.lsl\" \"$b/luxwm\""
  lslc --target linux-x86_64-gnu --system-bindings "$lsl" --system-bindings "$root/packages/luxos-desktop/files/lsl" \
    "$lsl/luxwm-msg.lsl" "$b/luxwm-msg"
fi
echo "$b"
