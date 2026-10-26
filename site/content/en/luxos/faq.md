# LuxOS FAQ – frequently asked questions

## What is LuxOS?

LuxOS is a fast, lightweight Linux distribution based on Arch Linux with a macOS-like desktop (Xfce
underneath). It has its own package manager `lux`, its own kernel build `linux-luxos`, automatic
drivers, the AI assistant LuxAI, the terminal coding agent Lux Code and its own programming language,
LSL. It is a rolling release, currently in beta (version 0.9.x, codename "Polaris").

## Is LuxOS free? What licence does it use?

You can download the ISO for free from the LuxOS website. The LuxOS code (the `luxos-*` packages,
`lux`, `luxdrop`, scripts and the installer) is licensed GPL-3.0-or-later; bundled third-party
packages keep their own licences. LuxAI uses a LuxAI account, which has a monthly usage limit.

## What hardware does LuxOS need?

A 64-bit PC (x86_64) with UEFI or BIOS and at least a 20 GB disk. Installation takes about 10 minutes
and needs an internet connection. Drivers for Intel, AMD and NVIDIA graphics, Wi-Fi, audio, cameras
and virtual machines are detected automatically. See [Hardware support](hardware.html).

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

## Where is pacman? How do I install software?

There is no `pacman` command in LuxOS; the package manager is `lux`. If you type a pacman command, the
shell shows the matching `lux` command (`pacman -Syu` becomes `lux update`). `lux install` searches
the LuxOS and Arch repositories, `.lux` apps, Flathub and the community repository (AUR); AUR
packages are reviewed and built in the Sandbox. You can also use the graphical
[LuxOS Store](store.html). See [Package management with lux](package-management.html).

## What is LuxAI?

LuxAI is the AI assistant of LuxOS, a desktop app with a Chat mode and an Agent mode that can work
with your computer, search the web and read the offline LuxOS manual. It asks before every risky
action. See [LuxAI](luxai.html).

## Do I need an account for LuxAI?

Yes. LuxAI, Lux Code and LSL IDE share one LuxAI account, which you can create in the installer or in
the **LuxAI Account** app. See [LuxAI account](luxai-account.html).

## What is Lux Code?

Lux Code is an AI coding agent for the terminal, written in LSL. It edits files, runs commands and
tests, and uses your LuxAI account. See [Lux Code](lux-code.html).

## What is LSL?

LSL (Lux Simple Lang) is the programming language of LuxOS, used for system apps and available to
everyone: scripts, command-line tools and native programs. See the [LSL overview](../lsl/overview.html).

## How does LuxOS protect me from malware?

**Lux Guard** checks programs from downloads, attachments and USB drives when they start and runs
dangerous ones only in the Sandbox. The [Sandbox](sandbox.html) is an isolated system for untrusted
apps, and [Safe](safe.html) is an encrypted folder with its own password. Packages are signed.
See [Lux Guard](guard.html).

## How do I verify the downloaded ISO?

Run `sha256sum -c SHA256SUMS`, import the LuxOS key with `gpg --import luxos.gpg` and check the
signature with `gpg --verify luxos-VERSION-x86_64.iso.sig luxos-VERSION-x86_64.iso`. The key
fingerprint is on the home page.

## Does it work with NVIDIA graphics?

Yes. Turing and newer cards use the open NVIDIA driver, Maxwell, Pascal and Volta use the 580xx
branch, older cards use nouveau; hybrid laptops get `prime-run`. See
[Drivers and hardware detection](drivers.html).

## How do I send files to my phone or another computer?

Use [LuxDrop](luxdrop.html): encrypted file sharing between LuxOS computers and apps compatible with
LocalSend (phones, tablets, Windows, Linux).

## Which languages does LuxOS support?

The installer and the LuxOS apps are available in 13 languages, including English, Czech, Slovak,
German, Polish, French, Spanish, Italian, Portuguese, Dutch, Hungarian, Swedish and Ukrainian.

## What if something breaks?

See [Troubleshooting](troubleshooting.html). LuxOS Care keeps the previous kernel in the boot menu,
`lux fix` repairs a locked package database and signing keys, and `lux doctor` checks the system.
Bugs and ideas can be sent from the Feedback app or by asking LuxAI.
