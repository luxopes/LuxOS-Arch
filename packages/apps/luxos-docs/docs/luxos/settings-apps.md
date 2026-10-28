# LuxOS Settings Apps

LuxOS replaces several Xfce settings dialogs with simpler apps of its own. Most of them are in
Launchpad and in Settings (`xfce4-settings-manager`, `Super+,`). The original Xfce dialogs are
redirected to the LuxOS apps through wrappers in `/usr/lib/luxos/override-bin`:

- `xfdesktop-settings` opens Desktop & Dock;
- `xfce4-display-settings` opens Displays;
- `xfce4-keyboard-settings` with no arguments opens Keyboard Layouts;
- `xfce4-screenshooter` opens Screenshot.

| App | Command | What it sets |
|---|---|---|
| Desktop & Dock | `luxos-settings` | appearance, boot screen, wallpaper, Dock, menu bar |
| Displays | `luxos-display-settings` | resolution, refresh rate, rotation, text size, multiple monitors |
| Keyboard Layouts | `luxos-keyboard` | layouts and switching, for all users ([keyboard.md](keyboard.md)) |
| Keyboard Shortcuts | `luxos-shortcuts` | global shortcuts ([keyboard.md](keyboard.md)) |
| Battery & Power | `luxos-power` | battery info, power mode, Battery Saver, screen-off and sleep times, lid |
| Bluetooth | `luxos-bluetooth` | turn Bluetooth on or off, pair and connect devices |
| Fingerprint | `luxos-fingerprint` | fingerprints for login, lock, sudo, polkit |
| Profile Picture | `luxos-profile-picture` | the picture of your account (login and lock screen, menu, Control Center) |
| Screen Saver & Lock | `luxos-lock-settings` | screen saver, when to ask for the password |
| Control Center | `luxos-control-center` | quick toggles ([desktop.md](desktop.md#control-center)) |
| Printers & Scanners | `luxos-printers` | [printing-scanning.md](printing-scanning.md) |
| LuxAI Account | `luxos-account` | [luxai-account.md](luxai-account.md) |
| Drivers | `luxos-drivers` | [drivers.md](drivers.md) |
| Organization Network | `luxos-domain-settings` | join a Windows domain (Active Directory), offline sign-in, domain administrators ([domain.md](domain.md)) |

## Desktop & Dock

Run `luxos-settings`, or use Control Center › Desktop & Dock…. It replaces the Xfce desktop
settings. Sections:

- **Appearance**: Light / Dark / Auto. Auto is light from sunrise to sunset, based on the time
  zone (`luxos-appearance`, see [desktop.md](desktop.md#light-dark-and-auto-appearance)).
- **Boot Screen**: Blue, Purple, Orange, Green or White. It runs `luxos-splash set` through pkexec
  and rebuilds the initramfs, and it takes effect at the next boot.
- **Wallpaper**: thumbnails from `/usr/share/backgrounds/luxos` and `~/Pictures/Wallpapers`, plus
  Choose… for your own picture.
- **Dock**: "Automatically hide and show the Dock" (it appears when you move the pointer to the
  bottom edge), Size, Magnification and its size, Position on screen (Bottom/Left/Right), Dock
  opacity. These are stored in Plank's GSettings, and opacity goes through
  `luxos-appearance dock-opacity`.
- **Menu Bar**: menu bar opacity (`luxos-appearance bar-opacity`).
- Buttons: Displays…, Advanced Desktop Settings… (`/usr/bin/xfdesktop-settings`, desktop icons and
  so on), Menu Bar Items… (`xfce4-panel --preferences`).

## Displays

There are two tools:

- **Displays app**: `luxos-display-settings`. Also opens when you click the brightness icon in
  Control Center.
- **Quick menu**: `Super+P` or the Display key (`luxos-displays menu`).

**Arrangement** (with two or more monitors connected, like in macOS):

- The monitors are drawn as scaled rectangles with their names (EDID model, "Built-in Display").
  Drag one to place it next to another. On release it snaps to the nearest edge: no overlaps, no gaps,
  at least 32 px of shared edge, and top/bottom/centre edges align when they are close.
  Dragging away a monitor that connected two others re-attaches the rest.
- The **white bar** marks the main display. Drag it onto another monitor, or pick one under
  **Main display**, to move the menu bar (xfce4-panel `output-name` = `Primary`) and the Dock
  (Plank `monitor` = empty) there.
- **Mirror displays** shows the same picture on all monitors. Turning it off restores the saved positions.
- Every change uses the same 15-second "Keep these display settings?" confirmation (see below).
  Arranging switches the multi-monitor mode to extend.

Layouts are saved per **set of monitors** in `~/.config/luxos/displays.json` (key `layouts`). The key
is the sorted list of `CONNECTOR|EDID-hash` of all connected monitors. When the same monitors are
connected again (`luxos-displays auto` after hotplug or at login), the layout is restored. If the
connectors differ but the monitors (EDIDs) are the same, the layout still applies. When a monitor's
resolution or rotation changes, positions are re-snapped so no gap or overlap appears. Super+P
**Extend** uses the layout without mirroring; the other Super+P modes ignore it.

In the app, for each monitor:

- **Resolution**: "(Recommended)" marks the sharpest one. A lower one makes everything larger.
- **Refresh rate**.
- **Rotation**.

Every change applies at once, and a dialog asks "Keep these display settings?". If you do not
click **Keep Changes** within **15 seconds**, the previous settings are restored (or click
Revert). Confirmed settings are saved to `~/.config/luxos/displays.json`. They are re-applied at
login (`luxos-session`) and whenever a monitor is connected (`luxos-menubar` runs
`luxos-displays auto`).

- **Text Size**: Smaller / Default / Large / Larger / Largest. Sets Xft DPI in the xfconf channel
  `xsettings`, and apps pick it up immediately.
- **Multiple Displays › Use as**:

  | Choice | Command |
  |---|---|
  | Extend - use both screens | `luxos-displays extend` |
  | Mirror - same picture on both | `luxos-displays mirror` |
  | Only external screen | `luxos-displays external` |
  | Only this computer's screen | `luxos-displays internal` |

  The mode is saved in `~/.config/luxos/displays-mode` (default: extend). The built-in panel
  (eDP/LVDS/DSI) is the primary display.

Other `luxos-displays` commands:

```
luxos-displays auto           # apply saved mode/resolution/layout (after hotplug, at login)
luxos-displays rescue         # move windows that are off-screen to the main monitor
luxos-displays brightness N   # software brightness 10-100 % (monitors without backlight)
```

If the app reports "No displays found", display settings need an X11 session.

## Battery & Power

Run `luxos-power`, or use Control Center › Battery…. The data comes from UPower:

- Battery percentage and state: Charging (full in …), On battery (about … left), Fully charged,
  Plugged in, not charging.
- Power usage in watts, battery health (% of original capacity), charge cycles (UPower, else
  `/sys/class/power_supply/BAT*/cycle_count`; many batteries do not report them – then "Not reported
  by this battery", use battery health instead), energy (Wh).
- Charts: battery level and power usage over the last 24 hours.
- **Power mode** (power-profiles-daemon): Power Saver, Balanced (recommended), Performance.
- **Battery Saver**: power-saver profile, no CPU turbo, slightly lower
  brightness, no Dock magnification, idle devices sleep, background tasks pause (details in
  [Power and performance](power-and-performance.md)). The switch
  "Turn on automatically at 20 %" stores its state in `~/.config/luxos/powersaver-auto`;
  "Lower the screen to 60 Hz" (off by default, the screen goes dark for a moment when switching)
  in `~/.config/luxos/powersaver-60hz`. Battery
  Saver turns off again when the computer charges. From the command line:
  `luxos-powersaver on|off|toggle|status`.
- **Screen and sleep** (xfce4-power-manager): turn off the screen on battery / on power adapter
  after…, sleep on battery / on power adapter after…, and when the lid is closed (Sleep, Lock
  screen, Turn off the screen, Hibernate), and *Stay awake while music or video is playing*.
- **Advanced Power Settings…** opens `xfce4-power-manager-settings`.

On a computer without a battery the app says "This computer runs on mains power - there is no
battery." Demo data: `LUXOS_POWER_DEMO=1 luxos-power`. See also
[power-and-performance.md](power-and-performance.md).

## Bluetooth

Run `luxos-bluetooth`, or use the Bluetooth tile in Control Center. The app talks directly to
BlueZ over D-Bus.

- A switch turns Bluetooth on or off.
- **While the window is open and Bluetooth is on, the computer is visible** to other devices (like
  macOS): "Visible as “name” while this window is open". Closing the window (or turning Bluetooth
  off) makes it invisible again – but only if the window turned visibility on; if something else made
  it visible (e.g. `bluetoothctl discoverable on`), it is left alone. Visibility is set with a
  3-minute timeout that the open window keeps renewing, so a crashed window cannot leave the computer
  visible. Otherwise the hint says "Not visible to other devices".
- **Pairing from a phone**: with the window open, pick the computer's name in the phone's Bluetooth
  settings. LuxOS shows *Pair this device?* with a 6-digit code – press **Pair** if the phone shows
  the same code. A device that pairs without a code asks *Allow “name” to pair with this computer?*.
  For the LuxOS Companion app, Settings › Phone › **Pair a Phone…** does the same for 3 minutes.
- **My devices**: paired devices, each with Connected/Not connected and battery level, and
  Connect/Disconnect and Forget this device.
- **Nearby devices**: while the window is open the app searches ("Searching… Put the device into
  pairing mode."). **Connect** pairs, trusts and connects in one step.
- If the device asks for a code, a dialog appears: confirm the code, type the code shown, or enter
  the PIN ("Usually 0000 or 1234").
- Pairing started from a phone or headphones is handled by the agent in `luxos-hub` when the window
  is closed (blueman-applet is disabled); both ask the same questions.

If connecting fails, the app says "Make sure the device is on, close by and in pairing mode." With
no adapter, it says "No Bluetooth adapter was found on this computer."

## Sound output switching

Newly connected sound devices become the output right away and playing sound moves to them; after
unplugging, sound returns to the previous device:

- **Monitor or TV (HDMI/DisplayPort)**: a monitor only changes the availability of the HDMI port of
  the sound card, and the card usually stays on its analog profile (higher priority), so no new
  output appears. `luxos-hub` follows `pactl subscribe` and on card changes runs
  `/usr/lib/luxos/python/luxos_audio_switch.py check`: when an HDMI/DisplayPort port becomes
  available it switches the card to the best available profile with that port, keeping the
  microphone if possible (e.g. `output:hdmi-stereo+input:analog-stereo`), makes that output the
  default and moves playing streams. On cards where HDMI is always a separate output (SOF/UCM,
  profile `HiFi`) only the default output changes. After unplugging, the previous profile and
  output come back.
- **USB and Bluetooth** headsets, speakers and headphones: the new device becomes the default
  output; `/usr/share/pipewire/pipewire-pulse.conf.d/50-luxos-switch-on-connect.conf` also loads
  `module-switch-on-connect` (output and input).
- Your choice wins: if you pick another output (or card profile) after an automatic switch, nothing
  is switched back when the device is unplugged, and the next automatic switch happens only on the
  next connection. Devices already connected at login are not switched to. The state of the last
  check is in `$XDG_RUNTIME_DIR/luxos-audio-switch.json`.

Volume is in Control Center and the top bar (the sound menu shows "Output: <device>" over the volume
slider and "Input: <microphone>" over the microphone slider). For a detailed mixer, use
`pavucontrol` (the "mixer" of the sound icon).

## Fingerprint

Run `luxos-fingerprint` (the app is named "Fingerprint" and its window "Fingerprint Login"). It is
also reachable from Screen Saver & Lock › Fingerprint Login › Set Up…. It talks to fprintd over
D-Bus (`net.reactivated.Fprint`).

- `fprintd` is installed by `luxos-drivers` only when a reader is detected (`luxos-hwdetect`). With
  no reader, the app shows "No fingerprint reader found" and an **Open Drivers** button.
- **Add Fingerprint…**: choose the finger (right/left index, thumb, middle, ring, little), then
  touch or swipe the sensor several times ("Step N of M").
- Remove a single fingerprint, or **Remove All** (after that you need your password to log in).
- Changing fingerprints may ask for authentication (polkit).

How login works: `/usr/lib/luxos/luxos-fingerprint-pam` inserts a managed block with
`pam_fprintd.so` into the PAM services `lightdm`, `sudo`, `polkit-1` and `xfce4-screensaver`. The
block sits between the markers `# LuxOS fingerprint: begin/end`. A libalpm hook
(`luxos-fingerprint.hook`) re-runs `sync` after fprintd, lightdm, sudo, polkit, xfce4-screensaver
or luxos-desktop are installed, upgraded or removed.

- Login screen: `max-tries=3 timeout=30`. When you start typing the password, the greeter skips
  the fingerprint (`/run/luxos-fingerprint/password-only`).
- sudo, polkit and the lock screen: `timeout=10`.
- The password always works. Without a reader or enrolled fingers, pam_fprintd returns
  "unavailable" at once.
- Check or repair (root): `/usr/lib/luxos/luxos-fingerprint-pam status|sync|apply|remove`.

## Profile Picture

Run `luxos-profile-picture` (also: LuxAI Account → **Change Picture**, or click the picture there;
the user name in the LuxOS menu opens LuxAI Account). The window shows your current picture or the
fallback avatar (first letter of your name on a blue-violet circle).

- **Choose Photo…**: any image GdkPixbuf can open (JPEG, PNG, WebP…); EXIF rotation is applied.
  `luxos-profile-picture FILE` opens a file directly.
- **Take Photo**: a live, mirrored preview from the webcam, the same way as the Camera app
  (`luxos_camera`: v4l2src, MJPEG through jpegdec). The shutter (or Space/Enter) takes the picture.
  `luxos-profile-picture --camera` starts here. No camera, a busy camera or missing access are
  explained in the window.
- **Crop**: the photo sits under a circle. Drag to move it, scroll (or the slider, +/−) to zoom up to
  4×, arrow keys move it. The circle is always fully covered. **Save** (Enter) or **Cancel** (Esc).
- **Remove Picture** goes back to the letter avatar.

Saving writes a 384×384 PNG to `~/.face` (read by the lock screen of xfce4-screensaver and by
Control Center) and calls AccountsService `SetIconFile` on your user over D-Bus. AccountsService
copies it to `/var/lib/AccountsService/icons/<user>`, where the login screen (`luxos-greeter`) and the
user button of the LuxOS menu (Whisker Menu) read it. Changing your own picture needs no password
(polkit `org.freedesktop.accounts.change-own-user-data` for the active local session). If
AccountsService fails, the picture is still saved in `~/.face` and the window says so. The Python
helper is `/usr/lib/luxos/python/luxos_avatar.py`.

## Screen Saver & Lock

Run `luxos-lock-settings`. It writes the xfconf channel `xfce4-screensaver`.

- **Start after inactivity of**: Never, 1, 2, 5, 10 (default), 15 or 30 minutes, or 1 hour.
- **Screen saver**:
  - LuxOS - wallpapers and clock (default);
  - Clock (large clock on black, moves slowly, gentle on OLED);
  - Aurora;
  - Photos (slideshow from `~/Pictures`, LuxOS wallpapers if there are none);
  - Floating Logo;
  - Black screen.

  The Preview button shows the chosen one. The program is `/usr/lib/xfce4-screensaver/luxos --style
  wallpapers|clock|aurora|photos|logo`.
- **Require password after the screen saver starts**: Immediately, After 1 minute (default), After
  5 minutes, After 15 minutes, Never.
- **Lock when the computer goes to sleep** (`/lock/sleep-activation`).
- **Fingerprint Login › Set Up…** appears only when fprintd is installed.
- **Lock Now** (`xflock4`). Shortcuts: `Super+L`, `Ctrl+Super+Q`.

The Safe (`/safe/<user>`) also locks itself when the screen locks. See [safe.md](safe.md).

## Reset App Settings

Run `luxos-app-reset` (Settings › Reset App Settings, Czech "Výchozí nastavení aplikací"). It lists
apps with settings in the home folder – `~/.config/<name>`, `~/.local/share/<name>` and
`~/.cache/<name>`, Flatpak apps (`~/.var/app/<id>`) and `~/.mozilla` / `~/.thunderbird` – with the
app name and icon from its `.desktop` file, the size and the folders; folders without a matching
app are listed under "Other folders with settings".

**Reset…** (only when the app is not running) moves all its folders to
`~/.local/share/luxos/app-settings-backups/<YYYY-MM-DD_HH-MM-SS>-<app>/` (with `manifest.json`);
nothing is deleted. **Backups › Restore** puts them back (settings the app created meanwhile go to a
new backup first). Never offered: the keyring (passwords), GnuPG, the LuxAI account, Trash, fonts,
icons, themes, Flatpak installations, dconf, the Xfce/LuxOS desktop, the shell and LuxOS's own
settings. Apps that keep settings only in dconf (GSettings) are not covered.

```bash
luxos-app-reset list [--json]
luxos-app-reset reset vlc [--yes] [--force]
luxos-app-reset backups
luxos-app-reset restore ~/.local/share/luxos/app-settings-backups/2026-10-26_15-00-00-vlc
```
