# Printing and Scanning

LuxOS sets up printers and scanners without asking. Printers on the network and on USB are added
automatically, without drivers where possible (IPP Everywhere / AirPrint / Mopria, and ipp-usb for
USB). Classic USB printers get the best installed driver. Scanners work through SANE with eSCL
(`sane-airscan`). All of this is in the package `luxos-printing`, which also provides the apps
**Printers & Scanners** (`luxos-printers`) and **Scanner** (`luxos-scan`).

## Components

| Part | Path | Role |
|---|---|---|
| CUPS | `cups.socket` | print server, started on first use |
| Avahi + nss-mdns | `avahi-daemon.service` | finds network printers and scanners; `.local` names |
| ipp-usb | started by udev | makes IPP-over-USB printers look like network printers |
| watcher | `luxos-printing-watch.service` → `/usr/lib/luxos/printing/luxos-printing-watch` | listens to `avahi-browse` for new `_ipp._tcp` and `_uscan._tcp` services (no polling) and runs the helper |
| USB trigger | `/usr/lib/udev/rules.d/70-luxos-printing.rules` → `luxos-printing-sync.service` | runs the helper when a USB printer or scanner is plugged in |
| helper (root) | `/usr/lib/luxos/printing/luxos-printing-helper` | creates the queues and installs drivers |
| notifications | `/usr/lib/luxos/printing/luxos-printing-notify` | "Printer “X” is ready" etc. in the user session |
| mDNS in nsswitch | `/usr/lib/luxos/printing/luxos-nsswitch-mdns` (+ libalpm hook) | adds `mdns_minimal` to the `hosts:` line of `/etc/nsswitch.conf` |
| polkit | `org.luxos.printing.manage` | lets the active user run the helper through `pkexec` without a password |

The package's install script enables `cups.socket`, `avahi-daemon.service` and
`luxos-printing-watch.service`. The print-queue applet (system-config-printer-applet) is disabled
on purpose.

## How printers are added

`luxos-printing-helper sync` finds devices and handles each kind like this:

- **Network or IPP-USB printers with driverless support** get a queue with `lpadmin -m everywhere`.
  Queues are not shared and use `printer-error-policy=retry-job`.
- **Classic USB printers** get the best matching installed PPD driver. If none fits, the helper
  installs `hplip` (HP) or `gutenprint` (others) through `lux` (`lux_alpm.py`; it waits if the
  package database is busy). If that is not possible either, it uses a generic PostScript or PCL
  driver.
- Printers whose only driver is in the AUR (Samsung SPL/QPDL lasers such as the Xpress M2020/M2026
  series; `luxos_printing.AUR_DRIVERS`) get no queue. AUR packages cannot be built as root, so the
  notification "needs a driver from the manufacturer" has an **Install Driver** button: it opens
  Terminal with `lux install samsung-unified-driver-printer` and then runs
  `pkexec luxos-printing-helper sync`. The Samsung PPD is per series ("M2020 Series" covers M2026).
  "Add" in Printers & Scanners offers the same.
- Some HP models need HP's proprietary plugin. The notification then says: "Open Terminal and run:
  hp-plugin".
- A network printer without driverless support gets no queue automatically. The notification says
  "needs to be set up… Open Printers & Scanners and choose Advanced…".
- With no internet, a needed driver is installed later ("LuxOS will set it up automatically once
  you are connected to the internet").

The helper remembers the queues it created in `/var/lib/luxos-printing/state.json`. It never
touches queues created by someone else, and it does not re-add a printer you removed.

Other helper commands (root, or through `pkexec`):

```
luxos-printing-helper discover        # JSON of all found printers
luxos-printing-helper add KEY         # add one from discover (also a removed one)
luxos-printing-helper remove QUEUE    # remove (and do not add again)
luxos-printing-helper default QUEUE   # default printer
luxos-printing-helper resume QUEUE    # re-enable a paused queue
luxos-printing-helper cancel ID       # cancel a print job (any user)
```

## Printers & Scanners app

Run `luxos-printers` (or `luxos-printers --add` to open Add Printer, `--scanner` to select the
first scanner). It is in Launchpad and Settings.

- **Printers** list with state: Ready, Printing…, N documents waiting, Paused, "Offline – make
  sure the printer is turned on". Ink and toner levels, and the print queue with per-job Cancel
  and Cancel All.
- Per-printer actions: **Default printer**, **Print Test Page**, **Resume**, **Remove Printer…**.
- **Add Printer…** is a fallback for when the printer was not added automatically. It shows
  "Printers nearby" (USB and network) with an Add button. **Advanced…** opens
  `system-config-printer` for printers that need special setup (LPD, Windows sharing, manual
  drivers).
- **Scanners** tab: Kind, Quality, Source, Preview, Scan. It saves as a PDF document or JPEG
  pictures and supports several pages.

## Scanner app

Run `luxos-scan` (optionally `--device <SANE device>`). It is a simple scanner with one Scan button.

- The scanner is picked automatically. A list appears only when there are several. eSCL is
  preferred over WSD when the same scanner shows up through several backends.
- **Scan as** Document (300 dpi) or Photo (600 dpi). Colours: Colour or Black & white. Paper size.
  Source: Glass (flatbed), Document feeder, or Document feeder, both sides.
- Pages can be reordered and removed, and "Scan Another Page" adds more. Save as a PDF document
  (multi-page), JPEG picture or PNG picture, or **Print…**.
- Files are named like `Scan 2026-10-22 14.03` and saved to the Documents folder
  (`xdg-user-dir DOCUMENTS`, otherwise `~/Documents`). Temporary pages are kept in
  `~/.cache/luxos-scan`.
- Scanning runs `scanimage` in a background thread. Cancel sends SIGTERM.
- The laptop camera (SANE `v4l` backend) is never listed as a scanner.
- With no scanner found the app keeps looking every few seconds, so a scanner switched on later
  appears by itself. The refresh button in the title bar searches again at any time.

## Troubleshooting

- **Printer not added**: make sure it is on and on the same network. Open Printers & Scanners ›
  Add Printer… › Search Again. Check the services:
  `systemctl status cups.socket avahi-daemon luxos-printing-watch`, and the log:
  `journalctl -u luxos-printing-watch -u luxos-printing-sync`.
- **See what the system finds**: `avahi-browse -rt _ipp._tcp` (network printers),
  `lpstat -v` (queues), `pkexec /usr/lib/luxos/printing/luxos-printing-helper discover`.
- **`.local` names do not resolve**: the `hosts:` line of `/etc/nsswitch.conf` must contain
  `mdns_minimal`. Repair (root): `/usr/lib/luxos/printing/luxos-nsswitch-mdns`.
- **Printer "needs a driver"**: connect to the internet. The helper installs `hplip` or
  `gutenprint` itself. You can also install them by hand: `lux install hplip`.
- **HP printer needs a plugin**: run `hp-plugin` in a terminal.
- **Printer not driverless (old network printer)**: use Advanced… (system-config-printer).
- **Paused printer**: the Resume button in the app, or `luxos-printing-helper resume QUEUE`.
- **Scanner not found**: `scanimage -L`. The Scanner app says "Scanning support is not installed"
  when SANE is missing (install `luxos-printing`). It says "The scanner does not respond" when the
  device is off or busy.
- If you have a firewall, network printers need mDNS (UDP 5353). LuxOS does not ship a firewall by
  default.
