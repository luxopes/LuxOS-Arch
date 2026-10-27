# The LuxOS Desktop

LuxOS gives Xfce a macOS-like look and behaviour. It uses Xfce parts (xfwm4 with its built-in
compositor, xfce4-panel, xfdesktop, xfsettingsd/xfconf, xfce4-notifyd), the Plank dock, rofi for
Search and Launchpad, and LuxOS programs from the `luxos-desktop` package (`/usr/bin/luxos-*`,
Python helpers in `/usr/lib/luxos/python`). The login session is called "LuxOS"
(`/usr/share/xsessions/luxos.desktop`).

Default settings live in `/etc/xdg/luxos` (it comes first in `XDG_CONFIG_DIRS`), so LuxOS does not
overwrite files of other packages. The user's own changes (in `~/.config`) always win. See
[configuration.md](configuration.md).

Window buttons sit on the left (close, minimize, maximize: xfwm4 `button_layout=CHM|`), titles are
centred, and a double click on the title bar maximizes. The default fonts are Inter 10 and
JetBrainsMono Nerd Font 10. The themes are WhiteSur GTK, icons and cursors, plus LuxOS icons.

## Top bar (menu bar)

The top bar is an xfce4-panel ("panel-1", 28 px, at the top of the primary monitor, translucent).
Its items, from left to right:

| Item | What it is | Click |
|---|---|---|
| LuxOS logo | Whisker Menu with the LuxOS logo (see [The LuxOS menu](#the-luxos-menu)). Favourites: About This Computer, Firefox, Files, Terminal, Text Editor, Welcome, Settings. | opens the system menu; clicking the user name or photo opens LuxAI Account (`luxos-account`) |
| App name | name of the active application in bold (`luxos-appname`, genmon) | - |
| Open windows | icons of open windows (tasklist, grouped) | switch to that window |
| Keyboard flag | xkb plugin: the flag of the current keyboard layout, Caps Lock indicator | switches layout; "Keyboard settings" opens Keyboard Layouts (`luxos-keyboard`) |
| Tray | status icons (systray, symbolic) | - |
| "!" network warning | shown only when you are connected but there is no internet (`luxos-netcheck`) | opens the captive-portal sign-in page (`http://ping.archlinux.org/`) or Control Center |
| Sound | PulseAudio plugin (volume, media keys); the menu labels its sliders "Output: <device>" (volume) and "Input: <microphone>" (microphone sensitivity), without a microphone only the output slider is shown | mixer: `pavucontrol` |
| Battery | icon and percentage (`luxos-battery`); hidden on computers without a battery | opens Control Center; the scroll wheel changes screen brightness (`luxos-brightness up/down`, 5 % steps, not below 10 %) |
| Search (magnifier) | `luxos-search --panel` (genmon) | opens or closes Search, same as `Super+Space` |
| Control Center | `luxos-control-center --panel` | opens or closes Control Center |
| Notifications | notification plugin (notification history) | - |
| Clock | e.g. "Wed 22. Oct  14:05" (`luxos-clock`, refreshed every 3 s) | opens or closes the Calendar |

`luxos-menubar` (a small C program running in the background) lets you switch between open menus of the top bar with a single
click (left or right button), as in macOS. While a menu is open, shortcuts with Super, Ctrl+Alt,
Alt+Tab, Alt+F4 and PrtSc close it and still run. It also watches monitor hotplug through RandR events and pushes the pointer to
the screen edge so an auto-hidden Dock comes out.

Panel plugins without menus (genmon, systray) run inside the panel process to save memory
(`/usr/lib/luxos/panel`). Plugins with menus stay external. LuxOS ships a patched genmon
(`xfce4-genmon-plugin` in [luxos]) with an extra tag `<scroll>command</scroll>`: the scroll wheel
runs `command up` / `command down`. The GTK module `luxos-panel-menus` (loaded by
`/usr/lib/luxos/override-bin/xfce4-panel`) removes the grey plugin name from right-click menus.

### The LuxOS menu

The menu under the LuxOS logo is Whisker Menu (patched package `xfce4-whiskermenu-plugin` in
[luxos], style in `luxos.css` of the WhiteSur themes, light and dark):

- a translucent rounded panel like the other LuxOS menus;
- at the top your profile photo (round; without a photo a coloured circle with your initial, as
  on the login screen) and name, on the right a **Log Out…** button (the Xfce dialog also offers
  Switch User, Restart and Shut Down); below it the search field "Search applications…";
- on the left your favourite applications (32 px icons), on the right the categories with an
  arrow; the selected row is a soft blue rounded highlight;
- at the bottom **Lock Screen** on the left and round **Restart**, **Sleep** and **Power Off**
  buttons with labels on the right (Restart and Power Off ask for confirmation).

Applications that Chromium installs as "Chromium Apps" appear in the Internet category instead of
a category of their own: the menu uses `/etc/xdg/luxos/menus/luxos-applications.menu` (the Xfce menu
plus a `<Move>` of `chrome-apps`; the files in `~/.config/menus` stay untouched). The labels come
from the LuxOS translations (luxos-i18n). Settings are in the `xfce4-panel` xfconf channel
(`/plugins/plugin-1`: `position-commands-alternate=false` = bar at the bottom, `custom-menu-file`,
`menu-width` 480, `menu-height` 640). Older profiles get the new layout once at login
(`luxos-session`, mark `~/.config/luxos/menu-layout-2`); favourites and other menu settings stay.
If you later change the layout in the menu settings, it is not overwritten again.

Older profiles get the Search magnifier once, before Control Center: `luxos-session` runs
`luxos-search --add-to-panel` at login (it restarts the panel; the mark
`~/.config/luxos/search-icon-added` makes sure it is never added again after you remove it). To
remove it: right-click the magnifier → Remove.

When you log out, restart or shut down, `luxos-hub` starts `luxos-session-cover`: the screen fades
to black before the compositor stops, so windows never show black edges.

Daylight saving time: in time zones with summer/winter time `luxos-hub` notifies the evening
before the change (18:00) and the morning after. Turn it off in Desktop & Dock → Top bar or with
`TIME_CHANGE=0` in `~/.config/luxos/notifications.conf`.

## Control Center

Open it with the Control Center icon in the top bar (or run `luxos-control-center`). A second click
closes it, and so do Esc and clicking elsewhere. It runs inside `luxos-hub`, so it appears
immediately (`luxos-cc-toggle` sends SIGUSR1).

Contents:

- **LuxAI profile** at the top: "Sign in to LuxAI" or your account, with your profile picture
  (`~/.face`) or the first letter of the name. Opens `luxos-account`.
- **Tiles:**
  - **Wi-Fi**: turns the Wi-Fi radio on or off (`nmcli radio wifi on|off`).
  - **Bluetooth**: opens the Bluetooth app (`luxos-bluetooth`).
  - **Do Not Disturb**: xfconf `xfce4-notifyd /do-not-disturb`.
  - **Dark Mode**: `luxos-appearance toggle`.
  - **Data Saver**: `luxos-datasaver toggle` (marks the connection as metered and skips background
    update checks).
  - **Battery Saver**: `luxos-powersaver toggle` (power-saver profile, no Dock magnification).
- **Share Wi-Fi with QR Code…** under the tiles while connected to Wi-Fi (`luxos-wifi-qr`), or
  **Join Wi-Fi with QR Code…** when Wi-Fi is on but not connected (`luxos-wifi-qr --scan`); see
  [wifi-qr.md](wifi-qr.md).
- **Display** slider: brightness. With a backlight it uses `brightnessctl`. Without one (desktop
  monitor, VM) it uses software brightness of all outputs (`luxos-displays brightness N`, saved in
  `~/.config/luxos/brightness`). The minimum is 10 %. Clicking the brightness icon opens Displays.
- **Sound** slider: `pactl set-sink-volume @DEFAULT_SINK@`. Clicking the icon mutes; moving the
  slider while muted turns the sound back on.
- **Now playing**: appears only when an MPRIS player (Firefox, Spotify, VLC, mpv…) runs, with
  Previous / Play-Pause / Next.
- **Battery**: percentage, charging state and time left or time until full. Opens Battery & Power.
- **Footer**: Desktop & Dock… (`luxos-settings`), Battery… (`luxos-power`), All Settings…
  (`xfce4-settings-manager`).

More detail on Data Saver and Battery Saver: [power-and-performance.md](power-and-performance.md).

## Dock

The Dock is Plank, started by `luxos-dock`, which restarts Plank after a crash. It sits at the
bottom with 48 px icons and 150 % magnification, and it hides itself when a window covers it
("window-dodge"). The default items are Launchpad, LuxAI, LuxOS Store, Files, Firefox, Terminal,
Text Editor, Settings and Trash. Settings are in dconf (`net.launchpad.plank.dock.settings`,
`/net/launchpad/plank/docks/dock1/`), and the launchers are in `~/.config/plank/dock1/launchers`.

Change the size, magnification, position (Bottom, Left, Right), auto-hide and opacity in
**Desktop & Dock** (`luxos-settings`, see [settings-apps.md](settings-apps.md)). To add an app, drag
it from Launchpad to the Dock. To remove one, drag it out. A dot below an icon means the app is
running.

## Launchpad and Search

- **Launchpad** (tap `Super` alone, `Super+A`, `luxos-launchpad`, also the first Dock icon): a grid of all apps
  (rofi theme `luxos-launchpad`). Settings panels of Xfce are hidden there. A few LuxOS settings
  apps get Launchpad-only copies: Displays, Keyboard Layouts, Fingerprint, Printers & Scanners
  (`X-LuxOS-Launchpad`).
- **Sorting** (buttons under the Launchpad grid, or `Alt+1`..`Alt+4`): **Alphabetical**, **Recently
  used**, **Most used** (default) and **Category** (Internet, Office, Graphics, Multimedia,
  Development, Education, Games, Science, Accessories, Settings, System, then alphabetically). The
  choice is remembered in `~/.config/luxos/launchpad-sort`. Launches from Launchpad are counted only
  locally in `~/.local/share/luxos/launchpad-usage.json` (app IDs, counts and last-use times; nothing
  is sent anywhere). The order is prepared after each launch (`~/.cache/luxos/launchpad-order-*`) and
  handed to rofi as its history, so opening Launchpad stays as fast as before.
- Without a compositor (compositing off, a VM without 3D acceleration) the rounded Launchpad and
  Search panels take a snapshot of the screen as background, so their corners are not black.
- **Search** (`Super+Space`, `luxos-search`): rofi with modes Apps, Windows, Files and Run. Fuzzy
  matching.
- In both, text that matches no app (or any text with **Ctrl+Enter**) is sent to LuxAI as a
  question in Agent mode (`luxai --agent "<text>"`, through `luxos-luxai-rofi`).
- Running the command again (or pressing the shortcut again) closes the window.

## Notifications

Notifications come from xfce4-notifyd. They are slightly translucent and follow light or dark mode
(themes in `luxos-themes`), and they disappear after 6 s. Do Not Disturb is in Control Center. The
bell in the top bar shows the history: every notification of every app is kept (xfconf
`xfce4-notifyd` `/notification-log=true`, `/log-level=always`, the last 100), not only the ones
missed during Do Not Disturb. Short on-screen indicators sent with the `transient` hint (volume) are
not kept. `luxos-hub` also sends notifications about low memory (earlyoom), missing drivers, no
internet and the daylight saving time change; the Calendar reminds of events.

- **Click** a notification to see all of it (the whole title and text, the body is cut to 3 lines
  otherwise); clicking it again runs its default action (for example opens the message) and closes it.
  A notification with nothing more to show runs the default action on the first click. Right or
  middle click closes it as before.
- **Close**: point at a notification and a small **×** appears in its top-left corner. Pointing at a
  notification also stops its timer.
- Notifications stay on top of windows, but never cover an open top-bar popup: while Control Center,
  the Calendar, the LuxOS menu, a panel menu, Launchpad or Search is open, notifications that would
  overlap it wait hidden (their timer stops) and appear when it closes. xfce4-notifyd from
  `[luxos]` watches windows mapped on the X root window, so it also works for rofi and panel menus.

## Light, dark and auto appearance

`luxos-appearance` switches the look of GTK, icons, xfwm4, notifications, the panel and the Dock all
at once:

```
luxos-appearance light | dark | toggle   # set the mode (turns Auto off)
luxos-appearance auto                    # follow sunrise/sunset
luxos-appearance status                  # light | dark (current look)
luxos-appearance mode                    # light | dark | auto (the setting)
luxos-appearance wallpaper FILE          # wallpaper on all monitors and workspaces
luxos-appearance bar-opacity 0-100       # top bar opacity (default 62)
luxos-appearance dock-opacity 0-100|default
luxos-appearance greeter-sync            # same wallpaper on the login screen (done automatically)
```

- Light mode is the default. The state is stored in `~/.config/luxos/appearance`, and the
  preferences (`APPEARANCE_AUTO`, `BAR_OPACITY`, `DOCK_OPACITY`) in `~/.config/luxos/appearance.conf`.
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
`luxos-appearance wallpaper /path/picture.jpg` (stored in the xfconf channel `xfce4-desktop`).

## Boot splash

The boot splash is Plymouth. It comes in colour variants blue (default), purple, orange, green and
light ("White" in the UI). Change it in **Desktop & Dock › Boot Screen** or from the command line:

```
luxos-splash list
luxos-splash get
pkexec luxos-splash set purple     # writes Theme= in /etc/plymouth/plymouthd.conf, runs mkinitcpio -P
```

On the live ISO the boot image is not rebuilt.

## Login and lock screen

The login screen is `luxos-greeter`, a LightDM greeter (Python + GTK). At rest it shows the
wallpaper, the date and a large clock, with keyboard, battery and network at the top right. A click
or a key shows the avatars, the password field and the power buttons. After 30 s of idle it returns
to the clock. If a fingerprint reader is set up, you can log in with your finger
([settings-apps.md](settings-apps.md#fingerprint)).

The configuration file is `/etc/lightdm/luxos-greeter.conf`, with keys `background`,
`user-background`, `clock-24h=auto`, `clock-format`, `date-format`, `idle-timeout`, `font`,
`cursor-theme`, `show-battery` and `show-network`. `/etc/lightdm/lightdm.conf.d/60-luxos-greeter.conf`
selects this greeter. To preview it without LightDM: `luxos-greeter --demo` (the password is
`luxos`).

The login screen and the screen shown when switching users use the wallpaper of the user's desktop
(in the current light or dark mode): `luxos-appearance greeter-sync` writes it to AccountsService
(`BackgroundFile`) at login, when the mode changes and, through `luxos-hub`, whenever the desktop
wallpaper changes. A wallpaper the login screen cannot read (in the home folder) is replaced by the
LuxOS wallpaper of the current mode; a `BackgroundFile` set by other means is left alone.
`LOGIN_WALLPAPER=0` in `~/.config/luxos/appearance.conf` turns this off; `user-background=false` in
`luxos-greeter.conf` makes the login screen always use `background`.

The avatar is the user's profile picture from AccountsService (`IconFile`,
`/var/lib/AccountsService/icons/<user>`); without one the screen shows the first letter of the name on
a blue-violet circle. Change it in **Profile Picture** (see [settings-apps.md](settings-apps.md#profile-picture)).

**After login** the greeter hides the clock and the form and leaves only the (slightly dimmed)
wallpaper as the last frame; the session starts at most one frame later. The X server keeps that
frame (`X -background none`); drivers that cannot (QEMU with bochs + llvmpipe, no glamor) paint it
black, so the greeter also saves the frame to the LightDM data folder of the user
(`/var/lib/lightdm-data/<user>/login-frame.raw`, removed after use, plus a small blurred wallpaper
as the last resort). `luxos-session-cover --login` (started by
`/etc/X11/xinit/xinitrc.d/60-luxos-login-cover.sh` before the session) covers the desktop while it is
being put together. As soon as the desktop (xfdesktop) and the top bar or Dock are mapped, it waits
200 ms for them to draw and then dissolves in about 0.3 s through the xfwm4 compositor, so the
wallpaper brightens and the top bar and Dock appear. It never delays anything: input goes through it,
without a compositor it waits for one at most 1.2 s, and it always ends within 5 s. With Battery
Saver on, or with GTK animations turned off (xsettings `EnableAnimations`), it just disappears
without the fade.

The screen locks with `xflock4` (`Super+L`, `Ctrl+Super+Q`). The lock settings are in Screen Saver &
Lock. The default screen saver of the locked screen, "Desktop wallpaper and clock", shows the same
wallpaper as the desktop with a large clock; the password dialog uses it too.

## Session startup and luxos-hub

`luxos-session` runs at every login (autostart). It:

- on first login: creates the standard folders and applies the default look;
- re-applies saved display settings (`luxos-displays auto`) and software brightness;
- starts `luxos-appname watch`, `luxos-menubar`, the Safe watcher (`luxos-safe-watch` user
  service, plus a "Safe" bookmark in Files) and **`luxos-hub`** (restarted if it crashes);
- re-applies Data Saver (`luxos-datasaver reapply`) and the wallpaper for new monitors;
- on first login starts the LuxOS Tour and then Welcome. After an update to a new LuxOS version it
  shows What's New.

`luxos-hub` is one light process that replaces several background programs:

- keeps Control Center (SIGUSR1) and Calendar (SIGUSR2) preloaded;
- locks the Safe on screen lock and before sleep;
- marks new networks as metered while Data Saver is on;
- notifies when earlyoom ended a program because memory ran low;
- shows the "!" network warning;
- runs the Bluetooth pairing agent (instead of blueman-applet, which is disabled);
- switches the sound output to a newly connected monitor (HDMI/DisplayPort), USB or Bluetooth
  device and back after unplugging (see [settings-apps.md](settings-apps.md#sound-output-switching));
- runs the auto light/dark check;
- once per boot, notifies about missing drivers.

## Multiple monitors

When a monitor is connected, LuxOS extends the desktop onto it. Windows from a disconnected
monitor move back to the main one. `Super+P` (or the Display key) opens a quick menu: Extend,
Mirror, Only external screen, Only this computer's screen (`luxos-displays menu`). The chosen mode
is remembered for the next connection. Resolution, refresh rate, rotation and text size are in the
Displays app. Details: [settings-apps.md](settings-apps.md#displays).

## Touchpad

`/etc/X11/xorg.conf.d/30-luxos-touchpad.conf` (libinput) sets: tap to click, two-finger tap for the
right button, tap-and-drag, scrolling by dragging along the right (and bottom) edge, click-finger
method, touchpad off while typing, and adaptive acceleration.

## Keyboard shortcuts

`Super` plays the role of the macOS Cmd key: `Super+Space` Search, `Super` alone or `Super+A` Launchpad, `Super+Q`
close, `Super+Shift+4` screenshot of an area. The full list and how to change it:
[keyboard.md](keyboard.md).
