load studio_project as projects
load studio_native as native
load studio_ui
load json
load glib

function help():
    print "LuxOS App Studio " + projects.VERSION
    print "  luxos-app-studio [PROJECTPATH]"
    print "  luxos-app-studio --new PROJECTPATH --name TITLE --id PACKAGE_NAME --type gtk|cli [--summary TEXT]"
    print "  luxos-app-studio --inspect PROJECTPATH"
    print "  luxos-app-studio --build PROJECTPATH"
    print "  luxos-app-studio --package PROJECTPATH OUTDIR"
    print "  luxos-app-studio --version | --help"
end

function main():
    if arg_count() <= 1:
        call studio_ui.run()
        return 0
    end
    command = arg(1)
    if command == "--version":
        print projects.VERSION
        return 0
    elif command == "--help" or command == "-h":
        call help()
        return 0
    elif command == "--new":
        if arg_count() < 3:
            Error(UsageError: "--new requires a project path")
        end
        values = {"--name": "My application", "--id": "my-application", "--type": "gtk", "--summary": "An application for LuxOS"}
        index = 3
        while index < arg_count():
            key = arg(index)
            if key not in values or index + 1 >= arg_count():
                Error(UsageError: "Unknown option or missing value: " + key)
            end
            values[key] = arg(index + 1)
            index += 2
        end
        result = projects.create(arg(2), values["--name"], values["--id"], values["--type"], values["--summary"])
        print json.encode(result)
        return 0
    elif command == "--inspect" or command == "--build" or command == "--package":
        required = 3
        if command == "--package":
            required = 4
        end
        if arg_count() != required:
            Error(UsageError: "Invalid arguments; use --help")
        end
        project = projects.open_project(arg(2))
        if command == "--inspect":
            print json.encode(project)
            return 0
        elif command == "--build":
            result = projects.build(project)
        else:
            result = projects.package(project, arg(3))
        end
        print json.encode(result)
        return result["status"]
    elif command.startswith("-") or arg_count() != 2:
        Error(UsageError: "Unknown command; use --help")
    end
    call studio_ui.run(command)
    return 0
end

call glib.unbuffered()
status = 0
try:
    status = main()
else:
    call glib.report("App Studio: " + String(last_error()) + "\n")
    status = 1
end
call __lsl_qbe_call1(__lsl_symbol("exit"), native.ptr(status))
