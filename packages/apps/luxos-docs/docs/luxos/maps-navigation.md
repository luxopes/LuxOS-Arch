# Maps navigation

**Navigation** in [Maps](maps.md) (`luxos-maps`; in Czech "Navigovat") guides you along a computed
route turn by turn with your live location: car, bike and walk routes, and the selected public
transport connection (steps only, without rerouting).

## Start and end

1. Plan a route in **Directions** (Car, Bike, Walk or Transit – for Transit select a connection).
2. Click **Start Navigation** under the travel time.
3. If Maps does not have your permission yet, it asks once (the same consent as **Show My Location**).

**End** in the bar at the bottom of the map stops navigation. Choosing another route, mode of travel or
closing the route also ends it; Esc does not (so it cannot end by accident).

## What you see

- **Instruction banner** at the top of the map: the icon of the next maneuver, the distance to it
  (e.g. "250 m"), the instruction ("Turn left", "Enter the roundabout and take exit 2") and the street,
  and below it the following maneuver ("Then: Turn right"). Instructions are translated into the system
  language.
- **Bottom bar**: remaining time, remaining distance and the arrival time (ETA), the compass button
  and **End**.
- The **current step** is highlighted in the sidebar list and scrolled into view.
- The **map follows you**: your position is an arrow pointing in the direction of travel. By default
  the map turns with you (**heading up**, your position in the lower part of the map so you see more
  ahead); the compass button switches to **north up** and back (remembered). Dragging the map stops
  following and shows **Re-center**; zooming keeps following.
- The map moves only when a new position arrives, at most 5 times per second (no animation between
  positions), so navigation stays light even on slow computers.

## Live location

- **Phone GPS** (best): an Android phone with **LuxOS Companion** that shares its location
  (Settings › Phone › Share phone location with Maps) – see [Phone (LuxOS Companion)](companion.md).
  A fresh phone position always wins.
- **GeoClue** (the system location service): used when the phone has sent nothing for 15 seconds.
  On a computer without GPS it is based on Wi-Fi networks and can be off by tens of metres.
- Positions worse than 100 m (for example by internet address) never move you along the route or
  trigger rerouting.
- Without any live position Maps says "Waiting for your location…", and after 12 seconds
  "No live location. Connect your phone with LuxOS Companion and share its location, or turn on the
  location service." When the phone stops sending, the arrow turns grey and the banner says
  "Location signal lost".

## Steps, rerouting and arrival

- The next maneuver changes once you have **passed** the current one (5 m past it along the route),
  using the turn points from the route server (OSRM maneuver type and direction).
- **Off route**: more than 50 m from the route (or more than the GPS accuracy, if that is worse) for
  3 positions in a row or for 10 seconds. Car, bike and walk routes are then **recalculated from your
  current position** ("Rerouting…") – at most once every 15 seconds, 30 seconds after a failed attempt,
  so the free FOSSGIS routing server is not overloaded. Your position and destination are sent to it,
  as when planning the route.
- **Arrival**: within 25 m of the end of the route – "You have arrived".
- **Remaining time** is the time of the rest of the current step plus the following steps, as computed
  by the route server; ETA = now + remaining time.

## Public transport

For a Transit connection the banner shows the steps of the itinerary live: "Walk to …", "Take Tram 22
→ …" with the stop, departure time and platform, "Get off at …" with the arrival time, then the walk
to the destination. The arrival time is the one from the timetable (with live delays known when the
connection was found). The current leg is highlighted in Connection details. There is no rerouting
for public transport – off the route Maps only says "You are off the route."; search again for a new
connection.

## Screen and voice

- While navigating, the screen does not blank or lock and the computer does not suspend
  (`org.freedesktop.ScreenSaver` of xfce4-screensaver and `org.freedesktop.PowerManagement.Inhibit` of
  xfce4-power-manager). Ending navigation or closing Maps releases it.
- **Voice guidance** is optional and **off by default**. The speaker button in the banner appears only
  when a speech program is installed: `speech-dispatcher` (`spd-say`) or `espeak-ng`
  (`lux install espeak-ng`). Maps then announces the next maneuver ahead ("In 400 m, turn left") and
  just before it, and the arrival, in the system language. The choice is remembered.

## Settings and testing

- `~/.config/luxos/maps.json`: `"nav_heading_up"` (true/false), `"nav_voice"` (true/false) and
  `"sidebar_width"` (the dragged width of the sidebar, 280–560 px).
- For testing without a phone or GPS: start Maps with `LUXOS_MAPS_SIMULATE=1 luxos-maps` – when there
  is no live location, the banner offers **Simulate**, which drives the route with a simulated
  position (a number such as `LUXOS_MAPS_SIMULATE=10` makes it 10× faster). Without the variable the
  button never appears.

## Troubleshooting

- **"No live location"**: check that the phone is connected in Settings › Phone and shares its
  location, that **⋯ › Allow My Location** is on in Maps, and that GPS is on in the phone.
- **The arrow jumps or the route is recalculated in a city centre**: GPS between tall buildings can be
  off by 50 m and more; Maps waits for 3 positions or 10 seconds before rerouting.
- **"The route could not be recalculated"**: no internet or the routing server is busy; Maps keeps
  the old route and tries again after 30 seconds.
- **No speaker button**: no speech program is installed (see Screen and voice).
