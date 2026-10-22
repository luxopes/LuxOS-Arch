# Package management with lux

`lux` is the LuxOS package manager and the only supported way to install, update and remove
software from the command line. It manages packages from the LuxOS and Arch Linux repositories
directly through **libalpm** (the pacman library, used from Python via `pyalpm`), and also handles
the AUR, Flatpak (Flathub) and the LuxOS `.lux` app format.

There is **no `pacman` command** in LuxOS. See [lux-engine-and-repos.md](lux-engine-and-repos.md)
for the engine behind lux, the repositories and what happens when someone types `pacman`.

- Program: `/usr/bin/lux` (bash), version shown by `lux --version` (lux 0.3.0 at the time of writing).
- Transaction backend: `/usr/lib/lux/lux_alpm.py`.
- `.lux` support: `/usr/lib/lux/luxpkg.sh` (see [lux-packages.md](lux-packages.md)).
- Reference docs installed with the package: `/usr/share/doc/lux/lux.md`,
  `/usr/share/doc/lux/lux-package-format.md`.
- Bash completion: `/usr/share/bash-completion/completions/lux`.

## Commands

| Command (aliases) | What it does | pacman equivalent |
|---|---|---|
| `lux` (no arguments) | interactive store in the terminal (TUI, needs `fzf` and `expac`) | |
| `lux install <pkg...>` (`i`, `add`) | install from repositories → LuxOS `.lux` → AUR → Flathub; also a local `.lux` or `.pkg.tar.*` file; already installed packages are skipped | `-S --needed`, `-U` |
| `lux remove <pkg...>` (`rm`, `uninstall`) | remove packages with their no longer needed dependencies and config backups | `-Rns` |
| `lux update` (`upgrade`, `up`) | refresh databases, update signing keys first, then the whole system; then AUR, `.lux` apps and Flatpak | `-Sy` + `-Su` |
| `lux search <term>` (`s`, `find`) | search repositories, the LuxOS `.lux` repo and the AUR (top 20 by popularity) | `-Ss` |
| `lux info <pkg>` (`show`) | details: installed package, else from a repository, then `.lux`, then AUR | `-Qi` / `-Si` |
| `lux list` / `lux list --installed` (`ls`) | installed packages (including `.lux`) | `-Q` |
| `lux list --upgradable` (`--updates`) | available updates according to the last database refresh (plus `.lux` updates) | `-Qu` |
| `lux list --explicit` | explicitly installed packages | `-Qe` |
| `lux list --aur` (`--foreign`) | packages not from any repository (AUR, manual builds) | `-Qm` |
| `lux list --orphans` | dependencies nothing needs any more | `-Qdt` |
| `lux list --lux` | installed `.lux` apps | |
| `lux list <pattern>` | installed packages matching a pattern | |
| `lux reinstall <pkg...>` | install the same version again (from repository, else from cache) | `-S` / `-U` |
| `lux autoremove` | remove orphaned dependencies | `-Rns $(pacman -Qdtq)` |
| `lux files <pkg>` | files installed by a package | `-Ql` |
| `lux owns <file>` (`owner`) | which package owns a file (also a command name from `PATH`) | `-Qo` |
| `lux clean` | clean the package cache (keeps `CLEAN_KEEP` versions, removes cached versions of uninstalled packages), offers `autoremove`, deletes AUR build packages older than 30 days | `paccache -rk2`, `paccache -ruk0` |
| `lux fix` | repair a locked database and the signing keys (see below) | |
| `lux configs` | review and merge new config files from updates (`.pacnew`, `.pacsave`) using `pacdiff` | `pacdiff` |
| `lux history [n] [pkg]` | recent package changes from `pacman.log` (default 25 lines) | |
| `lux drivers` | detect hardware and install missing drivers (see [drivers.md](drivers.md)) | |
| `lux mirrors` | pick the fastest download mirrors with `reflector` | |
| `lux doctor` | system health check | |
| `lux pack <dir> [out]` | build a `.lux` package from a directory with `lux.json` | |

### Options

| Option | Meaning |
|---|---|
| `-y`, `--yes` | do not ask for confirmation (otherwise lux always asks) |
| `-v`, `--verbose` | show package lists, script output and raw libalpm errors |
| `--repo` | only official repositories (no AUR, no `.lux` updates, no Flatpak) |
| `--aur` | only AUR |
| `-h`, `--help` | help |
| `-V`, `--version` | version |

Examples:

```bash
lux install firefox              # from the repositories
lux install ./myapp-1.0-1-any.lux
lux install org.gimp.GIMP        # Flatpak app ID (only if flatpak is installed)
lux remove gimp
lux update                       # full system update
lux -y update                    # without questions
lux search video editor
lux info lsl
lux owns /usr/bin/fastfetch
lux history 50 linux-zen
```

## Install resolution order

`lux install NAME` decides per target:

1. A `.lux` file path → installed as a `.lux` package (signature checked).
2. A `.pkg.tar.*` file path → installed through libalpm like `pacman -U`.
3. Found in the configured repositories (name, `repo/name`, group or a `provides`) → libalpm.
4. Found in the signed LuxOS `.lux` index → downloaded, checksum and signature verified, installed.
5. Found in the AUR (and `AUR=1`) → built from the AUR (see below).
6. Name looks like a Flatpak app ID (contains at least two dots, e.g. `org.gimp.GIMP`) and `flatpak`
   is installed → `flatpak install -y flathub <id>`.
7. Otherwise: `Package 'X' not found. Try: lux search X`.

Installing directly from a URL is not supported; download the file first.

## Output and confirmation

```
Install 3 packages (73 MB download, +259 MB disk)? [Y/n]
✓ Downloading ████████████████████ 100%  73 MB / 73 MB · 9.1 MB/s
✓ Verifying   ████████████████████ 100%
✓ Installing  ████████████████████ 100%  3/3 firefox
✓ Installed firefox 131.0-1 (+2 deps) in 8.2 s
```

- One line per phase (refresh, download, verify, install/remove, hooks); errors as one plain
  sentence (details with `--verbose`).
- Colors and progress bars only on a terminal and without `NO_COLOR`; redirected output is plain
  text (`name version` like `pacman -Q`).
- Network failures are retried up to 3 times without asking again.
- Ctrl+C during installation finishes the package being installed and then stops safely.
- Removing a package listed in `HoldPkg` (pacman.conf) triggers a warning that it is essential.
- With Data Saver on, lux still downloads (the user started it) but reminds about the download size.
- Messages are English with translations from `luxos-i18n`.

## Administrator rights

Run lux as a normal user. It asks for root by itself:

- in a terminal: `sudo`,
- in a graphical session without a terminal: `pkexec` (graphical password dialog),
- when running as root already: directly.

Through sudo/pkexec lux passes a fixed `PATH=/usr/lib/lux/alpm/bin:/usr/local/sbin:/usr/local/bin:/usr/bin`,
`LANG`, color settings and `LUX_BACKEND`. AUR packages must be built as a regular user — never run
`sudo lux install <aur-package>`.

## Configuration: /etc/lux/lux.conf

System file `/etc/lux/lux.conf` (pacman `backup` file), per-user override
`~/.config/lux/lux.conf` (`$XDG_CONFIG_HOME/lux/lux.conf`). Both are bash `KEY=value` files.

| Key | Default | Meaning |
|---|---|---|
| `AUR` | `1` | enable AUR (community packages) |
| `REVIEW_PKGBUILD` | `1` | offer to review the PKGBUILD before building from AUR |
| `FLATPAK` | `1` | `lux update` also updates Flatpak apps (if flatpak is installed) |
| `CLEAN_KEEP` | `2` | how many versions of each package `lux clean` keeps in the cache |

Environment variables: `LUX_BACKEND=pacman` (force the internal pacman fallback), `NO_COLOR`,
`LUX_LOCK_WAIT` (seconds to wait for another package manager, default 300),
`LUX_INDEX_URL` (`.lux` repository URL).

## AUR

- Needs `jq`, `git` and `base-devel`; if missing, lux offers to install `base-devel` and `git`.
- Must run as a regular user (`AUR packages must be built as a regular user (run lux without sudo)`).
- Dependencies are resolved recursively through the AUR RPC (`https://aur.archlinux.org/rpc/v5`);
  repository dependencies are installed normally, AUR dependencies are built first (as dependencies).
- lux prints `AUR packages to build: …` and warns that AUR packages are maintained by the community,
  not by LuxOS, then asks `Continue?`.
- With `REVIEW_PKGBUILD=1` and without `-y` it asks `Review PKGBUILD of X before building?`
  (opens `bat` or `less`) and `Build and install X?`.
- Sources are cloned to `~/.cache/lux/aur/<pkgbase>` and built with `makepkg -si`.
- `lux update` checks installed foreign packages (`-Qm`) against the AUR and rebuilds newer ones
  (only when not running as root and not with `--repo`).

## Flatpak

Flatpak is optional (`flatpak` is an optional dependency of lux). `lux install <app.id>` installs
from Flathub, and `lux update` runs `flatpak update -y --noninteractive` when `FLATPAK=1`.

## lux update in detail

1. Waits for another running package manager (LuxOS Care, LuxOS Store, …) up to 5 minutes; a stale
   lock with no package manager running is removed automatically
   (`Removed a stale database lock left by an interrupted update.`).
2. Refreshes the databases.
3. Updates `archlinux-keyring` / `luxos-keyring` first if newer ones exist.
4. Full system upgrade (no partial upgrades).
5. AUR packages, `.lux` apps (`Updating LuxOS apps`), Flatpak apps.
6. Lists new `*.pacnew` files (`New config files to review:`) and warns
   `Kernel was updated - restart to use it.` when the running kernel's modules are gone.

Automatic background updates are done by LuxOS Care, not by lux — see [care-updates.md](care-updates.md).

## lux fix: locked database and signing keys

`lux fix` (runs as root via sudo/pkexec) does:

1. Checks `/var/lib/pacman/db.lck` (path from `pacman-conf DBPath`).
   - If a package manager is running (`pacman`, `lux_alpm.py`, `makepkg`, `pacstrap`, `yay`, `paru`,
     `pamac`, `pamac-daemon`, `packagekitd`): `Another package manager is running (…) - wait until it finishes.`
   - Otherwise asks `The package database is locked, but no package manager is running. Remove the stale lock?`
2. When nothing is running, deletes unfinished downloads (`*.part`, `download-*` dirs) in the cache.
3. Initializes the keyring if empty (`pacman-key --init`) and runs `pacman-key --populate`.
4. Warns if the clock is not NTP synchronized (`timedatectl set-ntp true`) — wrong time breaks signatures.
5. Reinstalls `archlinux-keyring` and `luxos-keyring` with a database refresh.

Recovering a locked database: never delete `db.lck` by hand while an update is running. Run
`lux fix`; if it says another package manager is running, wait (LuxOS Care may be installing
updates — see the Software Update app). LuxOS Care also removes a lock older than 10 minutes when
nothing is running.

## lux doctor

Checks and prints:

- failed systemd services (`systemctl --failed`),
- pending `.pacnew` files (suggests `lux configs`),
- root filesystem usage (warning above 90 %),
- orphaned packages (suggests `lux clean`),
- available updates via `checkupdates` (suggests `lux update`),
- whether `lux-engine` is older than pacman in Arch Linux (a LuxOS update will follow),
- whether the running kernel was replaced (restart needed),
- number of error messages in this boot's journal (`journalctl -b -p err`).

Exit code 1 when issues were found, otherwise `Everything looks good`.

## lux mirrors, history, configs

- `lux mirrors` runs `reflector --latest 20 --protocol https --sort rate --fastest 10 --save /etc/pacman.d/mirrorlist`.
- `lux history [n] [pkg]` shows `installed/removed/upgraded/downgraded/reinstalled` entries from
  `/var/log/pacman.log` (date, action, package, versions).
- `lux configs` says `No pending config files` or runs `pacdiff` as root to compare and merge
  `.pacnew`/`.pacsave` files.

## Interactive terminal store (TUI)

`lux` without arguments in a terminal opens an fzf-based store listing packages from the LuxOS and
Arch repositories (LuxOS apps first, `●` = installed, preview on the right). If the system has no
package databases yet it downloads them first.

| Key | Action |
|---|---|
| Enter | install the selected package(s) |
| Ctrl-R | remove selected |
| Ctrl-U | update the system |
| Tab | select more packages |
| Alt-L | LuxOS apps only |
| Alt-I | installed only |
| Alt-A | all packages |
| Esc | quit |

## Machine mode (for apps)

LuxOS Store, LuxOS Care and the Drivers app call
`/usr/lib/lux/lux_alpm.py --machine -y COMMAND`, which prints lines such as
`@@PLAN`, `@@PHASE`, `@@PROGRESS`, `@@RETRY`, `@@SUMMARY`, `@@ERROR <kind> <sentence>`,
`@@UNAVAILABLE` and `@@DONE <code>`. Error kinds: `locked`, `network`, `keyring`, `disk`,
`conflict`, `pkgconflict`, `deps`, `corrupt`, `notfound`, `notinstalled`, `permission`,
`confirm`, `cancelled`, `unknown`. Exit codes: 0 ok, 1 error, 2 usage, 3 pyalpm unusable
(fall back to pacman), 130 interrupted. Full description: `/usr/share/doc/lux/lux.md`.

## Error messages and what to do

| Message (kind) | Fix |
|---|---|
| The package database is locked … (`locked`) | wait for the other update, otherwise `lux fix` |
| A package signature could not be verified … (`keyring`) | `lux fix`; check the clock |
| Some packages could not be downloaded … (`network`) | check internet; `lux mirrors` |
| Not enough free disk space … (`disk`) | `lux clean` |
| A downloaded package is damaged … (`corrupt`) | try again; if it repeats `lux clean` |
| file conflict (`conflict`) | a file exists on disk; `lux owns <file>` to find the owner |
| Dependencies can not be satisfied (`deps`) | usually a partial update; run `lux update` first |
| Package 'X' not found (`notfound`) | `lux search X` |
