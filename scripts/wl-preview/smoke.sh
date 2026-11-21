#!/bin/bash
# Kourovy test zkusebni VM bez okna: start.sh --headless (od cisteho obrazu), snimky pres QMP screendump,
# vstup pres QMP, prikazy v hostu pres guest agenta (scripts/vmctl.py). Na konci VM vypne a disk vrati.
#   scripts/wl-preview/smoke.sh [ADRESAR_VM]      (vychozi out/vm-wayland-preview), vysledky v ADRESAR/smoke
# Hlida celou cestu relace (WP-9/WP-13): start do prihlasovaci obrazovky greetd bez X serveru, prihlaseni heslem
# do plochy (lista + Dock), pad listy = jen lista znovu, Terminal, prejezd plochy, oznameni, XWayland, zamek,
# PSS cele relace a zadny Python v necinne relaci, odhlaseni zpet na prihlaseni, pad kompozitoru zpet na
# prihlaseni, relace LuxOS (X11) z prihlasovaci obrazovky; casy start -> prihlaseni a prihlaseni -> plocha.
# Greeter, lista, Dock a okna se ovladaji i mysi (absolutni mys QEMU) a kontroluje se, ze se obraz opravdu zmeni.
#   LUXOS_SMOKE_START=--tablet ...   totez s usb-tablet misto vmmouse (start.sh --tablet)
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
# Vstup mysi jako clovek (QMP input-send-event: absolutni mys QEMU, vmmouse nebo usb-tablet) a kontrola, ze se
# obraz opravdu zmenil: zamrzly klient (greeter po prvnim snimku) proces i stopu ma, ale nic neprekresli
click() { ctl click "$1" "$2" "$W" "$H" >/dev/null; }
grab() { ctl move 8 400 "$W" "$H" >/dev/null; sleep "${2:-0.6}"; ctl shot "$out/$1.ppm" >/dev/null; }   # kurzor mimo
changed() {  # changed A B X Y W H: pocet zmenenych pixelu v obdelniku (snimky z grab)
    python3 -c 'import sys
def load(p):
    d = open(p, "rb").read()
    m, w, h, mx, px = d.split(maxsplit=4)
    return int(w), px
(w, a), (_, b) = load(sys.argv[1]), load(sys.argv[2])
x, y, bw, bh = map(int, sys.argv[3:7])
print(sum(a[i:i + 3] != b[i:i + 3] for r in range(y, y + bh) for i in range((r * w + x) * 3, (r * w + x + bw) * 3, 3)))' \
        "$out/$1.ppm" "$out/$2.ppm" "${@:3}"
}
redrawn() { (($(changed "$@") > 40)); }   # redrawn A B X Y W H

"$vm/start.sh" --reset >/dev/null
t0=$(now)
"$vm/start.sh" --headless ${LUXOS_SMOKE_START:-} >"$out/qemu.log" 2>&1 &
qpid=$!
trap 'ctl quit >/dev/null 2>&1; wait $qpid 2>/dev/null; "$vm/start.sh" --reset >/dev/null' EXIT

# prubeh obrazu pri startu: splash Plymouthu az do greeteru bez cerne mezery a textove konzole
sleep 0.5
python3 "$here/boot-frames.py" "$vm/qmp2.sock" "$out/boot" 300 >"$out/boot-frames.txt" 2>&1 &
frames_pid=$!

# 1. start do prihlasovaci obrazovky
check "greeter up after boot" wait_for 300 "$greeter_up"
echo "boot_to_greeter_s=$(since "$t0")" | tee "$out/result.txt"
check "boot splash until the greeter, no bright flash, dark gap <= 3 s" wait $frames_pid
grep -E "splash_to_greeter_s|dark_gap_s" "$out/boot-frames.txt" | tee -a "$out/result.txt"
check "splash ended (plymouth quit after the greeter's first frame)" bash -c "! ctl exec 'pgrep -x plymouthd' 2>/dev/null | grep -q '[0-9]'"
sleep 3   # prvni snimek (rozostrena tapeta)
shot 1-greeter
# rozliseni obrazovky VM ze snimku (souradnice tlacitek greeteru)
read -r W H < <(python3 -c 'import struct, sys; d = open(sys.argv[1], "rb").read(24); print(*struct.unpack(">II", d[16:24]))' "$out/1-greeter.png")
echo "screen=${W}x$H" | tee -a "$out/result.txt"
check "no X server at the greeter" bash -c "! ctl exec 'pgrep -x Xorg; pgrep -x Xwayland' 2>/dev/null | grep -q '[0-9]'"
ctl exec 'for p in $(pgrep -u greeter); do echo "$(awk "/^Pss:/{print \$2}" /proc/$p/smaps_rollup) $(cat /proc/$p/comm)"; done' \
    >"$out/greeter-pss.txt" 2>&1
awk '{s += $1} END {printf "greeter_pss_mb=%.1f\n", s / 1024}' "$out/greeter-pss.txt" | tee -a "$out/result.txt"

# pole pro heslo a kulate tlacitko relace (prvni v rade dole) - rozmisteni jako X11 luxos-greeter (luxos_lock_draw):
# pole nad radkem Caps Lock a hlaskou, rada tlacitek uprostred (sirku popisku jen odhadem, tlacitko je 40 px)
read -r fx fy fw fh sx sy < <(awk -v w="$W" -v h="$H" 'function px(v, lo) {x = int(v * u + 0.5); return x < lo ? lo : x}
    BEGIN {u = h / 1080; if (u < 0.55) u = 0.55
           fh = px(36, 28); fw = px(250, 180); if (150 + px(16, 11) + fh > fw) fw = 150 + px(16, 11) + fh
           sp = px(14, 9); fy = h - int(150 * u + 0.5) - px(22, 16) - sp - px(24, 18) - sp - fh
           aw = px(44, 34) + px(8, 6); bh = aw + px(5, 3) + int(px(13, 11) * 1.25 + 0.5)
           bw = 4 * aw + 3 * px(40, 26) + 16
           print int((w - fw) / 2), fy, fw, fh, int(w / 2 - bw / 2 + aw / 2), h - px(42, 26) - bh + aw / 2}')

# 2. mysi: klik do pole, spatne heslo, odeslani sipkou v poli; pak prihlaseni klikem do pole, heslo a Enter
grab g0
click $((fx + fw / 2)) $((fy + fh / 2)); ctl keys spatne >/dev/null
grab g1
check "greeter draws the typed password (click into the field)" redrawn g0 g1 "$fx" "$fy" "$fw" "$fh"
click $((fx + fw - fh / 2)) $((fy + fh / 2)); sleep 3
shot 2-wrong-password
grab g2
check "greeter draws the error hint (submit by the arrow)" redrawn g1 g2 $((fx - 100)) $((fy + fh)) $((fw + 200)) 40
check "greeter stays after a wrong password" has 'pgrep -u greeter -x luxos-greeter' '[0-9]'
# zamrzly greeter mel hodiny porad na minute startu: pockat na dalsi minutu (hodiny VM jdou s hostitelem)
sleep $((62 - 10#$(date +%S)))
grab g3
check "greeter clock follows the time" redrawn g2 g3 0 0 "$W" $((H / 4))
t1=$(now)
click $((fx + fw / 2)) $((fy + fh / 2))
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

# 2b. mys v relaci: nabidka LuxOS a Ovladaci centrum v liste, Terminal z Docku, psani do okna normalniho
# i maximalizovaneho (zamrzla okna: luxcomp prestal posilat frame callbacky). Prohlidka LuxOS pryc, at se nehybe obraz
ctl exec 'systemctl --machine=luxos@ --user stop luxos-first-run.service' >/dev/null 2>&1
grab d0 1.5
click 14 13
grab d1
check "bar: LuxOS menu opens on a click" redrawn d0 d1 0 30 320 300
ctl key esc >/dev/null
grab d2
click $((W - 158)) 13
grab d3
check "bar: Control Center opens on a click" redrawn d2 d3 $((W - 420)) 30 420 300
ctl key esc >/dev/null
click $((W / 2)) $((H - 33))
check "dock: Terminal starts on a click" wait_for 15 'pgrep -u luxos -x luxos-terminal'
grab t0 2
ctl keys 'echo mouse' >/dev/null
grab t1
check "terminal window redraws typed text" redrawn t0 t1 0 30 "$W" $((H - 120))
ctl key meta_l-up >/dev/null
grab t2 1
ctl keys ' ok' >/dev/null
grab t3
check "maximized terminal redraws typed text" redrawn t2 t3 0 30 "$W" $((H - 120))
shot 3b-terminal-maximized
ctl exec 'pkill -u luxos -x luxos-terminal' >/dev/null 2>&1
sleep 1

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
# 8. relace LuxOS (X11): klik na kulate tlacitko relace ji prepne (jako X11 luxos-greeter), zmeni se popisek
ctl key shift >/dev/null; sleep 1   # vyzva (v klidu by klik jen probudil)
grab s0
click "$sx" "$sy"
grab s2
check "greeter draws the chosen session (session button label LuxOS (X11))" redrawn s0 s2 $((sx - 60)) $((sy - 30)) 120 70
shot 10-greeter-x11
click $((fx + fw / 2)) $((fy + fh / 2))
login
check "X11 session (Xorg + xfce4-session) from greetd" wait_for 120 'pgrep -u luxos -x xfce4-session && pgrep -x Xorg'
sleep 10
shot 11-x11-desktop
check "session type x11" has "loginctl show-session $(luxos_session) -p Type" 'x11'

echo "passed $ok, failed $bad" | tee -a "$out/result.txt"
((bad == 0))
