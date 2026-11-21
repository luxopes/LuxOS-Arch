# Screenshot and Screen Recording

The screenshot tool (`luxos-screenshot`). Other apps are described in [apps.md](apps.md).

## Taking a screenshot

Run `luxos-screenshot`, press **Print** or **Super+Shift+5** for the floating bar, or use the
direct shortcuts **Super+Shift+3** (whole screen) and **Super+Shift+4** / **Shift+Print** (selected
area; press Space to pick a window instead).

The bar has these modes: Capture Entire Screen, Capture Selected Window, Capture Selected Portion,
Record Entire Screen, Record Selected Portion. Its **Options** menu has:

- **Save to**: Screenshots (default, `Pictures/Screenshots` named in the user's language, created on
  the first save), Desktop, Pictures, Clipboard, Other… (a chosen folder). Recordings cannot go to the
  clipboard and are saved to the default folder instead.
- **Timer**: None, 5 Seconds, 10 Seconds.
- **Show Mouse Pointer**.
- **Remember Last Selection**.

## Files

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
luxos-screenshot --close   close an open bar, selection or thumbnail
```

**Esc** closes the tool in every state (bar, selection, timer countdown, thumbnail) even when another
app has the keyboard focus; an open Options or thumbnail menu closes first. While recording, Esc is
left to the recorded apps – use **Stop** or run the tool again. The bar and its windows live in the
session process `luxos-hub`, so the bar appears instantly; without it `luxos-screenshot` starts the
same tool on its own (`/usr/lib/luxos/luxos-screenshot-ui`).

Old `xfce4-screenshooter` launchers open this tool too.
