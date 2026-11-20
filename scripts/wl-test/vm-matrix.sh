#!/bin/bash
# VM matice: kompozitor na DRM v QEMU s ruznymi grafickymi kartami, snimky QMP screendump a detektor blikani.
#   vm-matrix.sh [KONFIGURACE..]      vychozi: std-auto std-pixman virtio-auto virtio-pixman vmware-auto vmware-pixman
# Konfigurace = KARTA-RENDERER, karta std (bochs-drm), virtio (virtio-gpu bez virgl), vmware (vmwgfx),
# renderer auto (vyber wlroots), pixman, gles2. Pripona -swcursor zapne WLR_NO_HARDWARE_CURSORS=1.
# WLT_VM_COMP=labwc (vychozi) nebo luxcomp: luxcomp-demo z obrazu s balikem luxcomp (vm-image.sh BALIKY..),
# scenar 2 okna, tazeni, Ctrl+Right/Left (prejezd ploch), zavreni okna.
# Obraz: vm-image.sh. Vysledky: $WLT_OUT/vm-runs/CAS/{report.md,KONFIGURACE/..}.
# WLT_KEEP_FRAMES=1 necha vsechny snimky (jinak jen oznacene a jejich sousedy), WLT_VM_FPS, WLT_VM_SECONDS.
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
out=${WLT_OUT:-$(readlink -f "$here/../..")/out/wl-test}
vm=$out/vm
bin=$out/bin
fps=${WLT_VM_FPS:-30}
sec=${WLT_VM_SECONDS:-10}
comp=${WLT_VM_COMP:-labwc}
[[ -f $vm/root.img ]] || { echo "No VM image, run vm-image.sh first" >&2; exit 1; }
make -s -C "$here" OUT="$out"
(($#)) || set -- std-auto std-pixman virtio-auto virtio-pixman vmware-auto vmware-pixman

root=$out/vm-runs/$(date +%Y%m%d-%H%M%S)
mkdir -p "$root"
report=$root/report.md
{
    echo "# VM matrix $(date -Iseconds)"
    echo
    echo "Compositor: $comp. Guest: $(grep -E '^(linux|labwc|luxcomp|wlroots0.20|mesa) ' "$vm/packages.txt" | tr '\n' ' ')"
    echo "Host: $(qemu-system-x86_64 --version | head -1), capture $fps fps x $sec s"
    echo
    echo "| config | DRM driver | /dev/dri | renderer (WLR_RENDERER) | started | capture fps | idle flags | scenario flags | $comp PSS kB idle / after | slides: captured frames (guest) |"
    echo "|---|---|---|---|---|---|---|---|---|---|"
} >"$report"

scope=()
if command -v systemd-run >/dev/null && systemd-run --user --scope --quiet -p TasksMax=300 -- true 2>/dev/null; then
    scope=(systemd-run --user --scope --quiet -p TasksMax=300 --)
fi

guest() { grep -a "^WLT $1" "$run/guest.log" 2>/dev/null | head -1 | cut -d' ' -f2- || true; }
# prikaz pro hosta (port wltctl, u luxcomp stdin luxcomp-demo)
ctl() { echo "$*" >"$run/ctl"; }
input() { "$bin/wlt-qmp" "$run/in.sock" input "${W}x${H}" "$@" || echo "input failed" >>"$run/qemu.log"; }

# Pocet ruznych snimku zachycenych od casu $2 (s od zacatku snimani) po dobu $3 s v adresari $1
frames_between() {
    local dir=$1 from=$2 len=$3 prev= n=0 f t
    while read -r f t _; do
        awk -v t="$t" -v a="$from" -v l="$len" 'BEGIN{exit !(t >= a && t <= a + l)}' || continue
        [[ -n $prev ]] && [[ $("$bin/wlt-frames" diff "$dir/$prev" "$dir/$f") != 0.0000 ]] && n=$((n + 1))
        prev=$f
    done <"$dir/times.txt"
    echo $n
}

# Scenar labwc: okno 400x300 na stredu (titulek ~25 px nad obsahem) tam a zpet, nabidka na volne plose
scenario_labwc() {
    local tx=$((W / 2)) ty=$(((H - 300) / 2 - 12)) mx=$((W * 3 / 4)) my=$((H / 7))
    local -a s=("sleep 0.5" "move $tx $ty" "sleep 0.3" "drag $tx $ty $((tx - 250)) $((ty - 120)) 2000"
        "sleep 0.3" "drag $((tx - 250)) $((ty - 120)) $tx $ty 1500" "sleep 0.3" "move $mx $my" "click right" "sleep 0.3")
    for dy in $(seq 4 4 120); do s+=("move $((mx + 30)) $((my + dy))" "sleep 0.04"); done
    s+=("sleep 0.3" "key esc" "sleep 0.5" "move $((W - 20)) $((H - 20))")
    input "${s[@]}"
}

since_cap0() { awk -v a="$(date +%s.%N)" -v b="$cap0" 'BEGIN{printf "%.3f\n", a - b}'; }

# Scenar luxcomp-demo: A na stred, B kaskadou o 28 px niz a vpravo (titulek 28 px, zavrit = kolecko
# 14 px od leveho okraje), tazeni B, prejezd na prazdnou plochu a zpet (420 ms), zavreni B.
# Casy stisku Ctrl+sipek jdou do slides.txt (vzhledem k zacatku snimani $cap0).
scenario_luxcomp() {
    local x=$(((W - 400) / 2)) y=$(((H - 328) / 2))
    local bx=$((x + 28)) by=$((y + 28)) dx=-180 dy=-120
    input "sleep 0.3" "move $((W - 20)) $((H - 20))"
    ctl "spawn wlt-client --title A --size 400x300 --hstripes"
    input "sleep 1"
    ctl "spawn wlt-client --title B --size 400x300 --color 2f8f5f --hstripes"
    input "sleep 1" "move $((bx + 200)) $((by + 14))" "sleep 0.3" \
        "drag $((bx + 200)) $((by + 14)) $((bx + 200 + dx)) $((by + 14 + dy)) 1500" "sleep 0.5"
    since_cap0 >"$run/slides.txt"
    input "key ctrl+right" "sleep 1"
    since_cap0 >>"$run/slides.txt"
    input "key ctrl+left" "sleep 1" "move $((bx + dx + 14)) $((by + dy + 14))" "sleep 0.3" "click" "sleep 0.8" \
        "move $((W - 20)) $((H - 20))"
}

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
    mkfifo "$run/ctl"
    "${scope[@]}" timeout -k 5 300 qemu-system-x86_64 -enable-kvm -machine q35 -cpu host -smp 2 -m 2048 \
        -display none -nic none -kernel "$vm/vmlinuz" -initrd "$vm/initramfs.img" \
        -append "root=/dev/vda rw console=ttyS0 loglevel=4 wlt.comp=$comp wlt.renderer=$renderer wlt.swcursor=$swcursor" \
        -drive "file=$vm/root.img,if=virtio,format=raw,snapshot=on" \
        -vga none -device "$dev" -device qemu-xhci -device usb-tablet \
        -device virtio-serial -chardev "file,id=wlt,path=$run/guest.log" -device virtserialport,chardev=wlt,name=wlt \
        -chardev "pipe,id=ctl,path=$run/ctl" -device virtserialport,chardev=ctl,name=wltctl \
        -qmp "unix:$run/cap.sock,server=on,wait=off" -qmp "unix:$run/in.sock,server=on,wait=off" \
        -serial "file:$run/console.log" >"$run/qemu.log" 2>&1 &
    local qpid=$! started=no
    for _ in $(seq 900); do
        grep -aq '^WLT READY' "$run/guest.log" && { started=yes; break; }
        grep -aq '^WLT comp_exit' "$run/guest.log" && break
        kill -0 $qpid 2>/dev/null || break
        sleep 0.1
    done
    local idle=- scen=- capfps=- slides=- W=1024 H=768 cap0
    if [[ $started == yes ]]; then
        "$bin/wlt-qmp" "$run/cap.sock" capture "$run/idle" "$fps" "$sec" >"$run/idle.capture"
        read -r W H < <("$bin/wlt-frames" stat "$run/idle/f0000.ppm" | awk '{split($2, s, "x"); print s[1], s[2]}')
        cap0=$(date +%s.%N)
        "$bin/wlt-qmp" "$run/cap.sock" capture "$run/scenario" "$fps" "$sec" >"$run/scenario.capture" &
        local cpid=$!
        "scenario_$comp"
        wait $cpid
        "$bin/wlt-frames" check "$run/idle" >"$run/idle.check" && idle=0 || idle=$(grep -c ^FLAG "$run/idle.check" || true)
        "$bin/wlt-frames" check "$run/scenario" >"$run/scenario.check" && scen=0 || scen=$(grep -c ^FLAG "$run/scenario.check" || true)
        "$bin/wlt-frames" stat "$run/scenario/f0000.ppm" >"$run/stat.txt"
        capfps=$(sed -n 's/.*fps=\([0-9.]*\).*/\1/p' "$run/scenario.capture")
        if [[ -f $run/slides.txt ]]; then
            slides=$(while read -r t; do frames_between "$run/scenario" "$t" 0.6; done <"$run/slides.txt" | paste -sd/)
        fi
        prune "$run/idle" "$run/idle.check"
        prune "$run/scenario" "$run/scenario.check"
        for _ in $(seq 200); do grep -aq '^WLT pss_after' "$run/guest.log" && break; sleep 0.1; done
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
    [[ $slides != - ]] && slides+=" ($(grep -a '^WLT slide ' "$run/guest.log" | cut -d' ' -f3- | paste -sd';'))"
    printf '| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' "$cfg" "${drv:--}" "$(guest dri_nodes= | cut -d= -f2)" \
        "$(guest renderer= | cut -d= -f2) ($(guest renderer_env | cut -d= -f2))$(guest headless_renderer= | sed 's/^[^=]*=/; headless: /')" "$started$(guest comp_exit | sed 's/^/ /')" "$capfps" "$idle" "$scen" \
        "$(guest pss_idle_kb= | cut -d= -f2) / $(guest pss_after_kb= | cut -d= -f2)" "$slides" >>"$report"
    tail -1 "$report"
}

for cfg in "$@"; do run_one "$cfg"; done
{
    echo
    echo "Flags per config: */idle.check, */scenario.check. Guest messages: */guest.log, kernel: */console.log."
} >>"$report"
echo "$report"
