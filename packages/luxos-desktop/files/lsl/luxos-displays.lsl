# LuxOS - monitory (/usr/lib/luxos/luxos-displays, spousti ho /usr/bin/luxos-displays). Na Waylandu jediny
# program s pravem menit monitory (wlr-output-management, allowlist luxwm); okno nastaveni a rychla volba
# rezimu ho jen volaji. Logika a ulozeni: luxos_displays.lsl. Na X11 (bez WAYLAND_DISPLAY) get a try pro okno
# a prikazy skriptu luxos-displays (output-args, layout-args, mode-get/-set, mirror-args, rate-cap/-restore)
# dela luxos_displays_x11.lsl nad xrandr.
#
#   luxos-displays [auto]         ulozene nastaveni pro pripojenou sadu monitoru (luxwm po pripojeni nebo
#                                 odpojeni monitoru a pri startu); nova sada = rozsirit, novy monitor vpravo
#   luxos-displays extend|mirror|external|internal   rezim (Super+P), ulozi se pro sadu
#   luxos-displays mode           rezim, ktery auto pouzije
#   luxos-displays get            stav jako JSON (okno nastaveni)
#   luxos-displays set JSON       pouzit a ulozit: {"config": {...}, "primary": nazev} nebo {"mode": "mirror"}
#   luxos-displays try [-s N] JSON   pouzit, vypsat "applied" a cekat na potvrzeni: SIGUSR1 = ponechat
#                                 (ulozit, "kept"), SIGUSR2/SIGTERM nebo N s (vychozi 15) = vratit puvodni
#                                 ("reverted"); i kdyz okno nastaveni mezitim spadne
#   luxos-displays menu           rychla volba rezimu (luxos-displays-settings --menu)
# Konec: 0 ok, 1 kompozitor zmenu odmitl, 2 spatne argumenty nebo bez Waylandu/prava, 3 vraceno.
load luxos_glib, glib as glib
load json, env
load luxos_wl as wl
load luxos_luxwm as wm
load luxos_displays as dw
load luxos_displays_x11 as x11

SETTINGS = "/usr/lib/luxos/luxos-displays-settings"
X11_COMMANDS = ["output-args", "layout-args", "mode-get", "mode-set", "mirror-args", "rate-cap", "rate-restore",
                "scale-get", "scale-set"]

job = {"cmd": "", "store": None, "outs": [], "plan": None, "undo": None, "undo_primary": "", "hint": "",
       "retried": False, "after": None, "pending": False, "timer": 0}

function say(text):
    print text
end

function fail(text, code):
    call glib.report("luxos-displays: " + text + chr(10))
    call finish(code)
end

function finish(code):
    call wl.disconnect()
    exit(code)
end

function usage():
    call glib.report("usage: luxos-displays auto | extend | mirror | external | internal | mode | get | set JSON"
        + " | try [-s SECONDS] JSON | menu" + chr(10))
    exit(2)
end

# ---- luxwm: hlavni monitor ----------------------------------------------------------------------------

function luxwm_primary(f):
    if not wm.connected():
        call f("")
        return
    end
    call wm.request({"cmd": "get_state"}, luxwm_state_reply)
    job["after"] = f
end

function luxwm_state_reply(reply):
    name = ""
    safe:
        name = reply["state"]["output"]["primary"]
    end
    f = job["after"]
    job["after"] = None
    call f(String(name))
    return 0
end

function set_primary(name, f):
    if not wm.connected() or name == "":
        call f()
        return
    end
    job["after"] = f
    call wm.request({"cmd": "set_primary", "output": name}, primary_reply)
end

function primary_reply(reply):
    if reply == None or reply.get("ok") != True:
        call glib.report("luxos-displays: luxwm did not take the main display" + chr(10))
    end
    f = job["after"]
    job["after"] = None
    call f()
    return 0
end

# ---- pouziti ------------------------------------------------------------------------------------------

function run_plan(plan, done):
    job["plan"] = plan
    job["after_apply"] = done
    call dw.apply(job["outs"], plan["config"], applied)
end

function retry():
    job["outs"] = dw.read_outputs()
    call dw.apply(job["outs"], job["plan"]["config"], applied)
    return False
end

function applied(result):
    if result == 2 and not job["retried"]:
        # stav se mezitim zmenil (jiny klient, pripojeny monitor): znovu, az prijde novy stav
        job["retried"] = True
        call glib.timeout_add(100, retry)
        return
    end
    f = job["after_apply"]
    call f(result == 1)
end

# Plan ze vstupu set/try: cela konfigurace (okno nastaveni) nebo rezim
function plan_from(text):
    request = None
    safe:
        request = json.decode(text)
    end
    if type(request) != "Dictionary":
        call fail("bad JSON", 2)
    end
    mode = request.get("mode", "")
    if mode in dw.MODES:
        return dw.plan(job["store"], job["outs"], mode, job["hint"])
    end
    config = request.get("config")
    primary = request.get("primary", "")
    if type(config) != "Dictionary" or type(primary) != "String":
        call fail("need config and primary, or mode", 2)
    end
    mirror = request.get("mirror", False) == True
    problem = dw.check_config(job["outs"], config, mirror)
    if problem != "":
        call fail(problem, 2)
    end
    if dw.find(job["outs"], primary) == None or not config[primary]["enabled"]:
        call fail("main display must be enabled", 2)
    end
    return {"config": config, "primary": primary, "mode": "mirror" if mirror else "extend", "explicit": True}
end

function store_plan():
    plan = job["plan"]
    store = dw.load()
    call dw.remember(store, job["outs"], plan["config"], plan["primary"], plan["mode"], plan.get("explicit", False))
    if not dw.save(store):
        call glib.report("luxos-displays: cannot write " + dw.conf_path() + chr(10))
    end
end

# ---- prikazy ------------------------------------------------------------------------------------------

function cmd_get():
    plan = dw.plan(job["store"], job["outs"], "", job["hint"])
    found = dw.find_set(job["store"], job["outs"])
    items = []
    for o in job["outs"]:
        item = {}
        for k in ["name", "description", "enabled", "x", "y", "width", "height", "refresh", "scale", "transform",
                  "modes", "key", "internal"]:
            item[k] = o[k]
        end
        item["preferred"] = dw.preferred(o)
        if o["enabled"] and o["width"] > 0:
            item["logical"] = dw.logical(o["width"], o["height"], o["transform"], o["scale"])
        else:
            item["logical"] = [0, 0]
        end
        items.append(item)
    end
    mode = dw.detect_mode(job["outs"])
    if found[0] != None and found[0].get("mode") in dw.MODES:
        mode = found[0]["mode"]
    end
    primary = job["hint"]
    if primary == "" or dw.find(job["outs"], primary) == None:
        primary = plan["primary"]
    end
    print json.encode({"outputs": items, "primary": primary, "mode": mode, "set": dw.set_key(job["outs"]),
                       "saved": found[0] != None})
    call finish(0)
end

function cmd_mode():
    print dw.plan(job["store"], job["outs"], "", job["hint"])["mode"]
    call finish(0)
end

function cmd_apply(mode):
    call run_plan(dw.plan(job["store"], job["outs"], mode, job["hint"]), after_mode)
end

function after_mode(ok):
    if not ok:
        call fail("the compositor refused the configuration", 1)
    end
    call set_primary(job["plan"]["primary"], mode_done)
end

function mode_done():
    if job["cmd"] != "auto":
        call store_plan()
    end
    call finish(0)
end

function cmd_set(text):
    call run_plan(plan_from(text), after_set)
end

function after_set(ok):
    if not ok:
        call say("failed")
        call finish(1)
    end
    call set_primary(job["plan"]["primary"], set_done)
end

function set_done():
    call store_plan()
    call say("applied")
    call finish(0)
end

function cmd_try(text, seconds):
    job["undo"] = dw.current_config(job["outs"])
    job["undo_primary"] = job["hint"]
    job["seconds"] = seconds
    call run_plan(plan_from(text), after_try)
end

function after_try(ok):
    if not ok:
        call say("failed")
        call finish(1)
    end
    call set_primary(job["plan"]["primary"], try_wait)
end

# Signaly zachytavat driv, nez okno dostane "applied" (jinak by ho SIGUSR2 ukoncil bez vraceni)
function try_wait():
    job["pending"] = True
    call glib.unix_signal_add(10, on_keep)
    call glib.unix_signal_add(12, on_revert)
    call glib.unix_signal_add(15, on_revert)
    call glib.unix_signal_add(2, on_revert)
    job["timer"] = glib.timeout_add(job["seconds"] * 1000, on_timeout)
    call say("applied")
end

function on_keep():
    if job["pending"]:
        job["pending"] = False
        call store_plan()
        call say("kept")
        call finish(0)
    end
    return False
end

function on_timeout():
    job["timer"] = 0
    call on_revert()
    return False
end

function on_revert():
    if not job["pending"]:
        return False
    end
    job["pending"] = False
    # bez roundtripu: obsluha signalu ma vyssi prioritu nez zdroj Waylandu, ktery uz muze mit
    # pripravene cteni (wl_display_roundtrip by pak cekal navzdy); stav monitoru drzi udalosti
    job["outs"] = dw.read_outputs()
    job["retried"] = False
    call run_plan({"config": job["undo"], "primary": job["undo_primary"], "mode": ""}, after_revert)
    return False
end

function after_revert(ok):
    if not ok:
        call fail("the previous configuration could not be restored", 1)
    end
    call set_primary(job["undo_primary"], revert_done)
end

function revert_done():
    call say("reverted")
    call finish(3)
end

# ---- start ------------------------------------------------------------------------------------------

function start(hint):
    job["hint"] = hint
    cmd = job["cmd"]
    if cmd == "get":
        call cmd_get()
    elif cmd == "mode":
        call cmd_mode()
    elif cmd == "auto":
        call cmd_apply("")
    elif cmd in dw.MODES:
        call cmd_apply(cmd)
    elif cmd == "set":
        call cmd_set(job["arg"])
    elif cmd == "try":
        call cmd_try(job["arg"], job["seconds"])
    end
end

function on_deadline():
    # zaseknuty kompozitor nebo luxwm nesmi nechat pomocnika viset (try ma vlastni casovac)
    if not job["pending"]:
        call fail("timeout", 1)
    end
    return False
end

job["cmd"] = "auto"
if len(args) > 1:
    job["cmd"] = args[1]
end
job["arg"] = ""
job["seconds"] = 15
wayland = env.get("WAYLAND_DISPLAY", "")
if job["cmd"] in X11_COMMANDS or ((wayland == None or wayland == "") and job["cmd"] in ["get", "try"]):
    call x11.main(args[1:])
end
if job["cmd"] == "menu":
    settings = env.get("LUXOS_DISPLAYS_SETTINGS", "")
    if settings == "":
        settings = SETTINGS
    end
    call glib.exec([settings, "--menu"])
    call fail("cannot start " + settings, 2)
end
if job["cmd"] == "set" or job["cmd"] == "try":
    rest = args[2:]
    if len(rest) >= 2 and rest[0] == "-s":
        safe:
            job["seconds"] = max(1, min(120, Int(rest[1])))
        end
        rest = rest[2:]
    end
    if len(rest) != 1:
        call usage()
    end
    job["arg"] = rest[0]
elif job["cmd"] not in ["auto", "mode", "get"] and job["cmd"] not in dw.MODES:
    call usage()
end
call glib.unbuffered()
if not dw.connect(None):
    call fail("no Wayland output management (not allowed, or not a Wayland session)", 2)
end
job["outs"] = dw.read_outputs()
if len(job["outs"]) == 0:
    call fail("no displays", 2)
end
job["store"] = dw.load()
call glib.timeout_add(10000, on_deadline)
call wm.connect(None)
call luxwm_primary(start)
call glib.main()
