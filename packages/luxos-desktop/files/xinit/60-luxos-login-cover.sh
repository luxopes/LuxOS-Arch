# LuxOS - prechod po prihlaseni (nacita ho /etc/lightdm/Xsession pred spustenim relace): obrazovka
# zustane jako posledni snimek prihlasovaci obrazovky (tapeta), dokud se neposklada plocha a lista,
# pak se behem ~0,3 s odkryje. Nic nezdrzuje - bezi na pozadi, vstup jde skrz, nejdele 5 s.
case "${DESKTOP_SESSION:-}" in
    luxos | xfce) [ -x /usr/bin/luxos-session-cover ] && /usr/bin/luxos-session-cover --login >/dev/null 2>&1 & ;;
esac
