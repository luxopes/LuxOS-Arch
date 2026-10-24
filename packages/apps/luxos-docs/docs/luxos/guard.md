# Lux Guard – protection against harmful downloaded programs

**Lux Guard** (package `luxos-guard`, service `luxos-guard.service`, window **Lux Guard** =
`luxos-guard-gui`, command `luxos-guard`) checks programs and scripts that came **from outside the
computer** at the moment they are started, and keeps hourly read-only snapshots of `/home` so that
deleted or encrypted files can be restored. It is not a classic antivirus: no signature database, no
background scanning of all files, no cloud. Normal programs and files cost nothing.

## What it watches

Only executable content from outside:

- files in the Downloads folder (`XDG_DOWNLOAD_DIR` and `~/Downloads`), `~/Sandbox`, mail and web
  attachments opened from `/tmp/mozilla_*`, removable media (`/run/media`, `/media`, `/mnt`),
- files with the `user.xdg.origin.url` attribute (set by browsers and `wget --xattr`),
- files written anywhere in a home folder by a browser, mail, download, torrent or chat app,
- files written by a program that itself came from outside (droppers) or by a program that has a
  file from outside open (unpacking an archive from Downloads, copying from USB),
- copies of a watched file (same size and SHA-256).

Executable content = ELF programs, AppImages, scripts with `#!` or with `.sh/.py/.pl/.rb/.lsl`
extensions, `.desktop` launchers, `.jar` and Windows `.exe` (via Wine). Documents, pictures,
archives and videos are never touched.

## Levels and what happens

| Level | When | What the user sees |
|---|---|---|
| **Risky** | any unknown program or script from outside | dialog "Run a program from outside this computer?" with **Don't Run** (default), **Run in Sandbox**, **Run Anyway** |
| **Critical** | dangerous behaviour found (list below) | the start is **always refused** outside the sandbox; dialog "Lux Guard blocked a dangerous program" with **OK**, **Run in Sandbox**, **Move to Trash**; a notification already when it is downloaded |

**Run Anyway** is remembered for that exact content (SHA-256); the file is then no longer watched
and starts at full speed. **Don't Run** or no answer within 90 s refuses the start (the program
gets "Permission denied"); the same file is not asked about again for 60 s. If no Lux Guard session
helper runs for that user (no graphical session, SSH), risky files are refused without asking –
use `luxos-guard allow FILE`.

Critical findings (reasons shown in the dialog):

- deletes your files, your home folder or the whole system – `rm -rf ~`, `rm -rf /`, `find ~ -delete`,
  `find ~ -name '*.jpg' -delete`, `shutil.rmtree(Path.home())`, walking the home folder and
  deleting/overwriting files, `fs.rmSync(os.homedir(), …)`, `FileUtils.rm_rf(Dir.home)` …
- formats, wipes or overwrites a disk – `dd of=/dev/sda`, `mkfs`, `wipefs -a`, `shred /dev/…`,
  `blkdiscard`, `> /dev/nvme0n1`, writing to `/dev/sd*` from Python
- removes the bootloader, kernels or core system packages; breaks permissions of the whole system
- freezes the computer (fork bomb); crashes the kernel (`/proc/sysrq-trigger`)
- changes sudo, polkit or PAM security settings (writes to `/etc/sudoers`, `/etc/pam.d` …)
- tries to switch off Lux Guard or delete its backups
- downloads code from the internet and runs it immediately without any check – `curl … | sh` **as
  administrator** (`| sudo bash`), from plain `http://`, an IP address, paste or link-shortener
  sites, or combined with decoding; plain `curl https://… | sh` is only a note in the risky dialog
- runs hidden (encoded) code – `base64 -d | sh`, `xxd -r | sh`, `eval "$(… base64 -d)"`,
  `exec(base64.b64decode(…))`, `eval(Buffer.from(…, 'base64'))`; base64 text inside a script is
  also decoded and checked
- encrypts your files (ransomware behaviour) – `openssl enc`/`gpg -c`/`7z -p` in a loop over the home
  folder, Python `Fernet`/AES over `os.walk(home)`

Notes (risky dialog only): asks for administrator rights, adds a program to startup, changes user
accounts, downloads more code, disables package signature checks. Typical install and build
scripts (`rm -rf "$TMPDIR"`, `rm -rf build`, `sudo usermod -aG …`, `rm -rf "$DIR/"*` with an unknown
variable) are **not** critical. For programs (ELF) only readable command strings are checked;
compressed programs and AppImages are usually just risky.

## Why something was blocked – for AI assistants

1. `luxos-guard scan FILE` – type, dangerous findings and notes, origin and Lux Guard state.
2. `luxos-guard list` – watched files and recent decisions; `journalctl -t luxos-guard` – the log
   (`blocked critical PATH (by PROGRAM[PID], uid N): REASON`).
3. Explain the reason in plain words. For a critical file recommend **Run in Sandbox** or deleting
   it. Never suggest switching Lux Guard off, never run `luxos-guard allow --force` and never copy
   the file elsewhere or strip it to get around the check.
4. A false alarm on a trusted risky file: the user clicks **Run Anyway** or runs
   `luxos-guard allow FILE`. A critical file can only be released by an administrator with
   `sudo luxos-guard allow --force FILE` – only when the user explicitly insists and understands it.

## Run in Sandbox

The button starts the file in the user's [Sandbox](sandbox.md): programs (ELF, AppImage, jar, exe) with
`luxos-sandbox run --gui -- FILE`, scripts in a terminal with `luxos-sandbox run -- FILE`. The file
is copied into the sandbox; inside it cannot see the home folder, desktop or local network. If the
sandbox does not exist yet, the Sandbox window opens (click Create, then try again). The sandbox is a
minimal Arch Linux without Python, Java or Wine unless installed with `luxos-sandbox install`.

## Snapshots and restoring files

If `/home` is a btrfs subvolume (standard LuxOS installation: `@home`), `luxos-guard-snapshot.timer`
makes a read-only snapshot every hour in `/home/.luxos-guard-snapshots/YYYY-MM-DD_HH-MM`. Kept: all
from the last 24 hours, then the newest of each day for 7 days; with less than 5 % (or 2 GiB) free
space the oldest are deleted (the newest two stay). Snapshots cost almost no space until files
change. Programs of the user cannot change or delete them (read-only subvolumes, root-owned
folder); each user sees only their own home in them (original permissions).

Restoring – window **Lux Guard › Restore files**: **Show Files** (opens the snapshot in Files),
**Restore Deleted** (copies back missing files, skips `.cache`), **Restore All…** (also replaces
changed files, e.g. encrypted by ransomware; newer files are kept). Command line, as the user:

```bash
luxos-guard snapshots                                   # list times
luxos-guard restore ~/Documents/report.odt              # newest snapshot, only if missing
luxos-guard restore --from "2026-10-23 14:00" ~/Pictures
luxos-guard restore --overwrite --from 2026-10-22 ~     # everything back to that day
luxos-guard restore --dry-run ~/Documents               # only count
```

On ext4/xfs or when `/home` is not a subvolume there are no snapshots (`luxos-guard status` says so).

## How enforcement works

- Kernel **fanotify**: writes (`FAN_CLOSE_WRITE`) on the mounts of `/home`, `/tmp` and
  `/dev/shm` (`/var/tmp` only if it has its own mount) are reported asynchronously (writers are never slowed down); only executable content
  is analysed in a background thread.
- Watched files get a mark on their inode with `FAN_OPEN_EXEC_PERM` (every `execve`, however the
  program is started) and, for scripts, `FAN_OPEN_PERM` – `bash file.sh`, `python3 file.py`,
  `. file.sh` are checked too; editors, `cat`, `cp` or file managers only reading the file are
  allowed immediately. Removable media get the mark on the whole mount (files are analysed when
  started). Marks are restored from `/var/lib/luxos-guard/state.json` after a reboot.
- Critical files also lose their execute bits.
- The service runs as root (`systemctl status luxos-guard`); the session helper
  `luxos-guard-agent` (autostart) shows the dialogs. Kernel option needed:
  `CONFIG_FANOTIFY_ACCESS_PERMISSIONS=y` (set in `linux-luxos` and Arch kernels).

## Limits

- Malware started **as root** can stop the service; already allowed programs (Run Anyway) run with
  the user's full rights – they can delete what the user can delete (snapshots stay).
- Code that never touches a watched file: commands pasted into a terminal, `cat file | sh`,
  `curl … | sh` typed by hand, browser exploits, Flatpak/sandboxed apps writing through their own
  mounts, files on network shares (gvfs, SMB), interpreters not in the list (e.g. `awk -f` is,
  `Rscript` is, `make -f` is not).
- Content analysis is pattern based: well-hidden or compiled malware is only **risky** (the user
  still gets the dialog). A file run in the first milliseconds after download may start before the
  check (normally the mark is set before a user could click).
- `.desktop` launchers: a critical one cannot even be read (Files cannot start it); a risky one is
  not asked about – what it starts is checked only if that file is watched.

Related: [sandbox.md](sandbox.md), [for-ai-assistants.md](for-ai-assistants.md),
[troubleshooting.md](troubleshooting.md).

## Live system

In the live system started from the USB stick (`/run/archiso` exists) Lux Guard does not run: the
installer itself runs disk tools (`mkfs`, `cryptsetup`, `dd`) and nothing in the live session is kept.
The installed system has Lux Guard from the first start.
