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
| `tests/` | `build-host.sh` (build against the wl-test sysroot), `test_luxwm.py` |

The build copies `packages/luxos-desktop/files/lsl/luxos_tokens.lsl` next to the sources, because LSL
looks for modules next to the importing file.

## Behaviour

- **Placement** is the xfwm4 `luxos` mode (`packages/xfwm4/luxos-windows.patch`): the centre of the
  usable area when nothing is there, otherwise the leftmost, then topmost free spot, otherwise a 28 px
  cascade from the topmost window of the same app, wrapping at the edges. A window never lands on the
  same corner as another one. The usable area excludes layer-shell exclusive zones (bar, Dock). A dialog
  goes over the centre of its parent. When the bar appears, windows under it move down. Maximised,
  tiled and fullscreen windows are fitted again.
- **Focus**: click to focus. When the focused window closes, focus goes to its parent, otherwise to
  the most recent window on the workspace. The traffic lights of an inactive window work without
  focusing it. A new window does not take focus from a focused fullscreen window. A dialog of an app
  on another workspace does not take focus either. Activation requests from clients are honoured only
  for the app that already has focus, until xdg-activation tokens exist.
- **Alt+Tab / Super+Tab** cycle the windows of the workspace in most-recent order. The selected
  window comes to the front at once; minimised ones show only while selected. Releasing the modifier
  commits, Alt+Esc cancels. **Alt+`** (the key under Esc in every layout) does the same within the
  focused app.
- **Workspaces**: 4 by default. They slide like Spaces in macOS (the animation runs in C, and pixman
  jumps to the end when frames are slow). Focus moves to the new workspace at once. A focused
  fullscreen window is above the bar (`LAYER_FULLSCREEN`). When it loses focus it goes back into its
  workspace tree, so it leaves with its workspace.
- **Maximise** fills the usable area and keeps the title bar. **Tile left/right** fills half of it.
  **Minimise** hides the window. Minimised windows come back through Alt+Tab (the Dock follows with
  foreign-toplevel). **Show desktop** toggles.
- **Title bars** take their colours from `luxos_tokens`: window, fg/dim, traffic lights, inactive
  light, border, radius 16, Inter Semi-Bold 10. Light or dark follows `~/.config/luxos/appearance`.

## Configuration

`~/.config/luxwm/luxwm.conf` overrides `/usr/share/luxwm/luxwm.conf` entry by entry. Lines are
`name = value`. After a `[keys]` line come shortcuts written like luxos-shortcuts/xfconf
(`<Primary><Super>Left`, `<Alt>grave`, `Print`). Their values are xfwm4 action names, so WP-12 can
convert the user's xfconf shortcuts one to one. `exec COMMAND` starts a program with `sh -c`. An empty
value turns a default shortcut off. Unknown actions are skipped, so the tabwin keys of xfwm4 (`Up`,
`Escape`…) are never grabbed globally.

Settings: `workspaces` (1–16), `slide_ms` (0 = no animation), `wrap_workspaces` (yes/no).

Actions: `close_window_key`, `hide_window_key`, `maximize_window_key`, `fullscreen_key`,
`tile_left_key`, `tile_right_key`, `show_desktop_key`, `cycle_windows_key`,
`cycle_reverse_windows_key`, `cycle_app_windows_key`, `cycle_reverse_app_windows_key`,
`switch_window_key`, `left_workspace_key`, `right_workspace_key`, `workspace_N_key`,
`move_window_left_workspace_key`, `move_window_right_workspace_key`,
`move_window_workspace_N_key`, `quit`.

Signals:
- `SIGHUP` reloads the configuration and the look.
- `SIGUSR1` reloads only the look. luxos-appearance should send it after switching light/dark (not wired yet, WP-12).
- `SIGUSR2` writes the window state to stderr (tests).
- `SIGTERM` and `SIGINT` stop cleanly.

`luxwm -d` (or `LUXWM_TRACE=1`) traces decisions. Further arguments are commands started after the
backend is up.

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
  systemd-run --user --scope -p TasksMax=300 -- timeout 900 python3 -m unittest -v test_luxwm
```

- Sessions run through `scripts/wl-test`: headless pixman 1280×800 and nested in a private Xvfb, with
  `LUXCOMP_VIRTUAL_INPUT=1` so that `wlt input` works.
- Screenshots and measurements go to `out/luxwm-test/results`.
- `lslc` links only against system library directories. `build-host.sh` therefore compiles luxwm in a
  private mount namespace with the freshly built libluxcomp over `/usr/local/lib`.

## Later stages (hooks)

- **XWayland**: lazy start belongs in libluxcomp. X11 windows will arrive as ordinary `VIEW_*` events,
  so the policy stays the same.
- **IPC for the shell** (bar, Dock, Launchpad: workspace list, app name, switching): a socket
  in luxwm is the natural place. `dump()` already shows the state it would publish.
- **foreign-toplevel** (Dock, minimised windows) and **xdg-activation** tokens (then `REQ_ACTIVATE`
  can switch workspaces like xfwm4 `activate_action=switch`): core work in libluxcomp. The policy has
  `request()` ready for them.
- **ext-session-lock** and greeter mode: core work. luxwm will only have to ignore shortcuts while the session is locked.
- Keyboard layout from locale1 (`luxcomp_set_keymap`), multi-monitor slide per output, snapping and
  resize from the keyboard.
