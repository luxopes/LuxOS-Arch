#!/bin/bash
# shellcheck disable=SC2015  # ok() nikdy neselze
# LuxOS - testy luxos-hwdetect nad falesnymi stromy /sys, /proc a /etc (bez rootu, bez hardwaru)
#   bash packages/luxos-drivers/tests/test-hwdetect.sh
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
HW=$HERE/../luxos-hwdetect
export LUXOS_HW_DATA=$HERE/..          # nvidia-legacy.ids z repozitare
export NO_COLOR=1
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0 tests=0

# --- Stavba falesneho pocitace --------------------------------------------------------
machine() {  # novy prazdny koren
    ROOT=$TMP/$1
    rm -rf "$ROOT"
    mkdir -p "$ROOT/sys/bus/pci/devices" "$ROOT/sys/bus/usb/devices" "$ROOT/proc" "$ROOT/etc"
    printf '[options]\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n' >"$ROOT/etc/pacman.conf"
    : >"$ROOT/proc/cpuinfo"
    unset LUXOS_HW_VIRT
}
pci() {  # pci SLOT TRIDA VENDOR DEVICE
    local d=$ROOT/sys/bus/pci/devices/$1
    mkdir -p "$d"
    echo "0x$2" >"$d/class"; echo "0x$3" >"$d/vendor"; echo "0x$4" >"$d/device"
}
usb() {  # usb JMENO VENDOR PRODUCT
    local d=$ROOT/sys/bus/usb/devices/$1
    mkdir -p "$d"
    echo "$2" >"$d/idVendor"; echo "$3" >"$d/idProduct"
}
cpu() { printf 'processor\t: 0\nvendor_id\t: %s\n' "$1" >"$ROOT/proc/cpuinfo"; }
battery() { mkdir -p "$ROOT/sys/class/power_supply/BAT0"; }
kernel() {  # kernel PKGBASE VERZE
    mkdir -p "$ROOT/usr/lib/modules/$2"
    echo "$1" >"$ROOT/usr/lib/modules/$2/pkgbase"
}
multilib() { printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >>"$ROOT/etc/pacman.conf"; }
pciids() {
    mkdir -p "$ROOT/usr/share/hwdata"
    printf '%s\n' '# test' '10de  NVIDIA Corporation' $'\t2684  AD102 [GeForce RTX 4090]' \
        $'\t1c03  GP106 [GeForce GTX 1060 6GB]' '8086  Intel Corporation' $'\t46a6  Alder Lake-P GT2 [Iris Xe Graphics]' \
        'C 00  Unclassified device' >"$ROOT/usr/share/hwdata/pci.ids"
}

hw() { LUXOS_HW_ROOT=$ROOT "$HW" "$@"; }

# --- Kontroly ------------------------------------------------------------------------
ok()   { tests=$((tests + 1)); }
bad()  { tests=$((tests + 1)); fails=$((fails + 1)); printf 'FAIL [%s] %s\n' "$CASE" "$*"; }
has()  { local p; for p in "$@"; do if grep -qxF -- "$p" <<<"$PK"; then ok; else bad "missing package $p"; fi; done; }
lacks(){ local p; for p in "$@"; do if grep -qxF -- "$p" <<<"$PK"; then bad "unexpected package $p"; else ok; fi; done; }
svc_has()  { local s; for s in "$@"; do if grep -qxF -- "$s" <<<"$SV"; then ok; else bad "missing service $s"; fi; done; }
svc_lacks(){ local s; for s in "$@"; do if grep -qxF -- "$s" <<<"$SV"; then bad "unexpected service $s"; else ok; fi; done; }
run_case() {  # run_case NAZEV [--kernel ...]
    CASE=$1; shift
    PK=$(hw --packages "$@") || bad "--packages exited non-zero"
    SV=$(hw --services "$@") || bad "--services exited non-zero"
    REP=$(hw --report "$@") || bad "--report exited non-zero"
    JS=$(hw --json "$@") || bad "--json exited non-zero"
    # JSON musi byt platny a jeho sjednoceni baliku = --packages
    if python3 -I -c 'import json,sys
d=json.loads(sys.argv[1])
assert d["version"]==1
pk=set(sys.argv[2].split())
assert set(d["packages"])==pk, (set(d["packages"])^pk)
dev=set()
for x in d["devices"]:
    assert x["id"] and x["kind"] and x["title"], x
    dev|=set(x["packages"])
assert dev==pk, (dev^pk)' "$JS" "$PK"; then ok; else bad "invalid JSON or JSON/--packages mismatch: $JS"; fi
}
report_has() { if grep -qF -- "$1" <<<"$REP"; then ok; else bad "report lacks: $1"; fi; }
json_py() {  # json_py 'vyraz nad d' - musi byt pravda
    if python3 -I -c 'import json,sys
d=json.loads(sys.argv[1])
dev={x["id"]:x for x in d["devices"]}
assert eval(sys.argv[2]), sys.argv[2]' "$JS" "$1" 2>/dev/null; then ok; else bad "json check failed: $1"; fi
}

# ==== Pripady =========================================================================
machine empty
run_case "empty machine"
[[ -z $PK ]] && ok || bad "packages on an empty machine: $PK"
[[ -z $SV ]] && ok || bad "services on an empty machine: $SV"
report_has "No special drivers needed"
json_py 'd["devices"]==[] and d["live"] is False and d["multilib"] is False'

# --- NVIDIA: open moduly (Turing, Ampere, Ada, Blackwell) ---
for g in "Turing 1e84" "Turing-GTX1650 1f82" "Ampere 2204" "Ada 2684" "Blackwell 2b85"; do
    machine "nv-${g% *}"; cpu AuthenticAMD; pci 0000:01:00.0 030000 10de "${g#* }"; kernel linux-zen 7.2.11-zen1-1-zen
    run_case "NVIDIA ${g% *}"
    has nvidia-open-dkms nvidia-utils nvidia-settings libva-nvidia-driver linux-zen-headers amd-ucode
    lacks nvidia-580xx-dkms vulkan-nouveau nvidia-prime lib32-nvidia-utils nvidia-470xx-dkms
    # 595+: uspani resi open moduly v jadre, sluzby nvidia-suspend se nezapinaji
    svc_lacks nvidia-suspend.service
    json_py 'dev["gpu-0000:01:00.0"]["module"]=="nvidia" and dev["gpu-0000:01:00.0"]["reboot"] is True'
done

# --- NVIDIA: 580xx (Maxwell, Pascal, Volta) ---
for g in "Maxwell-GTX970 13c2" "Maxwell-MX130 174d" "Pascal-GTX1060 1c03" "Pascal-GT1030 1d01" "Volta 1db6" "Maxwell-unknown 13ff"; do
    machine "nv-${g% *}"; cpu GenuineIntel; pci 0000:01:00.0 030000 10de "${g#* }"; kernel linux-zen 7.2.11-zen1-1-zen
    run_case "NVIDIA ${g% *}"
    has nvidia-580xx-dkms nvidia-580xx-utils libva-nvidia-driver linux-zen-headers intel-ucode
    lacks nvidia-open-dkms nvidia-utils nvidia-settings vulkan-nouveau thermald
    svc_has nvidia-suspend.service nvidia-resume.service nvidia-hibernate.service
    report_has "legacy NVIDIA 580 driver"
done

# --- NVIDIA: Kepler -> nouveau, 470xx jako volitelna moznost ---
for g in "Kepler-GTX680 1180" "Kepler-GT730 1287" "Kepler-GTX650 0fc6"; do
    machine "nv-${g% *}"; cpu GenuineIntel; pci 0000:01:00.0 030000 10de "${g#* }"; kernel linux-zen 7.2.11-zen1-1-zen
    run_case "NVIDIA ${g% *}"
    has vulkan-nouveau linux-firmware-nvidia
    lacks nvidia-470xx-dkms nvidia-open-dkms nvidia-580xx-dkms linux-zen-headers nvidia-utils
    report_has "nouveau"
    report_has "NVIDIA 470 legacy driver"
    json_py 'any(a["id"]=="nvidia-470xx" and "nvidia-470xx-dkms" in a["packages"] and "linux-zen-headers" in a["packages"] for a in dev["gpu-0000:01:00.0"]["alternatives"])'
done

# --- NVIDIA: Fermi a starsi -> nouveau bez alternativy ---
machine nv-fermi; cpu GenuineIntel; pci 0000:01:00.0 030000 10de 1200; kernel linux-zen 7.2.11-zen1-1-zen
run_case "NVIDIA Fermi"
has vulkan-nouveau; lacks nvidia-470xx-dkms nvidia-580xx-dkms nvidia-open-dkms linux-zen-headers
json_py 'dev["gpu-0000:01:00.0"]["alternatives"]==[]'

# --- Hybridni notebook Intel + NVIDIA Ampere ---
machine hybrid; cpu GenuineIntel; battery; pciids
pci 0000:00:02.0 030000 8086 46a6; pci 0000:01:00.0 030200 10de 2520; kernel linux-zen 7.2.11-zen1-1-zen
run_case "hybrid Intel + NVIDIA"
has nvidia-open-dkms nvidia-prime vulkan-intel intel-media-driver thermald intel-ucode
svc_has thermald.service
report_has "prime-run"
json_py 'dev["gpu-0000:00:02.0"]["title"]=="Intel Iris Xe Graphics"'

# --- Hybridni notebook Intel + NVIDIA Pascal (580xx + prime) ---
machine hybrid580; cpu GenuineIntel; battery
pci 0000:00:02.0 030000 8086 591b; pci 0000:01:00.0 030200 10de 1c8d; kernel linux-zen 7.2.11-zen1-1-zen
run_case "hybrid Intel + NVIDIA Pascal"
has nvidia-580xx-dkms nvidia-580xx-utils nvidia-prime vulkan-intel
lacks nvidia-utils

# --- Hybridni AMD + Kepler: prime jen v alternative 470 ---
machine hybrid470; cpu AuthenticAMD; pci 0000:05:00.0 030000 1002 1638; pci 0000:01:00.0 030200 10de 1292
run_case "hybrid AMD + NVIDIA Kepler"
lacks nvidia-prime
json_py '"nvidia-prime" in dev["gpu-0000:01:00.0"]["alternatives"][0]["packages"]'

# --- Dve karty NVIDIA ruznych generaci: jeden ovladac (580 umi i Turing+) ---
machine nv-mixed; cpu AuthenticAMD; pci 0000:01:00.0 030000 10de 2204; pci 0000:02:00.0 030000 10de 1b80
run_case "NVIDIA Ampere + Pascal"
has nvidia-580xx-dkms; lacks nvidia-open-dkms nvidia-utils

# --- AMD ---
machine amd; cpu AuthenticAMD; pci 0000:03:00.0 030000 1002 73bf
run_case "AMD"
has vulkan-radeon amd-ucode; lacks lib32-vulkan-radeon nvidia-utils linux-zen-headers
report_has "AMD graphics"

# --- AMD + multilib (Steam) -> 32bitove ovladace ---
machine amd-multilib; cpu AuthenticAMD; pci 0000:03:00.0 030000 1002 73bf; multilib
run_case "AMD with multilib"
has lib32-vulkan-radeon lib32-mesa
json_py 'd["multilib"] is True'

# --- NVIDIA + multilib ---
machine nv-multilib; pci 0000:01:00.0 030000 10de 2684; multilib
run_case "NVIDIA open with multilib"
has lib32-nvidia-utils
machine nv580-multilib; pci 0000:01:00.0 030000 10de 1c03; multilib
run_case "NVIDIA 580 with multilib"
has lib32-nvidia-580xx-utils; lacks lib32-nvidia-utils

# --- Intel: stara grafika (i965) a SOF zvuk ---
machine intel-old; cpu GenuineIntel; pci 0000:00:02.0 030000 8086 0166
run_case "Intel Ivy Bridge"
has libva-intel-driver vulkan-intel; lacks intel-media-driver

machine intel-sof; cpu GenuineIntel; battery; pci 0000:00:02.0 030000 8086 a7a0; pci 0000:00:1f.3 040100 8086 51ca
run_case "Intel laptop with SOF audio"
has sof-firmware alsa-ucm-conf intel-media-driver thermald
report_has "Smart Sound"

machine intel-hda; cpu GenuineIntel; pci 0000:00:1f.3 040300 8086 a0c8
run_case "Intel desktop HDA audio"
lacks sof-firmware

machine intel-sof380; cpu GenuineIntel; pci 0000:00:1f.3 040380 8086 7e28
run_case "Intel audio class 040380"
has sof-firmware

# --- Kamery IPU6 / IPU7 ---
machine ipu6; cpu GenuineIntel; battery; pci 0000:00:05.0 048000 8086 a75d
run_case "Intel IPU6 camera"
has libcamera pipewire-libcamera gst-plugin-libcamera
report_has "IPU6"
machine ipu7; cpu GenuineIntel; battery; pci 0000:00:05.0 048000 8086 645d
run_case "Intel IPU7 camera"
has libcamera
report_has "experimental"

# --- Broadcom Wi-Fi ---
machine broadcom; cpu GenuineIntel; pci 0000:02:00.0 028000 14e4 43a0; kernel linux 7.2.9.arch1-1
run_case "Broadcom BCM4360"
has broadcom-wl-dkms linux-headers; lacks linux-zen-headers
json_py 'dev["wifi-0000:02:00.0"]["module"]=="wl"'
machine broadcom-fmac; pci 0000:02:00.0 028000 14e4 43a3
run_case "Broadcom brcmfmac (in-kernel)"
lacks broadcom-wl-dkms

# --- Hlavicky pro vsechna nainstalovana jadra; --kernel ma prednost ---
machine kernels; pci 0000:01:00.0 030000 10de 2684
kernel linux-zen 7.2.11-zen1-1-zen; kernel linux-lts 6.18.40-1-lts
mkdir -p "$ROOT/usr/lib/modules/7.2.10-zen1-1-zen"     # zalozni jadro LuxOS Care (bez pkgbase)
run_case "two kernels"
has linux-zen-headers linux-lts-headers
json_py 'sorted(d["kernels"])==["linux-lts","linux-zen"]'
run_case "explicit --kernel" --kernel linux-zen
has linux-zen-headers; lacks linux-lts-headers
machine nokernel; pci 0000:01:00.0 030000 10de 2684
run_case "no kernel installed (live)"
has linux-zen-headers
machine badkernel; pci 0000:01:00.0 030000 10de 2684; kernel 'linux;rm -rf' 7.2.0
run_case "invalid pkgbase is ignored"
has linux-zen-headers
if grep -q 'rm' <<<"$PK"; then bad "invalid pkgbase leaked"; else ok; fi

# --- Virtualni stroje ---
for v in "kvm qemu-guest-agent" "oracle virtualbox-guest-utils" "vmware open-vm-tools" "microsoft hyperv"; do
    machine "vm-${v% *}"; cpu AuthenticAMD; pci 0000:00:01.0 030000 1af4 1050
    export LUXOS_HW_VIRT=${v% *}
    run_case "VM ${v% *}"
    has "${v#* }"
    lacks nvidia-utils vulkan-radeon
    unset LUXOS_HW_VIRT
done
machine vm-svc; export LUXOS_HW_VIRT=oracle; run_case "VirtualBox services"; svc_has vboxservice.service; unset LUXOS_HW_VIRT

# --- USB: otisky prstu, Wi-Fi v rezimu CD, Elan dotykovka ---
machine usb; usb 1-1 06cb 00bd; usb 1-2 0bda 1a2b; usb 1-3 04f3 2b7c
run_case "USB fingerprint + Wi-Fi CD mode"
has fprintd usb_modeswitch
machine elan-touch; usb 1-3 04f3 2b7c
run_case "Elan touchscreen only"
lacks fprintd

# --- Thunderbolt a akcelerometr ---
machine tb; mkdir -p "$ROOT/sys/bus/thunderbolt/devices/domain0"
mkdir -p "$ROOT/sys/bus/iio/devices/iio:device0"; echo accel_3d >"$ROOT/sys/bus/iio/devices/iio:device0/name"
run_case "Thunderbolt + accelerometer"
has bolt iio-sensor-proxy

# --- Live ISO ---
machine live; mkdir -p "$ROOT/run/archiso"; pci 0000:01:00.0 030000 10de 2684
run_case "live ISO"
json_py 'd["live"] is True'

# --- Rozhrani ---
CASE=interface
if hw --bogus >/dev/null 2>&1; then bad "unknown option accepted"; else ok; fi
if hw --kernel >/dev/null 2>&1; then bad "--kernel without value accepted"; else ok; fi
hw --help | grep -q -- '--packages' && ok || bad "--help"
# Bez falesneho korene (skutecny pocitac): musi probehnout a vratit platny JSON
if "$HW" --json | python3 -I -c 'import json,sys; json.load(sys.stdin)'; then ok; else bad "real machine JSON"; fi
# Rychlost: skutecny pocitac, vsechny rezimy
start=$(date +%s%N)
"$HW" --packages >/dev/null; "$HW" --json >/dev/null
ms=$(( ($(date +%s%N) - start) / 1000000 ))
echo "real machine: --packages + --json took ${ms} ms"
((ms < 1500)) && ok || bad "too slow (${ms} ms)"

echo "$tests checks, $fails failed"
((fails == 0))
