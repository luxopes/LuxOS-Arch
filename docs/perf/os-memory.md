# RAM celeho LuxOS a rezervy jadra

Overeno 2026-11-11. Tri MiB usetrene v Companion nejsou resenim spotreby celeho
OS. Puvodni hodnota `free` kolem 2,5 GiB byla z pracovniho pocitace s aplikacemi,
nikoli z ciste relace LuxOS. Soucty RSS navic opakovane zapocitavaly knihovny.

## Co se zmenilo

`luxos-tweaks 1.0.0-14` vraci `vm.watermark_scale_factor` ze 125 na vychozich 10.
Zadna sluzba, automaticke pripojovani ani graficka funkce se kvuli tomu nevypina.
Zram a earlyoom zustavaji nastavene stejne.

Hodnota ridi vzdalenost mezi prahy pro probouzeni a uspavani kswapd. Vyssi hodnota
je vhodna az pri dolozenych problemech s direct reclaim, nikoli automaticky pro
vsechny stroje. Viz [dokumentace jadra](https://docs.kernel.org/admin-guide/sysctl/vm.html#watermark-scale-factor).

## Rozdil mezi obsazenou RAM a rezervou

`free` pocita pouzitou pamet jako `MemTotal - MemAvailable`. Odhad MemAvailable
odecita od fyzicky volne pameti rezervy jadra a ponechava cast cache. Viz
[si_mem_available](https://github.com/torvalds/linux/blob/master/mm/show_mem.c).
Vyssi watermarks proto zhorsuji i toto cislo, prestoze procesy zadnou dalsi
pamet nealokovaly. Zmena rezerv neni uvolneni pameti procesu.

Na pracovnim stroji s 15,0 GiB pouzitelne RAM model z `/proc/zoneinfo` a
`/proc/meminfo` reprodukoval MemAvailable s presnosti pod 1 MiB. Pri prahove
vzdalenosti odpovidajici hodnote 10 by odhad dostupne pameti stoupl asi o
525 MiB. Na tomto stroji se sysctl nemenilo; jde o vypocet, ne merenou uspornost
aplikaci. Ostatni procesy po vylouceni stromu Claude, Codexu a Terminalu mely
kolem 800 MiB PSS. Toto cislo nezahrnuje jadro a nelze ho primo scitat s
MemTotal-MemAvailable: tyto metriky zachazeji jinak se sdilenymi mapovanimi/cache.

## Overeni v izolovane 4GB VM

KVM, 4096 MiB (3903 MiB MemTotal), dva procesory, standardni VGA, sit odpojena.
Zapis pouze do noveho qcow2 overlay nad existujicim testovacim diskem; puvodni
disk ani pracovni instalace se nemenily. Testovaci obraz ma kernel
`7.2.13-1-luxos`, desktop `1.1.0-59`, tweaks `1.0.0-10` (nejde o nove sestavene
aktualni ISO). Pri srovnani se menil pouze watermark_scale_factor.

Po prihlaseni, zavreni uvodniho okna a Firefoxu, bez restartu nebo vyprazdnovani cache:

| Hodnota | Pouzita RAM dle free (MiB) | Fyzicky volna RAM (MiB) | AnonPages (MiB) |
|---|---:|---:|---:|
| 125 | 991,4 | 2763,1 | 414,7 |
| 10 | 894,8 | 2763,1 | 414,8 |
| 125, opakovani | 991,4 | 2763,1 | 414,8 |
| 10, opakovani | 894,8 | 2763,1 | 414,8 |

Stejny desktop je tedy pod 1 GiB v obou nastavenich. Rozdil rezerv je 96,6 MiB.

## Pametovy tlak a odezva

Desktop + uvodni okno + Firefox s prazdnou kartou + dalsich 2600 MiB nahodnych
dat v mmap (zamerne spatne komprimovatelnych). Deset roundtripu `xprop` pres
runuser v kazdem behu. Nejde o test skutecnych webovych stranek nebo her.

| Poradi | Faktor | Dostupna RAM pod zatezi (MiB) | Median odezvy X (ms) | Allocstall | PSI full (ms) |
|---|---:|---:|---:|---:|---:|
| A/B, prvni | 125 | 246,0 | 46,32 | 0 | 97,2 |
| A/B, druhy | 10 | 318,3 | 43,19 | 0 | 0,0 |
| B/A, prvni | 10 | 323,5 | 45,61 | 0 | 0,0 |
| B/A, druhy | 125 | 243,3 | 43,98 | 0 | 11,8 |

V tomto testu zmena nezpusobila zamrznuti plochy ani ukonceni aplikaci OOM.
Swap vyuzity asi 0,2 MiB. Cisla nejsou zarukou pro libovolnou aplikaci ani
dukazem zrychleni X; ukazuji vice dostupne pameti bez pozorovaneho zhorseni
odezvy pri tomto zatizeni. Oba smery poradi omezuji vliv zahrati cache.

Opakovani (jen root v docasne 4GB VM, skript po dokonceni obnovi puvodni sysctl):

```sh
python3 /tmp/watermark-probe.py test 2600 125 10
python3 /tmp/watermark-probe.py test 2600 10 125
```

Zdroj skriptu: `scripts/perf/watermark-probe.py`. Overen take guard proti spusteni
na pracovnim pocitaci, syntaxe PKGBUILD, sestaveni baliku a existujici testy
ochrany earlyoom. Plne chovani vsech aplikaci ani realny 4GB notebook se tim
nepovazuji za otestovane.

## Cista relace ve 4GB VM: co zabira pamet a co se zmenilo (2026-11-13)

Mereni: KVM, 4096 MiB (3903 MiB MemTotal), 4 vCPU, VGA, sit pres NAT. Testovaci disk
`out/fwtest/base.qcow2` aktualizovany ze staging (kernel `7.3.3-1-luxos`) + baliky z `main`
(`luxos-desktop` 64, `luxos-tweaks` 14 tj. watermark 10, `luxos-companion` 6, `luxos-i18n` 71);
kazde mereni na novem qcow2 overlay (cisty stav), uvodni okna (Vitejte, Co je noveho) uz videna.
Po startu greeter, prihlaseni klavesnici, 2 min a 6 min klidu, pak `scripts/perf/mem-snapshot.py`
(PSS/USS ze `smaps_rollup`, meminfo, slab, tmpfs, zram). Dva behy pred zmenou a dva po ni.

| Hodnota (MiB) | pred (2 behy) | po (2 behy) | rozdil |
|---|---:|---:|---:|
| `free` pouzito (MemTotal - MemAvailable), 2 min | 822,3 / 812,0 | 790,1 / 803,9 | -20,1 |
| `free` pouzito, 6 min | 796,7 / 795,7 | 766,1 / 775,3 | -25,5 |
| AnonPages, 2 min | 402,2 / 402,3 | 386,6 / 386,7 | -15,6 |
| Soucet PSS procesu uzivatele, 2 min | 419,9 / 418,8 | 400,9 / 400,7 | -18,6 |
| Soucet PSS systemovych procesu, 2 min | 162,6 / 163,1 | 165,8 / 166,1 | +3,1 |
| Slab (z toho neuvolnitelny ~59) | 81,6 / 81,1 | 83,7 / 84,5 | +2,8 |

Systemova cast a slab nejsou ovlivnene zmenou (`luxos-guard service` +2,3 MiB a btrfs inody: obraz
"po" mel navic instalaci baliku). Jadro mimo procesy (slab, tabulky stranek, zasobniky, rezervy) je
v cisle `free` asi 200 MiB. zram prazdny, tmpfs < 1 MiB, swap 0.

Nejvetsi procesy (PSS MiB, prumer dvou behu, 2 min po prihlaseni):

| Proces | pred | po | Poznamka |
|---|---:|---:|---|
| Xorg | 65,2 | 65,0 | VGA + glamor/llvmpipe ve VM |
| xfwm4 | 46,1 | 46,2 | kompozitor (GLX); xpresent by sel bez Mesa, ale riskuje trhani obrazu |
| luxos-hub | 31,2 | 24,3 | Emoji a symboly az pri prvnim pouziti (viz nize) |
| xfdesktop | 28,2 | 28,1 | tapeta + ikony plochy |
| tumblerd | 28,1 | 28,1 | spusti ho xfdesktop pri startu (nahledy ikon na plose), sam konci po 5 min necinnosti; po 6 min uz nebezi |
| xkb plugin listy (wrapper) | 23,3 | 23,3 | rozlozeni klavesnice |
| plank + bamfdaemon | 31,9 | 31,9 | Dock |
| nm-applet | 18,3 | 18,1 | ikona site a agent hesel Wi-Fi |
| xfce4-panel + whisker/pulseaudio/oznameni (wrapper) | 62,4 | 62,5 | pluginy s nabidkou zustavaji externi (luxos-menubar je rozlisuje podle X klienta) |
| luxos-guard service (Python, root) | 14,3 | 16,6 | beze zmeny |
| luxos-guard-agent | 12,1 | 0,5 | Python -> LSL (viz nize) |
| polkit-gnome, xfsettingsd, xfce4-session, screensaver, power-manager, Thunar --daemon | 77,0 | 76,9 | potrebne: overeni, nastaveni, zamykani, baterie, pripojovani USB |

Zmeny:

- `luxos-guard 1.0.0-7`: pomocnik v sezeni je program v LSL (`docs/perf/lsl-rewrite-plan.md`, kapitola 7);
  Python bezi jen na chvili pri udalosti. -11,6 MiB PSS v kazde relaci.
- `luxos-desktop 1.1.0-65`: `luxos-hub` uz predem nestavi okno Emoji a symboly (data CLDR a okno);
  vznikne pri prvnim Super+. a pak zustane. -6,9 MiB PSS (s otevrenym oknem hub +9,6 MiB). Prvni
  otevreni ve VM 0,57 s, dalsi 0,1-0,15 s jako dosud (xdotool --sync, vcetne jeho rezie). Ovladaci centrum, Kalendar a Snimek obrazovky zustavaji pripravene predem
  (Ovladaci centrum je prvni okno GTK v hubu, snimek musi byt okamzity, Kalendar stoji jen ~1,2 MB).
- Watermark (`luxos-tweaks` 14) a Companion (`luxos-companion` 6) jsou v `main` od drivejska, staging
  mel jeste `luxos-tweaks` 13 a `luxos-companion` 5. Ve VM s 4 GB dela watermark ~97 MiB (viz vyse),
  na pocitaci s 16 GB vic: vypocet ze `/proc/zoneinfo` pracovniho pocitace (Normal 12,2 GB, DMA32 3,1 GB)
  dava soucet rezerv (high watermark + lowmem_reserve) 556 MiB pri hodnote 125 a ~207 MiB pri 10, a odhad
  MemAvailable navic odecita mensi `low` watermark od cache; celkem asi 0,5-0,6 GiB mene "pouzite" pameti
  v `free` hned po instalaci balicku (pracovni pocitac ma stale 125, tedy `luxos-tweaks` < 14).

Proc majitel vidi ~1,94 GiB a VM ~0,8 GiB: watermark (~0,55 GiB na 16 GB), ovladace dvou grafik
(amdgpu + nvidia: VmallocUsed 185 MiB, pamet jadra pro GPU), vetsi rozliseni (tapeta, kompozitor,
Xorg) a vic jader (per-CPU struktury). Procesy relace LuxOS na pracovnim pocitaci (cteni `smaps_rollup`,
bez zmen; vcetne casti ve swapu, protoze stroj odklada): luxos-hub 29 + 15 MiB swap, xfce4-panel 27,
xkb plugin 25, xfdesktop 20, plank 19, xfwm4 19, nm-applet 15, luxos-guard-agent 3 + 7 swap,
luxos-companion 2 + 15 swap (telefon schvaleny), luxdrop prijem 3 + 23 swap (zapnuty v nastaveni),
luxos-mail-service 19 (ucty posty). Zbytek "pouzite" pameti tam tvori aplikace (Firefox, Chromium,
terminaly, kontejnery), ne LuxOS.

Zkoumane a ponechane (funkce nebo rychlost by utrpely, nebo zisk nebyl doloziteny):
tumblerd (nahledy na plose; konci sam), Thunar --daemon (pripojovani USB, okamzite okno Souboru),
pluginy listy uvnitr panelu (prepinani nabidek jednim klikem), nm-applet (hesla Wi-Fi), xfwm4 vblank
(trhani obrazu na nekterych ovladacich), journald (uz 200M/64M), Companion jen s telefonem (prvni
parovani by vyzadovalo spusteni z okna Telefon; pro majitele nic, telefon ma schvaleny).

Start a prihlaseni (systemd-analyze; okno plank od startu xfce4-session): pred 15,8 s / 15,3 s a
6,8 s / 4,4 s, po 15,3 s / 16,5 s a 3,5 s / 3,7 s. Rozptyl VM je vetsi nez rozdil; zhorseni nepozorovano.

Opakovani: `scripts/perf/mem-snapshot.py OUT.json` jako root ve VM (`scripts/vmctl.py put` + `exec`),
login a klid jako ve `scripts/perf/vm-measure.sh`.
