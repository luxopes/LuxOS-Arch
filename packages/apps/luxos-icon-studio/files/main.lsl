# LuxOS Icon Studio, native Lux Simple Lang + GTK.
load gtk
load glib
load icon_ui
load icon_cli

arguments = []
for index in rang(1, arg_count()):
    arguments.append(arg(index))
end
if arguments and arguments[0] == "--version":
    print "LuxOS Icon Studio 1.0.0"
    call exit(0)
end
if arguments and (arguments[0] == "--help" or arguments[0] == "-h"):
    print "LuxOS Icon Studio 1.0.0\nUsage: luxos-icon-studio [PROJECT.luxicon] [--lang en|cs]\n       luxos-icon-studio --new OUTPUT [aurora|blank|ember]\n       luxos-icon-studio --render INPUT OUTPUT [SIZE]\n       luxos-icon-studio --export INPUT DIRECTORY\n       luxos-icon-studio --inspect INPUT\n\nNative layered icon editor. Ctrl+N/O/S, Ctrl+Shift+S, Ctrl+Z, Ctrl+Shift+Z, Ctrl+D, Ctrl+E."
    call exit(0)
end
if arguments and arguments[0].startswith("--") and arguments[0] != "--lang":
    call exit(icon_cli.run(arguments))
end
path = ""
locale = ""
index = 0
while index < len(arguments):
    if arguments[index] == "--lang":
        index += 1
        if index >= len(arguments) or (arguments[index] != "cs" and arguments[index] != "en"):
            call eprint("--lang expects en or cs")
            call exit(2)
        end
        locale = arguments[index]
    elif not path:
        path = arguments[index]
    else:
        call eprint("Unexpected argument: " + arguments[index])
        call exit(2)
    end
    index += 1
end
call glib.set_prgname("luxos-icon-studio")
call gtk.init()
window = icon_ui.new_window(path, locale)
call gtk.main()
