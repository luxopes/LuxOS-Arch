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

// Prvni spusteni: misto oznameni o soukromi Mozilly a about:welcome uvitaci stranka LuxOS (jednou pro novy
// profil; adresu v jazyce systemu nastavuje /usr/lib/firefox/luxos.cfg). Po aktualizaci Firefoxu zadna
// stranka "Co je noveho" z webu Mozilly.
pref("datareporting.policy.firstRunURL", "");
pref("browser.aboutwelcome.enabled", false);
pref("startup.homepage_override_url", "");
// Soukromi: Firefox neposila telemetrii ani technicka data Mozille, zadne studie, zadne sponzorovane
// zkratky a clanky na nove karte (uvitaci stranka LuxOS uvadi presne tyto volby)
pref("datareporting.healthreport.uploadEnabled", false);
pref("datareporting.policy.dataSubmissionEnabled", false);
pref("toolkit.telemetry.enabled", false);
pref("toolkit.telemetry.unified", false);
pref("toolkit.telemetry.archive.enabled", false);
pref("app.shield.optoutstudies.enabled", false);
pref("app.normandy.enabled", false);
pref("browser.newtabpage.activity-stream.showSponsored", false);
pref("browser.newtabpage.activity-stream.showSponsoredTopSites", false);
pref("browser.newtabpage.activity-stream.feeds.telemetry", false);
pref("browser.newtabpage.activity-stream.telemetry", false);
// Ani jine dotazy na servery Mozilly, o kterych uvitaci stranka mlci: urceni zeme podle IP, test pripojeni
// a prihlasovaci stranky Wi-Fi (detectportal.firefox.com - LuxOS ma vlastni luxos-portal-check a okno
// prihlaseni k siti), doporucene doplnky a clanky Pocket na nove karte
pref("browser.region.update.enabled", false);
pref("browser.region.network.url", "");
pref("network.captive-portal-service.enabled", false);
pref("network.connectivity-service.enabled", false);
pref("browser.discovery.enabled", false);
pref("extensions.getAddons.showPane", false);
pref("extensions.htmlaboutaddons.recommendations.enabled", false);
pref("browser.newtabpage.activity-stream.feeds.section.topstories", false);
pref("browser.newtabpage.activity-stream.feeds.system.topstories", false);
// Blokovani reklam: uBlock Origin z balicku firefox-ublock-origin (/usr/lib/firefox/browser/extensions)
// se v novych i stavajicich profilech zapne bez dotazu - doplnky v adresari aplikace (rozsah 4) se
// nevypinaji. Stejnou hodnotu ma vendor.js Firefoxu z Archu; tady pro jistotu, kdyby ji zmenil.
pref("extensions.autoDisableScopes", 11);
