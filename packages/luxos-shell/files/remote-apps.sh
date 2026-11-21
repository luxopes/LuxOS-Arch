# LuxOS - okna aplikaci z jineho pocitace: "ssh -X pocitac aplikace" jako na X11 (bash, lsh, zsh).
#
# Jen v interaktivnim shellu relace na Waylandu; skripty dal volaji /usr/bin/ssh beze zmeny.
# Ma-li druhy pocitac waypipe, spusti se "waypipe ssh ..." (okno pres Wayland, komprese, rychlejsi
# nez X11), jinak obycejne preposilani X11 pres XWayland. Zda waypipe ma, zjisti poprve kratke
# spojeni navic; vysledek se pamatuje v $XDG_RUNTIME_DIR/luxos-ssh. Sdilene spojeni (ControlMaster)
# schvalne ne: Ctrl+C v terminalu by aplikaci nezavrel, jeji okno by dal drzel hlavni proces ssh.
# Vypnuti: LUXOS_SSH_WAYPIPE=0 v ~/.config/luxos/shell.conf, jednorazove "command ssh ...".

ssh() {
    local a c i n w x=0 host="" arg="" dir key probe
    local -a opts nox cmd
    if [[ ${LUXOS_SSH_WAYPIPE:-1} == 0 || -z ${WAYLAND_DISPLAY-} || -z ${XDG_RUNTIME_DIR-} ]] ||
        ! command -v waypipe >/dev/null; then
        command ssh "$@"
        return
    fi
    # rozbor jako getopt v ssh: prvni slovo, ktere neni volba, je pocitac, za nim prikaz;
    # nox = tytez volby bez -X/-Y
    while (($#)); do
        a=$1
        shift
        if [[ -n $arg ]]; then
            opts+=("$a") nox+=("$a")
            arg=""
        elif [[ $a == -- ]]; then
            host=${1-}
            (($#)) && shift
            break
        elif [[ $a == -?* ]]; then
            opts+=("$a")
            w=-
            n=${#a}
            for ((i = 1; i < n; i++)); do
                c=${a:$i:1}
                case $c in
                    X | Y) x=1; continue ;;
                    x) x=0 ;;
                    # preposilani portu, sdilene spojeni a zvlastni rezimy: beze zmeny
                    [NfGVMsOWSLRDQ]) command ssh "${opts[@]}" "$@"; return ;;
                    [BbcEeFIiJlmoPpw])
                        ((i == n - 1)) && arg=1
                        w+=${a:$i}
                        break ;;
                esac
                w+=$c
            done
            [[ $w != - ]] && nox+=("$w")
        else
            host=$a
            break
        fi
    done
    cmd=("$@")
    if ((!x)) || [[ -z $host ]]; then
        command ssh "${opts[@]}" ${host:+"$host"} "${cmd[@]}"
        return
    fi

    dir=$XDG_RUNTIME_DIR/luxos-ssh
    mkdir -p -m 700 "$dir" || { command ssh "${opts[@]}" "$host" "${cmd[@]}"; return; }
    # X11 jde jen do XWayland teto relace, okna Waylandu z nej videt nejsou: duverive jako -Y. Neduveryhodny
    # klient nema XKB (po prepnuti rozlozeni pise spatna pismena) a cast schranky. XWayland z wlroots je bez
    # cookie a ssh by pri kazdem spojeni hlasilo "No xauth data"; nahodne cookie v soukromem souboru staci,
    # XWayland bez autorizace ho nekontroluje. Vlastni XAUTHORITY s cookie pro DISPLAY zustava.
    local xa=${XAUTHORITY:-$HOME/.Xauthority}
    local -a xo
    if [[ -n ${DISPLAY-} ]]; then
        xo=(-o ForwardX11Trusted=yes)
        if [[ -z $(xauth list "$DISPLAY" 2>/dev/null) ]]; then
            xa=$dir/xauth
            [[ -s $xa ]] || xauth -q -f "$xa" add "$DISPLAY" MIT-MAGIC-COOKIE-1 "$(mcookie)" 2>/dev/null
        fi
    fi
    key=$(command ssh -G "${opts[@]}" "$host" 2>/dev/null | awk '$1 == "user" {u = $2} $1 == "hostname" {h = $2}
        $1 == "port" {p = $2} END {print u "@" h ":" p}' | tr -c 'A-Za-z0-9@:.\n-' _)
    probe=""
    [[ -n $key && -r $dir/remote-$key ]] && probe=$(<"$dir/remote-$key")
    # "bez waypipe" plati 10 minut (mohl ho mezitim doinstalovat), "s waypipe" do odhlaseni
    if [[ $probe != *waypipe* && -z $(find "$dir/remote-$key" -mmin -10 2>/dev/null) ]]; then
        # prompty hesla a klice jdou na /dev/tty; chyby spojeni ukaze az skutecny prikaz nize
        probe=$(XAUTHORITY=$xa command ssh -o ConnectTimeout=15 -o LogLevel=ERROR \
            "${opts[@]}" "${xo[@]}" -T "$host" \
            "sh -c 'command -v waypipe >/dev/null && echo waypipe; test -n \"\$DISPLAY\" && echo x11; :'" \
            2>/dev/null </dev/null) &&
            [[ -n $key ]] && printf '%s\n' "$probe" >"$dir/remote-$key"
    fi
    if [[ $probe != *waypipe* ]]; then
        XAUTHORITY=$xa command ssh "${opts[@]}" "${xo[@]}" "$host" "${cmd[@]}"
        return
    fi
    # bez povoleneho X11 na druhem pocitaci -X/-Y pryc, jinak by ssh u kazdeho okna hlasilo
    # "X11 forwarding request failed"; s nim zustava pro aplikace jen pro X11
    [[ $probe == *x11* ]] || opts=("${nox[@]}") xo=()
    XAUTHORITY=$xa waypipe ssh "${opts[@]}" "${xo[@]}" "$host" "${cmd[@]}"
    a=$?
    # 127: waypipe (nebo aplikace) na druhem pocitaci neni - priste zjistit znovu
    ((a == 127)) && rm -f "$dir/remote-$key"
    return "$a"
}
