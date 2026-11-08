# Posta LuxOS - znami velci poskytovatele posty: rozpoznani podle domeny adresy, serveru IMAP nebo zaznamu MX
# (Google Workspace, Microsoft 365 na vlastni domene) a zpusob prihlaseni, ktery poskytovatel z postovnich
# programu prijima:
#   "app_password"  normalni heslo nefunguje, jen heslo aplikace (Google, Yahoo, AOL, iCloud)
#   "oauth"         zadne heslo, jen prihlaseni tokenem OAuth2 (Microsoft od 2024/2025)
#   "password"      normalni heslo (pripadne heslo aplikace pri dvoufazovem overeni), IMAP nekdy treba povolit
# Texty pro uzivatele (s preklady) sklada okno; tady jen data bez site.
#
# Prihlaseni OAuth2 ("Prihlasit se Googlem/Microsoftem") je v mail_oauth (data v oauth-providers.json, stejna
# id poskytovatelu jako tady); "oauth_issuer" je jen informace, kdo token vydava. Tlacitko se ukaze, az ma
# poskytovatel registrovane client ID (docs/proposals/mail-oauth-registration.md), do te doby plati "auth" zde.

PROVIDERS = {
    "google": {"name": "Google", "auth": "app_password", "url": "https://myaccount.google.com/apppasswords",
               "webmail": "https://mail.google.com/", "oauth_issuer": "accounts.google.com"},
    "microsoft": {"name": "Microsoft", "auth": "oauth", "url": "",
                  "webmail": "https://outlook.live.com/mail/", "oauth_issuer": "login.microsoftonline.com"},
    "yahoo": {"name": "Yahoo", "auth": "app_password", "url": "https://login.yahoo.com/account/security",
              "webmail": "https://mail.yahoo.com/", "oauth_issuer": "api.login.yahoo.com"},
    "aol": {"name": "AOL", "auth": "app_password", "url": "https://login.aol.com/account/security",
            "webmail": "https://mail.aol.com/", "oauth_issuer": "api.login.aol.com"},
    "icloud": {"name": "iCloud", "auth": "app_password", "url": "https://account.apple.com/account/manage",
               "webmail": "https://www.icloud.com/mail", "oauth_issuer": ""},
    "seznam": {"name": "Seznam", "auth": "password", "url": "https://ucet.seznam.cz/",
               "webmail": "https://email.seznam.cz/", "oauth_issuer": ""},
    "centrum": {"name": "Centrum", "auth": "password", "url": "",
                "webmail": "https://mail.centrum.cz/", "oauth_issuer": ""},
    "gmx": {"name": "GMX", "auth": "password", "url": "",
            "webmail": "https://www.gmx.net/", "oauth_issuer": ""}}

DOMAINS = {"gmail.com": "google", "googlemail.com": "google",
           "outlook.com": "microsoft", "outlook.cz": "microsoft", "outlook.sk": "microsoft", "outlook.de": "microsoft",
           "msn.com": "microsoft", "passport.com": "microsoft",
           "ymail.com": "yahoo", "rocketmail.com": "yahoo", "aim.com": "aol",
           "icloud.com": "icloud", "me.com": "icloud", "mac.com": "icloud",
           "seznam.cz": "seznam", "email.cz": "seznam", "post.cz": "seznam", "spoluzaci.cz": "seznam",
           "centrum.cz": "centrum", "atlas.cz": "centrum", "volny.cz": "centrum", "centrum.sk": "centrum", "atlas.sk": "centrum",
           "web.de": "gmx"}

# prvni slovo domeny u poskytovatelu s mnoha narodnimi domenami (hotmail.cz, yahoo.co.uk, gmx.de ...)
FIRST_LABELS = {"hotmail": "microsoft", "live": "microsoft", "windowslive": "microsoft", "yahoo": "yahoo",
                "aol": "aol", "gmx": "gmx"}

# konce jmen serveru IMAP a MX
HOSTS = [[".gmail.com", "google"], [".googlemail.com", "google"], [".google.com", "google"],
         [".outlook.com", "microsoft"], [".office365.com", "microsoft"], [".hotmail.com", "microsoft"],
         [".yahoo.com", "yahoo"], [".yahoodns.net", "yahoo"], [".aol.com", "aol"],
         [".mail.me.com", "icloud"], [".icloud.com", "icloud"],
         [".seznam.cz", "seznam"], [".centrum.cz", "centrum"], [".atlas.cz", "centrum"], [".volny.cz", "centrum"],
         [".gmx.net", "gmx"], [".gmx.com", "gmx"], [".web.de", "gmx"]]

function by_host(host):
    h = String(host).strip().lower()
    if h.endswith("."):
        h = h[0:len(h) - 1]
    end
    if h == "":
        return ""
    end
    h = "." + h
    for pair in HOSTS:
        if h.endswith(pair[0]):
            return pair[1]
        end
    end
    return ""
end

function by_domain(domain):
    d = String(domain).strip().lower()
    if d in DOMAINS:
        return DOMAINS[d]
    end
    parts = d.split(".")
    # jen kratke narodni domeny (hotmail.cz, yahoo.co.uk), ne live.firma.cz
    if len(parts) >= 2 and len(parts) <= 3 and parts[0] in FIRST_LABELS:
        if len(parts) == 2 or len(parts[1]) <= 3:
            return FIRST_LABELS[parts[0]]
        end
    end
    return ""
end

# domena adresy, server IMAP (muze byt ""), jmena serveru MX (seznam textu) -> id poskytovatele nebo ""
function detect(domain, imap_host, mx_hosts):
    p = by_domain(domain)
    if p != "":
        return p
    end
    p = by_host(imap_host)
    if p != "":
        return p
    end
    for mx in mx_hosts:
        p = by_host(mx)
        if p != "":
            return p
        end
    end
    return ""
end

function domain_of(email):
    e = String(email).strip()
    at = e.find("@")
    if at < 0:
        return ""
    end
    return e[at + 1:].lower()
end

# Poskytovatel uctu: ulozeny pri pridani, jinak podle adresy a serveru
function of_account(a):
    p = String(a.get("provider", ""))
    if p != "" and p in PROVIDERS:
        return p
    end
    return detect(domain_of(a.get("email", "")), a.get("imap", {}).get("host", ""), [])
end

function info(id):
    if id in PROVIDERS:
        return PROVIDERS[id]
    end
    return {}
end

# Google na vlastni domene (Workspace): spravce muze hesla aplikaci zakazat
function workspace(id, domain):
    return id == "google" and by_domain(domain) != "google"
end
