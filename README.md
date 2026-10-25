# ✦ LuxOS

Rychlý a lehký Linux na Arch Linuxu s prostředím ve stylu macOS.

> **English:** LuxOS is a fast, lightweight Arch Linux based distribution with a macOS-like desktop
> (Xfce underneath), its own package manager `lux`, its own kernel build, hassle-free drivers, the LuxAI
> assistant and its own language [LSL](https://lsl.lux-ai.cz). Download: <https://luxos.lux-ai.cz>.
> License: GPL-3.0-or-later (see [LICENSE](LICENSE)); bundled third-party packages keep their own licenses.

- **Rychlost a nenáročnost:** Xfce + vestavěný kompozitor xfwm4 (žádný těžký shell), jádro `linux-zen`,
  zram swap (zstd), ladění sysctl, I/O plánovače podle typu disku, systemd-oomd, Btrfs se zstd kompresí,
  systemd initramfs, squashfs ISO v zstd (rychlý start live systému). Relace bez pravidelného dotazování:
  Ovládací centrum, Kalendář, Trezor, Spořič dat a automatický vzhled v jednom procesu `luxos-hub`,
  připojení monitoru hlídá událost RandR, pluginy lišty bez nabídek běží přímo v panelu. Nepoužívaná
  grafika NVIDIA se uspí (runtime PM), Firefox dekóduje video hardwarově (VA-API).
- **Vzhled macOS:** horní lišta (logo-menu, název aktivní aplikace, ikony, hodiny), dock Plank se zvětšováním,
  tlačítka oken vlevo (semafor), WhiteSur GTK/ikony/kurzory, písmo Inter, Hledání (`Super+Mezerník`),
  Launchpad (`Super+A`), zkratky ve stylu Cmd (`Super+Q`, `Super+Shift+4`…), touchpad: klepnutí = klik, dvěma prsty = pravé tlačítko, posouvání na okraji,
  přepínání světlého/tmavého režimu.
- **Bez starostí s ovladači:** `luxos-hwdetect` při instalaci rozpozná GPU (Intel/AMD/NVIDIA včetně hybridní
  grafiky; NVIDIA Turing+ `nvidia-open`, Maxwell/Pascal/Volta legacy 580xx z `[luxos]`, Kepler nouveau nebo volitelně 470xx),
  zvuk Intel SOF, kamery Intel IPU6/IPU7, Thunderbolt, Wi‑Fi Broadcom, čtečky otisků, akcelerometry a virtualizaci
  (VirtualBox, VMware, QEMU, Hyper‑V). Nový hardware po instalaci: upozornění po přihlášení a aplikace Ovladače
  (instalace jedním tlačítkem), v terminálu `lux drivers`. PipeWire, Bluetooth, tisk bez ovladačů (IPP Everywhere) a skenery v základu.
- **Shell `lsh` (Lux Shell):** vlastní shell LuxOS – fork GNU bash 5.3, plně kompatibilní, s
  [ble.sh](https://github.com/akinomyoga/ble.sh) (našeptávání a zvýraznění syntaxe), starship promptem, fzf, zoxide,
  eza, bat a fastfetch. Navíc oproti bashi:
  - `about [shell|os|lsl]` – přehled o shellu, systému a LSL,
  - příkazy [LSL](https://lsl.lux-ai.cz) přímo v shellu (`print 6 * 7`, `load time`, `x = 5`; relace: `lsl-session`),
    `./skript.lsl` se spustí přes `lsl`,
  - `pip install` funguje i mimo venv (balíčky do `~/.local`, jen varování místo chyby).

  Konfigurace `/etc/lsh/lshrc` a `~/.lshrc`, historie `~/.lsh_history`. zsh zůstává jako alternativa.
  macOS zvyky: `open`, `pbcopy`, `pbpaste`.
- **Aplikace a ikony:** vlastní Kalkulačka LuxOS, ikony LuxOS pro Soubory, Nastavení, Poznámky, Launchpad,
  instalátor a Kalkulačku; ostatní z WhiteSur v překreslené variantě (bez napodobenin ikon a loga Apple).
- **Splash screeny:** Plymouth (tónované pozadí + logo se září + tenký progress bar, i pro zadání hesla k LUKS;
  varianty modrá/fialová/oranžová/zelená/bílá v Nastavení › Plocha a Dock nebo `luxos-splash set <varianta>`), skrytý zavaděč
  (systemd-boot `timeout 0`), přihlašovací obrazovka uprostřed (lightdm-gtk-greeter), ISO boot menu v barvách LuxOS.
- **`lux`** – správce balíků LuxOS místo pacmanu: repozitáře přes libalpm (`pyalpm`), vlastní konfigurace
  `/etc/lux/lux.conf` (formát LuxOS, žádný `/etc/pacman.conf`), AUR, Flatpak a balíky `.lux`; krátký barevný výstup, příkazy jako u apt; `lux` bez parametrů otevře interaktivní
  obchod v terminálu (TUI) s balíky z repozitářů LuxOS i Arch Linuxu. Příkaz `pacman` v LuxOS není (jádro `lux-engine`,
  viz níže); kdo ho napíše, uvidí odpovídající příkaz `lux`.
- **Obchod LuxOS** – grafický obchod s aplikacemi z repozitářů LuxOS a Arch Linuxu (metadata AppStream),
  instalace jedním kliknutím, aktualizace.
- **Ovládací centrum** v horní liště – Wi‑Fi, Bluetooth, Nerušit, tmavý režim, **Spořič dat**
  (`luxos-datasaver`: měřené připojení, bez stahování na pozadí) a **Spořič baterie** (`luxos-powersaver`:
  úsporný výkonový profil), jas, hlasitost, baterie v procentech; přepínač klávesnice v liště.
- **Monitor systému** – výkon v grafech (procesor, paměť, disk, síť) a otevřené aplikace s tlačítkem
  Ukončit; technický výpis procesů na přepnutí.
- **Baterie a napájení** – procenta, nabíjení/vybíjení s odhadem výdrže, spotřeba ve wattech, zdraví
  baterie, grafy úrovně a spotřeby za 24 hodin, výkonový režim, automatický Spořič baterie při 20 %.
- **Bluetooth** – zapnutí, moje zařízení a připojení nového jedním klikem (spárování, důvěra, připojení).
- **Monitory** – po připojení se obrazovka sama rozšíří, okna z odpojeného monitoru se přesunou zpět,
  `Super+P` přepíná Rozšířit / Zrcadlit / Jen externí / Jen vestavěná (`luxos-displays`).
- **Plocha a Dock** (`luxos-settings`) – tapety, vzhled, automatické skrývání a průhlednost Docku,
  průhlednost horní lišty (nahrazuje nastavení plochy Xfce).
- **Přihlášení jako v macOS** (`luxos-greeter`) – obrazovka s hodinami, po kliknutí avatar a heslo;
  plynulý přechod ze splashe bez černé obrazovky.
- **Kalendář** pod hodinami v liště – den s událostmi, měsíc a rok, události v `.ics` s připomínkami.
- **Hudba** v Ovládacím centru (MPRIS: Firefox, Spotify, VLC…), **jas displeje**, **profil LuxAI**.
- **Účet LuxAI** (`luxos-account`) – jedno přihlášení pro LuxAI, Lux Code a LSL IDE; volitelně už při instalaci.
- **Trezor** (`luxos-safe`) – šifrovaná složka `/safe/<uživatel>` s vlastním heslem, zamyká se sama.
- **Sandbox** (`luxos-sandbox`) – izolovaný systém pro nedůvěryhodné aplikace (`/dev/sandbox/<uživatel>`).
- **LuxDrop** – šifrovaný přenos souborů mezi počítači LuxOS (ověření kódem, připnuté klíče) a s aplikací LocalSend (telefony, tablety, Windows, Linux; protokol v2, HTTPS + mTLS).
- **Světlý režim** jako výchozí, přepínatelný nebo automatický podle východu a západu slunce;
  spořiče obrazovky (tapety, hodiny, polární záře, fotky, logo).
- **Čeština i angličtina** – aplikace a skripty LuxOS podle jazyka systému (`luxos-i18n`,
  překlady v `packages/luxos-i18n/files/cs.tsv`), instalátor se přepne podle zvoleného jazyka.

## Sestavení ISO

Potřebuješ jen `podman` (nebo `docker`). Vše ostatní běží v kontejneru Arch Linuxu.

```bash
./build.sh            # balíky LuxOS + ISO  → out/luxos-YYYY.MM.DD-x86_64.iso
./build.sh packages   # jen balíky (out/repo)
./build.sh iso        # jen ISO z hotových balíků
```

Zápis na USB: `sudo dd if=out/luxos-*.iso of=/dev/sdX bs=4M status=progress oflag=sync`

## Testování ve VM

```bash
scripts/test-vm.sh live          # boot ISO v QEMU/KVM (UEFI) s prázdným 40G diskem
scripts/test-vm.sh live --bios   # totéž v režimu BIOS
scripts/test-vm.sh disk          # boot nainstalovaného systému
scripts/test-vm.sh reset         # smazat testovací disk

scripts/vmctl.py shot screen.png # snímek obrazovky běžící VM
scripts/vmctl.py exec 'lux doctor'   # příkaz v hostu přes QEMU guest agent
```

## Instalace

V live systému ikona **Install LuxOS** (plocha, dock, uvítací okno) nebo `sudo luxos-install`.
Průvodce se zeptá na jazyk, klávesnici, časové pásmo, disk, volitelné šifrování (LUKS2) a účet.

- Rozdělení: UEFI → ESP 1 GiB (`/boot`, systemd-boot) + Btrfs; BIOS → bios_grub + `/boot` ext4 + Btrfs (GRUB).
- Btrfs subvolumy `@`, `@home`, `@log`, `@cache`, `noatime,compress=zstd:1`.
- **Ruční rozdělení** (GUI: Cíl › *Ruční rozdělení*): editor disků, oddílů, LVM a LUKS2 – vytvořit, smazat
  a zmenšit/zvětšit oddíl (ext4, btrfs, NTFS), šifrovat oddíl nebo LV (LVM na LUKS i LUKS na LVM), skupiny LVM
  přes více disků, přípojné body (`/`, `/home`, `/var`, `/tmp`, `/opt`, `/srv`, `/var/log`, vlastní), btrfs/ext4/xfs/f2fs,
  swap (oddíl, LV, nebo jen zram), ponechat existující ESP, VG/LV a odemčený LUKS. Předvolby *Šifrované LVM
  (/, /home, swap)* a *… se samostatným /var a /tmp*. Kontrola s hláškami (ESP ≥ 300 MB v `/boot` nebo `/efi`,
  nešifrovaný `/boot` pro GRUB v BIOS režimu, duplicitní body, velikosti, rozdílné šifrování `/` a `/home`);
  souhrn vypíše vše, co se smaže, a vyžaduje potvrzení. Při startu jedno heslo: svazky pod `/` odemkne initramfs
  (`sd-encrypt` + `lvm2`, `rd.luks.name`), ostatní klíč v `/etc/cryptsetup-keys.d` na šifrovaném `/`.
- Bezobslužně: `sudo luxos-install --config install.conf --yes`
  (vzor: `/usr/share/luxos/installer/install.conf.example`; ruční rozdělení `DISK_MODE=layout` + `LAYOUT`,
  kontrola bez změn `luxos-install --check-layout soubor`).
- Pokročilí: připojit vlastní oddíly do `/mnt` a zvolit *Advanced* (např. dual-boot).
- Testy instalátoru: `packages/luxos-installer/tests/` (bez roota `test-layout.sh`, GUI `gui-smoke.py`,
  ve virtuálu jako root `vm-layout-test.sh`).

Instalace stahuje aktuální balíky z internetu; balíky LuxOS bere z lokálního repozitáře na ISO
(`/opt/luxos-repo`, kopíruje se i do nainstalovaného systému).

## Repozitáře balíků

LuxOS má dva podepsané repozitáře na `https://luxos.lux-ai.cz/repo/` (přehled: <https://luxos.lux-ai.cz/repo/>):

- `[luxos]` – systém LuxOS (`packages/*`),
- `[luxos-apps]` – aplikace ke stažení, např. LSL, LSL IDE, Lux Code (`packages/apps/*`).

Nainstalovaný systém z nich bere aktualizace (`lux update`) a aplikace (`lux install lsl`); libalpm ověřuje
podpis každého balíku klíčem z `luxos-keyring`. Live ISO instaluje z kopie repozitářů na médiu.

Přidání aplikace:

```bash
mkdir packages/apps/lux-code            # PKGBUILD jako u packages/apps/lsl
                                        # (lsl-ide: zdrojový archiv vytvoří packages/apps/lsl-ide/make-source.sh)
./build.sh apps                         # sestaví a podepíše jen [luxos-apps] (./build.sh packages = oba repozitáře)
scripts/publish-repo.sh                 # nahraje na server a přepne vydání (ponechá 3 předchozí)
```

Podpisový klíč je mimo projekt v `~/.local/share/luxos/signing` (bez něj vzniknou nepodepsané balíky
a `publish-repo.sh` odmítne nahrávat). Na serveru: `/srv/luxos-repo/{releases,current}`, Caddy blok
`handle_path /luxos/*` v `lsl.lux-ai.cz`.

## Balíčky LuxOS (.lux)

Vlastní formát aplikací: archiv `tar.zst` s `lux.json` (metadata, závislosti, příkazy), aplikací v `app/`
a soubory pro systém v `share/`; podepsaný klíčem LuxOS. Specifikace: [docs/lux-package-format.md](docs/lux-package-format.md),
vzor `docs/examples/hello-lux`. Balíčky patří do `lux-packages/<název>/`, repozitář je
`https://luxos.lux-ai.cz/repo/lux/` (Obchod LuxOS je nabízí mezi aplikacemi LuxOS).

```bash
lux pack lux-packages/moje-aplikace out/   # sestavit
lux install ./moje-aplikace-1.0-1-any.lux  # nainstalovat soubor (ověří podpis)
lux install hello-lux                      # z repozitáře LuxOS
```

## lux

Výchozí správce balíků. Transakce dělá přes libalpm (`pyalpm`, `/usr/lib/lux/lux_alpm.py`): databáze
`/var/lib/lux`, cache `/var/cache/lux/pkg`, log `/var/log/lux.log`, klíčenka `/etc/lux/keyring`, konfigurace
`/etc/lux/lux.conf` ve vlastním formátu (`klíč hodnota`, bloky `repo NÁZEV`, `hold`, `include /etc/lux/conf.d/*.conf`)
a zrcadla `/etc/lux/mirrorlist` (jedna adresa na řádek). Konfiguraci jádra `/run/lux/engine.conf` z ní generuje
`lux-config` (nikdo ji neupravuje); chyba v `lux.conf` = hlášení se souborem a řádkem, `lux config check`.
Bez `pyalpm` (nebo `LUX_BACKEND=engine`) volá nástroj jádra `/usr/lib/lux/alpm/bin/lux-engine`. Obchod LuxOS
a LuxOS Care volají `lux_alpm.py --machine` (řádky `@@…`). Podrobně: [packages/lux/lux.md](packages/lux/lux.md).

**Jádro `lux-engine`**: libalpm a nástroje pacmanu z Arch Linuxu sestavené ze stejných zdrojů a součtů jako
v Archu (libalpm, makepkg, `vercmp`, `repo-add`, hooky); LuxOS mění jen názvy, cesty a balení. Příkaz `pacman`
v systému není: interní nástroje `lux-engine`, `lux-engine-key`, `lux-engine-conf` a `lux-engine-db-upgrade` jsou
v `/usr/lib/lux/alpm/bin` (mimo `PATH`, bez manuálů a doplňování). Dostane je `lux` (a hooky a skriptlety jeho
transakcí), `makepkg` (`/etc/makepkg.conf.d/lux-engine.conf`), služba `archlinux-keyring-wkd-sync` (drop-in)
a nástroje LuxOS; `pacman-contrib`, `pacman-mirrorlist` ani `expac` LuxOS nepotřebuje. Starší instalace převede
při aktualizaci hook `00-lux-engine-migrate` (`/var/lib/pacman` → `/var/lib/lux`, `/etc/pacman.conf` →
`/etc/lux/lux.conf` …); podrobně v [packages/lux/lux.md](packages/lux/lux.md). Shell LuxOS na `pacman …` odpoví odpovídajícím
příkazem `lux` (`pacman -Syu` → `lux update`). `lux-engine` nahrazuje `pacman` i `luxos-pacman` z LuxOS 0.9
(`replaces`/`provides`) a musí držet krok s verzí v Archu (`pyalpm` z Archu se sestavuje proti jeho
`libalpm.so`) – `build.sh` varuje, když je Arch novější; postup aktualizace je v hlavičce
`packages/lux-engine/PKGBUILD`. Testy: `python3 -m unittest discover -s packages/lux-engine/tests`
(formát `lux.conf`, generování konfigurace jádra a migrace na falešném kořeni)
(nápověda a shell: `packages/lux/tests/test_pacman_hint.py`).

| Příkaz | Co dělá |
|---|---|
| `lux` | interaktivní obchod v terminálu (Enter instalovat, Ctrl-R odebrat) |
| `lux install <balík…>` | repozitáře → LuxOS (`.lux`) → AUR → Flathub; i soubor `.lux` / `.pkg.tar.zst` |
| `lux remove <balík…>` | odebere i nepotřebné závislosti |
| `lux update` / `lux upgrade` | obnoví databáze, nejdřív klíče, celý systém + AUR + `.lux` + Flatpak |
| `lux search <výraz>` · `lux info <balík>` | hledání a podrobnosti (repozitáře, LuxOS, AUR) |
| `lux list [--installed\|--upgradable]` | nainstalované balíky / dostupné aktualizace (`--explicit`, `--aur`, `--orphans`, `--lux`) |
| `lux reinstall <balík…>` | stejná verze znovu |
| `lux autoremove` | odebere závislosti, které už nic nepotřebuje |
| `lux files <balík>` · `lux owns <soubor>` | soubory balíku / komu patří soubor |
| `lux clean` | vyčistí cache balíků (+ nabídne `autoremove`) |
| `lux fix` | opraví zamčenou databázi a podpisové klíče |
| `lux configs` | porovná a sloučí nové konfigurační soubory (`.pacnew`) |
| `lux history [počet] [balík]` | poslední změny balíků |
| `lux drivers` · `lux doctor` · `lux mirrors` · `lux pack` | ovladače, kontrola systému, zrcadla, sestavení `.lux` |

Výstup: `Install 3 packages (12.4 MB download, +48 MB disk)? [Y/n]`, jedna řádka s pruhem na fázi
(stahování, ověření, instalace) a souhrn `✓ Installed firefox 131.0-1 (+2 deps) in 8.2 s`; chyby jednou
větou, detaily s `--verbose`. `-y` přeskočí otázky (jinak se `lux` vždy zeptá), práva správce přes
`sudo`/`pkexec` automaticky, `NO_COLOR` a přesměrovaný výstup bez barev.

Konfigurace `/etc/lux/lux.conf` (AUR, kontrola PKGBUILD, Flatpak, velikost cache).

Testy (bez rootu, napodobenina pyalpm): `python3 -m unittest discover -s packages/lux/tests`.

## Struktura

```
build.sh                    sestavení (podman/docker)
scripts/                    Containerfile, build v kontejneru, test VM, publish-repo.sh
archiso/                    profil ISO (odvozený z archiso releng)
packages/                   vlastní balíky LuxOS (lokální repozitář [luxos])
  luxos-branding            logo, tapety, Plymouth, os-release
  luxos-themes              WhiteSur GTK/xfwm4/Plank/ikony/kurzory (pevné commity)
  luxos-desktop             nastavení Xfce, dock, Hledání/Launchpad, LightDM, aplikace
  luxos-shell               konfigurace shellu: ble.sh, zsh, starship, fastfetch
  lsh                       Lux Shell (fork GNU bash: about, LSL, pip)
  luxos-keyring             podpisový klíč repozitářů
  luxos-i18n                překlady (cs) pro skripty a aplikace
  luxos-store               Obchod LuxOS
  apps/                     aplikace pro repozitář [luxos-apps]
    lsl                     Lux Simple Lang (oficiální binární vydání)
  luxos-tweaks              výkon: zram, sysctl, I/O, oomd, journald
  luxos-drivers             luxos-hwdetect, aplikace Ovladače
  nvidia-580xx-utils …      legacy ovladače NVIDIA z AUR (580xx, 470xx a lib32), jen online, ne v ISO
  luxos-installer           luxos-install
  luxdrop                   LuxDrop – bezpečné posílání souborů v síti, kompatibilní s LocalSend (GTK, CLI, protokol)
  lux                       správce balíků
  lux-engine                jádro lux: libalpm a nástroje z pacmanu Archu (makepkg…), lux.conf, lux-config, bez příkazu pacman
  gdk-pixbuf2               náhrada balíku z Archu bez glycinu: obrázky a ikony se dekódují v procesu aplikace
  luxos-pixbuf-svg          zavaděč SVG pro gdk-pixbuf (librsvg, v procesu)
  blesh                     ble.sh
```

Výchozí nastavení desktopu jsou v `/etc/xdg/luxos` (má přednost před `/etc/xdg` přes `XDG_CONFIG_DIRS`),
takže LuxOS nepřepisuje soubory jiných balíků a uživatelské změny mají vždy přednost.

## Klávesové zkratky

| Zkratka | Akce |
|---|---|
| `Super+Mezerník` | Hledání |
| `Super+A` | Launchpad |
| `Super+Q` | zavřít okno |
| `Super+M` / `Super+H` | minimalizovat |
| `Super+Tab` | přepínání oken |
| `Super+↑ / ← / →` | maximalizovat / půl obrazovky |
| `Ctrl+Super+F` | celá obrazovka |
| `Super+Shift+3 / 4 / 5` | snímek obrazovky / výřezu / nástroj |
| `Super+L`, `Ctrl+Super+Q` | zamknout |
| `Super+Alt+Esc` | správce úloh (vynutit ukončení) |
| `Super+,` | nastavení |
| klávesa Kalkulačka | Kalkulačka LuxOS |

## Licence

Vlastní skripty a konfigurace LuxOS: MIT. lsh: GPL‑3.0 (fork GNU bash). LSL: MIT. Témata WhiteSur © vinceliuice (MIT/GPL‑3.0), ble.sh © Koichi Murase (BSD‑3).

## Licence

Kód LuxOS (balíčky `luxos-*`, `lux`, `luxdrop`, skripty a instalátor) je pod licencí
**GPL-3.0-or-later** – viz [LICENSE](LICENSE). Balíčky a záplaty třetích stran (rofi, xfce4-genmon-plugin,
ovladače NVIDIA, jádro Linux, LSL…) mají vlastní licence uvedené v jejich `PKGBUILD`.

## Sestavení

- Lokálně: `./build.sh` (podman nebo docker), viz začátek `build.sh`.
- GitHub Actions: workflow **Build** (`.github/workflows/build.yml`) – `packages` sestaví balíčky
  (nepodepsané), `iso` sestaví ISO ze zveřejněných podepsaných repozitářů. Soukromý podpisový klíč
  LuxOS na GitHubu není: balíčky a ISO podepisuje správce lokálně.

