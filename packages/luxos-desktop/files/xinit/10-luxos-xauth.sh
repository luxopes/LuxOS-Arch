# LuxOS - pristup k obrazovce i po zmene nazvu pocitace za behu relace (nacita ho /etc/lightdm/Xsession
# pred spustenim relace, drive nez kterykoli program relace): polozka FamilyWild v ~/.Xauthority,
# viz /usr/lib/luxos/luxos-xauth-wildcard. Nejvys par desitek ms; chyba relaci nikdy nezastavi.
[ -x /usr/lib/luxos/luxos-xauth-wildcard ] && /usr/lib/luxos/luxos-xauth-wildcard >/dev/null 2>&1 </dev/null
true
