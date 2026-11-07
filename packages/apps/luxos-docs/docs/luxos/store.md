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
| Arch Linux repositories (`[core]`, `[extra]`, …) | desktop apps described by AppStream metadata (`archlinux-appstream-data`) whose package exists in the synced databases (not packages that come from `[luxos]`/`[luxos-apps]`, e.g. the adopted libraries vte3/vte4) |
| LuxOS apps (`[luxos]`, `[luxos-apps]`) | the LuxOS app catalog `apps.json` (see below): every user-facing app of a LuxOS package, also when it is not installed |
| `.lux` repository | packages from the signed index (`lux __index`), labelled "LuxOS package (.lux)" |

| Flathub | **search results only**: section "From Flathub" under the search results (Flathub API through `/usr/lib/lux/lux_community.py`, max 12, apps already in the repositories are skipped, not with Data Saver on), badge "Flathub", detail with size incl. a shared runtime that is not installed yet; installed Flatpak apps also appear in Installed |

Flathub apps are installed and removed with `lux -y install|remove <app ID>` (no Store helper:
flatpak asks for permission itself; progress is a pulsing bar). Removing also deletes Flatpak
runtimes nothing uses. The Store does **not** show community (AUR) packages: the search page says
to use `lux install <name>` in Terminal, which installs them into the sandbox
(see [package-management.md](package-management.md)). Command-line tools without a desktop app
are also not listed (search them with `lux search`).

## LuxOS app catalog

The section **LuxOS Apps** (and "From LuxOS" on Discover) comes from the catalog
`https://luxos.lux-ai.cz/repo/apps.json` (icons in `app-icons/` next to it; staging channel
`/staging/apps.json`). It is generated from the signed packages when the repositories are published
(`scripts/publish-repo.sh`; for the ISO `scripts/container-build.sh` writes `/opt/luxos-repo/apps.json`)
by `/usr/lib/luxos/python/luxos_app_catalog.py generate REPO_ROOT`.

- An app is every `.desktop` file of type Application in `/usr/share/applications` of a LuxOS package:
  all of `[luxos-apps]`, from `[luxos]` only LuxOS's own `lux*` packages (packages adopted from Arch
  such as vte3, rofi or xfwm4 are never listed; libraries and documentation have no `.desktop`).
- Not listed: hidden entries (`NoDisplay=true`, `Hidden=true`), Settings panels (`Categories=Settings`)
  and the Launchpad copies `*-launchpad.desktop`.
- A package decides with a key in its `.desktop`: `X-LuxOS-Store=show` lists a Settings panel or hidden
  app anyway (LuxAI Account, Phone, Printers & Scanners, Profile Picture, Firewall, Drivers, What's New),
  `X-LuxOS-Store=hide` hides a part of the system (Launchpad, About This Computer, Welcome, Install LuxOS,
  the Store itself).
- Name and summary are shown in the user's language (`Name[cs]`/`Comment[cs]` from the `.desktop`,
  otherwise the `luxos-i18n` translation of `Name`/`Comment`).
- Featured apps come first (LuxAI, Terminal, Text Editor, Maps, Weather, Mail, Calculator, LuxDrop,
  Backups, Safe, Screenshot, LSL IDE, Lux Code), then the rest by name. Each app is in the Store category
  of its `Categories` (Settings panels go to System).
- Apps of `luxos-desktop` and its dependencies are part of the system: always installed, the Store offers
  no Remove for them.
- Button: **Open** (installed), **Get**, or **Update** when the package has a known update or the app
  arrived in a newer package version than the installed one (its `.desktop` is not on the system yet) –
  Update opens the Updates page.
- The Store keeps the catalog in `~/.cache/luxos-store/apps.json`; an older copy (6 hours) is used
  immediately and refreshed in the background. Without any catalog (first start offline) the same
  selection is built from the `.desktop` files of the installed LuxOS packages.

## Layout

- Sidebar: **Discover**, **LuxOS Apps**, CATEGORIES (Internet, Office, Graphics, Music & Video,
  Developer Tools, Games, Education & Science, Utilities, System), LIBRARY (**Installed**, **Updates**).
- Discover: a welcome banner ("Welcome to the LuxOS Store"), "From LuxOS" (the first 6 featured LuxOS apps) and
  "Popular apps" (Firefox, Chromium, Thunderbird, LibreOffice, GIMP, Inkscape, Krita, VLC,
  OBS Studio, Kdenlive, Audacity, Blender, Telegram, Signal, Discord, Code - OSS, …).
- LuxOS Apps: "Apps made for LuxOS, signed by the LuxOS team." – all apps of the LuxOS app catalog.
- Search box "Search apps" (at least 2 characters; matches name, package name and summary,
  LuxOS apps ranked first).
- App detail: icon, name, **Get** / **Open** / **Update** button, **Remove** for installed apps (not for parts of the system), Version, Size,
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

- **Check for Updates** runs `lux_alpm.py check-updates` (no root needed, does not touch the system databases).
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
helper falls back to the internal tool `lux-engine` with up to 3 retries on network errors.
