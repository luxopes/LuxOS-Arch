# Testovaci program pro Snimek obrazovky (spousti test_luxos_screenshot.py): jedna funkce modulu
# luxos_shot_base / luxos_shot podle prvniho argumentu, vysledek jako JSON na stdout (None = null).
#   luxos-shot-test FUNKCE ARGUMENTY...
load json
load luxos_sys
load luxos_glib
load luxos_shot_base as base
load luxos_shot as shot

function out(value):
    if value == None:
        print "null"
    else:
        print json.encode(value)
    end
    return 0
end

argv = []
index = 2
while index < arg_count():
    argv.append(arg(index))
    index += 1
end
name = arg(1)
if name == "file_name":
    call out(base.file_name([Int(argv[0]), Int(argv[1]), Int(argv[2]), Int(argv[3]), Int(argv[4]), Int(argv[5])], argv[6] == "1"))
elif name == "unique_path":
    call out(base.unique_path(argv[0], argv[1]))
elif name == "load_options":
    call out(base.load_options(argv[0]))
elif name == "save_options":
    call out(base.save_options(json.decode(argv[1]), argv[0]))
elif name == "save_dir":
    override = None
    if len(argv) > 2:
        override = argv[2]
    end
    call out(shot.save_dir(json.decode(argv[0]), argv[1] == "1", override))
elif name == "screenshots_dir":
    call out(shot.screenshots_dir())
elif name == "user_dir":
    call out(shot.user_dir(argv[0]))
elif name == "clamp_rect":
    call out(base.clamp_rect([Int(argv[0]), Int(argv[1]), Int(argv[2]), Int(argv[3])], Int(argv[4]), Int(argv[5])))
elif name == "parse_region":
    call out(base.parse_region(argv[0]))
elif name == "pretty_accel":
    call out(base.pretty_accel(argv[0]))
elif name == "global_shortcut":
    files = None
    if len(argv) > 1:
        files = argv[1:]
    end
    call out(base.global_shortcut(argv[0], files))
elif name == "pick_encoder":
    call out(base.pick_encoder(readfile(argv[0])))
elif name == "ffmpeg_cmd":
    enc = argv[7:]
    call out(base.ffmpeg_cmd(argv[0], [Int(argv[1]), Int(argv[2]), Int(argv[3]), Int(argv[4])], argv[5], enc, 30, argv[6] == "1"))
elif name == "parse_args":
    call out(base.parse_args(argv, luxos_sys.cwd()))
elif name == "canonical_args":
    call out(base.canonical_args(base.parse_args(argv, luxos_sys.cwd())))
elif name == "request":
    call out(base.request_args(base.request_text(argv)))
elif name == "request_raw":
    call out(base.request_args(argv[0].replace("\\n", "\n")))
elif name == "trash":
    call out(luxos_glib.trash_file(argv[0]))
elif name == "options_text":
    call out(base.options_text(json.decode(argv[0])))
else:
    call eprint("unknown function " + name)
    call exit(2)
end
