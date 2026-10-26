# Návrh: Adresářové služby a centrální správa v LuxOS („LuxOS pro firmy“)

| | |
|---|---|
| Stav | **NÁVRH k rozhodnutí** – nic z toho zatím není implementováno |
| Cílová verze | 1.0.0 (vrstva 1) a 1.1+ (vrstva 2), viz [Etapy](#7-etapy-a-odhad-prace) |
| Datum | 2026-10-26 |
| Navazuje na | `lux system` (`packages/lux/lux_system.py`, `docs/luxos/system-config.md`), účty LuxAI (`packages/luxos-account`, `docs/luxos/luxai-account.md`), OEM režim (`packages/luxos-installer/files/luxos_oem.py`), LuxOS Care, Lux Guard, LuxDrop, `luxos-greeter`, `luxos-hub` |

Místa, kde musíš rozhodnout ty, jsou označená **🟡 ROZHODNUTÍ Rx** a souhrnně vypsaná
v [kapitole 9](#9-otevrene-otazky-a-rozhodnuti). U každého je moje doporučení.
Už rozhodnuté body jsou označené **✅ ROZHODNUTO** (self-hosted server, šablony organizací,
role ve stylu Discordu, účet LuxAI jen volitelně).

---

## 0. Shrnutí na jednu stránku

Firmy nezůstávají u Windows kvůli Windows, ale kvůli **Active Directory + Group Policy + Intune**:
jeden účet na každém počítači, centrální hesla a práva, vynucená nastavení, nasazování softwaru,
přehled o zařízeních a možnost ukradený notebook zamknout. Návrh to řeší ve dvou vrstvách:

1. **Vrstva 1 – „Připojit k firemní síti“ (kompatibilita):** LuxOS se umí připojit do
   **existující** domény Microsoft AD nebo Samba AD (realmd + SSSD + Kerberos). Přihlášení
   doménovým účtem na přihlašovací obrazovce, offline přihlášení z cache, `sudo` pro doménovou
   skupinu, firemní sdílené složky a tiskárny bez dalšího hesla, základní podmnožina GPO.
   Tohle je *vstupenka* – firma nemusí nic měnit, aby LuxOS vyzkoušela. **Patří do 1.0.**
2. **Vrstva 2 – „LuxOS Directory“ (vlastní, jednodušší AD):** **server si hostuje organizace
   sama** (rozhodnuto) – role „LuxOS Directory Server“ na počítači s LuxOS (i bez obrazovky),
   nebo balíček/kontejner pro libovolný Linux server; počítače ho najdou v LAN přes mDNS.
   Při založení se volí **šablona organizace** (Vlastní/rodina, Škola, Firma, Úřad/knihovna),
   která předvytvoří role a politiky. **Role jako na Discordu**: šablonové i vlastní, pořadí
   (hierarchie), více rolí na člověka, přepínače oprávnění povolit/zakázat/zdědit a přepsání
   pro skupiny počítačů (jako přepsání v kanálech). Účty organizace jsou na jejím serveru;
   **účet LuxAI je volitelný** (propojení / přihlášení přes LuxAI). Dále zapsání počítače
   kódem nebo už v OEM průvodci, **politiky zapsané v LSL** a aplikované přes `lux system`
   (diff, snapshot, rollback, audit), software z repozitářů lux, aktualizační kruhy přes LuxOS
   Care, vzdálené zamknutí/vymazání, inventář, úschova klíče k disku a hesla lokálního
   správce. **1.1 a dál.**

Vrstva 1 (Microsoft AD) zůstává **samostatnou volbou** – firma s Windows doménou nemusí
LuxOS Directory vůbec používat.

Proč by to firmy chtěly místo AD: politika je **čitelný soubor**, ne 4000 položek registru
v GPMC; každá změna má **diff před aplikací a rollback**; žádné CAL licence; počítač, který se
ztratí ze sítě, dál funguje; zaměstnanec vidí, co o něm firma sbírá.

---

## 1. Co firmy od AD reálně potřebují

### 1.1 Funkce, které rozhodují o nákupu

| # | Potřeba | Jak to dělá Windows | Kritické pro malou firmu (5–200 PC)? |
|---|---|---|---|
| F1 | **Jeden účet na každém PC** (SSO), nový zaměstnanec se přihlásí kdekoli | AD + Kerberos, přihlášení `FIRMA\jan` | **ano** |
| F2 | **Centrální uživatelé, skupiny, hesla**, odchod zaměstnance = 1 klik | ADUC / Entra ID | **ano** |
| F3 | **Kdo je správce** na kterém PC (bez sdíleného hesla) | Skupina „Domain Admins“, Restricted Groups, LAPS | **ano** |
| F4 | **Vynucená nastavení** (zámek obrazovky, firewall, USB, prohlížeč, tapeta) | Group Policy (GPO), Intune configuration profiles | **ano** |
| F5 | **Nasazení a aktualizace softwaru**, kontrolované vlny aktualizací | GPO software install, SCCM, Intune, WSUS/Windows Update for Business (ringy) | **ano** |
| F6 | **Inventář**: co máme, kde, v jakém stavu (šifrování, aktualizace) | SCCM/Intune, Defender | ano |
| F7 | **Ukradený notebook**: zamknout, vymazat, klíč k disku v úschově | Intune wipe, BitLocker recovery v AD | **ano** |
| F8 | **Sdílené složky a tiskárny** bez dalšího přihlašování | SMB + Kerberos, GPO mapování disků a tiskáren | **ano** |
| F9 | **Audit**: kdo co změnil, kdo se kde přihlásil | Event log, AD audit | ano (ISO 27001, NIS2) |
| F10 | **Bezpečnostní dohled** nad sítí a stanicemi | Defender for Endpoint, SIEM | spíš střední firmy |
| F11 | SSO do webových aplikací (intranet, e‑mail) | Kerberos/NTLM, Entra ID (OIDC/SAML) | střední |
| F12 | Nastavení počítače „z krabice“ bez IT technika | Autopilot | střední |

Pozn.: **NIS2** (v ČR nový zákon o kybernetické bezpečnosti, účinný od 2025) tlačí i menší firmy
k řízení přístupů, MFA, logování a správě aktiv – F2, F3, F6, F9 a MFA jsou proto prodejní argument.

### 1.2 Co na AD bolí (a kde může být LuxOS jednodušší)

| Bolest AD | Jak to udělá LuxOS jinak |
|---|---|
| Složitost: DC, DNS, FSMO, replikace, sites, trusty, schéma | Jeden server u organizace (i na běžném PC s LuxOS nebo v kontejneru), žádné vlastní DNS požadavky, žádné schéma. Pro firmy, které AD *už mají*, vrstva 1 bez změny čehokoli. |
| Licence: Windows Server + CAL na uživatele/zařízení, Intune/Entra P1 předplatné | Klient zdarma (je součástí LuxOS), server zdarma a open source (🟡 R10), žádné CAL. |
| **GPO jsou neprůhledné**: tisíce položek registru, pořadí LSDOU, filtry WMI, „proč se to neaplikovalo?“ = `gpresult` | Politika = **jeden čitelný LSL soubor** na skupinu, výsledná konfigurace PC je vidět jako soubor (`lux org policy show`), `lux system diff` ukáže přesně co se změní, každá aplikace má snapshot a rollback. |
| Změna rozbije stovky PC naráz | Aktualizační a politické **kruhy** (IT → pilot → všichni), automatický rollback, když se PC po změně nenahlásí. |
| Bez spojení s DC je PC „poloviční“ | Všechno funguje offline z poslední podepsané politiky; přihlášení z cache. |
| Správce domény je „bůh“, kterého nikdo nekontroluje | Role s nejmenšími právy, čtyři oči pro nebezpečné akce, neměnný audit log viditelný i zaměstnanci. |
| Lockout účtu po 3–5 chybách | Lokálně platí naše pravidlo: zamknutí jen při rychlosti brute-force (20 chyb / 30 s → 1 min), na serveru rate‑limit místo zamykání účtů. |

---

## 2. Vrstva 1: kompatibilita s Microsoft AD / Samba AD

### 2.1 Cíl

Počítač s LuxOS se připojí do existující domény (Windows Server 2016–2025 nebo Samba 4 AD DC)
**bez jakékoli změny na straně domény**, s výjimkou volitelné instalace šablon politik LuxOS
(2.7). Uživatel se přihlásí doménovým účtem na `luxos-greeter`, má domovskou složku, přístup ke
sdíleným složkám a tiskárnám a doménoví správci mají `sudo`.

### 2.2 Technologie (stav k 10/2026)

| Komponenta | Účel | Kde je | Poznámka |
|---|---|---|---|
| **SSSD 2.13** | NSS (uživatelé/skupiny), PAM (přihlášení), Kerberos, offline cache, GPO access control | Arch `extra` | standard RHEL/Fedora/Ubuntu; `id_provider = ad` |
| **realmd 0.17** | zjištění domény (`realm discover`) a připojení | **AUR** | poslední vydání 2022, ale stabilní; D-Bus API → hodí se pro GUI |
| **adcli** | vytvoření účtu počítače, keytab, obnova hesla stroje | **AUR** | používá ho realmd i SSSD (`ad_maximum_machine_account_password_age`) |
| **oddjob(-mkhomedir)** | vytvoření domovské složky | **AUR** | lze nahradit `pam_mkhomedir` (pam je v `core`) → oddjob nepotřebujeme |
| **krb5 1.22** | Kerberos | `core` | |
| **samba 4.25** (klientské části) | `samba-gpupdate` (aplikace GPO), `smbclient`, `winbind` ne | `extra` | jen pro GPO, viz 2.7 |
| **cifs-utils**, **gvfs-smb** | připojení SMB sdílení | `extra` | Thunar používá gvfs |

**Rozhodnutí v návrhu:** `realmd` a `adcli` přeneseme do repozitáře `[luxos]` jako
ověřené balíčky (stejně jako ovladače podle politiky AUR 0.9.10 – kontrola diffu při každé
aktualizaci). Nebudeme je instalovat z AUR „community“ sandboxu, protože běží jako root.
`oddjob` nepotřebujeme (`pam_mkhomedir`).

Alternativa *winbind* místo SSSD: lepší pro složité trusty a ID mapping kompatibilní se
Samba file servery, ale těžší a hůř funguje offline. **SSSD je pro desktop lepší volba.**

### 2.3 Nový balíček `luxos-domain`

```
luxos-domain
├── /usr/bin/lux-domain → volá se jako `lux domain …` (podpříkaz lux)
├── /usr/lib/luxos/domain/luxos-domain-helper   (root, volaný přes pkexec, pevné akce)
├── /usr/lib/luxos/python/luxos_domain.py        (logika bez GTK: discover, join, status, leave)
├── /usr/share/luxos/domain/sssd.conf.tmpl       (náš výchozí sssd.conf)
├── /usr/share/polkit-1/actions/org.luxos.domain.policy
└── závislosti: sssd, realmd, adcli, krb5, samba (jen klient + gpupdate), cifs-utils, gvfs-smb
```

Příkazy:

```bash
lux domain discover firma.local          # najde DC, typ (AD/Samba), požadavky
sudo lux domain join firma.local -U admin  # připojí (zeptá se na heslo správce domény)
lux domain status                        # doména, DC, online/offline, stav keytabu, cache, GPO
sudo lux domain leave                    # odpojí (účet počítače smaže, pokud má práva)
sudo lux domain admins add "LuxOS Admins"   # doménová skupina = správci tohoto PC
sudo lux domain login allow "Účtárna"       # kdo se smí přihlásit (realm permit -g)
```

Postup `join` (vše přes pevné příkazy bez shellu, stejně jako `lux_system.py`):

1. `realm discover` → ověření, že doména je AD, časový rozdíl < 5 min (Kerberos!) – jinak
   nabídnout synchronizaci času z DC (`timedatectl` + `systemd-timesyncd` na DC).
2. `realm join --membership-software=adcli --client-software=sssd` (heslo jde na stdin,
   nikdy v argumentech).
3. Přepsání `/etc/sssd/sssd.conf` naší šablonou (viz 2.4), `chmod 600`.
4. PAM: přidání `pam_sss` do `/etc/pam.d/system-auth` (a tím i `lightdm`, `sudo`,
   `xfce4-screensaver`), `pam_mkhomedir` do session. Pozor na pořadí s `pam_fprintd`
   (otisk prstu) a `pam_faillock` (naše nastavení 20/30 s zůstává).
5. NSS: `sss` do `passwd`, `group`, `shadow`, `sudoers` v `/etc/nsswitch.conf` (stejný styl
   jako `luxos-nsswitch-mdns` z `luxos-printing` – idempotentní úprava řádku + hook při
   aktualizaci `glibc`/`filesystem`).
6. Kerberos: `/etc/krb5.conf` s `dns_lookup_kdc = true`, `default_ccache_name = KCM:`
   (SSSD KCM – ticket přežije odhlášení a obnovuje se).
7. Před krokem 2 snapshot přes LuxOS Care (`luxos-care snapshot --kind system`), aby šel
   `lux rollback`.
8. Záznam do `/var/lib/luxos/domain/state.json` a do auditu (journal `-t luxos-domain`).

### 2.4 Výchozí `sssd.conf` (podstatné volby)

```ini
[sssd]
domains = firma.local
services = nss, pam, sudo

[domain/firma.local]
id_provider = ad
access_provider = ad
ad_domain = firma.local
krb5_realm = FIRMA.LOCAL
cache_credentials = True          # offline přihlášení
krb5_store_password_if_offline = True
offline_credentials_expiration = 30   # dní bez kontaktu s DC (🟡 R5)
use_fully_qualified_names = False     # přihlášení jako „jan“, ne „jan@firma.local“
fallback_homedir = /home/%u
default_shell = /usr/bin/lsh          # naše lsh, ne bash
ldap_id_mapping = True                # UID/GID z SID (bez POSIX atributů v AD)
ad_gpo_access_control = enforcing     # respektovat GPO „Allow log on locally“
ad_gpo_map_interactive = +lightdm, +luxos-greeter
krb5_renewable_lifetime = 7d
krb5_renew_interval = 60m
```

Kolize jmen: když existuje lokální `jan` i doménový `jan`, `use_fully_qualified_names = False`
by to zakrylo. `join` to zkontroluje a nabídne buď plná jména jen pro kolize (`full_name_format`),
nebo přejmenování lokálního účtu. (🟡 R4 – výchozí chování.)

### 2.5 Přihlášení, domovské složky, offline režim

- **`luxos-greeter`** už má položku „Other…“ pro ruční zadání jména. Doplníme:
  - text pole „Jméno (firma\\jan nebo jan@firma.local)“ a pod ním malý řádek
    „Přihlášení do domény FIRMA“;
  - doménové účty, které se na tomto PC už přihlásily, se ukážou jako dlaždice s avatarem
    (z cache SSSD + `luxos-profile-picture`), jako lokální účty;
  - **stav sítě**: když DC není dostupný, „Offline – přihlásíte se uloženým heslem“
    (rozlišit od chybného hesla!);
  - **vypršelé heslo**: PAM konverzace `chauthtok` přímo na přihlašovací obrazovce
    (LightDM to podporuje, greeter musí umět víc výzev za sebou);
  - **zamčený účet v AD** (lockout nastavuje doména, ne my): jasná hláška „Účet je zamčený
    správcem domény“, stejně jako dnes u `pam_faillock`.
- **Domovská složka** `/home/jan` vzniká při prvním přihlášení z `/etc/skel` (LuxOS skel,
  tedy stejný vzhled a Dock jako lokální uživatel). Volitelně (politika) síťová domovská
  složka nebo „Home drive“ z atributu `homeDirectory` přes `pam_mount` + CIFS s Kerberos
  ticketem – **ne ve výchozím stavu** (pomalé, nefunguje offline).
- **Offline přihlášení**: SSSD si po úspěšném online přihlášení uloží hash hesla
  (SHA-512 se solí, root-only cache v `/var/lib/sss/db`). Bez spojení s DC se dá přihlásit
  `offline_credentials_expiration` dní. První přihlášení na novém PC vyžaduje spojení s DC
  (nebo VPN – viz 2.9).
- **Zámek obrazovky** (`xfce4-screensaver` + náš greeter v režimu `--lock`) jde také přes
  `pam_sss`, takže změna hesla v AD platí i pro odemčení.
- **Otisk prstu** (`luxos-fingerprint`) funguje i pro doménový účet po prvním přihlášení
  heslem (otisky jsou lokální).

### 2.6 Správci, sudo a polkit

- `lux domain admins add GROUP` zapíše `/etc/sudoers.d/50-luxos-domain` (`%GROUP ALL=(ALL:ALL) ALL`,
  ověření `visudo -c`) a **polkit pravidlo** `49-luxos-domain-admins.rules`
  (`polkit.addAdminRule` → `unix-group:GROUP`). Polkit je nutný, protože naše aplikace
  (LuxOS Care, Software Update, tiskárny, Lux Guard…) se ptají na skupinu `wheel`.
  Pravidla, která dnes kontrolují `subject.isInGroup("wheel")` (např. `50-luxos-care.rules`),
  rozšíříme o skupinu ze `/etc/luxos/admin-groups` – jedno místo pravdy.
- Výchozí návrh při joinu: skupina „Domain Admins“ + volitelně „LuxOS Admins“, pokud v doméně
  existuje. Lokální účet vytvořený v instalátoru zůstává správcem (nouzový přístup).
- Kontrola `lux system`: „alespoň jeden správce“ musí počítat i doménovou skupinu.

### 2.7 Group Policy – co je reálné

Linux nemá registr, takže GPO lze mapovat jen částečně. Tři úrovně:

1. **Přihlašovací práva (hned, zdarma)** – SSSD `ad_gpo_access_control` čte z GPO
   „Allow/Deny log on locally / through Remote Desktop“ a podle toho povolí přihlášení.
2. **`samba-gpupdate` (Samba 4.25)** – klientská rozšíření, která už existují: sudo práva,
   skripty (cron hourly/daily…), MOTD a text na přihlašovací obrazovce, certifikáty
   (auto‑enrollment z AD CS), **politiky Firefoxu a Chromia**, `smb.conf`, firewall (firewalld –
   my máme ufw, nepoužijeme), nastavení GNOME (nepoužijeme). Spouští se `samba-gpupdate`
   s keytabem stroje; `--rsop` vypíše výslednou politiku, `--unapply` vrátí. Zapneme jen
   bezpečnou podmnožinu: **sudoers, certifikáty, Firefox/Chromium, MOTD/login text**.
   Skripty z GPO **ne ve výchozím stavu** (spouštění libovolného kódu jako root – 🟡 R6).
3. **Vlastní ADMX šablony „LuxOS“** – nejzajímavější: dodáme `LuxOS.admx/.adml` (cs, en), které
   si správce nahraje do Central Store. V GPMC pak uvidí složku „LuxOS“ s položkami jako
   *Zámek obrazovky po N minutách*, *Režim aktualizací (Carefree/Classic) a kruh*, *Lux Guard
   vynutit*, *Firewall*, *USB disky jen pro čtení*, *LuxDrop: příjem jen od důvěryhodných*,
   *Nainstalované balíčky*, *Tapeta*. Hodnoty jdou do `Registry.pol` pod
   `Software\Policies\LuxOS\…`. Náš **CSE** (client side extension registrovaná do
   `samba-gpupdate`, Python – Samba to umožňuje přes `register_gp_extension`) je přeloží do
   **LSL fragmentu** `/etc/luxos/system.d/40-domain-gpo.lsl` a zavolá `lux system apply -y`
   (se snapshotem). Tím vrstva 1 i vrstva 2 používají **stejný aplikační mechanismus** (kap. 3.8).

Spouštění: `luxos-domain-gpo.timer` (při startu + každých 90 min ± 30 min, jako Windows),
`lux domain gpupdate` ručně. Výsledek: `lux domain gpresult` – které GPO, které položky,
co se změnilo (diff z `lux system`).

### 2.8 Sdílené složky, tiskárny, SSO do webu

- **SMB sdílení**: Thunar/gvfs-smb s Kerberos ticketem z KCM → `smb://fs.firma.local/data`
  se otevře bez hesla. Politika (GPO LuxOS šablona nebo LSL) může přidat **záložky** do
  postranního panelu Souborů („Firemní data“) – jen záložky, ne trvalé mounty (rychlost,
  offline). Volitelně `pam_mount` pro mapování při přihlášení.
- **Tiskárny**: `luxos-printing` už umí IPP Everywhere. Pro Windows print server přidáme do
  `luxos-printing-helper` frontu `smb://print.firma.local/Tiskarna` s
  `AuthInfoRequired=negotiate` (Kerberos). Tiskárny z politiky (GPO „Deployed Printers“ není
  v `samba-gpupdate`, takže přes naši ADMX položku nebo LSL `printers`).
- **SSO do webu**: Firefox politika `Authentication.SPNEGO = [".firma.local"]` (lze nastavit
  automaticky při joinu) → intranet/Exchange/SharePoint s Kerberos bez hesla.

### 2.9 UX: „Připojit k firemní síti“

Jedno místo v **Nastavení → Uživatelé a skupiny → Firemní síť** (anglicky „Join Company
Network…“, jako „Network Account Server“ v macOS), plus:

- **Instalátor** (GUI i text) a **OEM průvodce** (`luxos-setup-assistant`): krok „Komu
  počítač patří?“ → *Mně* / *Firmě nebo škole*. U firmy: „Doména Windows (Active Directory)“
  nebo „LuxOS Directory (kód organizace)“. Bezobslužná instalace: `DOMAIN=`, `DOMAIN_USER=`,
  `DOMAIN_OU=`, heslo přes soubor s právy 0600 nebo jednorázový „offline join“ přes
  předvytvořený účet počítače (`adcli preset-computer` na straně IT → jednorázové heslo).
- Dialog: pole „Doména“ (automaticky předvyplněné z DHCP `domain-search`), tlačítko
  **Najít** (`realm discover`) → zobrazí „Microsoft Active Directory – firma.local – 2 řadiče“
  → „Jméno a heslo správce domény“ → průběh s lidskými kroky („Vytvářím účet počítače…“,
  „Nastavuji přihlášení…“) → hotovo, „Odhlaste se a přihlaste doménovým účtem“.
- Chyby přeložené do lidštiny: hodiny nesedí, DNS nenachází DC (nejčastější chyba – nabídnout
  DNS z DHCP / ruční IP DC), nedostatečná práva, účet počítače už existuje (nabídnout
  přepsání).
- **VPN před přihlášením** (první přihlášení vzdáleně): NetworkManager systémové VPN
  (WireGuard/OpenVPN) s `permissions=` prázdné a `autoconnect` → funguje i na přihlašovací
  obrazovce. Ikona sítě v greeteru to ukáže. (Později.)

### 2.10 Co vrstva 1 neřeší

Inventář, vzdálené akce, aktualizační kruhy, úschova klíčů k LUKS – AD na to nemá Linuxové
protějšky (to dělá Intune, který Linux podporuje jen pro Ubuntu/RHEL a velmi omezeně). To je
prostor pro vrstvu 2 – a vrstva 2 může běžet **vedle** vrstvy 1 jen pro správu zařízení
(viz 3.13).

---

## 3. Vrstva 2: LuxOS Directory

### 3.1 Princip

> Organizace = **server LuxOS Directory, který si hostuje sama**, na něm seznam lidí (účty
> organizace, volitelně propojené s účtem LuxAI), jejich **role** (jako na Discordu), skupiny
> počítačů a **LSL politiky**. Počítač si stáhne politiku a svá efektivní oprávnění, ověří podpis,
> sloučí to s lokálním `system.lsl` a aplikuje přes `lux system`.

Pracovní názvy (🟡 R11): **LuxOS Directory** (služba), **LuxOS Directory Server** (role/balíček
`luxos-directory-server`), **Lux Admin** (konzole), `lux org` (příkazy), `luxos-org-service`
(služba na PC). Žádné jméno neobsahuje „daemon“.

Vrstva 1 (Microsoft AD / Samba AD, kap. 2) zůstává **samostatnou volbou** pro firmy, které
doménu Windows už mají; LuxOS Directory ji nenahrazuje ani nevyžaduje.

### 3.2 Nasazení serveru (✅ ROZHODNUTO: self-hosted u organizace)

Server neběží na lux-ai.cz. LuxOS je desktopová distribuce, proto server musí jít nasadit
třemi způsoby, vždy **stejný program** (Python, jeden proces + pracovní vlákna, SQLite ve
výchozím stavu):

| Způsob | Pro koho | Jak |
|---|---|---|
| **A. Role na počítači s LuxOS** | rodina, malá škola/firma bez serveru | Nastavení → **Sdílení → Adresář organizace** (jako macOS Server.app), nebo `lux install luxos-directory-server && sudo lux org server init`. Běží jako služba na pozadí běžného desktopu (např. PC rodiče, PC v kabinetu). |
| **B. LuxOS v režimu server (bez obrazovky)** | školy, firmy s vyhrazeným strojem (i starý PC) | instalátor: nová volba **„LuxOS Server – adresář organizace“**: bez Xfce/Plank, jen jádro, lux, Care, Guard, firewall, `luxos-directory-server`, SSH volitelně; správa přes webovou konzoli nebo `lux org server …` přes SSH. Care v režimu Classic s oknem údržby (aktualizace serveru nesmí přijít uprostřed vyučování). |
| **C. Libovolný Linux server** | firmy s existující infrastrukturou (Debian, Ubuntu, Proxmox, NAS) | **OCI obraz** (podman/Docker, `compose.yaml` v dokumentaci, data ve volume `/var/lib/luxos-directory`), nebo Python balíček (wheel) + systemd jednotka; později `.deb`/`.rpm`. |

**Průvodce `lux org server init`** (i v GUI): název organizace → **šablona** (3.4) → první
vlastník (jméno, heslo, volitelně propojení s účtem LuxAI) → adresa serveru (hostname v LAN,
volitelně veřejná adresa pro notebooky mimo firmu) → vytvoření **CA organizace** a klíčů →
nastavení záloh → vytiskne/uloží **záchranný list** (QR se záložním klíčem vlastníka, 4.5).

**Součásti serveru:** HTTPS API (port 8443, TLS z vlastní CA organizace – žádný Let's Encrypt
nutný), webová konzole, CA, databáze (SQLite; PostgreSQL volitelně nad ~2000 PC),
fronta úloh, volitelně **cachovací zrcadlo repozitářů se snímky** (3.10) a volitelně
**WireGuard brána** pro notebooky mimo LAN. Nároky: 1 jádro, 1 GB RAM a pár GB disku stačí na
stovky PC (bez zrcadla); se zrcadlem +30–60 GB.

**Objevení v LAN (mDNS):** server ohlašuje `_luxos-dir._tcp` (Avahi – už ho máme kvůli
tiskárnám) s TXT `org=<název>`, `id=<id organizace>`, `fp=<otisk CA>`. Instalátor, OEM průvodce
a Nastavení → Firemní síť ukážou „Nalezeno: **ZŠ Lipová** (server.zs-lipova.lan)“. **Objevení
samo nic nezakládá na důvěře** (mDNS lze podvrhnout): zápis vyžaduje kód nebo QR od správce,
který obsahuje otisk CA; alternativně potvrzení **6místného kódu na obou obrazovkách**
(stejný princip jako LuxDrop – PC ukáže kód, správce ho potvrdí v konzoli). Bez mDNS (jiná
podsíť, VLAN): DNS záznam `_luxos-dir._tcp.firma.lan` (SRV), DHCP doména, nebo ruční adresa.

**Zálohy:**
- automatická denní šifrovaná záloha (`lux org server backup`): databáze + CA + klíče serveru +
  konfigurace, šifrovaná heslem/klíčem vlastníka (age), cíl: druhý disk, NAS (SMB/SFTP) nebo
  **LuxOS Backup** (`luxos-backup`, už existuje); uchovávání 7 denních + 4 týdenní;
- konzole varuje, když se záloha 2 dny nepovedla;
- `lux org server restore ZÁLOHA` na nový stroj → klienti pokračují (stejná CA a klíče; nová IP
  se najde přes mDNS/hostname). Test obnovy je v testovacím plánu i v dokumentaci jako
  „vyzkoušejte jednou za čtvrt roku“.

**Vysoká dostupnost (později, E5):** volitelný **záložní server** (replika jen pro čtení:
streamovaná replikace SQLite/PostgreSQL). Replika umí přihlášení, synchronizaci politik a
zamknutí, ne změny v administraci. Povýšení repliky ručně jedním příkazem. Pro většinu
organizací stačí jeden server, protože klienti fungují offline (4.5).

**Když je server vypnutý/nedostupný:** PC pracují dál s poslední podepsanou politikou a
oprávněními; přihlásí se každý, kdo se na tomto PC už přihlásil (cache, `offline_days`);
**nový** uživatel na cizím PC se nepřihlásí; vzdálené akce a hlášení se zařadí do fronty a
odešlou po obnovení. Rodinný scénář (server na PC rodiče, které je vypnuté) tak funguje bez
omezení pro běžné používání.

**Aktualizace serveru:** přes lux/Care jako jakýkoli balíček; migrace databáze vždy s
automatickou zálohou předtím; server a klienti mají verzované API (klient o 2 verze starší musí
fungovat).

### 3.3 Identita: účty organizace, LuxAI volitelně

Zdroj pravdy o lidech je **server organizace**. Účet LuxAI **není podmínkou** (✅ ROZHODNUTO):

- **Účet organizace** (výchozí): uživatelské jméno + heslo (Argon2id na serveru), volitelně
  TOTP/FIDO2. Funguje úplně bez internetu. Hromadný import z CSV (školy: export z Bakalářů /
  Edookitu, firmy: z HR tabulky).
- **Propojení s účtem LuxAI** (volitelné, pro člena i pro celou organizaci podle šablony):
  - člen může svůj účet organizace propojit s účtem LuxAI (OAuth/PKCE přes `lux-ai.cz`) → po
    přihlášení na PC jsou **LuxAI, Lux Code a LSL IDE rovnou přihlášené** (SSO, server předá
    token do `~/.config/luxai/account.json` – stejný formát jako dnes);
  - organizace může povolit **„Přihlásit se účtem LuxAI“** jako alternativní způsob ověření
    (heslo LuxAI ověří server organizace u lux-ai.cz) – vyžaduje internet a OIDC na lux-ai.cz
    (E6, volitelné);
  - oprávnění `luxai.use` (3.5) určuje, zda člen vůbec smí LuxAI na PC používat.
- **Bez propojení** se na lux-ai.cz nic neposílá – organizace je plně soukromá.

#### Model identity

```
Organizace (id, název, šablona, CA, klíče, nastavení)
├── Členové  – whitelist: účet organizace (± propojený účet LuxAI)
│     stav: pozvaný / aktivní / pozastavený / odebraný
│     atributy: jméno na PC („jan“), UID (přidělený serverem, stabilní), celé jméno, role, avatar
├── Role     – viz 3.5 (pořadí, barva, oprávnění, přepsání pro skupiny počítačů)
├── Skupiny počítačů – „Učebna 1“, „Kabinet“, „Notebooky“, „Kiosk“ (obdoba kanálů na Discordu)
├── Počítače – id, jméno, sériové číslo, klíč, certifikát, skupina, primární uživatel, stav
└── Politiky – LSL dokumenty pro organizaci, roli nebo skupinu počítačů, s kruhem aktualizací
```

**Whitelist** = jen aktivní člen, který má na dané skupině počítačů oprávnění
`device.signin`, se na PC přihlásí. To je tvoje původní myšlenka „přihlásit se na kterémkoli PC
v síti, pokud to PC dovolí a účet je na whitelistu“ – „PC dovolí“ je přepsání oprávnění pro
skupinu počítačů.

Uživatelské jméno a UID: server přidělí `uid` z rozsahu organizace (1 000 000–1 999 999) a
jméno bez kolizí. Kolize s lokálním účtem na PC → přihlášení odmítnuto s jasnou hláškou a
konflikt v konzoli (🟡 R4).

### 3.4 Šablony organizací (✅ ROZHODNUTO)

Při zakládání adresáře správce zvolí šablonu. Šablona je obyčejný **LSL soubor**
(`/usr/share/luxos-directory/templates/*.lsl`), který předvytvoří role, oprávnění, skupiny
počítačů a výchozí politiky. Po založení je vše normálně upravitelné; šablona jen dává rozumný
start. Vlastní šablony lze exportovat a sdílet (např. IT firma, která spravuje 20 škol).

| Šablona | Role (od nejvyšší) | Skupiny počítačů | Výchozí politiky a funkce |
|---|---|---|---|
| **Vlastní (rodina)** | Rodič, Dítě, Host | Domácí počítače | Server jako role na PC rodiče (A). Dítě: webový filtr „Děti“, **čas u obrazovky** (denní limit, povolené hodiny), instalace aplikací jen **na žádost** (rodič schválí v notifikaci – „Ask to Buy“), USB jen čtení. Host: dočasný profil smazaný po odhlášení, bez LuxAI, bez USB zápisu. Care Carefree, Guard zapnutý, LuxDrop „jen rodina“. Propojení s LuxAI doporučeno pro rodiče. |
| **Škola** | IT admin, Vedení (Admin), Učitel, Žák | Učebny, Kabinety, Notebooky, Kiosk | Žák: bez instalace, webový filtr „Škola“, USB jen čtení, nesmí měnit síť, terminál skrytý (měkké omezení), LuxAI podle volby školy. Učitel: tisk, sdílené složky „Materiály“, **režim testu** pro učebnu (dočasně: síť jen na povolené adresy, LuxAI a LuxDrop vypnuté, USB zakázané), vzdálená pomoc žákům v učebně se souhlasem/indikací. Sdílené PC v učebnách: smazání profilů žáků po 30 dnech, rychlé přihlášení. Import tříd z CSV. Aktualizace mimo vyučování. |
| **Firma** | IT admin, Admin, Vedoucí, Zaměstnanec | Kancelář, Notebooky, Sdílené/kiosk | Zaměstnanec: instalace z Lux Store (Flathub) do profilu, tisk, sdílené složky podle oddělení. Vedoucí: schvaluje žádosti o aplikace svých lidí, vidí inventář svého týmu. Kruhy aktualizací (IT → pilot → všichni), LUKS recovery key v úschově, LAPS, zámek obrazovky 10 min, firewall vynucený. |
| **Úřad / knihovna** | Správce, IT admin, Úředník, Veřejnost | Kancelář, Veřejné terminály | Veřejnost: **kiosk** – automatické přihlášení hosta, profil vymazán po odhlášení nebo 10 min nečinnosti, jen prohlížeč a kancelář, tisk (případně placený – mimo rozsah), webový filtr „Veřejný“. Úředník: jako Zaměstnanec; přísnější audit (retence 2 roky), USB zakázané (citlivá data). |
| **Prázdná** | Admin | – | jen vlastník a role `@všichni`; pro zkušené správce |

🟡 R16: další šablony (např. „Kancelář malé firmy bez IT“, „Ordinace“ s důrazem na
zdravotnická data)? Doporučení: v 1.1 jen těchto pět.

### 3.5 Role a oprávnění (jako Discord) (✅ ROZHODNUTO)

#### Pravidla (převzatá z Discordu, doplněná o bezpečnost)

- **Role** mají **pořadí** (seznam, nejvyšší nahoře), název, barvu (v konzoli a u jména) a sadu
  oprávnění. Každý člen má automaticky roli **`@všichni`** a libovolný počet dalších rolí.
- Každé oprávnění má v roli stav **Povolit ✓ / Zakázat ✗ / Zdědit /** (zdědit = role k tomu
  nic neříká).
- **Přepsání pro skupinu počítačů** (obdoba přepsání v kanálu): u skupiny „Učebna 1“ lze pro
  `@všichni`, pro konkrétní roli nebo konkrétního člena nastavit jiné ✓/✗/ /. Navíc lze přepsat
  i **pro jeden počítač** (výjimka, v konzoli zvýrazněná).
- **Hierarchie správy**: člen může spravovat jen role **pod svou nejvyšší rolí** a jen lidi,
  jejichž nejvyšší role je pod jeho; nemůže udělit oprávnění, které sám nemá. Vlastník
  (Owner) stojí nad vším a nelze ho odebrat posledním správcem.
- **Administrátor organizace** (`org.administrator`) = všechna oprávnění kromě těch
  označených 🔒 „vyžaduje druhé schválení“ (vymazání, změna klíčů, Security Center) – ty
  potřebují vždy druhého člověka s tím oprávněním.

#### Vyhodnocení (konflikty) – deterministický algoritmus

Pro člena *U* na počítači *P* ze skupiny *G*, pro každé **ano/ne oprávnění**:

1. **Základ** = `@všichni`; pak pro všechny role člena: je-li v některé roli **✓, výsledek ✓**
   (povolení vyhrává mezi rolemi, jako na Discordu). Jinak ✗ z kterékoli role → ✗. Jinak výchozí
   hodnota z katalogu.
2. **Přepsání skupiny G** pro `@všichni` (✗ pak ✓).
3. **Přepsání skupiny G** pro role člena: nejdřív se uplatní všechna ✗, pak všechna ✓
   (povolení zase vyhrává).
4. **Přepsání skupiny G pro člena** (✗/✓).
5. Totéž pro přepsání **počítače P** (role, pak člen) – nejkonkrétnější vyhrává.
6. `org.administrator` / Vlastník → ✓ pro všechna oprávnění kromě 🔒 (ta jdou přes schválení).
7. **Bezpečnostní pojistka (navíc proti Discordu):** oprávnění označená **„tvrdé ✗“** – v roli
   lze zakázání zamknout (ikona zámku). Takové ✗ nepřebije povolení z **nižší** role ani
   přepsání nastavené někým s nižší rolí. Použití: „Režim testu“ – zákaz sítě pro roli Žák
   nepřebije omylem jiná role „Kroužek robotiky“.

Pro **hodnotová oprávnění** (profil webového filtru, čas u obrazovky, max. velikost tisku…):
platí hodnota z **nejvyšší role v pořadí**, která ji nastavuje; přepsání pro skupinu/počítač
má přednost stejně jako výše. Kde dává smysl „nejméně omezující“ (např. kvóta disku), je to
v katalogu uvedeno výslovně.

`lux org why jan usb.storage.write` (a stejné tlačítko v konzoli) vypíše celý průběh: které
role, která přepsání a proč výsledek – odpověď na „proč to nejde“ jedním příkazem, na rozdíl
od `gpresult`.

#### Katalog oprávnění (v1)

Rozsah: **U** = vynucuje se pro uživatele v jeho sezení, **D** = celé zařízení (vyhodnocuje se
pro primárního uživatele nebo skupinu počítačů), **S** = na serveru (správa).

| Oprávnění | Rozsah | Výchozí `@všichni` | Vynucení na PC |
|---|---|---|---|
| `device.signin` – přihlásit se na počítače (této skupiny) | U | ✓ | `pam_luxos_org` odmítne přihlášení; seznam v userdb jen pro povolené |
| `device.admin` – správce počítače (sudo, systémová nastavení) | U | ✗ | členství ve skupině `lux-p-admin` → `sudoers.d` + polkit `addAdminRule` |
| `apps.install` – instalovat aplikace z Lux Store / Flathub (do profilu) | U | ✓ | polkit akce Lux Store + Flatpak `org.freedesktop.Flatpak.app-install`; ✗ → tlačítko „Požádat o aplikaci“ |
| `apps.install.system` – instalovat systémové balíčky bez plného správce | U | ✗ | polkit akce lux helperu (jen z repozitářů LuxOS/Arch, ne komunita) |
| `apps.request` – žádat o aplikace (schvaluje role s `org.approve_requests`) | U | ✓ | Lux Store ukáže „Požádat“; schválení → politika pro uživatele |
| `apps.community` – komunitní (AUR) balíčky v sandboxu | U | ✗ | lux odmítne `--community` pro uživatele |
| `apps.run_downloaded` – spouštět programy stažené z internetu („Run Anyway“ v Lux Guard) | U | ✓ | konfigurace Lux Guard per UID: ✗ → jen „Run in Sandbox“ nebo zákaz |
| `terminal.use` – terminál (měkké omezení) | U | ✓ | skrytí spouštěčů, `luxos-terminal` odmítne start; *není to bezpečnostní hranice* – v dokumentaci výslovně |
| `usb.storage.read` / `usb.storage.write` – USB disky | U | ✓ / ✓ | polkit `org.freedesktop.udisks2.filesystem-mount*` per skupina, mount `ro`; ✗ obojí → udev neautomountuje |
| `network.settings` – měnit síťová nastavení, přidávat Wi-Fi | U | ✓ | polkit `org.freedesktop.NetworkManager.settings.modify.system` + `…wifi.share` |
| `network.vpn` – vlastní VPN | U | ✓ | polkit NM pro VPN připojení |
| `bluetooth.use` | U | ✓ | polkit bluez / rfkill v sezení |
| `print` – tisknout | U | ✓ | CUPS `AllowUser @lux-p-print` v politikách front |
| `print.manage` – přidávat tiskárny | U | ✗ | polkit `org.luxos.printing.manage` |
| `share.<název>` – přístup ke sdílené složce *název* (čtení/zápis jako dvě oprávnění) | U | ✗ | na souborovém serveru (SMB ACL nebo sdílení LuxDrop), na PC záložka v Souborech jen když ✓ |
| `luxdrop.send` / `luxdrop.receive` / `share.folders` (sdílet vlastní složky) | U | ✓ / ✓ / ✗ | konfigurace LuxDrop, systémové výchozí + zámek |
| `luxai.use` – používat LuxAI, Lux Code s účtem | U | podle šablony | skrytí aplikací + nftables `meta skuid` blokace `lux-ai.cz` pro UID; token se do profilu nezapíše |
| `web.filter` (hodnota: `vypnuto` / `deti` / `skola` / `verejny` / `prisny`) | U | `vypnuto` | lokální filtrující resolver `luxos-webfilter` (seznamy domén, lokálně, bez cloudu); nftables `meta skuid` přesměruje DNS daného UID na filtr a blokuje DoH/DoT; Firefox politika (vypnout DoH, SafeSearch) |
| `screen_time` (hodnota: denní limit, povolené hodiny, pauzy) | U | bez limitu | `pam_luxos_org` hlídá povolené hodiny při přihlášení; `luxos-hub` ukazuje zbývající čas a varování 10/5/1 min; `luxos-org-service` po vypršení zamkne sezení (`loginctl`), rodič může na dálku přidat čas |
| `session.persistent` – trvalý profil (✗ = dočasný, smaže se po odhlášení) | U | ✓ | `pam_luxos_org` session: home na tmpfs/overlay |
| `remote.assist.receive` – může přijmout vzdálenou pomoc | U | ✓ | vždy s potvrzením a viditelnou indikací |
| `device.exam_mode` – může zapnout režim testu pro skupinu | S | ✗ | server pošle dočasnou tvrdou politiku skupině |
| `org.manage_members` – lidé, pozvánky, reset hesel | S | ✗ | API serveru, hierarchie rolí |
| `org.manage_roles` – role a oprávnění (jen pod svou rolí) | S | ✗ | API serveru |
| `org.manage_devices` – zápis, skupiny počítačů, přepsání | S | ✗ | |
| `org.manage_policies` – LSL politiky, software, kruhy | S | ✗ | podpis politik (4.2) |
| `org.approve_requests` – schvalovat žádosti o aplikace/čas | S | ✗ | |
| `org.remote_assist` – vzdálená pomoc | S | ✗ | jen se souhlasem na PC |
| `org.remote_lock` – zamknout počítač / zablokovat člena | S | ✗ | |
| `org.remote_wipe` 🔒 – vymazat počítač | S | ✗ | druhé schválení |
| `org.view_inventory` – inventář (lze omezit na skupinu počítačů) | S | ✗ | |
| `org.view_secrets` – LAPS heslo, recovery key (audit, upozornění vlastníkovi PC) | S | ✗ | |
| `org.security_center` 🔒 – Lux Security Center | S | ✗ | 3.14 |
| `org.audit` – číst audit | S | ✗ | |
| `org.administrator` – vše kromě 🔒 | S | ✗ | jen Vlastník smí udělit |

Katalog je **verzovaný**; nové oprávnění se přidá s výchozí hodnotou, takže starší klienti ho
ignorují a nové nic nerozbije.

#### Jak se oprávnění dostanou do PC

1. Server pro každý počítač spočítá **efektivní oprávnění každého člena**, který se na něm smí
   přihlásit (podle algoritmu výše), a přidá je do **podepsaného balíčku politiky** (3.8).
2. `luxos-org-service` z nich vytvoří:
   - **syntetické skupiny** `lux-p-<oprávnění>` (např. `lux-p-admin`, `lux-p-usb-write`,
     `lux-p-network`) a členství v nich – přes **systemd userdb** záznamy (3.7). Statická
     pravidla polkitu, sudo a CUPS jsou v balíčku `luxos-org` jednou provždy a jen se ptají na
     skupinu; mění se jen členství → žádné generování JS pravidel, žádné riziko injekce;
   - **LSL fragment** `/etc/luxos/system.d/25-org-permissions.lsl` pro věci, které řeší
     `lux system` (správci, USB, LuxDrop, Lux Guard per UID, webový filtr, výchozí nastavení);
   - **nftables tabulku** `inet luxos_org` s pravidly `meta skuid` (webový filtr, blokace LuxAI,
     režim testu) – generovanou z validovaných hodnot (UID = číslo, domény přes sadu);
   - konfiguraci pro `pam_luxos_org` (kdo, kdy, dočasný profil) a pro `luxos-hub` (čas
     u obrazovky).
3. Změna role se projeví při další synchronizaci (sekundy přes long-poll); polkit se ptá na
   skupiny při každém dotazu, takže většina změn platí hned; `sudo`/nové procesy po
   příštím přihlášení (nebo nucené odhlášení u odebrání práv správce).
4. **Offline**: platí poslední efektivní oprávnění. Odebrání oprávnění se tedy projeví až po
   spojení – proto mají PC **maximální stáří politiky** (výchozí 30 dní, pak dočasné omezení na
   `@všichni`). 🟡 R5.

#### Ukázka: role v LSL (export z konzole, verzovatelné v gitu)

```lsl
roles = [
    {"name": "IT admin", "color": "#d33", "allow": ["org.administrator", "device.admin"]}
    {"name": "Učitel", "color": "#36c",
     "allow": ["print", "share.materialy.write", "device.exam_mode", "org.remote_assist"],
     "values": {"web.filter": "vypnuto"}}
    {"name": "Žák", "color": "#3a3",
     "deny": ["apps.install", "network.settings", "usb.storage.write"],
     "deny_locked": ["apps.community"],
     "values": {"web.filter": "skola"}}
]
overrides = {
    "Učebna 1": {"Žák": {"deny": ["luxdrop.send"]}, "@všichni": {"allow": ["print"]}}
}
```

Konzole ukazuje totéž jako Discord: seznam rolí vlevo (táhnutím měnit pořadí), vpravo
přepínače ✓ / / ✗ po kategoriích (Počítač, Aplikace, Síť, Soubory a tisk, LuxAI, Bezpečnost
dětí, Správa), u skupiny počítačů záložka „Oprávnění“ s přepsáními.

### 3.6 Zapsání počítače (enrollment)

Cesty:

1. **OEM průvodce / instalátor**: krok „Patří počítač organizaci?“ → zadat **kód organizace**
   (např. `LUX-7KQ2-9XHM`) nebo **naskenovat QR** (máme `luxos-wifi-qr` a kameru – QR může
   obsahovat i Wi-Fi firmy). Pak průvodce **nevytváří lokálního uživatele**, ale rovnou
   „Přihlaste se firemním účtem“ (jako u Mac s Automated Device Enrollment).
   V LAN průvodce rovnou nabídne servery nalezené přes mDNS („Připojit k: ZŠ Lipová“) – pak
   stačí potvrdit **6místný kód** shodný na PC a v konzoli správce (3.2).
2. **Existující PC**: Nastavení → Firemní síť → LuxOS Directory → nalezený server nebo kód;
   nebo `sudo lux org join LUX-7KQ2-9XHM` / `sudo lux org join --discover`.
3. **Hromadně** (učebna 30 PC): správce vytvoří kód s více použitími a cílovou skupinou
   („Učebna 1“, platnost 2 hodiny) a v OEM instalaci ho předá bezobslužně (`ORG_TOKEN=`
   v `install.conf`) – PC se po instalaci zapíšou sama.
4. **Zero-touch přes internet** (Autopilot) **není** – vyžadoval by centrální službu; bez
   ní ho nahrazuje bod 3.

Kód organizace (enrollment token) obsahuje/odkazuje na: URL serveru, **otisk CA organizace**
(pinning – žádná důvěra jen v systémové CA, ochrana proti MITM), platnost (výchozí 7 dní),
počet použití, cílovou skupinu počítačů, zda je nutné schválení adminem. Krátký kód se na
serveru přeloží na plný token; QR nese plný token přímo.

Průběh:

1. PC vygeneruje klíč zařízení – **v TPM 2.0**, pokud je (nevyexportovatelný), jinak
   Ed25519/P-256 v souboru 0600 root na šifrovaném disku.
2. Pošle CSR + základní inventář (model, sériové číslo, verze LuxOS, TPM ano/ne, šifrování
   disku ano/ne) přes TLS s pinnutou CA.
3. Server (po případném schválení) vydá **certifikát zařízení** (platnost 90 dní, automatická
   obnova), pošle veřejné klíče pro ověření politik (4.2) a první politiku.
4. PC zapíše `/etc/luxos/org/` (konfigurace, certifikát, pinnuté klíče), zapne
   `luxos-org-service`, aplikuje politiku (snapshot + `lux system apply`).
5. Volitelně **úschova klíče k disku** (LUKS recovery key, jako BitLocker v AD) a **heslo
   lokálního správce** (LAPS) – viz 3.12.

### 3.7 Přihlášení na PC

#### Přehled možností

| Možnost | Výhody | Nevýhody |
|---|---|---|
| SSSD `idp` provider (SSSD ≥ 2.11, Keycloak/Entra ID) | upstream, cache, NSS | jen **device flow** (na přihlašovací obrazovce kód + druhé zařízení – špatné UX), v RHEL 10 „Technology Preview“ |
| Himmelblau 3.x (Entra ID + generický OIDC od 3.0, Rust, SUSE) | hotové PAM+NSS, PIN, offline | velká závislost v AUR, orientace na Entra, cizí tempo vývoje |
| Ubuntu authd (brokery Entra/Google/OIDC) | hezký design | navázáno na GDM a snapy, nehodí se pro LightDM/Arch |
| **Vlastní tenký PAM modul + systemd userdb** | malé, rychlé, přesně pro náš model, heslo přímo na greeteru, vazba na certifikát zařízení | musíme napsat a udržovat bezpečnostně citlivý kód |

**Doporučení: vlastní, ale minimální** (🟡 R7):

- **NSS přes systemd userdb**: `luxos-org-service` vystaví Varlink službu
  `io.systemd.UserDatabase` (socket `/run/systemd/userdb/org.luxos.Directory`). Arch už má
  `nss-systemd` v `nsswitch.conf`, takže **nemusíme psát NSS modul v C**. Členové, kteří se na
  PC už přihlásili (nebo které politika „předpřipraví“), mají navíc statický JSON záznam
  v `/etc/userdb/jan.user` → fungují, i když služba neběží.
- **PAM modul `pam_luxos_org.so`** (malý, C, žádná síť, žádné parsování JSON v PAM): jen předá
  jméno + heslo (+ TOTP) přes Unix socket službě a vrátí výsledek. Veškerá logika je ve službě.
- **Online ověření**: služba pošle na server přes **mTLS s certifikátem zařízení** požadavek
  `login(jméno, heslo, totp)`. Server ověří heslo účtu organizace (Argon2id), případně – jen
  u organizací, které to povolily – heslo LuxAI u lux-ai.cz (3.3) a vrátí krátkodobý **podepsaný přihlašovací token** svázaný se zařízením
  (podobně jako Primary Refresh Token v Entra). Heslo nikdy nejde jinam než na server
  organizace přes TLS.
- **Offline ověření**: po úspěšném online přihlášení si služba uloží ověřovač hesla
  (**Argon2id**, sůl per zařízení, soubor root 0600, při TPM zapečetěný) s platností
  `offline_days` (výchozí 30, politika). Bez spojení se ověří lokálně. Po vypršení: „Připojte se
  k firemní síti pro přihlášení“ (lokální správce / LAPS funguje vždy).
- **MFA**: TOTP pole na greeteru (po heslu, jen když účet má MFA); offline se MFA nevyžaduje
  (stejné jako Windows Hello cache) nebo lze vynutit FIDO2 klíč (`pam_u2f` lokálně registrovaný
  při online přihlášení). Později „schválit na telefonu“. Otisk prstu jako lokální odemykání.
- **Změna hesla**: v Nastavení → Uživatelé (heslo účtu organizace), v greeteru při vynucené
  změně, nebo v aplikaci LuxAI Account u přihlášení účtem LuxAI;
  offline ověřovač se obnoví při dalším online přihlášení. Při odebrání člena server pošle
  revokaci → služba smaže ověřovač a zablokuje účet na PC (aktivní sezení se zamkne).
- **Rate limit místo lockoutu**: server omezuje rychlost pokusů na účet a IP; žádné trvalé
  zamykání účtů po N chybách (tvoje pravidlo).
- **Sezení**: má-li člen propojený účet LuxAI a oprávnění `luxai.use`, dostane po přihlášení
  token pro aplikace LuxAI (stejný soubor `~/.config/luxai/account.json` jako dnes, zapsaný
  službou) → LuxAI, Lux Code, LSL IDE fungují bez dalšího přihlášení (**SSO v rámci LuxOS**).
- **Oprávnění v sezení**: `pam_luxos_org` při přihlášení zkontroluje `device.signin`,
  `screen_time` (povolené hodiny) a `session.persistent` (dočasný profil) – viz 3.5.

Domovské složky: `pam_mkhomedir` z `/etc/skel` jako ve vrstvě 1. Sdílené PC (učebna) může mít
politiku „smazat domovské složky po odhlášení“ / „po 30 dnech nepřihlášení“.

### 3.8 Politiky jako LSL fragmenty (srdce návrhu)

Dnešní `lux system` čte `/etc/luxos/system.lsl` (+ `imports`), validuje, ukáže diff, udělá
snapshot, aplikuje, pamatuje si stav v `/var/lib/lux/system/applied.json` a historii 20 souborů.
To je přesně to, co GPO chybí. Rozšíření:

**1. Vrstvy konfigurace** (nová složka, čte `lux_system.py`):

```
/etc/luxos/system.d/
  20-org-base.lsl        ← z LuxOS Directory (podepsané, root 0644, needitovat)
  30-org-group-ucetni.lsl
  40-domain-gpo.lsl      ← z ADMX šablon LuxOS (vrstva 1)
/etc/luxos/system.lsl    ← lokální soubor (uživatel / místní IT)
```

Sloučení: lokální soubor má nejvyšší prioritu **kromě položek, které organizace vynutí**
(`config.mkForce` v org fragmentu = zamčeno). Pokus o přepsání zamčené položky lokálně →
chyba `firewall.enable: nastaveno organizací Firma s.r.o. (politika „Základ“), nelze změnit`.
`config.mkDefault` v org fragmentu = jen doporučení, lokálně přepsatelné.

**2. Původ hodnot**: `lux system show --origin` ukáže u každé položky, odkud je
(lokální / organizace + název politiky / doména GPO). `lux system diff` to vypíše také.
Odpověď na „proč se to neaplikovalo“ je jeden příkaz.

**3. Nové klíče** (potřebné pro firmy; každý = validace + diff + apply v `lux_system.py`):

| Klíč | Význam | Realizace |
|---|---|---|
| `admins.groups` / `admins.users` | kdo je správce PC | sudoers.d + polkit (jako 2.6) |
| `login.allow_groups`, `login.offline_days`, `login.mfa` | whitelist a pravidla přihlášení | konfigurace `luxos-org-service` |
| `lock_screen.after_minutes`, `lock_screen.require_password` | zamykání | výchozí hodnoty xfconf v `/etc/xdg/luxos` + Xfce kiosk (`/etc/xdg/xfce4/kiosk/kioskrc`) pro zamčení |
| `usb_storage` = `allow` / `read-only` / `block` | USB disky | udev pravidlo + udisks2 polkit |
| `luxdrop.receive`, `luxdrop.share` | sdílení v LAN | systémové výchozí + zámek |
| `care.ring`, `care.window` | aktualizační kruh, okno instalace | `care.conf` |
| `browser.firefox_policies` | `policies.json` | `/usr/lib/firefox/distribution/policies.json` |
| `printers`, `bookmarks.smb` | tiskárny, záložky v Souborech | `luxos-printing-helper`, gtk bookmarks v skel/politice |
| `certificates.ca` | firemní CA | `trust anchor` |
| `wifi`, `vpn` | firemní sítě (802.1X, WireGuard) | NetworkManager systémová připojení (tajemství jen přes klíč zařízení) |
| `desktop.wallpaper`, `desktop.dock` | vzhled | výchozí xfconf/Plank pro nové uživatele (neměnit existující uživatelům bez zámku) |
| `security_center.*` | viz 3.14 | |

Uživatelská nastavení (Xfce) jsou slabé místo: Xfce kiosk mód umí zamknout jen část.
Výchozí hodnoty pro nové profily jsou spolehlivé, vynucení u existujících jen pro vybrané
klíče (zámek, spořič). To otevřeně přiznat v dokumentaci.

**4. Příklad politiky „Základ“ v konzoli:**

```lsl
load config

config = {
    "packages": ["libreoffice-fresh", "hunspell-cs_cz", "firefox"]
    "flatpaks": ["org.signal.Signal"]
    "care": {"mode": config.mkForce("carefree"), "ring": "broad"}
    "guard": {"enable": config.mkForce(True)}
    "firewall": {"enable": config.mkForce(True)}
    "lock_screen": {"after_minutes": config.mkForce(10)}
    "usb_storage": "read-only"
    "luxdrop": {"receive": "trusted"}
    "admins": {"groups": ["IT"]}
    "login": {"allow_groups": ["Všichni"], "offline_days": 30}
}
```

**5. Doručení a aplikace**: server pro každé PC sestaví **balíček politiky** = seznam fragmentů
+ verze + hash, **podepsaný** (4.2). `luxos-org-service` ověří podpis, zapíše fragmenty, spustí
`lux system check` (vyhodnocení LSL jako `nobody` v `lsl config` sandboxu – už existuje),
`diff`, snapshot, `apply -y`. Výsledek (OK / chyba + diff + id snapshotu) jde zpět na server.

**6. Bezpečnost změn**: politika má **kruh** (IT → Pilot → Všichni) a **automatický rollback**:
když po aplikaci PC nenaběhne nebo se do 30 min nenahlásí, při dalším startu LuxOS Care nabídne
/ provede návrat na snapshot (máme `luxos_recovery.py`). Konzole ukáže „Politika aplikována na
48/50, 2 chyby“ s diffem.

**7. Odchod z organizace**: `lux org leave` (jen lokální správce nebo vzdáleně admin) smaže
`system.d/*org*`, zruší zámky; hodnoty zůstanou, jak byly (nic se „neodinstaluje“ samo,
kromě položek označených v politice jako `remove_on_leave`). 🟡 R8.

### 3.9 Software

- Politika obsahuje `packages` a `flatpaks` (už dnes v LSL) → instalace přes `lux`.
- **Firemní repozitář**: organizace může mít vlastní repozitář (interní aplikace) podepsaný
  klíčem organizace. Klíč se do klíčenky lux přidá při zápisu PC. Riziko: klíč organizace
  by mohl podepsat i podvržený systémový balíček – proto **lux musí umět omezit klíč na jeden
  repozitář** (v `/etc/lux/lux.conf` per‑repo `SigLevel` + seznam povolených klíčů; libalpm
  to sám neumí, ověření doplníme v lux před transakcí). Upřímně: správce organizace je na
  spravovaných PC fakticky root, ale omezení klíče brání tomu, aby *ukradený klíč repozitáře*
  znamenal ovládnutí všech PC.
- **Komunitní (AUR) balíčky** do politik nepovolíme (stejně jako dnes `lux system`).
- **Flathub** ano, systémově.
- **Lux Store** na firemním PC: politika může omezit na „jen schválené aplikace“ (allowlist)
  nebo povolit vše; uživatel bez práv správce instaluje Flatpaky do svého profilu (pokud to
  politika dovolí).

### 3.10 Aktualizace a kruhy (LuxOS Care)

- `care.ring` = `it` / `pilot` / `broad` + volitelné **okno** (např. 12:00–13:00 nebo „při
  vypnutí“).
- Problém: Arch repozitáře se mění každý den, takže „stejná aktualizace pro všechny kruhy“
  vyžaduje **zmrazený snímek** repozitářů. Varianty:
  - self-hosted server funguje i jako **cachovací zrcadlo se snímky** (`/srv/luxos-mirror/<datum>`)
    – šetří i linku (50 PC stahuje jednou); kruh *it* dostane snímek hned, *pilot* po 2 dnech,
    *broad* po 7 dnech; nouzové bezpečnostní aktualizace admin „povýší“ okamžitě;
  - bez zrcadla (malá organizace): kruh = zpoždění + Arch Linux Archive (`archive.archlinux.org/repos/RRRR/MM/DD`) a
    snímky našeho `[luxos]` (dnes server drží 3 releases – pro firmy delší retence).
- Care dál dělá snapshot před aktualizací a záložní jádro – to už máme a je to silný argument
  (Windows Update rollback je slabý).
- Konzole: „Verze LuxOS a stáří aktualizací“ po kruzích, PC, která se neaktualizovala > 14 dní.

### 3.11 Vzdálené akce

| Akce | Potřebné oprávnění (3.5) | Podmínky |
|---|---|---|
| Synchronizovat teď, aktualizovat teď, restartovat (s upozorněním přes `luxos-hub`) | `org.remote_lock` / `org.manage_devices` | – |
| **Zamknout** (zamknout sezení, zakázat přihlášení členů, zobrazit zprávu „Počítač je zablokován organizací, volejte …“) | `org.remote_lock` | okamžitě při spojení |
| **Vymazat** (kryptografické smazání: zničení LUKS keyslotů + reset do OEM stavu) | `org.remote_wipe` 🔒 + **druhé schválení** | PC musí být online; varování, že offline PC to provede až při spojení |
| Rotovat heslo lokálního správce (LAPS), zobrazit ho | `org.view_secrets` (zobrazení se audituje) | |
| Zobrazit LUKS recovery key | `org.view_secrets` (audit, upozornění vlastníkovi PC) | |
| Sesbírat diagnostiku (logy Care, Guard, `lux system` historie) | `org.remote_assist` + souhlas uživatele na PC | |
| Poslat zprávu uživateli | `org.manage_devices` | |
| **Vzdálená plocha** | nebude v MVP; později jen s viditelným souhlasem uživatele | 🟡 R9 |
| **Vzdálený shell / libovolný skript** | **ne** ve výchozím stavu | 🟡 R6 |
| **Poloha zařízení** | **ne** (GDPR, nepřiměřené) | 🟡 R9 |

Doručení: `luxos-org-service` drží jedno nečinné HTTPS spojení (long-poll, ~0 % CPU) – zamknutí
tak dorazí do sekund; když neběží, periodický check-in každých 15 min ± jitter (systemd timer).

### 3.12 Úschova klíčů (LAPS + recovery key)

- **Lokální správce (LAPS)**: při zápisu PC vznikne skrytý účet `luxadmin` (nebo se použije
  existující) s náhodným heslem, které se zašifrované klíčem serveru uloží na server
  a rotuje se po každém zobrazení / 30 dnech. Nouzový přístup bez sdíleného hesla.
- **LUKS recovery key**: OEM průvodce už pracuje s LUKS sloty; přidá se slot s recovery klíčem
  (formát jako BitLocker: 8×6 číslic), klíč jde na server (šifrovaně, přístup jen Admin
  s auditem). Zapomenuté heslo k disku → helpdesk přečte klíč.
- **TPM odemykání** (`systemd-cryptenroll --tpm2-device`, s PCR 7 + PIN) – volitelně politikou.

### 3.13 Inventář a reporty

Sbírá se jen technický stav zařízení (ne obsah, ne aktivita):

- HW: výrobce, model, sériové číslo, CPU, RAM, disky, baterie (zdraví), TPM, Secure Boot;
- systém: verze LuxOS, jádro, poslední aktualizace a výsledek Care, čekající restart,
  stav Lux Guard, firewall, šifrování disku, verze politiky a výsledek aplikace;
- software: seznam nainstalovaných balíčků a Flatpaků (pro licence a zranitelnosti);
- přihlášení: kdo a kdy se naposledy přihlásil (jméno, čas) – pro správu, ne sledování
  (retence 90 dní, 🟡 R12).

Reporty: „Nešifrované disky“, „Neaktualizováno > 14 dní“, „Lux Guard vypnut“, „Balíček X
ve zranitelné verzi“ (napojení na Arch security advisories), export CSV/JSON pro audit NIS2.

**Režim „jen správa zařízení“** pro firmy s Windows AD: PC je ve vrstvě 1 (přihlášení
doménou) a zároveň zapsané v LuxOS Directory jen pro inventář, aktualizace a politiky LSL.
Přihlašovací část vrstvy 2 je pak vypnutá. Obě přihlašovací cesty naráz ne (kolize UID).

### 3.14 Lux Security Center

Tvoje myšlenka: dohled nad síťovým provozem firemních PC. Technicky snadné, **právně
nejcitlivější část celého návrhu**.

**Právní rámec (EU/ČR):**

- **GDPR** – zaměstnavatel je správce, potřebuje právní titul (oprávněný zájem, čl. 6(1)(f))
  s testem proporcionality, **posouzení vlivu (DPIA, čl. 35)** – systematické monitorování
  zaměstnanců ho téměř jistě vyžaduje; minimalizace dat, omezení účelu, retence.
- **Zákoník práce § 316** – zaměstnavatel nesmí bez závažného důvodu spočívajícího ve zvláštní
  povaze činnosti narušovat soukromí zaměstnanců sledováním (otevřeným i skrytým),
  odposlechem či kontrolou písemností; pokud takový důvod je, musí zaměstnance **předem
  informovat o rozsahu a způsobu kontroly**. Kontrola obsahu (co kdo čte, píše) je
  v zásadě nepřípustná; bezpečnostní ochrana systémů je obhajitelná, když je přiměřená.
- Judikatura ESLP (Bărbulescu v. Rumunsko, 2017): monitoring musí být předem oznámený,
  přiměřený a s nejméně invazivními prostředky.
- **NIS2** naopak detekci a logování bezpečnostních událostí vyžaduje – to je legitimní účel.
- Server hostuje organizace sama → **my nejsme zpracovatel** jejích dat (žádná smlouva čl. 28 s námi, data neopouštějí firmu); organizace je správce. Dodáme šablonu DPIA a informace pro zaměstnance/rodiče.

**Návrh „privacy by design“:**

1. **Detekce na PC, ne sběr provozu.** Na zařízení běží lehká analýza (jako Lux Guard:
   žádné skenování všeho, jen události): nftables/conntrack počítadla toků + DNS dotazy
   z lokálního resolveru. Na server jdou **jen bezpečnostní nálezy**: spojení na známé
   škodlivé domény/IP (threat feed, stažený do PC), skenování portů z PC, těžba kryptoměn,
   neobvykle velký upload (exfiltrace), spojení programu zablokovaného Lux Guardem, nový
   naslouchající port.
2. **Žádný obsah, žádné URL cesty, žádná TLS inspekce (MITM).** Maximálně doména + port + objem
   + název programu, a to jen u nálezu.
3. **Agregované statistiky** (objem podle aplikace/kategorie, ne podle webu) volitelně, a jen na
   úrovni zařízení; vazba na osobu (kdo byl přihlášen) se v konzoli zobrazí až po zadání důvodu
   a je auditovaná („čtyři oči“: Auditor/DPO vidí, kdo se díval).
4. **Transparentnost**: na PC v Nastavení → O počítači → „Spravováno organizací Firma s.r.o.“
   seznam: co organizace může (politiky, software, zamknutí, vymazání) a **co sbírá** (inventář,
   bezpečnostní nálezy), s odkazem na informaci zaměstnavatele. Ikona v panelu, když je
   Security Center zapnutý. Zaměstnanec vidí svoje nálezy.
5. **Výchozí stav vypnuto**; zapnutí v konzoli vyžaduje potvrzení „Zaměstnanci byli
   informováni, DPIA provedeno“ (checkbox + jméno + datum do auditu) a nastavení retence
   (výchozí 30 dní, max. 180).
6. **BYOD** (soukromé PC zaměstnance zapsané do firmy): Security Center nelze zapnout,
   inventář jen omezený. 🟡 R9.
7. Nástroj neslouží k hodnocení produktivity – žádné „čas na Facebooku“. To je i marketingový
   rozdíl proti „bossware“.

Výkon: žádné eBPF programy na každý paket; conntrack události + počítadla, zpracování
v dávkách co 60 s, cíl < 1 % CPU a < 20 MB RAM.

### 3.15 Konzole správce (Lux Admin)

- **Webová konzole** (servíruje ji `luxos-directory-server`, HTTPS): Lidé, Skupiny, Počítače,
  Politiky (LSL editor se zvýrazněním a kontrolou – sdílí kód s LSL IDE; náhled „co tato změna
  udělá na PC X“ = `lux system diff` vyhodnocený na serveru proti poslednímu inventáři),
  Software, Aktualizace (kruhy), Security Center, Audit, Nastavení organizace.
- **Desktopová aplikace `luxos-admin`** (GTK, macOS styl jako ostatní naše aplikace, zavírací
  tlačítko podle `check-titlebars.sh`): stejné API, navíc „Zapsat tento počítač“, QR s kódem
  organizace, offline práce s LSL politikami v gitu. Pro první verzi stačí web + `lux org` CLI;
  desktop později.
- **CLI** `lux org …` (pro skriptování a pro AI asistenty – LuxAI může pomoct psát politiky,
  ale jen jako návrh, který člověk schválí).
- Přihlášení do konzole: účet organizace (nebo propojený účet LuxAI) + **povinné MFA** pro každého s oprávněním `org.*`.

### 3.16 Komponenty na PC

```
luxos-org (balíček)
├── luxos-org-service     root, minimální: ověřuje podepsané balíčky politik a akce, volá
│                         lux system, LUKS/LAPS operace, userdb Varlink; NEMÁ síť
│                         (RestrictAddressFamilies=AF_UNIX), sandbox systemd
├── luxos-org-sync        uživatel `luxos-org` (bez práv): síťová komunikace se serverem
│                         (mTLS, long-poll), stahování, inventář (čte jen to, co smí);
│                         předává službě jen podepsaná data přes Unix socket
├── pam_luxos_org.so      tenký PAM modul (C)
├── lux org …             CLI (status, join, leave, sync, policy show, why)
└── luxos-hub             (už existuje) – notifikace v sezení: „Organizace nainstalovala …“,
                          „Restart za 10 minut“, zpráva od helpdesku
```

Jazyk: služba a sync v Pythonu (konzistentní s `lux_system.py`, `luxdrop`); PAM modul v C;
server v Pythonu (async) + SQLite (výchozí) / PostgreSQL (velké organizace, replika). 🟡 R13.

---

## 4. Bezpečnost

### 4.1 Model hrozeb

| Hrozba | Dopad | Opatření |
|---|---|---|
| **Ukradený notebook** (vypnutý) | data, cache hesel | LUKS (instalátor), volitelně TPM+PIN; ověřovače hesel Argon2id root-only, zapečetěné v TPM; offline platnost omezená (30 dní); revokace certifikátu → při prvním spojení zamknutí/vymazání; recovery key jen na serveru |
| Ukradený notebook (zapnutý, zamčený) | útok na zámek obrazovky | zámek přes PAM, rate-limit; USB politika; Thunderbolt/DMA – IOMMU v jádře |
| **Zlovolný správce** | špehování, malware na všech PC | role s nejmenšími právy; nebezpečné akce (vymazání, nový podpisový klíč, skripty, Security Center, nový software do všech PC) vyžadují **druhého schvalovatele**; neměnný audit viditelný Auditorovi i zaměstnancům (pro jejich PC); transparentní seznam schopností na PC |
| **Kompromitovaný server** | rozeslání škodlivé politiky všem PC | politiky podepisuje **klíč správce** (FIDO2/passkey v prohlížeči nebo hardwarový klíč), ne server; PC má veřejné klíče správců pinnuté od zápisu a odmítne politiku podepsanou jen serverem; změna seznamu klíčů musí být podepsaná existujícím klíčem Ownera (řetěz důvěry). Server sám umí jen „nízkorizikové“ akce (synchronizace, zamknutí). 🟡 R14 |
| **MITM v LAN** (falešný DC/server, ARP spoofing) | podvržená politika, odposlech hesel | vrstva 2: TLS 1.3 s pinnutou CA organizace (z kódu/QR), mTLS s certifikátem zařízení, podepsané politiky; vrstva 1: Kerberos (vzájemná autentizace), LDAP přes SASL/GSSAPI se signing+sealing, žádné NTLM; LDAPS/channel binding dle DC |
| Kompromitovaný účet uživatele | přístup k PC | MFA, rate-limit, okamžitá revokace členství, audit přihlášení |
| Lokální malware na PC chce ovládnout agenta | eskalace na root | síťová část bez práv, root část bez sítě a přijímá jen podepsaná data; žádné „spusť příkaz“ API; Lux Guard hlídá zápis do `/etc/luxos/org` a `/etc/pam.d` |
| Replay starých politik (downgrade) | návrat k slabší politice | monotónní číslo verze + čas v podepsaném balíčku; PC odmítne starší |
| Server nedostupný / zaniklý | PC nelze spravovat | vše funguje z poslední politiky; LAPS účet; `lux org leave --force` lokálním správcem |
| Únik databáze serveru | hesla, klíče | hesla na serveru jen u lokálních účtů (Argon2id); LAPS/recovery klíče šifrované klíčem, který není v DB (soubor/HSM/TPM serveru); zálohy šifrované |

### 4.2 Klíče a důvěra

```
CA organizace (offline/na serveru, chráněná)           → certifikáty zařízení (90 dní)
Klíče správců (FIDO2, ve vlastnictví lidí, ≥ 2 Owner)  → podpis balíčků politik a nebezpečných akcí
Klíč serveru                                            → podpis běžných zpráv (sync, zamknutí)
Klíč zařízení (TPM 2.0 nebo soubor 0600)               → mTLS, podpis inventáře a výsledků
Klíč repozitáře organizace                              → podpis interních balíčků (jen pro ten repozitář)
```

Pinnuté hodnoty na PC v `/etc/luxos/org/trust.json` (root 0644, změna jen podepsaným balíčkem).
Žádná důvěra v systémové CA pro komunikaci se serverem organizace.

### 4.3 Nejmenší oprávnění na PC

- Rozdělení služba (root, bez sítě) / sync (bez práv, se sítí) – viz 3.16.
- systemd hardening: `ProtectSystem=strict` s výčtem zapisovatelných cest, `NoNewPrivileges`,
  `PrivateTmp`, `SystemCallFilter=@system-service`, `CapabilityBoundingSet` jen co je nutné.
- Pevná sada akcí (enum), žádný shell, validace všech hodnot – stejný přístup jako
  `lux_system.py` (který politiku nakonec stejně aplikuje).
- LSL politiky se vyhodnocují v `lsl config` jako `nobody` (už dnes).
- **Názvy**: žádný „daemon“ – `luxos-org-service`, `luxos-org-sync`, `luxos-hub`,
  `luxos-directory-server`. Upstream jména (sssd, realmd, oddjobd) v UI neukazovat.

### 4.4 Audit

- **Server**: append-only log, každý záznam obsahuje hash předchozího (hash řetěz); kdo, kdy,
  odkud, co (diff politiky), schválení. Pravidelný „otisk“ řetězu se rozešle na PC → zpětná
  změna logu by byla vidět. Export pro SIEM (syslog/JSON).
- **PC**: `/var/lib/luxos/org/audit.jsonl` + journal `-t luxos-org` (přijaté politiky, výsledky,
  vzdálené akce, kdo se díval na LAPS heslo), historie `lux system` (20 souborů) už existuje.
- Uživatel na PC: Nastavení → Spravováno organizací → **Historie** (co organizace na tomto PC
  udělala).

### 4.5 Obnova, když server není dostupný

| Situace | Chování |
|---|---|
| Krátký výpadek | nic se neděje; přihlášení z cache; politika poslední platná |
| Dlouhý výpadek (> offline_days) | noví uživatelé se nepřihlásí; přihlášení lokálním správcem / LAPS heslem (poslední známé zná helpdesk) |
| Server zrušen / firma odchází | lokální správce: `sudo lux org leave --force` (s varováním, audit lokálně) |
| Certifikát zařízení vypršel offline | po připojení automatická obnova, pokud zařízení nebylo revokováno; jinak nový zápis |
| Ztráta klíčů správců | Owner recovery: offline záložní klíč (vytištěný QR při založení organizace) – 🟡 R14 |
| Vrstva 1, DC nedostupný | SSSD offline režim, přihlášení z cache; GPO poslední aplikované |

---

## 5. Uživatelské rozhraní (souhrn)

- **Nastavení → Uživatelé a skupiny → Firemní síť**: stav („Připojeno k firma.local, online“
  / „LuxOS Directory: Firma s.r.o.“), tlačítka Připojit / Odpojit, Synchronizovat, Zobrazit
  politiku.
- **Nastavení → O počítači**: řádek „Spravováno organizací Firma s.r.o.“ → přehled schopností,
  sbíraných dat a historie (transparentnost).
- **Přihlašovací obrazovka**: „Jiný uživatel…“, firemní dlaždice, stav online/offline, TOTP,
  zpráva organizace (banner), změna vypršelého hesla.
- **Instalátor / OEM průvodce**: „Komu počítač patří?“ → firma → doména nebo kód/QR organizace.
- **Notifikace** (`luxos-hub`): instalace softwaru, restart, zamknutí.
- Všechny UI texty anglicky + `luxos-i18n` (cs), jako zbytek LuxOS.

---

## 6. Testovací plán

Pravidla: vše v QEMU (`scripts/test-vm.sh`, `scripts/vmctl.py` přes guest agent), GUI testy jen
v Xvfb nebo ve VM, nikdy na skutečné obrazovce, žádné testy proti 185.183.156.25 ani lux-ai.cz
(pro vrstvu 2 lokální mock OIDC poskytovatele).

### 6.1 Vrstva 1 – laboratoř se Samba AD DC

- **Síť mezi VM bez root práv**: QEMU `-netdev socket,mcast=230.0.0.1:1234` (nebo
  `socket,listen/connect`) – privátní L2 segment mezi VM, druhá karta s user-mode NAT pro
  internet. DHCP/DNS dělá DC.
- **VM 1 – DC**: Samba 4.25 AD DC (`samba-tool domain provision --realm=LUXTEST.LAN
  --dns-backend=SAMBA_INTERNAL`), skript `scripts/ad-lab/provision-dc.sh` vytvoří uživatele,
  skupiny („Domain Admins“, „LuxOS Admins“, „Účtárna“), sdílení, tiskárnu (CUPS-PDF přes SMB),
  GPO s ADMX šablonami LuxOS (`samba-tool gpo` + `Registry.pol` ze skriptu).
- **VM 2 – LuxOS klient** z aktuálního ISO.
- **Před vydáním 1x ručně**: Windows Server 2022/2025 Evaluation (180 dní zdarma) – ověřit
  LDAP signing, channel binding, AES-only Kerberos, nové výchozí hodnoty bezpečnosti.

Scénáře (automatizované přes `vmctl.py`, kde to jde):

1. `lux domain discover/join` – úspěch; chybné heslo; hodiny posunuté o 10 min (nabídnutí
   synchronizace); DNS bez SRV záznamů; existující účet počítače.
2. Přihlášení doménovým účtem na greeteru (Xvfb ve VM, screenshot): první přihlášení vytvoří
   `/home/jan` ze skel; plné jméno; avatar.
3. **Offline**: odpojit síťovou kartu (`vmctl` → QMP `set_link off`), přihlášení z cache;
   chybné heslo offline; vypršení cache (posun času).
4. Vypršené heslo → změna na greeteru; zamčený účet v AD → hláška.
5. `sudo` a polkit pro „LuxOS Admins“; obyčejný uživatel nesmí; LuxOS Care „Update Now“ funguje
   pro doménového správce.
6. GPO: Deny log on locally → odmítnutí; ADMX LuxOS (zámek obrazovky 5 min, firewall, USB
   read-only) → fragment `40-domain-gpo.lsl`, `lux system diff` ukazuje původ; `--unapply`.
7. SMB sdílení v Thunaru bez hesla (Kerberos), tiskárna přes `smb://` s negotiate.
8. `lux domain leave` + `lux rollback`; aktualizace balíčků `sssd`/`glibc` nerozbije
   `nsswitch.conf` (hook).
9. Koexistence: lokální `jan` vs doménový `jan`; otisk prstu po doménovém přihlášení.

### 6.2 Vrstva 2 – více VM

- **VM S**: LuxOS v režimu server s rolí `luxos-directory-server` (a druhá varianta: OCI obraz
  v podman uvnitř Debian VM), volitelně mock OIDC (malý testovací IdP v Pythonu, simuluje
  lux-ai.cz – jen pro volitelné propojení s LuxAI), **VM A, B**: LuxOS klienti, **VM M**
  (volitelně): `mitmproxy`/ARP spoofing a **falešný mDNS server** útočníka.
- Unit testy: slučování LSL fragmentů a `mkForce`/`mkDefault`, původ hodnot, validace nových
  klíčů (`packages/lux/tests`), podpisy balíčků politik, downgrade, hash řetěz auditu.
- **Unit testy oprávnění**: tabulkové testy algoritmu 3.5 (role ✓/✗/zdědit, pořadí, přepsání
  skupiny a počítače, tvrdé ✗, hodnotová oprávnění, hierarchie správy – nelze udělit víc, než
  mám), `lux org why` vrací stejný výsledek jako server; kompilace oprávnění do syntetických
  skupin, nftables a LSL je deterministická (golden files).
- Fuzzing: parser balíčku politiky a socketový protokol PAM ↔ služba.
- **Šablony**: založení organizace z každé šablony → `lux system check` všech výsledných
  fragmentů projde; zápis PC a přihlášení každé role.
- **Vynucení na PC** (ve VM, Xvfb): Žák nemůže připojit USB pro zápis, změnit Wi-Fi, instalovat
  z Lux Store (vidí „Požádat“); webový filtr blokuje testovací doménu jen pro UID žáka, DoH
  zablokované; čas u obrazovky zamkne sezení (posun času); režim testu zapnutý a vypnutý
  učitelem; dočasný profil Hosta po odhlášení zmizí.
- **Server**: objevení přes mDNS, podvržený mDNS server (zápis bez kódu musí selhat), záloha →
  smazání VM S → obnova na nové VM → klienti pokračují; server vypnutý týden (posun času) →
  přihlášení z cache, maximální stáří politiky; aktualizace serveru s migrací DB.
- Scénáře: zápis kódem (platný/prošlý/vyčerpaný), zápis v OEM průvodci (Xvfb, `gui-oem.py`
  styl), přihlášení online/offline/po odebrání člena, TOTP, změna politiky a kruhy (A = pilot,
  B = broad), chybná politika → rollback, zamknutí do 5 s, vymazání (VM se snapshotem
  disku), LAPS, recovery key, server vypnut (cache), **MITM** (musí selhat), **politika
  podepsaná jen serverem** (musí být odmítnuta), revokace certifikátu.
- Výkon: nečinná služba na PC < 15 MB RAM, ~0 % CPU; přihlášení online < 1 s v LAN; aplikace
  prázdné politiky < 2 s.
- Před vydáním: `scripts/check-titlebars.sh` pro nové aplikace (`luxos-admin`, dialogy).

---

## 7. Etapy a odhad práce

Odhady pro jednoho vývojáře s Claude, v čistém čase; realisticky ×1.5 na ladění a dokumentaci.

| Etapa | Obsah | Odhad | Verze |
|---|---|---|---|
| **E0 – základ `lux system`** | `/etc/luxos/system.d/`, zamčené položky z org fragmentů, `--origin`, nové klíče `admins`, `lock_screen`, `usb_storage`, `luxdrop`, `browser`, `certificates` | 2–3 týdny | 1.0 |
| **E1 – vrstva 1 MVP** | realmd/adcli do `[luxos]`, `luxos-domain`, `lux domain`, sssd šablona, PAM/NSS, sudo+polkit, greeter (Jiný uživatel, offline stav, vypršené heslo), Nastavení → Firemní síť, instalátor/OEM krok, SMB+Kerberos v Souborech, AD lab skripty + testy | 4–6 týdnů | **1.0** |
| **E2 – GPO** | `samba-gpupdate` podmnožina, ADMX šablony LuxOS + CSE → LSL fragment, `lux domain gpresult`, tiskárny přes SMB | 3 týdny | 1.0 (pokud stihneme) / 1.0.x |
| **E3 – LuxOS Directory MVP** | server (role na LuxOS + OCI obraz), průvodce `lux org server init`, **šablony** (5), lidé, **role a oprávnění ve stylu Discordu** (katalog v1, přepsání pro skupiny počítačů, `lux org why`), skupiny počítačů, mDNS objevení + zápis kódem/QR, mTLS, `luxos-org-service`/`sync`, PAM + userdb, offline přihlášení, syntetické skupiny + polkit/sudo/CUPS/udisks, podepsané politiky, zálohy a obnova, inventář základní, zamknutí, webová konzole minimální, `lux org` | 3–4 měsíce | 1.1 |
| **E4 – rodina a škola** | čas u obrazovky, webový filtr (`luxos-webfilter` + nftables per UID), žádosti o aplikace, dočasné profily/kiosk, režim testu, import CSV | 6–8 týdnů | 1.1–1.2 |
| **E5 – firemní funkce** | kruhy aktualizací + cachovací zrcadlo se snímky, LAPS, LUKS recovery key, vymazání, firemní repozitář s omezeným klíčem, reporty, režim LuxOS Server v instalátoru, záložní server (replika) | 6–8 týdnů | 1.2 |
| **E6 – propojení s LuxAI (volitelné)** | propojení účtu organizace s účtem LuxAI (PKCE), SSO do aplikací LuxAI, volitelně „Přihlásit se účtem LuxAI“ (OIDC na lux-ai.cz, mimo repozitář), MFA na účtu LuxAI | 3–4 týdny | 1.2 |
| **E7 – Lux Security Center** | detekce na PC, threat feed, konzole, transparentnost, DPIA šablona pro zákazníky | 6 týdnů + právní revize | 1.3 |
| **E8 – pokročilé** | desktopová `luxos-admin`, FIDO2/passkeys, schválení na telefonu, SSO do webových aplikací (OIDC pro firemní aplikace), VPN před přihlášením, vzdálená plocha se souhlasem | průběžně | 1.3+ |

**Co je realistické v 1.0:** E0 + E1, pravděpodobně E2 (vrstva 1 – Microsoft AD – je
samostatná a hotová dřív než vlastní adresář). To samo o sobě umožní říct
„LuxOS se připojí do vaší domény Windows jako Windows PC“ – což je pro firmy první otázka.
Vrstva 2 je samostatný produkt a neměl by zdržet 1.0.

---

## 8. Rizika

| Riziko | Pravděpodobnost / dopad | Zmírnění |
|---|---|---|
| Rozsah (AD je obrovské, snadno se z toho stane nekonečný projekt) | vysoká / vysoký | přísné MVP, „ne“ seznam (skripty, vzdálený shell, poloha, Windows klienti) |
| Bezpečnostní chyba v přihlašování = kompromitace všech PC firmy | střední / kritický | malý PAM modul, logika ve službě, fuzzing, nezávislá revize kódu před 1.1, bug bounty |
| Organizace provozuje server špatně (bez záloh, neaktualizovaný, vystavený do internetu) | vysoká / vysoký | automatické šifrované zálohy s varováním, Care aktualizuje i server, výchozí poslech jen v LAN, veřejný přístup jen přes vestavěný WireGuard, kontrola stavu v konzoli („Zdraví serveru“) |
| Role ve stylu Discordu jsou mocné, ale složité (nečekané výsledky přepsání) | střední / střední | šablony s rozumnými výchozími hodnotami, `lux org why` / „Proč?“ v konzoli, náhled „zobrazit jako člen X“, tvrdé ✗ pro bezpečnostní zákazy |
| Omezení v uživatelském sezení nejsou bezpečnostní hranice (terminál, čas u obrazovky u zkušeného žáka) | vysoká / nízký | dokumentovat jako „měkká“; skutečné hranice jsou polkit, sudo, nftables a PAM |
| realmd/adcli nejsou v Arch oficiálních repozitářích, realmd se málo vyvíjí | střední / střední | vlastní balení v `[luxos]`, `lux domain` volá adcli přímo, pokud by realmd odpadl |
| Xfce nastavení nejdou spolehlivě vynutit | vysoká / střední | výchozí hodnoty + kiosk pro malou sadu; přiznat v dokumentaci; souvisí s přepisem Xfce v 1.0 |
| GDPR/zákoník práce u Security Center | střední / vysoký (pověst) | výchozí vypnuto, detekce na PC, transparentnost, právní revize před vydáním |
| Kompatibilita s novými bezpečnostními výchozími hodnotami Windows Server (LDAP channel binding, odstranění RC4, NTLM) | střední / střední | test s Windows Server Evaluation před každým velkým vydáním |
| Uživatelé čekají „GPO 1:1“ | vysoká / střední | jasně komunikovat podporovanou podmnožinu a výhody LSL |
| Udržitelnost pro jednoho vývojáře (server + klient + konzole + bezpečnost) | vysoká / vysoký | etapy, každá samostatně užitečná; vrstva 1 přináší hodnotu sama |

---

## 9. Otevřené otázky a rozhodnutí

**🟡 R1 – Pořadí:** Vrstva 1 (AD kompatibilita) v 1.0 a vrstva 2 až 1.1+?
*Doporučení: ano.* Vrstva 1 je rychlejší, ověřená technologie a odpovídá na první otázku firem.

**✅ R2 – Architektura vrstvy 2: ROZHODNUTO – self-hosted u organizace** (role na LuxOS,
LuxOS v režimu server, OCI obraz / balíček pro jiný Linux), viz 3.2. Hosted na lux-ai.cz není.

**✅ R3 – Identita: ROZHODNUTO – účty organizace na jejím serveru, účet LuxAI volitelně**
(propojení, SSO do aplikací LuxAI, případně přihlášení účtem LuxAI), viz 3.3.
🟡 Zbývá: má být „Přihlásit se účtem LuxAI“ (vyžaduje OIDC na lux-ai.cz) vůbec v plánu, nebo
stačí propojení pro SSO do aplikací? *Doporučení: nejdřív jen propojení (E6), přihlášení
účtem LuxAI až na požádání uživatelů.*

**✅ Šablony organizací a role ve stylu Discordu: ROZHODNUTO**, viz 3.4 a 3.5. 🟡 Zbývá
potvrdit: (a) pravidlo „povolení vyhrává mezi rolemi“ (Discord) + naše **tvrdé ✗** – souhlas?
(b) hodnotová oprávnění (webový filtr, čas) podle **nejvyšší role** – souhlas? (c) katalog
oprávnění v1 v 3.5 – chybí ti něco? (d) R16 – další šablony?

**🟡 R4 – Jména a kolize:** Doménoví/organizační uživatelé jako `jan` (krátké jméno) s kontrolou
kolizí, nebo vždy `jan@firma`?
*Doporučení: krátké jméno, při kolizi plné.*

**🟡 R5 – Offline přihlášení:** jak dlouho platí uložené heslo bez spojení se serverem?
*Doporučení: 30 dní výchozí, politikou 0–180.*

**🟡 R6 – Spouštění skriptů:** Povolit správcům skripty (GPO scripts, „spusť příkaz na PC“)?
*Doporučení: ne v MVP; jen deklarativní LSL a podepsané balíčky. Později možná podepsané skripty
se dvěma schváleními.*

**🟡 R7 – Přihlašování ve vrstvě 2:** vlastní tenký PAM modul + systemd userdb, nebo převzít
Himmelblau / SSSD `idp`?
*Doporučení: vlastní (heslo přímo na přihlašovací obrazovce, vazba na zařízení, rychlost);
SSSD `idp` sledovat jako budoucí alternativu.*

**🟡 R8 – Odchod z organizace:** co zůstane na PC po `lux org leave` (software, nastavení)?
*Doporučení: vše zůstane, jen se zruší zámky; výjimky označené `remove_on_leave`.*

**🟡 R9 – Hranice dohledu:** vzdálená plocha (jen se souhlasem?), poloha (ne?), BYOD (bez Security
Center?).
*Doporučení: plocha jen se souhlasem a později; poloha nikdy; BYOD omezený režim.*

**🟡 R10 – Licence a cena:** klient i server zdarma a open source (jakou licencí – GPL/AGPL?).
Případný příjem: placená podpora/instalace pro školy a firmy, certifikace partnerů.
*Doporučení: server AGPL; je to obchodní rozhodnutí.*

**🟡 R11 – Názvy:** „LuxOS Directory“ / „Lux Admin“ / `lux org` – nebo česky orientované
(„Lux Organizace“)?

**🟡 R12 – Retence dat:** přihlášení 90 dní, bezpečnostní nálezy 30 dní, audit 2 roky?

**🟡 R13 – Technologie serveru:** Python + SQLite (výchozí) / PostgreSQL (konzistence
s LuxOS, běží i na slabém stroji)? *Doporučení: ano.* A kde publikovat OCI obraz (vlastní
registr vedle repozitáře `luxos.lux-ai.cz`, nebo GitHub Container Registry)?

**🟡 R14 – Podepisování politik klíči správců (FIDO2):** povinné od začátku (bezpečnější proti
kompromitaci serveru, ale složitější UX a nutnost záložního klíče), nebo volitelné?
*Doporučení: povinné pro nebezpečné akce (software do všech PC, vymazání, změna klíčů),
běžné politiky může podepsat server – kompromis UX/bezpečnost.*

**🟡 R15 – Security Center vůbec?** Je to prodejní argument, ale i právní riziko a hodně práce.
*Doporučení: až po E5, s právní revizí; zaměřit na bezpečnost (detekce), ne na sledování lidí.*

---

## 10. Reference

- SSSD 2.11 release notes (nový `idp` provider, device flow): https://sssd.io/release-notes/sssd-2.11.0.html
- RHEL 10 – SSSD s generickým IdP (Technology Preview): https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/10/html/configuring_authentication_and_authorization_in_rhel/configuring-sssd-to-use-a-generic-identity-provider
- Samba – Group Policy na klientech, `samba-gpupdate`: https://wiki.samba.org/index.php/Group_Policy , https://man.archlinux.org/man/samba-gpupdate.8.en
- Himmelblau 3.0 (Entra ID + OIDC pro Linux): https://heise.de/-11200189
- Ubuntu authd (OIDC přihlašování): https://ubuntu.com/blog/authd-oidc-authentication-for-ubuntu-desktop-server
- systemd userdb / JSON user records: `man userdbctl`, `man nss-systemd`, https://systemd.io/USER_RECORD/
- RFC 8628 (OAuth 2.0 Device Authorization Grant)
- GDPR čl. 6, 28, 35; zákoník práce § 316; ESLP Bărbulescu v. Rumunsko (61496/08)
- Interní: `docs/luxos/system-config.md`, `docs/luxos/luxai-account.md`, `docs/luxos/installer.md`
  (OEM), `docs/luxos/care-updates.md`, `docs/luxos/guard.md`, `docs/luxos/luxdrop.md`,
  `docs/luxos/printing-scanning.md`, `docs/luxos/remote-files.md` (vše v `packages/apps/luxos-docs/`)
