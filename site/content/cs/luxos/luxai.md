# LuxAI – AI asistent pro LuxOS

**LuxAI** je AI asistent systému LuxOS: desktopová aplikace (Python 3 a GTK 3, balík `luxai`
z repozitáře `[luxos-apps]`), která umí konverzovat jako každý AI asistent a v režimu **Agent**
dokáže skutečně pracovat s vaším počítačem. Je to stejný asistent jako terminálový agent
[Lux Code](lux-code.html), jen s grafickým rozhraním. Nainstalujete ho příkazem `lux install luxai`
a spustíte z Launchpadu nebo z Hledání.

## Dva režimy

| Režim | Co dělá |
|---|---|
| **Chat** | Obyčejná konverzace se streamovanými odpověďmi, Markdown (nadpisy, seznamy, tabulky, bloky kódu s tlačítkem Kopírovat, odkazy) a historií konverzací v postranním panelu. Chat nemá přístup k počítači, používá jen offline příručku a webové nástroje. |
| **Agent** | LuxAI pracuje s počítačem pomocí nástrojů: příkazy shellu, čtení, zápis, úprava a mazání souborů, výpis a hledání souborů, otevírání aplikací a adres, snímky obrazovky, myš a klávesnice (`xdotool`), seznam, aktivace a zavření oken (`wmctrl`), schránka a oznámení. Každé volání nástroje je karta s výsledkem a podrobnostmi. |

Ke zprávě lze přiložit obrázky a textové soubory (tlačítko **+** nebo vložení Ctrl+V): nejvýše 4 obrázky
a 8 příloh na zprávu; obrázky se zmenší na JPEG, textové soubory se vloží jako text (nejvýše 60 000 znaků).

## Zná LuxOS: offline příručka

V obou režimech má model offline příručku LuxOS a [LSL](../lsl/overview.html) z balíku `luxos-docs`
(stejné stránky jako tato dokumentace). Hledá v ní nástrojem `docs_search` (řazené sekce, bez ohledu na
velikost písmen a diakritiku) a čte soubor nebo sekci nástrojem `docs_read`. Nástroje čtou jen soubory
ve složce příručky a nevyžadují schválení. Proto LuxAI odpoví na otázky typu „jak přidám repozitář do
luxu“ ze skutečné dokumentace.

## Hledání na webu

V režimech Chat i Agent umí LuxAI hledat na webu a číst stránky (`web_search`, `web_fetch`):

- `web_search` vrátí nejvýše 8 výsledků (název, URL, úryvek) přes váš účet LuxAI; když server
  nepřijme požadavek, použije se DuckDuckGo.
- `web_fetch` čte jen veřejné adresy `http(s)` bez cookies a přihlašovacích údajů, sleduje nejvýše
  5 přesměrování, stáhne nejvýše 2 MB a vytáhne čitelný text (do 20 000 znaků).
- **Domácí sítě jsou blokované**: každá adresa musí být veřejná (žádný loopback, LAN ani link-local),
  i po každém přesměrování.
- Obsah z webu je označený jako **nedůvěryhodná data** a model nesmí plnit pokyny z webových stránek.
  Jakmile je v konverzaci obsah z webu, každý příkaz shellu v režimu Agent vyžaduje samostatné
  potvrzení a adresu, kterou nenapsal uživatel ani nevrátilo hledání, otevře LuxAI jen po schválení.
  Chrání to před prompt injection a před vynášením dat v URL.

## Matematika, kód a kopírování

Vzorce LaTeX v odpovědích se vykreslí (zlomky, sumy, integrály, indexy, řecká písmena). Bloky kódu mají
zvýraznění syntaxe (Python, LSL, Bash, JavaScript, C/C++, Rust, Go, JSON, HTML, CSS, SQL, YAML a další)
ve světlém i tmavém motivu. Text vyberete myší a zkopírujete Ctrl+C, nebo tlačítky **Kopírovat** pod
odpověďmi a bloky kódu.

## Bezpečnost agenta a oprávnění

Agent se před činností ptá. Akce jsou rozdělené podle rizika:

| Úroveň | Příklady | Chování |
|---|---|---|
| čtení | čtení souboru, výpis složky, hledání souborů, seznam oken | bez dotazu |
| akce | shell, zápis a mazání, myš a klávesnice, otevření aplikace či adresy, snímek obrazovky, schránka | karta **Povolit jednou / Vždy v této relaci / Zamítnout**; přepínač *Automaticky schvalovat* ji přeskočí (po restartu je vždy vypnutý) |
| citlivé | čtení `~/.ssh`, `.env`, klíčů; odeslání hlášení autorovi LuxOS | vždy jednorázové potvrzení |
| nebezpečné | vypnutí PC, `sudo` v příkazu, `curl … \| sh`, zápis mimo domovskou složku | dvě potvrzení, nelze povolit natrvalo |
| blokované | token účtu LuxAI, `rm -rf /`, `mkfs`, zápis na disk, zavaděč a jádro, účty, sudoers/polkit/PAM, předání hesla do `sudo`/`su` | vždy odmítnuto při jakémkoli nastavení |

V **Nastavení › Oprávnění agenta** nastavíte po kategoriích, zda se spouštějí příkazy, čtou a zapisují
soubory, používá síť, otevírají aplikace, ovládá myš a klávesnice a pořizují snímky obrazovky (vždy se
ptát / ptát se jen u rizikových / nikdy), dále pracovní složku, povolené a zakázané složky a časový limit
příkazů (výchozí 120 s). **Zastavit** (nebo Esc) přeruší odpověď modelu i běžící příkaz.

### Režim správce

Když úkol vyžaduje root, agent spustí příkaz přes `pkexec` po stejné kontrole tvrdých bloků. Výchozí
je dvojí potvrzení a heslo správce. Volitelně (jen model Flash) lze povolit příkazy root bez hesla.
Každý příkaz root se zapíše do `~/.local/state/luxai/root-commands.log` a do žurnálu
(`journalctl -t luxai-root`).

## Účet LuxAI a modely

LuxAI používá sdílený **účet LuxAI** systému LuxOS – přihlásíte se jednou v systému a využijí ho LuxAI,
Lux Code i LSL IDE. Viz [Účet LuxAI](luxai-account.html). Aplikace komunikuje se `https://lux-ai.cz`
a nabízí dva modely, **Flash** a **Lite** (nejlevnější, používá se i pro názvy konverzací). Měsíční
spotřebu vidíte dole v postranním panelu. Pokud nejste přihlášeni nebo vypršela relace, nabídne LuxAI
**Přihlásit se účtem LuxAI** (spustí `luxos-account login`). Token se čte z `~/.config/luxai/account.json`;
LuxAI ho nikdy nezapisuje ani nevypisuje.

## Soukromí a vaše data

- Konverzace se ukládají lokálně do `~/.local/share/luxai/conversations/` (soubory `0600`), obrázky do
  `~/.local/share/luxai/images/`, nastavení do `~/.config/luxai/settings.json`, snímky obrazovky do
  `~/.cache/luxai/screenshots/`.
- V **Nastavení › Soukromí a historie** lze vypnout historii, smazat všechny konverzace i snímky obrazovky.
- Zprávy (a v režimu Agent výsledky nástrojů, které model potřebuje) se posílají službě LuxAI, aby
  vznikla odpověď. Obrázky se posílají jen modelům, které je vidí.
- Nástroj `send_feedback` odešle hlášení chyby či nápad autorovi LuxOS **jen po vašem potvrzení**:
  napřed uvidíte celý text, účet (nebo anonymně) a anonymizované systémové údaje. Jména uživatelů
  a počítačů, e-maily, adresy IP/MAC a tokeny se anonymizují.

## Nastavení

**Nastavení** otevřete Ctrl+, nebo nabídkou ⋮: motiv (systém, světlý, tmavý), odesílání Enter nebo
Ctrl+Enter, oznámení, výchozí model, styl odpovědí (vyvážený, stručný, podrobný, technický, přátelský),
délka odpovědi, jazyk, vlastní pokyny, automatické názvy konverzací, oprávnění agenta a soukromí.
Klávesy: Enter odeslat, Esc zastavit, Ctrl+N nová konverzace, Ctrl+F hledání, Ctrl+, nastavení, Ctrl+Q konec.

LuxAI je přeložené do 13 jazyků a řídí se jazykem systému.

## Související

- [Účet LuxAI](luxai-account.html) – přihlášení a příkaz `luxos-account` (anglicky)
- [Lux Code](lux-code.html) – stejný asistent v terminálu pro programování
- [Příručka pro AI asistenty na LuxOS](for-ai-assistants.html) (anglicky)
