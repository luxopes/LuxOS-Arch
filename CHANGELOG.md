# LuxOS – seznam změn

Verze: `X.Y.Z` – `Y` roste s každým novým ISO, `Z` s opravami chyb. Každá velká verze nese jméno hvězdy.
Číslo verze je v `packages/luxos-branding/files/version` (os-release, O tomto počítači, fastfetch, název ISO).
LuxOS je průběžně aktualizovaný systém (`lux update`): verze označuje, z jakého stavu systém vychází.

## 0.9.0 „Polaris“ – 2026-10-22 (beta)

První číslovaná verze.

### Vzhled a prostředí
- Prostředí ve stylu macOS nad Xfce: horní lišta s nabídkami a ikonami oken, Dock, Launchpad, Hledání, Ovládací centrum, oznámení, kalendář.
- Vlastní ikony, tapety a logo LuxOS, světlý/tmavý/automatický režim, boot splash a přihlašovací obrazovka.
- Průvodce LuxOS při prvním přihlášení.

### Aplikace
- LuxOS Store, LuxAI (s účtem LuxAI), Lux Code, LSL IDE, Kalkulačka, Kamera, Skener, Tiskárny a skenery, Ovladače, Sledování systému, Bluetooth, Baterie a napájení, Trezor (šifrovaná složka), LuxDrop (kompatibilní s LocalSend), Zpětná vazba.

### Systém
- `lux` – vlastní správce balíčků nad libalpm (místo příkazu pacman), repozitáře `[luxos]` a `[luxos-apps]` s podpisy.
- Automatická detekce hardwaru a ovladačů (NVIDIA podle generace včetně starších karet, zvuk, kamery, Wi-Fi), tisk a skenování bez nastavování.
- Ochrana proti nedostatku paměti (earlyoom), spořič dat a baterie, automatická údržba.
- 13 jazyků.

### Instalátor
- Celý disk, volné místo vedle jiného systému, existující oddíl, nebo ruční rozdělení (LVM, LUKS2, samostatné oddíly).
- Sady aplikací (Každodenní, Programování, Video a foto, Hry, Bezpečnost a sítě).
- Účet LuxAI přímo v instalátoru: přihlášení heslem, kódem z e-mailu nebo založení nového účtu.
