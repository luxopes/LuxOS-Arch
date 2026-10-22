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
              default: installed kernels (/usr/lib/modules/*/pkgbase), else linux-zen
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
| Hybrid graphics (NVIDIA open/580 + Intel/AMD) | adds `nvidia-prime`; run `prime-run <app>` to use the NVIDIA GPU |
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

32-bit (`lib32-*`) packages are added only when `[multilib]` is enabled in `/etc/pacman.conf`.
DKMS drivers get the matching `<kernel>-headers` (e.g. `linux-zen-headers`).

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

Inside `luxos-daemon`, at most once per boot and about 45 s after login, `luxos-hwdetect --json` is
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

The installer runs `luxos-hwdetect --packages --kernel linux-zen` and installs the result with the
base system. Legacy NVIDIA drivers (`nvidia-580xx-*`, `nvidia-470xx-*`) are not on the ISO; they
are downloaded from the online `[luxos]` repository after the base system. If that fails, nouveau
stays in use and the driver is offered later in Drivers.

## Troubleshooting

- Driver says "Restart required": restart; DKMS modules load only with the new initramfs.
- NVIDIA black screen after a kernel update: LuxOS Care keeps the previous kernel
  ("LuxOS (previous kernel)" in the boot menu) and can rebuild DKMS modules
  (see [care-updates.md](care-updates.md)); manually: `sudo dkms autoinstall` then `sudo mkinitcpio -P`.
- Check what is loaded: `lsmod | grep -E 'nvidia|nouveau'`, `luxos-hwdetect --report`.
