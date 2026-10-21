# LuxOS installer - nahrada diskovych prikazu pro testy layout.sh bez roota (source z test-layout.sh)
#
# Stav je v $MOCK: disks/<jmeno>.size (sektory 512 B), disks/<jmeno>.tbl ("cislo zacatek konec kod jmeno"),
# fs/<zarizeni> (typ FS), luks/<zarizeni>, open/<mapper> (podklad), lv/<vg>-<lv>, vg/<vg> (PV).
# Kazdy volany prikaz se zapise do $MOCK/cmds (bez hesel - ta jdou na stdin).

mock_init() {  # mock_init "vda:64G" "sda:500G" ...
    MOCK=$(mktemp -d "${TMPDIR:-/tmp}/luxos-mock.XXXXXX")
    mkdir -p "$MOCK"/{disks,fs,luks,open,lv,vg,keys}
    : >"$MOCK/cmds"
    local d name size
    for d in "$@"; do
        name=${d%%:*} size=${d#*:}
        size=$(ly_bytes "$size")
        echo $((size / 512)) >"$MOCK/disks/$name.size"
        : >"$MOCK/disks/$name.tbl"
    done
}

mock_log() { printf '%s\n' "$*" >>"$MOCK/cmds"; }
mk_key() { local k=${1#/dev/}; echo "${k//\//_}"; }

# --- diskove nastroje -------------------------------------------------------------
mock_disk_of() {  # /dev/vda2 -> vda 2 ; /dev/nvme0n1p3 -> nvme0n1 3
    local n=${1#/dev/}
    if [[ $n =~ ^(nvme[0-9]+n[0-9]+|mmcblk[0-9]+|loop[0-9]+)p([0-9]+)$ ]]; then echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]}"
    elif [[ $n =~ ^([a-z]+)([0-9]+)$ ]]; then echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]}"
    fi
}

mock_partpath() { if [[ $1 == *[0-9] ]]; then echo "/dev/$1p$2"; else echo "/dev/$1$2"; fi; }

sgdisk() {
    mock_log "sgdisk $*"
    local disk=${!#} name tbl sz a n s e code pname
    name=${disk#/dev/}
    tbl=$MOCK/disks/$name.tbl
    [[ -e $tbl ]] || return 2
    sz=$(<"$MOCK/disks/$name.size")
    local first=2048 last=$((sz - 34))
    local -a args=("${@:1:$#-1}")
    local i=0
    while ((i < ${#args[@]})); do
        a=${args[i]}
        case $a in
            -o|--zap-all) : >"$tbl" ;;
            -p)
                echo "Disk $disk: $sz sectors"
                echo "Sector size (logical/physical): 512/512 bytes"
                echo "Number  Start (sector)    End (sector)  Size       Code  Name"
                sort -n "$tbl" | while read -r n s e code pname; do
                    printf '%4s %15s %15s   %s MiB  %s  %s\n' "$n" "$s" "$e" $(((e - s + 1) / 2048)) "$code" "$pname"
                done ;;
            -i)
                i=$((i + 1)); n=${args[i]}
                read -r _ s e code pname < <(awk -v n="$n" '$1 == n' "$tbl")
                [[ -n $s ]] || return 4
                echo "Partition GUID code: 00000000-0000-0000-0000-00000000$code (type)"
                printf 'Partition unique GUID: 11111111-2222-3333-4444-%012x\n' "$n"
                echo "First sector: $s (at x)"
                echo "Last sector: $e (at x)"
                echo "Partition name: '$pname'" ;;
            -d)
                i=$((i + 1)); n=${args[i]}
                grep -q "^$n " "$tbl" || return 4
                awk -v n="$n" '$1 != n' "$tbl" >"$tbl.new"; mv "$tbl.new" "$tbl" ;;
            -n)
                i=$((i + 1)); IFS=: read -r n s e <<<"${args[i]}"
                grep -q "^$n " "$tbl" && return 4
                # nejvetsi volny blok
                local bs=0 be=-1 pos=$first ps pe
                while read -r ps pe; do
                    if ((ps - pos > be - bs + 1)); then bs=$pos be=$((ps - 1)); fi
                    pos=$((pe + 1))
                done < <(awk '{print $2, $3}' "$tbl" | sort -n)
                if ((last - pos + 1 > be - bs + 1)); then bs=$pos be=$last; fi
                bs=$(((bs + 2047) / 2048 * 2048))
                [[ $s == 0 ]] && s=$bs
                if [[ $e == 0 ]]; then e=$be
                elif [[ $e == +*M ]]; then e=$((s + ${e//[+M]/} * 2048 - 1))
                fi
                ((e > s && e <= last && s >= first)) || return 4
                # prekryv s jinym oddilem
                if awk -v s="$s" -v e="$e" '!(e < $2 || s > $3) {f = 1} END {exit !f}' "$tbl"; then return 4; fi
                echo "$n $s $e 8300 LuxOS" >>"$tbl" ;;
            -u) i=$((i + 1)) ;;
            -t|-c)
                i=$((i + 1)); IFS=: read -r n code <<<"${args[i]}"
                local col=4; [[ $a == -c ]] && col=5
                awk -v n="$n" -v c="$col" -v v="${code// /_}" '$1 == n {$c = v} {print}' "$tbl" >"$tbl.new"
                mv "$tbl.new" "$tbl" ;;
        esac
        i=$((i + 1))
    done
    return 0
}

lsblk() {
    local opts=$* dev=${!#} name
    name=${dev#/dev/}
    case $opts in
        *NAME,PARTN*)
            [[ -e $MOCK/disks/$name.tbl ]] || return 0
            awk '{print $1}' "$MOCK/disks/$name.tbl" | while read -r n; do echo "$(mock_partpath "$name" "$n") $n"; done ;;
        *NAME,TYPE*)
            if [[ -e $MOCK/disks/$name.tbl ]]; then
                echo "$dev disk"
                awk '{print $1}' "$MOCK/disks/$name.tbl" | while read -r n; do echo "$(mock_partpath "$name" "$n") part"; done
            else
                echo "$dev part"
            fi ;;
        *PKNAME*) read -r name _ <<<"$(mock_disk_of "$dev")"; echo "$name" ;;
        *PARTN*) read -r _ name <<<"$(mock_disk_of "$dev")"; echo "$name" ;;
        *MOUNTPOINTS*) [[ -e $MOCK/busy/$(mk_key "$dev") ]] && echo /mnt/busy; return 0 ;;
    esac
    return 0
}

ly_isblk() {  # existuje v emulaci?
    local d=$1 k
    [[ $d == /dev/* ]] || return 1
    k=${d#/dev/}
    [[ -e $MOCK/disks/$k.tbl ]] && return 0
    if [[ $d == /dev/mapper/* ]]; then
        [[ -e $MOCK/open/${d#/dev/mapper/} || -e $MOCK/lv/${d#/dev/mapper/} ]] && return 0
        return 1
    fi
    local dn n
    read -r dn n <<<"$(mock_disk_of "$d")"
    if [[ -n $dn && -e $MOCK/disks/$dn.tbl ]]; then grep -q "^$n " "$MOCK/disks/$dn.tbl"; return; fi
    [[ -e $MOCK/lv/${k//\//-} ]]   # /dev/vg/lv
}

blkid() {
    local dev=${!#} what="" k
    local -a a=("$@")
    for ((i = 0; i < ${#a[@]}; i++)); do [[ ${a[i]} == -s ]] && what=${a[i + 1]}; done
    k=$(mk_key "$dev")
    case $what in
        UUID)
            if [[ -e $MOCK/luks/$k ]]; then echo "luks-uuid-$k"
            elif [[ -e $MOCK/fs/$k ]]; then echo "fs-uuid-$k"
            else return 2; fi ;;
        PARTUUID) echo "partuuid-$k" ;;
        TYPE)
            if [[ -e $MOCK/luks/$k ]]; then echo crypto_LUKS
            elif [[ -e $MOCK/fs/$k ]]; then cat "$MOCK/fs/$k"
            else return 2; fi ;;
        PTTYPE) [[ -e $MOCK/disks/${dev#/dev/}.tbl ]] && echo gpt ;;
    esac
}

blockdev() {  # velikost: $MOCK/size/<klic>, disk z .size, oddil z tabulky, jinak 100 GiB
    local dev=${!#} k dn n se
    k=$(mk_key "$dev")
    if [[ -e $MOCK/size/$k ]]; then cat "$MOCK/size/$k"; return; fi
    if [[ -e $MOCK/disks/${dev#/dev/}.size ]]; then echo $(($(<"$MOCK/disks/${dev#/dev/}.size") * 512)); return; fi
    read -r dn n <<<"$(mock_disk_of "$dev")"
    if [[ -n $dn && -e $MOCK/disks/$dn.tbl ]]; then
        se=$(awk -v n="$n" '$1 == n {print ($3 - $2 + 1) * 512}' "$MOCK/disks/$dn.tbl")
        [[ -n $se ]] && { echo "$se"; return; }
    fi
    echo $((100 * 1024 ** 3))
}

cryptsetup() {
    local pass=""
    [[ " $* " == *" --key-file - "* ]] && pass=$(cat)
    mock_log "cryptsetup $*"
    [[ -n $pass ]] && printf '%s\n' "$pass" >>"$MOCK/passes"
    local dev name
    case $1 in
        luksFormat) dev=${!#}; printf '%s' "$pass" >"$MOCK/luks/$(mk_key "$dev")"; rm -f "$MOCK/fs/$(mk_key "$dev")" ;;
        open)
            # heslo kontejneru je v souboru luks/<zarizeni> (prazdny = jakekoli)
            if [[ " $* " == *" --test-passphrase "* ]]; then dev=${!#}; else name=${!#}; dev=${*: -2:1}; fi
            [[ -e $MOCK/luks/$(mk_key "$dev") ]] || return 1
            local good; good=$(<"$MOCK/luks/$(mk_key "$dev")")
            [[ -z $good || $pass == "$good" ]] || return 2
            [[ -n ${name-} ]] && echo "$dev" >"$MOCK/open/$name"
            return 0 ;;
        close) rm -f "$MOCK/open/$2" ;;
        luksAddKey) cp "${!#}" "$MOCK/keys/$(mk_key "${*: -2:1}")" ;;
    esac
    return 0
}

pvcreate() { mock_log "pvcreate $*"; }
vgcreate() { mock_log "vgcreate $*"; local a; for a in "$@"; do [[ $a == -* ]] || { echo "${*: 2}" >"$MOCK/vg/$a"; break; }; done; }
vgs() {  # vgs NAME | vgs ... -o vg_free NAME (volne misto z $MOCK/vgfree/NAME, jinak 10 GiB)
    local name=${!#}
    [[ -e $MOCK/vg/$name ]] || return 5
    if [[ " $* " == *" -o "* ]]; then cat "$MOCK/vgfree/$name" 2>/dev/null || echo $((10 * 1024 ** 3)); fi
    return 0
}
vgchange() { mock_log "vgchange $*"; }
lvs() {  # lvs VG/LV | lvs ... -o lv_size DEV (velikost z $MOCK/lvsize/<vg-lv>, jinak 1 GiB)
    local d=${!#} k
    k=${d#/dev/}; k=${k//\//-}
    if [[ " $* " == *" -o lv_size "* ]]; then cat "$MOCK/lvsize/$k" 2>/dev/null || echo $((1024 ** 3)); return 0; fi
    [[ " $* " == *" -o "* ]] && return 0
    [[ -e $MOCK/lv/$k ]]
}
lvremove() { mock_log "lvremove $*"; }
lvcreate() {
    mock_log "lvcreate $*"
    local n="" vg=${!#} a=("$@") i
    for ((i = 0; i < ${#a[@]}; i++)); do [[ ${a[i]} == -n ]] && n=${a[i + 1]}; done
    : >"$MOCK/lv/${vg//-/--}-${n//-/--}"
    : >"$MOCK/lv/$vg-$n"
}
mock_mkfs() { local t=$1; shift; mock_log "mkfs.$t $*"; echo "$t" >"$MOCK/fs/$(mk_key "${!#}")"; rm -f "$MOCK/luks/$(mk_key "${!#}")"; }
mkfs.btrfs() { mock_mkfs btrfs "$@"; }
mkfs.ext4()  { mock_mkfs ext4 "$@"; }
mkfs.xfs()   { mock_mkfs xfs "$@"; }
mkfs.f2fs()  { mock_mkfs f2fs "$@"; }
mkfs.fat()   { mock_mkfs vfat "$@"; }
mkswap()     { mock_mkfs swap "$@"; }
wipefs()     { mock_log "wipefs $*"; rm -f "$MOCK/fs/$(mk_key "${!#}")" "$MOCK/luks/$(mk_key "${!#}")"; }
mount()      { mock_log "mount $*"; }
umount()     { mock_log "umount $*"; }
btrfs()      { mock_log "btrfs $*"; }
partprobe()  { mock_log "partprobe $*"; }
partx()      { mock_log "partx $*"; }
udevadm()    { :; }
swapoff()    { :; }
e2fsck()     { mock_log "e2fsck $*"; }
resize2fs()  { mock_log "resize2fs $*"; }
ntfsresize() { mock_log "ntfsresize $*"; }
sleep()      { :; }

# --- funkce volajiciho (luxos-install) ---------------------------------------------
T() { local f=$1; shift; printf -- "$f" "$@"; }
run() { "$@"; }
step() { mock_log "@@STEP $*"; }
info() { :; }
progress() { :; }
fail() { mock_log "FAIL $*"; echo "FAIL: $*" >&2; exit 1; }
