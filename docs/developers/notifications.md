# Oznámení

LuxOS používá standardní [Desktop Notifications](https://specifications.freedesktop.org/notification-spec/latest/)
(`org.freedesktop.Notifications`, démon `xfce4-notifyd` s úpravami LuxOS). Navíc oznámení
chová jako Android:

1. **Bublina** se ukáže v rohu obrazovky.
2. **Historie:** oznámení s hintem `x-luxos-keep` zůstane pod zvonkem v horní liště. Neprečtená
   oznámení = červená tečka na zvonku.
3. **Klik:** první klik na bublinu rozbalí celý text (zkrácený nadpis a text), další klik pošle
   aplikaci akci `default`. Klik na záznam v historii (okno zvonku) pošle akci `default` hned. Když
   aplikace neběží nebo akci nemá, LuxOS otevře aplikaci podle `desktop-entry`. Oznámení pak
   z historie zmizí.
4. **Vyřízeno v aplikaci:** když aplikace oznámení zavře (`CloseNotification`), zmizí i z historie.
5. **Nahrazení:** nové oznámení se stejným id (`replaces_id`) přepíše bublinu i záznam v historii.
   V historii tak bude jeden souhrn místo hromady záznamů.

## Hinty

| Hint | Typ | Význam |
|---|---|---|
| `desktop-entry` | `s` | ID souboru `.desktop` bez přípony (`moje-aplikace`). Název a ikona v historii, otevření aplikace. **Posílejte vždy.** |
| `x-luxos-keep` | `b` | `true` = uložit do historie. Bez něj je oznámení jen bublina (hlasitost, síť, „hotovo“). |
| `category` | `s` | Standardní kategorie, např. `email.arrived`, `im.received`. |
| `urgency` | `y` | 0 nízká, 1 normální, 2 kritická. |
| `transient` | `b` | `true` = nikdy do historie (i s `x-luxos-keep`). |

`expire_timeout`: `-1` = výchozí doba LuxOS (6 s), `0` = bublina zůstane, dokud ji uživatel
nezavře, kladné číslo = milisekundy.

## Celý životní cyklus (Python)

```python
from gi.repository import Gio, GLib

FDO = ("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications")
bus = Gio.bus_get_sync(Gio.BusType.SESSION)

def notify(summary, body, replaces=0, target=None):
    hints = {"desktop-entry": GLib.Variant("s", "moje-aplikace"),
             "x-luxos-keep": GLib.Variant("b", True),
             "category": GLib.Variant("s", "im.received")}
    nid = bus.call_sync(*FDO, "Notify", GLib.Variant("(susssasa{sv}i)", (
        "Moje aplikace", replaces, "moje-aplikace", summary, body,
        ["default", "Otevřít"], hints, 0)), None, 0, -1, None).unpack()[0]
    opened[nid] = target            # co otevřít po kliknutí
    return nid

opened = {}

# Klik na bublinu nebo na záznam v historii
def on_action(conn, sender, path, iface, signal, params):
    nid, action = params.unpack()
    if action == "default" and nid in opened:
        open_conversation(opened.pop(nid))

# Zavřeno: 1 vypršelo, 2 zavřel uživatel, 3 zavřela aplikace, 4 jinak (Nerušit)
def on_closed(conn, sender, path, iface, signal, params):
    nid, reason = params.unpack()
    if reason in (2, 3):
        opened.pop(nid, None)       # příště nové oznámení, ne nahrazení

bus.signal_subscribe(FDO[0], FDO[2], "ActionInvoked", FDO[1], None, 0, on_action)
bus.signal_subscribe(FDO[0], FDO[2], "NotificationClosed", FDO[1], None, 0, on_closed)

# Uživatel konverzaci přečetl přímo v aplikaci -> pryč z bubliny i z historie
def mark_read(nid):
    bus.call_sync(*FDO, "CloseNotification", GLib.Variant("(u)", (nid,)), None, 0, -1, None)
```

Akce `default` dorazí, i když bublina už zmizela (vypršela nebo platil režim Nerušit) a uživatel
klikne na záznam v historii. Aplikace proto musí `opened[nid]` držet, dokud nedostane
`NotificationClosed` s důvodem 2 nebo 3.

## Ze skriptu

```bash
id=$(notify-send -p -a "Zálohy" -i drive-harddisk -h string:desktop-entry:luxos-backup \
     -h boolean:x-luxos-keep:true "Záloha dokončena" "Uloženo 12 GB")
# ...později, když už není aktuální:
gdbus call --session --dest org.freedesktop.Notifications \
  --object-path /org/freedesktop/Notifications \
  --method org.freedesktop.Notifications.CloseNotification "$id"
```

`notify-send -A default=Otevřít` čeká na kliknutí a vypíše `default`. Hodí se pro skripty,
které mají na kliknutí něco udělat.

## Historie: API pro okna systému

Tato rozhraní používá okno Oznámení v horní liště. Aplikace je běžně nepotřebují.

| Rozhraní | Metody |
|---|---|
| `org.xfce.Notifyd` `/org/xfce/Notifyd` `org.xfce.Notifyd.Log` | `List(s start_after, u count, b only_unread)`, `Get`, `MarkRead(as)`, `MarkAllRead`, `Delete(as)`, `Clear`; signály `RowAdded`, `RowChanged`, `RowDeleted`, `Cleared` |
| `org.freedesktop.Notifications` `/cz/luxos/NotificationHistory` `cz.luxos.NotificationHistory` | `Activate(s log_id) -> b`: pošle aplikaci akci `default` a oznámení zavře. `false` = aplikace neběží, akci nemá, nebo oznámení už zavřela; okno pak otevře aplikaci podle `desktop-entry`. |

Záznam historie: `(s id, x čas_µs, s časové_pásmo, s desktop_entry, s název_aplikace, s ikona,
s nadpis, s text, a(ss) akce, i expire_timeout, b přečteno)`.

Párování oznámení a historie dělá GTK modul `luxos-notifyd` v procesu `xfce4-notifyd`
(`packages/luxos-desktop/files/src/luxos-notifyd.c`). Drží ho jen v paměti, takže po restartu
`xfce4-notifyd` starší záznamy aplikace nesmaže a klik na ně otevře jen aplikaci.

## Kontrolní seznam

- [ ] `desktop-entry` odpovídá názvu vašeho `.desktop` souboru.
- [ ] Důležitá oznámení mají `x-luxos-keep`, dočasná ne.
- [ ] Akce `default` otevře přesně tu věc, o které oznámení mluví.
- [ ] Vyřízené oznámení zavřete (`CloseNotification`).
- [ ] Opakované události nahrazujte stejným id (souhrn), místo aby přibývala nová oznámení.
