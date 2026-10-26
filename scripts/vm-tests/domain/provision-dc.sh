#!/bin/bash
# LuxOS - laborator AD: z VM (LuxOS) udela radic domeny Samba AD LUXTEST.LAN. Bezi UVNITR VM "dc"
# jako root (vmctl.py put + exec), nikdy na hostiteli.
#
#   provision-dc.sh              instalace samba, provision, uzivatele, skupiny, sdileni, tiskarna, GPO
#
# Vysledek (hesla jen pro laborator):
#   domena luxtest.lan / LUXTEST, DC dc1.luxtest.lan 10.77.0.1 (DNS SAMBA_INTERNAL)
#   Administrator / Lab-Admin-2026    jan, eva / Lab-User-2026    itadmin (LuxOS Admins) / Lab-It-2026
#   joiner (smi jen pridavat pocitace do OU=LuxOS) / Lab-Join-2026     locked (ucet vypnuty v domene)
#   expired (heslo musi zmenit pri prihlaseni) / Lab-User-2026   denied (skupina "No Local Logon")
#   skupiny: "LuxOS Admins" (itadmin), "Účtárna" (eva), "No Local Logon" (denied)
#   sdileni \\dc1\data (cteni/zapis pro Domain Users), tiskarna \\dc1\pdf (cups-pdf)
set -euo pipefail
[[ $EUID == 0 ]] || { echo "run as root inside the DC VM" >&2; exit 1; }
[[ -f /etc/luxos-ad-lab ]] || [[ ${LUXOS_AD_LAB_FORCE-} == 1 ]] || {
    echo "Refusing: /etc/luxos-ad-lab missing (this script turns the machine into a domain controller)" >&2; exit 1; }

REALM=LUXTEST.LAN DOMAIN=LUXTEST DCIP=10.77.0.1
ADMINPASS=Lab-Admin-2026 USERPASS=Lab-User-2026

# 1. sit: druha karta = laborator (MAC 52:54:00:77:00:01), staticka adresa
ifname=$(ip -o link | awk -F': ' '/52:54:00:77:00:01/ {print $2}')
nmcli con delete lab 2>/dev/null || true
nmcli con add type ethernet ifname "$ifname" con-name lab ipv4.method manual ipv4.addresses "$DCIP/24" \
    ipv4.dns 127.0.0.1 ipv4.dns-search luxtest.lan ipv6.method disabled
nmcli con up lab
hostnamectl set-hostname dc1.luxtest.lan

# 2. samba (z repozitaru Arch Linuxu pres lux) + krb5
lux install -y --repo samba krb5 cups cups-pdf
systemctl disable --now systemd-resolved 2>/dev/null || true
rm -f /etc/resolv.conf
printf 'search luxtest.lan\nnameserver 127.0.0.1\n' >/etc/resolv.conf

# 3. provision (vymaze predchozi pokus)
systemctl stop samba 2>/dev/null || true
rm -f /etc/samba/smb.conf
rm -rf /var/lib/samba/private/* /var/lib/samba/sysvol/* 2>/dev/null || true
samba-tool domain provision --use-rfc2307 --realm="$REALM" --domain="$DOMAIN" --server-role=dc \
    --dns-backend=SAMBA_INTERNAL --adminpass="$ADMINPASS" --host-ip="$DCIP" \
    --option="dns forwarder = 10.0.2.3" --option="interfaces = lo $ifname" --option="bind interfaces only = yes"
cp /var/lib/samba/private/krb5.conf /etc/krb5.conf
# sdileni a tiskarna v smb.conf
cat >>/etc/samba/smb.conf <<'EOF'

[data]
   path = /srv/data
   read only = no

[pdf]
   path = /var/spool/samba
   printable = yes
   printer name = pdf
EOF
install -d -m 1777 /srv/data /var/spool/samba
echo "LuxOS AD lab share" >/srv/data/README.txt
systemctl enable --now samba.service
for _ in $(seq 30); do samba-tool domain info 127.0.0.1 >/dev/null 2>&1 && break; sleep 2; done

# 4. uzivatele a skupiny
st() { samba-tool "$@"; }
st user create jan "$USERPASS" --given-name=Jan --surname=Novak
st user create eva "$USERPASS" --given-name=Eva --surname=Svobodova
st user create itadmin Lab-It-2026 --given-name=IT --surname=Admin
st user create joiner Lab-Join-2026
st user create locked "$USERPASS"
st user create expired "$USERPASS" --must-change-at-next-login
st user create denied "$USERPASS"
st user disable locked
st group add "LuxOS Admins"
st group add "Účtárna"
st group add "No Local Logon"
st group addmembers "LuxOS Admins" itadmin
st group addmembers "Účtárna" eva
st group addmembers "No Local Logon" denied
st ou create "OU=LuxOS,DC=luxtest,DC=lan"
# joiner smi jen vytvaret pocitace v OU=LuxOS (bez Domain Admins)
st dsacl set --objectdn="OU=LuxOS,DC=luxtest,DC=lan" --action=allow \
    --sddl="(OA;CI;CCDC;bf967a86-0de6-11d0-a285-00aa003049e2;;$(st user show joiner --attributes=objectSid | awk '/objectSid/ {print $2}'))" || true
st user setexpiry joiner --noexpiry
# politika hesel bez zamykani (laborator testuje i zamceni pres "locked")
st domain passwordsettings set --complexity=off --min-pwd-length=8 --account-lockout-threshold=0

# 5. GPO "Deny log on locally" pro skupinu "No Local Logon" (scenar 6)
gpo=$(st gpo create "LuxOS lab deny logon" -U Administrator --password="$ADMINPASS" | awk -F"'" '/GPO/ {print $4}' | tail -1)
if [[ -n $gpo ]]; then
    st gpo setlink "DC=luxtest,DC=lan" "$gpo" -U Administrator --password="$ADMINPASS"
    sid=$(st group show "No Local Logon" --attributes=objectSid | awk '/objectSid/ {print $2}')
    dir=/var/lib/samba/sysvol/luxtest.lan/Policies/$gpo/MACHINE/Microsoft/Windows\ NT/SecEdit
    install -d "$dir"
    printf '[Unicode]\r\nUnicode=yes\r\n[Version]\r\nsignature="$CHICAGO$"\r\nRevision=1\r\n[Privilege Rights]\r\nSeDenyInteractiveLogonRight = *%s\r\n' \
        "$sid" | iconv -f UTF-8 -t UTF-16 >"$dir/GptTmpl.inf"
    st ntacl sysvolreset || true
fi

# 6. tiskarna cups-pdf sdilena pres SMB
systemctl enable --now cups.service
lpadmin -p pdf -E -v cups-pdf:/ -m lsb/usr/cups-pdf/CUPS-PDF_opt.ppd 2>/dev/null || lpadmin -p pdf -E -v cups-pdf:/ -m raw
smbcontrol all reload-config || true

echo "== DC ready: $REALM at $DCIP =="
samba-tool domain info 127.0.0.1
