# Drivers and hardware detection

LuxOS picks drivers automatically. The same detection is used by the installer, by the
**Drivers** app, by the check after login and by `lux drivers`.

Package: `luxos-drivers` (`[luxos]`).

## luxos-hwdetect

`/usr/bin/luxos-hwdetect` reads only sysfs/procfs (no `lspci`, about 0.1 s) and prints what is needed.

```
luxos-hwdetect [--kernel NAME]... [--packages|--services|--report|--json]
  --packages  packages to install (default)
  --services  systemd services to enable
  --report    readable overview for the user
  --json      machine description per device (Drivers app, login check)
  --kernel    kernel whose headers are needed for DKMS (repeatable);
              default: installed kernels (/usr/lib/modules/*/pkgbase), else linux-luxos
```

Example: `luxos-hwdetect --report` prints `LuxOS hardware detection` with one bullet per finding
and the package list.

### What is detected

| Hardware | Packages / action |
|---|---|
| Intel GPU | `vulkan-intel`, `intel-media-driver` (VA-API; older GPUs `libva-intel-driver`); with multilib `lib32-mesa lib32-vulkan-intel` |
| AMD GPU | `vulkan-radeon` (VA-API is in mesa); with multilib `lib32-mesa lib32-vulkan-radeon` |
| NVIDIA Turing and newer (PCI ID ≥ 0x1e00: GTX 16xx, RTX 20xx and newer) | `nvidia-open-dkms nvidia-utils nvidia-settings libva-nvidia-driver` + kernel headers; restart needed |
| NVIDIA Maxwell / Pascal / Volta (legacy branch 580) | `nvidia-580xx-dkms nvidia-580xx-utils libva-nvidia-driver` from `[luxos]` + headers; services `nvidia-suspend`, `nvidia-resume`, `nvidia-hibernate` (enabled, not started) |
| NVIDIA Kepler (branch 470) | open-source **nouveau** (`vulkan-nouveau linux-firmware-nvidia`); optional alternative "NVIDIA 470 legacy driver" (`nvidia-470xx-dkms nvidia-470xx-utils`, Xorg only, community-patched, can break on kernel updates) |
| NVIDIA Fermi and older | nouveau (NVIDIA has no driver for current kernels) |
| Hybrid graphics (NVIDIA open/580 + Intel/AMD) | adds `nvidia-prime`; in **Performance mode** games and demanding apps use the NVIDIA GPU automatically ([Power and performance](power-and-performance.md)); `prime-run <app>` still works manually |
| VMware / VirtualBox / QEMU virtual GPU | built into the kernel (noted only) |
| Broadcom Wi-Fi (specific PCI IDs, e.g. BCM4311–4360, 43a0, 43b1, 43b3) | `broadcom-wl-dkms` + headers, restart |
| Intel Smart Sound audio (SOF) | `sof-firmware alsa-ucm-conf` (laptop speakers and microphones), restart |
| Intel IPU6 camera | `libcamera pipewire-libcamera gst-plugin-libcamera` — works through PipeWire (Firefox, apps with PipeWire camera support); apps opening the camera directly may not see it |
| Intel IPU7 camera | same packages; Linux support still experimental, the built-in camera may not work yet |
| USB Wi-Fi adapter in driver-CD mode (0bda:1a2b, 0e8d:2870) | `usb_modeswitch` |
| Thunderbolt / USB4 | `bolt` (authorizes docks and devices) |
| Intel CPU | `intel-ucode`; on laptops also `thermald` (service enabled) |
| AMD CPU | `amd-ucode` |
| VirtualBox guest | `virtualbox-guest-utils`, `vboxservice.service` |
| VMware guest | `open-vm-tools`, `vmtoolsd.service`, `vmware-vmblock-fuse.service` |
| QEMU/KVM guest | `qemu-guest-agent spice-vdagent` |
| Hyper-V guest | `hyperv`, `hv_kvp_daemon.service`, `hv_vss_daemon.service` |
| Fingerprint reader (libfprint hwdb list, else known vendors) | `fprintd` — set up in Settings › Fingerprint |
| Accelerometer (2-in-1) | `iio-sensor-proxy` (automatic screen rotation) |

32-bit (`lib32-*`) packages are added only when the `multilib` repository is enabled in
`/etc/lux/lux.conf` (or `/etc/lux/conf.d/*.conf`), e.g. by `sudo /usr/lib/lux/lux-config enable-repo multilib`.
DKMS drivers get the matching `<kernel>-headers` (e.g. `linux-luxos-headers`).

### NVIDIA generations

The legacy table is `/usr/share/luxos/hwdetect/nvidia-legacy.ids` (`<pci id> <branch> <name>`,
generated from NVIDIA driver 615.78.08 supported chips; ~162 cards on branch 580, ~117 on 470).
Unknown IDs: ≥ 0x1340 → 580, older → nouveau. With several NVIDIA cards one driver is chosen for
all (580 also supports Turing+).

### NVIDIA power management

- `/usr/lib/modprobe.d/luxos-nvidia-pm.conf`: `options nvidia NVreg_DynamicPowerManagement=0x02`
  (fine-grained D3 sleep, also for Turing).
- udev `80-luxos-nvidia-pm.rules`: runtime PM `auto` when the driver binds, plus for the card's HDMI
  audio and USB-C controller, so an unused NVIDIA GPU in a hybrid laptop powers down.
- The installer puts NVIDIA modules into the initramfs only without integrated graphics.

### Hybrid graphics

The integrated GPU drives the screen and the desktop; the NVIDIA (or discrete AMD) GPU sleeps until an
app uses it. Which apps use it follows the power mode: in **Performance** games (`Categories=Game`),
apps with `PrefersNonDefaultGPU=true` and Flatpak game launchers such as Steam start on the discrete
GPU (`luxos-gpu`, see [Power and performance](power-and-performance.md#performance-mode-maximum-performance-including-the-gpu-luxos-gpu));
in Balanced and Power Saver everything stays on the integrated GPU. `prime-run <app>` (NVIDIA) and
`DRI_PRIME=1 <app>` (AMD/nouveau) still start any single app on the discrete GPU by hand.
`luxos-gpu status` shows what was detected.

## Drivers app

`luxos-drivers` (Settings / Launchpad "Drivers"): detected hardware grouped by device with a
status — **Working**, **Installed**, **Restart required**, **Driver available**.

- **Install recommended drivers** installs everything missing through
  `pkexec /usr/lib/luxos/drivers/luxos-drivers-helper install` (lux machine mode).
- **Other option: …** offers an alternative driver, e.g. "NVIDIA 470 legacy driver" for Kepler
  (`luxos-drivers-helper install-alt <device-id> <option>`), after a confirmation "Install …?".
- If kernel headers would not match the installed kernel, it first runs a full system update
  ("Updating the system first (the kernel headers must match the kernel)…").
- "Building the driver for the kernel (this can take a few minutes)…" while DKMS builds.
- Finishes with "Drivers installed - restart to activate them" and a **Restart** button.
- In the live system it only shows what the installer will install
  ("Drivers are installed automatically when you install LuxOS.").
- Polkit action `org.luxos.drivers.policy`.

## Check after login

Inside `luxos-hub`, at most once per boot and about 45 s after login, `luxos-hwdetect --json` is
compared with installed packages. If drivers are missing (new GPU, USB adapter…), a notification
"Additional drivers are available" appears with **Show drivers** and **Don't remind me**
(remembered in `~/.config/luxos/drivers-ignored` until the hardware changes). Silent in the live system.

## lux drivers

```bash
lux drivers
```

Prints the report, lists missing packages (`Missing: …`), asks `Install now?`, installs them,
enables services (NVIDIA suspend services are enabled but not started) and ends with
`Drivers installed - restart to activate them`, or `All drivers are installed`.

## Installer

The installer runs `luxos-hwdetect --packages --kernel linux-luxos` and installs the result with the
base system. Legacy NVIDIA drivers (`nvidia-580xx-*`, `nvidia-470xx-*`) are not on the ISO; they
are downloaded from the online `[luxos]` repository after the base system. If that fails, nouveau
stays in use and the driver is offered later in Drivers.

## Verified drivers ([luxos-drivers])

Many printer and scanner drivers exist only in the AUR (user-submitted build scripts). LuxOS does
not let normal users build them blindly. Instead the drivers people need are **verified, built and
signed by LuxOS** into the repository `[luxos-drivers]` (`/etc/lux/lux.conf`; added to older
installs once by the `lux-engine` update, `lux_config.add_drivers_repo`; whoever removes it keeps
it removed).

How a driver gets into the repository (`drivers/luxdrv.py` in the LuxOS source tree):

1. `luxdrv.py discover` lists AUR packages of known vendors (`drivers/vendors.json`: Brother,
   Epson, Canon, Samsung, Kyocera, Ricoh, Xerox, HP plugin).
2. `luxdrv.py verify` checks **every new AUR commit** - also every update of an already verified
   driver - against strict rules:
   - outside functions the PKGBUILD may only assign variables (and test `$CARCH`); it is read
     with no network and an empty environment
   - sources only from the vendor's own domains, no git/svn, every source has a real checksum
     (no `SKIP`); the file is downloaded, compared and its SHA-256 pinned in
     `drivers/state/manifest.json`
   - no network tools, `| sh`, `sh -c`, `eval`, `base64 -d`, `sudo`, setuid/setgid, writes
     outside `$pkgdir`/`$srcdir` in the build functions
   - the `.install` script (runs as root on the user's computer) may only use an allowlist of
     commands, may restart only CUPS/scanner services and write only into driver directories
     (`/opt`, `/usr/share/cups`, `/etc/sane.d`, …)
   - a new AUR committer since the last verified version, or rewritten history, needs a manual
     review; the diff against the last verified commit is saved to `out/drivers/diffs/`
   - optional extra review command `LUXOS_DRIVERS_REVIEW` (e.g. LuxAI) gets the PKGBUILD,
     `.install` and diff as JSON; a non-zero exit rejects the version
   Anything that fails is **not built**; reasons are in `drivers/state/rejected.json`. If an update
   fails, the last verified version stays in the repository.
3. `./build.sh drivers` builds only verified commits, from a local copy of the AUR history, with
   the already verified sources and **no network access during the build**, then signs the
   packages and the repository with the LuxOS key. It also builds `luxos-drivers-index`: the map
   printer model (PPD `*1284DeviceID`) and scanner USB ID (udev rules) → package.
4. `scripts/publish-repo.sh` uploads `[luxos-drivers]` together with the other repositories.

Plug and play: `luxos-printing-helper` installs the printer driver by model (see
[Printing and scanning](printing-scanning.md)); `luxos-hwdetect` reads
`/usr/share/luxos/drivers-usb.tsv` and lists the scanner driver for a connected USB scanner, so the
Drivers app and the check after login offer it (device kind `scanner`).

Maintenance: `drivers/update.sh` (re-verify everything that changed in the AUR, show the
diffs, build, then publish by hand).

## Troubleshooting

- Driver says "Restart required": restart; DKMS modules load only with the new initramfs.
- NVIDIA black screen after a kernel update: LuxOS Care keeps the previous kernel
  ("LuxOS (previous kernel)" in the boot menu) and can rebuild DKMS modules
  (see [care-updates.md](care-updates.md)); manually: `sudo dkms autoinstall` then `sudo mkinitcpio -P`.
- Check what is loaded: `lsmod | grep -E 'nvidia|nouveau'`, `luxos-hwdetect --report`.
