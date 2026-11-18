# Dock: číslo na ikoně

Dock LuxOS (Plank) podporuje rozhraní `com.canonical.Unity.LauncherEntry`. Aplikace pošle signál
`Update` a na její ikoně se ukáže číslo, například počet nepřečtených zpráv.

```python
from gi.repository import Gio, GLib

bus = Gio.bus_get_sync(Gio.BusType.SESSION)

def set_badge(count):
    bus.emit_signal(None, "/cz/example/MojeAplikace", "com.canonical.Unity.LauncherEntry", "Update",
                    GLib.Variant("(sa{sv})", ("application://moje-aplikace.desktop", {
                        "count": GLib.Variant("x", count),
                        "count-visible": GLib.Variant("b", count > 0)})))
```

- První argument je `application://<soubor>.desktop`, takže platí i pro aplikace bez okna (služby na pozadí).
- Cesta objektu je libovolná, jen ať je v rámci aplikace stálá.
- Signál posílejte jen při změně čísla, ne pravidelně.
- Pošta LuxOS to tak dělá v `packages/apps/luxos-mail/files/mail_service.lsl`, funkce `update_badge`.
