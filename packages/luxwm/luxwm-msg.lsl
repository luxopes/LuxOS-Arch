# LuxOS - luxwm-msg: prikazy pro luxwm z prikazove radky a skriptu (luxos-appearance, testy).
# Protokol: docs/developers/luxwm-ipc.md
#
#   luxwm-msg next-layout | switch-layout KOD|INDEX | switch-workspace N | set-theme light|dark
#             | reload | get-state | list-windows | focus-window ID
#   luxwm-msg --raw '{"cmd": ...}'          libovolny pozadavek, vypise odpoved
#   luxwm-msg --watch TEMA...               vypisuje udalosti (window workspace keyboard output theme)
# Konec: 0 = ok, 1 = luxwm odmitl (chyba na stderr), 2 = luxwm nebezi nebo spatne argumenty.
load glib, json
load luxos_luxwm as wm

result = {"code": 2}

function usage():
    call glib.report("usage: luxwm-msg next-layout | switch-layout CODE|INDEX | switch-workspace N | set-theme light|dark"
        + " | reload | get-state | list-windows | focus-window ID | --raw JSON | --watch TOPIC..." + chr(10))
    exit(2)
end

function number(text):
    value = None
    safe:
        value = Int(text)
    end
    return value
end

function build(words):
    cmd = words[0]
    arg = words[1] if len(words) > 1 else ""
    if cmd == "--raw" and arg != "":
        message = None
        safe:
            message = json.decode(arg)
        end
        return message
    elif cmd == "next-layout" or cmd == "reload" or cmd == "get-state" or cmd == "list-windows":
        return {"cmd": cmd.replace("-", "_")}
    elif cmd == "switch-layout" and arg != "":
        if number(arg) != None:
            return {"cmd": "switch_layout", "index": number(arg)}
        end
        return {"cmd": "switch_layout", "layout": arg}
    elif cmd == "switch-workspace" and number(arg) != None:
        return {"cmd": "switch_workspace", "number": number(arg)}
    elif cmd == "set-theme" and (arg == "light" or arg == "dark"):
        return {"cmd": "set_theme", "theme": arg}
    elif cmd == "focus-window" and number(arg) != None:
        return {"cmd": "focus_window", "window": number(arg)}
    end
    return None
end

function on_reply(reply):
    if reply.get("ok", False):
        reply.pop("id")
        reply.pop("ok")
        if len(reply) > 0:
            print json.encode(reply)
        end
        result["code"] = 0
    else:
        call glib.report("luxwm-msg: " + String(reply.get("error", "failed")) + chr(10))
        result["code"] = 1
    end
    call glib.main_quit()
    return 0
end

function on_watch_reply(reply):
    if not reply.get("ok", False):
        call glib.report("luxwm-msg: " + String(reply.get("error", "failed")) + chr(10))
        result["code"] = 1
        call glib.main_quit()
    end
    return 0
end

function on_event(event):
    print json.encode(event)
    return 0
end

function on_state(up):
    if not up:
        call glib.main_quit()
    end
    return 0
end

function on_timeout():
    call glib.report("luxwm-msg: no reply" + chr(10))
    call glib.main_quit()
    return False
end

words = args[1:]
if len(words) == 0:
    call usage()
end
if not wm.connect(on_event):
    call glib.report("luxwm-msg: luxwm is not running (" + wm.socket_path() + ")" + chr(10))
    exit(2)
end
call wm.on_state(on_state)
if words[0] == "--watch":
    if len(words) < 2:
        call usage()
    end
    # konec spojeni pri sledovani = luxwm skoncil, ne chyba prikazu
    call wm.request({"cmd": "subscribe", "events": words[1:]}, on_watch_reply)
    call glib.main()
    exit(1 if result["code"] == 1 else 0)
end
request = build(words)
if type(request) != "Dictionary":
    call usage()
end
call wm.request(request, on_reply)
call glib.timeout_add(5000, on_timeout)
call glib.main()
exit(result["code"])
