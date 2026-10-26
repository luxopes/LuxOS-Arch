#!/bin/bash
# LuxOS - laborator Active Directory v QEMU: radic domeny (Samba AD DC) a klient LuxOS
#
#   scripts/vm-tests/domain/vm-ad.sh base DISK.qcow2      zakladni disk = nainstalovany LuxOS
#                                                          (napr. out/test/disk.qcow2 po instalaci)
#   scripts/vm-tests/domain/vm-ad.sh dc     [--headless]   spusti radic domeny (overlay disku)
#   scripts/vm-tests/domain/vm-ad.sh client [--headless]   spusti klienta LuxOS (overlay disku)
#   scripts/vm-tests/domain/vm-ad.sh reset                 smaze overlaye (zaklad zustane)
#
# Sit bez root prav: kazda VM ma 2 karty -
#   net0: user-mode NAT (internet, instalace samba na DC),
#   net1: soukromy L2 segment mezi VM (QEMU socket multicast 230.0.0.77:12377), adresy 10.77.0.0/24
#         nastavi provision-dc.sh (DC 10.77.0.1, DNS domeny) a setup-client.sh (klient 10.77.0.10).
# Ovladani: LUXOS_VM_DIR=out/test-ad/dc scripts/vmctl.py exec '...' (guest agent, QMP).
# Spoustet jen rucne nebo z run-scenarios.sh; nikdy proti skutecne domene ani mimo laborator.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/../../.."

LAB=${LUXOS_AD_LAB:-out/test-ad}
MCAST=${LUXOS_AD_MCAST:-230.0.0.77:12377}
role=${1:-}; shift || true
headless=0
for a in "$@"; do [[ $a == --headless ]] && headless=1; done
mkdir -p "$LAB"

case $role in
    base)
        [[ -f ${1-} ]] || { echo "Usage: vm-ad.sh base DISK.qcow2 (installed LuxOS)" >&2; exit 2; }
        ln -sfn "$(readlink -f "$1")" "$LAB/base.qcow2"
        echo "Base disk: $(readlink -f "$1")"; exit 0 ;;
    reset)
        rm -rf "$LAB/dc" "$LAB/client"; echo "Overlays removed."; exit 0 ;;
    dc|client) ;;
    *) sed -n '2,15p' "$0"; exit 2 ;;
esac

[[ -e $LAB/base.qcow2 ]] || { echo "Set the base disk first: vm-ad.sh base out/test/disk.qcow2" >&2; exit 1; }
T=$LAB/$role
mkdir -p "$T"
# overlay: zaklad se nikdy nemeni, kazda VM ma vlastni zmeny (reset = smazat overlay)
[[ -f $T/disk.qcow2 ]] || qemu-img create -f qcow2 -F qcow2 -b "$(readlink -f "$LAB/base.qcow2")" "$T/disk.qcow2" >/dev/null
[[ -f $T/OVMF_VARS.fd ]] || cp /usr/share/OVMF/OVMF_VARS_4M.fd "$T/OVMF_VARS.fd"

if [[ $role == dc ]]; then mac1=52:54:00:77:00:01 mac0=52:54:00:77:01:01 mem=2048 vnc=17
else mac1=52:54:00:77:00:10 mac0=52:54:00:77:01:10 mem=4096 vnc=18; fi

args=(
    -name "LuxOS AD lab: $role" -enable-kvm -machine q35 -cpu host -smp 2 -m "$mem"
    -drive file="$T/disk.qcow2",if=none,id=hd0,discard=unmap,cache=unsafe -device virtio-blk-pci,drive=hd0,bootindex=1
    -netdev user,id=net0 -device virtio-net-pci,netdev=net0,mac=$mac0
    -netdev socket,id=net1,mcast="$MCAST" -device virtio-net-pci,netdev=net1,mac=$mac1
    -device virtio-vga -device qemu-xhci -device usb-tablet
    -chardev socket,path="$T/qga.sock",server=on,wait=off,id=qga0
    -device virtio-serial -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0
    -qmp unix:"$T/qmp.sock",server=on,wait=off
    -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd
    -drive if=pflash,format=raw,file="$T/OVMF_VARS.fd"
)
if ((headless)); then args+=(-display none -vnc "127.0.0.1:$vnc"); else args+=(-display gtk,zoom-to-fit=on); fi
rm -f "$T/qga.sock" "$T/qmp.sock"
exec qemu-system-x86_64 "${args[@]}"
