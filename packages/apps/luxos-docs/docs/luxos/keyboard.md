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

## Typing Vietnamese (input methods)

Vietnamese is typed on an ordinary keyboard (US, Czech, …) with an **input method**, not with
another XKB layout: the fcitx5 input method with the Bamboo engine (packages `fcitx5`, `fcitx5-gtk`
and `fcitx5-bamboo`, installed with `luxos-desktop`). For example, Telex turns `Vieejt Nam` into
"Việt Nam".

- **Turn it on:** Keyboard Layouts › **Input Methods** › **Vietnamese** switch, or Add Layout… and
  search "Vietnam" → "Vietnamese (Telex, VNI)" (this turns the same switch on). It is set **for
  your account only**, applies at once and needs no administrator password.
- **Typing style:** the combo next to it: **Telex** (default), **VNI** or **VIQR**.
- **Switching:** Vietnamese is active right after turning it on and after every login.
  **Ctrl+Space** switches between English and Vietnamese (Super+Space stays Search), or click the
  input method icon in the menu bar. The XKB layout and the flag in the menu bar do not change.
- **Vietnamese language accounts:** an account whose language is Vietnamese (`vi_*`) gets it
  turned on automatically at its first login.
- For other users fcitx5 never runs. Users who set fcitx5 up themselves (an existing
  `~/.config/fcitx5/profile` and no choice made in LuxOS) are left alone; the app then says "Your
  account uses its own fcitx5 settings", and turning Vietnamese on adds it to their profile.

### Telex and VNI cheat sheet

| Result | Telex | VNI |
|---|---|---|
| â ê ô | `aa` `ee` `oo` | `a6` `e6` `o6` |
| ă | `aw` | `a8` |
| ơ ư | `ow` `uw` (also `w` alone → ư) | `o7` `u7` |
| đ | `dd` | `d9` |
| sắc (á) | `s` | `1` |
| huyền (à) | `f` | `2` |
| hỏi (ả) | `r` | `3` |
| ngã (ã) | `x` | `4` |
| nặng (ạ) | `j` | `5` |
| remove the tone | `z` | `0` |

Tone keys go after the vowel or at the end of the word (Telex `tieesng` or `tieengs` → "tiếng",
VNI `Vie65t` or `Vie6t5` → "Việt"). Pressing a mark key twice undoes it and types the letter (`ss` → "s").
VIQR types the marks after the vowel: `^` (â), `(` (ă), `+` (ơ), `'` `` ` `` `?` `~` `.` for the
five tones, and `dd` for đ. VNI needs digit keys on the number
row; on layouts whose number row types letters (such as Czech), use Telex.

### How it works

- The choice is stored in `~/.config/luxos/input-method` (`IM=vi` or `IM=none`, `VI_STYLE=Telex|VNI|VIQR`);
  the fcitx5 configuration is written to `~/.config/fcitx5/`.
- fcitx5 is started at login by `/etc/xdg/luxos/autostart/org.fcitx.Fcitx5.desktop` (it replaces
  fcitx5's own autostart) through `luxos-input-method autostart`, only when the account uses it.
- `GTK_IM_MODULE`, `QT_IM_MODULE`, `XMODIFIERS` and `SDL_IM_MODULE` are set at login by
  `/etc/X11/xinit/xinitrc.d/55-luxos-input-method.sh`, only for accounts that use it (values you set
  yourself win). When you turn it on during a session, GTK apps get it through XSETTINGS
  (`Gtk/IMModule`); it works in GTK apps, Firefox and LuxOS Terminal.
- Command line (in your own session):

  | Command | What it does |
  |---|---|
  | `luxos-input-method status` | active method (`vi`, `user` or `none`), style, whether it is installed |
  | `luxos-input-method enable [vi] [--style Telex\|VNI\|VIQR]` | turn Vietnamese on |
  | `luxos-input-method disable` | turn it off |
  | `luxos-input-method style STYLE` | change the typing style |

### Troubleshooting Vietnamese typing

- **An app ignores it:** restart apps that were already open when you turned it on. The
  environment variables are set only at login, so logging out and in again also helps.
- **Qt apps (e.g. KDE apps):** install the Qt module with `lux install fcitx5-qt`, then restart the
  app (or log in again).
- **Nothing happens when typing:** check the menu bar icon or press Ctrl+Space, and check
  `luxos-input-method status`. "Not installed" in Keyboard Layouts means a missing package:
  `lux install fcitx5 fcitx5-gtk fcitx5-bamboo`.

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
| Super+T | Terminal | `luxos-terminal` |
| Ctrl+Alt+T | Terminal | `luxos-terminal` |
| Super+, (comma) | Settings | `xfce4-settings-manager` |
| Super+. (period) | Emoji & Symbols | `luxos-emoji` |
| Ctrl+Super+Space | Emoji & Symbols (macOS habit) | `luxos-emoji` |
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
| Alt+` (grave) | Switch windows of the current app (Alt+Tab previews, only windows with the same WM_CLASS) |
| Alt+Shift+` | Switch windows of the current app backwards |
| Super+` (grave) | Next window of the same app, without previews |
| Super+Up | Maximize window |
| Super+Left / Super+Right | Tile window left / right (half screen) |
| Ctrl+Super+F, F11 | Full screen |
| Super+D | Show desktop |
| Ctrl+Super+Left / Ctrl+Super+Right | Previous / next workspace (2 workspaces by default) |
| Ctrl+Super+1 / Ctrl+Super+2 | Go to workspace 1 / 2 |

Esc and the arrow keys are bound to xfwm4's internal cancel and movement keys, which are used
while moving or resizing windows.

The ` key is the key below Esc (above Tab) in every layout: xfwm4 from [luxos] (`packages/xfwm4`)
binds shortcuts with `grave` to the physical XKB key `<TLDE>`. On the Czech layout this key types
";" and "`" is only on AltGr of other keys, so stock xfwm4 resolved `<Alt>grave` to the H key. The
actions are `cycle_app_windows_key` and `cycle_reverse_app_windows_key` (new in the LuxOS xfwm4);
older profiles get the two shortcuts once at login (`luxos-session`, marker
`~/.config/luxos/app-windows-shortcuts`), only when the keys are still free.

**Group windows by app in Alt+Tab** (Keyboard Shortcuts › Windows, off by default; xfconf
`xfwm4 /general/cycle_group_apps`): Alt+Tab shows every app once, with its most recently used
window. While holding Alt, Down or ` shows the windows of the selected app (` also moves to its
next window), Up goes back to the list of apps; releasing Alt activates the selected window.

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
