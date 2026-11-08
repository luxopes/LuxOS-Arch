#!/bin/bash
# LuxOS - Plank nesmi spadnout na varovani GLib s novym radkem a neplatnym UTF-8 ani na .dockitem
# s nazvem souboru v neplatnem UTF-8.
#  - Plank 0.11.89 v Logger.glib_log_func odstranuje "\n" pres string.replace () (GRegex); na
#    neplatnem UTF-8 GRegex vrati chybu a kod z valac skonci g_assert_not_reached () -> SIGABRT
#    ("ERROR:Services/Logger.c:517:string_replace: code should not be reached"), Dock zmizi.
#  - S opravenym Loggerem by Plank dosel k ulozeni dock-items do GSettings s neplatnym UTF-8 v poli
#    retezcu -> SIGSEGV v g_variant_serialiser_needed_size. Oprava: takovy .dockitem se preskoci.
# Spousti se uvnitr session.sh:  logger_utf8.sh PRACOVNI_ADRESAR [PLANK]
set -u
w=$(readlink -f "$1"); plank=${2:-/usr/bin/plank}
launch=$XDG_CONFIG_HOME/plank/dock1/launchers
case $launch in "$w"/*) ;; *) echo "FAIL: XDG_CONFIG_HOME neni v $w"; exit 2;; esac
mkdir -p "$launch"
printf '[PlankDockItemPreferences]\nLauncher=file:///usr/share/applications/firefox.desktop\n' >"$launch/firefox.dockitem"
printf 'tohle neni key=value \377\n' >"$launch/"$'poskozeny\n\377\376.dockitem'
"$plank" >"$w/plank-logger.log" 2>&1 &
pid=$!
sleep 5
if kill -0 "$pid" 2>/dev/null; then
    # stdout Planku je do souboru blokove bufferovany - log cist az po ukonceni
    kill "$pid"; wait "$pid" 2>/dev/null
    if LC_ALL=C grep -aq "not valid UTF-8: 'poskozeny" "$w/plank-logger.log"; then
        echo "OK: Plank bezi, .dockitem s neplatnym nazvem preskocil a varovani zapsal"
        rc=0
    else
        echo "FAIL: Plank bezi, ale varovani o neplatnem nazvu v logu chybi"
        rc=1
    fi
else
    wait "$pid"; rc=$?
    echo "FAIL: Plank skoncil (rc $rc)"
    grep -aE "assert|ERROR|code should not be reached" "$w/plank-logger.log" | tail -2
    rc=1
fi
exit $rc
