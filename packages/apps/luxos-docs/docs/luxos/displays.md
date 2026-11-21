# Displays

## Tools

There are two tools:

- **Displays app**: `luxos-display-settings`. Also opens when you click the brightness icon in
  Control Center.
- **Quick menu**: `Super+P` or the Display key (`luxos-displays menu`).
- **Window scaling 2x** (Settings › Appearance, HiDPI): window frames switch to `WhiteSur-*-xhdpi`
  automatically (`luxos-appearance wm-theme`, run by `luxos-hub`); a custom xfwm4 theme is kept.
- **Control Center › Screens** (only with two or more monitors connected): Mirror, Extend and, with
  a built-in panel, External Only. No window pops up when a monitor is connected.

## Arrangement

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

## Resolution, rotation and text size

- **Resolution**: "(Recommended)" marks the sharpest one. A lower one makes everything larger.
- **Refresh rate**.
- **Rotation**.

Every change applies at once, and a dialog asks "Keep these display settings?". If you do not
click **Keep Changes** within **15 seconds**, the previous settings are restored (or click
Revert). Confirmed settings are saved to `~/.config/luxos/displays.json`. They are re-applied at
login (`luxos-session`) and whenever a monitor is connected (`luxos-menubar` runs
`luxos-displays auto`).

- **Scale**: 100 % (default), 125 %, 150 %, 175 % or 200 % – the size of everything on the screen,
  like the display scale in Windows; useful on touch screens and small high-resolution displays.
  100–150 % make text bigger (Xft DPI 96/120/144) and enlarge the menu bar, the Dock icons, the
  cursor and the window title bars (WhiteSur `-hdpi` frames, easier to hit with a finger); 175 % and
  200 % switch GTK to 2× (`Gdk/WindowScalingFactor`) with `-xhdpi` frames. Your own menu bar height
  and Dock size are kept relative to the scale. Stored in `~/.config/luxos/display-scale`; command
  `python3 /usr/lib/luxos/python/luxos_displays.py scale-set 150`. Some apps need to be reopened.
- **Text Size**: Smaller / Default / Large / Larger / Largest, relative to the scale. Sets Xft DPI in
  the xfconf channel `xsettings`, and apps pick it up immediately.
- **Multiple Displays › Use as**:

  | Choice | Command |
  |---|---|
  | Extend - use both screens | `luxos-displays extend` |
  | Mirror - same picture on both | `luxos-displays mirror` |
  | Only external screen | `luxos-displays external` |
  | Only this computer's screen | `luxos-displays internal` |

  The mode is saved for the connected **set of monitors** in `~/.config/luxos/displays.json` (key
  `modes`, same set key and EDID matching as layouts), so a projector can stay mirrored while the
  monitor at home stays extended. A set that has no saved mode uses the last chosen mode
  (`~/.config/luxos/displays-mode`), otherwise extend. The built-in panel (eDP/LVDS/DSI) is the
  primary display unless the saved arrangement says otherwise; the menu bar and Dock always follow
  the primary display.

## How mirroring and layouts work

**Mirroring** puts all monitors at 0,0 with the same resolution, so nothing is cut off:

1. the primary display's saved resolution, or its native one, when every monitor supports it;
2. otherwise the best resolution all monitors share: the same aspect ratio as the primary display
   first (16:9 laptop + 4:3 projector → 1280×720 rather than 1280×1024), unless that is less than
   half the size of the largest shared one, then the largest;
3. if there is no shared resolution at all (e.g. a 1366×768 laptop and a TV with only 4K/1080p),
   the primary display stays native and the others run at their own recommended mode with
   `xrandr --scale-from` the primary's size. The whole picture is scaled, nothing is panned or
   cut off; with a different aspect ratio it is slightly stretched.

Interlaced modes are never used; the refresh rate is the monitor's recommended one, otherwise the
one closest to 60 Hz. Switching back to Extend resets the scaling (`--scale 1x1`). The Arrangement
mirror switch uses the same choice. Connecting a monitor never opens a dialog: the Xfce display
popup is off (xfconf `displays /Notify` = 0, reset at login if an old profile changed it).

Other `luxos-displays` commands:

```
luxos-displays auto           # apply saved mode/resolution/layout (after hotplug, at login)
luxos-displays mode           # print the mode auto would use for the connected monitors
luxos-displays rescue         # move windows that are off-screen to the main monitor
luxos-displays brightness N   # software brightness 10-100 % (monitors without backlight)
```

If the app reports "No displays found", display settings need an X11 session.

