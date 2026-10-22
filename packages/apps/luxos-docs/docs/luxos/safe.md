# Safe – encrypted folder (/safe/<user>)

The **Safe** (Czech: *Trezor*, package `luxos-safe`, command `luxos-safe`) gives every user one
encrypted folder at `/safe/<user>` that is unlocked with its **own password** (separate from the
login password). It is meant for sensitive files such as documents, keys or exports.

## How it works

- Encryption: **gocryptfs** (AES-256-GCM, scrypt key derivation). The encrypted data lives in
  `/safe/.vaults/<user>` (owned by the user, mode `0700`).
- Unlocked: the decrypted contents are mounted with FUSE at `/safe/<user>`, **without `allow_other`**,
  so only the owner can enter the mounted folder – not even root can enter it by ordinary means.
- Locked: `/safe/<user>` is a read-only placeholder (a tiny `tmpfs` with `nr_inodes=2`, mounted by the
  root helper). It contains only an **Unlock Safe** launcher. Nothing can be saved into a locked Safe,
  and the underlying directory on disk is `root:root 0000` and immutable (`chattr +i`), so unencrypted
  data can never land on the disk by accident.
- A bookmark **Safe** is added to the Files (Thunar) sidebar (`~/.config/gtk-3.0/bookmarks`).

Directory layout created by the helper:

| Path | Owner / mode | Content |
|---|---|---|
| `/safe` | root:root `0755` | top directory |
| `/safe/.vaults` | root:root `0711` | encrypted vaults (cannot be listed) |
| `/safe/.vaults/<user>` | user `0700` | gocryptfs encrypted files |
| `/safe/<user>` | root:root `0000` + immutable | mount point (placeholder tmpfs, then gocryptfs) |
| `/safe/.recovered/<user>` | user `0700` | unencrypted files found in an old-style Safe folder |

## Using the Safe

Open **Safe** from Launchpad/Search (`luxos-safe`). The window has three states:

1. **Create your Safe** – enter a new Safe password twice (at least 8 characters). Creating the
   directories asks for authorization once (polkit action `org.luxos.safe.setup`, allowed for the
   active local user). **If you forget the Safe password, the files cannot be recovered.**
2. **The Safe is locked** – enter the password, the folder opens in Files.
3. **The Safe is unlocked** – *Open Safe*, *Lock Now*, auto-lock settings and *Change Password…*.

In Files, double-clicking **Unlock Safe** inside the locked folder runs `luxos-safe unlock --open`.

## Command line

```bash
luxos-safe                 # Safe window
luxos-safe unlock          # password dialog (exit 0 when unlocked)
luxos-safe unlock --open   # unlock, then open the folder
luxos-safe lock            # lock now (fails and names the apps if files are still open)
luxos-safe lock --force    # retry for a moment, notify on failure (used for auto-lock)
luxos-safe lock --logout   # on logout: terminate apps holding files, then lock
luxos-safe status          # prints: locked | unlocked | none
luxos-safe --watch         # session watcher (lock on screen lock and sleep)
```

The password is always passed to gocryptfs on standard input – never in arguments or the environment.
There is no command-line way to type the password non-interactively; unlocking always uses the dialog.

## When it locks automatically

| Event | Behaviour |
|---|---|
| Inactivity | gocryptfs idle timeout (`-i`), default **15 minutes**; options 5 min, 15 min, 1 hour, Never. Only when no file is open. |
| Screen lock | locks when the screen saver/locker activates (setting *Lock when the screen locks*, default on). |
| Sleep / suspend | **always** locks before sleep; a logind *delay* inhibitor holds sleep until it is locked. |
| Logout | **always** locks (`luxos-safe-watch.service`, user unit, `ExecStop=luxos-safe lock --logout`). |

Screen-lock and sleep handling run inside the session daemon `luxos-daemon` (one process for the whole
session); `luxos-session` starts `luxos-safe-watch.service` for the logout case.

Settings are stored in `~/.config/luxos/safe.json`:

```json
{"idle_minutes": 15, "lock_on_screen_lock": true}
```

### Open files block locking

The Safe never uses a lazy unmount while gocryptfs is alive (open files would stay readable).
If an app keeps a file open, a manual lock fails with *"These apps keep files in the Safe open: …"*;
automatic locking retries and then shows a critical notification – the Safe stays unlocked.
On logout the apps holding files get `SIGTERM`; as a last resort the gocryptfs process is killed
(the key disappears with it) and the dead mount is detached.

## Boot-time protection

`luxos-safe-guard.service` (system unit, enabled by the package, runs before the display manager)
executes `luxos-safe-helper guard`: for every user with a Safe it seals the underlying directory and
mounts the read-only placeholder. It also runs after package upgrades.

Older versions left the locked folder writable. If files were saved there, the helper moves them (never
deletes) to `/safe/.recovered/<user>/<time>`; on the next unlock they are moved to
`~/Safe-unencrypted-recovered-<date>` and the user is asked whether to **Import into Safe** (the
unencrypted copies are then deleted) or **Keep in Home Folder**.

## Privileged helper

`/usr/lib/luxos/luxos-safe-helper` (root):

- `pkexec luxos-safe-helper create` – create directories and protection for the calling user
  (`PKEXEC_UID`),
- `pkexec luxos-safe-helper protect` – only protection (upgrade of older installs),
- `luxos-safe-helper guard` – boot/upgrade protection of all Safes (refused through pkexec).

Only regular users (UID ≥ 1000, safe names) are accepted.

## Kernel hardening shipped with the Safe

`/usr/lib/sysctl.d/60-luxos-safe.conf`:

- `kernel.yama.ptrace_scope = 2` – processes of another user cannot be debugged (memory read) without
  `CAP_SYS_PTRACE`,
- `fs.suid_dumpable = 0` – no core dumps of setuid programs (they could contain keys).

## Limits and caveats

- The Safe password is not recoverable; there is no reset path that keeps the data.
- While unlocked, any program running **as the same user** can read the files – the Safe protects data
  at rest and from other users, not from malware in your own session.
- Root cannot enter the mounted FUSE folder by ordinary means, but a malicious root (rootkit) can do more;
  the protection is against casual access and offline disk access.
- One Safe per user; the folder name is fixed (`/safe/<user>`).
- Change the password from the unlocked window (*Change Password…*), it uses `gocryptfs -passwd`.

See also: [Sandbox](sandbox.md), [Configuration](configuration.md).
