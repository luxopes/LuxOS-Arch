# Top bar options and desktop widgets

The top bar of LuxOS can have square or rounded bottom corners, with the clock on the right or in the middle. Desktop widgets show the time,
weather, month, computer usage and music in the corner of the desktop. Everything is switched with
`luxos-appearance` and `luxos-widgets` and applies right away.

In the Wayland session (`luxos-bar`) the bar has rounded corners and the clock in the middle unless
`appearance.conf` says `BAR_STYLE=classic` or `BAR_CLOCK=right`.

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
- **Clock in the middle** (Desktop & Dock › Menu Bar › Clock in the middle, or
  `luxos-appearance bar-clock center`): the plugin draws the time in the
  centre of the whole bar (not of the plugin, so it does not move when the app name changes) and hides
  the clock on the right; the Calendar then opens centred under it. `bar-clock right` restores it.
  The change is applied without restarting the panel.
- **Rounded corners** (Desktop & Dock › Menu Bar › Rounded corners, or
  `luxos-appearance bar-style rounded`): the bar stays flush with the top
  edge of the screen and its two bottom corners are rounded (10 px, managed block in
  `~/.config/gtk-3.0/gtk.css`, transparent separators at both ends). Under a window the corners are
  square again (class `luxos-covered` set by the plugin), so no wallpaper shows in them.
  `bar-style classic` has square corners.
- **White text** (`luxos-appearance bar-text white`): white text in light mode as well, with a soft
  shadow; the bar is then tinted dark (smoked glass) so the text stays readable on any wallpaper.
  On a wallpaper that is too light for white text (white, beige, LuxOS Light/Citrus) the bar switches
  by itself to dark text and dark icons (clock, app name, status icons incl. the Wi-Fi indicator,
  workspace numbers, battery) with a light tint, and back to white on a darker wallpaper. The plugin
  decides from the WCAG contrast of white text over the wallpaper area under the bar (on the monitor
  with the bar, wallpaper of the active workspace): dark text below 2.0 : 1, white again above
  2.3 : 1, so a wallpaper on the edge does not make the bar flicker. Lighter but still readable
  wallpapers such as Sunrise (about 2.4 : 1, plus the shadow and the soft veil) keep white text.
  The switch needs no panel restart: the plugin sets the class `luxos-ink-dark` / `luxos-ink-white`
  on the bar window (rules in the managed `gtk.css` block), so everything drawn by the panel itself
  changes at once; the decision is stored in `~/.config/luxos/bar-ink` by
  `luxos-appearance bar-ink dark|white live`, and the plugins running in their own processes (logo
  menu, keyboard layout, sound, notifications bell) are restarted by the panel in a fraction of a
  second to load it. Switching back and forth quickly (workspaces with different wallpapers)
  restarts them only once at the end. It is re-checked when the wallpaper, workspace, monitor or bar
  opacity changes. Legacy XEmbed tray icons (GtkStatusIcon in GTK 3 apps) take the bar colour only
  when the app starts - GTK does not repaint them later; StatusNotifier icons (Wi-Fi, Bluetooth and
  most apps) follow at once. Without `live` (`luxos-appearance bar-ink dark|white`) the panel is
  restarted.
- **Shade under the bar on a very bright wallpaper** (like macOS): when the bar text is white (dark
  mode, or `bar-text white`) and the wallpaper at the top of the screen is very bright (white, beige,
  a white linen texture), the wallpaper under the bar and a little below it gets darker with a smooth
  fade to nothing - up to 38 % black at the top edge, gone after 128 px. It is not a darker bar: the
  plugin paints the shade into the wallpaper strip of the bar and below the bar into its own
  transparent desktop window (above the wallpaper, below widgets and windows, sticky, it takes no
  clicks - right-click on the desktop works there as everywhere). With it the white text keeps at
  least 4.5 : 1 contrast (WCAG AA), so it stays white; dark text is used only when even that is not
  enough. Strength follows the brightness of the wallpaper band under the bar (stored per wallpaper,
  so switching workspaces only repaints the fade): none on ordinary wallpapers - Sunrise, Lagoon and
  all dark ones look exactly as before -, partial on LuxOS Light/Citrus, full on white. It follows the
  wallpaper of the active workspace and goes away by itself with a normal wallpaper. It needs the
  compositor (the default); without it the bar behaves as before. Turn it off with
  `luxos-appearance desktop-scrim off` (`DESKTOP_SCRIM=0`) or in **Desktop & Dock › Wallpaper**;
  the same switch turns off the widget shadows below.
- **Wallpaper of all workspaces:** like xfdesktop, the bar takes the wallpaper of workspace 0 for
  every workspace unless "Apply to all workspaces" is turned off in the advanced desktop settings
  (`/backdrop/single-workspace-mode`); earlier it painted a stale wallpaper of the workspace instead.

```
luxos-appearance bar-style classic|rounded    # square / rounded bottom corners
luxos-appearance bar-clock right|center       # clock on the right / in the middle of the bar
luxos-appearance bar-text auto|white          # text colour of the bar (white also in light mode)
luxos-appearance desktop-scrim on|off         # shade under the bar and widgets on a very bright wallpaper
```

The choices are stored in `~/.config/luxos/appearance.conf` (`BAR_STYLE`, `BAR_CLOCK`, `BAR_TEXT`,
`DESKTOP_SCRIM`).
At login `luxos-appearance panel-css` puts `luxos-bar` in place of the expanding separator of a bar
from older versions (a customised bar without that separator stays as it is). For the rest of the
top bar see [The LuxOS Desktop](desktop.md).

## Desktop widgets

`luxos-widgets` shows widgets on the desktop like on Android: each widget is its own card.

- **Move:** drag a card anywhere; it snaps to an 8 px grid and keeps its place
  (`POS_<widget>=x,y` relative to the work area of the primary monitor). Cards without a saved
  place stack in the top corner under the bar.
- **Right-click** a card: **Edit Widgets…** (the gallery) or **Remove**.
- **Right-click the desktop:** **Edit Widgets…** under **Desktop Settings…** (GTK module
  `luxos-desktop-menu` loaded into xfdesktop by `/usr/lib/luxos/override-bin/xfdesktop`; it is shown
  only when `luxos-widgets` is installed and is not passed on to apps started from the desktop).
- **Desktop & Dock › Widgets:** **Show widgets on the desktop** (the same as `luxos-widgets on|off`;
  the switch follows changes made in the gallery) and **Edit Widgets…**.
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

Each card is frosted glass made from the blurred wallpaper right behind it: light glass with dark
text over a light wallpaper, darker glass with white text over a dark one, always with at least
4.5 : 1 contrast, a light border and a soft shadow. The wallpaper is the one the desktop shows: the
primary monitor and the active workspace (like the bar; earlier always workspace 0 of the last
monitor in xfconf - with a different wallpaper per workspace or an old monitor entry the cards were
coloured after a wallpaper that was not on screen). On a very bright wallpaper (white, beige, white
linen) each card also gets a soft dark shadow cast below it, so the light card stands out from the
light desktop like on macOS; ordinary wallpapers (Sunrise and darker) have no extra shadow.
`DESKTOP_SCRIM=0` turns the shadow off together with the shade under the bar. The transparent edge
of a card window takes no clicks any more - they go to the desktop. A new wallpaper, workspace or a
move recolours the card; materials are kept per wallpaper, so switching workspaces does not reload
anything.

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
