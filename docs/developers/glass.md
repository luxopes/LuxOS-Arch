# Okno z matného skla

Aplikace LuxOS (Hodiny, Účet LuxAI) mají okno jako průsvitné aplikace v macOS. Pod oknem je
rozostřená tapeta plochy, přes ni mléčný závoj a odlesk, rohy jsou zaoblené, vlevo nahoře je
semafor (zavřít, minimalizovat, maximalizovat) a okno nemá lištu správce oken.

X11/xfwm4 rozmazání pod oknem neumí, proto se kreslí výřez tapety pod oknem. Okno tedy
neprosvítá na jiná okna, jen na plochu.

## Python (GTK 3)

```python
import sys
sys.path.insert(0, "/usr/lib/luxos/python")
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

try:
    import luxos_glass as glass          # balíček luxos-desktop
except ImportError:
    glass = None                         # jinde klasické okno

win = Gtk.Window(title="Moje aplikace")
win.set_default_size(520, 600)
root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
if glass:
    glass.setup(win, can_resize=True)
    glass.set_dark(glass.theme_is_dark(win))
    bar = Gtk.Box(margin_start=16, margin_end=16, margin_top=12)
    bar.pack_start(glass.lights(win, lambda _b: win.close()), False, False, 0)
    bar.pack_start(Gtk.Label(label="Moje aplikace"), True, True, 0)
    root.pack_start(bar, False, False, 0)
else:
    win.set_titlebar(Gtk.HeaderBar(show_close_button=True, title="Moje aplikace"))
root.pack_start(Gtk.Label(label="Obsah"), True, True, 0)
win.add(root)
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
```

| Funkce | Co dělá |
|---|---|
| `setup(win, can_resize=True)` | okno bez dekorací, RGBA, sklo, tažení za prázdné místo, změna velikosti za okraj, dvojklik = maximalizace (`False` = pevná velikost) |
| `lights(win, on_close)` | semafor; `on_close(button)` obsluhuje aplikace (u pevné velikosti bez zeleného tlačítka) |
| `set_dark(bool)` | tmavé sklo se světlým textem |
| `theme_is_dark(widget)` | tmavý režim LuxOS (motiv `*-Dark` nebo prefer-dark) |
| `install_css()` | styly semaforu a průhledných posuvných oblastí (volá `setup` sám) |

Okno dostane třídu `lg-window`. Pozadí obsahu nechte průhledné a karty kreslete poloprůhledně,
podle barev v `packages/luxos-account/files/luxos-account` (`GLASS_LIGHT`, `GLASS_DARK`, `GLASS_CSS`)
nebo v Hodinách. Při změně režimu za běhu sledujte `notify::gtk-theme-name` na `Gtk.Settings`.

Tapeta se rozmazává ve vlákně (asi 0,4 s). Do té doby je okno jen v barvě skla.

## LSL

`load luxos_glass as glass` a stejné funkce (`glass.setup`, `glass.lights`, `glass.set_dark`,
`glass.CSS`), viz hlavička `packages/luxos-desktop/files/lsl/luxos_glass.lsl` a Hodiny
(`luxos-clock-app.lsl`).

Python a LSL dávají stejné pixely, hlídá to `packages/luxos-desktop/tests/test_luxos_glass_py.py`.
