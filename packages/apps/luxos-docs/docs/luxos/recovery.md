# LuxOS Recovery

LuxOS Recovery is a small repair menu in the boot menu. Use it when LuxOS does not start properly
any more, for example after an update. It can check the disk, return LuxOS to the state before an
update (a snapshot), or install LuxOS again while keeping your files and accounts.

**Opening it is safe.** Nothing runs automatically. LuxOS Recovery only shows a menu; every action
that changes something asks first. A reinstall additionally asks you to type a word. If you only
look around and choose **Restart**, nothing on the disk changes: the system, your files and the
snapshots stay exactly as they were (only the system log notes that the computer was started).

## How to open it

LuxOS starts without waiting in a boot menu, so the menu is normally hidden.

1. Turn the computer on or restart it.
2. Right after the maker's logo, press **Space** repeatedly (or hold it down) until the boot menu
   appears. On computers with GRUB (older computers without UEFI): hold **Shift** or press **Esc**.
3. Choose **LuxOS Recovery** with the arrow keys and press **Enter**.

**When a start fails, the menu appears by itself.** After every change of the system (update,
installing or removing an app, restoring a snapshot, reinstall) LuxOS watches the next start. If
that start does not finish (LuxOS or the login screen does not come up, or the power goes off), the
next start shows the boot menu for 10 seconds, so you can pick LuxOS Recovery or a snapshot without
pressing anything. After a successful start the menu is hidden again. Normal starts are not slower.
(This needs systemd-boot, the standard boot loader of LuxOS on UEFI computers. It works with
Secure Boot on.)

The boot menu shows:

- **LuxOS** – normal start (default),
- **LuxOS (before update of DATE TIME)** – one entry per snapshot: starts LuxOS exactly as it was
  before that change, without changing anything (changes made in this mode disappear after a restart),
- **LuxOS (previous kernel)** – after a kernel update, the kernel that worked before,
- **LuxOS Recovery**.

## The menu

Choose a number and press Enter. On a Czech or Slovak keyboard the keys of the top row work too
(+ ě š č ř ž … mean 1 2 3 4 5 6 …). Questions "[y/N]" also accept **a** (ano).

**1 Check the disk.** Reads the whole disk and checks the file system without changing anything
(Btrfs scrub read-only, Btrfs check read-only, the boot partition). This can take several minutes.
If a problem is found, LuxOS offers to repair what is safe: data that has a second copy on the disk
and the boot partition. It repairs only after you confirm it. LuxOS never runs the risky
`btrfs check --repair`.

**2 Restore a snapshot.** Shows the snapshots, newest first, with the apps that were being installed
or updated at that time. After you choose one and confirm it, LuxOS will start as it was at that
moment after the next restart. Your files in `/home` do not change. The current system is not
deleted – it is kept as a snapshot "before rollback", so you can go back again. Automatic updates
wait 3 days so the same update is not installed again right away.

**3 Reinstall LuxOS (keeps your files and accounts).** Downloads LuxOS and installs it again, with
the same apps. Use it when restoring a snapshot did not help. Before you confirm, the screen lists:

- what is **kept**: your files in `/home`, user accounts and passwords (by name), language, keyboard,
  time zone, disk encryption, Wi‑Fi networks (by name), Bluetooth pairings, apps from Flathub, the
  boot settings, enabled services (also the login screen), the package signing keys, and all apps
  from the LuxOS repositories (they are installed again);
- what is **lost**, by name: apps that are not from the LuxOS repositories (AUR, community, packages
  installed by hand – install them again afterwards), system settings in `/etc` you changed yourself
  (they return to the defaults), and programs installed outside the package manager (`/opt`,
  `/usr/local`).

Then you type the word shown (REINSTALL, in Czech PŘEINSTALOVAT – capital letters and accents do
not matter, "preinstalovat" works too). It needs the internet (the menu can connect to Wi‑Fi) and
takes about as long as a large update (about 6 minutes in a test with a fast connection). The old system is switched only when
the new one is complete; if anything fails, the old system stays as it was. The old system is kept as
the snapshot "before reinstall", so you can still restore it or copy something from it.

**4 Repair the settings (lux system fix).** Only on computers with a system configuration file
`/etc/luxos/system.lsl`: returns changed settings to what the file describes. It shows the
differences and asks first; a snapshot is taken before.

**5 Connect to the internet**, **6 Restart**, **7 Shut down.**

## Where it starts from

LuxOS Recovery starts from the newest snapshot, not from the current system. A broken update
therefore cannot break LuxOS Recovery. It runs the snapshot read-only with a temporary layer in
memory, so just opening it changes nothing. Before the first snapshot exists (right after
installation), it starts from the current system.

## For administrators

- Boot entries: systemd-boot `loader/entries/recovery-<entry>.conf` and
  `snapshot-<entry>-<name>.conf` (GRUB: `/boot/grub/luxos-snapshots.cfg`). LuxOS Care writes them at
  every snapshot (before every package transaction), after restore and reinstall, after cleaning the
  boot partition and after a successful start when they are missing. `sudo luxos-care boot-entries`
  rewrites them. The entry starts `systemd.unit=luxos-recovery.target`, the menu is
  `/usr/lib/luxos/care/luxos-recovery` on tty1.
- Secure Boot: snapshot entries use copies of the signed LuxOS kernel. A kernel saved before LuxOS
  signed its kernels is marked "needs Secure Boot off"; in that case LuxOS Recovery uses the signed
  kernel of the main entry.
- Boot menu after a failed start: a change of the system writes `/var/lib/luxos-care/verify-boot`.
  On the next start `luxos-care-boot-menu.service` sets the UEFI variable `LoaderConfigTimeout`
  to 10 s (`bootctl set-timeout 10`); a successful start (`luxos-care boot-check`, the same check that
  confirms a new kernel) removes it again. A timeout you set yourself (`bootctl set-timeout`, key
  `t` in the menu) is never changed.
- Command line (root): `luxos-care disk-check [--repair]`, `luxos-care snapshots`,
  `luxos-care rollback NAME --yes`, `luxos-care reinstall --plan` (what is kept and lost, changes
  nothing), `luxos-care reinstall --yes`.

See also [care-updates.md](care-updates.md) (snapshots and rollback), [boot-partition.md](boot-partition.md)
(space for snapshot kernels) and [secure-boot.md](secure-boot.md).
