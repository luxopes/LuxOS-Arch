# Lux Code – terminálový AI programovací agent

**Lux Code** je AI agent pro programování v terminálu. Je napsaný v [LSL](../lsl/overview.html),
programovacím jazyce LuxOS, a přeložený do nativního programu. Čte váš projekt, upravuje soubory,
spouští příkazy a testy a z výsledků pokračuje. Používá stejného asistenta a stejný účet jako
[LuxAI](luxai.html), ale pracuje v terminálu a míří na programování.

## Instalace a spuštění

```bash
lux install lux-code      # z repozitáře [luxos-apps]
cd muj-projekt
lux-code                  # nebo: lux-code --cwd /cesta/k/projektu
```

Další volby: `--plain` (řádkový režim), `--prompt 'TEXT'` (jeden úkol), `--resume ID` (pokračovat
v uložené relaci). Pokyny k projektu agent čte jen ze souboru `AGENTS.md` přímo v pracovní složce
(ne z nadřazených složek ani z domovské složky).

| Položka | Hodnota |
|---|---|
| Balík | `lux-code` 0.1.2 |
| Příkaz | `lux-code` (a položka nabídky **Lux Code**) |
| Dokumentace na disku | `/usr/share/doc/lux-code/README.md`, `TOOLS.md` |
| Nastavení | `~/.config/lux-code/.env`; proměnné prostředí mají přednost |
| Relace | `~/.local/share/lux-code/sessions` (složka 700, soubory 600) |

## Přihlášení

V LuxOS používá Lux Code sdílený **účet LuxAI** (viz [Účet LuxAI](luxai-account.html)). Když existuje
`~/.config/luxai/account.json`, požadavky jdou službě LuxAI, spotřeba se započítá do měsíčního limitu
účtu a modely jsou `flash` a `lite`. Když nejste přihlášeni, spusťte `luxos-account login`. Bez souboru
účtu může Lux Code použít klíč API (`LUX_AI_API`). Způsob lze vynutit `LUX_CODE_AUTH=account|apikey|auto`.
Soubor účtu jen čte a token nikdy nevypisuje.

## Rozhraní v terminálu

- `/` nabídne příkazy. Enter odešle, Alt+Enter vloží nový řádek a zatímco agent pracuje, můžete zařadit další úkoly.
- Ctrl+C nebo Esc přeruší běžící požadavek či příkaz; Ctrl+C na prázdném řádku skončí.
- Ctrl+V (nebo `/paste`) přiloží obrázek ze schránky.
- F2 přepíná změny a plán, F3 rozbalí podrobnosti nástrojů.

| Příkaz | K čemu |
|---|---|
| `/tools [filtr]` | katalog nástrojů |
| `/model [název]` | výběr modelu |
| `/reasoning [auto\|none\|low\|medium\|high\|xhigh\|max]` | úsilí při uvažování |
| `/new`, `/sessions`, `/resume [ID]`, `/rename NÁZEV`, `/save`, `/export SOUBOR.md` | relace |
| `/compact` | shrne kontext a původní uloží do archivu |
| `/retry` | pokračovat po chybě nebo přerušení |
| `/cd CESTA` | změna pracovní složky |
| `/diff`, `/diff all`, `/undo` | změny v relaci či pracovním prostoru; vrácení poslední úpravy souboru |
| `/plan`, `/jobs`, `/context`, `/references`, `/lang cs\|en` | plán, úlohy na pozadí, kontext, knihovna odkazů, jazyk |
| `/permissions readonly\|ask\|full` | režim oprávnění |
| `/clear`, `/quit` | vyčistit obrazovku, uložit a skončit |

## Oprávnění

`readonly` povolí jen čtení souborů a web; `ask` se ptá před každou další akcí; `full` spouští
vše bez ptaní. Je to kontrola uvnitř aplikace, ne izolace operačního systému: schválený příkaz shellu
běží s vašimi běžnými právy. Pro nedůvěryhodný kód použijte [Sandbox](sandbox.html).

## Nástroje

Lux Code má 113 nástrojů; model dostává nejvýše 64 definic na požadavek a speciální nástroje najde
přes `tool_search`. Hlavní oblasti:

- **soubory** – čtení s čísly řádků, přesné úpravy, rozdíly, vrácení, JSON, hledání, strom složek;
- **vývoj** – příkazy shellu, testy, git status/diff/log/blame, explicitní staging, nové větve;
- **služby na pozadí** s logy;
- **web** – hledání přes účet LuxAI (20 dotazů za minutu, 500 za den) nebo vlastní klíč Tavily, extrakce
  stránek, HTTP požadavky;
- **ladění Firefoxu** (DOM, konzole, síť, snímky, kliknutí), **plocha** (snímky obrazovky, okna, myš,
  klávesy, schránka) a **Android** přes `adb`;
- **nástroje agenta** – plán, dotaz na uživatele, paměť projektu v `.lux-code/memory.md`, obrázky.

## Knihovna odkazů

Při prvním interaktivním spuštění Lux Code stáhne referenční materiály včetně oficiální příručky LSL
pro nainstalovaný překladač a model je čte nástroji `reference_search` a `reference_read`. Vývojová
verze využívá i offline příručku LuxOS a LSL z `/usr/share/luxos/docs` (stejné stránky jako tento web).

## Nastavení

| Proměnná | Význam |
|---|---|
| `LUX_CODE_CONFIG` | cesta k souboru `.env` |
| `LUX_AI_API` | klíč API (když není přihlášený účet) |
| `LUX_CODE_AUTH` | `auto`, `account` nebo `apikey` |
| `LUX_AI_MODEL` | model, výchozí `flash` |
| `LUX_AI_REASONING` | výchozí `low` (`auto` ji vynechá) |
| `LUX_CODE_SHELL` | shell pro příkazy, výchozí `/bin/bash` |
| `LUX_CODE_HOME` | datová složka |
| `LUX_CODE_PLAIN` | `1` = řádkový režim |
| `LUX_CODE_RECONNECT` | `0` vypne opakování při chybě sítě |
| `LUX_CODE_REFERENCES` | `0` vypne stahování referencí |

## Související

- [Lux Code a LSL IDE](../lsl/lux-code.html) – úplný přehled včetně LSL IDE (anglicky)
- [LuxAI](luxai.html), [Účet LuxAI](luxai-account.html)
- [Přehled LSL](../lsl/overview.html) (anglicky)
