# Maps

**Maps** (`luxos-maps`, package `luxos-maps`, installed by default; in Czech "Mapy") shows an
OpenStreetMap map of the whole world, finds places and addresses, plans routes by car, bike or on
foot, keeps your favorite places and opens `geo:` links. Open it from Launchpad or Search ("Maps",
"Mapy"), or click a `geo:` link in another app.

## The map

- **Move**: drag with the mouse (the map glides on after a quick drag) or use the arrow keys.
- **Zoom**: mouse wheel or touchpad (towards the pointer), double-click, `+`/`-` keys or the
  **+ / −** buttons in the bottom right corner.
- The scale bar is in the bottom left (metres/kilometres; feet/miles with a US locale).
- **"© OpenStreetMap contributors"** in the bottom right is always visible (the OpenStreetMap
  licence requires it); clicking it opens the copyright page.
- **Right-click** (or Ctrl+click) on the map: **What's Here?** (address of the point),
  **Directions from Here**, **Directions to Here**, **Add to Favorites**, **Copy Coordinates**.
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

**Directions** (on a place, in the title bar or the right-click menu) opens the route panel:

- Start and destination: type a place and press Enter, use the location button in the field for
  **My Location**, or pick points on the map with the right-click menu. The arrows button swaps them.
- **Car / Bike / Walk** – the last choice is remembered.
- The panel shows travel time and distance and a list of turns (Turn left, Enter the roundabout and
  take exit 2…) with the street and the distance; clicking a turn shows it on the map.
- Routes come from the FOSSGIS routing server (`routing.openstreetmap.de`, OSRM) – the same one
  openstreetmap.org uses. It is free for reasonable personal use (at most one request per second);
  the start and destination are sent to that server. Esc or the back arrow closes the route.

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
- Settings, favorites and the last map view: `~/.config/luxos/maps.json`. Other servers can be set
  there without an update: `"tile_url": "https://…/{z}/{x}/{y}.png"`, `"search_url"`,
  `"reverse_url"`, `"route_url"` (with `{profile}` = `car`/`bike`/`foot` and `{coords}`).
- **Report a Map Issue** in the menu opens openstreetmap.org/fixthemap – the map is made by volunteers
  and anyone can fix it.

## For LuxAI and scripts: `luxos-maps --json`

`luxos-maps --json COMMAND` answers with one JSON object on stdout (no window; exit code 0 = ok,
1 = error, 2 = unknown command). It uses the same caches, rate limits and location permission as the
app.

| Command | Result |
|---|---|
| `search QUERY [--near LAT,LON] [--limit N]` | `results`: name, address, lat, lon, type, `geo_uri`, `osm_url` (max 10) |
| `reverse LAT,LON` | `place`: the address of a point |
| `route FROM TO [--mode car\|bike\|walk]` | `distance_m`, `duration_s`, readable `distance`/`duration`, `steps` (instruction, street, distance_m, lat, lon), `from`, `to` |
| `where-am-i` | `lat`, `lon`, `accuracy_m`, `source` (`geoclue` or `ip`) – only after the user allowed My Location in Maps, otherwise `{"ok": false, "error": "consent"}` |
| `open PLACE` / `open --route FROM TO [--mode M]` | opens the Maps window at a place (`LAT,LON`, `geo:` link or name) or with a route |

`FROM`/`TO` can be `LAT,LON`, a `geo:` link, a place name (the first search result) or `here` (my
location, needs the permission). Errors: `{"ok": false, "error": "…"}` (`NoRoute` when there is no
route). Example:

```
$ luxos-maps --json route "Staroměstské náměstí, Praha" "Pražský hrad" --mode walk
{"ok": true, "mode": "walk", "distance_m": 1816, "duration_s": 1453, "distance": "1.8 km",
 "duration": "24 min", "steps": [{"instruction": "Depart", "street": "Staroměstské náměstí", ...}], ...}
```

## Troubleshooting

- **Grey squares instead of the map**: no internet and the area was never viewed; or a firewall
  blocks `tile.openstreetmap.org`.
- **Search failed**: check the internet connection; HTTPS to `nominatim.openstreetmap.org` must be
  allowed. Very fast repeated searches are slowed down to one per second.
- **My location is far off**: without GeoClue the location comes from the internet address and may
  point to your provider's city; install `geoclue` (`lux install geoclue`) for a precise position.
