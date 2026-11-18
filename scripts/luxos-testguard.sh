# LuxOS - testy GUI v shellu nikdy na skutecne obrazovce a ve skutecne relaci (stejne jako
# scripts/luxos_testguard.py). Nacita se z testu (hleda se nahoru od skriptu): . .../scripts/luxos-testguard.sh
# DISPLAY, ktery neni Xvfb/Xephyr/Xvnc tohoto uzivatele, se nahradi vlastnim Xvfb (ukonci se pri
# skonceni skriptu), bez Xvfb se odebere; sbernice, XAUTHORITY, HOME a XDG_* skutecne relace se nahradi
# docasnymi. Skutecnou obrazovku nelze vynutit.
# Systemova sbernice: DBUS_SYSTEM_BUS_ADDRESS vzdy miri na neexistujici soket; vlastni falesnou systemovou
# sbernici preda test jen schvalenou promennou LUXOS_TEST_SYSTEM_BUS (nebo ji nastavi az pro podproces).
# Kamery: LUXOS_VIDEO_DEV_DIR miri na prazdnou docasnou slozku (aplikace hledaji video* tam, ne v /dev).
_luxos_tg_private() {  # _luxos_tg_private :N
    local num=${1#:} pid argv
    num=${num%%.*}
    [[ $1 == :* && $num =~ ^[0-9]+$ ]] || return 1
    for pid in /proc/[0-9]*; do
        [[ -O $pid ]] || continue
        argv=$(tr '\0' '\n' <"$pid/cmdline" 2>/dev/null) || continue
        case ${argv%%$'\n'*} in
            *Xvfb | *Xephyr | *Xvnc) grep -qx ":$num" <<<"$argv" && return 0 ;;
        esac
    done
    return 1
}
_luxos_tg_real() {  # cesta ve skutecnem domove nebo /run/user/UID?
    local p
    [[ -n ${1-} ]] || return 1
    p=$(realpath -m -- "$1")
    local home
    home=$(getent passwd "$(id -u)" | cut -d: -f6)
    [[ $p == "$home" || $p == "$home"/* || $p == /run/user/$(id -u) || $p == /run/user/$(id -u)/* ]]
}
luxos_tg_tmp=$(mktemp -d -t luxos-testguard-XXXXXX)
chmod 700 "$luxos_tg_tmp"
luxos_tg_xvfb=
_luxos_tg_cleanup() {
    [[ -n $luxos_tg_xvfb ]] && kill "$luxos_tg_xvfb" 2>/dev/null
    [[ -n ${luxos_tg_buspid-} ]] && kill "$luxos_tg_buspid" 2>/dev/null
    rm -rf "$luxos_tg_tmp"
}
trap _luxos_tg_cleanup EXIT
if [[ -n ${DISPLAY-} ]] && ! _luxos_tg_private "$DISPLAY"; then
    unset XAUTHORITY
    luxos_tg_n=
    for n in $(seq 90 199); do
        [[ -e /tmp/.X11-unix/X$n || -e /tmp/.X$n-lock ]] || { luxos_tg_n=$n; break; }
    done
    if [[ -n $luxos_tg_n ]] && command -v Xvfb >/dev/null; then
        # Xvfb skonci i se skriptem, ktery si pozdeji nastavi vlastni "trap EXIT" (pdeathsig)
        if setpriv --pdeathsig TERM true 2>/dev/null; then
            setpriv --pdeathsig TERM Xvfb ":$luxos_tg_n" -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
        else
            Xvfb ":$luxos_tg_n" -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
        fi
        luxos_tg_xvfb=$!
        for _ in $(seq 100); do [[ -e /tmp/.X11-unix/X$luxos_tg_n ]] && break; sleep 0.05; done
        export DISPLAY=:$luxos_tg_n
    else
        unset DISPLAY
    fi
fi
if _luxos_tg_real "${XDG_RUNTIME_DIR-}"; then
    mkdir -p "$luxos_tg_tmp/run"; chmod 700 "$luxos_tg_tmp/run"
    export XDG_RUNTIME_DIR=$luxos_tg_tmp/run
fi
if _luxos_tg_real "${HOME-}"; then
    mkdir -p "$luxos_tg_tmp/home"
    export HOME=$luxos_tg_tmp/home
fi
for _v in XDG_CONFIG_HOME XDG_DATA_HOME XDG_CACHE_HOME XDG_STATE_HOME; do
    _luxos_tg_real "${!_v-}" && unset "$_v"
done
unset _v
# sbernice skutecne relace -> vlastni (az s docasnym HOME; ukonci se pri skonceni skriptu)
luxos_tg_buspid=
if [[ ${DBUS_SESSION_BUS_ADDRESS-} == unix:path=/run/user/$(id -u)/bus* ]]; then
    unset DBUS_SESSION_BUS_ADDRESS
    if command -v dbus-daemon >/dev/null; then
        # bez --fork a s pdeathsig (jako Xvfb): skonci se skriptem i kdyz si test nastavi vlastni
        # "trap EXIT" (drive dbus-daemon --fork po takovem testu zustaval bezet)
        luxos_tg_pd=()
        setpriv --pdeathsig TERM true 2>/dev/null && luxos_tg_pd=(setpriv --pdeathsig TERM)
        "${luxos_tg_pd[@]}" dbus-daemon --session --nofork --print-address=3 3>"$luxos_tg_tmp/bus" \
            >/dev/null 2>&1 </dev/null &
        luxos_tg_buspid=$!
        luxos_tg_bus=
        for _ in $(seq 100); do
            IFS= read -r luxos_tg_bus <"$luxos_tg_tmp/bus" 2>/dev/null
            [[ -n $luxos_tg_bus ]] && break
            sleep 0.05
        done
        [[ -n ${luxos_tg_bus-} ]] && export DBUS_SESSION_BUS_ADDRESS=$luxos_tg_bus
    fi
fi
# systemova sbernice: mrtvy soket, jen schvalena falesna sbernice testu (ne skutecny soket) projde
_luxos_tg_real_sysbus() {  # adresa miri na skutecnou systemovou sbernici (prazdna = vychozi = skutecna)?
    local a=${1-} part p
    [[ -n $a ]] || return 0
    IFS=';' read -ra _luxos_tg_parts <<<"$a"
    for part in "${_luxos_tg_parts[@]}"; do
        case $part in
            unix:*path=*)
                p=${part#*path=}; p=${p%%,*}
                [[ $p == /run/dbus/system_bus_socket || $p == /var/run/dbus/system_bus_socket ||
                   $(realpath -m -- "$p") == /run/dbus/system_bus_socket ]] && return 0 ;;
            unix:*) ;;
            *) return 0 ;;
        esac
    done
    return 1
}
if [[ -n ${LUXOS_TEST_SYSTEM_BUS-} ]] && ! _luxos_tg_real_sysbus "$LUXOS_TEST_SYSTEM_BUS"; then
    export DBUS_SYSTEM_BUS_ADDRESS=$LUXOS_TEST_SYSTEM_BUS
else
    unset LUXOS_TEST_SYSTEM_BUS
    export DBUS_SYSTEM_BUS_ADDRESS=unix:path=$luxos_tg_tmp/no-system-bus
fi
# kamery: prazdna slozka misto /dev
mkdir -p "$luxos_tg_tmp/no-cameras"
export LUXOS_VIDEO_DEV_DIR=$luxos_tg_tmp/no-cameras
