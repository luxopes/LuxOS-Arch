# LuxOS Care and Software Update

LuxOS Care (package `luxos-care`) makes LuxOS maintenance-free: automatic updates, a kept
previous kernel with automatic fallback, and self-repair of known problems. The user-facing app
is **Software Update** (`luxos-update`, Czech "Aktualizace softwaru").

## Modes

The mode is stored in `/etc/luxos/care.conf` as `MODE=carefree` or `MODE=classic`
(missing or invalid = `carefree`). It is chosen in the installer ("How should LuxOS be maintained?",
`CARE_MODE=` in unattended installs) and can be changed in Software Update.

| Mode | Behaviour |
|---|---|
| **Carefree** (recommended) | updates install automatically in the background, known problems are repaired by built-in rules, unknown serious problems can be repaired by an option chosen by LuxAI Flash |
| **Classic** (for IT professionals) | only checks and notifies ("N updates available", problems found); you decide when to update; no automatic repairs |

Change from the command line:

```bash
luxos-care mode               # print the current mode
sudo luxos-care mode classic  # or carefree
```

The app switches mode through `pkexec /usr/lib/luxos/care/luxos-care-helper set-mode carefree|classic`.

## When automatic updates run

- `luxos-care-update.timer`: 15 min after boot, then every hour (±10 min). The service decides
  whether an update is due: at most once per ~20 hours after the last success.
- Conditions (skipped otherwise, with the reason saved):
  - internet connectivity is full (not `none`, `portal`, `limited`) — reason `offline`,
  - the connection is not metered (NetworkManager `Metered`; Data Saver marks connections
    metered) — reason `metered`,
  - on battery: average charge at least **40 %**, or charging/AC — reason `battery`.
- A manual "Update Now" ignores the metered and battery conditions (only needs internet).
- After a failure it backs off 1 h, 2 h, 4 h … up to 24 h; the user is notified after 3 failures
  in a row (or immediately for a manual update).
- In Classic mode the update timer only checks for updates (at most once per ~20 h).
- The services do not run in the live ISO (`ConditionPathExists=!/run/archiso`).

## How an update is done

1. If another package manager is running → postponed (`busy`). A stale `db.lck` is removed.
2. `lux_alpm.py check-updates` lists pending updates (refresh into a temporary database copy,
   the system database is not touched).
3. `archlinux-keyring` / `luxos-keyring` are updated first.
4. Everything is downloaded (`-Syuw`); download is safe to interrupt (shutdown stops it).
5. Installation from the cache (`-Su`) under `systemd-inhibit` (blocks shutdown, sleep and lid
   switch, "Installing updates"); on shutdown the installation is allowed to finish (up to 30 min).
6. If a file conflict involves the kept previous kernel, it is released and the install retried.
7. Old cache cleaned, `.pacnew` files recorded, reboot flagged if the kernel changed, then a
   problem check runs.

Updates go through `lux` (libalpm) when available, otherwise the internal tool `lux-engine`.
The log of all transactions is `/var/log/lux.log`, the lock `/var/lib/lux/db.lck`. Network errors are
retried within one run (after 20 s and 90 s).

## Software Update app

`luxos-update` (Settings / Launchpad "Software Update"). Shows:

- Status: "LuxOS is up to date", "N updates available", "Updating LuxOS…" with real progress
  (Downloading… X of Y, Installing X (n of m), "Do not turn off the computer."),
  "Restart to finish the update", "Updates could not be installed".
- Last update / last check, and why an automatic update is waiting ("waiting for an unmetered
  connection (Data Saver)", "waiting for the charger or more battery", "waiting for the internet connection").
- Buttons **Update Now**, **Restart**, **Check for Problems Now**.
- "When updates are installed": Carefree / Classic.
- "Available updates" list and new configuration files to review (`lux configs`).
- "System health": problems found, the kept previous kernel.
- "Repair and update history" with **Show Full Log…** (`/var/lib/luxos-care/history.jsonl`).

Update Now starts `luxos-care-update-now.service`; Check for Problems Now starts
`luxos-care-check-now.service`. A polkit rule (`50-luxos-care.rules`) lets active local users in
group `wheel` start exactly these units (and `luxos-care-apply@<id>-<n>.service`) without a password.

## Command line

```
luxos-care [status] [--json]   status (anyone)
luxos-care history [N]         audit log (JSON lines, default 30)
luxos-care mode [carefree|classic]
luxos-care update [--manual]   (root) what the update service runs
luxos-care check [--updates]   (root) problem check (+ update check)
```

Useful one-liners: `systemctl start luxos-care-update-now.service` (needs wheel),
`luxos-care status`, `journalctl -u luxos-care-update.service`.

## Files

| Path | Content |
|---|---|
| `/etc/luxos/care.conf` | `MODE=` |
| `/var/lib/luxos-care/state.json` | last update/check, pending updates, problems, kept kernel |
| `/var/lib/luxos-care/events.json` | recent events for notifications |
| `/var/lib/luxos-care/history.jsonl` | audit log of updates, repairs and AI decisions |
| `/run/luxos-care/progress.json` | progress of the running update |
| `/var/lib/luxos-care/kernel/` | kept kernel state (`prev`, `good`, `kept`) |

## Previous kernel fallback

- libalpm hook `10-luxos-care-kernel-pre.hook`: when the kernel package (`KERNEL=` in care.conf or
  `/etc/luxos/esp.conf`: `linux-luxos`; `linux-zen` on older installs until they switch) is replaced,
  the version that last booted successfully is saved.
- `95-luxos-care-kernel-post.hook`: it is restored as a boot entry **"LuxOS (previous kernel)"**
  (systemd-boot entry, or `/etc/grub.d/11_luxos_previous` with files in `/boot/luxos-prev`).
- A new kernel gets 3 boot attempts: systemd-boot boot counting (`+3` entry) or GRUB variable
  `luxos_tries` in grubenv. `luxos-care-boot.service` confirms a successful start (display manager
  active, basic targets OK) before `boot-complete.target`. After 3 failed starts the boot loader
  uses the previous kernel automatically.
- Automatic fallback works with GRUB and with a LuxOS-owned systemd-boot; with a shared ESP owned by
  another system the user picks "LuxOS (previous kernel)" in the boot menu manually.
- If the boot partition is full the entry cannot be prepared ("The boot partition is full.").


## Switch to the LuxOS kernel

Installs from before LuxOS 0.9.7 run `linux-zen`. After an update (`lux update` runs
`/usr/lib/lux/after-update.d/50-luxos-kernel`, LuxOS Care after its automatic update) LuxOS Care
switches them to `linux-luxos` (`luxos-care kernel-switch`, root):

1. installs `linux-luxos` (and `linux-luxos-headers` when `linux-zen-headers` was installed for DKMS
   drivers such as NVIDIA);
2. checks that the initramfs exists and every DKMS module is built for the new kernel – otherwise it
   stops and the system stays on `linux-zen` unchanged (state `kernel_switch_error` in
   `luxos-care status --json`; it tries again after the next update);
3. points the boot entries (`linux`/`initrd` lines, safe mode entry, shared ESP copy) at
   `linux-luxos` and writes `KERNEL=linux-luxos` to `/etc/luxos/care.conf`;
4. removes `linux-zen`; the kernel pre hook keeps it (modules, DKMS modules and the initramfs it
   booted with) as **"LuxOS (previous kernel)"**, and the new kernel gets 3 boot attempts – if it does
   not start, the boot loader goes back to `linux-zen` by itself.

A restart finishes the switch ("Restart to finish the kernel update").

## Self-repair

`luxos-care-check.timer` runs a check 30 min after boot and every 6 hours (also after each
update and at boot). Detected serious problems:

1. package database left locked (lock older than 10 min, nothing running),
2. interrupted system update,
3. missing kernel/initramfs files in `/boot`,
4. DKMS module (e.g. NVIDIA) not built for the kernel,
5. the newest kernel failed and the previous one was used,
6. a failed critical service (display manager, NetworkManager, bluetooth, cups, polkit, …),
7. disk almost full (`/` under 2 GiB and 5 % free),
8. file system errors (reported only: "back up your data"),
9. updates keep failing.

In Carefree mode built-in rules run at most once per day per problem. Only actions from a fixed
catalog are ever executed: remove stale lock, finish interrupted upgrade, refresh signing keys,
rebuild initramfs (`mkinitcpio -P`), `dkms autoinstall`, reinstall a package, restart a failed unit,
clean cache (`lux_alpm.py clean` + journal vacuum to 200 MB), retry the new kernel, use the previous kernel.
For unknown serious problems the session part (in `luxos-hub`) sends a redacted diagnosis to
LuxAI Flash with the user's LuxAI account; the AI may only pick the number of one of the prepared
options, root re-validates it, max 3 AI actions per day. Without a LuxAI account the user gets a
notification "Sign in to LuxAI to let LuxOS fix unknown problems."

## Notifications

Shown by `luxos-hub` in the user session: "LuxOS was updated", "Restart to finish the kernel
update" (Restart / Details), "Updates are available" (Classic), "Updates could not be installed",
"Update postponed", "LuxOS fixed a problem", "LuxOS found a problem". Details opens Software Update.

## Disabling

Prefer Classic mode. To stop the timers completely:
`sudo systemctl disable --now luxos-care-update.timer luxos-care-check.timer` (and
`luxos-care-boot.service` disables boot confirmation). The package re-enables the units on upgrade.
