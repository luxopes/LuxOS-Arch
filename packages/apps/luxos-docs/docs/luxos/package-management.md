# Package management with lux

`lux` is the LuxOS package manager and the only supported way to install, update and remove
software from the command line. It manages packages from the LuxOS and Arch Linux repositories
directly through **libalpm** (used from Python via `pyalpm`), and also handles Flathub (Flatpak),
the community source (AUR, built and installed into your sandbox by default) and the LuxOS `.lux`
app format.

There is **no `pacman` command and no `/etc/pacman.conf`** in LuxOS. The configuration is
`/etc/lux/lux.conf` in its own format (see [Configuration](#configuration-etcluxluxconf)). The engine
behind lux is the `lux-engine` package (libalpm and tools taken from Arch Linux pacman) — see
[lux-engine-and-repos.md](lux-engine-and-repos.md).

- Program: `/usr/bin/lux` (bash); transaction backend `/usr/lib/lux/lux_alpm.py`.
- `.lux` support: `/usr/lib/lux/luxpkg.sh` (see [lux-packages.md](lux-packages.md)).
- Reference installed with the package: `/usr/share/doc/lux/lux.md`.

## Files

| Path | What it is |
|---|---|
| `/etc/lux/lux.conf` | configuration: repositories, signatures, held packages, lux settings |
| `/etc/lux/conf.d/*.conf` | more files in the same format (repositories added by packages or the admin) |
| `/etc/lux/mirrorlist` | Arch Linux download mirrors, one address per line (`lux mirrors`) |
| `~/.config/lux/lux.conf` | per-user lux settings (only `aur`, `review-pkgbuild`, `flatpak`, `clean-keep`) |
| `/var/lib/lux/` | package database (`local/`, `sync/`, lock `db.lck`); `installed/` = `.lux` apps |
| `/var/cache/lux/pkg/` | downloaded packages |
| `/var/log/lux.log` | transaction log (`lux history`) |
| `/etc/lux/keyring/` | GnuPG keyring for package signatures (`lux fix` repairs it) |
| `/etc/lux/hooks/` | admin hooks (`*.hook`, alpm-hooks format) |
| `/run/lux/engine.conf` | **generated** engine configuration — never edit, it is rebuilt from lux.conf |

## Commands

| Command (aliases) | What it does |
|---|---|
| `lux` (no arguments) | interactive store in the terminal (TUI, needs `fzf`) |
| `lux install <pkg...>` (`i`, `add`) | install from repositories → LuxOS `.lux` → Flathub → community (AUR, into the sandbox); also a local `.lux` or `.pkg.tar.*` file; installed packages are skipped |
| `lux remove <pkg...>` (`rm`) | remove with no longer needed dependencies; config files you changed stay as `*.luxsave` (`-n`/`--nosave` deletes them too) |
| `lux update` (`upgrade`, `up`) | refresh databases, signing keys first, then the whole system; then community (AUR) packages in the system, `.lux` apps, Flatpak (+ unused runtimes removed) |
| `lux search <term>` (`s`) | search repositories, the LuxOS `.lux` repo, Flathub and the community source (AUR) |
| `lux info <pkg>` (`show`) | details (installed, else repository, `.lux`, AUR) |
| `lux list [--installed]` (`ls`) | installed packages (including `.lux`); `lux list <pattern>` filters |
| `lux check` (`check-updates`) | available updates from freshly downloaded lists (temporary copy, no root, nothing changes) |
| `lux list --upgradable` | available updates according to the last database refresh |
| `lux list --explicit` / `--aur` / `--orphans` / `--lux` | explicitly installed / not from a repository / unneeded / `.lux` apps |
| `lux reinstall <pkg...>` | same version again (repository, else cache) |
| `lux autoremove` | remove orphaned dependencies |
| `lux files <pkg>` / `lux owns <file>` | files of a package / which package owns a file |
| `lux clean` | clean the cache (keeps `clean-keep` versions, removes uninstalled packages), offers `autoremove` |
| `lux fix` | repair a locked database, unfinished downloads and the signing keys |
| `lux configs` | review new config files from updates (`.luxnew`, `.luxsave`; older `.pacnew`, `.pacsave` too): diff, use new, keep yours, edit |
| `lux config [check\|show\|edit\|engine]` | check, show or edit `/etc/lux/lux.conf`; `engine` prints the generated engine config |
| `lux history [n] [pkg]` | recent package changes from `/var/log/lux.log` |
| `lux mirrors` | fastest mirrors (`reflector`) written to `/etc/lux/mirrorlist` |
| `lux drivers` / `lux doctor` / `lux pack <dir>` | drivers ([drivers.md](drivers.md)), health check, build a `.lux` |
| `lux system show\|init\|edit\|check\|diff\|apply` | the whole system (packages, services, users, ...) in one LSL file `/etc/luxos/system.lsl`, see [system-config.md](system-config.md) |

Options: `-y`/`--yes` (no questions — otherwise lux always asks), `-n`/`--nosave` (`lux remove`
also deletes changed config files, no `*.luxsave`), `-v`/`--verbose` (package lists,
script output, raw errors), `--repo` (only official repositories), `--aur`/`--community` (only the
community source), `--system` (community package into the system instead of the sandbox), `-h`, `-V`.

```bash
lux install firefox
lux install ./myapp-1.0-1-any.lux
lux install zoom                 # not in the repositories -> Flathub (us.zoom.Zoom)
lux install org.gimp.GIMP        # Flatpak app ID
lux remove zoom                  # also removes Flatpak apps (+ runtimes nothing uses)
lux -y update
lux owns /usr/bin/fastfetch
lux history 50 linux-luxos
```

Arch habits are translated: typing `pacman -Syu` (or `lux -Syu`) prints the matching lux command
(`lux update`), `pacman -S x` → `lux install x`.

## Configuration: /etc/lux/lux.conf

LuxOS format: one `key  value` per line (separated by spaces), `#` starts a comment to the end of
the line. Lines indented with spaces or a tab belong to the `repo NAME` line above them. Edit as
root (`lux config edit` opens it and checks it afterwards), then run `lux config check`.

```
architecture        auto
parallel-downloads  10
signatures          required          # required | optional | never
hold                linux-firmware    # keep at the current version
aur                 on

repo luxos
    server  https://luxos.lux-ai.cz/repo/$repo/$arch

repo core
    mirrors  /etc/lux/mirrorlist

include  /etc/lux/conf.d/*.conf
```

### Global keys

| Key | Value (default) | Meaning |
|---|---|---|
| `architecture` | `auto` | package architecture |
| `parallel-downloads` | number ≥ 1 (`10`) | files downloaded at once |
| `signatures` | `required` \| `optional` (`required`) | package/database signature checks; `never` only for a local `file://` repo |
| `local-signatures` | `required` \| `optional` \| `never` (`optional`) | packages installed from a file (AUR builds) |
| `hold` | package names, repeatable | held packages: `lux update` skips them (pacman's `IgnorePkg`) |
| `ignore-group` | group names, repeatable | the same for package groups |
| `protect` | package names (`lux-engine glibc`) | `lux remove` warns and never removes them with `-y` |
| `no-upgrade` | paths without leading `/`, repeatable | files updates never overwrite (new version saved as `.luxnew`) |
| `no-extract` | path patterns, repeatable | files never extracted (e.g. `usr/share/doc/*`) |
| `color`, `candy`, `verbose-lists`, `check-space` | `on` \| `off` (`on`) | colors, Pac-Man progress bar, detailed lists, free space check |
| `syslog` | `on` \| `off` (`off`) | also log to the system journal |
| `download-timeout` | `on` \| `off` (`on`) | `off` = no timeout for slow mirrors |
| `download-user` | user \| `none` (`alpm`) | unprivileged user that downloads |
| `download-sandbox` | `on` \| `off` (`on`) | restrict the download process |
| `cache`, `hooks` | absolute path, repeatable | other cache / hook directories |
| `database`, `log`, `keyring` | absolute path | other database, log, keyring |
| `include` | path or pattern | load more files in the same format |
| `aur` | `on` \| `off` (`on`) | AUR packages (built on this computer) |
| `review-pkgbuild` | `on` \| `off` (`on`) | offer to read the build script before an AUR build |
| `flatpak` | `on` \| `off` (`on`) | `lux update` also updates Flatpak apps |
| `clean-keep` | number (`2`) | versions per package `lux clean` keeps |

### Repositories

`repo NAME` starts a block; indented keys belong to it. Block order is search order (the first
repository that has a package wins).

| Key in block | Value | Meaning |
|---|---|---|
| `server` | `https://`, `http://`, `ftp://` or `file://` address, repeatable | `$repo` and `$arch` are filled in |
| `mirrors` | path to a mirror list, repeatable | addresses from the file (e.g. `/etc/lux/mirrorlist`) |
| `signatures` | `required` \| `optional` \| `never` | overrides the global setting (`never` only for `file://`) |
| `usage` | `sync search install upgrade all` | what the repository is used for (default `all`) |

### Mirror list: /etc/lux/mirrorlist

One address per line, best first, `#` comments. The default is the worldwide mirror
`geo.mirror.pkgbuild.com` (picks the nearest) plus a few reliable HTTPS mirrors. `lux mirrors`
replaces it with the fastest mirrors; `reflector.timer` refreshes it weekly. `Server = …` lines from
other tools are accepted when reading, but lux writes plain addresses.

```
https://geo.mirror.pkgbuild.com/$repo/os/$arch
https://mirror.rackspace.com/archlinux/$repo/os/$arch
```

### Examples

- **Add a repository** — create `/etc/lux/conf.d/myrepo.conf`, then `lux update`:
  ```
  repo myrepo
      server  https://example.org/$repo/$arch
  ```
  Import its signing key with `sudo /usr/lib/lux/alpm/bin/lux-engine-key --recv-keys ID` and
  `--lsign-key ID`. `multilib` (Steam): `sudo /usr/lib/lux/lux-config enable-repo multilib`.
- **Hold a package**: add `hold  linux-firmware` (several names per line or several lines).
- **Change mirrors**: `lux mirrors`, or edit `/etc/lux/mirrorlist` (one address per line).
- **Disable AUR**: `aur  off` in lux.conf; for one user `aur off` in `~/.config/lux/lux.conf`.

### Errors

Unknown keys, wrong values and pacman.conf syntax (`[options]`, `Key = value`) are errors with the
file and line number:

```
lux: error in the configuration: /etc/lux/lux.conf:12: unknown key 'paralel-downloads' (did you mean 'parallel-downloads'?)
lux: the package manager keeps using the last working configuration until this is fixed
✗ lux will not run until the configuration is fixed (/etc/lux/lux.conf). Check it with: lux config check
```

With a broken config lux, LuxOS Store and LuxOS Care install and update nothing until it is fixed;
hooks and `makepkg` keep the last working generated config. Other messages: `repository 'x' has no
'server' or 'mirrors' line`, `mirror list … does not exist`, `mirror list … has no mirrors`,
`'signatures never' is only allowed for a local repository (file://)`, `repository 'x' is already
defined at FILE:LINE`, `indented line '…' does not belong to any 'repo' block`, `'server' belongs to
a repository: indent it under a 'repo NAME' line`, `'parallel-downloads' must be a whole number of
at least 1`, `'color' must be on or off`.

### How it works and migration from pacman

`lux-config` (`/usr/lib/lux/lux-config`) turns lux.conf, included files and mirror lists into
`/run/lux/engine.conf` for the engine and regenerates it whenever a source changes. Updating
LuxOS 0.9.5 or older moves `/var/lib/pacman` → `/var/lib/lux`, `/var/cache/pacman/pkg` →
`/var/cache/lux/pkg`, `/etc/pacman.d/gnupg` → `/etc/lux/keyring`, `/var/log/pacman.log` →
`/var/log/lux.log`, converts custom repositories and options from `/etc/pacman.conf`
(`[multilib]`, `IgnorePkg` → `hold`, …) into lux.conf and the ranked mirror list into
`/etc/lux/mirrorlist`. Leftover links are cleaned after the next restart; copies stay in
`/var/lib/lux/migrated-from-pacman/`.

Config files kept by updates are named after lux: `*.luxnew` (new version of a file you changed)
and `*.luxsave` (your changed file of a removed package). LuxOS 1.0 renames older `*.pacnew`,
`*.pacsave` and `*.pacorig` files in `/etc` once when `lux-engine` is updated (an existing
`.luxnew`/`.luxsave` is never overwritten; renamed files are listed in `/var/log/lux.log`).
`lux configs`, `lux doctor` and LuxOS Care still recognise the old names.

## Administrator rights

Run lux as a normal user; it asks for root itself (`sudo` in a terminal, `pkexec` in a graphical
session). Community (AUR) packages are built as a regular user — never `sudo lux install <aur-package>`.
Environment: `LUX_BACKEND=engine` (force the `lux-engine` fallback), `NO_COLOR`, `LUX_LOCK_WAIT`
(seconds to wait for another package manager, default 300).

## Flathub and the community source (AUR)

Order of sources for `lux install <name>`: LuxOS and Arch Linux repositories → LuxOS `.lux` apps →
**Flathub** → **community (AUR)**. The first source that has the name wins.

**Flathub** (`flatpak on`):
- The name is looked up with the Flathub API (works before flatpak is installed): an app ID
  (`us.zoom.Zoom`), an exact app name or the last part of the ID (`zoom`). Several matches → a
  numbered choice (none with `-y`).
- lux offers to install `flatpak`, adds the `flathub` remote if missing and shows the download and
  disk size, **including the shared runtime** (for example `org.freedesktop.Platform`, 0.5–1 GB)
  when it is not installed yet. Runtimes are shared by all Flatpak apps.
- `lux remove <id or name>` removes the app and then runs `flatpak uninstall --unused` (runtimes
  no app needs); `lux update` does the same after `flatpak update`. App data in `~/.var/app` stays.

**Community (AUR)** — build scripts written by other users, not checked by LuxOS:
- Before building, the PKGBUILD (and `.install` files) is checked: fixed rules (curl | sh, hidden
  base64, writes outside `$pkgdir`, sudo/SSH/accounts, network in `.install`, plain-HTTP sources…)
  and **LuxAI Lite** when you are signed in to LuxAI (verdict safe / suspicious / dangerous with
  reasons; only the script text is sent). Without LuxAI the verdict is "not checked".
- **Default target: your sandbox** ([sandbox.md](sandbox.md)). lux copies the checked directory into
  the sandbox (`luxos-sandbox build-install`), installs `base-devel`/dependencies there, runs
  `makepkg` inside as the sandbox user and installs the result with the sandbox's own `pacman`. The
  build script never runs on your system. Start the app with `luxos-sandbox run --gui --net <command>`.
- **Into the system only with explicit permission**: `--system`, or choose "2 System" and type the
  word `system`. A **dangerous** script is never installed into the system; an unchecked or
  suspicious one only after you confirm without `-y`. System builds use `makepkg -si`
  (`jq`, `git`, `base-devel` are offered), sources in `~/.cache/lux/aur/<pkgbase>`.
- `lux update` rebuilds newer versions of community packages already in the system and checks the
  new build script again (not as root, not with `--repo`).
- **LuxAI never installs community packages**: lux refuses them when run by the LuxAI agent
  (`LUXAI_AGENT=1`) and LuxAI tells you to run `lux install <name>` yourself.
- Hardware drivers people need (printers, scanners) are verified and shipped in the LuxOS
  repository instead — see [drivers.md](drivers.md).

## lux update in detail

1. Waits up to 5 minutes for another package manager (LuxOS Care, Store); a stale lock with nothing
   running is removed (`Removed a stale database lock left by an interrupted update.`).
2. Refreshes databases, updates `archlinux-keyring` / `luxos-keyring` first, then the full system.
3. Community (AUR) packages in the system, `.lux` apps, Flatpak apps (then unused Flatpak runtimes are
   removed); lists new `*.luxnew` files and warns when a restart is needed.

Automatic background updates are done by LuxOS Care — see [care-updates.md](care-updates.md).

## lux fix, doctor, clean

- `lux fix` (as root): checks `/var/lib/lux/db.lck` — if a package manager runs (`lux-engine`,
  `lux_alpm.py`, `makepkg`, …) it says `Another package manager is running (…)`, otherwise offers to
  remove the stale lock; deletes unfinished downloads; initializes/populates the keyring
  (`lux-engine-key --init/--populate`); warns about an unsynchronized clock; reinstalls the keyrings.
  Never delete `db.lck` by hand while an update runs.
- `lux doctor`: failed services, `.luxnew` files, disk usage, orphans, available updates (checked
  into a temporary database copy), configuration errors, old package manager files waiting for
  cleanup, engine version vs. Arch, replaced kernel, journal errors.
- `lux clean`: own cache cleaner (no pacman-contrib): keeps `clean-keep` newest versions of
  installed packages, removes cached uninstalled packages, then offers `autoremove`.

## Interactive terminal store (TUI)

`lux` without arguments opens an fzf store (LuxOS apps first, `●` = installed). Keys: Enter install,
Ctrl-R remove, Ctrl-U update, Tab select more, Alt-L LuxOS apps, Alt-I installed, Alt-A all, Esc quit.

## Machine mode (for apps)

LuxOS Store, LuxOS Care and the Drivers app call `/usr/lib/lux/lux_alpm.py --machine -y COMMAND`
(`@@PLAN`, `@@PHASE`, `@@PROGRESS`, `@@ERROR <kind> <sentence>`, `@@DONE <code>` …). Error kinds:
`locked`, `network`, `keyring`, `disk`, `conflict`, `pkgconflict`, `deps`, `corrupt`, `notfound`,
`notinstalled`, `permission`, `confirm`, `cancelled`, `config`, `unknown`. Exit codes: 0 ok,
1 error, 2 usage, 3 pyalpm unusable (fall back to `lux-engine`), 130 interrupted. Also
`check-updates` (0 updates, 2 none), `clean`, `list --sync`, `migrate`.

## Error messages and what to do

| Message (kind) | Fix |
|---|---|
| The package database is locked … (`locked`) | wait for the other update, otherwise `lux fix` |
| A package signature could not be verified … (`keyring`) | `lux fix`; check the clock |
| Some packages could not be downloaded … (`network`) | check internet; `lux mirrors` |
| Not enough free disk space … (`disk`) | `lux clean` |
| file conflict (`conflict`) | `lux owns <file>` to find the owner |
| Dependencies can not be satisfied (`deps`) | usually a partial update; `lux update` first |
| configuration has an error (`config`) | `lux config check`, fix the reported line |
| Package 'X' not found (`notfound`) | `lux search X` |
| The package X was damaged again after a new download (`corrupt`) | lux already deleted the damaged file from `/var/cache/lux/pkg` and downloaded it once more; if it is damaged again, the server is probably being updated – try later |

The full command reference is also in the manual page: `man lux`.
