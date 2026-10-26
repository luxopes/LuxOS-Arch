# Hardware support

LuxOS runs on 64-bit PCs (**x86_64**), both **UEFI** and legacy **BIOS**, on real hardware and in
virtual machines. Drivers are detected automatically, during installation and afterwards, so most
computers need no manual setup. This page summarises what is supported; details are in
[Drivers and hardware detection](drivers.html).

## At a glance

| Area | Support |
|---|---|
| Architecture | x86_64 (64-bit PC) |
| Boot | UEFI (systemd-boot) and BIOS (GRUB) |
| Disk | at least 20 GB; Btrfs with zstd compression, optional LUKS2 encryption, manual LVM |
| Intel graphics | Vulkan and hardware video decoding (VA-API) |
| AMD graphics | Vulkan (`vulkan-radeon`), VA-API through Mesa |
| NVIDIA Turing and newer (GTX 16xx, RTX 20xx and newer) | open kernel driver (`nvidia-open`) |
| NVIDIA Maxwell, Pascal, Volta | legacy 580xx driver from the LuxOS repository |
| NVIDIA Kepler and older | open-source nouveau; optional 470xx driver for Kepler (Xorg only) |
| Hybrid graphics | NVIDIA with Intel or AMD, `prime-run <app>` to use the NVIDIA GPU; an unused NVIDIA GPU is powered down |
| Wi-Fi | Broadcom chips get `broadcom-wl-dkms`; some USB adapters in driver-CD mode are switched automatically |
| Audio | PipeWire; Intel Smart Sound (SOF) laptops get the firmware automatically |
| Cameras | Intel IPU6 through libcamera and PipeWire; IPU7 is still experimental in Linux |
| Bluetooth | built in, pairing in one click in the Control Center |
| Fingerprint readers | `fprintd`, set up in Settings › Fingerprint |
| Accelerometers | automatic screen rotation on 2-in-1 laptops |
| Thunderbolt / USB4 | `bolt` authorises docks and devices |
| CPU microcode | `intel-ucode` or `amd-ucode`; `thermald` on Intel laptops |
| Printers and scanners | driverless printing (IPP Everywhere) by default, plus verified vendor drivers for Brother, Canon, Epson, Kyocera, Ricoh, Samsung and Xerox |

## Virtual machines

Guest tools are installed automatically for **VirtualBox**, **VMware**, **QEMU/KVM** (guest agent
and SPICE) and **Hyper-V**.

## New hardware after installation

About 45 seconds after login (once per boot) LuxOS compares the detected hardware with the installed
packages. If a driver is missing, a notification "Additional drivers are available" offers to open
the **Drivers** app, where one button installs everything recommended. In a terminal run
`lux drivers`. Check what was detected with `luxos-hwdetect --report`.

## Notes

- Installation needs an internet connection (about 10 minutes); current packages are downloaded.
- 32-bit libraries for games (Steam) need the `multilib` repository:
  `sudo /usr/lib/lux/lux-config enable-repo multilib`.
- Legacy NVIDIA drivers are not on the ISO; they are downloaded after the base system. If that fails,
  nouveau stays active and the driver is offered later in the Drivers app.
- LuxOS Care keeps the previous kernel in the boot menu, so a faulty kernel update does not leave you
  without a working system. See [LuxOS Care](care-updates.html).

## See also

- [Drivers and hardware detection](drivers.html)
- [Installing LuxOS](installer.html)
- [Printing and scanning](printing-scanning.html)
- [Power, performance and memory](power-and-performance.html)
