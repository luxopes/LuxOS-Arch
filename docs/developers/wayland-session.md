# Wayland session and login screen (LuxOS 1.1.0)

WP-9 and WP-13 in `docs/proposals/wayland-desktop-1.1.0.md`. This page covers how LuxOS logs in on Wayland and how
the session is started, supervised and stopped.

## Overview

```
greetd (root, VT 1)
 └─ greeter session (user greeter): luxos-greeter-session
     └─ luxwm --greeter /usr/lib/luxos/luxos-greeter      (Xorg + xinit on NVIDIA 470 and older)
         greetd IPC: create_session → PAM conversation → start_session; the greeter exits, greetd starts the session
user session (logind session, Type=wayland)
 └─ luxos-wayland-session                                  session leader (bash)
     └─ luxwm "luxos-wayland-session --started"           compositor, in the session scope
          └─ systemctl --user start luxos-session.target   (after the socket exists)
systemd --user
 └─ luxos-session.target  BindsTo=graphical-session.target
     ├─ luxos-bar  luxos-dock  luxos-backdrop  luxos-widgets  luxos-notify
     ├─ luxos-lock (watcher; the locker itself is ext-session-lock)  luxos-launchpad
     └─ luxos-polkit
```

## Login screen (`luxos-greetd`)

- The package contains:
  - `/usr/lib/luxos/luxos-greeter`: the LSL greeter (`packages/luxos-greetd/files/lsl`).
  - `/usr/lib/luxos/luxos-greeter-session`: the greetd command.
  - `/etc/greetd/luxos.toml`.
  - `luxos-greetd.service` (alias `display-manager.service`), which runs `greetd --config /etc/greetd/luxos.toml`.
    The `config.toml` of the greetd package is left alone, so the two packages never fight over a file. It is its own
    unit because `greetd.service` is ordered after `plymouth-quit-wait.service` (a drop-in cannot remove that), which
    meant a black screen and the text console between the boot splash and the login screen.
  - The boot splash hand-off, like LightDM: `plymouth-quit.service` conflicts, `plymouth deactivate` runs before
    greetd so luxwm gets DRM, and `luxos-greetd-splash` runs `plymouth quit --retain-splash` once the greeter has
    drawn its first frame (it writes `$XDG_RUNTIME_DIR/luxos-greeter-shown`; at most 10 s).
- PAM runs in greetd, under the `greetd` service. The greeter only speaks the JSON IPC on `GREETD_SOCK`, so no PAM
  code and no password check run in the UI process.
- **What the greeter shows and handles:**
  - The look of the lock screen (`luxos_lock_draw`): blurred wallpaper (`background` in
    `/etc/lightdm/luxos-greeter.conf`, if present), date and clock, avatar, glass password field, Caps Lock, the
    layout chip, and the battery.
  - The user row. Users come from `/etc/passwd` (UID_MIN..UID_MAX, with a login shell). AccountsService adds real
    names, avatars and cached domain users (UID ≥ 100000).
  - **Other…** is a free username field. It is always present when the PC is in a domain (`lux-domain status
    --json`).
  - The session button at the bottom left.
  - Sleep, Restart and Shut Down, through logind.
- **PAM messages:**
  - `info` and `error` are shown under the field. They cover pam_fprintd, pam_faillock and SSSD (offline,
    expired, domain-locked).
  - `secret` and `visible` prompts become the field label. This includes password change prompts.
- **Fingerprint:**
  - `luxos-fingerprint-pam` adds the same block to `/etc/pam.d/greetd` as to LightDM.
  - greetd runs PAM strictly in sequence, so the password prompt comes only after pam_fprintd gives up. The
    timeout for greetd is therefore 10 s, not 30 s.
  - A password typed meanwhile is kept and sent with the prompt.
- **Session choice:**
  - Sessions are read from `wayland-sessions/*.desktop` and `xsessions/*.desktop`; `xfce.desktop` is hidden.
  - The last session is remembered per user in `/var/lib/luxos-greeter/state`.
  - Default is LuxOS (Wayland). X11 is the default instead in these cases:
    - NVIDIA 470 and older, or NVIDIA without `nvidia_drm modeset=Y`.
    - The last Wayland session ended within 10 s of starting, which protects against a login loop on broken
      graphics. The greeter then says so.
- X11 sessions start through `/usr/lib/luxos/luxos-x11-session`: `startx` on the session VT, with
  `/etc/X11/xinit/xinitrc.d` sourced like LightDM's Xsession.
- **luxwm --greeter:**
  - One client, fullscreen and focused.
  - No key bindings, no XWayland, no privileged protocols.
  - luxwm exits when the greeter exits.
  - Ctrl+Alt+F1..F12 switch consoles (in libluxcomp, for every mode).

### Switching between greetd and LightDM

| Action | Command | Effect |
|---|---|---|
| greetd (Wayland login) | `lux install luxos-greetd` | `post_install` disables lightdm and runs `systemctl enable -f greetd` (`display-manager.service`) |
| back to LightDM | `lux remove luxos-greetd` | `post_remove` disables greetd and enables lightdm again if it is installed |

Both take effect after the next restart. A running session is never stopped. Without the package, LightDM and the
Python greeter keep working as in 1.0.x (X11 only).

## Session (`luxos-desktop`)

- **Compositor as the session leader.** `luxwm` runs in the logind session scope, not as a user unit:
  - libseat and logind need the session for DRM and input.
  - When luxwm ends (logout, crash, `quit`), `luxos-wayland-session` stops `luxos-session.target` and
    `graphical-session.target`, removes the session variables from the systemd and D-Bus activation environment,
    and exits. greetd then shows the login screen.
- **Shell clients as user units.** Each one has its own `Restart=` (bar and Dock 200 ms). A crash restarts only
  that client. The compositor and the other clients keep running.
- **Logout** is `loginctl terminate-session auto` (bar menu). On SIGTERM the launcher forwards the signal to luxwm
  and cleans up.
- **Exported variables:**
  - `WAYLAND_DISPLAY`, `DISPLAY` (lazy XWayland) and `XDG_SESSION_ID` (polkit agent, lock).
  - `XDG_CURRENT_DESKTOP=LuxOS`, so the portals use `luxos-portals.conf`.
  - The toolkit variables (`GDK_BACKEND`, `QT_QPA_PLATFORM`, `MOZ_ENABLE_WAYLAND`, `SDL_VIDEODRIVER`,
    `ELECTRON_OZONE_PLATFORM_HINT`) and the cursor theme.
- **Portals:** Screenshot and ScreenCast go through `xdg-desktop-portal-wlr`, which is on the luxwm privileged
  allowlist. Everything else goes through `xdg-desktop-portal-gtk` (file chooser, settings), and Secret through
  gnome-keyring.
- **Polkit agent:** `luxos-polkit` (LSL), see the header of `files/lsl/luxos-polkit.lsl`. It speaks the
  AuthenticationAgent D-Bus interface and the helper line protocol of polkit 128 directly. There is no
  libpolkit-agent, because PolkitAgentListener would need GObject subclassing.
- **Environment like the X11 login:** `/etc/profile` is sourced (`/etc/xdg/luxos`, `/var/lib/luxos/apps`,
  Flatpak, the LuxOS PATH), and `PATH`, `XDG_CONFIG_DIRS` and `XDG_DATA_DIRS` are imported into systemd --user.
  `luxos-wayland-settings` copies xsettings to gsettings before the shell starts and gives the cursor variables.
- **XDG autostart** follows the desktop entry spec for `LuxOS`: user entries override system ones, in the order of
  `XDG_CONFIG_DIRS`. An entry is skipped when it has `Hidden`, an `OnlyShowIn` without LuxOS, a `NotShowIn` with
  LuxOS, or a missing `TryExec`. Each entry runs as a transient unit `app-luxos-autostart-*` bound to the session.
  `/etc/xdg/luxos/autostart` keeps nm-applet, blueman, the print applet and Plank in Xfce only.
- **Duties carried over from `bin/luxos-session` (X11):**
  - The shadow guard for old copies in `~/.local`.
  - User dirs at every login; first-login defaults: appearance, `/etc/luxos/new-users.conf`.
  - Chromium WebGPU flags.
  - The wallpaper for `luxos-backdrop`.
  - The managed `gtk.css` block.
  - Tour, Welcome and What's new, as the transient unit `luxos-first-run`.
  - One-time import of the Xfce keyboard shortcuts into `~/.config/luxwm/luxwm.conf`
    (`luxos-keyboard-settings --import-shortcuts`, once luxwm is up).
- **Not carried over:** the xfconf migrations, which have no meaning without Xfce, and these, which are left to
  WP-12: `luxos-hub`, saved display layout, software brightness, power saver re-apply, clock alarms and data saver.

## Top bar and its popups (`luxos-bar`, `luxos-hub`)

The look follows the unreleased 1.1.1 glass UI the owner had on local branches (`gpt-features-1.1.1`,
`~/LuxOS-Arch-ui`, owner feedback 2026-11-21, item 8):

- **Glass cards.** The bar popups (system menu, Wi-Fi, Sound, Notifications), the Control Center and the Calendar
  paint a cut-out of the blurred wallpaper under their card (`luxos_hub_popup.paint_glass` →
  `luxos_material.strip`, the same maths as `luxos-glass.c`): a veil measured from the wallpaper keeps the text
  readable, white card edges, sheen, radius 18 px. The client paints it, so the cards stay transparent without
  compositor blur too (pixman, VMs without 3D). Without a wallpaper the CSS material applies. Like 1.1.1, the
  card shows the wallpaper, not the windows behind it. The compositor still draws the shadow (`@popup:18`).
- **Keyboard layout:** a bold code (`US`, `CZ`) in the bar ink, no frame, only with two or more layouts. A click
  switches to the next layout at once (luxwm `next_layout`) and flashes the accent for 650 ms. Right click or a
  500 ms hold opens the layout menu with Keyboard Settings.
- **Control Center:** on Wayland the Wi-Fi and Bluetooth tiles work like Android. The round icon toggles (NetworkManager radio,
  BlueZ `Powered`). The rest of the tile opens the Wi-Fi popup of the bar (SIGUSR1 to the PID in
  `$XDG_RUNTIME_DIR/luxos-bar.pid`) or the Bluetooth app.
- **LuxOS logo = system menu (decision for item 10).** It stays a system menu and does not become an app menu:
  apps live in Launchpad and Search, and an app menu would duplicate them with a second, smaller list. It has the
  1.1.1 Whisker Menu look as a glass popup: photo and name on top, About This Computer, Settings and Launchpad,
  then round buttons with labels for Lock Screen, Sign Out, Restart and Shut Down. Launchpad therefore does not need
  to change for this item.
- **X11:** the Control Center and Calendar get the 1.1.1 glass card on X11 too (`luxos_glass.panel`, only with a
  compositor) and the same CSS; their tiles keep the X11 behaviour. The rest of the 1.1.1 X11 work (glass `luxos-bar.c`, the `luxos-xkb` text plugin,
  the X11 bar popups, the `luxos-glass` GTK module) is not ported; the X11 bar is unchanged.

## Tests

| Test | What it covers |
|---|---|
| `packages/luxos-greetd/tests/test_luxos_greeter_wl.py` | The greeter under `luxwm --greeter` in the wl-test harness against a fake greetd: login, wrong password, Caps Lock, domain user, session choice, per-user session, legacy NVIDIA, failed-start fallback, fingerprint messages, power buttons, no X server, PSS |
| `packages/luxos-desktop/tests/test_luxos_polkit_wl.py` | The polkit agent against a fake authority and helper |
| `scripts/wl-preview/smoke.sh` | The preview VM, headless: boot to the greeter, login, bar crash, idle PSS and no Python, logout, compositor crash, X11 session, and timings |
