# libluxcomp – API jádra kompozitoru (LuxOS 1.1.0)

`libluxcomp.so.0` je tenké jádro kompozitoru v C na wlroots 0.20 (architektura R2 v
`docs/proposals/wayland-desktop-1.1.0.md`). Jádro vlastní všechny objekty wlroots a kreslí.
O oknech nerozhoduje. Umístění, zaměření, plochy, klávesové zkratky a dekorace řídí program nad
knihovnou: `luxwm` v LSL. Hlavička je `packages/luxcomp/include/luxcomp.h` (verze API
`LUXCOMP_API_VERSION` = 9: 3 přidala stíny, kurzor a znaky semaforu, 4 IPC a rozložení klávesnice,
5 sandbox oken a štítek záhlaví, 6 monitory (testovací výstupy, zrcadlení, hlavní monitor), stín
a zaoblení oken s vlastním záhlavím a `org_kde_kwin_server_decoration`, 7 událost `VIEW_SIZE`
a `luxcomp_view_set_names()`, 8 material (rozmazané pozadí ploch layer-shell), 9 myš a touchpad přes libinput), balík `packages/luxcomp`.

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
| `VIEW_SIZE` | okno | šířka, výška; klient sám změnil velikost (ne během tažení myší, to končí uvolněním tlačítka) |
| `VIEW_REQUEST` | okno | `LUXCOMP_REQ_*` a argument (viz níže) |
| `BUTTON` | okno nebo 0 | tlačítko (kód Linuxu, 272 = levé), 1 stisk / 0 uvolnění, `LUXCOMP_PART_*` |
| `KEYBIND` | zkratka | |
| `MODS_RELEASED` | | po zkratce se pustily všechny modifikátory (konec Alt+Tab) |
| `SLIDE_DONE` | plocha | přejezd skončil, plocha je vidět |
| `LOCK` | | a = 1 zamčeno, 0 odemčeno; b = 1 zamykač skončil bez odemčení (zůstává zamčeno) |

Požadavky (`VIEW_REQUEST`): `MOVE` (tah za zahlaví CSD), `RESIZE` (b = okraje
`LUXCOMP_EDGE_*`), `MAXIMIZE` a `FULLSCREEN` (b = 1/0), `MINIMIZE` (b = 1 minimalizovat,
0 obnovit), `ACTIVATE`, `DECORATION` (b = 1 okno chce zahlaví od kompozitoru, 0 vlastní, také když
zruší objekt xdg-decoration) a `CLOSE`.
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
`TASKBAR`. Okna sandboxu (`SANDBOXED`) jsou „stejná aplikace“ jen v rámci téže instance sandboxu,
takže okno sandboxu se aktivuje jen se zaměřením tohoto sandboxu. Pak přepne na plochu okna a zaměří ho (xfwm4 `activate_action=switch`).

Části okna (`BUTTON`, c): `NONE` (prázdná plocha), `CLIENT`, `TITLE`, `CLOSE`, `MINIMIZE`,
`MAXIMIZE` (semafor v zahlaví od kompozitoru), `LAYER` (lišta, Dock a jiný povrch layer-shell).
Klik se klientovi předá vždy, když je pod kurzorem jeho povrch. Klik do zahlaví klient nedostane.

## Funkce

**Výstupy.** `luxcomp_output_get(id, LUXCOMP_OUT_*)` vrací X, Y, W, H, `USABLE_*` (bez
exkluzivních zón), `REFRESH_MHZ` a `SCALE_PCT`. Další funkce: `luxcomp_output_name(id)`,
`luxcomp_output_at(x, y)`, `luxcomp_cursor_x()` a `luxcomp_cursor_y()`.
Jen pro testy: `luxcomp_test_output_add(w, h)` připojí headless výstup (vrací id, 0 bez headless
backendu) a `luxcomp_test_output_remove(id)` ho odpojí; skutečné výstupy (DRM) to nezmění.

**Okna.** `luxcomp_view_get(id, LUXCOMP_VIEW_*)` vrací:
- X, Y, W, H: obsah okna (geometrie klienta) v souřadnicích rozložení.
- `DECO_TOP`: výška zahlaví od kompozitoru, 0 = žádné.
- `OUTPUT`, `WORKSPACE`, `PARENT`.
- `MAPPED`, `VISIBLE`, `FOCUSED`, `FULLSCREEN`, `MAXIMIZED`, `LAYER`.
- `MIN_*` a `MAX_*` (velikostní meze klienta) a `PID`.
- `X11`: 1 = okno X11 přes XWayland. Jeho app_id je `WM_CLASS` (třída), název `_NET_WM_NAME`.
- `SANDBOXED`: 1 = klient soketu wp-security-context (sandbox aplikací). Metadata kontextu vrací
  `luxcomp_view_sandbox_engine()`, `luxcomp_view_sandbox_app_id()` a `luxcomp_view_sandbox_instance()`
  (`""` mimo sandbox). Nastavuje je správce sandboxu, ne aplikace, takže jsou důvěryhodná; app_id okna
  (`luxcomp_view_app_id()`) si aplikace volí sama.

`luxcomp_view_set_badge(id, text)` nakreslí krátký tlumený štítek u pravého okraje záhlaví od
kompozitoru (luxwm: „Sandbox · příkaz“ u oken sandboxu), `""` ho odebere.

`luxcomp_view_set_names(id, app_id, title)` přepíše app_id a název, které vidí záhlaví, Dock
(foreign-toplevel) i `luxcomp_view_app_id()`/`luxcomp_view_title()`; `""` vrátí hodnotu klienta.
luxwm tak ukazuje u kořenového okna Xwayland sandboxu („Xwayland on :0“) aplikaci ze sandboxu.

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

**IPC pro shell** (`lib/ipc.c`, protokol v `docs/developers/luxwm-ipc.md`):
- `luxcomp_ipc_listen(cesta)` otevře soket (0600). Spojení od jiného uid jádro zavře (`SO_PEERCRED`).
- Události `IPC_CONNECT` (`id` klient, `a` pid, `b` 1 = program z allowlistu), `IPC_LINE`
  (`luxcomp_ipc_line(id)`), `IPC_CLOSE`.
- `luxcomp_ipc_send(id, řádek)` přidá konec řádku; 0 = klient zmizel (pak `IPC_CLOSE` nepřijde).
  `luxcomp_ipc_close(id)`.

**Vstup.**
- `luxcomp_set_keymap(layout, variant, options)`: hodnoty jako v localed (`X11Layout` atd.).
  Špatné rozložení spadne na výchozí, nikdy nezůstane systém bez klávesnice.
- `luxcomp_set_layout(i)`, `luxcomp_layout()`, `luxcomp_layout_count()`, `luxcomp_layout_name(i)`:
  aktivní rozložení je jedno pro všechny klávesnice. Přepnutí volbou XKB `grp:` na fyzické klávesnici
  pošle `LAYOUT` (`a` = index); po `set_layout`/`set_keymap` událost nepřijde.
- `luxcomp_set_repeat(rate, delay)`.
- Myš a touchpad (zařízení libinput; virtuální ukazatele a headless backend žádná nemají):
  - `luxcomp_input_set(kind, prop, value)`: `kind` je `LUXCOMP_INPUT_MOUSE` nebo `LUXCOMP_INPUT_TOUCHPAD`
    (zařízení, které umí klepnout). Hodnota platí pro všechna připojená zařízení toho druhu i pro
    později připojená. `LUXCOMP_INPUT_DEFAULT` vrátí výchozí hodnotu zařízení. Zařízení bez volby ji
    tiše přeskočí, odmítnutou hodnotu jádro zapíše do logu.
  - Vlastnosti `LUXCOMP_INPUT_*`: `SPEED` (-100..100, libinput -1..1), `ACCEL_PROFILE` (0 adaptive,
    1 flat), `NATURAL_SCROLL`, `LEFT_HANDED`, `MIDDLE_EMULATION`, `TAP`, `TAP_DRAG`,
    `DISABLE_WHILE_TYPING` (0/1), `CLICK_METHOD` (0 žádná, 1 oblasti tlačítek, 2 clickfinger),
    `SCROLL_METHOD` (0 žádná, 1 dvěma prsty, 2 okrajem, 3 s tlačítkem).
  - Zpětné čtení po zařízeních (co má libinput opravdu nastavené, pro IPC a testy):
    `luxcomp_input_next(id)` (0 začne i skončí seznam), `luxcomp_input_name(id)`,
    `luxcomp_input_get(id, prop)`; `prop` `LUXCOMP_INPUT_KIND` vrátí druh, volba, kterou zařízení
    nemá, vrátí `LUXCOMP_INPUT_NONE`.
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
  okna, oddělovač a znak na semaforu pod ukazatelem (`GLYPH`: ×, −, +);
- stín: barvu s alfou (`SHADOW_ACTIVE`, `SHADOW_INACTIVE`, alfa 0 = bez stínu) a dosah v px
  (`SHADOW_ACTIVE_SIZE`, `SHADOW_INACTIVE_SIZE`).

`luxcomp_theme_set_font("Inter Semi-Bold 10")` nastaví písmo. Výchozí hodnoty jsou světlý vzhled
LuxOS. Tmavý režim a tokeny návrhu (WP-4) nastaví luxwm těmito voláními, v jádře nejsou žádné
soubory s tématem.

Jak to jádro kreslí:
- Okno se zahlavím kompozitoru (xdg-decoration nebo `org_kde_kwin_server_decoration` v režimu server,
  ten používá GTK 3 u oken bez headerbaru, např. Thunar) má zahlaví, stín a zaoblené dolní rohy.
  Výchozí režim protokolu KDE je server; xdg-decoration má přednost.
- Okno s vlastním zahlavím (CSD, GTK headerbar) má jen stín kolem geometrie okna
  (`xdg_surface.set_window_geometry`, bez okrajů, kam si klient kreslí vlastní stín) a zaoblené dolní
  rohy. `VIEW_DECO_TOP` je 0.
- Zahlaví i stín se kreslí v měřítku největšího výstupu (při 2x ostré písmo a kolečka).
- Stín je 8 dílů jedné předem rozmazané textury (rohy 1:1, hrany roztažené z jednoho sloupce).
  Textura je společná všem oknům se stejnou velikostí, poloměrem, barvou a měřítkem, při přesunu
  okna se nic nepočítá. Maximalizované a celoobrazovkové okno stín ani zaoblení nemá.
- Dolní rohy obsahu se zaoblí poloměrem `CORNER_RADIUS`: obsah se ořízne nad dolním pruhem, pruh
  mezi rohy kreslí druhý strom téhož povrchu a rohy jsou malé kopie pixelů klienta s vyhlazenou
  maskou. Pixely rohů se čtou jen když je klient v rozích změnil. Povrch s viewportem nebo rotací
  a textura, kterou nejde číst, mají rohy ostré.
- `LUXCOMP_STATS=1` vypíše po každém tažení okna počet snímků a nejdelší a průměrný čas kreslení.

### Material (rozmazané pozadí)

Plocha layer-shell o material požádá příponou jmenného prostoru: `název@material[:poloměr]`, např.
`luxos-cc@popup:16`, `luxos-launchpad@dim:0`. Bez přípony je plocha jako dřív. Část před `@`
kompozitor nečte. Soukromý protokol by klienti GTK (gtk-layer-shell) museli vázat sami přes
`wl_display` GDK; jmenný prostor nastaví jedno volání `gtk_layer_set_namespace()` a labwc ho ignoruje.

Pod povrch jde v jeho stromu scény:
- **rozmazaný výřez** všeho, co je ve scéně pod plochou (tapeta, okna, nižší vrstvy), v každém
  obdélníku vstupní oblasti povrchu (`wl_surface.set_input_region`, výchozí je celý povrch) se
  zaoblenými rohy daného poloměru, saturace 1,6. Sklo je tam, kam jde kliknout: Dock si vstupní oblast
  nastaví na panel (ne na místo pro zvětšené ikony a popisky), oznámení na bubliny. Obdélníky tenčí než
  8 px (horká hrana skrytého Docku) material nemají, nejvýš 8 obdélníků;
- **stín** materiálu (úroveň výšky: barva s alfou, dosah, posun dolů), kreslený vně plochy.

Klient kreslí jen tónování materiálu (průhlednou barvu) a obsah. Popupy xdg takové plochy (nabídky
GTK) dostanou material `menu` v obdélníku geometrie okna (stín GTK kolem nabídky je mimo). Material
`popups` (`luxos-widgets@popups`) dá material jen popupům, plocha sama žádný nemá (nabídka plochy).

**Material okna** (`luxcomp_view_set_material(okno, název, x, y, w, h)`, luxwm IPC `set_window_material`):
rozmazané pozadí pod obdélníkem obsahu okna xdg nebo X11 (průsvitný panel Nastavení). Souřadnice jsou
v geometrii okna (bez okrajů klienta pro stín CSD), obdélník se ořízne na okno. Uzel je ve stromu těla
okna úplně dole (pod povrchem klienta i pod kopiemi zaoblených rohů), takže jde s oknem při přesunu,
změně velikosti, přejezdu plochy i minimalizaci. Výřez končí pod oknem: vlastní stín okna ani okna nad
ním do něj nepatří a překreslování okna samotného nic nepřepočítává. Material okna nemá vlastní stín.
Rohy obdélníku, které leží v zaoblených rozích okna, dostanou poloměr rohu okna (dolní, když je zaobluje
kompozitor; horní u okna s vlastním záhlavím), ostatní jsou ostré; maximalizované okno ostré všechny.
Barva `fallback`, tiery a hlídání času snímku jsou stejné jako u ploch. Uzel vzniká až s dekorací okna
(při namapování), požadavek před tím se jen uloží. `""` nebo `w`/`h` ≤ 0 material zruší.

Část okna mimo výstup (přejezd plochy, okno na kraji obrazovky) výřez nemá; pod pixman je tam barva
materiálu, pod gles2 protažený okraj výřezu.

Výřez se počítá znovu jen tehdy, když se změnilo, co pod plochou je. Podpis tvoří uzly scény pod
výřezem: poloha, velikost, buffer, průhlednost a pořadové číslo commitu povrchu. Při klidu se
nepočítá nic, ani když plocha sama překresluje obsah (hodiny).

| Tier (`luxcomp_blur_tier()`) | Kdy | Jak |
|---|---|---|
| 2 | gles2 | výřez v plném rozlišení průchodem rendereru, dual Kawase shadery GLES2 (4 průchody dolů, 4 nahoru, efektivní poloměr 32 px), v posledním saturace a zaoblení |
| 1 | pixman | výřez ve čtvrtinovém rozlišení, 3× box blur v C (kanály v 16bitových pruzích), zvětšení rendererem, zaoblení rohů |
| 0 | `luxcomp_blur_set(…, 0)`, chyba shaderu nebo pomalé snímky | neprůhledná barva `fallback` materiálu se zaoblenými rohy |

Pod pixman se hlídá čas snímku: když tři snímky s přepočtem po sobě trvají přes 8 ms, kompozitor
přejde na tier 0 (do dalšího `luxcomp_blur_set`). Naměřeno headless 1920×1080 pixman, plocha
400×500 nad oknem 1600×900, které se každých 8 ms posune o 12 px: snímek průměrně 3,6 ms, nejvýš
5,4 ms; přepočet výřezu 1,5 ms (nejvýš 2,1 ms).

Tier 2 je ověřený headless na skutečných GPU (`WLT_RENDER_NODE`, viz `scripts/wl-test/README.md`): AMD Ryzen 5500U
(radeonsi) a NVIDIA GTX 1650 (proprietární ovladač 620). Obraz odpovídá pixmanu (`blur.sh`: průměrný rozdíl
0,8–0,9 z 255 pod plochou). Zátěž 6 oken + ztmavení Launchpadu přes celou obrazovku + 3 vyskakovací plochy, okno pod
nimi se hýbe každých 8 ms (všechny čtyři výřezy se přepočítávají v každém snímku), čas snímku na CPU:

| | 1920×1080 | 3840×2160 | CPU kompozitoru (bez materiálu) |
|---|---|---|---|
| AMD (gles2) | 3,8 ms, přepočet 2,6 ms | 3,6 ms, přepočet 2,3 ms | 21 % (5 %) |
| NVIDIA (gles2) | 5,6 ms, přepočet 4,1 ms | 4,8 ms, přepočet 3,5 ms | 25 % (10–13 %) |
| pixman (bez přechodu na tier 0) | 27,7 ms, přepočet 18,9 ms | – | 63 % |

Pixman tu po třech snímcích přejde na tier 0, jak má. V klidu nula probuzení a 0 % CPU na všech třech;
2000 otevření a zavření plochy s materiálem bez růstu PSS, deskriptorů ani paměti GPU (fdinfo amdgpu).

Proč to tak je:
- Textury bufferů, které nejsou klientské (záhlaví, stíny oken), si blur drží u bufferu (`wlr_addon`):
  gles2 by je jinak při každém přepočtu nahrával do GPU znovu (64 textur pod ztmavením ~9 ms).
- Záhlaví, rohy a stíny drží svůj zobrazený buffer zamčený. Scéna pod gles2 buffer po nahrání pustí a nechá
  si jen texturu; výřez materiálu by pak záhlaví a stíny oken pod plochou neviděl.
- Rozmazaný materiál není pro scénu neprůhledný (jen tier 0): jinak scéna zahodila poškození pod ním
  (pohyb okna celého pod ztmavením, video pod vyskakovací plochou zůstaly v materiálu staré) a zakrytým
  klientům neposílala frame done. Pod pixman to stojí ~0,9 ms na snímek s pohybem pod plochou 400×500.
- Kontext EGL rendereru zůstává aktuální: jeho uvolnění po každém průchodu stálo na NVIDIA 0,3–1,8 ms.

- `luxcomp_material_set(název, poloměr, fallback, stín, dosah, posun)`: poloměr je výchozí pro
  jmenný prostor bez `:poloměr`, `fallback` neprůhledná barva tieru 0, stín `0xAARRGGBB` (alfa 0 = bez
  stínu). Neznámý název se přidá (nejvýš 16 materiálů). Výchozí tabulka je světlý režim tokenů:
  `bar`, `dock`, `menu`, `popup`, `toast`, `sheet`, `dim`; luxwm ji přepíše z `luxos_tokens.lsl`
  (`MATERIAL`, `ELEVATION`) při startu a změně režimu.
- `luxcomp_blur_set(poloměr, saturace_%, režim)`: režim 0 = jen neprůhledná barva, 1 = automaticky.
- `luxcomp_view_set_material(okno, název, x, y, w, h)`: material pod obdélníkem okna (viz výše), přidáno
  bez změny verze API (9).
- `LUXCOMP_STATS=1` vypíše každých 120 snímků s materiálem nejdelší a průměrný snímek a přepočet;
  `LUXCOMP_BLUR_SLOW_MS` mění rozpočet 8 ms (testy přechodu na tier 0).

`luxcomp_set_cursor(téma, velikost)` nastaví ukazatel kompozitoru (plocha, zahlaví) a exportuje
`XCURSOR_THEME`/`XCURSOR_SIZE` pro později spuštěné klienty. Velikost je v logických px, obrázek
pro měřítko každého výstupu si wlroots načte sám. luxwm bere téma a velikost z `gtk-3.0/settings.ini`
(jako GTK na X11: WhiteSur-cursors 24), proměnné prostředí relace mají přednost.

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
- `WLR_RENDER_DRM_DEVICE` (render node) má ve wlroots přednost i před GPU displeje; detekce 3D kontroluje
  právě ten node.
- Volba je vždy v logu, u gles2 s řetězcem `GL_RENDERER`:
  `luxcomp: renderer pixman + software cursor (no DRM render node)`,
  `luxcomp: renderer gles2 on AMD Radeon Graphics (radeonsi, renoir, ACO, DRM 3.64, …)`.

**Více GPU (hybridní notebook).** S backendem DRM (skutečné přihlášení) wlroots otevře všechny GPU s výstupy;
renderer vzniká na primárním (GPU s `boot_vga`, u notebooku Ryzen + GTX 1650 iGPU AMD, které řídí vestavěný panel). Výstupy na
druhém GPU (HDMI zapojené do NVIDIA) dostávají snímky kopií: druhý GPU má vlastní pomocný renderer gles2 a
buffer z primárního importuje přes dmabuf (obvykle s modifikátorem LINEAR). Material na takovém výstupu
alokuje mezibuffery podle formátu jeho swapchainu, tedy taky LINEAR - funguje, jen je pomalejší.
`WLR_RENDER_DRM_DEVICE=/dev/dri/renderD129` by renderovalo na NVIDIA a kopírovalo na panel AMD.
glvnd do kompozitoru načte EGL všech výrobců (NVIDIA ~37 MB PSS, i když renderuje AMD).

Na skutečném přihlášení ještě ověřit (headless to neumí): renderer v logu (má být AMD), material a stíny
na vestavěném panelu i na monitoru na NVIDIA, čas snímku `LUXCOMP_STATS=1` na obou, přetažení okna mezi
nimi, uspání/probuzení dGPU (runtime PM) a odpojení monitoru za běhu.

## Výstupy pro klienty

Jádro nabízí `wlr-output-management-v1`: `wlr-randr` vypíše výstupy a nastaví režim (i vlastní
velikost u headless a vnořeného backendu), polohu a měřítko. Harness `scripts/wl-test` přes něj
zjišťuje, že kompozitor běží, a nastavuje `--size`. Po změně velikosti přijde `OUTPUT_USABLE`.

- Jádro opravdu použije režim (i vlastní u headless a vnořeného), polohu, měřítko včetně zlomkového
  (wl_fixed, logická velikost = `wlr_output_effective_resolution`, tedy oříznutá), otočení
  a zapnutí/vypnutí.
- Konfigurace je celá nebo nic: nejdřív se otestují všechny hlavy, teprve pak se použijí. Odmítnutý
  režim jednoho monitoru nenechá ostatní napůl přepnuté.
- Vypnutý výstup zmizí z rozložení a jeho použitelná plocha je prázdná (`OUTPUT_USABLE`), luxwm
  z něj přesune okna. Odpojený výstup zavře své vrstvy layer-shell (klient dostane `closed`).
- **Zrcadlení** protokol nezná: nastavení monitorů dá zrcadlené výstupy na stejný počátek. Výstup,
  který má počátek společný s menším (při shodě dřívějším) zapnutým výstupem, je zrcadlo: ukazuje
  obsah vzoru a jeho vlastní vrstvy (lišta, Dock, tapeta) jsou schované ve vypnutém stromu scény,
  aby se průhledná lišta nekreslila dvakrát přes sebe. Použitelná plocha zrcadla je celý výstup.

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
  zavření semaforem, Alt+Tab, Ctrl+šipky a psaní do zaměřeného okna přes xdotool;
- **material okna**: `packages/luxwm/tests/test_luxwm_window_material.py` (pixman a gles2 s render node,
  `material-probe.c`: pruhledný panel nad pruhy 4 px, cizí PID, sandbox, oříznutí, přesun, plocha, odpojení,
  skutečný `luxos-settings`). Pixman 1280×800, tažení okna 360×260 s panelem 120×260 (přepočet každý snímek):
  snímek průměrně 1,3 ms, nejvýš 3–7 ms; přepočet výřezu 0,5 ms (nejvýš 1,8 ms).
- **material** (`blur.sh`, `blur_check.py`): plocha `test-popup@popup:16` nad oknem s pruhy 4 px;
  pod plochou s materiálem pruhy zmizí (směrodatná odchylka jasu v řádku < 3), bez materiálu zůstanou
  (> 20), tier 0 je jednolitý; čas snímku při pohybu okna v `demo.log`, druhý běh s
  `LUXCOMP_BLUR_SLOW_MS=0` ověří automatický přechod na tier 0.

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
- `org.freedesktop.a11y.KeyboardMonitor` a režim greeteru.
- Material pro vnořené popupy (podnabídky); material jen u ploch layer-shell, jejich prvních popupů
  a obdélníku okna, o který okno požádá přes luxwm (`set_window_material`, zatím jen vlastní okna shellu).
- Hlídání sériových čísel u `REQ_MOVE`/`REQ_RESIZE`. Teď stačí, že politika tah spustí jen pro
  okno pod kurzorem.
