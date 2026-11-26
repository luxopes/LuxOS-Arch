#!/bin/bash
set -euo pipefail

package=$(dirname -- "$(readlink -f -- "$0")")
source_dir="$package/../../packages/apps/luxos-vela"
stage=${1:?Provide an empty staging directory}
install -d "$stage/app"
test "$(jq -r .version "$package/lux.json")" = "$(jq -r .version "$source_dir/package.json")"

install -m644 "$package/lux.json" "$stage/lux.json"
install -m755 "$package/launcher" "$stage/app/luxos-vela"
install -m644 -t "$stage/app" "$source_dir/package.json" "$source_dir/package-lock.json"
cp -r "$source_dir/app" "$stage/app/"
cp -r "$package/share" "$stage/"
npm --prefix "$stage/app" ci --omit=dev --ignore-scripts --no-audit --no-fund
bash "$source_dir/prepare-rules.sh" "$stage/app/rules"
rsvg-convert -w 256 -h 256 "$package/share/icons/hicolor/scalable/apps/luxos-vela.svg" -o "$stage/app/luxos-vela.png"
install -Dm644 "$stage/app/luxos-vela.png" "$stage/share/icons/hicolor/256x256/apps/luxos-vela.png"
node "$source_dir/tests/blocker.cjs" "$stage/app"
node "$source_dir/tests/history.cjs" "$stage/app"
