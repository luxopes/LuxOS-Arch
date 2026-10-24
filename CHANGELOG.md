# LuxOS – seznam změn

Verze: `X.Y.Z` – `Y` roste s každým novým ISO, `Z` s opravami chyb. Každá velká verze nese jméno hvězdy.
Číslo verze je v `packages/luxos-branding/files/version` (os-release, O tomto počítači, fastfetch, název ISO).
LuxOS je průběžně aktualizovaný systém (`lux update`): verze označuje, z jakého stavu systém vychází.

## 0.9.9 „Polaris“ – 2026-10-24 (beta)

### Nové
- **Šifrovaný disk nikdy nespadne potichu** (hook `luxos-boot` v `luxos-tweaks`): při špatném hesle hláška „Spatne heslo, zkuste to znovu.“ na úvodní obrazovce i v konzoli, pokusů neomezeně (`systemd-cryptsetup@` se po 3 chybách spustí znovu), na zařízení se při psaní hesla nečeká s limitem. Když se systémový disk neobjeví do 90 s nebo start skončí v nouzovém režimu, uloží se záznam startu na EFI oddíl (`\EFI\LuxOS\boot-failure-*.log`, posledních 5) a vypíše se vysvětlení a co dělat.
- `lux check` (dostupné aktualizace bez instalace), manuálová stránka `man lux`; poškozený stažený balíček lux sám smaže a stáhne znovu (i v Lux Store).
- Instalátor přidá ostatní systémy ze sdíleného EFI oddílu (Debian, Ubuntu, Fedora, …) do nabídky při startu a dá LuxOS na první místo v pořadí UEFI.
- Tiskárny, pro které je ovladač jen u výrobce (AUR, např. Samsung Xpress M2026/SPL): místo nefunkční tiskárny upozornění s tlačítkem „Nainstalovat ovladač“.
- Skener: kamera už není nabízena jako skener, skener zapnutý později se najde sám (hledání každých 6 s, tlačítko „Hledat znovu“). Otisk prstu: tlačítko „Zkusit znovu“ po neúspěšném snímání.

### Opravy
- **Instalace vedle jiného systému do existujícího LUKS + LVM** (Debian): chybělo odemčení disku při startu (`rd.luks.name`, `sd-encrypt`) – systém skončil v nouzovém režimu; instalace z konfiguračního souboru se zastavila na kontrole zamčené skupiny LVM; jméno nového svazku se neuložilo (vždy „root“, kolize se svazkem Debianu).
- Instalátor: ikona oka u všech polí s heslem, větší okno (pole pro heslo šifrování viditelná bez celé obrazovky).
- Ventoy v běžném režimu („INIT NOT FOUND“): initramfs live ISO bez hooku `kms` (229 → 66 MB), ISO 2,42 → 2,10 GB.
- Lux Store „Aktualizace se nepodařilo zkontrolovat“: na počítačích se sdíleným EFI odmítal `lux_alpm` kvůli `HookDir` (jen pro transakce), ověření podpisů pod uživatelem (kopie klíčů), nesouhlasná kopie databáze a podpisu (stáhne se načisto).
- Lux Guard v živém systému z USB neběží (varoval před vlastním instalátorem).
- Launchpad a Hledání: bez výběru najetím myši – neposouvá se samo a Enter spustí první (nejlepší) shodu.
- „Internet není k dispozici“ po každém přihlášení: upozornění až po 20 s trvalého výpadku, ne v první minutě.
- LuxAI 1.0.0-12: agent neohlásí akci bez provedení (jednou se sám dovede k akci), příkazy roota bez `pkexec` (režim správce).

## 0.9.8 „Polaris“ – 2026-10-24 (beta)

### Nové
- **Jas kolečkem myši** nad baterií v horní liště (`luxos-brightness up|down`, kroky po 5 %, nejméně 10 %, ukazatel jako u kláves jasu). Vlastní balík `xfce4-genmon-plugin` (4.3.0-1.1) se značkou `<scroll>příkaz</scroll>`.
- **Upozornění na letní/zimní čas** (`luxos_timechange` v `luxos-hub`): jen v pásmech se změnou času, večer předem (18:00) a ráno po změně, vypínač v Ploše a Docku › Horní lišta a tlačítko Vypnout v upozornění.
- **Lux Store: formátovaný průběh aktualizace** – krok, ukazatel průběhu, seznam balíčků (stará → nová verze, stav), shrnutí a doporučení restartu; technický výpis pod „Podrobnosti“.

### Opravy
- **Jádro LuxOS na starších instalacích**: instalace bez `luxos-care` (starší instalátor) na `linux-luxos` nikdy nepřešly. `luxos-desktop` teď `luxos-care` vyžaduje a jeho instalace přechod spustí (mimo chroot instalátoru).
- Otevřená nabídka horní lišty (např. Zvuk) blokovala klávesové zkratky a pravé tlačítko: zkratky se Super, Ctrl+Alt, Alt+Tab, Alt+F4 a PrtSc nabídku zavřou a provedou se; pravým tlačítkem se mezi nabídkami přepíná jako levým; tuknutí na Super otevře Launchpad i s otevřenou nabídkou.
- Kontextové nabídky horní lišty nezačínají šedým názvem pluginu, na který nejde kliknout (např. „Rozložení klávesnice“) – GTK modul `luxos-panel-menus`.
- Odhlášení, restart a vypnutí: místo oken s černými pruhy (konec kompozitoru) obrazovka plynule zčerná (`luxos-session-cover`).
- Spořič baterie už obrazovku nepřepíná na 60 Hz (přepnutí frekvence ji na okamžik zčernalo); volitelně „Snížit obrazovku na 60 Hz“ v Baterii a napájení.
- Launchpad se kolečkem posouvá po řádcích místo skoku o celou stránku.
- fastfetch v každém novém okně terminálu (ne ve vnořeném shellu).
- Časovač procesoru (TSC) falešně označený za nestabilní (např. Ryzen 5000 v noteboocích, systém pak četl čas z pomalého HPET): LuxOS Care po startu doplní do položek LuxOS jednou `tsc=nowatchdog`, jen u procesorů s invariantním TSC.
- Chyběly `rtkit` (PipeWire bez priority v reálném čase) a `wireless-regdb` (Wi-Fi bez pravidel země) – závislosti `luxos-desktop`.
- Pravidlo I/O plánovače se zkoušelo i na oddíly (varování v záznamu startu).

## 0.9.7 „Polaris“ – 2026-10-23 (beta)

### Nové
- **Lux Guard** (`luxos-guard`): kontrola souborů z internetu, pošty, chatu, LuxDrop a USB při spuštění (fanotify v jádře, značky jen na hlídaných souborech – ostatní programy nic nestojí). Rizikové: dialog „Nespouštět / Spustit v sandboxu / Přesto spustit“; kritické (mazání domovské složky nebo disku, `dd`/`mkfs`/`shred` na disk, šifrování souborů ve smyčce, skrytý kód, vypnutí ochrany…): mimo sandbox nikdy. Vlastní pravidla bez antiviru (na 35 980 skriptech a programech systému 1 planý poplach). Každou hodinu snímek `/home` jen pro čtení (btrfs, 24 h po hodinách + 7 dní), obnova souborů v okně Lux Guard nebo `luxos-guard restore`. Dokumentace i pro LuxAI: `docs/luxos/guard.md`.
- **Přihlášení k síti s portálem** (hotel, vlak, letiště): `luxos-hub` při stavu „portal“ otevře přihlašovací stránku sám, jednou za připojení (znovu tlačítkem „Přihlásit se“ v upozornění), v jednorázovém okně Firefoxu s prázdným profilem v paměti (bez cookies, hesel, historie a doplňků uživatele, po zavření smazáno); po připojení se okno zavře.
- **Jádro LuxOS `linux-luxos`** (https://github.com/luxopes/luxos-kernel): stabilní Linux z kernel.org s ověřeným podpisem, konfigurace Archu (všechny ovladače) + `config-luxos` (BBR, `NR_CPUS=512`, THP na vyžádání). GitHub Actions každých 6 h sestaví novou verzi, spustí ji v QEMU s ~50 ovladači a vydá s attestací původu; LuxOS ji převezme po ověření (`scripts/fetch-kernel.sh`) a podepíše. Nové instalace a live ISO ho mají rovnou, starší instalace přejdou z `linux-zen` samy po aktualizaci (`luxos-care kernel-switch`: hlavičky pro DKMS, kontrola initramfs a modulů DKMS, `linux-zen` zůstane jako „LuxOS (previous kernel)“ a nové jádro má 3 pokusy o start).
- **Ovládací centrum, Kalendář a `luxos-hub` v LSL** (LSL 0.10.6, jeden program místo tří v Pythonu): o 23 MB méně paměti (PSS), 7× méně CPU při startu relace, odezva po kliknutí stejná.

### Opravy
- Obchod: „Aktualizace se nepodařilo zkontrolovat“, když běžela kontrola LuxOS Care současně, nebo po přerušené kontrole (zámek v dočasné databázi). Kontroly na sebe počkají, zbylý zámek se uklidí a Obchod ukáže skutečný důvod chyby.
- Čtečky otisků ELAN (např. 04f3:0c4f, Acer Aspire 7): „Calibration failed!“ – vlastní balík `libfprint` dává kalibraci až 100 kontrol (5 s) místo 10.
- LuxAI 1.0.0-11: hlášení chyb opět uvádí balíky LuxOS (dotaz přes `lux-engine` místo neexistujícího `pacman`).

### Změny
- Repozitáře a stažení LuxOS jsou na **https://luxos.lux-ai.cz** (`/repo/`, `/download/`); stará adresa `lsl.lux-ai.cz/luxos` dál funguje, převod starých konfigurací ji přepíše.
- `lux update` spouští po aktualizaci kroky ostatních balíků (`/usr/lib/lux/after-update.d`).
- `lsl` 0.10.6 v `[luxos-apps]`.
- `./build.sh one BALÍK` sestaví jeden balík do `out/single` (repozitář beze změny).

## 0.9.6 „Polaris“ – 2026-10-23 (beta)

### Nové
- LuxAI 1.0.0-10: režim správce – Nastavení › Oprávnění agenta › Příkazy správce (pokaždé heslo / bez hesla s potvrzením / bez hesla a bez ptaní; bez hesla jen model Flash). Tvrdé bloky (smazání systému, formátování disků, zavaděč, účty, sudo/polkit/PAM, podpisy balíků) platí vždy; záznam v `~/.local/state/luxai/root-commands.log` a `journalctl -t luxai-root`.

### Rychlost
- Často spouštěné programy horní lišty jsou v LSL místo bashe (`packages/luxos-desktop/files/lsl`, překládá `lslc` 0.10.5 při sestavení): baterie každých 20 s 9,6 ms → 1,6 ms bez procesu awk, název aplikace při každém přepnutí okna 7,4 ms → 1,5 ms, hodiny každé 3 s 1,7 ms → 1,4 ms, klik na Ovládací centrum a hodiny 4,5–5,3 ms → 1,0 ms, kontrola internetu přímo z NetworkManageru přes D-Bus (11,6 ms → 4,6 ms). Stejný výstup a překlady (TSV `luxos-i18n`); opraven neplatný markup `<`/`>` v názvu aplikace. Měření a plán dalších přepisů: `docs/perf/lsl-rewrite-plan.md`.

### Žádný pacman
- LuxOS už nemá ani konfiguraci pacmanu: správce balíků se nastavuje v `/etc/lux/lux.conf` ve vlastním formátu (`klíč hodnota`, bloky `repo NÁZEV` s odsazenými `server`/`mirrors`, `hold` místo `IgnorePkg`, `include /etc/lux/conf.d/*.conf`, nastavení `aur`, `flatpak`, `clean-keep` v témže souboru). Chyby hlásí soubor a řádek, `lux config check`/`edit`/`show`/`engine`. Konfiguraci jádra `/run/lux/engine.conf` generuje `lux-config` a nikdo ji neupravuje.
- Nová místa: databáze `/var/lib/lux`, cache `/var/cache/lux/pkg`, log `/var/log/lux.log`, klíčenka `/etc/lux/keyring`, hooky `/etc/lux/hooks`, zrcadla `/etc/lux/mirrorlist` (jedna adresa na řádek; `lux mirrors` a reflector.timer převádějí výstup reflectoru).
- Interní nástroje jádra se jmenují `lux-engine`, `lux-engine-key`, `lux-engine-conf`, `lux-engine-db-upgrade` (`/usr/lib/lux/alpm/bin`); žádný soubor `pacman*` v systému. Jádro zůstává libalpm z Arch Linuxu.
- Bez `pacman-contrib`, `pacman-mirrorlist` a `expac`: vlastní čištění cache (`lux clean`, LuxOS Care), kontrola aktualizací do dočasné kopie databáze (`lux_alpm.py check-updates`, Obchod, `lux doctor`), slučování `.pacnew`/`.pacsave` (`lux configs`) a seznam balíků pro TUI a Obchod.
- Přechod při aktualizaci: hook `00-lux-engine-migrate` přesune databázi, cache, klíčenku, hooky a log (přejmenováním, odolné vůči výpadku proudu), převede vlastní repozitáře a volby z `/etc/pacman.conf` a seřazená zrcadla; staré cesty zůstanou do restartu jako odkazy, pak je `lux` uklidí (kopie v `/var/lib/lux/migrated-from-pacman/`).

### Změny
- Proces relace `luxos-daemon` se jmenuje `luxos-hub` (Kalendář a Ovládací centrum na pozadí: `--background`); v textech LuxOS už není slovo „daemon“ (LuxDrop: „Avahi“). Po aktualizaci se nový název projeví po odhlášení a přihlášení.
- Balík `lsl` v `[luxos-apps]` je 0.10.5 (cíl `linux-x86_64-gnu`, moduly glib/gio/gtk, malé programy s ~136 kB paměti). Programy lišty startují pod 1 ms (baterie 0,94 ms, hodiny 0,73 ms, název aplikace 0,57 ms ve VM).

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
