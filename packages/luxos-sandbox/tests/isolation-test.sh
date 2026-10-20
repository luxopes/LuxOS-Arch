#!/usr/bin/env bash
# LuxOS Sandbox - automaticky test izolace (bez sudo, na hostiteli s bwrap).
#
# Postavi maly testovaci koren (busybox + staticka sonda probe.c) v docasnem
# adresari a spousti luxos-sandbox ze zdrojoveho stromu v testovacim rezimu
# (LUXOS_SANDBOX_TESTING=1, jiny BASE a sdileny adresar). Overuje:
#   domov hostitele neni videt, sit bez --net neni, /proc jen sandbox,
#   ptrace hostitele selze, zapis mimo koren nejde (i pres podvrzene symlinky),
#   sdileny adresar jen s --shared, seccomp, capabilities, --net bez LAN/hostitele,
#   --gui jen vlastni X server, kopirovani souboru dovnitr, limity (systemd scope).
#
# Pouziti: tests/isolation-test.sh            (vystup PASS/FAIL/SKIP, navratovy kod = pocet FAIL)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
CLI="$HERE/../files/luxos-sandbox"
PASS=0 FAIL=0 SKIP=0

pass() { echo "PASS: $*"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $*"; FAIL=$((FAIL + 1)); }
skip() { echo "SKIP: $*"; SKIP=$((SKIP + 1)); }
# expect <popis> <ocekavany-podretezec> -- prikaz...
expect() {
    local desc=$1 want=$2; shift 3
    local out
    out=$("$@" 2>&1)
    if [[ $out == *"$want"* ]]; then pass "$desc  [$(echo "$out" | tr '\n' ' ' | cut -c1-110)]"
    else fail "$desc  (expected '$want', got: $(echo "$out" | tr '\n' ' ' | cut -c1-200))"; fi
}

for t in bwrap busybox gcc python3; do
    command -v $t >/dev/null || { echo "missing $t"; exit 99; }
done

T=$(mktemp -d "${TMPDIR:-/tmp}/luxos-sandbox-test.XXXXXX")
chmod 700 "$T"
HOST_PIDS=()
cleanup() {
    for p in "${HOST_PIDS[@]}"; do kill "$p" 2>/dev/null; done
    chmod -R u+rwX "$T" 2>/dev/null
    rm -rf "$T"
}
trap cleanup EXIT

USERNAME=$(id -un)
BASE="$T/base"
R="$BASE/$USERNAME"
SHARED="$T/shared"
export LUXOS_SANDBOX_TESTING=1 LUXOS_SANDBOX_BASE="$BASE" LUXOS_SANDBOX_SHARED="$SHARED" \
       LUXOS_SANDBOX_TEST_IMPORT_ROOT="$T"
S() { python3 "$CLI" "$@"; }

# ---- testovaci koren --------------------------------------------------------------
echo "== building test rootfs in $R"
mkdir -p "$R"/{usr/bin,usr/lib,etc,var/tmp,opt,srv,root,mnt,home/sandbox/Shared,home/sandbox/Downloads}
chmod 755 "$BASE"; chmod 700 "$R"
cp "$(command -v busybox)" "$R/usr/bin/busybox"
for lib in $(ldd "$(command -v busybox)" | grep -o '/[^ ]*'); do cp -L "$lib" "$R/usr/lib/"; done
for a in sh ls cat id ps touch mkdir chmod grep wc echo sleep test env stat readlink head tr ln rm; do
    ln -s busybox "$R/usr/bin/$a"
done
gcc -static -O2 -o "$R/usr/bin/probe" "$HERE/probe.c" || { echo "probe build failed"; exit 99; }
cp "$R/usr/bin/probe" "$T/probe-host"
printf 'root:x:0:0:root:/root:/bin/sh\nsandbox:x:%s:%s:Sandbox:/home/sandbox:/bin/sh\n' "$(id -u)" "$(id -g)" > "$R/etc/passwd"
printf 'root:x:0:\nsandbox:x:%s:\n' "$(id -g)" > "$R/etc/group"
ln -s /run/luxos/resolv.conf "$R/etc/resolv.conf"
mkdir -p "$SHARED"; chmod 700 "$SHARED"
echo "host-secret" > "$T/host-marker"
echo "shared-marker" > "$SHARED/marker"

echo "== bwrap $(bwrap --version | cut -d' ' -f2), kernel $(uname -r)"

# ---- 1. domov a soubory hostitele --------------------------------------------------
expect "host home ($HOME) is not visible" "GONE" -- S run sh -c 'test -e "$1" && echo VISIBLE || echo GONE' sh "$HOME"
expect "host test dir with marker is not visible" "GONE" -- S run sh -c 'test -e "$1" && echo VISIBLE || echo GONE' sh "$T/host-marker"
expect "/home contains only the sandbox user" "sandbox" -- S run sh -c 'ls /home | tr "\n" " "'
out=$(S run sh -c 'for p in /run/user /run/dbus /tmp/.X11-unix /sys /oldroot /newroot /var/run/dbus; do test -e $p && echo "LEAK:$p"; done; env | grep -E "^(DISPLAY|WAYLAND|DBUS|XAUTH|SSH_AUTH|PULSE)" ; echo done' 2>&1)
[[ $out == "done" ]] && pass "no /run/user, D-Bus, X11, /sys and no session env vars [$out]" || fail "host session resources leaked: $out"

# ---- 2. sit bez --net ---------------------------------------------------------------
expect "only loopback interface without --net" "lo" -- S run sh -c 'grep : /proc/net/dev | grep -v "lo:" | wc -l | grep -q "^0$" && echo lo-only-ok'
PORT=$((20000 + RANDOM % 20000))
python3 -m http.server --bind 0.0.0.0 "$PORT" >/dev/null 2>&1 & HOST_PIDS+=($!)
sleep 1
expect "control: host itself reaches its listener 127.0.0.1:$PORT" "OK" -- "$T/probe-host" connect 127.0.0.1 "$PORT"
expect "no internet without --net (1.1.1.1:443)" "FAIL ENETUNREACH" -- S run probe connect 1.1.1.1 443
expect "host listener 127.0.0.1:$PORT unreachable without --net" "FAIL ECONNREFUSED" -- S run probe connect 127.0.0.1 "$PORT"
if [[ ${DISPLAY:-} =~ ^:([0-9]+) ]]; then
    HD=${BASH_REMATCH[1]}
    if [[ $("$T/probe-host" abstract "/tmp/.X11-unix/X$HD") == OK ]]; then
        expect "host X display abstract socket @/tmp/.X11-unix/X$HD unreachable" "FAIL" -- S run probe abstract "/tmp/.X11-unix/X$HD"
    else
        skip "host X server has no abstract socket to test"
    fi
fi

# ---- 3. /proc a ptrace ------------------------------------------------------------------
sleep 300 & HP=$!; HOST_PIDS+=("$HP")
expect "host process $HP not in sandbox /proc" "NOTVISIBLE" -- S run sh -c 'test -d /proc/$1 && echo VISIBLE || echo NOTVISIBLE' sh "$HP"
expect "/proc shows only sandbox processes (<=4 pids)" "SMALL" -- S run sh -c 'n=$(ls /proc | grep -c "^[0-9][0-9]*$"); ps -o pid,user,args | tr "\n" ";"; test $n -le 4 && echo SMALL n=$n || echo BIG n=$n'
expect "ptrace of host process $HP fails" "FAIL" -- S run probe ptrace "$HP"
expect "ptrace of own child fails (seccomp EPERM)" "FAIL EPERM" -- S run probe ptrace-self-child

# ---- 4. seccomp a capabilities ---------------------------------------------------------
expect "blocked syscalls (unshare/mount/chroot/keyctl/bpf/perf/userfaultfd/kexec/...)" "ALLOWED 0" -- S run probe syscalls
expect "no capabilities, no_new_privs, seccomp filter active" "CapEff:	0000000000000000 NoNewPrivs:	1 Seccomp:	2" -- \
    S run sh -c 'grep -E "^(CapEff|NoNewPrivs|Seccomp):" /proc/self/status | tr "\n" " "'

# ---- 5. zapis mimo koren ------------------------------------------------------------------
expect "root of sandbox filesystem is read-only (not the rootfs dir)" "RO" -- S run sh -c 'touch /newfile 2>/dev/null && echo RW || echo RO'
expect "cannot write into host test dir path" "DENIED" -- S run sh -c 'touch "$1/escape" 2>/dev/null && echo WROTE || echo DENIED' sh "$T"
S run sh -c 'touch /tmp/luxos-sbx-tmp-'"$$"' /var/tmp/persist-ok; echo x > /home/sandbox/persist-ok' >/dev/null 2>&1
[[ ! -e /tmp/luxos-sbx-tmp-$$ ]] && pass "sandbox /tmp is private (file not on host /tmp)" || fail "sandbox /tmp leaked to host"
[[ -e $R/var/tmp/persist-ok && -e $R/home/sandbox/persist-ok ]] && pass "writes inside sandbox persist only in rootfs ($R)" || fail "persistent writes missing"
[[ $(stat -c %a "$R") == 700 ]] && pass "rootfs is 0700" || fail "rootfs mode $(stat -c %a "$R")"
# Podvrzene symlinky v koreni (jako by je vytvorila skodliva aplikace)
mkdir -p "$T/attack-opt"
rm -rf "$R/opt"; ln -s "$T/attack-opt" "$R/opt"
rm -rf "$R/home/sandbox/Shared"; ln -s "../../../../..$T/attack-shared" "$R/home/sandbox/Shared"
S run sh -c 'mkdir -p /opt/x; touch /opt/x/pwn' >/dev/null 2>&1
[[ -z $(ls -A "$T/attack-opt") ]] && pass "symlinked /opt in rootfs is not followed to the host" || fail "write through /opt symlink reached host: $(ls -A "$T/attack-opt")"
S run --shared sh -c 'touch /home/sandbox/Shared/via-shared' >/dev/null 2>&1
[[ ! -e $T/attack-shared && -e $SHARED/via-shared ]] && pass "planted Shared symlink is replaced, nothing created outside" \
    || fail "Shared symlink attack: $(ls -la "$T" | tr '\n' ' ')"
rm -f "$R/opt"; mkdir "$R/opt"
rm -f "$SHARED/via-shared"

# ---- 6. sdileny adresar ----------------------------------------------------------------
expect "shared folder hidden without --shared" "HIDDEN" -- S run sh -c 'cat /home/sandbox/Shared/marker 2>/dev/null || echo HIDDEN'
expect "shared folder visible with --shared" "shared-marker" -- S run --shared cat /home/sandbox/Shared/marker
S run --shared sh -c 'echo from-sandbox > /home/sandbox/Shared/out' >/dev/null 2>&1
[[ $(cat "$SHARED/out" 2>/dev/null) == from-sandbox ]] && pass "--shared write reaches ~/Sandbox" || fail "--shared write missing"
S run sh -c 'echo nope > /home/sandbox/Shared/out2' >/dev/null 2>&1
[[ ! -e $SHARED/out2 ]] && pass "without --shared writes do not reach ~/Sandbox" || fail "write reached shared dir without --shared"

# ---- 7. spusteni stazeneho souboru -------------------------------------------------------
printf '#!/bin/sh\necho imported-ok\ngrep -c "%s" /proc/self/mountinfo\n' "$T" > "$T/hello.sh"
chmod 644 "$T/hello.sh"
expect "run ./file copies it in and runs it (original dir not mounted: 0 mounts)" "imported-ok 0" -- \
    bash -c "cd '$T' && python3 '$CLI' run ./hello.sh 2>/dev/null | tr '\n' ' '"
[[ -x $R/home/sandbox/Downloads/hello.sh ]] && pass "copy stored in sandbox ~/Downloads" || fail "imported copy missing"

# ---- 8. navratovy kod --------------------------------------------------------------------
S run sh -c 'exit 42' >/dev/null 2>&1; rc=$?
[[ $rc == 42 ]] && pass "exit code is passed through (42)" || fail "exit code $rc"

# ---- 9. sit s --net (pasta) ----------------------------------------------------------------
if command -v pasta >/dev/null && command -v ip >/dev/null; then
    GW=$(ip -4 route show default | awk '{print $3; exit}')
    ADDRS=$(ip -j -4 addr | python3 -c 'import json,sys; print(" ".join(a["local"] for l in json.load(sys.stdin) for a in l["addr_info"] if not a["local"].startswith("127.")))')
    if [[ -n $GW ]]; then
        # Kontrola: naivni pasta (vychozi volby) zpristupni hostitele pres adresu brany
        expect "control: plain pasta (defaults) exposes host listener via gateway $GW" "OK" -- \
            pasta --config-net --quiet -- "$T/probe-host" connect "$GW" "$PORT"
        expect "--net: host listener via gateway $GW blocked" "FAIL" -- S run --net probe connect "$GW" "$PORT"
    fi
    for a in $ADDRS; do
        expect "--net: host address $a:$PORT not reachable as host service" "FAIL" -- S run --net probe connect "$a" "$PORT"
    done
    expect "--net: LAN range 192.168.1.1 blocked" "FAIL" -- S run --net probe connect 192.168.1.1 80
    if [[ $("$T/probe-host" connect 1.1.1.1 443) == OK ]]; then
        expect "--net: internet reachable (1.1.1.1:443)" "OK" -- S run --net probe connect 1.1.1.1 443
        expect "--net: resolv.conf points to pasta DNS forwarder" "169.254.1.53" -- S run --net cat /etc/resolv.conf
    else
        skip "host has no internet, internet test skipped"
    fi
    expect "--net: still no host processes, no caps" "CapEff:	0000000000000000" -- S run --net sh -c 'test -d /proc/'"$HP"' && echo VIS; grep CapEff /proc/self/status'
else
    skip "pasta not installed, --net tests skipped"
fi

# ---- 10. GUI (Xephyr) ----------------------------------------------------------------------
if [[ -n ${DISPLAY:-} ]] && command -v Xephyr >/dev/null; then
    expect "--gui: only the nested display socket X0 is inside and it accepts connections" "X0 OK" -- \
        S run --gui sh -c 'ls /tmp/.X11-unix | tr "\n" " "; probe unix /tmp/.X11-unix/X0'
    expect "--gui: DISPLAY=:0 inside is the Xephyr socket, XAUTHORITY private" ":0 /run/luxos/Xauthority" -- \
        S run --gui sh -c 'echo $DISPLAY $XAUTHORITY'
else
    skip "no DISPLAY or Xephyr, GUI test skipped"
fi

# ---- 11. limity (systemd --user scope) --------------------------------------------------------
if [[ -S ${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/systemd/private ]]; then
    S run sleep 4 >/dev/null 2>&1 & SP=$!
    sleep 2
    unit=$(systemctl --user list-units --type=scope --no-legend 'luxos-sandbox-*' | awk '{print $1}' | head -1)
    if [[ -n $unit ]]; then
        props=$(systemctl --user show "$unit" -p MemoryMax -p TasksMax -p CPUQuotaPerSecUSec | tr '\n' ' ')
        [[ $props == *TasksMax=512* ]] && pass "resource limits via systemd scope $unit: $props" || fail "scope limits: $props"
    else
        fail "no luxos-sandbox scope found"
    fi
    wait $SP
else
    skip "no systemd user manager, limit test skipped"
fi

echo
echo "== RESULT: $PASS passed, $FAIL failed, $SKIP skipped"
exit $FAIL
