# LuxOS - rucni rozdeleni disku (DISK_MODE=layout): parser, kontrola, provedeni, crypttab/fstab/cmdline
#
# Knihovnu nacita luxos-install (/usr/share/luxos/installer/layout.sh). Od volajiciho potrebuje:
#   run, step, info, fail, progress, T, TARGET, BOOTMODE, BOOTLOADER, LUKS_PASS (+ LUKS_PASS_<ID>)
# Prikazy menici disky jdou vyhradne pres "run" (testy je nahrazuji zaznamem, viz tests/).
#
# Format LAYOUT (radky "druh klic=hodnota ...", # komentar; poradi radku = poradi zakladani):
#   disk   dev=/dev/vda table=new|keep          new = smazat cely disk, nova prazdna GPT
#   part   id=ID disk=/dev/vda size=1G|rest [type=esp|bios|linux|swap|lvm|luks|boot] [name=TEXT]
#   use    id=ID dev=/dev/sda2 [resize=100G]    existujici oddil/zarizeni (volitelne zmenit velikost)
#   delete dev=/dev/sda3                        smazat existujici oddil
#   luks   id=ID on=ID name=MAPPER [keep=1]     LUKS2 (keep=1: existujici kontejner jen odemknout)
#   vg     id=ID name=VG pvs=ID[,ID] [keep=1]   skupina svazku LVM (keep=1: existujici)
#   lv     id=ID vg=ID name=LV size=40G|rest [keep=1]
#   fs     on=ID mount=/home type=btrfs|ext4|xfs|f2fs|vfat [format=1|0] [label=X] [subvol=@home]
#   swap   on=ID [format=1|0]
# Velikosti: cele cislo s K/M/G/T (binarni, jako sgdisk a lvcreate), "rest" = zbytek mista.
# Hesla nejsou v LAYOUT: LUKS_PASS_<ID velkymi> nebo spolecne LUKS_PASS.

declare -gA L=()      # "id.klic" -> hodnota; "id.kind" druh objektu
declare -ga L_IDS=()  # poradi objektu
declare -ga LY_ERR=() # chyby "kod|detail"
declare -ga LY_WARN=()
declare -ga LY_OPENED=()   # aktivovane LUKS/VG (pro uklid v opacnem poradi)

LY_MIN_ESP=$((300 * 1000 * 1000))
LY_MIN_ROOT=$((8 * 1024 * 1024 * 1024))
LY_WARN_ROOT=$((20 * 1024 * 1024 * 1024))
LY_MIN_BOOT=$((300 * 1024 * 1024))
# Vypocet kapacity (stejne jako luxos_layout.py a skutecne LVM): data LUKS2 zacinaji po 16 MiB
# (luksFormat --offset 32768), PV ma 1 MiB metadat (pe_start), extent 4 MiB, oddily zarovnane na 1 MiB
LY_MiB=$((1024 * 1024))
LY_LUKS_HEADER=$((16 * LY_MiB))
LY_LUKS_OFFSET=32768
LY_PE_START=$((1 * LY_MiB))
LY_EXTENT=$((4 * LY_MiB))
LY_FORBIDDEN_MOUNTS=" /usr /etc /bin /sbin /lib /lib64 /proc /sys /dev /run /boot/efi /var/lib/pacman "

ly_err()  { LY_ERR+=("$1|${2-}"); }
ly_isblk() { [[ -b $1 ]]; }   # testy nahrazuji (zarizeni bez roota neexistuji)
ly_warn() { LY_WARN+=("$1|${2-}"); }

ly_keys() {  # povolene klice podle druhu
    case $1 in
        disk)   echo "dev table" ;;
        part)   echo "id disk size type name" ;;
        use)    echo "id dev resize" ;;
        delete) echo "dev" ;;
        luks)   echo "id on name keep" ;;
        vg)     echo "id name pvs keep" ;;
        lv)     echo "id vg name size keep" ;;
        fs)     echo "on mount type format label subvol" ;;
        swap)   echo "on format" ;;
    esac
}

ly_bytes() {  # ly_bytes 40G -> bajty (binarni jednotky); "rest" -> -1; chyba -> navrat 1
    local s=$1 n u
    [[ $s == rest ]] && { echo -1; return 0; }
    [[ $s =~ ^([0-9]+)([KMGT]?)i?B?$ ]] || return 1
    n=${BASH_REMATCH[1]} u=${BASH_REMATCH[2]}
    case $u in
        K) n=$((n * 1024)) ;; M) n=$((n * 1024 ** 2)) ;; G) n=$((n * 1024 ** 3)) ;; T) n=$((n * 1024 ** 4)) ;;
    esac
    ((n > 0)) || return 1
    echo "$n"
}

ly_mib() { echo $(( ($1 + 1024 * 1024 - 1) / (1024 * 1024) )); }   # bajty -> MiB (nahoru)

# --- Nacteni -------------------------------------------------------------------
layout_parse() {  # layout_parse TEXT -> L, L_IDS, LY_ERR (syntax)
    L=() L_IDS=() LY_ERR=() LY_WARN=()
    local text=$1 line n=0 kind tok key val id allowed
    local -a toks
    while IFS= read -r line || [[ -n $line ]]; do
        n=$((n + 1))
        line=${line%%#*}
        read -ra toks <<<"$line"
        ((${#toks[@]})) || continue
        kind=${toks[0]}
        allowed=$(ly_keys "$kind")
        if [[ -z $allowed ]]; then ly_err syntax "$n:$kind"; continue; fi
        local -A kv=()
        for tok in "${toks[@]:1}"; do
            key=${tok%%=*} val=${tok#*=}
            if [[ $tok != *=* || -z $val || " $allowed " != *" $key "* ]]; then
                ly_err syntax "$n:$tok"; continue
            fi
            [[ -n ${kv[$key]+x} ]] && ly_err syntax "$n:$key"
            kv[$key]=$val
        done
        if [[ " $allowed " == *" id "* ]]; then
            id=${kv[id]-}
            if [[ ! $id =~ ^[a-z][a-z0-9_]{0,30}$ ]]; then ly_err bad_id "$n:${id}"; unset kv; continue; fi
            if [[ -n ${L[$id.kind]+x} ]]; then ly_err dup_id "$id"; unset kv; continue; fi
        else
            id="_$n"
        fi
        L[$id.kind]=$kind
        L[$id.line]=$n
        for key in "${!kv[@]}"; do L[$id.$key]=${kv[$key]}; done
        L_IDS+=("$id")
        unset kv
    done <<<"$text"
    return 0
}

ly_ids() {  # ly_ids DRUH -> id objektu daneho druhu v poradi
    local id
    for id in "${L_IDS[@]}"; do [[ ${L[$id.kind]} == "$1" ]] && echo "$id"; done
    return 0
}

ly_is_block() { [[ ${L[$1.kind]-} == @(part|use|luks|lv) ]]; }   # objekt nesouci data (lze na nem neco postavit)

ly_consumers() {  # spocita L[id.by] = kdo objekt pouziva (luks/vg/fs/swap); dvoji pouziti -> chyba
    local id ref p
    for id in "${L_IDS[@]}"; do
        case ${L[$id.kind]} in
            luks|fs|swap) ref=${L[$id.on]-} ;;
            vg) ref=${L[$id.pvs]-} ;;
            *) continue ;;
        esac
        for p in ${ref//,/ }; do
            if [[ -z ${L[$p.kind]+x} ]]; then ly_err ref_missing "$p"; continue; fi
            if ! ly_is_block "$p"; then ly_err ref_kind "$p"; continue; fi
            if [[ -n ${L[$p.by]-} ]]; then ly_err used_twice "$p"; continue; fi
            L[$p.by]=$id
        done
        [[ -n $ref || ${L[$id.kind]} == vg && ${L[$id.keep]-0} == 1 ]] || ly_err ref_missing "${L[$id.kind]}"
    done
}

ly_parents() {  # ly_parents ID -> primi predchudci (na cem objekt stoji)
    case ${L[$1.kind]-} in
        luks|fs|swap) echo "${L[$1.on]-}" ;;
        lv) echo "${L[$1.vg]-}" ;;
        vg) local v=${L[$1.pvs]-}; echo "${v//,/ }" ;;
    esac
}

ly_ancestors() {  # ly_ancestors ID -> vsechny objekty pod nim (vcetne nej)
    local -A seen=()
    local -a todo=("$1")
    local x p
    while ((${#todo[@]})); do
        x=${todo[0]}; todo=("${todo[@]:1}")
        [[ -z $x || -n ${seen[$x]+x} || -z ${L[$x.kind]+x} ]] && continue
        seen[$x]=1
        echo "$x"
        for p in $(ly_parents "$x"); do todo+=("$p"); done
    done
}

ly_encrypted() {  # ly_encrypted ID -> 0 pokud nekde pod objektem je LUKS
    local a
    for a in $(ly_ancestors "$1"); do [[ ${L[$a.kind]} == luks ]] && return 0; done
    return 1
}

ly_has_lvm() { local a; for a in $(ly_ancestors "$1"); do [[ ${L[$a.kind]} == @(lv|vg) ]] && return 0; done; return 1; }

ly_fs_by_mount() {  # ly_fs_by_mount /home -> id radku fs
    local id
    for id in $(ly_ids fs); do [[ ${L[$id.mount]-} == "$1" ]] && { echo "$id"; return 0; }; done
    return 0
}

ly_esp() {  # id fs, ktery je EFI oddil (vfat v /boot nebo /efi)
    local id
    for id in $(ly_ids fs); do
        [[ ${L[$id.type]-} == vfat && ${L[$id.mount]-} == @(/boot|/efi) ]] && { echo "$id"; return 0; }
    done
    return 0
}

ly_delete_lv() {  # delete na LV (/dev/VG/LV) -> 0; mazani LV az po odemceni/aktivaci skupiny
    [[ ${L[$1.dev]-} =~ ^/dev/([^/]+)/([^/]+)$ && ${BASH_REMATCH[1]} != mapper ]]
}

ly_bios_part() { local id; for id in $(ly_ids part); do [[ ${L[$id.type]-} == bios ]] && { echo "$id"; return 0; }; done; return 0; }

ly_root_chain() {  # LUKS objekty potrebne pro pripojeni / (odemyka initramfs)
    local r a
    r=$(ly_fs_by_mount /)
    [[ -n $r ]] || return 0
    for a in $(ly_ancestors "$r"); do [[ ${L[$a.kind]} == luks ]] && echo "$a"; done
    return 0
}

ly_pass() {  # heslo pro LUKS objekt: LUKS_PASS_<ID> nebo LUKS_PASS
    local v="LUKS_PASS_${1^^}"
    printf '%s' "${!v:-${LUKS_PASS-}}"
}

ly_random_swap() {  # LUKS jen pro swap a koren neni sifrovany -> nahodny klic pri kazdem startu (bez LUKS hlavicky)
    local id=$1
    [[ ${L[$id.keep]-0} != 1 && ${L[${L[$id.by]-x}.kind]-} == swap && -z $(ly_root_chain) ]]
}

ly_mount_ok() {  # platny pripojny bod
    local m=$1
    [[ $m == / ]] && return 0
    [[ $m =~ ^(/[A-Za-z0-9._+-]+)+$ && $m != */. && $m != */.. && $m != *"/../"* && $m != *"/./"* ]]
}

# --- Kontrola (jen cte konfiguraci; zarizeni kontroluje layout_check_devices) ----
layout_validate() {  # BOOTMODE, BOOTLOADER -> LY_ERR / LY_WARN (kody stejne jako v GUI, luxos_layout.py)
    local id k b mp t size root esp
    ly_consumers
    local -A mounts=() luksnames=() vgnames=() lvnames=() rest=() wiped=() devs=()
    for id in $(ly_ids disk); do
        [[ ${L[$id.dev]-} == /dev/* ]] || ly_err bad_dev "${L[$id.dev]-}"
        [[ ${L[$id.table]-keep} == @(new|keep) ]] || ly_err syntax "${L[$id.line]}:table"
        [[ ${L[$id.table]-keep} == new ]] && wiped[${L[$id.dev]}]=1
    done
    for id in "${L_IDS[@]}"; do
        k=${L[$id.kind]}
        case $k in
            part)
                [[ ${L[$id.disk]-} == /dev/* ]] || ly_err bad_dev "$id"
                b=$(ly_bytes "${L[$id.size]-}") || { ly_err bad_size "$id"; b=0; }
                if ((b < 0)); then
                    [[ -n ${rest[${L[$id.disk]-}]-} ]] && ly_err rest_twice "${L[$id.disk]-}"
                    rest[${L[$id.disk]-}]=1
                fi
                [[ ${L[$id.type]-linux} == @(esp|bios|linux|swap|lvm|luks|boot) ]] || ly_err bad_type "$id"
                [[ ${L[$id.name]-x} =~ ^[A-Za-z0-9._-]{1,36}$ ]] || ly_err bad_name "$id"
                ;;
            use)
                [[ ${L[$id.dev]-} == /dev/* ]] || ly_err bad_dev "$id"
                [[ -n ${devs[${L[$id.dev]-}]-} ]] && ly_err dup_dev "${L[$id.dev]}"
                devs[${L[$id.dev]-}]=1
                [[ -n ${L[$id.resize]-} ]] && { b=$(ly_bytes "${L[$id.resize]}") && ((b > 0)) || ly_err bad_size "$id"; }
                for t in "${!wiped[@]}"; do [[ ${L[$id.dev]-} == "$t"* ]] && ly_err use_on_wiped "${L[$id.dev]}"; done
                ;;
            delete)
                [[ ${L[$id.dev]-} == /dev/* ]] || ly_err bad_dev "$id"
                [[ -n ${devs[${L[$id.dev]-}]-} ]] && ly_err dup_dev "${L[$id.dev]}"
                devs[${L[$id.dev]-}]=1
                ;;
            luks)
                [[ ${L[$id.name]-} =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,40}$ ]] || ly_err bad_name "$id"
                [[ -n ${luksnames[${L[$id.name]-}]-} ]] && ly_err dup_name "${L[$id.name]}"
                luksnames[${L[$id.name]-}]=1
                [[ ${L[$id.keep]-0} == @(0|1) ]] || ly_err syntax "${L[$id.line]}:keep"
                if [[ ${L[$id.keep]-0} == 1 && ${L[${L[$id.on]-x}.kind]-} != @(use|lv) ]]; then ly_err keep_on_new "$id"; fi
                ;;
            vg)
                [[ ${L[$id.name]-} =~ ^[A-Za-z0-9_][A-Za-z0-9_+.-]{0,60}$ ]] || ly_err bad_name "$id"
                [[ -n ${vgnames[${L[$id.name]-}]-} ]] && ly_err dup_name "${L[$id.name]}"
                vgnames[${L[$id.name]-}]=1
                [[ ${L[$id.keep]-0} == 1 || -n ${L[$id.pvs]-} ]] || ly_err no_pvs "$id"
                ;;
            lv)
                [[ ${L[${L[$id.vg]-x}.kind]-} == vg ]] || ly_err ref_kind "${L[$id.vg]-}"
                [[ ${L[$id.name]-} =~ ^[A-Za-z0-9_][A-Za-z0-9_+.-]{0,60}$ ]] || ly_err bad_name "$id"
                [[ -n ${lvnames[${L[$id.vg]-}/${L[$id.name]-}]-} ]] && ly_err dup_name "${L[$id.name]}"
                lvnames[${L[$id.vg]-}/${L[$id.name]-}]=1
                if [[ ${L[$id.keep]-0} == 1 ]]; then
                    [[ ${L[${L[$id.vg]-x}.keep]-0} == 1 ]] || ly_err keep_on_new "$id"
                else
                    b=$(ly_bytes "${L[$id.size]-}") || { ly_err bad_size "$id"; b=0; }
                    if ((b < 0)); then
                        [[ -n ${rest[vg:${L[$id.vg]-}]-} ]] && ly_err rest_twice "${L[$id.vg]-}"
                        rest[vg:${L[$id.vg]-}]=1
                    fi
                fi
                ;;
            fs)
                mp=${L[$id.mount]-}
                if ! ly_mount_ok "$mp"; then ly_err bad_mount "$mp"
                elif [[ $LY_FORBIDDEN_MOUNTS == *" $mp "* ]]; then ly_err forbidden_mount "$mp"
                fi
                [[ -n ${mounts[$mp]-} ]] && ly_err dup_mount "$mp"
                mounts[$mp]=1
                t=${L[$id.type]-btrfs}
                [[ $t == @(btrfs|ext4|xfs|f2fs|vfat) ]] || ly_err bad_fstype "$mp"
                [[ $t == vfat && $mp == @(/|/home|/var|/tmp|/opt|/srv|/var/log) ]] && ly_err bad_fstype "$mp"
                [[ ${L[$id.format]-1} == @(0|1) ]] || ly_err syntax "${L[$id.line]}:format"
                [[ $mp == / && ${L[$id.format]-1} == 0 ]] && ly_err root_keep
                [[ -n ${L[$id.subvol]-} && ( ${L[$id.format]-1} == 1 || $t != btrfs ) ]] && ly_err syntax "${L[$id.line]}:subvol"
                [[ -z ${L[$id.label]-} || ${L[$id.label]} =~ ^[A-Za-z0-9._-]{1,16}$ ]] || ly_err bad_name "$id"
                ;;
            swap)
                [[ ${L[$id.format]-1} == @(0|1) ]] || ly_err syntax "${L[$id.line]}:format"
                ;;
        esac
    done
    # Kontrola, ze vsechny reference lv->vg a fs/swap na bloky sedi; objekty bez pouziti jen varovani
    for id in "${L_IDS[@]}"; do
        if ly_is_block "$id" && [[ -z ${L[$id.by]-} && ${L[$id.kind]} != use ]]; then ly_warn unused "$id"; fi
    done
    # ESP a /boot podle zavadece (systemd-boot cte jadro jen z FAT na ESP, GRUB z nesifrovaneho /boot)
    root=$(ly_fs_by_mount /)
    [[ -n $root ]] || ly_err no_root
    esp=$(ly_esp)
    for id in $(ly_ids fs); do
        if [[ ${L[$id.mount]-} == /efi && ${L[$id.type]-btrfs} != vfat ]]; then ly_err esp_fstype /efi; fi
    done
    if [[ $BOOTMODE == uefi && ${BOOTLOADER:-auto} != none ]]; then
        if [[ -z $esp ]]; then
            ly_err esp_missing
        else
            [[ ${L[${L[$esp.on]-x}.kind]-} == @(part|use) ]] || ly_err esp_not_part
            if [[ ${L[${L[$esp.on]-x}.kind]-} == part ]]; then
                [[ ${L[${L[$esp.on]}.type]-} == esp ]] || ly_err esp_type
                b=$(ly_bytes "${L[${L[$esp.on]}.size]-}" 2>/dev/null) || b=0
                ((b < 0 || b >= LY_MIN_ESP)) || ly_err esp_small
            fi
            [[ ${L[$esp.mount]} == /boot && -n $(ly_fs_by_mount /efi) ]] && ly_err dup_mount /efi
        fi
        local bootfs
        bootfs=$(ly_fs_by_mount /boot)
        if [[ -n $bootfs && $bootfs != "$esp" ]]; then
            # Oddeleny /boot vedle ESP v /efi: jadro se kopiruje na ESP (luxos-esp-sync), /boot muze byt cokoli citelneho
            [[ ${L[$esp.mount]-} == /efi ]] || ly_err boot_vfat
        fi
    elif [[ $BOOTMODE == bios && ${BOOTLOADER:-auto} != none ]]; then
        local bootfs
        bootfs=$(ly_fs_by_mount /boot)
        [[ -n $bootfs ]] || bootfs=$root
        if [[ -n $bootfs ]] && ly_encrypted "$bootfs"; then ly_err boot_encrypted; fi
        # GRUB potrebuje oddil BIOS boot; na zachovane tabulce ho muze mit uz disk (overi layout_check_devices)
        if [[ -z $(ly_bios_part) && -z $(ly_ids use) ]]; then ly_err bios_grub_missing; fi
    fi
    # Velikosti
    if [[ -n $root ]]; then
        b=$(ly_size_of "${L[$root.on]-}")
        if ((b > 0 && b < LY_MIN_ROOT)); then ly_err root_small
        elif ((b > 0 && b < LY_WARN_ROOT)); then ly_warn root_small_warn; fi
    fi
    id=$(ly_fs_by_mount /boot)
    if [[ -n $id && $id != "$esp" ]]; then
        b=$(ly_size_of "${L[$id.on]-}")
        ((b <= 0 || b >= LY_MIN_BOOT)) || ly_err boot_small
    fi
    # Sifrovani: / a /home (a swap) by mely byt sifrovane stejne
    if [[ -n $root ]]; then
        local rootenc=0
        ly_encrypted "$root" && rootenc=1
        id=$(ly_fs_by_mount /home)
        if [[ -n $id ]]; then
            local homeenc=0
            ly_encrypted "$id" && homeenc=1
            ((rootenc == homeenc)) || ly_warn enc_mismatch /home
        fi
        if ((rootenc)); then
            for id in $(ly_ids swap); do ly_encrypted "$id" || ly_warn swap_plain; done
        fi
    fi
    for id in $(ly_ids luks); do
        ly_random_swap "$id" && continue
        [[ -n $(ly_pass "$id") ]] || ly_err luks_no_pass "$id"
    done
    return 0
}

ly_size_of() {  # odhad velikosti objektu z konfigurace (bajty, 0 = nevime / rest)
    local id=$1 b
    case ${L[$id.kind]-} in
        part|lv) b=$(ly_bytes "${L[$id.size]-}" 2>/dev/null) || b=0; ((b < 0)) && b=0; echo "$b" ;;
        luks) ly_size_of "${L[$id.on]-}" ;;
        use) [[ -n ${L[$id.resize]-} ]] && ly_bytes "${L[$id.resize]}" || echo 0 ;;
        *) echo 0 ;;
    esac
}

ly_error_text() {  # citelna zprava ke kodu chyby/varovani (stejne texty jako GUI)
    local code=${1%%|*} d=${1#*|}
    case $code in
        syntax)          T "Layout line %s is not valid." "$d" ;;
        bad_id)          T "Layout line %s has an invalid id." "$d" ;;
        dup_id)          T "The id %s is used twice in the layout." "$d" ;;
        ref_missing)     T "The layout refers to %s, which does not exist." "$d" ;;
        ref_kind)        T "%s cannot be used here." "$d" ;;
        used_twice)      T "%s is used for two things at once." "$d" ;;
        bad_dev)         T "Invalid device %s." "$d" ;;
        dup_dev)         T "The device %s is listed twice." "$d" ;;
        bad_size)        T "Invalid size for %s." "$d" ;;
        rest_twice)      T "Only one volume on %s can use the remaining space." "$d" ;;
        bad_type)        T "Invalid partition type for %s." "$d" ;;
        bad_name)        T "Invalid name for %s." "$d" ;;
        dup_name)        T "The name %s is used twice." "$d" ;;
        keep_on_new)     T "%s is marked as existing but sits on a new volume." "$d" ;;
        no_pvs)          T "The volume group %s has no physical volumes." "$d" ;;
        use_on_wiped)    T "%s is on a disk that will be erased." "$d" ;;
        bad_mount)       T "%s is not a valid mount point." "$d" ;;
        forbidden_mount) T "%s cannot be a separate partition." "$d" ;;
        dup_mount)       T "The mount point %s is used twice." "$d" ;;
        bad_fstype)      T "Unsupported file system for %s." "$d" ;;
        root_keep)       T "The root file system (/) must be formatted." ;;
        no_root)         T "Choose a volume for the root file system (/)." ;;
        esp_missing)     T "An EFI system partition (FAT32, at least 300 MB) mounted at /boot or /efi is needed." ;;
        esp_not_part)    T "The EFI system partition must be a plain partition (not encrypted, not LVM)." ;;
        esp_type)        T "The partition mounted at /boot or /efi must be an EFI system partition." ;;
        esp_fstype)      T "The EFI system partition must use FAT32." ;;
        esp_small)       T "The EFI system partition must have at least 300 MB." ;;
        boot_vfat)       T "With the EFI partition at /boot, there cannot be another /boot. Mount the EFI partition at /efi instead." ;;
        boot_encrypted)  T "The boot loader (GRUB) cannot open encrypted volumes: add an unencrypted /boot partition." ;;
        bios_grub_missing) T "A BIOS boot partition (1 MB) is needed to start from this disk." ;;
        root_small)      T "The root file system (/) needs at least 8 GB." ;;
        root_small_warn) T "The root file system (/) has less than 20 GB; apps may not fit." ;;
        boot_small)      T "/boot needs at least 300 MB." ;;
        enc_mismatch)    T "/ and %s are not encrypted the same way: files in the unencrypted one are not protected." "$d" ;;
        swap_plain)      T "The swap is not encrypted although / is: memory contents can leak to the disk." ;;
        luks_no_pass)    T "Enter a passphrase for the encrypted volume %s." "$d" ;;
        unused)          T "%s is created but not used." "$d" ;;
        not_block)       T "%s does not exist." "$d" ;;
        not_gpt)         T "%s does not use a GPT partition table." "$d" ;;
        busy)            T "%s is in use (mounted). Unmount it first." "$d" ;;
        luks_not)        T "%s is not an encrypted (LUKS) volume." "$d" ;;
        luks_open)       T "The passphrase for %s is wrong." "$d" ;;
        vg_exists)       T "A volume group named %s already exists." "$d" ;;
        vg_missing)      T "The volume group %s was not found." "$d" ;;
        lv_missing)      T "The logical volume %s was not found." "$d" ;;
        name_in_use)     T "The name %s is already used by an open volume." "$d" ;;
        resize_fs)       T "%s cannot be resized (only ext4, btrfs and NTFS)." "$d" ;;
        esp_keep_fs)     T "The kept EFI system partition %s is not FAT32." "$d" ;;
        no_space)        T "There is not enough free space on %s." "$d" ;;
        vg_full)         T "The volume group %s does not have enough free space." "$d" ;;
        esp_keep_small)  T "The EFI system partition %s is smaller than 300 MB." "$d" ;;
        *)               printf '%s %s' "$code" "$d" ;;
    esac
}

# --- Kontrola zarizeni (jen cte; pred souhrnem) ----------------------------------
ly_busy() {  # zarizeni nebo neco nad nim je pripojene / aktivni swap (mimo $TARGET, ten se odpoji)
    local m
    while read -r m; do
        [[ -z $m || $m == "$TARGET" || $m == "$TARGET"/* ]] && continue
        return 0
    done < <(lsblk -nrpo MOUNTPOINTS "$1" 2>/dev/null | sed 's/\\x0a/\n/g')
    return 1
}

ly_luks_dev_of() {  # mapper otevreneho LUKS na zarizeni (nebo nic)
    lsblk -nrpo NAME,TYPE "$1" 2>/dev/null | awk '$2 == "crypt" {print $1; exit}'
}

layout_check_devices() {  # zarizeni existuji, nejsou pouzivana, existujici LUKS/VG/LV sedi
    local id dev t fst
    for id in $(ly_ids disk); do
        dev=${L[$id.dev]}
        ly_isblk "$dev" || { ly_err not_block "$dev"; continue; }
        if [[ ${L[$id.table]-keep} == new ]]; then
            ly_busy "$dev" && ly_err busy "$dev"
        fi
    done
    for id in $(ly_ids part); do
        dev=${L[$id.disk]}
        ly_isblk "$dev" || { ly_err not_block "$dev"; continue; }
        local wiped=0 d
        for d in $(ly_ids disk); do [[ ${L[$d.dev]} == "$dev" && ${L[$d.table]-keep} == new ]] && wiped=1; done
        if ((!wiped)) && [[ $(blkid -p -o value -s PTTYPE "$dev" 2>/dev/null) != gpt ]]; then ly_err not_gpt "$dev"; fi
    done
    for id in $(ly_ids delete); do
        dev=${L[$id.dev]}
        # LV ve skupine na zamcenem LUKS jeste neexistuje (overi se po odemceni)
        if ly_delete_lv "$id" && ! ly_isblk "$dev"; then continue; fi
        ly_isblk "$dev" || { ly_err not_block "$dev"; continue; }
        ly_busy "$dev" && ly_err busy "$dev"
    done
    for id in $(ly_ids use); do
        dev=${L[$id.dev]}
        ly_isblk "$dev" || { ly_err not_block "$dev"; continue; }
        fst=$(blkid -p -o value -s TYPE "$dev" 2>/dev/null || true)
        if [[ -n ${L[$id.resize]-} ]]; then
            [[ $fst == @(ext4|btrfs|ntfs) ]] || ly_err resize_fs "$dev"
            ly_busy "$dev" && ly_err busy "$dev"
        fi
        local by=${L[$id.by]-}
        case ${L[$by.kind]-} in
            luks)
                if [[ ${L[$by.keep]-0} == 1 ]]; then
                    [[ $fst == crypto_LUKS ]] || ly_err luks_not "$dev"
                else
                    ly_busy "$dev" && ly_err busy "$dev"
                fi ;;
            vg) ly_busy "$dev" && ly_err busy "$dev" ;;
            fs|swap)
                if [[ ${L[$by.format]-1} == 1 ]]; then ly_busy "$dev" && ly_err busy "$dev"; fi
                if [[ ${L[$by.kind]} == fs && $by == "$(ly_esp)" ]]; then
                    if [[ ${L[$by.format]-1} == 0 ]]; then
                        [[ $fst == vfat ]] || ly_err esp_keep_fs "$dev"
                    fi
                    t=$(blockdev --getsize64 "$dev" 2>/dev/null || echo 0)
                    ((t >= LY_MIN_ESP)) || ly_err esp_keep_small "$dev"
                fi ;;
        esac
    done
    for id in $(ly_ids luks); do
        local m=/dev/mapper/${L[$id.name]-x}
        if [[ ${L[$id.keep]-0} == 1 ]]; then
            # Existujici kontejner: heslo overit hned (nic se nemeni)
            local base=${L[${L[$id.on]}.dev]-}
            [[ ${L[${L[$id.on]}.kind]} == lv ]] && base=""
            if [[ -n $base ]] && ly_isblk "$base" && [[ -z $(ly_luks_dev_of "$base") ]]; then
                ly_pass "$id" | cryptsetup open --test-passphrase --key-file - "$base" >/dev/null 2>&1 ||
                    ly_err luks_open "$base"
            fi
        elif [[ -e $m ]]; then
            # Otevreny z predchoziho pokusu: zavre se pri priprave, jen pokud lezi na niceni urcenem zarizeni
            :
        fi
    done
    # BIOS: oddil BIOS boot (EF02) na zachovanem disku
    LY_GRUB_DISK=""
    if [[ $BOOTMODE == bios && ${BOOTLOADER:-auto} != none && -z $(ly_bios_part) ]]; then
        local d
        for id in $(ly_ids use); do
            d=$(ly_parent_disk "${L[$id.dev]}")
            if sgdisk -p "$d" 2>/dev/null | awk '$1 ~ /^[0-9]+$/ && toupper($6) == "EF02" {f = 1} END {exit !f}'; then
                LY_GRUB_DISK=$d; break
            fi
        done
        [[ -n $LY_GRUB_DISK ]] || ly_err bios_grub_missing
    fi
    # Kapacita: nove oddily na discich a LV ve skupinach (pred jakoukoli zmenou)
    ((${#LY_ERR[@]})) || ly_capacity
    for id in $(ly_ids vg); do
        if [[ ${L[$id.keep]-0} == 1 ]]; then
            vgs "${L[$id.name]}" >/dev/null 2>&1 || ly_err vg_missing "${L[$id.name]}"
        fi
    done
    for id in $(ly_ids lv); do
        if [[ ${L[$id.keep]-0} == 1 ]]; then
            lvs "${L[${L[$id.vg]}.name]}/${L[$id.name]}" >/dev/null 2>&1 || ly_err lv_missing "${L[$id.name]}"
        fi
    done
    return 0
}

# --- Kapacita (jen cte; stejny vypocet jako Layout.allocate/vg_alloc v luxos_layout.py) ----------
ly_blk_size() { blockdev --getsize64 "$1" 2>/dev/null || echo 0; }

ly_alloc_disk() {  # ly_alloc_disk DISK: simulace sgdisk (sized v poradi do nejvetsi oblasti, pak rest) -> L[id.bytes]
    local disk=$1 total first=$LY_MiB last id d wiped=0 ss num st en dev len pos a i k want
    local -a rs=() rl=() used=()
    total=$(ly_blk_size "$disk")
    ((total > 0)) || return 0
    last=$((total - 34 * 512))
    for d in $(ly_ids disk); do [[ ${L[$d.dev]} == "$disk" && ${L[$d.table]-keep} == new ]] && wiped=1; done
    if ((wiped)); then
        rs=("$first") rl=($((last - first)))
    else
        ss=$(sgdisk -p "$disk" 2>/dev/null | sed -nE 's/^Sector size \(logical[^)]*\): ([0-9]+).*/\1/p' | head -1)
        ss=${ss:-512}
        while read -r num st en; do
            dev=$(ly_part_path "$disk" "$num")
            local skip=0 rsz=""
            for id in $(ly_ids delete); do [[ ${L[$id.dev]} == "$dev" ]] && skip=1; done
            ((skip)) && continue
            for id in $(ly_ids use); do [[ ${L[$id.dev]} == "$dev" && -n ${L[$id.resize]-} ]] && rsz=$(ly_bytes "${L[$id.resize]}"); done
            len=$(((en - st + 1) * ss))
            [[ -n $rsz ]] && len=$rsz
            used+=("$((st * ss)) $len")
        done < <(sgdisk -p "$disk" 2>/dev/null | awk '$1 ~ /^[0-9]+$/ && NF >= 6 {print $1, $2, $3}')
        pos=$first
        while read -r st len; do
            [[ -n $st ]] || continue
            a=$(((pos + LY_MiB - 1) / LY_MiB * LY_MiB))
            ((st - a >= LY_MiB)) && { rs+=("$a"); rl+=($((st - a))); }
            ((st + len > pos)) && pos=$((st + len))
        done < <(printf '%s\n' "${used[@]}" | sort -n)
        a=$(((pos + LY_MiB - 1) / LY_MiB * LY_MiB))
        ((last - a >= LY_MiB)) && { rs+=("$a"); rl+=($((last - a))); }
    fi
    local pass short=0
    for pass in sized rest; do
        for id in $(ly_ids part); do
            [[ ${L[$id.disk]} == "$disk" ]] || continue
            [[ $pass == rest && ${L[$id.size]} != rest || $pass == sized && ${L[$id.size]} == rest ]] && continue
            k=-1
            for i in "${!rl[@]}"; do ((k < 0 || rl[i] > rl[k])) && k=$i; done
            if ((k < 0)); then short=1; L[$id.bytes]=0; continue; fi
            if [[ ${L[$id.size]} == rest ]]; then want=${rl[k]}
            else want=$(( $(ly_mib "$(ly_bytes "${L[$id.size]}")") * LY_MiB )); fi
            ((want > rl[k])) && { short=1; want=${rl[k]}; }
            L[$id.bytes]=$want
            rs[k]=$((rs[k] + want)) rl[k]=$((rl[k] - want))
            # oblasti mensi nez 1 MiB uz nic nepojmou
            local -a nrs=() nrl=()
            for i in "${!rl[@]}"; do ((rl[i] >= LY_MiB)) && { nrs+=("${rs[i]}"); nrl+=("${rl[i]}"); }; done
            rs=("${nrs[@]}") rl=("${nrl[@]}")
        done
    done
    ((short)) && ly_err no_space "$disk"
    return 0
}

ly_obj_size() {  # ocekavana velikost objektu v bajtech (po ly_alloc_disk/ly_alloc_vg)
    local id=$1 b
    case ${L[$id.kind]-} in
        part) echo "${L[$id.bytes]:-0}" ;;
        use)  if [[ -n ${L[$id.resize]-} ]]; then ly_bytes "${L[$id.resize]}"; else ly_blk_size "${L[$id.dev]}"; fi ;;
        luks) b=$(ly_obj_size "${L[$id.on]}"); b=$((b - LY_LUKS_HEADER)); echo $((b > 0 ? b : 0)) ;;
        lv)
            if [[ ${L[$id.keep]-0} == 1 ]]; then
                lvs --noheadings --units b --nosuffix -o lv_size "${L[${L[$id.vg]}.name]}/${L[$id.name]}" 2>/dev/null | tr -d ' ' || echo 0
            else
                ly_alloc_vg "${L[$id.vg]}"
                echo "${L[$id.bytes]:-0}"
            fi ;;
        *) echo 0 ;;
    esac
}

ly_alloc_vg() {  # ly_alloc_vg ID: misto ve skupine -> L[lv.bytes], chyba vg_full
    local id=$1 free=0 p b lv want short=0 vg dl
    [[ -n ${L[$id.alloc]-} ]] && return 0
    L[$id.alloc]=1
    vg=${L[$id.name]}
    if [[ ${L[$id.keep]-0} == 1 ]]; then
        free=$(vgs --noheadings --units b --nosuffix -o vg_free "$vg" 2>/dev/null | tr -d ' ')
        free=${free:-0}
        # mazane LV uvolni misto
        for dl in $(ly_ids delete); do
            if [[ ${L[$dl.dev]} == /dev/$vg/* ]]; then
                b=$(lvs --noheadings --units b --nosuffix -o lv_size "${L[$dl.dev]}" 2>/dev/null | tr -d ' ')
                free=$((free + ${b:-0}))
            fi
        done
    else
        for p in ${L[$id.pvs]//,/ }; do
            b=$(ly_obj_size "$p")
            b=$(((b - LY_PE_START) / LY_EXTENT * LY_EXTENT))
            ((b > 0)) && free=$((free + b))
        done
    fi
    for lv in $(ly_ids lv); do
        [[ ${L[$lv.vg]} == "$id" && ${L[$lv.keep]-0} != 1 && ${L[$lv.size]-} != rest ]] || continue
        want=$(( ($(ly_bytes "${L[$lv.size]}") + LY_EXTENT - 1) / LY_EXTENT * LY_EXTENT ))
        L[$lv.bytes]=$want
        if ((want > free)); then short=1; free=0; else free=$((free - want)); fi
    done
    for lv in $(ly_ids lv); do
        [[ ${L[$lv.vg]} == "$id" && ${L[$lv.keep]-0} != 1 && ${L[$lv.size]-} == rest ]] || continue
        ((free < LY_EXTENT)) && short=1
        L[$lv.bytes]=$free free=0
    done
    ((short)) && ly_err vg_full "$vg"
    return 0
}

ly_capacity() {
    local id d
    local -A disks=()
    for id in $(ly_ids part); do disks[${L[$id.disk]}]=1; done
    for d in "${!disks[@]}"; do ly_alloc_disk "$d"; done
    for id in $(ly_ids vg); do ly_alloc_vg "$id"; done
    return 0
}

# Co se smaze (pro souhrn a GUI)
layout_destroy_list() {
    local id by
    for id in $(ly_ids disk); do
        [[ ${L[$id.table]-keep} == new ]] && T "ERASE the whole disk %s" "${L[$id.dev]}" && echo
    done
    for id in $(ly_ids delete); do
        if ly_delete_lv "$id"; then T "DELETE logical volume %s" "${L[$id.dev]#/dev/}"; else T "DELETE partition %s" "${L[$id.dev]}"; fi
        echo
    done
    for id in $(ly_ids use); do
        [[ -n ${L[$id.resize]-} ]] && { T "Resize %s to %s" "${L[$id.dev]}" "${L[$id.resize]}"; echo; }
        by=${L[$id.by]-}
        case ${L[$by.kind]-} in
            luks) [[ ${L[$by.keep]-0} == 1 ]] || { T "ERASE %s (new encrypted volume)" "${L[$id.dev]}"; echo; } ;;
            vg)   T "ERASE %s (new LVM physical volume)" "${L[$id.dev]}"; echo ;;
            fs|swap) [[ ${L[$by.format]-1} == 1 ]] && { T "FORMAT %s" "${L[$id.dev]}"; echo; } ;;
        esac
    done
    for id in $(ly_ids lv); do
        [[ ${L[$id.keep]-0} == 1 ]] || continue
        by=${L[$id.by]-}
        case ${L[$by.kind]-} in
            luks) [[ ${L[$by.keep]-0} == 1 ]] || { T "ERASE logical volume %s" "${L[${L[$id.vg]}.name]}/${L[$id.name]}"; echo; } ;;
            fs|swap) [[ ${L[$by.format]-1} == 1 ]] && { T "FORMAT logical volume %s" "${L[${L[$id.vg]}.name]}/${L[$id.name]}"; echo; } ;;
        esac
    done
    return 0
}

layout_text() {  # citelny popis pripojeni pro souhrn: "/  btrfs  luks:cryptlvm > lvm:luxos/root"
    local id a chain
    for id in $(ly_ids fs) $(ly_ids swap); do
        chain=""
        for a in $(ly_ancestors "${L[$id.on]}"); do
            case ${L[$a.kind]} in
                luks) chain+=" LUKS(${L[$a.name]})" ;;
                lv)   chain+=" LV(${L[${L[$a.vg]}.name]}/${L[$a.name]})" ;;
                part) chain+=" ${L[$a.disk]}+${L[$a.size]}" ;;
                use)  chain+=" ${L[$a.dev]}" ;;
            esac
        done
        if [[ ${L[$id.kind]} == fs ]]; then
            printf '%-10s %-6s%s%s\n' "${L[$id.mount]}" "${L[$id.type]-btrfs}" "$chain" \
                "$([[ ${L[$id.format]-1} == 0 ]] && printf ' (%s)' "$(T "keep data")")"
        else
            printf '%-10s %-6s%s\n' swap swap "$chain"
        fi
    done
}

layout_packages() {  # baliky potrebne v cilovem systemu
    local id
    [[ -n $(ly_ids vg) ]] && echo lvm2
    for id in $(ly_ids fs); do
        case ${L[$id.type]-btrfs} in
            xfs) echo xfsprogs ;; f2fs) echo f2fs-tools ;;
        esac
    done | sort -u
}

# --- Bezpecne smazani (WIPE, wipe.sh) ----------------------------------------------
# Maze se nejnizsi uroven, na ktere LuxOS vse zaklada znovu: nove oddily, existujici oddil/LV/otevreny
# LUKS, nad kterym vznika novy LUKS/VG nebo formatovany FS/swap, a nove LV v zachovane skupine
# (to az po lvcreate, viz ly_ensure). Zachovane (format=0, keep=1) a mazane/jine oddily nikdy.
ly_wipe_on() { declare -F wipe_enabled >/dev/null && wipe_enabled; }

ly_new_consumer() {  # ly_new_consumer ID: objekt nad nim prepise data (novy LUKS/VG, formatovany FS/swap)
    case ${L[$1.kind]-} in
        luks|vg) [[ ${L[$1.keep]-0} != 1 ]] ;;
        fs|swap) [[ ${L[$1.format]-1} == 1 ]] ;;
        *) return 1 ;;
    esac
}

ly_wipe_lv_later() {  # nove LV v zachovane skupine (maze se po lvcreate)
    [[ ${L[$1.kind]-} == lv && ${L[$1.keep]-0} != 1 && ${L[${L[$1.vg]}.keep]-0} == 1 ]]
}

layout_wipe_ids() {  # objekty ke smazani v kroku mazani (bez ly_wipe_lv_later)
    local id
    for id in $(ly_ids part); do echo "$id"; done
    for id in $(ly_ids use) $(ly_ids lv) $(ly_ids luks); do
        [[ ${L[$id.kind]} == use || ${L[$id.keep]-0} == 1 ]] || continue
        ly_new_consumer "${L[$id.by]-}" && echo "$id"
    done
    return 0
}

layout_wipe_bytes() {  # odhad velikosti mazane oblasti (po ly_capacity; pro souhrn)
    local id total=0
    for id in $(layout_wipe_ids) $(for id in $(ly_ids lv); do ly_wipe_lv_later "$id" && echo "$id"; done); do
        total=$((total + $(ly_obj_size "$id")))
    done
    echo "$total"
}

ly_wipe_step() {  # krok mazani: po rozdeleni disku, pred LUKS/LVM/mkfs
    local id devs=()
    ly_wipe_on || return 0
    step "$(T "Erasing the space for LuxOS")"
    for id in $(layout_wipe_ids); do
        [[ ${L[$id.kind]} == @(lv|luks) ]] && ly_ensure "$id"   # zachovane: jen cesta / odemceni
        [[ -n ${L[$id.dev]-} ]] || fail "$(T "Partitions were not created correctly")"
        devs+=("${L[$id.dev]}")
    done
    wipe_devices "${devs[@]}"
}

layout_steps() {  # pocet kroku pripravy disku (pro @@STEP celkem)
    local n=2
    ly_wipe_on && n=$((n + 1))
    [[ -n $(for id in $(ly_ids luks); do [[ ${L[$id.keep]-0} == 1 ]] || ly_random_swap "$id" || echo x; done) ]] && n=$((n + 1))
    [[ -n $(ly_ids vg) ]] && n=$((n + 1))
    echo "$n"
}

# --- Provedeni -------------------------------------------------------------------
ly_part_path() {  # ly_part_path /dev/disk N
    local p
    p=$(lsblk -lnpo NAME,PARTN "$1" 2>/dev/null | awk -v n="$2" '$2 == n {print $1}')
    if [[ -z $p ]]; then
        if [[ $1 == *[0-9] ]]; then p=$1p$2; else p=$1$2; fi
    fi
    printf '%s\n' "$p"
}

ly_partnum() {  # cislo oddilu z cesty (sysfs, jinak z nazvu)
    local n
    n=$(cat "/sys/class/block/${1##*/}/partition" 2>/dev/null || true)
    [[ -n $n ]] || n=$(lsblk -no PARTN "$1" 2>/dev/null | tr -d ' ')
    [[ -n $n ]] || n=$(sed -E 's/.*[^0-9]([0-9]+)$/\1/' <<<"$1")
    echo "$n"
}

ly_parent_disk() {  # disk, na kterem lezi oddil
    local p
    p=$(lsblk -no PKNAME "$1" 2>/dev/null | head -1)
    if [[ -n $p ]]; then echo "/dev/$p"; else sed -E 's/p?[0-9]+$//' <<<"$1"; fi
}

ly_release() {  # ly_release DEV: zavrit LUKS/LVM/swap nad zarizenim, ktere se bude prepisovat
    local dev=$1 name type
    ly_isblk "$dev" || return 0
    while read -r name type; do
        [[ $name == "$dev" ]] && continue
        case $type in
            crypt) run cryptsetup close "$name" || true ;;
            lvm)
                local vg
                vg=$(lvs --noheadings -o vg_name "$name" 2>/dev/null | tr -d ' ' || true)
                [[ -n $vg ]] && { run vgchange -an "$vg" || true; } ;;
        esac
    done < <(lsblk -nrpo NAME,TYPE "$dev" 2>/dev/null | tail -n +2 | tac)   # 1. radek = zarizeni samo
    swapoff "$dev" 2>/dev/null || true
    return 0
}

ly_settle() {  # novy stav tabulky oddilu jadru (ostatni oddily mohou byt pouzivane)
    run partprobe "$1" || run partx -u "$1" || true
    run udevadm settle || true
}

ly_wait_dev() {  # ly_wait_dev DISK N -> cesta noveho oddilu
    local i p
    for i in 1 2 3 4 5; do
        p=$(ly_part_path "$1" "$2")
        ly_isblk "$p" && { echo "$p"; return 0; }
        run partx -a --nr "$2" "$1" || true
        run udevadm settle || true
        sleep 1
    done
    return 1
}

ly_gpt_type() {  # typ GPT podle pouziti oddilu
    local id=$1 by t=${L[$1.type]-}
    case $t in
        esp) echo ef00; return ;; bios) echo ef02; return ;; swap) echo 8200; return ;;
        lvm) echo 8e00; return ;; luks) echo 8309; return ;; boot) echo ea00; return ;;
    esac
    by=${L[$id.by]-}
    case ${L[$by.kind]-} in
        luks) echo 8309 ;;
        vg) echo 8e00 ;;
        swap) echo 8200 ;;
        fs)
            if [[ $by == "$(ly_esp)" ]]; then echo ef00
            elif [[ ${L[$by.mount]} == / ]]; then echo 8304
            else echo 8300; fi ;;
        *) echo 8300 ;;
    esac
}

ly_resize_part() {  # ly_resize_part DEV BAJTU: oddil se stejnym zacatkem, typem, PARTUUID a nazvem
    local dev=$1 bytes=$2 disk n ss start guid puuid name end
    disk=$(ly_parent_disk "$dev"); n=$(ly_partnum "$dev")
    ss=$(sgdisk -p "$disk" | sed -nE 's/^Sector size \(logical[^)]*\): ([0-9]+).*/\1/p' | head -1)
    local info; info=$(sgdisk -i "$n" "$disk")
    start=$(sed -nE 's/^First sector: ([0-9]+).*/\1/p' <<<"$info")
    guid=$(sed -nE 's/^Partition GUID code: ([0-9A-Fa-f-]+).*/\1/p' <<<"$info")
    puuid=$(sed -nE 's/^Partition unique GUID: ([0-9A-Fa-f-]+).*/\1/p' <<<"$info")
    name=$(sed -nE "s/^Partition name: '(.*)'$/\1/p" <<<"$info")
    [[ $start =~ ^[0-9]+$ && -n $guid && -n $puuid && $ss =~ ^[0-9]+$ ]] || fail "$(T "Could not read partition %s." "$dev")"
    end=$((start + bytes / ss - 1))
    run sgdisk -d "$n" -n "$n:$start:$end" -t "$n:$guid" -u "$n:$puuid" ${name:+-c "$n:$name"} "$disk"
    run partx -u --nr "$n" "$disk" || ly_settle "$disk"
}

ly_resize() {  # ly_resize ID SMER(shrink|grow): zmenseni = nejdriv FS, zvetseni = nejdriv oddil
    local id=$1 dir=$2 dev=${L[$1.dev]} bytes cur fst mnt
    bytes=$(ly_bytes "${L[$id.resize]}")
    cur=$(blockdev --getsize64 "$dev")
    [[ $dir == shrink ]] && ((bytes >= cur)) && return 0
    [[ $dir == grow ]] && ((bytes <= cur)) && return 0
    fst=$(blkid -p -o value -s TYPE "$dev")
    info "$(T "Resizing %s to %s" "$dev" "${L[$id.resize]}")"
    if [[ $dir == grow ]]; then ly_resize_part "$dev" "$bytes"; fi
    case $fst in
        ext4)
            run e2fsck -f -y "$dev" || [[ $? -le 1 ]] || fail "$(T "The file system on %s has errors." "$dev")"
            if [[ $dir == shrink ]]; then run resize2fs "$dev" "$((bytes / 1024))K"; else run resize2fs "$dev"; fi ;;
        ntfs)
            if [[ $dir == shrink ]]; then
                run ntfsresize --no-action --force --size "$bytes" "$dev" || fail "$(T "%s cannot be shrunk that much." "$dev")"
                printf 'y\n' | run ntfsresize --force --size "$bytes" "$dev"
            else
                printf 'y\n' | run ntfsresize --force "$dev"
            fi ;;
        btrfs)
            mnt=$(mktemp -d /run/luxos-resize.XXXXXX)
            run mount -t btrfs "$dev" "$mnt"
            if [[ $dir == shrink ]]; then run btrfs filesystem resize "$bytes" "$mnt"; else run btrfs filesystem resize max "$mnt"; fi
            run umount "$mnt"; rmdir "$mnt" ;;
        *) fail "$(ly_error_text "resize_fs|$dev")" ;;
    esac
    if [[ $dir == shrink ]]; then ly_resize_part "$dev" "$bytes"; fi
}

ly_dev() { echo "${L[$1.dev]-}"; }

ly_lv_path() { local v=${1//-/--} l=${2//-/--}; echo "/dev/mapper/$v-$l"; }

ly_ensure() {  # ly_ensure ID: zalozi objekt (a vse pod nim), nastavi L[id.dev]
    local id=$1 base p pv pvs=() pass
    [[ -n ${L[$id.done]-} ]] && return 0
    L[$id.done]=1
    case ${L[$id.kind]} in
        part|use) ;;   # oddily zalozila ly_partitions
        luks)
            ly_ensure "${L[$id.on]}"
            base=$(ly_dev "${L[$id.on]}")
            if ly_random_swap "$id"; then
                # Bez LUKS: swap s nahodnym klicem pri kazdem startu (crypttab), ted jen smazat podpisy
                run wipefs -af "$base"
                L[$id.dev]=""
                L[$id.random]=1
                return 0
            fi
            pass=$(ly_pass "$id")
            if [[ ${L[$id.keep]-0} == 1 ]]; then
                p=$(ly_luks_dev_of "$base")
                if [[ -z $p ]]; then
                    printf '%s' "$pass" | run cryptsetup open --allow-discards --key-file - "$base" "${L[$id.name]}" ||
                        fail "$(ly_error_text "luks_open|$base")"
                    p=/dev/mapper/${L[$id.name]}
                    LY_OPENED+=("luks ${L[$id.name]}")
                fi
            else
                [[ -e /dev/mapper/${L[$id.name]} ]] && fail "$(ly_error_text "name_in_use|${L[$id.name]}")"
                ly_release "$base"
                run wipefs -af "$base"
                info "$(T "Encrypting %s" "$base")"
                printf '%s' "$pass" | run cryptsetup luksFormat --type luks2 --batch-mode --offset "$LY_LUKS_OFFSET" --key-file - "$base"
                printf '%s' "$pass" | run cryptsetup open --allow-discards --perf-no_read_workqueue \
                    --perf-no_write_workqueue --persistent --key-file - "$base" "${L[$id.name]}"
                p=/dev/mapper/${L[$id.name]}
                LY_OPENED+=("luks ${L[$id.name]}")
            fi
            L[$id.dev]=$p
            L[$id.uuid]=$(blkid -s UUID -o value "$base")
            ;;
        vg)
            if [[ ${L[$id.keep]-0} == 1 ]]; then
                run vgchange -ay "${L[$id.name]}" || fail "$(ly_error_text "vg_missing|${L[$id.name]}")"
            else
                vgs "${L[$id.name]}" >/dev/null 2>&1 && fail "$(ly_error_text "vg_exists|${L[$id.name]}")"
                for p in ${L[$id.pvs]//,/ }; do
                    ly_ensure "$p"
                    pv=$(ly_dev "$p")
                    ly_release "$pv"
                    run wipefs -af "$pv"
                    run pvcreate -ff -y "$pv"
                    pvs+=("$pv")
                done
                info "$(T "Creating volume group %s" "${L[$id.name]}")"
                run vgcreate -y "${L[$id.name]}" "${pvs[@]}"
            fi
            LY_OPENED+=("vg ${L[$id.name]}")
            L[$id.dev]=/dev/${L[$id.name]}
            ;;
        lv)
            local vg=${L[$id.vg]} vgname other
            ly_ensure "$vg"
            vgname=${L[$vg.name]}
            if [[ ${L[$id.keep]-0} != 1 ]]; then
                if [[ ${L[$id.size]} == rest ]]; then
                    # Zbytek az po vsech LV s pevnou velikosti ve stejne skupine
                    for other in $(ly_ids lv); do
                        [[ $other != "$id" && ${L[$other.vg]} == "$vg" && ${L[$other.size]-} != rest ]] && ly_ensure "$other"
                    done
                    run lvcreate -y -Wy -Zy -l 100%FREE -n "${L[$id.name]}" "$vgname"
                else
                    run lvcreate -y -Wy -Zy -L "$(ly_mib "$(ly_bytes "${L[$id.size]}")")m" -n "${L[$id.name]}" "$vgname"
                fi
            fi
            L[$id.dev]=$(ly_lv_path "$vgname" "${L[$id.name]}")
            ly_isblk "${L[$id.dev]}" || run udevadm settle || true
            if ly_wipe_on && ly_wipe_lv_later "$id"; then
                wipe_devices "${L[$id.dev]}"
            fi
            ;;
    esac
}

ly_partitions() {  # tabulky oddilu: zmenseni, mazani, zvetseni, nove oddily (v tomto poradi)
    local id dev disk n before after
    local -A touched=()
    # Smazani celeho disku
    for id in $(ly_ids disk); do
        [[ ${L[$id.table]-keep} == new ]] || continue
        dev=${L[$id.dev]}
        ly_release "$dev"
        local p
        for p in $(lsblk -nrpo NAME,TYPE "$dev" | awk '$2 == "part" {print $1}'); do ly_release "$p"; done
        run wipefs -af "$dev"
        run sgdisk --zap-all "$dev"
        run sgdisk -o "$dev"
        ly_settle "$dev"
    done
    for id in $(ly_ids use); do [[ -n ${L[$id.resize]-} ]] && ly_resize "$id" shrink; done
    for id in $(ly_ids delete); do
        ly_delete_lv "$id" && continue   # LV az v layout_apply
        dev=${L[$id.dev]}
        disk=$(ly_parent_disk "$dev"); n=$(ly_partnum "$dev")
        ly_release "$dev"
        run wipefs -af "$dev" || true
        run sgdisk -d "$n" "$disk"
        run partx -d --nr "$n" "$disk" || true
        touched[$disk]=1
    done
    for id in $(ly_ids use); do [[ -n ${L[$id.resize]-} ]] && ly_resize "$id" grow; done
    # Nove oddily: pevne velikosti v poradi, "rest" na konci daneho disku
    local pass
    for pass in sized rest; do
        for id in $(ly_ids part); do
            [[ $pass == rest && ${L[$id.size]} != rest || $pass == sized && ${L[$id.size]} == rest ]] && continue
            disk=${L[$id.disk]}
            n=$(ly_free_partnum "$disk") || fail "$(T "The partition table on %s is full." "$disk")"
            before=$(sgdisk -p "$disk" | awk '$1 ~ /^[0-9]+$/ && NF >= 6')
            local end=0 name=${L[$id.name]-}
            [[ ${L[$id.size]} == rest ]] || end="+$(ly_mib "$(ly_bytes "${L[$id.size]}")")M"
            [[ -n $name ]] || case $(ly_gpt_type "$id") in
                ef00) name=EFI ;; ef02) name=BIOS ;; ea00) name=boot ;; *) name=LuxOS ;;
            esac
            run sgdisk -n "$n:0:$end" -t "$n:$(ly_gpt_type "$id")" -c "$n:$name" "$disk" ||
                fail "$(T "Not enough free space on %s." "$disk")"
            # Kontrola: ostatni oddily beze zmeny
            after=$(sgdisk -p "$disk" | awk -v n="$n" '$1 ~ /^[0-9]+$/ && NF >= 6 && $1 != n')
            [[ $before == "$after" ]] || fail "$(T "Unexpected change of existing partitions on %s - stopping." "$disk")"
            L[$id.num]=$n
            touched[$disk]=1
        done
    done
    for disk in "${!touched[@]}"; do ly_settle "$disk"; done
    for id in $(ly_ids part); do
        L[$id.dev]=$(ly_wait_dev "${L[$id.disk]}" "${L[$id.num]}") || fail "$(T "Partitions were not created correctly")"
        run wipefs -af "${L[$id.dev]}" || true
    done
}

ly_free_partnum() {
    local used n
    used=" $(sgdisk -p "$1" | awk '$1 ~ /^[0-9]+$/ && NF >= 6 {printf "%s ", $1}')"
    for ((n = 1; n <= 128; n++)); do
        [[ $used == *" $n "* ]] || { echo "$n"; return 0; }
    done
    return 1
}

ly_mkfs() {  # ly_mkfs ID(fs) DEV
    local id=$1 dev=$2 t=${L[$1.type]-btrfs} label=${L[$1.label]-}
    if [[ -z $label ]]; then
        case ${L[$id.mount]} in /) label=LuxOS ;; /boot|/efi) label=EFI ;; *) label=${L[$id.mount]##*/} ;; esac
        [[ ${L[$id.mount]} == /boot && $t != vfat ]] && label=boot
        label=${label:0:11}
    fi
    ly_release "$dev"
    case $t in
        btrfs) run mkfs.btrfs -f -L "$label" "$dev" ;;
        ext4)  run mkfs.ext4 -F -L "$label" "$dev" ;;
        xfs)   run mkfs.xfs -f -L "${label:0:12}" "$dev" ;;
        f2fs)  run mkfs.f2fs -f -l "$label" -O extra_attr,inode_checksum,sb_checksum "$dev" ;;
        vfat)  run mkfs.fat -F32 -n "${label^^}" "$dev" ;;
    esac
}

ly_mount_opts() {  # volby pripojeni podle FS a mista
    local id=$1 o=""
    case ${L[$id.type]-btrfs} in
        btrfs) o=noatime,compress=zstd:1 ;;
        ext4|xfs|f2fs) o=noatime ;;
        vfat) o=fmask=0077,dmask=0077 ;;
    esac
    [[ ${L[$id.mount]} == /tmp ]] && o+=,nosuid,nodev
    [[ -n ${L[$id.subvol]-} ]] && o+=,subvol=${L[$id.subvol]}
    echo "${o#,}"
}

layout_apply() {  # vse zalozit a pripojit do $TARGET (az po potvrzeni souhrnu)
    local id dev mp opts sv root
    step "$(T "Preparing disks")"
    swapoff -a 2>/dev/null || true
    umount -R "$TARGET" 2>/dev/null || true
    ly_partitions

    # Existujici LUKS na oddilech odemknout a existujici VG aktivovat, pak smazat vybrane LV
    for id in $(ly_ids luks); do
        [[ ${L[$id.keep]-0} == 1 && ${L[${L[$id.on]}.kind]} == use ]] && ly_ensure "$id"
    done
    for id in $(ly_ids vg); do [[ ${L[$id.keep]-0} == 1 ]] && ly_ensure "$id"; done
    for id in $(ly_ids delete); do
        ly_delete_lv "$id" || continue
        ly_isblk "${L[$id.dev]}" || fail "$(ly_error_text "lv_missing|${L[$id.dev]}")"
        ly_busy "${L[$id.dev]}" && fail "$(ly_error_text "busy|${L[$id.dev]}")"
        ly_release "${L[$id.dev]}"
        run lvremove -y "${L[$id.dev]}"
    done
    ly_wipe_step

    # LUKS, LVM (v poradi zavislosti; ly_ensure zalozi i vse pod objektem)
    local nluks=0
    for id in $(ly_ids luks); do [[ ${L[$id.keep]-0} == 1 ]] || ly_random_swap "$id" || nluks=1; done
    if ((nluks)); then
        step "$(T "Encrypting volumes")"
        for id in $(ly_ids luks); do ly_random_swap "$id" || ly_ensure "$id"; done
    fi
    if [[ -n $(ly_ids vg) ]]; then
        step "$(T "Setting up LVM")"
        for id in $(ly_ids lv); do ly_ensure "$id"; done
    fi
    for id in $(ly_ids fs) $(ly_ids swap); do ly_ensure "${L[$id.on]}"; done

    step "$(T "Creating file systems")"
    for id in $(ly_ids fs); do
        dev=$(ly_dev "${L[$id.on]}")
        ly_isblk "$dev" || fail "$(ly_error_text "not_block|$dev")"
        L[$id.dev]=$dev
        if [[ ${L[$id.format]-1} == 1 ]]; then
            info "$(T "Formatting %s as %s (%s)" "$dev" "${L[$id.type]-btrfs}" "${L[$id.mount]}")"
            ly_mkfs "$id" "$dev"
        fi
    done
    for id in $(ly_ids swap); do
        local on=${L[$id.on]}
        [[ ${L[$on.random]-0} == 1 ]] && continue
        dev=$(ly_dev "$on")
        L[$id.dev]=$dev
        [[ ${L[$id.format]-1} == 1 ]] && { ly_release "$dev"; run mkswap -L swap "$dev"; }
    done

    # Pripojeni: / nejdriv, pak podle hloubky cesty
    root=$(ly_fs_by_mount /)
    dev=${L[$root.dev]}
    if [[ ${L[$root.type]-btrfs} == btrfs ]]; then
        # Jako automaticka instalace: subvolumy @ (+ @home, @log, @cache, pokud nejsou samostatne)
        run mount "$dev" "$TARGET"
        local -a svs=(@)
        [[ -n $(ly_fs_by_mount /home) ]] || svs+=(@home)
        [[ -n $(ly_fs_by_mount /var)$(ly_fs_by_mount /var/log) ]] || svs+=(@log)
        [[ -n $(ly_fs_by_mount /var) ]] || svs+=(@cache)
        for sv in "${svs[@]}"; do run btrfs subvolume create "$TARGET/$sv"; done
        run umount "$TARGET"
        run mount -o "$(ly_mount_opts "$root"),subvol=@" "$dev" "$TARGET"
        L[$root.rootsubvol]=@
        for sv in "${svs[@]:1}"; do
            case $sv in @home) mp=home ;; @log) mp=var/log ;; @cache) mp=var/cache ;; esac
            mkdir -p "$TARGET/$mp"
            run mount -o "$(ly_mount_opts "$root"),subvol=$sv" "$dev" "$TARGET/$mp"
        done
    else
        run mount -o "$(ly_mount_opts "$root")" "$dev" "$TARGET"
    fi
    while read -r _ id; do
        [[ $id == "$root" ]] && continue
        mp=${L[$id.mount]}
        mkdir -p "$TARGET$mp"
        run mount -o "$(ly_mount_opts "$id")" "${L[$id.dev]}" "$TARGET$mp"
    done < <(for id in $(ly_ids fs); do
                 mp=${L[$id.mount]}; s=${mp//[^\/]/}
                 printf '%s %s\n' "${#s}" "$id"
             done | sort -n -s)
    [[ -d $TARGET/tmp ]] && chmod 1777 "$TARGET/tmp"
    ROOTDEV=$dev
    GRUB_DISK=""
    p=$(ly_bios_part)
    if [[ -n $p ]]; then GRUB_DISK=${L[$p.disk]}; else GRUB_DISK=${LY_GRUB_DISK-}; fi
    id=$(ly_esp)
    if [[ -n $id ]]; then
        BOOTPART=${L[$id.dev]}
        ESP_PART=${L[$id.dev]}
        ESP_MOUNT=${L[$id.mount]}
        ESP_KEEP=$((1 - ${L[$id.format]-1}))
    fi
    return 0
}

# --- Konfigurace ciloveho systemu --------------------------------------------------
layout_crypt_base() {  # identifikace podkladu LUKS pro crypttab: UUID=… (LUKS) nebo stala cesta (nahodny swap)
    local id=$1 on=${L[$1.on]} p
    if [[ ${L[$id.random]-0} == 1 ]]; then
        case ${L[$on.kind]} in
            lv) echo "/dev/${L[${L[$on.vg]}.name]}/${L[$on.name]}" ;;
            *) p=$(blkid -s PARTUUID -o value "$(ly_dev "$on")" 2>/dev/null || true)
               if [[ -n $p ]]; then echo "PARTUUID=$p"; else ly_dev "$on"; fi ;;
        esac
    else
        echo "UUID=${L[$id.uuid]}"
    fi
}

layout_write_crypt() {  # /etc/crypttab, /etc/crypttab.initramfs, klice v /etc/cryptsetup-keys.d
    local id chain keydir="$TARGET/etc/cryptsetup-keys.d" key ct="" cti=""
    chain=" $(ly_root_chain | tr '\n' ' ') "
    for id in $(ly_ids luks); do
        if [[ $chain == *" $id "* ]]; then
            # Odemyka initramfs (sd-encrypt): jedno heslo, systemd ho zkusi i pro dalsi svazky
            cti+="${L[$id.name]} $(layout_crypt_base "$id") none luks,discard"$'\n'
        elif [[ ${L[$id.random]-0} == 1 ]]; then
            ct+="${L[$id.name]} $(layout_crypt_base "$id") /dev/urandom swap,cipher=aes-xts-plain64,size=512,sector-size=4096"$'\n'
        elif [[ $chain != "  " ]]; then
            # Koren je sifrovany: ostatni svazky odemkne klic ulozeny na sifrovanem / (bez dalsiho dotazu na heslo)
            install -d -m700 "$keydir"
            key="$keydir/${L[$id.name]}.key"
            (umask 077; head -c 4096 /dev/urandom >"$key")
            chmod 0400 "$key"
            ly_pass "$id" | run cryptsetup luksAddKey --batch-mode --pbkdf pbkdf2 --pbkdf-force-iterations 1000 \
                --key-file - "$(ly_dev "${L[$id.on]}")" "$key"
            ct+="${L[$id.name]} $(layout_crypt_base "$id") /etc/cryptsetup-keys.d/${L[$id.name]}.key luks,discard"$'\n'
        else
            # Nesifrovany koren: heslo se zada pri startu (systemd ho zkusi pro vsechny svazky)
            ct+="${L[$id.name]} $(layout_crypt_base "$id") none luks,discard"$'\n'
        fi
    done
    if [[ -n $ct ]]; then
        printf '# LuxOS - sifrovane svazky odemykane po startu jadra (name device key options)\n%s' "$ct" \
            >>"$TARGET/etc/crypttab"
    fi
    if [[ -n $cti ]]; then
        install -Dm600 /dev/stdin "$TARGET/etc/crypttab.initramfs" <<<"# LuxOS - svazky pro pripojeni / (initramfs, sd-encrypt)
${cti%$'\n'}"
    fi
    return 0
}

layout_fstab_swap() {  # radky swapu do fstab (genfstab je nevidi, swap se pri instalaci nezapina)
    local id on
    for id in $(ly_ids swap); do
        on=${L[$id.on]}
        if [[ ${L[$on.random]-0} == 1 ]]; then
            printf '/dev/mapper/%s\tnone\tswap\tdefaults\t0 0\n' "${L[$on.name]}"
        else
            printf 'UUID=%s\tnone\tswap\tdefaults\t0 0\n' "$(blkid -s UUID -o value "${L[$id.dev]}")"
        fi
    done
}

layout_cmdline() {  # root=… a rd.luks.* pro zavadec
    local root id out
    root=$(ly_fs_by_mount /)
    out="root=UUID=$(blkid -s UUID -o value "${L[$root.dev]}")"
    [[ -n ${L[$root.rootsubvol]-} ]] && out+=" rootflags=subvol=${L[$root.rootsubvol]}"
    local chain luks=""
    chain=$(ly_root_chain)
    for id in $chain; do luks+="rd.luks.name=${L[$id.uuid]}=${L[$id.name]} "; done
    [[ -n $chain ]] && luks+="rd.luks.options=discard "
    echo "$luks$out"
}

layout_hooks() {  # ENCRYPT_HOOK / LVM_HOOK pro mkinitcpio (jen co je potreba pro /)
    local root a enc=0 lvm=0
    root=$(ly_fs_by_mount /)
    for a in $(ly_ancestors "$root"); do
        [[ ${L[$a.kind]} == luks ]] && enc=1
        [[ ${L[$a.kind]} == @(lv|vg) ]] && lvm=1
    done
    echo "ENCRYPT_HOOK=$enc LVM_HOOK=$lvm"
}

layout_teardown() {  # po instalaci: zavrit LVM a LUKS v opacnem poradi
    local i e
    for ((i = ${#LY_OPENED[@]} - 1; i >= 0; i--)); do
        e=${LY_OPENED[i]}
        case $e in
            "luks "*) cryptsetup close "${e#luks }" 2>/dev/null || true ;;
            "vg "*) vgchange -an "${e#vg }" >/dev/null 2>&1 || true ;;
        esac
    done
    return 0
}
