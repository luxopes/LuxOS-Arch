#!/usr/bin/env bash
# LuxOS installer - OEM predinstalace bez roota: konfigurace instalatoru (OEM=1), zapeceteni,
# prvni start, dokonceni Pruvodce nastavenim a zmena klice LUKS vcetne vypadku proudu v kazdem kroku.
#
#   bash packages/luxos-installer/tests/test-oem.sh
#
# luxos-oem se nacte (source) s OEM_ROOT = docasny adresar; systemove prikazy (cryptsetup, useradd,
# localectl, mkinitcpio, systemctl...) nahrazuji funkce nize. LUKS je napodoben sloty v souborech.
set -uo pipefail
unset DISPLAY SUDO_USER WAYLAND_DISPLAY
HERE=$(cd "$(dirname "$0")" && pwd)
FILES=$HERE/../files
TMP=$(mktemp -d "${TMPDIR:-/tmp}/luxos-oem-test.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
FAILS=0

check() {  # check POPIS PRIKAZ...
    if "${@:2}"; then echo "ok    $1"; else echo "FAIL  $1"; FAILS=$((FAILS + 1)); fi
}
eq() {  # eq POPIS OCEKAVANO SKUTECNE
    if [[ $2 == "$3" ]]; then echo "ok    $1"; else echo "FAIL  $1: ocekavano '$2', je '$3'"; FAILS=$((FAILS + 1)); fi
}

# =====================================================================================================
echo "## Instalator: OEM=1 v konfiguraci"
(
    T() { local f=$1; shift; printf -- "$f" "$@"; }
    fail() { printf 'FAIL: %s\n' "$*"; exit 3; }
    info() { :; }
    LOG=$TMP/install.log
    SHARE=$FILES
    eval "$(sed -n '/^# --- OEM: priprava pro jineho cloveka/,/^# Bezpecne smazani (WIPE)/p' "$FILES/luxos-install")"
    eval "$(sed -n '/^LANGS=(/,/^)/p' "$FILES/luxos-install")"
    declare -F oem_config oem_prepare_target oem_finish_target oem_check_mode >/dev/null || { echo "FAIL  funkce OEM"; exit 1; }

    # zapeceteno hned, bez sifrovani: zadny ucet, zadne LuxAI
    OEM=1 OEM_SEAL=1 ENCRYPT=0 USERNAME=jana PASSWORD=x FULLNAME="Jana" LUXAI_ACCOUNT='{"a":1}' AUTOLOGIN=1
    oem_config
    eq "seal: bez uctu" "|" "$USERNAME|$PASSWORD"
    eq "seal: bez LuxAI a autologinu" "|0" "$LUXAI_ACCOUNT|$AUTOLOGIN"
    eq "seal: LUKS_PASS se negeneruje bez sifrovani" "" "${LUKS_PASS-}"

    # priprava: docasny ucet oem
    OEM=1 OEM_SEAL=0 USERNAME=jana PASSWORD=tajne FULLNAME=jana ENCRYPT=1 LUKS_PASS=""
    oem_config
    eq "prepare: ucet oem" "oem|tajne|OEM" "$USERNAME|$PASSWORD|$FULLNAME"
    check "prepare + sifrovani: nahodny docasny klic (64 znaku)" test "${#LUKS_PASS}" -eq 64
    k1=$LUKS_PASS
    LUKS_PASS=""; oem_config
    check "docasny klic je pokazde jiny" test "$k1" != "$LUKS_PASS"

    out=$( (OEM=1 OEM_SEAL=0 PASSWORD="" ENCRYPT=0; oem_config) 2>&1 )
    check "prepare bez PASSWORD: chyba" grep -q "needs PASSWORD" <<<"$out"
    out=$( (OEM=1 OEM_SEAL=2; oem_config) 2>&1 )
    check "OEM_SEAL=2: chyba" grep -q "Invalid OEM_SEAL" <<<"$out"
    out=$( (OEM=0 USERNAME=jana; oem_config; echo "U=$USERNAME") 2>&1 )
    check "OEM=0: nic se nemeni" grep -q "U=jana" <<<"$out"

    # rucni rozdeleni s LUKS v OEM nejde
    ly_ids() { [[ $1 == luks ]] && echo croot; }
    out=$( (OEM=1 DISK_MODE=layout; oem_check_mode) 2>&1 )
    check "layout + LUKS: odmitnuto" grep -q "does not support encryption" <<<"$out"
    ly_ids() { :; }
    out=$( (OEM=1 DISK_MODE=layout; oem_check_mode && echo OK) 2>&1 )
    check "layout bez LUKS: v poradku" grep -q OK <<<"$out"

    oem_locs() { local oem_locales=""; ((${OEM:-0})) && oem_locales=$(printf '%s ' "${LANGS[@]##*|}"); echo "$oem_locales"; }
    eq "jazyky predem (OEM)" 14 "$(OEM=1 oem_locs | wc -w)"
    eq "bez OEM zadne jazyky navic" "" "$(OEM=0 oem_locs)"
    check "configure_system: OEM_LOCALES do setup-chroot" grep -q 'OEM_LOCALES=$(printf %q "$oem_locales")' "$FILES/luxos-install"

    # cil: oem.conf, klic disku a initramfs
    TARGET=$TMP/target
    mkdir -p "$TARGET"
    OEM=1 OEM_SEAL=0 ENCRYPT=1 LUKS_PASS=klic123
    oem_prepare_target
    check "oem.conf: OEM=1" grep -qx "OEM=1" "$TARGET/etc/luxos/oem.conf"
    check "oem.conf: docasny ucet" grep -qx "OEM_USER=oem" "$TARGET/etc/luxos/oem.conf"
    check "oem.conf: svazek cryptroot" grep -qx "LUKS_NAME=cryptroot" "$TARGET/etc/luxos/oem.conf"
    eq "klic disku = docasny klic (bez noveho radku)" "klic123" "$(cat "$TARGET/etc/cryptsetup-keys.d/cryptroot.key")"
    eq "klic jen pro roota" 400 "$(stat -c %a "$TARGET/etc/cryptsetup-keys.d/cryptroot.key")"
    check "initramfs: FILES s klicem" grep -qx 'FILES+=(/etc/cryptsetup-keys.d/cryptroot.key)' "$TARGET/etc/mkinitcpio.conf.d/luxos-oem.conf"
    rm -rf "$TARGET"; mkdir -p "$TARGET"
    OEM_SEAL=1 ENCRYPT=0
    oem_prepare_target
    check "seal bez sifrovani: bez uctu a svazku" grep -qx "OEM_USER=" "$TARGET/etc/luxos/oem.conf"
    check "seal bez sifrovani: bez klice" test ! -e "$TARGET/etc/cryptsetup-keys.d/cryptroot.key"

    # zapecetit hned: luxos-oem seal v chrootu; priprava: spoustec Zapecetit pro ucet oem
    arch-chroot() { printf '%s\n' "$*" >>"$TMP/chroot.log"; }
    OEM_SEAL=1; oem_finish_target
    check "seal: luxos-oem seal --chroot --yes v cili" grep -q "/usr/bin/luxos-oem seal --chroot --yes" "$TMP/chroot.log"
    OEM_SEAL=0; : >"$TMP/chroot.log"
    mkdir -p "$TARGET/usr/share/applications"
    cp "$FILES/luxos-oem-seal.desktop" "$TARGET/usr/share/applications/"
    oem_finish_target
    check "prepare: spoustec na plose oem" test -e "$TARGET/home/oem/Desktop/luxos-oem-seal.desktop"
    check "prepare: pripominka po prihlaseni" grep -q -- "--seal-dialog --reminder" "$TARGET/home/oem/.config/autostart/luxos-oem-seal.desktop"
    check "prepare: nic se nezapecetilo" bash -c "! grep -q seal '$TMP/chroot.log'"
    echo "SUB_FAILS=$FAILS"
) | tee "$TMP/part1"
FAILS=$((FAILS + $(sed -n 's/^SUB_FAILS=//p' "$TMP/part1" | tail -1)))
grep -q '^SUB_FAILS=' "$TMP/part1" || FAILS=$((FAILS + 1))

# =====================================================================================================
# napodoba systemu pro luxos-oem
R=$TMP/root
LDEV=/dev/vda2
setup_root() {  # setup_root [sifrovani 0/1] [OEM_USER]
    rm -rf "$R" "$TMP/luks" "$TMP/cmds" "$TMP/crash"
    mkdir -p "$R"/etc/{luxos,ssh,NetworkManager/system-connections,lightdm/lightdm.conf.d,mkinitcpio.conf.d} \
             "$R"/var/{log/journal/abc,lib/lightdm/.local/state/luxos-setup,lib/NetworkManager,cache/pacman/pkg,tmp} \
             "$R"/usr/share/zoneinfo/Europe "$R"/root "$R"/home "$TMP/luks"
    : >"$R/usr/share/zoneinfo/Europe/Prague"
    printf 'root:x:0:0::/root:/bin/bash\nlightdm:x:620:620::/var/lib/lightdm:/usr/bin/nologin\n' >"$R/etc/passwd"
    printf 'wheel:x:998:\nvideo:x:985:\naudio:x:995:\n' >"$R/etc/group"
    printf '127.0.0.1   localhost\n127.0.1.1   luxos.localdomain luxos\n' >"$R/etc/hosts"
    printf '#cs_CZ.UTF-8 UTF-8\n' >"$R/etc/locale.gen"
    echo 0123456789abcdef >"$R/etc/machine-id"
    : >"$R/etc/ssh/ssh_host_ed25519_key"; : >"$R/etc/ssh/ssh_host_ed25519_key.pub"
    echo "spam" >"$R/var/log/pacman.log"; echo "install" >"$R/var/log/luxos-install.log"
    : >"$R/var/log/journal/abc/system.journal"
    : >"$R/var/cache/pacman/pkg/firefox.pkg.tar.zst"
    echo "ls" >"$R/root/.bash_history"
    printf '[connection]\nid=Shop\ntype=wifi\n[wifi-security]\npsk=heslo-obchodu\n' >"$R/etc/NetworkManager/system-connections/Shop.nmconnection"
    printf '[connection]\nid=Wired\ntype=ethernet\n' >"$R/etc/NetworkManager/system-connections/Wired.nmconnection"
    echo '{"step": "account"}' >"$R/var/lib/lightdm/.local/state/luxos-setup/progress.json"
    local enc=${1:-0} user=${2-}
    printf 'OEM=1\nOEM_USER=%s\nLUKS_NAME=%s\n' "$user" "$( ((enc)) && echo cryptroot)" >"$R/etc/luxos/oem.conf"
    if [[ -n $user ]]; then
        printf '%s:x:1000:1000::/home/%s:/usr/bin/lsh\n' "$user" "$user" >>"$R/etc/passwd"
        mkdir -p "$R/home/$user"
        printf '[Seat:*]\nautologin-user=%s\n' "$user" >"$R/etc/lightdm/lightdm.conf.d/60-autologin.conf"
    fi
    if ((enc)); then
        install -d -m700 "$R/etc/cryptsetup-keys.d"
        printf 'TEMPKEY' >"$R/etc/cryptsetup-keys.d/cryptroot.key"
        printf 'FILES+=(/etc/cryptsetup-keys.d/cryptroot.key)\n' >"$R/etc/mkinitcpio.conf.d/luxos-oem.conf"
        printf 'TEMPKEY' >"$TMP/luks/slot.0"
    fi
    : >"$TMP/cmds"
}

# Vypadek proudu: po N zmenach (LUKS, initramfs, journal) proces skonci (exit 99)
crash_tick() {
    [[ -n ${CRASH_AT-} ]] || return 0
    local n=0
    [[ -e $TMP/crash ]] && n=$(<"$TMP/crash")
    n=$((n + 1))
    echo "$n" >"$TMP/crash"
    ((n >= CRASH_AT)) && { echo "CRASH at $n ($*)" >>"$TMP/cmds"; exit 99; }
    return 0
}

log() { printf '%s\n' "$*" >>"$TMP/cmds"; }
getent() {
    case $1 in
        passwd) grep "^$2:" "$R/etc/passwd" ;;
        group) grep "^$2:" "$R/etc/group" ;;
    esac
}
useradd() {
    log "useradd $*"
    local u=${!#} c="" a=("$@") i
    for ((i = 0; i < ${#a[@]}; i++)); do [[ ${a[i]} == -c ]] && c=${a[i + 1]}; done
    printf '%s:x:1001:1001:%s:/home/%s:/usr/bin/lsh\n' "$u" "$c" "$u" >>"$R/etc/passwd"
    mkdir -p "$R/home/$u"
    crash_tick useradd
}
usermod() { log "usermod $*"; }
userdel() { log "userdel $*"; local u=${!#}; sed -i "/^$u:/d" "$R/etc/passwd"; rm -rf "${R:?}/home/$u"; }
chpasswd() { local l; l=$(cat); log "chpasswd ${l%%:*}"; printf '%s\n' "$l" >>"$TMP/passwords"; }
passwd() { log "passwd $*"; }
groupadd() { log "groupadd $*"; }
gpasswd() { log "gpasswd $*"; }
chown() { :; }
localectl() { log "localectl $*"; }
timedatectl() { log "timedatectl $*"; }
hostnamectl() { log "hostnamectl $*"; }
locale() { printf 'C\nC.utf8\nen_US.utf8\ncs_CZ.utf8\n'; }
locale-gen() { log "locale-gen"; }
systemctl() { log "systemctl $*"; }
journalctl() { log "journalctl $*"; }
ssh-keygen() { log "ssh-keygen $*"; }
sync() { :; }
shred() { [[ $1 == -u ]] && rm -f "$2"; }
mkinitcpio() {
    crash_tick mkinitcpio
    log "mkinitcpio $* (key in image: $([[ -e $R/etc/mkinitcpio.conf.d/luxos-oem.conf ]] && echo yes || echo no))"
    # obraz initramfs: obsahuje klic, jen kdyz je v konfiguraci
    if [[ -e $R/etc/mkinitcpio.conf.d/luxos-oem.conf ]]; then cp "$R/etc/cryptsetup-keys.d/cryptroot.key" "$TMP/initramfs.key"
    else rm -f "$TMP/initramfs.key"; fi
    [[ ${MKINITCPIO_FAIL-} == 1 ]] && return 1
    return 0
}

# cryptsetup: sloty $TMP/luks/slot.N (obsah = klic)
slot_match() {  # slot_match SOUBOR -> cislo slotu s timto klicem
    local f c
    c=$(cat "$1")
    for f in "$TMP"/luks/slot.*; do [[ -e $f && $(cat "$f") == "$c" ]] && { echo "${f##*.}"; return 0; }; done
    return 1
}
cryptsetup() {
    local a=("$@") kf="" slot="" i
    for ((i = 0; i < ${#a[@]}; i++)); do
        [[ ${a[i]} == --key-file ]] && kf=${a[i + 1]}
        [[ ${a[i]} == --key-slot ]] && slot=${a[i + 1]}
    done
    case $1 in
        status) echo "/dev/mapper/$2 is active and is in use."; echo "  type:    LUKS2"; echo "  device:  $LDEV" ;;
        luksDump)
            echo "LUKS header information"; echo "Keyslots:"
            for f in "$TMP"/luks/slot.*; do [[ -e $f ]] && printf '  %s: luks2\n\tKey:        512 bits\n' "${f##*.}"; done
            echo "Tokens:"; echo "Digests:" ;;
        open)
            [[ -e $TMP/luks/slot.$slot ]] || return 1
            [[ $(cat "$TMP/luks/slot.$slot") == "$(cat "$kf")" ]] ;;
        luksAddKey)
            slot_match "$kf" >/dev/null || return 2
            crash_tick luksAddKey
            local n=0
            while [[ -e $TMP/luks/slot.$n ]]; do n=$((n + 1)); done
            cp "${!#}" "$TMP/luks/slot.$n"
            log "cryptsetup luksAddKey -> slot $n" ;;
        luksKillSlot)
            slot_match "$kf" >/dev/null || return 2
            crash_tick luksKillSlot
            rm -f "$TMP/luks/slot.${!#}"; log "cryptsetup luksKillSlot ${!#}" ;;
        luksRemoveKey)
            local s
            s=$(slot_match "$kf") || return 2
            crash_tick luksRemoveKey
            rm -f "$TMP/luks/slot.$s"; log "cryptsetup luksRemoveKey slot $s" ;;
    esac
}

load_oem() {
    OEM_ROOT=$R TMPDIR_OEM=$TMP
    export OEM_ROOT
    # shellcheck disable=SC1091
    . "$FILES/luxos-oem"
    # journal se pocita jako zmena (vypadek tesne pred / po zapisu)
    eval "orig_$(declare -f jset)"
    jset() { crash_tick "jset $1"; orig_jset "$@"; }
}

INPUT=$'LOCALE=cs_CZ.UTF-8\nXKB_LAYOUT=cz,us\nXKB_VARIANT=qwerty,\nXKB_OPTIONS=grp:shifts_toggle\nTIMEZONE=Europe/Prague\nFULLNAME=Jana Nováková\nUSERNAME=jana\nPASSWORD=ucet heslo\nHOSTNAME=\nAUTOLOGIN=0\nCARE_MODE=classic\nLUXAI_ACCOUNT={"sessionToken":"t","user":{"email":"j@x.cz"}}\nPHOTO=\nDISK_PASS=disk-heslo-1'
input_with() {  # input_with KLIC=hodnota... -> INPUT se zmenenymi radky
    local out=$INPUT kv
    for kv in "$@"; do out=$(sed "s|^${kv%%=*}=.*|$kv|" <<<"$out"); done
    printf '%s\n' "$out"
}

# =====================================================================================================
echo "## luxos-oem seal"
setup_root 0 oem
(load_oem; main seal --yes) >"$TMP/out" 2>&1
check "seal skoncil bez chyby" grep -q "Sealed" "$TMP/out"
check "armed" test -e "$R/var/lib/luxos/oem/armed"
check "greeter = Pruvodce nastavenim" grep -qx "greeter-session=luxos-setup" "$R/etc/lightdm/lightdm.conf.d/90-luxos-oem.conf"
check "sudoers jen status a finish" grep -qx "lightdm ALL=(root) NOPASSWD: /usr/bin/luxos-oem status, /usr/bin/luxos-oem finish" "$R/etc/sudoers.d/90-luxos-oem"
eq "sudoers 0440" 440 "$(stat -c %a "$R/etc/sudoers.d/90-luxos-oem")"
check "polkit: Wi-Fi pro lightdm" grep -q 'subject.user == "lightdm"' "$R/etc/polkit-1/rules.d/49-luxos-oem.rules"
check "sluzba prvniho startu zapnuta" grep -q "systemctl enable luxos-oem-firstboot.service" "$TMP/cmds"
check "ucet oem zamknut" grep -q "passwd -l oem" "$TMP/cmds"
check "ucet oem ke smazani pri startu" grep -qx "OEM_USER=oem" "$R/var/lib/luxos/oem/cleanup"
check "autologin oem pryc" test ! -e "$R/etc/lightdm/lightdm.conf.d/60-autologin.conf"
eq "machine-id" "uninitialized" "$(cat "$R/etc/machine-id")"
check "klice SSH pryc" test ! -e "$R/etc/ssh/ssh_host_ed25519_key"
eq "zaznamy vyprazdnene" 0 "$(stat -c %s "$R/var/log/pacman.log")"
check "instalacni zaznam zustava" grep -q install "$R/var/log/luxos-install.log"
check "journal pryc" test ! -e "$R/var/log/journal/abc"
check "cache baliku pryc" test ! -e "$R/var/cache/pacman/pkg/firefox.pkg.tar.zst"
check "historie roota pryc" test ! -e "$R/root/.bash_history"
check "Wi-Fi obchodu pryc" test ! -e "$R/etc/NetworkManager/system-connections/Shop.nmconnection"
check "kabelove spojeni zustava" test -e "$R/etc/NetworkManager/system-connections/Wired.nmconnection"
check "rozpracovany Pruvodce pryc" test ! -e "$R/var/lib/lightdm/.local/state/luxos-setup/progress.json"
check "bez --poweroff se nevypina" bash -c "! grep -q poweroff '$TMP/cmds'"

setup_root 0 oem
(load_oem; main seal --yes --keep-wifi) >/dev/null 2>&1
check "--keep-wifi: Wi-Fi zustava" test -e "$R/etc/NetworkManager/system-connections/Shop.nmconnection"

setup_root 0 ""
(load_oem; main seal --chroot --yes) >"$TMP/out" 2>&1
check "seal --chroot (instalator)" test -e "$R/var/lib/luxos/oem/armed"
check "chroot: bez journalctl" bash -c "! grep -q journalctl '$TMP/cmds'"
check "bez uctu oem: cleanup jen klice SSH" bash -c "! grep -q OEM_USER '$R/var/lib/luxos/oem/cleanup'"

setup_root 0 ""
rm "$R/etc/luxos/oem.conf"
(load_oem; main seal --yes) >"$TMP/out" 2>&1
check "seal bez OEM instalace: odmitnuto" grep -q "not installed for another person" "$TMP/out"
check "  ... a nic nezapeceteno" test ! -e "$R/var/lib/luxos/oem/armed"

setup_root 0 oem
(load_oem; echo n | main seal) >"$TMP/out" 2>&1
check "seal bez potvrzeni: nic" test ! -e "$R/var/lib/luxos/oem/armed"

echo "## luxos-oem firstboot"
setup_root 0 oem
(load_oem; main seal --yes; main firstboot) >/dev/null 2>&1
check "firstboot: ucet oem smazan" grep -q "userdel -r -f oem" "$TMP/cmds"
check "firstboot: klice SSH" grep -q "ssh-keygen -A" "$TMP/cmds"
check "firstboot: cleanup hotovy" test ! -e "$R/var/lib/luxos/oem/cleanup"
rm -f "$R/etc/lightdm/lightdm.conf.d/90-luxos-oem.conf"
(load_oem; main firstboot) >/dev/null 2>&1
check "firstboot: chybejici greeter doplnen" test -e "$R/etc/lightdm/lightdm.conf.d/90-luxos-oem.conf"

echo "## luxos-oem status"
setup_root 1 ""
(load_oem; main seal --chroot --yes) >/dev/null 2>&1
out=$(load_oem; main status)
check "status: zapeceteno" grep -qx "ARMED=1" <<<"$out"
check "status: heslo disku ceka" grep -qx "LUKS=pending" <<<"$out"
setup_root 0 ""
(load_oem; main seal --chroot --yes) >/dev/null 2>&1
check "status bez sifrovani: LUKS=none" grep -qx "LUKS=none" <<<"$(load_oem; main status)"

echo "## luxos-oem finish (bez sifrovani)"
setup_root 0 ""
(load_oem; main seal --chroot --yes) >/dev/null 2>&1
(load_oem; main finish <<<"$INPUT") >"$TMP/out" 2>&1
check "finish: @@DONE" grep -qx "@@DONE" "$TMP/out"
check "jazyk" grep -q "localectl set-locale LANG=cs_CZ.UTF-8" "$TMP/cmds"
check "klavesnice vcetne konzole (localectl)" grep -q "localectl set-x11-keymap cz,us  qwerty, grp:shifts_toggle" "$TMP/cmds"
check "casove pasmo" grep -q "timedatectl set-timezone Europe/Prague" "$TMP/cmds"
check "nazev pocitace podle uzivatele" grep -q "hostnamectl set-hostname jana-luxos" "$TMP/cmds"
check "/etc/hosts" grep -q "127.0.1.1   jana-luxos.localdomain jana-luxos" "$R/etc/hosts"
check "ucet se skupinou wheel" grep -q "useradd -m -G wheel,video,audio -s /usr/bin/lsh -c Jana Nováková jana" "$TMP/cmds"
check "heslo uctu" grep -qx "jana:ucet heslo" "$TMP/passwords"
check "udrzba classic" grep -qx "MODE=classic" "$R/etc/luxos/care.conf"
check "ucet LuxAI" grep -q sessionToken "$R/home/jana/.config/luxai/account.json"
eq "ucet LuxAI 0600" 600 "$(stat -c %a "$R/home/jana/.config/luxai/account.json")"
check "OEM vypnuto: greeter" test ! -e "$R/etc/lightdm/lightdm.conf.d/90-luxos-oem.conf"
check "OEM vypnuto: sudoers" test ! -e "$R/etc/sudoers.d/90-luxos-oem"
check "OEM vypnuto: polkit" test ! -e "$R/etc/polkit-1/rules.d/49-luxos-oem.rules"
check "OEM vypnuto: done" test -e "$R/var/lib/luxos/oem/done"
check "sluzba prvniho startu vypnuta" grep -q "systemctl disable luxos-oem-firstboot.service" "$TMP/cmds"
(load_oem; main finish <<<"$INPUT") >"$TMP/out" 2>&1
check "druhy finish: odmitnut (uz neni aktivni)" grep -q "not active" "$TMP/out"

echo "## luxos-oem finish: kontrola vstupu"
setup_root 0 ""
(load_oem; main seal --chroot --yes) >/dev/null 2>&1
bad() {  # bad POPIS OCEKAVANA_HLASKA KLIC=hodnota...
    local d=$1 msg=$2
    shift 2
    (load_oem; main finish < <(input_with "$@")) >"$TMP/out" 2>&1
    check "$d" grep -q "$msg" "$TMP/out"
}
bad "spatne jmeno" "Invalid user name" "USERNAME=Jana"
bad "rezervovane jmeno" "Invalid user name" "USERNAME=lightdm"
printf 'pavel:x:1005:1005::/home/pavel:/bin/bash\n' >>"$R/etc/passwd"
bad "obsazene jmeno" "already taken" "USERNAME=pavel"
bad "prazdne heslo" "cannot be empty" "PASSWORD="
bad "casove pasmo mimo zoneinfo" "Invalid time zone" "TIMEZONE=../../etc/passwd"
bad "jazyk" "Invalid language" "LOCALE=cs;rm"
bad "rozlozeni" "Invalid keyboard" 'XKB_LAYOUT=cz;x'
bad "udrzba" "Invalid CARE_MODE" "CARE_MODE=weird"
(load_oem; main finish <<<$'EVIL=1\nUSERNAME=jana') >"$TMP/out" 2>&1
check "neznamy klic odmitnut" grep -q "Invalid setup data" "$TMP/out"
check "po chybach porad zapeceteno" test -e "$R/var/lib/luxos/oem/armed"
eq "po chybach zadny ucet" "" "$(grep '^jana:' "$R/etc/passwd")"
# fotka: jen PNG
printf 'GIF89a' >"$TMP/photo.gif"
printf '\x89PNG\r\n\x1a\n0000' >"$TMP/photo.png"
(load_oem; main finish < <(input_with "PHOTO=$TMP/photo.gif" "AUTOLOGIN=1")) >"$TMP/out" 2>&1
check "fotka jinak nez PNG se ignoruje" test ! -e "$R/var/lib/AccountsService/icons/jana"
check "autologin noveho uctu" grep -qx "autologin-user=jana" "$R/etc/lightdm/lightdm.conf.d/60-autologin.conf"
setup_root 0 ""
(load_oem; main seal --chroot --yes) >/dev/null 2>&1
(load_oem; main finish < <(input_with "PHOTO=$TMP/photo.png")) >"$TMP/out" 2>&1
check "fotka PNG: AccountsService" grep -qx "Icon=/var/lib/AccountsService/icons/jana" "$R/var/lib/AccountsService/users/jana"
check "fotka PNG: ~/.face" test -e "$R/home/jana/.face"

echo "## luxos-oem finish: preruseny beh s jinym jmenem"
setup_root 0 ""
(load_oem; main seal --chroot --yes) >/dev/null 2>&1
(load_oem; CRASH_AT=2; main finish <<<"$INPUT") >/dev/null 2>&1   # pad po zalozeni uctu (2. zmena po jset USER)
check "pad: ucet jana existuje" grep -q '^jana:' "$R/etc/passwd"
eq "pad: status hlasi rozpracovany ucet" "USER=jana" "$(load_oem; main status | grep '^USER=')"
(load_oem; main finish < <(input_with "USERNAME=petr" "FULLNAME=Petr")) >"$TMP/out" 2>&1
check "znovu s jinym jmenem: hotovo" grep -qx "@@DONE" "$TMP/out"
check "  ... stary rozpracovany ucet smazan" bash -c "! grep -q '^jana:' '$R/etc/passwd'"
check "  ... novy ucet" grep -q '^petr:' "$R/etc/passwd"

# =====================================================================================================
echo "## LUKS: heslo zakaznika misto docasneho klice"
luks_keys() { local f; for f in "$TMP"/luks/slot.*; do [[ -e $f ]] && cat "$f" && echo; done | sort | paste -sd' '; }
setup_root 1 ""
(load_oem; main seal --chroot --yes) >/dev/null 2>&1
(load_oem; main finish <<<"$INPUT") >"$TMP/out" 2>&1
check "finish se sifrovanim: @@DONE" grep -qx "@@DONE" "$TMP/out"
eq "jen heslo zakaznika" "disk-heslo-1" "$(luks_keys)"
check "docasny klic smazan" test ! -e "$R/etc/cryptsetup-keys.d/cryptroot.key"
check "initramfs bez klice" test ! -e "$R/etc/mkinitcpio.conf.d/luxos-oem.conf"
check "initramfs prestaven bez klice" grep -q "mkinitcpio -P (key in image: no)" "$TMP/cmds"
check "status: LUKS=done" grep -qx "LUKS=done" <<<"$(load_oem; main status)"

setup_root 1 ""
(load_oem; main seal --chroot --yes) >/dev/null 2>&1
(load_oem; main finish < <(input_with "DISK_PASS=")) >"$TMP/out" 2>&1
check "bez hesla disku: chyba" grep -q "Choose a password for the disk" "$TMP/out"
eq "  ... klice beze zmeny" "TEMPKEY" "$(luks_keys)"

setup_root 1 ""
(load_oem; main seal --chroot --yes) >/dev/null 2>&1
(load_oem; MKINITCPIO_FAIL=1; main finish <<<"$INPUT") >"$TMP/out" 2>&1
check "mkinitcpio selze: chyba" grep -q "Could not rebuild the boot image" "$TMP/out"
check "  ... docasny klic porad plati" test -n "$(cd "$TMP/luks" && grep -l TEMPKEY slot.*)"
check "  ... initramfs s klicem zpet" test -e "$R/etc/mkinitcpio.conf.d/luxos-oem.conf"
(load_oem; main finish <<<"$INPUT") >"$TMP/out" 2>&1
check "  ... znovu: hotovo" grep -qx "@@DONE" "$TMP/out"
eq "  ... jen heslo zakaznika" "disk-heslo-1" "$(luks_keys)"

# Vypadek proudu po kazde zmene: pocitac musi jit spustit (klic v initramfs nebo heslo, ktere
# zakaznik zadal) a druhy beh Pruvodce (zakaznik zada jine heslo) musi skoncit jen s jeho heslem.
echo "## LUKS: vypadek proudu v kazdem kroku"
bootable() {  # initramfs s platnym klicem, nebo nektere zadane heslo plati
    local p f
    if [[ -e $TMP/initramfs.key ]]; then
        for f in "$TMP"/luks/slot.*; do [[ -e $f && $(cat "$f") == "$(cat "$TMP/initramfs.key")" ]] && return 0; done
    fi
    for p in "$@"; do
        for f in "$TMP"/luks/slot.*; do [[ -e $f && $(cat "$f") == "$p" ]] && return 0; done
    done
    return 1
}
crash_points=0
for at in $(seq 1 14); do
    setup_root 1 ""
    (load_oem; main seal --chroot --yes) >/dev/null 2>&1
    cp "$R/etc/cryptsetup-keys.d/cryptroot.key" "$TMP/initramfs.key"   # obraz z instalace
    rm -f "$TMP/crash"
    (load_oem; CRASH_AT=$at; main finish <<<"$INPUT") >"$TMP/out" 2>&1
    rc=$?
    if ((rc != 99)); then
        check "vypadek $at: dobehlo bez vypadku (vsechny body probehly)" grep -qx "@@DONE" "$TMP/out"
        break
    fi
    crash_points=$((crash_points + 1))
    what=$(sed -n 's/^CRASH at [0-9]* (\(.*\))/\1/p' "$TMP/cmds" | tail -1)
    check "vypadek $at ($what): pocitac nastartuje" bootable "disk-heslo-1"
    st=$(load_oem; main status | sed -n 's/^LUKS=//p')
    # Pruvodce se spusti znovu; heslo disku zada jen ve stavu pending
    pass=disk-heslo-2
    [[ $st == pending ]] || pass=""
    (load_oem; main finish < <(input_with "DISK_PASS=$pass")) >"$TMP/out2" 2>&1
    check "vypadek $at ($what): druhy beh hotov (LUKS=$st)" grep -qx "@@DONE" "$TMP/out2"
    if [[ $st == pending ]]; then
        eq "vypadek $at: plati jen nove heslo" "disk-heslo-2" "$(luks_keys)"
    else
        eq "vypadek $at: plati heslo z prvniho behu" "disk-heslo-1" "$(luks_keys)"
    fi
    check "vypadek $at: docasny klic pryc" test ! -e "$R/etc/cryptsetup-keys.d/cryptroot.key"
    check "vypadek $at: initramfs bez klice" test ! -e "$TMP/initramfs.key"
done
check "vypadek proudu vyzkousen v aspon 6 bodech" test "$crash_points" -ge 6

echo
if ((FAILS)); then echo "FAILED: $FAILS"; exit 1; fi
echo "All OEM tests passed."
