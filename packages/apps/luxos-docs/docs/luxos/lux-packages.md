# The .lux package format

`.lux` is LuxOS's own app format, managed by [`lux`](package-management.md) and offered in the
[LuxOS Store](store.md). A package is one file named `name-version-release-arch.lux`: a
**tar + zstd** archive with metadata, the app itself and everything needed to integrate it into
the system. Apps are self-contained in `/opt/lux/<name>`.

Reference installed on the system: `/usr/share/doc/lux/lux-package-format.md`.
Implementation: `/usr/lib/lux/luxpkg.sh`.

## Archive contents

```
lux.json                 metadata (required)
app/                     the application -> /opt/lux/<name>/app/
share/                   optional: files for the system -> /usr/local/share/
  applications/<name>.desktop
  icons/hicolor/<size>/apps/<name>.png|svg
scripts/                 optional: post_install, pre_remove (bash, run as root)
```

## lux.json

```json
{
  "format": 1,
  "name": "hello-lux",
  "title": "Hello Lux",
  "version": "1.0.0",
  "release": 1,
  "arch": "any",
  "summary": "Example app in the LuxOS package format",
  "description": "Shows a greeting. Use it as a template for your own .lux packages.",
  "license": "MIT",
  "url": "https://luxos.lux-ai.cz/repo/",
  "categories": ["Utility"],
  "depends": { "system": ["yad"], "lux": [] },
  "bin": { "hello-lux": "hello-lux" }
}
```

| Field | Meaning |
|---|---|
| `format` | format version (currently `1`); an older lux refuses newer packages (`This package needs a newer lux`) |
| `name` | identifier: lowercase letters, digits, `.` `_` `+` `-`, must start with a letter or digit |
| `title` | display name (Store), optional |
| `version`, `release` | app version and package release (compared like other package versions, `vercmp`); `release` defaults to 1 |
| `arch` | `any` or `x86_64` (default `any`) |
| `summary`, `description`, `license`, `url`, `categories` | info for the Store and `lux info`; freedesktop categories (`Utility`, `Development`, `Graphics`, …) |
| `depends.system` | packages from the LuxOS/Arch repositories, installed first through libalpm |
| `depends.lux` | other `.lux` packages from the LuxOS repository |
| `bin` | commands: `name` → path inside `app/`; creates the symlink `/usr/local/bin/<name>` |

## Installation

`lux install file.lux` or `lux install <name>` (from the repository):

1. Verifies the signature with the LuxOS key (`/usr/share/pacman/keyrings/luxos.gpg`, `gpgv`).
   From the repository the SHA-256 from the index is also checked. A local file without a valid
   `file.lux.sig` next to it prints `… is not signed by LuxOS.` and asks `Install it anyway?` (default No).
2. Installs `depends.system` (repositories) and missing `depends.lux`.
3. When upgrading, runs the old version's `scripts/pre_remove` first.
4. Unpacks into a temporary dir in `/opt/lux`, then replaces `/opt/lux/<name>` (the old version is
   removed only after unpacking succeeded).
5. Creates commands in `/usr/local/bin`, copies `share/` into `/usr/local/share`, refreshes the
   desktop database and icon cache.
6. Writes the metadata plus `installed_files` and an `installed` timestamp to
   `/var/lib/lux/installed/<name>.json`, then runs `scripts/post_install`
   (environment: `LUX_PACKAGE=<name>`, `LUX_PREFIX=/opt/lux/<name>`).

## Managing installed .lux apps

| Task | Command |
|---|---|
| list | `lux list --lux` |
| details | `lux info <name>` (shows `Format : lux`) |
| files | `lux files <name>` (prints `/opt/lux/<name>/` and the integrated files) |
| owner of a file | `lux owns /opt/lux/<name>/...` → `(LuxOS)` |
| update | `lux update` (section `Updating LuxOS apps`) |
| reinstall | `lux reinstall <name>` |
| remove | `lux remove <name>` — runs `scripts/pre_remove`, deletes exactly the recorded files in `/usr/local` and `/opt/lux/<name>` |

## Repository

`https://luxos.lux-ai.cz/repo/lux/`:

- `index.json` + `index.json.sig` — list of packages (`name`, `title`, `version`, `release`, `arch`,
  `summary`, `description`, `depends`, `license`, `url`, `categories`, `file`, `size`, `sha256`, optional `icon`),
- `<file>.lux` + `<file>.lux.sig`, icons `<name>.icon.svg|png` for the Store.

lux caches the verified index for 30 minutes (`~/.cache/lux/index.json`, as root
`/var/cache/lux/index.json`). If the download or signature check fails, the cached copy is used
(or an empty list). The repository may contain few or no packages; most LuxOS apps are regular
packages in `[luxos-apps]`.

## Building a package

```bash
cp -r docs/examples/hello-lux lux-packages/my-app   # in the LuxOS source tree; edit lux.json and app/
lux pack lux-packages/my-app out/                  # build and check
lux install out/my-app-1.0.0-1-any.lux             # test locally (asks because it is unsigned)
```

`lux pack DIR [OUT]` checks that `lux.json` is valid JSON, the name and version are valid, `app/`
exists and every `bin` target exists, then writes a reproducible archive
(owner 0, sorted names, mtime 0) containing `lux.json`, `app` and, if present, `share` and `scripts`.
Signing and publishing to the LuxOS repository is done by the LuxOS build (`./build.sh packages`,
`scripts/publish-repo.sh`) with the LuxOS signing key.
