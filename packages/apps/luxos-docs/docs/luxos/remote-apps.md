# SSH and apps from another computer (ssh -X)

A single app window from another computer can be opened on your screen over SSH, the same way
as on X11: type `ssh -X user@computer app` in the terminal. The app runs on the other computer,
its window appears on yours and works normally: keyboard, mouse, clipboard both ways, resizing and
closing. This works in the Wayland session of LuxOS 1.1 and in the X11 session.

```bash
ssh -X anna@office-pc gnome-calculator     # one app
ssh -Y anna@office-pc                     # a shell; apps started in it open on your screen
```

## How it works on Wayland

In an interactive shell (lsh, bash, zsh) of the Wayland session, `ssh -X` and `ssh -Y` go through
the function `ssh` from `/usr/share/luxos/shell/remote-apps.sh` (package `luxos-shell`):

1. **The other computer has waypipe** (every LuxOS 1.1, many distributions): the command becomes
   `waypipe ssh …`. The window is forwarded as a Wayland window, compressed (lz4), with the same
   title bar as local apps. Over slow or distant links this starts much faster than X11, because
   X11 needs hundreds of round trips just to open a GTK window.
2. **The other computer has no waypipe**: plain X11 forwarding. The app is an X11 client of
   XWayland, which LuxOS starts on demand with the first X11 app.

Whether the other computer has waypipe is checked once with a short extra SSH connection
(`command -v waypipe`). The answer is remembered for each user, computer and port in
`$XDG_RUNTIME_DIR/luxos-ssh`: "has waypipe" until you log out, "no waypipe" for 10 minutes.
With key or agent login nothing changes for you; with a password, SSH asks twice the first time.

Scripts are not affected: they run `/usr/bin/ssh` directly. The function also leaves `ssh` alone
when there is no `-X`/`-Y`, and for port forwarding (`-L`, `-R`, `-D`), `-N`, `-f`, `-W`, `-O`,
`-M`, `-S`, `-s`, `-G`, `-Q` and `-V`.

- Off for good: `LUXOS_SSH_WAYPIPE=0` in `~/.config/luxos/shell.conf`.
- Off once: `command ssh -X …`.
- Own waypipe options (for example stronger compression on a slow link):
  `waypipe -c zstd ssh user@computer app`.

## X11 forwarding details

- `-X` behaves like `-Y` (trusted, as on Debian, Ubuntu and Fedora). Untrusted X11 clients
  cannot use the XKB extension, so after switching the keyboard layout they would type the wrong
  letters, and parts of the clipboard do not work. The forwarded app can only see other X11 apps
  in XWayland, never Wayland apps. Add `-o ForwardX11Trusted=no` to get untrusted forwarding.
- XWayland has no authorization cookie, so the function gives SSH a random cookie in
  `$XDG_RUNTIME_DIR/luxos-ssh/xauth` (otherwise SSH prints "No xauth data" every time). Your own
  `XAUTHORITY` with a cookie for the display is used instead when it exists.
- When the other computer allows X11 forwarding and has waypipe, `-X` stays on in the waypipe
  connection, so apps that only speak X11 (xeyes, old Java and Motif apps) still work. When it does
  not allow X11, `-X` is dropped, so SSH does not print "X11 forwarding request failed".
- `Ctrl+C` in the terminal closes the remote app, like plain `ssh -X`.

## Allowing it on a LuxOS computer (server side)

The SSH server is off on LuxOS. Turn it on on the computer whose apps you want to use:

```bash
sudo systemctl enable --now sshd
```

or in the system configuration (`lux system edit`, see [system configuration](system-config.md)):
`"services": {"enable": ["sshd"]}`. The firewall opens TCP 22 automatically while `sshd` is enabled
or running ([firewall](firewall.md)).

LuxOS to LuxOS needs nothing else: waypipe is installed with the desktop and uses a Unix socket
forwarded over the SSH connection (`AllowStreamLocalForwarding`, on by default), not X11.

**X11 forwarding stays off** (`X11Forwarding no`, the OpenSSH default). It is only needed when the
connecting computer has no waypipe (an older LuxOS, an X11-only distribution, macOS with XQuartz),
or for apps that only speak X11. To allow it:

```bash
echo 'X11Forwarding yes' | sudo tee /etc/ssh/sshd_config.d/50-x11.conf
sudo systemctl reload sshd
```

## Speed (measured)

Two LuxOS VMs, GTK demo app, software rendering, link with about 1 ms round trip unless stated:

| | waypipe | X11 through XWayland |
|---|---|---|
| first window (gtk3-demo) | 1.5 s | 1.5 s (3.8 s with XWayland start and the check) |
| first window, 50 ms round trip | 2.8 s | 10–22 s |
| data to open gtk3-demo | 0.3–0.7 MB | 0.4–0.5 MB |
| idle, static window | 0 B/s | 0 B/s |
| idle, window with animations (gtk3-widget-factory) | 4–7 MB/s (zstd: 4 MB/s) | 0.4 MB/s |

waypipe sends changed pixels, so constantly animated content costs more bandwidth than X11 drawing
commands on a fast LAN; on links with latency waypipe is far more responsive.

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| `Error: Can't open display` for an X11-only app | the other computer has `X11Forwarding no`; allow it (above) |
| `waypipe: command not found` (exit 127) | waypipe was removed on the other computer; the next run checks again and uses X11 |
| the window does not appear, `ssh -X` behaves like plain ssh | the shell is not interactive, the session is X11, or `LUXOS_SSH_WAYPIPE=0` |
| typed letters wrong after switching layout (X11 apps) | untrusted forwarding (`ForwardX11Trusted=no`); use the default |
