# LuxOS geocoder

Own lightweight geocoder for typeahead in LuxOS Maps (`luxos-maps` Suggester). Answers like Photon
(`/api?q=&lat=&lon=&limit=&lang=` → GeoJSON FeatureCollection), so the Maps client parser is shared.
Coverage: Czechia + Slovakia (more countries: add the Geofabrik extract and its admin levels to
`COUNTRY_LEVELS` in `scripts/geocoder/build.py`, then widen `GEOCODER_COVERAGE` in `luxos_maps.py`).

| File | What |
|------|------|
| `luxos_geocoder.py` | the service (Python 3 stdlib only: asyncio HTTP/1.1 + sqlite3 FTS5) |
| `luxos-geocoder.service` | systemd unit (DynamicUser, ProtectSystem=strict, MemoryMax=200M, CPUQuota=100%, localhost only) |
| `Caddyfile.snippet` | `handle_path /geocode/*` for `luxos.lux-ai.cz` (no access log, gzip/zstd) |
| `deploy.sh` | upload a DB + install/update the service from the admin's PC |
| `tests/` | `python3 -m unittest server/geocoder/tests/test_geocoder.py` (tiny Prague/Brno OSM fixture) |
| `../../scripts/geocoder/build.py` | builds the SQLite DB from OSM extracts |
| `../../scripts/geocoder/bench.py` | sanity checks + p50/p95 latency of 200 typical typeahead queries |

## Why Python and not LSL

LSL 0.10.8 has `httpserver`, but SQLite only through the `sqlite3` CLI (a new process and a new open
of a ~1 GB database per query, no shared page cache) and LSL is not installed on the Debian server.
Python 3 with sqlite3/FTS5 is part of every Debian. `http.server` is not meant for production, so the
service has its own small asyncio HTTP/1.1 server (keep-alive, 8 KB header limit, no request bodies,
30 s idle timeout) and runs only on 127.0.0.1 behind Caddy (TLS, compression).

## Database

One SQLite file (`geocoder.sqlite`, schema 1), read-only on the server (`immutable=1`, `query_only`):

- `feat` – one row per suggestion: kind (city/stop/street/poi/address), name, translations
  (`name:cs/sk/en/de/...` as JSON), folded name variants (alt_name, short_name, official_name …),
  street, house number, postcode, town, district, region, country, lat/lon (1e-6 deg integers),
  OSM id, OSM key/value, importance. **Row id = importance rank** (1 = most important).
- `fts` – contentless FTS5 (`detail=none`, `unicode61 remove_diacritics 2`, `prefix='2 3 4'`) over
  names + context (town, district, street, house number) + a grid-cell token (`zq<row>x<col>`,
  ~22 × 22 km).
- `str`, `tag`, `meta` – interned strings, OSM tags, build info (`built`, `data`, `features`).

What is in it: places (city … hamlet, suburbs/quarters), streets (segments with the same name in one
municipality within 1.5 km merged), addresses (`addr:housenumber` or conscription/street number with
`addr:street` or `addr:place`), POIs (amenity, shop, tourism, leisure, historic, healthcare …; no
benches, waste baskets …), public transport stops (stations, halts, tram/bus stops and platforms with
the same name in one municipality within 700 m merged into one). Municipality, district (admin level
10), region and country come from the OSM boundaries, rasterised to a ~150 m grid during the build
(no shapely/GEOS needed). Objects outside CZ/SK (the extracts overlap the borders) are dropped.

### Query

1. Words of the query are folded (no accents, lower case); words of ≥ 2 characters go to FTS as
   prefix terms (`"vodickova"* AND "30"*`); 1-character words are filtered afterwards in Python
   (no 1-char prefix index – it would be large and slow).
2. `MATCH … LIMIT 150` returns the 150 **most important** matches (rowid order) without sorting all
   matches; with a position a second query adds `AND (9 cells around the position)`.
3. The ≤ 300 candidates are scored: whole name starts with the query (+3, exact +0.5), all words
   in the name (+2), some (+share), house number match for addresses (+0.8), `2 × importance`,
   `−0.6 × log10(1 + distance km)`; the same name and kind within 300 m is listed once.
4. Each query has a 0.4 s SQLite budget (progress handler); expensive queries return no results
   instead of blocking a worker.

## Build

Build host only (never the server): Python ≥ 3.9 with FTS5, `pip install osmium` (pyosmium 4),
~1.5 GB RAM, ~6 GB temporary disk (node location index + staging DB, in `--work`).

```bash
python3 -m venv ~/geocoder-venv && ~/geocoder-venv/bin/pip install osmium
curl -LO https://download.geofabrik.de/europe/czech-republic-latest.osm.pbf
curl -LO https://download.geofabrik.de/europe/slovakia-latest.osm.pbf
nice -n 10 ~/geocoder-venv/bin/python scripts/geocoder/build.py -o geocoder.sqlite \
    --work /path/with/space czech-republic-latest.osm.pbf slovakia-latest.osm.pbf
python3 scripts/geocoder/bench.py geocoder.sqlite
```

Small `.osm` XML files (tests) are read with the standard library, no pyosmium needed.

**Weekly rebuild**: the GitHub Actions workflow `Geocoder data` (`.github/workflows/geocoder.yml`) runs
every Monday 03:17 UTC (or by hand), downloads fresh Geofabrik extracts (md5 checked), runs the tests,
builds, checks/benchmarks and uploads the artifact `geocoder` (`geocoder-<date>.sqlite.zst`,
`SHA256SUMS`, `build.log`, kept 14 days). Nothing is pushed to the server from GitHub; the admin
deploys:

```bash
gh run download <run-id> -n geocoder -D /tmp/geocoder
(cd /tmp/geocoder && sha256sum -c SHA256SUMS)
GEOCODER_SSH=root@<server> server/geocoder/deploy.sh /tmp/geocoder/geocoder-*.sqlite.zst
```

## Deploy

`deploy.sh DB [ssh-target]` checks the DB locally, uploads it with rsync to
`/var/lib/luxos-geocoder/releases/<stamp>/` (`.partial` + sha256 check + rename), installs
`/opt/luxos-geocoder/luxos_geocoder.py` and the unit, switches the `current` symlink atomically,
enables/restarts the service, checks `/health`, keeps the last 2 releases and prints the Caddy block.
The running service also notices a new `current` by itself within 30 s (no restart needed for data).
`deploy.sh --service-only` updates just the code and unit.

The Caddy block is added by hand once (see `Caddyfile.snippet`): inside `luxos.lux-ai.cz { }`, before
other `handle` blocks, then `caddy validate` and `systemctl reload caddy`.

## Limits and privacy

- `q` ≤ 100 characters (400 otherwise), `limit` 1–10 (default 7), at most 8 words, GET/HEAD only.
- Rate limit per client IP (last `X-Forwarded-For` entry, trusted only from localhost = Caddy):
  burst 40, 10 requests/s – Maps sends at most ~7/s while typing; 429 with `Retry-After: 1`.
- No query is ever written anywhere: no access log in the service, errors are logged without the
  query, Caddy `log_skip` for `/geocode/*`. The rate limiter keeps IP → counter only in memory.
- Memory: RSS ~30–40 MB (2 workers × 8 MB SQLite cache); database pages live in the kernel page
  cache (counted towards `MemoryHigh=150M`/`MemoryMax=200M` of the unit, reclaimed under pressure).
  `--mmap-mb` / `GEOCODER_MMAP_MB` can map the DB instead (faster cold queries, higher RSS).

Data © OpenStreetMap contributors, ODbL.
