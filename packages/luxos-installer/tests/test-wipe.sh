#!/bin/bash
# LuxOS installer - testy bezpecneho smazani (WIPE, wipe.sh) BEZ roota a bez disku.
# dd, blkdiscard, sysfs i diskove nastroje nahrazuje mock-env.sh + mock-wipe.sh; skutecne programy
# dd/blkdiscard/mkfs/cryptsetup v PATH nahrazuji pojistky, ktere jen zaznamenaji volani (a test selze).
# Kontroluje se: konfigurace WIPE, volba zpusobu (secure/zeroout/dd) a navrat pri nepodpore, presne
# pokryti zarizeni po kusech, pojistky (cely disk, pripojene), zruseni souborem a Ctrl+C, chyba zapisu,
# prubeh (@@WIPE/@@PCT/@@STATUS), a ze se v kazdem rezimu mazou jen oddily LuxOS a vzdy pred LUKS/mkfs.
#
#   packages/luxos-installer/tests/test-wipe.sh       (vypis ok/FAIL, navratovy kod = pocet chyb)
#   KEEP=1 tests/test-wipe.sh                         (ponecha vystupy v $OUT)
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
FILES=$(cd "$HERE/../files" && pwd)
OUT=$(mktemp -d "${TMPDIR:-/tmp}/luxos-wipe-test.XXXXXX")
export TMPDIR=$OUT
NPASS=0 NFAIL=0

ok()  { NPASS=$((NPASS + 1)); printf 'ok    %s\n' "$1"; }
bad() { NFAIL=$((NFAIL + 1)); printf 'FAIL  %s\n' "$1"; [[ -n ${2-} ]] && printf '      %s\n' "$2"; return 0; }
expect() { local d=$1; shift; if "$@"; then ok "$d"; else bad "$d"; fi; }
has()    { grep -qF -- "$2" "$1"; }
hasnot() { ! grep -qF -- "$2" "$1" 2>/dev/null; }
before() {  # before SOUBOR TEXT1 TEXT2: posledni vyskyt TEXT1 je pred prvnim TEXT2
    local a b
    a=$(grep -nF -- "$2" "$1" | tail -1 | cut -d: -f1)
    b=$(grep -nF -- "$3" "$1" | head -1 | cut -d: -f1)
    [[ -n $a && -n $b && $a -lt $b ]]
}

# Pojistka: skutecne nastroje nesmi byt nikdy zavolany (funkce z mock-* maji prednost)
mkdir -p "$OUT/guard"
for t in dd blkdiscard mkfs.btrfs mkfs.ext4 mkfs.fat cryptsetup sgdisk wipefs; do
    printf '#!/bin/sh\necho "REAL %s $*" >>"%s/REAL_CALLS"\nexit 1\n' "$t" "$OUT" >"$OUT/guard/$t"
    chmod +x "$OUT/guard/$t"
done
export PATH="$OUT/guard:$PATH"

# Zakryti zarizeni: kusy jednoho zarizeni navazuji od 0 do VELIKOSTI bez mezer a prekryvu
covers() {  # covers SOUBOR_WIPE DEV VELIKOST [NASTROJ]
    awk -v d="$2" -v size="$3" -v t="${4-}" '
        $2 == d { if (t != "" && $1 != t) bad = 1; if ($3 != pos) bad = 1; pos = $3 + $4 }
        END { exit !(bad != 1 && pos == size) }' "$1"
}
GiB=$((1024 ** 3)) MiB=$((1024 ** 2))

# Prostredi jednoho behu (podshell): layout.sh, wipe.sh, nahrady
setup_env() {  # setup_env "vda:64G ..."
    set -Eeuo pipefail
    . "$FILES/layout.sh"
    . "$FILES/wipe.sh"
    . "$HERE/mock-env.sh"
    . "$HERE/mock-wipe.sh"
    # shellcheck disable=SC2086
    mock_init $1
    mkdir -p "$MOCK"/{sysfs,size,busy,label,mnt,vgfree}
    TARGET=$MOCK/target
    mkdir -p "$TARGET/etc"
    LOG=$MOCK/log PROGRESS=1 WIPE=zero WIPE_CANCEL_FILE=$MOCK/skip-wipe
    BOOTMODE=uefi BOOTLOADER=auto LUKS_PASS=heslo
    progress() { printf '@@%s\n' "$*" >>"$MOCK/progress"; }
    info() { printf '%s\n' "$*" >>"$MOCK/info"; }
    step() { mock_log "@@STEP $*"; }
}

# Oddil v emulaci: addp DISK CISLO VELIKOST_MIB KOD
addp() {
    local tbl=$MOCK/disks/$1.tbl start
    start=$(awk 'BEGIN {m = 2048} {if ($3 + 1 > m) m = $3 + 1} END {print m}' "$tbl")
    start=$(((start + 2047) / 2048 * 2048))
    echo "$2 $start $((start + $3 * 2048 - 1)) $4 part$2" >>"$tbl"
}

save() {  # save ADRESAR: vystupy behu
    mkdir -p "$1"
    for f in cmds wipe progress info; do cp "$MOCK/$f" "$1/$f" 2>/dev/null || : >"$1/$f"; done
}

run_case() {  # run_case JMENO DISKY KOD (v podshellu; rc do $OUT/JMENO/rc)
    local dir=$OUT/$1
    mkdir -p "$dir"
    (
        setup_env "$2"
        trap 'save "'"$dir"'"' EXIT
        eval "$3"
    ) >"$dir/out" 2>&1 </dev/null
    echo $? >"$dir/rc"
}
rc_is() { [[ $(<"$OUT/$1/rc") == "$2" ]]; }

echo "# vystupy: $OUT"

# ---------------------------------------------------------------------------------
echo "## A: konfigurace WIPE (check_wipe z luxos-install, install.conf.example)"
sed -n '/^check_wipe() {/,/^}/p' "$FILES/luxos-install" >"$OUT/check_wipe.sh"
grep -q '^check_wipe() {' "$OUT/check_wipe.sh" || bad "A: extrakce check_wipe"
cw() {  # cw "PROMENNE" -> rc 0/1 a hodnota WIPE
    (
        . "$FILES/wipe.sh"; . "$OUT/check_wipe.sh"
        T() { local f=$1; shift; printf -- "$f" "$@"; }
        fail() { echo "FAIL $*"; exit 1; }
        TARGET=/mnt DISK_MODE=erase
        unset WIPE
        eval "$1"
        check_wipe
        echo "WIPE=$WIPE"
    )
}
expect "A: bez WIPE -> none" test "$(cw '')" == "WIPE=none"
expect "A: WIPE=none" test "$(cw 'WIPE=none')" == "WIPE=none"
expect "A: WIPE=zero" test "$(cw 'WIPE=zero')" == "WIPE=zero"
expect "A: WIPE=overwrite" test "$(cw 'WIPE=overwrite')" == "WIPE=overwrite"
for m in freespace partition layout; do
    expect "A: WIPE=zero s DISK_MODE=$m" test "$(cw "WIPE=zero DISK_MODE=$m")" == "WIPE=zero"
done
out=$(cw 'WIPE=random'); expect "A: neplatna hodnota -> chyba" grep -q '^FAIL Invalid WIPE' <<<"$out"
out=$(cw 'WIPE=ZERO'); expect "A: velka pismena neplatna" grep -q '^FAIL Invalid WIPE' <<<"$out"
out=$(cw 'WIPE=zero DISK_MODE=manual'); expect "A: manual + WIPE -> chyba" grep -q '^FAIL WIPE is not available' <<<"$out"
expect "A: manual + WIPE=none je OK" test "$(cw 'WIPE=none DISK_MODE=manual')" == "WIPE=none"
expect "A: install.conf.example ma WIPE=none" grep -q '^WIPE=none ' "$FILES/install.conf.example"
expect "A: vychozi WIPE pri --config" grep -q '"${WIPE:=none}"' "$FILES/luxos-install"
expect "A: wipe.sh v PKGBUILD" grep -q 'installer/wipe.sh' "$HERE/../PKGBUILD"
expect "A: luxos-install nacita wipe.sh" grep -q '^\. "\$SHARE/wipe.sh"' "$FILES/luxos-install"
# poradi v main: priprava rezimu -> (TUI dotaz) -> check_wipe -> kroky -> souhrn -> priprava disku
main_body=$(sed -n '/^main() {/,/^}/p' "$FILES/luxos-install")
expect "A: check_wipe pred souhrnem a pripravou disku" bash -c '
    b=$1; c=${b%%check_wipe*}; s=${b%%    summary*}; p=${b%%prepare_disk ;;*}
    (( ${#c} < ${#s} && ${#s} < ${#p} ))' _ "$main_body"

# ---------------------------------------------------------------------------------
echo "## B: zpusob mazani, kusy, pojistky (wipe_device)"
# B1: HDD bez podpory prikazu -> dd po 256 MiB, posledni kus castecny
run_case B1 "vda:64G" '
    addp vda 1 1025 8304; echo $((GiB + 4096)) >"$MOCK/size/vda1"
    wipe_devices /dev/vda1'
c=$OUT/B1/wipe
expect "B1: probehlo" rc_is B1 0
expect "B1: dd pokryje cely oddil presne" covers "$c" /dev/vda1 $((GiB + 4096)) dd
expect "B1: kusy po 256 MiB (5 kusu)" test "$(wc -l <"$c")" == 5
expect "B1: posledni kus 4096 B" test "$(tail -1 "$c" | cut -d' ' -f4)" == 4096
expect "B1: dd s O_DIRECT a /dev/zero (bez chyby argumentu)" hasnot "$OUT/B1/cmds" "BAD ARGS"
expect "B1: nic jineho nez vda1" test "$(cut -d' ' -f2 "$c" | sort -u)" == /dev/vda1
expect "B1: @@WIPE START/END" bash -c "grep -qx '@@WIPE START' '$OUT/B1/progress' && tail -1 '$OUT/B1/progress' | grep -qx '@@WIPE END'"
expect "B1: @@PCT konci na 100" test "$(grep '^@@PCT' "$OUT/B1/progress" | tail -1)" == "@@PCT 100"
expect "B1: @@PCT neklesa" bash -c "grep '^@@PCT' '$OUT/B1/progress' | awk '{if (\$2 < p) exit 1; p = \$2}'"
expect "B1: @@STATUS s prubehem" grep -q '^@@STATUS Erasing /dev/vda1: 100 %' "$OUT/B1/progress"

# B2: disk umi bezpecne smazani (discard) -> blkdiscard --secure po 4 GiB
run_case B2 "nvme0n1:64G" '
    addp nvme0n1 2 10240 8304; echo 4294967296 >"$MOCK/sysfs/nvme0n1.discard_max_bytes"
    wipe_devices /dev/nvme0n1p2'
expect "B2: secure discard pokryje oddil" covers "$OUT/B2/wipe" /dev/nvme0n1p2 $((10 * GiB)) secure
expect "B2: 3 kusy (4+4+2 GiB)" test "$(wc -l <"$OUT/B2/wipe")" == 3
expect "B2: zadne dd" hasnot "$OUT/B2/wipe" "dd "

# B3: secure nepodporovano, Write Zeroes ano -> blkdiscard -z od zacatku
run_case B3 "nvme0n1:64G" '
    addp nvme0n1 1 2048 8304; : >"$MOCK/nosecure"
    echo 1 >"$MOCK/sysfs/nvme0n1.discard_max_bytes"; echo 131072 >"$MOCK/sysfs/nvme0n1.write_zeroes_max_bytes"
    wipe_devices /dev/nvme0n1p1'
expect "B3: navrat na zeroout, cele pokryto" covers "$OUT/B3/wipe" /dev/nvme0n1p1 $((2 * GiB)) zeroout
expect "B3: pokus o secure zaznamenan" has "$OUT/B3/cmds" "blkdiscard --secure EOPNOTSUPP /dev/nvme0n1p1"

# B4: secure nepodporovano, Write Zeroes ne -> dd
run_case B4 "sda:64G" '
    addp sda 1 512 8304; : >"$MOCK/nosecure"; echo 1 >"$MOCK/sysfs/sda.discard_max_bytes"
    wipe_devices /dev/sda1'
expect "B4: navrat na dd, cele pokryto" covers "$OUT/B4/wipe" /dev/sda1 $((512 * MiB)) dd

# B5: WIPE=overwrite = vzdy dd, i kdyz disk umi prikazy
run_case B5 "nvme0n1:64G" '
    addp nvme0n1 1 512 8304; WIPE=overwrite
    echo 1 >"$MOCK/sysfs/nvme0n1.discard_max_bytes"; echo 1 >"$MOCK/sysfs/nvme0n1.write_zeroes_max_bytes"
    wipe_devices /dev/nvme0n1p1'
expect "B5: overwrite -> jen dd" covers "$OUT/B5/wipe" /dev/nvme0n1p1 $((512 * MiB)) dd

# B6: pojistky - cely disk, pripojeny oddil, neexistujici zarizeni: chyba a zadny zapis
run_case B6a "vda:64G" 'wipe_devices /dev/vda'
expect "B6: cely disk odmitnut" bash -c "rc=\$(cat '$OUT/B6a/rc'); [[ \$rc == 1 ]] && grep -q 'FAIL Refusing to erase /dev/vda (type disk)' '$OUT/B6a/cmds'"
expect "B6: cely disk - zadny zapis" test ! -s "$OUT/B6a/wipe"
run_case B6b "vda:64G" 'addp vda 1 512 8304; : >"$MOCK/busy/vda1"; wipe_devices /dev/vda1'
expect "B6: pripojeny oddil odmitnut" bash -c "[[ \$(cat '$OUT/B6b/rc') == 1 ]] && grep -q 'FAIL Cannot erase /dev/vda1: it is in use' '$OUT/B6b/cmds'"
expect "B6: pripojeny - zadny zapis" test ! -s "$OUT/B6b/wipe"
run_case B6c "vda:64G" 'wipe_devices /dev/vda7'
expect "B6: neexistujici zarizeni odmitnuto" bash -c "[[ \$(cat '$OUT/B6c/rc') == 1 ]] && test ! -s '$OUT/B6c/wipe'"

# B7: zruseni z GUI (soubor) po 3 kusech: zbytek i dalsi zarizeni preskoceny, instalace pokracuje
run_case B7 "vda:64G" '
    addp vda 1 2048 8304; addp vda 2 2048 8304; echo 3 >"$MOCK/cancel_after"
    wipe_devices /dev/vda1 /dev/vda2; echo "AFTER rc=$? cancelled=$WIPE_CANCELLED"'
expect "B7: konec bez chyby" rc_is B7 0
expect "B7: pokracuje dal" grep -q 'AFTER rc=0 cancelled=1' "$OUT/B7/out"
expect "B7: jen 3 kusy" test "$(wc -l <"$OUT/B7/wipe")" == 3
expect "B7: vda2 nezacato" hasnot "$OUT/B7/wipe" /dev/vda2
expect "B7: hlaska o preskoceni" grep -q '^@@STATUS Erasing was skipped' "$OUT/B7/progress"
expect "B7: @@WIPE END i po zruseni" test "$(tail -1 "$OUT/B7/progress")" == "@@WIPE END"

# B8: Ctrl+C (SIGINT) behem 2. kusu: preskoceni, ne konec instalatoru; trap INT pak zrusen
run_case B8 "vda:64G" '
    addp vda 1 2048 8304; addp vda 2 2048 8304; echo 2 >"$MOCK/int_after"
    wipe_devices /dev/vda1 /dev/vda2; echo "AFTER cancelled=$WIPE_CANCELLED trap=[$(trap -p INT)]"'
expect "B8: konec bez chyby" rc_is B8 0
expect "B8: preskoceno, trap INT vracen" grep -q 'AFTER cancelled=1 trap=\[\]' "$OUT/B8/out"
expect "B8: po Ctrl+C uz nic" test "$(wc -l <"$OUT/B8/wipe")" == 2

# B9: chyba zapisu uprostred -> instalace konci chybou (ne tichy uspech)
run_case B9 "vda:64G" '
    addp vda 1 1024 8304; echo $((256 * MiB)) >"$MOCK/ddfail"
    wipe_devices /dev/vda1'
expect "B9: chyba zapisu = chyba instalace" bash -c "[[ \$(cat '$OUT/B9/rc') == 1 ]] && grep -q 'FAIL Erasing /dev/vda1 failed' '$OUT/B9/cmds'"
expect "B9: po chybe uz zadny dalsi kus" test "$(wc -l <"$OUT/B9/wipe")" == 2

# B10: WIPE=none -> nic; B11: stejne zarizeni jen jednou
run_case B10 "vda:64G" 'addp vda 1 512 8304; WIPE=none; wipe_devices /dev/vda1'
expect "B10: WIPE=none nic nezapise ani nehlasi" bash -c "test ! -s '$OUT/B10/wipe' && test ! -s '$OUT/B10/progress'"
run_case B11 "vda:64G" 'addp vda 1 512 8304; wipe_devices /dev/vda1 /dev/vda1; wipe_devices /dev/vda1'
expect "B11: zarizeni smazano jen jednou" covers "$OUT/B11/wipe" /dev/vda1 $((512 * MiB)) dd

# B12: odhad doby a rychlosti podle disku
est=$(
    . "$FILES/wipe.sh"; T() { local f=$1; shift; printf -- "$f" "$@"; }
    lsblk() { case ${!#} in /dev/sda) echo "1 sata" ;; /dev/sdb) echo "0 sata" ;; *) echo "0 nvme" ;; esac; }
    echo "$(wipe_estimate_text $((1000 ** 4)) /dev/sda)|$(wipe_estimate_text $((500 * 1000 ** 3)) /dev/sdb)|$(wipe_estimate_text $((512 * 1000 ** 3)) /dev/nvme0n1)|$(wipe_estimate_text $((10 * 1000 ** 3)) /dev/nvme0n1)"
)
expect "B12: odhady HDD 1 TB / SSD 500 GB / NVMe 512 GB / 10 GB" test "$est" == "about 2 h 8 min|about 19 min|about 6 min|under a minute"

# ---------------------------------------------------------------------------------
echo "## C: rucni rozdeleni a existujici oddil (layout_apply): jen oblasti LuxOS, pred LUKS/mkfs"
lay_case() {  # lay_case JMENO DISKY PRIPRAVA LAYOUT
    run_case "$1" "$2" "$3"'
        layout_parse "$LAYOUT_TEXT"; layout_validate
        ((${#LY_ERR[@]})) || layout_check_devices
        ((${#LY_ERR[@]} == 0)) || { printf "ERR %s\n" "${LY_ERR[@]}"; exit 3; }
        layout_steps >"'"$OUT/$1"'/steps"
        { layout_wipe_ids; echo --; for id in $(ly_ids lv); do ly_wipe_lv_later "$id" && echo "$id"; done; } >"'"$OUT/$1"'/ids"
        layout_apply
        layout_teardown'
}

# C1: cely disk (nova GPT), ESP + sifrovany /
LAYOUT_TEXT='disk dev=/dev/vda table=new
part id=esp disk=/dev/vda size=1G type=esp
part id=r disk=/dev/vda size=rest
luks id=cr on=r name=cryptroot
fs on=esp mount=/boot type=vfat
fs on=cr mount=/ type=btrfs'
export LAYOUT_TEXT
lay_case C1 "vda:24G" ''
c=$OUT/C1/cmds
expect "C1: probehlo" rc_is C1 0
expect "C1: smazany jen novy ESP a /" test "$(cut -d' ' -f2 "$OUT/C1/wipe" | sort -u | tr '\n' ' ')" == "/dev/vda1 /dev/vda2 "
expect "C1: ESP cely" covers "$OUT/C1/wipe" /dev/vda1 $((GiB))
expect "C1: mazani az po rozdeleni" before "$c" "sgdisk -n" "wipe-chunk"
expect "C1: mazani pred LUKS" before "$c" "wipe-chunk" "cryptsetup luksFormat"
expect "C1: mazani pred mkfs" before "$c" "wipe-chunk" "mkfs."
expect "C1: krok mazani" grep -q "@@STEP Erasing the space for LuxOS" "$c"
expect "C1: pocet kroku +1" test "$(<"$OUT/C1/steps")" == 4
expect "C1: nikdy cely disk" bash -c "! grep -q ' /dev/vda ' '$OUT/C1/wipe'"

LAYOUT_TEXT=$LAYOUT_TEXT lay_case C1n "vda:24G" 'WIPE=none'
expect "C1n: WIPE=none bez mazani i bez kroku" bash -c "test ! -s '$OUT/C1n/wipe' && ! grep -q 'Erasing the space' '$OUT/C1n/cmds' && [[ \$(cat '$OUT/C1n/steps') == 3 ]]"

# C2: existujici oddil (jako DISK_MODE=partition): / do vda3, sdileny ESP a /home bez formatovani
PREP_C2='addp vda 1 512 ef00; echo vfat >"$MOCK/fs/vda1"
addp vda 2 30720 0700; echo ntfs >"$MOCK/fs/vda2"
addp vda 3 25600 8300; echo ext4 >"$MOCK/fs/vda3"
addp vdb 1 40960 8300; echo ext4 >"$MOCK/fs/vdb1"'
LAYOUT_TEXT='use id=root dev=/dev/vda3
luks id=croot on=root name=cryptroot
fs on=croot mount=/ type=btrfs
use id=esp dev=/dev/vda1
fs on=esp mount=/efi type=vfat format=0
use id=home dev=/dev/vdb1
fs on=home mount=/home type=ext4 format=0' lay_case C2 "vda:64G vdb:64G" "$PREP_C2"
c=$OUT/C2/cmds
expect "C2: probehlo" rc_is C2 0
expect "C2: smazan jen vybrany oddil vda3" test "$(cut -d' ' -f2 "$OUT/C2/wipe" | sort -u)" == /dev/vda3
expect "C2: vda3 cely" covers "$OUT/C2/wipe" /dev/vda3 $((25600 * MiB))
expect "C2: Windows, ESP a /home netknute" bash -c "! grep -qE '/dev/(vda1|vda2|vdb1) ' '$OUT/C2/wipe'"
expect "C2: mazani pred LUKS" before "$c" "wipe-chunk" "cryptsetup luksFormat"

# C3: zachovana skupina LVM: nove LV (az po lvcreate), LV s formatovanim, LV se zachovanymi daty
PREP_C3='cat >"$MOCK/disks/vdb.tbl" <<T
1 2048 1050623 ef00 EFI
2 1050624 67108830 8309 LuxOS
T
printf stare >"$MOCK/luks/vdb2"; echo vfat >"$MOCK/fs/vdb1"
echo /dev/mapper/x >"$MOCK/vg/oldvg"; : >"$MOCK/lv/oldvg-home"; : >"$MOCK/lv/oldvg-root"; : >"$MOCK/lv/oldvg-tmp"
echo $((2 * GiB)) >"$MOCK/size/mapper_oldvg-tmp"; echo $((3 * GiB)) >"$MOCK/size/mapper_oldvg-data"
echo $((4 * GiB)) >"$MOCK/vgfree/oldvg"
LUKS_PASS_CO=stare'
LAYOUT_TEXT='disk dev=/dev/vda table=new
part id=esp disk=/dev/vda size=1G type=esp
part id=r disk=/dev/vda size=rest
use  id=old dev=/dev/vdb2
luks id=co on=old name=cryptold keep=1
vg   id=ovg name=oldvg keep=1
lv   id=oh vg=ovg name=home keep=1
lv   id=ot vg=ovg name=tmp keep=1
lv   id=nd vg=ovg name=data size=3G
delete dev=/dev/oldvg/root
fs   on=esp mount=/boot type=vfat
fs   on=r mount=/ type=btrfs
fs   on=oh mount=/home type=ext4 format=0
fs   on=ot mount=/var/tmp type=ext4
fs   on=nd mount=/data type=ext4' lay_case C3 "vda:40G vdb:32G" "$PREP_C3"
c=$OUT/C3/cmds
expect "C3: probehlo" rc_is C3 0
expect "C3: cile: nove oddily, LV tmp (formatovany); pozdeji nove LV data" test "$(tr '\n' ' ' <"$OUT/C3/ids")" == "esp r ot -- nd "
expect "C3: smazana zarizeni" test "$(cut -d' ' -f2 "$OUT/C3/wipe" | sort -u | tr '\n' ' ')" == "/dev/mapper/oldvg-data /dev/mapper/oldvg-tmp /dev/vda1 /dev/vda2 "
expect "C3: /home (format=0) a stary LUKS netknute" bash -c "! grep -qE 'oldvg-home|/dev/vdb' '$OUT/C3/wipe'"
expect "C3: mazane LV root se nemaze prepisem" hasnot "$OUT/C3/wipe" "oldvg-root"
expect "C3: nove LV smazano az po lvcreate" before "$c" "lvcreate" "wipe-chunk dd /dev/mapper/oldvg-data"
expect "C3: nove LV smazano pred mkfs" before "$c" "wipe-chunk dd /dev/mapper/oldvg-data" "mkfs.ext4 -F -L data"
expect "C3: LV tmp cely" covers "$OUT/C3/wipe" /dev/mapper/oldvg-tmp $((2 * GiB))
expect "C3: LV tmp smazan pred mkfs" before "$c" "wipe-chunk dd /dev/mapper/oldvg-tmp" "mkfs.ext4 -F -L tmp"

# C4: zachovany disk: smazany stary oddil a novy oddil v uvolnenem miste -> maze se jen novy
PREP_C4='addp vda 1 512 ef00; echo vfat >"$MOCK/fs/vda1"
addp vda 2 20480 0700; echo ntfs >"$MOCK/fs/vda2"
addp vda 3 20480 8300; echo ext4 >"$MOCK/fs/vda3"'
LAYOUT_TEXT='use id=esp dev=/dev/vda1
delete dev=/dev/vda3
part id=r disk=/dev/vda size=rest
fs on=esp mount=/efi type=vfat format=0
fs on=r mount=/ type=btrfs' lay_case C4 "vda:64G" "$PREP_C4"
expect "C4: probehlo" rc_is C4 0
expect "C4: smazan jen novy oddil (vda3)" test "$(cut -d' ' -f2 "$OUT/C4/wipe" | sort -u)" == /dev/vda3
expect "C4: Windows a ESP netknute" bash -c "! grep -qE '/dev/vda[12] ' '$OUT/C4/wipe'"
expect "C4: smazani stareho oddilu predchazi prepisu" before "$OUT/C4/cmds" "sgdisk -d 3" "wipe-chunk"

# C5: shoda s GUI modelem (luxos_layout.wipe_targets) na predvolbach a zachovane VG
pyids=$(python3 -I - "$FILES" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import luxos_layout as m
L = m.Layout(m.fake_scan())
L.preset("/dev/sdb", "lvm_var")
print(" ".join(sorted(n.id for n, b in L.wipe_targets())))
print(" ".join(sorted(n.id for n in L.of("part") if not n.existing)))
print(all(b > 0 for n, b in L.wipe_targets()))
PY
)
expect "C5: GUI model: predvolba maze prave nove oddily (velikosti > 0)" bash -c '
    a=$(sed -n 1p <<<"$1"); b=$(sed -n 2p <<<"$1"); [[ -n $a && $a == "$b" ]] && [[ $(sed -n 3p <<<"$1") == True ]]' _ "$pyids"
pymix=$(python3 -I - "$FILES" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import luxos_layout as m
L = m.Layout(m.fake_scan())
luks = next(n for n in L.of("luks") if n.existing)
L.unlock_fake(luks.id)
vg = next(n for n in L.of("vg") if n.name == "oldvg")
home = next(n for n in L.lvs_of(vg.id) if n.name == "home")
root = next(n for n in L.lvs_of(vg.id) if n.name == "root")
L.set_use(home.id, {"type": "fs", "mount": "/home", "fstype": "ext4", "format": False})
L.set_use(root.id, {"type": "fs", "mount": "/var", "fstype": "ext4", "format": True})
esp = next(n for n in L.of("part") if n.dev == "/dev/nvme0n1p1")
L.set_use(esp.id, {"type": "fs", "mount": "/efi", "fstype": "vfat", "format": False})
r = L.add_part("/dev/nvme0n1", 60 * m.GiB)
L.set_use(r.id, {"type": "fs", "mount": "/", "fstype": "btrfs", "format": True})
nl = L.add_lv(vg.id, "data", 1 * m.GiB, use={"type": "fs", "mount": "/data", "fstype": "ext4", "format": True})
win = next(n for n in L.of("part") if n.dev == "/dev/nvme0n1p3")
t = {n.id for n, b in L.wipe_targets()}
print(r.id in t, root.id in t, nl.id in t, home.id not in t, esp.id not in t, win.id not in t, luks.id not in t)
PY
)
expect "C5: GUI model: novy oddil, formatovane LV, nove LV v zachovane VG; ne /home, ESP, Windows, LUKS" \
    test "$pymix" == "True True True True True True True"

# ---------------------------------------------------------------------------------
echo "## D: automaticke rezimy (prepare_disk, prepare_freespace z luxos-install)"
# Funkce z instalatoru; [[ -b ]] nelze nahradit funkci -> v kopii pres ly_isblk (emulace)
for f in part_path encrypt_root mount_root prepare_disk prepare_freespace free_partnum; do
    sed -n "/^$f() {/,/^}/p" "$FILES/luxos-install"
done | sed -e 's/\[\[ -b \$BOOTPART && -b \$rootpart \]\]/{ ly_isblk "$BOOTPART" \&\& ly_isblk "$rootpart"; }/' \
           -e 's/\[\[ -b \$rootpart \]\]/ly_isblk "$rootpart"/' \
           -e 's/\[\[ -b \$p \]\]/ly_isblk "$p"/' >"$OUT/auto.sh"
expect "D: extrakce a nahrada -b" bash -c "grep -q '^prepare_disk() {' '$OUT/auto.sh' && ! grep -q '\[\[ -b' '$OUT/auto.sh'"
auto_case() {  # auto_case JMENO DISKY KOD
    run_case "$1" "$2" '. "'"$OUT"'/auto.sh"; ENCRYPT=${ENCRYPT:-1}
        # instalator pise "-n1:0:+1G" (spojene, G); emulace umi "-n 1:0:+1024M"
        eval "mock_sgdisk_orig () $(declare -f sgdisk | tail -n +2)"
        sgdisk() {
            local -a a=() ; local x o
            for x in "$@"; do
                if [[ $x =~ ^-([ntc])([0-9].*)$ ]]; then
                    o=${BASH_REMATCH[1]} x=${BASH_REMATCH[2]}
                    [[ $x =~ ^(.*)\+([0-9]+)G$ ]] && x=${BASH_REMATCH[1]}+$((BASH_REMATCH[2] * 1024))M
                    a+=("-$o" "$x")
                else a+=("$x"); fi
            done
            mock_sgdisk_orig "${a[@]}"
        }
        '"$3"
}
auto_case D1 "vda:32G" 'DISK=/dev/vda; prepare_disk'
c=$OUT/D1/cmds
expect "D1: probehlo (erase, UEFI, sifrovani)" rc_is D1 0
expect "D1: smazany jen novy ESP a oddil LuxOS" test "$(cut -d' ' -f2 "$OUT/D1/wipe" | sort -u | tr '\n' ' ')" == "/dev/vda1 /dev/vda2 "
expect "D1: po rozdeleni" before "$c" "sgdisk -n 1:0:+1024M" "wipe-chunk"
expect "D1: pred LUKS a mkfs" bash -c "$(declare -f before); before '$c' wipe-chunk 'cryptsetup luksFormat' && before '$c' wipe-chunk mkfs."
expect "D1: krok mazani" grep -q "@@STEP Erasing the space for LuxOS" "$c"
auto_case D1n "vda:32G" 'DISK=/dev/vda; WIPE=none; prepare_disk'
expect "D1n: WIPE=none -> zadne mazani" bash -c "rc=\$(cat '$OUT/D1n/rc'); [[ \$rc == 0 ]] && test ! -s '$OUT/D1n/wipe' && ! grep -q Erasing '$OUT/D1n/cmds'"
auto_case D2 "vda:64G" '
    addp vda 1 512 ef00; echo vfat >"$MOCK/fs/vda1"; addp vda 2 20480 0700; echo ntfs >"$MOCK/fs/vda2"
    DISK=/dev/vda ESP_PART=/dev/vda1 BOOTLOADER=auto ENCRYPT=0
    check_freespace() { FS_ERR="" FS_START=$((22 * 1024 * 2048)) FS_END=$((60 * 1024 * 2048)) FS_BYTES=$((38 * GiB)); }
    prepare_freespace'
c=$OUT/D2/cmds
expect "D2: probehlo (vedle Windows)" rc_is D2 0
expect "D2: smazan jen novy oddil vda3" test "$(cut -d' ' -f2 "$OUT/D2/wipe" | sort -u)" == /dev/vda3
expect "D2: novy oddil cely" covers "$OUT/D2/wipe" /dev/vda3 $(((60 * 1024 * 2048 - 22 * 1024 * 2048 + 1) * 512))
expect "D2: pred mkfs" before "$c" "wipe-chunk" "mkfs.btrfs"

# ---------------------------------------------------------------------------------
echo "## F: TUI - dotaz a souhrn (ask_wipe, wipe_text z luxos-install)"
for f in human_bytes ask_wipe wipe_text wipe_area_bytes wipe_disk_hint; do
    sed -n "/^$f() {/,/^}/p" "$FILES/luxos-install"
done >"$OUT/tui.sh"
tui_case() {  # tui_case JMENO DISKY KOD
    run_case "$1" "$2" '. "'"$OUT"'/tui.sh"; title() { echo "TITLE $*"; }; info() { echo "INFO $*"; }
        ENCRYPT=0; '"$3"
}
tui_case F1 "vda:64G" 'DISK=/dev/vda DISK_MODE=erase; gum() { echo "GUM $*"; return 0; }; ask_wipe; echo "WIPE=$WIPE"; echo "TEXT=$(wipe_text)"'
expect "F1: potvrzeno -> WIPE=zero" grep -qx 'WIPE=zero' "$OUT/F1/out"
expect "F1: odhad z velikosti disku" grep -q '^INFO Area: 68.8GB. This can take long: about 9 min' "$OUT/F1/out"
expect "F1: vychozi volba Ne" grep -q 'GUM confirm --default=false' "$OUT/F1/out"
expect "F1: souhrn" grep -qx 'TEXT=yes, 68.8GB (about 9 min)' "$OUT/F1/out"
tui_case F2 "vda:64G" 'DISK=/dev/vda DISK_MODE=erase ENCRYPT=1; gum() { return 1; }; ask_wipe; echo "WIPE=$WIPE"; echo "TEXT=$(wipe_text)"'
expect "F2: odmitnuto -> none" grep -qx 'WIPE=none' "$OUT/F2/out"
expect "F2: se sifrovanim doporuceno" grep -q '^INFO Recommended with encryption' "$OUT/F2/out"
expect "F2: souhrn no" grep -qx 'TEXT=no' "$OUT/F2/out"
tui_case F3 "vda:64G" 'DISK=manual DISK_MODE=manual; gum() { echo GUM; return 0; }; ask_wipe; echo "WIPE=$WIPE"'
expect "F3: manual -> bez dotazu, none" bash -c "grep -qx 'WIPE=none' '$OUT/F3/out' && ! grep -q GUM '$OUT/F3/out'"
tui_case F4 "vda:64G" 'addp vda 3 25600 8300; DISK=/dev/vda DISK_MODE=partition ROOT_PART=/dev/vda3; gum() { return 0; }; ask_wipe; echo "TEXT=$(wipe_text)"'
expect "F4: existujici oddil: velikost oddilu" grep -qx 'TEXT=yes, 26.9GB (about 4 min)' "$OUT/F4/out"
LAYOUT_TEXT='disk dev=/dev/vda table=new
part id=esp disk=/dev/vda size=1G type=esp
part id=r disk=/dev/vda size=rest
fs on=esp mount=/boot type=vfat
fs on=r mount=/ type=btrfs' tui_case F5 "vda:32G" 'DISK=layout DISK_MODE=layout; layout_parse "$LAYOUT_TEXT"; layout_validate; layout_check_devices
    gum() { return 0; }; ask_wipe; echo "TEXT=$(wipe_text)"'
expect "F5: rucni rozdeleni: soucet novych oddilu" grep -qx 'TEXT=yes, 34.4GB (about 5 min)' "$OUT/F5/out"

# ---------------------------------------------------------------------------------
echo "## E: bezpecnost testu"
expect "E: zadne volani skutecnych nastroju" test ! -e "$OUT/REAL_CALLS"

echo
echo "Vysledek: $NPASS ok, $NFAIL FAIL"
[[ -n ${KEEP-} ]] || { ((NFAIL)) || rm -rf "$OUT"; }
exit "$NFAIL"
