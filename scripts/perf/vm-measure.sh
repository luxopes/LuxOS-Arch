#!/bin/bash
# LuxOS - mereni rychlosti ve VM: start do prihlasovaci obrazovky, prihlaseni, klidova zatez.
#   LUXOS_VM_DIR=out/vmperf scripts/perf/vm-measure.sh OUTDIR [heslo]
# VM musi bezet a byt cerstve nastartovana (greeter, nikdo neprihlaseny). Vysledky do OUTDIR.
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")/../.."
out=${1:?OUTDIR}; pass=${2:-luxos}
mkdir -p "$out"
vm() { python3 scripts/vmctl.py "$@"; }

until vm ping >/dev/null 2>&1; do sleep 1; done
# greeter + dokonceni startu
until vm exec 'systemctl is-system-running --wait >/dev/null 2>&1; pgrep -f "python3 /usr/bin/luxos-greeter" >/dev/null || pgrep -x lightdm-gtk-gre >/dev/null' >/dev/null 2>&1; do sleep 1; done
sleep 8
vm put scripts/perf/login-probe.py /root/login-probe.py >/dev/null
vm put scripts/perf/idle-probe.py /root/idle-probe.py >/dev/null
vm exec 'systemd-analyze; echo; systemd-analyze blame | head -25; echo; systemd-analyze critical-chain graphical.target;
  echo; echo "greeter process start (s since boot):"; for p in $(pgrep -f "python3 /usr/bin/luxos-greeter"; pgrep -x lightdm-gtk-gre); do
  awk -v hz=$(getconf CLK_TCK) "{print \$22/hz}" /proc/$p/stat; done;
  echo "lightdm.service start (s since boot): $(awk "BEGIN {print $(systemctl show lightdm.service -p ExecMainStartTimestampMonotonic --value) / 1e6}")";
  grep -E "Launching X|Greeter connected" /var/log/lightdm/lightdm.log | head -3;
  journalctl -b -o short-monotonic --no-pager -t lightdm 2>/dev/null | head -5;
  grep -h "ready in" /var/lib/lightdm/.cache/luxos-greeter/*.log /var/log/lightdm/*greeter*.log 2>/dev/null | tail -3' >"$out/boot.txt" 2>&1

# prihlaseni: sonda bezi 40 s, heslo + Enter
vm exec 'setsid nohup python3 /root/login-probe.py /root/login.json lux 40 >/root/login.txt 2>&1 &' >/dev/null
sleep 1
vm key ret; sleep 1.5
vm keys "$pass"
vm key ret
vm exec 'cat /proc/uptime' | awk '{print "enter_uptime", $1}' >"$out/enter.txt"
sleep 42
vm exec 'cat /root/login.txt' >"$out/login.txt"
vm exec 'cat /root/login.json' >"$out/login.json"
vm shot "$out/desktop.png" >/dev/null
# klid: 60 s po ustaleni
sleep 20
vm exec 'python3 /root/idle-probe.py lux 60' >"$out/idle.txt"
echo "done: $out"
