# LuxOS 1.1.0 – vlastni desktop na Waylandu (plan)

Rozhodnuti majitele 2026-11-21: cil je R2 (tenke jadro libluxcomp v C na wlroots 0.20 s plochym C API + veskera logika spravce oken `luxwm` v LSL; shell v LSL - Python v desktopu zakazan; R3 ciste LSL se neresi). Shell se mezitim vyviji proti beznemu labwc (layer-shell klientum je kompozitor jedno); licence kompozitoru je jedno (GPL-2 ok); poradi podle navrhu; pracuji jen Claude (koordinator) a jeho subagenti. Pilire: bezpecnost, RAM, rychlost; musi bezet vsude (vcetne VM bez 3D - pixman). X11 sezeni zustava jako zaloha (NVIDIA 470xx, problemovy HW). Nikdy netestovat na skutecne obrazovce majitele.

Integracni vetev: `wayland-1.1` (do main az pri vydani 1.1.0). Kazdy balik prace ve vlastni vetvi z `wayland-1.1`.

Nize je podkladovy pruzkum (stav k cfa11537).

---

# LuxOS 1.1.0: own Wayland desktop in LSL. Survey

Date: 2026-11-20. Base: `origin/main` = `cfa11537` (Release 1.0.4 "Sirius").

This was a read-only survey. Nothing graphical was started and nothing ran as root. The other worktrees were only read (git log/diff/status).

External facts come from upstream release pages and issue trackers, fetched 2026-11-20; URLs are in section 4. Items marked **(unverified)** were not tested locally.

---

## 0. Summary

- **Today's desktop is about 40 processes of X11/Xfce glue.** Our own code splits into three groups:
  - **LSL:** about 30 modules, around 25k lines. This covers luxos-hub, Control Center, Calendar, widgets, screenshot, emoji, glass.
  - **C:** about 11 files, around 7k lines. These are the panel plugin, menubar, session cover and lock UI, plus patches to xfwm4, plank, notifyd and screensaver.
  - **Python:** about 37 programs, around 25k lines. These are the settings apps, greeter, Launchpad helpers, screensaver, displays and keyboard.
- **X11 coupling is concentrated in a few places:** `luxos_x11.lsl`, `luxos-session-cover.c`, `luxos-menubar.c`, `luxos-bar.c`, `luxos_wm_icon.py`, `luxos_displays.py`, `luxos-session` (51× xfconf-query) and the greeter (Xlib/XFixes). Section 1.3 has the per-file table.
- **LSL can already drive C libraries,** through `# lsl: internal-abi` + `# lsl: link` + `__lsl_qbe_callN` (up to 12 args), with C→LSL callbacks. It ships bindings for GLib, GIO, GTK 3, cairo and pango.
- **Gaps in LSL:**
  - There are no Wayland, xkbcommon, libinput, pixman, wlroots or gtk-layer-shell bindings.
  - There is no struct layout support.
  - The callback trampolines don't fit the `wl_listener` (container_of) pattern.
  - The GC is a conservative stop-the-world mark-sweep. A frame loop in LSL is therefore risky, and per-pixel work in LSL is slow.
- **The `gtk-layer-shell` 0.10.1 library (GTK 3) is installed.** It is the shortest path for shell UI in LSL: about 15 functions to bind. Section 3 lists the remaining LSL gaps.
- **A pure-LSL Wayland server prototype exists** in `~/Projects/LSL/LSL-Packages/libraries/wayland.lsl` (2863 lines), with DRM dumb-buffer output in `display.lsl`. It is from LSL 0.8.2 and not installed. It has no page flip, layer-shell, dmabuf, XWayland or libinput. It is not a base for 1.1.0.
- **Recommendation** (ranked in section 5):
  - **R1:** a C compositor core forked from **labwc**, pinned to **wlroots 0.20**, with the pixman renderer forced when there is no 3D. Every piece of shell UI is a separate **LSL layer-shell client** (bar, dock, notifications, lock, launcher, desktop/widgets, OSD, greeter UI).
  - **R2** (long-term goal): our own thin C core on wlroots with policy in LSL.
  - **R3:** a pure-LSL compositor. Research only.

---

## 1. Inventory of the current X11/Xfce desktop

Paths are relative to `packages/luxos-desktop/files/` unless noted. The build is in `packages/luxos-desktop/PKGBUILD`:
- C files are compiled with gcc on lines 113–134.
- LSL files go through `lslc --target linux-x86_64-gnu` on lines 144–172.
- It requires `lsl>=0.10.6`. The installed LSL is 0.10.15.
- The session is `xsessions/luxos.desktop` → `Exec=startxfce4`, started under LightDM.

### 1.1 Components

| Function | Today (component) | Language / our code | X11-bound? | Notes |
|---|---|---|---|---|
| Window manager + compositor | xfwm4 + `packages/xfwm4/luxos-windows.patch` (745 l), `luxos-workspace-slide.patch` (1204 l), `luxos-fullscreen-layer.patch` (106 l) | C patches | fully | GLX compositor; xpresent rejected for tearing (`docs/perf/os-memory.md`) |
| Top bar | xfce4-panel + plugin `src/luxos-bar.c` (1666 l, libwnck/xfconf/gdkx) + `src/luxos-menubar.c` (651 l, XInput2 raw + XTest to switch menus) + `src/luxos-panel-menus.c` + genmon (`lsl/luxos-clock.lsl`, `luxos-battery.lsl`, `luxos-netcheck.lsl`, `luxos-appname.lsl` + `luxos-appname-watch` = `xprop -spy`) + whisker, pulseaudio, xkb and systray plugins | C + LSL + shell | fully (wnck, `_NET_*`, xfconf, panel API) | Only the bar logic carries over: WCAG ink with hysteresis, scrim, appearance.conf keys |
| Dock | plank fork `packages/plank/luxos-dock.patch` (448 l) + bamfdaemon, `bin/luxos-dock` | Vala/C patch, shell | fully (bamf/wnck/xprop) | Behaviour tests exist: `packages/plank/tests/dock_zoom.py`, `dock_latency.py` and others |
| Desktop, wallpaper, icons | xfdesktop (+ tumblerd), `src/luxos-desktop-menu.c` (GTK module) | C | fully | |
| Desktop widgets | `lsl/luxos-widgets.lsl` (2086 l) | LSL/GTK 3 | partly (`_NET_CURRENT_DESKTOP`, xfconf wallpaper, DESKTOP type hint) | Drawing code reusable |
| Session helper hub | `lsl/luxos-hub.lsl` (1150 l) + `luxos_*_hub.lsl`, `luxos_awake`, `luxos_mpris`, `luxos_timechange` … | LSL | mostly no; some xfwm4/xfconf/panel calls | Mostly D-Bus logic (BlueZ agent, audio, firewall, Care, news), so ~80 % reusable |
| Control Center | `lsl/luxos_cc.lsl` (1448 l) | LSL/GTK 3 | partly (xrandr for brightness/night light, `_NET_ACTIVE_WINDOW`, positioning) | |
| Calendar popup | `lsl/luxos_cal.lsl` (1819 l), `luxos_ics.lsl` (1898 l), `luxos_date.lsl` | LSL | positioning only | ICS and date logic reusable as-is |
| Launchpad / Search | rofi fork (`packages/rofi`) + `bin/luxos-launchpad` (bash), `python/luxos_launchpad.py`, `bin/luxos-search` | shell + Python | rofi is X11 (rofi 2.x has Wayland upstream (unverified)) | Must be rewritten in LSL (no Python in the desktop) |
| Notifications | xfce4-notifyd + 6 patches (`packages/xfce4-notifyd/*.patch`, ~840 l), themes `luxos-themes/files/notify/*.css` | C patches | partly (xfconf, window placement) | Contract documented in `docs/developers/notifications.md` (on the gpt-features branch) |
| Screensaver / lock | xfce4-screensaver + `packages/xfce4-screensaver/luxos-lock-ui.c` (2313 l), `luxos-lock-kbd.c`, `luxos-lock-battery.c`, `luxos-lock-dialog.patch` (1346 l); savers `screensaver/luxos-screensaver` (Python, Xlib) | C + Python | fully (X grab-based lock) | Look and logic reusable; the security model changes to ext-session-lock-v1 |
| Greeter | LightDM + `packages/luxos-greeter/files/luxos-greeter` (Python, 2439 l, gi LightDM + Gtk 3, Xlib/XFixes for the frame hand-off) | Python | fully | Must become LSL; the hand-off concept changes |
| Session start/end | `bin/luxos-session` (bash, 379 l, 51× xfconf-query, 24× xfwm4), `src/luxos-session-cover.c` (1164 l: XComposite/XFixes black cover and login transition), `xinit/*.sh`, `session/luxos-xauth-wildcard` | bash + C | fully | Replaced by compositor-owned fade + systemd user target |
| Screenshot | `lsl/luxos_shot.lsl` (2796 l), `luxos_shot_base.lsl` (781 l, logic without GTK), `luxos_x11.lsl` (XGrabKey, window list, XFixes cursor, XTest), xclip | LSL | capture and hotkeys X11; UI/editor portable | Capture via ext-image-copy-capture-v1 / portal |
| Emoji picker | `lsl/luxos_emoji.lsl` (1274 l) + `luxos_emoji_base.lsl` | LSL | typing via XTest, active window via `_NET_*` | Needs virtual-keyboard-v1 or input-method-v2 on Wayland |
| Glass material | `lsl/luxos_glass.lsl` (619 l) | LSL/cairo | partly (xfconf wallpaper, `window_get_position`, XShape) | See section 2 |
| GTK helper bindings | `lsl/luxos_gtk.lsl` (902 l), `luxos_glib.lsl` (612), `luxos_gio.lsl` (146), `luxos_sys.lsl` (360) | LSL internal-abi | `luxos_gtk` uses `gdk_x11_window_get_xid`, `gdk_x11_get_server_time` | Pattern for new bindings |
| Smooth scrolling | `src/luxos-scroll.c` (GTK module, XI2) | C | yes | Wayland has smooth scrolling natively; remove |
| Keyboard layouts | `python/luxos_keyboard.py` writes `/etc/X11/xorg.conf.d/00-keyboard.conf` in localectl format, `setxkbmap`, xfce4-xkb-plugin | Python | setxkbmap/xkb-plugin | The localed source of truth stays; the compositor reads `org.freedesktop.locale1` X11Layout/Options into xkbcommon |
| Displays | `python/luxos_displays.py` (521 l, xrandr 16×), `luxos_arrange.py`, `bin/luxos-displays` (wmctrl/xrandr), `bin/luxos-display-settings` | Python + bash | fully | Becomes wlr-output-management-v1 (or compositor IPC) |
| Shortcuts | `python/luxos_shortcuts.py` (xfconf xfce4-keyboard-shortcuts), xfwm4 keybinds | Python | xfconf | Becomes compositor config (labwc rc.xml `<keybind>`) generated from LuxOS config |
| xsettings | xfsettingsd, `xdg/xfce4/xfconf/.../xsettings.xml`, dconf `dconf/10-luxos`, `xdg/gtk-3.0/settings.ini` | config | X11 only for xsettings | GTK on Wayland reads gsettings/settings.ini; color-scheme via portal (`docs/developers/appearance.md` on the gpt branch) |
| Window icons | `python/luxos_wm_icon.py` (Xlib `_NET_WM_ICON`) | Python | yes | Becomes xdg-toplevel-icon-v1 (wlroots 0.19+) or app-id → icon theme |
| Other X helpers | `bin/luxos-unfreeze` (xprop/xfwm4), `bin/luxos-tour` (XShape via ctypes), `bin/luxos-appearance` (21× xfconf-query, 8× xfwm4, xrandr) | bash/Python | yes | |
| Settings apps (not shell) | `bin/luxos-settings`, `-power`, `-bluetooth`, `-calculator`, `-camera`, `-monitor`, `-router`, `-tour`, `-whats-new`, `-fingerprint`, `-feedback`, `-profile-picture`, `-wifi-qr`, `-lock-settings`, `-app-reset`, `-portal-check`, `-keyboard`, `-shortcuts`, `-display-settings` | **Python** gi Gtk 3 | mostly not (some xfconf) | Run on Wayland unchanged via GTK, but the "no Python in the desktop" rule means LSL rewrites. A separate, parallelisable track |
| Sandbox display | `packages/luxos-sandbox/files/luxos-sandbox` (Xephyr in bwrap, XSecurity cookies) | Python | yes | Becomes Wayland security-context-v1 (labwc already allowlists globals for sandboxed clients) |
| Other packages with X calls | `luxos-text.c` (gdk_x11, `_NET_*`), `luxdrop/remote.py` (xdotool), `luxos-installer` (setxkbmap), `luxos-guard_session.py` (Xinerama) | C/Python | small | Audit list for an XWayland-free session |

The full per-file token table was made with a grep over `packages/` (excluding tests and patches); section 1.3 has the raw result.

### 1.2 RAM (from `docs/perf/os-memory.md`, 4 GB KVM, std VGA, 2 min after login, PSS MiB)

| Process | PSS | What replaces it in 1.1.0 |
|---|---:|---|
| Xorg | 65.0 | compositor (+ XWayland only on demand) |
| xfwm4 | 46.2 | compositor |
| xfce4-panel + whisker/pulseaudio/notify wrappers | 62.5 | LSL bar (1 process) |
| xkb plugin wrapper | 23.3 | folded into the bar |
| plank + bamfdaemon | 31.9 | LSL dock (no bamf; foreign-toplevel) |
| xfdesktop (+ tumblerd 28.1, exits after 5 min) | 28.1 | LSL background/widgets layer |
| luxos-hub | 24.3 | stays (LSL) |
| nm-applet | 18.1 | Wi-Fi popup in the bar (`luxos_bar_popups.lsl` pattern) + NM secret agent in the hub |
| polkit-gnome, xfsettingsd, xfce4-session, screensaver, power-manager, Thunar --daemon | 76.9 | polkit agent (LSL/C), no xfsettingsd/xfce4-session; locker spawned on demand; power handling in the hub |
| **Session total (user PSS)** | **≈400** | target: at most 250 (estimate, to be measured in WP-1) |

LSL baseline (from `docs/perf/lsl-rewrite-plan.md` §6): the Python → LSL hub rewrite saved 23 MB PSS, and a GTK 3 window in LSL costs about the same as in C (`/usr/lib/lsl/docs/developer_guides/gtk.md`: ~150 ms, 88 MB RSS under Xvfb, of which LSL itself is ~2 MB).

**No compositor RSS figures were found published** for labwc or wayfire; this is an acceptance measurement for WP-2.

### 1.3 X11-specific calls per file (counts)
```
src/luxos-session-cover.c   _NET_*(12) XComposite(6) XFixes(11) XGetWindowProperty(6) XInternAtom(12) XRandR(4) XOpenDisplay(4)
src/luxos-menubar.c         _NET_*(8) XGrabKey XTest(13) XRandR(9) XSendEvent(2) XInternAtom(8)
src/luxos-bar.c             wnck_*(18) xfconf_*(19) gdk_x11 _NET_* xfce4-panel API
src/luxos-scroll.c          gdk_x11(3) + XI2
lsl/luxos_x11.lsl           gdk_x11(4) _NET_*(19) XFixes(4) XGrabKey(2) XTest(5) XSendEvent XGetWindowProperty
lsl/luxos_shot.lsl          _NET_*(2) xclip(7) XGrabKey
lsl/luxos-widgets.lsl       _NET_*(3) xfconf(2)
lsl/luxos_cc.lsl            xrandr(6) xfconf-query(3) _NET_ACTIVE_WINDOW
lsl/luxos_cal.lsl           _NET_ACTIVE_WINDOW xfconf-query(2)
lsl/luxos-hub.lsl           xfwm4(10) xfconf(3) xfce4-panel(2)
lsl/luxos_gtk.lsl           gdk_x11_window_get_xid, gdk_x11_get_server_time
lsl/luxos_glass.lsl         xfconf(2) (+ XShape via gtk shape, window_get_position)
lsl/luxos_awake.lsl         xfconf(5)
lsl/luxos-appname.lsl       xprop -spy
bin/luxos-session           xfconf-query(51) xfwm4(24) xfce4-panel(17) plank(11) xprop xauth
bin/luxos-appearance        xfconf-query(21) xfce4-panel(10) xfwm4(8) xrandr(3) plank(4)
bin/luxos-displays          xrandr(8) wmctrl(4)   python/luxos_displays.py xrandr(16) xfconf(3)
bin/luxos-keyboard          setxkbmap(6)          python/luxos_keyboard.py setxkbmap(2)
python/luxos_shortcuts.py   xfconf(9) xfwm4(10)   python/luxos_wm_icon.py Xlib/_NET_WM_ICON
bin/luxos-unfreeze          xprop(3) xfwm4(6)     bin/luxos-tour XShape/XOpenDisplay
screensaver/luxos-screensaver GdkX11/XOpenDisplay luxos-greeter Xlib XFixes(7) XChangeProperty
packages/luxos-sandbox      Xephyr, xauth(7), Xlib
```

---

## 2. Unreleased UI code (read-only review of branches and worktrees)

There is one body of work: the "1.1.1 glass" UI. It exists in four copies:

| Copy | Ref / state | Use |
|---|---|---|
| branch `gpt-features-1.1.1` (also on origin) | `eaee2515` (2026-11-18), 67 files, +8202, base 58 behind main | **Cleanest reference** |
| `~/LuxOS-Arch-ui` | branch `glass-ui-current` (HEAD `08bd4ffd`, in main) + 68 uncommitted files | **Newest port** onto newer main; adds `glass.setup_solid()`, `BAR_COVER=clear`/`BAR_SHADE`, and a menubar DESKTOP-window fix |
| `~/LuxOS-Arch-glass` | `glass-ui-experiment` = `gpt-wip-20261118` `da4a6d4b` + 23 uncommitted files | Same UI mixed with unrelated fixes |
| `~/LuxOS-Arch-main-ui` | `glass-ui-on-main` `9e65b389`, **unresolved merge conflicts** | Abandoned; ignore |
| `~/LuxOS-Arch-luxai-lsl` | `agent/luxai-lsl` `f249a2d0`, already in main | No desktop UI |

The commit message itself says "unfinished … not for the stable release". No record was found that its tests pass.

There is **no Wayland, layer-shell or non-GTK LSL toolkit code** anywhere. Everything is GTK 3 + cairo.

### Reusable for a Wayland shell
- **Glass material math** (pure cairo, reusable as-is):
  - In `src/luxos-glass.c` (821 l), the functions `glass_surface`, `glass_stats`, `glass_veil` and `glass_paint` (~l. 55–300). How it works: wallpaper scaled to 96 px, 2-pass 1-4-6-4-1 blur, desaturation, luminance-dependent veil, sheen.
  - The LSL equivalents are in `lsl/luxos_glass.lsl`.
  - Pixel equivalence tests: `test_luxos_glass_module.py`, `test_luxos_glass_py.py`.
- **`lsl/luxos_bar_popups.lsl`** (1835 l) and its 61-line client `luxos-bar-popup.lsl`: Wi-Fi (NM D-Bus `AddAndActivateConnection`, password never on argv), Sound (`pactl -f json`) and notification history popups.
  - Reusable with changes: placement must become layer-shell anchors and margins; replace the xfconf/`org.xfce.Panel` glue.
- **`src/luxos-notifyd.c`** (384 l): history sync, `x-luxos-keep`, `cz.luxos.NotificationHistory.Activate`. The D-Bus contract is reusable; reimplement it inside our own LSL notification daemon.
- **Specs** (on the gpt branch, `docs/developers/`):
  - `notifications.md`: hints, 6 s timeout
  - `appearance.md`: portal `org.freedesktop.appearance color-scheme`
  - `dock.md`: `com.canonical.Unity.LauncherEntry` badges
- **Design tokens.** There is **no central token file**; values are duplicated in `luxos_glass.lsl`/`.py`, `luxos-glass.c`, the CSS strings in `luxos_bar_popups.lsl` and `luxos_cc.lsl`, `GLASS_*` in `luxos-account`, and `luxos-themes/files/*.css`. Recurring values:
  - radii 16 (windows, menus), 18 (popups, Control Center), 14 (tiles), 10 (rows), 999 (pills)
  - accent `#3d7bff`, error `#ff453a`, traffic lights `#ff5f57` / `#febc2e` / `#28c840`
  - card edge alphas .38 / .62 / .20, glass base `rgba(235,240,250,.86)`, sheen 8–14 %
  - dark popup background `rgba(32,33,52,.86)`, light `rgba(246,247,252,.88)`

### X11-bound in that work
- `src/luxos-xkb.c` (XKBlib `_XKB_RULES_NAMES`; only the badge look is worth keeping).
- The glass changes in `luxos-bar.c`: wnck, XID, `_NET_SYSTEM_TRAY_COLORS`, xfconf, a DESKTOP-hint scrim window.
- The module wiring in `luxos-glass.c`: GTK_MODULES injection into xfce4-panel/notifyd, and menu backdrop via a root-window screenshot (`gdk_pixbuf_get_from_window(root)`).
- `migrate_panel()`.

### Consequence
The wallpaper-slice "fake blur" exists only because xfwm4 cannot blur. With our own compositor, real background blur belongs **compositor-side**, done once per damaged region and cached for static wallpaper. The client-side material then stays as the fallback for software rendering.

---

## 3. LSL capabilities for a compositor or shell

LSL 0.10.15 is installed: `/usr/bin/lslc`, `/usr/lib/lsl/{stdlib,docs,runtime}`. The source is at `~/Projects/LSL/lsl` (HEAD `4847a8e` "Release LSL 0.10.15"). Backend: LuxIR (QBE-derived).

### 3.1 What exists
- **Dynamic C interop** (target `linux-x86_64-gnu`, `docs/developer_guides/gtk.md`):
  - The pragma `# lsl: link libfoo.so.N` becomes `DT_NEEDED`. The linker checks symbols at compile time, so a missing function is a build error.
  - Calls go through `__lsl_qbe_callN / icallN / fcallN` with up to 12 args (`compiler/pure/validation.lsl:268`). There are `__lsl_qbe_f32` for C `float`, `load/store8..64`, `__lsl_address`, `__lsl_symbol`.
  - This is "internal ABI", meant only for trusted modules (`# lsl: internal-abi`). The policy pass that blocks it is skipped by direct `lslc` (`12-compiler-internals.md` ~l. 205–215). LuxOS already uses it in its own modules: `luxos_x11.lsl`, `luxos_gtk.lsl`, `luxos_glib.lsl`, `luxos_gio.lsl`, `luxos_sys.lsl`.
- **C→LSL callbacks:**
  - Trampolines `lsl_arch_callback`, `_u3`, `_u4`, `_u7` and `_u8`. The suffix is the user_data position (first, 3rd, 4th, 7th, 8th). See `~/Projects/LSL/lsl/runtime/arch/linux_gnu_x86_64.S:329–415` and the dispatch in `/usr/lib/lsl/stdlib/glib.lsl:75–160`.
  - Up to 6 boxed args. Errors in the handler are caught and printed as "LSL callback error".
  - Wayland **client** listener structs pass `void *data` as the **first** argument, so they fit `lsl_arch_callback` directly.
- **Stdlib bindings:** `glib`, `gio`, `gtk` (GTK **3** only, `libgtk-3.so.0`), `cairo`, `pango`. Also `unixsock`, `fd`, `process`, `json`, `lconf`, `time`, `crypto`, `tls`, `http`, `sandbox`.
- **GLib event loop:** `glib.unix_fd_add` (g_unix_fd_add_full) means a wayland-client display fd, or libinput/DRM fds, can be integrated into the GLib main loop. There are also `idle_add`, timeouts with priorities, and `unix_signal_add`.
- **Threads:** `thread_spawn` (up to 127 workers, 8 MiB stacks), futex locks, atomics on `IntArray`. The GC is stop-the-world across threads (`11-performance-and-optimization.md` §Vlákna, `12-compiler-internals.md` l.147).
- **Memory model:** conservative mark-sweep GC (`12-compiler-internals.md` l.325). It triggers by allocation volume (4 MiB starting budget). It is "not a hard-real-time collector".
  - `IntArray`/`ByteArray` hold raw values. `List` boxes everything.
  - Float arithmetic boxes intermediates, which made per-pixel shapes "~1000× slower" (comment in `LSL-Packages/libraries/gfx.lsl`).
- **Performance data:** GTK window in LSL ≈ C (88 MB RSS, ~150 ms under Xvfb). Hub: 15.7 MB PSS idle vs 38.7 MB in Python (`docs/perf/lsl-rewrite-plan.md`).
- **Pure-LSL graphics packages** (`~/Projects/LSL/LSL-Packages/libraries`, registry v0.8.2, **not installed**):
  - `wayland.lsl` (2863 l): a Wayland server written from the wire protocol (wl_compositor/shm/seat/output, xdg_wm_base/toplevel/popup, keymap fd).
  - `display.lsl` (761 l): X11 window / fbdev / DRM dumb buffer + DIRTYFB, but **no page flip**, so tearing is likely.
  - `input.lsl`: raw evdev. `gfx.lsl`: integer rasteriser, blur. `ui.lsl`, `css.lsl`.
  - This proves LSL can speak the protocol, but it lacks dmabuf, layer-shell, xdg-decoration, XWayland, libinput and multi-GPU, and pixels are computed in LSL.

### 3.2 Locally available C libraries
- Present: libwayland-{client,server,cursor,egl} 1.26, libxkbcommon 1.13.2, libinput 1.32 (so 10.13), pixman 0.46.4, libdrm, libgbm, libEGL (mesa + nvidia 620.73), **libgtk-layer-shell 0.10.1**, GTK 4 runtime.
- **Not installed but in the repo:** wlroots0.20 0.20.2, labwc 0.20.3, gtk4-layer-shell 1.3.0, greetd 0.10.3, xorg-xwayland 24.1.15, grim/slurp 1.5.0, wl-clipboard 2.3.0, xdg-desktop-portal-wlr 0.8.4, seatd 0.9.3, cage 0.3.1.
- `pacman` is not on this system (`lux` instead).

### 3.3 LSL gaps (to add before or alongside the desktop)
| # | Gap | Why it matters | Proposed fix |
|---|---|---|---|
| L1 | No **public, supported FFI**. Desktop modules rely on `internal-abi`, which only works because direct `lslc` skips the policy pass | Fragile; the wrong trust boundary for a security pillar | Formal "system binding" mechanism: a signed/allowlisted module directory (e.g. `/usr/lib/lsl/system/`) for LuxOS bindings |
| L2 | **No struct layouts.** Offsets are hand-coded (`__lsl_qbe_load64(base+24)`) | wlroots structs change every minor release, so hand offsets break silently | Keep wlroots-facing code in C; or a build-time generator `lsl-cstruct` (offsets from C headers via a tiny C program) |
| L3 | **wl_listener / container_of callbacks** aren't supported. Trampolines assume user_data at a fixed argument position; `wl_signal` notify passes `(listener, data)` | Can't bind wayland-server/wlroots signals directly | New trampoline variant: "record pointer stored right after the listener struct", or a C shim that converts signals to `(user_data, …)` callbacks |
| L4 | **Callback records are never freed** (`handlers.append(record)` in glib.lsl `record_new`) | Long-running compositor/shell with per-surface listeners leaks | `record_free(handle)` + a destroy-notify path |
| L5 | One global `lsl_arch_callback_slot` (single dispatcher); callbacks max 6 args | OK for one GLib thread; risky if a C library calls back from its own thread | Document "main thread only"; assert thread id in dispatch |
| L6 | GC stop-the-world, no hard-RT; Float boxing | A frame loop in LSL could miss vblank (jank, "flicker-like" stutter) | Hot path (render, input dispatch) in C/pixman; LSL only for event-driven policy and UI |
| L7 | Only GTK 3 bound; no **gtk-layer-shell**, **wayland-client**, **xkbcommon**, gtk4 | Shell clients need layer-shell; the bar needs the layout name; the dock needs foreign-toplevel | `luxos_layer.lsl` (gtk-layer-shell, ~15 functions), `luxos_wl.lsl` (wl_display fd + registry + the few protocols we need through wayland-scanner-generated C glue), `luxos_xkb.lsl` |
| L8 | Dynamic-library target is documented only for `linux-x86_64-gnu` (`gtk.md`) | An ARM LuxBook/RPi target wouldn't build the desktop | Port the gnu target trampolines to aarch64 (arch file `linux_arm64.S` exists for the static target) |
| L9 | Known: `strip` breaks gnu binaries (`options=(!strip)`), the program starts in locale "C", no stderr in the public API (`lsl-rewrite-plan.md` §5) | Packaging and i18n | Already worked around; fix upstream |
| L10 | No PAM binding | Lock screen and greeter | A small C helper (`luxos-auth`, setuid-free, via a greetd IPC or a PAM conversation over a pipe), called from LSL |

**gtk-layer-shell option:** yes. `libgtk-layer-shell.so.0` 0.10.1 is installed and GTK 3 is what LSL binds, so a layer-shell bar or dock in LSL needs only:
- `gtk_layer_init_for_window`, `set_layer`, `set_anchor`, `set_margin`, `auto_exclusive_zone_enable`, `set_keyboard_mode`, `set_namespace`, `set_monitor`, `is_supported`

gtk4-layer-shell 1.3.0 also offers a session-lock API, but would require binding GTK 4 first (a large job). **Recommendation:** GTK 3 + gtk-layer-shell for 1.1.0. For the lock screen, use a small dedicated ext-session-lock client (C or LSL over wayland-client) rather than gtk-session-lock, which is stale (0.2.0, 2024).

---

## 4. Compositor base and session stack (external facts)

### 4.1 wlroots
- **Versions:** 0.20.2 (2026-07-07), 0.20.1 (2026-05-19), 0.20.0 (2026-03-26), 0.19.3 (2026-03-19). Source: https://gitlab.freedesktop.org/api/v4/projects/wlroots%2Fwlroots/releases
- **No API stability:** every minor release breaks the API (0.18 removed `wlr_renderer_begin`; 0.19 removed buffer age; 0.20 changed event timespecs and the text-input headers). The soname is versioned (`libwlroots-0.20.so`), so a release can be pinned.
- **Renderer auto-selection** (`render/wlr_renderer.c` 0.20):
  - The order is gles2 → vulkan → pixman.
  - Pixman is picked automatically only when the DRM device has **no render node**: bochs-drm (QEMU std VGA) and simpledrm.
  - llvmpipe is refused unless `WLR_RENDERER_ALLOW_SOFTWARE=1`.
  - virtio-gpu without virgl, or vmwgfx without 3D, may fail instead of falling back (unverified reading of the code; issue #3477).
  - So **LuxOS must detect "no usable 3D" and set `WLR_RENDERER=pixman` explicitly**, or retry with pixman on failure.
  - Env reference: https://gitlab.freedesktop.org/wlroots/wlroots/-/raw/0.20/docs/env_vars.md
- **Pixman path:** double-buffered dumb-buffer swapchain with page flips, so no tearing in principle.
- **Open VM issues:**
  - #3930: corruption with virtio without virgl
  - #4040: pixman multi-output across virtio/QXL
  - #4071: vmwgfx dmabuf close EINVAL
  - #3839: simpledrm → real driver hand-off leaves a dead screen. Relevant to early start; order the session after the GPU driver is loaded.
  - #3621: VirtualBox `drm_dumb: Failed to get PRIME handle` (closed; whether it's fixed is unverified)
- **Avoid reading back from write-combined scanout memory.** The KWin QPainter experience (https://bugs.kde.org/show_bug.cgi?id=466633) shows it costs seconds per frame and black bands. Keep damage small.
- **Cursor:** DRM cursor hotspots for VMs since 0.18. #3731 (offset under virtio, open); fallback `WLR_NO_HARDWARE_CURSORS=1` gives a software cursor.
- **Multi-GPU:** render on the primary (`WLR_DRM_DEVICES` first entry), copy to the other GPUs' outputs. Hybrid AMD + NVIDIA behaviour is **unverified**.
- **NVIDIA:** needs GBM (≥ 21.1 in 0.20; the 470xx driver has no GBM, which matters because LuxOS ships `nvidia-470xx-utils`). linux-drm-syncobj-v1 since 0.18, full explicit sync since 0.19. Upstream still says "do not open issues for proprietary drivers". Sway 1.12 no longer refuses to start on NVIDIA.
- **Protocols:**

  | Protocol / feature | Since |
  |---|---|
  | ext-session-lock-v1 | 0.16 |
  | wp-fractional-scale-v1, security-context-v1, cursor-shape | 0.17 |
  | ext-foreign-toplevel-list | 0.18 |
  | ext-image-copy-capture, ext-data-control, layer-shell v5, xdg-toplevel-icon | 0.19 |
  | ext-workspace-v1, per-window capture sources | 0.20 |

  wlr-screencopy and wlr-data-control are deprecated in 0.20. input-method-v2 and text-input-v3 are present. XWayland is supported. HDR is Vulkan-only (not needed).
- **Nested and headless backends:**
  - The headless backend has no requirements.
  - The x11 backend needs Present, XFixes ≥ 4 and XInput2; DRI3 is optional, with a fallback to MIT-SHM. So **wlroots nested in our private Xvfb with pixman should work (unverified)**.
  - The x11 backend fails on the NVIDIA X server (#3954).

### 4.2 Candidate bases
| | (a) labwc fork | (b) wayfire | (c) own C core on wlroots + LSL policy | (d) Smithay (Rust) | (e) pure LSL (LSL-Packages wayland.lsl) |
|---|---|---|---|---|---|
| Version | 0.20.3 (2026-10-30, wlroots 0.20.2); 0.9.x LTS-like branch on wlroots 0.19 | 0.11.0 (2026-07-27) | n/a | 0.7.0 (2025-06) | prototype, LSL 0.8.2 |
| Size | ~46k lines of C, 703 kB package | ~82k lines of C++, 9.3 MB package | target 10–20k lines of C | Rust | 2.9k + 0.8k lines of LSL |
| Licence | GPL-2.0-only | MIT | ours | MIT | MIT (ours) |
| No-GPU | pixman via autocreate; theme has software-renderer defaults; its error text suggests `WLR_RENDERER=pixman` | pixman core since 0.10, effects are GLES | same pixman path; we own the fallback logic | pixman renderer exists but niri/cosmic don't use it (niri needs EGL) | dumb buffer without page flip, so tearing |
| Security | security-context global allowlist (`src/server.c allow_for_sandbox`), `<privilegedInterfaces>` (0.20.0) | security-context in 0.11 | full control | memory-safe | memory-safe language; huge attack surface written by us |
| Ecosystem | Raspberry Pi OS default since 2024-10; LXQt and Xfce Wayland sessions default to it | Raspberry Pi dropped it | — | Xfce's experimental xfwl4 uses it | — |
| Tests upstream | cmocka helper tests only | headless core harness (0.11) | ours | — | — |
| Effort for 1.1.0 | low | medium (C++) | high | very high, foreign toolchain | very high |

Sources: https://github.com/labwc/labwc/releases, https://raw.githubusercontent.com/labwc/labwc/master/NEWS.md, https://github.com/WayfireWM/wayfire/releases, https://github.com/Smithay/smithay/releases, https://github.com/YaLTeR/niri/discussions/2570, https://wiki.xfce.org/releng/wayland_roadmap, https://docs.xfce.org/xfce/xfwl4/start, https://hackaday.com/2024/10/28/raspberry-pi-oss-wayland-transition-completed-with-switch-to-labwc

**KibaOS flicker context:** KWin and Mutter on QEMU std VGA / llvmpipe show known framebuffer failures and black bands (Debian #1115707, KDE #466633, RH #2312900). That KibaOS hit exactly this is a plausible guess, not verified.

### 4.3 Session, greeter, lock, capture, input, a11y
- **Greeter:** greetd 0.10.3 (repo), with the greeter running under a kiosk compositor. The usual one is cage 0.3.1; we can run our own compositor in a greeter mode instead.
  - LightDM greeters are X11-only. Keeping LightDM means keeping Xorg for login, which **contradicts the RAM and Wayland goals**.
  - SDDM's Wayland greeter is still "experimental".
  - **Recommendation:** greetd + LSL greeter UI as a layer-shell/fullscreen client in `luxwm --greeter`. Auth goes through greetd IPC (JSON over a unix socket; LSL has `unixsock` + `json`), so **no PAM in the UI process**.
- **Lock:** ext-session-lock-v1 (the compositor guarantees that if the locker crashes, the screen stays locked).
  - swaylock 1.8.6 is maintained.
  - gtklock 5.0.1: its author says it is "probably the last release".
  - gtk-session-lock is stale.
  - So build our own LSL locker on wayland-client with a session-lock binding, plus a PAM helper (L10). Reuse the look of `luxos-lock-ui.c`.
- **Screenshots and screencast:**
  - Capture via ext-image-copy-capture-v1 (our own code in `luxos_shot` replacing XFixes/xclip).
  - Portal: xdg-desktop-portal-wlr 0.9.0 upstream (2026-11-12; ScreenCast via ext_image_copy, repo has 0.8.4) + xdg-desktop-portal-gtk (installed) for the rest.
  - Clipboard: ext-data-control-v1 (wl-clipboard 2.3.0) replaces xclip.
- **Input methods:** input-method-v2 / text-input-v3 (fcitx5 works on labwc since 0.7.2). The emoji picker types via virtual-keyboard-v1 or as an input method instead of XTest.
- **Accessibility (weak spot):**
  - wlroots has no a11y protocol, and labwc has no a11y code.
  - Orca needs the `org.freedesktop.a11y.KeyboardMonitor` D-Bus interface. niri implements it (https://github.com/YaLTeR/niri/wiki/Accessibility); sway has only an open PR #9331.
  - We must implement it ourselves (small and well-defined), which fits LSL + GIO.
- **Keyboard:** the compositor reads localed X11Layout/Variant/Options (the same source `luxos_keyboard.py` writes) and builds an xkbcommon keymap. The layout switch indicator gets the current group from the compositor via IPC or wl_keyboard.
- **XWayland:** xorg-xwayland 24.1.15; labwc can run without it (0.20.0). Use on-demand/lazy start to save RAM; Xorg was 65 MB in the X session.

---

## 5. Recommended architecture (ranked)

### R1: labwc-derived C core ("luxwm") + LSL shell clients. RECOMMENDED for 1.1.0
- **Compositor:**
  - Fork labwc 0.20.x, built against `libwlroots-0.20` (pinned soname; packaged as `wlroots0.20` in the [luxos] repo so an Arch update cannot break it).
  - Strip the Openbox-menu/theme parts we don't use.
  - Add:
    1. VM/no-3D detection and a pixman retry. Check for a render node and test EGL creation; when not usable, force `WLR_RENDERER=pixman` + `WLR_NO_HARDWARE_CURSORS=1`; otherwise gles2.
    2. LuxOS window behaviour from the xfwm4 patches: workspace slide, fullscreen layer, placement, Alt+\`. Animations are disabled under pixman.
    3. Server-side decorations in the LuxOS look (traffic lights), using the token module.
    4. Compositor-side blur behind layer surfaces and opted-in toplevels: blurred wallpaper texture cached, gles2 only. Under pixman, the wallpaper-slice material (section 2) is the fallback with no live blur.
    5. `org.freedesktop.a11y.KeyboardMonitor`.
    6. A small IPC socket (JSON lines) for the shell: layout group, active app name, workspace, Expose triggers, and the login/logout fade replacing `luxos-session-cover.c`.
  - Keep labwc's security-context allowlist; privileged protocols (screencopy, data-control, foreign-toplevel-management, virtual-keyboard, output-management) only for LuxOS shell binaries. Matching is by path and the security-context `app_id`/sandbox engine (this mechanism needs checking).
- **Shell:** separate small LSL processes on GTK 3 + gtk-layer-shell, each crash-isolated and restarted by a systemd user unit:
  - `luxos-bar`: bar + popups + tray via StatusNotifierItem
  - `luxos-dock`: ext-foreign-toplevel-list + wlr-foreign-toplevel-management for activate/close
  - `luxos-desktop`: background layer, wallpaper and widgets; reuses `luxos-widgets.lsl`
  - `luxos-notify`: org.freedesktop.Notifications + the history API
  - `luxos-lock`: ext-session-lock
  - `luxos-launchpad` + search: overlay layer, replacing rofi
  - `luxos-osd`
  - `luxos-hub`: kept, with its X11 bits removed
- **Session:** greetd → `luxwm --greeter` + LSL greeter; on login, `luxwm` user session started via a systemd user target (`luxos-session.target`). No xfce4-session, xfsettingsd, xfconf or LightDM.
- **Why it fits the pillars:**
  - Smallest proven C core with a pixman path.
  - RAM: drops Xorg (65 MB) + xfwm4 (46 MB) + panel wrappers (85 MB) + plank/bamf (32 MB); estimated savings of 150 MB or more, to be measured.
  - Wayland isolation fixes the X11 keylogging/screenshot exposure that `luxos-sandbox` currently works around with Xephyr.
  - Effort fits one release.
- **Costs:**
  - GPL-2.0 applies to the compositor fork, so it cannot go closed source. That conflicts with the closed-source direction (memory note 2026-11-17); separate shell clients are unaffected.
  - We rebase on labwc each wlroots minor release (roughly yearly).
  - No LSL in the compositor itself.

### R2: own thin C core on wlroots ("libluxcomp") + policy in LSL (long-term; 1.2+)
- A C library (~8–15k lines) owning the scene graph, render loop, input, outputs, XWayland and protocols. It exposes a flat C API with opaque handles and callbacks whose user_data comes first, so it fits LSL trampolines without struct offsets (fixes L2/L3).
- Window management policy (placement, keybinds, workspace logic, rules) is written in LSL in the compositor process, event-driven only, with no per-frame LSL code (L6).
- Can be MIT/proprietary (our code) if desired; wlroots is MIT.
- Start it after R1 ships, reusing R1's tests. Migrate one policy area at a time behind R1's IPC.

### R3: pure-LSL compositor (research only)
- Based on `LSL-Packages/libraries/wayland.lsl` + `display.lsl`.
- Would need: page-flip/atomic KMS, dmabuf/linux-dmabuf, libinput or our own evdev with full a11y, XWayland, multi-GPU, NVIDIA, pixel work in C kernels, and much faster LSL Floats.
- Not viable for 1.1.0. Useful as a long-term LSL showcase and as a protocol test client.

**Not recommended:**
- wayfire: C++ plugins, GLES-centric effects, Raspberry Pi dropped it.
- Smithay: Rust toolchain alongside LSL, and its API breaks too.

---

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| wlroots auto-selection fails on virtio-gpu without virgl or vmwgfx without 3D, producing a black screen or corruption (#3477, #3930, #4071) | "runs everywhere" pillar | Explicit detection + pixman retry; VM matrix in CI (WP-1) |
| simpledrm→amdgpu/nvidia hand-off during early start (#3839) | blank screen on real hardware | greetd unit `After=` udev settle/GPU readiness; watch for DRM device removal and restart the backend |
| NVIDIA proprietary is unsupported upstream; 470xx has no GBM | users with old NVIDIA lose the desktop | Keep the X11 session as fallback for 1.1.x (install both; auto-pick X11 when GBM is missing) |
| Hybrid AMD+NVIDIA copy path untested | owner's machine | Owner-hardware acceptance test; render on AMD by default |
| LSL GC pauses or callback leaks in long-running shell clients (L4/L6) | jank, memory growth | Hot paths in C; leak test (24 h soak with RSS slope limit) |
| Internal-ABI reliance (L1) | security review, breakage on LSL updates | WP-0 formalises system bindings |
| Accessibility regressions (Orca) | legal/B2B | KeyboardMonitor in WP-2; Orca smoke test |
| Apps that call X11 directly (luxos-text gdk_x11, luxdrop xdotool, Python settings apps via xfconf) | features broken under XWayland or Wayland | WP-12 audit; XWayland on demand |
| GPL-2 on the labwc fork | closed-source plan | R2 later; keep proprietary bits in shell clients |
| Loss of xfwm4-patch behaviour (workspace slide, Alt+\`, placement) and plank zoom polish | perceived regression | Port behaviour tests (`packages/plank/tests/dock_zoom.py` scenarios) to the Wayland harness |
| Two desktops to maintain during the transition | effort | Freeze X11 features after 1.0.x; ship Wayland as the default with X11 as fallback for one release |

---

## 7. Work packages (independent, hand-off ready)

Common rules for every package:
- Prefix commands with `env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY`.
- No real display.
- Large builds and VMs go in `out/`.
- Tests run in the WP-1 harness.

**WP-0: LSL FFI hardening (LSL repo)**
- Inputs: L1–L5, L8 above; `stdlib/glib.lsl`; `runtime/arch/linux_gnu_x86_64.S`.
- Outputs:
  - a trusted "system binding" directory mechanism
  - `record_free` + destroy notify
  - a `wl_listener` trampoline (record stored after the listener)
  - a main-thread assert in dispatch
  - (optional) the aarch64-gnu target
- Acceptance:
  - LSL tests: 10⁶ create/free cycles of callbacks with stable RSS (±1 MB)
  - a listener test against a C fixture library that emits `wl_signal`
  - `lslc` rejects internal ABI outside allowlisted paths

**WP-1: Headless test harness and VM matrix**
- Inputs: wlroots0.20, labwc 0.20.3 (repo), grim, `scripts/luxos-testguard.sh`, `scripts/test-vm.sh`, `scripts/vmctl.py`.
- Outputs `scripts/wl-test/` with:
  1. headless run: `WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1 WLR_HEADLESS_OUTPUTS=1`, private `XDG_RUNTIME_DIR`, screenshot via grim (ext-image-copy-capture)
  2. nested run: wlroots x11 backend inside a private Xvfb
  3. VM matrix: QEMU `-vga std`, `virtio-vga` without virgl, `-vga vmware`, plus a VirtualBox VMSVGA note. QMP screendump at 30 fps for 10 s while dragging a window and opening menus; a frame-diff "flicker detector" flags any full-black or regressed frame
- Acceptance:
  - harness runs stock labwc and gets non-empty screenshots in headless and nested modes
  - flicker detector catches an injected black frame
  - zero false positives on 3 idle runs

**WP-2: luxwm compositor (labwc fork)**
- Inputs: labwc 0.20.3 source, the xfwm4 patches (behaviour spec), the token module (WP-4), WP-1.
- Outputs:
  - `packages/luxwm` + `packages/wlroots0.20` (pinned)
  - renderer detection and fallback
  - LuxOS SSD theme
  - IPC socket spec (`docs/developers/luxwm-ipc.md`)
  - KeyboardMonitor D-Bus interface
  - privileged-protocol allowlist
  - compositor blur (gles2) + no-op under pixman
  - login/logout fade
  - keymap from locale1
- Acceptance:
  - starts and renders in all WP-1 VM targets with no flicker detected
  - idle PSS measured with `scripts/perf/mem-snapshot.py`, target ≤ 40 MB under pixman at 1080p (measure, then set the target)
  - a sandboxed client (security-context) can't bind screencopy or foreign-toplevel
  - Orca reads a focused GTK app (manual)
  - owner hybrid machine: login, external monitor, game on NVIDIA

**WP-3: LSL Wayland/layer bindings (LuxOS)**
- Inputs: `/usr/lib/libgtk-layer-shell.so.0`, `luxos_gtk.lsl` pattern, WP-0.
- Outputs:
  - `lsl/luxos_layer.lsl` (gtk-layer-shell)
  - `luxos_wl.lsl` (C glue generated by wayland-scanner and built into a small `libluxos-wl.so`) covering ext-foreign-toplevel-list, wlr-foreign-toplevel-management, ext-session-lock-v1, ext-image-copy-capture-v1, ext-data-control-v1, virtual-keyboard-v1, wlr-output-management-v1
  - `luxos_luxwm.lsl` (IPC client)
- Acceptance: a unit test per protocol against labwc/luxwm headless (list toplevels, lock and unlock, capture one frame, set the clipboard).

**WP-4: Design tokens + glass material module**
- Inputs: values from section 2; `luxos-glass.c` math; `luxos_glass.lsl`.
- Outputs:
  - `lsl/luxos_tokens.lsl` (single source; generates CSS and the compositor theme)
  - `luxos_material.lsl`: wallpaper source from LuxOS config, not xfconf; offsets from layer anchors; no XShape
- Acceptance: pixel-equivalence test against the existing C material, keeping `test_luxos_glass_module.py` thresholds.

**WP-5: Top bar `luxos-bar` (LSL)**
- Inputs: `luxos-bar.c` behaviour (clock centre, ink/WCAG with hysteresis, scrim), `luxos_bar_popups.lsl`, the genmon LSL scripts, WP-3/4.
- Outputs:
  - layer-shell top bar with exclusive zone
  - app name via ext-foreign-toplevel
  - clock/calendar toggle, Control Center toggle
  - Wi-Fi/Sound/Notifications popups
  - StatusNotifierItem tray (+ watcher)
  - keyboard layout badge via luxwm IPC
- Acceptance:
  - runs under WP-1 with screenshot goldens light/dark
  - popup opens in ≤ 120 ms warm (same budget as today, `lsl-rewrite-plan.md` §6)
  - idle PSS ≤ 25 MB (target)
  - crash → restarted by systemd within 1 s, exclusive zone preserved

**WP-6: Dock `luxos-dock` (LSL)**
- Inputs: plank patch behaviour, `packages/plank/tests/*` scenarios, skel dock items, LauncherEntry spec.
- Outputs: bottom layer surface; pinned plus running apps; magnification (off under pixman unless measured fine); autohide; badges.
- Acceptance: ported zoom-leave scenarios (zoom gone within 0.45 s); activate/minimise via foreign-toplevel; flicker detector clean in std VGA.

**WP-7: Notifications `luxos-notify` (LSL)**
- Inputs: `docs/developers/notifications.md` (gpt branch), `src/luxos-notifyd.c` logic, notify CSS.
- Outputs: `org.freedesktop.Notifications` server, history, DND, `cz.luxos.NotificationHistory`.
- Acceptance: `notify-send` matrix (actions, replace-id, urgency, transient, `x-luxos-keep`); history persists across restarts.

**WP-8: Lock `luxos-lock` (LSL + C PAM helper)**
- Inputs: `luxos-lock-ui.c` look and tests (`tests/test-lock-kbd.c`, `test-lock-battery.c`, `fake-pam.c`), ext-session-lock binding, faillock policy (memory: lockouts only at brute-force rate).
- Outputs: locker, PAM helper, idle → lock via ext-idle-notify-v1, logind Lock/PrepareForSleep integration.
- Acceptance:
  - killing the locker keeps the screen locked (compositor red/blank)
  - fake-PAM tests pass
  - fingerprint path
  - lock appears before suspend completes

**WP-9: Greeter (greetd + LSL UI)**
- Inputs: `luxos-greeter` (Python) behaviour and `tests/gui-*.py`, greetd IPC spec.
- Outputs: `luxos-greeter` in LSL under `luxwm --greeter`; config in `/etc/greetd/config.toml`; login transition handled by the compositor (no frame hand-off).
- Acceptance: login, wrong password, caps lock, domain user (AD), fingerprint, multi-user, battery tests ported; no X server running at the greeter.

**WP-10: Desktop layer (`luxos-desktop`): wallpaper, widgets, desktop menu**
- Inputs: `luxos-widgets.lsl`, `luxos-desktop-menu.c`, xfdesktop config.
- Outputs: background layer per output with wallpaper and widgets; workspace from ext-workspace-v1.
- Acceptance: goldens, multi-monitor via headless 2 outputs, PSS budget.

**WP-11: Launchpad/Search (LSL, replaces rofi)**
- Inputs: `bin/luxos-launchpad`, `python/luxos_launchpad.py`, rofi themes.
- Outputs: overlay layer surface with keyboard-exclusive mode, app grid, search.
- Acceptance: open time measured with the existing `scripts/perf/launch-probe.py` method; keyboard-only navigation.

**WP-12: Screenshot, emoji, clipboard, displays, keyboard, shortcuts ports**
- Inputs: `luxos_shot*.lsl`, `luxos_emoji*.lsl`, `luxos_displays.py`, `luxos_keyboard.py`, `luxos_shortcuts.py`, the per-file X11 table (section 1.3).
- Outputs:
  - Wayland backends for `luxos_shot` (capture, per-window sources) and emoji (virtual-keyboard)
  - display settings via wlr-output-management in LSL
  - keyboard via locale1 + luxwm reload
  - shortcuts → luxwm config
  - removal of xfconf usage from `luxos-hub`, `luxos_cc`, `luxos_cal` and `luxos_awake`
- Acceptance: each LSL test suite runs headless; grep for X11 tokens in shipped Wayland-session code = 0 (except the XWayland fallback).

**WP-13: Session and services**
- Inputs: `bin/luxos-session` duties (first-login defaults, shadow guard, chromium flags, theme), `luxos-hub`.
- Outputs: `luxos-session.target` + units, a polkit agent (LSL or C), portal config (wlr + gtk), XWayland on demand, an X11-session fallback selector.
- Acceptance:
  - cold login to usable desktop timed against today's 1.0.4 (`scripts/perf/login-probe.py`)
  - full session PSS ≤ 250 MB in the 4 GB VM (target; baseline ≈ 400 MB)
  - no Python process running in the idle session

**WP-14: Sandbox to Wayland security-context**
- Inputs: `packages/luxos-sandbox` Xephyr design, luxwm allowlist.
- Outputs: sandboxed apps get a security-context socket; no Xephyr unless the app is X11-only (then XWayland-in-sandbox).
- Acceptance: a sandboxed client can't list toplevels, capture the screen or read the clipboard without focus; the existing `test_sandbox_launch.py` scenarios pass.

**WP-15: Python settings apps → LSL** (parallel, not blocking the shell)
- Inputs: the Python list in section 1.1.
- Outputs: per-app LSL rewrites, highest-traffic first: settings, power, bluetooth, display, keyboard.
- Acceptance: per-app feature parity tests; PSS lower than the Python version.

**Suggested order:**
1. WP-1 and WP-0 in parallel.
2. Then WP-2, WP-3 and WP-4 in parallel.
3. Then WP-5 through WP-12 in parallel, after WP-3 lands.
4. Then WP-13 and WP-14.
5. WP-15 runs throughout.

---

## 8. Not verified / open questions
- Whether virtio-gpu without virgl exposes a render node (which decides pixman auto-selection); real x11-backend behaviour in Xvfb; compositor RAM figures. All are covered by WP-1.
- Hybrid AMD+NVIDIA (620.73 open driver) behaviour on wlroots 0.20.
- Whether rofi 2.x Wayland mode would be an acceptable interim launcher.
- Whether labwc's security-context matching can identify LuxOS shell clients robustly (by path, or by a launcher-issued security-context).
- The LuxOS AD/domain login path under greetd (the PAM stack is the same; greeter UI work only).
