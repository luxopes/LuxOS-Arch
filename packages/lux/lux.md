# lux – správce balíků LuxOS

`lux` je výchozí nástroj pro instalaci a aktualizace v LuxOS. Balíky z repozitářů LuxOS
a Arch Linuxu spravuje přímo přes **libalpm** (knihovnu pacmanu, v Pythonu přes `pyalpm`), navíc umí
AUR, Flatpak a vlastní balíky `.lux`.

Příkaz `pacman` v LuxOS není. Jádro `lux` je balík **`lux-engine`**: libalpm a nástroje pacmanu
z Arch Linuxu (sestavené ze stejných zdrojů a součtů jako v Archu) – `makepkg`, `vercmp`, `repo-add`,
hooky a konfigurace zůstávají, interní nástroje `pacman`, `pacman-key`, `pacman-conf`
a `pacman-db-upgrade` jsou v `/usr/lib/lux/alpm/bin` mimo `PATH` (bez manuálových stránek
a doplňování). Kdo z Archu napíše `pacman -Syu`, uvidí v shellu LuxOS místo „command not found“
i odpovídající příkaz `lux` (`pacman -Syu` → `lux update`, `pacman -S x` → `lux install x`,
nápověda `/usr/lib/lux/pacman-hint`); totéž `lux -Syu`.

Nástroje jádra dostanou ti, kdo je potřebují:

- `lux` a `lux_alpm.py` si `/usr/lib/lux/alpm/bin` přidají na začátek `PATH`; dědí ho hooky
  a skriptlety transakcí. Přes `sudo`/`pkexec` lux předá pevnou cestu
  `/usr/lib/lux/alpm/bin:/usr/local/sbin:/usr/local/bin:/usr/bin` (ne `PATH` uživatele).
- `makepkg`: `/etc/makepkg.conf.d/lux-engine.conf` (`PATH`, `PACMAN`, `PACMAN_AUTH` se stejnou cestou
  pro `sudo`).
- služby z `pacman-contrib` a `archlinux-keyring` (`paccache`, `pacman-filesdb-refresh`,
  `archlinux-keyring-wkd-sync`): drop-iny `/usr/lib/systemd/system/<služba>.service.d/lux-engine.conf`.
  Globální `DefaultEnvironment` záměrně ne – `PATH` správce služeb dědí i relace uživatelů (LightDM).
- nástroje LuxOS (Obchod, LuxOS Care, Ovladače, tisk, instalátor, sandbox) si cestu nastaví samy.
- klíče z klíčenek (`archlinux-keyring`, `luxos-keyring`) načte hook `lux-engine-keyrings`
  (instalační skript `archlinux-keyring` hledá `/usr/bin/pacman-key`, který v LuxOS není).

`lux` používá databázi `/var/lib/pacman`, `/etc/pacman.conf` (načtený přes `pacman-conf`, tedy
včetně `Include`), ověřování podpisů, cache a hooky jako pacman v Arch Linuxu.

`lux-engine` musí držet krok s `pacman` v Archu (`pyalpm` z Archu se sestavuje proti jeho
`libalpm.so`); `lux doctor` upozorní, když je Arch novější. Do té doby `lux` při nefunkčním `pyalpm`
sám přejde na záložní cestu níže. `lux-engine` nahrazuje `luxos-pacman` z LuxOS 0.9 (`replaces`):
`lux update` ho vymění sám.

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
| `lux configs` | porovná a sloučí nové konfigurační soubory z aktualizací (`.pacnew`, `.pacsave`) | `pacdiff` |
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
používá (např. `XferCommand`, `HookDir` s hooky), `lux` použije pacman z jádra
(`/usr/lib/lux/alpm/bin/pacman`) se stejnými volbami.
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
