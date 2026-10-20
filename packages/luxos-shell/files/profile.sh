# LuxOS - systemove promenne prostredi
# /etc/xdg/luxos ma prednost pred /etc/xdg (vychozi nastaveni LuxOS bez prepisovani cizich baliku)
case ":${XDG_CONFIG_DIRS:-}:" in
    *:/etc/xdg/luxos:*) ;;
    *) export XDG_CONFIG_DIRS="/etc/xdg/luxos:${XDG_CONFIG_DIRS:-/etc/xdg}" ;;
esac

# Prekryti .desktop souboru (skryti technickych polozek z Launchpadu a menu)
case ":${XDG_DATA_DIRS:-}:" in
    *:/usr/share/luxos/xdg:*) ;;
    *) export XDG_DATA_DIRS="/usr/share/luxos/xdg:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}" ;;
esac
