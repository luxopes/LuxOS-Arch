# Pamet LuxOS Companion

Mereno 2026-11-11, Python 3.14.10, Linux/glibc. Vychozi zdroje: `6baac50`,
`luxos-companion 1.0.0-5`; optimalizovany balik: `1.0.0-6`.

## Zmeny

- Kalendarovy modul, ctec i zapisovac vznikaji az pri pouziti kalendare.
  Bluetooth handshake, poloha a dotazy na stav je nepotrebuji.
- Po odpojeni posledniho telefonu se zahodi rozparsovane kalendare. Dalsi pozadavek
  je znovu nacte z disku, vcetne zmen provedenych mezitim na pocitaci.
- Po uvolneni kalendarove cache probehne GC a na glibc `malloc_trim(0)`.
  Samotne zahozeni objektu nestacilo: alokator si ponechaval vetsinu volnych stranek.
  [malloc_trim](https://man7.org/linux/man-pages/man3/malloc_trim.3.html) vraci volne
  stranky haldy systemu; zive objekty zachovava. Bez teto funkce se cache uvolni
  bez trimovani. Pri beznem Bluetooth/poloze se ctypes nenacita ani GC nevynucuje.
- Pamet deduplikace zapisu se zachovava, vcetne pripadu neuspesneho zapisu jejiho
  souboru. Automaticky start, registrace BlueZ, prednacteni schopnosti LuxAI,
  protokol, opravneni a D-Bus rozhrani zustavaji zachovane.

## Mereni

Median tri stridanych spusteni obou verzi, kazde v novem procesu a docasnych XDG
slozkach. Metrika PSS, nikoli soucet RSS. Zadne skutecne uzivatelske kalendare,
Bluetooth ani existujici sluzba se pri benchmarku nepouzivaji.

| Stav benchmarku | Pred zmenou (MiB PSS) | Po zmene (MiB PSS) |
|---|---:|---:|
| Inicializovana sluzba bez telefonu | 20,39 | 17,40 |
| Nacteny kalendar | 55,44 | 55,27 |
| Telefon odpojen | 55,44 | 22,39 |

Kalendar v testu ma 4000 udalosti s popisem 4096 znaku. Uspora 33 MiB po
odpojeni se vztahuje k tomuto syntetickemu vstupu, ne ke kazdemu kalendari.
Absolutni hodnoty zahrnuji take Python moduly mericiho skriptu; nejsou totozne
s hodnotami produkcni sluzby. Pri aktivnim spojeni se kalendarova cache zachovava.

Opakovani z `packages/luxos-companion` (puvodni adresar `files` uchovat mimo repo
pred zmenou):

```sh
python3 -B tests/measure_memory.py --files /cesta/k/puvodnim/files
python3 -B tests/measure_memory.py
```

## Overeni

- 124 testu protokolu, kalendare, polohy, LuxAI, schvalovani a D-Bus/BlueZ na
  soukrome sbernici; zahrnuji restart BlueZ, predani socketu a odmitani ciziho volajiciho.
- Nove regrese: handshake bez importu kalendare, uvolneni cache a aktualni data po
  dalsim pripojeni, zachovani cache pro druhy telefon, deduplikace po odpojeni a
  chovani bez dostupneho `malloc_trim`.
- 3 testy okna Telefon pod Xvfb a soukromou sbernici D-Bus prosly.
- Sestaveni baliku pres makepkg; testy spusteny zvlast, build s `--nocheck --nodeps`.
- Fyzicky telefon ani zatez celeho OS ve 4GB VM timto overenim pokryte nejsou.
  Bezici instalace nebyla nahrazena ani restartovana.
