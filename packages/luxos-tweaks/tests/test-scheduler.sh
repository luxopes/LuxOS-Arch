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
run() { LUXOS_SCHEDULER_CONF=$T/scheduler.conf LUXOS_SYSROOT=$T LUXOS_SCX_BIN=$T/bin LUXOS_SCHEDULER_STATE=$T/state \
    LUXOS_SCHEDULER_RUN=$T/run bash "$S/luxos-scheduler" 2>&1; }

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

echo "## pad planovace (scx_alloc failed) a navrat k planovaci jadra"
echo disabled >"$T/sys/kernel/sched_ext/state"
printf 'SCHEDULER=lavd\n' >"$T/scheduler.conf"
touch -d '2026-01-01' "$T/scheduler.conf"
printf '#!/bin/bash\necho "Error: EXIT: scx_bpf_error (scx_alloc failed)" >&2\nexit 1\n' >"$T/bin/scx_lavd"
touch -d '2026-01-01' "$T/bin/scx_lavd"
NOW0=$(date +%s)
out=$(LUXOS_NOW=$NOW0 run); rc=$?
DESC="1. pad: nenulovy konec (systemd zkusi znovu)"; ok test $rc -ne 0
DESC="1. pad: klidna zprava v zaznamu"; ok test "${out/took over right away/}" != "$out"
DESC="1. pad: cas padu zapsan"; ok test "$(wc -l <"$T/state/scheduler-crashes")" -eq 1
out=$(LUXOS_NOW=$((NOW0 + 60)) run); rc=$?
DESC="2. pad: dal nenulovy konec"; ok test $rc -ne 0
out=$(LUXOS_NOW=$((NOW0 + 120)) run); rc=$?
DESC="3. pad: konec s 0 (zadny dalsi pokus, sluzba neselze)"; ok test $rc -eq 0
DESC="3. pad: priznak planovace jadra pro LuxOS Care"; ok grep -q '^crashes=3$' "$T/run/scheduler-fallback"
out=$(LUXOS_NOW=$((NOW0 + 180)) run); rc=$?
DESC="po 3 padech za 24 h se scx_lavd nespusti"; ok test $rc -eq 0 -a "${out/scx_bpf_error/}" = "$out"
DESC="... a zprava je klidna (nothing to do)"; ok test "${out/nothing to do/}" != "$out"
out=$(LUXOS_NOW=$((NOW0 + 86400 + 30)) run); rc=$?
DESC="po 24 h od prvniho padu novy pokus"; ok test "${out/scx_bpf_error/}" != "$out"
DESC="... stare pady zapomenuty (2 z poslednich 24 h + novy)"; ok test "$(wc -l <"$T/state/scheduler-crashes")" -eq 3

echo "## novy pokus po zmene nastaveni nebo aktualizaci planovace"
printf '%s\n' "$NOW0" "$NOW0" "$NOW0" >"$T/state/scheduler-crashes"
touch -d "@$((NOW0 - 10))" "$T/scheduler.conf"
out=$(LUXOS_NOW=$((NOW0 + 60)) run)
DESC="konfigurace starsi nez pady: planovac jadra"; ok test "${out/scx_bpf_error/}" = "$out"
touch -d "@$((NOW0 + 30))" "$T/scheduler.conf"
out=$(LUXOS_NOW=$((NOW0 + 60)) run); rc=$?
DESC="konfigurace zmenena po padech (luxos-care scheduler lavd): novy pokus"; ok test "${out/scx_bpf_error/}" != "$out"
DESC="... pocitani padu od zacatku"; ok test "$(wc -l <"$T/state/scheduler-crashes")" -eq 1 -a $rc -ne 0
touch -d '2026-01-01' "$T/scheduler.conf"
printf '%s\n' "$NOW0" "$NOW0" "$NOW0" >"$T/state/scheduler-crashes"
touch -d "@$((NOW0 + 30))" "$T/bin/scx_lavd"
out=$(LUXOS_NOW=$((NOW0 + 60)) run)
DESC="nova verze scx_lavd po padech: novy pokus"; ok test "${out/scx_bpf_error/}" != "$out"
DESC="priznak planovace jadra pri novem pokusu zmizi"; ok test ! -e "$T/run/scheduler-fallback"

echo "## zastaveni sluzby"
# Na pozadi neinteraktivniho shellu je SIGINT ignorovany (a bash ho pak nejde zachytit) - systemd
# spousti sluzbu s vychozimi signaly, proto je obnovit; timeout = pojistka proti zaseknuti testu
launch() {
    LUXOS_SCHEDULER_CONF=$T/scheduler.conf LUXOS_SYSROOT=$T LUXOS_SCX_BIN=$T/bin LUXOS_SCHEDULER_STATE=$T/state \
        LUXOS_SCHEDULER_RUN=$T/run MARK=$T/mark timeout -k 2 20 python3 -c \
        'import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_DFL); os.execvp(sys.argv[1], sys.argv[1:])' \
        bash "$S/luxos-scheduler" >/dev/null 2>&1 &
}
rm -rf "$T/state" "$T/run"
cat >"$T/bin/scx_lavd" <<'SCX'
#!/bin/bash
trap 'echo "got SIGINT" >"$MARK"; exit 0' INT
trap 'echo "got SIGTERM" >"$MARK"; exit 0' TERM
while true; do sleep 0.1; done
SCX
launch
job=$!
for _ in $(seq 50); do pgrep -f "$T/bin/scx_lavd" >/dev/null && break; sleep 0.1; done
w=$(pgrep -f "^bash $S/luxos-scheduler" | head -1)
kill -INT "$w"
wait $job; rc=$?
DESC="SIGINT sluzby (KillSignal) se preda planovaci: konec s 0"; ok test $rc -eq 0
DESC="planovac dostal SIGINT (cisty navrat na EEVDF)"; ok grep -q "got SIGINT" "$T/mark"
DESC="zastaveni neni pad"; ok test ! -e "$T/state/scheduler-crashes"
rm -f "$T/mark"
launch
job=$!
for _ in $(seq 50); do pgrep -f "$T/bin/scx_lavd" >/dev/null && break; sleep 0.1; done
w=$(pgrep -f "^bash $S/luxos-scheduler" | head -1)
kill -TERM "$w"
wait $job; rc=$?
DESC="SIGTERM: planovac dostane SIGINT, konec s 0"; ok test $rc -eq 0 -a -f "$T/mark"

echo "## jednotka"
U=$S/luxos-scheduler.service
DESC="Restart s rostouci prodlevou"; ok grep -q '^RestartSteps=' "$U"
DESC="nejvetsi prodleva"; ok grep -q '^RestartMaxDelaySec=' "$U"
DESC="KillMode=mixed (SIGINT jen pro luxos-scheduler, ten ho preda)"; ok grep -q '^KillMode=mixed' "$U"
if command -v systemd-analyze >/dev/null; then
    mkdir -p "$T/units"
    sed 's#^ExecStart=.*#ExecStart=/bin/true#' "$U" >"$T/units/luxos-scheduler.service"
    out=$(systemd-analyze verify --man=no "$T/units/luxos-scheduler.service" 2>&1 | grep -v -e 'graphical.target' -e 'scx_loader' || true)
    DESC="systemd-analyze verify bez chyb ($out)"; ok test -z "$out"
fi

echo
echo "Vysledek: $FAIL FAIL"
exit $((FAIL > 0))
