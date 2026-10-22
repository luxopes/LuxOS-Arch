#!/bin/bash
# LuxOS installer - testy instalace do existujiciho oddilu (DISK_MODE=partition) BEZ roota a bez disku.
# Funkce se vyjmou z luxos-install, diskove prikazy nahrazuje mock-env.sh. Kontroluje se:
# vhodnost oddilu (duvody), --probe radky pro GUI, sdileny ESP bez formatovani, sifrovani ano/ne,
# zachovany /home, prikazy menici disk jen na vybranem oddilu, crypttab/fstab/cmdline, souhrn a chyby.
#
#   packages/luxos-installer/tests/test-partition.sh       (vypis ok/FAIL, navratovy kod = pocet chyb)
#   KEEP=1 tests/test-partition.sh                         (ponecha vystupy v $OUT)
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
FILES=$(cd "$HERE/../files" && pwd)
OUT=$(mktemp -d "${TMPDIR:-/tmp}/luxos-part-test.XXXXXX")
export TMPDIR=$OUT
NPASS=0 NFAIL=0

ok()  { NPASS=$((NPASS + 1)); printf 'ok    %s\n' "$1"; }
bad() { NFAIL=$((NFAIL + 1)); printf 'FAIL  %s\n' "$1"; [[ -n ${2-} ]] && printf '      %s\n' "$2"; return 0; }
expect() { local d=$1; shift; if "$@"; then ok "$d"; else bad "$d"; fi; }
has()    { grep -qF -- "$2" "$1"; }
hasnot() { ! grep -qF -- "$2" "$1" 2>/dev/null; }

# Funkce z instalatoru (bez spusteni main): sekce volneho mista a existujiciho oddilu + vybrane funkce
extract() { sed -n "/^$1() {/,/^}/p" "$FILES/luxos-install"; }
sed -n '/^# --- Volne misto vedle jinych systemu/,/^# Sifrovani (volitelne)/p' "$FILES/luxos-install" >"$OUT/lib.sh"
for f in human_bytes iso_disk report_layout summary xkb_text configure_system shared_esp_entry \
         wipe_text wipe_area_bytes wipe_disk_hint; do extract "$f" >>"$OUT/lib.sh"; done
grep -q '^part_setup() {' "$OUT/lib.sh" && grep -q '^summary() {' "$OUT/lib.sh" || { echo "extrakce selhala"; exit 1; }

# Prostredi jednoho behu (v podshellu): layout.sh, nahrady disku, funkce instalatoru
setup_env() {  # setup_env "vda:200G ..."
    set -Eeuo pipefail
    . "$FILES/layout.sh"
    . "$FILES/wipe.sh"
    . "$HERE/mock-env.sh"
    . "$OUT/lib.sh"
    # shellcheck disable=SC2086
    mock_init $1
    mkdir -p "$MOCK"/{label,busy,mnt,holders,espfree}
    TARGET=$MOCK/target
    mkdir -p "$TARGET/etc" "$TARGET/root"
    BOOTMODE=uefi BOOTLOADER=auto ENCRYPT=0 LUKS_PASS="" HOME_PART="" ESP_PART="" PROGRESS=0 LOG=/dev/null
    SHARE=$OUT/share AUTOLOGIN=0 NVIDIA_EARLY=0
    # mock-env zna jen ty disky, ktere zalozil; holders a ESP z $MOCK; skutecne pripojeni nikdy
    part_disks() { local f; for f in "$MOCK"/disks/*.size; do f=${f##*/}; echo "/dev/${f%.size}"; done; }
    part_holders() { [[ -e $MOCK/holders/$(mk_key "$1") ]]; }
    esp_info() {
        [[ -e $MOCK/espbad ]] && return 1
        ESP_FREE=$(cat "$MOCK/espfree/$(mk_key "$1")" 2>/dev/null || echo $((400 * 1000 * 1000)))
        ESP_SYSTEMS=Windows ESP_LOADER=0
    }
    timeout() { return 1; }
    iso_disk() { :; }
}

# Oddil v emulaci: addp DISK CISLO VELIKOST_MIB KOD [FS] [POPISEK]
addp() {
    local disk=$1 n=$2 mib=$3 code=$4 fs=${5-} label=${6-} tbl start
    tbl=$MOCK/disks/$disk.tbl
    start=$(awk 'BEGIN {m = 2048} {if ($3 + 1 > m) m = $3 + 1} END {print m}' "$tbl")
    start=$(((start + 2047) / 2048 * 2048))
    echo "$n $start $((start + mib * 2048 - 1)) $code part$n" >>"$tbl"
    local k; k=$(mk_key "$(mock_partpath "$disk" "$n")")
    [[ -n $fs ]] && echo "$fs" >"$MOCK/fs/$k"
    [[ $fs == crypto_LUKS ]] && { rm -f "$MOCK/fs/$k"; : >"$MOCK/luks/$k"; }
    [[ -n $label ]] && echo "$label" >"$MOCK/label/$k"
    return 0
}
content() {  # content DEV druh: obsah "pripojeneho" FS pro part_peek (findmnt v mock-env)
    local d=$MOCK/mnt/$(mk_key "$1")
    mkdir -p "$d"
    case $2 in
        windows) mkdir -p "$d/Windows/System32" ;;
        ubuntu)  mkdir -p "$d/etc"; printf 'NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\n' >"$d/etc/os-release" ;;
        btrfs_home) mkdir -p "$d/@/etc" "$d/@home/jana"; echo 'PRETTY_NAME="Fedora Linux 42"' >"$d/@/etc/os-release" ;;
        data)    mkdir -p "$d/lost+found" "$d/Photos" ;;
        empty)   mkdir -p "$d/lost+found" ;;
    esac
}

# Typicky pocitac: vda = Windows + data, vdb = ruzne nepouzitelne oddily
standard_disks() {
    addp vda 1 512 ef00 vfat SYSTEM
    addp vda 2 16 0c01
    addp vda 3 102400 0700 ntfs Windows
    addp vda 4 61440 8300 ext4 Data
    addp vda 5 4096 8200 swap
    addp vda 6 15360 8300 ext4 home
    addp vda 7 1024 2700 ntfs Recovery
    addp vdb 1 30720 8309 crypto_LUKS
    addp vdb 2 30720 8e00 LVM2_member
    addp vdb 3 30720 fd00 linux_raid_member
    addp vdb 4 30720 8300 ext4 Mounted
    : >"$MOCK/busy/vdb4"
    addp vdb 5 1 0x5
    addp vdb 6 30720 8300 xfs Held
    : >"$MOCK/holders/vdb6"
    addp vdb 7 25600 8300 btrfs OldLinux
    content /dev/vda3 windows
    content /dev/vda4 data
    content /dev/vda6 data
    content /dev/vdb7 btrfs_home
}

echo "# vystupy: $OUT"

# ---------------------------------------------------------------------------------
echo "## A: vhodnost oddilu a duvody (part_check)"
(
    setup_env "vda:200G vdb:200G"
    standard_disks
    for p in /dev/vda{1..7} /dev/vdb{1..7} /dev/vdz9 /dev/vda; do
        part_check "$p"
        printf '%s root=%s home=%s\n' "$p" "${PC_ROOT_ERR:--}" "${PC_HOME_ERR:--}"
    done >"$OUT/A.check"
    rm -rf "$MOCK"
)
c=$OUT/A.check
expect "A: ESP nelze (esp)"                         has "$c" "/dev/vda1 root=esp home=esp"
expect "A: Microsoft reserved nelze (system)"       has "$c" "/dev/vda2 root=system home=system"
expect "A: Windows NTFS lze pro /, ne pro /home"     has "$c" "/dev/vda3 root=- home=home_fs"
expect "A: ext4 data lze pro / i /home"              has "$c" "/dev/vda4 root=- home=-"
expect "A: maly swap: / ne (small), /home ne (FS)"   has "$c" "/dev/vda5 root=small home=home_fs"
expect "A: maly ext4 jen pro /home"                  has "$c" "/dev/vda6 root=small home=-"
expect "A: Windows recovery nelze (system)"         has "$c" "/dev/vda7 root=system home=system"
expect "A: LUKS clen nelze (luks)"                   has "$c" "/dev/vdb1 root=luks home=luks"
expect "A: LVM clen nelze (lvm)"                     has "$c" "/dev/vdb2 root=lvm home=lvm"
expect "A: RAID clen nelze (raid)"                   has "$c" "/dev/vdb3 root=raid home=raid"
expect "A: pripojeny nelze (busy)"                   has "$c" "/dev/vdb4 root=busy home=busy"
expect "A: rozsireny oddil MBR nelze (extended)"    has "$c" "/dev/vdb5 root=extended home=extended"
expect "A: oddil s holders (dm/md) nelze (busy)"     has "$c" "/dev/vdb6 root=busy home=busy"
expect "A: btrfs 25 GiB lze"                         has "$c" "/dev/vdb7 root=- home=-"
expect "A: neexistujici zarizeni (not_found)"        has "$c" "/dev/vdz9 root=not_found home=not_found"
expect "A: cely disk neni oddil (not_part)"          has "$c" "/dev/vda root=not_part home=not_part"

# ---------------------------------------------------------------------------------
echo "## B: obsah oddilu (part_peek_dir na skutecnych adresarich)"
(
    set -uo pipefail
    . "$OUT/lib.sh"
    T() { local f=$1; shift; printf -- "$f" "$@"; }
    d=$OUT/B; mkdir -p "$d"/{win/WINDOWS/system32,ubu/etc,btr/@/usr/lib,btr/@home,data/Docs,empty/lost+found,rel/usr/lib}
    printf 'NAME=Ubuntu\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\n' >"$d/ubu/etc/os-release"
    echo "PRETTY_NAME='Arch Linux'" >"$d/btr/@/usr/lib/os-release"
    echo 'ID=foo' >"$d/rel/usr/lib/os-release"
    for x in win ubu btr data empty rel; do
        PP_CONTENT="" PP_NAME="" PP_SUBVOL=""
        part_peek_dir "$d/$x"
        printf '%s|%s|%s|%s\n' "$x" "$PP_CONTENT" "$PP_NAME" "$PP_SUBVOL"
    done >"$OUT/B.out"
    for t in "" BitLocker apfs swap weirdfs; do
        part_peek /dev/null "$t"
        printf 'fs=%s|%s|%s\n' "$t" "$PP_CONTENT" "$(part_content_text "$PP_CONTENT" "$PP_NAME")"
    done >>"$OUT/B.out"
)
b=$OUT/B.out
expect "B: Windows (velka/mala pismena)"           has "$b" "win|windows|Windows|"
expect "B: Linux z /etc/os-release"                 has "$b" "ubu|os|Ubuntu 24.04.1 LTS|"
expect "B: btrfs: os-release v @, subvolume @home"  has "$b" "btr|os|Arch Linux|@home"
expect "B: soubory bez systemu (data)"              has "$b" "data|data||"
expect "B: jen lost+found = prazdny FS"             has "$b" "empty|empty_fs||"
expect "B: os-release bez PRETTY_NAME -> Linux"     has "$b" "rel|os|Linux|"
expect "B: bez FS = prazdny oddil"                  has "$b" "fs=|empty|Empty (no file system)"
expect "B: BitLocker = Windows"                     has "$b" "fs=BitLocker|bitlocker|Encrypted with BitLocker (Windows)"
expect "B: APFS = macOS"                            has "$b" "fs=apfs|macos|Operating system: macOS"
expect "B: swap"                                    has "$b" "fs=swap|swap|Swap space"
expect "B: neznamy FS = obsah nelze zjistit"        has "$b" "fs=weirdfs|unknown|Contents could not be checked"

# ---------------------------------------------------------------------------------
echo "## C: --probe radky pro GUI (part_probe)"
(
    setup_env "vda:200G vdb:200G"
    standard_disks
    part_probe /dev/vda >"$OUT/C.vda"
    part_probe /dev/vdb >"$OUT/C.vdb"
    rm -rf "$MOCK"
)
expect "C: PART_BOOT_ERR prazdne (UEFI, ESP s mistem)" grep -qx 'PART_BOOT_ERR=' "$OUT/C.vda"
expect "C: PART_ESP=/dev/vda1"                      grep -qx 'PART_ESP=/dev/vda1' "$OUT/C.vda"
expect "C: radek Windows (8 sloupcu, TAB)" grep -qxP '^PART=/dev/vda3\t107374182400\tntfs\tWindows\t\thome_fs\twindows\tWindows$' "$OUT/C.vda"
expect "C: radek data"                     grep -qxP '^PART=/dev/vda4\t64424509440\text4\tData\t\t\tdata\t$' "$OUT/C.vda"
expect "C: ESP bez nahledu obsahu"         grep -qxP '^PART=/dev/vda1\t536870912\tvfat\tSYSTEM\tesp\tesp\t\t$' "$OUT/C.vda"
expect "C: vsech 7 oddilu vda"             test "$(grep -c '^PART=' "$OUT/C.vda")" -eq 7
expect "C: ESP z jineho disku pro vdb"     grep -qx 'PART_ESP=/dev/vda1' "$OUT/C.vdb"
expect "C: btrfs jineho Linuxu: Fedora"    grep -qP '^PART=/dev/vdb7\t.*\tos\tFedora Linux 42$' "$OUT/C.vdb"

# ---------------------------------------------------------------------------------
# Jeden beh instalace do oddilu: part_setup -> summary -> layout_apply -> crypttab/fstab/cmdline -> configure_system
run_case() {  # run_case JMENO PRIPRAVA(bash)
    local name=$1 prep=$2 dir=$OUT/$1
    mkdir -p "$dir"
    (
        setup_env "vda:200G vdb:200G vdc:100G"
        trap 'echo "ERR radek $LINENO (prikaz: $BASH_COMMAND)" >>"$dir/err"' ERR
        standard_disks
        DISK_MODE=partition
        eval "$prep"
        fail() { printf '%s\n' "$*" >"$dir/fail"; cp "$MOCK/cmds" "$dir/cmds"; exit 3; }
        info() { printf 'INFO %s\n' "$*" >>"$dir/info"; }
        progress() { ((PROGRESS)) && printf '@@%s\n' "$*"; return 0; }
        part_setup
        printf '%s\n' "$LAYOUT" >"$dir/layout"
        printf '%s\n' "${LY_WARN[@]}" >"$dir/warnings"
        # souhrn (bez gum: --progress --yes)
        PROGRESS=1 ASSUME_YES=1 LOCALE=cs_CZ.UTF-8 XKB_LAYOUT=cz XKB_VARIANT="" TIMEZONE=Europe/Prague
        FULLNAME="Jana" USERNAME=jana HOSTNAME_SEL=pc CARE_MODE=carefree LUXAI_ACCOUNT=""
        templates_text() { echo "-"; }; care_text() { echo "carefree"; }
        summary >"$dir/summary"
        PROGRESS=0
        : >"$MOCK/cmds"   # od ted jen prikazy instalace
        part_check "$ROOT_PART"; [[ -z $PC_ROOT_ERR ]]
        for t in "$MOCK"/disks/*.tbl; do echo "== ${t##*/}"; sort -n "$t"; done >"$dir/tables.before"
        part_set_type
        for t in "$MOCK"/disks/*.tbl; do echo "== ${t##*/}"; sort -n "$t"; done >"$dir/tables.after"
        layout_apply >"$dir/apply.out" 2>&1
        layout_write_crypt
        layout_cmdline >"$dir/cmdline"
        layout_hooks >"$dir/hooks"
        printf 'ESP_MOUNT=%s ESP_KEEP=%s ESP_PART=%s ROOTDEV=%s DISK=%s\n' "${ESP_MOUNT-}" "${ESP_KEEP-}" \
            "${ESP_PART-}" "$ROOTDEV" "$DISK" >"$dir/vars"
        cp "$MOCK/cmds" "$dir/cmds"
        cat "$TARGET/etc/crypttab" >"$dir/crypttab" 2>/dev/null || : >"$dir/crypttab"
        cat "$TARGET/etc/crypttab.initramfs" >"$dir/crypttab.initramfs" 2>/dev/null || : >"$dir/crypttab.initramfs"
        # configure_system s nahradami chroot/genfstab: luxos-setup.env, fstab a polozka UEFI
        genfstab() {   # fstab podle pripojeni v $MOCK/cmds + aktivni swap live systemu (musi zmizet)
            local opts dev mp
            while read -r _ _ opts dev mp; do
                [[ $mp == "$TARGET"* ]] || continue
                printf 'UUID=%s\t%s\tauto\t%s\t0 0\n' "$(blkid -s UUID -o value "$dev")" "$(m=${mp#"$TARGET"}; echo "${m:-/}")" "$opts"
            done < <(grep '^mount -o ' "$MOCK/cmds")
            printf 'UUID=live-swap\tnone\tswap\tdefaults\t0 0\n'
        }
        luxos-hwdetect() { :; }
        x11_to_console() { echo cz; }
        install() {
            local dst=${!#}
            if [[ " $* " == *" /dev/stdin "* ]]; then mkdir -p "${dst%/*}"; cat >"$dst"; fi
            return 0
        }
        arch-chroot() { if [[ $2 == /root/luxos-setup.sh ]]; then cp "$TARGET/root/luxos-setup.env" "$dir/setup.env"; else cat >/dev/null; fi; }
        efibootmgr() { echo "efibootmgr $*" >>"$dir/efi"; }
        bootctl() { echo "bootctl $*" >>"$dir/efi"; }
        PASSWORD=x
        configure_system >"$dir/configure.out" 2>&1
        cp "$TARGET/etc/fstab" "$dir/fstab" 2>/dev/null || : >"$dir/fstab"
        layout_teardown
        rm -rf "$MOCK"
        exit 0
    ) </dev/null
    echo $? >"$dir/rc"
}
rc_is() { [[ $(<"$OUT/$1/rc") == "$2" ]]; }
mock_disk_of_t() { local x=${1#/dev/}; [[ $x =~ ^([a-z]+)([0-9]+)$ ]] && echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]}"; }
# Tabulky oddilu: jine oddily beze zmeny, vybrany jen novy kod typu
only_type_changed() {  # only_type_changed CASE DISK N KOD
    local d=$OUT/$1
    diff <(grep -v "^$3 " "$d/tables.before") <(grep -v "^$3 " "$d/tables.after") >/dev/null || return 1
    local b a
    b=$(sed -n "/^== $2.tbl/,/^==/p" "$d/tables.before" | awk -v n="$3" '$1 == n {print $1, $2, $3}')
    a=$(sed -n "/^== $2.tbl/,/^==/p" "$d/tables.after" | awk -v n="$3" '$1 == n {print $1, $2, $3, $4}')
    [[ -n $b && $a == "$b $4" ]]
}

# Prikazy menici disky smi jmenovat jen vybrany oddil (nebo jeho LUKS mapper);
# na disku jen zmena typu prave tohoto oddilu (sgdisk -t N:kod, partx -u --nr N)
only_touches() {  # only_touches CASE DEV [MAPPER]
    local c=$OUT/$1/cmds dev=$2 mapper=${3-} line bad_lines="" disk n
    read -r disk n <<<"$(mock_disk_of_t "$dev")"
    while IFS= read -r line; do
        case $line in
            "sgdisk -v /dev/$disk"|"sgdisk -p /dev/$disk") continue ;;
            "sgdisk -t $n:8304 /dev/$disk"|"sgdisk -t $n:8309 /dev/$disk"|"partx -u --nr $n /dev/$disk") continue ;;
            wipefs*|mkfs.*|mkswap*|cryptsetup\ luksFormat*|cryptsetup\ luksAddKey*|sgdisk*|pvcreate*|vgcreate*|lvcreate*|lvremove*|e2fsck*|resize2fs*|ntfsresize*|"btrfs filesystem resize"*|partx*|partprobe*)
                local devs; devs=$(grep -oE '/dev/[A-Za-z0-9/_-]+' <<<"$line" | sort -u | tr '\n' ' ')
                [[ $devs == "$dev " || ( -n $mapper && $devs == "$mapper " ) ]] || bad_lines+="$line; " ;;
        esac
    done <"$c"
    [[ -z $bad_lines ]] || { echo "      mimo $dev: $bad_lines"; return 1; }
}

echo "## D: bez sifrovani, / na ext4 'Data' (vda4), ESP sdileny"
run_case D 'ROOT_PART=/dev/vda4'
expect "D: probehlo" rc_is D 0
[[ -s $OUT/D/err ]] && bad "D: chyba" "$(cat "$OUT/D/err")"
c=$OUT/D/cmds
expect "D: prikazy menici disk jen na /dev/vda4" only_touches D /dev/vda4
expect "D: tabulka: jen typ vda4 -> Linux root (8304), ostatni beze zmeny" only_type_changed D vda 4 8304
expect "D: zmena typu az po kontrole GPT (sgdisk -v)" grep -q '^sgdisk -v /dev/vda$' "$c"
expect "D: btrfs na /dev/vda4" has "$c" "mkfs.btrfs -f -L LuxOS /dev/vda4"
expect "D: zadny luksFormat" hasnot "$c" "luksFormat"
expect "D: ESP se neformatuje" hasnot "$c" "mkfs.vfat"
expect "D: ESP pripojen v /efi" grep -q "^mount -o fmask=0077,dmask=0077 /dev/vda1 .*/target/efi$" "$c"
expect "D: subvolume @home na / (bez samostatneho /home)" grep -q 'btrfs subvolume create .*/@home$' "$c"
expect "D: cmdline bez LUKS" grep -qx 'root=UUID=fs-uuid-vda4 rootflags=subvol=@' "$OUT/D/cmdline"
expect "D: HOOKS bez sd-encrypt" grep -qx 'ENCRYPT_HOOK=0 LVM_HOOK=0' "$OUT/D/hooks"
expect "D: ESP_MOUNT=/efi ESP_KEEP=1, DISK podle oddilu" has "$OUT/D/vars" "ESP_MOUNT=/efi ESP_KEEP=1 ESP_PART=/dev/vda1 ROOTDEV=/dev/vda4 DISK=/dev/vda"
expect "D: crypttab prazdny" test ! -s "$OUT/D/crypttab" -a ! -s "$OUT/D/crypttab.initramfs"
expect "D: fstab: / a /efi" grep -qP '^UUID=fs-uuid-vda4\t/\t' "$OUT/D/fstab"
expect "D: fstab: /efi" grep -qP '^UUID=fs-uuid-vda1\t/efi\t' "$OUT/D/fstab"
expect "D: fstab: bez swapu (zram)" hasnot "$OUT/D/fstab" "swap"
e=$OUT/D/setup.env
expect "D: env: DISK_MODE=partition" grep -qx 'DISK_MODE=partition' "$e"
expect "D: env: sdileny ESP v /efi bez formatovani" grep -qx 'ESP_MOUNT=/efi' "$e"
expect "D: env: ESP_KEEP=1" grep -qx 'ESP_KEEP=1' "$e"
expect "D: env: ENCRYPT=0 ENCRYPT_HOOK=0" grep -qx 'ENCRYPT_HOOK=0' "$e"
expect "D: env: CMDLINE root=UUID" grep -q '^CMDLINE=.*root=UUID=fs-uuid-vda4\\ rootflags=subvol=@' "$e"
expect "D: polozka UEFI na disk ESP" grep -q 'efibootmgr --create --disk /dev/vda --part 1 --label LuxOS' "$OUT/D/efi"
s=$OUT/D/summary
expect "D: souhrn: rezim a oddil" has "$s" "partition /dev/vda4  (will be ERASED, other partitions are kept)"
expect "D: souhrn: co se smaze vcetne obsahu" has "$s" "! ERASE partition /dev/vda4  64.5GB  ext4  \"Data\": Files (no operating system found)"
expect "D: souhrn: ostatni oddily zustanou" has "$s" "All other partitions are kept unchanged."
expect "D: souhrn: @@ERASE pro GUI" grep -q '^@@ERASE ERASE partition /dev/vda4' "$s"
expect "D: souhrn: bez varovani o systemu" hasnot "$s" "@@WARN"
expect "D: souhrn: /efi zachovany" grep -qE '^ +/efi +vfat +/dev/vda1 \(keep data\)' "$s"
expect "D: souhrn: Sifrovani ne" grep -qE '^ +Encryption +no' "$s"

echo "## E: sifrovani + zachovany /home, / do oddilu s Windows (silne varovani)"
run_case E 'ROOT_PART=/dev/vda3 HOME_PART=/dev/vda6 ENCRYPT=1 LUKS_PASS=tajne'
expect "E: probehlo" rc_is E 0
[[ -s $OUT/E/err ]] && bad "E: chyba" "$(cat "$OUT/E/err")"
c=$OUT/E/cmds
expect "E: prikazy menici disk jen na /dev/vda3 (a cryptroot)" only_touches E /dev/vda3 /dev/mapper/cryptroot
expect "E: tabulka: jen typ vda3 -> Linux LUKS (8309), Windows ostatni beze zmeny" only_type_changed E vda 3 8309
expect "E: LUKS2 na /dev/vda3" has "$c" "cryptsetup luksFormat --type luks2 --batch-mode --offset 32768 --key-file - /dev/vda3"
expect "E: otevren jako cryptroot" grep -q 'cryptsetup open .*--key-file - /dev/vda3 cryptroot$' "$c"
expect "E: btrfs na cryptroot" has "$c" "mkfs.btrfs -f -L LuxOS /dev/mapper/cryptroot"
expect "E: /home se neformatuje" grep -vq 'mkfs.*vda6' "$c"
expect "E: /home pripojen (ext4, noatime)" grep -q '^mount -o noatime /dev/vda6 .*/target/home$' "$c"
expect "E: bez subvolumu @home (samostatny /home)" bash -c "! grep -q 'subvolume create .*/@home' '$c'"
expect "E: crypttab.initramfs pro /" grep -qx 'cryptroot UUID=luks-uuid-vda3 none luks,discard' "$OUT/E/crypttab.initramfs"
expect "E: crypttab bez dalsich svazku" test ! -s "$OUT/E/crypttab"
expect "E: cmdline rd.luks + root" grep -qx 'rd.luks.name=luks-uuid-vda3=cryptroot rd.luks.options=discard root=UUID=fs-uuid-mapper_cryptroot rootflags=subvol=@' "$OUT/E/cmdline"
expect "E: HOOKS sd-encrypt" grep -qx 'ENCRYPT_HOOK=1 LVM_HOOK=0' "$OUT/E/hooks"
expect "E: env ENCRYPT_HOOK=1" grep -qx 'ENCRYPT_HOOK=1' "$OUT/E/setup.env"
expect "E: fstab: /home zachovany" grep -qP '^UUID=fs-uuid-vda6\t/home\t' "$OUT/E/fstab"
expect "E: varovani: /home nesifrovany" grep -q '^enc_mismatch|/home' "$OUT/E/warnings"
expect "E: heslo neni v LAYOUT" hasnot "$OUT/E/layout" "tajne"
s=$OUT/E/summary
expect "E: souhrn: Windows bude smazan" has "$s" "! ERASE partition /dev/vda3  107.4GB  ntfs  \"Windows\": Operating system: Windows"
expect "E: souhrn: silne varovani" has "$s" "!! WARNING: /dev/vda3 contains Windows. It will be deleted and will no longer start."
expect "E: souhrn: @@WARN pro GUI" grep -q '^@@WARN WARNING: /dev/vda3 contains Windows' "$s"
expect "E: souhrn: /home keep data" grep -qE '^ +/home +ext4 +/dev/vda6 \(keep data\)' "$s"
expect "E: souhrn: Sifrovani ano" grep -qE '^ +Encryption +yes' "$s"
expect "E: souhrn: heslo neni ve vystupu" hasnot "$s" "tajne"

echo "## F: /home z btrfs jineho Linuxu (subvolume @home), / na vdc bez ESP (ESP z vda)"
run_case F 'addp vdc 1 51200 8300 ext4 Empty; content /dev/vdc1 empty; ROOT_PART=/dev/vdc1 HOME_PART=/dev/vdb7'
expect "F: probehlo" rc_is F 0
c=$OUT/F/cmds
expect "F: prikazy menici disk jen na /dev/vdc1" only_touches F /dev/vdc1
expect "F: LAYOUT: /home subvol=@home bez formatovani" has "$OUT/F/layout" "fs on=home mount=/home type=btrfs format=0 subvol=@home"
expect "F: /home pripojen se subvol=@home" grep -q '^mount -o noatime,compress=zstd:1,subvol=@home /dev/vdb7 .*/target/home$' "$c"
expect "F: ESP z jineho disku (vda1)" has "$OUT/F/vars" "ESP_PART=/dev/vda1"
expect "F: polozka UEFI na disk s ESP" grep -q 'efibootmgr --create --disk /dev/vda --part 1' "$OUT/F/efi"
expect "F: souhrn: prazdny FS" has "$OUT/F/summary" "Empty file system"

echo "## G: BIOS bez zavadece (BOOTLOADER=none) - bez ESP"
run_case G 'BOOTMODE=bios BOOTLOADER=none ROOT_PART=/dev/vda4'
expect "G: probehlo" rc_is G 0
expect "G: LAYOUT bez /efi" hasnot "$OUT/G/layout" "/efi"
expect "G: prikazy jen na /dev/vda4" only_touches G /dev/vda4

echo "## H: chyby (nic se nezmeni)"
err_case() {  # err_case JMENO PRIPRAVA OCEKAVANY_TEXT
    run_case "$1" "$2"
    if rc_is "$1" 3 && has "$OUT/$1/fail" "$3"; then ok "H: $1: $3"; else bad "H: $1" "rc=$(<"$OUT/$1/rc") fail=$(cat "$OUT/$1/fail" 2>/dev/null)"; fi
    local c=$OUT/$1/cmds
    if [[ -e $c ]] && grep -qE '^(wipefs|mkfs|cryptsetup luksFormat|sgdisk -[ndtcoZ]|mount)' "$c"; then bad "H: $1: neco se zmenilo" "$(cat "$c")"
    else ok "H: $1: zadna zmena disku"; fi
}
err_case H1 'ROOT_PART=/dev/vda1' "/dev/vda1 cannot be used for LuxOS: EFI system partition"
err_case H2 'ROOT_PART=/dev/vdb4' "/dev/vdb4 cannot be used for LuxOS: in use (mounted)"
err_case H3 'ROOT_PART=/dev/vda6' "/dev/vda6 cannot be used for LuxOS: smaller than 20 GB"
err_case H4 'ROOT_PART=/dev/vdb2' "/dev/vdb2 cannot be used for LuxOS: part of LVM"
err_case H5 'ROOT_PART=/dev/vda4 HOME_PART=/dev/vda4' "/dev/vda4 cannot be used as /home: already chosen for LuxOS"
err_case H6 'ROOT_PART=/dev/vda4 HOME_PART=/dev/vda3' "/dev/vda3 cannot be used as /home: no Linux file system for /home"
err_case H7 'ROOT_PART=/dev/vda4 HOME_PART=/dev/vdb1' "/dev/vdb1 cannot be used as /home: encrypted (LUKS)"
err_case H8 'BOOTMODE=bios ROOT_PART=/dev/vda4' "needs a computer started in UEFI mode"
err_case H9 'addp vdc 1 51200 8300 ext4; content /dev/vdc1 empty; ROOT_PART=/dev/vdc1; rm -f "$MOCK/disks/vda.tbl" "$MOCK/disks/vda.size"' "No EFI system partition found"
err_case H10 'echo $((100 * 1000 * 1000)) >"$MOCK/espfree/vda1"; ROOT_PART=/dev/vda4' "/dev/vda1 has less than 250 MB free"
err_case H11 ': >"$MOCK/espbad"; ROOT_PART=/dev/vda4' "/dev/vda1 could not be read"
err_case H12 'ROOT_PART=/dev/vda4 ENCRYPT=1 LUKS_PASS=""' "Enter a passphrase"
err_case H13 'ROOT_PART=""' "DISK_MODE=partition needs ROOT_PART"

echo "## J: textovy instalator (ask_partition) s nahradou gum"
(
    setup_env "vda:200G vdb:200G"
    standard_disks
    extract ask_partition >"$OUT/ask.sh"; . "$OUT/ask.sh"
    info() { printf 'INFO %s\n' "$*" >>"$OUT/J.info"; }
    fail() { echo "FAIL $*" >>"$OUT/J.info"; exit 3; }
    # gum choose: polozky do souboru, vyber podle vzoru PICK1, PICK2 (n-te volani)
    echo 0 >"$OUT/J.n"
    gum() {   # bezi v podshellu $(...) - pocitadlo volani v souboru
        local pat item n; n=$(($(<"$OUT/J.n") + 1)); echo "$n" >"$OUT/J.n"; pat=PICK$n
        shift
        while (($#)); do case $1 in --header) shift ;; *) printf '%s\n' "$1" >>"$OUT/J.items$n"; esac; shift; done
        while IFS= read -r item; do [[ $item == ${!pat} ]] && { echo "$item"; return 0; }; done <"$OUT/J.items$n"
        return 1
    }
    PICK1='/dev/vda3 *' PICK2='/dev/vda6 *'
    ask_partition
    printf 'ROOT_PART=%s HOME_PART=%s DISK=%s\n' "$ROOT_PART" "$HOME_PART" "$DISK" >"$OUT/J.vars"
    rm -rf "$MOCK"
)
expect "J: vybran / a /home" grep -qx 'ROOT_PART=/dev/vda3 HOME_PART=/dev/vda6 DISK=/dev/vda' "$OUT/J.vars"
expect "J: nabidka / jen vhodne oddily (vda3, vda4, vdb7)" test "$(cut -c1-9 "$OUT/J.items1" | tr '\n' ' ')" == "/dev/vda3 /dev/vda4 /dev/vdb7 "
expect "J: nabidka / s obsahem" grep -q '^/dev/vda3 .*Operating system: Windows$' "$OUT/J.items1"
expect "J: /home: moznost bez /home + ext4/btrfs mimo /" test "$(cut -c1-9 "$OUT/J.items2" | tr '\n' ' ')" == "No - keep /dev/vda4 /dev/vda6 /dev/vdb7 "
expect "J: nepouzitelne oddily s duvodem" grep -q 'INFO   /dev/vda1 .*(EFI system partition)' "$OUT/J.info"
expect "J: maly oddil s duvodem" grep -q 'INFO   /dev/vda6 .*(smaller than 20 GB)' "$OUT/J.info"

echo "## I: luxos-install: neplatny rezim a napoveda (bez roota)"
I18N=$(cd "$HERE/../../luxos-i18n/files" && pwd)
expect "I: DISK_MODE=partition v hlaseni o neplatnem rezimu" grep -q 'use erase, freespace, partition, layout or manual' "$FILES/luxos-install"
expect "I: bash -n luxos-install" bash -n "$FILES/luxos-install"
extract interactive >>"$OUT/lib.sh"; extract main >>"$OUT/lib.sh"
missing=$(grep -ohE '\bT "[^"$]+"' "$OUT/lib.sh" | sed -E 's/^T "//; s/"$//' | sort -u | while IFS= read -r k; do
    grep -qF -- "$k"$'\t' "$I18N/cs.tsv" || echo "$k"; done)
if [[ -z $missing ]]; then ok "I: vsechny texty rezimu maji cesky preklad"; else bad "I: chybi cesky preklad" "$missing"; fi

echo
echo "Vysledek: $NPASS ok, $NFAIL FAIL"
[[ -n ${KEEP-} ]] || { ((NFAIL)) || rm -rf "$OUT"; }
exit "$NFAIL"
