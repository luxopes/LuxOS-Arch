# LuxOS - metoda zadavani (fcitx5, psani vietnamsky): promenne pro aplikace, jen kdyz ji uzivatel ma
# (nacita /etc/lightdm/Xsession pred spustenim relace). Stejne poradi jako luxos_input_method.active():
# volba IM= v ~/.config/luxos/input-method (vi / user / none), pak vlastni profil fcitx5 uzivatele,
# nakonec jazyk vi_*. fcitx5 samotny spousti xdg autostart (luxos-input-method autostart).
# Vlastni hodnoty promennych maji prednost. LUXOS_IM_ADDONS: slozka s bamboo.conf (testy).
_luxos_im() {
    _c=${XDG_CONFIG_HOME:-$HOME/.config}
    _im=
    [ -r "$_c/luxos/input-method" ] &&
        _im=$(sed -n 's/^[[:space:]]*IM[[:space:]]*=[[:space:]]*//p' "$_c/luxos/input-method" | tail -n 1 | tr -d ' \r\t')
    case $_im in
        vi) [ -f "${LUXOS_IM_ADDONS:-/usr/share/fcitx5/inputmethod}/bamboo.conf" ]; return ;;
        user) return 0 ;;
        ?*) return 1 ;;
    esac
    [ -f "$_c/fcitx5/profile" ] && return 0
    # prvni nastaveny jazyk z LC_ALL, LC_CTYPE, LANG; C/POSIX preskocit
    for _v in "${LC_ALL:-}" "${LC_CTYPE:-}" "${LANG:-}"; do
        case $_v in
            ""|C|C.*|POSIX|POSIX.*) continue ;;
            vi_*|vi) [ -f "${LUXOS_IM_ADDONS:-/usr/share/fcitx5/inputmethod}/bamboo.conf" ]; return ;;
            *) return 1 ;;
        esac
    done
    return 1
}
if command -v fcitx5 >/dev/null 2>&1 && _luxos_im; then
    [ -n "${GTK_IM_MODULE:-}" ] || export GTK_IM_MODULE=fcitx
    [ -n "${QT_IM_MODULE:-}" ] || export QT_IM_MODULE=fcitx
    [ -n "${XMODIFIERS:-}" ] || export XMODIFIERS=@im=fcitx
    [ -n "${SDL_IM_MODULE:-}" ] || export SDL_IM_MODULE=fcitx
fi
unset -f _luxos_im
unset _c _im _v
