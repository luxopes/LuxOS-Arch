# Power, performance and memory

LuxOS puts speed and low resource use first. This page lists the system defaults (package
`luxos-tweaks` and parts of `luxos-desktop`/`luxos-drivers`) and the two user-facing savers:
**Data Saver** and **Battery Saver**.

## Data Saver (luxos-datasaver)

Toggle: **Control Center › Data Saver** tile, or the command:

```bash
luxos-datasaver on|off|toggle|status
```

What it does:

- State file `~/.config/luxos/datasaver` (exists = on).
- Marks every active NetworkManager connection as **metered** (`nmcli device modify <dev>
  connection.metered yes`), so apps that honour metered connections limit background downloads.
- Networks connected later are marked too: `luxos-hub` watches NetworkManager and runs
  `luxos-datasaver reapply`; `luxos-session` also reapplies it at login.
- **LuxOS Care** does not update automatically on a metered connection (reason shown: "The connection
  is metered (Data Saver)").
- **LuxOS Store** shows "Data Saver is on - updates are not checked automatically."
- `lux` still downloads when you run it yourself (passes `--datasaver` to the backend, which only
  reminds you of the download size before asking).
- System background downloads `reflector.service` (mirror list) and `archlinux-keyring-wkd-sync.service`
  are skipped on any metered connection (Data Saver, or a phone hotspot NetworkManager guesses as
  metered): drop-in `ExecCondition=/usr/lib/luxos/luxos-unmetered` (package `luxos-tweaks`). They run
  again at the next timer elapse on an unmetered connection.
- Not changed (not controllable reversibly): Firefox prefs, third-party sync clients.

Turning it off sets `connection.metered no` on active devices.

## Battery Saver (luxos-powersaver)

Toggle: **Control Center › Battery Saver**, **Battery & Power** app, or:

```bash
luxos-powersaver on|off|toggle|status
```

- State file `~/.config/luxos/powersaver`; original values in `~/.config/luxos/powersaver.saved`.
- On (like macOS Low Power Mode), session part:
  - power-profiles-daemon profile **power-saver** (EPP "power", platform_profile low-power);
  - built-in display (eDP/LVDS/DSI) above 60 Hz is switched to ~60 Hz (also after monitor changes);
  - backlight dimmed by 20 % (not below 40 %, only when above 40 %);
  - GTK animations off (xsettings `/Gtk/EnableAnimations`), no Dock magnification.
- System part `luxos-powersaver.service` (root, started without a password by polkit rule
  `50-luxos-powersaver.rules`, helper `/usr/lib/luxos/luxos-powersaver-helper`, originals in
  `/run/luxos/powersaver.saved`):
  - CPU turbo/boost off (`intel_pstate/no_turbo`, `cpufreq/boost`, per-policy `boost`);
  - HDA audio codec power save 1 s (only if it was 0);
  - USB autosuspend for idle devices whose driver handles it (webcam `uvcvideo`, Realtek card readers)
    or that have no driver; input, audio, Bluetooth, network, storage and hubs are left alone;
  - `vm.dirty_writeback_centisecs` 500 → 1500 (fewer disk wake-ups);
  - pauses `man-db.timer` and `luxos-care-check.timer` (they catch up when the saver turns off);
  - marker `/run/luxos/powersaver`: LuxOS Care does not update automatically unless charging.
- Off: everything restored (previous power profile, refresh rate, brightness if you did not change
  it meanwhile, animations, Dock zoom; the service's stop restores the system values).
- After reboot `/run` is empty; `luxos-session` runs `luxos-powersaver reapply` at login.
- Deliberately not changed: Wi-Fi power save (already on by default in the kernel), PCIe ASPM
  (`powersave` can disable L1 substates and use more power, `powersupersave` is unstable on some
  hardware), SATA link power (already the kernel default on laptops), NMI watchdog (already off),
  NVIDIA dGPU (runtime PM from `luxos-drivers` already powers it off when idle), freezing apps.

### Automatic Battery Saver at 20 %

In **Battery & Power › Battery Saver** the switch *Turn on automatically at 20 %* creates
`~/.config/luxos/powersaver-auto`. The top-bar battery indicator (`luxos-battery`) then turns Battery
Saver on when the battery is discharging at ≤ 20 % (notification "Battery Saver is on – Battery is at
N %. Connect the charger.") and turns it off again when charging – but only if it was turned on
automatically (marker `$XDG_RUNTIME_DIR/luxos-powersaver-auto-on`).

### Stay awake while music or video is playing

Battery & Power › Screen and sleep › *Stay awake while music or video is playing* (default on; off =
`~/.config/luxos/sleep-while-playing` exists). xfce4-power-manager handles the lid (it holds logind's
`handle-lid-switch` inhibitor), so `luxos-hub` watches MPRIS players over D-Bus (no polling) and
while something plays temporarily sets xfce4-power-manager's lid action to *Turn off the screen* (if it
was Sleep/Hibernate) and sleep-on-inactivity to *Never*. The originals are in
`~/.config/luxos/sleep-override` (restored after 30 s without playback, and at luxos-hub start after a
crash). If the lid was closed while playing, the computer then goes to sleep (via
xfce4-power-manager, which locks the screen). Battery & Power edits the originals while the override
is active.

Battery & Power also offers the power mode (Power Saver / Balanced / Performance, when
power-profiles-daemon supports them), screen-off and sleep timeouts, lid action and *Advanced Power
Settings…* (xfce4-power-manager). See [Settings apps](settings-apps.md).

## Low-memory protection (earlyoom)

LuxOS uses **earlyoom** (enabled service); `systemd-oomd` is disabled on upgrade because on Xfce it
would kill the whole session. Drop-in `/usr/lib/systemd/system/earlyoom.service.d/10-luxos.conf`:

```
earlyoom -m 4,2 -s 8,4 -r 0 -n --avoid "<protected>" --prefer "<preferred>"
```

- When free RAM < 4 % **and** free swap (zram) < 8 %, the largest process gets `SIGTERM`; below 2 % / 4 %
  it gets `SIGKILL`.
- Protected (`--avoid`): Xorg/Xwayland, lightdm, systemd*, xfce4-session, xfwm4, xfce4-panel,
  xfdesktop, xfsettingsd, plank, luxos-hub, luxos-menubar, luxos-greeter, PipeWire, WirePlumber,
  NetworkManager, wpa_supplicant, D-Bus, polkitd, udisksd, sshd, earlyoom.
- Preferred victims (`--prefer`): browser tabs/content processes, chromium/chrome, electron, code,
  node, java, qemu-system-x86.
- `luxos-hub` shows a critical notification **"Memory is running low – “<app>” used too much memory
  and was closed so the computer would not freeze."**

Related cgroup limits:

- `user-.slice`: `MemoryHigh=92%` – user programs are throttled (pushed to zram) instead of freezing
  the desktop.
- `lightdm.service`: `MemoryLow=200M` – the display server and login stay responsive.

## zram swap

`/etc/systemd/zram-generator.conf` (a backup file – local edits are kept):

```ini
[zram0]
zram-size = min(ram / 2, 8192)
compression-algorithm = zstd
swap-priority = 100
fs-type = swap
```

Compressed swap in RAM, half of RAM up to 8 GiB.

## sysctl (/usr/lib/sysctl.d/99-luxos.conf)

| Setting | Value | Why |
|---|---|---|
| `vm.swappiness` | 180 | zram swap is cheap |
| `vm.page-cluster` | 0 | no swap read-ahead for zram |
| `vm.watermark_boost_factor` / `vm.watermark_scale_factor` | 0 / 125 | smoother reclaim |
| `vm.vfs_cache_pressure` | 50 | keep directory/inode caches |
| `vm.dirty_bytes` / `vm.dirty_background_bytes` | 256 MiB / 64 MiB | fewer stalls when copying big files |
| `kernel.nmi_watchdog` | 0 | fewer interrupts |
| `net.core.default_qdisc` / `net.ipv4.tcp_congestion_control` | fq / bbr | faster network (`tcp_bbr` loaded via modules-load.d) |
| `net.ipv4.tcp_fastopen` | 3 | |
| `fs.inotify.max_user_watches` | 524288 | IDEs, file sync |

`luxos-safe` adds `kernel.yama.ptrace_scope = 2` and `fs.suid_dumpable = 0` (see [Safe](safe.md)).

## I/O schedulers

udev rule `60-luxos-ioschedulers.rules`: NVMe → `none`, SSD/eMMC → `mq-deadline`, rotating disks → `bfq`.

## journald and shutdown

- Journal limited to `SystemMaxUse=200M`, `RuntimeMaxUse=64M`.
- `DefaultTimeoutStopSec=10s` and `DefaultTimeoutAbortSec=10s` for system and user managers – faster
  shutdown/restart.

## Kernel, file system, builds

- The installer installs the **linux-zen** kernel.
- Btrfs with `compress=zstd:1,noatime` (subvolumes `@`, `@home`, `@log`, `@cache`) – see
  [Installer](installer.md).
- `/etc/makepkg.conf.d/luxos.conf`: `MAKEFLAGS="-j$(nproc)"`, multithreaded zstd, LTO – faster AUR
  builds through `lux`.

## Services enabled by the installer

From `/usr/lib/luxos/services`: NetworkManager, lightdm, bluetooth, cups.socket, avahi-daemon,
power-profiles-daemon, systemd-timesyncd, earlyoom, fstrim.timer, paccache.timer, reflector.timer.

## NVIDIA runtime power management

On hybrid-graphics laptops an unused NVIDIA GPU is put to sleep: `luxos-drivers` ships
`options nvidia NVreg_DynamicPowerManagement=0x02` and udev rules setting `power/control=auto` for the
NVIDIA GPU, its HDMI audio and USB-C controller. See [Drivers](drivers.md).
