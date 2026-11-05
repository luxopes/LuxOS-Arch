# Terminal (luxos-terminal)

**Terminal** (Czech: *Terminál*, command `luxos-terminal`, package `luxos-terminal`) is the default
terminal of LuxOS since 1.0. It replaces xfce4-terminal: a small C program on GTK 3 and VTE (the same
terminal engine as before), so it starts as fast and uses less memory, and it adds tabs that look like
macOS Terminal, light and dark profiles that follow the system appearance, and images in the
terminal (SIXEL). Open it with **Super+T**, **Ctrl+Alt+T**, from the Dock, Launchpad or Search, or
with *Open Terminal Here* in Files.

## Using it

| Shortcut | Action |
|---|---|
| Ctrl+Shift+T | New tab (in the same folder as the current tab) |
| Ctrl+Shift+N | New window (in the same folder) |
| Ctrl+Shift+W | Close tab (asks first if a program is still running) |
| Ctrl+Shift+Q | Close window |
| Ctrl+Shift+C / Ctrl+Shift+V | Copy / paste (the middle mouse button pastes the selection) |
| Ctrl+Shift+A | Select all |
| Ctrl+Shift+F | Find (Enter = older match, Shift+Enter = newer, Esc closes) |
| Ctrl+Shift+G | Find next |
| Ctrl+Plus / Ctrl+Minus / Ctrl+0 | Bigger / smaller / normal font (per window) |
| Ctrl+PageUp / Ctrl+PageDown | Previous / next tab |
| Ctrl+Shift+PageUp / PageDown | Move the tab left / right |
| Alt+1 … Alt+9 | Go to tab 1 … 8, Alt+9 = last tab |
| F11 | Full screen |

- **Tabs** appear only when a window has more than one. The **+** button in the title bar opens a
  tab, the magnifier opens Find. Tabs can be dragged to reorder; the middle mouse button closes one.
- **Links**: Ctrl+click opens web addresses, `file://` links and e‑mail addresses (also OSC 8
  hyperlinks printed by `ls --hyperlink`, `gcc`, …). Right click on a link: *Open Link*, *Copy Link
  Address*.
- **Right click** menu: Copy, Paste, Select All, New Tab, New Window, Find…, Close Tab. Programs
  that use the mouse (mc, htop) get Shift+right click.
- **Tab title** = current folder (set by the LuxOS `bashrc`/`zshrc` only in this terminal), or the
  title a program sets.
- Closing a tab or window with a running program (not just the shell) asks first.
- The **window size** (columns × rows) of the last closed window is remembered for new windows.
- **Colours**: dark profile by default – black background, very slightly transparent (95 %),
  purple cursor – in light and dark system appearance alike. `theme=auto` in the settings file makes
  it follow the system appearance (immediately, also in open windows), `theme=light` is white.
- One process serves all windows (like xfce4-terminal): another `luxos-terminal` only passes the
  request to the running process, so a new window opens in about 50 ms.

## Images (SIXEL)

The terminal shows **SIXEL** images, for example from `img2sixel` (libsixel), `chafa -f sixel`,
`timg -p sixel` or `lsix`. On start, `fastfetch` shows the
real LuxOS logo as an image instead of the Unicode block logo.

How it works: VTE removes SIXEL from its stable releases (`vte3` in Arch has none) and even the
development version only reads the images without drawing them. LuxOS ships its own `vte3` in
`[luxos]` (`packages/vte3`): the Arch package plus the upstream SIXEL code restored
(`restore-sixel.patch`, the reverted upstream commit) and image drawing for GTK 3
(`sixel-draw-gtk3.patch`). SIXEL stays **off** in VTE by default; only `luxos-terminal` turns it on,
other apps using VTE behave as before.

An image belongs to the cells under it, like in xterm: text written over it, erased lines (`clear`,
`top` repainting the screen) and full-screen programs on the alternate screen (`vim`, `less`,
`htop`) hide it; it scrolls with the text and stays in the scrollback.

Check: `luxos-terminal --version` prints `SIXEL` when the installed VTE supports it. In the shell,
`LUXOS_TERMINAL_SIXEL=1` is set when images are on.

## fastfetch logo

For each font size the terminal renders the colour LuxOS logo (`/usr/share/luxos/logo/luxos-logo.svg`)
to SIXEL once, sized to the logo area of the fastfetch config (31 × 12 cells), and caches it in
`~/.cache/luxos/terminal/logo-<cell width>x<cell height>-<dark|light>.six`. The shell gets the path in
`LUXOS_TERMINAL_LOGO`, and `bashrc`/`zshrc` run `fastfetch --logo-type raw --logo "$LUXOS_TERMINAL_LOGO"`.
Everywhere else (xfce4-terminal, SSH, tmux, the text console) fastfetch keeps the Unicode logo. The
cache can be deleted at any time.

## Settings file

`~/.config/luxos/terminal.conf` (created when you close a window):

```ini
[terminal]
font=JetBrainsMono Nerd Font 11
theme=dark          # dark (default, black), light, or auto (follow the system appearance)
opacity=0.95        # background opacity 0.3–1.0 (1 = opaque)
scrollback=10000
sixel=true          # false = no images at all (and the Unicode logo in fastfetch)
logo=true           # false = keep images, but the Unicode logo in fastfetch

[state]
columns=100
rows=30
```

Changes apply to new windows.

## Command line

`luxos-terminal [OPTION…] [-x COMMAND [ARG…]]` – options compatible with xfce4-terminal:

| Option | Meaning |
|---|---|
| `-x`, `--execute CMD ARG…` | run the rest of the command line instead of the shell |
| `-e`, `--command "CMD"` | run a command given as one string |
| `-w`, `--working-directory DIR` | start in DIR |
| `-T`, `--title TITLE` | fixed tab title |
| `-H`, `--hold` | keep the tab open after the command exits (`[Process completed]`) |
| `--tab` | open a tab in the last used window instead of a new window |
| `--geometry COLSxROWS`, `--maximize`, `--fullscreen` | window size |
| `--disable-server` | separate process (does not reuse a running terminal) |
| `-V`, `--version` | version, VTE version and `SIXEL` support |

The shell is your login shell (`lsh` by default), started as a non-login interactive shell like
xfce4-terminal. The environment has `TERM=xterm-256color`, `COLORTERM=truecolor`,
`TERM_PROGRAM=LuxOS-Terminal`, `TERM_PROGRAM_VERSION`.

## Process and memory limits per tab (fork bomb protection)

Every tab runs its shell in its own systemd scope `luxos-terminal-tab-<PID>.scope` (in `app.slice`
of your user systemd) with a process limit (`TasksMax`) and a memory limit. A program that forks
without stopping – a fork bomb such as `:(){ :|:& };:`, or a broken script – only hits the limit of
**its own tab**: new processes in that tab are refused (`fork: Resource temporarily unavailable`),
while the top bar, Dock, Search, keyboard shortcuts, other tabs and other apps keep working. Within
about a second the system guard **luxos-forkguard** stops the runaway processes (see
[troubleshooting.md](troubleshooting.md#a-runaway-program-was-stopped-fork-bomb)); the shell you
typed the command in stays, so the tab is usable again.

- **Process limit:** RAM in MB / 8, at most 5 % of the kernel maximum, at least 1024 and at most
  16384 (16 GB RAM → about 1900). Measured in a VM, one fork-bomb process costs 0.25 MB (`bash -c`)
  to 0.83 MB (typed in the interactive shell, which is copied for every process), half of it kernel
  memory that cannot be swapped – so a bomb in a tab takes at most ~10 % of RAM (~21 % on 4 GB).
  Normal heavy work stays far below (`make -j`, `cargo`, browsers, Steam/Proton, Electron).
  Check it with `systemctl --user show -p TasksMax luxos-terminal-tab-$$.scope`.
- **Memory limit:** `MemoryMax` 75 % of RAM and `MemorySwapMax` 50 % of swap (zram). A program in a
  tab that eats all memory is stopped inside the tab by the kernel (only the biggest process,
  `OOMPolicy=continue` – the shell stays) instead of filling RAM and zram of the whole desktop.
  Large builds (LTO, LLVM, Rust), containers and ML scripts fit into 75 % of RAM.
- When a tab hits the process limit, a red line appears in the tab and a notification "Too many
  processes" says so. **Closing the tab stops all of its processes at once** (`cgroup.kill`). Tabs
  that never hit the limit close as before: programs started with `nohup` or `disown` keep running.
- The shell waits (a few ms) until it is inside its scope, so even a command started directly with
  `-x` cannot fork past the limit.
- To make this possible the terminal runs as the user service `luxos-terminal2.service`, started via
  D-Bus (`cz.luxos.Terminal2`); `luxos-terminal` itself just hands over the command line. If the user
  systemd or the service is not available, the terminal runs as before in one process, without
  scopes (`LUXOS_TERMINAL_NO_SERVICE=1` forces that, for debugging). That fallback process never takes
  over the service's name, so the next window is protected again.
- Administrators can change the limits with a drop-in, e.g.
  `/etc/systemd/user/luxos-terminal-tab-.scope.d/50-limits.conf` with `[Scope]` `TasksMax=4096`,
  `MemoryMax=80%`.

### After an update

Terminal windows opened before an update keep running in the old Terminal process – they cannot be
moved. **Every new window and tab is protected right after the update**, without logging out: the new
Terminal starts its own service under a new D-Bus name even while the old process is still running
(before 1.3.0-3 the new window was handed to the old, unprotected process – a fork bomb there froze
a laptop on 5 November 2026). When old windows are still open, a notification "Older Terminal windows
are not protected" says so once; close them when it suits you. Fork bombs in those old windows (and
anywhere else on the desktop) are stopped by luxos-forkguard.

## Default terminal

- Keyboard shortcuts Super+T and Ctrl+Alt+T, the Dock icon and the menu favourite run
  `luxos-terminal`. Profiles from earlier LuxOS versions are switched once at login (only where the
  old default `xfce4-terminal` was set; your own choice stays), marker `~/.config/luxos/terminal-migrated`.
- *Open Terminal Here* in Files uses the Xfce helper `TerminalEmulator=luxos-terminal`
  (`/etc/xdg/luxos/xfce4/helpers.rc`, helper `/usr/share/xfce4/helpers/luxos-terminal.desktop`;
  your own choice in `~/.config/xfce4/helpers.rc` wins).
- Apps with `Terminal=true` (htop, vim from the menu) open through `xdg-terminal-exec` with
  `/etc/xdg/xdg-terminals.list` → `luxos-terminal.desktop`.
- LuxOS tools that open a terminal (Update in About this Computer, printer driver install, Sandbox,
  Lux Guard, LuxOS Care rollback) use `luxos-terminal`.
- xfce4-terminal is no longer installed on new systems. On updated systems it stays installed but
  is hidden from Launchpad and Search; remove it with `lux remove xfce4-terminal` if you like.

## Speed and memory

Measured under Xvfb with the same VTE (LuxOS `vte3`), font and settings, time from start to the
mapped window (median of 12 runs):

| | Start (new process) | New window (running process) | Memory (PSS) | RSS |
|---|---|---|---|---|
| xfce4-terminal 1.2 | 203 ms | 108 ms | 32.8 MB | 50.4 MB |
| luxos-terminal 1.0 | 175 ms | 53 ms | 31.0 MB | 54.8 MB |

RSS is about 4.5 MB higher only because the title bar and tabs map the UI font (Inter) – shared with
every other app, so the real cost (PSS) is lower. Each further window costs about 0.6 MB in both.
The fastfetch logo is rendered once per font size (about 25 ms), then read from the cache.
