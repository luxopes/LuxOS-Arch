# Whole-system configuration in one file (lux system)

The whole LuxOS system can be described in **one file written in LSL**, `/etc/luxos/system.lsl`,
similar to `configuration.nix` in NixOS: the wanted packages, Flathub apps, services, users and
groups, computer name, language, time zone, keyboard layouts, LuxOS Care, Lux Guard, the firewall
and kernel parameters. `lux system` compares the file with the running system, shows the
differences and applies them only after confirmation. A system snapshot is taken first, so
`lux rollback` returns everything to the state before.

## Quick start

```bash
sudo lux system init     # write /etc/luxos/system.lsl from this computer
lux system edit          # edit it (sudoedit), then it is checked
lux system diff          # what would change
sudo lux system apply    # snapshot, show the changes, ask, apply
lux rollback             # back to the snapshot taken before the apply
```

`lux system show` prints the same file as `init` without writing anything (as a normal user the
kernel parameters are left out, they can be read only by root). On an existing installation the
generated file describes the computer exactly, so `lux system diff` right after `init` says
"The system already matches the configuration".

## Commands

| Command | What it does |
|---|---|
| `lux system show` | print a configuration made from this computer (no passwords) |
| `lux system init [--force]` | write `/etc/luxos/system.lsl` from this computer; `--force` overwrites (old file kept as `system.lsl.bak`) |
| `lux system edit` | edit the file with `sudoedit` (`$EDITOR`, default nano) and check it |
| `lux system check [FILE]` | evaluate and validate the file, nothing is changed |
| `lux system diff [FILE] [--json]` | list the changes `apply` would make (needs administrator rights to read password hashes, firewall rules and boot entries) |
| `lux system apply [FILE] [-y] [--no-snapshot]` | snapshot, changes, confirmation, apply |
| `lux system show --origin [--json]` | the merged configuration (organization policies + your file) with the origin of every value and 🔒 for locked values |
| `lux system locks [--json]` | the settings an organization has locked (`config.mkForce` in `/etc/luxos/system.d`) |

`check`, `diff` and `plan` accept `--no-policies` to look at your file alone; `apply` always
includes the organization policies.

Without `FILE` the commands use `/etc/luxos/system.lsl`. `lux system` alone prints a short help.
Nothing is ever applied without showing the changes and a confirmation, unless `-y` is given.
Without a terminal and without `-y`, `apply` changes nothing. When the changes remove packages
or apps, the default answer is "no".

## Example file

```lsl
load config

laptop = True
office = ["libreoffice-fresh", "hunspell-en_us"]

config = {
    "hostname": "lux-laptop"
    "timezone": "Europe/Prague"
    "locale": "cs_CZ.UTF-8"
    "keyboard": {
        "layouts": ["us", "cz(qwerty)"]
        "options": ["grp:shifts_toggle"]
    }
    "packages": [
        "firefox",
        "htop",
        config.mkIf(laptop, "tlp")
    ] + office
    "flatpaks": ["org.signal.Signal"]
    "remove_unlisted": False
    "services": {
        "enable": ["sshd", "cups.socket"]
        "disable": ["bluetooth"]
    }
    "groups": ["family"]
    "users": {
        "anna": {
            "description": "Anna Novakova"
            "groups": ["wheel", "family"]
            "shell": "/bin/bash"
        }
    }
    "care": {"mode": "carefree", "keep_snapshots": 5}
    "guard": {"enable": True, "home_snapshots": True}
    "firewall": {"enable": True, "allow": ["22/tcp"]}
    "kernel": {"params": ["quiet", "splash"]}
}

assertions = [
    [len(config["users"]) > 0, "at least one user is needed"]
]
```

A longer commented example is installed as `/usr/share/doc/lux/system.lsl.example`.

## Settings

Only what is in the file is managed. A missing setting means "leave it as it is", so a file
can be as short as `config = {"packages": ["htop"]}`.

| Setting | Value | Applied with |
|---|---|---|
| `hostname` | computer name, e.g. `"lux-pc"` | `hostnamectl set-hostname` |
| `timezone` | e.g. `"Europe/Prague"` (`timedatectl list-timezones`) | `timedatectl set-timezone` |
| `locale` | e.g. `"cs_CZ.UTF-8"` (must be in `/usr/share/i18n/SUPPORTED`) | `/etc/locale.gen` + `locale-gen`, `LANG` in `/etc/locale.conf` (other `LC_*` lines stay) |
| `keyboard.layouts` | up to 4 XKB layouts, variant in brackets: `["us", "cz(qwerty)"]`; a plain list is accepted too | `localectl set-x11-keymap` (login screen, console, all users) |
| `keyboard.options` | XKB options, e.g. `["grp:shifts_toggle"]` | same |
| `packages` | packages from the LuxOS and Arch Linux repositories | `lux install --repo`, `lux remove` |
| `flatpaks` | Flathub app IDs, e.g. `"org.mozilla.firefox"` (system-wide) | `flatpak install --system flathub` |
| `remove_unlisted` | `True` also removes installed packages and Flathub apps that are not listed (default `False`) | `lux remove`, `flatpak uninstall` |
| `services.enable` | systemd units started at boot; without a suffix `.service` is added | `systemctl enable --now` |
| `services.disable` | units to turn off | `systemctl disable --now` |
| `groups` | extra groups to create | `groupadd` |
| `users` | normal users (UID 1000 and more), see below | `useradd`, `usermod`, `gpasswd`, `chpasswd -e` |
| `care.mode` | `"carefree"` (automatic updates) or `"classic"` (only notify) | `MODE` in `/etc/luxos/care.conf` |
| `care.snapshots` | `True`/`False`: snapshot before every update | `SNAPSHOTS` in `care.conf` |
| `care.keep_snapshots` | how many snapshots to keep (2-50, default 5) | `SNAPSHOT_KEEP` in `care.conf` |
| `care.protect` | `True`/`False`: system protection, `/usr` read-only except during package changes (see `system-protection.md`); applied at once | `PROTECT` in `care.conf`, `luxos-care protect apply` |
| `care.verify` | `True`/`False`: weekly verification of system files (default `True`) | `VERIFY` in `care.conf` |
| `guard.enable` | Lux Guard on/off | `luxos-guard.service` |
| `guard.home_snapshots` | hourly snapshots of `/home` | `luxos-guard-snapshot.timer` |
| `firewall.enable` | firewall on/off (ufw; added to the packages automatically when on) | `ufw enable`, `ufw.service` |
| `firewall.allow` | incoming ports allowed from anywhere: `"22/tcp"`, `"8000:8010/udp"`, `"53"` | `ufw allow`, `ufw delete allow` |
| `kernel.params` | extra kernel parameters | `options` of the LuxOS systemd-boot entries or `GRUB_CMDLINE_LINUX_DEFAULT` + `grub-mkconfig` |
| `domain.admins` | domain groups that administer this computer (only in a domain, see `domain.md`) | `lux domain admins add/remove` (sudo + polkit) |
| `domain.allow_groups` | domain groups allowed to sign in; `[]` = everybody in the domain | `lux domain login allow/deny` |
| `domain.offline_days` | days a domain account may sign in without the domain controller (0-180, default 30) | `lux domain set offline-days` |
| `domain.admin_offline_days` | days administrator rights from the domain last offline (0-180, default 7, at most `offline_days`) | `lux domain set admin-offline-days` |

### Users

```lsl
"users": {
    "anna": {
        # full name
        "description": "Anna Novakova"
        # exactly these groups; wheel = administrator
        "groups": ["wheel", "family"]
        # must be in /etc/shells
        "shell": "/bin/bash"
        # optional, only for new users
        "uid": 1000
        # optional, output of: openssl passwd -6
        "password_hash": "$6$..."
    }
}
```

- **Passwords never go into the file.** A `password` key is refused. A new user without
  `password_hash` cannot log in until you run `sudo passwd NAME` (the diff reminds you). The hash is
  never printed and is passed to `chpasswd -e` on standard input.
- `groups` is the complete list of extra groups (the user's own group is not listed). Groups that
  do not exist yet are created at apply time, unless an installed package created them first.
- Users are never deleted, and system accounts (`root`, UID under 1000) cannot be managed.
- At least one user must stay in `wheel` (administrator); a change that would remove the last
  administrator is refused.

## Organization policies (/etc/luxos/system.d)

A computer managed by an organization (a Windows domain, later LuxOS Directory) gets **policy
fragments** next to your file. They are LSL files like `system.lsl`, owned by root, named
`NN-name.lsl` and merged in the order of their names:

```
/etc/luxos/system.d/
  20-org-base.lsl        from LuxOS Directory (do not edit)
  30-org-group-ucetni.lsl
  40-domain-gpo.lsl      from the Group Policy of a Windows domain
/etc/luxos/system.lsl    your own file (or the local IT)
```

A fragment may name its organization and policy, which then appear in every message:

```lsl
load config

config = {
    "policy": {"organization": "Firma s.r.o.", "name": "Základ"}
    "packages": ["libreoffice-fresh", "firefox"]
    "firewall": {"enable": config.mkForce(True)}
    "care": {"mode": config.mkForce("carefree"), "keep_snapshots": config.mkDefault(8)}
}
```

Merge rules:

| Value in a fragment | Meaning |
|---|---|
| plain value | the organization's setting; **your file wins** when it sets the same key; a later fragment (higher number) wins over an earlier one |
| `config.mkDefault(v)` | only a recommendation, weaker than any other value |
| `config.mkForce(v)` | **locked**: your file may set the same value, a different one is an error: `firewall.enable: set by the organization Firma s.r.o. „Základ“ (20-org-base.lsl), it cannot be changed here`. `mkForce` on a dictionary locks the whole section, also keys the policy does not list. Two fragments forcing different values are an error too. |

- Lists of packages, Flathub apps, groups, services, firewall ports, kernel parameters and the
  `domain` group lists are **joined** (organization + yours). A forced item cannot be turned the
  other way locally (e.g. a service the organization forces on cannot be in your `disable`).
- `lux system diff` lists the policies and marks each change that comes from one, e.g.
  `+ install: libreoffice-fresh  [Firma s.r.o. „Základ“ (20-org-base.lsl)]`; `--json` adds
  `"origin"`. `lux system show --origin` answers "why is it set like this?" for every value.
- A fragment that other users than root could change (group/world-writable, not owned by root)
  stops `lux system` with an error; files with other names are ignored with a warning.
- **Leaving the organization** removes its fragments: the locks disappear and the values stay as
  they are. Packages, apps, services and kernel parameters that came only from a policy are never
  removed because the policy disappeared - only items of your own file are tracked for removal.
- Each apply keeps copies of the fragments in `/var/lib/lux/system/history/DATE.d/` and writes the
  locks to `/var/lib/lux/system/policy.json` (readable by all, no secrets) so that settings apps can
  show "set by your organization". `lux rollback` returns the whole system to the snapshot taken
  before the apply, as for your own file.
- Locks are not a security boundary against `root` (who can edit the fragments); they protect
  organization settings from accidental local changes and make the result explainable.

## What gets removed

- A package, Flathub app, enabled service or kernel parameter that **was in the file at the last
  apply and has been deleted from it** is removed, turned off or dropped at the next apply. This is
  remembered in `/var/lib/lux/system/applied.json` (`init` records the starting state).
- Packages and apps that were **never in the file** stay, unless `"remove_unlisted": True`. The
  diff says how many such packages there are.
- Never removed: `base`, kernels (`linux*`), `lux`, `lux-engine`, `luxos-care`, `luxos-desktop`,
  `luxos-branding`, `luxos-keyring`, `luxos-i18n`, `lsl`, `python`, `pyalpm`, `systemd`, `sudo`,
  `glibc`, `bash`, `filesystem`, `linux-firmware`. Units such as `dbus*`, `systemd-journald`,
  `systemd-logind`, `luxos-care*` and the display manager cannot be turned off.
- Kernel parameters for the disk and encryption (`root=`, `rw`, `cryptdevice=`, `rd.luks.*`,
  `resume=`, `luxos.*`, ...) are set by the installer and cannot be set or removed here.

## How apply works

1. The file is evaluated by `lsl config` and validated (as `lux system check`).
2. The current state is read and the changes are listed (as `lux system diff`).
3. Confirmation (unless `-y`).
4. LuxOS Care takes a read-only system snapshot (`luxos-care snapshot --kind system`, in the boot
   menu as "LuxOS (before system change of ...)"). If the snapshot fails (e.g. the system is not on
   Btrfs), you are asked whether to continue; with `-y` the apply stops unless `--no-snapshot` is
   given. The package transaction inside the apply does not take a second snapshot.
5. Changes in this order: groups, packages, Flathub apps, computer name, time zone, language,
   keyboard, users, services, Lux Guard, LuxOS Care, firewall, kernel parameters, and finally the
   removals.
6. On the first error the apply stops, says how many changes were made and prints
   `lux rollback SNAPSHOT` to return to the state before. The remembered state is updated only
   after a successful apply; a copy of each applied file is kept in `/var/lib/lux/system/history/`
   (last 20).

Apply is idempotent: running it again with the same file finds nothing to do. It is refused
while LuxOS runs from a snapshot (keep that version with `lux rollback` first) and when another
`lux system apply` is running.

## Safety of the configuration file

- The file is evaluated by **`lsl config`**, the pure LSL configuration evaluator: only
  `load config` is allowed, and reading files, running programs, the network, environment
  variables and time are refused before the code runs; an endless loop stops after 30 s.
- Run as root, the evaluation additionally runs as the user `nobody` without privileges
  (`setpriv --no-new-privs`) on a copy of the file and the `*.lsl` files next to it.
- LSL only produces JSON; all changes are made by `lux_system.py` with fixed commands (no shell)
  and validated values (package names, unit names, user names, ports, kernel parameters).
- Keep the file owned by root (`init` writes it as `0644`); with a `password_hash` inside, consider
  `chmod 600 /etc/luxos/system.lsl`.

## LSL rules for beginners

- Texts are in double quotes, `True`/`False` and `None` start with a capital letter.
- Lists: `["a", "b"]`; items are separated by commas, **no comma after the last item** (the error
  then says "expected an expression"). A list may span several lines.
- Dictionaries: `{ "key": value }`, one entry per line, no commas needed between lines.
- `#` starts a comment.
- Variables and arithmetic work as in normal LSL: `office = [...]` and then `"packages": [...] + office`.
- `config.mkIf(condition, value)` leaves the value out when the condition is `False`, also inside
  lists: `config.mkIf(laptop, "tlp")`.
- `imports = ["laptop.lsl"]` merges another file next to `system.lsl` (relative paths only; lists
  are joined). Merge priorities `config.mkDefault` / `config.mkForce` work as described in
  [the LSL configuration reference](../lsl/stdlib-system.md#config-and-lsl-config).
- `assertions = [[condition, "message"]]` stop the evaluation with your own message.

## Errors

- Syntax and evaluation errors show the file, line and column from LSL, with a hint for the most
  common mistakes (comma after the last list item, `load` of other modules, reading files).
- Wrong settings are listed all at once with their place, e.g.
  `packages[2]: "Bad Name" is not a valid package name` or
  `config: unknown setting "hostnme" (did you mean "hostname"?)`.
- `These packages are not in the repositories: ...` - check the name with `lux search NAME`
  (packages from the community/AUR cannot be listed in the file).
- `Unknown service X` - the unit does not exist (a unit from a package installed in the same
  apply is accepted).
- Messages follow the system language (luxos-i18n, e.g. Czech).

## Files

| Path | Purpose |
|---|---|
| `/etc/luxos/system.lsl` | the configuration (root-owned) |
| `/etc/luxos/system.d/NN-name.lsl` | organization policies (root-owned, merged before your file) |
| `/var/lib/lux/system/applied.json` | what the file managed at the last apply (for removals) |
| `/var/lib/lux/system/policy.json` | policies and locked settings of the last apply (readable by all) |
| `/var/lib/lux/system/history/` | copies of the last 20 applied files (and policies in `DATE.d/`) |
| `/usr/share/doc/lux/system.lsl.example` | commented example |
| `/usr/lib/lux/lux_system.py` | evaluation, diff and apply |
