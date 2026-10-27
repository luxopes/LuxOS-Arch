# LuxOS Snimek obrazovky - spousteci prikaz (klavesove zkratky Print, Shift+Super+3/4/5, Spoustec).
# Maly program jen s libc (start ~1 ms): prepinace preda bezicimu luxos-hub, ktery ma okna listy pripravena
# (lista je videt hned), a vypise cesty ulozenych souboru; bez hubu spusti samostatny proces
# /usr/lib/luxos/luxos-screenshot-ui se stejnym modulem (luxos_shot).
#   luxos-screenshot [--screen|--portion|--window|--record-screen|--record-portion|--stop|--close]
#                    [--clipboard] [--output DIR] [--region X,Y,W,H] [--no-thumbnail]
load env
load luxos_sys
load luxos_shot_base as base

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
code = base.client_run(canon, 3000)
if code >= 0:
    call exit(code)
end
# Nikdo neposloucha (hub nebezi) nebo neodpovedel: samostatny proces se stejnymi okny
ui = env.get("LUXOS_SCREENSHOT_UI", "")
if ui == None or ui == "":
    ui = "/usr/lib/luxos/luxos-screenshot-ui"
end
if code == -2:
    call luxos_sys.setenv("LUXOS_SCREENSHOT_FALLBACK", "1")
end
command = [ui]
command.extend(canon)
call luxos_sys.exec(command)
call eprint("luxos-screenshot: cannot start " + ui)
call exit(127)
