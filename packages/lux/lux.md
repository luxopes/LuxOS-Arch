# lux – správce balíků LuxOS

`lux` je výchozí nástroj pro instalaci a aktualizace v LuxOS. Balíky z repozitářů LuxOS
a Arch Linuxu spravuje přímo přes **libalpm** (knihovnu pacmanu, v Pythonu přes `pyalpm`), navíc umí
AUR, Flatpak a vlastní balíky `.lux`.

Pacman z Arch Linuxu je v systému dál (balík `luxos-pacman`: libalpm, makepkg, `pacman-key`,
`pacman-conf`, hooky), skutečný program je ale `/usr/lib/lux/alpm/pacman`. Příkaz `pacman` je
kompatibilní vrstva: skripty, hooky, služby, `makepkg`, `pacstrap`, `lux` a AUR pomocníci (`yay`,
`paru`…) dostanou skutečný pacman beze změny; člověk v terminálu místo toho uvidí odpovídající příkaz
`lux` (např. `pacman -Syu` → `lux update`, `pacman -S x` → `lux install x`) a návratový kód 1.

Pro pokročilé zůstává pacman dostupný:

- jednorázově: `LUX_ALLOW_PACMAN=1 pacman …`, s právy správce `sudo LUX_ALLOW_PACMAN=1 pacman …`
  (`sudo` proměnné z prostředí nepředává, proto až za `sudo`),
- přímo: `sudo /usr/lib/lux/alpm/pacman …`,
- trvale pro celý systém: `sudo touch /etc/lux/allow-pacman` (zrušení: smazat soubor).

`lux` i `pacman` používají stejnou databázi `/var/lib/pacman`, stejný `/etc/pacman.conf`
(načtený přes `pacman-conf`, tedy včetně `Include`), stejné ověřování podpisů, cache a hooky.
Balík nainstalovaný jedním nástrojem druhý normálně vidí, aktualizuje i odebere.

`luxos-pacman` je sestavený ze stejných zdrojů jako `pacman` v Archu a musí s ním držet krok
(`pyalpm` z Archu se sestavuje proti jeho `libalpm.so`); `lux doctor` upozorní, když je pacman
v Archu novější. Do té doby `lux` při nefunkčním `pyalpm` sám přejde na záložní cestu níže.

## Příkazy

| Příkaz | Co dělá | pacman |
|---|---|---|
| `lux` | interaktivní obchod v terminálu (Enter instalovat, Ctrl-R odebrat, Ctrl-U aktualizovat) | |
| `lux install <balík…>` | instalace z repozitářů → LuxOS (`.lux`) → AUR → Flathub; i soubor `.lux` nebo `.pkg.tar.zst`; už nainstalované přeskočí | `-S --needed`, `-U` |
| `lux remove <balík…>` | odebrání i s nepotřebnými závislostmi a zálohami konfigurace | `-Rns` |
| `lux update` (`upgrade`, `up`) | obnoví databáze, nejdřív podpisové klíče, pak celý systém; dál AUR, `.lux` a Flatpak | `-Sy` + `-Su` |
| `lux search <výraz>` | hledání v repozitářích, LuxOS a AUR | `-Ss` |
| `lux info <balík>` | podrobnosti (nainstalovaný, jinak z repozitáře; LuxOS, AUR) | `-Qi` / `-Si` |
| `lux list [--installed]` | nainstalované balíky (i `.lux`) | `-Q` |
| `lux list --upgradable` | dostupné aktualizace podle posledního obnovení databází | `-Qu` |
| `lux list --explicit \| --aur \| --orphans \| --lux` | výslovně instalované / mimo repozitáře / nepotřebné / `.lux` | `-Qe` / `-Qm` / `-Qdt` |
| `lux reinstall <balík…>` | stejná verze znovu (z repozitáře, jinak z cache) | `-S`, `-U` |
| `lux autoremove` | odebere závislosti, které už nic nepotřebuje | `-Rns $(pacman -Qdtq)` |
| `lux files <balík>` | soubory balíku | `-Ql` |
| `lux owns <soubor>` (`owner`) | kterému balíku soubor patří (i příkaz z `PATH`) | `-Qo` |
| `lux clean` | vyčistí cache (ponechá `CLEAN_KEEP` verzí) a nabídne `autoremove` | `paccache` |
| `lux fix` | opraví zamčenou databázi (jen když žádný správce balíků neběží), smaže nedokončená stahování, obnoví podpisové klíče (`pacman-key --init/--populate`, `archlinux-keyring`, `luxos-keyring`) | |
| `lux history [počet] [balík]` | poslední změny balíků z `pacman.log` | |
| `lux drivers`, `lux mirrors`, `lux doctor`, `lux pack` | ovladače, rychlá zrcadla, kontrola systému, sestavení `.lux` | |

Volby: `-y` (bez otázek – jinak se `lux` vždy zeptá), `-v`/`--verbose` (seznam balíků, výstup skriptů
a surové chyby libalpm), `--repo`, `--aur`. Práva správce si `lux` vyžádá sám: v terminálu `sudo`,
v grafické relaci bez terminálu `pkexec`.

## Výstup

```
Install 3 packages (73 MB download, +259 MB disk)? [Y/n]
✓ Downloading ████████████████████ 100%  73 MB / 73 MB · 9.1 MB/s
✓ Verifying   ████████████████████ 100%
✓ Installing  ████████████████████ 100%  3/3 firefox
✓ Installed firefox 131.0-1 (+2 deps) in 8.2 s
```

Jedna řádka na fázi (obnovení databází, stahování, ověření, instalace/odebrání, hooky), chyby
srozumitelně jednou větou (zamčená databáze → `lux fix`, síť, podpisy, místo na disku, konflikt
souborů, nesplnitelné závislosti); syrové detaily jen s `--verbose`. Barvy a pruhy jen na terminálu
a bez `NO_COLOR`; přesměrovaný výstup je prostý text (`název verze` jako u `pacman -Q`). Texty jsou
anglicky s překlady `luxos-i18n`.

Při výpadku sítě se stahování zopakuje (až 3×, bez nové otázky); Ctrl+C během instalace dokončí
rozdělaný balík a skončí bezpečně. Se Spořičem dat `lux` stahuje (spustil ho uživatel), jen před
otázkou připomene velikost stahování; automatické aktualizace na pozadí řeší LuxOS Care.

## Zálohy a záložní cesta

Transakce dělá `/usr/lib/lux/lux_alpm.py`. Když `pyalpm` chybí nebo neumí něco, co `pacman.conf`
používá (např. `XferCommand`, `HookDir` s hooky), `lux` použije skutečný pacman
(`/usr/lib/lux/alpm/pacman`, ne kompatibilní vrstvu) se stejnými volbami.
Vynucení: `LUX_BACKEND=pacman lux …`. Kontrola: `/usr/lib/lux/lux_alpm.py --verbose available`.

## Strojový režim (Obchod LuxOS, LuxOS Care)

`lux_alpm.py --machine -y PŘÍKAZ` (bez otázek jen s `-y`; bez něj skončí chybou `confirm`) píše
na stdout řádky `@@…` a navíc anglické řádky ve tvaru pacmanu, které už čtou starší části systému:

| Řádek | Význam |
|---|---|
| `@@PLAN <akce> <počet> <stahování B> <změna na disku B>` | plán transakce (`install`, `upgrade`, `reinstall`, `remove`, `download`) |
| `@@PHASE <fáze>` | `refresh`, `download`, `verify`, `install`, `remove`, `hooks` |
| `@@PROGRESS <fáze> <procenta> [detail]` | průběh fáze (nejvýš 2× za sekundu + konec fáze) |
| `@@RETRY <pokus>` | stahování selhalo, další pokus (2, 3) |
| `@@SUMMARY <akce> <počet> <stahování> <změna> <sekundy>` | hotovo |
| `@@ERROR <druh> <věta>` | `locked`, `network`, `keyring`, `disk`, `conflict`, `pkgconflict`, `deps`, `corrupt`, `notfound`, `notinstalled`, `permission`, `confirm`, `cancelled`, `unknown` |
| `@@UNAVAILABLE <důvod>` | pyalpm nelze použít (návratový kód 3) – volající použije pacman |
| `@@DONE <kód>` | poslední řádek |

Řádky ve stylu pacmanu: `Packages (N) …`, `<soubor> downloading...`,
`installing|upgrading|reinstalling|downgrading|removing <balík>...`,
`:: Running post-transaction hooks...`, `error: failed to … transaction (<chyba libalpm>)`,
`<balík>: <soubor> exists in filesystem` (konflikty – podle nich LuxOS Care uvolní záložní jádro).

Návratové kódy: 0 ok, 1 chyba, 2 špatné použití, 3 pyalpm nepoužitelné, 130 přerušeno.
