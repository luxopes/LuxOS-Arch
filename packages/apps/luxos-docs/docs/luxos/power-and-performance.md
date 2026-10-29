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
- System background downloads `reflector.service` (mirror list `/etc/lux/mirrorlist`, converted by
  the `luxos-tweaks` drop-in) and `archlinux-keyring-wkd-sync.service`
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
  - only when `~/.config/luxos/powersaver-60hz` exists (Battery & Power, off by default - the mode
    change blanks the screen for a moment): built-in display (eDP/LVDS/DSI) above 60 Hz is switched
    to ~60 Hz (also after monitor changes);
  - backlight dimmed by 20 % (not below 40 %, only when above 40 %);
  - no Dock magnification. GTK animations stay on: without them progress spinners stop and apps
    look frozen, for practically no energy saved (until 0.9.11 the saver turned them off; the
    original value is restored once).
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
  it meanwhile, Dock zoom; the service's stop restores the system values).
- After reboot `/run` is empty; `luxos-session` runs `luxos-powersaver reapply` at login.
- Deliberately not changed: Wi-Fi power save (already on by default in the kernel), PCIe ASPM
  (`powersave` can disable L1 substates and use more power, `powersupersave` is unstable on some
  hardware), SATA link power (already the kernel default on laptops), NMI watchdog (already off),
  NVIDIA dGPU (runtime PM from `luxos-drivers` already powers it off when idle), freezing apps.
- Battery Saver sets the Power Saver profile, so games are back on the integrated GPU (see Performance
  mode below).

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

## Performance mode: maximum performance including the GPU (luxos-gpu)

Choosing **Performance** (Battery & Power, or any tool that sets the power-profiles-daemon profile)
switches everything to maximum performance; **Balanced** and **Power Saver** switch it back. The only
source of truth is power-profiles-daemon's `ActiveProfile`: `luxos-hub` listens for its
`PropertiesChanged` signal (no polling) and runs `luxos-gpu apply` on every change and 2 s after login.
`apply` is idempotent – it compares the wanted state with what is there, so leftovers after a crash,
logout or a changed profile are fixed at the next login.

- **CPU**: power-profiles-daemon itself (amd-pstate-epp / intel_pstate: EPP `performance`; on
  amd-pstate-epp also the `performance` governor; platform profile where the firmware has one).
  Selecting Performance in Battery & Power while **Battery Saver** is on turns Battery Saver off first
  (it disables CPU turbo).
- **Graphics** (laptops with hybrid graphics – a discrete NVIDIA or AMD GPU next to the GPU that drives the
  screen, detected from sysfs `boot_vga`/`uevent` without waking the dGPU): games and demanding apps run on
  the discrete GPU, the desktop (xfwm4 compositor, panel, Dock) stays on the integrated GPU.
  - Environment for offload: NVIDIA (proprietary driver) `__NV_PRIME_RENDER_OFFLOAD=1
    __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only` (the same as `prime-run`);
    AMD/Intel/nouveau dGPU `DRI_PRIME=1`. Variables you set yourself are kept.
  - **Native apps**: `luxos-apps-sync` (package hook) writes a copy of every `.desktop` file with
    `Categories=…Game…` or `PrefersNonDefaultGPU=true` (not `DBusActivatable`) to
    `/var/lib/luxos/apps/applications` with `Exec=luxos-gpu run …` and `X-LuxOS-GPU=true`. Launchpad,
    the menu, Dock, Search and Files use these. `luxos-gpu run` asks power-profiles-daemon at every launch
    (a few ms) – in Performance mode it sets the variables, otherwise it just starts the program.
  - **Flatpak apps** (Flathub): the Flatpak sandbox does not see the launcher's choice reliably, so
    `apply` adds the variables to your user overrides
    `~/.local/share/flatpak/overrides/<app-id>`, group `[Environment]` (same file as
    `flatpak override --user`) for game launchers (Steam, Heroic, Lutris, Bottles, Prism Launcher,
    ATLauncher, itch, RetroArch, RetroDECK, Sober, PCSX2, RPCS3, Cemu, Dolphin, Blender) and every
    installed Flatpak whose exported `.desktop` is a game or prefers the discrete GPU. Only missing keys are
    added; your own keys and values are never changed. What LuxOS added is listed in
    `~/.local/state/luxos/gpu-flatpak` and removed when leaving Performance mode (unless you changed the
    value meanwhile); files LuxOS created are deleted. Steam's own GPU choice ("AMD Radeon Graphics
    (RADV …)") does not matter then – Vulkan only shows the NVIDIA GPU to games.
  - **NVIDIA PowerMizer** "Prefer Maximum Performance" (`nvidia-settings -a
    [gpu:0]/GpuPowerMizerMode=1` in the running X session; the previous value is in
    `$XDG_RUNTIME_DIR/luxos/gpu-powermizer` and restored when leaving). Best effort: on PRIME render
    offload the GPU sleeps (runtime D3) when no app uses it and the driver may return to adaptive
    clocks after waking up; under game load adaptive mode already runs at full clocks.
  - **Discrete AMD GPU**: `power_dpm_force_performance_level` `high` (back to the previous value, usually
    `auto`) through `luxos-gpu-performance.service` (root, started without a password by polkit rule
    `50-luxos-gpu.rules`; `luxos-gpu system on|off`, originals in `/run/luxos/gpu-performance.saved`).
- Battery & Power shows a line under the power modes, e.g. *Graphics: NVIDIA GeForce GTX 1650 Mobile /
  Max-Q for games and demanding apps* (Performance) or *Graphics: integrated (Performance mode uses …
  for games)*.

Limits: a program reads its environment only when it starts – apps and games that are already running
keep their GPU until restarted. If a Flatpak launcher (Steam) is running when the mode changes, a
notification says "Restart Steam to run its games on …" (or that it will use the integrated graphics
again). Flatpak apps on NVIDIA need the matching `org.freedesktop.Platform.GL.nvidia-<version>` extension
(Flatpak installs it with updates). Dock items pinned from `/usr/share/applications` directly, programs
started from a terminal and D-Bus-activated apps are not wrapped – use `prime-run <app>` (NVIDIA) or
`luxos-gpu run <app>` there. switcheroo-control is deliberately not used: it would put
`PrefersNonDefaultGPU` apps on the dGPU in every mode (battery), and only GLib launchers honour it.

Commands: `luxos-gpu status` (detected GPU, profile, `offload=yes|no`), `luxos-gpu env` (variables now),
`luxos-gpu run <program>`, `luxos-gpu apply`.

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
  NetworkManager, wpa_supplicant, D-Bus, the accessibility bus (at-spi: when it is killed and later
  restarts, every running GTK app and the top bar crash), polkitd, udisksd, sshd, earlyoom.
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

## CPU scheduler (sched_ext, scx_lavd)

Since LuxOS 1.0 the CPU scheduler on desktops is **scx_lavd** (package `scx-scheds`), a
latency-aware [sched_ext](https://github.com/sched-ext/scx) BPF scheduler: windows, input, audio and
games get the CPU first when the machine is busy. Its default *autopilot* mode picks powersave,
balanced or performance by load.

- `/etc/luxos/scheduler.conf` (package `luxos-tweaks`): `SCHEDULER=lavd` (default) or
  `SCHEDULER=default` (the kernel's own EEVDF scheduler); `ARGS=` adds options for scx_lavd, e.g.
  `ARGS=--autopower` to follow the power profile (Battery Saver → powersave) instead of the load.
- Switch: `luxos-care scheduler` shows the setting and what runs now; `sudo luxos-care scheduler
  default` or `sudo luxos-care scheduler lavd` writes the file and switches immediately.
- In [system.lsl](system-config.md) the same setting is the key
  `kernel.scheduler = "lavd" | "default"` (written to `SCHEDULER=` in `/etc/luxos/scheduler.conf`).
- `luxos-scheduler.service` (`/usr/lib/luxos/luxos-scheduler`) starts it **after** the login screen
  (`After=graphical.target`), so loading the BPF program never delays booting and nothing waits for it.
- Safe fallback: without sched_ext in the kernel the unit is skipped; if scx_lavd is missing or the
  setting is `default` it exits quietly. If the scheduler crashes or the kernel ejects it (watchdog),
  the kernel switches back to EEVDF by itself; systemd retries 3× within 10 minutes and then leaves the
  kernel scheduler running. An enabled `scx_loader.service` (package `scx-tools`) takes precedence.
- Overhead: one mostly idle process (≈ 10 MB binary, typically 10–20 MB RSS) and BPF maps of a few MB;
  the scheduling decisions run in the kernel. Disk: `scx-scheds` installs all upstream schedulers
  (≈ 160 MB, 18 MB download).
- Check: `systemctl status luxos-scheduler`, `cat /sys/kernel/sched_ext/state` (`enabled`),
  `cat /sys/kernel/sched_ext/root/ops` (`lavd_…`).

## Boot speed

- Boot menu hidden without waiting: systemd-boot `timeout 0`, GRUB (BIOS) `GRUB_TIMEOUT=0` with
  `GRUB_TIMEOUT_STYLE=hidden`. To reach the menu (previous kernel, snapshots, LuxOS Recovery) hold
  **Space** (systemd-boot) or hold **Shift** / press **Esc** repeatedly (GRUB) while the computer
  starts. With other systems on the EFI partition the menu stays visible for 3 s. Installs from before
  1.0 with GRUB are switched from 1 s to 0 s once by LuxOS Care, only if they still have the LuxOS
  default (a changed `GRUB_TIMEOUT` or a visible menu is kept).
- A timeout set in the firmware variable (`bootctl set-timeout`, or `+`/`-` pressed in the
  systemd-boot menu) overrides `loader.conf`; `bootctl status` shows it, `sudo bootctl set-timeout ""`
  removes it.
- Boot splash: the progress bar finishes in `luxos-plymouth-finish.service` right after
  `basic.target`, in parallel with the network start that LightDM waits for anyway; LightDM then takes
  the splash picture over without a black gap (`plymouth quit --retain-splash`, `X -background none`).
- Kernel: `HZ=1000` and full preemption (`PREEMPT_DYNAMIC`, default `full`; `preempt=voluntary` on the
  kernel command line switches a server to throughput).

## journald and shutdown

- Journal limited to `SystemMaxUse=200M`, `RuntimeMaxUse=64M`.
- `DefaultTimeoutStopSec=10s` and `DefaultTimeoutAbortSec=10s` for system and user managers – faster
  shutdown/restart.

## Kernel, file system, builds

- The kernel is **linux-luxos** (since LuxOS 0.9.7): vanilla stable Linux from kernel.org (signature
  checked), Arch Linux's configuration as the base (every driver as a module – any hardware works
  out of the box) plus LuxOS settings (`recipe/config-luxos`: BBR TCP congestion control, `NR_CPUS=512`
  instead of 8192, transparent huge pages only on request, pinned `HZ=1000`, full preemption and
  sched_ext). No out-of-tree patches.
- Built and released automatically by GitHub Actions (<https://github.com/luxopes/luxos-kernel>): every
  6 hours it checks kernel.org, builds the chosen version, boots it in QEMU and loads ~50 typical
  drivers (storage, USB, graphics, Wi-Fi, Bluetooth, sound) before publishing. Version policy: newest
  stable series once it has at least 3 point releases (e.g. 7.3.3), until then the newest point
  release of the current series; never a release candidate, never an older series.
- The LuxOS repository picks a release up only after checking its SHA256SUMS and build provenance
  attestation (`scripts/fetch-kernel.sh`), then signs it with the LuxOS key.
- Headers for DKMS drivers (NVIDIA): `linux-luxos-headers` (installed together with the driver).
- Older installs used `linux-zen`; LuxOS Care switches them automatically (see
  [Care and updates](care-updates.md), "Switch to the LuxOS kernel").
- Btrfs with `compress=zstd:1,noatime` (subvolumes `@`, `@home`, `@log`, `@cache`) – see
  [Installer](installer.md).
- `/etc/makepkg.conf.d/luxos.conf`: `MAKEFLAGS="-j$(nproc)"`, multithreaded zstd, LTO – faster AUR
  builds through `lux`.

## Services enabled by the installer

From `/usr/lib/luxos/services`: NetworkManager, lightdm, bluetooth, cups.socket, avahi-daemon,
power-profiles-daemon, systemd-timesyncd, earlyoom, fstrim.timer, reflector.timer (writes `/etc/lux/mirrorlist`; the package cache is cleaned by LuxOS Care, not `paccache.timer`).

## NVIDIA runtime power management

On hybrid-graphics laptops an unused NVIDIA GPU is put to sleep: `luxos-drivers` ships
`options nvidia NVreg_DynamicPowerManagement=0x02` and udev rules setting `power/control=auto` for the
NVIDIA GPU, its HDMI audio and USB-C controller. See [Drivers](drivers.md).
