#!/bin/bash
set -euo pipefail
target=$1
mkdir -p "$target"
staged=$(mktemp -d "$target/.fetch.XXXXXX")
trap 'rm -rf -- "$staged"' EXIT

for list in easylist easyprivacy; do
    curl --proto '=https' --fail --silent --show-error --retry 2 --max-time 45 --max-filesize 10000000 \
        "https://easylist.to/easylist/$list.txt" -o "$staged/$list.txt"
    head -1 "$staged/$list.txt" | grep -q '^\[Adblock Plus '
    test "$(wc -l < "$staged/$list.txt")" -gt 10000
done
for list in easylist easyprivacy; do
    install -m644 "$staged/$list.txt" "$target/$list.txt"
done
