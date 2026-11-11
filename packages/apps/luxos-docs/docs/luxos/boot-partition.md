# Boot partition (EFI) space

The boot loader reads the kernel and the initramfs from the **EFI system partition** (FAT32, mounted at
`/boot` on a whole-disk install; with a disk shared with Windows the LuxOS files are in
`EFI/LuxOS/<id>` on the shared ESP; with GRUB the separate `/boot` partition). The partition is small
– new installs create **1 GiB**, a Windows ESP often has only 100–300 MB – and it holds several copies
of the kernel. A full partition must never leave a half-written kernel, initramfs or boot loader
behind, so LuxOS guards it.

## What is on it

| Item | Size (typical) | Managed by |
|---|---|---|
| main kernel `vmlinuz-linux-luxos` + `initramfs-linux-luxos.img` | ~17 + ~60 MB | mkinitcpio |
| previous kernel `vmlinuz-linux-luxos-prev` + `initramfs-linux-luxos-prev.img` | ~77 MB | LuxOS Care |
| snapshot kernel sets `luxos-snapshots/<version>-<hash>/` | ~77 MB each | LuxOS Care |
| `EFI/LuxOS` (shim, MokManager, signed systemd-boot), `EFI/BOOT` fallback | ~3 MB | luxos-secureboot |
| `amd-ucode.img`, `intel-ucode.img` (microcode packages) | up to 16 MB | packages |

The initramfs is built for the computer it runs on (mkinitcpio `autodetect`). The initramfs hook
**`luxos-slim`** (`/usr/lib/initcpio/install/luxos-slim`, added right after `autodetect` by
`/etc/mkinitcpio.conf.d/zz-luxos-slim.conf`) leaves out modules that are blacklisted in
`modprobe.d` (or with `module_blacklist=` / `modprobe.blacklist=`) and not loaded. The main case is
**nouveau next to the NVIDIA driver**: the `kms` hook would add it together with the firmware of every
NVIDIA GPU generation (~110 MB, already compressed) although it is never loaded – a laptop with AMD +
NVIDIA graphics had a 172 MB initramfs, now 59 MB. The Plymouth theme uses the single fonts Inter
Variable and Noto Sans Mono instead of the whole `Inter.ttc` collection (another 6 MB). Images
without `autodetect` and modules listed in `MODULES=()` are not changed.

## How the space is kept

- **Snapshot kernel sets** (see [care-updates.md](care-updates.md#system-snapshots-and-rollback)):
  snapshots with the same kernel and initramfs share one set. The same kernel with different initramfs
  images (a systemd, firmware or configuration update in between) is kept in **at most 2 sets** – the
  newest and the oldest; snapshots of the merged ones start the newest set (same kernel, same
  modules), so no snapshot loses its boot entry.
- **Before every package transaction** (hook `05-luxos-snapshot`) at least **100 MB plus room for one
  more kernel set** stays free – the room mkinitcpio needs to write a new initramfs next to the old one
  and the previous kernel. If there is less, the kernel sets of the **oldest snapshots** are removed
  first. Never removed: the set of the newest snapshot, the set of the snapshot the system runs from,
  and the main and previous kernels (they are not sets). A snapshot without a set stays (it can still be
  restored with `lux rollback` when its kernel version is the current one, or from LuxOS Recovery), it
  only has no boot menu entry.
- **mkinitcpio on a full partition**: with less free space than 1.25 × the old image mkinitcpio writes
  straight into the old image, and an error ("No space left on device") would leave a truncated
  initramfs – the computer would not start. `luxos-slim` first lets LuxOS Care free space
  (`luxos-care esp-clean --need N`); if that is not enough, the build stops with
  `Not enough space in /boot for a new initramfs … The current image was kept.` before anything changes.
- **After every transaction** (hook `96-luxos-care-esp-check`, `luxos-care esp-check`) leftovers of
  interrupted writes are removed (`initramfs-linux-luxos*.img.tmp`, `*-prev*.new`, `*.luxos-new`,
  `luxos-snapshots/*.new` – only these exact LuxOS names) and the initramfs images are checked to be
  fully readable (`lsinitcpio`). A truncated image is rebuilt after freeing space; when that fails the
  hook ends with an error ("The boot image is damaged … Do not restart the computer yet").
- **Copies to the partition** (previous kernel, snapshot kernel sets, rollback, `luxos-esp-sync` on a
  shared ESP, `luxos-secureboot`) write a temporary file, sync it, check it and only then rename it; on
  an error the old file stays and the temporary one is removed. `luxos-esp-sync` copies the kernel and
  the initramfs as a pair (never a new kernel with the old initramfs).

## Secure Boot loader files

`luxos-secureboot sync` checks the free space for the whole set of files first ("Not enough space on
the EFI partition: N MB needed, M MB free. Nothing was changed."), compares every copy with the
package and keeps the previous files on any error (exit code 1). The UEFI boot entry "LuxOS" (shim)
is only put first in the boot order or used for BootNext when `EFI/LuxOS/shimx64.efi` and
`grubx64.efi` are non-empty EFI files; a damaged shim entry is moved to the end of the boot order until
the files are repaired. Empty or partial copies of its own files (`EFI/LuxOS/*`,
`EFI/BOOT/{BOOTX64,mmx64,fbx64,grubx64}.efi`) are recognized and replaced; foreign boot loaders are
never touched. See [secure-boot.md](secure-boot.md).

## Check after boot

`luxos-care-boot.service` (after every start) and the periodic check (`luxos-care check`) first clean
the safe items (leftovers, duplicate kernel sets) and then report, as a normal LuxOS Care
notification:

| Problem | Repair (carefree mode does it itself) |
|---|---|
| The boot partition is almost full (< 50 MB free) | `clean_esp`: remove older snapshot kernel sets |
| The boot image of the kernel is damaged | `clean_esp`, then `rebuild_initramfs` |
| Boot loader files on the EFI partition are damaged | `clean_esp`, then `repair_boot_loader` (`luxos-secureboot sync`) |

## Commands

```bash
sudo luxos-care esp-clean          # free space: leftovers, merged and older snapshot kernel sets
sudo luxos-care esp-check          # leftovers + is the initramfs readable? (rebuilds a broken one)
sudo luxos-secureboot status       # loader=broken and loader_damaged=... when files are damaged
df -h /boot                        # free space
lsinitcpio -a /boot/initramfs-linux-luxos.img   # size and content of the initramfs
```

The installer warns when a kept or new EFI partition is smaller than 1 GB ("fewer system snapshots can
be started from the boot menu"); LuxOS still works, only fewer snapshot kernel sets fit.
