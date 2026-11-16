# LuxOS - Firefox na X11 pres XInput2 (nacita ho /etc/lightdm/Xsession pred spustenim relace): touchpad posouva
# po pixelech jako gesto posunu a po zvednuti prstu dojede setrvacnosti. Bez toho Firefox (160) na X11 vypne
# XInput2 a z touchpadu dostava jen zarazky kolecka. Vlastni hodnota (MOZ_USE_XINPUT2=0) ma prednost.
[ -n "${MOZ_USE_XINPUT2:-}" ] || export MOZ_USE_XINPUT2=1
