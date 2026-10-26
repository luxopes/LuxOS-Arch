# Router app (network administration)

The **Router** app (Czech: *Správa sítě*, command `luxos-router`, package `luxos-desktop`) shows your
network details, opens the router or modem web admin inside the app, lists devices on your home
network and runs quick tests. Start it from Launchpad or Search ("router", "network", "gateway").

## Overview tab

- **Network**: connection name and type (Wi‑Fi / Ethernet), Wi‑Fi network (SSID), interface,
  IP address, router (default gateway), IPv6 gateway, DNS servers, MAC address. The gateway is the
  default IPv4 route with the lowest metric (`ip -j route show default`); the other details come from
  NetworkManager (`nmcli -t device show`), DNS falls back to `/etc/resolv.conf`.
- **Public IP address**: only when you click **Show**. It asks `api.ipify.org` (fallback
  `icanhazip.com`).
- **Open Router Settings** switches to the Router tab.

**Quick Tests**:

| Test | What it does |
|---|---|
| Ping router | `ping -c 4` to the gateway, shows the average time and lost packets |
| Ping internet | `ping -c 4 1.1.1.1` |
| Name lookup (DNS) | looks up `example.com` with the system resolver and shows the time |
| Download speed | estimate: downloads 10 MB from `speed.cloudflare.com` (only on click) |

## Router tab (web admin)

The router's web page opens inside the app in WebKitGTK (`webkit2gtk-4.1`). It is already installed
on LuxOS because `yad` needs it, so the app adds no download. WebKit is loaded only when you open
this tab. The overview alone uses about 55 MB (PSS), the open router page about 250 MB in total
(app and two WebKit processes), freed when you close the app.

- **HTTP / HTTPS** switch in the toolbar (default `http://GATEWAY/`). Back, Reload and **Open in
  Browser** are next to it. The lock icon shows the connection type.
- **Home network only**: the page may navigate only to private addresses (10.0.0.0/8,
  172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, fc00::/7, fe80::/10) and to the gateway itself.
  A host name (for example `fritz.box`, `routerlogin.net`) is allowed only when it resolves to home
  network addresses only. A link you click that leads elsewhere opens in your normal web browser. A
  redirect without a click only shows a bar with **Open in Browser**. `file:`, `data:` and
  `javascript:` addresses are blocked; `localhost` opens in the browser.
- **Self-signed certificates**: routers often use a certificate that cannot be verified. The app
  asks "The router uses its own security certificate" and allows it only after **Continue**, only
  for the exact gateway address, and only until the app is closed. Untrusted certificates of other
  devices cannot be allowed.
- **No stored passwords**: the web view uses a temporary (ephemeral) session with no cookies, cache
  or form data on disk. HTTP sign-in (Basic/Digest) uses the app's own dialog, and the password is
  never saved. The app stores no credentials.
- Downloads (for example a configuration backup) go to the Downloads folder.

If WebKitGTK is missing, the tab offers **Open in Browser** instead.

## Devices tab

It lists devices your computer has seen on the network: the neighbour table `ip -j neigh`
(incomplete and failed entries hidden). Columns: address, device, MAC address, state (Active, Seen
recently, …). The router and this computer are marked.

- **Vendor** comes from the local IEEE OUI list `/usr/share/hwdata/oui.txt` (package `hwdata`),
  with no network lookup. Phones and newer laptops use a **random (private) MAC**. These show as
  "Private address (random MAC)" and have no vendor.
- **Search Network** pings every address of your IPv4 network once (at most a /24, 253 addresses,
  48 at a time), so quiet devices appear too. Then the list refreshes.

## For scripts and AI assistants

The logic is in `/usr/lib/luxos/python/luxos_netadmin.py` (no GTK): `default_gateway()`,
`network_info()`, `lan_policy(url, gateway)` (allow / resolve / external / block),
`tls_exception_allowed(url, gateway)`, `neighbours()`, `oui_lookup(macs)`, `ping(host)`,
`dns_test()`. Never put router passwords into files or commands. Change router settings only
through its web admin, with the user watching.
