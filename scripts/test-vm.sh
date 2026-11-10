#!/bin/bash
# LuxOS - spusteni ISO nebo nainstalovaneho systemu v QEMU/KVM
#   (LUXOS_VM_DIR, LUXOS_VM_MEM, LUXOS_VM_MEMFILE, LUXOS_VM_ISO, LUXOS_VM_NAME, LUXOS_VM_OUTPUTS, LUXOS_VM_VGA)
#   LUXOS_VM_VGA=VGA: standardni graficka karta (virtio-vga se po uspani S3 zasekne)
#   LUXOS_VM_VNC=N: cislo displeje VNC pro --headless (vychozi 7 = 127.0.0.1:5907)
#   LUXOS_VM_SERIAL=SOUBOR: seriova konzole do souboru (zaznam startu, napr. hlasky shim/OVMF)
#
#   scripts/test-vm.sh live      [--headless] [--bios] [--secureboot]   boot z ISO (+ prazdny disk 40G)
#   scripts/test-vm.sh disk      [--headless] [--bios] [--secureboot]   boot z nainstalovaneho disku
#
#   --secureboot: OVMF se Secure Boot (SMM) a klici Microsoftu jako bezny pocitac s Windows.
#   Promenne UEFI (prvni spusteni): LUXOS_VM_SB_VARS=soubor (napr. z virt-fw-vars --enroll-microsoft
#   --microsoft-db all --microsoft-kek all --sb), jinak je vytvori virt-fw-vars (balik virt-firmware).
#   Ulozene v $LUXOS_VM_DIR/OVMF_VARS.fd - zapsany klic MOK tam zustava jako na skutecnem pocitaci.
#   scripts/test-vm.sh reset                             smazat testovaci disk
#
# Ovladani bezici VM: scripts/vmctl.py (screenshot, prikazy pres guest agenta, klavesy)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

T=${LUXOS_VM_DIR:-out/test}
mode=${1:-live}; shift || true
headless=0 bios=0 sb=0
for a in "$@"; do
    case $a in --headless) headless=1 ;; --bios) bios=1 ;; --secureboot) sb=1 ;; esac
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
[[ -n ${LUXOS_VM_SERIAL-} ]] && args+=(-serial "file:$LUXOS_VM_SERIAL")
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
    if ((sb)); then
        # Secure Boot: kod OVMF se SMM (promenne chranene pred OS), stroj q35 s SMM
        code=/usr/share/OVMF/OVMF_CODE_4M.secboot.fd
        [[ -f $code ]] || code=/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd
        [[ -f $code ]] || { echo "No OVMF with Secure Boot (edk2-ovmf: OVMF_CODE.secboot.4m.fd)" >&2; exit 1; }
        if [[ ! -f $T/OVMF_VARS.fd ]]; then
            if [[ -n ${LUXOS_VM_SB_VARS-} ]]; then
                cp "$LUXOS_VM_SB_VARS" "$T/OVMF_VARS.fd"
            elif command -v virt-fw-vars >/dev/null; then
                virt-fw-vars -i "$vars" -o "$T/OVMF_VARS.fd" --enroll-microsoft \
                    --microsoft-db all --microsoft-kek all --sb >/dev/null
            else
                echo "Secure Boot needs UEFI variables with Microsoft keys: set LUXOS_VM_SB_VARS or install virt-firmware" >&2
                exit 1
            fi
        fi
        args+=(-machine smm=on -global driver=cfi.pflash01,property=secure,value=on -global ICH9-LPC.disable_s3=1)
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
if ((headless)); then args+=(-display none -vnc "127.0.0.1:${LUXOS_VM_VNC:-7}"); else args+=(-display gtk,zoom-to-fit=on); fi

rm -f "$T/qga.sock" "$T/qmp.sock"
exec qemu-system-x86_64 "${args[@]}"
