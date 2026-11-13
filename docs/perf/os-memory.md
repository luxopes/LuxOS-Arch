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
