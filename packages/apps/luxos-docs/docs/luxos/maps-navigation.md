# Maps navigation

**Navigation** in [Maps](maps.md) (`luxos-maps`; in Czech "Navigovat") guides you along a computed
route turn by turn with your live location: car, bike and walk routes, and the selected public
transport connection. When you leave the route, Maps finds a new one from where you are.

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
- **Smooth movement**: the arrow (and the map following it) glides between positions instead of
  jumping. On the route the arrow sits on the route line (when the position is within its accuracy);
  for up to 1.5 seconds after the last position it keeps moving with the phone's speed and direction,
  then it stops and waits. A new position does not make it jump – the difference is eased in within a
  fraction of a second, and the map turns along the shortest way. Positions are processed at most
  5 times per second; the animation draws at most 30 frames per second (about 10 when walking) and
  only while the arrow moves – without new positions Maps draws nothing.

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
- **Off route**: farther from the route than 50 m by car, 40 m by bike or 35 m on foot (or than the
  GPS accuracy, if that is worse) for 3 positions in a row over at least 4 seconds, or for 10 seconds.
  A position just below the limit does not reset the count (GPS noise next to a parallel street), only
  a position clearly on the route (below 3/4 of the limit) does. While the phone reports that it is not
  moving, jumping positions count only when they are more than twice the limit away.
- **Wrong direction**: walking or driving back along the route (more than 40 m, or the GPS accuracy,
  behind the farthest point you reached, with the phone's direction against the route) counts as off
  route too.
- Car, bike and walk routes are then **recalculated from your current position** ("Rerouting…"); car
  and bike routes start in your direction of travel (no U-turn at the start). The new route replaces
  the old one on the map, in the sidebar and in the banner. At most once every 15 seconds, 30 seconds
  after a failed attempt, so the free FOSSGIS routing server is not overloaded. Your position and
  destination are sent to it, as when planning the route.
- **Arrival**: within 25 m of the end of the route – "You have arrived".
- **Remaining time** is the time of the rest of the current step plus the following steps, as computed
  by the route server; ETA = now + remaining time.

## Public transport

For a Transit connection the banner shows the steps of the itinerary live: "Walk to …", "Take Tram 22
→ …" with the stop, departure time and platform, "Get off at …" with the arrival time, then the walk
to the destination. The arrival time is the one from the timetable (with live delays known when the
connection was found). The current leg is highlighted in Connection details.

Public transport is replanned with Transitous from your current position ("Finding a new
connection…") when:

- you leave the route on a walking leg (same limits as walking) or, in a vehicle, are more than 150 m
  from the line (line shapes are approximate), or go the wrong way;
- you **missed the connection**: 90 seconds after the departure of the next vehicle you still have not
  boarded (you are not past the boarding stop) – "Connection missed. Finding another one…".

The first connection found replaces the old one in the sidebar, on the map and in the banner. With
**Arrive By** the arrival time you chose is kept; otherwise the new connection leaves now. At most one
new search per minute (30 seconds after a failed one); without any connection Maps says "No other
connection found." and keeps the old one.

## Screen and voice

- While navigating, the screen does not blank or lock and the computer does not suspend
  (`org.freedesktop.ScreenSaver` of xfce4-screensaver and `org.freedesktop.PowerManagement.Inhibit` of
  xfce4-power-manager). Ending navigation or closing Maps releases it.
- **Voice guidance** is optional and **off by default**. To turn it on:
  1. Install a speech program, for example `lux install espeak-ng` (or `speech-dispatcher`, which
     provides `spd-say`).
  2. Restart Maps – the **speaker button** appears in the top right corner of the navigation banner
     (without a speech program the button is not shown at all).
  3. Start navigation and click the speaker button (crossed speaker = off). Maps then announces the next
     maneuver ahead ("In 400 m, turn left") and just before it, and the arrival, in the system language.
     The choice is remembered (`"nav_voice"`), so next time voice is on right away.

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
- **The route is recalculated in a city centre without a reason**: GPS between tall buildings can be
  off by 50 m and more; Maps waits for 3 positions (at least 4 seconds) or 10 seconds before
  rerouting and ignores jumps while the phone is not moving.
- **The route is not recalculated**: positions worse than 100 m are ignored, and the limit grows with
  the GPS accuracy – with an accuracy of 60 m a street 50 m away cannot be told apart from the route.
- **"The route could not be recalculated"**: no internet or the routing server is busy; Maps keeps
  the old route and tries again after 30 seconds.
- **No speaker button**: no speech program is installed (see Screen and voice).
