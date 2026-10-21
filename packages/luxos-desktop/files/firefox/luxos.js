// LuxOS - vychozi nastaveni Firefoxu (uzivatel je muze zmenit v about:config)

// Hardwarove dekodovani videa pres VA-API (Intel, AMD): mene prace pro procesor, delsi vydrz baterie
pref("media.ffmpeg.vaapi.enabled", true);
// Pri nedostatku pameti uvolnit dlouho nepouzivane panely (misto zpomaleni celeho systemu)
pref("browser.tabs.unloadOnLowMemory", true);
// Relace se uklada jednou za minutu misto kazdych 15 s (mene zapisu na disk)
pref("browser.sessionstore.interval", 60000);
// Prekryvne posuvniky a plynule posouvani jako v macOS
pref("widget.gtk.overlay-scrollbars.enabled", true);
pref("general.smoothScroll.msdPhysics.enabled", true);
