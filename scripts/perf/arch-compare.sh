#!/bin/bash
# LuxOS - srovnani s cistym Arch Linux + Xfce + LightDM ve VM (stejne mereni jako vm-measure.sh).
#   scripts/perf/arch-compare.sh install   nainstaluje Arch do out/vmarch (z out/arch/archlinux-x86_64.iso)
#   scripts/perf/arch-compare.sh measure OUTDIR   nastartuje nainstalovany Arch a zmeri start, prihlaseni, klid
# Jen jedna VM najednou (pamet): LuxOS VM musi byt vypnuta. Pozor: disk VM bezi s cache=unsafe -
# pred ukoncenim VM (kill) v hostu spustit "sync", jinak se posledni zapisy ztrati (soubory o delce 0).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/../.."
export LUXOS_VM_DIR=out/vmarch LUXOS_VM_MEM=3072 LUXOS_VM_NAME=ArchXfce
vm() { python3 scripts/vmctl.py "$@"; }
case ${1:-} in
install)
    scripts/test-vm.sh reset >/dev/null
    LUXOS_VM_ISO=out/arch/archlinux-x86_64.iso setsid nohup scripts/test-vm.sh live --headless >out/vmarch.log 2>&1 &
    sleep 20
    until vm ping >/dev/null 2>&1; do sleep 2; done
    sleep 10
    vm put scripts/perf/arch-install.sh /root/arch-install.sh >/dev/null
    vm exec 'bash /root/arch-install.sh > /root/install.log 2>&1; tail -3 /root/install.log' 
    vm exec 'sync; systemctl poweroff' >/dev/null 2>&1 || true
    sleep 10
    echo "installed"
    ;;
measure)
    out=${2:?OUTDIR}
    setsid nohup scripts/test-vm.sh disk --headless >out/vmarch.log 2>&1 &
    sleep 5
    scripts/perf/vm-measure.sh "$out" luxos
    vm put scripts/perf/launch-probe.py /root/launch-probe.py >/dev/null
    vm exec 'python3 /root/launch-probe.py lux 3 2>&1' >"$out/launch.txt"
    ;;
*) echo "usage: $0 install | measure OUTDIR" >&2; exit 2 ;;
esac
