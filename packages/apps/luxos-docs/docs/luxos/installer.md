# Installing LuxOS

The installer is the package `luxos-installer`: a bash backend `luxos-install` (text UI with
`gum`, and unattended mode) and a graphical wizard `luxos-install-gui` (GTK) on top of it.

- Start in the live system: the **Install LuxOS** icon (desktop, Dock, welcome window), or
  `sudo luxos-install` in a terminal (text UI).
- The installation takes about 10 minutes and **needs internet**: current packages are downloaded;
  LuxOS packages come from the local repository on the ISO (`/opt/luxos-repo`).
- Log: `/var/log/luxos-install.log` (copied to the installed system).
- Shared files: `/usr/share/luxos/installer/` (`packages`, `install.conf.example`, `pacman.conf`,
  `templates/*.list`, `setup-chroot.sh`, `layout.sh`).

## Steps

Graphical wizard: Introduction (language) → Network (only when offline) → Keyboard → Time Zone →
Destination (disk) → Account → Maintenance → Software → LuxAI account → Summary → installation.

Text UI (`sudo luxos-install`): language, internet check, keyboard, time zone (auto-detected and
confirmed), disk, full name / user name / password / computer name, automatic login, maintenance
mode, software templates, LuxAI account, summary.

Languages offered: English (US/UK), Čeština, Slovenčina, Deutsch, Polski, Français, Español,
Italiano, Português (Brasil), Nederlands, Magyar, Svenska, Українська, or any other locale.
The installer UI switches to the chosen language.

## Disk modes (Destination)

| Mode | GUI name | `DISK_MODE` | Notes |
|---|---|---|---|
| Whole disk | Erase disk and install LuxOS | `erase` | everything on the disk is deleted; optional LUKS2 encryption |
| Free space | Install alongside other systems | `freespace` | largest free region (min. 20 GB), GPT + UEFI only, shares the EFI partition (needs ≥ 250 MB free on it); GUI and unattended only |
| Existing partition | Replace an existing partition | `partition` | formats only `ROOT_PART` (min. 20 GB, unmounted), other partitions are kept; UEFI only; swap = zram; optionally keep an existing partition as `/home` without formatting; optional encryption |
| Manual | Manual partitioning (advanced) | `layout` | editor for disks, partitions, LVM and LUKS2 |
| Pre-mounted | Advanced: use partitions already mounted at /mnt | `manual` / `DISK=manual` | for custom setups such as dual boot; mount root (and `/boot`) to `/mnt` first |

Minimum disk size is 20 GB.

### Default layout (erase)

- UEFI: ESP 1 GiB FAT32 mounted at `/boot` + the rest as Btrfs (`LuxOS`), boot loader **systemd-boot**.
- BIOS: 1 MiB `bios_grub` + 1 GiB ext4 `/boot` + Btrfs, boot loader **GRUB**.
- Btrfs subvolumes `@` (/), `@home`, `@log` (/var/log), `@cache` (/var/cache), mount options
  `noatime,compress=zstd:1`.
- Encryption: LUKS2 on the Btrfs partition (`cryptroot`); the password is asked at every start.
- Swap: zram (no swap partition).
- Kernel: `linux-zen`.

With a shared ESP mounted at `/efi`, the kernel is copied to `EFI/LuxOS/<id>` by
`/usr/local/sbin/luxos-esp-sync` (pacman hook `99-luxos-esp-sync.hook`) and systemd-boot is only
installed if none is present; a boot menu with a 3 s timeout is created when other systems exist.

### Manual partitioning

GUI: Destination › Manual partitioning. Create, delete and resize partitions (resize only ext4,
btrfs, NTFS), encrypt a partition or logical volume (LVM on LUKS and LUKS on LVM), LVM volume groups
across disks, mount points (`/`, `/home`, `/var`, `/tmp`, `/opt`, `/srv`, `/var/log`, custom),
file systems btrfs/ext4/xfs/f2fs (vfat for the ESP), swap (partition, LV or just zram), keep an
existing ESP, VG/LV or unlocked LUKS volume. Presets: **Encrypted LVM (/, /home, swap)** and
**Encrypted LVM with separate /var and /tmp**.

Checks: an ESP (vfat, ≥ 300 MB) at `/boot` or `/efi` on UEFI; on BIOS a `type=bios` partition and
an unencrypted `/boot` when `/` is encrypted; no duplicate mount points; sizes; mismatched
encryption of `/` and `/home`. Separate `/usr` or `/boot/efi` are not supported. The summary lists
everything that will be erased and must be confirmed.

At boot one password is enough: volumes under `/` are unlocked by the initramfs (`sd-encrypt` +
`lvm2`, `rd.luks.name`); other volumes use a key file in `/etc/cryptsetup-keys.d` on the encrypted
root. If `/` is not encrypted, encrypted swap gets a random key each boot and other volumes ask.

## Unattended installation

```bash
sudo luxos-install --config install.conf --yes
... | sudo luxos-install --config - --yes --progress   # config from stdin (passwords never hit the disk)
luxos-install --check-layout layout.conf             # validate a LAYOUT without changes (no root needed)
sudo luxos-install --scan                            # disks, partitions, LUKS, LVM as JSON (read-only)
sudo luxos-install --probe /dev/sdX                  # free space, ESP, partitions (KEY=value, read-only)
```

Template: `/usr/share/luxos/installer/install.conf.example`. Keys (bash variables):

| Key | Meaning / default |
|---|---|
| `LOCALE` | e.g. `cs_CZ.UTF-8` (default `en_US.UTF-8`) |
| `XKB_LAYOUT`, `XKB_VARIANT` | comma-separated, first is default, max 4 (e.g. `cz,us` and `qwerty,`) |
| `XKB_OPTIONS` | switching, e.g. `grp:shifts_toggle` (both Shift keys, the default); empty = only by clicking the flag in the top bar. Without it a single non-`us` layout gets `us` added (both Shift keys) |
| `TIMEZONE` | e.g. `Europe/Prague` (default `UTC`) |
| `DISK` | target disk, or `manual` |
| `DISK_MODE` | `erase` (default), `freespace`, `partition`, `layout`, `manual` |
| `BOOTLOADER` | `auto` (systemd-boot on UEFI / GRUB on BIOS) or `none` (kernel stays in /boot) |
| `ROOT_PART`, `HOME_PART` | for `DISK_MODE=partition` (`HOME_PART` is kept unformatted; ext4/btrfs/xfs/f2fs, btrfs `@home` subvolume supported) |
| `ENCRYPT`, `LUKS_PASS` | `1` = LUKS2 (requires `LUKS_PASS`) |
| `USERNAME`, `FULLNAME`, `PASSWORD` | required: `DISK`, `USERNAME`, `PASSWORD` |
| `HOSTNAME_SEL` | computer name (default `luxos`) |
| `AUTOLOGIN` | `1` = log in without a password |
| `CARE_MODE` | `carefree` (default) or `classic`, see [care-updates.md](care-updates.md) |
| `TEMPLATES` | comma-separated: `everyday`, `programming`, `creative`, `gaming`, `security` |
| `UI_LANG` | language of installer output |
| `LUXAI_EMAIL`, `LUXAI_PASSWORD` or `LUXAI_ACCOUNT` | optional LuxAI sign-in (account JSON as in `~/.config/luxai/account.json`) |
| `LAYOUT` / `LAYOUT_FILE` | manual layout for `DISK_MODE=layout` |
| `LUKS_PASS_<ID>` | per-volume LUKS passwords in a layout |

### LAYOUT syntax

One line per item, `kind key=value ...`:

```
disk   dev=/dev/vda table=new|keep
part   id=ID disk=/dev/vda size=1G|rest [type=esp|bios|linux|swap|lvm|luks|boot] [name=TEXT]
use    id=ID dev=/dev/sda2 [resize=100G]
delete dev=/dev/sda3
luks   id=ID on=ID name=MAPPER [keep=1]
vg     id=ID name=VG pvs=ID[,ID] [keep=1]
lv     id=ID vg=ID name=LV size=40G|rest [keep=1]
fs     on=ID mount=/home type=btrfs|ext4|xfs|f2fs|vfat [format=1|0] [label=X] [subvol=@home]
swap   on=ID [format=1|0]
```

Sizes K/M/G/T (binary), one `rest` per disk/group. `/` is always formatted. Example (encrypted LVM, UEFI):

```
disk dev=/dev/vda table=new
part id=esp  disk=/dev/vda size=1G type=esp
part id=crypt disk=/dev/vda size=rest
luks id=cryptlvm on=crypt name=cryptlvm
vg   id=vg name=luxos pvs=cryptlvm
lv   id=root vg=vg name=root size=40G
lv   id=swap vg=vg name=swap size=4G
lv   id=home vg=vg name=home size=rest
fs   on=esp  mount=/boot type=vfat
fs   on=root mount=/ type=btrfs
fs   on=home mount=/home type=btrfs
swap on=swap
```

## Keyboard layouts

The layout for the chosen language's country is listed first; up to 3 more layouts can be added
(US is pre-selected for typing passwords). With more than one layout, pressing both Shift keys
together switches by default. Layouts apply to the console, X11, the login screen and all users. They can be changed
later in the Keyboard Layouts app (see [keyboard.md](keyboard.md)).

## Maintenance mode

"How should LuxOS be maintained?": **Carefree (recommended)** — automatic background updates
(not on metered networks, with Data Saver or on low battery), a kept previous kernel and self-repair;
**Classic (for IT professionals)** — no automatic updates or repairs, only notifications.

## Software templates

Optional extra apps on top of the base system ("Choose your software"):

| ID | Name | Apps | Approx. extra download |
|---|---|---|---|
| `everyday` | Everyday | LibreOffice (with language pack), Thunderbird, Galculator, hunspell dictionary | 320 MB |
| `programming` | Programming | Lux Code, Code - OSS, Git, git-lfs, GitHub CLI, base-devel, OpenSSH, Python + pip, Node.js + npm, jq, Meld | 370 MB |
| `creative` | Video & Photo | Kdenlive, GIMP, Inkscape, darktable, Audacity, OBS Studio | 450 MB |
| `gaming` | Gaming | Steam, GameMode, MangoHud (+ 32-bit drivers matching the GPU; enables `[multilib]`) | 650 MB |
| `security` | Security & Networking | Nmap, Wireshark (user added to group `wireshark`), tcpdump, mtr, traceroute, bind, whois, netcat, iperf3, Gufw, Lynis, arch-audit, KeePassXC | 170 MB |

If some template apps fail to install, the installation continues with a warning.

## Base system

Always installed (`/usr/share/luxos/installer/packages`): `base`, `lux-engine`, `linux-zen`,
`linux-firmware`, `sof-firmware`, `alsa-firmware`, CPU microcode, `btrfs-progs`, `dosfstools`,
`e2fsprogs`, `exfatprogs`, `ntfs-3g`, `cryptsetup`, `plymouth`, `sudo`, `nano`, man pages,
`networkmanager`, `pipewire-jack`, `noto-fonts`, `luxos-greeter`, `luxos-printing`,
`luxos-desktop`, `luxdrop`, `luxai`, `luxos-safe`, `luxos-sandbox`, `luxos-care`, plus drivers from
`luxos-hwdetect` (see [drivers.md](drivers.md)) and `efibootmgr` (UEFI) or `grub` (BIOS).
Downloads are retried up to 3 times (fewer parallel downloads on retry); mirrors are ranked first.

## LuxAI account

Optional step "Sign in to your LuxAI account now?": **Sign in with a password**,
**Sign in with a code from e-mail**, **Create a new account** (name, e-mail, password 12–128
characters, accept terms, 6-digit e-mail code) or **Skip**. The session is saved for the new user in
`~/.config/luxai/account.json` and used by LuxAI, Lux Code and LSL IDE.
See [luxai-account.md](luxai-account.md).

## After installation

"LuxOS is installed — Remove the installation media and restart your computer."
On first login the LuxOS Tour starts. Updates afterwards: `lux update` or Software Update.

## Installer tests (developers)

`packages/luxos-installer/tests/` in the LuxOS source: `test-layout.sh` (no root),
`gui-smoke.py` (GUI), `vm-layout-test.sh` (as root in a VM).
