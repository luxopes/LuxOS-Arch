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
  - The drop-in `greetd.service.d/luxos.conf`, which runs `greetd --config /etc/greetd/luxos.toml`.
    The `config.toml` of the greetd package is left alone, so the two packages never fight over a file.
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
- **Duties carried over from `bin/luxos-session` (X11):**
  - The shadow guard for old copies in `~/.local`.
  - First-login defaults: user dirs, appearance, `/etc/luxos/new-users.conf`.
  - Chromium WebGPU flags.
  - The wallpaper for `luxos-backdrop`.
  - The managed `gtk.css` block.
  - Tour, Welcome and What's new, as the transient unit `luxos-first-run`.
- **Not carried over:** the xfconf migrations, which have no meaning without Xfce, and these, which are left to
  WP-12: `luxos-hub`, saved display layout, software brightness, power saver re-apply, clock alarms and data saver.

## Tests

| Test | What it covers |
|---|---|
| `packages/luxos-greetd/tests/test_luxos_greeter_wl.py` | The greeter under `luxwm --greeter` in the wl-test harness against a fake greetd: login, wrong password, Caps Lock, domain user, session choice, per-user session, legacy NVIDIA, failed-start fallback, fingerprint messages, power buttons, no X server, PSS |
| `packages/luxos-desktop/tests/test_luxos_polkit_wl.py` | The polkit agent against a fake authority and helper |
| `scripts/wl-preview/smoke.sh` | The preview VM, headless: boot to the greeter, login, bar crash, idle PSS and no Python, logout, compositor crash, X11 session, and timings |
