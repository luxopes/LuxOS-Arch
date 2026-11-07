"""Pocasi: aktualni pocasi s predpovedi pro Prahu a destivy den v jinem ulozenem miste.

Open-Meteo nahrazuje mistni falesny server s odpovedi z testovacich dat
(packages/luxos-weather/tests/fixtures/forecast-prague.json); ostatni mista jsou z nej odvozena
(posun teplot a jine pocasi). luxos-weather pridava na zacatek sys.path /usr/lib/luxos/python -
spoustec v s.tmp proto nejdriv nacte luxos_i18n a luxos_weather z pracovni kopie.
"""
import copy
import http.server
import json
import os
import sys
import urllib.parse

# misto: (lat, lon, zeme, posun teploty, kod pocasi ted, kody pocasi po hodinach/dnech)
PLACES = [
    ("Praha", 50.088, 14.4208, "Česko", 0, None),
    ("Brno", 49.1952, 16.6080, "Česko", -1.5, 3),
    ("Wien", 48.2085, 16.3721, "Österreich", 1.0, 61),
    ("London", 51.5085, -0.1257, "United Kingdom", 2.5, 80),
    ("Barcelona", 41.3888, 2.159, "España", 8.5, 0),
]


def variant(base, shift, code):
    d = copy.deepcopy(base)
    if shift:
        cur = d["current"]
        for k in ("temperature_2m", "apparent_temperature"):
            cur[k] = round(cur[k] + shift, 1)
        d["hourly"]["temperature_2m"] = [round(t + shift, 1) for t in d["hourly"]["temperature_2m"]]
        for k in ("temperature_2m_max", "temperature_2m_min"):
            d["daily"][k] = [round(t + shift, 1) for t in d["daily"][k]]
    if code is not None:
        d["current"]["weather_code"] = code
        rainy = code in (61, 80)
        n = len(d["hourly"]["weather_code"])
        d["hourly"]["weather_code"] = [code if i % 5 else (3 if code else 1) for i in range(n)]
        if rainy:
            d["current"]["precipitation"] = 1.2
            d["current"]["relative_humidity_2m"] = 84
            d["daily"]["precipitation_sum"] = [4.6, 1.8, 0.4, 0.0, 0.6, 3.1, 0.2][:len(d["daily"]["time"])]
            d["hourly"]["precipitation_probability"] = [70 + (i * 7) % 25 for i in range(n)]
            d["daily"]["precipitation_probability_max"] = [80, 65, 40, 20, 35, 60, 30][:len(d["daily"]["time"])]
            d["daily"]["weather_code"] = [code, 3, 2, 1, 3, 61, 2][:len(d["daily"]["time"])]
        elif code == 0:
            d["hourly"]["precipitation_probability"] = [0] * n
            d["daily"]["precipitation_probability_max"] = [0] * len(d["daily"]["time"])
            d["daily"]["weather_code"] = [0, 0, 1, 2, 0, 1, 0][:len(d["daily"]["time"])]
        else:
            d["daily"]["weather_code"] = [3, 3, 2, 61, 3, 2, 3][:len(d["daily"]["time"])]
    return d


def shots(s):
    files = s.src("luxos-weather/files")
    with open(s.src("luxos-weather/tests/fixtures/forecast-prague.json"), encoding="utf-8") as f:
        base = json.load(f)
    answers = [((lat, lon), variant(base, shift, code)) for _n, lat, lon, _c, shift, code in PLACES]

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path != "/v1/forecast":
                self.send_response(404)
                self.end_headers()
                return
            lat, lon = float(q.get("latitude", 0)), float(q.get("longitude", 0))
            body = min(answers, key=lambda a: abs(a[0][0] - lat) + abs(a[0][1] - lon))[1]
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    port = s.serve_http(Handler)
    srv = "http://127.0.0.1:%d" % port
    cfg = {"locations": [{"name": n, "lat": lat, "lon": lon, "country": c, "tz": "Europe/Prague"}
                         for n, lat, lon, c, _s, _k in PLACES], "units": "auto", "selected": 0}
    s.write(".config/luxos/weather.json", json.dumps(cfg, ensure_ascii=False))
    env = {"LUXOS_WEATHER_API": srv + "/v1/forecast", "LUXOS_WEATHER_GEO": srv + "/v1/search",
           "LUXOS_WEATHER_IP": srv + "/ip", "LUXOS_WEATHER_TZ": "Europe/Prague",
           "LUXOS_WEATHER_ICONS": os.path.join(files, "icons"),
           # metricke jednotky jako v testech (en_US by ukazal °F)
           "LC_MEASUREMENT": "en_GB.UTF-8"}
    run = os.path.join(s.tmp, "luxos-weather-run")
    with open(run, "w", encoding="utf-8") as f:
        f.write("#!%s\nimport runpy, sys\nsys.path[:0] = %r\nimport luxos_i18n, luxos_weather  # pracovni kopie\n"
                "sys.argv[0] = %r\nrunpy.run_path(sys.argv[0], run_name='__main__')\n"
                % (sys.executable, [s.src("luxos-i18n/files"), files], os.path.join(files, "luxos-weather")))
    os.chmod(run, 0o755)
    s.python_env()

    p = s.launch([run], env=env)
    win = s.window(pid=p.pid, size=(1000, 700))
    s.sleep(2.5)
    s.capture("1", win)

    # 2: destivy den v jinem ulozenem miste (Wien v postrannim panelu)
    s.click(100, 170, win, delay=2.0)
    s.capture("2", win)

    # 3: podrobnosti (pocitova teplota, vlhkost, vitr, UV, tlak, vychod a zapad slunce) - London
    s.click(100, 221, win, delay=2.0)
    for _ in range(12):
        s.click(615, 450, win, button=5, delay=0.05)
    s.sleep(1.0)
    s.capture("3", win)
