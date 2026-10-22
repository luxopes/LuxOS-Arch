# lux-engine, repositories and signing

## No pacman command

LuxOS is based on Arch Linux but has **no `pacman` command**. The package manager is
[`lux`](package-management.md). Its core is the package **`lux-engine`**: libalpm and the pacman
tools built from exactly the same sources, checksums and patches as Arch Linux's `pacman`
package (currently Arch tag `7.1.0.r9.g54d9411-3`, LuxOS `pkgver=7.1.0.r9.g54d9411`, `pkgrel=3.1`).

Differences from Arch's `pacman` package (only in packaging):

- `pacman`, `pacman-key`, `pacman-conf` and `pacman-db-upgrade` are **internal tools** in
  `/usr/lib/lux/alpm/bin`, outside `PATH`, without man pages or shell completion.
  `/usr/lib/lux/alpm/pacman` is a compatibility symlink for LuxOS 0.9 callers.
- `makepkg`, `vercmp`, `repo-add`, `repo-remove`, libalpm hooks and `/etc/makepkg.conf` stay as in Arch.
- `/etc/pacman.conf` is the LuxOS configuration (identical to the installer's copy).
- `provides=(pacman libalpm.so luxos-pacman)`, `conflicts`/`replaces` `pacman` and `luxos-pacman`,
  so packages depending on `pacman` keep working.

Who gets the internal tools in `PATH`:

| Caller | How |
|---|---|
| `lux`, `lux_alpm.py` and hooks/scriptlets of their transactions | prepend `/usr/lib/lux/alpm/bin` to `PATH`; via sudo/pkexec a fixed `PATH=/usr/lib/lux/alpm/bin:/usr/local/sbin:/usr/local/bin:/usr/bin` |
| `makepkg` | `/etc/makepkg.conf.d/lux-engine.conf` sets `PATH`, `PACMAN=/usr/lib/lux/alpm/bin/pacman` and `PACMAN_AUTH` (sudo with the same PATH) |
| `paccache`, `pacman-filesdb-refresh`, `archlinux-keyring-wkd-sync` services | drop-ins `/usr/lib/systemd/system/<unit>.service.d/lux-engine.conf` |
| LuxOS Store, LuxOS Care, Drivers, printing, installer, sandbox | set the path themselves |

A global systemd `DefaultEnvironment` is intentionally not used (user sessions would inherit it).

Signing keys from keyring packages (`archlinux-keyring`, `luxos-keyring`) are loaded by the hook
`/usr/share/libalpm/hooks/lux-engine-keyrings.hook` (runs `pacman-key --populate <keyring>` after
any transaction that installs or upgrades `usr/share/pacman/keyrings/*.gpg`), because the
keyrings' own install scripts call `/usr/bin/pacman-key`, which does not exist in LuxOS.

For debugging only, an assistant may call `/usr/lib/lux/alpm/bin/pacman -Q ...` for read-only
queries, but all changes should go through `lux`.

## The pacman hint

Typing `pacman` (or `lux -Syu`, `lux -S x` …) shows the matching lux command instead of
"command not found". The helper is `/usr/lib/lux/pacman-hint`, called from the shell's
command-not-found handler (bashrc/zshrc/lsh) and by lux for pacman-style arguments. It never
installs or runs anything and exits with code 1.

```
✦ LuxOS uses lux to manage software.
  pacman -Syu  →  lux update
  All lux commands: lux --help
```

| pacman | lux |
|---|---|
| `pacman -Syu`, `-Su` | `lux update` |
| `pacman -Syu foo` | `lux update` + `lux install foo` |
| `pacman -Sy` | `lux update` |
| `pacman -S foo` | `lux install foo` |
| `pacman -U file.pkg.tar.zst` | `lux install file.pkg.tar.zst` |
| `pacman -Ss term` | `lux search term` |
| `pacman -Si foo` | `lux info foo` |
| `pacman -Sc`, `-Scc` | `lux clean` |
| `pacman -R…` `foo` | `lux remove foo` |
| `pacman -Q` | `lux list` |
| `pacman -Q foo`, `-Qi foo` | `lux info foo` |
| `pacman -Qs term` | `lux list term` |
| `pacman -Qu` | `lux list --upgradable` |
| `pacman -Qdt` | `lux list --orphans` + `lux autoremove` |
| `pacman -Qm` | `lux list --aur` |
| `pacman -Qe` | `lux list --explicit` |
| `pacman -Ql foo` | `lux files foo` |
| `pacman -Qo file` | `lux owns file` |
| `pacman -Qk` | `lux doctor` |
| `pacman -V` | `lux --version` |

## Keeping up with Arch

`pyalpm` from Arch is built against Arch's `libalpm.so`, so `lux-engine` must follow Arch's pacman
version. `lux doctor` warns `The package manager core X is older than the one in Arch Linux (Y); a LuxOS
update will follow`. If `pyalpm` is unusable in the meantime, lux falls back to the internal pacman
automatically. Check the backend: `/usr/lib/lux/lux_alpm.py --verbose available`. Force the fallback:
`LUX_BACKEND=pacman lux …`.

## Migration from LuxOS 0.9

LuxOS 0.9.0 shipped `luxos-pacman`; since 0.9.1 the engine is `lux-engine`, which `replaces` it.
`lux update` swaps it automatically. Since 0.9.2, `lux` and LuxOS Care depend on the virtual
`pacman` so older installs update without "unresolvable package conflicts"; the new lux then
replaces the engine.

## Repositories

`/etc/pacman.conf` (LuxOS default, without comments):

```ini
[options]
HoldPkg     = pacman glibc
Architecture = auto
Color
ILoveCandy
CheckSpace
VerbosePkgLists
ParallelDownloads = 10
DownloadUser = alpm
SigLevel    = Required DatabaseOptional
LocalFileSigLevel = Optional

[luxos]
Server = https://lsl.lux-ai.cz/luxos/$repo/$arch

[luxos-apps]
Server = https://lsl.lux-ai.cz/luxos/$repo/$arch

[core]
Include = /etc/pacman.d/mirrorlist

[extra]
Include = /etc/pacman.d/mirrorlist
```

| Repository | Content |
|---|---|
| `[luxos]` | the LuxOS system: lux-engine, lux, luxos-desktop, luxos-care, luxos-drivers, luxos-installer, lsh, themes, branding, LuxDrop, … and legacy NVIDIA drivers (`nvidia-580xx-*`, `nvidia-470xx-*`, built from AUR, online only) |
| `[luxos-apps]` | downloadable apps, e.g. `lsl` (Lux Simple Lang), `lsl-ide`, `lux-code`, `luxai`, `luxos-docs` |
| `[core]`, `[extra]` | Arch Linux, via `/etc/pacman.d/mirrorlist` (`lux mirrors` refreshes it) |
| `.lux` repo | `https://lsl.lux-ai.cz/luxos/lux/` (`index.json` + signatures), see [lux-packages.md](lux-packages.md) |

`[multilib]` is not enabled by default; the installer's Gaming template enables it (Steam needs it).
`[luxos]`/`[luxos-apps]` are listed before Arch's repos, so LuxOS versions win on name clashes.
An overview page of the repos is at `https://lsl.lux-ai.cz/luxos/`.

The live ISO installs LuxOS packages from a local copy at `/opt/luxos-repo` (`file://` servers);
the installed system uses the online servers above.

## Signing and luxos-keyring

- Every package and database in `[luxos]`/`[luxos-apps]` is signed with the LuxOS key, fingerprint
  `FD185DAB770140E89C37275E7035CFDFDCA6C991` (marked fully trusted in `luxos-trusted`).
- The public key is in the package `luxos-keyring`:
  `/usr/share/pacman/keyrings/luxos.gpg`, `luxos-trusted`, `luxos-revoked`.
- `SigLevel = Required DatabaseOptional`: package signatures are mandatory; local files
  (`lux install ./x.pkg.tar.zst`) are `Optional`.
- `.lux` packages and the `.lux` index are verified with `gpgv` against the same `luxos.gpg`.
- Keyring problems: `lux fix` (re-init and re-populate the keyring, reinstall keyrings).
