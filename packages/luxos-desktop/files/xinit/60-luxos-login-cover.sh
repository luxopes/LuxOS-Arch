# LuxOS - prechod po prihlaseni (nacita ho /etc/lightdm/Xsession pred spustenim relace): obrazovka
# zustane jako posledni snimek prihlasovaci obrazovky (tapeta) s koleckem nacitani, dokud neni plocha,
# lista a Dock vykreslena, pak se behem ~0,3 s odkryje. Nic nezdrzuje - bezi na pozadi, vstup jde skrz,
# nejdele 15 s. Jine relace jen uvolni snimek, ktery greeter nechal na obrazovce.
case "${DESKTOP_SESSION:-}" in
    luxos | xfce) [ -x /usr/bin/luxos-session-cover ] && /usr/bin/luxos-session-cover --login >/dev/null 2>&1 & ;;
    *) [ -x /usr/bin/luxos-session-cover ] && /usr/bin/luxos-session-cover --release >/dev/null 2>&1 ;;
esac
