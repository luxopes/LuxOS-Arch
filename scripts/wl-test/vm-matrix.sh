#!/bin/bash
# VM matice: labwc na DRM v QEMU s ruznymi grafickymi kartami, snimky QMP screendump a detektor blikani.
#   vm-matrix.sh [KONFIGURACE..]      vychozi: std-auto std-pixman virtio-auto virtio-pixman vmware-auto vmware-pixman
# Konfigurace = KARTA-RENDERER, karta std (bochs-drm), virtio (virtio-gpu bez virgl), vmware (vmwgfx),
# renderer auto (vyber wlroots), pixman, gles2. Pripona -swcursor zapne WLR_NO_HARDWARE_CURSORS=1.
# Obraz: vm-image.sh. Vysledky: $WLT_OUT/vm-runs/CAS/{report.md,KONFIGURACE/..}.
# WLT_KEEP_FRAMES=1 necha vsechny snimky (jinak jen oznacene a jejich sousedy), WLT_VM_FPS, WLT_VM_SECONDS.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
out=${WLT_OUT:-$(readlink -f "$here/../..")/out/wl-test}
vm=$out/vm
bin=$out/bin
fps=${WLT_VM_FPS:-30}
sec=${WLT_VM_SECONDS:-10}
[[ -f $vm/root.img ]] || { echo "No VM image, run vm-image.sh first" >&2; exit 1; }
make -s -C "$here" OUT="$out"
(($#)) || set -- std-auto std-pixman virtio-auto virtio-pixman vmware-auto vmware-pixman

root=$out/vm-runs/$(date +%Y%m%d-%H%M%S)
mkdir -p "$root"
report=$root/report.md
{
    echo "# VM matrix $(date -Iseconds)"
    echo
    echo "Guest: $(grep -E '^(linux|labwc|wlroots0.20|mesa) ' "$vm/packages.txt" | tr '\n' ' ')"
    echo "Host: $(qemu-system-x86_64 --version | head -1), capture $fps fps x $sec s"
    echo
    echo "| config | DRM driver | /dev/dri | renderer (WLR_RENDERER) | started | capture fps | idle flags | scenario flags | labwc PSS kB idle / after |"
    echo "|---|---|---|---|---|---|---|---|---|"
} >"$report"

scope=()
if command -v systemd-run >/dev/null && systemd-run --user --scope --quiet -p TasksMax=300 -- true 2>/dev/null; then
    scope=(systemd-run --user --scope --quiet -p TasksMax=300 --)
fi

guest() { grep -a "^WLT $1" "$run/guest.log" 2>/dev/null | head -1 | cut -d' ' -f2- || true; }
# moduly virtio-vga z vm-image.sh, kdyz je QEMU hostitele nema
[[ -d $out/qemu-mod/lib ]] && export QEMU_MODULE_DIR=$out/qemu-mod/lib

# Snimky necha jen kolem nalezu (cela rada ma ~2 MB na snimek)
prune() {
    local dir=$1 flags=$2
    [[ ${WLT_KEEP_FRAMES:-0} == 1 ]] && return
    local keep=() f n
    for f in $(awk '/^FLAG/{print $3}' "$flags" || true); do
        n=$((10#${f:1:4}))
        for i in $((n - 2)) $((n - 1)) $n $((n + 1)) $((n + 2)); do keep+=("$(printf 'f%04d.ppm' "$i")"); done
    done
    for f in "$dir"/f*.ppm; do
        [[ " ${keep[*]-} " == *" $(basename "$f") "* || $(basename "$f") == f0000.ppm ]] || rm -f "$f"
    done
}

run_one() {
    local cfg=$1 card=${1%%-*} rest=${1#*-} renderer swcursor=0
    renderer=${rest%%-*}
    [[ $cfg == *-swcursor ]] && swcursor=1
    local dev
    case $card in
        std) dev=VGA,xres=1024,yres=768 ;;
        virtio) dev=virtio-vga,xres=1024,yres=768 ;;
        vmware) dev=vmware-svga ;;
        *) echo "unknown card $card" >&2; return 1 ;;
    esac
    run=$root/$cfg
    mkdir -p "$run"
    : >"$run/guest.log"
    "${scope[@]}" timeout -k 5 300 qemu-system-x86_64 -enable-kvm -machine q35 -cpu host -smp 2 -m 2048 \
        -display none -nic none -kernel "$vm/vmlinuz" -initrd "$vm/initramfs.img" \
        -append "root=/dev/vda rw console=ttyS0 loglevel=4 wlt.renderer=$renderer wlt.swcursor=$swcursor" \
        -drive "file=$vm/root.img,if=virtio,format=raw,snapshot=on" \
        -vga none -device "$dev" -device qemu-xhci -device usb-tablet \
        -device virtio-serial -chardev "file,id=wlt,path=$run/guest.log" -device virtserialport,chardev=wlt,name=wlt \
        -qmp "unix:$run/cap.sock,server=on,wait=off" -qmp "unix:$run/in.sock,server=on,wait=off" \
        -serial "file:$run/console.log" >"$run/qemu.log" 2>&1 &
    local qpid=$! started=no
    for _ in $(seq 900); do
        grep -aq '^WLT READY' "$run/guest.log" && { started=yes; break; }
        grep -aq '^WLT labwc_exit' "$run/guest.log" && break
        kill -0 $qpid 2>/dev/null || break
        sleep 0.1
    done
    local idle=- scen=- capfps=- W=1024 H=768
    if [[ $started == yes ]]; then
        "$bin/wlt-qmp" "$run/cap.sock" capture "$run/idle" "$fps" "$sec" >"$run/idle.capture"
        read -r W H < <("$bin/wlt-frames" stat "$run/idle/f0000.ppm" | awk '{split($2, s, "x"); print s[1], s[2]}')
        # okno 400x300 je na stredu, titulek ~25 px nad obsahem; nabidka na volne plose vpravo nahore
        local tx=$((W / 2)) ty=$(((H - 300) / 2 - 12)) mx=$((W * 3 / 4)) my=$((H / 7))
        local -a scenario=("sleep 0.5" "move $tx $ty" "sleep 0.3" "drag $tx $ty $((tx - 250)) $((ty - 120)) 2000"
            "sleep 0.3" "drag $((tx - 250)) $((ty - 120)) $tx $ty 1500" "sleep 0.3" "move $mx $my" "click right" "sleep 0.3")
        for dy in $(seq 4 4 120); do scenario+=("move $((mx + 30)) $((my + dy))" "sleep 0.04"); done
        scenario+=("sleep 0.3" "key esc" "sleep 0.5" "move $((W - 20)) $((H - 20))")
        "$bin/wlt-qmp" "$run/cap.sock" capture "$run/scenario" "$fps" "$sec" >"$run/scenario.capture" &
        local cpid=$!
        "$bin/wlt-qmp" "$run/in.sock" input "${W}x${H}" "${scenario[@]}" || echo "input failed" >>"$run/qemu.log"
        wait $cpid
        "$bin/wlt-frames" check "$run/idle" >"$run/idle.check" && idle=0 || idle=$(grep -c ^FLAG "$run/idle.check" || true)
        "$bin/wlt-frames" check "$run/scenario" >"$run/scenario.check" && scen=0 || scen=$(grep -c ^FLAG "$run/scenario.check" || true)
        "$bin/wlt-frames" stat "$run/scenario/f0000.ppm" >"$run/stat.txt"
        capfps=$(sed -n 's/.*fps=\([0-9.]*\).*/\1/p' "$run/scenario.capture")
        prune "$run/idle" "$run/idle.check"
        prune "$run/scenario" "$run/scenario.check"
        for _ in $(seq 150); do grep -aq '^WLT pss_after' "$run/guest.log" && break; sleep 0.1; done
    else
        "$bin/wlt-qmp" "$run/cap.sock" exec '{"execute":"screendump","arguments":{"filename":"'"$run"'/failed.ppm"}}' \
            >/dev/null 2>&1 || true
        sleep 2
    fi
    "$bin/wlt-qmp" "$run/in.sock" exec '{"execute":"quit"}' >/dev/null 2>&1 || kill $qpid 2>/dev/null || true
    wait $qpid 2>/dev/null || true
    [[ $started == no && -s $run/qemu.log ]] && started="no: $(head -1 "$run/qemu.log" | cut -c1-80)"
    # zadna karta DRM: duvod z jadra (napr. vmwgfx odmita vmware-svga z QEMU)
    if [[ $started != yes ]] && ! grep -aq '^WLT drm card[0-9] driver=.' "$run/guest.log"; then
        started+="; kernel: $(grep -aoE 'probe with driver [a-z0-9_]+ failed with error -?[0-9]+|Hardware has no [a-z]+' "$run/console.log" | head -2 | tr '\n' ' ' || true)"
    fi
    local drv
    drv=$(grep -a '^WLT drm ' "$run/guest.log" | sed 's/.*driver=//' | tr '\n' ' ' || true)
    printf '| %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' "$cfg" "${drv:--}" "$(guest dri_nodes= | cut -d= -f2)" \
        "$(guest renderer= | cut -d= -f2) ($(guest renderer_env | cut -d= -f2))" "$started$(guest labwc_exit | sed 's/^/ /')" "$capfps" "$idle" "$scen" \
        "$(guest pss_idle_kb= | cut -d= -f2) / $(guest pss_after_kb= | cut -d= -f2)" >>"$report"
    tail -1 "$report"
}

for cfg in "$@"; do run_one "$cfg"; done
{
    echo
    echo "Flags per config: */idle.check, */scenario.check. Guest messages: */guest.log, kernel: */console.log."
} >>"$report"
echo "$report"
