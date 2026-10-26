# LuxOS changelog

LuxOS versions are numbered `X.Y.Z`: `Y` grows with every new ISO, `Z` with bug fixes, and every major
version carries the name of a star (currently **Polaris**). LuxOS is a rolling release: installed
systems update continuously with `lux update`, so the version tells which state the system started
from. The detailed changelog is maintained in Czech ([Czech version](/cs/zmeny/)); this page
summarises the recent releases in English.

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
