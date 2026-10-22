# LuxOS installer - nahrada dd, blkdiscard a sysfs pro testy wipe.sh (source PO mock-env.sh)
#
# Nic se skutecne nezapisuje: kazdy kus se zapise do $MOCK/wipe ("nastroj zarizeni offset delka")
# a do $MOCK/cmds. Rizeni testu (soubory v $MOCK):
#   sysfs/<klic>.<atribut>   hodnota queue/<atribut> (oddil bez vlastni hodnoty -> hodnota disku)
#   nosecure                 blkdiscard --secure skonci EOPNOTSUPP (95)
#   ddfail                   dd selze na tomto offsetu (chyba zapisu)
#   cancel_after             po N kusech vytvori $WIPE_CANCEL_FILE (tlacitko v GUI)
#   int_after                po N kusech posle sam sobe SIGINT (Ctrl+C v terminalu)

wipe_isblk() { ly_isblk "$1"; }

wipe_sysfs() {
    local k dn n
    k=$(mk_key "$1")
    [[ -e $MOCK/sysfs/$k.$2 ]] && { cat "$MOCK/sysfs/$k.$2"; return; }
    read -r dn n <<<"$(mock_disk_of "$1")"
    [[ -n $dn && -e $MOCK/sysfs/$dn.$2 ]] && { cat "$MOCK/sysfs/$dn.$2"; return; }
    echo 0
}

mock_wipe_chunk() {  # mock_wipe_chunk NASTROJ DEV OFF LEN -> zaznam, rizene chyby/zruseni
    local n
    printf '%s %s %s %s\n' "$1" "$2" "$3" "$4" >>"$MOCK/wipe"
    mock_log "wipe-chunk $1 $2 $3 $4"
    n=$(wc -l <"$MOCK/wipe")
    if [[ -e $MOCK/cancel_after ]] && ((n >= $(<"$MOCK/cancel_after"))); then
        : >"$WIPE_CANCEL_FILE"
    fi
    if [[ -e $MOCK/int_after ]] && ((n == $(<"$MOCK/int_after"))); then
        kill -INT "$BASHPID"
        return 130
    fi
    [[ -e $MOCK/ddfail && $1 == dd && $3 == "$(<"$MOCK/ddfail")" ]] && return 1
    return 0
}

dd() {
    local a dev="" off=0 len=0
    for a in "$@"; do
        case $a in
            of=*) dev=${a#of=} ;;
            seek=*) off=${a#seek=} ;;
            count=*) len=${a#count=} ;;
        esac
    done
    [[ " $* " == *" if=/dev/zero "* && " $* " == *"oflag=direct,seek_bytes"* && " $* " == *"iflag=count_bytes"* ]] ||
        { mock_log "dd BAD ARGS $*"; return 1; }
    mock_wipe_chunk dd "$dev" "$off" "$len"
}

blkdiscard() {
    local tool=discard off=0 len=0 dev=${!#} i
    local -a a=("$@")
    for ((i = 0; i < ${#a[@]}; i++)); do
        case ${a[i]} in
            --secure|-s) tool=secure ;;
            -z|--zeroout) tool=zeroout ;;
            -o) off=${a[i + 1]} ;;
            -l) len=${a[i + 1]} ;;
        esac
    done
    if [[ $tool == secure && -e $MOCK/nosecure ]]; then
        mock_log "blkdiscard --secure EOPNOTSUPP $dev"
        return 95
    fi
    mock_wipe_chunk "$tool" "$dev" "$off" "$len"
}
