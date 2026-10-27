# Phone (LuxOS Companion)

**LuxOS Companion** is an Android app (8.0 or newer) that connects a phone with a LuxOS computer over
Bluetooth. With it the phone can:

- share its **live GPS location** with **Maps** (the blue dot follows you),
- send text requests to **LuxAI** (Chat or Agent) and show the streamed answer,
- save **notes to the Calendar** of the computer.

The computer side is the package `luxos-companion` (installed by default): a small service in your
session (`luxos-companion.service`, systemd user unit) and the settings window **Phone**
(`luxos-companion`, Settings › Phone). Nothing goes through the internet or an account: the phone talks
only to the computer over an encrypted Bluetooth link.

## First connection

1. **Pair the phone in Bluetooth settings first** (Settings › Bluetooth or the Bluetooth icon in the
   top bar). LuxOS never makes the computer visible ("discoverable") by itself – turn visibility on in
   the Bluetooth settings only while pairing.
2. Open LuxOS Companion on the phone, pick the computer from the paired devices and press
   **Connect**.
3. On the first connection LuxOS asks: **Allow “Phone name” to connect to LuxOS?** with **Allow** /
   **Deny** (a notification; the same question is in the Phone window). Pairing alone is not
   permission: every phone has to be allowed once.
4. The phone has about 20 seconds to finish connecting. If you answer later, LuxOS remembers the answer
   – just press Connect on the phone again.

Phones that are paired but not allowed get an error and are disconnected. BlueZ may additionally ask to
authorize the service if the phone is not marked as trusted in the Bluetooth settings.

## The Phone window

Settings › **Phone** (`luxos-companion`) shows:

- **Status**: service not running (button **Start**), Bluetooth off, *Ready for the phone*, or
  *Connected: Pixel 8 – Sharing location*.
- Pending questions from new phones (**Allow** / **Deny**).
- **Allowed Phones** with **Remove** – removing a phone revokes it immediately and disconnects it.
- **Permissions** (for all allowed phones, all on by default):
  - **Share phone location with Maps** – when off, location updates from the phone are dropped.
  - **Allow LuxAI requests from the phone**.
  - **Allow saving notes to Calendar**.
- **Bluetooth Settings…** for pairing.

Settings are stored in `~/.config/luxos/companion.json` (mode 0600):

```json
{"version": 1, "phones": {"AA:BB:CC:DD:EE:FF": {"name": "Pixel 8", "approved": "2026-10-27T12:00:00+00:00"}},
 "share_location": true, "allow_luxai": true, "allow_calendar": true}
```

`luxos-companion --status` prints the state of the service as JSON (connections, pending approvals,
Bluetooth, current phone location).

## Location in Maps

The phone sends a fresh GPS fix about once a second while location sharing is on in the app. LuxOS
keeps only the newest fix and treats it as **valid for at most 15 seconds** (measured with the
computer's own monotonic clock minus the age reported by the phone – the clocks of the phone and
computer are never compared). Turning GPS off in the app, disconnecting or a timeout removes the phone
location immediately.

Maps uses the phone only when **both** are true:

- Maps has your location consent (Maps › ⋯ › **Allow My Location**, asked once), and
- **Share phone location with Maps** is on in the Phone window.

Then **Show My Location** in Maps uses the phone's GPS (accuracy circle in metres) instead of GeoClue
or the IP address, and Maps **follows the phone**: the blue dot moves with every update and the map
keeps it centred until you drag the map (press Show My Location again to follow again). When the phone
location becomes stale the dot turns grey. `luxos-maps --json where-am-i` reports `"source": "phone"`.

Other applications do not get the phone location: it is published only on the session bus (below).

### Later: GeoClue bridge (planned, not implemented)

To give the phone GPS to every Linux application, a later version can feed GeoClue: GeoClue reads
NMEA sentences from a network source announced over Avahi (`_nmea-0183._tcp`, the same mechanism as
the Android app "GPSd Forwarder"). The service would write `$GPGGA`/`$GPRMC` sentences built from fresh
fixes to a local TCP socket bound to 127.0.0.1 and announce it only while sharing is on; GeoClue's
own per-application permissions would then decide who gets the location. This needs a GeoClue configuration change (`[network-nmea] enable=true`) and
a check that stale fixes stop the stream after 15 s. Until then only Maps uses the phone location.

## LuxAI from the phone

A request from the phone (at most 8000 characters, mode Chat or Agent) starts
`luxai --remote-session` for that connection (a headless mode of LuxAI) and the answer is streamed back.
The conversation lasts for the connection; reconnecting starts a new one. Only one request runs at a
time (a second one gets "busy"). **Stop** on the phone cancels the running request (best effort: actions
that already happened are not undone).

- The phone's text is passed to LuxAI only as data on standard input – it is never run as a command.
- LuxAI's own permission rules apply. Confirmations of tools and actions are shown **on the computer**,
  never on the phone (protocol v1 has no mobile confirmations).
- If the installed LuxAI does not have `--remote-session` yet, the phone gets the error
  `luxai_unavailable` ("Update LuxAI").

## Calendar notes

A note from the phone (title up to 200 characters, text up to 8000, date, optional time, time zone)
becomes an event in your own calendar `~/.local/share/luxos/calendar/events.ics` (Calendar in the top
bar shows it right away):

- **Without time** – an all-day event (`DTSTART;VALUE=DATE`, `DTEND` the next day).
- **With time** – a 30-minute event in the phone's time zone (`DTSTART;TZID=Europe/Prague:…`).
- A time that does not exist because the clocks change (for example 02:30 on the last Sunday of
  March in Prague) is refused; an ambiguous time when the clocks go back means the first one.
- Title → `SUMMARY`, text → `DESCRIPTION`, written by the same iCalendar serializer as the Calendar
  (escaping, folding, Czech characters). Other events, time zones and to-dos in the file are kept
  byte for byte.
- The phone gets the confirmation **only after the file is safely on disk** (fsync). The same request
  sent twice never creates two events (request IDs are remembered in
  `~/.local/state/luxos/companion/calendar-requests.json`; the event UID is derived from the request ID).
- Writing is coordinated with the Calendar: a lock, re-reading the file right before writing, an atomic
  replace, and the Calendar takes over events added by other programs before it saves its own changes.

## Protocol and troubleshooting

Bluetooth Classic RFCOMM, service UUID `ad9b7c10-6ce5-4f35-9952-728f760fcb70`, registered in BlueZ
with `ProfileManager1.RegisterProfile` (role server, authentication and authorization required, no
auto-connect). Frames are one JSON object per line (UTF-8, at most 65 536 bytes including the newline);
invalid UTF-8, oversized or unfinished frames and unsupported versions close the connection. The phone
must send `hello` within 20 s; it pings every 15 s and the connection closes after 45 s without any
message. Error replies carry a `code` such as `not_approved`, `permission_denied`, `invalid_title`,
`invalid_date`, `invalid_time`, `nonexistent_time`, `invalid_timezone`, `storage_failed`, `busy`,
`luxai_unavailable`.

Session bus API (`cz.luxos.Companion1` at `/cz/luxos/Companion1`): `GetLocation()` and the property
`CurrentLocation` (`a{sv}`: `valid`, `latitude`, `longitude`, `accuracy`, `timestamp_ms`, `age_ms`,
`mock`, `device`, optional `altitude`, `speed`, `bearing`), the signal `LocationChanged`, `GetStatus()`
(JSON), `StatusChanged`, `AnswerApproval(address, allow)`, `Disconnect(address)`, `ReloadSettings()`.

- **The phone does not see the computer**: pair it in Bluetooth settings first; check that the Phone
  window shows *Ready for the phone* (otherwise **Start**, or `systemctl --user status
  luxos-companion`).
- **"Počítač nepotvrdil protokol v1"** (the computer did not confirm protocol v1) on the phone: the
  phone was not allowed in time or was denied –
  allow it in the Phone window and connect again.
- Logs: `journalctl --user -u luxos-companion`.
