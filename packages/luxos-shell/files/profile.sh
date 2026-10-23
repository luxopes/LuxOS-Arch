# LuxOS - systemove promenne prostredi
# /etc/xdg/luxos ma prednost pred /etc/xdg (vychozi nastaveni LuxOS bez prepisovani cizich baliku)
case ":${XDG_CONFIG_DIRS:-}:" in
    *:/etc/xdg/luxos:*) ;;
    *) export XDG_CONFIG_DIRS="/etc/xdg/luxos:${XDG_CONFIG_DIRS:-/etc/xdg}" ;;
esac

# Prekryti .desktop souboru: kratke nazvy aplikaci (/var/lib/luxos/apps, generuje hook spravce baliku)
# a skryti technickych polozek z Launchpadu a menu (/usr/share/luxos/xdg)
case ":${XDG_DATA_DIRS:-}:" in
    *:/usr/share/luxos/xdg:*) ;;
    *) export XDG_DATA_DIRS="/var/lib/luxos/apps:/usr/share/luxos/xdg:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}" ;;
esac
# Lehci horni lista: pluginy bez nabidek primo v procesu panelu (/usr/lib/luxos/panel, luxos-desktop)
case ":$XDG_DATA_DIRS:" in
    *:/usr/lib/luxos/panel/share:*) ;;
    *) export XDG_DATA_DIRS="/usr/lib/luxos/panel/share:$XDG_DATA_DIRS" ;;
esac

# Programy LuxOS, ktere nahrazuji casti Xfce (napr. xfdesktop-settings -> Plocha a Dock)
case ":$PATH:" in
    *:/usr/lib/luxos/override-bin:*) ;;
    *) export PATH="/usr/lib/luxos/override-bin:$PATH" ;;
esac
