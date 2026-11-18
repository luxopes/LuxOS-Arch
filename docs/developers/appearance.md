# Vzhled: světlý a tmavý režim

Uživatel přepíná režim v Nastavení, případně se přepíná automaticky podle východu a západu slunce
(`luxos-appearance`). LuxOS při změně nastaví všechna běžná místa najednou, takže stačí použít to,
které zná váš toolkit:

| Kde | Hodnota | Kdo to čte |
|---|---|---|
| Motiv GTK (xsettings `/Net/ThemeName`) | `WhiteSur-Light` / `WhiteSur-Dark` | aplikace GTK 3 automaticky |
| Portál `org.freedesktop.portal.Settings`, `org.freedesktop.appearance` `color-scheme` | `1` tmavý, `2` světlý | GTK 4/libadwaita, Qt 6, Electron, Firefox |
| `gsettings org.gnome.desktop.interface color-scheme` | `prefer-dark` / `prefer-light` | aplikace GNOME |
| `luxos-appearance status` | `dark` / `light` | skripty |

## Změna za běhu (portál, libovolný jazyk)

```python
from gi.repository import Gio, GLib

bus = Gio.bus_get_sync(Gio.BusType.SESSION)
PORTAL = ("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Settings")

def is_dark():
    value = bus.call_sync(*PORTAL, "ReadOne", GLib.Variant("(ss)", ("org.freedesktop.appearance", "color-scheme")),
                          None, 0, -1, None).unpack()[0]
    return value == 1

def on_changed(conn, sender, path, iface, signal, params):
    namespace, key, value = params.unpack()
    if namespace == "org.freedesktop.appearance" and key == "color-scheme":
        apply_theme(dark=(value == 1))

bus.signal_subscribe(PORTAL[0], PORTAL[2], "SettingChanged", PORTAL[1], None, 0, on_changed)
```

## Doporučení

- Barvy berte z motivu (GTK), nikoli napevno. Na skle LuxOS se pak text přizpůsobí sám.
- Ikony symbolické (`*-symbolic`) se v tmavém režimu přebarví samy.
- Nepoužívejte `luxos-appearance` k nastavování režimu. To je volba uživatele.
