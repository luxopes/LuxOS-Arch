#!/bin/bash
# LuxOS Sandbox - test pomocnika (pacstrap, vlastnictvi, odkaz /dev/sandbox, negativni pripady)
# v kontejneru jako root (bez pkexec):
#   podman run --rm --privileged -v packages/luxos-sandbox:/src:ro,z -v packages/lux-engine:/lux-engine:ro,z -v packages/luxos-sandbox/tests/helper-container-test.sh:/t.sh:ro,z luxos-builder bash /t.sh
set -u
F=/src/files
pacman -Sy --noconfirm --needed bubblewrap arch-install-scripts python passt iproute2 >/dev/null 2>&1 || echo "pacman deps failed"
install -Dm755 $F/luxos-sandbox /usr/bin/luxos-sandbox
install -Dm755 $F/luxos-sandbox-helper /usr/lib/luxos/sandbox/luxos-sandbox-helper
install -Dm644 $F/luxos_sandbox_seccomp.py /usr/lib/luxos/python/luxos_sandbox_seccomp.py
install -Dm644 $F/lux.conf /usr/share/luxos/sandbox/lux.conf
# lux-config a seznam zrcadel z lux-engine; v kontejneru (Arch) jsou nastroje jadra lux odkazy na pacman Archu
install -Dm755 /lux-engine/lux_config.py /usr/lib/lux/lux_config.py || echo "mount packages/lux-engine at /lux-engine"
[[ -s /etc/lux/mirrorlist ]] || { mkdir -p /etc/lux; grep -h '^Server' /etc/pacman.d/mirrorlist | sed 's/^Server *= *//' >/etc/lux/mirrorlist; }
mkdir -p /usr/lib/lux/alpm/bin
for t in "" -key -conf; do ln -sf /usr/bin/pacman$t /usr/lib/lux/alpm/bin/lux-engine$t; done
install -Dm644 $F/luxos-sandbox.tmpfiles /usr/lib/tmpfiles.d/luxos-sandbox.conf
systemd-tmpfiles --create /usr/lib/tmpfiles.d/luxos-sandbox.conf
id tester >/dev/null 2>&1 || useradd -m -u 1500 tester
H=/usr/lib/luxos/sandbox/luxos-sandbox-helper
echo "== negative: no PKEXEC_UID";            env -u PKEXEC_UID $H create; echo "rc=$?"
echo "== negative: PKEXEC_UID=0";             PKEXEC_UID=0 $H create; echo "rc=$?"
echo "== negative: system user uid 33";       PKEXEC_UID=33 $H create; echo "rc=$?"
echo "== negative: extra argument";           PKEXEC_UID=1500 $H create /etc; echo "rc=$?"
echo "== negative: as non-root";              su tester -c "PKEXEC_UID=1500 $H create"; echo "rc=$?"
echo "== negative: /var/lib/luxos/sandbox replaced by symlink"
mv /var/lib/luxos/sandbox /var/lib/luxos/sandbox.real; ln -s /tmp /var/lib/luxos/sandbox
PKEXEC_UID=1500 $H create; echo "rc=$?"
rm /var/lib/luxos/sandbox; mv /var/lib/luxos/sandbox.real /var/lib/luxos/sandbox
echo "== negative: group-writable base";      chmod 775 /var/lib/luxos/sandbox; PKEXEC_UID=1500 $H create; echo "rc=$?"; chmod 755 /var/lib/luxos/sandbox
echo "== create"
time (PKEXEC_UID=1500 $H create 2>&1 | tail -4); echo "rc=${PIPESTATUS[0]}"
ls -la /var/lib/luxos/sandbox/
ls -la /dev/sandbox/ 2>&1; cat /etc/tmpfiles.d/luxos-sandbox-tester.conf
R=/var/lib/luxos/sandbox/tester
echo "files not owned by tester: $(find $R ! -user tester | wc -l)"
echo "setuid/setgid files: $(find $R -perm /6000 | wc -l)"
echo "device nodes: $(find $R -type b -o -type c | wc -l)"
readlink $R/etc/resolv.conf; grep sandbox $R/etc/passwd; grep -c '^\[' $R/etc/pacman.conf; grep -n DownloadUser $R/etc/pacman.conf; grep -c '^#@' $R/etc/pacman.conf; grep -c '^Server' $R/etc/pacman.conf
du -sh $R
echo "== create again (must refuse)";         PKEXEC_UID=1500 $H create; echo "rc=$?"
echo "== CLI as tester"
su tester -c 'luxos-sandbox status; luxos-sandbox run /bin/sh -c "id; cat /etc/os-release | head -1; ls /home"' 2>&1
echo "== install app as tester (pacman in sandbox, fake root, network via pasta)"
su tester -c 'luxos-sandbox install cowsay 2>&1 | tail -6; echo "install rc=${PIPESTATUS[0]}"; luxos-sandbox run cowsay hi; luxos-sandbox status; luxos-sandbox remove-app cowsay 2>&1 | tail -2; luxos-sandbox status | tail -1'
echo "files not owned by tester after install: $(find $R ! -user tester | wc -l); setuid: $(find $R -perm /6000 | wc -l)"
echo "== reset"
PKEXEC_UID=1500 $H reset >/dev/null 2>&1; echo "rc=$?"; ls -la /var/lib/luxos/sandbox/
echo "== destroy"
PKEXEC_UID=1500 $H destroy; echo "rc=$?"; ls -la /var/lib/luxos/sandbox/ /dev/sandbox/; ls /etc/tmpfiles.d/
