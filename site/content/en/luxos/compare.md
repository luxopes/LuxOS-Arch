# LuxOS compared with other distributions

LuxOS is often compared with Ubuntu, Linux Mint, Zorin OS, elementary OS and the Arch family. This
page sums up the differences honestly – including where the others are the better choice. LuxOS is
**beta** and a young, small project; the other distributions have years of releases and large
communities.

## At a glance

| | LuxOS | Ubuntu | Linux Mint | Zorin OS | elementary OS | Arch Linux / EndeavourOS / Manjaro |
|---|---|---|---|---|---|---|
| Base | Arch Linux | Debian | Ubuntu LTS | Ubuntu LTS | Ubuntu LTS | Arch (Manjaro: own delayed repositories) |
| Release model | rolling (numbered ISO snapshots) | fixed releases, LTS every 2 years | fixed, follows Ubuntu LTS | fixed, follows Ubuntu LTS | fixed, follows Ubuntu LTS | rolling |
| Desktop | Xfce parts in a macOS-like layout (top bar, Plank Dock, Launchpad, Control Center) | GNOME | Cinnamon (also MATE, Xfce) | GNOME-based with Windows/macOS-like layouts | Pantheon | your choice |
| Package tools | `lux` (libalpm): Arch repos, Flathub, AUR built in a sandbox, `.lux` apps; LuxOS Store | apt, Snap | apt, Flatpak | apt, Flatpak, Snap | apt, Flatpak (AppCenter) | pacman (+ AUR helpers) |
| Updates | automatic in the background, Btrfs snapshot before each one, rollback from the boot menu | unattended security updates | Update Manager, Timeshift snapshots | Software Updater | AppCenter | manual |
| Kernel | `linux-luxos` (vanilla stable kernel.org) | Ubuntu kernel | Ubuntu kernel | Ubuntu kernel | Ubuntu kernel | Arch kernels / Manjaro kernels |
| Drivers | automatic detection at install and later (NVIDIA by generation, Wi-Fi, audio, cameras) | Additional Drivers | Driver Manager | Additional Drivers | AppCenter drivers | manual (EndeavourOS/Manjaro help with NVIDIA) |
| Security defaults | firewall on, Lux Guard for downloaded programs, read-only `/usr`, signed repos | AppArmor, firewall off by default | firewall available (off by default) | firewall available | AppArmor | up to you |
| AI assistant | optional LuxAI (account, cloud models) | – | – | – | – | – |
| Maturity and support | beta, one developer, GitHub issues | very mature, commercial support (Canonical) | very mature, big community | mature, paid Pro edition | mature | mature, huge wiki and community |

The details of other distributions change between releases; check their sites for the current state.

## Ubuntu, Linux Mint and Zorin OS

These are the safe, popular choices: long-term-support releases, huge communities and countless
guides. They are the better choice if you need stability above all, commercial support, or software
that is officially packaged only for Ubuntu.

LuxOS is different in that it follows Arch Linux: software is new soon after upstream releases,
updates are continuous (no big upgrade every two years) and are protected by snapshots. The desktop is
arranged like macOS out of the box. Zorin OS also offers a macOS-like layout, on an Ubuntu base.

## elementary OS

elementary OS is the closest in spirit: a calm, Mac-inspired design. It uses its own Pantheon desktop
and a curated AppCenter on an Ubuntu LTS base. LuxOS uses an Xfce base (light on resources), the full
Arch repositories plus Flathub and the AUR, and adds snapshot rollback, automatic drivers and an
optional AI assistant. elementary OS is more mature and polished as a whole.

## Arch Linux, EndeavourOS and Manjaro

- **Arch Linux** gives you a minimal base and you build everything yourself. LuxOS uses the same
  repositories but is a finished desktop with a graphical installer.
- **EndeavourOS** stays close to plain Arch with an installer and a few tools; you still use `pacman`
  and configure the desktop yourself.
- **Manjaro** holds Arch packages back in its own repositories and uses its own kernels.

LuxOS takes packages straight from Arch, replaces the `pacman` command with `lux` (same libalpm
underneath, own configuration in `/etc/lux/lux.conf`), builds AUR packages only after checking them
and installs them into a sandbox by default, and maintains the system automatically with
[LuxOS Care](care-updates.html). Arch support channels do not support LuxOS or other derivatives.

## Who should pick LuxOS?

- You want a Mac-like desktop on Linux without spending days on configuration.
- You like new software (rolling release) but want updates that can be undone.
- You are comfortable with a beta and willing to report bugs.

Pick an established distribution instead if the computer must not have surprises (work machines,
family computers), if you need long-term support or vendor certification, or if you rely on a large
community for help.

See also: [FAQ](faq.html), [Hardware support](hardware.html), [Installing LuxOS](installer.html).
