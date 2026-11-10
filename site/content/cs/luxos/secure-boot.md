# Secure Boot

LuxOS startuje se **zapnutým Secure Boot** na běžných počítačích s Windows, bez jakékoli změny
v nastavení firmwaru. Jediný krok navíc je jednorázové potvrzení klíče LuxOS při prvním startu (asi
deset stisků kláves, nic se nepíše). Tato stránka popisuje první start, kontrolu stavu a co dělat,
když něco nejde. Kvůli instalaci LuxOS Secure Boot nikdy nevypínejte.

## Jak to funguje

Počítače prodávané s Windows věří jen zavaděčům podepsaným Microsoftem. LuxOS startuje přes
**shim**, malý zavaděč podepsaný Microsoftem (stejný soubor používá Fedora; má podpis certifikátem
Microsoft UEFI CA 2011 i 2023, takže funguje na starších i nových počítačích). shim pak spustí
nabídku LuxOS (systemd-boot) a jádro, obojí podepsané **klíčem LuxOS**.

Firmware klíč LuxOS zatím nezná, a tak se jednou přidá do seznamu klíčů, kterým věří majitel
počítače (**MOK**, Machine Owner Key). To se dělá v **MokManageru**, modré obrazovce, kterou shim
ukáže sám. Klíč v počítači zůstane: přeinstalace LuxOS, aktualizace ani nová jádra už nic dalšího
nepotřebují. Protože Secure Boot zůstává zapnutý, Windows vedle LuxOS funguje jako dřív a BitLocker
nechce obnovovací klíč (vypnutí Secure Boot by si ho vyžádalo).

| Část | Soubor na oddílu EFI | Podepsal |
|---|---|---|
| shim | `EFI/LuxOS/shimx64.efi`, záložní `EFI/BOOT/BOOTX64.EFI` | Microsoft |
| fallback (obnoví položku startu) | `EFI/BOOT/fbx64.efi`, `EFI/LuxOS/BOOTX64.CSV` | Fedora (shim mu věří) |
| MokManager | `EFI/LuxOS/mmx64.efi` | Fedora (shim mu věří) |
| nabídka (systemd-boot) | `EFI/LuxOS/grubx64.efi` | LuxOS |
| jádro | `vmlinuz-linux-luxos` | LuxOS |
| certifikát LuxOS | `EFI/LuxOS/luxos-secureboot.cer`, na USB `LUXOS_ENROLL_THIS_KEY.cer` | – |

## První start z USB

1. Spusťte počítač z USB s LuxOS (klávesa nabídky startu, často F12, F11, F8 nebo Esc).
2. Modrá obrazovka hlásí **Verification failed: (0x1A) Security Violation**. To je v pořádku:
   stiskněte **Enter** (OK).
3. „Press any key to perform MOK management“ odpočítává 10 sekund: stiskněte **mezerník** (jakoukoli
   klávesu). Když čas vyprší, modrá obrazovka z kroku 2 se prostě vrátí.
4. MokManager: **Perform MOK management**. Vyberte **Enroll key from disk** (jednou šipka dolů) a Enter.
5. Vyberte disk (USB s LuxOS, popisek `ARCHISO_EFI`).
6. Soubor **LUXOS_ENROLL_THIS_KEY.cer** je nahoře: Enter.
7. Vyberte **Continue**, pak **Yes** u „Enroll the key(s)?“.
8. Vyberte **Reboot**. Počítač znovu nastartuje z USB, objeví se nabídka LuxOS a živý systém
   poběží se zapnutým Secure Boot.

Nainstalovaný systém pak startuje rovnou, klíč už v počítači je. Snímky každého kroku:
[Secure Boot: první start](secure-boot-first-start.html).

Některé počítače s označením „Secured-core“ (např. část Lenovo, Microsoft Surface, Dell a HP) mají
z výroby vypnutý **Microsoft 3rd-party UEFI CA**. Firmware pak USB odmítne ještě před shim
(„Secure Boot violation“, „Image failed to verify“). V nastavení firmwaru na stránce Security nebo
Secure Boot zapněte **Allow Microsoft 3rd Party UEFI CA** (Surface: „Microsoft & 3rd party CA“).
Secure Boot zůstává zapnutý.

## Počítače, které už LuxOS mají

LuxOS 1.0.1 a starší startoval bez shim. Aktualizace nainstaluje `luxos-secureboot` sama: na oddíl
EFI přidá shim a podepsanou nabídku, novou položku startu „LuxOS“ dá na první místo a stará zůstane
jako záloha, dokud LuxOS jednou nenastartuje přes shim. Počítačům s vypnutým Secure Boot se nic
nemění.

Zapnutí Secure Boot potom:

```
sudo luxos-secureboot enroll
```

Ukáže jednorázové heslo z osmi číslic (jen číslice, rozložení klávesnice nevadí). Restartujte:
objeví se „Press any key to perform MOK management“ a čeká 60 sekund – stiskněte klávesu, vyberte
**Enroll MOK**, **Continue**, **Yes**, napište heslo, **Reboot**. `enroll` zároveň zajistí, že
další start půjde přes shim (viz [Pořadí startu ve firmwaru](#pořadí-startu-ve-firmwaru)), a vypíše,
přes kterou položku. Až `luxos-secureboot check` řekne „Secure Boot je připravený“ (LuxOS to jednou
ukáže i jako oznámení), zapněte Secure Boot v nastavení firmwaru. Bez hesla: zapněte Secure Boot rovnou; když shim ukáže chybu
ověření, vyberte **Enroll key from disk** a soubor `EFI/LuxOS/luxos-secureboot.cer` na oddílu EFI.

## Instalace s vypnutým Secure Boot

Když USB nastartovalo s vypnutým Secure Boot (na počítači, který ho umí), instalátor klíč LuxOS
připraví sám a na konci ukáže jednorázové heslo. Při prvním startu nainstalovaného systému: u „Press
any key to perform MOK management“ stiskněte klávesu, vyberte **Enroll MOK**, **Continue**, **Yes**,
napište heslo, **Reboot**. Od té chvíle jde Secure Boot kdykoli zapnout v nastavení firmwaru bez
dalšího kroku. Instalace bez obsluhy: `SECUREBOOT_ENROLL=auto|yes|no` v `install.conf`.

## Pořadí startu ve firmwaru

MokManager je součást shim, takže modrá obrazovka se ukáže, jen když počítač nastartuje přes položku
**LuxOS → `\EFI\LuxOS\shimx64.efi`**. Některý firmware má s pořadím vlastní hlavu: Acer (Insyde)
si pro každý `\EFI\Boot\grubx64.efi` založí položku „Linpus lite“ a dá ji na první místo, HP
a Lenovo po aktualizaci Windows vrátí dopředu Windows Boot Manager a jiný firmware změny pořadí
rovnou ignoruje. LuxOS si s tím poradí sám:

- V `EFI/BOOT` je shim (`BOOTX64.EFI`), MokManager a fallback shim `fbx64.efi`, ale žádný
  `grubx64.efi`. Když firmware položky ztratí (reset firmwaru, nová baterie), spustí `BOOTX64.EFI`
  a fallback podle `EFI/LuxOS/BOOTX64.CSV` položku „LuxOS“ obnoví a spustí – i se zapnutým Secure
  Boot.
- Při každém startu se položka LuxOS vrátí na první místo; Windows a ostatní položky zůstanou za ní
  ve stejném pořadí. Položky, které firmware založil pro starý `EFI/BOOT/grubx64.efi` LuxOS (Acer
  „Linpus lite“), se smažou; položek jiných systémů a jiných disků se LuxOS nikdy nedotkne.
- Když zápis klíče čeká, když start nešel přes shim a na firmwaru, který pořadí nedodrží, nastaví
  LuxOS navíc **BootNext** – jednorázové „příště spusť tohle“, které firmware dodrží, i když pořadí
  ignoruje – při startu i při vypnutí.

`sudo luxos-secureboot fix-boot` to všechno udělá hned a další start nastaví přes shim. Když se modrá
obrazovka přesto neukáže, otevřete při startu nabídku startu (často F12) a vyberte „LuxOS“.

## Kontrola stavu

```
luxos-secureboot check
luxos-secureboot status
mokutil --sb-state
```

`luxos-secureboot check` řekne „Secure Boot je připravený: teď ho můžete zapnout v nastavení
firmwaru“, jen když je klíč LuxOS zapsaný, tento start šel přes shim, položka LuxOS je první
v pořadí startu a jádro je podepsané; jinak vypíše, co chybí a co spustit.

`luxos-secureboot status` vypíše `secure_boot` (enabled, disabled, setup), `boot_path` (shim nebo
direct), `luxos_key` (enrolled, pending, missing; po startu bez shim unknown), `kernel` (signed /
unsigned), `loader` (installed / missing), `boot_current` a `boot_first` (shim, fallback, direct,
other: čím nastartoval tento start a co je první v pořadí), `boot_next` (jen když je nastavený)
a `secure_boot_ready` (yes, no, on). Bez roota nejde oddíl EFI přečíst; hodnoty pak pocházejí z kontroly
při startu (nebo `unknown`). Řádky `hint=` radí, co dělat. Když zápis klíče čeká, ukáže
`sudo luxos-secureboot status` znovu i heslo. `sudo luxos-secureboot cancel` připravený zápis zruší.

## Ovladače (NVIDIA, Wi-Fi)

Ovladače, které jsou součástí jádra LuxOS, se podepisují při sestavení jádra. Ovladače sestavené
v počítači (DKMS: NVIDIA, Wi-Fi Broadcom) se se Secure Boot načtou taky, nic se nedělá.
`luxos-secureboot enroll` ve stejném kroku přidá i vlastní klíč DKMS počítače
(`/var/lib/dkms/mok.pub`), pokud existuje.

## Když něco nejde

| Příznak | Řešení |
|---|---|
| Modrá obrazovka „Verification failed“ při každém startu | klíč není zapsaný: OK, pak Enroll key from disk (postup výše) |
| „Secure Boot violation“ ještě před obrazovkou LuxOS | ve firmwaru zapnout Microsoft 3rd-party UEFI CA (viz výše) |
| MokManager se po `enroll` neukázal | počítač nenastartoval přes shim (pořadí startu ve firmwaru): `sudo luxos-secureboot fix-boot` a restart, nebo v nabídce startu (F12) vybrat „LuxOS“ |
| U modré obrazovky vypršel čas | žádost se zahodí; znovu `sudo luxos-secureboot enroll` a u modré obrazovky stisknout klávesu (čeká 60 sekund) |
| V nabídce startu je „Linpus lite“ (Acer) | položka, kterou firmware založil pro starý soubor LuxOS; LuxOS ji při dalším startu smaže |
| Položka nabídky končí „- needs Secure Boot off“ | snímek nebo předchozí jádro z doby před podepsanými jádry; startuje jen s vypnutým Secure Boot. Hlavní položka LuxOS a LuxOS Recovery startují vždy; takové položky zmizí s úklidem starých snímků |
| Reset firmwaru | seznam MOK většinou zůstane; jinak klíč znovu z `EFI/LuxOS/luxos-secureboot.cer` |

Memtest86+ a UEFI shell na USB nejsou podepsané a se Secure Boot nestartují; živý systém ani
instalátor to neovlivní.
