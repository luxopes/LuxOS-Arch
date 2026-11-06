# LuxOS changelog

LuxOS versions are numbered `X.Y.Z`: `Y` grows with every new ISO, `Z` with bug fixes, and every major
version carries the name of a star (currently **Polaris**). LuxOS is a rolling release: installed
systems update continuously with `lux update`, so the version tells which state the system started
from. The detailed changelog is maintained in Czech ([Czech version](/cs/zmeny/)); this page
summarises the recent releases in English.

## 1.0.0 "Sirius" – 2026-11-04 (unstable)

An unstable release: there are still bugs. Compared with 0.9.12 "Polaris" (installed systems get everything with
`lux update`):

### New apps
- **Terminal** – our own fast terminal (GTK3 + VTE) in the style of macOS: tabs, images in the
  terminal (SIXEL), and every tab in its own process group, so a runaway program or a fork bomb
  only blocks its own tab, never the desktop.
- **Text Editor** – our own editor replacing Mousepad: folder sidebar, syntax highlighting, tabs.
- **Maps** – smooth OpenStreetMap maps, search with suggestions while typing (LuxOS's own fast
  geocoder for Czechia and Slovakia), routes by car, bike, on foot and by public transport, and
  **turn-by-turn navigation** with GPS, automatic rerouting (also for public transport) and a
  smoothly moving position arrow; resizable sidebar.
- **Weather** – current weather, 24-hour and 7-day forecast, several places.
- **Backups** – automatic hourly incremental backups of your home folder to a USB disk or a network
  disk (SFTP, SMB), only while charging.
- **Phone – LuxOS Companion** – connect an Android phone over Bluetooth: LuxDrop file transfer,
  phone calendar, and LuxAI remote sessions from the phone with one-time approvals on the phone.
- **Connect to a Computer** – the files of another LuxOS computer next to yours, drag and drop
  between them (LuxDrop).
- **Network admin (Router)**, **Wi‑Fi QR code**, **LuxAI Account**, **Profile picture**,
  **Reset app settings**.

### System
- **System snapshots before every update** and **LuxOS Recovery** in the boot menu: go back to a
  working system after a bad update, disk checks.
- **System protection** – system files in `/usr` are read-only and only change through package
  updates.
- **The whole system in one file**: `/etc/luxos/system.lsl` (like NixOS `configuration.nix`) –
  packages, Flathub apps, services, users, network, printers, power, created at installation.
- **Company networks**: join a Windows Active Directory or Samba AD domain without changes on the
  domain side; organisation policies in `lux system`.
- **OEM / prepare for another person** with a full-screen Setup Assistant and sealing.
- **Faster and smoother**: the scx_lavd scheduler gives windows, input, sound and games priority;
  login without a black screen (wallpaper with a spinner like macOS); the lock screen looks like the
  login screen; analog-clock screen saver.
- **Update channels** stable/staging; `/etc/lux/lux.conf` in TOML; `lux search` patterns like
  aptitude (`^vim`, `vim$`, `*qt*`).
- **Performance mode uses the whole computer**: maximum CPU performance and, on hybrid-graphics
  laptops, the NVIDIA/AMD discrete GPU for games (Steam, Heroic, Lutris…) automatically; the desktop
  stays on the integrated GPU.
- **Flathub apps appear in Launchpad immediately** after installing, without logging out.
- **Community (AUR) apps in the sandbox start like normal apps**: type the command or find
  "App (Sandbox)" in Launchpad; two-layer PKGBUILD review (fixed rules + LuxAI).
- **LuxAI 2.0** rewritten natively in LSL (starts faster, uses less memory), calendar tools, reliable
  tool calls and code display.
- **Sound switches automatically** to a connected monitor (HDMI/DP), USB or Bluetooth device;
  labelled output/input sliders.
- **Launchpad sorting** (alphabetical, recent, most used, by category), **Alt+Tab with window
  previews**, notifications that expand on click and never cover the top bar menus, monitor
  arrangement like macOS, new LuxOS menu, search button in the top bar.

### Security and stability fixes
- **The screen lock asks for the password immediately** – before, the password was required only one
  minute after the screen saver started, so pressing Enter in that minute returned to the desktop.
- **A fork bomb no longer takes down the desktop.**
- Stronger Safe encryption (scrypt 2^18), Lux Guard improvements, captive portals (train/hotel
  Wi‑Fi) also with Tailscale/VPN DNS.
- Low memory no longer kills the session's core services (notifications, settings, portals,
  accessibility); notifications and the volume icon recover by themselves; a memory leak in the
  Bluetooth window is fixed.
- Printers: Canon UFR II printers (e.g. MF4100) are added with one click.
- Many more fixes – the full list is in the [Czech changelog](/cs/zmeny/).

## 0.9.12 "Polaris" – 2026-10-26 (beta)

New ISO: the ISO 0.9.7–0.9.11 failed on computers with DKMS drivers (NVIDIA, Broadcom) with "target
not found: linux-luxos-headers"; the kernel headers are back on the ISO.

- **The terminal no longer freezes**: the prompt (starship) has a time limit and an emergency prompt,
  and ssh/sshfs detect a dead connection within about 45 seconds.
- **Lux Code no longer freezes** on a network folder in the working directory.
- Multi-line commands pasted into the terminal run with Enter.
- Sharp icons in Alt+Tab, a single brightness indicator when scrolling, Battery Saver no longer turns
  off GTK animations, fewer network notifications.
- **lux**: installation errors show the real cause; a 404 from a mirror is reported as an outdated
  package list ("run lux update first").
- **Installer**: closing the window asks first, 5 download attempts, the default keyboard is US with
  the local layout added as second, LuxAI sign-in is retried after Wi-Fi connects.

## 0.9.11 "Polaris" – 2026-10-24

- **LuxAI searches the web** (`web_search`, `web_fetch`) in all modes. Web content is untrusted data,
  and once it is in a conversation every Agent command needs confirmation. See [LuxAI](/docs/luxos/luxai.html).
- LuxAI renders LaTeX formulas, highlights code and copies text.
- **Manual pages** from the LuxOS documentation: `man luxos`, `man lux.conf`, `man lsl`,
  `man luxos-sandbox`, `luxos-safe`, `luxos-guard`, `luxos-care`, `luxdrop`.
- **Notification history** in the top bar bell (last 100 notifications).
- Installer: bigger *Everyday use* and *Programming* software sets.
- Fixes: brightness by scrolling on the battery icon, Launchpad hover highlight, lock and login screen
  use the desktop wallpaper, screenshots go to Pictures › Screenshots.

## 0.9.10 "Polaris" – 2026-10-24

- **Verified printer and scanner drivers**: the signed repository `[luxos-drivers]` with vendor
  drivers (Brother, Canon, Epson, Kyocera, Ricoh, Samsung, Xerox) checked by strict rules and built
  without network access; 689 drivers, an index of 4,354 printer models and 233 scanner USB IDs. The
  driver installs itself when you plug the printer in.
- **Community (AUR) packages, safely**: `lux install` searches repositories, `.lux` apps, Flathub and
  then AUR. Package scripts are checked by fixed rules and LuxAI Lite, and built and installed in the
  Sandbox.
- **Flathub in `lux` and Lux Store**, for example `lux install zoom`.
- A password no longer locks the account; only brute-force speed is limited.

## 0.9.9 "Polaris" – 2026-10-24

- **An encrypted disk never fails silently**: a clear message for a wrong password, unlimited tries
  and a boot-failure log on the EFI partition.
- Dual-boot installer fixes, Ventoy support, `lux check` and `man lux`.

## Earlier releases

| Version | Highlights |
|---|---|
| 0.9.8 | LuxOS kernel on older installs, brightness by scrolling on the battery, daylight saving time reminders |
| 0.9.7 | own `linux-luxos` kernel, Lux Guard, captive portal sign-in, Control Center and Calendar rewritten in LSL |
| 0.9.6 | no pacman at all: own `lux.conf` format and `lux-engine` |
| 0.9.5 | Screenshot copy and save actions, named LuxAI conversations, Super alone opens Launchpad |
| 0.9.4 | faster startup and lower memory use |
| 0.9.3 | stronger Data and Battery Saver, `adduser`, `service` and `about` commands in lsh, secure erase in the installer |
| 0.9.2 | several keyboard layouts, editable Keyboard Shortcuts |
| 0.9.1 | Screenshot tool with recording, Displays app, fingerprint login, `lux configs` |
| 0.9.0 | first numbered version: macOS-like desktop over Xfce, LuxOS apps, `lux` with signed repositories, automatic drivers, installer with LUKS2 and LVM, LuxAI account |

For the full history see the [LuxOS overview](/docs/luxos/overview.html) and the
[Czech changelog](/cs/zmeny/).
