# Sandbox – isolated system for untrusted apps (/dev/sandbox/<user>)

**LuxOS Sandbox** (package `luxos-sandbox`, command `luxos-sandbox`, window **Sandbox** =
`luxos-sandbox-gui`) runs and installs applications you do not trust, separated from your files,
your desktop session, other users and the local network.

## What /dev/sandbox/<user> is

Each user has **one** sandbox: a minimal **Arch Linux** root file system.

- The data lives permanently in `/var/lib/luxos/sandbox/<user>` (owned by the user, mode `0700`).
- `/dev/sandbox/<user>` is only a **symlink** to it. `/dev` is a devtmpfs (empty after every boot),
  so the link is recreated at boot by systemd-tmpfiles from
  `/etc/tmpfiles.d/luxos-sandbox-<user>.conf` (written by the helper):
  `L+ /dev/sandbox/<user> - - - - /var/lib/luxos/sandbox/<user>`.
- The base package `/usr/lib/tmpfiles.d/luxos-sandbox.conf` creates `/var/lib/luxos`,
  `/var/lib/luxos/sandbox` (root `0755`) and `/dev/sandbox`.

It is **not** a VM and not a chroot you enter as root: programs are started inside it with
**bubblewrap** (`bwrap`, no setuid) as your normal user.

## How it is built

`luxos-sandbox create` calls `pkexec /usr/lib/luxos/sandbox/luxos-sandbox-helper create`
(polkit action `org.luxos.sandbox.create`, `auth_admin_keep` – asks for the administrator password).
The helper:

1. runs `pacstrap -c -K` with `/usr/share/luxos/sandbox/pacman.conf` – **only official Arch Linux
   repositories** `[core]` and `[extra]`, no LuxOS repos, no AUR; man pages/docs/most locales are not
   extracted,
2. installs a small base: `filesystem bash coreutils pacman archlinux-keyring ca-certificates sed grep
   gawk findutils tar gzip xz zstd less nano which procps-ng curl file diffutils glibc`,
3. removes setuid/setgid bits and file capabilities, adds user `sandbox` (your UID) with home
   `/home/sandbox` (with `Downloads` and `Shared`), hostname `sandbox`,
4. builds in a hidden `.build-<user>` directory, `chown`s to you and atomically renames it into place,
5. writes the tmpfiles entry for the `/dev/sandbox/<user>` link.

The helper accepts only `create|reset|destroy` for the calling user (`PKEXEC_UID`, UID ≥ `UID_MIN`,
< 60000). Everything else runs **without root**.

## Command line

```bash
luxos-sandbox create                     # create your sandbox (admin password once, takes minutes)
luxos-sandbox status [--json]            # path, link, size, installed apps
luxos-sandbox install firefox            # install apps from Arch repos into the sandbox
luxos-sandbox remove-app firefox         # remove apps from the sandbox
luxos-sandbox run --gui --net firefox    # run a GUI app with internet
luxos-sandbox run ./downloaded-program   # a host file is COPIED in first, then run
luxos-sandbox shell [--net] [--shared]   # interactive bash inside ([sandbox] prompt)
luxos-sandbox reset [--yes]              # wipe everything inside and create it again
luxos-sandbox destroy [--yes]            # delete the sandbox (~/Sandbox stays)
```

Options for `run` (before the command): `--net`, `--gui`, `--shared`.

| Option | Effect |
|---|---|
| (none) | no network (own loopback only), no window, no shared folder |
| `--net` | internet only: NAT through `pasta`; local network and this computer are blocked |
| `--gui` | the app gets its own nested X server (**Xephyr**) window "Sandbox - <app>", 1280×800, resizable – never your desktop |
| `--shared` | `~/Sandbox` on the host appears as `/home/sandbox/Shared` |

`luxos-sandbox` refuses to run as root ("Run luxos-sandbox as a normal user, not root").

### Installing apps

`install` runs `pacman -Syu --needed --noconfirm` **inside** the sandbox as a fake root (network is
enabled only for this step) and deletes downloaded packages afterwards. Package names must match
`^[a-z0-9@_+][a-z0-9@._+-]*$`. Only Arch `[core]`/`[extra]` packages are available. Use
`luxos-sandbox`, not `lux`, for sandbox apps – `lux` manages the host system.

### Running a downloaded file

If the first argument is a host file (relative path with `/`, `~/…`, or a path under your home, `/tmp`,
`/media`, `/run/media`, `/mnt`), it is copied into `/home/sandbox/Downloads/<name>` via stdin by a
process inside the sandbox and made executable; the original location is never mounted.

### The Sandbox window

The GUI shows status (Ready / Not created), **Create Sandbox**, **Installed apps** (Run / Remove),
**Install app** (package name), **Run app** (command or *Choose File…*), switches **Network**
(default off), **Window** (default on = `--gui`), **Shared folder** (default off), **Open Terminal**
(needs `xfce4-terminal`), **Open** shared folder, **Reset…**, and a *Details* log.

## What is isolated

- **Files:** `/` inside is a fresh read-only tmpfs; persistent are only the sandbox's own `/usr /etc
  /var /opt /srv /root /mnt` and `/home/sandbox`. Your home, `/run/user`, `/media`, `/sys`, host files
  and other users are not visible. `/tmp` and `/run` are private tmpfs.
- **Symlink attacks:** the host side never opens sandbox paths by name; directories are opened
  component by component with `O_NOFOLLOW` and passed to bwrap as file descriptors (`--bind-fd`).
- **Processes:** own PID namespace; `ptrace`, `process_vm_readv/writev`, `pidfd_getfd`, `kcmp` blocked.
- **Privileges:** `--cap-drop ALL`, `no_new_privs`, setuid does not work, single UID.
- **Namespaces:** user/pid/ipc/uts/cgroup/net/mount (`bwrap --unshare-all`), `--die-with-parent`,
  `--clearenv`.
- **Seccomp** (x86_64 only, i386/x32 rejected): blocks `mount` and the new mount API, `pivot_root`,
  `chroot` (except during install), `setns`, nested user namespaces (`clone3` returns `ENOSYS`), key
  management, `bpf`, `perf_event_open`, `userfaultfd`, `io_uring_*`, `kexec_*`, kernel modules,
  `open_by_handle_at`, `fanotify_init`, `syslog`, clock changes, `swapon`, `reboot`, `iopl/ioperm/modify_ldt`,
  `ioctl(TIOCSTI/TIOCLINUX)`, unusual socket families (`AF_PACKET`, `AF_VSOCK`, Bluetooth…).
- **Network:** without `--net` only loopback (no host abstract sockets such as the X11 socket). With
  `--net`: `pasta --no-map-gw -t none -u none -T none -U none`; inside, all private ranges
  (RFC 1918, CGNAT 100.64/10, link-local, ULA, multicast) and all host addresses are `prohibit` routes.
  DNS goes to `169.254.1.53`, forwarded to the host resolver.
- **Session:** no D-Bus (session or system), **no sound** (PulseAudio/PipeWire), no Wayland, no host
  X11, no SSH agent, no keyring.
- **Clipboard:** not shared (Xephyr has its own).
- **Resources:** `systemd-run --user --scope` with `MemoryMax=50%`, `MemorySwapMax=1G`,
  `TasksMax=512`, `CPUQuota` = 75 % of all cores (without a user systemd only a warning).

Environment inside: `HOME=/home/sandbox`, `USER=sandbox`, `LUXOS_SANDBOX=1`, `LANG=C.UTF-8`.

## What is NOT isolated (threat model)

- **Kernel bugs:** the sandbox shares the kernel; a kernel exploit can escape. For really dangerous
  software use a virtual machine.
- Unprivileged user namespaces must be enabled in the kernel (bwrap without setuid).
- **Xephyr** runs as your user on the desktop; a Xephyr bug could give code execution outside. Apps in the
  same Xephyr window can see each other (keylogging between them is possible). No window manager inside,
  so windows have no decorations.
- **Terminal:** `shell`/`run` in a terminal share the terminal (for Ctrl+C/job control); `TIOCSTI` is
  blocked, but escape sequences can still reach the terminal emulator.
- **Shared folder:** anything written to `~/Sandbox` is untrusted (malicious documents, symlinks).
- **With `--net`:** the app can do anything on the internet from your IP address. Networks that appear
  on the host after start are not blocked by host-address rules (private ranges always are).
- **Installs:** pacman runs as a fake root with one UID; `chown*()` pretends to succeed, so system services
  needing separate system users or setuid will not work; some hooks print errors. Signature checks
  use the sandbox's own keyring, which the sandbox itself can change.
- **Disk:** no quota – the sandbox can fill `/var`.
- Timing/side channels (Spectre etc.) are not addressed.

The full threat model is installed as `/usr/share/doc/luxos-sandbox/SECURITY.md`. The repository has an
automated isolation test (`packages/luxos-sandbox/tests/isolation-test.sh`).

## Reset and removal

- `luxos-sandbox reset --yes` (or **Reset…** in the window) – deletes everything inside and runs
  pacstrap again. Use it when the sandbox is damaged (e.g. error *"The sandbox is damaged … Run:
  luxos-sandbox reset"*).
- `luxos-sandbox destroy --yes` – deletes `/var/lib/luxos/sandbox/<user>`, the tmpfiles entry and the
  `/dev/sandbox/<user>` link. `~/Sandbox` on the host is kept.

See also: [Safe](safe.md), [Configuration](configuration.md).
