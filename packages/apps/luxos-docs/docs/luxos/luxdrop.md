# LuxDrop

LuxDrop (`luxdrop`, package `luxdrop`) sends files, folders and text securely to devices on the
same local network. It speaks two protocols:

- **LuxDrop protocol** (LuxOS ↔ LuxOS): TLS 1.3, pinned keys and a 6-digit verification code. This
  is the default whenever both sides run LuxOS.
- **LocalSend protocol v2** (v2.2, compatible with 2.0/2.1): for the LocalSend app on Android,
  phones and tablets, Windows and other Linux systems. It uses HTTPS with mutual TLS.

The full specification is in `/usr/share/doc/luxdrop/PROTOCOL.md`.

## GUI

Run `luxdrop` (Launchpad: LuxDrop), or `luxdrop FILE…` to open it with files already selected. In
Files (Thunar), right-click › **Send To › LuxDrop** (`/usr/share/Thunar/sendto/luxdrop.desktop`).

- **Send**: "Choose what to send or drop files here, then tap a device". You can pick Files, a
  Folder, Text, or Paste from the clipboard.
- **Nearby devices**: LuxOS computers (mDNS `_luxdrop._tcp`) and LocalSend apps (multicast). Use
  Refresh, **Scan the local network** (finds LocalSend devices when multicast is blocked) or
  **Connect by address…** (IP of the other device).
- **Receive**: a "Ready to receive" switch, and **Who can send**: Everyone nearby, Trusted devices
  only, or receiving off ("Receiving is turned off. Other devices cannot see this computer.").
  Recently received files have "Open folder" and "Show in folder".
- **Settings**:
  - Device name, Save to (folder).
  - **Quick save**: save files from trusted devices without asking.
  - **Receive when LuxDrop is closed**: enables the background service. Requests then appear as
    notifications.
  - **Work with LocalSend apps** (port 53317), PIN for LocalSend senders.
  - Trusted devices (Remove), and the key fingerprint of this computer.
  - Security notes.

## Verification code and trust

When two LuxOS computers meet for the first time, both screens show the same **6-digit code**
(e.g. `972 316`). The receiver must click **Accept**, and the sender must confirm that the
receiver shows the same code. Only then is data sent. "Trust this device" (on by default) pins the
other computer's key. After that no code is shown, and with Quick save the transfer is accepted
automatically.

If a trusted device later shows a different key, the transfer is aborted with `key_mismatch`
("someone may be impersonating the device"). There is no fallback to code pairing. To pair again,
first remove the device from Trusted devices (`luxdrop trust remove <ID>`).

LocalSend has no verification code, so trust works on first use. "Trust this device" is off by
default for LocalSend devices. Plain-HTTP LocalSend devices (encryption turned off in LocalSend)
are shown as "Unencrypted", and nothing is sent to them or accepted from them.

## Who may send (receive modes)

| Mode | Trusted device | Unknown device |
|---|---|---|
| `off` | refused | refused |
| `trusted` | allowed (auto-saved with Quick save, otherwise asked) | refused without asking |
| `everyone` (default) | allowed | you must Accept after comparing the code |

`everyone` can be limited in time (at most 10 minutes, then back to `trusted`). Every transfer from
an unknown device always needs an explicit Accept. A request expires after 120 s. The same policy
applies to LocalSend senders, who can additionally be required to enter a PIN.

## Command line

```
luxdrop                                  # GUI (also: luxdrop gui, luxdrop FILES…)
luxdrop devices [--timeout 3] [--scan]   # list nearby devices (--scan: also scan the LAN for LocalSend)
luxdrop send TARGET FILE…                # TARGET = device name, ID, HOST[:PORT] or NAME@HOST[:PORT]
luxdrop send TARGET --text "hello"       # send a text message
luxdrop send TARGET FILE --localsend     # send to a LocalSend device (phone, Windows, …)
     [--pin PIN] [--port N] [--no-remember] [-q]
luxdrop receive [--mode off|trusted|everyone] [--minutes N] [--dir DIR] [--port N] [--bind ADDR]
                [--no-mdns] [--ls-port N] [--no-localsend] [--no-multicast] [--pin PIN]
luxdrop trust [list]                     # trusted devices
luxdrop trust remove ID|NAME
luxdrop id                               # this device's name and key fingerprint
luxdrop mode [off|trusted|everyone] [--minutes N]
```

When sending in a terminal, `luxdrop send` prints the receiver and the verification code and asks
"[y]es and remember / [o]nly this time / [N]o". Exit codes: 0 ok, 1 failure, 2 usage, 3 declined,
4 key problem.

## Files of another computer

LuxDrop can also open the **shared folders** of another LuxOS computer in Files, side by side
with your own files (drag & drop copies between the computers). The other computer turns on
Settings › **Share folders** (only Public by default) and must allow each new computer:
**Allow once**, **Always allow** or **Deny**. Access is read-only unless the owner also allows
changes. See [Files of another computer](remote-files.md).

```
luxdrop connect [TARGET] [--write] [--no-open] [--port N]   # without TARGET: "Connect to Computer" window
luxdrop disconnect [NAME | --all]
luxdrop connections
luxdrop share [status | on | off | add FOLDER [--yes] | remove FOLDER]
luxdrop share forget|allow-write|read-only ID
```

## Background receiving

The user service `luxdrop-receiver.service` runs `luxdrop receive --service`. Turn it on with
"Receive when LuxDrop is closed" in Settings, or with
`systemctl --user enable --now luxdrop-receiver.service`. Accept requests appear as notifications,
or as a dialog when a display is available.

## Files and folders

| What | Where |
|---|---|
| Received files | `~/Downloads/LuxDrop` (XDG download folder + `LuxDrop`), or the folder from Settings |
| Partial downloads | `<download folder>/.luxdrop-partial/` (verified by SHA-256 before being moved into place; existing files are never overwritten, names get " (1)") |
| Settings | `~/.config/luxdrop/settings.json` (`name`, `receive_mode`, `download_dir`, `port`, `background`, `auto_accept_trusted`, `localsend`, `localsend_port`, `pin`) |
| Identity key and certificate | `~/.local/share/luxdrop/identity-key.pem`, `identity-cert.pem` (EC P-256) |
| Trusted devices, history | `~/.local/share/luxdrop/trusted.json`, `history.json` |
| Shared folders, computers with access | `~/.config/luxdrop/shares.json`, `~/.local/share/luxdrop/file-access.json` |

## Ports and firewall

| Port | Use |
|---|---|
| TCP 47923 | LuxDrop protocol (receiver) |
| TCP 47924 | Shared folders (only while sharing is on) |
| TCP 53317 | LocalSend HTTPS server |
| UDP 53317 | LocalSend multicast discovery, group 224.0.0.167 (link-local) |
| UDP 5353 | mDNS (Avahi) |

LuxOS ships no firewall by default, so nothing needs to be opened. If you enable one, allow these
ports **only on private networks**. The package includes a firewalld service and a ufw profile:

```
sudo firewall-cmd --permanent --zone=home --add-service=luxdrop && sudo firewall-cmd --reload
sudo ufw allow from 192.168.0.0/16 to any app LuxDrop
```

## Troubleshooting

- **No LuxOS computers found**: `avahi-daemon` must be running (the app says so when it is not):
  `systemctl status avahi-daemon`.
- **Port in use**: "Cannot receive from LuxOS computers: port 47923 is in use". Another LuxDrop
  instance (for example the background receiver) is probably running.
- **Devices not visible on guest Wi-Fi** (client isolation, no multicast): use Scan the local
  network or Connect by address.
- **LocalSend compatibility missing**: it needs the `python-pyopenssl` package.
- **"key_mismatch"**: the other device has a new key (reinstall) or someone is impersonating it.
  Check it, then remove the old trust entry and pair again.
