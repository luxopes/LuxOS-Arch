# LuxOS ve srovnání s jinými distribucemi

LuxOS se často srovnává s Ubuntu, Linux Mintem, Zorin OS, elementary OS a rodinou Archu. Tato stránka
shrnuje rozdíly poctivě – včetně toho, kde jsou ostatní lepší volbou. LuxOS je **beta** a mladý, malý
projekt; ostatní distribuce mají za sebou roky vydání a velké komunity.

## Přehled

| | LuxOS | Ubuntu | Linux Mint | Zorin OS | elementary OS | Arch Linux / EndeavourOS / Manjaro |
|---|---|---|---|---|---|---|
| Základ | Arch Linux | Debian | Ubuntu LTS | Ubuntu LTS | Ubuntu LTS | Arch (Manjaro: vlastní zdržené repozitáře) |
| Model vydávání | průběžný (číslovaná ISO) | pevná vydání, LTS každé 2 roky | pevný, podle Ubuntu LTS | pevný, podle Ubuntu LTS | pevný, podle Ubuntu LTS | průběžný |
| Prostředí | součásti Xfce v rozložení jako macOS (horní lišta, Dock Plank, Launchpad, Ovládací centrum) | GNOME | Cinnamon (i MATE, Xfce) | na GNOME, rozložení jako Windows/macOS | Pantheon | podle vás |
| Správa balíků | `lux` (libalpm): repozitáře Archu, Flathub, AUR sestavené v sandboxu, aplikace `.lux`; Obchod LuxOS | apt, Snap | apt, Flatpak | apt, Flatpak, Snap | apt, Flatpak (AppCenter) | pacman (+ pomocníci pro AUR) |
| Aktualizace | automaticky na pozadí, před každou snímek Btrfs, návrat z nabídky spouštění | automatické bezpečnostní aktualizace | Správce aktualizací, snímky Timeshift | Aktualizace softwaru | AppCenter | ručně |
| Jádro | `linux-luxos` (neupravené stabilní z kernel.org) | jádro Ubuntu | jádro Ubuntu | jádro Ubuntu | jádro Ubuntu | jádra Archu / Manjara |
| Ovladače | automatické rozpoznání při instalaci i později (NVIDIA podle generace, Wi‑Fi, zvuk, kamery) | Další ovladače | Správce ovladačů | Další ovladače | ovladače v AppCenteru | ručně (EndeavourOS/Manjaro pomáhají s NVIDIA) |
| Výchozí zabezpečení | zapnutý firewall, Lux Guard pro stažené programy, `/usr` jen pro čtení, podepsané repozitáře | AppArmor, firewall ve výchozím stavu vypnutý | firewall k dispozici (vypnutý) | firewall k dispozici | AppArmor | podle vás |
| AI asistent | volitelný LuxAI (účet, modely v cloudu) | – | – | – | – | – |
| Zralost a podpora | beta, jeden vývojář, GitHub issues | velmi zralé, komerční podpora (Canonical) | velmi zralé, velká komunita | zralé, placená edice Pro | zralé | zralé, obrovská wiki a komunita |

Podrobnosti o ostatních distribucích se mezi vydáními mění; aktuální stav ověřte na jejich webech.

## Ubuntu, Linux Mint a Zorin OS

To jsou bezpečné a oblíbené volby: vydání s dlouhodobou podporou, obrovské komunity a nespočet návodů.
Jsou lepší volbou, když potřebujete hlavně stabilitu, komerční podporu nebo software, který se oficiálně
balí jen pro Ubuntu.

LuxOS se liší tím, že sleduje Arch Linux: software je nový brzy po vydání, aktualizace přicházejí
průběžně (žádný velký přechod každé dva roky) a chrání je snímky. Prostředí je rovnou uspořádané jako
macOS. Rozložení podobné macOS nabízí i Zorin OS, na základu Ubuntu.

## elementary OS

elementary OS má nejbližší přístup: klidný design inspirovaný Macem. Používá vlastní prostředí Pantheon
a vybraný AppCenter na základu Ubuntu LTS. LuxOS stojí na Xfce (nenáročné), na plných repozitářích Archu
s Flathubem a AUR a přidává návrat ze snímků, automatické ovladače a volitelného AI asistenta.
elementary OS je jako celek zralejší a vyladěnější.

## Arch Linux, EndeavourOS a Manjaro

- **Arch Linux** dává minimální základ a vše si postavíte sami. LuxOS používá stejné repozitáře, ale je
  to hotové prostředí s grafickým instalátorem.
- **EndeavourOS** zůstává blízko čistému Archu s instalátorem a pár nástroji; dál používáte `pacman`
  a prostředí si nastavujete sami.
- **Manjaro** balíky Archu zdržuje ve vlastních repozitářích a používá vlastní jádra.

LuxOS bere balíky přímo z Archu, příkaz `pacman` nahrazuje `lux` (pod ním stejná knihovna libalpm,
vlastní konfigurace v `/etc/lux/lux.conf`), balíky z AUR sestavuje až po kontrole a ve výchozím stavu
je instaluje do sandboxu a systém udržuje automaticky pomocí [LuxOS Care](care-updates.html). Fóra
a kanály Archu LuxOS ani jiné odvozené distribuce nepodporují.

## Pro koho je LuxOS?

- Chcete na Linuxu prostředí jako na Macu bez dnů strávených nastavováním.
- Máte rádi nový software (rolling release), ale chcete aktualizace, které jde vrátit.
- Nevadí vám beta a jste ochotni hlásit chyby.

Zavedenou distribuci zvolte, když počítač nesmí překvapit (pracovní nebo rodinný počítač), když
potřebujete dlouhodobou podporu nebo certifikaci výrobce, nebo když spoléháte na pomoc velké komunity.

Viz také: [Časté otázky](faq.html), [Podporovaný hardware](hardware.html),
[Instalace LuxOS](installer.html) (anglicky).
