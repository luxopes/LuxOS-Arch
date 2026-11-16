#!/bin/bash
# Doplnek mkarchiso (scripts/mkarchiso-luxos.sh) s napodobenymi funkcemi mkarchiso:
# /etc/.updated a /var/.updated se stejnym casem jako /usr (live ISO bez ldconfig pri kazdem startu,
# audit 1.0.2: ldconfig.service 7,8 s pred basic.target), popisek EFI oddilu LUXOS (mlabel, je-li).
#   bash scripts/tests/test-mkarchiso-luxos.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
fail=0
ok() { if "${@:2}"; then echo "ok    $1"; else echo "FAIL  $1"; fail=1; fi; }

pacstrap_dir=$T/root
mkdir -p "$pacstrap_dir"/{etc,var,usr/lib}
touch -d '2026-11-16 07:25:58' "$pacstrap_dir/usr"
_msg_info() { :; }
_msg_warning() { echo "WARN $*" >>"$T/warn"; }
_prepare_airootfs_image() { echo "orig-prepare $*" >>"$T/calls"; }
_make_efibootimg() { echo "orig-efi" >>"$T/calls"; }
mlabel() { echo "mlabel $*" >>"$T/calls"; }
efibootimg=$T/efiboot.img
. "$HERE/../mkarchiso-luxos.sh"

_prepare_airootfs_image airootfs
for d in etc var; do
    ok "$d/.updated existuje" test -f "$pacstrap_dir/$d/.updated"
    ok "$d/.updated ma cas /usr (ConditionNeedsUpdate nesplnena)" \
        test "$(stat -c %Y "$pacstrap_dir/$d/.updated")" = "$(stat -c %Y "$pacstrap_dir/usr")"
done
ok "puvodni _prepare_airootfs_image zavolana s argumenty" grep -qx 'orig-prepare airootfs' "$T/calls"
_make_efibootimg
ok "puvodni _make_efibootimg zavolana" grep -qx 'orig-efi' "$T/calls"
ok "popisek EFI LUXOS" grep -qx "mlabel -i $efibootimg ::LUXOS" "$T/calls"
ok "popisek az po vytvoreni obrazu" test "$(grep -n orig-efi "$T/calls" | cut -d: -f1)" -lt "$(grep -n mlabel "$T/calls" | cut -d: -f1)"

# container-build.sh: doplnek se pridava do kopie mkarchiso vzdy (i bez Secure Boot)
cb=$HERE/../container-build.sh
ok "container-build: mkarchiso-luxos.sh vzdy" grep -q 'local -a add=("$ROOT/scripts/mkarchiso-luxos.sh")' "$cb"
exit $fail
