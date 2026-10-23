# LuxOS Apps

LuxOS ships its own small apps, mostly in the `luxos-desktop` package (GTK 3, Python or bash,
`/usr/bin/luxos-*`). All of them follow the system language (`luxos-i18n`: English plus 12
translations) and the light/dark mode.

## Overview

| App (name in Launchpad) | Command | What for |
|---|---|---|
| About This Computer | `luxos-about` | version, hardware, links to What's New, Tour, Feedback, Software Update |
| Welcome to LuxOS | `luxos-welcome` | first steps: dark mode, Store, update, LuxAI sign-in, Tour, Shortcuts |
| LuxOS Tour | `luxos-tour` | short illustrated tour of where everything is |
| What's New | `luxos-whats-new` | news of the installed LuxOS version |
| Calculator | `luxos-calculator` | basic and scientific calculator |
| Calendar | `luxos-calendar` | calendar under the clock, events with reminders (.ics) |
| Camera | `luxos-camera` | photos and videos from the webcam |
| System Monitor | `luxos-monitor` | performance charts, quit frozen apps |
| Screenshot | `luxos-screenshot` | screenshots and screen recording |
| Feedback | `luxos-feedback` | send a bug report or an idea to the author of LuxOS |
| Control Center | `luxos-control-center` | quick settings ([desktop.md](desktop.md#control-center)) |
| Search / Launchpad | `luxos-search` / `luxos-launchpad` | find and launch apps ([desktop.md](desktop.md#launchpad-and-search)) |
| Toggle Dark Mode | `luxos-appearance toggle` | switch light/dark |
| LuxDrop | `luxdrop` | send files nearby ([luxdrop.md](luxdrop.md)) |
| Printers & Scanners, Scanner | `luxos-printers`, `luxos-scan` | [printing-scanning.md](printing-scanning.md) |
| Software Update | `luxos-update` | updates ([care-updates.md](care-updates.md)) |
| LuxOS Store | `luxos-store` | install apps ([store.md](store.md)) |
| Safe, Sandbox | `luxos-safe`, `luxos-sandbox` | [safe.md](safe.md), [sandbox.md](sandbox.md) |
| Settings apps | `luxos-settings`, `luxos-display-settings`, … | [settings-apps.md](settings-apps.md) |

Standard apps that are installed by default: Firefox, Files (Thunar), Terminal (xfce4-terminal with
the `lsh` shell), Mousepad (text editor), Ristretto (images), Evince (documents), Xarchiver,
Celluloid (video). In the top bar, some of them get short names such as "Files", "Terminal", "Text
Editor", "Image Viewer" and "Document Viewer".

## About This Computer

Run `luxos-about`, or use the LuxOS logo menu (first favourite). It shows the LuxOS version and
build ("Rolling release · based on Arch Linux"), computer model, processor, memory, graphics,
storage, battery, kernel and the `lsh` version. Buttons: What's New, LuxOS Tour, Send Feedback…,
Software Update (`luxos-update`, or `lux update` in a terminal if LuxOS Care is missing), Close.

## Welcome to LuxOS

Run `luxos-welcome`. It opens on first login (after the Tour), and on the live ISO it opens right
away. It lists the key shortcuts. Buttons:

- Install LuxOS (live ISO only);
- Light Mode / Dark Mode;
- LuxOS Store;
- Update (runs `lux update` in a terminal);
- Sign in to LuxAI (only while not signed in);
- LuxOS Tour;
- Shortcuts (`luxos-shortcuts`).

After it closes, it writes `~/.config/luxos/welcome-done`.

## LuxOS Tour

`luxos-tour` opens the tour, `luxos-tour --page N` opens page N, and `--first-run` is used at the
first login (it runs only once; `~/.config/luxos/tour-done`). Pages:

1. Welcome.
2. The Menu Bar.
3. The Dock.
4. Launchpad and Search (with LuxAI questions).
5. Files and Safe.
6. Installing Apps (Store, `lux`).
7. Light, Dark or Auto.
8. Share and Print (LuxDrop, Printers & Scanners).
9. Help and Shortcuts.

Buttons open the apps, and "Show on Screen" highlights the real top bar or Dock (needs the
compositor).

## What's New

`luxos-whats-new` shows the news of the current version. The notes are in
`/usr/share/luxos/whats-new/<version>.json` (package `luxos-branding`), with English and Czech text.
After an update to a new LuxOS version, `luxos-whats-new --auto` runs at login and shows the news
of every version since the last one seen (`~/.config/luxos/whats-new-seen`). New users see the
Tour instead (`--mark-seen`). The installed version is in `/usr/lib/luxos/version`.

## Calculator

Run `luxos-calculator`, or press the Calculator key. It uses decimal arithmetic, so 0.1 + 0.2 =
0.3, and it respects operator precedence and parentheses.

- Basic mode is **Ctrl+1**, scientific mode is **Ctrl+2**. Scientific mode adds powers, roots,
  logarithms, trigonometric functions (degrees/radians), factorial and constants.
- Keyboard: digits, `+ - * / ^ ( )`, Enter, Backspace, Esc, `%`, Ctrl+C and Ctrl+V.

## Calendar

Click the clock in the top bar (`luxos-calendar-toggle`), or run `luxos-calendar`.

- Views: **Day** (big date and today's events as coloured cards), **Month** (a dot marks a day
  with events, click a day to see them) and **Year** (click a month to open it).
- **+ / New Event**: title, date, start and end or All day, Repeat (Never, Daily, Weekly, Monthly,
  Yearly, or Custom for imported rules), colour, "Remind 10 minutes before". Click an event card to
  edit or delete it.
- Data: `~/.local/share/luxos/calendar/events.ics` (iCalendar RFC 5545). Other `*.ics` files in
  that folder are loaded **read-only**, so you can drop an export from Google Calendar there.
  Supported: VEVENT with SUMMARY, DTSTART/DTEND/DURATION, time zones, RRULE (DAILY, WEEKLY,
  MONTHLY, YEARLY with INTERVAL, COUNT, UNTIL, BYDAY, BYMONTHDAY, BYMONTH), EXDATE, RECURRENCE-ID,
  COLOR, VALARM. Unknown properties are kept unchanged.
- Reminders are sent as desktop notifications by the calendar running inside `luxos-hub` (or
  `luxos-calendar --background`).

## Camera

Run `luxos-camera`. It is a Photo Booth-style webcam app built on GStreamer (v4l2).

- Photo or Video, a mirrored preview (toggle "Mirror preview"), Choose camera when there are
  several, and "Take the picture after 3 seconds".
- Photos (JPEG) are saved to `$(xdg-user-dir PICTURES)/Camera`, and videos (WebM VP8 + Opus, or MP4
  if x264enc is available) to `$(xdg-user-dir VIDEOS)/Camera`. "Open last capture" opens the latest
  file.
- Possible errors: "No camera found", "The camera is being used by another app", "Camera access is
  not allowed", or a missing `gst-plugins-good`. Webcams that need special drivers (Intel
  IPU6/IPU7) are handled by [drivers.md](drivers.md).

## System Monitor

Run `luxos-monitor`, or press **Super+Alt+Esc** or **Ctrl+Shift+Esc**.

- Cards with gauges and a 60-second chart for Processor, Memory, Disk and Network (download and
  upload).
- Below them, the open apps with icons and a **Quit** button. If an app does not respond, it offers
  "Force Quit" (unsaved changes are lost).
- A switch shows "All processes" (a technical list with processor and memory use).
- The data is read straight from `/proc` every second.

## Screenshot

Run `luxos-screenshot`, press **Print** or **Super+Shift+5** for the floating bar, or use the
direct shortcuts **Super+Shift+3** (whole screen) and **Super+Shift+4** / **Shift+Print** (selected
area; press Space to pick a window instead).

The bar has these modes: Capture Entire Screen, Capture Selected Window, Capture Selected Portion,
Record Entire Screen, Record Selected Portion. Its **Options** menu has:

- **Save to**: Desktop (default), Pictures, Clipboard, Other… (a chosen folder). Recordings
  cannot go to the clipboard and are saved to the Desktop instead.
- **Timer**: None, 5 Seconds, 10 Seconds.
- **Show Mouse Pointer**.
- **Remember Last Selection**.

Files are named like `Screenshot 2026-10-22 at 11.12.03.png` and `Screen Recording … .mp4`. A
thumbnail appears for 5 s after saving. Options are stored in `~/.config/luxos/screenshot.json`.

Recording uses `ffmpeg` (x11grab, MP4). A small pill with a timer and **Stop** appears. Running
`luxos-screenshot --stop` (or starting the tool again) also stops recording.

Command-line options:

```
luxos-screenshot --screen | --portion | --window
luxos-screenshot --record-screen | --record-portion | --stop
  --clipboard            copy instead of saving a file
  --output DIR           save into DIR
  --region X,Y,W,H       capture this rectangle without selecting
  --no-thumbnail
```

Old `xfce4-screenshooter` launchers open this tool too.

## Feedback

Run `luxos-feedback`, or use About This Computer › Send Feedback… or Keyboard Shortcuts › Send
Feedback…. The report goes **directly to the author of LuxOS**: `POST https://lux-ai.cz/api/feedback`
(JSON).

- Type: Bug ("Something doesn't work"), Idea ("Suggest an improvement"), or Something else
  ("Question or comment"). A text with a minimum length.
- Optional e-mail (if you would like a reply), optional screenshot ("Attach a screenshot").
- **Attach system information** (optional, with "Show what will be sent"):
  - OS name and version, kernel, computer model, CPU and cores, GPU, memory, free disk space;
  - session type, language, uptime;
  - versions of LuxOS-related packages (`luxos*`, `lux`, `lux-*`, `luxai`, `lsl`, kernels, mesa,
    xorg-server, xfce4-session);
  - the last 50 error lines of the user and system journal of this boot, and `~/.xsession-errors`.

  Personal files, tokens, e-mail addresses and the home path are not included.
- If you are signed in to LuxAI, the account is attached (cookie). Otherwise the report is
  anonymous.
- Offline: the report is saved in `~/.local/share/luxos/feedback-outbox` and sent later
  (`luxos-feedback --send-outbox`).
- After sending, you get a Report ID.

## Network warning (luxos-netcheck)

`luxos-netcheck` is not a window. It is the "!" icon in the top bar, shown when NetworkManager
reports a connection without internet (`limited`/`none`) or a captive portal (`portal`). For a
portal, clicking it opens the sign-in page. Otherwise it opens Control Center. To check by hand:
`nmcli -t -f CONNECTIVITY,STATE general`.
