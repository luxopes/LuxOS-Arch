#!/bin/bash
# Firefox z Docku, Launchpadu a s novym profilem (uvitaci stranka LuxOS) v nahledove VM bez okna, N-krat kazda cesta:
# kolikrat se okno opravdu objevilo (luxwm SIGUSR2: pohled app=firefox s velikosti a visible=1) a za jak dlouho.
# Pripominka 44: aplikace z Docku byly v cgroup luxos-dock.service a Firefox pod jeho MemoryHigh (96 MB)
# visel ve stavu D, okno se skoro nikdy neukazalo. Kontroluje se i to, ze Firefox bezi ve vlastnim app-*.scope.
#   scripts/wl-preview/firefox-launch.sh [ADRESAR_VM] [N]    (vychozi out/vm-wayland-preview, N=20)
#   LUXOS_FF_OVERLAY=adresar   soubory z adresare (jako od /) nahrat do VM pred prihlasenim (zkouska oprav bez obrazu)
# Cesty: dock-cold (Firefox nebezi, zahozena cache stranek), dock-warm, launchpad (Launchpad v Docku, psani "firefox",
# Enter), first-run (smazany profil: prvni spusteni s uvitaci strankou LuxOS). Vysledky v ADRESAR/ffcheck.
set -uo pipefail
here=$(dirname "$(readlink -f "$0")")
repo=$(readlink -f "$here/../..")
vm=$(readlink -f "${1:-$repo/out/vm-wayland-preview}")
N=${2:-20}
TIMEOUT=${LUXOS_FF_TIMEOUT:-45}
out=$vm/ffcheck
rm -rf "$out" && mkdir -p "$out"
export LUXOS_VM_DIR=$vm
W=1280 H=800
ctl() { python3 "$repo/scripts/vmctl.py" "$@"; }
log() { echo "$*" | tee -a "$out/result.txt"; }

# v hostu: cekani na okno Firefoxu (vypis stavu luxwm po SIGUSR2), ukonceni Firefoxu, ikony Docku
cat >"$out/ff-guest.sh" <<'EOF'
#!/bin/bash
log=/home/luxos/.local/state/luxos/luxwm.log
wm=$(pgrep -u luxos -x luxwm)
case $1 in
wait)   # wait SEKUND -> "mapped S CGROUP" | "none S CGROUP"
    t0=$(date +%s%N) end=$(( $(date +%s%N) + $2 * 1000000000 ))
    while (( $(date +%s%N) < end )); do
        n=$(wc -l <"$log"); kill -USR2 "$wm"; sleep 0.2
        if tail -n +$((n + 1)) "$log" | grep -Eq '^luxwm: view [0-9]+ app=firefox .* w=[1-9][0-9]* h=[1-9][0-9]* .* visible=1 '; then
            p=$(pgrep -u luxos -o -x firefox)
            echo "mapped $(( ($(date +%s%N) - t0) / 1000000 )) $(cut -d: -f3 /proc/$p/cgroup 2>/dev/null)"
            exit 0
        fi
    done
    p=$(pgrep -u luxos -o -x firefox)
    echo "none $(( ($(date +%s%N) - t0) / 1000000 )) $(cut -d: -f3 /proc/$p/cgroup 2>/dev/null) state=$(awk '{print $3}' /proc/$p/stat 2>/dev/null)" ;;
close)  # Firefox jako pri zavreni (SIGTERM), po 15 s SIGKILL; zadny proces Firefoxu nesmi zustat
    for p in $(pgrep -u luxos -x firefox); do kill -TERM "$p"; done
    for _ in $(seq 75); do pgrep -u luxos -f '^/usr/lib/firefox/' >/dev/null || exit 0; sleep 0.2; done
    pkill -KILL -u luxos -f '^/usr/lib/firefox/'; sleep 1 ;;
windows)  # pocet oken mimo Firefox (ikony spustenych aplikaci v Docku za pripnutymi)
    n=$(wc -l <"$log"); kill -USR2 "$wm"; sleep 0.3
    tail -n +$((n + 1)) "$log" | grep '^luxwm: view ' | grep -vc ' app=firefox ' ;;
esac
EOF
ctl_ff() { ctl exec "bash /tmp/ff-guest.sh $*"; }

"$vm/start.sh" --reset >/dev/null
"$vm/start.sh" --headless >"$out/qemu.log" 2>&1 &
qpid=$!
trap 'ctl quit >/dev/null 2>&1; wait $qpid 2>/dev/null; "$vm/start.sh" --reset >/dev/null' EXIT
ctl ping 300 >/dev/null || { log "FAIL guest agent"; exit 1; }
for _ in $(seq 300); do ctl exec 'pgrep -u greeter -x luxos-greeter' >/dev/null 2>&1 && break; sleep 1; done
ctl put "$out/ff-guest.sh" /tmp/ff-guest.sh
if [[ -n ${LUXOS_FF_OVERLAY:-} ]]; then
    (cd "$LUXOS_FF_OVERLAY" && find . -type f) | while read -r f; do
        ctl put "$LUXOS_FF_OVERLAY/$f" "/${f#./}.new" && ctl exec "mv -f '/${f#./}.new' '/${f#./}' && chmod 755 '/${f#./}'" >/dev/null
        log "overlay /${f#./}"
    done
fi
sleep 3
ctl keys luxos >/dev/null; ctl key ret >/dev/null
for _ in $(seq 120); do
    ctl exec 'systemctl --machine=luxos@ --user is-active -q luxos-bar.service luxos-dock.service luxos-launchpad.service' \
        >/dev/null 2>&1 && break
    sleep 1
done
sleep 8
ctl shot "$out/desktop.png" >/dev/null

# Ikona v Docku: 8 pripnutych (Launchpad, Obchod, Soubory, Firefox, ...) + okna dalsich aplikaci, rozestup 62 px
icon_x() {  # icon_x PORADI
    local n=$((8 + $(ctl_ff windows | tr -d '[:space:]')))
    echo $((W / 2 + ($1 * 62) - (n - 1) * 31))
}
dock_ff() { click_at "$(icon_x 3)"; }
click_at() { ctl click "$1" $((H - 33)) "$W" "$H" >/dev/null; }
launchpad_ff() {
    click_at "$(icon_x 0)"; sleep 1.2
    ctl keys firefox >/dev/null; sleep 0.6
    ctl key ret >/dev/null
}

declare -A ok total ms
run() {  # run CESTA PRIPRAVA SPUSTENI
    local path=$1 prep=$2 launch=$3 i r
    ok[$path]=0 total[$path]=0 ms[$path]=0
    for ((i = 1; i <= N; i++)); do
        ctl_ff close >/dev/null 2>&1
        [[ -n $prep ]] && ctl exec "$prep" >/dev/null 2>&1
        $launch
        r=$(ctl_ff wait "$TIMEOUT" 2>/dev/null)
        total[$path]=$((total[$path] + 1))
        if [[ $r == mapped* ]]; then
            ok[$path]=$((ok[$path] + 1))
            ms[$path]=$((ms[$path] + $(awk '{print $2}' <<<"$r")))
            ((i == 1)) && { sleep 3; ctl shot "$out/$path.png" >/dev/null; }
        else
            ctl shot "$out/$path-fail-$i.png" >/dev/null
        fi
        echo "$path $i $r" >>"$out/tries.txt"
    done
    ctl_ff close >/dev/null 2>&1
    local avg=0
    ((ok[$path] > 0)) && avg=$((ms[$path] / ok[$path]))
    log "$path mapped ${ok[$path]}/${total[$path]} avg_ms=$avg"
}

# Prvni spusteni noveho profilu, jak ho uvidi novy uzivatel (Prohlidka LuxOS jeste otevrena)
run first-run 'rm -rf /home/luxos/.mozilla /home/luxos/.cache/mozilla' dock_ff
ctl exec 'systemctl --machine=luxos@ --user stop luxos-first-run.service' >/dev/null 2>&1
sleep 1
run dock-cold 'sync; echo 3 >/proc/sys/vm/drop_caches' dock_ff
run dock-warm '' dock_ff
run launchpad '' launchpad_ff
ctl exec 'for u in luxos-dock luxos-launchpad; do echo "$u $(grep -E "^high " /sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/session.slice/$u.service/memory.events)"; done' \
    | tee -a "$out/result.txt"
grep -c ' mapped .* /user.slice/user-1000.slice/user@1000.service/app.slice/app-' "$out/tries.txt" \
    | sed 's/^/in_app_scope=/' | tee -a "$out/result.txt"
bad=0
for p in "${!ok[@]}"; do ((ok[$p] == total[$p])) || bad=1; done
exit $bad
