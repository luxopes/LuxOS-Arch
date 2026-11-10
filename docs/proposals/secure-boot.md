# Secure Boot v LuxOS

Cíl (priorita vlastníka): LuxOS **musí nastartovat se zapnutým Secure Boot** na běžném počítači
s Windows – ISO (live a instalátor) i nainstalovaný systém – a nikdy neradit „vypněte Secure Boot“.
Cílovka: netechnici přecházející z Windows a firmy (B2B, kde Secure Boot vyžaduje politika).

Tento dokument popisuje, co je hotové **teď** (shim podepsaný Microsoftem + klíč LuxOS v MOK),
co musí udělat správce, jak se převádějí starší instalace a **dlouhodobý plán** (vlastní shim
podepsaný Microsoftem, pak odpadne i krok s MOK).

## 1. Teď: shim od Fedory + klíč LuxOS (MOK)

### Řetěz startu

```
firmware (db: Microsoft UEFI CA 2011 a/nebo 2023)
  └─ shimx64.efi        Fedora shim 16.1-7, podepsaný Microsoftem (2011 i 2023), beze změny
       └─ grubx64.efi   = systemd-boot podepsaný klíčem LuxOS (shim ho ověří klíčem v MokListu)
            └─ vmlinuz-linux-luxos   podepsané klíčem LuxOS (systemd-boot ho ověří přes protokol shim)
                 └─ moduly jádra: ve stromu podepsané jednorázovým klíčem sestavení jádra
```

- **Proč Fedora shim:** jediný hotový, volně šiřitelný (BSD-2-Clause, `files/shim-COPYRIGHT`) shim
  podepsaný Microsoftem **oběma** certifikáty – Microsoft UEFI CA 2011 (starší počítače) i 2023
  (nové počítače a ty, kterým Windows Update starý certifikát odebere). Ověřeno na staženém RPM
  (`shim-x64-16.1-7.x86_64.rpm`, sha512 shodný s AUR `shim-signed`): dva podpisy Authenticode,
  „Microsoft Windows UEFI Driver Publisher“ (CA 2011) a „Microsoft UEFI CA 2023 signer“.
  Vestavěný certifikát dodavatele je Fedora – tím se spustí i zavaděče/jádra Fedory, LuxOS nijak
  neomezuje. MokManager (`mmx64.efi`) je podepsaný Fedorou, shim mu věří. Ubuntu/Debian shim by šel
  taky, ale Fedora je nejrychleji aktualizovaná a balí ji Arch (AUR) – stejný soubor.
- **Proč systemd-boot (ne GRUB):** systemd-boot už LuxOS používá (ISO i nainstalované UEFI
  systémy), má sekci `.sbat` (shim 15.3+ bez ní odmítne zavaděč spustit) a umí ověřit jádro přes
  protokol shim. GRUB z Archu `.sbat` nemá (museli bychom vlastní sestavení a GRUB má historicky
  nejvíc revokací). Jádro sekci `.sbat` nepotřebuje (ověřuje se přes protokol, ne zaváděním shim).
- **initramfs se neověřuje** (typ 1 položky systemd-boot) – stejně jako u Ubuntu/Fedory s GRUB.
  Ochranu initramfs přinese až UKI (viz bod 4).
- **Jádro neběží v lockdown** (`CONFIG_LOCK_DOWN_KERNEL_FORCE_NONE`, `MODULE_SIG_FORCE` vypnuto).
  Proto se nepodepsané moduly DKMS (NVIDIA, broadcom-wl) načtou i se Secure Boot (jen značka
  „tainted“) – **žádný další krok pro uživatele s NVIDIA**. Pro vlastní shim (bod 3) bude lockdown
  povinný; pak přijde na řadu klíč DKMS (viz 1.4).

### 1.1 Co uživatel udělá při prvním startu ISO se zapnutým Secure Boot

Jednou za život počítače (klíč zůstává v NVRAM i po přeinstalaci):

1. Start z USB → modrá obrazovka shim „**Verification failed: (0x1A) Security Violation**“ → **OK**
   (Enter). Shim sám spustí MokManager.
2. „Press any key to perform MOK management“ (odpočet 10 s – při prvním startu z USB ho prodloužit
   nejde, `MokTimeout` umí nastavit jen běžící systém) → libovolná klávesa (mezerník). Po vypršení se
   vrátí obrazovka z kroku 1 – nic se nerozbije.
3. MokManager „Perform MOK management“ → šipka dolů → **Enroll key from disk**.
4. Disk s LuxOS (popisek `ARCHISO_EFI`, obvykle jediný) → soubor **`LUXOS_ENROLL_THIS_KEY.cer`**
   (první položka – `mkarchiso-secureboot.sh` ho zapisuje do FAT jako první).
5. šipka dolů **Continue** → šipka dolů **Yes** → **Reboot**.
6. Počítač nastartuje znovu z USB → nabídka LuxOS → live systém se Secure Boot.

Celkem 11 stisků (Enter, mezerník, šipky), bez hesla a bez psaní. Totéž dělá Ventoy (soubor
`ENROLL_THIS_KEY_IN_MOKMANAGER.cer`). Instalovaný systém pak startuje rovnou – klíč už je zapsaný.
Návod s obrázky: luxos-docs `luxos/secure-boot.md` (offline v LuxOS) a web
`/docs/luxos/secure-boot-first-start.html` (cs + en, snímky z VM).

### 1.2 Nainstalovaný systém

`luxos-secureboot` (nový balík, závislost `luxos-care`, takže přijde i starším instalacím):

- ESP: `EFI/LuxOS/shimx64.efi`, `mmx64.efi`, `grubx64.efi` (= podepsaný systemd-boot),
  `luxos-secureboot.cer` (pro „Enroll key from disk“ např. po resetu firmwaru).
- Záložní `EFI/BOOT/BOOTX64.EFI` = shim (+ `fbx64.efi` a `mmx64.efi` vedle, **žádný `grubx64.efi`**,
  viz 1.6) – **jen** když tam nic není, je tam systemd-boot nebo už náš shim. Cizí zavaděč (Windows,
  shim jiné distribuce) ani cizí `EFI/BOOT/grubx64.efi` se nikdy nepřepisuje.
- Položka UEFI „LuxOS“ → `\EFI\LuxOS\shimx64.efi` – první v BootOrder při každém startu (viz 1.6).
  Stará přímá položka `\EFI\systemd\systemd-bootx64.efi` zůstává jako záloha, dokud jednou
  nenastartuje cesta přes shim (systemd-boot zapíše `LoaderImageIdentifier` = `…\grubx64.efi` a shim
  v tomto startu založí `SbatLevelRT`/`MokListRT` – samotný název grubx64.efi nestačí, Acer „Linpus
  lite“ spouští `EFI/BOOT/grubx64.efi` bez shim); pak ji `luxos-secureboot-sync.service` smaže. Smaže se jen položka s názvem LuxOS na našem ESP (ne „Linux Boot Manager“ jiné distribuce).
- `systemd-boot` a `vmlinuz` na ESP i ve snímcích (luxos-care kopíruje `/boot/vmlinuz-linux-luxos`)
  jsou podepsané, protože podepsané jsou už v balících – snímky systému tak startují se Secure Boot
  bez další práce.
- Bez Secure Boot shim jen spustí systemd-boot: start stejný jako dřív.
- Nepodepsaný systemd-boot v balíku (testovací/neoficiální sestavení) → `sync` nic nemění.
- Příkazy: `luxos-secureboot status` (secure_boot, boot_path, luxos_key, kernel, loader, boot_current,
  boot_first, boot_next, secure_boot_ready, enroll_pending/enroll_password, rady `hint=`; bez roota
  hodnoty z oddílu EFI ze stavu služby `/run/luxos-secureboot/status`, jinak `unknown`),
  `luxos-secureboot check` (připraveno k zapnutí Secure Boot: klíč zapsaný, start přes shim, shim
  první v pořadí, podepsané jádro; jednou i jako oznámení po přihlášení), `sudo luxos-secureboot
  fix-boot` (pořadí + BootNext hned), `sudo luxos-secureboot enroll` (příprava zápisu klíče s jednorázovým
  heslem – 8 číslic, stejné na každé klávesnici, protože firmware má vždy americké rozložení; heslo jen
  přes stdin, ne v argumentech procesu; nastaví `MokTimeout` na 60 s místo 10 s – po vypršení shim
  žádost zahodí), `sudo luxos-secureboot cancel`. Hlášky přeložené (luxos-i18n, 13 jazyků).
- **Instalátor se Secure Boot vypnutým** (USB nastartované bez Secure Boot na počítači s klíči
  Microsoftu): `luxos-install` (`SECUREBOOT_ENROLL=auto`, výchozí) připraví zápis klíče LuxOS už při
  instalaci a heslo ukáže na konci (`@@NOTICE` v grafickém instalátoru). První start: klávesa → Enroll
  MOK → Continue → Yes → heslo → Reboot; Secure Boot pak jde kdykoli zapnout bez dalšího kroku.
  `yes` = vždy, `no` = nikdy. Se Secure Boot zapnutým už klíč zapsaný je (jinak by USB nenastartovalo).
- **Snímky a předchozí jádro z doby před podepisováním:** podepsat je nejde (klíč má jen správce), proto
  `luxos-care` jejich položku jen označí „… - needs Secure Boot off“ (kontrola: certifikát LuxOS
  v podpisu Authenticode souboru vmlinuz) a **LuxOS Recovery** v takovém případě startuje s jádrem
  hlavní položky (vždy podepsané). Výchozí položka je vždy hlavní (podepsané jádro z balíku).

### 1.3 Převod existujících instalací 1.0.x (bez zásahu uživatele, bez rizika)

1. `lux update` → nový `luxos-care` přitáhne `luxos-secureboot` → hook po transakci spustí
   `luxos-secureboot sync`: soubory na ESP (atomicky `.luxos-new` + `mv`, fsync), nová položka UEFI
   na prvním místě, stará přímá položka zůstává druhá.
2. Další start: firmware spustí shim (Secure Boot je vypnutý → shim neověřuje) → systemd-boot →
   LuxOS. Kdyby shim na nějakém firmwaru selhal, firmware přejde na další položku = stará přímá.
3. `luxos-secureboot-sync.service` při startu uklidí starou položku (až po úspěšném startu přes shim).
4. Kdo chce zapnout Secure Boot: `sudo luxos-secureboot enroll` → restart → MokManager: Enroll MOK →
   Continue → Yes → heslo → Reboot → v nastavení firmwaru zapnout Secure Boot. Nebo rovnou zapnout
   Secure Boot – shim ukáže chybu, MokManager → Enroll key from disk → `EFI/LuxOS/luxos-secureboot.cer`.

Nic z toho systém nemůže „zabít“: soubory se jen přidávají, stará cesta zůstává, BIOS/GRUB a
`BOOTLOADER=none` se přeskočí.

### 1.4 Moduly jádra a ovladače mimo strom

| Moduly | Řešení teď | Se Secure Boot |
|---|---|---|
| ve stromu `linux-luxos` | `CONFIG_MODULE_SIG_ALL`, jednorázový klíč sestavení (luxos-kernel CI), veřejná část v jádře | načtou se, bez značky |
| DKMS (`nvidia-open-dkms`, `nvidia-580xx/470xx-dkms`, `broadcom-wl-dkms`) | dkms je podepíše klíčem počítače `/var/lib/dkms/mok.key` (dkms ho vytvoří sám; při první instalaci v chrootu ne – `try_sign_modules=not_in_chroot`, až při dalším sestavení), jádro podpis nevyžaduje | načtou se (bez zapsaného klíče se značkou „tainted“) |
| klíč DKMS v MOK | volitelně: `sudo luxos-secureboot enroll` ho přidá do **stejné** žádosti jako klíč LuxOS | moduly bez značky; připraveno na lockdown |

Zvolená varianta je nejbezstarostnější: NVIDIA funguje se Secure Boot hned, bez druhého kroku
v MokManageru. Předpřipravené podepsané moduly NVIDIA z CI by vyžadovaly klíč LuxOS na GitHubu
(nepřijatelné) nebo podpis u správce pro každou verzi jádra × ovladače – zbytečné, dokud jádro
podpisy nevynucuje. Ověřeno ve VM testovacím modulem mimo strom (viz Testy).

### 1.5 Zbývající rizika (teď)

- **Počítače „Secured-core“** (některé Lenovo, Surface, nové Dell/HP) mají v továrním nastavení
  **vypnutý** „Microsoft 3rd-party UEFI CA“ – shim tam firmware odmítne (stejně jako Ubuntu/Fedoru).
  Řešení je jedno zaškrtnutí ve firmwaru („Allow Microsoft 3rd Party UEFI CA“) – návod v dokumentaci;
  vypínat Secure Boot netřeba. Simulace ve VM (`vars-win-only.fd`): firmware shim odmítne.
- **Počítače jen s UEFI CA 2023** (po aktualizaci db/dbx z Windows Update) – Fedora shim 16.1-7 má
  i podpis 2023 → funguje. Až Microsoft revokuje 2011 (dbx), funguje dál podpis 2023.
- **SBAT revokace:** shim 16 sám zapisuje `SbatLevel`; starý GRUB jiné distribuce na dual-bootu může
  přestat startovat se Secure Boot (týká se všech distribucí se shim 16). Fedora shim aktualizovat
  při každé nové verzi (`_shimver/_shimrel` v PKGBUILD + sha512).
- **Snímky se starým jádrem** uložené před první podepsanou verzí (sady jádra z doby 1.0.1) a
  „previous kernel“ se Secure Boot nenastartují (nepodepsané jádro); v nabídce jsou označené
  „- needs Secure Boot off“, zmizí samy při úklidu snímků (5 posledních). Bez Secure Boot startují dál.
  LuxOS Recovery se v tom případě přepne na podepsané jádro hlavní položky. Automatický návrat po
  3 neúspěšných startech (boot counting) na nepodepsané předchozí jádro se Secure Boot nepomůže –
  do první aktualizace jádra po přechodu.
- **Paměť UEFI Shell a Memtest86+ na ISO** jsou nepodepsané → se Secure Boot jejich položka hlásí
  chybu (živý systém i instalace fungují).
- **Ztráta klíče LuxOS** = každý počítač musí zapsat nový klíč. Proto záloha v Trezoru jako klíč
  repozitáře. Únik klíče = kdokoli podepíše zavaděč, kterému věří počítače s klíčem LuxOS v MOK →
  zneplatnit (`mokutil --delete`/MokX z aktualizace) a vydat nový. Proto HSM v bodu 3.

### 1.6 Pořadí startu ve firmwaru (Acer/Insyde, HP, Lenovo)

Skutečný případ (Acer majitele, 2026-11-10): po `enroll` a restartu se MokManager neukázal. Firmware si
pro záložní `\EFI\Boot\grubx64.efi` (kopie systemd-boot vedle shim v `EFI/BOOT`) sám založil položku
„Linpus lite“ a dal ji první; položka shim byla čtvrtá za USB, start šel přes starou přímou položku.
MokManager ukazuje jen shim – start tedy musí jít přes položku shim.

Zvažované možnosti pro záložní `EFI/BOOT` (shim jako `BOOTX64.EFI` napevno spouští `grubx64.efi` ze
svého adresáře, pokud mu položka nepředá jinou cestu):

| Možnost | Proč (ne) |
|---|---|
| (a) dál `EFI/BOOT/grubx64.efi` | Acer pro něj zakládá „Linpus lite“ na prvním místě: start bez shim, se Secure Boot nepodepsaný Microsoftem → selže a MokManager se nikdy neukáže |
| (b) **fallback shim**: `EFI/BOOT/fbx64.efi` + `EFI/LuxOS/BOOTX64.CSV` | **zvoleno** – standard Fedora/RHEL/Ubuntu; shim spuštěný jako `BOOTX64.EFI` místo `grubx64.efi` spustí fallback (podepsaný Fedorou, vendor cert v shim), ten podle CSV založí nebo vrátí na první místo položku „LuxOS“ → shim a spustí ji. Žádný soubor, pro který by firmware zakládal vlastní položky; po resetu NVRAM se položka obnoví sama |
| (c) druhá fáze přes load option (`efibootmgr … --unicode '\EFI\LuxOS\grubx64.efi'`) | shim to umí, ale jen u položky UEFI – start záložní cestou (bez položky) žádné load options nemá, takže pro `EFI/BOOT` nepomůže; položka `EFI/LuxOS` ho nepotřebuje |
| (d) jen přeskládat/mazat položky | nutné i tak (níže), ale samo nestačí – firmware „Linpus lite“ při každém startu znovu založí, dokud soubor existuje |

K (b) navíc (d): `sync` (služba při každém startu, hook po aktualizaci) a `fix-boot`/`enroll`:
- smaže položky, které ukazují na `EFI/BOOT/grubx64.efi` **na našem ESP**, když tam soubor už není
  (cizí `grubx64.efi` jiného systému i položky jiných disků zůstávají),
- dá položku shim na první místo, ostatní (Windows…) ve stejném pořadí za ni,
- **BootNext** = shim: vždy po `enroll`/`fix-boot`, při startu, když čeká zápis klíče, start nešel přes
  shim nebo pořadí nejde zapsat; firmware, který pořadí ignoruje nebo ho sám mění (zapamatováno
  v `/var/lib/luxos-secureboot/firmware-quirk`), dostane BootNext i při každém vypnutí (`ExecStop`).
  BootNext je jednorázový a firmware ho dodržuje i tam, kde zápis BootOrder ignoruje.
- Instalátor: `uefi_luxos_first` bere přednostně položku se zavaděčem instalace (shim), ne starou
  přímou položku na sdíleném ESP, a nastaví BootNext na první start; v chrootu `enroll` položky
  UEFI nemění (dělá je instalátor z živého systému).

Fallback v `EFI/BOOT` resetuje počítač s TPM po založení položky (kvůli měření) – firmware, který by
BootOrder ignoroval a startoval jen záložní cestu, by se mohl zacyklit; stejné riziko nesou všechny
distribuce s fbx64 (Fedora, Ubuntu) a v praxi se neprojevuje, protože položku najde a jen ji spustí.

## 2. Klíč a podepisování (správce)

- Klíč Secure Boot: RSA 3072, SHA-256, 30 let (firmware ani shim platnost nekontrolují), jen
  `codeSigning`, **bez** OID „jen moduly jádra“ (1.3.6.1.4.1.2312.16.1.2) – s ním by shim klíčem
  zavaděč neověřil.
- Místo: Trezor `/safe/$USER/luxos-signing-sb` (doporučeno), jinak `~/.local/share/luxos/signing-sb`
  (adresář 0700, `luxos-secureboot.key` 0600, `.crt` PEM, `.cer` DER). Nikdy v gitu ani na GitHubu.
- **CI staví nepodepsané** balíky i ISO. Podepisuje se jen u správce, před podpisem GPG:
  - `./build.sh packages` (klíč z Trezoru se připojí do kontejneru jako `/sb-signing`, z Trezoru přes
    kopii v RAM) – `container-build.sh` podepíše `linux-luxos` (vmlinuz) a `luxos-secureboot`
    (systemd-boot) a ověří podpis, pak GPG + `repo-add`.
  - Balík z CI ručně: `scripts/sb-sign.sh package out/ci-pub/.../linux-luxos-*.pkg.tar.zst`
    (přebalí na místě, změní jen podepsaný soubor, jeho řádek v `.MTREE` a `size` v `.PKGINFO`;
    starý `.sig` smaže) → `gpg --detach-sign` → `repo-add`.
  - `scripts/publish-repo.sh` odmítne zveřejnit `[luxos]`, kde jádro nebo systemd-boot nejsou
    podepsané klíčem LuxOS (`LUXOS_ALLOW_UNSIGNED_EFI=1` jen výjimečně).
  - **ISO** se dál staví na GitHub Actions ze zveřejněného (už podepsaného) repozitáře – soukromý
    klíč není potřeba: `container-build.sh` přidá do mkarchiso doplněk
    `scripts/mkarchiso-secureboot.sh` (shim jako `BOOTX64.EFI`, podepsaný systemd-boot jako
    `grubx64.efi`, MokManager, `LUXOS_ENROLL_THIS_KEY.cer` v kořeni EFI oddílu).
- `./build.sh iso-test` / CI `iso-test`: jednorázový testovací klíč Secure Boot (zaniká s
  kontejnerem), certifikát `out/luxos-test-secureboot.cer` vedle ISO.

### Co musí správce udělat (jednou)

```bash
luxos-safe unlock
scripts/sb-sign.sh init        # klíč do /safe/$USER/luxos-signing-sb, veřejný certifikát do
                               # packages/luxos-secureboot/files/luxos-secureboot.pem
git add packages/luxos-secureboot/files/luxos-secureboot.pem && git commit -m "Secure Boot: public LuxOS certificate"
```

Bez `luxos-secureboot.pem` se balík `luxos-secureboot` nesestaví (a `./build.sh packages` skončí
s návodem) – záměrně, aby se omylem nevydal balík bez certifikátu. Pak běžně `./build.sh packages`
(Trezor odemčený) a vydání jako dosud; nové ISO po zveřejnění repozitáře.

## 3. Dlouhodobě: vlastní shim podepsaný Microsoftem

S vlastním shim má LuxOS svůj certifikát **vestavěný v shim** → systemd-boot a jádro podepsané
klíčem LuxOS shim ověří bez MokListu → **odpadne krok s MokManagerem**, ISO nastartuje se Secure
Boot rovnou (jako Ubuntu/Fedora).

### Postup

1. **Firma** (vlastník ji zakládá) – Microsoft podepisuje jen organizacím.
2. **EV certifikát pro podpis kódu** (Extended Validation, na firmu; DigiCert, Sectigo, GlobalSign…;
   cca 300–700 USD/rok, token/HSM je u EV povinný). Slouží k registraci a odesílání do
   **Microsoft Partner Center – Hardware Dev Center** (účet zdarma).
3. **Klíč LuxOS pro shim v HSM** (YubiHSM 2 / Nitrokey HSM / cloudové HSM): shim-review se ptá, jak
   jsou klíče chráněné; soukromý klíč na disku neprojde. Nový vestavěný certifikát musí být **RSA
   ≥ 4096** (pravidlo shim-review). Ideálně CA LuxOS (v shim) + podpisový klíč (podepisuje
   systemd-boot a jádro), aby šlo podpisový klíč vyměnit bez nového shim.
4. **Jádro do souladu:** lockdown (integrity) při Secure Boot (patch jako Fedora/Ubuntu
   `efi: lock down the kernel if booted in secure boot mode` nebo `lockdown=integrity` vynucené),
   tři upstream commity z požadavků shim-review, jednorázový klíč modulů (už je), žádné načítání
   nepodepsaného jádra (kexec jen podepsané – `KEXEC_SIG` už je). Pak **DKMS potřebuje klíč v MOK**
   (Ubuntu postup: instalátor vytvoří klíč DKMS, zapíše přes `mokutil --import` s jednorázovým
   heslem – připravené v `luxos-secureboot enroll`), nebo podepsané předsestavené moduly NVIDIA.
5. **SBAT:** vlastní řádek `shim.luxos` v shim, `systemd-boot.luxos,1,LuxOS,...` v systemd-boot
   (vlastní sestavení systemd-boot s `-Dsbat-distro=luxos`, nebo `objcopy --add-section .sbat`),
   řádky přidat k těm z Archu (ne nahradit).
6. **Reprodukovatelné sestavení** shim z tarbalu 16.x (Dockerfile, `docker build .` musí dát
   stejný binár), NX kompatibilita (celý řetěz) nebo výjimka.
7. **shim-review:** fork `rhboot/shim-review`, vyplnit šablonu (kontakty s PGP – dvě osoby, ověří je
   zašifrovaným e-mailem), přidat shim, logy, certifikát, tag `luxos-shim-x86_64-RRRRMMDD`, issue.
   Recenze dělají dobrovolníci – rychleji to jde, když LuxOS recenzuje přihlášky jiných.
   Čekání **2–3 měsíce**, i víc.
8. Po štítku „accepted“: shim zabalit do `.cab`, podepsat EV certifikátem, odeslat v Partner Center
   („UEFI submission“) → Microsoft vrátí shim podepsaný **pouze Microsoft UEFI CA 2023** (od
   27. 6. 2026 už Microsoft 2011 nepodepisuje). Několik dní.
9. Vydat: `luxos-secureboot` s vlastním shim; MokManager zůstává pro klíče DKMS a obnovu.

### Časový plán a náklady (odhad)

| Krok | Doba | Náklady |
|---|---|---|
| firma, EV certifikát | 2–6 týdnů (ověření firmy) | 300–700 USD/rok |
| HSM | dny | 0 (cloud, platí se provoz) – 650 USD (YubiHSM 2) |
| úpravy jádra (lockdown), SBAT, reprodukovatelný shim | 2–4 týdny práce | – |
| shim-review | 2–3 měsíce a víc | 0 (vlastní recenze jiných) |
| podpis Microsoftem | dny | 0 |

Celkem realisticky **4–6 měsíců**. Do té doby platí bod 1 (funguje na stejných počítačích, jen
s jedním krokem v MokManageru). Pozor: shim podepsaný jen CA 2023 nenastartuje na počítačích, které
ještě nemají v db „Microsoft UEFI CA 2023“ (starší bez aktualizací Windows) – i proto má smysl
Fedora shim (2011 + 2023) držet jako zálohu, dokud se 2023 nerozšíří všude.

### 4. Dál: UKI

Unified Kernel Image (jádro + initramfs + příkazová řádka v jednom podepsaném EFI souboru, `ukify`)
uzavře poslední mezeru (initramfs a cmdline nejsou ověřené) a je základ pro dm-verity / podepsaný
`/usr` (viz system-protection v luxos-docs). Vyžaduje podpis u správce pro každé jádro × initramfs
→ initramfs se staví na počítači, takže buď obecný initramfs v balíku (jako Fedora/Ubuntu Core),
nebo podpis klíčem počítače v MOK/TPM. Až po vlastním shim.

## Testy

QEMU + OVMF se Secure Boot (`OVMF_CODE.secboot.4m.fd`, SMM) a klíči Microsoftu
(`virt-fw-vars --enroll-microsoft --microsoft-db all --microsoft-kek all --sb`, balík virt-firmware),
`scripts/test-vm.sh live|disk --secureboot` (`LUXOS_VM_SB_VARS`, `LUXOS_VM_SERIAL`, `LUXOS_VM_VNC`),
`scripts/vmctl.py` (klávesy, snímky, příkazy přes guest agenta, `quit`). Testovací ISO a balíky
podepsané jednorázovým klíčem (`scripts/sb-sign.sh test-key`), ne klíčem LuxOS. Výsledky 2026-11-10:

| # | Test | Výsledek |
|---|---|---|
| 1 | ISO 1.0.1, Secure Boot zapnutý, klíče Microsoftu | firmware odmítne: „Access Denied -- rejected probably by Secure Boot“ |
| 2 | nové ISO: shim → „Verification failed“ → MokManager → Enroll key from disk (`LUXOS_ENROLL_THIS_KEY.cer` první) → Reboot | živý systém, `mokutil --sb-state`: SecureBoot enabled, certifikát LuxOS v klíčence `.machine`, `boot_path=shim`; 11 kláves |
| 3 | instalace bez obsluhy se Secure Boot, restart | položka `LuxOS → \EFI\LuxOS\shimx64.efi` první, `EFI/LuxOS` + záložní `EFI/BOOT`, start se Secure Boot, plocha; `bootctl`: Secure Boot enabled (user) |
| 4 | snímek (`luxos-care snapshot`, `bootctl set-oneshot`) | start snímku se Secure Boot (`rootflags=subvol=@snapshots/…`, overlay) |
| 4b | snímky pořízené před podepsaným jádrem (převod 1.0.1) | položky „… - needs Secure Boot off“, LuxOS Recovery přepnuté na `/vmlinuz-linux-luxos` |
| 5 | instalace 1.0.1 (Secure Boot vypnutý) → `lux install` luxos-care 16 + luxos-secureboot, podepsané jádro | nová položka shim první, stará zůstala; restart: start přes shim, služba smazala starou položku; `enroll` → MokManager (60 s) Enroll MOK → heslo → Reboot → klíč zapsaný; Secure Boot zapnutý ve firmwaru → start, plocha |
| 6 | instalace z nového ISO se Secure Boot vypnutým (`SECUREBOOT_ENROLL=auto`) | instalátor ukázal heslo, první start MokManager → Enroll MOK → heslo; pak Secure Boot zapnutý → start bez dalšího kroku |
| 7 | modul mimo strom, Secure Boot, bez lockdown | nepodepsaný: načte se, taint O+E; podepsaný klíčem DKMS po zápisu do MOK (`enroll`): jen taint O, bez „verification failed“ |
| 8 | firmware jen s Microsoft UEFI CA 2011 | shim přijatý (podpis 2011) |
| 9 | firmware jen s certifikáty Windows (Secured-core bez CA třetích stran) | odmítnuto před shim – návod v dokumentaci |

| 10 | přesný stav z Aceru (stará přímá položka, „Linpus lite“ → `EFI/BOOT/grubx64.efi` první, shim za DVD, starý `enroll`), Secure Boot vypnutý | **dříve:** firmware spustil „Linpus lite“, systemd-boot bez shim, žádný MokManager, `status` hlásil `boot_path=shim` |
| 11 | nový `sync` na tomto stavu, `enroll`, pak firmware znovu založí „Linpus lite“ první | `EFI/BOOT/grubx64.efi` pryč, „Linpus lite“ smazaná, shim první, BootNext → start přes shim i s „Linpus lite“ první → MokManager → Enroll MOK → heslo; další start přes shim: stará položka smazaná, `check`: „Secure Boot ready“, oznámení |
| 12 | položky LuxOS smazané (reset NVRAM), Secure Boot zapnutý | firmware → `EFI/BOOT/BOOTX64.EFI` (shim) → `fbx64.efi` založil „LuxOS“ → shim (první) → systemd-boot a jádro ověřené klíčem z MOK → živý systém, `SecureBoot enabled` |

Opraveno při testech: mokutil 0.7 píše výzvy hesla na stdout (soubor s hashem byl neplatný a `enroll`
selhal), heslo se mazalo i při čekající žádosti, `sbverify --cert` hlásí „OK“ i pro cizí řetězce
(Microsoft shim) – kontrola teď vyžaduje certifikát LuxOS přímo v podpisu, `grep -q` s pipefail
v `container-build.sh` (ISO bez Secure Boot), `awk -v` a zpětná lomítka cest, název `BOOTx64.EFI`
v mkarchiso, MokManager 10 s nestačil (`MokTimeout` 60 s).

- Jednotkové: `packages/luxos-secureboot/tests/test-luxos-secureboot.sh` (ESP, záložní zavaděč,
  cizí zavaděče, položky UEFI a jejich úklid, zápis klíče, heslo, stav; model NVRAM s „firmwarem“:
  přesný výpis z Aceru, HP/Lenovo vrací Windows dopředu, firmware ignorující BootOrder s BootNext,
  stav bez roota, `check`, `fix-boot`, `notify`), `packages/luxos-installer/tests/
  test-boot-entries.sh` (položka shim na první místo BootOrder), `packages/luxos-care/tests`
  (označení nepodepsaných sad jádra, LuxOS Recovery, předchozí jádro).
