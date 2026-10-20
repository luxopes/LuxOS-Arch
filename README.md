# ✦ LuxOS

Rychlý a lehký Linux na Arch Linuxu s prostředím ve stylu macOS.

- **Rychlost a nenáročnost:** Xfce + vestavěný kompozitor xfwm4 (žádný těžký shell), jádro `linux-zen`,
  zram swap (zstd), ladění sysctl, I/O plánovače podle typu disku, systemd-oomd, Btrfs se zstd kompresí,
  systemd initramfs, squashfs ISO v zstd (rychlý start live systému).
- **Vzhled macOS:** horní lišta (logo-menu, název aktivní aplikace, ikony, hodiny), dock Plank se zvětšováním,
  tlačítka oken vlevo (semafor), WhiteSur GTK/ikony/kurzory, písmo Inter, Spotlight (`Super+Mezerník`),
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
- **`lux`** – správce balíků LuxOS (zatím nad pacmanem, AUR a Flatpakem; připravený na vlastní repozitář).

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

## lux

```
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
scripts/                    Containerfile, build v kontejneru, test VM
archiso/                    profil ISO (odvozený z archiso releng)
packages/                   vlastní balíky LuxOS (lokální repozitář [luxos])
  luxos-branding            logo, tapety, Plymouth, os-release
  luxos-themes              WhiteSur GTK/xfwm4/Plank/ikony/kurzory (pevné commity)
  luxos-desktop             nastavení Xfce, dock, Spotlight/Launchpad, LightDM, aplikace
  luxos-shell               konfigurace shellu: ble.sh, zsh, starship, fastfetch
  lsh                       Lux Shell (fork GNU bash: about, LSL, pip)
  lsl                       Lux Simple Lang (oficiální binární vydání)
  luxos-tweaks              výkon: zram, sysctl, I/O, oomd, journald
  luxos-drivers             luxos-hwdetect
  luxos-installer           luxos-install
  lux                       správce balíků
  blesh                     ble.sh
```

Výchozí nastavení desktopu jsou v `/etc/xdg/luxos` (má přednost před `/etc/xdg` přes `XDG_CONFIG_DIRS`),
takže LuxOS nepřepisuje soubory jiných balíků a uživatelské změny mají vždy přednost.

## Klávesové zkratky

| Zkratka | Akce |
|---|---|
| `Super+Mezerník` | Spotlight |
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
