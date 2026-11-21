#!/bin/bash
# "ssh -X" mezi dvema VM nahledu Waylandu (luxos-shell remote-apps.sh): VM A v relaci na Waylandu spusti
# v Terminalu "ssh -X luxos@vm-b gtk3-demo", okno se musi objevit na A, psani a zavreni (Super+Q) funguje.
# Poprve pres waypipe (B ho ma), pak bez waypipe na B pres XWayland (B povoli X11Forwarding).
#
#   scripts/wl-preview/remote-apps.sh [ADRESAR_VM]     (vychozi out/vm-wayland-preview), vysledky v out/wl-remote
#   LUXOS_EXTRA_PKGS="out/single/luxcomp-*.pkg.tar.zst ..." scripts/wl-preview/remote-apps.sh   novejsi baliky do obou VM
#
# Obe VM bez okna, 2,5 GB RAM pod stropem 3 GB, mezi sebou soukroma sit (UDP soket QEMU, 10.77.0.0/24).
# Nove soubory remote-apps.sh a aliases.sh z pracovni kopie se do obou VM nahraji (obraz muze byt starsi).
# waypipe na B (a wl-clipboard na A pro kontrolu schranky) instaluje lux z internetu, kdyz v obrazu chybi.
set -uo pipefail
here=$(dirname "$(readlink -f "$0")")
repo=$(readlink -f "$here/../..")
img=$(readlink -f "${1:-$repo/out/vm-wayland-preview}")
out=$repo/out/wl-remote
[[ -f $img/base.qcow2 ]] || { echo "no preview image in $img (scripts/wl-preview/build-image.sh)" >&2; exit 2; }
rm -rf "$out" && mkdir -p "$out/a" "$out/b"
ok=0 bad=0
check() {
    local what=$1; shift
    if "$@"; then echo "OK   $what"; ok=$((ok + 1)); else echo "FAIL $what"; bad=$((bad + 1)); fi
}
vm() { local n=$1; shift; LUXOS_VM_DIR=$out/$n timeout 300 python3 "$repo/scripts/vmctl.py" "$@"; }
export -f vm
export out repo
in_a() { vm a exec "$1" 2>>"$out/a/exec.log"; }
in_b() { vm b exec "$1" 2>>"$out/b/exec.log"; }
shot() { vm a shot "$out/$1.png" >/dev/null && echo "shot $out/$1.png"; }
wait_for() {  # wait_for SEKUND VM PRIKAZ
    local end=$((SECONDS + $1))
    while ((SECONDS < end)); do
        vm "$2" exec "$3" >/dev/null 2>&1 && return 0
        kill -0 $pa $pb 2>/dev/null || return 1
        sleep 0.5
    done
    return 1
}
start() {  # start a|b
    local n=$1 l=41001 r=41002 mac=52:54:00:77:00:01
    [[ $n == b ]] && l=41002 r=41001 mac=52:54:00:77:00:02
    qemu-img create -q -f qcow2 -F qcow2 -b "$img/base.qcow2" "$out/$n/disk.qcow2"
    systemd-run --user --scope -q -p MemoryMax=3G -p MemorySwapMax=0 -- \
        qemu-system-x86_64 -name "wl-remote-$n" -enable-kvm -machine q35 -cpu host -smp 2 -m 2560M \
        -kernel "$img/vmlinuz" -initrd "$img/initramfs.img" -append "root=/dev/vda rw quiet loglevel=3" \
        -drive "file=$out/$n/disk.qcow2,if=virtio,format=qcow2" -vga std -display none \
        -netdev user,id=n0 -device virtio-net-pci,netdev=n0,romfile= \
        -netdev "socket,id=n1,udp=127.0.0.1:$r,localaddr=127.0.0.1:$l" -device "virtio-net-pci,netdev=n1,mac=$mac,romfile=" \
        -device qemu-xhci -device usb-tablet -device virtio-serial \
        -chardev "socket,path=$out/$n/qga.sock,server=on,wait=off,id=qga0" \
        -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0 \
        -qmp "unix:$out/$n/qmp.sock,server=on,wait=off" >"$out/$n/qemu.log" 2>&1 &
    echo $!
}
pa=$(start a) pb=$(start b)
# KEEP=1: VM po testu nechat bezet (ladeni), vypnout pak "LUXOS_VM_DIR=out/wl-remote/a scripts/vmctl.py quit"
[[ ${KEEP-} == 1 ]] || trap 'vm a quit >/dev/null 2>&1; vm b quit >/dev/null 2>&1; wait $pa $pb 2>/dev/null' EXIT
check "VM A up" wait_for 300 a 'pgrep -u greeter -x luxos-greeter'
check "VM B up" wait_for 300 b 'true'

if [[ -n ${LUXOS_EXTRA_PKGS-} ]]; then
    files=()
    for f in $LUXOS_EXTRA_PKGS; do
        vm a put "$f" "/root/${f##*/}" >/dev/null && vm b put "$f" "/root/${f##*/}" >/dev/null
        files+=("/root/${f##*/}")
    done
    in_b "yes | lux install -y ${files[*]}" >/dev/null   # B jen jako server, restart netreba
    # restart greetd hned po startu obcas skonci na textove konzoli (DRM jeste drzi stary greeter): restart VM
    in_a "yes | lux install -y ${files[*]}; systemctl --no-block reboot" >/dev/null
    sleep 10
    check "extra packages installed" wait_for 300 a 'pgrep -u greeter -x luxos-greeter'
    sleep 4
fi

# sit, sshd na B, klic A -> B, nove soubory luxos-shell
for n in a b; do
    vm $n put "$repo/packages/luxos-shell/files/remote-apps.sh" /usr/share/luxos/shell/remote-apps.sh >/dev/null
    vm $n put "$repo/packages/luxos-shell/files/aliases.sh" /usr/share/luxos/shell/aliases.sh >/dev/null
done
in_a 'chmod 644 /usr/share/luxos/shell/*.sh; echo "10.77.0.2 vm-b" >>/etc/hosts' >/dev/null
in_b 'chmod 644 /usr/share/luxos/shell/*.sh; systemctl enable --now sshd; hostnamectl hostname vm-b' >/dev/null
# NetworkManager pri startu prevezme a vyprazdni enp0s3, kdyz jeste nebezel: adresy nastavovat znovu, dokud
# A nevidi sshd na B (ten po prvnim startu chvili generuje klice)
link_up() {
    local end=$((SECONDS + 180)) l='nmcli dev set enp0s3 managed no 2>/dev/null; ip link set enp0s3 up; ip addr replace'
    while ((SECONDS < end)); do
        in_a "$l 10.77.0.1/24 dev enp0s3" >/dev/null
        in_b "$l 10.77.0.2/24 dev enp0s3" >/dev/null
        vm a exec 'ssh-keyscan -T 2 vm-b 2>/dev/null | grep -q ed25519' >/dev/null 2>&1 && return 0
        sleep 2
    done
    return 1
}
check "sshd on B reachable from A" link_up
key=$(in_a 'sudo -u luxos sh -c "mkdir -p -m 700 ~/.ssh; ssh-keygen -q -t ed25519 -N \"\" -f ~/.ssh/id_ed25519 >/dev/null; cat ~/.ssh/id_ed25519.pub"' | grep ssh-ed25519)
in_b "sudo -u luxos sh -c 'mkdir -p -m 700 ~/.ssh; echo \"$key\" >>~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys'" >/dev/null
in_a 'sudo -u luxos sh -c "ssh-keyscan vm-b >>~/.ssh/known_hosts 2>/dev/null"' >/dev/null
check "key login A -> B" bash -c "[[ \$(vm a exec 'sudo -u luxos ssh -o BatchMode=yes vm-b echo ok' 2>/dev/null) == *ok* ]]"
# stara databaze baliku v obrazu: instalace selze ("transaction preparation failed"), pak nejdriv lux update
get='get() { command -v "$1" >/dev/null || yes | lux install -y "$2" || { lux update -y; yes | lux install -y "$2"; }; }'
in_b "$get; get waypipe waypipe" >/dev/null
in_a "$get; get waypipe waypipe; get wl-paste wl-clipboard" >/dev/null
check "waypipe on A and B" bash -c "vm a exec 'command -v waypipe' >/dev/null && vm b exec 'command -v waypipe' >/dev/null"

# prihlaseni do relace na Waylandu, Terminal, rozlozeni us (Alt+Shift)
vm a keys luxos >/dev/null; vm a key ret >/dev/null
check "Wayland session on A" wait_for 120 a 'systemctl --machine=luxos@ --user is-active -q luxos-bar.service'
sleep 8
in_a 'pkill -u luxos -f luxos-tour; pkill -u luxos -f luxos-welcome; pkill -u luxos -f luxos-whats-new' >/dev/null
vm a key ctrl-alt-t >/dev/null; sleep 5
vm a key alt-shift >/dev/null; sleep 1

run_case() {  # run_case NAZEV CESTA(waypipe|x11)
    local name=$1 want=$2 t0 t1
    vm a keys "clear; ssh -X luxos@vm-b gtk3-demo --run=entry_buffer" >/dev/null
    t0=$(date +%s%N); vm a key ret >/dev/null
    check "$name: app runs on B" wait_for 60 b 'pgrep -x gtk3-demo'
    t1=$(date +%s%N)
    echo "$name: app_on_B_ms=$(((t1 - t0) / 1000000))" | tee -a "$out/result.txt"
    if [[ $want == waypipe ]]; then
        check "$name: through waypipe" bash -c "vm a exec 'pgrep -u luxos -f \"^waypipe ssh\"' >/dev/null 2>&1"
    else
        check "$name: through X11 (XWayland on A)" bash -c "vm a exec 'pgrep -x Xwayland' >/dev/null 2>&1 &&
            ! vm a exec 'pgrep -u luxos -f \"^waypipe ssh\"' >/dev/null 2>&1"
    fi
    sleep 6
    shot "$name-1-window"
    in_a 'pkill -u luxos wl-copy; sudo -u luxos XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 sh -c "printf fromA | wl-copy >/dev/null 2>&1 &"' >/dev/null
    vm a keys "typed@b-1 " >/dev/null; vm a key ctrl-v >/dev/null; sleep 1
    vm a key ctrl-a >/dev/null; vm a key ctrl-c >/dev/null; sleep 1
    shot "$name-2-typed"
    check "$name: typing and paste A -> B, copy B -> A" bash -c "[[ \$(vm a exec 'sudo -u luxos XDG_RUNTIME_DIR=/run/user/1000 \
        WAYLAND_DISPLAY=wayland-0 timeout 5 wl-paste -n' 2>/dev/null) == 'typed@b-1 fromA' ]]"
    vm a key meta_l-q >/dev/null; sleep 2      # dialog Entry Buffer
    vm a key meta_l-q >/dev/null               # hlavni okno
    check "$name: closed with Super+Q, app gone on B" bash -c "sleep 3; ! vm b exec 'pgrep -x gtk3-demo' >/dev/null 2>&1"
    shot "$name-3-closed"
}
run_case waypipe waypipe

# B bez waypipe, s X11Forwarding (na LuxOS je vychozi vypnute)
in_b 'yes | lux remove -y waypipe; echo "X11Forwarding yes" >/etc/ssh/sshd_config.d/50-x11.conf; systemctl reload sshd' >/dev/null
in_a 'rm -f /run/user/1000/luxos-ssh/remote-*' >/dev/null
run_case x11 x11

echo "ok=$ok bad=$bad" | tee -a "$out/result.txt"
((bad == 0))
