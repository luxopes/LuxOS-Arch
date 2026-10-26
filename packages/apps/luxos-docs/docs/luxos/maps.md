# Maps

**Maps** (`luxos-maps`, package `luxos-maps`, installed by default; in Czech "Mapy") shows an
OpenStreetMap map of the whole world, finds places and addresses, plans routes by car, bike, on
foot or by public transport, shows live departures from stops, finds places nearby (pharmacies,
stops, hotels…), keeps your favorite places and opens `geo:` links. Open it from Launchpad or Search ("Maps",
"Mapy"), or click a `geo:` link in another app.

## The map

- **Move**: drag with the mouse (the map glides on after a quick drag) or use the arrow keys.
- **Zoom**: mouse wheel or touchpad (towards the pointer), double-click, `+`/`-` keys or the
  **+ / −** buttons in the bottom right corner.
- The scale bar is in the bottom left (metres/kilometres; feet/miles with a US locale).
- **"© OpenStreetMap contributors"** in the bottom right is always visible (the OpenStreetMap
  licence requires it); clicking it opens the copyright page.
- **Right-click** (or Ctrl+click) on the map: **What's Here?** (address of the point),
  **Directions from Here**, **Directions to Here**, **Departures Nearby**, **Nearby ›** (categories),
  **Add to Favorites**, **Copy Coordinates**.
- **Map Appearance** in the **⋯** menu: Automatic (follows the light/dark system appearance), Light or
  Dark. The dark map is the normal map with inverted brightness (water stays blue), drawn locally.

## Search

Type a place, address or coordinates (`50.0875, 14.4208`) into the search field in the title bar and
press **Enter** (Ctrl+F or Ctrl+L focus the field). Places near the visible part of the map come
first. Maps searches only when you press Enter – OpenStreetMap's search service (Nominatim) does not
allow searching while typing. Click a result to show it: name, address, coordinates and the buttons
**Directions**, **Save** (star), **Copy Coordinates**, **Copy Location Link** (a `geo:` link for
other apps and phones) and **Open in OpenStreetMap** (in the web browser).

## Directions

**Directions** (on a place, in the title bar or the right-click menu) opens the route panel
(Directions › Car/Bike/Walk; public transport is described below):

- Start and destination: type a place and press Enter, use the location button in the field for
  **My Location**, or pick points on the map with the right-click menu. The arrows button swaps them.
- **Car / Bike / Walk** – the last choice is remembered.
- The panel shows travel time and distance and a list of turns (Turn left, Enter the roundabout and
  take exit 2…) with the street and the distance; clicking a turn shows it on the map.
- Routes come from the FOSSGIS routing server (`routing.openstreetmap.de`, OSRM) – the same one
  openstreetmap.org uses. It is free for reasonable personal use (at most one request per second);
  the start and destination are sent to that server. Esc or the back arrow closes the route.

## Public transport

Choose **Transit** next to Car/Bike/Walk in the route panel (the choice is remembered):

- **Leave Now**, **Depart At** or **Arrive By** with a time (`HH:MM`, today; press Enter).
- Up to three connections, each with departure – arrival, travel time and the legs as coloured line
  badges in the colours of the transport company (tram 22 dark red, metro A green…; walking is grey
  with the walking time). Below: **Direct** or the number of transfers, where the first vehicle
  leaves and its delay (**+2 min** in red, **On time** in green when live data are available,
  **Cancelled**).
- Clicking a connection draws it on the map – each line in its colour, walking dotted – with
  circles at the stops. **Connection details** lists every leg: line and direction, departure and
  arrival with the stop and platform (a changed platform is marked), number of stops and the operator.
- Clicking a leg, or a stop circle on the map, opens the **departures board** of that stop.

### Departures board

The next 20 departures (or **Arrivals**) with the line, destination, platform and live delay: the
real time is large, a different scheduled time is struck through below it, the delay is red,
cancelled trips are struck through. The board refreshes itself every minute while it is shown, the
refresh button reloads it at once. Open it from a connection, from a stop found by search or
**Nearby** (button **Departures** on the place), or for any point with right-click › **Departures
Nearby** (all stops within 300 m).

Public transport comes from **[Transitous](https://transitous.org)** (MOTIS), a free community
service that combines open timetable and realtime data of many transport companies across Europe and
elsewhere ([data sources](https://transitous.org/sources/)). Coverage depends on the published data:
some regions have no realtime delays, some have no data at all. The start, destination and time are
sent to Transitous.

## Nearby

**Nearby** on a place (or right-click › **Nearby**) finds Restaurants, Cafés, Groceries, Fuel,
Charging Stations, Parking, Pharmacies, Hospitals and Doctors, Hotels, Attractions, Public
Transport Stops, Toilets or Playgrounds around it (1.5 km, stops 600 m), nearest first, with the
distance and – when they are mapped – address, opening hours, phone and website. The data come from
OpenStreetMap through the **Overpass API** (`overpass-api.de`); a platform that is mapped several
times (A, B, C…) is shown once with all its platforms.

## Favorites

The **star** in the title bar shows your favorite places; a place is saved with **Save** or the
right-click menu and removed with **×** in the list or **Saved** on the place. Favorites are shown
on the map as yellow stars (click one to open it).

## My location

**Show My Location** (the location button) asks once whether Maps may use your location. After you
allow it, Maps uses the system location service **GeoClue** when it is installed and allows it
(`geoclue` package, precise), otherwise it finds your approximate location from your internet
address with **ipinfo.io** (your address is sent to that service; usually your city or provider).
Your position is a blue dot with a circle showing its accuracy. Maps never looks for your location
by itself; **⋯ › Allow My Location** turns the permission off again.

## geo: links

Maps is the handler for `geo:` links (`x-scheme-handler/geo`), for example
`geo:50.0875,14.4208?z=16`, `geo:0,0?q=Karlovo náměstí` (search) or
`geo:50.0875,14.4208?q=50.0875,14.4208(Home)` (with a label). From a terminal:

```
luxos-maps geo:50.0875,14.4208?z=16
luxos-maps "Karlovo náměstí, Praha"
luxos-maps --route "Staroměstské náměstí, Praha" "Pražský hrad" --mode walk
```

When Maps is already open, the link opens in the same window.

## Offline, cache and fair use

- Map tiles come from `tile.openstreetmap.org` and follow its usage policy: Maps identifies itself
  (`LuxOS-Maps/1.0`), downloads only the tiles you see (at most 2 at a time, no pre-loading of
  areas), keeps them in `~/.cache/luxos/maps/tiles` for as long as the server allows (usually about
  a week, then they are only re-checked with a short conditional request) and keeps at most 300 MB
  (oldest tiles are removed once a day).
- **Without internet** Maps shows everything you have viewed before ("Offline – showing saved map");
  missing areas are shown enlarged from a lower zoom level. Downloading areas for offline use is not
  offered – OpenStreetMap's tile servers do not allow it.
- Searches are cached for 30 days (`~/.cache/luxos/maps/search.json`) and limited to one request per
  second for all Maps windows and scripts together; routes are remembered while Maps runs.
- Public transport and Nearby (`~/.cache/luxos/maps/api`, at most 96 answers / 32 MB): connections
  are kept 3 minutes, departures 45 seconds (live delays change; the refresh button reloads after
  15 seconds), nearby places 10 minutes. Transitous and Overpass each get at most one request per
  second from the whole computer. When a service answers that it is overloaded (HTTP 429/502/503/504
  – the public Overpass server often is), Maps sends it nothing for 30 seconds and says "busy".
  Overpass queries have a 20 s server timeout and at most 50 results.
- Settings, favorites and the last map view: `~/.config/luxos/maps.json`. Other servers can be set
  there without an update: `"tile_url": "https://…/{z}/{x}/{y}.png"`, `"search_url"`,
  `"reverse_url"`, `"route_url"` (with `{profile}` = `car`/`bike`/`foot` and `{coords}`),
  `"transit_plan_url"`, `"stoptimes_url"` (a MOTIS v6 server) and `"overpass_url"`.
- **Report a Map Issue** in the menu opens openstreetmap.org/fixthemap – the map is made by volunteers
  and anyone can fix it.

## For LuxAI and scripts: `luxos-maps --json`

`luxos-maps --json COMMAND` answers with one JSON object on stdout (no window; exit code 0 = ok,
1 = error, 2 = unknown command). It uses the same caches, rate limits and location permission as the
app. `luxos-maps --json help` lists the commands and `nearby_categories`.

| Command | Result |
|---|---|
| `search QUERY [--near LAT,LON] [--limit N]` | `results`: name, address, lat, lon, type, `geo_uri`, `osm_url` (max 10) |
| `reverse LAT,LON` | `place`: the address of a point |
| `route FROM TO [--mode car\|bike\|walk\|transit] [--no-preview]` | `distance_m`, `duration_s`, readable `distance`/`duration`, `steps` (instruction, street, distance_m, lat, lon), `from`, `to`, `open_map_url`, `preview`; `--mode transit` = `transit-route` |
| `transit-route FROM TO [--time T] [--arrive] [--max-transfers 0-8] [--limit 1-5] [--geometry] [--no-preview]` | public transport: `itineraries` (default 3, max transfers 3), `timezone`, `search`, `preview`, `attribution` |
| `timetable STOP [--type departures\|arrivals] [--time T] [--radius 25-2000] [--limit 1-30] [--stop-id ID]` | `connections` at all stops within `--radius` m (default 500, 8 connections), `stops` (names) |
| `nearby PLACE --category C \| --name TEXT [--radius 50-10000] [--limit 1-50]` | `results` sorted by distance (default 1500 m, 20 results) |
| `where-am-i` | `lat`, `lon`, `accuracy_m`, `source` (`geoclue` or `ip`) – only after the user allowed My Location in Maps, otherwise `{"ok": false, "error": "consent"}` |
| `open PLACE` / `open --route FROM TO [--mode M]` | opens the Maps window at a place (`LAT,LON`, `geo:` link or name) or with a route (also `--mode transit`) |

`FROM`/`TO`/`STOP`/`PLACE` can be `LAT,LON`, a `geo:` link, a place name (the first search result) or
`here` (my location, needs the permission). `T` is ISO 8601 with a time zone
(`2026-08-24T10:00:00+02:00`; without a zone = the computer's local time) or `HH:MM` (today); without
`--time` = now. Categories `C`: `restaurants`, `cafes`, `groceries`, `fuel`, `charging`, `parking`,
`pharmacies`, `hospitals`, `hotels`, `attractions`, `public_transport`, `toilets`, `playgrounds`.

Errors: `{"ok": false, "error": "…"}` – `NoRoute` (no route / no public transport connection),
`consent` (location not allowed), `busy` (Transitous or Overpass overloaded or cooling down for 30 s;
`message` says how long – try later, do not retry in a loop), `invalid time …`, `unknown category …`,
`place not found: …`, `no departures found near this place`.

### Public transport (`transit-route`)

All times are in the local time zone of the stop (`timezone`, e.g. `Europe/Prague`), as ISO 8601
with offset (`departure`, `arrival`) and as `HH:MM` (`departure_time`, `arrival_time`). Each
itinerary:

| Field | Meaning |
|---|---|
| `departure`, `arrival`, `departure_time`, `arrival_time`, `date` | whole journey (realtime when known) |
| `duration_s`, `duration`, `transfers`, `walk_m` | travel time, number of transfers, walking metres |
| `realtime` | some leg has live data; `cancelled`: some leg is cancelled |
| `summary` | one English line for reading out: `19:10 → 19:33 · 23 min · 0 transfers: Walk 56 m to Karlovo náměstí (1 min); Tram 22 toward Vypich · 19:11–19:21 · Karlovo náměstí → Malostranské náměstí · platform C · +1 min · realtime; Walk 810 m to destination (12 min)` |
| `legs[]` | in order, see below |

Leg: `mode` (MOTIS: `WALK`, `TRAM`, `SUBWAY`, `BUS`, `RAIL`, `REGIONAL_RAIL`, `FERRY`, …),
`mode_name` (English: Walk, Tram, Metro, Bus, Train…), `transit` (false for walking), `line`
(`22`, `A`, `S9`), `headsign` (direction), `operator`, `route_name`, `color`/`text_color` (line
colour from the timetable, otherwise by mode – the same colours as the Maps app and LuxAI on the
phone), `from`/`to` (`name`, `lat`, `lon`, `stop_id`, `platform`, `scheduled_platform` +
`platform_changed` when it changed, `departure`/`arrival` + `…_time` + `…_delay_min`),
`departure`/`arrival`/`departure_time`/`arrival_time`, `scheduled_departure_time`,
`scheduled_arrival_time`, `delay_min` and `arrival_delay_min` (minutes, + late / − early),
`realtime`, `cancelled`, `duration_s`, `distance_m` (walking), `stops` and `intermediate_stops`
(vehicles). With `--geometry` every leg also has `geometry` = `{"polyline", "precision"}` (Google
encoded polyline, MOTIS precision 6). `attribution` and `sources_url`
(`https://transitous.org/sources/`) must be shown with the data.

### Departures (`timetable`)

`connections[]`: `time`/`datetime` (real or planned), `scheduled_time`/`scheduled_datetime`,
`delay_min`, `realtime`, `line`, `mode`, `mode_name`, `color`, `text_color`, `headsign`
(destination), `origin` (where the trip started; for arrivals), `stop`, `stop_id`, `lat`, `lon`,
`platform`, `scheduled_platform` + `platform_changed`, `cancelled`, `operator` and `summary`
(`19:04 · 194 toward Florenc · Masná · +2 min · platform B (scheduled A) · realtime · operator
Pražská integrovaná doprava`). `--stop-id` (from `transit-route` legs) asks for exactly one stop
instead of a radius.

### Nearby (`nearby`)

`results[]`: `name`, `lat`, `lon`, `distance_m`, `distance`, `kind` (`amenity=pharmacy`), `address`,
`opening_hours`, `phone`, `website`, `wheelchair`, `cuisine`, `operator` (when mapped), `osm_url`,
`geo_uri`; stops also `transit: true`, `platform`/`platforms`. The same stop mapped several times is
merged (nearest first). `--name` searches by name (case-insensitive), alone or with a category.

### Route picture for LuxAI (`preview`, `--render-preview`)

`route` and `transit-route` include `preview` – everything needed to draw a small route map (the
same fields as the route card of LuxAI on the phone, plus `bbox`):

```json
{"version": 1, "mode": "transit",
 "start": {"lat": 50.0757, "lon": 14.4199, "label": "Karlovo náměstí"},
 "end": {"lat": 50.0905, "lon": 14.3995, "label": "Pražský hrad"},
 "bbox": [50.075672, 14.397947, 50.090618, 14.4199],
 "legs": [{"mode": "WALK", "label": "Walk", "color": "#64748B", "polyline": "…", "precision": 6},
          {"mode": "TRAM", "label": "22", "color": "#7A0603", "polyline": "…", "precision": 6}],
 "open_map_url": null, "attribution": "© OpenStreetMap contributors"}
```

`bbox` = south, west, north, east; `polyline` = Google encoded polyline with `precision` digits
(at most 400 points per leg); `transit-route` previews its first itinerary; car/bike/walk have
`open_map_url` (openstreetmap.org directions). Render it as a PNG:

```
luxos-maps --render-preview route.json --size 480x270 --out /tmp/route.png [--itinerary N]
→ {"ok": true, "out": "/tmp/route.png", "zoom": 15, "tiles": 4, "missing_tiles": 0,
   "downloaded": 0, "width": 480, "height": 270, "attribution": "© OpenStreetMap contributors"}
```

The input is the whole `route`/`transit-route` output, only its `preview`, or `-` (stdin);
`--itinerary N` draws another itinerary (needs `transit-route --geometry`). Size 64×64 to 1024×1024.
It uses the tile cache of Maps and downloads only the few tiles that this picture covers (same
User-Agent and cache rules as the app, at most 2 at a time); offline, missing tiles stay plain. The
picture always carries "© OpenStreetMap contributors".

Example:

```
$ luxos-maps --json transit-route "Karlovo náměstí, Praha" "Pražský hrad" --limit 1
{"ok": true, "mode": "transit", "timezone": "Europe/Prague", "search": {"time": "now", "arrive_by": false},
 "itineraries": [{"departure_time": "19:10", "arrival_time": "19:33", "duration": "23 min", "transfers": 0,
   "legs": [{"mode": "WALK", ...}, {"mode": "TRAM", "line": "22", "headsign": "Vypich", "delay_min": 1,
            "from": {"name": "Karlovo náměstí", "platform": "C", ...}, ...}, ...],
   "summary": "19:10 → 19:33 · 23 min · 0 transfers: ..."}],
 "preview": {...}, "attribution": "Timetable data by participating open-data providers via Transitous — https://transitous.org/sources/; map data © OpenStreetMap contributors"}
$ luxos-maps --json route "Staroměstské náměstí, Praha" "Pražský hrad" --mode walk
{"ok": true, "mode": "walk", "distance_m": 1816, "duration_s": 1453, "distance": "1.8 km",
 "duration": "24 min", "steps": [{"instruction": "Depart", "street": "Staroměstské náměstí", ...}], ...}
```

## Troubleshooting

- **Grey squares instead of the map**: no internet and the area was never viewed; or a firewall
  blocks `tile.openstreetmap.org`.
- **Search failed**: check the internet connection; HTTPS to `nominatim.openstreetmap.org` must be
  allowed. Very fast repeated searches are slowed down to one per second.
- **"busy" / "The public transport service is busy"**: Transitous or the public Overpass server is
  overloaded; Maps waits 30 s before asking again. Try again later.
- **No connections or departures**: Transitous has no timetable for that area (see
  [its data sources](https://transitous.org/sources/)), or there is no service at that time.
- **My location is far off**: without GeoClue the location comes from the internet address and may
  point to your provider's city; install `geoclue` (`lux install geoclue`) for a precise position.
