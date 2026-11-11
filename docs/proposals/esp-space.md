# Místo na oddílu EFI (/boot) – plný ESP nesmí rozbít start

Stav: hotovo (luxos-secureboot 1.0.0-3, luxos-care 17, luxos-tweaks 13, luxos-branding 28,
luxos-installer 38). Uživatelská dokumentace: `packages/apps/luxos-docs/docs/luxos/boot-partition.md`.

## Incident 2026-11-10

Notebook majitele (Ryzen 5500U + GTX 1650, ovladač NVIDIA): 1GB ESP (`/boot`, FAT32, systemd-boot) plný
na 100 %. Obsah: `initramfs-linux-luxos.img` 172 MB, `initramfs-linux-luxos-prev.img` 172 MB, 2× vmlinuz
17 MB, intel-ucode 16 MB, `luxos-snapshots/` 565 MB = tři sady jádra 7.2.13 (stejné jádro, jiný initramfs,
každá 190 MB).

- `luxos-secureboot sync` (první instalace 1.0.0-1) dostal „No space left on device“, ale vypsal
  „Secure Boot loader updated“ a nechal 0B `EFI/LuxOS/{shimx64,grubx64}.efi` a
  `EFI/BOOT/{BOOTX64,grubx64,mmx64}.efi`. BootNext/BootOrder pak ukazovaly na prázdný shim, start
  zachránil jen návrat firmwaru ke staré přímé položce (MokManager se proto nikdy neukázal).
  Příčina: `put SRC DST && changed=1` – `set -e` v podmínce neplatí, po chybě `cp` proběhl `mv`
  prázdné kopie. Reprodukce: test „Plný ESP“ v `test-luxos-secureboot.sh` se starou verzí skriptu
  (24 chyb, mj. 0B soubory, kód 0, BootNext nastavený) a skutečný plný tmpfs (níže).
- Zůstal i useknutý `initramfs-linux-luxos-prev.img.new` (65 MB): `install_prev_boot` počítal staré
  soubory jako volné místo (nová kopie se ale píše vedle nich) a po chybě `.new` nesmazal.

## Proč 172 MB initramfs

Měřeno na hostiteli (`mkinitcpio -c <konfigurace hostitele> -g out/…`, jen čtení): early CPIO 145 MB,
komprimovaná část 27 MB. Firmware v obrazu: `nvidia/` 108 MB, `amdgpu/` 30 MB. Hook `kms`
(`add_checked_modules /drivers/gpu/drm/`) s autodetect přidá **nouveau** (modalias GTX 1650), i když je
zakázaný (`blacklist nouveau` z nvidia-utils) a nikdy se nenačte – a `add_module` přidá firmware
**všech** generací NVIDIA (`modinfo -F firmware nouveau`, GSP 535 i 570, už `.zst`, takže komprese
nepomůže). Plymouth navíc bral celou sbírku `Inter.ttc` (13 MB) a JetBrains Mono Nerd (2× 2,5 MB).

| Obraz (hostitel, 7.3.3) | Velikost |
|---|---|
| dosavadní konfigurace | 171,5 MiB |
| + hook `luxos-slim` (bez zakázaných nenačtených modulů) | 64,8 MiB |
| + písma Inter Variable / Noto Sans Mono | 58,8 MiB |
| totéž se `zstd -19` (+16 s sestavení, +30 ms dekomprese) | 55,3 MiB |
| totéž s `xz` (+13 s, dekomprese 0,34 s místo 0,11 s) | 54,0 MiB |

Komprese zůstává výchozí (zstd -3): −6 % za pomalejší aktualizace a start nestojí. Amdgpu firmware
(30 MB pro všechny ASIC) zůstává – amdgpu ho načítá už v initramfs a výběr podle čipu je křehký.
Ve VM (bez NVIDIA) 27,9 → 21,7 MB jen díky písmům.

## Model místa

Typický 1GB ESP po změně: hlavní jádro ~76 MB, záložní ~76 MB, mikrokód ≤ 16 MB, rezerva 100 MB +
jedna sada (~76 MB) → na sady jádra snímků zbývá ~650 MB ≈ 8 sad.

- Sady se stejným jádrem (otisk vmlinuz) a jiným initramfs: nejvýš 2 (nejnovější a nejstarší),
  snímky ostatních se přesměrují na nejnovější (stejné jádro = stejné moduly). Žádný snímek nepřijde
  o položku.
- Před každou transakcí (`snapshot-pre`) volno ≥ 100 MB + sada (+ další sada, pokud nový snímek
  potřebuje novou), jinak se mažou sady nejstarších snímků. Chráněné: sada nejnovějšího snímku a snímku,
  ze kterého systém běží; hlavní a záložní jádro sadami nejsou. Smazaná sada se stejným jádrem v novější
  sadě → přesměrování, jinak snímek zůstává bez položky (`lux rollback` k němu funguje, když je verze
  jádra stejná jako teď – nově).
- `luxos-slim` v mkinitcpio: volno < 1,25 × starý obraz + 16 MB → `luxos-care esp-clean --need`;
  pořád málo → chyba a konec dřív, než mkinitcpio začne psát přímo do starého obrazu.
- Po transakci `96-luxos-care-esp-check`: zbytky (`*.img.tmp`, `*-prev*.new`, `*.luxos-new`,
  `luxos-snapshots/*.new`) pryč, `lsinitcpio` na hlavní/záložní initramfs; useknutý → místo + `mkinitcpio
  -P`, jinak hlasitá chyba (kód 1).
- Kontrola po startu (`boot-check`) a periodická (`check`): bezpečný úklid vždy, pak problémy
  `esp_low_space` (< 50 MB), `initramfs_damaged`, `boot_loader_damaged` s pravidly `clean_esp`,
  `rebuild_initramfs`, `repair_boot_loader` (v režimu bez starostí se provedou samy).

## XBOOTLDR?

Samostatný oddíl XBOOTLDR (ext4/FAT pro jádra, systemd-boot ho čte) by ESP odlehčil, ale u stávajících
instalací znamená změnu oddílů (nejde bez rizika ani automaticky) a u nových instalací jen přesune
stejný problém na jiný malý oddíl. systemd-boot navíc čte XBOOTLDR jen přes ovladač souborového systému
firmwaru (FAT) nebo vlastní ovladače. Minimální robustní řešení je menší initramfs + hlídaný rozpočet
na stávajícím ESP; nové instalace mají 1 GiB (beze změny), instalátor varuje u ESP < 1 GB (`esp_small_warn`,
shell i GUI model).

## Testy

- `packages/luxos-secureboot/tests/test-luxos-secureboot.sh` (146): ENOSPC uprostřed zápisu (mock `cp`
  zapíše N bajtů a skončí ENOSPC) → staré soubory beze změny, žádný 0B/neúplný soubor, kód ≠ 0, žádný
  BootNext/BootOrder/položka; málo místa podle `df` → nic se nezapíše; oprava 0B zbytků z incidentu
  (status `loader=broken`, odsunutí poškozené položky na konec, po uvolnění místa oprava); neúplná kopie
  shim v EFI/BOOT; cizí BOOTX64.EFI se neposuzuje. `df` mock odmítá `-P` s `--output` jako skutečný df
  (chyba nalezená ve VM).
- `packages/luxos-tweaks/tests/test-slim.sh`: blacklist (modprobe.d, příkazová řádka, načtený modul
  zůstává, bez autodetect nic), hlídání místa (esp-clean, chyba bez změny obrazu), drop-in.
- `packages/luxos-care/tests/test_esp.py` (27): slučování sad, pořadí mazání, ochrana nejnovější/běžící
  sady, přesměrování, `pre_transaction` s rozpočtem, zbytky jen s vlastními jmény, ENOSPC uprostřed kopie
  (sada, rollback, záložní jádro – žádný `.new`, žádná položka na půl zapsaný soubor), rollback bez sady,
  problémy a akce kontroly, `esp-check`.
- Skutečný plný souborový systém (tmpfs v user namespace, bez roota): stará `luxos-secureboot`
  reprodukuje incident (0B grubx64/BOOTX64, „updated“, kód 0, nová položka UEFI), nová kód 1 bez
  0B souborů a zápisů UEFI; skutečný mkinitcpio s `luxos-slim` na 100MB tmpfs: chyba, starý obraz
  beze změny; `luxos-esp-sync`: starý pár jádro+initramfs zůstane, žádný `.new`.
- VM (QEMU, kopie instalace z 6. 11., FAT32 ESP 1 GB): mkinitcpio s `luxos-slim` a novými písmy, start,
  nový snímek a start ze snímku (`luxos.snapshot=…`, overlay) s menším initramfs; plný ESP: mkinitcpio
  nechal LuxOS Care smazat starší sadu a sestavil obraz, bez místa chyba a starý obraz beze změny;
  `esp-check` opravil useknutý initramfs; `luxos-secureboot sync` na plném FAT: kontrola předem i ENOSPC
  uprostřed zápisu bez 0B souborů.
