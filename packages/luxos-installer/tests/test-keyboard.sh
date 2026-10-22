#!/usr/bin/env bash
# LuxOS installer - vice rozlozeni klavesnice: krok Klavesnice (TUI), xkb_normalize, prevod na konzoli
# a soubory, ktere zapise setup-chroot.sh (00-keyboard.conf, vconsole.conf).
#
#   bash packages/luxos-installer/tests/test-keyboard.sh
#
# Funkce se vezmou primo z luxos-install, gum je nahrazen skriptovanymi odpovedmi. Nic se nezapisuje
# do /etc ani nesaha na displej (DISPLAY a SUDO_USER jsou zrusene, setxkbmap je napodoba).
set -uo pipefail
unset DISPLAY SUDO_USER WAYLAND_DISPLAY
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
FILES=$ROOT/luxos-installer/files
TMP=$(mktemp -d "${TMPDIR:-/tmp}/luxos-kbd.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
FAILS=0

check() {  # check POPIS PRIKAZ...
    if "${@:2}"; then echo "ok    $1"; else echo "FAIL  $1"; FAILS=$((FAILS + 1)); fi
}
eq() {  # eq POPIS OCEKAVANO SKUTECNE
    if [[ $2 == "$3" ]]; then echo "ok    $1"; else echo "FAIL  $1: ocekavano '$2', je '$3'"; FAILS=$((FAILS + 1)); fi
}

# ---- napodoba prostredi luxos-install ----
T() { local f=$1; shift; printf -- "$f" "$@"; }
title() { :; }
info() { printf '%s\n' "$*" >>"$TMP/info"; }
fail() { printf 'FAIL: %s\n' "$*" >"$TMP/fail"; exit 3; }
setxkbmap() { printf 'setxkbmap %s\n' "$*" >>"$TMP/setxkbmap"; }
sudo() { printf 'sudo %s\n' "$*" >>"$TMP/setxkbmap"; }
localectl() {
    case $1 in
        list-x11-keymap-layouts) printf '%s\n' cz de fr ua us ;;
        list-x11-keymap-variants) printf '%s\n' phonetic qwerty ;;
        *) echo "localectl $* NESMI BEZET" >&2; return 1 ;;
    esac
}
# gum: odpovedi z fronty $TMP/answers (radek "__CANCEL__" = Esc); choose vrati vic radku oddelenych "|"
gum() {
    local sub=$1 a
    shift
    case $sub in
        choose|filter)
            cat >"$TMP/gum.items"
            a=$(head -1 "$TMP/answers")
            sed -i 1d "$TMP/answers"
            printf '%s %s\n' "$sub" "$*" >>"$TMP/gum.log"
            [[ $a == __CANCEL__ ]] && return 1
            tr '|' '\n' <<<"$a" ;;
        *) return 0 ;;
    esac
}
answers() { printf '%s\n' "$@" >"$TMP/answers"; : >"$TMP/info"; : >"$TMP/gum.log"; rm -f "$TMP/fail"; }

# funkce z instalatoru (od KEYMAPS po valid_user)
eval "$(sed -n '/^KEYMAPS=(/,/^valid_user() {/p' "$FILES/luxos-install" | sed '$d')"
declare -F ask_keyboard xkb_normalize x11_to_console >/dev/null || { echo "FAIL  funkce z luxos-install"; exit 1; }

kbd() {  # kbd LOCALE ODPOVEDI... -> spusti ask_keyboard v podshellu, vypise "LAYOUT|VARIANT|OPTIONS"
    local loc=$1; shift
    answers "$@"
    (LOCALE=$loc; unset XKB_LAYOUT XKB_VARIANT XKB_OPTIONS; ask_keyboard >/dev/null
     printf '%s|%s|%s\n' "$XKB_LAYOUT" "$XKB_VARIANT" "$XKB_OPTIONS")
}

echo "## TUI krok Klavesnice"
eq "cs: Czech + predvybrana US (Enter)" "cz,us|,|grp:shifts_toggle" "$(kbd cs_CZ.UTF-8 "Czech" "English (US)")"
check "cs: US je predvybrana" grep -q -- '--selected English (US)' "$TMP/gum.log"
check "cs: nejvyse 3 dalsi" grep -q -- '--limit 3' "$TMP/gum.log"
check "cs: nabidka obsahuje 'Only Czech' jako prvni" test "$(head -1 "$TMP/gum.items")" == "Only Czech"
check "cs: vychozi rozlozeni neni v nabidce dalsich" test "$(grep -cx 'Czech' "$TMP/gum.items")" == 0
check "cs: info v souhrnu" grep -q "Keyboard: cz, us" "$TMP/info"
eq "cs: jen Czech (bez US)" "cz||" "$(kbd cs_CZ.UTF-8 "Czech" "Only Czech")"
eq "cs: Czech (QWERTY) + US + German" "cz,us,de|qwerty,,|grp:shifts_toggle" \
    "$(kbd cs_CZ.UTF-8 "Czech (QWERTY)" "English (US)|German")"
eq "cs: 'Only' spolu s jinymi se ignoruje" "sk,us|,|grp:shifts_toggle" \
    "$(kbd sk_SK.UTF-8 "Slovak" "Only Slovak|English (US)")"
eq "en: jen US (bez predvyberu)" "us||" "$(kbd en_US.UTF-8 "English (US)" "Only English (US)")"
check "en: US neni predvybrana" bash -c "! grep -q -- '--selected' '$TMP/gum.log'"
eq "en: US + Czech" "us,cz|,|grp:shifts_toggle" "$(kbd en_US.UTF-8 "English (US)" "Czech")"
eq "Other…: fr + ua (phonetic)" "fr,ua|,phonetic|grp:shifts_toggle" \
    "$(kbd en_US.UTF-8 "Other…" "fr" "(default)" "Other…" "ua" "phonetic")"
eq "Ukrainian: varianty sedi k rozlozenim" "ua,us,cz|,,qwerty|grp:shifts_toggle" \
    "$(kbd uk_UA.UTF-8 "Ukrainian" "English (US)|Czech (QWERTY)")"
out=$(kbd cs_CZ.UTF-8 "Czech" "__CANCEL__"); rc=$?
check "Esc v dalsich rozlozenich ukonci pruvodce" test "$rc" != 0
check "live: bez DISPLAY se setxkbmap nevola" test ! -e "$TMP/setxkbmap"

echo "## xkb_normalize (bezobsluzna konfigurace, GUI)"
norm() {  # norm 'PROMENNE' -> "LAYOUT|VARIANT|OPTIONS" nebo FAIL
    rm -f "$TMP/fail"
    (unset XKB_LAYOUT XKB_VARIANT XKB_OPTIONS; eval "$1"; xkb_normalize
     printf '%s|%s|%s\n' "$XKB_LAYOUT" "$XKB_VARIANT" "$XKB_OPTIONS") 2>/dev/null || echo "FAIL"
}
eq "starsi konfigurace: cz -> cz,us + obe Shift" "cz,us|,|grp:shifts_toggle" "$(norm 'XKB_LAYOUT=cz XKB_VARIANT=')"
eq "starsi konfigurace: cz qwerty" "cz,us|qwerty,|grp:shifts_toggle" "$(norm 'XKB_LAYOUT=cz XKB_VARIANT=qwerty')"
eq "starsi konfigurace: us zustane samo" "us||" "$(norm 'XKB_LAYOUT=us XKB_VARIANT=')"
eq "bez XKB_LAYOUT: us" "us||" "$(norm ':')"
eq "explicitni XKB_OPTIONS='': jen cz" "cz||" "$(norm 'XKB_LAYOUT=cz XKB_VARIANT= XKB_OPTIONS=')"
eq "seznam bez XKB_OPTIONS: obe Shift" "de,us|,|grp:shifts_toggle" "$(norm 'XKB_LAYOUT=de,us')"
eq "mezery a duplicity" "cz,us|qwerty,|grp:ctrl_shift_toggle" \
    "$(norm 'XKB_LAYOUT="cz, us,cz" XKB_VARIANT="qwerty,,qwerty" XKB_OPTIONS=grp:ctrl_shift_toggle')"
eq "prazdne polozky se vynechaji" "cz,us|,|" "$(norm 'XKB_LAYOUT=cz,,us XKB_VARIANT= XKB_OPTIONS=')"
eq "vice voleb" "cz,us|,|grp:alt_shift_toggle,compose:ralt" \
    "$(norm 'XKB_LAYOUT=cz,us XKB_OPTIONS=grp:alt_shift_toggle,compose:ralt')"
eq "4 rozlozeni jsou maximum" "cz,us,de,fr|,,,|" "$(norm 'XKB_LAYOUT=cz,us,de,fr XKB_OPTIONS=')"
eq "5 rozlozeni selze" "FAIL" "$(norm 'XKB_LAYOUT=cz,us,de,fr,pl XKB_OPTIONS=')"
eq "uvozovka v rozlozeni selze" "FAIL" "$(norm 'XKB_LAYOUT="cz\"" XKB_OPTIONS=')"
eq "mezera ve variante se odstrani, jine znaky selzou" "FAIL" "$(norm 'XKB_LAYOUT=cz XKB_VARIANT="a;b" XKB_OPTIONS=')"
eq "neplatne XKB_OPTIONS selze" "FAIL" "$(norm 'XKB_LAYOUT=cz,us XKB_OPTIONS="grp:alt shift"')"
eq "XKB_OPTIONS s uvozovkou selze" "FAIL" "$(norm "XKB_LAYOUT=cz,us XKB_OPTIONS='grp:x\"'")"

echo "## x11_to_console (tabulka systemd)"
if [[ -e /usr/share/systemd/kbd-model-map ]]; then
    eq "cz,us -> cz-us-qwertz" "cz-us-qwertz" "$(x11_to_console cz,us ,)"
    eq "cz -> cz-us-qwertz" "cz-us-qwertz" "$(x11_to_console cz "")"
    eq "cz qwerty,us -> cz-qwerty" "cz-qwerty" "$(x11_to_console cz,us qwerty,)"
    eq "sk qwerty -> sk-qwerty" "sk-qwerty" "$(x11_to_console sk qwerty)"
    eq "us -> us" "us" "$(x11_to_console us "")"
    eq "us,cz -> us" "us" "$(x11_to_console us,cz ,)"
    eq "neznamy -> us" "us" "$(x11_to_console xx "")"
    km=$(x11_to_console de,us ,)
    check "de,us -> nemecka konzole ($km)" test "${km:0:2}" == "de"
else
    echo "skip  x11_to_console (neni /usr/share/systemd/kbd-model-map)"
fi
cat >"$TMP/map" <<'M'
# test
cz-us-qwertz	cz,us	pc105	-	terminate:ctrl_alt_bksp,grp:shifts_toggle
cz-qwerty	cz,us	pc105	qwerty,	terminate:ctrl_alt_bksp
cz-lat2	cz	pc105	qwerty	terminate:ctrl_alt_bksp
M
eq "vlastni tabulka: cz qwerty -> cz-lat2 (presna shoda)" "cz-lat2" "$(KBD_MODEL_MAP=$TMP/map x11_to_console cz qwerty)"
eq "vlastni tabulka: cz qwerty,de -> cz-qwerty (prvni rozlozeni)" "cz-qwerty" \
    "$(KBD_MODEL_MAP=$TMP/map x11_to_console cz,de qwerty,)"

echo "## setup-chroot.sh: soubory pro cely system"
snippet() {  # cast setup-chroot.sh pro klavesnici s cestami do $1
    sed -n '/^echo "--> Keyboard/,/^echo "--> Time zone/p' "$FILES/setup-chroot.sh" | sed '$d' |
        sed -e "s|/etc/X11/xorg.conf.d|$1/X11|g" -e "s|/etc/vconsole.conf|$1/vconsole.conf|g"
}
chroot_kbd() {  # chroot_kbd JMENO 'PROMENNE'
    local d=$TMP/chroot-$1
    mkdir -p "$d"
    snippet "$d" >"$d/s.sh"
    (set -Eeuo pipefail; unset XKB_OPTIONS; eval "$2"; . "$d/s.sh") >/dev/null || echo "FAIL  $1: skript selhal"
}
chroot_kbd multi 'XKB_LAYOUT=cz,us XKB_VARIANT=qwerty, XKB_OPTIONS=grp:alt_shift_toggle CONSOLE_KEYMAP=cz-qwerty'
d=$TMP/chroot-multi
check "multi: XkbLayout" grep -qx '        Option "XkbLayout" "cz,us"' "$d/X11/00-keyboard.conf"
check "multi: XkbVariant" grep -qx '        Option "XkbVariant" "qwerty,"' "$d/X11/00-keyboard.conf"
check "multi: XkbOptions" grep -qx '        Option "XkbOptions" "grp:alt_shift_toggle"' "$d/X11/00-keyboard.conf"
check "multi: InputClass system-keyboard" grep -q 'Identifier "system-keyboard"' "$d/X11/00-keyboard.conf"
eq "multi: vconsole.conf" $'KEYMAP=cz-qwerty\nXKBLAYOUT=cz,us\nXKBVARIANT=qwerty,\nXKBOPTIONS=grp:alt_shift_toggle' \
    "$(cat "$d/vconsole.conf")"
chroot_kbd single 'XKB_LAYOUT=de XKB_VARIANT= XKB_OPTIONS= CONSOLE_KEYMAP=de'
d=$TMP/chroot-single
check "single: jen de" grep -qx '        Option "XkbLayout" "de"' "$d/X11/00-keyboard.conf"
check "single: bez XkbVariant/XkbOptions" bash -c "! grep -q 'XkbVariant\|XkbOptions' '$d/X11/00-keyboard.conf'"
eq "single: vconsole.conf" $'KEYMAP=de\nXKBLAYOUT=de' "$(cat "$d/vconsole.conf")"
chroot_kbd novar 'XKB_LAYOUT=cz,us XKB_VARIANT=, CONSOLE_KEYMAP=cz-us-qwertz'
d=$TMP/chroot-novar
check "bez XKB_OPTIONS v env (set -u) a variant ',': bez XkbVariant" bash -c "grep -q '\"cz,us\"' '$d/X11/00-keyboard.conf' && ! grep -q XkbVariant '$d/X11/00-keyboard.conf'"

# Stejny soubor musi precist aplikace Klavesnice i prihlasovaci obrazovka
PYCHK=$(cat <<'PY'
import ast, os, sys
sys.path.insert(0, sys.argv[1])
import luxos_keyboard as kb
cfg = kb.read_system(sys.argv[3], "/nonexistent")
src = open(sys.argv[2], encoding="utf-8").read()
tree = ast.parse(src)
fn = next(n for c in ast.walk(tree) if isinstance(c, ast.ClassDef) and c.name == "Keyboard"
          for n in c.body if isinstance(n, ast.FunctionDef) and n.name == "_read_conf")
fn.decorator_list = []
ns = {"KEYBOARD_CONF": sys.argv[3]}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "greeter", "exec"), ns)
g_layouts, g_opts = ns["_read_conf"]()
print(cfg["layouts"], cfg["options"], g_layouts, g_opts)
PY
)
out=$(python3 -c "$PYCHK" "$ROOT/luxos-desktop/files/python" "$ROOT/luxos-greeter/files/luxos-greeter" \
      "$TMP/chroot-multi/X11/00-keyboard.conf" 2>&1)
eq "aplikace Klavesnice + greeter ctou vysledek instalatoru" \
    "[('cz', 'qwerty'), ('us', '')] ['grp:alt_shift_toggle'] [('cz', 'qwerty'), ('us', '')] grp:alt_shift_toggle" "$out"

echo "## luxos-install: luxos-setup.env obsahuje XKB_OPTIONS"
check "vychozi prepinani: obe klavesy Shift" grep -qx 'XKB_SWITCH_DEFAULT=grp:shifts_toggle' "$FILES/luxos-install"
check "TUI napoveda: obe klavesy Shift" grep -q '(switch with both Shift keys)' "$FILES/luxos-install"
check "env: XKB_OPTIONS" grep -q '^XKB_OPTIONS=$(printf %q "${XKB_OPTIONS-}")$' "$FILES/luxos-install"
check "konfigurace: xkb_normalize po nacteni" grep -q '^        xkb_normalize' "$FILES/luxos-install"
check "bash -n luxos-install" bash -n "$FILES/luxos-install"
check "bash -n setup-chroot.sh" bash -n "$FILES/setup-chroot.sh"

echo
echo "Vysledek: $FAILS FAIL"
((FAILS == 0))
