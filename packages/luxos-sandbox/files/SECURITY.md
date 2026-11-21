# LuxOS Sandbox – model hrozeb

LuxOS Sandbox (`luxos-sandbox`, okno **Sandbox**) slouží ke spouštění a instalaci aplikací, kterým
nedůvěřujete. Každý uživatel má vlastní sandbox: minimální Arch Linux v
`/var/lib/luxos/sandbox/<uživatel>` (vlastník uživatel, práva `0700`), odkaz `/dev/sandbox/<uživatel>`.

Cíl: škodlivá aplikace v sandboxu nesmí číst ani měnit data uživatele, ostatní uživatele a systém,
nesmí se dostat k jeho sezení (D-Bus, X11, zvuk, klíčenka) ani do místní sítě.
Nejde o ochranu proti cílenému útoku na jádro Linuxu (viz Co izolované NENÍ).

## Architektura

| Vrstva | Co dělá |
|---|---|
| `luxos-sandbox-helper` (root, přes `pkexec`, akce `org.luxos.sandbox.create`, `auth_admin_keep`) | jen vytvoření / smazání sandboxu volajícího uživatele (`PKEXEC_UID`); `pacstrap -c -K -M` s oficiálními repozitáři Arch Linuxu (konfigurace `/usr/share/luxos/sandbox/lux.conf` převedená `lux-config`, nástroje jádra `lux-engine` jen pro běh pacstrapu pod jmény, která pacstrap očekává), odstranění setuid/setgid a file capabilities, `chown` na uživatele, atomické přejmenování na místo |
| `systemd-run --user --scope` | limity: `MemoryMax=50%`, `MemorySwapMax=1G`, `TasksMax=512`, `CPUQuota=75 % jader` |
| `pasta` (jen s `--net`) | nový síťový namespace s NAT; nikdy síť hostitele |
| `bwrap` (bubblewrap, bez setuid) | namespaces user/pid/ipc/uts/cgroup/net/mount, `--cap-drop ALL`, `--die-with-parent`, `--new-session`, seccomp, `no_new_privs` |

Vše kromě vytvoření/smazání běží **bez root práv** jako uživatel.

## Co je izolované

- **Soubory:** kořen `/` uvnitř je čerstvý tmpfs jen pro čtení; trvalé jsou pouze adresáře sandboxu
  (`/usr /etc /var /opt /srv /root /mnt` a `/home/sandbox`). Domov uživatele, `/run/user`, `/media`,
  `/sys`, soubory hostitele ani jiných uživatelů nejsou vidět. `/tmp` a `/run` jsou soukromé tmpfs.
- **Symlinkové útoky:** obsah sandboxu ovládá nedůvěryhodný kód, proto ho hostitelská strana nikdy
  neotevírá podle cest: adresáře se otevírají po komponentách s `O_NOFOLLOW` a do bwrap se předávají
  jako FD (`--bind-fd`). Body připojení leží na čerstvém tmpfs. Soubor ke spuštění (`run ./soubor`) se
  kopíruje procesem uvnitř sandboxu přes stdin – původní umístění se nikdy nepřipojí.
  Pomocník (root) staví kořen v adresáři `.build-<uživatel>`, ke kterému uživatel nemá přístup, a cesty
  k němu kontroluje (`/var/lib/luxos/sandbox` musí patřit rootovi a nebýt zapisovatelný pro jiné).
- **Procesy:** vlastní PID namespace – `/proc` ukazuje jen procesy sandboxu; `ptrace`,
  `process_vm_readv/writev`, `pidfd_getfd`, `kcmp` blokuje seccomp.
- **Práva:** žádné capabilities, `no_new_privs`, setuid soubory v sandboxu nefungují (a pomocník je
  odstraní). Jediné UID (uživatel) – „root“ při instalaci je jen namapovaný uživatel.
- **Jádro – zmenšená útočná plocha (seccomp):** zakázáno `mount` a nové mount API, `pivot_root`,
  `chroot` (kromě instalace), `setns`, vnořené user namespaces (`unshare`/`clone` s `CLONE_NEWUSER`;
  `clone3` vrací `ENOSYS`), `keyctl/add_key/request_key`, `bpf`, `perf_event_open`, `userfaultfd`,
  `io_uring_*`, `kexec_*`, moduly jádra, `open_by_handle_at`, `fanotify_init`, `syslog`, hodiny,
  `swapon`, `reboot`, `iopl/ioperm/modify_ldt`, `ioctl(TIOCSTI/TIOCLINUX)`, neobvyklé rodiny socketů
  (`AF_PACKET`, `AF_VSOCK`, Bluetooth, …); 32bitová a x32 ABI se odmítají.
- **Síť:** bez `--net` jen vlastní loopback (žádné rozhraní ven, ani abstraktní unixové sockety
  hostitele, např. `@/tmp/.X11-unix/X0`). S `--net` NAT přes `pasta` s volbami `--no-map-gw -t none
  -u none -T none -U none`; v síťovém namespace zůstane jen výchozí trasa (ostatní trasy se smažou,
  ohlášení routeru se vypnou) a zakáže se (`prohibit`) celá místní síť (RFC 1918, CGNAT 100.64/10,
  link-local, ULA, multicast), sítě přímo připojené k hostiteli včetně veřejných IPv6 prefixů LAN
  a všechny adresy hostitele – sandbox vidí jen internet. Když některý krok selže, sandbox se nespustí. DNS jde přes přesměrování `pasta` (169.254.1.53) na resolver hostitele.
- **Sezení:** žádný D-Bus (session ani system), PulseAudio/PipeWire, Wayland, X11 hostitele, SSH
  agent, klíčenka. Proměnné prostředí se mažou (`--clearenv`).
- **GUI na Waylandu (`--gui`, plocha luxwm):** aplikace nedostane soket plochy, ale vlastní naslouchající
  soket od kompozitoru (**wp-security-context-v1**, `sandbox_engine` `cz.luxos.sandbox`, `app_id` = název
  příkazu, `instance_id` = běh), připojený jako jediný `WAYLAND_DISPLAY` (`/run/luxos/runtime/wayland-0`).
  Vytvoří ho malý pomocník v C (`/usr/lib/luxos/sandbox/luxos-sandbox-wayland`); kompozitor ho zavře,
  jakmile `luxos-sandbox` skončí (čtecí konec roury `close_fd`, i při pádu). Klient tohoto soketu
  nevidí ani nebindne snímání obrazovky, data-control, seznam a správu cizích oken, virtuální vstup,
  správu výstupů, zámek, layer-shell, idle-notify a security-context (luxcomp `security.c`).
  Schránku dostane jen se zaměřením (`wl_data_device`). luxwm mu vždy kreslí záhlaví se značkou
  „Sandbox · příkaz“ (podle `app_id` od spouštěče, aplikace ji nezmění ani nevypne) a aktivace
  (xdg-activation) z okna sandboxu projde jen tehdy, když zaměření má tentýž sandbox – ani app_id
  zaměřeného okna aplikaci nepomůže. Soket luxwm IPC, sokety X11 a D-Bus hostitele v namespace nejsou.
  **X11 aplikace na Waylandu:** vlastní **Xwayland** (celá obrazovka X v jednom okně jako Xephyr) jako
  klient téhož soketu sandboxu; spustí se až s prvním spojením X11 a skončí s posledním (aplikace pro
  Wayland na něm nestojí paměť). Běží ve vlastním bwrap (jen `/usr`, bez domova, sítě, IPC a sezení,
  softwarově `-glamor off`); do sandboxu jde jen jeho X soket. Volba *důvěryhodný displej* na Waylandu
  nic nemění (sdílená paměť `wl_shm` je rychlá i tak). Okno X obrazovky má velikost a název hlavního okna
  aplikace: `luxos-sandbox` (mimo sandbox) se k Xwayland sandboxu připojí s jeho cookie jako malý klient
  protokolu X11 v Pythonu (bez Xlib, chyba spojení ho neukončí), čte jen velikost a název prvního okna
  (délky omezené, název jen tisknutelné znaky, nejvýš 120) a pošle je luxwm (`sandbox_window`). Ten mění
  jen kořenové okno Xwayland té instance; značka „Sandbox · příkaz“ zůstává od kompozitoru. Bez
  kořene (rootless) by okna X sandboxu spravoval správce oken luxwm mimo sandbox, což wlroots pro
  X server, který sám nespustil, neumí.
- **GUI v relaci X11 (`--gui`):** aplikace dostane jen socket vlastního X serveru **Xephyr** v okně
  „Sandbox – aplikace“ (`-nolisten tcp -nolisten local`, vlastní MIT cookie). Na displej plochy (`:0`)
  se nedostane, schránka se nesdílí.
- **Spojení Xephyru s plochou (X11 SECURITY):** X11 dovoluje každému *důvěryhodnému* klientovi číst
  klávesy jiných oken, snímat obrazovku a vkládat události. Xephyr zpracovává protokol X od nedůvěryhodné
  aplikace, proto:
  - běží ve **vlastním bwrap** (jen `/usr` pro čtení a `/etc/X11`, bez domova, bez sítě, bez D-Bus,
    `--cap-drop ALL`, seccomp jako aplikace, `--clearenv`); dovnitř jde jen socket displeje plochy
    a dva soubory autorizace v paměti (`memfd`, nikdy na disku);
  - k displeji plochy se připojuje s **nedůvěryhodnou autorizací** z rozšíření X serveru SECURITY
    (`XSecurityGenerateAuthorization`, `untrusted`, `timeout 0`), novou pro každé spuštění. Nikdy
    nedostane `~/.Xauthority` ani jeho položku FamilyWild (`luxos-xauth-wildcard`);
  - autorizaci drží spojení `luxos-sandbox` s displejem: při skončení sandboxu ji zruší
    (`XSecurityRevokeAuthorization`, X server odpojí všechny, kdo ji ještě používají); spadne-li
    `luxos-sandbox`, X server ji zruší sám se zavřením spojení;
  - nedůvěryhodný klient vidí jen rozšíření `BIG-REQUESTS` a `XC-MISC` (žádné `RECORD`, `XTEST`,
    `XInputExtension`, `MIT-SHM`, `XKEYBOARD`), `XQueryKeymap` vrací prázdný stav, výběr událostí na
    cizích oknech se tiše ignoruje, `XGetImage` cizího okna i celé obrazovky selže a `XSendEvent` do
    cizího okna se odmítne (`BadWindow`). Ověřuje `tests/test_x11_untrusted.py`;
  - GLX v Xephyru kreslí softwarově (Mesa, `__EGL_VENDOR_LIBRARY_FILENAMES`) – EGL NVIDIA bez `/dev`
    a `/sys` hostitele Xephyr shazoval.
  Bez rozšíření SECURITY na displeji plochy se okno sandboxu nespustí (fail closed). Xorg i Xvfb
  z `xorg-server` ho mají zapnuté, LuxOS ho v konfiguraci Xorg nevypíná.
- **Důvěryhodný displej (výjimka na přání):** nedůvěryhodný Xephyr kreslí bez `MIT-SHM` (pomaleji
  u videa a her). Pro jednotlivý příkaz lze v okně Sandbox zapnout **Důvěryhodný displej** (s varováním)
  nebo `luxos-sandbox trusted-display PŘÍKAZ on` (`~/.config/luxos/sandbox/trusted-display`). I pak jde
  o dočasnou autorizaci jen pro tento běh (úroveň `trusted`) a Xephyr zůstává v bwrap, jen sdílí IPC
  namespace kvůli `MIT-SHM`. Výchozí je vždy nedůvěryhodné spojení.
- **Výměna souborů:** jen složka `~/Sandbox`, a to pouze s `--shared` (jako `/home/sandbox/Shared`).
- **Zdroje:** limity paměti, procesů a CPU (systemd scope); bez uživatelského systemd jen varování.
- **Spouštěče na hostiteli** (`luxos-sandbox sync-launchers`; obaly příkazů v
  `~/.local/share/luxos/sandbox/bin`, položky `luxos-sandbox-app-*.desktop` v `~/.local/share/applications`):
  databáze balíků, `.desktop` soubory a ikony sandboxu se čtou bez spuštění sandboxu, ale jen přes FD
  adresářů s `O_NOFOLLOW` (žádný symlink se nenásleduje, FIFO a zařízení se přeskočí) a s limity velikosti.
  Z `.desktop` souborů sandboxu se **nikdy nepřebírá `Exec` ani jiné klíče** – jen očištěné `Name`/`Comment`
  (bez řídicích, neviditelných a obousměrných znaků) a hlavní kategorie; spouští se vždy
  `luxos-sandbox run [--gui] --net -- /usr/bin/<příkaz>`, příkaz vybraný ze seznamu souborů balíku a ověřený
  regulárním výrazem. Ikony jen jako běžný PNG (≤ 1 MiB, ≤ 1024×1024) nebo SVG (≤ 256 KiB) bez DOCTYPE/entit,
  skriptů, obsluh událostí a vnějších odkazů. Složka obalů je vždy **poslední** v `PATH` a obal nevznikne
  pro jméno, které systém už má, ani pro `sudo`, `su`, `pkexec`, `passwd`, `ssh`, `gpg`, shelly, `lux`,
  `luxos-*` apod. – program systému stejného jména vždy vyhraje. Zastaralé spouštěče se mažou jen podle
  vlastní značky (`luxos-sandbox launcher`, `X-LuxOS-Sandbox-Launcher`).

## Co izolované NENÍ (poctivě)

- **Portály na Waylandu zatím nejsou.** Sandbox nemá D-Bus, takže ani výběr souboru nebo snímek přes
  xdg-desktop-portal; soubory jen přes `~/Sandbox` (`--shared`). Aplikace v sandboxu si může nakreslit
  cokoli uvnitř svého okna (i falešný dialog) – proto je značka v záhlaví kompozitoru, ne v obsahu.

- **Chyby jádra.** Sandbox sdílí jádro s hostitelem. Zneužití chyby jádra (syscall, souborový systém,
  síťový stack, ovladač GPU) může vést k úplnému průniku. Seccomp plochu zmenšuje, ale neodstraňuje.
  Pro opravdu nebezpečný software použijte virtuální počítač.
- **Neprivilegované user namespaces** musí být v jádře povolené (bwrap bez setuid). To samo o sobě
  zvětšuje útočnou plochu jádra pro celý systém (vnořené namespaces uvnitř sandboxu ale seccomp blokuje).
- **X11 přes Xephyr:** chyba v Xephyr může útočníkovi dát kód mimo sandbox aplikace – ale jen uvnitř
  omezení Xephyru (bez domova, sítě a sezení) a s nedůvěryhodným spojením k ploše. Rozšíření SECURITY
  **nebrání `XGrabKeyboard`**: ovládnutý Xephyr si může klávesnici aktivně převzít (to, co pak píšete,
  dostane on). Je to viditelné – okno, do kterého píšete, přestane dostávat znaky a ztratí fokus;
  pasivní odposlech kláves jiných oken nejde. S **důvěryhodným displejem** (výjimka) by ovládnutý
  Xephyr mohl plochu odposlouchávat, snímat a ovládat. Aplikace v témže okně Xephyr se navzájem vidí
  (keylogging mezi nimi je možný). Bez správce oken se okna aplikací zobrazují bez dekorací.
- **Flatpak (Flathub) není LuxOS Sandbox:** aplikace Flatpak s oprávněním `x11`/`fallback-x11` dostanou
  v relaci X11 socket displeje plochy a **důvěryhodný** cookie uživatele (Flatpak ho kopíruje
  z `XAUTHORITY`) – mohou číst klávesy, snímat obrazovku a vkládat události. LuxOS Flatpak nijak
  neobaluje ani nemění jeho výchozí oprávnění (spouští se přímo `flatpak run`). Pro nedůvěryhodné
  programy s oknem používejte Sandbox.
- **Terminál:** `shell` a `run` v terminálu sdílí terminál (bez `--new-session`, aby fungovala
  Ctrl+C a job control); vkládání znaků (`TIOCSTI`) blokuje seccomp, ale aplikace může do terminálu
  posílat escape sekvence (chyby emulátoru terminálu).
- **Spouštěče a síť:** obaly a položky Launchpadu spouštějí aplikace s `--net` (jen internet; většina takto
  instalovaných aplikací ho potřebuje – AI agenti, prohlížeče, chat). Aplikace spuštěná z terminálu jménem
  příkazu sdílí terminál: příkaz, který v systému (zatím) není, spustí verzi ze sandboxu, a ta může např.
  vypsat podvržený dotaz na heslo a odeslat odpověď na internet. Proto obaly nedostanou jména nástrojů
  pro hesla a práva (`sudo`, `su`, `passwd`, `ssh`, `gpg` …) a v terminálu se při prvním spuštění za
  přihlášení vypíše, že příkaz běží v sandboxu. Heslo nikdy nezadávejte do programu ze sandboxu.
- **Sdílená složka:** vše, co aplikace zapíše do `~/Sandbox`, je nedůvěryhodné (škodlivé dokumenty,
  symlinky mířící jinam – neotevírejte je slepě na hostiteli).
- **Síť s `--net`:** sandbox může cokoli na internetu (stahovat malware, útočit na jiné servery, být
  součástí botnetu) z vaší IP adresy. DNS dotazy jdou přes resolver hostitele. Blokace LAN je řešena
  směrováním v namespace; sítě, které se na hostiteli objeví až za běhu, se nezablokují (adresy hostitele
  se čtou při spuštění) – privátní rozsahy jsou ale blokované vždy.
- **Instalace (`install`):** správce balíků Archu uvnitř sandboxu (balík `pacman` – sandbox je minimální Arch Linux, ne LuxOS) běží jako „falešný root“ v namespace s jedním UID. Změna vlastníka
  na jiné UID není možná, proto seccomp volání `chown*()` předstírá úspěch – všechny soubory patří
  uživateli, aplikace spoléhající na oddělené systémové uživatele (systémové služby, `setuid`) nebudou fungovat.
  Některé hooky (`systemd-tmpfiles`, ACL) vypíšou chyby, instalace přesto doběhne. Podpisy balíčků
  ověřuje správce balíků uvnitř podle klíčenky sandboxu (archlinux-keyring) – sandbox ji ale může sám změnit,
  takže balíčky v sandboxu jsou stejně důvěryhodné jako sandbox sám.
- **Pomocník (root):** jediná privilegovaná část. Přijímá jen `create|reset|destroy`, uživatele bere
  z `PKEXEC_UID` (UID ≥ `UID_MIN`, < 60000). `pacstrap` běží jako root nad prázdným adresářem s balíky
  z oficiálních repozitářů (podepsané, ověřené klíčenkou hostitele) – nikdy nad daty uživatele.
- **Disk:** sandbox může zaplnit disk (`/var` – sdílí oddíl se systémem); kvóty nejsou nastavené.
- **Časové kanály, Spectre a podobné** útoky postranními kanály izolace neřeší.
- **Jiné architektury:** seccomp filtr je pro x86_64 (i386/x32 volání se odmítají).

## Kontrola

Automatický test izolace (bez root): `packages/luxos-sandbox/tests/isolation-test.sh`
(domov, síť, `/proc`, ptrace, zápis mimo kořen včetně podvržených symlinků, sdílená složka, seccomp,
capabilities, `--net` bez LAN/hostitele, `--gui` jen Xephyr, limity), test nedůvěryhodného spojení
Xephyru s plochou `packages/luxos-sandbox/tests/test_x11_untrusted.py` (jen Xvfb: sonda `x11-probe.c` na
místě Xephyru zkouší odposlech, snímky a vkládání do důvěryhodného okna; na staré cestě s cookie uživatele
test selže), test oken na Waylandu `packages/luxos-sandbox/tests/test_wayland.py` (headless luxwm: globaly,
bind podle čísla, sokety v namespace, schránka bez zaměření, krádež zaměření, značka, vstup, X11 přes Xwayland
sandboxu) a test spouštěčů
`packages/luxos-sandbox/tests/test_launchers.py` (podvržené `.desktop` soubory, ikony a symlinky,
zastaralé spouštěče, pořadí v `PATH`).
