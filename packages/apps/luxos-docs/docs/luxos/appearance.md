# Appearance, Wallpapers and Desktop Icons

Light, dark and automatic appearance, wallpapers (also per monitor in the Wayland session), desktop
icons on Wayland and the boot splash. The rest of the desktop (top bar, Control Center, Dock, Launchpad,
notifications, login) is described in [desktop.md](desktop.md).

## Light, dark and auto appearance

`luxos-appearance` switches the look of GTK, icons, xfwm4, notifications, the panel and the Dock all
at once:

```
luxos-appearance light | dark | toggle   # set the mode (turns Auto off)
luxos-appearance auto                    # follow sunrise/sunset
luxos-appearance status                  # light | dark (current look)
luxos-appearance mode                    # light | dark | auto (the setting)
luxos-appearance wallpaper FILE [OUTPUT] # wallpaper on all monitors and workspaces, or on one output (Wayland)
luxos-appearance wallpaper-mode fill|fit|center|tile [OUTPUT]   # how the wallpaper is shown (Wayland)
luxos-appearance bar-opacity 0-100       # top bar opacity (default 62)
luxos-appearance bar-style|bar-text|desktop-scrim ...  # bar-widgets.md
luxos-appearance dock-opacity 0-100|default
luxos-appearance greeter-sync            # same wallpaper on the login screen (done automatically)
```

- Light mode is the default. The state is stored in `~/.config/luxos/appearance`, and the
  preferences (`APPEARANCE_AUTO`, `BAR_*`, `DOCK_OPACITY`) in `~/.config/luxos/appearance.conf`.
- **Auto** computes sunrise and sunset offline from the time zone (`luxos_sun.py`, using the
  coordinates of the zone's city in `/usr/share/zoneinfo/zone1970.tab`, NOAA formula; Prague if the
  zone is unknown). `luxos-hub` checks every 5 minutes. To see today's times, run
  `python3 /usr/lib/luxos/python/luxos_sun.py times`.
- The same switch is in Control Center (Dark Mode), Desktop & Dock (Light / Dark / Auto), Welcome
  and the LuxOS Tour.

## Wallpapers

LuxOS wallpapers are in `/usr/share/backgrounds/luxos`: aurora-blue, aurora-orange, aurora-purple,
citrus, flow-dark, flow-light, lagoon, sunrise and twilight.
`luxos-dark.jpg` and `luxos-light.jpg` are the defaults for each mode (links to flow-dark and
flow-light). When you switch the mode, the default wallpaper changes with it, but a wallpaper you
picked yourself stays.

Choose one in **Desktop & Dock › Wallpaper**. That panel also shows pictures from
`~/Pictures/Wallpapers`, and "Choose…" accepts any picture. From the command line:
`luxos-appearance wallpaper /path/picture.jpg` (stored in the xfconf channel `xfce4-desktop`
and as `WALLPAPER=` in `~/.config/luxos/appearance.conf`).

In the Wayland session the wallpaper is drawn by `luxos-backdrop` (user unit `luxos-backdrop.service`)
from `appearance.conf`: `WALLPAPER`, `WALLPAPER_<OUTPUT>` for one monitor (`WALLPAPER_HDMI_A_1`),
`WALLPAPER_MODE[_<OUTPUT>]` = `fill` (default, crops like xfdesktop "Zoomed"), `fit`, `center` or `tile`,
and `WALLPAPER_COLOR=#rrggbb` around a smaller picture. Changes show at once, also in the glass of the top
bar and the Dock. Right-clicking the desktop offers New Folder (in `~/Desktop`, named right away),
Change Wallpaper…, Edit Widgets… and Displays….

Desktop icons on Wayland follow the same xfconf settings as on X11 (channel `xfce4-desktop`,
`desktop-icons/style` 2 = file icons, 0 = none; `icon-size`, `font-size`, `file-icons/show-home`,
`show-filesystem`, `show-trash`, `show-removable`). They show the files in `~/Desktop` and mounted
removable drives on the first monitor, in columns from the top left below the bar:

- click selects, double-click (or Enter) opens in the default app; a `.desktop` launcher starts its
  app only when it is executable, like in Thunar
- drag from an empty spot selects with a rectangle, dragging icons moves them (positions are kept in
  `~/.config/luxos/desktop-icons`)
- right-click an icon: Open, Rename…, Move to Trash (drives: Open, Eject); keys: arrows, Enter, F2,
  Delete, Escape, Menu
- files dropped from the file manager are copied (or moved, if the file manager asks for a move) to
  `~/Desktop` where they were dropped

The desktop takes the keyboard only while the pointer is over it, so a click into a window always
gives the window the keyboard back. Thumbnails of pictures are not shown yet.

## Boot splash

The boot splash is Plymouth. It comes in colour variants blue (default), purple, orange, green and
light ("White" in the UI). Change it in **Desktop & Dock › Boot Screen** or from the command line:

```
luxos-splash list
luxos-splash get
pkexec luxos-splash set purple     # writes Theme= in /etc/plymouth/plymouthd.conf, runs mkinitcpio -P
```

On the live ISO the boot image is not rebuilt.
