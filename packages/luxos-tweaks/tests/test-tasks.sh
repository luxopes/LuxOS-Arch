#!/bin/bash
# LuxOS - limit procesu relace/uzivatele (luxos-tasks-generator) nad falesnym /proc.
#   bash packages/luxos-tweaks/tests/test-tasks.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
G=$HERE/../files/tasks/luxos-tasks-generator
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAIL=0
ok() { if "$@"; then echo "ok    $DESC"; else echo "FAIL  $DESC"; FAIL=$((FAIL + 1)); fi; }

# gen RAM_MB THREADS_MAX [PID_MAX] -> "relace uzivatel"
gen() {
    rm -rf "$T/proc" "$T/out"
    mkdir -p "$T/proc/sys/kernel" "$T/out"
    echo "$2" >"$T/proc/sys/kernel/threads-max"
    echo "${3:-4194304}" >"$T/proc/sys/kernel/pid_max"
    printf 'MemTotal:       %s kB\nMemFree:  1 kB\n' "$(($1 * 1024))" >"$T/proc/meminfo"
    LUXOS_PROC=$T/proc bash "$G" "$T/out" "$T/out" "$T/out"
    local s u
    s=$(sed -n 's/^TasksMax=//p' "$T/out/session-.scope.d/10-luxos-tasks.conf" 2>/dev/null)
    u=$(sed -n 's/^TasksMax=//p' "$T/out/user-.slice.d/10-luxos-tasks.conf" 2>/dev/null)
    echo "$s $u"
}

echo "## podle RAM (threads-max ~7,9 na 1 MB RAM)"
read -r s u <<<"$(gen 15313 121984)"
DESC="16 GB: beze zmeny proti 5 %/8 % ($s/$u)"; ok test "$s" -eq 6099 -a "$u" -eq 9758
read -r s u <<<"$(gen 7800 61000)"
DESC="8 GB: relace nejmene 3 900 = RAM/2 ($s)"; ok test "$s" -eq 3900
DESC="8 GB: uzivatel nad relaci s rezervou 1024 ($u)"; ok test "$u" -ge $((s + 1024))
read -r s u <<<"$(gen 3800 30000)"
DESC="4 GB: relace 1 900 misto 1 500 ($s)"; ok test "$s" -eq 1900
DESC="4 GB: fork bomba v nejhorsim pripade (0,83 MB/proces) pod 45 % RAM"; ok test $((s * 83 / 100)) -lt $((3800 * 45 / 100))
read -r s u <<<"$(gen 65536 500000)"
DESC="64 GB: 5 % maxima ($s)"; ok test "$s" -eq 25000 -a "$u" -eq 40000

echo "## meze a chyby"
read -r s u <<<"$(gen 16000 3000)"
DESC="male maximum jadra: uzivatel nejvys polovina maxima ($u)"; ok test "$u" -eq 1500 -a "$s" -le "$u"
read -r s u <<<"$(gen 16000 121984 5000)"
DESC="pid_max mensi nez threads-max se pocita ($s/$u)"; ok test "$u" -le 2499
rm -rf "$T/proc" "$T/out"; mkdir -p "$T/proc" "$T/out"
LUXOS_PROC=$T/proc bash "$G" "$T/out"; rc=$?
DESC="bez /proc: nic nezapise, konec s 0 (plati staticke drop-iny)"; ok test $rc -eq 0 -a ! -e "$T/out/session-.scope.d"
DESC="bez adresare: konec s 0"; ok bash "$G" "$T/nonexistent"

echo "## systemd prijme vystup"
if command -v systemd-analyze >/dev/null; then
    gen 7800 61000 >/dev/null
    mkdir -p "$T/u"
    printf '[Unit]\nDescription=t\n' >"$T/u/test.slice"
    { cat "$T/u/test.slice"; sed 1d "$T/out/user-.slice.d/10-luxos-tasks.conf"; } >"$T/u/x.slice"
    out=$(systemd-analyze verify --man=no "$T/u/x.slice" 2>&1)
    DESC="systemd-analyze verify ($out)"; ok test -z "$out"
fi

echo
echo "Vysledek: $FAIL FAIL"
exit $((FAIL > 0))
