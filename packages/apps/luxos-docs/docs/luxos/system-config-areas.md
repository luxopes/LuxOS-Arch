# Whole-system configuration: network, printers, power, boot and new users

Part of [system-config.md](system-config.md) (`lux system`, `/etc/luxos/system.lsl`): the settings beyond packages, services and users. As everywhere in the file, a missing setting means "leave it as it is", and `lux system diff` / `apply` / `fix` show, confirm and apply the changes after a snapshot.

## The generated file

`init` (and `show`) write the file in groups, each with a short explanation in the **language of
the system** (`LANG` in `/etc/locale.conf`). Shortened:

```lsl
# LuxOS - configuration of the whole system in one file (LSL)
# A missing setting or a deleted section means "leave it as it is": only what is written here is managed.
# Passwords are never stored here (users, Wi-Fi, VPN): they stay in the system.
load config

config = {
    # ── Computer and language ──────────────────────────────
    "hostname": "lux-pc"
    "locale": "cs_CZ.UTF-8"
    "formats": {"LC_TIME": "cs_CZ.UTF-8"}
    "console": {"keymap": "cz-qwertz"}
    # ── Software ───────────────────────────────────────────
    "packages": ["base", "firefox", "linux-luxos", ...]
    "drivers": ["nvidia-open-dkms"]
    "repos": {"list": ["luxos", "luxos-apps", "luxos-drivers", "core", "extra"], "community": True, ...}
    # ── Network ────────────────────────────────────────────
    "network": {
        "connections": {
            "Home": {
                "type": "wifi"
                "ssid": "Novakovi"
                "security": "wpa-psk"   # password: kept by the system
                "autoconnect": True
                "ipv4": {"method": "auto"}
                "ipv6": {"method": "auto"}
            }
        }
    }
    # ── Printers ───────────────────────────────────────────
    "printers": {"default": "HP_LaserJet", "queues": {...}}
    # ── Power ──────────────────────────────────────────────
    "power": {"lid": "suspend", "lid_on_power": "suspend", "suspend_after_minutes": 0, "profile": "balanced"}
    # ── Boot ───────────────────────────────────────────────
    "boot": {"timeout": 0, "default": "luxos"}
    "kernel": {"params": ["quiet", "splash"], "scheduler": "lavd"}
    # ── Updates and security ───────────────────────────────
    "security": {"faillock": {"deny": 20, "fail_interval": 30, "unlock_time": 60}}
    # ── Defaults for new users ─────────────────────────────
    "new_users": {
        # "theme": "dark"
        # "dock": ["luxos-launchpad", "firefox", "thunar", "luxos-terminal", "trash"]
    }
}
```

Users are written without passwords and without `password_hash`; network connections without
their Wi-Fi/VPN passwords. As a normal user `lux system show` leaves out what only root can read
(network connections, kernel parameters on the EFI partition) and says so in a comment.

## Settings

| Setting | Value | Applied with |
|---|---|---|
| `formats` | other formats than the language: `{"LC_TIME": "cs_CZ.UTF-8", "LC_PAPER": ...}`; `None` = as the language | `LC_*` in `/etc/locale.conf` (+ `locale-gen`) |
| `console.keymap`, `console.font` | keyboard and font of the text console | `KEYMAP`, `FONT` in `/etc/vconsole.conf` (after a restart) |
| `drivers` | driver packages – from `[luxos-drivers]` and the graphics/Wi-Fi drivers the Drivers app installs (NVIDIA, Broadcom); kept apart from `packages` so it is clear what they are. Without the key, installed drivers stay as they are (also with `remove_unlisted`) | `lux install --repo`, `lux remove` |
| `network.connections` | saved NetworkManager connections, see [Network](#network) | `nmcli connection add/modify/delete` |
| `printers.queues` | CUPS printers: `{"NAME": {"uri": "ipp://...", "model": "everywhere", "shared": False}}`; `model` is `"everywhere"` (driverless) or a driver from `lpinfo -m` (name or description) | `lpadmin -p`, `lpadmin -x` |
| `printers.default` | the default printer | `lpadmin -d` |
| `power.lid`, `power.lid_on_power` | closing the lid on battery / with the power adapter: `"suspend"`, `"hibernate"`, `"suspend-then-hibernate"`, `"lock"`, `"poweroff"`, `"ignore"` | `HandleLidSwitch`, `HandleLidSwitchExternalPower` in `/etc/systemd/logind.conf.d/zz-luxos-system.conf` (logind reloads it) |
| `power.suspend_after_minutes` | sleep after so many minutes without use (0 = never) | `IdleAction`, `IdleActionSec` (same file) |
| `power.profile` | `"power-saver"`, `"balanced"`, `"performance"` (not changed while Battery Saver is on) | `powerprofilesctl set` |
| `boot.timeout` | seconds the boot menu is shown (0 = hidden, hold Space) | systemd-boot: `bootctl set-timeout` (EFI variable, `loader.conf` of LuxOS Care stays); GRUB: `GRUB_TIMEOUT` |
| `boot.default` | `"luxos"` = the newest working LuxOS (with the automatic fallback to the previous kernel), or another entry, e.g. `"auto-windows"`; snapshot entries are refused | `bootctl set-default` (EFI variable); GRUB: `GRUB_DEFAULT` |
| `security.faillock` | sign-in lockout after wrong passwords: `deny` failures within `fail_interval` seconds lock for `unlock_time` seconds (LuxOS: 20 / 30 / 60; 0 is refused – nobody is locked out until an administrator helps) | `/etc/security/faillock.conf` (other lines and comments stay) |
| `new_users` | defaults for NEW users, see [Defaults for new users](#defaults-for-new-users) | `/etc/luxos/new-users.conf` |
| `repos` | `list` of repositories, `community` (AUR), `review_build_scripts`, `flatpak_updates` – **only checked**: a difference is a warning in `diff`, `lux system` never changes `/etc/lux/lux.conf` | (edit `/etc/lux/lux.conf`, `lux config check`) |

## Network

```lsl
"network": {
    "connections": {
        "Office": {
            "type": "ethernet"          # "wifi" or "ethernet" (other kinds: only autoconnect is managed)
            "interface": "enp3s0"       # optional
            "autoconnect": True
            "ipv4": {"method": "manual", "addresses": ["192.168.10.5/24"], "gateway": "192.168.10.1",
                     "dns": ["192.168.10.1", "1.1.1.1"]}
            "ipv6": {"method": "disabled"}
            "proxy": "http://proxy.firma.cz/proxy.pac"   # "" = no proxy
        }
        "Home": {"type": "wifi", "ssid": "Novakovi", "security": "wpa-psk"}
    }
}
```

- **Passwords are never in the file** ("password: kept by the system"). A key such as `password`,
  `psk` or `secret` is refused. A new Wi-Fi connection with a password is created without it; it is
  asked for the first time the computer connects and then stays in NetworkManager.
- `security`: `"none"` (open), `"wpa-psk"` (WPA2 password), `"sae"` (WPA3), `"owe"`, `"wep"`; enterprise
  Wi-Fi (`"wpa-eap"`, 802.1x) needs certificates and an account – connect it once in Settings ›
  Network, then the file manages its other settings. `ipv4.method`: `"auto"` (DHCP), `"manual"`,
  `"disabled"`, `"link-local"`, `"shared"`; `ipv6.method` also `"dhcp"` and `"ignore"`. `"ipv4": "auto"`
  is a short form.
- Only listed keys are compared; changes are made with `nmcli connection modify` and apply at the next
  connection (the connection is not restarted).
- **The connection in use is protected** (a remote computer must not lose its network): a change of
  it is shown with `!` and needs a separate question (default *no*); with `-y` it is left out unless
  `--force` is given. A connection in use that was deleted from the file is kept (a note says so)
  and is deleted only with `--force`. Connections that were never in the file are never deleted.
- The connections are read from `/etc/NetworkManager/system-connections` (root only); `show` as a
  normal user leaves them out.

## Defaults for new users

```lsl
"new_users": {
    "theme": "auto"                       # "light", "dark" or "auto" (by sunrise and sunset)
    "wallpaper": "/usr/share/backgrounds/luxos/luxos-dark.jpg"
    "dock": ["luxos-launchpad", "firefox", "thunar", "luxos-terminal", "trash"]
    "browser": "firefox"
    "text_editor": "luxos-text"
    "mail": "thunderbird"
    "lock_after_minutes": 10              # 0 = do not lock
    "screen_off_minutes": 20              # 0 = never
}
```

The values are written to `/etc/luxos/new-users.conf`; `luxos-session` uses them **once, at the
first sign-in of a new user** (local or from a domain): appearance, wallpaper, the Dock (names of
`.desktop` files, `"trash"` = Trash), default apps (`xdg-mime`), screen lock and screen off.
**Existing users keep their settings** – change them in Settings. `None` returns a key to the LuxOS
default. Displays: the resolution and scale are personal settings of each user (Displays); LuxOS
keeps no system-wide display setting, so they are not in the file.

