# LuxOS – seznam změn

Verze: `X.Y.Z` – `Y` roste s každým novým ISO, `Z` s opravami chyb. Každá velká verze nese jméno hvězdy.
Číslo verze je v `packages/luxos-branding/files/version` (os-release, O tomto počítači, fastfetch, název ISO).
LuxOS je průběžně aktualizovaný systém (`lux update`): verze označuje, z jakého stavu systém vychází.

## 0.9.6 „Polaris“ – připravuje se

### Změny
- Proces relace `luxos-daemon` se jmenuje `luxos-hub` (Kalendář a Ovládací centrum na pozadí: `--background`); v textech LuxOS už není slovo „daemon“ (LuxDrop: „Avahi“). Po aktualizaci se nový název projeví po odhlášení a přihlášení.

## 0.9.5 „Polaris“ – 2026-10-22 (beta)

### Nové
- Rozložení klávesnice se ve výchozím stavu přepíná oběma Shifty (dosavadní výchozí Alt+Shift se při aktualizaci jednou převede, vlastní volba zůstane); samotný stisk Super otevře Launchpad (lze vypnout v Klávesových zkratkách).
- Snímek obrazovky: nad lištou název vybraného režimu a zkratka, okamžité popisky při najetí; náhled s akcemi Kopírovat, Zobrazit v Souborech, Uložit jako…, Smazat; Ctrl při pořízení kopíruje do schránky.
- Nové ikony Monitorů a Otisku prstu.

## 0.9.4 „Polaris“ – 2026-10-22 (beta)

### Rychlost
- Obrázky a ikony se dekódují přímo v procesu aplikace: vlastní balík `gdk-pixbuf2` bez glycinu a zavaděč SVG `luxos-pixbuf-svg` (Arch od gdk-pixbuf 2.44 spouští na každý obrázek sandbox bwrap + proces glycin; ikona SVG stála ~4 ms a 5 procesů, teď ~2 ms a žádný; přihlášení bez ~40 sandboxů, Launchpad bez ~120 procesů, PNG 6× rychleji). Ve VM: Dock po přihlášení za 1,9 s místo 2,9 s, procesor po přihlášení 3,6 s místo 5,2 s.
- luxos-hub vytváří skrytá okna Ovládacího centra a Kalendáře až po usazení relace (nebo při prvním kliknutí), gpg-agent se při přihlášení nezabíjí a nespouští znovu (jede přes systemd), tapeta po přihlášení jedním dotazem xfconf, překlady ve skriptech lišty bez načítání celé tabulky (baterie každých 20 s: 70 ms → 10 ms), kontrola LuxOS Care po startu s nízkou prioritou, kratší dojezd splashe (0,3 s).

### Opravy
- Otisk prstu: okno má zase horní lištu se zavíráním; u neznámé chyby čtečky ukáže technický důvod. Nová kontrola `scripts/check-titlebars.sh` ověří horní lištu u všech aplikací.
- Ovládací centrum se vždy vejde na obrazovku (delší překlady se zkrátí, okno se po změně velikosti znovu umístí).

## 0.9.3 „Polaris“ – 2026-10-22 (beta)

### Nové
- Spořič baterie naplno: bez turba procesoru, displej 60 Hz, nižší jas, bez animací, úspora zvuku a USB, pozastavené úlohy na pozadí (systémová část jako služba s polkit pravidlem). Spořič dat pozastaví i reflector a synchronizaci klíčů na měřeném připojení.
- Baterie a napájení: „Nespat při přehrávání hudby nebo videa“ (zavření víka jen vypne obrazovku); počet nabíjecích cyklů – když ho baterie nehlásí, řekne to.
- Terminál: `about os`, `about system`, `adduser`, `deluser`, `addgroup`, `delgroup`, `service`, `update-grub`, `lsb_release`; nápovědy pro `apt`, `dnf`, `ifconfig`, `netstat` a další.
- Bluetooth: přejmenování počítače. Instalátor: volitelné bezpečné smazání cílového místa (hardwarově nebo nulami).
- Alt+Tab ve stylu macOS.

### Opravy
- Ovládání přehrávání v Ovládacím centru reaguje okamžitě (události MPRIS místo dotazování).
- Zamčená obrazovka po probuzení: bez černého pruhu dole a posunutého dialogu (chyba xfce4-screensaver, opraveno modulem GTK).
- Jména oken „Co je nového“ a „Snímek obrazovky“ v horní liště.

## 0.9.2 „Polaris“ – 2026-10-22 (beta)

### Nové
- Více rozložení klávesnice v instalátoru (textovém i grafickém) a aplikace Rozložení klávesnice: nastavení pro všechny uživatele a přihlašovací obrazovku, volba kláves pro přepínání.
- Klávesové zkratky: změna, vypnutí, vlastní zkratky, kontrola kolizí, obnovení výchozích.
- Nově připojená sluchátka / reproduktory (Bluetooth, USB, HDMI) se hned stanou výstupem zvuku.

### Opravy
- Starší instalace se aktualizují bez „unresolvable package conflicts“ (lux a LuxOS Care závisí na obecném jádru balíčků; lux-engine nahradí až nový lux).
- Vlajka klávesnice v horní liště otevře Rozložení klávesnice.

## 0.9.1 „Polaris“ – 2026-10-22 (beta)

### Nové
- Snímek obrazovky: plovoucí lišta (Print, Shift+Super+5) – celá obrazovka, okno, výřez, nahrávání obrazovky či výřezu, volby (kam uložit, časovač, ukazatel); Shift+Super+3/4 rovnou.
- Monitory: rozlišení, obnovovací frekvence, otočení (s 15s potvrzením) a velikost textu.
- Přihlášení otiskem prstu (přihlašovací obrazovka, zámek, sudo, schvalování); aplikace Otisk prstu.
- Co je nového: po aktualizaci na novou verzi se při prvním přihlášení ukážou novinky (i v O tomto počítači).
- `lux configs`: sloučení nových verzí konfiguračních souborů.

### Změny
- lux je jediný správce balíčků: příkaz `pacman` v systému není, motor balíčků je balík `lux-engine` (dříve `luxos-pacman`).
- Přihlašovací obrazovka: tapeta se při přepínání uživatelů nemění, profil se plynule posune.
- Obchod: „Aktualizovat vše“ jen když jsou aktualizace, chyba kontroly (síť) se hlásí.
- Ovládací centrum: odhad zbývajícího času baterie; klik na ikonu jasu otevře Monitory.
- Průhledné notifikace podle světlého/tmavého režimu.
- fastfetch: LuxOS Desktop a LuxOS Terminal místo názvů Xfce.

## 0.9.0 „Polaris“ – 2026-10-22 (beta)

První číslovaná verze.

### Vzhled a prostředí
- Prostředí ve stylu macOS nad Xfce: horní lišta s nabídkami a ikonami oken, Dock, Launchpad, Hledání, Ovládací centrum, oznámení, kalendář.
- Vlastní ikony, tapety a logo LuxOS, světlý/tmavý/automatický režim, boot splash a přihlašovací obrazovka.
- Průvodce LuxOS při prvním přihlášení.

### Aplikace
- LuxOS Store, LuxAI (s účtem LuxAI), Lux Code, LSL IDE, Kalkulačka, Kamera, Skener, Tiskárny a skenery, Ovladače, Sledování systému, Bluetooth, Baterie a napájení, Trezor (šifrovaná složka), LuxDrop (kompatibilní s LocalSend), Zpětná vazba.

### Systém
- `lux` – vlastní správce balíčků nad libalpm (místo příkazu pacman), repozitáře `[luxos]` a `[luxos-apps]` s podpisy.
- Automatická detekce hardwaru a ovladačů (NVIDIA podle generace včetně starších karet, zvuk, kamery, Wi-Fi), tisk a skenování bez nastavování.
- Ochrana proti nedostatku paměti (earlyoom), spořič dat a baterie, automatická údržba.
- 13 jazyků.

### Instalátor
- Celý disk, volné místo vedle jiného systému, existující oddíl, nebo ruční rozdělení (LVM, LUKS2, samostatné oddíly).
- Sady aplikací (Každodenní, Programování, Video a foto, Hry, Bezpečnost a sítě).
- Účet LuxAI přímo v instalátoru: přihlášení heslem, kódem z e-mailu nebo založení nového účtu.
