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
- Aplikace v sandboxu (WP-14) soket do sandboxu nedostanou: bwrap nesmí připojit
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
odpověď, pořadí odpovědí odpovídá pořadí požadavků. Neznámý příkaz: `"error": "unknown command"`,
chybný JSON: `"error": "bad request"` (spojení zůstává).

| Příkaz | Argumenty | Privilegovaný | Popis |
|---|---|---|---|
| `subscribe` | `events`: seznam témat | jen téma `window` | odběr událostí; hned po odpovědi přijde aktuální stav každého tématu |
| `get_state` | – | ne (`window` jen privilegovaným) | `{"ok": true, "state": {téma: obsah události}}` |
| `switch_layout` | `index` (od 0) nebo `layout` (kód, např. `"cz"`) | ne | přepne rozložení klávesnice |
| `next_layout` | – | ne | další rozložení (za posledním první) |
| `switch_workspace` | `number` (od 1) nebo `delta` (`-1`, `1`) | ne | přepne plochu jako zkratka |
| `reload` | – | ne | znovu načte `luxwm.conf`, rozložení klávesnice, allowlist a vzhled (jako `SIGHUP`) |
| `set_theme` | `theme`: `"light"` / `"dark"` | ne | překreslí záhlaví oken a pošle událost `theme` |
| `list_windows` | – | ano | `{"ok": true, "windows": [okno, ...]}` v pořadí od naposledy zaměřeného |
| `focus_window` | `id` | ano | zaměří okno (i na jiné ploše, obnoví minimalizované) |

Proč jsou příkazy neprivilegované: totéž dokáže každý proces uživatele i bez soketu (upraví
`~/.config/luxwm/luxwm.conf` a pošle `SIGHUP`) a přepnutí plochy nebo rozložení nic neprozradí.
Informace o cizích oknech (názvy, aplikace) a jejich ovládání
jsou privilegované stejně jako wlr-foreign-toplevel.

`set_theme` vzhled neukládá. Trvalá volba je `~/.config/luxos/appearance` (`light`/`dark`), kterou
píše `luxos-appearance` před voláním `luxwm-msg set-theme`. luxwm ji čte při startu a při `reload`.

## Události

Události nemají `id`, mají `event`. Odběr: `{"cmd": "subscribe", "events": ["keyboard", "workspace"]}`.
Když klient požádá o téma, na které nemá právo, odpověď je `"ok": false, "error": "permission denied"`
a nepřihlásí se nic.

| Téma | Událost | Kdy |
|---|---|---|
| `window` | `{"event": "window", "id": 7, "app_id": "org.gnome.Calculator", "title": "Kalkulačka"}` | zaměřené okno se změní (i jeho název nebo app_id); bez okna `id` 0 a prázdné řetězce |
| `workspace` | `{"event": "workspace", "current": 2, "count": 4}` | přepnutí plochy (hned, ne až po animaci) |
| `keyboard` | `{"event": "keyboard", "current": 1, "layouts": [{"code": "us", "variant": "", "name": "English (US)"}, {"code": "cz", "variant": "", "name": "Czech"}]}` | přepnutí rozložení (zkratka `grp:…`, příkaz, klik v liště), nový seznam po `reload` |
| `output` | `{"event": "output", "outputs": [{"name": "HDMI-A-1", "x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 100, "refresh_mhz": 60000, "usable": [0, 30, 1920, 1050]}]}` | monitor přidán nebo odebrán, změna použitelné plochy (lišta, Dock) |
| `theme` | `{"event": "theme", "theme": "dark"}` | `set_theme`, `reload`, `SIGUSR1` |

Okno v `list_windows`: `{"id", "app_id", "title", "workspace" (od 1), "focused", "minimized", "fullscreen", "maximized"}`.

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

## Příklady

```sh
luxwm-msg next-layout
luxwm-msg switch-layout cz
luxwm-msg switch-workspace 2
luxwm-msg set-theme dark
luxwm-msg reload
luxwm-msg get-state
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
