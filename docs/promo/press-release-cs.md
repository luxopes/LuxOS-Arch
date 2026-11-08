# Tisková zpráva (česky)

> Připraveno ke vložení. Fakta ověřena v CHANGELOG.md, packages/apps/luxos-docs/docs a site/iso.json
> k 8. 11. 2026. Odkazy na snímky vedou do aktuální galerie webu; pokud se soubory v
> `site/assets/shots/` přejmenují, před odesláním je opravte.

---

**Praha, 8. listopadu 2026**

## Vyšel LuxOS 1.0.1 „Sirius“ (beta): český Linux na Arch Linuxu s prostředím ve stylu macOS, vlastním správcem balíků a vlastním jádrem

LuxOS, nezávislá linuxová distribuce, kterou v Česku vyvíjí Antonín Tomeček, vydala verzi 1.0.1
„Sirius“ s novým instalačním ISO. LuxOS stojí na Arch Linuxu, pod povrchem používá součásti Xfce
a vzhledem připomíná macOS. Ke stažení je zdarma pod licencí GPL-3.0-or-later. **Projekt je ve fázi
beta: autor upozorňuje, že je třeba počítat s chybami a před instalací si zálohovat data.**

### Co je LuxOS

- **Prostředí ve stylu macOS.** Horní lišta s názvem aplikace a Ovládacím centrem, dock Plank,
  Launchpad (`Super+A`), Hledání (`Super+Mezerník`), tlačítka oken vlevo, světlý a tmavý režim. Pod
  tím je Xfce (xfwm4, panel Xfce), žádný těžký shell. Ikony jsou vlastní, bez log a ikon Apple.
- **Vlastní správce balíků `lux`.** Příkaz `pacman` v systému není: `lux` používá knihovnu libalpm
  (na které stojí pacman) s vlastní konfigurací `/etc/lux/lux.conf` a instaluje z repozitářů Archu
  a podepsaných repozitářů LuxOS, z Flathubu a z AUR (balíky z AUR se kontrolují a sestavují
  v sandboxu). Nad ním je grafický Obchod LuxOS.
- **Vlastní sestavení jádra `linux-luxos`.** Neupravené stabilní jádro z kernel.org s konfigurací
  Archu jako základem a nastavením LuxOS (HZ=1000, plná preempce, sched_ext), bez záplat mimo strom
  jádra. Staví se automaticky v GitHub Actions a před vydáním se zkouší v QEMU. Plánovač procesoru na
  desktopu je `scx_lavd`.
- **Aktualizace, které jdou vrátit.** LuxOS Care instaluje aktualizace na pozadí, před každou udělá
  snímek systému (Btrfs, jen pro čtení; zpět vede `luxos-care rollback`) a v zavaděči ponechává
  předchozí jádro. `/usr` je mimo instalaci balíků jen pro čtení a týdenní kontrola opraví změněné
  systémové soubory z podepsaných repozitářů.
- **Zabezpečení navíc.** Lux Guard při spuštění kontroluje programy, které přišly zvenku (stažené,
  z příloh, z USB), a nabídne jejich spuštění v sandboxu; zároveň dělá každou hodinu snímky `/home`.
  Firewall (nftables) je zapnutý od začátku, součástí je i šifrovaná složka Trezor.
- **Ovladače bez starostí.** Grafiky Intel, AMD i NVIDIA (včetně starších větví NVIDIA a hybridních
  notebooků), zvuk Intel SOF, Wi‑Fi Broadcom, čtečky otisků a nástroje pro virtuální stroje se
  rozpoznají při instalaci i později.
- **Asistent LuxAI a jazyk LSL.** LuxAI je volitelný asistent s režimem chatu a agenta, který se před
  rizikovými kroky ptá; potřebuje účet LuxAI s měsíčními limity. Část systémových aplikací je napsaná
  v LSL (Lux Simple Lang), vlastním kompilovaném jazyce autora.
- **13 jazyků** včetně češtiny, slovenštiny, angličtiny, němčiny a polštiny.

### Co přináší 1.0.1

Verze 1.0.1 je opravné vydání 1.0.0 „Sirius“ (4. 11. 2026) s novým ISO. Hlavní změny:

- Firewall je zapnutý od začátku, s dotazem **Povolit / Nechat blokované** a panelem v Nastavení;
  tiskárny, LuxDrop, Steam Remote Play nebo KDE Connect v místní síti fungují dál.
- `/tmp` se přesunul z paměti RAM do vlastního podsvazku Btrfs na disku; fork bomba v Terminálu už
  nezamrazí plochu.
- Každá aplikace LuxOS má v Obchodě úplný popis a skutečné snímky obrazovky.
- Počasí kreslí animovanou oblohu podle počasí a denní doby.
- Nová okna se otevírají do volného místa nebo kaskádovitě jako v macOS, `Alt+`` ` přepíná okna
  aktuální aplikace, nový panel emoji (`Super+.`).
- Opravy tisku a skenování, režimu správce v LuxAI (už žádné pravidlo pro root bez hesla pro celou
  relaci), návratu systému v LuxOS Care a další. Úplný seznam: <https://luxos.lux-ai.cz/cs/zmeny/>

Nainstalované systémy dostanou vše přes `lux update`, nové ISO nepotřebují.

### Snímky obrazovky

Galerie: <https://luxos.lux-ai.cz/cs/#gallery>

- Plocha: <https://luxos.lux-ai.cz/assets/shots/desktop-light.webp>
- Launchpad: <https://luxos.lux-ai.cz/assets/shots/launchpad-light.webp>
- Ovládací centrum: <https://luxos.lux-ai.cz/assets/shots/control-center-light.webp>
- Obchod LuxOS: <https://luxos.lux-ai.cz/assets/shots/store-light.webp>
- LuxAI: <https://luxos.lux-ai.cz/assets/shots/luxai-light.webp>

### Dostupnost

- Stažení (ISO 2,1 GB, x86_64, UEFI i BIOS): <https://luxos.lux-ai.cz/cs/#download>
  (vedle ISO jsou SHA256SUMS a podpis GPG)
- Požadavky: 64bitové PC, disk alespoň 20 GB; instalace trvá asi 10 minut a potřebuje připojení
  k internetu.
- Dokumentace: <https://luxos.lux-ai.cz/cs/docs/> (většina stránek je anglicky)
- Zdrojový kód: <https://github.com/luxopes/LuxOS-Arch> (jádro: <https://github.com/luxopes/luxos-kernel>)
- Anonymní statistika používání (vypnutelný „countme“): <https://luxos.lux-ai.cz/cs/pouzivani/>

### Poznámka ke zralosti

LuxOS je mladý a malý projekt: veřejný repozitář vznikl v říjnu 2026 a systém je stále označený jako
beta. Hodí se pro ty, kdo rádi zkoušejí nové systémy a hlásí chyby, zatím ne pro počítače, kde je
nejdůležitější stabilita.

### Kontakt

Antonín Tomeček – <info@lux-ai.cz> – <https://luxos.lux-ai.cz/cs/>
