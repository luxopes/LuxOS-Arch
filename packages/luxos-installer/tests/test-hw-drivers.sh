#!/bin/bash
# LuxOS installer - test kroku ovladacu (install_packages + install_online_drivers) BEZ roota a disku.
# Funkce se vyjmou z luxos-install a spusti s nahradami pacstrap/arch-chroot; luxos-hwdetect bezi
# skutecny nad falesnym /sys (LUXOS_HW_ROOT). Kontroluje se, co jde do pacstrap, co se stahuje
# az z online [luxos] (legacy NVIDIA nejsou v ISO), NVIDIA_EARLY a chovani pri chybe site.
#
#   packages/luxos-installer/tests/test-hw-drivers.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
FILES=$HERE/../files
DRIVERS=$(cd "$HERE/../../luxos-drivers" && pwd)
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
NPASS=0 NFAIL=0
ok()  { NPASS=$((NPASS + 1)); printf 'ok    %s\n' "$1"; }
bad() { NFAIL=$((NFAIL + 1)); printf 'FAIL  %s\n' "$1"; [[ -n ${2-} ]] && printf '      %s\n' "$2"; return 0; }

# Funkce z instalatoru (bez spusteni main)
extract() { sed -n "/^$1() {/,/^}/p" "$FILES/luxos-install"; }
eval "$(extract install_packages)"
eval "$(extract install_online_drivers)"
grep -q 'install_online_drivers' <<<"$(extract install_packages)" && ok "pacstrap step calls install_online_drivers" \
    || bad "install_online_drivers is not called"

# --- Nahrady prostredi instalatoru ---
# shellcheck disable=SC2059
T() { local f=$1; shift; printf -- "$f" "$@"; }
step() { :; }; progress() { :; }; info() { echo "INFO $*" >>"$OUT/log"; }
rank_mirrors() { :; }; pac_cleanup() { :; }; wait_internet() { :; }; sleep() { :; }
pac_filter() { cat >/dev/null; }
layout_packages() { :; }
install_engine_config() { :; }                     # kopie lux.conf a zrcadel do cile
engine_shim() { ENGINE_SHIM=$OUT/shim; }
LUX_CONFIG_TOOL=$OUT/lux-config                     # lux-config ensure -> konfigurace jadra live systemu
printf '#!/bin/sh\necho /run/lux/engine.conf\n' >"$LUX_CONFIG_TOOL"; chmod +x "$LUX_CONFIG_TOOL"
pacstrap() { printf '%s\n' "$@" >"$OUT/pacstrap"; printf '%s\n' "$PATH" >"$OUT/pacstrap.path"; return "${PACSTRAP_RC:-0}"; }
chroot_engine() { printf '%s\n' "$@" >>"$OUT/chroot"; return "${CHROOT_RC:-0}"; }
fail() { echo "FAIL-CALLED $*" >>"$OUT/log"; return 1; }
# Skutecny luxos-hwdetect z repozitare misto prikazu v PATH
eval 'luxos-hwdetect() { "$DRIVERS/luxos-hwdetect" "$@"; }'
export DRIVERS
export LUXOS_HW_DATA=$DRIVERS LUXOS_HW_VIRT=none
SHARE=$OUT/share; mkdir -p "$SHARE"; printf 'base\nlinux-luxos\n' >"$SHARE/packages"
# shellcheck disable=SC2034  # cte je vyjmuta install_packages
BOOTLOADER=auto BOOTMODE=uefi DISK_MODE=erase TARGET=$OUT/target

machine() {  # machine "slot trida vendor device"...
    export LUXOS_HW_ROOT=$OUT/root
    rm -rf "$LUXOS_HW_ROOT" "$OUT/pacstrap" "$OUT/chroot" "$OUT/log"
    mkdir -p "$LUXOS_HW_ROOT/sys/bus/pci/devices"
    local e slot c v d
    for e in "$@"; do
        read -r slot c v d <<<"$e"
        mkdir -p "$LUXOS_HW_ROOT/sys/bus/pci/devices/$slot"
        echo "0x$c" >"$LUXOS_HW_ROOT/sys/bus/pci/devices/$slot/class"
        echo "0x$v" >"$LUXOS_HW_ROOT/sys/bus/pci/devices/$slot/vendor"
        echo "0x$d" >"$LUXOS_HW_ROOT/sys/bus/pci/devices/$slot/device"
    done
}
in_file() { grep -qxF -- "$2" "$OUT/$1" 2>/dev/null; }
check() {  # check popis podminka...
    local d=$1; shift
    if "$@"; then ok "$d"; else bad "$d"; fi
}

# --- Turing+ (nvidia-open z [extra]) -> vse v pacstrap, early KMS bez iGPU ---
machine "0000:01:00.0 030000 10de 2684"
install_packages >/dev/null 2>&1
check "open: nvidia-open-dkms in pacstrap" in_file pacstrap nvidia-open-dkms
check "open: headers in pacstrap" in_file pacstrap linux-luxos-headers
check "open: nothing downloaded online" test ! -e "$OUT/chroot"
check "open: NVIDIA_EARLY=1 without iGPU" test "$NVIDIA_EARLY" = 1
check "pacstrap uses the engine config of the live system" bash -c "grep -A1 -x -- -C '$OUT/pacstrap' | grep -qx /run/lux/engine.conf"
check "pacstrap does not copy a mirror list (-M)" in_file pacstrap -M
check "pacstrap gets the engine tools under Arch names (shim first in PATH)" bash -c "grep -q '^$OUT/shim:' '$OUT/pacstrap.path'"

# --- Pascal (580xx z online [luxos]) ---
machine "0000:01:00.0 030000 10de 1c03"
install_packages >/dev/null 2>&1
check "580: dkms not in pacstrap" bash -c "! grep -qx nvidia-580xx-dkms '$OUT/pacstrap'"
check "580: headers in pacstrap (DKMS builds in the second step)" in_file pacstrap linux-luxos-headers
check "580: libva-nvidia-driver in pacstrap" in_file pacstrap libva-nvidia-driver
check "580: online -Syy" in_file chroot -Syy
check "580: dkms online" in_file chroot nvidia-580xx-dkms
check "580: utils online" in_file chroot nvidia-580xx-utils
check "580: NVIDIA_EARLY=1" test "$NVIDIA_EARLY" = 1

# --- Hybridni Pascal: nvidia-prime musi jit spolu s 580xx (jinak pacstrap pritahne nvidia-utils) ---
machine "0000:00:02.0 030000 8086 591b" "0000:01:00.0 030200 10de 1c8d"
install_packages >/dev/null 2>&1
check "hybrid 580: prime not in pacstrap" bash -c "! grep -qx nvidia-prime '$OUT/pacstrap'"
check "hybrid 580: prime online" in_file chroot nvidia-prime
check "hybrid 580: NVIDIA_EARLY=0 with iGPU" test "$NVIDIA_EARLY" = 0
check "hybrid 580: intel driver in pacstrap" in_file pacstrap vulkan-intel

# --- Hybridni Turing: prime z [extra] v pacstrap ---
machine "0000:00:02.0 030000 8086 46a6" "0000:01:00.0 030200 10de 2520"
install_packages >/dev/null 2>&1
check "hybrid open: prime in pacstrap" in_file pacstrap nvidia-prime
check "hybrid open: nothing online" test ! -e "$OUT/chroot"

# --- Kepler: nouveau, nic online ---
machine "0000:01:00.0 030000 10de 1180"
install_packages >/dev/null 2>&1
check "kepler: vulkan-nouveau in pacstrap" in_file pacstrap vulkan-nouveau
check "kepler: nothing online" test ! -e "$OUT/chroot"
check "kepler: NVIDIA_EARLY=0" test "$NVIDIA_EARLY" = 0

# --- Online stahovani selze: instalace pokracuje, bez early KMS, s vysvetlenim ---
machine "0000:01:00.0 030000 10de 1c03"
CHROOT_RC=1 install_packages >/dev/null 2>&1; rc=$?
check "580 offline: install continues" test "$rc" = 0
check "580 offline: five attempts" test "$(grep -cx -- -Syy "$OUT/chroot")" = 5
check "580 offline: NVIDIA_EARLY reset" test "$NVIDIA_EARLY" = 0
check "580 offline: user is told" grep -q "Drivers" "$OUT/log"
check "580 offline: fail not called" bash -c "! grep -q FAIL-CALLED '$OUT/log'"

# --- Balik chybi v repozitari ISO: hned srozumitelna chyba, ne 5 pokusu a "zkontrolujte internet" ---
machine "0000:00:02.0 030000 8086 9a49"
LOG=$OUT/install.log; : >"$LOG"
pac_filter() { cat >>"$LOG"; }
pacstrap() { echo "attempt" >>"$OUT/attempts"; echo "error: target not found: linux-luxos-headers"; return 1; }
rm -f "$OUT/attempts"
install_packages >/dev/null 2>&1
check "missing package: one attempt only" test "$(wc -l <"$OUT/attempts")" = 1
check "missing package: names the package" grep -q "FAIL-CALLED .*missing packages: linux-luxos-headers" "$OUT/log"
check "missing package: no internet advice" bash -c "! grep -q 'Check the internet' '$OUT/log'"

# --- setup-chroot: early KMS pozna i legacy DKMS ---
pat=$(grep -o "grep -xE '[^']*'" "$FILES/setup-chroot.sh" | head -1 | sed "s/grep -xE //; s/'//g")
for p in nvidia-open-dkms nvidia-580xx-dkms nvidia-470xx-dkms; do
    check "setup-chroot early KMS matches $p" bash -c "printf 'base\n%s\n' $p | grep -qxE '$pat'"
done
check "setup-chroot early KMS ignores nvidia-utils" bash -c "! printf 'nvidia-utils\nlibva-nvidia-driver\n' | grep -qxE '$pat'"

printf '\n%d ok, %d failed\n' "$NPASS" "$NFAIL"
exit "$NFAIL"
