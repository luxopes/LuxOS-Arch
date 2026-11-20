# libluxcomp – API jádra kompozitoru (LuxOS 1.1.0)

`libluxcomp.so.0` je tenké jádro kompozitoru v C na wlroots 0.20 (architektura R2 v
`docs/proposals/wayland-desktop-1.1.0.md`). Jádro vlastní všechny objekty wlroots a kreslí.
O oknech nerozhoduje. Umístění, zaměření, plochy, klávesové zkratky a dekorace řídí program nad
knihovnou: `luxwm` v LSL. Hlavička je `packages/luxcomp/include/luxcomp.h` (verze API
`LUXCOMP_API_VERSION` = 1), balík `packages/luxcomp`.

```
klienti Wayland ──► libluxcomp (C: wlroots, scéna, vstup, renderer, dekorace, animace)
                         │  události: jeden callback (user, event, id, a, b, c)
                         ▼
                    luxwm (LSL: politika)  ──►  volání luxcomp_* (jen čísla a řetězce)
```

## Pravidla rozhraní

Rozhraní je navržené pro FFI LSL (`# lsl: internal-abi`, `__lsl_qbe_callN`, trampolína
`lsl_arch_callback` s `user_data` na prvním místě):

- **Jen celá čísla (`int64_t`), řetězce (`const char *`) a jeden ukazatel `user`.** Přes hranici
  nejde žádná struktura, takže LSL nepotřebuje znát rozložení struktur wlroots (mezera L2).
- **Objekty jsou čísla.** Výstup, okno, plocha i zkratka mají `id > 0`. Id se nikdy znovu
  nepoužije. Funkce s neplatným id nic neudělá a vrátí 0. Zastaralé id z LSL proto nemůže
  sáhnout do uvolněné paměti.
- **Jeden callback na všechny události:**
  `void fn(void *user, int64_t event, int64_t id, int64_t a, int64_t b, int64_t c)`.
  To je 6 argumentů, víc trampolína LSL neumí. Stačí jediný záznam callbacku, takže LSL nemusí
  záznamy uvolňovat (mezera L4). Žádný `wl_listener` neleží na straně LSL (mezera L3).
- **Vše běží v hlavním vlákně.** Callback se volá jen uvnitř `luxcomp_dispatch()` nebo
  `luxcomp_run()`.
- **Vrácené řetězce** (`luxcomp_view_title()` apod.) platí do dalšího `luxcomp_dispatch()` nebo
  do zničení objektu. Kdo je potřebuje déle, musí si je zkopírovat.
- **Nic se nevolá každý snímek.** Animace (přejezd ploch) a interaktivní přesun nebo změna
  velikosti běží v C. LSL dostává jen řídké události: nové okno, klik, zkratka, konec animace.
  GC v LSL tak nikdy nebrzdí vykreslování (mezera L6).

## Smyčka událostí

```c
luxcomp_init(on_event, user);      // 0 = ok; vytvoří socket a nastaví WAYLAND_DISPLAY
/* ... luxcomp_workspace_new(), luxcomp_bind_key(), luxcomp_theme_set() ... */
luxcomp_start();                   // spustí backend (DRM, headless, x11 ve vnořeném režimu)
// buď:
luxcomp_run();                     // do luxcomp_quit()
// nebo s vlastní smyčkou (GLib v LSL):
//   glib.unix_fd_add(luxcomp_fd(), ...) a v obsluze luxcomp_dispatch(0)
luxcomp_destroy();
```

`luxcomp_dispatch()` vrací záporné číslo po `luxcomp_quit()` nebo při chybě. Klienty spouští
`luxcomp_spawn(cmd)` (`sh -c`, dvojitý fork, nezůstanou zombie).

## Události

| Událost | id | a, b, c |
|---|---|---|
| `OUTPUT_ADD` | výstup | šířka, výška |
| `OUTPUT_REMOVE` | výstup | |
| `OUTPUT_USABLE` | výstup | změnila se použitelná plocha (exkluzivní zóny lišty a Docku) |
| `VIEW_NEW` | okno | rodič (dialog) nebo 0 |
| `VIEW_MAP` | okno | šířka, výška; teď okno umístit, zaměřit, zvednout |
| `VIEW_UNMAP` | okno | |
| `VIEW_DESTROY` | okno | id potom už neplatí |
| `VIEW_TITLE`, `VIEW_APP_ID` | okno | změnil se název nebo app_id |
| `VIEW_REQUEST` | okno | `LUXCOMP_REQ_*` a argument (viz níže) |
| `BUTTON` | okno nebo 0 | tlačítko (kód Linuxu, 272 = levé), 1 stisk / 0 uvolnění, `LUXCOMP_PART_*` |
| `KEYBIND` | zkratka | |
| `MODS_RELEASED` | | po zkratce se pustily všechny modifikátory (konec Alt+Tab) |
| `SLIDE_DONE` | plocha | přejezd skončil, plocha je vidět |
| `LOCK` | | a = 1 zamčeno, 0 odemčeno; b = 1 zamykač skončil bez odemčení (zůstává zamčeno) |

Požadavky (`VIEW_REQUEST`): `MOVE` (tah za zahlaví CSD), `RESIZE` (b = okraje
`LUXCOMP_EDGE_*`), `MAXIMIZE` a `FULLSCREEN` (b = 1/0), `MINIMIZE` (b = 1 minimalizovat,
0 obnovit), `ACTIVATE`, `DECORATION` (b = 1 okno chce zahlaví od kompozitoru) a `CLOSE`.
Jádro na požadavek vždy odpoví configure. Politika rozhodne, co udělá.

Kdo žádá (`LUXCOMP_ORIGIN_*`): u `MAXIMIZE`, `FULLSCREEN`, `MINIMIZE` a `CLOSE` je to c, u
`ACTIVATE` b:
- `CLIENT` (0): okno samo. U `ACTIVATE` to znamená žádný platný token.
- `VIEW`: jen `ACTIVATE`. Token xdg-activation vytvořil povrch okna c, navázaný na vstup
  uživatele. Sériové číslo a to, že povrch měl zaměření, ověří wlroots. Politika ještě
  porovná okno c se zaměřeným oknem.
- `SHELL`: jen `ACTIVATE`. Token vytvořil povrch layer-shell (Dock, spouštěč) nebo
  `luxcomp_spawn()`, který ho předá v `XDG_ACTIVATION_TOKEN` a `DESKTOP_STARTUP_ID`.
- `TASKBAR`: wlr-foreign-toplevel-management, tedy Dock nebo jiný klient z allowlistu.

luxwm povolí aktivaci jiné aplikace jen s původem `VIEW` od zaměřené aplikace, `SHELL` nebo
`TASKBAR`. Pak přepne na plochu okna a zaměří ho (xfwm4 `activate_action=switch`).

Části okna (`BUTTON`, c): `NONE` (prázdná plocha), `CLIENT`, `TITLE`, `CLOSE`, `MINIMIZE`,
`MAXIMIZE` (semafor v zahlaví od kompozitoru), `LAYER` (lišta, Dock a jiný povrch layer-shell).
Klik se klientovi předá vždy, když je pod kurzorem jeho povrch. Klik do zahlaví klient nedostane.

## Funkce

**Výstupy.** `luxcomp_output_get(id, LUXCOMP_OUT_*)` vrací X, Y, W, H, `USABLE_*` (bez
exkluzivních zón), `REFRESH_MHZ` a `SCALE_PCT`. Další funkce: `luxcomp_output_name(id)`,
`luxcomp_output_at(x, y)`, `luxcomp_cursor_x()` a `luxcomp_cursor_y()`.

**Okna.** `luxcomp_view_get(id, LUXCOMP_VIEW_*)` vrací:
- X, Y, W, H: obsah okna (geometrie klienta) v souřadnicích rozložení.
- `DECO_TOP`: výška zahlaví od kompozitoru, 0 = žádné.
- `OUTPUT`, `WORKSPACE`, `PARENT`.
- `MAPPED`, `VISIBLE`, `FOCUSED`, `FULLSCREEN`, `MAXIMIZED`, `LAYER`.
- `MIN_*` a `MAX_*` (velikostní meze klienta) a `PID`.
- `X11`: 1 = okno X11 přes XWayland. Jeho app_id je `WM_CLASS` (třída), název `_NET_WM_NAME`.

Okna v pořadí od nejvyššího projde `luxcomp_view_next(0)`, `luxcomp_view_next(id)` … až po 0.

Akce:

| Funkce | Co dělá |
|---|---|
| `luxcomp_view_move(id, x, y)` | posune okno, x a y je levý horní roh obsahu |
| `luxcomp_view_resize(id, w, h)` | configure; 0, 0 = velikost zvolí klient |
| `luxcomp_view_focus(id)` | klávesnice a stav activated; 0 = nikdo |
| `luxcomp_view_raise(id)` | zvedne okno nahoru |
| `luxcomp_view_set_state(id, FULLSCREEN\|MAXIMIZED\|TILED, on)` | nastaví stav xdg-toplevel; geometrii nastaví politika |
| `luxcomp_view_set_layer(id, NORMAL\|ABOVE\|FULLSCREEN)` | vrstva okna; `FULLSCREEN` je nad listou |
| `luxcomp_view_set_workspace(id, ws)` | přesune okno na plochu |
| `luxcomp_view_set_decorated(id, on)` | zahlaví LuxOS od kompozitoru, nebo CSD |
| `luxcomp_view_set_visible(id, on)` | 0 = minimalizace |
| `luxcomp_view_close(id)` | požádá klienta o zavření |
| `luxcomp_view_begin_move(id)`, `luxcomp_view_begin_resize(id, edges)` | tah myší v C do uvolnění tlačítka |

Vrstvy od spodu: tapeta (layer-shell background), bottom, okna `NORMAL` (stromy ploch),
`ABOVE`, lišta (layer-shell top), `FULLSCREEN`, overlay. Celoobrazovkové okno nad listou je
tedy jen `set_layer(FULLSCREEN)`. O tom, kdy ho vrátit pod listu (např. když zaměření převezme
jiné okno), rozhoduje politika. Viz `luxos-fullscreen-layer.patch` u xfwm4.

**Plochy.** `luxcomp_workspace_new()` vytvoří plochu. První plocha je vidět, další ne.
`luxcomp_workspace_show(ws, on)` plochu ukáže nebo schová.

`luxcomp_workspace_slide(from, to, dir, ms)` je přejezd jako Spaces v macOS:
- `dir` 1 = nová plocha přijede zprava, −1 = zleva.
- Křivka je `ease` (cubic-bezier 0.25, 0.1, 0.25, 1). Krok je po každém vykresleném snímku
  výstupu.
- Lišta, Dock, tapeta a okna mimo vrstvu `NORMAL` stojí.
- Nový přejezd během běžícího naváže z aktuální polohy. Zpětný směr plynule obrátí.
- Když vykreslení dvou snímků po sobě trvá přes 8 ms, přejezd skočí na konec (raději skok než
  trhaná animace). Stejně tak při `ms <= 0`, třeba pro „omezit pohyb“.
- Na konci přijde `SLIDE_DONE`.

**Vstup.**
- `luxcomp_set_keymap(layout, variant, options)`: hodnoty jako v localed (`X11Layout` atd.).
  Špatné rozložení spadne na výchozí, nikdy nezůstane systém bez klávesnice.
- `luxcomp_set_repeat(rate, delay)`.
- `luxcomp_bind_key(mods, key)`:
  - `mods` je `LUXCOMP_MOD_*` (Shift 1, Ctrl 4, Alt 8, Super 64).
  - `key` je název keysym xkb (`"Tab"`, `"Left"`, `"F4"`). Hledá se v aktuálním i prvním
    rozložení, takže zkratky s latinkou fungují i v českém nebo ruském rozložení.
  - `key` může být také `"code:N"` pro fyzickou klávesu (xkb keycode; `code:49` je klávesa pod
    Esc, tedy Alt+\` v každém rozložení).
  - Klávesu zkratky klient nedostane, ani její uvolnění.
- `luxcomp_unbind_key(id)`, `luxcomp_modifiers()`.

**Dekorace.** `luxcomp_theme_set(LUXCOMP_THEME_*, hodnota)` nastavuje:
- výšku zahlaví, poloměr rohů, velikost a mezery tlačítek;
- barvy `0xAARRGGBB`: pozadí a text aktivního i neaktivního okna, semafor, tlačítka neaktivního
  okna a oddělovač.

`luxcomp_theme_set_font("Inter Semi-Bold 10")` nastaví písmo. Výchozí hodnoty jsou světlý vzhled
LuxOS. Tmavý režim a tokeny návrhu (WP-4) nastaví luxwm těmito voláními, v jádře nejsou žádné
soubory s tématem.

Ostatní: `luxcomp_set_background(argb)` (jednolitá barva pod tapetou) a
`luxcomp_software_rendering()` (1 = pixman; politika může vypnout drahé efekty).

**Allowlist, XWayland, zámek.**
- `luxcomp_privileged_allow(cesta)` přidá program do allowlistu. NULL allowlist vyprázdní.
  Viz [Privilegované protokoly](#privilegované-protokoly).
- `luxcomp_xwayland_start()` zapne XWayland na požádání. Viz [XWayland](#xwayland).
  `luxcomp_xwayland_display()` vrací `":N"`, `luxcomp_xwayland_running()` 1, dokud X server běží.
- `luxcomp_locked()` vrací 1 při zámku, i když zamykač mezitím skončil.

## Protokoly shellu

Na stejné protokoly se píšou klienti shellu (`packages/luxos-desktop/files/src/luxos-wl`) proti
labwc. `test_luxos_wl.py` je spouští proti oběma kompozitorům.

| Protokol | V jádře |
|---|---|
| ext-foreign-toplevel-list-v1, wlr-foreign-toplevel-management-v1 | Handle existují, dokud je okno namapované. Stav (activated, minimized, maximized, fullscreen), název, app_id, výstup a rodiče hlásí jádro samo. Požadavky Docku jdou politice s původem `TASKBAR`. |
| ext-image-capture-source-v1 (výstup i okno), ext-image-copy-capture-v1, wlr-screencopy | Snímek okna je jen obsah okna, bez zahlaví. Jeden zdroj na okno, zanikne s oknem. |
| ext-data-control-v1, wlr-data-control | Schránka pro historii schránky a testy. |
| xdg-activation-v1 | Viz původ `ACTIVATE` výše. |
| ext-session-lock-v1 | Při zamčení jádro hned zakryje celou scénu neprůhlednou plochou v barvě pozadí LuxOS (`luxcomp_set_background`). `locked` pošle až poté, co tu plochu vykreslily všechny výstupy. Zamykací plochy (jedna na výstup) leží nad ní. Klávesnici, ukazatel ani zkratky nedostane nic jiného. Když zamykač skončí bez `unlock_and_destroy` (pád, kill), zůstane zakryto a zamčeno, dokud nový zamykač neodemkne. Nová okna pod zámkem se namapují, ale nejsou vidět a nedostanou klávesnici. |
| ext-idle-notify-v1 | Aktivitu hlásí každá klávesa, pohyb, klik i kolečko, také z virtuálního vstupu. |
| idle-inhibit-v1 | Brání nečinnosti, jen dokud je povrch vidět: okno na zobrazené ploše a ne minimalizované, nebo vrstva. Video na jiné ploše tedy uspání nebrání. |
| wlr-output-management-v1 | Viz výše. |
| virtual-keyboard-v1, wlr-virtual-pointer-v1 | Psaní shellu a testy. |

## Privilegované protokoly

Privilegované globaly jsou:
- snímání obrazovky: wlr-screencopy, ext-image-copy-capture a oba zdroje ext-image-capture-source;
- schránka: ext- a wlr-data-control;
- správa cizích oken: wlr-foreign-toplevel-management a ext-foreign-toplevel-list;
- virtuální klávesnice a ukazatel;
- wlr-output-management;
- ext-session-lock.

Jádro je nabídne a dovolí bindnout (`wl_display_set_global_filter`) jen takto:

1. **Klient přes soket wp-security-context-v1 je nedostane nikdy.** Sandboxované aplikace
   (flatpak, bwrap, WP-14) se připojují přes soket od svého správce. Nedostanou ani
   layer-shell (falešná zamykací obrazovka nebo lišta), ext-idle-notify (časování aktivity
   uživatele) a samotný security-context-manager (vnořené kontexty).
2. **Ostatní klienti je dostanou, jen když je jejich program v allowlistu.** Program se zjistí
   z `/proc/PID/exe`, PID z pověření soketu (`SO_PEERCRED`) při připojení. luxwm čte allowlist
   z `/usr/share/luxwm/privileged.conf` (absolutní cesty po řádcích), v testech z
   `LUXWM_PRIVILEGED`. Uživatelský soubor záměrně neexistuje.
3. `LUXCOMP_VIRTUAL_INPUT=1` otevře virtuální vstup všem klientům mimo sandbox (testy).

Kompromisy:
- **Není to hranice proti nativnímu kódu téhož uživatele.** Takový proces může programu
  z allowlistu přes `LD_PRELOAD` nebo ptrace podstrčit vlastní kód, přepsat
  `~/.config/luxwm`, nebo rovnou číst paměť sezení. Allowlist chrání před aplikacemi
  v sandboxu a před tím, aby libovolný program bez námahy snímal obrazovku, četl schránku
  nebo psal do cizích oken. Tvrdou hranicí je security-context.
- **Zmatený zástupce.** Program z allowlistu spuštěný s cizími argumenty (např. `grim
  soubor.png`) udělá snímek pro toho, kdo ho spustil. Proto v allowlistu patří jen shell
  LuxOS. Nástroje jako grim jen tam, kde je to potřeba (testy, aplikace pro snímky). Nikdy
  ne interprety (`/usr/bin/python3`, `sh`), to by povolilo každý skript.
- **PID a exec.** PID drží jádro z doby připojení. Proces může po připojení provést `exec`
  jiného programu se zděděným soketem. Kontroluje se program v okamžiku bindu, tedy ten,
  který právě běží. Program mimo allowlist proto nemůže použít soket allowlistovaného, ale
  allowlistovaný program zděděný soket použít může (zase zmatený zástupce).
- **Aktualizace balíku.** Běžící lišta má po aktualizaci `exe` s příponou `" (deleted)"`.
  Přípona se ignoruje, cesta je pořád ta systémová.
- XWayland je pro jádro jeden klient. **X11 aplikace mezi sebou nic nedělí:** mohou snímat
  okna jiných X11 aplikací a číst jejich vstup. Wayland okna a obrazovku nevidí.

## XWayland

`luxcomp_xwayland_start()` vytvoří XWayland wlroots s `lazy=true`:
- Socket `/tmp/.X11-unix/XN` a `DISPLAY` existují hned. `DISPLAY` dědí programy z
  `luxcomp_spawn()`.
- Xwayland se spustí až s prvním X11 klientem a skončí 10 s po posledním.
- luxwm ho zapne podle `xwayland = yes` v luxwm.conf (výchozí).

Spravovaná X11 okna jsou obyčejné `struct view`. Politika tedy dostane stejné `VIEW_*` a
použije stejné umístění, zaměření, Alt+Tab a zahlaví LuxOS:
- Zahlaví vypne `_MOTIF_WM_HINTS` (`REQ_DECORATION` 0).
- Poloha jde X klientovi přes configure.
- Velikost si klient volí sám.

Okna override-redirect (menu, tooltipy) politika nevidí. Leží ve vlastním stromu nad okny na
své X poloze.

Při softwarovém renderování jádro spouští Xwayland přes `/usr/lib/luxcomp/xwayland-sw`
(`-glamor off`; skutečná binárka v `LUXCOMP_XWAYLAND`, jinak `/usr/bin/Xwayland`). Glamor by
jinak načetl EGL a Mesu a stejně spadl na sdílenou paměť. `XWAYLAND_NO_GLAMOR` načtení EGL
nezabrání. Naměřeno headless (pixman, xeyes): PSS Xwaylandu 71,9 MB s glamorem a 25,8 MB bez
něj. luxwm sám ~17,8 MB s XWaylandem i bez něj.

## Renderer

Jádro samo vybere renderer, který funguje všude:
- **gles2** se zkouší jen tehdy, když existuje render node a GPU umí 3D. Při virtio-gpu bez
  virgl, vmwgfx bez 3D nebo jen s llvmpipe (gles2 selže) se použije **pixman** a softwarový
  kurzor.
- `WLR_RENDERER` má přednost, ale při selhání také spadne na pixman.
- Volba je vždy v logu: `luxcomp: renderer pixman + software cursor (no DRM render node)`.

## Výstupy pro klienty

Jádro nabízí `wlr-output-management-v1`: `wlr-randr` vypíše výstupy a nastaví režim (i vlastní
velikost u headless a vnořeného backendu), polohu a měřítko. Harness `scripts/wl-test` přes něj
zjišťuje, že kompozitor běží, a nastavuje `--size`. Po změně velikosti přijde `OUTPUT_USABLE`.

## Proměnné prostředí

| Proměnná | Význam |
|---|---|
| `LUXCOMP_DEBUG` | ladicí log wlroots |
| `LUXCOMP_STATS` | po každém přejezdu ploch počet snímků a nejpomalejší vykreslení |
| `LUXCOMP_OUTPUT_MODE=1920x1080` | velikost výstupu bez režimů (headless, vnořené okno) |
| `LUXCOMP_VIRTUAL_INPUT=1` | virtual-keyboard-v1 a wlr-virtual-pointer-v1 pro každého klienta mimo sandbox (vstup z testů `scripts/wl-test`); bez ní jen pro allowlist |
| `LUXCOMP_XWAYLAND_WRAPPER` | jiná cesta k `xwayland-sw` (testy ze stromu zdrojů) |
| `WLR_XWAYLAND` | binárka Xwayland (wlroots), harness ji nastaví na sysroot |
| `WLR_*` | jako ve wlroots (`WLR_BACKENDS`, `WLR_RENDERER`…) |

## Testy

`packages/luxcomp/tests/run.sh` všechno spouští v kontejneru, nikdy na skutečné obrazovce:
- **headless pixman 1920×1080** (`scenario.sh`): umístění, testovací lišta layer-shell,
  celoobrazovkové okno nad listou, přejezd ploch a obrácení, PSS;
- **vnořený backend x11 v soukromém Xvfb** (`nested.sh`, `input.sh`): klik, přesun za zahlaví,
  zavření semaforem, Alt+Tab, Ctrl+šipky a psaní do zaměřeného okna přes xdotool.

Protokoly shellu se testují přes luxwm:
- `packages/luxwm/tests/test_luxwm_protocols.py`: Dock, xdg-activation, zámek, allowlist a XWayland;
- `packages/luxos-desktop/tests/test_luxos_wl.py`: stejná sada pro luxwm i labwc.

`luxcomp-demo` (`tests/demo.c`) je nejmenší politika v C. Slouží jen k testům, skutečná politika
bude luxwm v LSL. Testy jsou dočasně tady, dokud nebude hotový harness WP-1 (`scripts/wl-test`).

## Zatím chybí (další etapy)

- X11: přechod okna mezi override-redirect a spravovaným. Spravovaná okna typu menu, tooltip
  nebo DnD politika zatím umisťuje jako běžná okna. `_NET_WM_STRUT` doků X11 se
  ignoruje. Pořadí zásobníku X (restack) se posílá jen při zvednutí.
- Velikost zamykacích ploch po změně režimu výstupu během zámku. Configure jde jen při
  vytvoření.
- Popupy u okrajů více výstupů a škálování zahlaví na HiDPI. Zahlaví se zatím kreslí v měřítku 1.
- Přejezd ploch na více monitorech posouvá strom plochy o šířku monitoru pod kurzorem.
  Samostatný posun pro každý monitor zatím chybí.
- Navázání rychlosti při přerušeném přejezdu. Navazuje se poloha, rychlost zatím ne.
- IPC pro shell, `org.freedesktop.a11y.KeyboardMonitor`, blur a režim greeteru.
- Hlídání sériových čísel u `REQ_MOVE`/`REQ_RESIZE`. Teď stačí, že politika tah spustí jen pro
  okno pod kurzorem.
