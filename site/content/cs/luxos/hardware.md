# Podporovaný hardware

LuxOS běží na 64bitových počítačích (**x86_64**) s **UEFI** i klasickým **BIOS**, na skutečném hardwaru
i ve virtuálních počítačích. Ovladače se rozpoznají automaticky při instalaci i po ní, takže většina
počítačů nepotřebuje žádné ruční nastavení. Tato stránka shrnuje podporu; podrobnosti jsou v
[Ovladače a rozpoznání hardwaru](drivers.html) (anglicky).

## Přehled

| Oblast | Podpora |
|---|---|
| Architektura | x86_64 (64bitové PC) |
| Spouštění | UEFI (systemd-boot) a BIOS (GRUB) |
| Disk | alespoň 20 GB; Btrfs s kompresí zstd, volitelné šifrování LUKS2, ruční LVM |
| Grafika Intel | Vulkan a hardwarové dekódování videa (VA-API) |
| Grafika AMD | Vulkan (`vulkan-radeon`), VA-API přes Mesa |
| NVIDIA Turing a novější (GTX 16xx, RTX 20xx a novější) | otevřený ovladač jádra (`nvidia-open`) |
| NVIDIA Maxwell, Pascal, Volta | starší větev 580xx z repozitáře LuxOS |
| NVIDIA Kepler a starší | open-source nouveau; pro Kepler volitelně ovladač 470xx (jen Xorg) |
| Hybridní grafika | NVIDIA s Intel nebo AMD, `prime-run <aplikace>` použije NVIDIA; nepoužívaná NVIDIA se uspí |
| Wi-Fi | čipy Broadcom dostanou `broadcom-wl-dkms`; některé USB adaptéry v režimu „disk s ovladači“ se přepnou samy |
| Zvuk | PipeWire; notebooky s Intel Smart Sound (SOF) dostanou firmware automaticky |
| Kamery | Intel IPU6 přes libcamera a PipeWire; IPU7 je v Linuxu zatím experimentální |
| Bluetooth | v základu, párování jedním klikem v Ovládacím centru |
| Čtečky otisků prstů | `fprintd`, nastavení v Nastavení › Otisk prstu |
| Akcelerometry | automatické otáčení obrazovky u 2v1 notebooků |
| Thunderbolt / USB4 | `bolt` autorizuje dokovací stanice a zařízení |
| Mikrokód CPU | `intel-ucode` nebo `amd-ucode`; `thermald` u notebooků s Intelem |
| Tiskárny a skenery | tisk bez ovladačů (IPP Everywhere) a ověřené ovladače výrobců Brother, Canon, Epson, Kyocera, Ricoh, Samsung a Xerox |

## Virtuální počítače

Nástroje pro hosta se instalují automaticky pro **VirtualBox**, **VMware**, **QEMU/KVM** (guest agent
a SPICE) a **Hyper-V**.

## Nový hardware po instalaci

Zhruba 45 sekund po přihlášení (jednou za start) LuxOS porovná rozpoznaný hardware s nainstalovanými
balíky. Chybí-li ovladač, oznámení „Jsou k dispozici další ovladače“ nabídne otevření aplikace
**Ovladače**, kde jedno tlačítko nainstaluje vše doporučené. V terminálu spusťte `lux drivers`.
Co bylo rozpoznáno, ukáže `luxos-hwdetect --report`.

## Poznámky

- Instalace potřebuje připojení k internetu (zhruba 10 minut); stahují se aktuální balíky.
- 32bitové knihovny pro hry (Steam) vyžadují repozitář `multilib`:
  `sudo /usr/lib/lux/lux-config enable-repo multilib`.
- Starší ovladače NVIDIA nejsou na ISO; stáhnou se po základním systému. Pokud se to nepovede, zůstane
  nouveau a ovladač nabídne později aplikace Ovladače.
- LuxOS Care nechává předchozí jádro v nabídce spouštění, takže vadná aktualizace jádra nenechá počítač
  bez funkčního systému. Viz [LuxOS Care](care-updates.html) (anglicky).

## Související

- [Ovladače a rozpoznání hardwaru](drivers.html) (anglicky)
- [Instalace LuxOS](installer.html) (anglicky)
- [Tisk a skenování](printing-scanning.html) (anglicky)
