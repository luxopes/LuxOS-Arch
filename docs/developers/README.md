# LuxOS pro vývojáře aplikací

Jak napsat aplikaci, která v LuxOS působí jako doma: oznámení, která se chovají jako v Androidu,
odznak v Docku, tmavý režim a překlady. Všechno jsou běžná rozhraní (D-Bus, soubory, příkazy),
takže je použijete z Pythonu, C, Rustu, JavaScriptu (Electron) i ze skriptu v bashi.

| Téma | Co získáte | Stránka |
|---|---|---|
| Oznámení | bublina, historie pod zvonkem v liště, klik otevře to správné místo v aplikaci, zmizí, když ho vyřídíte | [notifications.md](notifications.md) |
| Dock | číslo na ikoně aplikace (nepřečtené zprávy, stahování) | [dock.md](dock.md) |
| Vzhled | světlý/tmavý režim, změna za běhu | [appearance.md](appearance.md) |
| Okno ze skla | průsvitné okno se semaforem jako Hodiny a Účet LuxAI (Python, LSL) | [glass.md](glass.md) |
| Překlady | texty v jazyce uživatele ze sdílených tabulek LuxOS | [i18n.md](i18n.md) |
| Balíček `.lux` | instalace přes Obchod LuxOS a `lux` | [../lux-package-format.md](../lux-package-format.md), příklad [../examples/hello-lux](../examples/hello-lux) |

## Rychlý start: oznámení, které se samo uklidí

```python
from gi.repository import Gio, GLib

bus = Gio.bus_get_sync(Gio.BusType.SESSION)
nid = bus.call_sync(
    "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
    "org.freedesktop.Notifications", "Notify",
    GLib.Variant("(susssasa{sv}i)", (
        "Moje aplikace", 0, "moje-aplikace", "Nová zpráva", "Ahoj!",
        ["default", "Otevřít"],                          # klik = akce "default"
        {"desktop-entry": GLib.Variant("s", "moje-aplikace"),   # název a ikona v historii
         "x-luxos-keep": GLib.Variant("b", True)},              # uložit do historie (zvonek)
        0)),                                             # 0 = nezmizí samo
    None, 0, -1, None).unpack()[0]
# ...uživatel zprávu přečetl v aplikaci:
bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
              "org.freedesktop.Notifications", "CloseNotification",
              GLib.Variant("(u)", (nid,)), None, 0, -1, None)   # zmizí i z historie
```

Podrobnosti, včetně obsluhy kliknutí, najdete v [notifications.md](notifications.md).

## Zásady

- **`desktop-entry` vždy.** Podle souboru `.desktop` LuxOS zobrazí název a ikonu aplikace a otevře ji,
  když už aplikace neběží.
- **Uklízejte po sobě.** Co uživatel vyřídil v aplikaci, zavřete přes `CloseNotification`. Jinak
  zůstane v historii a zvonek bude dál ukazovat nepřečtené.
- **Nespouštějte nic navíc.** Lišta a oznámení jsou sdílené prostředky. Žádné dotazování ve smyčce:
  sledujte signály D-Bus.
- **Testujte izolovaně.** Vlastní sběrnice (`dbus-daemon --config-file` bez aktivace služeb),
  vlastní Xvfb a dočasný `HOME`. Viz testy v `packages/luxos-desktop/tests/test_luxos_notifyd_sync.py`.
