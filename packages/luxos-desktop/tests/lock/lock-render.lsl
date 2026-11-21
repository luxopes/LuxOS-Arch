# Testy: kresba zamku a prihlaseni (luxos_lock_draw) bez kompozitoru do PNG a mereni ceny snimku.
#
#   lock-render VYSTUP SIRKA VYSKA MERITKO TAPETA STAV...
# Stavy: idle prompt typed wrong caps fingerprint lockout busy greeter greeter-wrong greeter-menu.
# Vypisuje "soft <ms>" (rozmazani tapety, jednou) a za kazdy stav "frame <stav> <prumer us> <max us>" (30 snimku
# po jednom zahrivacim do obrazku ARGB32 v plnem rozliseni, jako bufer wl_shm), "fade <prumer us> <max us>" pro prolnuti a zatreseni.
load cairo, glib, env
load luxos_glib as lglib
load luxos_i18n as i18n
load luxos_material as material
load luxos_lock_draw as draw

RUNS = 30

function base_ui(mode):
    ui = draw.new_ui(mode)
    ui["clock"] = "9:41"
    ui["date"] = i18n.format_tm(lglib.gmtime(lglib.timegm(2026, 11, 20, 9, 41, 0)), "long")
    ui["battery"] = [84, False]
    ui["net"] = ["wifi", 3]
    ui["layout"] = "CZ"
    ui["name"] = "Alex Novák"
    ui["placeholder"] = i18n.T("Enter Password")
    ui["caps_text"] = i18n.T("Caps Lock is on")
    ui["reveal"] = 1.0
    ui["rev_to"] = 1.0
    return ui
end

function greeter_ui():
    ui = base_ui("greeter")
    ui["users"] = [{"real": "Alex Novák", "face": None, "other": False}, {"real": "Eva Nováková", "face": None, "other": False},
                   {"real": i18n.T("Other…"), "face": None, "other": True}]
    ui["sessions"] = ["LuxOS", "LuxOS (X11)"]
    ui["session"] = i18n.TF("Session: %s", ["LuxOS"])
    ui["power"] = [["suspend", i18n.T("Sleep")], ["reboot", i18n.T("Restart")], ["poweroff", i18n.T("Shut Down")]]
    return ui
end

function state_ui(name):
    if name.startswith("greeter"):
        ui = greeter_ui()
    else:
        ui = base_ui("lock")
    end
    if name == "idle":
        ui["reveal"] = 0.0
        ui["rev_to"] = 0.0
    elif name == "typed" or name == "busy":
        ui["length"] = 7
        ui["busy"] = name == "busy"
        ui["spin_start"] = glib.monotonic_time()
    elif name == "wrong" or name == "greeter-wrong":
        ui["hint"] = i18n.T("Incorrect password. Try again.")
        ui["error"] = True
        ui["rim"] = 1.0
    elif name == "caps":
        ui["caps"] = True
        ui["length"] = 3
    elif name == "fingerprint":
        ui["hint"] = i18n.T("Touch the fingerprint sensor or enter your password")
        ui["hint_icon"] = "fingerprint"
    elif name == "lockout":
        ui["hint"] = i18n.TF("Too many failed attempts. The account is locked for %d min, then try again.", [1])
        ui["hint_icon"] = "lock"
        ui["error"] = True
        ui["lockout"] = True
    elif name == "greeter-menu":
        ui["menu"] = True
        ui["hover"] = "menu1"
    end
    return ui
end

function measure(surface, w, h, ui, bd):
    # prvni snimek stavu plni mezipameti (pismo, avatar, tlacitka) - do prumeru nepatri
    cr = cairo.create(surface)
    call cairo.scale(cr, ui["scale"], ui["scale"])
    call draw.frame(cr, w, h, ui, bd)
    call cairo.destroy(cr)
    total = 0
    worst = 0
    for i in range(RUNS):
        cr = cairo.create(surface)
        call cairo.scale(cr, ui["scale"], ui["scale"])
        t0 = glib.monotonic_time()
        call draw.frame(cr, w, h, ui, bd)
        call cairo.surface_flush(surface)
        dt = glib.monotonic_time() - t0
        call cairo.destroy(cr)
        total = total + dt
        worst = max(worst, dt)
    end
    return [total / RUNS, worst]
end

# LOCK_RENDER_HALF=1: obrazek v polovicni logicke velikosti (vzory testu: mensi soubory, porovnani rozvrzeni)
function save(surface, path, w, h, scale):
    if env.get("LOCK_RENDER_HALF", "") == "":
        call cairo.surface_write_to_png(surface, path)
        return 0
    end
    half = cairo.image_surface_create(cairo.FORMAT_RGB24, w // 2, h // 2)
    cr = cairo.create(half)
    call cairo.scale(cr, 0.5 / scale, 0.5 / scale)
    call cairo.set_source_surface(cr, surface, 0.0, 0.0)
    call cairo.paint(cr)
    call cairo.destroy(cr)
    call cairo.surface_write_to_png(half, path)
    call cairo.surface_destroy(half)
    return 0
end

function main():
    out = arg(1)
    w = Int(arg(2))
    h = Int(arg(3))
    scale = Float(arg(4))
    wallpaper = arg(5)
    t0 = glib.monotonic_time()
    bd = draw.backdrop(wallpaper, w, h, scale)
    print "sharp " + String((glib.monotonic_time() - t0) / 1000)
    print "soft " + String(draw.backdrop_soft(bd))
    surface = cairo.image_surface_create(cairo.FORMAT_ARGB32, Int(Float(w) * scale + 0.5), Int(Float(h) * scale + 0.5))
    for i in range(6, arg_count()):
        name = arg(i)
        ui = state_ui(name)
        ui["scale"] = scale
        cost = measure(surface, w, h, ui, bd)
        print "frame " + name + " " + String(cost[0]) + " " + String(cost[1])
        call save(surface, out + "/" + name + ".png", w, h, scale)
    end
    # prolnuti klid -> zadavani a zatreseni: kazdy snimek jina hodnota
    ui = state_ui("wrong")
    ui["scale"] = scale
    total = 0
    worst = 0
    for i in range(RUNS):
        ui["reveal"] = Float(i + 1) / Float(RUNS + 1)
        ui["shake"] = Float((i % 7) - 3) * 3.0
        cr = cairo.create(surface)
        call cairo.scale(cr, scale, scale)
        t1 = glib.monotonic_time()
        call draw.frame(cr, w, h, ui, bd)
        call cairo.surface_flush(surface)
        dt = glib.monotonic_time() - t1
        call cairo.destroy(cr)
        total = total + dt
        worst = max(worst, dt)
    end
    print "fade " + String(total / RUNS) + " " + String(worst)
    for t in [0.0, 0.5, 1.0]:
        total = 0
        for i in range(RUNS):
            cr = cairo.create(surface)
            call cairo.scale(cr, scale, scale)
            t1 = glib.monotonic_time()
            call draw.background(cr, bd, t)
            call cairo.surface_flush(surface)
            total = total + glib.monotonic_time() - t1
            call cairo.destroy(cr)
        end
        print "background " + String(t) + " " + String(total / RUNS)
    end
    if env.get("LOCK_RENDER_PARTS", "") != "":
        ui = state_ui(env.get("LOCK_RENDER_PARTS", ""))
        ui["scale"] = scale
        u = draw.unit(h)
        m = draw.metrics(w, h)
        for part in ["clock", "status", "cluster", "avatar", "field", "name", "users", "power", "session"]:
            total = 0
            for i in range(RUNS):
                cr = cairo.create(surface)
                t1 = glib.monotonic_time()
                if part == "clock":
                    call draw.clock(cr, w, h, ui, u)
                elif part == "status":
                    call draw.status(cr, w, ui, u)
                elif part == "avatar":
                    call draw.avatar(cr, 960.0, 600.0, 96.0, None, "Alex", "Inter", 1.0, 1.0, 1.0)
                elif part == "field":
                    call draw.field(cr, ui, m, m["fy"])
                elif part == "name":
                    call draw.centered(cr, "Alex Novák", draw.font(ui, "Semi-Bold", 17.0), 960.0, 700.0, 1.0, 1.0)
                elif part == "users":
                    call draw.users_row(cr, w, ui, m)
                elif part == "power":
                    call draw.power_buttons(cr, w, h, ui, u)
                elif part == "session":
                    call draw.session_pill(cr, w, h, ui, u)
                else:
                    call draw.prompt_cluster(cr, w, h, ui, 1.0)
                end
                call cairo.surface_flush(surface)
                total = total + glib.monotonic_time() - t1
                call cairo.destroy(cr)
            end
            print "part " + part + " " + String(total / RUNS)
        end
    end
    return 0
end

call main()
