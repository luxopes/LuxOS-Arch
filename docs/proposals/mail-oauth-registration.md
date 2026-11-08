# Pošta LuxOS: registrace „Přihlásit se Googlem / Microsoftem“ (OAuth2)

Stav: **kód je hotový, chybí jen registrace u poskytovatelů.** Pošta (`luxos-mail`) umí přihlášení
u poskytovatele jako Thunderbird: tlačítko **Přihlásit se účtem Google** / **Přihlásit se účtem
Microsoft**, systémový prohlížeč, návrat do Pošty, obnovovací token jen v klíčence. Tlačítko se
ukáže, jakmile je pro poskytovatele vyplněné **client ID**. Do té doby Pošta nabízí heslo aplikace
jako dřív.

Tento návod je pro vlastníka projektu: co zaregistrovat, kde, a kam ID vložit.

> **Nikdy nepoužívat client ID jiné aplikace** (Thunderbird, Evolution, K-9 …). Porušuje to podmínky
> Googlu i Microsoftu a poskytovatel takové ID může kdykoli zablokovat pro všechny uživatele.

## Co Pošta posílá (pro vyplnění formulářů)

| | Google | Microsoft |
| --- | --- | --- |
| Typ aplikace | Desktop app (installed app) | Public client, „Mobile and desktop applications“ |
| Přesměrování | `http://127.0.0.1:<náhodný port>/` | `http://localhost:<náhodný port>/` |
| PKCE | S256 | S256 |
| Rozsahy | `https://mail.google.com/ openid email` | `https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send offline_access openid email` |
| Další parametry | `access_type=offline`, `prompt=consent`, `login_hint` | `prompt=select_account`, `login_hint` |
| Tajemství klienta | ano (u Desktop klienta Google není důvěrné, je v balíku) | ne (veřejný klient) |
| IMAP / SMTP | `imap.gmail.com:993`, `smtp.gmail.com:465` (XOAUTH2/OAUTHBEARER) | `outlook.office365.com:993`, `smtp.office365.com:587` STARTTLS (XOAUTH2) |

Pošta naslouchá jen na loopbacku a jen během přihlášení (nejvýš 10 minut), kontroluje `state`
a kód vymění sama (PKCE). Port je náhodný; Google u Desktop klienta i Microsoft u `localhost`
port neporovnávají.

Odesílání pošty (SMTP) v Poště ještě není (fáze 2). Rozsah `SMTP.Send` / `https://mail.google.com/`
se ale žádá už teď, aby se uživatelé po přidání odesílání nemuseli přihlašovat znovu.

## 1. Microsoft (Outlook.com, Hotmail, Live, Microsoft 365)

Microsoft je jednodušší a má smysl ho udělat první: osobní účty Microsoftu **už heslo pro IMAP vůbec
nepřijímají**, takže bez registrace Pošta Outlook.com neumí.

1. Přihlaste se na <https://entra.microsoft.com> (stačí bezplatný účet Microsoft; pro ověření
   vydavatele je potřeba tenant firmy, viz bod 8). **Identity › Applications › App registrations ›
   New registration**.
2. **Name**: `LuxOS Mail` (uživatel ho vidí na stránce souhlasu).
3. **Supported account types**: *Accounts in any organizational directory (Any Microsoft Entra ID
   tenant – Multitenant) and personal Microsoft accounts (e.g. Skype, Xbox)*. Jen tato volba dovolí
   osobní účty (outlook.com, hotmail.com) i pracovní účty Microsoft 365.
4. **Redirect URI**: platforma **Public client/native (mobile & desktop)**, hodnota `http://localhost`.
   (Port Microsoft u `localhost` ignoruje – RFC 8252 § 7.3. Nepřidávejte více adres lišících se jen
   portem.) Pokud portál `http://` adresu odmítne, přidejte ji v **Manifest** do `replyUrlsWithType`
   s `"type": "InstalledClient"`.
5. **Register**. Na stránce **Overview** zkopírujte **Application (client) ID** (GUID) – to je
   jediný údaj, který Pošta potřebuje.
6. Tajemství klienta (Certificates & secrets) **nevytvářejte** – desktopová aplikace ho neumí utajit.
   **Authentication › Allow public client flows** nechte **No** (Pošta používá autorizační kód
   s PKCE přes platformu Mobile and desktop; tato volba zapíná jen device code / heslo v aplikaci).
7. **API permissions › Add a permission › APIs my organization uses** › vyhledat
   **Office 365 Exchange Online** › **Delegated permissions**:
   `IMAP.AccessAsUser.All` a `SMTP.Send`. Dále **Microsoft Graph › Delegated**: `offline_access`,
   `openid`, `email` (obvykle už jsou). *Grant admin consent* nedělejte – souhlas dává každý
   uživatel sám.
8. **Ověření vydavatele (publisher verification)**: bez něj uvidí uživatelé na stránce souhlasu
   „**Neověřeno**“ (unverified) a správci firem mohou mít nastavené, že uživatelé neověřeným
   aplikacím souhlas dát nesmí. Postup: účet v **Microsoft Partner Network (Microsoft AI Cloud
   Partner Program)** s ověřenou firmou (MPN ID), registrace aplikace musí být v tenantu, kde je
   ověřená doména (např. `lux-ai.cz`), pak **Branding & properties › Publisher verification › Add
   MPN ID**. Doplňte tam i **Home page URL** (`https://luxos.lux-ai.cz/`), **Terms of service**
   a **Privacy statement** (viz níže) a **Publisher domain** (`lux-ai.cz`, ověření souborem
   `/.well-known/microsoft-identity-association.json`).
9. Firmy s Microsoft 365: IMAP musí mít povolený jejich správce (Exchange Online › poštovní schránka
   › *IMAP* a *Authenticated SMTP*). Pošta pak ukáže „Poštovní server nepřijal přihlášení účtem
   Microsoft“ s důvodem od serveru.

Výsledek: `client_id` = Application (client) ID. **Tajemství žádné.**

## 2. Google (Gmail, Google Workspace)

Rozsah `https://mail.google.com/` je u Googlu **omezený (restricted)**. Bez ověření aplikace
Googlem funguje jen v režimu **Testing** pro ručně zadané testery.

1. <https://console.cloud.google.com> › nový projekt `LuxOS Mail` (organizace `lux-ai.cz`, je-li).
2. **APIs & Services › Library** › zapnout **Gmail API** (kvůli kontrole rozsahu; IMAP samotné API
   nepotřebuje, ale ověření rozsahu se vede přes něj).
3. **Google Auth Platform › Branding** (dříve *OAuth consent screen*):
   - **User type: External**,
   - App name `LuxOS Mail`, support e-mail, logo (vlastní ikona Pošty, ne loga Googlu),
   - **App home page** `https://luxos.lux-ai.cz/`, **Privacy policy**
     `https://luxos.lux-ai.cz/privacy` (viz níže), **Terms of service** (volitelně),
   - **Authorized domains**: `lux-ai.cz` – doménu je nutné ověřit v **Google Search Console**
     (DNS záznam TXT) stejným účtem.
4. **Data Access › Add or remove scopes**: `.../auth/userinfo.email`, `openid` a ručně
   `https://mail.google.com/` (zařadí se mezi *Restricted scopes*). Do zdůvodnění: „Plnohodnotný
   poštovní klient IMAP/SMTP; data zůstávají jen na počítači uživatele, žádný server LuxOS je
   nevidí.“
5. **Clients › Create client › Application type: Desktop app**, název `LuxOS Mail (desktop)`.
   Zkopírujte **Client ID** (`….apps.googleusercontent.com`) a **Client secret** (`GOCSPX-…`).
   U Desktop klienta Google tajemství nepovažuje za důvěrné (RFC 8252 § 8.5) – patří do balíku.
   Přesměrování se nezadává; Desktop klient přijme `http://127.0.0.1:<libovolný port>/`.
6. **Audience › Publishing status: Testing** – omezení:
   - nejvýš **100 testovacích uživatelů** (Audience › Test users, každý ručně svým e-mailem Google),
   - **obnovovací token vyprší po 7 dnech** – uživatel pak v Poště uvidí klidný pruh „Vaše
     přihlášení Google … vypršelo“ a klikne **Přihlásit se znovu…**,
   - stránka souhlasu ukazuje „Google tuto aplikaci neověřil“.
   Pro LuxOS jako veřejnou distribuci je to jen na vyzkoušení.
7. **Ověření pro produkci (Publish app › In production)**:
   - **ověření značky a domény** (název, logo, domovská stránka na ověřené doméně, zásady ochrany
     osobních údajů na stejné doméně, odkaz na ně z domovské stránky),
   - **ověření omezeného rozsahu** – video ukazující přihlášení a použití Gmailu v Poště,
     zdůvodnění, že užší rozsah nestačí (klient IMAP potřebuje `https://mail.google.com/`),
   - **bezpečnostní posouzení CASA** (Cloud Application Security Assessment, App Defense Alliance)
     u schváleného posuzovatele; opakuje se **každých 12 měsíců**. Pro aplikaci, která data
     uživatelů neposílá na vlastní server, bývá k dispozici nižší úroveň (Tier 2, samoposouzení se
     skenem). Cena a termíny se mění – ověřit aktuální podmínky v konzoli při podání.
   - Celé ověření trvá týdny. Do té doby lze zůstat v režimu Testing.
8. Google Workspace: správce firmy může aplikaci třetí strany zakázat nebo ji musí povolit
   (Admin console › Security › API controls › App access control). Uživatel pak uvidí chybu od
   Googlu přímo v prohlížeči.

Výsledek: `client_id` + `client_secret` (Desktop app).

## 3. Yahoo a AOL – zatím ne

Koncové body (`https://api.login.yahoo.com/oauth2/request_auth`, `/oauth2/get_token`; AOL totéž na
`api.login.aol.com`) a rozsah `mail-w` jsou v souboru poskytovatelů připravené, ale **vypnuté**
(`"enabled": false`), protože:

- rozsahy pošty Yahoo **nejsou k dispozici v samoobsluze** vývojářské konzole – je nutné požádat
  formulářem <https://senders.yahooinc.com/developer/developer-access-mail-form/> (nebo
  `mail-api@yahooinc.com`) a Yahoo přístup schvaluje a může ho odebrat,
- Yahoo vyžaduje tajemství klienta a dokumentace neuvádí PKCE ani pravidla pro loopback s portem
  (Thunderbird používá pevnou adresu `https://127.0.0.1`),
- AOL má samostatné údaje klienta pro svůj „namespace“.

Až Yahoo přístup schválí: v souboru poskytovatelů nastavit `"enabled": true`, `client_id`,
`client_secret` a podle registrace `redirect_port` (pevný port, např. `8765`, pokud Yahoo port
porovnává). Do té doby Pošta u Yahoo/AOL nabízí heslo aplikace (funguje).

## 4. Kam vložit ID

Tři možnosti, podle situace:

1. **Do balíku** (doporučeno, trvalé): `packages/apps/luxos-mail/files/oauth-providers.json`,
   položky `providers.google.client_id`, `providers.google.client_secret`,
   `providers.microsoft.client_id`. Zvýšit `pkgrel` balíku `luxos-mail`, sestavit a publikovat.
   Testy (`test_oauth.py` › `test_shipped_file_has_no_ids`) dnes hlídají, že jsou prázdná – při
   vyplnění test upravit (např. kontrolovat tvar ID místo prázdnoty).
2. **Bez nového balíku – server LuxOS**: na `https://luxos.lux-ai.cz/mail-oauth.json` dát
   ```json
   {"version": 1, "providers": {
     "google": {"client_id": "….apps.googleusercontent.com", "client_secret": "GOCSPX-…"},
     "microsoft": {"client_id": "00000000-0000-0000-0000-000000000000"}}}
   ```
   Pošta soubor stáhne při otevření okna Přidat účet (nejvýš jednou denně, jen když nějaké ID
   chybí), zkontroluje tvar a uloží do `~/.cache/luxos-mail/mail-oauth.json`. Ze souboru bere
   **jen** `client_id`/`client_secret` známých poskytovatelů a **jen tam, kde je ID v balíku
   prázdné** – koncové body, rozsahy ani servery ze serveru nikdy nemění.
3. **Na jednom počítači (správce)**: `/etc/luxos/mail-oauth.json`, např.
   `{"providers": {"microsoft": {"client_id": "…"}}}` – má přednost před balíkem i serverem;
   `{"remote": false}` vypne stahování ze serveru LuxOS.

Účty už přihlášené si pamatují client ID, kterým byl token vydán (obnovovací token patří
konkrétnímu klientovi), takže pozdější změna ID je nerozbije.

### Proč je stahování ze serveru zapnuté a proč je bezpečné

- Přenáší se jen veřejné údaje: client ID není tajné a „tajemství“ Desktop klienta Google také ne.
- Útočník, který by ovládl `luxos.lux-ai.cz`, by mohl podvrhnout jen **jiné client ID**. Kód
  přihlášení ale vždy jde na loopback tohoto počítače a bez PKCE ověřovače z paměti Pošty je
  bezcenný; koncové body (kam jde heslo a obnovovací token) jsou pevně v balíku. Nejhorší dopad:
  přihlášení selže nebo uživatel uvidí na stránce Googlu/Microsoftu cizí název aplikace.
- HTTPS s ověřením certifikátu, limit velikosti 64 KB, přísná kontrola tvaru, nic jiného se
  neukládá. Podpis souboru zatím není (stačilo by to jen při ohrožení serveru, viz výše).

## 5. Zásady ochrany osobních údajů (potřeba pro Google i Microsoft)

Stránka `https://luxos.lux-ai.cz/privacy` (a anglicky) musí říkat aspoň: Pošta LuxOS je program na
počítači uživatele; přístup k poště (Gmail/Outlook) používá jen ke čtení a odesílání pošty na tomto
počítači; tokeny ukládá jen v klíčence uživatele; žádná data pošty ani tokeny neposílá na servery
LuxOS ani třetím stranám; přístup lze zrušit odebráním účtu v Poště a na stránce zabezpečení účtu
Google/Microsoft. Odkaz na stránku musí být z domovské stránky.

## 6. Kontrola po vložení ID

1. `luxos-mail --test-oauth-providers` – u poskytovatele `"available": true`.
2. Pošta › Přidat účet › adresa `@gmail.com` / `@outlook.com` → tlačítko **Přihlásit se účtem …**.
3. Přihlášení v prohlížeči → stránka „Jste přihlášeni“ → okno Pošty v popředí, účet se stahuje.
4. V *Hesla a klíče* záznam „LuxOS Mail (Google): adresa“; v `~/.config/luxos-mail/accounts.json`
   žádný token.
