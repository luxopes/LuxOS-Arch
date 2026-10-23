# Lux Guard – model hrozeb

Lux Guard (`luxos-guard`) chrání běžného uživatele před programy, které **přišly zvenku**
(stažené prohlížečem, přílohy, USB, rozbalené archivy, jejich kopie) a které by spustil omylem.
Rizikové se před spuštěním zeptá, kritické (mazání disku nebo domova, ransomware, skrytý kód,
stažení a spuštění kódu jako správce) mimo sandbox nespustí vůbec. Jako záchranná síť dělá každou
hodinu snímek btrfs složky `/home` jen pro čtení.

Není to antivirus: žádná databáze signatur, žádné procházení disku, žádný cloud.

## Architektura

| Část | Práva | Co dělá |
|---|---|---|
| `luxos-guard service` (`luxos-guard.service`) | root, `CAP_SYS_ADMIN` (fanotify), `CAP_SYS_PTRACE` (/proc), `CAP_DAC_READ_SEARCH`, `CAP_FOWNER` | fanotify, analýza, rozhodování, stav `/var/lib/luxos-guard/state.json` (0600), socket `/run/luxos-guard/guard.sock` |
| `luxos-guard-agent` (autostart sezení) | uživatel | dotazy a oznámení (okno `luxos-guard-gui dialog`), „Spustit v sandboxu“, „Přesunout do koše“ |
| `luxos-guard-snapshot.timer` | root | `btrfs subvolume snapshot -r /home …`, úklid starých snímků |
| `luxos-guard` CLI | uživatel | `status`, `scan`, `allow`, `list`, `snapshots`, `restore` |

### Vynucení v jádře

- Skupina fanotify `FAN_CLASS_NOTIF`: `FAN_CLOSE_WRITE` na připojeních `/home`, `/tmp` a
  `/dev/shm` (`/var/tmp` jen jako samostatné připojení). Zápis se nikdy neblokuje; čtečka udělá jen `readlink` deskriptoru,
  filtr cesty a `pread` 64 B (magické číslo ELF, `#!`, přípona). Teprve spustitelný obsah jde
  do vlákna analýzy (původ, pravidla, SHA-256).
- Skupina `FAN_CLASS_CONTENT`: značky jen na **inode** hlídaných souborů – `FAN_OPEN_EXEC_PERM`
  (každý `execve`, ať je program spuštěn jakkoli: Soubory, terminál, jiný program, `sudo`) a u
  skriptů `FAN_OPEN_PERM` (interpret soubor jen otevře). Při otevření se podle `/proc/<pid>`
  rozliší interpret, který soubor spouští (`bash x.sh`, `python3 x.py`, `. x.sh`, `bash -c`), od
  programu, který ho jen čte (editor, `cp`, správce souborů, systémový nástroj v `/usr`).
- Výměnná média (`/run/media`, `/media`, `/mnt`): značka na celém připojení; soubory se analyzují
  až při spuštění (neinterpret se pustí hned).
- Hned po zápisu kandidáta ze Stažených/od prohlížeče se dá **předběžná značka**, spuštění během
  analýzy počká na výsledek (max. 15 s, pak zamítnutí).
- Kritickým souborům se odebere právo spuštění (`chmod a-x`), kritický spouštěč `.desktop` nejde
  ani přečíst (Soubory ho nespustí).
- Sandbox: proces uvnitř LuxOS Sandboxu (předek `/usr/bin/bwrap` se signaturou luxos-sandbox)
  smí soubor spustit. „Spustit v sandboxu“ soubor do sandboxu kopíruje (`luxos-sandbox run`).

### Rozhodnutí

- kritický + spuštění mimo sandbox → **vždy zamítnout**; výjimku smí udělat jen root
  (`luxos-guard allow --force`),
- rizikový → dotaz uživateli (agent podle `loginuid` procesu); bez odpovědi do 90 s nebo bez
  agenta → zamítnout. „Přesto spustit“ se pamatuje podle SHA-256 (kopie stejného obsahu se už
  neptá), značka se zruší – další spuštění nic nestojí,
- čtení → povolit.

Když služba skončí, jádro čekající události povolí (vlastnost fanotify) – systemd ji restartuje
(`Restart=always`). Jednotka záměrně nepoužívá `ProtectSystem`/`PrivateTmp`/`Protect*`: vlastní
jmenný prostor připojení by značky na připojení přesunul na kopie, které ostatní programy nepoužívají.

## Snímky

`/home/.luxos-guard-snapshots/RRRR-MM-DD_HH-MM` – subvolume jen pro čtení ve složce root 0755.
Uživatel je nemůže změnit ani smazat (mazat subvolume smí jen root, bez `user_subvol_rm_allowed`).
Domov každého uživatele má ve snímku původní práva, obnova proto běží jako uživatel.
Uchovává se 24 h po hodinách a 7 dní po dnech; při < 5 % / 2 GiB volného místa se mažou nejstarší.

## Co Lux Guard NEZASTAVÍ (poctivě)

- **Kód spuštěný jako root** může službu vypnout, smazat stav i snímky.
- **Povolený program** („Přesto spustit“) běží s právy uživatele: smí smazat vše, co uživatel
  (snímky zůstanou). Agent v sezení ověřuje jen UID – program uživatele se může vydávat za agenta
  a rizikové soubory si povolit sám (kritické ne).
- Kód, který se hlídaného souboru nedotkne: vložený do terminálu, `cat x.sh | sh`, `curl … | sh`
  napsané ručně, zneužití chyby prohlížeče, interpret mimo seznam (`make -f`, `gdb -x` …), knihovny
  načtené přes `LD_PRELOAD`/`dlopen`, Flatpak a jiné aplikace s vlastním jmenným prostorem připojení
  (zápis přes jejich připojení fanotify na `/home` nevidí), síťové disky (gvfs, SMB, NFS).
- **Analýza je podle vzorů**: zkomprimované a zašifrované programy (AppImage, UPX, PyInstaller) a
  šikovně skrytý kód jsou jen rizikové – uživatel dostane dotaz, ne blokaci.
- **Závod**: soubor spuštěný v prvních milisekundách po zápisu (dropper `curl -o x && ./x`) může
  proběhnout před předběžnou značkou; soubory zapsané mimo Stažené neznámým programem se poznají
  až po analýze (taint přes /proc je best effort – krátce běžící `cp` už nemusí existovat).
- Přetečení fronty fanotify (desetitisíce zápisů naráz) – některé zápisy se neanalyzují (počítadlo
  `overflows` v `luxos-guard status` jako root).
- Nové připojení uvnitř domova (FUSE, bind) se nehlídá; `/home` na jiném FS než btrfs = bez snímků.

## Kontrola

- `python -m pytest packages/luxos-guard/tests` (pravidla, původ, rozhodování, služba s náhradou
  fanotify, snímky), `env -u DISPLAY xvfb-run -a … tests/test_gui.py` (okna),
- ve VM jako root: `bash /usr/share/doc/luxos-guard/root-fanotify-test.sh UZIVATEL` (skutečné
  jádro, btrfs, režie).
