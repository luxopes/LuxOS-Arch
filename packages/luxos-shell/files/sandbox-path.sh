# LuxOS - prikazy aplikaci ze sandboxu (obaly od "luxos-sandbox sync-launchers") vzdy na KONCI PATH:
# program systemu stejneho jmena (napr. pozdeji nainstalovany "lux install --system") tak vzdy vyhraje.
# Jako /etc/profile.d/zz-luxos-sandbox.sh se nacte pri prihlaseni az po ostatnich skriptech (ktere PATH
# prodluzuji, napr. perl), bashrc a zshrc LuxOS ho nacitaji v kazdem novem terminalu - i v relaci
# prihlasene pred aktualizaci. Opakovane nacteni nic nezdvoji; slozka uprostred PATH se presune na konec.
_luxos_sb="${XDG_DATA_HOME:-$HOME/.local/share}/luxos/sandbox/bin"
case ":$PATH:" in
    *":$_luxos_sb:") ;;
    *)
        _luxos_p=""
        _luxos_rest="$PATH:"
        while [ -n "$_luxos_rest" ]; do
            _luxos_d=${_luxos_rest%%:*}
            _luxos_rest=${_luxos_rest#*:}
            [ "$_luxos_d" = "$_luxos_sb" ] && continue
            _luxos_p="${_luxos_p:+$_luxos_p:}$_luxos_d"
        done
        PATH="${_luxos_p:+$_luxos_p:}$_luxos_sb" ;;
esac
export PATH
unset _luxos_sb _luxos_p _luxos_rest _luxos_d
