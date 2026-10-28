#!/bin/bash
# LuxOS - prevedeni testovaciho kanalu do vydani: odkaz current na serveru ukaze na stejne vydani
# jako staging (https://luxos.lux-ai.cz/staging/ -> https://luxos.lux-ai.cz/repo/)
#
#   scripts/promote-staging.sh        ukaze obe vydani a po potvrzeni prepne current
#   scripts/promote-staging.sh -y     bez dotazu
#
# Nic se nenahrava ani nemaze: vydani pod staging uz na serveru je (scripts/publish-repo.sh s
# LUXOS_REPO_CHANNEL=staging), prepnuti current je atomicke (ln + mv -T) a staging zustava, kde je.
# Navrat: odkaz current zpet na predchozi vydani (vypise se), publish-repo.sh ho pri cisteni nesmaze,
# dokud na nej ukazuje current nebo staging, a jinak drzi 3 posledni vydani.
set -euo pipefail

HOST=${LUXOS_REPO_HOST:-root@185.183.156.25}
BASE=${LUXOS_REPO_DIR:-/srv/luxos-repo}
URL=${LUXOS_REPO_URL:-https://luxos.lux-ai.cz/repo}
yes=0
[[ ${1:-} == -y ]] && yes=1

staging=$(ssh "$HOST" "readlink '$BASE/staging'" || true)
current=$(ssh "$HOST" "readlink '$BASE/current'" || true)
[[ $staging =~ ^releases/[0-9]{8}-[0-9]{6}$ ]] || { echo "No staging release on $HOST ($BASE/staging)" >&2; exit 1; }
ssh "$HOST" "test -f '$BASE/$staging/luxos/x86_64/luxos.db.tar.gz'" \
    || { echo "$BASE/$staging has no [luxos] database" >&2; exit 1; }
echo "current: ${current:-(none)}"
echo "staging: $staging"
if [[ $current == "$staging" ]]; then
    echo "current already points to the staging release - nothing to do"
    exit 0
fi
if ((!yes)); then
    read -r -p "Publish $staging to everyone (current -> $staging)? [y/N] " a
    [[ $a == [yYaA]* ]] || { echo "Nothing changed."; exit 1; }
fi
ssh "$HOST" "set -e
    cd '$BASE'
    test -d '$staging'
    ln -sfn '$staging' current.new && mv -T current.new current"
echo "==> current -> $staging (previous: ${current:-none}; back: on $HOST in $BASE run ln -sfn $current current.new && mv -T current.new current)"
for r in luxos luxos-apps luxos-drivers; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$URL/$r/x86_64/$r.db")
    echo "    $URL/$r/x86_64/$r.db -> HTTP $code"
done
