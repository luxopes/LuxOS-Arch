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
| `/etc/lux/lux.conf` | konfigurace (TOML, popis níže) – repozitáře, podpisy, podržené balíky, nastavení `lux` |
| `/etc/lux/conf.d/*.conf` | další soubory ve stejném formátu (repozitáře přidané balíky nebo správcem) |
| `/etc/lux/lux.conf.old-format` | původní soubor ve formátu LuxOS 0.9 po převodu (`lux config migrate`) |
| `/etc/lux/mirrorlist` | zrcadla repozitářů Arch Linuxu, jedna adresa na řádek (`lux mirrors`) |
| `~/.config/lux/lux.conf` | vlastní nastavení `lux` pro uživatele (jen `[packages]` `aur`, `review_pkgbuild`, `flatpak`, `cache_keep`) |
| `/var/lib/lux/` | databáze balíků (`local/`, `sync/`), `installed/` = balíky `.lux` |
| `/var/cache/lux/pkg/` | stažené balíky (`lux clean` nechá `cache_keep` verzí) |
| `/var/log/lux.log` | záznam transakcí (`lux history`) |
| `/etc/lux/keyring/` | klíčenka GnuPG pro podpisy balíků (`lux fix` ji opraví) |
| `/etc/lux/hooks/` | vlastní hooky správce (`*.hook`, formát alpm-hooks) |
| `/run/lux/engine.conf` | **vygenerovaná** konfigurace nástrojů jádra v C – neupravovat, vzniká z `lux.conf` |

## Konfigurace `/etc/lux/lux.conf`

Od LuxOS 1.0 je `lux.conf` soubor **TOML**: tabulky `[general]`, `[downloads]`, `[security]`,
`[packages]`, `[paths]`, jedna tabulka `[repo.NÁZEV]` na repozitář a `[include]`; v nich řádky
`klíč = hodnota`. Text je v uvozovkách (`"auto"`), přepínače `true`/`false`, čísla bez uvozovek,
seznamy `["a", "b"]` (smějí být na více řádcích, i s komentáři). `#` začíná komentář do konce řádku.
Soubor čte přímo `lux` (modul `lux_config` z `lux-engine`, parser TOML ze standardní knihovny
Pythonu). Po úpravě: `lux config check` (nebo `lux config edit`, které soubor otevře a hned
zkontroluje).

```toml
# LuxOS Package Manager
# Configuration: /etc/lux/lux.conf

[general]
architecture = "auto"
color = true
candy = true
verbose = true
# updates: "stable" (releases) | "staging" (test builds before a release - for testers)
channel = "stable"

[downloads]
parallel = 10
check_space = true
user = "alpm"

[security]
signatures = "required"
local_signatures = "optional"
protect = ["lux-engine", "glibc"]

[packages]
aur = true
review_pkgbuild = true
flatpak = true
cache_keep = 2
hold = ["linux-firmware"]        # podržet balík (lux update ho přeskočí)

# ── LuxOS repositories ────────────────────────

[repo.luxos]
server = "https://luxos.lux-ai.cz/repo/$repo/$arch"

# ── Arch Linux repositories ───────────────────

[repo.core]
mirrors = "/etc/lux/mirrorlist"

# ── Additional configuration ──────────────────

[include]
files = ["/etc/lux/conf.d/*.conf"]
```

Proč `[include]` a ne samotné `include = …` na konci: v TOML patří každý řádek `klíč = hodnota`
do tabulky nad ním, takže `include` pod `[repo.extra]` by byl klíč repozitáře `extra`. Samotné
`include = …` je možné jen na začátku souboru (před první tabulkou). `lux` ho najde i pod
repozitářem (a použije), ale `lux config check` napíše varování.

### Klíče

| Tabulka | Klíč | Hodnota (výchozí) | Význam |
|---|---|---|---|
| `[general]` | `architecture` | text nebo seznam (`"auto"`) | architektura balíků (`auto` = podle systému) |
| | `color`, `candy`, `verbose` | `true` \| `false` (`true`) | barvy, pruh ve stylu Pac-Mana, podrobné seznamy |
| | `syslog` | `true` \| `false` (`false`) | záznam i do systémového deníku |
| | `channel` | `"stable"` \| `"staging"` (`"stable"`) | kanál aktualizací: ve `"staging"` (testovací sestavení před vydáním, pro testery) se adresy začínající `https://luxos.lux-ai.cz/repo/` čtou z `https://luxos.lux-ai.cz/staging/` (repozitáře LuxOS, balíky `.lux`, ikony Obchodu); soubor se nemění, Arch a vlastní repozitáře beze změny. Přepnutí: `updates.channel` v `system.lsl` + `sudo lux system apply`, nebo `lux-config set-channel`; `lux config check` ho ukáže |
| `[downloads]` | `parallel` | číslo ≥ 1 (`10`) | kolik souborů se stahuje najednou |
| | `check_space` | `true` \| `false` (`true`) | kontrola místa na disku |
| | `user` | uživatel \| `"none"` (`"alpm"`) | pod kým se stahuje (bez práv roota) |
| | `timeout` | `true` \| `false` (`true`) | `false` = čekat na pomalá zrcadla bez časového limitu |
| | `sandbox` | `true` \| `false` (`true`) | omezení procesu, který stahuje |
| `[security]` | `signatures` | `"required"` \| `"optional"` (`"required"`) | kontrola podpisů balíků a databází; `"never"` jen u místního repozitáře (`file://`) |
| | `local_signatures` | `"required"` \| `"optional"` \| `"never"` (`"optional"`) | podpisy balíků instalovaných ze souboru (sestavení z AUR) |
| | `protect` | seznam balíků (`["lux-engine", "glibc"]`) | balíky, u kterých se `lux remove` zeptá, i s `-y` je neodebere |
| `[packages]` | `aur` | `true` \| `false` (`true`) | balíky z AUR (sestavují se na tomto počítači) |
| | `review_pkgbuild` | `true` \| `false` (`true`) | před sestavením z AUR nabídnout kontrolu skriptu |
| | `flatpak` | `true` \| `false` (`true`) | `lux update` aktualizuje i aplikace Flatpak |
| | `cache_keep` | číslo (`2`) | kolik verzí balíku nechá `lux clean` v cache |
| | `hold` | seznam balíků | podržené balíky – `lux update` je neaktualizuje |
| | `ignore_group` | seznam skupin | totéž pro celé skupiny balíků |
| | `no_upgrade` | seznam cest bez `/` na začátku | soubory, které aktualizace nepřepíše (nová verze jako `.luxnew`) |
| | `no_extract` | seznam vzorů cest | soubory, které se z balíků vůbec nerozbalí (např. `usr/share/doc/*`) |
| `[paths]` | `cache`, `hooks` | absolutní cesta nebo seznam | jiný adresář cache / hooků (výchozí `/var/cache/lux/pkg`, `/etc/lux/hooks`) |
| | `database`, `log`, `keyring` | absolutní cesta | jiná databáze, log, klíčenka (výchozí viz *Soubory*) |
| `[include]` | `files` | seznam cest nebo vzorů (`["/etc/lux/conf.d/*.conf"]`) | další soubory (relativní cesta = vůči souboru); čtou se po celém souboru |

Seznamy ze všech souborů se sčítají (`hold` v `conf.d` přidá další balíky), ostatní hodnoty
z později čteného souboru přepíší dřívější.

### Repozitáře

Tabulka `[repo.NÁZEV]`; pořadí tabulek je pořadí hledání balíků (první repozitář, který balík má,
vyhrává; repozitáře z `[include]` jsou za repozitáři souboru). Název s tečkou nebo `+` patří do
uvozovek: `[repo."muj.repo"]`; pomlčky a podtržítka ne (`[repo.luxos-apps]`).

| Klíč | Hodnota | Význam |
|---|---|---|
| `server` | `"https://…"`, `"http://…"`, `"ftp://…"`, `"file://…"` nebo seznam | adresa repozitáře; `$repo` a `$arch` se doplní |
| `mirrors` | cesta k seznamu zrcadel nebo seznam | adresy ze souboru (např. `"/etc/lux/mirrorlist"`) |
| `signatures` | `"required"` \| `"optional"` \| `"never"` | jiná kontrola podpisů než globální (`"never"` jen pro `file://`) |
| `usage` | `["sync", "search", "install", "upgrade"]` nebo `"all"` | k čemu se repozitář používá (výchozí `all`) |

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
  ```toml
  [repo.muj]
  server = "https://example.org/$repo/$arch"
  ```
  Klíč repozitáře naimportuje `lux-engine-key` (`sudo /usr/lib/lux/alpm/bin/lux-engine-key --recv-keys ID`
  a `--lsign-key ID`), pak `lux update`. Repozitář `multilib` (Steam) zapne
  `sudo /usr/lib/lux/lux-config enable-repo multilib`.
- **Podržet balík** na současné verzi: v `[packages]` `hold = ["linux-firmware"]` (víc balíků do seznamu).
- **Jiná zrcadla**: `lux mirrors`, nebo upravit `/etc/lux/mirrorlist` (jedna adresa na řádek).
- **Bez AUR**: v `[packages]` `aur = false`; pro jednoho uživatele `~/.config/lux/lux.conf`:
  ```toml
  [packages]
  aur = false
  ```

### Chyby a varování

Chybná syntaxe nebo hodnota je chyba s názvem souboru a číslem řádku, např.:

```
lux: error in the configuration: /etc/lux/lux.conf:11: 'parallel' in [downloads] must be a whole number of at least 1 (without quotes), not "10"
lux: the package manager keeps using the last working configuration until this is fixed
```

S chybou `lux` (i Obchod a LuxOS Care) nic neinstaluje ani neaktualizuje, dokud se soubor neopraví.
Nástroje jádra (hooky, `makepkg`) zatím používají poslední funkční vygenerovanou konfiguraci
(`/var/lib/lux/engine.conf.last-good`). Další hlášení: `'color' in [general] must be true or false,
not "on"`, `Invalid value - text values need quotes`, `'hold  linux' is the old 'key value' format`,
`repository 'x' has no 'server' or 'mirrors' line`, `mirror list … does not exist`,
`'signatures never' is only allowed for a local repository (file://)`,
`repository 'x' is already defined at soubor:řádek`, `this looks like pacman.conf`.

**Neznámý klíč nebo tabulka** není chyba, jen varování v `lux config check` (s návrhem), klíč se
nepoužije:

```
lux: warning: /etc/lux/lux.conf:12: unknown key 'paralel' in [downloads] (did you mean 'parallel'?) - ignored
lux: warning: /etc/lux/lux.conf:7: unknown key 'parallel' in [general] (it belongs to [downloads]) - ignored
```

### Starší formát (LuxOS 0.9) a převod

Formát LuxOS 0.9 (`klíč  hodnota` na řádku, odsazené řádky pod `repo NÁZEV`, `include …`) `lux`
pořád čte – každý soubor (i v `conf.d`) se rozpozná sám; `lux config check` u něj napíše
`uses the old LuxOS 0.9 format`. Klíče se převádějí 1:1:

| LuxOS 0.9 | TOML | LuxOS 0.9 | TOML |
|---|---|---|---|
| `architecture` | `[general] architecture` | `aur` | `[packages] aur` |
| `color`, `candy` | `[general] color`, `candy` | `review-pkgbuild` | `[packages] review_pkgbuild` |
| `verbose-lists` | `[general] verbose` | `flatpak` | `[packages] flatpak` |
| `syslog` | `[general] syslog` | `clean-keep` | `[packages] cache_keep` |
| `channel` | `[general] channel` | | |
| `parallel-downloads` | `[downloads] parallel` | `hold` | `[packages] hold` |
| `check-space` | `[downloads] check_space` | `ignore-group` | `[packages] ignore_group` |
| `download-user` | `[downloads] user` | `no-upgrade` | `[packages] no_upgrade` |
| `download-timeout` | `[downloads] timeout` | `no-extract` | `[packages] no_extract` |
| `download-sandbox` | `[downloads] sandbox` | `cache`, `hooks` | `[paths] cache`, `hooks` |
| `signatures` | `[security] signatures` | `database`, `log`, `keyring` | `[paths] database`, `log`, `keyring` |
| `local-signatures` | `[security] local_signatures` | `repo X` + `server`/`mirrors`/`signatures`/`usage` | `[repo.X]` se stejnými klíči |
| `protect` | `[security] protect` | `include X` | `[include] files = ["X"]` |

`on`/`off` → `true`/`false`, opakované řádky (`hold`, `server` …) → jeden seznam.
**Převod:** `sudo lux config migrate` převede `/etc/lux/lux.conf` i soubory z `conf.d`
(`lux config migrate --dry-run` jen ukáže výsledek). Hodnoty zůstanou stejné (převod se ověří, jinak
se soubor nezmění), komentáře zůstanou u klíče nebo repozitáře, pod kterým byly, původní soubor
zůstane jako `lux.conf.old-format`. Nezměněná výchozí konfigurace se nahradí přesně výchozím souborem
balíku. Při aktualizaci na `lux-engine` z LuxOS 1.0 to hook `00-lux-engine-migrate` udělá jednou sám
(značka `/var/lib/lux/config-format-toml`); `lux.conf.luxnew` s novou výchozí konfigurací, kterou
po úpravě souboru nechal balík, pak smaže – soubor se jen převedl, není co slučovat. Soubor, který
převést nejde (např. chybí seznam zrcadel), zůstane ve starém formátu a další aktualizace to zkusí
znovu. Vlastní `~/.config/lux/lux.conf` převede `lux-config migrate ~/.config/lux/lux.conf`.

### Jak to funguje

`lux` (`lux_alpm.py`) čte `lux.conf`, vložené soubory a seznamy zrcadel přímo a z výsledku nastaví
libalpm – bez mezisouboru. Stabilní rozhraní pro další nástroje LuxOS je `lux_config.load()`
(slovník se všemi hodnotami včetně výchozích, repozitáři a varováními; v shellu
`/usr/lib/lux/lux-config json`). Nástroje jádra převzaté z Archu (`lux-engine`, `lux-engine-key`,
`makepkg` přes `lux-engine-conf`) jsou nezměněné programy v C, které umí jen syntaxi `pacman.conf`;
pro ně `lux-config` (`/usr/lib/lux/lux-config`, balík `lux-engine`) vygeneruje `/run/lux/engine.conf`.
V hlavičce si pamatuje čas změny a velikost každého zdroje; spouštěcí skripty v
`/usr/lib/lux/alpm/bin` (před skutečnými programy v `/usr/lib/lux/alpm/libexec`) ji před spuštěním
ověří a při změně vygenerují znovu. Uživatel bez práv k `/run/lux` dostane vlastní kopii
v `$XDG_RUNTIME_DIR/lux/`. Vygenerovanou konfiguraci ukáže `lux config engine`.

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
| `lux install <balík…>` | instalace z repozitářů → LuxOS (`.lux`) → Flathub → komunita (AUR, do sandboxu; do systému jen s `--system`); i soubor `.lux` nebo `.pkg.tar.zst`; už nainstalované přeskočí | `-S --needed`, `-U` |
| `lux remove <balík…>` | odebrání i s nepotřebnými závislostmi; změněné konfigurační soubory zůstanou jako `*.luxsave` (s `-n`/`--nosave` se smažou i ty) | `-Rs` (`-Rns`) |
| `lux update` (`upgrade`, `up`) | obnoví databáze, nejdřív podpisové klíče, pak celý systém; dál balíky komunity (AUR) v systému, `.lux` a Flatpak (+ úklid nepoužívaných prostředí) | `-Sy` + `-Su` |
| `lux check` (`check-updates`) | dostupné aktualizace z čerstvých seznamů (dočasná kopie, bez roota, systém beze změny) | `checkupdates` |
| `lux search [--installed] <výraz>` | hledání v repozitářích, LuxOS, na Flathubu a v komunitě (AUR); vzory názvu `^vim`, `vim$`, `^vim$`, `*qt*`, `lib*-git`, `%qt%` (`%` = `*`) | `-Ss` |
| `lux info <balík>` | podrobnosti (nainstalovaný, jinak z repozitáře; LuxOS, AUR) | `-Qi` / `-Si` |
| `lux list [--installed]` | nainstalované balíky (i `.lux`) | `-Q` |
| `lux list --upgradable` | dostupné aktualizace podle posledního obnovení databází | `-Qu` |
| `lux list --explicit \| --aur \| --orphans \| --lux` | výslovně instalované / mimo repozitáře / nepotřebné / `.lux` | `-Qe` / `-Qm` / `-Qdt` |
| `lux reinstall <balík…>` | stejná verze znovu (z repozitáře, jinak z cache) | `-S`, `-U` |
| `lux autoremove` | odebere závislosti, které už nic nepotřebuje | `-Rns $(-Qdtq)` |
| `lux files <balík>` | soubory balíku | `-Ql` |
| `lux owns <soubor>` (`owner`) | kterému balíku soubor patří (i příkaz z `PATH`) | `-Qo` |
| `lux clean` | vyčistí cache (ponechá `cache_keep` verzí, odinstalované balíky smaže) a nabídne `autoremove` | `paccache -rk2`, `-ruk0` |
| `lux fix` | opraví zamčenou databázi (jen když žádný správce balíků neběží), smaže nedokončená stahování, obnoví podpisové klíče (`lux-engine-key --init/--populate`, `archlinux-keyring`, `luxos-keyring`) | |
| `lux configs` | projde nové konfigurační soubory z aktualizací (`.luxnew`, `.luxsave`; i starší `.pacnew`, `.pacsave`): rozdíl, použít novou verzi, ponechat svou, upravit | `pacdiff` |
| `lux config [check\|show\|edit\|engine\|migrate]` | kontrola (chyby i varování), výpis, úprava `/etc/lux/lux.conf`; `engine` = vygenerovaná konfigurace nástrojů jádra; `migrate` = převod ze starého formátu | |
| `lux history [počet] [balík]` | poslední změny balíků z `/var/log/lux.log` | |
| `lux mirrors` | nejrychlejší zrcadla (`reflector`) do `/etc/lux/mirrorlist` | |
| `lux drivers`, `lux doctor`, `lux pack` | ovladače, kontrola systému (i konfigurace), sestavení `.lux` | |
| `lux snapshots`, `lux snapshot` | snímky systému (LuxOS Care dělá snímek před každou změnou balíků), nový snímek hned | |
| `lux rollback [snímek]` | návrat systému ke snímku od příštího startu (současný systém zůstane jako snímek, `/home` se nemění) | |
| `lux system show\|init\|edit\|check\|diff\|apply\|fix` | celý systém v jednom souboru LSL `/etc/luxos/system.lsl`, vytvoří ho instalátor (balíky, ovladače, služby, uživatelé, jazyk a formáty, klávesnice, síťová připojení bez hesel, tiskárny, napájení, zavaděč, Care, Guard, firewall, zamčení po chybných heslech, parametry jádra, výchozí nastavení nových uživatelů); `apply` udělá snímek, ukáže rozdíl a zeptá se, `fix` vrátí systém do stavu podle souboru (`man luxos-system`) | |

Volby: `-y` (bez otázek – jinak se `lux` vždy zeptá), `-n`/`--nosave` (`lux remove` smaže i změněné konfigurační soubory, žádný `*.luxsave`), `-v`/`--verbose` (seznam balíků, výstup skriptů
a surové chyby libalpm), `--repo`, `--aur`/`--community`, `--system` (balík komunity do systému místo sandboxu). Práva správce si `lux` vyžádá sám: v terminálu `sudo`,
v grafické relaci bez terminálu `pkexec`.

**Flathub a komunita (AUR).** Název, který není v repozitářích ani mezi aplikacemi LuxOS, se hledá
přes API Flathubu (`zoom` → `us.zoom.Zoom`); `lux` ukáže velikost včetně sdíleného prostředí
(runtime), které ještě není nainstalované. `lux remove` odebere i aplikace Flatpak a po odebrání
i aktualizaci smaže nepoužívaná prostředí (`flatpak uninstall --unused`). Až potom přijde komunita
(AUR): skript PKGBUILD zkontrolují pevná pravidla a LuxAI Lite (`/usr/lib/lux/lux_community.py
review`), balík se pak sestaví a nainstaluje **v sandboxu** (`luxos-sandbox build-install`). Do
systému jen s `--system` nebo volbou „2“ a napsaným slovem `system`; nebezpečný skript nikdy,
neověřený jen s potvrzením bez `-y`. Agent LuxAI (`LUXAI_AGENT=1`) balíky komunity instalovat nesmí.

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
| `@@PHASE <fáze>` | `refresh`, `download`, `verify`, `prepare` (hooky před transakcí, např. snímek systému), `install`, `remove`, `hooks` (hooky po transakci) |
| `@@PROGRESS <fáze> <procenta> [detail]` | průběh fáze (nejvýš 2× za sekundu + konec fáze); u `prepare`/`hooks` je detail `3/12 · <popis hooku>` |
| `@@RETRY <pokus>` | stahování selhalo, další pokus (2, 3) |
| `@@SUMMARY <akce> <počet> <stahování> <změna> <sekundy>` | hotovo |
| `@@ERROR <druh> <věta>` | `locked`, `network`, `keyring`, `disk`, `conflict`, `pkgconflict`, `deps`, `corrupt`, `notfound`, `notinstalled`, `permission`, `confirm`, `cancelled`, `config` (chyba v `lux.conf`), `protected` (chráněné systémové soubory se nepodařilo otevřít pro zápis, viz `system-protection.md`), `unknown` |
| `@@UNAVAILABLE <důvod>` | pyalpm nelze použít (návratový kód 3) – volající použije `lux-engine` |
| `@@DONE <kód>` | poslední řádek |

Řádky ve stylu libalpm: `Packages (N) …`, `<soubor> downloading...`,
`installing|upgrading|reinstalling|downgrading|removing <balík>...`,
`:: Running pre-transaction hooks...`, `:: Running post-transaction hooks...`, `error: failed to … transaction (<chyba libalpm>)`,
`<balík>: <soubor> exists in filesystem` (konflikty – podle nich LuxOS Care uvolní záložní jádro).

Návratové kódy: 0 ok, 1 chyba, 2 špatné použití, 3 pyalpm nepoužitelné, 130 přerušeno.
