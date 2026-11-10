# Secure Boot

LuxOS starts with **Secure Boot turned on**, on ordinary Windows computers, without changing any
firmware setting. The only extra step is a one-time confirmation of the LuxOS key on the first start
(about ten key presses, no typing). This page explains the first start, how to check the state and
what to do when something goes wrong. Never turn Secure Boot off to install LuxOS.

## How it works

Computers sold with Windows trust only boot loaders signed by Microsoft. LuxOS starts through
**shim**, a small loader signed by Microsoft (the same file Fedora uses, signed with both the
Microsoft UEFI CA 2011 and the 2023 certificate, so it works on older and new computers). shim then
starts the LuxOS boot menu (systemd-boot) and the kernel, both signed with the **LuxOS key**.

The firmware does not know the LuxOS key yet, so it has to be added once to the list of keys the
computer owner trusts (**MOK**, Machine Owner Key). This is done in **MokManager**, a blue screen that
shim shows by itself. The key stays in the computer: reinstalling LuxOS, updates and new kernels need
nothing more. Because Secure Boot stays on, Windows next to LuxOS keeps working as before and
BitLocker does not ask for its recovery key (turning Secure Boot off would make it ask).

| Part | File on the EFI partition | Signed by |
|---|---|---|
| shim | `EFI/LuxOS/shimx64.efi`, fallback `EFI/BOOT/BOOTX64.EFI` | Microsoft |
| MokManager | `EFI/LuxOS/mmx64.efi` | Fedora (trusted by shim) |
| boot menu (systemd-boot) | `EFI/LuxOS/grubx64.efi` | LuxOS |
| kernel | `vmlinuz-linux-luxos` | LuxOS |
| LuxOS certificate | `EFI/LuxOS/luxos-secureboot.cer`, on the USB stick `LUXOS_ENROLL_THIS_KEY.cer` | – |

## First start from the USB stick

1. Start the computer from the LuxOS USB stick (boot menu key, often F12, F11, F8 or Esc).
2. A blue screen says **Verification failed: (0x1A) Security Violation**. This is expected: press
   **Enter** (OK).
3. "Press any key to perform MOK management" counts down from 10 seconds: press **Space** (any
   key). If the time runs out, the blue screen from step 2 simply comes back.
4. MokManager: **Perform MOK management**. Choose **Enroll key from disk** (one down arrow) and press
   Enter.
5. Choose the disk (the LuxOS USB stick, labelled `ARCHISO_EFI`).
6. The file **LUXOS_ENROLL_THIS_KEY.cer** is at the top: press Enter.
7. Choose **Continue**, then **Yes** to "Enroll the key(s)?".
8. Choose **Reboot**. The computer starts again from the USB stick, the LuxOS menu appears and the
   live system starts with Secure Boot on.

The installed system then starts directly, because the key is already in the computer. Screenshots of
every step are on the website: [Secure Boot: first start](https://luxos.lux-ai.cz/docs/luxos/secure-boot-first-start.html).

Some computers with the "Secured-core" label (for example some Lenovo, Microsoft Surface, Dell and HP
models) ship with **Microsoft 3rd-party UEFI CA** turned off. Then the firmware refuses the USB stick
before shim starts ("Secure Boot violation", "Image failed to verify"). In the firmware settings, on
the Security or Secure Boot page, turn on **Allow Microsoft 3rd Party UEFI CA** (Lenovo: "Allow
Microsoft 3rd Party UEFI CA", Surface: "Microsoft & 3rd party CA"). Secure Boot stays on.

## Computers that already run LuxOS

LuxOS 1.0.1 and older started without shim. An update installs `luxos-secureboot` automatically:
shim and the signed boot menu are added to the EFI partition, a new boot entry "LuxOS" is put first
and the old entry stays as a backup until LuxOS has started once through shim. Nothing changes for
computers with Secure Boot off.

To turn Secure Boot on afterwards:

```
sudo luxos-secureboot enroll
```

It shows a one-time password of eight digits (only digits, so the keyboard layout does not
matter). Restart: "Press any key to perform MOK management" appears and waits 60 seconds – press a
key, choose **Enroll MOK**, **Continue**, **Yes**, type the password, **Reboot**. Then turn on
Secure Boot in the firmware settings. Alternative without the password: turn Secure Boot on
directly; when shim shows the verification error, choose **Enroll key from disk** and the file
`EFI/LuxOS/luxos-secureboot.cer` on the EFI partition.

## Installed with Secure Boot off

If the USB stick was started with Secure Boot turned off (on a computer that supports it), the
installer prepares the LuxOS key already and shows the one-time password at the end. On the first
start of the installed system: press a key at "Press any key to perform MOK management", choose
**Enroll MOK**, **Continue**, **Yes**, type the password, **Reboot**. From then on Secure Boot can be
turned on in the firmware settings at any time, without any further step. Unattended installs
control this with `SECUREBOOT_ENROLL=auto|yes|no` in `install.conf`.

## Checking the state

```
luxos-secureboot status
mokutil --sb-state
```

`luxos-secureboot status` prints `secure_boot` (enabled, disabled, setup), `boot_path` (shim or
direct), `luxos_key` (enrolled, pending, missing), `kernel` (signed or unsigned) and `loader`
(installed or missing). While an enrollment is waiting, it also shows the password again.
`sudo luxos-secureboot cancel` withdraws a prepared enrollment.

## Drivers (NVIDIA, Wi-Fi)

Drivers that are part of the LuxOS kernel are signed when the kernel is built. Drivers built on the
computer (DKMS: NVIDIA, Broadcom Wi-Fi) load with Secure Boot too, nothing has to be done.
`luxos-secureboot enroll` also adds the computer's own DKMS key (`/var/lib/dkms/mok.pub`) in the
same step, if it exists, so these drivers are trusted as well.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Blue screen "Verification failed" on every start | the key was not enrolled: choose OK, then Enroll key from disk (steps above) |
| "Secure Boot violation" before any LuxOS screen | turn on Microsoft 3rd-party UEFI CA in the firmware (see above) |
| MokManager did not appear or the time ran out | the request is discarded; run `sudo luxos-secureboot enroll` again and press a key at the blue screen (it waits 60 seconds) |
| Boot menu entry ends with "- needs Secure Boot off" | a snapshot or the previous kernel from before signed kernels; it starts only with Secure Boot off. The main LuxOS entry and LuxOS Recovery always start; such entries disappear as old snapshots are removed |
| Firmware was reset | the MOK list usually survives; if not, enroll the key again from `EFI/LuxOS/luxos-secureboot.cer` |

Memtest86+ and the UEFI shell on the USB stick are not signed and do not start with Secure Boot on;
the live system and the installer are not affected.

## Files

| Path | Content |
|---|---|
| `/usr/bin/luxos-secureboot` | status, sync, enroll, cancel |
| `/usr/lib/luxos/secureboot/` | shim, MokManager and signed systemd-boot copied to the EFI partition |
| `/usr/share/luxos/secureboot/luxos-secureboot.pem`, `.cer` | public LuxOS Secure Boot certificate |
| `luxos-secureboot-sync.service` | checks the EFI partition at every start, removes the old boot entry |
| `/usr/share/libalpm/hooks/luxos-secureboot.hook` | updates the EFI partition after an update of the package |
| `/var/lib/luxos-secureboot/enroll-pin` | one-time password of a waiting enrollment (root only, removed after use) |

See also [Installer](installer.md), [Care and updates](care-updates.md) and
[Troubleshooting](troubleshooting.md).
