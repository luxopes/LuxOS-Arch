# LuxOS overview

LuxOS is a fast, lightweight Linux distribution based on **Arch Linux** with a **macOS-like
desktop**. Its priorities, in order: speed and low resource use, macOS-style design, and
hassle-free drivers. It is a rolling release: installed systems are updated continuously with
`lux update` (automatically by LuxOS Care), and the version number tells which state the system
started from.

## Version and codenames

- Current version: **0.9.11 "Polaris"** (beta, 2026-10-24). The exact installed version is always in `/usr/lib/os-release`.
- Single source of the version: `/usr/lib/os-release` (written by `luxos-branding`):
  `ID=luxos`, `ID_LIKE=arch`, `VERSION_ID=0.9.11`, `PRETTY_NAME="LuxOS … Polaris"`, `BUILD_ID` =
  build day. `/etc/os-release` links to it. The same version appears in About This Computer,
  fastfetch and the ISO name.
- Numbering `X.Y.Z`: `Y` grows with every new ISO, `Z` with bug-fix releases. Every major version
  carries the name of a star: Polaris, then Sirius, Vega, Rigel, Altair, ...
- Check it: `cat /etc/os-release`, `about os` (in the lsh shell), `fastfetch`, or `luxos-about`.

### Release history

| Version | Highlights |
|---|---|
| 0.9.0 | first numbered version: macOS-like desktop over Xfce, LuxOS apps (Store, LuxAI, Lux Code, LSL IDE, Calculator, Camera, Scanner, Printers & Scanners, Drivers, System Monitor, Bluetooth, Battery & Power, Safe, LuxDrop, Feedback), `lux` with signed `[luxos]`/`[luxos-apps]` repos, automatic driver detection, earlyoom, Data/Battery Saver, automatic maintenance, 13 languages, installer with whole disk / free space / existing partition / manual LVM+LUKS2 and app sets, LuxAI account in the installer |
| 0.9.1 | Screenshot tool with recording, Displays (resolution, refresh rate, rotation with 15 s confirmation, text size), fingerprint login, What's New, `lux configs`; **no `pacman` command any more** – the engine is `lux-engine` |
| 0.9.2 | several keyboard layouts (installer and Keyboard Layouts app), editable Keyboard Shortcuts, automatic switch to newly connected audio outputs, fix for "unresolvable package conflicts" on older installs |
| 0.9.3 | stronger Data/Battery Saver, closing the lid keeps media playing, `adduser`/`service`/`about` commands in lsh, installer secure erase, new Alt+Tab |
| 0.9.4 | faster startup and lower memory use (image loaders, lazy windows) |
| 0.9.5 | Screenshot copy/save actions, named LuxAI conversations, Super alone opens Launchpad |
| 0.9.6 | no pacman at all: own `/etc/lux/lux.conf` format, `lux-engine`; more parts rewritten in LSL |
| 0.9.7 | own `linux-luxos` kernel, Lux Guard (blocks dangerous downloads outside the Sandbox), captive portal sign-in, Control Center and Calendar in LSL |
| 0.9.8 | LuxOS kernel on older installs, brightness by scrolling on the battery, daylight saving time reminders, formatted Store updates |
| 0.9.9 | encrypted disk start never fails silently (wrong password message, unlimited tries, boot failure log), dual-boot installer fixes, Ventoy, `lux check`, `man lux` |
| 0.9.10 | verified printer/scanner drivers in `[luxos-drivers]`, community (AUR) packages reviewed and installed into the Sandbox, Flathub in `lux` and Lux Store, no password lockouts (only brute-force rate) |
| 0.9.11 | Launchpad highlights the app under the pointer, notification history, lock/login screen use the desktop wallpaper, screenshots in Pictures/Screenshots, brightness scrolling fixed, LuxAI web search/fetch with prompt-injection protection, copy, math and code highlighting, man pages (`man luxos`), bigger Everyday/Programming app sets |

What's New after an update shows these items (data in `/usr/share/luxos/whats-new/<version>.json`).

## What makes LuxOS different from other distributions

| Area | LuxOS | Typical Arch/other distro |
|---|---|---|
| Package manager | **`lux`** (libalpm via pyalpm, plus AUR, Flatpak and `.lux` apps); **there is no `pacman` command** – typing it shows the matching `lux` command | `pacman`, `apt`, ... |
| Package engine | `lux-engine`: libalpm and tools from Arch's pacman, internal tools `lux-engine`, `lux-engine-key` in `/usr/lib/lux/alpm/bin` | `pacman` package |
| Package configuration | `/etc/lux/lux.conf` in TOML (`[repo.NAME]` tables, `hold`), mirrors `/etc/lux/mirrorlist`, data in `/var/lib/lux` – no `/etc/pacman.conf` | `/etc/pacman.conf` |
| Own repositories | signed `[luxos]` (system) and `[luxos-apps]` (apps such as `lsl`, `lsl-ide`, `lux-code`, `luxai`) at `https://luxos.lux-ai.cz/repo/` | – |
| App format | own `.lux` packages installed to `/opt/lux/<name>` | – |
| Desktop | Xfce parts (xfwm4 compositor, panel, xfdesktop, xfconf) styled like macOS: top bar, Plank Dock, Launchpad, Search, Control Center | GNOME/KDE/Xfce stock |
| Shell | **`lsh`** (Lux Shell, a GNU bash 5.3 fork) with `about`, LSL statements and a pip warning; ble.sh, starship, fzf, zoxide | bash/zsh |
| Programming | LSL (Lux Simple Lang) packaged as `lsl`, usable directly in the shell | – |
| Maintenance | **LuxOS Care**: automatic updates, previous-kernel fallback, self-repair | manual |
| Drivers | `luxos-hwdetect` + Drivers app (NVIDIA by generation incl. legacy 580xx/470xx, SOF audio, IPU6/7 cameras, Broadcom Wi-Fi, VM guests) | manual |
| Security extras | **Lux Guard** (checks programs from downloads/USB when started, dangerous ones only in the sandbox, hourly `/home` snapshots), **Safe** (`/safe/<user>`, gocryptfs) and **Sandbox** (`/dev/sandbox/<user>`, bubblewrap) | – |
| AI | **LuxAI** assistant, one shared LuxAI account for LuxAI, Lux Code and LSL IDE | – |
| Defaults | `/etc/xdg/luxos` first in `XDG_CONFIG_DIRS` – never overwrites other packages' files | edits in `/etc/xdg` |
| Performance | own `linux-luxos` kernel (stable kernel.org, auto-built), zram (zstd), earlyoom, sysctl tuning, I/O schedulers by disk type, Btrfs with zstd, hidden boot menu without waiting (systemd-boot `timeout 0`, GRUB `GRUB_TIMEOUT=0`; 3 s menu when other systems share the EFI partition), scx_lavd CPU scheduler (sched_ext), HZ=1000 kernel | varies |

## Main components

| Package | Content | Page |
|---|---|---|
| `lux`, `lux-engine`, `luxos-keyring` | package management | [package-management.md](package-management.md), [lux-engine-and-repos.md](lux-engine-and-repos.md), [lux-packages.md](lux-packages.md) |
| `luxos-store` | LuxOS Store | [store.md](store.md) |
| `luxos-care` | automatic updates and repairs, Software Update app | [care-updates.md](care-updates.md) |
| `luxos-drivers` | `luxos-hwdetect`, Drivers app | [drivers.md](drivers.md) |
| `luxos-desktop`, `luxos-themes`, `luxos-greeter`, `luxos-branding` | desktop, apps, login screen, splash | [desktop.md](desktop.md), [apps.md](apps.md), [settings-apps.md](settings-apps.md), [keyboard.md](keyboard.md) |
| `luxos-printing` | driverless printing and scanning | [printing-scanning.md](printing-scanning.md) |
| `luxdrop` | LuxDrop file sharing (LocalSend compatible) | [luxdrop.md](luxdrop.md) |
| `luxos-safe`, `luxos-sandbox` | encrypted folder, isolated app system | [safe.md](safe.md), [sandbox.md](sandbox.md) |
| `luxos-guard` | Lux Guard: check of downloaded programs, `/home` snapshots | [guard.md](guard.md) |
| `luxos-backup` | Backups: hourly backups of the home folder to an external or network disk, restore | [backups.md](backups.md) |
| `luxos-tweaks` | zram, sysctl, earlyoom, journald, I/O | [power-and-performance.md](power-and-performance.md) |
| `lsh`, `luxos-shell`, `blesh` | shell, prompt, aliases, fastfetch | [shell.md](shell.md) |
| `luxos-installer` | `luxos-install` (text and GUI) | [installer.md](installer.md) |
| `luxos-account` | LuxAI account | [luxai-account.md](luxai-account.md) |
| `luxos-i18n` | translations (English + 12 languages, e.g. Czech, Slovak, German, Polish) | |
| `luxos-docs` | this offline documentation in `/usr/share/luxos/docs` | |

Where settings are stored: [configuration.md](configuration.md). Fixing problems:
[troubleshooting.md](troubleshooting.md). Guidance for AI assistants working on a LuxOS computer:
[for-ai-assistants.md](for-ai-assistants.md). The programming language LSL:
[LSL overview](../lsl/overview.md). The same pages are installed as manual pages generated from
this documentation: start with `man luxos`, then e.g. `man lux.conf`, `man luxos-care`, `man lsl`.

## Default software

Firefox (hardware video decoding via VA-API), Files (Thunar), Terminal (`luxos-terminal` with
`lsh`, see [terminal.md](terminal.md)), Text Editor (`luxos-text`, see [text-editor.md](text-editor.md)), Ristretto, Evince, Xarchiver, Celluloid, plus the LuxOS apps. PipeWire audio,
Bluetooth, NetworkManager, driverless printing (IPP Everywhere) and scanners work out of the box.
More apps: LuxOS Store or `lux install NAME`. The installer can add app sets (Everyday,
Programming, Video & Photo, Gaming, Security & Networking).

## Languages

UI strings are English; LuxOS apps and scripts are translated by `luxos-i18n` according to the
system language (13 languages in total). The installer switches language as soon as it is chosen.
