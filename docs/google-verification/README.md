# Ověření aplikace LuxOS Mail u Googlu (OAuth, omezený rozsah Gmailu)

Postup pro vlastníka projektu (Antonín Tomeček, info@lux-ai.cz). Projekt Google Cloud **LuxOS Mail**
(ID `luxos-mail`), klient OAuth typu **Desktop app**, client ID
`167842547008-kl3g01rd4b424v6q8msuj7ue47eodm52.apps.googleusercontent.com`.
Rozsahy: `https://mail.google.com/` (omezený / restricted), `openid`, `.../auth/userinfo.email`.

Texty, které se vkládají do Google Cloud Console, jsou **anglicky** a připravené ke zkopírování.

Zdroje požadavků (stav 8. 11. 2026):
[Production readiness](https://developers.google.com/identity/protocols/oauth2/production-readiness),
[Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification),
[OAuth app verification](https://support.google.com/cloud/answer/9110914),
[Verification requirements](https://support.google.com/cloud/answer/13464321),
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
[Google Workspace API User Data and Developer Policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy),
[Security assessment](https://support.google.com/cloud/answer/13465431).

## 0. Co je hotové a co zbývá

Hotové (v této větvi):

| Co | Kde |
|---|---|
| Domovská stránka aplikace (en + cs) | `site/pages/mail.*.html` → https://luxos.lux-ai.cz/mail/ a /cs/mail/ |
| Zásady ochrany soukromí celého LuxOS s oddílem o datech Google a přesnou větou Limited Use | `site/pages/privacy.*.html` → https://luxos.lux-ai.cz/privacy/ (kotva `#google-user-data`) |
| Podmínky použití | `site/pages/terms.*.html` → https://luxos.lux-ai.cz/terms/ |
| Odkazy v patičce všech stránek, kontrola obsahu | `scripts/build-site.py`, `scripts/check-site.py` |
| Logo 120×120 PNG (vlastní ikona Pošty, žádné prvky Apple/Google) | `docs/google-verification/luxos-mail-logo-120.png` |
| Upozornění v aplikaci před souhlasem + tlačítko Zásady ochrany soukromí; odebrání účtu odvolá přístup u Googlu | `luxos-mail` 1.0.0-7, `luxos-i18n` 64 |
| Automaticky nahrané části videa a náhled celého videa | `~/LuxOS-Arch/out/google-verification/` |
| Skript pro váš záznam skutečného souhlasu, který ho rovnou vloží do videa | `docs/google-verification/record-consent.sh` |

Zbývá (jen vy – vyžaduje váš účet Google, DNS nebo zveřejnění):

1. [ ] Ověřit doménu `lux-ai.cz` v Search Console (kap. 1) – možná už je hotové.
2. [ ] Schválit a zveřejnit web: `scripts/publish-site.sh` (kap. 2).
3. [ ] Nasadit `mail-oauth.json` s klientem Google na server a vydat balíky `luxos-mail` 1.0.0-7,
       `luxos-i18n` 64, `luxos-docs` 44 (kap. 3) – video má ukazovat stejnou verzi, jakou dostanou uživatelé.
4. [ ] Vyplnit Branding, Audience a Data access v Google Cloud Console (kap. 4–6).
5. [ ] Nahrát skutečný souhlas `record-consent.sh`, zkontrolovat video, nahrát ho na YouTube jako
       **Neveřejné (Unlisted)** (kap. 7).
6. [ ] Odeslat k ověření a odpovídat na e-maily Googlu (kap. 8–9).
7. [ ] Po schválení přepnout Audience na **In production** (kap. 10).

## 1. Ověření domény lux-ai.cz (Google Search Console)

Google vyžaduje, aby všechny **Authorized domains** (u nás `lux-ai.cz`) byly ověřené v Search Console
**účtem, který je Owner nebo Editor projektu `luxos-mail`**. Domovská stránka i zásady jsou na
`luxos.lux-ai.cz`, tedy pod `lux-ai.cz` – stačí ověřit `lux-ai.cz` jako **doménovou službu** (Domain property).

**Pozor – už existuje záznam:** DNS `lux-ai.cz` už obsahuje
`TXT "google-site-verification=5dg9y4Hx1ZEjpAG4VcoA_fy13C24DYWgW_s_DFEMsms"` (zjištěno 8. 11. 2026).
Doména tedy možná už je ověřená. Nejdřív zkontrolujte:

1. Otevřete https://search.google.com/search-console pod stejným účtem Google, který vlastní projekt `luxos-mail`.
2. Pokud v seznamu služeb vidíte **lux-ai.cz** (Domain property) a v Settings → Users and permissions jste
   **Owner** (ověřený vlastník), je hotovo – pokračujte kapitolou 2. Stávající TXT záznam **nemažte**.
3. Pokud tam není (nebo je ověřená jiným účtem), přidejte ji:
   - **Add property → Domain** → `lux-ai.cz` → Continue.
   - Search Console ukáže záznam `google-site-verification=…` – zkopírujte ho (hodnotu dostanete jen tam).

DNS domény `lux-ai.cz` je u **WEDOS** (`ns.wedos.cz`, `ns.wedos.eu`, `ns.wedos.com`, `ns.wedos.net`):

1. Přihlaste se do https://client.wedos.com → **Domény** → `lux-ai.cz` → **DNS záznamy** (WEDOS DNS).
2. **Přidat záznam**: Jméno **prázdné** (= samotná doména `lux-ai.cz`, ne `www` ani `luxos`), TTL `300`,
   Typ **TXT**, Data `google-site-verification=…` (přesně z Search Console, bez uvozovek navíc).
   Stávající TXT záznamy (SPF `v=spf1 …` a starší `google-site-verification`) **ponechte** – TXT záznamů
   může být víc.
3. **Uložit** a nahoře **Aplikovat změny** (WEDOS změny bez potvrzení nezveřejní).
4. Kontrola po několika minutách (do hodiny):
   `curl -s -H 'accept: application/dns-json' 'https://cloudflare-dns.com/dns-query?name=lux-ai.cz&type=TXT'`
   (nebo `dig +short TXT lux-ai.cz`, když máte `bind`) – musí obsahovat nový záznam.
5. V Search Console **Verify**.

## 2. Zveřejnění webu (schvalujete vy)

```bash
scripts/build-site.py && scripts/check-site.py     # kontrola bez nahrávání (potřebuje python-markdown)
scripts/publish-site.sh                             # sestavení, kontrola a nahrání na luxos.lux-ai.cz
```

Po zveřejnění zkontrolujte v prohlížeči bez přihlášení (Google vyžaduje veřejný přístup):
https://luxos.lux-ai.cz/mail/, https://luxos.lux-ai.cz/privacy/#google-user-data, https://luxos.lux-ai.cz/terms/.

**Před zveřejněním si prosím přečtěte zásady** (`site/pages/privacy.en.html`) – popisují skutečné chování
kódu v repozitáři. Z repozitáře se nedalo zjistit (a zásady to proto netvrdí konkrétně):

- jak dlouho server lux-ai.cz uchovává hlášení zpětné vazby, historii chatu a přístupové logy,
- zda služba LuxAI předává dotazy dalšímu poskytovateli modelu AI (pokud ano, doplňte do oddílu 4 jeho jméno
  a že dostává obsah dotazu – je to zpracovatel podle GDPR),
- vaši doručovací adresu (GDPR ji u správce vyžaduje – doplňte do oddílu 1, pokud ji chcete uvést).

Oddíl o Google (2) se týká jen Pošty a je přesný – data z Googlu na žádný server LuxOS nejdou.

## 3. Client ID v Poště a nové balíky

Aby se v Poště ukázalo tlačítko „Sign in with Google“, musí mít klienta Google:

- Na server patří úplný `mail-oauth.json` i s Google `client_id` a `client_secret` (mimo git, viz
  `server/mail-oauth/README-ids.md`):
  `scp ~/.local/share/luxos/mail-oauth/mail-oauth.json root@185.183.156.25:/srv/luxos-site/`
- Posta stahuje ID nejvýš jednou denně; na svém počítači to urychlíte smazáním
  `~/.cache/luxos-mail/mail-oauth.json` a novým spuštěním Pošty.
- Vydejte balíky `luxos-mail` 1.0.0-7, `luxos-i18n` 64, `luxos-docs` 44 (`scripts/publish-repo.sh`) a na svém
  počítači `sudo lux update` – ve videu má být verze s upozorněním před přihlášením.

## 4. Branding (Google Auth Platform → Branding)

| Pole | Hodnota |
|---|---|
| App name | `LuxOS Mail` (stejně jako na domovské stránce a ve videu) |
| User support email | `info@lux-ai.cz` (musí to být váš e-mail nebo skupina, kterou spravujete) |
| App logo | `docs/google-verification/luxos-mail-logo-120.png` (120×120, PNG, 5 KB) |
| Application home page | `https://luxos.lux-ai.cz/mail/` |
| Application privacy policy link | `https://luxos.lux-ai.cz/privacy/` |
| Application terms of service link | `https://luxos.lux-ai.cz/terms/` |
| Authorized domains | `lux-ai.cz` |
| Developer contact information | `info@lux-ai.cz` |

Pozn.: s nahraným logem Google vyžaduje ověření značky (brand verification, obvykle 2–3 pracovní dny); během
ověřování nejde branding měnit.

## 5. Audience

- **User type: External.**
- Dokud čekáte na ověření, nechte **Publishing status: Testing** a do **Test users** přidejte testovací účet
  Gmail, kterým budete nahrávat video (max. 100 testerů). V režimu Testing obnovovací token vyprší po
  7 dnech – v Poště se pak objeví žlutý pruh „Sign in again“ (to je v pořádku).

## 6. Data access (rozsahy a zdůvodnění)

**Add or remove scopes** → zaškrtněte / vložte ručně:

- `https://mail.google.com/` (Gmail – restricted)
- `openid`
- `https://www.googleapis.com/auth/userinfo.email`

Nic jiného nepřidávejte (Google vyžaduje jen nejužší potřebné rozsahy; Pošta nic dalšího nežádá – viz
`packages/apps/luxos-mail/files/oauth-providers.json`).

Pokud formulář nabídne typ aplikace / funkce, zvolte **Email client** (desktopový poštovní klient).

**Justification / How will the scopes be used** (vložte, upravte jen pokud se něco změní):

```text
LuxOS Mail is the desktop email client of LuxOS, a free Linux distribution (https://luxos.lux-ai.cz/mail/).
It is a full IMAP mail client that runs entirely on the user's computer, similar to Thunderbird.
When the user adds a Gmail or Google Workspace address and clicks "Sign in with Google", the app uses
OAuth 2.0 for native apps (system browser, loopback redirect, PKCE) and then connects directly from the
user's computer to imap.gmail.com (and later smtp.gmail.com) with SASL XOAUTH2/OAUTHBEARER.

How https://mail.google.com/ is used (all user-facing features of a mail client):
- list the user's folders/labels and messages, download and display message headers, bodies and attachments;
- keep a local cache on the user's computer for offline reading and searching;
- instant new-mail notifications with IMAP IDLE;
- actions the user takes: mark as read/unread, move to Trash;
- sending mail via SMTP in an upcoming version (the same scope covers SMTP).

Why narrower scopes are not sufficient: Google allows IMAP, POP and SMTP access with OAuth only with the
https://mail.google.com/ scope. The narrower Gmail scopes (gmail.readonly, gmail.modify, gmail.send, ...)
work only with the Gmail REST API, not with IMAP/SMTP. LuxOS Mail is a standards-based IMAP/SMTP client
that works the same way with every provider (Gmail, Microsoft, any IMAP server), so it needs the IMAP scope.

openid and userinfo.email are used only to read the e-mail address of the signed-in Google account, so the
account in the app matches the address the user typed.

Data handling: Google user data is stored only on the user's own computer (mail cache in the user's home
folder, the refresh token in the encrypted desktop keyring). It is never transferred to LuxOS servers or to
any third party; there is no server-side component that can access Gmail data. It is not used for ads, not
sold, not used to train AI/ML models, and not read by humans. Removing the account in the app deletes the
local data and revokes the token at Google (oauth2.googleapis.com/revoke).
```

**Demo video**: vložte odkaz YouTube (kap. 7).

## 7. Ukázkové video

Google chce (Verification requirements, Restricted scope verification): celý průběh v aplikaci včetně
**udělení souhlasu OAuth**, celou obrazovku souhlasu **v angličtině** s přesně požadovanými rozsahy,
**adresní řádek prohlížeče s client ID**, název aplikace a ukázku funkcí, které rozsah používají;
video na YouTube jako **Unlisted**. Délku Google nepředepisuje; video drží do 3 minut.

Video má tři části (titulky jsou v obraze, bez komentáře):

1. **Add account** – plocha LuxOS, Pošta z Docku, Add Account, adresa Gmail, upozornění o použití dat,
   tlačítko „Sign in with Google“ (automaticky, `parts/part-a.mp4`).
2. **Google consent** – **váš skutečný záznam** (`record-consent.sh`).
3. **Mail uses the scope** – doručená pošta, čtení zpráv, příloha, označení nepřečtené, filtr, přesun do
   Koše, složky (štítky Gmailu), odebrání účtu s odvoláním přístupu (automaticky, `parts/part-b.mp4`).

Automatické části nahrál `record-demo.sh` na virtuální obrazovce s ukázkovou schránkou (falešný server IMAP
v podobě Gmailu, ukázkové zprávy, adresa `alex.morgan.luxos.demo@gmail.com`); nic se při tom neposílalo na
Google. Náhled s kartou místo souhlasu: `~/LuxOS-Arch/out/google-verification/luxos-mail-demo-preview.mp4`.

### Váš záznam souhlasu

V terminálu na své ploše LuxOS (X11):

```bash
cd ~/LuxOS-Arch
docs/google-verification/record-consent.sh                       # primární monitor, max. 60 s
# volitelně: --email vas.test@gmail.com  (automatické části se nejdřív přenahrají s vaší testovací adresou,
#            aby adresa ve videu všude odpovídala; trvá asi 3 minuty)
#            --monitor HDMI-1 | --area 1920x1080+0+0 | --trim-start 2
```

Skript vypíše kontrolní seznam, po Enteru odpočítá 5 s, nahrává jen váš monitor (bez zvuku) a zastaví se
libovolnou klávesou v terminálu. Postup během nahrávání:

1. V Poště je otevřené Add Account s napsanou testovací adresou → klikněte **Sign in with Google**.
2. V prohlížeči vyberte testovací účet. Klikněte na chvíli do adresního řádku, ať je vidět
   `client_id=167842547008-…` (Google to výslovně kontroluje).
3. V režimu Testing se ukáže „Google hasn’t verified this app“ → **Advanced** → **Go to LuxOS Mail (unsafe)**.
4. Obrazovka souhlasu: název **LuxOS Mail**, oprávnění Gmailu („Read, compose, send and permanently delete all
   your email from Gmail“) – je-li zaškrtávátko, zaškrtněte → **Continue**.
5. „You are signed in“ → Pošta načte schránku → klávesa v terminálu = konec.

Stránka Googlu musí být anglicky: jazyk prohlížeče angličtina, nebo dole na stránce Googlu vyberte
**English (United States)**. Použijte **testovací účet**, ne osobní schránku – její obsah bude ve videu.

Výsledek: `~/LuxOS-Arch/out/google-verification/luxos-mail-demo-final.mp4` (1920×1080, 30 fps, H.264,
s tichou zvukovou stopou). Přehrajte si ho celé, pak ho **sami** nahrajte na YouTube (Studio → Create →
Upload, Visibility **Unlisted**) a odkaz vložte do Data access. Skript nic nenahrává.

Automatické části jde kdykoli přenahrát: `docs/google-verification/record-demo.sh` (virtuální obrazovka,
přeloží Poštu ze zdrojů; `--debug` uloží snímky jednotlivých kroků).

## 8. Odeslání k ověření

Google Auth Platform → **Verification Center** → **Prepare for verification** / **Submit for verification**:
zkontrolujte, že branding, domény, rozsahy, zdůvodnění a video jsou vyplněné, potvrďte souhlas s
User Data Policy a odešlete. Google pošle potvrzení na kontaktní e-mail (`info@lux-ai.cz`) a další dotazy
chodí také tam – **odpovídejte na stejné vlákno**. Ověření omezených rozsahů trvá i několik týdnů.

## 9. Očekávané dotazy a připravené odpovědi (anglicky)

**Security assessment (CASA) – proč ho nepotřebujeme.** Google: „Every app that requests access to Google
users' restricted data and has the ability to access data from or through a third-party server must go
through a security assessment.“ Pošta takový server nemá. Odpověď:

```text
LuxOS Mail is a desktop IMAP client. All Gmail data flows only between the user's computer and Google
(accounts.google.com, oauth2.googleapis.com, imap.gmail.com, smtp.gmail.com). We operate no server that
receives, stores, proxies or can access Google user data: tokens are exchanged by the app on the user's
computer, the refresh token is stored in the user's local keyring, mail is cached only in the user's home
folder. The only LuxOS server the app contacts is https://luxos.lux-ai.cz/mail-oauth.json, a static public
file with OAuth client IDs, which contains and receives no user data. Therefore the app does not have the
ability to access restricted data from or through a third-party server, and we believe the CASA security
assessment does not apply. The source code is public (GPL-3.0-or-later) and we are happy to provide any
further details.
```

**„Narrower scopes would be sufficient (gmail.readonly / gmail.modify).“**

```text
Those scopes are not accepted by Gmail's IMAP and SMTP servers; Google documents https://mail.google.com/
as the scope for IMAP, POP and SMTP with XOAUTH2. LuxOS Mail is a generic IMAP/SMTP client (it works with
any provider), so it cannot use the Gmail REST API scopes. We request no other Google scopes besides
openid and userinfo.email.
```

**„The demo video does not show the feature that uses the scope / show sending.“**

```text
The current version reads mail: listing folders and messages, reading messages and attachments, marking
read/unread, moving to Trash, and new-mail notifications (IMAP IDLE) - all shown in part 3 of the video.
Sending over SMTP will be added in a future version, using the same scope; we will update the
verification if Google requires it.
```

**„The video uses demo data / a different account.“**

```text
Part 2 is a recording of the real Google consent screen for our OAuth client on the developer's computer.
Parts 1 and 3 show the same, unmodified LuxOS Mail with a demo mailbox (sample messages) so that no real
user's mail is visible; the app behaves identically with a real Gmail account. We can record the complete
flow with a test account if you prefer.
```

**„Your privacy policy must disclose … / Limited Use statement.“** Zásady obsahují oddíl
„LuxOS Mail and Google user data“ (přístup, použití, uložení, sdílení, odvolání, smazání) a přesnou větu:
*LuxOS Mail's use and transfer to any other app of information received from Google APIs will adhere to the
Google API Services User Data Policy, including the Limited Use requirements.* – odpovězte odkazem
`https://luxos.lux-ai.cz/privacy/#google-user-data`.

**„In-app disclosure / user consent before access.“** Pošta v okně Add Account před tlačítkem
„Sign in with Google“ ukazuje: *„Mail uses this access only to download, show and organize your mail on this
computer. Your mail and the sign-in stay on this computer and are never sent to LuxOS or anyone else.“* a
tlačítko **Privacy Policy** (vidět ve videu, část 1).

**„How can users delete their data?“**

```text
In LuxOS Mail: menu -> Remove <address>. This deletes all locally cached mail and settings of the account,
deletes the refresh token from the keyring and revokes the token at Google (oauth2.googleapis.com/revoke).
Users can also revoke access at https://myaccount.google.com/permissions. LuxOS holds no Google user data on
any server, so there is nothing to delete on our side; requests can be sent to info@lux-ai.cz.
```

**„The client secret is embedded in the app.“** Klient typu Desktop app nemá důvěrné tajemství (Google to
pro instalované aplikace uvádí); Pošta používá PKCE. Tajemství není v gitu, Pošta ho stahuje z
`https://luxos.lux-ai.cz/mail-oauth.json`.

**„Homepage / privacy policy is not accessible or not on the verified domain.“** Obě stránky jsou na
`luxos.lux-ai.cz` (pod ověřenou `lux-ai.cz`), veřejné, bez přihlášení; domovská stránka odkazuje na zásady.

## 10. Po schválení

1. Audience → **Publish app** → Publishing status **In production** (zmizí varování „unverified app“, limit
   100 testerů a 7denní platnost tokenů).
2. Změny názvu, loga, domén nebo rozsahů znamenají nové ověření – před změnou si to rozmyslete.
3. U omezených rozsahů Google kontroluje aplikaci znovu zhruba jednou ročně (e-mail na kontakt projektu);
   udržujte kontaktní e-maily a role Owner/Editor aktuální.
4. Když Pošta přidá odesílání nebo jiné využití dat, upravte zásady (oddíl 2) a případně zdůvodnění.

## Soubory

| Soubor | Účel |
|---|---|
| `README.md` | tento postup |
| `luxos-mail-logo-120.png` | logo pro Branding (z `packages/apps/luxos-mail/files/luxos-mail.svg`) |
| `record-demo.sh`, `record_demo.py` | automatický záznam částí 1 a 3 (xvfb, falešné servery, žádná síť) |
| `demo_imap.py` | ukázkový server IMAP v podobě Gmailu (z testů Pošty) |
| `assemble.py` | karty, titulky a složení videa (ffmpeg) |
| `record-consent.sh` | váš záznam skutečného souhlasu + složení výsledného videa |
