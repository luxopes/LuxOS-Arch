# Headless commands, dispatched before gtk.init by the application's entry point.
load icon_model
load icon_render
load json

function run(argv):
    try:
        if len(argv) >= 2 and argv[0] == "--new" and len(argv) <= 3:
            preset = "aurora"
            if len(argv) == 3:
                preset = argv[2]
            end
            call icon_model.save(icon_model.new_project(preset), argv[1])
            print json.encode({"ok": True, "project": argv[1]})
        elif len(argv) >= 3 and argv[0] == "--render" and len(argv) <= 4:
            project = icon_model.open_project(argv[1])
            size = 512
            if len(argv) == 4:
                size = Int(argv[3])
            end
            if argv[2].lower().endswith(".svg"):
                call icon_model.atomic_text(argv[2], icon_render.svg(project, size))
            elif argv[2].lower().endswith(".png"):
                call icon_render.render_png(project, argv[2], size)
            else:
                Error(ExportError: "Choose an output file ending in .svg or .png.")
            end
            print json.encode({"ok": True, "output": argv[2], "size": size})
        elif len(argv) == 3 and argv[0] == "--export":
            paths = icon_render.export_set(icon_model.open_project(argv[1]), argv[2])
            print json.encode({"ok": True, "files": paths})
        elif len(argv) == 2 and argv[0] == "--inspect":
            print json.encode({"ok": True, "project": icon_model.open_project(argv[1])})
        else:
            print json.encode({"ok": False, "error": "Usage: luxos-icon-studio --new FILE [aurora|ember|blank] | --render PROJECT OUTPUT.svg|OUTPUT.png [SIZE] | --export PROJECT FOLDER | --inspect PROJECT"})
            return 2
        end
    else:
        print json.encode({"ok": False, "error": String(last_error())})
        return 1
    end
    return 0
end
