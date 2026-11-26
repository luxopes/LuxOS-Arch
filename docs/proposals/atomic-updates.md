# Atomické aktualizace systému (LuxOS Care)

Stav: návrh (2026-11-26). Cíl: systém „nezničitelný“ jako Fedora Silverblue / openSUSE Aeon – běžící
systém se aktualizací nikdy nemění, aktualizace se připraví do nové kopie a přepne se při restartu;
nepovedená aktualizace = start předchozí verze, nic napůl.

## Co už je (LuxOS 1.1)

- `/usr` jen pro čtení, zapisovatelný jen během transakce (`luxos_protect.py`), týdenní kontrola
  celistvosti proti databázi balíčků.
- Snímek `@` před každou transakcí (`05-luxos-snapshot.hook`), položky snímků v zavaděči (start ze
  snímku s `systemd.volatile=overlay`), sady jader na ESP (`save_kernel`, `kset`).
- `lux rollback` (`luxos_snapshots.rollback`): za běhu přejmenuje `@` do `@snapshots`, ze snímku
  udělá nový zapisovatelný `@`, vrátí jádro snímku na hlavní položku, první start ověří
  (`VERIFY_BOOT`, jinak nabídka zavaděče).

Atomická aktualizace je tedy „rollback dopředu“: místo starého snímku se přepne na nově připravený.

## Průběh

1. **Příprava (na pozadí, běžící systém se nemění).** `luxos-care update` udělá ze `@`
   zapisovatelný snímek `@snapshots/<čas>.next` a k tomu jen pro čtení základ `<čas>.base`
   (stav v okamžiku klonu, pro slučování níže). Do `.next` připojí `/proc /sys /dev /run`,
   `/var/cache` (balíčky), `/boot` jen jako cíl sady jader (ne hlavní položka) a spustí transakci
   `lux-engine` s `RootDir=.next`. Hooky (mkinitcpio, DKMS, depmod, sysusers) běží v `.next`.
   Nové jádro + initramfs se uloží jako sada jader `.next` (`save_kernel`), hlavní položka
   zavaděče zůstává u běžícího systému.
2. **Čeká na restart.** Aktualizace softwaru ukáže „Aktualizace je připravená – restartujte“
   (jako Windows „Aktualizovat a restartovat“); v nabídce vypnutí přibude „Aktualizovat a
   restartovat / vypnout“. Nic nespěchá: další příprava jen nahradí `.next` novějším.
3. **Přepnutí při vypnutí/restartu** (`luxos-care-deploy.service`, `Before=shutdown.target`,
   `DefaultDependencies=no`, běží ještě s připojeným `/`):
   - **Sloučení `/etc` a `/var`** (změny, které uživatel/programy udělaly od klonu): třícestně
     `base` × běžící `@` × `.next` po souborech; změněno jen v běžícím → kopie do `.next`
     (`cp --reflink`, okamžitá, stejný btrfs); změněno jen v `.next` → zůstává; změněno v obou →
     vyhrává `.next` a běžící verze se uloží vedle jako `*.luxsave` (jako `.pacsave`).
     Kandidáti se hledají přes `btrfs subvolume find-new` (generace od klonu), ne procházením
     celého `/var`. Bez slučování: `/var/lib/lux` (databáze balíčků patří k `/usr`),
     `/var/cache`, `/var/log`, `/var/tmp` (vlastní subvolumy nebo bezvýznamné).
   - Pak stejně jako `rollback()`: `@` → `@snapshots/<čas>` (druh „před aktualizací“),
     `.next` → `@`, sada jader `.next` na hlavní položku, `VERIFY_BOOT`, `base` smazat.
   - Chyba kdekoli = nic se nepřepne, `.next` zůstane na příští pokus, systém nabehne jako dosud.
4. **První start** se ověří jako po rollbacku; selže-li, zavaděč nabídne předchozí systém
   (snímek „před aktualizací“) – a `luxos-care` sám vrátí, pokud start dvakrát selže.

## Aplikace a ovladače (bez restartu)

Restart kvůli instalaci aplikace by uživatele Windows odradil:

- **Flatpak** (Obchod): vždy hned, `/var/lib/flatpak` se do `.next` sloučí krokem 3.
- **Nový balíček** (`lux install X`, Obchod, ovladače), který nic neaktualizuje: nainstaluje se
  hned do běžícího systému (jako dnes, `/usr` na chvíli zapisovatelný) a je-li připravené `.next`,
  stejná transakce proběhne i v něm. Když by instalace vyžadovala aktualizaci knihoven
  (částečná aktualizace), nainstaluje se jen do `.next` a ukáže se „po restartu“.
- **Aktualizace systému** (`lux upgrade`, automatické aktualizace): vždy jen do `.next`.
  `lux upgrade --live` = dnešní chování (pro správce, Klasický režim).

## Migrace stávajících instalací

Rozvržení subvolumů se nemění (`@` obsahuje `/etc` i `/var`, jako dosud kvůli konzistentnímu
snímku). Zapnutí: `UPDATES=atomic` v `/etc/luxos/care.conf` – nové instalace ano, stávající po
aktualizaci `luxos-care` s jedním upozorněním; `UPDATES=live` = dnešní chování.

## Rizika a jak je ošetřit

- Shutdown se natáhne o sloučení (`find-new` + reflink: typicky < 2 s; limit 90 s, pak
  přepnutí odložit na příště a pokračovat ve vypnutí).
- Výpadek proudu během přepnutí: přejmenování subvolumů je atomické; mezi dvěma kroky existuje
  vždy buď starý, nebo nový `@` (pořadí jako v `rollback()`), initramfs hook najde `@` nebo
  poslední `.next` a vybere ho.
- Hooky, které sahají mimo kořen (např. zápis do NVRAM `efibootmgr`, firmware) – seznam
  povolených; ostatní se spustí až po přepnutí (`luxos-care-after-deploy.service`).
- DKMS/NVIDIA: moduly se sestaví v `.next` proti jádru `.next` – po přepnutí sedí.
- Místo na disku: `.next` sdílí bloky se `@` (btrfs CoW), roste jen o změněné soubory.

## Testy

- Jednotkové: třícestné sloučení (všechny kombinace změněno/smazáno/nové), `find-new` parser,
  pořadí přejmenování a návrat při chybě v každém kroku (falešný BTRFS jako v testech rollbacku).
- VM (`out/vm-r3-integ`): aktualizace jádra + mesa do `.next`, změna `/etc/hostname` a nová
  Flatpak aplikace mezi přípravou a restartem, restart → nové verze + obě změny zachované;
  výpadek proudu (kill QEMU) v každém kroku přepnutí → systém vždy nabehne; rozbitý initramfs
  v `.next` → automatický návrat.
