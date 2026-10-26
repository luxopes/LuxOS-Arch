# Guide for AI assistants on LuxOS

How an AI assistant (LuxAI, Lux Code or any other agent) should perform common tasks safely on a
LuxOS computer. LuxOS is Arch-based, but several Arch habits are wrong here.

## Golden rules

1. **Use `lux`, never `pacman`.** There is no `pacman` command and no `/etc/pacman.conf` or
   `/etc/pacman.d` — never suggest them, `yay`, `paru` or `pacman-contrib` tools. Install
   `lux install NAME`, remove `lux remove NAME`, update `lux update`, search `lux search TERM`, info
   `lux info NAME`, owner of a file `lux owns PATH`. Repositories, held packages and mirrors are in
   `/etc/lux/lux.conf` (LuxOS format, **not** pacman INI) and `/etc/lux/mirrorlist`; see
   [package management](package-management.md#configuration-etcluxluxconf). The engine tools in
   `/usr/lib/lux/alpm/bin` (`lux-engine`, `lux-engine-key`, `lux-engine-conf`) are only for advanced
   cases (read-only `lux-engine -Q…`, importing a repository key); never change packages with them.
2. **Never guess, ask for, store or pipe passwords.** Do not run `echo PASSWORD | sudo -S`, do not
   ask the user to type a password into the chat. LuxOS tools request administrator rights
   themselves: `lux` uses `sudo` in a terminal and a **polkit dialog (`pkexec`)** when it has no
   terminal but a graphical session; the user types the password in that dialog.
3. **Confirm before changing the system.** `lux` always asks `[Y/n]`; pass `-y` only after the
   user agreed in the conversation (e.g. `lux -y install gimp`). Without a terminal, run it with
   stdin not attached to a TTY so the graphical polkit prompt is used.
4. **Prefer the LuxOS app or command made for the task** (table below) over editing config files.
   LuxOS defaults live in `/etc/xdg/luxos`; user changes go to `~/.config`. Never edit files under
   `/usr` – they are replaced by updates.
5. **Do not touch secrets.** Never print `luxos-account token` or `~/.config/luxai/account.json`;
   use `luxos-account status`. Never ask for or handle the Safe password.
6. **No partial updates.** Do not refresh databases without upgrading; `lux update` does the full,
   correct sequence (keys first, then everything).
7. **Community (AUR) packages: never install them yourself.** `lux install` tries the repositories,
   LuxOS apps and Flathub first; a package that exists only in the community source (AUR) is built
   by the user in a terminal (`lux install NAME`, no sudo) and goes into their sandbox by default –
   `--system` only on the user's explicit request. LuxAI's agent is refused by lux. Tell the user
   that community packages are not checked by LuxOS.
8. **Printer or scanner driver missing?** Prefer the verified package from `[luxos-drivers]`
   (`lux-engine -Ss NAME`, then `lux install NAME`) over building the same driver from the AUR; the
   printing helper installs it by itself when the printer is connected (`pkexec
   /usr/lib/luxos/printing/luxos-printing-helper sync`).
9. **Root shells are rarely needed.** Use `pkexec` for a single command that really needs root
   (wheel users may also use `sudo` in a terminal); don't start interactive root shells.

## Which tool for which task

| Task | Use | Notes |
|---|---|---|
| Install / remove / update software | `lux install`, `lux remove`, `lux update`; GUI: LuxOS Store (`luxos-store [search]`) | Store shows repo desktop apps, `[luxos-apps]`, `.lux` apps and Flathub search results (no AUR) |
| Automatic updates, update status | Software Update (`luxos-update`), `luxos-care status` | mode: `luxos-care mode carefree\|classic` (root) |
| Fix a locked package database / keys | `lux fix` | never delete `/var/lib/lux/db.lck` during an update |
| Add a repository, hold a package, mirrors | `/etc/lux/conf.d/NAME.conf` with `repo NAME` + indented `server URL`; `hold PKG` in `/etc/lux/lux.conf`; `lux mirrors` | check with `lux config check`; `multilib`: `sudo /usr/lib/lux/lux-config enable-repo multilib` |
| System health | `lux doctor` | |
| Drivers | Drivers (`luxos-drivers`), `lux drivers`, `luxos-hwdetect --report` | restart after installing |
| Wallpaper, light/dark/auto, Dock, top bar, boot splash | Desktop & Dock (`luxos-settings`); `luxos-appearance light\|dark\|auto\|toggle\|wallpaper FILE\|bar-opacity N\|dock-opacity N` | |
| Monitors, arrangement, main display, resolution, rotation, text size | Displays (`luxos-display-settings`); quick mode menu `luxos-displays menu` (Super+P) | changes revert after 15 s unless kept |
| Router admin page, network details, devices on the LAN, ping/DNS test | Router app (`luxos-router`), see [network-admin.md](network-admin.md) | router page opens only LAN addresses; never store router passwords |
| Keyboard layouts | Keyboard Layouts (`luxos-keyboard`) | system-wide via `localectl`, needs polkit |
| Keyboard shortcuts | Keyboard Shortcuts (`luxos-shortcuts`) | xfconf channel `xfce4-keyboard-shortcuts` |
| Battery, power mode, sleep, lid | Battery & Power (`luxos-power`) | |
| Battery Saver / Data Saver | `luxos-powersaver on\|off\|toggle\|status`, `luxos-datasaver on\|off\|toggle\|status` | also Control Center tiles |
| Bluetooth | Bluetooth (`luxos-bluetooth`) | |
| Fingerprint login | Fingerprint (`luxos-fingerprint`) | password always works too |
| Screen saver, lock delay | Screen Saver & Lock (`luxos-lock-settings`); lock now: `xflock4` | |
| Quick toggles (Wi-Fi, DND, dark mode, savers, brightness, volume) | Control Center (`luxos-control-center`) | |
| Printers, scanners | Printers & Scanners (`luxos-printers`, `--add`), Scanner (`luxos-scan`) | |
| Screenshots, screen recording | `luxos-screenshot` (`--screen`, `--portion`, `--window`, `--record-screen`, `--stop`) | never capture the screen without the user asking |
| Send files to phones / other PCs | LuxDrop (`luxdrop`) | LocalSend compatible |
| Find a place or address, plan a route (car/bike/walk/public transport), departures from a stop, places nearby, "where am I", show something on a map | `luxos-maps --json search\|reverse\|route\|transit-route\|timetable\|nearby\|where-am-i\|open …` | JSON on stdout; see [Maps and places](#maps-and-places) |
| Encrypted folder | Safe (`luxos-safe`; `luxos-safe status`, `luxos-safe lock`) | user unlocks in the dialog |
| Run untrusted software | Sandbox (`luxos-sandbox`) | see below |
| Why a downloaded program does not start, restore deleted files | Lux Guard (`luxos-guard scan FILE`, `luxos-guard list`, `luxos-guard restore PATH`) | see below |
| Back up to an external/network disk, restore an older version, restore everything on a new install | Backups (`luxos-backup status`, `luxos-backup list`, `luxos-backup restore [--from TIME] PATH`, `luxos-backup restore --all --source DISK`) | [backups.md](backups.md) |
| LuxAI account | LuxAI Account (`luxos-account`), `luxos-account login\|status\|logout` | |
| System info | About This Computer (`luxos-about`), `about os`, `fastfetch`, `cat /etc/os-release` | |
| Processes, force quit | System Monitor (`luxos-monitor`, Super+Alt+Esc) | |
| Feedback / bug report | `luxos-feedback` | |
| Other Xfce settings | `xfce4-settings-manager` (Super+,), `xfce4-power-manager-settings`, `/usr/bin/xfce4-keyboard-settings` (key repeat) | some Xfce dialogs are redirected to LuxOS apps |

## Common admin tasks

### Install an app

```bash
lux search inkscape          # find the exact name
lux info inkscape            # check what it is
lux install inkscape         # asks [Y/n], then for the admin password
```

Flatpak (if installed): `lux install org.gimp.GIMP`. A local file: `lux install ./app.lux` or
`lux install ./pkg.pkg.tar.zst`. LuxOS apps: `lux install lsl`, `lux install lux-code`,
`lux install lsl-ide`.

### Update the system

Run `lux update` (or press **Update Now** in Software Update). Afterwards: if lux says the kernel
was updated, suggest a restart; if it lists new config files, `lux configs`.

### Services

Standard systemd: `systemctl status NAME`, `pkexec systemctl restart NAME`. Do not disable LuxOS
units (`luxos-care-*`, `luxos-safe-guard`, `luxos-guard`, `earlyoom`) unless the user explicitly asks.

### Users, hostname, time zone

Standard Arch tools work (`hostnamectl`, `timedatectl`, `useradd -s /usr/bin/lsh`); new users get
the `lsh` shell, and members of `wheel` may use sudo. Keyboard layouts must go through Keyboard
Layouts (it also sets the login screen).

### Change a desktop setting from a script

Only inside the user's own graphical session: `xfconf-query -c CHANNEL -p PROPERTY -s VALUE`, or
the `luxos-appearance` / `luxos-displays` commands. Never run GUI tools, `xrandr` or xfconf changes
against a display that is not the user's active session. Reset with `xfconf-query … -r`.

## Maps and places

For places, addresses, distances, travel times, directions, public transport and nearby places use
the Maps command-line interface instead of scraping map or timetable websites. It prints one JSON
object, never opens a window (except `open`) and shares the app's caches and rate limits
(OpenStreetMap, Transitous and Overpass: at most 1 request per second for the whole computer – do
not loop over many places, never bulk-geocode, scan areas or poll departures).

```bash
luxos-maps --json search "Karlovo náměstí, Praha"          # results[]: name, address, lat, lon, geo_uri, osm_url
luxos-maps --json search "pharmacy" --near 50.08,14.42     # prefer results near a point
luxos-maps --json reverse 50.0757,14.4199                   # place: address of a point
luxos-maps --json route "Praha hlavní nádraží" "Pražský hrad" --mode walk   # car|bike|walk|transit
luxos-maps --json route here "Brno" --mode car              # "here" = the user's location (needs permission)
luxos-maps --json transit-route "Karlovo náměstí, Praha" "Pražský hrad"     # public transport, now
luxos-maps --json transit-route here "Brno hlavní nádraží" --time 2026-08-24T10:00:00+02:00 --arrive
luxos-maps --json timetable "Karlovo náměstí, Praha"        # next departures at stops within 500 m
luxos-maps --json timetable --stop-id cz-PID_U237Z3P --type arrivals   # one stop (stop_id from transit-route)
luxos-maps --json nearby here --category pharmacies         # nearest first; --radius M, --limit N
luxos-maps --json nearby 50.0757,14.4199 --name "Lidl"      # by name
luxos-maps --json where-am-i                                # lat, lon, accuracy_m, source (geoclue|ip)
luxos-maps --json open "Pražský hrad"                       # show a place in the Maps window
luxos-maps --json open --route here "Pražský hrad" --mode transit   # show a route in the Maps window
luxos-maps --render-preview route.json --size 480x270 --out /tmp/route.png   # route picture (PNG)
```

- `route` returns `distance_m`, `duration_s`, readable `distance`/`duration` and `steps[]`
  (`instruction`, `street`, `distance_m`, `lat`, `lon`). Instructions are in English; translate
  them for the user. `{"ok": false, "error": "NoRoute"}` means there is no route.
- `transit-route` returns `itineraries[]` (default 3): `departure_time`/`arrival_time` (`HH:MM`, in
  the local time zone of the stops – `timezone`), ISO `departure`/`arrival`, `duration`,
  `transfers`, `realtime`, `cancelled`, a ready English `summary` and `legs[]` (`mode_name`, `line`,
  `headsign`, `operator`, `from`/`to` with `name`, `platform`, `stop_id`, times, `delay_min`,
  `realtime`, `cancelled`). Mention delays (`delay_min` > 0), platform changes
  (`platform_changed`) and cancellations. `NoRoute` = no connection at that time; the coverage
  depends on open timetable data (some regions have none).
- `timetable` returns `connections[]` (`time`, `scheduled_time`, `delay_min`, `line`, `headsign`,
  `stop`, `platform`, `realtime`, `cancelled`, `operator`, `summary`). Times are live when
  `realtime` is true, otherwise planned.
- `nearby` categories: `restaurants`, `cafes`, `groceries`, `fuel`, `charging`, `parking`,
  `pharmacies`, `hospitals`, `hotels`, `attractions`, `public_transport`, `toilets`, `playgrounds`.
  Results: `name`, `distance`, `address`, `opening_hours`, `phone`, `website`, `osm_url`, `geo_uri`.
- Times for `--time`: ISO 8601 with a time zone (`2026-08-24T10:00:00+02:00`) or `HH:MM` (today,
  local time); omit for now. `--arrive` makes it the latest arrival.
- `{"ok": false, "error": "busy"}`: Transitous or the public Overpass server is overloaded (Maps then
  waits 30 s). Tell the user and try once later – do not retry in a loop.
- **Location is private.** `where-am-i` and `here` work only after the user allowed My Location in
  the Maps app; otherwise the answer is `{"ok": false, "error": "consent"}` – tell the user to open
  Maps and click the location button once. Never try other ways to find the user's location.
- Always mention the `attribution` field when you present the data: "© OpenStreetMap contributors"
  for map data, and for public transport "Transitous and its open-data providers"
  (`https://transitous.org/sources/`).
- A `geo:` link (`geo_uri`) opens in Maps for the user; `osm_url` opens openstreetmap.org in the browser.
- **Route card picture:** `route` and `transit-route` include `preview` (start, end, `bbox`
  south/west/north/east, `legs[]` with `color` and Google-encoded `polyline` + `precision`). Do not
  pass `preview` to the language model (it is only coordinates); save the JSON to a file and run
  `luxos-maps --render-preview FILE --size 480x270 --out FILE.png` to get the card image (uses the
  Maps tile cache, downloads only that picture's few tiles). `--itinerary N` draws another
  connection (needs `transit-route --geometry`).
- Details: [maps.md](maps.md#for-luxai-and-scripts-luxos-maps---json).

### Map tools for LuxAI (same as LuxAI on the phone)

The tool definitions of the LuxAI phone app map 1:1 to these commands, so a built-in desktop tool is
a thin wrapper (coordinates as `LAT,LON`):

| Tool | Command |
|---|---|
| `map_geocode(query, country_codes?, language?, limit 1-10 = 5)` | `search QUERY --limit N` |
| `map_reverse(latitude, longitude, zoom 3-18?, language?)` | `reverse LAT,LON` |
| `map_nearby(latitude, longitude, category?, query?, radius_meters 50-10000 = 1500, limit 1-50 = 20)` | `nearby LAT,LON --category C --name QUERY --radius R --limit N` |
| `map_route(start_latitude, start_longitude, end_latitude, end_longitude, travel_mode driving\|walking\|cycling = driving)` | `route A B --mode car\|walk\|bike` |
| `map_transit_route(start_*, end_*, time?, arrive_by = false, max_transfers 0-8 = 3, limit 1-5 = 3)` | `transit-route A B --time T [--arrive] --max-transfers N --limit N` |
| `transit_timetable(latitude, longitude, time?, type departures\|arrivals, radius_meters 25-2000 = 500, limit 1-12 = 8, language?)` | `timetable LAT,LON --type TYPE --time T --radius R --limit N` |
| `current_location()` | `where-am-i` (only with the user's permission in Maps) |

Rules from the phone tool descriptions: resolve names to coordinates first (`map_geocode`) and
never guess coordinates; inspect alternatives for ambiguous places; route durations are estimates
without live traffic; transit times are time-dependent (omit `time` for now, otherwise ISO 8601
with offset); `current_location` only when the user explicitly asks for something near them or
from where they are – never proactively, repeatedly or in the background.

`country_codes` and `language` of `map_geocode`/`map_reverse` are not needed on LuxOS (Maps uses
the system language and prefers places near the map/the `--near` point).

LuxAI has no dedicated map tool yet; in Agent mode run these commands with `run_command` (they only
read data, except `open`, which shows a window, and `--render-preview`, which writes the PNG).

## Sandbox for untrusted programs

`luxos-sandbox` gives each user an isolated minimal Arch system at `/dev/sandbox/<user>` (a link
to `/var/lib/luxos/sandbox/<user>`), started with bubblewrap, seccomp and no access to the user's
files, D-Bus, sound or the local network.

```bash
luxos-sandbox create                    # once, asks for the admin password
luxos-sandbox install firefox           # Arch [core]/[extra] packages, inside the sandbox
luxos-sandbox run --gui --net firefox   # own Xephyr window, internet only
luxos-sandbox run ./downloaded-file     # the file is copied in, never mounted
luxos-sandbox reset --yes               # wipe and recreate
```

Use `luxos-sandbox install`, not `lux`, for sandbox apps. It is not a VM – kernel exploits can
escape; for clearly malicious software recommend a virtual machine. Details: [sandbox.md](sandbox.md).

## Lux Guard

Lux Guard checks programs and scripts from downloads, attachments and USB drives when they start.
"Permission denied" for such a file usually means Lux Guard refused it: run `luxos-guard scan FILE`
(reasons, origin) and `journalctl -t luxos-guard -n 20`, then explain the reason. Critical files
(wiping the disk or home, ransomware, hidden code) run only in the Sandbox – recommend **Run in
Sandbox** or deleting the file; never stop the service, never use `luxos-guard allow --force` and
never copy or rewrite the file to get around the check. Deleted or encrypted files can be restored
from hourly snapshots: `luxos-guard snapshots`, `luxos-guard restore [--from TIME] [--overwrite] PATH`
(as the user). Details: [guard.md](guard.md).

## Safe (encrypted folder)

`/safe/<user>` is unlocked only by the user in the Safe dialog (`luxos-safe unlock --open`). While
unlocked, every process of the same user can read it, so do not read Safe files unless the user asks.
It always locks on sleep and logout. Never `chattr`, `chmod` or force-unmount anything under `/safe`.
Details: [safe.md](safe.md).

## LSL on LuxOS

LSL (Lux Simple Lang) is installed with `lux install lsl` (`/usr/bin/lsl`). Run `lsl file.lsl`,
compile `lsl compile file.lsl out`, help `lsl help`, offline manual `lsl man`. In the `lsh` shell
LSL lines can be typed directly (`print 6 * 7`). The language reference is in the LSL collection,
starting at [LSL overview](../lsl/overview.md).

## Things that are different from Arch Linux

- No `pacman`, no `yay`/`paru` needed – `lux` covers repositories, Flathub, community/AUR (sandbox) and `.lux`.
- No `/etc/pacman.conf`: configuration is `/etc/lux/lux.conf` (`key value` lines, `repo NAME` blocks,
  `hold` instead of `IgnorePkg`), database `/var/lib/lux`, cache `/var/cache/lux/pkg`, log
  `/var/log/lux.log`, keyring `/etc/lux/keyring`. The engine is based on Arch's libalpm (pacman code).
- Default shell is `lsh` (bash-compatible). `~/.lshrc` instead of `~/.bashrc`.
- Kernel is `linux-luxos` (own LuxOS kernel; older installs switch from `linux-zen` automatically); initramfs built with `mkinitcpio`; Btrfs subvolumes `@`, `@home`, `@log`,
  `@cache`.
- Desktop defaults are in `/etc/xdg/luxos`, LuxOS state files in `~/.config/luxos`
  ([configuration.md](configuration.md)).
- earlyoom, not systemd-oomd, handles low memory; zram is the swap.
- Updates may run automatically in the background (LuxOS Care); if the package database is locked,
  wait instead of forcing.

## Manual pages

The same documentation is installed as manual pages (generated from these files, so they never
differ): `man luxos` (overview: what is where), `man lux` and `man lux.conf` (packages and
`/etc/lux/lux.conf`), `man luxos-care`, `man luxos-sandbox`, `man luxos-safe`, `man luxos-guard`, `man luxos-backup`,
`man luxdrop`, and for LSL `man lsl` (command line), `man 7 lsl` (language and standard library)
and `man lslc`. Suggest them to users who prefer the terminal; `man -k luxos` lists them.

When something fails, follow [troubleshooting.md](troubleshooting.md) and report the exact error
message to the user instead of guessing.
