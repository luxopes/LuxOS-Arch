#!/usr/bin/env bash
# LuxOS - oznameni zmenenych stranek webu vyhledavacum pres IndexNow (Bing, Seznam.cz, Yandex, Naver;
# Google IndexNow nepouziva - pro nej staci sitemap v Search Console).
#
#   scripts/indexnow-submit.sh            vsechny URL ze sitemap.xml zverejneneho webu
#   scripts/indexnow-submit.sh URL...     jen vybrane adresy (https://luxos.lux-ai.cz/...)
#
# Spoustet AZ PO scripts/publish-site.sh: vyhledavac si overi klic stazenim https://luxos.lux-ai.cz/<klic>.txt
# (klic je verejny, je v site/indexnow-key.txt a build-site.py ho publikuje). Odpoved 200 nebo 202 = prijato,
# 403 = klic na webu neni nebo nesedi, 422 = URL nepatri k hostu, 429 = prilis casto (pockej).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
HOST=luxos.lux-ai.cz
KEY=$(tr -d '[:space:]' <"$ROOT/site/indexnow-key.txt")
[[ $KEY =~ ^[A-Za-z0-9-]{8,128}$ ]] || { echo "indexnow: invalid key in site/indexnow-key.txt" >&2; exit 1; }

# klic musi byt na webu, jinak by vyhledavac pozadavek odmitl
live=$(curl -fsS --max-time 20 "https://$HOST/$KEY.txt" | tr -d '[:space:]' || true)
if [[ $live != "$KEY" ]]; then
    echo "indexnow: https://$HOST/$KEY.txt is not published yet - run scripts/publish-site.sh first" >&2
    exit 1
fi

if (($#)); then
    urls=("$@")
else
    mapfile -t urls < <(curl -fsS --max-time 30 "https://$HOST/sitemap.xml" | grep -o '<loc>[^<]*</loc>' | sed 's/<[^>]*>//g')
fi
((${#urls[@]})) || { echo "indexnow: no URLs" >&2; exit 1; }
for u in "${urls[@]}"; do
    [[ $u == "https://$HOST/"* ]] || { echo "indexnow: $u is not on $HOST" >&2; exit 1; }
done

body=$(python3 -I -c 'import json, sys
print(json.dumps({"host": sys.argv[1], "key": sys.argv[2], "keyLocation": f"https://{sys.argv[1]}/{sys.argv[2]}.txt",
                  "urlList": sys.argv[3:]}))' "$HOST" "$KEY" "${urls[@]}")
code=$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' -X POST "https://api.indexnow.org/indexnow" \
    -H 'Content-Type: application/json; charset=utf-8' --data-binary "$body")
echo "indexnow: ${#urls[@]} URLs submitted, HTTP $code"
[[ $code == 200 || $code == 202 ]]
