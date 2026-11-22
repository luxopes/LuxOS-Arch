# Scenare protokolu luxos_wl pro test_luxos_wl.py (kompozitor labwc headless):
#   luxos-wl-test toplevels APP1 APP2   seznam, aktivace, minimalizace, zavreni
#   luxos-wl-test restore APP           Dock: minimalizace a obnoveni okna aktivaci
#   luxos-wl-test lock                  zamceni, zamykaci plocha, snimek pod zamkem, odemceni
#   luxos-wl-test lock-abandon          zamceni a konec bez odemceni (obrazovka musi zustat zamcena)
#   luxos-wl-test capture SOUBOR.png    snimek vystupu (+ snimek okna, kdyz ho kompozitor umi)
#   luxos-wl-test clip-roundtrip TEXT   nastavit a precist vlastni schranku a primarni vyber
#   luxos-wl-test clip-set TEXT         drzet schranku (do zruseni nebo 20 s)
#   luxos-wl-test clip-get              precist schranku jineho klienta
#   luxos-wl-test type TEXT             napsat text do okna s fokusem
#   luxos-wl-test keyboard              drzet virtualni klavesnici (seat s klavesnici uz pri startu oken)
#   luxos-wl-test heads                 monitory, test a pouziti nove polohy
#   luxos-wl-test idle MS               necinnost a navrat (vstup virtualni klavesnici)
#   luxos-wl-test soak N                N kol snimku a schranky; RSS na zacatku a na konci
#   luxos-wl-test unattached            vystupy a hlavy bez pripojeni (0 a 0, ne pad)
# Vystup: radky "klic hodnota"; kod 0 hotovo, 1 chyba nebo vyprseni (10 s).
load luxos_wl as wl
load glib, cairo, fd

scenario = arg(1)
param = ""
param2 = ""
if arg_count() > 2:
    param = arg(2)
end
if arg_count() > 3:
    param2 = arg(3)
end

state = {"step": 0, "count": 0, "seen": {}, "target": 0, "other": 0, "surface": 0, "capture": 0, "watch": 0}

function finish(code):
    call wl.disconnect()
    call exit(code)
end

function timeout():
    print "timeout step " + String(state["step"])
    call finish(1)
    return False
end

function rss_kb():
    for line in fd.read_text("/proc/self/status").split("\n"):
        if line.startswith("VmRSS:"):
            return Int(line[6:len(line)].strip().split(" ")[0])
        end
    end
    return 0
end

function first_output():
    outputs = wl.outputs()
    if len(outputs) == 0:
        return 0
    end
    return outputs[0]
end

# pixel ze snimku (x, y) jako "rrggbb"
function capture_pixel(capture, width, height, x, y):
    image = wl.capture_surface(capture, width, height)
    if image == 0:
        return "none"
    end
    pixel = cairo.image_surface_pixel(image, x, y)
    call cairo.surface_destroy(image)
    digits = "0123456789abcdef"
    text = ""
    for shift in [20, 16, 12, 8, 4, 0]:
        text += digits[(pixel >> shift) & 15]
    end
    return text
end

# ---- okna ----

function app_toplevel(app_id, list):
    handles = wl.toplevels()
    if list:
        handles = wl.list_toplevels()
    end
    for t in handles:
        if wl.toplevel_app_id(t) == app_id:
            return t
        end
    end
    return 0
end

function toplevels_check():
    if state["step"] == 0:
        one = app_toplevel(param, False)
        two = app_toplevel(param2, False)
        if one == 0 or two == 0 or app_toplevel(param, True) == 0 or app_toplevel(param2, True) == 0:
            return 0
        end
        for t in wl.toplevels():
            print "wlr " + wl.toplevel_app_id(t) + "|" + wl.toplevel_title(t) + "|" + String(wl.toplevel_state(t))
        end
        for t in wl.list_toplevels():
            print "ext " + wl.toplevel_app_id(t) + "|" + wl.toplevel_title(t) + "|" + String(len(wl.toplevel_identifier(t)) > 0)
        end
        state["target"] = one
        state["other"] = two
        state["step"] = 1
        # aktivovat to, ktere aktivni neni
        if wl.toplevel_state(one) & wl.STATE_ACTIVATED:
            state["target"] = two
            state["other"] = one
        end
        print "activate " + wl.toplevel_app_id(state["target"]) + " " + String(wl.activate(state["target"]))
    elif state["step"] == 1:
        if wl.toplevel_state(state["target"]) & wl.STATE_ACTIVATED:
            print "activated " + wl.toplevel_app_id(state["target"])
            state["step"] = 2
            print "minimize " + String(wl.minimize(state["other"], True))
        end
    elif state["step"] == 2:
        if wl.toplevel_state(state["other"]) & wl.STATE_MINIMIZED:
            print "minimized " + wl.toplevel_app_id(state["other"])
            state["step"] = 3
            print "close " + String(wl.close(state["target"]))
        end
    end
    return 0
end

# Dock: okno APP minimalizovat, pak obnovit aktivaci (kompozitor ho zobrazi a zameri)
function restore_check():
    t = app_toplevel(param, False)
    if t == 0:
        return 0
    end
    st = wl.toplevel_state(t)
    if state["step"] == 0:
        state["step"] = 1
        print "minimize " + String(wl.minimize(t, True))
    elif state["step"] == 1 and (st & wl.STATE_MINIMIZED):
        print "minimized"
        state["step"] = 2
        print "activate " + String(wl.activate(t))
    elif state["step"] == 2 and (st & wl.STATE_ACTIVATED) and not (st & wl.STATE_MINIMIZED):
        print "restored"
        call finish(0)
    end
    return 0
end

function on_toplevel(kind, handle):
    if kind == wl.TOPLEVEL_CLOSED and state["step"] == 3 and handle == state["target"]:
        # behem udalosti je zavrene okno jeste citelne
        print "closed " + wl.toplevel_app_id(handle)
        print "remaining " + String(len(wl.toplevels()))
        call finish(0)
    end
    if kind == wl.LIST_TOPLEVEL_CLOSED:
        print "list-closed " + wl.toplevel_app_id(handle)
    end
    call toplevels_check()
    return 0
end

# ---- zamek ----

function draw_lock(surface):
    image = wl.surface_begin(surface)
    if image == 0:
        print "no-buffer"
        call finish(1)
    end
    cr = cairo.create(image)
    call cairo.set_source_rgb(cr, 0.1, 0.2, 0.6)
    call cairo.paint(cr)
    call cairo.destroy(cr)
    call wl.surface_commit(surface, image)
    return 0
end

# heslo: klavesy dostane zamykaci plocha (fokus ma jen ona, az kdyz je zobrazena)
function type_password():
    print "typed " + String(wl.type_text("aě"))
    call glib.timeout_add(300, lock_capture)
    return False
end

function lock_capture():
    state["capture"] = wl.capture_output(first_output(), False)
    return False
end

function on_lock(kind, handle, a, b):
    if kind == wl.LOCKED:
        print "locked"
    elif kind == wl.LOCK_FINISHED:
        print "lock-finished"
        call finish(1)
    elif kind == wl.SURFACE_CONFIGURE:
        print "configure " + String(a) + "x" + String(b)
        call draw_lock(handle)
        if state["step"] == 0:
            state["step"] = 1
            if scenario == "lock-abandon":
                call glib.timeout_add(300, abandon)
            else:
                call glib.timeout_add(300, type_password)
            end
        end
    elif kind == wl.KEY:
        print "key " + String(a) + " " + String(b)
    elif kind == wl.CAPTURE_READY:
        print "pixel " + capture_pixel(handle, a, b, a // 2, b // 2)
        call wl.capture_free(handle)
        if state["step"] == 1:
            state["step"] = 2
            print "unlock " + String(wl.unlock())
            call glib.timeout_add(300, lock_capture)
        else:
            call finish(0)
        end
    elif kind == wl.CAPTURE_FAILED:
        print "capture-failed " + String(a)
        call finish(1)
    end
    return 0
end

function abandon():
    print "abandon"
    call exit(0)
    return False
end

# ---- snimek ----

function on_capture(kind, handle, a, b):
    if kind == wl.CAPTURE_READY:
        if state["step"] == 0:
            print "capture " + String(a) + "x" + String(b) + " format " + String(wl.capture_format(handle))
            print "png " + String(wl.capture_write_png(handle, a, b, param))
            print "center " + capture_pixel(handle, a, b, a // 2, b // 2)
            call wl.capture_free(handle)
            state["step"] = 1
            toplevels = wl.list_toplevels()
            if wl.has("ext_foreign_toplevel_image_capture_source_manager_v1") > 0 and len(toplevels) > 0:
                state["capture"] = wl.capture_toplevel(toplevels[0], False)
                return 0
            end
            print "toplevel-capture unsupported"
            call finish(0)
        else:
            print "toplevel-capture " + String(a) + "x" + String(b) + " " + capture_pixel(handle, a, b, a // 2, b // 2)
            call wl.capture_free(handle)
            call finish(0)
        end
    elif kind == wl.CAPTURE_FAILED:
        print "capture-failed " + String(a)
        call finish(1)
    end
    return 0
end

# ---- schranka ----

function on_clip(kind, handle, a, b):
    if kind == wl.CLIPBOARD_CHANGED:
        print "changed primary=" + String(a) + " text=" + String(b) + " types=" + ",".join(wl.clipboard_types(a == 1))
        if scenario == "clip-roundtrip" and b == 1:
            state["count"] += 1
            call wl.clipboard_request("text/plain;charset=utf-8", a == 1)
        elif scenario == "clip-get" and a == 0:
            if b != 1:
                print "no-text"
                call finish(1)
            end
            call wl.clipboard_request("text/plain;charset=utf-8", False)
        end
    elif kind == wl.CLIPBOARD_DATA:
        print "data " + String(a) + " " + String(b) + " " + wl.clipboard_text(handle)
        call wl.clipboard_free(handle)
        state["seen"][String(handle)] = True
        if scenario == "clip-get" or len(state["seen"]) == 2:
            call finish(0)
        end
    elif kind == wl.CLIPBOARD_CANCELLED:
        print "cancelled primary=" + String(a)
        if scenario == "clip-set":
            call finish(0)
        end
    end
    return 0
end

# ---- monitory ----

function print_head(head):
    info = wl.head_info(head)
    line = "head"
    for value in info:
        line += " " + String(value)
    end
    print line
    return 0
end

function on_heads(kind, handle, a, b):
    if kind == wl.OUTPUT_CONFIG_RESULT:
        print "result " + String(a)
        head = wl.heads()[0]
        info = wl.head_info(head)
        if state["step"] == 0:
            state["step"] = 1
            # skutecne pouziti: nova poloha
            call wl.output_config_begin()
            call wl.output_config_head(head, True, info[5], info[6], info[7], 200, 50, 0, 1000)
            call wl.output_config_apply(False)
        elif state["step"] == 1:
            state["step"] = 2
            # zmenu hlavy kompozitor posila pred vysledkem
            if info[3] == 200:
                call on_heads(wl.HEAD_CHANGED, head, 0, 0)
            end
        end
    elif kind == wl.HEAD_CHANGED and state["step"] == 2:
        call print_head(handle)
        call finish(0)
    end
    return 0
end

# ---- necinnost ----

function on_idle(kind, handle, a, b):
    if kind == wl.IDLE:
        print "idle " + String(glib.monotonic_time() // 1000 - state["count"])
        state["step"] = 1
        call glib.timeout_add(200, poke)
    elif kind == wl.RESUMED:
        print "resumed"
        call wl.idle_release(handle)
        call finish(0)
    end
    return 0
end

function poke():
    print "poke " + String(wl.type_text(" "))
    return False
end

function type_now():
    print "type " + String(wl.type_text(param))
    call wl.roundtrip()
    call finish(0)
    return False
end

# ---- soak ----

function soak_round():
    state["count"] += 1
    if state["count"] == 20:
        state["target"] = rss_kb()
    end
    if state["count"] > Int(param):
        print "rss " + String(state["target"]) + " " + String(rss_kb())
        call finish(0)
    end
    state["capture"] = wl.capture_output(first_output(), False)
    call wl.clipboard_set("soak " + String(state["count"]), False)
    return 0
end

function on_soak(kind, handle, a, b):
    if kind == wl.CAPTURE_READY or kind == wl.CAPTURE_FAILED:
        call wl.capture_free(handle)
    elif kind == wl.CLIPBOARD_CHANGED and b == 1:
        call wl.clipboard_request("text/plain", False)
    elif kind == wl.CLIPBOARD_DATA:
        call wl.clipboard_free(handle)
        call soak_round()
    end
    return 0
end

function event(kind, handle, a, b):
    if scenario == "toplevels":
        return on_toplevel(kind, handle)
    elif scenario == "restore":
        return restore_check()
    elif scenario == "lock" or scenario == "lock-abandon":
        return on_lock(kind, handle, a, b)
    elif scenario == "capture":
        return on_capture(kind, handle, a, b)
    elif scenario.startswith("clip"):
        return on_clip(kind, handle, a, b)
    elif scenario == "heads":
        return on_heads(kind, handle, a, b)
    elif scenario == "idle":
        return on_idle(kind, handle, a, b)
    elif scenario == "soak":
        return on_soak(kind, handle, a, b)
    end
    return 0
end

function start():
    if scenario == "toplevels":
        call toplevels_check()
    elif scenario == "restore":
        call wl.roundtrip()
        call restore_check()
    elif scenario == "lock" or scenario == "lock-abandon":
        print "outputs " + String(len(wl.outputs()))
        # klavesnice seatu driv nez zamek (headless seat zadnou nema)
        print "keyboard " + String(wl.type_text(""))
        call wl.roundtrip()
        print "lock " + String(wl.lock())
        print "surface " + String(wl.lock_surface(first_output()) > 0)
    elif scenario == "capture":
        output = first_output()
        print "output " + wl.output_name(output) + " " + String(wl.output_geometry(output))
        state["capture"] = wl.capture_output(output, False)
        print "started " + String(state["capture"] > 0)
    elif scenario == "clip-roundtrip":
        print "set " + String(wl.clipboard_set(param, False)) + " " + String(wl.clipboard_set(param + " (primary)", True))
    elif scenario == "clip-set":
        print "set " + String(wl.clipboard_set(param, False))
    elif scenario == "clip-get":
        call wl.roundtrip()
    elif scenario == "type":
        print "type " + String(wl.type_text(param))
        call wl.roundtrip()
        call finish(0)
    elif scenario == "heads":
        for head in wl.heads():
            call print_head(head)
            print "modes " + String(len(wl.head_modes(head)))
        end
        head = wl.heads()[0]
        info = wl.head_info(head)
        print "begin " + String(wl.output_config_begin())
        print "head " + String(wl.output_config_head(head, True, info[5], info[6], info[7], 100, 0, 0, 1000))
        print "test " + String(wl.output_config_apply(True))
    elif scenario == "keyboard":
        print "keyboard " + String(wl.type_text(""))
    elif scenario == "idle":
        state["count"] = glib.monotonic_time() // 1000
        state["watch"] = wl.idle_watch(Int(param))
        print "watch " + String(state["watch"] > 0)
    elif scenario == "soak":
        call soak_round()
    else:
        print "unknown scenario"
        call exit(2)
    end
    return 0
end

call glib.unbuffered()
if not wl.on_event(event):
    print "no-library"
    call exit(2)
end
# knihovna nactena, ale nepripojena (luxos-hub): dotazy na vystupy a hlavy nesmi spadnout
if scenario == "unattached":
    print "outputs " + String(len(wl.outputs())) + " heads " + String(len(wl.heads()))
    call exit(0)
end
if not wl.connect(""):
    print "no-connection"
    call exit(2)
end
limit = 10000
if scenario == "clip-set":
    limit = 20000
elif scenario == "soak":
    limit = 120000
end
call glib.timeout_add(limit, timeout)

call start()
call glib.main()
