# VM test plan: LuxOS in an Active Directory domain (luxos-domain, E1)

Laboratory with a **Samba 4 AD domain controller** and a **LuxOS client** in QEMU, on a private
network between the two VMs. Never run these scripts against a real domain, on the host system or
on the user's screen (each VM has its own QEMU window or VNC). No root rights are needed on the
host.

| File | Where it runs | Purpose |
|---|---|---|
| `vm-ad.sh` | host | `base DISK` (installed LuxOS as the base image), `dc`, `client` (qcow2 overlays), `reset` |
| `provision-dc.sh` | inside the DC VM (root) | Samba AD DC `LUXTEST.LAN` 10.77.0.1, users, groups, OU, share, printer, GPO |
| `setup-client.sh` | inside the client VM (root) | lab network 10.77.0.10 with DNS of the DC, local user `jan` (name clash) |
| `run-scenarios.sh [N...]` | host | scenarios 1-9 below through `scripts/vmctl.py`, PASS/FAIL + screenshots |
| `pam-auth.py` | inside the client (copied by run-scenarios) | PAM sign-in without a terminal (`lightdm` service), password change |
| `vmlink.py` | host | QMP `set_link` of the client's lab NIC (offline tests) |

## Network

Each VM has two NICs: `net0` user-mode NAT (internet: installing `samba` on the DC, packages on the
client) and `net1` a private L2 segment between the VMs (`-netdev socket,mcast=230.0.0.77:12377`,
no root, no bridge). DHCP is not used in the lab: DC 10.77.0.1 (Samba internal DNS, forwarder
10.0.2.3), client 10.77.0.10 with DNS 10.77.0.1 and search domain `luxtest.lan`.

## Steps

```bash
# 0. A normal LuxOS installation in out/test/disk.qcow2 (scripts/test-vm.sh live, install, power off)
scripts/vm-tests/domain/vm-ad.sh base out/test/disk.qcow2
# 1. Domain controller
scripts/vm-tests/domain/vm-ad.sh dc --headless &
LUXOS_VM_DIR=out/test-ad/dc scripts/vmctl.py ping
LUXOS_VM_DIR=out/test-ad/dc scripts/vmctl.py exec 'touch /etc/luxos-ad-lab'
LUXOS_VM_DIR=out/test-ad/dc scripts/vmctl.py put scripts/vm-tests/domain/provision-dc.sh /root/provision-dc.sh
LUXOS_VM_DIR=out/test-ad/dc scripts/vmctl.py exec 'bash /root/provision-dc.sh' 1800
# 2. Client (with luxos-domain from the build under test: lux install ./luxos-domain-*.pkg.tar.zst)
scripts/vm-tests/domain/vm-ad.sh client &
LUXOS_VM_DIR=out/test-ad/client scripts/vmctl.py ping
LUXOS_VM_DIR=out/test-ad/client scripts/vmctl.py put scripts/vm-tests/domain/setup-client.sh /root/setup-client.sh
LUXOS_VM_DIR=out/test-ad/client scripts/vmctl.py exec 'bash /root/setup-client.sh'
# 3. Join once, then all scenarios
scripts/vm-tests/domain/run-scenarios.sh            # or e.g.: run-scenarios.sh 3 5
```

Lab accounts (passwords only for the lab): `Administrator` / `Lab-Admin-2026`, `jan`, `eva` /
`Lab-User-2026`, `itadmin` (LuxOS Admins) / `Lab-It-2026`, `joiner` (may only add computers to
`OU=LuxOS`) / `Lab-Join-2026`, `locked` (disabled in AD), `expired` (must change the password),
`denied` (in "No Local Logon", denied by GPO). Groups: `LuxOS Admins`, `Účtárna`, `No Local Logon`.

## Scenarios

| # | Scenario | Automated checks (run-scenarios.sh) | By hand / screenshot |
|---|---|---|---|
| 1 | Discover and join | `discover` finds dc1; wrong password → `@@ERROR password` and no `sssd.conf`; clock +10 min → `@@ERROR clock`; sync-time; join as `joiner` into `OU=LuxOS` (account in that OU on the DC); leave without `-U` and re-join with the existing account; the admin password is in no file under `/etc`, `/var/lib/luxos`, `/var/log`, `/root` | Settings > Organization Network: Find, errors in plain language, progress steps; installer GUI/TUI with `DOMAIN=` (`install.conf` on stdin) and Setup Assistant step |
| 2 | Domain sign-in | PAM `lightdm` for `eva` online; `getent passwd eva` = short name, `/home/eva`, `/usr/bin/lsh`; home created from skel with mode 700 | greeter: **Other…** → name → password (screenshot), desktop and Dock like a local user, avatar tile after the first sign-in |
| 3 | Offline | link down → `/run/luxos/domain/status.json` `"online": false`; offline sign-in from cache ("cached credentials"); wrong password offline refused; `offline-days 1` + clock +3 days → refused | greeter shows "Offline – you will sign in with your saved password (N more days)" (screenshot), not "Incorrect password" |
| 4 | Expired / disabled | `expired` → "new password required", change succeeds; `locked` (disabled) refused | greeter asks Current / New / Repeat New Password; disabled account message |
| 5 | Administrators | `sudo -l -U itadmin` = ALL (LuxOS Admins added automatically); `eva` not allowed; polkit rule lists the group; **R5**: last contact 8 days ago + offline → rights suspended, online → back | LuxOS Care "Update now" as `itadmin` without password prompt; Settings shows "suspended until the next connection" |
| 6 | Group Policy | `denied` refused by GPO "Deny log on locally" (`sssctl user-checks -a acct -s lightdm`); `eva` allowed; `login allow Účtárna` → `jan` refused, then `login deny` | greeter message for a denied account |
| 7 | Shares, printers | `smbclient --use-kerberos=required //dc1/data` as `eva` after `kinit` lists `README.txt`; `printer add` queue has `auth-info-required=negotiate`; `share add` stored | Thunar: bookmark "Lab data" after sign-in, opens without a password; print a page to `pdf` |
| 8 | Leave, rollback, updates | `lux reinstall filesystem` keeps `sss` in nsswitch (hook); `leave -U Administrator` → `@@DONE`, `/home/eva` kept, `sss` removed, computer account deleted on the DC, local admin `sudo` works; join again | `lux rollback SNAPSHOT` taken before join returns the system before the join (boot menu entry); reboot after leave: login screen without "Other…" |
| 9 | Name clash (R4) | local `jan` stays `jan` (UID ≥ 1000); domain `jan` = `jan@luxtest.lan` with `/home/jan@luxtest.lan`; both sign in | greeter: local Jan tile and "Other…" → `jan@luxtest.lan` |

Before the 1.0 release additionally once by hand: **Windows Server 2022/2025 Evaluation** as the
DC (LDAP signing, channel binding, AES-only Kerberos), the same scenarios 1-7.

## Results

`run-scenarios.sh` prints one `PASS`/`FAIL` line per check and a summary; screenshots are in
`out/test-ad/shots/`. Failing checks: look at `journalctl -t luxos-domain`, `journalctl -u sssd`,
`sssctl domain-status luxtest.lan` and `/var/log/sssd/` in the client VM.
