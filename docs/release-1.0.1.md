# Vydání LuxOS 1.0.1 „Sirius“ – postup

Vydání: vše ze staging do stabilního kanálu **kromě Pošty (`luxos-mail`)**, která zůstává jen ve
staging, a **Lux Code (`lux-code`, případně `lux-code-next`)**, které ve stabilním kanálu zůstává
v dosavadní verzi. Nové ISO `luxos-1.0.1-x86_64.iso`.

Připravené v repozitáři (větev s tímto souborem):

- `packages/luxos-branding/files/version` → `VERSION=1.0.1`, `CODENAME=Sirius`; `luxos-branding` 1.1.0-27
  (os-release „LuxOS 1.0.1 Sirius“, O tomto počítači, fastfetch, název ISO, `countme v=1.0.1`).
- `packages/luxos-branding/files/whats-new/1.0.1.json` – okno Co je nového (13 jazyků). Ukáže se po
  přihlášení jednou: verze se uloží do `~/.config/luxos/whats-new-seen` a zobrazí se novinky všech
  verzí `seen < verze <= aktuální`, tedy po aktualizaci z 1.0.0 jen 1.0.1. Noví uživatelé ho nevidí
  (mají Prohlídku, `--mark-seen`).
- `CHANGELOG.md` – sekce `1.0.1 „Sirius“ – 2026-11-08 (beta)`, Pošta přesunutá do „Připravuje se“;
  anglický překlad `site/content/en/changes/<verze>-<datum>.md` (stejné sekce a počty položek,
  hlídá `scripts/check-site.py`).
- `scripts/compose-stable-repo.sh` – složí stabilní vydání bez Pošty a se stabilním Lux Code.
- `scripts/publish-repo.sh` – nově `LUXOS_REPO_SRC` (výchozí dál `out/repo`).
- `scripts/update-iso-json.sh` – doplní `site/iso.json` z hotového ISO.

Všechny příkazy se spouštějí v kořeni repozitáře `~/LuxOS-Arch`. Klíč LuxOS (otisk
`FD18 5DAB 7701 40E8 9C37 275E 7035 CFDF DCA6 C991`) je v Trezoru – nejdřív `luxos-safe unlock`.

```bash
KEY=FD185DAB770140E89C37275E7035CFDFDCA6C991
SIGN=/safe/$USER/luxos-signing          # GNUPGHOME s podpisovým klíčem
```

## 0. Kontroly před vydáním

```bash
python3 -m unittest packages/luxos-desktop/tests/test_luxos_whats_new.py   # 13 jazyků, verze, zobrazení jednou
python3 -m unittest packages/luxos-i18n/tests/test_cli_i18n.py packages/luxos-store/tests/test_app_catalog.py
env -u DISPLAY xvfb-run -a scripts/check-titlebars.sh                      # každé okno má horní lištu
out/sitevenv/bin/python scripts/build-site.py && out/sitevenv/bin/python scripts/check-site.py
```

Očekávání: vše OK, `check-titlebars.sh` 31× `ok`, `check-site: … 0 problems`, web hlásí
`LuxOS 1.0.1 (ISO 1.0.0)` (dokud není nové ISO, stránka nabízí ISO 1.0.0 s poznámkou „po instalaci
se systém aktualizuje na 1.0.1“).

## 1. Větev do main a na GitHub

CI staví z `main` na GitHubu (`luxopes/LuxOS-Arch`) – i název ISO se bere z `files/version` v checkoutu.

```bash
git switch main && git merge --ff-only <větev-vydání> && git push origin main
```

## 2. luxos-branding 1.1.0-27 na CI

```bash
gh workflow run build.yml -R luxopes/LuxOS-Arch --ref main -f target=one -f package=luxos-branding -f channel=staging
gh run list -R luxopes/LuxOS-Arch -w build.yml -L1          # ID běhu
gh run watch -R luxopes/LuxOS-Arch <ID> --exit-status
rm -rf out/ci-pub/luxos-branding
gh run download -R luxopes/LuxOS-Arch <ID> -n single -D out/ci-pub/luxos-branding
```

(Totéž dělá místní pomocník `out/ci-pub/build.sh luxos-branding`.) Artefakt `single` obsahuje
nepodepsaný `luxos-branding-1.1.0-27-any.pkg.tar.zst` a `SHA256SUMS`. Kontrola:

```bash
cd out/ci-pub/luxos-branding && sha256sum -c SHA256SUMS && cd -
P=out/ci-pub/luxos-branding/luxos-branding-1.1.0-27-any.pkg.tar.zst
tar --zstd -xOf $P usr/lib/luxos/version | grep '^VERSION=1.0.1$'
tar --zstd -tf $P | grep 'usr/share/luxos/whats-new/1.0.1.json'
tar --zstd -xOf $P usr/lib/luxos/apply-branding | grep 'PRETTY_NAME="LuxOS 1.0.1 Sirius"'
```

## 3. Podpis a přidání do out/repo ([luxos])

```bash
d=out/repo/luxos/x86_64
install -m644 $P $d/
GNUPGHOME=$SIGN gpg --detach-sign --no-armor -u $KEY $d/${P##*/}
GNUPGHOME=$SIGN repo-add -s -k $KEY $d/luxos.db.tar.gz $d/${P##*/}
tar -xzOf $d/luxos.db.tar.gz --wildcards '*/desc' | grep -A1 '^%FILENAME%' | grep luxos-branding
```

`out/repo` musí odpovídat tomu, co je teď ve staging (poslední `publish-repo.sh` do staging šel
z něj). Kontrola rozdílu proti serveru:

```bash
diff <(tar -xzOf out/repo/luxos-apps/x86_64/luxos-apps.db.tar.gz --wildcards '*/desc' | grep -A1 '^%FILENAME%' | grep -v '^%\|^--' | sort) \
     <(curl -fsS https://luxos.lux-ai.cz/staging/luxos-apps/x86_64/luxos-apps.db | tar -xzO --wildcards '*/desc' | grep -A1 '^%FILENAME%' | grep -v '^%\|^--' | sort)
```

(totéž pro `luxos`; jediný rozdíl smí být nový `luxos-branding`).

## 4. Staging

```bash
LUXOS_REPO_CHANNEL=staging scripts/publish-repo.sh
```

Na počítači se `channel = "staging"`: `sudo lux update`, odhlásit/přihlásit → okno **Co je nového
v LuxOS 1.0.1**, O tomto počítači „Verze 1.0.1 (Sirius)“, `cat /etc/os-release`.

## 5. Stabilní vydání bez Pošty

**Nepoužívat `scripts/promote-staging.sh`** – přepnul by `current` na staging včetně Pošty a nového Lux Code.

```bash
scripts/compose-stable-repo.sh            # out/repo -> out/repo-stable
```

Skript zkopíruje `out/repo` (reflink, zdroj se nemění), z `[luxos-apps]` odebere `luxos-mail`
(databáze, všechny verze souborů, ikona), `lux-code` (a `lux-code-next`, pokud by byl) nahradí verzí,
která je teď na `https://luxos.lux-ai.cz/repo` (stáhne ji s podpisem a ověří klíčem LuxOS; balík,
který ve stabilním kanálu není, odebere), databáze znovu podepíše a na konci ověří podpisy
databází i všech balíků a vypíše obsah. Zkontrolujte výpis: žádný `luxos-mail`, `lux-code` ve
stabilní verzi, `luxos-branding-1.1.0-27`. Jiné seznamy: `LUXOS_STABLE_EXCLUDE`, `LUXOS_STABLE_KEEP`.

```bash
LUXOS_REPO_SRC=out/repo-stable scripts/publish-repo.sh      # kanál current = stabilní
curl -fsS https://luxos.lux-ai.cz/repo/luxos-apps/x86_64/luxos-apps.db | tar -tz | grep -c luxos-mail   # 0
```

`publish-repo.sh` vezme `[luxos-drivers]` z `out/drivers-repo`, katalog Obchodu (`apps.json`,
snímky) vygeneruje z právě skládaného vydání – Pošta v Obchodě stabilního kanálu nebude.
Na stabilním počítači `sudo lux update` → Co je nového 1.0.1; Pošta se nenabízí.

Pozn.: `luxos-docs` ve stabilním kanálu obsahuje i stránku o Poště (aplikace v něm zatím není).

## 6. ISO na GitHub Actions

Až je stabilní repozitář zveřejněný (ISO se staví z něj):

```bash
gh workflow run build.yml -R luxopes/LuxOS-Arch --ref main -f target=iso -f channel=stable
gh run list -R luxopes/LuxOS-Arch -w build.yml -L1
gh run watch -R luxopes/LuxOS-Arch <ID> --exit-status        # limit běhu 300 min
rm -rf out/iso-1.0.1
gh run download -R luxopes/LuxOS-Arch <ID> -n iso -D out/iso-1.0.1
```

Co workflow dělá: `scripts/fetch-published-repo.sh` stáhne `[luxos]` a `[luxos-apps]` z
`https://luxos.lux-ai.cz/repo` a ověří podpis databází i každého balíku klíčem z `luxos-keyring`;
`./build.sh iso` (kanál `stable`, `/etc/lux/lux.conf` beze změny) postaví
`out/luxos-1.0.1-x86_64.iso`; krok Checksums vytvoří `out/SHA256SUMS` (jen toto ISO); artefakt
**`iso`** = ISO + `SHA256SUMS` (bez komprese, 14 dní). **Na server nic nenahrává a nic nepodepisuje**
(soukromý klíč na GitHubu není) – podpis a nahrání do `/srv/luxos-site/download/` dělá správce
(kroky 7–8). `publish-site.sh` soubory v `/download/` (`*.iso`, `*.iso.sig`, `SHA256SUMS*`) nemaže
ani nepřepisuje.

## 7. Ověření a podpis ISO

```bash
cd out/iso-1.0.1
sha256sum -c SHA256SUMS
ls -l luxos-1.0.1-x86_64.iso                                  # ~2,2 GB jako 1.0.0
cd -
LUXOS_VM_ISO=out/iso-1.0.1/luxos-1.0.1-x86_64.iso scripts/test-vm.sh live
```

Ve VM: start, instalace, po přihlášení `cat /etc/os-release` (1.0.1), O tomto počítači, Obchod
(bez Pošty), firewall zapnutý (`luxos-firewall status`), `/tmp` na disku (`findmnt /tmp` → btrfs `@tmp`).

Rozložení `/download/` z vydání 1.0.0: `luxos-<verze>-x86_64.iso`, `luxos-<verze>-x86_64.iso.sig`
(binární odpojený podpis), `SHA256SUMS` (řádky všech nabízených ISO, nejnovější první) a
`SHA256SUMS.sig`. Stránka radí `sha256sum -c SHA256SUMS` a `gpg --verify <iso>.sig <iso>`.

```bash
cd out/iso-1.0.1
GNUPGHOME=$SIGN gpg --detach-sign --no-armor -u $KEY luxos-1.0.1-x86_64.iso
curl -fsS https://luxos.lux-ai.cz/download/SHA256SUMS -o SHA256SUMS.server
cp SHA256SUMS SHA256SUMS.ci
{ cat SHA256SUMS.ci; grep -v ' luxos-1.0.1-x86_64.iso$' SHA256SUMS.server; } > SHA256SUMS
GNUPGHOME=$SIGN gpg --detach-sign --no-armor -u $KEY SHA256SUMS
# ověření veřejným klíčem jako návštěvník webu
g=$(mktemp -d); gpg --homedir $g -q --import ../../packages/luxos-keyring/files/luxos.gpg
gpg --homedir $g --verify luxos-1.0.1-x86_64.iso.sig luxos-1.0.1-x86_64.iso
gpg --homedir $g --verify SHA256SUMS.sig SHA256SUMS
sha256sum -c --ignore-missing SHA256SUMS; rm -rf $g
cd -
```

## 8. Nahrání ISO na server

```bash
S=root@185.183.156.25:/srv/luxos-site/download
rsync -P --chmod=F644 out/iso-1.0.1/luxos-1.0.1-x86_64.iso out/iso-1.0.1/luxos-1.0.1-x86_64.iso.sig $S/
rsync --chmod=F644 out/iso-1.0.1/SHA256SUMS out/iso-1.0.1/SHA256SUMS.sig $S/
curl -sI https://luxos.lux-ai.cz/download/luxos-1.0.1-x86_64.iso | head -3
```

ISO 1.0.0 zůstává v `/download/` (starší odkazy). Na server posílat jen pár požadavků (LUX Guard na
serveru blokuje IP při náporu dotazů).

## 9. site/iso.json

```bash
scripts/update-iso-json.sh out/iso-1.0.1/luxos-1.0.1-x86_64.iso
git add site/iso.json && git commit -m "Website: ISO 1.0.1 Sirius"
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
(`version` i `iso.version` 1.0.1), stránka nabízí ISO 1.0.1 s velikostí a datem, odkazy na `.sig` a
`SHA256SUMS` fungují, poznámka o aktualizaci po instalaci je skrytá, `/changes/` i `/cs/zmeny/`
začínají 1.0.1 „Sirius“.
