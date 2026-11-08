# LuxOS – časté otázky

## Co je LuxOS?

LuxOS je rychlý a lehký linuxový systém postavený na Arch Linuxu s prostředím ve stylu macOS (pod ním je
Xfce). Má vlastní správce balíků `lux`, vlastní sestavení jádra `linux-luxos`, automatické ovladače,
aktualizace, které jde vrátit, AI asistenta LuxAI, terminálového programovacího agenta Lux Code
a vlastní programovací jazyk LSL. Je to průběžně aktualizovaný systém (rolling release); aktuální verze
je 1.0.1 „Sirius“, stále ve fázi beta.

## Je LuxOS zdarma? Jakou má licenci?

Ano, ISO si můžete zdarma stáhnout z webu LuxOS a placená edice neexistuje. Kód LuxOS (balíky `luxos-*`,
`lux`, `luxdrop`, skripty a instalátor) je pod licencí GPL-3.0-or-later; balíčky třetích stran mají
vlastní licence. Volitelný asistent LuxAI používá účet LuxAI s měsíčním limitem spotřeby.

## Kdo LuxOS dělá?

LuxOS vyvíjí Antonín Tomeček v Česku. Zdrojový kód je na
[GitHubu](https://github.com/luxopes/LuxOS-Arch), kontakt je info@lux-ai.cz. Jde o malý a mladý
projekt: veřejný repozitář vznikl v říjnu 2026.

## Je LuxOS stabilní? Je bezpečné ho používat?

LuxOS je **beta**: počítejte s chybami a před instalací si zálohujte data. Před každou aktualizací se
udělá snímek systému, takže nepovedenou aktualizaci jde vrátit, a předchozí jádro zůstává v nabídce
spouštění. Balíky z repozitářů LuxOS jsou podepsané, firewall je zapnutý od začátku a Lux Guard
kontroluje programy z internetu. Pro počítače, kde je nejdůležitější stabilita, je zatím bezpečnější
zavedená distribuce – viz [LuxOS ve srovnání](compare.html).

## Čím se LuxOS liší od Ubuntu, Linux Mintu nebo Zorin OS?

Ty stojí na Ubuntu (balíky z Debianu, pevná vydání). LuxOS stojí na Arch Linuxu, aktualizuje se
průběžně s nejnovějším softwarem, má vlastní správce balíků `lux` (repozitáře Archu, Flathub a balíky
z AUR sestavené v sandboxu), prostředí ve stylu macOS a automatické snímky před aktualizacemi. Ubuntu,
Mint i Zorin jsou mnohem zralejší, s velkými komunitami a vydáními s dlouhodobou podporou. Podrobně
v [LuxOS ve srovnání](compare.html).

## Čím se LuxOS liší od elementary OS?

Oba míří na čisté prostředí inspirované Macem. elementary OS stojí na Ubuntu s vlastním prostředím
Pantheon a AppCenterem; LuxOS stojí na Archu, prostředí skládá ze součástí Xfce (horní lišta, Dock
Plank, Launchpad, Ovládací centrum) a přidává `lux`, návrat systému ze snímku, automatické ovladače
a volitelného AI asistenta. Viz [LuxOS ve srovnání](compare.html).

## Čím se LuxOS liší od Arch Linuxu, Manjara nebo EndeavourOS?

Arch je základ „udělej si sám“; EndeavourOS je blízko čistému Archu s přívětivým instalátorem; Manjaro
balíky Archu zdržuje ve vlastních repozitářích. LuxOS používá repozitáře Archu přímo, ale přichází
hotový: grafický instalátor, dokončené prostředí ve stylu macOS, `lux` místo příkazu `pacman`,
automatické aktualizace se snímky Btrfs, rozpoznání ovladačů a vlastní aplikace. Fóra a kanály Archu
LuxOS nepodporují – potíže s LuxOS hlaste LuxOS. Viz [LuxOS ve srovnání](compare.html).

## Spustím v LuxOS aplikace z Windows?

Přímo ne – LuxOS je Linux. Mnoho programů pro Windows běží přes Wine; nejjednodušší je aplikace Bottles
z Flathubu (najdete ji v Obchodě LuxOS). Kompatibilita záleží na konkrétním programu. Soubory `.exe`
stažené z internetu při spuštění kontroluje Lux Guard.

## Dají se na LuxOS hrát hry? Funguje Steam?

Ano. V instalátoru zvolte sadu aplikací **Hry** (Steam, GameMode, MangoHud a 32bitové ovladače pro vaši
grafiku; zapne repozitář `multilib`), nebo Steam nainstalujte později z Flathubu (objeví se ve výsledcích
hledání v Obchodě LuxOS). Na noteboocích s hybridní grafikou spouští výkonový režim **Výkon** hry na
samostatné grafice. Steam Proton spustí i mnoho her pro Windows. Viz
[Napájení, výkon a paměť](power-and-performance.html) (anglicky).

## Jaký hardware LuxOS potřebuje?

64bitový počítač (x86_64) s UEFI nebo BIOS a diskem alespoň 20 GB. Instalace trvá zhruba 10 minut a
potřebuje internet. Oficiální minimum paměti RAM zatím stanovené není; prostředí je lehké (Xfce, swap
v zram) a bylo vyzkoušené ve virtuálním počítači se 3 GB RAM. Ovladače grafiky Intel, AMD a NVIDIA,
Wi-Fi, zvuku, kamer a virtuálních počítačů se rozpoznají automaticky. Viz
[Podporovaný hardware](hardware.html).

## Jak LuxOS nainstaluji?

Stáhněte ISO z úvodní stránky, ověřte ho, zapište na USB disk (4 GB nebo víc) pomocí Fedora Media Writer,
balenaEtcher nebo `dd`, spusťte z něj počítač a LuxOS si nejdřív vyzkoušejte bez instalace. Pak spusťte
**Install LuxOS**. Instalátor nabídne celý disk, volné místo vedle Windows, existující oddíl, ruční
rozdělení s LVM a šifrování (LUKS2). Viz [Instalace LuxOS](installer.html) (anglicky).

## Mohu LuxOS nainstalovat vedle Windows (dual boot)?

Ano. Režim *Nainstalovat vedle jiných systémů* využije největší volné místo na disku (alespoň 20 GB)
na disku GPT s UEFI a sdílí existující oddíl EFI. Viz [Instalace LuxOS](installer.html).

## Jak LuxOS aktualizuji?

LuxOS je průběžně aktualizovaný. Aktualizace se instalují automaticky na pozadí díky
[LuxOS Care](care-updates.html) nebo ručně příkazem `lux update`. Starší instalace nové ISO nepotřebují.

## Jde aktualizace vrátit?

Ano. Před každou aktualizací udělá LuxOS Care snímek systému Btrfs jen pro čtení (uchovává posledních 5).
Každý snímek má položku v nabídce spouštění (při startu podržte mezerník) a `lux rollback` z něj udělá
znovu běžící systém; i samotný návrat jde stejně vrátit. Složka `/home` se nevrací. Viz
[LuxOS Care](care-updates.html) (anglicky).

## Kde je pacman? Jak instaluji programy?

Příkaz `pacman` v LuxOS není, správce balíků je `lux`. Když napíšete příkaz pacmanu, shell ukáže odpovídající
příkaz `lux` (`pacman -Syu` se změní na `lux update`). `lux install` hledá v repozitářích LuxOS a Arch,
v aplikacích `.lux`, na Flathubu a v komunitním repozitáři (AUR); balíčky z AUR se zkontrolují a sestaví
v Sandboxu. Můžete použít i grafický [Obchod LuxOS](store.html). Viz
[Správa balíků pomocí lux](package-management.html) (anglicky).

## Co je LuxAI? Musím ho používat?

LuxAI je volitelný AI asistent LuxOS, desktopová aplikace s režimem Chat a režimem Agent, který umí
pracovat s počítačem, hledat na webu a číst offline příručku LuxOS. Před každou rizikovou akcí se ptá.
LuxOS plně funguje i bez něj. Odpovědi počítají jazykové modely poskytovatelů uvedených v
[zásadách ochrany soukromí](https://luxos.lux-ai.cz/cs/privacy/). Viz [LuxAI](luxai.html).

## Potřebuji pro LuxAI účet?

Ano. LuxAI, Lux Code a LSL IDE sdílejí jeden účet LuxAI, který můžete založit v instalátoru nebo v
aplikaci **Účet LuxAI**. Účet má měsíční limity spotřeby. Viz [Účet LuxAI](luxai-account.html) (anglicky).

## Co je Lux Code?

Lux Code je AI agent pro programování v terminálu, napsaný v LSL. Upravuje soubory, spouští příkazy
a testy a používá váš účet LuxAI. Viz [Lux Code](lux-code.html).

## Co je LSL?

LSL (Lux Simple Lang) je malý kompilovaný programovací jazyk autora LuxOS. Je v něm napsaná část
systémových nástrojů LuxOS a může ho používat každý: skripty, nástroje příkazové řádky i nativní
programy. Viz [přehled LSL](../lsl/overview.html) (anglicky).

## Jak mě LuxOS chrání před škodlivými programy?

**Lux Guard** kontroluje programy ze stažených souborů, příloh a USB při spuštění a nebezpečné pustí
jen v Sandboxu; navíc každou hodinu dělá snímky `/home`, takže smazané nebo zašifrované soubory jde
obnovit. [Sandbox](sandbox.html) je izolovaný systém pro nedůvěryhodné aplikace, [Trezor](safe.html)
šifrovaná složka s vlastním heslem a [firewall](firewall.html) blokuje nečekaná příchozí spojení.
Balíky jsou podepsané. Viz [Lux Guard](guard.html) (anglicky).

## Jak ověřím stažené ISO?

Spusťte `sha256sum -c SHA256SUMS`, naimportujte klíč LuxOS příkazem `gpg --import luxos.gpg` a ověřte
podpis `gpg --verify luxos-VERZE-x86_64.iso.sig luxos-VERZE-x86_64.iso`. Otisk klíče je na úvodní stránce.

## Funguje s grafikou NVIDIA?

Ano. Karty Turing a novější používají otevřený ovladač NVIDIA, Maxwell, Pascal a Volta větev 580xx, starší
karty nouveau; hybridní notebooky dostanou `prime-run` a režim Výkon. Viz [Ovladače](drivers.html) (anglicky).

## Jak pošlu soubory do telefonu nebo jiného počítače?

Pomocí [LuxDrop](luxdrop.html): šifrovaný přenos souborů mezi počítači LuxOS a aplikacemi kompatibilními
s LocalSend (telefony, tablety, Windows, Linux).

## Jaké jazyky LuxOS podporuje?

Instalátor a aplikace LuxOS jsou ve 13 jazycích, mj. angličtina, čeština, slovenština, němčina, polština,
francouzština, španělština, italština, portugalština, nizozemština, maďarština, švédština a ukrajinština.

## Co když se něco rozbije?

Viz [Řešení potíží](troubleshooting.html) (anglicky). Vraťte se ke snímku před poslední aktualizací,
spusťte předchozí jádro z nabídky spouštění, `lux fix` opraví zamčenou databázi a podpisové klíče
a `lux doctor` zkontroluje systém.

## Kam hlásit chyby a posílat dotazy?

Pošlete hlášení z aplikace **Zpětná vazba** (nebo požádejte LuxAI), založte issue na
[GitHubu](https://github.com/luxopes/LuxOS-Arch/issues), nebo napište na info@lux-ai.cz.
