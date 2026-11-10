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
**Enroll MOK**, **Continue**, **Yes**, napište heslo, **Reboot**. Pak zapněte
Secure Boot v nastavení firmwaru. Bez hesla: zapněte Secure Boot rovnou; když shim ukáže chybu
ověření, vyberte **Enroll key from disk** a soubor `EFI/LuxOS/luxos-secureboot.cer` na oddílu EFI.

## Instalace s vypnutým Secure Boot

Když USB nastartovalo s vypnutým Secure Boot (na počítači, který ho umí), instalátor klíč LuxOS
připraví sám a na konci ukáže jednorázové heslo. Při prvním startu nainstalovaného systému: u „Press
any key to perform MOK management“ stiskněte klávesu, vyberte **Enroll MOK**, **Continue**, **Yes**,
napište heslo, **Reboot**. Od té chvíle jde Secure Boot kdykoli zapnout v nastavení firmwaru bez
dalšího kroku. Instalace bez obsluhy: `SECUREBOOT_ENROLL=auto|yes|no` v `install.conf`.

## Kontrola stavu

```
luxos-secureboot status
mokutil --sb-state
```

`luxos-secureboot status` vypíše `secure_boot` (enabled, disabled, setup), `boot_path` (shim nebo
direct), `luxos_key` (enrolled, pending, missing), `kernel` (signed / unsigned) a `loader`
(installed / missing). Když zápis klíče čeká, ukáže znovu i heslo. `sudo luxos-secureboot cancel`
připravený zápis zruší.

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
| MokManager se neukázal nebo vypršel čas | žádost se zahodí; znovu `sudo luxos-secureboot enroll` a u modré obrazovky stisknout klávesu (čeká 60 sekund) |
| Položka nabídky končí „- needs Secure Boot off“ | snímek nebo předchozí jádro z doby před podepsanými jádry; startuje jen s vypnutým Secure Boot. Hlavní položka LuxOS a LuxOS Recovery startují vždy; takové položky zmizí s úklidem starých snímků |
| Reset firmwaru | seznam MOK většinou zůstane; jinak klíč znovu z `EFI/LuxOS/luxos-secureboot.cer` |

Memtest86+ a UEFI shell na USB nejsou podepsané a se Secure Boot nestartují; živý systém ani
instalátor to neovlivní.
