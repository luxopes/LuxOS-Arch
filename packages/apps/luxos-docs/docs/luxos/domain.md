# Organization network: Windows domain (lux domain)

LuxOS joins an existing **Microsoft Active Directory** domain (Windows Server 2016-2025) or a
**Samba 4 AD** domain without any change on the domain side. Domain users then sign in on the
LuxOS login screen with their domain name and password, get a home folder, open the shared
folders and printers of the organization without another password, and the administrators of
the domain administer the computer. Signing in keeps working offline from a cached password.

It is the package **luxos-domain** (`lux install luxos-domain`) with the command `lux domain`, the
settings page **Settings > Organization Network** (`luxos-domain-settings`), a step in the
installer and in the Setup Assistant. Underneath are the standard tools: **SSSD** (users, groups,
sign-in, offline cache), **Kerberos** (tickets in SSSD KCM), **adcli** (computer account and
keytab) and **realmd** (domain discovery). realmd and adcli are not in the Arch Linux repositories;
LuxOS ships verified copies in its own repository (`[luxos]`), never from the community (AUR).

## Quick start

```bash
lux domain discover firma.local             # find the domain controllers, check the clock
sudo lux domain join firma.local -U admin   # join (asks for the password of the domain admin)
lux domain status                           # online/offline, offline sign-in, administrators
```

Then sign out. On the login screen choose **Other…** and type the domain name: `jan`,
`jan@firma.local` or `FIRMA\jan`. Domain users who have signed in before appear as normal
tiles with their picture.

In the graphical way: **Settings > Organization Network** → type the domain (pre-filled from the
network) → **Find** shows e.g. "Microsoft Active Directory – firma.local – 2 controllers" → the name
and password of a domain administrator → **Join**. The progress is shown step by step.

## Commands

| Command | What it does |
|---|---|
| `lux domain discover DOMAIN [--json]` | find the domain controllers (`adcli info`), short domain name and clock difference; no root needed |
| `lux domain join DOMAIN -U ADMIN [--ou OU] [--computer-name NAME] [--admins "G1,G2"]` | join the computer (details below) |
| `lux domain leave [-U ADMIN]` | leave the domain; with `-U` the computer account in the domain is deleted as well |
| `lux domain status [--json]` | domain, computer name, online/offline, last contact, days of offline sign-in left, administrator groups and whether their rights are active |
| `lux domain admins add/remove/list GROUP` | domain groups whose members administer this computer (`sudo` and the LuxOS administrator dialogs) |
| `lux domain login allow/deny/list GROUP` | only these domain groups may sign in (empty = everybody the domain allows) |
| `lux domain set offline-days N` | how many days domain accounts may sign in without the domain controller (0-180, default 30; 0 = never offline) |
| `lux domain set admin-offline-days N` | how many days administrator rights from the domain last offline (0-180, default 7) |
| `lux domain share add/remove/list URL [NAME]` | shared folders of the organization, added as bookmarks in Files at sign-in |
| `lux domain printer add/remove/list NAME URI` | printers of a Windows print server (`smb://print.firma.local/Printer`) with Kerberos |
| `lux domain sync-time` | set the clock from the domain controller (Kerberos allows at most 5 minutes) |

Commands that change the system ask for administrator rights (`sudo`). `--yes` skips the
confirmation, `--password-stdin` reads the password from the first line of standard input,
`--progress` prints machine-readable progress lines (`@@STEP n total text`, `@@ERROR code text`,
`@@DONE`), used by Settings and the installer.

## What join does

1. Finds the domain (`adcli info`) and checks the clock difference to the domain controller
   (LDAP `currentTime`); more than 5 minutes stops the join with "Set the clock from the domain".
2. Takes a system snapshot (LuxOS Care) - `lux rollback` can undo the whole join.
3. Saves the original `/etc/pam.d/system-auth`, `/etc/nsswitch.conf`, `/etc/krb5.conf`, ...
   to `/var/lib/luxos/domain/backup/`.
4. Creates the computer account with `adcli join` (the password goes to adcli on standard input,
   never as an argument; with `--ou` into that organizational unit) and the keytab
   `/etc/krb5.keytab`. SSSD renews the computer password every 30 days.
5. Writes `/etc/sssd/sssd.conf` (0600), `/etc/krb5.conf` (KCM tickets), the LuxOS
   `/etc/pam.d/system-auth` with `pam_sss` and `pam_mkhomedir`, adds `sss` to `passwd`, `group`
   and `shadow` in `/etc/nsswitch.conf`, enables **Other…** on the login screen, a client
   `/etc/samba/smb.conf` (only if there was none) and Kerberos sign-in to the organization's web
   sites in Firefox (`SPNEGO` in `/etc/firefox/policies/policies.json`).
6. Administrators: `sudo` rule `/etc/sudoers.d/50-luxos-domain` (checked with `visudo` first) and
   polkit rule `/etc/polkit-1/rules.d/49-luxos-domain-admins.rules` for "Domain Admins" (or
   `--admins`); "LuxOS Admins" is added automatically when this group exists in the domain.
7. Starts `sssd.service`, `sssd-kcm.socket` and `luxos-domain-refresh.timer`.

If any step fails, everything is put back as before (files, keytab, services) and the error is
explained. **The password of the domain administrator is never stored**: not in files, logs,
arguments or the environment. The installer and Settings pass it only on standard input.

### Common errors

| Message | What to do |
|---|---|
| The domain was not found in DNS | the computer must use the DNS server of the organization (usually from DHCP); check `resolvectl status` |
| No domain controller answered | wrong name or no network to the domain controller |
| The clock differs by more than 5 minutes | `sudo lux domain sync-time` (or the button in Settings): sets the clock from the domain controller and uses it as the time server |
| The administrator name or password is not correct | the account must be allowed to add computers |
| This account may not add computers | ask IT for the right, or for a pre-created computer account |
| This is not an Active Directory domain | FreeIPA and plain Kerberos realms are not supported |

## Signing in

- **Names** (decision R4): domain users have short names on the computer: `jan`. If a local
  account with the same name exists, the domain account gets the full name `jan@firma.local` and
  the home folder `/home/jan@firma.local` (`sss_override`, checked every 10 minutes); the local
  account stays as it is. `lux domain status` lists such full names.
- **Home folder** `/home/jan` is created at the first sign-in from `/etc/skel` (the same LuxOS
  desktop and Dock as for local users), with access only for the user (umask 077). Network home
  folders are not used (slow, do not work offline).
- **Offline** (decision R5): after one successful online sign-in, SSSD keeps a salted hash of the
  password (root-only cache). Without the domain controller the user signs in with it for
  `offline-days` (default 30) days after the last contact. The login screen shows "Offline – you
  will sign in with your saved password (N more days)", which is different from a wrong
  password. The first sign-in on a computer needs the network to the domain (or a VPN).
- **Expired password**: the login screen asks for the current and the new password (PAM password
  change) and continues.
- **Account locked or disabled in the domain**: the login screen says so ("Account is locked by
  the domain administrator."). LuxOS itself never locks accounts after mistakes, only at the rate
  of a brute-force attack (20 failures in 30 s → 1 minute).
- **Group Policy** "Allow/Deny log on locally" applies (SSSD `ad_gpo_access_control = enforcing`),
  also to unlocking the screen. With `lux domain login allow GROUP` only the listed groups may
  sign in (SSSD `simple` access) and the Group Policy log-on rights are not used.
- Screen lock, `sudo` and administrator dialogs check the domain password the same way.
- Fingerprint sign-in works for domain accounts after the first password sign-in.

## Administrators

The local account created during installation always stays an administrator (emergency access).
Members of the administrator groups of the domain get `sudo` and the LuxOS administrator dialogs
(LuxOS Care "Update now", printers, Lux Guard, ...).

**Offline limit** (decision R5): administrator rights from the domain last only
`admin-offline-days` (default **7**) after the last contact with the domain controller. Then
`luxos-domain-refresh` turns the `sudo` and polkit rules off (`lux domain status`: "suspended until
the next connection") and turns them on again as soon as the domain controller answers. This
limits a stolen computer or a person removed from the administrators while the computer was away.

The refresh runs 30 s after boot, every 10 minutes and on every network change
(NetworkManager dispatcher), and writes the state for the login screen to
`/run/luxos/domain/status.json`.

## Shared folders, printers, web

- **Files (Thunar/gvfs)**: `smb://fs.firma.local/data` opens without a password, with the Kerberos
  ticket from sign-in. `lux domain share add smb://fs.firma.local/data "Company data"` adds it as a
  bookmark in Files for every domain user at the next sign-in (only bookmarks, no permanent
  mounts - fast and offline-safe).
- **Command line**: `gio mount smb://fs.firma.local/data`, or `mount -t cifs` with
  `sec=krb5,cruid=$UID` (cifs-utils).
- **Printers**: `sudo lux domain printer add Tiskarna smb://print.firma.local/Tiskarna` adds a CUPS
  queue with `auth-info-required=negotiate` (Kerberos) and the generic PostScript driver
  (`--model` for another one). Driverless network printers keep working as before.
- **Web**: Firefox uses Kerberos for `*.firma.local` (intranet, Exchange, SharePoint).

## Leaving

`sudo lux domain leave` (or **Leave…** in Settings) takes a snapshot, stops SSSD, puts back the
original PAM, NSS, Kerberos, Samba and Firefox settings, removes the administrator rules, the
login-screen change, the domain Group Policy fragment (`/etc/luxos/system.d/40-domain-gpo.lsl`),
the printers from the domain, the keytab and the SSSD cache with the saved password hashes.

**Home folders and personal files of domain users are not deleted** (decision R8); `leave` lists
them. With `-U ADMIN` the computer account is also deleted in the domain; if that is not allowed,
the computer leaves anyway and IT can delete the account later.

A copy of the last state is kept in `/var/lib/luxos/domain/left.json`.

## Installer, Setup Assistant and automatic installation

- **Installer** (graphical and text): step **Organization** - "Me" or "An organization (Windows
  domain)" with the domain, the administrator, the password and optionally the organizational unit.
  The computer joins at the end of the installation (`lux-domain join --offline-install` inside the
  new system). If it fails, the installation still finishes and says "Join it later in Settings >
  Organization Network".
- **Setup Assistant** (computer prepared by a seller, OEM): the same step after the account; the
  owner's local account is created first.
- **install.conf**: `DOMAIN=firma.local`, `DOMAIN_USER=admin`, `DOMAIN_PASSWORD=...`,
  `OU=OU=Computers,DC=firma,DC=local` (also `DOMAIN_OU=`), optional `DOMAIN_ADMINS="Domain
  Admins,IT"`. Pass the file on standard input (`luxos-install --config - --yes`) so the
  password never touches a disk.

## lux system and Group Policy

In `/etc/luxos/system.lsl` (see `system-config.md`) the key `domain` manages the same settings
declaratively:

```lsl
"domain": {
    "admins": ["Domain Admins", "IT"]
    "allow_groups": []
    "offline_days": 30
    "admin_offline_days": 7
}
```

An organization can lock them with `config.mkForce` in a policy fragment in
`/etc/luxos/system.d/` (`lux system locks` lists the locks).

## Files

| Path | Purpose |
|---|---|
| `/var/lib/luxos/domain/state.json` | domain, computer, groups, settings, last contact (no secrets) |
| `/var/lib/luxos/domain/backup/` | original files restored by `leave` |
| `/run/luxos/domain/status.json` | online/offline for the login screen |
| `/etc/sssd/sssd.conf` | SSSD, generated from `/usr/share/luxos/domain/sssd.conf.tmpl` |
| `/etc/krb5.conf`, `/etc/krb5.keytab` | Kerberos, computer account keys |
| `/etc/sudoers.d/50-luxos-domain` | `sudo` for the administrator groups |
| `/etc/polkit-1/rules.d/49-luxos-domain-admins.rules` | administrator dialogs for the groups |
| `/etc/lightdm/lightdm.conf.d/70-luxos-domain.conf` | "Other…" on the login screen |
| `/usr/lib/luxos/domain/luxos-domain-helper` | fixed root actions for Settings (polkit `org.luxos.domain.manage`) |
| `journalctl -t luxos-domain` | audit: join, leave, administrator changes, suspended rights |

## Limits

- Supported: one AD domain (forest trusts work through SSSD but are not tested), SSSD with ID
  mapping from SIDs (POSIX attributes in AD are not needed).
- Not yet: LuxOS settings from Group Policy templates (ADMX), domain logon scripts, network home
  folders, VPN before sign-in.
