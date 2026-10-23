# Přepis částí desktopu LuxOS do LSL – inventura, měření a plán

Stav k 2026-10-23 (LSL 0.10.4, LuxOS 0.9.5 → 0.9.6). Priority projektu: rychlost a nízká spotřeba
zdrojů, pak design. LSL se použije tam, kde je měřitelně rychlejší nebo lehčí než bash/Python; kde to
současné API LSL (moduly `glib`, `gio`, `gtk`) nestačí, je níže přesný seznam chybějících funkcí.

Měřeno nástrojem `rss-launch` (fork + execve + wait4 bez libc, aby vlastní paměť spouštěče
nezkreslila `ru_maxrss` potomka; medián wall času, průměr CPU, medián maxrss) na notebooku
(Kali, hostitel) a ve VM LuxOS 0.9.5 (`scripts/test-vm.sh live --headless`, 4 vCPU, 3 GB), dále
`scripts/perf/idle-probe.py` (klidová zátěž relace 60 s) a `scripts/perf/launch-probe.py` (start aplikací).

## 1. Inventura: vlastní programy, které běží často nebo stále

| Program | Jazyk | Kdy běží | Cena (VM, před přepisem) | Zisk přepisem do LSL |
|---|---|---|---|---|
| `luxos-clock` (genmon) | bash (printf `%()T`) | každé 3 s (28 800×/den) | 1,7 ms, 1,6 ms CPU, 3,7 MB | malý, ale nejčastější proces: −20–27 % času |
| `luxos-battery` (genmon) | bash + awk na každý překlad | každých 20 s (4 320×/den), na baterii až 4 překlady | 9,6 ms, 10,5 ms CPU, 4,4 MB | **velký**: 6× rychleji, žádný další proces |
| `luxos-appname print` (genmon) | bash | při každém přepnutí okna (refresh z `luxos-appname watch`) + 1×/den | 7,4 ms, 8,3 ms CPU, 4,3 MB | **velký**: 5× rychleji |
| `luxos-appname watch` | bash + `xprop -spy` | stále (2 procesy bash + xprop, PSS 1,0 MB) | 0 CPU v klidu, 0 probuzení | žádný (řízené událostmi); zůstává bash |
| `luxos-netcheck` (genmon) | bash + `nmcli` | při změně sítě (refresh z hubu) + 1×/den | 11,6 ms (nmcli), 3,6 MB | **střední**: 2,5× rychleji, D-Bus přímo |
| `luxos-cc-toggle` | sh + cat + grep + kill | klik na Ovládací centrum | 4,5 ms, 3,6 MB | **střední**: 4× rychlejší odezva kliknutí |
| `luxos-calendar-toggle` | sh + cat + grep + kill | klik na hodiny | 5,3 ms, 3,6 MB | **střední**: 5× rychlejší odezva |
| `luxos-control-center --panel` (genmon) | Python | 1× při startu panelu + 1×/den | 46 ms, 51 ms CPU, 14,8 MB | malý (jen 1×/přihlášení); viz plán |
| `luxos-hub` (dříve luxos-daemon) | Python + GTK | stále | RSS 72 MB, PSS 38 MB, 5 vláken, 0,5 s CPU za 11 min | **velký** (−25 MB PSS podle měření LSL 43 vs 60 MB), ale API nestačí – plán níže |
| `luxos-control-center` (okno) | Python + GTK | klik v liště (předpřipravené v hubu); samostatně 0,29 s warm / 0,50 s cold | sdílí proces hubu | start 150 ms místo 240 ms (měření LSL), plán níže |
| `luxos-calendar` (okno) | Python + GTK + cairo/Pango | klik na hodiny (předpřipravené v hubu); samostatně 0,30 s / 0,47 s | sdílí proces hubu | plán níže, kreslení cairo/Pango chybí |
| `luxos-launchpad`, `luxos-search` | bash → `rofi` | Super+A / Super+Space | rofi dominuje (desítky ms + ikony); bash část ~5 ms (`luxos-appearance status`, překlad) | malý; neřešit, dokud je rofi |
| `luxos-session` | bash | 1× při přihlášení | desítky volání xfconf-query/pgrep (jednorázově) | malý |
| `luxos-dock` | bash (hlídá plank) | stále (1 proces, PSS 0,6 MB, spí ve `wait`) | 0 | žádný |
| `luxos-menubar` | C | stále (PSS 0,4 MB) | 0,2 probuzení/s | žádný (už C) |
| LuxOS Care, část relace (`luxos_care_session.py`) | Python, uvnitř hubu | stále (file monitor + D-Bus) | součást hubu | součást přepisu hubu |
| `luxos-datasaver`, `luxos-powersaver` | bash + nmcli/gdbus | po přihlášení, při změně sítě, ručně | 20–100 ms, jednorázově | malý |
| `luxos-settings`, `luxos-screenshot`, `luxos-tour`, … | Python + GTK | na vyžádání | start 0,4 s warm (settings 3,1 s cold) | mimo rozsah: GTK API LSL zatím nestačí |

Klidová zátěž celé relace lux ve VM (60 s): CPU 110 ms, 16,9 probuzení/s, forky 25/min (z toho 20/min
jsou hodiny, dalších ~3/min baterie na notebooku). Python `import gi, Gtk` stojí 81 ms, samotný start
Pythonu 11 ms; bash 1,5 ms; program LSL cíle `linux-x86_64-gnu` 1,0–1,2 ms (jen libc), s GLib/GIO
(D-Bus) 3,5–4,5 ms.

## 2. Přepsáno do LSL (tento krok)

Zdroje: `packages/luxos-desktop/files/lsl/*.lsl`, překlad v `build()` PKGBUILDu
(`lslc --target linux-x86_64-gnu`). Společné moduly:

- `luxos_i18n.lsl` – `T("English")`, `TF("English %s", [hodnota])`: stejná data a pravidla jako
  `i18n.sh`/`luxos_i18n.py` (TSV `/usr/share/luxos/i18n/<jazyk>.tsv`, komentáře a prázdné překlady se
  přeskočí, `LUXOS_I18N_DIR` pro testy). Tabulka se čte celá, ale neparsuje: hledá se přímo v textu
  (`memmem`, ~10 µs na 160 kB); slovník ze 2 400 řádků by v LSL stál ~60 ms.
- `luxos_sys.lsl` – tenké vazby na libc (`# lsl: internal-abi`, bloky `unsafe:`): `strftime_local`,
  `tsv_lookup`, `kill`, `exec` (execvp), `list_dir`, `eprint`. Nahrazuje funkce, které v `glib`/`gtk`
  LSL 0.10.4 chybí (seznam v kapitole 5); až budou ve standardní knihovně, modul zmizí.

Měření starý (bash/sh) → nový (LSL), medián wall / průměr CPU / maxrss:

| Program | Hostitel: starý | Hostitel: nový | VM: starý | VM: nový |
|---|---|---|---|---|
| `luxos-clock` (cs_CZ) | 1,43 ms / 1,47 / 3,6 MB | 1,02 ms / 1,09 / 1,9 MB | 1,66 ms / 1,58 / 3,66 MB | 1,37 ms / 1,45 / 3,82 MB |
| `luxos-clock` (en_US) | – | – | 1,62 ms / 1,70 / 3,69 MB | 1,18 ms / 1,17 / 3,82 MB |
| `luxos-battery` (vybíjení, odhad času) | 6,3 ms / 6,7 / 4,0 MB | 1,50 ms / 1,47 / 2,1 MB | 9,6 ms / 10,5 / 4,4 MB | 1,55 ms / 1,63 / 4,1 MB |
| `luxos-netcheck` | 21,1 ms / 3,3 / 3,6 MB (nmcli) | 5,9 ms / 4,7 / 6,2 MB | 11,6 ms / 2,9 / 3,6 MB | 4,6 ms / 5,3 / 8,2 MB |
| `luxos-appname print` | 8,8 ms / 9,1 / 4,0 MB | 1,02 ms / 1,03 / 1,9 MB | 7,4 ms / 8,3 / 4,3 MB | 1,47 ms / 1,39 / 4,0 MB |
| `luxos-cc-toggle` (hub běží → signál) | 1,9 ms / 2,0 / 2,3 MB (bez hubu) | 0,90 ms / 0,88 / 1,4 MB | 4,5 ms / 4,8 / 3,6 MB | 1,03 ms / 1,01 / 3,5 MB |
| `luxos-calendar-toggle` (hub běží) | 1,9 ms / 2,0 / 2,3 MB (bez hubu) | 0,72 ms / 0,72 / 1,4 MB | 5,3 ms / 5,6 / 3,6 MB | 0,99 ms / 0,99 / 3,5 MB |

Poznámky k měření:

- Ve VM je maxrss všech programů o ~2 MB vyšší než na hostiteli (Arch mapuje `locale-archive`
  celé, glibc je načte při `setlocale`); pořadí a poměry jsou stejné.
- `luxos-netcheck` v LSL má vyšší maxrss (GIO + GObject + D-Bus spojení), ale je 2,5–3,6× rychlejší
  a nemá další proces; běží jen při změně sítě. CPU je mírně vyšší než u bashe, který většinu práce
  nechal na `nmcli` (jeho CPU se do dětí skriptu nepočítá).
- Hodiny: zisk je malý (0,3–0,45 ms na běh, ~10 s CPU denně), ale jde o nejčastější proces relace
  a nová verze čte čas jednou pro oba formáty. Ponecháno v LSL.
- `luxos-appname print`: původní bash ≥ 5.2 vracel pro `<` a `>` neplatný markup (`<lt;`, `>gt;` –
  `&` v náhradě `${s//</&lt;}` je nalezený text, volba `patsub_replacement`); LSL verze escapuje správně.
- Za den na notebooku: hodiny 28 800 × 0,3 ms ≈ 9 s CPU, baterie 4 320 × 8 ms ≈ 35 s CPU
  a 4 320 forků awk méně; přepnutí okna ~7 ms rychleji.

Ponecháno beze změny (a proč):

- `luxos-appname watch` – dlouho běžící smyčka nad `xprop -spy`, v klidu 0 CPU; LSL nemá X11
  vazbu v cíli gnu (a cena by se nezměnila). Přesunut do `/usr/lib/luxos/luxos-appname-watch`,
  `luxos-appname watch` (LSL) ho spustí přes `execvp`.
- `luxos-launchpad`, `luxos-search` – čas určuje rofi; bash část je ~5 ms z desítek.
- `luxos-dock`, `luxos-session`, `luxos-datasaver`, `luxos-powersaver`, `luxos-appearance`,
  `luxos-displays` – jednorázové nebo spící; zisk by byl neměřitelný.
- `luxos-control-center --panel` – 46 ms Pythonu 1× za přihlášení; samostatný LSL program by
  vyžadoval změnu příkazu v xfconf profilech uživatelů (`luxos-control-center --panel` je uložené
  v `xfce4-panel.xml` každého uživatele). Vyřeší se až s přepisem Ovládacího centra (kapitola 4).

## 3. Balení: jak se LSL překládá v sestavení

- Zvolená varianta: **`lslc` jako makedepend v kontejneru** (`makedepends=('lsl>=0.10.4')` v
  `packages/luxos-desktop/PKGBUILD`), ne předkompilované binárky v Gitu (nereprodukovatelné, závislé
  na glibc/GLib hostitele, kde se překládaly).
- `lsl` je balík `packages/apps/lsl` (repozitář `[luxos-apps]`, aktualizován na 0.10.4,
  `sha256 56202da9…`). Kontejner sestavuje aplikace před `[luxos]`, proto `scripts/container-build.sh`
  (`build_one`) nainstaluje makedepend, který není v repozitářích Archu, z balíku sestaveného
  dříve v témže běhu (`pacman -U` z `$BUILD/pkgs/*/<název>-[0-9]*.pkg.tar.zst`); zavislosti z Archu
  se instalují zvlášť (`pacman -S` s neznámým cílem by dřív neinstaloval nic – a `|| true` to skryl).
  Totéž v `scripts/perf/build-pkg.sh`: `scripts/perf/build-pkg.sh out/x packages/apps/lsl packages/luxos-desktop`.
- Cíl `linux-x86_64-gnu`: `lslc` při překladu ověřuje každý symbol proti knihovnám stroje,
  kontejner tedy musí mít glib2/gtk3 (makedepend `gtk3` už je). Výsledné programy závisí jen na
  glibc, GLib a GIO (`depends` už obsahuje gtk3 přes Xfce), ne na balíku `lsl`.
- `options=(!debug !strip)`: `strip` rozbije dynamický ELF cíle gnu (po `strip` „exec format
  error“; viz chyby pro LSL níže). Programy a knihovny z C se zmenšují ručně v `build()`.
- Překlad všech šesti programů trvá ~0,7 s.

## 4. Plán: luxos-hub, Ovládací centrum, Kalendář, Launchpad

Pořadí podle zisku:

1. **luxos-hub** (72 MB RSS / 38 MB PSS Python; LSL démon s hlavní smyčkou + D-Bus měřen na 43 MB
   PSS místo 60 MB, 0.10.5 ještě méně). Hub drží skrytá okna Ovládacího centra a Kalendáře,
   proto jeho přepis dává smysl až spolu s nimi (jinak by GTK Python zůstal v paměti kvůli oknům).
   Části hubu bez oken (sledování sítě, paměti, Bluetooth agent, uspávání při přehrávání, Spořič dat,
   automatický vzhled, LuxOS Care) jdou přepsat hned, jakmile bude mít `gio`: `register_object`
   (Bluetooth agent odpovídá na volání metod BlueZ), `file_monitor`, parsování GVariant do hodnot
   LSL a `watch_name` s již existujícím spojením.
2. **Ovládací centrum** – jednoduché widgety (Box, Grid, Label, Button, Image, Scale, CSS).
   Chybí hlavně `Gtk.Scale`, `Gtk.Grid`, ikony z pixbufu, typ okna/pozice, klávesy (Escape),
   `Gtk.Settings` (název motivu pro CSS). Po doplnění API je to ~700 řádků Pythonu → LSL.
3. **Kalendář** – navíc `DrawingArea` s kreslením přes cairo + Pango layout (dny v mřížce),
   `ScrolledWindow`, `EventBox`, `Entry`, `Switch`, kurzor, file monitor (ICS). Vyžaduje modul cairo
   nebo alespoň `cairo_*`/`pango_cairo_*` vazby.
4. **Launchpad / Hledání** – dnes rofi (C). Vlastní LSL/GTK mřížka aplikací by dávala smysl až po
   Ovládacím centru (sdílené GTK vazby) a musela by se měřit proti rofi (ikony, fuzzy hledání).
5. `luxos-control-center --panel` zmizí s bodem 2 (hub vypíše ikonu sám; xfconf profil se změní jednou
   jako dnes u `netcheck-added`).

## 5. Chybějící API v LSL 0.10.4 (moduly glib/gio/gtk) – k doplnění do `stdlib`

Použito dnes přes vlastní `luxos_sys.lsl` (libc); ve standardní knihovně by patřilo do `glib`:

| Funkce | Podpis (návrh) | Proč |
|---|---|---|
| `glib.strftime_local(format)` nebo `glib.date_time_format(format)` | `(String) -> String`; `g_date_time_new_now_local` + `g_date_time_format` (nebo `localtime_r` + `strftime` po `setlocale(LC_ALL, "")`) | hodiny v liště: místní čas a názvy dnů/měsíců podle LANG; `time.strftime` v LSL je jen UTC bez locale |
| `glib.setlocale()` | `() -> String`; `setlocale(LC_ALL, "")` | překlady GTK a strftime podle prostředí; program cíle gnu dnes startuje v locale "C" |
| `glib.kill(pid, signal)` | `(Int, Int) -> Int` | přepínače oken posílají SIGUSR1/2 běžícímu hubu; dnes nutné `kill` přes proces |
| `glib.exec(argv)` | `(List) -> Int`; `execvp`, vrací jen při chybě | „exec“ v shellových skriptech (nahradit proces bez dalšího PID) |
| `glib.list_dir(path)` | `(String) -> List`; veřejná obálka `__lsl_list_directory` bez `unsafe` | `/sys/class/power_supply/BAT*` |
| `glib.read_file(path)` / veřejná `fd.read_text` bez omezení | `/proc/<pid>/cmdline` – `readfile` vrací prázdný text (velikost souboru 0); `fd.read_text` funguje, ale je skrytá v modulu `fd` | kontrola běžícího procesu |
| `eprint(text)` / `print_error` | zápis na stderr | chybová hlášení programů (`usage:`) |
| `String.find(needle, start)`, `String.rstrip(chars)` | jako Python | dnes ruční smyčky |
| rychlé hledání v textu | `String.find` je O(n) po code pointech (0,7 ms na 160 kB); `memmem` 10 µs | překladové tabulky bez parsování |

Pro luxos-hub (gio/glib):

| Funkce | Podpis (návrh) | Proč |
|---|---|---|
| `gio.register_object(bus, path, xml, on_method)` | `on_method(sender, path, interface, method, params_text, invocation)` + `gio.return_value(invocation, text)` / `gio.return_error(invocation, name, message)` | Bluetooth agent (`org.bluez.Agent1`: RequestPinCode, RequestConfirmation, …) |
| `gio.call_with_timeout(bus, name, path, iface, method, params, ms)` | jako `call`, s timeoutem | hub volá xfconf/UPower/login1 s 2–3 s timeoutem |
| `gio.get_property` → hodnota | varianta vracející Int/Bool/String/List místo textu `"uint32 4"` (nebo `gio.variant_to_value(text)`) | každé čtení dnes parsuje text |
| `gio.subscribe` → `params` jako hodnota | `f(sender, path, interface, signal, params)` s rozbalenou n-ticí | `PropertiesChanged` (slovník a{sv}) – rozbor textu GVariant je křehký |
| `gio.file_monitor(path, f)` | `g_file_monitor_file`, `f(path, event)`; události CHANGED, CREATED, DELETED, MOVED_IN, RENAMED, CHANGES_DONE_HINT | LuxOS Care (`/var/lib/luxos-care`), přehrávání (`/run/luxos/...`), Kalendář (ICS) |
| `gio.watch_name_on_connection(bus, name, appeared, vanished)` | už existuje `watch_name(bus, …)`; ověřit, že `bus` je existující spojení | BlueZ |
| `glib.spawn` s potlačeným výstupem / `start_new_session` | `g_spawn_async` s `G_SPAWN_STDOUT_TO_DEV_NULL \| G_SPAWN_STDERR_TO_DEV_NULL` | notify-send, luxos-powersaver |
| `glib.timeout_add_seconds` s prioritou, `glib.unix_signal_add` s prioritou | volitelný parametr | hub používá PRIORITY_HIGH |
| `glib.variant_builder` / tvorba `a{sv}` z Dictionary | `gio.variant_from_value(value, signature)` | xfconf `SetProperty` s hodnotou `<uint32 n>` |
| `glib.get_user_cache_dir()`, `glib.getenv`, `glib.file_test` | | adresáře cache, existence souborů bez `exists` (ok) |

Pro Ovládací centrum (gtk):

| Funkce | Podpis (návrh) | Proč |
|---|---|---|
| `gtk.grid_new()`, `gtk.grid_attach(grid, child, left, top, width, height)`, `grid_set_row/column_spacing`, `grid_set_column_homogeneous` | | mřížka dlaždic |
| `gtk.scale_new_with_range(orientation, min, max, step)`, `range_get_value`, `range_set_value`, `scale_set_draw_value` | | jas, hlasitost |
| `gtk.image_new_from_pixbuf`, `gdk.pixbuf_new_from_file_at_scale(path, w, h, keep_aspect)` | | avatar/ikony mimo motiv |
| `gtk.image_set_from_icon_name(image, name, size)` | | změna ikony dlaždice |
| `gtk.button_set_relief(button, gtk.RELIEF_NONE)`, `gtk.button_set_image`, `gtk.button_set_always_show_image` | | dlaždice |
| `gtk.window_set_type_hint(window, hint)`, `window_set_decorated`, `window_set_keep_above`, `window_set_skip_taskbar_hint`, `window_move`, `window_resize`, `window_present_with_time`, `window_set_position`, `window_stick` | | vyskakovací okno u lišty (hint DIALOG) |
| `gtk.widget_set_visual` + `gdk.screen_get_rgba_visual`, `widget_set_app_paintable` | | průhledné pozadí |
| `gdk.screen_get_default`, `gdk.display_get_default`, `gdk.monitor_get_workarea(display, n)`, `gdk.display_get_primary_monitor`, `gdk.monitor_at_point` | | umístění okna k liště |
| `gtk.settings_get_default()` + `gobject.get_string(obj, "gtk-theme-name")` / `gobject.set(…)` | obecné `g_object_get`/`g_object_set` pro String/Int/Bool | název motivu → CSS, `gtk-application-prefer-dark-theme` |
| obsluha `key-press-event` s přístupem k `keyval` (`gdk.event_key_keyval(event)`), `gdk.KEY_Escape` | | Escape zavře okno |
| `gtk.get_current_event_time()`, `gdk.CURRENT_TIME` | | present |
| `gtk.widget_get_allocated_width/height`, `widget_queue_draw`, `widget_set_opacity`, `widget_get_visible`, `label_set_ellipsize`, `label_set_xalign`, `label_set_max_width_chars` | | layout |
| `gtk.css_load` s prioritou aplikace + odstranění starého provideru (`style_context_remove_provider_for_screen`) | | přepnutí světlý/tmavý za běhu |
| `glib.filename_from_uri(uri)` | | tapeta z URI |

Pro Kalendář (navíc):

| Funkce | Proč |
|---|---|
| `gtk.drawing_area_new()`, obsluha `draw(cr, widget)` s modulem **cairo**: `cairo.set_source_rgba`, `rectangle`, `arc`, `fill`, `stroke`, `move_to`, `line_to`, `set_line_width`, `save/restore`, `clip` | mřížka dnů, zvýraznění dneška |
| **Pango**: `pango_cairo_create_layout`, `pango_layout_set_text/markup`, `set_font_description` (`pango_font_description_from_string`), `set_width`, `set_ellipsize`, `set_alignment`, `get_pixel_size`, `pango_cairo_show_layout`, `pango.Weight`, `pango.SCALE` | text v kreslené ploše |
| `gtk.scrolled_window_new`, `scrolled_window_set_policy`, `event_box_new`, `widget_add_events`, `button-press-event` s `gdk.event_button_x/y/button(event)`, `scroll-event` | seznam událostí, klikání na dny |
| `gtk.entry_set_placeholder_text`, `entry_set_icon_from_icon_name`, signál `activate`, `changed` | nová událost |
| `gdk.cursor_new_from_name(display, name)`, `gdk.window_set_cursor(gdk_window, cursor)`, `gtk.widget_get_window` | kurzor ruky |
| `gtk.style_context_get_color(ctx, state)` → RGBA | barvy z motivu pro kreslení |
| `gtk.widget_get_style_context`, `gtk.widget_set_state_flags` | |
| `glib.date_time_*` (lokální datum, dny v týdnu, názvy měsíců podle locale, první den týdne) | kalendář bez vlastní implementace; `time` modul je UTC bez locale |

Chyby/omezení LSL 0.10.4 nalezené při práci (k nahlášení):

- `strip` na binárce cíle `linux-x86_64-gnu` vede k „exec format error“ (makepkg stripuje
  implicitně; balík musí mít `options=(!strip)`).
- `readfile("/proc/<pid>/cmdline")` vrací prázdný text (soubory s hlášenou velikostí 0);
  `fd.read_text` funguje.
- `String.rstrip`/`lstrip`/`strip` nepřijímají znaky k odstranění; `String.find` nemá počáteční pozici.
- `__lsl_list_directory` je použitelná jen v `unsafe:` bloku; chybí veřejná obálka.
- `env.get(name, default)` vrací prázdný String pro prázdnou proměnnou (shellové `${VAR:-x}` dá `x`);
  je to korektní, jen jiné než bash – řešeno pomocnou funkcí.
- Výstup na stderr není ve veřejném API (jen `print` na stdout).
- Program cíle gnu startuje v locale "C"; GTK/strftime potřebují `setlocale(LC_ALL, "")`
  (v LSL dostupné jen přes `internal-abi`).
