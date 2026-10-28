#!/bin/bash
# LuxOS - spusteni ISO nebo nainstalovaneho systemu v QEMU/KVM
#   (LUXOS_VM_DIR, LUXOS_VM_MEM, LUXOS_VM_MEMFILE, LUXOS_VM_ISO, LUXOS_VM_NAME, LUXOS_VM_OUTPUTS, LUXOS_VM_VGA)
#   LUXOS_VM_VGA=VGA: standardni graficka karta (virtio-vga se po uspani S3 zasekne)
#
#   scripts/test-vm.sh live      [--headless] [--bios]   boot z ISO (+ prazdny disk 40G)
#   scripts/test-vm.sh disk      [--headless] [--bios]   boot z nainstalovaneho disku
#   scripts/test-vm.sh reset                             smazat testovaci disk
#
# Ovladani bezici VM: scripts/vmctl.py (screenshot, prikazy pres guest agenta, klavesy)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

T=${LUXOS_VM_DIR:-out/test}
mode=${1:-live}; shift || true
headless=0 bios=0
for a in "$@"; do
    case $a in --headless) headless=1 ;; --bios) bios=1 ;; esac
done

mkdir -p "$T"
if [[ $mode == reset ]]; then rm -f "$T"/disk.qcow2 "$T"/OVMF_VARS.fd; echo "Reset."; exit 0; fi

# LUXOS_VM_ISO: jine ISO (napr. Arch Linux pro porovnani), LUXOS_VM_NAME: nazev okna
iso=${LUXOS_VM_ISO:-$(ls -t out/luxos-*.iso 2>/dev/null | head -1 || true)}
[[ -f $T/disk.qcow2 ]] || qemu-img create -f qcow2 "$T/disk.qcow2" 40G >/dev/null

args=(
    -name "${LUXOS_VM_NAME:-LuxOS}" -enable-kvm -machine q35 -cpu host -smp 4 -m "${LUXOS_VM_MEM:-4096}"
    -drive file="$T/disk.qcow2",if=none,id=hd0,discard=unmap,cache=unsafe -device virtio-blk-pci,drive=hd0,bootindex=1
    -nic user,model=virtio-net-pci
    -device "${LUXOS_VM_VGA:-virtio-vga}${LUXOS_VM_OUTPUTS:+,max_outputs=$LUXOS_VM_OUTPUTS}" -device qemu-xhci -device usb-tablet
    -audiodev none,id=snd0 -device intel-hda -device hda-output,audiodev=snd0
    -chardev socket,path="$T/qga.sock",server=on,wait=off,id=qga0
    -device virtio-serial -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0
    -qmp unix:"$T/qmp.sock",server=on,wait=off
)
# LUXOS_VM_MEMFILE=cesta: pamet VM v souboru na disku (MAP_SHARED) - host s malo RAM ji muze
# odkladat do souboru misto swapu, earlyoom pak QEMU nezabije
if [[ -n ${LUXOS_VM_MEMFILE-} ]]; then
    args+=(-object "memory-backend-file,id=mem0,size=${LUXOS_VM_MEM:-4096}M,mem-path=$LUXOS_VM_MEMFILE,share=on"
           -machine memory-backend=mem0)
fi
if ((!bios)); then
    # Debian/Ubuntu: /usr/share/OVMF/*_4M.fd, Arch (edk2-ovmf): /usr/share/edk2/x64/*.4m.fd
    code=/usr/share/OVMF/OVMF_CODE_4M.fd vars=/usr/share/OVMF/OVMF_VARS_4M.fd
    if [[ ! -f $code ]]; then
        code=/usr/share/edk2/x64/OVMF_CODE.4m.fd vars=/usr/share/edk2/x64/OVMF_VARS.4m.fd
    fi
    [[ -f $T/OVMF_VARS.fd ]] || cp "$vars" "$T/OVMF_VARS.fd"
    args+=(-drive if=pflash,format=raw,readonly=on,file="$code" -drive if=pflash,format=raw,file="$T/OVMF_VARS.fd")
fi
if [[ $mode == live ]]; then
    [[ -n $iso ]] || { echo "No ISO in out/ - run ./build.sh first" >&2; exit 1; }
    # bootindex: UEFI jinak upredni nainstalovany system podle ulozenych NVRAM polozek
    args+=(-drive file="$iso",if=none,id=cd0,media=cdrom,readonly=on -device ide-cd,drive=cd0,bootindex=0)
fi
if ((!headless)) && ! qemu-system-x86_64 -display help 2>/dev/null | grep -qx gtk; then
    echo "QEMU has no window backend: install it with 'sudo lux install qemu-ui-gtk', or use --headless (VNC 127.0.0.1:5907)" >&2
    exit 1
fi
if ((headless)); then args+=(-display none -vnc 127.0.0.1:7); else args+=(-display gtk,zoom-to-fit=on); fi

rm -f "$T/qga.sock" "$T/qmp.sock"
exec qemu-system-x86_64 "${args[@]}"
