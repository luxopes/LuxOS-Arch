# Login, lock screen and screen saver

How LuxOS signs you in, locks the screen and shows the screen saver. The rest of the desktop is described in [desktop.md](desktop.md).

## Login and lock screen

The login screen is `luxos-greeter`, a LightDM greeter (Python + GTK). At rest it shows the
wallpaper, the date and a large clock, with keyboard, battery and network at the top right. A click
or a key shows the avatars, the password field and the power buttons. After 30 s of idle it returns
to the clock. If a fingerprint reader is set up, you can log in with your finger
([settings-apps.md](settings-apps.md#fingerprint)).

The configuration file is `/etc/lightdm/luxos-greeter.conf`, with keys `background`,
`user-background`, `clock-24h=auto`, `clock-format`, `date-format`, `idle-timeout`, `font`,
`cursor-theme`, `show-battery` and `show-network`. `/etc/lightdm/lightdm.conf.d/60-luxos-greeter.conf`
selects this greeter. To preview it without LightDM: `luxos-greeter --demo` (the password is
`luxos`).

The login screen and the screen shown when switching users use the wallpaper of the user's desktop
(in the current light or dark mode): `luxos-appearance greeter-sync` writes it to AccountsService
(`BackgroundFile`) at login, when the mode changes and, through `luxos-hub`, whenever the desktop
wallpaper changes. A wallpaper the login screen cannot read (in the home folder) is replaced by the
LuxOS wallpaper of the current mode; a `BackgroundFile` set by other means is left alone.
`LOGIN_WALLPAPER=0` in `~/.config/luxos/appearance.conf` turns this off; `user-background=false` in
`luxos-greeter.conf` makes the login screen always use `background`.

The avatar is the user's profile picture from AccountsService (`IconFile`,
`/var/lib/AccountsService/icons/<user>`); without one the screen shows the first letter of the name on
a blue-violet circle. Change it in **Profile Picture** (see [settings-apps.md](settings-apps.md#profile-picture)).

**After login** the greeter hides the clock and the form and leaves only the (slightly dimmed)
wallpaper as the last frame; the session starts at most one frame later. Right before that it puts the
frame into a window on its own X connection in `RetainPermanent` mode, so the X server keeps it on the
screen after the greeter exits, on every driver (the root window is `X -background none`, which
drivers without glamor, e.g. QEMU with bochs + llvmpipe, cannot keep). The window is named in the
root property `_LUXOS_LOGIN_HOLD`. The greeter also saves the frame to the LightDM data folder of the
user (`/var/lib/lightdm-data/<user>/login-frame.raw`, removed after use, plus a small blurred
wallpaper as the last resort).

`luxos-session-cover --login` (started by `/etc/X11/xinit/xinitrc.d/60-luxos-login-cover.sh` before
the session) takes the frame over (and frees the greeter's window) and shows it with a small spinning
loader where the password field was, until the desktop is really ready:

- its window lives in the Composite overlay window, above everything the compositor draws, so the
  start of the xfwm4 compositor cannot hide it (xfwm4 often did not paint a full-screen window that
  existed before the compositor started — that was the black screen after login);
- it ends only when the xfdesktop window really shows the wallpaper (the contents of its composited
  window are an image and no longer change — xfdesktop loads the wallpaper in the background) and the
  top bar and Dock have drawn; then it dissolves in about 0.3 s (a normal translucent window with the
  same frame, composited by xfwm4 over the finished desktop).

It never delays anything: input goes through it; without a compositor it waits 0.4 s after the desktop
and the top bar are mapped (and up to 1.5 s more for a compositor); a solid-colour desktop counts as
ready after 1.2 s, a desktop that never draws after 4 s; it always ends within 15 s. With Battery
Saver on, or with GTK animations turned off (xsettings `EnableAnimations`), it just disappears without
the fade. Other sessions only free the greeter's frame (`luxos-session-cover --release`); `luxos-session`
does the same as a safety net. The frame-capture test `packages/luxos-desktop/tests/login-transition/run.sh`
(private Xvfb + xfwm4 compositor, hundreds of frames per second) fails on any black frame.

The screen locks with `xflock4` (`Super+L`, `Ctrl+Super+Q`). The lock settings are in Screen Saver &
Lock. The default screen saver of the locked screen, "Desktop wallpaper and clock", shows the same
wallpaper as the desktop with a large clock; the password dialog uses it too. When a key or the mouse
wakes the locked screen, xfce4-screensaver (`[luxos]` build) keeps the last frame of the screen saver
as the background of its window until the password dialog has drawn, and the last frame of the dialog
when it goes back to the screen saver — no black frame in between.
