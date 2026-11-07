# Temporary files (/tmp)

Because swap is only zram, a RAM-backed `/tmp` (tmpfs) would always take real memory – forgotten
files there cannot be swapped out to disk and neither earlyoom nor the fork guard can free them.
On installed LuxOS systems `/tmp` is therefore on the disk (encrypted together with the system):

- Btrfs root in a subvolume (every LuxOS installation): own subvolume **`@tmp`** at the top level
  of the file system, mounted from `/etc/fstab` on `/tmp` with the root's options plus
  `nodev,nosuid`. Programs may still run from `/tmp` (installers, AppImages, Steam, pip builds), so
  there is no `noexec`. `@tmp` is not part of system snapshots or a rollback (only `@` is), backups
  never include `/tmp`.
- Other root file systems (ext4, xfs, f2fs, Btrfs without subvolumes): systemd's `tmp.mount` is
  masked (`/etc/systemd/system/tmp.mount` → `/dev/null`) and `/tmp` is a directory of the root.
- A separate `/tmp` from the manual partitioning (installer) or your own `/tmp` line in fstab /
  own `tmp.mount` in `/etc` is left alone. The live ISO keeps `/tmp` in RAM (tmpfs).
- Cleaning (`/usr/lib/tmpfiles.d/luxos-tmp.conf`: `D /tmp 1777 root root 10d`): `/tmp` is emptied
  at **every start**, while running files not touched for 10 days are removed. X11 directories
  (`/tmp/.X11-unix` …) are created again by systemd. `/var/tmp` is unchanged (30 days, kept over
  restarts). Secrets and sockets of LuxOS programs belong in `$XDG_RUNTIME_DIR` (RAM), not `/tmp`.

New installations get `@tmp` from the installer. Existing installations switch automatically:
`luxos-tweaks` (install script, or `luxos-tmp-setup.service` once at start when the package update
could not do it, e.g. when started from a snapshot) runs `/usr/lib/luxos/luxos-tmp-setup`, which
creates `@tmp` (on a privately mounted top level, the running `/tmp` is not touched), tries to mount
it with the final options and only then adds the fstab line. It takes effect at the **next start**.
Done = `/var/lib/luxos/tmp-on-disk`; after that nothing is changed again (removing the fstab line by
hand is respected). Do **not** mask `tmp.mount` together with a `/tmp` fstab line – the mask in
`/etc` would also switch off the fstab mount; the fstab line alone already replaces systemd's tmpfs.

## Check

```sh
findmnt /tmp                       # /dev/...[/@tmp] btrfs ... nosuid,nodev ... subvol=/@tmp
cat /var/lib/luxos/tmp-on-disk     # method=btrfs|mask|fstab|custom
journalctl -b -u luxos-tmp-setup   # message of the one-time switch at start
```

Programs that keep large temporary data should still delete it themselves; files in `/tmp` survive
until the next start (or 10 days).
