# LuxOS - nazev aktivni aplikace v horni liste (jako v macOS)
#
#   luxos-appname print   vystup pro plugin genmon (pri kazdem prepnuti okna - proto v LSL, 1 ms)
#   luxos-appname watch   sleduje aktivni okno a pri zmene obnovi plugin genmon v panelu
#                         (skript /usr/lib/luxos/luxos-appname-watch, xprop -spy bez dotazovani)
load env, fd
load luxos_sys
load luxos_i18n as i18n

mode = "print"
if arg_count() > 1:
    mode = arg(1)
end
if mode == "print":
    runtime = env.get("XDG_RUNTIME_DIR", "")
    if runtime == "":
        runtime = "/tmp"
    end
    name = ""
    safe:
        name = fd.read_text(runtime + "/luxos-appname")
    end
    while name.endswith("\n"):
        name = name[0:len(name) - 1]
    end
    name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Tooltip srozumitelny pro kazdeho (prazdny by genmon nahradil technickym popisem pluginu)
    print "<txt>" + name + "</txt><tool>" + i18n.TF("Active app: %s", [name]) + "</tool>"
elif mode == "watch":
    call luxos_sys.exec(["/usr/lib/luxos/luxos-appname-watch"])
    call exit(127)
end
