# Press release (English)

> Ready to paste. Facts checked against CHANGELOG.md, packages/apps/luxos-docs/docs and site/iso.json
> on 2026-11-08. Screenshot links point to the current site gallery; if the site agent renames files in
> `site/assets/shots/`, update the links before sending.

---

**For immediate release – Prague, Czech Republic, 8 November 2026**

## LuxOS 1.0.1 "Sirius" beta: an Arch-based Linux with a macOS-like desktop, its own package manager and its own kernel build

LuxOS, an independent Linux distribution developed in the Czech Republic by Antonín Tomeček, has
released version 1.0.1 "Sirius" with a new installation ISO. LuxOS is based on Arch Linux and uses
Xfce components underneath a desktop styled after macOS. It is a free download and is licensed
GPL-3.0-or-later. **The project is in beta: the developer asks users to expect bugs and to back up
their data before installing.**

### What LuxOS is

- **A macOS-style desktop on a light base.** Top bar with the app name and a Control Center, the Plank
  dock, Launchpad (`Super+A`), Search (`Super+Space`), window buttons on the left and light/dark mode.
  Underneath it is Xfce (xfwm4, the Xfce panel), not a heavy shell. LuxOS draws its own icons and does
  not use Apple logos or icons.
- **Its own package manager, `lux`.** There is no `pacman` command: `lux` uses libalpm (the library
  behind pacman) with its own configuration in `/etc/lux/lux.conf`, and installs from the Arch and
  signed LuxOS repositories, Flathub and AUR packages, which are reviewed and built in a sandbox.
  A graphical LuxOS Store sits on top of it.
- **Its own kernel build, `linux-luxos`.** Vanilla stable Linux from kernel.org with Arch's
  configuration as the base and LuxOS settings (HZ=1000, full preemption, sched_ext), with no
  out-of-tree patches. It is built automatically by GitHub Actions and smoke-tested in QEMU before
  release. The default CPU scheduler on desktops is `scx_lavd`.
- **Updates you can undo.** LuxOS Care installs updates in the background, takes a read-only Btrfs
  snapshot of the system before every update (`luxos-care rollback` goes back) and keeps the previous
  kernel in the boot menu. `/usr` is mounted read-only outside package transactions, and a weekly
  check repairs changed system files from the signed repositories.
- **Security extras.** Lux Guard checks programs that came from outside the computer (downloads,
  attachments, USB drives) when they start and offers to run them in a sandbox; it also keeps hourly
  snapshots of `/home`. A firewall (nftables) is on by default, and an encrypted folder ("Safe") is
  included.
- **Automatic drivers.** Intel, AMD and NVIDIA graphics (including legacy NVIDIA branches and hybrid
  laptops), Intel SOF audio, Broadcom Wi-Fi, fingerprint readers and virtual machine guest tools are
  detected during installation and afterwards.
- **LuxAI assistant and the LSL language.** LuxAI is an optional desktop assistant with a chat mode and
  an agent mode that asks before risky actions; it needs a LuxAI account with monthly usage limits.
  Several system apps are written in LSL (Lux Simple Lang), the author's own compiled language.
- **13 languages**, including English, Czech, Slovak, German and Polish.

### What is new in 1.0.1

1.0.1 is a bug-fix release of 1.0.0 "Sirius" (4 November 2026) with a new ISO. Highlights:

- A firewall is now on from the start, with **Allow / Keep Blocked** prompts and a Settings panel;
  local services such as printers, LuxDrop, Steam Remote Play and KDE Connect keep working.
- `/tmp` moved from RAM to its own Btrfs subvolume on disk; a fork bomb in the Terminal no longer
  freezes the desktop.
- Every LuxOS app in the Store has a full description and real screenshots.
- Weather draws an animated sky that matches the weather and time of day.
- New windows open in free space or in a cascade, like on macOS; `Alt+`` ` switches between windows of
  the current app; a new emoji panel (`Super+.`).
- Fixes for printing and scanning, LuxAI administrator mode (no more system-wide passwordless root
  rule), LuxOS Care rollback and more. Full list: <https://luxos.lux-ai.cz/changes/>

Existing installations receive everything with `lux update`; they do not need the new ISO.

### Screenshots

Gallery: <https://luxos.lux-ai.cz/#gallery>

- Desktop: <https://luxos.lux-ai.cz/assets/shots/desktop-light.webp>
- Launchpad: <https://luxos.lux-ai.cz/assets/shots/launchpad-light.webp>
- Control Center: <https://luxos.lux-ai.cz/assets/shots/control-center-light.webp>
- LuxOS Store: <https://luxos.lux-ai.cz/assets/shots/store-light.webp>
- LuxAI: <https://luxos.lux-ai.cz/assets/shots/luxai-light.webp>

### Availability

- Download (ISO, 2.1 GB, x86_64, UEFI and BIOS): <https://luxos.lux-ai.cz/#download>
  (SHA256SUMS and a GPG signature are published next to the ISO)
- Requirements: 64-bit PC, at least 20 GB disk; installation takes about 10 minutes and needs an
  internet connection.
- Documentation: <https://luxos.lux-ai.cz/docs/>
- Source code: <https://github.com/luxopes/LuxOS-Arch> (kernel: <https://github.com/luxopes/luxos-kernel>)
- Anonymous usage statistics (opt-out "countme"): <https://luxos.lux-ai.cz/usage/>

### A note on maturity

LuxOS is a young, small project: the public repository started in October 2026 and LuxOS is still
labelled beta. It is a good fit for people who like to try new systems and report bugs, not yet for
machines where stability matters most.

### Contact

Antonín Tomeček – <info@lux-ai.cz> – <https://luxos.lux-ai.cz>
