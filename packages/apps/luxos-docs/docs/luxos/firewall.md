# LuxOS Firewall

LuxOS has a firewall that is **on by default** (package `luxos-firewall`; installed
systems get it with `lux update`, without a restart). It blocks new incoming
connections from the network. Apps on the computer can still use the internet as before, and the
things LuxOS itself needs keep working: getting an address (DHCP, IPv6), printers and scanners on
the network, LuxDrop, network time, updates, Tailscale.

The firewall never breaks something silently: when it blocks a connection to a program that is
listening on this computer, LuxOS shows a notification **"<App> wants to accept connections from
the network"** with **Allow** and **Keep Blocked**, and the program is listed in
**Settings › Firewall** under *Recently blocked*.

## Something stopped working on the network

If another device cannot connect to this computer (a phone opening a development web server, a
game server, a database, a shared folder of another app):

1. Look for the notification "… wants to accept connections from the network" and press **Allow**.
   That allows the port for devices on **this network only** (not the internet).
2. Or open **Settings › Firewall**: *Recently blocked* lists the blocked programs with an **Allow**
   button; *Allow a port* adds any port.
3. Or in Terminal:

```bash
luxos-firewall status                 # what is allowed and what was blocked recently
luxos-firewall allow 8080             # TCP and UDP 8080 from this network only
luxos-firewall allow 5432/tcp         # only TCP
luxos-firewall allow 25565/tcp --from any   # also from the internet
luxos-firewall deny 8080              # block it again
```

To check whether the firewall causes a problem at all, turn it off for a moment
(`luxos-firewall off`, or the switch in Settings › Firewall), try again and turn it back on
(`luxos-firewall on`). Turning it off removes all LuxOS rules immediately; the computer then
accepts connections exactly as without a firewall.

## What is allowed automatically

| What | Ports | From |
|---|---|---|
| Replies to connections this computer started (web, updates, DNS, NTP, printing …) | – | everywhere |
| Loopback (`localhost`), containers and virtual machines of this computer (`podman*`, `docker0`, `virbr*`, Waydroid …) | all | this computer |
| Getting an address: DHCP, IPv6 router advertisements, neighbour discovery, DHCPv6, path MTU | – | everywhere |
| mDNS (printers, scanners, LuxDrop, `.local` names) and replies when searching for devices (SSDP, WS-Discovery, SNMP, Canon BJNP, Epson, NetBIOS, LLMNR) | 5353 and replies | this network |
| Ping | ICMP echo | this network |
| LuxDrop (while it runs; 47924 only while folder sharing is on; also ports changed in its settings) | TCP 47923-47924, TCP/UDP 53317 | this network |
| Steam Remote Play and game transfer (while Steam runs) | UDP 27031-27036, TCP 27036-27037 | this network |
| KDE Connect / GSConnect (while it runs) | TCP/UDP 1714-1764 | this network |
| Syncthing (while it runs) | TCP/UDP 22000, UDP 21027 | this network |
| Printer sharing (only when CUPS shares printers, e.g. `cupsctl --share-printers`) | TCP 631 | this network |
| SSH server (only while `sshd` is enabled or running; ports from `sshd_config`) | TCP 22 | everywhere |
| Tailscale (when installed; WireGuard port from `/etc/default/tailscaled`) | UDP 41641 | everywhere |
| Internet sharing / hotspot from NetworkManager: DHCP and DNS for the connected devices | UDP 53, 67, 547, TCP 53 | the shared interface |

**This network** means private addresses (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, link-local
169.254.0.0/16, IPv6 fc00::/7 and fe80::/10) and the networks the computer is directly connected
to right now (so public IPv6 addresses of devices in your home network count too). The list of
connected networks follows Wi-Fi and cable changes within 10 seconds. VPN interfaces (`wg*`,
`tun*`, `ppp*`) and Tailscale are not "this network".

**App ports only while the app listens.** For LuxDrop, Steam, KDE Connect and Syncthing only the
ports from the table on which the app is listening right now are open (sets `app_tcp`/`app_udp`,
updated every 2 seconds by `luxos-firewall-watch.service`; a connection attempt to such a port opens
it at once when the app listens). An installed app that is not running – or LuxDrop with folder
sharing off – has no open port. Steam Remote Play and LAN game transfer work as soon as Steam runs;
nothing to set up. `luxos-firewall status --json` lists for each app rule `"when": "running"` and the
ports that are `"open"` now.

Everything else is blocked, for example a database or development server started by a rootless
Podman container (`-p 5432:5432`): it works on the computer itself (`localhost` and the computer's
own address), but other devices cannot reach it until you allow the port.

Apps installed later (Steam, KDE Connect, SSH turned on) are picked up automatically: after
`lux install`, when a service is enabled, when CUPS or Tailscale settings change and when a system
Flathub app is installed. Flathub apps installed only for one user are found at the next start or
via the notification.

## Settings › Firewall

`luxos-firewall-settings` (Settings › Firewall, or search for "Firewall"):

- **Firewall** switch – on/off (asks for the administrator password once).
- **Allowed automatically** – the table above, as detected on this computer.
- **Your exceptions** – each allowed port with *This network only* / *Everywhere* and **Remove**;
  **Allow a port** adds one (TCP, UDP or both).
- **Tailscale** (when Tailscale is installed) – *Treat Tailscale devices as this network*: LuxDrop
  and your "this network only" exceptions then accept connections from your Tailscale devices too.
  Off by default; Tailscale's own features (Taildrop, Tailscale SSH, MagicDNS) work either way.
- **Recently blocked** – programs that wanted connections, with **Allow**.

## Notifications

`luxos-firewall-watch.service` reads the kernel log of blocked connections (at most 30 per minute)
and checks with `ss` whether a program on this computer listens on that port. Only connections
from this network and from Tailscale lead to a notification; port scans from the internet do not.
The notification appears once per port and session; **Allow** adds an exception for this network
after the administrator password (polkit `auth_admin_keep`, remembered for a few minutes: opening a
port is a change to the protection of the whole computer), **Keep Blocked** stores the port in
`~/.config/luxos/firewall-ignored` and LuxOS does not ask again. Blocked connections to ports where
nothing listens (scans) are only counted.

## How it works

- Rules are in their own nftables table `inet luxos` (`sudo nft list table inet luxos`). The
  firewall never touches other tables: Tailscale (`ts-input`, `ts-forward`), Podman/netavark,
  libvirt, Docker or ufw keep theirs. Every change replaces the table in one transaction, so there
  is never a moment without rules and a failed load leaves the previous state.
- Only incoming traffic to this computer is filtered (`input`); forwarding (containers, virtual
  machines, Tailscale exit node and subnet routing) and outgoing traffic are not changed.
- `luxos-firewall.service` loads the rules at boot before the network starts; if loading fails,
  the network stays open and `luxos-firewall status` shows the error (it never locks you out).
- `luxos-firewall-refresh.path` reloads the rules when `/etc/luxos/firewall.json`, enabled services,
  `sshd_config`, `cupsd.conf`, `/etc/default/tailscaled` or system Flathub apps change; a package
  manager hook does the same after `lux install`/`lux remove`. Starting or stopping `sshd`
  (`systemctl start sshd`) opens or closes the SSH port right away (a drop-in in
  `sshd.service.d`/`sshd.socket.d` reloads the rules).

| File | Content |
|---|---|
| `/etc/luxos/firewall.json` | on/off, `trust_tailscale`, exceptions (`port`, `proto`, `from`: `lan`/`any`, `app`) |
| `/run/luxos-firewall/state.json` | loaded rules, detected apps, connected networks (readable by all users) |
| `/run/luxos-firewall/requests.json` | recently blocked programs (for notifications and Settings) |

## Command line

| Command | What it does |
|---|---|
| `luxos-firewall status [--json]` | state, automatic rules, exceptions, recently blocked programs |
| `luxos-firewall on` / `off` | turn the firewall on or off (stays after a restart) |
| `luxos-firewall allow PORT[/tcp\|/udp] [--from lan\|any] [--app NAME]` | add an exception; `PORT` can be a range `8000-8010`; default `--from lan` |
| `luxos-firewall deny PORT[/tcp\|/udp]` | remove an exception |
| `luxos-firewall tailscale on` / `off` | treat Tailscale devices as this network |
| `luxos-firewall render` | print the nftables rules without loading them |

Commands that change something ask for the administrator password (pkexec) when run without
`sudo`.

## In /etc/luxos/system.lsl

The whole-system configuration ([system-config.md](system-config.md)) has a `firewall` section:

```
"firewall": {"enable": True, "allow": ["22/tcp"], "allow_lan": ["5432/tcp", "8000:8010"]}
```

`allow` = open from everywhere, `allow_lan` = only from this network; a port without `/tcp` or
`/udp` means both. A listed key is the complete list: exceptions of the same kind that are not in
it are removed by `lux system apply`.

## Other firewalls

ufw or firewalld can still be installed; they use their own tables and a connection must then be
allowed by both. LuxDrop ships a firewalld service and a ufw profile for that case.
