#!/bin/bash
# LuxOS - laborator AD: sit klienta (druha karta 10.77.0.10, DNS = DC). Bezi UVNITR VM "client".
set -euo pipefail
[[ $EUID == 0 ]] || { echo "run as root inside the client VM" >&2; exit 1; }
ifname=$(ip -o link | awk -F': ' '/52:54:00:77:00:10/ {print $2}')
nmcli con delete lab 2>/dev/null || true
nmcli con add type ethernet ifname "$ifname" con-name lab ipv4.method manual ipv4.addresses 10.77.0.10/24 \
    ipv4.dns 10.77.0.1 ipv4.dns-search luxtest.lan ipv4.dns-priority -10 ipv6.method disabled
nmcli con up lab
hostnamectl set-hostname luxpc1
# mistni ucet "jan" pro test kolize jmen (R4), heslo jen pro laborator
id jan &>/dev/null || { useradd -m -s /usr/bin/lsh -c "Jan (local)" jan; echo 'jan:Local-Jan-2026' | chpasswd; }
getent hosts dc1.luxtest.lan
