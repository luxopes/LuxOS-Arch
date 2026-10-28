# Maps search and suggestions

How to find places in [Maps](maps.md) (`luxos-maps`; in Czech "Mapy"): the search field in the title
bar, suggestions while typing (also in the **Start** and **Destination** fields of Directions), recent
places, and what is sent where.

## Search

Type a place, address or coordinates (`50.0875, 14.4208`) into the search field in the title bar
(Ctrl+F or Ctrl+L focus it). While you type, **suggestions** appear under the field (see below);
**Enter** without a selected suggestion runs a full search with OpenStreetMap's search service
**Nominatim** and lists the results in the sidebar – places near the visible part of the map come
first. Click a result to show it: name, address, coordinates and the buttons **Directions**, **Save**
(star), **Copy Coordinates**, **Copy Location Link** (a `geo:` link for other apps and phones) and
**Open in OpenStreetMap** (in the web browser). A stop or station also offers **Departures**.

## Suggestions while typing

After two letters a list opens under the field (like Apple or Google Maps). Each row has a coloured
icon for its kind, the name with the typed part in **bold**, a second line with the street, town and
country, and the distance from the centre of the map:

| Icon | Kind |
|------|------|
| blue dot | **My Location** (only in Start/Destination, see below) |
| yellow star | favorite place |
| grey clock | recent place (picked earlier) |
| blue bus | public transport stop or station |
| house | address (street and house number) |
| road | street or square |
| buildings | town, district, region or country |
| pin (colour by category) | place: restaurant/café (orange), shop (yellow), sights and hotels (pink), pharmacy/doctor (red), parks and sport (green), other (red) |

Order: your own places first – favorites, then recent places, then stops already loaded in Maps
(stops of the shown connection, a departures board or a nearby search) – at most four, then
online suggestions (from the **LuxOS geocoder** in Czechia and Slovakia, otherwise **Photon**, see
below), with places whose name matches the typed words before places that only match in the address. The same place is listed once (a square drawn as an
area and its street segments, several platforms of one stop).

Matching of your own places ignores accents and case and looks at the beginning of words:
`namesti mir` finds "Náměstí Míru", `karl` finds "Karlín" and "Karlovo náměstí", but `esti` finds
nothing. Online suggestions start after three letters.

**Keyboard and mouse**: **↓/↑** move through the list, **Enter** picks the selected row, **Esc** closes
the list (the text stays), **Tab** moves on. **Enter** with no row selected searches as before (search
field) or takes the first search result (Start/Destination). A click on a row picks it.

Picking a suggestion goes straight to its coordinates – the suggestion already has them, so no
further request to Nominatim is made:

- **Search field**: the place opens in the sidebar and the map moves there (to the whole area for a
  town or square).
- **Start / Destination**: the field gets the name and the route is computed again right away (car,
  bike, walk or public transport, whichever is selected). With location permission
  (**⋯ › Allow My Location**) **My Location** is always the first suggestion in these fields; picking
  it uses your current position (and asks for a fix if Maps does not have one yet).

The list only queries the server after you stop typing for **150 ms**; each new letter cancels the
previous query (also one already sent), so a fast typist sends one request, not one per letter.
Answers are remembered for 10 minutes while Maps runs, and the HTTPS connection stays open between
queries (no new TLS handshake for every letter). Nothing blocks the window: queries run in the
background and a late answer for text you already changed is thrown away.

### Where online suggestions come from

1. **LuxOS geocoder** (`https://luxos.lux-ai.cz/geocode/api`, run by the LuxOS project) when the map
   centre is in **Czechia or Slovakia**. It answers in tens of milliseconds and knows towns and
   districts, streets, addresses (house numbers), places (shops, restaurants, sights…) and public
   transport stops (platforms of one stop are merged into one row), built weekly from
   OpenStreetMap data. The footer then says "Suggestions by LuxOS · © OpenStreetMap contributors".
2. **Photon** (`photon.komoot.io`) when the map centre is elsewhere, when the LuxOS geocoder does not
   answer within 1.2 s (then it is skipped for 30 s), or when it finds fewer than two places whose
   name matches – the LuxOS rows stay on top and Photon's are added below them as they arrive
   (for example a city abroad while the map shows Prague). Photon takes 2–4 s.

## Recent places

A place you pick from suggestions or search results (and a start or destination found by name) is
added to **recent places** – at most 12, newest first, a repeated place moves up. They are kept only
on this computer in `~/.config/luxos/maps.json` (`"recent"`) and are never sent anywhere.
**⋯ › Clear Recent Places** empties the list.

## Privacy: what is sent where

- **Suggestions** (online): the typed text, the map centre rounded to about 1 km and the language go
  with the `LuxOS-Maps/1.0` user agent – the same way pressing Enter sends the text to Nominatim:
  - to **luxos.lux-ai.cz** (the LuxOS geocoder) when the map shows Czechia or Slovakia. The server
    **does not store or log the typed text**: the service writes no access log, error messages never
    contain the query, and the web server's access log is turned off for `/geocode/`. To limit
    abuse it keeps only a request counter per IP address in memory (a few seconds, never written);
  - to **photon.komoot.io** (Photon by komoot, built on OpenStreetMap data, no account or key)
    outside that area or as a fallback (see above). Photon is used because Nominatim's usage policy
    forbids searching while typing on its public server.

  Maps keeps to fair use: 150 ms pause, at most 7 results, the last text only, no repeated queries
  for the same text and area; after a network error or a "busy" answer (HTTP 429/5xx) it sends
  nothing to that server for 30 seconds.
- **⋯ › Suggestions While Typing** turns online suggestions off (`"suggest_online": false` in
  `maps.json`). The list then shows only favorites, recent places and loaded stops – nothing is sent
  while typing; Enter still searches with Nominatim.
- **Search with Enter**: the text and the visible map area go to `nominatim.openstreetmap.org`.
- Your location itself is not added to suggestion queries – only the map centre (which is near you
  when the map follows your location).

## Without internet

When neither the LuxOS geocoder nor Photon can be reached the list keeps working with your own places
and shows "Offline – showing saved places only"; Maps then waits 30 seconds before trying again.

## Settings in `maps.json`

`~/.config/luxos/maps.json` (written by Maps; edit while Maps is closed):

- `"suggest_online": true` – online suggestions (default on).
- `"suggest_url": "https://photon.example.org/api/"` – use only this server for suggestions, for
  example your own or a company Photon (any server with the Photon `/api` interface: `q`, `lat`,
  `lon`, `limit`, `lang`). Neither the LuxOS geocoder nor photon.komoot.io is then asked.
- `"suggest_providers": ["https://luxos.lux-ai.cz/geocode/api", "https://photon.komoot.io/api/"]` –
  several servers in order (at most 4); this list is the default. The first gets 1.2 s, the others
  are the fallback. A server whose path ends in `/geocode/api` is treated as a LuxOS geocoder (asked
  only for Czechia and Slovakia, with the system language). Only `http://` and `https://` addresses
  are accepted.
- `"recent": […]` – recent places (name, coordinates, address, kind).

The LuxOS geocoder returns names in the system language when OpenStreetMap has them (`name:cs`,
`name:sk`, `name:en`, `name:de` …; "Prag" in German) and the country name in that language. Photon
understands English, German and French; for other languages Maps asks Photon for local names
("Praha", "Wien"), which is what people in the area use.

## Troubleshooting

- **No online suggestions**: check **⋯ › Suggestions While Typing**; HTTPS to `luxos.lux-ai.cz` and
  `photon.komoot.io` must be allowed. After a network error that server pauses for 30 seconds.
- **A place is missing in suggestions**: press Enter to search with Nominatim, which finds more
  (for example house names and areas the suggestion servers do not index). Data of the LuxOS
  geocoder is rebuilt weekly, so a place added to OpenStreetMap today appears within about a week.
- **Suggestions open in the wrong country**: move the map to the area first – suggestions near the
  map centre come first.
