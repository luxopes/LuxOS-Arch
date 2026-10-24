# lux – správce balíků LuxOS

`lux` je výchozí nástroj pro instalaci a aktualizace v LuxOS. Balíky z repozitářů LuxOS
a Arch Linuxu spravuje přímo přes **libalpm** (v Pythonu přes `pyalpm`), navíc umí AUR, Flatpak
a vlastní balíky `.lux`.

Příkaz `pacman` v LuxOS není a LuxOS nemá ani jeho konfiguraci (`/etc/pacman.conf`, `/etc/pacman.d`).
Jádro `lux` je balík **`lux-engine`**: libalpm a nástroje převzaté z pacmanu Arch Linuxu (sestavené
ze stejných zdrojů a součtů jako v Archu) – `makepkg`, `vercmp`, `repo-add` a hooky zůstávají,
interní nástroje se jmenují `lux-engine`, `lux-engine-key`, `lux-engine-conf`
a `lux-engine-db-upgrade` a jsou v `/usr/lib/lux/alpm/bin` mimo `PATH`. Kdo z Archu napíše
`pacman -Syu`, uvidí v shellu LuxOS místo „command not found“ odpovídající příkaz `lux`
(`pacman -Syu` → `lux update`, `pacman -S x` → `lux install x`, nápověda `/usr/lib/lux/pacman-hint`);
totéž `lux -Syu`.

## Soubory

| Cesta | Co to je |
|---|---|
| `/etc/lux/lux.conf` | konfigurace (formát níže) – repozitáře, podpisy, podržené balíky, nastavení `lux` |
| `/etc/lux/conf.d/*.conf` | další soubory ve stejném formátu (repozitáře přidané balíky nebo správcem) |
| `/etc/lux/mirrorlist` | zrcadla repozitářů Arch Linuxu, jedna adresa na řádek (`lux mirrors`) |
| `~/.config/lux/lux.conf` | vlastní nastavení `lux` pro uživatele (jen `aur`, `review-pkgbuild`, `flatpak`, `clean-keep`) |
| `/var/lib/lux/` | databáze balíků (`local/`, `sync/`), `installed/` = balíky `.lux` |
| `/var/cache/lux/pkg/` | stažené balíky (`lux clean` nechá `clean-keep` verzí) |
| `/var/log/lux.log` | záznam transakcí (`lux history`) |
| `/etc/lux/keyring/` | klíčenka GnuPG pro podpisy balíků (`lux fix` ji opraví) |
| `/etc/lux/hooks/` | vlastní hooky správce (`*.hook`, formát alpm-hooks) |
| `/run/lux/engine.conf` | **vygenerovaná** konfigurace jádra – neupravovat, vzniká z `lux.conf` |

## Konfigurace `/etc/lux/lux.conf`

Vlastní formát LuxOS: na každém řádku `klíč  hodnota` (oddělené mezerami), `#` začíná komentář do
konce řádku. Řádky odsazené mezerou nebo tabulátorem patří k řádku `repo NÁZEV` nad nimi. Po úpravě:
`lux config check` (nebo `lux config edit`, které soubor otevře a hned zkontroluje).

```
# LuxOS - konfigurace lux
architecture        auto
parallel-downloads  10
signatures          required          # required | optional | never
hold                linux-firmware    # podržet balík (lux update ho přeskočí)
aur                 on

repo luxos
    server  https://luxos.lux-ai.cz/repo/$repo/$arch

repo core
    mirrors  /etc/lux/mirrorlist

include  /etc/lux/conf.d/*.conf
```

### Globální klíče

| Klíč | Hodnota (výchozí) | Význam |
|---|---|---|
| `architecture` | `auto` | architektura balíků (`auto` = podle systému) |
| `parallel-downloads` | číslo ≥ 1 (`10`) | kolik souborů se stahuje najednou |
| `signatures` | `required` \| `optional` (`required`) | kontrola podpisů balíků a databází; `never` je povolené jen u místního repozitáře (`file://`) |
| `local-signatures` | `required` \| `optional` \| `never` (`optional`) | podpisy balíků instalovaných ze souboru (sestavení z AUR) |
| `hold` | názvy balíků (opakovatelný) | podržené balíky – `lux update` je neaktualizuje |
| `ignore-group` | názvy skupin (opakovatelný) | totéž pro celé skupiny balíků |
| `protect` | názvy balíků (`lux-engine glibc`) | balíky, u kterých se `lux remove` zeptá, i s `-y` je neodebere |
| `no-upgrade` | cesty bez `/` na začátku (opakovatelný) | soubory, které aktualizace nepřepíše (nová verze jako `.pacnew`) |
| `no-extract` | vzory cest (opakovatelný) | soubory, které se z balíků vůbec nerozbalí (např. `usr/share/doc/*`) |
| `color`, `candy`, `verbose-lists`, `check-space` | `on` \| `off` (`on`) | barvy, pruh ve stylu Pac-Mana, podrobné seznamy, kontrola místa na disku |
| `syslog` | `on` \| `off` (`off`) | záznam i do systémového deníku |
| `download-timeout` | `on` \| `off` (`on`) | `off` = čekat na pomalá zrcadla bez časového limitu |
| `download-user` | uživatel \| `none` (`alpm`) | pod kým se stahuje (bez práv roota) |
| `download-sandbox` | `on` \| `off` (`on`) | omezení procesu, který stahuje |
| `cache`, `hooks` | absolutní cesta (opakovatelný) | jiný adresář cache / hooků (výchozí `/var/cache/lux/pkg`, `/etc/lux/hooks`) |
| `database`, `log`, `keyring` | absolutní cesta | jiná databáze, log, klíčenka (výchozí viz *Soubory*) |
| `include` | cesta nebo vzor (`/etc/lux/conf.d/*.conf`) | načte další soubory ve stejném formátu |
| `aur` | `on` \| `off` (`on`) | balíky z AUR (sestavují se na tomto počítači) |
| `review-pkgbuild` | `on` \| `off` (`on`) | před sestavením z AUR nabídnout kontrolu skriptu |
| `flatpak` | `on` \| `off` (`on`) | `lux update` aktualizuje i aplikace Flatpak |
| `clean-keep` | číslo (`2`) | kolik verzí balíku nechá `lux clean` v cache |

### Repozitáře

`repo NÁZEV` začíná blok, odsazené řádky pod ním patří k repozitáři. Pořadí bloků je pořadí
hledání balíků (první repozitář, který balík má, vyhrává).

| Klíč v bloku | Hodnota | Význam |
|---|---|---|
| `server` | `https://…`, `http://…`, `ftp://…`, `file://…` (opakovatelný) | adresa repozitáře; `$repo` a `$arch` se doplní |
| `mirrors` | cesta k seznamu zrcadel (opakovatelný) | adresy ze souboru (např. `/etc/lux/mirrorlist`) |
| `signatures` | `required` \| `optional` \| `never` | jiná kontrola podpisů než globální (`never` jen pro `file://`) |
| `usage` | `sync search install upgrade all` | k čemu se repozitář používá (výchozí `all`) |

### Seznam zrcadel `/etc/lux/mirrorlist`

Jedna adresa na řádek, nejlepší první, `#` komentáře. Výchozí seznam je celosvětové zrcadlo
(`geo.mirror.pkgbuild.com` vybere nejbližší) a několik spolehlivých HTTPS zrcadel. `lux mirrors`
vybere nejrychlejší (`reflector`) a seznam přepíše; řádky `Server = …` z jiných nástrojů `lux` také
přečte, ale zapisuje jen adresy.

```
https://geo.mirror.pkgbuild.com/$repo/os/$arch
https://mirror.rackspace.com/archlinux/$repo/os/$arch
```

### Příklady

- **Přidat repozitář** – nový soubor `/etc/lux/conf.d/muj.conf`:
  ```
  repo muj
      server  https://example.org/$repo/$arch
  ```
  Klíč repozitáře naimportuje `lux-engine-key` (`sudo /usr/lib/lux/alpm/bin/lux-engine-key --recv-keys ID`
  a `--lsign-key ID`), pak `lux update`. Repozitář `multilib` (Steam) zapne
  `sudo /usr/lib/lux/lux-config enable-repo multilib`.
- **Podržet balík** na současné verzi: `hold  linux-firmware` (víc balíků na řádek nebo víc řádků).
- **Jiná zrcadla**: `lux mirrors`, nebo upravit `/etc/lux/mirrorlist` (jedna adresa na řádek).
- **Bez AUR**: `aur  off`; pro jednoho uživatele `~/.config/lux/lux.conf` s řádkem `aur off`.

### Chyby

Neznámý klíč, chybná hodnota nebo syntaxe pacman.conf (`[options]`, `Klíč = hodnota`) je chyba
s názvem souboru a číslem řádku, např.:

```
lux: error in the configuration: /etc/lux/lux.conf:12: unknown key 'paralel-downloads' (did you mean 'parallel-downloads'?)
lux: the package manager keeps using the last working configuration until this is fixed
```

S chybou `lux` (i Obchod a LuxOS Care) nic neinstaluje ani neaktualizuje, dokud se soubor neopraví.
Jádro (hooky, `makepkg`) zatím používá poslední funkční vygenerovanou konfiguraci
(`/var/lib/lux/engine.conf.last-good`). Další hlášení: `repository 'x' has no 'server' or 'mirrors'
line`, `mirror list … does not exist`, `mirror list … has no mirrors`, `'signatures never' is only
allowed for a local repository (file://)`, `repository 'x' is already defined at soubor:řádek`,
`indented line '…' does not belong to any 'repo' block`, `'server' belongs to a repository: indent it
under a 'repo NAME' line`.

### Jak to funguje

Jádro (libalpm a jeho nástroje) čte syntaxi INI, kterou nikdo nepíše ručně: `lux-config`
(`/usr/lib/lux/lux-config`, balík `lux-engine`) z `lux.conf`, vložených souborů a seznamů zrcadel
vygeneruje `/run/lux/engine.conf`. V hlavičce si pamatuje čas změny a velikost každého zdroje;
`lux`, `lux_alpm.py`, LuxOS Care, Obchod i nástroje v `/usr/lib/lux/alpm/bin` (spouštěcí skripty
před skutečnými programy v `/usr/lib/lux/alpm/libexec`) ji před spuštěním jádra ověří a při změně
vygenerují znovu. Uživatel bez práv k `/run/lux` dostane vlastní kopii v `$XDG_RUNTIME_DIR/lux/`.
Vygenerovanou konfiguraci ukáže `lux config engine`.

### Přechod z LuxOS 0.9.5 a starších (pacman)

Při aktualizaci na `lux-engine` 7.1.0.r9.g54d9411-3.2 hook `00-lux-engine-migrate` (běží ve stejné
transakci, první ze všech hooků) přesune `/var/lib/pacman` → `/var/lib/lux`, `/var/cache/pacman/pkg`
→ `/var/cache/lux/pkg`, `/etc/pacman.d/gnupg` → `/etc/lux/keyring`, `/etc/pacman.d/hooks` →
`/etc/lux/hooks` a `/var/log/pacman.log` → `/var/log/lux.log` (přejmenování na stejném souborovém
systému; na starých místech zůstanou do restartu odkazy pro ještě běžící starý proces).
Vlastní repozitáře a volby z `/etc/pacman.conf` (např. `[multilib]`, `IgnorePkg` → `hold`) převede do
`/etc/lux/lux.conf`, seřazená zrcadla z `/etc/pacman.d/mirrorlist` do `/etc/lux/mirrorlist`
a nastavení `lux` ze starého `lux.conf` (`AUR=0` …) zachová. Po restartu `lux` (jako root) uklidí
odkazy a staré soubory; kopie zůstanou v `/var/lib/lux/migrated-from-pacman/`. Ručně:
`sudo /usr/lib/lux/lux_alpm.py migrate --now`. Co nešlo převést (např. `XferCommand`), migrace vypíše.

## Nástroje jádra a služby

- `lux` a `lux_alpm.py` si `/usr/lib/lux/alpm/bin` přidají na začátek `PATH`; dědí ho hooky
  a skriptlety transakcí. Přes `sudo`/`pkexec` lux předá pevnou cestu
  `/usr/lib/lux/alpm/bin:/usr/local/sbin:/usr/local/bin:/usr/bin` (ne `PATH` uživatele).
- `makepkg`: `/etc/makepkg.conf.d/lux-engine.conf` (`PATH`, `PACMAN=/usr/lib/lux/alpm/bin/lux-engine`,
  `PACMAN_AUTH` se stejnou cestou pro `sudo`).
- `archlinux-keyring-wkd-sync` (z `archlinux-keyring`): drop-in `…/archlinux-keyring-wkd-sync.service.d/lux-engine.conf`
  (klíčenka `/etc/lux/keyring`). Globální `DefaultEnvironment` záměrně ne – `PATH` správce služeb
  dědí i relace uživatelů (LightDM).
- klíče z klíčenek (`archlinux-keyring`, `luxos-keyring`) načte hook `lux-engine-keyrings`
  (instalační skript `archlinux-keyring` hledá `/usr/bin/pacman-key`, který v LuxOS není).
- kontrola aktualizací a čištění cache jsou součástí `lux` (`lux_alpm.py check-updates`, `clean`),
  `pacman-contrib` LuxOS nepotřebuje.

`lux-engine` musí držet krok s `pacman` v Archu (`pyalpm` z Archu se sestavuje proti jeho
`libalpm.so`); `lux doctor` upozorní, když je Arch novější. Do té doby `lux` při nefunkčním `pyalpm`
sám přejde na záložní cestu níže. `lux-engine` nahrazuje `luxos-pacman` z LuxOS 0.9 (`replaces`):
`lux update` ho vymění sám.

## Příkazy

Úplný přehled je i v manuálové stránce `man lux` (soubor `lux.1`, musí odpovídat `lux --help`).
Poškozený balík v `/var/cache/lux/pkg` lux smaže sám a jednou stáhne znovu; když je poškozený i potom, hlásí
jméno balíku (`@@ERROR corrupt`).

| Příkaz | Co dělá | v pacmanu (Arch) |
|---|---|---|
| `lux` | interaktivní obchod v terminálu (Enter instalovat, Ctrl-R odebrat, Ctrl-U aktualizovat) | |
| `lux install <balík…>` | instalace z repozitářů → LuxOS (`.lux`) → AUR → Flathub; i soubor `.lux` nebo `.pkg.tar.zst`; už nainstalované přeskočí | `-S --needed`, `-U` |
| `lux remove <balík…>` | odebrání i s nepotřebnými závislostmi a zálohami konfigurace | `-Rns` |
| `lux update` (`upgrade`, `up`) | obnoví databáze, nejdřív podpisové klíče, pak celý systém; dál AUR, `.lux` a Flatpak | `-Sy` + `-Su` |
| `lux check` (`check-updates`) | dostupné aktualizace z čerstvých seznamů (dočasná kopie, bez roota, systém beze změny) | `checkupdates` |
| `lux search <výraz>` | hledání v repozitářích, LuxOS a AUR | `-Ss` |
| `lux info <balík>` | podrobnosti (nainstalovaný, jinak z repozitáře; LuxOS, AUR) | `-Qi` / `-Si` |
| `lux list [--installed]` | nainstalované balíky (i `.lux`) | `-Q` |
| `lux list --upgradable` | dostupné aktualizace podle posledního obnovení databází | `-Qu` |
| `lux list --explicit \| --aur \| --orphans \| --lux` | výslovně instalované / mimo repozitáře / nepotřebné / `.lux` | `-Qe` / `-Qm` / `-Qdt` |
| `lux reinstall <balík…>` | stejná verze znovu (z repozitáře, jinak z cache) | `-S`, `-U` |
| `lux autoremove` | odebere závislosti, které už nic nepotřebuje | `-Rns $(-Qdtq)` |
| `lux files <balík>` | soubory balíku | `-Ql` |
| `lux owns <soubor>` (`owner`) | kterému balíku soubor patří (i příkaz z `PATH`) | `-Qo` |
| `lux clean` | vyčistí cache (ponechá `clean-keep` verzí, odinstalované balíky smaže) a nabídne `autoremove` | `paccache -rk2`, `-ruk0` |
| `lux fix` | opraví zamčenou databázi (jen když žádný správce balíků neběží), smaže nedokončená stahování, obnoví podpisové klíče (`lux-engine-key --init/--populate`, `archlinux-keyring`, `luxos-keyring`) | |
| `lux configs` | projde nové konfigurační soubory z aktualizací (`.pacnew`, `.pacsave`): rozdíl, použít novou verzi, ponechat svou, upravit | `pacdiff` |
| `lux config [check\|show\|edit\|engine]` | kontrola, výpis, úprava `/etc/lux/lux.conf`; `engine` = vygenerovaná konfigurace jádra | |
| `lux history [počet] [balík]` | poslední změny balíků z `/var/log/lux.log` | |
| `lux mirrors` | nejrychlejší zrcadla (`reflector`) do `/etc/lux/mirrorlist` | |
| `lux drivers`, `lux doctor`, `lux pack` | ovladače, kontrola systému (i konfigurace), sestavení `.lux` | |

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
a bez `NO_COLOR`; přesměrovaný výstup je prostý text (`název verze`). Texty jsou
anglicky s překlady `luxos-i18n`.

Při výpadku sítě se stahování zopakuje (až 3×, bez nové otázky); Ctrl+C během instalace dokončí
rozdělaný balík a skončí bezpečně. Se Spořičem dat `lux` stahuje (spustil ho uživatel), jen před
otázkou připomene velikost stahování; automatické aktualizace na pozadí řeší LuxOS Care.

## Zálohy a záložní cesta

Transakce dělá `/usr/lib/lux/lux_alpm.py`. Když `pyalpm` chybí nebo neumí něco, co konfigurace jádra
používá, `lux` použije nástroj jádra `/usr/lib/lux/alpm/bin/lux-engine` se stejnými volbami.
Vynucení: `LUX_BACKEND=engine lux …`. Kontrola: `/usr/lib/lux/lux_alpm.py --verbose available`.

## Strojový režim (Obchod LuxOS, LuxOS Care)

`lux_alpm.py --machine -y PŘÍKAZ` (bez otázek jen s `-y`; bez něj skončí chybou `confirm`) píše
na stdout řádky `@@…` a navíc anglické řádky ve tvaru výstupu libalpm, které už čtou starší části systému:

| Řádek | Význam |
|---|---|
| `@@PLAN <akce> <počet> <stahování B> <změna na disku B>` | plán transakce (`install`, `upgrade`, `reinstall`, `remove`, `download`) |
| `@@PHASE <fáze>` | `refresh`, `download`, `verify`, `install`, `remove`, `hooks` |
| `@@PROGRESS <fáze> <procenta> [detail]` | průběh fáze (nejvýš 2× za sekundu + konec fáze) |
| `@@RETRY <pokus>` | stahování selhalo, další pokus (2, 3) |
| `@@SUMMARY <akce> <počet> <stahování> <změna> <sekundy>` | hotovo |
| `@@ERROR <druh> <věta>` | `locked`, `network`, `keyring`, `disk`, `conflict`, `pkgconflict`, `deps`, `corrupt`, `notfound`, `notinstalled`, `permission`, `confirm`, `cancelled`, `config` (chyba v `lux.conf`), `unknown` |
| `@@UNAVAILABLE <důvod>` | pyalpm nelze použít (návratový kód 3) – volající použije `lux-engine` |
| `@@DONE <kód>` | poslední řádek |

Řádky ve stylu libalpm: `Packages (N) …`, `<soubor> downloading...`,
`installing|upgrading|reinstalling|downgrading|removing <balík>...`,
`:: Running post-transaction hooks...`, `error: failed to … transaction (<chyba libalpm>)`,
`<balík>: <soubor> exists in filesystem` (konflikty – podle nich LuxOS Care uvolní záložní jádro).

Návratové kódy: 0 ok, 1 chyba, 2 špatné použití, 3 pyalpm nepoužitelné, 130 přerušeno.
