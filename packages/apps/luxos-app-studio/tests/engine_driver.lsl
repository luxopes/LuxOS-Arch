# Testovaci ovladac logiky App Studia bez GUI: vysledky jako JSON (tests/test_app_studio.py)
load studio_project as projects
load studio_native as native
load json

function save_details_version(project, version):
    return projects.save_details(project, project["title"], project.get("summary", "Summary"), version, "Utility")
end

function install_only(project, unused):
    return projects.install(project)
end

function attempt(handler, a, b):
    try:
        call handler(a, b)
    else:
        return String(last_error())
    end
    return ""
end

root = arg(1)
report = {}
project = projects.create(root + "/engine-app", "Engine App", "engine-app", "gtk", "First summary")

# chyby prekladace
log = "› lsl compile\n\nerror[E2001]: unknown native variable: y\n --> " + project["path"] + "/src/helpers.lsl:7:12\n  |\nerror: unexpected token\n --> /elsewhere/x.lsl:3:1\n"
report["errors"] = projects.parse_errors(log, project["path"])

# udaje aplikace
call projects.save_details(project, "Weather Lite", "Forecast at a glance", "1.2.0", "Graphics")
report["details"] = projects.details(projects.open_project(project["path"]))
report["desktop"] = readfile(project["path"] + "/package/share/applications/engine-app.desktop")
report["lux"] = json.decode(readfile(project["path"] + "/package/lux.json"))
report["bad_version"] = attempt(save_details_version, project, "1.0; rm")
report["bad_category"] = ""
try:
    call projects.save_details(project, "X", "Y", "1.0", "Nope")
else:
    report["bad_category"] = String(last_error())
end

# ikona
call writefile(root + "/icon.svg", "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"8\" height=\"8\"/>")
call writefile(root + "/fake.png", "not a png")
call writefile(root + "/note.txt", "<svg>")
report["icon_svg"] = projects.set_icon(project, root + "/icon.svg")
report["icon_fake_png"] = attempt(projects.set_icon, project, root + "/fake.png")
report["icon_txt"] = attempt(projects.set_icon, project, root + "/note.txt")
report["icon_file"] = projects.icon_file(project)

# zdrojove soubory
report["new_source"] = projects.new_source(project, "helpers")
report["new_source_again"] = attempt(projects.new_source, project, "helpers")
report["new_source_bad"] = attempt(projects.new_source, project, "../evil")
report["sources"] = projects.sources(project)

# instalace (HOME a XDG_DATA_HOME z testu)
report["install_unbuilt"] = attempt(install_only, project, 0)
built = projects.build(project)
report["built"] = built["ok"]
report["installed_files"] = projects.install(project)
report["installed"] = projects.installed(project)
report["installed_desktop"] = readfile(native.env("XDG_DATA_HOME") + "/applications/engine-app.desktop")
report["removed"] = projects.uninstall(project)
report["installed_after"] = projects.installed(project)

# cizi program se stejnym jmenem se neprepise
other = projects.create(root + "/other-app", "Other", "foreign-tool", "cli", "Other")
call projects.build(other)
call native.mkdirs(native.env("HOME") + "/.local/bin")
call writefile(native.env("HOME") + "/.local/bin/foreign-tool", "#!/bin/sh\necho mine\n")
report["foreign"] = attempt(install_only, other, 0)
report["foreign_kept"] = readfile(native.env("HOME") + "/.local/bin/foreign-tool")

# nedavne projekty
call projects.remember(project)
call projects.remember(other)
call projects.remember(project)
report["recent"] = projects.recent()
print json.encode(report)
