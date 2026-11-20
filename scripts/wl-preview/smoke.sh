#!/bin/bash
# Kourovy test zkusebni VM bez okna: start.sh --headless (od cisteho obrazu), snimky pres QMP screendump,
# vstup pres QMP, prikazy v hostu pres guest agenta (scripts/vmctl.py). Na konci VM vypne a disk vrati.
#   scripts/wl-preview/smoke.sh [ADRESAR_VM]      (vychozi out/vm-wayland-preview), vysledky v ADRESAR/smoke
# Hlida: start do plochy (lista + Dock), Terminal zkratkou, aplikace z Docku, prejezd plochy, oznameni,
# PSS cele relace uzivatele luxos a cas od spusteni QEMU do plochy.
set -uo pipefail
here=$(dirname "$(readlink -f "$0")")
repo=$(readlink -f "$here/../..")
vm=$(readlink -f "${1:-$repo/out/vm-wayland-preview}")
out=$vm/smoke
bin=$repo/out/wl-test/bin
make -s -C "$repo/scripts/wl-test" OUT="$repo/out/wl-test"
rm -rf "$out" && mkdir -p "$out"
export LUXOS_VM_DIR=$vm
ctl() { python3 "$repo/scripts/vmctl.py" "$@"; }
# prikaz jako uzivatel luxos v jeho relaci (prostredi uzivatelskeho systemd: WAYLAND_DISPLAY...)
as_user() {
    ctl exec "sudo -u luxos XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
        WAYLAND_DISPLAY=wayland-0 DISPLAY=:0 sh -c '$1'"
}
has() { ctl exec "$1" 2>/dev/null | grep -q "$2"; }   # has PRIKAZ_V_HOSTU VZOR
shot() { ctl shot "$out/$1.png" >/dev/null && echo "shot $out/$1.png"; }
ok=0 bad=0
check() {  # check POPIS PRIKAZ..
    local what=$1; shift
    if "$@"; then echo "OK   $what"; ok=$((ok + 1)); else echo "FAIL $what"; bad=$((bad + 1)); fi
}

"$vm/start.sh" --reset >/dev/null
t0=$(date +%s.%N)
"$vm/start.sh" --headless >"$out/qemu.log" 2>&1 &
qpid=$!
trap 'ctl quit >/dev/null 2>&1; wait $qpid 2>/dev/null; "$vm/start.sh" --reset >/dev/null' EXIT

# plocha = bezi lista i Dock a oba uz maji okno (layer surface): luxwm je zapise do logu az po namapovani
desk=""
for _ in $(seq 600); do
    if ctl exec 'systemctl --machine=luxos@ --user is-active -q luxos-bar.service luxos-dock.service' >/dev/null 2>&1; then
        desk=$(date +%s.%N); break
    fi
    kill -0 $qpid 2>/dev/null || break
    sleep 0.5
done
check "desktop session up" test -n "$desk"
[[ -n $desk ]] || { shot failed; exit 1; }
awk -v a="$t0" -v b="$desk" 'BEGIN {printf "boot_to_desktop_s=%.1f\n", b - a}' | tee "$out/result.txt"
sleep 8   # prvni snimky listy a Docku, Launchpad na pozadi
shot 1-desktop

ctl exec 'grep -h "running on" /home/luxos/.local/state/luxos/luxwm.log' | tee -a "$out/result.txt"
check "luxwm on pixman" has 'cat /home/luxos/.local/state/luxos/luxwm.log' 'software rendering'
ctl exec 'systemctl --machine=luxos@ --user --no-pager list-units "luxos-*"' >"$out/units.txt" 2>&1

# Terminal zkratkou Super+T
ctl key meta_l-t; sleep 4
shot 2-terminal
check "terminal opened by Super+T" has 'pgrep -u luxos -x luxos-terminal' '[0-9]'

# prejezd na plochu 2 a zpet (Ctrl+Super+sipky): snimky behem prejezdu, plocha 2 je prazdna
"$bin/wlt-qmp" "$vm/qmp2.sock" capture "$out/slide" 30 2 >"$out/slide.capture" &
cap=$!
sleep 0.3; ctl key ctrl-meta_l-right
wait $cap
shot 3-workspace2
"$bin/wlt-frames" check "$out/slide" >"$out/slide.check" 2>&1
frames=$(md5sum "$out"/slide/*.ppm | awk '{print $1}' | uniq | wc -l)
echo "slide_distinct_frames=$frames" | tee -a "$out/result.txt"
check "workspace slide animates" test "$frames" -ge 4
ctl key ctrl-meta_l-left; sleep 1.5
shot 4-workspace1
rm -rf "$out/slide"

# oznameni
as_user 'notify-send -a Smoke "LuxOS na Waylandu" "Bublina z luxos-notify"' >/dev/null
sleep 1.5
shot 5-notification
check "notification server is luxos-notify" has 'pgrep -u luxos -f /usr/lib/luxos/luxos-notify' '[0-9]'

# aplikace z Docku: ikona Souboru (Thunar), treti zleva ve vychozim Docku pri 1280x800
ctl click "${DOCK_X:-555}" "${DOCK_Y:-762}" "${SCR_W:-1280}" "${SCR_H:-800}"; sleep 5
shot 6-dock-app
check "app started from Dock" has "pgrep -u luxos -x ${DOCK_APP:-thunar}" '[0-9]'

# XWayland
as_user 'setsid xeyes >/dev/null 2>&1 &' >/dev/null; sleep 4
shot 7-xeyes
check "xeyes via XWayland" has 'pgrep -u luxos -x Xwayland' '[0-9]'

# zamek: loginctl lock-session (jako polozka Zamknout v liste), odemknout heslem luxos
check "lock watcher running" has 'systemctl --machine=luxos@ --user is-active luxos-lock.service' '^active'
ctl exec 'loginctl lock-session 1' >/dev/null; sleep 3
shot 8-locked
check "screen locked" has 'loginctl show-session 1 -p LockedHint' 'yes'
ctl keys luxos >/dev/null; ctl key ret >/dev/null; sleep 3
shot 9-unlocked
check "unlocked with the password" has 'loginctl show-session 1 -p LockedHint' 'no'

# PSS vsech procesu uzivatele luxos (relace vcetne aplikaci otevrenych testem) a jen shellu
ctl exec 'for p in $(pgrep -u luxos); do n=$(cat /proc/$p/comm); k=$(awk "/^Pss:/{print \$2}" /proc/$p/smaps_rollup 2>/dev/null); echo "${k:-0} $n"; done | sort -rn' \
    >"$out/pss.txt" 2>&1
awk '{s += $1} END {printf "session_pss_mb=%.1f\n", s / 1024}' "$out/pss.txt" | tee -a "$out/result.txt"
awk '$2 ~ /^(luxwm|luxos-bar|luxos-dock|luxos-notify|luxos-lock-ses|luxos-launchpad|swaybg|systemd|dbus-broker|dbus-daemon|dbus-broker-lau|pipewire|wireplumber|luxos-wayland-p)$/ {s += $1}
     END {printf "shell_pss_mb=%.1f\n", s / 1024}' "$out/pss.txt" | tee -a "$out/result.txt"

echo "passed $ok, failed $bad" | tee -a "$out/result.txt"
((bad == 0))
