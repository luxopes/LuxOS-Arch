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
| `privileged.conf` | programs allowed to use privileged protocols, installed as `/usr/share/luxwm/privileged.conf` |
| `tests/` | `build-host.sh` (build against the wl-test sysroot), `test_luxwm.py`, `test_luxwm_protocols.py`, `wl-probe.c` |

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
- **Title bars** take their colours from `luxos_tokens`: window, fg/dim, traffic lights, inactive
  light, border, radius 16, Inter Semi-Bold 10. Light or dark follows `~/.config/luxos/appearance`.

## Configuration

`~/.config/luxwm/luxwm.conf` overrides `/usr/share/luxwm/luxwm.conf` entry by entry. Lines are
`name = value`. After a `[keys]` line come shortcuts written like luxos-shortcuts/xfconf
(`<Primary><Super>Left`, `<Alt>grave`, `Print`). Their values are xfwm4 action names, so WP-12 can
convert the user's xfconf shortcuts one to one. `exec COMMAND` starts a program with `sh -c`. An empty
value turns a default shortcut off. Unknown actions are skipped, so the tabwin keys of xfwm4 (`Up`,
`Escape`…) are never grabbed globally.

Settings: `workspaces` (1–16), `slide_ms` (0 = no animation), `wrap_workspaces` (yes/no),
`xwayland` (yes/no).

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
  systemd-run --user --scope -p TasksMax=300 -- timeout 900 python3 -m unittest -v test_luxwm test_luxwm_protocols
```

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

- **IPC for the shell** (bar, Dock, Launchpad: workspace list, app name, switching): a socket
  in luxwm is the natural place. `dump()` already shows the state it would publish.
- Greeter mode (`luxwm --greeter`, WP-9).
- Keyboard layout from locale1 (`luxcomp_set_keymap`), multi-monitor slide per output, snapping and
  resize from the keyboard.
