#!/bin/bash
# LuxOS 1.1.0 - nahled desktopu na Waylandu v QEMU (okno QEMU, nic nebezi v relaci hostitele).
#   ./start.sh            -vga std (bochs-drm, bez 3D)
#   ./start.sh --virtio   virtio-vga bez virgl (taky bez 3D)
#   ./start.sh --reset    smazat zmeny (disk.qcow2) a zacit znovu od cisteho obrazu
#   ./start.sh --headless bez okna (testy: QMP qmp.sock, guest agent qga.sock, snimky pres screendump)
# Zmeny se ukladaji do disk.qcow2 nad base.qcow2; base.qcow2 se nikdy nemeni.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
vga=(-vga std) display=(-display gtk,zoom-to-fit=on)
for a in "$@"; do
    case $a in
        --reset) rm -f disk.qcow2; echo "Reset: disk.qcow2 deleted." ;;
        --virtio) vga=(-vga none -device virtio-vga) ;;
        --headless) display=(-display none) ;;
        *) echo "Unknown option '$a' (--virtio, --reset, --headless)" >&2; exit 2 ;;
    esac
done
[[ $* == --reset ]] && exit 0   # jen reset, nespoustet
[[ -f disk.qcow2 ]] || qemu-img create -q -f qcow2 -F qcow2 -b base.qcow2 disk.qcow2
# pamet VM pod stropem (QEMU + 6 GB hosta), at pripadny unik nesezere hostitele
scope=()
command -v systemd-run >/dev/null && scope=(systemd-run --user --scope -q -p MemoryMax=7G -p MemorySwapMax=0 --)
exec "${scope[@]}" qemu-system-x86_64 -name "LuxOS Wayland preview" \
    -enable-kvm -machine q35 -cpu host -smp 4 -m 6G \
    -kernel vmlinuz -initrd initramfs.img -append "root=/dev/vda rw quiet loglevel=3" \
    -drive file=disk.qcow2,if=virtio,format=qcow2,discard=unmap \
    "${vga[@]}" "${display[@]}" \
    -netdev user,id=n0 -device virtio-net-pci,netdev=n0,romfile= -device qemu-xhci -device usb-tablet \
    -device virtio-serial -chardev socket,path=qga.sock,server=on,wait=off,id=qga0 \
    -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0 \
    -qmp unix:qmp.sock,server=on,wait=off -qmp unix:qmp2.sock,server=on,wait=off
