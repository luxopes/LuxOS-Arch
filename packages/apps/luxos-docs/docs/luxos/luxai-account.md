# LuxAI account

LuxOS has **one shared LuxAI account per user profile**. You sign in once in the system and LuxOS
apps – **LuxAI**, **Lux Code** and **LSL IDE** – reuse it; nobody signs in inside each app separately.
The account belongs to the service at `https://lux-ai.cz`.

## Where to sign in

- App **LuxAI Account** (`luxos-account`, package `luxos-account`): sign in, profile, monthly AI
  usage, sign out.
  It also shows the account on this computer with its profile picture (the same picture as on the
  login screen); clicking the picture or **Change Picture** opens Profile Picture
  (`luxos-profile-picture`, see [settings-apps.md](settings-apps.md#profile-picture)). The user
  button of the LuxOS menu opens this app.
- The welcome window after first login.
- Optionally already in the **installer** (graphical and text): password, code sent by e-mail, or
  creating a new account.
- LuxAI and Lux Code offer **Sign in with LuxAI account** / **Sign in again** when there is no
  account or the server answers 401/403; this runs `luxos-account login`.

Sign-in methods (shared GTK panel `SignInPanel` in `/usr/lib/luxos/python/luxai_account_gtk.py`):
password, 6-digit code from e-mail, new account, and web login (PKCE through
`https://lux-ai.cz/ide/connect?…&app=luxos`).

## Command line

```bash
luxos-account            # account window (sign in / profile)
luxos-account login      # sign-in window; exit code 0 = signed in
luxos-account register   # same, directly creating a new account
luxos-account status     # JSON {"signedIn": true, "user": {...}} - never contains the token
luxos-account token      # prints the session token (for apps of the same user only)
luxos-account logout     # signs out and invalidates the session on the server
```

`luxos-account status` is the safe way to check whether a user is signed in. **Never print, log or
share the output of `luxos-account token`** – it is a secret session credential.

## Storage

`~/.config/luxai/account.json` (directory `0700`, file `0600`, written atomically):

```json
{
  "version": 1,
  "origin": "https://lux-ai.cz",
  "sessionToken": "…",
  "user": { "id": "…", "email": "…", "displayName": "…", "username": "…" },
  "client": "luxos",
  "updatedAt": "2026-10-20T16:30:00+0200"
}
```

- Missing file = not signed in.
- Apps **only read** it; it is written by `luxos-account` (and the installer). On HTTP 401/403 apps
  offer *Sign in again* and do not delete the file themselves.
- The origin can be overridden for testing with `LUXAI_ORIGIN`.

## Models and monthly limits

The account offers two AI models:

| Model | id | Description in LuxAI |
|---|---|---|
| **Flash** | `flash` | "smarter", default model; can see images |
| **Lite** | `lite` | "faster, larger limit"; no image input by default; also used to generate conversation titles |

Usage is counted per calendar month per model. The real limits are delivered by the server in
`GET /api/me` (`usage.fastTokens` / `usage.fastLimit` for Flash, `usage.liteTokens` /
`usage.liteLimit` for Lite, or `usage.unlimited`); the LuxAI Account window shows them as bars under
**AI usage this month**. The LSL IDE documentation states the limits as **Flash 50k / Lite 1M tokens**
per month – treat the values from `/api/me` as authoritative because the server may change them.

When a limit is used up, LuxAI reports "The monthly Flash limit is used up. Switch to Lite or wait for
the next month." or "The monthly Lite limit is used up."

## Using the account from apps

Every request to `https://lux-ai.cz` carries:

- cookie `lux_account_session=<sessionToken>`,
- header `X-Lux-Client: <client>` – allowed values `lsl-ide`, `luxos`, `lux-code`, `luxai`.

| Call | Purpose |
|---|---|
| `GET /api/me` | user and monthly usage |
| `POST /api/ide/chat/completions` | OpenAI-compatible chat (tools, `stream: true` = SSE), billed to the account limit |
| `GET/PUT/DELETE /api/ide/cloud/...` | cloud files (LSL IDE cloud) |
| `POST /api/ide/logout` | invalidate the session |

Helpers:

- Python: `/usr/lib/luxos/python/luxai_account.py` – `load()`, `me()`, `request(...)`,
  `login_password`, `request_code` + `login_code`, `WebLogin`, `logout()`, `register_start`,
  `fetch_terms()`, `error_text(err, _)`.
- Shell/LSL/Lux Code: `luxos-account status`, `luxos-account token` (pass the token only in a header
  or cookie, never in a URL or command line visible to others).

Lux Code uses the account automatically when `~/.config/luxai/account.json` exists
(`LUX_CODE_AUTH=auto|account|apikey`, default model `LUX_AI_MODEL=flash`); otherwise it falls back to
an API key from its `.env`.

## Creating an account

Possible directly in LuxOS (installer and `luxos-account register`), without a browser:

1. name, e-mail, password (**12–128 characters**) and acceptance of the terms (text from `GET /terms`
   is shown in the app),
2. `POST /api/auth/register/start` sends a 6-digit code to the e-mail,
3. `POST /api/auth/code/verify` creates the account and signs in.

Errors: `invalid_email`, `email_domain_blocked`, `weak_password`, `terms_required`, `account_exists`
(409), `rate` / `slow_down` (429), `email_domain_check_unavailable` (503), `email_domain_review` (422).
If the server does not allow registration from native clients (`403 {"error": "origin"}`), the apps
offer to finish at `https://lux-ai.cz/register`.

## Troubleshooting

- "Your LuxAI session has expired or is not valid" → run `luxos-account login` (or open LuxAI
  Account) and sign in again.
- Check state without exposing secrets: `luxos-account status`.
- Sign out everywhere on this profile: `luxos-account logout`.
- Never edit `account.json` by hand and never ask the user for their password in a chat – use the
  sign-in window.

See also: [Configuration](configuration.md), [Apps](apps.md).
