load studio_native as native
load json

VERSION = "1.0.0"

function valid_name(name):
    if type(name) != "String" or len(name) < 1 or len(name) > 64:
        return False
    end
    if name[0] not in "abcdefghijklmnopqrstuvwxyz0123456789":
        return False
    end
    for character in name:
        if character not in "abcdefghijklmnopqrstuvwxyz0123456789-_":
            return False
        end
    end
    return True
end

function clean_text(value, title):
    if type(value) != "String" or len(value) > 512 or "\0" in value or "\n" in value or "\r" in value:
        Error(ProjectError: title + " must be a single line of at most 512 characters.")
    end
    if not value.strip():
        Error(ProjectError: title + " must not be empty.")
    end
    return value
end

function split_destination(destination):
    if type(destination) != "String" or not destination.startswith("/") or "\0" in destination:
        Error(ProjectError: "Choose an absolute project path.")
    end
    parts = destination.split("/")
    leaf = parts[len(parts) - 1]
    if leaf == "" or leaf == "." or leaf == "..":
        Error(ProjectError: "Choose a new project folder, not an existing directory.")
    end
    for part in parts:
        if part == "." or part == "..":
            Error(ProjectError: "Project paths must not contain . or .. components.")
        end
    end
    parent = "/".join(parts[:len(parts) - 1])
    if parent == "":
        parent = "/"
    end
    return [native.canonical(parent), leaf]
end

function app_icon():
    return "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"256\" height=\"256\" viewBox=\"0 0 256 256\"><defs><linearGradient id=\"a\" x2=\"1\" y2=\"1\"><stop stop-color=\"#3265ed\"/><stop offset=\"1\" stop-color=\"#20b9ba\"/></linearGradient></defs><rect x=\"12\" y=\"12\" width=\"232\" height=\"232\" rx=\"58\" fill=\"url(#a)\"/><path d=\"M71 139l38 35 77-91\" fill=\"none\" stroke=\"white\" stroke-width=\"21\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/></svg>"
end

function source(title, kind):
    literal = json.encode(title)
    if kind == "cli":
        return "# Created with LuxOS App Studio\n\nTITLE = " + literal + "\n\nfunction main():\n    print TITLE\n    name = \"world\"\n    if arg_count() > 1:\n        name = arg(1)\n    end\n    print \"Hello, \" + name + \"!\"\n    return 0\nend\n\ncall main()\n"
    end
    return "# Created with LuxOS App Studio (native LSL + GTK 3)\n# Press Run (Ctrl+R) to build and start the app.\nload gtk\n\nTITLE = " + literal + "\napp = {\"clicks\": 0, \"label\": 0}\n\nfunction clicked(button):\n    app[\"clicks\"] = app[\"clicks\"] + 1\n    call gtk.label_set_text(app[\"label\"], \"You clicked \" + String(app[\"clicks\"]) + \" times.\")\nend\n\nfunction closed(window):\n    call gtk.main_quit()\nend\n\ncall gtk.init()\ncall gtk.css_load(\".app-title { font-size: 24px; font-weight: 700; } .app-text { opacity: 0.7; }\")\nwindow = gtk.window_new(TITLE)\ncall gtk.window_set_default_size(window, 480, 320)\n\ncolumn = gtk.box_new(gtk.VERTICAL, 12)\ncall gtk.widget_set_margin(column, 32)\ncall gtk.widget_set_valign(column, gtk.ALIGN_CENTER)\n\nheading = gtk.label_new(TITLE)\ncall gtk.widget_add_class(heading, \"app-title\")\ncall gtk.box_pack_start(column, heading, False, True, 0)\n\napp[\"label\"] = gtk.label_new(\"Edit src/main.lsl and press Run.\")\ncall gtk.widget_add_class(app[\"label\"], \"app-text\")\ncall gtk.box_pack_start(column, app[\"label\"], False, True, 0)\n\nbutton = gtk.button_new(\"Click me\")\ncall gtk.widget_add_class(button, \"suggested-action\")\ncall gtk.widget_set_halign(button, gtk.ALIGN_CENTER)\ncall gtk.connect(button, \"clicked\", clicked)\ncall gtk.box_pack_start(column, button, False, False, 8)\n\ncall gtk.container_add(window, column)\ncall gtk.connect(window, \"destroy\", closed)\ncall gtk.widget_show_all(window)\ncall gtk.main()\n"
end

CATEGORIES = ["Utility", "Development", "Graphics", "Office", "Education", "Game", "Network", "AudioVideo", "System"]

# Desktop Entry aplikace; Name/Comment jsou doslovne hodnoty (procenta plati jen pro Exec)
function desktop_entry(name, title, summary, kind, category, exec):
    terminal = "false"
    if kind == "cli":
        terminal = "true"
    end
    return "[Desktop Entry]\nType=Application\nName=" + title.replace("\\", "\\\\") + "\nComment=" + summary.replace("\\", "\\\\") + "\nExec=" + exec + "\nIcon=" + name + "\nTerminal=" + terminal + "\nCategories=" + category + ";\n"
end

function create(destination, title="My application", name="my-application", kind="gtk", summary="An application for LuxOS"):
    if not valid_name(name):
        Error(ProjectError: "Package name: use lowercase letters, digits and hyphens, beginning with a letter or digit.")
    end
    call clean_text(title, "Application title")
    call clean_text(summary, "Summary")
    if kind not in ["gtk", "cli"]:
        Error(ProjectError: "Template must be gtk or cli.")
    end
    parent, leaf = split_destination(destination)
    path = parent + "/" + leaf
    if parent == "/":
        path = "/" + leaf
    end
    if not native.mkdir(path):
        Error(ProjectError: "The project folder already exists or cannot be created. No files were overwritten.")
    end
    for sub in ["src", "build", "package/app", "package/share/applications", "package/share/icons/hicolor/scalable/apps", "exports"]:
        call native.mkdirs(path + "/" + sub)
    end
    project = {"format": 1, "name": name, "title": title, "type": kind, "summary": summary}
    call writefile(path + "/studio.json", json.encode(project) + "\n")
    call writefile(path + "/src/main.lsl", source(title, kind))
    dependencies = ["glibc"]
    if kind == "gtk":
        dependencies.append("gtk3")
    end
    metadata = {"format": 1, "name": name, "title": title, "version": "0.1.0", "release": 1, "arch": "x86_64", "summary": summary, "description": summary, "license": "MIT", "categories": ["Utility"], "depends": {"system": dependencies, "lux": []}, "bin": {name: name}}
    call writefile(path + "/package/lux.json", json.encode(metadata) + "\n")
    call writefile(path + "/package/share/applications/" + name + ".desktop", desktop_entry(name, title, summary, kind, "Utility", name))
    call writefile(path + "/package/share/icons/hicolor/scalable/apps/" + name + ".svg", app_icon())
    call writefile(path + "/README.md", "# " + title + "\n\nCreated with LuxOS App Studio.\n\nEdit `src/main.lsl` with LSL IDE or your editor, then build and run from App Studio.\n\n```sh\nluxos-app-studio --build .\nluxos-app-studio --package . exports\n```\n\nThe exported `.lux` is unsigned. Review its metadata before sharing it.\nThe application is native LSL and does not need the compiler after installation.\n\n## Icon\n\nCreate an SVG icon in LuxOS Icon Studio and replace `package/share/icons/hicolor/scalable/apps/" + name + ".svg`.\n\n## Integration\n\nMetadata lives in `package/lux.json`; the desktop entry and icon live under `package/share`.\nAdd your required system packages in `depends.system`. No installation scripts are generated.\n")
    project["path"] = path
    return project
end

function source_fingerprint(project):
    root = project["path"]
    pending = ["src"]
    entries = []
    count = 0
    while pending:
        if len(pending) + count > 2000:
            Error(ProjectError: "This project exceeds the source-tree entry limit.")
        end
        relative = pending.pop(0)
        path = root + "/" + relative
        if native.symlink(path):
            Error(ProjectError: "Source files must stay inside the project without symbolic links.")
        end
        if native.directory(path):
            for name in sorted(listdir(path)):
                pending.append(relative + "/" + name)
            end
        else:
            count += 1
            if count > 500:
                Error(ProjectError: "This project exceeds the 500 source-file limit.")
            end
            if relative.endswith(".lsl"):
                text = readfile(path)
                if len(text) > 4194304:
                    Error(ProjectError: "A source file exceeds 4 MiB.")
                end
                entries.append(relative + ":" + native.digest(text))
            end
        end
    end
    return native.digest("\n".join(sorted(entries)))
end

function build_ready(project):
    if project == None:
        return False
    end
    root = project["path"]
    path = root + "/build/" + project["name"]
    stamp = root + "/build/success.json"
    if native.symlink(root + "/build"):
        return False
    end
    if not native.exists(path) or native.symlink(path) or not native.exists(stamp) or native.symlink(stamp):
        return False
    end
    try:
        value = json.decode(readfile(stamp))
        return value.get("source") == source_fingerprint(project)
    else:
        return False
    end
end

function finish_build(project, status):
    root = project["path"]
    temporary = root + "/build/" + project["name"] + ".pending"
    if status != 0:
        call native.unlink(temporary)
        return False
    end
    if source_fingerprint(project) != project.get("_building_source"):
        call native.unlink(temporary)
        Error(ProjectError: "Source changed while building. Build again before running or exporting.")
    end
    if not native.exists(temporary) or native.symlink(temporary):
        Error(ProjectError: "The compiler did not produce the expected executable.")
    end
    bytes = readbytes(temporary)
    if len(bytes) < 4 or bytes[0] != 127 or bytes[1] != 69 or bytes[2] != 76 or bytes[3] != 70:
        call native.unlink(temporary)
        Error(ProjectError: "The compiler output is not a native ELF executable.")
    end
    call native.chmod(temporary, 493)
    if not native.rename(temporary, root + "/build/" + project["name"]):
        Error(ProjectError: "Cannot save the successfully built executable.")
    end
    call writefile(root + "/build/success.json", json.encode({"source": project["_building_source"]}) + "\n")
    return True
end

function open_project(path):
    root = native.canonical(path)
    descriptor = root + "/studio.json"
    if not native.exists(descriptor):
        Error(ProjectError: "This folder has no studio.json. Choose a project made by App Studio.")
    end
    text = readfile(descriptor)
    if len(text) > 65536:
        Error(ProjectError: "Project metadata is too large.")
    end
    project = json.decode(text)
    if type(project) != "Dictionary" or project.get("format") != 1 or not valid_name(project.get("name", "")) or project.get("type") not in ["gtk", "cli"]:
        Error(ProjectError: "Unsupported or invalid App Studio project metadata.")
    end
    call clean_text(project.get("title", ""), "Application title")
    if not native.exists(root + "/src/main.lsl"):
        Error(ProjectError: "The project is missing src/main.lsl.")
    end
    project["path"] = root
    return project
end

function prepare_build(project):
    root = project["path"]
    call native.confined_directory(root, "build")
    compiler = native.program("lsl")
    if not compiler:
        Error(ToolError: "Install the LSL compiler first: lux install lsl")
    end
    output = root + "/build/" + project["name"] + ".pending"
    if native.symlink(output):
        Error(ProjectError: "The build output must not be a symbolic link.")
    end
    call native.unlink(root + "/build/success.json")
    if native.exists(output):
        call native.unlink(output)
    end
    project["_building_source"] = source_fingerprint(project)
    return [compiler, "compile", "--unsafe", "--target", "linux-x86_64-gnu", root + "/src/main.lsl", output]
end

function prepare_package(project, destination):
    root = project["path"]
    executable = root + "/build/" + project["name"]
    if not build_ready(project):
        Error(ProjectError: "Build the application successfully before exporting a package.")
    end
    call native.confined_directory(root, "package/app")
    call native.confined_directory(root, "package/share")
    call native.mkdirs(destination)
    destination = native.canonical(destination)
    if native.symlink(root + "/package/lux.json"):
        Error(ProjectError: "Package metadata must stay inside the project.")
    end
    metadata = json.decode(readfile(root + "/package/lux.json"))
    if metadata.get("name") != project["name"] or metadata.get("format") != 1:
        Error(ProjectError: "Package metadata must match the project's package name and format.")
    end
    version = String(metadata.get("version", ""))
    for character in version:
        if character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+":
            Error(ProjectError: "The package version contains unsupported characters.")
        end
    end
    if not version or len(version) > 80 or metadata.get("arch") not in ["x86_64", "any"]:
        Error(ProjectError: "Invalid package version or architecture.")
    end
    release = metadata.get("release", 1)
    if type(release) != "Int" or release < 1 or release > 999999:
        Error(ProjectError: "The package release must be a positive integer.")
    end
    output = destination + "/" + project["name"] + "-" + version + "-" + String(release) + "-" + metadata["arch"] + ".lux"
    if native.exists(output):
        Error(ProjectError: "The exported package already exists. Choose another export folder or increment its release.")
    end
    target = root + "/package/app/" + project["name"]
    if native.symlink(target):
        Error(ProjectError: "The packaged executable must not be a symbolic link.")
    end
    call writebytes(target, readbytes(executable))
    call native.chmod(target, 493)
    lux = native.program("lux")
    if lux:
        return [lux, "pack", root + "/package", destination]
    end
    tar = native.program("tar")
    if not tar or not native.program("zstd"):
        Error(ToolError: "Install lux, or tar and zstd, to export .lux packages.")
    end
    return [tar, "-C", root + "/package", "--owner=0", "--group=0", "--numeric-owner", "--sort=name", "--mtime=@0", "--zstd", "-cf", output, "lux.json", "app", "share"]
end

function build(project):
    argv = prepare_build(project)
    job = native.spawn_logged(argv, project["path"], project["path"] + "/build/studio.log")
    status = native.wait(job)
    log = native.log_tail(job["log"])
    try:
        call finish_build(project, status)
    else:
        status = 1
        log += "\n" + String(last_error())
    end
    return {"status": status, "ok": status == 0, "log": log}
end

function package(project, destination):
    argv = prepare_package(project, destination)
    job = native.spawn_logged(argv, project["path"], project["path"] + "/build/export.log")
    status = native.wait(job)
    return {"status": status, "ok": status == 0, "log": native.log_tail(job["log"])}
end

# --- udaje aplikace (lux.json, studio.json, .desktop) -------------------------

function package_file(project, relative):
    path = project["path"] + "/" + relative
    if native.symlink(path):
        Error(ProjectError: "Package files must stay inside the project without symbolic links.")
    end
    return path
end

function details(project):
    metadata = json.decode(readfile(package_file(project, "package/lux.json")))
    category = "Utility"
    categories = metadata.get("categories", [])
    if type(categories) == "List" and len(categories) > 0 and categories[0] in CATEGORIES:
        category = categories[0]
    end
    return {"title": project["title"], "summary": project.get("summary", metadata.get("summary", "")), "version": String(metadata.get("version", "0.1.0")), "category": category}
end

function valid_version(version):
    if not version or len(version) > 80:
        return False
    end
    for character in version:
        if character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+":
            return False
        end
    end
    return True
end

function save_details(project, title, summary, version, category):
    call clean_text(title, "Application name")
    call clean_text(summary, "Summary")
    if not valid_version(version):
        Error(ProjectError: "Version: use letters, digits, dots, + and _ (for example 1.0.2).")
    end
    if category not in CATEGORIES:
        Error(ProjectError: "Unknown category.")
    end
    root = project["path"]
    metadata = json.decode(readfile(package_file(project, "package/lux.json")))
    if metadata.get("description") == metadata.get("summary"):
        metadata["description"] = summary
    end
    metadata["title"] = title
    metadata["summary"] = summary
    metadata["version"] = version
    metadata["categories"] = [category]
    call writefile(package_file(project, "package/lux.json"), json.encode(metadata) + "\n")
    stored = json.decode(readfile(package_file(project, "studio.json")))
    stored["title"] = title
    stored["summary"] = summary
    call writefile(package_file(project, "studio.json"), json.encode(stored) + "\n")
    call native.confined_directory(root, "package/share/applications")
    call writefile(package_file(project, "package/share/applications/" + project["name"] + ".desktop"), desktop_entry(project["name"], title, summary, project["type"], category, project["name"]))
    project["title"] = title
    project["summary"] = summary
    return project
end

# --- ikona -------------------------------------------------------------------

function icon_targets(project):
    return ["package/share/icons/hicolor/scalable/apps/" + project["name"] + ".svg", "package/share/icons/hicolor/256x256/apps/" + project["name"] + ".png"]
end

function icon_file(project):
    for relative in icon_targets(project):
        path = project["path"] + "/" + relative
        if native.exists(path) and not native.symlink(path):
            return path
        end
    end
    return ""
end

# Ikona aplikace z SVG nebo PNG (export z Icon Studia); druhy format se odstrani,
# aby balicek mel jedinou ikonu.
function set_icon(project, source):
    if not native.exists(source) or native.directory(source):
        Error(ProjectError: "Choose an SVG or PNG image.")
    end
    bytes = readbytes(source)
    if len(bytes) > 4194304:
        Error(ProjectError: "The icon is larger than 4 MiB.")
    end
    targets = icon_targets(project)
    lower = source.lower()
    index = 0
    if lower.endswith(".svg"):
        if "<svg" not in readfile(source):
            Error(ProjectError: "This file is not an SVG image.")
        end
    elif lower.endswith(".png"):
        if len(bytes) < 8 or bytes[0] != 137 or bytes[1] != 80 or bytes[2] != 78 or bytes[3] != 71:
            Error(ProjectError: "This file is not a PNG image.")
        end
        index = 1
    else:
        Error(ProjectError: "Choose an SVG or PNG image.")
    end
    parts = targets[index].split("/")
    call native.confined_directory(project["path"], "/".join(parts[:len(parts) - 1]))
    call writebytes(package_file(project, targets[index]), bytes)
    other = project["path"] + "/" + targets[1 - index]
    if native.exists(other) and not native.symlink(other):
        call native.unlink(other)
    end
    return project["path"] + "/" + targets[index]
end

# --- zdrojove soubory ------------------------------------------------------------

function sources(project):
    root = project["path"]
    found = []
    pending = ["src"]
    while pending and len(found) < 500:
        relative = pending.pop(0)
        path = root + "/" + relative
        if native.symlink(path):
            continue
        end
        if native.directory(path):
            for name in sorted(listdir(path)):
                if not name.startswith("."):
                    pending.append(relative + "/" + name)
                end
            end
        elif relative.endswith(".lsl"):
            found.append(relative)
        end
    end
    # main.lsl vzdy prvni
    if "src/main.lsl" in found:
        found.remove("src/main.lsl")
        found = ["src/main.lsl"] + found
    end
    return found
end

# Novy modul src/NAZEV.lsl; v main.lsl se nacte "load NAZEV"
function new_source(project, name):
    name = name.strip()
    if name.endswith(".lsl"):
        name = name[:len(name) - 4]
    end
    if not name or len(name) > 48 or name[0] not in "abcdefghijklmnopqrstuvwxyz":
        Error(ProjectError: "File name: start with a lowercase letter; use letters, digits and _.")
    end
    for character in name:
        if character not in "abcdefghijklmnopqrstuvwxyz0123456789_":
            Error(ProjectError: "File name: start with a lowercase letter; use letters, digits and _.")
        end
    end
    relative = "src/" + name + ".lsl"
    path = project["path"] + "/" + relative
    if native.exists(path):
        Error(ProjectError: "A file with this name already exists.")
    end
    call writefile(path, "# " + name + ".lsl - load it from main.lsl with: load " + name + "\n\nfunction hello():\n    return \"Hello from " + name + "\"\nend\n")
    return relative
end

# --- chyby prekladace --------------------------------------------------------------

function last_index(text, needle):
    position = -1
    start = text.find(needle)
    offset = 0
    while start >= 0:
        position = offset + start
        offset = position + len(needle)
        start = text[offset:].find(needle)
    end
    return position
end

function digits(text):
    if not text or len(text) > 9:
        return False
    end
    for character in text:
        if character not in "0123456789":
            return False
        end
    end
    return True
end

# "error[E2001]: zprava" a pod ni " --> /cesta/soubor.lsl:RADEK:SLOUPEC"
function parse_errors(log, root):
    found = []
    lines = log.split("\n")
    for index in range(len(lines)):
        line = lines[index].strip()
        if not line.startswith("--> "):
            continue
        end
        location = line[4:]
        second = last_index(location, ":")
        if second <= 0:
            continue
        end
        first = last_index(location[:second], ":")
        if first <= 0:
            continue
        end
        number_text = location[first + 1:second]
        column_text = location[second + 1:]
        if not digits(number_text) or not digits(column_text):
            continue
        end
        number = Int(number_text)
        column = Int(column_text)
        path = location[:first]
        if path.startswith(root + "/"):
            path = path[len(root) + 1:]
        end
        message = ""
        if index > 0:
            message = lines[index - 1].strip()
            colon = message.find("]: ")
            if message.startswith("error[") and colon > 0:
                message = message[colon + 3:]
            elif message.startswith("error: "):
                message = message[7:]
            end
        end
        found.append({"file": path, "line": number, "column": column, "message": message})
    end
    return found
end

# --- instalace pro tohoto uzivatele (Launchpad) ------------------------------------

function user_dirs():
    home = native.env("HOME")
    if not home.startswith("/"):
        Error(ProjectError: "HOME is not set.")
    end
    for character in "\"`$\\":
        if character in home:
            Error(ProjectError: "The home folder path contains characters a desktop entry cannot use.")
        end
    end
    data = native.env("XDG_DATA_HOME", home + "/.local/share")
    if not data.startswith("/"):
        data = home + "/.local/share"
    end
    return {"bin": home + "/.local/bin", "data": data}
end

function install_record(project):
    return user_dirs()["data"] + "/luxos/app-studio/installed/" + project["name"] + ".json"
end

function installed(project):
    return native.exists(install_record(project))
end

# Kopie sestavene aplikace do ~/.local/bin, spoustec a ikona do ~/.local/share:
# aplikace je v Launchpadu. Cizi soubory stejneho jmena se neprepisuji.
function install(project):
    if not build_ready(project):
        Error(ProjectError: "Build the application successfully before installing it.")
    end
    dirs = user_dirs()
    name = project["name"]
    target = dirs["bin"] + "/" + name
    desktop = dirs["data"] + "/applications/" + name + ".desktop"
    icon = icon_file(project)
    icon_target = ""
    if icon:
        if icon.endswith(".svg"):
            icon_target = dirs["data"] + "/icons/hicolor/scalable/apps/" + name + ".svg"
        else:
            icon_target = dirs["data"] + "/icons/hicolor/256x256/apps/" + name + ".png"
        end
    end
    record = install_record(project)
    if not native.exists(record):
        for path in [target, desktop]:
            if native.exists(path) or native.symlink(path):
                Error(ProjectError: "Another program is already installed as " + path + ". Nothing was changed.")
            end
        end
    end
    files = [target, desktop]
    for directory in [dirs["bin"], dirs["data"] + "/applications", dirs["data"] + "/luxos/app-studio/installed"]:
        call native.mkdirs(directory)
    end
    call writebytes(target + ".part", readbytes(project["path"] + "/build/" + name))
    call native.chmod(target + ".part", 493)
    if not native.rename(target + ".part", target):
        Error(ProjectError: "Cannot install " + target)
    end
    metadata = details(project)
    call writefile(desktop, desktop_entry(name, metadata["title"], metadata["summary"], project["type"], metadata["category"], "\"" + target + "\""))
    if icon_target:
        parts = icon_target.split("/")
        call native.mkdirs("/".join(parts[:len(parts) - 1]))
        call writebytes(icon_target, readbytes(icon))
        files.append(icon_target)
    end
    call writefile(record, json.encode({"files": files}) + "\n")
    return files
end

# Odstrani jen cesty, ktere instalace vytvari (zaznam se pouze kontroluje, neveri se mu)
function uninstall(project):
    record = install_record(project)
    if not native.exists(record):
        return []
    end
    dirs = user_dirs()
    name = project["name"]
    removed = []
    for path in [dirs["bin"] + "/" + name, dirs["data"] + "/applications/" + name + ".desktop", dirs["data"] + "/icons/hicolor/scalable/apps/" + name + ".svg", dirs["data"] + "/icons/hicolor/256x256/apps/" + name + ".png"]:
        if native.exists(path) and not native.directory(path):
            call native.unlink(path)
            removed.append(path)
        end
    end
    call native.unlink(record)
    return removed
end

# --- nedavne projekty ------------------------------------------------------------

function recent_file():
    config = native.env("XDG_CONFIG_HOME", native.env("HOME") + "/.config")
    return config + "/luxos/app-studio.json"
end

function recent():
    result = []
    try:
        value = json.decode(readfile(recent_file()))
        for item in value.get("recent", []):
            if type(item) == "Dictionary" and type(item.get("path")) == "String" and native.exists(item["path"] + "/studio.json"):
                result.append(item)
            end
        end
    else:
        return []
    end
    return result[:8]
end

function remember(project):
    items = [{"path": project["path"], "title": project["title"]}]
    for item in recent():
        if item["path"] != project["path"] and len(items) < 8:
            items.append(item)
        end
    end
    path = recent_file()
    parts = path.split("/")
    try:
        call native.mkdirs("/".join(parts[:len(parts) - 1]))
        call writefile(path, json.encode({"recent": items}) + "\n")
    else:
        return False
    end
    return True
end
