# LuxOS Snimek obrazovky bez luxos-hub: stejna okna (modul luxos_shot) v samostatnem procesu, ktery
# spousti luxos-screenshot, kdyz hub nebezi. Po dobu behu posloucha na stejnem socketu jako hub, takze
# dalsi spusteni (stejna zkratka, --stop) dostane tento proces; skonci, jakmile nic nedela.
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_sys
load luxos_shot_base as base
load luxos_shot as shot

SIGINT = 2
SIGTERM = 15

function on_signal():
    call shot.cancel()
    if shot.S["rec"] == None:
        call gtk.main_quit()
    end
    return True
end

argv = []
index = 1
while index < arg_count():
    argv.append(arg(index))
    index += 1
end
a = base.parse_args(argv, luxos_sys.cwd())
if "error" in a:
    call eprint(a["error"])
    call exit(1)
end
if a["help"]:
    print base.HELP
    call exit(0)
end
canon = base.canonical_args(a)
# LUXOS_SCREENSHOT_RESIDENT=1: jen pripravena okna a socket jako v luxos-hub (testy a mereni bez hubu)
if env.get("LUXOS_SCREENSHOT_RESIDENT", "") == "1":
    if not shot.start_server(True):
        call eprint("luxos-screenshot-ui: another instance is listening")
        call exit(1)
    end
    shot.S["resident"] = True
    call glib.set_prgname("luxos-screenshot")
    call gtk.init()
    call glib.unix_signal_add(SIGTERM, gtk.main_quit)
    call glib.unix_signal_add(SIGINT, gtk.main_quit)
    call shot.prebuild()
    call gtk.main()
    call exit(0)
end
fallback = env.get("LUXOS_SCREENSHOT_FALLBACK", "") == "1"
if not shot.start_server(True) and not fallback:
    # mezitim se spustil hub nebo jina instance: predat pozadavek jim
    code = base.client_run(canon, 3000)
    if code >= 0:
        call exit(code)
    end
end
call glib.set_prgname("luxos-screenshot")
call gtk.init()
call glib.unix_signal_add(SIGTERM, on_signal)
call glib.unix_signal_add(SIGINT, on_signal)
call shot.handle_request(canon, None)
if shot.S["active"] or shot.S["holding_clip"]:
    call gtk.main()
end
call exit(shot.exit_code())
