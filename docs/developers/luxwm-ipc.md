# luxwm IPC – rozhraní pro shell (LuxOS 1.1.0)

luxwm (správce oken na Waylandu, `packages/luxwm`) poslouchá na soketu UNIX. Shell (lišta, Dock,
nastavení, `luxos-appearance`) přes něj dostává události o oknech, plochách, rozložení klávesnice,
monitorech a vzhledu a posílá jednoduché příkazy. Protokol je řádkový JSON: jeden objekt na řádek,
UTF-8, konec řádku `\n`.

Klient v LSL je `luxos_luxwm.lsl` (`packages/luxwm`, instalovaný jako modul pro shell). Z příkazové
řádky a ze skriptů slouží `luxwm-msg`.

## Soket

- Cesta: `$XDG_RUNTIME_DIR/luxwm-$WAYLAND_DISPLAY.sock`. luxwm ji exportuje programům, které spouští,
  jako `LUXWM_SOCK`. Klient bere `LUXWM_SOCK`, jinak cestu odvodí z `WAYLAND_DISPLAY` (výchozí
  `wayland-0`).
- Soket má práva `0600` a leží v `XDG_RUNTIME_DIR` (`0700`). Starý soket po pádu luxwm se při startu
  smaže, živý (jiný luxwm na stejném `WAYLAND_DISPLAY`) se nepřepíše.
- **Kontrola spojení:** jádro (libluxcomp, `ipc.c`) přečte `SO_PEERCRED`. Spojení od jiného uid se
  hned zavře a zapíše se do logu (`luxcomp: ipc: rejected uid N pid N`). Na soket nedosáhne ani root
  jiného uživatele, protože kontrola je i mimo práva souboru.
- **Privilegovaní klienti:** program spojení (`/proc/PID/exe` z `SO_PEERCRED`) se porovná se stejným
  allowlistem jako privilegované protokoly Waylandu (`/usr/share/luxwm/privileged.conf`, přenačte se
  na `SIGHUP` i příkazem `reload`). Výsledek platí po celé spojení. Interprety (sh, python) na
  allowlistu nikdy nejsou, skript proto privilegovaný být nemůže.
- Aplikace v sandboxu (`luxos-sandbox run --gui`) soket nedostanou: bwrap nepřipojí
  `$XDG_RUNTIME_DIR/luxwm-*.sock`.
- Limity: nejvýš 32 klientů, řádek nejvýš 64 KiB (delší = odpojení), nejvýš 1 MiB neodeslaných dat
  na klienta (pomalý odběratel se odpojí, luxwm nikdy nečeká).

## Požadavky a odpovědi

```
→ {"id": 1, "cmd": "next_layout"}
← {"id": 1, "ok": true}
→ {"id": 2, "cmd": "list_windows"}
← {"id": 2, "ok": false, "error": "permission denied"}
```

`id` je volitelné celé číslo; odpověď ho vrací beze změny. Každý požadavek dostane právě jednu
odpověď, pořadí odpovědí odpovídá pořadí požadavků. Události, které příkaz vyvolá (např. `workspace`
po `switch_workspace`), přijdou až po jeho odpovědi. Neznámý příkaz: `"error": "unknown command"`,
chybný JSON: `"error": "bad request"` (spojení zůstává).

| Příkaz | Argumenty | Privilegovaný | Popis |
|---|---|---|---|
| `subscribe` | `events`: seznam témat | jen téma `window` | odběr událostí; hned po odpovědi přijde aktuální stav každého tématu |
| `get_state` | – | ne (`window` jen privilegovaným) | `{"ok": true, "state": {téma: obsah události}}` |
| `switch_layout` | `index` (od 0) nebo `layout` (kód, např. `"cz"`) | ne | přepne rozložení klávesnice |
| `next_layout` | – | ne | další rozložení (za posledním první) |
| `switch_workspace` | `number` (od 1) nebo `delta` (`-1`, `1`) | ne | přepne plochu jako zkratka |
| `get_input` | – | ne | myš a touchpad: `{"ok": true, "config": {"mouse": {volba: hodnota}, "touchpad": {...}}, "devices": [zařízení, ...]}`, viz níže |
| `reload` | – | ne | znovu načte `luxwm.conf`, rozložení a opakování klávesnice, allowlist a vzhled (jako `SIGHUP`) |
| `set_theme` | `theme`: `"light"` / `"dark"` | ne | překreslí záhlaví oken a pošle událost `theme` |
| `set_cursor` | `theme`: název motivu kurzoru, `size`: 8–256 | ne | kurzor kompozitoru do konce relace (i po `reload`); trvale ho nastavuje Nastaveni > Vzhled v kanálu xsettings, odkud ho při přihlášení bere prostředí relace |
| `suspend_shortcuts` | `on`: `true` / `false` | ne | vypne globální zkratky, dokud klient neřekne `false` nebo se neodpojí (zadávání nové zkratky v nastavení) |
| `list_windows` | – | ano | `{"ok": true, "windows": [okno, ...]}` v pořadí od naposledy zaměřeného |
| `focus_window` | `window` (id okna) | ano | zaměří okno (i na jiné ploše, obnoví minimalizované) |
| `set_primary` | `output`: název výstupu | ano | hlavní monitor (viz níže); odpověď `"primary"` = skutečně použitý |
| `test_output` | `add`: `"WxH"` nebo `remove`: název | ano | jen testy: připojí/odpojí headless výstup (na skutečném backendu `"no headless backend"`) |
| `dock_zone` | `output`: název, `height`: px od spodního okraje (0 = nic) | ano | Dock, který jen uhýbá oknům (exkluzivní zóna 0): nová okna luxwm umisťuje nad něj a příliš vysoká zmenší; platí do dalšího `dock_zone` nebo do odpojení klienta |
| `sandbox_window` | `instance`, `width`, `height`, `title` | ne | `luxos-sandbox`: velikost a název hlavního okna X11 aplikace v sandboxu; luxwm podle nich nastaví kořenové okno Xwayland té instance sandboxu (jiných oken se netýká) |
| `set_window_material` | `app_id`, `material`, `x`, `y`, `w`, `h`, `radius` (0) | ne | sklo pod obdélníkem vlastního okna (panel Nastavení), viz níže |

`sandbox_window` je neprivilegovaný, protože ho posílá `luxos-sandbox` (skript, nemůže být na
allowlistu). Aplikace v sandboxu soket nemá; příkaz mění jen velikost a název kořenového okna
Xwayland s danou (náhodnou) instancí sandboxu, štítek „Sandbox · příkaz“ zůstává od kompozitoru.

Proč jsou příkazy neprivilegované: totéž dokáže každý proces uživatele i bez soketu (upraví
`~/.config/luxwm/luxwm.conf` a pošle `SIGHUP`) a přepnutí plochy nebo rozložení nic neprozradí.
Informace o cizích oknech (názvy, aplikace) a jejich ovládání
jsou privilegované stejně jako wlr-foreign-toplevel.

`set_theme` vzhled neukládá. Trvalá volba je `~/.config/luxos/appearance` (`light`/`dark`), kterou
píše `luxos-appearance` před voláním `luxwm-msg set-theme`. luxwm ji čte při startu a při `reload`.

### Material okna (`set_window_material`)

```
→ {"id": 3, "cmd": "set_window_material", "app_id": "luxos-settings", "material": "popup", "radius": 0,
   "x": 0, "y": 46, "w": 220, "h": 594}
← {"id": 3, "ok": true}
```

Pod obdélník obsahu okna kompozitor nakreslí rozmazané pozadí materiálu (jako u ploch layer-shell,
`luxcomp_view_set_material()` v `luxcomp-api.md`); klient pak kreslí panel jen průhledným tónováním.
Souřadnice jsou v geometrii okna xdg (`set_window_geometry`, bez okrajů pro stín CSD, u GTK od levého
horního rohu HeaderBar), v logických px. Obdélník se ořízne na okno a jde s ním (přesun, změna velikosti,
plocha, minimalizace). Rohy, které leží v zaoblených rozích okna, se zaoblí s ním.

- Platí jen pro namapovaná hlavní okna (bez rodiče) procesu, který poslal příkaz (PID z `SO_PEERCRED`
  spojení = PID klienta Wayland), se shodným `app_id`; nikdy pro okna ze sandboxu (wp-security-context).
  Cizí okna tak neovlivní ani neprivilegovaný klient.
- `{"ok": true}` jen když se material použil aspoň na jedno okno; jen pak má klient panel udělat
  průhledný. Jinak `"error"`: `"no such window"` (okno ještě není namapované nebo nesedí app_id/PID),
  `"blur off"` (`blur = no` v `luxwm.conf`), `"unknown material"`, `"bad request"` (také `radius` ≠ 0,
  zatím se nepoužívá). Klient pošle obdélník znovu při každé změně velikosti panelu a po novém spojení.
- Platí poslední požadavek spojení. Okno toho procesu, které se namapuje později, ho dostane také
  (odpověď ale už nepřijde, klient se zeptá znovu). `w` nebo `h` ≤ 0 nebo `material` `""` material zruší
  (`{"ok": true}`).
- Material žije se spojením: po odpojení klienta se zruší, protože klient bez luxwm kreslí panel
  neprůhledně (`luxos_luxwm.lsl` hlásí odpojení přes `on_state`). `luxos-settings` drží spojení po
  celou dobu běhu.
- Materiály: názvy z `luxos_tokens.SURFACE` kromě `dim`; barva a tier rozmazání jako u ploch shellu
  (pod pixman nebo při pomalých snímcích neprůhledná barva materiálu).

## Události

Události nemají `id`, mají `event`. Odběr: `{"cmd": "subscribe", "events": ["keyboard", "workspace"]}`.
Když klient požádá o téma, na které nemá právo, odpověď je `"ok": false, "error": "permission denied"`
a nepřihlásí se nic.

| Téma | Událost | Kdy |
|---|---|---|
| `window` | `{"event": "window", "id": 7, "app_id": "org.gnome.Calculator", "title": "Kalkulačka", "frame": [340, 120, 600, 432]}` | zaměřené okno se změní (i jeho název, app_id, poloha nebo velikost: `frame` je rám se záhlavím v souřadnicích rozložení, při tažení až po uvolnění tlačítka); bez okna `id` 0, prázdné řetězce a `frame` `[]` |
| `workspace` | `{"event": "workspace", "current": 2, "count": 4}` | přepnutí plochy (hned, ne až po animaci) |
| `keyboard` | `{"event": "keyboard", "current": 1, "layouts": [{"code": "us", "variant": "", "name": "English (US)"}, {"code": "cz", "variant": "", "name": "Czech"}], "repeat": {"rate": 25, "delay": 600}, "caps": false}` | přepnutí rozložení (zkratka `grp:…`, příkaz, klik v liště), nový seznam po `reload`, zapnutí/vypnutí Caps Lock; `repeat` = použité opakování klávesy (viz níže), `caps` = Caps Lock zapnutý |
| `output` | `{"event": "output", "primary": "HDMI-A-1", "outputs": [{"name": "HDMI-A-1", "x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 100, "refresh_mhz": 60000, "usable": [0, 30, 1920, 1050], "primary": true}]}` | monitor přidán nebo odebrán, změna použitelné plochy (lišta, Dock), změna hlavního monitoru; vypnutý monitor má `width` 0 a `usable` `[0, 0, 0, 0]` |
| `theme` | `{"event": "theme", "theme": "dark"}` | `set_theme`, `reload`, `SIGUSR1` |

Okno v `list_windows`: `{"id", "app_id", "title", "workspace" (od 1), "focused", "minimized", "fullscreen", "maximized", "sandbox"}`.
`sandbox` je app_id z wp-security-context (aplikace v sandboxu, nastavuje spouštěč), jinak `""`.

## Hlavní monitor

Na Waylandu neexistuje „primary output“ protokolu. V LuxOS je hlavní monitor ten, na kterém je Dock,
oznámení a OSD, kam luxwm přesune okna z odpojeného nebo vypnutého monitoru a kde začíná nové okno,
když kurzor není na žádném monitoru. Horní lišta je na každém monitoru. Volí se v Monitorech
(`luxos-displays-settings`, bílý pruh v uspořádání) a ukládá se pro sadu monitorů
v `~/.config/luxos/displays-wayland.json` (`sets.<sada>.primary`). Po každé změně ho pomocník
`luxos-displays` pošle příkazem `set_primary`; luxwm ho drží jen v paměti, po startu ho obnoví
`displays_command`. Shell ho čte z události `output` (`primary`). Bez volby (nebo když je vypnutý)
platí zapnutý monitor nejvíc vlevo nahoře.

## Rozložení klávesnice

luxwm skládá keymapu takto (pozdější přepisuje dřívější po položkách):

1. `org.freedesktop.locale1` na systémové sběrnici: `X11Layout`, `X11Variant`, `X11Options`,
   `X11Model` (stejný zdroj jako X11 relace, přihlašovací obrazovka a konzole);
2. `xkb_layout`, `xkb_variant`, `xkb_options`, `xkb_model` v `~/.config/luxwm/luxwm.conf`
   (píše je `luxos-keyboard` na Waylandu, když uživatel zvolí vlastní rozložení jen pro sebe).

Bez obojího platí `us`. Přepínání je volba XKB `grp:…` (výchozí v LuxOS `grp:shifts_toggle`, obě
klávesy Shift), kterou vyhodnotí xkbcommon; luxwm jen pošle událost a srovná skupinu na všech
klávesnicích. Rozložení je jedno pro celý systém (jako `group-policy=0` panelu xkb v X11 relaci),
paměť rozložení pro jednotlivá okna není.

Opakování držené klávesy: `repeat_rate` (znaky za sekundu, 0–100, 0 = vypnuto, výchozí 25) a
`repeat_delay` (ms do prvního opakování, 100–3000, výchozí 600) v `luxwm.conf`. Píše je Nastavení >
Klávesnice a pošle `reload`; luxwm je použije na všechny klávesnice při startu i po `reload` a hlásí
je v události `keyboard` (`get_state`). Hodnota mimo rozsah se omezí na mez. V X11 relaci totéž
nastavuje kanál xfconf `keyboards` (`/Default/KeyRepeat`, `Rate`, `Delay`).

## Myš a touchpad

`get_input` vrací nastavení z `luxwm.conf` (`config`, položky `mouse_*` a `touchpad_*`, popis v
`packages/luxwm/README.md`) a co libinput skutečně nastavil na každém zařízení (`devices`). Volby:
`speed` (-100..100), `accel` (`"adaptive"`/`"flat"`), `natural_scroll`, `left_handed`,
`middle_emulation`, `tap`, `tap_drag`, `disable_while_typing` (bool), `click_method`
(`"none"`/`"areas"`/`"clickfinger"`), `scroll_method` (`"none"`/`"two_finger"`/`"edge"`/`"button"`).
V `config` je `null` u volby, která v `luxwm.conf` není (platí výchozí hodnota zařízení). Zařízení
má `name`, `kind` (`"mouse"`/`"touchpad"`) a jen volby, které umí:

```json
{"ok": true, "config": {"mouse": {"speed": -40, "natural_scroll": null, ...}, "touchpad": {"tap": true, ...}},
 "devices": [{"name": "Logitech USB Optical Mouse", "kind": "mouse", "speed": -40, "accel": "adaptive",
              "natural_scroll": false, "left_handed": false, "middle_emulation": false, "scroll_method": "none"},
             {"name": "SynPS/2 Synaptics TouchPad", "kind": "touchpad", "speed": 0, "tap": true, ...}]}
```

Headless backend (testy) žádná zařízení libinput nemá, `devices` je prázdné. Nastavení zapisuje stránka
Nastavení > Myš a touchpad do `~/.config/luxwm/luxwm.conf` a pošle `reload`.

## Příklady

```sh
luxwm-msg next-layout
luxwm-msg switch-layout cz
luxwm-msg switch-workspace 2
luxwm-msg set-theme dark
luxwm-msg reload
luxwm-msg get-state
luxwm-msg get-input
luxwm-msg --raw '{"cmd": "list_windows"}'
luxwm-msg --watch keyboard workspace      # vypisuje události, dokud luxwm běží
```

`luxwm-msg` končí kódem 0 při `"ok": true`, 1 při `"ok": false` (chyba na stderr), 2 když se nedá
připojit.

V LSL:

```
load luxos_luxwm as wm

function on_wm(event):
    if event["event"] == "keyboard":
        ...
    end
    return 0
end

if wm.connect(on_wm):
    call wm.subscribe(["keyboard", "workspace"])
end
call wm.request({"cmd": "next_layout"})
```

`connect` se po pádu luxwm znovu připojuje (po 1, 2, 4 … nejvýš 30 s) a po připojení obnoví
odběry. Odpovědi chodí do volitelné funkce `request(msg, f)`; bez ní se zahodí.

## Implementace

- Jádro (`packages/luxcomp/lib/ipc.c`): soket, `SO_PEERCRED`, allowlist, rámování řádků a fronta
  odchozích dat ve smyčce událostí wlroots. LSL nemá `getsockopt`, proto přenos v C.
  API: `luxcomp_ipc_listen()`, `luxcomp_ipc_line()`, `luxcomp_ipc_send()`, `luxcomp_ipc_close()`,
  události `LUXCOMP_EV_IPC_CONNECT` (`id` klient, `a` pid, `b` 1 = privilegovaný), `LUXCOMP_EV_IPC_LINE`,
  `LUXCOMP_EV_IPC_CLOSE`.
- Politika (`luxwm.lsl`): JSON, kontrola oprávnění příkazů, odběry, stav.
- Rozložení: `luxcomp_set_layout()`, `luxcomp_layout()`, `luxcomp_layout_count()`,
  `luxcomp_layout_name()`, událost `LUXCOMP_EV_LAYOUT` (`a` = index).
