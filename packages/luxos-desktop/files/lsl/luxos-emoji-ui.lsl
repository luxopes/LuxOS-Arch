# LuxOS Emoji a symboly bez luxos-hub: stejne okno (modul luxos_emoji) v samostatnem procesu, ktery spousti
# luxos-emoji, kdyz hub nebezi. Po dobu behu posloucha na stejnem socketu jako hub, takze dalsi spusteni
# (stejna zkratka okno zavre) dostane tento proces; skonci, jakmile nic nedela a nedrzi schranku.
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_emoji_base as base
load luxos_emoji as emoji

SIGINT = 2
SIGTERM = 15

argv = []
index = 1
while index < arg_count():
    argv.append(arg(index))
    index += 1
end
a = base.parse_args(argv)
if "error" in a:
    call eprint(a["error"])
    call exit(1)
end
if a["help"]:
    print base.HELP
    call exit(0)
end
canon = base.canonical_args(a)
# LUXOS_EMOJI_RESIDENT=1: jen pripravene okno a socket jako v luxos-hub (testy a mereni bez hubu)
if env.get("LUXOS_EMOJI_RESIDENT", "") == "1":
    if not emoji.start_server(True):
        call eprint("luxos-emoji-ui: another instance is listening")
        call exit(1)
    end
    emoji.S["resident"] = True
    call glib.set_prgname("luxos-emoji")
    call gtk.init()
    call glib.unix_signal_add(SIGTERM, gtk.main_quit)
    call glib.unix_signal_add(SIGINT, gtk.main_quit)
    call emoji.prebuild()
    call gtk.main()
    call exit(0)
end
fallback = env.get("LUXOS_EMOJI_FALLBACK", "") == "1"
if not emoji.start_server(True) and not fallback:
    # mezitim se spustil hub nebo jina instance: predat pozadavek jim
    code = base.client_run(canon, 3000)
    if code >= 0:
        call exit(code)
    end
end
call glib.set_prgname("luxos-emoji")
call gtk.init()
call glib.unix_signal_add(SIGTERM, gtk.main_quit)
call glib.unix_signal_add(SIGINT, gtk.main_quit)
call emoji.handle_request(canon, None)
if emoji.is_visible():
    call gtk.main()
end
call exit(emoji.exit_code())
