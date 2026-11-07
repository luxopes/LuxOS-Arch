# Weather

**Weather** (`luxos-weather`, package `luxos-weather`, installed by default) shows the current
weather, an hourly forecast for the next 24 hours and a 7-day forecast for your saved places. Open
it from Launchpad or Search ("Weather", in Czech "Počasí"), or click the weather line under the
date in the Calendar.

## What it shows

- **Now**: place, temperature, condition (Clear Sky, Partly Cloudy, Rain, Thunderstorm…), today's
  high and low. The window background is an animated scene of the weather and time of day (see
  Background).
- **Hourly forecast**: 24 hours from the current hour with an icon, temperature and the chance of
  precipitation (shown from 20 %).
- **7-day forecast**: day, icon, chance of precipitation, low and high with a bar showing the day's
  range within the week.
- **Details**: feels like, humidity, wind (speed and direction), precipitation today, UV index,
  pressure, sunrise and sunset.

## Places

- The sidebar lists your places with the current temperature; click one to show it.
- **+** searches for a city by name (Open-Meteo geocoding, in your language). Enter picks the first
  result.
- **Use My Approximate Location…** in the same popover finds your city from your internet address.
  It first asks for permission, because your address is sent to **ipinfo.io**. Weather never uses
  a location service on its own.
- On the first start, Weather adds the city of the computer's time zone (for example
  `Europe/Prague` → Praha). This is a city search, not a location service.
- Remove a place with right-click on it in the sidebar, or with **⋯ › Remove Location**.

## Units

°C, km/h and mm everywhere except where Fahrenheit is customary: °F, mph and inches for the US and
its territories (PR, GU, VI, AS, MP, UM), Palau, Micronesia, the Marshall Islands, the Bahamas,
Belize, the Cayman Islands and Liberia. **Automatic** decides like this:

1. The region of the measurement locale, in the usual order `LC_ALL`, `LC_MEASUREMENT`, `LANG`
   (`en_GB` → °C, `cs_CZ` → °C, `LC_MEASUREMENT=en_US` → °F). `LC_MEASUREMENT` set in
   `/etc/locale.conf` or `~/.config/locale.conf` counts at once, without logging out.
2. `LANG=en_US.UTF-8` alone (no `LC_MEASUREMENT`) is just the default English of LuxOS and Arch, so
   it is not taken as "I live in the US": the country of your first saved place decides, then the
   country of the system time zone (`Europe/Prague` → °C). Only if neither is known: °F.
3. No region at all (`C`, `POSIX`, `C.UTF-8`): first place, then time zone, otherwise °C.

On the first open, a small bar above the forecast asks **Which unit do you prefer?** with
**Celsius (°C)** and **Fahrenheit (°F)**; the detected one is highlighted and the forecast is
already shown in it, so you can ignore the bar. A choice is saved; **×** keeps Automatic. Either way
it is asked only once. Change it any time in **⋯ › Units** (Automatic (°C/°F), Celsius, Fahrenheit).

Upgrading from `luxos-weather` 1.0.0-1: before, `LANG=en_US.UTF-8` gave °F even in Europe (the
time zone and places were ignored). Settings still on Automatic are evaluated again with the rules
above and the bar is shown once; a unit you had chosen yourself in the menu is kept and not asked.

## Background

The window background is drawn by Weather itself (no images) and follows the current weather of the
selected place and the time of day there: clear, partly cloudy, cloudy, fog, drizzle, rain,
thunderstorm and snow, each by day, by night, at dawn and at dusk (45 minutes around sunrise and
sunset). Sun, moon in its real phase, twinkling stars, drifting clouds and fog, falling rain and
snow, and distant lightning (one soft flash at most every 5 seconds). Colours are darkened just
enough that white text keeps at least 3.3:1 contrast; the dark appearance tones the day sky down.

It is light on the CPU: only what moves is redrawn (rain and storms 30 frames/s, drizzle 24, snow
20, clouds and fog 15, stars 8; a clear day is a still picture), and nothing runs while the window
is minimized, hidden or not the active window, in **Battery Saver**, when GTK animations are off
(reduce motion), or when **⋯ › Animated Background** is unchecked. A still picture is shown then.

## Data, cache and offline use

- Data come from [Open-Meteo](https://open-meteo.com) (free, no API key, CC BY 4.0); requests go to
  `api.open-meteo.com` and `geocoding-api.open-meteo.com` only while the window is open.
- Each forecast is cached for **30 minutes** in `~/.cache/luxos/weather/forecast-<lat>_<lon>-<units>.json`;
  the window checks every 5 minutes and downloads only stale data. The refresh button forces a
  download.
- Without internet the last downloaded forecast is shown with "Offline – showing the forecast
  from 11:53". With no data at all you get "The forecast could not be loaded" and **Try Again**.
- Settings (places, selected place, units, `units_asked`, `animate`, `version`):
  `~/.config/luxos/weather.json`.
- `~/.cache/luxos/weather/summary.json` holds a short summary of the selected place. The Calendar
  under the clock shows it under today's date ("13°  Partly Cloudy · Praha") when it is less than
  3 hours old; clicking it opens Weather. The Calendar itself never downloads anything.

## Troubleshooting

- **"The forecast could not be loaded"**: check the internet connection; a firewall or proxy must
  allow HTTPS to `api.open-meteo.com`.
- **Wrong first city**: the time zone decides it (`timedatectl`); add your city with **+** and
  remove the other one.
- **Search finds nothing**: try the English or local name of the city.
- **Wrong units on Automatic**: check `locale` (`LC_MEASUREMENT`) and `timedatectl`; or simply
  pick Celsius or Fahrenheit in **⋯ › Units**.
- **Background does not move**: the window must be active; Battery Saver, GTK animations off and
  **⋯ › Animated Background** stop it on purpose.
