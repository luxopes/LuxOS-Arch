#!/bin/bash
# mDNS jen Avahi: systemd-resolved s MulticastDNS=no (regrese audit 1.0.2: live ISO "Detected another
# IPv4 mDNS stack", pocitac prejmenovany na luxos-2). Ve VM overeno: resolvectl "-mDNS", Avahi bez konfliktu.
#   bash packages/luxos-tweaks/tests/test-mdns.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
F=$HERE/../files/resolved-mdns.conf
fail=0
ok() { if "${@:2}"; then echo "ok    $1"; else echo "FAIL  $1"; fail=1; fi; }
ok "[Resolve] MulticastDNS=no" bash -c "grep -qx '\[Resolve\]' '$F' && grep -qx 'MulticastDNS=no' '$F'"
ok "nic jineho se nemeni" bash -c "! grep -vE '^(#.*|\[Resolve\]|MulticastDNS=no|)$' '$F'"
ok "PKGBUILD: /usr/lib/systemd/resolved.conf.d" grep -q 'resolved.conf.d/50-luxos-mdns.conf' "$HERE/../PKGBUILD"
exit $fail
