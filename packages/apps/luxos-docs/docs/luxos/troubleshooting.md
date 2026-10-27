# Troubleshooting LuxOS

Recipes for common problems, collected from the LuxOS tools' own error handling. Each section
names the app or command to use first. Commands that change the system ask for the
administrator password themselves (sudo in a terminal, a polkit dialog otherwise).

## First checks

```bash
lux doctor                 # failed services, .luxnew files, disk usage, orphans, updates, kernel, journal errors
luxos-care status          # automatic updates / repairs state
systemctl --failed         # failed system services
journalctl -b -p err       # errors since boot
luxos-hwdetect --report    # detected hardware and required driver packages
cat /etc/os-release        # LuxOS version
```

## "pacman: command not found"

Expected: LuxOS has no `pacman` command. Use `lux` – the shell prints the matching command
(`pacman -Syu` → `lux update`, `pacman -S x` → `lux install x`, `pacman -Rns x` → `lux remove x`).
Scripts or AUR helpers that call `pacman` directly do not work; `makepkg` is configured to use
the internal engine (`/usr/lib/lux/alpm/bin/lux-engine`) automatically. There is also no
`/etc/pacman.conf`: repositories, `hold` (instead of `IgnorePkg`) and mirrors are in
`/etc/lux/lux.conf` and `/etc/lux/mirrorlist`. See [lux-engine-and-repos.md](lux-engine-and-repos.md).

## "error in the configuration" (lux.conf)

```
lux: error in the configuration: /etc/lux/lux.conf:12: unknown key 'paralel-downloads' (did you mean 'parallel-downloads'?)
✗ lux will not run until the configuration is fixed (/etc/lux/lux.conf). Check it with: lux config check
```

Open the file (`lux config edit`), fix the reported line and run `lux config check`. Typical
causes: pacman syntax (`[options]`, `Key = value`) – lux.conf uses `key value` and `repo NAME`
blocks; a repository key (`server`, `mirrors`) that is not indented under `repo NAME`; an empty or
missing mirror list. Until fixed, lux, the Store and LuxOS Care do not install anything; the engine
keeps the last working configuration. Format: [package-management.md](package-management.md#configuration-etcluxluxconf).

## Old pacman files after updating from LuxOS 0.9.5

`/var/lib/pacman`, `/var/cache/pacman/pkg`, `/etc/pacman.d/gnupg`, `/var/log/pacman.log` are
links to the new `/var/lib/lux`, `/var/cache/lux/pkg`, `/etc/lux/keyring`, `/var/log/lux.log` until
the next restart; then lux removes them together with `/etc/pacman.conf` (copies stay in
`/var/lib/lux/migrated-from-pacman/`). `lux doctor` mentions it; check with
`/usr/share/libalpm/scripts/lux-engine-migrate status`, finish now with
`sudo /usr/lib/lux/lux_alpm.py migrate --now`. `/etc/pacman.d/mirrorlist` stays while the unneeded
`pacman-mirrorlist` package is installed – `lux autoremove` offers to remove it.

## Updates fail

| Symptom / message | Fix |
|---|---|
| "The package database is locked" / Store: "Another app is installing software right now" | Wait – LuxOS Care, the Store or another `lux` may be running (lux waits up to 5 minutes by itself). If nothing is running: `lux fix`. Never delete `/var/lib/lux/db.lck` while an update runs. |
| "A package signature could not be verified" | `lux fix` (re-initializes and re-populates keys, reinstalls `archlinux-keyring` and `luxos-keyring`). Check the clock: `timedatectl` – enable sync with `timedatectl set-ntp true`. |
| "Some packages could not be downloaded" | check the internet connection; `lux mirrors` picks fast mirrors; lux already retries 3× |
| "Not enough free disk space" | `lux clean` (cache, offers `autoremove`); check `df -h /` |
| "A downloaded package is damaged" | try again; if it repeats, `lux clean` and retry |
| file conflict ("… exists in filesystem") | `lux owns <file>` shows the owner; files not owned by any package were created manually – move them away only after checking |
| "Dependencies can not be satisfied" / "unresolvable package conflicts" | usually a partial update – run a full `lux update` first (since 0.9.2 old installs update cleanly) |
| `pyalpm` problems after an Arch Linux engine update | lux falls back to the internal `lux-engine` tool automatically; `lux doctor` reports when `lux-engine` is behind Arch; diagnose with `/usr/lib/lux/lux_alpm.py --verbose available`, force with `LUX_BACKEND=engine lux update` |
| new config files from updates | `lux configs` (review `.luxnew`/`.luxsave`: use new, keep yours, edit) |
| "The package manager configuration has an error" | `lux config check`, see above |
| "Kernel was updated - restart to use it." | restart |

AUR builds must run as a normal user (never `sudo lux install <aur-package>`) and need `git`,
`base-devel` and `jq`. Details: [package-management.md](package-management.md).

## Automatic updates do not happen

Open **Software Update** (`luxos-update`); it shows why an update is waiting:

- metered connection / **Data Saver** on → turn Data Saver off (`luxos-datasaver off`) or press
  **Update Now** (manual updates ignore metered and battery conditions),
- battery below 40 % without charger → connect the charger,
- no internet.

After failures LuxOS Care waits 1 h, 2 h, 4 h … up to 24 h and notifies after 3 failures. Logs:
`journalctl -u luxos-care-update.service`, history `/var/lib/luxos-care/history.jsonl`
(`luxos-care history`). Classic mode only notifies. See [care-updates.md](care-updates.md).

## The computer does not start after an update

- After 3 failed starts of a new kernel the boot loader uses **"LuxOS (previous kernel)"**
  automatically; it can also be chosen in the boot menu (systemd-boot or GRUB). With an EFI
  partition shared with another system the choice is manual.
- When LuxOS runs again, LuxOS Care rebuilds the initramfs / DKMS modules or retries the new
  kernel; check **Software Update › System health**.
- "The boot partition is full." – the previous kernel cannot be kept; free space on `/boot`.
- An interrupted update is finished automatically by LuxOS Care (or run `lux update`).
- Something else broke after an update: hold **Space** (GRUB: hold **Shift** or press **Esc**) while the computer starts and
  choose **"LuxOS (before update of …)"**. If it works, keep it with **Keep this version** /
  `lux rollback`. **"LuxOS Recovery"** in the same menu checks the disk, restores a snapshot,
  repairs the settings from `/etc/luxos/system.lsl` or reinstalls LuxOS keeping `/home` and
  accounts. See [care-updates.md](care-updates.md).

## A setting changed by itself (printer gone, lid, network, service off)

All important settings are in `/etc/luxos/system.lsl` (written by the installer). `lux system diff`
lists what differs from the file and **`sudo lux system fix`** returns the system to it (it shows
the changes, asks and takes a snapshot first; the network connection in use is changed only after a
separate question). The same is in **LuxOS Recovery › Repair the settings**. See
[system-config.md](system-config.md).

## The desktop froze (mouse moves, but clicks and typing do nothing)

Do not power off the computer. Press **Ctrl+Alt+F3**, sign in with your user name and password and run:

```
luxos-unfreeze
```

It saves a report to `~/.local/share/luxos/freeze-reports/` and restarts the window manager and the
panel; open apps keep running. Go back with **Ctrl+Alt+F1** (or F7). `luxos-unfreeze --report` only
saves the report. When the display server or the window manager stops responding for 30 s,
LuxOS saves such a report automatically. Send the newest report with your bug report.

## An app misbehaves

Settings › **Reset App Settings** (`luxos-app-reset`) moves the app's settings to a backup and the
app starts as if just installed; see [settings-apps.md](settings-apps.md).

## Drivers and graphics

- Open **Drivers** (`luxos-drivers`) or run `lux drivers`; install the recommended drivers and
  restart. If kernel headers do not match, the Drivers app updates the system first.
- Legacy NVIDIA drivers (580xx for Maxwell/Pascal/Volta, optional 470xx for Kepler) come only
  from the online `[luxos]` repository; without internet during installation nouveau stays until
  they are installed from Drivers.
- Hybrid graphics: run an app on the NVIDIA GPU with `prime-run <app>`.
- Check the loaded driver: `lsmod | grep -E 'nvidia|nouveau'`.
- A notification "Additional drivers are available" appears ~45 s after login when new hardware
  needs drivers; "Don't remind me" stores the choice in `~/.config/luxos/drivers-ignored`.

Details: [drivers.md](drivers.md).

## Display and monitors

- Wrong mode with a second monitor: `Super+P` (or the Display key) → Extend, Mirror, Only
  external screen, Only this computer's screen. The mode is saved in `~/.config/luxos/displays-mode`.
- Windows lost off-screen: `luxos-displays rescue`.
- Re-apply saved monitor settings: `luxos-displays auto` (also runs at login and on hotplug).
- Resolution / refresh / rotation: **Displays** (`luxos-display-settings`); unconfirmed changes
  revert after 15 s. Saved settings: `~/.config/luxos/displays.json`.
- Monitor without backlight control (desktop monitor, VM): brightness is software
  (`luxos-displays brightness 10..100`, saved in `~/.config/luxos/brightness`).
- Text too small/large: Displays › text size (Xft DPI in xfconf `xsettings`).

See [settings-apps.md](settings-apps.md#displays).

## Sound

- New Bluetooth/USB/HDMI headphones or speakers become the output automatically (PipeWire rule
  `50-luxos-switch-on-connect.conf`); after disconnecting, sound returns to the previous device.
- Choose devices and per-app volume in the mixer: click the sound icon in the top bar or run
  `pavucontrol`.
- From a terminal: `pactl set-sink-volume @DEFAULT_SINK@ 50%`, `pactl set-sink-mute @DEFAULT_SINK@ toggle`,
  `pactl list short sinks`.
- Laptop speakers/microphone missing on Intel laptops: `luxos-hwdetect --report` should list
  `sof-firmware` – install via Drivers and restart.
- Standard PipeWire restart (user services): `systemctl --user restart pipewire pipewire-pulse wireplumber`.

## Bluetooth

- Use **Bluetooth** (`luxos-bluetooth`): turn on, then **Connect** pairs, trusts and connects.
- "No Bluetooth adapter was found" – no adapter or it is blocked; check `rfkill list` and
  `systemctl status bluetooth`.
- Pairing started from the phone/headphones is answered by the agent inside `luxos-hub`
  (blueman-applet is disabled); if it fails, make sure `luxos-hub` is running (log out and in).
- "Make sure the device is on, close by and in pairing mode".

## Printing and scanning

- Printers are added automatically. Otherwise **Printers & Scanners** (`luxos-printers`) ›
  Add Printer… › Search Again.
- Services: `systemctl status cups.socket avahi-daemon luxos-printing-watch`; log
  `journalctl -u luxos-printing-watch -u luxos-printing-sync`.
- What is visible: `lpstat -v`, `avahi-browse -rt _ipp._tcp`.
- `.local` names do not resolve: `/etc/nsswitch.conf` needs `mdns_minimal`; repair with
  `/usr/lib/luxos/printing/luxos-nsswitch-mdns` (root).
- Driver needed: connect to the internet (hplip/gutenprint are installed automatically) or
  `lux install hplip`; some HP models need `hp-plugin`. Old non-driverless printers: Advanced…
- A printer the user removed is not re-added automatically.
- Scanner not found: `scanimage -L`; open **Scanner** (`luxos-scan`).

See [printing-scanning.md](printing-scanning.md).

## Keyboard layout

- Change layouts only in **Keyboard Layouts** (`luxos-keyboard`) → *Apply to All Users and the
  Login Screen*; it writes `/etc/X11/xorg.conf.d/00-keyboard.conf` and `/etc/vconsole.conf`.
- Layout differs in one account: that account has own Xfce layouts
  (`xfconf-query -c keyboard-layout -p /Default/XkbDisable` is `false`); press Apply in Keyboard
  Layouts.
- Cannot switch: check "Switch layouts with" (default both Shift keys together; max 4 layouts).
- Inspect: `localectl status`, `setxkbmap -query`.

Shortcut conflicts or a broken shortcut: **Keyboard Shortcuts** (`luxos-shortcuts`) › Restore
Default / Restore All Defaults…. See [keyboard.md](keyboard.md).

## Network

- "!" in the top bar: connected but no internet, or a captive portal; click it to open the sign-in
  page. Check with `nmcli -t -f CONNECTIVITY,STATE general`.
- Wi-Fi on/off: Control Center › Wi-Fi (`nmcli radio wifi on`).
- Broadcom Wi-Fi without driver: Drivers (`broadcom-wl-dkms`), restart.

## Desktop

- Dock missing: run `luxos-dock` (it stops restarting Plank after 5 quick crashes).
- Wrong look after a change: `luxos-appearance light` / `dark` / `auto`; Dock defaults:
  `dconf reset -f /net/launchpad/plank/docks/dock1/`.
- Reset one Xfce setting: `xfconf-query -c <channel> -p <property> -r`. See
  [configuration.md](configuration.md#resetting-to-defaults).

## Apps closed with "Memory is running low"

earlyoom closed the biggest process because RAM < 4 % and swap < 8 %. Close heavy apps/tabs, or
check memory with System Monitor (`luxos-monitor`). See
[power-and-performance.md](power-and-performance.md#low-memory-protection-earlyoom).

## A downloaded program does not start (Lux Guard)

- "Permission denied" or a **Lux Guard** dialog: the file came from outside (Downloads, USB,
  attachment). `luxos-guard scan FILE` shows why; `journalctl -t luxos-guard -n 20` the decisions.
- Risky (unknown) file you trust: **Run Anyway** in the dialog, or `luxos-guard allow FILE`.
- Critical file: it runs only in the Sandbox (**Run in Sandbox**). Delete it unless you are sure.
- No dialog appears and risky files are refused: the session helper is not running –
  `luxos-guard status`; log out and in, or start `luxos-guard-agent &`.
- Files deleted or encrypted: `luxos-guard restore PATH` or Lux Guard › Restore files. See
  [guard.md](guard.md).

## Safe, Sandbox, LuxAI, LuxDrop

- **Safe** will not lock: "These apps keep files in the Safe open: …" – close those apps, then
  `luxos-safe lock`. A forgotten Safe password cannot be recovered. See [safe.md](safe.md).
- **Sandbox** damaged ("The sandbox is damaged …"): `luxos-sandbox reset --yes`. See
  [sandbox.md](sandbox.md).
- **LuxAI** says the session expired / 401: `luxos-account login`; check with
  `luxos-account status`. "The monthly Flash limit is used up" – switch to Lite or wait for the next
  month. See [luxai-account.md](luxai-account.md).
- **LuxDrop** finds nothing: `systemctl status avahi-daemon`; on guest Wi-Fi use Connect by
  address; "port 47923 is in use" – another LuxDrop instance runs. See [luxdrop.md](luxdrop.md).

## Reporting a bug

**Feedback** (`luxos-feedback`, also in About This Computer › Send Feedback…) sends a report to the
LuxOS author. See [apps.md](apps.md#feedback).

## LuxOS does not start (emergency mode)

The initramfs hook `luxos-boot` (package luxos-tweaks, added to every systemd initramfs by
`/etc/mkinitcpio.conf.d/zz-luxos-boot.conf`) makes a failed start visible:

- A wrong disk password shows "Wrong password, try again." on the splash screen and the console;
  attempts are unlimited (`systemd-cryptsetup@` restarts after 3 failures), so a typo never ends
  in emergency mode. While the password prompt is open there is no time limit.
- Outside the password prompt LuxOS waits at most 90 s for the system disk (kernel parameter
  `luxos.root_wait=SECONDS`), then starts emergency mode.
- In emergency mode (initramfs or the started system) `luxos-boot-failure` saves the start-up log
  to the EFI system partition as `\EFI\LuxOS\boot-failure-<time>.log` (the last 5 are kept) and
  prints what happened and what to do. From another system the logs are e.g. in
  `/boot/efi/EFI/LuxOS/` (Debian/Ubuntu) or `/efi/EFI/LuxOS/` (LuxOS).

## "Incorrect password" although the password is right (account temporarily locked)

LuxOS practically never locks an account: only a brute-force rate of **20 failed logins within 30 seconds** (impossible by hand, PAM waits ~2 s after each failure) locks it for **1 minute** (`pam_faillock`;
Arch's default of 3 failures / 10 minutes is replaced by `luxos-tweaks` via
`/usr/lib/luxos/luxos-faillock-setup`, values in `/etc/security/faillock.conf`). A cancelled
unlock dialog (for example while waiting for a fingerprint) also counts as a failure. While the
account is locked even the correct password is refused; the login screen says "Too many failed
attempts. The account is locked for N min". Check or clear the counter as root:
`faillock --user NAME` and `faillock --user NAME --reset`.
