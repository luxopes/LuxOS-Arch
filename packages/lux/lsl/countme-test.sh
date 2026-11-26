#!/bin/bash
# lux_countme.py a lux-countme (LSL): stejny pozadavek bajt po bajtu a stejny stav po odeslani.
# Mistni HTTP server zaznamena pozadavek; cas je pevny (LUX_COUNTME_NOW), stav a zamek v docasne slozce,
# "root" jen v user namespace. Nic se neposila na skutecny server.
#   packages/lux/lsl/countme-test.sh /cesta/lux-countme
set -u
LSL=$1; here=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
cat > "$T/srv.py" <<'PY'
import socket, sys
port, out, status = int(sys.argv[1]), sys.argv[2], sys.argv[3]
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", port)); s.listen(5); open(out + ".ready", "w").write("1")
while True:
    c, _ = s.accept(); data = b""
    while b"\r\n\r\n" not in data:
        d = c.recv(4096)
        if not d: break
        data += d
    open(out, "ab").write(data)
    c.sendall(("HTTP/1.1 %s X\r\nContent-Length: 0\r\nConnection: close\r\n\r\n" % status).encode()); c.close()
PY
fails=0; n=0
case_() {  # case_ JMENO HTTP-STATUS [STAV-PRED]
    local name=$1 st=$2 pre=${3:-} port=$((20000 + RANDOM % 20000)) w d sp
    n=$((n+1))
    for w in py lsl; do
        d=$T/$w-$name; mkdir -p "$d"; [[ -n $pre ]] && echo "$pre" > "$d/countme"
        python3 "$T/srv.py" $port "$d/req" $st & sp=$!
        for _ in $(seq 50); do [[ -e $d/req.ready ]] && break; sleep 0.1; done
        if [[ $w == py ]]; then
            python3 - <<PY > "$d/out" 2>&1
import sys; sys.path.insert(0, "/usr/lib/lux"); import lux_countme as c
r = c.run_once(now=1795000000, state_path="$d/countme", lock_path="$d/lock",
               sender=lambda p: c.send(p, host="127.0.0.1", port=$port, https=False), euid=0)
print("countme:", r)
PY
        else
            env LUX_COUNTME_NOW=1795000000 LUX_COUNTME_STATE="$d/countme" LUX_COUNTME_LOCK="$d/lock" \
                LUX_COUNTME_HOST=127.0.0.1 LUX_COUNTME_PORT=$port LUX_COUNTME_HTTP=1 unshare -r "$LSL" send > "$d/out" 2>&1
        fi
        kill $sp 2>/dev/null; wait $sp 2>/dev/null
    done
    local a b
    a="$(cat "$T/py-$name/out") $(cat "$T/py-$name/countme" 2>/dev/null)"
    b="$(cat "$T/lsl-$name/out") $(cat "$T/lsl-$name/countme" 2>/dev/null)"
    if [[ $a == "$b" ]] && { [[ ! -e $T/py-$name/req && ! -e $T/lsl-$name/req ]] || cmp -s "$T/py-$name/req" "$T/lsl-$name/req"; }; then
        echo "ok   $name"
    else
        fails=$((fails+1)); echo "=== ROZDIL: $name"; echo "  py:  $a"; echo "  lsl: $b"
    fi
}
case_ "odeslano" 200
case_ "server 500" 500
case_ "presmerovani" 302
case_ "uz tento tyden" 200 '{"since": 1790000000, "last_week": "2026-W47"}'
case_ "minuly tyden" 200 '{"since": 1790000000, "last_week": "2026-W46"}'
case_ "prvni tyden instalace" 200 '{"since": 1794900000, "last_week": null}'
case_ "stara instalace" 200 '{"since": 1700000000, "last_week": "2026-W01"}'
case_ "rozbity stav" 200 'nesmysl'
case_ "since z budoucnosti" 200 '{"since": 1999999999, "last_week": null}'
for l in en_US.UTF-8 cs_CZ.UTF-8 de_DE.UTF-8; do
    n=$((n+1))
    if diff <(LANG=$l /usr/lib/lux/lux_countme.py status) <(LANG=$l "$LSL" status) >/dev/null; then echo "ok   status $l"
    else fails=$((fails+1)); echo "=== ROZDIL: status $l"; fi
done
echo "shoda $((n-fails))/$n"
[[ $fails == 0 ]]
