# LuxOS - pomocnik luxos-displays na X11 (drive luxos_displays.py a aplikace Monitory v Pythonu). Prikazy:
#
#   output-args                   "NAZEV argumenty xrandr" pro vystupy s ulozenym rozlisenim/frekvenci/otocenim
#                                 (overeno proti rezimum monitoru) nebo se zbylym meritkem ze zrcadleni
#   layout-args [extend]          cely prikaz xrandr podle ulozeneho rozlozeni pro pripojenou sadu (nic = neni);
#                                 "extend" (Super+P Rozsirit) zrcadleni v rozlozeni vypne a ulozi
#   mode-get | mode-set REZIM     rezim vice monitoru ulozeny pro pripojenou sadu
#   mirror-args                   prikaz xrandr pro zrcadleni (spolecne rozliseni, jinak --scale-from)
#   rate-cap | rate-restore VYSTUP REZIM FREKVENCE   Sporic baterie: vestaveny displej nejvys 60 Hz a navrat
#   get                           stav pro okno Monitory jako JSON
#   try [-s N] JSON               zkusebni pouziti z okna: {"output", "mode", "rate", "rotate"} (jeden monitor),
#                                 {"config", "primary"} (polohy a hlavni monitor) nebo {"mirror", "primary"};
#                                 provede ho skript luxos-displays auto s docasnym souborem nastaveni, pak
#                                 "applied" a ceka: SIGUSR1 = ulozit ("kept"), SIGUSR2/SIGTERM nebo N s = vratit
#                                 ulozene nastaveni ("reverted", konec 3); monitor zmenu nepouzil = "failed", 1
# Samotne zapojeni (auto, rezimy Super+P) dela skript /usr/bin/luxos-displays prikazem xrandr.
load env, json
load luxos_glib, glib as glib
load luxos_xrandr as xr

job = {"pending": False, "timer": 0, "entries": {}, "layouts": {}, "mode": "", "preview": ""}

function usage():
    call glib.report("usage: luxos-displays output-args | layout-args [extend] | mode-get | mode-set MODE"
        + " | mirror-args | rate-cap | rate-restore OUTPUT MODE RATE | get | try [-s SECONDS] JSON | scale-get | scale-set 100|125|150|175|200" + chr(10))
    exit(2)
end

function config_dir():
    return glib.user_config_dir() + "/luxos"
end

function mode_file():
    return config_dir() + "/displays-mode"
end

# Rezim jako luxos-displays auto: pro tuto sadu monitoru, posledni zvoleny, extend
function read_mode(outputs):
    mode = xr.mode_for(outputs, xr.load_modes(None))
    if mode != None:
        return mode
    end
    mode = glib.read_text(mode_file()).strip()
    if mode in xr.MODES:
        return mode
    end
    return "extend"
end

# ---- prikazy pro skript luxos-displays --------------------------------------------------------------------

function cmd_output_args():
    for line in xr.all_output_args(xr.query(), xr.load(None)):
        print line[0] + " " + " ".join(line[1])
    end
end

function cmd_layout_args(force):
    layouts = xr.load_layouts(None)
    if len(layouts) == 0:
        return 0
    end
    outputs = xr.query()
    p = xr.plan(outputs, xr.load(None), layouts, force)
    if p == None:
        return 0
    end
    if force:
        lay = xr.find_layout(layouts, outputs)[0]
        if lay.get("mirror") == True:
            lay["mirror"] = False
            call xr.save(xr.load(None), None, layouts, None)
        end
    end
    print " ".join(p["args"])
end

function cmd_mode_set(mode):
    if mode not in xr.MODES:
        call glib.report("usage: luxos-displays mode-set " + "|".join(xr.MODES) + chr(10))
        exit(2)
    end
    modes = xr.with_mode(xr.load_modes(None), xr.query(), mode)
    if modes != None:
        call xr.save(xr.load(None), None, None, modes)
    end
end

# ---- stav pro okno -----------------------------------------------------------------------------------------

ROTATION_LABELS = {"normal": "Standard", "right": "90°", "inverted": "180°", "left": "270°"}

function window_output(o):
    item = {"name": o["name"], "description": xr.edid_name(o["edid"]), "internal": xr.is_internal(o["name"]),
            "enabled": o["geometry"] != None, "x": 0, "y": 0, "width": 0, "height": 0, "refresh": 0, "scale": 1000,
            "transform": 0, "modes": [], "preferred": [0, 0, 0], "key": xr.output_key(o)}
    if o["geometry"] != None:
        # plocha vystupu (s otocenim i meritkem ze zrcadleni) jako drive current_rects
        item["width"] = o["geometry"][0]
        item["height"] = o["geometry"][1]
        item["x"] = o["geometry"][2]
        item["y"] = o["geometry"][3]
    end
    cur = xr.current_mode(o)
    item["current"] = cur[0]
    item["rate"] = cur[1]
    item["choices"] = [[c[0], xr.fmt_mode(c[0]), c[1]] for c in xr.resolution_choices(o)]
    rates = []
    md = xr.find_mode(o, cur[0]) if cur[0] != None else None
    if md != None:
        for r in md["rates"]:
            if xr.mhz(r) > 0:
                rates.append(r)
            end
        end
    end
    # od nejvyssi frekvence (stabilne jako sorted(..., reverse=True))
    ordered = []
    for r in rates:
        i = 0
        while i < len(ordered) and xr.mhz(ordered[i]) >= xr.mhz(r):
            i += 1
        end
        call ordered.insert(i, r)
    end
    item["rates"] = [[r, xr.fmt_rate(r)] for r in ordered] if len(rates) > 0 else []
    item["rotation"] = o["rotation"]
    item["rotations"] = [[r, ROTATION_LABELS[r]] for r in xr.ROTATIONS if r in o["rotations"]]
    return item
end

function cmd_get():
    outputs = xr.query()
    rects = xr.current_rects(outputs)
    primary = ""
    for o in outputs:
        if o["connected"] and o["primary"] and o["name"] in rects:
            primary = o["name"]
        end
    end
    if primary == "" and len(rects) > 0:
        primary = sorted(rects.keys())[0]
    end
    print json.encode({"x11": True, "outputs": [window_output(o) for o in xr.connected(outputs)],
                       "primary": primary, "mode": read_mode(outputs), "set": xr.set_key(outputs),
                       "text_size": xr.text_size_index(xr.read_dpi()), "scale": xr.read_scale()})
end

# ---- zkusebni pouziti ----------------------------------------------------------------------------------------

function script():
    value = env.get("LUXOS_DISPLAYS_SCRIPT", "")
    if value == None or value == "":
        return "luxos-displays"
    end
    return value
end

function preview_path():
    base = glib.user_runtime_dir()
    if base == None or base == "":
        base = config_dir()
    end
    return base + "/luxos-displays-preview.json"
end

# luxos-displays auto (s promennymi pro zkusebni soubor), synchronne
function run_auto(extra):
    call xr.run(["env"] + extra + [script(), "auto"])
end

# Polohy pro zmenu zrcadleni: ulozene rozlozeni teto sady, jinak aktualni stav
function layout_positions(outputs, layouts):
    found = xr.find_layout(layouts, outputs)
    if found[0] != None and type(found[0].get("pos")) == "Dictionary":
        pos = {}
        for key in found[1].keys():
            p = found[0]["pos"].get(key)
            if type(p) == "List" and len(p) == 2 and type(p[0]) == "Int" and type(p[1]) == "Int":
                pos[found[1][key]] = p
            end
        end
        if len(pos) == len(found[1]):
            return pos
        end
    end
    pos = {}
    rects = xr.current_rects(outputs)
    for n in rects.keys():
        pos[n] = [rects[n][0], rects[n][1]]
    end
    return pos
end

function find_output(outputs, name):
    for o in outputs:
        if o["name"] == name and o["connected"]:
            return o
        end
    end
    return None
end

function bad(text):
    call glib.report("luxos-displays: " + text + chr(10))
    exit(2)
end

function cmd_try(text, seconds):
    request = None
    safe:
        request = json.decode(text)
    end
    if type(request) != "Dictionary":
        call bad("bad JSON")
    end
    outputs = xr.query()
    entries = xr.load(None)
    layouts = xr.load_layouts(None)
    extra = []
    check = None
    if type(request.get("output")) == "String":
        o = find_output(outputs, request["output"])
        if o == None or o["geometry"] == None:
            call bad("unknown output")
        end
        mode = request.get("mode")
        md = xr.find_mode(o, mode)
        if md == None:
            call bad("unknown mode")
        end
        rate = request.get("rate")
        if type(rate) != "String" or rate == "":
            rate = xr.best_rate(md, None)
        end
        rotation = request.get("rotate", "normal")
        if rotation not in o["rotations"]:
            call bad("unsupported rotation")
        end
        e = xr.entry_for(o, mode, rate, rotation)
        key = xr.output_key(o)
        if e != None:
            entries[key] = e
        elif key in entries:
            call entries.pop(key)
        end
        check = {"output": o["name"], "mode": mode, "rate": rate, "rotate": rotation}
    else:
        primary = request.get("primary", "")
        if type(request.get("mirror")) == "Bool" and request.get("config") == None:
            pos = layout_positions(outputs, layouts)
            mirror = request["mirror"]
        else:
            config = request.get("config")
            if type(config) != "Dictionary":
                call bad("need output, config or mirror")
            end
            pos = {}
            for name in config.keys():
                c = config[name]
                if type(c) == "Dictionary" and c.get("enabled") == True and type(c.get("x")) == "Int" and type(c.get("y")) == "Int":
                    pos[name] = [c["x"], c["y"]]
                end
            end
            mirror = False
        end
        layouts[xr.set_key(outputs)] = xr.make_layout(outputs, pos, primary, mirror)
        expected = xr.plan(outputs, entries, layouts, False)
        if expected == None:
            call bad("arrangement needs two displays")
        end
        check = {"plan": expected}
        job["mode"] = "extend"
        extra = ["LUXOS_DISPLAYS_MODE=extend"]
    end
    job["entries"] = entries
    job["layouts"] = layouts
    job["preview"] = preview_path()
    # rezimy sad monitoru i do zkusebniho souboru (jinak by auto pouzilo posledni zvoleny rezim)
    call xr.save(entries, job["preview"], layouts, xr.load_modes(None))
    call run_auto(["LUXOS_DISPLAYS_CONF=" + job["preview"]] + extra)
    if not applied(xr.query(), check):
        call glib.unlink(job["preview"])
        call run_auto([])
        print "failed"
        exit(1)
    end
    job["pending"] = True
    call glib.unix_signal_add(10, on_keep)
    call glib.unix_signal_add(12, on_revert)
    call glib.unix_signal_add(15, on_revert)
    call glib.unix_signal_add(2, on_revert)
    job["timer"] = glib.timeout_add(seconds * 1000, on_revert)
    print "applied"
    call glib.main()
end

# Pouzil monitor zmenu? (xrandr muze rezim odmitnout)
function applied(outputs, check):
    if "plan" in check:
        return xr.matches(outputs, check["plan"])
    end
    o = find_output(outputs, check["output"])
    if o == None:
        return False
    end
    cur = xr.current_mode(o)
    if cur[0] != check["mode"] or o["rotation"] != check["rotate"]:
        return False
    end
    rate = check["rate"]
    return rate == None or cur[1] == None or abs(xr.mhz(cur[1]) - xr.mhz(rate)) < 50
end

function on_keep():
    if not job["pending"]:
        return False
    end
    job["pending"] = False
    modes = None
    if job["mode"] != "":
        # rozlozeni plati v rezimu "extend" (i se zrcadlenim z Usporadani)
        call glib.mkdir_p(config_dir())
        call glib.write_atomic(mode_file(), job["mode"] + chr(10))
        modes = xr.with_mode(xr.load_modes(None), xr.query(), job["mode"])
    end
    call xr.save(job["entries"], None, job["layouts"], modes)
    call xr.forget_xfce_profile()
    call glib.unlink(job["preview"])
    print "kept"
    exit(0)
end

function on_revert():
    if not job["pending"]:
        return False
    end
    job["pending"] = False
    call glib.unlink(job["preview"])
    # puvodni (ulozene) nastaveni znovu pouzije luxos-displays
    call run_auto([])
    print "reverted"
    exit(3)
end

# ---- start -----------------------------------------------------------------------------------------------------

function main(argv):
    call glib.unbuffered()
    cmd = argv[0] if len(argv) > 0 else ""
    rest = argv[1:]
    if cmd == "output-args" and len(rest) == 0:
        call cmd_output_args()
    elif cmd == "layout-args" and len(rest) <= 1:
        call cmd_layout_args(rest == ["extend"])
    elif cmd == "mode-get" and len(rest) == 0:
        mode = xr.mode_for(xr.query(), xr.load_modes(None))
        if mode != None:
            print mode
        end
    elif cmd == "mode-set" and len(rest) == 1:
        call cmd_mode_set(rest[0])
    elif cmd == "mirror-args" and len(rest) == 0:
        p = xr.mirror_plan(xr.query(), xr.load(None), xr.load_layouts(None), None)
        if p != None:
            print " ".join(p["args"])
        end
    elif cmd == "rate-cap" and len(rest) == 0:
        for line in xr.rate_cap(xr.query()):
            print " ".join(line)
        end
    elif cmd == "rate-restore" and len(rest) == 3:
        call xr.rate_restore(xr.query(), rest[0], rest[1], rest[2])
    elif cmd == "get" and len(rest) == 0:
        call cmd_get()
    elif cmd == "scale-get" and len(rest) == 0:
        print String(xr.read_scale())
    elif cmd == "scale-set" and len(rest) == 1:
        scale = 0
        safe:
            scale = Int(rest[0])
        end
        if not (scale in xr.SCALES):
            call usage()
        end
        if not xr.set_scale(scale):
            exit(1)
        end
    elif cmd == "try":
        seconds = 15
        if len(rest) >= 2 and rest[0] == "-s":
            safe:
                seconds = max(1, min(120, Int(rest[1])))
            end
            rest = rest[2:]
        end
        if len(rest) != 1:
            call usage()
        end
        call cmd_try(rest[0], seconds)
    else:
        call usage()
    end
    exit(0)
end
