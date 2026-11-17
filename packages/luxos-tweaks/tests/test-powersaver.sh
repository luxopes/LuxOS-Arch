#!/bin/bash
# LuxOS - Sporic baterie (luxos-powersaver-helper) a casovace na pozadi bez roota: falesny koren
# a zastupce systemctl, ktery jen zapisuje volani a drzi stav casovacu v souborech.
#   bash packages/luxos-tweaks/tests/test-powersaver.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
H=$HERE/../files/power/luxos-powersaver-helper
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAIL=0
ok() { if "$@"; then echo "ok    $DESC"; else echo "FAIL  $DESC"; FAIL=$((FAIL + 1)); fi; }

mkdir -p "$T/root/run" "$T/units"
cat >"$T/systemctl" <<'SC'
#!/bin/bash
# zastupce: is-active/is-enabled podle souboru units/NAZEV.active|.enabled, start/stop je meni
echo "$*" >>"$STUB_DIR/calls"
args=()
for a in "$@"; do [[ $a == --* ]] || args+=("$a"); done
verb=${args[0]} unit=${args[1]:-}
case $verb in
    is-active) [[ -f $STUB_DIR/units/$unit.active ]] ;;
    is-enabled) [[ -f $STUB_DIR/units/$unit.enabled ]] ;;
    start) : >"$STUB_DIR/units/$unit.active" ;;
    stop) rm -f "$STUB_DIR/units/$unit.active" ;;
esac
SC
chmod +x "$T/systemctl"
run() { STUB_DIR=$T LUXOS_SYSROOT=$T/root LUXOS_SYSTEMCTL=$T/systemctl bash "$H" "$1"; }
active() { [[ -f $T/units/$1.active ]]; }
fresh() { rm -f "$T"/units/* "$T/calls" "$T"/root/run/luxos/*; for u in "$@"; do : >"$T/units/$u"; done; }

echo "## zapnuti na baterii"
fresh man-db.timer.active man-db.timer.enabled luxos-care-check.timer.active luxos-care-check.timer.enabled
run on
DESC="man-db.timer se pozastavi"; ok test ! -f "$T/units/man-db.timer.active"
DESC="luxos-care-check.timer bezi dal (kontroly bezpecnosti a aktualizaci)"; ok active luxos-care-check.timer
DESC="kontrola LuxOS Care se nezastavuje"; ok bash -c "! grep -q 'stop.*luxos-care-check' '$T/calls'"
DESC="priznak sporice pro LuxOS Care"; ok test -f "$T/root/run/luxos/powersaver"
run off
DESC="vypnuti: man-db.timer znovu bezi"; ok active man-db.timer
DESC="vypnuti: zaznam smazan"; ok test ! -f "$T/root/run/luxos/powersaver.saved"

echo "## prechod ze starsi verze (casovac Care zastaveny sporicem)"
fresh man-db.timer.enabled luxos-care-check.timer.enabled
mkdir -p "$T/root/run/luxos"
printf 'timer:luxos-care-check.timer\t\n' >"$T/root/run/luxos/powersaver.saved"
run on
DESC="drive zastaveny casovac Care se znovu spusti"; ok active luxos-care-check.timer
DESC="jeho zaznam ze seznamu k obnoveni zmizi"; ok bash -c "! grep -q luxos-care-check '$T/root/run/luxos/powersaver.saved'"

echo "## zapnuty, ale neaktivni casovac (stav po starsi verzi bez zaznamu)"
fresh luxos-care-check.timer.enabled
run on
DESC="zapnuty casovac Care se spusti"; ok active luxos-care-check.timer
fresh
run on
DESC="vypnuty (disabled) casovac Care zustava vypnuty"; ok bash -c "! test -f '$T/units/luxos-care-check.timer.active'"

echo "## bez zastupce systemctl a s falesnym korenem se casovace neresi"
fresh luxos-care-check.timer.enabled
STUB_DIR=$T LUXOS_SYSROOT=$T/root bash "$H" on
DESC="zadne volani systemctl"; ok test ! -f "$T/calls"

echo
echo "Vysledek: $FAIL FAIL"
exit $((FAIL > 0))
