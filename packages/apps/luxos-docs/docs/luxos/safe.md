# Safe – encrypted folder (/safe/<user>)

The **Safe** (Czech: *Trezor*, package `luxos-safe`, command `luxos-safe`) gives every user one
encrypted folder at `/safe/<user>` that is unlocked with its **own password** (separate from the
login password). It is meant for sensitive files such as documents, exports and **signing keys**
(GnuPG, Android keystores – see [Signing keys in the Safe](#signing-keys-in-the-safe)).

## How it works

- Encryption: **gocryptfs** (AES-256-GCM for contents, encrypted file names, scrypt key derivation).
  The encrypted data lives in `/safe/.vaults/<user>` (owned by the user, mode `0700`).
- Password → key: **scrypt with N = 2^18** (256 MiB of memory) for new Safes and every password
  change. Measured on a Ryzen 5 5500U: unlocking takes 0.18 s with gocryptfs' default 2^16,
  0.35 s with 2^17 and **0.69 s with 2^18**; every password guess costs an attacker the same.
- Unlocked: the decrypted contents are mounted with FUSE at `/safe/<user>`, **without `allow_other`**
  (only the owner can enter, not even root by ordinary means) and with **`nosuid,nodev,noexec`**
  (programs stored in the Safe cannot be run from it). gocryptfs runs with core dumps disabled.
- Locked: `/safe/<user>` is a read-only placeholder (a tiny `tmpfs` with `nr_inodes=2`, mounted by the
  root helper) containing only an **Unlock Safe** launcher. Nothing can be saved into a locked Safe,
  and the underlying directory on disk is `root:root 0000` and immutable (`chattr +i`).
- A bookmark **Safe** is added to the Files (Thunar) sidebar (`~/.config/gtk-3.0/bookmarks`).

| Path | Owner / mode | Content |
|---|---|---|
| `/safe` | root:root `0755` | top directory |
| `/safe/.vaults` | root:root `0711` | encrypted vaults (cannot be listed) |
| `/safe/.vaults/<user>` | user `0700` | gocryptfs encrypted files + `gocryptfs.conf` (wrapped key) |
| `/safe/<user>` | root:root `0000` + immutable | mount point (placeholder tmpfs, then gocryptfs) |
| `/safe/.recovered/<user>` | user `0700` | unencrypted files found in an old-style Safe folder |

## Threat model

**The Safe protects** the files against:

- **a stolen or offline disk** (also a disk image or a laptop taken while the Safe is locked) – only
  ciphertext and the scrypt-wrapped key are on the disk. With a good password (12+ characters, not
  common) guessing is impractical; scrypt 2^18 makes every guess cost ~0.7 s of CPU and 256 MiB.
- **other local users** – the vault is `0700`, the mounted folder has no `allow_other`, and
  `kernel.yama.ptrace_scope = 2` stops them from reading the gocryptfs process memory.
- **other programs of your own account while the Safe is locked** – they see only ciphertext.
- **backups** – backups contain only the encrypted vault; a stolen backup disk is like a stolen disk.
- **accidental leaks to the disk** – nothing can be saved into a locked Safe, no core dumps of
  gocryptfs, LuxOS swap is zram (RAM only); `luxos-safe check` warns about an unencrypted swap.

**The Safe does not protect against:**

- **malware or any program running as your user while the Safe is unlocked** – it can read every
  file in the Safe, exactly like you can. Unlock the Safe only for the moment you need a key, and lock it
  again (*Lock Now*, or auto-lock after 5 minutes).
- **malware in your session capturing the Safe password** when you type it (on X11 any program of the
  session can read the keyboard, or it can put a fake `luxos-safe` earlier in your `PATH`). After that
  it can unlock the Safe whenever it gets the encrypted files.
- **root / the administrator account, a malicious kernel module or firmware** – root can replace
  programs, read memory with `CAP_SYS_PTRACE` or wait for you to unlock.
- **a forgotten password without the recovery key** – the data are lost; nobody can reset it.
- **someone with your recovery key** – it opens the Safe without the password.

In short: the Safe is a strong lock for data at rest and against other users, not a sandbox for a
compromised session. For signing keys, combine it with a passphrase on the key itself (GnuPG) or the
keystore password (Android), so a stolen copy of an unlocked file is still not enough.

## Using the Safe

Open **Safe** from Launchpad/Search (`luxos-safe`). The window has three states:

1. **Create your Safe** – enter a new Safe password twice. Creating the directories asks for
   authorization once (polkit action `org.luxos.safe.setup`, allowed for the active local user).
   Right after creating, the **recovery key** is shown (see below).
2. **The Safe is locked** – enter the password, the folder opens in Files. *Forgot Password…* sets a
   new password with the recovery key.
3. **The Safe is unlocked** – *Open Safe*, *Lock Now*, auto-lock settings, *Change Password…*,
   *Recovery Key…* and, for older Safes, *Upgrade Protection…*.

In Files, double-clicking **Unlock Safe** inside the locked folder runs `luxos-safe unlock --open`.

### Password rules

New passwords (create, change, reset) must have **at least 12 characters**, must not be mostly a
sequence or repetition (`123456789012`, `aaaa…`, `qwertzuiop…`) and must not be just a common word or
your user name with digits or symbols around it (a small built-in list: `password`, `heslo`, `qwerty`,
`trezor`, … also written as `p@ssw0rd`). A strength meter (Weak / Fair / Good / Strong) shows an
estimate as you type; several unrelated words are a good choice. Existing passwords keep working.

**No lockouts:** wrong passwords are never counted or blocked. Guessing speed is limited by scrypt
(each try ~0.7 s and 256 MiB) – an attacker with the encrypted files is not slowed by attempt counters
anyway, so they would add only the risk of locking yourself out.

### Recovery key

The recovery key is the gocryptfs **master key** (64 hexadecimal characters in 8 groups). It is shown
once after creating the Safe and any time later via *Recovery Key…* (requires the password; it is read
with `gocryptfs-xray -dumpmasterkey` and never stored). Write it **on paper** and keep it away from the
computer. It cannot be selected or copied (clipboard managers keep history) and is not printed (print
jobs are spooled to the disk). Anyone with the key can open the Safe without the password.

*Forgot Password…* (locked Safe): enter the recovery key and a new password. The key is first verified
by mounting the encrypted data read-only into a private temporary folder (a wrong key cannot decrypt
names or contents), then `gocryptfs -passwd -masterkey=stdin` wraps the key with the new password and
the backup of the old wrapping (`gocryptfs.conf.bak`) is deleted.

If `gocryptfs.conf` itself is lost (or damaged), the recovery key still opens the data:
`gocryptfs -ro -masterkey=stdin /safe/.vaults/$USER /some/empty/folder` (type the key), copy the files out,
create a new Safe. Backups also contain `gocryptfs.conf` (see [Backups](#backups)).

### Upgrade protection (existing Safes)

Safes created before LuxOS 1.0 use scrypt 2^16. The unlocked window then shows **Upgrade Protection…**:
enter the password, the key is re-wrapped with scrypt 2^18 (`gocryptfs -passwd -scryptn 18`, same
password; file contents are not re-encrypted, it takes about a second). *Change Password…* also always
upgrades. A Safe with a higher value set by hand is never downgraded. Old backups still contain the old
`gocryptfs.conf` – they open with the password that was valid at that time.

## Signing keys in the Safe

Keep private keys only inside the unlocked Safe and point tools to them; the Safe locks on sleep,
logout and screen lock, and before locking `luxos-safe` stops the `gpg-agent` of every GnuPG folder
in the Safe (it would otherwise keep unlocked keys in memory).

**GnuPG** – use a GnuPG home inside the Safe:

```bash
luxos-safe unlock
export GNUPGHOME=/safe/$USER/gnupg        # for this shell only
gpg -K                                    # your secret keys
gpgconf --kill gpg-agent                  # forget cached passphrases when done
```

**LuxOS repository signing key** – `./build.sh` uses, in this order: `LUXOS_SIGNING_DIR`
(`none` = unsigned build), **`/safe/$USER/luxos-signing`**, then the old `~/.local/share/luxos/signing`.
If you have a Safe, it is locked and no old key exists, the build stops with *"Unlock the Safe first
(luxos-safe unlock)"*. The key folder is copied for the build into a private folder in
`$XDG_RUNTIME_DIR` (RAM) and GnuPG in the build container works on a tmpfs copy, so the plain key
never lands on the disk; `scripts/publish-repo.sh` refuses unsigned packages.

**Android release keystore** – keep `release.jks` and its passwords in the Safe, e.g.
`/safe/$USER/android/release.jks` and `/safe/$USER/android/keystore.properties`, and load them in
`app/build.gradle.kts` only when present:

```kotlin
val ks = file("/safe/${System.getProperty("user.name")}/android/keystore.properties")
if (ks.exists()) android.signingConfigs.create("release") {
    val p = java.util.Properties().apply { ks.inputStream().use { load(it) } }
    storeFile = file(p.getProperty("storeFile")); storePassword = p.getProperty("storePassword")
    keyAlias = p.getProperty("keyAlias"); keyPassword = p.getProperty("keyPassword")
}
```

After a release build run `./gradlew --stop` (the Gradle process keeps the passwords in memory) and
lock the Safe. Or sign by hand: `apksigner sign --ks /safe/$USER/android/release.jks app.apk`.

### Moving existing keys into the Safe

1. Create the Safe (or use *Upgrade Protection…*), **write down the recovery key**, unlock it.
2. Copy the keys in, keeping permissions:
   `cp -a ~/.local/share/luxos/signing /safe/$USER/luxos-signing`,
   `mkdir -m700 /safe/$USER/android && cp -a PATH/release.jks /safe/$USER/android/`.
3. Check they work: `gpg --homedir /safe/$USER/luxos-signing -K`, a test build, `keytool -list -keystore …`.
4. Delete the old plain copies (`rm -rf ~/.local/share/luxos/signing`, the keystore in Downloads…).
   On btrfs and SSDs overwriting (`shred`) does not reliably erase old blocks – LuxOS' full-disk
   encryption (LUKS) is what protects them. **Lux Guard snapshots** of `/home` keep the old copy for
   up to 7 days and **older backups** keep it until they are deleted – remove those if the key must go.
5. Run `luxos-safe check` and lock the Safe.

## Command line

```bash
luxos-safe                 # Safe window
luxos-safe unlock          # password dialog (exit 0 when unlocked)
luxos-safe unlock --open   # unlock, then open the folder
luxos-safe lock            # lock now (fails and names the apps if files are still open)
luxos-safe lock --force    # retry for a moment, notify on failure (used for auto-lock)
luxos-safe lock --logout   # on logout: terminate apps holding files, then lock
luxos-safe status          # prints: locked | unlocked | none
luxos-safe check           # protection report, exit 1 if something should be fixed
luxos-safe --watch         # session watcher (lock on screen lock and sleep)
```

`luxos-safe check` reports: scrypt strength of the vault, mount options and core-dump limit of the
running gocryptfs (when unlocked), `kernel.yama.ptrace_scope` and every swap device (encrypted,
zram or **unencrypted**). The password is always passed to gocryptfs on standard input – never in
arguments or the environment; unlocking always uses the dialog.

## When it locks automatically

| Event | Behaviour |
|---|---|
| Inactivity | gocryptfs idle timeout (`-i`), default **15 minutes**; options 5 min, 15 min, 1 hour, Never. Only when no file is open. |
| Screen lock | locks when the screen saver/locker activates (setting *Lock when the screen locks*, default on). |
| Sleep / suspend | **always** locks before sleep; a logind *delay* inhibitor holds sleep until it is locked. |
| Logout | **always** locks (`luxos-safe-watch.service`, user unit, `ExecStop=luxos-safe lock --logout`). |

Screen-lock and sleep handling run inside the session process `luxos-hub`; `luxos-session` starts
`luxos-safe-watch.service` for the logout case. Settings: `~/.config/luxos/safe.json`
(`{"idle_minutes": 15, "lock_on_screen_lock": true}`).

The Safe never uses a lazy unmount while gocryptfs is alive (open files would stay readable). If an app
keeps a file open, a manual lock fails with *"These apps keep files in the Safe open: …"*; automatic
locking retries and then shows a critical notification – the Safe stays unlocked. On logout the apps
holding files get `SIGTERM`; as a last resort gocryptfs is killed (the key disappears with it).

## Backups

[Backups](backups.md) (`luxos-backup`) copy the **encrypted** vault `/safe/.vaults/<user>` into every
backup as `safe/vault` (incremental like the rest), including `gocryptfs.conf`. The unlocked
`/safe/<user>` is never copied – it is outside the home folder and the copy never crosses mount points.
To restore: lock the Safe and copy the folder back while the Safe is locked, e.g.
`rsync -a BACKUP/…/safe/vault/ /safe/.vaults/$USER/` (on a new system create a Safe first so that
the directories exist, then replace its contents). Unlock with the password valid at backup time.

## Boot-time protection and helper

`luxos-safe-guard.service` (system unit, before the display manager) runs `luxos-safe-helper guard`:
for every user with a Safe it seals the underlying directory and mounts the read-only placeholder; it
also runs after package upgrades. Files saved into an old-style writable Safe folder are moved (never
deleted) to `/safe/.recovered/<user>/<time>` and offered for import on the next unlock.

`/usr/lib/luxos/luxos-safe-helper` (root): `pkexec … create` (directories and protection for the
calling user), `pkexec … protect` (only protection), `guard` (boot, refused through pkexec). Only
regular users (UID ≥ 1000) are accepted. `/usr/lib/sysctl.d/60-luxos-safe.conf` sets
`kernel.yama.ptrace_scope = 2` (no process may read another process' memory without
`CAP_SYS_PTRACE` – also processes of the same user) and `fs.suid_dumpable = 0`.

## Limits and caveats

- One Safe per user; the folder name is fixed (`/safe/<user>`).
- **Security keys (FIDO2) are not offered.** gocryptfs' `-fido2` replaces the password with the
  security key (it is not a second factor), cannot change the password or be upgraded later, needs
  `libfido2` tools and a key present at every unlock; losing the key would leave only the recovery key.
  This may come later as an opt-in for new Safes.
- No per-app access control inside the session: a Lux Guard warning when an unknown program opens files
  in the unlocked Safe is a possible future addition (root cannot watch a FUSE mount without
  `allow_other`, so it would need a user-level watcher).
- An unencrypted swap partition (custom installer layouts only) could store memory pages with keys;
  `luxos-safe check` reports it. Hibernation to such a swap has the same risk.
- Change the password from the unlocked window (*Change Password…*, `gocryptfs -passwd`).

See also: [Sandbox](sandbox.md), [Backups](backups.md), [Lux Guard](guard.md), [Configuration](configuration.md).
