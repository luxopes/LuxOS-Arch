#!/bin/bash
# LuxOS - testy rozhodovani luxos-tmp-setup (/tmp na disk) bez roota: fstab, stav a /etc/systemd jsou
# v docasnem koreni, koren systemu urcuje LUXOS_TMP_ROOTINFO. Skutecny subvolume a start overuje VM.
#   bash packages/luxos-tweaks/tests/test-tmp.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
S=$HERE/../files/tmp/luxos-tmp-setup
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAIL=0
ok() { if "$@"; then echo "ok    $DESC"; else echo "FAIL  $DESC"; FAIL=$((FAIL + 1)); fi; }
has() { [[ $1 == *"$2"* ]]; }
fresh() { rm -rf "$T/r"; mkdir -p "$T/r/etc"; printf '%s\n' "$@" >"$T/r/etc/fstab"; }
run() { LUXOS_TMP_ROOT=$T/r LUXOS_TMP_FORCE=1 LUXOS_TMP_ROOTINFO=$1 bash "$S" ${2-} 2>&1; }

LUX_ROOT='UUID=abcd	/	btrfs	rw,noatime,compress=zstd:1,ssd,discard=async,space_cache=v2,subvol=/@	0 0'
LUX_HOME='UUID=abcd	/home	btrfs	rw,noatime,compress=zstd:1,ssd,discard=async,space_cache=v2,subvol=/@home	0 0'
LUX_INFO='btrfs /dev/mapper/cryptroot[/@] rw,noatime,compress=zstd:1,ssd,discard=async,space_cache=v2,subvolid=256,subvol=/@'

echo "## btrfs (instalace LuxOS)"
fresh "# /etc/fstab" "$LUX_ROOT" "$LUX_HOME"
out=$(run "$LUX_INFO" --dry-run); rc=$?
DESC="subvol=@: navrh @tmp, konec s 0"; ok test $rc -eq 0
DESC="fstab radek: stejny zdroj, volby korene bez subvol/rw + nodev,nosuid,subvol=/@tmp"
ok has "$out" "UUID=abcd /tmp btrfs noatime,compress=zstd:1,ssd,discard=async,space_cache=v2,nodev,nosuid,subvol=/@tmp 0 0"
DESC="zarizeni pro subvolume bez [/@]"; ok has "$out" "on /dev/mapper/cryptroot "
DESC="--dry-run nic nezapise"; ok test ! -e "$T/r/var/lib/luxos/tmp-on-disk" -a "$(grep -c /tmp "$T/r/etc/fstab")" = 0
fresh "$LUX_ROOT"
out=$(run "btrfs /dev/vda2[/@] rw,subvol=/@" ); rc=$?
DESC="skutecny beh bez blokoveho zarizeni: nic nezmeni, konec s 0"
ok test $rc -eq 0 -a ! -e "$T/r/var/lib/luxos/tmp-on-disk" -a "$(grep -c /tmp "$T/r/etc/fstab")" = 0
DESC="... a rekne proc"; ok has "$out" "not found"

echo "## uz vyreseno"
fresh "$LUX_ROOT" "/dev/mapper/luxos-tmp /tmp ext4 noatime,nosuid,nodev 0 2"
out=$(run "$LUX_INFO")
DESC="vlastni /tmp ve fstab: nic, stav fstab"; ok grep -qx method=fstab "$T/r/var/lib/luxos/tmp-on-disk"
fresh "$LUX_ROOT" "tmpfs /tmp/ tmpfs size=2G 0 0"
out=$(run "$LUX_INFO")
DESC="tmpfs /tmp/ ve fstab (spravce): nic"; ok grep -qx method=fstab "$T/r/var/lib/luxos/tmp-on-disk"
fresh "$LUX_ROOT" "#UUID=x /tmp btrfs subvol=/@tmp 0 0"
out=$(run "$LUX_INFO" --dry-run)
DESC="zakomentovany radek /tmp se nepocita"; ok has "$out" "would create subvolume @tmp"
fresh "$LUX_ROOT"; mkdir -p "$T/r/etc/systemd/system"; ln -s /dev/null "$T/r/etc/systemd/system/tmp.mount"
out=$(run "$LUX_INFO")
DESC="tmp.mount v /etc (spravce): nic, stav custom"; ok grep -qx method=custom "$T/r/var/lib/luxos/tmp-on-disk"
out=$(run "$LUX_INFO" --dry-run)
DESC="se zaznamem o hotovem prechodu: nic, ani hlaseni"; ok test -z "$out"

echo "## ostatni koreny"
fresh "UUID=e / ext4 rw,relatime 0 1"
out=$(run "ext4 /dev/sda2 rw,relatime"); rc=$?
DESC="ext4: maska tmp.mount -> /dev/null"; ok test "$(readlink "$T/r/etc/systemd/system/tmp.mount")" = /dev/null
DESC="ext4: stav mask"; ok grep -qx method=mask "$T/r/var/lib/luxos/tmp-on-disk"
out=$(run "ext4 /dev/sda2 rw,relatime")
DESC="opakovany beh: maska zustane"; ok test -L "$T/r/etc/systemd/system/tmp.mount"
echo "/dev/sdb1 /tmp ext4 defaults 0 2" >>"$T/r/etc/fstab"
out=$(run "ext4 /dev/sda2 rw,relatime")
DESC="pozdeji /tmp ve fstab: maska LuxOS pryc (jinak by vypnula pripojeni z fstab)"
ok test ! -e "$T/r/etc/systemd/system/tmp.mount" -a ! -L "$T/r/etc/systemd/system/tmp.mount"
DESC="... stav fstab"; ok grep -qx method=fstab "$T/r/var/lib/luxos/tmp-on-disk"
fresh "UUID=b / btrfs rw,noatime 0 0"
out=$(run "btrfs /dev/sda2 rw,noatime,subvolid=5,subvol=/" --dry-run)
DESC="btrfs bez subvolumu (nejvyssi uroven): maska, ne @tmp"; ok has "$out" "would mask tmp.mount"
fresh
out=$(run "overlay airootfs rw,lowerdir=/x"); rc=$?
DESC="overlay (live ISO): nic, bez stavu"; ok test $rc -eq 0 -a ! -e "$T/r/var/lib/luxos/tmp-on-disk" -a ! -L "$T/r/etc/systemd/system/tmp.mount"
out=$(run "" ); rc=$?
DESC="neznamy koren: nic, konec s 0"; ok test $rc -eq 0 -a ! -e "$T/r/var/lib/luxos/tmp-on-disk"
fresh "$LUX_ROOT"
out=$(run "btrfs /dev/vda2[/@snapshots/2026-11-01_10-00-00] ro,subvol=/@snapshots/2026-11-01_10-00-00" --dry-run)
DESC="koren ve snimku: nic"; ok test -z "$out" -a ! -e "$T/r/var/lib/luxos/tmp-on-disk"

echo "## bez roota a v chrootu"
fresh "$LUX_ROOT"
if ((EUID != 0)); then
    out=$(LUXOS_TMP_ROOT=$T/r LUXOS_TMP_ROOTINFO=$LUX_INFO bash "$S" 2>&1); rc=$?
    DESC="bez roota: nic, konec s 0"; ok test $rc -eq 0 -a -z "$out" -a ! -e "$T/r/var/lib/luxos/tmp-on-disk"
fi

echo "## tmpfiles"
C=$HERE/../files/tmp/luxos-tmp.conf
DESC="D /tmp 1777 root root 10d"; ok grep -qx 'D /tmp 1777 root root 10d' "$C"
DESC="jmeno pred tmp.conf systemd (prednost)"; ok test "luxos-tmp.conf" \< "tmp.conf"

echo
echo "Vysledek: $FAIL FAIL"
exit $((FAIL > 0))
