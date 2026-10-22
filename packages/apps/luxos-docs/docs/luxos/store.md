# LuxOS Store

LuxOS Store (`luxos-store`, Czech name "Obchod LuxOS") is the graphical app store: browse,
install with one click, open, remove and update apps from the LuxOS and Arch Linux repositories.

- Launch: Launchpad/Search "LuxOS Store", or `luxos-store [search text]` (the optional argument
  pre-fills the search box).
- Package: `luxos-store` in `[luxos]` (`/usr/bin/luxos-store`, Python + GTK 3).
- Root actions: `/usr/lib/luxos/luxos-store-helper` through `pkexec`
  (polkit action `org.luxos.store.manage`, admin password, remembered for a short time).

## What the Store shows

| Source | How it appears |
|---|---|
| Arch Linux repositories (`[core]`, `[extra]`, …) | desktop apps described by AppStream metadata (`archlinux-appstream-data`) whose package exists in the synced databases |
| `[luxos-apps]` | all packages, even without AppStream; name and summary from the package description (`Name - summary`), icons downloaded from `https://lsl.lux-ai.cz/luxos/luxos-apps/x86_64/icons` |
| `.lux` repository | packages from the signed index (`lux __index`), labelled "LuxOS package (.lux)" |

The Store does **not** show AUR packages or Flatpak apps; use `lux install` for those
(see [package-management.md](package-management.md)). Command-line tools without a desktop app
are also not listed (search them with `lux search`).

## Layout

- Sidebar: **Discover**, **LuxOS Apps**, CATEGORIES (Internet, Office, Graphics, Music & Video,
  Developer Tools, Games, Education & Science, Utilities, System), LIBRARY (**Installed**, **Updates**).
- Discover: a welcome banner ("Welcome to the LuxOS Store"), "From LuxOS" (LuxOS apps) and
  "Popular apps" (Firefox, Chromium, Thunderbird, LibreOffice, GIMP, Inkscape, Krita, VLC,
  OBS Studio, Kdenlive, Audacity, Blender, Telegram, Signal, Discord, Code - OSS, …).
- LuxOS Apps: "Apps made for LuxOS, signed by the LuxOS team."
- Search box "Search apps" (at least 2 characters; matches name, package name and summary,
  LuxOS apps ranked first).
- App detail: icon, name, **Get** / **Open** button, **Remove** for installed apps, Version, Size,
  Package, About (description) and Website.

## Install, open, remove

- **Get** installs: repository packages via `luxos-store-helper install <pkg>` (lux in machine mode,
  `--needed`); `.lux` packages via `luxos-store-helper lux-install <name>`.
- **Open** launches the installed app (if it has no window: "X is installed, but has no window to open.").
- **Remove** asks "Remove X?" — "The app will be removed from this computer. Your files stay untouched."
  Repository packages are removed like `lux remove` (with unneeded dependencies).
- A status bar shows progress: Downloading…, Checking…, Installing X…, Finishing…, and retries
  ("Download failed, trying again (attempt N)…").

## Updates page

- **Check for Updates** runs `checkupdates` (no root needed, does not touch the system databases).
- **Update All** (only enabled when updates exist) runs `luxos-store-helper upgrade` = full
  `lux update` of repository packages ("Updating system…").
- With Data Saver on, updates are not checked automatically when the page opens
  ("Data Saver is on - updates are not checked automatically.").
- A failed check shows "Could not check for updates. Check your internet connection and try again."
- Automatic background updates are handled by LuxOS Care / Software Update, see
  [care-updates.md](care-updates.md).

## Error messages

| Message | Meaning / fix |
|---|---|
| The internet connection is too slow or unavailable. Try it again later. | network |
| Another app is installing software right now. Try it again in a moment. | database locked (LuxOS Care or lux running); if it persists: `lux fix` |
| Not enough free disk space. | `lux clean` or free space |
| A package signature could not be verified. Run in Terminal: lux fix | keyring |
| The app conflicts with files of another package. / … with an installed package. | conflict |
| Some required packages are not available. | dependencies; run a full update first |
| The app is no longer available in the repository. | removed upstream |

## Helper interface

```
luxos-store-helper install|remove PACKAGE...   # repository packages (lux_alpm.py --machine -y)
luxos-store-helper upgrade                     # full system update
luxos-store-helper lux-install|lux-remove NAME # .lux packages
```

Package names are validated (`^[a-z0-9@._+][a-z0-9@._+-]*$`). Without a usable `pyalpm` the
helper falls back to the internal pacman with up to 3 retries on network errors.
