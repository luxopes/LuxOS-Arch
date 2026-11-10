# Secure Boot: první start

LuxOS startuje se **zapnutým Secure Boot**. Nevypínejte ho. Při úplně prvním startu z USB s LuxOS
se počítač jednou zeptá, jestli má klíči LuxOS věřit; trvá to necelou minutu a nic se nepíše.
Ovládá se šipkami a klávesou **Enter**. Proč a jak to funguje: [Secure Boot](secure-boot.html).

## 1. Start z USB

Připojte USB s LuxOS a vyberte ho v nabídce startu počítače (často **F12**, **F11**, **F8** nebo
**Esc** hned po zapnutí). Objeví se modrá obrazovka **Verification failed: (0x1A) Security
Violation**. Napoprvé je to v pořádku. Stiskněte **Enter** (OK).

![shim: Verification failed, OK](/assets/secureboot/sb-01-verification-failed.webp)

## 2. Libovolná klávesa

„Press any key to perform MOK management“ odpočítává 10 sekund. Stiskněte **mezerník** (jakoukoli
klávesu). Když čas vyprší, modrá obrazovka z kroku 1 se vrátí – stačí to zkusit znovu.

![MokManager: Press any key to perform MOK management](/assets/secureboot/sb-02-press-any-key.webp)

Otevře se modrá nabídka **MokManageru** **Perform MOK management**. Šipkou dolů přejděte na
**Enroll key from disk** a stiskněte **Enter**.

![MokManager: Enroll key from disk](/assets/secureboot/sb-02-mok-menu.webp)

## 3. Vyberte USB

Vyberte USB s LuxOS (popisek **ARCHISO_EFI**, většinou jediná položka) a stiskněte **Enter**.

![MokManager: výběr disku](/assets/secureboot/sb-03-select-disk.webp)

## 4. Vyberte klíč LuxOS

**LUXOS_ENROLL_THIS_KEY.cer** je první položka: stiskněte **Enter**.

![MokManager: LUXOS_ENROLL_THIS_KEY.cer](/assets/secureboot/sb-04-select-file.webp)

## 5. Pokračovat a potvrdit

Vyberte **Continue**, pak **Yes** u „Enroll the key(s)?“.

![MokManager: Continue](/assets/secureboot/sb-05-continue.webp)

![MokManager: Enroll the key(s)? Yes](/assets/secureboot/sb-06-confirm.webp)

## 6. Restart

Vyberte **Reboot**. Počítač znovu nastartuje z USB.

![MokManager: Reboot](/assets/secureboot/sb-07-reboot.webp)

## 7. LuxOS běží se zapnutým Secure Boot

Na chvíli se ukáže nabídka LuxOS a spustí se živý systém. LuxOS nainstalujte jako obvykle – nainstalovaný
systém startuje rovnou, klíč už v počítači je. V terminálu `mokutil --sb-state` ukáže
`SecureBoot enabled`.

![Živý systém LuxOS se zapnutým Secure Boot](/assets/secureboot/sb-08-live-desktop.webp)

## Když počítač USB odmítne

Když firmware ještě před modrou obrazovkou hlásí „Secure Boot violation“ nebo „Image failed to
verify“, má počítač vypnutý certifikát Microsoftu pro třetí strany (některé notebooky „Secured-core“).
V nastavení firmwaru na stránce Security nebo Secure Boot zapněte **Allow Microsoft 3rd Party UEFI
CA** a zkuste to znovu. Secure Boot zůstává zapnutý. Víc v [Secure Boot](secure-boot.html#když-něco-nejde).

## Když se modrá obrazovka neukáže

Modrou obrazovku ukazuje jen shim. Když LuxOS (nebo Windows) nastartuje bez ní, firmware spustil
nejdřív jinou položku startu: v nabídce startu (často **F12**) vyberte USB, nebo „LuxOS“.
V nainstalovaném LuxOS dá `sudo luxos-secureboot fix-boot` položku LuxOS → shim na první místo
v pořadí startu firmwaru a další start pošle přes shim; LuxOS to dělá i sám při každém startu.
`luxos-secureboot check` řekne, kdy jde Secure Boot zapnout. Víc v
[Secure Boot](secure-boot.html#pořadí-startu-ve-firmwaru).
