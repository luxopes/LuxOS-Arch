# LuxOS - preklady pro skripty (bash): T "English %s" arg -> text v jazyce uzivatele
# Preklady: /usr/share/luxos/i18n/<jazyk>.tsv (radek "anglicky<TAB>preklad")
declare -gA _LUX_TR=()
_lux_lang=${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}
_lux_lang=${_lux_lang%%[_.@]*}
if [[ -r /usr/share/luxos/i18n/$_lux_lang.tsv ]]; then
    while IFS=$'\t' read -r _k _v; do
        [[ -z $_k || $_k == \#* || -z $_v ]] && continue
        _LUX_TR[$_k]=$_v
    done </usr/share/luxos/i18n/$_lux_lang.tsv
fi
unset _k _v

T() {
    local f=${_LUX_TR[$1]-$1}
    shift
    # shellcheck disable=SC2059
    printf -- "$f" "$@"
}
