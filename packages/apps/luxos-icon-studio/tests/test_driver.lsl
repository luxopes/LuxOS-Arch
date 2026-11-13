# lsl: internal-abi
load icon_model
load icon_render
load icon_cli
load json

function action(item):
    command = item["command"]
    project = item.get("project")
    if project == None:
        project = icon_model.new_project(item.get("preset", "aurora"))
    end
    if command == "normalize":
        return icon_model.normalize(project)
    elif command == "mutate":
        added = icon_model.add_layer(project, "text")
        added["name"] = "Added"
        duplicate = icon_model.duplicate_layer(project, added["id"])
        call icon_model.move_layer(project, duplicate["id"], -100)
        call icon_model.remove_layer(project, added["id"])
        return project
    elif command == "save":
        call icon_model.save(project, item["path"])
        return icon_model.open_project(item["path"])
    elif command == "open":
        return icon_model.open_project(item["path"])
    elif command == "svg":
        return icon_render.svg(project, item.get("size", 512), item.get("background", "transparent"))
    elif command == "png":
        call icon_render.render_png(project, item["path"], item.get("size", 128))
        return True
    elif command == "import":
        layer = icon_render.import_asset(project, item["path"])
        if item.get("output"):
            call icon_render.render_png(project, item["output"], 128)
        end
        return layer
    elif command == "export":
        return icon_render.export_set(project, item["path"], item.get("basename", "icon"))
    elif command == "cli":
        return icon_cli.run(item["args"])
    end
    Error(TestError: "Unknown test action")
end

results = []
for item in json.decode(readfile(arg(1))):
    try:
        results.append({"ok": True, "value": action(item)})
    else:
        results.append({"ok": False, "error": String(last_error())})
    end
end
print json.encode(results)
