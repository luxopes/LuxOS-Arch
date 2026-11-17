# Vydání LuxOS 1.0.2 „Sirius“ – postup

Vydání (rozhodnutí majitele 2026-11-17): **všechno ze staging do stabilního kanálu kromě balíků, které
do stabilního kanálu zatím nepatří** – `luxos-mail`, `luxos-app-studio`, `luxos-icon-studio` a
`luxos-sdk` se vynechají a `lux-code` (případně `lux-code-next`) zůstává ve stabilním kanálu v
dosavadní verzi. To jsou přesně výchozí seznamy `scripts/compose-stable-repo.sh`
(`LUXOS_STABLE_EXCLUDE="luxos-mail luxos-app-studio luxos-icon-studio luxos-sdk"`,
`LUXOS_STABLE_KEEP="lux-code lux-code-next"`), nic se nepřepisuje. Pořád beta. Nové ISO
`luxos-1.0.2-x86_64.iso` jde na web.

Poprvé ve stabilním kanálu: **`luxos-secureboot`** (1.0.0-3, závislost `luxos-care`) a **jádro
`linux-luxos` 7.3.3 podepsané klíčem Secure Boot LuxOS** – viz [Secure Boot na stávajících
stabilních počítačích](#secure-boot-na-stávajících-stabilních-počítačích).

Připravené v repozitáři (větev s tímto souborem):

- `packages/luxos-branding/files/version` → `VERSION=1.0.2`, `CODENAME=Sirius`; `luxos-branding` 1.1.0-29
  (os-release „LuxOS 1.0.2 Sirius“, O tomto počítači, fastfetch, název ISO, `countme v=1.0.2`).
- `packages/luxos-branding/files/whats-new/1.0.2.json` – okno Co je nového (13 jazyků, 8 položek):
  Secure Boot, nová horní lišta + widgety + Hodiny (a automatická barva písma lišty), posun ploch,
  posouvání se setrvačností, Firefox (tlačítka okna, uvítací stránka, bez telemetrie), LuxOS Recovery,
  rychlejší start + méně paměti + instalace na 4 GB RAM, přes sto oprav. Nic o Poště, Lux Code, App
  Studiu, Icon Studiu ani SDK (hlídá test `test_current_notes_skip_staging_only_apps`). Po aktualizaci
  z 1.0.1 se ukáže jen 1.0.2, z 1.0.0 obě (nejnovější první); noví uživatelé ho nevidí (Prohlídka).
- `CHANGELOG.md` – sekce `1.0.2 „Sirius“ – 2026-11-17 (beta)` (8 Nové, 46 Opraveno), položky Pošty
  (5 + 5) zůstaly v nové sekci „Připravuje se“; anglicky `site/content/en/changes/1.0.2-2026-11-17.md`
  a `unreleased.md` (stejné sekce a počty položek, hlídá `scripts/check-site.py`).
- Aktuální verze 1.0.2 na webu (FAQ cs/en), v README a v dokumentaci (`luxos-docs` 1.0.0-70,
  Přehled LuxOS). Verzi na hlavní stránce a v `release.json` bere `build-site.py` z `files/version`,
  ISO z `site/iso.json` (ten se mění až v kroku 9 ze skutečného ISO).
- Oprava testu `packages/luxos-i18n/tests/test_cli_i18n.py`: `desktop-i18n.py` je nástroj pro sestavení
  (volají ho PKGBUILDy, `luxos-i18n` ho neinstaluje), ne program pro uživatele.

Všechny příkazy se spouštějí v kořeni repozitáře `~/LuxOS-Arch`. Klíč LuxOS (otisk
`FD18 5DAB 7701 40E8 9C37 275E 7035 CFDF DCA6 C991`):

```bash
KEY=FD185DAB770140E89C37275E7035CFDFDCA6C991
SIGN=$HOME/.local/share/luxos/signing     # GNUPGHOME s podpisovým klíčem (nebo Trezor /safe/$USER/luxos-signing)
```

## 0. Kontroly před vydáním

Grafické testy jen ve virtuální obrazovce (`scripts/luxos-testguard.sh`), nikdy na skutečné relaci:

```bash
E="env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY nice -n 10"
$E python3 -m unittest packages/luxos-desktop/tests/test_luxos_whats_new.py   # 13 jazyků, verze, zobrazení jednou, bez aplikací jen ze staging
$E python3 -m unittest packages/luxos-i18n/tests/test_cli_i18n.py packages/luxos-store/tests/test_app_catalog.py
$E xvfb-run -a scripts/check-titlebars.sh                                       # každé okno má horní lištu
$E bash packages/luxos-secureboot/tests/test-luxos-secureboot.sh                # ESP, položky UEFI, zápis klíče (vše nahrazené)
$E out/sitevenv/bin/python scripts/build-site.py && $E out/sitevenv/bin/python scripts/check-site.py
```

Očekávání (ověřeno na větvi vydání 2026-11-17): Co je nového 13 testů OK (1 přeskočený test velikostí
ikony okna bez obrazovky), i18n + katalog 29 OK, `check-titlebars.sh` 31× `ok`, Secure Boot
146 ok / 0 failed, `site: LuxOS 1.0.2 (ISO 1.0.1)` a `check-site: … 0 problems`. Dokud není nové ISO,
stránka nabízí ISO 1.0.1 s poznámkou „po instalaci se systém aktualizuje na 1.0.2“.

## 1. Větev do main a na GitHub

CI staví z `main` na GitHubu (`luxopes/LuxOS-Arch`) – i název ISO se bere z `files/version` v checkoutu.

```bash
git switch main && git merge --no-ff release-1.0.2 && git push origin main
```

(Když mezitím `main` zvýšil `pkgrel` `luxos-branding` nebo `luxos-docs`, při sloučení vzít vyšší + 1.)

## 2. luxos-branding 1.1.0-29 a luxos-docs 1.0.0-70 na CI

```bash
out/ci-pub/build.sh luxos-branding luxos-docs        # postupně, každý balík vlastní běh (concurrency)
```

nebo ručně pro každý balík:

```bash
gh workflow run build.yml -R luxopes/LuxOS-Arch --ref main -f target=one -f package=luxos-branding -f channel=staging
gh run list -R luxopes/LuxOS-Arch -w build.yml -L1          # ID běhu
gh run watch -R luxopes/LuxOS-Arch <ID> --exit-status
rm -rf out/ci-pub/luxos-branding
gh run download -R luxopes/LuxOS-Arch <ID> -n single -D out/ci-pub/luxos-branding
```

Artefakt `single` obsahuje `SHA256SUMS` a podsložku `single/` s nepodepsaným balíkem (s `-n single`
leží v `out/ci-pub/<balík>/single/`, pomocník `build.sh` stahuje bez `-n`, takže o úroveň hlouběji –
proto `find`). Kontrola:

```bash
P=$(find out/ci-pub/luxos-branding -name 'luxos-branding-1.1.0-29-any.pkg.tar.zst')
D=$(find out/ci-pub/luxos-docs -name 'luxos-docs-1.0.0-70-any.pkg.tar.zst')
for f in $P $D; do (cd "$(dirname "$(dirname "$f")")" && sha256sum -c SHA256SUMS); done
tar --zstd -xOf $P usr/lib/luxos/version | grep '^VERSION=1.0.2$'
tar --zstd -tf $P | grep 'usr/share/luxos/whats-new/1.0.2.json'
tar --zstd -xOf $P usr/lib/luxos/apply-branding | grep 'PRETTY_NAME="LuxOS 1.0.2 Sirius"'
tar --zstd -xOf $D usr/share/luxos/docs/luxos/overview.md | grep '1.0.2 "Sirius"'
```

Ověřeno na větvi `release-1.0.2` (běh 44056595180, `--ref release-1.0.2`): `sha256sum` OK,
`VERSION=1.0.2`, `CODENAME=Sirius`, `whats-new/1.0.2.json` (shodný se zdrojem), `PRETTY_NAME="LuxOS 1.0.2 Sirius"`.
Pro vydání se balík staví znovu z `main` (krok 1) – obsah je stejný, jen z ověřeného `main`.

## 3. Podpis a přidání do out/repo ([luxos] a [luxos-apps])

`out/repo` musí odpovídat tomu, co je teď ve staging (poslední `publish-repo.sh` do staging šel
z něj). Kontrola rozdílu proti serveru **před** přidáním (prázdný výstup):

```bash
for r in luxos luxos-apps; do
  diff <(tar -xzOf out/repo/$r/x86_64/$r.db.tar.gz --wildcards '*/desc' | grep -A1 '^%FILENAME%' | grep -v '^%\|^--' | sort) \
       <(curl -fsS https://luxos.lux-ai.cz/staging/$r/x86_64/$r.db | tar -xzO --wildcards '*/desc' | grep -A1 '^%FILENAME%' | grep -v '^%\|^--' | sort)
done
```

```bash
d=out/repo/luxos/x86_64
install -m644 $P $d/
GNUPGHOME=$SIGN gpg --detach-sign --no-armor -u $KEY $d/${P##*/}
GNUPGHOME=$SIGN repo-add -s -k $KEY $d/luxos.db.tar.gz $d/${P##*/}
a=out/repo/luxos-apps/x86_64
install -m644 $D $a/
GNUPGHOME=$SIGN gpg --detach-sign --no-armor -u $KEY $a/${D##*/}
GNUPGHOME=$SIGN repo-add -s -k $KEY $a/luxos-apps.db.tar.gz $a/${D##*/}
tar -xzOf $d/luxos.db.tar.gz --wildcards '*/desc' | grep -A1 '^%FILENAME%' | grep luxos-branding     # 1.1.0-29
tar -xzOf $a/luxos-apps.db.tar.gz --wildcards '*/desc' | grep -A1 '^%FILENAME%' | grep luxos-docs     # 1.0.0-70
```

## 4. Staging

```bash
LUXOS_REPO_CHANNEL=staging scripts/publish-repo.sh
```

`publish-repo.sh` před nahráním ověří podpis Secure Boot jádra a systemd-boot (`scripts/sb-sign.sh
verify` na `linux-luxos-*` a `luxos-secureboot-*` z databáze `[luxos]`). Na počítači se
`channel = "staging"`: `sudo lux update`, odhlásit/přihlásit → okno **Co je nového v LuxOS 1.0.2**,
O tomto počítači „Verze 1.0.2 (Sirius)“, `cat /etc/os-release`.

## 5. Stabilní vydání bez balíků jen pro staging

**Nepoužívat `scripts/promote-staging.sh`** – přepnul by `current` na staging včetně Pošty, App Studia,
Icon Studia, SDK a nového Lux Code.

```bash
scripts/compose-stable-repo.sh            # out/repo -> out/repo-stable, výchozí seznamy = rozhodnutí majitele
```

Skript zkopíruje `out/repo` (reflink, zdroj se nemění), z `[luxos-apps]` odebere `luxos-mail`,
`luxos-app-studio`, `luxos-icon-studio` a `luxos-sdk` (databáze, všechny verze souborů, ikona),
`lux-code` (a `lux-code-next`, pokud by byl) nahradí verzí, která je teď na
`https://luxos.lux-ai.cz/repo` (stáhne ji s podpisem a ověří klíčem LuxOS; balík, který ve stabilním
kanálu není, odebere), databáze znovu podepíše a na konci ověří podpisy databází i všech balíků a
vypíše obsah. Zkontrolujte výpis: žádný `luxos-mail`, `luxos-app-studio`, `luxos-icon-studio`,
`luxos-sdk`; `lux-code` ve stabilní verzi; `luxos-branding-1.1.0-29`, `luxos-docs-1.0.0-70`,
`luxos-secureboot-1.0.0-3`, `linux-luxos-7.3.3-1`.

Podpis Secure Boot ve stabilním vydání (totéž dělá `publish-repo.sh`; ověřeno 2026-11-17 na
`out/repo`: `OK linux-luxos-7.3.3-1 … vmlinuz`, `OK luxos-secureboot-1.0.0-3 … systemd-bootx64.efi`):

```bash
s=out/repo-stable/luxos/x86_64
scripts/sb-sign.sh verify $(tar -xzOf $s/luxos.db.tar.gz --wildcards '*/desc' | awk '/^%FILENAME%$/ {getline; print}' \
    | grep -E '^(linux-luxos|luxos-secureboot)-[0-9]' | sed "s|^|$s/|")
```

```bash
LUXOS_REPO_SRC=out/repo-stable scripts/publish-repo.sh      # kanál current = stabilní
for p in luxos-mail luxos-app-studio luxos-icon-studio luxos-sdk; do
  echo "$p $(curl -fsS https://luxos.lux-ai.cz/repo/luxos-apps/x86_64/luxos-apps.db | tar -tz | grep -c "^$p-[0-9]")"   # 0
done
```

`publish-repo.sh` vezme `[luxos-drivers]` z `out/drivers-repo`, katalog Obchodu (`apps.json`,
snímky) vygeneruje z právě skládaného vydání – vynechané aplikace v Obchodě stabilního kanálu nebudou.
Na stabilním počítači `sudo lux update` → Co je nového 1.0.2; Pošta se nenabízí.

Pozn.: `luxos-docs` ve stabilním kanálu obsahuje i stránky o Poště a vývojářských nástrojích (aplikace
v něm zatím nejsou), `CHANGELOG` 1.0.2 v několika položkách zmiňuje Poštu jako jednu z aplikací.

### Secure Boot na stávajících stabilních počítačích

Stabilní 1.0.1 startuje bez shim (systemd-boot přímo). `lux update` na 1.0.2 nainstaluje
`luxos-secureboot` jako závislost `luxos-care` a jeho hook po transakci spustí
`luxos-secureboot sync --quiet`; služba `luxos-secureboot-sync` totéž při každém startu (s nízkou
prioritou, start na ni nečeká).

- **BIOS / GRUB, nebo LuxOS nestartuje ze systemd-boot:** nic („nothing to do“, kód 0).
- **Systemd-boot v balíku nepodepsaný klíčem LuxOS** (neoficiální sestavení): ESP ani položky UEFI se
  nemění. Oficiální balík je podepsaný (ověřeno výše).
- **Secure Boot vypnutý (běžný případ):** na oddíl EFI přibude `EFI/LuxOS` (shim, MokManager,
  podepsaný systemd-boot jako `grubx64.efi`, certifikát). Každý soubor se nejdřív ověří místo na ESP,
  zapisuje se do dočasného souboru, kontroluje proti balíku a teprve pak atomicky přejmenuje –
  plný ESP nic nerozbije (staré soubory zůstanou, hlášení s radou `luxos-care esp-clean`).
  Záložní `EFI/BOOT/BOOTX64.EFI` se nahradí shimem jen tehdy, když je to systemd-boot, náš shim nebo
  náš nedokončený zápis – cizí zavaděč (Windows, jiná distribuce) nikdy. Přidá se položka UEFI
  „LuxOS“ → shim na první místo pořadí a BootNext na ni; **stará přímá položka systemd-boot zůstává
  jako záloha**, dokud LuxOS jednou opravdu nenastartuje přes shim (kdyby shim na nějakém firmwaru
  selhal, firmware pokračuje starou položkou). Bez Secure Boot shim jen spustí systemd-boot – nabídka,
  jádro, šifrovaný disk i rychlost startu stejné jako dřív. Uživatel nic nevidí a nic nemusí dělat;
  oznámení „Secure Boot lze zapnout“ se ukáže jen po `sudo luxos-secureboot enroll` (klíč zapsaný).
- **Secure Boot zapnutý:** stabilní 1.0.1 se zapnutým Secure Boot s klíči Microsoftu vůbec nenastartoval
  („Access Denied“), takové stávající počítače nejsou. Když si uživatel po aktualizaci zapne Secure Boot
  bez `enroll`, shim systemd-boot klíčem LuxOS neověří a sám otevře MokManager („Enroll key from disk“
  → `EFI/LuxOS/luxos-secureboot.cer`); nebo Secure Boot zase vypne – žádná ztráta dat ani zamčení.
  Výjimka: kdo měl Secure Boot s vlastními klíči (např. `sbctl`, bez klíčů Microsoftu), tomu firmware
  shim odmítne a pokračuje starou přímou položkou (ta se pak nikdy nesmaže, protože start přes shim
  neproběhne); systém startuje dál jako dřív, jen firmware může při každém startu krátce ukázat chybu
  ověření (služba `luxos-secureboot-sync` dává položku shim při každém startu zase na první místo).
  LuxOS vlastní klíče Secure Boot nepodporuje; na takovém počítači stačí v db firmwaru
  povolit i Microsoft UEFI CA (pak shim projde a dál platí postup `sudo luxos-secureboot enroll`).
- **Dual boot s Windows a BitLockerem s vypnutým Secure Boot:** když se Windows spouští z nabídky
  systemd-boot, změní se měřený řetězec zavaděčů (navíc shim) a BitLocker se může jednou zeptat na
  obnovovací klíč – stejně jako už dnes po každé aktualizaci systemd-boot. Windows spouštěné přímo
  firmwarem (Windows Boot Manager) se to netýká.

Testy: `packages/luxos-secureboot/tests/test-luxos-secureboot.sh` (146 ok) pokrývá první instalaci se
starou přímou položkou, start mimo shim (nic se nemaže), plný ESP, firmware Acer/HP/Lenovo a cizí
zavaděče; skutečný start ve VM se Secure Boot zapnutým i vypnutým je v `docs/proposals/secure-boot.md`.

## 6. ISO na GitHub Actions

Až je stabilní repozitář zveřejněný (ISO se staví z něj):

```bash
gh workflow run build.yml -R luxopes/LuxOS-Arch --ref main -f target=iso -f channel=stable
gh run list -R luxopes/LuxOS-Arch -w build.yml -L1
gh run watch -R luxopes/LuxOS-Arch <ID> --exit-status        # limit běhu 300 min
rm -rf out/iso-1.0.2
gh run download -R luxopes/LuxOS-Arch <ID> -n iso -D out/iso-1.0.2
I=$(dirname "$(find out/iso-1.0.2 -name 'luxos-1.0.2-x86_64.iso')")   # podle verze gh přímo out/iso-1.0.2 nebo out/iso-1.0.2/iso
```

Co workflow dělá: `scripts/fetch-published-repo.sh` stáhne `[luxos]` a `[luxos-apps]` z
`https://luxos.lux-ai.cz/repo` a ověří podpis databází i každého balíku klíčem z `luxos-keyring`;
`./build.sh iso` (kanál `stable`, `/etc/lux/lux.conf` beze změny) postaví
`out/luxos-1.0.2-x86_64.iso` (shim + podepsaný systemd-boot a jádro z balíků, bez soukromého klíče);
krok Checksums vytvoří `out/SHA256SUMS` (jen toto ISO); artefakt **`iso`** = ISO + `SHA256SUMS`
(bez komprese, 14 dní). **Na server nic nenahrává a nic nepodepisuje** – podpis a nahrání do
`/srv/luxos-site/download/` dělá správce (kroky 7–8). `publish-site.sh` soubory v `/download/`
(`*.iso`, `*.iso.sig`, `SHA256SUMS*`) nemaže ani nepřepisuje.

## 7. Ověření a podpis ISO

```bash
cd $I
sha256sum -c SHA256SUMS
ls -l luxos-1.0.2-x86_64.iso
cd -
LUXOS_VM_ISO=$I/luxos-1.0.2-x86_64.iso scripts/test-vm.sh live
LUXOS_VM_ISO=$I/luxos-1.0.2-x86_64.iso scripts/test-vm.sh live --secureboot   # OVMF se Secure Boot a klíči Microsoftu
```

Ve VM: start (se Secure Boot: modrá obrazovka shim → Enroll key from disk → `LUXOS_ENROLL_THIS_KEY.cer`),
instalace, po přihlášení `cat /etc/os-release` (1.0.2), O tomto počítači, Co je nového se neukáže
(nový uživatel), Obchod (bez Pošty, App Studia, Icon Studia, SDK), `luxos-secureboot status`,
firewall zapnutý (`luxos-firewall status`).

Rozložení `/download/`: `luxos-<verze>-x86_64.iso`, `luxos-<verze>-x86_64.iso.sig` (binární odpojený
podpis), `SHA256SUMS` (řádky všech nabízených ISO, nejnovější první) a `SHA256SUMS.sig`.

```bash
cd $I
GNUPGHOME=$SIGN gpg --detach-sign --no-armor -u $KEY luxos-1.0.2-x86_64.iso
curl -fsS https://luxos.lux-ai.cz/download/SHA256SUMS -o SHA256SUMS.server
cp SHA256SUMS SHA256SUMS.ci
{ cat SHA256SUMS.ci; grep -v ' luxos-1.0.2-x86_64.iso$' SHA256SUMS.server; } > SHA256SUMS
GNUPGHOME=$SIGN gpg --detach-sign --no-armor -u $KEY SHA256SUMS
# ověření veřejným klíčem jako návštěvník webu (dočasný adresář pod out/, ne /tmp)
K=~/LuxOS-Arch/packages/luxos-keyring/files/luxos.gpg
g=$(mktemp -d -p ~/LuxOS-Arch/out); gpg --homedir $g -q --import $K
gpg --homedir $g --verify luxos-1.0.2-x86_64.iso.sig luxos-1.0.2-x86_64.iso
gpg --homedir $g --verify SHA256SUMS.sig SHA256SUMS
sha256sum -c --ignore-missing SHA256SUMS; gpgconf --homedir $g --kill gpg-agent; rm -rf $g
cd -
```

## 8. Nahrání ISO na server

```bash
S=root@185.183.156.25:/srv/luxos-site/download
rsync -P --chmod=F644 $I/luxos-1.0.2-x86_64.iso $I/luxos-1.0.2-x86_64.iso.sig $S/
rsync --chmod=F644 $I/SHA256SUMS $I/SHA256SUMS.sig $S/
curl -sI https://luxos.lux-ai.cz/download/luxos-1.0.2-x86_64.iso | head -3
```

ISO 1.0.1 a 1.0.0 zůstávají v `/download/` (starší odkazy). Na server posílat jen pár požadavků (LUX
Guard na serveru blokuje IP při náporu dotazů).

## 9. site/iso.json

```bash
scripts/update-iso-json.sh $I/luxos-1.0.2-x86_64.iso
git add site/iso.json && git commit -m "Website: ISO 1.0.2 Sirius"
git push origin main
```

Skript vezme verzi z názvu (musí se shodovat s `files/version`, TEST ISO odmítne), velikost,
SHA-256 (porovná ho s `SHA256SUMS` vedle ISO) a dnešní datum (`--date YYYY-MM-DD` jiné) a soubor
zapíše atomicky. Upozorní, když chybí `.sig`.

## 10. Web

```bash
scripts/publish-site.sh
```

Sestaví web, zkontroluje odkazy a nahraje ho. Kontrola: `https://luxos.lux-ai.cz/release.json`
(`version` i `iso.version` 1.0.2), stránka nabízí ISO 1.0.2 s velikostí a datem, odkazy na `.sig` a
`SHA256SUMS` fungují, poznámka o aktualizaci po instalaci je skrytá, `/changes/` i `/cs/zmeny/`
začínají „Coming soon“/„Připravuje se“ (jen Pošta) a pak 1.0.2 „Sirius“.

## 11. countme

`server/countme/deploy.sh` při každém nasazení vytvoří `versions.txt` z nadpisů `## X.Y.Z` v
`CHANGELOG.md`. Verze 1.0.2 se už teď přijímá jako „nejbližší další patch“ nad 1.0.1, takže to
**není naléhavé**, ale po vydání ho majitel spustí znovu, aby 1.0.2 byla v seznamu vydaných verzí
(a přijímala se i 1.0.3):

```bash
server/countme/deploy.sh root@185.183.156.25
```
