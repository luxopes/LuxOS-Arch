# Formát balíčků LuxOS (`.lux`)

Vlastní formát aplikací LuxOS. Balíček je jeden soubor `nazev-verze-vydani-arch.lux`:
archiv **tar + zstd** s metadaty, samotnou aplikací a vším, co potřebuje k integraci do systému.
Spravuje ho `lux` (instalace, aktualizace, odebrání) a nabízí ho Obchod LuxOS.

## Obsah archivu

```
lux.json                 metadata (povinné)
app/                     aplikace → /opt/lux/<name>/app/
share/                   volitelné: soubory pro systém → /usr/local/share/
  applications/<name>.desktop
  icons/hicolor/<velikost>/apps/<name>.png|svg
scripts/                 volitelné: post_install, pre_remove (bash, běží jako root)
```

## `lux.json`

```json
{
  "format": 1,
  "name": "hello-lux",
  "title": "Hello Lux",
  "version": "1.0.0",
  "release": 1,
  "arch": "any",
  "summary": "Krátký popis na jeden řádek",
  "description": "Delší popis pro Obchod LuxOS.",
  "license": "MIT",
  "url": "https://example.com",
  "categories": ["Utility"],
  "depends": { "system": ["yad"], "lux": [] },
  "bin": { "hello-lux": "hello-lux" }
}
```

| Pole | Význam |
|---|---|
| `format` | verze formátu (teď `1`); novější balíček starý `lux` odmítne |
| `name` | identifikátor: malá písmena, číslice, `.` `_` `+` `-` |
| `title` | zobrazovaný název (Obchod), nepovinné |
| `version`, `release` | verze aplikace a vydání balíčku (porovnává se jako u pacmanu) |
| `arch` | `any` nebo `x86_64` |
| `summary`, `description`, `license`, `url`, `categories` | informace pro Obchod a `lux info`; kategorie podle freedesktop (`Utility`, `Development`, `Graphics`…) |
| `depends.system` | balíčky z repozitářů (pacman), nainstalují se před aplikací |
| `depends.lux` | další balíčky `.lux` z repozitáře LuxOS |
| `bin` | příkazy: `název` → cesta v `app/`; vznikne odkaz `/usr/local/bin/název` |

## Instalace

`lux install soubor.lux` nebo `lux install název` (z repozitáře):

1. ověří podpis klíčem LuxOS (`luxos-keyring`); u repozitáře i kontrolní součet z indexu,
   nepodepsaný lokální soubor nainstaluje jen po potvrzení,
2. nainstaluje `depends.system` (pacman) a `depends.lux`,
3. rozbalí aplikaci do `/opt/lux/<name>` (atomicky, stará verze se nahradí až po rozbalení),
4. vytvoří příkazy v `/usr/local/bin`, zkopíruje `share/` do `/usr/local/share`,
5. zapíše seznam souborů do `/var/lib/lux/installed/<name>.json` a spustí `scripts/post_install`.

`lux remove název` spustí `scripts/pre_remove` a odstraní přesně zapsané soubory.
`lux update` aktualizuje i balíčky `.lux`, `lux list --lux` je vypíše.

## Repozitář

`https://lsl.lux-ai.cz/luxos/lux/`:

- `index.json` + `index.json.sig` – seznam balíčků (`name`, `title`, `version`, `release`, `summary`,
  `file`, `size`, `sha256`, volitelně `icon`),
- `<soubor>.lux` + `<soubor>.lux.sig`, ikony `<name>.icon.svg|png` pro Obchod.

Index i balíčky podepisuje `./build.sh packages` (klíč v `~/.local/share/luxos/signing`),
nahrává `scripts/publish-repo.sh`.

## Vytvoření balíčku

```bash
cp -r docs/examples/hello-lux lux-packages/moje-aplikace   # upravit lux.json a app/
lux pack lux-packages/moje-aplikace out/                   # ruční sestavení a kontrola
./build.sh packages && scripts/publish-repo.sh             # do repozitáře LuxOS
```
