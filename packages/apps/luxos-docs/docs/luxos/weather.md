# Weather

**Weather** (`luxos-weather`, package `luxos-weather`, installed by default) shows the current
weather, an hourly forecast for the next 24 hours and a 7-day forecast for your saved places. Open
it from Launchpad or Search ("Weather", in Czech "Počasí"), or click the weather line under the
date in the Calendar.

## What it shows

- **Now**: place, temperature, condition (Clear Sky, Partly Cloudy, Rain, Thunderstorm…), today's
  high and low. The window background follows the sky (clear, cloudy, rain, snow, storm, fog; darker
  at night).
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

Units follow the system language and region: °C, km/h and mm (Czech and most countries), °F, mph and
inches for the US and a few others (`LC_MEASUREMENT`, then `LANG`). **⋯ › Units** switches between
Automatic, Celsius and Fahrenheit.

## Data, cache and offline use

- Data come from [Open-Meteo](https://open-meteo.com) (free, no API key, CC BY 4.0); requests go to
  `api.open-meteo.com` and `geocoding-api.open-meteo.com` only while the window is open.
- Each forecast is cached for **30 minutes** in `~/.cache/luxos/weather/forecast-<lat>_<lon>-<units>.json`;
  the window checks every 5 minutes and downloads only stale data. The refresh button forces a
  download.
- Without internet the last downloaded forecast is shown with "Offline – showing the forecast
  from 11:53". With no data at all you get "The forecast could not be loaded" and **Try Again**.
- Settings (places, selected place, units): `~/.config/luxos/weather.json`.
- `~/.cache/luxos/weather/summary.json` holds a short summary of the selected place. The Calendar
  under the clock shows it under today's date ("13°  Partly Cloudy · Praha") when it is less than
  3 hours old; clicking it opens Weather. The Calendar itself never downloads anything.

## Troubleshooting

- **"The forecast could not be loaded"**: check the internet connection; a firewall or proxy must
  allow HTTPS to `api.open-meteo.com`.
- **Wrong first city**: the time zone decides it (`timedatectl`); add your city with **+** and
  remove the other one.
- **Search finds nothing**: try the English or local name of the city.
