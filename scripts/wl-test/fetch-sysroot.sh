#!/bin/bash
# Stahne pripnute balicky z packages.lock (labwc, wlroots 0.20, grim, wlr-randr a zavislosti)
# z archive.archlinux.org, overi sha256 a rozbali je do $WLT_OUT/sysroot.
# Na hostiteli nic neinstaluje; wlt pouzije sysroot pres PATH a LD_LIBRARY_PATH.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
out=${WLT_OUT:-$(readlink -f "$here/../..")/out/wl-test}
cache=$out/pkgcache
root=$out/sysroot
mkdir -p "$cache"

while read -r name file sum; do
    [[ -z $name || $name == \#* ]] && continue
    f=$cache/$file
    if [[ ! -f $f ]] || ! sha256sum --status -c <<<"$sum  $f"; then
        curl -fsSL --retry 3 -o "$f.part" "https://archive.archlinux.org/packages/${name:0:1}/$name/$file"
        mv "$f.part" "$f"
    fi
    sha256sum --status -c <<<"$sum  $f" || { echo "sha256 mismatch: $file" >&2; rm -f "$f"; exit 1; }
done <"$here/packages.lock"

rm -rf "$root.new"
mkdir -p "$root.new"
while read -r name file sum; do
    [[ -z $name || $name == \#* ]] && continue
    tar --zstd -xf "$cache/$file" -C "$root.new" --exclude='.PKGINFO' --exclude='.BUILDINFO' \
        --exclude='.MTREE' --exclude='.INSTALL' usr etc 2>/dev/null || true
done <"$here/packages.lock"
[[ -x $root.new/usr/bin/labwc && -e $root.new/usr/lib/libwlroots-0.20.so ]] \
    || { echo "sysroot incomplete" >&2; exit 1; }
rm -rf "$root"
mv "$root.new" "$root"
echo "$root"
