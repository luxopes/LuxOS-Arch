# Touch screens and tablets

Since LuxOS 1.0.5 the whole system works on touch screens – tablets, 2-in-1 laptops and touch
monitors – also without a physical keyboard. Nothing has to be set up: when LuxOS finds a touch
screen at sign-in (`luxos-touch session`), it turns on everything below. Computers without a touch
screen are not changed.

## On-screen keyboard

- **In apps:** the on-screen keyboard (Onboard) appears by itself when you tap a text field and hides
  again when you leave it. It is docked at the bottom edge and windows shrink so that the field you
  type into stays visible.
- **With a physical keyboard connected** (a 2-in-1 laptop in laptop mode, a touch monitor with a
  keyboard) it does not pop up by itself; on a 2-in-1 that reports tablet mode it can appear again
  in tablet mode.
- **Any time:** the small floating keyboard button, **Keyboard** in Control Center, or a swipe up with
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
| Swipe left / right with 3 fingers | Next / previous workspace |
| Pinch with 3 fingers | Close the window |
| Swipe up with 4 fingers | Show or hide the on-screen keyboard |
| Tap with 2 fingers | Right click (context menu) |
| Drag with 1 finger | Scroll in apps and web pages; move windows by their title bar |
| Pinch with 2 fingers | Zoom in Firefox and Chromium |

Gestures come from Touchégg. LuxOS copies its gestures to `~/.config/touchegg/touchegg.conf` on the
first sign-in; when you edit that file, LuxOS keeps your version.

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
