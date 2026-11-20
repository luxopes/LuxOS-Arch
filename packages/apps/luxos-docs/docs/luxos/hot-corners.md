# Hot corners

Moving the pointer into a corner of the screen and keeping it there for a moment (about 0.3 s) runs an
action, like hot corners on a Mac.

## Default corners

| Corner | Action |
|---|---|
| Top left | Launchpad (all apps) |
| Bottom right | Show the desktop; the second time the windows come back |
| Top right, bottom left | nothing |

A corner runs again only after the pointer leaves it. Passing through the top left corner on the way
to the LuxOS menu does not open Launchpad.

## Changing the corners

Open **Desktop & Dock › Hot Corners** (Control Center › Desktop & Dock…). Each corner can be set to
Launchpad, Show Desktop, Control Center, Lock Screen, Start Screen Saver or nothing (—). The change
applies within two seconds, without signing out.

The choice is stored in `~/.config/luxos/hotcorners`, one line per corner: `tl` (top left), `tr`
(top right), `bl` (bottom left) and `br` (bottom right), with the values `launchpad`, `desktop`,
`control-center`, `lock`, `screensaver` or `none`, for example `tl=none`. A missing line keeps the default.

## Notes

- Hot corners run in luxos-hub; with several monitors the outer corners of the whole desktop count.
- On a touch device without a physical keyboard (see [Touch screens and tablets](touch.md)) hot corners
  are off, because a tap into a corner would trigger them.
