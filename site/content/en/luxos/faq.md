# LuxOS FAQ – frequently asked questions

## What is LuxOS?

LuxOS is a fast, lightweight Linux distribution based on Arch Linux with a macOS-like desktop (Xfce
underneath). It has its own package manager `lux`, its own kernel build `linux-luxos`, automatic
drivers, updates that can be rolled back, the AI assistant LuxAI, the terminal coding agent Lux Code
and its own programming language, LSL. It is a rolling release; the current version is 1.0.1
"Sirius", still in beta.

## Is LuxOS free? What licence does it use?

Yes, the ISO is a free download from the LuxOS website and there is no paid edition. The LuxOS code
(the `luxos-*` packages, `lux`, `luxdrop`, scripts and the installer) is licensed GPL-3.0-or-later;
bundled third-party packages keep their own licences. The optional LuxAI assistant uses a LuxAI
account, which has a monthly usage limit.

## Who makes LuxOS?

LuxOS is developed by Antonín Tomeček in the Czech Republic. The source code is on
[GitHub](https://github.com/luxopes/LuxOS-Arch) and the contact address is info@lux-ai.cz. It is a
small, young project: the public repository started in October 2026.

## Is LuxOS stable? Is it safe to use?

LuxOS is **beta**: expect bugs and back up your data before installing. Every update takes a system
snapshot first, so a bad update can be undone, and the previous kernel stays in the boot menu. Packages
from the LuxOS repositories are signed, the firewall is on by default and Lux Guard checks programs
from the internet. For computers where stability matters most, an established distribution is still
the safer choice – see [LuxOS compared](compare.html).

## How is LuxOS different from Ubuntu, Linux Mint or Zorin OS?

Those are based on Ubuntu (Debian packages, fixed releases). LuxOS is based on Arch Linux and is a
rolling release with the newest software, its own package manager `lux` (Arch repositories, Flathub
and sandboxed AUR builds), a macOS-style desktop and automatic snapshots before updates. Ubuntu, Mint
and Zorin are far more mature, with large communities and long-term-support releases. Details in
[LuxOS compared](compare.html).

## How is LuxOS different from elementary OS?

Both aim for a clean, Mac-inspired desktop. elementary OS is Ubuntu-based with its own Pantheon desktop
and AppCenter; LuxOS is Arch-based, builds its desktop from Xfce parts (top bar, Plank Dock,
Launchpad, Control Center) and adds `lux`, snapshot rollback, automatic drivers and an optional AI
assistant. See [LuxOS compared](compare.html).

## How is LuxOS different from Arch Linux, Manjaro or EndeavourOS?

Arch is a do-it-yourself base; EndeavourOS is close to plain Arch with a friendly installer; Manjaro
holds Arch packages back in its own repositories. LuxOS uses the Arch repositories directly but comes
fully set up: a graphical installer, a finished macOS-like desktop, `lux` instead of the `pacman`
command, automatic updates with Btrfs snapshots, driver detection and its own apps. Arch support
channels do not support LuxOS – please report LuxOS problems to LuxOS. See
[LuxOS compared](compare.html).

## Does LuxOS run Windows apps?

Not natively – LuxOS is Linux. Many Windows programs run with Wine; the easiest way is Bottles from
Flathub (search for it in the LuxOS Store). Compatibility depends on the program. Windows `.exe` files
downloaded from the internet are checked by Lux Guard when started.

## Can I play games on LuxOS? Does Steam work?

Yes. Choose the **Gaming** app set in the installer (Steam, GameMode, MangoHud and the 32-bit drivers
for your graphics card; it enables the `multilib` repository), or install Steam later from Flathub (it appears
in the LuxOS Store search results). On laptops with hybrid graphics, the **Performance** power mode runs games on the
discrete GPU. Steam's Proton runs many Windows games. See
[Power, performance and memory](power-and-performance.html).

## What hardware does LuxOS need?

A 64-bit PC (x86_64) with UEFI or BIOS and at least a 20 GB disk. Installation takes about 10 minutes
and needs an internet connection. There is no official RAM minimum yet; the desktop is light (Xfce,
zram swap) and has been tested in virtual machines with 3 GB of RAM. Drivers for Intel, AMD
and NVIDIA graphics, Wi-Fi, audio, cameras and virtual machines are detected automatically. See
[Hardware support](hardware.html).

## How do I install LuxOS?

Download the ISO from the home page, verify it, write it to a USB drive (4 GB or more) with Fedora
Media Writer, balenaEtcher or `dd`, boot from it and try LuxOS without installing. Then start
**Install LuxOS**. The installer offers a whole disk, free space next to Windows, an existing
partition, manual partitioning with LVM and encryption (LUKS2). See [Installing LuxOS](installer.html).

## Can I install LuxOS next to Windows (dual boot)?

Yes. The *Install alongside other systems* mode uses the largest free region of the disk (at least
20 GB) on a GPT disk with UEFI and shares the existing EFI partition. See
[Installing LuxOS](installer.html).

## How do I update LuxOS?

LuxOS is a rolling release. Updates are installed automatically in the background by
[LuxOS Care](care-updates.html) or manually with `lux update`. Older installations do not need a new
ISO.

## Can I undo an update?

Yes. Before every update LuxOS Care takes a read-only Btrfs snapshot of the system (the last 5 are
kept). Each snapshot has an entry in the boot menu (hold Space while the computer starts), and
`lux rollback` makes a snapshot the running system again; the rollback itself can be undone the same
way. `/home` is not rolled back. See [LuxOS Care](care-updates.html).

## Where is pacman? How do I install software?

There is no `pacman` command in LuxOS; the package manager is `lux`. If you type a pacman command, the
shell shows the matching `lux` command (`pacman -Syu` becomes `lux update`). `lux install` searches
the LuxOS and Arch repositories, `.lux` apps, Flathub and the community repository (AUR); AUR
packages are checked and built in the Sandbox. You can also use the graphical
[LuxOS Store](store.html). See [Package management with lux](package-management.html).

## What is LuxAI? Do I have to use it?

LuxAI is the optional AI assistant of LuxOS, a desktop app with a Chat mode and an Agent mode that can
work with your computer, search the web and read the offline LuxOS manual. It asks before every risky
action. LuxOS works fully without it. Answers are computed by third-party language model providers
listed in the [privacy policy](https://luxos.lux-ai.cz/privacy/). See [LuxAI](luxai.html).

## Do I need an account for LuxAI?

Yes. LuxAI, Lux Code and LSL IDE share one LuxAI account, which you can create in the installer or in
the **LuxAI Account** app. The account has monthly usage limits. See
[LuxAI account](luxai-account.html).

## What is Lux Code?

Lux Code is an AI coding agent for the terminal, written in LSL. It edits files, runs commands and
tests, and uses your LuxAI account. See [Lux Code](lux-code.html).

## What is LSL?

LSL (Lux Simple Lang) is a small compiled programming language by the LuxOS author. Several LuxOS
system tools are written in it, and it is available to everyone for scripts, command-line tools and
native programs. See the [LSL overview](../lsl/overview.html).

## How does LuxOS protect me from malware?

**Lux Guard** checks programs from downloads, attachments and USB drives when they start and runs
dangerous ones only in the Sandbox; it also keeps hourly snapshots of `/home`, so deleted or encrypted
files can be restored. The [Sandbox](sandbox.html) is an isolated system for untrusted apps,
[Safe](safe.html) is an encrypted folder with its own password, and the [firewall](firewall.html)
blocks unexpected incoming connections. Packages are signed. See [Lux Guard](guard.html).

## How do I verify the downloaded ISO?

Run `sha256sum -c SHA256SUMS`, import the LuxOS key with `gpg --import luxos.gpg` and check the
signature with `gpg --verify luxos-VERSION-x86_64.iso.sig luxos-VERSION-x86_64.iso`. The key
fingerprint is on the home page.

## Does it work with NVIDIA graphics?

Yes. Turing and newer cards use the open NVIDIA driver, Maxwell, Pascal and Volta use the 580xx
branch, older cards use nouveau; hybrid laptops get `prime-run` and the Performance mode. See
[Drivers and hardware detection](drivers.html).

## How do I send files to my phone or another computer?

Use [LuxDrop](luxdrop.html): encrypted file sharing between LuxOS computers and apps compatible with
LocalSend (phones, tablets, Windows, Linux).

## Which languages does LuxOS support?

The installer and the LuxOS apps are available in 13 languages, including English, Czech, Slovak,
German, Polish, French, Spanish, Italian, Portuguese, Dutch, Hungarian, Swedish and Ukrainian.

## What if something breaks?

See [Troubleshooting](troubleshooting.html). Roll back to the snapshot before the last update, start
the previous kernel from the boot menu, run `lux fix` to repair a locked package database and signing
keys, or `lux doctor` to check the system.

## Where do I report bugs or ask questions?

Send a report from the **Feedback** app (or ask LuxAI to send one), open an issue on
[GitHub](https://github.com/luxopes/LuxOS-Arch/issues), or write to info@lux-ai.cz.
