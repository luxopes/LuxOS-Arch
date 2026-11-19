# LuxOS Discord bot

Support bot for the official LuxOS Discord server, plus a one-time server setup script. The bot
answers questions in `#support` from the LuxOS documentation using LuxAI, hands threads to the
LuxOS team when it is not sure, and posts LuxOS announcements. The server language is English.

It runs on the LuxOS/LuxAI server as a small Node 20 service (no open port, nothing in Caddy). It
talks to Discord over HTTPS/WebSocket, to the local `lux-api` gateway (`127.0.0.1:3002`) for
answers and to the local SMTP server (`127.0.0.1:25`) for hand-off e-mails.

| File | What |
|------|------|
| `src/main.js` | the bot: starts everything, reads secrets from `$CREDENTIALS_DIRECTORY` |
| `src/bot.js` | where it answers, limits, hand-off to a human, `/human` command |
| `src/gateway.js`, `src/rest.js` | small Discord Gateway (heartbeat, resume, reconnect) and REST client (rate limits) |
| `src/assistant.js` | prompt and call to LuxAI (`/v1/chat/completions`, model `flash`, low effort) |
| `src/knowledge.js`, `scripts/build-index.js` | BM25 keyword search over the docs index `knowledge.json` built at deploy time |
| `src/announce.js` | posts new items from `announcements.json` and new releases from `release.json` |
| `src/mailer.js` | hand-off e-mail and bug forwards to info@lux-ai.cz (one per thread/report, rate-limited) |
| `src/bugs.js` | `#bug-reports`: checks each report with LuxAI, forwards clear ones, asks once for missing details |
| `src/secrets.js` | recognises passwords/keys/tokens (kept from the model, redacted from bug mails) |
| `src/setup.js` | one-time, idempotent setup of roles, channels, Onboarding (Tester/Member), `/human` and the invite link |
| `luxos-discord-bot.service` | systemd unit (DynamicUser, LoadCredential, ProtectSystem=strict, MemoryMax=128M) |
| `deploy.sh` | builds the index, runs the tests, installs the bot and the unit from the admin's PC |
| `test/` | `npm test` (node:test with a fake Discord, fake lux-api, fake SMTP and fake website) |

Dependencies (exact versions, `package-lock.json`): `ws` (WebSocket client) and `nodemailer`
(same SMTP library as lux-account). Both have no further dependencies.

## Owner's steps (once)

You need: the empty Discord server "LuxOS" (you are its owner) and SSH access to the server.
Never paste the bot token into a chat, an e-mail, a ticket or this repository.

### 1. Create the bot in the Discord Developer Portal

1. Open <https://discord.com/developers/applications> and log in.
2. **New Application** → name `LuxOS Support` → accept the terms → **Create**.
   (Optional: upload the LuxOS logo as App Icon → **Save Changes**.)
3. Left menu **Installation** → Install Link: **None** → **Save Changes**. Then left menu **Bot**
   → turn **Public Bot** off (nobody else can add the bot to their server).
4. Still on **Bot**, under *Privileged Gateway Intents*: turn **Message Content Intent** on
   (leave Presence and Server Members off) → **Save Changes**.
5. **Reset Token** → **Yes, do it!** (enter your 2FA code if asked) → **Copy**. The token is shown
   only once. Go straight to step 2 and don't keep it anywhere else. If it ever leaks, press
   Reset Token again and store the new one.

### 2. Store the token on the server

```
ssh root@185.183.156.25
install -d -m 700 /etc/luxos-discord
(umask 077; cat > /etc/luxos-discord/token)
```

Now paste the token (right click or Ctrl+Shift+V), press **Enter**, then **Ctrl+D**. Nothing is
shown while you paste, that is fine. Check that something was saved (prints only a number of
characters, around 70):

```
wc -c < /etc/luxos-discord/token
```

The bot's own LuxAI API key goes the same way into `/etc/luxos-discord/luxai-key` (an API key
created for the bot in the LuxAI admin, e.g. named `discord-bot`; its usage is then visible
separately from other clients):

```
(umask 077; cat > /etc/luxos-discord/luxai-key)
```

Paste, **Enter**, **Ctrl+D**. Both files stay readable only by root; systemd hands them to the
bot (`LoadCredential`), the bot never prints them.

### 3. Add the bot to the server (with Administrator, only for the setup)

Developer Portal → your application → **OAuth2** → **URL Generator**:

- Scopes: **bot** and **applications.commands**
- Bot Permissions: **Administrator**

Copy the generated URL at the bottom, open it, choose the **LuxOS** server → **Continue** →
**Authorize**.

### 4. Deploy and run the setup

On the admin PC (from this repository):

```
server/discord-bot/deploy.sh root@185.183.156.25
```

Then the setup, on the server (it reads the same token file):

```
ssh root@185.183.156.25 'node /opt/luxos-discord-bot/src/setup.js'
```

The first run creates the roles, `#welcome-and-rules` and the private `#team` and `#bot-testing`,
then stops if **Community** is off, because the forum `#support`, the `#announcements` channel and
Onboarding need it. It prints three choices:

- `--enable-community`: the bot turns Community on itself (verified e-mail required to chat,
  media scan for all members, rules channel `#welcome-and-rules`, Discord's updates channel `#team`).
- or click it yourself: **Server Settings → Enable Community → Get Started**; Safety check: keep
  *Verified email* and *Scan media content from all members*; Basics: Rules channel =
  `#welcome-and-rules`, Community updates channel = `#team`; Final step: accept → **Finish Setup**.
  Then run the setup again.
- `--no-community`: no Community; `#support` is a text channel where the bot answers in threads,
  `#announcements` is a read-only text channel, role buttons instead of Onboarding.

When it finishes it prints the **permanent invite link** (put it on the website) and the link
for step 5. Running the setup again changes nothing ("Nothing to change"); if someone deleted
or changed one of its channels, it is put back.

"Discoverable" (Server Discovery) is not needed: it requires Discord's eligibility (server age,
member count, activity) and is clicked later in Server Settings → Discovery. Use the invite link.

**Server rules** have no API: the setup prints the rules and where to click, **Server Settings →
Access → "Server rules"** → turn it on and use **Add rule** for each one.

The default channels Discord created with the server ("obecné" and the voice "Obecné", or
"general" and "General" in English) are listed at the end. If they are empty, run
`node /opt/luxos-discord-bot/src/setup.js --cleanup-defaults` to delete them, together with their
empty default categories. Channels with messages are never deleted.

### 5. Reduce the bot's permissions

Open the link printed by the setup, or build it in **OAuth2 → URL Generator**:

- Scopes: **bot** and **applications.commands**
- Bot Permissions: **View Channels**, **Send Messages**, **Send Messages in Threads**,
  **Read Message History** (permissions integer `274877975552`)

Open the URL → **LuxOS** → **Authorize**. Then check **Server Settings → Roles → LuxOS Support**
(the bot's role): *Administrator* must be off; if it is still on, turn it off and **Save**.
What the bot needs beyond that (posting in the read-only channels, tagging and creating threads
in `#support` and `#bot-testing`, reacting and asking in `#bug-reports`) was given to the bot in
those channels by the setup. Only if Discord refused Onboarding (the setup says so and uses role
buttons instead) the printed link also contains **Manage Roles** (`275146411008`), which the
buttons need.

To run the setup again later, give the bot *Administrator* for that time (step 3), then step 5.

### 6. Finish

- Give yourself the **Team** role: Server Settings → Members → you → **+** → Team. Team members
  can post in `#announcements`, see `#team` and `#testers`, and moderate.
- New members pick their role in Onboarding: "I want to test new LuxOS builds (staging)" → Tester
  (sees `#testers`), "I use LuxOS / I'm curious" → Member. They can change it later in
  **Channels & Roles** at the top of the channel list. You can also give roles by hand.
- Put the invite link on the website and add the privacy note below to the privacy page.

## What the setup creates

| Category | Channels |
|----------|----------|
| INFO | `#welcome-and-rules` (read-only, rules + where to go), `#announcements` (Announcement channel with Community; only Team and the bot post) |
| COMMUNITY | `#general`, `#show-your-desktop`, `#off-topic` |
| SUPPORT | `#support` (forum with Community, tags Installation, Hardware, Apps, LuxAI, Solved, and *Needs human* that only Team/the bot can set) |
| DEVELOPMENT | `#ideas`, `#bug-reports` (forwarded to the team, link to GitHub issues), `#testers` (Tester + Team only; staging is open to anyone who wants to test) |
| VOICE | General |
| STAFF | `#team` (Team only; also Discord's community updates channel), `#bot-testing` (Team only; the bot answers every message) |

Roles Team, Tester, Member; Onboarding question "What brings you here?" (required, one choice:
Tester or Member; default channels are the public ones), or a "Choose your role" message with
buttons when Onboarding is not available; slash command `/human`; server defaults (notifications
only for mentions, verified e-mail, media scan); one permanent invite.
If the Community wizard created `#rules` and `#moderator-only`, the setup reports them so you can
delete them; it deletes only empty default Discord channels and only with `--cleanup-defaults`.

## What the bot does

- **#support**: answers every new post (forum) or every new message (text channel, it opens a
  thread). It then answers follow-ups of the person who asked; others only when they mention it.
  The *Needs human* tag only means the team was notified: later answerable questions still get
  normal answers (no second e-mail). Once another person (a helper or the team) has replied in a
  `#support` thread, the bot stays quiet there unless it is mentioned.
- **#bot-testing** (Team only): every message gets a thread and an answer, like `#support`, from any
  team member and without the per-user limit. Hand-off e-mails from there have `[test]` in the
  subject.
- **#general**: only when mentioned (or when you reply to the bot). Other channels: never.
- **#bug-reports**: no doc answers. Each new report is checked by LuxAI (short, low effort): does
  it say what happened and in which app? A clear report is e-mailed to info@lux-ai.cz at once
  (subject `[LuxOS bug] <summary>`, author, report text, attachment links, message link, LuxOS
  version if mentioned) and gets a ✅. Only an unclear report gets one question in a thread on it,
  asking just for what is missing; when the author answers there, it is checked again and
  forwarded once it is clear, at the latest after the second answer. One e-mail per report, the
  shared e-mail limits plus 20 bug e-mails per day; passwords, keys and tokens are replaced by
  `[redacted]` before the check and the e-mail. If LuxAI is unavailable, the report is forwarded.
- **DMs**: only to members of the LuxOS server (others get one short note per day).
- **Greetings, thanks, small talk, off-topic: never escalated.** Short messages like "Hey Lux",
  "ahoj", "thanks!", "díky" or "are you there?" are recognised without the model. Everything
  else is classified by LuxAI first (GREETING / THANKS / SMALLTALK / OFFTOPIC / QUESTION, looking
  at the latest message). Greetings and small talk get a short intro ("Hi! I'm the LuxOS
  assistant. Ask me anything about LuxOS..."), thanks a short "You're welcome", topics clearly
  unrelated to LuxOS (prices, recipes, sports) a polite "I can only help with LuxOS and LuxAI" -
  in English or Czech, with no e-mail, tag or rename. The next real question in the same thread
  is handled normally.
- **Mention only** ("@LuxOS Support", also with "?", "pls", "help"): the bot answers the author's
  last unanswered message(s) in that channel or thread from the last 10 minutes; with nothing to
  answer it asks "What would you like to know?".
- **No made-up answers.** For real questions LuxAI also returns short English topic keywords
  (translating other languages; the docs are in English). If the docs, FAQ or changelog don't match those keywords well
  (BM25 score below `MIN_MATCH_SCORE` or less than `MIN_MATCH_COVERAGE` of the keyword weight
  found in one passage; tuned on the real index so that e.g. "printer not printing" passes and
  "goulash recipe" does not), the model is not asked at all. The bot replies "I couldn't find
  this in the LuxOS documentation, so I've passed your question to the LuxOS team (they'll reply
  here)." and e-mails the team. After the model answers, the answer is posted only if its META
  says `confident: true` and it cites at least one of the provided doc links; otherwise it is
  discarded and the same reply + e-mail follow. In `#general` the e-mail has the message link; in
  DMs the bot points to `#support` instead, because the team can't answer there.
- Replies in the language of the question (English if unclear).
- **Knowledge**: `knowledge.json`, built by `deploy.sh` from `packages/apps/luxos-docs/docs/**/*.md`,
  the website's extra docs (FAQ, LuxAI, hardware ...), the landing and home pages, and the latest
  release + "Coming soon" sections of the English changelog. The 5 best passages (BM25) go into
  the prompt with their `https://luxos.lux-ai.cz/...` links. Redeploy after docs changes.
- **Model**: `lux-api` `/v1/chat/completions`, `model: "flash"`, `reasoning_effort: "low"`,
  `max_tokens: 4000` (Flash always thinks and the thinking counts toward `max_tokens`), with its
  own key (`Authorization: Bearer lux-...`). The system prompt: answer only from the provided
  passages, every claim backed by them, never guess commands, paths, versions or hardware
  support, never ask for secrets, warn before destructive commands, always cite links. The model
  ends each reply with a hidden `META {...}` line (`confident`, `handoff`, `lang`, `summary`).
  Every line starting with `META` is removed before posting, even a cut-off one. A reply cut off
  by the token limit (`finish_reason: "length"`) is retried once with twice the budget; if it is
  still cut off, or META is missing or can't be parsed, the answer counts as not confident.
- **Hand-off to a human** in the cases above, when the model suggests the team (answer + note),
  when the user asks for a human (or types `/human`), or when a thread reaches the bot's reply
  limit: the *Needs human* tag (text channel: `[Needs human]` in the thread name) and one e-mail
  to info@lux-ai.cz with the thread link, title, author, reason, a one-sentence summary, the first
  600 characters of the question and the doc passages that were found (titles and links). At most
  one e-mail per thread, max 6 per hour / 30 per day.
- **Announcements**: every 15 minutes it reads `https://luxos.lux-ai.cz/announcements.json` (the
  same feed as the LuxOS News app) and `release.json`, and posts each new item to `#announcements`
  once (published to following servers). On the first start it skips items older than 14 days and
  only remembers the current release. A new release is announced unless an announcement already
  mentions that version.
- **Limits**: 4 answers per user per 10 minutes and 25 per day, 400 answers per day in total,
  8 bot replies per thread, 3 answers at the same time (20 waiting), questions cut at 3000
  characters, replies split into Discord-sized messages. It ignores bots, webhooks and messages
  with @everyone/@here, never pings anyone, and refuses to send messages that look like they
  contain a password, key or token to the model (it asks the user to delete them instead).
- **Discord**: honours REST rate limits (429, per-route and global), resumes the gateway session
  after a disconnect, reconnects with back-off. A rejected token or a missing intent ends the
  service with exit code 78, which systemd does not restart in a loop.
- **Logs**: only events and ids (`answered channel=... passages=5 handoff=false`), never message
  text. `state.json` (in `/var/lib/private/luxos-discord-bot/`) holds counters, thread ids with
  the asker's user id and reply count (dropped after 30 days), e-mail times and posted
  announcement ids, and for bug reports the author's id and the redacted report text until it is
  forwarded (dropped after 30 days).

## Configuration

Optional, in `/etc/luxos-discord/bot.env` (no secrets there), then `systemctl restart luxos-discord-bot`:

| Variable | Default |
|----------|---------|
| `DISCORD_GUILD_ID` | the only server the bot is in |
| `SUPPORT_CHANNEL`, `GENERAL_CHANNEL`, `ANNOUNCEMENTS_CHANNEL` | `support`, `general`, `announcements` |
| `BOT_TESTING_CHANNEL`, `BUG_REPORTS_CHANNEL` | `bot-testing`, `bug-reports` |
| `MIN_MATCH_SCORE`, `MIN_MATCH_COVERAGE` | `4`, `0.6` (below = no model answer, passed to the team) |
| `USER_ANSWERS_PER_10MIN`, `USER_ANSWERS_PER_DAY` | `4`, `25` |
| `DAILY_ANSWER_CAP` | `400` (all users, UTC day) |
| `THREAD_REPLY_CAP` | `8` |
| `MAX_QUESTION_CHARS` | `3000` |
| `MAX_CONCURRENT_ANSWERS`, `MAX_QUEUED_ANSWERS` | `3`, `20` |
| `MAILS_PER_HOUR`, `MAILS_PER_DAY`, `BUG_MAILS_PER_DAY` | `6`, `30`, `20` |
| `MAIL_TO`, `MAIL_FROM` | `info@lux-ai.cz`, `LuxOS Discord <accounts@lux-ai.cz>` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS_SERVERNAME` | `127.0.0.1`, `25`, `mail.lux-ai.cz` |
| `LUXAI_URL`, `LUXAI_MODEL`, `LUXAI_EFFORT`, `LUXAI_MAX_TOKENS` | `http://127.0.0.1:3002/v1/chat/completions`, `flash`, `low`, `4000` |
| `ANNOUNCE_INTERVAL_MIN` (0 = off), `ANNOUNCE_RELEASES` (0 = off) | `15`, `1` |
| `DISCORD_TOKEN_FILE`, `LUXAI_KEY_FILE` | `$CREDENTIALS_DIRECTORY/...`, else `/etc/luxos-discord/token`, `/etc/luxos-discord/luxai-key` |

## Privacy note for the website

Text for the privacy page (section "LuxOS Discord"):

> **LuxOS Discord support bot.** In the `#support` channel of the LuxOS Discord server, in
> messages that mention the bot in `#general`, and in direct messages to the bot, an AI assistant
> answers questions. To write an answer, the text of your message, the title of your support post
> and the earlier messages between you and the bot in the same thread (at most the last 12) are
> sent to LuxAI, our AI service, together with excerpts from the public LuxOS documentation.
> LuxAI passes them to the AI model provider to generate the answer; your Discord name, ID and
> attachments are not sent to the model. Messages that look like they contain a password, key or
> token are not sent. When the assistant can't answer from the documentation or hands a question
> to the LuxOS team, we receive an e-mail with your Discord name, the link to the thread and the
> beginning of your question. Reports in `#bug-reports` are also checked by LuxAI for missing
> details and then e-mailed to the LuxOS team with your Discord name, the report text (passwords,
> keys and tokens removed), attachment links and the message link. The bot keeps no message
> contents of questions: it stores only counters, thread IDs with the ID of the person who asked
> and, until a bug report is forwarded, its text (deleted after 30 days), and which announcements
> it posted. Discord itself stores
> messages according to the Discord privacy policy. For help from a human without the AI, write
> to info@lux-ai.cz.

## Tests

```
cd server/discord-bot && npm ci && npm test
```

Everything runs on 127.0.0.1 with fakes: the fake Discord (REST + Gateway) checks answers in
`#support` and `#bot-testing` (`[test]` mails), mention-only `#general`, DMs only for members,
language handling, greetings/thanks/small talk/off-topic never escalating ("Hey Lux", "ahoj",
"thanks!", "díky", "bitcoin price?"), mention-only messages, answers after a hand-off, the strict rules (weak match → no model call + mail, answer without a doc link
or unconfident or with a truncated META → discarded + mail, cut-off reply retried, confident cited
answer → posted, no mail; the match threshold on the real index), `#bug-reports` (clear report →
one mail with ✅ and no question, unclear → one question then mail after the answer, secrets
redacted, own daily cap), role buttons (Team never self-assignable), the hand-off (tag,
exactly one e-mail per thread, e-mail rate limit), per-user/daily/thread limits, ignored
bots/@everyone, secrets kept from the model, the text-channel fallback, gateway resume, 429
handling and a rejected token; announcements are posted once (also after a restart); the setup
creates everything (incl. Onboarding with Discord's default-channel rules, the button fallback
and `--cleanup-defaults`) and a second run sends no change to Discord; `main.js` runs as under systemd
(credentials, state, exit code 78, memory). Nothing contacts Discord, lux-ai.cz or the server.

## Troubleshooting

- `journalctl -u luxos-discord-bot -e`
- Exit code 78 and the service stays stopped: the token or key file is missing/empty, Discord
  rejected the token (reset it, step 1.5 + 2) or Message Content Intent is off (step 1.4). Fix it,
  then `systemctl restart luxos-discord-bot`.
- The bot is online but silent in `#support`: check the channel is named `support` and that the bot
  can see it; after step 5 run `node /opt/luxos-discord-bot/src/setup.js` only with Administrator.
- Previous version: `/opt/luxos-discord-bot.old` (see the end of `deploy.sh` output).
