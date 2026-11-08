# Verejna ID pro prihlaseni v Poste (OAuth)

Server: https://luxos.lux-ai.cz/mail-oauth.json (soubor /srv/luxos-site/mail-oauth.json, publish-site.sh ho nemaze).
Repozitar obsahuje jen ID Microsoftu (mail-oauth.json). Uplna verze vcetne client_secret Google je mimo git:
~/.local/share/luxos/mail-oauth/mail-oauth.json (vlastnik projektu). Secret Google pro "Desktop app" neni
duverny, ale do verejneho gitu nepatri - skenovani tajemstvi (GitHub) by ho mohlo nahlasit a Google zneplatnit.
Nasazeni: scp ~/.local/share/luxos/mail-oauth/mail-oauth.json root@185.183.156.25:/srv/luxos-site/
