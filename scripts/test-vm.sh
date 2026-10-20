#!/bin/bash
# LuxOS - spusteni ISO nebo nainstalovaneho systemu v QEMU/KVM
#
#   scripts/test-vm.sh live      [--headless] [--bios]   boot z ISO (+ prazdny disk 40G)
#   scripts/test-vm.sh disk      [--headless] [--bios]   boot z nainstalovaneho disku
#   scripts/test-vm.sh reset                             smazat testovaci disk
#
# Ovladani bezici VM: scripts/vmctl.py (screenshot, prikazy pres guest agenta, klavesy)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

T=out/test
mode=${1:-live}; shift || true
headless=0 bios=0
for a in "$@"; do
    case $a in --headless) headless=1 ;; --bios) bios=1 ;; esac
done

mkdir -p "$T"
if [[ $mode == reset ]]; then rm -f "$T"/disk.qcow2 "$T"/OVMF_VARS.fd; echo "Reset."; exit 0; fi

iso=$(ls -t out/luxos-*.iso 2>/dev/null | head -1 || true)
[[ -f $T/disk.qcow2 ]] || qemu-img create -f qcow2 "$T/disk.qcow2" 40G >/dev/null

args=(
    -name LuxOS -enable-kvm -machine q35 -cpu host -smp 4 -m 4096
    -drive file="$T/disk.qcow2",if=virtio,discard=unmap,cache=unsafe
    -nic user,model=virtio-net-pci
    -device virtio-vga -device qemu-xhci -device usb-tablet
    -audiodev none,id=snd0 -device intel-hda -device hda-output,audiodev=snd0
    -chardev socket,path="$T/qga.sock",server=on,wait=off,id=qga0
    -device virtio-serial -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0
    -qmp unix:"$T/qmp.sock",server=on,wait=off
)
if ((!bios)); then
    code=/usr/share/OVMF/OVMF_CODE_4M.fd
    [[ -f $T/OVMF_VARS.fd ]] || cp /usr/share/OVMF/OVMF_VARS_4M.fd "$T/OVMF_VARS.fd"
    args+=(-drive if=pflash,format=raw,readonly=on,file="$code" -drive if=pflash,format=raw,file="$T/OVMF_VARS.fd")
fi
if [[ $mode == live ]]; then
    [[ -n $iso ]] || { echo "No ISO in out/ - run ./build.sh first" >&2; exit 1; }
    args+=(-cdrom "$iso" -boot order=d)
fi
if ((headless)); then args+=(-display none -vnc 127.0.0.1:7); else args+=(-display gtk,zoom-to-fit=on); fi

rm -f "$T/qga.sock" "$T/qmp.sock"
exec qemu-system-x86_64 "${args[@]}"
