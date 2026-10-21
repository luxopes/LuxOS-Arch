#!/bin/bash
# LuxOS installer - skutecny test rucniho rozdeleni (layout.sh) na loop discich. JEN V JEDNORAZOVEM VIRTUALU!
#
# Co dela: vytvori 2 ridke soubory (disky) v $WORK, pripoji je jako loop zarizeni a pro kazdy scenar
# spusti skutecne prikazy instalatoru (sgdisk, cryptsetup luksFormat --type luks2, pvcreate/vgcreate/
# lvcreate, mkfs.*, mount) pres layout.sh. Pak overi vysledek (lsblk, cryptsetup, findmnt, blkid) a
# vygenerovane soubory (crypttab, crypttab.initramfs, klice, swap do fstab, cmdline, HOOKS). Nic se
# neinstaluje (bez pacstrap a site); jine disky nez vlastni loop zarizeni se nemeni.
#
# Scenare: A predvolba "Sifrovane LVM (/, /home, swap)", B predvolba "… se samostatnym /var a /tmp",
#          C vlastni LUKS na LVM pres oba disky (kazdy LV vlastni LUKS, ruzna hesla), D B v rezimu BIOS,
#          E pripojeny disk se nesmaze, F kapacita (plna VG odmitnuta pred zapisem, presna hranice extentu)
#
# Pouziti (live ISO LuxOS ve virtualu, jako root; potrebuje lvm2, cryptsetup, gptfdisk, btrfs-progs,
# xfsprogs, dosfstools, e2fsprogs, python3 - vse je na ISO):
#   1) zkopirovat adresar packages/luxos-installer (a packages/luxos-i18n/files) do VM, napr. scp -r
#   2) sudo LUXOS_VM_TEST=yes packages/luxos-installer/tests/vm-layout-test.sh
#      (WORK=/var/tmp/luxos-vmtest, DISK1_GB=24, DISK2_GB=16, KEEP=1 = nechat disky pro prohlidku)
#   Vystup: radky ok/FAIL, navratovy kod = pocet chyb, protokol prikazu v $WORK/<scenar>/log.
#
# Bootovani nainstalovaneho systemu tento test neoveruje - viz "Rucni overeni" na konci souboru.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
FILES=$(cd "$HERE/../files" && pwd)
WORK=${WORK:-/var/tmp/luxos-vmtest}
DISK1_GB=${DISK1_GB:-24}
DISK2_GB=${DISK2_GB:-16}
NPASS=0 NFAIL=0

((EUID == 0)) || { echo "Spustte jako root (jen v jednorazovem virtualu)." >&2; exit 2; }
[[ ${LUXOS_VM_TEST-} == yes ]] || { echo "Nastavte LUXOS_VM_TEST=yes (test vytvari a maze loop disky; jen ve virtualu)." >&2; exit 2; }
for c in sgdisk cryptsetup pvcreate vgcreate lvcreate mkfs.btrfs mkfs.ext4 mkfs.xfs mkfs.fat losetup python3 findmnt; do
    command -v "$c" >/dev/null || { echo "Chybi $c" >&2; exit 2; }
done

ok()  { NPASS=$((NPASS + 1)); printf 'ok    %s\n' "$1"; }
bad() { NFAIL=$((NFAIL + 1)); printf 'FAIL  %s\n' "$1"; [[ -n ${2-} ]] && printf '      %s\n' "$2"; return 0; }
expect() { local d=$1; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d" "$*"; fi; }

LOOP1="" LOOP2=""
cleanup_disks() {
    umount -R "$WORK/mnt" 2>/dev/null || true
    swapoff -a 2>/dev/null || true
    local d n
    for d in $LOOP1 $LOOP2; do
        # vse nad loop diskem zavrit (LV, LUKS) v opacnem poradi
        for n in $(lsblk -nrpo NAME,TYPE "$d" 2>/dev/null | tail -n +2 | tac | awk '$2 == "crypt" || $2 == "lvm" {print $1 ":" $2}'); do
            case ${n#*:} in
                crypt) cryptsetup close "${n%:*}" 2>/dev/null || true ;;
                lvm) vgchange -an "$(lvs --noheadings -o vg_name "${n%:*}" 2>/dev/null | tr -d ' ')" >/dev/null 2>&1 || true ;;
            esac
        done
    done
    for d in $LOOP1 $LOOP2; do
        local vg
        for vg in $(pvs --noheadings -o vg_name ${d}p* 2>/dev/null | tr -d ' ' | sort -u); do vgchange -an "$vg" >/dev/null 2>&1 || true; done
    done
}

new_disks() {
    cleanup_disks
    [[ -n $LOOP1 ]] && losetup -d "$LOOP1" 2>/dev/null
    [[ -n $LOOP2 ]] && losetup -d "$LOOP2" 2>/dev/null
    mkdir -p "$WORK/mnt"
    rm -f "$WORK/disk1.img" "$WORK/disk2.img"
    truncate -s "${DISK1_GB}G" "$WORK/disk1.img"
    truncate -s "${DISK2_GB}G" "$WORK/disk2.img"
    LOOP1=$(losetup -fP --show "$WORK/disk1.img")
    LOOP2=$(losetup -fP --show "$WORK/disk2.img")
}

py_preset() {  # py_preset PRESET DISK GIB BOOTMODE -> LAYOUT z GUI modelu
    python3 -I - "$FILES" "$@" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import luxos_layout as m
preset, disk, gib, bm = sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
scan = {"bootmode": bm, "vgs": [], "disks": [{"path": disk, "name": disk[5:], "size": gib * m.GiB, "parts": [],
                                              "model": "loop", "pttype": ""}]}
L = m.Layout(scan)
L.preset(disk, preset, ram=2 * m.GiB)   # PresetTooSmall -> traceback, scenar selze
L.passphrase = "x"
errs = [c for lvl, c, d in L.validate() if lvl == "error"]
if errs:
    sys.exit("GUI model hlasi chyby: " + " ".join(errs))
sys.stdout.write(L.to_text())
PY
}

# Jeden scenar: skutecne provedeni layout.sh a zapis vysledku do $WORK/<jmeno>
run_scenario() {  # run_scenario JMENO BOOTMODE LAYOUT
    local name=$1 bm=$2 layout=$3 dir=$WORK/$1
    rm -rf "$dir"; mkdir -p "$dir/target-etc"
    printf '%s\n' "$layout" >"$dir/layout"
    (
        set -Eeuo pipefail
        LOG=$dir/log
        TARGET=$WORK/mnt
        T() { local f=$1; shift; printf -- "$f" "$@"; }
        run() { printf '+ %s\n' "$*" >>"$LOG"; "$@" >>"$LOG" 2>&1; }
        step() { printf '@@STEP %s\n' "$*" >>"$LOG"; }
        info() { printf '  %s\n' "$*" >>"$LOG"; }
        progress() { :; }
        fail() { printf 'FAIL %s\n' "$*" | tee -a "$LOG" >&2; exit 1; }
        trap 'echo "chyba na radku $LINENO" >>"$LOG"' ERR
        . "$FILES/layout.sh"
        BOOTMODE=$bm BOOTLOADER=auto
        layout_parse "$layout"
        layout_validate
        ((${#LY_ERR[@]})) || layout_check_devices
        printf '%s\n' "${LY_ERR[@]}" >"$dir/errors"
        ((${#LY_ERR[@]} == 0)) || exit 3
        layout_apply
        # konfigurace jako configure_system (do $TARGET/etc)
        mkdir -p "$TARGET/etc"
        layout_write_crypt
        layout_fstab_swap >"$dir/fstab_swap"
        if command -v genfstab >/dev/null; then genfstab -U "$TARGET" >"$dir/fstab"; fi
        layout_cmdline >"$dir/cmdline"
        layout_hooks >"$dir/hooks"
        cp -a "$TARGET/etc/crypttab" "$dir/crypttab" 2>/dev/null || : >"$dir/crypttab"
        cp -a "$TARGET/etc/crypttab.initramfs" "$dir/crypttab.initramfs" 2>/dev/null || : >"$dir/crypttab.initramfs"
        if [[ -d $TARGET/etc/cryptsetup-keys.d ]]; then cp -a "$TARGET/etc/cryptsetup-keys.d" "$dir/keys"; fi
        findmnt -R -n -o TARGET,SOURCE,FSTYPE,OPTIONS "$TARGET" >"$dir/findmnt"
        lsblk -o NAME,TYPE,FSTYPE,SIZE,MOUNTPOINTS $LOOP1 $LOOP2 >"$dir/lsblk"
    )
    echo $? >"$dir/rc"
}

by_uuid() { blkid -U "${1#UUID=}" 2>/dev/null || echo "/dev/disk/by-uuid/${1#UUID=}"; }   # UUID[=]x -> zarizeni

dev_of_mount() { findmnt -n -o SOURCE --target "$WORK/mnt$1" | sed 's/\[.*//'; }

verify_common() {  # verify_common JMENO "seznam pripojnych bodu" PASS
    local name=$1 mounts=$2 pass=$3 dir=$WORK/$1 mp src
    expect "$name: provedeno bez chyby" test "$(cat "$dir/rc")" = 0
    [[ $(cat "$dir/rc") == 0 ]] || { sed 's/^/      /' "$dir/errors"; tail -20 "$dir/log" | sed 's/^/      /'; return; }
    for mp in $mounts; do
        expect "$name: $mp pripojeno" findmnt -n "$WORK/mnt${mp%/}"
    done
    # cmdline: root=UUID odpovida skutecnemu / ; rd.luks.name kazdeho LUKS pod / sedi s jeho UUID
    src=$(dev_of_mount /)
    local ruuid; ruuid=$(blkid -s UUID -o value "$src")
    expect "$name: cmdline root=UUID odpovida /" grep -q "root=UUID=$ruuid" "$dir/cmdline"
    local line uuid mname
    while read -r line; do
        [[ $line == \#* || -z $line ]] && continue
        read -r mname uuid _ <<<"$line"
        uuid=${uuid#UUID=}
        expect "$name: initramfs $mname: UUID je LUKS2" bash -c "cryptsetup luksDump '$(by_uuid "$uuid")' | grep -q '^Version:[[:space:]]*2'"
        expect "$name: cmdline rd.luks.name pro $mname" grep -q "rd.luks.name=$uuid=$mname" "$dir/cmdline"
        expect "$name: $mname otevreno pod spravnym jmenem" test -e "/dev/mapper/$mname"
    done <"$dir/crypttab.initramfs"
    # crypttab: klic otevre svazek, UUID sedi
    while read -r line; do
        [[ $line == \#* || -z $line ]] && continue
        local key opts
        read -r mname uuid key opts <<<"$line"
        if [[ $key == /etc/cryptsetup-keys.d/* ]]; then
            local kf=$dir/keys/${key##*/}
            expect "$name: klic $mname ma prava 0400" test "$(stat -c %a "$kf")" = 400
            expect "$name: klic otevre $mname" cryptsetup open --test-passphrase --key-file "$kf" "$(by_uuid "$uuid")"
            expect "$name: heslo dal otevre $mname" bash -c "printf '%s' \"\$1\" | cryptsetup open --test-passphrase --key-file - '$(by_uuid "$uuid")'" _ "${PASS_OF[$mname]:-$pass}"
        elif [[ $opts == *swap* ]]; then
            expect "$name: $mname nahodny swap (PARTUUID/LV existuje)" blkid -t "${uuid}" -o device
        fi
    done <"$dir/crypttab"
    # swap ve fstab: UUID existuje a je swap
    while read -r src _; do
        [[ $src == UUID=* ]] || continue
        expect "$name: swap $src je swap" bash -c "[[ \$(blkid -s TYPE -o value '$(by_uuid "$src")') == swap ]]"
    done <"$dir/fstab_swap"
    # heslo otevre LUKS pod /
    while read -r line; do
        [[ $line == \#* || -z $line ]] && continue
        read -r mname uuid _ <<<"$line"
        expect "$name: heslo otevre $mname" bash -c "printf '%s' \"\$1\" | cryptsetup open --test-passphrase --key-file - '$(by_uuid "$uuid")'" _ "$pass"
    done <"$dir/crypttab.initramfs"
}

declare -A PASS_OF=()
mkdir -p "$WORK"
echo "# pracovni adresar: $WORK"

# --- A: predvolba Sifrovane LVM (UEFI) na disku 1 ---------------------------------------
new_disks
LA=$(py_preset lvm "$LOOP1" "$DISK1_GB" uefi)
LUKS_PASS=heslo-A run_scenario A uefi "$LA"
verify_common A "/ /boot /home" heslo-A
expect "A: ESP je FAT32" bash -c "[[ \$(blkid -s TYPE -o value ${LOOP1}p1) == vfat ]]"
expect "A: ESP typ EF00" bash -c "sgdisk -i 1 $LOOP1 | grep -qi 'C12A7328-F81F-11D2-BA4B-00A0C93EC93B'"
expect "A: LUKS oddil typ 8309" bash -c "sgdisk -i 2 $LOOP1 | grep -qi 'CA7D7CCB-63ED-4C53-861C-1742536059CC'"
expect "A: / btrfs subvol=@" bash -c "findmnt -n -o OPTIONS '$WORK/mnt' | grep -q 'subvol=/@'"
expect "A: HOOKS sd-encrypt + lvm2" grep -qx 'ENCRYPT_HOOK=1 LVM_HOOK=1' "$WORK/A/hooks"
expect "A: VG luxos na cryptlvm" bash -c "pvs --noheadings -o pv_name,vg_name | grep -q '/dev/mapper/cryptlvm *luxos'"
expect "A: LV root, swap, home" bash -c "lvs --noheadings -o lv_name luxos | tr -d ' ' | sort | tr '\n' ' ' | grep -qx 'home root swap '"
expect "A: /etc/crypttab bez dalsich svazku" bash -c "! grep -v '^#' '$WORK/A/crypttab' | grep -q ."

# --- B: predvolba s /var a /tmp (UEFI) ---------------------------------------------------
new_disks
LB=$(py_preset lvm_var "$LOOP1" "$DISK1_GB" uefi)
LUKS_PASS=heslo-B run_scenario B uefi "$LB"
verify_common B "/ /boot /home /var /tmp" heslo-B
expect "B: /tmp nosuid,nodev" bash -c "findmnt -n -o OPTIONS '$WORK/mnt/tmp' | grep -q nosuid"
expect "B: /tmp ext4" bash -c "[[ \$(findmnt -n -o FSTYPE '$WORK/mnt/tmp') == ext4 ]]"
expect "B: bez subvolumu @log/@cache (samostatny /var)" bash -c "! btrfs subvolume list '$WORK/mnt' | grep -q '@cache'"

# --- C: LUKS na LVM pres oba disky, ruzna hesla, klice pro /home a swap ------------------
new_disks
LC="disk dev=$LOOP1 table=new
disk dev=$LOOP2 table=new
part id=esp disk=$LOOP1 size=512M type=esp
part id=pv1 disk=$LOOP1 size=rest
part id=pv2 disk=$LOOP2 size=rest
vg   id=vg name=vmtest-vg pvs=pv1,pv2
lv   id=lroot vg=vg name=root size=12G
lv   id=lswap vg=vg name=swap size=1G
lv   id=lhome vg=vg name=home size=rest
luks id=croot on=lroot name=cryptroot
luks id=chome on=lhome name=crypthome
luks id=cswap on=lswap name=cryptswap
fs   on=esp mount=/efi type=vfat
fs   on=croot mount=/ type=ext4
fs   on=chome mount=/home type=xfs
swap on=cswap"
PASS_OF[crypthome]=heslo-home
LUKS_PASS=heslo-C LUKS_PASS_CHOME=heslo-home run_scenario C uefi "$LC"
verify_common C "/ /efi /home" heslo-C
expect "C: VG pres dva disky" bash -c "[[ \$(vgs --noheadings -o pv_count vmtest-vg | tr -d ' ') == 2 ]]"
expect "C: LUKS na LV (root)" bash -c "cryptsetup isLuks /dev/vmtest-vg/root"
expect "C: crypthome a cryptswap v /etc/crypttab s klicem" bash -c "grep -q '^crypthome .*/etc/cryptsetup-keys.d/crypthome.key' '$WORK/C/crypttab' && grep -q '^cryptswap .*/etc/cryptsetup-keys.d/cryptswap.key' '$WORK/C/crypttab'"
expect "C: initramfs jen cryptroot" bash -c "[[ \$(grep -vc '^#' '$WORK/C/crypttab.initramfs') == 1 ]]"
expect "C: adresar klicu 0700" test "$(stat -c %a "$WORK/C/keys")" = 700
expect "C: /home xfs" bash -c "[[ \$(findmnt -n -o FSTYPE '$WORK/mnt/home') == xfs ]]"

# --- D: BIOS (GRUB): BIOS boot + nesifrovany /boot ---------------------------------------
new_disks
LD=$(py_preset lvm_var "$LOOP1" "$DISK1_GB" bios)
LUKS_PASS=heslo-D run_scenario D bios "$LD"
verify_common D "/ /boot /home /var /tmp" heslo-D
expect "D: BIOS boot oddil EF02" bash -c "sgdisk -i 1 $LOOP1 | grep -qi '21686148-6449-6E6F-744E-656564454649'"
expect "D: /boot ext4 nesifrovany" bash -c "[[ \$(findmnt -n -o SOURCE '$WORK/mnt/boot') == ${LOOP1}p2 ]]"

# --- E: kontrola pred zmenami: pripojeny disk se nesmi smazat ------------------------------
new_disks
LUKS_PASS=x run_scenario E0 uefi "$(py_preset lvm "$LOOP1" "$DISK1_GB" uefi)"   # na disku je system
LE="disk dev=$LOOP1 table=new
part id=esp disk=$LOOP1 size=1G type=esp
part id=r disk=$LOOP1 size=rest
fs on=esp mount=/boot type=vfat
fs on=r mount=/ type=btrfs"
# disk 1 zustal pripojeny v jinem adresari -> kontrola musi selhat (busy)
mkdir -p "$WORK/busy"; mount "${LOOP1}p1" "$WORK/busy"
umount -R "$WORK/mnt" 2>/dev/null || true
run_scenario E uefi "$LE"
expect "E: pripojeny disk odmitnut pred zmenami (busy)" bash -c "[[ \$(cat '$WORK/E/rc') == 3 ]] && grep -q '^busy|' '$WORK/E/errors'"
expect "E: data na disku nezmenena (ESP porad FAT32)" bash -c "[[ \$(blkid -s TYPE -o value ${LOOP1}p1) == vfat ]]"
umount "$WORK/busy"

# --- F: kapacita (regrese): 30 GiB pevnych LV ve ~23 GiB skupine -> odmitnuto pred zapisem ------
new_disks
LF="disk dev=$LOOP1 table=new
part id=p1 disk=$LOOP1 size=1G type=esp
part id=p2 disk=$LOOP1 size=rest
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
swap on=lv8"
LUKS_PASS=x run_scenario F uefi "$LF"
expect "F: plna VG odmitnuta pred zmenami (vg_full)" bash -c "[[ \$(cat '$WORK/F/rc') == 3 ]] && grep -q '^vg_full|luxos' '$WORK/F/errors'"
expect "F: disk zustal prazdny (zadna tabulka oddilu)" bash -c "[[ -z \$(blkid -p -o value -s PTTYPE $LOOP1) ]]"
# Hranice presne podle LVM: LV velikosti cele VG projde, o 1 extent vic ne
LUKS_PASS=x run_scenario F2 uefi "disk dev=$LOOP1 table=new
part id=p1 disk=$LOOP1 size=1G type=esp
part id=p2 disk=$LOOP1 size=rest
luks id=c on=p2 name=cryptlvm
vg id=v name=luxos pvs=c
lv id=r vg=v name=root size=$(( (DISK1_GB * 1024 - 1024 - 1 - 16 - 1) / 4 * 4 ))M
fs on=p1 mount=/boot type=vfat
fs on=r mount=/ type=ext4"
expect "F2: LV pres celou VG (vypocet = skutecne LVM) se vytvori" bash -c "[[ \$(cat '$WORK/F2/rc') == 0 ]] && [[ \$(vgs --noheadings -o vg_free_count luxos | tr -d ' ') == 0 ]]"

cleanup_disks
losetup -d "$LOOP1" "$LOOP2" 2>/dev/null || true
[[ -n ${KEEP-} ]] || rm -f "$WORK/disk1.img" "$WORK/disk2.img"
echo
echo "Vysledek: $NPASS ok, $NFAIL FAIL   (protokoly: $WORK/<scenar>/log)"
exit "$NFAIL"

# Rucni overeni (cela instalace a start; v jednorazovem virtualu s internetem):
#  1) VM s UEFI (OVMF) a dvema prazdnymi disky (vda 40G, vdb 20G), spustit live ISO.
#  2) Graficky instalator: Cil > Rucni rozdeleni > "Sifrovane LVM (/, /home, swap)" na vda, heslo, Install.
#     Po restartu: jeden dotaz na heslo (Plymouth), lsblk ukaze vda2 > cryptlvm > luxos-root/home/swap,
#     swapon --show ukaze zram i /dev/mapper/luxos-swap, cat /proc/cmdline obsahuje rd.luks.name.
#  3) Totez s "… /var a /tmp" a s vlastnim LUKS na LVM (jako scenar C): po startu jen jedno heslo,
#     crypthome a cryptswap se odemknou klici (journalctl -b -u systemd-cryptsetup@crypthome).
#  4) BIOS VM (SeaBIOS): predvolba vytvori BIOS boot + /boot ext4; GRUB se musi spustit a zeptat se na heslo.
#  5) Dual boot: disk s Windows (ESP + NTFS), zmenseni NTFS, ESP ponechat v /efi -> systemd-boot nabidne oba systemy.
