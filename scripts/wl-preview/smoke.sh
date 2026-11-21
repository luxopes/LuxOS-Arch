#!/bin/bash
# Kourovy test zkusebni VM bez okna: start.sh --headless (od cisteho obrazu), snimky pres QMP screendump,
# vstup pres QMP, prikazy v hostu pres guest agenta (scripts/vmctl.py). Na konci VM vypne a disk vrati.
#   scripts/wl-preview/smoke.sh [ADRESAR_VM]      (vychozi out/vm-wayland-preview), vysledky v ADRESAR/smoke
# Hlida celou cestu relace (WP-9/WP-13): start do prihlasovaci obrazovky greetd bez X serveru, prihlaseni heslem
# do plochy (lista + Dock), pad listy = jen lista znovu, Terminal, prejezd plochy, oznameni, XWayland, zamek,
# PSS cele relace a zadny Python v necinne relaci, odhlaseni zpet na prihlaseni, pad kompozitoru zpet na
# prihlaseni, relace LuxOS (X11) z prihlasovaci obrazovky; casy start -> prihlaseni a prihlaseni -> plocha.
set -uo pipefail
here=$(dirname "$(readlink -f "$0")")
repo=$(readlink -f "$here/../..")
vm=$(readlink -f "${1:-$repo/out/vm-wayland-preview}")
out=$vm/smoke
bin=$repo/out/wl-test/bin
make -s -C "$repo/scripts/wl-test" OUT="$repo/out/wl-test"
rm -rf "$out" && mkdir -p "$out"
export LUXOS_VM_DIR=$vm
W=${SCR_W:-1280} H=${SCR_H:-800}
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
now() { date +%s.%N; }
since() { awk -v a="$1" -v b="$(now)" 'BEGIN {printf "%.1f", b - a}'; }
wait_for() {  # wait_for SEKUND PRIKAZ_V_HOSTU: 0 kdyz prikaz uspel
    local end=$((SECONDS + $1))
    while ((SECONDS < end)); do
        ctl exec "$2" >/dev/null 2>&1 && return 0
        kill -0 $qpid 2>/dev/null || return 1
        sleep 0.3
    done
    return 1
}
greeter_up='pgrep -u greeter -x luxos-greeter && pgrep -u greeter -x luxwm'
desktop_up='systemctl --machine=luxos@ --user is-active -q luxos-bar.service luxos-dock.service'
luxos_session() { ctl exec "loginctl list-sessions --no-legend | awk '\$3 == \"luxos\" && \$6 == \"user\" {print \$1}' | head -1" 2>/dev/null | tr -d '[:space:]'; }
login() {  # prihlaseni heslem z prihlasovaci obrazovky
    ctl keys luxos >/dev/null; ctl key ret >/dev/null
}

"$vm/start.sh" --reset >/dev/null
t0=$(now)
"$vm/start.sh" --headless >"$out/qemu.log" 2>&1 &
qpid=$!
trap 'ctl quit >/dev/null 2>&1; wait $qpid 2>/dev/null; "$vm/start.sh" --reset >/dev/null' EXIT

# 1. start do prihlasovaci obrazovky
check "greeter up after boot" wait_for 300 "$greeter_up"
echo "boot_to_greeter_s=$(since "$t0")" | tee "$out/result.txt"
sleep 3   # prvni snimek (rozostrena tapeta)
shot 1-greeter
# rozliseni obrazovky VM ze snimku (souradnice tlacitek greeteru)
read -r W H < <(python3 -c 'import struct, sys; d = open(sys.argv[1], "rb").read(24); print(*struct.unpack(">II", d[16:24]))' "$out/1-greeter.png")
echo "screen=${W}x$H" | tee -a "$out/result.txt"
check "no X server at the greeter" bash -c "! ctl exec 'pgrep -x Xorg; pgrep -x Xwayland' 2>/dev/null | grep -q '[0-9]'"
ctl exec 'for p in $(pgrep -u greeter); do echo "$(awk "/^Pss:/{print \$2}" /proc/$p/smaps_rollup) $(cat /proc/$p/comm)"; done' \
    >"$out/greeter-pss.txt" 2>&1
awk '{s += $1} END {printf "greeter_pss_mb=%.1f\n", s / 1024}' "$out/greeter-pss.txt" | tee -a "$out/result.txt"

# 2. spatne heslo, pak prihlaseni
ctl keys spatne >/dev/null; ctl key ret >/dev/null; sleep 4
shot 2-wrong-password
check "greeter stays after a wrong password" has 'pgrep -u greeter -x luxos-greeter' '[0-9]'
t1=$(now)
login
check "desktop session up after login" wait_for 120 "$desktop_up"
echo "login_to_desktop_s=$(since "$t1")" | tee -a "$out/result.txt"
sleep 8   # lista a Dock nakreslene, Launchpad na pozadi
shot 3-desktop
check "greeter gone in the session" bash -c "! ctl exec 'pgrep -u greeter -x luxos-greeter' 2>/dev/null | grep -q '[0-9]'"
check "session type wayland" has "loginctl show-session $(luxos_session) -p Type" 'wayland'
check "luxwm on pixman" has 'cat /home/luxos/.local/state/luxos/luxwm.log' 'software rendering'
ctl exec 'systemctl --machine=luxos@ --user --no-pager list-units "luxos-*" "graphical-session*"' >"$out/units.txt" 2>&1
check "polkit agent registered" has 'systemctl --machine=luxos@ --user is-active luxos-polkit.service' '^active'

# 3. pad listy: systemd spusti jen listu znovu, kompozitor a Dock bezi dal
bar=$(ctl exec 'systemctl --machine=luxos@ --user show -p MainPID --value luxos-bar.service' | tr -d '[:space:]')
wm=$(ctl exec 'pgrep -u luxos -x luxwm' | tr -d '[:space:]')
dock=$(ctl exec 'systemctl --machine=luxos@ --user show -p MainPID --value luxos-dock.service' | tr -d '[:space:]')
ctl exec "kill -SEGV $bar" >/dev/null
tb=$(now)
check "bar restarted after a crash" wait_for 10 "p=\$(systemctl --machine=luxos@ --user show -p MainPID --value luxos-bar.service); [ \"\$p\" != 0 ] && [ \"\$p\" != $bar ] && systemctl --machine=luxos@ --user is-active -q luxos-bar.service"
echo "bar_restart_s=$(since "$tb")" | tee -a "$out/result.txt"
check "compositor kept after the bar crash" has "pgrep -u luxos -x luxwm" "^$wm\$"
check "dock kept after the bar crash" has "systemctl --machine=luxos@ --user show -p MainPID --value luxos-dock.service" "^$dock\$"
sleep 2
shot 4-bar-restarted

# 4. necinna relace: PSS a zadny Python. Prohlidka LuxOS (Python) bezi jen pri prvnim prihlaseni: zavrit ji
ctl exec 'pgrep -u luxos -af luxos-tour' >"$out/first-run.txt" 2>&1
ctl exec 'systemctl --machine=luxos@ --user stop luxos-first-run.service' >/dev/null 2>&1
sleep 20
ctl exec 'for p in $(pgrep -u luxos); do n=$(cat /proc/$p/comm); k=$(awk "/^Pss:/{print \$2}" /proc/$p/smaps_rollup 2>/dev/null); echo "${k:-0} $n"; done | sort -rn' \
    >"$out/pss-idle.txt" 2>&1
awk '{s += $1} END {printf "idle_session_pss_mb=%.1f\n", s / 1024}' "$out/pss-idle.txt" | tee -a "$out/result.txt"
ctl exec 'ps -u luxos -o pid=,comm=,args=' >"$out/ps-idle.txt" 2>&1
check "no Python process in the idle session" bash -c "! grep -Ei 'python' '$out/ps-idle.txt'"
ctl exec 'free -m' >"$out/free.txt" 2>&1

# 5. bezne pouziti: Terminal, prejezd plochy, oznameni, XWayland, zamek
ctl key meta_l-t; sleep 4
shot 5-terminal
check "terminal opened by Super+T" has 'pgrep -u luxos -x luxos-terminal' '[0-9]'
"$bin/wlt-qmp" "$vm/qmp2.sock" capture "$out/slide" 30 2 >"$out/slide.capture" &
cap=$!
sleep 0.3; ctl key ctrl-meta_l-right
wait $cap
frames=$(md5sum "$out"/slide/*.ppm | awk '{print $1}' | uniq | wc -l)
echo "slide_distinct_frames=$frames" | tee -a "$out/result.txt"
check "workspace slide animates" test "$frames" -ge 4
ctl key ctrl-meta_l-left; sleep 1.5
rm -rf "$out/slide"
as_user 'notify-send -a Smoke "LuxOS na Waylandu" "Bublina z luxos-notify"' >/dev/null
sleep 1.5
shot 6-notification
check "notification server is luxos-notify" has 'pgrep -u luxos -f /usr/lib/luxos/luxos-notify' '[0-9]'
as_user 'setsid xeyes >/dev/null 2>&1 &' >/dev/null; sleep 4
check "xeyes via XWayland" has 'pgrep -u luxos -x Xwayland' '[0-9]'
s=$(luxos_session)
ctl exec "loginctl lock-session $s" >/dev/null; sleep 3
shot 7-locked
check "screen locked" has "loginctl show-session $s -p LockedHint" 'yes'
login; sleep 3
check "unlocked with the password" has "loginctl show-session $s -p LockedHint" 'no'
ctl exec 'for p in $(pgrep -u luxos); do n=$(cat /proc/$p/comm); k=$(awk "/^Pss:/{print \$2}" /proc/$p/smaps_rollup 2>/dev/null); echo "${k:-0} $n"; done | sort -rn' \
    >"$out/pss-apps.txt" 2>&1
awk '{s += $1} END {printf "session_with_apps_pss_mb=%.1f\n", s / 1024}' "$out/pss-apps.txt" | tee -a "$out/result.txt"

# 6. odhlaseni (polozka Odhlasit v liste = loginctl terminate-session) -> zpet prihlasovaci obrazovka
# stejny prikaz jako polozka Odhlasit v liste, v prostredi uzivatelskeho systemd (XDG_SESSION_ID z relace)
ctl exec "systemd-run --machine=luxos@ --user --quiet --wait -- sh -c 'exec loginctl terminate-session \"\${XDG_SESSION_ID:-auto}\"'" >/dev/null 2>&1
tl=$(now)
check "greeter back after logout" wait_for 60 "$greeter_up"
echo "logout_to_greeter_s=$(since "$tl")" | tee -a "$out/result.txt"
check "session units stopped after logout" bash -c "! ctl exec \"systemctl --machine=luxos@ --user is-active -q luxos-bar.service\" >/dev/null 2>&1"
check "WAYLAND_DISPLAY removed from the user manager" bash -c "! ctl exec 'systemctl --machine=luxos@ --user show-environment' 2>/dev/null | grep -q '^WAYLAND_DISPLAY='"
sleep 3
shot 8-greeter-after-logout

# 7. druhe prihlaseni a pad kompozitoru -> zpet prihlasovaci obrazovka
login
check "second login" wait_for 120 "$desktop_up"
# dele nez 10 s: rychly konec relace by greeter vzal jako nefunkcni Wayland a vybral X11 sam
sleep 12
ctl exec 'pkill -KILL -u luxos -x luxwm' >/dev/null
tc=$(now)
check "greeter back after a compositor crash" wait_for 60 "$greeter_up"
echo "crash_to_greeter_s=$(since "$tc")" | tee -a "$out/result.txt"
sleep 3
shot 9-greeter-after-crash
# 8. relace LuxOS (X11): tlacitko relace vlevo dole
u=$(awk -v h="$H" 'BEGIN {u = h / 1080; if (u < 0.55) u = 0.55; print u}')
read -r sx sy < <(awk -v u="$u" -v h="$H" 'function px(v, lo) {x = int(v * u + 0.5); return x < lo ? lo : x}
    BEGIN {d = px(44, 34); print px(42, 26) + d, h - px(42, 26) - px(20, 14) - d / 2}')
ctl click "$sx" "$sy" "$W" "$H" >/dev/null; sleep 1
shot 10-greeter-x11
login
check "X11 session (Xorg + xfce4-session) from greetd" wait_for 120 'pgrep -u luxos -x xfce4-session && pgrep -x Xorg'
sleep 10
shot 11-x11-desktop
check "session type x11" has "loginctl show-session $(luxos_session) -p Type" 'x11'

echo "passed $ok, failed $bad" | tee -a "$out/result.txt"
((bad == 0))
