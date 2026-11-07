# LuxOS Mail

**Mail** (Pošta, package `luxos-mail`, command `luxos-mail`) is the lightweight mail app of LuxOS,
written in LSL. It reads mail from any IMAP server and shows a notification the moment new mail
arrives – also when the window is closed. Thunderbird stays available in the *Everyday* app set for
people who need its features; Mail starts in a fraction of a second and uses a fraction of the memory.

This first version **reads** mail and **notifies**. Writing, replying and sending (SMTP) come in a
later update; until then **Ctrl+N** or a `mailto:` link shows a short note and the address can be
copied to use in webmail.

## Sign in with your LuxAI account

When a LuxAI account is signed in on this computer (in the installer, the welcome window or the
**LuxAI Account** app, see [luxai-account.md](luxai-account.md)), the first screen of Mail offers
**Continue as <name>** with the registration e-mail of the account under it:

1. Mail asks the LuxAI server which mailboxes this account may use (`GET /api/mail/mailboxes`). The
   registration e-mail is usually a personal address elsewhere; the mailboxes are the ones hosted
   on the LuxAI server that the account has access to (for example `info@lux-ai.cz` for its owner).
2. **LuxAI Mailboxes** lists them – press **Add** next to one. No password is asked: Mail signs in
   with the LuxAI account and downloads the newest messages like for any other account.
3. When the account has no mailbox on the LuxAI server, the normal **Add Account** window opens with
   the registration e-mail already filled in (enter its password, settings are found automatically).

**Use Another Account…** opens the normal Add Account window with the registration e-mail filled in;
the LuxAI server is not contacted. Later, **… › Add LuxAI Mailbox…** in the menu shows the list again.

How it works and what it means for security:

- Mail never stores a password for a LuxAI mailbox (nothing in the keyring). Before each connection
  the background program asks the LuxAI server for a **short-lived access token** for that mailbox
  (`POST /api/mail/token`, valid 15 minutes, bound to the account, this computer's sign-in and the
  mailbox) and signs in with SASL **OAUTHBEARER** (RFC 7628) or **XOAUTH2**. An open connection
  (IDLE) stays signed in after the token expires; a new connection gets a new token.
- The session token of the LuxAI account (`~/.config/luxai/account.json`, written only by
  `luxos-account`) is sent only to the LuxAI server, as a cookie in the curl configuration on
  standard input – never on a command line, in a file of Mail or in a log.
- The mail server checks every token with the LuxAI server. **Signing out** of the LuxAI account on
  this computer, **changing the LuxAI password** (signs out other devices) or removing the account's
  access to the mailbox stops new sign-ins at once.
- When the LuxAI sign-in expired, the message list shows *"Your LuxAI sign-in has expired"* with
  **Sign In…** (runs `luxos-account login`, then Mail reconnects). A refused token or a missing
  access is **not retried** automatically (the server blocks addresses after repeated failures);
  **Try Again** makes one new attempt.

## Add an account

1. Open **Mail** (Dock, Launchpad or Search) and press **Add Account…**.
2. Enter the email address and password and press **Continue**. Mail finds the server settings
   itself (see below) and shows them – check them and press **Sign In**.
3. Mail signs in, saves the password in the keyring and downloads the newest 500 messages of the
   Inbox. Older messages load with **Load Older Messages** at the end of the list.

When the settings are not found automatically, Mail opens the server fields: **Incoming server
(IMAP)**, **Port** (993 for SSL/TLS, 143 for STARTTLS), **Security** and **User name** (usually the
whole address). The outgoing server (SMTP) is stored for the coming send feature.

### How the server settings are found

The same order as Thunderbird, without signing in anywhere:

1. the provider's own configuration: `https://autoconfig.<domain>/mail/config-v1.1.xml` and
   `https://<domain>/.well-known/autoconfig/mail/config-v1.1.xml`,
2. the Thunderbird provider database (ISPDB) for the domain, and for the domain of its MX server
   (company domains hosted at Google, Microsoft, Seznam …),
3. DNS SRV records (RFC 6186/8314): `_imaps._tcp`, `_imap._tcp`, `_submissions._tcp`, `_submission._tcp`,
4. a guess: the MX server when it is in the same domain (often `mail.<domain>`), then `imap.<domain>`,
   `mail.<domain>`, `<domain>`. Each name is checked by connecting with TLS and reading the IMAP
   greeting (no password is sent). A wildcard DNS record (`*.domain`) is detected so a name that
   only seems to exist is not chosen.

Test it in Terminal: `luxos-mail --discover name@example.com` (JSON with every step), add
`--no-probe` to only use DNS and HTTPS without connecting to any mail server.

## Security

- **TLS is mandatory and the certificate is always checked** (system CAs and the server name). An
  invalid certificate shows *"The security certificate of … is not valid (reason)"* and Mail does
  not connect – there is no "continue anyway". Port 143 is used only with STARTTLS; a server without
  encryption is refused, the password is never sent unencrypted.
- **The password is only in the keyring** (Secret Service: gnome-keyring, unlocked at login),
  stored with `secret-tool` and never written to a file or a command line. You can see it in
  *Passwords and Keys* as "LuxOS Mail: address".
- LuxAI mailboxes have no password at all – see [Sign in with your LuxAI account](#sign-in-with-your-luxai-account).
- A wrong password is **not retried** automatically (servers block accounts after repeated
  failures). The message list shows *"The server rejected the password"* with **Enter Password…**;
  after you change the password in webmail, enter the new one there or in the menu
  (**… › Change Password for …**).
- HTML mail is shown as text: no scripts, no images and **no remote content** (tracking pixels are
  never loaded). Links are shown as `<https://…>` after the link text.
- Mail files are private to the user (folders 0700, files 0600).

## Reading mail

The window has three columns like Mail on macOS: mailboxes, the message list (sender, subject, date,
preview, a blue dot for unread, a paper clip for attachments) and the message. A message is marked
as read when you open it. Attachments are listed above the text; click one to save it.

| Key | Action |
| --- | --- |
| ↑ ↓ | previous / next message (also in the mailbox list) |
| Enter | move to the message text |
| Delete | move to Trash (in Trash: delete permanently after a question) |
| Ctrl+Shift+U | mark as read / unread |
| Ctrl+F | filter the message list (sender, subject, preview); Esc clears it |
| Ctrl+R, F5 | get mail now |
| Ctrl+N | new message (coming in a later update) |
| Ctrl+Q, Ctrl+W | close Mail |

Messages that were opened once stay readable **offline**; the list always comes from the local cache,
so Mail opens instantly also without a network. When the server cannot be reached, a yellow bar says
so and **Try Again** reconnects.

Special mailboxes (Inbox, Sent, Drafts, Archive, Junk, Trash) are recognised from the server's
SPECIAL-USE flags, otherwise by common names in several languages (Odeslané, Koš, Gesendet …).

## New mail notifications

A small background program, `luxos-mail-service` (no GTK, about 17 MB), starts with the session
(`/etc/xdg/autostart/luxos-mail-background.desktop`) and keeps **one connection per account**:

- With **IMAP IDLE** the server tells Mail about new mail immediately (typically under a second);
  the IDLE command is renewed every 25 minutes. Servers without IDLE are checked every 5 minutes.
- A new unread message shows **"New mail from <sender>"** with the subject and the beginning of the
  text; **Open** (or a click) opens Mail at that message. When more than three messages arrive at
  once, one notification says how many. Messages already read elsewhere, messages that were in the
  mailbox before the account was added, and messages already notified (also across restarts) do
  not notify again. **Do Not Disturb** in the Control Center silences the popups (they stay in the
  notification log).
- After the network comes back (NetworkManager) or after waking from sleep, Mail reconnects at
  once; after a connection failure it waits 5 s, 10 s, 20 s … at most 15 minutes.
- The Dock icon shows the number of unread messages in the Inbox (Plank, LauncherEntry API).
- Without any account the background program ends by itself after a minute.

## Files

| Path | Content |
| --- | --- |
| `~/.config/luxos-mail/accounts.json` | accounts and server settings (no passwords; LuxAI mailboxes have `"auth": "luxai"`) |
| `~/.config/luxai/account.json` | LuxAI account of this computer – Mail only reads it (written by `luxos-account`) |
| `~/.local/share/luxos-mail/<account>/mailboxes.tsv` | mailboxes and unread counts |
| `~/.local/share/luxos-mail/<account>/m-<hash>/index.tsv` | message list cache (one line per message) |
| `~/.local/share/luxos-mail/<account>/m-<hash>/state.json` | UIDVALIDITY, UIDNEXT, HIGHESTMODSEQ, last notified message |
| `~/.local/share/luxos-mail/<account>/m-<hash>/bodies/<uid>.eml` | messages that were opened (raw RFC 5322) |

**Remove** an account in the menu (**… › Remove …**): the cache and the keyring entry are deleted,
nothing is deleted on the server. Deleting `~/.local/share/luxos-mail` only clears the cache; it is
downloaded again.

## Technical notes

- IMAP4rev1/IMAP4rev2 with UIDs, CONDSTORE (only changed flags are fetched) and QRESYNC (deleted
  messages arrive as VANISHED) when the server has them, MOVE/UIDPLUS, SASL PLAIN or LOGIN,
  SASL OAUTHBEARER (RFC 7628) and XOAUTH2 with an access token (LuxAI mailboxes; the JSON error in the
  server's continuation is answered as the RFC requires; `NO [UNAVAILABLE]` counts as a temporary
  failure and is retried later), literals, ENVELOPE and BODYSTRUCTURE parsing; previews come from the
  first 2 KB of the text part. Unsolicited `FETCH (UID … FLAGS …)` responses that Dovecot sends while
  new messages are fetched are merged into the message, not stored as an empty line.
- MIME: multipart (alternative, mixed, related, digest), base64, quoted-printable, RFC 2047 headers
  (also words split in the middle of a character), RFC 2231 file names, format=flowed, any charset
  known to iconv (cs/sk/pl: ISO-8859-2, windows-1250; uk: KOI8-U, windows-1251; ISO-8859-1 read as
  windows-1252). Text without a charset is UTF-8, or windows-1250/1251/1252 by the user's language.
- The window asks the background program for all network work over a private UNIX socket
  (`luxos-mail-<uid>`, only the same user), so it never freezes on a slow server.
- Logs: the background program writes to the session log with the prefix `luxos-mail:` (never
  passwords).

## Troubleshooting

| Problem | What to do |
| --- | --- |
| No notifications | Check that `luxos-mail-service` runs (`pgrep -a luxos-mail`), Do Not Disturb is off, and the account has no error bar. Start it with `luxos-mail --background`. |
| "The security certificate … is not valid" | The server name does not match its certificate or the certificate expired. Use the exact server name from your provider (e.g. `mail.example.com` instead of `example.com`). |
| "The password is not in the keyring" | The keyring was not unlocked at login (password changed?). Enter the password again with **Enter Password…**. |
| Settings not found | Ask the provider for IMAP server, port and security, then **Configure Manually**. |
| "Your LuxAI sign-in has expired" | Press **Sign In…** (or run `luxos-account login`); Mail reconnects after signing in. |
| "Your LuxAI account no longer has access to …" | The owner of the mailbox removed the access on the LuxAI server. Remove the account in the menu, or ask the owner and press **Try Again**. |
| "The mail server did not accept the LuxAI sign-in" | Press **Try Again** once. If it repeats, the mail server cannot check tokens right now – wait a few minutes (repeated failures can block your address for an hour). |
| A folder is missing | Press **Ctrl+R** (the mailbox list refreshes) – folders marked as hidden or not selectable on the server are not shown. |
