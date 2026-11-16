# Anonymous usage count (countme)

LuxOS counts how many computers use it, without knowing **which** computers. Once a week each
installed LuxOS computer says "I am a LuxOS computer, version X" and nothing else. The idea and the
design come from Fedora's DNF "countme". The public results are on the website:
[luxos.lux-ai.cz/usage](https://luxos.lux-ai.cz/usage/) (Czech:
[/cs/pouzivani/](https://luxos.lux-ai.cz/cs/pouzivani/)).

It is **on by default** and easy to turn off (see [Turning it off](#turning-it-off)).

## What is sent

At most **once per calendar week** (ISO week starting on Monday, UTC), when the package manager
`lux` already downloads the package lists as root (LuxOS Care does this automatically, or
`sudo lux update`), it makes **one** small extra request to the LuxOS server with exactly four
values:

| Value | Where it comes from |
|---|---|
| LuxOS version, e.g. 1.0.1 | `/usr/lib/luxos/version`, else `VERSION_ID` in os-release |
| processor architecture | currently always x86_64 |
| update channel: stable or staging | `[general] channel` in `/etc/lux/lux.conf` |
| install age group: first week, up to 1 month, up to 6 months, or longer | install time (see below) |

The HTTP headers carry no cookies, no Python version and no computer name. To see the exact request
your computer would send, run `lux config countme` (see below).

**Not sent:** no unique ID, no machine-id, no computer name, no user name, no hardware, no list of
installed apps, no location, no files, nothing about what you do.

The `age` groups let the statistics show whether people **keep** using LuxOS (groups 3 and 4) or
only try it once (group 1), without any ID. Like in Fedora, this is the only reason for them.

## When it is not sent

- the setting is off (`countme = false`);
- not as root (user programs such as the Store never send it) and never from a user session;
- from the live ISO (the live system also has `countme = false`), in a container, or when `lux`
  works on another root directory (installer chroot);
- on a computer prepared for another person (OEM) before the owner finished the Setup Assistant —
  the owner sees the choice there; the install age then starts at the end of the Setup Assistant;
- when the package lists come only from non-LuxOS repositories;
- a second time in the same week.

## It never slows updates

The request runs in a background thread with a 5-second time limit, after the package lists were
already downloaded. Errors (offline, server down, slow network) are ignored; there are no retries
except at the next run of `lux`. In a terminal, `lux` never waits for it; a background service
(LuxOS Care) waits at most for the rest of the 5 seconds before it exits so the request can finish.
The week is recorded only after the server answered.

## State on your computer

`/var/lib/lux/countme` (readable, written by root):

```json
{"since": 1762520000, "last_week": "2026-W45"}
```

`since` is the install time (time of `/var/log/luxos-install.log` from the installer, or the end of
the Setup Assistant on OEM computers, or the first run); `last_week` is the last counted week.
Delete the file and the next count starts again in the first-week group.

See exactly what would be sent and whether this week was counted:

```
lux config countme
```

## What the server stores

The server (`server/countme/` in the LuxOS repository, a small service in LSL behind the web server)
keeps **only counters**: for each week, version, architecture, channel and age group, a number. It
does not store IP addresses, user agents or times finer than the week. Web server access logging is
switched off for these requests.

To make spamming harder (one computer sending many counts), the server remembers, **only in memory
and only for the current week**, a keyed hash (HMAC-SHA512 with a random key that is created every
week and never written anywhere) of the sender's network: the IPv4 address, or for IPv6 only the
network part (the first 64 bits, which one computer usually owns as a whole). Each network is
counted at most once per week, whatever values it sends, and only versions of LuxOS that were
actually released (or the next ones) are accepted. When the week changes, the key and the whole
table are thrown away. This is a heuristic: many computers behind one shared IP (a school, a
company, a VPN exit) count as one per week, so the numbers are an approximate lower bound.
Computers that are off or offline for a whole week are not counted either. The count cannot be made
tamper-proof without identifying computers, which LuxOS deliberately does not do: someone with many
IP addresses can still inflate it.

The aggregated numbers are public: `https://luxos.lux-ai.cz/stats/usage.json` (last 26 weeks:
totals, age groups, versions, channels).

## Turning it off

Any of these (each sets `[general] countme = false` in `/etc/lux/lux.conf`):

- **Software Update** (Aktualizace softwaru) › **Privacy** › switch "Anonymously report that this
  computer uses LuxOS";
- `lux config countme off` (it asks for the administrator password); `lux config countme on` turns it
  back on, `lux config countme` shows the state and the exact request;
- in [`/etc/luxos/system.lsl`](system-config.md): `"updates": {"countme": False}` and
  `sudo lux system apply`;
- edit `/etc/lux/lux.conf`: `countme = false` in `[general]` (a file in `/etc/lux/conf.d/` can also
  set it and wins over the main file);
- at installation: the checkbox on the Maintenance page of the installer (default on), in the text
  installer the question after the maintenance mode, or `COUNTME=0` in an unattended
  `install.conf`; on OEM computers the owner decides on the Maintenance page of the Setup Assistant.

Turning it off takes effect immediately; nothing is sent afterwards.

## Files

| File | Purpose |
|---|---|
| `/usr/lib/lux/lux_countme.py` | client (called by `lux_alpm.py` after the package lists were refreshed) |
| `/etc/lux/lux.conf` | `[general] countme = true\|false` |
| `/var/lib/lux/countme` | install time and last counted week |
| `/var/lib/lux/countme.lock` | prevents two counts at the same time |
