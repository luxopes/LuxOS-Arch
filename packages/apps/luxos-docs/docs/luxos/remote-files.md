# Files of another computer (Connect to Computer)

Files (Thunar) can show the shared folders of another LuxOS computer on the same network next to
your own files, like in macOS Finder. Drag & drop copies files between the two computers. The
feature is part of LuxDrop (package `luxdrop`) and needs no SSH server and no administrator
password on either computer.

## Quick start

1. **On the computer with the files**: LuxDrop › Settings › **Share folders** (or
   `luxdrop share on`). The first time only the **Public** folder (`~/Public`, in Czech
   `~/Veřejné`) is shared. Add more folders with **Add folder…**.
2. **On your computer**: open **Connect to Computer** (Launchpad, Search, or LuxDrop › Settings ›
   Connect to Computer…), pick the computer and click it. You can also type its address.
3. Both screens show the same **6-digit code** (only the first time). The owner of the other
   computer sees "“<name>” wants to access your shared folders" and chooses **Allow once**,
   **Always allow** or **Deny**. You click **Codes match**.
4. A Files window opens split in two: your home folder on one side, the other computer on the
   other side (F3 toggles the split). The computer also appears in the sidebar of Files.

To change files on the other computer, tick **Ask for permission to change files** before
connecting. The owner then sees "wants to access and change your shared folders" and must also
tick **Also allow changes (copy in, rename and delete files)**. Without it the connection is
read-only.

## Security model

- **Nothing is shared by default.** Sharing is off until the owner turns it on, and then only
  the Public folder is shared.
- **Every new computer must be allowed** on the sharing computer. "Allow once" lasts for one
  connection. "Always allow" remembers the computer (Settings › Computers with access). "Deny"
  also refuses the same computer for the next 5 minutes without asking again.
- **Read-only by default.** Write access needs a request from the connecting computer and an
  explicit tick by the owner. Notification buttons (when no dialog can be shown) never grant
  write access.
- **Encrypted and authenticated**: TLS 1.3 with the LuxDrop identity keys of both computers and
  the same verification code as LuxDrop. A trusted computer that suddenly has a different key is
  refused (`key_mismatch`).
- **Only the shared folders exist for the other computer.** The file server (OpenSSH
  `sftp-server`) runs in a bubblewrap sandbox without network, without capabilities and without
  the rest of the disk. Paths with `..`, absolute paths and symbolic links cannot leave the
  shared folders. Creating symbolic links is refused.
- Only folders in your home folder or on external drives can be shared, never hidden folders
  (`.ssh`, `.config`, …) or system folders. Sharing the whole home folder needs an extra
  confirmation, and its hidden files and folders stay hidden (keys, passwords, settings). With
  write access, files can be changed only inside its folders (Documents, Pictures, …), never at
  the top level of the home folder (so nobody can add a `.bashrc` or `.profile`).
- Turning sharing off, removing a computer or taking away "Can change files" closes its open
  connections within a few seconds.
- The connected folders are mounted with `noexec`: programs from the other computer cannot be
  started directly from the mount.

## Command line

```
luxdrop share                          # status: on/off, shared folders, computers with access
luxdrop share on | off
luxdrop share add ~/Documents          # share a folder (home folder: asks, or --yes)
luxdrop share remove Documents
luxdrop share forget ID|NAME           # remove a computer with "Always allow"
luxdrop share allow-write ID|NAME      # let it change files / back to read-only:
luxdrop share read-only ID|NAME
luxdrop share serve [--port N] [--bind ADDR] [--no-mdns]   # share in a terminal, asks there

luxdrop connect                        # "Connect to Computer" window
luxdrop connect Bob-PC                 # by name or ID (mDNS) …
luxdrop connect 192.168.1.20           # … or by address (port 47924)
luxdrop connect Bob-PC@192.168.1.20    # address + pinned key of a trusted computer
     [--write] [--no-open] [--port N]
luxdrop connections                    # connected computers and mount points
luxdrop disconnect [NAME | --all]
```

`luxdrop connect TARGET` stays in the foreground until the connection ends (Ctrl+C disconnects).
Exit codes: 0 ok, 1 failure, 3 denied or code not confirmed, 4 key problem.

## How it works

The sharing computer runs the user service `luxdrop-files.service` (`luxdrop share serve
--service`), announced over mDNS as `_luxdrop-files._tcp` on TCP port **47924**. After the TLS
handshake and approval, the connection carries the standard **SFTP** protocol: OpenSSH
`sftp-server` in a sandbox on one side, `sshfs` (FUSE) on the other. The remote folders are
mounted at `$XDG_RUNTIME_DIR/luxdrop-files/<computer name>` (for example
`/run/user/1000/luxdrop-files/Bob-PC`), with a bookmark in `~/.config/gtk-3.0/bookmarks` while
connected. The protocol is described in `/usr/share/doc/luxdrop/PROTOCOL.md` (Part C).

| What | Where |
|---|---|
| Shared folders, on/off | `~/.config/luxdrop/shares.json` |
| Computers with "Always allow" | `~/.local/share/luxdrop/file-access.json` |
| Active connections | `$XDG_RUNTIME_DIR/luxdrop-files/connections.json` |
| Service | `/usr/lib/systemd/user/luxdrop-files.service` |

## Troubleshooting

- **The computer is not in the list**: sharing must be on there, and `avahi-daemon` must run on
  both computers. On guest Wi-Fi (client isolation) type the address instead.
- **"… does not share any folders"**: sharing was turned off, or all shared folders were removed
  or deleted.
- **"… denied access"**: the owner chose Deny. Ask again after 5 minutes.
- **Firewall**: LuxOS has none by default. With firewalld or ufw allow TCP 47924 only on private
  networks (the `luxdrop` firewalld service and the ufw profile include it).
- **The other computer went away**: the connection is detected as dead within about 45 s, then
  the folder disappears from Files. Nothing freezes.
- Connecting needs FUSE (`/dev/fuse`, `fusermount3`); sharing needs user namespaces for
  bubblewrap (enabled in the LuxOS kernel).
