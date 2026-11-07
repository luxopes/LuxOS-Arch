"""Textovy editor: ukazkovy projekt v postrannim panelu se zvyraznenim LSL a Markdown s hledanim a nahrazovanim.

Editor se preklada ze zdroju do s.tmp (jako build() v PKGBUILD); barvy a jazyk LSL ze zdroju
(LUXOS_TEXT_DATA_DIR jako testy), ikona okna z luxos-branding.
"""
import os
import subprocess

FORECAST = '''# Weather widget - hourly forecast for the top bar
load http, json, math
load luxos_text as text

API = "https://weather.example.com/v1/forecast"
HOURS = 12

# Rounds the temperature to whole degrees ("-0" becomes "0")
function format_temp(celsius):
    value = Int(math.round(celsius))
    if value == 0:
        return "0 °C"
    end
    return text.format("{} °C", value)
end

function hourly(place):
    reply = http.get(API + "?lat=" + place.lat + "&lon=" + place.lon)
    if reply.status != 200:
        return []
    end
    data = json.parse(reply.body)
    rows = []
    for hour in data["hourly"][0:HOURS]:
        rows.append({"time": hour["time"][11:16],
                     "temp": format_temp(hour["temperature"]),
                     "icon": hour["symbol"]})
    end
    return rows
end

function main():
    place = {"name": "Prague", "lat": "50.08", "lon": "14.42"}
    for row in hourly(place):
        print(row["time"] + "  " + row["icon"] + "  " + row["temp"])
    end
end
'''

README = '''# Weather widget

A tiny widget for the LuxOS top bar that shows the weather
for the next 12 hours. Written in LSL.

## Build

Run `make` in this folder. The widget is saved as
`weather-widget` next to the sources.

## Usage

Start the widget and pick your place. The weather is
refreshed every 30 minutes. Click the weather icon to open
the full forecast.

## Settings

- `place` - the place shown in the top bar
- `units` - Celsius or Fahrenheit
- `hours` - how many hours of weather to show

## License

GPL-3.0-or-later. Weather icons by the LuxOS team.
'''

FILES = {
    "README.md": README,
    "Makefile": "all:\n\tlslc src/main.lsl weather-widget\n",
    "src/main.lsl": "load forecast\n\nforecast.main()\n",
    "src/forecast.lsl": FORECAST,
    "src/icons.lsl": "# Weather icons\n",
    "src/settings.lsl": "# Settings\n",
    "tests/test_forecast.lsl": "# Tests\n",
    "assets/sun.svg": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>\n",
    "assets/rain.svg": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>\n",
}


def build(s):
    out = os.path.join(s.tmp, "luxos-text")
    flags = subprocess.run(["pkg-config", "--cflags", "--libs", "gtksourceview-4", "x11"], capture_output=True,
                           text=True, check=True).stdout.split()
    f = s.src("luxos-text/files")
    subprocess.run(["gcc", "-O2", '-DLUXOS_TEXT_VERSION="1.0.0"', "-o", out, os.path.join(f, "luxos-text.c"),
                    os.path.join(f, "text-core.c")] + flags, check=True, timeout=300)
    return out


def shots(s):
    ed = build(s)
    proj = os.path.join(s.home, "Projects", "weather-widget")
    for rel, text in FILES.items():
        s.write(os.path.join("Projects", "weather-widget", rel), text)
    s.write(".config/luxos/text-editor.conf", "[window]\nsidebar-width=210\n")
    env = {"LUXOS_TEXT_DATA_DIR": s.src("luxos-text/files"), "LUXOS_TEXT_NEW_PROCESS": "1",
           "LUXOS_TEXT_ICON": s.src("luxos-branding/files/icons/luxos-notes.png")}

    # 1: slozka v postrannim panelu, kod v LSL se zvyraznenim a osnovou
    p = s.launch([ed, proj, os.path.join(proj, "src", "forecast.lsl")], env=env)
    win = s.window(pid=p.pid, size=(1040, 700))
    s.sleep(1.5)
    s.key("ctrl+l", win)
    s.type("12", win, delay=0.3)
    s.key("Return", win, delay=0.8)
    s.capture("1", win)

    # 2: Markdown s hledanim a nahrazovanim
    p2 = s.launch([ed, os.path.join(proj, "README.md")], env=env)
    win2 = s.window(pid=p2.pid, size=(1040, 700))
    s.sleep(1.0)
    s.key("ctrl+h", win2)
    s.type("widget", win2, delay=0.4)
    s.key("ctrl+h", win2)
    s.type("applet", win2, delay=0.8)
    s.capture("2", win2)
