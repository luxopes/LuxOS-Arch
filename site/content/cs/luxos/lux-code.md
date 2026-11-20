# Lux Code – terminálový AI programovací agent

**Lux Code** je AI agent pro programování v terminálu. Řeknete mu, co potřebujete, a pracuje ve vašem
projektu: čte kód, upravuje soubory, spouští příkazy a testy v shellu LuxOS `lsh` a z výsledků
pokračuje. Používá stejného asistenta a stejný účet jako [LuxAI](luxai.html), ale pracuje v terminálu
a je určený pro programování. Od LuxOS 1.0.3 je Lux Code (verze 0.6) postavený na otevřeném projektu
[Oh My Pi](https://omp.sh) (MIT) s vrstvou LuxOS: účet a modely LuxAI, `lsh` jako shell, příručka LuxOS
a pravidla LuxOS.

## Instalace a spuštění

```bash
lux install lux-code      # z repozitáře [luxos-apps] (potřebuje bun z Archu, nainstaluje se s ním)
cd muj-projekt
lux-code                  # interaktivně; lux-code -p "ÚKOL" pro jeden úkol
```

| Položka | Hodnota |
|---|---|
| Balík | `lux-code` 0.6.5 (nahrazuje `lux-code-next` i původní Lux Code 0.1) |
| Příkaz | `lux-code` (a položka **Lux Code** v nabídce); `lux-code-next` dál funguje |
| Nastavení | `~/.config/lux-code/agent/config.yml` (upravíte i přes `/settings`) |
| Pokyny projektu | `AGENTS.md` jen přímo v pracovní složce (ne v nadřazených) |
| Dokumentace na disku | `/usr/share/doc/lux-code/README.md` |

Nastavení dřívější zkušební verze z `~/.config/lux-code-next` se při prvním spuštění přesune do
`~/.config/lux-code`. Původní Lux Code 0.1 měl data v `~/.local/share/lux-code`; ta zůstávají
nedotčená.

## Přihlášení

V LuxOS používá Lux Code společný **účet LuxAI** (viz [Účet LuxAI](luxai-account.html)); když nejste
přihlášení, spusťte `/luxai login` nebo `luxos-account login`. Požadavky se počítají do měsíčních
kreditů účtu. Bez účtu může Lux Code použít klíč API (`LUX_AI_API`).

## Rozhraní v terminálu

| Příkaz | K čemu |
|---|---|
| `/help` | všechny příkazy |
| `/model flash`, `/model lite` | výběr LuxAI Flash nebo Lite |
| `/usage` | kredity LuxAI v tomto měsíci (pruh, zbývající kredity, datum obnovení) |
| `/luxai`, `/luxai login` | stav účtu a personalizace; přihlášení |
| `/cd SLOŽKA` | změna pracovní složky (`/cd` = domovská, `/cd -` = předchozí, Tab doplňuje) |
| `/settings` | nastavení, např. vypnutí personalizace LuxAI pro Lux Code |
| `/hub` nebo Alt+A | co dělají podagenti |
| `/notifications on\|off` | oznámení na ploše |
| `/mouse off` | klasické zobrazení s historií terminálu |

- Přemýšlení modelu je skryté za jedním řádkem; Ctrl+T ho ukáže.
- Myš funguje jako v jiných programovacích agentech: tažením vyberete a zkopírujete text, dvojklik
  vybere slovo, trojklik řádek, kolečko a PgUp/PgDn posouvají konverzaci.
- Podagenti běží na pozadí (nejvýš 3 najednou) a hlavní agent mezitím pracuje dál.
- Dlouhé konverzace se samy shrnou dřív, než dosáhnou limitů požadavků LuxAI.

## Nástroje

Model dostane malou základní sadu (soubory, úpravy, hledání, příkazy v `lsh`, web) a další si podle
potřeby načte přes `tool_search`: plocha a snímky obrazovky, schránka, Android přes `adb`, ladění ve
Firefoxu, informace o systému, jazykové servery a offline příručka LuxOS a LSL z
`/usr/share/luxos/docs`. Příkazy, které LuxOS dělá jinak, se přesměrují: `pacman`, `yay` a podobné se
odmítnou s odpovídajícím příkazem `lux` a hesla se nikdy neposílají do `sudo` rourou.

Lux Code není sandbox: schválený příkaz běží s vašimi běžnými právy. Pro nedůvěryhodný kód použijte
[Sandbox](sandbox.html).

## Nastavení proměnnými

| Proměnná | Význam |
|---|---|
| `LUX_AI_API` | klíč API (když není přihlášený účet) |
| `LUX_CODE_MOUSE` | `0` = klasické zobrazení bez obsluhy myši |
| `LUX_CODE_MAX_MESSAGES`, `LUX_CODE_MAX_BODY` | limity požadavků LuxAI pro shrnutí (také `agent/luxai-limits.json`) |
| `LUX_CODE_NAME` | název složky nastavení (`~/.config/<název>`), výchozí `lux-code` |

## Související

- [Lux Code a LSL IDE](../lsl/lux-code.html) – úplný přehled včetně LSL IDE (anglicky)
- [LuxAI](luxai.html), [Účet LuxAI](luxai-account.html)
- [Přehled LSL](../lsl/overview.html) (anglicky)
