# LuxOS Emoji a symboly - spousteci prikaz (zkratky Super+. a Ctrl+Super+Mezernik, Launchpad).
# Maly program bez GTK (start ~1 ms): prepinace preda bezicimu luxos-hub, ktery ma okno pripravene predem
# (je videt hned); bez hubu spusti samostatny proces /usr/lib/luxos/luxos-emoji-ui se stejnym modulem.
#   luxos-emoji [--search TEXT | --open | --close]
load env
load luxos_sys
load luxos_emoji_base as base

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
code = base.client_run(canon, 3000)
if code >= 0:
    call exit(code)
end
if a["action"] == "close":
    call exit(0)
end
# Nikdo neposloucha (hub nebezi) nebo neodpovedel: samostatny proces se stejnym oknem
ui = env.get("LUXOS_EMOJI_UI", "")
if ui == None or ui == "":
    ui = "/usr/lib/luxos/luxos-emoji-ui"
end
if code == -2:
    call luxos_sys.setenv("LUXOS_EMOJI_FALLBACK", "1")
end
command = [ui]
command.extend(canon)
call luxos_sys.exec(command)
call eprint("luxos-emoji: cannot start " + ui)
call exit(127)
