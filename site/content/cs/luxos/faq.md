# LuxOS – časté otázky

## Co je LuxOS?

LuxOS je rychlý a lehký linuxový systém postavený na Arch Linuxu s prostředím ve stylu macOS (pod ním je
Xfce). Má vlastní správce balíků `lux`, vlastní sestavení jádra `linux-luxos`, automatické ovladače,
AI asistenta LuxAI, terminálového programovacího agenta Lux Code a vlastní programovací jazyk LSL.
Je to průběžně aktualizovaný systém (rolling release), zatím ve verzi beta (0.9.x, jméno „Polaris“).

## Je LuxOS zdarma? Jakou má licenci?

ISO si můžete stáhnout zdarma z webu LuxOS. Kód LuxOS (balíky `luxos-*`, `lux`, `luxdrop`, skripty
a instalátor) je pod licencí GPL-3.0-or-later; balíčky třetích stran mají vlastní licence. LuxAI
používá účet LuxAI s měsíčním limitem spotřeby.

## Jaký hardware LuxOS potřebuje?

64bitový počítač (x86_64) s UEFI nebo BIOS a diskem alespoň 20 GB. Instalace trvá zhruba 10 minut a
potřebuje internet. Ovladače grafiky Intel, AMD a NVIDIA, Wi-Fi, zvuku, kamer a virtuálních počítačů se
rozpoznají automaticky. Viz [Podporovaný hardware](hardware.html).

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

## Kde je pacman? Jak instaluji programy?

Příkaz `pacman` v LuxOS není, správce balíků je `lux`. Když napíšete příkaz pacmanu, shell ukáže odpovídající
příkaz `lux` (`pacman -Syu` se změní na `lux update`). `lux install` hledá v repozitářích LuxOS a Arch,
v aplikacích `.lux`, na Flathubu a v komunitním repozitáři (AUR); balíčky z AUR se zkontrolují a sestaví
v Sandboxu. Můžete použít i grafický [Obchod LuxOS](store.html). Viz
[Správa balíků pomocí lux](package-management.html) (anglicky).

## Co je LuxAI?

LuxAI je AI asistent LuxOS, desktopová aplikace s režimem Chat a režimem Agent, který umí pracovat
s počítačem, hledat na webu a číst offline příručku LuxOS. Před každou rizikovou akcí se ptá. Viz [LuxAI](luxai.html).

## Potřebuji pro LuxAI účet?

Ano. LuxAI, Lux Code a LSL IDE sdílejí jeden účet LuxAI, který můžete založit v instalátoru nebo v
aplikaci **Účet LuxAI**. Viz [Účet LuxAI](luxai-account.html) (anglicky).

## Co je Lux Code?

Lux Code je AI agent pro programování v terminálu, napsaný v LSL. Upravuje soubory, spouští příkazy
a testy a používá váš účet LuxAI. Viz [Lux Code](lux-code.html).

## Co je LSL?

LSL (Lux Simple Lang) je programovací jazyk LuxOS, kterým jsou napsané systémové aplikace a který je
k dispozici všem: skripty, nástroje příkazové řádky i nativní programy. Viz [přehled LSL](../lsl/overview.html) (anglicky).

## Jak mě LuxOS chrání před škodlivými programy?

**Lux Guard** kontroluje programy ze stažených souborů, příloh a USB při spuštění a nebezpečné pustí
jen v Sandboxu. [Sandbox](sandbox.html) je izolovaný systém pro nedůvěryhodné aplikace a [Trezor](safe.html)
šifrovaná složka s vlastním heslem. Balíky jsou podepsané. Viz [Lux Guard](guard.html) (anglicky).

## Jak ověřím stažené ISO?

Spusťte `sha256sum -c SHA256SUMS`, naimportujte klíč LuxOS příkazem `gpg --import luxos.gpg` a ověřte
podpis `gpg --verify luxos-VERZE-x86_64.iso.sig luxos-VERZE-x86_64.iso`. Otisk klíče je na úvodní stránce.

## Funguje s grafikou NVIDIA?

Ano. Karty Turing a novější používají otevřený ovladač NVIDIA, Maxwell, Pascal a Volta větev 580xx, starší
karty nouveau; hybridní notebooky dostanou `prime-run`. Viz [Ovladače](drivers.html) (anglicky).

## Jak pošlu soubory do telefonu nebo jiného počítače?

Pomocí [LuxDrop](luxdrop.html): šifrovaný přenos souborů mezi počítači LuxOS a aplikacemi kompatibilními
s LocalSend (telefony, tablety, Windows, Linux).

## Jaké jazyky LuxOS podporuje?

Instalátor a aplikace LuxOS jsou ve 13 jazycích, mj. angličtina, čeština, slovenština, němčina, polština,
francouzština, španělština, italština, portugalština, nizozemština, maďarština, švédština a ukrajinština.

## Co když se něco rozbije?

Viz [Řešení potíží](troubleshooting.html) (anglicky). LuxOS Care nechává předchozí jádro v nabídce
spouštění, `lux fix` opraví zamčenou databázi a podpisové klíče a `lux doctor` zkontroluje systém. Chyby
a nápady můžete poslat z aplikace Zpětná vazba nebo přes LuxAI.
