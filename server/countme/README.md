# LuxOS countme

Anonymous weekly count of LuxOS installations, modelled on Fedora's DNF `countme`. Each LuxOS
computer sends at most one small request per week. The server counts it into a weekly counter and
keeps nothing else. The public result is `https://luxos.lux-ai.cz/stats/usage.json`, which the
website dashboard draws.

| File | What |
|------|------|
| `luxos_countme.lsl` | the service (LSL, compiled to one static binary) |
| `luxos-countme.service` | systemd unit (DynamicUser, StateDirectory, ProtectSystem=strict, MemoryMax=64M, localhost only) |
| `Caddyfile.snippet` | `handle /countme` (no access log) and `handle /stats/usage.json` for `luxos.lux-ai.cz` |
| `deploy.sh` | compile, test and install the binary and unit from the admin's PC |
| `tests/test_countme.py` | `python3 -m unittest server/countme/tests/test_countme.py` |

## What is counted

```
GET /countme?v=1.0.0&arch=x86_64&ch=stable&age=1
```

| Param | Allowed values |
|-------|----------------|
| `v` | LuxOS version, `^[0-9]{1,2}\.[0-9]{1,3}\.[0-9]{1,3}$` |
| `arch` | `x86_64` |
| `ch` | `stable`, `staging` |
| `age` | `1` = first week of the install, `2` = up to 1 month, `3` = up to 6 months, `4` = longer |

- The request must have exactly these 4 params, each once, in any order, with no percent-encoding
  and no `+`. It must be `GET` or `HEAD`, have no body and a target of at most 160 characters.
  Anything else gets `400`.
- A valid request always gets `204` with an empty body, whether it was counted or ignored as a
  duplicate or over the rate limit. The answer tells the client nothing.
- `GET /stats/usage.json` returns `200 application/json`, recomputed at most every 10 minutes:

```json
{"schema":1,"generated":"2026-11-07T10:00:00Z","current_week":"2026-W45",
 "weeks":["2026-W20", "...", "2026-W45"], "week_start":["2026-05-11", "...", "2026-11-02"],
 "totals":[...], "by_age":{"1":[...],"2":[...],"3":[...],"4":[...]},
 "by_channel":{"stable":[...],"staging":[...]}, "by_version":{"0.9.10":[...],"1.0.0":[...]},
 "by_arch":{"x86_64":[...]}}
```

  `weeks` holds the last 26 ISO weeks in ascending order, including the current partial week.
  `week_start` holds their Monday dates. Every array is aligned with `weeks`. `by_version` lists
  only versions seen in the window, sorted by version number.
- `GET /health` returns `ok`. Every other path gets `404`.
- ISO weeks start on Monday and use UTC. The key is `YYYY-Www` with the ISO year, so 2027-01-01
  belongs to `2026-W53`, which starts on 2026-12-28.

## Privacy guarantees

- **On disk** there is only `/var/lib/luxos-countme/counts.json` (mode 0600, directory 0700):
  `{"schema":1,"counts":{"2026-W45":{"1.0.0|x86_64|stable|1":12,...}}}`. Counters are keyed only
  by (ISO week, v, arch, ch, age). No IP address, IP hash, user agent, salt or timestamp finer than
  the ISO week is ever written to disk, stdout, stderr or the journal.
- **Deduplication** stays in memory only. The key is
  `HMAC-SHA512(weekly_salt, ip|v|arch|ch)`, truncated to 63 bits, stored in an open-addressing hash
  table: an `IntArray` of 2^20 slots, about 8 MB. Each IP is counted at most once per ISO week for
  each (v, arch, ch).
- **The weekly salt** is 32 random bytes from the kernel (`random.SystemRandom`). It lives only in
  memory. It is replaced, and the dedupe table cleared, when the ISO week changes.
- **The hourly rate limit** also stays in memory: at most 60 requests per IP per hour (HMAC of the
  IP), cleared every hour. Requests over the cap still get `204` and are ignored.
- **Memory is bounded.** After 500 000 dedupe entries in one week, new entries are not counted for
  the rest of that week. After 65 536 distinct IPs in one hour, new IPs are ignored until the next
  hour. A week keeps at most 5 000 distinct `v|arch|ch|age` keys, so fake versions cannot grow the
  file. Each limit logs one line, without any IP.
- **The client IP** is the last comma-separated element of `X-Forwarded-For`. Caddy sets this
  header to the real peer and drops a client-supplied one. Without the header the IP is the literal
  `none`. The service listens only on 127.0.0.1, and the unit allows only localhost
  (`IPAddressAllow=localhost`).
- **Nothing is logged per request.** Caddy's `/countme` block uses `log_skip`. The service prints
  only its start line, its stop line and errors, none of which contain an IP. Core dumps are off
  (`LimitCORE=0`).
- **Writes are atomic and debounced.** The service writes `counts.json.tmp` (chmod 0600), then
  `rename(2)`, only when a counter changed, at most once per 30 s. The 1 s accept loop also writes
  when there is no traffic. On `SIGTERM` (`systemctl stop/restart`) it writes the counters before
  exiting. A crash or `SIGKILL` loses at most the last 30 s.
- **A corrupt state file** (bad JSON, wrong schema, or any key or value outside the allowed format)
  is renamed to `counts.json.corrupt-<ISO week>`, or `...-2` and so on if that name exists. It is
  never deleted. The service then starts empty.

### This is a heuristic

- Many computers behind one IP (NAT, a school or company network, CGNAT) count **once** per week
  for each version and channel, so the numbers are a lower bound.
- A machine that changes IP during the week (VPN hopping, a laptop moving between networks) can be
  counted a few extra times.
- Nobody can be tracked across weeks. The salt changes every week, and only aggregate counters are
  stored.

## Test

```bash
python3 -m unittest server/countme/tests/test_countme.py      # compiles luxos_countme.lsl first
COUNTME_BIN=/path/to/luxos-countme python3 server/countme/tests/test_countme.py
```

Each test starts its own instance on a free 127.0.0.1 port, with a temp state dir and
`--clock-file`. The clock file is a test-only hook: the service reads the current unix time from it
on every use, so tests can move between hours and weeks. A second hook, `--max-entries N`, makes
the dedupe bound testable. The production unit passes neither.

The tests cover:
- validation (`400`/`404`, methods, body, length, percent-encoding);
- aggregation and the shape of `usage.json`;
- ISO week edges (2026-12-27/28, 2027-01-01, 2027-01-04);
- dedupe, including `X-Forwarded-For` handling and the missing header;
- the hourly cap, weekly salt rotation and the dedupe table bound;
- persistence (debounced write without traffic, `SIGKILL` loss, `SIGTERM` flush, restart);
- corrupt state files and the 10-minute stats cache;
- no IP persisted: state dir and process output are grepped for the test IPs, hex digests and long
  numbers, and the state file may hold only week keys and allowed count keys.

Local run:

```bash
lsl compile server/countme/luxos_countme.lsl /tmp/luxos-countme
mkdir -p /tmp/countme-state && /tmp/luxos-countme --bind 127.0.0.1 --port 8766 --state /tmp/countme-state
curl -i 'http://127.0.0.1:8766/countme?v=1.0.0&arch=x86_64&ch=stable&age=1'    # 204
curl -s http://127.0.0.1:8766/stats/usage.json
```

## Deploy

```bash
COUNTME_SSH=root@<server> server/countme/deploy.sh
```

`deploy.sh [ssh-target]` takes these steps:
1. Compiles the static binary locally and checks that `file` reports it as statically linked.
2. Runs the test suite against that binary.
3. Installs `/opt/luxos-countme/luxos-countme` (0755, via `.new` + `mv`) and
   `/etc/systemd/system/luxos-countme.service`.
4. Runs `daemon-reload`, `enable` and `restart`. The restart flushes the counters, and the state
   in `/var/lib/luxos-countme` is kept.
5. Checks `/health`, an invalid `/countme` (expects `400`, so nothing is counted) and
   `/stats/usage.json` on 127.0.0.1:8766.
6. Prints the Caddy block.

The server needs only systemd, rsync, curl and Caddy. LSL is not installed there.

Add the Caddy block by hand once (see `Caddyfile.snippet`): put it inside `luxos.lux-ai.cz { }`,
before the other `handle` blocks, then run `caddy validate` and `systemctl reload caddy`. On Caddy
older than 2.8, use `skip_log` instead of `log_skip`.

## Resources

RSS is about 14 MB: two hash tables of 8 MB and 2 MB plus the runtime. When the week changes it
peaks at about 21 MB until the old table is collected. Measured locally: 20 000 requests from
distinct IPs, p50 1.3 ms and p99 2.1 ms per request including the Python client, with no memory
growth. The unit sets `MemoryHigh=48M`, `MemoryMax=64M`, `TasksMax=8` and `CPUQuota=50%`.

The service is single-threaded: one accept loop with a 1 s accept timeout and 5 s socket read and
write timeouts. That is enough behind Caddy, which sends each request to the upstream in one piece.
It must not be exposed directly.

## Why LSL

LuxOS policy prefers LSL for new code. `lsl compile` produces one static ELF of about 400 KB with
no runtime dependencies, so nothing has to be installed on the Debian server. The binary does not
JIT. It runs under `MemoryDenyWriteExecute=yes` and `SystemCallFilter=@system-service
~@privileged`, which was checked with `systemd-run --user`.

LSL details this service relies on:
- `load crypto` is not used, because it links `libcrypto.so.3` dynamically. HMAC-SHA512 is built
  on `_random_hash.digest` (SHA-512), checked against Python's `hmac`.
- `rename(2)`, `chmod(2)` and the signal mask (`rt_sigprocmask` / `rt_sigpending` for a clean
  `SIGTERM` flush) are raw syscalls in `unsafe:` blocks.
- `httpserver.serve()` cannot run code between requests, so the service has its own accept loop.
  It uses the module's `listen_ipv4` / `accept_client` / `serve_client`.
- A `Dictionary` with 500 000 Int keys needs about 70 MB, so the dedupe set is an `IntArray` hash
  table instead.
- The handler cannot set response headers, so Caddy adds `Cache-Control`.
