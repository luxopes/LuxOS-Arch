# luxwm

Window manager of the LuxOS 1.1.0 Wayland desktop (architecture R2 in
`docs/proposals/wayland-desktop-1.1.0.md`). libluxcomp (`packages/luxcomp`, C on wlroots 0.20) owns
wlroots and draws. luxwm is the policy on top of it, written in LSL. It only reacts to sparse events
(new window, click, shortcut, end of a slide); nothing runs per frame in LSL.

| File | Purpose |
|---|---|
| `luxwm.lsl` | the policy |
| `luxos_luxcomp.lsl` | binding to `libluxcomp.so.0` (internal ABI, one static event callback through `glib.record_new`) |
| `luxwm.conf` | defaults, installed as `/usr/share/luxwm/luxwm.conf` |
| `privileged.conf` | programs allowed to use privileged protocols and privileged IPC commands, installed as `/usr/share/luxwm/privileged.conf` |
| `luxwm-msg.lsl` | `luxwm-msg`, IPC commands from scripts (`luxos-appearance`, tests) |
| `tests/` | `build-host.sh` (build against the wl-test sysroot), `test_luxwm.py`, `test_luxwm_protocols.py`, `wl-probe.c` |

The build copies `packages/luxos-desktop/files/lsl/luxos_tokens.lsl` next to the sources, because LSL
looks for modules next to the importing file.

## Behaviour

- **Placement** is the xfwm4 `luxos` mode (`packages/xfwm4/luxos-windows.patch`): the centre of the
  usable area when nothing is there, otherwise the leftmost, then topmost free spot, otherwise a 28 px
  cascade from the topmost window of the same app, wrapping at the edges. A window never lands on the
  same corner as another one. The usable area excludes layer-shell exclusive zones (bar, Dock). A Dock
  that only dodges windows reports its height over IPC (`dock_zone`), and new windows go above it. A
  window taller or wider than that area shrinks to fit (not below its minimum size), like in the X11
  session, so its bottom buttons stay visible. A dialog goes over the centre of its parent. When the bar appears, windows under it move down. Maximised,
  tiled and fullscreen windows are fitted again.
- **Focus**: click to focus. When the focused window closes, focus goes to its parent, otherwise to
  the most recent window on the workspace. The traffic lights of an inactive window work without
  focusing it. A new window does not take focus from a focused fullscreen window. A dialog of an app
  on another workspace does not take focus either.
- **Activation** (xdg-activation, Dock): a window of another app is focused only with a token from
  the focused app, from the shell (layer-shell surface, a program started by luxwm) or from the
  Dock (foreign-toplevel). luxwm then switches to the window's workspace and restores it when it
  is minimised. Without a token, only windows of the focused app may activate themselves.
- **Alt+Tab / Super+Tab** cycle the windows of the workspace in most-recent order. The selected
  window comes to the front at once; minimised ones show only while selected. Releasing the modifier
  commits, Alt+Esc cancels. **Alt+`** (the key under Esc in every layout) does the same within the
  focused app.
- **Workspaces**: 4 by default. They slide like Spaces in macOS (the animation runs in C, and pixman
  jumps to the end when frames are slow). Focus moves to the new workspace at once. A focused
  fullscreen window is above the bar (`LAYER_FULLSCREEN`). When it loses focus it goes back into its
  workspace tree, so it leaves with its workspace.
- **Maximise** fills the usable area and keeps the title bar. **Tile left/right** fills half of it.
  **Minimise** hides the window. Minimised windows come back through Alt+Tab or the Dock
  (foreign-toplevel restore = activation). The Dock can also maximise, make fullscreen and close.
  **Show desktop** toggles.
- **Session lock**: while locked, the core hides everything under an opaque cover in the LuxOS
  background colour and sends input only to the lock surfaces. luxwm gets no shortcuts and cancels Alt+Tab.
  If the locker dies, the screen stays covered until a new locker unlocks it.
- **X11 apps** run through XWayland. It starts with the first X11 client and stops 10 s after the
  last. X11 windows get the same placement, focus and title bars. `xwayland = no` turns it off.
- **Sandboxed apps** (clients of a wp-security-context socket, `luxos-sandbox run --gui`) always get
  the server-side title bar with a dim "Sandbox · app" label at the right end. The app comes from the
  security context (set by the launcher), so the app can neither change nor drop it (a request for
  client-side decorations is ignored). Their activation requests pass only while the same sandbox has
  the focus: "same app" for activation means the same app_id and the same sandbox instance.
  An X11 app in the sandbox runs in the sandbox's own rootful Xwayland. luxwm shows that window with the
  sandbox app_id and title, and `luxos-sandbox` reports the size and title of the app's main X window
  (`sandbox_window`): the Xwayland window takes that size, and the app's window follows when the user
  resizes it. A rootless Xwayland would need luxwm's X window manager inside the sandbox's Xwayland,
  which wlroots cannot attach to an X server it did not start.
- **Animations** like the picom setup of LuxOS 1.0.x: a new window grows from 90 % and fades in (180 ms),
  a closing one shrinks and fades out (140 ms), minimise flies into the Dock (320 ms), restore from the
  Dock grows back out of it (300 ms). Alt+Tab and Show desktop stay instant. Input is never blocked
  (`docs/developers/luxcomp-api.md`, section Animace oken). `reduce_motion = yes` or Battery Saver turn them off.
- **Launch feedback**: after a launcher asks for an xdg-activation token, or an `exec` shortcut, the arrow
  is the animated busy pointer until the app's window maps (at most 15 s), like startup-notification on X11.
- **Login transition** (`--intro`, used by `luxos-wayland-session`), like `luxos-session-cover --login` on X11:
  the greeter's last frame (dimmed wallpaper, `/run/luxos-greeter/login-frame`) with the Plymouth-like progress
  bar where the password field was, until the wallpaper, the bar and the Dock drew their first frame; then it
  fades into the desktop over 280 ms (no fade under reduce motion or Battery Saver). In `--greeter` mode luxwm
  hands the screen over through the empty graphics VT 12 after a login, so no text console shows in between.
- **Title bars** take their colours from `luxos_tokens`: window, fg/dim, traffic lights, inactive
  light, border, radius 16, Inter Semi-Bold 10. Light or dark follows `~/.config/luxos/appearance`.

## Login screen mode

`luxwm --greeter COMMAND` runs the greetd login screen (`packages/luxos-greetd`, `docs/developers/wayland-session.md`):
- The client that COMMAND starts is fullscreen and focused.
- There are no shortcuts, no XWayland, no privileged protocols and no user configuration.
- luxwm exits when COMMAND exits, with status 1 if it failed.
- `LUXWM_PRIVILEGED` is still honoured, only so that the wl-test harness can use its tools.

In every mode, Ctrl+Alt+F1..F12 switch the console (libluxcomp, libseat session).

## Configuration

`~/.config/luxwm/luxwm.conf` overrides `/usr/share/luxwm/luxwm.conf` entry by entry. Lines are
`name = value`. After a `[keys]` line come shortcuts written like luxos-shortcuts/xfconf
(`<Primary><Super>Left`, `<Alt>grave`, `Print`). Their values are xfwm4 action names, so WP-12 can
convert the user's xfconf shortcuts one to one. `exec COMMAND` starts a program with `sh -c`. An empty
value turns a default shortcut off. Unknown actions are skipped, so the tabwin keys of xfwm4 (`Up`,
`Escape`…) are never grabbed globally.

Settings: `workspaces` (1–16, also changed by `reload`: windows of removed workspaces move to the last one),
`slide_ms` (0 = no animation), `reduce_motion` (yes = no workspace slide and no window animations; also off while Battery Saver is on), `wrap_workspaces` (yes/no),
`double_click_action` (title bar double-click: maximize, hide, none),
`xwayland` (yes/no), `blur` (yes/no: material of shell surfaces blurred or a solid colour, see
`docs/developers/luxcomp-api.md`), `displays_command` (run with `sh -c` once, 300 ms after outputs are plugged in or
out and at startup; default `luxos-displays auto`, which applies the saved display settings for the
connected set of monitors; empty = nothing).

Night light (Control Center moon next to brightness, Settings > Displays): `night_light` (`off`, `on`,
`schedule` from `night_light_from` to `night_light_to`, `H:MM`, also across midnight), `night_light_temperature`
(kelvin, 1000–6500, default 4000). A quick toggle in schedule mode lasts until the next schedule boundary; IPC
`get_night_light`/`set_night_light`, `luxwm-msg night-light [on|off]`. Screens without a backlight get software
brightness from `~/.config/luxos/brightness` (IPC `set_brightness`). libluxcomp uses the output's gamma table,
or a warm and a black overlay where there is none (VMs).

Mouse and touchpad (Settings > Mouse & Touchpad writes them): `mouse_OPTION` and `touchpad_OPTION`, applied
by libluxcomp to every libinput device of that kind, also to devices plugged in later (a touchpad is a
device that can tap). Options: `speed` (-100 slow .. 100 fast, libinput accel speed -1..1), `accel`
(`adaptive`/`flat`), `natural_scroll`, `left_handed`, `middle_emulation`, `tap`, `tap_drag`,
`disable_while_typing` (yes/no), `click_method` (`areas`/`clickfinger`/`none`), `scroll_method`
(`two_finger`/`edge`/`button`/`none`). A missing or empty entry is the libinput default of the device,
also after `reload`; an option the device lacks is ignored. IPC `get_input` returns the configured values
and what libinput really has on each device.

Displays: windows whose centre is on no enabled output (unplugged or turned off) move to the main
display. The main display is chosen in the display settings (`set_primary` over IPC); without a choice
it is the enabled output furthest left and up.

`/usr/share/luxwm/privileged.conf` lists absolute paths of programs allowed to use the screen
capture, clipboard (data-control), foreign-toplevel management, virtual input, output management
and session lock protocols. It is reread on `SIGHUP`. `LUXWM_PRIVILEGED` overrides the path for
tests. There is no per-user file. Sandboxed clients (wp-security-context) never get these
protocols. For the trade-offs, see `docs/developers/luxcomp-api.md`.

Actions: `close_window_key`, `hide_window_key`, `maximize_window_key`, `fullscreen_key`,
`tile_left_key`, `tile_right_key`, `show_desktop_key`, `cycle_windows_key`,
`cycle_reverse_windows_key`, `cycle_app_windows_key`, `cycle_reverse_app_windows_key`,
`switch_window_key`, `left_workspace_key`, `right_workspace_key`, `workspace_N_key`,
`move_window_left_workspace_key`, `move_window_right_workspace_key`,
`move_window_workspace_N_key`, `quit`.

Signals:
- `SIGHUP` reloads the configuration and the look.
- `SIGUSR1` reloads only the look (light/dark from `~/.config/luxos/appearance`).
- `SIGUSR2` writes the window state to stderr (tests).
- `SIGTERM` and `SIGINT` stop cleanly.

`luxwm -d` (or `LUXWM_TRACE=1`) traces decisions. Further arguments are commands started after the
backend is up.

## IPC and keyboard layouts

luxwm listens on `$XDG_RUNTIME_DIR/luxwm-$WAYLAND_DISPLAY.sock` (exported as `LUXWM_SOCK`): line-based
JSON, same-uid peers only (`SO_PEERCRED` in libluxcomp), window information and control only for
programs on `privileged.conf`. Events: window, workspace, keyboard, output, theme. Commands: switch and
next layout, switch workspace, reload, set theme, suspend shortcuts, list and focus windows, mouse and touchpad state (`get_input`). The
protocol is in `docs/developers/luxwm-ipc.md`; the shell client is
`packages/luxos-desktop/files/lsl/luxos_luxwm.lsl`.

The keymap comes from `org.freedesktop.locale1` (`X11Layout`, `X11Variant`, `X11Options`), and
`xkb_layout`, `xkb_variant`, `xkb_options` in `luxwm.conf` override it. These are written by
Settings > Keyboard (`luxos-keyboard-settings`). Layouts are switched by the XKB `grp:` option (LuxOS
default: both Shift keys) or over IPC (the bar badge). The layout is the same for all windows, as in the X11 session.
Key repeat comes from `repeat_rate` (characters per second, 0-100, 0 turns repeat off, default 25) and
`repeat_delay` (ms before the first repeat, 100-3000, default 600) in `luxwm.conf`, applied to every
keyboard at start and on reload and reported in the `keyboard` event (`repeat`); Settings > Keyboard
writes them and sends `reload`.
Shortcuts in `[keys]` are compared in canonical form (`<Primary><Shift><Alt><Super>key`). The Xfce
shortcuts of a user are imported once (`luxos-keyboard-settings --import-shortcuts`).

## Robustness

An error in the LSL policy is logged as `luxwm: error in <event>` and the compositor keeps running.
glib's callback bridge catches what is left. A window whose placement failed still gets focus.
Without any configuration a built-in minimum applies: Alt+Tab, Alt+`, Alt+F4, workspace keys and a
terminal.

## Tests

```sh
scripts/wl-test/fetch-sysroot.sh
packages/luxwm/tests/build-host.sh        # libluxcomp, luxcomp-demo, luxwm -> out/luxwm-test/build
cd packages/luxwm/tests
env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \
  systemd-run --user --scope -p TasksMax=300 -- timeout 900 python3 -m unittest -v test_luxwm test_luxwm_protocols
```

`packages/luxos-desktop/tests/test_luxos_displays_wl.py` covers display settings: modes, fractional
scale, rotation, arrangement, mirroring with hidden layers, the quick switcher, hotplug through
`test_output`, the revert timer and the allowlist.

`test_luxwm_ipc.py` covers IPC, layouts, the bar badge, shortcut import and settings, and the theme.

`test_luxwm_protocols.py` covers the following:
- Dock restore of a minimised window from another workspace.
- xdg-activation: a token without user input is refused, a token from a program started by luxwm is accepted.
- Session lock:
  - a new window stays hidden while locked and gets no keyboard;
  - SIGKILL of the locker keeps the cover (pixel check);
  - shortcuts are off while locked;
  - a new locker unlocks.
- Privileged allowlist: what `wl-probe` sees and can bind when it is allowlisted, not allowlisted,
  or behind a security-context socket.
- XWayland: xeyes from the sysroot is placed, decorated and focusable by click, Xwayland exits after
  the last client, and PSS is measured.

`packages/luxos-desktop/tests/test_luxos_wl.py` runs the shell protocol suite against luxwm and labwc.

- Sessions run through `scripts/wl-test`: headless pixman 1280×800 and nested in a private Xvfb, with
  `LUXCOMP_VIRTUAL_INPUT=1` so that `wlt input` works.
- Screenshots and measurements go to `out/luxwm-test/results`.
- `lslc` links only against system library directories. `build-host.sh` therefore compiles luxwm in a
  private mount namespace with the freshly built libluxcomp over `/usr/local/lib`.

## Later stages (hooks)

- Multi-monitor slide per output, snapping and resize from the keyboard, xdg_popup keyboard grab
  (GTK menus of layer-shell clients cannot be driven from the keyboard yet), `X11Model`.
