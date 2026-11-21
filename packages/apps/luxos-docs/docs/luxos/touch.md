# Touch screens and tablets

Since LuxOS 1.0.5 the whole system works on touch screens – tablets, 2-in-1 laptops and touch
monitors – also without a physical keyboard. Nothing has to be set up: when LuxOS finds a touch
screen at sign-in (`luxos-touch session`), it turns on everything below. Computers without a touch
screen are not changed.

## On-screen keyboard

- **In apps:** the on-screen keyboard (Onboard) appears by itself when you tap a text field and hides
  again when you leave it. It is docked at the bottom edge and windows shrink so that the field you
  type into stays visible.
- **With a physical keyboard** (a 2-in-1 laptop, a detachable tablet with its keyboard, a touch monitor
  with a keyboard) it appears as well – also in laptop mode – and hides as soon as you type on the
  physical keyboard. To show it only without a physical keyboard:
  `gsettings set org.onboard.auto-show keyboard-device-detection-enabled true`.
- **Size:** docked at about 40 % of the screen height in landscape and 30 % in portrait, so the keys
  are big enough for fingers. A height you set yourself in the keyboard's settings is kept.
- **Any time:** the small floating keyboard button (at the right edge of the screen; drag it anywhere), **Keyboard** in Control Center, or a swipe up with
  four fingers shows or hides it.
- **Sign-in screen:** a **Keyboard** button appears next to Sleep, Restart and Shut Down. On a device
  without a physical keyboard the keyboard is shown right away.
- **Lock screen:** the keyboard button of the lock screen is turned on; without a physical keyboard
  the keyboard is shown right away.
- **Installer and first start:** the live system of the ISO works the same way, so LuxOS can be
  installed on a tablet by touch only.

The keys follow the system keyboard layout (for example Czech in Keyboard Layouts). The keyboard's own
settings (layout, theme, size) open from its menu key.

## Gestures

| Gesture | Action |
|---|---|
| Swipe up with 3 fingers | Launchpad (all apps) |
| Swipe down with 3 fingers | Show the desktop |
| Swipe left / right with 3 or 4 fingers | Next / previous workspace (4 fingers also work with an app open, which may scroll with 3) |
| Pinch with 3 fingers | Close the window |
| Swipe up with 4 fingers | Show or hide the on-screen keyboard |
| Tap with 2 fingers | Right click (context menu) |
| Drag with 1 finger | Scroll in apps and web pages; move windows by their title bar |
| Pinch with 2 fingers | Zoom in Firefox and Chromium |

Gestures come from Touchégg (the LuxOS build: with the original, multi-finger swipes on touch screens
were often taken for pinches, so switching workspaces and Launchpad did nothing, and a three-finger
pinch did not close the window). LuxOS copies its gestures to `~/.config/touchegg/touchegg.conf` on the
first sign-in; when you edit that file, LuxOS keeps your version.

## Touch is not a mouse

- The pointer hides as soon as you touch the screen and comes back when you move a mouse or touchpad
  (`unclutter --hide-on-touch`).
- **Firefox** gets real touch events on a touch device (`dom.w3c_touch_events.enabled` = 1, set by
  LuxOS only when a touch screen is present): dragging a finger scrolls pages and YouTube, two fingers
  zoom. Its window has the normal LuxOS title bar there (`browser.tabs.inTitlebar` = 0): dragging the
  window by the tab bar with a finger used to leave Firefox thinking the finger was still down – pages
  stopped scrolling and the close button stopped working.
- Window buttons are small at 100 %: in **Displays › Scale** choose 125 % or 150 % – text, title bars,
  window buttons, the menu bar and the Dock get bigger. A three-finger pinch also closes a window.
- If touch ever stops reacting while the on-screen keyboard was in use (the keyboard briefly detaches
  the touch screen from the pointer), LuxOS reattaches it within a few seconds (`luxos-touch guard`).

## Screen rotation

With a rotation sensor (most tablets and 2-in-1 laptops) the built-in screen turns with the device and
touch follows the rotation. **Rotation Lock** in Control Center keeps the current orientation. Touch is
always mapped to the built-in screen, also when an external monitor is connected.

## Control Center

On a touch device Control Center has two extra tiles: **Keyboard** (show or hide the on-screen
keyboard) and **Rotation Lock** (only with a rotation sensor).

## Commands

| Command | What it does |
|---|---|
| `luxos-touch detect` | shows `touchscreen=0/1 keyboard=0/1 accel=0/1` |
| `luxos-touch osk show\|hide\|toggle` | on-screen keyboard |
| `luxos-touch rotation-lock on\|off\|toggle\|status` | rotation lock |
| `luxos-touch rotate normal\|left\|right\|inverted` | turn the built-in screen |
| `luxos-touch map` | map touch to the built-in screen again |

## Troubleshooting

- **Touch works but nothing else:** sign out and in again (the touch features start at sign-in) and
  check `luxos-touch detect`. A touch screen that is not reported as `touchscreen=1` is not seen by
  the system as a touch screen (driver problem – send `luxos-touch detect` and the output of
  `libinput list-devices` in a Feedback report).
- **Touch hits the wrong place after connecting a monitor:** run `luxos-touch map`.
- **The keyboard does not appear in one app:** some apps do not report text fields to the system;
  use the floating keyboard button or a four-finger swipe up.
- **Gestures do nothing:** `systemctl status touchegg` must be running; it starts automatically when a
  touch screen is present.
