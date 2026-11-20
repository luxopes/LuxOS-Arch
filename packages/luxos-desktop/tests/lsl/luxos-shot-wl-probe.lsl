# Pomocny klient pro test_luxos_shot_wl.py a test_luxos_emoji_wl.py (vlastni spojeni, bez GTK):
#   luxos-shot-wl-probe clip     ceka na obrazek ve schrance: "types ..." a "png DELKA", pak schranku
#                                prevezme textem (drzitel obrazku ma skoncit) a skonci
#   luxos-shot-wl-probe text     ceka na text ve schrance ("text ..."), pak ji prevezme a skonci
#   luxos-shot-wl-probe globals  vypise, ktere privilegovane globaly vidi ("has NAZEV VERZE")
load luxos_wl as wl
load glib

scenario = arg(1)
state = {"asked": False}

function timeout():
    print "timeout"
    call exit(1)
    return False
end

function done():
    call wl.disconnect()
    call exit(0)
    return False
end

function event(kind, handle, a, b):
    if kind == wl.CLIPBOARD_CHANGED and a == 0 and not state["asked"]:
        types = wl.clipboard_types(False)
        if scenario == "text" and b == 1:
            state["asked"] = True
            call wl.clipboard_request("text/plain;charset=utf-8", False)
        elif scenario == "clip" and "image/png" in types:
            state["asked"] = True
            print "types " + ",".join(types)
            call wl.clipboard_request("image/png", False)
        end
    elif kind == wl.CLIPBOARD_DATA:
        if scenario == "text":
            print "text " + wl.clipboard_text(handle)
        else:
            print "png " + String(a) + " " + String(b)
        end
        call wl.clipboard_free(handle)
        call wl.clipboard_set("probe", False)
        call glib.timeout_add(300, done)
    end
    return 0
end

call glib.unbuffered()
if not wl.on_event(event) or not wl.connect(""):
    print "no-connection"
    call exit(2)
end
if scenario == "globals":
    for name in ["ext_image_copy_capture_manager_v1", "ext_output_image_capture_source_manager_v1",
            "ext_foreign_toplevel_image_capture_source_manager_v1", "ext_foreign_toplevel_list_v1",
            "ext_data_control_manager_v1", "zwp_virtual_keyboard_manager_v1"]:
        print "has " + name + " " + String(wl.has(name))
    end
    call exit(0)
end
call glib.timeout_add(10000, timeout)
call glib.main()
