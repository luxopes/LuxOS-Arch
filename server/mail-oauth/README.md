# Mail: sign in to LuxAI mailboxes with the LuxAI account

LuxOS Mail (`luxos-mail`) offers **Continue as <name>** when a LuxAI account is signed in on the
computer and adds the mailboxes the account may use on the LuxAI server (e.g. `info@lux-ai.cz`)
without a password. This folder holds the server side: a patch for the LuxAI account server, Dovecot
and Postfix configuration, fail2ban filters, the deploy/rollback scripts and their tests.

**Nothing here is deployed automatically.** `deploy.sh` is run by the administrator.

## How it works

```
LuxOS Mail ──GET /api/mail/mailboxes──▶ lux-account (127.0.0.1:3020, behind Caddy on lux-ai.cz)
  (cookie lux_account_session + X-Lux-Client: luxos, same as Lux Code / LuxAI)
           ──POST /api/mail/token {"address"}──▶ token (random 256 bit, 15 min, in memory only)
           ──IMAPS 993, AUTHENTICATE OAUTHBEARER/XOAUTH2──▶ Dovecot 2.4 (passdb oauth2)
                                         Dovecot ──POST /oauth/introspect (RFC 7662)──▶ lux-account
```

- **Which mailboxes an account may use** – `/etc/lux-account-mailboxes.json` (no secrets, 0640
  root:luxaccount). The deploy script creates it from the existing webmail rule in
  `/etc/roundcube/luxai-sso.inc.php` (see *Findings*): mailbox `info@lux-ai.cz` for the e-mails in
  `allowed_emails` that are in the group `luxai-admin`, plus the account id from `allowed_subject`.
  Format:

  ```json
  {"imap": {"host": "mail.lux-ai.cz", "port": 993, "security": "ssl"},
   "smtp": {"host": "mail.lux-ai.cz", "port": 465, "security": "ssl"},
   "mailboxes": [{"address": "info@lux-ai.cz", "display_name": "LuxAI",
                  "emails": ["<registration e-mail>"], "users": ["<account id>"],
                  "require_group": "luxai-admin"}]}
  ```

  An account matches a mailbox by id **or** registration e-mail (verified, not suspended) and must
  have `require_group` when set. Changes apply immediately (the file is re-read when it changes),
  also to tokens already issued.
- **Token** (`POST /api/mail/token`) – only for native clients with a valid session, only for a
  mapped mailbox, 30 per minute per account. It is bound to the account, the session and the
  mailbox; it is not an OIDC access token (`/oauth/userinfo` refuses it).
- **Introspection** (`POST /oauth/introspect`) – answers only direct loopback requests without
  proxy headers (Caddy always adds `X-Forwarded-For`, so from the internet the path is a 404) and
  only with the client `lux-dovecot` + secret (HTTP Basic). It re-checks expiry, the session (sign
  out / password change revokes), suspension and the mapping. Response:
  `{"active": true, "username": "<mailbox>", "sub", "client_id", "scope": "mail", "exp", "iat"}` or
  `{"active": false}`.
- **Dovecot** – `luxai-oauth2.conf`: `auth_mechanisms = plain login xoauth2 oauthbearer`;
  passwd-file only for `plain login` and only from `127.0.0.0/8 ::1/128` (`allow_nets`), so the
  mailbox password used by Roundcube cannot be tried from the internet; passdb oauth2 for
  `xoauth2 oauthbearer` with introspection (mode `post`). Dovecot 2.4 sends Basic auth only from the
  URL user info (not from `client_id`/`client_secret`), so the URL with the secret is in
  `luxai-oauth2-secret.conf` (0600 root). **`doveconf -n` prints that URL – never share its output
  without `grep -v introspection_url`.** `luxai-public.conf`: IMAPS 993 on all addresses with the Let's
  Encrypt certificate `/etc/lux-mail/tls/*` (until now Dovecot had the snakeoil certificate), port
  143 stays loopback-only, SASL socket `/var/spool/postfix/private/auth` for Postfix.
- **Postfix** – `submission` (587, STARTTLS required) and `submissions` (465, TLS): AUTH only after
  TLS, relay only after SASL login (via Dovecot, so the same token), the sender address must belong
  to the login (`/etc/postfix/luxai_sender_login`), `milter_macro_daemon_name=ORIGINATING` for
  OpenDKIM. Sending from Mail comes in phase 2; `--no-submission` skips this part.
- **fail2ban** – `luxai-dovecot` (993/143) and `luxai-postfix-sasl` (465/587), 5 failures in 10 min
  → 1 h ban on the mail ports. Own filters because the stock ones of fail2ban 1.1.0 do not match
  Dovecot 2.4 log lines (0 of 3 real lines) and do not know XOAUTH2/OAUTHBEARER in Postfix.
  Mail itself never retries a refused token (one attempt, then it waits for the user).
- **Firewall** – rule `tcp dport { 465, 587, 993 } … comment "luxai-mail-oauth"` added to
  `/etc/nftables.d/lux-filter.nft` (for the next boot) and live with `nft add rule` (never
  `nft -f /etc/nftables.conf`: it starts with `flush ruleset` and would drop the current fail2ban and
  LUX Guard bans). IPs banned by LUX Guard are dropped before (chain `lux_guard_scope`).

## Deploy

From a computer with SSH access as root:

```bash
# optional but recommended: tests against a local copy of the live server.js
scp root@185.183.156.25:/opt/lux-account/server.js /tmp/lux-account-server.js
export LUX_ACCOUNT_SERVER_JS=/tmp/lux-account-server.js
# optional: Dovecot 2.4 unpacked from the Arch package for the real-Dovecot tests (see Tests)
export LUX_DOVECOT_ROOT=/path/to/unpacked/dovecot

server/mail-oauth/deploy.sh                    # or: deploy.sh root@host --no-submission
```

`deploy.sh` runs the local checks, uploads this folder (without `tests/`) to
`/root/mail-oauth-<stamp>/` and runs `remote-apply.sh <stamp>` there. Each step stops on the first
error; the steps are idempotent (running again does not duplicate anything and keeps the secret):

1. checks: Dovecot 2.4, certificate, account server healthy, ports 993/465/587 free
2. backup of every touched file to `/root/mail-oauth-backup-<stamp>/` (files that did not exist are
   recorded as such)
3. secret: `/etc/lux-account-mail-oauth.env` (0600, `MAIL_INTROSPECTION_SECRET`,
   `MAIL_MAILBOXES_FILE`) and `/etc/dovecot/luxai-oauth2-secret.conf` (0600) – created once, never printed
4. mapping file from the Roundcube config (only when missing)
5. `server.js` patched with `account-server/mail_oauth_patch.py`, `node --check`, drop-in
   `lux-account.service.d/mail-oauth.conf` (EnvironmentFile), restart, checks: 401/403 without a
   session/client header, `{"active":false}` for an invalid token with the real secret
6. Dovecot files + two `!include_try` lines at the end of `/etc/dovecot/local.conf`, `doveconf -n`
   check (output hidden), restart, check that 993 listens with a certificate valid for
   `mail.lux-ai.cz` and offers `AUTH=OAUTHBEARER`, and that 143 is still loopback-only
7. `/usr/local/sbin/lux-mail-sync-cert` also reloads Dovecot after a certificate renewal
8. Postfix `submission`/`submissions` via `postconf -M/-P`, `postfix check`, reload, check 465/587
9. fail2ban filters + `jail.d/luxai-mail.local`, `fail2ban-client -t`, reload, jail running
10. firewall last (only when everything above works)

The Dovecot restart interrupts open IMAP connections (Roundcube reconnects by itself).

### After deployment

1. Webmail: sign in at `https://mail.lux-ai.cz` once (password/plain login on 127.0.0.1:143 must
   still work).
2. From outside: `openssl s_client -connect mail.lux-ai.cz:993 -servername mail.lux-ai.cz` shows
   a valid chain and `AUTH=OAUTHBEARER AUTH=XOAUTH2`; `nc -vz mail.lux-ai.cz 143` must fail.
3. On a LuxOS computer signed in to the LuxAI account (luxos-mail ≥ 1.0.0-2): open Mail →
   **Continue as …** → **Add** next to `info@lux-ai.cz`. `journalctl -u dovecot` shows
   `Logged in: user=<info@lux-ai.cz>, method=OAUTHBEARER`.
4. `fail2ban-client status luxai-dovecot` – jail runs.
5. Later, with phase 2 (sending): send one message and check its `DKIM-Signature` (OpenDKIM signs
   authenticated submissions).

## Rollback

```bash
ssh root@185.183.156.25 bash /root/mail-oauth-<stamp>/remote-rollback.sh <stamp>          # keep secret + mapping
ssh root@185.183.156.25 bash /root/mail-oauth-<stamp>/remote-rollback.sh <stamp> --purge  # remove them too
```

Removes the live firewall rule, restores every backed-up file byte for byte (files created by the
deploy are deleted), removes the Postfix services, restarts Dovecot and the account server and
reloads fail2ban. Issued tokens live only in the account server's memory and disappear with the
restart. Use the stamp of the **first** deployment to get back to the original state.

## Tests (all local, never the live server or a real account)

```bash
cd server/mail-oauth/tests
LUX_ACCOUNT_SERVER_JS=/tmp/lux-account-server.js python3 -m unittest test_account_server   # 17 tests: endpoints, revocation, regressions
LUX_ACCOUNT_SERVER_JS=... LUX_DOVECOT_ROOT=... python3 -m unittest test_dovecot_oauth       # real Dovecot 2.4 + patched account server
LUX_ACCOUNT_SERVER_JS=... LUX_DOVECOT_ROOT=... LUXOS_MAIL_BIN=.../luxos-mail \
    python3 -m unittest test_end_to_end                                                     # LuxOS Mail service -> account server -> Dovecot
LUX_FAIL2BAN_ROOT=/path/to/unpacked/fail2ban python3 -m unittest test_fail2ban               # filters vs real Dovecot 2.4 log lines
python3 -m unittest test_deploy_scripts                                                     # apply/rollback in a fake root with stub commands
```

- `server.js` is private and not in the repository; the tests patch a local copy and run it with a
  temporary `DATA_FILE` of fake users, fake secrets and a `nodemailer` stub.
- Dovecot runs without root from an unpacked package: `bsdtar xf dovecot-2.4.x-…pkg.tar.zst` (plus
  `mariadb-libs` and `postgresql-libs`, which the auth process links) into one folder; bubblewrap
  overlays it on `/usr/lib` and `/usr/bin` for the test processes only (Dovecot has compiled-in paths).
- The configuration was also parsed with Dovecot **2.4.1** (the Debian 13 version on the server)
  together with a copy of the server's `/etc/dovecot` (without `private/` and `users`).

## Findings about the current server (2026-11-07)

- Dovecot 2.4.1 (Debian 13) listens only on 127.0.0.1/::1 port 143 (imaps port 0), `auth_mechanisms
  = plain login`, passdb passwd-file `/etc/dovecot/users` with **one** user `info@lux-ai.cz`
  (ARGON2ID), userdb static `/var/vmail/<domain>/<user>`, delivery from Postfix over LMTP. Dovecot
  used the **snakeoil** certificate; Postfix already has the Let's Encrypt certificate of
  `mail.lux-ai.cz` (Caddy → `lux-mail-sync-cert` timer → `/etc/lux-mail/tls`, valid to 2027-01-24).
  `dovecot-submissiond` is not installed (submission is done by Postfix).
- Webmail mapping today: Roundcube plugin `luxai_sso` (`/usr/share/roundcube/plugins/luxai_sso`,
  config `/etc/roundcube/luxai-sso.inc.php`) does OIDC against lux-ai.cz (client `lux-mail`), then
  accepts the login only if `email_verified`, group `luxai-admin` (= account role admin) and the
  e-mail is in `allowed_emails`; it then logs in to the single configured mailbox `info@lux-ai.cz`
  with a **stored mailbox password** (`mailbox_password`) over 127.0.0.1:143. `allowed_subject` is in
  the config but the plugin does not check it. The account server itself has no mailbox mapping.
- Postfix 3.10: only port 25 (no submission), `smtpd_sasl_type = cyrus` default, virtual mailboxes
  for lux-ai.cz, OpenDKIM milter on 127.0.0.1:8891.
- Firewall: nftables `inet lux_filter`, input policy drop, open 22/25/80/443/8085 (+UDP 443,
  51820); LUX Guard bans are limited to non-web ports. fail2ban 1.1.0 jails: sshd, caddy-*,
  roundcube-auth, postfix (port 25); no Dovecot jail; the stock Dovecot filter would not match
  Dovecot 2.4 lines anyway.
- DNS: `mail.lux-ai.cz` A 185.183.156.25 and AAAA 2a03:4000:1d:b17:…:5233, MX lux-ai.cz → mail.lux-ai.cz.
  No `_imaps._tcp`/`_submissions._tcp` SRV records (not needed: Mail gets the servers from the
  LuxAI server).

## Not done / ideas

- Per-device app passwords (for other mail clients): design only – a separate
  `passdb passwd-file` with hashed app passwords (`/etc/dovecot/app-passwords`, ARGON2ID, one line
  per device `info@lux-ai.cz:{ARGON2ID}…::::::user=info@lux-ai.cz`), `mechanisms_filter = plain
  login`, no `allow_nets`, generated and revoked from the LuxAI account page. Not implemented.
- Sending from Mail (SMTP, phase 2) will reuse the same token via SASL OAUTHBEARER/XOAUTH2 on 465.
