// LuxOS - vychozi nastaveni Firefoxu (uzivatel je muze zmenit v about:config)

// Hardwarove dekodovani videa pres VA-API (Intel, AMD): mene prace pro procesor, delsi vydrz baterie
pref("media.ffmpeg.vaapi.enabled", true);
// Pri nedostatku pameti uvolnit dlouho nepouzivane panely (misto zpomaleni celeho systemu)
pref("browser.tabs.unloadOnLowMemory", true);
// Relace se uklada jednou za minutu misto kazdych 15 s (mene zapisu na disk)
pref("browser.sessionstore.interval", 60000);
// Prekryvne posuvniky a plynule posouvani jako v macOS
pref("widget.gtk.overlay-scrollbars.enabled", true);
pref("general.smoothScroll", true);
pref("general.smoothScroll.msdPhysics.enabled", true);
// Touchpad po pixelech se setrvacnosti po zvednuti prstu: gesto posunu z XInput2 (MOZ_USE_XINPUT2=1 nastavuje
// /etc/X11/xinit/xinitrc.d/50-luxos-firefox-xinput2.sh), konec gesta posila xf86-input-libinput po zvednuti
// prstu; vypnuti v Nastaveni > Posouvani resi modul luxos-scroll (konec gesta prijde pozdeji, rychlost 0)
pref("apz.gtk.pangesture.enabled", true);
pref("apz.gtk.kinetic_scroll.enabled", true);
