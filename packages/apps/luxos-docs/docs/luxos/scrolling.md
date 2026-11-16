# Scrolling, Mouse and Touchpad

LuxOS scrolls like macOS: the touchpad moves the content pixel by pixel and, after a quick swipe,
the content keeps gliding and slows down (inertia, "kinetic scrolling"). The mouse wheel glides to the
new position instead of jumping. Both are on by default and can be turned off in
**Settings › Scrolling** (`luxos-scrolling`).

## Where it works

| App | Touchpad inertia | Smooth mouse wheel |
|---|---|---|
| GTK 3 apps (Files, Text Editor, Settings, Store, LuxOS apps in LSL, Xfce apps) | yes (GtkScrolledWindow) | yes (module `luxos-scroll`) |
| Terminal (`luxos-terminal`) | yes – history scrolls by pixels | yes |
| Firefox | yes (XInput2 pan gesture) | yes (Firefox's own smooth scrolling) |
| Mail, help viewer (WebKitGTK) | yes | yes (WebKit's own) |
| Programs with their own scrolling (games, Blender, Steam, maps, `htop`/`mc`/`less` in Terminal) | unchanged | unchanged |

Touching the touchpad to move the pointer, a tap or a click stops the glide. On X11 the touchpad
driver does not report fingers that only rest on the touchpad, so resting two fingers without moving
does not stop it (macOS does); moving them slightly does.

## Settings › Scrolling

- **Smooth scrolling with the mouse wheel** – each notch glides for 200 ms (ease-out); more notches
  during the glide add up. The distance is the same as without it. It is not used while animations are
  off (Battery Saver, `Gtk/EnableAnimations` = false) or with `Ctrl`/`Alt`/`Super` held (zoom in apps).
- **Inertia on the touchpad** – off: the content stops when the fingers lift.
- **Mouse and touchpad settings** opens `xfce4-mouse-settings` (pointer speed, scrolling direction,
  edge or two-finger scrolling, tap to click).

Changes apply right away, also in windows that are already open. From the command line:

```
luxos-scrolling status               # smooth_wheel=true / kinetic=true
luxos-scrolling kinetic off          # or on
luxos-scrolling smooth-wheel off     # or on
```

The values are stored in `~/.config/luxos/scrolling.conf`:

```
[scrolling]
smooth_wheel=true
kinetic=true
```

A missing file or key means "on".

## Touchpad driver

`/etc/X11/xorg.conf.d/30-luxos-touchpad.conf` (libinput): tap to click, two-finger tap for the right
button, tap-and-drag, scrolling by dragging along the right (and bottom) edge, click-finger method,
touchpad off while typing, adaptive acceleration. Edge scrolling and two-finger scrolling both scroll
by pixels with inertia; switch between them in Mouse and Touchpad settings.

## How it works

- After the fingers lift, `xf86-input-libinput` sends a scroll event with zero movement. GDK turns it
  into a "scroll stop" event; GtkScrolledWindow, Firefox and WebKitGTK compute the speed of the last
  ~150 ms and glide.
- The GTK 3 module `luxos-scroll` (`/usr/lib/gtk-3.0/modules/libluxos-scroll.so`) is loaded into every
  GTK 3 app through the XSETTINGS value `Gtk/Modules` (default in the xsettings channel; `luxos-session`
  adds it at login if another value replaced it). It animates the wheel in GtkScrolledWindow only
  when the event really reaches it (an app's own scroll handler keeps priority), stops the glide on
  pointer movement from the touchpad or a click, and when inertia is off it delivers the stop event
  250 ms later, so every app computes zero speed. `LUXOS_SCROLL=0` turns the module off for one program.
- Firefox uses XInput2 on X11 only with `MOZ_USE_XINPUT2=1`
  (`/etc/X11/xinit/xinitrc.d/50-luxos-firefox-xinput2.sh`, after the next login); without it Firefox
  gets only wheel notches from the touchpad. LuxOS Firefox defaults (`luxos.js`): `general.smoothScroll`,
  `general.smoothScroll.msdPhysics.enabled`, `apz.gtk.pangesture.enabled`, `apz.gtk.kinetic_scroll.enabled`.
- Terminal scrolls its history by pixels through GtkScrolledWindow (VTE `scroll-unit-is-pixels`,
  fallback scrolling off). Apps that use the mouse (`htop`, `mc`) and `less`/`man` on the alternate
  screen still get the wheel from VTE as before.

## Troubleshooting

- No inertia anywhere: check `luxos-scrolling status`, and that the touchpad uses libinput
  (`xinput list-props "<touchpad>" | grep "libinput Scroll Method"`).
- No inertia in Firefox: `echo $MOZ_USE_XINPUT2` in a terminal should print `1` (log out and in once
  after the update); a Firefox that was running before keeps the old behavior until it is restarted.
- An app scrolls strangely: start it with `LUXOS_SCROLL=0 app` and report it with Feedback.
