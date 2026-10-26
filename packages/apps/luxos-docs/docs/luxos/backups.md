# Backups – automatic backups to an external or network disk

**Backups** (Czech *Zálohy*; package `luxos-backup`, window `luxos-backup-gui`, command
`luxos-backup`) keeps automatic, incremental backups of the user's home folder on an external disk
(USB) or a network disk (SFTP server, SMB shared folder). Each backup is a complete, browsable copy
of the home folder at that time; unchanged files take no extra space. Restoring works per file or
folder, or for the whole home folder on a new installation. Unlike the hourly `/home` snapshots of
[Lux Guard](guard.md), which live on the same disk, these backups survive a broken or stolen computer.

## Setting up a backup disk

- Plug in a USB disk: a notification asks **Use this disk for backups?** (button **Use for
  Backups** opens the window). Disks you decline are not offered again.
- Or open **Backups** › **Add Disk…** and choose an external disk or type a network address
  (`luxos-backup-gui --add DEVICE` opens this dialog directly, `--restore` the restore view).
- A disk with btrfs, ext4, xfs or f2fs that is mounted is used as it is (folder `LuxOS-Backups`).
  FAT, exFAT and NTFS cannot hold incremental backups – the disk is **erased and prepared**
  (btrfs with zstd compression) after a confirmation; administrator password via polkit.
- **Encrypt backups** (when preparing a disk): LUKS2 with your password. The password is stored in
  the keyring (`secret-tool`, service `luxos-backup`) so backups run unattended; without it nobody can
  read the disk.
- Network disks: `sftp://user@server/folder` (the server needs `rsync`; host key accepted on first
  use, password from the keyring through `SSH_ASKPASS`) or `smb://user@server/share` (gvfs; the
  backups go into one image file `LuxOS-Backups/<computer>-<user>.img` on the share, formatted as
  btrfs, optionally encrypted).

Command line:

```
luxos-backup disk candidates              # external disks
luxos-backup disk add /run/media/anna/USB # use a mounted disk as it is
luxos-backup disk prepare /dev/sdb1 --encrypt   # erase and prepare
luxos-backup disk add sftp://anna@nas.local/volume1/backup
luxos-backup disk remove ID               # backups already on the disk are kept
```

## When backups run

- User timer `luxos-backup.timer` (systemd `--user`, enabled for everyone) runs
  `luxos-backup service` every hour; nothing happens until a disk is added. Lowest CPU and disk
  priority (`Nice=19`, `IOSchedulingClass=idle`).
- Automatic backups only **while the computer is charging** (desktops always); paused on battery and
  in Battery Saver; backups to a network disk also pause on a **metered connection** (Data Saver).
  **Back Up Now** / `luxos-backup now` ignores these conditions.
- A known disk plugged in starts a backup right away if the last one is older than an hour (udev rule
  `70-luxos-backup.rules` starts the user service `luxos-backup-plug@DEVICE.service`; no process
  waits in the background).
- Disks are mounted and unlocked through udisks in the user's session and unmounted again when the
  backup is done (if Backups mounted them).

## How backups are stored

```
<disk>/LuxOS-Backups/<computer>-<user>/
    backup.json
    2026-10-26-140000/        one backup (UTC time)
        home/                 the home folder
        system/etc/           optional: readable files from /etc
        system/packages.txt   optional: explicitly installed packages
        info.json
```

- **btrfs disk:** `rsync --inplace` into the working subvolume `.current`, then a read-only btrfs
  snapshot per backup – even big files that change a little (virtual machine images) share their
  unchanged blocks. Runs without root.
- **other disks and SFTP:** each backup is a folder; unchanged files are hard links to the previous
  backup (`rsync --link-dest`). An interrupted backup stays as `NAME.partial` and is completed next time.
- Not `btrfs send/receive`: it needs root on both sides, cannot leave out caches, and the `@home`
  subvolume contains every user's home folder.
- Other mounts inside the home folder (sshfs, USB) are never followed.

**Thinning:** all backups from the last 24 hours, one per day for the last month, one per week before
that. When the disk is full, the oldest backups are deleted (never the newest one) and a
notification says so. If the disk still has no space, a persistent notification reports the failure.
Without a backup for 7 days a notification reminds you to connect the disk.

## What is backed up

The whole home folder except caches: `~/.cache`, the trash, thumbnails, Flatpak caches, container
storage (`~/.local/share/containers/storage`), build caches and `lost+found`. Options in the window
(or `luxos-backup option NAME on|off`):

| Option | Default | Meaning |
|---|---|---|
| Back up automatically (`auto`) | on | hourly backups |
| Back up system settings (`system`) | off | readable files from `/etc` (no passwords or keys) and the package list |
| Back up the Downloads folder (`downloads`) | on | `~/Downloads` / the XDG download folder |
| Back up virtual machines (`vms`) | off | `*.qcow2`, `*.vdi`, `*.vmdk`, `~/VirtualBox VMs` … |

Own exclusions: **Exclude Folder…** or `luxos-backup exclude add ~/Videos` (also patterns like
`*.iso`); `luxos-backup exclude list` prints all rules. Settings are in
`~/.config/luxos/backup/config.json`, the state in `~/.local/state/luxos/backup/status.json`.

## Restoring files

In the window: **Restore Files…** – a timeline of backups on the left (grouped by day), the folder
contents of the chosen backup on the right (double-click opens a folder; a file opens read-only
straight from the backup). **Restore** puts the selection back where it was, **Restore To…** into a
chosen folder.

Nothing is ever overwritten silently: if the file or folder still exists, the restored copy gets a
new name, e.g. `report (restored 2026-10-26 14.00).txt`.

```
luxos-backup list
luxos-backup files --from "2026-10-20" Documents
luxos-backup restore ~/Documents/report.txt
luxos-backup restore --from "2026-10-20 18:00" --to ~/Desktop ~/Pictures/Holiday
```

`--from` takes a backup name, `latest` (default), a date (`YYYY-MM-DD` = the last backup of that
day) or `YYYY-MM-DD HH:MM` (the last backup at or before that time).

## Restore everything on a new installation

**Restore Everything…** in the window, or:

```
luxos-backup restore --all --source /run/media/anna/Backup
luxos-backup restore --all --source /run/media/anna/Backup --replace
```

- `--source` reads the backups straight from a folder (disk root, `LuxOS-Backups` or the computer
  folder) without any configuration – usable on a fresh system, from the installer or from
  LuxOS Recovery (as root it sets the owner to the owner of `--target`). `--machine
  COMPUTER-USER` chooses when several computers back up to one disk.
- Without `--replace` existing files are kept (useful when merging). With `--replace` (what the
  window does) the backup wins and the replaced files are moved to `~/.luxos-backup-replaced-TIME`.
- `system/packages.txt` lists the apps of the old system: `lux install $(cat …/packages.txt)`.
- Log out and back in afterwards so that restored settings are loaded.

## For AI assistants

- State: `luxos-backup status` (or `--json`); log: `journalctl --user -u luxos-backup.service`.
- "Backup failed" notifications contain the reason; common ones: disk not connected (not an error,
  just waiting), disk full, server unreachable, password missing in the keyring (remove and add the
  disk again).
- Never delete folders inside `LuxOS-Backups` by hand to free space – remove whole backups only, or let
  thinning do it. Never run `restore --all --replace` without the user asking for it.
