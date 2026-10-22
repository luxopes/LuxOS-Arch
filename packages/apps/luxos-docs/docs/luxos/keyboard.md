# Keyboard Layouts and Keyboard Shortcuts

LuxOS has two keyboard apps: **Keyboard Layouts** (`luxos-keyboard`), which sets the layouts and
how to switch between them for the whole system, and **Keyboard Shortcuts** (`luxos-shortcuts`),
which shows and edits the global shortcuts. In shortcuts, `Super` (the Windows key) plays the role
of the macOS Cmd key.

## Keyboard Layouts (luxos-keyboard)

Open it from Launchpad ("Keyboard Layouts"), by clicking the keyboard flag in the top bar and
choosing keyboard settings, or by running `luxos-keyboard`. (In LuxOS, `xfce4-keyboard-settings`
with no arguments also opens this app.)

- **Layouts**: up to **4** (an XKB limit). The first one is the default. Add Layout… lists common
  layouts first (English (US), Czech, Czech (QWERTY), Slovak, German, English (UK), French, Spanish,
  Italian, Polish, Hungarian, Ukrainian, Portuguese, Portuguese (Brazil), Swedish), and you can
  search all XKB layouts and variants. Each layout can be moved up, moved down or removed.
- **Switching**: "Switch layouts with" one of these:

  | Choice | XKB option |
  |---|---|
  | Both Shift keys (default) | `grp:shifts_toggle` |
  | Alt + Shift | `grp:alt_shift_toggle` |
  | Ctrl + Shift | `grp:ctrl_shift_toggle` |
  | Caps Lock | `grp:caps_toggle` |
  | Menu key | `grp:menu_toggle` |
  | Only by clicking the flag in the menu bar | (none) |

  Super+Space is not offered, because it opens Search. "Both Shift keys" means pressing left and
  right Shift together; it does not clash with shortcuts such as Alt+Shift+Tab. Older LuxOS
  installs that still had the previous default (only `grp:alt_shift_toggle`) are switched to
  `grp:shifts_toggle` by the `luxos-desktop` package update (takes effect at the next login); a
  layout switch chosen by the user is never changed.
- A test field ("Type here to test your keyboard"). Changes are tried right away in the running
  session (`setxkbmap`). If you close the window without applying them, the old layout comes back.
- **Apply to All Users and the Login Screen** saves through `localectl set-x11-keymap`
  (systemd-localed). This asks for administrator authentication (polkit). It writes
  `/etc/X11/xorg.conf.d/00-keyboard.conf`, and localed derives the console keymap in
  `/etc/vconsole.conf` from it.
- **More Keyboard Settings…** opens the original Xfce dialog (`/usr/bin/xfce4-keyboard-settings`),
  which has key repeat and similar settings.

### How layouts are applied

By default every user follows the system layouts: the xfconf channel `keyboard-layout` has
`/Default/XkbDisable = true` (default file in `/etc/xdg/luxos`). If a user turned on their own
layouts in the Xfce keyboard settings (`XkbDisable = false`), those override the system ones. The
app then shows "Your account uses its own keyboard layouts from Xfce settings", and clicking Apply
switches the account back to the system layouts.

The installer (text and graphical) writes the same file format, so layouts chosen during
installation also show up here.

### Troubleshooting layouts

- **Wrong layout at login or in the console:** apply it again in Keyboard Layouts. That is the only
  place that sets it for the login screen and the console.
- **The layout changes only in one account:** that account has its own Xfce layouts. Click Apply in
  Keyboard Layouts, or check with `xfconf-query -c keyboard-layout -p /Default/XkbDisable` (should
  be `true`).
- **Cannot switch layouts:** check the "Switch layouts with" choice (default: both Shift keys
  pressed together). With "Only by clicking the flag", there is no key combination.
- **Check the current settings:** `localectl status` (system), `setxkbmap -query` (session).

## Keyboard Shortcuts (luxos-shortcuts)

Open it with `luxos-shortcuts`, from Welcome (Shortcuts) or from the last page of the LuxOS Tour.
Shortcuts are stored in the xfconf channel `xfce4-keyboard-shortcuts`. Commands are under
`/commands/custom/<shortcut>` (run by xfsettingsd), and window actions are under
`/xfwm4/custom/<shortcut>` (xfwm4). Changes apply at once.

Sections: **Windows**, **Apps & System**, **Screenshots**, **Custom Shortcuts**, and **Other Xfce
Shortcuts** (stock Xfce shortcuts that LuxOS keeps).

### Change, turn off, add and reset

- **Change**: click a shortcut, then press the new combination ("Press the new shortcut for …").
  **Esc** cancels and **Backspace** turns the shortcut off. A shortcut must use at least one of
  Ctrl, Alt or Super. The exceptions are single function keys (F1–F39), multimedia/XF86 keys,
  Print, Pause, Scroll Lock and Menu.
- **Conflicts**: if the combination is already used, the app says "“X” is already used by “Y”" and
  offers **Replace**. Replacing frees the key from the other action.
- **Turn off**: a system (default) shortcut is turned off by setting an empty command. It cannot be
  deleted, because resetting the xfconf property would bring back the system value. A user-added
  shortcut is deleted.
- **Restore Default** (per action) or **Restore All Defaults…**. Custom shortcuts are kept unless a
  default shortcut needs their keys.
- **Add Shortcut…**: a name (e.g. "Open my notes"), a command (or Choose App…), and Record
  Shortcut…. The names of custom shortcuts are stored in `~/.config/luxos/shortcuts.json`. xfconf
  itself only stores the command.
- The layout switching shortcut is shown here but is set in Keyboard Layouts ("Set together with
  the keyboard layouts").
- **Super key alone opens Launchpad** (under Apps & System, on by default): a switch for tapping
  Super on its own (see "Other keys" below). Super+A keeps working either way.

From a script, use `xfconf-query -c xfce4-keyboard-shortcuts -l -v` to list shortcuts. For example,
`xfconf-query -c xfce4-keyboard-shortcuts -p '/commands/custom/<Super>k' -n -t string -s 'firefox'`
adds one. Run this only inside the user's own session.

## Default shortcuts

These are the LuxOS defaults from `/etc/xdg/luxos/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml`.
When the package is built, the stock Xfce defaults are merged in, so other Xfce shortcuts may exist
as well. They appear under "Other Xfce Shortcuts".

### Apps and system

| Shortcut | Action | Command |
|---|---|---|
| Super+Space | Search | `luxos-search` |
| Super (tap alone) | Launchpad (open/close) | `luxos-launchpad` (via `luxos-menubar`) |
| Super+A | Launchpad | `luxos-launchpad` |
| Launch A key (XF86LaunchA) | Launchpad | `luxos-launchpad` |
| Super+E | Files | `thunar` |
| Super+T | Terminal | `xfce4-terminal` |
| Ctrl+Alt+T | Terminal | `xfce4-terminal` |
| Super+, (comma) | Settings | `xfce4-settings-manager` |
| Super+L | Lock screen | `xflock4` |
| Ctrl+Super+Q | Lock screen | `xflock4` |
| Super+Alt+Esc | System Monitor (force quit) | `luxos-monitor` |
| Ctrl+Shift+Esc | System Monitor (force quit) | `luxos-monitor` |
| Super+P | Displays quick menu | `luxos-displays menu` |
| Display key (XF86Display) | Displays quick menu | `luxos-displays menu` |
| Calculator key (XF86Calculator) | Calculator | `luxos-calculator` |
| Ctrl+Alt+Delete | Log out or shut down | `xfce4-session-logout` |
| Power key (XF86PowerOff) | Log out or shut down | `xfce4-session-logout` |

### Screenshots

| Shortcut | Action | Command |
|---|---|---|
| Super+Shift+3 | Screenshot of the whole screen | `luxos-screenshot --screen` |
| Super+Shift+4 | Screenshot of a region (Space = window) | `luxos-screenshot --portion` |
| Super+Shift+5 | Screenshot tool (floating bar) | `luxos-screenshot` |
| Print | Screenshot tool | `luxos-screenshot` |
| Shift+Print | Screenshot of a region | `luxos-screenshot --portion` |

### Windows (xfwm4)

| Shortcut | Action |
|---|---|
| Super+Q, Alt+F4 | Close window |
| Super+M, Super+H, Super+Down | Minimize window |
| Super+Tab, Alt+Tab | Switch windows |
| Super+Shift+Tab, Alt+Shift+Tab | Switch windows backwards |
| Super+` (grave) | Switch windows of the same app |
| Super+Up | Maximize window |
| Super+Left / Super+Right | Tile window left / right (half screen) |
| Ctrl+Super+F, F11 | Full screen |
| Super+D | Show desktop |
| Ctrl+Super+Left / Ctrl+Super+Right | Previous / next workspace (2 workspaces by default) |
| Ctrl+Super+1 / Ctrl+Super+2 | Go to workspace 1 / 2 |

Esc and the arrow keys are bound to xfwm4's internal cancel and movement keys, which are used
while moving or resizing windows.

### Other keys

- Volume and media keys are handled by the sound plugin in the top bar.
- Layout switching: both Shift keys together by default (Keyboard Layouts).
- Tapping **Super alone** (press and release within 0.4 s, no other key or mouse button in
  between) opens Launchpad, like the Start key on Windows; tapping it again closes it. Super+key
  shortcuts never trigger it. It is detected by `luxos-menubar` from passive XInput2 raw key
  events (no key grabs) and does nothing while another program holds the keyboard (locked screen,
  screensaver, open menu, recording a shortcut). Turn it off in Keyboard Shortcuts ("Super key
  alone opens Launchpad"); this creates `~/.config/luxos/super-launchpad-off`, which
  `luxos-menubar` checks every 5 seconds.
- In Launchpad and Search, Ctrl+Enter sends the typed text to LuxAI.
- In the Calculator, Ctrl+1 and Ctrl+2 switch between the basic and scientific modes.
