# Účet LuxAI v LuxOS

LuxOS má jeden sdílený účet LuxAI pro celý uživatelský profil. Přihlašuje se v systému
(aplikace **Účet LuxAI** `luxos-account`, uvítací okno, volitelně instalátor) a aplikace
LuxOS ho přebírají – uživatel se nepřihlašuje v každé aplikaci zvlášť.

## Uložení

`~/.config/luxai/account.json` (adresář `0700`, soubor `0600`, zápis atomicky přes rename):

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

Soubor chybí = uživatel není přihlášený. Aplikace ho **jen čtou**; zapisuje ho
`luxos-account` (a instalátor). Při `401/403` z API ať aplikace nabídnou
„Přihlásit se znovu“ (`luxos-account login`), soubor samy nemažou.

## Použití tokenu v aplikacích

Každý požadavek na `https://lux-ai.cz`:

- cookie `lux_account_session=<sessionToken>`,
- hlavička `X-Lux-Client: <klient>` – povolené hodnoty `lsl-ide`, `luxos`, `lux-code`, `luxai`
  (server: `NATIVE_CLIENTS` v `/opt/lux-account/server.js`).

Dostupná API (stejná jako pro LSL IDE, viz `~/lsl-ide/server/patch_lux_account.py`):

| Volání | Účel |
|---|---|
| `GET /api/me` | uživatel a měsíční spotřeba |
| `POST /api/ide/chat/completions` | OpenAI-kompatibilní chat (tools, `stream: true` = SSE), účtuje se do limitu účtu |
| `GET/PUT/DELETE /api/ide/cloud/...` | cloudové soubory |
| `POST /api/ide/logout` | zneplatní session |

## Pomocné nástroje

- Python: `/usr/lib/luxos/python/luxai_account.py` – `load()`, `me()`, `request(...)`,
  `login_password`, `request_code` + `login_code`, `WebLogin` (PKCE přes `/ide/connect?app=…`), `logout()`;
  bez uložení (instalátor): `password_session`, `verify_code`; registrace `register_start`,
  podmínky jako text `fetch_terms()`, hlášky k chybovým kódům `error_text(err, _)`.
- GTK: `/usr/lib/luxos/python/luxai_account_gtk.py` – `SignInPanel` (heslo / kód z e-mailu / nový účet)
  a `show_terms()`; používá ho `luxos-account` i grafický instalátor.
- Příkazová řádka (i pro LSL / Lux Code):
  - `luxos-account status` → JSON `{"signedIn": true, "user": {...}}` (bez tokenu),
  - `luxos-account token` → vypíše session token (jen pro aplikace téhož uživatele),
  - `luxos-account login` → otevře okno přihlášení (vrátí 0 po přihlášení),
  - `luxos-account register` → totéž, rovnou se založením nového účtu,
  - `luxos-account register` → totéž, rovnou se založením nového účtu,
  - `luxos-account logout`.

## Vytvoření účtu

Účet jde založit přímo v LuxOS (instalátor – grafický i textový – a `luxos-account`), bez prohlížeče:

1. jméno, e-mail, heslo (12–128 znaků) a souhlas s podmínkami (text `GET /terms` se zobrazí v aplikaci),
2. `POST /api/auth/register/start` `{email, password, displayName, termsAccepted: true}` pošle 6místný kód,
3. `POST /api/auth/code/verify` `{email, code}` účet založí a vrátí `{ok, user, sessionToken}`.

Chyby: `invalid_email`, `email_domain_blocked`, `weak_password`, `terms_required`, `account_exists` (409),
`rate` / `slow_down` (429, `Retry-After`), `email_domain_check_unavailable` (503), `email_domain_review` (422).
Dokud server registraci z nativních klientů nepovolí (`403 {"error": "origin"}`), aplikace nabídnou
dokončení na webu (`https://lux-ai.cz/register`).
