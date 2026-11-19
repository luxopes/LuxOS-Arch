# Vydání LuxOS 1.0.3 „Sirius“ – postup

Vydání (plán majitele 2026-11-19): **všechno nejdřív do testovacího kanálu staging jako 1.0.3**. Když
se tam osvědčí, stane se 1.0.3 **první stabilní verzí LuxOS** (bez „beta“) a jde do stabilního kanálu
stejně jako 1.0.2: bez balíků, které do stabilního kanálu zatím nepatří – `luxos-mail`,
`luxos-app-studio`, `luxos-icon-studio` a `luxos-sdk` se vynechají a `lux-code` (případně
`lux-code-next`) zůstává ve stabilním kanálu v dosavadní verzi. To jsou pořád výchozí seznamy
`scripts/compose-stable-repo.sh` (`LUXOS_STABLE_EXCLUDE="luxos-mail luxos-app-studio luxos-icon-studio
luxos-sdk"`, `LUXOS_STABLE_KEEP="lux-code lux-code-next"`), nic se nepřepisuje. **Teď nic nejde do
stabilního kanálu** – kroky 6–12 se dělají až po rozhodnutí majitele, že staging je v pořádku.

Připravené v repozitáři:

- Větev **`release-1.0.3`** (do `main` hned):
  - `packages/luxos-branding/files/version` → `VERSION=1.0.3`, `CODENAME=Sirius`; `luxos-branding` 1.1.0-32
    (os-release „LuxOS 1.0.3 Sirius“, O tomto počítači, fastfetch, název ISO, `countme v=1.0.3`).
  - `packages/luxos-branding/files/whats-new/1.0.3.json` – okno Co je nového (13 jazyků, 8 položek):
    stovky oprav z úplné kontroly, bezpečnější zálohy, bezpečná instalace vedle Windows, aplikace v
    sandboxu nevidí do jiných oken (nedůvěryhodné X11), víc soukromí (Firefox bez zbytečných spojení k
    Mozille, tiskárny ze sítě až po kliknutí na Přidat), nové O tomto počítači + okna pro malé
    obrazovky, Kalendář + Kalkulačka + datum a čísla podle jazyka, LuxAI se nezacyklí. Nic o Poště, Lux
    Code, App Studiu, Icon Studiu ani SDK (hlídá `test_current_notes_skip_staging_only_apps`). Po
    aktualizaci z 1.0.2 se ukáže jen 1.0.3, z 1.0.1 obě (nejnovější první); noví uživatelé ho nevidí.
  - `CHANGELOG.md` – sekce `1.0.3 „Sirius“ – 2026-11-19` (bez „(beta)“; 6 Nové, 81 Opraveno), položky
    Pošty, App Studia, Icon Studia a Lux Code (5 + 14) zůstaly v nové sekci „Připravuje se“; anglicky
    `site/content/en/changes/1.0.3-2026-11-19.md` a `unreleased.md` (stejné sekce a počty položek,
    hlídá `scripts/check-site.py`). Sloučené zdvojené položky (3× `luxos-desktop` 82/83, LSL 0.10.9 v
    položce LSL 0.10.14); smíšené položky rozdělené (Lux Code z „LSL IDE, LuxAI a Lux Code“, Icon Studio
    z „Web, Icon Studio a Sandbox“). Nová položka **LuxAI: odpověď, která se začne opakovat dokola, se
    zastaví** (`luxai` 2.0.2-13 ze soukromého repozitáře – viz krok 2).
  - Aktuální verze 1.0.3 na webu (FAQ cs/en), v README a v dokumentaci (`luxos-docs` 1.0.0-83,
    Přehled LuxOS). Verzi na hlavní stránce a v `release.json` bere `build-site.py` z `files/version`,
    ISO z `site/iso.json` (mění se až v kroku 11 ze skutečného ISO).
- Větev **`release-1.0.3-stable`** (nad `release-1.0.3`, **do `main` až v kroku 6**): pryč napevno
  zapsané „beta“ (audit B12-BETA-01) – `build-site.py` (štítek u ISO, upozornění „LuxOS je beta“,
  `llms.txt`, `release.json` `"channel": "stable"`), README (odznak stavu), hlavní a úvodní stránky
  webu, FAQ cs/en, Přehled v `luxos-docs` (+1 `pkgrel`). Historie v `CHANGELOG.md` zůstává, jak byla
  (ta vydání beta byla).

Všechny příkazy se spouštějí v kořeni repozitáře `~/LuxOS-Arch`. Klíč LuxOS (otisk
`FD18 5DAB 7701 40E8 9C37 275E 7035 CFDF DCA6 C991`):

```bash
KEY=FD185DAB770140E89C37275E7035CFDFDCA6C991
SIGN=$HOME/.local/share/luxos/signing     # GNUPGHOME s podpisovým klíčem (nebo Trezor /safe/$USER/luxos-signing)
```

## 0. Kontroly před vydáním

Grafické testy jen ve virtuální obrazovce (`scripts/luxos-testguard.sh`), nikdy na skutečné relaci:

```bash
E="env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent nice -n 10"
$E python3 -m unittest packages/luxos-desktop/tests/test_luxos_whats_new.py   # 13 jazyků, verze, zobrazení jednou, bez aplikací jen ze staging
$E python3 -m unittest discover -s packages/luxos-i18n/tests
$E python3 -m unittest packages/luxos-store/tests/test_app_catalog.py
$E python3 -m unittest discover -s packages/apps/luxos-docs/tests
$E xvfb-run -a scripts/check-titlebars.sh                                       # každé okno má horní lištu
PATH=$HOME/LuxOS-Arch/out/sitevenv/bin:$PATH $E sh -c 'python3 scripts/build-site.py && python3 scripts/check-site.py'
```

Očekávání (ověřeno na větvi `release-1.0.3` 2026-11-19): Co je nového 14 testů OK (1 přeskočený test
ikon v nainstalovaném motivu), i18n 16 OK (1 přeskočený), katalog Obchodu OK, `luxos-docs` 39 OK,
`site: LuxOS 1.0.3 (ISO 1.0.2)` a `check-site: … 0 problems`. Dokud není nové ISO, stránka nabízí ISO
1.0.2 s poznámkou „po instalaci se systém aktualizuje na 1.0.3“. Na větvi `release-1.0.3-stable` totéž
a na webu nikde „beta“ kromě historie změn.

## 1. Větev do main a na GitHub

CI staví z `main` na GitHubu (`luxopes/LuxOS-Arch`) – i název ISO se bere z `files/version` v checkoutu.

```bash
git switch main && git merge --no-ff release-1.0.3 && git push origin main
```

(Když mezitím `main` zvýšil `pkgrel` `luxos-branding` nebo `luxos-docs`, při sloučení vzít vyšší + 1.)
`release-1.0.3-stable` se teď **neslučuje**.

## 2. Balíky na CI: luxos-branding, luxos-docs, LuxAI a programy v LSL 0.10.14

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

Kontrola (artefakt má `SHA256SUMS` a podsložku `single/`, proto `find`):

```bash
P=$(find out/ci-pub/luxos-branding -name 'luxos-branding-1.1.0-32-any.pkg.tar.zst')
D=$(find out/ci-pub/luxos-docs -name 'luxos-docs-1.0.0-83-any.pkg.tar.zst')
for f in $P $D; do (cd "$(dirname "$(dirname "$f")")" && sha256sum -c SHA256SUMS); done
tar --zstd -xOf $P usr/lib/luxos/version | grep '^VERSION=1.0.3$'
tar --zstd -tf $P | grep 'usr/share/luxos/whats-new/1.0.3.json'
tar --zstd -xOf $P usr/lib/luxos/apply-branding | grep 'PRETTY_NAME="LuxOS 1.0.3 Sirius"'
tar --zstd -xOf $D usr/share/luxos/docs/luxos/overview.md | grep '1.0.3 "Sirius"'
```

**LuxAI 2.0.2-13** (zacyklená odpověď se zastaví a jednou zkusí znovu; v `CHANGELOG` 1.0.3) je v
soukromém repozitáři (`luxai-loop`, „not yet released“) – před zveřejněním ve staging ho postavit
ze soukromého repozitáře (`out/ci-pub-private`, postup jako u ostatních proprietárních balíků),
podepsat a přidat do `[luxos-apps]` stejně jako v kroku 3. Bez něj položku z `CHANGELOG`, anglického
překladu i z `whats-new/1.0.3.json` (poslední položka) odebrat.

**Programy v LSL přeložené `lsl` 0.10.14** (0.10.14 opravuje mocninu `^` s desetinnými čísly, 0.10.13
`%` a `//`). `lsl-0.10.14-1` musí být v `out/repo/luxos-apps` a balíky s programy v LSL postavené
**po** něm. Balík starší než překladač dostane `pkgrel` + 1 a nové sestavení na CI:

```bash
L=$(find out/repo/luxos-apps/x86_64 -name 'lsl-0.10.14-1-*.pkg.tar.zst'); test -n "$L"
ld=$(tar --zstd -xOf $L .PKGINFO | awk -F' = ' '/^builddate/{print $2}')
for p in luxos-desktop luxos-guard luxos-firewall luxai luxos-domain luxos-mail luxos-app-studio luxos-icon-studio; do
  f=$(tar -xzOf out/repo/*/x86_64/*.db.tar.gz --wildcards '*/desc' 2>/dev/null | awk '/^%FILENAME%$/{getline; print}' | grep -E "^$p-[0-9]")
  b=$(tar --zstd -xOf out/repo/*/x86_64/$f .PKGINFO 2>/dev/null | awk -F' = ' '/^builddate/{print $2}')
  [ "${b:-0}" -ge "$ld" ] && echo "ok    $f" || echo "STARÉ $f (pkgrel + 1, sestavit znovu)"
done
```

(`luxai` a `luxos-domain` se staví ze soukromého repozitáře; `luxos-mail`, `luxos-app-studio` a
`luxos-icon-studio` jdou jen do staging, ale i tam mají být přeložené 0.10.14.)

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
tar -xzOf $d/luxos.db.tar.gz --wildcards '*/desc' | grep -A1 '^%FILENAME%' | grep luxos-branding     # 1.1.0-32
tar -xzOf $a/luxos-apps.db.tar.gz --wildcards '*/desc' | grep -A1 '^%FILENAME%' | grep -E 'luxos-docs|luxai-'   # 1.0.0-83, 2.0.2-13
```

Stejně každý balík z kroku 2 (LuxAI, znovu přeložené programy v LSL) do jeho repozitáře.

## 4. Staging

```bash
LUXOS_REPO_CHANNEL=staging scripts/publish-repo.sh
```

`publish-repo.sh` před nahráním ověří podpis Secure Boot jádra a systemd-boot (`scripts/sb-sign.sh
verify`) a nově i **ovladače**: `[luxos-drivers]` (z `out/drivers-repo`, jinak ze serveru) projde
`drivers/luxdrv.py perms --report` – balík se setuid/setgid nebo se soubory či složkami zapisovatelnými
pro všechny (mimo `drivers/perms-allow.json`) skript zastaví hláškou „Driver packages with unsafe
permissions - nothing was uploaded.“ a **nic se nenahraje**. Soubory, které databáze nezná (staré
verze), se z vydání vynechají. Při zastavení opravit ovladač (`drivers/luxdrv.py`, záplata v
`RULES`), postavit znovu (`./build.sh drivers`) a spustit znovu.

## 5. Zkouška ve staging

Na počítači (nebo ve VM) přepnout na staging a aktualizovat:

```bash
lux config channel staging
sudo lux update
```

Odhlásit/přihlásit → okno **Co je nového v LuxOS 1.0.3** (8 položek ve vašem jazyce), O tomto počítači
„Verze 1.0.3 (Sirius)“ (nové okno), `cat /etc/os-release`. Projít hlavně to, co 1.0.3 mění:

- **Zálohy:** záloha na USB disk a na `sftp://uživatel@server`, přerušení zálohy (vytažení disku) a
  další záloha, obnova složky s nečitelným souborem („Některé soubory se nepodařilo obnovit“), znovu
  přidaný disk SMB si zálohy ponechá.
- **Instalátor vedle Windows** (VM s Windows): s Rychlým spuštěním / hibernací zmenšení odmítne ještě
  před souhrnem; po úplném vypnutí Windows zmenšení a instalace projdou a Windows dál startuje.
- **Sandbox:** aplikace v sandboxu kreslí, píše a funguje; `tests/test_x11_untrusted.py` v
  `luxos-sandbox` pod Xvfb; volba **Důvěryhodný displej** v okně Sandbox.
- **Firefox:** nový profil – uvítací stránka, žádné spojení na `detectportal.firefox.com`, oblast ani
  doporučené doplňky (`about:config`: `browser.region.update.enabled` = false).
- **Tisk:** síťová tiskárna (mDNS) se jen nabídne v oznámení s **Přidat**, po kliknutí se přidá; USB
  tiskárna se nastaví sama.
- **Kalendář a Kalkulačka:** opakovaná událost z Outlooku/Google v UTC přes změnu času, smazání
  jednoho přesunutého výskytu; 300 + 10 % = 330.
- **Malá obrazovka:** VM s 1366×768 a 1280×800 – Monitor systému, Zpětná vazba, Baterie a napájení,
  Plocha a Dock, Co je nového se vejdou.
- **Jazyk:** datum na přihlašovací a zamykací obrazovce a v horní liště v jiném jazyce než češtině,
  desetinná čárka v Zálohách a Monitoru systému.
- **LuxAI:** dlouhá odpověď bez zacyklení beze změny; zacyklená se zastaví a zkusí znovu.

Návrat do stabilního kanálu: `lux config channel stable` (balíky novější než stabilní zůstanou,
dokud stabilní kanál nedožene staging).

## 6. Rozhodnutí: 1.0.3 jako první stabilní verze

Až majitel řekne, že staging je v pořádku, sloučit větev bez „beta“:

```bash
git switch main && git merge --no-ff release-1.0.3-stable && git push origin main
```

`luxos-docs` z ní (Přehled bez „beta“, `pkgrel` + 1 proti tomu, co je pak na `main`) postavit a
přidat do `out/repo` stejně jako v krocích 2–3 a zveřejnit ve staging (krok 4) – stabilní vydání se
skládá ze stejného `out/repo`.

## 7. Stabilní vydání bez balíků jen pro staging

**Nepoužívat `scripts/promote-staging.sh`** – přepnul by `current` na staging včetně Pošty, App Studia,
Icon Studia, SDK a nového Lux Code.

```bash
scripts/compose-stable-repo.sh            # out/repo -> out/repo-stable, výchozí seznamy = rozhodnutí majitele
```

Skript zkopíruje `out/repo` (reflink, zdroj se nemění), z `[luxos-apps]` odebere `luxos-mail`,
`luxos-app-studio`, `luxos-icon-studio` a `luxos-sdk` (databáze, všechny verze souborů, ikona),
`lux-code` (a `lux-code-next`, pokud by byl) nahradí verzí, která je teď na
`https://luxos.lux-ai.cz/repo` (stáhne ji s podpisem a ověří klíčem LuxOS), databáze znovu podepíše a
na konci ověří podpisy databází i všech balíků a vypíše obsah. Zkontrolujte výpis: žádný
`luxos-mail`, `luxos-app-studio`, `luxos-icon-studio`, `luxos-sdk`; `lux-code` ve stabilní verzi;
`luxos-branding-1.1.0-32`, `luxos-docs` z kroku 6, `luxai-2.0.2-13`, `lsl-0.10.14-1`.

Podpis Secure Boot ve stabilním vydání (totéž dělá `publish-repo.sh`):

```bash
s=out/repo-stable/luxos/x86_64
scripts/sb-sign.sh verify $(tar -xzOf $s/luxos.db.tar.gz --wildcards '*/desc' | awk '/^%FILENAME%$/ {getline; print}' \
    | grep -E '^(linux-luxos|luxos-secureboot)-[0-9]' | sed "s|^|$s/|")
```

Majitel zveřejní:

```bash
LUXOS_REPO_SRC=out/repo-stable scripts/publish-repo.sh      # kanál current = stabilní
for p in luxos-mail luxos-app-studio luxos-icon-studio luxos-sdk; do
  echo "$p $(curl -fsS https://luxos.lux-ai.cz/repo/luxos-apps/x86_64/luxos-apps.db | tar -tz | grep -c "^$p-[0-9]")"   # 0
done
```

I tady platí kontrola práv ovladačů z kroku 4. `publish-repo.sh` vezme `[luxos-drivers]` z
`out/drivers-repo`, katalog Obchodu (`apps.json`, snímky) vygeneruje z právě skládaného vydání –
vynechané aplikace v Obchodě stabilního kanálu nebudou. Na stabilním počítači `sudo lux update` → Co je
nového 1.0.3; Pošta se nenabízí.

## 8. ISO na GitHub Actions

Až je stabilní repozitář zveřejněný (ISO se staví z něj):

```bash
gh workflow run build.yml -R luxopes/LuxOS-Arch --ref main -f target=iso -f channel=stable
gh run list -R luxopes/LuxOS-Arch -w build.yml -L1
gh run watch -R luxopes/LuxOS-Arch <ID> --exit-status        # limit běhu 300 min
rm -rf out/iso-1.0.3
gh run download -R luxopes/LuxOS-Arch <ID> -n iso -D out/iso-1.0.3
I=$(dirname "$(find out/iso-1.0.3 -name 'luxos-1.0.3-x86_64.iso')")
```

Workflow stáhne `[luxos]` a `[luxos-apps]` z `https://luxos.lux-ai.cz/repo` s ověřením podpisů,
postaví `out/luxos-1.0.3-x86_64.iso` a `SHA256SUMS`; **na server nic nenahrává a nic nepodepisuje**.

## 9. Ověření a podpis ISO

```bash
cd $I
sha256sum -c SHA256SUMS
ls -l luxos-1.0.3-x86_64.iso
cd -
LUXOS_VM_ISO=$I/luxos-1.0.3-x86_64.iso scripts/test-vm.sh live
LUXOS_VM_ISO=$I/luxos-1.0.3-x86_64.iso scripts/test-vm.sh live --secureboot   # OVMF se Secure Boot a klíči Microsoftu
```

Ve VM: start (se Secure Boot přes zápis klíče), instalace, po přihlášení `cat /etc/os-release` (1.0.3),
O tomto počítači, Co je nového se neukáže (nový uživatel), Obchod (bez Pošty, App Studia, Icon Studia,
SDK), `luxos-secureboot status`, `luxos-firewall status`, na živém systému i v instalátoru nikde „beta“.

```bash
cd $I
GNUPGHOME=$SIGN gpg --detach-sign --no-armor -u $KEY luxos-1.0.3-x86_64.iso
curl -fsS https://luxos.lux-ai.cz/download/SHA256SUMS -o SHA256SUMS.server
cp SHA256SUMS SHA256SUMS.ci
{ cat SHA256SUMS.ci; grep -v ' luxos-1.0.3-x86_64.iso$' SHA256SUMS.server; } > SHA256SUMS
GNUPGHOME=$SIGN gpg --detach-sign --no-armor -u $KEY SHA256SUMS
K=~/LuxOS-Arch/packages/luxos-keyring/files/luxos.gpg
g=$(mktemp -d -p ~/LuxOS-Arch/out); gpg --homedir $g -q --import $K
gpg --homedir $g --verify luxos-1.0.3-x86_64.iso.sig luxos-1.0.3-x86_64.iso
gpg --homedir $g --verify SHA256SUMS.sig SHA256SUMS
sha256sum -c --ignore-missing SHA256SUMS; gpgconf --homedir $g --kill gpg-agent; rm -rf $g
cd -
```

## 10. Nahrání ISO na server

```bash
S=root@185.183.156.25:/srv/luxos-site/download
rsync -P --chmod=F644 $I/luxos-1.0.3-x86_64.iso $I/luxos-1.0.3-x86_64.iso.sig $S/
rsync --chmod=F644 $I/SHA256SUMS $I/SHA256SUMS.sig $S/
curl -sI https://luxos.lux-ai.cz/download/luxos-1.0.3-x86_64.iso | head -3
```

Starší ISO zůstávají v `/download/`. Na server posílat jen pár požadavků (Lux Guard na serveru blokuje
IP při náporu dotazů).

## 11. site/iso.json a web

```bash
scripts/update-iso-json.sh $I/luxos-1.0.3-x86_64.iso
git add site/iso.json && git commit -m "Website: ISO 1.0.3 Sirius"
git push origin main
scripts/publish-site.sh
```

`update-iso-json.sh` vezme verzi z názvu (musí se shodovat s `files/version`), velikost, SHA-256
(porovná se `SHA256SUMS`) a dnešní datum; upozorní, když chybí `.sig`. Kontrola webu:
`https://luxos.lux-ai.cz/release.json` (`version` i `iso.version` 1.0.3, `channel` `stable`), stránka
nabízí ISO 1.0.3 bez štítku „beta“, odkazy na `.sig` a `SHA256SUMS` fungují, `/changes/` i
`/cs/zmeny/` začínají „Coming soon“/„Připravuje se“ (Pošta, App Studio, Icon Studio, Lux Code) a pak
1.0.3 „Sirius“.

## 12. countme

`server/countme/deploy.sh` při každém nasazení vytvoří `versions.txt` z nadpisů `## X.Y.Z` v
`CHANGELOG.md`. Verze 1.0.3 se přijímá jako „nejbližší další patch“ nad 1.0.2, takže to není naléhavé,
ale po vydání ho majitel spustí znovu, aby 1.0.3 byla v seznamu vydaných verzí:

```bash
server/countme/deploy.sh root@185.183.156.25
```

## Otevřené body

- **PRIV-1 – chybové logy Caddy na serveru** (audit, nízká, neověřeno): `log_skip` v
  `server/countme/Caddyfile.snippet` a `server/geocoder/Caddyfile.snippet` vypíná jen access log;
  když služba na 8765/8766 neodpovídá, chybový záznam `reverse_proxy` může nést `remote_ip` a URI (u
  geocoderu i hledaný text `q`) do výchozího logu/journalu Caddy. Ověřit na serveru (úroveň logu,
  `journalctl -u caddy` při zastavené službě) a případně přidat `log { exclude … }` / vlastní logger pro
  tyto cesty.
- **Upozornění earlyoom pod novou politikou D-Bus** (`luxos-desktop` 1.1.0-88,
  `cz.luxos.ForkGuard.conf`): signál `net.nuetzlich.SystemNotifications` smí poslat jen root nebo
  skupina `proc` (earlyoom běží jako DynamicUser s doplňkovou skupinou `proc`). Ve VM ověřit, že
  luxos-hub upozornění earlyoom pořád ukáže (např. `tail /dev/zero` v Terminálu, VM s 2–4 GB) a že
  obyčejný uživatel signál poslat nemůže (`dbus-send --system --type=signal …` → odmítnuto).
- **Mapy: dialog souhlasu s polohou bez BeaconDB**: `ask_consent` v `luxos-maps` zmiňuje GPS telefonu,
  GeoClue a ipinfo.io, ale ne to, že GeoClue posílá okolní sítě Wi‑Fi službě BeaconDB
  (`files/90-luxos-maps.conf`). Zásady soukromí to už uvádějí; doplnit text dialogu (12 jazyků v
  `luxos-i18n`) a `pkgrel` `luxos-maps`.
