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
| LuxOS logo | Whisker Menu with the LuxOS logo. Favourites: About This Computer, Firefox, Files, Terminal, Mousepad, Welcome, Settings. Lock, sleep, restart, log out and shut down. | opens the system menu; clicking the user name opens LuxAI Account (`luxos-account`) |
| App name | name of the active application in bold (`luxos-appname`, genmon) | - |
| Open windows | icons of open windows (tasklist, grouped) | switch to that window |
| Keyboard flag | xkb plugin: the flag of the current keyboard layout, Caps Lock indicator | switches layout; "Keyboard settings" opens Keyboard Layouts (`luxos-keyboard`) |
| Tray | status icons (systray, symbolic) | - |
| "!" network warning | shown only when you are connected but there is no internet (`luxos-netcheck`) | opens the captive-portal sign-in page (`http://ping.archlinux.org/`) or Control Center |
| Sound | PulseAudio plugin (volume, media keys) | mixer: `pavucontrol` |
| Battery | icon and percentage (`luxos-battery`); hidden on computers without a battery | opens Control Center; the scroll wheel changes screen brightness (`luxos-brightness up/down`, 5 % steps, not below 10 %) |
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

- **LuxAI profile** at the top: "Sign in to LuxAI" or your account. Opens `luxos-account`.
- **Tiles:**
  - **Wi-Fi**: turns the Wi-Fi radio on or off (`nmcli radio wifi on|off`).
  - **Bluetooth**: opens the Bluetooth app (`luxos-bluetooth`).
  - **Do Not Disturb**: xfconf `xfce4-notifyd /do-not-disturb`.
  - **Dark Mode**: `luxos-appearance toggle`.
  - **Data Saver**: `luxos-datasaver toggle` (marks the connection as metered and skips background
    update checks).
  - **Battery Saver**: `luxos-powersaver toggle` (power-saver profile, no Dock magnification).
- **Display** slider: brightness. With a backlight it uses `brightnessctl`. Without one (desktop
  monitor, VM) it uses software brightness of all outputs (`luxos-displays brightness N`, saved in
  `~/.config/luxos/brightness`). The minimum is 10 %. Clicking the brightness icon opens Displays.
- **Sound** slider: `pactl set-sink-volume @DEFAULT_SINK@`. Clicking the icon mutes.
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
Mousepad, Settings and Trash. Settings are in dconf (`net.launchpad.plank.dock.settings`,
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
- **Search** (`Super+Space`, `luxos-search`): rofi with modes Apps, Windows, Files and Run. Fuzzy
  matching.
- In both, text that matches no app (or any text with **Ctrl+Enter**) is sent to LuxAI as a
  question in Agent mode (`luxai --agent "<text>"`, through `luxos-luxai-rofi`).
- Running the command again (or pressing the shortcut again) closes the window.

## Notifications

Notifications come from xfce4-notifyd. They are slightly translucent and follow light or dark mode
(themes in `luxos-themes`), and they disappear after 6 s. Do Not Disturb is in Control Center. The
bell in the top bar shows the history. `luxos-hub` also sends notifications about low memory
(earlyoom), missing drivers and no internet.

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
citrus, flow-dark, flow-light, lagoon, sunrise, twilight, waves-dark and waves-light.
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

The screen locks with `xflock4` (`Super+L`, `Ctrl+Super+Q`). The lock settings are in Screen Saver &
Lock.

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
