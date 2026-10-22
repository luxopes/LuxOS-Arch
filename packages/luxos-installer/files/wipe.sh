# LuxOS - bezpecne smazani mista pro LuxOS pred instalaci (WIPE=zero|overwrite)
#
# Knihovnu nacita luxos-install (/usr/share/luxos/installer/wipe.sh). Od volajiciho potrebuje:
#   T, info, progress, fail, LOG, PROGRESS a promenne WIPE, WIPE_CANCEL_FILE.
# Maze se jen zarizeni, ktera LuxOS hned potom naformatuje / zasifruje (oddily LuxOS, nove LV,
# formatovane existujici oddily) - po rozdeleni disku, pred mkfs/LUKS. Cely disk ani jine oddily nikdy.
#
# Zpusob (WIPE=zero, od nejrychlejsiho; vse setri procesor):
#   secure    blkdiscard --secure  (bezpecne smazani prikazem disku, eMMC/nektera SSD)
#   zeroout   blkdiscard -z        (nulovani prikazem disku Write Zeroes, NVMe/SCSI; jen pri hw podpore)
#   overwrite dd z /dev/zero s O_DIRECT (opakovany vzor = nuly; procesor jen kopiruje, nic nepocita)
# WIPE=overwrite = vzdy jen dd (napr. kdyz firmware disku neverime).
# Postupuje po kusech: prubeh, odhad casu a zruseni (Ctrl+C v terminalu, soubor WIPE_CANCEL_FILE z GUI)
# mezi kusy. Zruseni = zbytek mazani se preskoci a instalace pokracuje.

WIPE_CHUNK=$((256 * 1024 * 1024))          # dd: kus mezi kontrolami zruseni (~2 s na HDD)
WIPE_HW_CHUNK=$((4 * 1024 * 1024 * 1024))  # blkdiscard: prikaz disku je rychly, vetsi kusy
WIPE_CANCELLED=0
WIPE_TOTAL=0      # bajtu celkem (pro @@PCT a odhad); 0 = nevime
WIPE_DONE=0       # bajtu hotovo napric zarizenimi
declare -gA WIPE_SEEN=()

wipe_enabled() { [[ ${WIPE:-none} == @(zero|overwrite) ]]; }
wipe_valid() { [[ ${WIPE:-none} == @(none|zero|overwrite) ]]; }

wipe_sysfs() {  # wipe_sysfs DEV ATTR -> hodnota z queue/ (oddil: fronta nadrazeneho disku), jinak 0
    local name dir
    name=$(basename "$(readlink -f "$1")")
    dir=/sys/class/block/$name
    [[ -d $dir/queue ]] || dir=$dir/..
    cat "$dir/queue/$2" 2>/dev/null || echo 0
}

wipe_size() { blockdev --getsize64 "$1" 2>/dev/null || echo 0; }
wipe_isblk() { [[ -b $1 ]]; }   # testy nahrazuji (zarizeni v emulaci)

wipe_guard() {  # wipe_guard DEV: jen oddil / LV / otevreny LUKS, nepripojeny, ne cely disk
    local dev=$1 type mp
    wipe_isblk "$dev" || fail "$(T "Cannot erase %s: it is not a block device." "$dev")"
    type=$(lsblk -dno TYPE "$dev" 2>/dev/null | head -1)
    [[ $type == @(part|lvm|crypt) ]] || fail "$(T "Refusing to erase %s (type %s): only LuxOS partitions and volumes are erased." "$dev" "${type:-?}")"
    mp=$(lsblk -no MOUNTPOINTS "$dev" 2>/dev/null | sed '/^$/d' | head -1) || true
    [[ -z $mp ]] || fail "$(T "Cannot erase %s: it is in use (%s)." "$dev" "$mp")"
    return 0
}

wipe_method() {  # wipe_method DEV -> secure|zeroout|overwrite (podle WIPE a podpory disku)
    [[ ${WIPE:-none} == overwrite ]] && { echo overwrite; return; }
    if (($(wipe_sysfs "$1" discard_max_bytes) > 0)); then echo secure; return; fi
    if (($(wipe_sysfs "$1" write_zeroes_max_bytes) > 0)); then echo zeroout; return; fi
    echo overwrite
}

wipe_cancel_requested() {
    ((WIPE_CANCELLED)) && return 0
    if [[ -n ${WIPE_CANCEL_FILE-} && -e $WIPE_CANCEL_FILE ]]; then WIPE_CANCELLED=1; return 0; fi
    return 1
}

wipe_human() { numfmt --to=si --suffix=B --format=%.1f "$1" 2>/dev/null || echo "$1 B"; }

wipe_eta_text() {  # sekundy -> "about 3 min left"
    local s=$1
    if ((s < 60)); then T "less than a minute left"
    elif ((s < 5400)); then T "about %s min left" "$(((s + 59) / 60))"
    else T "about %s h %s min left" "$((s / 3600))" "$((s % 3600 / 60))"; fi
}

wipe_now() { local t=${EPOCHREALTIME:-$SECONDS}; echo "${t/[.,]/}"; }   # mikrosekundy (EPOCHREALTIME)

wipe_report() {  # wipe_report DEV HOTOVO VELIKOST START_US
    local dev=$1 done=$2 size=$3 start=$4 pct all_pct=0 el rate eta="" line
    pct=$((size > 0 ? done * 100 / size : 100))
    el=$(($(wipe_now) - start))
    if ((el > 2000000 && done > 0)); then
        rate=$((done * 1000000 / el))
        ((rate > 0)) && eta=" · $(wipe_eta_text $(((size - done) / rate)))"
    fi
    line="$(T "Erasing %s: %s %% (%s of %s)" "$dev" "$pct" "$(wipe_human "$done")" "$(wipe_human "$size")")$eta"
    if ((WIPE_TOTAL > 0)); then
        all_pct=$(((WIPE_DONE + done) * 100 / WIPE_TOTAL))
        ((all_pct > 100)) && all_pct=100
        progress "PCT $all_pct"
    fi
    if ((PROGRESS)); then
        progress "STATUS $line"
    else
        printf '\r\e[K  %s  %s' "$line" "$(T "(Ctrl+C skips erasing)")"
    fi
}

wipe_chunk() {  # wipe_chunk METODA DEV OFFSET DELKA -> navratovy kod nastroje
    case $1 in
        secure)  blkdiscard -f --secure -o "$3" -l "$4" "$2" ;;
        zeroout) blkdiscard -f -z -o "$3" -l "$4" "$2" ;;
        *)       dd if=/dev/zero of="$2" bs=4M iflag=count_bytes oflag=direct,seek_bytes conv=notrunc,fsync \
                    seek="$3" count="$4" status=none ;;
    esac
}

wipe_device() {  # wipe_device DEV: smaze cele zarizeni (jednou), pri zruseni skonci bez chyby
    local dev=$1 size method off len step rc start
    [[ -n ${WIPE_SEEN[$dev]-} ]] && return 0
    WIPE_SEEN[$dev]=1
    wipe_enabled || return 0
    wipe_cancel_requested && return 0
    wipe_guard "$dev"
    size=$(wipe_size "$dev")
    ((size > 0)) || { info "$(T "Skipping %s: size unknown." "$dev")"; return 0; }
    method=$(wipe_method "$dev")
    printf '+ wipe %s %s (%s bytes)\n' "$method" "$dev" "$size" >>"$LOG" 2>/dev/null || true
    info "$(T "Erasing %s (%s)" "$dev" "$(wipe_human "$size")")"
    start=$(wipe_now)
    off=0
    while ((off < size)); do
        if wipe_cancel_requested; then break; fi
        step=$WIPE_CHUNK
        [[ $method != overwrite ]] && step=$WIPE_HW_CHUNK
        len=$((size - off < step ? size - off : step))
        rc=0
        wipe_chunk "$method" "$dev" "$off" "$len" >>"$LOG" 2>&1 || rc=$?
        if ((rc)); then
            wipe_cancel_requested && break
            if [[ $method != overwrite && $off == 0 ]]; then
                # Disk prikaz nepodporuje (EOPNOTSUPP) - zkusit dalsi zpusob od zacatku
                if [[ $method == secure && $(wipe_sysfs "$dev" write_zeroes_max_bytes) -gt 0 ]]; then method=zeroout
                else method=overwrite; fi
                printf '+ wipe fallback %s %s\n' "$method" "$dev" >>"$LOG" 2>/dev/null || true
                continue
            fi
            fail "$(T "Erasing %s failed (write error at %s). The disk may be damaged." "$dev" "$(wipe_human "$off")")"
        fi
        off=$((off + len))
        wipe_report "$dev" "$off" "$size" "$start"
    done
    ((PROGRESS)) || printf '\r\e[K'
    WIPE_DONE=$((WIPE_DONE + (off < size ? off : size)))
    if ((WIPE_CANCELLED)); then
        info "$(T "Erasing was skipped - the installation continues. %s of %s was overwritten." "$(wipe_human "$off")" "$(wipe_human "$size")")"
        progress "STATUS $(T "Erasing was skipped - the installation continues.")"
    fi
    return 0
}

wipe_begin() {  # wipe_begin CELKEM_BAJTU: zacatek mazani (Ctrl+C = preskocit, GUI ukaze tlacitko)
    WIPE_TOTAL=${1:-0} WIPE_DONE=0
    wipe_enabled || return 0
    progress "WIPE START"
    trap 'WIPE_CANCELLED=1' INT
}

wipe_end() {
    wipe_enabled || return 0
    trap - INT
    progress "WIPE END"
    return 0
}

wipe_devices() {  # wipe_devices DEV...: vse v jednom kroku s prubehem pres vsechna zarizeni
    local d total=0
    wipe_enabled || return 0
    for d in "$@"; do total=$((total + $(wipe_size "$d"))); done
    wipe_begin "$total"
    for d in "$@"; do wipe_device "$d"; done
    wipe_end
}

# Odhad doby prepsani (bez rychleho prikazu disku): HDD ~130 MB/s, SATA SSD ~450 MB/s, NVMe ~1,5 GB/s
wipe_speed() {  # wipe_speed DISK -> bajtu za sekundu
    local rota tran
    read -r rota tran < <(lsblk -dno ROTA,TRAN "$1" 2>/dev/null)
    if [[ $tran == nvme || $1 == /dev/nvme* ]]; then echo 1500000000
    elif [[ $rota == 0 ]]; then echo 450000000
    else echo 130000000; fi
}

wipe_estimate_text() {  # wipe_estimate_text BAJTU DISK -> "about 25 min"
    local bytes=$1 speed s
    speed=$(wipe_speed "$2")
    s=$((bytes / speed))
    if ((s < 60)); then T "under a minute"
    elif ((s < 5400)); then T "about %s min" "$(((s + 59) / 60))"
    else T "about %s h %s min" "$((s / 3600))" "$((s % 3600 / 60))"; fi
}
