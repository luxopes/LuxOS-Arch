# LuxOS - preklady pro skripty (bash): T "English %s" arg -> text v jazyce uzivatele
# Preklady: /usr/share/luxos/i18n/<jazyk>.tsv (radek "anglicky<TAB>preklad")
# Rychlost: tabulka se nenacita cela (smycka v bashi pres ~2400 radku stala ~70 ms pri kazdem
# spusteni skriptu, napr. baterie v liste kazdych 20 s, Launchpad, Hledani). Kazdy text se
# vyhleda az pri pouziti jednim volanim awk (~2-5 ms) a zapamatuje se v procesu; skript, ktery
# primo (ne v $(...)) vyhleda vic nez 12 textu, si nacte celou tabulku jako drive.
# LUXOS_I18N_DIR prepise adresar s preklady (testy bez instalace balicku).
declare -gA _LUX_TR=()
_lux_lang=${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}
_lux_lang=${_lux_lang%%[_.@]*}
_lux_tsv=${LUXOS_I18N_DIR:-/usr/share/luxos/i18n}/$_lux_lang.tsv
[[ $_lux_lang != en && -r $_lux_tsv ]] || _lux_tsv=
_lux_miss=0

_lux_load_all() {
    local _k _v
    while IFS=$'\t' read -r _k _v; do
        [[ -z $_k || $_k == \#* || -z $_v ]] && continue
        _LUX_TR[$_k]=$_v
    done <"$_lux_tsv"
    _lux_tsv=
}

T() {
    local f
    if [[ -n $_lux_tsv && -z ${_LUX_TR[$1]+x} ]] && (( ++_lux_miss > 12 )); then
        _lux_load_all
    fi
    if [[ -n $_lux_tsv && -z ${_LUX_TR[$1]+x} ]]; then
        # stejna pravidla jako drive: komentare a prazdne preklady se preskoci, plati posledni radek
        f=$(_LUX_K=$1 LC_ALL=C awk -F'\t' '$1 == ENVIRON["_LUX_K"] && $1 !~ /^#/ && $2 != "" {
                v = $0; sub(/^[^\t]*\t+/, "", v); sub(/\t+$/, "", v); r = v } END { printf "%s", r }' "$_lux_tsv")
        _LUX_TR[$1]=${f:-$1}
    fi
    f=${_LUX_TR[$1]-$1}
    shift
    # shellcheck disable=SC2059
    printf -- "$f" "$@"
}
