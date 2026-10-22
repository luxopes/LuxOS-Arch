# LuxOS overview

LuxOS is a fast, lightweight Linux distribution based on **Arch Linux** with a **macOS-like
desktop**. Its priorities, in order: speed and low resource use, macOS-style design, and
hassle-free drivers. It is a rolling release: installed systems are updated continuously with
`lux update` (automatically by LuxOS Care), and the version number tells which state the system
started from.

## Version and codenames

- Current version: **0.9.2 "Polaris"** (beta, 2026-10-22).
- Single source of the version: `/usr/lib/os-release` (written by `luxos-branding`):
  `ID=luxos`, `ID_LIKE=arch`, `VERSION_ID=0.9.2`, `PRETTY_NAME="LuxOS … Polaris"`, `BUILD_ID` =
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

What's New after an update shows these items (data in `/usr/share/luxos/whats-new/<version>.json`).

## What makes LuxOS different from other distributions

| Area | LuxOS | Typical Arch/other distro |
|---|---|---|
| Package manager | **`lux`** (libalpm via pyalpm, plus AUR, Flatpak and `.lux` apps); **there is no `pacman` command** – typing it shows the matching `lux` command | `pacman`, `apt`, ... |
| Package engine | `lux-engine`: libalpm and pacman tools from Arch, internal tools in `/usr/lib/lux/alpm/bin` | `pacman` package |
| Own repositories | signed `[luxos]` (system) and `[luxos-apps]` (apps such as `lsl`, `lsl-ide`, `lux-code`, `luxai`) at `https://lsl.lux-ai.cz/luxos/` | – |
| App format | own `.lux` packages installed to `/opt/lux/<name>` | – |
| Desktop | Xfce parts (xfwm4 compositor, panel, xfdesktop, xfconf) styled like macOS: top bar, Plank Dock, Launchpad, Search, Control Center | GNOME/KDE/Xfce stock |
| Shell | **`lsh`** (Lux Shell, a GNU bash 5.3 fork) with `about`, LSL statements and a pip warning; ble.sh, starship, fzf, zoxide | bash/zsh |
| Programming | LSL (Lux Simple Lang) packaged as `lsl`, usable directly in the shell | – |
| Maintenance | **LuxOS Care**: automatic updates, previous-kernel fallback, self-repair | manual |
| Drivers | `luxos-hwdetect` + Drivers app (NVIDIA by generation incl. legacy 580xx/470xx, SOF audio, IPU6/7 cameras, Broadcom Wi-Fi, VM guests) | manual |
| Security extras | **Safe** (`/safe/<user>`, gocryptfs) and **Sandbox** (`/dev/sandbox/<user>`, bubblewrap) | – |
| AI | **LuxAI** assistant, one shared LuxAI account for LuxAI, Lux Code and LSL IDE | – |
| Defaults | `/etc/xdg/luxos` first in `XDG_CONFIG_DIRS` – never overwrites other packages' files | edits in `/etc/xdg` |
| Performance | `linux-zen` kernel, zram (zstd), earlyoom, sysctl tuning, I/O schedulers by disk type, Btrfs with zstd, hidden boot menu (systemd-boot `timeout 0`; 3 s menu when other systems share the EFI partition) | varies |

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
| `luxos-tweaks` | zram, sysctl, earlyoom, journald, I/O | [power-and-performance.md](power-and-performance.md) |
| `lsh`, `luxos-shell`, `blesh` | shell, prompt, aliases, fastfetch | [shell.md](shell.md) |
| `luxos-installer` | `luxos-install` (text and GUI) | [installer.md](installer.md) |
| `luxos-account` | LuxAI account | [luxai-account.md](luxai-account.md) |
| `luxos-i18n` | translations (English + 12 languages, e.g. Czech, Slovak, German, Polish) | |
| `luxos-docs` | this offline documentation in `/usr/share/luxos/docs` | |

Where settings are stored: [configuration.md](configuration.md). Fixing problems:
[troubleshooting.md](troubleshooting.md). Guidance for AI assistants working on a LuxOS computer:
[for-ai-assistants.md](for-ai-assistants.md). The programming language LSL:
[LSL overview](../lsl/overview.md).

## Default software

Firefox (hardware video decoding via VA-API), Files (Thunar), Terminal (xfce4-terminal with
`lsh`), Mousepad, Ristretto, Evince, Xarchiver, Celluloid, plus the LuxOS apps. PipeWire audio,
Bluetooth, NetworkManager, driverless printing (IPP Everywhere) and scanners work out of the box.
More apps: LuxOS Store or `lux install NAME`. The installer can add app sets (Everyday,
Programming, Video & Photo, Gaming, Security & Networking).

## Languages

UI strings are English; LuxOS apps and scripts are translated by `luxos-i18n` according to the
system language (13 languages in total). The installer switches language as soon as it is chosen.
