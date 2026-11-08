#!/bin/bash
# LuxOS Mail - zaznam SKUTECNEHO souhlasu Google na plose vlastnika a slozeni vysledneho videa
# pro overeni aplikace OAuth u Googlu. Spousti VLASTNIK na sve skutecne plose (ne agent, ne v xvfb).
#
#   docs/google-verification/record-consent.sh [--monitor JMENO | --area SxV+X+Y] [--max SEKUNDY]
#                                              [--trim-start SEKUNDY] [--email ADRESA] [--no-countdown]
#
# Co dela:
#   1. zkontroluje, ze automaticky nahrane casti existuji (record-demo.sh) a ze Posta nabizi
#      "Sign in with Google" (Google client ID je dostupne)
#   2. po odpoctu 5 s nahrava obrazovku (ffmpeg x11grab, jen vas monitor, bez zvuku) - nahore v terminalu
#      bezi cas; zastavite libovolnou klavesou v tomto terminalu (nejpozdeji po --max, vychozi 60 s)
#   3. klip vlozi do videa misto zastupne karty (assemble.py): uvod, 1. pridani uctu, 2. VAS ZAZNAM,
#      3. pouziti rozsahu, zaver -> ~/LuxOS-Arch/out/google-verification/luxos-mail-demo-final.mp4
#
# Nic nenahrava na internet - video na YouTube (Neverejne / Unlisted) nahrajete sami.
# --email ADRESA: automaticke casti se nejdriv znovu nahraji s touto adresou (xvfb, falesne servery), aby
#                 adresa ve videu odpovidala vasemu testovacimu uctu (trva ~3 minuty, potrebuje lslc).
set -euo pipefail
here=$(dirname "$(readlink -f "$0")")
repo=$(readlink -f "$here/../..")
out=${LUXOS_GV_OUT:-$HOME/LuxOS-Arch/out/google-verification}
parts=$out/parts
max=60
trim=0
monitor=""
area=""
email=""
countdown=1

while (($#)); do
    case $1 in
        --monitor) monitor=$2; shift 2 ;;
        --area) area=$2; shift 2 ;;
        --max) max=$2; shift 2 ;;
        --trim-start) trim=$2; shift 2 ;;
        --email) email=$2; shift 2 ;;
        --out) out=$2; parts=$out/parts; shift 2 ;;
        --no-countdown) countdown=0; shift ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

die() { echo "record-consent: $*" >&2; exit 1; }
for t in ffmpeg ffprobe xrandr python3 rsvg-convert; do
    command -v "$t" >/dev/null || die "missing $t"
done
[[ -n ${DISPLAY:-} ]] || die "no DISPLAY - run this in a terminal on your LuxOS desktop"
[[ ${XDG_SESSION_TYPE:-x11} != wayland ]] || die "Wayland session: x11grab cannot record it"
[[ $max =~ ^[0-9]+$ && $max -ge 10 && $max -le 90 ]] || die "--max must be 10-90 seconds"
[[ $trim =~ ^[0-9]+([.][0-9]+)?$ ]] || die "--trim-start must be a number of seconds"

mkdir -p "$out/consent"

# ---- 1. automaticke casti -----------------------------------------------------------------------------
if [[ -n $email ]]; then
    echo "==> Re-recording the automated parts with $email (virtual screen, test servers only)"
    "$here/record-demo.sh" --email "$email" --out "$out"
fi
for p in part-a part-g part-b; do
    [[ -f $parts/$p.mp4 ]] || die "missing $parts/$p.mp4 - run docs/google-verification/record-demo.sh first"
done

# ---- kontrola Posty: je "Sign in with Google" dostupne? ---------------------------------------------------
mailbin=$(command -v luxos-mail || true)
if [[ -n $mailbin ]]; then
    if ! "$mailbin" --test-oauth-providers 2>/dev/null | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin)["providers"]["google"]["available"] else 1)'; then
        echo "!  LuxOS Mail on this computer does not offer \"Sign in with Google\" yet (no Google client ID)."
        echo "   Deploy mail-oauth.json with the Google client to luxos.lux-ai.cz (server/mail-oauth/README-ids.md),"
        echo "   or put it in /etc/luxos/mail-oauth.json, then start Mail once (it fetches the IDs at most once a day:"
        echo "   delete ~/.cache/luxos-mail/mail-oauth.json to fetch now). See docs/google-verification/README.md."
        read -rp "   Continue anyway? [y/N] " a
        [[ $a == [yYaA]* ]] || exit 1
    fi
else
    echo "!  luxos-mail is not installed on this computer."
fi

# ---- oblast nahravani: jeden monitor ---------------------------------------------------------------------
if [[ -z $area ]]; then
    # radky "0: +*eDP-1 1920/344x1080/194+0+0  eDP-1"; vychozi je primarni monitor (*)
    line=""
    if [[ -n $monitor ]]; then
        line=$(xrandr --listmonitors | awk -v m="$monitor" '$NF == m')
    else
        line=$(xrandr --listmonitors | awk '$2 ~ /\*/' | head -n1)
        [[ -n $line ]] || line=$(xrandr --listmonitors | sed -n 2p)
    fi
    [[ -n $line ]] || die "monitor not found (xrandr --listmonitors)"
    geo=$(awk '{print $3}' <<<"$line")
    w=${geo%%/*}; rest=${geo#*x}; h=${rest%%/*}
    off=${geo#*+}; x=${off%%+*}; y=${off#*+}
    area="${w}x${h}+${x}+${y}"
fi
[[ $area =~ ^([0-9]+)x([0-9]+)\+([0-9]+)\+([0-9]+)$ ]] || die "bad --area $area (WxH+X+Y)"
w=${BASH_REMATCH[1]}; h=${BASH_REMATCH[2]}; x=${BASH_REMATCH[3]}; y=${BASH_REMATCH[4]}
# x264 + yuv420p potrebuje sude rozmery
w=$((w / 2 * 2)); h=$((h / 2 * 2))

cat <<EOF

LuxOS Mail - recording the real Google consent screen
------------------------------------------------------
Area: ${w}x${h} at +${x}+${y} on $DISPLAY, at most ${max} s, no sound. Nothing is uploaded.

Before you start:
  * Use a TEST Gmail account that is listed under Audience -> Test users (not your personal mailbox -
    its inbox will be visible in the video).
  * Close windows with private content, turn on Do Not Disturb (no notifications in the video).
  * Open LuxOS Mail -> Add Account, type the test Gmail address, so "Sign in with Google" is visible.
  * Make the Google page English: browser language English, or pick "English (United States)"
    in the language menu at the bottom of the Google page.

While recording (slowly, ~2 s pause on each screen):
  1. click "Sign in with Google" in Mail
  2. in the browser: choose the account; the address bar must show client_id=167842547008-...
     (click into the address bar for a moment so the whole URL is visible)
  3. "Google hasn't verified this app" (while in Testing): Advanced -> Go to LuxOS Mail
  4. the consent screen: app name LuxOS Mail, the Gmail permission - tick it if there is a checkbox -> Continue
  5. "You are signed in" -> back in Mail the inbox loads
  then press any key in THIS terminal to stop.
EOF
read -rsp $'\nPress Enter to start the countdown (Ctrl+C to cancel)... ' _
echo
if ((countdown)); then
    for i in 5 4 3 2 1; do printf '\r  Recording starts in %d ...   ' "$i"; sleep 1; done
fi
# klavesy stisknute behem odpoctu nezastavi zaznam hned na zacatku
while read -rsn1 -t 0.05 _; do :; done

raw=$out/consent/consent-raw.mkv
log=$out/consent/ffmpeg.log
rm -f "$raw"
ffmpeg -loglevel error -y -f x11grab -draw_mouse 1 -framerate 30 -video_size "${w}x${h}" -i "${DISPLAY}+${x},${y}" \
    -t "$max" -c:v libx264 -preset veryfast -crf 16 -pix_fmt yuv420p "$raw" </dev/null 2>"$log" &
ff=$!
# SIGTERM: ffmpeg zaznam radne uzavre (SIGINT ma proces na pozadi skriptu ignorovany)
stop() { kill -TERM "$ff" 2>/dev/null || true; }
trap 'stop; wait "$ff" 2>/dev/null; exit 130' INT TERM
start=$(date +%s)
printf '\r  \e[1;31m● REC\e[0m  press any key in this terminal to stop                \n'
while kill -0 "$ff" 2>/dev/null; do
    if read -rsn1 -t 1 _; then
        stop
        break
    fi
    printf '\r  %3d s / %d s ' "$(( $(date +%s) - start ))" "$max"
done
wait "$ff" 2>/dev/null || true
trap - INT TERM
echo
[[ -s $raw ]] || die "recording failed: $(tail -n 5 "$log")"
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$raw")
echo "==> Recorded ${dur%.*} s: $raw"

clip=$raw
if [[ $trim != 0 ]]; then
    clip=$out/consent/consent-trimmed.mkv
    ffmpeg -loglevel error -y -ss "$trim" -i "$raw" -c:v libx264 -preset veryfast -crf 16 -pix_fmt yuv420p "$clip"
fi

# ---- 3. slozeni ---------------------------------------------------------------------------------------------
final=$out/luxos-mail-demo-final.mp4
echo "==> Assembling $final"
python3 "$here/assemble.py" "$parts" --consent "$clip" --out "$final"
cat <<EOF

Done. Check the video, then upload it yourself to YouTube as Unlisted (Neverejne) and paste the link into
Google Cloud Console -> Google Auth Platform -> Data access -> demo video. If something went wrong, run this
script again (the automated parts are kept).
  Video: $final
  Your raw recording: $raw (delete it when you are done if it shows private data)
EOF
