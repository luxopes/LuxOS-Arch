#!/bin/bash
# LuxOS installer - testy rucniho rozdeleni (layout.sh, luxos_layout.py) BEZ roota a bez disku.
# Diskove prikazy nahrazuje mock-env.sh (emulace GPT, LUKS, LVM); kontroluje se poradi prikazu,
# crypttab, crypttab.initramfs, klice, fstab (swap), cmdline, HOOKS a kontrola LAYOUT v bash i Pythonu.
#
#   packages/luxos-installer/tests/test-layout.sh          (vypis ok/FAIL, navratovy kod = pocet chyb)
#   KEEP=1 tests/test-layout.sh                            (ponecha vystupy v $OUT)
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
FILES=$(cd "$HERE/../files" && pwd)
OUT=$(mktemp -d "${TMPDIR:-/tmp}/luxos-layout-test.XXXXXX")
export TMPDIR=$OUT
NPASS=0 NFAIL=0

ok()  { NPASS=$((NPASS + 1)); printf 'ok    %s\n' "$1"; }
bad() { NFAIL=$((NFAIL + 1)); printf 'FAIL  %s\n' "$1"; [[ -n ${2-} ]] && printf '      %s\n' "$2"; return 0; }
expect() {  # expect "popis" prikaz... (uspech = ok)
    local d=$1; shift
    if "$@"; then ok "$d"; else bad "$d"; fi
}
has()    { grep -qF -- "$2" "$1"; }                # soubor obsahuje text
hasnot() { ! grep -qF -- "$2" "$1" 2>/dev/null; }
before() {  # before SOUBOR TEXT1 TEXT2: prvni vyskyt TEXT1 je pred prvnim TEXT2
    local a b
    a=$(grep -nF -- "$2" "$1" | head -1 | cut -d: -f1)
    b=$(grep -nF -- "$3" "$1" | head -1 | cut -d: -f1)
    [[ -n $a && -n $b && $a -lt $b ]]
}

# Rozlozeni z GUI modelu (predvolby) - stejny kod jako graficky instalator
py_layout() {  # py_layout PRESET DISK VELIKOST_GIB BOOTMODE [ram_gib]
    python3 -I - "$FILES" "$@" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import luxos_layout as m
preset, disk, gib, bootmode = sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
ram = int(sys.argv[6]) * m.GiB if len(sys.argv) > 6 else 0
scan = {"bootmode": bootmode, "vgs": [],
        "disks": [{"path": disk, "name": disk[5:], "size": gib * m.GiB, "parts": [], "model": "", "pttype": ""}]}
L = m.Layout(scan)
L.preset(disk, preset, ram=ram)
L.passphrase = "x"
errs = [c for lvl, c, d in L.validate() if lvl == "error"]
if errs:
    print("PYERR", *errs, file=sys.stderr)
sys.stdout.write(L.to_text())
PY
}

# Jeden scenar v podshellu: emulace disku, kontrola, provedeni, konfiguracni soubory
scenario() {  # scenario JMENO BOOTMODE "vda:64G ..." LAYOUT [PRIPRAVA (bash kod)]
    local name=$1 bm=$2 disks=$3 layout=$4 prep=${5-}
    local dir=$OUT/$name
    mkdir -p "$dir"
    (
        # stejne volby shellu jako luxos-install (chyba = konec s radkem)
        set -Eeuo pipefail
        trap 'echo "ERR radek $LINENO (prikaz: $BASH_COMMAND)" >>"$dir/apply.out"' ERR
        . "$FILES/layout.sh"
        . "$HERE/mock-env.sh"
        # shellcheck disable=SC2086
        mock_init $disks
        TARGET=$MOCK/target
        mkdir -p "$TARGET/etc"
        BOOTMODE=$bm BOOTLOADER=auto LUKS_PASS=${LUKS_PASS-heslo1}
        eval "$prep"
        layout_parse "$layout"
        layout_validate
        ((${#LY_ERR[@]})) || layout_check_devices
        printf '%s\n' "${LY_ERR[@]}" >"$dir/errors"
        printf '%s\n' "${LY_WARN[@]}" >"$dir/warnings"
        ((${#LY_ERR[@]} == 0)) || { cp "$MOCK/cmds" "$dir/cmds"; exit 3; }
        layout_destroy_list >"$dir/destroy"
        layout_steps >"$dir/steps"
        layout_packages >"$dir/packages"
        layout_apply >"$dir/apply.out" 2>&1 || exit 4
        layout_write_crypt
        layout_fstab_swap >"$dir/fstab_swap"
        layout_cmdline >"$dir/cmdline"
        layout_hooks >"$dir/hooks"
        printf 'ESP_MOUNT=%s ESP_KEEP=%s GRUB_DISK=%s ROOTDEV=%s\n' "${ESP_MOUNT-}" "${ESP_KEEP-}" "${GRUB_DISK-}" "$ROOTDEV" >"$dir/vars"
        cp "$MOCK/cmds" "$dir/cmds"
        cat "$TARGET/etc/crypttab" >"$dir/crypttab" 2>/dev/null || : >"$dir/crypttab"
        cat "$TARGET/etc/crypttab.initramfs" >"$dir/crypttab.initramfs" 2>/dev/null || : >"$dir/crypttab.initramfs"
        ls -l "$TARGET/etc/cryptsetup-keys.d" >"$dir/keys" 2>/dev/null || : >"$dir/keys"
        stat -c '%a' "$TARGET/etc/cryptsetup-keys.d" >"$dir/keydir_mode" 2>/dev/null || :
        ls "$MOCK/keys" >"$dir/keyslots" 2>/dev/null || :
        cat "$MOCK/passes" >"$dir/passes" 2>/dev/null || :
        for t in "$MOCK"/disks/*.tbl; do echo "== ${t##*/}"; cat "$t"; done >"$dir/tables"
        layout_teardown
        rm -rf "$MOCK"
        exit 0
    ) </dev/null
    echo $? >"$dir/rc"
}

rc_is() { [[ $(<"$OUT/$1/rc") == "$2" ]]; }
err_is() { grep -q "^$2|" "$OUT/$1/errors"; }
warn_is() { grep -q "^$2|" "$OUT/$1/warnings"; }

echo "# vystupy: $OUT"

# ---------------------------------------------------------------------------------
echo "## A: predvolba Sifrovane LVM (/, /home, swap), UEFI, 64 GiB"
LA=$(py_layout lvm /dev/vda 64 uefi 8 2>"$OUT/A.pyerr")
expect "A: GUI model bez chyb" test ! -s "$OUT/A.pyerr"
scenario A uefi "vda:64G" "$LA"
expect "A: probehlo" rc_is A 0
c=$OUT/A/cmds
expect "A: disk smazan a nova GPT" before "$c" "sgdisk --zap-all /dev/vda" "sgdisk -o /dev/vda"
expect "A: ESP 1 GiB jako oddil 1 (EF00)" grep -q '^1 2048 2099199 ef00 EFI$' "$OUT/A/tables"
expect "A: LUKS oddil 2 (8309) do konce disku" grep -qE '^2 2099200 134217694 8309 LuxOS$' "$OUT/A/tables"
expect "A: luksFormat LUKS2 na /dev/vda2" has "$c" "cryptsetup luksFormat --type luks2 --batch-mode --offset 32768 --key-file - /dev/vda2"
expect "A: open jako cryptlvm" has "$c" "--persistent --key-file - /dev/vda2 cryptlvm"
expect "A: PV na /dev/mapper/cryptlvm" has "$c" "pvcreate -ff -y /dev/mapper/cryptlvm"
expect "A: vgcreate luxos" has "$c" "vgcreate -y luxos /dev/mapper/cryptlvm"
expect "A: home = zbytek, az po root a swap" before "$c" "-n swap luxos" "-l 100%FREE -n home luxos"
expect "A: root LV pred home" before "$c" "-n root luxos" "-n home luxos"
expect "A: ESP FAT32" has "$c" "mkfs.vfat -F32 -n EFI /dev/vda1"
expect "A: btrfs na luxos-root" has "$c" "mkfs.btrfs -f -L LuxOS /dev/mapper/luxos-root"
expect "A: mkswap na luxos-swap" has "$c" "mkfs.swap -L swap /dev/mapper/luxos-swap"
expect "A: / pripojeno pred /boot" before "$c" "subvol=@ /dev/mapper/luxos-root" "dmask=0077 /dev/vda1"
expect "A: /home pripojen" has "$c" "mount -o noatime,compress=zstd:1 /dev/mapper/luxos-home"
expect "A: bez subvolumu @home (samostatny /home)" hasnot "$c" "subvolume create $OUT/A"/"@home"
expect "A: crypttab.initramfs" has "$OUT/A/crypttab.initramfs" "cryptlvm UUID=luks-uuid-vda2 none luks,discard"
expect "A: /etc/crypttab prazdny (vse v initramfs)" test ! -s "$OUT/A/crypttab"
expect "A: cmdline" test "$(<"$OUT/A/cmdline")" == "rd.luks.name=luks-uuid-vda2=cryptlvm rd.luks.options=discard root=UUID=fs-uuid-mapper_luxos-root rootflags=subvol=@"
expect "A: HOOKS sd-encrypt + lvm2" test "$(<"$OUT/A/hooks")" == "ENCRYPT_HOOK=1 LVM_HOOK=1"
expect "A: swap ve fstab podle UUID" has "$OUT/A/fstab_swap" "UUID=fs-uuid-mapper_luxos-swap"
expect "A: 4 kroky pripravy (disky, sifrovani, LVM, FS)" test "$(<"$OUT/A/steps")" == 4
expect "A: @@STEP kroky v poradi" test "$(grep -c '^@@STEP' "$c")" == 4
expect "A: balik lvm2" test "$(<"$OUT/A/packages")" == lvm2
expect "A: ESP /boot, novy" grep -q 'ESP_MOUNT=/boot ESP_KEEP=0' "$OUT/A/vars"
expect "A: souhrn: smazani celeho disku" has "$OUT/A/destroy" "ERASE the whole disk /dev/vda"
expect "A: heslo jen pres stdin" hasnot "$c" "heslo1"

# ---------------------------------------------------------------------------------
echo "## B: predvolba s /var a /tmp, BIOS, 40 GiB"
LB=$(py_layout lvm_var /dev/vda 40 bios 2>"$OUT/B.pyerr")
expect "B: GUI model bez chyb" test ! -s "$OUT/B.pyerr"
scenario B bios "vda:40G" "$LB"
expect "B: probehlo" rc_is B 0
c=$OUT/B/cmds
expect "B: BIOS boot oddil EF02" grep -q '^1 2048 4095 ef02 BIOS$' "$OUT/B/tables"
expect "B: nesifrovany /boot ext4" has "$c" "mkfs.ext4 -F -L boot /dev/vda2"
expect "B: GRUB na /dev/vda" grep -q 'GRUB_DISK=/dev/vda ' "$OUT/B/vars"
expect "B: LV var a tmp" has "$c" "-n var luxos"
expect "B: /tmp nosuid,nodev" has "$c" "mount -o noatime,nosuid,nodev /dev/mapper/luxos-tmp"
expect "B: bez @log/@cache (samostatny /var)" hasnot "$c" "/@cache"
expect "B: / pripojeno pred /var" before "$c" "subvol=@ " "mount -o noatime,compress=zstd:1 /dev/mapper/luxos-var"
expect "B: varovani maly /" warn_is B root_small_warn

# ---------------------------------------------------------------------------------
echo "## C: LUKS na LVM pres dva disky (kazdy LV vlastni LUKS)"
LC='
disk dev=/dev/vda table=new
disk dev=/dev/vdb table=new
part id=esp disk=/dev/vda size=512M type=esp
part id=pv1 disk=/dev/vda size=rest
part id=pv2 disk=/dev/vdb size=rest
vg   id=vg name=data-vg pvs=pv1,pv2
lv   id=lroot vg=vg name=root size=20G
lv   id=lswap vg=vg name=swap size=2G
lv   id=lhome vg=vg name=home size=rest
luks id=croot on=lroot name=cryptroot
luks id=chome on=lhome name=crypthome
luks id=cswap on=lswap name=cryptswap
fs   on=esp mount=/boot type=vfat
fs   on=croot mount=/ type=ext4
fs   on=chome mount=/home type=xfs
swap on=cswap
'
LUKS_PASS_CHOME=heslo2 scenario C uefi "vda:64G vdb:32G" "$LC"
expect "C: probehlo" rc_is C 0
c=$OUT/C/cmds
expect "C: VG ze dvou PV" has "$c" "vgcreate -y data-vg /dev/vda2 /dev/vdb1"
expect "C: LUKS na LV (jmeno s pomlckou v mapperu)" has "$c" "luksFormat --type luks2 --batch-mode --offset 32768 --key-file - /dev/mapper/data--vg-root"
expect "C: LV az pred LUKS" before "$c" "-n home data-vg" "luksFormat --type luks2 --batch-mode --offset 32768 --key-file - /dev/mapper/data--vg-home"
expect "C: xfs na /home" has "$c" "mkfs.xfs -f -L home /dev/mapper/crypthome"
expect "C: initramfs jen cryptroot" test "$(grep -vc '^#' "$OUT/C/crypttab.initramfs")" == 1
expect "C: cryptroot v initramfs" has "$OUT/C/crypttab.initramfs" "cryptroot UUID=luks-uuid-mapper_data--vg-root none luks,discard"
expect "C: crypthome klicem z /etc/cryptsetup-keys.d" has "$OUT/C/crypttab" "crypthome UUID=luks-uuid-mapper_data--vg-home /etc/cryptsetup-keys.d/crypthome.key luks,discard"
expect "C: cryptswap klicem" has "$OUT/C/crypttab" "cryptswap UUID=luks-uuid-mapper_data--vg-swap /etc/cryptsetup-keys.d/cryptswap.key luks,discard"
expect "C: klic pridan do crypthome (luksAddKey)" test -e "$OUT/C/../C/keyslots" -a -n "$(grep -x 'mapper_data--vg-home' "$OUT/C/keyslots")"
expect "C: klice 0400, adresar 0700" bash -c "grep -c '^-r--------' '$OUT/C/keys' | grep -qx 2 && grep -qx 700 '$OUT/C/keydir_mode'"
expect "C: luksAddKey s vlastnim heslem /home" grep -qx heslo2 "$OUT/C/passes"
expect "C: cmdline jen root" test "$(<"$OUT/C/cmdline")" == "rd.luks.name=luks-uuid-mapper_data--vg-root=cryptroot rd.luks.options=discard root=UUID=fs-uuid-mapper_cryptroot"
expect "C: HOOKS sd-encrypt + lvm2" test "$(<"$OUT/C/hooks")" == "ENCRYPT_HOOK=1 LVM_HOOK=1"
expect "C: ext4 root bez rootflags" hasnot "$OUT/C/cmdline" rootflags
expect "C: baliky lvm2 + xfsprogs" test "$(tr '\n' ' ' <"$OUT/C/packages")" == "lvm2 xfsprogs "

# ---------------------------------------------------------------------------------
echo "## D: nesifrovany /, sifrovany /home a swap s nahodnym klicem"
LD='
disk dev=/dev/sda table=new
part id=esp  disk=/dev/sda size=1G type=esp
part id=root disk=/dev/sda size=30G
part id=sw   disk=/dev/sda size=4G
part id=home disk=/dev/sda size=rest
luks id=ch on=home name=crypthome
luks id=cs on=sw name=cryptswap
fs   on=esp mount=/efi type=vfat
fs   on=root mount=/ type=f2fs
fs   on=ch mount=/home type=btrfs
swap on=cs
'
scenario D uefi "sda:100G" "$LD"
expect "D: probehlo" rc_is D 0
c=$OUT/D/cmds
expect "D: varovani / a /home sifrovane ruzne" warn_is D enc_mismatch
expect "D: swap bez luksFormat" hasnot "$c" "luksFormat --type luks2 --batch-mode --offset 32768 --key-file - /dev/sda3"
expect "D: swap partuuid a nahodny klic" has "$OUT/D/crypttab" "cryptswap PARTUUID=partuuid-sda3 /dev/urandom swap,cipher=aes-xts-plain64,size=512,sector-size=4096"
expect "D: /home se zepta na heslo" has "$OUT/D/crypttab" "crypthome UUID=luks-uuid-sda4 none luks,discard"
expect "D: zadny klic (nesifrovany /)" test ! -s "$OUT/D/keys"
expect "D: swap ve fstab pres mapper" has "$OUT/D/fstab_swap" "/dev/mapper/cryptswap"
expect "D: bez crypttab.initramfs" test ! -s "$OUT/D/crypttab.initramfs"
expect "D: HOOKS bez sd-encrypt/lvm2" test "$(<"$OUT/D/hooks")" == "ENCRYPT_HOOK=0 LVM_HOOK=0"
expect "D: cmdline bez rd.luks" hasnot "$OUT/D/cmdline" "rd.luks"
expect "D: ESP v /efi" grep -q 'ESP_MOUNT=/efi ESP_KEEP=0' "$OUT/D/vars"
expect "D: f2fs-tools" has "$OUT/D/packages" f2fs-tools
expect "D: 3 kroky (bez LVM)" test "$(<"$OUT/D/steps")" == 3

# ---------------------------------------------------------------------------------
echo "## E: zachovani Windows: ESP bez formatovani, zmenseni NTFS, smazani oddilu"
PREP_E='
cat >"$MOCK/disks/sda.tbl" <<T
1 2048 616447 ef00 EFI
2 616448 420046847 0700 Windows
3 420046848 629762047 8300 Data
T
echo vfat >"$MOCK/fs/sda1"; echo ntfs >"$MOCK/fs/sda2"; echo ext4 >"$MOCK/fs/sda3"
mkdir -p "$MOCK/size"; echo $((300 * 1024 * 1024 + 2048 * 512)) >"$MOCK/size/sda1"
echo $((200 * 1024 ** 3)) >"$MOCK/size/sda2"
'
LE='
use    id=winesp dev=/dev/sda1
use    id=win dev=/dev/sda2 resize=150G
delete dev=/dev/sda3
part   id=root disk=/dev/sda size=rest
fs     on=winesp mount=/efi type=vfat format=0
fs     on=root mount=/ type=btrfs
'
scenario E uefi "sda:500G" "$LE" "$PREP_E"
expect "E: probehlo" rc_is E 0
c=$OUT/E/cmds
expect "E: NTFS se nejdriv zkusi (no-action)" before "$c" "ntfsresize --no-action" "ntfsresize --force --size"
expect "E: zmenseni FS pred oddilem" before "$c" "ntfsresize --force --size 161061273600 /dev/sda2" "sgdisk -d 2 -n 2:616448:"
expect "E: oddil 2 se stejnym zacatkem, typem a PARTUUID" has "$c" "-t 2:00000000-0000-0000-0000-000000000700 -u 2:11111111-2222-3333-4444-000000000002 -c 2:Windows"
expect "E: zmenseni pred smazanim" before "$c" "sgdisk -d 2 -n" "sgdisk -d 3 /dev/sda"
expect "E: smazani pred novym oddilem" before "$c" "sgdisk -d 3 /dev/sda" "sgdisk -n 3:0:0"
expect "E: ESP se neformatuje" hasnot "$c" "mkfs.vfat"
expect "E: ESP zachovany v /efi" grep -q 'ESP_MOUNT=/efi ESP_KEEP=1' "$OUT/E/vars"
expect "E: Windows oddil zustal (velikost 150 GiB)" grep -qE '^2 616448 315189247 ' "$OUT/E/tables"
expect "E: souhrn: zmenseni a smazani" bash -c "grep -q 'Resize /dev/sda2 to 150G' '$OUT/E/destroy' && grep -q 'DELETE partition /dev/sda3' '$OUT/E/destroy'"
expect "E: souhrn: ESP se neformatuje" hasnot "$OUT/E/destroy" "/dev/sda1"
expect "E: nesifrovany btrfs root" test "$(<"$OUT/E/cmdline")" == "root=UUID=fs-uuid-sda3 rootflags=subvol=@"

# ---------------------------------------------------------------------------------
echo "## F: existujici sifrovany disk se starou VG (odemknout, /home ponechat) + novy sifrovany /"
PREP_F='
cat >"$MOCK/disks/vdb.tbl" <<T
1 2048 1050623 ef00 EFI
2 1050624 67108830 8309 LuxOS
T
printf stare >"$MOCK/luks/vdb2"; echo vfat >"$MOCK/fs/vdb1"
echo /dev/mapper/x >"$MOCK/vg/oldvg"; : >"$MOCK/lv/oldvg-home"; : >"$MOCK/lv/oldvg-root"
'
LF='
disk dev=/dev/vda table=new
part id=esp disk=/dev/vda size=1G type=esp
part id=r disk=/dev/vda size=rest
luks id=cr on=r name=cryptroot
use  id=old dev=/dev/vdb2
luks id=co on=old name=cryptold keep=1
vg   id=ovg name=oldvg keep=1
lv   id=oh vg=ovg name=home keep=1
delete dev=/dev/oldvg/root
fs   on=esp mount=/boot type=vfat
fs   on=cr mount=/ type=btrfs
fs   on=oh mount=/home type=ext4 format=0
'
LUKS_PASS_CO=stare LUKS_PASS=nove scenario F uefi "vda:40G vdb:32G" "$LF" "$PREP_F"
expect "F: probehlo" rc_is F 0
c=$OUT/F/cmds
expect "F: stary LUKS jen otevren (bez luksFormat)" hasnot "$c" "luksFormat --type luks2 --batch-mode --offset 32768 --key-file - /dev/vdb2"
expect "F: stary LUKS otevren jako cryptold" has "$c" "cryptsetup open --allow-discards --key-file - /dev/vdb2 cryptold"
expect "F: VG aktivovana" has "$c" "vgchange -ay oldvg"
expect "F: /home bez formatovani" hasnot "$c" "mkfs.ext4"
expect "F: /home klicem (koren je sifrovany)" has "$OUT/F/crypttab" "cryptold UUID=luks-uuid-vdb2 /etc/cryptsetup-keys.d/cryptold.key luks,discard"
expect "F: lvm2 balik, ale ne lvm2 hook" bash -c "grep -qx lvm2 '$OUT/F/packages' && test \"\$(cat '$OUT/F/hooks')\" = 'ENCRYPT_HOOK=1 LVM_HOOK=0'"
expect "F: souhrn nic z vdb nesmaze" hasnot "$OUT/F/destroy" "vdb"
expect "F: souhrn: smazani stareho LV" has "$OUT/F/destroy" "DELETE logical volume oldvg/root"
expect "F: LV se maze az po odemceni" before "$c" "/dev/vdb2 cryptold" "lvremove -y /dev/oldvg/root"
expect "F: LV se maze pred novym LUKS" before "$c" "lvremove -y /dev/oldvg/root" "luksFormat"
expect "F: mazani LV nedeaktivuje skupinu" hasnot "$c" "vgchange -an oldvg"
LUKS_PASS_CO=spatne LUKS_PASS=nove scenario F2 uefi "vda:40G vdb:32G" "$LF" "$PREP_F"
expect "F2: spatne heslo stareho LUKS odhaleno pred zmenami" bash -c "rc=\$(cat '$OUT/F2/rc'); [[ \$rc == 3 ]] && grep -q '^luks_open|/dev/vdb2' '$OUT/F2/errors'"

# ---------------------------------------------------------------------------------
echo "## G: chyby a varovani kontroly (bash)"
vcheck() {  # vcheck POPIS BOOTMODE KOD LAYOUT  -> kontrola obsahuje KOD
    local d=$1 bm=$2 code=$3 lay=$4
    local got
    got=$(
        set -Eeuo pipefail; trap 'echo "ERR radek $LINENO: $BASH_COMMAND"' ERR
        . "$FILES/layout.sh"
        T() { local f=$1; shift; printf -- "$f" "$@"; }
        BOOTMODE=$bm BOOTLOADER=auto LUKS_PASS=${LUKS_PASS-x}
        layout_parse "$lay"; layout_validate
        printf '%s\n' "${LY_ERR[@]}" "${LY_WARN[@]}" | cut -d'|' -f1
    )
    if grep -qx "$code" <<<"$got"; then ok "G: $d ($code)"; else bad "G: $d ($code)" "dostal: $(tr '\n' ' ' <<<"$got")"; fi
}
BASE_ESP='part id=esp disk=/dev/vda size=1G type=esp
fs on=esp mount=/boot type=vfat'
vcheck "chybi /" uefi no_root "$BASE_ESP"
vcheck "chybi ESP" uefi esp_missing $'part id=r disk=/dev/vda size=rest\nfs on=r mount=/'
vcheck "maly ESP" uefi esp_small $'part id=esp disk=/dev/vda size=100M type=esp\nfs on=esp mount=/boot type=vfat\npart id=r disk=/dev/vda size=rest\nfs on=r mount=/'
vcheck "ESP na LUKS" uefi esp_not_part $'part id=e disk=/dev/vda size=1G\nluks id=c on=e name=x\nfs on=c mount=/boot type=vfat\npart id=r disk=/dev/vda size=rest\nfs on=r mount=/'
vcheck "/boot vfat bez typu ESP" uefi esp_type $'part id=e disk=/dev/vda size=1G\nfs on=e mount=/boot type=vfat\npart id=r disk=/dev/vda size=rest\nfs on=r mount=/'
vcheck "ESP v /boot a dalsi /boot" uefi dup_mount "$BASE_ESP"$'\npart id=b disk=/dev/vda size=1G\nfs on=b mount=/boot type=ext4\npart id=r disk=/dev/vda size=rest\nfs on=r mount=/'
vcheck "ESP v /efi + /boot ext4 je OK, / povinny" uefi no_root $'part id=esp disk=/dev/vda size=1G type=esp\nfs on=esp mount=/efi type=vfat\npart id=b disk=/dev/vda size=1G\nfs on=b mount=/boot type=ext4'
vcheck "duplicitni /home" uefi dup_mount "$BASE_ESP"$'\npart id=r disk=/dev/vda size=20G\nfs on=r mount=/\npart id=h disk=/dev/vda size=5G\nfs on=h mount=/home\npart id=h2 disk=/dev/vda size=5G\nfs on=h2 mount=/home'
vcheck "/ nelze ponechat" uefi root_keep "$BASE_ESP"$'\nuse id=r dev=/dev/vda5\nfs on=r mount=/ format=0'
vcheck "/usr zvlast" uefi forbidden_mount "$BASE_ESP"$'\npart id=r disk=/dev/vda size=20G\nfs on=r mount=/\npart id=u disk=/dev/vda size=5G\nfs on=u mount=/usr'
vcheck "spatny pripojny bod" uefi bad_mount "$BASE_ESP"$'\npart id=r disk=/dev/vda size=20G\nfs on=r mount=/\npart id=u disk=/dev/vda size=5G\nfs on=u mount=/data/../etc'
vcheck "/ na vfat" uefi bad_fstype "$BASE_ESP"$'\npart id=r disk=/dev/vda size=20G\nfs on=r mount=/ type=vfat'
vcheck "dvakrat rest na disku" uefi rest_twice "$BASE_ESP"$'\npart id=r disk=/dev/vda size=rest\nfs on=r mount=/\npart id=h disk=/dev/vda size=rest\nfs on=h mount=/home'
vcheck "jeden oddil pro dve veci" uefi used_twice "$BASE_ESP"$'\npart id=r disk=/dev/vda size=rest\nfs on=r mount=/\nswap on=r'
vcheck "odkaz na neexistujici" uefi ref_missing "$BASE_ESP"$'\nfs on=nic mount=/'
vcheck "neznamy klic" uefi syntax "$BASE_ESP"$'\npart id=r disk=/dev/vda size=rest color=red\nfs on=r mount=/'
vcheck "neznamy druh" uefi syntax "$BASE_ESP"$'\nraid id=r'
vcheck "spatne id" uefi bad_id "$BASE_ESP"$'\npart id=R-1 disk=/dev/vda size=rest'
vcheck "spatna velikost" uefi bad_size "$BASE_ESP"$'\npart id=r disk=/dev/vda size=12parsecs\nfs on=r mount=/'
vcheck "maly /" uefi root_small "$BASE_ESP"$'\npart id=r disk=/dev/vda size=4G\nfs on=r mount=/'
vcheck "BIOS: sifrovany / bez /boot" bios boot_encrypted $'part id=b disk=/dev/vda size=1M type=bios\npart id=r disk=/dev/vda size=rest\nluks id=c on=r name=cr\nfs on=c mount=/'
vcheck "BIOS: chybi BIOS boot" bios bios_grub_missing $'part id=r disk=/dev/vda size=rest\nfs on=r mount=/'
vcheck "sifrovany / a nesifrovany swap" uefi swap_plain "$BASE_ESP"$'\npart id=r disk=/dev/vda size=20G\nluks id=c on=r name=cr\nfs on=c mount=/\npart id=s disk=/dev/vda size=2G\nswap on=s'
vcheck "sifrovany / a nesifrovany /home" uefi enc_mismatch "$BASE_ESP"$'\npart id=r disk=/dev/vda size=20G\nluks id=c on=r name=cr\nfs on=c mount=/\npart id=h disk=/dev/vda size=rest\nfs on=h mount=/home'
LUKS_PASS= vcheck "chybi heslo" uefi luks_no_pass "$BASE_ESP"$'\npart id=r disk=/dev/vda size=20G\nluks id=c on=r name=cr\nfs on=c mount=/'
vcheck "dve LUKS stejne jmeno" uefi dup_name "$BASE_ESP"$'\npart id=r disk=/dev/vda size=20G\nluks id=c on=r name=cr\nfs on=c mount=/\npart id=h disk=/dev/vda size=2G\nluks id=c2 on=h name=cr\nfs on=c2 mount=/home'
vcheck "existujici LV v nove VG" uefi keep_on_new "$BASE_ESP"$'\npart id=p disk=/dev/vda size=rest\nvg id=v name=a pvs=p\nlv id=l vg=v name=r keep=1\nfs on=l mount=/'
vcheck "pouziti oddilu na mazanem disku" uefi use_on_wiped $'disk dev=/dev/vda table=new\nuse id=x dev=/dev/vda1\n'"$BASE_ESP"
vcheck "nepouzity novy oddil (varovani)" uefi unused "$BASE_ESP"$'\npart id=r disk=/dev/vda size=20G\nfs on=r mount=/\npart id=z disk=/dev/vda size=2G'

# Bez chyb: platna rozlozeni nemaji zadnou chybu
vclean() {
    local d=$1 bm=$2 lay=$3 got
    got=$(set -Eeuo pipefail; trap 'echo "ERR radek $LINENO: $BASH_COMMAND"' ERR; . "$FILES/layout.sh"; T() { local f=$1; shift; printf -- "$f" "$@"; }
          BOOTMODE=$bm BOOTLOADER=${BL:-auto} LUKS_PASS=x; layout_parse "$lay"; layout_validate; printf '%s\n' "${LY_ERR[@]}")
    if [[ -z $got ]]; then ok "G: bez chyb: $d"; else bad "G: bez chyb: $d" "$got"; fi
}
vclean "predvolba A" uefi "$LA"
vclean "predvolba B (BIOS)" bios "$LB"
vclean "LUKS na LVM" uefi "$LC"
BL=none vclean "BIOS bez zavadece nepotrebuje BIOS boot" bios $'part id=r disk=/dev/vda size=rest\nfs on=r mount=/'

# Zarizeni: neexistujici disk, pripojeny oddil
scenario H uefi "vda:64G" "disk dev=/dev/vdz table=new
$BASE_ESP
part id=r disk=/dev/vda size=rest
fs on=r mount=/"
expect "H: neexistujici disk odhalen pred zmenami" bash -c "[[ \$(cat '$OUT/H/rc') == 3 ]] && grep -q '^not_block|/dev/vdz' '$OUT/H/errors'"
PREP_I='printf "1 2048 999999 8300 x\n" >"$MOCK/disks/vda.tbl"; mkdir -p "$MOCK/busy"; : >"$MOCK/busy/vda"'
scenario I uefi "vda:64G" "disk dev=/dev/vda table=new
$BASE_ESP
part id=r disk=/dev/vda size=rest
fs on=r mount=/" "$PREP_I"
expect "I: pripojeny disk se nesmaze" bash -c "[[ \$(cat '$OUT/I/rc') == 3 ]] && grep -q '^busy|/dev/vda' '$OUT/I/errors'"
scenario J uefi "vda:8G" "$BASE_ESP
part id=r disk=/dev/vda size=20G
fs on=r mount=/"
expect "J: malo mista -> odhaleno pred zmenami (no_space)" bash -c "[[ \$(cat '$OUT/J/rc') == 3 ]] && grep -q '^no_space|/dev/vda' '$OUT/J/errors'"
expect "J: zadny zapis na disk" bash -c "! grep -qE '^(sgdisk -[no]|wipefs|cryptsetup luksFormat|mkfs)' '$OUT/J/cmds'"

# ---------------------------------------------------------------------------------
echo "## N: kapacita (regrese z VM: predvolba s /var a /tmp na 24 GB disku)"
# Puvodni chybne rozlozeni: 30 GiB pevnych LV ve skupine o ~23 GiB
LBAD='disk dev=/dev/vda table=new
part id=p1 disk=/dev/vda size=1G type=esp
part id=p2 disk=/dev/vda size=rest
luks id=c3 on=p2 name=cryptlvm
vg id=vg4 name=luxos pvs=c3
lv id=lv5 vg=vg4 name=root size=16G
lv id=lv6 vg=vg4 name=var size=8G
lv id=lv7 vg=vg4 name=tmp size=4G
lv id=lv8 vg=vg4 name=swap size=2G
lv id=lv9 vg=vg4 name=home size=rest
fs on=p1 mount=/boot type=vfat
fs on=lv5 mount=/
fs on=lv6 mount=/var
fs on=lv7 mount=/tmp type=ext4
fs on=lv9 mount=/home
swap on=lv8'
scenario N1 uefi "vda:24G" "$LBAD"
expect "N1: VG plna odhalena pred zmenami (vg_full luxos)" bash -c "[[ \$(cat '$OUT/N1/rc') == 3 ]] && grep -qx 'vg_full|luxos' '$OUT/N1/errors'"
expect "N1: zadny zapis na disk" bash -c "! grep -qE '^(sgdisk -[no]|wipefs|cryptsetup luksFormat|pvcreate|lvcreate|mkfs)' '$OUT/N1/cmds'"
for gb in 16 20 24 32; do
    for pr in lvm lvm_var; do
        LN=$(py_layout $pr /dev/vda $gb uefi 8 2>"$OUT/N.pyerr")
        if [[ -s $OUT/N.pyerr ]]; then bad "N: $pr ${gb}G: GUI model ma chyby" "$(cat "$OUT/N.pyerr")"; continue; fi
        scenario "N-$pr-$gb" uefi "vda:${gb}G" "$LN"
        expect "N: predvolba $pr na ${gb} GiB projde kontrolou kapacity i provedenim" rc_is "N-$pr-$gb" 0
    done
done
# Presne hranice jako LVM: 24 GiB -> 5883 extentu; LV o 1 extent vic nez zbytek musi selhat, presne zbytek projde
LEX='disk dev=/dev/vda table=new
part id=p1 disk=/dev/vda size=1G type=esp
part id=p2 disk=/dev/vda size=rest
luks id=c on=p2 name=cryptlvm
vg id=v name=luxos pvs=c
lv id=r vg=v name=root size=SIZE
fs on=p1 mount=/boot type=vfat
fs on=r mount=/'
scenario N2 uefi "vda:24G" "${LEX/SIZE/23532M}"
expect "N2: LV presne velikosti VG (5883 extentu) projde" rc_is N2 0
scenario N3 uefi "vda:24G" "${LEX/SIZE/23536M}"
expect "N3: o 1 extent vic -> vg_full" bash -c "[[ \$(cat '$OUT/N3/rc') == 3 ]] && grep -qx 'vg_full|luxos' '$OUT/N3/errors'"
scenario N4 uefi "vda:20G" $'disk dev=/dev/vda table=new\npart id=e disk=/dev/vda size=1G type=esp\npart id=a disk=/dev/vda size=10G\npart id=b disk=/dev/vda size=9G\nfs on=e mount=/boot type=vfat\nfs on=a mount=/\nfs on=b mount=/home'
expect "N4: oddily soucet > disk -> no_space" bash -c "[[ \$(cat '$OUT/N4/rc') == 3 ]] && grep -qx 'no_space|/dev/vda' '$OUT/N4/errors'"
scenario N5 uefi "vda:20G" $'disk dev=/dev/vda table=new\npart id=e disk=/dev/vda size=1G type=esp\npart id=a disk=/dev/vda size=19455M\npart id=b disk=/dev/vda size=rest\nfs on=e mount=/boot type=vfat\nfs on=a mount=/\nfs on=b mount=/home'
expect "N5: na rest nezbyl 1 MiB -> no_space" bash -c "[[ \$(cat '$OUT/N5/rc') == 3 ]] && grep -qx 'no_space|/dev/vda' '$OUT/N5/errors'"
PREP_N6='echo /dev/x >"$MOCK/vg/oldvg"; mkdir -p "$MOCK/vgfree" "$MOCK/lvsize"; echo $((5 * 1024 ** 3)) >"$MOCK/vgfree/oldvg"'
LN6=$'disk dev=/dev/vda table=new\npart id=e disk=/dev/vda size=1G type=esp\nfs on=e mount=/boot type=vfat\nvg id=o name=oldvg keep=1\nlv id=r vg=o name=root size=8G\nfs on=r mount=/'
scenario N6 uefi "vda:20G" "$LN6" "$PREP_N6"
expect "N6: existujici VG s 5 GiB volna, novy LV 8 GiB -> vg_full" bash -c "[[ \$(cat '$OUT/N6/rc') == 3 ]] && grep -qx 'vg_full|oldvg' '$OUT/N6/errors'"
scenario N7 uefi "vda:20G" "$LN6"$'\ndelete dev=/dev/oldvg/old' "$PREP_N6"'; : >"$MOCK/lv/oldvg-old"; echo $((4 * 1024 ** 3)) >"$MOCK/lvsize/oldvg-old"'
expect "N7: smazany LV uvolni misto (5 + 4 GiB) -> projde" rc_is N7 0


# ---------------------------------------------------------------------------------
echo "## K: GUI model (Python) a backend (bash) hlasi stejne chyby"
python3 -I - "$FILES" >"$OUT/K.cases" <<'PY'
import sys, json
sys.path.insert(0, sys.argv[1])
import luxos_layout as m
GB = m.GiB
def disk(path, gib, parts=()):
    return {"path": path, "name": path[5:], "size": gib * GB, "model": "", "pttype": "gpt", "parts": list(parts)}
cases = []
def case(name, L):
    py = sorted({c for lvl, c, d in L.validate() if lvl == "error"})
    cases.append({"name": name, "bootmode": L.bootmode, "text": L.to_text(), "py": py,
                  "pass": L.passphrase, "disks": [f"{d['name']}:{d['size'] // GB}G" for d in L.scan["disks"]]})
scan = {"bootmode": "uefi", "vgs": [], "disks": [disk("/dev/vda", 64), disk("/dev/vdb", 32)]}
L = m.Layout(scan); L.preset("/dev/vda", "lvm"); L.passphrase = "p"; case("preset", L)
L = m.Layout(scan); L.preset("/dev/vda", "lvm"); L.passphrase = ""; case("no-pass", L)
L = m.Layout(scan); L.preset("/dev/vda", "lvm_var"); L.passphrase = "p"
root = L.by_mount("/"); root.use = None; case("no-root", L)
L = m.Layout(scan); L.preset("/dev/vda", "lvm"); L.passphrase = "p"
L.by_mount("/home").use["mount"] = "/"; case("dup-root", L)
L = m.Layout(scan); L.preset("/dev/vda", "lvm"); L.passphrase = "p"
L.esp().use = None; case("no-esp", L)
L = m.Layout(scan); L.wipe_disk("/dev/vda"); p = L.add_part("/dev/vda", 30 * GB)
p.use = {"type": "fs", "mount": "/", "fstype": "ext4", "format": True}
e = L.add_part("/dev/vda", 1 * GB); e.use = {"type": "fs", "mount": "/boot", "fstype": "vfat", "format": True}
case("esp-not-type", L)
L = m.Layout(dict(scan, bootmode="bios")); L.preset("/dev/vda", "lvm"); L.passphrase = "p"
L.by_mount("/boot").use = None; case("bios-root-encrypted", L)
L = m.Layout(scan); L.wipe_disk("/dev/vda"); e = L.add_part("/dev/vda", 1 * GB, ptype="esp")
e.use = {"type": "fs", "mount": "/boot", "fstype": "vfat", "format": True}
p = L.add_part("/dev/vda", 4 * GB); p.use = {"type": "fs", "mount": "/", "fstype": "btrfs", "format": True}
q = L.add_part("/dev/vda", 4 * GB); q.use = {"type": "fs", "mount": "/usr", "fstype": "btrfs", "format": True}
case("small-root-usr", L)
L = m.Layout(scan); L.wipe_disk("/dev/vda"); L.wipe_disk("/dev/vdb")
e = L.add_part("/dev/vda", 1 * GB, ptype="esp"); e.use = {"type": "fs", "mount": "/efi", "fstype": "vfat", "format": True}
a = L.add_part("/dev/vda", rest=True); b = L.add_part("/dev/vdb", rest=True)
vg = L.add_vg("luxos", [a.id, b.id])
r = L.add_lv(vg.id, "root", 30 * GB); h = L.add_lv(vg.id, "home", rest=True)
cr = L.encrypt(r.id); cr.use = {"type": "fs", "mount": "/", "fstype": "btrfs", "format": True}
ch = L.encrypt(h.id); ch.use = {"type": "fs", "mount": "/home", "fstype": "ext4", "format": True}
L.passphrase = "p"; case("luks-on-lvm", L)
# Kapacita (regrese z VM): predvolba na 24 GiB je platna, puvodni 30 GiB LV ve 23 GiB VG ne
small = {"bootmode": "uefi", "vgs": [], "disks": [disk("/dev/vda", 24)]}
L = m.Layout(small); L.preset("/dev/vda", "lvm_var", ram=8 * GB); L.passphrase = "p"; case("preset-24G-var", L)
L = m.Layout(small); L.preset("/dev/vda", "lvm", ram=8 * GB); L.passphrase = "p"; case("preset-24G", L)
L = m.Layout(small); L.preset("/dev/vda", "lvm_var"); L.passphrase = "p"
for lv, sz in zip(sorted(L.of("lv"), key=lambda n: n.id), (16, 8, 4, 2)):
    lv.size = sz * GB
case("old-bad-preset-24G (vg_full)", L)
L = m.Layout(small); L.preset("/dev/vda", "lvm"); L.passphrase = "p"
root = L.by_mount("/"); root.size = L.size_of(L.of("vg")[0]); case("rest-lv-empty (vg_full)", L)
L = m.Layout(small); L.wipe_disk("/dev/vda"); e = L.add_part("/dev/vda", GB, ptype="esp")
e.use = {"type": "fs", "mount": "/boot", "fstype": "vfat", "format": True}
a = L.add_part("/dev/vda", 20 * GB); a.use = {"type": "fs", "mount": "/", "fstype": "btrfs", "format": True}
b = L.add_part("/dev/vda", 4 * GB); b.use = {"type": "fs", "mount": "/home", "fstype": "btrfs", "format": True}
case("parts-over-disk (no_space)", L)
L = m.Layout(small); L.wipe_disk("/dev/vda"); e = L.add_part("/dev/vda", GB, ptype="esp")
e.use = {"type": "fs", "mount": "/boot", "fstype": "vfat", "format": True}
a = L.add_part("/dev/vda", 23 * GB - 2 * m.MiB); a.use = {"type": "fs", "mount": "/", "fstype": "btrfs", "format": True}
b = L.add_part("/dev/vda", rest=True); b.use = {"type": "fs", "mount": "/home", "fstype": "btrfs", "format": True}
case("rest-part-tiny", L)
try:
    m.Layout({"bootmode": "uefi", "vgs": [], "disks": [disk("/dev/vda", 13)]}).preset("/dev/vda", "lvm_var")
    print(json.dumps({"name": "TOO-SMALL-NOT-RAISED"}))
except m.PresetTooSmall:
    pass
for c in cases:
    print(json.dumps(c))
PY
while IFS= read -r line; do
    name=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["name"])' "$line")
    [[ $name == TOO-SMALL-NOT-RAISED ]] && { bad "K: predvolba na 13 GiB disku nevyvolala PresetTooSmall"; continue; }
    bm=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["bootmode"])' "$line")
    text=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["text"])' "$line")
    pass=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["pass"])' "$line")
    py=$(python3 -c 'import json,sys; print(" ".join(json.loads(sys.argv[1])["py"]))' "$line")
    disks=$(python3 -c 'import json,sys; print(" ".join(d for d in json.loads(sys.argv[1])["disks"]))' "$line")
    sh=$(set -Eeuo pipefail; trap 'echo "ERR radek $LINENO: $BASH_COMMAND"' ERR; . "$FILES/layout.sh"; . "$HERE/mock-env.sh"
         mock_init $disks; TARGET=$MOCK/target
         BOOTMODE=$bm BOOTLOADER=auto LUKS_PASS=$pass; layout_parse "$text"; layout_validate
         ((${#LY_ERR[@]})) || layout_check_devices
         rm -rf "$MOCK"
         printf '%s\n' "${LY_ERR[@]}" | cut -d'|' -f1 | sort -u | tr '\n' ' ')
    sh=${sh% }
    # kody, ktere kontroluje jen jedna strana (velikosti po alokaci, zarizeni)
    # kody, ktere kontroluje jen GUI (zamceny LUKS, pripojene v live systemu)
    py=$(tr ' ' '\n' <<<"$py" | grep -vxE 'busy|locked|esp_keep_fs|esp_keep_small' | tr '\n' ' '); py=${py% }
    py=${py# }
    if [[ $py == "$sh" ]]; then ok "K: $name: [${sh:-zadna chyba}]"; else bad "K: $name" "python: [$py]  bash: [$sh]"; fi
done <"$OUT/K.cases"

# ---------------------------------------------------------------------------------
echo "## L: setup-chroot HOOKS a ESP podle prostredi"
hooks_for() {  # hooks_for "ENCRYPT=0 ENCRYPT_HOOK=1 LVM_HOOK=1" -> radek HOOKS
    local tmp; tmp=$(mktemp -d)
    sed -n '/^modules=""/,/^M$/p' "$FILES/setup-chroot.sh" |
        sed "s|/etc/mkinitcpio.conf.d/luxos.conf|$tmp/luxos.conf|" >"$tmp/s.sh"
    (eval "$1"; NVIDIA_EARLY=0; pacman() { return 1; }; . "$tmp/s.sh")
    grep '^HOOKS' "$tmp/luxos.conf" | tr -s ' '; rm -rf "$tmp"
}
expect "L: puvodni sifrovani (erase)" test "$(hooks_for 'ENCRYPT=1')" == "HOOKS=(base systemd plymouth autodetect microcode modconf kms keyboard sd-vconsole block sd-encrypt filesystems fsck)"
expect "L: bez sifrovani (erase)" test "$(hooks_for 'ENCRYPT=0')" == "HOOKS=(base systemd plymouth autodetect microcode modconf kms keyboard sd-vconsole block filesystems fsck)"
expect "L: layout LUKS+LVM" test "$(hooks_for 'ENCRYPT=0 ENCRYPT_HOOK=1 LVM_HOOK=1')" == "HOOKS=(base systemd plymouth autodetect microcode modconf kms keyboard sd-vconsole block sd-encrypt lvm2 filesystems fsck)"
expect "L: layout jen LVM" test "$(hooks_for 'ENCRYPT=0 ENCRYPT_HOOK=0 LVM_HOOK=1')" == "HOOKS=(base systemd plymouth autodetect microcode modconf kms keyboard sd-vconsole block lvm2 filesystems fsck)"

# ---------------------------------------------------------------------------------
echo "## M: luxos-install --check-layout (bez roota, kopie s cestami do repozitare)"
I18N=$(cd "$HERE/../../luxos-i18n/files" && pwd)
sed "s|/usr/share/luxos/i18n|$I18N|g" "$I18N/i18n.sh" >"$OUT/i18n.sh"
sed -e "s|^SHARE=.*|SHARE=$FILES|" -e "s|/usr/lib/luxos/i18n.sh|$OUT/i18n.sh|g" "$FILES/luxos-install" >"$OUT/luxos-install"
printf '%s' "$LA" >"$OUT/A.layout"
if out=$(BOOTMODE=uefi LUKS_PASS=x bash "$OUT/luxos-install" --check-layout "$OUT/A.layout" 2>&1); then
    if grep -q "ERASE ERASE the whole disk /dev/vda" <<<"$out" && grep -q '^/home' <<<"$out"; then ok "M: platne rozlozeni (souhrn a seznam mazani)"
    else bad "M: platne rozlozeni" "$out"; fi
else
    bad "M: platne rozlozeni (navratovy kod)" "$out"
fi
if out=$(BOOTMODE=uefi bash "$OUT/luxos-install" --check-layout - <<<"$BASE_ESP" 2>&1); then
    bad "M: chybejici / musi selhat" "$out"
else
    grep -q '^ERROR no_root' <<<"$out" && ok "M: chybejici / -> ERROR no_root" || bad "M: chybejici /" "$out"
fi
out=$(BOOTMODE=uefi LANG=cs_CZ.UTF-8 bash "$OUT/luxos-install" --check-layout - <<<"$BASE_ESP" 2>&1 || true)
expect "M: hlaseni v cestine (preklad z i18n)" grep -q 'kořenový' <<<"$out"

# ---------------------------------------------------------------------------------
echo
echo "Vysledek: $NPASS ok, $NFAIL FAIL"
[[ -n ${KEEP-} ]] || { ((NFAIL)) || rm -rf "$OUT"; }
exit "$NFAIL"
