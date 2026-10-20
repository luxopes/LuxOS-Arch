# ✦ LuxOS

Rychlý a lehký Linux na Arch Linuxu s prostředím ve stylu macOS.

- **Rychlost a nenáročnost:** Xfce + vestavěný kompozitor xfwm4 (žádný těžký shell), jádro `linux-zen`,
  zram swap (zstd), ladění sysctl, I/O plánovače podle typu disku, systemd-oomd, Btrfs se zstd kompresí,
  systemd initramfs, squashfs ISO v zstd (rychlý start live systému).
- **Vzhled macOS:** horní lišta (logo-menu, název aktivní aplikace, ikony, hodiny), dock Plank se zvětšováním,
  tlačítka oken vlevo (semafor), WhiteSur GTK/ikony/kurzory, písmo Inter, Hledání (`Super+Mezerník`),
  Launchpad (`Super+A`), zkratky ve stylu Cmd (`Super+Q`, `Super+Shift+4`…), přirozené posouvání na touchpadu,
  přepínání světlého/tmavého režimu.
- **Bez starostí s ovladači:** `luxos-hwdetect` při instalaci rozpozná GPU (Intel/AMD/NVIDIA včetně hybridní
  grafiky), Wi‑Fi Broadcom, čtečky otisků, akcelerometry a virtualizaci (VirtualBox, VMware, QEMU, Hyper‑V).
  Po instalaci kdykoli `lux drivers`. PipeWire, Bluetooth, tisk bez ovladačů (IPP Everywhere) a skenery v základu.
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
- **Splash screeny:** Plymouth (černá + logo + tenký progress bar, i pro zadání hesla k LUKS), skrytý zavaděč
  (systemd-boot `timeout 0`), přihlašovací obrazovka uprostřed (lightdm-gtk-greeter), ISO boot menu v barvách LuxOS.
- **`lux`** – správce balíků LuxOS (nad pacmanem, AUR a Flatpakem); `lux` bez parametrů otevře interaktivní
  obchod v terminálu (TUI) s balíky z repozitářů LuxOS i Arch Linuxu.
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
- **LuxDrop** – šifrovaný přenos souborů mezi počítači LuxOS (ověření kódem, připnuté klíče).
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
- Pokročilí: připojit vlastní oddíly do `/mnt` a zvolit *Advanced* (např. dual-boot).
- Bezobslužně: `sudo luxos-install --config install.conf --yes`
  (vzor: `/usr/share/luxos/installer/install.conf.example`).

Instalace stahuje aktuální balíky z internetu; balíky LuxOS bere z lokálního repozitáře na ISO
(`/opt/luxos-repo`, kopíruje se i do nainstalovaného systému).

## Repozitáře balíků

LuxOS má dva podepsané repozitáře na `https://lsl.lux-ai.cz/luxos/` (přehled: <https://lsl.lux-ai.cz/luxos/>):

- `[luxos]` – systém LuxOS (`packages/*`),
- `[luxos-apps]` – aplikace ke stažení, např. LSL, LSL IDE, Lux Code (`packages/apps/*`).

Nainstalovaný systém z nich bere aktualizace (`lux update`) a aplikace (`lux install lsl`); pacman ověřuje
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
`https://lsl.lux-ai.cz/luxos/lux/` (Obchod LuxOS je nabízí mezi aplikacemi LuxOS).

```bash
lux pack lux-packages/moje-aplikace out/   # sestavit
lux install ./moje-aplikace-1.0-1-any.lux  # nainstalovat soubor (ověří podpis)
lux install hello-lux                      # z repozitáře LuxOS
```

## lux

```
lux                        # interaktivní obchod v terminálu (Enter instalovat, Ctrl-R odebrat)
lux install firefox        # repozitáře → AUR → Flathub
lux remove <balík>
lux update                 # systém + AUR + Flatpak, nejdřív klíče
lux search <výraz>
lux drivers                # doinstaluje chybějící ovladače
lux doctor                 # kontrola systému
lux clean | mirrors | history | info | files | owner
```

Konfigurace `/etc/lux/lux.conf` (AUR, kontrola PKGBUILD, Flatpak, velikost cache).

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
  luxos-drivers             luxos-hwdetect
  luxos-installer           luxos-install
  luxdrop                   LuxDrop – bezpečné posílání souborů v síti (GTK, CLI, protokol)
  lux                       správce balíků
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
