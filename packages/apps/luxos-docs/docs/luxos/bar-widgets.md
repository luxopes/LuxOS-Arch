# Top bar options and desktop widgets

The top bar of LuxOS can have square or rounded bottom corners, with the clock on the right or in the middle. Desktop widgets show the time,
weather, month, computer usage and music in the corner of the desktop. Everything is switched with
`luxos-appearance` and `luxos-widgets` and applies right away.

## The luxos-bar plugin

Between the left and the right part of the top bar is the `luxos-bar` plugin (a C plugin running inside the panel,
`/usr/lib/luxos/panel/lib/xfce4/panel/plugins/libluxos-bar.so`) instead of an expanding separator:

- **Wallpaper under the bar:** the plugin paints the part of the wallpaper that lies under the bar
  into the bar, with the bar's tint (`BAR_OPACITY`). It looks like a translucent bar over the
  wallpaper, but a window behind the bar (a full-screen browser left in the background, a window
  moved under the bar) never shows through and the bar never turns black. It follows the wallpaper
  of the current workspace and the light/dark mode. Other options in
  `~/.config/luxos/appearance.conf`: `BAR_COVER=translucent` (real translucency) and
  `BAR_COVER=solid` (translucent, fully opaque when a window reaches under the bar; desktop widgets
  and other keep-below windows never count).
- **Clock in the middle** (`luxos-appearance bar-clock center`): the plugin draws the time in the
  centre of the whole bar (not of the plugin, so it does not move when the app name changes) and hides
  the clock on the right; the Calendar then opens centred under it. `bar-clock right` restores it.
  The change is applied without restarting the panel.
- **Rounded corners** (`luxos-appearance bar-style rounded`): the bar stays flush with the top
  edge of the screen and its two bottom corners are rounded (10 px, managed block in
  `~/.config/gtk-3.0/gtk.css`, transparent separators at both ends). Under a window the corners are
  square again (class `luxos-covered` set by the plugin), so no wallpaper shows in them.
  `bar-style classic` has square corners.
- **White text** (`luxos-appearance bar-text white`): white text in light mode as well, with a soft
  shadow; the bar is then tinted dark (smoked glass) so the text stays readable on any wallpaper.

```
luxos-appearance bar-style classic|rounded    # square / rounded bottom corners
luxos-appearance bar-clock right|center       # clock on the right / in the middle of the bar
luxos-appearance bar-text auto|white          # text colour of the bar (white also in light mode)
```

The choices are stored in `~/.config/luxos/appearance.conf` (`BAR_STYLE`, `BAR_CLOCK`, `BAR_TEXT`).
At login `luxos-appearance panel-css` puts `luxos-bar` in place of the expanding separator of a bar
from older versions (a customised bar without that separator stays as it is). For the rest of the
top bar see [The LuxOS Desktop](desktop.md).

## Desktop widgets

`luxos-widgets` shows widgets on the desktop like on Android: each widget is its own card.

- **Move:** drag a card anywhere; it snaps to an 8 px grid and keeps its place
  (`POS_<widget>=x,y` relative to the work area of the primary monitor). Cards without a saved
  place stack in the top corner under the bar.
- **Right-click** a card: **Edit Widgets…** (the gallery) or **Remove**.
- **Widgets gallery** (`luxos-widgets settings`, **Widgets** in Launchpad): live previews of all
  widgets with **Add** / **Remove**, a switch to show or hide all widgets and **Default Layout**
  (forget the saved places).

The widgets:

- **Clock & Weather:** the date and the time in large digits; on the right the weather of the place
  chosen in the Weather app (colour icon, temperature, condition, city). Click the time: Clock
  (`luxos-clock-app`, see [Apps](apps.md#clock)); the weather: Weather.
- **System Health:** the system name (e.g. "LuxOS Sirius"), the state (Excellent / Good / Busy from
  CPU over the last 8 s, memory and storage) and CPU, memory and storage (`/`) usage as open rings,
  refreshed every 2 s. Click: System Monitor.
- **Now Playing:** what is playing (MPRIS: title, artist) with Play/Pause and Next; shown only when a
  player has something.
- **Calendar:** the current month with today highlighted. Click: Calendar.

Each card is tinted glass: its colour is the average colour of the wallpaper right behind it, darker
and more saturated, with white text, a light border and a soft shadow. Over a bright wallpaper the
card is less transparent, so the white text stays readable. A new wallpaper or a move recolours it.

```
luxos-widgets on          # turn widgets on (and start them)
luxos-widgets off         # turn them off
luxos-widgets settings    # the widgets gallery
```

Widgets are off by default. Settings are in `~/.config/luxos/widgets.conf` and apply at once:
`ENABLED=1`, `WIDGETS=today,system,music` (choice and order, also `calendar`), `POS_*`,
`SIDE=right|left` (side of the default stack). The cards stay below other windows, on all
workspaces, without a taskbar entry and without taking focus. Weather comes from the Weather app
summary (at most 3 hours old) or from `luxos-weather --json forecast` every 30 minutes when a place
is saved; widgets never look up the location themselves. The program is written in LSL
(`files/lsl/luxos-widgets.lsl`), started by `luxos-session`, and exits right away when widgets are off.
