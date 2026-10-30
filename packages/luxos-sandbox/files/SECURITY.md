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
  -u none -T none -U none`; v síťovém namespace se navíc zakáže (`prohibit`) celá místní síť
  (RFC 1918, CGNAT 100.64/10, link-local, ULA, multicast) a všechny adresy hostitele – sandbox vidí jen
  internet. DNS jde přes přesměrování `pasta` (169.254.1.53) na resolver hostitele.
- **Sezení:** žádný D-Bus (session ani system), PulseAudio/PipeWire, Wayland, X11 hostitele, SSH
  agent, klíčenka. Proměnné prostředí se mažou (`--clearenv`).
- **GUI (`--gui`):** aplikace dostane jen socket vlastního X serveru **Xephyr** v okně
  „Sandbox – aplikace“ (`-nolisten tcp -nolisten local`, vlastní MIT cookie). Na displej plochy (`:0`)
  se nedostane, schránka se nesdílí.
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

- **Chyby jádra.** Sandbox sdílí jádro s hostitelem. Zneužití chyby jádra (syscall, souborový systém,
  síťový stack, ovladač GPU) může vést k úplnému průniku. Seccomp plochu zmenšuje, ale neodstraňuje.
  Pro opravdu nebezpečný software použijte virtuální počítač.
- **Neprivilegované user namespaces** musí být v jádře povolené (bwrap bez setuid). To samo o sobě
  zvětšuje útočnou plochu jádra pro celý systém (vnořené namespaces uvnitř sandboxu ale seccomp blokuje).
- **X11 přes Xephyr:** Xephyr je X server běžící jako uživatel na ploše; chyba v Xephyr může útočníkovi
  dát kód s právy uživatele mimo sandbox. Aplikace v témže okně Xephyr se navzájem vidí (keylogging
  mezi nimi je možný). Bez správce oken se okna aplikací zobrazují bez dekorací.
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
capabilities, `--net` bez LAN/hostitele, `--gui` jen Xephyr, limity) a test spouštěčů
`packages/luxos-sandbox/tests/test_launchers.py` (podvržené `.desktop` soubory, ikony a symlinky,
zastaralé spouštěče, pořadí v `PATH`).
