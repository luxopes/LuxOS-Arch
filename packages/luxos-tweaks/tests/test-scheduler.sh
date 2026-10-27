#!/bin/bash
# LuxOS - testy spousteni planovace sched_ext (luxos-scheduler) bez roota a bez jadra se sched_ext:
# /sys/kernel/sched_ext a scx_* jsou v docasnem koreni.
#   bash packages/luxos-tweaks/tests/test-scheduler.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
S=$HERE/../files/scheduler
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAIL=0
ok() { if "$@"; then echo "ok    $DESC"; else echo "FAIL  $DESC"; FAIL=$((FAIL + 1)); fi; }

mkdir -p "$T/sys/kernel/sched_ext" "$T/bin"
printf '#!/bin/bash\necho "scx_lavd $*"\n' >"$T/bin/scx_lavd"
chmod +x "$T/bin/scx_lavd"
run() { LUXOS_SCHEDULER_CONF=$T/scheduler.conf LUXOS_SYSROOT=$T LUXOS_SCX_BIN=$T/bin bash "$S/luxos-scheduler" 2>&1; }

echo "## jadro bez sched_ext"
cp "$S/scheduler.conf" "$T/scheduler.conf"
out=$(run); rc=$?
DESC="bez /sys/kernel/sched_ext: konec s 0, planovac jadra"; ok test $rc -eq 0 -a "${out/without sched_ext/}" != "$out"

echo "## vychozi konfigurace"
echo disabled >"$T/sys/kernel/sched_ext/state"
DESC="SCHEDULER=lavd spusti scx_lavd bez voleb"; ok test "$(run)" = "scx_lavd "
printf 'SCHEDULER="lavd"\nARGS="--autopower"\n' >"$T/scheduler.conf"
DESC="volby z ARGS (s uvozovkami)"; ok test "$(run)" = "scx_lavd --autopower"
printf 'SCHEDULER=lavd\nARGS=--autopower; rm -rf /\n' >"$T/scheduler.conf"
DESC="podezrele ARGS se ignoruji"; ok test "$(run | tail -1)" = "scx_lavd "
rm -f "$T/scheduler.conf"
DESC="chybejici konfigurace = lavd"; ok test "$(run)" = "scx_lavd "

echo "## vypnuto a chyby"
printf 'SCHEDULER=default\n' >"$T/scheduler.conf"
out=$(run); rc=$?
DESC="SCHEDULER=default: nic nespusti, konec s 0"; ok test $rc -eq 0 -a "${out/scx_lavd/}" = "$out"
printf 'SCHEDULER=bpfland\n' >"$T/scheduler.conf"
out=$(run); rc=$?
DESC="nenainstalovany planovac: konec s 0"; ok test $rc -eq 0 -a "${out/not installed/}" != "$out"
printf 'SCHEDULER=../../bin/sh\n' >"$T/scheduler.conf"
out=$(run); rc=$?
DESC="neplatne jmeno: konec s 0, nic nespusti"; ok test $rc -eq 0 -a "${out/invalid/}" != "$out"
printf 'SCHEDULER=lavd\n' >"$T/scheduler.conf"
echo enabled >"$T/sys/kernel/sched_ext/state"
out=$(run); rc=$?
DESC="uz bezi jiny planovac sched_ext: nic nespusti"; ok test $rc -eq 0 -a "${out/scx_lavd /}" = "$out"

echo
echo "Vysledek: $FAIL FAIL"
exit $((FAIL > 0))
