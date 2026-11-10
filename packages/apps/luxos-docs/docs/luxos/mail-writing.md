# LuxOS Mail – writing, reading and technical notes

Part of [LuxOS Mail](mail.md).

## Write and send mail

- **New message**: the toolbar button or **Ctrl+N**. **Reply** (**Ctrl+R**), **Reply All**
  (**Ctrl+Shift+R**) and **Forward** (**Ctrl+Shift+F**) work on the selected message – also from the
  toolbar. A `mailto:` link anywhere in LuxOS (and in a message) opens a new message with the address,
  subject and text from the link.
- The message window has **From** (choose the account), **To**, **Cc**, **Bcc**, **Subject** and the
  text. While you type an address, Mail suggests addresses you wrote to before and senders of mail
  saved on this computer (by name or address; Enter or a click takes it). Several addresses are
  separated by commas.
- **Attachments**: the paper-clip button or **Ctrl+Shift+A** (several files at once), or drag files
  from Files into the window. They are listed under the subject with their size and an **×** to
  remove them; above 25 MB Mail warns that many servers refuse such big messages.
- **Send** with the button or **Ctrl+Enter**. A message without a recipient or with a mistyped address
  is not sent (the status line says what to fix); a message without a subject asks first.
- **Replies** quote the original under *"On <date>, <name> wrote:"* (lines starting with `>`), keep
  the thread (In-Reply-To, References) and go to the Reply-To address when the sender set one. Reply
  All adds the other recipients without your own addresses. The original message is marked as answered
  (forwarded) on the server. **Forward** includes the original text and its attachments.
- **Signature**: **… › Signature for <address>…** – it is added under `-- ` to new messages, replies
  (above the quote) and forwards.

### Drafts – a written message is never lost

- 1.5 seconds after every change the message is saved on this computer
  (`~/.local/share/luxos-mail/drafts/`). If Mail or the computer stops, the message window opens again
  the next time Mail starts (*"Recovered – Mail closed before this message was sent or saved."*).
- After 30 seconds without typing (and with **Ctrl+S**) the draft is saved to **Drafts** on the server
  (each new version replaces the previous one), so you can finish it on another device too.
- Closing a message window asks **Save this message as a draft?** – **Save** keeps it in Drafts,
  **Delete Draft** removes it here and on the server. An empty window closes without asking. Open a
  draft from Drafts with Enter or a double click; sending it removes it from Drafts.

### Sending, Sent and the Outbox

- Mail sends through the account's outgoing server: Gmail `smtp.gmail.com:465` (SSL/TLS), Microsoft
  `smtp.office365.com:587` (STARTTLS), LuxAI mailboxes the LuxAI mail server (465/587), other accounts the
  server found when the account was added. TLS is mandatory and the certificate is checked; the password
  or token is never sent unencrypted.
- A copy of the sent message is saved to **Sent** on the server – except for **Gmail** and **Microsoft**
  (Outlook.com, Microsoft 365), which save messages sent through their servers to Sent themselves (a copy
  from Mail would appear twice).
- **Without a connection** (or when the server is temporarily unavailable) the message goes to the
  **Outbox** – it appears at the top of the left column – and is sent automatically: after 30 s, 1 min,
  2 min … at most every 15 minutes, and at once when the network comes back or the computer wakes up.
- When a message cannot be sent at all (the server refused a recipient or the sign-in, the message is
  too large), Mail says why in the message window and nothing is sent. A message from the Outbox that
  fails like this (or still cannot be sent after 48 hours) stays in the Outbox marked **Not sent** with
  the reason, and a notification *"A message could not be sent"* appears (**Open** shows the Outbox).
  In the Outbox: **Send Now / Send Again**, Enter or double click to **edit** the message, **Delete**
  to remove it.
- When a server refuses one recipient, nobody gets the message (so you can correct the address and send
  it to everyone again).

## Reading mail

The window has three columns like Mail on macOS: mailboxes, the message list (sender, subject, date,
preview, a blue dot for unread, a paper clip for attachments) and the message. A message is marked
as read when you open it. Attachments are listed above the text; click one to **Open** it in its app
or **Save As…**.

Messages are shown like in a web browser, but locked down (WebKitGTK – already part of LuxOS):

- **HTML mail** (newsletters, notifications from big services …) keeps its layout, colours, tables
  and pictures attached to the message. A message with its own colours is shown on white paper also in
  the dark appearance, so it stays readable; plain messages follow the light/dark appearance.
- **Plain text**: web and e-mail addresses become links, quoted lines (`> …`) are shown as indented
  blocks with a coloured bar (nested quotes in other colours), the signature after `-- ` is dimmed,
  ASCII tables and code keep a monospace font, long lines wrap, format=flowed text is reflowed.
- **Links** open in your web browser (a `mailto:` link opens a new message); pointing at a link shows
  its real address at the bottom of the message. Nothing ever navigates inside the message.
- **Remote images** (pictures loaded from the internet – often used to track when you read a message)
  are not loaded: a bar says *"Remote images are hidden to protect your privacy."* with **Load
  Images** (this message) and **Always from <sender>**. Tracking pixels (1×1 images) are never loaded.
- Pictures attached to a message are shown under the text.
- Text can be selected and copied. **Ctrl+F** in the message (after clicking into it or Enter in the
  list) finds text (Enter / Shift+Enter next / previous, Esc closes), **Ctrl+P** prints,
  **Ctrl+plus / Ctrl+minus / Ctrl+0** change the text size.

Safety: JavaScript, plugins, forms, frames, external style sheets and anything that could reach the
network are removed before the message is shown, and the message page itself forbids network access
(Content-Security-Policy) – also when a trick in the mail would slip through the cleaning. No cookies
or website data are stored.

| Key | Action |
| --- | --- |
| ↑ ↓ | previous / next message (also in the mailbox list) |
| Enter | move to the message text |
| Delete | move to Trash (in Trash: delete permanently after a question) |
| Ctrl+Shift+U | mark as read / unread |
| Ctrl+F | filter the message list (sender, subject, preview); Esc clears it |
| F5, Ctrl+Shift+N | get mail now |
| Ctrl+N | new message |
| Ctrl+R / Ctrl+Shift+R | reply / reply all |
| Ctrl+Shift+F | forward |
| Ctrl+Enter | send (in the message window); Ctrl+Shift+A attach, Ctrl+S save draft, Esc close |
| Ctrl+F in the message | find in the message text |
| Ctrl+P | print the message |
| Ctrl+plus / minus / 0 | text size of the message |
| Ctrl+Q, Ctrl+W | close Mail |
| F10 | menu (Add Account, Change Password, Remove …) |

Messages that were opened once stay readable **offline**; the list always comes from the local cache,
so Mail opens instantly also without a network. When the server cannot be reached, a yellow bar says
so and **Try Again** reconnects.

Special mailboxes (Inbox, Sent, Drafts, Archive, Junk, Trash) are recognised from the server's
SPECIAL-USE flags, otherwise by common names in several languages (Odeslané, Koš, Gesendet …).


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
- SMTP submission (RFC 6409) with implicit TLS (465, RFC 8314) or STARTTLS (587), EHLO extensions,
  AUTH PLAIN/LOGIN with the password, XOAUTH2 or OAUTHBEARER with the access token (Google, Microsoft,
  LuxAI; a refused cached token is renewed once), SIZE checked before sending, 8BITMIME/SMTPUTF8 only
  when needed, multi-line replies, a refused recipient cancels the whole message (RSET). Messages are
  composed as RFC 5322 with UTF-8: RFC 2047 encoded headers, quoted-printable or base64 text,
  attachments as multipart/mixed with RFC 2231 file names, lines of at most 78 characters (998 at most),
  CRLF, Message-ID at the sender's domain, no Bcc header. The draft and the Sent copy are stored with IMAP
  APPEND (UIDPLUS).
- Message view: WebKitGTK 4.1 (`webkit2gtk-4.1`, already installed in LuxOS for the router management and
  yad), loaded only when the first message is shown (`dlopen`; without it Mail falls back to plain text).
  One ephemeral, locked-down web view (no JavaScript, plugins, WebGL, media, local storage, cookies or
  page cache; document-viewer cache model). The message is cleaned first (`mail_html`: whitelist of tags
  and attributes, links only http/https/mailto/tel/#, CSS without `@import`/`expression()`, `url()` only
  for pictures inside the message) and carries `Content-Security-Policy: default-src 'none'` (with
  remote images allowed: `img-src https: http:` only). Navigation is refused; a link click is handed to
  the browser. A rich-text converter (GtkTextView) was considered but would lose table layouts and
  colours of most real mail. Cost: WebKit starts its web and network processes only when the first message is
  shown; measured in the tests (RSS, shared libraries included) about 275 MB for the web process and 45 MB for the
  network process. The background program (notifications) does not load WebKit at all.
- The window asks the background program for all network work over a private UNIX socket
  (`luxos-mail-<uid>`, only the same user), so it never freezes on a slow server.
- Logs: the background program writes to the session log with the prefix `luxos-mail:` (never
  passwords).

